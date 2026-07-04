
# 平台 / 游戏分离:从 naive main 到 cdylib 热重载的演化

> Handmade Hero Day 11 是全剧最重要的架构决策。Casey 把代码拆成"平台层"和"游戏层",通过函数指针通信。这个决策决定了后面 656 集的代码演化路径——为什么 HH 能两年开发不重写,核心就在这里。本文从"最 naive 的 main.rs"开始,一步步演化到"cdylib + libloading + 状态外置"的成熟架构,展示**为什么**这样设计、**怎么**实现、**有什么** trade-off。

## 0 · 为什么平台 / 游戏分离

你写一个最简单的游戏 demo:

```rust
fn main() {
    let window = winit::create_window();
    let mut player = Player { x: 100, y: 100 };
    
    loop {
        let input = window.poll_input();
        
        // 游戏逻辑
        if input.left { player.x -= 1; }
        if input.right { player.x += 1; }
        
        // 渲染
        window.clear();
        window.draw_rect(player.x, player.y, 50, 50, GREEN);
        window.present();
    }
}
```

100 行,跑起来。看起来没问题。但你想:

1. **换平台**(从桌面到 Web 到手机):整个 main 都要重写。游戏逻辑(玩家移动)和平台代码(开窗、渲染)纠缠在一起。
2. **测试游戏逻辑**:你的 `if input.left` 这段是游戏逻辑,但它在 main 里。要测试它,你要跑整个程序。
3. **热重载**:你想"改一行代码不重启程序",但所有代码都在一个二进制里,改了要重编整个。

**根本问题**:**平台 / 游戏混合**。开窗、读输入是平台;玩家移动规则是游戏。混在一起,任何一个改动都影响全部。

### 解法:分层

把代码拆两层:

- **平台层**(platform layer):开窗、读输入、播音频、显示像素。和 OS / 硬件打交道。
- **游戏层**(game layer):游戏规则、物理、AI、渲染命令。**完全不知道**自己跑在什么 OS 上。

两层通过**接口**通信:

```
┌──────────────────────────────────┐
│ 平台层(知道 OS)                  │
│ - Win32 / Linux / macOS          │
│ - 开窗、读输入、播音频             │
└──────────────────────────────────┘
              ↑↓ 接口
┌──────────────────────────────────┐
│ 游戏层(不知道 OS)                │
│ - 玩家移动、碰撞、AI              │
│ - 渲染到内存 buffer              │
└──────────────────────────────────┘
```

游戏代码用平台层提供的"抽象服务",自己不调任何 OS API。这样:

- 换平台 = 换平台层,游戏代码不动
- 测试游戏 = 单独跑游戏,不需要真开窗
- 热重载 = 游戏编 .so,平台层 reload,状态保留

## 1 · 演化阶段 0:naive main(混合)

起点。所有代码在 main.rs:

```rust
// src/main.rs(混合,100% 依赖 winit)
use winit::*;

fn main() {
    let event_loop = EventLoop::new().unwrap();
    let window = event_loop.create_window(...).unwrap();
    
    let mut player_x = 100.0;
    let mut keys: HashSet<KeyCode> = HashSet::new();
    
    // 主循环
    loop {
        // 处理 winit 事件(平台代码)
        let event = event_loop.poll();
        match event {
            WinitEvent::KeyPressed(k) => { keys.insert(k); }
            WinitEvent::KeyReleased(k) => { keys.remove(&k); }
            _ => {}
        }
        
        // 游戏逻辑(应该独立)
        if keys.contains(&KeyCode::KeyA) { player_x -= 1.0; }
        if keys.contains(&KeyCode::KeyD) { player_x += 1.0; }
        
        // 渲染(平台 + 游戏混合)
        let mut buf = surface.buffer_mut().unwrap();
        for px in buf.iter_mut() { *px = 0xFF_00_00_00; }
        for dx in 0..50 {
            for dy in 0..50 {
                let x = player_x as i32 + dx;
                let y = 100 + dy;
                buf[y as usize * WIDTH + x as usize] = 0xFF_00_FF_00;
            }
        }
        buf.present().unwrap();
    }
}
```

