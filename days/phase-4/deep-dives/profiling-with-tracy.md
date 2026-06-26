---
title: "Profiling with Tracy Deep Dive"
subtitle: "从零写 zone macro → Tracy v0.11 架构 → GPU timestamp → 集成进 HH 项目"
type: deep-dive
phase: 4
domains: [game, graphics, rust, linux, performance]
duration: "8-10h"
---

# Profiling with Tracy 完整深度专题

> 你跟着 Handmade Hero 走到 Day 138 写了第一个 profiler overlay——简单地在主循环里抓 `Instant::now()` 算每个子系统的耗时,然后画到屏幕右上角。你在 Day 184 又升级了一次,加了 frame time 图。你打开 Steam,看见游戏在 60 FPS 跑得很顺,自我感觉良好。然后你按 F2 加了一个新功能——bloom 后处理。游戏卡到 30 FPS。你盯着自己的 profiler overlay,它告诉你"render: 28 ms",但**它不告诉你 bloom 究竟卡在哪一步**:是高斯模糊的水平 pass?是 downsample?是 final composite?还是某个 uniform 上传?你意识到自己的 profiler 给你**总数**,但**不给调用栈**。今天我们要装一个真正的 profiler——Tracy——它能告诉你"在 28 ms 的 render 里,bloom_horizontal_pass 的第 23 行占 4.2 ms,因为它在内层循环里调用了 `texture.Sample()` 64 次"。这一篇从零讲清楚:profiling 三大流派、Tracy 的 capture/server/client 三段架构、zone/plot/frame/lock 五类核心原语、Rust 集成的两条主流路线(tracy_client 裸用 vs tracing-tracy 组合)、GPU timestamp 怎么抓、Chrome Tracing JSON 这个开源标准为什么是工业通用语言、以及 5 个真实性能 bug 的调试全过程。读完这一篇,你能在自己 HH 项目里 30 分钟接入 Tracy,并能给 tracy_client crate 提一个有意义的 PR。

## 0 · 为什么要有这一篇

Profiling(性能剖析)这件事,新手觉得"装个工具跑一下看数字",老手觉得"工具会骗你,数据才不会"。两边的认知鸿沟,藏在这三个事实里:

**事实一:profiling 不是测量,是采样 + 重建**。当你打开 perf record 或者 Tracy,你以为是"真实地测了 CPU 在干什么",其实你拿到的是**一组样本**——profiler 每隔 1ms 中断一次,记录当前 PC(程序计数器)和调用栈,然后从这些样本**统计推断**"哪段代码花了多久"。Instrumentation(埋点)派则相反——你手动在代码里写 `zone_begin("foo")` / `zone_end("foo")`,工具精确记录这两点之间的时间。两派各有代价:sampling 精度低但零代码改动,instrumentation 精度高但要手埋点。**真实生产里你两派都要用**,采样派做"哪段代码热点"的快速侦察,埋点派做"这段热点内部到底什么慢"的深度调查。这就是为什么 Casey 在 HH 里同时用 simple profiler(自己写的埋点)和 superluminal(商业采样 profiler)。

**事实二:profiler 给你的"数字"本身就有 bias**。最经典的例子是 **Heisenberg effect**(观察者效应)——你给一段代码加 profiler 埋点,埋点本身要花时间(写 timestamp 到 thread-local buffer,~50ns),这段额外时间被算进"代码耗时"。一段真实耗时 100ns 的函数,profile 显示 200ns,你以为是 hotspot,其实是 profiler 自己。Tracy 通过极小心的 lock-free queue + per-thread buffer 把这个 overhead 压到 ~10ns/zone,所以 Tracy 能 profile 数百万 zone / 帧。商业 profiler Superluminal 更狠,宣称 <5ns/zone。你不知道这些数字,profile 数据会让你误判方向。

**事实三:profiler 是后期 5% 价值,前期 95% 麻烦的工具**。新手装 profiler 太早,每天看一堆自己看不懂的图,陷入"调参焦虑"。资深工程师的原则:**先写正确性,再写可读性,最后才写性能**。在性能成为瓶颈前不装 profiler,装上之后只用它定位**具体瓶颈**,定位完就关掉。Casey 在 HH Day 134 第一次开 profiler 是因为"游戏从 60 掉到 30 FPS",定位完是 sound mixing 卡顿,改完关掉 profiler 再也没开过——直到 Day 200 又卡了。这是工业级态度。

这三件事合起来意味着:**profiler 不是"装上就好"的工具,是"理解清楚才能用对"的工具**。本篇全文都是"理解清楚"。

读者基线假设:你完成了 Phase 0(24-memory / 25-concurrency)+ Phase 4 的 atomics + Phase 5 Day 176 的 debug overlay。也就是说:

- 你写过 `Instant::now()` 测时间,知道 nanosecond / microsecond / millisecond 的换算
- 你理解 thread、atomic、lock-free queue 的基本概念
- 你写过 simple immediate-mode debug overlay,知道 frame budget 怎么画
- 你不知道的是:**怎么从"我大概知道这段慢"升级到"我精确知道哪行慢、慢多少、为什么慢"**

这就是今天的主题。

**学完这一篇,你应该能**:

- 解释 profiling 三大流派(Instrumentation / Sampling / Tracing)的差别,知道何时选哪个
- 解释 Tracy 的 capture / server / client 三段架构,知道每段跑在哪台机器上、用什么协议通信
- 写一个 Rust zone macro,把任意函数自动包成 Tracy zone(用 `#[tracing::instrument]` 或自己写 proc macro)
- 抓 GPU timestamp,定位 shader 卡顿的**真正原因**(不是 frame 时间,是某个 draw call 在 GPU 上跑了多久)
- 解释 Chrome Tracing JSON 格式,知道为什么这是工业通用 profiler 格式,能自己生成一份给 Perfetto / chrome://tracing 打开
- 在你 HH 项目里 30 分钟接入 tracy_client,抓出第一个 zone 数据
- 给 tracy_client crate 或 Tracy 本体提一个有意义的 PR

## 1 · Profiling 三大流派

我们要从头讲。先确认你脑子里"profiler"的定义,然后逐步往里加复杂度。

### 1.1 Instrumentation(埋点派)

**Instrumentation** 是最古老最朴素的 profiler 形式——**在代码里手动埋点,记录两点之间的时间**。

最原始的 instrumentation 你已经在 HH Day 138 写过:

```rust
fn update(state: &mut State) {
    let t0 = std::time::Instant::now();
    physics_step(state);
    let t1 = std::time::Instant::now();
    state.profile.physics_us = t1.duration_since(t0).as_micros() as u64;
    
    let t0 = std::time::Instant::now();
    ai_step(state);
    let t1 = std::time::Instant::now();
    state.profile.ai_us = t1.duration_since(t0).as_micros() as u64;
    
    // ...
}
```

这是 instrumentation 的最小原型——三个要素:

1. **Begin timestamp**:`Instant::now()` 抓起点
2. **End timestamp**:`Instant::now()` 抓终点
3. **Storage**:差值存到 `state.profile.xxx_us`

优缺点一目了然:

| 优点 | 缺点 |
|---|---|
| 精度高(nanosecond 级别) | 要手动埋点,代码侵入大 |
| 调用栈明确(你写的就是这个函数) | 不能记录"没埋点"的代码 |
| 可生产部署(开销可控) | 多线程不直观(每线程一份 buffer) |
| 工具无关(纯 timestamp) | 改函数名 / 重构要更新埋点 |

工业级的 instrumentation profiler(Tracy、Optick、Superluminal)都在这个基础上做扩展:把 begin/end 改成 macro 自动 RAII,把 storage 改成 lock-free queue 异步发送,把"调用栈明确"扩展成支持 zone 嵌套(parent/child 关系)。

### 1.2 Sampling(采样派)

**Sampling** profiler 不需要你改代码——它**周期性中断程序**,记录当前 PC 和调用栈。

Linux 上最经典的是 `perf`:

```bash
# 每 1ms 中断一次,CPU 周期计数器触发
sudo perf record -F 1000 -g ./game
# -F 1000:采样频率 1000 Hz(每秒 1000 次)
# -g:记录调用栈(dwarf 模式或 fp 模式)

# 分析
sudo perf report
# 输出按"函数在样本中出现的频率"排序
# 例如:
#  23.5%  game   game.so   physics_step
#  18.2%  game   game.so   b2_world_solve
#   9.1%  game   game.so   ai_pathfind
```

`perf` 报告告诉你"在 10000 个样本里,23.5% 落在 physics_step 里"——意味着大约 23.5% 的 CPU 时间花在 physics_step。这是统计推断,不是直接测量。

优缺点:

| 优点 | 缺点 |
|---|---|
| 零代码改动 | 精度受采样频率限制 |
| 抓**整个程序**(包括库函数) | 短函数(<1ms)可能完全抓不到 |
| 真实生产环境可跑 | 多线程需要特殊处理(per-event) |
| 系统 level(CPU / cache miss / branch miss) | 调用栈展开慢,可能漏帧 |

`perf` 还能抓硬件事件:

```bash
# 同时抓 cache miss 和 branch mispredict
sudo perf stat -e cycles,instructions,cache-misses,branch-misses ./game
# 输出:
#  234,567,890      cycles
#  198,765,432      instructions  # IPC = 0.85,有点低(健康 > 1)
#    1,234,567      cache-misses   # 占 0.6% of all cache accesses
#       12,345      branch-misses  # 占 0.01% of branches
```

这些数字告诉你 CPU 在**真实硬件**上的表现。Cache miss 多——你的数据布局有问题(数组 of struct 改 struct of array)。Branch miss 多——你的 if/else 分支不可预测(改成 branchless 或排序数据)。这些是 instrumentation profiler 看不到的——instrumentation 只能告诉你"花了多久",不能告诉你"为什么花这么久"。**为什么花这么久只有 sampling 能告诉你**。

Rust 生态的 flamegraph crate:

```bash
# 装
cargo install flamegraph

# 一键生成 SVG 火焰图
cargo flamegraph --bin game
# 它自动调 perf record + stackcollapse + flamegraph.pl
# 输出 flame.svg,浏览器打开
```

火焰图是采样 profiler 数据的经典可视化——横向是时间(或样本数),纵向是调用栈,每格是一个函数。一眼看出热点在哪一层。

### 1.3 Tracing(追踪派)

**Tracing** 是 instrumentation 的"重型版"——不只是 begin/end,还记录**事件之间的因果关系**(哪个事件触发了哪个)。

