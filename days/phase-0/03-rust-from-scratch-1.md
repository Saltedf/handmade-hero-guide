
# 03 · Rust 从零(1):安装、cargo、变量、类型、控制流

> 从这一篇开始,你正式学 Rust。后面 664 天的所有代码都用 Rust 写。本篇覆盖 The Rust Book 第 1-3 章:装好工具链、用 cargo 建项目、理解变量和类型、写控制流。读完你能看懂任何 Rust 程序的骨架。

## 0 · 为什么要有这一天

Casey 用 C 写 Handmade Hero。我们用 Rust 翻译。为什么?

1. **C 的痛点**:指针乱飞、内存泄漏、buffer overflow、Undefined Behavior(UB)。Casey 自己视频里也常 debug 几个小时才发现是初始化没做对。
2. **Rust 的承诺**:编译期保证**内存安全**和**线程安全**,没有 GC(垃圾回收)。**只要代码编译通过,就不会有数据竞争**(并发 bug)。**只要编译通过,就不会 use-after-free**。
3. **零开销抽象**:Rust 的高级特性(迭代器、trait、泛型)编译后和手写 C 一样快。Casey 风格的"贴近金属"用 Rust 完全可以表达。
4. **生态成熟**:rustc 编译器、cargo 包管理器、crates.io 生态、rust-analyzer IDE 支持,2024 年已经完备。
5. **真正开源**:Rust 自身用 Rust 写,公开演进,任何人可以提 RFC 和 PR。

但 Rust 不简单。它的**所有权(ownership)**、**借用(borrow)**、**生命周期(lifetime)**是其他语言没有的概念,新手会卡。本系列 4 篇文章手把手带你过这道坎。这是第 1 篇——地基。学完 4 篇你能读懂 Casey 的 C 代码同时用 Rust 表达同样的事。

**心理锚点**:读完这一篇,你能:
- 装 Rust 工具链,跑通 hello world
- 用 cargo 新建、构建、运行、测试项目
- 解释 `let` / `let mut` / `const` / `static` 的差别
- 知道 `i32`, `f64`, `bool`, `char`, `&str`, `String`, tuple, array 的取舍
- 写 if/else、loop/while/for、match
- 读 Rust 编译器的报错并修复

## 1 · 概念地图:rustc / cargo / rustup / crates.io

| 词 | 是什么 | 类比 |
|---|---|---|
| **Rust** | 一门系统编程语言 | C++ 的现代替代 |
| **rustc** | Rust 编译器(把 `.rs` 编成机器码) | gcc / clang 的 Rust 版 |
| **cargo** | Rust 的包管理器 + 构建工具 + 测试运行器 | npm (Node) / pip (Python) / maven (Java) 的合体 |
| **rustup** | Rust 工具链管理器(管理多个 rustc 版本) | nvm (Node) / pyenv (Python) 的 Rust 版 |
| **crate** | 一个 Rust 包(库或可执行) | Python 的 package / Node 的 module |
| **module** | crate 内部的代码组织单元 | Python 的 module / Java 的 package |
| **crates.io** | Rust 公共包仓库 | npmjs.com / pypi.org |
| **rust-analyzer** | Rust 的 LSP 语言服务器(IDE 智能提示) | clangd / pyright |
| **stable / beta / nightly** | Rust 的三个发布频道 | 大多数项目用 stable; nightly 有实验特性 |

**关键关系**:
- `rustup` 装 `rustc` 和 `cargo`(它们绑在一起)
- 你写代码 → `cargo build` → `rustc` 真正编译
- `cargo` 从 `crates.io` 下载依赖,缓存到 `~/.cargo/`
- 你不直接调 `rustc`,永远通过 `cargo`

## 2 · 心智模型

### 费曼类比:Rust 是"带守卫的车间"

把编程想成一个车间。C 语言的车间是个**没有守卫**的车间——你可以拿起任何工具做任何事,包括把手放到电锯下面。生产快,但事故多。

Python / Java / JS 的车间有**自动救援队**(GC),事故发生时它会跑来清理,但你不知道它什么时候来,可能打断生产(暂停)。

**Rust 的车间**有一个**编译期守卫**(borrow checker)。你要做任何事(借工具、传递材料)都得先填表说明:
- 谁拥有这把工具(所有权)
- 你借多久(借用)
- 借多久才还(生命周期)

填错表(违反规则),守卫在**编译时**就拦住你,程序根本编译不通过。但只要编译通过,运行时几乎没有事故。

