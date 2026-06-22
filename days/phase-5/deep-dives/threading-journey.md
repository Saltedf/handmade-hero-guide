---
phase: 5
title_en: "Threading Journey"
title_zh: "线程演化史:从 Mutex 到 lock-free"
type: deep-dive
domains: [game, rust, linux, system, concurrency]
bridges: ["phase-4", "phase-6"]
---

# 线程演化史:从 Mutex 到 lock-free

> 你跟着 HH Day 250 开始多线程。Casey 在 Win32 上 `CreateThread`,主线程跑游戏,worker 线程跑 asset 加载。一切顺利。然后你想加并行渲染——结果 race condition 让你的画面闪烁。你加 Mutex,性能掉一半。你换成 `Arc<Mutex<T>>`,frame time 从 16ms 变成 30ms。Casey 在视频里说"audio 线程绝不能等锁",你心里嘀咕"那其它线程就能?"。**这一篇把整个并发演化串起来**:从 pthread 到 futex,从 Mutex 到 lock-free,从 atomics 到 rayon,从 SPSC 到 work-stealing。看完你应该能写出真正不卡的游戏并发架构。

## 0 · 为什么要有这一篇

游戏并发是**最容易被新手搞砸**的子系统。原因有几个:

1. **多核是必须的**。2026 年的 CPU 都是 8-16 核。单线程游戏直接浪费 87.5%-93.75% 的算力。
2. **每帧时间预算严苛**。60 FPS = 16.67ms。任何线程同步开销超过 1ms 都很可疑。
3. **race condition 难 debug**。多线程 bug 在 release build 出现,debug build 消失。开发者本地不复现,玩家机器天天崩。
4. **错误的抽象代价巨大**。从 Mutex 重构成 lock-free 不是"换个数据结构"——是"重写整个并发架构"。
5. **Send / Sync / lifetime 概念门槛高**。Rust 在这里救了你,但你要先理解它救的是什么。

Casey 在 HH 上对并发的处理是**保守**的:音频走 SPSC ring,asset loading 走 worker 线程 + job queue,渲染保持单线程。这是务实的工业实践。但工业级游戏引擎(Unreal、Unity DOTS、Bevy ECS)走得更远——ECS + work-stealing + system scheduling。

这一篇把整个 spectrum 摊开:

**读完这一篇,你应该能**:
- 解释 `Ordering::Relaxed`、`Acquire`、`Release`、`SeqCst` 的区别
- 在 Mutex / RwLock / lock-free 之间做正确选择
- 实现 SPSC ring buffer 并理解它和 MPSC 的区别
- 用 rayon 做 work-stealing parallel reduce
- 诊断 false sharing 并修复
- 解释 pthread_mutex 和 futex 的关系
- 设计游戏的并发架构(主线程 + worker pool + audio thread)

## 1 · atomics 和 Ordering:Rust 的原子基础

### 1.1 atomic 是什么

普通变量读写不是原子的。`x += 1` 在汇编层是 3 条指令:`load x → inc → store x`。两个线程同时 `x += 1`,可能出现:

```
Thread A:  load x (=5)
Thread B:  load x (=5)
Thread A:  inc (x=6)
Thread B:  inc (x=6)
Thread A:  store x (=6)
Thread B:  store x (=6)
```

应该 +2,实际 +1。这就是 **data race**。

`std::sync::atomic` 提供原子类型:`AtomicU32`、`AtomicBool`、`AtomicUsize` 等。它们的 `load` / `store` / `fetch_add` 等方法在汇编层是单条指令(`lock incl` 等),保证原子性。

```rust
use std::sync::atomic::{AtomicU32, Ordering};

let counter = AtomicU32::new(0);
// 多个线程同时调这个不会丢更新
counter.fetch_add(1, Ordering::Relaxed);
```

### 1.2 Ordering:Rust 给你的精度旋钮

Rust 的 atomic 操作都带一个 `Ordering` 参数。这是个**编译器/CPU 重排约束**的旋钮。从弱到强:

- **`Relaxed`**:只保证当前操作原子,**不**约束其它读写顺序。
- **`Release`**(store 用):之前的内存在这次 store 之前完成。
- **`Acquire`**(load 用):之后的内存在这次 load 之后开始。
- **`AcqRel`**(read-modify-write 用):同时是 Acquire + Release。
- **`SeqCst`**:全序,所有 SeqCst 操作有一个全局顺序。最强,最贵。

