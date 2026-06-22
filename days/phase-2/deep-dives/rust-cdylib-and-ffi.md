---
phase: 2
type: deep-dive
title: "Rust cdylib + FFI 完整指南:所有权 / 生命周期 / unsafe 边界"
domains: [rust, linux]
duration: "3h"
prereqs: ["day026", "day029", "phase-0/08-processes-and-signals", "phase-0/15-c-and-assembly-reading"]
---

# Rust cdylib + FFI 完整指南 · 所有权 / 生命周期 / unsafe 边界

> Rust 最强大的特性是所有权 / 借用 / 生命周期——它能编译期消除 use-after-free、double-free、data race。但跨 FFI(和 C / C++ / Python 交互)时,这些保护**全失效**。Casey 在 HH Day 026 用 cdylib 把游戏层编译成动态库,平台层通过 libloading 调用。这意味着每次调用游戏函数都是跨 FFI 边界,所有规则都改写。本文 3 小时讲透 Rust cdylib + FFI 的所有陷阱:ABI、生命周期标记、unsafe 边界、热重载状态保持、跨语言实战。

## 0 · 这篇文章解决什么问题

你做了 HH Day 026-029,实现 cdylib 热重载。代码大概这样:

```rust
// 游戏层(cdylib)
#[no_mangle]
pub extern "C" fn update_and_render(
    memory: &mut GameMemory,
    input: &GameInput,
    buffer: &mut GameOffscreenBuffer,
    dt: f32,
) {
    // ...
}
```

这看起来正常 Rust,但你心里有疑问:

1. **`memory` 是 `&mut`,为什么不会触发 borrow checker?** —— 因为函数从 FFI 调用,Rust 编译器看不到调用点
2. **`GameMemory` 里 `*mut c_void` 怎么 cast 成 `&mut GameState`?** —— unsafe,绕过所有规则
3. **如果平台层调两次 update_and_render(并发),会 UB 吗?** —— 会,但 Rust 不报错
4. **热重载后,旧的 GameState 还能用吗?** —— 用对就 OK,错了直接段错误
5. **C 代码怎么调 Rust cdylib?反过来呢?** —— extern "C" 双向

本文逐个回答这些问题。

读完本文,你能:

- 解释 Rust ABI 和 C ABI 的差别
- 用 `#[repr(C)]` 写 FFI 安全的结构体
- 处理跨 FFI 的生命周期(用 `'static`、`PhantomData`、raw pointer)
- 知道每行 unsafe 后面承担什么责任
- 写 Rust 函数给 C / Python / Node.js 调用
- 写 Rust 调 C / C++ 库(libclang-sys、libsqlite3-sys 等)

## 1 · ABI(Application Binary Interface)

### 1.1 ABI 是什么

**ABI** = 函数如何调用的低层规约。包括:

- 参数怎么传(寄存器 vs 栈)
- 返回值怎么返回(寄存器 vs 栈)
- 谁清栈(调用者 vs 被调用者)
- 结构体怎么布局(padding、对齐)
- 异常怎么传播

ABI 由**编译器 + 平台 + 操作系统**共同决定。同一份 C 代码,在 Linux x86_64 和 Windows x86_64 编译出的 .o 文件**不能互相 link**——ABI 不同。

### 1.2 C ABI(System V AMD64 / Microsoft x64)

C ABI 是跨语言通信的"通用语"。所有系统调用、所有动态库、所有 FFI 都用 C ABI。

Linux x86_64 用 System V AMD64 ABI:

- 前 6 个整数/指针参数在寄存器:RDI, RSI, RDX, RCX, R8, R9
- 前 8 个浮点参数在 XMM0-XMM7
- 返回值在 RAX(整数)或 XMM0(浮点)
- 栈 16 字节对齐

Windows x86_64 用 Microsoft x64 ABI:

- 前 4 个参数在 RCX, RDX, R8, R9(整数)或 XMM0-XMM3(浮点)
- 返回值在 RAX 或 XMM0
- shadow space(调用者预留 32 字节栈)

