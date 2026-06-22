# 多线程渲染:帧流水线、双/三缓冲、GL 多线程限制

> 你完成单线程渲染器,144 Hz 显示器上跑出 60 FPS——CPU 一边算游戏逻辑一边等 GPU 画完,两个核心互相干等。现代 CPU 8 核起跳,你应该让它们一起干活。但 GPU 渲染有自己的时序,不能简单地"多线程上 GPU"。本文讲清楚为什么"GPU 命令缓冲"和"帧缓冲"是两个独立的多线程机制,以及 OpenGL 为什么那么难多线程化。

## 0 · 为什么渲染需要多线程

游戏主循环看起来极简:

```
loop {
    process_input();
    update_game();           // CPU 工作 1:逻辑
    render_setup();          // CPU 工作 2:准备渲染数据
    gpu_render();            // GPU 工作:画
    swap_buffers();          // 等 GPU 完成
}
```

这个循环里,**CPU 和 GPU 串行**:

- CPU 算逻辑时,GPU 闲着
- GPU 渲染时,CPU 闲着(只能等 swap_buffers)
- 一帧的总时间 = CPU 时间 + GPU 时间,而不是 max(CPU, GPU)

这就是为什么你的 i9 跑不出 144 FPS——CPU 时间 + GPU 时间 > 1/144 秒。

**多线程渲染的核心目标**:让 CPU 和 GPU **重叠工作**。当 GPU 渲染第 N 帧时,CPU 在算第 N+1 帧。

但这件事比想象复杂,因为:

1. **GPU 命令不是立即执行的**——CPU 提交命令到队列,GPU 异步消费
2. **帧缓冲(framebuffer)不能在 GPU 还在画时被覆盖**——需要多缓冲
3. **OpenGL 是单线程 API**(从 API 角度)——同一个 context 不能多线程调用
4. **同步原语**(fence、semaphore)的开销和正确性

**读完这一篇你能**:
- 写出双缓冲和三缓冲渲染循环
- 解释为什么 OpenGL 单 context 不能多线程,而 Vulkan 可以
- 知道什么时候用 deferred rendering(延迟渲染)
- 看 bevy / filament / unreal 的多线程渲染架构不被吓到

## 1 · 帧流水线:核心抽象

### 单线程基线

```
帧 N:
  CPU: [input | update | render_setup]
  GPU:                                  [render | swap]
  
  时间: ────────────────────────────────────────────►
  
  CPU 和 GPU 完全不重叠,一帧时间 = CPU + GPU
```

### 双缓冲

```
帧 N:
  CPU: [input | update | render_setup_N]
  GPU: [render_N-1]                     [render_N | swap]
  
  时间: ────────────────────────────────────────────►
  
  CPU 算 N 帧时,GPU 画 N-1 帧——重叠 1 帧。
```

CPU 不等 GPU 完成,立即开始下一帧的 CPU 工作。GPU 会在自己时间线上"追"CPU 提交的命令。

但 GPU 比 CPU 慢的话,CPU 提交太多命令,显存爆;CPU 比 GPU 慢的话,GPU 闲着。

### 三缓冲

```
帧 N:
  CPU: [update_N]
  GPU:           [render_N-1]           [render_N-2 ─ swap]
  
  时间: ────────────────────────────────────────────►
  
  GPU 可以晚两帧开始,CPU 更不受 GPU 拖累。
```

三缓冲让"CPU 提交"和"GPU 渲染"完全解耦,代价是输入延迟增加 2 帧(33ms @ 60FPS)。

### 缓冲数选择的取舍

| 缓冲数 | CPU/GPU 重叠 | 输入延迟 | 适用场景 |
|---|---|---|---|
| 1(单缓冲) | 无 | 0 | 教学示例 |
| 2(双缓冲) | 1 帧 | ~16ms | 竞技游戏(低延迟) |
| 3(三缓冲) | 2 帧 | ~33ms | 大多数游戏 |
| 4+ | N-1 帧 | ~50ms+ | VR(给 GPU 大缓冲)|

