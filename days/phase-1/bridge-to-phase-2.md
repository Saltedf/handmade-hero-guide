
# Bridge · 从 Phase 1 到 Phase 2

> 你刚把 Phase 1 走完。25 天。窗口起来了,像素能画上去,声音能播出来,键盘鼠标能读,代码改一行不重启就生效。你坐在那里看自己写的窗口,心想:然后呢?——然后呢就是:**该做游戏了**。Phase 1 是盖剧院,Phase 2 是排剧。这篇文章是过桥指南,告诉你"剧院盖好了,我手上的工具到底够不够用,排剧前还差什么,第一天排剧要从哪开始"。

## §0 · 你已经走过的路

Phase 1 是 Handmade Hero 全程最抽象、最"看不到游戏"的 25 天。Casey 在这 25 集里没让玩家动一步,没让一颗子弹飞起来。他做的全部事情,是搭一台机器:**这台机器能开窗、能画像素、能读键鼠、能播声音、能改代码不重启**。

按时间顺序复盘:

- **Day 1-4**:Win32 开窗。`CreateWindowEx`、`PeekMessage`、`WM_PAINT`。一个黑色窗口出现了,你能看见自己写的 exe 跑起来。
- **Day 5-8**:后缓冲(back buffer)。`VirtualAlloc` 申请一块 `WIDTH * HEIGHT * 4` 字节的内存,每 4 字节是一个 `0xAARRGGBB` 像素。然后用 `StretchDIBits` 把它贴到屏幕上。你学会"画一个像素"的本质就是"往这块内存里写一个 32 位整数"。
- **Day 9-11**:主循环 + 时间。`QueryPerformanceCounter` 拿到纳秒级时间,算出每帧的 `dt`(delta time,两帧之间的时间间隔)。游戏循环从此固定为"`while (running) { process_input(); update(dt); render(); swap(); }`"。
- **Day 12-15**:输入。`XInput` 拿手柄,`RAWINPUT` 拿键鼠。你封装成 `game_input` 结构,包含"这一帧哪些键按下、哪些键刚 down、哪些键刚 up、左摇杆在 (0.3, -0.7) 这种坐标"。
- **Day 16-19**:音频。DirectSound 创建次级缓冲区,每帧把"下一帧要播的样本"填进去。你第一次听见自己写的程序发出 440Hz 正弦波的"嘟——"声。
- **Day 20-22**:平台层 / 游戏层分离。Casey 用 `LoadLibrary` + `GetProcAddress` 把游戏代码编成 `game.dll`,平台代码留在 `win32_handmade.exe`。平台层拿到 `game_update_and_render` 函数指针,每帧调用。这是整个 HH 最重要的架构决定。
- **Day 23-25**:热重载。文件 watcher 检测到 `game.dll` 的 mtime 改变,平台层卸载旧 dll、加载新 dll、下一帧立即用新代码。从此你改一行代码按个键就生效,告别"重新 build + 重启游戏"的循环。

这 25 天的产出**没有任何一行游戏代码**。但所有后续 642 天,都站在这 25 天之上。这就是为什么 Phase 1 收尾时,你心里既有一种"我做了什么?"的空虚(没看到游戏画面),又有一种"地基打牢了"的踏实——这踏实是真实的,地基确实打牢了。

接下来 Phase 2 是 Day 26-70(45 天),主要内容:**把黑屏窗口变成一个能玩的小游戏**。黑板上的方块、地板纹理、怪物 AI、碰撞、摄像机、关卡——所有 2D 游戏该有的东西。Phase 2 才是"做游戏",Phase 1 是"做能让游戏跑起来的机器"。

## §1 · 进入 Phase 2 前的能力盘点

进 Phase 2 之前,我们要做一次能力盘点。下面这张清单的每一项,都是 Phase 2 第一周就会用到的能力。你**必须**逐项打勾,任何一项不通,Phase 2 都会很痛苦。