代价是:**学习曲线陡**(要懂规则),**编译慢**(守卫要检查每个角落)。
回报是:**运行时安全**、**没有 GC 暂停**、**性能和 C 一样**。

这一篇只讲地基(变量、类型、控制流),守卫(ownership / borrow)在下一篇 04。先把地基打好,你才不会在守卫面前懵。

### Rust 的核心承诺(为什么它能这样设计)

Rust 编译器做的事:
1. 解析 `.rs` 文件成 AST(抽象语法树)
2. 做类型检查(每个变量什么类型,函数签名匹配不)
3. **做借用检查**(borrow check)——这是 Rust 独有的:分析每个引用的生命周期、可变性,确保规则被遵守
4. 优化(MIR → LLVM IR → 机器码)
5. 链接生成可执行

第 3 步是 Rust 杀手锏。C / C++ 编译器没有这步,所以运行时才暴露问题。Python / Java 不在编译时检查内存,运行时 GC 兜底。

### 编译期 vs 运行时

新手要区分两件事:

- **编译期(compile time)**:rustc 在分析代码时。类型检查、borrow 检查都在这里。**没有实际的数字在跑**,只是分析
- **运行时(runtime)**:程序跑起来后。变量真的有值,函数真的被调

例:

```rust
let x: i32 = "hello";  // 编译期错误:类型不匹配
let y = 1 / 0;          // 编译期不报错(无法判断除数是否 0),运行时 panic
```

Rust 设计哲学:**能编译期检查的,绝不留到运行时**。

## 3 · 四域深入

### 3.1 · 🐧 Linux 系统编程视角

Rust 是 Linux 上系统编程的新星。Linux 内核从 6.1 开始接受 Rust 代码(2022 年)。Rust 在 Linux 生态的角色:

- **systemd 部分组件用 Rust 重写**
- **核心工具的 Rust 替代**:`ripgrep`(grep)、`fd`(find)、`bat`(cat)、`exa`(ls)、`zoxide`(cd)、`starship`(prompt)
- **新一代服务**:`deno`(JS runtime)、`ruff`(Python linter)、`uv`(Python 包管理器)
- **图形栈**:wgpu(Vulkan 抽象)、bevy(游戏引擎)、iced(GUI)

为什么 Rust 适合系统编程:
- **没有 GC**:有 GC 的语言(Go、Java)不适合实时场景
- **没有 runtime**:Rust 程序不依赖虚拟机,启动快,内存占用小
- **ABI 兼容 C**:可以从 Rust 调 C 库(FFI),也可以从 C 调 Rust
- **cross-compile**:cargo 跨平台编译简单

### 3.2 · 🦀 Rust 生态视角(本篇核心)

#### 3.2.1 装 Rust

用 rustup(官方推荐,不用 pacman 直接装,这样能管理多版本):

```bash
# 装 rustup(Arch 用 pacman,其他发行版用 rustup 官方脚本)
sudo pacman -S rustup

# 装默认工具链(stable)
rustup default stable

# 验证
rustc --version
cargo --version
# 输出类似:
# rustc 1.82.0 (f6e511eec 2024-10-15)
# cargo 1.82.0 (8f40fc59f 2024-08-21)

# 装其他组件(IDE 用)
rustup component add rust-src rust-analyzer clippy rustfmt
# rust-src       - 标准库源码(IDE 跳转用)
# rust-analyzer  - LSP 服务器(IDE 智能提示)
# clippy         - lint 工具(揪出常见错误)
# rustfmt        - 代码格式化
```

为什么不直接 `pacman -S rust`:pacman 装的 rust 是固定的版本,而你后面跟开源项目可能要 nightly(实验特性)。rustup 让你灵活切换。

#### 3.2.2 用 cargo 创建项目

```bash
# 新建一个 binary(可执行)项目
cargo new hello
# 输出:Created binary (application) `hello` package

# 看结构
cd hello
ls -la
# Cargo.toml   - 项目配置(像 package.json)
# Cargo.lock   - 依赖锁定(自动生成,要 commit 给 binary)
# src/
#   main.rs    - 程序入口
# .git/        - 自动初始化的 git repo
# .gitignore   - 自动加了 /target

# 看默认 main.rs
cat src/main.rs
# fn main() {
#     println!("Hello, world!");
# }

# 编译 + 运行
cargo run
# 输出:
# Compiling hello v0.1.0 (/home/sun/hello)
#  Finished dev [unoptimized + debuginfo] target(s) in 0.5s
#    Running `target/debug/hello`
# Hello, world!

# 不运行,只编译
cargo build
# 生成 target/debug/hello(可执行)

# 发布构建(优化)
cargo build --release
# 生成 target/release/hello,优化打开,体积小,跑得快

# 跑测试
cargo test

# 检查(只编译不生成,比 build 快,IDE 用)
cargo check

# 格式化代码
cargo fmt

# lint
cargo clippy
```