**两个 ABI 不兼容**——同一段 Rust 编译的 .dll 不能在 Linux 跑。

### 1.3 Rust ABI(不稳定!)

Rust 默认用 "Rust" ABI,这个 ABI **不稳定**——Rust 团队保留改名、改布局、改寄存器分配的权利。

例如,Rust 1.40 编译的 lib 和 Rust 1.85 编译的 lib **可能 ABI 不兼容**。

```rust
// Rust ABI(默认,不稳定)
pub fn foo(x: i32) -> i32 { ... }

// C ABI(稳定)
#[no_mangle]
pub extern "C" fn foo(x: i32) -> i32 { ... }
```

跨 FFI / 跨 cdylib 边界**必须用 `extern "C"`**。

### 1.4 `#[no_mangle]`

Rust 默认会修改函数名(name mangling),把类型信息编码进去。例如 `fn foo(x: i32)` 可能编译成 `_ZN3foo3barE`。

C 代码 `dlsym("foo")` 找不到——因为 mangled name 不是 `foo`。

`#[no_mangle]` 告诉编译器"别改名字",函数名就是 `foo`,dlsym 能找到。

## 2 · cdylib vs dylib vs rlib vs staticlib

Rust 有 4 种 crate-type,差别:

| crate-type | 输出 | 用途 |
|---|---|---|
| `bin` | 可执行文件 | main.rs |
| `lib`(default) | rlib | 给其他 Rust crate 用 |
| `rlib` | rlib | 同上(显式) |
| `dylib` | .so / .dll / .dylib | 给其他 **Rust** 程序动态 link |
| `cdylib` | .so / .dll / .dylib | 给 **C / 其他语言** 动态 link |
| `staticlib` | .a / .lib | 给 C 静态 link |

关键差别 **dylib vs cdylib**:

- **dylib**:Rust ABI,有 Rust runtime(metadata、panics、alloc),只能给 Rust 程序 link
- **cdylib**:C ABI,导出 `extern "C"` 函数,可给任何语言 link(libloading / dlopen / ctypes / FFI)

HH 用 **cdylib**(平台层用 libloading 加载)。

```toml
[lib]
name = "handmade_hero"
crate-type = ["cdylib", "rlib"]
```

同时是 cdylib(给 libloading)和 rlib(给单元测试,`cargo test` 需要)。

## 3 · `#[repr(C)]` 详解

### 3.1 为什么需要

Rust 默认会重排结构体字段以减少 padding:

```rust
struct Mixed {
    a: u8,    // 1 byte
    b: u64,   // 8 bytes,对齐 8
    c: u8,    // 1 byte
    d: u32,   // 4 bytes,对齐 4
}
// Rust 可能重排成:[b: u64, d: u32, a: u8, c: u8 + 6 padding] = 24 字节
// (避免 7 bytes padding)
```

这是优化,但破坏跨 FFI——如果 C 代码假设字段顺序是 `a, b, c, d`,读到的是错的。

### 3.2 `#[repr(C)]` 的行为

`#[repr(C)]` 强制:

1. 字段按**声明顺序**布局
2. 每个字段对齐到自己的对齐(可能产生 padding)
3. 整个结构体大小是最大字段对齐的倍数

```rust
#[repr(C)]
struct Mixed {
    a: u8,    // offset 0
    // 7 bytes padding(b 需要对齐 8)
    b: u64,   // offset 8
    c: u8,    // offset 16
    // 3 bytes padding(d 需要对齐 4)
    d: u32,   // offset 20
    // 4 bytes padding(struct size 对齐 8)
}
// 总大小:32 bytes
```

C 代码看到完全一样的布局。

### 3.3 `#[repr(C, packed)]`

`packed` 移除所有 padding:

```rust
#[repr(C, packed)]
struct Packed {
    a: u8,
    b: u64,  // 紧贴 a,无 padding
    c: u8,
    d: u32,
}
// 总大小:1 + 8 + 1 + 4 = 14 bytes
```