竞技游戏(CS:GO、Valorant)选双缓冲,因为输入延迟是核心体验;3A 大作选三缓冲,因为画质优先。VR 至少 3-4 缓冲,因为帧率要求 90+ 且姿态预测需要缓冲。

## 2 · 实现双缓冲的两种方式

### 方式 1:FBO 双缓冲

CPU 准备两个 framebuffer(FBO A, FBO B)。第 N 帧画到 A,第 N+1 帧画到 B,GPU 永远在画前一个 FBO。

```rust
let fbos = [create_fbo(), create_fbo()];
let mut frame_idx = 0;

loop {
    let current_fbo = fbos[frame_idx % 2];
    render_to(current_fbo);
    frame_idx += 1;
}
```

但屏幕(默认 framebuffer)只有一个——你不能在 GPU 还画前一张时换显示。**swap buffers** 这个 API 就是解决这个问题:GPU 内部交换 front/back buffer,屏幕显示新的,GPU 画到新的空 buffer。

### 方式 2:Vulkan 的多帧并行

Vulkan 原生支持多帧并行:你提交 frame N 的命令缓冲,GPU 异步执行;同时 CPU 可以构建 frame N+1 的命令缓冲。Vulkan 显式要求**至少 2 帧在 fly**(用 swapchain image count 控制)。

```rust
let swapchain = create_swapchain(image_count: 3);  // 三缓冲

loop {
    let image_idx = acquire_next_image(&swapchain);  // 等可写的 image
    let cmd = build_command_buffer(image_idx);       // CPU 构建命令
    submit(cmd);                                      // 提交给 GPU 队列
    present(image_idx);                               // 显示
}
```

CPU 和 GPU 完全异步,通过 fence 和 semaphore 同步。

## 3 · OpenGL 多线程:为什么那么难

### OpenGL 的 Context 模型

OpenGL 的所有状态(绑定的 shader、texture、buffer 等)都在一个**Context** 里。一个线程同时只能有一个 current context。

```c
// 线程 A
wglMakeCurrent(dc, ctx);   // ctx 在线程 A
glDrawArrays(...);          // OK

// 线程 B(同时)
wglMakeCurrent(dc, ctx);   // 失败!ctx 已经在线程 A
```

Context 是**线程亲和**(thread-affine)的。

### 多线程 OpenGL 的几种方案

**方案 A:单线程,所有 GL 调用都在主线程**(简单,但 CPU 闲)。

**方案 B:多线程,每个线程一个独立 context**。

```c
// 主线程
wglMakeCurrent(dc, ctx_main);
// 渲染...

// 工作线程
wglMakeCurrent(NULL, ctx_worker);  // 不绑定到任何窗口 DC
// 后台加载纹理到 PBO(buffer object)
```

工作线程做资源加载(纹理、模型),不能调用绘制命令。和主线程共享资源需要 wglShareLists 或 GL_SHARE_CONTEXT(平台 API)。

**方案 C:单线程渲染,多线程准备数据**(主流)。

```
线程 1: 主循环(逻辑 + 输入)
线程 2: 资源加载(解码 PNG、加载 OBJ)
线程 3: 渲染线程(GL 调用全在这里)
线程 4: 音频
```

所有线程通过 channel 通信,渲染线程消费主线程的"渲染命令"。这是 Casey Handmade Hero 的架构,也是大量游戏引擎的基础。

## 4 · Vulkan/D3D12/Metal:显式多线程

新一代 API(Vulkan、D3D12、Metal)从设计之初就是多线程友好的:

- **Command Buffer**:CPU 在任何线程构建命令缓冲(thread-local),最后提交到 queue
- **Descriptor Sets** 可重用,不用每帧重建
- **Pipeline State Object**:预编译的 pipeline,运行时直接绑定

Vulkan 渲染循环(多线程版):