Tracing 的特征:

1. **每事件带时间戳**(和 instrumentation 一样)
2. **每事件带因果关系**(parent / child / continuation)
3. **每事件带类型**(CPU zone / GPU zone / lock acquire / memory alloc / frame boundary / plot value)
4. **可视化成时间线**(不是火焰图,而是甘特图)

**Tracy 是这一派的代表**。打开 Tracy 你看到的不是火焰图,是时间线——每个 CPU 一个 lane,lane 上是 zone(彩色矩形),zone 可以嵌套(zone 里套 zone),还有 lock 等待区(灰色块)、memory alloc 标记(小三角)、plot 曲线(任意数值随时间变化)。这就是为什么 Tracy 适合"卡顿调试"——你能看见帧 N 卡顿时,所有 8 个线程到底在干什么,谁在等谁。

这三个流派不是互斥的——Tracy 同时支持 instrumentation(你手动写 `ZoneScoped`)和 sampling(它内置 callstack sampling,每秒抓 500 次)。所以 Tracy 是"以 instrumentation 为主、sampling 为辅"的混合。

下面这张表把三派并列对比:

| 维度 | Instrumentation | Sampling | Tracing |
|---|---|---|---|
| 代码改动 | 中(手动埋点) | 零 | 中-高(深度集成) |
| 精度 | 高(精确时间) | 中(统计推断) | 高(精确时间) |
| 调用关系 | 静态(你写的) | 动态(采样抓的) | 静态+因果 |
| 多线程 | 手动 per-thread | 自动 | 自动(每线程 lane) |
| 开销 | 低(~10ns/zone) | 极低(零代码) | 低-中(~50ns/zone) |
| 典型工具 | Manual `Instant`, Optick | perf, VTune, Superluminal | Tracy, Chrome Tracing |
| 适合 | 已知热点定位 | 热点发现 | 卡顿 / 多线程调试 |

工业实践是**三派结合**:用 sampling 发现"大概哪段慢",用 instrumentation 精确测量,用 tracing 看多线程时序。Casey 在 HH 用的是"sampling(Superluminal) + 自己写的 instrumentation(profiler overlay) + 后期偶尔 Tracy"。这就是为什么 Casey 能在视频里说"这个卡顿是 sound mixing 的某个循环"——他用 sampling 找到大概位置,用 instrumentation 精确定位。

## 2 · Tracy 完整架构

我们要看清楚 Tracy 这个工具本身。**不理解工具本身,用工具就是黑箱**。

### 2.1 三段架构:Capture / Server / Client

Tracy 是一个**网络化 profiler**——profiler 和被 profile 的程序可以不在同一台机器上。这听起来奇怪,实则是关键设计。让我把架构画出来:

```
┌──────────────────────────┐    TCP/IP    ┌──────────────────────────┐
│  Profiled Application    │  (port 8086) │  Tracy Profiler (GUI)    │
│  ──────────────────────  │              │  ──────────────────────  │
│                          │              │                          │
│  ┌────────────────────┐  │   zones,    │  ┌────────────────────┐  │
│  │ Your Game (with    │──┼──────────────>│  Tracy Server       │  │
│  │  tracy_client      │  │   frames,    │  │  (parse, store,    │  │
│  │  crate linked in)  │<──┼──────────────│   index)             │  │
│  └────────────────────┘  │   commands   │  └────────────────────┘  │
│           │              │              │           │              │
│           │ inline       │              │           │ in-process   │
│           v              │              │           v              │
│  ┌────────────────────┐  │              │  ┌────────────────────┐  │
│  │ Tracy Capture      │  │              │  │ Tracy GUI          │  │
│  │ (lock-free queue,  │  │              │  │ (Qt-based timeline │  │
│  │  per-thread buffer)│  │              │  │  view)             │  │
│  └────────────────────┘  │              │  └────────────────────┘  │
└──────────────────────────┘              └──────────────────────────┘
       "Client"                                    "Server"
```

术语(注意容易混):

- **Capture**:被 profile 的程序内,在内存里收集 zone 数据的那一段代码。**每线程一个 lock-free queue**,zone begin/end 写到 queue,后台 thread 把 queue 内容发到网络。
- **Client**(Tracy 术语,容易反):**被 profile 的程序整体**,包含 capture + 网络发送。Tracy 把"被 profile 的"叫 client,因为它"主动连接 server"。
- **Server**(Tracy 术语):**显示数据的 GUI 程序**,监听 TCP 8086,接收 client 发的数据,存到内存,渲染时间线。

为什么这么设计?三个理由:

**理由一:跨机器 profile**。你的游戏跑在 Steam Deck(Arm Linux),你不想在 Deck 上跑 GUI,你在桌面 PC 上跑 server,Deck 上跑 client,两边用 WiFi 连。Server 收数据、显示、分析,Deck 上零 GUI 开销。这就是为什么 Steam Deck 上能跑 60 FPS 游戏 + 实时 profile——GUI 不在同一机器。

**理由二:长期保存**。Tracy server 可以把抓到的数据存盘(`.tracy` 文件),下次直接 load 不用重新跑游戏。Casey 抓了一个 30 秒的 trace,可以慢慢看半小时——这是 instrumentation 数据 vs sampling 数据的关键区别,sampling 数据是统计摘要(就一个表),trace 数据是**完整时间线**(可以任意放大缩小)。

**理由三:延迟 vs 吞吐量分离**。capture 必须**极快**(每 zone 几十纳秒),否则改变被测程序行为(Heisenberg effect)。但 server 显示可以**慢**(60 FPS 刷新就够)。两者分开,capture 用 lock-free queue 不阻塞游戏线程,server 慢慢消费。

### 2.2 协议:Tracy 自己的 TCP 协议

Client 和 server 之间用**自定义二进制 TCP 协议**(端口 8086,默认)。不是 HTTP,不是 gRPC,是 Tracy 自己设计的极简协议。

协议要点(从 Tracy 源码 `TracyClient.cpp` 推):

1. **小端字节序**。所有多字节整数 little-endian。x86 / ARM 都是小端,所以无字节序转换开销。
2. **每个消息**:1 字节 type + 可变 payload。type 区分 zone begin / zone end / frame / lock / memory / plot 等 30 多种事件类型。
3. **不 framed**。TCP 是流,Tracy 用 type 字节的特殊值(0xFF 表示后续 4 字节是长度)做内嵌 framing。
4. **client 主动连接 server**,不是 server 连 client。Client 启动后立刻尝试连 127.0.0.1:8086(或配置的 IP),失败则定期重试。
5. **server 多路复用**。一个 server 可以同时连多个 client(比如你 profile 多人游戏的两个 client)。

这个协议设计极简——**没有 JSON、没有 protobuf、没有 cap'n proto**——因为 Tracy 关心 overhead,任何抽象层都增加 bytes 和 cycles。Tracy 作者 Bartosz Taudul(也叫 wolfpld)在多个场合强调:**profiler 的协议必须比被 profile 的代码快几个数量级**,否则 profiler 自己变成瓶颈。

### 2.3 Capture:lock-free queue 的工程细节

Tracy capture 的核心是**每线程一个 SPMC(单生产者多消费者)queue**。生产者是游戏线程(写 zone),消费者是后台 send 璺 thread(读 zone 发网络)。SPMC 比通用 MPMC queue 快几倍,因为不需要 CAS。

具体(tracy 源码 `TracyThread.hpp` 推):

```cpp
// 每个 tracy thread 启动时分配一个 buffer
struct TracyThreadLocalData {
    // 一个固定大小的环形 buffer(典型 64KB)
    TracyQueueHeader* buffer;
    // 写指针(只有 owner thread 写)
    std::atomic<uint32_t> write_pos;
    // 读指针(只有 send thread 读)
    std::atomic<uint32_t> read_pos;
};
```

写一个 zone begin:

```cpp
inline void TracyQueueZoneBegin(const char* name, const char* function, 
                                 const char* file, uint32_t line) {
    auto* tld = get_thread_local_data();
    
    // 1. 写槽位(原子)
    uint32_t pos = tld->write_pos.load(std::memory_order_relaxed);
    uint32_t next_pos = (pos + sizeof(ZoneBeginEvent)) % BUFFER_SIZE;
    
    // 2. 检查 buffer 满(罕见)
    if (next_pos == tld->read_pos.load(std::memory_order_acquire)) {
        // 满,丢事件(tracy 记一个 "queue full" 计数)
        return;
    }
    
    // 3. 写数据(非原子,只有自己写)
    auto* evt = reinterpret_cast<ZoneBeginEvent*>(tld->buffer + pos);
    evt->type = QueueType::ZoneBegin;
    evt->name = name;  // 第一次出现时,发完整字符串;之后发 7 字节 hash
    evt->function = function;
    evt->file = file;
    evt->line = line;
    evt->timestamp = get_high_precision_timestamp();  // rdtsc on x86
    
    // 4. 发布(原子 store with release)
    tld->write_pos.store(next_pos, std::memory_order_release);
}
```

关键点:

- **没有锁**。Thread-local 数据 + atomic 指针 = 完全 lock-free 的生产端。
- **release/acquire 内存序**。写数据用 relaxed(只有自己写),发 publish 用 release,读端用 acquire——这是经典 SPMC pattern。
- **timestamp 用 rdtsc**。x86 `rdtsc` 指令直接读 CPU 时间戳计数器,精度 1 cycle(< 1ns on modern CPUs)。这就是 Tracy 能做 nanosecond profiling 的原因。
- **字符串 hash 优化**。Zone name 第一次发完整字符串,之后发 7-byte hash。Tracy 知道 "physics_step" 这个字符串出现 10000 次,只发一次字符串 + 9999 次 hash——这是为什么 Tracy 能 profile 数百万 zone / 帧而不爆炸。

### 2.4 五大原语:zone / plot / frame / lock / memory

Tracy 的所有功能都建立在这 5 个原语上。每个原语对应一类事件类型。让我一一讲清楚。

#### 2.4.1 Zone(CPU 区间)

**Zone** 是最常用的原语——一段代码的 begin/end,带名字和位置。从 capture 角度,zone 就是一对事件:`ZoneBegin{ name, srcloc, t0 }` 和 `ZoneEnd{ t1 }`。两者通过一个**线程局部栈**关联——zone begin 时 push,zone end 时 pop。这就是为什么 Tracy 能显示嵌套结构。

Tracy C++ API 的 zone:

```cpp
#include "Tracy.hpp"

void update(GameState* state) {
    ZoneScoped;  // 自动 zone,名字 = 函数名,位置 = 当前行
    // ZoneScoped 是一个 RAII 对象,构造时 zone begin,析构时 zone end
    
    {
        ZoneScopedN("physics_step");  // 自定义名字
        physics_step(state);
    }
    
    {
        ZoneScopedN("ai_step");
        ai_step(state);
    }
}
```

`ZoneScoped` 实际是 macro,展开后:

```cpp
#define ZoneScoped TracyZoneScoped(__func__, __FILE__, __LINE__)
#define TracyZoneScoped(name, file, line) \
    tracy::ScopedZone ___tracy_scoped_zone(name, file, line); \
    // ^^^ RAII 对象,构造调 zone_begin,析构调 zone_end
```

`ScopedZone` 析构在函数返回、抛异常、`break`/`continue` 时都被调,所以 zone 永远正确闭合——这是 RAII 比手动 begin/end 优越的地方。

#### 2.4.2 Plot(数值曲线)

**Plot** 用来跟踪一个**数值随时间变化**。比如帧时间、玩家坐标、内存使用、粒子数、draw call 数。

```cpp
TracyPlot("FPS", current_fps);          // 整数
TracyPlot("Player X", player.x);        // 浮点
TracyPlot("Allocated MB", mem_mb);      // 任意数值
```

在 Tracy GUI 里,plot 显示成时间线下面的一条曲线。Plot 是**调试物理 / 数值问题**的利器——比如玩家穿墙,你 plot 玩家坐标和墙体坐标,看见两条曲线在某个时刻交叉,你就知道那一帧碰撞检测漏了。

Plot 比 printf 高效一个数量级——printf 要格式化字符串、写 stdout、刷缓冲(几十微秒),TracyPlot 只写一个 8 字节 event(< 50ns)。

#### 2.4.3 Frame(帧边界)

**Frame** 原语标记一帧的开始 / 结束。在 Tracy 里显示成顶部的"帧条"——每帧一条,长度对应该帧耗时。

```cpp
void game_loop() {
    while (running) {
        FrameMark;  // 标记帧开始(下一次 FrameMark 之间是一帧)
        update(state);
        render(state);
    }
}
```

`FrameMark` 是一个 single event,Tracy 自动把两个连续 FrameMark 之间算作一帧。这比"用一个 zone 包住整个帧"更轻量(只有 1 个 event,不是 2 个 begin/end pair)。

Tracy 还支持**secondary frame mark**——比如你的游戏有 logic frame 和 render frame,可以分别标记:

```cpp
while (running) {
    FrameMark;
    update(state);          // logic frame
    FrameMarkNamed("Logic");
    render(state);          // render frame
    FrameMarkNamed("Render");
}
```

Tracy GUI 显示三条 frame 条,你可以独立看 logic 和 render 的帧时间分布。这对"logic 稳定但 render 卡"的 bug 特别有用——你立刻知道问题在 render,不在 logic。

#### 2.4.4 Lock(锁等待)

**Lock** 原语记录**锁的获取 / 等待**。多线程程序里锁等待是隐形开销——你的 thread 跑得很快,但它花了 90% 时间在等一把锁。

```cpp
std::mutex m;
LockableBase<std::mutex> tracy_m;  // Tracy 包装的锁

void thread_fn() {
    std::lock_guard<LockableBase<std::mutex>> lock(tracy_m);
    // Tracy 自动记录 acquire / wait / release
    do_work();
}
```

在 Tracy GUI 里,锁显示成一个 lane,绿色 = 持有,黄色 = 等待,红色 = 等待 + 持有线程阻塞。一眼看出"哪个线程在等哪把锁等多久"。

这就是为什么 Tracy 适合调试**多线程死锁 / 活锁**——你看见锁 lane 全红,就知道有 contention。

#### 2.4.5 Memory(分配追踪)

**Memory** 原语记录**每个 malloc / free**。打开后 Tracy 显示:

- 每次 alloc 的大小、地址、调用栈、时间戳
- 当前活跃分配的总大小(类似 Valgrind massif)
- 每帧分配数(检测"每帧分配"反模式)
- 内存泄漏(程序结束时还没释放的)

```cpp
// Tracy 通过宏替换 malloc / free 自动 hook
#define TRACY_ENABLE
#include "Tracy.hpp"

// 之后用 malloc / free 自动被 Tracy 记录
// 或者用 new / delete(通过 TracyOpNew hook)
```

Memory 原语开销大(每次 alloc 多几百纳秒),所以 Tracy 默认关,要用 `tracy-no-memory` feature 显式开。生产里通常只在 debug build 开。

### 2.5 GPU Zone(GPU 时间戳)

到这里都是 CPU profiling。**游戏卡顿的另一半原因在 GPU**——shader 慢、纹理上传慢、PSO cache miss、draw call 串行化。Tracy 通过 **GPU timestamp** 抓 GPU 时间。

GPU timestamp 的原理:

1. **GPU 写 timestamp**。GPU 在执行 command list 时,在指定位置往一个 query object 写当前 GPU 时钟。
2. **CPU 之后读**。CPU 调 `glGetQueryObjectui64v`(OpenGL)或 `ID3D11Query::GetData`(D3D)读 timestamp。
3. **GPU 时钟 vs CPU 时钟对齐**。Tracy 用一个"calibration zone"——同时记 CPU timestamp 和 GPU timestamp,推算两边时钟差。这样 Tracy 时间线上 CPU 和 GPU 事件能对齐。

Tracy 的 GPU zone API(以 Vulkan 为例):

```cpp
#include "TracyVulkan.hpp"

VkCommandBuffer cmd = ...;
// TracyVkScope 是 RAII,自动 begin/end GPU zone
TracyVkScope(tracy_vk_ctx, cmd);  // 给后续 cmd 标记成 GPU zone
vkCmdDraw(cmd, ...);
vkCmdDraw(cmd, ...);
```

在 Tracy GUI 里 GPU zone 显示成单独的 lane,你能看见"这一帧 GPU 总耗时 12 ms,其中 forward pass 8 ms,shadow pass 3 ms,bloom pass 1 ms"。这是**定位 GPU 卡顿的唯一精确方法**。

GPU timestamp 的代价:

- 每 zone 要分配 query object(Vulkan / D3D12 pool)
- 读 timestamp 要等 GPU 完成(异步,有 1-2 帧延迟)
- Tracy 用 query pool ring buffer,避免每 zone 分配

Tracy 支持 OpenGL / Vulkan / D3D11 / D3D12 / Metal 五个后端。

### 2.6 Callstack sampling(调用栈采样)

最后是 Tracy 的"杀手锏"——**callstack sampling**。这是 sampling 派的能力,instrumentation 派通常没有。Tracy 把两者合一。

打开 callstack sampling(`TRACY_CALLSTACK` 或 GUI 里点按钮),Tracy 启动一个**后台采样线程**,每隔 1ms 给所有被 profile 的线程发 signal,触发调用栈展开,把调用栈发回 server。

```cpp
#define ZoneScoped TracyZoneScopedC(__func__, __FILE__, __LINE__, 5)
//                                                                       ^
//                                                       callstack 深度 5
```

`ZoneScopedC` 的 C = callstack,在 zone begin 时同时抓调用栈。这样 zone 不只是"这段代码花了多久",还有"这段代码被谁调用"——你能从 Tracy 时间线上 jump 到调用栈任何一帧。

Callstack 展开是慢操作(几微秒,要读 DWARF 调试信息),所以 Tracy 默认关。开发时打开定位问题,生产关掉。

## 3 · Rust 集成:两条主流路线

Rust 生态有两条主流路线集成 Tracy。让我把两条都跑一遍,你看清楚哪条适合你。

### 3.1 路线一:tracy_client crate(裸用)

`tracy_client` crate 是 Tracy C++ client 的 Rust binding。直接调底层 API,不开额外抽象。

`Cargo.toml`:

```toml
[dependencies]
tracy_client = "1.0"  # 或 "2.0",取决于 Tracy 版本

[profile.release]
# Tracy 需要调试符号来显示函数名
debug = true
# 或者只 line tables,体积小
debug = "line-tables-only"
```

`src/main.rs`:

```rust
use tracy_client::{span, Client};

fn main() {
    // Client 启动后,自动连接 127.0.0.1:8086 的 server
    let _client = Client::start();
    
    // 主循环
    let mut state = GameState::new();
    loop {
        tracy_client::frame_mark();  // FrameMark
        update(&mut state);
        render(&state);
    }
}

fn update(state: &mut GameState) {
    // span! 是 RAII,生命周期内是 zone
    let _span = span!("update");
    
    {
        let _physics_span = span!("physics_step");
        physics_step(state);
    }
    {
        let _ai_span = span!("ai_step");
        ai_step(state);
    }
}

fn render(state: &GameState) {
    let _span = span!("render");
    // ...
}
```

优缺点:

| 优点 | 缺点 |
|---|---|
| 直接对接 Tracy API,功能全 | 每个 zone 要手写 `let _span = span!(...)` |
| 性能开销最小(C binding) | 没有 Rust 生态集成(日志、metrics) |
| 可以用所有 Tracy 功能(memory / lock / GPU) | 学习曲线陡 |

适合:**资深性能工程师**,清楚知道要抓什么。

### 3.2 路线二:tracing-tracy(组合 tracing)

`tracing` 是 Rust 生态的"结构化日志 + metrics"框架,远超 Tracy 范畴——它支持多个 subscriber(log to file / log to console / metrics to Prometheus / tracing to Tracy)。`tracing-tracy` 是其中一个 subscriber。

`Cargo.toml`:

```toml
[dependencies]
tracing = "0.1"
tracing-subscriber = "0.3"
tracy-client = { version = "1.0", optional = true }
tracing-tracy = { version = "0.11", optional = true }

[features]
profile = ["dep:tracy-client", "dep:tracing-tracy"]
```

`src/main.rs`:

```rust
fn main() {
    // 初始化 tracing subscriber
    #[cfg(feature = "profile")]
    {
        use tracing_subscriber::layer::SubscriberExt;
        let tracy_layer = tracing_tracy::TracyLayer::new();
        tracing::subscriber::set_global_default(
            tracing_subscriber::registry().with(tracy_layer)
        ).expect("setup tracing");
    }
    
    game_loop();
}

#[tracing::instrument]  // 自动 zone,名字 = 函数名
fn update(state: &mut GameState) {
    physics_step(state);
    ai_step(state);
}

#[tracing::instrument(name = "physics_step")]
fn physics_step(state: &mut GameState) {
    // ...
    tracing::info!(?state.player_pos, "player moved");  // 这个会变成 plot / event
}

fn game_loop() {
    loop {
        tracing::info_span!("frame").in_scope(|| {
            let mut state = GameState::new();
            update(&mut state);
            render(&state);
        });
    }
}
```