文件格式(BMP / WAV header)用 packed。

**警告**:packed struct 的字段可能**未对齐**。某些 CPU(早期 ARM)未对齐访问会 SIGBUS。x86 容忍但慢。

取字段要小心:

```rust
let m = Packed { a: 1, b: 2, c: 3, d: 4 };
let b = m.b;  // 可能未对齐访问!
// 安全写法:
let b = unsafe { std::ptr::addr_of!(m.b).read_unaligned() };
```

### 3.4 `#[repr(transparent)]`

包装一层新类型,但内存布局和内部完全一样:

```rust
#[repr(transparent)]
struct MyType(u32);
// MyType 和 u32 完全一样,可以 FFI 直接当 u32 用
```

适合 newtype pattern + FFI。

### 3.5 enum 的 repr

```rust
#[repr(C)]
enum Kind { A, B, C }  // C enum,通常是 int(4 字节)
```

`#[repr(C)]` enum 是 plain C enum。如果 enum 带数据:

```rust
#[repr(C)]
enum Event {
    Click,
    Key(u32),
    Resize { w: u32, h: u32 },
}
```

这是 tagged union。Rust 的 tagged union 布局是内部细节,**即使 `#[repr(C)]` 也不保证稳定跨 Rust 版本**。**FFI 边界不要用带数据的 enum**——用显式 union + tag 字段:

```rust
#[repr(C)]
struct Event {
    tag: u32,  // 0 = Click, 1 = Key, 2 = Resize
    payload: EventPayload,
}

#[repr(C)]
union EventPayload {
    key: u32,
    resize: ResizePayload,
}

#[repr(C)]
struct ResizePayload { w: u32, h: u32 }
```

C 代码看这个布局清晰,Rust 端封装成 enum 用。

## 4 · 跨 FFI 的生命周期

### 4.1 借用 vs 所有权

Rust 的借用规则:

```rust
fn foo(x: &i32)      // 借用,不拥有,函数返回后 x 还能被 caller 用
fn bar(x: &mut i32)  // 可变借用
fn baz(x: Box<i32>)  // 拥有,函数返回时 drop
```

跨 FFI 时,这些规则**完全靠人遵守**——编译器看不到 FFI 边界两侧的代码。

### 4.2 静态生命周期 `&'static`

```rust
#[no_mangle]
pub extern "C" fn get_version() -> *const u8 {
    b"1.0.0\0".as_ptr()
    // 字面量是 'static,永远有效
}
```

`&'static` 表示"整个程序周期内有效"。字符串字面量、`const`、`lazy_static` 都是 `'static`。

C 代码 `get_version()` 拿到指针,**永远可以读**,不需要释放。

### 4.3 持有引用的难题

```rust
// 错误:返回栈上引用
#[no_mangle]
pub extern "C" fn make_string() -> *const u8 {
    let s = format!("hello");  // String,栈上
    s.as_ptr()                  // 函数返回 s 被 drop,指针悬空!
}
```

返回的数据要么:

1. **'static**(字面量、`lazy_static`)
2. **Box::leak**(泄漏到堆)
3. **caller-provided buffer**(调用方给缓冲区,我们填)

### 4.4 Box::into_raw / from_raw(对象所有权转移)

```rust
#[no_mangle]
pub extern "C" fn create_player() -> *mut Player {
    let player = Box::new(Player::new());
    Box::into_raw(player)  // 转 raw pointer,不 drop
}

#[no_mangle]
pub extern "C" fn destroy_player(p: *mut Player) {
    if !p.is_null() {
        unsafe { drop(Box::from_raw(p)) };  // 重新拿回所有权,drop
    }
}
```

C 代码:

```c
Player* p = create_player();
// ... 用 p
destroy_player(p);  // 必须 destroy,否则泄漏
```

这是 C API 标准 pattern(malloc / free 的 Rust 版)。

