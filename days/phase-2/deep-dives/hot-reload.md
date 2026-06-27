---
phase: 2
type: deep-dive
title: "热重载完整链路:从 build 系统 到 libloading 到 状态保持"
domains: [game, rust, linux]
duration: "2h"
prereqs: ["day026", "day029"]
---

# 热重载完整链路 · 从 build 系统到 libloading 到状态保持

> 改一行游戏代码,从"按 Ctrl+C → cargo build → cargo run → 走到对应关卡 → 测试"变成"按 Ctrl+S → 自动生效"。开发循环从分钟级降到秒级。这是 Casey 在 Day 026-029 搭建的核心开发体验,本文 2 小时讲透整条链路:构建系统、库加载、状态外置、ABI 兼容、文件监控、踩坑大全。

## 0 · 这篇文章解决什么问题

你在开发游戏。你写了一段新逻辑——让玩家按 F 切换飞行模式。流程是:

1. 改 `src/game/player.rs`,加 `fn toggle_fly(&mut self)`
2. 改 `src/game/input.rs`,绑 F 键
3. 按 Ctrl+C 终止游戏
4. `cargo build --release` 等 10 秒
5. `./target/release/handmade-hero` 启动游戏
6. 走到对应关卡(WASD 几秒)
7. 按 F,看效果

整个循环 30 秒。一天 100 次循环,1 小时没了。

热重载后:

1. 改代码
2. `cargo build --release --lib` 等 3 秒(只编译 cdylib)
3. **游戏窗口不关**,按 R 键触发重载
4. 玩家位置 / 怪物状态 / 关卡进度全部保留,只有代码换了
5. 按 F,立即看效果

整个循环 5 秒。**效率提升 6 倍**。

Casey 在 HH Day 026 实现热重载,后面 640 天**每天都在用**。这是 HH 最有价值的工程实践之一。

读完本文,你能:

- 解释热重载的完整链路(build → load → state preserve → call)
- 设计一个支持热重载的 Rust cdylib 架构
- 处理 ABI 兼容、状态版本化、drop 顺序等坑
- 用 `cargo-watch` + `notify` 自动化监控代码变化
- 知道热重载的局限(WASM、移动端不支持)

## 1 · 热重载的完整链路

```
┌──────────────────────────────────────────────────────────────────────┐
│  开发循环                                                             │
│                                                                      │
│  [1] 改代码(src/game/*.rs)                                          │
│        ↓                                                             │
│  [2] 文件监控系统检测到变化(inotify / notify)                       │
│        ↓                                                             │
│  [3] cargo build --lib,产出新的 libhandmade_hero.so(3-5 秒)        │
│        ↓                                                             │
│  [4] 平台层在下一帧检测 .so 的 mtime 变化                            │
│        ↓                                                             │
│  [5] 平台层 unload 旧 lib(libloading Library drop → dlclose)       │
│        ↓                                                             │
│  [6] 平台层 load 新 lib(libloading Library::new → dlopen)          │
│        ↓                                                             │
│  [7] 平台层 lookup 函数符号(library.get → dlsym)                    │
│        ↓                                                             │
│  [8] 下一帧调用新函数,状态(GameMemory)保留                         │
│        ↓                                                             │
│  [9] 游戏立即看到新逻辑生效                                           │
└──────────────────────────────────────────────────────────────────────┘
```

每一步都可能出错。本文逐个讲。

## 2 · 构建系统:cargo 怎么产出 cdylib

### 2.1 Cargo.toml 配置

```toml
[package]
name = "handmade-hero"
version = "0.1.0"
edition = "2021"

[lib]
name = "handmade_hero"
# 关键:crate-type 包含 cdylib
crate-type = ["cdylib", "rlib"]
# cdylib: 动态库,Linux 上是 .so,Windows 上是 .dll,macOS 上是 .dylib
# rlib: 普通 Rust 库,给单元测试用(cargo test 需要)

[[bin]]
name = "handmade-hero"
path = "src/main.rs"
# bin 是平台层
```

`cargo build --release` 同时产出:

- `target/release/handmade-hero`(可执行文件,平台层)
- `target/release/libhandmade_hero.so`(cdylib,游戏层,Linux)
- `target/release/libhandmade_hero.rlib`(rlib,内部用)

### 2.2 只重 build cdylib

