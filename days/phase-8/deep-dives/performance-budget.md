# 深入:性能预算 / Profiling / 优化方法论

> HH 后期反复在调性能——确保 60 / 144 FPS。本文系统讲**性能工程**:怎么设预算、怎么 profile、怎么优化。这是从"能让游戏跑"到"让游戏流畅跑"的关键能力。

## 1 · 帧时间预算

60 FPS = 每帧 16.67 ms。这 16.67 ms 分给各个子系统:

| 子系统 | 典型预算 |
|---|---|
| 渲染(GPU draw + sync) | 8-10 ms |
| 物理 / 碰撞 | 2-3 ms |
| AI / Game logic | 1-2 ms |
| 音频 mixing | <0.5 ms |
| 资产 streaming | 1-2 ms(突发) |
| Debug overlay | 0.5 ms |
| **总计** | **~16 ms** |

**预算思维**:每个子系统有配额,超过要砍。"加新功能"不是"加代码",是"分配多少 ms"。

### 1.1 60 vs 144 FPS

- 60 FPS:16.67 ms / 帧
- 120 FPS:8.33 ms
- 144 FPS:6.94 ms
- 240 FPS:4.17 ms

每翻倍 FPS,预算减半。144 FPS 比 60 FPS 难 2.4 倍——不只是"代码快一点",是**重新设计**。

### 1.2 frame budget pipeline

游戏主循环:

```rust
fn frame() {
    let t_start = Instant::now();
    process_input();  // 0.1 ms
    update_simulation(); // 2 ms
    render(); // 10 ms
    present(); // 0.5 ms
    let t_end = Instant::now();
    let dt = t_end - t_start;
    if dt < Duration::from_millis(16) {
        sleep(Duration::from_millis(16) - dt);
    }
}
```

`present()` 调 `swapchain present`,可能 block 等 v-sync。这就是为什么 vsync on 时帧时间稳定 16.67 ms。

## 2 · Profiling 工具链

### 2.1 perf(Linux 标杆)

```bash
# 基础:统计事件
perf stat -e cycles,instructions,cache-misses ./game

# 录制调用图
perf record -g ./game
perf report

# Flamegraph
perf record -g ./game
perf script | stackcollapse-perf.pl | flamegraph.pl > flame.svg
```

`perf` 是 Linux 标准,采样 CPU,几乎零开销。

### 2.2 Valgrind / Callgrind

```bash
valgrind --tool=callgrind ./game
callgrind_annotate callgrind.out.*
# 或 kcachegrind GUI
```

Valgrind 模拟每条指令,精确但慢 20-50 倍。适合**详细分析**,不适合日常 benchmark。

### 2.3 Massif(内存)

```bash
valgrind --tool=massif ./game
ms_print massif.out.*
```

看堆内存随时间变化,找内存泄漏 / 峰值。

### 2.4 Hotspot

Linux 上 perf 的 GUI 前端:

```bash
sudo pacman -S hotspot
hotspot perf.data
```

可视化 flamegraph + 调用图,比命令行直观。

### 2.5 Tracy(帧级 profiler)

```bash
cargo add tracy_client
```

C++ / Rust 跨平台帧级 profiler,游戏专用:

```rust
{
    tracy_client::span!("render_pass");
    render();
}
```

GUI 看 frame timeline + 各 zone 时间。游戏开发标配。

### 2.6 RenderDoc / PIX(图形)

- **RenderDoc**:抓一帧 OpenGL / Vulkan 调用,看每个 draw call 的状态
- **PIX**:DirectX 版
- **Intel Graphics Performance Analyzer**:GPU 性能

这些是图形程序员必备。

## 3 · 优化方法论

### 3.1 Amdahl 定律

**优化最耗时的部分**。如果某段代码占总时间 50%,把它快 2 倍,总快 25%。如果某段占 1%,快 10 倍,总快 0.9%。

实践:**先 profile,找最热的 20% 代码,优化它们**。

### 3.2 测两次再优化

```rust
// 不要猜!
fn hot_function() {
    // ... 100 行代码
}

// Profile,看哪几行热
fn hot_function() {
    expensive_op_1(); // 5 ms
    cheap_op_2();     // 0.1 ms
    expensive_op_3(); // 3 ms
}
```

