---
article: 25
phase: 0
title: "并发基础:线程 / 锁 / 原子 / 内存序 / async"
type: concept
difficulty: 5
duration: "8-10h"
domains: [concurrency, system, game, rust, linux]
prereqs: ["08-processes-and-signals", "23-network-foundation", "24-memory-foundation"]
---

# 25 · 并发基础:从竞态到 async/await

> 你给游戏加多线程:渲染线程 + 物理线程。你写代码:`position += velocity * dt;`,两个线程都改 `position`。你跑游戏——角色**瞬移**到随机位置,然后**消失**,然后出现在天空。你以为是物理 bug,改了半天没改好。你打印 `position` 的值,发现**两线程同时读、各自算、各自写**——经典的 read-modify-write race。这是**并发**的第一个陷阱。后面还有死锁、活锁、false sharing、内存序——每个都能让你 debug 一周。这一篇讲完,你能 debug 上面所有问题,因为你会理解"两个线程看起来同时跑",但 CPU、cache、编译器**各自对'同时'的定义**完全不同。

## 0 · 为什么要有这一天

让我把镜头拉到一个具体场景。

你跟着 Handmade Hero 走到 Day 50,你想"用多线程加速游戏"。你写一个粒子系统,每个粒子独立更新,你觉得"开 8 个线程,每个线程处理 1/8 粒子"。代码:

```rust
let mut positions: Vec<Vec3> = ...;  // 1 万个粒子
let chunk = positions.len() / 8;

let mut handles = vec![];
for i in 0..8 {
    let start = i * chunk;
    let end = start + chunk;
    let slice = &mut positions[start..end];
    let h = thread::spawn(move || {
        for p in slice {
            p.y -= 9.8 * dt;
        }
    });
    handles.push(h);
}
for h in handles { h.join().unwrap(); }
```

跑起来——快了 6 倍。你得意。

然后你想加个全局统计:"活跃粒子数"。代码:

```rust
let active_count = Arc::new(Mutex::new(0));
// 每个粒子如果还活着,*active_count.lock() += 1
```

跑——比单线程还慢。你打开 perf,看见 99% 时间在 `__pthread_mutex_lock`。**为什么**?

**真正的问题**:每个粒子都 `lock()` / `unlock()`,锁成了瓶颈。8 个线程争一个锁,大部分时间在等。

修法:**每线程一个本地计数器,最后合并**。

```rust
let local_counts: Vec<i32> = ...;  // 每线程一个
// 每线程只更新自己的
// join 后 sum 起来
```

或者用 **atomic**:`AtomicI32` 比 Mutex 快几十倍,因为无锁(用 CPU 的 CAS 指令)。

但这只是冰山一角。并发有更深的问题:

第二个陷阱:**死锁**。线程 A 锁 lock1 再要 lock2,线程 B 锁 lock2 再要 lock1。两个都等对方释放,**永远等下去**。

第三个陷阱:**内存序**。`AtomicBool` 的 `store(true)` 写完,另一个线程**不保证立刻看到**。CPU 有 store buffer、cache,数据在多核之间传播要时间。如果你不指定正确的 `Ordering`,你看到的可能是旧值——代码看起来对,行为完全错。

第四个陷阱:**Send / Sync**。Rust 编译器拒绝你"把 `Rc<T>` 跨线程 send"——但 `Arc<T>` 可以。为什么?Rust 的"数据竞争自由"保证背后是什么?

第五个陷阱:**async / await**。你听说 Rust 的 async 是"零成本协程",但不知道它怎么工作。Tokio runtime 内部到底怎么调度成千上万的 task?Future 是什么?Poll 是什么?

**这一篇覆盖**:
- 进程 vs 线程 vs 协程(绿色线程)
- Linux pthread / clone 系统调用 / Rust std::thread
- 线程状态(ready / running / blocked) / 上下文切换代价
- 竞态条件 — bank transfer 案例
- mutex / semaphore / condvar
- 死锁四条件 + dining philosophers
- happens-before / C++ memory model 概念
- 原子操作 / CAS / fetch_add
- Memory ordering(Relaxed / Acquire / Release / AcqRel / SeqCst)完整对比
- 无锁数据结构概念
- Rust Send / Sync 标记 trait
- async / await 基础 / Tokio 运行时概念
- 实战:多线程求和 + atomic vs mutex benchmark

**每一节**:概念 → Rust 代码 → Linux 工具验证 → 游戏场景 → 跨域关联。

**心理锚点**:这一篇读完,你能:
- 解释为什么 mutex 比原子慢几十倍
- 解释 `Ordering::Relaxed` 和 `Ordering::SeqCst` 的差别
- 写一个无死锁的多线程代码
- 用 `helgrind`(valgrind)或 `ThreadSanitizer` 检测竞态
- 解释 `Arc<Mutex<T>>` 为什么是 Rust 多线程标配
- 解释 async fn 怎么编译成 state machine
- 写一个并发求和,8 线程线性加速
- 解释 Tokio 怎么用 epoll 处理 1 万连接

---

## 1 · 概念地图:并发的层次

并发不是单一概念,它分多个层次:

| 层 | 单位 | 谁调度 | 切换代价 |
|---|---|---|---|
| 多进程 | process | 内核 | 高(MMU 切换、cache flush) |
| 多线程(内核) | thread | 内核 | 中(共享地址空间) |
| 协程(用户态) | coroutine / task | 用户态 runtime | 低(只切寄存器) |
| 异步 IO | task | 用户态 runtime | 低 |

**并发(concurrency) vs 并行(parallelism)**:
- **并发**:多件事在"管理"中,可能同时跑(单核分时),也可能不。
- **并行**:多件事**物理上同时**跑(多核)。

单核 CPU 也能并发(时间片轮转),但不能并行。多核 CPU 可以既并发又并行。

**关键洞察**:**并发是结构,并行是执行**。你的代码先设计成并发(可以拆分独立任务),再放到多核上并行跑。

---

## 2 · 心智模型

### 2.1 类比:厨房

把 CPU 想成厨房,任务想成菜。

- **单核单线程**:一个厨师,一道一道做。红烧肉做完再炒青菜。慢但简单。
- **单核多线程(时间片)**:一个厨师,红烧肉在炖(等待中),趁机切青菜。看起来"同时",其实是切换。
- **多核多线程**:多个厨师,每个做一道菜。物理并行。
- **协程 / async**:厨师切一切青菜,放下,去做红烧肉;红烧肉炖着,回去继续切青菜。**没有等待**——厨师永远在干活。

最后一种(协程)就是 async/await 的精髓:**线程不等 I/O,先做别的,等 I/O 完了再回来**。一个厨师可以做 10 道菜,因为每道菜的"等待"环节被其他菜的"工作"填满。

### 2.2 第一原理:为什么需要并发

并发的核心驱动力:**等待太慢**。

CPU 一秒做几十亿次操作。但等磁盘 IO,几百万周期。等网络,几亿周期。**等的时候 CPU 闲着**,浪费。

并发让 CPU **在等待时干别的**:
- Web server:一个连接等数据库,处理另一个连接的请求。
- 游戏:渲染线程等 GPU 提交完成,物理线程算下一帧。
- GUI:主线程响应点击,后台线程加载文件。

**两种等待**:
- **CPU-bound**:计算密集,等待 = CPU 算。多线程只能多核并行加速。
- **IO-bound**:大部分时间等 IO。多线程 / async 能让一个核干多个 IO 任务。

