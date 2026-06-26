---
article: 24
phase: 0
title: "内存基础:虚拟内存 / 分页 / cache / 分配器 / NUMA"
type: concept
difficulty: 4
duration: "6-8h"
domains: [memory, system, game, rust, linux]
prereqs: ["07-linux-filesystem", "16-rust-toolchain-deep", "23-network-foundation"]
---

# 24 · 内存基础:从 DRAM cell 到你的 `let x = 5;`

> 你给游戏写 hot loop:每帧 100 万次迭代,每次读一个 `Vec<u32>` 的元素做点计算。代码看起来对——`for &v in &vec { sum += v; }`。你跑——12ms 一帧。你换一种写法:把 `Vec<u32>` 改成 `Vec<u64>`(数据量翻倍),你期待"慢一倍",结果**慢十倍**。你打开 perf,看见 99% 时间花在 `LLC-load-misses`。你不认识这个 perf event,也不知道为什么 u64 比 u32 慢十倍。这是**内存层级(cache / DRAM)的事**。这一篇讲完,你能 debug 这种"代码没错但慢得离谱"的问题,因为你会理解 CPU 看到的"内存"和你 `let x = 5` 写的"内存",**根本不是同一个东西**。

## 0 · 为什么要有这一天

让我把镜头拉到一个具体场景。

你跟着 Handmade Hero 走到 Day 100,你写了一个 tile-based 的渲染器。每个 tile 一个 `Tile` 结构体,大约 32 字节。地图 1000×1000 = 100 万个 tile,放在 `Vec<Tile>` 里。每帧遍历一次,挑要渲染的画。

代码大概是:

```rust
struct Tile {
    kind: u8,
    visible: bool,
    height: f32,
    color: [u8; 4],
    // 加起来 16 字节,但加 padding 32 字节
}

fn render(tiles: &[Tile]) {
    for t in tiles.iter() {
        if t.visible {
            draw_tile(t);
        }
    }
}
```

跑一下,30ms 一帧。Casey 在视频里同样代码,5ms 一帧。你 diff 一下,代码一字不差。**问题在哪儿**?

**真正的问题**:`Tile` 结构体里,`visible` 字段在 `kind` 旁边,你遍历的时候,`Tile` 整个结构体 32 字节都进了 cache line。但 visible 你只读 1 bit,**剩下 31 字节是死重量**——cache 装的多数是无用数据。100 万 tile × 32 字节 = 32 MB,你的 L3 cache 8 MB,**每次访问都是 cache miss**,直冲 DRAM,200 cycles 一个。

Casey 怎么修?**把 visible 拆成单独一个数组**:

```rust
struct World {
    visible: Vec<bool>,        // 100 万 bool
    tiles: Vec<Tile>,          // 100 万 Tile(无 visible 字段)
}

fn render(world: &World) {
    for (i, t) in world.tiles.iter().enumerate() {
        if world.visible[i] {
            draw_tile(t);
        }
    }
}
```

把"经常一起访问"的字段聚成一个数组,这是 **SoA(Struct of Arrays)** 设计。100 万 bool = 1 Mbit = 128 KB,塞进 L2。遍历 visible 数组几乎全 L2 hit,只有确实 visible 的 tile 才去访问 tile 详情,cache miss 大大减少。这个改造能让代码快 5-10 倍。

但你要懂**为什么**——你得懂 cache line、懂 false sharing、懂内存层级延迟。这些是这一篇的核心。

第二个陷阱:**分配开销**。你写 `let v: Vec<u8> = Vec::with_capacity(1024);`,看似一行。实际:`malloc` → 系统调用 `brk` 或 `mmap` → 内核给一页(4 KB)→ user space allocator 切。**一次分配可能要几微秒**。游戏每帧分配 1 万个小对象,光分配就 10ms 一帧。要做对,得用 **arena allocator**(预分配大块,从里面切)或 **object pool**(对象复用)。

第三个陷阱:**page fault**。你启动游戏,加载 1 GB 的关卡数据到内存,加载花 30 秒。然后玩家进入关卡,前 5 秒卡得不行。因为 OS 延迟分配——`mmap` 只是记下"这段虚拟地址可以用",物理内存要等**第一次访问**才给(叫 demand paging)。前 5 秒玩家走过的每个 tile 都触发 page fault,每个 fault 几十微秒。修法:**预读 / mlock**(锁住物理页)。

第四个陷阱:**NUMA**。你的 threadripper 32 核,内存控制器分两半,核 0-15 看一块内存近,核 16-31 看另一块近。你随机 spawn 线程,数据可能放在远的那块——访问延迟翻倍。要用 `numactl --membind` 或 `libnuma` 控制。

**这一篇覆盖**:
- CPU 地址空间(虚拟 vs 物理)
- 分页 / page table / TLB / page fault
- 大页 / THP(transparent huge pages)
- 内存层级:寄存器 / L1 / L2 / L3 / DRAM / SSD(延迟数字)
- Cache line(64 字节)/ alignment / false sharing
- Write policy(write-back / write-through)
- Prefetching(hardware / software)
- NUMA(多 socket CPU)
- DMA / IOMMU
- mmap / shared memory
- 内存分配:brk / mmap / malloc / arena / pool / stack allocator

**每一节**:概念 → Rust 代码 → Linux 工具验证 → 游戏场景 → 跨域关联。

**心理锚点**:这一篇读完,你能:
- 解释 L1 cache 一个 hit 1ns,L3 hit 10ns,DRAM 100ns——为什么数字差这么大
- 解释为什么 `Vec<u8>` 比 `Vec<bool>` 更快(虽然 sizeof 一样)
- 解释 false sharing 怎么把多线程程序拖到比单线程还慢
- 用 `perf stat` 看你程序的 cache miss 数
- 解释为什么游戏用 arena allocator 而不是 `malloc`
- 解释 mmap 怎么"映射"一个文件到内存
- 解释 NUMA 系统上为什么线程数 > 核数会变慢
- 用 `valgrind --tool=cachegrind` 看 cache 行为

---

## 1 · 概念地图:内存层级的 7 层

CPU 看到的"内存"实际是**一栋楼**,不是单一房间。从最快最小到最慢最大:

| 层 | 大小 | 延迟(典型) | 谁管理 |
|---|---|---|---|
| 寄存器 | ~1 KB | < 1 ns | 编译器 |
| L1 cache | 32-64 KB / 核 | ~1 ns | 硬件 |
| L2 cache | 256 KB - 1 MB / 核 | ~4 ns | 硬件 |
| L3 cache | 8-64 MB / CPU | ~12 ns | 硬件 |
| DRAM(主存) | 16-256 GB | ~100 ns | 内核 + 内存控制器 |
| SSD(NVMe) | 1-8 TB | ~100 μs | 内核 block layer |
| HDD | 几 TB | ~10 ms | (老式) |

**关键数字**:每相邻层差 **~10×** 延迟。寄存器到 L1 几乎同时,L1 到 L2 4×,L2 到 L3 3×,L3 到 DRAM 10×,DRAM 到 SSD 1000×。这种"指数级差异"决定了——**程序快慢 90% 取决于 cache 命中率**。

