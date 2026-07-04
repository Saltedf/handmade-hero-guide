
# Bridge · 从 Phase 4 到 Phase 5

> 你刚把 Phase 4 走完。64 天。你的代码现在能 SIMD 加速、能多核并行、能用 arena 分配内存、能用 .hha 打包资产、能渲染 TrueType 字体。Phase 3 写的软件渲染器,经过 Phase 4 优化,从 30 FPS 跑到稳定 60+ FPS。你心想:CPU 这块我已经榨干了。然后呢?——然后就是:**该上 GPU 了**。Phase 5 是 Handmade Hero 全程"工具栈切换"最大的一段——过去 175 天你只用 CPU,Phase 5 开始你**同时用 CPU 和 GPU**,通过 OpenGL 接口让 GPU 帮你算。本文是过桥指南。

## §0 · 你已经走过的路

Phase 4 的 64 天,你完成了"工程化"的六个核心子问题。按时间顺序复盘:

- **Day 112-121**:SIMD + 性能心智。Tracy profiler 日常使用。`std::arch::x86_64` 的 intrinsic。把 Vec3、Mat4 的操作 SIMD 化。**这一段你学会了"测量优先于优化"**。

- **Day 122-131**:多线程。`std::thread`、`Arc`、`Mutex`、原子操作、内存顺序(`Relaxed` / `Acquire` / `Release` / `SeqCst`)。lock-free work queue。**Phase 4 难度最大的一段时间**——race condition 的 bug 不复现,你要学会用 ThreadSanitizer、Miri 等工具辅助。

- **Day 132-137**:资产管理。设计 `.hha` 格式(自定义二进制),打包 BMP/WAV → `.hha`,游戏只读 `.hha`。streaming loading(按需加载,不是启动全加载)。**这是工业级游戏引擎资产管线的雏形**,Phase 7 大规模扩展。

- **Day 138-145**:自定义内存分配器。arena allocator(整帧一次性释放)、pool allocator(固定 size 对象池)。`#[global_allocator]` 替换 Rust 默认分配器。**性能提升 10-100 倍**(取决于场景)。

- **Day 146-155**:音频混音器。多声道混音、音量控制、低通/高通滤波、空间音频(声源距离衰减)。**Phase 1 你写的"播放正弦波"演化为完整的混音系统**。

- **Day 156-165**:TrueType 字体。从 .ttf 字节流解析 glyph,光栅化 glyph 到位图,渲染字符串。**这是 HH 全程"造轮子含量"高的一段**,Phase 7 的 PNG 解码器是延续。

- **Day 166-175**:Phong 光照升级 + 整理。法线贴图、Gamma 校正、HDR(High Dynamic Range,允许光照值超过 1.0)。Phase 4 收官。

Phase 4 全程最值得记住的两件事:

**第一,测量优先于优化**。Casey 在 HH 里反复说:"Don't optimize what you don't measure." 任何优化前先 Tracy profile,优化后再 profile,确认有效。**不测量就优化,90% 是浪费时间**(或者更糟,优化错地方让代码更慢更复杂)。

**第二,lock-free 数据结构是必需品**。Phase 4 第 3-4 周你写了 lock-free work queue,主线程 push 任务,工作线程 pop 任务,无锁。**这是工业级游戏引擎的标准架构**——Unreal 的 Task Graph、Unity 的 Job System、Bevy 的 Tasks 都是 lock-free work queue 的变种。

接下来 Phase 5 是 Day 176-235(60 天),主要内容:**把 CPU 渲染器升级为 GPU 渲染器**。具体七件事:
1. OpenGL 上下文创建(winit + glow / gl bindings)。
2. Shader(GLSL,顶点着色器 + 片段着色器)。
3. FBO(Frame Buffer Object,渲染到纹理)。
4. immediate-mode UI(游戏内调试 UI)。
5. ECS 深化(structure of arrays,archetype)。
6. 网络多人游戏(预测 + 回滚)。
7. ECS 系统调度(并行执行系统)。

Phase 5 是 HH 全程"领域跨度"最大的一段——你同时学图形、UI、ECS、网络四个领域。Phase 5 走完,你拥有**现代游戏引擎的所有核心组件**(虽然每个都是简化版)。

