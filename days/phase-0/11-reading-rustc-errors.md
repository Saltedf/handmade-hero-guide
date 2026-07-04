
# 11 · 读懂 rustc 报错:E0xxx 错误码、借用 / 生命周期 / trait bound

> Rust 编译器的报错是它的招牌——比绝大多数语言都精准、有教育性。但只有在你**看得懂**的前提下,这个招牌才有用。这一篇把 Rust 最常见的报错类型(借用错误、生命周期错误、trait bound 错误、类型不匹配)逐个拆解,让你看到红色波浪线时不再慌。

## 0 · 为什么要有这一天

你写 Rust 的前 100 小时,大部分时间在跟编译器吵架。你会反复看到这些:

1. **"cannot borrow ... as mutable, as it is also borrowed as immutable"** —— 这英文你认识每个词,合起来不知道在说什么
2. **"does not live long enough"** —— 谁?谁不够长?
3. **"the trait bound `T: Default` is not satisfied"** —— trait bound 是什么?T 是什么?Default 是什么?
4. **"mismatched types: expected `u32`, found `i32`"** —— 我看代码就是 32 位整数啊,为啥不行?
5. **E0507、E0596、E0277** —— 这一堆 E0xxx 是什么鬼?

如果你不知道怎么读这些报错,你会:写一行 → 编译 → 红错 → 改一个字符 → 又红错 → 改回去 → 还是错 → 抓狂 → 放弃 Rust。

**学会读报错**是 Rust 学习的最大关卡。一旦突破,你写代码会进入"流":写一行 → 红错 → 一眼看懂 → 5 秒修好 → 继续。这就是 Rust 老手的日常——他们不"会 Rust",他们"会读 rustc"。

**心理锚点**:这一篇读完,你能:
- 看到 E0xxx 错误码,立刻知道错误类型(借用 / trait / 类型 / 语法)
- 看 5 段最常见报错,1 分钟说出原因 + 修法
- 知道 rust-analyzer 怎么把 rustc 报错变成编辑器内的红色波浪线
- 用 `cargo --explain` 看官方对某错误的解释

## 1 · 概念地图:rustc 报错的结构

一个典型的 rustc 报错:

```
error[E0382]: borrow of moved value: `s`
  --> src/main.rs:5:20
   |
2  |     let s = String::from("hi");
   |         - move occurs because `s` has type `String`,
   |           which does not implement the `Copy` trait
3  |     takes(s);
   |            - value moved here
4  |
5  |     println!("{}", s);
   |                    ^ value borrowed here after move
   |
   = note: this error originates in the macro `println`
```

拆解:

| 部分 | 含义 |
|---|---|
| `error` | 错误级别(error / warning) |
| `[E0382]` | 错误码(E = error,4 位数字) |
| `borrow of moved value: \`s\`` | 简短描述 |
| `src/main.rs:5:20` | 文件:行:列 |
| 下面的代码段 + `^` 下划线 | 精确指出哪行哪列 |
| `- move occurs because...` | 解释**为什么**发生 |
| `= note: ...` | 额外补充 |

**关键**:rustc 报错的核心是**告诉你为什么**——不只是说"错了",而是给你完整因果链。学会读这条链,大部分错误自动消失。

### 错误码分类

- E0xxx - 普通编译错误(类型 / 借用 / trait / 语法)
- E0Wxx - warning(警告,不影响编译)
- W0xxx - lint 警告

`rustc --explain E0382` 会打印这段错误的完整解释 + 多个示例。

## 2 · 心智模型

### 类比:rustc 是"严格的质检员"

想象一个工厂,产品出厂前要过质检。大多数工厂的质检员是宽松的——发现小毛病不管,放行。出问题再说。

Rust 的质检员(rustc)是**严格且话痨**的——发现一个螺丝松了,立刻停线,而且给你 5 段说明:
1. **哪儿松了**(精确到螺丝坐标)
2. **什么时候松的**(它什么时候被拧的)
3. **为什么松**(因为没加锁紧垫片)
4. **要怎么修**(加个 Copy trait,或用 borrow)
5. **类似的螺丝也松了吗**(类似的代码也会触发)

