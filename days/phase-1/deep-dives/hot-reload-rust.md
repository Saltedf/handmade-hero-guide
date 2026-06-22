---
title: "Rust 热重载:cdylib + libloading + cargo-watch 完整指南"
phase: 1
type: deep-dive
domains: [rust, software-engineering, linux]
---

# Rust 热重载:cdylib + libloading + cargo-watch 完整指南

> Casey 在 HH 用 LoadLibrary + C++ DLL 实现热重载。在 Rust 里,我们用 cdylib + libloading + cargo-watch 实现同样体验,但 Rust 的所有权系统带来独特挑战。本文是 Rust 热重载的完整指南——从最小 demo 到生产级 pipeline,处理所有 Rust 特有陷阱。

## 0 · 热重载的承诺

你改一行代码:

- **没有热重载**:保存 → cargo build(几秒)→ 关游戏 → 重启 → 进关卡 → 测试。30 秒一次。
- **有热重载**:保存 → cargo-watch 自动 build → 平台层自动 reload → 下一帧新代码生效。1-3 秒一次。

10× 加速。两年开发,省下几百小时。

热重载的核心思想:**状态外置 + 代码替换 + 接口一致**。

- 状态(GameMemory)由平台层持有,跨 reload 不动
- 代码(update_and_render 函数)编 cdylib,平台层 libloading 加载
- 接口(函数签名)跨 reload 一致

## 1 · 最小可工作 demo

我们从最小 demo 开始,逐步扩展。

### 项目结构

```
hot_reload_demo/
├── Cargo.toml           (workspace)
├── game_lib/
│   ├── Cargo.toml
│   └── src/lib.rs
└── platform/
    ├── Cargo.toml
    └── src/main.rs
```

### workspace 配置

```toml
# Cargo.toml
[workspace]
members = ["game_lib", "platform"]
resolver = "2"
```

### game_lib(cdylib)

```toml
# game_lib/Cargo.toml
[package]
name = "game_lib"
version = "0.1.0"
edition = "2021"

[lib]
name = "game_lib"
crate-type = ["cdylib"]   # ← 关键
```

```rust
// game_lib/src/lib.rs
use std::sync::atomic::{AtomicU64, Ordering};

/// 游戏主函数
/// 
/// # Safety
/// - counter 必须是有效的 AtomicU64 指针
/// - 平台层保证此指针稳定(跨 reload 不变)
#[no_mangle]
pub unsafe extern "C" fn update_and_render(counter: *const AtomicU64) {
    let n = (*counter).fetch_add(1, Ordering::SeqCst);
    println!("frame: {}", n);
}
```

每个关键字:

- `#[no_mangle]`——保持函数名,Rust 默认会 mangle(加 hash)
- `pub`——对外可见
- `extern "C"`——C ABI,跨编译器 / 版本稳定
- `unsafe`——因为解引用裸指针
- `*const AtomicU64`——裸指针(FFI 边界)

### platform(bin)

```toml
# platform/Cargo.toml
[package]
name = "platform"
version = "0.1.0"
edition = "2021"

[dependencies]
libloading = "0.8"
```

```rust
// platform/src/main.rs
use libloading::Library;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;

fn main() {
    let counter = Arc::new(AtomicU64::new(0));
    let counter_ptr = Arc::as_ptr(&counter);
    
    let path = "./target/debug/libgame_lib.so";
    let mut lib = unsafe { Library::new(path) }.expect("load library");
    let mut last_mtime = std::fs::metadata(path).unwrap().modified().unwrap();
    
    loop {
        // 检测 reload
        let mtime = std::fs::metadata(path).unwrap().modified().unwrap();
        if mtime != last_mtime {
            println!("🔄 Reloading...");
            std::thread::sleep(Duration::from_millis(50));  // 等文件写完整
            lib = unsafe { Library::new(path) }.expect("reload");
            last_mtime = mtime;
        }
        
        // 调用
        let func: libloading::Symbol<unsafe extern "C" fn(*const AtomicU64)> = 
            unsafe { lib.get(b"update_and_render") }.expect("symbol");
        unsafe { func(counter_ptr) };
        
        std::thread::sleep(Duration::from_millis(100));
    }
}
```

### 跑起来

```bash
# 终端 1
cargo watch -x build

# 终端 2
cargo run --bin platform

# 终端 3(编辑器):改 game_lib/src/lib.rs 的 println 内容
# 终端 2:看到 reload + 新消息,counter 持续递增
```

