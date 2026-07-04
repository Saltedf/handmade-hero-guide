
# 06 · Rust 从零(4):trait / 泛型 / 生命周期 / 迭代器 / 闭包 / 智能指针 / 并发 / async

> Rust 基础的最后一篇。这一篇覆盖 The Rust Book 第 10-16 章:trait(接口)、泛型、生命周期、迭代器、闭包、智能指针、多线程、async/await。学完你能读 Rust 生态任何主流 crate 的代码。Phase 1 开始你就要用 trait + 迭代器写真实游戏代码了。

## 0 · 为什么要有这一天

前三篇你学了基础。但真实 Rust 代码,你打开 bevy / wgpu / tokio / serde,满眼是这些:

1. **trait bound**:`fn foo<T: Clone + Send>(...)` —— 函数能接受任何满足某些约束的类型。这让你写一次,适用无限类型
2. **生命周期**:`fn foo<'a>(x: &'a str) -> &'a str` —— 编译器要你明确"返回的引用活多久"
3. **迭代器**:`vec.iter().filter(...).map(...).collect()` —— 函数式数据流。性能和手写 for 一样
4. **闭包**:`let f = |x| x + 1;` —— 匿名函数
5. **智能指针**:`Box<T>` / `Rc<T>` / `Arc<T>` / `RefCell<T>` / `Mutex<T>` —— 所有权模型的高级逃生舱
6. **多线程**:`thread::spawn` + `Send` + `Sync` —— Rust 编译期保证无 data race
7. **async/await**:`async fn` —— 异步 I/O,网络服务必备

这些不是炫技,是日常工具。Casey 在 HH 后期用线程池、SIMD、热重载,这些都需要 trait + 并发。Phase 4 你会用线程池渲染,Phase 7 用 async 加载资产。

**心理锚点**:读完这一篇,你能:
- 定义 trait,为类型实现它,理解 trait bound
- 读 `<T>` 泛型代码,写自己的泛型函数 / 结构
- 标注生命周期,理解 `'a` 的含义
- 用迭代器 / 闭包写函数式代码
- 选对智能指针(Box / Rc / Arc / RefCell / Mutex)
- 跑多线程代码,理解 Send / Sync
- 写 async 函数,理解 Future trait

这是 Rust 基础最后一关。学完你算是入门了。

## 1 · 概念地图

| 词 | 是什么 | 类比 |
|---|---|---|
| **trait** | 类型的能力清单(接口) | Java interface,Haskell typeclass |
| **trait bound** | 泛型参数要满足的 trait | "T 必须实现 Clone" |
| **泛型(generic)** | 类型参数化,一份代码适用多类型 | C++ template |
| **生命周期(lifetime)** | 引用有效的范围,编译期标注 | 引用的"使用期限" |
| **迭代器(iterator)** | 惰性序列,实现 Iterator trait | Python iter,JS iterator |
| **闭包(closure)** | 捕获环境的匿名函数 | Python lambda + 闭包,JS arrow function |
| **智能指针(smart ptr)** | 像 Box / Rc / Arc,拥有数据 + 行为 | C++ unique_ptr / shared_ptr |
| **Drop / Deref** | 智能指针的关键 trait | 析构 / 解引用 |
| **Send / Sync** | 并发安全 marker trait | "能跨线程转移 / 共享" |
| **Future** | 异步计算的状态机 | JS Promise |
| **async/await** | 异步语法糖,编译器生成 Future | C# / Python / JS 的 async/await |

## 2 · 心智模型

### 费曼类比:trait 是"能力清单"

想象大学里有一个"工程实习生招聘会"。公司不看你**专业**(类型),看你**能干什么**(trait):
- 能编程吗?(trait `Program`)
- 能用英语开会吗?(trait `SpeakEnglish`)
- 能值夜班吗?(trait `AvailableNight`)

招聘要求(trait bound):"我们需要 `Program + SpeakEnglish`"。任何满足这两个 trait 的人都符合,无论是计算机、电子、还是数学专业。

trait 就是这种"能力清单"。类型可以有多个 trait。函数可以约束泛型参数"必须有哪些能力"。Rust 编译器在编译期检查类型确实有这些能力。

### trait 详解

```rust
// 定义 trait
trait Greet {
    fn greet(&self) -> String;
    
    // 默认实现(可选,实现者可不重写)
    fn shout(&self) -> String {
        self.greet().to_uppercase()
    }
}

// 为类型实现 trait
struct English;
struct Chinese;

impl Greet for English {
    fn greet(&self) -> String {
        String::from("Hello!")
    }
}

impl Greet for Chinese {
    fn greet(&self) -> String {
        String::from("你好!")
    }
}

fn main() {
    let e = English;
    let c = Chinese;
    println!("{}", e.greet());        // Hello!
    println!("{}", c.shout());        // 你好!(默认实现)
}
```