游戏两种都有:物理是 CPU-bound,网络 / 文件加载是 IO-bound。

### 2.3 上下文切换的代价

线程切换不是免费午餐。一次切换做这些事:
1. **保存当前线程状态**:寄存器、程序计数器、栈指针 → TCB(thread control block)。
2. **加载新线程状态**:从它的 TCB。
3. **TLB 刷新**(进程切换时,线程切换不需要,因为共享地址空间)。
4. **cache cold**:新线程的数据大概率不在 cache,前几次访问都 miss。
5. **branch predictor reset**:CPU 的分支预测要重新"学习"新线程的代码模式。

每次切换 ~1-10 微秒。**1 秒切 1 万次 = 10-100 ms 浪费**。如果线程数 > 核数,切换频繁,性能反而下降。

```bash
# 看系统的上下文切换数
cat /proc/<pid>/status | grep ctxt
# voluntary_ctxt_switches: 12345
# nonvoluntary_ctxt_switches: 678

# 全局看
pidstat -w 1     # 每秒刷新
# 或
perf stat -e context-switches,cpu-migrations ./my_program
```

**voluntary**:线程主动让(调用了阻塞 syscall,如 `read` / `recv`)。
**nonvoluntary**:时间片用完被抢占。

### 2.4 进程 vs 线程

**进程**:OS 资源分配的单元。每个进程有自己的**地址空间**(虚拟内存)、文件描述符表、用户/组 ID。

**线程**:OS 调度的单元。同一进程的线程**共享地址空间**——共享代码、堆、全局变量;各自有**栈**和寄存器。

Linux 用 `clone(2)` syscall 创建线程。`clone` 可以选择"共享什么":
- 共享地址空间 → 线程
- 不共享地址空间 → 进程(`fork`)
- 部分共享 → 容器(namespace)

```
+-------------------+
|     Process       |
| +---------------+ |
| | Address space | |
| |  - code       | |
| |  - data       | |
| |  - heap       | |
| +---------------+ |
| +---------------+ |
| | Thread 1      | |
| |  - stack      | |
| |  - registers  | |
| +---------------+ |
| +---------------+ |
| | Thread 2      | |
| |  - stack      | |
| |  - registers  | |
| +---------------+ |
+-------------------+
```

**为什么用线程而不是进程**:
1. 创建快(fork 要复制页表,虽然 COW 但仍开销)。
2. 通信快(共享内存,不用 IPC)。
3. 切换快(无 TLB flush)。

**为什么用进程而不是线程**:
1. 隔离——一个进程崩了,其他进程不受影响。Chrome 多进程如此。
2. 安全——不同权限。
3. 分布式——进程可以跑在不同机器。

游戏:
- 单进程多线程:大部分游戏。共享状态方便。
- 多进程:server 端——一个客户端一个进程(或 worker pool)。隔离 + 多核利用。

---

## 3 · Linux 线程实现

### 3.1 pthread 和 clone

POSIX 标准定义 pthread(POSIX thread)API。Linux glibc 的 pthread 实现,底层调 `clone`。

```c
// 简化的 clone 调用
clone(child_func, child_stack,
      CLONE_VM | CLONE_FS | CLONE_FILES | CLONE_SIGHAND | CLONE_THREAD,
      arg);
```

`CLONE_VM` = 共享虚拟内存(这就是线程的本质)。`CLONE_THREAD` = 放进同一线程组(共享 PID,有独立 TID)。

```bash
# 看一个进程的线程
ps -T -p $(pidof firefox)
# 或
ls /proc/$(pidof firefox)/task/
# 每个数字是一个 TID(thread ID)

# 顶层看所有线程
htop  # 默认显示线程(可关)
top -H  # 显示线程
```

Linux 内核调度的不是进程,是**线程**(内核叫 task)。每个线程一个 `task_struct`。所以 Linux 的"process"和"thread"在内核里是同一种东西,只是共享多少不同。

### 3.2 Rust std::thread

Rust 标准库的 `std::thread` 是 pthread 的安全封装。

```rust
use std::thread;

fn main() {
    let handle = thread::spawn(|| {
        println!("Hello from thread!");
        42
    });
    
    let result = handle.join().unwrap();
    println!("Thread returned: {}", result);
}
```

`thread::spawn` 签名:
```rust
pub fn spawn<F, T>(f: F) -> JoinHandle<T>
where
    F: FnOnce() -> T,
    F: Send + 'static,
    T: Send + 'static,
```

注意两个 trait bound:
- **`Send`**:closure 和返回值能安全跨线程传。
- **`'static`**:closure 不借用主线程的数据(否则主线程可能在 join 前回收数据)。

所以下面代码**编译失败**:

```rust
let s = String::from("hello");
let h = thread::spawn(|| {
    println!("{}", s);  // 错误:s 是借用,不是 'static
});
```

修法:
```rust
let s = String::from("hello");
let h = thread::spawn(move || {  // move 把 s 所有权转移到 closure
    println!("{}", s);
});
```

`move` 关键字强制 closure 取走所用变量的所有权。这是 Rust 多线程编程的基础动作。

### 3.3 scoped thread

如果你**就是要借用**主线程数据,Rust 1.63+ 给了 `std::thread::scope`:

```rust
let mut arr = vec![1, 2, 3, 4, 5, 6];

std::thread::scope(|s| {
    // 这些线程在 scope 结束前 join,所以可以借用 arr
    s.spawn(|| {
        println!("{:?}", &arr[0..3]);
    });
    s.spawn(|| {
        println!("{:?}", &arr[3..6]);
    });
});
// 这里 arr 的借用结束,可以再次使用
```

scope 内 spawn 的线程保证在 scope 结束前完成,所以借用安全。这是处理"短期并行任务"的优雅方式。

### 3.4 thread builder

`thread::spawn` 用默认栈大小(通常 2-8 MB)。要改:

```rust
use std::thread::Builder;

let handle = Builder::new()
    .name("worker-1".into())      // 给线程命名(便于 debug)
    .stack_size(64 * 1024)         // 64 KB 栈
    .spawn(|| {
        // ...
    })
    .unwrap();
```

游戏里大量 worker thread 时,小栈(64 KB)省内存。10000 线程 × 8 MB 默认栈 = 80 GB——不可能。但 64 KB 栈 × 10000 = 640 MB,可行。

`htop` 里看线程名:
```
  PID  USER   NAME
 1234  user   my-game
 1235  user   my-game:worker-1
 1236  user   my-game:worker-2
```

### 3.5 thread parking

线程"停"和"走":

```rust
use std::thread;
use std::time::Duration;

let h = thread::spawn(|| {
    println!("before park");
    thread::park();                    // 阻塞,直到 unpark
    println!("after park");
});

thread::sleep(Duration::from_millis(100));
println!("unparking");
h.thread().unpark();                   // 唤醒
h.join().unwrap();
```

`park` / `unpark` 比 condvar 简单,适合"等待一个一次性信号"。unpark 在 park 之前调用也有效(unpark 计数不会丢失),这避免了 condvar 的"丢失唤醒"问题。

---

## 4 · 竞态条件

**Race condition**(竞态):多个线程访问同一资源,结果**取决于执行顺序**,而顺序不确定。

### 4.1 bank transfer 案例

经典例子:账户转账。