### 三大错误根因

Rust 编译错误 90% 集中在三个领域:

1. **所有权 / 借用(ownership / borrow)** —— "你借了它又改了它" / "它已经搬走了"
2. **生命周期(lifetime)** —— "我引用的东西活得没我久"
3. **trait bound** —— "我没保证 T 能做这件事"

剩下 10% 是类型不匹配、语法错误、找不到符号——这些 rustc 都能精确定位。

## 3 · 四域深入

### 3.1 · 借用 / 所有权错误

#### E0382: use of moved value

最经典的 Rust 错误。

```rust
fn takes(s: String) { /* ... */ }

fn main() {
    let s = String::from("hi");
    takes(s);
    println!("{}", s);   // 错!
}
```

报错:
```
error[E0382]: borrow of moved value: `s`
  --> src/main.rs:5:20
   |
2  |     let s = String::from("hi");
   |         - move occurs because `s` has type `String`,
   |           which does not implement the `Copy` trait
3  |     takes(s);
   |            - value moved here
5  |     println!("{}", s);
   |                    ^ value borrowed here after move
```

**怎么读**:
1. `E0382` 是错误码 → `rustc --explain E0382` 看完整说明
2. 标题:"使用了已经被搬走的值 `s`"
3. 行 2:变量 `s` 声明,因为类型是 `String`(没实现 Copy),它会被 move
4. 行 3:`s` 被 move 进 `takes` 函数——这一刻 `s` 已经不属于 main 了
5. 行 5:你还想用 `s`?它已经搬走了

**修法**:三种,选一种:

```rust
// 方法 1:借给它(takes 改成 &String)
fn takes(s: &String) { }
takes(&s);

// 方法 2:让它还回来(takes 返回 String)
fn takes(s: String) -> String { s }
s = takes(s);

// 方法 3:克隆一份
takes(s.clone());
```

#### E0502 / E0500: 同时借用可变和不可变

```rust
let mut v = vec![1, 2, 3];
let first = &v[0];        // 不可变借用
v.push(4);                // 可变借用!错!
println!("{}", first);
```

报错:
```
error[E0502]: cannot borrow `v` as mutable because it is also borrowed as immutable
  --> src/main.rs:3:5
   |
2  |     let first = &v[0];
   |                  - immutable borrow occurs here
3  |     v.push(4);
   |     ^^^^^^^^^ mutable borrow occurs here
4  |     println!("{}", first);
   |                        ------ immutable borrow later used here
```

**怎么读**:
- 行 2:借了 `v` 的不可变引用 `first`
- 行 3:又想可变借用 `v` 调用 `push`
- 行 4:行 2 的不可变借用在这里还在用

Rust 规则:**同一时间,要么有多个不可变借用,要么有一个可变借用,不能同时**。原因:`push` 可能 realloc,让 `first` 指向无效内存。

**修法**:让不可变借用先结束。

```rust
let mut v = vec![1, 2, 3];
{
    let first = &v[0];
    println!("{}", first);
}   // first 在这里结束生命周期
v.push(4);   // OK
```

或重排代码,让 `first` 的最后使用在 `push` 之前。Rust 有 NLL(Non-Lexical Lifetimes)优化,允许:

```rust
let mut v = vec![1, 2, 3];
let first = &v[0];
println!("{}", first);   // first 最后一次用在这里
v.push(4);               // NLL 知道 first 不再用了,OK
```

#### E0596: cannot borrow as mutable

```rust
let v = vec![1, 2, 3];    // 注意没 mut
v.push(4);                 // 错!
```

报错:
```
error[E0596]: cannot borrow `v` as mutable, as it is not declared as mutable
  --> src/main.rs:2:5
   |
1  |     let v = vec![1, 2, 3];
   |         - help: consider changing this to be mutable: `mut v`
2  |     v.push(4);
   |     ^^^^^^^^^ cannot borrow as mutable
```

**怎么读**:rustc 直接告诉你修法——加 `mut`。这是它最贴心的一面。