**和 Java/C# interface 的关键差别**:
- Rust 允许**之后**为任何类型实现 trait,包括标准库的类型(叫"扩展方法")。Java 不能给 String 加方法
- 但有**孤儿规则(orphan rule)**:impl 块的 trait 或类型,至少有一个是在当前 crate 定义的。你不能给外部类型实现外部 trait(防止冲突)
- 默认实现让 trait 像抽象类

### trait bound

```rust
// 1. 函数级 bound
fn print_all<T: Greet>(items: &[T]) {
    for item in items {
        println!("{}", item.greet());
    }
}

// 2. where 子句(更易读,复杂 bound 推荐)
fn complex<T, U>(t: T, u: U) -> String
where
    T: Greet + Clone,        // 多个 trait 用 +
    U: std::fmt::Debug,
{
    format!("{:?}", u)
}

// 3. impl Trait 语法(现代写法,等价 T: Trait)
fn use_greet(item: &impl Greet) -> String {
    item.greet()
}

// 4. 返回 impl Trait(注意:不能返回不同类型)
fn make_greet() -> impl Greet {
    English
}
```

**`+` 意味着 AND**:`T: A + B` 表示 T 必须**同时**实现 A 和 B。

### 泛型

```rust
// 泛型函数
fn largest<T: PartialOrd>(list: &[T]) -> &T {
    let mut max = &list[0];
    for item in &list[1..] {
        if item > max {
            max = item;
        }
    }
    max
}

// 泛型 struct
struct Point<T> {
    x: T,
    y: T,
}

// 多类型参数
struct Pair<A, B> {
    first: A,
    second: B,
}

// 泛型 enum
enum Option<T> {
    Some(T),
    None,
}

// 泛型 impl
impl<T> Point<T> {
    fn x(&self) -> &T {
        &self.x
    }
}

// 限定类型的 impl(只为特定 T)
impl Point<f32> {
    fn distance_from_origin(&self) -> f32 {
        (self.x.powi(2) + self.y.powi(2)).sqrt()
    }
}
```

**静态分发 vs 动态分发**:

```rust
// 静态分发(monomorphization):每个 T 类型生成一份代码
fn static_greet<T: Greet>(item: &T) { item.greet(); }
// 编译后:有 static_greet_English 和 static_greet_Chinese 两个函数

// 动态分发(trait object,运行时查 vtable)
fn dyn_greet(item: &dyn Greet) { item.greet(); }
// 编译后:只有一个 dyn_greet,通过 vtable 找方法
```

- **静态分发**:快(无运行时开销),代码大(每个 T 一份)
- **动态分发**:代码小,慢(一次指针跳转,vtable cache miss)

经验:库的 API 用泛型(让用户选),简单场景用 `&dyn Trait`。

### 生命周期深入

第 4 篇介绍了"借用不超过所有者生命期"。本节深入 lifetime annotation。

```rust
// 函数返回引用,编译器需要知道返回的引用基于谁
// 'a 是生命周期参数,告诉编译器:返回值和 s 同生命期
fn first_word<'a>(s: &'a str) -> &'a str {
    s
}

// 两个入参,返回其一
fn longest<'a>(s1: &'a str, s2: &'a str) -> &'a str {
    if s1.len() > s2.len() { s1 } else { s2 }
}
```

`'a` 是个**编译期变量**,代表"某段生命期"。`'a` 出现在入参和返回,意思是:**返回值的生命期不超过入参的最短生命期**。

**省略规则(elision rules)**:大多数情况编译器自动推断,不用写。规则:
1. 每个入参引用默认不同生命周期(`'a`, `'b`)
2. 只有一个入参引用,返回值用相同生命周期
3. 方法(`&self` / `&mut self`),返回值用 self 的生命周期

满足这些规则就不用标注。不满足编译器报错让你加。

**struct 里的引用**:

```rust
// struct 持有引用,必须标注生命周期
struct Excerpt<'a> {
    part: &'a str,        // part 借用外部数据
}

fn main() {
    let novel = String::from("hello world. foo bar.");
    let first_sentence;
    {
        let words = novel.as_str();
        let excerpt = Excerpt { part: words };
        first_sentence = excerpt.part;
    }   // excerpt drop,但 words 还活着
    println!("{}", first_sentence);
}
```

struct 持有引用时,struct 实例的生命周期不能超过被引用数据。这让 struct **不**复制数据,但需要数据活得够久。如果嫌麻烦,直接用 `String`(拥有所有权)更简单。

**`'static` 生命周期**:整个程序运行期。所有字符串字面量是 `&'static str`。函数返回 `&'static str` 表示这个引用永远有效。

```rust
fn static_str() -> &'static str {
    "I live forever"      // 字面量,在静态区
}
```

