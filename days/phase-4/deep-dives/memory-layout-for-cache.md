
# Memory Layout for Cache

> 现代 CPU 性能瓶颈不是计算,是**内存**。Cache miss 代价 ~100 ns,ALU 运算 ~1 ns——差 100 倍。Phase 4 多处提到 cache(SIMD 数据布局、粒子系统 SoA、分桶锁 false sharing)。这篇 deep-dive 系统讲 cache-aware 编程。

## 0 /// Cache 是什么

CPU cache 在 CPU 和主存(RAM)之间,SRAM 制造,极快但小:

| 层 | 大小 | 延迟 |
|---|---|---|
| Register | 几十字节 | 0 cycle |
| L1 cache | 32-64 KB / 核 | ~1 ns (4 cycle) |
| L2 cache | 256 KB - 1 MB / 核 | ~4 ns (12 cycle) |
| L3 cache | 8-32 MB 共享 | ~12 ns (40 cycle) |
| 主存 RAM | GB | ~100 ns (300 cycle) |

每读一个字节,**先查 L1**,miss 查 L2,再 miss 查 L3,再 miss 查 RAM。RAM 慢 100 倍。

## 1 /// Cache Line

cache 不是字节粒度,是 **cache line**(64 字节)。一次 RAM 读读整 line,放到 cache。

```
读 byte 0x1000:
- 内核读 0x1000 - 0x103F(64 字节)到 L1
- byte 0x1000 给 CPU
- byte 0x1001-0x103F 也在 cache,后续读几乎免费
```

**Cache locality**:访问相邻字节几乎免费。

## 2 /// Spatial vs Temporal Locality

- **Spatial locality**:访问内存后,大概率访问附近内存(数组遍历)
- **Temporal locality**:访问内存后,大概率再访问(循环变量)

cache 设计就是利用这两个 locality。

## 3 /// AoS vs SoA

### AoS(Array of Structs)

```rust
struct Particle {
    x: f32, y: f32, vx: f32, vy: f32,
    color: u32, life: f32,
}
let particles: Vec<Particle> = ...;

// 更新位置
for p in &mut particles {
    p.x += p.vx * dt;
    p.y += p.vy * dt;
}
```

每 `Particle` 24 字节,内存布局:

```
[x, y, vx, vy, color, life, x, y, vx, vy, color, life, ...]
```

遍历时:cache 读 64 字节 = 2.6 个 particle(64/24)。**每读 1 particle 浪费 ~24%**(只用了 x/y/vx/vy)。

### SoA(Struct of Arrays)

```rust
struct Particles {
    xs: Vec<f32>,
    ys: Vec<f32>,
    vxs: Vec<f32>,
    vys: Vec<f32>,
    colors: Vec<u32>,
    lives: Vec<f32>,
}
let particles: Particles = ...;

// 更新位置
for i in 0..n {
    particles.xs[i] += particles.vxs[i] * dt;
    particles.ys[i] += particles.vys[i] * dt;
}
```

内存布局:

```
[x, x, x, x, x, x, ...][y, y, y, y, y, ...][vx, vx, vx, ...]
```

遍历 xs 时:cache 读 64 字节 = 16 个 x(f32 4 字节)。**100% 利用**。

### 性能对比

10 万粒子 update 实测:

| 布局 | 时间 |
|---|---|
| AoS | 4.2 ms |
| SoA | 1.5 ms(2.8x) |
| SoA + SIMD | 0.5 ms(8.4x) |

SoA + SIMD 是工业标准。

### AoSoA(Array of Struct of Arrays)

混合:每 batch 是 SoA(8 个一组),array of batches。

```rust
#[repr(C)]
struct ParticleBatch {
    xs: [f32; 8],
    ys: [f32; 8],
    vxs: [f32; 8],
    vys: [f32; 8],
    // ...
}
let particles: Vec<ParticleBatch> = ...;
```

平衡:cache 友好 + SIMD 友好 + 单粒子访问仍可行。

`bevy_ecs`、Unreal Mass Entity 用 AoSoA。

## 4 /// False Sharing

多线程下,两个变量**在同一 cache line**,即使不相关,也会"共享":

```rust
struct Counters {
    counter_a: AtomicU64,  // 线程 1 写
    counter_b: AtomicU64,  // 线程 2 写
}
```

线程 1 写 counter_a → cache line 在 L1 of core 1。
线程 2 写 counter_b → cache line 在 L1 of core 2。
两个 core **互相 invalidate**(MESI 协议),cache 反复 miss。

虽然两个变量逻辑独立,但**物理共享 cache line**——叫 **false sharing**。

### 解决:CachePadded