问题:

- **游戏逻辑(`player_x -= 1.0`)和 winit 强耦合**:换平台要改这一段
- **没法测试**:要测试 `if keys.contains` 逻辑,要真开窗
- **没法热重载**:所有代码在 main 里,改了重编整个

## 2 · 演化阶段 1:游戏函数提取

把游戏逻辑提取到独立函数:

```rust
// src/main.rs(部分分离)
struct GameState {
    player_x: f32,
}

// 游戏函数(不依赖 winit!)
fn update_game(state: &mut GameState, left: bool, right: bool) {
    if left { state.player_x -= 1.0; }
    if right { state.player_x += 1.0; }
}

fn render_game(state: &GameState, buf: &mut [u32], width: usize) {
    for px in buf.iter_mut() { *px = 0xFF_00_00_00; }
    for dx in 0..50 {
        for dy in 0..50 {
            let x = state.player_x as i32 + dx;
            let y = 100 + dy;
            if x >= 0 && (x as usize) < width {
                buf[y as usize * width + x as usize] = 0xFF_00_FF_00;
            }
        }
    }
}

fn main() {
    // 平台层(main + winit)
    let window = ...;
    let mut state = GameState { player_x: 100.0 };
    let mut keys: HashSet<KeyCode> = HashSet::new();
    
    loop {
        // 处理事件
        // ...
        let left = keys.contains(&KeyCode::KeyA);
        let right = keys.contains(&KeyCode::KeyD);
        
        // 调游戏函数
        update_game(&mut state, left, right);
        render_game(&state, &mut buf, WIDTH);
    }
}
```

游戏函数 `update_game` / `render_game` **不再依赖 winit**!它们只接受原始数据(`bool` 表示按键,`&mut [u32]` 表示 framebuffer)。

这一步的好处:

- 游戏逻辑可以单元测试(`assert!(after_update.player_x < before)`)
- 换平台时,游戏函数不变
- 但还是不能热重载——所有代码在一个 crate

## 3 · 演化阶段 2:定义稳定接口

阶段 1 的游戏函数签名太具体(`left: bool, right: bool`)。一旦你要加按键(up / down),所有调用都要改。

定义一个**稳定接口**:

```rust
// src/main.rs

#[derive(Default)]
pub struct GameInput {
    pub left: bool,
    pub right: bool,
    pub up: bool,
    pub down: bool,
    pub action: bool,
    pub dt: f32,
}

#[derive(Default)]
pub struct GameState {
    pub player_x: f32,
    pub player_y: f32,
}

pub struct GameOutput<'a> {
    pub buffer: &'a mut [u32],
    pub width: usize,
    pub height: usize,
}

// 游戏主函数签名(稳定)
pub fn update_and_render(state: &mut GameState, input: &GameInput, output: GameOutput) {
    // 移动
    let speed = 200.0;
    if input.left  { state.player_x -= speed * input.dt; }
    if input.right { state.player_x += speed * input.dt; }
    if input.up    { state.player_y -= speed * input.dt; }
    if input.down  { state.player_y += speed * input.dt; }
    
    // 渲染
    for px in output.buffer.iter_mut() { *px = 0xFF_00_00_00; }
    // ... 画玩家
}
```

接口稳定后:

- 加按键:GameInput 加字段,游戏代码用,**main 不变**(只是填新字段)
- 改渲染分辨率:GameOutput 字段不变,游戏代码用 width / height 自适应
- 加音频:GameInput 不动,加一个 SoundOutput 参数

签名 `fn(&mut GameState, &GameInput, GameOutput)` 是 Casey 的核心设计。

## 4 · 演化阶段 3:GameMemory(状态外置)

阶段 2 还有问题:`GameState` 在 main 里。如果热重载,main 不变(它是平台),但 `GameState` 在 main 里意味着重编 main 后 state 重置。