### 迭代器

迭代器是 Rust 函数式编程的核心。`Iterator` trait:

```rust
trait Iterator {
    type Item;
    fn next(&mut self) -> Option<Self::Item>;
    // 还有几十个默认方法:map, filter, fold, ...
}
```

任何实现了 `next()` 方法的类型都是迭代器。

```rust
let v = vec![1, 2, 3, 4, 5];

// 1. iter:借用,产生 &T
for x in v.iter() { ... }

// 2. into_iter:获取所有权,产生 T
for x in v.into_iter() { ... }    // v 被 move,后面不能用

// 3. iter_mut:可变借用,产生 &mut T
let mut v = vec![1, 2, 3];
for x in v.iter_mut() { *x *= 2; }

// 4. 链式
let sum: i32 = v.iter()
    .filter(|&&x| x > 2)        // 保留 > 2 的
    .map(|&x| x * x)              // 平方
    .sum();                       // 求和
// sum = 9 + 16 + 25 = 50(注意:filter 保留 3, 4, 5)

// 5. collect:转集合
let evens: Vec<i32> = (1..10).filter(|x| x % 2 == 0).collect();
let set: std::collections::HashSet<i32> = vec![1, 1, 2, 3, 3].into_iter().collect();

// 6. fold:累积
let product = (1..=5).fold(1, |acc, x| acc * x);   // 120(5!)
```

**惰性(lazy)**:迭代器不立刻执行,直到你"消费"它(for / collect / sum / count / ...)。这让链式调用无中间分配。

**零成本抽象**:Rust 迭代器编译后和手写 for 循环一样快。`vec.iter().map(|x| x * 2).sum()` 和 `let mut sum = 0; for x in &vec { sum += x * 2; }` 编译后机器码几乎相同。

**自定义迭代器**:

```rust
struct Counter { count: u32 }

impl Counter {
    fn new() -> Counter { Counter { count: 0 } }
}

impl Iterator for Counter {
    type Item = u32;
    
    fn next(&mut self) -> Option<u32> {
        if self.count < 5 {
            self.count += 1;
            Some(self.count)
        } else {
            None
        }
    }
}

fn main() {
    for n in Counter::new() {
        println!("{}", n);   // 1, 2, 3, 4, 5
    }
}
```

### 闭包

闭包是匿名函数,能**捕获**定义点的环境变量。

```rust
fn main() {
    let x = 10;
    
    // 三种闭包语法
    let add = |a, b| a + b;            // 类型推断
    let add2 = |a: i32, b: i32| -> i32 { a + b };  // 显式
    let add3 = |a, b| {                // 多行
        let sum = a + b;
        sum
    };
    
    // 捕获环境
    let multiplier = 3;
    let times = |n| n * multiplier;     // 捕获 multiplier
    
    println!("{}", add(1, 2));          // 3
    println!("{}", times(5));            // 15
}
```

**捕获方式**(由编译器选最小侵入):
- `Fn`:不可变借用(默认最常用)
- `FnMut`:可变借用
- `FnOnce`:获取所有权(用于 `move` 闭包)

```rust
let s = String::from("hi");

let borrow = || println!("{}", s);          // Fn:借用 s
let mut s2 = String::from("hi");
let mut borrow_mut = || { s2.push_str("!"); };  // FnMut:可变借用
borrow_mut();

let own = move || println!("{}", s);         // FnOnce + move:拿走 s
// s 后面不能用
```

**`move` 关键字**:`move || ...` 强制闭包获取环境所有权。线程场景必需:

```rust
let data = vec![1, 2, 3];
std::thread::spawn(move || {
    println!("{:?}", data);   // 子线程拥有 data
});
```

### 智能指针

智能指针 = 数据 + 行为(Drop / Deref)。

| 类型 | 作用 | 何时用 |
|---|---|---|
| `Box<T>` | 堆分配,独占所有权 | 递归类型 / 大数据放堆 |
| `Rc<T>` | 引用计数(单线程) | 多 owner 共享 |
| `Arc<T>` | 原子引用计数(多线程) | 多线程共享 |
| `RefCell<T>` | 运行时借用检查 | 单线程内部可变性 |
| `Mutex<T>` / `RwLock<T>` | 锁 | 多线程内部可变性 |
| `Cow<'a, B>` | Clone-on-write | 可能改可能不改 |
| `Cell<T>` | Copy 类型的内部可变 | 小类型,无借用 |

**Box<T>**:

```rust
// 把数据放到堆上,栈上只放指针(8 字节)
let b = Box::new(5);
println!("{}", b);        // 自动 deref,像直接用 5

// 递归类型必须用 Box(否则大小无限)
enum List {
    Cons(i32, Box<List>),
    Nil,
}

let list = List::Cons(1, Box::new(List::Cons(2, Box::new(List::Nil))));
```