代码改了,平台层不需要重 build(它不变),只需要重 build 游戏层 lib:

```bash
cargo build --release --lib
# 或
cargo build --release -p handmade-hero --lib
```

这只编译 lib crate,跳过 bin。增量编译通常 1-3 秒。

### 2.3 让 cdylib 和 bin 在同一目录

平台层需要知道 cdylib 路径。两个常见做法:

**做法 A:复制到同目录**

```bash
# build 后,复制 cdylib 到 bin 旁边
cp target/release/libhandmade_hero.so target/release/
# 平台层在 current_exe() 目录找
```

**做法 B:用 rpath**

```toml
# .cargo/config.toml
[target.x86_64-unknown-linux-gnu]
rustflags = ["-C", "link-arg=-Wl,-rpath,$ORIGIN"]
```

rpath 告诉动态链接器"在可执行文件同目录找 .so"。这样平台层 `Library::new("libhandmade_hero.so")` 自动找到。

**做法 C:绝对路径**(开发期简单):

```rust
let lib_path = "/home/user/handmade-hero/target/release/libhandmade_hero.so";
```

不灵活但清晰。Casey 在 HH 早期用类似方式。

### 2.4 cargo-watch 自动化

`cargo-watch` 监控 src/ 变化,自动跑 build:

```bash
# 安装
cargo install cargo-watch

# 监控 src/game/ 变化,自动 build lib
cargo watch -w src/game -s "cargo build --release --lib"
```

`-w src/game`:只监控 src/game 目录(平台层 src/main.rs 改了不重 build)
`-s "..."`:变化时跑这条命令

游戏运行时同时开这个,你保存代码 → 自动 build → 平台层检测变化 → 重载。

## 3 · libloading:加载和卸载动态库

### 3.1 基础 API

```rust
use libloading::{Library, Symbol};

// 加载
let lib = unsafe { Library::new("libhandmade_hero.so")? };

// 查找符号
let update_fn: Symbol<extern "C" fn(...) -> ...> = unsafe {
    lib.get(b"update_and_render")?
};

// 调用
update_fn(...);
```

`Library::new` 内部调 `dlopen`(Linux/macOS)或 `LoadLibrary`(Windows)。`library.get` 调 `dlsym`。

### 3.2 unsafe 的来源

为什么 `Library::new` 是 unsafe?

1. **库可能有恶意代码**:`.so` 加载时执行 `__attribute__((constructor))` 函数,可以跑任意代码。
2. **库可能崩溃**:有 bug 的库能在加载时 SIGSEGV。
3. **ABI 不匹配**:如果 lib 是 C++ ABI,期望的函数签名和 Rust 假设的不一致,调用时 UB。

`library.get` 是 unsafe 因为返回的 `Symbol` 持有 lib 引用,lib 卸载后 symbol 失效。

### 3.3 把 unsafe 包成 safe API

```rust
pub struct GameCode {
    library: Library,
    update_and_render: UpdateAndRenderFn,
    last_modified: std::time::SystemTime,
}

impl GameCode {
    pub fn load(path: &Path) -> Result<Self, Box<dyn std::error::Error>> {
        let library = unsafe { Library::new(path)? };
        let update_and_render = unsafe {
            *library.get::<UpdateAndRenderFn>(b"update_and_render")?
        };
        let last_modified = std::fs::metadata(path)?.modified()?;

        Ok(Self { library, update_and_render, last_modified })
    }

    pub fn call(&self, memory: &mut GameMemory, input: &GameInput,
                buffer: &mut GameOffscreenBuffer, dt: f32) {
        (self.update_and_render)(memory, input, buffer, dt);
    }

    pub fn check_reload(&mut self, path: &Path) -> bool {
        if let Ok(meta) = std::fs::metadata(path) {
            if let Ok(mtime) = meta.modified() {
                if mtime != self.last_modified {
                    if let Ok(new_code) = Self::load(path) {
                        *self = new_code;  // 旧 library 被 drop,自动 dlclose
                        return true;
                    }
                }
            }
        }
        false
    }
}
```

注意 `*library.get::<UpdateAndRenderFn>(...)` 的 dereference。`Symbol<Fn>` 实现了 `Deref<Target = Fn>`,所以 `*symbol` 拿到函数指针。赋值给结构体字段后,Symbol 可以释放,函数指针仍然有效(它指向 lib 内的代码,lib 还活着)。

