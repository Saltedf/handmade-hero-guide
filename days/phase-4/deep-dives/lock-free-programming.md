---
title: "Lock-Free Programming"
subtitle: "Atomics, Ordering, ABA problem, crossbeam"
type: deep-dive
phase: 4
domains: [rust, linux]
duration: "2-3h"
---

# Lock-Free Programming

> Phase 4 多处涉及多线程(Day 122-125 work queue、Day 141 音频流式、Day 165-166 asset 系统加锁)。这篇 deep-dive 把 lock-free 编程完整讲:atomic 操作、Ordering 语义、ABA 问题、crossbeam 的实用模式。读完后你能写正确的 lock-free 数据结构,且知道**何时不该写**(用现成 crate)。

## 0 · 为什么需要 lock-free

`Mutex` / `RwLock` 的问题:

1. **阻塞**:线程等锁时 sleep,内核切换上下文(~1-10 μs)
2. **死锁**:多锁顺序错可能死锁
3. **优先级反转**:高优先级等低优先级持锁,实时性差
4. **contention**:多核抢锁,CPU 浪费在 lock/unlock

lock-free 用 **原子操作**(atomic)代替锁,线程不阻塞,等时 spin。性能 5-10x 提升(SPSC 场景)。

但 lock-free **更难写对**。错误数据竞争 = UB。这篇教你正确写。

## 1 · 原子操作

`std::sync::atomic` 提供原子类型:

- `AtomicBool`
- `AtomicI32` / `AtomicU32` / `AtomicI64` / `AtomicU64`
- `AtomicUsize`
- `AtomicPtr<T>`

每个的方法:

```rust
let a = AtomicU32::new(0);

a.store(5, Ordering::Relaxed);             // 写
let v = a.load(Ordering::Acquire);         // 读
let old = a.swap(10, Ordering::SeqCst);    // 交换(返旧值)
let (old, _) = a.fetch_add(1, Ordering::Relaxed);  // 自增
let ok = a.compare_exchange(10, 20, Ordering::Acquire, Ordering::Relaxed).is_ok();
// CAS:如果当前是 10,换成 20
```

关键:**原子操作不可分割**——多线程同时 fetch_add 不会丢失。

硬件实现:x86 `LOCK` 前缀(`lock incl`)、ARM `LDXR/STXR`(独占加载 / 存储)。

## 2 · Ordering 解释

Ordering 是 atomic 操作的"内存可见性"约定。Rust 提供 5 种:

### Relaxed

最弱保证。只保证**原子性**(不会撕裂),不保证跨线程可见顺序。

```rust
static COUNTER: AtomicU64 = AtomicU64::new(0);
// 多线程 fetch_add(_, Relaxed):最终值正确,但每线程看不到对方的中间值
```

适合**统计计数**(不关心顺序,只关心最终值)。

### Release / Acquire

**Release** 写 + **Acquire** 读 配对。Acquire 之后的代码看到 Release 之前的所有写入。

```rust
// 线程 1
DATA.write(42);                              // 普通写
READY.store(true, Ordering::Release);       // Release

// 线程 2
while !READY.load(Ordering::Acquire) {}    // Acquire
assert_eq!(DATA.read(), 42);                // 保证看到
```

这是 SPSC 队列 / publisher-subscriber 的核心模式。

### AcqRel

`AcqRel` = `Acquire` + `Release`,用在 RMW(read-modify-write)操作(`fetch_add` / `compare_exchange`)。

### SeqCst

顺序一致性,最强。所有 SeqCst 操作有一个全局顺序。最贵(性能差)。

```rust
a.store(1, Ordering::SeqCst);
b.store(2, Ordering::SeqCst);
// 全局所有线程看到同样的顺序
```

适合**需要全局顺序**的算法(简单的 mutex 实现用 SeqCst)。

### Ordering 选择

| Ordering | 何时用 |
|---|---|
| Relaxed | 计数器,无关顺序 |
| Release / Acquire | SPSC 数据传递 |
| AcqRel | RMW(如 fetch_add) |
| SeqCst | 简单情况,不确定就用 |

## 3 · SPSC 队列(无锁单生产单消费)

最简单的 lock-free 数据结构:

```rust
use std::sync::atomic::{AtomicUsize, Ordering};

const SIZE: usize = 1024;
struct SpscQueue<T: Copy> {
    buffer: Box<[T; SIZE]>,  // 或 Vec 掩码版
    head: AtomicUsize,        // 消费者读
    tail: AtomicUsize,        // 生产者写
}

impl<T: Copy + Default> SpscQueue<T> {
    fn new() -> Self {
        Self {
            buffer: Box::new([Default::default(); SIZE]),
            head: AtomicUsize::new(0),
            tail: AtomicUsize::new(0),
        }
    }

    fn push(&self, v: T) -> bool {
        let tail = self.tail.load(Ordering::Relaxed);
        let head = self.head.load(Ordering::Acquire);
        if tail - head >= SIZE {
            return false;  // 满
        }
        self.buffer[tail % SIZE] = v;
        self.tail.store(tail + 1, Ordering::Release);
        true
    }

    fn pop(&self) -> Option<T> {
        let head = self.head.load(Ordering::Relaxed);
        let tail = self.tail.load(Ordering::Acquire);
        if head == tail {
            return None;  // 空
        }
        let v = self.buffer[head % SIZE];
        self.head.store(head + 1, Ordering::Release);
        Some(v)
    }
}
```

**关键点**:

- `head` 只消费者写,`tail` 只生产者写
- `Acquire` 读对方的 index,**保证**对应的 buffer 写入已可见
- `Release` 写自己的 index,**保证**之前的 buffer 写入对未来 Acquire 可见