记住"Jeff Dean 数字":L1 ~1ns,主存 ~100ns,SSD ~100μs,磁盘 ~10ms。背下来,做所有性能估算都靠它。

```
+----------------------------+
|  CPU 核 (寄存器)            |   <-- 1 ns
+----------------------------+
            |
+----------------------------+
|  L1 / L2 / L3 cache        |   <-- 1-12 ns
+----------------------------+
            |
+----------------------------+
|  DRAM (主存)                |   <-- 100 ns
+----------------------------+
            |
+----------------------------+
|  SSD / HDD                  |   <-- 100 μs - 10 ms
+----------------------------+
```

每层都是下面一层的"缓存"。L3 缓存 DRAM,DRAM 缓存 SSD(LRU 算法在 OS 内核),SSD 缓存 HDD(如果你还有 HDD)。这是**层级化存储(memory hierarchy)** 的本质——用快的小的当慢的大的"前置缓存"。

---

## 2 · 心智模型

### 2.1 类比:你在工位上工作

把 CPU 想象成你坐在工位上写代码。

- **寄存器 = 你的脑袋**:你脑子里能立刻想到的东西。容量极小(几个变量),速度极快(瞬间)。
- **L1 cache = 你的桌面**:伸手就拿到,1 秒内。但桌面只有那么大,放不下太多。
- **L2 cache = 你的抽屉**:开抽屉,几秒。比桌面大。
- **L3 cache = 你的书柜**:站起来走两步,10 秒。和同事共享(多核共享 L3)。
- **DRAM = 楼下档案室**:坐电梯下去找,1-2 分钟。容量大。
- **SSD = 另一栋楼的仓库**:开车去,半小时。
- **HDD = 异地的仓库**:海运,几周。

程序员写代码时,如果变量在寄存器(L1),代码飞快。如果数据每访问一次都要去档案室(DRAM),慢得想砸键盘。

**怎么让数据"留在桌面"**?**Locality(局部性)** 是核心:
- **时间局部性**:刚用过的数据,等会还会用——保留在 cache。
- **空间局部性**:用了 `array[5]`,接着大概率用 `array[6]`——把整个 cache line(64 字节)都加载,后面就 hit。

数组遍历(`for x in &array`)空间局部性极好,cache 全 hit。链表遍历(`while let Some(n) = node.next`)节点随机散布,每次访问都 miss。这就是为什么 `Vec` 比 `LinkedList` 快——Rust 标准库甚至不建议用 `LinkedList`。

### 2.2 第一原理:地址空间

你写 `let x = 5;`,编译器做几件事:
1. 在栈上给 `x` 分配 4 字节(假设 `i32`)。
2. 把这 4 字节的"地址"记下来,比如 `0x7ffe4a3c0010`。
3. 把 5 写到这个地址对应的内存。

这个地址是**虚拟地址**(virtual address)——你的程序看到的"地址"。CPU 把它翻译成**物理地址**(physical address)——DRAM 芯片上的实际位置。

**为什么要虚拟**?
1. **隔离**:每个进程有自己的虚拟地址空间,互不干扰。A 进程的 0x1000 和 B 进程的 0x1000 是不同的物理内存。
2. **方便**:虚拟地址空间看起来连续,物理上可以散布。
3. **超过物理**:可以"虚拟"出比实际物理 RAM 更大的空间(用 SSD 当 swap)。

64 位 Linux,每个进程有 **128 TB** 虚拟地址空间(实际只用 48 位 = 256 TB,内核 / 用户对半)。你的笔记本 16 GB RAM,但程序能"看到"128 TB——绝大多数没映射,一旦访问就 segfault。

```
高地址 +-------------------+ 0x7FFF_FFFF_FFFF (用户空间顶)
       | 栈 ↓               |
       | ...                |
       | mmap 区             |  ← 共享库、大块 mmap
       | ...                |
       | 堆 ↑               |  ← malloc 分配
       | BSS / Data          |  ← 全局变量
       | Text (代码)          |  ← 可执行指令
低地址 +-------------------+ 0x400000 (典型)
       | (不可访问)            |  ← NULL 区(防止 NULL deref)
       +-------------------+ 0x0
```

`pmap` 或 `cat /proc/PID/maps` 看一个进程的虚拟内存布局。

### 2.3 翻译:页表和 TLB

虚拟到物理怎么翻译?**页表(page table)**。

虚拟地址空间被切成 **页(page)**,默认 4 KB。物理空间也切成**页帧(page frame)**,同样 4 KB。页表记录"虚拟页 X → 物理页帧 Y"。

虚拟地址 = 虚拟页号(VPN)+ 页内偏移(offset)。例如 64 位虚拟地址,4 KB 页 = 12 位 offset,剩 52 位 VPN。但实际 48 位有效,VPN 36 位。

**多级页表**:如果一级表存所有映射,要 36 位 × 8 字节 / 8 = 大量内存。Linux 用 **4 级页表**:
```
虚拟地址 48 位:
| 9 位 | 9 位 | 9 位 | 9 位 | 12 位 |
   PML4   PDPT   PD     PT    offset
```
每级 9 位 = 512 项(每项 8 字节,一页 4 KB 正好 512 项)。查 4 次,得到物理地址。

**问题**:每次内存访问要查 4 次页表,每次都要读内存(L1 / L2)。开销巨大。

**TLB(Translation Lookaside Buffer)**:CPU 内部的"页表缓存"。TLB 缓存最近用的虚拟→物理映射。访问内存时,先查 TLB,95%+ 命中(因为程序的访问很局部)。TLB miss 时,硬件自动 walk page table(叫 hardware page table walker),填进 TLB。

TLB 大小:典型 64-1024 项。每项覆盖 4 KB,1024 项覆盖 4 MB——对大程序不够。所以有 **大页(huge pages)**。

**Page fault**:访问的虚拟地址**没有映射**或**权限不对**,CPU 触发 page fault,内核接管。内核可能:
1. 分配新物理页(如 stack 增长、demand paging)。
2. 从 swap 读回(被换出的页)。
3. 从文件读(file-backed mmap)。
4. 杀死进程(segmentation fault)。

```bash
# 看一个进程的 page fault 数
cat /proc/$$/stat | awk '{print "minor:", $10, "major:", $12}'
# minor = soft fault(只缺页表项,数据在 DRAM)
# major = hard fault(数据要从 SSD/HDD 读)

# 实时看 page fault
perf stat -e page-faults ls /tmp
```

---

## 3 · 大页 / THP

4 KB 页太小。一个 1 GB 数据库,要 26 万个页表项,TLB 装不下,walk 频繁。

**大页(huge page)**:让一页更大。x86-64 支持:
- 4 KB(默认)
- 2 MB(huge page,512 倍)
- 1 GB(giant page,262144 倍)

2 MB 大页:同样 TLB 大小,能覆盖 1024 × 2 MB = 2 GB。walk 次数减半。

**THP(Transparent Huge Pages)**:Linux 内核自动合并 4 KB 页成 2 MB,程序员无感知。`echo always > /sys/kernel/mm/transparent_hugepage/enabled` 开启。