```rust
fn transfer(from: &mut Account, to: &mut Account, amount: i64) {
    from.balance -= amount;
    to.balance += amount;
}
```

单线程没问题。多线程并发执行,两个线程同时操作同一账户:

```
Thread A: transfer(A, B, 100)
Thread B: transfer(A, C, 100)

可能的执行:
1. A 读 A.balance = 500
2. B 读 A.balance = 500   ← 还没写回
3. A 写 A.balance = 400
4. B 写 A.balance = 400   ← 覆盖了 A 的写!
```

A 给了 B 100,A 给了 C 100,本应 A.balance = 300。但实际 = 400。**100 块凭空消失了**。

这就是**read-modify-write race**:读 → 算 → 写,中间另一线程插入。

### 4.2 数据竞争 vs 竞态

精确区分:

- **数据竞争(data race)**:两个线程同时访问同一内存,**至少一个是写**,无同步。Rust 的 safe 代码**禁止**数据竞争(编译期拒绝)。
- **竞态条件(race condition)**:更广义,逻辑层的"顺序依赖"问题。即使无数据竞争(用 mutex 保护了),也可能有竞态——比如"先转账再扣费"vs"先扣费再转账",顺序不同结果不同。

Rust 帮你消灭数据竞争,但**消灭不了逻辑竞态**——那要靠设计。

### 4.3 修法一:mutex

最直接——加锁。

```rust
use std::sync::Mutex;

let account_a = Arc::new(Mutex::new(Account { balance: 500 }));
let account_b = Arc::new(Mutex::new(Account { balance: 0 }));

fn transfer(from: &Mutex<Account>, to: &Mutex<Account>, amount: i64) {
    let mut from_guard = from.lock().unwrap();
    let mut to_guard = to.lock().unwrap();   // 危险!见死锁
    from_guard.balance -= amount;
    to_guard.balance += amount;
}
```

mutex.lock() 给你一个 `MutexGuard`,RAII——出作用域自动 unlock。这是 Rust 比 C++ 优雅的地方:不可能忘记 unlock。

### 4.4 修法二:atomic

如果是简单的整数加减,用 `AtomicI64` 比 mutex 快:

```rust
use std::sync::atomic::{AtomicI64, Ordering};

let balance: AtomicI64 = AtomicI64::new(500);
balance.fetch_sub(100, Ordering::Relaxed);   // 原子减
```

`fetch_sub` 是原子的——读、减、写在 CPU 指令级别是一条 `lock xadd`。无竞态。

### 4.5 修法三:消息传递(channel)

Rust 文化推崇**"不要通过共享内存来通信,要通过通信来共享内存"**(Go 的口号,Rust 借鉴)。

```rust
use std::sync::mpsc;
use std::thread;

let (tx, rx) = mpsc::channel();

for i in 0..10 {
    let tx = tx.clone();
    thread::spawn(move || {
        tx.send(format!("hello {}", i)).unwrap();
    });
}

for _ in 0..10 {
    println!("{}", rx.recv().unwrap());
}
```

每个 worker 把结果 send 到 channel,主线程 recv。**单一所有权**——一个值一旦 send,发送方就失去了。这避免了共享状态。

工业级 channel:
- `std::sync::mpsc`:标准库,多生产者单消费者。
- `crossbeam-channel`:多生产者多消费者,性能强。
- `flume`:更现代的 channel。
- `tokio::sync::mpsc`:异步 channel。

---

## 5 · Mutex / Semaphore / Condvar

### 5.1 Mutex

**Mutex**(mutual exclusion,互斥锁):同一时刻**只允许一个线程**进入临界区。

```rust
use std::sync::Mutex;

let m = Mutex::new(0);

// lock() 阻塞直到拿到锁
{
    let mut guard = m.lock().unwrap();
    *guard += 1;
}   // guard 出作用域,自动 unlock

// try_lock() 不阻塞,失败立即返回
if let Ok(guard) = m.try_lock() {
    *guard += 1;
}
```

mutex 实现:Linux 用 **futex**(fast userspace mutex)。无竞争时纯用户态(atomic CAS),快;有竞争时 syscall 进入内核等待。

**poisoning**:Rust 的 mutex 有"中毒"机制——持有锁的线程 panic 后,mutex 标记为 poisoned,后续 lock 返回 `PoisonError`。这避免其他线程拿到锁后访问**半破坏**的数据。

```rust
let m = Mutex::new(String::from("hi"));
{
    let mut guard = m.lock().unwrap();
    panic!("oops");  // 持有锁时 panic
}
// 后续:
let r = m.lock();  // Err(PoisonError)
let guard = r.unwrap_or_else(|p| p.into_inner());  // 强制拿数据
```

### 5.2 parking_lot::Mutex

`std::sync::Mutex` 性能不极致,API 也有 `Result`(因为 poisoning)。`parking_lot` crate 提供更高效的 mutex:

```toml
[dependencies]
parking_lot = "0.12"
```

```rust
use parking_lot::Mutex;

let m = Mutex::new(0);
let mut guard = m.lock();  // 不返回 Result,无 poisoning
*guard += 1;
// guard 出作用域 unlock
```

`parking_lot::Mutex`:
- 比 std 快 2-3×。
- 无 poisoning(更简单)。
- 公平锁选项(防止饥饿)。
- 更小的内存占用。

游戏 / 高性能 server 推荐 parking_lot。

### 5.3 RwLock

读写锁:多个读者同时,但写者独占。

```rust
use std::sync::RwLock;

let lock = RwLock::new(5);

// 多个读
{
    let r1 = lock.read().unwrap();
    let r2 = lock.read().unwrap();  // 同时多个 read OK
    println!("{} {}", *r1, *r2);
}

// 一个写
{
    let mut w = lock.write().unwrap();
    *w += 1;
}
```

适用:**读多写少**场景。比如配置缓存——读频繁,改罕见。

风险:**写饥饿**——如果一直有读者,写者永远等。Rust 的 `std::sync::RwLock` 实现策略是 OS 决定(Linux 倾向公平)。

### 5.4 Semaphore

**信号量**:整数计数器,P 操作 -1(到 0 阻塞),V 操作 +1。

Rust 标准库**没有**直接 semaphore(因为 mutex + condvar 能实现)。但 `parking_lot` 等提供。

```rust
use std::sync::Arc;
use std::thread;
use parking_lot::Semaphore;

// 限制并发数到 3
let sem = Arc::new(Semaphore::new(3));

let mut handles = vec![];
for i in 0..10 {
    let sem = sem.clone();
    handles.push(thread::spawn(move || {
        let _permit = sem.acquire();  // 等待 permit
        println!("Worker {} running", i);
        // ... 干活
        // _permit 出作用域,自动 release
    }));
}
```

典型场景:限制连接池大小、线程池并发数、API rate limit。

### 5.5 Condvar

**条件变量**:线程等待"某条件成立",被另一线程唤醒。

经典模式——生产者 / 消费者:

```rust
use std::sync::{Arc, Mutex, Condvar};
use std::thread;

let pair = Arc::new((Mutex::new(false), Condvar::new()));
let (lock, cvar) = (pair.0.clone(), pair.1.clone());

// 等待者
let waiter = thread::spawn(move || {
    let mut started = lock.lock().unwrap();
    while !*started {
        started = cvar.wait(started).unwrap();   // 释放锁,等通知,重新拿锁
    }
    println!("Notified!");
});

// 通知者
thread::sleep(std::time::Duration::from_millis(100));
{
    let mut started = lock.lock().unwrap();
    *started = true;
}
cvar.notify_one();
waiter.join().unwrap();
```