解法:**把 GameState 包在 GameMemory 里,由平台层持有**。

```rust
// src/game.rs(独立文件)
pub struct GameMemory {
    pub is_initialized: bool,
    pub state: GameState,  // 实际游戏状态
}

// src/main.rs
fn main() {
    let mut memory = GameMemory::default();
    // memory 在 main 里,跨 reload 保留
    
    loop {
        let input = build_input();
        let mut output = build_output();
        
        // 调游戏(签名稳定)
        update_and_render(&mut memory, &input, output);
    }
}
```

`GameMemory` 的设计:

- **平台层持有**(它在 main 里,跨 reload 保留)
- **游戏代码使用**(通过 `&mut` 借用)
- **可序列化**(整个 dump 到文件 = 存档)
- **可测试**(从内存里 build 一个 GameMemory,跑 update,看变化)

Casey 还把 GameMemory 分两区:

- `permanent`:跨 reload 保留(玩家进度)
- `transient`:每帧 reset(渲染命令)

我们 Day 014 详细讲。

## 5 · 演化阶段 4:跨 crate 拆分

到目前所有代码在一个 crate(`main.rs` + `game.rs`)。要热重载,游戏代码必须能"独立编译"。

把游戏代码拆到独立 crate:

```
handmade-hero/
├── Cargo.toml          (workspace)
├── platform/           (bin,平台层)
│   ├── Cargo.toml
│   └── src/main.rs
└── game/               (lib,游戏层)
    ├── Cargo.toml
    └── src/lib.rs
```

```toml
# Cargo.toml(workspace)
[workspace]
members = ["platform", "game"]
resolver = "2"
```

```toml
# game/Cargo.toml
[lib]
name = "handmade_game"
path = "src/lib.rs"
```

```toml
# platform/Cargo.toml
[dependencies]
handmade_game = { path = "../game" }
winit = "0.30"
softbuffer = "0.4"
```

```rust
// platform/src/main.rs
use handmade_game::{GameMemory, GameInput, GameOutput, update_and_render};

fn main() {
    let mut memory = GameMemory::default();
    // ... 调 update_and_render
}
```

现在 game crate 可以独立编译。但还是静态链接进 platform——改 game 要重编 platform。

## 6 · 演化阶段 5:cdylib + libloading(热重载)

最后一步。把 game crate 编译成 cdylib(C ABI 动态库),platform 用 libloading 加载。

```toml
# game/Cargo.toml
[lib]
name = "handmade_game"
crate-type = ["cdylib"]  # 关键:cdylib
```

```rust
// game/src/lib.rs
#[no_mangle]
pub extern "C" fn update_and_render(
    memory: *mut GameMemory,
    input: *const GameInput,
    buffer: *mut u32,
    width: usize,
    height: usize,
    dt: f32,
) {
    let memory = unsafe { &mut *memory };
    let input = unsafe { &*input };
    let buffer = unsafe { std::slice::from_raw_parts_mut(buffer, width * height) };
    
    // 游戏逻辑(用 memory.state,平台层保留)
}
```

为什么用裸指针?**C ABI 要求**。Rust 的 `&mut` 是 fat pointer(指针 + 生命周期),C 不理解。裸指针就是地址,跨 FFI 边界安全。

```rust
// platform/src/main.rs
use libloading::Library;

fn main() {
    let mut memory = GameMemory::default();
    let path = "./target/debug/libhandmade_game.so";
    
    let mut lib = unsafe { Library::new(path) }.unwrap();
    let mut last_mtime = std::fs::metadata(path).unwrap().modified().unwrap();
    
    loop {
        // 检测 reload
        let mtime = std::fs::metadata(path).unwrap().modified().unwrap();
        if mtime != last_mtime {
            std::thread::sleep(std::time::Duration::from_millis(50));
            lib = unsafe { Library::new(path) }.unwrap();
            last_mtime = mtime;
            println!("reloaded");
        }
        
        // 调游戏
        let func: libloading::Symbol<unsafe extern "C" fn(*mut GameMemory, *const GameInput, *mut u32, usize, usize, f32)> = 
            unsafe { lib.get(b"update_and_render") }.unwrap();
        let mut buf = vec![0u32; 1280 * 720];
        unsafe {
            func(
                &mut memory as *mut GameMemory,
                &input as *const GameInput,
                buf.as_mut_ptr(),
                1280, 720,
                dt,
            );
        }
        
        // 显示 buf(平台层职责)
    }
}
```