#### 1.2.1 为什么需要 Ordering

CPU 和编译器都会**重排**指令以提升性能。比如:

```rust
let data = 0;
let ready = false;
// Thread A
data = 42;
ready = true;
// Thread B
if ready { println!("{}", data); }
```

逻辑上 Thread B 看到 `ready = true` 时 `data` 必然是 42。但 CPU 可能重排 `data = 42` 和 `ready = true`,导致 Thread B 看到 `ready = true` 但 `data = 0`。

用 atomic + Release/Acquire 阻止重排:

```rust
let data = AtomicU32::new(0);
let ready = AtomicBool::new(false);
// Thread A
data.store(42, Ordering::Relaxed);
ready.store(true, Ordering::Release);  // 之前的 store 对 Thread B 可见
// Thread B
if ready.load(Ordering::Acquire) {
    println!("{}", data.load(Ordering::Relaxed));  // 必然看到 42
}
```

`Release` store 保证:之前所有内存写入在 store 前完成。`Acquire` load 保证:之后所有读取在 load 后开始。两者配对,你看到 ready=true 时,一定看到 data=42。

#### 1.2.2 实际选择

| 场景 | Ordering | 原因 |
|---|---|---|
| 引用计数 | Relaxed | 只关心计数本身 |
| 计数器 | Relaxed | 不依赖顺序 |
| mutex unlock | Release | 临界区内的写要可见 |
| mutex lock | Acquire | 看到上次 Release 的写 |
| spin lock | Acquire / Release | 同 mutex |
| 一次性初始化 flag | Acquire / Release | 初始化内容要可见 |
| 跨线程信号 | SeqCst | 全局顺序重要 |

**经验法则**:用最弱的 Ordering 能工作的就用最弱的。90% 场景是 Relaxed 或 Release/Acquire。**几乎不需要 SeqCst**。

### 1.3 用 SeqCst 的代价

`SeqCst` 不是免费的。x86 上,`SeqCst` store 是 `mfence` 或 `lock` 前缀指令,几十 cycle。`Relaxed` store 是普通 `mov`,1 cycle。差距 20-50 倍。

ARM 上更明显:`Relaxed` 是 `str`,`SeqCst` 是 `stlr` + `dmb ish`,几十到几百 cycle。

实际测试(我的 Ryzen 7):

```
AtomicU32::store(n, Relaxed):   0.3 ns/op
AtomicU32::store(n, Release):   0.3 ns/op    (x86 Release store 不需要 fence)
AtomicU32::store(n, SeqCst):    13 ns/op    (需要 mfence)
```

ARM 差距更大。**不要无脑 SeqCst**。

## 2 · Mutex vs lock-free

### 2.1 Mutex 是什么

`Mutex<T>` 是 Rust 标准库提供的互斥锁。它保证同一时刻只有一个线程能 access T。

```rust
use std::sync::Mutex;

let data = Mutex::new(vec![1, 2, 3]);
{
    let mut guard = data.lock().unwrap();
    guard.push(4);
}  // guard drop 时 unlock
```

底层实现:x86 上用 `pthread_mutex_t`(POSIX),内部用 futex(fast userspace mutex,Linux 系统调用)。futex 在无竞争时纯用户态 CAS,纳秒级;有竞争时 syscall 让出 CPU,微秒到毫秒级。

### 2.2 Mutex 的代价

无竞争:`lock` + `unlock` 大约 20-30 ns。
有竞争:每次切换 1-10 μs。
**优先级反转**:高优先级线程等低优先级线程的锁,低优先级被中优先级抢占,高优先级被无限延迟。这是 Mars Pathfinder 1997 著名 bug 的根因。

游戏里 Mutex 的真实代价不是 lock 本身,而是 **contention**。10 个线程抢一个锁,9 个线程阻塞,你的 8 核 CPU 利用率瞬间从 800% 跌到 100%。

### 2.3 RwLock:读多写少的替代

`RwLock<T>`(read-write lock)允许多个读者同时持有,但写者独占。适合"配置很少变,但读很频繁"的场景。

```rust
use std::sync::RwLock;

let config = RwLock::new(Config::default());
{
    let r = config.read().unwrap();  // 多个线程可以同时 read
    println!("{}", r.value);
}
{
    let mut w = config.write().unwrap();  // 独占
    w.value = 42;
}
```