`cvar.wait(guard)` 做三件事:
1. 原子地**释放 mutex** 并**阻塞线程**。
2. 被 `notify_one` / `notify_all` 唤醒。
3. **重新拿 mutex**,返回 guard。

**为什么 condvar 必须配 mutex**:防止**丢失唤醒**。如果不用 mutex,生产者可能在消费者"检查条件"和"开始等待"之间 notify,消费者错过。

**为什么用 while 不用 if**:防止**虚假唤醒**(spurious wakeup)。POSIX 允许 condvar 无故唤醒,所以醒来要再检查条件。

工业上更推荐直接用 channel,而不是手写 condvar 模式——更难写错。

---

## 6 · 死锁

### 6.1 死锁四条件

死锁要同时满足四个条件(Coffman conditions):

1. **互斥(mutual exclusion)**:资源不可共享,一个时刻一个用户。
2. **占有并等待(hold and wait)**:线程持有资源 A,等待资源 B。
3. **不可剥夺(no preemption)**:资源只能自愿释放。
4. **循环等待(circular wait)**:线程间形成等待环。

破坏任何一个就能避免死锁。

### 6.2 dining philosophers

经典问题:5 个哲学家围桌,5 个叉子。每个哲学家要**两个叉子**才能吃饭。

```
        P0
     /      \
   F0        F1
   |          |
   P1        P4
   |          |
   F1        F4
     \      /
       P2-P3
```

如果每个哲学家先拿左叉子,再拿右叉子——所有人同时拿左,**等待右**——死锁。

修法:
1. **破坏循环等待**:规定一个叉子有"优先级",必须先拿编号小的。
2. **破坏占有等待**:要求一次拿两个(要么都拿到,要么一个不拿)。
3. **仲裁者**:一个 waiter 协调,只允许 4 人同时尝试。

代码示例(用 Rust):

```rust
use std::sync::Mutex;
use std::thread;

let forks: Vec<Mutex<()>> = (0..5).map(|_| Mutex::new(())).collect();

// 死锁版:每个哲学家先左后右
// for i in 0..5 {
//     let left = forks[i].lock().unwrap();
//     let right = forks[(i+1) % 5].lock().unwrap();  // 最后一个等第一个,循环
//     eat();
// }

// 修法:破坏循环——最后一个哲学家先右后左
let mut handles = vec![];
for i in 0..5 {
    let forks_ref = &forks;
    handles.push(thread::spawn(move || {
        let (first, second) = if i == 4 {
            (0, 4)  // 最后一个反过来
        } else {
            (i, (i + 1) % 5)
        };
        let _f1 = forks_ref[first].lock().unwrap();
        let _f2 = forks_ref[second].lock().unwrap();
        println!("Philosopher {} eating", i);
    }));
}
for h in handles { h.join().unwrap(); }
```

### 6.3 检测死锁

```bash
# 用 helgrind(valgrind 工具)
valgrind --tool=helgrind ./target/release/my_program

# 或 ThreadSanitizer
RUSTFLAGS="-Zsanitizer=thread" cargo +nightly run
```

这些工具运行时检测潜在的锁问题和竞态。**生产前必跑**。

### 6.4 lock hierarchy

工业实践:**lock hierarchy**——给所有锁编层级号,**必须按号升序加锁**。

```rust
// 假设层级:
// Level 0: global_config
// Level 1: world_state
// Level 2: entity

// 持有 entity 锁时,可以拿 world_state(向下)
// 持有 world_state 锁时,**不能**拿 entity(向上,违反 hierarchy)
```

只要所有线程遵守层级,**不可能死锁**(因为锁顺序一致,不形成环)。游戏引擎(Unreal、bevy)都靠这套纪律。

---

## 7 · 原子操作

### 7.1 什么是原子

**原子操作**(atomic operation):不可分的操作——要么完成,要么没发生,中间状态不可见。

CPU 指令级别,常见原子:
- `xchg`:原子交换。
- `lock inc`:原子加。
- `lock cmpxchg`:CAS(compare and swap)。
- `lock xadd`:原子加并返回旧值。
- `lock bts / btr`:位测试并设置 / 重置。

`lock` 前缀(x86)告诉 CPU:"这条指令要原子"——CPU 锁总线(老式)或锁 cache line(现代),保证不被其他核干扰。

### 7.2 Rust Atomic types

```rust
use std::sync::atomic::{AtomicI32, AtomicUsize, AtomicBool, AtomicPtr, Ordering};

let counter = AtomicI32::new(0);
counter.fetch_add(1, Ordering::Relaxed);     // +
counter.fetch_sub(1, Ordering::Relaxed);     // -
counter.fetch_or(0b0001, Ordering::Relaxed); // |=
counter.fetch_and(!0b0001, Ordering::Relaxed); // &=
let old = counter.swap(10, Ordering::Relaxed);
let prev = counter.compare_exchange(10, 20, Ordering::SeqCst, Ordering::Relaxed);
// 如果当前是 10,换成 20。成功返回 Ok(prev),失败返回 Err(actual)
```

每个原子操作都要指定 **Ordering**(下一节深入)。

### 7.3 CAS(compare-and-swap)

CAS 是无锁编程的核心原语。语义:

```
cas(addr, expected, new):
    if *addr == expected:
        *addr = new
        return success
    else:
        return failure (*addr 的当前值)
```

CAS 是**乐观锁**——大多数时候没冲突,成功;少数冲突重试。

```rust
fn atomic_increment(counter: &AtomicI32) {
    loop {
        let cur = counter.load(Ordering::Relaxed);
        let new = cur + 1;
        match counter.compare_exchange_weak(
            cur, new,
            Ordering::Relaxed,
            Ordering::Relaxed,
        ) {
            Ok(_) => return,
            Err(_) => continue,  // 被别人改了,重试
        }
    }
}
```

`compare_exchange_weak` 比 `compare_exchange` 多允许**虚假失败**(返回 Err 但其实成功),性能略好。在 loop 里用 weak。

**ABA 问题**:线程 A 读到 expected,准备 CAS;这时线程 B 把值改成 B,又改回 A。线程 A 的 CAS 成功——但它以为"没人动过"。在某些场景(如无锁栈)是 bug。

ABA 修法:加版本号(指针 + counter),或用 `fetch_update` 帮你处理。

### 7.4 fetch_add 实现

```rust
// Rust AtomicI32::fetch_add 的等价汇编(x86)
// lock xadd DWORD PTR [rdi], esi
```

一条指令,原子完成。比 mutex 快 50-100×。

---

## 8 · 内存序

这是并发最难的部分。

### 8.1 为什么有内存序

CPU 和编译器会**重排指令**——为了优化。单线程下重排不影响结果,但多线程下,**重排会破坏通信**。

例子:

```
线程 1:                线程 2:
data = 42;             while (!ready) {}
ready = true;          print(data);   // 期望 42
```

如果线程 1 的两条指令被重排(ready = true 先执行),线程 2 可能看到 ready=true 但 data 还是 0。

**内存序**(memory ordering)告诉你:"这两条指令**不能重排**"。

### 8.2 Rust 的五种 Ordering

Rust 的 `std::sync::atomic::Ordering` 五个变体:

**Relaxed**:只保证**当前变量**的原子性,不约束其他内存访问。
- 用:计数器、统计。`counter.fetch_add(1, Relaxed)`。

**Release**: store 用。**之前的所有读写**不能重排到这条之后。即"我写完了,别人可以看到"。
- 用:写数据后置 ready flag。

**Acquire**: load 用。**之后的所有读写**不能重排到这条之前。即"我看到 ready=true 后,我能读到对应数据"。
- 用:检查 ready flag 后读数据。

**AcqRel**: read-modify-write 操作(如 `fetch_add`)用。是 Acquire + Release。
- 用:同时读和写的原子操作。

**SeqCst**:最强。所有 SeqCst 操作**全局有序**。
- 用:需要严格全局顺序的(罕见)。

### 8.3 Acquire / Release 配对模式

经典模式:

```rust
use std::sync::atomic::{AtomicBool, Ordering};

static DATA: AtomicI32 = AtomicI32::new(0);
static READY: AtomicBool = AtomicBool::new(false);

// 线程 1
DATA.store(42, Ordering::Relaxed);
READY.store(true, Ordering::Release);   // Release:确保 DATA 写在 READY 之前

// 线程 2
while !READY.load(Ordering::Acquire) {} // Acquire:确保读 DATA 在 READY 之后
println!("{}", DATA.load(Ordering::Relaxed));  // 保证是 42
```

**关键**:Release 和 Acquire **配对**。一个线程 Release 写,另一个线程 Acquire 读——后者保证看到前者 Release 之前的所有写。

### 8.4 各 Ordering 的代价

```
Relaxed:   1 cycle(普通 atomic 指令)
Acquire:   ~1 cycle(x86 大部分 acquire 是免费的)
Release:   ~1 cycle(x86 大部分 release 是免费的)
AcqRel:    ~1 cycle
SeqCst:    几十 cycles(需要 memory barrier,锁总线或 cache 同步)
```

**x86 是强内存模型**——大部分 acquire / release 在 x86 上免费(因为 x86 不重排 store-load)。所以 x86 上 Relaxed 和 SeqCst 性能差不多。

**ARM 是弱内存模型**——会重排更多,需要显式 barrier。Acquire / Release 比 Relaxed 慢明显。

**实践建议**:
- 默认用 **Acquire / Release**(正确性优先)。
- 计数器用 **Relaxed**(性能优先)。
- 只在需要严格全局顺序时用 **SeqCst**(罕见,比如某些 GC 算法)。

### 8.5 happens-before 关系

内存序本质上是定义 **happens-before** 关系——"A 操作 happens-before B 操作,意味着 A 的效果对 B 可见"。

- 单线程:程序顺序 = happens-before。
- 多线程:线程 A 的 Release **synchronizes-with** 线程 B 的 Acquire,建立跨线程 happens-before。
- `join()`:线程 A join 线程 B,B 的所有操作 happens-before join 之后 A 的操作。

理解 happens-before 是写出正确并发代码的关键。

---

## 9 · Send 和 Sync

Rust 的并发安全靠两个 marker trait:

**Send**:类型 `T` 可以**跨线程 move**(所有权转移)。
**Sync**:类型 `&T` 可以跨线程共享(即 `&T` 是 Send)。

类型自动推导:
- `i32`, `String`, `Vec<T>`(若 T: Send):Send + Sync。
- `Rc<T>`:不 Send(引用计数非原子)。
- `Arc<T>`:Send(原子引用计数)。
- `Mutex<T>`:Sync(若 T: Send)。
- `Cell<T>` / `RefCell<T>`:不 Sync(内部可变性非线程安全)。
- `AtomicI32`:Send + Sync。

```rust
use std::rc::Rc;
use std::sync::Arc;
use std::thread;

let rc = Rc::new(5);
// thread::spawn(move || {            // 编译错误!Rc 不是 Send
//     println!("{}", rc);
// });

let arc = Arc::new(5);
thread::spawn(move || {               // OK,Arc 是 Send
    println!("{}", arc);
});
```

Rust 编译器在编译期拒绝不安全的跨线程传递。**这就是 Rust 的"无畏并发"**(fearless concurrency)——编译器帮你检查,你不会写错。

### 9.1 实现 Send / Sync

大多数类型自动推导。手动实现(unsafe)的情况:

```rust
struct MySmartPointer {
    ptr: *mut u8,  // 原始指针,默认不 Send 不 Sync
}

unsafe impl Send for MySmartPointer {}
unsafe impl Sync for MySmartPointer {}
```

这是 unsafe——你保证跨线程使用这个类型是安全的。FFI(包装 C 库)经常这么做。

---

## 10 · 无锁数据结构(概念)

无锁(lock-free)数据结构不用 mutex,用 CAS + atomic 实现并发安全。

**优点**:
- 无死锁(无锁可死)。
- 无抢占问题(线程不会卡在锁里)。
- 高吞吐(无系统调用)。

**缺点**:
- 难写对。ABA、内存回收、正确内存序——每个都能踩坑。
- 不一定快(高竞争时 CAS 重试风暴)。

### 10.1 Treiber Stack

经典无锁栈:

```rust
use std::sync::atomic::{AtomicPtr, Ordering};
use std::ptr;

struct Node<T> {
    val: T,
    next: *mut Node<T>,
}

struct TreiberStack<T> {
    head: AtomicPtr<Node<T>>,
}

impl<T> TreiberStack<T> {
    fn push(&self, val: T) {
        let node = Box::into_raw(Box::new(Node {
            val,
            next: ptr::null_mut(),
        }));
        loop {
            let cur = self.head.load(Ordering::Acquire);
            unsafe { (*node).next = cur; }
            if self.head.compare_exchange_weak(
                cur, node,
                Ordering::Release,
                Ordering::Relaxed,
            ).is_ok() {
                return;
            }
        }
    }
}
```

但要正确——ABA 问题、内存回收(hazard pointer / epoch-based reclamation)——是博士论文级别的话题。

Rust 生态 `crossbeam` 提供工业级无锁队列、栈。**不要自己写**。

工业实现留到 phase-4 的 lock-free-programming.md 深入。

---

## 11 · async / await

### 11.1 为什么有 async

线程的代价:
- 创建慢(~50 μs)。
- 切换慢(~1-10 μs)。
- 栈大(默认 2-8 MB)。

10 万并发连接 = 10 万线程 = 几百 GB 栈。不可行。

**协程(coroutine) / async task**:
- 创建快(几 ns)。
- 切换快(几 ns,纯用户态)。
- 栈小(几 KB,按需增长)。

10 万 async task = 几百 MB,可行。

### 11.2 async fn 的本质

```rust
async fn fetch_data() -> Vec<u8> {
    let resp = http_get("https://api.example.com").await;
    resp.bytes().await
}
```

`async fn` 不立即执行,而是返回一个 **Future**——一个状态机。`future.await` 推动状态机一步。

编译器把上面函数转换成大致:

```rust
enum FetchDataFut {
    Start,
    AwaitingHttpGet(HttpGetFut),
    AwaitingBytes(BytesFut),
    Done,
}

impl Future for FetchDataFut {
    type Output = Vec<u8>;
    
    fn poll(self, cx: &mut Context) -> Poll<Vec<u8>> {
        loop {
            match self.state {
                Start => {
                    let fut = http_get("...");
                    self.state = AwaitingHttpGet(fut);
                }
                AwaitingHttpGet(ref mut fut) => {
                    match fut.poll(cx) {
                        Pending => return Pending,
                        Ready(resp) => {
                            self.state = AwaitingBytes(resp.bytes());
                        }
                    }
                }
                AwaitingBytes(ref mut fut) => {
                    match fut.poll(cx) {
                        Pending => return Pending,
                        Ready(bytes) => {
                            self.state = Done;
                            return Ready(bytes);
                        }
                    }
                }
                Done => panic!("polled after completion"),
            }
        }
    }
}
```

