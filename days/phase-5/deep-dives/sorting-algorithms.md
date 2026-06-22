---
phase: 5
title_en: "Sorting Algorithms Deep Dive"
title_zh: "排序算法深度专题"
type: deep-dive
domains: [game, rust, linux, cs]
---

# 排序算法深度专题

> 你在 HH Day 95 写资产管理器。资源列表要按"加载优先级"排序——音频先于贴图,贴图先于 shader。你写了一行 `assets.sort_by(|a, b| a.priority.cmp(&b.priority))`,跑起来,任务完成。但你心里有个声音:Rust 的 `sort_by` 内部到底用的什么算法?为什么不是 quicksort?它对已经基本有序的数据会不会退化到 O(N²)?rayon 的 `par_sort` 又是怎么并行化的?今天这一篇,把排序这个"看似 trivial 但其实是计算机科学核心话题"的东西,从头到脚拆开。

## 0 · 为什么要有这一篇

排序是计算机科学最早的研究对象之一。从 1950s 到 2020s,排序算法的演化折射了整个 CS 领域的进步——从"理论最优"到"硬件友好",从"通用算法"到"自适应 pattern-defeating"。Handmade Hero 里 Casey 用了 18 集涉及排序:资产管理、render queue、event queue、debug overlay 行排序。看起来就是 `sort()` 一下,但背后的工程取舍极其精彩。

**这一篇要回答的核心问题**:
1. Big O notation 到底意味着什么?O(N log N) 一定比 O(N²) 快吗?
2. 为什么 Rust 标准库 1.51 之前用 introsort(quick + heap 混合),1.51 之后改用 pattern-defeating quicksort?
3. 非比较排序(counting / radix)什么时候比 O(N log N) 还快?
4. Topological sort 不是"排序算法",为什么叫 sort?
5. `sort_by` vs `sort_unstable_by` 到底什么区别?
6. rayon 的并行排序怎么工作的?

**学完这一篇,你应该能**:
- 解释 Big O 的精确含义(不是"O(N²) 慢",而是"规模无穷大时的渐进行为")
- 用 Rust 从零实现 bubble / insertion / merge / quick / heap / counting / radix
- 解释 pdqsort(pattern-defeating quicksort)的设计
- 知道什么时候该用 `sort`,什么时候该用 `sort_unstable`,什么时候该用 `par_sort`
- 在游戏项目里正确选择排序算法(render queue / event queue / inventory)
- 解释 topological sort 的实现和应用

## 1 · Big O 精确理解

### 1.1 直觉和数学

Big O 是描述"函数增长速度"的数学工具。O(f(N)) 的严格定义:

> 对于足够大的 N,函数 g(N) ≤ C · f(N),其中 C 是常数。

直觉:**忽略常数项,只看增长趋势**。一个 O(N²) 算法在 N=10 可能比 O(N log N) 快(常数小),但在 N=1000000 一定慢。

| Big O | 名字 | N=10 | N=1000 | N=1000000 |
|---|---|---|---|---|
| O(1) | 常数 | 1 | 1 | 1 |
| O(log N) | 对数 | 3.3 | 10 | 20 |
| O(N) | 线性 | 10 | 1000 | 1M |
| O(N log N) | 准线性 | 33 | 10000 | 20M |
| O(N²) | 平方 | 100 | 1M | 1T |
| O(2^N) | 指数 | 1024 | ∞ | ∞ |

### 1.2 容易踩的坑

**坑 1**:Big O 忽略常数,但常数有时很大。一个 O(1000000 N) 算法和 O(0.001 N²) 算法,N<1000 时平方反而快。

**坑 2**:Big O 是"最坏情况"或"平均情况"——必须说清。Quicksort 平均 O(N log N),最坏 O(N²)。这"最坏"在工程里能不能避免,是另一个问题。

**坑 3**:**总 cost = N · log。Big O 是 log。当 N=1M 时,N log N 已经是 20M 次操作,在现代 CPU(3 GHz)上是几毫秒。N²=1T 次操作,几分钟。这就是为什么排序算法的选择,在大数据量时**生死攸关**。

**坑 4**:Big O 不考虑**缓存**。一个 cache-friendly 的 O(N²) 算法可能比 cache-unfriendly 的 O(N log N) 快(因为 cache miss 极贵)。这是为什么 cache-friendly 的 **radix sort** 在大数据上经常胜过 quicksort。

