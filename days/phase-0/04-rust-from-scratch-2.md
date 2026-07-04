
# 04 · Rust 从零(2):所有权、借用、切片

> 这一章是 Rust 的灵魂。读懂这一章,你就跨过了 Rust 最陡的那道坎——比所有其他语言的"难点"都难。它叫所有权(ownership),它决定了 Rust 为什么能"无 GC 内存安全"。Casey 用 C 手动管理内存,他用 free() 释放;Rust 用所有权,编译器自动插入 free。读懂这篇你才真正开始写 Rust。

## 0 · 为什么要有这一天

C/C++ 程序员一辈子和这些 bug 战斗:

1. **use-after-free**:释放了内存,还继续用那个指针。读到的是垃圾数据,甚至安全漏洞(很多黑客攻击利用这个)
2. **double-free**:同一块内存释放两次。导致堆损坏
3. **memory leak**:分配了不释放。短程序没事,长跑的服务会撑爆内存
4. **buffer overflow**:数组越界读写。可能导致安全漏洞(Love Bug 蠕虫就是这么来的)
5. **data race**:多线程并发改同一个变量,结果不确定

C/C++ 的解决方式:
- **手动管理**(`malloc` / `free`):高效但易错。Casey 在 HH 视频里就踩过 double-free 的坑
- **智能指针**(C++ 的 `unique_ptr` / `shared_ptr`):有用但逃不脱循环引用

Java / Python / Go 的解决方式:**垃圾回收(GC)**。运行时定期扫描内存,没人引用的就释放。代价:
- **暂停(STW, Stop-The-World)**:GC 时整个程序暂停,游戏掉帧
- **高内存占用**:GC 要 2-5 倍实际使用量
- **不确定释放时机**:文件 / 锁可能不及时释放

**Rust 的方案:所有权(ownership)**。编译器在编译期分析每个变量的所有权,自动在它"离开作用域"时插入 `free`。代价:
- 你要学规则(本篇)
- 借用要满足约束(borrow checker)
- 某些模式需要绕过(`Rc<RefCell<T>>` / `unsafe`)

但回报巨大:**无 GC、无暂停、内存安全、线程安全**。这就是为什么 Rust 适合游戏开发(低延迟)、嵌入式(无 GC)、系统服务(长跑稳定)。

**心理锚点**:读完这一篇,你能:
- 解释"所有权"是什么,为什么 Rust 这么设计
- 看懂 `&` 和 `&mut`,知道什么时候用哪个
- 修编译器报的 `cannot borrow as mutable` / `does not live long enough` 错误
- 解释 String 和 &str 的本质差别
- 写不依赖 GC 的 Rust 代码,内存自动管理

## 1 · 概念地图:ownership / borrow / lifetime / slice

| 词 | 是什么 | 类比 |
|---|---|---|
| **所有权(ownership)** | 一个变量"拥有"某块内存的责任,负责释放它 | 唯一保管钥匙的人,他要走要把钥匙交出去或销毁 |
| **move** | 把所有权从 A 转给 B,A 不再能用 | 钥匙从 A 手交到 B 手 |
| **借用(borrow)** | 暂时拿别人的数据用,不拥有 | 借别人的书看,看完整还 |
| **引用(reference)** | 借用的语法形式,`&x` 是"指向 x 的引用" | 书签,标出书在哪 |
| **可变引用** | `&mut x`,允许通过引用修改原数据 | 借来允许涂改 |
| **生命周期(lifetime)** | 引用有效的范围(编译期分析) | 借书期限,过期归还 |
| **slice** | 某连续序列的"一段视图",`&[T]` / `&str` | 把蛋糕切一块,不动整块 |
| **Copy** | 整数 / bool / 等小类型"复制"而非"移动" | 钥匙复制一份,各拿一把 |
| **Drop** | 离开作用域时自动调用的析构函数 | 离开房间自动关灯 |

**核心规则**(背下来):

1. Rust 里每个**值**有且仅有一个**所有者**(owner)
2. 当所有者离开作用域,值被自动销毁(`Drop::drop` 被调用,内存释放)
3. 赋值或传参默认是**移动**(move),所有权转给新变量;原变量失效
4. 实现 `Copy` trait 的类型(整数、bool、char 等)赋值是**复制**,原变量仍有效
5. 借用规则:任意时刻,要么有**一个** `&mut`,要么有**多个** `&`,不能同时