代价:`RwLock` 比 `Mutex` 复杂(需要跟踪读者数量),开销略大。但读多场景下吞吐量高得多。

Rust 的 `RwLock` 在 Linux 上默认用 `pthread_rwlock_t`,有 writer starvation 问题(写者等不到锁)。`parking_lot::RwLock` 公平性更好,推荐。

### 2.4 lock-free:不要锁

`lock-free` 数据结构不用 mutex,直接用 atomic 操作。**至少有一个线程**总在前进(不会所有线程都阻塞)。

```rust
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;

pub struct LockFreeCounter {
    value: AtomicUsize,
}

impl LockFreeCounter {
    pub fn inc(&self) {
        self.value.fetch_add(1, Ordering::Relaxed);
    }
    pub fn get(&self) -> usize {
        self.value.load(Ordering::Relaxed)
    }
}
```

`fetch_add` 是 atomic,不需要锁。多线程同时 `inc`,不阻塞。

**lock-free ≠ wait-free**:
- lock-free:至少一个线程在前进,某些线程可能饿死
- wait-free:每个操作在有限步内完成,无饿死

`fetch_add` 是 wait-free(每条指令完成)。CAS 循环是 lock-free(失败重试,但某线程成功)。

### 2.5 什么时候用 lock-free

| 场景 | 推荐 | 原因 |
|---|---|---|
| 简单计数器 | atomic | 比 Mutex 快 100 倍 |
| 标志位(flag) | atomic | 同上 |
| SPSC 队列(audio) | lock-free SPSC ring | Mutex 在 audio thread 是禁忌 |
| 配置读多写少 | RwLock | 公平性好 |
| 通用数据结构 | Mutex | lock-free 实现复杂,容易出 bug |
| 跨线程共享资源 | Mutex | 错误少 |

**反模式**:看到 Mutex 就改成 lock-free。**这是错的**。Mutex 在低竞争场景下足够快,而 lock-free 代码很容易写出隐蔽的 bug(ABA、memory ordering)。**先用 Mutex,profile,有证据了再换**。

## 3 · SPSC ring buffer:audio 标准答案

游戏里典型的跨线程通信是 **audio**:主线程产生命令,audio thread 消费。**只有一个生产者** + **只有一个消费者**——这个约束让 SPSC ring 可以 100% lock-free。

实现要点(完整代码见 [audio-pipeline-complete.md](audio-pipeline-complete.md)):

- 容量是 2^n,`% capacity` 变 `& mask`,一条 AND 指令。
- `write_pos` / `read_pos` 用 `AtomicUsize`,单调递增。
- 写者 store 用 Release,读者 load 用 Acquire,保证 buf 写入可见。
- 无 Mutex、无 CAS,纯 atomic load/store。

Rust 标准库的 `std::sync::mpsc` 是 MPSC,基于 CAS,性能比 SPSC 慢 5-10 倍。如果场景是 SPSC,**不要用 mpsc**——直接用 `crossbeam_queue::ArrayQueue` 或自己实现。

### 3.1 实战:audio 命令队列

```rust
pub enum AudioCommand {
    PlaySound { idx: usize, volume: f32, pan: f32 },
    StopSound(usize),
    SetMasterVolume(f32),
}

pub struct AudioBridge {
    command_queue: Arc<SpscRing<AudioCommand>>,
    finished_queue: Arc<SpscRing<FinishedEvent>>,
}
```

主线程 push 命令,audio thread pop 处理。两个方向的 SPSC ring 解决双向通信。**命令 enum 大小要小(<= 32 字节)**,太大时 box 起来传 Arc。

## 4 · Work stealing:rayon 的秘密

### 4.1 job queue 的问题

游戏想做并行 asset 加载。朴素方案:一个全局 job queue,worker 线程从 queue 取 job 执行。

```rust
let queue = Arc::new(Mutex::new(VecDeque::<Job>::new()));

// worker
let q = queue.clone();
thread::spawn(move || {
    while let Some(job) = q.lock().unwrap().pop_front() {
        job.run();
    }
});
```

问题:**queue 是 contention 点**。8 个 worker 抢一个 queue,锁竞争极重。

### 4.2 每 worker 一个队列

改进:每个 worker 一个本地队列。worker 从自己队列取 job,无 contention。