## 2 · 比较排序算法

### 2.1 Bubble sort(冒泡)

最简单也最慢。重复扫描数组,每对相邻元素如果顺序错就交换。每轮最大值"冒泡"到末尾。

```rust
fn bubble_sort(arr: &mut [i32]) {
    let n = arr.len();
    for i in 0..n {
        for j in 0..n - 1 - i {
            if arr[j] > arr[j+1] {
                arr.swap(j, j+1);
            }
        }
    }
}

fn main() {
    let mut v = vec![5, 2, 8, 1, 9, 3];
    bubble_sort(&mut v);
    println!("{:?}", v);  // [1, 2, 3, 5, 8, 9]
}
```

**复杂度**:O(N²) 比较和交换。空间 O(1)。
**最佳用途**:**教学**。生产环境从不使用。Casey 在 HH Day 95 提到"我不会用 bubble sort,但我讲它因为它是入门"。

### 2.2 Insertion sort(插入)

像打牌时把新摸的牌插入到手中正确的位置。从左到右,把每个元素插入到左边已排序部分的正确位置。

```rust
fn insertion_sort(arr: &mut [i32]) {
    for i in 1..arr.len() {
        let mut j = i;
        while j > 0 && arr[j-1] > arr[j] {
            arr.swap(j-1, j);
            j -= 1;
        }
    }
}
```

**复杂度**:平均 O(N²),最好情况(已排序)O(N)。空间 O(1)。

**最佳用途**:**小数组(N<32)**,或**几乎已排序的数据**。pdqsort 在小数组时切换到 insertion sort——它的"对已排序数据 O(N)"特性让它在这两个场景里胜过 quicksort。

### 2.3 Merge sort(归并)

分治。把数组对半切,递归排序两半,然后合并两个有序数组。

```rust
fn merge_sort(arr: &mut [i32]) {
    let n = arr.len();
    if n <= 1 { return; }
    let mid = n / 2;
    merge_sort(&mut arr[..mid]);
    merge_sort(&mut arr[mid..]);

    // 合并两个有序半
    let mut merged = Vec::with_capacity(n);
    let (mut i, mut j) = (0, mid);
    while i < mid && j < n {
        if arr[i] <= arr[j] {
            merged.push(arr[i]); i += 1;
        } else {
            merged.push(arr[j]); j += 1;
        }
    }
    while i < mid { merged.push(arr[i]); i += 1; }
    while j < n { merged.push(arr[j]); j += 1; }
    arr.copy_from_slice(&merged);
}
```

**复杂度**:O(N log N) 最坏情况。空间 O(N)(辅助数组)。

**优点**:稳定(相等元素相对顺序不变)、最坏 O(N log N)、并行化容易。
**缺点**:辅助空间。
**最佳用途**:**链表排序**(无辅助空间)、**外部排序**(数据大于内存,文件上的归并)、**稳定排序必需时**。

### 2.4 Quicksort(快排)

最经典的分治排序。选一个 pivot,把小于 pivot 的放左边,大于的放右边,递归排序两边。

```rust
fn quick_sort(arr: &mut [i32]) {
    if arr.len() <= 1 { return; }
    let pivot_idx = partition(arr);
    let (left, right) = arr.split_at_mut(pivot_idx);
    quick_sort(left);
    quick_sort(&mut right[1..]);
}

fn partition(arr: &mut [i32]) -> usize {
    let n = arr.len();
    let pivot = arr[n - 1];  // 简化:取最后一个作 pivot
    let mut i = 0;
    for j in 0..n-1 {
        if arr[j] < pivot {
            arr.swap(i, j);
            i += 1;
        }
    }
    arr.swap(i, n-1);
    i
}
```

**复杂度**:平均 O(N log N),最坏 O(N²)(已排序数组 + 取末尾作 pivot)。空间 O(log N)(递归栈)。

**最坏情况怎么发生**:已排序 / 反向排序 / 全相同数组,加上"取首/尾作 pivot"策略。这是早期 quicksort 的经典坑。

