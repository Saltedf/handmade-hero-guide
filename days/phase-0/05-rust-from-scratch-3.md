---
article: 05
phase: 0
title: "Rust 从零(3):struct / enum / pattern / 错误处理 / 集合"
type: setup
difficulty: 4
duration: "3-4h"
domains: [rust]
prereqs: ["04-rust-from-scratch-2"]
---

# 05 · Rust 从零(3):struct / enum / pattern / 错误处理 / 集合

> 上一篇你啃下了所有权。这一篇是把 Rust "组织代码"的工具讲完:struct(把数据组织起来)、enum(把可能性组织起来)、pattern matching(把分支表达优雅)、错误处理(Rust 没异常,用 Result)、集合(Vec/HashMap/String)。学完你能写出 200 行的 Rust 程序,处理真实业务逻辑。

## 0 · 为什么要有这一天

你已经能写"变量+控制流"的小程序。但真实代码不是几行 `let` 和 `if`,是:

1. **数据有结构**:游戏里的"角色"有 HP、位置、名字、装备。你不能用 5 个独立变量记,要用 **struct** 把它们组织起来
2. **状态有分支**:游戏状态可能是 Menu / Playing / Paused。你要么用整数枚举(C 的 `enum` 是数字),要么用 Rust 的 **enum**(每个变体可以带数据,强大得多)
3. **代码要可读**:`if state == 1 { ... } else if state == 2 { ... }` 是垃圾,用 **pattern matching** 一目了然
4. **错误是常态**:文件读不到、网络断、JSON 解析错。Java 抛异常,Python 抛异常,Rust **没有异常**,用 `Result<T, E>` 类型显式处理
5. **数据多了要容器**:1000 个角色用 1000 个变量?用 `Vec`。按名字找角色?用 `HashMap`

这些不是"高级特性",是日常工具。Casey 在 HH Day 26 就开始定义 struct 组织游戏状态;Phase 2 的实体系统全是 struct + enum。

**心理锚点**:读完这一篇,你能:
- 定义 struct,带方法(impl block)
- 定义 enum,带数据的变体(algebraic data type)
- 用 match 表达所有分支,包括 if let / while let
- 解释 Result 和 Option,用 `?` 简化错误传播
- 用 Vec / HashMap / String 处理集合数据
- 写出 200 行可维护的 Rust 代码

## 1 · 概念地图

| 词 | 是什么 | 类比 |
|---|---|---|
| **struct** | 把多个字段打包成一个类型 | C 的 struct,Go 的 struct,Python 的 class(只数据) |
| **impl block** | 给 struct 实现方法 | Python 的 class methods |
| **tuple struct** | 字段无名的 struct | `struct Color(i32, i32, i32)` |
| **unit struct** | 无字段的 struct | `struct Marker;`,用作类型标记 |
| **enum** | 类型,有若干"变体"之一 | C 的 enum(但 Rust enum 变体可带数据) |
| **algebraic data type(ADT)** | enum 的本质:和类型(sum type) | "或"的数学表达 |
| **pattern matching** | 用 `match` 检查 enum 变体,绑定内部数据 | 强化的 switch |
| **Option<T>** | std 内置 enum,表示"有值 / 无值" | 替代 null |
| **Result<T, E>** | std 内置 enum,表示"成功 / 失败" | 替代异常 |
| **?** 操作符 | 简化错误传播 | `match { Ok(v) => v, Err(e) => return Err(e) }` |
| **Vec<T>** | 动态数组,堆分配 | C++ vector,Python list |
| **HashMap<K,V>** | 哈希表 | C++ unordered_map,Python dict |
| **String** | 拥有所有权的可变字符串 | C++ string,Python str |
| **trait** | 接口(下一篇深入) | Java interface,Go interface,Haskell typeclass |

## 2 · 心智模型

### 费曼类比:struct 是档案,enum 是清单

**struct 是档案柜**:你想描述"一个学生",他/她有姓名、年龄、班级。你建一个档案:

```
学生档案:
  姓名: 张三
  年龄: 18
  班级: 高三(2)班
```

这就是 struct。每个字段有名字(便于阅读)和类型(便于编译器检查)。

**enum 是清单 / 单选题**:

```
学生的当前状态(只能选一个):
  □ 在校
  □ 请假(带:请假原因)
  □ 退学(带:退学日期)
```

这就是 enum。它的特点是"**只能选一个**变体",而且**每个变体可以带不同的数据**(请假带原因字符串,退学带日期)。这种能力 C 的 enum 没有——C 的 enum 只是整数常量。Rust 的 enum 是**和类型(sum type)**,数学上叫"代数数据类型"。

### struct 详解

