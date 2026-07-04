
# OS 调度、线程亲和性与实时优先级:从 CFS 到 NUMA

> 你的 HH 项目跑到 Day 250+,你按 [threading-models](threading-models.md) 拆出了 render thread 和 game thread,按 [threading-journey](../../phase-5/deep-dives/threading-journey.md) 把 audio 换成了 SPSC + lock-free。Tracy 上的 frame time 平时稳得像尺子画出来的 16.6ms,但每隔几秒会突然冒一根 40ms 的尖刺。你 zoom 进去,没有哪个 zone 慢——game logic 还是 4ms,render submit 还是 8ms,audio callback 还是 0.3ms。可整帧就是 40ms。你怀疑过 GC(你用 Rust,没有 GC)、怀疑过 driver、怀疑过 thermals,全都排除了。最后你打开 `perf sched` 看了一下,**发现那 40ms 的帧里,game thread 从 core 3 被搬到了 core 7,render thread 从 core 5 被搬到了 core 1**。它俩的 L1/L2 全是冷的,cache miss 飙了 8 倍。这 24ms 的"幽灵开销"不是你的代码慢,是 **OS 把你的线程搬家了**。这一篇讲清楚:Linux 内核怎么决定哪个线程跑在哪个核上、什么时候、跑多久;你怎么用 `taskset` / `chrt` / `sched_setaffinity` 看见并干预这个决定;render/gameplay 双线程 + 帧流水(pipelining)模型是怎么和调度器配合的;以及 NUMA 在多 socket 机器上为什么会让你的"随机"内存访问突然慢 4 倍。读完这一篇,你应该能在自己机器上用 `perf sched` 看见内核的调度决策,在 audio thread 上正确地申请 SCHED_FIFO 而不把系统锁死,并能解释为什么大多数商业游戏不手动 pin 线程、而你在嵌入式目标上必须 pin。

## 0 · 一根无法解释的尖刺

把场景焊死。你写了这样一个最小循环(节选自 [09B-1 游戏循环与固定步长](../../phase-9/09B-1-game-loop-and-timestep.md) 的扩展):

```rust
fn main() {
    let mut game = Game::new();
    let (tx, rx) = crossbeam_channel::unbounded::<FrameResult>();

    // render thread
    let render_handle = std::thread::Builder::new()
        .name("render".into())
        .spawn(move || {
            let mut renderer = Renderer::new();
            while let Ok(frame) = rx.recv() {
                renderer.submit(&frame);   // Tracy zone: render 8ms
            }
        })
        .unwrap();

    // game thread (main)
    loop {
        let frame_start = Instant::now();
        let state = game.step();            // Tracy zone: game 4ms
        tx.send(state.extract_render_snapshot()).unwrap();
        let elapsed = frame_start.elapsed();
        Tracy::frame_mark();
        if elapsed < Duration::from_millis(16) {
            std::thread::sleep(Duration::from_millis(16) - elapsed);
        }
    }
}
```

Tracy 给你的数字永远在合理范围:game zone 4ms,render zone 8ms,合起来 12ms,远低于 16.6ms 预算。但玩家反馈"偶尔卡一下",你自己也复现了——每 5-10 秒一根 30-40ms 的尖刺。把 game zone 内部每个子 zone 都点开,4ms 全在,没有空洞。**那多出来的 24ms 哪去了?**

答案在 Tracy 的"thread timeline"那一行。你切到 thread view,看到的是一根水平条,平时是连续的绿色(run),偶尔有一段灰色(idle/sleep),然后一段绿色。**那一段灰色就是 24ms**。你的线程没在跑你的代码,它在哪里?它在 runqueue 里等内核把它分发到核上,或者刚被搬到另一个核正在重新 warm cache。这不是你代码的 bug,是你和内核谈判失败的结果。要赢这场谈判,先理解内核这一侧。

## 1 · 内核这一侧:CFS 在做什么

你写的 `std::thread::spawn` 在 Linux 上最终调到 `clone(2)` 系统调用,内核给你造一个 task(线程)。这个 task 一旦成为 runnable(可运行,比如刚 spawn、刚被唤醒、时间片用完),它就进某个 CPU 核的 **runqueue**(运行队列)。问题是:进哪个核?什么时候被选中跑?跑多久?这三个决定构成了"调度策略"。