每个命令后做什么:

- `cargo new` 创建标准结构:src/main.rs、Cargo.toml、.git/
- `cargo run` = `cargo build` + 运行生成的二进制
- `target/` 是构建产物,**不**应该 commit(`.gitignore` 自动忽略它)
- `cargo build --release` 开 `-O3` 优化,适合发布;调试用 `cargo build`

#### 3.2.3 Cargo.toml 详解

打开 `Cargo.toml`:

```toml
[package]
name = "hello"          # crate 名
version = "0.1.0"        # 语义版本(major.minor.patch)
edition = "2021"         # Rust edition(每 3 年一次,2021 是当前默认)

[dependencies]
# 这里列依赖,例如:
# serde = { version = "1.0", features = ["derive"] }
# tokio = { version = "1", features = ["full"] }
```

**edition** 不是 rustc 版本!edition 是 Rust 语言的"版本集",每 3 年一次:2015、2018、2021、2024。edition 决定哪些新语法可用。每个 crate 选一个 edition,各 crate 可以混合。

#### 3.2.4 变量:`let` / `let mut` / `const` / `static`

Rust 的变量默认**不可变(immutable)**:

```rust
let x = 5;        // 不可变
// x = 6;         // 编译错误:cannot assign twice to immutable variable
let mut y = 5;    // 可变(mut 是 mutable 的缩写)
y = 6;             // OK

const MAX: u32 = 100_000;  // 常量(必须大写,必须显式类型,编译期求值)
// const 不能用函数返回值赋值,只能用字面量或常量表达式

static GREETING: &str = "Hello";  // 静态变量(有固定内存地址,'static 生命周期)
```

四个概念的差别:

| 关键字 | 可变性 | 求值时机 | 生命周期 |
|---|---|---|---|
| `let x = 5` | 不可变 | 运行时 | 当前 scope |
| `let mut x = 5` | 可变 | 运行时 | 当前 scope |
| `const X: i32 = 5` | 不可变(永远) | 编译期(必须能常量求值) | 整个程序(inline 进每次使用) |
| `static X: i32 = 5` | 不可变(可加 mut) | 编译期 | 整个程序(固定地址) |

为什么默认不可变?**安全的并发**。多线程共享可变状态是 bug 之源。Rust 让你**主动用 mut**表示"我要改它",强迫你想清楚。

**变量遮蔽(shadowing)**:

```rust
let x = 5;
let x = x + 1;       // 用同名变量遮蔽前一个
let x = "hello";     // 可以改变类型!这是 shadowing 比 mut 强的地方
```

shadowing 不是 mutation,是**新声明了一个变量**,旧 x 还在(但被遮蔽看不见了)。可以用它做"转换后重命名"。

#### 3.2.5 数据类型

**标量类型(scalar)**:

| 类型 | 含义 | 字面量例子 |
|---|---|---|
| `i8 / i16 / i32 / i64 / i128 / isize` | 有符号整数 | `-5`, `100`, `1_000_000` |
| `u8 / u16 / u32 / u64 / u128 / usize` | 无符号整数 | `255u8`, `0xFFu8`, `0b1010u8` |
| `f32 / f64` | 浮点(IEEE 754) | `3.14`, `2.0f32` |
| `bool` | 布尔 | `true`, `false` |
| `char` | Unicode 标量值(4 字节) | `'a'`, `'中'`, `'🦀'` |

`isize` / `usize` 是"和指针一样大"——64 位机器上是 64 位。**数组索引、内存大小都用 usize**。

整数字面量前缀:`0x` 十六进制,`0o` 八进制,`0b` 二进制,`_` 是分隔符(为了可读性,`1_000_000` = 100 万)。

整数字面量后缀:`255u8` 显式指定类型。不加后缀时,rustc 根据上下文推断,推断不出时默认 `i32`。

**整数溢出**:debug 模式 panic,release 模式 wrap(回绕)。要明确行为用 `wrapping_*` / `checked_*` / `saturating_*` 方法。

**复合类型**:

```rust
// 元组(tuple):固定长度,可以不同类型
let pair: (i32, f64) = (500, 6.4);
let (a, b) = pair;       // 解构
let first = pair.0;      // 索引访问(从 0 开始)
let second = pair.1;
let unit: () = ();       // 单元类型(空元组),函数无返回时是它

// 数组(array):固定长度,同类型,栈上分配
let arr: [i32; 5] = [1, 2, 3, 4, 5];
let zeros = [0; 10];     // 10 个 0
let first = arr[0];
// arr[10] 会 panic(越界)
```

array vs Vec(下一篇讲):
- `[T; N]` 是固定长度,**栈**上分配,长度编译期已知
- `Vec<T>` 是动态长度,**堆**上分配,运行时可增长

**字符串**:

Rust 有两种字符串,新手最容易混:

```rust
let s1: &str = "hello";       // 字符串切片,不可变,引用某段 UTF-8 字节
let s2: String = String::from("hello");  // 拥有所有权的字符串,堆上分配,可增长
```

- `&str`("string slice"):**只读**视图,引用某段内存里的 UTF-8 字节。**没有所有权**(下一篇讲)。字面量 `"hello"` 是 `&'static str`(程序整个生命期都存在)
- `String`:**可变,拥有所有权**,堆上分配。能 push、pop、修改

为什么两种:**性能**。绝大多数场景只需要看一段文本(`&str`),少数场景需要构造和修改(`String`)。区分让函数签名明确表达"我只读"还是"我拥有"。

字符串是 **UTF-8** 编码的,字节和字符不一一对应:

```rust
let s = "你好";
println!("{}", s.len());       // 6(6 个 UTF-8 字节)
println!("{}", s.chars().count()); // 2(2 个 Unicode 字符)
```

#### 3.2.6 控制流

**if / else if / else**:

```rust
let number = 6;

if number % 4 == 0 {
    println!("divisible by 4");
} else if number % 3 == 0 {
    println!("divisible by 3");
} else {
    println!("not divisible by 4 or 3");
}

// if 是表达式,可以用来赋值
let x = if number > 5 { 10 } else { 20 };
// 两支必须同类型!否则编译错
```

**注意**:Rust 的 if 条件**必须**是 `bool`,不会自动转换。`if 1 { ... }` 是错的(C 里 1 是 true,Rust 严格区分)。

**loop(无限循环,带 break)**:

```rust
let mut counter = 0;
let result = loop {
    counter += 1;
    if counter == 10 {
        break counter * 2;   // break 带值,作为 loop 表达式的返回
    }
};
// result == 20
```

**while**:

```rust
let mut n = 3;
while n != 0 {
    println!("{n}!");
    n -= 1;
}
```

**for(遍历迭代器)**:

```rust
let arr = [10, 20, 30, 40, 50];

for element in arr {
    println!("value: {element}");
}

// 范围(range):
for i in 0..5 {       // 0,1,2,3,4(不含 5)
    println!("{i}");
}
for i in 0..=5 {      // 0,1,2,3,4,5(含 5)
    println!("{i}");
}

// 反向 + 步长:
for i in (1..10).rev() { ... }     // 倒序
for i in (0..20).step_by(2) { ... } // 0,2,4,...
```

**match(Rust 的 switch,但强大得多)**:

```rust
let coin = 25;
match coin {
    1 => println!("penny"),
    5 => println!("nickel"),
    10 => println!("dime"),
    25 => println!("quarter"),
    _ => println!("unknown"),     // _ 是通配,匹配任意
}

// match 也是表达式
let description = match coin {
    1 => "penny",
    5 => "nickel",
    _ => "other",
};

// match 必须穷尽所有可能(exhaustive),否则编译错
```

**if let(简化 match)**:

```rust
// 只关心一种情况时,if let 比 match 简洁
let some_value = Some(5);
if let Some(n) = some_value {
    println!("got {n}");
} else {
    println!("nothing");
}
```

枚举(`Option`)下一篇文章细讲,这里只要知道 `Some(5)` 是个"可能有值"的容器。

#### 3.2.7 函数

```rust
// 无返回值(隐式返回单元 ())
fn greet() {
    println!("hello");
}

// 有参数和返回类型
fn add(a: i32, b: i32) -> i32 {
    a + b       // 最后一行无分号,作为返回值(称为"表达式")
    // 如果写成 a + b; 就返回 () 了
}

// 多语句
fn complex(x: i32) -> i32 {
    let y = x * 2;
    let z = y + 1;
    z           // 返回 z
}

// 提前返回
fn abs(x: i32) -> i32 {
    if x < 0 {
        return -x;   // return 关键字 + 分号,提前返回
    }
    x               // 否则返回 x
}
```

