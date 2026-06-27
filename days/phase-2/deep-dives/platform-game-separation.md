---
phase: 2
type: deep-dive
title: "平台层与游戏层分离:从 Win32 callback 到 Rust cdylib"
domains: [game, rust, linux]
duration: "2-3h"
prereqs: ["day026", "day029", "phase-0/08-processes-and-signals"]
---

# 平台层与游戏层分离 · 从 Win32 callback 到 Rust cdylib

> "我现在写的代码,5 年后能不能换平台?"—— Casey 在 Day 026 提了这个问题。他的答案是一套**三明治架构**:平台层(开窗/输入/音频/热重载)夹着接口层(GameMemory/GameInput/GameSound),接口层夹着游戏层(规则/物理/AI)。换平台 = 改平台层,游戏层零改动。这个抽象是 Handmade Hero 全 667 天的**架构基石**。本文 3 小时讲透它的过去、现在和 Rust 实现。

## 0 · 这篇文章解决什么问题

你做了 Phase 1 的 25 天,能开窗、能显示像素、能读键盘。所有代码都堆在 `main.rs` 里——winit 的回调里写游戏逻辑,gamepad 事件里改 entity,buffer 写完顺手画 UI。看起来没问题,直到你想:

1. **从桌面切到 Web**(用 wasm-bindgen + web-sys 跑浏览器版):你的 winit 代码全部失效,要重写整个游戏。
2. **加单元测试**:你的 update 函数依赖 `winit::Window`,没法在没窗口的 CI 里跑。
3. **多人协作**:有人写游戏规则,有人写平台层,两人改同一个 `main.rs` 互相踩。
4. **热重载**:你改一行游戏代码,要重新启动游戏,加载到对应关卡看效果。

这些问题根源都是一个:**游戏代码和平台代码混在一起**。Casey 在 Day 026 把它们拆开,从此后面 640 天**每次重构都不动摇这个分层**。

读完本文,你能:

- 解释为什么 Win32 callback 模型天然让游戏和平台耦合
- 设计一个跨平台游戏接口(GameMemory / GameInput / GameOffscreenBuffer)
- 用 Rust cdylib + libloading 实现热重载
- 处理 cdylib 跨 FFI 的所有权 / lifetime / unsafe 边界
- 把这套架构迁移到 Web / Android / iOS / 主机

## 1 · 历史回顾:Win32 callback 是怎么把代码耦合的

### 1.1 Win32 的窗口消息循环

Windows API(简称 Win32)的核心抽象是**窗口消息**(window message)。你创建一个窗口,Windows 给你发各种消息——按键、鼠标、resize、关闭、重绘。你的程序在一个循环里不断取出消息并处理。

最简的 Win32 游戏看起来这样(C 代码):

```c
// Win32 平台层骨架
LRESULT CALLBACK WindowProc(HWND hwnd, UINT uMsg, WPARAM wParam, LPARAM lParam) {
    switch (uMsg) {
    case WM_KEYDOWN:
        // 处理按键 ↓↓↓ 这里直接写游戏逻辑
        if (wParam == 'W') {
            player.y -= 5;          // ← 游戏代码混在平台代码里!
        }
        return 0;
    case WM_PAINT:
        // 重绘 ↓↓↓ 这里直接画游戏画面
        DrawPlayer(player);         // ← 游戏代码混在平台代码里!
        return 0;
    }
    return DefWindowProc(hwnd, uMsg, wParam, lParam);
}

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE, LPSTR, int) {
    HWND hwnd = CreateWindow(...);
    ShowWindow(hwnd, SW_SHOW);

    MSG msg;
    while (GetMessage(&msg, NULL, 0, 0)) {
        TranslateMessage(&msg);
        DispatchMessage(&msg);       // ← 触发 WindowProc 回调
    }
    return 0;
}
```

这看起来简单,但有 4 个**致命问题**:

1. **游戏代码嵌入在平台代码里**——`player.y -= 5` 和 `WM_KEYDOWN` 绑死了。换平台(到 Linux/X11)要重写这段。
2. **`player` 变量必须是全局**——WindowProc 是回调,没法传 context(除非用 `SetWindowLongPtr` hack)。全局变量是工程灾难。
3. **测试困难**——你没法在没窗口的环境下测 `WM_KEYDOWN` 处理逻辑。
4. **多人冲突**——平台层改 winit 参数,游戏层改 player 行为,都在同一个文件,git 永远在 merge conflict。