### 4.5 跨 FFI 的可变借用

Rust 借用规则:`&mut T` 必须唯一。但跨 FFI 时,你不知道 caller 会不会并发调。

```rust
static mut STATE: Option<GameState> = None;

#[no_mangle]
pub extern "C" fn update(dt: f32) {
    unsafe {
        STATE.as_mut().unwrap().update(dt);
    }
}
```

`unsafe` 因为 static mut 访问。多线程并发调 update 是 UB(data race)。

**最佳实践**:不要用 static mut。把状态外置(GameMemory 模式),caller 管理生命周期。

### 4.6 PhantomData

有时候你需要表达"这个结构体借用了一个东西",但结构体内没有那个字段:

```rust
struct Iterator<'a> {
    ptr: *const u8,
    _phantom: PhantomData<&'a [u8]>,  // 告诉编译器:我借用了 'a 的 [u8]
}
```

`PhantomData` 是零大小,但告诉 borrow checker 这个类型的生命周期约束。

## 5 · unsafe 的 5 种用法

### 5.1 解引用 raw pointer

```rust
let x: i32 = 42;
let p: *const i32 = &x;
let y: i32 = unsafe { *p };  // 解引用 unsafe
```

为什么 unsafe:编译器不保证 p 有效(可能是悬空的、未对齐的、违反别名规则的)。

### 5.2 调用 unsafe 函数(包括 FFI)

```rust
extern "C" {
    fn abs(x: i32) -> i32;
}

let x = unsafe { abs(-5) };  // 调 extern 函数 unsafe
```

为什么 unsafe:编译器不知道 abs 的实现,可能 UB。

### 5.3 访问 / 修改 static mut

```rust
static mut COUNTER: i32 = 0;

fn increment() {
    unsafe { COUNTER += 1; }  // static mut 访问 unsafe
}
```

为什么 unsafe:多线程并发访问是 data race。

### 5.4 访问 union 字段

```rust
#[repr(C)]
union IntOrFloat {
    i: i32,
    f: f32,
}

let u = IntOrFloat { i: 42 };
let i = unsafe { u.i };  // union 访问 unsafe
```

为什么 unsafe:你可能读到无效的 bit pattern(把 i32 当 f32 读)。

### 5.5 实现 unsafe trait

```rust
unsafe trait MyTrait { /* ... */ }
unsafe impl MyTrait for i32 { /* ... */ }
```

为什么 unsafe:trait 的 invariant 由实现者保证,编译器无法验证。

## 6 · 不安全的根源:UB(Undefined Behavior)

### 6.1 什么是 UB

UB 是"程序行为不在语言规范定义内"。一旦 UB 发生:

- 编译器可以假设 UB 不发生,基于这个假设做激进优化
- 实际行为不可预测(可能崩、可能跑出错、可能看似正常但隐藏 bug)

Rust 的 unsafe 不创建 UB,它**取消编译器对 UB 的检查**。你写 unsafe 时,你必须**人工保证不 UB**。

### 6.2 常见 UB

1. **悬空指针**:`*p` 释放后又访问
2. **未对齐访问**:在不对齐的地址读 `u64`
3. **数据竞争**:多线程并发写同一变量
4. **违反别名规则**:两个 `&mut T` 指向同一数据
5. **无效枚举值**:`SomeEnum::from_u32(99)` 当合法 enum 用
6. **整数溢出**(debug panic,release wrapping,不算 UB 但要小心)
7. **除以零**(integer division by zero,panic)
8. **栈溢出**:无穷递归

### 6.3 排查 UB 的工具

- **MIRI**:Rust 内部 IR 解释器,运行时检测 UB(`cargo +nightly miri test`)
- **asan / msan**:AddressSanitizer / MemorySanitizer,检测内存错误
- **valgrind**:Linux 内存检查
- **loom**:Rust concurrency 测试

## 7 · 完整的 FFI 示例

