---
title: "Threading Models"
subtitle: "Thread pool, work stealing, rayon, scheduled vs immediate"
type: deep-dive
phase: 4
domains: [rust, game, linux]
duration: "2-3h"
---

# Threading Models

> Phase 4 多处涉及多线程(Day 122 work queue、Day 144 混音、Day 165 asset cache)。这篇 deep-dive 系统讲游戏开发的线程模型:线程池、work stealing、rayon 的并行迭代器,以及"何时该开线程"的判断。

## 0 /// 为什么多线程

单核 CPU 已停滞(2005 后),多核成为性能来源。

| 代码 | 1 核 | 8 核(理想) | 8 核(实际) |
|---|---|---|---|
| 单线程 | 1x | 1x | 1x |
| 多线程 + 锁 | — | 8x | 2-4x |
| 多线程 + lock-free | — | 8x | 6-7x |

实际多核加速 < 线程数,因锁竞争 + 内存带宽。

## 1 /// 线程模型分类

### 1:N(N 个 OS thread,1 个应用)

```rust
fn main() {
    // 顺序
    step1();
    step2();
}
```

无并发,简单。

### N:1(用户级线程 / 协程)

```python
async def main():
    await task1()
    await task2()
```

单 OS 线程,多个用户任务切换。无锁,但单核。

### M:N(M 个 OS 线程,N 个用户任务)

Go goroutine、Erlang process、Rust tokio。

### 1:1(每任务一个 OS 线程)

```rust
thread::spawn(task);
```

简单,但每线程 1-8 MB stack,1000 线程 = GB。

### 线程池(Thread Pool)

固定 N 个 OS 线程,任务队列:

```rust
struct Pool {
    threads: Vec<JoinHandle>,
    queue: Mutex<Vec<Task>>,
}
```

N 通常 = CPU 核数。任务从队列取,跑完还线程。

## 2 /// 线程池实现

```rust
use std::sync::mpsc;
use std::sync::Arc;
use std::sync::Mutex;

type Task = Box<dyn FnOnce() + Send + 'static>;

struct ThreadPool {
    workers: Vec<std::thread::JoinHandle<()>>,
    sender: mpsc::Sender<Message>,
}

enum Message {
    Task(Task),
    Stop,
}

impl ThreadPool {
    fn new(n: usize) -> Self {
        let (sender, receiver) = mpsc::channel::<Message>();
        let receiver = Arc::new(Mutex::new(receiver));
        let mut workers = Vec::with_capacity(n);
        for _ in 0..n {
            let receiver = Arc::clone(&receiver);
            workers.push(std::thread::spawn(move || {
                loop {
                    let msg = receiver.lock().unwrap().recv().unwrap();
                    match msg {
                        Message::Task(t) => t(),
                        Message::Stop => break,
                    }
                }
            }));
        }
        Self { workers, sender }
    }

    fn execute(&self, task: Task) {
        self.sender.send(Message::Task(task)).unwrap();
    }
}
```

## 3 /// Work Stealing

朴素线程池问题:任务队列是单个 Mutex,所有线程抢锁,**contention** 高。

work-stealing:每线程有自己的本地队列(LIFO),空时从别人队列"偷"(FIFO):

- 本地 push / pop:LIFO,无 contention
- 偷:从别人队列**尾部**偷,减少冲突
- 偷的频率低(只在自己空时)

性能接近无锁。Java ForkJoinPool / Rust rayon / .NET ThreadPool 用此。

### crossbeam-deque

```rust
use crossbeam_deque::{Injector, Worker, Stealer};

let injector = Injector::new();  // 全局任务队列
let worker = Worker::new_fifo();
let stealer = worker.stealer();

// 线程 A(拥有 worker)
worker.push(task1);
worker.push(task2);
let t = worker.pop();  // task2(LIFO)

// 线程 B(有 stealer)
let stolen = stealer.steal();  // task1(FIFO)
```

## 4 /// rayon crate

Rust 最流行的并行库,基于 work stealing。

### par_iter

```rust
use rayon::prelude::*;

let v: Vec<i32> = (0..1_000_000).collect();
let sum: i32 = v.par_iter().map(|&x| x * 2).sum();
// 自动分块 + 多核并行
```