### 1.2 业界的解法演化

#### 时代 1:消息映射宏(MFC, 1992)

微软的 MFC 用宏把消息和处理函数关联,部分解耦:

```cpp
BEGIN_MESSAGE_MAP(CMyView, CView)
    ON_WM_KEYDOWN()      // 把 WM_KEYDOWN 路由到 OnKeyDown
    ON_WM_PAINT()        // 把 WM_PAINT 路由到 OnPaint
END_MESSAGE_MAP()

void CMyView::OnKeyDown(UINT nChar, ...) {
    if (nChar == 'W') player.y -= 5;
}
```

游戏代码还是混在视图类里,只是分层稍微清楚。

#### 时代 2:框架抽象(SDL, 1998)

Sam Lantinga 写了 SDL(Simple DirectMedia Layer),把所有平台的窗口/输入/音频封装成统一 API:

```c
SDL_Event e;
while (SDL_PollEvent(&e)) {
    if (e.type == SDL_KEYDOWN && e.key.keysym.sym == SDLK_w) {
        player.y -= 5;
    }
}
SDL_RenderCopy(renderer, player_texture, ...);
```

平台层跨平台了(同一份代码在 Win/Linux/Mac 都跑),但**游戏代码还是写在主循环里**。

#### 时代 3:Game Loop 分离(id Software, Quake, 1996)

John Carmack 在 Quake 里把"游戏循环"和"平台循环"拆开:

```c
// 平台层
int main() {
    InitPlatform();  // 开窗、初始化 D3D / OpenGL
    while (running) {
        ProcessEvents();    // 平台事件 → 填 input
        GameLoop(input);    // 调用游戏层
        SwapBuffers();
    }
}

// 游戏层(独立 .exe 或 .dll)
void GameLoop(Input* input) {
    UpdateWorld(input);
    RenderWorld();
}
```

这是**真正的分离**——游戏层是一个函数,平台层调用它。换平台只改 `InitPlatform` / `ProcessEvents` / `SwapBuffers`,游戏层 `GameLoop` 不动。

#### 时代 4:Handmade Hero(2014)

Casey 把 Carmack 的模型推到极致:

1. 游戏层编译成**独立动态库**(`handmade_hero.dll`)
2. 平台层只负责"调游戏层的 update_and_render 函数"
3. 平台层维护一个**持久内存块**(GameMemory),每帧传给游戏层
4. 平台层按快捷键重新加载 cdylib,**热重载**

这就是 HH 的"三明治架构"。

## 2 · 三明治架构详解

### 2.1 三层

```
┌─────────────────────────────────────────────────────┐
│  平台层(platform layer)                            │
│  • 开窗(winit / X11 / Win32)                       │
│  • 输入(键盘 / 鼠标 / 手柄)                        │
│  • 音频(cpal / ALSA / DirectSound)                │
│  • 文件 IO(std::fs / mmap)                        │
│  • 热重载(libloading / dlopen)                    │
│  • 时间(clock_gettime / QueryPerformanceCounter)  │
└─────────────────────────────────────────────────────┘
                    ↕ 平台 API
┌─────────────────────────────────────────────────────┐
│  接口层(platform-game interface)                   │
│  • GameMemory(持久内存,游戏层独占)                │
│  • GameInput(每帧输入,平台层填充)                 │
│  • GameOffscreenBuffer(每帧输出像素,游戏层写)     │
│  • GameSoundBuffer(每帧音频样本,游戏层写)         │
└─────────────────────────────────────────────────────┘
                    ↕ 函数调用(FFI)
┌─────────────────────────────────────────────────────┐
│  游戏层(game layer)                                │
│  • update_and_render(memory, input, buffer, dt)     │
│  • update_sound(memory, sound_buffer, samples)      │
│  • World / Entity / AI / Physics / Collision        │
│  • 资产加载 / 缓存                                 │
└─────────────────────────────────────────────────────┘
```

**核心原则**:游戏层**只知道接口层**,不知道平台层的存在。游戏层看不到 `winit::Window`,看不到 `cpal::Stream`,看不到任何平台类型。

### 2.2 接口层:GameMemory

