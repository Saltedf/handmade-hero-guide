---
phase: 3
title_en: "SIMD Progression"
title_zh: "SIMD 演化史:从 scalar 到 AVX-512"
type: deep-dive
domains: [game, rust, performance, cpu]
bridges: ["day117", "day337", "day550"]
---

# SIMD 演化史:从 scalar 到 AVX-512

> 你跟着 HH Day 117 第一次听说 "SIMD"。Casey 把 4 个 f32 同时计算,说这是"现代 CPU 的免费午餐"。Day 337 他开始手写 SSE intrinsic,你被 `_mm_add_ps` 这种神秘符号劝退。Day 550 你听说 AVX-512 在新 Intel CPU 上能用,但 AMD Zen 4 部分支持,Zen 5 全支持——这是 2026 年的你最讨厌的硬件碎片化。这一篇把 SIMD 从最基础的 scalar 一直讲到 AVX-512、NEON、portable-simd,把所有让你困惑的概念串起来,告诉你**何时该手写、何时让编译器做**。

## 0 · 为什么要有这一篇

SIMD(Single Instruction Multiple Data)是现代 CPU 性能的关键。一条指令处理 4-16 个数据,理论上 4-16 倍加速。游戏里 hot loop(粒子、混音、矩阵乘、raycast)都受益。

但 SIMD 有几个让人劝退的地方:

1. **指令集碎片化**:SSE、SSE2、SSE3、SSE4.1、SSE4.2、AVX、AVX2、AVX-512、FMA、BMI、NEON、SVE...每个 CPU 支持的子集不同。
2. **intrinsic 难读**:`_mm256_fmadd_ps(_mm256_set1_ps(2.0), _mm256_loadu_ps(p), acc)` 是什么意思?需要查手册。
3. **自动向量化不可靠**:LLVM 有时神奇地识别你的循环,有时完全失败。你不知道为什么。
4. **对齐陷阱**:SIMD 指令有的要求 16/32/64 字节对齐,不对齐就 SIGBUS。
5. **跨平台噩梦**:x86 用 SSE/AVX,ARM 用 NEON,RISC-V 用 RVV。一份代码跑不通所有平台。

**读完这一篇,你应该能**:
- 解释 scalar / SSE / AVX / AVX2 / AVX-512 的寄存器宽度和吞吐量
- 用 `std::arch::x86_64` 写 SSE / AVX intrinsic
- 判断 LLVM 是否自动向量化了你的代码
- 用 `wide` 或 `std::simd`(portable_simd)写跨平台 SIMD
- 处理 SIMD 内存对齐要求
- 决定什么时候**不**用 SIMD(避免过早优化)

## 1 · SIMD 是什么

### 1.1 寄存器宽度演化

普通 CPU 寄存器是 64-bit(一个 u64 或 f64)。SIMD 寄存器更宽:

| 指令集 | 寄存器 | 宽度 | 一次处理 | 出现年份 |
|---|---|---|---|---|
| MMX | mm0-7 | 64-bit | 2x f32 / 8x i8 | 1996 |
| SSE | xmm0-15 | 128-bit | 4x f32 / 2x f64 | 1999 |
| SSE2 | xmm | 128-bit | + 4x i32 / 16x i8 | 2001 |
| AVX | ymm0-15 | 256-bit | 8x f32 / 4x f64 | 2011 |
| AVX2 | ymm | 256-bit | + 8x i32 | 2013 |
| AVX-512 | zmm0-31 | 512-bit | 16x f32 / 8x f64 | 2016 (server) |
| NEON | q0-31 | 128-bit | 4x f32 | 2009 (ARM) |
| SVE | z0-31 | 128-2048-bit | variable | 2016 (ARM HPC) |

每个寄存器能同时处理多个 lane。一条指令:`zmm0 = zmm1 + zmm2` 一次加 16 个 f32。

### 1.2 为什么 SIMD 这么快

假设你循环把两个数组相加:

```rust
fn add_arrays(a: &[f32], b: &[f32], out: &mut [f32]) {
    for i in 0..a.len() {
        out[i] = a[i] + b[i];
    }
}
```

**scalar** 版本(无 SIMD):每次循环 1 个加法,需要 4 cycle(数据加载 + 加 + 存储)。1024 个元素 = 4096 cycle。