```rust
// 命名字段 struct
struct Player {
    name: String,
    hp: i32,
    position: (f32, f32),
}

// 元组 struct(字段无名)
struct Color(u8, u8, u8);

// 单元 struct(无字段,用作类型标记)
struct EntityManager;

fn main() {
    // 构造
    let p = Player {
        name: String::from("Hero"),
        hp: 100,
        position: (0.0, 0.0),
    };

    // 访问字段
    println!("{} has {} hp", p.name, p.hp);

    // 字段简写(变量名和字段名一致时)
    let name = String::from("Hero2");
    let p2 = Player { name, hp: 100, position: (0.0, 0.0) };

    // 更新语法(用其他 struct 的剩余字段)
    let p3 = Player { name: String::from("Enemy"), ..p2 };
    // p3.hp == p2.hp == 100,p3.position == p2.position

    // tuple struct
    let red = Color(255, 0, 0);
    println!("R={}, G={}, B={}", red.0, red.1, red.2);

    // 单元 struct
    let _manager = EntityManager;
}
```

**struct 默认不可变**(整个 struct 都不可变,不能改某个字段):

```rust
let p = Player { name: "x".into(), hp: 100, position: (0.0, 0.0) };
// p.hp = 90;  // 错
let mut p = Player { name: "x".into(), hp: 100, position: (0.0, 0.0) };
p.hp = 90;     // OK,因为 p 是 mut
```

**注意 mut 是 struct 级别的**——不能"只让 hp 可变,其他不变"。如果要,用 `Cell` / `RefCell`(第 6 篇讲)。

### 方法:`impl` block

```rust
struct Player {
    name: String,
    hp: i32,
    max_hp: i32,
}

impl Player {
    // 关联函数(类似"静态方法"):无 self 参数,通过 Player::new 调
    fn new(name: &str, hp: i32) -> Player {
        Player {
            name: name.to_string(),
            hp,
            max_hp: hp,
        }
    }

    // 方法(不可变借用 self)
    fn is_alive(&self) -> bool {
        self.hp > 0
    }

    // 方法(可变借用 self)
    fn take_damage(&mut self, amount: i32) {
        self.hp -= amount;
        if self.hp < 0 { self.hp = 0; }
    }

    // 方法(获取所有权,较少见)
    fn into_name(self) -> String {
        self.name
    }
}

fn main() {
    let mut p = Player::new("Hero", 100);  // 关联函数用 ::
    p.take_damage(30);                       // 方法用 .
    println!("{} alive: {}, hp: {}", p.name, p.is_alive(), p.hp);
}
```

`self` 的几种形式:

| 形式 | 含义 | 类似 |
|---|---|---|
| `&self` | 不可变借用 | C++ `const this` |
| `&mut self` | 可变借用 | C++ `this` |
| `self`(值) | 获取所有权 | C++ by-value,调用者失去变量 |
| `self: Box<Self>` | 拿 Box(罕见) | C++ unique_ptr |

绝大多数方法用 `&self` 或 `&mut self`。

### enum:Rust 的杀手锏之一

```rust
// 简单 enum(C 风格,变体无数据)
enum Direction {
    Up,
    Down,
    Left,
    Right,
}

// 变体带数据(这是 Rust enum 比 C enum 强的地方)
enum Message {
    Quit,                          // 无数据
    Move { x: i32, y: i32 },       // 命名字段(像 struct)
    Write(String),                 // 一个值
    ChangeColor(i32, i32, i32),    // 多个值(像 tuple struct)
}

// 经典:Option<T>
enum Option<T> {
    Some(T),
    None,
}

// 经典:Result<T, E>
enum Result<T, E> {
    Ok(T),
    Err(E),
}

fn main() {
    let dir = Direction::Up;
    let msg = Message::Move { x: 10, y: 20 };
    let maybe: Option<i32> = Some(5);
    let result: Result<i32, String> = Ok(42);
}
```

为什么 Rust enum 比 C enum 强:C enum 只是 `int` 常量(`enum Color { RED, GREEN, BLUE }` 就是 0, 1, 2)。Rust enum 的每个变体可以带**不同类型的数据**。这让 Rust 表达力接近 Haskell。

**enum 在内存里怎么存**:Rust enum 用一个 tag(整数,标识是哪个变体)+ 足够容纳最大变体的空间。例:

```rust
enum Foo {
    A,                // tag 0,无数据
    B(i32),            // tag 1 + 4 字节
    C(f64, String),   // tag 2 + 8 + 24 字节
}
```

`Foo` 的大小 = tag(可能 1 字节)+ padding + max(0, 4, 8+24) = ~32 字节(对齐填充)。

### pattern matching:match / if let / while let

```rust
enum Coin {
    Penny,
    Nickel,
    Dime,
    Quarter,
}

fn value_in_cents(coin: Coin) -> u8 {
    match coin {
        Coin::Penny => 1,
        Coin::Nickel => 5,
        Coin::Dime => 10,
        Coin::Quarter => 25,
    }
}
```

**绑定变体里的数据**:

```rust
fn process(msg: Message) {
    match msg {
        Message::Quit => println!("quit"),
        Message::Move { x, y } => println!("move to {}, {}", x, y),
        Message::Write(text) => println!("write: {}", text),
        Message::ChangeColor(r, g, b) => println!("color: {}, {}, {}", r, g, b),
    }
}
```