**风险**:THP 会让 `malloc` 慢——分配器要找 2 MB 连续物理页,可能要 defrag。某些数据库(Redis、Cassandra)反而要求**关掉** THP,因为延迟尖峰。

```bash
# 看 THP 状态
cat /sys/kernel/mm/transparent_hugepage/enabled
# [always] madvise never   ← 当前 always

# 看你进程用了多少透明大页
grep -E "AnonHugePages|FileHugePages" /proc/meminfo

# 显式分配 huge page(用于关键服务)
echo 1024 | sudo tee /proc/sys/vm/nr_hugepages  # 保留 1024 个 2MB huge page
# 然后在程序里:
# fd = open("/dev/hugepages/myfile", O_CREAT|O_RDWR, 0755);
# addr = mmap(NULL, 2*1024*1024, PROT_READ|PROT_WRITE, MAP_SHARED, fd, 0);
```

Rust 生态:`tikv-jemalloc` 默认开 THP;Redis 建议关闭。

---

## 4 · Cache 深入

### 4.1 Cache line:64 字节的搬运单元

CPU 和 DRAM 之间不是一字节一字节搬的。最小搬运单位是 **cache line**,通常 64 字节。

你访问一个 `u8`,CPU 不是只读 1 字节——**把那 1 字节所在的整个 64 字节 cache line 都拉进 L1**。所以接下来访问旁边的 63 字节,全 hit。

```rust
// 数组遍历,cache 友好
let arr: Vec<u32> = (0..1_000_000).collect();
let sum: u32 = arr.iter().sum();
// arr 里相邻 4 字节在同一 cache line,一次拉 16 个 u32。
// 全程几乎全 L1 hit,飞快。
```

```rust
// 链表遍历,cache 不友好
let mut list: LinkedList<u32> = ...;
let mut sum = 0;
for x in &list { sum += x; }
// 每个 Node 在堆上随机位置,每次访问都 cache miss,慢。
```

这就是为什么"缓存友好"代码 = "顺序访问数据"代码。

### 4.2 Set-associative cache

L1 cache 内部组织:分成 N 个 **set**,每个 set 有 W 个 **way**。地址 hash 到一个 set,在 set 内的 W 个 way 里查找。

```
L1 32 KB,8-way set-associative,line 64 字节:
sets = 32 KB / (64 × 8) = 64 sets
一个地址的 set = (地址 / 64) mod 64
```

8-way 意味着同一个 set 最多放 8 个 line。如果你的程序访问的 8 个地址都 hash 到同一个 set(叫 set conflict miss),第 9 个就要 evict 旧的。

实际几乎不会撞——除非你刻意构造(stride pattern)。但**这是性能 bug 的常见原因**。比如矩阵的"行优先 vs 列优先"遍历,如果矩阵 stride 是 cache set 数的倍数,会 conflict miss。

### 4.3 Alignment:数据放在对齐地址

CPU 喜欢"对齐"的访问——`u32` 放在 4 字节对齐的地址,`u64` 放在 8 字节对齐。

不对齐会怎样?
- **x86-64**:能处理,但慢(可能拆两次内存访问)。
- **ARM**:某些指令对齐错就 trap。
- **atomic**:必须对齐,否则 UB。

Rust 默认保证对齐:
```rust
#[repr(C)]
struct S {
    a: u8,    // 1 字节
              // padding 7 字节(为了 b 对齐 8)
    b: u64,   // 8 字节
}
// sizeof(S) = 16,align_of(S) = 8
```

**强制对齐**(Rust):
```rust
#[repr(C, align(64))]   // 强制 64 字节对齐(一个 cache line)
struct CacheLineAligned {
    data: [u8; 64],
}

// 运行时验证
let s = CacheLineAligned { data: [0; 64] };
let addr = &s as *const _ as usize;
assert!(addr % 64 == 0);
```

### 4.4 False sharing:多线程性能陷阱

两个线程各自写自己的变量,但**变量碰巧在同一 cache line**。CPU cache 一致性协议(MESI)会让这个 line 在两个核之间来回弹——一个核写了,另一个核的 L1 copy 失效,要重新加载。

```rust
// 反例:false sharing
struct Counters {
    a: u64,
    b: u64,
}
let c = Arc::new(Mutex::new(Counters::default()));

// 线程 1:疯狂 +c.a
// 线程 2:疯狂 +c.b
// 看似各干各的,实际 cache line 在两核之间疯狂弹,慢得要死。
```

修法:**padding**。让 a 和 b 不在同一 cache line。

```rust
#[repr(C)]
struct Counters {
    a: u64,
    _pad1: [u8; 56],   // 填满 64 字节 cache line
    b: u64,
    _pad2: [u8; 56],
}
// 现在 a 和 b 一定在不同 cache line。
```

Rust 有 `crossbeam::CachePadded`:
```rust
use crossbeam::CachePadded;

let c = Arc::new(Mutex::new((
    CachePadded::new(0u64),
    CachePadded::new(0u64),
)));
```

`CachePadded` 自动 padding 到 cache line。Rust 的 `AtomicU64` 经常用 `CachePadded<AtomicU64>` 包,避免 false sharing。

### 4.5 Cache 替换策略

Cache 满了,谁出去?常见策略:
- **LRU**:Least Recently Used,最久没用的出去。最常见。
- **Pseudo-LRU**:LRU 的近似,硬件好实现。Intel CPU 用这个。
- **RRIP**:更复杂的策略,AMD 用。

LRU 在 8-way cache 里实际只是"用一个 use bit 粗略记录"。对程序员透明,但你设计数据结构时要考虑"哪些数据应该被 evict"。

### 4.6 Write policy:write-back vs write-through

CPU 写数据到 cache:
- **Write-through**:同时写 cache 和下层内存。简单但慢(每次写都要访问 DRAM)。
- **Write-back**:只写 cache,标记这个 line 为 dirty。被 evict 时才写回 DRAM。

现代 CPU 全用 write-back,大幅减少 DRAM 写。

但 write-back 有问题——多核之间,一个核写了 cache,另一个核看不到。需要 **cache coherence protocol**(MESI):每个 cache line 有 4 状态——Modified(modified,独占)/ Exclusive(clean,独占)/ Shared(多核持有)/ Invalid(失效)。状态机维护一致性。

写一个 shared line 时,CPU 发 invalidate 消息给其他核,其他核把自己的 copy 标 Invalid。这就是 false sharing 慢的根源——每个写都触发 invalidate 风暴。

### 4.7 Prefetching

CPU 看到你"按顺序访问内存",**预测**你会继续顺序访问,提前把后面的 line 拉进 cache。这叫 **hardware prefetcher**。

```rust
// 顺序访问,prefetcher 帮你
for i in 0..n {
    sum += arr[i];
}
```

Prefetcher 看你前几个 access 都差 4 字节,猜你下一个也差 4 字节,提前拉。

但跳跃访问:
```rust
for i in (0..n).step_by(2048) {
    sum += arr[i];
}
// stride = 2048,prefetcher 可能猜不准
```