Linux 默认调度器叫 **CFS**(Completely Fair Scheduler,完全公平调度器),2007 年由 Ingo Molnärt 合入主线,跑在 `SCHED_OTHER` 类下(也叫 `SCHED_NORMAL`)。CFS 的目标如其名:**让每个 runnable 线程公平地分享 CPU**。它给每个线程维护一个 `vruntime`(虚拟运行时间),线程在核上跑多久,`vruntime` 就涨多少(还会按优先级 nice 值缩放)。runqueue 用红黑树按 `vruntime` 排序,**`vruntime` 最小的线程下一个跑**。这样长期跑的线程 `vruntime` 大,会"让"给长期等待的线程。听起来很美。

但"公平"和"游戏想要的"不是一回事。考虑 audio thread:它每 10ms 必须被唤醒一次去填 DMA buffer,否则喇叭就 glitch。在 CFS 看来,audio thread 醒来跑 0.3ms 又睡,它的 `vruntime` 涨得慢,看起来已经"很公平"了。可如果系统同时跑着一个 `make -j16` 的编译、一个 chrome 的 64 个标签、一个 OBS 编码器,这些线程的 `vruntime` 在和 audio 线程"公平竞争"。某个核的 runqueue 里塞了 30 个线程,CFS 给 audio 线程的"那一轮"可能排在第 15 位——它醒来的时机被推迟了 2ms,喇叭噼啪响。**CFS 没有承诺"audio 线程 10ms 一定跑"**,它只承诺"长期看大家份额公平"。游戏的实时性需求(每帧 16.6ms,audio 每 10ms 一次)和 CFS 的公平目标有**结构性冲突**。

context switch(上下文切换)是另一个隐藏税。当内核决定让线程 B 接管核、把线程 A 换下来,它要保存 A 的寄存器、FPU/MMX 状态、TLS 指针,加载 B 的对应状态。如果 A 和 B 属于不同进程,还要换 CR3(地址空间)。这一套下来在现代 x86 上 **3-10 μs**。听着不多,但你一帧只有 16666 μs。一个不必要的 context switch 就吃掉万分之几的预算。更要命的是**核间迁移**——内核把线程从 core 3 搬到 core 7。寄存器和地址空间好换,**L1/L2 cache 搬不了**。新核的 L1 是空的,你的 game state、render snapshot、texture descriptor 全要重新从 L3 或内存加载。冷 cache 访问比热 cache 慢 20-100 倍。一次迁移带来的 cache warm-up 成本可以轻松到 **几百 μs**,这就是你那 24ms 尖刺的主要来源。

你可以亲眼看内核在干什么。`perf sched` 是观察调度的瑞士军刀:

```bash
# 录 10 秒的调度事件
sudo perf sched record -- sleep 10
# 看每个线程被调度到的核的分布
sudo perf sched timehist -p $(pidof my_game) | head -30
```

输出里你会看到 `my_game` 这个线程被切来切去,每一行带 `[cpu]` 标记,告诉你它当时跑在哪个核。如果你的 game 线程在 10 秒内被切了 200 个核,那它平均每 50ms 就搬一次家——cache 根本来不及暖。这是诊断调度问题的第一手数据。

## 2 · 线程亲和性:把线程钉在核上

干预调度的第一个杠杆是 **CPU affinity**(CPU 亲和性)。每个线程有一个 `affinity mask`,一个 bitmap,bit i 置位表示这个线程**被允许**跑在 core i。默认 mask 是"所有核都行"(在 8 核机器上就是 `0xFF`),所以内核可以随便搬。你可以收紧这个 mask——比如只允许 game 线程跑在 core 2,那内核就没法搬它,它永远在 core 2 上,它的 L1/L2 永远是热的(对它访问的那些数据而言)。

Linux 提供 `sched_setaffinity(2)` 系统调用设置这个 mask:

```rust
use libc::{cpu_set_t, sched_setaffinity, CPU_ZERO, CPU_SET};

fn pin_to_core(cpu: usize) {
    unsafe {
        let mut set: cpu_set_t = std::mem::zeroed();
        CPU_ZERO(&mut set);
        CPU_SET(cpu, &mut set);
        // 0 = 当前线程
        let r = sched_setaffinity(0, std::mem::size_of::<cpu_set_t>(), &set);
        assert_eq!(r, 0, "sched_setaffinity failed");
    }
}
```