最小 demo 完成。下面我们扩展到生产级。

## 2 · Rust 所有权 + libloading 的张力

最小 demo 里有个细节:`Symbol<Fn>` 借用 `Library`。每帧 `lib.get(...)` 重新拿 Symbol——开销几纳秒,但规避借用冲突。

如果你想"加载一次,长期持有":

```rust
// ❌ 编译错误
struct App {
    lib: Library,
    func: libloading::Symbol<'?, unsafe extern "C" fn(...)>,  // 借用 lib,生命周期问题
}
```

`Symbol<'a, Fn>` 的 `'a` 是 Library 的借用。但 lib 是 App 的字段,App 不能借用自己——Rust 不允许自引用。

### 解法 1:每帧重新 get(最简单)

```rust
loop {
    let func: Symbol<_> = unsafe { lib.get(b"update_and_render") }?;
    func(...);
    // func drop,lib 不再被借用
}
```

开销:每帧几次原子操作,纳秒级。**推荐**。

### 解法 2:函数指针(放弃 Symbol)

```rust
let func_ptr: unsafe extern "C" fn(...) = {
    let sym: Symbol<unsafe extern "C" fn(...)> = unsafe { lib.get(b"...") }?;
    sym.into_raw()  // 放弃 Symbol 借用,返回裸函数指针
};
// 之后用 func_ptr,不绑 lib
```

`into_raw` 把 Symbol 转成裸函数指针。但**这指针指向 lib 的代码段**——lib 卸载后指针无效!

reload 时:

```rust
// reload
drop(lib);  // 旧 lib 卸载,代码段释放
lib = unsafe { Library::new(path) }?;
// func_ptr 还指向旧地址 → use after unload,UB!
```

要么用 reload 时不 drop 旧 lib(用 Box::leak 让它永生),要么 reload 时重新 get。

### 解法 3:Box::leak(让 Library 永生)

```rust
let lib: &'static Library = Box::leak(Box::new(unsafe { Library::new(path) }?));
// lib 生命周期 'static,永不释放
let func: Symbol<'static, Fn> = unsafe { lib.get(b"...") }?;
// func 也 'static,可以独立持有
```

代价:Library 永不释放,reload 时累积泄漏。

但对开发工具 OK——一次开发会话泄漏几 MB,程序退出 OS 清理。

### 解法 4:Arc<Library>

```rust
let lib = Arc::new(unsafe { Library::new(path) }?);
let lib_clone = lib.clone();

// 主线程持有 lib
// 某处持有 lib_clone
// 不会过早 drop
```

但 Arc 不能让你"替换"——`Arc::new` 创建新 Arc,旧的不动。reload 时旧 lib 仍在内存(引用计数 > 0)。

### 实战推荐

- **demo / 学习**:解法 1(每帧 get,简单)
- **生产工具**:解法 3(Box::leak)或用 `hot-lib-reloader` crate
- **完美主义**:解法 4(Arc)+ 不 reload 旧 lib(容忍小泄漏)

## 3 · 状态外置的实现

热重载的核心:**状态不在 game_lib crate**。

### 错误:状态在 static

```rust
// game_lib/src/lib.rs
static mut PLAYER_HP: i32 = 100;  // ← 状态在 game_lib!

#[no_mangle]
pub unsafe extern "C" fn update() {
    unsafe { PLAYER_HP -= 1; }
}
```

reload 时:

1. 旧 .so 卸载,`PLAYER_HP` 内存释放
2. 新 .so 加载,`PLAYER_HP` 重新初始化为 100
3. 玩家 HP=30 → reload → HP=100 ← **bug**

### 正确:状态在 GameMemory

```rust
// game_lib/src/lib.rs
#[repr(C)]
pub struct GameMemory {
    pub is_initialized: bool,
    pub player_hp: i32,
}

#[no_mangle]
pub unsafe extern "C" fn update(memory: *mut GameMemory) {
    let memory = unsafe { &mut *memory };
    memory.player_hp -= 1;
}
```

```rust
// platform/src/main.rs
let mut memory = GameMemory { is_initialized: false, player_hp: 100 };

loop {
    // 调用
    let func: Symbol<unsafe extern "C" fn(*mut GameMemory)> = unsafe { lib.get(b"update") }?;
    unsafe { func(&mut memory as *mut GameMemory) };
    // memory 在 platform,reload 时不动
}
```