**穷尽性(exhaustiveness)**:match 必须覆盖所有变体。漏了一个编译错。这是 Rust 的安全网——你加了一个新变体,编译器会强制你在所有 match 处处理它。

**通配符 `_`**:

```rust
match dir {
    Direction::Up => println!("up"),
    _ => println!("other"),     // 其他都用这个分支
}
```

**`Option` 的 match**:

```rust
fn double(maybe: Option<i32>) -> Option<i32> {
    match maybe {
        Some(n) => Some(n * 2),
        None => None,
    }
}
```

**`if let`(简化 match)**:

```rust
let maybe = Some(5);

// 用 match
match maybe {
    Some(n) => println!("got {}", n),
    _ => (),
}

// 用 if let,只关心一种情况
if let Some(n) = maybe {
    println!("got {}", n);
}
```

`if let` 用于"我只关心一种情况,其他忽略"。但**失去穷尽性检查**——慎用。

**`while let`**:

```rust
let mut iter = vec![1, 2, 3].into_iter();
while let Some(n) = iter.next() {
    println!("{}", n);
}
// 循环到 iter.next() 返回 None
```

**多模式 + 范围 + 守卫**:

```rust
match x {
    1 | 2 => println!("one or two"),       // 多模式
    3..=9 => println!("single digit"),     // 范围
    n if n % 2 == 0 => println!("even: {}", n),   // 守卫(if)
    _ => println!("other"),
}
```

### Option<T>:Rust 没有 null

很多语言(C, Java, Python)用 `null` / `None` / `nil` 表示"无值"。问题:`null` 是任何类型的值,你不能从类型看出某变量是否可能为 null,导致 `NullPointerException` 满天飞。

Rust 没有空值,用 `Option<T>` 显式表达"可能有值":

```rust
fn find_user(id: u32) -> Option<String> {
    if id == 1 {
        Some(String::from("admin"))
    } else {
        None
    }
}

fn main() {
    match find_user(1) {
        Some(name) => println!("found: {}", name),
        None => println!("not found"),
    }

    // 简便方法
    let name = find_user(2).unwrap_or_else(|| String::from("anonymous"));
    // unwrap_or_else:None 时用闭包构造默认值
}
```

Option 的常用方法:
- `unwrap()`:有值返回,无值 panic
- `expect("msg")`:同上,但 panic 信息带 msg
- `unwrap_or(default)`:无值时返回 default
- `unwrap_or_else(closure)`:无值时调闭包
- `map(f)`:Some 时变换, None 时返回 None
- `and_then(f)`:flatMap
- `is_some() / is_none()`:布尔判断

**记住**:`unwrap()` 在生产代码里慎用,出问题会 panic 崩溃。用 `?` 或 match / 上述方法。

### Result<T, E>:Rust 没异常

很多语言用 try / catch 异常。问题:
- 异常"暗中"传播,你不知道哪个函数可能抛
- 异常类型多,catch 容易漏
- 性能:抛异常要 stack unwinding

Rust 用 `Result<T, E>`:

```rust
use std::fs::File;
use std::io::Read;

fn read_username() -> Result<String, std::io::Error> {
    let mut file = File::open("username.txt")?;  // ? 操作符
    let mut contents = String::new();
    file.read_to_string(&mut contents)?;
    Ok(contents.trim().to_string())
}

fn main() {
    match read_username() {
        Ok(name) => println!("username: {}", name),
        Err(e) => eprintln!("error: {}", e),
    }
}
```

`?` 操作符的语义:

```rust
let x = expr?;
// 等价于
let x = match expr {
    Ok(v) => v,
    Err(e) => return Err(e.into()),
};
```

如果 `expr` 是 `Ok(v)`,`v` 被赋给 `x`,继续;如果是 `Err(e)`,**立刻 return** Err。这是 Rust 错误传播的"语法糖",和异常类似但显式。

`?` 只能在返回 `Result` 或 `Option` 的函数里用。

**自定义错误类型**:

```rust
use std::fmt;

#[derive(Debug)]
enum AppError {
    Io(std::io::Error),
    Parse(std::num::ParseIntError),
    NotFound(String),
}

impl fmt::Display for AppError {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match self {
            AppError::Io(e) => write!(f, "IO error: {}", e),
            AppError::Parse(e) => write!(f, "parse error: {}", e),
            AppError::NotFound(name) => write!(f, "not found: {}", name),
        }
    }
}

impl std::error::Error for AppError {}

// From 转换让 ? 自动工作
impl From<std::io::Error> for AppError {
    fn from(e: std::io::Error) -> Self {
        AppError::Io(e)
    }
}

impl From<std::num::ParseIntError> for AppError {
    fn from(e: std::num::ParseIntError) -> Self {
        AppError::Parse(e)
    }
}

fn do_work() -> Result<i32, AppError> {
    let mut f = std::fs::File::open("data")?;   // io::Error 自动转 AppError
    let mut s = String::new();
    std::io::Read::read_to_string(&mut f, &mut s)?;
    let n: i32 = s.trim().parse()?;             // ParseIntError 自动转
    Ok(n)
}
```