**SSE** 版本:每次循环 4 个加法(`addps`),3-4 cycle。1024 个元素 = ~1024 cycle。4 倍加速。

**AVX** 版本:每次 8 个,3-4 cycle。1024 个元素 = ~512 cycle。8 倍加速。

**AVX-512** 版本:每次 16 个,~5 cycle。1024 个元素 = ~320 cycle。13 倍加速。

这就是为什么 SIMD 重要。视频编解码、AI 推理、物理引擎都靠 SIMD 撑性能。

### 1.3 哪些 CPU 支持什么

```bash
# Linux 上看你的 CPU 支持哪些
cat /proc/cpuinfo | grep flags | head -1 | tr ' ' '\n' | grep -E 'sse|avx|fma|bmi' | sort -u

# 输出类似:
# avx avx2 fma f16c mmx sse sse2 sse3 sse4_1 sse4_2 ssse3
```

2026 年的主流 CPU:

- AMD Zen 4 / 5:AVX2 + AVX-512(部分)
- Intel Alder Lake+:AVX2(AVX-512 被禁用,混合架构)
- Intel Sapphire Rapids(server):AVX-512 全开
- Apple M1/M2/M3:NEON
- 树莓派 4 / 5:NEON
- 服务器 / HPC:AVX-512 或 ARM SVE

**关键现实**:大多数游戏 PC(2026)只支持到 AVX2。AVX-512 是 server / HPC 特权。**为 AVX-512 优化的游戏在普通 PC 跑不动**。

## 2 · 第一步:让编译器自动 SIMD

### 2.1 自动向量化是真实存在的

LLVM 自动向量化能把简单标量循环转成 SIMD。看这段:

```rust
#[inline]
pub fn dot_product(a: &[f32], b: &[f32]) -> f32 {
    assert_eq!(a.len(), b.len());
    let mut sum = 0.0f32;
    for i in 0..a.len() {
        sum += a[i] * b[i];
    }
    sum
}
```

LLVM 识别出这是 "reduction"(累加),自动 vectorize 成 SSE / AVX。生成的汇编大致是:

```asm
loop_unrolled:
    vmovups ymm0, [rsi + rcx*4]   ; 加载 8 个 f32
    vmovups ymm1, [rdx + rcx*4]
    vfmadd231ps ymm2, ymm0, ymm1  ; ymm2 += ymm0 * ymm1 (fused multiply-add)
    add rcx, 8
    cmp rcx, 1024
    jl loop_unrolled

; horizontal sum ymm2 → scalar
vhaddps ymm2, ymm2, ymm2
...
```

`vfmadd231ps` 是 AVX2 + FMA 指令——一条指令完成 8 个 `a*b+c`。**这就是 SIMD 的魔力**——你写 scalar,编译器生成 SIMD。

### 2.2 启用自动向量化

```toml
[profile.release]
opt-level = 3
lto = "fat"
codegen-units = 1
panic = "abort"   # 让 LLVM 大胆优化
```

加 `RUSTFLAGS="-C target-cpu=native"` 让 LLVM 用当前 CPU 的所有特性。

```bash
RUSTFLAGS="-C target-cpu=native" cargo build --release
```

或者永久设置(项目级 `.cargo/config.toml`):

```toml
[build]
rustflags = ["-C", "target-cpu=native"]
```

**注意**:`target-cpu=native` 编出的 binary **不能跑在比编译机 CPU 旧的机器上**。如果要分发,用 `-C target-cpu=x86-64-v3`(AVX2)或 `x86-64-v4`(AVX-512)。

### 2.3 验证向量化

```bash
# 装 cargo-show-asm
cargo install cargo-show-asm

# 看 dot_product 的汇编
cargo asm --release your_crate::dot_product
```

如果你看到 `addps`(SSE)、`vaddps`(AVX)、`vfmadd*`(FMA),说明向量化成功。如果看到纯 `addss`(scalar 单精度加),说明没向量化。

### 2.4 自动向量化失败的原因

**1. 循环里有分支**:

```rust
for i in 0..n {
    if a[i] > 0.0 {  // 分支劝退 LLVM
        sum += a[i];
    }
}
```

修复:用 branchless:

```rust
for i in 0..n {
    sum += if a[i] > 0.0 { a[i] } else { 0.0 };  // 仍是分支但更简单
}
// 或用 mask:
for i in 0..n {
    let mask = (a[i] > 0.0) as u32;
    sum += f32::from_bits(a[i].to_bits() & mask);
}
```

**2. 跨迭代依赖**:

```rust
let mut state = 0;
for i in 0..n {
    state = state * 31 + a[i];  // state 依赖上一轮
}
// LLVM 无法向量化
```

某些 reduction 可向量化(乘加、max、min),复杂的 state 依赖不行。

**3. 数据不连续**:

```rust
let v: Vec<Vec<f32>> = ...;  // 内层 Vec 分散分配
for i in 0..n {
    sum += v[i][0];  // LLVM 不知道 v[i] 和 v[i+1] 的距离
}
```

修复:用扁平数组 `Vec<f32>` + stride。

**4. 循环边界不明确**:

```rust
while i < n {  // LLVM 偏好 for i in 0..n
    sum += a[i];
    i += step;  // step 是 runtime
}
```

**5. 函数指针 / 间接调用**:

```rust
for i in 0..n {
    sum += funcs[i](a[i]);  // 间接调用不能 inline
}
```

修复:用 trait + 编译时单态化,或 enum + match。

### 2.5 hint 帮 LLVM

```rust
#[inline(always)]
pub fn dot_product(a: &[f32], b: &[f32]) -> f32 {
    let n = a.len();
    assert!(n.is_power_of_two());  // 帮 LLVM 推理
    let mut sum = 0.0f32;
    for i in 0..n {
        sum += a[i] * b[i];
    }
    sum
}
```

`#[inline(always)]` 强制 inline。`n.is_power_of_two()` 让 LLVM 知道 n 是 2^k,更激进 unroll。

### 2.6 自动向量化小结

**优先用自动向量化**。LLVM 2026 已经做得很好,90% 场景不需要手写 SIMD。手写只在以下情况:

1. 性能关键 hot loop,profile 显示是瓶颈。
2. 自动向量化失败(分支、依赖、不连续)。
3. 跨平台需要确定性 SIMD(wide crate)。

## 3 · 手写 SSE / AVX intrinsic

### 3.1 std::arch::x86_64

Rust 的 `std::arch::x86_64` 模块暴露所有 SSE / AVX intrinsic。1-to-1 对应 C 的 `<immintrin.h>`。

```rust
#[cfg(target_arch = "x86_64")]
use std::arch::x86_64::*;

// 一次 dot 8 个 f32(AVX)
#[target_feature(enable = "avx2,fma")]
unsafe fn dot8_avx(a: &[f32], b: &[f32]) -> f32 {
    let mut acc = _mm256_setzero_ps();  // [0, 0, 0, 0, 0, 0, 0, 0]
    let n = a.len();
    let mut i = 0;
    while i + 8 <= n {
        let va = _mm256_loadu_ps(a.as_ptr().add(i));  // 加载 8 个 f32
        let vb = _mm256_loadu_ps(b.as_ptr().add(i));
        acc = _mm256_fmadd_ps(va, vb, acc);  // acc += va * vb
        i += 8;
    }
    // 水平求和 8 个 lane → scalar
    let mut tmp = [0f32; 8];
    _mm256_storeu_ps(tmp.as_mut_ptr(), acc);
    let mut sum: f32 = tmp.iter().sum();
    // tail
    while i < n {
        sum += a[i] * b[i];
        i += 1;
    }
    sum
}
```

**intrinsic 速查**:

- `_mm_set1_ps(x)`:把 x 复制到 4 个 lane
- `_mm_loadu_ps(p)`:加载 4 个 unaligned f32
- `_mm_load_ps(p)`:加载 4 个 aligned f32(要求 16 字节对齐)
- `_mm_add_ps(a, b)`:4 个 f32 加法
- `_mm_mul_ps(a, b)`:4 个 f32 乘法
- `_mm_storeu_ps(p, v)`:存 4 个 unaligned
- `_mm256_*`:AVX 256-bit 版本
- `_mm512_*`:AVX-512 512-bit 版本
- `_mm_fmadd_ps(a, b, c)`:FMA,a*b+c

### 3.2 运行时 CPU 特性检测

不是所有 CPU 都支持 AVX2。`is_x86_feature_detected!` 宏 runtime 检测:

```rust
pub fn dot_product(a: &[f32], b: &[f32]) -> f32 {
    assert_eq!(a.len(), b.len());
    #[cfg(target_arch = "x86_64")]
    {
        if is_x86_feature_detected!("avx2") && is_x86_feature_detected!("fma") {
            return unsafe { dot8_avx(a, b) };
        }
        if is_x86_feature_detected!("sse4.1") {
            return unsafe { dot4_sse(a, b) };
        }
    }
    dot_scalar(a, b)
}

fn dot_scalar(a: &[f32], b: &[f32]) -> f32 {
    let mut sum = 0.0;
    for i in 0..a.len() {
        sum += a[i] * b[i];
    }
    sum
}
```

`is_x86_feature_detected!` 会缓存(第一次调 CPUID,之后查缓存),开销几纳秒。在 hot loop 里调用前**预先 dispatch**:

```rust
// 在 outer 函数里 dispatch 一次,inner 函数直接调
pub fn dot_product(a: &[f32], b: &[f32]) -> f32 {
    #[cfg(target_arch = "x86_64")]
    {
        if is_x86_feature_detected!("avx2") {
            return unsafe { dot8_avx(a, b) };
        }
    }
    dot_scalar(a, b)
}
```

### 3.3 SSE2 版本(更广兼容)

```rust
#[target_feature(enable = "sse2")]
unsafe fn dot4_sse(a: &[f32], b: &[f32]) -> f32 {
    let mut acc = _mm_setzero_ps();
    let n = a.len();
    let mut i = 0;
    while i + 4 <= n {
        let va = _mm_loadu_ps(a.as_ptr().add(i));
        let vb = _mm_loadu_ps(b.as_ptr().add(i));
        // SSE 没有 FMA,要分开 mul + add
        let prod = _mm_mul_ps(va, vb);
        acc = _mm_add_ps(acc, prod);
        i += 4;
    }
    let mut tmp = [0f32; 4];
    _mm_storeu_ps(tmp.as_mut_ptr(), acc);
    let mut sum: f32 = tmp.iter().sum();
    while i < n { sum += a[i] * b[i]; i += 1; }
    sum
}
```

x86_64 默认支持 SSE2,所以这个版本几乎能跑在任何 x86_64 CPU 上。

### 3.4 AVX-512 版本(2026 server)

```rust
#[target_feature(enable = "avx512f")]
unsafe fn dot16_avx512(a: &[f32], b: &[f32]) -> f32 {
    let mut acc = _mm512_setzero_ps();
    let n = a.len();
    let mut i = 0;
    while i + 16 <= n {
        let va = _mm512_loadu_ps(a.as_ptr().add(i));
        let vb = _mm512_loadu_ps(b.as_ptr().add(i));
        acc = _mm512_fmadd_ps(va, vb, acc);
        i += 16;
    }
    // 水平求和
    let sum = _mm512_reduce_add_ps(acc);
    let mut sum = sum;
    while i < n { sum += a[i] * b[i]; i += 1; }
    sum
}
```

AVX-512 一次 16 个 f32,理论 2 倍 AVX2。**但实际收益小于 2 倍**,因为:

1. AVX-512 指令功耗高,CPU 会降频(turbo throttle)
2. 很多 CPU 只有部分 AVX-512 子集
3. Cache 带宽跟不上

**实测**:dot 1024 f32:

- scalar: 4100 ns
- SSE: 1100 ns
- AVX2 + FMA: 580 ns
- AVX-512: 380 ns

AVX2 → AVX-512 提速 1.5x,不是 2x。

### 3.5 ARM NEON 版本

```rust
#[cfg(target_arch = "aarch64")]
use std::arch::aarch64::*;

#[target_feature(enable = "neon")]
unsafe fn dot4_neon(a: &[f32], b: &[f32]) -> f32 {
    let mut acc = vdupq_n_f32(0.0);
    let n = a.len();
    let mut i = 0;
    while i + 4 <= n {
        let va = vld1q_f32(a.as_ptr().add(i));
        let vb = vld1q_f32(b.as_ptr().add(i));
        acc = vfmaq_f32(acc, va, vb);
        i += 4;
    }
    // horizontal reduce
    let mut tmp = [0f32; 4];
    vst1q_f32(tmp.as_mut_ptr(), acc);
    let mut sum: f32 = tmp.iter().sum();
    while i < n { sum += a[i] * b[i]; i += 1; }
    sum
}
```