## §1 · 进入 Phase 5 前的能力盘点

**A. CPU 性能优化**
- [ ] 你写过 SIMD 加速的代码(`_mm_add_ps` 之类),知道如何 benchmark 标量 vs SIMD。
- [ ] 你写过至少一个 lock-free 数据结构(ring buffer 或 work queue),理解 ABA 问题。
- [ ] 你理解 cache line(64 字节)、false sharing(多线程写同一 cache line)、对齐(`#[repr(align(64))]`)。
- [ ] 你能用 Tracy 或 flamegraph 找到自己代码的热点。

**B. 内存管理**
- [ ] 你写过 arena allocator——`Arena::new(capacity)`, `alloc<T>()`, `reset()`。
- [ ] 你理解 arena vs pool vs system malloc 各自的适用场景。
- [ ] 你理解"生命周期"概念——arena 内的对象生命周期 = arena 生命周期,不能跨 reset 存活。

**C. 资产管线**
- [ ] 你设计过自定义二进制格式(类似 `.hha`)。
- [ ] 你写过"打包器"(packer,把源文件转成二进制)和"加载器"(loader,从二进制加载)。
- [ ] 你理解"资产 hot reload"是什么——改资产文件,游戏实时看到变化。

**D. 软件光栅化(Phase 3 + Phase 4 优化)**
- [ ] 你能写出 SIMD 加速的三角形光栅化器(每帧处理几万到几十万像素)。
- [ ] 你理解 z-buffer、early-z 优化。
- [ ] 你理解纹理映射、纹理过滤(最近邻 vs 双线性)。

**E. GPU 基础(Phase 5 第一周需要)**
- [ ] 你知道 GPU 是什么——显卡上的独立芯片,有自己的内存(VRAM)和计算单元(着色器核)。
- [ ] 你知道 OpenGL 是什么——一个跨平台的图形 API,通过它命令 GPU。
- [ ] 你知道 shader 是什么——在 GPU 上跑的小程序,分顶点着色器(每个顶点跑一次)和片段着色器(每个像素跑一次)。
- [ ] 你知道为什么用 GPU 而不是 CPU——GPU 有几千个核,适合"同样的计算对大量数据并行做"。CPU 几个核,适合复杂逻辑。

**F. 心理建设**
- [ ] 你接受了"GPU 编程和 CPU 编程是两套心智"——CPU 你写指令序列,GPU 你写"对每个顶点 / 像素独立做什么"。后者叫 data-parallel 编程。
- [ ] 你接受了"调试 GPU 代码比 CPU 难"——printf 在 GPU 不存在(或很难),用专门的工具(RenderDoc、Nsight)。
- [ ] 你接受了"GLSL 和 C 很像但有微妙差别"——比如 GLSL 没有指针,所有变量是值类型。

**怎么用这张清单**:Phase 5 第一周(OpenGL 入门)就会用 §E 全部。Phase 5 第二周(Shader)需要 §D 全部(因为你写的 shader 是软件光栅化的 GPU 版)。Phase 5 中后期(ECS、UI、网络)需要 §A、§B。

## §2 · 自测题

下面 6 道题。

### 题 1(SIMD vs 标量)

下面这段标量代码计算两个 4D 向量的点乘。改写成 SSE SIMD 版本。

```rust
fn dot4(a: [f32; 4], b: [f32; 4]) -> f32 {
    a[0]*b[0] + a[1]*b[1] + a[2]*b[2] + a[3]*b[3]
}
```

**参考答案**:

```rust
use std::arch::x86_64::*;

fn dot4_simd(a: [f32; 4], b: [f32; 4]) -> f32 {
    unsafe {
        let va = _mm_loadu_ps(a.as_ptr());  // 加载 4 个 float
        let vb = _mm_loadu_ps(b.as_ptr());
        let mul = _mm_mul_ps(va, vb);  // 4 个乘法,1 条指令
        // 水平加 4 个分量(_mm_hadd_ps 是 SSE3)
        let sum1 = _mm_hadd_ps(mul, mul);  // [a0+a1, a2+a3, a0+a1, a2+a3]
        let sum2 = _mm_hadd_ps(sum1, sum1);  // [a0+a1+a2+a3, ...]
        let result = _mm_cvtss_f32(sum2);  // 取低位
        result
    }
}
```