现在:

- game crate 改一行代码 → cargo build game → 生成新 .so
- platform 检测 mtime → reload → 下一帧用新代码
- **memory 不动**(在 platform 里),游戏状态保留

完整热重载工作流。

## 7 · 状态外置的关键

热重载能工作的核心:**状态不在 game crate**。

错误做法(状态在 game crate):

```rust
// game/src/lib.rs
static mut PLAYER_HP: i32 = 100;  // ← 状态在 game crate!

#[no_mangle]
pub extern "C" fn update(...) {
    unsafe {
        PLAYER_HP -= 1;  // 玩家每帧掉血
    }
}
```

reload 时:

1. 旧 .so 卸载,`PLAYER_HP` 内存释放
2. 新 .so 加载,`PLAYER_HP` 重新初始化为 100
3. 玩家之前打到 HP=30 → reload 后 HP=100 ← **bug**

正确做法(状态在 platform):

```rust
// game/src/lib.rs
pub struct GameMemory {
    pub player_hp: i32,
}

#[no_mangle]
pub extern "C" fn update(memory: *mut GameMemory, ...) {
    let memory = unsafe { &mut *memory };
    memory.player_hp -= 1;  // 玩家掉血
}
```

reload 时:

1. 旧 .so 卸载,但 `memory` 在 platform 里,**不释放**
2. 新 .so 加载,平台层把同一个 `memory` 指针传给新代码
3. 新代码看到 `player_hp = 30`(玩家真实状态),继续

**状态外置**是热重载的物理前提。Casey 在 Day 011 设计 GameMemory 时已经为 Day 021 热重载铺路。

## 8 · 接口稳定性的契约

热重载的另一个前提:**函数签名跨 reload 一致**。

错误:

```rust
// V1
#[no_mangle]
pub extern "C" fn update(memory: *mut GameMemory) { ... }

// V2(你改了签名)
#[no_mangle]
pub extern "C" fn update(memory: *mut GameMemory, input: *const GameInput) { ... }
```

reload V2 时,platform 还按 V1 签名调用——参数不对,栈帧错乱,crash 或 UB。

正确:**签名一旦定,不再改**。

如果真要改签名(加参数),怎么做?

1. 重新启动 platform(失去热重载便利,但 OK)
2. 或:用版本号 + 兼容层

```rust
#[no_mangle]
pub extern "C" fn update_v2(memory: *mut GameMemory, input: *const GameInput) { ... }

// platform
let func: Symbol<...> = unsafe { lib.get(b"update_v2").or_else(|_| lib.get(b"update")) };
```

但 Casey 不这么做——他保持签名稳定,新需求通过 GameMemory / GameInput 加字段解决。

```rust
pub struct GameInput {
    pub dt: f32,
    pub controllers: [GameController; 5],
    // 加新字段在这里:
    pub new_feature_flag: bool,  // ← 新加,旧字段不动
}
```

加字段需要 platform 配合(填新字段),但签名不变,热重载工作。

## 9 · Rust 所有权 + 热重载的张力

libloading 的 `Symbol<Fn>` 借用 `Library`:

```rust
let lib = Library::new(...)?;
let func: Symbol<Fn> = unsafe { lib.get(b"update") }?;
// func 借用 lib
drop(lib);  // ← 错!func 还在借用
```

