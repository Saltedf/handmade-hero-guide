---
title: "SIMD 演化论:从标量到 AVX-512"
type: deep-dive
phase: 3
domains: [rust, linux, game, graphics]
prereqs: ["phase-0/14-math-foundations", "phase-3/day081"]
---

# SIMD 演化论:从标量到 AVX-512

> 在 Phase 3 的某一天你会看到 Casey 突然在代码里写 `_mm_add_ps(a, b)`,然后兴奋地说"四倍快!"。这一篇是给你的预习——为什么 SIMD 这么猛,什么时候用,什么时候反而会更慢。我们用 tsoding 风格直接上代码,从标量版本一步步演化到 SIMD 版本,中间该踩的坑一个都不少。

## 0 · 为什么要有这一篇

你写过两数相加:

```rust
fn add(a: f32, b: f32) -> f32 { a + b }
```

CPU 算这个要 1 个 cycle(其实更少,因为浮点单元流水化)。看起来挺快。但你游戏里经常有"10000 个粒子,每帧位置更新一次"的需求——10 万次 f32 加法,如果每次都 1 cycle,**总开销就是 10 万 cycle**。

能不能"一次算多个"?

答案就是 **SIMD**(Single Instruction, Multiple Data):一条指令同时处理多个数据。一条 `_mm_add_ps` 一次算 **4 个 f32 加法**,仍然只要 1 cycle。10000 个粒子变成 2500 条指令,**理论上 4 倍加速**。

但**理论不等于实际**。SIMD 有它的脾气——数据要对齐、gather/scatter 极慢、CPU 间版本不同指令不同、auto-vectorization 不可靠……这一篇就把这些坑一次性踩完。

HH 在 Day 117 开始接触 SIMD(Packing Pixels for the Framebuffer),Day 337 用在音频混音器,Day 431 用在光线投射,Day 550 用在光照采样。**每次都是同一个套路**——拿一个标量循环,改写成 SIMD。学会这一篇,以后 4 次出现你都能 30 秒看懂。

学完后,你应该能:
- 解释 SIMD 为什么快(指令并行 vs 数据并行)
- 写出 SSE / AVX / NEON 的基本 intrinsics
- 看懂 `cargo asm` 输出,判断编译器有没有自动向量化
- 知道什么时候**不该用 SIMD**(可读性 / 可移植性 / 边界处理成本)
- 在 Rust 项目里用 `std::arch::x86_64` 写出 zero-cost 抽象

## 1 · 心智模型:从标量到 SIMD 的"思维切换"

### 1.1 标量思维:一个萝卜一个坑

标量代码:`for sum += x[i]`。每次循环算一个数。直觉是"一次一件事"。

```rust
fn sum_scalar(xs: &[f32]) -> f32 {
    let mut s = 0.0;
    for &x in xs { s += x; }
    s
}
```

CPU 内部其实也很"标量地"做:取一个 x[i],加到 s,推进 i。即使有流水线,本质是**串行**。

### 1.2 SIMD 思维:一筐萝卜一起处理

SIMD 把数据组织成**向量**(vector)——一个寄存器里塞多个数。128 位寄存器塞 4 个 f32,256 位塞 8 个,512 位塞 16 个。一条指令对**整个向量**做同一操作。

```rust
// SSE: 4 个 f32 同时加
use std::arch::x86_64::*;
unsafe {
    let a = _mm_set_ps(1.0, 2.0, 3.0, 4.0);  // [4, 3, 2, 1] (倒序!)
    let b = _mm_set_ps(10.0, 20.0, 30.0, 40.0);
    let c = _mm_add_ps(a, b);                 // [14, 23, 32, 41]
    // c 是 __m128 类型,内部 4 个 f32 同时被加上对应位置的 b
}
```

一条 `_mm_add_ps` 在硬件层是 `addps` 指令(注意结尾的 `s` = packed single precision)。CPU 的向量单元(ALU 阵列)同时算 4 个加法。延迟和一次标量加法**几乎一样**(1-3 cycle,看 CPU 代际)。

### 1.3 类比:超市结账

标量 = 一个收银台,一个顾客一扫一装。
SIMD = 一个收银员同时扫 4 个顾客的同一商品(都是 1 瓶可乐)。