你也能**手动 prefetch**:
- C/C++:`__builtin_prefetch(&arr[i+32], 0, 0);`
- Rust:不直接,但有 `_mm_prefetch` SIMD intrinsic。

```rust
// Rust prefetch 示例(unsafe)
use std::arch::x86_64::_mm_prefetch;

unsafe {
    for i in 0..n {
        // 提前 32 个元素 prefetch
        if i + 32 < n {
            _mm_prefetch::<{_MM_HINT_T0}>(&arr[i + 32] as *const _ as *const i8);
        }
        sum += arr[i];
    }
}
```

实际工程中,prefetch 用得少——hardware prefetcher 太聪明,人手写一般不如自动。除非你 stride 不规则,自动 prefetcher 抓不住。

---

## 5 · NUMA:多 socket CPU

你的 threadripper / EPYC / Xeon 多芯片 CPU,内存控制器分多块。每块叫一个 **NUMA node**。

```
NUMA Node 0           NUMA Node 1
+--------------+      +--------------+
| CPU cores 0-15|      | CPU cores 16-31|
| L3 cache      |      | L3 cache      |
| DRAM 控制器 0  |      | DRAM 控制器 1  |
+--------------+      +--------------+
        |                     |
        +----- QPI/UPI -----+
              (核间互联)
```

NUMA node 0 上的核访问 node 0 的 DRAM,延迟 ~100ns。访问 node 1 的 DRAM,延迟 ~150-200ns(要走 QPI/UPI 互联)。这种**远端访问慢**是 NUMA 的核心特性。

```bash
# 看你的 NUMA 拓扑
numactl --hardware
# 输出例:
# available: 2 nodes (0-1)
# node 0 cpus: 0 1 2 ... 15
# node 1 cpus: 16 17 ... 31
# node 0 size: 32123 MB
# node 1 size: 32122 MB
# node distances:
# node  0  1
#   0: 10 21
#   1: 21 10
```

`distance 10` = 本地,`distance 21` = 远端(2.1× 延迟)。

**NUMA 优化**:
- **CPU binding**:线程绑定到核(`taskset` / `pthread_setaffinity`)。
- **Memory binding**:数据放在哪个 node(`numactl --membind`)。
- **First-touch policy**:Linux 默认,数据放在"第一次访问它的核"所在的 node。所以**初始化数据时,要在最终使用它的核上 touch**。

```bash
# 把程序绑到 node 0
numactl --cpunodebind=0 --membind=0 ./my_program

# 把程序绑到具体核 0-7
taskset -c 0-7 ./my_program

# numactl 还能 interleave(轮流分配)
numactl --interleave=all ./my_program
# 数据分散在所有 node,远端访问平均化
```

工业级 NUMA 敏感场景:数据库、HPC(高性能计算)、ML 训练。游戏单机一般一个 socket,无 NUMA。

---

## 6 · DMA 和 IOMMU

**DMA(Direct Memory Access)**:外设(SSD、网卡、GPU)**不通过 CPU**直接读写内存。CPU 设定"把这块数据从 SSD 搬到内存地址 X",然后干别的,SSD 控制器自己完成搬运,完成后中断 CPU。

DMA 加速了 IO——CPU 不用一字节一字节搬。但 DMA 要求**物理地址连续**(因为外设不懂虚拟地址)。

**IOMMU**(Input/Output MMU):给外设的"页表",让外设也能用虚拟地址。这样外设可以做 scatter-gather DMA(数据散布在不同物理页,外设按虚拟地址连续访问)。

IOMMU 也叫 **VT-d**(Intel)或 **AMD-Vi**。用途:
- **PCI passthrough**(虚拟化):把 PCIe 设备直接给虚拟机用。
- **安全**:限制外设能访问的内存区域(防止恶意设备 DMA 攻击)。
- **IOMMU groups**:Linux 用它隔离设备。

```bash
# 看 IOMMU 状态
dmesg | grep -i iommu
# 看 IOMMU groups
ls /sys/kernel/iommu_groups/
```

对游戏:GPU 和 SSD 的 DMA 性能决定加载速度。NVMe SSD + PCIe 4.0 能 7 GB/s 顺序读。前提是 OS 用了 DMA(就是),不是 CPU 拷贝。

---

## 7 · mmap:文件映射到内存

`mmap` 是 Unix 的"魔法 syscall"——把文件映射到虚拟内存。之后访问这段内存 = 读写文件,OS 自动同步。

```rust
use std::fs::File;
use memmap2::Mmap;  // crate memmap2

let file = File::open("big_data.bin")?;
let mmap = unsafe { Mmap::map(&file)? };

// 现在 mmap[0..100] 就是文件头 100 字节
let header = &mmap[..100];
println!("First byte: {}", header[0]);
```

OS 在你访问 mmap 区时,自动 page fault,从文件读对应页到 DRAM。**懒加载**——只有访问的部分才占内存。

mmap 模式:
- **MAP_PRIVATE**:写时复制(COW)。你的修改不写回文件。
- **MAP_SHARED**:修改写回文件(或共享给其他进程)。
- **MAP_ANONYMOUS**:不映射文件,纯内存分配(大块 malloc 用这个)。

**mmap 的优势**:
- 大文件不必全加载。1 GB 文件 mmap,你只访问 100 MB,只有 100 MB 占内存。
- 内核 page cache 自动缓存。
- 多进程共享同一段数据(MAP_SHARED,大家看到同一物理页)。

**mmap 的坑**:
- **page fault 延迟**:第一次访问触发 fault,几十微秒。要预热(`madvise(MADV_WILLNEED)` 或 `posix_fadvise`)。
- **SIGBUS**:文件被 truncate,mmap 访问越界 → 进程死。
- **随机访问 vs 顺序**:顺序访问 mmap 飞快;随机访问,每个 page 都 fault,可能比 read() 慢。

```rust
// Rust 用 mmap 装载大文件并预热
let file = File::open("huge.dat")?;
let mmap = unsafe { MmapOptions::new().map(&file)? };

// 告诉内核"我等会要顺序读全部"
unsafe { libc::madvise(mmap.as_ptr() as *mut _, mmap.len(), libc::MADV_SEQUENTIAL); }

// 或者"我要随机访问,但希望预热"
unsafe { libc::madvise(mmap.as_ptr() as *mut _, mmap.len(), libc::MADV_WILLNEED); }
// MADV_WILLNEED 让内核后台 prefetch
```

游戏用 mmap 加载关卡:启动时 mmap 关卡文件,玩家走过去时内核自动加载。配合 SSD + 大页,几乎无缝。

---

## 8 · 内存分配器

`malloc(1024)` 看起来一行,实际复杂。Linux 上 malloc 实现(glibc malloc / jemalloc / mimalloc)做的事:

### 8.1 brk 和 mmap:两个底层 syscall

- **brk / sbrk**:扩展"堆"指针。`brk(addr)` 把堆顶设到 addr,堆就增长到那里。malloc 小对象(< 128 KB)用 brk。
- **mmap**:大块分配。malloc 大对象(>= 128 KB)用 mmap,直接向内核要一页。