### 3.4 drop 顺序

```rust
struct GameCode {
    library: Library,           // 必须最后 drop
    update_and_render: UpdateAndRenderFn,
    last_modified: SystemTime,
}
```

Rust 的字段 drop 顺序是**声明反序**:`last_modified` → `update_and_render` → `library`。所以 library 最后 drop,dlclose 时没有悬空指针。

如果你担心,显式加 Drop impl:

```rust
impl Drop for GameCode {
    fn drop(&mut self) {
        // self.update_and_render 自然 drop(函数指针是 Copy,drop no-op)
        // self.library 最后 drop,触发 dlclose
    }
}
```

## 4 · 状态保持:GameMemory 的 trick

### 4.1 核心思路

游戏状态不能放在游戏层的 static / 全局变量里——热重载后,新 lib 有新的 static。

放哪?**放在平台层管理的一块大内存里(GameMemory)**。平台层分配,游戏层每帧借用。

```
平台层 ────┐
           │ 分配 1GB
           ↓
        GameMemory {
            permanent_storage: *mut u8 ──── 游戏层 cast 成 *mut GameState
        }
```

热重载时:

```
[旧 lib]                [新 lib]
  ↓                       ↓
library.unload         library.load
GameMemory 不动         新 lib 接着用 GameMemory
  
GameMemory 里的 GameState 完整保留!
```

### 4.2 实现

```rust
// 平台层分配
let permanent_size = 1024 * 1024 * 1024;  // 1 GB
let mut permanent_vec = vec![0u8; permanent_size];
let memory = GameMemory {
    permanent_storage_size: permanent_size,
    permanent_storage: permanent_vec.as_mut_ptr() as *mut c_void,
};
std::mem::forget(permanent_vec);  // 不让 Vec 析构!GameMemory 全程持有这块内存
```

`std::mem::forget` 让 Vec 不释放内存——平台层退出时手动释放(或不释放,程序退出时 OS 回收)。

游戏层把 raw memory cast 成 GameState:

```rust
#[no_mangle]
pub extern "C" fn update_and_render(
    memory: &mut GameMemory,
    input: &GameInput,
    buffer: &mut GameOffscreenBuffer,
    dt: f32,
) {
    let state: &mut GameState = unsafe {
        assert!(!memory.permanent_storage.is_null());
        assert!(memory.permanent_storage_size >= std::mem::size_of::<GameState>());
        &mut *(memory.permanent_storage as *mut GameState)
    };

    if !state.initialized {
        // 第一次调用,初始化
        state.player = Player::new();
        state.world = World::new();
        state.initialized = true;
    }

    // ... update + render
}
```

### 4.3 状态版本化(踩坑)

如果你给 GameState 加字段:

```rust
struct GameState {
    initialized: bool,
    player: Player,
    world: World,
    new_field: i32,  // ← 新加的
}
```

旧 GameMemory 里的 GameState 没有这个字段。新代码读到 `state.new_field` 是 0(因为分配时 zeroed)。但 `initialized = true`,新字段不会被初始化!

解决:

**做法 A:加 version 字段**

```rust
struct GameState {
    version: u32,
    initialized: bool,
    // ...
}

if state.version < 2 {
    state.new_field = default_value;  // 旧版本,初始化新字段
    state.version = 2;
}
```

**做法 B:强制重启**

dev 模式下检测布局大小变化:

```rust
const EXPECTED_SIZE: usize = std::mem::size_of::<GameState>();
if memory.permanent_storage_size < EXPECTED_SIZE || state.layout_signature != LAYOUT_SIG {
    // 布局变了,清零重置
    unsafe {
        std::ptr::write_bytes(memory.permanent_storage, 0, EXPECTED_SIZE);
    }
}
```

Casey 在 HH 里用做法 B——开发期重启可接受,版本化太麻烦。

## 5 · ABI 兼容性

### 5.1 extern "C" vs extern "Rust"

`#[no_mangle] pub extern "C" fn ...`:C ABI,Rust 团队承诺不破坏。

`#[no_mangle] pub extern "Rust" fn ...`(默认):Rust ABI,**不稳定**,跨 Rust 版本可能不兼容。

**永远用 extern "C"**。

### 5.2 结构体 repr(C)

```rust
#[repr(C)]
pub struct GameInput { ... }
```