**A. 平台层 API 接口**
- [ ] 能在白纸上写出 Phase 1 末尾平台层对游戏层暴露的"四个函数指针签名":`update_and_render`、`update_audio`、以及(如果你跟了 Rust 移植)`initialize`。
- [ ] 能解释 `game_offscreen_buffer` 这个结构里都有什么(width、height、pitch、bytes-per-pixel、memory 指针),以及为什么 pitch 不一定等于 `width * bytes_per_pixel`(对齐)。
- [ ] 能写一段最简的"往 (x, y) 画一个红色像素"代码:`u32* pixel = (u32*)((u8*)buffer->memory + y * buffer->pitch + x * 4); *pixel = 0xFFFF0000;`。
- [ ] 能解释 `dt`(delta time)的含义,并知道为什么不能用"固定每帧前进 5 像素",而要写"每秒前进 300 像素,每帧前进 `300 * dt`"。

**B. Win32 → winit(Rust 跨平台)**
- [ ] 能解释 Win32 的 `WM_PAINT` / `WM_KEYDOWN` / `WM_DESTROY` 这三个消息的作用,以及它们和 winit 的 `Event::RedrawRequested` / `WindowEvent::KeyboardInput` / `WindowEvent::CloseRequested` 一一对应关系。
- [ ] 知道 winit 的 `EventLoop` 是什么(`EventLoop::new()` + `run(move |event, _, control_flow| { ... })`),并能解释"事件循环"在所有 GUI 程序里都是同一个心智模型。
- [ ] 能解释"消息驱动"和"轮询"的区别。Win32 是消息驱动(系统 push 消息给你),winit 既是消息驱动也允许轮询。
- [ ] 写过一段最小 winit 程序:开窗、画一个背景色、Esc 关窗。

**C. Win32 → cpal(Rust 跨平台音频)**
- [ ] 知道 DirectSound 在 Windows 上的工作方式:创建 primary buffer(全局格式)、创建 secondary buffer(你写样本进去)、混音器从 secondary 读出贴到 primary。
- [ ] 知道 cpal 在所有平台上提供同样的抽象:`Stream`、`SampleRate`、`Sample` trait。你能写出"cpal 回调里填一个 440Hz 正弦波"的最小代码。
- [ ] 能解释"音频回调"和"游戏主循环"为什么是两个不同的线程(音频对时序敏感,游戏帧率高但可以抖动),以及它们怎么共享数据(`Arc<Mutex<...>>` 或 lock-free ring buffer)。
- [ ] 能解释"音频 glitch"是什么(回调来不及填样本,播放端读到旧数据),以及为什么"回调里不能做耗时操作"(持锁、内存分配、IO)。

**D. 热重载机制**
- [ ] 能解释 `LoadLibrary` / `dlclose` / `dlopen` 三个 API 的对应关系(Windows / Linux)。
- [ ] 能解释为什么 Rust 里要用 `cdylib`(C ABI dynamic library)而不是 `dylib`(Rust native dynamic library)。答案:Rust ABI 不稳定,平台和游戏要用 C ABI 沟通。
- [ ] 知道 Rust 里 `#[no_mangle] pub extern "C" fn update_and_render(...)` 的每个关键字什么意思(`no_mangle` = 不修改符号名,`extern "C"` = 用 C 调用约定,`pub` = 暴露给外面)。
- [ ] 能写出"watch 一个 .so 文件,变了就 reload"的最小代码框架(inotify on Linux,`ReadDirectoryChangesW` on Windows)。

**E. 通用编程能力(Phase 1 副产品)**
- [ ] 你写过至少一次"自己设计一个 struct,决定它放什么字段",而不是抄教程的。
- [ ] 你能在 Rust 里独立用 `Option`、`Result`、`match` 写完一段逻辑,而不是用 `if let` 凑合。
- [ ] 你能用 `cargo` 起一个新 binary 项目,加一个依赖,跑通最小例子。
- [ ] 你能用 `gdb` 或 `lldb` 至少下个断点、看个变量。这是 Phase 2 出 bug 时唯一的救命手段。

**F. 心理建设**
- [ ] 你接受了"做游戏是一个长跑"——Phase 2 的前 10 天你不会看到任何"像游戏"的东西,你还在拍"一个能动的方块"。
- [ ] 你接受了"代码会反复改"——Phase 2 你会发现 Phase 1 的某些设计不够好,会回去重构。这不是失败,这是工程常态。
- [ ] 你接受了"看不懂的代码就读到懂为止"——某些代码段你读三遍才懂,这是正常的。

**怎么用这张清单**:逐项打勾。任何一项打不上勾,你**就先回到 Phase 1 对应的 day 文件**补上,再进 Phase 2。我特别推荐 `/home/sun/src/handmade-hero-guide/days/phase-1/deep-dives/` 里的三个文件——`win32-to-winit.md`、`hot-reload-rust.md`、`platform-game-separation.md`——它们就是为这一刻写的,每一篇都从零开始讲。