```bash
strace -e trace=brk,mmap ./your_program
# 看你的程序实际怎么调
```

### 8.2 glibc malloc:ptmalloc

设计:
- 小分配(< 512 bytes):用"fastbin",单链表,分配释放 O(1)。
- 中分配(512 bytes - 128 KB):用"small / large bin",按 size 分桶。
- 大分配(>= 128 KB):直接 mmap。

每次释放后,空闲 chunk 可能合并(coalesce),防止碎片。但碎片仍是大问题——长期运行的服务,内存使用率可能 50% 都是碎片。

### 8.3 替代品

**jemalloc**(Facebook / Jason Evans):thread-local cache,减少锁竞争。Rust 默认 allocator。Firefox、Redis、Rust 用。

**tcmalloc**(Google):类似 jemalloc,Chrome 用。

**mimalloc**(Microsoft):更现代,低碎片。Daan Leijen 设计。

**Hoard**:多核友好。

Rust 切换 allocator:
```toml
# Cargo.toml
[dependencies]
tikv-jemallocator = "0.5"
```

```rust
// src/main.rs
#[global_allocator]
static ALLOC: tikv_jemallocator::Jemalloc = tikv_jemallocator::Jemalloc;
```

切换后,所有 `Vec` / `Box` 等都走 jemalloc。

### 8.4 Arena allocator:游戏的杀手锏

游戏每帧分配大量临时对象(粒子、UI 控件、调试字符串)。**用 malloc 每帧几万次调用,几毫秒浪费在分配器上**。

**Arena allocator**:预分配一大块,从这里"bump"分配——只动一个指针,不释放。一帧结束,**整块丢弃**(指针归零),下一帧重新用。

```rust
pub struct Arena {
    buffer: Vec<u8>,
    offset: usize,
}

impl Arena {
    pub fn new(capacity: usize) -> Self {
        Self { buffer: vec![0; capacity], offset: 0 }
    }
    
    pub fn alloc<T: Default + Copy>(&mut self) -> Option<&mut T> {
        let size = std::mem::size_of::<T>();
        let align = std::mem::align_of::<T>();
        
        // 对齐
        let aligned_offset = (self.offset + align - 1) & !(align - 1);
        if aligned_offset + size > self.buffer.len() {
            return None;
        }
        
        let ptr = self.buffer.as_mut_ptr().wrapping_add(aligned_offset) as *mut T;
        self.offset = aligned_offset + size;
        unsafe { ptr.write(T::default()); }
        Some(unsafe { &mut *ptr })
    }
    
    pub fn reset(&mut self) {
        self.offset = 0;
    }
}
```

每帧开始 `arena.reset()`,然后随便 `arena.alloc()`。一帧用几 KB,几乎零开销。

工业级 Rust arena crate:
- `bumpalo`:成熟的 arena allocator。
- `typed-arena`:类型化的 arena。
- `id-arena`:arena + ID(代替指针,避免生命周期)。

### 8.5 Pool allocator:对象复用

类似 arena,但**对象不丢弃,放回池子**。常用于固定大小的对象(子弹、敌人、网络包)。

```rust
pub struct Pool<T> {
    items: Vec<T>,
    free_list: Vec<usize>,
}

impl<T> Pool<T> {
    pub fn new(capacity: usize, factory: impl Fn() -> T) -> Self {
        let items = (0..capacity).map(|_| factory()).collect();
        let free_list = (0..capacity).collect();
        Self { items, free_list }
    }
    
    pub fn acquire(&mut self, factory: impl Fn() -> T) -> Option<&mut T> {
        let idx = self.free_list.pop()?;
        let item = &mut self.items[idx];
        *item = factory();
        Some(item)
    }
    
    pub fn release(&mut self, idx: usize) {
        self.free_list.push(idx);
    }
}
```

游戏里"子弹池"特别经典——开火时 acquire,子弹消失时 release。绝不每帧 malloc/free。

### 8.6 Stack allocator

栈式分配,只能 LIFO 释放。比 arena 灵活一点,但要求严格的 push/pop 配对。

```rust
pub struct StackAllocator {
    buffer: Vec<u8>,
    offset: usize,
}

impl StackAllocator {
    pub fn push(&mut self, size: usize) -> &mut [u8] {
        let start = self.offset;
        self.offset += size;
        &mut self.buffer[start..self.offset]
    }
    
    pub fn pop(&mut self, size: usize) {
        self.offset -= size;
    }
}
```

用于嵌套作用域的临时分配(物理模拟、渲染子系统)。

---

## 9 · 实战:Rust cache 友好代码

我们做一个 benchmark,对比"cache 友好"和"cache 不友好"代码的差距。

### 9.1 false sharing benchmark

```toml
[package]
name = "false-sharing-bench"
version = "0.1.0"
edition = "2021"

[dependencies]
crossbeam = "0.8"
```

```rust
// src/main.rs
use std::sync::atomic::{AtomicU64, Ordering};
use std::thread;
use std::time::Instant;
use crossbeam::CachePadded;

const ITERS: u64 = 100_000_000;

// 反例:false sharing
struct CountersBad {
    a: AtomicU64,
    b: AtomicU64,
}

fn bench_bad() -> u128 {
    let c = std::sync::Arc::new(CountersBad {
        a: AtomicU64::new(0),
        b: AtomicU64::new(0),
    });
    
    let c1 = c.clone();
    let t1 = thread::spawn(move || {
        let start = Instant::now();
        for _ in 0..ITERS {
            c1.a.fetch_add(1, Ordering::Relaxed);
        }
        start.elapsed().as_millis()
    });
    
    let c2 = c.clone();
    let t2 = thread::spawn(move || {
        let start = Instant::now();
        for _ in 0..ITERS {
            c2.b.fetch_add(1, Ordering::Relaxed);
        }
        start.elapsed().as_millis()
    });
    
    let (t1, t2) = (t1.join().unwrap(), t2.join().unwrap());
    t1.max(t2)
}

// 正例:CachePadded 避免 false sharing
struct CountersGood {
    a: CachePadded<AtomicU64>,
    b: CachePadded<AtomicU64>,
}

fn bench_good() -> u128 {
    let c = std::sync::Arc::new(CountersGood {
        a: CachePadded::new(AtomicU64::new(0)),
        b: CachePadded::new(AtomicU64::new(0)),
    });
    
    let c1 = c.clone();
    let t1 = thread::spawn(move || {
        let start = Instant::now();
        for _ in 0..ITERS {
            c1.a.fetch_add(1, Ordering::Relaxed);
        }
        start.elapsed().as_millis()
    });
    
    let c2 = c.clone();
    let t2 = thread::spawn(move || {
        let start = Instant::now();
        for _ in 0..ITERS {
            c2.b.fetch_add(1, Ordering::Relaxed);
        }
        start.elapsed().as_millis()
    });
    
    let (t1, t2) = (t1.join().unwrap(), t2.join().unwrap());
    t1.max(t2)
}

fn main() {
    println!("Bad (false sharing): {} ms", bench_bad());
    println!("Good (padded):       {} ms", bench_good());
    // 输出大概:
    // Bad: 800 ms
    // Good: 200 ms
    // 4× 差距
}
```