下一篇文章讲 trait 时再深入 `Display` / `Error` / `From`。这里只要知道:**自定义错误让你把不同来源的错误统一**。

**panic! 不是异常**:

`panic!` 是 Rust 的"立即崩溃"。用于**不可恢复**的错误:
- 数组越界
- 除以零
- `unwrap()` 一个 None
- 显式 `panic!("...")`

panic 触发 stack unwinding(逐层析构)然后终止进程(或 abort,看配置)。生产代码慎用 panic。

### 集合:Vec / HashMap / String

**Vec<T>**(动态数组):

```rust
let mut v: Vec<i32> = Vec::new();
v.push(1);
v.push(2);
v.push(3);

// 用宏初始化
let v2 = vec![1, 2, 3];

// 访问
let first = v[0];          // panic 如果越界
let maybe = v.get(10);     // 返回 Option<&i32>,越界返回 None

// 遍历
for n in &v {              // 借用
    println!("{}", n);
}
for n in &mut v {           // 可变借用
    *n *= 2;                 // 解引用 + 赋值
}

// 长度 / 容量
println!("len={}, cap={}", v.len(), v.capacity());

// 切片
let slice: &[i32] = &v[1..3];
```

Vec 的内存布局:

```
栈上的 v:                堆:
+--------+
| ptr    | ----------> [1][2][3]......(capacity 个槽,前 len 个有效)
| len    |   3
| cap    |   4(或更大)
+--------+
```

push 时如果 len == cap,Vec 分配更大的堆(通常 2 倍),拷贝旧数据,释放旧堆。这是 amortized O(1)。

**HashMap<K, V>**:

```rust
use std::collections::HashMap;

let mut scores: HashMap<String, i32> = HashMap::new();
scores.insert(String::from("Sun"), 10);
scores.insert(String::from("Li"), 20);

// 访问
let sun_score = scores.get("Sun");        // Option<&i32>
let sun_score = scores["Sun"];             // panic 如果 key 不存在

// entry API(避免先查再插)
scores.entry(String::from("Wang")).or_insert(0);

// 遍历
for (name, score) in &scores {
    println!("{}: {}", name, score);
}

// 从 Vec 构造
let teams = vec![("Sun".to_string(), 10), ("Li".to_string(), 20)];
let map: HashMap<_, _> = teams.into_iter().collect();
```

**注意**:HashMap 默认用 SipHash(抗 DoS 攻击),比 C++ 的 unordered_map 慢一点。游戏里如果性能关键,可以用 `ahash` 或 `fnv` crate 替换 hasher。

**String**:

```rust
let mut s = String::from("hello");
s.push_str(", world");
s.push('!');
s += "!";                              // 等价 push_str
let s2 = format!("{} how are you", s); // 格式化构造

// 遍历
for c in s.chars() {                    // 字符(Unicode 标量)
    print!("{}", c);
}
for b in s.bytes() {                    // 字节
    print!("{:02x} ", b);
}

// 替换
let new = s.replace("hello", "hi");

// 分割
let parts: Vec<&str> = "a,b,c".split(',').collect();
```

### 综合例子:小型库存系统

```rust
use std::collections::HashMap;

#[derive(Debug)]
struct Item {
    name: String,
    quantity: u32,
    price: f32,
}

#[derive(Debug)]
enum InventoryError {
    NotFound(String),
    InsufficientStock { requested: u32, available: u32 },
}

impl std::fmt::Display for InventoryError {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            InventoryError::NotFound(name) => write!(f, "item not found: {}", name),
            InventoryError::InsufficientStock { requested, available } => 
                write!(f, "need {} but only have {}", requested, available),
        }
    }
}

struct Inventory {
    items: HashMap<String, Item>,
}

impl Inventory {
    fn new() -> Self {
        Inventory { items: HashMap::new() }
    }

    fn add(&mut self, name: &str, quantity: u32, price: f32) {
        let entry = self.items.entry(name.to_string()).or_insert(Item {
            name: name.to_string(),
            quantity: 0,
            price,
        });
        entry.quantity += quantity;
    }

    fn take(&mut self, name: &str, quantity: u32) -> Result<f32, InventoryError> {
        let item = self.items.get_mut(name)
            .ok_or_else(|| InventoryError::NotFound(name.to_string()))?;
        
        if item.quantity < quantity {
            return Err(InventoryError::InsufficientStock {
                requested: quantity,
                available: item.quantity,
            });
        }
        item.quantity -= quantity;
        Ok(item.price * quantity as f32)
    }
}

fn main() {
    let mut inv = Inventory::new();
    inv.add("apple", 10, 0.5);
    inv.add("banana", 5, 0.3);

    match inv.take("apple", 3) {
        Ok(cost) => println!("took apple, cost: ${:.2}", cost),
        Err(e) => eprintln!("error: {}", e),
    }

    match inv.take("apple", 100) {
        Ok(_) => println!("ok"),
        Err(InventoryError::InsufficientStock { requested, available }) => {
            println!("not enough: want {} have {}", requested, available);
        }
        Err(e) => eprintln!("other error: {}", e),
    }
}
```