Rust 借用检查器阻止"被借用的对象被 drop"。但热重载需要"reload = drop 旧 Library + 加载新"——和借用冲突。

解法:

**解法 1:Symbol 用完才 reload**

```rust
loop {
    let func: Symbol<Fn> = lib.get(...)?;
    func(...);  // 用完
    // func drop,lib 不再被借用
    if needs_reload {
        let new_lib = Library::new(...)?;
        std::mem::replace(&mut lib, new_lib);  // 现在 OK
    }
}
```

每帧重新 `get` symbol(开销几纳秒),用完才 reload。

**解法 2:函数指针(Symbol → fn pointer)**

```rust
let func: Symbol<Fn> = lib.get(...)?;
let func_ptr: unsafe extern "C" fn(...) = func.into_raw();  // 放弃 Symbol 借用
// 现在 lib 可以替换(func_ptr 是裸函数指针,不绑 Library)
```

但 `func_ptr` 指向 lib 的代码段。lib 卸载后,代码段释放,func_ptr 指向无效内存——UB。

要么 lib 永不卸载(Box::leak),要么确保 reload 时不用旧 func_ptr。

**解法 3:Arc<Library>**

```rust
let lib = Arc::new(Library::new(...)?);
let lib_for_func = lib.clone();
let func = unsafe { lib_for_func.get(...)? };
// 主线程持有 lib,reload 时替换
```

Arc 让多个 owner,reload 时旧 lib 在 func 还活着时不释放。

实战推荐:**解法 1**(简单清楚)或 **`hot-lib-reloader` crate**(封装好)。

## 10 · 平台层暴露给游戏的 API

平台层不只是"调游戏函数",还**反向**给游戏提供"服务":

```rust
// 平台层暴露的 API(平台 → 游戏)
pub struct PlatformAPI {
    pub read_file: extern "C" fn(path: *const c_char, ...) -> FileHandle,
    pub write_file: extern "C" fn(path: *const c_char, ...) -> bool,
    pub log: extern "C" fn(msg: *const c_char),
    pub get_time: extern "C" fn() -> f64,
    // ...
}

// 平台层调用游戏时,把 PlatformAPI 传进去
#[no_mangle]
pub extern "C" fn update_and_render(
    memory: *mut GameMemory,
    input: *const GameInput,
    platform: *const PlatformAPI,  // ← 平台服务
) {
    let platform = unsafe { &*platform };
    
    // 游戏代码调平台 API
    let file_data = (platform.read_file)(b"level.txt\0".as_ptr(), ...);
}
```

为什么这样?**游戏代码不知道 OS,但偶尔需要 OS 服务**(读文件、log、时间)。这些通过 platform API 间接调,保持解耦。

Casey HH 全剧用这个模式。读资产(BMP / WAV)、写存档、debug log,全走 platform API。

## 11 · 完整架构图

```
┌──────────────────────────────────────────────────────────┐
│ 平台层(platform crate,bin)                              │
│                                                          │
│ ┌────────────────────────────────────────────────────┐  │
│ │ OS 抽象:winit(window) / softbuffer(display) /      │  │
│ │ cpal(audio) / gilrs(input) / libloading(reload)    │  │
│ └────────────────────────────────────────────────────┘  │
│                       ↑↓                                │
│ ┌────────────────────────────────────────────────────┐  │
│ │ 平台服务:read_file / write_file / log / get_time   │  │
│ └────────────────────────────────────────────────────┘  │
│                       ↑↓                                │
│ ┌────────────────────────────────────────────────────┐  │
│ │ GameMemory 持有(permanent + transient)              │  │
│ └────────────────────────────────────────────────────┘  │
│                       ↑↓                                │
│ ┌────────────────────────────────────────────────────┐  │
│ │ libloading 加载 / reload libhandmade_game.so        │  │
│ └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
                       ↑↓ FFI 边界
┌──────────────────────────────────────────────────────────┐
│ 游戏层(game crate,cdylib)                              │
│                                                          │
│ ┌────────────────────────────────────────────────────┐  │
│ │ update_and_render(memory, input, platform_api)     │  │
│ │   游戏逻辑:物理、AI、规则                          │  │
│ │   渲染:写像素到 buffer                            │  │
│ └────────────────────────────────────────────────────┘  │
│                                                          │
│ 注:状态在 GameMemory(平台持有),不在 game crate static │
└──────────────────────────────────────────────────────────┘
```