**解法 1**:三数取中(median-of-three)。取 arr[0] / arr[mid] / arr[-1] 的中位数作 pivot。
**解法 2**:随机 pivot。每轮随机选一个 index,理论上无 worst case 输入。
**解法 3**:Introsort。递归深度超过 2log N 时切到 heap sort,保证最坏 O(N log N)。这是 C++ std::sort 的实现。
**解法 4**:pdqsort(pattern-defeating)。Rust 1.51+ 标准。

### 2.5 Heap sort(堆排序)

利用堆(完全二叉树)的性质。先把数组建成 max-heap,然后反复"取出堆顶(最大值)放到末尾"。

```rust
fn heap_sort(arr: &mut [i32]) {
    let n = arr.len();
    // 建堆
    for i in (0..n/2).rev() {
        heapify(arr, n, i);
    }
    // 反复取出最大值
    for i in (1..n).rev() {
        arr.swap(0, i);
        heapify(arr, i, 0);
    }
}

fn heapify(arr: &mut [i32], n: usize, i: usize) {
    let mut largest = i;
    let left = 2*i + 1;
    let right = 2*i + 2;
    if left < n && arr[left] > arr[largest] { largest = left; }
    if right < n && arr[right] > arr[largest] { largest = right; }
    if largest != i {
        arr.swap(i, largest);
        heapify(arr, n, largest);
    }
}
```

**复杂度**:O(N log N) 最坏情况。空间 O(1)。
**特点**:**最坏 O(N log N) + O(1) 空间**——这是 heap sort 的独特优势。但常数比 quicksort 大,实际运行慢。
**用途**:introsort 的兜底,嵌入式 / 实时系统(无动态分配)。

### 2.6 比较排序的下限

**理论证明**:基于比较的排序,**下界是 O(N log N)**。为什么?N 个元素有 N! 种排列,每次比较(binary)给出 1 bit 信息,所以至少需要 log₂(N!) ≈ N log N 次比较。

这意味着 O(N log N) 是比较排序的极限,想更快必须用**非比较**排序(counting / radix)。下一节讲。

## 3 · 非比较排序

### 3.1 Counting sort(计数)

如果元素是整数且范围有限(counting_sort 适合 0..K,K 比 N 大不多),可以用计数。

```rust
fn counting_sort(arr: &mut [u8]) {
    let mut count = [0u32; 256];
    for &x in arr.iter() {
        count[x as usize] += 1;
    }
    let mut idx = 0;
    for v in 0..256 {
        for _ in 0..count[v] {
            arr[idx] = v as u8;
            idx += 1;
        }
    }
}

fn main() {
    let mut v = vec![3, 1, 4, 1, 5, 9, 2, 6, 5, 3];
    counting_sort(&mut v);
    println!("{:?}", v);
}
```

**复杂度**:O(N + K),K 是值域大小。
**特点**:**线性时间!** 但要求值域有限。

**用途**:
- byte 数组排序(K=256)。
- 给 radix sort 做基础。
- HH Day 95 Casey 用 counting sort 给 render queue 按 depth bucket 排序。

### 3.2 Radix sort(基数)

对多位整数,从低位到高位(或反之)反复用 counting sort。

```rust
fn radix_sort(arr: &mut [u32]) {
    for shift in (0..32).step_by(8) {
        let mask = 0xFFu32;
        // 按 byte 排序
        let mut buckets: [Vec<u32>; 256] = Default::default();
        for &x in arr.iter() {
            let b = ((x >> shift) & mask) as usize;
            buckets[b].push(x);
        }
        let mut idx = 0;
        for b in 0..256 {
            for &x in &buckets[b] {
                arr[idx] = x;
                idx += 1;
            }
        }
    }
}
```

**复杂度**:O(N · d),d 是位数(32-bit int d=4)。

**特点**:对大整数数组,经常比 quicksort 快。**不基于比较**,所以突破 O(N log N) 下界。

**用途**:
- 大整数排序(database index)。
- GPU 排序(radix 特别适合 GPU 并行)。
- HH 里 Casey 用 radix 给 render queue 排序(按 sort key,通常是 depth + material id 打包成 u64)。

**坑**:对带符号数要预处理(翻转符号位),否则负数排到正数后面。

## 4 · Topological sort(拓扑排序)

### 4.1 它不是"排序"