## 2 · 心智模型

### 费曼类比:所有权是"独特的图书借阅制度"

想象一个图书馆有奇怪的规则:

**规则 1:每本书只有一个借出者**
书只能被一个人借出。借出后,书架上书的"位置"标记是空的(不在你那),只有借的人能用。

**规则 2:归还 = 自动**
借出者到期(离开作用域)时,书自动归还。你不用记得还。

**规则 3:转借 = 转移所有权**
借的人可以把书转给另一个人(传参、赋值),但转了之后,他自己**再也用不了**这本书了。"转借"就是 move。

**规则 4:复印 = 仅小书**
有些"小书"(整数、bool)被设计成"可复制"。借出去时复印一份,两人各拿一份,互不影响。

**规则 5:参观 = 借用**
你不借书,只是"看一眼"——这叫**借用(borrow)**。规则:
- 可以多人**同时**看(多个 `&` 不可变引用)
- 但**只有一人**改时,别人不能看也不能改(唯一 `&mut`)
- 为什么:多人看不会冲突;有人改时,别人看就违反一致性

这就是 Rust 所有权 + 借用 的全部。它的代价是你要**显式声明**谁拥有什么、谁借用什么。它的回报是:**编译器在编译期就验证了这些规则,运行时不会有 use-after-free 或 data race**。

### 内存布局:栈 vs 堆

要理解所有权,先理解内存布局:

- **栈(stack)**:自动分配,后进先出。函数调用时局部变量压栈,返回时弹栈。**快**(就一个指针移动),**但大小编译期必须知道**
- **堆(heap)**:手动申请释放。`malloc` 在堆上找一块,返回指针;`free` 释放。**慢**(要管理空闲列表),**但大小运行时决定**

C 代码:
```c
int x = 5;             // 栈
int* p = malloc(4);    // 堆,返回指针
*p = 10;
free(p);               // 必须手动释放,否则 leak
```

Rust:
```rust
let x = 5;                  // 栈(i32 是 Copy)
let mut s = String::from("hello");  // s 在栈,内部指针指向堆上的 UTF-8 字节
s.push_str(", world");      // 可能重新分配堆
// s 离开作用域时,自动 drop,堆被释放
```

`String` 的内存布局:

```
栈上的 s:               堆:
+----------+
| ptr      | ---------> [h][e][l][l][o][,][ ][w][o][r][l][d]
| len      |  11
| capacity |  11
+----------+
```

- `ptr`:指向堆上字节的指针(8 字节)
- `len`:当前长度(8 字节)
- `capacity`:分配的总容量(8 字节)

总共栈上 24 字节。堆上 11 字节(实际可能多,因为有 capacity)。

### move 的本质

```rust
let s1 = String::from("hello");
let s2 = s1;

// println!("{}", s1);  // 编译错:s1 已 move
println!("{}", s2);     // OK
```

发生了什么:
1. `s1` 在栈上有 `{ptr, len, cap}`
2. `let s2 = s1` 把这 24 字节**位拷贝**到 `s2` 的栈位置
3. **关键**:Rust 把 `s1` 标记为"已 move,不可再用"
4. `s2` 现在是这块堆内存的**唯一所有者**
5. 当 `s2` 离开作用域,它的 `drop` 被调用,堆被释放

为什么不"深拷贝"堆?**性能**。如果每次赋值都深拷贝,程序会慢到不能忍。Rust 选择 move 语义,堆只有一份,所有权转移。

如果是 C++ 同样的代码 `string s2 = s1`,默认是深拷贝(慢)。C++ 也支持 `std::move(s1)` 显式 move,但程序员要记得用。Rust 让 move 成为默认,immutable 共享靠 `Rc` / `Arc`(后面讲)。

### Copy 的本质

```rust
let x = 5;
let y = x;            // x 被复制(不是 move)
println!("{} {}", x, y);   // 两个都能用
```

为什么 `i32` 是 Copy 而 String 不是?