`CPU_ZERO` / `CPU_SET` 是 glibc 的宏,Rust 里通过 `libc` crate 调用。`pid=0` 表示当前线程(对线程来说 PID 其实是 TID,但你传 0 总是当前线程)。设置完,这个线程就被钉死了。

更直接的是命令行 `taskset`:

```bash
# 启动时就只允许跑在 core 2 和 3
taskset -c 2,3 ./my_game

# 对已经跑起来的进程,改它的 affinity(给 game 线程的 TID)
taskset -cp 2 $(pidof my_game)
# 注意 pidof 给的是主线程 TID,worker 线程要 ps -T 找
```

什么时候该 pin?这是关键判断,不能盲信"pin 总是好的"。pin 帮你的场景是:**工作负载稳定、热数据集合紧凑**。game thread 主循环每帧访问的就是那几个 GB 的世界状态,数据集合稳定,pin 在一个核上让那个核的 L1/L2 专门为这套数据"练手",性能可期。production 里的 audio thread 几乎总是 pin 的——它的工作集合小(几个 ring buffer + DSP 状态),且对 latency 极敏感,任何迁移都是风险。

pin 帮不到你甚至有害的场景是:**负载在核间严重不均衡、或工作集合远大于 cache**。假设你有 8 个 worker 线程,任务通过 rayon work-stealing 分发(见 [threading-models](threading-models.md) §3)。如果你强行 pin 每个 worker 到一个核,而某个核上的 worker 因为任务不均空闲了,内核没法把别的核上的工作搬过来——你失去了 work-stealing 的负载均衡收益。又比如一个扫整个 32GB 数据库的批处理任务,数据远超 L3,cache 命中率本来就接近 0,pin 不 pin 都一样,反而占了一个核别人用不了。

**经验法则**:pin 你**确定**工作集合稳定且热的线程(audio、game loop、render submit),让 worker pool 自由迁移(work-stealing 会自己均衡)。先量,再 pin,别相信"听说 pin 快"。

## 3 · 优先级与实时调度类

affinity 回答"哪些核",优先级回答"什么时候"。Linux 的调度不是单一策略,而是**调度类**(scheduling class)的栈,从高到低:

`stop_machine` > `SCHED_FIFO` / `SCHED_RR`(实时类)> `SCHED_OTHER` / `SCHED_BATCH` / `SCHED_IDLE`(普通类)> `SCHED_DEADLINE`。高调度类的 runnable 线程**绝对抢占**低调度类——只要有一个 `SCHED_FIFO` 线程 runnable,所有 `SCHED_OTHER` 线程一律没机会跑。这是关键。

你的 game 线程默认在 `SCHED_OTHER`,nice 值 0。你可以用 `nice` 或 `setpriority(2)` 调 nice 值,范围 -20 到 +19,数字越小优先级越高。但 nice 只是 CFS 内部 `vruntime` 的缩放因子,nice -20 的线程比 nice 0 的线程多得约 10 倍 CPU 份额——**但它仍然在 `SCHED_OTHER` 内,仍然要排队等编译、OBS、chrome**。nice 不足以保证实时性。

要真正保证"我醒了一定立刻跑",你要进实时调度类。`SCHED_FIFO`(先进先出)给线程一个 1-99 的优先级,**同优先级的线程按 FIFO 排队,没有时间片——只要你不 sleep / yield,你就一直跑**。`SCHED_RR`(round-robin)类似,但同优先级的线程轮流跑,每人一个时间片(默认 100ms)。对 audio 来说,你要的是 `SCHED_FIFO` + 高优先级——一旦 audio callback 醒来,它把编译、chrome 全部踢下核,直到它跑完回去 sleep。

设置实时优先级在 Rust 里:

```rust
use libc::{sched_param, sched_setscheduler, SCHED_FIFO};

fn make_realtime(priority: i32) {
    unsafe {
        let param = sched_param { sched_priority: priority };
        let r = sched_setscheduler(0, SCHED_FIFO, &param);
        if r != 0 {
            eprintln!("sched_setscheduler failed: errno = {}", std::io::Error::last_os_error());
        }
    }
}
```

或者命令行 `chrt`:

```bash
# 给 PID 12345 设 SCHED_FIFO 优先级 80
sudo chrt -f -p 80 12345
# 看某线程当前的调度策略
chrt -p $(pgrep my_game)
```

**实时权限是有门槛的**。普通用户默认没有 `CAP_SYS_NICE` 能力,直接 `sched_setscheduler` 到 `SCHED_FIFO` 会 `EPERM`。要拿到这个能力有三条路:(1) `sudo`(简单粗暴,生产不可行);(2) systemd 给你的 service 设 `LimitRTPRéaltime=yes` / `CapabilityBoundingSet=CAP_SYS_NICE`(服务器、嵌入式游戏机常用);(3) 内核启动参数 `threadedirqs` + rtkit 守护进程(桌面 audio 路径,PipeWire / PulseAudio 都走这条)。PipeWire 默认通过 rtkit 申请到 `SCHED_FIFO` 优先级 80,然后它的 audio callback 在那跑。

**能力越大,自杀越快**。`SCHED_FIFO` 线程的一个死循环会**永久独占一个核**,把同核上所有 `SCHED_OTHER` 线程饿死——包括你的 shell、你的 SSH 守护、甚至内核线程(如果它在那个核上)。早期 Linux 你甚至能锁死整个机器,只能硬重启。现代内核有两个保护机制:(1) **`rlimit(RLIMIT_RTTIME)`** 限制一个实时线程在 uninterrupted 状态下能跑多少 μs,超了内核强制把它降级回 `SCHED_OTHER`;(2) **`RT bandwidth control`**,通过 `/proc/sys/kernel/sched_rt_runtime_us` 和 `sched_rt_period_us` 控制全局——默认每 1 秒里最多 950ms 给实时类,留 50ms 给普通类,避免完全饿死系统。

生产游戏里用实时优先级的标准姿势是 **watchdog + 有限时段**。audio callback 不应该长跑——它每次醒来填一帧 buffer(几百 μs)就回去 sleep。如果你写的 callback 出 bug 进了死循环,rlimit 会救你。更稳的是自己写 watchdog:一个低优先级线程定时检查 audio callback 的进度计数器,如果计数器不增长,主动 `sched_setscheduler` 把 audio 降回 `SCHED_OTHER`。这种"自觉放弃权力"的设计是工程上负责任使用实时的标志,和"无脑 sudo chrt 99"是完全两种工程文化。

## 4 · render/gameplay 双线程模型与帧流水

到这里你已经理解了调度器和优先级,现在把它们和游戏引擎架构对起来。threading-models 讲了线程的抽象分类,但游戏引擎真正高频用的是**两个长寿命线程 + 帧流水(pipelining)**这个具体模型,这里把它的调度含义讲透。

设想一个最朴素的"主线程一切搞定"游戏循环:update 一帧 → render 一帧 → present → 下一帧。这种循环里,CPU 和 GPU 是**串行**的:CPU 在 update 时 GPU 闲着,GPU 在渲染时 CPU 闲着。一帧的 latency(输入到画面)是 1 帧。问题是浪费:你的 8 核 CPU 在 render 那段 8ms 里,有 7 个核在 idle。

双线程流水模型把 update 和 render 拆到两个线程:

```
时间 →  | frame N            | frame N+1          | frame N+2
game:   | update N           | update N+1         | update N+2
render: | render N-1         | render N           | render N+1
GPU:    |        execute N-2 |        execute N-1 |        execute N
```

注意三个层错开了。当 game thread 在 update N 时,render thread 在 render N-1,GPU 在 execute N-2。**三段并行**。CPU 利用率上去了,GPU 也不闲。代价是 latency 变成 3 帧(玩家输入到画面),但 60 FPS 下 3 帧 = 50ms,绝大多数游戏类型可接受(格斗 / 节奏游戏例外,要做输入补偿)。

数据怎么传?game thread update 出来的世界状态,**绝不能**直接交给 render thread 用——render thread 还在 render N-1,你改了状态它就 race 了。工业解法是 **double buffering**(双缓冲)或 **triple buffering**(三缓冲)状态快照:

```rust
struct Snapshots {
    // 三份游戏状态的 render-ready 副本
    buffers: [RenderSnapshot; 3],
    // game 写 game_writable,render 读 render_readable
    game_writable: usize,
    render_readable: usize,
}

impl Snapshots {
    // game thread 在 update 开始时拿到可写副本
    fn begin_game_frame(&mut self) -> &mut RenderSnapshot {
        &mut self.buffers[self.game_writable]
    }

    // game thread update 完,推进指针,通知 render
    fn publish_game_frame(&mut self) {
        self.game_writable = (self.game_writable + 1) % 3;
        // 通过 SPSC channel 把新可读索引发给 render thread
    }

    // render thread 取最新可读副本去画
    fn begin_render_frame(&self) -> &RenderSnapshot {
        &self.buffers[self.render_readable]
    }
}
```

为什么三个 buffer 而不是两个?两个的话,game 想写时 render 还在读,你必须等。三个的话,game 永远有一个"完全空闲"的 buffer 可以写,render 永远有一个"刚发布稳定"的 buffer 可以读,中间隔一个。这是无锁 pipelining 的关键。SPSC channel(见 [threading-journey](../../phase-5/deep-dives/threading-journey.md) §3)传索引,索引本身是 `usize`,Release/Acquire ordering 完美覆盖。snapshot 本身尽量做成**值类型 / arena-allocated**(见 [arena-allocator](arena-allocator.md)),避免指针追到 game thread 正在写的内存。

现在调度器登场。这两条流水线线程谁先跑?**它们必须几乎同时开始**。如果 game 线程醒来晚了 5ms,render 线程那一帧就晚了 5ms,GPU 闲 5ms,到 vsync 时 present 不出来,掉帧。这就是为什么 render/gameplay 双线程对调度抖动极敏感——任何一条流水线被内核延迟,整条流水线就抖。你在 §1 看到的"无法解释的尖刺",在流水线模型里会被放大:game 线程迁移一次,render 线程那一帧也跟着晚,组合起来 frame time 翻倍。

[preflight §2 of 09B-1](../../phase-9/09B-1-game-loop-and-timestep.md) 讲过固定步长循环靠累加器消费现实时间。流水线模型下,累加器要同时管"现实时间 → game step"和"game step → render submission"两个相位。Casey 在 HH 没走到双线程,但工业引擎(Unreal、Unity、Bevy)全是这套。从单线程 HH 走到双线程,你需要重写 [09B-1 那个循环](../../phase-9/09B-1-game-loop-and-timestep.md),把"update + render 一坨"切成两个 phase,用 SPSC channel 同步,然后在 Tracy 里看两条 timeline 的对齐情况。

## 5 · cache-aware 调度与 NUMA

到这里都是单 socket(单 CPU 封装、所有核平等)的世界。一旦你的目标硬件是多 socket 服务器或 Threadripper / EPYC 这种 chiplet 架构,**内存不再是平等的距离**——这就是 **NUMA**(Non-Uniform Memory Access,非均匀内存访问)。

NUMA 的物理:一块双路主板上插了两个 CPU,每个 CPU 有自己直接挂的内存(本地 DRAM),两个 CPU 之间用一条高速互联(Intel UPI、AMD Infinity Fabric)连。core 0(CPU 0)访问 CPU 0 的本地内存是 ~80ns,访问 CPU 1 的本地内存要走互联,~140ns。差距快 2 倍。chiplet 架构更细——一个 EPYC 64 核是 8 个 8 核 chiplet,每个 chiplet 有自己的 L3 和本地内存控制器,跨 chiplet 访问慢 1.5-3 倍。

这对游戏意味着什么?对单机游戏影响小,因为单机游戏一般跑在单 socket 消费级 CPU 上,所有核平等。但**思路**——"线程访问的数据应该靠近线程跑的核"——在所有架构上都对。具体说就是 cache-aware(缓存感知)的线程安排:

(1)**热数据要"原地热"**。如果一个线程每帧访问某个 4KB 的世界状态,这个状态应该尽量留在这个线程常驻核的 L2 里。affinity pin 是手段之一;另一个手段是**避免这个核上跑其他会冲刷 cache 的工作**——比如不要把 game thread 和一个 worker pool 抢同一个核,worker pool 的不同数据会把 game 的热数据挤出 L2。

(2)**线程间共享的数据要就近放**。如果 game thread 和 render thread 都读 snapshot,这两个线程最好在同一个 chiplet / 同一个 cache 域里,snapshot 的副本不用跨 chiplet。Linux 给你 `numactl --cpunodebind=0 --membind=0` 来控制"线程跑在哪些核 + 内存从哪个 NUMA node 分配"。