关键点:
- `_mm_loadu_ps` 加载 4 个 float 到 128 位 XMM 寄存器(无需对齐)。
- `_mm_mul_ps` 一条指令算 4 个乘法。
- `_mm_hadd_ps` 水平加(把寄存器内相邻元素相加),SSE3 指令。
- 最后 `_mm_cvtss_f32` 取低位(就是 4 个分量之和)。

性能:标量版 4 次乘法 + 3 次加法 = 7 条指令。SIMD 版 1 次乘法 + 2 次水平加 = 3 条指令。**SIMD 版快 ~2 倍**(水平加较慢,拖了一些)。

### 题 2(多线程陷阱)

下面这段多线程代码意图是"把数组每个元素 +1"。有什么问题?怎么修?

```rust
use std::thread;

let mut data = vec![0u32; 1000];
let mut handles = vec![];
for i in 0..1000 {
    let handle = thread::spawn(move || {
        data[i] += 1;  // ERROR: data 不能 move 到 1000 个线程
    });
    handles.push(handle);
}
for h in handles { h.join().unwrap(); }
```

**参考答案**:

问题:`data` 是 `Vec<u32>`,不能同时被 1000 个线程持有所有权。

修复方案 1(分块,无锁):
```rust
use std::thread;

let mut data = vec![0u32; 1000];
let chunks: Vec<&mut [u32]> = data.chunks_mut(125).collect();  // 8 块
let mut handles = vec![];
for chunk in chunks {
    let handle = thread::spawn(move || {
        for x in chunk.iter_mut() {
            *x += 1;
        }
    });
    handles.push(handle);
}
for h in handles { h.join().unwrap(); }
```

每个线程独占一块,**无共享,无锁,无 race condition**。这是工业级并行模式——**"embarrassingly parallel"**。

修复方案 2(原子,适合同一个变量被多线程更新):
```rust
use std::sync::Arc;
use std::sync::atomic::{AtomicU32, Ordering};

let data: Vec<AtomicU32> = (0..1000).map(|_| AtomicU32::new(0)).collect();
let data = Arc::new(data);
let mut handles = vec![];
for i in 0..1000 {
    let data = Arc::clone(&data);
    let handle = thread::spawn(move || {
        data[i].fetch_add(1, Ordering::Relaxed);
    });
    handles.push(handle);
}
```

`fetch_add` 是原子操作,无锁。但每次访问要 Arc 共享数据,cache 不友好(尤其原子操作的 cache coherence 开销)。**性能比方案 1 差**。

**经验法则**:**优先无共享并行(方案 1),被迫才用原子(方案 2)**。这是 Phase 4 后期 Casey 大量讨论的"数据并行 vs 任务并行"。

### 题 3(GPU 概念)

GPU 和 CPU 的关键差别是什么?为什么图形 / 物理计算适合 GPU?

**参考答案**:

| 维度 | CPU | GPU |
|---|---|---|
| 核数 | 4-16 | 1000-10000 |
| 每核性能 | 强(乱序执行、分支预测、大 cache) | 弱(顺序执行,小 cache) |
| 适合任务 | 复杂逻辑、分支、单线程性能 | 简单计算、大量数据并行 |
| 内存 | 几 GB DDR,延迟低 | 几十 GB GDDR,带宽高 |
| 编程模型 | 顺序指令 | SIMT(单指令多线程) |

GPU 的设计哲学:**砍掉每个核的复杂度,换核数**。CPU 一个核可能 1ns 算一次乘法,GPU 一个核可能 5ns 算一次乘法,但 GPU 有几千个核,**总吞吐量远超 CPU**。

图形 / 物理适合 GPU 因为:
1. **图形**:每个像素独立计算(光照、纹理),100 万像素并行算。
2. **物理**:每个粒子独立运动(布料、流体),几万粒子并行算。

CPU 上算 100 万像素,即便 SIMD 也要几十毫秒。GPU 上算 100 万像素,几毫秒。**这就是 GPU 的价值**。

### 题 4(OpenGL 数据流)

写下 OpenGL 渲染一个三角形的最简步骤(伪代码即可)。

**参考答案**:

```rust
// 1. 创建顶点数据(3 个顶点,每个 3 个 float 表示位置)
let vertices: [f32; 9] = [
    -0.5, -0.5, 0.0,
     0.5, -0.5, 0.0,
     0.0,  0.5, 0.0,
];

// 2. 上传到 GPU 的 VBO(Vertex Buffer Object)
let mut vbo = 0;
gl::GenBuffers(1, &mut vbo);
gl::BindBuffer(gl::ARRAY_BUFFER, vbo);
gl::BufferData(gl::ARRAY_BUFFER, 36, vertices.as_ptr() as *const _, gl::STATIC_DRAW);

// 3. 编译顶点着色器和片段着色器,链接成 program
let vertex_shader = compile_shader(VERTEX_SHADER_SOURCE, gl::VERTEX_SHADER);
let fragment_shader = compile_shader(FRAGMENT_SHADER_SOURCE, gl::FRAGMENT_SHADER);
let program = link_program(vertex_shader, fragment_shader);

// 4. 每帧:bind VBO 和 program,draw call
gl::UseProgram(program);
gl::BindBuffer(gl::ARRAY_BUFFER, vbo);
gl::VertexAttribPointer(0, 3, gl::FLOAT, gl::FALSE, 12, std::ptr::null());
gl::EnableVertexAttribArray(0);
gl::DrawArrays(gl::TRIANGLES, 0, 3);
```

关键概念:
- **VBO**(Vertex Buffer Object):GPU 上的内存,存顶点数据。
- **顶点着色器**(vertex shader):GPU 程序,每个顶点跑一次,把顶点位置变换到屏幕坐标。
- **片段着色器**(fragment shader):GPU 程序,每个像素跑一次,决定像素颜色。
- **Draw call**:CPU 命令 GPU "画这些顶点"。**Draw call 是性能瓶颈**——每次 draw call 有几百 ns 开销,几千次 draw call 累计毫秒级。

Phase 5 第一周(OpenGL 入门)就是把这段代码跑通,然后用它重写 Phase 4 的软件渲染器。

### 题 5(arena allocator)

写一个 arena allocator,支持 `alloc<T>()` 和 `reset()`。

**参考答案**:

```rust
use std::alloc::{alloc, dealloc, Layout};

pub struct Arena {
    base: *mut u8,
    offset: usize,
    capacity: usize,
}

impl Arena {
    pub fn new(capacity: usize) -> Self {
        let layout = Layout::from_size_align(capacity, 64).unwrap();
        let base = unsafe { alloc(layout) };
        if base.is_null() { panic!("alloc failed"); }
        Arena { base, offset: 0, capacity }
    }

    pub fn alloc<T>(&mut self) -> *mut T {
        let align = std::mem::align_of::<T>();
        let size = std::mem::size_of::<T>();
        // 对齐 offset
        let aligned_offset = (self.offset + align - 1) & !(align - 1);
        let new_offset = aligned_offset + size;
        assert!(new_offset <= self.capacity, "arena out of memory");
        self.offset = new_offset;
        unsafe { self.base.add(aligned_offset) as *mut T }
    }

    pub fn reset(&mut self) {
        self.offset = 0;
    }
}

impl Drop for Arena {
    fn drop(&mut self) {
        let layout = Layout::from_size_align(self.capacity, 64).unwrap();
        unsafe { dealloc(self.base, layout); }
    }
}
```

特点:
- **一次性分配**:new 时一次性分配 capacity 字节,后续 alloc 是指针移动,O(1)。
- **无 individual free**:不支持单独释放某个对象。所有对象"一起死"——reset 时一次性归零。
- **对齐**:每次 alloc 自动对齐(`aligned_offset` 计算)。
- **生命周期**:arena 内对象生命周期 = arena 生命周期。对象不能"逃出" arena(指针出 arena 后失效)。

性能:对比 system malloc(每次 alloc 几十 ns),arena alloc 是 ~1ns(指针加法)。**快 10-100 倍**。

适用场景:每帧分配大量小对象(粒子、临时矩阵、debug 信息),帧末 reset。

### 题 6(Phase 4 反思)

Phase 4 收尾时,你的代码相对 Phase 3 收尾时,主要改进了什么?给出至少 4 条。

**参考答案**:

1. **性能**:SIMD + 多线程 + 内存布局优化,FPS 从 30 提升到 60+。某些场景 120+。
2. **内存受控**:arena allocator 替换 system malloc,内存峰值和分配次数可控。
3. **资产管线**:`.hha` 格式替代零散 BMP/WAV,启动加载从几秒降到几百毫秒。
4. **音频真实**:多声道混音器替代单声道正弦波,支持音量、滤波、空间音频。
5. **字体可读**:TrueType 字体渲染,游戏 UI 能显示文字。
6. **代码工程化**:模块化更清晰(SIMD 模块、线程模块、内存模块、资产模块各自独立)。
7. **可测量**:Tracy profiler 集成,任何代码段都能 profile。

## §3 · 心智切换:从 CPU 到 CPU + GPU

Phase 4 全程你在 CPU 上写代码——单核、多核、SIMD、内存。你的代码"完全在 CPU 上"。

Phase 5 全程你**同时**在 CPU 和 GPU 上写代码——CPU 上写游戏逻辑、物理、AI、音频;GPU 上写顶点着色器、片段着色器、光栅化。**这是巨大的心智切换**。

具体 5 条:

**1. 从"CPU 一种硬件"到"CPU + GPU 两种硬件"**。
Phase 4 你的代码跑在 CPU 上,数据在 RAM 里。Phase 5 你**有一份数据在 CPU(RAM),一份数据在 GPU(VRAM)**。两份数据要同步——CPU 修改了顶点位置,要上传到 GPU;GPU 渲染了场景到 FBO,要下载回 CPU 才能截图。

心智切换:**写代码时,永远知道数据在哪——CPU 还是 GPU**。CPU 访问 GPU 数据要"下载"(慢),GPU 访问 CPU 数据要"上传"(慢)。**频繁 CPU-GPU 通信是性能杀手**。

**2. 从"指令序列"到"data-parallel"**。
CPU 代码:`for i in 0..n { do_something(i); }`——n 次循环,每次一条指令。
GPU 代码:`do_something(i);`——一次定义,但 GPU 对 n 个数据并行执行 n 次。

心智切换:**GPU 代码不写循环,写"对每个元素独立做什么"**。这叫 SIMT(Single Instruction, Multiple Threads)。GPU 上每个顶点 / 像素是独立"线程",都跑同样的 shader,但数据不同。

```glsl
// GPU shader:对每个顶点跑一次
#version 330 core
in vec3 position;
uniform mat4 mvp;
void main() {
    gl_Position = mvp * vec4(position, 1.0);
}
```

这就是 GPU 编程的核心:**写"一次"的代码,GPU 并行跑"百万次"**。

**3. 从"print debug"到"特殊工具 debug"**。
CPU 代码 bug,你 `println!`、用 gdb / lldb。
GPU 代码 bug(渲染错了),`println` 不存在(shader 是 GPU 上跑的,没 IO)。你用:
- **RenderDoc**:抓一帧,看每个 draw call 的输入输出。
- **Nsight**(NVIDIA 专属):类似 RenderDoc,但更深入 GPU 内部。
- **apitrace**:记录 GL 调用,可重放。

心智切换:**GPU bug 不靠 print,靠"抓帧 + 看每步状态"**。学会 RenderDoc 是 Phase 5 第一周的事。

**4. 从"代码即数据"到"代码和数据分开"**。
CPU 代码,函数和数据都在内存里。
GPU 代码,**shader 是 GPU 上的代码**(独立编译),**数据是 GPU 上的 buffer**(独立上传)。两者通过"绑定"(bind)关联——bind buffer X 到 shader 的 attribute Y。

心智切换:**shader 和 buffer 是两个独立资源,要分别创建、绑定、解绑**。状态机概念——OpenGL 是状态机,你 set 状态(当前 program、当前 VBO、当前 FBO),后续 draw call 用这些状态。

**5. 从"主线程一个"到"渲染线程 + 主线程"**。
Phase 4 你写多线程,主线程 + 工作线程。Phase 5 你**额外有一个渲染线程**(或主线程兼任)专门给 GPU 发命令。

心智切换:**CPU-GPU 通信是异步的**——CPU 发 draw call,GPU 开始执行,但 CPU 不等,继续发下一个。这就是 GPU 的"命令缓冲区"。但有些操作要同步(glFinish,glFence),慢,慎用。