- `i32` 是 4 字节,纯值,**所有信息都在栈上**。复制 4 字节廉价
- `String` 持有堆指针,如果"按位复制",会有两个变量指向同一块堆,**释放两次崩溃**(double-free)

Rust 规定:实现 `Copy` trait 的类型,赋值是复制;否则是 move。`Copy` 类型的规则:**所有字段都是 Copy**(纯栈数据)。常见 Copy 类型:
- 所有整数 / 浮点 / bool / char
- 不含任何堆数据的 tuple / array(如 `(i32, f64)`、`[i32; 5]`)
- `&T`(引用本身是 Copy,因为引用不"拥有")

不是 Copy:`String`、`Vec<T>`、`Box<T>`、`HashMap`、任何有堆的东西。

### 借用的本质

```rust
fn print_len(s: &String) {     // s 是 String 的引用
    println!("len = {}", s.len());
}

fn main() {
    let s = String::from("hello");
    print_len(&s);              // 借用 s 给函数,不转移所有权
    println!("still own: {}", s);  // s 仍然可用
}
```

- `&s` 创建一个"指向 s 的引用",类型 `&String`
- 函数接收 `&String`,借用,**不**拥有,**不**会在结束时 drop
- main 仍然拥有 s,后面继续用

为什么用借用:不想为了一次函数调用就丢失数据所有权。

**可变借用**:

```rust
fn push_world(s: &mut String) {
    s.push_str(", world");
}

fn main() {
    let mut s = String::from("hello");
    push_world(&mut s);          // 可变借用
    println!("{}", s);            // hello, world
}
```

- `&mut s` 创建可变引用
- 函数能通过引用修改原数据
- 要求 `s` 本身是 `mut`

### 借用规则(关键!)

**同一时间,要么有一个 `&mut`,要么有多个 `&`,不能同时存在。**

```rust
let mut s = String::from("hello");

let r1 = &s;       // 不可变借用
let r2 = &s;       // 另一个不可变借用(OK,多个 & 可以共存)
println!("{} {}", r1, r2);

let r3 = &mut s;   // 可变借用(错!不可变借用 r1 r2 还在用)
// 编译错:cannot borrow `s` as mutable because it is also borrowed as immutable
```

为什么这样设计?**避免数据竞争**:
- 多个 reader 没问题
- 一个 writer 时,任何 reader 看到的可能是中间状态——不一致

Rust 在**编译期**就保证这条规则。这就是为什么"Rust fearless concurrency"——你随便开线程,编译器帮你检查不会 data race。

规则的关键细节:**借用是否"还在用"取决于最后一次使用**,不是作用域结束。这叫 NLL(Non-Lexical Lifetimes):

```rust
let mut s = String::from("hello");
let r1 = &s;
let r2 = &s;
println!("{} {}", r1, r2);
// r1 r2 在这之后没用了,NLL 知道它们"结束"了

let r3 = &mut s;   // OK!r1 r2 已结束
println!("{}", r3);
```

### slice:借用的特殊形式

slice 是对一个连续序列的"片段视图"。它是一个**胖指针(fat pointer)**,包含起点指针和长度。

```rust
let s = String::from("hello world");
let hello: &str = &s[0..5];       // "hello"(借用了 s 的一部分)
let world: &str = &s[6..11];      // "world"
```

- `&str` 是字符串 slice,胖指针(8 字节 ptr + 8 字节 len = 16 字节)
- 不拥有数据,只是借用
- 不修改原数据

为什么用 slice 而不是 String:很多函数只需要"读一段文本",不需要拥有。`fn process(s: &str)` 比 `fn process(s: String)` 灵活——可以接受 String 借用、字符串字面量、其他 slice。

```rust
fn first_word(s: &str) -> &str {
    let bytes = s.as_bytes();
    for (i, &byte) in bytes.iter().enumerate() {
        if byte == b' ' {
            return &s[0..i];
        }
    }
    &s[..]
}

fn main() {
    let s = String::from("hello world");
    let word = first_word(&s);     // word 借用 s
    // 如果这里 clear s,word 就 dangling!
    // println!("{} {}", s, word);  // 但 Rust 编译期就阻止这种事
}
```

slice 让函数签名**精确表达意图**:"我只需要读,不需要拥有,不需要修改"。