```bash
# 让 game 跑在 NUMA node 0 的核上,内存也从 node 0 分配
numactl --cpunodebind=0 --membind=0 ./my_game

# 看系统的 NUMA 拓扑
numactl --hardware
# 看 PID 的内存分布在哪些 node
numastat -p $(pgrep my_game)
```

NUMA-aware 的内存分配是更深的一步。Rust 默认的 `std::alloc::System` 走 glibc malloc,glibc 在多 NUMA node 上默认是"first-touch"策略——内存分配在哪页由第一次写它的线程所在的 node 决定。所以**谁先碰这块内存,这块内存就"长"在谁的本地 DRAM 上**。这意味着你在 game thread 里 `Vec::new` 然后填满的数据,默认就在 game thread 的 NUMA node 上;如果你后来把它 send 给 render thread,render thread 在另一个 node,每次访问都跨互联。NUMA 优化的代码会在"哪个线程将来主要读它"的那个线程上做第一次填充,这一招叫 first-touch placement。

游戏服务器(大型 MMO、专用服务器)是真用 NUMA 优化的,因为它们跑在双路 / 四路服务器上,玩家连接的 zone 分布在不同 NUMA node 上能榨出 30%+ 吞吐。单机游戏基本不需要,但你理解了 NUMA 就理解了"为什么 cache locality 不只是数据布局问题,也是线程拓扑问题"。

## 6 · 把工具凑齐:诊断调度问题

讲了一堆原理,落到工程是**怎么看见内核在干什么、怎么定位那根尖刺**。Linux 给了一套相互补充的工具,每个看一个层面。

**`/proc/<pid>/status`** 是静态视图。看你的进程现在的调度策略和 nice:

```bash
grep -E "Mems_allowed|voluntary_ctxt|nonvoluntary" /proc/$(pgrep my_game)/status
```

`voluntary_ctxt_switches` 是线程主动 sleep / yield 引起的切换(正常,你 sleep 等下一帧就计这里)。`nonvoluntary_ctxt_switches` 是内核**强制**把你换下来(时间片用完或更高优先级线程抢占)。**非自愿切换多 = 你被内核干扰得多**。一个稳定的 60 FPS 游戏主线程,`nonvoluntary` 每秒应该 < 100 次。如果你看到每秒上千次,你的优先级太低或核上有太多竞争者。

**`/proc/<pid>/sched`** 给更详细的调度统计,包括 `nr_switches`(总切换)、`nr_migrations`(核间迁移次数)、`se.sum_exec_runtime`(实际跑的时间)。`nr_migrations` 高就是 §1 那个尖刺的元凶。

**`perf sched`** 是动态 trace 工具,前面用过。它采内核的 `sched:sched_switch` tracepoint,记录每次切换的 from / to / cpu / reason。深入用法:

```bash
# 录
sudo perf sched record -a -- sleep 10
# 看"哪些线程被切换了、什么时候"
sudo perf sched timehist -p $(pgrep my_game)
# 看每个线程在每个核上跑了多久(summary)
sudo perf sched map | head
```

`perf sched map` 给你一张 ASCII 地图,行是时间,列是核,每格是该时刻那个核在跑哪个线程。你能直观看见你的 game thread 在核之间跳来跳去。如果它一秒钟跳 50 个核,这就是问题。

**`chrt -p`** 看优先级。**`taskset -p`** 看 affinity mask:

```bash
taskset -p $(pgrep my_game)
# 输出: pid 12345's current affinity mask: ff
# ff = 所有 8 个核都允许
```

**`htop`** 在按 F2 → Display options → 开 "Show custom thread names",再按 H 切到线程视图,能实时看每个线程跑在哪个核、CPU% 多少。这是快速的"现场快照"。

把这些工具串起来的诊断流程:(1) Tracy 看到一根尖刺;(2) `perf sched` 录复现期,看尖刺时刻是否伴随核间迁移;(3) `/proc/<pid>/sched` 看 `nr_migrations` 累积值是否异常高;(4) 如果是迁移,用 `taskset` pin 看是否消失;(5) 如果是优先级问题(被 chrome 抢了),考虑 nice 或 SCHED_FIFO。**永远先诊断再优化**,否则你会去改一段根本不慢的代码。