不加 `#[repr(C)]`,Rust 可能重排字段以减少 padding(优化)。这破坏跨 Rust 版本兼容——同一份代码不同版本编译出的 lib 内存布局可能不同。

`#[repr(C)]` 强制按 C 规则布局(声明顺序,每字段对齐到自己的对齐),跨 Rust 版本稳定。

### 5.3 不要在接口层用 Rust 专有类型

**错误**:

```rust
#[repr(C)]
pub struct GameInput {
    pub controllers: Vec<GameController>,  // ← Vec 不是 repr(C)!
}
```

`Vec<T>` 内部是 `(pointer, capacity, length)`,Rust 不保证布局稳定。用 `&[T]` 或 `*const T + usize`:

```rust
#[repr(C)]
pub struct GameInput {
    pub controllers: *const GameController,
    pub controller_count: usize,
}
```

或者用固定大小数组:

```rust
#[repr(C)]
pub struct GameInput {
    pub controllers: [GameController; 5],  // 固定大小,数组是 repr(C) 兼容
}
```

### 5.4 不要在接口层用 trait object

`Box<dyn Trait>` / `&dyn Trait` 的 vtable 布局是 Rust 内部,不稳定。

接口层只用:

- 原始类型(`i32`, `f32`, `bool`, ...)
- `#[repr(C)]` struct / enum
- 原始指针(`*const T`, `*mut T`)
- 固定大小数组

### 5.5 enum 的 repr

```rust
#[repr(C)]
pub enum EntityKind { Player, Monster, Wall }
```

C enum 默认是 `int`(4 字节)。Rust enum 默认按变体数量决定大小(可能 1 字节)。`#[repr(C)]` 强制 Rust 用 C enum 布局。

如果 enum 带数据:

```rust
#[repr(C)]
pub enum CollisionRule {
    None,
    Damage(u32),
    Destroy,
}
```

这是 tagged union。Rust 的 tagged union 布局是 Rust 内部细节,即使加 `#[repr(C)]` 也不保证跨 Rust 版本兼容。

**最佳实践**:接口层只传 C 风格 enum(无数据)或 i32 / u32 标签 + union。

## 6 · 文件监控:检测代码变化

### 6.1 平台层主动检查 mtime

最简单的实现:每帧检查 .so 的 mtime:

```rust
pub fn check_reload(&mut self, path: &Path) -> bool {
    if let Ok(meta) = std::fs::metadata(path) {
        if let Ok(mtime) = meta.modified() {
            if mtime != self.last_modified {
                if let Ok(new_code) = Self::load(path) {
                    *self = new_code;
                    return true;
                }
            }
        }
    }
    false
}
```

每帧调一次。`std::fs::metadata` 大约 1 µs,影响微乎其微。

### 6.2 用 inotify 异步通知(Linux)

`notify` crate 封装了 inotify / kqueue / ReadDirectoryChangesW:

```toml
[dependencies]
notify = "6.0"
```

```rust
use notify::{Watcher, RecursiveMode, DebouncedEvent};

let (tx, rx) = std::sync::mpsc::channel();
let mut watcher = notify::recommended_watcher(tx)?;
watcher.watch(Path::new("target/release/"), RecursiveMode::NonRecursive)?;

// 在另一线程接收事件
std::thread::spawn(move || {
    while let Ok(event) = rx.recv() {
        if let notify::EventKind::Modify(_) = event.event.kind {
            // 触发 reload
        }
    }
});
```

notify 在子线程触发,主线程不阻塞。但需要和游戏循环同步——加 Mutex / channel。

**Casey 在 HH 用 mtime 轮询**(简单)。性能上 inotify 更好,但开发体验差不多。

### 6.3 防抖动

cargo build 写 .so 时,文件可能短暂"半成品"。读到这种 .so 会 dlopen 失败。

解决:

1. **mtime 防抖**:检查 mtime 后再等 100ms,如果再变就再等
2. **临时文件**:cargo 写到 `.so.tmp`,完成后 rename。平台层只读 `.so`,看不到中间状态
3. **重试**:dlopen 失败时记下 mtime,下一帧重试

Casey 用重试——dlopen 失败时静默跳过,下帧再试。

## 7 · 触发重载的方式

### 7.1 手动按键

最简单:玩家按 R 键时,平台层调 `check_reload`:

```rust
WindowEvent::KeyPressed(VirtualKeyCode::R) => {
    self.game_code.check_reload(&lib_path);
}
```