## §2 · 自测题

下面 6 道题,每道都自己先写答案再读参考答案。如果某题答得磕磕巴巴,**这就是进 Phase 2 之前要补的洞**。

### 题 1(平台层接口)

写下 Phase 1 末尾平台层对游戏层暴露的 `update_and_render` 函数签名(Rust 版,C ABI)。所有参数和返回值的含义都写出来。

**参考答案**:

```rust
#[no_mangle]
pub extern "C" fn update_and_render(
    state: *mut GameState,                  // 游戏状态,平台层分配内存,游戏层填字段
    input: &GameInput,                       // 这一帧的输入:键盘、鼠标、手柄
    bitmap: &mut GameOffscreenBuffer,        // 后缓冲(平台层拥有,游戏层写像素)
    sound_buffer: &mut GameSoundBuffer,      // 音频缓冲(游戏层填下一帧要播的样本)
    dt: std::time::Duration,                 // 上一帧到这一帧的时间
) {
    // ... 游戏逻辑
}
```

`GameState` 由游戏层定义结构,平台层只负责分配内存和传指针。这种设计让"游戏代码改了 GameState 的字段"不需要平台层重编——只有 GameState 的内存大小变了,才需要平台层重编(它要按新大小 VirtualAlloc)。

### 题 2(后缓冲画像素)

给定一个 `GameOffscreenBuffer { width: u32, height: u32, pitch: usize, memory: *mut u8 }`,写一段 Rust 代码,在 (10, 20) 画一个白色像素。要求安全(无 UB)。

**参考答案**:

```rust
fn put_pixel(buf: &GameOffscreenBuffer, x: u32, y: u32, color: u32) {
    assert!(x < buf.width);
    assert!(y < buf.height);
    // pitch 是"一行字节数"。每个像素 4 字节(BGRA)。
    let offset = (y as usize) * buf.pitch + (x as usize) * 4;
    // 安全地把 *mut u8 当成切片用
    let bytes: &mut [u8] = unsafe {
        std::slice::from_raw_parts_mut(buf.memory, buf.pitch * buf.height as usize)
    };
    let pixel_bytes = color.to_le_bytes();  // 0xFFFFFFFF -> [255, 255, 255, 255]
    bytes[offset..offset + 4].copy_from_slice(&pixel_bytes);
}
```

关键点:(1) pitch 是字节数,不是像素数;(2) `to_le_bytes()` 因为 x86 是小端;(3) `from_raw_parts_mut` 是 unsafe,但因为 `memory` 来自平台层 `VirtualAlloc`/`mmap`,size 是正确的,所以这次使用是 sound 的。

### 题 3(为什么 dt)

为什么不能"每帧前进固定 5 像素",而要"每秒前进 300 像素,每帧前进 `300 * dt`"?具体讲:如果游戏在 60 FPS 跑,玩家在屏幕上 1 秒走多少像素?如果掉到 30 FPS,1 秒走多少像素?这两种情况下"玩家走 1 秒"是同一段距离吗?

**参考答案**:

- "每帧 5 像素"在 60 FPS:1 秒 60 帧,每帧 5 像素 → 1 秒走 300 像素。
- "每帧 5 像素"在 30 FPS:1 秒 30 帧,每帧 5 像素 → 1 秒走 150 像素。
- 同一段玩家输入(按方向键 1 秒),在不同帧率下走的距离不同。这是 bug——"游戏在快机器上变快"。

正确写法是"每秒 300 像素":无论帧率,dt 是真实时间。60 FPS 时 dt = 1/60,每帧 `300 * (1/60) = 5` 像素。30 FPS 时 dt = 1/30,每帧 `300 * (1/30) = 10` 像素。1 秒都走 300 像素,和帧率无关。

这个心智模型叫 **frame-rate independent**(帧率无关),所有严肃游戏都必须这样写。Casey 在 Day 9-11 反复强调。

### 题 4(平台和游戏分离)

为什么 Casey 用 `LoadLibrary` + 函数指针,而不是直接静态链接游戏代码到平台代码?给出至少 3 个具体好处。

**参考答案**:

1. **热重载**:平台 exe 不动,只重编游戏 dll。游戏代码改一行,平台层检测到 dll 的 mtime 变,卸载旧的加载新的,下一帧立即用新代码。这是 Casey 直播时每几分钟就做的事,效率提升巨大。
2. **平台无关**:理论上,只要平台层暴露的接口一致,游戏代码可以在不同平台(Win32、Linux、macOS、WebAssembly)上跑,只需要换平台层。Casey 实际没完全做到这点(用了 Win32 私有 API),但社区 fork 在 Linux 上用 SDL/winit 替代 Win32 平台层就跑通了。
3. **崩溃隔离**:游戏代码 crash,dll 加载失败,平台层可以 fallback(比如重加载上次保存的 dll),而不是整个进程退出。实践中不太用,但理论可行。
4. **构建时间**:大项目里,平台层稳定后很少改,改游戏代码时只编游戏 dll(几秒),不用编整个 exe(几十秒)。这是 C/C++/Rust 大项目必备的增量构建技巧。
5. **多版本并存**:平台层可以同时加载多个游戏 dll(比如 debug 版和 release 版),runtime 切换。

### 题 5(Rust 的 cdylib)

`Cargo.toml` 里写 `[lib] crate-type = ["cdylib", "rlib"]`,这两个 crate-type 各自是什么?为什么热重载场景要 `cdylib`?

**参考答案**:

- `rlib`(Rust library):Rust 内部用的库格式,包含 Rust 的 metadata(类型信息、trait impl、宏)。只有 Rust 编译器能消费。适合"另一个 Rust crate 要依赖这个 crate"的场景。
- `cdylib`(C dynamic library):C ABI 的动态库。导出的函数用 C 调用约定(`extern "C"`),符号名按 C 规则(可被 `dlopen` 找到)。Windows 上是 `.dll`,Linux 上是 `.so`,macOS 上是 `.dylib`。
- 热重载用 `cdylib` 是因为:**平台层要用 C ABI 找到游戏层的函数**。`LoadLibrary`/`dlopen` 不理解 Rust 的 metadata,只认 C 符号。`#[no_mangle] pub extern "C" fn` 暴露的函数,在 cdylib 里就是一个 C 符号,平台层能拿到。

一个 Rust 项目同时声明 `["cdylib", "rlib"]` 是常见的:**自己用 rlib(被其他 Rust crate 依赖),给热重载平台用 cdylib**。Casey 在 HH 里只用 cdylib(没有 rlib 需求)。

### 题 6(音频回调的约束)

`cpal` 的音频回调里,**不能**做哪些事?为什么?给出至少 3 个。

**参考答案**:

不能做的事:
1. **分配内存**(`Box::new`、`Vec::push`、`String::from`)。分配器可能持锁(malloc 内部锁),回调被阻塞 → 音频 glitch。
2. **持锁**(`Mutex::lock`、`RwLock::write`)。回调线程优先级高,持锁等低优先级线程释放 → 优先级反转(priority inversion),整个音频线程卡死。
3. **做磁盘 IO**(文件读写、网络)。IO 可能阻塞数百毫秒,音频回调每 ~10ms 就要跑一次,等不起。
4. **做复杂计算**(FFT、卷积、大循环)。同上,音频回调有严格时间预算(~3ms),超出就 glitch。
5. **panic**。Rust 里 panic 会 unwind 栈,cpal 的回调线程 panic 后整个音频流停。所以回调里要么用 `Result` 严格处理错误,要么用 `catch_unwind` 包一层。

正确做法:**音频回调只做"读 ring buffer → 拷贝到输出"**。所有重活在游戏主线程做,把结果写进 ring buffer,回调只读。

```rust
// 回调里只做这种事
let stream = device.build_output_stream(
    &config,
    move |data: &mut [f32], _: &cpal::OutputCallbackInfo| {
        // ring_buf 是 lock-free SPSC ring
        for sample in data.iter_mut() {
            *sample = ring_buf.pop().unwrap_or(0.0);
        }
    },
    |err| eprintln!("audio err: {:?}", err),
    None,
)?;
```

## §3 · 心智切换:从"造基础设施"到"做游戏"

Phase 1 的 25 天,你的心智模式是**工程师**:你关心"这个 API 怎么调"、"这块内存谁拥有"、"这个回调什么时候触发"。你读的是 Win32 文档、Rust 文档、cpal 文档。你画的图是"内存布局图"、"线程图"、"调用栈图"。