这段代码用到了本篇所有概念:struct、enum 带数据、impl、match、Result、HashMap、错误传播。

## 3 · 四域深入

### 3.1 · 🐧 Linux 系统编程视角

Linux 系统调用大量返回 `Result` 风格(返回值 + errno)。Rust 标准库把这些封装成 `Result`:

```rust
use std::fs::File;
// File::open 返回 Result<File, io::Error>
let f: Result<File, std::io::Error> = File::open("foo.txt");
```

Linux 的 `open(2)` 系统调用返回 `-1` 表示错误,然后查 `errno`。Rust 标准库帮我们把这个变成类型安全的 `Result`。

`std::io::Error` 内部其实存了 OS errno,可以用 `.raw_os_error()` 拿到:

```rust
match File::open("/nonexistent") {
    Ok(_) => println!("ok"),
    Err(e) => {
        if let Some(code) = e.raw_os_error() {
            println!("errno = {} ({})", code, e);  // 2 (ENOENT)
        }
    }
}
```

### 3.2 · 🦀 Rust 生态视角

#### 3.2.1 错误处理生态

主流 crate:

- **thiserror**(deriving 错误类型):用 `#[derive(Error)]` 自动实现 Display / From
- **anyhow**(应用层错误):用 `anyhow::Result<T>` 简化错误传播,不写具体类型
- **eyre**(anyhow 分支):更友好的错误报告

例,thiserror:

```rust
use thiserror::Error;

#[derive(Error, Debug)]
enum AppError {
    #[error("io error")]
    Io(#[from] std::io::Error),
    #[error("parse error")]
    Parse(#[from] std::num::ParseIntError),
    #[error("not found: {0}")]
    NotFound(String),
}
```

`#[from]` 自动生成 `From` 实现,`?` 就能用了。

应用代码用 anyhow:

```rust
use anyhow::{Result, Context};

fn do_work() -> Result<()> {     // 不用写具体错误类型
    let f = File::open("x").context("failed to open x")?;
    // context 给错误加一层说明
    Ok(())
}
```

库代码用 thiserror(明确错误类型),应用代码用 anyhow(简化)。

#### 3.2.2 集合生态

std 内置:Vec / HashMap / BTreeMap / HashSet / BTreeSet / VecDeque / LinkedList / BinaryHeap

外部 crate:
- **ahash**:快速非加密 hash
- **smallvec**:小数据放栈上,大才上堆
- **indexmap**:保持插入顺序的 HashMap
- **hashbrown**:rustc 内部用的 hashmap(后被 std 吸收)
- **bumpalo**:arena 分配器(Phase 4 会用)

### 3.3 · 🎮 游戏编程视角

游戏里 enum 用于状态机:

```rust
enum GameState {
    Loading,
    MainMenu { selected: usize },
    Playing { score: u32, time: f32 },
    Paused,
    GameOver { score: u32, time: f32 },
}
```

每个变体带不同数据。`match` 处理每种情况:

```rust
match state {
    GameState::Loading => draw_loading_bar(),
    GameState::MainMenu { selected } => draw_menu(*selected),
    GameState::Playing { score, time } => update_gameplay(*score, *time),
    GameState::Paused => draw_pause(),
    GameState::GameOver { score, time } => draw_game_over(*score, *time),
}
```

Casey 在 HH 用 C 写同样的逻辑:用 `enum` 加 `switch`,但变体不能带数据,要用 struct + 联合体。Rust enum 一行搞定。

## 4 · 认知地图

### 4.1 上级

- **代数数据类型(ADT)** — 类型论概念:struct 是积类型(product type,AND),enum 是和类型(sum type,OR)。两者组合能表达任意数据
- **类型驱动开发(Type-Driven Design)** — 先设计类型让非法状态不可表达。Rust enum + Option 让 null 引用、未初始化状态都不存在
- **ADT + Pattern Matching** — Haskell / OCaml / Rust / Swift / Kotlin 的标志性特性

### 4.2 同级

| 错误处理方式 | 代表 | 优点 | 缺点 |
|---|---|---|---|
| 异常 | Java / Python / C++ | 简洁 | 隐式,类型不显示 |
| 错误码 | C / Go | 显式 | 容易忽略 |
| Result 类型 | Rust / Haskell | 显式 + 类型安全 | 代码冗长(但 ? 缓解) |
| Optional chaining | Swift / Kotlin | 简洁 | 只解决 null 不解决错误 |

| 集合 | 何时用 |
|---|---|
| `Vec<T>` | 默认动态数组 |
| `HashMap<K,V>` | 按 key 查 |
| `BTreeMap<K,V>` | 按 key 查 + 有序遍历 |
| `HashSet<T>` / `BTreeSet<T>` | 去重 |
| `VecDeque<T>` | 双端队列 |
| `LinkedList<T>` | 几乎不用(Rust 链表难写,且性能差)|

### 4.3 下级