`#[tracing::instrument]` 是 attribute macro,自动在函数入口/出口插入 span。比手写 `span!` 干净。

优缺点:

| 优点 | 缺点 |
|---|---|
| 集成 tracing 生态(同时输出 log / metrics / Tracy) | 抽象层多一点,性能稍低 |
| `#[instrument]` macro 极优雅 | 不是所有 Tracy 功能都暴露(GPU zone 支持有限) |
| 同一份 instrumentation 多个 subscriber | 学习 tracing 框架 |

适合:**Rust 项目主流**,99% 的 Rust 游戏引擎(bevy / rend3 / wgpu)用这条。

### 3.3 自己写 profiling macro

有时候你不想拉 tracing 整套依赖,但想要 `#[instrument]` 的优雅——可以自己写 proc macro,~50 行:

`profiling-macro/src/lib.rs`:

```rust
use proc_macro::TokenStream;
use quote::quote;
use syn::{parse_macro_input, ItemFn};

#[proc_macro_attribute]
pub fn profile(_attr: TokenStream, item: TokenStream) -> TokenStream {
    let func = parse_macro_input!(item as ItemFn);
    let func_name = &func.sig.ident;
    let func_name_str = func_name.to_string();
    let block = &func.block;
    
    let expanded = quote! {
        #func {
            let _tracy_span = tracy_client::span!(#func_name_str);
            #block
        }
    };
    
    expanded.into()
}
```

用法:

```rust
#[profile]
fn physics_step(state: &mut GameState) {
    // 自动包在 tracy_client::span! 里
}
```

这个 macro 简单到 20 行,但能显著减少手写 span 的痛苦。这就是为什么 `tracing::instrument` 存在——把模式抽出来。

## 4 · 其他 profiler 横向对比

Tracy 不是唯一选择。让我把主流 profiler 横向对比,你看清取舍。

### 4.1 Optick(C++ / 跨平台)

**Optick** 是 Crytek 开源的 C++ profiler,设计哲学类似 Tracy(instrumentation + sampling + GPU),但 GUI 是 C# 写的(WPF)。

GitHub: https://github.com/bombomby/optick

| 维度 | Optick | Tracy |
|---|---|---|
| 语言 | C++ / C# GUI | C++ / Qt GUI |
| 平台 | Win / Linux | Win / Linux / macOS / BSD |
| GPU | D3D12 / Vulkan | D3D11/12 / Vulkan / GL / Metal |
| 网络 | 文件为主 | TCP 实时 |
| Rust binding | optick-rs | tracy_client |
| 开源协议 | MIT | BSD-3 |

Optick 在 Crytek 自己游戏里用,功能成熟但社区比 Tracy 小。Crytek 的《Crysis》系列用它调优。

### 4.2 Superluminal(Windows / 商业)

**Superluminal** 是 Commercial profiler(€499/developer),只支持 Windows。被誉为"Windows 上最快的 profiler"。

URL: https://superluminal.eu/

核心卖点:

- **极低 overhead**(宣称 <5ns/instrumented function)
- **sampling + instrumentation 混合**,自动采样抓调用关系
- **CPU 优化的 GUI**(不像 Tracy 是 Qt,Superluminal 是 native Win32)
- **支持 D3D12 / Vulkan GPU profiling**
- **thread timeline 视图**(类似 Tracy 但更精致)

Casey Muratori 在 HH 视频里多次推荐 Superluminal——他自己用,且 vlog 里反复说"如果你做 Windows 上的性能工作,Superluminal 是必备"。

缺点:Windows only、付费、不开源。

### 4.3 PIX(Windows / Xbox)

**PIX** 是微软出的 Windows / Xbox profiler,完全免费。D3D12 开发者必备。

URL: https://devblogs.microsoft.com/directx/pix/

核心功能:

- **GPU frame capture**:抓一帧,显示每个 draw call 的完整状态(shader binding、texture、render target、PSO)
- **Timing captures**:CPU + GPU 时间线,类似 Tracy 但 D3D12-centric
- **Shader debugging**:抓帧后,可以单步 shader 代码,看每个 vertex / pixel 经过 pipeline 的状态
- **Memory tracking**:GPU 内存分配追踪

PIX 是 **D3D12 游戏开发的事实标准**。在 Windows 上做 D3D12 你**必须**装 PIX。其他 profiler(Superluminal / Tracy)做 D3D12 都不如 PIX 深。

### 4.4 RenderDoc(开源 / 跨平台)

**RenderDoc** 是开源的 graphics debugger,专门做 frame capture(抓一帧 draw call,逐个检查)。

GitHub: https://github.com/baldurk/renderdoc

和 profiler 的区别:**RenderDoc 是 debugger,不是 profiler**。Profiler 告诉你"哪段慢",RenderDoc 告诉你"为什么渲染结果错了"。两者互补。

RenderDoc 支持:

- Vulkan / D3D11 / D3D12 / OpenGL / Metal
- 抓帧后逐个 draw call 检查
- 看每个 draw call 的输入(texture、vertex buffer)和输出(render target)
- shader 反编译 + 编辑 + 重跑
- pixel history(选中某个像素,看哪些 draw call 写过它)

游戏开发流程:**先用 profiler 定位卡帧 → 用 RenderDoc 看那帧渲染细节**。

### 4.5 NVIDIA Nsight Graphics / AMD Radeon Developer Tool Suite

GPU 厂商自家的工具,比通用工具更深:

- **Nsight Graphics**(NVIDIA):https://developer.nvidia.com/nsight-graphics
  - GPU 性能 counter(shader cycles、texture bandwidth、register pressure)
  - GPU trace(每个 SM 上的 warp 调度)
  - Shader profiling(哪个 shader 哪行慢)

- **Radeon Developer Tool Suite**(AMD):https://gpuopen.com/rdts/
  - Radeon GPU Profiler:类似 Nsight
  - Radeon Memory Visualizer:GPU 内存布局

这些工具是**GPU 极致优化**必备。一般 indie 游戏用 RenderDoc + Tracy 就够,GPU-bound 的 3A 游戏用 Nsight / Radeon。

### 4.6 XCode GPU Frame Capture(macOS / iOS)

苹果生态的 PIX 等价物。XCode 内置,免费。抓一帧 Metal 渲染,逐 draw call 检查。iOS / macOS 游戏必备。

### 4.7 flamegraph(Rust / perf-based)

最简单的 sampling profiler——直接用 `cargo flamegraph`。

```bash
cargo install flamegraph
cargo flamegraph --bin game
# 自动 perf record + 生成 flame.svg
```

适合**快速热点定位**,不需要深度分析。生成的 SVG 一眼看出哪段代码占 CPU 最多。

### 4.8 选型表

把所有 profiler 并列对比:

| 场景 | 首选 |
|---|---|
| Linux CPU 快速热点 | `cargo flamegraph` |
| Linux CPU 深度分析 | `perf record + report` |
| Windows CPU 商业级 | Superluminal |
| Windows D3D12 开发 | PIX |
| 跨平台 instrumentation | Tracy |
| 跨平台 GPU debugging | RenderDoc |
| NVIDIA GPU 极致优化 | Nsight Graphics |
| macOS / iOS | XCode Instruments |
| Rust 项目一体化 | tracing-tracy |

工业实践:**装 2-3 个,各用一段时间**。比如 Linux 开发机:flamegraph(快速) + Tracy(深度) + RenderDoc(渲染 debug)。Windows 开发机:PIX(D3D12) + Superluminal(CPU) + RenderDoc。

## 5 · Chrome Tracing JSON:工业通用格式

到这里你注意到一个事实:每个 profiler 有自己的格式(`.tracy`、`.optick`、`.pix`、`.nsight`、`.chrome.json`)。但其中**Chrome Tracing JSON** 成了事实上的开源标准——所有 profiler 几乎都能导入 / 导出它。

### 5.1 格式规范

Chrome Tracing JSON(也叫 Perfetto 格式)极简:

```json
{
  "traceEvents": [
    {
      "name": "frame",
      "cat": "game",
      "ph": "B",            // B = begin
      "ts": 1234567890,      // microseconds
      "pid": 1,              // process id
      "tid": 100             // thread id
    },
    {
      "name": "frame",
      "cat": "game",
      "ph": "E",            // E = end
      "ts": 1234571234,
      "pid": 1,
      "tid": 100
    },
    {
      "name": "physics_step",
      "cat": "game",
      "ph": "X",            // X = complete(begin + end 合一)
      "ts": 1234567890,
      "dur": 1500,          // microseconds
      "pid": 1,
      "tid": 101
    },
    {
      "name": "fps",
      "cat": "metric",
      "ph": "C",            // C = counter(plot)
      "ts": 1234567890,
      "args": { "value": 60 },
      "pid": 1,
      "tid": 100
    }
  ]
}
```

事件类型(`ph` 字段):

- `B` / `E`:begin / end pair(配套用)
- `X`:complete event(自带 duration)
- `i`:instant event(瞬时,无 duration)
- `C`:counter / plot(数值随时间)
- `M`:metadata(进程 / 线程名)
- `S` / `T` / `F`:flow events(跨线程因果关系)

时间戳 `ts` 是 **microseconds since boot**,64 位整数,足以表示 50 万年。所有时间都是绝对时间,所以多进程 / 多线程事件可以混在一个文件里。

### 5.2 通用 viewer:chrome://tracing 和 Perfetto

打开 Chrome,输入 `chrome://tracing`,拖入 JSON 文件——你立刻看见时间线视图。