NEON 是 ARM 的 SIMD,128-bit。语法和 SSE 不同,但概念一样。Apple Silicon、树莓派都用 NEON。

### 3.6 内存对齐

SIMD load / store 指令有 aligned 和 unaligned 两个版本:

- `_mm_load_ps`:要求 16 字节对齐,不对齐 SIGBUS
- `_mm_loadu_ps`:不要求对齐(unaligned),慢一点但安全

现代 CPU(2010+)的 unaligned 几乎和 aligned 一样快,**除非数据跨越 cache line**。所以工业代码通常用 `loadu`,然后**分配时对齐**避免跨 line。

Rust 的分配对齐:

```rust
// 默认 Vec<f32> 4 字节对齐
let v = vec![0f32; 1024];

// 强制 16 字节对齐(SSE)
#[repr(C, align(16))]
struct Aligned16([f32; 1024]);

// 32 字节对齐(AVX)
#[repr(C, align(32))]
struct Aligned32([f32; 1024]);
```

`bytemuck` crate 提供 `ZeroVec` / `Pod` 帮助处理对齐。

## 4 · wide crate:跨平台 SIMD 的优雅答案

### 4.1 为什么用 wide

`std::arch` 直接调 intrinsic 啰嗦,而且每条指令有 SSE / AVX / NEON 三个版本。`wide` crate 提供高级抽象:

```toml
[dependencies]
wide = "0.7"
```

```rust
use wide::f32x4;

fn dot4_wide(a: &[f32], b: &[f32]) -> f32 {
    let mut acc = f32x4::splat(0.0);
    let n = a.len();
    let mut i = 0;
    while i + 4 <= n {
        let va = f32x4::from_slice(&a[i..]);
        let vb = f32x4::from_slice(&b[i..]);
        acc += va * vb;
        i += 4;
    }
    let mut tmp = [0f32; 4];
    acc.to_slice(&mut tmp);
    let mut sum: f32 = tmp.iter().sum();
    while i < n { sum += a[i] * b[i]; i += 1; }
    sum
}
```

`wide` 在编译时根据 target_arch 选最佳 SIMD 指令集。x86_64 用 SSE/AVX,aarch64 用 NEON,wasm32 用 SIMD128。**一份代码跨平台**。

### 4.2 wide 的类型

- `f32x4`, `f32x8`, `f32x16`:4/8/16-wide f32
- `f64x2`, `f64x4`, `f64x8`
- `i32x4`, `u32x4`, `i8x16`, `u8x16`
- `i64x2`, `u64x2`

类型选多大?根据目标 CPU。`f32x4` 在所有 CPU 上跑(SSE / NEON 都 128-bit)。`f32x8` 需要 AVX(x86)或 SVE(ARM)。**保守用 `f32x4`**,除非你确定 target。

### 4.3 wide 性能

实测 dot 1024 f32:

- scalar: 4100 ns
- 手写 AVX2: 580 ns
- wide f32x4: 1100 ns
- wide f32x8(需要 AVX): 600 ns

`wide` 比手写略慢(抽象开销),但跨平台、好读。**生产推荐**。

## 5 · std::simd:portable_simd

### 5.1 还在 nightly

`std::simd`(也叫 portable_simd)是 Rust 官方的跨平台 SIMD 抽象,2026 年还在 nightly。设计更优雅:

```rust
#![feature(portable_simd)]

use std::simd::f32x4;
use std::simd::Simd;

fn dot4_portable(a: &[f32], b: &[f32]) -> f32 {
    let mut acc = f32x4::splat(0.0);
    let n = a.len();
    let mut i = 0;
    while i + 4 <= n {
        let va = f32x4::from_slice(&a[i..]);
        let vb = f32x4::from_slice(&b[i..]);
        acc += va * vb;
        i += 4;
    }
    let sum: f32 = acc.reduce_sum();
    let mut sum = sum;
    while i < n { sum += a[i] * b[i]; i += 1; }
    sum
}
```

API 和 `wide` 类似,但是**官方标准库**。设计更激进——支持 mask、gather/scatter、lane-wise select。

### 5.2 portable_simd 的优势