#### E0507: cannot move out of borrow

```rust
fn f(v: &Vec<i32>) -> i32 {
    v[0]    // 错!这是 Copy,但写法不对
}
```

实际:`v[0]` 是 `i32`(Copy),没问题。改成:

```rust
fn f(v: &Vec<String>) -> String {
    v[0]    // 错!String 不是 Copy,不能 move 出借用
}
```

报错:
```
error[E0507]: cannot move out of index of `Vec<String>`
  --> src/main.rs:2:5
   |
2  |     v[0]
   |     ^^^^ move occurs because value has type `String`,
   |           which does not implement the `Copy` trait
```

**修法**:
```rust
v[0].clone()         // 克隆
(&v[0])              // 返回引用,改签名
```

### 3.2 · 生命周期错误

#### E0106: missing lifetime

```rust
fn longest(x: &str, y: &str) -> &str {  // 错!
    if x.len() > y.len() { x } else { y }
}
```

报错:
```
error[E0106]: missing lifetime specifier
  --> src/main.rs:1:33
   |
1  | fn longest(x: &str, y: &str) -> &str {
   |           ----      ----      ^ expected named lifetime parameter
   |
   = help: this function's return type contains a borrowed value,
           but the signature does not say whether it is borrowed from `x` or `y`
```

**怎么读**:返回的引用到底来自 `x` 还是 `y`?编译器不知道,所以不知道返回值能活多久。

**修法**:

```rust
fn longest<'a>(x: &'a str, y: &'a str) -> &'a str {
    if x.len() > y.len() { x } else { y }
}
```

`'a` 是个生命周期参数。它告诉编译器:**返回值的生命周期 = x 和 y 中较短的那个**。这样调用方知道:返回值的存活不能超过 x 和 y 中任一个。

#### E0597: borrowed value does not live long enough

```rust
let r;
{
    let x = 5;
    r = &x;   // 错!
}
println!("{}", r);
```

报错:
```
error[E0597]: `x` does not live long enough
  --> src/main.rs:4:13
   |
3  |     let x = 5;
   |         - binding `x` declared here
4  |     r = &x;
   |             ^^ borrowed value does not live long enough
5  | }
   | - `x` dropped here while still borrowed
6  | println!("{}", r);
   |                 - borrow later used here
```

**怎么读**:x 在第 5 行(大括号结束)被销毁,但 r 还在第 6 行用它。这就是悬垂引用(dangling pointer)——Rust 在编译期拒绝。

**修法**:让 x 活得久一些,或不用引用(让 r 拿到 x 的拥有权)。

```rust
let r;
{
    let x = 5;
    r = x;    // 复制(i32 是 Copy)
}
println!("{}", r);   // OK
```

#### E0621: lifetime mismatch

```rust
fn f<'a, 'b>(x: &'a str, y: &'b str) -> &'a str {
    y   // 错!说好返回 'a,实际返回 'b
}
```

报错:
```
error[E0621: lifetime mismatch
```

**修法**:改成 `y: &'a str`(参数生命周期对齐),或返回 `x`。

### 3.3 · trait bound 错误

#### E0277: the trait bound is not satisfied

```rust
struct MyType;

fn print_it<T: std::fmt::Display>(x: T) {
    println!("{}", x);
}

fn main() {
    print_it(MyType);   // 错!
}
```

报错:
```
error[E0277]: `MyType` doesn't implement `std::fmt::Display`
  --> src/main.rs:7:15
   |
3  | fn print_it<T: std::fmt::Display>(x: T) {
   |              - required by this bound in `print_it`
...
7  |     print_it(MyType);
   |     ^^^^^^^^^^^^^^^^ required by a bound in `print_it`
   |
   = help: the following other types implement trait `Display`:
              i32, f32, str, String, ...
```

**怎么读**:
- 标题:"`MyType` 没实现 `Display`"
- 行 3:`print_it` 要求 T 实现 Display
- 行 7:你传的 MyType 不满足
- help:列出实际实现了 Display 的类型