```rust
// 主线程
loop {
    // 1. 准备 frame 数据(多线程)
    let updates = parallel_collect_updates();  // rayon
    
    // 2. 每个 draw call 一个线程构建 command buffer
    let cmd_buffers: Vec<CommandBuffer> = draw_calls
        .par_iter()
        .map(|call| build_cmd_buffer(call, &updates))
        .collect();
    
    // 3. 提交到 queue
    queue.submit(&cmd_buffers);
    queue.present();
}
```

每个线程构建自己的 command buffer,最后 batch 提交。Vulkan 提交命令的开销比 OpenGL 低得多,因为驱动不需要在线程间同步状态。

## 5 · 双线程架构(渲染线程 + 主线程)

### Handmade Hero 的架构

Casey 在 Day 100+ 把平台层和游戏逻辑解耦:

```
主线程(平台层):
  - 处理消息(窗口、输入)
  - 调用 game_update_and_render(游戏逻辑)
  - 把 framebuffer 复制到屏幕
  - 音频在另一个线程

工作线程:
  - 后台加载资产
  - 解码 PNG/Ogg
```

这是单 GL 线程 + 多工作线程的方案。GL 调用全在主线程。

### Bevy / Filament 的架构

现代 Rust 引擎更进一步:

```
主线程:
  - ECS 调度(多线程,rayon)
  - 子系统并行(input、physics、audio)

渲染线程:
  - 独立线程,接收"渲染指令"
  - 调用 GL/Vulkan
  - 通过 channel 和主线程同步

资源加载线程:
  - 加载 PNG/OBJ/glTF
  - 解码后通过 channel 发到渲染线程
```

主线程不阻塞渲染——这就是为什么 Bevy 能用 ECS 让 16 线程并行更新。

## 6 · 同步原语

### Fence

GPU 完成某段命令后,fence 触发。CPU 可以等 fence:

```rust
let fence = device.create_fence();
queue.submit(cmd, Some(&fence));
device.wait_for_fences(&[&fence], true, u64::MAX);  // CPU 阻塞等待 GPU
```

### Semaphore

GPU 内部的信号量,用于 GPU 队列之间同步:

```rust
let img_available = device.create_semaphore();
let render_done = device.create_semaphore();

// 队列 A:acquire image,触发 img_available
acquire_next_image(&swapchain, &img_available);

// 队列 B:等 img_available,渲染,触发 render_done
submit(cmd, wait: &[&img_available], signal: &[&render_done]);

// 队列 C:等 render_done,present
present(&swapchain, wait: &[&render_done]);
```

### Barrier(管线屏障)

同一个 command buffer 内的内存屏障,保证"前一阶段写完才能被后一阶段读"。

```rust
cmd.pipeline_barrier(
    src_stage: COLOR_ATTACHMENT_OUTPUT,
    dst_stage: FRAGMENT_SHADER,
    // image layout 转换 + 内存可见性
);
```

Vulkan/D3D12 里几乎所有渲染状态切换都需要 barrier,显式管理是性能关键。

## 7 · Rust 多线程渲染实战

### 简化架构:主线程 + 渲染线程