`GameMemory` 是**游戏层独占的持久内存**。平台层分配一次(比如 1 GB),把指针 + 大小传给游戏层。游戏层把它当 raw memory 用(自己的 arena / 自由分配)。

```rust
// 接口层定义(平台和游戏共享)
pub struct GameMemory {
    pub permanent: Box<[u8]>,    // 持久存储(整个游戏周期)
    pub transient: Box<[u8]>,    // 瞬时存储(每帧重新分配)
    pub permanent_size: usize,
    pub transient_size: usize,
}

impl GameMemory {
    pub fn new(permanent_mb: usize, transient_mb: usize) -> Self {
        let permanent_size = permanent_mb * 1024 * 1024;
        let transient_size = transient_mb * 1024 * 1024;
        Self {
            permanent: vec![0u8; permanent_size].into_boxed_slice(),
            transient: vec![0u8; transient_size].into_boxed_slice(),
            permanent_size,
            transient_size,
        }
    }
}
```

游戏层用这内存做自己的 arena 分配:

```rust
#[no_mangle]
pub extern "C" fn update_and_render(
    memory: &mut GameMemory,
    input: &GameInput,
    buffer: &mut GameOffscreenBuffer,
    dt: f32,
) {
    // 把 raw memory 解释成 GameState
    let state: &mut GameState = unsafe {
        let p = memory.permanent.as_mut_ptr() as *mut GameState;
        &mut *p
    };

    // 第一次调用,初始化
    if !state.initialized {
        state.player = Player::new();
        state.world = World::new();
        state.initialized = true;
    }

    // 更新
    state.player.update(input, dt);
    state.world.update(dt);

    // 渲染
    state.render_to(buffer);
}
```

**关键设计**:平台层不分配游戏层的任何类型(它不知道 `Player` / `World` / `GameState` 长什么样)。平台层只分配"一段字节",游戏层自己解释。

### 2.3 接口层:GameInput

```rust
pub struct GameInput {
    pub dt: f32,                              // 这一帧耗时(秒)
    pub controllers: [GameController; 5],     // 最多 5 个手柄 / 键盘
}

pub struct GameController {
    pub is_connected: bool,
    pub is_analog: bool,                      // 模拟摇杆 vs 数字按键
    pub stick_average_x: f32,                 // -1.0 ~ 1.0
    pub stick_average_y: f32,
    pub buttons: [GameButtonState; 6],        // 上下左右 A B
}

pub struct GameButtonState {
    pub half_transition_count: u32,           // 这一帧按下/松开次数
    pub ended_down: bool,                     // 这一帧结束时是否按下
}
```

平台层每帧填好这个结构体,游戏层读它。

**关键设计**:
- 平台层不区分键盘 / 手柄 / 触屏——把它们都"翻译"成统一的 GameController。
- 游戏层永远问 `controllers[0].buttons[UP].ended_down`,不知道也不关心是键盘还是手柄。

按钮的 `half_transition_count` 让游戏层检测"按下边沿"(这一帧按下)和"松开边沿"(这一帧松开):

```rust
// 检测"按下了 A 键"(从松开 → 按下)
let button = &input.controllers[0].buttons[BUTTON_A];
let pressed = button.half_transition_count > 0 && button.ended_down;

// 或者更准确的边沿检测
let pressed_now = button.ended_down;
let was_pressed = button.half_transition_count > 0 && !button.ended_down;
// 上面这种"边沿检测"在 Day 006 Casey 详细讲
```

### 2.4 接口层:GameOffscreenBuffer

```rust
#[repr(C)]
pub struct GameOffscreenBuffer {
    pub width: i32,
    pub height: i32,
    pub pitch: i32,                           // 一行多少字节
    pub bytes_per_pixel: i32,                 // 通常是 4(BGRA / RGBA)
    pub memory: *mut u8,                      // 像素数据,游戏层写
}
```

平台层分配一块内存,把指针和尺寸告诉游戏层。游戏层直接写像素(0xBGRA 表示一个蓝色像素)。

**关键设计**:
- 平台层不在乎像素怎么算出来的,只负责"把这块内存的内容显示到屏幕"。
- 游戏层不在乎屏幕是 X11 window 还是 Win32 window 还是 HTML5 canvas,只负责"把这块内存填上像素"。
- `#[repr(C)]` 保证内存布局和 C 一致(避免 Rust 的 ZST padding 优化),FFI 安全。

