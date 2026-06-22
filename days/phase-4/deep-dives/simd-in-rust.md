---
title: "SIMD in Rust"
subtitle: "std::arch::x86_64, portable-simd, wide crate, auto-vectorization"
type: deep-dive
phase: 4
domains: [rust, graphics, game]
duration: "2-3h"
---

# SIMD in Rust

> 这篇 deep-dive 把 Phase 4 里散见各处的 SIMD 知识整合:从最基础的 SSE2 到现代 portable_simd,从手写 intrinsics 到编译器自动向量化。读完后你能判断:某个场景该手写 SIMD、依赖编译器、还是用 `wide` crate。

## 0 · SIMD 是什么

SIMD = Single Instruction, Multiple Data。一条 CPU 指令处理多个数据。

标量(普通)代码:

```rust
let a = [1.0, 2.0, 3.0, 4.0];
let b = [10.0, 20.0, 30.0, 40.0];
let mut c = [0.0; 4];
for i in 0..4 { c[i] = a[i] + b[i]; }
// 4 条 add 指令
```

SIMD:

```rust
let va = _mm_set_ps(4.0, 3.0, 2.0, 1.0);  // 一条 load
let vb = _mm_set_ps(40.0, 30.0, 20.0, 10.0);
let vc = _mm_add_ps(va, vb);  // 一条 add,4 lane 同时算
// 1 条 add 指令
```

理论 4 倍速。实际 1.5-4x,看场景。

## 1 · SIMD 的硬件发展

| ISA | 寄存器位宽 | f32 lane | 引入年 | 代表 CPU |
|---|---|---|---|---|
| MMX | 64 | 0(只 int) | 1997 | Pentium MMX |
| SSE | 128 | 4 | 1999 | Pentium III |
| SSE2 | 128 | 4 | 2001 | Pentium 4 |
| SSE3/SSE4 | 128 | 4 | 2004-2007 | Core 2 |
| AVX | 256 | 8 | 2011 | Sandy Bridge |
| AVX2 | 256 | 8(int) | 2013 | Haswell |
| AVX-512 | 512 | 16 | 2017 | Skylake-X |
| NEON(ARM) | 128 | 4 | 2000s | Cortex-A |
| SVE(ARM) | 可变 | 4-16 | 2018 | 服务器 ARM |
| WASM SIMD | 128 | 4 | 2020 | modern browsers |

主流游戏开发:

- **x86_64**:SSE2(最低基线)+ AVX2(可选加速)
- **ARM64 / Apple Silicon**:NEON
- **WASM**:Wasm SIMD

## 2 · Rust SIMD 的三种风格

### 风格 A:`std::arch::x86_64`(platform-specific intrinsics)

最底层,直接对应 CPU 指令。

```rust
#[cfg(target_arch = "x86_64")]
use std::arch::x86_64::*;

#[cfg(target_arch = "x86_64")]
fn sum_sse(data: &[f32]) -> f32 {
    unsafe {
        let mut sum = _mm_setzero_ps();
        let chunks = data.chunks_exact(4);
        for c in chunks {
            let v = _mm_loadu_ps(c.as_ptr());
            sum = _mm_add_ps(sum, v);
        }
        // horizontal add 4 lane
        let mut arr = [0f32; 4];
        _mm_storeu_ps(arr.as_mut_ptr(), sum);
        arr.iter().sum::<f32>() + chunks.remainder().iter().sum::<f32>()
    }
}
```

**优点**:极致控制,编译出可预测汇编。
**缺点**:平台绑定(ARM / WASM 不能编译),unsafe,API 难看。

### 风格 B:`std::simd`(portable_simd,nightly)

Rust 官方的跨平台 SIMD。

```rust
#![feature(portable_simd)]
use std::simd::{f32x4, SimdFloat};

fn sum_portable(data: &[f32]) -> f32 {
    let mut sum = f32x4::splat(0.0);
    let chunks = data.chunks_exact(4);
    for c in chunks {
        let v = f32x4::from_slice(c);
        sum += v;
    }
    sum.horizontal_sum() + chunks.remainder().iter().sum::<f32>()
}
```