**语句(statement)vs 表达式(expression)**——Rust 的关键区别:

- 语句:执行动作,不返回值。`let x = 5;` 是语句(不能写 `let y = (let x = 5);`)
- 表达式:求值为某个值。`5`、`x + 1`、`{ ... }` 块(最后无分号的表达式是块的值)

```rust
let y = {
    let x = 3;
    x + 1          // 块的值是 4
};
// y == 4
```

这是为什么函数最后一行**不能加分号**——加了就变成语句,返回 `()`。

### 3.3 · 🎮 游戏编程视角

Rust 在游戏开发生态:

- **bevy**:Rust 最流行的 ECS(实体-组件-系统)游戏引擎
- **wgpu**:Vulkan/Metal/D3D12/WebGPU 的跨平台抽象,handmade-hero 后面 Phase 5 用它做 GPU 渲染
- **macroquad**:轻量 2D 库,适合学习
- **ggez**:受 LÖVE( Lua)启发的 2D 库

变量、类型、控制流——这些都是基础,和具体语言无关。但 Rust 的 `match` 在游戏里特别有用:状态机(state machine)用 match 表达最自然:

```rust
enum GameState { Menu, Playing, Paused, GameOver }

fn update(state: GameState) {
    match state {
        GameState::Menu => draw_menu(),
        GameState::Playing => update_world(),
        GameState::Paused => draw_pause_overlay(),
        GameState::GameOver => show_game_over(),
    }
}
```

枚举 + match 在第 5 篇深入。

## 4 · 认知地图

### 4.1 上级

- **系统编程语言** — 直接操作系统资源(内存、文件、网络)的语言。C / C++ / Rust / Zig
- **静态强类型语言** — 编译期检查类型,且不允许隐式类型转换。Rust、Haskell、TypeScript(部分)。Python / JS 是动态弱类型
- **零开销抽象** — 高级抽象不引入运行时开销。C++ 提出,Rust 继承

### 4.2 同级

| 语言 | 关键差别 | 何时用 |
|---|---|---|
| Rust | 无 GC,编译期内存安全,强类型 | 系统编程、性能敏感、需要安全 |
| C | 最贴近硬件,手动内存管理,有 50 年历史 | 内核、嵌入式、维护老代码 |
| C++ | C 加 OOP 加模板,极其复杂 | 游戏引擎、高频交易 |
| Go | 有 GC,极简语法,并发原生 | 网络服务、微服务 |
| Zig | C 替代品,无隐藏控制流,无隐式分配 | 嵌入式、C 替代 |
| Odin | C 替代品,游戏导向 | 游戏(Casey 朋友圈影响) |

Handmade Hero 教程选 Rust 因为它**最安全 + 性能不输 C + 生态成熟**。

### 4.3 下级

- **rustc 内部**:Lexer → AST → HIR → MIR → LLVM IR → 机器码。borrow check 发生在 MIR 阶段
- **cargo 子命令**:build / run / test / check / fmt / clippy / doc / bench / update
- **基本类型系统**:整数(i*/u*)、浮点(f*)、bool、char、tuple、array、&str、String、slice、unit
- **控制流**:if/else、loop、while、for、match、if let、while let、break、continue、return
- **函数**:参数、返回类型、表达式 vs 语句、提前 return

## 5 · 对照与变奏

### Rust vs C:变量和类型

```c
// C
int x = 5;
x = 6;          // C: 默认可变
char* s = "hello";   // C: 字符串就是 char 数组
int arr[5] = {1,2,3,4,5};
```

```rust
// Rust
let x = 5;
// x = 6;       // 错:默认不可变
let mut x = 5; x = 6;  // OK
let s: &str = "hello";     // 字符串切片
let arr: [i32; 5] = [1, 2, 3, 4, 5];
```

最大差别:**Rust 默认不可变**,要变必须显式 `mut`。这避免了"我以为是常量但被改了"的 bug。

### Rust vs Python:类型系统

```python
# Python
x = 5          # int
x = "hello"    # str(同一个变量,类型变了)
```

```rust
// Rust
let x = 5;
// let x = "hello"; // 这是 shadowing,新声明,不是修改
let mut y = 5;
// y = "hello";      // 错:类型不匹配
```

Rust 一个变量(在 shadowing 之前的)只有一种类型,编译期固定。这让编译器能给更好的优化和检查。