工业实现见 `crossbeam-queue` 或 `ringbuf` crate。

## 4 · ABA 问题

经典 lock-free 陷阱。考虑 lock-free stack:

```rust
struct Node<T> { data: T, next: *mut Node<T> }
struct Stack<T> { head: AtomicPtr<Node<T>> }

fn pop<T>(s: &Stack<T>) -> Option<T> {
    loop {
        let head = s.head.load(Ordering::Acquire);
        if head.is_null() { return None; }
        let next = unsafe { (*head).next };
        // CAS head → next
        if s.head.compare_exchange(head, next, Ordering::Release, Ordering::Relaxed).is_ok() {
            return Some(unsafe { Box::from_raw(head) }.data);
        }
    }
}
```

ABA 场景:

1. 线程 A 读 head = X,读 next = Y
2. 线程 B pop X,pop Y,push X(数据变了但 X 指针重用)
3. 线程 A CAS head X → Y,**成功**(因为 head 还是 X)
4. 但 next Y 已被释放!Use-after-free

解决:

- **Tagged pointer**:指针高位放 counter,CAS 时 counter 也变
- **Hazard pointer**:线程公布"我在用这个指针",其他线程释放时检查
- **Epoch-based reclamation**:批量延迟释放
- **Use-after-free 不存在(Rust ownership)**:但 unsafe 实现仍有风险

`crossbeam-epoch` crate 实现 epoch-based reclamation,推荐用而非自己造。

## 5 · crossbeam crate 全家桶

`crossbeam` 是 Rust lock-free 标准库:

- `crossbeam-queue`:ArrayQueue / SegQueue(MPMC)
- `crossbeam-channel`:MPMC channel(比 std::sync::mpsc 快)
- `crossbeam-deque`:work-stealing deque
- `crossbeam-skiplist`:lock-free sorted map
- `crossbeam-epoch`:epoch-based GC(写自己的 lock-free 数据结构用)
- `crossbeam-utils`:CachePadded / AtomicCell

### 使用示例:ArrayQueue

```rust
use crossbeam_queue::ArrayQueue;

let q = ArrayQueue::new(100);
q.push(42).unwrap();
let v = q.pop().unwrap();
```

线程安全 MPMC,无锁。

### crossbeam-channel

```rust
use crossbeam_channel::unbounded;

let (s, r) = unbounded();
thread::spawn(move || {
    for i in 0..1000 {
        s.send(i).unwrap();
    }
});
for _ in 0..1000 {
    let v = r.recv().unwrap();
}
```

比 `std::sync::mpsc` 快 5-10x。

## 6 · 工作窃取(work-stealing)deque

rayon 用的模型:

- 每个线程有自己的 deque(LIFO)
- 空闲线程从别人 deque 末尾"偷"任务(FIFO)
- 减少锁竞争

```rust
use crossbeam_deque::{Worker, Stealer};

let worker = Worker::new_fifo();
let stealer = worker.stealer();

// 在 worker 线程
worker.push(task);
let t = worker.pop();

// 在别的线程
let stolen = stealer.steal();
```

rayon 用这套实现并行迭代器(`par_iter`)。

## 7 · lock-free 何时**不**该用

| 情况 | 推荐 |
|---|---|
| 简单共享 | Mutex |
| 多读少写 | RwLock |
| 单值计数 | AtomicU32 |
| SPSC 数据流 | crossbeam-channel 或 ringbuf |
| MPMC 任务 | rayon / crossbeam-deque |
| 复杂数据结构 | 标准库 + 锁,不要自己写 lock-free |

**自己写 lock-free 数据结构 = 给自己挖坑**。99% 场景用现成 crate。

## 8 · Rust 内存模型

Rust 1.x 内存模型**未完全规范**(C11 风格但 Rust 还在 formalize)。当前规则:

- atomic 操作 + Ordering 提供跨线程保证
- UnsafeCell 是单线程内部可变性
- 数据竞争(race condition)是 UB,但 Rust Send/Sync 防

实践中**遵循 C11 模型**(Acquire / Release / SeqCst 一致),编译器和硬件都正确实现。

## 9 · 调试 lock-free

- **ThreadSanitizer**:检测数据竞争
- **Loom**(Rust):模型检查并发代码
- **Shuttle**(Rust):随机化并发测试

```bash
# TSan
RUSTFLAGS="-Zsanitizer=thread" cargo +nightly test
```

loom 示例:

```rust
#[test]
fn loom_test() {
    loom::model(|| {
        let q = Arc::new(SpscQueue::new());
        // 模拟 2 线程交错
        // ...
    });
}
```

## 10 · 资源

- Rust atomics reference:https://doc.rust-lang.org/std/sync/atomic/
- Mara Bos 《Rust Atomics and Locks》(必读):https://marabos.nl/atomics/
- crossbeam:https://github.com/crossbeam-rs/crossbeam
- loom:https://github.com/tokio-rs/loom
- Paul McKenney 论文(RCU / memory ordering)

## 11 · 练习

### Lv1

用 `AtomicU64` 写一个**线程安全计数器**。10 个线程每个 +1 1000 次,最终 10000。

### Lv2

实现 SPSC queue(`push` / `pop`),测试 2 线程(生产 / 消费)的正确性。多线程跑 30 秒不崩。

### Lv3

用 crossbeam-epoch 实现 lock-free stack。对比 Mutex<Vec> 的性能。

### Lv4

读 `crossbeam-queue::ArrayQueue` 源码。看它如何处理 wrap-around。提一个 doc PR 解释算法。