```rust
use crossbeam::utils::CachePadded;

struct Counters {
    counter_a: CachePadded<AtomicU64>,
    counter_b: CachePadded<AtomicU64>,
}
```

`CachePadded<T>` 在 T 后加 padding 到 64 字节边界,确保不同变量不在同 line。

### 检测 false sharing

```bash
sudo perf stat -e cache-misses ./target/release/your_program
# cache-misses 高且性能差 → 可能 false sharing
```

## 5 /// Prefetching

CPU 自动 prefetch:发现"线性访问"模式,提前读下个 cache line。

```rust
// 自动 prefetch(顺序)
for i in 0..n {
    sum += arr[i];
}

// 无 prefetch(随机)
for i in random_order {
    sum += arr[i];
}
```

顺序访问 10 倍快于随机。

### 手动 prefetch

`_mm_prefetch` intrinsic 手动 prefetch:

```rust
#[cfg(target_arch = "x86_64")]
unsafe fn prefetch(addr: *const u8) {
    std::arch::x86_64::_mm_prefetch(addr as *const i8, std::arch::x86_64::_MM_HINT_T0);
}
```

但**编译器通常更懂**。手动 prefetch 是高阶优化。

## 6 /// Cache-Aware 数据结构

### 数组 / Vec

最 cache-friendly。连续内存,顺序访问几乎免费。

### LinkedList

最 cache-unfriendly。每节点单独 alloc,跳着读。

### HashMap

混合。bucket 数组连续,但 key/value 可能跳。

### B-Tree

cache-friendly 的 search tree。每 node 多 key,减少高度。

### Trie

cache-unfriendly。每字符跳一个 node。优化:**burst trie** / **crit-bit tree**。

## 7 /// 实战:cache-friendly 算法

### 矩阵乘法

```rust
// Naive:每内积都跳 k
for i in 0..n { for j in 0..n {
    let mut s = 0;
    for k in 0..n { s += a[i][k] * b[k][j]; }
    c[i][j] = s;
}}

// Tiled:block 后 a 和 b 都在小块内,cache 命中
const BLOCK: usize = 64;
for ii in (0..n).step_by(BLOCK) {
    for jj in (0..n).step_by(BLOCK) {
        for kk in (0..n).step_by(BLOCK) {
            // 在 ii..ii+BLOCK, jj..jj+BLOCK, kk..kk+BLOCK 内算
            // a 和 b 子矩阵适合 cache
        }
    }
}
```

Tiled 10 倍快。

### Bitmap / Image processing

```rust
// 每像素处理 4 字节 RGB,顺序遍历 cache-friendly
for y in 0..h {
    for x in 0..w {
        // 处理 pixel
    }
}
```

### Entity iteration

```rust
// ECS:遍历所有有 Position + Velocity 的 entity
for (pos, vel) in positions.iter_mut().zip(velocities.iter()) {
    pos.x += vel.x * dt;
}
// positions 和 velocities 都是连续 Vec,SIMD + cache-friendly
```

这是 bevy_ecs 快的核心。

## 8 /// Cache-Oblivious Algorithms

不依赖 cache size 的算法设计。理论上 cache-aware 和 cache-oblivious 都达到最优 cache 复杂度。

例:matrix tiling cache-oblivious 版本递归分块:

```rust
fn matmul_co(a: &[f32], b: &[f32], c: &mut [f32], n: usize) {
    if n <= BASE {
        // base case:小矩阵直接算
    } else {
        let h = n / 2;
        // 递归 4 个子矩阵
        matmul_co(...);
        // ...
    }
}
```

递归分块自动适应 cache size(L1 / L2 / L3)。

## 9 /// 工具

- **`perf stat -e cache-misses`**:Linux cache miss 统计
- **`valgrind --tool=cachegrind`**:详细 cache 模拟
- **`perf c2c`**:false sharing 检测(高级)

```bash
sudo perf stat -e cache-misses,cache-references ./target/release/game
# 输出 cache 命中率
```

## 10 /// 资源

- Ulrich Drepper "What Every Programmer Should Know About Memory":https://people.freebsd.org/~lstewart/articles/cpumemory.pdf
- Chandler Carruth "Efficiency with Algorithms, Performance with Data Structures"(CppCon)
- Scott Meyers "CPU Caches and Why You Care"
- bevy_ecs 存储:https://bevyengine.org/news/bevy-0-8/

## 11 /// 练习

### Lv1

写两个版本求和:Vec<f32>(连续)vs LinkedList<f32>。1000 万元素,对比时间。

### Lv2

把 ParticleSystem 从 AoS 改 SoA。benchmark 加速。

### Lv3

实现 tiled matrix multiplication。对比 naive 版本。

### Lv4

用 perf stat 分析你的 Phase 4 项目,找最大 cache miss 源。优化一处。