**修法**:给 MyType 实现 Display。

```rust
impl std::fmt::Display for MyType {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "MyType")
    }
}
```

#### E0501 / E0599: method not found

```rust
let s = "hi";
s.push_str("!");   // 错!
```

报错:
```
error[E0599]: no method named `push_str` found for reference `&'static str` in the current scope
```

**怎么读**:`&str` 是字符串切片,不可变。`push_str` 是 `String` 的方法。要用就先 `String::from(s)` 转换。

#### E0308: mismatched types

```rust
let x: i32 = "hello";   // 错!
```

报错:
```
error[E0308]: mismatched types
  --> src/main.rs:1:14
   |
1  | let x: i32 = "hello";
   |         ---   ^^^^^^^ expected `i32`, found `&str`
   |         |
   |         expected due to this
```

**怎么读**:类型对不上。rustc 告诉你"期望 i32,实际是 &str",精确到点。

#### E0277 的高级版本:多个 bound

```rust
fn f<T: Clone + Default + Debug>(x: T) { }
```

如果不满足任何一个,T 会报错。rustc 会告诉你**具体哪个**没满足,不是一次说三个。

#### Where clause 和 trait bound

```rust
// 等价的两种写法
fn f<T: Clone + Default>(x: T) -> T { x.clone() }

fn f<T>(x: T) -> T
where
    T: Clone + Default,
{
    x.clone()
}
```

`where` 子句更可读,适合多个 bound。

### 3.4 · Rust 生态:Lints 和 clippy

#### clippy:rustc 之上的 lint

clippy 是 Rust 官方 lint 工具,比 rustc 更严格。

```bash
rustup component add clippy
cargo clippy
```

clippy 报的不是错误,是建议——你的代码可以编译,但可以更好。例如:

```rust
let v = vec![1, 2, 3];
for i in 0..v.len() {
    println!("{}", v[i]);
}
```

clippy:
```
warning: the loop variable `i` is only used to index `v`
  --> src/main.rs:3:14
   |