### 2.5 接口层:GameSoundBuffer

类似 GameOffscreenBuffer,但内容是音频样本(int16 stereo):

```rust
#[repr(C)]
pub struct GameSoundOutputBuffer {
    pub samples_per_second: i32,              // 通常是 48000
    pub sample_count: i32,                    // 这一帧要多少样本
    pub samples: *mut i16,                    // 立体声交替(L R L R ...)
}
```

平台层每帧问"要多少样本",游戏层填。平台层把样本推到 cpal / ALSA / DirectSound。

## 3 · Rust 实现完整骨架

下面是一个完整的可运行示例(简化版,核心结构齐全)。

### 3.1 项目结构

```
handmade-hero/
├── Cargo.toml
├── src/
│   ├── main.rs              # 平台层(bin crate)
│   ├── shared.rs            # 接口层(共享)
│   ├── platform/
│   │   ├── mod.rs
│   │   ├── window.rs        # winit
│   │   ├── audio.rs         # cpal
│   │   └── reload.rs        # libloading
│   └── game/
│       ├── lib.rs           # 游戏层 cdylib 入口
│       ├── world.rs
│       └── player.rs
```

### 3.2 Cargo.toml

```toml
[package]
name = "handmade-hero"
version = "0.1.0"
edition = "2021"

[lib]
name = "handmade_hero"
crate-type = ["cdylib", "rlib"]  # 同时是 cdylib(给 libloading)和 rlib(给测试)

[[bin]]
name = "handmade-hero"
path = "src/main.rs"

[dependencies]
winit = "0.30"
softbuffer = "0.4"
cpal = "0.15"
libloading = "0.8"
```

### 3.3 src/shared.rs(接口层)

```rust
// shared.rs —— 平台和游戏共享的类型
// 这个文件必须没有 platform / game 依赖,完全自包含

use std::ffi::c_void;

pub const MAX_CONTROLLERS: usize = 5;
pub const BUTTON_COUNT: usize = 6;
pub const BUTTON_UP: usize = 0;
pub const BUTTON_DOWN: usize = 1;
pub const BUTTON_LEFT: usize = 2;
pub const BUTTON_RIGHT: usize = 3;
pub const BUTTON_A: usize = 4;
pub const BUTTON_B: usize = 5;

#[repr(C)]
pub struct GameButtonState {
    pub half_transition_count: u32,
    pub ended_down: bool,
}

#[repr(C)]
pub struct GameController {
    pub is_connected: bool,
    pub is_analog: bool,
    pub stick_average_x: f32,
    pub stick_average_y: f32,
    pub buttons: [GameButtonState; BUTTON_COUNT],
}

#[repr(C)]
pub struct GameInput {
    pub dt: f32,
    pub controllers: [GameController; MAX_CONTROLLERS],
}

#[repr(C)]
pub struct GameOffscreenBuffer {
    pub width: i32,
    pub height: i32,
    pub pitch: i32,
    pub bytes_per_pixel: i32,
    // 注意:不用 *mut u8,改用 Vec<u8> + extern "C" 包装,避免 unsafe
    pub memory: Vec<u32>,
}

#[repr(C)]
pub struct GameMemory {
    pub permanent_storage_size: usize,
    pub permanent_storage: *mut c_void,         // raw pointer,游戏层解释
    pub transient_storage_size: usize,
    pub transient_storage: *mut c_void,
}

// FFI 函数签名
pub type UpdateAndRenderFn = extern "C" fn(
    &mut GameMemory,
    &GameInput,
    &mut GameOffscreenBuffer,
    f32,                                  // dt
);
```

**关键点**:
- 所有结构体 `#[repr(C)]`,FFI 友好。
- `GameMemory` 用 `*mut c_void`——平台层分配,游戏层 cast 成 `*mut GameState`。
- `UpdateAndRenderFn` 是函数指针类型,平台层用 libloading 加载。

### 3.4 src/game/lib.rs(游戏层 cdylib)