```rust
use std::sync::mpsc::{channel, Sender, Receiver};
use std::thread;

// 渲染命令(主线程 → 渲染线程)
enum RenderCommand {
    DrawMesh { mesh_id: u32, transform: Mat4 },
    UpdateBuffer { buffer_id: u32, data: Vec<u8> },
    Resize { width: u32, height: u32 },
    Quit,
}

struct RenderThread {
    sender: Sender<RenderCommand>,
    handle: thread::JoinHandle<()>,
}

impl RenderThread {
    fn spawn() -> Self {
        let (tx, rx) = channel::<RenderCommand>();
        let handle = thread::spawn(move || {
            Self::run(rx);
        });
        Self { sender: tx, handle }
    }
    
    fn run(rx: Receiver<RenderCommand>) {
        // 初始化 OpenGL context(必须在渲染线程)
        let gl_context = create_gl_context_on_this_thread();
        let gl = unsafe { glow::Context::from_loader_function(...) };
        
        loop {
            // 等 / 收命令
            let cmd = match rx.recv() {
                Ok(c) => c,
                Err(_) => break,  // 主线程挂了
            };
            
            match cmd {
                RenderCommand::DrawMesh { mesh_id, transform } => {
                    // 调用 GL
                    unsafe {
                        gl.bind_vertex_array(...);
                        gl.draw_elements(...);
                    }
                }
                RenderCommand::UpdateBuffer { buffer_id, data } => {
                    // 上传数据
                    unsafe {
                        gl.named_buffer_sub_data(buffer_id, 0, &data);
                    }
                }
                RenderCommand::Resize { width, height } => {
                    unsafe { gl.viewport(0, 0, width as i32, height as i32); }
                }
                RenderCommand::Quit => break,
            }
            
            // swap buffers(必须在此线程)
            gl_context.swap_buffers();
        }
    }
    
    fn send(&self, cmd: RenderCommand) {
        self.sender.send(cmd).unwrap();
    }
}

// 主线程
fn main() {
    let render_thread = RenderThread::spawn();
    
    // 主循环
    loop {
        let input = process_input();
        let game_state = update_game(input);
        
        // 提交渲染命令
        for draw_call in game_state.draws {
            render_thread.send(RenderCommand::DrawMesh {
                mesh_id: draw_call.mesh,
                transform: draw_call.transform,
            });
        }
        
        if should_quit() {
            render_thread.send(RenderCommand::Quit);
            break;
        }
    }
    
    // 等渲染线程退出
    render_thread.handle.join().unwrap();
}
```

每段注释:

- `mpsc::channel` — 多生产者单消费者通道,主线程发,渲染线程收
- `glow::Context::from_loader_function` — 在渲染线程创建 GL context(必须!GL context 亲和线程)
- `rx.recv()` 阻塞等命令
- 主线程不调用任何 GL 函数——所有 GL 都在渲染线程

## 8 · 渲染线程的同步陷阱

### 陷阱 1:资源竞争

```rust
// 错误:主线程改 vertex buffer,渲染线程正在用
render_thread.send(RenderCommand::UpdateBuffer { ... });
// 渲染线程还没消费这条命令,主线程又改了同一 buffer → 数据竞争
```

解决:**双缓冲数据**。一个 buffer 当前帧用,另一个 buffer 准备下一帧。

### 陷阱 2:帧延迟

主线程提交"第 N 帧渲染命令",但渲染线程可能还在画"第 N-1 帧"。游戏逻辑看到的"状态"和画面上的"状态"差一帧——鼠标响应延迟。

解决:**预输入预测**(input prediction)和**插值渲染**(interpolation)。多人游戏都做这个。

### 陷阱 3:Context Loss

窗口大小变化、电源模式切换、显卡热切换都可能丢 context。渲染线程要能重建。

## 9 · 性能分析:多线程能提多少 FPS

理想情况下双缓冲:FPS ≈ 1 / max(CPU_time, GPU_time),从 1/(CPU + GPU) 提升。

但实际收益取决于:

- **GPU 瓶颈**:如果 GPU 比 CPU 慢,多线程救不了——你需要简化 shader 或降低分辨率
- **CPU 瓶颈**:如果 CPU 比 GPU 慢,多线程能直接提速
- **驱动开销**:OpenGL 调用驱动开销大,Vulkan 更低

工业界例子:Casey 的 Handmade Hero 在双线程下从 60FPS 提到 144FPS——CPU 瓶颈解除。

## 10 · 历史

- 1990s:OpenGL 单线程,游戏在单 CPU 上跑
- 2000s:多核 CPU 出现,游戏开始用"工作线程 + 主线程"
- 2010s:D3D11 引入 deferred context,OpenGL 4 多线程能力受限
- 2016:Vulkan 1.0 发布,显式多线程
- 2020s:Vulkan / D3D12 / Metal 成主流;移动端也跟随