### 生命周期(lifetime)简介

完整的 lifetime 在第 6 篇深入,这里给概念:

借用必须**不超过**所有者的生命期。例:

```rust
let r;
{
    let x = 5;
    r = &x;        // r 借用 x
}                   // x 在这里 drop,r 的借用失效
println!("{}", r); // 编译错:borrowed value does not live long enough
```

x 在内层 block 末尾 drop,但 r 还想用它——这就是 dangling reference。Rust 编译期检查出来。

大多数情况下 Rust 自动推断生命周期(就像自动推断类型)。但写函数时,有时需要显式标注:

```rust
// 'a 是生命周期参数,告诉编译器"返回的引用至少和 s1 一样长"
fn longest<'a>(s1: &'a str, s2: &'a str) -> &'a str {
    if s1.len() > s2.len() { s1 } else { s2 }
}
```

第 6 篇细讲,这里只要知道:**lifetime 是借用规则的延伸,编译期验证引用不会悬挂**。

## 3 · 四域深入

### 3.1 · 🐧 Linux 系统编程视角

C 的内存管理 vs Rust 的:

**C**(Casey 的方式):
```c
char* s = malloc(11);
strcpy(s, "hello world");
printf("%s\n", s);
free(s);
// 程序员的责任:
// 1. 记得 free
// 2. free 后别再用
// 3. 别 free 两次
// 4. 别忘了在所有错误路径上 free
```

**Rust**:
```rust
let s = String::from("hello world");
println!("{}", s);
// 离开作用域,自动 drop,堆释放
```

编译器自动调用 `String::drop`,等价于 C 的 `free(s.ptr)`。

Rust 的所有权模型让系统编程**安全且同样快**——`String` 在堆上分配,运行时和 C 的 `malloc` 一样,但 free 由编译器自动插入,不漏不错。

Linux 内核从 6.1(2022)开始接受 Rust 代码,正是因为这种"无 GC 的内存安全"对内核太有价值。

### 3.2 · 🦀 Rust 生态视角(本篇核心)

#### 3.2.1 编译期内存安全的代价

```rust
// 错误 1:用 move 后的变量
let s = String::from("hello");
let t = s;
println!("{}", s);    // 编译错:borrow of moved value

// 修复 1a:借用
println!("{}", &s);   // 改这里没用,要改 let t = &s;

// 修复 1b:克隆
let t = s.clone();    // 显式深拷贝,堆也复制一份
println!("{} {}", s, t);
```

#### 3.2.2 函数参数:借用 vs 拥有

```rust
// 拥有:函数拿走所有权,调用者失去变量
fn take(s: String) {
    println!("got {}", s);
}  // s 在这里 drop

// 借用:函数只读,调用者继续拥有
fn borrow(s: &String) {
    println!("got {}", s);
}

// 可变借用:函数可改,调用者继续拥有
fn modify(s: &mut String) {
    s.push_str("!");
}

fn main() {
    let s = String::from("hello");
    borrow(&s);                  // 借用
    borrow(&s);                  // 还能借
    take(s);                     // 拿走所有权
    // borrow(&s);               // 错:s 已 move
}
```

经验法则:
- 函数要**用完销毁**:`String`(take)
- 函数要**读**:`&String` 或更好,`&str`
- 函数要**改**:`&mut String`

更现代的 Rust 函数签名倾向用 `&str` 而非 `&String`(更通用):

```rust
fn print(s: &str) {        // 接受 &String、&str、字面量 都能自动转
    println!("{}", s);
}
```

#### 3.2.3 返回引用

```rust
// 错误:返回局部变量的引用(dangling reference)
fn bad() -> &String {
    let s = String::from("hello");
    &s       // 编译错:s 在函数结束就 drop
}

// 正确:返回拥有所有权的值(值移动出去)
fn good() -> String {
    let s = String::from("hello");
    s        // move 出去,不会被 drop
}

// 正确:接收引用,返回引用(同样的生命周期)
fn first_word(s: &str) -> &str {
    // ...
    s
}
```

#### 3.2.4 集合的借用