### par_chunks

```rust
v.par_chunks(1024).for_each(|chunk| {
    // 每块 1024 元素,独立处理
});
```

### join

```rust
let (a, b) = rayon::join(
    || compute_a(),
    || compute_b(),
);
// 两个 closure 并行跑
```

### scope

```rust
let mut data = vec![1, 2, 3];
rayon::scope(|s| {
    s.spawn(|_| {
        // 借用 data
        println!("{:?}", data);
    });
    s.spawn(|_| {
        // 也借用 data
        data.push(4);
    });
});
// scope 结束时所有 task 完成
```

scope 解决"非 'static 借用"——不像 `thread::spawn` 要求 `'static`。

## 5 /// Scheduled vs Immediate

两种执行模型:

### Immediate(立即执行)

`thread::spawn` 立刻跑。任务独立,生命周期长。

### Scheduled(调度执行)

任务被提交到调度器,何时跑由调度器决定。任务可以等待、依赖、优先级。

| 模型 | 何时用 |
|---|---|
| thread::spawn | 长期任务 |
| ThreadPool::execute | 短任务,无返回 |
| rayon::spawn | 短任务,需要 join |
| async / await | I/O 密集(网络 / 文件) |

## 6 /// Async / Await

`async fn` 返回 `impl Future`,不立即跑,要 `await` 或 spawn 到 runtime。

```rust
async fn fetch(url: &str) -> String { ... }

let s = fetch("https://example.com").await;  // 等
```

tokio / async-std 提供 runtime(线程池 + reactor)。

游戏开发**较少用 async**:游戏逻辑帧式,不适合 async 抢占。但 I/O(网络多人)适合。

## 7 /// 线程模型选择

| 场景 | 推荐 |
|---|---|
| CPU 密集(数学 / 物理) | rayon(par_iter) |
| 短任务并发 | ThreadPool |
| 长任务 | thread::spawn |
| I/O(网络 / 文件) | tokio(async) |
| 实时(音频) | 专用线程 + 实时优先级 |
| 数据并行 | rayon / SIMD |

游戏架构典型:

```
Main thread(游戏逻辑)
Audio thread(混音,实时)
Render thread(可选,GPU 提交)
Job pool(粒子 / 物理,rayon)
I/O thread(asset streaming)
```

## 8 /// 数据并行 vs 任务并行

- **数据并行**:同样操作作用在大量数据(粒子、像素)。用 rayon `par_iter` + SoA。
- **任务并行**:不同操作并行(物理 + AI + 渲染)。用 ThreadPool + 任务队列。

游戏两者都用:粒子系统数据并行,AI 决策任务并行。

## 9 /// Amdahl's Law

并行加速受**串行部分**限制:

```
Speedup = 1 / ((1 - p) + p / N)
```

p = 可并行比例,N = 核数。

| p | N=2 | N=4 | N=8 | N=infty |
|---|---|---|---|---|
| 50% | 1.33x | 1.6x | 1.78x | 2x |
| 90% | 1.8x | 3.07x | 4.7x | 10x |
| 99% | 1.98x | 3.88x | 7.48x | 100x |

**只有 90%+ 可并行才能从多核大幅受益**。

## 10 /// 资源

- rayon:https://github.com/rayon-rs/rayon
- crossbeam:https://github.com/crossbeam-rs/crossbeam
- tokio:https://github.com/tokio-rs/tokio
- "Structured Concurrency"(Nathaniel J. Smith)
- "Java Concurrency in Practice"(虽 Java,原理通用)

## 11 /// 练习

### Lv1

实现简单 ThreadPool(2-8 workers),execute 100 个任务。

### Lv2

把 100 万 Vec<f32> 求和改成 rayon `par_iter`。对比 1 核 vs 多核。

### Lv3

用 rayon::scope 实现 fork-join:并行计算 sum_tree(二叉树所有节点求和)。

### Lv4

读 rayon 的 `src/sleep.rs` 或 `src/job.rs`,看它如何 work-steal。提一个 doc PR。