reload 时:

1. 旧 .so 卸载
2. 新 .so 加载
3. platform 把**同一个 memory 指针**给新代码
4. 新代码看到 player_hp = 30(真实状态),继续

## 4 · is_initialized 标志

首次调用时初始化 GameMemory:

```rust
#[no_mangle]
pub unsafe extern "C" fn update(memory: *mut GameMemory) {
    let memory = unsafe { &mut *memory };
    
    if !memory.is_initialized {
        // 首次:初始化玩家位置 / 关卡 / 等
        memory.player_x = 100.0;
        memory.player_y = 100.0;
        memory.is_initialized = true;
        println!("first init");
    } else {
        // 后续帧(包括 reload 后)
        // state 已存在,直接用
    }
    
    // 游戏逻辑
    memory.player_x += 1.0;
}
```

reload 后 `is_initialized = true`,跳过初始化,继续游戏。

## 5 · GameMemory 的设计

Casey 把 GameMemory 分两区:

- **permanent**:跨 reload 保留(玩家进度)
- **transient**:每帧 reset(渲染命令)

```rust
#[repr(C)]
pub struct GameMemory {
    pub is_initialized: bool,
    
    // 永久存储
    pub permanent_storage_size: u64,
    pub permanent_storage: *mut u8,
    
    // 临时存储
    pub transient_storage_size: u64,
    pub transient_storage: *mut u8,
}
```

实际 Rust 实现可以用 Arena:

```rust
use std::cell::Cell;

pub struct Arena {
    buffer: Box<[u8]>,
    offset: Cell<usize>,
}

impl Arena {
    pub fn new(capacity: usize) -> Self {
        Self {
            buffer: vec![0u8; capacity].into_boxed_slice(),
            offset: Cell::new(0),
        }
    }
    
    pub fn alloc<T>(&self, n: usize) -> &mut [T] {
        let size = n * std::mem::size_of::<T>();
        let align = std::mem::align_of::<T>();
        let start = (self.offset.get() + align - 1) & !(align - 1);
        let end = start + size;
        assert!(end <= self.buffer.len());
        self.offset.set(end);
        unsafe { std::slice::from_raw_parts_mut(
            self.buffer.as_ptr().add(start) as *mut T, n) }
    }
    
    pub fn reset(&self) { self.offset.set(0); }
}

pub struct GameMemory {
    pub is_initialized: bool,
    pub permanent: Arena,
    pub transient: Arena,
}
```

Day 014 详细讲 Arena。

## 6 · ABI 稳定性

热重载要求**函数签名跨 reload 一致**。

### 错误:改签名

```rust
// V1
#[no_mangle]
pub extern "C" fn update(memory: *mut GameMemory) { ... }

// V2(改了签名)
#[no_mangle]
pub extern "C" fn update(memory: *mut GameMemory, input: *const GameInput) { ... }
```

reload V2:platform 还按 V1 调用,栈帧错乱,crash。

### 正确:扩展不改签名

加新数据通过 GameMemory 字段:

```rust
#[repr(C)]
pub struct GameMemory {
    pub is_initialized: bool,
    pub state: GameState,
    // 新加字段:
    pub debug_overlay: bool,  // ← 新加,旧字段不动
}

// 签名不变
#[no_mangle]
pub extern "C" fn update(memory: *mut GameMemory) {
    // 用 memory.debug_overlay
}
```

platform 配合(填新字段),签名不变,热重载工作。

### 例外:重大架构变化

有时真要改签名(架构大改)。这时:

1. 接受失去热重载便利
2. 重启 platform
3. GameMemory 可能要迁移(旧版本数据转新版本)

Casey 在 HH 大约一年改一次签名(Day 175 SIMD、Day 235 OpenGL),每次都要重启。可接受。

## 7 · C ABI vs Rust ABI

为什么用 `extern "C"` 而不是 `extern "Rust"`?

**Rust ABI 不稳定**——不同 rustc 版本可能有不同调用约定、参数布局。今天写的代码,明天 rustc 升级后可能不兼容。

**C ABI 稳定**——几十年标准,跨编译器 / 跨语言 / 跨版本兼容。