但前提是"4 个顾客都买 1 瓶可乐"。如果有一个买的是啤酒,SIMD 就不好处理——你得**gather**(把啤酒从某处抓过来)或**mask**(跳过啤酒顾客)。**SIMD 最怕的不是计算,是数据组织**。

### 1.4 SIMD 的硬件基础:寄存器宽度演化

```
1999  MMX     64-bit   (8 × u8 / 4 × u16 / 2 × u32)  — 整数,已淘汰
1999  SSE     128-bit  (4 × f32 / 4 × u32)            — 浮点开始
2001  SSE2    128-bit  (2 × f64 / 16 × u8)            — f64 支持
2004  SSE3    128-bit  (horizontal add/sub)
2006  SSSE3   128-bit  (shuffle / byte ops)
2007  SSE4.1/4.2  128-bit  (dot product, blend, CRC32)
2011  AVX     256-bit  (8 × f32 / 4 × f64)            — 大跃进
2013  AVX2    256-bit  (integer AVX 支持)             — gather 慢
2017  AVX-512 512-bit  (16 × f32)                     — 服务器,争议
2011  ARM NEON 128-bit (类似 SSE)
2020  ARM SVE  可变长度
```

注意:**AVX-512 不是免费的**。Skylake-X 上跑 AVX-512 会让 CPU 降频(license-based frequency),实际收益要测。AMD Zen4 才正式支持。**AVX2 是当前主流 baseline**。

游戏开发圈的态度:
- **SSE2 baseline**:所有 x86-64 都支持(AMD64 spec 强制)
- **AVX2 优先**:2013+ CPU 支持,游戏圈默认
- **AVX-512 跳过**:太多坑,除非数值计算 / AI

## 2 · Rust 的 SIMD 三种姿势

### 2.1 姿势一:std::arch::x86_64 intrinsics(直接调硬件)

```rust
use std::arch::x86_64::*;

#[target_feature(enable = "avx2")]
#[cfg(target_arch = "x86_64")]
unsafe fn sum_avx2(xs: &[f32]) -> f32 {
    assert!(xs.len() % 8 == 0);  // AVX2: 8 f32 per register
    
    let mut acc = _mm256_setzero_ps();  // 256-bit zero
    for chunk in xs.chunks_exact(8) {
        let v = _mm256_loadu_ps(chunk.as_ptr());  // unaligned load
        acc = _mm256_add_ps(acc, v);
    }
    
    // horizontal sum: 把 8 个 lane 求和
    let mut buf = [0f32; 8];
    _mm256_storeu_ps(buf.as_mut_ptr(), acc);
    buf.iter().sum()
}

pub fn sum(xs: &[f32]) -> f32 {
    #[cfg(target_arch = "x86_64")]
    if is_x86_feature_detected!("avx2") {
        return unsafe { sum_avx2(xs) };
    }
    // fallback
    sum_scalar(xs)
}
```

每行注释:
- `#[target_feature(enable = "avx2")]` — 告诉 rustc 这个函数编译时用 AVX2 指令,**不能在没有 AVX2 的 CPU 上跑**(否则 SIGILL)。
- `_mm256_setzero_ps()` — 创建全零的 256-bit 向量(8 个 f32)。
- `_mm256_loadu_ps(p)` — 从指针 p 加载 8 个 f32(unaligned,不要求对齐)。
- `_mm256_add_ps(a, b)` — 8 lane 同时加。
- `chunks_exact(8)` — 切成 8 元素的块,丢弃尾部不完整块。
- `is_x86_feature_detected!("avx2")` — runtime 检测 CPU 是否支持 AVX2。

**关键陷阱**:runtime check + unsafe 是**必须**的。如果直接调 `_mm256_*` 函数,在老 CPU(2013 前)上会 SIGILL 崩溃。

### 2.2 姿势二:portable-simd(nightly 的未来)

```rust
#![feature(portable_simd)]
use std::simd::f32x8;

fn sum_portable(xs: &[f32]) -> f32 {
    let chunks = xs.chunks_exact(8);
    let remainder = chunks.remainder();
    
    let mut acc = f32x8::splat(0.0);
    for chunk in chunks {
        let v = f32x8::from_slice(chunk);
        acc += v;
    }
    
    acc.reduce_sum() + remainder.iter().sum::<f32>()
}
```