跑这个你会看到 4× 差距。这就是 cache coherence 协议的开销——每个原子操作,如果目标 cache line 在另一核手上 modified,要先发 invalidate,等对方回 ACK,才能改。padding 后 a 和 b 在不同 line,两核独立,无干扰。

### 9.2 用 perf 验证

```bash
# 看 cache miss 数
sudo perf stat -e cache-misses,cache-references,L1-dcache-load-misses,LLC-load-misses \
    ./target/release/false-sharing-bench

# 输出大概:
# <not counted> cache-misses
# 1,234,567,890  cache-references
# 567,890,123    L1-dcache-load-misses    # ← bad 版这个高
# 1,234,567      LLC-load-misses
```

`LLC-load-misses` 高 = L3 cache miss = 跑到 DRAM 了。

### 9.3 cacheline alignment

让一个结构体独占 cache line:

```rust
#[repr(C, align(64))]
struct HotCounter {
    value: AtomicU64,
    _pad: [u8; 56],   // 让 sizeof = 64
}

// 或者用 crossbeam
use crossbeam::CachePadded;
let counter = CachePadded::new(AtomicU64::new(0));
```

### 9.4 prefetch 实验

```rust
fn sum_with_prefetch(arr: &[u32]) -> u32 {
    let mut sum = 0u32;
    for i in 0..arr.len() {
        unsafe {
            // 提前 32 个元素 prefetch
            if i + 32 < arr.len() {
                use std::arch::x86_64::{_mm_prefetch, _MM_HINT_T0};
                _mm_prefetch::<{_MM_HINT_T0}>(
                    arr.as_ptr().add(i + 32) as *const i8
                );
            }
        }
        sum = sum.wrapping_add(arr[i]);
    }
    sum
}
```

实测:对小数组(< L1)prefetch 无效;对超大数组(几十 MB)prefetch 可能快 5-15%。**但 hardware prefetcher 通常够好**,手动 prefetch 价值有限。

---

## 10 · 四域深入

### 10.1 游戏编程视角

游戏是 cache 性能的极端场景——60 FPS = 16ms 一帧,任何 cache miss 都致命。常见优化:

**SoA(Struct of Arrays)**:把"每个对象一个 struct"改成"一组对象,每字段一个数组"。ECS 架构(bevy、Unity DOTS)本质是 SoA。

```rust
// AoS(Array of Structs)—— 传统写法
struct Entity {
    pos: Vec3,
    vel: Vec3,
    health: f32,
}
let entities: Vec<Entity> = ...;

// SoA(Struct of Arrays)—— cache 友好
struct World {
    pos: Vec<Vec3>,
    vel: Vec<Vec3>,
    health: Vec<f32>,
}
// 只遍历 pos 时,vel 和 health 不进 cache,带宽省 2/3
```

**对象池**:子弹、敌人、特效这些高频创建/销毁的对象,用 pool。

**Arena per frame**:每帧临时分配,统一 reset。

**内存紧凑布局**:bit-packing、enum 替代 vtable、避免 `Box<dyn Trait>`。

工业级:Casey 在 Handmade Hero 里大量用"transient memory"——一帧用完就丢的内存。Unity DOTS 用 ECS + chunk-based memory。Unreal 用 Mass Entity。

### 10.2 图形学视角

GPU 也有内存层级——寄存器 / L1 / L2 / VRAM。GPU 编程的"性能"很大程度是**memory bandwidth**(带宽)管理。

- **Texture compression**(BC1-7 / ASTC / ETC2):纹理占 VRAM 大,压缩 4-8 倍,带宽省。
- **Vertex format**:位置用 f32 还是 f16?法线用 8-bit 还是 10-bit?直接影响 GPU 带宽。
- **Compute shader group size**:选择 32 / 64 / 256,匹配 wavefront / warp 大小,优化 L1 共享。
- **GPU residency**:大数据(高分辨率纹理)放 host RAM,按需 DMA 到 VRAM,叫 "texture streaming"。

CPU-GPU 数据传输(PCIe)是慢的——16 GB/s 量级,远低于 VRAM 带宽(几百 GB/s)。所以要最小化 CPU-GPU 同步。

### 10.3 Linux 系统编程视角

Linux 内核对内存的视图:

```bash
# 看系统内存
free -h
#                total   used   free  shared  buff/cache  available
# Mem:            31Gi   4.2Gi   20Gi   312Mi      6.8Gi        26Gi
# Swap:          8.0Gi      0B   8.0Gi

# buff/cache 是 OS page cache —— 加速文件 IO
# 真正"可用"内存看 available
```

```bash
# 看一个进程的内存
ps aux | grep firefox
# RSS = resident set size(物理内存中)
# VSZ = virtual size

cat /proc/$(pidof firefox)/status | grep -E 'Vm|Rss'
# VmPeak / VmSize / VmLck / VmRSS / VmData / VmStk / VmExe / VmLib / VmPTE ...

# 看进程的 maps
pmap -x $(pidof firefox) | head -50
# 看每段虚拟内存的地址、权限、大小、映射文件
```

```bash
# /proc/meminfo 看细节
cat /proc/meminfo | head -30
# MemTotal / MemFree / Buffers / Cached / SwapCached / Active / Inactive / ...
# 关键看 Active vs Inactive,SwapCached(被换出但 cache 还在)
```

```bash
# OOM killer
dmesg | grep -i 'killed process'
# 看 OOM 历史
```

**Swap**:Linux 可以把不常用的内存页换到 SSD(swap 区),腾出物理 RAM。但 swap 性能差,游戏 server 通常禁用 swap(`swapoff -a`)避免延迟尖峰。

**cgroups memory**:容器(Docker / Podman)限制内存。`docker run --memory=2g ...` 设置 2 GB 上限,超出就 OOM kill。

### 10.4 Rust 生态视角

Rust 的所有权和借用系统,让很多内存 bug 编译期消失。但底层 allocation 还是要懂。

**Rust allocator**:`std::alloc::GlobalAlloc` trait。可以实现自己的 allocator。

```rust
use std::alloc::{GlobalAlloc, Layout};

struct MyAllocator;

unsafe impl GlobalAlloc for MyAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        // 你自己的实现
        std::alloc::System.alloc(layout)
    }
    
    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        std::alloc::System.dealloc(ptr, layout)
    }
}

#[global_allocator]
static A: MyAllocator = MyAllocator;
```

**Rust 内存库**:
- `bumpalo`:arena allocator
- `typed-arena`:类型化 arena
- `slotmap`:池 + ID
- `sharded-slab`:并发池
- `crossbeam::CachePadded`:cache line 对齐
- `bytemuck`:安全的字节转换

**内存分析工具**:
- `valgrind --tool=massif`:heap profiler
- `heaptrack`(KDE):更现代的 heap profiler
- `dhat`:Rust 集成的 heap 分析
- `bytehound`:Rust 内存 profiler

```bash
# 用 heaptrack 分析 Rust 程序
heaptrack target/release/my_program
heaptrack_printers heaptrack.my_program.12345.gz
# 输出:每个调用点的分配量、峰值、热点
```