**Rc<T>**(单线程引用计数):

```rust
use std::rc::Rc;

// 多个 owner 共享同一份数据
let a = Rc::new(String::from("hello"));
let b = Rc::clone(&a);     // 引用计数 +1,不是深拷贝
let c = Rc::clone(&a);
println!("count = {}", Rc::strong_count(&a));   // 3

// a, b, c 都 drop 后,数据才释放
```

`Rc` 不是线程安全的(用的非原子计数)。多线程用 `Arc`。

**Arc<T>**(原子引用计数):

```rust
use std::sync::Arc;
use std::thread;

let data = Arc::new(vec![1, 2, 3]);

for _ in 0..3 {
    let data = Arc::clone(&data);
    thread::spawn(move || {
        println!("{:?}", data);
    });
}
```

**RefCell<T>**(运行时借用检查):

```rust
use std::cell::RefCell;

let data = RefCell::new(vec![1, 2, 3]);

// 借用规则在运行时检查
{
    let mut borrowed = data.borrow_mut();
    borrowed.push(4);
}   // 借用结束

{
    let b1 = data.borrow();
    let b2 = data.borrow();    // OK,多个不可变借用
    // let b3 = data.borrow_mut();   // panic:运行时检查,违反"一 mut XOR 多 immut"
    println!("{:?}", b1);
}
```

为什么需要 RefCell:**外部不可变,内部可变**。例如:

```rust
struct Cache {
    data: RefCell<HashMap<String, String>>,
}

impl Cache {
    fn get(&self, key: &str) -> Option<String> {
        // self 是 &Self(不可变),但我们要修改 data
        self.data.borrow_mut().insert("x".to_string(), "1".to_string());
        self.data.borrow().get(key).cloned()
    }
}
```

`Mutex<T>` / `RwLock<T>` 是多线程版本的 RefCell,第 7 节细讲。

### 多线程

Rust 用 `thread::spawn` 创建线程:

```rust
use std::thread;
use std::time::Duration;

thread::spawn(|| {
    for i in 0..5 {
        println!("spawned: {}", i);
        thread::sleep(Duration::from_millis(1));
    }
});

for i in 0..3 {
    println!("main: {}", i);
    thread::sleep(Duration::from_millis(1));
}
// 注意:主线程结束子线程可能被打断!
```

等子线程结束用 `.join()`:

```rust
let handle = thread::spawn(|| {
    println!("in thread");
});
handle.join().unwrap();    // 阻塞等子线程
```

**`Send` 和 `Sync`** 是两个 marker trait(无方法的 trait,只表示"承诺"):

- `Send`:类型可以**安全地转移所有权到另一线程**。`Rc<T>` 不是 Send,`Arc<T>` 是
- `Sync`:类型可以**安全地被多线程共享引用**(`&T`)。`RefCell<T>` 不是 Sync,`Mutex<T>` 是

编译器自动为纯数据类型(无内部可变性、无裸指针)实现 Send + Sync。需要时手动 `unsafe impl`。

**消息传递**:Rust 倾向用 channel 而非锁:

```rust
use std::sync::mpsc;     // multi-producer, single-consumer
use std::thread;

let (tx, rx) = mpsc::channel();

thread::spawn(move || {
    let vals = vec!["hi", "from", "thread"];
    for v in vals {
        tx.send(v).unwrap();
    }
});

for received in rx {
    println!("got: {}", received);
}
```

**共享状态 + 锁**:

```rust
use std::sync::{Arc, Mutex};
use std::thread;

let counter = Arc::new(Mutex::new(0));

let mut handles = vec![];
for _ in 0..10 {
    let counter = Arc::clone(&counter);
    handles.push(thread::spawn(move || {
        let mut num = counter.lock().unwrap();    // 拿锁,返回 MutexGuard
        *num += 1;
        // Guard 离开作用域,锁释放
    }));
}

for h in handles {
    h.join().unwrap();
}

println!("counter = {}", *counter.lock().unwrap());   // 10
```

为什么 Rust 没有 data race:`Mutex<T>` 强制通过 `lock()` 才能访问内部数据,`MutexGuard` 在 drop 时释放锁。**忘了释放不可能**——RAII。

### async / await

异步 I/O 让一个线程处理多个并发任务,不阻塞。适合网络服务、文件 I/O。

```rust
// Cargo.toml: tokio = { version = "1", features = ["full"] }
use tokio;
use std::time::Duration;

async fn say_after(delay: u64, msg: &str) {
    tokio::time::sleep(Duration::from_secs(delay)).await;
    println!("{}", msg);
}

#[tokio::main]
async fn main() {
    // 并发执行(不顺序)
    let f1 = say_after(2, "hello");
    let f2 = say_after(1, "world");
    
    tokio::join!(f1, f2);    // 等 both 完成
    // 输出顺序:world(1秒)然后 hello(2秒)
}
```