每行:
- `#![feature(portable_simd)]` — 启用 nightly feature。
- `f32x8` — 8 lane f32,但**编译器自动选 SSE/AVX/NEON**。
- `from_slice` / `reduce_sum` — 高级 API,不用 unsafe。
- 没有运行时 dispatch——编译器一次选好最优指令。

**优点**:可移植、无 unsafe、API 干净。**缺点**:还在 nightly,API 可能改。

### 2.3 姿势三:wide crate(stable 的中间方案)

```rust
use wide::f32x4;

fn sum_wide(xs: &[f32]) -> f32 {
    let mut acc = f32x4::splat(0.0);
    for chunk in xs.chunks_exact(4) {
        let v = f32x4::from_slice(chunk);
        acc += v;
    }
    // ... 实际求和需要额外 horizontal reduction
}
```

`wide` 提供 stable API,SSE2/NEON 自动切换。比 std intrinsics 易用,比 portable-simd 稳定。**生产代码推荐这个**。

### 2.4 三种姿势对比

| 方案 | 稳定性 | 性能 | 可移植 | unsafe |
|---|---|---|---|---|
| std::arch intrinsics | stable | 最高 | 需手动 dispatch | 必须 |
| wide crate | stable | 高(略低于 intrinsics) | 自动 | 不需要 |
| portable-simd | nightly | 最高 | 自动 | 不需要 |

**新手推荐**:wide crate。**性能极致**:std intrinsics + runtime dispatch。**未来**:portable-simd。

## 3 · 实战:从标量到 SIMD 的演化(粒子更新)

### 3.1 标量版

```rust
struct Particle { x: f32, y: f32, vx: f32, vy: f32 }

fn update_scalar(particles: &mut [Particle], dt: f32) {
    for p in particles.iter_mut() {
        p.x += p.vx * dt;
        p.y += p.vy * dt;
    }
}
```

10 万粒子 = 40 万次 f32 op。@ 3GHz = 0.13ms。看起来不慢。

但每帧 16ms 预算(60 FPS),你已经有渲染、AI、物理各占几 ms。0.13ms 也不该浪费。

### 3.2 SoA 重构(为 SIMD 铺路)

SIMD 要求数据**连续 + 同类型**。当前 Particle 是 **AoS**(Array of Structs):

```
[x0, y0, vx0, vy0, x1, y1, vx1, vy1, ...]
```

要算 4 个粒子的 x 坐标,得从 `[0], [4], [8], [12]` 取——**跨 stride 4**,不能一条 load 搞定。

改成 **SoA**(Struct of Arrays):

```rust
struct Particles {
    x: Vec<f32>,
    y: Vec<f32>,
    vx: Vec<f32>,
    vy: Vec<f32>,
}

fn update_soa(p: &mut Particles, dt: f32) {
    for i in 0..p.x.len() {
        p.x[i] += p.vx[i] * dt;
        p.y[i] += p.vy[i] * dt;
    }
}
```

现在 `p.x` 是连续 f32,SIMD 可以一条指令加载 4/8/16 个。

### 3.3 SSE 版本(4 lane)

```rust
use std::arch::x86_64::*;

#[target_feature(enable = "sse2")]
unsafe fn update_sse(p: &mut Particles, dt: f32) {
    let dt_v = _mm_set1_ps(dt);  // [dt, dt, dt, dt]
    
    let chunks_x = p.x.chunks_exact_mut(4);
    let chunks_y = p.y.chunks_exact_mut(4);
    let chunks_vx = p.vx.chunks_exact(4);
    let chunks_vy = p.vy.chunks_exact(4);
    
    for ((xc, (yc, (vxc, vyc)))) in chunks_x.zip(chunks_y).zip(chunks_vx).zip(chunks_vy) {
        let x = _mm_loadu_ps(xc.as_ptr());
        let y = _mm_loadu_ps(yc.as_ptr());
        let vx = _mm_loadu_ps(vxc.as_ptr());
        let vy = _mm_loadu_ps(vyc.as_ptr());
        
        let new_x = _mm_add_ps(x, _mm_mul_ps(vx, dt_v));
        let new_y = _mm_add_ps(y, _mm_mul_ps(vy, dt_v));
        
        _mm_storeu_ps(xc.as_mut_ptr(), new_x);
        _mm_storeu_ps(yc.as_mut_ptr(), new_y);
    }
    
    // tail(非 4 倍数部分)用标量
    let tail_start = (p.x.len() / 4) * 4;
    for i in tail_start..p.x.len() {
        p.x[i] += p.vx[i] * dt;
        p.y[i] += p.vy[i] * dt;
    }
}
```