---

## 11 · 认知地图

### 11.1 上级

- **计算机体系结构**:cache、虚拟内存是体系结构的核心话题。Hennessy & Patterson 的书是圣经。
- **操作系统**:Linux 内核的内存管理(mm subsystem)是最大的子系统之一。
- **性能工程**:cache miss 是性能优化的核心战场。

### 11.2 同级

| 主题 | 关系 |
|---|---|
| 并发(本系列 25) | 多线程 cache coherence 协议(MESI) |
| 网络(本系列 23) | 网络 buffer 大小调优,内核网络栈 cache 行为 |
| 编译器 | LLVM 自动向量化、循环展开,目标就是 cache 友好 |

### 11.3 下级

- DRAM cell 结构(电容 + 晶体管)
- Cache coherence protocol(MESI / MOESI / MESIF)
- Page table 数据结构(多级页表 / 反向页表 / hashed page table)
- TLB / VPI / PCID(进程上下文 ID)
- Swapping / OOM / cgroups

---

## 12 · 对照与变奏

### 12.1 跨语言内存管理

**C**:`malloc` / `free`,手动管理,bug 多。`valgrind` 是必需工具。

**C++**:`new` / `delete`,RAII,智能指针(`unique_ptr` / `shared_ptr`)。现代 C++ 接近 Rust 安全。

**Java / C#**:GC(垃圾回收)。无内存泄漏(理论上),但 GC 暂停是游戏杀手。Unity / Unreal 用 C# 时,有 incremental GC / IL2CPP 缓解。

**Go**:GC,设计为低延迟(< 10ms 暂停),但游戏仍嫌慢。

**Python / Ruby**:引用计数 + 周期 GC。性能不够,游戏服务器一般不用。

**Rust**:所有权 + 借用。编译期决定何时 free,**零运行时开销**。游戏服务器、嵌入式、内核 driver 用 Rust 越来越多。

### 12.2 历史演化

- **1950s**:磁芯内存、磁鼓。程序员手动管理每个字节。
- **1960s**:虚拟内存概念(Multics)。
- **1970s**:Unix 的 `brk` / `sbrk`,C 的 `malloc`。
- **1980s**:MMU(内存管理单元)普及,虚拟内存成为主流。
- **1990s**:多核 CPU 出现,cache coherence 协议(MESI)标准化。
- **2000s**:大页(2 MB / 1 GB)x86-64 支持。
- **2010s**:NUMA 多 socket 主流;SSD 取代 HDD,内存层级多一层。
- **2020s**:CXL(Compute Express Link)—— 内存解耦,服务器可以共享内存池。Rust 在 Linux 内核。

每个十年,内存层级变深,程序员更要懂 cache。

### 12.3 安全视角

内存 bug 是安全漏洞的最大来源。Buffer overflow、use-after-free、double-free、format string——都和内存模型有关。

防御:
- **ASLR**:地址空间随机化,攻击者难预测地址。
- **DEP / NX**:不可执行内存区。
- **Stack canary**:栈溢出检测。
- **CFI**(Control Flow Integrity):控制流完整性,防 ROP。
- **MTE**(Memory Tagging Extension,ARM)、**MPX**(Intel,已废弃)、**KASAN**(Linux 内核):运行时内存检测。

Rust 的所有权系统从根本上消除大量内存 bug。但 unsafe Rust / FFI 仍有风险。

---

## 13 · 关联 Day

- **铺垫**:[day007-linux-filesystem.md](../phase-0/07-linux-filesystem.md) — 文件系统和 page cache 关系
- **当天**:[24-memory-foundation.md](24-memory-foundation.md)(本篇)
- **后续**:[25-concurrency-foundation.md](25-concurrency-foundation.md) — 多线程和原子操作依赖内存模型;[day078-memory-arena.md](../phase-3/day078.md) — Handmade Hero 的 arena allocator 实现;[day240-cache-friendly-ecs.md](../phase-5/day240.md)(假设)— ECS cache 优化

---

## 14 · 变式训练

### Lv1 · 概念辨析

**题**:为什么 L1 cache 一个 hit ~1 ns,DRAM access ~100 ns?差 100×的原因是什么?

**参考答案**:
1. **物理距离**:L1 在 CPU 核旁边,导线几毫米;DRAM 在 DIMM 槽,导线几厘米。光速决定信号走这段距离的延迟。
2. **电路类型**:L1 是 SRAM(6 个晶体管 / bit,快速但贵);DRAM 是 1 晶体管 + 1 电容 / bit,慢但密度高。
3. **架构**:DRAM 要"行地址 → 列地址"两步访问,而且要刷新(refresh,电容会漏电)。L1 直接译码地址。
4. **共享性**:L1 每核独占,无竞争;DRAM 全核共享,内存控制器排队。

每个因素叠加,DRAM 比 L1 慢 100×。

### Lv2 · 动手实践

**题**:写一个 Rust benchmark,对比:
1. 顺序遍历 `Vec<u32>` 求和
2. 跳跃遍历(stride = 16,即每 16 个取一个)求和
3. 随机遍历(随机下标)求和

每种跑 1 亿次,打印耗时。**完成标准**:
- 三种差距明显(顺序最快,随机最慢)
- 用 perf 看 cache miss 数,验证随机遍历 miss 多

**参考解答**:

```rust
use std::time::Instant;

const SIZE: usize = 4_000_000;  // 16 MB,大于 L3
const SUMS: u32 = 100;

fn seq_sum(arr: &[u32]) -> u32 {
    let mut s = 0u32;
    for _ in 0..SUMS {
        for &v in arr {
            s = s.wrapping_add(v);
        }
    }
    s
}

fn stride_sum(arr: &[u32]) -> u32 {
    let mut s = 0u32;
    for _ in 0..(SUMS * 16) {
        for i in (0..arr.len()).step_by(16) {
            s = s.wrapping_add(arr[i]);
        }
    }
    s
}

fn random_sum(arr: &[u32], indices: &[usize]) -> u32 {
    let mut s = 0u32;
    for _ in 0..SUMS {
        for &i in indices {
            s = s.wrapping_add(arr[i]);
        }
    }
    s
}

fn main() {
    let arr: Vec<u32> = (0..SIZE).map(|_| 1).collect();
    let mut indices: Vec<usize> = (0..SIZE).collect();
    // shuffle
    use std::time::SystemTime;
    let seed = SystemTime::now().duration_since(SystemTime::UNIX_EPOCH).unwrap();
    let mut state = seed.as_nanos() as u64;
    for i in (1..indices.len()).rev() {
        state = state.wrapping_mul(6364136223846793005).wrapping_add(1);
        let j = (state >> 33) as usize % (i + 1);
        indices.swap(i, j);
    }
    
    let t = Instant::now();
    let _ = seq_sum(&arr);
    println!("Sequential: {} ms", t.elapsed().as_millis());
    
    let t = Instant::now();
    let _ = stride_sum(&arr);
    println!("Stride 16:  {} ms", t.elapsed().as_millis());
    
    let t = Instant::now();
    let _ = random_sum(&arr, &indices);
    println!("Random:     {} ms", t.elapsed().as_millis());
}
```