缺点:每次要手动按 R。

### 7.2 自动定时检查

每帧调 check_reload(自动检测 mtime 变化):

```rust
fn run_frame(&mut self) {
    self.game_code.check_reload(&lib_path);  // 每帧都查
    // ...
}
```

最常用。`std::fs::metadata` 1 µs,无感知。

### 7.3 inotify 触发

notify 在子线程,通过 channel 通知主线程:

```rust
if let Ok(()) = self.reload_rx.try_recv() {
    self.game_code.check_reload(&lib_path);
}
```

性能最好,但复杂。

### 7.4 cargo-watch 自动 build

```bash
cargo watch -w src/game -s "cargo build --release --lib"
```

游戏跑着,cargo-watch 在后台监控 src/game 变化,自动重 build。配合上面任一触发方式,实现"保存即重载"。

## 8 · 完整最小示例

下面是一个 100 行的完整热重载 demo,你可以直接抄。

### 8.1 Cargo.toml

```toml
[package]
name = "hot-reload-demo"
version = "0.1.0"
edition = "2021"

[lib]
name = "hot_reload_game"
crate-type = ["cdylib", "rlib"]

[[bin]]
name = "hot-reload-demo"
path = "src/main.rs"

[dependencies]
winit = "0.30"
softbuffer = "0.4"
libloading = "0.8"
notify = "6.0"
```

### 8.2 src/shared.rs

```rust
use std::ffi::c_void;

#[repr(C)]
pub struct GameMemory {
    pub storage_size: usize,
    pub storage: *mut c_void,
}

#[repr(C)]
pub struct GameBuffer {
    pub width: i32,
    pub height: i32,
    pub pixels: *mut u32,  // 0xAARRGGBB
}

pub type UpdateFn = extern "C" fn(&mut GameMemory, f32, &mut GameBuffer);
```

### 8.3 src/lib.rs(游戏层)

```rust
include!("shared.rs");

#[repr(C)]
struct GameState {
    initialized: bool,
    color_phase: f32,
}

#[no_mangle]
pub extern "C" fn update(memory: &mut GameMemory, dt: f32, buffer: &mut GameBuffer) {
    let state: &mut GameState = unsafe {
        &mut *(memory.storage as *mut GameState)
    };
    if !state.initialized {
        state.initialized = true;
        state.color_phase = 0.0;
    }

    // 循环变色
    state.color_phase += dt * 0.5;
    if state.color_phase > 1.0 { state.color_phase = 0.0; }

    let r = ((state.color_phase * 255.0) as u32) << 16;
    let g = (((1.0 - state.color_phase) * 255.0) as u32) << 8;
    let color = 0xff000000 | r | g;

    unsafe {
        for i in 0..(buffer.width * buffer.height) as usize {
            *buffer.pixels.add(i) = color;
        }
    }
}
```

### 8.4 src/main.rs(平台层)

```rust
use std::ffi::c_void;
use std::path::PathBuf;
use libloading::{Library, Symbol};
use winit::event::{VirtualKeyCode, WindowEvent};
use winit::event_loop::EventLoop;
use winit::window::Window;

include!("shared.rs");

struct GameCode {
    library: Library,
    update: UpdateFn,
    last_modified: std::time::SystemTime,
}

impl GameCode {
    fn load(path: &std::path::Path) -> Result<Self, Box<dyn std::error::Error>> {
        let library = unsafe { Library::new(path)? };
        let update = unsafe { *library.get::<UpdateFn>(b"update")? };
        let last_modified = std::fs::metadata(path)?.modified()?;
        Ok(Self { library, update, last_modified })
    }

    fn check_reload(&mut self, path: &std::path::Path) -> bool {
        if let Ok(meta) = std::fs::metadata(path) {
            if let Ok(mtime) = meta.modified() {
                if mtime != self.last_modified {
                    std::thread::sleep(std::time::Duration::from_millis(50));
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

fn main() {
    let lib_path = std::env::current_exe().unwrap()
        .parent().unwrap().to_path_buf()
        .join("libhot_reload_game.so");

    let mut game_code = GameCode::load(&lib_path).unwrap();

    let storage_size = 1024 * 1024;
    let mut storage_vec = vec![0u8; storage_size];
    let mut memory = GameMemory {
        storage_size,
        storage: storage_vec.as_mut_ptr() as *mut c_void,
    };
    std::mem::forget(storage_vec);

    // 创建窗口(简化,实际用 winit EventLoop)
    // ... 略
    let mut buffer_pixels = vec![0u32; 1280 * 720];
    let mut buffer = GameBuffer {
        width: 1280, height: 720,
        pixels: buffer_pixels.as_mut_ptr(),
    };

    let mut last_frame = std::time::Instant::now();
    loop {
        // 检查热重载
        if game_code.check_reload(&lib_path) {
            println!("Reloaded!");
        }

        let now = std::time::Instant::now();
        let dt = now.duration_since(last_frame).as_secs_f32();
        last_frame = now;

        (game_code.update)(&mut memory, dt, &mut buffer);

        // 渲染 buffer 到屏幕(略)
        std::thread::sleep(std::time::Duration::from_millis(16));
    }
}
```

