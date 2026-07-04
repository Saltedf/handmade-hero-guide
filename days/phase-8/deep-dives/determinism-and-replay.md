
# 决定性与 Replay 系统完整深度专题

> 你跟着 Handmade Hero 走到 Day 580,游戏已经发行。一个玩家发邮件说:"我保存的游戏存档,在我朋友家电脑上加载后,怪物 AI 走向不一样,半小时后游戏 desync,两个人对战完全没法重现。"你以为是存档 bug——重写存档系统,问题依旧。你以为是时钟漂移——加 NTP 同步,问题依旧。最后你打开 debug log 对比,发现根本原因:**两台机器的浮点 `sin()` 函数返回值在第 12 位小数后不一样**。这个差异每帧累加,30 分钟后游戏状态完全不同。今天这一篇,从 IEEE 754 浮点的二进制表示讲起,把所有"看起来在跑其实偷偷漂移"的陷阱讲清楚:FMA 指令、SSE 控制字、-ffast-math、NaN payload、x86 vs ARM、跨编译器差异、fixed-point 替代方案。然后讲 RNG 决定性——为什么 std::rand / rand::thread_rng() 都不能用,完整推导 PCG (O'Neill 2014) 的 LCG + permutation 输出函数。最后讲 replay 系统的三种架构(input-only、state-snapshot、hybrid),Box2D / Rapier 的决定性边界,以及怎么给你 HH 项目加一个"30 秒前发生了什么"的倒带系统。读完这一篇,你的游戏能在 Linux / Windows / macOS / Steam Deck 上跨平台完全一致,能记录玩家操作然后完美回放,能给反作弊 / 调试 / netcode 提供决定性基础。

## 0 · 为什么要有这一篇

决定性(determinism)是游戏开发里最反直觉的话题之一。新手觉得"我写的代码,跑两次结果应该一样啊",老手知道"浮点 + 多线程 + 编译器优化 + 硬件差异 = 几乎不可能一样"。两边的认知鸿沟,藏在这三个事实里:

**事实一:浮点不是数学,是工程近似**。你以为 `0.1 + 0.2 == 0.3` 在浮点里成立——它不成立,结果是 `0.30000000000000004`。你以为 `sin(π/4)` 在两台机器上结果一样——它不一样,Intel CPU 和 AMD CPU 的 microcode 实现差几位 ULP(Unit in the Last Place)。你以为 `a + b + c == a + c + b` 因为加法交换律——它不成立,因为浮点加法不满足结合律。这些不是"小到可以忽略"的差异——一个游戏每帧累加 1e-15 误差,60 FPS 跑 30 分钟 = 1.8e8 帧误差,即便每帧只差 1e-15,累加后玩家位置可能差几米。这就是为什么《星际争霸》职业比赛对 desync 零容忍——desync 意味着双方看见不同的世界,比赛作废。

**事实二:多线程让"看起来确定"变不可能**。即便你的代码本身确定(没有随机数、没有系统时间),多线程让结果不确定——thread scheduler 决定哪个 thread 先跑,如果两个 thread 都往一个累加器加浮点,加的顺序每帧不同,浮点累加结果不同。这就是为什么严肃 netcode / replay 系统强制**单线程 simulation** 或**确定性多线程**(per-thread 独立 state,不交互)。

**事实三:编译器优化会"破坏"决定性**。GCC / Clang / MSVC 的 `-O2` / `-O3` 默认假设浮点满足结合律(其实不满足),会重排浮点运算。`-ffast-math` 更激进,直接重写你的浮点代码。结果:Debug build 和 Release build 浮点结果不同,意味着你不能"Debug 复现 Release 的 bug"。Rust 默认 `-C overflow-checks=on` 在 debug、`off` 在 release,本身就是行为差异。生产里很多 desync bug 来源就是"Debug 没问题 Release desync"。

这三件事合起来意味着:**决定性是工程纪律,不是免费午餐**。你必须从第一天就设计,后期加几乎不可能。本篇全文都是"工程纪律"。

读者基线假设:你完成了 Phase 0(14-math / 20-math-extended)+ Phase 4 atomics + Phase 5 Day 176 debug overlay。也就是说:

- 你写过浮点代码,知道 `f32` / `f64` 的差别
- 你理解 thread / atomic / happens-before
- 你知道 Rust 默认 build 模式和 release build 的差别
- 你不知道的是:**怎么让游戏在任意硬件、任意编译器、任意多线程调度下产生完全相同的结果**

这就是今天的主题。

**学完这一篇,你应该能**:

- 解释 IEEE 754 浮点的二进制表示,知道为什么 0.1 + 0.2 ≠ 0.3
- 解释 FMA(fused multiply-add)、-ffast-math、SSE control word 对决定性的影响
- 写一个跨平台 PCG RNG(Rust 实现,~50 行),保证跨平台 bit-exact
- 写一个 hash-based desync detection 系统(CRC32 / xxHash / FNV)
- 设计三种 replay 架构(input-only / state-snapshot / hybrid),知道取舍
- 解释 Box2D / Rapier 的决定性边界,知道哪些操作跨平台一致、哪些不
- 在你 HH 项目里加 replay 系统,能回放最近 30 秒
- 给 Rapier 或 bevy_ecs 提一个有意义的 PR(决定性相关)

## 1 · 决定性是什么

我们要从头讲。先确认你脑子里"决定性"的定义,然后逐步往里加复杂度。

### 1.1 定义

**决定性(determinism)**:给定相同的初始状态 `S0` 和相同的输入序列 `I`,程序总是产生相同的状态序列 `S0 → S1 → S2 → ...` 和相同的输出。

关键点:

1. **初始状态相同**。这要求 `S0` 在所有机器上 bit-exact 一致。
2. **输入序列相同**。这要求所有机器看见相同的输入。
3. **状态转移函数 `f` 相同**。这要求 `f(S, I) → S'` 在所有机器上 bit-exact 一致。
4. **输出相同**。这是 1-3 的推论。

听起来简单,实现起来地狱——因为 `f` 包含浮点运算,浮点在不同硬件 / 编译器 / 优化级别下结果可能不同。

### 1.2 决定性的三个层次

工业实践把决定性分成三个层次,强度递增:

**层次 1:Single-platform determinism**。同一台机器,同一个 build,跑两次产生相同结果。这是最低要求——如果你连这都做不到,你连单元测试都写不了(测试期望值每次跑不一样)。Rust 的`#[test]` 默认要求这个层次。

**层次 2:Cross-build determinism**。同一台机器,不同 build(Debug / Release / 不同 compiler flag),跑两次产生相同结果。这是发布游戏的最低要求——玩家用 Release 玩,开发者用 Debug 复现 bug,如果两边结果不同,Debug 找不到 Release 的 bug。这个层次**很难**,要禁用 fast-math、固定浮点模式、避免 SIMD 重排。

**层次 3:Cross-platform determinism**。不同机器(Linux x86 / Windows x86 / Mac ARM / Steam Deck),不同 build,跑两次产生相同结果。这是 netcode / replay / esports 的要求——每个玩家在不同硬件上跑,如果结果不同,desync。这个层次**极难**,要避免所有平台特定的浮点函数(libm)、固定 RNG、固定 iteration 顺序。

Casey 在 HH 的早期不太关心决定性——单机游戏,玩家在自己机器上玩,desync 无所谓。但到 Day 400+ Casey 加 replay 系统,Day 500+ Casey 谈 netcode,决定性变成核心议题。这就是为什么这个 deep dive 在 Phase 8(后期)——发行前你必须决定。

### 1.3 为什么游戏需要决定性

5 个用例,从轻到重排:

**用例 1:测试**。单元测试要 reproducible。`assert_eq!(simulate(input), expected_state)` 要每次跑出同样的 state,否则测试没意义。

**用例 2:Replay**。玩家想看"我刚才那一波神操作"的回放。回放要求"用相同初始状态 + 记录的输入,完美重建当时的游戏"——必须决定性。

**用例 3:Debug**。玩家报告"我在 X 时刻遇到 bug Y"。开发者要重现——如果游戏决定性,玩家提供"输入记录 + 初始 seed",开发者完美重现 bug。如果不决定性,bug 不可重现,极难修。

**用例 4:Netcode lockstep**。多人游戏 lockstep 协议:每帧每个 client 把自己的输入广播给所有人,所有 client 用相同输入跑相同 simulation。如果 simulation 决定,所有 client 状态相同——这就是《星际争霸》《帝国时代》的网络模型。如果不决定,desync,游戏崩。

**用例 5:Esports 公平性**。职业比赛对 desync 零容忍。如果 A 玩家机器上怪物走左,B 玩家机器上怪物走右,比赛作废。这就是为什么 Blizzard / Valve 投入大量工程保证决定性。

## 2 · IEEE 754 浮点陷阱

我们要看清楚浮点的本质。**不理解浮点的二进制表示,你永远在猜哪里 desync**。

### 2.1 IEEE 754 二进制表示

IEEE 754 是浮点数标准(1985 年发布,2008 / 2019 修订)。`f32` 的 32 位这样布局:

```
[ sign: 1 bit ][ exponent: 8 bits ][ mantissa: 23 bits ]
     bit 31        bits 30-23            bits 22-0
```

数值 = `(-1)^sign * 1.mantissa * 2^(exponent - 127)`

例子:`1.0f32`:
- sign = 0
- exponent = 127(0b01111111),实际指数 0
- mantissa = 0(1.0 的隐式 1 + .0)
- 32 位:`0 01111111 00000000000000000000000` = 0x3F800000

例子:`0.5f32`:
- sign = 0
- exponent = 126,实际指数 -1
- mantissa = 0
- 数值 = 1.0 * 2^(-1) = 0.5

例子:`-2.0f32`:
- sign = 1
- exponent = 128,实际指数 1
- mantissa = 0
- 数值 = -1 * 1.0 * 2^1 = -2.0

### 2.2 为什么 0.1 + 0.2 ≠ 0.3

`0.1` 在十进制是 finite,在二进制是 infinite repeating:`0.1 (10) = 0.0001100110011...(2)`。`f32` 只有 23 位 mantissa,所以截断到 `0.10000000149...`。同理 `0.2` 截断到 `0.20000000298...`。

```rust
fn main() {
    let a: f32 = 0.1;
    let b: f32 = 0.2;
    let c: f32 = 0.3;
    println!("{}", a + b);  // 0.30000001192092896
    println!("{}", c);      // 0.30000001192092896
    // 在 f32 上 a+b 实际上 == c!但 f64:
    
    let a: f64 = 0.1;
    let b: f64 = 0.2;
    let c: f64 = 0.3;
    println!("{}", a + b);  // 0.30000000000000004
    println!("{}", c);      // 0.3
    println!("{}", a + b == c);  // false
}
```

`f64` 有 52 位 mantissa,精度更高但仍然截断。`a + b = 0.30000000000000004`,`c = 0.3`,两者不相等。

这是浮点的本质,**不是 bug**。你不能"修"它,只能理解它、绕过它。

### 2.3 ULP(Unit in the Last Place)

**ULP** 是浮点数的最小精度单位——mantissa 末位变 1 时的数值差。对 `f32` 在 1.0 附近,ULP = 2^(-23) ≈ 1.19e-7。对 `f64` 在 1.0 附近,ULP = 2^(-52) ≈ 2.22e-16。

ULP 是判断"两个浮点数是否相等"的合理单位:

```rust
fn almost_equal(a: f64, b: f64, max_ulps: u64) -> bool {
    if a.signum() != b.signum() {
        return a == b;  // +0 == -0
    }
    let ai = a.to_bits() as i64;
    let bi = b.to_bits() as i64;
    (ai - bi).abs() <= max_ulps as i64
}

fn main() {
    let a = 0.1_f64 + 0.2;
    let b = 0.3_f64;
    println!("{}", almost_equal(a, b, 4));  // true(差几个 ULP)
}
```

`max_ulps = 4` 意味着"允许 4 个最小精度的差异"。这是工业级 float comparison 标准做法——**永远不要用 `==` 比较 float,要用 ULP 比较**。

但 ULP 比较对决定性**没用**——ULP 比较容忍差异,决定性要求零差异。决定性场景必须用整数 / fixed-point。

### 2.4 浮点的 5 个不交换律

数学里我们学过交换律、结合律、分配律。浮点里这些**都不成立**:

**1. 加法结合律不成立**:`(a + b) + c ≠ a + (b + c)`。

```rust
let a: f64 = 1e20;
let b: f64 = 1.0;
let c: f64 = -1e20;
println!("{}", (a + b) + c);  // 0(因为 1e20 + 1 round 回 1e20,然后 + (-1e20) = 0)
println!("{}", a + (b + c));  // 0(不同路径,但同结果)
// 这个例子不明显,试:
let a: f64 = 1.0;
let b: f64 = 1e-16;
let c: f64 = -1.0;
println!("{}", (a + b) + c);  // 1e-16
println!("{}", a + (b + c));  // 0(因为 b + c = -1 + 1e-16 ≈ -1,然后 a + (-1) = 0)
```

这个例子让你看清:浮点加法**怎么括号**决定结果。

**2. 乘法结合律不成立**:`(a * b) * c ≠ a * (b * c)`。理由同上,中间结果 round 不同。

**3. 分配律不成立**:`a * (b + c) ≠ a * b + a * c`。

```rust
let a: f64 = 1e20;
let b: f64 = 1.0;
let c: f64 = 1.0;
println!("{}", a * (b + c));  // 2e20
println!("{}", a * b + a * c);  // 2e20,看着一样
// 试大数:
let a: f64 = 1e308;
let b: f64 = 1e308;
let c: f64 = -1e308;
println!("{}", a * (b + c));  // 0(因为 b + c = 0)
println!("{}", a * b + a * c);  // +inf + -inf = NaN
```

**4. 加法不保证精度单调**:`a + b` 后再 `a - b` 不一定等于 `b`。

**5. 乘 0 / 除 0 不是 0**:`0 * inf = NaN`,`0 / 0 = NaN`,`x / 0 = ±inf`。

这 5 个不交换律意味着:**任何重排浮点运算的优化都改变结果**。编译器优化(O2/O3/fast-math)、SIMD 向量化、FMA fusion,都属于"重排",都改变结果。这是 cross-build / cross-platform desync 的根本来源。

### 2.5 FMA(fused multiply-add)

**FMA**(fused multiply-add)是一条 CPU 指令,把 `a * b + c` 合成一条指令,中间结果不 round。x86 Haswell(2013)+、ARM VFPv4+ 都支持。

精度上 FMA **更高**——只 round 一次(最终结果),不 round 两次(乘和加各一次)。

```rust
// 没 FMA:a * b round 一次,然后 + c 再 round 一次
// 有 FMA:a * b + c 一次 round,精度高
```

问题:**有 FMA 和没 FMA 结果不同**。

```rust
let a: f64 = 0.1;
let b: f64 = 0.2;
let c: f64 = 0.3;

// 没 FMA 实现:
let tmp = a * b;       // round
let result = tmp + c;  // round

// 有 FMA 实现:
let result = a * b + c;  // 只 round 一次
```

两个 result 可能差 1 ULP。如果 A 机器有 FMA,B 机器没 FMA,你的游戏 desync。

Rust 默认**不启用** FMA(`-C target-feature=-fma`),但如果用户机器 CPU 支持,Rustc 可能 auto-enable。要严格跨平台,显式禁用:

```toml
# Cargo.toml
[profile.release]
# 禁用 FMA
# 注意:这不是标准 Rust flag,要用 RUSTFLAGS
```

```bash
# 在 .cargo/config.toml 里:
[build]
rustflags = ["-C", "target-feature=-fma"]
```

或者更安全的做法:**不用任何可能 fuse 的代码**——避免 `a * b + c` 模式,改写成:

```rust
let tmp = a * b;
let result = tmp + c;
// 编译器可能还是 fuse(如果开了 -ffast-math 类似选项)
// 唯一安全是 -C target-feature=-fma
```

### 2.6 SSE control word(舍入模式)

x86 SSE 提供 4 种舍入模式,通过 MXCSR 控制寄存器设定:

- **Round to nearest even**(默认,最精确)
- **Round toward -inf**(向下取整)
- **Round toward +inf**(向上取整)
- **Round toward zero**(截断)

```rust
fn main() {
    let x: f64 = 0.5;
    
    unsafe {
        // 读 MXCSR
        let mut mxcsr: u32;
        std::arch::asm!("stmxcsr {0}", out(reg) mxcsr, options(nostack));
        
        // 改成 round down
        mxcsr = (mxcsr & !0x6000) | 0x2000;  // RC bits = 01
        std::arch::asm!("ldmxcsr {0}", in(reg) mxcsr, options(nostack));
    }
    
    // 现在 0.5 round 是 0(向下),不是默认的 0(银行家舍入)
}
```

不同舍入模式结果不同。游戏默认用 nearest even,但有些算法(directed rounding)需要其他模式。如果两个机器舍入模式不同,desync。

**舍入模式是 thread-local**——多线程程序里每个 thread 独立设置。如果 thread A 设 round-down,thread B 设 nearest,A 和 B 跑同样代码结果不同。这就是为什么**跨 thread 共享浮点 simulation 几乎不可能决定性**。

### 2.7 -ffast-math:编译器的"破坏"

GCC / Clang 提供 `-ffast-math`,这开关打开后编译器假设浮点满足数学律(交换律、结合律),允许激进重排。结果:**快但不确定**。

Rust 没有 `-ffast-math` 直接对应,但有等价物:

```bash
# 启用类似 fast-math 的优化
RUSTFLAGS="-C llvm-args=-fast-math" cargo build --release
# 或者具体:
RUSTFLAGS="-C target-feature=+fast-math" cargo build --release
```

但 Rust 默认**不启用**——这是 Rust 设计的安全选择。如果你显式开 fast-math,你对自己负责。

`-ffast-math` 打开后,编译器会:

1. **假设没有 NaN / Inf**。`x != x` 永远 false(原本 NaN 检测失效)。
2. **假设没有 signed zero**。`0.0 == -0.0`(原本两个数 bits 不同但相等)。
3. **重排浮点运算**(违反结合律)。
4. **向量化 reduction**(把循环 `sum += arr[i]` 拆成 4 个 partial sum,最后合并)。
5. **假设 finite only**。数学函数可以简化。

每条都破坏决定性。**生产游戏永远不开 fast-math**,除非你 100% 确定不要决定性(比如纯单机游戏,玩家在自己机器上跑,无所谓 desync)。

### 2.8 NaN payload

IEEE 754 规定 NaN 有 payload——sign + exponent(全 1)+ mantissa(非零,第一位表示 quiet / signaling)。不同来源的 NaN payload 不同:

```rust
let nan1 = f64::NAN;                    // 默认 quiet NaN
let nan2 = 0.0 / 0.0;                   // 不同 payload
let nan3 = f64::INFINITY - f64::INFINITY;  // 又不同

// bits 不同:
println!("{:x}", nan1.to_bits());  // 7ff8000000000000
println!("{:x}", nan2.to_bits());  // fff8000000000000(sign 不同)
```

如果游戏 state 包含 NaN(比如未初始化的 float),payload 不同 = state hash 不同 = 假 desync 报警。

防御:**永远检查 NaN,绝不让 NaN 进入 state**。

```rust
fn check_clean(state: &State) {
    for &v in &state.floats {
        assert!(!v.is_nan(), "NaN detected in state!");
        assert!(v.is_finite(), "Inf detected in state!");
    }
}
```

### 2.9 32-bit vs 64-bit:x87 vs SSE

x87 是 80-bit extended precision(老 x86),SSE 是 32/64-bit 标准。同一份代码:

- x87 模式:中间结果 80-bit,精度更高,round 时不同
- SSE 模式:中间结果 32/64-bit,标准精度

旧 Linux 默认 x87,新 Linux / Windows 默认 SSE。Rust 强制 SSE2(因为 Rust 要求 i686+ SSE2),所以 Rust 程序跨 32 / 64-bit 一致。但 C++ 程序如果在 32-bit Linux 编译,可能用 x87,跨 32/64-bit desync。

### 2.10 ARM vs x86

ARM 的 NEON / SVE 浮点和 x86 SSE / AVX 不完全一致:

- **rounding 默认**:都是 nearest even,但 ARM 有特殊指令处理不同
- **denormal 处理**:ARM v7 默认 flush-to-zero(把 denormal 当 0),x86 默认正常处理
- **FMA**:ARMv8 默认有 FMA,x86 Haswell+ 才有

跨 ARM(Mac M1 / 手机)和 x86(PC)的游戏 desync 极常见。**只有完全软件浮点才能保证跨 ISA 决定性**。

### 2.11 不同 OS 的 libm 差异

`sin` / `cos` / `exp` / `log` 这些 transcendental 函数在不同 OS 的 libm 实现不同:

- **glibc**(Linux):高精度,SIMD 优化
- **macOS libm**:Apple 自己实现,精度更高但算法不同
- **Windows UCRT**:Microsoft 实现,精度和 glibc 略不同

```rust
let x: f64 = 1.0;
let s = x.sin();  // 调 libm
// Linux 和 macOS 结果可能差 1 ULP
```

跨 OS 决定性必须**自己实现 transcendental 函数**,不用 libm。Rust 生态有 [`micromath`](https://github.com/NeoBirth/micromath) crate 提供软件实现。或者用查找表 + 多项式拟合(游戏引擎标准做法)。

### 2.12 编译器差异:gcc / clang / msvc

同一份 C++ 代码,gcc / clang / msvc 编译,浮点结果可能不同。理由:

1. **不同的优化策略**。gcc 喜欢 FMA,clang 不一定,msvc 几乎不。
2. **不同的 vectorization**。gcc auto-vectorize 激进,msvc 保守。
3. **不同的 intrinsics 实现**。`_mm_mul_ps` 在不同编译器中间表示不同。

这就是为什么《星际争霸》用**特定编译器**编译所有 client build——所有玩家用同一份 binary,保证 bit-exact。这不可行 for indie,所以 indie 多人游戏要么单平台,要么用 lockstep 之外的 netcode(rollback / client-server authority)。

## 3 · 跨平台决定性策略

到这里你绝望了:**浮点全是坑,跨平台不可能决定性**。这是对的——**用硬件浮点,跨平台决定性几乎不可能**。但有三条出路。

### 3.1 策略 1:Fixed-point(整数模拟小数)

**Fixed-point** 是经典解法——用整数表示小数,自己管小数点。

```rust
// 16.16 fixed-point:高 16 位整数,低 16 位小数
#[derive(Copy, Clone, PartialEq, Eq, Debug)]
struct Fixed32(i32);

impl Fixed32 {
    const FRAC_BITS: u32 = 16;
    const FRAC_SCALE: i32 = 1 << Self::FRAC_BITS;  // 65536
    
    fn from_int(x: i32) -> Self {
        Self(x << Self::FRAC_BITS)
    }
    
    fn from_f32(x: f32) -> Self {
        Self((x * Self::FRAC_SCALE as f32) as i32)
    }
    
    fn to_f32(self) -> f32 {
        self.0 as f32 / Self::FRAC_SCALE as f32
    }
    
    fn add(self, other: Self) -> Self {
        Self(self.0 + other.0)
    }
    
    fn sub(self, other: Self) -> Self {
        Self(self.0 - other.0)
    }
    
    fn mul(self, other: Self) -> Self {
        // i32 * i32 可能溢出,用 i64 中间值
        let result = (self.0 as i64 * other.0 as i64) >> Self::FRAC_BITS;
        Self(result as i32)
    }
    
    fn div(self, other: Self) -> Self {
        // 先 shift 再除,避免丢精度
        let result = ((self.0 as i64) << Self::FRAC_BITS) / other.0 as i64;
        Self(result as i32)
    }
}
```

整数运算跨平台完全一致——这就是 fixed-point 的决定性来源。

| 维度 | f32 | Fixed32 |
|---|---|---|
| 范围 | ±1e38 | ±32768 |
| 精度 | 7 有效位 | 5 有效位(16.16) |
| 加法 | round | 精确 |
| 乘法 | round | 精确(中间 64-bit) |
| 除法 | round | 精确(中间 64-bit) |
| sqrt / sin / cos | hardware | 自己实现(查找表) |
| 跨平台 | 难 | 易 |

经典游戏用 fixed-point:

- **《Doom》**(1993):16.16 fixed-point,所有 platform 一致。
- **《星际争霸》**:32-bit integer 模拟。
- **《Command & Conquer》**:fixed-point。

现代游戏物理引擎通常用 float(性能 / 精度权衡),但 esport 游戏(《英雄联盟》《Dota》)依然 fixed-point 保证跨平台一致。

### 3.2 策略 2:Software float(自己实现浮点)

如果你需要 f32 的范围但跨平台决定性,可以**自己实现 IEEE 754**——用整数模拟浮点运算。

```rust
fn soft_f32_add(a: u32, b: u32) -> u32 {
    // 完整 IEEE 754 add 实现,~200 行
    // 拆 sign / exponent / mantissa
    // 对齐 exponent
    // 加 mantissa
    // normalize + round
    // 重新打包
    todo!()
}
```

完整实现参考:[SoftFloat](https://github.com/ucb-bar/berkeley-softfloat-3),UC Berkeley 出的开源 C 库。Rust binding:[softfloat-sys](https://crates.io/crates/softfloat-sys)。

性能代价:software float 比 hardware 慢 10-100 倍。但决定性完美——所有平台 bit-exact。

### 3.3 策略 3:限定平台

第三条路:**放弃跨平台决定性,只支持一个平台**。

很多 indie 单机游戏走这条——Steam 上 90% 玩家 Windows,你只支持 Windows,决定性问题大幅简化(同编译器、同 libm、同 CPU ISA)。

但要小心:

- **Debug vs Release**:同一编译器不同优化级别,仍可能 desync。要测试。
- **不同 CPU**:Intel 和 AMD 的 microcode 实现可能不同。极少数 desync 来自这。
- **不同 Windows 版本**:Win10 和 Win11 的 UCRT 可能略不同。

### 3.4 三条策略对比

| 策略 | 决定性强度 | 性能 | 复杂度 | 适合场景 |
|---|---|---|---|---|
| Fixed-point | 完美 | 高(int 运算) | 中(自己写 math) | esports / 老式游戏 |
| Software float | 完美 | 低(10-100x 慢) | 高(实现 IEEE 754) | 极严格 netcode |
| 限定平台 | 中(同平台 desync 风险) | 高 | 低 | 单机 indie |
| 硬件 float + 不严格 | 弱(desync 偶发) | 最高 | 最低 | 不需要 replay / netcode 的游戏 |

Casey 在 HH Day 580 时代选第 4 个——单机游戏,玩家自己玩,偶尔 desync 无所谓。如果你想加 netcode 或 replay,要选 1 或 2。

## 4 · RNG 决定性

到这里都是浮点。但 RNG 也有决定性问题——**不决定性的 RNG 是 desync 的隐形来源**。

### 4.1 为什么 std::rand / rand::thread_rng() 都不能用

新手写游戏,常用:

```rust
use rand::Rng;
let dice = rand::thread_rng().gen_range(0..6);
```

这在跨平台 / 跨运行 / 跨线程下**完全不确定**。原因:

1. **`thread_rng()` 用 thread-local entropy**。entropy 来自 OS(/dev/urandom on Linux, RtlGenRandom on Windows),每次跑都不同。
2. **`thread_rng()` 内部是 ChaCha**,seed 来自 OS。同 thread 同 process 不同时刻,seed 不同。
3. **多个 thread 同时调 thread_rng()**,调度顺序不确定,即便每个 thread 独立也跨 thread 不决定。

工业游戏**绝不**用 std RNG。所有 RNG 必须是**显式 seeded + 显式 state + 显式调用顺序**。

### 4.2 RNG 决定性的三个原则

**原则 1:显式 seed**。所有 RNG 由一个 u64 / u128 seed 初始化,这个 seed 来自 replay 文件或网络协议,不来自 OS。

```rust
let mut rng = MyRng::new(seed_from_replay_file);
let dice = rng.gen_range(0..6);  // 完全决定
```

**原则 2:线性调用顺序**。所有 RNG 调用按固定顺序——同帧同逻辑路径下,调 RNG N 次,第 K 次结果相同。

**原则 3:无 thread-shared RNG**。RNG state 是 per-simulation 的,不跨 thread 共享。如果多 thread simulation,每个 thread 自己一份 RNG,seed 由主 RNG 派生。

### 4.3 LCG(Linear Congruential Generator)

最简单的 RNG——LCG。公式:

```
state_{n+1} = (a * state_n + c) mod m
output_n = state_n
```

`a`、`c`、`m` 是常数。Numerical Recipes 推荐:`a = 1664525, c = 1013904223, m = 2^32`。

Rust 实现:

```rust
struct Lcg {
    state: u32,
}

impl Lcg {
    const A: u32 = 1664525;
    const C: u32 = 1013904223;
    
    fn new(seed: u32) -> Self {
        Self { state: seed }
    }
    
    fn next_u32(&mut self) -> u32 {
        self.state = self.state.wrapping_mul(Self::A).wrapping_add(Self::C);
        self.state
    }
    
    fn gen_range(&mut self, lo: u32, hi: u32) -> u32 {
        let range = hi - lo;
        lo + self.next_u32() % range
    }
}
```

LCG 优点:**极简、极快、跨平台 bit-exact**。缺点:**统计性质差**——低位周期短,通不过 TestU01 / BigCrush 测试套件。**不能用于加密**(预测容易)。

游戏 simulation 里 LCG 通常够用——你要的是"看起来随机 + 跨平台一致",不是密码学级别随机。

### 4.4 Xoshiro / xorshift

**Xoshiro**(Sebastiano Vigna, 2018)是 xorshift 家族的现代版。状态 256-bit(4 × u64),输出 64-bit,周期 2^256 - 1。

```rust
struct Xoshiro256Plus {
    state: [u64; 4],
}

impl Xoshiro256Plus {
    fn new(seed: [u64; 4]) -> Self {
        Self { state: seed }
    }
    
    fn next_u64(&mut self) -> u64 {
        let result = self.state[0].wrapping_add(self.state[3]);
        
        let t = self.state[1] << 17;
        self.state[2] ^= self.state[0];
        self.state[3] ^= self.state[1];
        self.state[1] ^= self.state[2];
        self.state[0] ^= self.state[3];
        self.state[2] ^= t;
        self.state[3] = self.state[3].rotate_left(45);
        
        result
    }
}
```

Xoshiro 通过 BigCrush 测试,统计性质好,速度快。Rust [`rand_xoshiro`](https://crates.io/crates/rand_xoshiro) crate 提供。

### 4.5 PCG(Permuted Congruential Generator)

**PCG**(Melissa O'Neill, 2014)是现代 RNG 的代表作——简单 LCG 内核 + permutation 输出函数,统计性质优秀,内存小,跨平台一致。

论文:[PCG, A Family of Better Random Number Generators](https://www.pcg-random.org/pdf/hmc-cs-2014-0905.pdf)

O'Neill 的洞察:**LCG 本身统计性质不好(低位周期短),但 LCG 的高位其实挺好**。如果对 LCG 状态做一个 permutation(把高位 mix 到低位),输出统计性质大幅提升。

PCG32 完整算法:

```
state: u64(64-bit internal state)
inc:   u64(odd number, stream selector)

next():
    oldstate = state
    state = oldstate * 6364136223846793005 + inc   // LCG step
    xorshifted = ((oldstate >> 18) ^ oldstate) >> 27  // shift-xor mix
    rot = oldstate >> 59                            // rotation amount from top 5 bits
    output = (xorshifted >> rot) | (xorshifted << ((-rot) & 31))  // 32-bit output
```

参数解释:

- **multiplier 6364136223846793005**:O'Neill 推荐(也是 Knuth 推荐的 LCG multiplier)
- **shift 18 + shift 27**:mix 状态,让高位影响低位
- **rot from top 5 bits**:从 state 最高 5 位取 rotation amount,让输出"变化更频繁"

完整 Rust 实现:

```rust
/// PCG32 - 32-bit output, 64-bit state
/// From O'Neill 2014: https://www.pcg-random.org/
#[derive(Copy, Clone, Debug)]
pub struct Pcg32 {
    state: u64,
    inc: u64,
}

impl Pcg32 {
    const MULTIPLIER: u64 = 6364136223846793005;
    const INCREMENT: u64 = 1442695040888963407;
    
    /// 创建一个 PCG32,seed 和 stream 都来自调用方
    pub fn new(seed: u64, stream: u64) -> Self {
        let mut rng = Self { state: 0, inc: (stream << 1) | 1 };  // inc must be odd
        rng.next_u32();  // 先跑一次,内部 state 初始化
        rng.state = rng.state.wrapping_add(seed);
        rng.next_u32();
        rng
    }
    
    /// 默认 stream
    pub fn from_seed(seed: u64) -> Self {
        Self::new(seed, Self::INCREMENT)
    }
    
    pub fn next_u32(&mut self) -> u32 {
        let oldstate = self.state;
        
        // LCG step
        self.state = oldstate
            .wrapping_mul(Self::MULTIPLIER)
            .wrapping_add(self.inc);
        
        // Output function: xorshift + rotation
        let xorshifted = (((oldstate >> 18) ^ oldstate) >> 27) as u32;
        let rot = (oldstate >> 59) as u32;
        
        (xorshifted >> rot) | (xorshifted.wrapping_shl((!rot).wrapping_add(1) & 31))
    }
    
    pub fn next_u64(&mut self) -> u64 {
        // 两个 32-bit 拼一个 64-bit
        let high = self.next_u32() as u64;
        let low = self.next_u32() as u64;
        (high << 32) | low
    }
    
    /// 生成 [lo, hi) 范围的 u32,避免 modulo bias
    pub fn gen_range(&mut self, lo: u32, hi: u32) -> u32 {
        let range = hi.wrapping_sub(lo);
        assert!(range > 0);
        
        // Lemire's debias method
        let mut mult = (self.next_u32() as u64) * (range as u64);
        let mut low = mult as u32;
        if low < range {
            let thresh = range.wrapping_neg() % range;
            while low < thresh {
                mult = (self.next_u32() as u64) * (range as u64);
                low = mult as u32;
            }
        }
        
        lo + (mult >> 32) as u32
    }
    
    /// 生成 [0, 1) 的 f32
    pub fn gen_f32(&mut self) -> f32 {
        // 23 bits of randomness → [0, 1)
        let bits = self.next_u32() >> 9;  // top 23 bits
        bits as f32 / (1u32 << 23) as f32
    }
    
    /// 生成 [0, 1) 的 f64
    pub fn gen_f64(&mut self) -> f64 {
        let bits = self.next_u64() >> 11;  // top 53 bits
        bits as f64 / (1u64 << 53) as f64
    }
}
```

PCG 优点:

| 维度 | PCG32 | LCG | Xoshiro256+ |
|---|---|---|---|
| State 大小 | 16 bytes | 4 bytes | 32 bytes |
| 周期 | 2^64 | 2^32 | 2^256 - 1 |
| 输出大小 | 32-bit | 32-bit | 64-bit |
| BigCrush 测试 | 通过 | 失败(低位) | 通过 |
| 跨平台 bit-exact | 是 | 是 | 是 |
| 速度 | 快 | 最快 | 快 |
| 内存 | 小 | 最小 | 大 |

PCG32 是 indie 游戏的 sweet spot——够随机、够小、够快、跨平台完美一致。我推荐所有 Rust 游戏项目用 PCG32。

### 4.6 PCG 的 stream 概念

PCG 的 `inc` 字段(必须是 odd)是 **stream selector**——同 seed 不同 stream 的 RNG 序列完全独立。这意味着你可以从同一 master seed 派生多个独立 RNG:

```rust
let master_seed = 0xDEADBEEF;
let physics_rng = Pcg32::new(master_seed, 1);      // stream 1
let ai_rng = Pcg32::new(master_seed, 2);           // stream 2
let particle_rng = Pcg32::new(master_seed, 3);     // stream 3

// 物理、AI、粒子各自独立 RNG,但都源自同一 seed
// 这样 replay 文件只存 master_seed,所有子系统一致重建
```

这是 PCG 的工程优势——**单一 seed 派生多 RNG,跨子系统无干扰**。LCG / Xoshiro 没这个原生概念,要手撸。

## 5 · Hash-based desync detection

到这里我们有了决定性 RNG 和 fixed-point / software float 的策略。但你**怎么知道** desync 发生了?玩家 A 和 B 同时玩 lockstep,两边 state 是否相同?

答案:**每帧 hash game state,广播 hash,比对**。

### 5.1 CRC32 / xxHash / FNV 三选一

hash 函数选择:

| hash | 速度 | collision 概率 | 决定性 | 推荐 |
|---|---|---|---|---|
| CRC32 | 中 | 中(32-bit) | 跨平台 | 简单 |
| xxHash | 极快 | 低(32 / 64) | 跨平台 | **推荐** |
| FNV | 慢 | 中 | 跨平台 | 极简实现 |
| SHA-256 | 极慢 | 极低 | 跨平台 | 加密用,游戏太慢 |
| MD5 | 中 | 已破解 | 跨平台 | 不推荐(碰撞) |

游戏用 **xxHash32 或 xxHash64**——快、低碰撞、跨平台一致。Rust [`xxhash-rust`](https://crates.io/crates/xxhash-rust) crate。

### 5.2 完整 desync detection 系统

```rust
use xxhash_rust::xxh3::xxh3_64;

#[derive(Serialize)]
struct GameState {
    frame: u64,
    player_pos: [f32; 3],
    entities: Vec<Entity>,
    // ...
}

impl GameState {
    fn hash(&self) -> u64 {
        // 把 state 序列化成字节,然后 hash
        let mut buf = Vec::new();
        bincode::serialize_into(&mut buf, self).unwrap();
        xxh3_64(&buf)
    }
}

// 主循环
let mut state = GameState::new();
loop {
    state.frame += 1;
    update(&mut state);
    
    let hash = state.hash();
    println!("frame {} hash: {:016x}", state.frame, hash);
    
    // 客户端-客户端 desync detect:
    // 每帧广播 hash 给对方,对比
    network.broadcast_hash(state.frame, hash);
    if let Some(other_hash) = network.recv_hash(state.frame) {
        if other_hash != hash {
            panic!("desync at frame {}! local={:016x} remote={:016x}", 
                state.frame, hash, other_hash);
        }
    }
}
```

注意 serialization 必须跨平台一致——`bincode` 默认 little-endian,跨平台一致。但如果 state 包含 `HashMap`,**iteration 顺序跨平台不一致**(hash 随机化)——必须用 `BTreeMap`(sorted)或 `IndexMap`(insertion order)。

### 5.3 desync 调试技巧

desync 报警后怎么找原因?**二分查找**。

```rust
// 记录最近 60 帧 state hash
let mut hash_history: VecDeque<(u64, u64)> = VecDeque::with_capacity(60);

loop {
    state.frame += 1;
    update(&mut state);
    let hash = state.hash();
    hash_history.push_back((state.frame, hash));
    if hash_history.len() > 60 {
        hash_history.pop_front();
    }
    
    if desync_detected {
        // dump 历史 hash
        for (frame, h) in &hash_history {
            log::info!("frame {}: {:016x}", frame, h);
        }
        // 找第一个不一致的 frame
    }
}
```

二分 log 输出 → 找第一个 frame A 和 B hash 不同 → 这 frame 的 update 是 desync 来源。然后逐步 print 这 frame 的 state 子结构,直到定位**哪个字段** desync。

工业级 desync 调试工具:把 state 分子系统 hash(player hash、entities hash、AI hash 等),desync 时立刻知道哪个子系统错。

## 6 · Replay 系统

到这里所有基础设施都讲完了。我们看**Replay 系统**——决定性的最重要应用。

### 6.1 三种 replay 架构

| 架构 | 记录什么 | 体积 | 完美重建条件 | 适合 |
|---|---|---|---|---|
| Input-only | 仅玩家输入 | 极小(KB/分钟) | 完美决定性 simulation | esports / lockstep |
| State-snapshot | 完整 state(定期 snapshot) | 大(MB/分钟) | 无 | 单机、不严格决定性 |
| Hybrid | Snapshot + 输入 | 中 | 完美决定性 + snapshot 加速 | 推荐生产用 |

### 6.2 Input-only replay

**Input-only** 记录每帧每个玩家的输入。回放时:

```
load initial_state from save file
load input_log
for frame in 0..N:
    apply inputs[frame]
    state = simulate(state, dt)
```

如果 simulation 决定,完美重建。

```rust
#[derive(Serialize, Deserialize, Copy, Clone)]
struct PlayerInput {
    move_x: i8,    // -1, 0, 1
    move_y: i8,
    jump: bool,
    attack: bool,
}

struct Replay {
    initial_seed: u64,
    initial_state_hash: u64,
    inputs: Vec<PlayerInput>,  // 每帧一个
}

impl Replay {
    fn record(state: &GameState, inputs: &[PlayerInput]) -> Self {
        Self {
            initial_seed: state.rng_seed,
            initial_state_hash: state.hash(),
            inputs: inputs.to_vec(),
        }
    }
    
    fn playback(&self, initial_state: GameState) -> Vec<GameState> {
        let mut state = initial_state;
        state.rng = Pcg32::from_seed(self.initial_seed);
        
        let mut history = Vec::with_capacity(self.inputs.len());
        for input in &self.inputs {
            state.apply_input(*input);
            state = simulate(state, FIXED_DT);
            history.push(state.clone());
        }
        history
    }
}
```

Input-only 优点:**体积小**——60 FPS × 30 分钟 × 8 字节/输入 = 864 KB。可以分享、上传、做精彩集锦。

缺点:**要求完美决定性**。任何 desync 让 replay 走偏。

### 6.3 State-snapshot replay

**State-snapshot** 定期保存完整 state(比如每秒一次)。

```rust
struct Replay {
    snapshots: Vec<(u64 frame, GameState)>,  // (frame, state at frame)
}

impl Replay {
    fn record(state: &GameState, frame: u64) -> Self {
        let mut snapshots = Vec::new();
        // 每秒(60 帧)snapshot
        if frame % 60 == 0 {
            snapshots.push((frame, state.clone()));
        }
        Self { snapshots }
    }
    
    fn playback_at(&self, target_frame: u64) -> GameState {
        // 找最近的 snapshot
        let snapshot = self.snapshots.iter()
            .rev()
            .find(|(f, _)| *f <= target_frame)
            .unwrap();
        
        snapshot.1.clone()  // 直接返回 snapshot state
    }
}
```

优点:**不需要决定性**——直接 dump state,任何游戏都能用。

缺点:**体积大**——每个 state 几 KB,每秒一个,30 分钟 = 1800 snapshots × 几 KB = 几 MB 到几十 MB。给玩家分享不友好。

### 6.4 Hybrid replay(推荐)

**Hybrid** 结合两者——定期 snapshot 加速 seek,input 之间用 simulation 推进。

```rust
struct Replay {
    initial_seed: u64,
    initial_state: GameState,
    inputs: Vec<PlayerInput>,
    checkpoints: Vec<(u64 frame, GameState)>,  // 每 5 秒 snapshot
}

impl Replay {
    fn playback_at(&self, target_frame: u64) -> GameState {
        // 找最近的 checkpoint
        let (cp_frame, mut state) = self.checkpoints.iter()
            .rev()
            .find(|(f, _)| *f <= target_frame)
            .map(|(f, s)| (*f, s.clone()))
            .unwrap_or((0, self.initial_state.clone()));
        
        // 从 checkpoint 模拟到 target
        for frame in cp_frame..target_frame {
            state.apply_input(self.inputs[frame as usize]);
            state = simulate(state, FIXED_DT);
        }
        
        state
    }
}
```

优点:

- **体积小**——inputs 占主导,checkpoint 偶尔几个
- **seek 快**——直接 jump 到 checkpoint,不用从头模拟
- **决定性不严格**——即便 simulation 偶有 desync,checkpoint 校正

工业级 replay 系统都用 hybrid。Casey 在 HH Day 400+ 加的 replay 就是 hybrid。

### 6.5 Replay 录制时的 desync 防御

Replay 录制时,如果 simulation 不严格决定性,replay 走偏。防御:

```rust
struct Replay {
    // ...
    checksums: Vec<u64>,  // 每帧 state hash,回放时校验
}

impl Replay {
    fn playback_check(&self) {
        let mut state = self.initial_state.clone();
        for (frame, input) in self.inputs.iter().enumerate() {
            state.apply_input(*input);
            state = simulate(state, FIXED_DT);
            
            let actual_hash = state.hash();
            let expected_hash = self.checksums[frame];
            if actual_hash != expected_hash {
                log::error!("replay desync at frame {}: expected {:016x} got {:016x}",
                    frame, expected_hash, actual_hash);
                break;
            }
        }
    }
}
```

回放时每帧 hash 校验。desync 立刻报警,知道哪一帧开始走偏。这是生产 replay 系统的标配。

## 7 · Sort 稳定性 + iteration 顺序

到这里都是 simulation 内部。但有一类 desync 来源经常被忽略:**集合的 iteration 顺序**。

### 7.1 HashMap 是非决定的

Rust `std::collections::HashMap` 用 SipHash,**默认启用 random seed**(防 hash collision DoS 攻击)。这意味着同一个 HashMap 在两次运行里 iteration 顺序不同。

```rust
use std::collections::HashMap;

let mut m = HashMap::new();
m.insert("apple", 1);
m.insert("banana", 2);
m.insert("cherry", 3);

for (k, v) in &m {
    println!("{} {}", k, v);
}
// 每次跑输出顺序不同!
```

如果 simulation 用 HashMap 迭代做计算(比如"对所有 entity 应用 force"),iteration 顺序不同 → 浮点累加顺序不同 → 结果 desync。

### 7.2 决定性集合

替代方案:

| 集合 | 决定性 | 适合 |
|---|---|---|
| `BTreeMap` | 是(sorted by key) | 需要按 key 顺序 |
| `IndexMap` | 是(insertion order) | 需要 insertion 顺序 |
| `IndexSet` | 是 | 同上 |
| `Vec<(K, V)>` | 是 | 极简,自己 linear search |
| `HashMap` | 否 | 不要用在 simulation |

```rust
use indexmap::IndexMap;

let mut m = IndexMap::new();
m.insert("apple", 1);
m.insert("banana", 2);
m.insert("cherry", 3);

for (k, v) in &m {
    println!("{} {}", k, v);
}
// 永远按 insertion 顺序输出 apple, banana, cherry
```

### 7.3 Sort 稳定性

Rust `slice::sort_by` 是 **stable sort**(同 key 元素保持原顺序)。`sort_unstable_by` 是 **unstable**(同 key 元素顺序可能变)。

```rust
let mut v = vec![(1, "a"), (2, "b"), (1, "c"), (2, "d")];

v.sort_by_key(|(k, _)| *k);
// [(1, "a"), (1, "c"), (2, "b"), (2, "d")]  ← stable,1 内部 a/c 顺序保留

v.sort_unstable_by_key(|(k, _)| *k);
// [(1, "a"), (1, "c"), (2, "b"), (2, "d")] 或 [(1, "c"), (1, "a"), ...]  ← 不保证
```

对决定性:**用 stable sort**。Unstable sort 跨运行 / 跨平台 / 跨 Rust 版本可能不同,desync 来源。

```rust
// 决定性排序
entities.sort_by(|a, b| a.id.cmp(&b.id));

// 不要:
// entities.sort_unstable_by(...)  // 不决定
```

`sort_unstable` 性能更好(快几倍),但**永远不要在 simulation 内部用**。

## 8 · Float comparison tolerance

到这里你可能会问:"我比较两个 float 用什么 tolerance?"这本身是个大话题。

### 8.1 三种 comparison 模式

```rust
// 1. 严格相等 - 几乎永远错(除非 hash key)
a == b

// 2. 绝对 tolerance - 适合 [0, 1] 范围
(a - b).abs() < 1e-6

// 3. 相对 tolerance - 适合任意范围
(a - b).abs() < 1e-6 * a.abs().max(b.abs())

// 4. ULP-based - 最严谨
(a.to_bits() as i64 - b.to_bits() as i64).abs() < 4
```

游戏开发一般用绝对 tolerance(因为游戏数值通常在合理范围):

```rust
const EPS: f32 = 1e-5;

fn almost_equal(a: f32, b: f32) -> bool {
    (a - b).abs() < EPS
}
```

但**决定性场景不用 tolerance**——用整数 / fixed-point,tolerance 是为了"显示和判断",不是为了 simulation 一致性。

### 8.2 显示层的 tolerance vs simulation 层的 strict

注意区分两层:

- **Simulation 层**:必须 bit-exact。用 fixed-point / software float / 禁止 fast-math。
- **Display 层**:可以 tolerance。玩家看不出 0.00001 米差异。

```rust
// Simulation:用 fixed-point,bit-exact
let pos_sim = Fixed32::from_int(100);  // 整数表示

// Display:转 f32,tolerance 比较
let pos_display = pos_sim.to_f32();
if almost_equal(pos_display, target_pos) {
    // ...
}
```

这两层分离,既保证决定性,又有灵活的判断逻辑。

## 9 · Box2D / Rapier 决定性考虑

物理引擎是 desync 高发区。我们看主流物理引擎的决定性状况。

### 9.1 Box2D 决定性

Box2D(Erin Catto)是工业级 2D 物理引擎,**设计上决定性**:

- **使用 f32**,所有平台一致(假设无 fast-math)
- **broadphase 用 dynamic AABB tree**,插入顺序确定 → tree 结构确定 → iteration 顺序确定
- **solver 用 Sequential Impulse**,迭代次数固定,无随机
- **contact manifold** 提取算法确定

但有几个 gotcha:

1. **user callback 顺序**:Box2D 的 `ContactListener` 在 contact 解决时调用,调用顺序跨平台一致(因为 broadphase 确定)。但**用户的 callback 内部代码可能不决定**(比如用 thread_rng)。
2. **TOI solver**:Continuous Collision Detection 用 substep,substep 数量基于物体速度,速度跨平台一致则 substep 一致。
3. **`b2World::Step(dt, velocityIter, positionIter)`**:`dt`、iteration 数量必须跨平台一致。

总评:**Box2D 跨平台决定性 OK**(相同 hardware float + 禁用 fast-math)。

### 9.2 Rapier(Rust)决定性

[Rapier](https://github.com/dimforge/rapier) 是 Rust 生态的物理引擎,设计参考 Box2D / Bullet。

Rapier 决定性状况:

- **跨 Rust 版本**:可能不决定,因为 Rust 标准库内部集合排序可能改。
- **跨 platform**:同 Rust 版本,跨平台决定(假设硬件浮点一致)。
- **跨 hardware float**:不保证(同 Box2D)。

Rapier 的 [determinism docs](https://rapier.rs/docs/user_guides/javascript/determinism) 明确说:

> Rapier is deterministic on a fixed set of dependencies. But it does not guarantee cross-version determinism.

也就是说,**同 Rapier 版本 + 同 Rust 版本 + 同 build flag**,跨平台一致。版本变就重新验证。

### 9.3 决定性物理引擎的最佳实践

如果你需要 netcode / replay 物理决定性:

1. **锁定 Rapier 版本**(`Cargo.lock`)。
2. **锁定 Rust 版本**(`rust-toolchain.toml`)。
3. **固定 timestep**(详见 Day 99 / Day 100,固定 dt 而不是 wall clock dt)。
4. **固定 iteration 数量**(不要让 Rapier 自适应 iteration)。
5. **broadphase 用户代码不要 RNG**。
6. **所有 user callback 决定性**(不调 thread_rng,不读 SystemTime)。
7. **CI 跑跨平台 desync 测试**(Linux / Windows / macOS 跑同样场景,hash state,对比)。

```rust
// rust-toolchain.toml
[toolchain]
channel = "1.76.0"
components = ["rustfmt", "clippy"]
targets = ["x86_64-unknown-linux-gnu", "x86_64-pc-windows-msvc", "x86_64-apple-darwin"]
```

```rust
// Cargo.lock 提交到 git,锁定所有 transitive deps 版本
// .gitignore 不要忽略 Cargo.lock
```

## 10 · 在你 HH 项目里实践

到这里理论讲完,我们要落地。下面是给 HH 项目加 replay 系统的完整步骤。

### 10.1 步骤 1:加 PCG RNG

`Cargo.toml`:

```toml
[dependencies]
serde = { version = "1", features = ["derive"] }
bincode = "1"
xxhash-rust = { version = "0.8", features = ["xxh3"] }
# 注意:不用 rand crate,我们自己写 PCG
```

`src/rng.rs`:

```rust
use serde::{Serialize, Deserialize};

#[derive(Copy, Clone, Debug, Serialize, Deserialize)]
pub struct Pcg32 {
    state: u64,
    inc: u64,
}

impl Pcg32 {
    const MULTIPLIER: u64 = 6364136223846793005;
    
    pub fn new(seed: u64, stream: u64) -> Self {
        let mut rng = Self { state: 0, inc: (stream << 1) | 1 };
        rng.next_u32();
        rng.state = rng.state.wrapping_add(seed);
        rng.next_u32();
        rng
    }
    
    pub fn from_seed(seed: u64) -> Self {
        Self::new(seed, 1442695040888963407)
    }
    
    pub fn next_u32(&mut self) -> u32 {
        let oldstate = self.state;
        self.state = oldstate
            .wrapping_mul(Self::MULTIPLIER)
            .wrapping_add(self.inc);
        
        let xorshifted = (((oldstate >> 18) ^ oldstate) >> 27) as u32;
        let rot = (oldstate >> 59) as u32;
        
        (xorshifted >> rot) | (xorshifted.wrapping_shl((!rot).wrapping_add(1) & 31))
    }
    
    pub fn gen_range(&mut self, lo: u32, hi: u32) -> u32 {
        let range = hi - lo;
        let mut mult = (self.next_u32() as u64) * (range as u64);
        let mut low = mult as u32;
        if low < range {
            let thresh = range.wrapping_neg() % range;
            while low < thresh {
                mult = (self.next_u32() as u64) * (range as u64);
                low = mult as u32;
            }
        }
        lo + (mult >> 32) as u32
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn pcg32_deterministic() {
        let mut a = Pcg32::from_seed(42);
        let mut b = Pcg32::from_seed(42);
        for _ in 0..1000 {
            assert_eq!(a.next_u32(), b.next_u32());
        }
    }
    
    #[test]
    fn pcg32_known_values() {
        // 已知 PCG32 输出(从 C reference impl 拿)
        let mut rng = Pcg32::from_seed(42);
        let first = rng.next_u32();
        // 这里填 C impl 的输出
        // assert_eq!(first, 0x...);
    }
}
```

### 10.2 步骤 2:用 PCG 替换所有随机调用

```rust
// 替换前
use rand::Rng;
fn spawn_particle(state: &mut State) {
    let angle = rand::thread_rng().gen_range(0.0..2.0 * PI);  // 不决定
    // ...
}

// 替换后
fn spawn_particle(state: &mut State) {
    let angle = (state.particle_rng.gen_range(0, 360) as f32).to_radians();
    // 用 u32 派生 f32,跨平台一致
}
```

注意:从 u32 转 f32 用整数计算(`angle as f32 * 2 * PI / 360.0`),不用 `gen_f32()`——因为 f32 计算跨平台可能不决定(虽然实际大概率一致,但保险起见用 int 路径)。

### 10.3 步骤 3:替换 HashMap

```rust
// 替换前
use std::collections::HashMap;
let entities: HashMap<EntityId, Entity> = HashMap::new();

// 替换后
use indexmap::IndexMap;
let entities: IndexMap<EntityId, Entity> = IndexMap::new();
// 或者按 id sorted
// 或者直接 Vec<Entity>,linear search(对小数量更快)
```

### 10.4 步骤 4:加 state hash

```rust
use xxhash_rust::xxh3::xxh3_64;
use serde::Serialize;

#[derive(Serialize)]
pub struct GameState {
    pub frame: u64,
    pub player_pos: [f32; 3],
    pub entities: Vec<Entity>,
    pub rng: Pcg32,
    // ...
}

impl GameState {
    pub fn hash(&self) -> u64 {
        let bytes = bincode::serialize(self).unwrap();
        xxh3_64(&bytes)
    }
}
```

### 10.5 步骤 5:加 replay 系统

```rust
use serde::{Serialize, Deserialize};

#[derive(Serialize, Deserialize, Copy, Clone)]
pub struct PlayerInput {
    pub move_x: i8,
    pub move_y: i8,
    pub jump_pressed: bool,
    pub attack_pressed: bool,
}

impl PlayerInput {
    pub fn empty() -> Self {
        Self { move_x: 0, move_y: 0, jump_pressed: false, attack_pressed: false }
    }
}

#[derive(Serialize, Deserialize)]
pub struct Replay {
    pub initial_seed: u64,
    pub initial_state: Vec<u8>,  // bincode-encoded
    pub inputs: Vec<PlayerInput>,
    pub checksums: Vec<u64>,  // 每帧 state hash,验证用
}

pub struct ReplayRecorder {
    initial_seed: u64,
    initial_state: Vec<u8>,
    inputs: Vec<PlayerInput>,
    checksums: Vec<u64>,
}

impl ReplayRecorder {
    pub fn new(state: &GameState) -> Self {
        Self {
            initial_seed: state.rng.state,  // 假设 rng 是 public 或有 accessor
            initial_state: bincode::serialize(state).unwrap(),
            inputs: Vec::new(),
            checksums: Vec::new(),
        }
    }
    
    pub fn record_frame(&mut self, input: PlayerInput, state: &GameState) {
        self.inputs.push(input);
        self.checksums.push(state.hash());
    }
    
    pub fn finish(self) -> Replay {
        Replay {
            initial_seed: self.initial_seed,
            initial_state: self.initial_state,
            inputs: self.inputs,
            checksums: self.checksums,
        }
    }
}

pub struct ReplayPlayer {
    replay: Replay,
    current_frame: usize,
    state: GameState,
}

impl ReplayPlayer {
    pub fn new(replay: Replay) -> Self {
        let state: GameState = bincode::deserialize(&replay.initial_state).unwrap();
        Self {
            replay,
            current_frame: 0,
            state,
        }
    }
    
    pub fn step(&mut self) -> Result<(), ReplayError> {
        if self.current_frame >= self.replay.inputs.len() {
            return Err(ReplayError::Ended);
        }
        
        let input = self.replay.inputs[self.current_frame];
        self.state.apply_input(input);
        self.state.simulate(FIXED_DT);
        
        // Verify checksum
        let actual = self.state.hash();
        let expected = self.replay.checksums[self.current_frame];
        if actual != expected {
            return Err(ReplayError::Desync {
                frame: self.current_frame,
                expected,
                actual,
            });
        }
        
        self.current_frame += 1;
        Ok(())
    }
    
    pub fn state(&self) -> &GameState {
        &self.state
    }
}

#[derive(Debug)]
pub enum ReplayError {
    Ended,
    Desync { frame: usize, expected: u64, actual: u64 },
}
```

### 10.6 步骤 6:加 checkpoint(hybrid)

```rust
pub struct HybridReplay {
    pub initial_state: Vec<u8>,
    pub inputs: Vec<PlayerInput>,
    pub checksums: Vec<u64>,
    pub checkpoints: Vec<Checkpoint>,
}

#[derive(Serialize, Deserialize)]
pub struct Checkpoint {
    pub frame: u64,
    pub state: Vec<u8>,
}

impl HybridReplay {
    pub const CHECKPOINT_INTERVAL: u64 = 300;  // 5 秒 @ 60fps
    
    pub fn seek(&self, target_frame: u64) -> Result<GameState, ReplayError> {
        // 找最近 checkpoint
        let cp = self.checkpoints.iter()
            .rev()
            .find(|c| c.frame <= target_frame);
        
        let (mut frame, mut state) = match cp {
            Some(cp) => (cp.frame, bincode::deserialize::<GameState>(&cp.state).unwrap()),
            None => (0, bincode::deserialize::<GameState>(&self.initial_state).unwrap()),
        };
        
        // 从 checkpoint 模拟到 target
        while frame < target_frame {
            let input = self.inputs.get(frame as usize).copied()
                .ok_or(ReplayError::Ended)?;
            state.apply_input(input);
            state.simulate(FIXED_DT);
            frame += 1;
            
            // Verify
            let actual = state.hash();
            let expected = self.checksums.get(frame as usize).copied()
                .ok_or(ReplayError::Ended)?;
            if actual != expected {
                return Err(ReplayError::Desync { 
                    frame: frame as usize, 
                    expected, 
                    actual 
                });
            }
        }
        
        Ok(state)
    }
}
```

### 10.7 步骤 7:主循环集成

```rust
mod rng;
mod replay;

use rng::Pcg32;
use replay::{PlayerInput, ReplayRecorder};

fn main() {
    let args: Vec<String> = std::env::args().collect();
    
    if let Some(replay_path) = args.get(1) {
        // 回放模式
        let replay_data = std::fs::read(replay_path).unwrap();
        let replay: HybridReplay = bincode::deserialize(&replay_data).unwrap();
        let mut player = ReplayPlayer::new(replay);
        
        while player.step().is_ok() {
            render(player.state());
        }
    } else {
        // 正常游戏 + 录制
        let mut state = GameState::new();
        state.rng = Pcg32::from_seed(0xDEADBEEF);  // 固定 seed
        
        let mut recorder = ReplayRecorder::new(&state);
        
        while state.running {
            let input = process_input();
            state.apply_input(input);
            state.simulate(FIXED_DT);
            
            recorder.record_frame(input, &state);
            render(&state);
        }
        
        let replay = recorder.finish();
        std::fs::write("last_replay.bin", bincode::serialize(&replay).unwrap()).unwrap();
    }
}
```

### 10.8 步骤 8:CI 跨平台 desync 测试

`.github/workflows/desync-test.yml`:

```yaml
jobs:
  desync-test:
    strategy:
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@1.76.0
      - name: Run deterministic scenario
        run: |
          cargo run --release -- --replay test_scenario.bin --check-only
          # --check-only: 跑 simulation,输出每帧 hash,不渲染
      - name: Upload hashes
        uses: actions/upload-artifact@v3
        with:
          name: hashes-${{ matrix.os }}
          path: hashes.txt

  compare-hashes:
    needs: desync-test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v3
        with:
          name: hashes-ubuntu-latest
          path: ubuntu/
      - uses: actions/download-artifact@v3
        with:
          name: hashes-windows-latest
          path: windows/
      - uses: actions/download-artifact@v3
        with:
          name: hashes-macos-latest
          path: macos/
      - name: Diff
        run: |
          diff ubuntu/hashes.txt windows/hashes.txt || exit 1
          diff ubuntu/hashes.txt macos/hashes.txt || exit 1
          echo "All platforms agree!"
```

这 CI 保证 PR 不引入跨平台 desync。任何 PR 让 Linux / Windows / macOS hash 不同,CI 失败。

### 10.9 步骤 9:倒带系统(rewind)

Replay 系统的副产品:**rewind**——让游戏"回到 30 秒前"。利用 hybrid replay 的 checkpoint:

```rust
pub struct RewindSystem {
    checkpoints: VecDeque<Checkpoint>,  // 最近 60 个 checkpoint(每秒一个 = 60 秒)
    inputs: VecDeque<(u64, PlayerInput)>,  // 最近 60 * 60 = 3600 帧 input
}

impl RewindSystem {
    pub fn record(&mut self, frame: u64, state: &GameState, input: PlayerInput) {
        if frame % 60 == 0 {
            self.checkpoints.push_back(Checkpoint {
                frame,
                state: bincode::serialize(state).unwrap(),
            });
            if self.checkpoints.len() > 60 {
                self.checkpoints.pop_front();
            }
        }
        self.inputs.push_back((frame, input));
        if self.inputs.len() > 60 * 60 {
            self.inputs.pop_front();
        }
    }
    
    pub fn rewind(&self, target_frame: u64) -> Option<GameState> {
        let cp = self.checkpoints.iter()
            .rev()
            .find(|c| c.frame <= target_frame)?;
        
        let mut state = bincode::deserialize::<GameState>(&cp.state).ok()?;
        let mut frame = cp.frame;
        
        while frame < target_frame {
            let input = self.inputs.iter()
                .find(|(f, _)| *f == frame)
                .map(|(_, i)| *i)
                .unwrap_or_default();
            state.apply_input(input);
            state.simulate(FIXED_DT);
            frame += 1;
        }
        
        Some(state)
    }
}

// 主循环里按 R 键 rewind 30 秒
if input.rewind_pressed {
    let target = state.frame.saturating_sub(30 * 60);
    if let Some(rewound) = rewind_system.rewind(target) {
        state = rewound;
    }
}
```

这就是"Braid" / "SUPERHOT" / "Prince of Persia: Sands of Time" 这些倒带游戏的核心机制。

## 11 · 性能数据汇总

到这里你要记住的关键数字:

| 数据 | 值 | 来源 |
|---|---|---|
| f32 mantissa bits | 23 | IEEE 754 |
| f64 mantissa bits | 52 | IEEE 754 |
| f32 ULP at 1.0 | ~1.19e-7 | 2^-23 |
| f64 ULP at 1.0 | ~2.22e-16 | 2^-52 |
| f32 范围 | ±3.4e38 | IEEE 754 |
| f64 范围 | ±1.8e308 | IEEE 754 |
| PCG32 state size | 16 bytes | O'Neill 2014 |
| PCG32 period | 2^64 | O'Neill 2014 |
| PCG32 next_u32 cost | ~3ns | benchmark |
| LCG next cost | ~1ns | benchmark |
| Xoshiro256+ next cost | ~2ns | benchmark |
| xxHash64 throughput | ~10 GB/s | xxHash benchmark |
| CRC32 throughput | ~1 GB/s | hardware CRC |
| bincode serialize 1 KB state | ~5us | benchmark |
| bincode deserialize 1 KB state | ~5us | benchmark |
| Frame time @ 60 FPS | 16.67 ms | 1000/60 |
| Replay input-only size | 60 FPS × 8B × 60s = 28.8 KB/min | calc |
| Replay snapshot size | 1 snapshot/s × 1 KB × 60s = 60 KB/min | calc |
| Frame budget for simulation | 2-5 ms (typical) | industry |
| Standard float op throughput | 1 op/cycle (FMA) | CPU spec |
| Hardware sin/cost | 20-50 cycle | Intel SDM |
| Software sin/cost | 100-500 cycle | micromath |
| Fixed-point mul (i64) | 1-3 cycle | CPU spec |
| Hash 1 KB state | ~100ns | xxh3 benchmark |

这些数字告诉你:**决定性不是免费的,但代价小**。PCG 比 thread_rng 慢 1-2 ns(几乎不可察觉),fixed-point 比浮点慢几 ns(可接受)。换来的跨平台决定性无价。

## 12 · 认知地图

### 12.1 上级(它属于哪个更大抽象?)

- **Reproducibility** — 软件工程通用概念。Reproducible builds、reproducible research、reproducible benchmarks,都是决定性。
- **State management** — 游戏架构核心议题。决定性是 state 管理的一部分(其他部分:persistence / save-load / network sync)。
- **Numeric computing** — 科学计算领域的核心议题。NumPy / MATLAB 用户对决定性敏感,因为 simulation 结果要 reproducible。

### 12.2 同级(并行方案对比)

| 方案 | 决定性 | 性能 | 复杂度 |
|---|---|---|---|
| 硬件浮点 + 禁 fast-math | 中(同平台) | 最高 | 低 |
| Fixed-point | 完美 | 高 | 中 |
| Software float | 完美 | 低(10-100x) | 高 |
| 限定平台 | 中-高 | 最高 | 低 |
| 不要决定性 | 不适用 | 最高 | 最低 |

### 12.3 下级(内部零件)

- IEEE 754 浮点格式
- FMA(fused multiply-add)指令
- MXCSR / FPCR 控制寄存器
- `-ffast-math` / `-fno-fast-math`
- PCG / Xoshiro / LCG / xorshift RNG 算法
- xxHash / FNV / CRC32 / SipHash hash 函数
- BTreeMap / IndexMap 决定性集合
- `slice::sort_by` stable sort
- Lockstep / rollback netcode
- Replay checkpoint / input log

## 13 · 对照与变奏

### 13.1 跨语言的 RNG 决定性

| 语言 | 默认 RNG | 决定性 | 跨平台 |
|---|---|---|---|
| C `rand()` | LCG | 是 | 是 |
| C++ `std::mt19937` | Mersenne Twister | 是(seeded) | 是 |
| Rust `rand::thread_rng()` | ChaCha | 否(OS seed) | 否 |
| Go `math/rand` | Additive Lagged Fibonacci | 是(seeded) | 是 |
| Python `random` | Mersenne Twister | 是(seeded) | 是 |
| JavaScript `Math.random` | implementation-defined | 否 | 否 |
| Lua `math.random` | platform C lib | 是(seeded) | 大致是 |

游戏开发要用**显式 seeded + 算法明确**的 RNG,不要用 language default。

### 13.2 历史演化

决定性这件事的演化,折射了游戏架构的演化:

- **1970s-80s**:8-bit 时代,所有游戏用整数物理(fixed-point),决定性自然。Astroids、Pac-Man、Space Invaders 都跨硬件完全一致(因为整数)。
- **1990s**:3D 革命,浮点普及。Doom(1993)坚持 fixed-point,Quake(1996)用 float。Quake 跨 CPU 偶有 desync,id Software 加 quirk 修正。
- **2000s**:RTS / esports 起步。《星际争霸》《帝国时代》用 lockstep + fixed-point,严格决定性。暴雪 / Ensemble Studios 投入大量工程保证 desync 为零。
- **2010s**:多核普及,多线程 desync 成新问题。Game state 必须单线程 simulation 或确定性多线程。FMA / SSE 演化让 cross-build 决定性变难。
- **2020s**:GGPO / rollback netcode 普及,要求 60 FPS 内每次倒退 / 重模拟。决定性是基础。

每个时代有新的 desync 来源,工程师持续对抗。

### 13.3 跨学科

决定性不是计算机专利。其他领域:

- **物理仿真**:Monte Carlo simulation 用决定性 RNG(seed 可重现)。气象模拟、分子动力学都要求 reproducibility。
- **机器学习**:训练神经网络用 seeded RNG,实验可重现。PyTorch / TensorFlow 提供 seeded random API。
- **加密**:加密 RNG 必须**不**决定(真随机),否则预测密钥。和游戏 RNG 反向。
- **赌博业**:slot machine RNG 受法律监管,要 certified 决定性(算法公开)+ 偶发性(seed 来自硬件真随机)。

跨学科的统一抽象:**state + transition function + reproducibility**。

### 13.4 开源贡献机会

- [Rapier 物理引擎](https://github.com/dimforge/rapier):跨平台决定性测试改进
- [bevy_ecs](https://github.com/bevyengine/bevy):ECS iteration 顺序决定性
- [rand crate](https://github.com/rust-random/rand):文档改进"什么时候用 / 不用 thread_rng"
- [Berkeley SoftFloat](https://github.com/ucb-bar/berkeley-softfloat-3):Rust binding 完善

具体 PR 方向:
- Rapier: 加跨平台 desync test
- bevy_ecs: 加 determinism 文档,说明 query iteration 顺序
- rand: 加 `Deterministic` 模块,显式 seeded RNG 推荐

## 14 · 关联 Day

- **铺垫**:[../phase-3/day095.md](../../phase-3/day095.md) — fixed timestep,本篇的固定 dt 是其扩展;[../phase-3/day099.md](../../phase-3/day099.md) / [day100.md](../../phase-3/day100.md) — 完整 fixed timestep,本篇假设你已经懂;[../phase-4/day138.md](../../phase-4/day138.md) — RNG 用于粒子,本篇讲为什么必须用 seeded RNG;[../phase-7/day550.md](../../phase-7/day550.md) — replay 系统 v1,本篇是其完整版
- **当天**:本 deep dive(无对应 HH day)
- **后续**:[../phase-8/deep-dives/performance-budget.md](performance-budget.md) — 性能预算,决定性有时牺牲性能;[shipping-checklist.md](shipping-checklist.md) — 发行检查表,Cargo.lock / rust-toolchain 提交是决定性前提

## 15 · 变式训练

### Lv1 · 概念辨析(读懂)

**题**:为什么 `0.1 + 0.2 != 0.3` 在 f64 下成立,但在 f32 下可能 == 成立?

**参考解答**:f32 精度 23 bit,0.1 / 0.2 / 0.3 各自 round 到最近的 f32,加法再 round。在 f32 下,(0.1 + 0.2) 和 0.3 的 round 结果**恰好相同**(都 round 到 0x3D4FDF3D),所以 == 成立。f64 精度 52 bit,round 更细,(0.1 + 0.2) = 0x3FD333...54,0.3 = 0x3FD333...53,差 1 ULP,所以 != 。这告诉你 f32 偶尔"看起来更准"是巧合,不是规则——精度低让差异恰好被 round 掉。

### Lv2 · 动手实践

**题**:用 `cargo new` 创建 `pcg-demo`,实现 PCG32,跑 1000 次输出,在你的 Linux 机器和一个朋友的 macOS 机器上跑,确认输出 bit-exact 相同。

**完成标准**:
1. 两台机器跑出相同的 1000 个 u32
2. `cargo test` 通过决定性测试

**参考解答**:见 10.1 节代码。

### Lv3 · 迁移设计

**题**:你接手一个 50K 行的 Rust 游戏。它用 `rand::thread_rng()` 散落在 30 个文件,有 `HashMap` 在 simulation 内部迭代,有 `slice::sort_unstable_by` 在 simulation。你的任务:**改造成完全决定性**。

设计回答:
1. 优先级?RNG → HashMap → sort?为什么?(提示:RNG 影响 simulation 最大,先改)
2. 怎么测?改之前先加 desync detection(hash 每帧),还是改完再加?(提示:之前加,作为 baseline)
3. 30 个文件的 `rand::thread_rng()` 怎么改?(提示:全局 State 加 rng,所有需要随机的函数接收 `&mut Pcg32`)
4. CI 怎么加跨平台 desync 测试?(提示:见 10.8)

### Lv4 · 开源贡献

**题**:[Rapier 物理引擎](https://github.com/dimforge/rapier)的 [determinism docs](https://rapier.rs/docs/user_guides/javascript/determinism) 说跨平台大致决定,但**没有 CI 跨平台 desync 测试**。

1. Clone 仓库。
2. 看 `examples/`,找一个简单 demo。
3. 加 CI 配置,Linux / Windows / macOS 跑 demo,输出 state hash,对比。
4. 提 PR。

PR 草稿:
```
标题:ci: add cross-platform determinism test
改动:.github/workflows/desync.yml + examples/desync_test.rs
动机:Rapier 文档说跨平台决定,但无 CI 保证。PR 引入 desync 测试,
     防止 regression。
验证:CI 跑三个 OS,对比 state hash,完全一致。
```

## 16 · 延伸阅读

本仓库本地资料:
- [../phase-3/day095.md](../../phase-3/day095.md) — 固定 timestep 入门
- [../phase-3/day099.md](../../phase-3/day099.md) / [day100.md](../../phase-3/day100.md) — 完整固定 timestep
- [../phase-4/day138.md](../../phase-4/day138.md) — 粒子用 RNG
- [../phase-7/day550.md](../../phase-7/day550.md) — replay v1
- [shipping-checklist.md](shipping-checklist.md) — 发行检查表

外部稳定 URL:
- IEEE 754-2019 standard: https://standards.ieee.org/ieee/7591-10870/
- IEEE 754 Wikipedia: https://en.wikipedia.org/wiki/IEEE_754
- PCG official: https://www.pcg-random.org/
- PCG paper (O'Neill 2014): https://www.pcg-random.org/pdf/hmc-cs-2014-0905.pdf
- Xoshiro paper: https://vigna.di.unimi.it/ftp/papers/ScrambledLinear.pdf
- Berkeley SoftFloat: https://github.com/ucb-bar/berkeley-softfloat-3
- Fixed-point arithmetic: https://en.wikipedia.org/wiki/Fixed-point_arithmetic
- GGPO rollback netcode: https://github.com/ottogsp/ggpo
- Lockstep protocol: https://en.wikipedia.org/wiki/Lockstep_protocol
- "Floating Point Demystified": https://floating-point-gui.de/
- "What Every Computer Scientist Should Know About Floating-Point Arithmetic": https://docs.oracle.com/cd/E19957-01/806-3568/ncg_goldberg.html
- Rapier determinism docs: https://rapier.rs/docs/user_guides/javascript/determinism
- Box2D deterministic note: https://github.com/erincatto/box2d/blob/main/FAQ.md

真实开源源码:
- PCG C reference impl: https://github.com/imneme/pcg-c/blob/master/include/pcg_variants.h
- Xoshiro reference: https://prng.di.unimi.it/
- Rapier Rust source: https://github.com/dimforge/rapier/tree/master/src
- bevy_ecs query iteration: https://github.com/bevyengine/bevy/blob/main/crates/bevy_ecs/src/system/query.rs
- HH day550 replay: https://github.com/HandmadeHero/handmade-hero/tree/main/code/day550
- Berkeley SoftFloat: https://github.com/ucb-bar/berkeley-softfloat-3/blob/master/source/f32_add.c