跑下来典型差距:sequential 100 ms,stride 300 ms,random 8000 ms。**80× 差距**。这就是 cache 的威力。

### Lv3 · 迁移设计

**题**:你接手一个 Rust ECS 游戏引擎,每帧 30ms。profile 显示 80% 时间在"遍历所有 entity 找 visible 的渲染"。当前每个 entity 是 `struct Entity { pos, vel, health, mesh, material, ... }` 共 256 字节,放在 `Vec<Entity>`。

设计 SoA 重构,回答:
1. 哪些字段应该一起分组?(提示:同一系统读的字段)
2. 怎么处理"组件可选"(某些 entity 没 health)?
3. 怎么测重构效果?(perf / cachegrind)
4. 重构有什么风险?(代码可读性、API 兼容)

写一份 200 字设计文档。

### Lv4 · 开源贡献

**题**:`bevy` 是 Rust 主流 ECS 引擎。`gh repo clone bevyengine/bevy`,看 `crates/bevy_ecs/src/storage/`。

1. 看 bevy 怎么存储组件(archetype-based vs sparse set)。
2. 找一个 cache-related issue(性能 / 优化 / 内存布局)。
3. 写一个 micro-benchmark 验证某段代码的 cache 行为。
4. 提一个 PR 改进(可以是文档,也可以是 perf 优化)。

---

## 15 · Rust / Arch 落地清单

### 15.1 装工具

```bash
# 性能 / 内存分析
sudo pacman -S perf                # 内置(Linux tools)
sudo pacman -S valgrind            # 内存检测 / cache 分析
sudo pacman -S heaptrack           # heap profiler
sudo pacman -S numactl             # NUMA 控制
sudo pacman -S dmidecode           # 硬件信息
sudo pacman -S lscpu               # 已装(util-linux)

# Rust
cargo install cargo-flamegraph     # 火焰图
cargo install dhat                 # heap 分析
cargo install bytehound --features [=default]  # 内存 profiler
```

### 15.2 看硬件

```bash
# CPU 信息
lscpu
# 关键字段:
#   CPU(s):              16    核数
#   On-line CPU(s) list: 0-15
#   Model name:          AMD Ryzen 9 ...
#   CPU(s) scaling MHz:  2200
#   L1d cache:           32K    ← L1 数据 cache
#   L1i cache:           32K    ← L1 指令 cache
#   L2 cache:            512K
#   L3 cache:            32768K ← L3(共享)
#   NUMA node(s):        1
#   Architecture:        x86-64

# 内存信息
sudo dmidecode -t memory | head -40
# 设备 / 大小 / 速度 / 厂商

# NUMA 拓扑
numactl --hardware
numactl --cpubind=0 --membind=0 echo "bound to node 0"
```

### 15.3 perf 实战

```bash
# 程序整体统计
sudo perf stat ./target/release/my_program
# 输出 cycles / instructions / cache-misses / branch-misses / ...

# 看 cache miss 细节
sudo perf stat -e cache-references,cache-misses,L1-dcache-load-misses,\
LLC-load-misses,LLC-loads \
    ./target/release/my_program

# 火焰图
sudo perf record -F 99 -g -- ./target/release/my_program
sudo perf script | flamegraph.pl > flame.svg
# flamegraph.pl 在 github.com/brendangregg/FlameGraph

# perf top 实时
sudo perf top
```

### 15.4 cachegrind

```bash
# 用 valgrind 的 cachegrind 模拟 cache 行为
valgrind --tool=cachegrind --cache-sim=yes ./target/release/my_program
# 输出:
# I1 misses / LLi misses (instruction cache)
# D1 misses / LLd misses (data cache)
# LL misses (last level = L3)

# 生成分析报告
cg_annotate cachegrind.out.<pid> | head -50
```

cachegrind 模拟,慢 20-50×,但能给精确 cache miss 数。

### 15.5 调优

```bash
# THP
echo always | sudo tee /sys/kernel/mm/transparent_hugepage/enabled

# 大页
echo 1024 | sudo tee /proc/sys/vm/nr_hugepages

# Swap
sudo swapoff -a    # 关 swap(游戏 server 常用)

# vm.swappiness(0-100,越高越倾向 swap)
sysctl vm.swappiness    # 默认 60
sudo sysctl -w vm.swappiness=10

# dirty ratio(写盘时机)
sysctl vm.dirty_ratio
sysctl vm.dirty_background_ratio
```

---

## 16 · Troubleshooting

**问题1**:程序随机 segfault,跑 valgrind 看不出问题。
诊断:可能是 use-after-free。Rust safe 代码不会,但 unsafe / FFI 会。开 ASAN:`RUSTFLAGS="-Zsanitizer=address" cargo +nightly build`。

**问题2**:多线程性能不如单线程。
诊断:false sharing 或 lock contention。perf top 看热点函数。如果是 `__pthread_mutex_lock`,是锁;如果是 `_mm_pause`,是 spin。`perf c2c` 工具能直接检测 false sharing。

**问题3**:启动慢,预热后正常。
诊断:page fault。`perf stat -e page-faults`。修法:`mlock` 锁住关键页,或 `madvise(MADV_WILLNEED)` 预读。

**问题4**:进程内存持续增长。
诊断:内存泄漏。`heaptrack target/release/my_program`,看哪个调用点分配多。

**问题5**:NUMA 系统多线程慢。
诊断:`numastat -p`,看每个 node 的分配。如果都在 node 0,说明 first-touch 不均。修法:`numactl --interleave=all` 或重写 first-touch 代码。

---

## 17 · 延伸阅读

本仓库本地资料:
- [07-linux-filesystem.md](07-linux-filesystem.md) — page cache
- [23-network-foundation.md](23-network-foundation.md) — 网络 buffer
- [25-concurrency-foundation.md](25-concurrency-foundation.md) — 原子操作内存模型

外部稳定 URL:
- What Every Programmer Should Know About Memory(Ulrich Drepper):https://people.freebsd.org/~lstewart/articles/cpumemory.pdf
- CPU Cache:https://en.wikipedia.org/wiki/CPU_cache
- MESI protocol:https://en.wikipedia.org/wiki/MESI_protocol
- NUMA:https://www.kernel.org/doc/html/latest/admin-guide/mm/numa_memory_policy.html
- Valgrind:https://valgrind.org/docs/manual/manual.html
- Brendan Gregg's perf examples:https://www.brendangregg.com/perf.html
- Rust Allocator API:https://doc.rust-lang.org/std/alloc/index.html
- jemalloc:https://github.com/jemalloc/jemalloc
- mimalloc:https://github.com/microsoft/mimalloc

真实开源源码:
- Linux mm 子系统:https://github.com/torvalds/linux/tree/master/mm
- glibc malloc:https://sourceware.org/git/?p=glibc.git
- jemalloc:https://github.com/jemalloc/jemalloc
- Bevy ECS storage:https://github.com/bevyengine/bevy/tree/main/crates/bevy_ecs/src/storage