## 12 · 各阶段对比

| 阶段 | 描述 | 优点 | 缺点 |
|---|---|---|---|
| 0 | naive main | 简单 | 平台 / 游戏混合 |
| 1 | 提取游戏函数 | 游戏可测 | 接口不稳 |
| 2 | 稳定接口 | 接口稳 | 还是单 crate |
| 3 | GameMemory | 状态外置 | 不能 reload |
| 4 | 跨 crate | 独立编译 | 静态链接 |
| 5 | cdylib + libloading | **热重载** | 复杂(所有权 / ABI) |

Casey HH Day 11 直接跳到阶段 2-3(架构决策),Day 21 实现阶段 5(热重载)。

## 13 · 类似架构(业界)

平台 / 业务分离是通用模式:

- **Web**:Node.js Express 服务器 + 业务逻辑。Express 是"平台层",业务函数是"游戏层"
- **Mobile**:iOS ViewController + 业务 Model。VC 是平台,Model 是业务
- **Embedded**:RTOS + 应用。RTOS 提供 API,应用调用
- **Database**:PostgreSQL backend + extension。Backend 平台,extension 业务
- **Browser**:浏览器 + Web app。浏览器平台,JS 业务

共同特点:**平台稳定,业务多变**。平台层抽象好,业务层专注逻辑。

## 14 · 什么时候 NOT 用这种架构

平台 / 游戏分离不是万能。这些场景不适用:

- **简单脚本**:你写一个 100 行的命令行工具。分两层 over-engineering
- **实验代码**:快速验证想法。先写,有效再重构
- **学习代码**:刚学 Rust,写一个 main 跑通就行。等熟悉了再分

Casey 在 HH Day 1-10 也是混合代码(实验),Day 11 开始分离。**先 work,再分离**。

## 15 · 给你的建议

1. **Phase 1 早期(day001-010)**:阶段 0-1,所有代码在 main,先跑通
2. **Phase 1 中期(day011-020)**:阶段 2-3,定义稳定接口,GameMemory 状态外置
3. **Phase 1 末期(day021-025)**:阶段 4-5,跨 crate + cdylib + 热重载
4. **Phase 2+**:架构稳定,专心写游戏代码,平台层基本不动

不要"一开始就完美架构"——**先简单,再演化**。Casey 自己也是这样:Day 1-10 简单,Day 11 重构,Day 21 再升级。

## 16 · 总结

平台 / 游戏分离的精髓:

1. **解耦**:平台处理 IO,游戏处理逻辑
2. **接口稳定**:签名不变,内部可换
3. **状态外置**:状态在平台层,游戏代码无状态
4. **动态加载**:游戏编 cdylib,平台 libloading
5. **热重载**:状态保留,代码替换

这五条是 Casey HH 25 集教给你的**架构核心**。后面 642 集都在这个架构上演化,不再大改。

理解这套设计,你就理解了"长期可维护的游戏引擎架构"。

## 延伸阅读

本仓库:
- [day011](../day011.md)——平台 / 游戏分离架构决策
- [day014](../day014.md)——GameMemory
- [day021](../day021.md)——热重载第一步
- [deep-dives/hot-reload-rust.md](hot-reload-rust.md)——热重载深入

外部:
- Martin Fowler "Separated Presentation":https://martinfowler.com/eaaDev/SeparatedPresentation.html
- Handmade Hero Day 11 video:https://guide.handmadehero.org/code/day011/
- bevy 引擎架构(类似思想):https://bevyengine.org/news/introducing-bevy/