**async 函数**返回 `Future`,Future 是个状态机:`.await` 推动状态机。

`async / await` 编译器把函数转成状态机,每个 `.await` 是一个"暂停点"。runtime(如 tokio)调度这些 Future。

为什么需要 async:网络 I/O 是阻塞的(一个 socket 读不到数据时,线程卡住)。异步让线程同时管几千个 socket,谁 ready 就处理谁。Handmade Hero 不需要(单线程游戏),但 Phase 7 你写编辑器或 asset server 时会用。

## 3 · 四域深入

### 3.1 · 🐧 Linux 系统编程视角

Rust 多线程和 Linux 线程的关系:`std::thread::spawn` 调用 `pthread_create`(Linux)或 Win32 线程 API。Rust 线程就是 OS 线程。

Linux 同步原语 vs Rust:
- Linux mutex: `pthread_mutex_lock` / `pthread_mutex_unlock`
- Rust: `Mutex<T>`,自动 RAII unlock
- Linux condvar: `pthread_cond_wait` / `pthread_cond_signal`
- Rust: `std::sync::Condvar`
- Linux rwlock: `pthread_rwlock_*`
- Rust: `std::sync::RwLock`

Rust 的 `Arc<Mutex<T>>` 是 Linux 上 `pthread_mutex_t` 加引用计数的封装,但安全。

Linux 的 async I/O(io_uring)对 Rust:`tokio-uring` crate 直接用 io_uring,比 epoll 还快。

### 3.2 · 🦀 Rust 生态视角

主流 trait / 模式:

- **`Clone`**:`.clone()` 复制
- **`Copy`**:隐式复制
- **`Debug`**:`{:?}` 格式化
- **`Display`**:`{}` 格式化
- **`Default`**:`Default::default()` 默认值
- **`Eq` / `PartialEq`**:等价
- **`Ord` / `PartialOrd`**:排序
- **`Hash`**:哈希(HashMap key)
- **`From` / `Into`**:类型转换
- **`TryFrom` / `TryInto`**:可能失败的转换
- **`Iterator`**:迭代
- **`Drop`**:析构
- **`Send` / `Sync`**:线程安全
- **`Sized`**:大小编译期已知(几乎所有类型)

**derive 宏**:让编译器自动生成 trait 实现:

```rust
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
struct Player { name: String, hp: i32 }
// 自动有了 Debug / Clone / 等
```

主流 async runtime:
- **tokio**:事实标准,网络服务首选
- **async-std**:标准库风格
- **smol**:轻量
- **glommio**:thread-per-core + io_uring

主流并发模式:
- **Actor**:`actix` / `axum` 用 actor 模式
- **CSP**(channel):`tokio::sync::mpsc`
- **Lock-based**:`Mutex<T>` / `RwLock<T>`
- **Lock-free**:`crossbeam` / `dashmap`

### 3.3 · 🎮 游戏编程视角

游戏里 trait + 泛型常用场景:

**组件系统(ECS)**:

```rust
// bevy 风格
trait Component {}

struct Position { x: f32, y: f32, z: f32 }
struct Health(i32)
struct Velocity { x: f32, y: f32, z: f32 }

impl Component for Position {}
impl Component for Health {}
impl Component for Velocity {}

// 系统(system)是泛型函数,过滤有特定组件的实体
fn movement_system(query: impl Iterator<Item = (&mut Position, &Velocity)>) {
    for (pos, vel) in query {
        pos.x += vel.x;
        pos.y += vel.y;
        pos.z += vel.z;
    }
}
```

bevy 真实代码用 archetype-based 存储,这里只是抽象示意。

**多线程渲染**:

```rust
// 主线程产生命令,渲染线程消费
use std::sync::mpsc;

let (tx, rx) = mpsc::channel();

std::thread::spawn(move || {
    while let Ok(cmd) = rx.recv() {
        match cmd {
            RenderCmd::Clear(color) => clear_screen(color),
            RenderCmd::Draw(mesh) => draw_mesh(mesh),
        }
    }
});

// 主线程
tx.send(RenderCmd::Clear([0.0, 0.0, 0.0, 1.0])).unwrap();
```

Phase 4 你会实现类似 Casey 的"游戏逻辑线程 + 渲染线程"。

## 4 · 认知地图

### 4.1 上级

- **类型类(Type Class)** — Haskell 提出的概念,Rust trait 的祖先。让 ad-hoc 多态(同名操作不同类型)类型化
- **Parametric Polymorphism** — 泛型的形式本质:代码不依赖具体类型
- **Algebraic Effects** — async / 迭代器的更一般理论,但 Rust 不直接支持