```rust
// game/lib.rs —— 编译成 handmade_hero.so / .dll / .dylib

use crate::shared::*;

// 这个 mod 是 shared.rs,可以用 include! 或 mod 引入
mod shared { include!("../shared.rs"); }

mod world;
mod player;

// 游戏状态:每个字段大小固定,可以放进 GameMemory
#[repr(C)]
pub struct GameState {
    pub initialized: bool,
    pub player: player::Player,
    pub world: world::World,
    pub green: f32,
}

// 游戏层入口
#[no_mangle]
pub extern "C" fn update_and_render(
    memory: &mut GameMemory,
    input: &GameInput,
    buffer: &mut GameOffscreenBuffer,
    _dt: f32,
) {
    // 把 raw memory cast 成 GameState
    let state: &mut GameState = unsafe {
        assert!(!memory.permanent_storage.is_null());
        assert!(memory.permanent_storage_size >= std::mem::size_of::<GameState>());
        &mut *(memory.permanent_storage as *mut GameState)
    };

    // 第一次调用,初始化
    if !state.initialized {
        state.player = player::Player::new();
        state.world = world::World::new();
        state.green = 0.0;
        state.initialized = true;
    }

    // 更新:按键改变绿度
    let ctrl = &input.controllers[0];
    if ctrl.buttons[BUTTON_UP].ended_down {
        state.green = (state.green + 0.01).min(1.0);
    }
    if ctrl.buttons[BUTTON_DOWN].ended_down {
        state.green = (state.green - 0.01).max(0.0);
    }

    // 渲染:全屏填充
    let color = (state.green * 255.0) as u32;
    let pixel = (color << 8) | 0xff000000; // 0xAARRGGBB,alpha=ff,green=color
    for px in buffer.memory.iter_mut() {
        *px = pixel;
    }
}
```

**关键点**:
- `#[no_mangle]` 让 Rust 不修改函数名(默认 Rust 会 name-mangling,FFI 必须禁掉)。
- `extern "C"` 用 C ABI(默认 Rust ABI 不稳定,不能用于 FFI)。
- raw pointer cast 必须在 `unsafe` 里——编译器没法保证指针有效。
- `assert!` 检查是动态保护,防止 GameMemory 没初始化。

### 3.5 src/platform/reload.rs(热重载)

```rust
// platform/reload.rs —— libloading 封装

use libloading::{Library, Symbol};
use std::path::Path;
use std::time::SystemTime;

use crate::shared::*;

pub struct GameCode {
    pub library: Library,
    pub update_and_render: UpdateAndRenderFn,
    pub last_loaded: SystemTime,
}

impl GameCode {
    pub fn load(path: &Path) -> Result<Self, Box<dyn std::error::Error>> {
        // Linux/macOS 用 .so / .dylib,Windows 用 .dll
        // cargo build 时 --lib 编译 cdylib 输出到 target/{debug,release}/
        let library = unsafe { Library::new(path)? };
        let symbol: Symbol<UpdateAndRenderFn> = unsafe {
            library.get(b"update_and_render")?
        };
        // Symbol 转 raw 函数指针
        let update_and_render: UpdateAndRenderFn = *symbol;
        let last_loaded = std::fs::metadata(path)?.modified()?;

        Ok(Self {
            library,
            update_and_render,
            last_loaded,
        })
    }

    pub fn check_reload(&mut self, path: &Path) -> bool {
        // 检查文件修改时间,变了就重新加载
        if let Ok(meta) = std::fs::metadata(path) {
            if let Ok(mtime) = meta.modified() {
                if mtime != self.last_loaded {
                    // 重新加载
                    if let Ok(new_code) = Self::load(path) {
                        *self = new_code;
                        return true;
                    }
                }
            }
        }
        false
    }
}
```

**关键点**:
- `Library::new` 是 unsafe——因为加载代码本身就 unsafe(任意 .so 可能有任意 bug)。
- `library.get(b"update_and_render")` 也是 unsafe——返回的 `Symbol` 持有 library 引用,library 卸载后 symbol 失效。
- 注意:**Symbol 必须在 Library 之前 drop**——否则 dangling pointer。Rust 的 drop 顺序是反序声明,所以把 `library` 字段放前面是对的。

### 3.6 src/main.rs(平台层)