每步:
- `_mm_set1_ps(dt)` — 把 dt 复制到 4 个 lane:`[dt, dt, dt, dt]`。
- `_mm_loadu_ps` — unaligned load,从 f32 指针取 4 个。
- `_mm_mul_ps(vx, dt_v)` — 4 lane 乘法。
- `_mm_add_ps` — 4 lane 加法。
- `_mm_storeu_ps` — 写回 4 个 f32。
- `chunks_exact_mut` + `zip` — 4 个数组同步迭代。

**4 倍加速**理论。实测大概 3.5x(tail 处理 + memory latency)。

### 3.4 AVX2 版本(8 lane)

把所有 `_mm_*` 换成 `_mm256_*`,chunk size 从 4 改成 8:

```rust
#[target_feature(enable = "avx2")]
unsafe fn update_avx2(p: &mut Particles, dt: f32) {
    let dt_v = _mm256_set1_ps(dt);
    
    let it = p.x.chunks_exact_mut(8)
        .zip(p.y.chunks_exact_mut(8))
        .zip(p.vx.chunks_exact(8))
        .zip(p.vy.chunks_exact(8));
    
    for ((xc, (yc, (vxc, vyc)))) in it {
        let x = _mm256_loadu_ps(xc.as_ptr());
        let y = _mm256_loadu_ps(yc.as_ptr());
        let vx = _mm256_loadu_ps(vxc.as_ptr());
        let vy = _mm256_loadu_ps(vyc.as_ptr());
        
        let new_x = _mm256_add_ps(x, _mm256_mul_ps(vx, dt_v));
        let new_y = _mm256_add_ps(y, _mm256_mul_ps(vy, dt_v));
        
        _mm256_storeu_ps(xc.as_mut_ptr(), new_x);
        _mm256_storeu_ps(yc.as_mut_ptr(), new_y);
    }
}
```

**理论 8 倍**,实测约 6-7 倍。

### 3.5 性能测量

```bash
# 装 criterion
cargo add criterion --dev

# benches/particles.rs
use criterion::{criterion_group, criterion_main, Criterion};

fn bench(c: &mut Criterion) {
    let mut p = Particles::new(100_000);
    c.bench_function("scalar", |b| b.iter(|| update_scalar(&mut p, 0.016)));
    c.bench_function("sse2",  |b| b.iter(|| unsafe { update_sse(&mut p, 0.016) }));
    c.bench_function("avx2",  |b| b.iter(|| unsafe { update_avx2(&mut p, 0.016) }));
}

criterion_group!(benches, bench);
criterion_main!(benches);
```

```bash
cargo bench
# 预期输出:
# scalar  time:   [320.00 µs]
# sse2    time:   [95.00 µs]   ← 3.4x
# avx2    time:   [52.00 µs]   ← 6.2x
```

## 4 · SIMD 的坑(实战经验)

### 4.1 坑一:数据对齐

`_mm_load_ps`(aligned)比 `_mm_loadu_ps`(unaligned)快一点点(legacy 原因)。但要求 16 字节对齐。Rust 的 `Vec<f32>` 不保证 16 字节对齐。

```rust
#[repr(align(16))]
struct AlignedF32x4([f32; 4]);

// 或者用 aligned-vec crate
```

**实战**:Modern CPU(Haswell+)对 unaligned 几乎没惩罚。**别为对齐疯狂**——除非 profiling 显示瓶颈。

### 4.2 坑二:tail 处理

`chunks_exact(8)` 跳过尾部不足 8 的部分。你得用标量补完:

```rust
// SIMD 处理 chunks_exact
// 标量补 tail
for i in tail_start..len { ... }
```

或者用 `chunks(8)` + 处理最后一块 padding(填零,结果正确,但有 mask 开销)。

### 4.3 坑三:horizontal sum 慢

`_mm256_add_ps` 累加后,8 个 lane 还得 sum 成一个标量。这个过程叫 **horizontal reduction**:

```rust
let buf = [0f32; 8];
_mm256_storeu_ps(buf.as_mut_ptr(), acc);
let sum = buf.iter().sum::<f32>();
```