### 8.5 跑

```bash
# 终端 1:启动游戏
cargo build --release
cp target/release/libhot_reload_game.so target/release/
cd target/release && ./hot-reload-demo

# 终端 2:监控代码变化
cargo watch -w src -s "cargo build --release --lib && cp target/release/libhot_reload_game.so target/release/"

# 改 src/lib.rs 里的颜色逻辑,保存,看终端 1 自动重载
```

## 9 · 局限性

### 9.1 状态布局变化

GameState 加字段,旧 GameMemory 不兼容。Casey 的做法:重启游戏。生产做法:版本化或 reflection。

### 9.2 WASM 不支持

WebAssembly 不支持 dlopen(没有运行时动态加载)。WASM 热重载只能"重启 wasm module",无法保留状态。

### 9.3 移动端不支持

Android / iOS 沙箱不允许任意 dlopen。开发期只能用桌面,移动端发布前在桌面调好。

### 9.4 不能热重载平台层

平台层是 bin,跑在 main 函数里,没法热重载。改平台层代码必须重启游戏。

### 9.5 调试器状态

热重载时,gdb / lldb 的断点 / watch 可能失效(因为新 lib 加载到新地址)。重新设断点。

## 10 · 业界对比

### 10.1 Casey HH

完整方案:cdylib + libloading + GameMemory。教学清晰,跨平台。

### 10.2 Rust 生态

- `bevy_mod_hotreload`(社区 Bevy 插件):用 ECS,热重载 System 函数
- `mold` / `lld` 链接器:加速 link 时间,使热重载更快
- `crate::hot_reload` 模式:trait + atomic swap

### 10.3 Unity

- **Domain Reload**:每次 play 都重新加载所有 C# 域。慢但彻底。
- **Disable Domain Reload**:Editor 设置,关掉域重载,Play Mode 启动快。需要手动 `[RuntimeInitializeOnLoadMethod]` 重置 static。
- **Enter Play Mode Faster**:Unity 2019+ 选项。

### 10.4 Unreal Engine

- **Live Coding**:类似 Casey 的 cdylib 重载,C++ 代码改了自动编译 + 注入到运行的游戏。
- **Hot Reload**(蓝图):蓝图编译不需要重启。

Unreal 的 Live Coding 是工业级的 Casey 方案。

### 10.5 LÖVE / Lua 系

Lua 解释器天然支持热重载:`require` 缓存可清空,模块重新加载。Lua 游戏开发的热重载是默认的,不像 C/Rust 要专门搭。

## 11 · 延伸阅读

本仓库:
- [day026.md](../day026.md) —— 热重载第一天
- [day029.md](../day029.md) —— 接口层完整
- [deep-dives/platform-game-separation.md](platform-game-separation.md) —— 平台/游戏分离
- [deep-dives/rust-cdylib-and-ffi.md](rust-cdylib-and-ffi.md) —— cdylib + FFI 完整指南

外部:
- libloading 文档: https://docs.rs/libloading/latest/libloading/
- notify crate: https://docs.rs/notify/latest/notify/
- cargo-watch: https://github.com/watchexec/cargo-watch
- Rust ABI stability: https://doc.rust-lang.org/reference/abi.html

开源源码:
- Casey HH Day 026 C 代码: https://github.com/HandmadeHero/handmade-hero/tree/main/code/day026
- Unreal Live Coding: https://docs.unrealengine.com/5.0/en-US/using-live-coding-in-unreal-engine/