每个 `.await` 是一个状态。poll 推进一步,如果还得等(Pending),返回,让 runtime 去跑别的 task;等到了被唤醒,继续 poll。

### 11.3 Tokio 运行时

`Future` 不自己跑——需要 **runtime** 来 poll 它。Tokio 是主流 Rust async runtime。

```rust
#[tokio::main]
async fn main() {
    // 主 task
    let result = some_async_op().await;
}
```

`#[tokio::main]` 把 main 包装成:
```rust
fn main() {
    tokio::runtime::Runtime::new()
        .block_on(async { /* 原 main */ });
}
```

Tokio 内部:
- **worker 线程池**:默认等于 CPU 核数。
- **任务队列**:每个 worker 有本地队列 + 全局队列(work-stealing)。
- **IO driver**:封装 epoll,异步处理 socket。
- **timer**:基于 timerfd / 最小堆的异步定时器。
- **reactor**:监听 IO 事件,唤醒等待的 task。

当你 `socket.read(&mut buf).await`,Tokio:
1. 把 socket 注册到 epoll,告诉内核"数据来了唤醒这个 task"。
2. 当前 task 返回 Pending。
3. Tokio 跑下一个 task。
4. epoll 通知"socket 有数据",Tokio 把对应 task 放回队列。
5. 该 task 重新 poll,这次 read 成功,返回 Ready。

**整个过程中,worker 线程没阻塞**——一直跑别的 task。这就是 async 的高效。

### 11.4 spawn task

```rust
#[tokio::main]
async fn main() {
    // spawn 一个 task(类似 thread::spawn,但更轻)
    let h1 = tokio::spawn(async {
        do_work().await
    });
    let h2 = tokio::spawn(async {
        do_other_work().await
    });
    
    let (r1, r2) = tokio::join!(h1, h2);  // 并发等待
}
```

10 万 `tokio::spawn` 没问题——每个 task 几 KB。这是 web server 高并发的基础。

### 11.5 spawn_blocking

async 函数里不能调阻塞 IO(如 `std::fs::read`),否则会**阻塞整个 worker**。要调阻塞代码,用 `spawn_blocking`:

```rust
let data = tokio::task::spawn_blocking(|| {
    std::fs::read("huge_file.bin").unwrap()
}).await.unwrap();
```

这把阻塞任务扔到**专用线程池**(默认 512 线程上限),不污染 async 线程。

---

## 12 · 实战:并发求和

我们做一个 benchmark,对比四种方式求和 1 到 1 亿:
1. 单线程
2. 多线程 + mutex
3. 多线程 + atomic
4. 多线程 + 本地计数器(最后合并)

```toml
[package]
name = "concurrent-sum"
version = "0.1.0"
edition = "2021"

[dependencies]
rayon = "1"
```

```rust
use std::sync::{Arc, Mutex};
use std::sync::atomic::{AtomicI64, Ordering};
use std::thread;
use std::time::Instant;

const N: i64 = 100_000_000;
const THREADS: usize = 8;

// 1. 单线程
fn seq_sum() -> i64 {
    (1..=N).sum()
}

// 2. 多线程 + mutex(差的实现)
fn mutex_sum() -> i64 {
    let result = Arc::new(Mutex::new(0i64));
    let chunk = N / THREADS as i64;
    
    let handles: Vec<_> = (0..THREADS).map(|i| {
        let result = Arc::clone(&result);
        thread::spawn(move || {
            let start = 1 + i as i64 * chunk;
            let end = if i == THREADS - 1 { N } else { start + chunk - 1 };
            for n in start..=end {
                let mut guard = result.lock().unwrap();
                *guard += n;
            }
        })
    }).collect();
    for h in handles { h.join().unwrap(); }
    let guard = result.lock().unwrap();
    *guard
}

// 3. 多线程 + atomic(较好)
fn atomic_sum() -> i64 {
    let result = Arc::new(AtomicI64::new(0));
    let chunk = N / THREADS as i64;
    
    let handles: Vec<_> = (0..THREADS).map(|i| {
        let result = Arc::clone(&result);
        thread::spawn(move || {
            let start = 1 + i as i64 * chunk;
            let end = if i == THREADS - 1 { N } else { start + chunk - 1 };
            for n in start..=end {
                result.fetch_add(n, Ordering::Relaxed);
            }
        })
    }).collect();
    for h in handles { h.join().unwrap(); }
    result.load(Ordering::Relaxed)
}

// 4. 本地 + 合并(最佳)
fn local_sum() -> i64 {
    let chunk = N / THREADS as i64;
    
    let handles: Vec<_> = (0..THREADS).map(|i| {
        thread::spawn(move || -> i64 {
            let start = 1 + i as i64 * chunk;
            let end = if i == THREADS - 1 { N } else { start + chunk - 1 };
            (start..=end).sum()
        })
    }).collect();
    
    handles.into_iter().map(|h| h.join().unwrap()).sum()
}

// 5. rayon(工业级)
fn rayon_sum() -> i64 {
    use rayon::prelude::*;
    (1..=N).into_par_iter().sum()
}

fn main() {
    let t = Instant::now();
    let s = seq_sum();
    println!("Sequential: {} ms  (sum={})", t.elapsed().as_millis(), s);
    
    let t = Instant::now();
    let s = mutex_sum();
    println!("Mutex:      {} ms  (sum={})", t.elapsed().as_millis(), s);
    
    let t = Instant::now();
    let s = atomic_sum();
    println!("Atomic:     {} ms  (sum={})", t.elapsed().as_millis(), s);
    
    let t = Instant::now();
    let s = local_sum();
    println!("Local:      {} ms  (sum={})", t.elapsed().as_millis(), s);
    
    let t = Instant::now();
    let s = rayon_sum();
    println!("Rayon:      {} ms  (sum={})", t.elapsed().as_millis(), s);
}
```

典型输出(8 核机器):

```
Sequential: 90 ms  (sum=5000000050000000)
Mutex:      5000 ms  (sum=5000000050000000)
Atomic:     800 ms   (sum=5000000050000000)
Local:      20 ms    (sum=5000000050000000)
Rayon:      15 ms    (sum=5000000050000000)
```

观察:
- **Mutex 比 sequential 慢 50×**:锁竞争成了瓶颈。
- **Atomic 比 mutex 快 6×**:但仍比 sequential 慢,因为 cache coherence 开销。
- **Local 比 sequential 快 4×**:无竞争,接近 8 核理论上限(实际 4× 因为 overhead)。
- **Rayon 比手写略快**:它的工作窃取(work-stealing)调度比静态分块好。

**教训**:
1. 共享可变状态慢。
2. 用 thread-local 或减少共享。
3. 用现成库(rayon、crossbeam),别造轮子。

---

## 13 · 四域深入

### 13.1 游戏编程视角

游戏并发结构:

**主线程 + worker 池**:主线程跑游戏逻辑,worker 跑可并行任务(物理、AI、路径寻找)。Unity、Unreal 的 Job System 如此。