```
Worker 0: [job, job, job]
Worker 1: []  ← 空了
Worker 2: [job]
Worker 3: [job, job, job, job, job, job]
```

但问题:负载不均。Worker 1 空了,Worker 3 还有 6 个 job。

### 4.3 Work stealing

**Work stealing**(任务窃取):worker 队列空了,**从别人尾部偷**。

```
Worker 1: ← steals from Worker 3 (尾部)
Worker 3: [job, job, job, job, job, job]
                       ↑ Worker 3 自己从这里取(头部)
```

为什么偷尾部、自己取头部?**减少冲突**。两端操作,很少同时撞上。

### 4.4 rayon:Rust 的 work-stealing 库

`rayon` 是 Rust 生态的并行计算库,基于 work-stealing。

```rust
use rayon::prelude::*;

fn main() {
    let v: Vec<u32> = (0..1000000).collect();
    let sum: u32 = v.par_iter().map(|&x| x * 2).sum();
    println!("sum = {}", sum);
}
```

`par_iter()` 把迭代器变成并行。rayon 内部把工作切分给 worker pool,worker 之间用 work-stealing 平衡。

性能对比(1M items,map + sum):

```
单线程:          8 ms
rayon (8 核):   1.2 ms   (~6.5x speedup)
```

接近线性加速。剩下的 1.5x 是 work-stealing 开销 + atomic 操作。

### 4.5 rayon 在游戏里

游戏 asset loading 经典用法:

```rust
use rayon::prelude::*;

let textures: Vec<Texture> = paths.par_iter()
    .map(|p| load_texture(p))
    .collect();
```

1000 个纹理文件并行 load,在 8 核 CPU 上接近 8 倍加速。

**rayon 不适合的场景**:
- 单帧很短的任务(rayon 启动 thread pool 有几十 μs 开销)
- 共享可变状态(rayon 不能容易地传 `&mut T` 到多个 task)
- 实时音频(callback 内不能用 rayon)

## 5 · False sharing:并发的隐形杀手

### 5.1 什么是 false sharing

CPU cache 是按 cache line 组织的,典型 64 字节。**两个变量在同一个 cache line 上,即使逻辑上不相关,从不同 CPU core 访问它们会导致 cache invalidation**——这叫 **false sharing**。

```rust
struct Counters {
    a: AtomicU64,
    b: AtomicU64,  // 和 a 在同一 cache line!
}
```

Thread A 在 core 0 反复 inc `a`。Thread B 在 core 1 反复 inc `b`。每次 A 写 `a`,cache line 被 invalidate,B core 必须重新加载——**即使 B 完全不读 `a`**。

### 5.2 修复:padding

```rust
#[repr(C)]
struct Counters {
    a: AtomicU64,
    pad1: [u8; 56],  // 填到 64 字节
    b: AtomicU64,
    pad2: [u8; 56],
}
```

`a` 和 `b` 现在在不同 cache line,无 false sharing。

Rust 的 `crossbeam_utils::CachePadded` 自动做这件事:

```rust
use crossbeam_utils::CachePadded;

struct Counters {
    a: CachePadded<AtomicU64>,
    b: CachePadded<AtomicU64>,
}
```

`CachePadded<T>` 内部 pad T 到 cache line 大小(64 或 128)。

### 5.3 性能对比

测试:两个线程分别 inc 一个 AtomicU64,1 亿次。

```
无 padding(同 cache line):  3.5 s
有 padding(不同 cache line): 0.6 s   (~6x)
```

false sharing 让你损失 6 倍性能。**这是真实的生产 bug**——很多 lock-free 数据结构不加 padding 性能不如 Mutex。

## 6 · Send 和 Sync:Rust 的并发安全护城河

### 6.1 定义

`Send`:类型可以**安全地跨线程转移所有权**(move)。
`Sync`:类型可以**安全地跨线程共享引用**(`&T`)。

```rust
// Send 意味着 T: Send 时,可以 send 到另一个线程
// 等价于 &T 可以给另一个线程使用

// 内部定义(标准库源码)
pub unsafe auto trait Send {}
pub unsafe auto trait Sync {}
```

这两个是 **marker trait**(空 trait),只能由编译器自动 derive(unstable),或 unsafe impl 手动。

### 6.2 哪些类型是 Send / Sync