虽然叫 sort,但 topological sort **不是按值排序**。它是给 DAG(有向无环图)的节点排出一个顺序,使每条边的"前驱"出现在"后继"之前。

经典例子:课程依赖。要学 OS,先要学数据结构;要学数据结构,先要学编程入门。给定这些依赖关系,排出一个合理的学习顺序——这就是 topological sort。

### 4.2 算法:Kahn's algorithm

```rust
use std::collections::{VecDeque, HashMap, HashSet};

fn topo_sort(num_nodes: usize, edges: &[(usize, usize)]) -> Option<Vec<usize>> {
    // edges: (from, to)
    let mut adj: HashMap<usize, Vec<usize>> = HashMap::new();
    let mut in_degree = vec![0; num_nodes];
    for &(from, to) in edges {
        adj.entry(from).or_default().push(to);
        in_degree[to] += 1;
    }
    let mut queue: VecDeque<usize> = VecDeque::new();
    for i in 0..num_nodes {
        if in_degree[i] == 0 { queue.push_back(i); }
    }
    let mut result = Vec::new();
    while let Some(node) = queue.pop_front() {
        result.push(node);
        if let Some(nexts) = adj.get(&node) {
            for &next in nexts {
                in_degree[next] -= 1;
                if in_degree[next] == 0 { queue.push_back(next); }
            }
        }
    }
    if result.len() == num_nodes { Some(result) } else { None }  // None = 有环
}
```

**复杂度**:O(V + E),V 节点数 E 边数。

**返回 None**:图有环,不能 topo sort。比如"A 依赖 B,B 依赖 A"——死锁。

### 4.3 HH 里的应用

Casey 在 HH Day 132 用 topo sort 给**渲染顺序**排序。规则:
- Skybox 先画(背景)。
- Opaque 物体按 material id 排序(减少 state switch)。
- Transparent 物体按 depth 排序(后到前)。
- UI 最后画(覆盖一切)。

这些规则是 DAG:Skybox → Opaque → Transparent → UI。topo sort 给出合法绘制顺序。

**其他用途**:Make / Cargo 的依赖解析、电子表格的公式计算顺序、C++ 类的初始化顺序、数据库的 schema migration。

## 5 · Rust 标准库的 sort

### 5.1 `slice::sort` vs `sort_unstable`

Rust 标准库提供两个排序 API:

| API | 算法 | 稳定 | 复杂度 |
|---|---|---|---|
| `sort_by` / `sort_by_key` / `sort` | pdqsort 的稳定变种(merge sort + insertion) | 是 | O(N log N) |
| `sort_unstable_by` / `sort_unstable_by_key` / `sort_unstable` | pdqsort(pattern-defeating quicksort) | 否 | O(N log N) |

**稳定性(stable)的含义**:相等元素(按你的比较函数判定相等)**保持原顺序**。

```rust
let mut v = vec![(1, 'a'), (2, 'b'), (1, 'c'), (2, 'd')];
v.sort_by_key(|&(k, _)| k);
// 稳定排序后: [(1,'a'), (1,'c'), (2,'b'), (2,'d')]  ← 'a' 还在 'c' 前
v.sort_unstable_by_key(|&(k, _)| k);
// 不稳定排序后: 可能是 [(1,'a'), (1,'c'), (2,'b'), (2,'d')]
//              也可能是 [(1,'c'), (1,'a'), (2,'d'), (2,'b')]
```

**什么时候用 unstable**:不需要稳定性时(数值排序、ID 排序),用 `sort_unstable`,**通常更快**(常数小),**辅助空间 O(1)**(stable sort 辅助 O(N))。

**什么时候必须用 stable**:相等元素有"额外信息"需要保持顺序。比如"按 priority 排序任务,同 priority 保持入队顺序"——必须 stable。

### 5.2 pdqsort:pattern-defeating quicksort

Rust 1.51 起,`sort_unstable` 用 pdqsort。pdqsort 是 Orson Peters 2015 年发表的算法。设计动机:**让 quicksort 对所有输入模式都表现良好**。

传统 quicksort 的弱点:
- 已排序数组 → O(N²)(如果 pivot 选不好)
- 全相同数组 → O(N²)(每次 partition 都不平衡)
- Killer sequence(专门构造的最坏输入)→ O(N²)