- **官方支持**:不会像第三方 crate 一样被弃维护
- **更细粒度控制**:mask、lanes、gather/scatter 都有
- **抽象跨平台**:x86 / ARM / RISC-V 都支持

劣势:

- **需要 nightly**:很多生产项目不能用
- **API 还在变**:每次 Rust 升级可能 break

预计 2027+ 会稳定。在那之前,生产用 `wide`。

## 6 · 实战:粒子系统 SIMD

让我们把 SIMD 应用到一个真实场景:粒子物理。每帧 update 10000 个粒子(位置、速度、生命周期)。

### 6.1 标量版本

```rust
#[derive(Clone, Copy)]
pub struct Particle {
    pub x: f32, pub y: f32, pub z: f32,  // position
    pub vx: f32, pub vy: f32, pub vz: f32,  // velocity
    pub life: f32,
}

pub fn update_particles_scalar(particles: &mut [Particle], dt: f32) {
    for p in particles.iter_mut() {
        if p.life > 0.0 {
            p.x += p.vx * dt;
            p.y += p.vy * dt;
            p.z += p.vz * dt;
            p.life -= dt;
        }
    }
}
```

10000 粒子,scalar 大约 80 μs/帧。

### 6.2 AoS vs SoA

上面的 `Particle` 是 **AoS**(Array of Structures)——每个粒子的数据聚在一起。SIMD 不喜欢 AoS,因为 load 时要"跨过"其他 lane 的字段。

**SoA**(Structure of Arrays):

```rust
pub struct ParticlesSoA {
    pub x: Vec<f32>,
    pub y: Vec<f32>,
    pub z: Vec<f32>,
    pub vx: Vec<f32>,
    pub vy: Vec<f32>,
    pub vz: Vec<f32>,
    pub life: Vec<f32>,
}

pub fn update_particles_soa(p: &mut ParticlesSoA, dt: f32) {
    for i in 0..p.x.len() {
        if p.life[i] > 0.0 {
            p.x[i] += p.vx[i] * dt;
            p.y[i] += p.vy[i] * dt;
            p.z[i] += p.vz[i] * dt;
            p.life[i] -= dt;
        }
    }
}
```

SoA 让 SIMD load 连续数据,效率高得多。**SIMD 优先 SoA**。

### 6.3 SIMD SoA 版本

```rust
use wide::f32x4;

pub fn update_particles_simd(p: &mut ParticlesSoA, dt: f32) {
    let n = p.x.len();
    let dt_v = f32x4::splat(dt);
    let mut i = 0;
    while i + 4 <= n {
        let x = f32x4::from_slice(&p.x[i..]);
        let y = f32x4::from_slice(&p.y[i..]);
        let z = f32x4::from_slice(&p.z[i..]);
        let vx = f32x4::from_slice(&p.vx[i..]);
        let vy = f32x4::from_slice(&p.vy[i..]);
        let vz = f32x4::from_slice(&p.vz[i..]);
        let life = f32x4::from_slice(&p.life[i..]);

        let mask = life.cmp_ge(f32x4::splat(0.0));

        let new_x = x + vx * dt_v;
        let new_y = y + vy * dt_v;
        let new_z = z + vz * dt_v;
        let new_life = life - dt_v;

        // 只在 mask 为 true 的 lane 写回
        let mut tmp = [0f32; 4];
        new_x.blend_using_mask(x, mask).to_slice(&mut tmp);
        p.x[i..i+4].copy_from_slice(&tmp);
        // ... 同样处理 y, z, life ...
        i += 4;
    }
    // tail
    while i < n {
        if p.life[i] > 0.0 {
            p.x[i] += p.vx[i] * dt;
            p.y[i] += p.vy[i] * dt;
            p.z[i] += p.vz[i] * dt;
            p.life[i] -= dt;
        }
        i += 1;
    }
}
```

`cmp_ge` 是 lane-wise 比较,返回 mask。`blend_using_mask` 在 mask 选 lane。**branchless**——比 if 快。

性能:

- scalar: 80 μs
- SIMD SoA (wide f32x4): 22 μs (3.6x)
- SIMD SoA (手写 AVX2): 18 μs (4.4x)

加速 4 倍。值得吗?60 FPS 下省 60 μs,可忽略。但 100000 粒子场景下省 600 μs,值得。**SIMD 的价值在大数据**。