Phase 2 的 45 天,你的心智模式要切换到**游戏设计师 + 工程师**:你**还要**继续关心 Phase 1 的那些事(没人在 Phase 2 帮你写代码),但同时你**开始关心游戏特有的东西**:

- **手感**(game feel):角色按方向键,是"立即响应"还是"有加速度"?跳跃的曲线是"抛物线"还是"线性"?按住跳是"跳更高"还是"固定高度"?这些决定游戏好不好玩,Phase 2 你第一次面对。
- **碰撞**:玩家撞墙应该"停下来",还是"弹开",还是"沿墙滑动"?这要写碰撞检测算法 + 碰撞响应策略。
- **关卡设计**:房间里有什么?怪物从哪刷?金币怎么放?Phase 1 没有"关卡"这个概念,Phase 2 你要发明它。
- **游戏状态**:游戏有"主菜单"、"游戏中"、"暂停"、"通关"、"死亡"这几个状态。怎么管?这是 Phase 2 的"状态机"问题。
- **资产**:游戏里要有图(精灵)、要有声音、要有数据。这些文件怎么加载、怎么管理?

具体的心智切换有 5 条:

**1. 从"消息驱动"到"轮询 + 状态"**。
Phase 1 你写 Win32 处理消息,每收到一个消息处理一个。Phase 2 的游戏循环是**每帧主动轮询**当前状态:`fn update() { match state { Menu => update_menu(), Playing => update_playing(), ... } }`。状态变化不是消息,是 update 内部的逻辑。

**2. 从"画像素"到"画精灵"**。
Phase 1 你写 `put_pixel(x, y, color)`,画的是抽象的像素。Phase 2 你写 `draw_sprite(x, y, sprite)`,画的是有意义的图形。中间一步是 `draw_bitmap`——把一块预存的内存(`u32` 数组)整块拷贝到后缓冲的指定位置。这是 sprite 的本质。

**3. 从"瞬时输入"到"持续状态"**。
Phase 1 你读"哪些键刚 down"。Phase 2 你需要知道"哪些键 down 着"——因为"按住方向键持续走"靠的是"持续 down 状态",不是"刚 down 事件"。Casey 在 Day 9 引入"上一帧按键状态 + 这一帧按键状态"的双缓冲设计,Phase 2 你天天用。

**4. 从"无状态"到"状态机"**。
Phase 1 平台层基本无状态(就是一直跑主循环)。Phase 2 游戏层从第一帧就有状态:`GameState { player_pos, player_hp, level, ... }`。状态怎么组织、怎么持久化(存档)、怎么演化,这是 Phase 2 全程的主线。

**5. 从"接口设计"到"游戏感"**。
Phase 1 你判断"接口好不好"看的是"调用方便吗"、"类型安全吗"。Phase 2 你判断"游戏好不好"看的是"按下方向键,角色有没有'啪'地一下就响应"。"啪"是手感。Casey 在 Day 33-40 反复调加速度曲线、跳跃高度、动画时机,就是为了这个"啪"。这种判断**不是工程判断,是审美判断**——这是 Phase 1 没有的维度。

切换的最大陷阱是**走极端**——要么完全审美化,把工程纪律扔了(代码乱成一团);要么完全工程化,做出一个"技术上完美但手感烂"的游戏。Casey 在 HH 里的平衡是:**先把功能跑通(工程优先),再反复调参数(审美优先)**。Phase 2 全程你会看到他在工程和审美之间反复横跳。

## §4 · 进 Phase 2 第一周学习路径

下面是 Phase 2 第 1-7 天的逐日学习路径。我标了"对应 HH 的 day"、"重点"、"产出",你跟着这个节奏走。

**Day 26(对应 HH day26)**:**画出第一个移动方块**。
重点:把 Phase 1 的 `put_pixel` 包成 `draw_bitmap`,然后画一个 32x32 的方块在屏幕中央。读输入:按右方向键,方块 x += 5。
产出:一个能动的方块。
坑:`dt` 用错的话方块会忽快忽慢。一定按 §2 题 3 的方式用 `dt * speed`。

**Day 27-28(对应 HH day27-28)**:**背景 + 滚动**。
重点:画一个比屏幕大的"地图"(2D `u32` 数组),按方向键移动相机。这是 2D 游戏的"摄像机"概念第一次出场。
产出:方向键移动相机,屏幕看到地图的不同区域。
坑:边界处理。相机不能滚到地图外。Casey 用 `max(0, min(map_width - screen_width, cam_x))` 的 clamp 写法。