```rust
// ❌ Rust ABI(不稳定,跨版本可能不兼容)
#[no_mangle]
pub fn update(memory: &mut GameMemory) { ... }

// ✅ C ABI(稳定)
#[no_mangle]
pub extern "C" fn update(memory: *mut GameMemory) { ... }
```

代价:C ABI 不支持 Rust 的 `&mut`(引用),只能用裸指针。所以游戏代码内部要 `unsafe { &mut *ptr }`。

### repr(C)

Rust 结构体默认布局是优化过的(字段重排、对齐 padding)。跨 FFI 边界要用 `#[repr(C)]` 强制 C 布局:

```rust
// ❌ Rust 默认布局(可能 reorder)
pub struct GameMemory {
    is_initialized: bool,
    player_hp: i32,
}

// ✅ C 布局(字段顺序固定)
#[repr(C)]
pub struct GameMemory {
    is_initialized: bool,
    player_hp: i32,
}
```

不加 `#[repr(C)]`,不同 rustc 版本可能布局不同,reload 时内存对不上。

## 8 · cargo-watch 完整配置

```bash
cargo install cargo-watch
```

`cargo watch` 监听文件变化,自动跑命令:

```bash
# 监听变化,自动 cargo build
cargo watch -x build

# 指定 package(只 build game_lib,不 build platform)
cargo watch -x "build -p game_lib"

# 多命令
cargo watch -x build -x test

# debounce(防止连续保存触发多次)
cargo watch -x build -d 0.3

# 监听特定目录
cargo watch -w src -x build

# 排除目录
cargo watch -x build --ignore tests
```

### 完整开发 workflow

```bash
# 终端 1:监听 game_lib 自动 build
cd ~/src/handmade-hero-rs
cargo watch -x "build -p game_lib" -d 0.3 -w game_lib

# 终端 2:跑游戏
cargo run --bin platform

# 终端 3:编辑器
nvim game_lib/src/lib.rs
```

或用 tmux 一屏三分:

```bash
tmux new-session -d -s dev
tmux send-keys -t dev "cargo watch -x 'build -p game_lib' -d 0.3" C-m
tmux split-window -h -t dev
tmux send-keys -t dev "cargo run --bin platform" C-m
tmux select-pane -t dev:0.0
tmux split-window -v -t dev
tmux send-keys -t dev "nvim" C-m
tmux attach -t dev
```

## 9 · 容错:build 失败时不崩

```rust
fn check_and_reload(&mut self) {
    let path = "./target/debug/libgame_lib.so";
    
    let mtime = match std::fs::metadata(path) {
        Ok(m) => match m.modified() {
            Ok(t) => t,
            Err(_) => return,
        },
        Err(_) => return,  // 文件可能还在写
    };
    
    if mtime == self.last_mtime {
        return;
    }
    
    std::thread::sleep(std::time::Duration::from_millis(50));
    
    match unsafe { Library::new(path) } {
        Ok(lib) => {
            match unsafe { lib.get::<unsafe extern "C" fn(*mut GameMemory)>(b"update_and_render") } {
                Ok(_) => {
                    self.library = lib;
                    self.last_mtime = mtime;
                    self.build_failed = false;
                    println!("✅ Reloaded");
                }
                Err(e) => {
                    self.build_failed = true;
                    self.build_error = format!("Symbol not found: {}", e);
                    self.last_mtime = mtime;
                }
            }
        }
        Err(e) => {
            // Build 失败,保留旧 library,游戏继续跑旧代码
            self.build_failed = true;
            self.build_error = format!("Build failed: {}", e);
            self.last_mtime = mtime;
            eprintln!("❌ {}", self.build_error);
        }
    }
}
```

游戏画面显示 "BUILD FAILED":

```rust
fn render(&mut self) {
    // ... 正常渲染
    
    if self.build_failed {
        draw_text(&mut self.back_buffer, "BUILD FAILED", 10, 10, RED);
        draw_text(&mut self.back_buffer, &self.build_error, 10, 30, RED);
    }
}
```

UX 价值:开发者看到 "BUILD FAILED" 立刻知道改的代码有编译错误,游戏不崩。

## 10 · 状态保留的细节

### 简单状态(Plain Old Data)

`f32` / `i32` / `bool` / struct of 这些——直接 memcpy 保留。reload 时内存不动,新代码看到旧值。

```rust
#[repr(C)]
pub struct GameMemory {
    pub player_x: f32,
    pub player_y: f32,
    pub player_hp: i32,
}
```