### 4.2 同级

| 抽象机制 | 代表 |
|---|---|
| Trait + 泛型 | Rust |
| Interface | Java / C# / TypeScript |
| Typeclass | Haskell |
| Concept | C++ 20 |
| Protocol | Swift / Python(PEP 544) |
| Template + CRTP | C++ 老式 |

| 智能指针 | 等价 |
|---|---|
| `Box<T>` | C++ `unique_ptr` |
| `Rc<T>` | C++ `shared_ptr`(非原子) |
| `Arc<T>` | C++ `shared_ptr`(原子) |
| `RefCell<T>` | C++ 无(运行时检查独特) |
| `Mutex<T>` | C++ `std::mutex` + lock_guard |

### 4.3 下级

- **trait Object Safety**:能做 `dyn Trait` 的 trait 叫 object safe(返回 Self / 含泛型方法的 trait 不行)
- **Higher-Ranked Trait Bounds(HRTB)**:`for<'a> T: Trait<'a>`,任何 lifetime 都实现
- **GAT(Generic Associated Types)**:`type Item<'a>;`,trait 关联类型带泛型
- **async Fn Trait**:`AsyncFn` / `AsyncFnMut` / `AsyncFnOnce`(2024+)
- **Const Generic**:`struct Array<T, const N: usize>`(数组大小作为泛型)

## 5 · 对照与变奏

### Rust trait vs Java interface

| | Java interface | Rust trait |
|---|---|---|
| 多继承 | 不支持(implements 多个) | 支持(多 trait bound) |
| 默认方法 | 支持(default) | 支持 |
| 静态方法 | 支持(static) | 关联函数 |
| 给外部类加方法 | 不支持 | 支持(孤儿规则保护) |
| 类型构造器(self type) | 不支持 | 支持(关联类型) |
| 运行时多态 | 自动(vtable) | 需显式 `dyn` |

### Rust async vs JS async

```javascript
// JS
async function fetchUser(id) {
    const res = await fetch(`/users/${id}`);
    return await res.json();
}
```

```rust
// Rust
async fn fetch_user(id: u32) -> Result<User, Error> {
    let res = reqwest::get(format!("/users/{}", id)).await?;
    res.json().await
}
```

语法很像,但底层不同:
- JS:单线程事件循环,V8 引擎管
- Rust:多 runtime 可选(tokio / async-std / smol),零成本

### 迭代器:命令式 vs 函数式

```rust
// 命令式
let mut sum = 0;
for x in &vec {
    if *x > 0 {
        sum += *x * 2;
    }
}

// 函数式
let sum: i32 = vec.iter().filter(|&&x| x > 0).map(|&x| x * 2).sum();
```

两者编译后机器码几乎相同,但函数式更短、可组合。

## 6 · 关联 Day

- **铺垫**:[05-rust-from-scratch-3.md](05-rust-from-scratch-3.md) — struct / enum
- **当天**:[06-rust-from-scratch-4.md](06-rust-from-scratch-4.md)(本篇)
- **后续**:
  - Phase 1 Day 001+:用 trait 设计平台层
  - Phase 4:线程池 + SIMD
  - Phase 7:async 加载资产
  - [13-diagnosis-tools.md](13-diagnosis-tools.md):perf 分析多线程性能

## 7 · 变式训练

### Lv1 · 概念辨析

**题**:`Send` 和 `Sync` 的关系:`&T` 是 Send 当且仅当 T 是 Sync。用定义解释为什么。

**参考解答**:
- `T: Send` 意味着 T 的所有权可以转移到另一线程
- `T: Sync` 意味着 `&T` 可以被多线程同时持有
- 如果 `&T` 是 Send(可以发到另一线程),且 T 是 Sync(`&T` 可以多线程共享),那么把 `&T` 发到另一线程后,那个线程拿到的是 `&T`,多线程共享它——这正是 Sync 的定义

所以 `T: Sync` 等价于 `&T: Send`,反过来也成立。

### Lv2 · 动手实践

**题**:实现一个线程安全的 LRU 缓存。

要求:
1. `struct LruCache<K, V>` 内部用 `Mutex<HashMap<K, V>>` 保护
2. 方法:`fn get(&self, k: &K) -> Option<V>`(V: Clone)
3. 方法:`fn put(&self, k: K, v: V)`
4. 多线程测试:10 个线程同时 get/put
5. 跑 `cargo test`,无 race condition

**参考解答骨架**:

```rust
use std::collections::HashMap;
use std::sync::Mutex;
use std::thread;

pub struct LruCache<K, V> {
    inner: Mutex<HashMap<K, V>>,
}

impl<K: std::hash::Hash + Eq, V: Clone> LruCache<K, V> {
    pub fn new() -> Self {
        LruCache {
            inner: Mutex::new(HashMap::new()),
        }
    }
    
    pub fn get(&self, k: &K) -> Option<V> {
        self.inner.lock().unwrap().get(k).cloned()
    }
    
    pub fn put(&self, k: K, v: V) {
        self.inner.lock().unwrap().insert(k, v);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;
    
    #[test]
    fn concurrent_access() {
        let cache = Arc::new(LruCache::new());
        let mut handles = vec![];
        
        for i in 0..10 {
            let cache = Arc::clone(&cache);
            handles.push(thread::spawn(move || {
                for j in 0..100 {
                    cache.put(i * 100 + j, i * 100 + j);
                    let _ = cache.get(&(i * 100 + j));
                }
            }));
        }
        
        for h in handles {
            h.join().unwrap();
        }
    }
}
```

注:这不是真正的 LRU(没淘汰策略),只是线程安全的 HashMap。LRU 实现可加 `LinkedList` 或 `VecDeque` 跟踪顺序。

### Lv3 · 迁移设计

**题**:你要实现一个"事件总线"(event bus):
- 多个订阅者注册到某 topic
- 发布者发消息,所有订阅者收到
- 跨线程(发布者和订阅者在不同线程)

设计:用 trait + channel 实现。考虑:
- 订阅者 trait 是同步还是 async?
- 用 `mpsc` 还是 `broadcast` channel?
- 用 `Arc<Mutex<Vec<Subscriber>>>` 还是其他?

写出 trait 定义和发布函数签名(不必完整实现)。

**提示**:
- trait:`trait Subscriber { fn on_event(&self, e: &Event); }`
- 用 `dyn Subscriber` 作为多态
- `broadcast` channel(tokio)支持多消费者
- 锁住订阅者列表,遍历调用

### Lv4 · 开源贡献

**题**:Rust 生态主流 crate 都大量用 trait + 泛型。选一个深入:

1. **bevy**(https://github.com/bevyengine/bevy):看 `crates/bevy_ecs/src/world/`,看 World 怎么用泛型 + trait 存组件
2. **tokio**(https://github.com/tokio-rs/tokio):看 `tokio/src/sync/mpsc.rs`,看 channel 怎么用 Send + Sync trait bound
3. **serde**(https://github.com/serde-rs/serde):看 Serializer / Deserializer trait 设计

选一个,找一个 `good first issue`,试着写 PR。

## 8 · Rust / Arch 落地代码

### trait + 泛型实战:简单 Vec2 库

```rust
use std::ops::{Add, Mul};

// 泛型 Vec2,任意数值类型
#[derive(Debug, Clone, Copy, PartialEq)]
struct Vec2<T> {
    x: T,
    y: T,
}

impl<T: Copy + Add<Output = T>> Add for Vec2<T> {
    type Output = Self;
    
    fn add(self, other: Self) -> Self {
        Vec2 {
            x: self.x + other.x,
            y: self.y + other.y,
        }
    }
}

// trait bound: T 必须能和 U 相乘输出 V
impl<T, U, V> Mul<V> for Vec2<T>
where
    T: Mul<U, Output = U>,
    U: Copy,
    V: Into<U>,
{
    type Output = Vec2<U>;
    fn mul(self, scalar: V) -> Vec2<U> {
        let s = scalar.into();
        Vec2 {
            x: self.x * s,
            y: self.y * s,
        }
    }
}

// 我们自己的 trait
trait Length {
    type Output;
    fn length_squared(&self) -> Self::Output;
}

impl<T> Length for Vec2<T>
where
    T: Copy + Mul<Output = T> + Add<Output = T>,
{
    type Output = T;
    
    fn length_squared(&self) -> T {
        self.x * self.x + self.y * self.y
    }
}

fn main() {
    let a = Vec2 { x: 1.0_f32, y: 2.0 };
    let b = Vec2 { x: 3.0, y: 4.0 };
    let c = a + b;
    println!("{:?} + {:?} = {:?}", a, b, c);
    println!("|c|^2 = {}", c.length_squared());
}
```

跑:

```bash
cargo run
# 输出:
# Vec2 { x: 1.0, y: 2.0 } + Vec2 { x: 3.0, y: 4.0 } = Vec2 { x: 4.0, y: 6.0 }
# |c|^2 = 52
```

### 多线程 + channel 实战

```rust
use std::sync::mpsc;
use std::thread;
use std::time::Duration;

fn main() {
    let (tx, rx) = mpsc::channel();
    
    // 多个 producer
    for i in 0..3 {
        let tx = tx.clone();      // 复制 sender
        thread::spawn(move || {
            for j in 0..5 {
                tx.send(format!("worker {} msg {}", i, j)).unwrap();
                thread::sleep(Duration::from_millis(10));
            }
        });
    }
    
    // drop 原 tx,否则 rx 永远不会结束(channel 至少一个 sender 时)
    drop(tx);
    
    // 单 consumer
    for msg in rx {
        println!("received: {}", msg);
    }
    
    println!("all done");
}
```

### async / await 实战

`Cargo.toml`:

```toml
[dependencies]
tokio = { version = "1", features = ["full"] }
reqwest = { version = "0.12", features = ["json"] }
serde = { version = "1", features = ["derive"] }
```

`src/main.rs`:

```rust
use serde::Deserialize;

#[derive(Deserialize, Debug)]
struct User {
    id: u32,
    name: String,
}

async fn fetch_user(id: u32) -> Result<User, reqwest::Error> {
    let url = format!("https://jsonplaceholder.typicode.com/users/{}", id);
    let user = reqwest::get(&url).await?.json::<User>().await?;
    Ok(user)
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // 并发获取 3 个用户
    let (u1, u2, u3) = tokio::join!(
        fetch_user(1),
        fetch_user(2),
        fetch_user(3),
    );
    
    println!("user 1: {:?}", u1?);
    println!("user 2: {:?}", u2?);
    println!("user 3: {:?}", u3?);
    
    Ok(())
}
```

跑:

```bash
cargo run
# 并发请求 3 个 API,总耗时约等于单次请求耗时(非 3 倍)
```

### 排错

```bash
# 故障 1: "the trait `Send` is not implemented"
# 原因:跨线程转移了非 Send 类型(如 Rc<T>)
# 修复:Rc 换 Arc

# 故障 2: "cannot be sent between threads safely"
# 原因:闭包捕获了非 Send 类型
# 修复:检查捕获,改成 Arc 或不用

# 故障 3: lifetime 标注错误 E0621
# 原因:函数返回引用,但和某个入参的生命周期对不上
# 修复:看编译器建议,加 'a 标注

# 故障 4: trait object 不 object safe
# 错误:`dyn MyTrait` cannot be made into an object
# 原因:trait 有返回 Self 或泛型方法
# 修复:把返回 Self 改成关联类型,或拆分 trait

# 故障 5: async 函数在非 async 上下文里 await
# 错误:`await` is only allowed inside async blocks
# 修复:加 #[tokio::main] 让 main 是 async

# 故障 6: dead lock
# 症状:程序 hang 住
# 调试:用 gdb 看每个线程在哪:`thread apply all bt`
# 常见原因:嵌套锁(Mutex 里又 lock 另一个 Mutex)
# 修复:重构,避免嵌套锁;或用 parking_lot::Mutex(更高效)

# 故障 7: tokio task panic 不传播
# tokio::spawn 默认吞 panic
# 修复:用 JoinHandle.await,它返回 Result,Err 是 panic
```

### 性能调试工具

```bash
# 装 perf(Phase 4 / Day 详细讲)
sudo pacman -S perf

# 装 flamegraph
cargo install flamegraph
# 跑生成火焰图:
cargo flamegraph --bin myapp
# 输出 flamegraph.svg,浏览器打开看哪里慢

# 多线程性能:用 perf top
sudo perf top -p <pid>
# 看哪个函数占 CPU 多

# 用 hyperfine 比较性能
sudo pacman -S hyperfine
hyperfine --warmup 3 './target/release/myapp' './target/release/myapp_other'
# 输出统计:平均时间 / 标准差 / 速度比
```

## 9 · 延伸阅读(可选补充,非必需)

本仓库本地:
- [05-rust-from-scratch-3.md](05-rust-from-scratch-3.md) — struct / enum(前置)
- [13-diagnosis-tools.md](13-diagnosis-tools.md) — gdb / perf / flamegraph
- [14-math-foundations.md](14-math-foundations.md) — 泛型 Vec2 在数学库的设计

外部稳定 URL:
- The Rust Book Ch.10-16:
  - https://doc.rust-lang.org/book/ch10-00-generics.html
  - https://doc.rust-lang.org/book/ch13-00-functional-features.html
  - https://doc.rust-lang.org/book/ch15-00-smart-pointers.html
  - https://doc.rust-lang.org/book/ch16-00-concurrency.html
- Rust Async Book:https://rust-lang.github.io/async-book/
- Tokio Tutorial:https://tokio.rs/tokio/tutorial
- Rustonomicon(unsafe / 内部细节):https://doc.rust-lang.org/nomicon/

真实开源源码:
- bevy ECS:https://github.com/bevyengine/bevy/tree/main/crates/bevy_ecs
- tokio mpsc:https://github.com/tokio-rs/tokio/blob/master/tokio/src/sync/mpsc.rs
- crossbeam(lock-free):https://github.com/crossbeam-rs/crossbeam
- std Sync:https://github.com/rust-lang/rust/tree/master/library/std/src/sync