```rust
// main.rs —— 平台层 bin

mod shared;
mod platform;

use shared::*;
use platform::reload::GameCode;
use winit::application::ApplicationHandler;
use winit::event::WindowEvent;
use winit::event_loop::{ActiveEventLoop, ControlFlow};
use winit::window::Window;

struct Platform {
    game_code: GameCode,
    memory: GameMemory,
    input: GameInput,
    window: Option<Window>,
    last_frame: std::time::Instant,
}

impl Platform {
    fn new() -> Self {
        // 加载游戏代码
        let lib_path = std::env::current_exe()
            .unwrap()
            .parent()
            .unwrap()
            .join("libhandmade_hero.so");
        let game_code = GameCode::load(&lib_path).expect("load game lib");

        // 分配 GameMemory(1 GB permanent + 1 GB transient)
        let permanent_size = 1024 * 1024 * 1024;
        let transient_size = 1024 * 1024 * 1024;
        let mut permanent_vec = vec![0u8; permanent_size];
        let mut transient_vec = vec![0u8; transient_size];
        let memory = GameMemory {
            permanent_storage_size: permanent_size,
            permanent_storage: permanent_vec.as_mut_ptr() as *mut _,
            transient_storage_size: transient_size,
            transient_storage: transient_vec.as_mut_ptr() as *mut _,
        };
        std::mem::forget(permanent_vec);  // 别让 Rust 释放,游戏层负责
        std::mem::forget(transient_vec);

        Self {
            game_code,
            memory,
            input: GameInput {
                dt: 0.016,
                controllers: std::array::from_fn(|_| GameController {
                    is_connected: false,
                    is_analog: false,
                    stick_average_x: 0.0,
                    stick_average_y: 0.0,
                    buttons: std::array::from_fn(|_| GameButtonState {
                        half_transition_count: 0,
                        ended_down: false,
                    }),
                }),
            },
            window: None,
            last_frame: std::time::Instant::now(),
        }
    }

    fn run_frame(&mut self, buffer: &mut GameOffscreenBuffer) {
        // 1. 检查热重载
        let lib_path = std::env::current_exe().unwrap().parent().unwrap()
            .join("libhandmade_hero.so");
        if self.game_code.check_reload(&lib_path) {
            println!("Hot reloaded game lib");
        }

        // 2. 算 dt
        let now = std::time::Instant::now();
        let dt = now.duration_since(self.last_frame).as_secs_f32() as f32;
        self.last_frame = now;
        self.input.dt = dt.min(1.0 / 30.0);  // 时间维度 clamp

        // 3. 调用游戏层
        (self.game_code.update_and_render)(
            &mut self.memory,
            &self.input,
            buffer,
            dt,
        );
    }
}

impl ApplicationHandler for Platform {
    fn resumed(&mut self, event_loop: &ActiveEventLoop) {
        let window = event_loop.create_window(
            winit::window::WindowAttributes::default()
                .with_title("Handmade Hero")
                .with_inner_size(winit::dpi::LogicalSize::new(1280, 720))
        ).unwrap();
        self.window = Some(window);
    }

    fn window_event(&mut self, event_loop: &ActiveEventLoop, _id: winit::window::WindowId,
                    event: WindowEvent) {
        match event {
            WindowEvent::CloseRequested => event_loop.exit(),
            WindowEvent::KeyPressed(e) => {
                // 填 GameInput
                let ctrl = &mut self.input.controllers[0];
                ctrl.is_connected = true;
                use winit::event::VirtualKeyCode::*;
                let idx = match e {
                    VirtualKeyCode::W => Some(BUTTON_UP),
                    VirtualKeyCode::S => Some(BUTTON_DOWN),
                    VirtualKeyCode::A => Some(BUTTON_LEFT),
                    VirtualKeyCode::D => Some(BUTTON_RIGHT),
                    VirtualKeyCode::Space => Some(BUTTON_A),
                    _ => None,
                };
                if let Some(i) = idx {
                    ctrl.buttons[i].ended_down = true;
                    ctrl.buttons[i].half_transition_count += 1;
                }
            },
            WindowEvent::AboutToWait => {
                // 跑一帧
                let mut buffer = GameOffscreenBuffer {
                    width: 1280, height: 720, pitch: 1280 * 4, bytes_per_pixel: 4,
                    memory: vec![0; 1280 * 720],
                };
                self.run_frame(&mut buffer);
                // 把 buffer 推到 softbuffer 显示(略)
                self.window.as_ref().unwrap().request_redraw();
            },
            _ => {}
        }
    }
}

fn main() {
    let mut platform = Platform::new();
    let event_loop = winit::event_loop::EventLoop::new().unwrap();
    event_loop.run_app(&mut platform).unwrap();
}
```