reload 时:`player_x` 等保持不变,新代码继续。

### 含堆分配的状态(Vec / String / Box)

```rust
#[repr(C)]
pub struct GameMemory {
    pub items: Vec<Item>,  // ← 含堆指针!
}
```

问题:Vec 内部有 `(*ptr, len, capacity)`。这个 ptr 指向 game_lib 的堆分配。

reload 时:

- 旧 .so 卸载——`Vec` 的 ptr 还在(堆内存没释放,因为 GameMemory 还引用)
- 新 .so 加载——新代码看到 GameMemory.items,ptr 还指向原来的堆
- **可以读,但删除 / push 时**,新 .so 的 allocator 和旧 allocator 可能不是同一个(尤其不同 rustc 版本)

**安全做法**:**FFI 边界只用 POD**。Vec / String 跨 reload 不安全。

```rust
// ✅ POD 状态(跨 reload 安全)
#[repr(C)]
pub struct GameMemory {
    pub player_x: f32,
    pub player_y: f32,
    pub player_hp: i32,
    pub items_count: u32,
    pub items: [Item; 100],  // 固定大小数组,不是 Vec
}

// ❌ 含堆指针(跨 reload 不安全)
#[repr(C)]
pub struct GameMemory {
    pub items: Vec<Item>,
    pub name: String,
}
```

### Arena 内存

```rust
#[repr(C)]
pub struct GameMemory {
    pub permanent_storage: *mut u8,  // 由 platform 分配的固定大小内存
    pub permanent_storage_size: u64,
}
```

game_lib 在这块内存里自己分配。reload 时这块不动,内容保留。

`GameMemory` 不含 Vec / String,只有裸指针 + 大小。**这是 Casey 的设计**——绕过 Rust allocator 问题。

### Box / Arc 跨 reload

绝对不要在 GameMemory 里放 Box / Arc / Vec / String。它们都隐含 Rust allocator,reload 后失效。

如果要"动态数据",用 Arena 自己管。

## 11 · 调试热重载问题

### 问题:reload 后 crash

**原因**:函数签名变了,栈帧错乱。

**排查**:确认 game_lib 的 `update_and_render` 签名和 platform 的 `Symbol<Fn>` 类型完全一致。

### 问题:reload 后状态错乱

**原因**:GameMemory 布局变了。

**排查**:确认 GameMemory 加了 `#[repr(C)]`,字段顺序不变。加字段加末尾,不删字段。

### 问题:reload 触发太频繁

**原因**:cargo-watch 触发多次(每次保存一次,但有多个文件保存)。

**排查**:加 debounce:`cargo watch -d 0.5`(0.5 秒 debounce)。

### 问题:reload 不触发

**原因**:cargo-watch 没跑,或路径不对。

**排查**:

```bash
# 看 .so mtime 是否变化
stat ./target/debug/libgame_lib.so

# 看 platform 检测的路径
ls -la ./target/debug/libgame_lib.so

# 用绝对路径试试
let path = "/home/sun/src/handmade-hero-rs/target/debug/libgame_lib.so";
```

### 问题:看到 "BUILD FAILED"

**原因**:game_lib 编译失败。

**排查**:

```bash
# 手动 build,看错误
cargo build -p game_lib

# 修编译错误,build 成功后游戏自动 reload
```

### 问题:读到半成品 .so

**原因**:cargo 还在写 .so,platform 已经 dlopen。

**排查**:加 sleep:

```rust
if mtime != last_mtime {
    std::thread::sleep(std::time::Duration::from_millis(100));  // 等 cargo 写完
    // 然后再 dlopen
}
```

或更稳健:重试机制:

```rust
for _ in 0..10 {
    match unsafe { Library::new(path) } {
        Ok(lib) => return lib,
        Err(_) => std::thread::sleep(Duration::from_millis(50)),
    }
}
panic!("could not load lib after 10 retries");
```

## 12 · 性能考量

热重载对生产模式无影响——release build 不用 cdylib(静态链接回正常)。

开发模式:

- cargo build:几百 ms 到几秒
- dlopen:几 ms
- dlsym:几纳秒

主要开销在 **cargo build**(rustc 编译)。缓解:

- 增量编译(`incremental = true` in dev profile)
- sccache(分布式缓存)
- mold 链接器(比 ld 快 10×)
- 限制 build 范围(只 build game_lib,不 build platform)