3  |     for i in 0..v.len() {
   |              ^^^^^^^^^^
   |
   = help: for further information visit https://rust-lang.github.io/rust-clippy/master/index.html#needless_range_loop
help: consider using an iterator
   |
3  |     for (i, item) in v.iter().enumerate() {
```

clippy 有 600+ 个 lint,分四组:
- `correctness` —— 正确性问题(默认 warn/error)
- `suspicious` —— 可疑代码
- `style` —— 风格建议
- `complexity` —— 复杂度
- `perf` —— 性能
- `pedantic` —— 挑剔(默认不开)
- `nursery` —— 实验性

#### 控制单个 lint

```rust
#[allow(clippy::needless_range_loop)]
fn f() { ... }

#[deny(unsafe_code)]    // 项目级禁止 unsafe
mod foo { }
```

#### rustfmt

```bash
cargo fmt    # 自动格式化
cargo fmt -- --check   # CI 检查
```

格式规则不可配置太多——这是 Rust 哲学(避免风格争论)。

## 4 · 认知地图

### 4.1 上级

- **类型系统(Type System)** — Rust 类型系统的"严格"源自所有权 + 生命周期 + trait
- **编译时检查(Static Analysis)** — 编译期消除整类错误(空指针、悬垂引用、数据竞争)
- **诊断信息(Diagnostics)** — 编译器/IDE 给开发者的反馈质量,是 DX 的核心

### 4.2 同级

| 错误类别 | 错误码 | 典型原因 |
|---|---|---|
| 所有权 / 借用 | E0382, E0502, E0507, E0596 | 用了 moved 值 / 同时 mut 和 immut borrow |
| 生命周期 | E0106, E0597, E0621 | 缺 lifetime / 借用不够长 / lifetime mismatch |
| trait bound | E0277, E0501 | trait 没实现 |
| 类型 | E0308, E0271 | 类型不匹配 |
| 语法 | E0425, E0433 | 找不到变量 / 找不到类型 |
| 宏 | E0433, E0578 | 宏展开错误 |

### 4.3 下级

- **错误码系统(E0xxx)** — rustc 每个错误有唯一码,`rustc --explain` 看详解
- **生命周期参数(`'a`)** — 描述引用间的关系
- **trait bound(`T: Trait`)** — 对泛型参数的约束
- **Salsa**(rust-analyzer 用的增量计算框架) — 决定 LSP 报错速度

## 5 · 对照与变奏

### Rust vs C++ 报错

| | Rust | C++ (gcc) |
|---|---|---|
| 借用错误 | E0502,精确指出哪两处冲突 | 没有(运行时崩溃) |
| 类型不匹配 | E0308,告诉你期望/实际 | "no known conversion",长篇 template error |
| 模板 / 泛型 | trait bound 错(E0277),清晰 | template substitution failure,几百行 |
| 教育性 | 解释为什么 + 怎么修 | 通常只说"不行" |

C++ 模板错误之所以臭名昭著,是因为没有 trait bound 机制——编译器要把所有重载试一遍,失败信息爆炸。Rust 的 trait 是显式声明,错误精准定位。

### Rust vs Python 报错

| | Rust | Python |
|---|---|---|
| 时机 | 编译期 | 运行时 |
| 类型错误 | E0308 编译失败 | TypeError 跑到那行才报 |
| 拼写错误 | 编译失败 | AttributeError 运行时 |

Rust 把"运行时可能崩"的错误提前到编译期——这就是 Rust 学习曲线陡的根本原因,也是 Rust 安全的根本保证。

### rustc vs rust-analyzer 报错

| | rustc | rust-analyzer |
|---|---|---|
| 触发 | cargo build | 每次按键 |
| 速度 | 几秒 - 几十秒 | 几十 ms |
| 完整性 | 完整(权威) | 偶尔漏(尤其复杂宏 / 复杂 lifetime) |
| 用途 | CI / 最终验证 | 实时反馈 |

rust-analyzer 用 flycheck(后台 cargo check)给真实 rustc 错误,加上自己的快速预测。所以 helix/nvim 里看到的错误可能延迟几百 ms。

## 6 · 关联 Day

- **铺垫**:[03-rust-from-scratch-1.md](03-rust-from-scratch-1.md)、[04-rust-from-scratch-2.md](04-rust-from-scratch-2.md)(Rust 基础,所有权 / 借用)
- **当天**:本篇
- **后续**:
  - [09-editor-toolchain.md](09-editor-toolchain.md)(rust-analyzer 集成)
  - Phase 1 Day 001-005(写第一个 winit 程序,会遇到大量 E0xxx)
  - Phase 4 Day 112+(unsafe FFI,会看到不同类错误)

## 7 · 变式训练

### Lv1 · 概念辨析

**题**:下面 4 段代码各自会报什么错误码?为什么?

```rust
// (a)
let s = String::from("a");
let t = s;
println!("{}", s);

// (b)
fn f(x: &str) -> &str { x }
// 没加 lifetime

// (c)
struct A;
fn print<T: Display>(x: T) {}
print(A);

// (d)
let x: i32 = "5";
```

**参考解答**:

- **(a) E0382** —— `t = s` 把 `s` move 了,后面用 `s` 报"borrow of moved value"。修法:`let t = s.clone();` 或 `let t = &s;`
- **(b) 不报错** —— 单参数引用,生命周期推断为同名 `'a`,返回值生命周期 = x 的。这其实是 OK 的(rustc 推断得出)。新手以为这里要加 lifetime,实际只在多参数时需要
- **(c) E0277** —— `A` 没实现 Display。修法:`impl Display for A { ... }`
- **(d) E0308** —— 类型不匹配。修法:`let x: i32 = "5".parse().unwrap();`

### Lv2 · 动手实践

**题**:下面代码故意写了 6 个错误,每个对应不同错误码。用 `cargo build` 看报错,记下每个错误码 + 修法,然后修复让代码编译通过。

```rust
use std::fmt::Display;

struct A;
// (1) 这里需要给 A 实现 Display,但故意没实现

fn print_it<T: Display>(x: T) { println!("{}", x); }

fn longest(x: &str, y: &str) -> &str {   // (2) 缺 lifetime
    if x.len() > y.len() { x } else { y }
}

fn take(v: String) {}

fn main() {
    let s = String::from("hi");
    take(s);
    println!("{}", s);          // (3) use of moved value

    let mut vec = vec![1, 2, 3];
    let first = &vec[0];
    vec.push(4);                // (4) borrow conflict
    println!("{}", first);

    let n: i32 = "5";           // (5) type mismatch

    print_it(A);                // (6) Display not implemented
}
```

完成标准:`cargo build` 通过(代码逻辑跑得动),每个错误写出代码注释。

**参考解答**(逐一修):

```rust
use std::fmt::{Display, Formatter, Result};

// (1) 给 A 实现 Display
struct A;
impl Display for A {
    fn fmt(&self, f: &mut Formatter) -> Result {
        write!(f, "A")
    }
}

fn print_it<T: Display>(x: T) { println!("{}", x); }

// (2) 加 lifetime
fn longest<'a>(x: &'a str, y: &'a str) -> &'a str {
    if x.len() > y.len() { x } else { y }
}

fn take(_v: String) {}

fn main() {
    // (3) clone 或 borrow
    let s = String::from("hi");
    take(s.clone());
    println!("{}", s);

    // (4) 让 first 先用完
    let mut vec = vec![1, 2, 3];
    let first = &vec[0];
    println!("{}", first);
    vec.push(4);

    // (5) parse
    let n: i32 = "5".parse().unwrap();

    print_it(A);
}
```

### Lv3 · 迁移设计

**题**:你写一个泛型函数 `fn sum<T>(items: &[T]) -> T`,想对 `&[i32]` / `&[f64]` 都工作。会报什么错误?怎么修(写出完整可编译版)?

**提示**:
- `+` 操作需要 `Add` trait
- 0 需要类型有 `Default` 或 `Zero` trait(num_traits crate)
- 试试 `T: std::ops::Add<Output = T> + Default + Copy`

### Lv4 · 开源贡献

**题**:Rust 编译器本身的错误信息也在持续改进。GitHub: https://github.com/rust-lang/rust

1. clone 它,看 `compiler/rustc_error_codes/` 目录,每个 E0xxx 错误码有一个 md 文件
2. 找一个错误码的 md(如 `E0507.md`),看是否:
   - 例子过时(用了老版本 Rust 语法)
   - 解释不清(没说"为什么")
   - 缺少常见场景
3. **可能的贡献**:改进某个错误码的 md 文件,提 PR
4. fork → branch → 改 → PR(完整流程见 [12-opensource-pr-flow.md](12-opensource-pr-flow.md))

写下 PR 描述(改的错误码 / 文件 / 动机 / 验证)。

## 8 · Rust / Arch 落地代码

### 完整示例:故意触发常见错误 + 修复

```rust
// src/main.rs —— 错误演示
use std::fmt::Display;
use std::ops::Add;

// 1. lifetime 函数
fn longest<'a>(x: &'a str, y: &'a str) -> &'a str {
    if x.len() >= y.len() { x } else { y }
}

// 2. trait bound + where 子句
fn sum_all<T>(items: &[T]) -> T
where
    T: Add<Output = T> + Copy + Default,
{
    let mut total = T::default();
    for &item in items {
        total = total + item;
    }
    total
}

// 3. 自定义类型 + Display
struct Point {
    x: f64,
    y: f64,
}

impl Display for Point {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        write!(f, "({}, {})", self.x, self.y)
    }
}

// 4. 借用规则演示
fn first_two(v: &Vec<i32>) -> Option<(i32, i32)> {
    if v.len() >= 2 {
        Some((v[0], v[1]))   // 两次不可变借用,允许
    } else {
        None
    }
}

fn main() {
    // lifetime
    let s1 = String::from("hello");
    let s2 = String::from("hi");
    let result = longest(s1.as_str(), s2.as_str());
    println!("longest: {}", result);

    // trait bound
    let nums = vec![1, 2, 3, 4, 5];
    println!("sum: {}", sum_all(&nums));   // 15

    let floats = vec![1.5, 2.5, 3.0];
    println!("float sum: {}", sum_all(&floats));   // 7.0

    // Display
    let p = Point { x: 1.0, y: 2.0 };
    println!("point: {}", p);

    // 借用
    let v = vec![10, 20, 30];
    if let Some((a, b)) = first_two(&v) {
        println!("first two: {} {}", a, b);
    }
}
```

**每段解释**:
- `fn longest<'a>` —— `'a` 是生命周期参数,声明"返回值活得和 x、y 中较短的一样长"
- `where T: Add<Output = T> + Copy + Default` —— 三个约束:`Add`(可加,且输出还是 T)、`Copy`(可复制,用 `for &item in items`)、`Default`(能初始化为 0)
- `T::default()` —— 调用 trait 方法,等价于 `Default::default::<T>()`,即"零值"
- `impl Display for Point` —— 给 Point 实现 Display,这样 `println!("{}", p)` 能工作
- `for &item in items` —— items 是 `&[T]`,迭代出 `&T`,我们用 `&item` 模式匹配解引用,得到 `T`(需要 T: Copy)

### Arch 命令:看错误码详解

```bash
# 1. 看某错误码的完整解释
rustc --explain E0382 | less
# 这个会打印完整的诊断说明 + 多个例子

# 2. 列出所有错误码
# 实际:Rust 错误码索引在 rustc 仓库:
# https://github.com/rust-lang/rust/tree/master/compiler/rustc_error_codes

# 3. 在线版本(可搜索)
xdg-open https://doc.rust-lang.org/error_codes/E0382.html

# 4. 看 clippy 提示详解
# 每个 clippy warning 都有 URL:
# https://rust-lang.github.io/rust-clippy/master/index.html#needless_range_loop

# 5. 项目里跑诊断
cargo check --message-format=short
# 短格式,适合脚本处理

cargo check --message-format=json
# JSON 格式,IDE / CI 用

# 6. 让 rust-analyzer 显示完整错误(在 helix 里)
# 文件 → :config-open → 加 [editor.lsp] display-messages = true

# 7. 看一个 crate 的所有 warning
RUSTFLAGS="-W unused" cargo build
# 加 -W unused 把 unused 设成 warning;加 -D warnings 把所有 warning 变错误(CI 用)
```

### Troubleshooting

- **报错信息里中文看不懂**:rustc 报错全是英文,先熟悉几个术语:borrow(借用)/ mutable(可变)/ immutable(不可变)/ lifetime(生命周期)/ trait bound(trait 约束)
- **报错指向宏(println!)**:宏展开后代码 rustc 才看,定位到宏调用位置可能误导。看 `note: this error originates in the macro ...` 找到真凶
- **报错说"expected lifetime, found concrete type"**:函数返回类型用 `&T` 但没标 `'a`,加 `<'a>` 和 `&'a T`
- **trait bound 多到看不懂**:rustc 会列每个不满足的,逐个解。从第一个开始修

## 9 · 延伸阅读(可选补充,非必需)

本仓库本地:
- [03-rust-from-scratch-1.md](03-rust-from-scratch-1.md)、[04-rust-from-scratch-2.md](04-rust-from-scratch-2.md) — Rust 基础
- [09-editor-toolchain.md](09-editor-toolchain.md) — rust-analyzer
- [phase-0/README.md](README.md)

外部稳定 URL:
- Rust 错误码索引:https://doc.rust-lang.org/error_codes/
- Rust 编译器 book:https://rustc-dev-guide.rust-lang.org/
- clippy lint 列表:https://rust-lang.github.io/rust-clippy/master/
- Rust Reference(Lifetime 章节):https://doc.rust-lang.org/reference/lifetimes.html

真实开源源码:
- rustc 错误码定义:https://github.com/rust-lang/rust/tree/master/compiler/rustc_error_codes
- rustc 诊断代码:https://github.com/rust-lang/rust/tree/master/compiler/rustc_errors