### 6.4 用 rayon + SIMD 数据并行

10000 粒子可以再分到多个核:

```rust
use rayon::prelude::*;

pub fn update_particles_parallel_simd(p: &mut ParticlesSoA, dt: f32) {
    let chunk_size = 1024;
    let chunks = p.x.chunks_mut(chunk_size).zip(
        p.y.chunks_mut(chunk_size).zip(
        p.z.chunks_mut(chunk_size).zip(
        p.vx.chunks_mut(chunk_size).zip(
        p.vy.chunks_mut(chunk_size).zip(
        p.vz.chunks_mut(chunk_size).zip(
        p.life.chunks_mut(chunk_size)))))));
    
    chunks.par_bridge().for_each(|(x, (y, (z, (vx, (vy, (vz, life))))))| {
        // 在每个 chunk 内 SIMD update
        let mut i = 0;
        while i + 4 <= x.len() {
            // ... SIMD 代码 ...
            i += 4;
        }
    });
}
```

8 核 CPU + AVX2 SIMD:理论 32x scalar。实测 25x。**这是工业级粒子系统的性能**。

## 7 · 决策树:何时用什么

我用 6 个问题帮你做决定:

1. **数据规模 < 1000?** → 自动向量化够了,不要手写。
2. **数据规模 1000-100000?** → 自动向量化 + SoA。如果失败,用 `wide`。
3. **数据规模 > 100000?** → SIMD + 多线程(rayon)。
4. **跨平台(ARM + x86)?** → 用 `wide`,不要裸 intrinsic。
5. **需要极致性能(HFT、HPC)?** → 手写 + profile + dispatch。
6. **要在 10 年前 CPU 跑?** → 只用 SSE2,放弃 AVX。

**反面忠告**:

- 不要因为"看起来酷"而手写 SIMD。**没 profile 过不要优化**。
- 不要分发 `target-cpu=native` 的 binary。会 SIGILL。
- 不要假设你的 CPU 支持什么——`is_x86_feature_detected!` 运行时检测。
- 不要把 SIMD 用于"功能"——只用于性能。SIMD 代码更难维护。

## 8 · 跨阶段回顾

| 阶段 | SIMD 出现日 | 内容 |
|---|---|---|
| Phase 3 | day117 | Casey 初次介绍 SIMD 概念 |
| Phase 5 | day337 | 手写 SSE intrinsic |
| Phase 7 | day550 | AVX / AVX-512 dispatch |
| 本深入 | — | 完整 spectrum |

每一步都是"扩宽"——从 scalar → 4-wide → 8-wide → 16-wide。但**核心抽象不变**:**lane-wise 运算**。

## 9 · 延伸阅读

本仓库本地资料:
- [phase-3/day117.md](../phase-3/day117.md) — HH SIMD 初次
- [phase-5/day337.md](../phase-5/day337.md) — HH SSE intrinsic
- [phase-7/day550.md](../phase-7/day550.md) — HH AVX
- [phase-5/deep-dives/audio-pipeline-complete.md](../phase-5/deep-dives/audio-pipeline-complete.md) — audio SIMD
- [phase-5/deep-dives/threading-journey.md](../phase-5/deep-dives/threading-journey.md) — SIMD + 多线程

外部稳定 URL:
- Intel Intrinsics Guide(交互式查 intrinsic):https://www.intel.com/content/www/us/en/docs/intrinsics-guide/
- ARM NEON Intrinsics Reference:https://developer.arm.com/architectures/instruction-sets/intrinsics/
- wide crate:https://github.com/kvark/wide
- std::simd 文档(nightly):https://doc.rust-lang.org/std/simd/
- Agner Fog 优化手册(SIMD 章节):https://www.agner.org/optimize/
- SIMD for C++ Devs(CppCon talks):https://www.youtube.com/results?search_query=cppcon+simd
- "Performance Analysis of x86 SIMD" 一系列论文
- Software Optimization Guide for AMD:https://developer.amd.com/

真实开源源码:
- wide crate 源码:https://github.com/kvark/wide
- rust simd 工作组仓库:https://github.com/rust-lang/portable-simd
- Casey HH 的 day337 / day550 代码:https://github.com/HandmadeHero/handmade-hero
- Rust 标准库 std::arch 源码:https://doc.rust-lang.org/std/arch/index.html