```rust
let mut v: Vec<i32> = vec![1, 2, 3, 4, 5];

// 借用整个 Vec
let slice: &[i32] = &v[1..3];   // [2, 3]
let whole: &[i32] = &v;

// 借用 + 修改:必须满足"只有一个 mut 借用"规则
let mut_ref: &mut Vec<i32> = &mut v;
mut_ref.push(6);
// 此时 v 不能被借用(因为 mut_ref 在用),直到 mut_ref 最后一次使用

// 借用元素
let first: &i32 = &v[0];
```

Vec 在 push 时可能重新分配(容量不够),之前的引用就失效了。Rust 编译期阻止你这么做:

```rust
let mut v = vec![1, 2, 3];
let first = &v[0];
v.push(4);           // 编译错:不能在不可变借用 first 存在时 mut v
println!("{}", first);
```

C++ 同样代码会 UB(可能 segfault),Rust 编译期就拦住。

#### 3.2.5 String vs &str 完整对比

| | String | &str |
|---|---|---|
| 拥有权 | 有 | 无(借用) |
| 可变性 | 可变 | 不可变(只能用 `&mut str` 改,但很少见) |
| 存储位置 | 堆 | 任意(栈、堆、静态区) |
| 大小 | 24 字节(ptr+len+cap) | 16 字节(ptr+len) |
| 创建 | `String::from("x")`、`"x".to_string()` | `"x"`、`&s[..]`、`&s` |
| 用途 | 拥有、修改、增长 | 借用、读、传参 |

**经验法则**:
- 字段、返回值、需要拥有:用 String
- 函数参数(只读):用 &str

### 3.3 · 🎮 游戏编程视角

游戏里所有资源(贴图、音频、模型)都是堆分配的大块数据。所有权让谁拥有什么清晰:

```rust
struct Texture { data: Vec<u8>, w: u32, h: u32 }

struct Sprite {
    texture: Texture,    // Sprite 拥有 Texture
    x: f32, y: f32,
}

// 多个 Sprite 共享一个 Texture 怎么办?
// 用 Rc<Texture>(引用计数,后面 Phase 4 讲)
// 或 Arc<Texture>(线程安全的 Rc)
```

Casey 在 HH 里手写"资产句柄 + 引用计数",本质和 Rust 的 `Arc<T>` 一样。Rust 把这个模式语言化、安全化。

## 4 · 认知地图

### 4.1 上级

- **RAII(Resource Acquisition Is Initialization)** — C++ 提出,资源获取和对象生命周期绑定。Rust 把它作为根基
- **Affine Type System** — 类型论里的"线性类型"放宽版:每个值最多被用一次(move 后不能用),但不能保证至少用一次
- **Borrow Checking** — 编译期验证借用规则的算法,Rust 编译器的核心组件

### 4.2 同级

| 内存管理方式 | 代表 | 优点 | 缺点 |
|---|---|---|---|
| 手动 | C / C++ | 最快,可控 | 易错(use-after-free / leak) |
| 引用计数(RC) | C++ shared_ptr / Swift / Python(部分) | 简单,无暂停 | 循环引用 leak,原子操作慢 |
| 追踪式 GC | Java / Go / Python(主要) | 程序员无负担 | STW 暂停,内存大 |
| 所有权 + Borrow | Rust | 无 GC、安全 | 学习曲线陡 |
| Arena | C / Rust(手写) | 批量释放,快 | 生命周期手动管 |

本教程:**Rust 所有权**(主要)+ **Arena**(Phase 4 Casey 会讲,大型游戏关卡切换时批量释放)。

### 4.3 下级

- **move semantics**:赋值和传参默认移动所有权
- **Copy trait**:简单类型按位复制(整数、bool 等)
- **Drop trait**:离开作用域自动析构
- **借用规则**:N 个 `&` XOR 1 个 `&mut`
- **slice**:`&[T]` / `&str`,胖指针,借用连续序列
- **lifetime**:`'a`,编译期标注引用有效范围
- **NLL(Non-Lexical Lifetimes)**:2018 edition 后,借用基于使用而非词法作用域结束

## 5 · 对照与变奏

### 同一函数在三种内存管理下