[Perfetto](https://ui.perfetto.dev/) 是 Google 出的 successor,功能更强,UI 更现代。两者都支持 Chrome Tracing JSON。

### 5.3 为什么这是事实标准

三个原因:

**理由一:Chrome 团队定标准**。Chrome 自己的性能团队 2014 年设计这个格式,发布成开源。Chrome 的市场份额 + Google 的背书,让这个格式瞬间扩散。

**理由二:格式极简**。JSON + 一组 ph 字段,任何 profiler 都能生成。Tracy 能 export chrome json,Optick 能,Superluminal 能,Vulkan validation layer 能,Android systrace 能,Linux ftrace 能。**一个 viewer 看所有 profiler 数据**。

**理由三:工具链丰富**。Perfetto UI 支持查询(SQL 语法),trace_CONV.py 工具转换,trace processor lib 给程序化分析。

### 5.4 自己生成 Chrome Tracing JSON

你可以自己写个 mini profiler 输出这个格式,~100 行 Rust:

```rust
use std::fs::File;
use std::io::Write;
use std::sync::Mutex;
use std::time::Instant;

struct TraceEvent {
    name: String,
    cat: &'static str,
    ph: char,
    ts: u64,
    pid: u32,
    tid: u32,
    dur: Option<u64>,
}

static EVENTS: Mutex<Vec<TraceEvent>> = Mutex::new(Vec::new());
static START: once_cell::sync::Lazy<Instant> = 
    once_cell::sync::Lazy::new(Instant::now);

pub fn zone_begin(name: &str) {
    let ts = START.elapsed().as_micros() as u64;
    EVENTS.lock().unwrap().push(TraceEvent {
        name: name.to_string(),
        cat: "default",
        ph: 'B',
        ts,
        pid: 1,
        tid: thread_id(),
        dur: None,
    });
}

pub fn zone_end(name: &str) {
    let ts = START.elapsed().as_micros() as u64;
    EVENTS.lock().unwrap().push(TraceEvent {
        name: name.to_string(),
        cat: "default",
        ph: 'E',
        ts,
        pid: 1,
        tid: thread_id(),
        dur: None,
    });
}

pub fn dump_to_file(path: &str) -> std::io::Result<()> {
    let events = EVENTS.lock().unwrap();
    let mut f = File::create(path)?;
    writeln!(f, "{{\"traceEvents\":[")?;
    for (i, e) in events.iter().enumerate() {
        let comma = if i + 1 < events.len() { "," } else { "" };
        if let Some(dur) = e.dur {
            writeln!(f, 
                "  {{\"name\":\"{}\",\"cat\":\"{}\",\"ph\":\"{}\",\"ts\":{},\"dur\":{},\"pid\":{},\"tid\":{}}}{}", 
                e.name, e.cat, e.ph, e.ts, dur, e.pid, e.tid, comma)?;
        } else {
            writeln!(f, 
                "  {{\"name\":\"{}\",\"cat\":\"{}\",\"ph\":\"{}\",\"ts\":{},\"pid\":{},\"tid\":{}}}{}", 
                e.name, e.cat, e.ph, e.ts, e.pid, e.tid, comma)?;
        }
    }
    writeln!(f, "]}}")?;
    Ok(())
}
```

100 行 mini profiler,输出能 chrome://tracing 打开。这就是为什么这个格式是工业通用——**生成器比解析器还简单**。

## 6 · Frame Graph(Unreal 的抽象)

讲到这里,我必须提一个 Unreal Engine 引入的高层抽象:**Frame Graph**。这不是 profiler,但和 profiler 关系紧密——它是**对渲染管线的结构化描述**,profiler 能直接用 frame graph 做"语义化 zone"。

### 6.1 传统渲染管线的问题

传统渲染代码:

```rust
fn render(state: &State) {
    let shadow_map = render_shadow_map(state);
    let gbuffer = render_gbuffer(state);
    let lighting = render_lighting(state, &gbuffer, &shadow_map);
    let bloom = render_bloom(state, &lighting);
    let final_image = render_composite(state, &lighting, &bloom);
    present(final_image);
}
```

问题:

1. **资源依赖硬编码**。`lighting` 依赖 `gbuffer` 和 `shadow_map`,代码里写死。改顺序、加 / 减 pass 要重写。
2. **资源生命周期隐式**。`shadow_map` 用完就该释放,但代码里没显式释放——靠 RAII 或者 GC。
3. **profiler 看不出语义**。profiler 知道"render_pass_3 花了 4 ms",但不知道这个 pass 在做什么。
4. **没法自动优化**。比如 bloom 不需要时应该跳过,但代码写死了。

### 6.2 Frame Graph 的解法

Frame Graph 把渲染描述成**有向无环图(DAG)**:

```rust
fn build_frame_graph(builder: &mut FrameGraphBuilder, state: &State) {
    let shadow_pass = builder.add_pass("shadow_map", |ctx| {
        let shadow_map = ctx.create_texture(2048, 2048, DepthFormat);
        ctx.write(shadow_map);
        ctx.set_callback(move |cmd| {
            render_shadow_map_internal(cmd, state);
        });
        shadow_map
    });
    
    let gbuffer_pass = builder.add_pass("gbuffer", |ctx| {
        let gbuffer = ctx.create_texture(...);
        ctx.write(gbuffer);
        ctx.set_callback(move |cmd| { render_gbuffer_internal(cmd, state); });
        gbuffer
    });
    
    let lighting_pass = builder.add_pass("lighting", |ctx| {
        ctx.read(shadow_pass);
        ctx.read(gbuffer_pass);
        let lighting = ctx.create_texture(...);
        ctx.write(lighting);
        ctx.set_callback(move |cmd| { render_lighting_internal(cmd, state); });
        lighting
    });
    
    // bloom 仅在 bloom_enabled 时加
    if state.bloom_enabled {
        builder.add_pass("bloom", |ctx| {
            ctx.read(lighting_pass);
            // ...
        });
    }
}
```

Frame Graph 系统:

1. **编译期分析依赖图**。哪些 pass 依赖哪些 texture。
2. **自动管理资源生命周期**。texture 在最后一个使用它的 pass 后释放。
3. **自动剔除 dead pass**。如果某 pass 的输出没人用,跳过。
4. **自动 barrier 插入**。GPU 同步自动管理。
5. **profiler 集成**。每个 pass 自动是一个 GPU zone,名字来自 graph node 名。

Unreal Engine 4.22+ 全部渲染管线用 Frame Graph。开源实现:[bevy_render 的 render graph](https://github.com/bevyengine/bevy/blob/main/crates/bevy_render/src/render_graph/mod.rs)、[Granite 的 frame graph](https://github.com/Themaister/Granite/blob/master/src/framework/frame_graph.cpp)。

Frame Graph 的 profiler 价值:**profile 数据自动带语义**。你不用手写 zone name,frame graph 自动用 pass name 做 zone。这就是为什么 Unreal 的 profile 数据看起来"很干净"——所有 zone 都是 frame graph pass。

## 7 · 性能反模式:profiler 教你看见的 4 类隐形杀手

到这里你有了工具,接下来讲**工具会教你看什么**。这 4 类反模式是工业级性能 bug 的 80% 来源。

### 7.1 Lock contention(锁竞争)

**症状**:Tracy 时间线显示线程 lane 大段灰色 "waiting" 区,旁边锁 lane 红色。

**原因**:多个线程高频抢一把锁。比如:

```rust
// 反模式:全局锁 + 每帧 1000 次访问
lazy_static! {
    static ref STATE: Mutex<State> = Mutex::new(State::new());
}

fn update() {
    for entity in 0..1000 {
        STATE.lock().unwrap().positions[entity] += 1;  // 1000 次 lock
    }
}
```

每次 `Mutex::lock` 在无竞争时 ~20ns,有竞争时几微秒(因为要 kernel context switch)。1000 次 = 1-10 ms,卡帧。

**修法**:

```rust
// 正确:一次 lock,批量访问
fn update() {
    let mut state = STATE.lock().unwrap();
    for entity in 0..1000 {
        state.positions[entity] += 1;
    }
}
// 锁只 acquire / release 一次
```

或者更激进,改成**lock-free**(atomic + per-thread buffer):

```rust
// 每 thread 独立 buffer,merge 时再锁
struct PerThreadBuffer {
    positions: Vec<Vec2>,
}

thread_local! {
    static BUFFER: RefCell<PerThreadBuffer> = RefCell::new(PerThreadBuffer { positions: Vec::new() });
}

fn update() {
    BUFFER.with(|buf| {
        let mut buf = buf.borrow_mut();
        for entity in 0..1000 {
            buf.positions.push(...);  // 无锁
        }
    });
}

fn merge_to_global() {
    let mut state = STATE.lock().unwrap();  // 一次锁
    BUFFER.with(|buf| {
        state.positions.extend(buf.borrow().positions.iter());
    });
}
```

这就是为什么 HH Day 138 后 Casey 把 sound mixing 改成 lock-free queue——锁等待是卡顿的隐形来源。

### 7.2 Cache miss(缓存未命中)

**症状**:perf stat 显示 cache-misses 占比 > 5%(健康 < 1%),且函数耗时和"指令数"不成比例。

**原因**:数据布局不友好 cache。比如:

```rust
// 反模式:array of struct
struct Entity {
    pos: Vec3,           // 12 bytes
    velocity: Vec3,      // 12 bytes
    health: f32,         // 4 bytes
    name: String,        // 24 bytes
    is_alive: bool,      // 1 byte
    // padding: 7 bytes
}

// 64 bytes per entity
let entities: Vec<Entity> = ...;

// 只用 pos
fn update_positions(entities: &mut [Entity]) {
    for e in entities.iter_mut() {
        e.pos += e.velocity * dt;  // 每次访问 64 bytes,只用 24 bytes,剩 40 bytes 是 cache 浪费
    }
}
```

每个 cache line 64 bytes,一个 entity 64 bytes 刚好填满。访问 entity.pos 时把整个 entity 加载进 cache,但 velocity / health / name / padding 都"白白占用 cache"。10000 个 entity * 40 bytes 浪费 = 400KB,远超 L1 cache(32KB)。

**修法**:struct of array

```rust
// 正确:struct of array
struct Entities {
    pos: Vec<Vec3>,          // 12 bytes per
    velocity: Vec<Vec3>,     // 12 bytes per
    health: Vec<f32>,        // 4 bytes per
    is_alive: Vec<bool>,     // 1 byte per
    // name 分开,因为 String 指针 + 堆,不连续
}

fn update_positions(entities: &mut Entities) {
    for (pos, vel) in entities.pos.iter_mut().zip(&entities.velocity) {
        *pos += *vel * dt;
    }
}
```

现在 pos 和 velocity 各自连续,只加载需要的数据进 cache。Cache miss 降到几乎零,性能提升 3-5 倍很常见。

这就是 Day 4 的 SIMD / cache 专题讲的内容——profiler (perf) 是**唯一能告诉你 cache miss 占比**的工具。instrumentation profiler 看不见 cache 行为。

### 7.3 Branch mispredict(分支预测失败)

**症状**:perf stat 显示 branch-misses 占比 > 2%,CPU IPC(instructions per cycle)低于 1。

**原因**:if/else 的条件不可预测。比如:

```rust
// 反模式:随机分支
fn process(items: &[Item]) {
    for item in items {
        if item.should_process() {  // 50% true / 50% false,完全随机
            do_work(item);
        }
    }
}
```

现代 CPU branch predictor 准确率通常 > 95%。但当分支真的随机(50/50),predictor 失败率 50%,每次失败 CPU flush pipeline 浪费 15-20 cycle。

**修法**:branchless 或排序数据

```rust
// 修法 1:branchless(条件传送)
fn process(items: &[Item]) {
    for item in items {
        let should = item.should_process() as usize;  // 0 or 1
        // 用 mask 代替 if
        do_work_branchless(item, should);
    }
}

// 修法 2:排序后批处理
fn process(items: &mut Vec<Item>) {
    items.sort_by_key(|i| !i.should_process());  // 应处理的排前面
    let split = items.iter().position(|i| !i.should_process()).unwrap_or(items.len());
    for item in &items[..split] {
        do_work(item);  // 现在分支稳定 100% true
    }
}
```

branchless 在数据量大时(>1000 元素)通常赢 branch 版本。小数据 (<100) branch 可能赢(因为 branchless 有额外 mask 计算)。

### 7.4 Register spilling(寄存器溢出)

**症状**:函数耗时和源代码复杂度不成比例,perf record 显示大量 `mov` 指令涉及 stack pointer。

**原因**:函数局部变量太多,编译器放不下寄存器,溢出到栈。每次访问栈比寄存器慢 5-10 倍。

```rust
// 反模式:大量局部变量
fn complex_compute(a: f32, b: f32, c: f32, d: f32, e: f32, f: f32, g: f32, h: f32) -> f32 {
    let v1 = a * b + c;
    let v2 = d * e + f;
    let v3 = g * h + a;
    let v4 = v1 * v2 + v3;
    let v5 = v2 * v3 + v4;
    let v6 = v3 * v4 + v5;
    let v7 = v4 * v5 + v6;
    let v8 = v5 * v6 + v7;
    let v9 = v6 * v7 + v8;
    let v10 = v7 * v8 + v9;
    // ... 一堆
    v10
}
```

x86-64 只有 16 个通用寄存器(其中几个被 ABI 占用),ARM64 有 31 个。超过就溢出。

**修法**:拆函数,或用 SIMD 把多个值放一个寄存器

```rust
// 修法 1:拆函数,每个函数寄存器够用
fn stage1(a: f32, b: f32, c: f32) -> f32 { a * b + c }
fn stage2(d: f32, e: f32, f: f32) -> f32 { d * e + f }
// main 只 hold 中间结果,寄存器够

// 修法 2:SIMD,8 个 f32 放一个 256-bit 寄存器
use std::arch::x86_64::*;
fn simd_compute(vals: &[f32; 8]) -> [f32; 8] {
    let v = unsafe { _mm256_loadu_ps(vals.as_ptr()) };
    let result = unsafe { _mm256_mul_ps(v, v) };
    let mut out = [0f32; 8];
    unsafe { _mm256_storeu_ps(out.as_mut_ptr(), result); }
    out
}
```

诊断 register spill:**看汇编**。`cargo asm` 命令或 `objdump -d` 看函数汇编,数 `mov` 涉及 `[rbp-X]`(栈访问)的次数。健康函数几乎没有。

## 8 · 5 个真实性能 bug 调试过程

讲到这里,我把 5 个真实游戏开发里的性能 bug 调试过程完整复盘。每个都是工业级案例,包含**症状 → 假设 → 工具 → 真相 → 修复**全链路。

### 8.1 案例 1:卡顿来自 string formatting

**症状**:HH Day 158 玩家报告"游戏每 3-5 秒卡 0.5 秒"。Casey 自己的 profiler overlay 显示帧时间正常 16ms,但偶尔跳到 500ms。

**假设**:听起来像 GC / 内存分配。但 Rust 没有 GC,Casey 用了 arena allocator,每帧分配稳定。

**工具**:Tracy 接入,callstack sampling 打开。

**真相**:Tracy callstack 显示卡顿帧里 `format!` 调用占 480ms。Casey 在 sound system 里写了一个 debug 打印:

```rust
// 反模式:每帧 format 一次大字符串
fn debug_overlay(state: &State) -> String {
    format!(
        "Player: {:?}\nEntities: {:?}\nParticles: {:?}",
        state.player,
        state.entities,  // 5000 个 entity
        state.particles  // 10000 个 particle
    )
}
// 这个 String 每帧分配 50KB,format 要遍历所有 entity + particle
```

每帧 format 50KB 字符串 + 分配 + 释放,正常时 5ms,但当 String allocator 触发 mmap 系统调用扩 arena 时,卡 480ms。

**修复**:debug overlay 改成 immediate-mode,只画可见的部分。format 用 `write!` 流式输出到 buffer。

**教训**:**字符串操作是隐形性能杀手**。Rust 没有 GC 但有 allocator,大字符串分配卡顿和 GC pause 等价。Tracy callstack 能精确定位"卡顿帧里到底在跑什么代码"。

### 8.2 案例 2:lock contention 隐形卡顿

**症状**:多人游戏玩家报告"我开房间后,5 分钟内越来越卡,从 60 FPS 掉到 20 FPS"。

**假设**:网络带宽饱和?但 ping 正常。

**工具**:Tracy 多线程时间线 + lock lane。

**真相**:游戏每帧从 network thread 拿 packet,用了 `Arc<Mutex<Vec<Packet>>>`。每帧 100 个 packet,polling 时每次 lock:

```rust
// 反模式:每 packet 一次 lock
while let Ok(packet) = rx.try_recv() {
    let mut queue = shared_queue.lock().unwrap();  // 每包 lock
    queue.push(packet);
}

// game loop 端,每帧也 lock
let packets: Vec<Packet> = {
    let mut q = shared_queue.lock().unwrap();
    q.drain().collect()  // drain 慢,持锁时间长
};
```

每帧 100 个 packet,每个 lock / drain,网络线程和 game thread 互锁。前期 packet 少(50),lock 持续时间短(<1us);后期 packet 累积到几千,drain 慢,持锁 100us,game thread 等待。

**修复**:lock-free queue(crossbeam-channel 或自己写 SPSC):

```rust
use crossbeam_channel::unbounded;
let (tx, rx) = unbounded::<Packet>();

// network thread
while let Some(packet) = receive_packet() {
    tx.send(packet).unwrap();  // 无锁
}

// game loop
let packets: Vec<Packet> = rx.try_iter().collect();  // 批量,无锁
```

**教训**:profiler 锁 lane 一眼看出 contention。Lock contention 不是"代码慢",是"代码等别人",只有时间线视图能看见。

### 8.3 案例 3:GPU upload 卡帧

**症状**:HH Day 235 加纹理资源,每秒第一个帧特别卡(30ms),后续帧正常 16ms。

**假设**:GPU driver 初始化?但每秒重复发生,不像初始化。

**工具**:PIX GPU timestamp + Tracy CPU zone。

**真相**:Tracy 显示第一帧的 `texture_upload` CPU zone 耗时 25ms,后续帧 1ms。GPU zone 显示真实 GPU 耗时正常(<1ms)。所以**CPU 慢**,不是 GPU 慢。

代码:

```rust
// 反模式:每帧上传纹理,但只在第一帧真正需要
fn render(state: &State) {
    let texture = create_texture_from_file("assets/hero.png");  // 每帧创建!
    bind_texture(texture);
    draw_player(state);
}
```

第一帧:读 PNG 文件(磁盘 IO)、解码、上传 GPU,25ms。后续帧:PNG 在 OS page cache 里,读快;但 decode + upload 仍然 1ms。

**修复**:缓存纹理,只在第一次创建:

```rust
lazy_static! {
    static ref HERO_TEX: Texture = create_texture_from_file("assets/hero.png");
}

fn render(state: &State) {
    bind_texture(&HERO_TEX);
    draw_player(state);
}
```

**教训**:Tracy CPU/GPU 分离时间线能精确定位"卡在 CPU 还是 GPU"。CPU 卡帧通常是 upload / state setup / shader compile。GPU 卡帧通常是 shader 复杂度 / texture bandwidth。

### 8.4 案例 4:branch mispredict 在 tight loop

**症状**:粒子系统更新卡。10 万粒子,理论 1ms,实测 5ms。

**假设**:数据布局不好?已经是 SoA。

**工具**:`perf record` + `perf stat -e branch-misses`。

**真相**:`perf stat` 显示 IPC = 0.4(应该 >1),branch-misses = 8%(应该 <2%)。`perf record` 显示热点在 `update_particle`。

代码:

```rust
// 反模式:每个粒子有 if 分支,但 99% 粒子都活
fn update_particle(p: &mut Particle) {
    if p.alive {            // 99% true,但 predictor 有时候猜 false
        p.pos += p.vel * dt;
    }
}
```

99% true 听起来好,但 1% false 散布在 100000 粒子里 = 1000 个 false。1000 次 mispredict * 20 cycle = 20000 cycle = 6us。听起来不大,但累加其他小分支也卡。

**修复**:branchless 或先 sort

```rust
// 修法 1:branchless
fn update_particle(p: &mut Particle) {
    let alive = p.alive as i32 as f32;  // 1.0 或 0.0
    p.pos += p.vel * dt * alive;  // 死的粒子 vel * 0 = 0,不动
}

// 修法 2:把 alive 排前面,批处理
particles.sort_by_key(|p| !p.alive);
let split = particles.iter().position(|p| !p.alive).unwrap();
for p in &mut particles[..split] {
    p.pos += p.vel * dt;  // 无分支
}
```

修法 2 后实测从 5ms 降到 1.5ms。

**教训**:**branch 在 hot loop 里要严肃对待**。Sampling profiler 是看 branch miss 的唯一办法,instrumentation 看不见。

### 8.5 案例 5:false sharing(伪共享)

**症状**:多线程粒子更新,4 核应该 4x 加速,实测只 1.5x。

**假设**:工作不均?但粒子均匀分布。

**工具**:Tracy 多线程时间线 + perf c2c(Linux cache coherence profiler)。

**真相**:每个 thread 处理 25000 粒子,但 thread 间共享 cache line。

```rust
// 反模式:多个 atomic 紧邻,共占 cache line
struct Counters {
    particles_processed: AtomicU64,  // thread A 写
    bytes_allocated: AtomicU64,      // thread B 写
    bytes_freed: AtomicU64,          // thread C 写
}
```

三个 atomic 都在一个 64-byte cache line 里。thread A 写 `particles_processed` 时,整个 cache line invalidate,thread B / C 必须从内存重新读。每秒几百万次 invalidate,变成 cache 抖动。

**修复**:padding 让每个 atomic 独占 cache line

```rust
#[repr(align(64))]
struct PaddedAtomic(AtomicU64);

struct Counters {
    particles_processed: PaddedAtomic,  // 64 bytes,独占 line
    bytes_allocated: PaddedAtomic,      // 64 bytes
    bytes_freed: PaddedAtomic,          // 64 bytes
}
```

或者用 `crossbeam::CachePadded`:

```rust
use crossbeam::utils::CachePadded;
struct Counters {
    particles_processed: CachePadded<AtomicU64>,
    bytes_allocated: CachePadded<AtomicU64>,
    bytes_freed: CachePadded<AtomicU64>,
}
```

修完后 4 核加速到 3.5x。

**教训**:**false sharing 是多线程性能的隐形杀手**。`perf c2c` 工具专门检测这个,显示哪些 cache line 被多核频繁 invalidate。

## 9 · 在你 HH 项目里实践

到这里理论讲完,我们要落地。下面是把 Tracy 接入 HH 项目的完整步骤,大约 30 分钟做完。

### 9.1 步骤 1:装 Tracy

```bash
# Linux (Arch)
sudo pacman -S tracy

# 或从源码编译(更新版本)
git clone https://github.com/wolfpld/tracy.git
cd tracy
make -C profiler/build/unix release -j$(nproc)
# binary 在 profiler/build/unix/Tracy-release

# macOS
brew install tracy

# Windows: 下载 https://github.com/wolfpld/tracy/releases
```

### 9.2 步骤 2:加 tracy_client crate

`Cargo.toml`:

```toml
[dependencies]
tracy-client = { version = "1.0", optional = true }

[features]
profile = ["dep:tracy-client"]
```

注意我用了 `optional = true` + feature,而不是默认开。理由:**Tracy 在 release 里会尝试连 server**,玩家机器上没 server,游戏会延迟启动(等连接 timeout)。所以只在开发时启用。这呼应了 Day 201 的"feature 隔离 debug 代码"原则。

### 9.3 步骤 3:写 zone macro

`src/profile.rs`:

```rust
#[cfg(feature = "profile")]
pub mod profile {
    use tracy_client::Client;

    pub fn init() {
        // 启动 client,连接 127.0.0.1:8086
        Client::start();
    }

    pub fn frame_mark() {
        tracy_client::frame_mark();
    }

    pub fn zone(name: &'static str) -> tracy_client::Span {
        tracy_client::span!(name)
    }

    pub fn plot(name: &'static str, value: f64) {
        tracy_client::plot!(name, value);
    }
}

#[cfg(not(feature = "profile"))]
pub mod profile {
    pub fn init() {}
    pub fn frame_mark() {}
    
    // 没 profile feature 时,zone 返回 unit
    pub struct Span;
    pub fn zone(_name: &'static str) -> Span { Span }
    
    pub fn plot(_name: &'static str, _value: f64) {}
}

// 调用方永远写 profile::zone("foo"),feature 开关透明
```

### 9.4 步骤 4:在主循环加 zone

`src/main.rs`:

```rust
mod profile;

fn main() {
    profile::init();  // 启动 tracy client
    
    let mut state = GameState::new();
    while state.running {
        let frame_start = profile::zone("frame");
        profile::frame_mark();
        
        {
            let _z = profile::zone("input");
            process_input(&mut state);
        }
        {
            let _z = profile::zone("update");
            update(&mut state);
        }
        {
            let _z = profile::zone("render");
            render(&state);
        }
        
        profile::plot("fps", state.fps as f64);
        profile::plot("entity_count", state.entities.len() as f64);
        
        drop(frame_start);  // zone end
    }
}

fn update(state: &mut GameState) {
    let _z = profile::zone("physics");
    physics_step(state);
    // _z 在这里 drop,zone end
    
    let _z = profile::zone("ai");
    ai_step(state);
}
```

### 9.5 步骤 5:启动 Tracy server,跑游戏

终端 1:

```bash
# 启动 Tracy GUI / server
tracy
# 它在 127.0.0.1:8086 监听
```

终端 2:

```bash
# 启动游戏(profile feature 开)
cargo run --features profile
```

Tracy GUI 立刻显示 client 连接。你能看见:

- 顶部 frame bar:每帧长度
- CPU lane:每个 zone 的彩色块,嵌套显示
- Plot lane:FPS 曲线

试着在游戏里跑 30 秒,然后回 Tracy GUI 分析。你会发现一些**之前不知道的事**:

- input 处理平时 0.1ms,但鼠标移动时跳到 2ms
- physics_step 平均 3ms,但偶尔跳到 8ms(可能是 broadphase 偶尔触发)
- render 总 8ms,但 shadow pass 占 4ms(你之前以为 forward pass 最贵)

这就是 Tracy 的价值——**让隐形变得可见**。

### 9.6 步骤 6:加 GPU zone(可选,有 wgpu 时)

如果你的 HH 项目用 wgpu:

`src/gpu_profile.rs`:

```rust
use wgpu::util::DeviceExt;

pub struct GpuProfiler {
    query_set: wgpu::QuerySet,
    query_buffer: wgpu::Buffer,
    pipeline_statistics: wgpu::ComputePipeline,
}

impl GpuProfiler {
    pub fn new(device: &wgpu::Device) -> Self {
        let query_set = device.create_query_set(&wgpu::QuerySetDescriptor {
            label: Some("Tracy GPU timestamp"),
            count: 64,
            ty: wgpu::QueryType::Timestamp,
        });
        
        let query_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("Tracy GPU query resolve"),
            size: 64 * 8,  // 64 timestamps * 8 bytes
            usage: wgpu::BufferUsages::QUERY_RESOLVE | wgpu::BufferUsages::COPY_SRC,
            mapped_at_creation: false,
        });
        
        Self { query_set, query_buffer, ... }
    }
    
    pub fn begin_zone(&self, encoder: &mut wgpu::CommandEncoder, name: &str, idx: u32) {
        encoder.write_timestamp(&self.query_set, idx);
        // tracy_client 接收 idx 关联 name
    }
    
    pub fn end_zone(&self, encoder: &mut wgpu::CommandEncoder, idx: u32) {
        encoder.write_timestamp(&self.query_set, idx);
    }
}
```

wgpu GPU timestamp 还在演化,tracy_client 对 GPU 的 Rust binding 比 C++ 弱。最完整的支持是直接用 Tracy C++ 库 + FFI。对于 indie 项目,CPU Tracy + RenderDoc(看 GPU)通常够用。

### 9.7 步骤 7:CI 集成

`.github/workflows/ci.yml`:

```yaml
jobs:
  bench:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
      - name: Run with Tracy, capture trace
        run: |
          # 装 tracy capture(不装 GUI)
          sudo apt install -y tracy-capture
          # 跑游戏 30 秒,输出 trace
          tracy-capture -o benchmark.tracy -t 30 \
            cargo run --release --features profile -- --auto-quit 30
      - name: Upload trace
        uses: actions/upload-artifact@v3
        with:
          name: tracy-trace
          path: benchmark.tracy
```

这样每次 PR 你能拿到一份 trace,人工或脚本分析。如果某 PR 让 frame time 从 16ms 涨到 20ms,立刻能发现。

## 10 · 性能数据汇总

到这里你要记住的关键数字:

| 数据 | 值 | 来源 |
|---|---|---|
| Tracy zone overhead | ~10ns/zone | wolfpld benchmark |
| Superluminal function overhead | <5ns/instrumented function | Superluminal docs |
| `Mutex::lock` uncontended | ~20ns | Rust std benchmark |
| `Mutex::lock` contended | 1-10us(取决于 kernel) | Linux futex |
| Cache line size | 64 bytes(x86 / ARM) | CPU spec |
| L1 cache latency | 1-2ns(~3 cycle) | CPU spec |
| L2 cache latency | 4-7ns(~12 cycle) | CPU spec |
| L3 cache latency | 15-30ns(~40 cycle) | CPU spec |
| Main memory latency | 80-120ns(~300 cycle) | CPU spec |
| Branch mispredict penalty | 15-20 cycle(~5-7ns) | Intel optimization manual |
| `rdtsc` instruction latency | ~25 cycle(~8ns) | Intel SDM |
| `Instant::now()` overhead | ~50ns | Rust std |
| `format!` allocation | 100ns-10us(取决于大小) | depends on string |
| Tracy capture queue size | 64KB per thread | tracy source |
| Tracy network protocol port | TCP 8086 | tracy default |
| `perf record` overhead | <1% with `-F 99` | Linux perf docs |
| 60 FPS frame budget | 16.67ms | 1000/60 |
| 144 FPS frame budget | 6.94ms | 1000/144 |
| Typical game loop subsystems | input / update / render / present | HH |
| Modern CPU IPC healthy | >1.0 | perf stat |

这些数字是你做性能判断的"基准"。比如你看见一个函数耗时 100ns,且访问一个数组元素——你能立刻判断:这速度正常,因为单次内存访问 100ns 级别(L3 cache)。看见 1us,你能判断:这有 cache miss 或 lock。看见 1ms,你能判断:有 I/O 或大量计算。

## 11 · 认知地图

### 11.1 上级(它属于哪个更大抽象?)

- **Performance engineering** — 软件工程通用领域,profiling 是其中一个环节。其他环节:benchmark 设计、回归检测、容量规划、SLO 管理。
- **Observability** — 现代软件工程的"可观察性"概念。Profiling 是 CPU 维度的可观察性,其他维度:logging(事件)、metrics(数值)、tracing(分布式调用链)。
- **Build vs runtime tooling** — 编译时工具(static analysis、linting)和运行时工具(profiling、debugging)的对比。

### 11.2 同级(并行方案对比)

| 方案 | 派别 | 平台 | 开源 | Rust 集成 |
|---|---|---|---|---|
| Tracy | tracing | 跨平台 | 是 | tracy_client / tracing-tracy |
| Optick | tracing | Win / Linux | 是 | optick-rs |
| Superluminal | sampling + instrumentation | Windows | 否(付费) | superluminal-client-rs |
| PIX | GPU profiler | Windows / Xbox | 是 | d3d12 直接用 |
| RenderDoc | GPU debugger | 跨平台 | 是 | 不需要 |
| perf | sampling | Linux | 是 | 直接用 |
| flamegraph | sampling | Linux / macOS | 是 | cargo flamegraph |
| VTune | sampling | Intel 平台 | 否(免费) | 直接用 |
| Instruments | sampling + tracing | macOS / iOS | 否(免费) | 直接用 |

### 11.3 下级(内部零件)

- `tracy_client::span!` macro
- `tracy_client::frame_mark!` macro
- `tracy_client::plot!` macro
- `#[tracing::instrument]` attribute macro
- `TracyLayer`(tracing-tracy 的 subscriber)
- rdtsc / rdtscp 指令(CPU timestamp)
- D3D11 / D3D12 / Vulkan / Metal timestamp query
- `LockableBase`(Tracy 锁包装)
- `FrameMark` / `FrameMarkNamed`
- Chrome Tracing JSON 格式
- `perf record` / `perf stat` / `perf report`
- `perf c2c`(cache coherence profiler)
- `cargo flamegraph`
- `cargo bloat`(体积 profiler)

## 12 · 对照与变奏

### 12.1 跨语言的 profiler 生态

| 语言 | 主流 profiler |
|---|---|
| C / C++ | Tracy / VTune / Superluminal / gperftools |
| Rust | Tracy / flamegraph / cargo profiler |
| Go | pprof(built-in)|
| Java | async-profiler / JFR |
| Python | cProfile / py-spy |
| JavaScript | Chrome DevTools Profiler / V8 CPU profiler |

每个语言生态有自己的"profiling 文化"。Go 因为 pprof 是 built-in,几乎所有 Go 服务都开 pprof。Rust 因为是 system language,继承 C++ 生态,主要用 Tracy。Java 的 async-profiler 用 asyncGetCallTrace JVM hook,独特。

### 12.2 历史演化

profiler 这件事的演化,折射了计算机系统复杂度的演化:

- **1960s-70s**:IBM mainframe 的 RMF(Resource Measurement Facility)。批处理时代,关注 throughput 不是 latency。
- **1980s**:Unix 的 `prof` / `gprof`。call graph 的概念首次出现。
- **1990s**:Windows NT 的`PStat`、Linux 的 `vmstat` / `top`。sampling profiler 起步。
- **2000s**:Intel VTune(1999)、AMD CodeAnalyst。硬件 counter 出现,profiler 能看 cache miss / branch predict。
- **2010s**:Chrome Tracing(2013)、flamegraph(2011, Brendan Gregg)、Continous profiler(2010+)。可视化大跃进。
- **2017+**:Tracy v0.1 发布。Bartosz Taudul 一人作品,成为 indie 游戏界标准。
- **2020+**:eBPF-based profiler(Linux)、Pyroscope(continuous profiling as service)。云原生时代的 profiler。

每个时代 profiler 解决那个时代的关键问题。60 年代是 batch throughput,80 年代是 single-CPU utilization,2000 年代是 cache + branch,2010 年代是 multicore + GPU,2020 年代是 distributed system。

### 12.3 开源贡献机会

Tracy 是相对友好的开源项目,有这些可贡献方向:

1. **Rust binding 完善**:[tracy-client crate](https://github.com/nagisa/rust_tracy_client)。看看哪些 Tracy C++ API 还没 wrap,提 PR。
2. **tracing-tracy 功能补全**:[tracing-tracy](https://github.com/nagisa/tracing_tracy)。GPU zone 支持、memory tracking 都有改进空间。
3. **Tracy 本体**:[wolfpld/tracy](https://github.com/wolfpld/tracy)。文档、example、bug fix。
4. **Chrome Tracing JSON 工具**:生成器、转换器、分析器。比如写一个"从 .tracy 转 chrome json"工具。
5. **Linux perf 工具链**:[perf](https://github.com/torvalds/linux/tree/master/tools/perf)。 Documentation 改进、新 event 类型。

具体 PR 方向示例:
- 给 tracy_client 加 GPU zone(目前 Rust 端 GPU 支持弱)
- 给 tracing-tracy 加 memory alloc hook(目前是手动)
- 给 Tracy 加 Vulkan GPU zone 的 Rust example
- 写一个"从 Tracy trace 提取性能回归"的脚本(对比两份 trace)

### 12.4 跨学科

profiling 不是计算机专利。其他领域有类似"测量 + 分析"的工具:

- **医学**:心电图(ECG)、功能性核磁共振(fMRI)。本质是"对人体做 sampling,然后分析异常"。
- **天文学**:望远镜 spectroscopy。测恒星光谱,推断化学组成。和 sampling profiler 推断热点代码同理。
- **金融**:市场 microstructure analysis。逐笔交易记录、订单簿变化,推断市场行为。
- **生物**:基因组测序。从 short reads 重建完整 DNA 序列。profiler 从 short samples 重建完整调用栈,理念相似。

跨学科的统一抽象:**采样子集 → 统计推断 → 全集行为**。

## 13 · 关联 Day

- **铺垫**:[../phase-4/day138.md](../day138.md) — 第一次写简单 profiler overlay;[../phase-4/day158.md](../day158.md) — 粒子系统性能调优;[../phase-5/day176.md](../phase-5/day176.md) — debug overlay 完整版,本篇扩展到 Tracy
- **当天**:本 deep dive(无对应 HH day)
- **后续**:[../phase-5/day184.md](../phase-5/day184.md) — frame time 图,本篇的 frame Mark 概念;[../phase-5/day201.md](../phase-5/day201.md) — feature 隔离 debug 代码,本篇用 `profile` feature 隔离 tracy_client;[../phase-8/deep-dives/performance-budget.md](../phase-8/deep-dives/performance-budget.md) — 性能预算,profiling 是设预算的前提

## 14 · 变式训练

### Lv1 · 概念辨析(读懂)

**题**:instrumentation、sampling、tracing 三派的差别是什么?Tracy 属于哪一派?为什么?

**参考答案**:见 1.1 / 1.2 / 1.3 节对比表。Tracy 是 tracing 派(主要 instrumentation + 因果关系 + 时间线可视化),但兼具 sampling 能力(callstack sampling)。它的核心是时间线视图 + 多线程 + 因果关系,这是 tracing 派的定义特征。

### Lv2 · 动手实践

**题**:用 `cargo new` 创建项目 `tracy-hello`,接入 tracy_client,在 main 函数加 3 个 zone,在 Tracy GUI 里看见。

**完成标准**:
1. `cargo run --features profile` 不报错
2. 启动 tracy GUI,看见 client 连接
3. 时间线显示 3 个嵌套 zone(frame / step1 / step2)

**参考解答**:见 9.1-9.5 节。

### Lv3 · 迁移设计

**题**:你的 HH 项目已经有 Day 176 的简单 profiler overlay(用 `Instant::now()` 测每帧子系统耗时)。怎么用 Tracy 替换 / 补充?

设计回答:
1. Tracy 是替换还是补充?(提示:Tracy 不显示在游戏画面上,而 overlay 显示)
2. 原 `Instant::now()` 调用站点怎么改?(提示:换成 zone RAII)
3. Feature 设计:Tracy 是 always-on 还是 feature-gated?(提示:feature,因为 client 启动要连 server)
4. Frame Mark 和 plot 怎么映射原 overlay 的数据?(提示:fps / entity count → plot,frame time → frame mark)

### Lv4 · 开源贡献

**题**:[tracy_client crate](https://github.com/nagisa/rust_tracy_client) 缺 GPU zone 支持的完整 example。

1. Clone 仓库。
2. 看 `examples/` 目录,找缺失。
3. 写一个完整 GPU zone example(用 wgpu 或 vulkano),提 PR。

PR 草稿:
```
标题:examples: add GPU zone demo with wgpu
改动:examples/wgpu-gpu-zones/{main.rs, Cargo.toml}
动机:tracing-tracy 文档说支持 GPU 但无完整 example。
     新手要从 source code 反推用法,门槛高。
     加 example,30 分钟跑起来。
验证:cargo run --example wgpu-gpu-zones,在 tracy GUI 看见 GPU lane。
```

## 15 · 延伸阅读

本仓库本地资料:
- [../phase-4/day138.md](../day138.md) — 第一次写简单 profiler overlay
- [../phase-4/day158.md](../day158.md) — 粒子系统性能
- [../phase-5/day176.md](../phase-5/day176.md) — debug overlay 完整版
- [../phase-5/day201.md](../day201.md) — feature 隔离 debug 代码
- [../phase-8/deep-dives/performance-budget.md](../phase-8/deep-dives/performance-budget.md) — 性能预算

外部稳定 URL:
- Tracy 官方:https://github.com/wolfpld/tracy
- Tracy 文档:https://github.com/wolfpld/tracy/releases/latest/download/tracy.pdf
- tracy_client crate:https://github.com/nagisa/rust_tracy_client
- tracing-tracy:https://github.com/nagisa/tracing_tracy
- Chrome Tracing 格式:https://docs.google.com/document/d/1CvAClvFfyA5R-PhYUwm5p0VUpalenlR8Ld5qnUf8HgE/
- Perfetto UI:https://ui.perfetto.dev/
- Brendan Gregg 火焰图:https://www.brendangregg.com/flamegraphs.html
- Linux perf wiki:https://perf.wiki.kernel.org/
- RenderDoc:https://renderdoc.org/
- Optick:https://github.com/bombomby/optick
- Superluminal:https://superluminal.eu/
- PIX:https://devblogs.microsoft.com/directx/pix/
- Nsight Graphics:https://developer.nvidia.com/nsight-graphics
- Unreal Frame Graph:https://docs.unrealengine.com/5.0/en-US/frame-graph-in-unreal-engine/

真实开源源码:
- Tracy client C++ 实现:https://github.com/wolfpld/tracy/blob/master/client/TracyProfiler.cpp
- Tracy public header(zone macros):https://github.com/wolfpld/tracy/blob/master/public/tracy/Tracy.hpp
- tracy_client Rust binding:https://github.com/nagisa/rust_tracy_client/blob/main/src/lib.rs
- tracing-tracy subscriber:https://github.com/nagisa/tracing_tracy/blob/main/src/lib.rs
- bevy 渲染层 profile 集成:https://github.com/bevyengine/bevy/blob/main/crates/bevy_render/src/lib.rs
- Granite frame graph:https://github.com/Themaister/Granite/blob/master/src/framework/frame_graph.cpp