**性能心智**:GPU 上的 draw call 是"贵"的(每次几百 ns CPU 开销 + 几百 ns GPU 状态切换)。**减少 draw call 是 GPU 性能优化第一原则**。工业级做法:**instancing**(一个 draw call 画 1000 个相同模型)、**batching**(把多个模型合并成一个大模型)。

切换的最大陷阱:**把 GPU 当 CPU 用**。Phase 5 第一周你会写"每帧上传一次顶点数据"——错,正确是"创建时上传一次,每帧只更新变化的"。你会写"for 循环里 1000 次 draw call"——错,正确是 instancing / batching 一次画完。

**GPU 编程的核心心智**:**最小化 CPU-GPU 通信,最大化 GPU 并行**。

## §4 · 进 Phase 5 第一周学习路径

**Day 176-180(对应 HH day176-180)**:**OpenGL 上下文 + 第一个三角形**。
重点:用 winit + glow(Rust OpenGL binding)创建 OpenGL 上下文。`gl::ClearColor`、`gl::Clear`。第一个 `gl::DrawArrays` 画三角形。
产出:屏幕上一个彩色三角形。
建议:读 `/home/sun/src/handmade-hero-guide/days/phase-5/deep-dives/opengl-context-creation.md`。

**Day 181-185(对应 HH day181-185)**:**Shader 基础**。
重点:GLSL 语法。顶点着色器(变换 + 投影)、片段着色器(决定颜色)。uniform 变量(从 CPU 传给 GPU 的参数)、attribute / in 变量(每个顶点的属性)。
产出:三角形能根据时间变色,uniform `time` 控制颜色。
建议:读 `/home/sun/src/handmade-hero-guide/days/phase-5/deep-dives/shader-basics.md`。

**Day 186-190(对应 HH day186-190)**:**3D 渲染 + 纹理**。
重点:画 3D 立方体(VBO + IBO)。texture upload 到 GPU,sampler,在 fragment shader 采样。
产出:有纹理的 3D 立方体。
建议:这是 Phase 5 第一阶段高潮,你已经能用 GPU 做 Phase 3 做的事了。

**Day 191-195(对应 HH day191-195)**:**Phong 光照在 GPU**。
重点:把 Phase 3 的 Phong 光照移到 GPU。fragment shader 里算 ambient + diffuse + specular。
产出:GPU 渲染的 3D 物体有光照。

**Day 196-200(对应 HH day196-200)**:**immediate-mode UI 基础**。
重点:游戏内调试 UI 的设计。immediate-mode vs retained-mode(区别和权衡)。简单按钮、滑块、文本。
产出:按 F1 出调试 overlay,显示 FPS、相机位置。
建议:读 `/home/sun/src/handmade-hero-guide/days/phase-5/deep-dives/immediate-mode-ui.md`。

**Day 201-205(对应 HH day201-205)**:**debug 隔离 + FBO**。
重点:用 Cargo feature 隔离 debug 代码(`#[cfg(feature = "debug")]`)。FBO(Frame Buffer Object),渲染到纹理而不是屏幕。
产出:debug 代码不进发行版;能把场景渲染到纹理再用做后处理。

第一周结束你应该有:能用 OpenGL 渲染带光照和纹理的 3D 物体,有调试 UI。**这是 Phase 5 第一阶段目标**——你已经把 Phase 3 + Phase 4 的渲染器成功"移植"到 GPU。

## §5 · 实战项目建议

### 项目 A:GPU 粒子系统

写一个 GPU 粒子系统。技术栈:Rust + OpenGL。

需求:
- 屏幕上 10000 个粒子,每个有位置、速度、生命周期。
- 粒子在 GPU 上更新(用 transform feedback 或 compute shader)。
- 粒子在 GPU 上渲染(用 point sprite 或 instanced quad)。
- CPU 只负责"发射粒子"和"draw call"。

时间预算:2-3 周。

为什么推荐:粒子系统是 GPU 优势的最佳展示——CPU 上算 10000 粒子要几毫秒,GPU 上几乎免费。做完这个,你彻底理解"为什么用 GPU"。

### 项目 B:GPU Mandelbrot 集合