### 7.1 Rust 给 C 调用

#### src/lib.rs(Rust)

```rust
use std::ffi::{CStr, CString};
use std::os::raw::c_char;

#[repr(C)]
pub struct Point {
    pub x: f32,
    pub y: f32,
}

#[no_mangle]
pub extern "C" fn distance(a: Point, b: Point) -> f32 {
    let dx = a.x - b.x;
    let dy = a.y - b.y;
    (dx * dx + dy * dy).sqrt()
}

#[no_mangle]
pub extern "C" fn greet(name: *const c_char) -> *mut c_char {
    let name = unsafe { CStr::from_ptr(name) };
    let name_str = match name.to_str() {
        Ok(s) => s,
        Err(_) => return std::ptr::null_mut(),
    };
    let greeting = format!("Hello, {}!", name_str);
    let c_greeting = CString::new(greeting).unwrap();
    c_greeting.into_raw()  // 转 raw pointer,caller 必须 free_greeting
}

#[no_mangle]
pub extern "C" fn free_greeting(s: *mut c_char) {
    if !s.is_null() {
        unsafe { drop(CString::from_raw(s)) };
    }
}
```

#### main.c(C)

```c
#include <stdio.h>
#include <stdint.h>

typedef struct { float x, y; } Point;
extern float distance(Point a, Point b);
extern char* greet(const char* name);
extern void free_greeting(char* s);

int main() {
    Point a = {0.0f, 0.0f};
    Point b = {3.0f, 4.0f};
    printf("distance: %f\n", distance(a, b));  // 5.0

    char* g = greet("World");
    printf("%s\n", g);
    free_greeting(g);
    return 0;
}
```

#### 编译和链接

```bash
# 编译 Rust cdylib
cargo build --release
# 产出 target/release/libmylib.so

# 编译 C
gcc main.c -L target/release -lmylib -o main

# 运行(需要 LD_LIBRARY_PATH 包含 .so 路径)
LD_LIBRARY_PATH=target/release ./main
# 输出:
# distance: 5.000000
# Hello, World!
```

### 7.2 Rust 调用 C 库

```rust
// 调用 C 标准库 abs
extern "C" {
    fn abs(x: i32) -> i32;
}

fn main() {
    let x = unsafe { abs(-5) };
    println!("{}", x);  // 5
}
```

更复杂的:用 `bindgen` 自动生成 Rust binding。

```bash
# 安装 bindgen
cargo install bindgen-cli

# 从 C header 生成 Rust binding
bindgen input.h -o bindings.rs
```

```rust
// bindings.rs(自动生成)
extern "C" {
    pub fn some_c_function(x: i32) -> i32;
}

// 用法
fn main() {
    let x = unsafe { some_c_function(42) };
}
```

### 7.3 Rust 给 Python 调用(PyO3)

```toml
[dependencies]
pyo3 = { version = "0.22", features = ["extension-module"] }

[lib]
name = "myrustmodule"
crate-type = ["cdylib"]
```

```rust
use pyo3::prelude::*;

#[pyfunction]
fn sum(a: i64, b: i64) -> i64 {
    a + b
}

#[pymodule]
fn myrustmodule(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(sum, m)?)?;
    Ok(())
}
```

```python
# Python
import myrustmodule
print(myrustmodule.sum(2, 3))  # 5
```

### 7.4 Rust 给 Node.js 调用(napi-rs)

```toml
[dependencies]
napi = "2"
napi-derive = "2"

[lib]
crate-type = ["cdylib"]
```

```rust
#[napi]
fn sum(a: i32, b: i32) -> i32 {
    a + b
}
```

```javascript
const { sum } = require('./myrustmodule');
console.log(sum(2, 3));  // 5
```

## 8 · 热重载的 FFI 完整链路

回到 HH 的场景:平台层用 libloading 加载 cdylib。整个链路的 unsafe:

```rust
use libloading::{Library, Symbol};

// 1. dlopen——unsafe 因为 .so 可能有恶意代码
let library: Library = unsafe { Library::new("libgame.so")? };

// 2. dlsym——unsafe 因为返回的 Symbol 持有 library 引用
let symbol: Symbol<UpdateFn> = unsafe { library.get(b"update_and_render")? };

// 3. 解引用 Symbol 拿到函数指针
let update_fn: UpdateFn = *symbol;

// 4. 调用函数——本身不是 unsafe(签名是 safe),但内部可能 unsafe
update_fn(&mut memory, &input, &mut buffer, dt);
```

每一步 unsafe 都承担:

1. **Library::new**:lib 是可信的吗?(开发期自己编译的可信,生产环境下载的可能不可信)
2. **library.get**:符号签名猜对了吗?(签名错就是 UB)
3. **\*symbol**:drop 顺序——library 必须 last drop
4. **update_fn**:内部用 unsafe 时(比如 cast raw memory),由游戏层负责

### 8.1 cast raw memory

游戏层接 `&mut GameMemory`,内部 cast 成 `&mut GameState`:

```rust
#[no_mangle]
pub extern "C" fn update_and_render(memory: &mut GameMemory, ...) {
    let state: &mut GameState = unsafe {
        // unsafe 因为:
        // 1. memory.storage 是 raw pointer,编译器不保证它有效
        // 2. 我们 cast 成 GameState,但实际可能不是 GameState(第一次是 raw 0)
        // 3. 别名规则:有没有别的地方也持有 GameState 的 &mut?
        &mut *(memory.storage as *mut GameState)
    };
}
```

程序员必须保证:

1. memory.storage 指向至少 `size_of::<GameState>()` 字节的合法内存
2. 内存里实际是合法的 GameState(第一次用 zeroed,后续 update 维护 invariant)
3. 同一时间只有一个 `&mut GameState`(平台层不并发调)

## 9 · 跨 cdylib 边界的类型

### 9.1 安全的跨边界类型

- 原始类型:`i32`, `f32`, `bool`, `u8`, ...
- `#[repr(C)]` struct(只含上述类型)
- `#[repr(C)]` enum(无数据)
- 原始指针:`*const T`, `*mut T`
- 函数指针:`extern "C" fn(...) -> ...`
- 固定大小数组:`[T; N]`

### 9.2 不安全的跨边界类型

- `Vec<T>`(内部布局是 Rust 内部)
- `String`(同上)
- `Box<T>`(布局可能变,且 ownership 语义不同)
- `Option<&T>`(null 优化,Rust 内部)
- `Result<T, E>`(同上)
- 带 lifetime 的引用(编译器假设 lifetime,FFI 不保证)
- trait object(`dyn Trait`,vtable Rust 内部)
- `Cell` / `RefCell` / `Mutex`(内部 unsafe 假设)

### 9.3 包装不安全类型

`Vec<T>` 不能跨 FFI,但你想要"Rust 返回一个数组给 C"。两种方案:

**方案 A:caller 提供 buffer**

```rust
#[no_mangle]
pub extern "C" fn fill_array(buffer: *mut f32, len: usize) -> usize {
    let data = compute_data();  // Vec<f32>
    let copy_len = data.len().min(len);
    unsafe {
        std::ptr::copy_nonoverlapping(data.as_ptr(), buffer, copy_len);
    }
    copy_len
}
```

C 调用:`float buf[100]; int n = fill_array(buf, 100);`

**方案 B:return raw pointer + length + free 函数**

```rust
#[no_mangle]
pub extern "C" fn compute_array(out_len: *mut usize) -> *mut f32 {
    let data = compute_data();
    let len = data.len();
    let mut data = data.into_boxed_slice();  // Vec → Box<[f32]>
    let ptr = data.as_mut_ptr();
    std::mem::forget(data);  // 不让 Box drop
    unsafe { *out_len = len; }
    ptr
}

#[no_mangle]
pub extern "C" fn free_array(ptr: *mut f32, len: usize) {
    if !ptr.is_null() {
        unsafe {
            let slice = std::slice::from_raw_parts_mut(ptr, len);
            let _ = Box::from_raw(slice as *mut [f32]);
        }
    }
}
```