- `i32`, `f32`, `bool` 等:Send + Sync(纯数据)
- `&T` where T: Sync:Send(共享引用可 send)
- `&mut T` where T: Send:Send(可变引用需要 T: Send)
- `Box<T>` where T: Send:Send
- `Arc<T>` where T: Send + Sync:Send + Sync
- `Rc<T>`:**不** Send **不** Sync(引用计数非原子)
- `Cell<T>`, `RefCell<T>`:**不** Sync(内部可变,非线程安全)
- `Mutex<T>` where T: Send:Send + Sync
- `AtomicU32` 等:Send + Sync

### 6.3 为什么 Rc 不 Send

`Rc<T>` 用非原子计数。两个线程同时 clone Rc,计数会丢更新,然后 double-free。所以 Rust 编译期禁止 Rc 跨线程。

如果你想跨线程共享,用 `Arc<T>`(Atomic Reference Counted)。Arc 的引用计数是 atomic,多线程 clone 安全。

```rust
let rc = Rc::new(42);
let rc2 = rc.clone();
thread::spawn(move || {  // 编译错误:Rc 不 Send
    println!("{}", rc2);
});

let arc = Arc::new(42);
let arc2 = arc.clone();
thread::spawn(move || {  // OK
    println!("{}", arc2);
});
```

**性能代价**:Arc clone 比 Rc clone 慢 5-10 倍(atomic add vs add)。**单线程不要用 Arc**。

### 6.4 unsafe impl Send / Sync:什么时候用

你自己实现 lock-free 数据结构时,编译器不知道你的实现是否线程安全。你需要 `unsafe impl Send` / `unsafe impl Sync`:

```rust
pub struct SpscRing<T> {
    buf: Box<[UnsafeCell<T>]>,
    // ...
}

// UnsafeCell 不是 Sync,所以 SpscRing 默认不是 Sync
// 但我们的实现是线程安全的(SPSC),所以手动 impl
unsafe impl<T: Send> Send for SpscRing<T> {}
unsafe impl<T: Send> Sync for SpscRing<T> {}
```

**unsafe 含义**:你承诺这个实现是线程安全的。错了就是 UB(未定义行为)。

## 7 · pthread 和 futex:Linux 线程底层

### 7.1 pthread:POSIX 线程

Linux 用户态线程 API 是 `pthread`(POSIX thread)。`pthread_create` 创建线程,`pthread_mutex_lock` 加锁,`pthread_join` 等待。

Rust 标准库的 `std::thread::spawn` 在 Linux 上调 `pthread_create`。`std::sync::Mutex` 在 Linux 上用 `pthread_mutex_t`(默认)或 futex(nightly 的实现)。

```bash
# 看进程的线程
ps -T -p <pid>
# 或
htop,然后 H 切换线程视图

# 看线程调度策略
chrt -p <tid>

# 设线程优先级(需要权限)
chrt -f -p 80 <tid>   # SCHED_FIFO,优先级 80
```

### 7.2 futex:Linux 的 fast mutex

`pthread_mutex` 在 Linux 上实现基于 **futex**(fast userspace mutex)。futex 系统调用:

```c
int futex(int *uaddr, int op, int val, ...);
```

`uaddr` 是用户态 atomic int。futex 操作有:
- `FUTEX_WAIT`:如果 `*uaddr == val`,把当前线程 park(挂起)
- `FUTEX_WAKE`:唤醒 `uaddr` 上等待的线程

mutex 实现简化版:

```c
void mutex_lock(int *m) {
    while (1) {
        if (atomic_cmpxchg(m, 0, 1) == 0) return;  // 拿到了
        // 没拿到,wait
        futex(m, FUTEX_WAIT, 1);  // 如果 *m == 1,挂起
    }
}

void mutex_unlock(int *m) {
    atomic_store(m, 0);
    futex(m, FUTEX_WAKE, 1);  // 唤醒一个 waiter
}
```

**无竞争时**:纯用户态 CAS,纳秒级。
**有竞争时**:futex syscall,微秒级。

Rust 的 `parking_lot::Mutex` 比 `std::sync::Mutex` 更快,因为它不用 pthread,直接实现 futex-based mutex。**生产推荐 parking_lot**。

### 7.3 线程优先级

Linux 调度策略:

- `SCHED_OTHER`:默认,普通进程
- `SCHED_FIFO`:实时,先到先得,不时间片
- `SCHED_RR`:实时,round-robin 带时间片