### 整数溢出:不同语言的处理

- **C / C++**:有符号整数溢出是 UB(未定义行为),编译器可以假设不会发生
- **Python**:整数任意精度,永不溢出(但慢)
- **Java**:整数 wrap,没 UB 但也不报错(静默错误)
- **Rust debug 模式**:溢出 panic(立即报告)
- **Rust release 模式**:wrap(和 Java 一样),但提供 `checked_*` / `wrapping_*` / `saturating_*` 方法让你明确

Rust 的设计:**debug 模式紧,release 模式快**,但**永远给你显式选项**。

## 6 · 关联 Day

- **铺垫**:
  - [00-terminal-basics.md](00-terminal-basics.md) — 命令行
  - [01-arch-setup.md](01-arch-setup.md) — `pacman -S rustup`
- **当天**:[03-rust-from-scratch-1.md](03-rust-from-scratch-1.md)(本篇)
- **后续**:
  - [04-rust-from-scratch-2.md](04-rust-from-scratch-2.md) — 所有权 / 借用 / 切片(Rust 最难)
  - [05-rust-from-scratch-3.md](05-rust-from-scratch-3.md) — struct / enum / Result / 错误处理
  - [06-rust-from-scratch-4.md](06-rust-from-scratch-4.md) — trait / 泛型 / 生命周期 / 迭代器
  - Phase 1 Day 001:你写的第一行 Rust 项目代码

## 7 · 变式训练

### Lv1 · 概念辨析

**题**:下面四段代码哪些能编译通过,哪些不能,为什么?

```rust
// A
let x = 5;
let x = x + 1;

// B
let x = 5;
x = x + 1;

// C
let mut x = 5;
x = x + 1;

// D
const X: i32;
X = 5;
```

**参考解答**:
- **A 通过**:用了 shadowing,第二行是新声明(不是赋值)。注意第二行的 `x` 是新变量,旧 x 被遮蔽
- **B 不通过**:`x` 是 immutable,第二行试图赋值,编译错误 `cannot assign twice to immutable variable x`
- **C 通过**:`x` 是 mut,可以重新赋值
- **D 不通过**:`const` 必须在声明时初始化,不能后赋值。正确写法是 `const X: i32 = 5;`

### Lv2 · 动手实践

**题**:写一个程序,完成斐波那契数列前 10 项的打印。要求:

1. 用 `cargo new fib` 建项目
2. 实现函数 `fn fib(n: u32) -> u64`(返回第 n 项,n 从 0 开始)
3. 在 main 里 for 循环打印前 10 项
4. 跑 `cargo run`,看到 `0 1 1 2 3 5 8 13 21 34`
5. 跑 `cargo clippy`,没有 warning
6. 跑 `cargo fmt`,代码格式化

完成标准:`cargo run` 输出正确序列。

**参考解答**:

```rust
// src/main.rs
fn fib(n: u32) -> u64 {
    // 用迭代实现,不用递归(递归会指数慢)
    if n == 0 {
        return 0;     // fib(0) = 0
    }
    let mut a: u64 = 0;  // 前一项
    let mut b: u64 = 1;  // 当前项
    for _ in 1..n {      // _ 表示"不用这个变量"
        let next = a + b;
        a = b;
        b = next;
    }
    b                    // 返回 b(无分号,作为返回值)
}

fn main() {
    for i in 0..10 {
        print!("{} ", fib(i));
    }
    println!();          // 最后换行
}
```

**关键点**:
- 函数参数和返回值类型必须显式
- `for _ in 1..n`:`_` 表示不关心这个值,只重复 n-1 次
- 最后 `b` 无分号,是函数返回值
- 用迭代而非递归,避免指数级时间复杂度

### Lv3 · 迁移设计

**题**:温度转换器。写一个程序,接受命令行参数(摄氏或华氏),输出转换结果。要求:

- 支持 `100C` → `212F`(摄氏转华氏)
- 支持 `100F` → `37.78C`(华氏转摄氏)
- 输入非法时打印 usage
- 用 `match` 处理后缀(C / F)

**提示**:
- 用 `std::env::args()` 拿命令行参数
- `s.ends_with('C')` 判断后缀
- `s.trim_end_matches('C').parse::<f64>()` 解析数字
- match 字符串切片:`match suffix { "C" => ..., "F" => ..., _ => ... }`

不要看答案,自己写。完成标准:三种情况(正常 C、正常 F、错误输入)都正确处理。