**C(手动)**:
```c
char* make_greeting(const char* name) {
    int len = strlen(name) + 8;
    char* s = malloc(len);
    sprintf(s, "Hello, %s!", name);
    return s;          // 调用者要 free
}

int main() {
    char* g = make_greeting("Sun");
    printf("%s\n", g);
    free(g);            // 必须!忘了就 leak
}
```

**Python(GC)**:
```python
def make_greeting(name):
    return f"Hello, {name}!"   # GC 自动释放

g = make_greeting("Sun")
print(g)
# 啥都不用管,GC 会处理
# 但你不知道什么时候释放,文件 / 锁可能延迟
```

**Rust(所有权)**:
```rust
fn make_greeting(name: &str) -> String {
    format!("Hello, {}!", name)    // 拥有,return 时 move 出去
}

fn main() {
    let g = make_greeting("Sun");
    println!("{}", g);
}   // g 离开作用域,自动 free
```

Rust 既有 C 的性能(编译期插入 free),又有 Python 的便利(不用记得 free)。

### 同一数据结构在不同语言

**链表节点**:

C(用裸指针,容易错):
```c
struct Node { int val; struct Node* next; };
```

Rust(安全版本,但有约束):
```rust
// 这是错的!因为 next 借用 self,生命周期不固定
// struct Node { val: i32, next: Option<&Node> }

// 正确:用 Box(独占所有权,单链)
struct Node { val: i32, next: Option<Box<Node>> }

// 双向链表 / 图:用 Rc<RefCell<Node>>(运行时借用检查)
// 或 unsafe 裸指针(像 C 一样,但失去安全保证)
```