audio thread 通常要 `SCHED_FIFO` 优先级 80+:

```rust
use libc::*;

unsafe fn set_realtime_priority() {
    let param: sched_param = sched_param { sched_priority: 80 };
    sched_setscheduler(0, SCHED_FIFO, &param);
}
```

但需要 `CAP_SYS_NICE` 能力。普通用户做不到。PipeWire / PulseAudio 通过 systemd 给自己这能力。

## 8 · 游戏并发架构设计

### 8.1 三层架构

工业级游戏并发大致是这个结构:

```
+------------------------------------------+
| Main thread (game logic)                 |
+------------------------------------------+
| Worker pool (asset loading, rayon)       |
+------------------------------------------+
| Audio thread (real-time, SCHED_FIFO)     |
+------------------------------------------+
| Render thread (Vulkan / OpenGL)          |
+------------------------------------------+
| IO thread (file, network)                |
+------------------------------------------+
```

每层职责:
- **Main**:跑游戏循环、输入、AI、物理
- **Worker**:并发跑 asset load、rayon 并行 reduce、烘焙
- **Audio**:audio callback,绝对 lock-free
- **Render**:Vulkan/OpenGL command buffer 生成
- **IO**:磁盘、网络,async 或 thread pool

线程间通信用 SPSC ring 或 lock-free queue。

### 8.2 frame graph

现代引擎(Bevy、Unreal)用 **frame graph** 概念:每帧把工作切分成多个 "system",引擎决定哪些 system 可以并行。

```rust
// Bevy 风格
app.add_systems(Update, (
    player_movement,
    enemy_ai,
    physics_step,
).chain());  // 串行

app.add_systems(Update, (
    update_health,
    update_position,
    update_animation,
));  // 并行(Bevy 自动分析依赖)
```

Bevy 用 ECS 的"组件访问模式"做并行调度:如果两个 system 都不写同一个 component,它们可以并行。

### 8.3 数据并行 vs 任务并行

**数据并行**:同一操作作用在大量数据上。GPU shader、SIMD、rayon。
**任务并行**:不同操作并行执行。Worker pool + job queue。

游戏里两者都用。粒子是数据并行(每个粒子独立 update)。Asset loading 是任务并行(每个 asset 独立 load)。

**选错类型代价大**。把 asset loading(任务)用 rayon 跑没问题,但把粒子 update(data parallel)用 job queue + per-particle job 就太慢——job 启动开销远大于粒子 update 本身。

## 9 · 完整 Rust 例子

下面是三层并发架构的最小骨架。完整代码:`cpal` + `crossbeam-queue` + `rayon` + `parking_lot`。

```rust
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use crossbeam_queue::ArrayQueue;
use rayon::prelude::*;

pub struct AudioCommand { pub freq: f32, pub duration_ms: u32 }

fn main() {
    rayon::ThreadPoolBuilder::new().num_threads(4).build_global().unwrap();

    let queue = Arc::new(ArrayQueue::<AudioCommand>::new(256));
    let running = Arc::new(AtomicBool::new(true));

    // Audio thread — SPSC 命令队列,实时
    let (q, r) = (queue.clone(), running.clone());
    thread::spawn(move || {
        let host = cpal::default_host();
        let dev = host.default_output_device().unwrap();
        let cfg: cpal::StreamConfig = dev.default_output_config().unwrap().into();
        let sr = cfg.sample_rate.0 as f32;
        let (mut phase, mut freq, mut rem) = (0.0f32, 0.0f32, 0u32);
        let stream = dev.build_output_stream(
            &cfg,
            move |out: &mut [f32], _: &_| {
                while let Some(c) = q.pop() { freq = c.freq; rem = c.duration_ms * (sr as u32) / 1000; }
                for frame in out.chunks_mut(cfg.channels as usize) {
                    if rem > 0 {
                        phase += freq / sr * 2.0 * std::f32::consts::PI;
                        if phase > 2.0 * std::f32::consts::PI { phase -= 2.0 * std::f32::consts::PI; }
                        let v = phase.sin() * 0.2;
                        frame.iter_mut().for_each(|s| *s = v);
                        rem = rem.saturating_sub(1);
                    } else {
                        frame.iter_mut().for_each(|s| *s = 0.0);
                    }
                }
            },
            |err| eprintln!("{:?}", err), None,
        ).unwrap();
        stream.play().unwrap();
        while r.load(Ordering::Relaxed) { thread::sleep(std::time::Duration::from_millis(100)); }
    });

    // 主循环:60 FPS,30 秒。每秒触发一个 audio 命令,rayon 并行 reduce
    for frame in 0..1800 {
        if frame % 60 == 0 {
            let _ = queue.push(AudioCommand { freq: 220.0 + frame as f32 * 0.5, duration_ms: 100 });
        }
        let work: Vec<u32> = (0..10000).collect();
        let _sum: u32 = work.par_iter().map(|&x| x.wrapping_mul(7)).sum();
        thread::sleep(std::time::Duration::from_millis(16));
    }
    running.store(false, Ordering::Relaxed);
}
```