- **struct 子形式**:named / tuple / unit
- **enum 子形式**:unit / tuple-variant / struct-variant
- **方法**:`&self` / `&mut self` / `self`
- **关联函数**:`TypeName::fn_name()`,无 self
- **Option 方法**:`map`, `and_then`, `unwrap_or`, `ok_or`
- **Result 方法**:`map`, `and_then`, `?`, `unwrap_or_else`, `is_ok`, `is_err`

## 5 · 对照与变奏

### Rust enum vs C enum vs Python

**C**:
```c
enum Color { RED, GREEN, BLUE };   // 实际是 int 0,1,2
enum Color c = RED;
// 变体不能带数据
```

**Python**(动态,无真正的 enum):
```python
from enum import Enum, auto
class Color(Enum):
    RED = auto()
    GREEN = auto()
# 变体不能带数据(可以用 dataclass 模拟)
```

**Rust**:
```rust
enum Color {
    Red,
    Green,
    Blue,
    Rgb(u8, u8, u8),   // 变体带数据!C/Python 做不到
}
```

Rust 的"代数数据类型"让 enum 表达力指数级提升。

### Result vs 异常

```python
# Python 异常
try:
    f = open("x")
    data = f.read()
except FileNotFoundError:
    print("not found")
# 不知道 read() 还会抛什么异常
```

```rust
// Rust Result
let f = File::open("x")?;       // 编译器知道可能 Err
let data = f.read_to_string()?;
// 所有可能 Err 都在类型签名里,看一眼就知道
```

代价:Rust 代码 `?` 满天飞。回报:错误处理**显式且类型安全**。

### 多语言模式匹配

- **C / C++**:switch(只支持整数,容易漏 case)
- **Java**:switch + sealed class(Java 17 后接近 Rust)
- **Haskell / OCaml**:pattern matching 是核心特性
- **Python 3.10+**:match / case(类似但较新)
- **Rust**:match 是核心,穷尽性检查,绑定变体数据

Rust 的 match 穷尽性检查独步——加新 enum 变体时,编译器告诉你哪里没处理。

## 6 · 关联 Day

- **铺垫**:[04-rust-from-scratch-2.md](04-rust-from-scratch-2.md) — 所有权(struct 字段涉及所有权)
- **当天**:[05-rust-from-scratch-3.md](05-rust-from-scratch-3.md)(本篇)
- **后续**:
  - [06-rust-from-scratch-4.md](06-rust-from-scratch-4.md) — trait / 泛型(给 struct / enum 加接口)
  - Phase 1 Day 001+:所有 HH 翻译代码用 struct + enum 组织状态
  - Phase 2:实体系统(Entity / Component)大量用 struct

## 7 · 变式训练

### Lv1 · 概念辨析

**题**:为什么 Rust 不让 enum 变体"直接"当类型用?即下面代码为什么不通过:

```rust
enum Message { Quit, Move(i32) }
let m: Move = Move(10);   // 错:Move 不是类型
let m: Message = Message::Move(10);  // 对
```

**参考解答**:Rust 的 enum 是**和类型**——`Message` 是类型,`Quit` 和 `Move` 是它的**变体**(constructors),不是类型本身。变体是用来**构造**`Message` 值的"工厂"。

如果你想为某个变体专门定义类型,可以把它拆出来:

```rust
struct Move { x: i32 }
enum Message { Quit, Move(Move) }
```

这样 `Move` 是类型,可以独立用。

这种设计让 enum 体积固定(能装下最大变体),并且 match 时不需要类型转换。

### Lv2 · 动手实践

**题**:实现一个简单的 JSON 解析器(只支持 string / number / bool / null / array / object)。要求:

1. 定义 `enum Json` 表示 JSON 值
2. 写 `fn parse(s: &str) -> Result<Json, ParseError>`
3. 至少支持:`{"name": "Sun", "age": 18, "tags": ["rust", "game"], "active": true, "score": null}`
4. 写测试用例
5. 跑 `cargo test`,全部通过

**提示**:
- enum:`Null, Bool(bool), Num(f64), Str(String), Arr(Vec<Json>), Obj(HashMap<String, Json>)`
- 解析思路:递归下降,手写 tokenizer
- 不需要支持转义字符 / 浮点精度细节

完成标准:能解析上面的 JSON 字符串,且非法输入返回 Err。

**参考解答骨架**(自己填实现):