## 13 · 完整生产级代码

下面是完整的生产级热重载 pipeline,集成上面所有最佳实践:

```rust
// platform/src/main.rs
use libloading::Library;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, SystemTime};

#[repr(C)]
pub struct GameMemory {
    pub is_initialized: bool,
    pub frame_count: u64,
    pub player_x: f32,
    pub player_y: f32,
    // ... 其他 POD 字段
}

impl Default for GameMemory {
    fn default() -> Self {
        Self {
            is_initialized: false,
            frame_count: 0,
            player_x: 0.0,
            player_y: 0.0,
        }
    }
}

pub struct GameCode {
    pub library: Library,
    pub update_and_render: unsafe extern "C" fn(*mut GameMemory),
    pub last_mtime: SystemTime,
}

pub struct App {
    pub memory: GameMemory,
    pub game_code: Option<GameCode>,
    pub build_failed: bool,
    pub build_error: String,
    pub lib_path: String,
}

impl App {
    pub fn new(lib_path: &str) -> Self {
        Self {
            memory: GameMemory::default(),
            game_code: None,
            build_failed: false,
            build_error: String::new(),
            lib_path: lib_path.to_string(),
        }
    }
    
    pub fn load_game_code(&mut self) {
        let path = &self.lib_path;
        
        let mtime = match std::fs::metadata(path).and_then(|m| m.modified()) {
            Ok(t) => t,
            Err(e) => {
                self.build_failed = true;
                self.build_error = format!("lib not found: {}", e);
                return;
            }
        };
        
        // 防止快速重复 reload
        if let Some(code) = &self.game_code {
            if code.last_mtime == mtime {
                return;
            }
        }
        
        // 等 cargo 写完
        std::thread::sleep(Duration::from_millis(50));
        
        // 加载
        let lib = match unsafe { Library::new(path.as_str()) } {
            Ok(lib) => lib,
            Err(e) => {
                self.build_failed = true;
                self.build_error = format!("load failed: {}", e);
                return;
            }
        };
        
        // 查找符号
        let func: libloading::Symbol<unsafe extern "C" fn(*mut GameMemory)> = 
            match unsafe { lib.get(b"update_and_render") } {
                Ok(f) => f,
                Err(e) => {
                    self.build_failed = true;
                    self.build_error = format!("symbol not found: {}", e);
                    return;
                }
            };
        
        let func_ptr = func.into_raw();
        
        self.game_code = Some(GameCode {
            library: lib,
            update_and_render: func_ptr,
            last_mtime: mtime,
        });
        self.build_failed = false;
        self.build_error.clear();
        println!("✅ Loaded game code");
    }
    
    pub fn check_and_reload(&mut self) {
        let path = &self.lib_path;
        let mtime = match std::fs::metadata(path).and_then(|m| m.modified()) {
            Ok(t) => t,
            Err(_) => return,
        };
        
        let needs_reload = match &self.game_code {
            Some(code) => code.last_mtime != mtime,
            None => true,
        };
        
        if needs_reload {
            self.load_game_code();
        }
    }
    
    pub fn run_frame(&mut self) {
        self.check_and_reload();
        
        if let Some(code) = &self.game_code {
            unsafe {
                (code.update_and_render)(&mut self.memory as *mut GameMemory);
            }
        }
    }
}

fn main() {
    let lib_path = {
        let mut p = std::env::current_exe().unwrap();
        p.pop();
        p.push("libgame_lib.so");
        p.to_str().unwrap().to_string()
    };
    
    let mut app = App::new(&lib_path);
    app.load_game_code();
    
    let frame_duration = Duration::from_millis(16);
    
    loop {
        let frame_start = std::time::Instant::now();
        app.run_frame();
        
        // 锁 60 FPS
        let elapsed = frame_start.elapsed();
        if let Some(remaining) = frame_duration.checked_sub(elapsed) {
            std::thread::sleep(remaining);
        }
    }
}
```