## 11 · 关联 Day

- **铺垫**:Day 100+ 线程池;Day 150 内存分配器(线程局部);Day 200 渲染线程基础
- **当天**:本篇是多线程渲染专题
- **后续**:Day 480+ Vulkan 化;Day 500+ GPU driven rendering

## 12 · 变式训练

### Lv1 · 概念辨析

**题**:为什么 OpenGL 的 context 必须线程亲和,而 Vulkan 的 command buffer 可以多线程构建?

**参考解答**:OpenGL 用**隐式状态机**——`glBindTexture`、`glUniform` 都改一个隐式的全局状态。如果多线程同时调用,状态互相覆盖,无法预测。Vulkan 用**显式状态**——command buffer 是不可变的数据结构,构建时无副作用,可以多线程并行构建。提交到 queue 后,驱动按顺序执行。Vulkan 把"构建命令"和"执行命令"分开,前者线程无关,后者串行(在 queue 里)。

### Lv2 · 动手实践

**题**:把你的单线程渲染器改成"主线程 + 渲染线程"双线程架构。要求:输入响应在主线程,所有 GL 调用在渲染线程。

完成标准:窗口能正常关闭,GL 调用全在渲染线程(用 `panic_if_not_render_thread()` 验证)。

**参考解答**:见上面的 Rust 代码骨架。关键点:
1. 在渲染线程创建 GL context(用 `winit` + `glutin` 时,window 也要在该线程创建)
2. 主线程通过 channel 发送渲染命令
3. 渲染线程无限循环收命令、调用 GL、swap buffers

### Lv3 · 迁移设计

**题**:你的游戏要从 OpenGL 迁到 Vulkan。架构上有哪些变化?render loop 写法呢?

**提示**:Vulkan 没有"隐式状态",每个状态切换都要 explicit。frame loop 从 `loop { gl.draw... }` 变成 `loop { acquire_image → build_cmd → submit → present }`,每步都有显式同步。

### Lv4 · 开源贡献

**题**:wgpu 是 Rust 主流跨平台图形抽象,GitHub: https://github.com/gfx-rs/wgpu

1. clone 它
2. 看 `wgpu/src/backend/direct.rs`(单线程)和 `wgpu/src/backend/remote.rs`(多线程)
3. 理解它的 "threadless" 模式
4. 可能的贡献:加一个示例展示多线程渲染 / 文档改进

## 13 · Rust / Arch 落地代码

完整的多线程渲染器骨架(用 winit + glow):