```rust
use std::collections::HashMap;

#[derive(Debug, PartialEq)]
enum Json {
    Null,
    Bool(bool),
    Num(f64),
    Str(String),
    Arr(Vec<Json>),
    Obj(HashMap<String, Json>),
}

#[derive(Debug)]
enum ParseError {
    UnexpectedChar(char, usize),
    UnexpectedEnd,
}

struct Parser<'a> {
    chars: Vec<char>,
    pos: usize,
    _phantom: std::marker::PhantomData<&'a ()>,
}

impl<'a> Parser<'a> {
    fn new(s: &str) -> Parser {
        Parser { chars: s.chars().collect(), pos: 0, _phantom: Default::default() }
    }
    
    fn peek(&self) -> Option<char> {
        self.chars.get(self.pos).copied()
    }
    
    fn next(&mut self) -> Option<char> {
        let c = self.peek()?;
        self.pos += 1;
        Some(c)
    }
    
    fn skip_whitespace(&mut self) {
        while let Some(c) = self.peek() {
            if c.is_whitespace() {
                self.pos += 1;
            } else {
                break;
            }
        }
    }
    
    fn parse_value(&mut self) -> Result<Json, ParseError> {
        self.skip_whitespace();
        match self.peek() {
            None => Err(ParseError::UnexpectedEnd),
            Some('{') => self.parse_object(),
            Some('[') => self.parse_array(),
            Some('"') => self.parse_string().map(Json::Str),
            Some('t') | Some('f') => self.parse_bool(),
            Some('n') => self.parse_null(),
            Some(c) if c == '-' || c.is_ascii_digit() => self.parse_number(),
            Some(c) => Err(ParseError::UnexpectedChar(c, self.pos)),
        }
    }
    
    // TODO: 实现 parse_object / parse_array / parse_string / parse_bool / parse_null / parse_number
}

fn parse(s: &str) -> Result<Json, ParseError> {
    let mut p = Parser::new(s);
    let v = p.parse_value()?;
    p.skip_whitespace();
    if p.peek().is_some() {
        return Err(ParseError::UnexpectedChar(p.peek().unwrap(), p.pos));
    }
    Ok(v)
}

fn main() {
    let s = r#"{"name": "Sun", "age": 18}"#;
    match parse(s) {
        Ok(json) => println!("{:?}", json),
        Err(e) => eprintln!("error: {:?}", e),
    }
}
```

实现各 parse_xxx 是练习重点。

### Lv3 · 迁移设计

**题**:你要设计一个配置加载系统。配置来源优先级:命令行参数 > 环境变量 > 配置文件 > 默认值。设计:

1. struct 表示配置
2. enum 表示错误(文件读、解析、缺字段……)
3. 用 Result 串联四个层级

思考:每层的错误类型不同,怎么统一?用 enum + From?或 Box<dyn Error>?或 anyhow?

写出完整签名(不实现细节),并讨论每种的优劣。

### Lv4 · 开源贡献