## 7 · 在你 HH 项目里动手(做中学红线)

理论不落到自己代码上不算学会。这条红线带你从零用一遍 §1-6 的全部工具,在你自己的 HH 项目(或上面那个最小双线程 demo)上做四件事:

**实验 1:量你的线程被搬了多少次家。** 启动你的游戏,跑 60 秒,期间:

```bash
PID=$(pgrep -n my_game)   # 假设你的 binary 叫 my_game
# baseline: 记录迁移总数
grep nr_migrations /proc/$PID/sched
sleep 60
grep nr_migrations /proc/$PID/sched
# 算差值
```

差值除以 60 就是每秒迁移次数。如果 > 10 次/秒,你的线程在频繁搬家。再分线程看:`ps -T -p $PID` 列出每个 TID,对每个 TID grep `/proc/<tid>/sched`,看是 game 还是 render 在迁移。

**实验 2:pin game 线程到一个核,看 frame time variance 变化。** 用 Rust 在 game thread 入口加 `pin_to_core(2)`,render thread 加 `pin_to_core(3)`。开 Tracy 录 5 分钟,导出 frame time 的统计:**p50 / p99 / max**。然后注释掉 pin 代码,重录 5 分钟,导同样统计。对比。你应该看到 pin 之后 p99 显著降低(比如从 22ms 降到 17ms),p50 几乎不变(pin 不让单帧变快,只让尾部长尾变短)。这是 affinity 帮你的硬证据。

也试试反面:**pin game 到一个核、render 到同一个核**。frame time 应该崩——两个线程抢一个核,work-stealing 都救不了。这一步让你体会"pin 不能瞎 pin,负载均衡是另一条腿"。

**实验 3:给 audio thread(或模拟的实时线程)上 SCHED_FIFO。** 如果你还没接 cpal,写一个最简的"伪 audio"线程——每 10ms 醒来跑 200μs,跑 1000 次。测它的唤醒延迟(实际醒来时间 - 计划醒来时间)的 p99。然后用 `sudo chrt -f -p 80 <tid>` 把它提到 SCHED_FIFO 80,重测。p99 应该从几百 μs 降到几十 μs。

```bash
# 找伪 audio 线程的 TID
ps -T -p $(pgrep my_game) | grep fake_audio
# 提到 SCHED_FIFO 80
sudo chrt -f -p 80 <tid>
# 看
chrt -p <tid>
```

**同时观察副作用**:开个 terminal 跑 `stress -c 8`(8 核满载),看伪 audio 线程在没有 SCHED_FIFO 时会不会被压得唤醒延迟飙到几十 ms。开 SCHED_FIFO 后再看。这是"实时优先级把别的线程踢下核"的直观演示。

故意造一个 bug:在伪 audio 线程里写个死循环 `loop {}`,开 SCHED_FIFO,看你的 shell / 鼠标还能不能动(现代内核 RT bandwidth 应该保住系统,但你那个核会被锁)。**这是为什么前面强调 watchdog + rlimit**——亲手把脚打穿一次,你就理解工程纪律为什么存在。

**实验 4:`perf sched` 抓尖刺。** 在跑实验 1 时同步开 `sudo perf sched record -a -- sleep 60`,然后 `sudo perf sched map | grep my_game`。看 ASCII 地图上你 game 线程跑过的核的轨迹。在 Tracy 里定位一个尖刺帧的时刻,在 perf sched 输出里找那个时刻附近的事件——大概率你会看到 game 线程正好被搬到另一个核。

做完这四个实验,你应该能:(1) 用 `taskset` / `sched_setaffinity` pin 线程;(2) 用 `chrt` / `sched_setscheduler` 提优先级;(3) 用 `/proc/<pid>/sched` + `perf sched` 看见内核决策;(4) 在 Tracy 里区分"我的代码慢"和"调度抖动"——前者 zone 长出来,后者 zone 之间有灰色 gap。最后一点是重点:**当 frame time 出问题,先排除调度,再 profile 代码**。太多程序员把 24ms 的迁移开销算到 bloom pass 头上,优化半年没改善。

## 8 · 练习