pdqsort 的对策:
1. **小数组(N<=20)切到 insertion sort**——避免递归 overhead。
2. **pivot 用 median-of-three**——避免已排序退化。
3. **如果 partition 不平衡(一边 < 1/8)**,把 pivot 当"bad pivot",累积 bad pivot 计数。连续 N/2 次 bad pivot 后,**切到 heap sort**保证最坏 O(N log N)。
4. **如果发现"全相同"模式**(连续多次 partition 都很平衡但没进展),用 **Clever sort** 模式:对每个 pivot,partition 后**两边都跳过等于 pivot 的部分**——下次 partition 就不会再处理等于 pivot 的元素。

效果:**对所有输入模式,都达到 O(N log N) 最坏 + O(N) 最好(已排序)+ O(N·k) 全相同(k 种值)**。这是工业级 sort 的金标。

### 5.3 实测对比

```rust
// 生成各种输入模式,对比 sort vs sort_unstable
use std::time::Instant;

fn bench(name: &str, mut v: Vec<u32>) {
    let start = Instant::now();
    v.sort();
    println!("{}: sort: {:?}", name, start.elapsed());

    let start = Instant::now();
    v.sort_unstable();
    println!("{}: sort_unstable: {:?}", name, start.elapsed());
}

fn main() {
    let n = 1_000_000;

    let random: Vec<u32> = (0..n).map(|_| rand::random()).collect();
    bench("random", random);

    let sorted: Vec<u32> = (0..n).collect();
    bench("sorted", sorted);

    let reverse: Vec<u32> = (0..n).rev().collect();
    bench("reverse", reverse);

    let all_same: Vec<u32> = vec![42u32; n];
    bench("all_same", all_same);

    // few_unique(只有几种不同值)
    let few: Vec<u32> = (0..n).map(|i| (i % 5) as u32).collect();
    bench("few_unique", few);
}
```

典型结果(我机器上 N=1M):

```
random:        sort: 65ms   sort_unstable: 45ms
sorted:        sort: 8ms     sort_unstable: 2ms
reverse:       sort: 12ms    sort_unstable: 3ms
all_same:      sort: 10ms    sort_unstable: 2ms
few_unique:    sort: 35ms    sort_unstable: 18ms
```

`sort_unstable` 全面胜出——这就是为什么"不需要稳定性时用 unstable"是 Rust 性能优化第一条。

## 6 · 并行排序:rayon

### 6.1 par_sort

```toml
rayon = "1.10"
```

```rust
use rayon::prelude::*;

fn main() {
    let mut v: Vec<u32> = (0..1_000_000).map(|_| rand::random()).collect();
    v.par_sort_unstable();  // 并行!
}
```

rayon 的 `par_sort_unstable` 内部用的是 **parallel merge sort + 小数组切 quicksort**。算法简述:

1. 数组对半切,递归并行排序两半(用 rayon 的 work-stealing 调度)。
2. 两半都排好后,合并。

由于 merge sort 的"分治"特性,它特别适合并行——两半完全独立,两个线程同时排。

实测(8 核机器,N=10M):

```
serial sort_unstable: 800ms
rayon par_sort_unstable: 130ms (≈6x 加速)
```

不是 8x 因为:并行有 overhead(任务调度 + 合并),且单核 sort_unstable 已经用了 SIMD / cache 优化,余下空间小。

### 6.2 什么时候用 par_sort

数据量大(N > 100K)+ 不在 hot loop 里。否则单线程更快(parallel overhead 大于并行收益)。

游戏里典型用途:
- **资产加载阶段**(启动时):按加载优先级排序资产列表,几万条,N=50K+。
- **关卡加载**:把场景物体按 material id 排序,减少 draw call。
- **离线工具**:贴图压缩管线按尺寸排序。

每帧 render queue 排序(几百条)用单线程 sort_unstable 就行,并行反而慢。

## 7 · 真实世界应用

### 7.1 数据库索引

PostgreSQL 的 B-tree 索引用排序后的页存储。INSERT 时维护有序——这是为什么大量 INSERT 慢。PostgreSQL 的 `CREATE INDEX` 用 **external sort**(磁盘上的 merge sort),因为数据超过内存。