```rust
// Cargo.toml:
// [dependencies]
// winit = "0.30"
// glow = "0.14"
// glam = "0.29"

use std::sync::mpsc::{channel, Sender, Receiver};
use std::thread;
use winit::event::{Event, WindowEvent};

enum RenderMsg {
    Init { window: winit::window::Window },  // 把 window 移交到渲染线程
    Resize { width: u32, height: u32 },
    Draw { frame_data: FrameData },
    Quit,
}

struct FrameData {
    pub camera: Mat4,
    pub draws: Vec<DrawCall>,
}

fn main() {
    let (tx, rx) = channel::<RenderMsg>();
    
    // 渲染线程
    let render_handle = thread::spawn(move || {
        render_thread_main(rx);
    });
    
    // 主线程
    let event_loop = winit::event_loop::EventLoop::new();
    let window = winit::window::Window::new(&event_loop).unwrap();
    
    tx.send(RenderMsg::Init { window }).unwrap();
    
    event_loop.run(move |event, _| {
        match event {
            Event::WindowEvent { event: WindowEvent::Resized(size), .. } => {
                tx.send(RenderMsg::Resize {
                    width: size.width,
                    height: size.height,
                }).unwrap();
            }
            Event::MainEventsCleared => {
                // 主线程跑游戏逻辑
                let frame_data = compute_frame();
                tx.send(RenderMsg::Draw { frame_data }).unwrap();
            }
            Event::WindowEvent { event: WindowEvent::CloseRequested, .. } => {
                tx.send(RenderMsg::Quit).unwrap();
            }
            _ => {}
        }
    });
    
    render_handle.join().unwrap();
}

fn render_thread_main(rx: Receiver<RenderMsg>) {
    let mut gl: Option<glow::Context> = None;
    
    while let Ok(msg) = rx.recv() {
        match msg {
            RenderMsg::Init { window } => {
                // 创建 GL context(必须在渲染线程)
                let ctx = unsafe {
                    glow::Context::from_loader_function(|_| {
                        panic!("需要真实 GL loader");
                    })
                };
                gl = Some(ctx);
                
                // window 在此线程,事件循环也在(简化)
            }
            RenderMsg::Resize { width, height } => {
                if let Some(ref gl) = gl {
                    unsafe { gl.viewport(0, 0, width as i32, height as i32); }
                }
            }
            RenderMsg::Draw { frame_data } => {
                if let Some(ref gl) = gl {
                    render_frame(gl, &frame_data);
                }
            }
            RenderMsg::Quit => break,
        }
    }
}

fn render_frame(gl: &glow::Context, _frame: &FrameData) {
    // 所有 GL 调用都在渲染线程
}
```

Arch 工具链:

```bash
# 性能调试
sudo pacman -S renderdoc    # 抓帧分析
sudo pacman -S gpu-viewer   # OpenGL 信息
sudo pacman -S mesa-utils

# 用 Renderdoc 看多线程:
# 1. 抓一帧
# 2. Timeline tab 看每个线程的 GL 调用时间
# 3. 找"主线程和渲染线程重叠"区域

# CPU profile
sudo pacman -S valgrind
valgrind --tool=callgrind ./my_game
# 输出 callgrind.out.<pid>
kcachegrind callgrind.out.1234   # GUI 分析

# GPU profile(NVIDIA)
sudo pacman -S nvidia-utils
nvidia-smi -l 1                   # 每秒看 GPU 使用率
# 输出:GPU-Util 80%, Memory-Usage 500MiB / 8000MiB
```

排错:

```bash
# 1. "OpenGL context is not current on this thread"
#    原因:GL 调用不在创建 context 的线程
#    解决:把所有 GL 调用放到同一个线程

# 2. "TLS(TLS = thread local storage)破坏"
#    原因:GL context 用 TLS 存状态,跨线程访问无效
#    解决:同上

# 3. 渲染卡顿(每秒掉几帧)
#    原因:主线程发命令太快,渲染线程积压;或反之
#    解决:用 mpsc::sync_channel(N) 限制缓冲(背压)

# 4. swap_buffers 卡住
#    原因:VSync 启用,GPU 等 VSync 信号
#    解决:禁用 VSync 测试,或换 mailbox mode(Vulkan)
```

## 14 · 延伸阅读

本仓库本地:

- `days/phase-4/deep-dives/`(若存在)— 线程池
- `days/phase-6/deep-dives/texture-compression.md` — 多线程资源加载

外部稳定 URL:

- Vulkan Multi-threading: https://vulkan-tutorial.com/Drawing_a_frame/Rendering_and_presentation
- Filament 渲染架构: https://google.github.io/filament/Filament.html
- GPU Open Multithreading: https://gpuopen.com/learn/multithreading-vulkan/
- LearnOpenGL Advanced: https://learnopengl.com/Advanced-OpenGL/Instancing

真实开源源码:

- Filament 渲染线程: https://github.com/google/filament/blob/main/filament/src/Renderer.cpp
- Bevy 渲染: https://github.com/bevyengine/bevy/blob/main/crates/bevy_render/src/lib.rs
- bgfx 多线程: https://github.com/bkaradzic/bgfx/blob/master/src/renderer_vk.cpp