C 调用:
```c
size_t len;
float* data = compute_array(&len);
// 用 data
free_array(data, len);
```

## 10 · 跨 ABI 的成本

### 10.1 函数调用开销

x86_64 上一次 `extern "C"` 调用大约 5-10 cycles(寄存器传参 + 保存 caller-saved 寄存器 + 实际调用)。

Rust 内部函数调用几乎 0 成本(内联)。所以**FFI 调用比内部调用慢 10-50 倍**。

### 10.2 优化策略

- **批量调用**:不要 1000 次 FFI(每次传一个 entity),改 1 次 FFI 传一个数组
- **缓存**:用 `once_cell` 缓存 dlopen 结果,不要每次调用都 dlopen
- **避免小数据**:传 `&[u8]` 比传 `u8` 高效(单次 FFI 传所有数据)

### 10.3 SIMD

Rust 的 `std::arch::x86_64::__m128` 跨 FFI 时和 C 的 `__m128` 一样(SIMD 类型有跨语言 ABI)。但要确保 `#[repr(C)]` 或 `transparent`。

## 11 · 错误处理

### 11.1 panic 跨 FFI

Rust panic 默认 unwind 栈。跨 FFI unwind 是 **UB**(C 代码不知道怎么 unwind)。

**解决 1**:`panic = "abort"`(Cargo.toml):

```toml
[profile.release]
panic = "abort"
```

panic 时直接 abort 进程,不 unwind。

**解决 2**:`catch_unwind`:

```rust
#[no_mangle]
pub extern "C" fn safe_function() -> i32 {
    std::panic::catch_unwind(|| {
        // 可能 panic 的代码
        risky()
    }).unwrap_or(-1)
}
```

panic 被捕获,函数返回错误码。但 catch_unwind 不保证所有 panic 都能 catch(`panic = "abort"` 时无效)。

### 11.2 返回错误码

C 风格错误处理:函数返回 0 成功,-1 失败,错误细节通过 out parameter 或全局 errno:

```rust
#[no_mangle]
pub extern "C" fn do_something(input: i32, error_msg: *mut *mut c_char) -> i32 {
    match try_do(input) {
        Ok(v) => v,
        Err(e) => {
            let msg = CString::new(e.to_string()).unwrap();
            unsafe { *error_msg = msg.into_raw(); }
            -1
        }
    }
}
```

## 12 · 调试 FFI 问题

### 12.1 segfault 怎么办

1. **gdb 调试**:`gdb ./program`,run,crash 时 bt 看堆栈
2. **检查 ABI**:函数签名两边一致吗?
3. **检查 repr(C)**:struct 加了吗?
4. **检查生命周期**:返回的指针是不是悬空?

### 12.2 valgrind(Linux)

```bash
valgrind --tool=memcheck ./program
# 看 Invalid read / Invalid write / Definitely lost
```

valgrind 能检测到内存错误(use-after-free、未初始化读、buffer overflow)。

### 12.3 MIRI

```bash
cargo +nightly miri test
```

MIRI 检测 UB(data race、未定义内存、违反别名规则)。是 Rust 独有的最强 UB 检测工具。

### 12.4 ltrace / strace

```bash
ltrace ./program  # 看 library call
strace ./program  # 看 system call
```

可以看出 dlopen / dlsym 是否成功。

## 13 · 完整 cdylib 项目模板

```
my_cdylib/
├── Cargo.toml
├── src/
│   ├── lib.rs       # cdylib 入口(extern "C" 函数)
│   ├── api.rs       # 公开 API
│   ├── internal.rs  # 内部实现(safe Rust)
│   └── ffi.rs       # FFI helper(CString / raw pointer 包装)
└── tests/
    └── integration.rs  # 测试 extern "C" 函数
```