这是骨架,实际 HH 项目还有音频回调、定时器、错误处理,但**核心架构就是上面这套**。

## 4 · 关键设计决策

### 4.1 为什么用 GameMemory(大块 raw memory),不让游戏层自己分配?

**因为热重载**。如果游戏层用 `Box::new(Player::new())`,Rust 会在堆上分配。下次热重载,新的 game lib 加载,旧的 Player 实例的 vtable / 内部指针可能指向旧 lib 的代码——use-after-free。

`GameMemory` 把所有游戏状态放在**平台层管理的一块大内存**里。热重载时,新 lib 加载,但 GameMemory 不动——里面的数据完整保留。新 lib 把 raw memory cast 成 `*mut GameState`,拿到原来的数据。

这是 HH 热重载的**核心 trick**:状态外置,代码热换。

### 4.2 为什么 GameMemory 用 `*mut c_void`,不用泛型 `*mut T`?

如果接口层写 `pub struct GameMemory<T> { storage: *mut T }`,平台层必须知道 `T = GameState`——但 GameState 是游戏层的私有类型,平台层看不到。

用 `*mut c_void`(类型擦除),平台层只管"一段字节",游戏层自己 cast。这是**编译期解耦**。

### 4.3 为什么游戏层函数是 `extern "C"`,不是 `extern "Rust"`?

`extern "Rust"` 用 Rust ABI,Rust ABI **不稳定**(Rust 团队保留改名/改布局的权利)。两个 Rust 版本编译的 lib 可能 ABI 不兼容。

`extern "C"` 用 C ABI,跨 Rust 版本稳定。HH 热重载可能用不同 Rust 版本编译,所以必须 `extern "C"`。

### 4.4 为什么 `#[repr(C)]` 所有结构体?

Rust 默认会重排结构体字段以减少 padding(比如把 `bool` 字段挤到一个字节)。这破坏了 FFI 的内存布局假设。

`#[repr(C)]` 强制按 C 规则布局(声明顺序,每字段对齐到自己的对齐)。这样 `&GameMemory` 在 Rust 和 C 里布局一致。

### 4.5 为什么不用 trait object(`dyn GameInterface`)?

trait object 也能解耦,但有几个问题:

1. **跨 cdylib 边界失效**:trait object 的 vtable 指向 cdylib 内部代码。热重载后 vtable 失效。
2. **泛型代码膨胀**:trait 不能像 C 函数指针那样简单 ABI。
3. **abi_stability crate 复杂**:用 trait object 跨 dylib 需要 abi_stable crate,工程量大。

**函数指针 + raw struct 是更简单、更可靠的方案**——C 语言证明它能工作 50 年。

## 5 · 跨平台迁移

### 5.1 Linux

Linux 平台层用 winit(X11 / Wayland)+ cpal(ALSA / PulseAudio / PipeWire)+ gilrs(evdev)+ libloading(dlopen)。

```toml
[dependencies]
winit = { version = "0.30", features = ["x11", "wayland"] }
cpal = "0.15"
gilrs = "0.10"
libloading = "0.8"
```

cdylib 编译成 `libhandmade_hero.so`。运行时 `dlopen` 加载。

### 5.2 Windows

Windows 平台层用 winit(Win32)+ cpal(WASAPI / DirectSound)+ gilrs(XInput)+ libloading(LoadLibrary)。

cdylib 编译成 `handmade_hero.dll`。注意 Windows 上 cdylib 输出文件名不是 `lib*` 前缀,是 `*.dll`。

### 5.3 macOS

macOS 平台层用 winit(Cocoa)+ cpal(CoreAudio)+ gilrs(IOKit)+ libloading(dlopen)。

cdylib 编译成 `libhandmade_hero.dylib`。

### 5.4 Web(WASM)

Web 平台层用 winit(HTML canvas)+ web-sys(WebAudio)+ libloading 不可用(WASM 不支持 dlopen)。

**Web 没有热重载**——必须用 `web-sys` 静态链接。或者用 wasm-bindgen 的 lazy-loaded wasm module 实验性支持。