不要"我觉得 expensive_op_2 慢"——profile 给数据。

### 3.3 优化层次

由易到难:

1. **算法层**:O(N²) → O(N log N),最大加速
2. **数据布局**:AoS → SoA,cache 改善
3. **并行化**:单线程 → 多线程,N 倍加速
4. **SIMD**:标量 → 向量,4-8 倍加速
5. **汇编 / intrinsics**:_mm_* 优化
6. **GPU 化**:CPU → GPU,大规模并行

越靠上层,效果越大。**先做算法,再做底层**。

### 3.4 Cache 友好

现代 CPU 一级 cache 命中 ~1 cycle,miss ~100 cycles(主存)。差距 100 倍。

```rust
// Cache 不友好(每元素跳 32 字节)
struct Entity { pos: Vec3, name: String, hp: f32, ... 32 fields }
let entities: Vec<Entity> = ...;
for e in &entities { sum += e.hp; }

// Cache 友好(连续读)
struct SoA { hps: Vec<f32>, positions: Vec<Vec3>, ... }
let data: SoA = ...;
for &hp in &data.hps { sum += hp; }
```

`hp` 在 SoA 里连续,一次 cache line 64 字节 = 16 个 f32。遍历 16 个 hp 一次 miss。

AoS 每元素 64+ 字节,每 hp miss 一次。

### 3.5 Branch prediction

CPU 假设分支按"常见方向"走。Mispredict 浪费 ~20 cycles。

```rust
// 分支不可预测(随机)
for &x in &data {
    if x > threshold {
        sum += expensive(x);
    }
}

// 用 cmov 或 SIMD
let mask = data.simd_gt(threshold);
sum += mask.blend(0.0, expensive_vec(data));
```

`branchless` 编程是高级优化。

### 3.6 False sharing(多线程)

两个线程各写自己的变量,但变量在同一 cache line(64 字节),CPU 互相 invalidate,慢。

```rust
struct Counters { a: u64, b: u64 } // false sharing(同 cache line)

struct CountersFixed {
    a: u64,
    _pad1: [u64; 7], // 填充到 64 字节
    b: u64,
    _pad2: [u64; 7],
}
```

`_pad` 让 a 和 b 不在同 cache line,无 false sharing。

## 4 · 游戏性能瓶颈

### 4.1 Draw call 数

每个 draw call CPU 有 overhead(setup、state change)。10000 draw calls = CPU 瓶颈。

**优化**:

- Batch(同 material 合并)
- Instancing(同 mesh 多实例一次画)
- GPU-driven rendering(提交 indirect command,GPU 自己 cull)

### 4.2 Overdraw

多物体覆盖同一像素,G-buffer 写多次。Deferred shading 减轻但仍有。

**优化**:pre-z pass(画深度,再画物体剔除被挡的)。

### 4.3 内存带宽

GPU 写 G-buffer、读 G-buffer、写 framebuffer——大量内存。1080p G-buffer = 几十 MB / 帧。

**优化**:packed G-buffer(把 normal 压成 2 字节 octahedral encoding,见 Day 576)。

### 4.4 Shader 复杂度

fragment shader 长 = 慢。PBR shader 比 Lambert 慢 5 倍。

**优化**:

- LOD(material LOD,远处用简化 shader)
- 分辨率缩放(远距离场景用低分辨率)
- Precomputed lookup table

### 4.5 资产 streaming

大世界加载新 chunk,IO 慢导致卡顿。

**优化**:

- Async IO(io_uring on Linux)
- Background loading
- LOD streaming(远处低 LOD 先加载)

## 5 · Rust 性能技巧

### 5.1 Profile-guided optimization(PGO)

```bash
cargo build --release
# 跑 representative workload,收集 profile
./target/release/game --instrument
# 用 profile 重新编译
RUSTFLAGS="-Cprofile-use=merged.profdata" cargo build --release
```

编译器看到热路径,inline 更激进。性能 +5-10%。

### 5.2 LTO(Link-Time Optimization)

```toml
# Cargo.toml
[profile.release]
lto = "fat"  # 或 "thin"
```

跨 crate 优化,慢编译但快运行。