### Lv4 · 开源贡献

**题**:`rustlings` 是 Rust 官方的练习项目(GitHub: https://github.com/rust-lang/rustlings),帮你通过"修复编译错误"学 Rust。

1. clone 它(或 fork 后 clone)
2. 跑 `rustlings` 它会逐个练习
3. 完成 `exercises/01_variables/` 和 `exercises/02_functions/` 和 `exercises/03_if/` 的所有练习
4. 每个练习都是"故意有错的代码",你修对让它编译通过
5. 如果发现某个练习的描述不清楚、有 typo、或测试 case 不充分,**这就是 PR 机会**

写下你修了多少个练习,以及发现的潜在 PR 机会。

## 8 · Rust / Arch 落地代码

### 完整环境配置

```bash
# 1. 装 rustup(Arch 官方源)
sudo pacman -S rustup

# 2. 装默认 stable 工具链
rustup default stable
# 输出:
# info: syncing channel updates for 'stable-x86_64-unknown-linux-gnu'
# info: latest update on 2024-XX-XX, rust version 1.82.0
# ...

# 3. 加 IDE 必需组件
rustup component add rust-src rust-analyzer clippy rustfmt

# 4. 验证
rustc --version
cargo --version
rustfmt --version
cargo-clippy --version

# 5. (可选)装 nightly(后面 Phase 5 用 portable-simd 需要)
rustup toolchain install nightly
# 切换某项目到 nightly:
# cd 项目目录
# rustup override set nightly

# 6. 加 cargo 子命令(用 cargo install 装社区 crate)
cargo install cargo-watch      # 监听文件变化自动 rebuild
cargo install cargo-edit       # cargo add / cargo rm
cargo install cargo-flamegraph # 性能火焰图
cargo install cargo-audit      # 检查依赖漏洞
cargo install cargo-binstall   # 装预编译二进制(不用每次源码编译)

# 7. (推荐)配 cargo 国内镜像(可选,加速依赖下载)
mkdir -p ~/.cargo
cat >> ~/.cargo/config.toml << 'EOF'
[source.crates-io]
replace-with = "tuna"

[source.tuna]
registry = "sparse+https://mirrors.tuna.tsinghua.edu.cn/crates.io-index/"
EOF
```

### 第一个完整 Rust 项目

```bash
# 建项目
cd ~
cargo new guess_game
cd guess_game

# 项目结构
ls -la
# Cargo.toml  Cargo.lock  src/  .git/  .gitignore

# 编辑 src/main.rs
nvim src/main.rs
```

把 `src/main.rs` 改成下面这个完整的猜数字游戏(覆盖本篇学的所有内容):

```rust
// src/main.rs
// 一个简单的猜数字游戏,综合练习本篇学的所有内容

// 引入标准库的部分(release of use std::xxx 前缀)
use std::cmp::Ordering;          // 枚举:Less / Equal / Greater
use std::io;                     // 输入输出

// 一个常量(编译期求值)
const MAX_GUESSES: u32 = 7;

fn main() {
    println!("=== 猜数字游戏 ===");
    println!("我已经想好了一个 1-100 之间的整数");
    println!("你有 {MAX_GUESSES} 次机会");

    // 生成随机数(用标准库 + 一个外部 crate)
    // 假设我们暂时用伪随机(系统时间种子)
    let secret = generate_secret(1, 100);

    // 计数器(可变)
    let mut attempts = 0;

    // 主循环
    while attempts < MAX_GUESSES {
        attempts += 1;
        println!("\n第 {attempts}/{MAX_GUESSES} 次猜测,请输入:");

        // 读用户输入
        let guess = read_guess();
        let guess = match guess {
            Some(g) => g,
            None => {
                println!("请输入有效数字");
                continue;     // 重新循环,不算这次尝试
            }
        };

        // 用 match 处理三种比较结果
        match guess.cmp(&secret) {
            Ordering::Less => println!("太小了!"),
            Ordering::Greater => println!("太大了!"),
            Ordering::Equal => {
                println!("🎉 猜对了!用了 {attempts} 次");
                return;        // 提前退出 main
            }
        }
    }

    println!("\n次数用完!答案是 {secret}");
}

// 生成秘密数字(简化版:用系统时间做种子)
fn generate_secret(min: u32, max: u32) -> u32 {
    // 用系统时间的纳秒部分做"伪随机"
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("time went backwards")  // 实际不会发生
        .subsec_nanos();
    min + (now % (max - min + 1))
}

// 读用户输入,解析成 u32
fn read_guess() -> Option<u32> {
    let mut input = String::new();      // 创建空 String
    io::stdin()
        .read_line(&mut input)          // 读一行到 input(&mut 是可变引用,下一篇细讲)
        .expect("failed to read line");

    // 去除换行符,解析
    let input = input.trim();           // trim 返回 &str
    input.parse::<u32>().ok()           // parse 返回 Result, .ok() 转 Option
}
```

跑起来:

```bash
cargo run
# 输出:
#   Compiling guess_game v0.1.0
#    Finished dev [unoptimized + debuginfo] target(s)
#     Running `target/debug/guess_game`
# === 猜数字游戏 ===
# 我已经想好了一个 1-100 之间的整数
# 你有 7 次机会
#
# 第 1/7 次猜测,请输入:
# 50
# 太小了!
# ...
```

### 排错实战

```bash
# 故障 1: 编译报 "cannot find value `x` in this scope"
# 原因:变量没声明,或作用域不对(在 if 块里 let 出来的变量,外面看不到)

# 故障 2: cargo build 报 "error[E0596]: cannot borrow `x` as mutable"
# 原因:x 是 immutable,但你想改它。加 mut。
# 下一篇细讲 borrow

# 故障 3: 整数运算溢出 panic(debug 模式)
# 症状:'attempt to add with overflow'
# 解决:用 wrapping_add / checked_add / saturating_add 显式说明

# 故障 4: cargo build 卡住下载依赖
# 原因:网络问题,或镜像没配
# 解决:配 crates.io 镜像(上面有命令)
# 或离线模式:cargo build --offline

# 故障 5: rust-analyzer 不工作
# 检查:nvim/helix 里跑 :LspInfo,看是否连上
# 解决:rustup component add rust-analyzer rust-src

# 故障 6: "error: linker `cc` not found"
# 原因:没装 base-devel(缺 gcc)
# 解决:sudo pacman -S base-devel

# 故障 7: cargo run 报权限错误
# 原因:target/ 是 root 拥有(之前 sudo cargo run 过)
# 解决:sudo chown -R $USER:$USER target/
```

### Rust 编译器错误阅读

Rust 编译器错误**极其有用**。例:

```
error[E0384]: cannot assign twice to immutable variable `x`
 --> src/main.rs:3:5
  |
2 |     let x = 5;
  |         - first assignment to `x`
3 |     x = 6;
  |     ^^^^^ cannot assign twice to immutable variable

help: consider making `x` mutable
  |
2 |     let mut x = 5;
  |         +++

For more information about this error, try `rustc --explain E0384`.
```

读懂这个错误:

1. **错误码 `E0384`**:每个 Rust 错误都有码,可跑 `rustc --explain E0384` 看详细解释
2. **位置**:`src/main.rs:3:5` 是文件:行:列
3. **箭头标记**:rustc 用 `^` 标出问题位置
4. **建议**:`consider making x mutable` 直接给你修复方案
5. **链接**:错误码 E0384 在 https://doc.rust-lang.org/error_codes/E0384.html 有完整说明

[11-reading-rustc-errors.md](11-reading-rustc-errors.md) 专门讲怎么读这些错误。

## 9 · 延伸阅读(可选补充,非必需)

本仓库本地:
- [04-rust-from-scratch-2.md](04-rust-from-scratch-2.md) — 所有权(下一篇)
- [05-rust-from-scratch-3.md](05-rust-from-scratch-3.md) — struct / enum
- [06-rust-from-scratch-4.md](06-rust-from-scratch-4.md) — trait / 泛型
- [11-reading-rustc-errors.md](11-reading-rustc-errors.md) — 读编译器错误

外部稳定 URL:
- The Rust Book(本篇对应 Ch.1-3):https://doc.rust-lang.org/book/
- Rust by Example(代码示例驱动):https://doc.rust-lang.org/rust-by-example/
- Rust Reference(语言规范):https://doc.rust-lang.org/reference/
- std 文档:https://doc.rust-lang.org/std/
- Comprehensive Rust(Google):https://google.github.io/comprehensive-rust/
- rustlings(练习):https://github.com/rust-lang/rustlings
- Rust 错误码索引:https://doc.rust-lang.org/error_codes/

真实开源源码:
- Rust 标准库源码:https://github.com/rust-lang/rust/tree/master/library/std
- cargo 源码:https://github.com/rust-lang/cargo
- rustup 源码:https://github.com/rust-lang/rustup