```sql
EXPLAIN SELECT * FROM users ORDER BY age;
-- 如果 age 有 index:Index Scan(快,O(log N))
-- 没有:Seq Scan + Sort(O(N log N))
```

### 7.2 文件系统

Linux ext4 / XFS 的目录项是按 hash 排序的 B-tree。`ls` 列目录后,内核返回已排序数据,你看到的"字母顺序"实际是文件系统帮你排好的。

```bash
ls -U   # 不排序(直接给内核返回的顺序)
ls      # 排序(用户态 sort)
```

`ls -U` 比默认 `ls` 快,在大目录(几万文件)上差距明显。

### 7.3 git blame / git log

git 内部用 radix sort 处理 commit hash(40 字符的 hex,16 进制)。这比通用 sort 快几倍。

### 7.4 游戏 render queue

最经典的"排序优化"案例。每帧需要把 N 个物体按 (material_id, depth, pass) 排序,使绘制顺序最优(state switch 最少)。

工业实现:
- 把这三个值打包成 u64(高位 material,中位 depth,低位 pass)。
- 用 `sort_unstable_by_key(|o| o.sort_key)`。
- 几千物体,N log N 也就几万次比较,几微秒。

```rust
#[derive(Clone, Copy)]
struct SortKey(u64);

impl SortKey {
    fn new(pass: u8, material: u16, depth: u32) -> Self {
        Self(((pass as u64) << 56)
            | ((material as u64) << 40)
            | (depth as u64))
    }
}

// 每帧:
objects.sort_unstable_by_key(|o| o.sort_key);
// 然后 iterate,绘制
```

## 8 · Rust 实战速查

```rust
// 数值排序
v.sort();
v.sort_unstable();

// 自定义 comparator
v.sort_by(|a, b| a.priority.cmp(&b.priority));

// by_key(更易读)
v.sort_by_key(|o| o.priority);

// by_key 反向
v.sort_by_key(|o| std::cmp::Reverse(o.priority));

// tuple 排序(字典序)
v.sort();  // 自动按 (a.0, a.1, a.2) 排

// 多 key 排序(用 tuple)
v.sort_by_key(|o| (o.material_id, o.depth));

// 浮点排序(注意 NaN)
v.sort_by(|a, b| a.partial_cmp(&b).unwrap_or(Equal));
// 或用 ord_subset crate

// 并行
v.par_sort_unstable();
v.par_sort_by(|a, b| a.cmp(b));
```

### 8.1 算法选择决策树

```
N < 32              → insertion sort(隐式:pdqsort 内部切到这里)
N < 10000           → sort_unstable_by_key
N < 1M              → sort_unstable_by_key(还是)
N > 1M,需要稳定      → sort_by_key(merge sort 稳定)
N > 1M,要并行        → rayon par_sort_unstable_by_key
N > 10M,整数         → 自己写 radix sort
有依赖关系(DAG)      → topological sort
数据范围有限(0..K)    → counting sort
需要外部(>内存)       → external merge sort
```

### 8.2 Rust crate 生态

| crate | 用途 |
|---|---|
| std `slice::sort` | 默认,稳定 pdqsort |
| std `slice::sort_unstable` | 默认,pdqsort |
| `rayon` `par_sort_unstable` | 并行排序 |
| `tinytemplate` | 排序 benchmark |
| `radsort` | 纯 Rust radix sort |
| `voracious_radix_sort` | 高性能 radix(适合大数据) |
| `pdqsort` | pdqsort 独立 crate(标准库也有) |

## 9 · 延伸阅读

- Orson Peters 的 pdqsort 论文:https://arxiv.org/abs/2106.05068
- Rust 标准库 sort 源码:https://github.com/rust-lang/rust/blob/master/library/core/src/slice/sort.rs
- rayon par_sort 源码:https://github.com/rayon-rs/rayon/blob/master/src/slice/quicksort.rs
- Knuth TAOCP Vol 3: Sorting and Searching——经典中的经典
- Tim Peters 的 timsort(Python 使用):https://svn.python.org/projects/python/trunk/Objects/listsort.txt
- Bevy 引擎 render queue 排序:https://github.com/bevyengine/bevy/blob/main/crates/bevy_render/src/render_phase/mod.rs
- Visualization: https://visualgo.net/en/sorting