```rust
// game_lib/src/lib.rs
#[repr(C)]
pub struct GameMemory {
    pub is_initialized: bool,
    pub frame_count: u64,
    pub player_x: f32,
    pub player_y: f32,
}

#[no_mangle]
pub unsafe extern "C" fn update_and_render(memory: *mut GameMemory) {
    let memory = unsafe { &mut *memory };
    
    if !memory.is_initialized {
        memory.player_x = 100.0;
        memory.player_y = 100.0;
        memory.is_initialized = true;
        println!("first init");
    }
    
    memory.frame_count += 1;
    memory.player_x += 1.0;
    
    if memory.frame_count % 60 == 0 {
        println!("frame {} pos ({}, {})", 
                 memory.frame_count, memory.player_x, memory.player_y);
    }
}
```

```toml
# Cargo.toml
[workspace]
members = ["game_lib", "platform"]
resolver = "2"

[profile.dev]
incremental = true
opt-level = 0

[profile.release]
opt-level = 3
lto = true
```

```toml
# game_lib/Cargo.toml
[lib]
name = "game_lib"
crate-type = ["cdylib"]
```

```toml
# platform/Cargo.toml
[dependencies]
libloading = "0.8"
```

```bash
# .cargo/config.toml(加速)
[build]
rustflags = ["-C", "link-arg=-fuse-ld=mold"]
```

## 14 · 进阶话题

### hot-lib-reloader crate

封装好的热重载库:

```toml
[dependencies]
hot-lib-reloader = "0.7"
```

```rust
use hot_lib_reloader::hot_lib_reloader;

#[hot_lib_reloader]
#[lib("game_lib")]
#[source_dir("target/debug")]
struct GameLib;

impl GameLib {
    pub fn update_and_render(memory: &mut GameMemory) {
        // 调用 game_lib 的函数
    }
}

fn main() {
    let mut memory = GameMemory::default();
    loop {
        GameLib::update_and_render(&mut memory);
    }
}
```

`hot-lib-reloader` 自动监听变化 + reload,你只管调用。比手写 libloading 简单。

### 跨 crate 共享类型

GameMemory 在 game_lib 定义,platform 也要看到。

方法:

```toml
# platform/Cargo.toml
[dependencies]
game_lib = { path = "../game_lib" }
```

```rust
// platform/src/main.rs
use game_lib::GameMemory;

let mut memory = GameMemory::default();
```

但**注意**:platform 静态链接 game_lib(Rust crate),会拉一份 game_lib 的代码。**reload 时,新 .so 是另一份 game_lib 代码**。

平台调用 .so 的 update_and_render,而不是静态链接的版本。OK,但要确保类型布局一致(`#[repr(C)]` 保证)。

更稳:把共享类型放第三个 crate:

```
handmade-hero/
├── shared/       (共享类型:GameMemory / GameInput)
├── game_lib/     (depends on shared)
└── platform/     (depends on shared)
```

### 资产热重载

热重载不只代码,资产(图片 / 音频)也可以:

```rust
fn check_asset_reload(&mut self) {
    let path = "assets/player.png";
    let mtime = std::fs::metadata(path).unwrap().modified().unwrap();
    
    if mtime != self.last_asset_mtime {
        self.player_sprite = load_png(path);
        self.last_asset_mtime = mtime;
    }
}
```

每次改图保存,游戏立刻看到新图。配合代码热重载,开发体验极佳。

## 15 · 总结

Rust 热重载完整链路:

1. **状态外置**:GameMemory 在 platform,reload 时不动
2. **代码 cdylib**:game_lib 编 cdylib,导出 extern "C" 函数
3. **libloading 加载**:platform 用 libloading 加载 .so
4. **mtime 检测**:每帧检查 .so mtime,变化就 reload
5. **cargo-watch 自动 build**:文件变化自动 cargo build
6. **容错**:build 失败保留旧 library
7. **ABI 稳定**:`#[no_mangle]` + `extern "C"` + `#[repr(C)]`
8. **POD 状态**:GameMemory 只用 POD,不用 Vec / String

掌握这套链路,你能在 Rust 项目实现 Casey HH 同等的热重载体验——1-3 秒从改代码到看到效果。

## 延伸阅读

本仓库:
- [day021](day021.md) / [day022](day022.md) / [day023](day023.md)——HH 热重载天数
- [deep-dives/platform-game-separation.md](platform-game-separation.md)——平台 / 游戏分离

外部:
- libloading:https://docs.rs/libloading/
- hot-lib-reloader:https://github.com/rksm/hot-lib-reloader
- cargo-watch:https://github.com/watchexec/cargo-watch
- Casey HH Day 21:https://guide.handmadehero.org/code/day021/