### 13.1 Cargo.toml

```toml
[package]
name = "my_cdylib"
version = "0.1.0"
edition = "2021"

[lib]
name = "my_cdylib"
crate-type = ["cdylib", "rlib"]

[profile.release]
panic = "abort"      # panic 不 unwind,FFI 安全
opt-level = 3
lto = true
codegen-units = 1
```

### 13.2 src/lib.rs

```rust
mod api;
mod internal;
mod ffi;

// 导出 C API
pub use api::*;

// 内部实现全 safe Rust
// extern "C" 函数只是 thin wrapper
```

### 13.3 src/api.rs(extern "C" wrapper)

```rust
use crate::internal;
use std::ffi::CStr;
use std::os::raw::c_char;

#[no_mangle]
pub extern "C" fn my_api_init() -> *mut internal::State {
    let state = Box::new(internal::State::new());
    Box::into_raw(state)
}

#[no_mangle]
pub extern "C" fn my_api_destroy(state: *mut internal::State) {
    if !state.is_null() {
        unsafe { drop(Box::from_raw(state)) };
    }
}

#[no_mangle]
pub extern "C" fn my_api_do(
    state: *mut internal::State,
    input: *const c_char,
) -> i32 {
    if state.is_null() || input.is_null() {
        return -1;
    }
    let state = unsafe { &mut *state };
    let input = unsafe { CStr::from_ptr(input) };
    let input_str = match input.to_str() {
        Ok(s) => s,
        Err(_) => return -2,
    };

    match std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        internal::do_work(state, input_str)
    })) {
        Ok(()) => 0,
        Err(_) => -3,
    }
}
```

### 13.4 src/internal.rs(safe Rust 实现)

```rust
pub struct State {
    pub counter: i32,
}

impl State {
    pub fn new() -> Self {
        Self { counter: 0 }
    }
}

pub fn do_work(state: &mut State, input: &str) {
    state.counter += 1;
    println!("[{}] processing: {}", state.counter, input);
}
```

注意 internal.rs **全是 safe Rust**,没有 unsafe。所有 unsafe 隔离在 api.rs(FFI 边界)。

### 13.5 tests/integration.rs

```rust
use my_cdylib::*;

#[test]
fn test_api() {
    let state = my_api_init();
    assert!(!state.is_null());

    let input = std::ffi::CString::new("hello").unwrap();
    let result = my_api_do(state, input.as_ptr());
    assert_eq!(result, 0);

    my_api_destroy(state);
}
```

`cargo test` 用 rlib,能直接调 `extern "C"` 函数(同进程,Rust ABI 兼容 C ABI)。

## 14 · 延伸阅读

本仓库:
- [day026.md](day026.md) —— 第一次写 cdylib
- [day029.md](day029.md) —— 完整接口层
- [deep-dives/platform-game-separation.md](platform-game-separation.md) —— 平台/游戏分离
- [deep-dives/hot-reload.md](hot-reload.md) —— 热重载完整链路
- [phase-0/08-processes-and-signals.md](../phase-0/08-processes-and-signals.md) —— dlopen 的底层
- [phase-0/15-c-and-assembly-reading.md](../phase-0/15-c-and-assembly-reading.md) —— 读汇编

外部:
- Rust Book ch.19(Unsafe): https://doc.rust-lang.org/book/ch19-01-unsafe-rust.html
- Rustonomicon(深入 unsafe): https://doc.rust-lang.org/nomicon/
- Rust FFI Omnibus: http://jakegoulding.com/rust-ffi-omnibus/
- libloading 文档: https://docs.rs/libloading/latest/libloading/

开源源码:
- libloading: https://github.com/nagisa/rust_libloading
- PyO3(Rust + Python): https://github.com/PyO3/pyo3
- napi-rs(Rust + Node): https://github.com/napi-rs/napi-rs
- bindgen(自动 binding): https://github.com/rust-lang/rust-bindgen