**ECS + parallel for**:bevy 用 rayon-like 调度,自动并行 query。

**渲染线程 + 游戏线程**:游戏机传统——游戏逻辑一个线程,渲染命令另一个线程,异步提交。Casey 在 HH 里也提过这种模式。

**网络线程 + 游戏线程**:网络 IO 异步,游戏逻辑主循环不阻塞。

**Anti-pattern**:
- 跨帧持锁。
- 锁里调用 IO(放大持锁时间)。
- 锁粒度过大(锁整个世界而非单个 entity)。

工业库:
- **rayon**:数据并行。
- **crossbeam**:并发数据结构、scope、内存回收。
- **tokio**:异步 IO。
- **bevy-tasks**:bevy 抽取的并行任务库。

### 13.2 图形学视角

GPU 是**终极并行机器**——成千上万 core 同时跑。GPU 编程模型:
- SIMT(Single Instruction Multiple Threads):一批 thread 跑同一指令。
- Wavefront / Warp:32 或 64 thread 一组。
- Memory coherence:GPU cache coherence 比弱,要显式同步(`__syncthreads`)。

CPU 端的渲染,主要并发是**渲染线程 + 游戏线程**,通过 command buffer 解耦。游戏线程填命令,渲染线程消费。

### 13.3 Linux 系统编程视角

Linux 内核是**抢占式多任务**——内核可以抢占任何线程,调度别的。调度器(CFS - Completely Fair Scheduler)按"虚拟运行时间"排序,公平分配 CPU。

```bash
# 看调度策略
chrt -p $(pidof my_game)

# 设置实时优先级(游戏可以)
sudo chrt -f 80 ./my_game   # SCHED_FIFO,优先级 80

# 隔离 CPU(实时游戏)
# 启动参数:isolcpus=2,3  把核 2、3 隔离,普通进程不调度到这两个核
# 然后 taskset -c 2,3 ./my_game
```

**futex**(fast userspace mutex):Linux 的同步原语。无竞争时纯用户态(atomic),快;竞争时 syscall futex(WAIT 或 WAKE)。

```bash
# 看 futex 调用
perf stat -e syscalls:sys_enter_futex ./my_program
# 调用越多,锁竞争越激烈
```

### 13.4 Rust 生态视角

Rust 并发库分层:

**底层**:
- `std::thread`:OS 线程。
- `std::sync::atomic`:原子。
- `std::sync::{Mutex, RwLock, Condvar, Arc, Barrier}`:同步原语。

**中层**:
- `parking_lot`:更快的 mutex / rwlock / condvar。
- `crossbeam`:scope thread、无锁队列、epoch-based GC。
- `rayon`:数据并行。
- `flume` / `crossbeam-channel`:channel。

**异步**:
- `tokio`:工业级 async runtime。
- `async-std`:tokio 的早期替代,现在边缘。
- `smol`:更轻量。
- `glommio`:thread-per-core 模型。

**高级**:
- `bevy_tasks`:bevy 的任务系统。
- `actor-framework`(actix、Axiom):actor 模型。

---

## 14 · 认知地图

### 14.1 上级

- **分布式系统**:多机并发 = 单机并发的延伸。CAP 定理、共识算法都基于本篇概念。
- **操作系统**:线程调度、futex、信号量是 OS 核心。
- **形式化方法**:并发程序的验证(model checking、TLA+)。

### 14.2 同级

| 主题 | 关系 |
|---|---|
| 内存(本系列 24) | cache coherence、false sharing、内存序都依赖内存模型 |
| 网络(本系列 23) | async IO = 网络 + 并发 |
| 性能工程 | 多线程加速的极限 = Amdahl 定律 |

### 14.3 下级

- CPU 指令:`lock`、`mfence`、`lfence`、`sfence`(x86)、`dmb`(ARM)
- futex syscall
- Thread-local storage(TLS)
- AsyncFuture state machine
- Poll / Waker / Context

---

## 15 · 对照与变奏

### 15.1 跨语言并发

**C**:pthread,手动管理锁、原子。bug 多。

**C++**:std::thread、std::mutex、std::atomic。memory order 概念是 C++11 引入的,Rust 借鉴。

**Java**:synchronized、java.util.concurrent、volatile。GC 让内存管理简单,但并发逻辑仍复杂。

**Go**:**goroutine**——绿色线程,M:N 调度。channel 是一等公民("Don't communicate by sharing memory; share memory by communicating")。极简单。

**Erlang / Elixir**:actor 模型,每个 actor 一个进程,纯消息传递。

**Rust**:**async/await + Send/Sync 编译期检查**。学习曲线陡,但**无畏并发**——并发 bug 编译期消失。

### 15.2 历史演化