**优点**:跨平台(x86/ARM/WASM 自动适配),safe Rust,API 简洁。
**缺点**:nightly only(2024 还在 unstable)。

### 风格 C:`wide` crate(stable)

稳定版的"portable_simd"。

```rust
use wide::f32x4;

fn sum_wide(data: &[f32]) -> f32 {
    let mut sum = f32x4::splat(0.0);
    let chunks = data.chunks_exact(4);
    for c in chunks {
        let v = f32x4::from(c);  // 注意 slice 转 f32x4
        sum += v;
    }
    let arr: [f32; 4] = sum.into();
    arr.iter().sum::<f32>() + chunks.remainder().iter().sum::<f32>()
}
```

**优点**:stable,跨平台。
**缺点**:非官方,某些边缘 case 没 portable_simd 完整。

### 风格 D:让编译器自动向量化

```rust
fn sum_auto(data: &[f32]) -> f32 {
    data.iter().sum()
}
// 用 cargo build --release,rustc 自动用 SIMD
```

**优点**:零代码改动。
**缺点**:不一定触发(编译器启发式),依赖编译器版本。

### 选择建议

| 场景 | 推荐 |
|---|---|
| 简单循环求和 | auto-vectorization(测试是否触发) |
| 跨平台项目 | wide crate |
| 复杂算法 + 多平台 | portable_simd(nightly) |
| 极致性能 + x86_64 only | std::arch::x86_64 + intrinsics |

## 3 · 常用 intrinsics 速查(SSE2)

| intrinsic | 含义 |
|---|---|
| `_mm_setzero_ps()` | 全 0 |
| `_mm_set1_ps(x)` | 4 lane 全 x |
| `_mm_set_ps(a,b,c,d)` | [d,c,b,a](逆序!) |
| `_mm_load_ps(p)` | 对齐加载 |
| `_mm_loadu_ps(p)` | 未对齐加载 |
| `_mm_store_ps(p, x)` | 对齐存 |
| `_mm_storeu_ps(p, x)` | 未对齐存 |
| `_mm_add_ps(a, b)` | 4 lane 加 |
| `_mm_sub_ps(a, b)` | 减 |
| `_mm_mul_ps(a, b)` | 乘 |
| `_mm_div_ps(a, b)` | 除 |
| `_mm_min_ps(a, b)` | 取小 |
| `_mm_max_ps(a, b)` | 取大 |
| `_mm_sqrt_ps(a)` | 平方根 |
| `_mm_floor_ps(a)` | SSE4.1 向下取整 |
| `_mm_cmpeq_ps(a, b)` | 4 lane 比较,得 mask |
| `_mm_blendv_ps(a, b, mask)` | 按 mask 选 a/b |

注意:`_mm_set_ps` 参数**逆序**——最后一个参数在 lane 0(低位)。

## 4 · Auto-vectorization

Rust 编译器(LLVM)能自动向量化简单循环。条件:

1. 循环边界确定
2. 无数据依赖(loop-carried)
3. 无函数调用(或可内联)
4. 数据连续(slice / Vec)
5. 编译期知道目标 SIMD 特性

### 触发 auto-vectorization 的写法

```rust
// 好:简单循环
fn sum_good(data: &[f32]) -> f32 {
    let mut s = 0.0;
    for &x in data { s += x; }
    s
}

// 不好:函数调用 + 数据依赖
fn sum_bad(data: &[f32]) -> f32 {
    let mut s = 0.0;
    for &x in data { s = complicated_op(s, x); }
    s
}
```

### 验证

```bash
cargo rustc --release -- --emit asm -C target-feature=+avx2
find target/release/deps -name "*.s" | head -1 | xargs grep -E "addps|vaddps|ymm"
# 看到 addps / vaddps 说明 SIMD 化了
```

或用 LLVM MCA 分析端口占用。

## 5 · 实战示例:SIMD 矩阵乘法