### 5.3 codegen-units = 1

```toml
[profile.release]
codegen-units = 1
```

单 codegen unit,优化更激进。慢编译。

### 5.4 panic = abort

```toml
[profile.release]
panic = "abort"
```

去掉 unwind 代码,二进制小,稍快。

### 5.5 内联控制

```rust
#[inline]            // 建议 inline
#[inline(always)]   // 强制 inline
#[inline(never)]    // 禁止 inline
#[cold]             // 标记"冷"函数,优化调用路径
```

滥用反而坏。**Profile 后再决定**。

### 5.6 SIMD

```rust
use std::arch::x86_64::*;

if is_x86_feature_detected!("avx2") {
    unsafe { simd_avx2(data) };
} else {
    scalar_fallback(data);
}

#[target_feature(enable = "avx2")]
unsafe fn simd_avx2(data: &[f32]) -> f32 {
    let chunks = data.chunks_exact(8);
    let sum = _mm256_setzero_ps();
    for chunk in chunks {
        let v = _mm256_loadu_ps(chunk.as_ptr());
        sum = _mm256_add_ps(sum, v);
    }
    // ... reduce
}
```

便携 SIMD(Rust 1.75+):`use std::simd::*`,跨架构自动选。

## 6 · 常见反模式

### 6.1 过早优化

"我觉得这里慢" → 写复杂 SIMD → 实际不是瓶颈 → 浪费时间。

**法则**:profile first。

### 6.2 微优化忽视算法

把 O(N²) 的 SIMD 写得极快,仍是 O(N²)。换 O(N log N) 标量更快。

### 6.3 测试用例不真实

benchmark 用 1 个物体,生产跑 1000 个——cache 表现完全不同。

**法则**:benchmark 用生产规模。

### 6.4 优化破坏可读性

把 `a + b` 改成位运算 trick,可读性丢。除非性能 critical,不要这样。

## 7 · HH 的性能工作

Casey 在 HH 里做过的性能优化:

- **Day 112+**:SIMD Vec2/Vec3
- **Day 200+**:线程池 + 任务并行
- **Day 250+**:arena allocator
- **Day 400+**:asset 压缩(BCn 纹理)
- **Day 500+**:OpenGL 迁移(CPU → GPU)
- **Day 600+**:tiled light table

每次都遵循"profile → 找热点 → 优化 → re-profile"循环。

## 8 · 给你的建议

### 8.1 学习路径

1. 学 perf 基础(2 小时)
2. 学 flamegraph(1 小时)
3. 学 RenderDoc(几小时)
4. 找一个 Rust 项目,跑 perf,看 flamegraph
5. 找最热函数,优化,benchmark

### 8.2 心态

- **数据驱动**:profile 数据 > 直觉
- **耐心**:优化是迭代,不是一次到位
- **不破坏架构**:性能优化不应该让代码不可读

### 8.3 工具配置

```bash
# Arch Linux 安装
sudo pacman -S perf valgrind hotspot
cargo install flamegraph
cargo install cargo-bench
```

## 9 · 总结

性能工程是"高级开发者"和"初级开发者"的分水岭。不是"会写更快代码",而是**理解计算机系统**(CPU / cache / memory / GPU),知道每行代码在硬件上做什么。

HH 的 Casey 是性能工程大师(他后来写"Performance-Aware Programming"系列)。看完 HH + 这篇 deep-dive,你应该:

- 会用 perf / flamegraph 找热点
- 理解 cache / SIMD / 多线程
- 知道什么时候优化什么层
- 有数据驱动的优化心态

这是开源极客的核心能力之一。

## 10 · 延伸阅读

本仓库本地:
- [phase-0/13-diagnosis-tools.md](../../phase-0/13-diagnosis-tools.md) - 诊断工具
- [phase-4/day112.md](../../phase-4/day112.md) - SIMD

外部稳定 URL:
- Performance-Aware Programming(Casey): https://www.computerenhance.com/
- Rust performance book: https://nnethercote.github.io/perf-book/
- CppCon talks on performance

真实开源源码:
- hotpath: https://github.com/anderslanglands/hotpath
- cargo flamegraph: https://github.com/flamegraph-rs/flamegraph