- **1960s**:Dijkstra 提出 semaphore、critical section。
- **1970s**:Hoare 提出 monitor、condvar。Unix 引入 pthread 草案。
- **1980s**:POSIX 标准化 pthread。
- **1990s**:多核 CPU 普及,无锁编程兴起。
- **2000s**:Java volatile / synchronized、C++11 std::atomic。
- **2010s**:async/await(C# / JS / Python / Rust)。Rust 1.0(2015)。
- **2020s**:io_uring(Linux 新异步 IO),Rust async 生态成熟。

### 15.3 并发的"暗面"

并发引入复杂度,代价是**正确性**。一些观察:
- 大部分并发 bug 在测试中不会出现(竞态需要特定时序触发)。
- 死锁可能在生产几周后才出现。
- 内存序错误在 x86 上工作、ARM 上炸(不同弱内存模型)。

工业实践:
- **静态分析**:Clang ThreadSanitizer、Rust 编译器。
- **运行时检测**:ThreadSanitizer、Helgrind。
- **形式化**:TLA+、Coq 验证关键算法。
- **简化设计**:actor 模型、消息传递减少共享状态。

---

## 16 · 关联 Day

- **铺垫**:[08-processes-and-signals.md](08-processes-and-signals.md) — 进程、信号
- **当天**:[25-concurrency-foundation.md](25-concurrency-foundation.md)(本篇)
- **后续**:[day078-memory-arena.md](../phase-3/day078.md) — Casey 的多线程;[day240-threading.md](../phase-5/day240.md)(假设)— 游戏多线程架构;[day400-lock-free.md](../phase-6/day400.md)(假设)— 无锁编程深入

---

## 17 · 变式训练

### Lv1 · 概念辨析

**题**:`Ordering::Relaxed` 和 `Ordering::SeqCst` 的差别?什么时候用哪个?

**参考答案**:

- **Relaxed**:只保证原子操作的"原子性",不约束其他内存访问的重排。计数器(如统计请求数)用——你只关心数,不关心和其他变量的顺序。
- **SeqCst**:全局严格顺序。所有 SeqCst 操作在所有线程看来是同一个全局顺序。代价高(需要 memory barrier)。

实践:
- 计数器、统计 → Relaxed。
- 发布数据(flag + payload)→ Release / Acquire 配对。
- 复杂的多变量同步 → SeqCst(谨慎,99% 场景用 Acquire / Release 够)。

### Lv2 · 动手实践

**题**:写一个并发安全的 LIFO 栈,要求:
1. 多线程 push / pop
2. 用 Mutex 实现(简单版)
3. 用 atomic + CAS 实现(无锁版)
4. benchmark 对比

**完成标准**:
- 单元测试正确(8 线程 × 100 万次 push/pop,栈空)
- mutex 版慢于无锁版

**参考解答**:

```rust
use std::sync::Mutex;

pub struct MutexStack<T> {
    inner: Mutex<Vec<T>>,
}

impl<T> MutexStack<T> {
    pub fn new() -> Self { Self { inner: Mutex::new(Vec::new()) } }
    pub fn push(&self, val: T) { self.inner.lock().unwrap().push(val); }
    pub fn pop(&self) -> Option<T> { self.inner.lock().unwrap().pop() }
}

// 无锁版(简化,未处理 ABA)
use std::sync::atomic::{AtomicPtr, Ordering};
use std::ptr;

pub struct LockFreeStack<T> {
    head: AtomicPtr<Node<T>>,
}

struct Node<T> { val: T, next: *mut Node<T> }

unsafe impl<T: Send> Send for LockFreeStack<T> {}
unsafe impl<T: Send> Sync for LockFreeStack<T> {}

impl<T> LockFreeStack<T> {
    pub fn new() -> Self { Self { head: AtomicPtr::new(ptr::null_mut()) } }
    
    pub fn push(&self, val: T) {
        let node = Box::into_raw(Box::new(Node { val, next: ptr::null_mut() }));
        loop {
            let cur = self.head.load(Ordering::Acquire);
            unsafe { (*node).next = cur; }
            if self.head.compare_exchange_weak(
                cur, node, Ordering::Release, Ordering::Relaxed
            ).is_ok() { return; }
        }
    }
    
    pub fn pop(&self) -> Option<T> {
        loop {
            let cur = self.head.load(Ordering::Acquire);
            if cur.is_null() { return None; }
            let next = unsafe { (*cur).next };
            if self.head.compare_exchange_weak(
                cur, next, Ordering::Release, Ordering::Relaxed
            ).is_ok() {
                let val = unsafe { Box::from_raw(cur).val };
                return Some(val);
            }
        }
    }
}
```

### Lv3 · 迁移设计

**题**:你有一个 1M entity 的游戏,每帧更新所有 entity。设计一个并行更新系统:
- 用 8 worker 线程
- 每个 entity 独立更新(无相互依赖)
- 主线程等待所有 worker 完成

回答:
1. 怎么分 chunk?(静态 / 动态?work-stealing?)
2. 主线程怎么等?(Barrier / join / condvar?)
3. 怎么测量加速比?
4. 怎么扩展到"entity 间有依赖"?

提示:用 rayon、crossbeam、或自研,各有利弊。

### Lv4 · 开源贡献

**题**:`crossbeam` 是 Rust 并发生态的核心库。`gh repo clone crossbeam-rs/crossbeam`。

1. 看 `crossbeam-epoch` 怎么实现 epoch-based GC(无锁内存回收)。
2. 看 `crossbeam-queue` 的 MSQueue / ArrayQueue。
3. 写一个 micro-benchmark,对比 std::sync::Mutex + VecDeque vs crossbeam ArrayQueue。
4. 提一个 PR(文档 / 测试 / 性能)。

---

## 18 · Rust / Arch 落地清单

### 18.1 装工具

```bash
sudo pacman -S valgrind          # 包含 helgrind、drd、memcheck
sudo pacman -S perf              # 性能分析
sudo pacman -S htop              # 进程 / 线程监视

# Rust 并发工具
cargo install flamegraph
cargo install cargo-llvm-lines   # async state machine 大小分析
```

### 18.2 线程监视

```bash
# 看进程的所有线程
ps -T -p $(pidof my_game)
ls /proc/$(pidof my_game)/task/

# 看每个线程的 CPU 占用
top -H -p $(pidof my_game)
htop  # H 切换线程视图

# 看上下文切换
pidstat -w -p $(pidof my_game) 1
```

### 18.3 锁分析

```bash
# helgrind 检测竞态 / 死锁
valgrind --tool=helgrind ./target/release/my_program
# 输出会指出可能的 race 和 lock order 问题

# drd(DRD)更现代
valgrind --tool=drd ./target/release/my_program

# ThreadSanitizer(更精准,但要重编译)
RUSTFLAGS="-Zsanitizer=thread" cargo +nightly build --release
./target/release/my_program
```

### 18.4 perf 分析

```bash
# 看锁相关
sudo perf stat -e syscalls:sys_enter_futex,syscalls:sys_exit_futex \
    ./target/release/my_program

# 锁热点
sudo perf record -g --call-graph=dwarf ./target/release/my_program
sudo perf report
# 看 __pthread_mutex_lock 占比

# futex 数过高 = 锁竞争激烈
```

### 18.5 strace 跟踪

```bash
# 看线程的 syscall
strace -f -e trace=futex,pthread_create,clone,sched_yield \
    ./target/release/my_program
# -f 跟踪所有线程
```

---

## 19 · Troubleshooting

**问题1**:多线程性能不如单线程。
诊断:perf top 看 `__pthread_mutex_lock`、`__pthread_rwlock_*`、`sched_yield` 占比高。修法:减少锁粒度、用 atomic、用 thread-local。

**问题2**:程序偶发 crash,栈是混乱的。
诊断:可能是数据竞争。Rust safe 代码不应该有,但 unsafe / FFI 可能。开 ThreadSanitizer:`RUSTFLAGS="-Zsanitizer=thread" cargo +nightly run`。

**问题3**:偶发死锁,生产环境几天才出现。
诊断:helgrind / drd 检测;或用 `gdb` attach 看所有线程栈(`thread apply all bt`)。常见原因:lock hierarchy 违反。

**问题4**:async task 永不返回。
诊断:可能 deadlock——某个 task 持锁等另一 task。或 `recv()` 在空 channel 上等。Tokio console(`tokio-console`)是 debug async task 的利器。

**问题5**:Tokio 程序 hang。
诊断:`tokio-console` 看 task 状态。或检查是否 `block_on` 在 async 上下文里(panic "Cannot block the current thread from within a runtime")。

---

## 20 · 延伸阅读

本仓库本地资料:
- [08-processes-and-signals.md](08-processes-and-signals.md) — 进程和信号
- [23-network-foundation.md](23-network-foundation.md) — 异步 IO 的应用
- [24-memory-foundation.md](24-memory-foundation.md) — cache coherence、false sharing

外部稳定 URL:
- Rust Atomics and Locks(Mara Bos):https://marabos.nl/atomics/
- The Rust Async Book:https://rust-lang.github.io/async-book/
- Tokio Tutorial:https://tokio.rs/tokio/tutorial
- C++ Memory Model(Hans-J. Boehm):https://www.hboehm.info/c++mm/
- Memory Barriers(Paul McKenney):https://www.kernel.org/doc/Documentation/memory-barriers.txt
- "Is Parallel Programming Hard, And, If So, What Can You Do About It?"(Paul McKenney):https://kernel.org/pub/linux/kernel/people/paulmck/perfbook/perfbook.html
- futex papers:https://www.akkadia.org/drepper/futex.pdf

真实开源源码:
- Rust std::sync:https://github.com/rust-lang/rust/tree/master/library/std/src/sync
- crossbeam:https://github.com/crossbeam-rs/crossbeam
- Tokio source:https://github.com/tokio-rs/tokio
- parking_lot:https://github.com/Amanieu/parking_lot
- Linux kernel locking:https://www.kernel.org/doc/html/latest/locking/index.html