```rust
#[cfg(target_arch = "x86_64")]
use std::arch::x86_64::*;

#[cfg(target_arch = "x86_64")]
fn matmul_4x4_sse(a: &[f32; 16], b: &[f32; 16]) -> [f32; 16] {
    unsafe {
        // a 和 b 是 row-major 4x4
        // 结果 c[i][j] = sum(a[i][k] * b[k][j])
        let mut c = [0f32; 16];

        for i in 0..4 {
            // 加载 a 的第 i 行到 a_row(broadcast 不需要,直接 load)
            let a_row = _mm_loadu_ps(&a[i * 4]);

            for j in 0..4 {
                // 加载 b 的第 j 列(需要 shuffle)
                let b_col = _mm_set_ps(b[3*4 + j], b[2*4 + j], b[1*4 + j], b[0*4 + j]);
                let prod = _mm_mul_ps(a_row, b_col);
                // 水平加
                let mut arr = [0f32; 4];
                _mm_storeu_ps(arr.as_mut_ptr(), prod);
                c[i * 4 + j] = arr.iter().sum::<f32>();
            }
        }
        c
    }
}
```

这只是演示。真正高效的 4x4 矩阵乘用 `_mm_fmadd_ps`(FMA,fused multiply-add)。

## 6 · SIMD 在 Phase 4 的应用

回顾 Phase 4 用到 SIMD 的地方:

- **Day 115-120**:SIMD 基础,Vec4 / Mat4 算术
- **Day 121**:tiled rendering,framebuffer blit SIMD
- **Day 144-145**:SSE 混音器,变调 + 插值
- **Day 146**:累加精度(用 FMA 改善)

游戏开发 SIMD 高频场景:

- 向量 / 矩阵数学(`glam` crate)
- 图像处理(blur / filter / blend)
- 音频(混音 / 滤波器)
- 物理(粒子 / 碰撞)
- 字体(栅格化扫描线)

## 7 · SIMD 的陷阱

### 陷阱 1:对齐

`_mm_load_ps` 要求 16 字节对齐,否则 segfault。Vec<T> 默认按 T 对齐(`align_of::<f32>()` = 4),不 16 字节。

解决:用 `_mm_loadu_ps`(未对齐,稍慢),或分配对齐 buffer。

```rust
use std::alloc::{alloc_zeroed, Layout};
let layout = Layout::from_size_align(n * 4, 16).unwrap();
unsafe {
    let ptr = alloc_zeroed(layout) as *mut f32;
    let slice = std::slice::from_raw_parts_mut(ptr, n);
    // 现在 slice.as_ptr() 是 16 对齐
}
```

### 陷阱 2:set_ps 逆序

`_mm_set_ps(a, b, c, d)` → 寄存器 `[d, c, b, a]`(lane 0 到 3)。常搞错。

记忆:**函数参数从右到左压栈**(C calling convention),低位 = 内存低地址 = 数组下标 0。

### 陷阱 3:AVX 频率降级

某些 CPU 在跑 AVX-512 时钟降 10-30%(避免过热)。实际性能未必比 AVX2 好。**游戏开发推荐 AVX2 上限**。

### 陷阱 4:horizontal_add 慢

把 SIMD 寄存器的 4 lane 求和(horizontal)是 SIMD 的弱项——通常需要 2-3 条指令(`haddps` 重复)。如果可能,**保持数据在 SIMD 寄存器**,不要频繁 horizontal。

## 8 · 资源

- Intel intrinsics guide:https://www.intel.com/content/www/us/en/docs/intrinsics-guide/
- Agner Fog 优化手册:https://www.agner.org/optimize/
- LLVM auto-vectorization:https://llvm.org/docs/Vectorizers.html
- wide crate:https://github.com/Lokathor/wide
- portable_simd tracking:https://github.com/rust-lang/portable-simd

## 9 · 练习

### Lv1

用 `wide::f32x4` 实现 vec4 dot product。对比标量版性能。

### Lv2

用 `std::arch::x86_64` 写一个 RGB → grayscale 函数。每像素 R/G/B 三个 u8 → 一个 u8 = 0.299 R + 0.587 G + 0.114 B。SIMD 一次处理 16 像素。

### Lv3

用 SIMD 实现 4x4 矩阵 × 4 向量。验证 vs `glam` 的实现。

### Lv4

把 `glam` 的某个 SIMD 函数(`Mat4::mul`)读源码,看它如何处理跨平台 SSE / NEON / WASM。提一个 doc PR。