跑一下。听到每秒一个不同音高的"嘟"声,同时 CPU 多核在跑 rayon work。

## 10 · 历史演化

并发的演化是软件工程的缩影:

- **1960s** mutex / semaphore(Dijkstra)。理论奠基。
- **1970s** monitor(Hoare),Java 后来的 `synchronized` 基于此。
- **1980s** POSIX threads(pthread)。
- **1990s** Java JVM 内存模型(第一版有 bug,2004 修正)。
- **2000s** lock-free 数据结构(Michael-Scott queue 等)。C++11 atomic。
- **2010s** Rust 1.0(2015)用类型系统保证并发安全。C++11 memory model。
- **2020s** async Rust / tokio 成熟。rayon / crossbeam 成为标准。Linux io_uring。

游戏并发的演化:

- **2000s** 单线程为主,简单 worker thread。
- **2010s** job system( Naughty Dog GDC 2012 talk 是经典)。Unity / Unreal 引入。
- **2020s** ECS + system scheduler。Bevy、Unity DOTS、Unreal Mass Entity。

每一步都是为了榨干摩尔定律带来的额外核心。**单线程优化时代结束了**,理解并发是 2026 年程序员的必备技能。

## 11 · 跨阶段回顾

| 阶段 | 主题 | HH 出现日 |
|---|---|---|
| Phase 4 | 第一次多线程 | day250+ |
| Phase 5 | audio 线程 + lock-free | day201+ |
| Phase 6 | ECS + system 调度 | day400+ |
| 本深入 | 完整 spectrum | — |

**关联 Day**:
- 铺垫:[phase-4](../phase-4/) — HH 第一次多线程;[phase-3/deep-dives/simd-progression.md](../phase-3/deep-dives/simd-progression.md) — 数据并行
- 当天:本深入
- 后续:[phase-6](../phase-6/) — ECS + system 调度;[deep-dives/audio-pipeline-complete.md](audio-pipeline-complete.md) — audio thread 实战;[deep-dives/collision-evolution.md](collision-evolution.md) — BVH 并行构建

## 12 · 延伸阅读

本仓库本地资料:
- [phase-4](../phase-4/) — HH 多线程初探
- [phase-5/day250.md](day250.md) — threading 基础
- [phase-5/deep-dives/audio-pipeline-complete.md](audio-pipeline-complete.md) — audio callback 实战

外部稳定 URL:
- Mara Bos 的 Rust Atomics and Locks(必读):https://marabos.nl/atomics/
- crossbeam 文档:https://docs.rs/crossbeam/
- rayon 文档:https://docs.rs/rayon/
- Paul McKenney "Is Parallel Programming Hard":https://kernel.org/pub/linux/kernel/people/paulmck/perfbook/perfbook.html
- Rustonomicon 关于 Send/Sync:https://doc.rust-lang.org/nomicon/send-and-sync.html
- parking_lot 文档:https://docs.rs/parking_lot/
- Linux futex man page:`man 2 futex`
- "Left-Right" concurrency pattern(用于读多写少):https://hal.inria.fr/hal-00984069

真实开源源码:
- crossbeam 源码(学习 lock-free 实现的宝藏):https://github.com/crossbeam-rs/crossbeam
- rayon 源码:https://github.com/rayon-rs/rayon
- Bevy ECS 调度器:https://github.com/bevyengine/bevy/tree/main/crates/bevy_ecs
- Naughty Dog GDC 2012 talk "Parallelizing the Naughty Dog Engine":https://www.gdcvault.com/