Rust 链表是出名的难(https://rust-unofficial.github.io/too-many-lists/),因为所有权模型对"循环引用"不友好。但实践中,游戏 / 服务里很少用链表,用 Vec 更快、更安全。

## 6 · 关联 Day

- **铺垫**:[03-rust-from-scratch-1.md](03-rust-from-scratch-1.md) — 变量、类型、控制流
- **当天**:[04-rust-from-scratch-2.md](04-rust-from-scratch-2.md)(本篇)
- **后续**:
  - [05-rust-from-scratch-3.md](05-rust-from-scratch-3.md) — struct / enum(用到所有权)
  - [06-rust-from-scratch-4.md](06-rust-from-scratch-4.md) — 完整 lifetime / 智能指针(Box/Rc/Arc/RefCell)
  - Phase 1 Day 001-005:所有 Rust 代码都需要懂所有权

## 7 · 变式训练

### Lv1 · 概念辨析

**题**:下面 5 段代码,哪些编译通过?对不通过的,说出错误码和原因。

```rust
// (a)
let s = String::from("hi");
let t = s;
println!("{}", t);

// (b)
let s = String::from("hi");
let t = s;
println!("{} {}", s, t);

// (c)
let n = 5;
let m = n;
println!("{} {}", n, m);

// (d)
let mut v = vec![1, 2, 3];
let r = &v;
v.push(4);
println!("{}", r);

// (e)
let mut s = String::from("hi");
let r1 = &s;
let r2 = &mut s;
println!("{} {}", r1, r2);
```

**参考解答**:
- **(a) 通过**:s move 给 t,t 拥有,只用 t 没问题
- **(b) 不通过**:s move 给 t 后再用 s,错 E0382(borrow of moved value)。修:`let t = s.clone();`
- **(c) 通过**:i32 是 Copy,赋值是复制,n m 都能用
- **(d) 不通过**:r 不可变借用 v,然后 mut v(push 改 vec),违反"一 mut XOR 多 immut"。错 E0502。修:把 r 用完再 push
- **(e) 不通过**:r1 不可变借用还在,r2 又可变借用。错 E0502。修:不要同时借用

### Lv2 · 动手实践

**题**:实现一个 `longest` 函数:接收两个字符串 slice,返回较长的那个的 slice。处理边界情况。

要求:
1. 写函数签名,自己决定参数和返回类型
2. 写至少 3 个测试用例(`#[test]`)
3. 跑 `cargo test`,全部通过
4. 故意制造一个 lifetime 错误,看编译器怎么报

**参考解答**:

```rust
// src/lib.rs(或在 src/main.rs 加 mod tests)

// 'a 是生命周期参数,告诉编译器:
// 返回的 &str 至少和 s1, s2 中较短的那个一样长
fn longest<'a>(s1: &'a str, s2: &'a str) -> &'a str {
    if s1.len() >= s2.len() {
        s1
    } else {
        s2
    }
}

#[cfg(test)]                  // 只在 cargo test 时编译
mod tests {
    use super::*;              // 引入上层模块的 longest

    #[test]
    fn first_longer() {
        assert_eq!(longest("hello", "hi"), "hello");
    }

    #[test]
    fn second_longer() {
        assert_eq!(longest("hi", "world"), "world");
    }

    #[test]
    fn equal_length() {
        // 两个一样长,返回第一个(我们的实现)
        assert_eq!(longest("abc", "xyz"), "abc");
    }
}
```

故意制造 lifetime 错误的例子:

```rust
fn bad_longest<'a>(s1: &str, s2: &str) -> &'a str {
    let result = String::from("computed");  // 局部 String
    &result    // 编译错:返回局部变量的引用
}
```

跑 `cargo build` 看错误,错误码大约是 E0515。

### Lv3 · 迁移设计

**题**:你要写一个文本处理函数 `truncate`,把字符串截断到最多 n 个**字符**(不是字节),如果太长就加 "...". 思考:

1. 函数应该返回 `String` 还是 `&str`?为什么?
2. 参数应该用 `&str` 还是 `String`?为什么?
3. 边界:中文字符怎么处理?如果 n=3 但有 4 字节字符,怎么算?
4. 写出完整实现 + 测试

**提示**:
- `s.chars()` 给 Unicode 字符迭代器
- `s.chars().take(n).collect::<String>()` 截前 n 个字符
- 返回 String(因为可能要构造新的带 "..." 字符串)
- 参数 &str(通用)

### Lv4 · 开源贡献

**题**:很多 Rust crate 的"good first issue"是修 borrow checker 报的问题。

1. 在 GitHub 搜:`is:issue is:open label:"good first issue" language:Rust lifetime`
2. 找一个关于 lifetime 的 issue
3. 尝试本地复现
4. 修对(可能要加 lifetime annotation,或重构借用关系)
5. 写测试,跑 `cargo test`
6. 提 PR

或者更简单的:翻你常用 crate 的源码,看 `src/lib.rs` 里函数签名,选一个用 `&str` 的函数,看它的 lifetime annotation(很多是 `'_` 省略)。读懂为什么这么标注。

写下你研究的 crate / 文件 / 函数 / lifetime 标注的含义。

## 8 · Rust / Arch 落地代码

### 完整所有权示例

```rust
// src/main.rs
// 综合演示所有权 / 借用 / slice

use std::io;

// 1. 所有权转移
fn take_ownership(s: String) {
    println!("take_ownership got: {}", s);
}   // s 在这里 drop,内存释放

// 2. 借用(不可变)
fn borrow(s: &String) {
    println!("borrow got: {}", s);
}   // 借用结束,但 s 不被 drop

// 3. 借用(可变)
fn modify(s: &mut String) {
    s.push_str(" (modified)");
}

// 4. 返回所有权
fn give_back() -> String {
    let s = String::from("from give_back");
    s    // move 出去,不 drop
}

// 5. slice 参数(推荐用 &str 而非 &String)
fn first_word(s: &str) -> &str {
    match s.find(' ') {
        Some(idx) => &s[..idx],
        None => s,
    }
}

// 6. 多借用 vs 单 mut 借用
fn demonstrate_borrow_rules() {
    let mut data = String::from("hello");

    // 不可变借用开始
    let r1 = &data;
    let r2 = &data;
    println!("immutable borrows: {} {}", r1, r2);
    // 不可变借用到这里结束(NLL)

    // 可变借用,因为前面借用已结束,OK
    let r3 = &mut data;
    r3.push_str(" world");
    println!("after mutable borrow: {}", r3);
}

fn main() {
    // 所有权
    let s1 = String::from("hello");
    take_ownership(s1);
    // println!("{}", s1);  // 错:s1 已 move

    // 借用
    let s2 = String::from("hello");
    borrow(&s2);                          // 借用
    println!("still have: {}", s2);       // OK

    // 可变借用
    let mut s3 = String::from("hello");
    modify(&mut s3);
    println!("after modify: {}", s3);

    // 返回所有权
    let s4 = give_back();
    println!("got: {}", s4);

    // slice
    let sentence = "hello world foo bar";
    let word1 = first_word(sentence);     // &str 字面量自动借用
    println!("first word: {}", word1);

    let owned = String::from("from owned");
    let word2 = first_word(&owned);       // &String 自动 deref 到 &str
    println!("first word: {}", word2);

    // 借用规则演示
    demonstrate_borrow_rules();
}
```

跑起来:

```bash
cargo run
# 输出:
# take_ownership got: hello
# borrow got: hello
# still have: hello
# after modify: hello (modified)
# got: from give_back
# first word: hello
# first word: from
# immutable borrows: hello hello
# after mutable borrow: hello world
```

### 常见编译错误及修复

```bash
# 错误 E0382: use of moved value
# 代码:
#   let s = String::from("hi");
#   let t = s;
#   println!("{}", s);
# 修复 1:let t = s.clone();
# 修复 2:let t = &s;

# 错误 E0502: cannot borrow as mutable because already borrowed as immutable
# 代码:
#   let mut v = vec![1, 2];
#   let r = &v;
#   v.push(3);
#   println!("{}", r);
# 修复:println!("{}", r); 放到 push 前

# 错误 E0505: cannot move out of value because it is borrowed
# 类似 E0502 但更严重

# 错误 E0515: cannot return reference to local variable
# 代码:
#   fn bad() -> &String { let s = String::new(); &s }
# 修复:返回 String(owned)而不是 &String

# 错误 E0106: missing lifetime specifier
# 代码:
#   fn foo(x: &str) -> &str { ... }
# 编译器无法推断返回的引用基于哪个入参
# 修复:加 lifetime:fn foo<'a>(x: &'a str) -> &'a str
```

### 用 cargo-watch 自动重编译

```bash
cargo install cargo-watch   # 装
cargo watch -x run          # 文件改动自动 cargo run
cargo watch -x test         # 文件改动自动跑测试
cargo watch -x "check && clippy"  # 多命令
```

### 性能对比:C 风格 vs Rust 安全

```bash
# 装 perf(Arch)
sudo pacman -S perf

# 测试 Rust String 分配性能
cat > /tmp/bench_string.rs << 'EOF'
use std::time::Instant;

fn main() {
    let start = Instant::now();
    let mut total = 0usize;
    for _ in 0..1_000_000 {
        let s = String::from("hello world hello world hello world");
        total += s.len();
        // s 离开作用域自动 drop,等价 C 的 free
    }
    let elapsed = start.elapsed();
    println!("total: {}, elapsed: {:?}", total, elapsed);
}
EOF

rustc -O /tmp/bench_string.rs -o /tmp/bench_string
/tmp/bench_string
# 输出:total: 35000000, elapsed: 30ms 左右
# 对比:同等 C 代码也是这个量级
```

## 9 · 延伸阅读(可选补充,非必需)

本仓库本地:
- [03-rust-from-scratch-1.md](03-rust-from-scratch-1.md) — 基础(前置)
- [05-rust-from-scratch-3.md](05-rust-from-scratch-3.md) — struct / enum
- [06-rust-from-scratch-4.md](06-rust-from-scratch-4.md) — lifetime 深入 + 智能指针
- [11-reading-rustc-errors.md](11-reading-rustc-errors.md) — 读 borrow checker 报错

外部稳定 URL:
- The Rust Book Ch.4(本篇对应):https://doc.rust-lang.org/book/ch04-00-understanding-ownership.html
- Rust Reference - Ownership:https://doc.rust-lang.org/reference/ownership.html
- Rustonomicon(unsafe 和深层内存模型):https://doc.rust-lang.org/nomicon/
- "Learn Rust With Entirely Too Many Linked Lists"(链表地狱):https://rust-unofficial.github.io/too-many-lists/

真实开源源码:
- std String 实现:https://github.com/rust-lang/rust/blob/master/library/alloc/src/string.rs
- std Vec 实现:https://github.com/rust-lang/rust/blob/master/library/alloc/src/vec/mod.rs
- Polonius(下一代 borrow checker):https://github.com/rust-lang/polonius