每条 horizontal add(`_mm_hadd_ps`)要 2-3 cycle,8 lane 需要 3 次。**对 hot loop 是显著开销**。除非你必须输出标量(如 dot product),否则让数据保持 SIMD 形式到最后。

### 4.4 坑四:gather / scatter 极慢

如果你想"从数组随机位置取 4 个值"——这是 gather:

```rust
let idx = _mm_set_epi32(3, 100, 7, 42);  // 取 indices
let v = _mm_i32gather_ps(array.as_ptr(), idx, 4);  // gather
```

但 gather **慢得离谱**——Skylake 上 12 cycle,AVX-512 上 5-12 cycle。**通常 gather 比标量还慢**。

**SIMD 的根本约束**:数据必须**连续访问**才有意义。如果你的算法本质是 random access,别用 SIMD——重构算法(如 sort by index 让访问变连续)。

### 4.5 坑五:auto-vectorization 不可靠

```rust
fn sum_auto(xs: &[f32]) -> f32 {
    xs.iter().sum()
}
```

`cargo build --release` 编译时,rustc/LLVM 可能自动向量化。但你不能保证。看汇编:

```bash
cargo rustc --release -- --emit asm -C target-cpu=native -
# 搜 addps / vaddps / vmovups
```

如果看到标量 `addss`,说明没向量化。LLVM 的 auto-vec 受:
- 循环结构(简单 for loop 更易)
- 数据布局(连续更易)
- aliasing(引用是否唯一)
- target-cpu(default x86-64 是 SSE2,不会用 AVX2)

**生产建议**:不要依赖 auto-vec。写显式 SIMD。

## 5 · 验证:汇编层看 SIMD

```bash
# 装编译器 explorer
cargo install cargo-asm

# 看你的函数汇编
cargo asm --release --rust update_avx2

# 或者直接 rustc
echo 'fn f(x: &[f32]) -> f32 { x.iter().sum() }' > /tmp/x.rs
rustc -O --emit asm --edition 2021 /tmp/x.rs -o /tmp/x.s
grep -E "addps|addss|vaddps" /tmp/x.s
```

如果你看到 `vaddps`(AVX)或 `addps`(SSE),说明向量化了。如果是 `addss`,没有。

**tsoding 风**:每次写 SIMD,先看汇编,再 benchmark。**别猜,测**。

## 6 · 跨域联结

### 6.1 GPU 是终极 SIMD

GPU = 大规模 SIMD + 高带宽内存。RTX 4090 同时 16384 个 lane。SIMD 是 GPU 编程的基础——shader 里 `vec4` 操作就是 SIMT(Single Instruction Multiple Thread)。

### 6.2 数据库的 vectorized execution

Postgres / DuckDB 用 SIMD 加速 scan / aggregate。一条 SQL `SELECT SUM(price) FROM orders` 在 DuckDB 里用 AVX2 一次算 8 行。

### 6.3 AI 推理:tensor cores

NVIDIA tensor cores 在 AVX-512 基础上做矩阵乘法(A × B + C)单指令。GPT 推理的硬件加速核心。

### 6.4 音频 / 图像处理

混音器 / 卷积滤波 / FFT——所有数字信号处理都是 SIMD 天然受益者。

## 7 · 认知地图

### 7.1 上级
- **ILP**(Instruction-Level Parallelism)— 标量级别的并行
- **DLP**(Data-Level Parallelism)— SIMD 的本质
- **TLP**(Thread-Level Parallelism)— 多线程
- **SIMT**(Single Instruction Multiple Thread)— GPU 模型

### 7.2 同级

| 方案 | 何时用 |
|---|---|
| SIMD(本篇) | 大批量同质数据计算 |
| 多线程 | 任务可独立分配 |
| GPU | 超大批量 + 内存带宽需求 |
| FPGA | 自定义数据通路 |
| DSP | 专用信号处理芯片 |

### 7.3 下级
- SSE/AVX/NEON 寄存器
- intrinsics 函数(`_mm_*`, `_mm256_*`)
- `target_feature` attribute
- `is_x86_feature_detected!` macro
- `chunks_exact` 迭代
- horizontal reduction
- gather/scatter

## 8 · 对照与变奏

### 8.1 不同语言怎么写 SIMD