**Day 29-30(对应 HH day29-30)**:**第一个 entity**。
重点:把方块改成 `struct Entity { pos, vel, ... }`,从 `Vec<Entity>` 遍历更新。这是 ECS 的雏形——Casey 后面 Phase 2 会把它演化成"sparse array + generation index"。
产出:屏幕上同时有玩家方块 + 怪物方块 + 子弹方块,各自移动。
坑:`Vec::remove` 是 O(n),删 entity 用 swap_remove,或用 Casey 的 sparse array 方案。

**Day 31-32(对应 HH day31-32)**:**碰撞检测**。
重点:写一个 `aabb_intersect(a, b)`——两个矩形是否相交(轴对齐包围盒 AABB,axis-aligned bounding box)。玩家撞墙时,做"分轴检测"——先 X 移动检查 X 碰撞,再 Y 移动检查 Y 碰撞,这样能正确处理"贴墙滑行"。
产出:玩家能撞墙,不能穿墙。
坑:"先 X 再 Y"的顺序写错,会导致对角碰撞处理不对。仔细看 Casey 的演示。

**Day 33-35(对应 HH day33-35)**:**精灵图 + 动画**。
重点:从 BMP 加载一张精灵图,画到屏幕。用 sprite sheet 做"两帧切换"动画(走路)。
产出:玩家方块变成一个会动的角色。
坑: BMP 格式里 width 必须是 4 的倍数(否则每行有 padding)。读 BMP 时要按 pitch 处理,不是按 width。

**Day 36-40(对应 HH day36-40)**:**玩家控制器 + 跳跃曲线**。
重点:重力 + 跳跃。Casey 在 HH 里做的是"按住跳键跳更高"——这要追踪"跳键 down 多久了"。这是"游戏手感"的第一次实战。
产出:能跳的角色,跳跃感觉自然。
坑:跳跃曲线写不好,要么"跳得太低没成就感",要么"飞起来下不来"。调参数可能花你几个小时,这是正常的。

**Day 41(对应 HH day41)**:**反思 + 整理**。
重点:回顾前 5 天写的代码。哪些是"游戏逻辑"(放在 game.rs),哪些是"渲染细节"(可以放 render.rs),哪些是"平台杂活"(放 platform.rs)。Casey 在 Day 41 做了这次架构整理。
产出:更清晰的代码结构。
建议:这天读一下 `/home/sun/src/handmade-hero-guide/days/phase-2/day041.md`——这是 HH 全程的"教学风格金标"day,Casey 把"如何思考游戏架构"讲透了。

第一周结束你应该有:一个能动的角色、一个能滚动的地图、一个能撞墙的碰撞系统。这是 Phase 2 后续所有内容(GI、AI、关卡、状态机、音效)的地基。

## §5 · 实战项目建议

光看视频不够。下面三个项目,任选一个,**自己从头写**。这是把 Phase 1 能力巩固的最好方式。

### 项目 A:Tetris(俄罗斯方块)

从零写一个 Tetris。技术栈:Rust + winit + 自己的 `put_pixel`。

需求:
- 7 种方块(I, O, T, S, Z, L, J),每种用 `[[u8; 4]; 4]` 表示形状。
- 方块按固定速度下落,按方向键左右移动,按上键旋转,按下键加速下落。
- 满行消除,加分。
- 顶部到底部,游戏结束。

时间预算:1-2 周。

为什么推荐:Tetris 完美覆盖 Phase 2 的所有核心概念——输入、计时、碰撞(方块能不能放)、状态机(游戏状态)、渲染(画 7 种形状)、音效(消行叮一声)。而且**完成度高**——你能玩起来,有成就感。

### 项目 B:小行星(Asteroids)

从零写一个小行星。技术栈同上。

需求:
- 飞船在屏幕中央,按 A/D 旋转,按 W 加速(有惯性),按空格发射子弹。
- 屏幕上有 5-10 个随机移动的小行星,可以分裂。
- 子弹击中小行星分裂成两个小的,最小的击中后消失。
- 飞船撞小行星失败。
- 屏幕环绕(飞出右边从左边回来)。

时间预算:1 周。