**Lv1**。写一个 Rust 程序,起 4 个线程每个跑空循环 10 秒,用 `taskset` 把它们分别 pin 到 core 0-3。`time` 程序运行时间,对比"pin 到 4 个不同核"vs "全部 pin 到 core 0"。理解时间差是怎么来的(context switch 串行 vs 并行)。

**Lv2**。写一个伪 audio 线程:每 10ms 唤醒,跑 200μs 工作,记 100 次的实际唤醒延迟。算 p99。(a) baseline SCHED_OTHER;(b) nice -20;(c) SCHED_FIFO 80。开 `stress -c $(nproc)` 制造背景压力,三种情况各测一次。报告 SCHED_FIFO 相对 baseline 的 p99 改善倍数,并解释 nice -20 为什么改善有限。

**Lv3**。在你 HH 项目(或最小双线程 demo)上加一个开关:`--pin`(pin game/render 到固定核)和 `--no-pin`(默认)。Tracy 录两种各 5 分钟的 frame time,导出 CSV,写个 Python 脚本算 p50/p95/p99/max。贴对比图。讨论:p99 改善多少?有没有副作用(p50 变差?某些核热?)?

**Lv4**。读 Linux 内核源码 `kernel/sched/fair.c`(CFS 主体)和 `kernel/sched/core.c`(`sched_setaffinity` 实现),写一份 1-2 页的笔记回答:vruntime 是怎么算的?为什么 CFS 选红黑树而不是堆?sched_setaffinity 之后线程一定立刻在新核上跑吗?如果要给 Bevy 的 [ecs-system-scheduling](../../phase-5/deep-dives/ecs-system-scheduling.md) 加一个 NUMA-aware 的 system 分配策略,你会怎么设计?提一个 doc issue。

## 9 · 延伸阅读

本仓库本地资料:
- [threading-models](threading-models.md) —— 线程池 / work-stealing / rayon,这一篇的抽象前提
- [threading-journey](../../phase-5/deep-dives/threading-journey.md) —— Mutex → lock-free 演化,audio SPSC ring 那一段是本文 §3 实时优先级的应用场景
- [lock-free-programming](lock-free-programming.md) —— 调度抖动 + lock-free queue 是实时线程的完整解
- [ecs-system-scheduling](../../phase-5/deep-dives/ecs-system-scheduling.md) —— Bevy / Unity DOTS 怎么在调度器之上做 system 并行,本文 §4 双线程是它的最小版
- [09B-1 游戏循环与固定步长](../../phase-9/09B-1-game-loop-and-timestep.md) —— 累加器 + 固定步长,本文 §4 帧流水要扩展那个循环
- [phase-0/25 并发基础](../../phase-0/25-concurrency-foundation.md) —— 线程 / 进程 / 调度的入门地基

外部稳定 URL:
- Linux kernel `sched(7)` man page:`man 7 sched`,调度类 / 优先级 / affinity 一页全有
- Daniel Borkmann, "CFS scheduler" slides(找带 vruntime 推导那版)
- Ingo Molnärt 2007 原始 CFS 合并邮件列表帖:lkml.org
- Jonathan Corbet, "CFS group scheduling" LWN.net 文章系列
- "RealtimeKit"(rtkit)项目,桌面 audio 怎么负责任地拿 SCHED_FIFO:git.0pointer.net
- "The Linux Programming Interface", Michael Kerrisk, 第 35 章(SCHED 策略)
- LWN.net 关于 RT bandwidth control 和 RLIMIT_RTTIME 的文章
- perf sched 文档:`perf sched --help` 和 `man perf-sched`
- Intel / AMD 关于 UPI / Infinity Fabric latency 的 whitepaper(NUMA 一节的事实来源)
- Valve Steam Deck / RADV 团队关于 game thread pinning 的博客(嵌入式目标上为什么真的 pin)
- Mara Bos, "Rust Atomics and Locks" 第 10 章,线程底层和系统调用的 Rust 视角

真实开源源码:
- Linux kernel `kernel/sched/fair.c`(CFS)、`kernel/sched/rt.c`(实时类)、`kernel/sched/core.c`(affinity)
- Bevy 的 `bevy_tasks` 和 `bevy_ecs` scheduler:github.com/bevyengine/bevy
- PipeWire 的 realtime 句柄:gitlab.freedesktop.org/pipewire/pipewire
- crossbeam-deque 的 worker pinning 相关讨论:github.com/crossbeam-rs/crossbeam