| 语言 | 方案 |
|---|---|
| Rust | `std::arch` / wide / portable-simd |
| C/C++ | `<immintrin.h>` intrinsics / `#pragma omp simd` |
| Go | 无显式 SIMD,编译器自动 |
| Python | numpy 底层用 SIMD,用户不直接写 |
| Zig | `@Vector` 内置类型 |
| Julia | `SIMD.jl` 包 |

C/C++ 的 intrinsics 和 Rust 几乎一样(都是 LLVM)。Zig 的 `@Vector` 最优雅,被 portable-simd 借鉴。

### 8.2 ARM NEON 对比

```c
// x86_64 SSE
__m128 a = _mm_set_ps(1,2,3,4);
__m128 b = _mm_add_ps(a, a);

// ARM NEON
float32x4_t a = {1,2,3,4};
float32x4_t b = vaddq_f32(a, a);
```

NEON 命名比 SSE 干净:`vaddq_f32` 一眼能读出"vector add quad f32"。但功能等价。

### 8.3 历史教训:Itanium / Larrabee

Itanium (2001) 尝试让编译器自动做指令级并行,**失败**——编译器太难写。Larrabee (2008) 尝试用 x86 + wide SIMD 做 GPU,**失败**——SIMD 编程模型对图形不友好。教训:**显式 + 自动** 混合是正确路径。

## 9 · 关联 Day

- **HH day117**: Packing Pixels for the Framebuffer — 第一次 SIMD
- **HH day337**: SSE Mixer Pre/Post Loops — 音频 SIMD
- **HH day431**: SIMD Raycasting — 光线投射 SIMD
- **HH day550**: SIMD Light Sampling — 光照 SIMD
- **本仓库**:
  - [phase-4/deep-dives/simd-in-rust.md](../../phase-4/deep-dives/simd-in-rust.md) — Phase 4 SIMD 基础
  - [phase-4/deep-dives/memory-layout-for-cache.md](../../phase-4/deep-dives/memory-layout-for-cache.md) — SoA vs AoS
  - [phase-5/deep-dives/audio-pipeline-complete.md](../../phase-5/deep-dives/audio-pipeline-complete.md) — SIMD 音频混音

## 10 · 变式训练

### Lv1 · 概念辨析

**题**:SIMD 的 "horizontal add"(`_mm_hadd_ps`)和普通的 vertical add(`_mm_add_ps`)有什么本质区别?为什么 horizontal add 通常更慢?

### Lv2 · 动手实践

**题**:用 SSE2 写一个 `clamp_f32(xs: &mut [f32], min: f32, max: f32)`,把所有元素限制在 [min, max]。完成标准:`cargo bench` 比 `xs.iter_mut().for_each(|x| *x = x.clamp(min, max))` 快 2x+。

### Lv3 · 迁移设计

**题**:你有一个 `Vec<u8>` 是 RGBA 像素(4 字节一组)。要把它转成 BGRA(Swap R 和 B)。用 SIMD 写。**提示**:`_mm_shuffle_epi8`(SSSE3 的字节级别 shuffle)。

### Lv4 · 开源贡献

`bevy_math` 的 `Vec3A`(16-byte aligned Vec3)是为了 SIMD 设计的。GitHub: https://github.com/bevyengine/bevy
- 读 `crates/bevy_math/src/vec3a.rs`,看它怎么用 SSE2 加速
- 找一个 unit test 没覆盖的 edge case(NaN / Infinity 处理)
- 提一个 PR 加测试

## 11 · 延伸阅读

本仓库:
- [phase-4/deep-dives/simd-in-rust.md](../../phase-4/deep-dives/simd-in-rust.md)
- [phase-5/day282.md](../../phase-6/day282.md)

外部稳定:
- Intel Intrinsics Guide(权威,搜索 _mm_*):https://www.intel.com/content/www/us/en/docs/intrinsics-guide/
- ARM NEON Intrinsics:https://developer.arm.com/architectures/instruction-sets/intrinsics/
- Rust std::arch 文档:https://doc.rust-lang.org/std/arch/index.html
- portable-simd book:https://std-dev-guide.rust-lang.org/policy/portable-simd.html
- wide crate:https://docs.rs/wide

真实源码:
- bevy_math Vec3A:https://github.com/bevyengine/bevy/tree/main/crates/bevy_math/src
- raylib 矩阵库(用 SIMD):https://github.com/raysan5/raylib