**题**:`serde`(https://github.com/serde-rs/serde)是 Rust 序列化生态的基石。它用 trait + macro 把 struct/enum 自动转成 JSON / YAML / Bincode / ...

1. clone serde
2. 看它的 `serde_derive` crate 怎么把你的 `#[derive(Serialize)]` 转成代码
3. 看它的 issue tracker 找 `good first issue`
4. 写一个小的 PR

或者更轻量:用 serde 写一个程序序列化你的 struct 到 JSON,从 JSON 反序列化。看生成的代码,理解 derive macro。

## 8 · Rust / Arch 落地代码

### thiserror / anyhow 实战

`Cargo.toml`:

```toml
[package]
name = "demo"
version = "0.1.0"
edition = "2021"

[dependencies]
thiserror = "1"
anyhow = "1"
```

`src/main.rs`:

```rust
use anyhow::{Context, Result};
use thiserror::Error;

// 库风格的错误:thiserror 自动实现 Display / From
#[derive(Error, Debug)]
enum AppError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    
    #[error("parse error: {0}")]
    Parse(#[from] std::num::ParseIntError),
    
    #[error("custom: {message}")]
    Custom { message: String },
}

// 库函数:返回具体错误类型
fn library_func() -> std::result::Result<i32, AppError> {
    let s = std::fs::read_to_string("data.txt")?;  // io::Error 自动转
    let n: i32 = s.trim().parse()?;                  // ParseIntError 自动转
    Ok(n)
}

// 应用函数:用 anyhow,简化
fn app_func() -> Result<()> {
    let n = library_func().context("library_func failed")?;
    println!("got: {}", n);
    Ok(())
}

fn main() -> Result<()> {
    app_func()?;        // main 也能返回 Result,Err 时打印并退出(非 0)
    Ok(())
}
```

跑:

```bash
cargo run
# 如果 data.txt 不存在:
# Error: library_func failed
# 
# Caused by:
#     io error: No such file or directory (os error 2)
# ...
# exit code: 1
```

注意:`anyhow::Error` 的 Debug 输出会**链式**打印所有 context 和 caused by。这就是为什么 anyhow 适合应用——错误报告友好。

### 完整 struct + enum + Result 示例

```rust
use std::collections::HashMap;
use std::fmt;

#[derive(Debug, Clone)]
struct Todo {
    id: u32,
    title: String,
    done: bool,
}

#[derive(Debug)]
enum TodoError {
    NotFound(u32),
    EmptyTitle,
}

impl fmt::Display for TodoError {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match self {
            TodoError::NotFound(id) => write!(f, "todo {} not found", id),
            TodoError::EmptyTitle => write!(f, "title cannot be empty"),
        }
    }
}

impl std::error::Error for TodoError {}

struct TodoList {
    todos: HashMap<u32, Todo>,
    next_id: u32,
}

impl TodoList {
    fn new() -> Self {
        TodoList { todos: HashMap::new(), next_id: 1 }
    }

    fn add(&mut self, title: &str) -> Result<u32, TodoError> {
        if title.trim().is_empty() {
            return Err(TodoError::EmptyTitle);
        }
        let id = self.next_id;
        self.next_id += 1;
        self.todos.insert(id, Todo {
            id,
            title: title.to_string(),
            done: false,
        });
        Ok(id)
    }

    fn complete(&mut self, id: u32) -> Result<(), TodoError> {
        let todo = self.todos.get_mut(&id)
            .ok_or(TodoError::NotFound(id))?;
        todo.done = true;
        Ok(())
    }

    fn list(&self) -> Vec<&Todo> {
        let mut all: Vec<&Todo> = self.todos.values().collect();
        all.sort_by_key(|t| t.id);
        all
    }

    fn summary(&self) -> (usize, usize) {
        let total = self.todos.len();
        let done = self.todos.values().filter(|t| t.done).count();
        (done, total)
    }
}

fn main() {
    let mut list = TodoList::new();
    
    match list.add("Learn Rust") {
        Ok(id) => println!("added todo {}", id),
        Err(e) => eprintln!("error: {}", e),
    }
    
    list.add("Write game").unwrap();
    list.add("Contribute OSS").unwrap();
    
    list.complete(1).unwrap();
    
    println!("\nAll todos:");
    for t in list.list() {
        let status = if t.done { "[x]" } else { "[ ]" };
        println!("  {} {}: {}", status, t.id, t.title);
    }
    
    let (done, total) = list.summary();
    println!("\n{}/{} done", done, total);
}
```

跑:

```bash
cargo run
# 输出:
# added todo 1
#
# All todos:
#   [x] 1: Learn Rust
#   [ ] 2: Write game
#   [ ] 3: Contribute OSS
#
# 1/3 done
```

### 排错

```bash
# 故障 1: "no variant named X in enum Y"
# 原因:enum variant 名打错,或忘了用 EnumName:: 前缀
# 修复:加前缀 Message::Quit,而不是 Quit

# 故障 2: "non-exhaustive patterns"
# 原因:match 没覆盖所有 enum 变体
# 修复:加 _ 通配,或显式处理每个变体

# 故障 3: "cannot find derive macro Error in this scope"
# 原因:没用 thiserror 或没在 Cargo.toml 加依赖
# 修复:cargo add thiserror

# 故障 4: ? 用在返回 () 的函数里
# 错误信息:`?` couldn't convert the error to `()`
# 原因:? 要返回 Result,但函数返回 ()
# 修复:改函数签名为 Result<...>,或用 match 显式处理

# 故障 5: HashMap 用自定义 struct 作为 key 失败
# 错误:the trait Hash is not implemented
# 原因:HashMap 要求 K: Hash + Eq
# 修复:为 struct 派生 #[derive(Hash, Eq, PartialEq)]
```

### 调试技巧

```bash
# 1. 用 {:?} 打印(Debug trait)
println!("{:?}", my_struct);
# 需要 #[derive(Debug)] 在 struct/enum 上

# 2. 用 {:#?} 美化打印(多行)
println!("{:#?}", my_struct);

# 3. dbg! 宏(打印表达式 + 值 + 文件位置,返回值)
let x = dbg!(5 + 3);   // 打印 [src/main.rs:1] 5 + 3 = 8

# 4. 调试模式跑
cargo run                # debug 模式,有 assert 检查
cargo run --release      # release 模式,优化打开(无 assert)

# 5. 用 GDB / LLDB 调试(后面专门讲)
sudo pacman -S gdb
cargo build              # 必须 debug build 才有符号
gdb target/debug/myapp
(gdb) break main
(gdb) run
(gdb) next
(gdb) print variable
```

## 9 · 延伸阅读(可选补充,非必需)

本仓库本地:
- [04-rust-from-scratch-2.md](04-rust-from-scratch-2.md) — 所有权(前置)
- [06-rust-from-scratch-4.md](06-rust-from-scratch-4.md) — trait / 泛型
- [13-diagnosis-tools.md](13-diagnosis-tools.md) — gdb 调试

外部稳定 URL:
- The Rust Book Ch.5-9(本篇对应):
  - https://doc.rust-lang.org/book/ch05-00-structs.html
  - https://doc.rust-lang.org/book/ch06-00-enums.html
  - https://doc.rust-lang.org/book/ch08-00-common-collections.html
  - https://doc.rust-lang.org/book/ch09-00-error-handling.html
- std::collections 文档:https://doc.rust-lang.org/std/collections/
- thiserror:https://docs.rs/thiserror/
- anyhow:https://docs.rs/anyhow/
- Rust Design Patterns:https://rust-unofficial.github.io/patterns/

真实开源源码:
- serde:https://github.com/serde-rs/serde
- thiserror:https://github.com/dtolnay/thiserror
- anyhow:https://github.com/dtolnay/anyhow