写一个 GPU 加速的 Mandelbrot 集合渲染器。技术栈同上。

需求:
- fragment shader 里对每个像素算 Mandelbrot 迭代。
- 鼠标缩放、平移。
- 高分辨率(4K)也能 60 FPS。

时间预算:1 周。

为什么推荐:Mandelbrot 是 GPU 入门经典。**代码量小(50 行 shader),效果震撼(无限缩放)。** 适合作为 GPU 入门的"hello world"。

### 项目 C:OpenGL immediate-mode UI 库

写一个简单的 immediate-mode UI 库。技术栈同上。

需求:
- `ui::button("click me")` 返回是否点击。
- `ui::slider("volume", &mut vol, 0.0..=1.0)`。
- `ui::text("FPS: 60")`。
- 自己处理输入、布局、渲染。

时间预算:2 周。

为什么推荐:immediate-mode UI 是现代游戏调试 UI 的主流。**而且实际有用**——做完你能用在任何项目里。建议读 `/home/sun/src/handmade-hero-guide/days/phase-5/deep-dives/immediate-mode-ui.md` 后开始。

## §6 · 推荐配合的 deep-dive

`/home/sun/src/handmade-hero-guide/days/phase-4/deep-dives/` 里有几篇进 Phase 5 前值得读的:

### `threading-models.md`(强推荐)

游戏引擎的线程模型——主线程、渲染线程、工作线程。Phase 5 你写"渲染线程"时会用到。

### `arena-allocator.md`(强推荐)

Phase 5 ECS 数据布局会大量用 arena 思想。

### `simd-in-rust.md`(可选,Phase 5 后期读)

Phase 5 后期 ECS 系统调度可能用 SIMD,但现在不必读。

---

`/home/sun/src/handmade-hero-guide/days/phase-5/deep-dives/` 里的推荐:

### `opengl-context-creation.md`(强推荐,Phase 5 第一天读)

OpenGL 上下文创建的完整过程。winit + glow 的具体配置。

### `shader-basics.md`(强推荐,Phase 5 第二周读)

GLSL 的完整入门。顶点 / 片段 / 几何 / 计算 shader。

### `immediate-mode-ui.md`(强推荐,Phase 5 第三周读)

immediate-mode UI 的设计哲学和实现。**读完你能在自己项目里写调试 UI**。

### `fbo-and-render-to-texture.md`(推荐,Phase 5 第三周末读)

FBO 的完整讨论。后处理(模糊、bloom)的基础。

### `ecs-evolution.md` + `ecs-data-layout.md` + `ecs-system-scheduling.md`(Phase 5 后期读)

Phase 5 后期 Casey 深化 ECS,这三篇是 ECS 的"圣三位一体"。

### `threading-journey.md`(Phase 5 后期读)

HH 全程线程演化的总结。Phase 5 收尾时读。

---

## 结语

Phase 4 是"让 CPU 跑满",Phase 5 是"开始用 GPU"。Phase 4 完成时你 CPU 跑稳定 60 FPS,Phase 5 完成时你**把渲染负载从 CPU 转移到 GPU**,CPU 跑 60 FPS 同时还有余量做游戏逻辑。

Phase 5 第一周你会觉得"OpenGL API 好啰嗦,要 GenBuffers / BindBuffer / BufferData / ... 一长串"。坚持一周,你会发现这一长串是 OpenGL 的状态机模型——一次设置状态,后续 draw call 复用。**理解了状态机,OpenGL 就不啰嗦了**。

Phase 5 第二周你会觉得"GLSL 和 Rust 不一样,数据类型好奇怪"。坚持一周,你会发现 GLSL 的设计哲学是"对每个顶点 / 像素独立运行,所以无指针、无堆、所有变量是值"——这种限制反而让 shader 易于并行。

Phase 5 后期你会进入 ECS、UI、网络三个领域。**这三个领域每个都能写一本书**。Phase 5 只是入门,**让你知道这三个领域长什么样**。深入要靠后续项目实战。

Phase 5 全程的核心纪律是:**CPU-GPU 通信最小化**。每帧的 draw call 数、buffer 上传 / 下载字节数,都要监控。Tracy + RenderDoc 是左膀右臂。

下一站:Day 176。装好 OpenGL,准备画第一个三角形。