### 5.5 Android / iOS

Android 用 winit(Android NDK)+ cpal(OpenSL ES / AAudio)+ oboe-rs。iOS 用 winit(UIKit)+ cpal(AudioToolbox)。

热重载在移动端不可行——App 沙箱不允许 dlopen 任意路径。开发时只能用桌面。

### 5.6 跨平台一致性的关键

**接口层不变**。无论平台是 Win / Linux / Mac / Web / Mobile,`GameMemory` / `GameInput` / `GameOffscreenBuffer` 的定义完全一样。游戏层代码一份,平台层每个平台一份。

## 6 · 常见坑

### 6.1 Symbol 生命周期

```rust
let sym: Symbol<UpdateAndRenderFn> = unsafe { lib.get(b"update_and_render")? };
let f: UpdateAndRenderFn = *sym;  // ← 这步解引用拷贝了函数指针,摆脱 Symbol 依赖
drop(sym);  // 现在 sym 可以释放
```

如果不用 `*sym` 解引用,直接传 sym,Symbol drop 时 library 还活着——但 library drop 时 sym 必须先 drop。**drop 顺序**:声明反序——把 library 放在结构体第一字段,Symbol 不存进结构体(立即解引用)。

### 6.2 热重载时的状态兼容

游戏状态 `GameState` 加字段后,**旧 save 的内存布局和新代码不匹配**——新代码读到旧内存的字段是垃圾。

解决:

1. 加 `version: u32` 字段,启动时检查
2. 不兼容时强制清零 GameMemory(等同于重启游戏)

Casey 在 HH 里基本不加 version——开发期不断重启可接受。

### 6.3 cdylib 和 rlib 同时存在

```toml
[lib]
crate-type = ["cdylib", "rlib"]
```

cdylib 给 libloading(运行时),rlib 给单元测试(编译期)。`cargo test` 用 rlib,`cargo build` 同时产出两者。

### 6.4 dlclose 不工作(库没卸载)

Linux 上 `dlclose` 引用计数为 0 才真的卸载。如果有线程在执行 lib 内代码,dlclose 等同 no-op。热重载时多 unload 几次或忽略——Casey 接受"内存里堆几个旧 lib"的小代价。

## 7 · 业界做法对比

### 7.1 Casey HH(本文讲的方式)

- 优点:简单、跨平台、热重载、教学清晰
- 缺点:状态外置 + raw memory cast 不够安全

### 7.2 Bevy 的方式

Bevy 用 ECS,跨平台通过 bevy_render / bevy_window 等 plugin。热重载用 bevy_mod_hotreload(社区)。

- 优点:type-safe、trait 抽象
- 缺点:复杂、ECS 学习曲线陡

### 7.3 Unity 的方式

Unity 用 C# 脚本绑到 GameObject。换平台靠 Unity 跨平台 runtime(Mono / IL2CPP)。

- 优点:成熟的跨平台、可视化编辑器
- 缺点:不开源、C# 性能不如 C++ / Rust

### 7.4 Unreal 的方式

Unreal 用 C++ 类 + Hot Reload(基于 Live Coding)。游戏代码是 dynamic library。

- 优点:工业级、AAA 游戏
- 缺点:庞大、不开源

## 8 · 延伸阅读

本仓库:
- [day026.md](../day026.md) —— 三明治架构第一天
- [day029.md](../day029.md) —— 接口层完整
- [deep-dives/hot-reload.md](hot-reload.md) —— 热重载完整链路
- [deep-dives/rust-cdylib-and-ffi.md](rust-cdylib-and-ffi.md) —— cdylib 的 unsafe / lifetime 完整指南

外部:
- The Rust Book ch.19(Unsafe / FFI): https://doc.rust-lang.org/book/ch19-01-unsafe-rust.html
- The Rustonomicon(FFI / ABI): https://doc.rust-lang.org/nomicon/ffi.html
- libloading 文档: https://docs.rs/libloading/latest/libloading/

开源源码:
- libloading(Rust 热重载基础): https://github.com/nagisa/rust_libloading
- winit(跨平台窗口): https://github.com/rust-windowing/winit
- Casey HH Day 026 C 代码: https://github.com/HandmadeHero/handmade-hero/tree/main/code/day026