为什么推荐:Asteroids 教你**向量数学**——位置、速度、夹角、点乘。Phase 3 你要做 3D,3D 数学是 2D 数学的扩展,2D 玩熟了 3D 就好学。

### 项目 C:贪吃蛇加强版

经典贪吃蛇 + 一些扩展。技术栈同上。

需求:
- 蛇按方向键移动,吃食物变长。
- 撞墙或撞自己失败。
- 加分系统。
- 加难度系统:吃到一定分数,蛇变快,生成障碍物。
- 加道具:吃到金色食物暂时无敌。

时间预算:4-7 天。

为什么推荐:贪吃蛇最简单,**保证你能完成**。如果你想"先做一个能跑的游戏再考虑复杂的",选这个。完成度比技术难度重要——做完一个简单游戏比半途而废一个复杂游戏收获大。

### 不推荐的项目

- **3D 游戏**:Phase 2 还没教 3D,做不出来。留到 Phase 3。
- **多人对战**:网络是 Phase 5 的事。
- **复杂的物理**:刚体物理要等 Phase 4 性能优化做完才能玩得起。

## §6 · 推荐配合的 deep-dive

`/home/sun/src/handmade-hero-guide/days/phase-1/deep-dives/` 里有三篇是进 Phase 2 前必读的:

### `win32-to-winit.md`(强推荐)

把 Win32 API 在 winit 里对应的接口逐条映射。Phase 2 你会反复用 winit 开窗、读键鼠、画帧。这篇让你**迁移成本最小化**——你在 Phase 1 学的 Win32 知识不会白学,它们在 winit 里都有对应物。

特别有用的章节:Win32 的 `WM_KEYDOWN` 在 winit 里是 `WindowEvent::KeyboardInput { state: Pressed, ... }`;Win32 的 `WM_PAINT` 是 `Event::RedrawRequested`;Win32 的 `SetWindowLongPtr` 设置用户数据,在 winit 里用 `Window::set_user_data`(或自己包一个 struct)。

### `hot-reload-rust.md`(强推荐)

Rust 版热重载的具体实现。包含:`Cargo.toml` 怎么写 `cdylib`、`#[no_mangle] pub extern "C" fn` 怎么写、inotify / `ReadDirectoryChangesW` 怎么监听文件变化、dll 卸载加载的内存安全注意点。

Phase 2 你天天热重载,这篇让你"一次配好,余生无忧"。

### `platform-game-separation.md`(强推荐)

Casey 在 HH Phase 1 末尾做的"平台层 / 游戏层"分离的完整 reasoning。为什么这样分、为什么不那样分、什么时候允许破坏这个分离(几乎不允许)。

Phase 2 你会动不动想"这个函数放平台层还是游戏层",这篇给你判断标准。

---

`/home/sun/src/handmade-hero-guide/days/phase-2/deep-dives/` 里也有几篇进 Phase 2 第一周可以读的:

### `math-foundations-for-games.md`(推荐)

2D 向量、矩阵、点乘叉乘的实战。Phase 2 你写碰撞、写移动、写摄像机全都要。**不需要先读**,等你 Phase 2 第一周卡壳了,回头来读。

### `entity-system.md`(后期再读)

Casey 在 Phase 2 Day 50+ 才开始演化 entity 系统。这篇是 Day 50 之后再读的。Phase 2 第一周你还停留在"Vec + index"阶段,先别管 ECS 演化。

### `collision-detection.md`(中期再读)

Phase 2 Day 31-32 做碰撞时读。比 `math-foundations-for-games` 晚一周。

---

## 结语

Phase 1 是"造工具",Phase 2 是"用工具做东西"。你已经有一把好锤子(平台层),现在要学的是**怎么用这把锤子钉出好看的家具**(游戏)。

Phase 2 第一周你会觉得"很简单"——画个方块能动起来能有多难。但做到 Day 35-40 调跳跃手感的时候,你会开始抓头发——为什么这个曲线就是不对我胃口。**这是正常的,所有做过游戏的人都经历过**。Casey 在直播里反复调同样的曲线,直到他对了。

记住:Phase 2 的目标不是"做完一个小游戏",是"做出一个**好玩**的小游戏"。**好玩是工程目标,更是审美目标**。代码能跑只是第一关,跑得有手感才是第二关。

下一站:Day 26。打开你的 IDE,开始画第一个方块。
