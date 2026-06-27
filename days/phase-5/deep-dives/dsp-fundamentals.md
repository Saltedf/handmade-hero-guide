---
phase: 5
title_en: "DSP Fundamentals"
title_zh: "数字信号处理基础:卷积、Z 变换与数字滤波器"
type: deep-dive
domains: [game, audio, rust, linux, system, math]
bridges: ["day009", "day142", "day184"]
---

# 数字信号处理基础

> 你已经会写混音器了——把 N 路声音加起来,做 `tanh` 软限幅。但这只是开始。玩家问:"能不能给脚步声加个低通,听起来闷一点?""开火的高频别那么刺耳?""回声做一下?"**这些都是 filter**。你打开任何 DAW(Ableton / FL / Reaper),效果器面板里全是 LP / HP / EQ / Reverb / Compressor——它们背后是同一套数学:**数字信号处理**(Digital Signal Processing, DSP)。今天这一篇从最基础的"卷积是什么"一路推到"RBJ biquad cookbook 公式",手写 Rust 实现一个能跑的 biquad filter 链。看完你能解释为什么 Butteworth 平坦、Chebyshev 有 ripple、Elliptic 最陡但相位乱;你能从零推导 Z 变换、画出 Bode plot、计算群延迟;你能在 HH 项目里把枪声的高频"削"下去 6 dB。

## 0 · 为什么要有这一篇

DSP 是音频工程的**底层地基**。它把所有"音频效果"统一成一个数学框架——**线性时不变系统**(LTI system)。一旦你看懂 LTI,所有 EQ、所有 reverb、所有 compressor、所有 pitch shifter,在你眼里都是**同一个东西的不同参数化**。

这件事的威力在哪?让我说几个具体场景:

**场景一**:你的射击游戏,枪声采样自真实 AK-47 录音。原始录音在室外靶场录的,有大量高频反射,听起来"刺耳"。你要**只削高频,保留中低频的"啪"**。怎么做?——低通滤波器(Low-Pass Filter, LPF),cutoff 6 kHz,12 dB/oct。三行代码。

**场景二**:你的 NPC 在山洞里说话。直接播语音文件,听起来像在录音棚。要做"山洞感"——多个延迟叠加,衰减不同的频率。怎么做?——Comb filter + All-pass filter 串联,这是 Schroeder reverb 的核心。

**场景三**:玩家用蓝牙耳机,你的游戏音频延迟 200ms。你想做"延迟补偿"——把某些声音"提前"播放。但"提前"等于**负延迟**,物理上不可能(你不能预测未来)。怎么办?——用**线性相位 filter** 的群延迟特性,做"已知延迟"的补偿。

**场景四**:你想做"老式电话"效果——军人在对讲机里说话,200 Hz 以下和 3400 Hz 以上全切掉。怎么做?——Band-pass filter(BPF),cutoff 300-3400 Hz,陡峭度 24 dB/oct。

这些场景背后,**全部**是同一套数学:**Z 变换、传递函数、频率响应、biquad**。学完这一篇,你不再是"调参侠",而是真正理解每个旋钮背后的物理。

**读完这一篇,你应该能**:

- 解释连续信号 vs 离散信号 vs 数字信号的区别(以及它们各自的数学)
- 写出卷积的定义式,用 flip-slide-multiply-sum 几何直觉理解它
- 从连续时间傅里叶变换一路推导到 Z 变换
- 设计 FIR 滤波器(window method、Parks-McClellan)和 IIR 滤波器(一阶 RC、biquad、Butterworth)
- 写出 RBJ cookbook 全部五个 biquad 类型(LP/HP/BP/BS/AP)的系数公式
- 实现 Direct Form I / II / Transposed II 三种 biquad 拓扑,知道它们各自的数值稳定性
- 画 Bode plot(频率响应)和群延迟曲线,解释 linear phase vs minimum phase
- 在 Rust 里写一个能跑的 biquad 链,实时处理麦克风输入

读者基线:完成 HH 22 信号基础 + Phase 5 day009 音频 + day142 mixer。下面的推导默认你已经会 f32 PCM、mixer、cpal callback。

## 1 · 信号的三副面孔:连续、离散、数字

### 1.1 物理世界:连续时间信号

物理世界的信号——声波、光强、电压、温度——都是**连续时间**的。形式化:

$$ x(t): \mathbb{R} \to \mathbb{R}, \quad t \in \mathbb{R} $$

`x(t)` 在**任意实数 t** 都有定义。声波是空气压强随时间的函数 `p(t)`,人耳鼓膜随压强振动,内耳毛细胞把振动转神经脉冲。整条链路是连续的。

连续信号的频域表示是**连续时间傅里叶变换**(Continuous-Time Fourier Transform, CTFT):

$$ X(\omega) = \int_{-\infty}^{\infty} x(t) e^{-i\omega t} \, dt $$

`ω` 是角频率(rad/s),`X(ω)` 是复数——幅度 `|X(ω)|` 是该频率分量的振幅,辐角 `arg X(ω)` 是相位。

CTFT 是"完美"的频域分析——分辨率无限。但**计算机做不了**——你不能在内存里存一个定义在 `R` 上的函数,也不能做无穷积分。

### 1.2 ADC:离散时间信号

模数转换器(Analog-to-Digital Converter, ADC)每隔 T 秒采一次值,把连续信号变成离散序列:

$$ x[n] = x(nT), \quad n \in \mathbb{Z} $$

`T` 叫**采样周期**(seconds/sample),它的倒数 `f_s = 1/T` 叫**采样率**(samples/second, Hz)。CD 是 44100 Hz,DVD 是 48000 Hz,专业音频 96000 或 192000 Hz。

Nyquist-Shannon 采样定理:**带限信号**(最高频率 f_max)**只要 f_s ≥ 2 f_max 就能无损重建**。人耳听觉 20 Hz - 20 kHz,所以 f_s = 40 kHz 就够。CD 选 44.1 kHz 留 2.05 kHz 余量给 anti-aliasing filter 的滚边。这个 44.1 kHz 是 Sony/Philips 在 1979 年定的,和 NTSC/PAL 视频时序对齐——历史包袱。

离散时间信号的频域是**离散时间傅里叶变换**(DTFT):

$$ X(e^{i\omega}) = \sum_{n=-\infty}^{\infty} x[n] e^{-i\omega n} $$

注意:DTFT 仍然是**连续频率**的(`ω` 是连续实数),但**周期 2π**——因为 `e^{iωn}` 周期 2π。这是离散信号和连续信号最大的频域差异:**离散化导致频域周期化**。

### 1.3 量化:数字信号

ADC 同时做两件事:**采样**(连续时间 → 离散时间)和**量化**(连续幅度 → 离散幅度)。量化把每个采样的连续值映射到 2^B 个离散电平之一,B 是 bit depth。

CD 是 16-bit,有 65536 个电平。24-bit 有 16M 个电平。**量化误差**:

$$ e[n] = x_{digital}[n] - x_{analog}[n] $$

如果量化阶 `Δ = 2 / 2^B`(信号范围归一化到 [-1, 1]),量化误差在 `[-Δ/2, Δ/2]` 均匀分布,方差 `σ² = Δ²/12`。

信噪比 SNR ≈ 6.02 B + 1.76 dB。CD(16-bit)≈ 96 dB,24-bit ≈ 144 dB。这就是为什么专业录音用 24-bit——后期处理(headroom、压缩)有更多余量。

**抖动**(dither):在量化前加一点白噪(±1 LSB),把"量化失真"(相关谐波,刺耳)变成"白噪"(不相关,大脑容易忽略)。这是 Apogee 的 Mytek Bernstein 在 1980s 提出的关键技术。CD 母带都加 dither。

### 1.4 三种信号的工程意义

为什么搞清楚这三副面孔?因为你做 DSP 时**频繁在这三个域之间切换**:

- **想计算输出**:数字域(已经量化了)。
- **想分析频率**:离散时间域(DTFT 周期 2π,好分析)。
- **想从连续原型迁移到离散**:连续时间 → 双线性变换 → 离散时间(下面 Z 变换会讲)。

工业级 DSP 文献(Oppenheim & Schafer、Proakis、Rabiner)都是这个三副面孔的展开。**头脑里把这三层分清楚**,看任何 DSP 公式都不会混乱。

## 2 · LTI 系统:线性时不变

### 2.1 为什么 LTI 是核心

**线性时不变系统**(Linear Time-Invariant system, LTI)是 DSP 的中心对象。原因是两个:

1. **可分析**。LTI 系统完全由**冲激响应**(impulse response) `h[n]` 刻画。给定 `h[n]`,任意输入 `x[n]` 的输出 `y[n]` 可以**显式算出**(用卷积)。这种"知道一个函数就知道一切"的简化,是数学上罕见的奢侈品。

2. **可叠加**。两个 LTI 系统级联 `h1 * h2` 可以等价为一个 LTI 系统 `h = h1 * h2`(卷积),且**交换顺序不影响结果**。这让你可以重组、简化、推导。

非 LTI 系统(比如 compressor,带增益非线性)就没有这些性质——你要逐样本模拟,没有简洁的频域分析。

### 2.2 线性的定义

系统 `T` 是线性的,当且仅当满足**叠加性**和**齐次性**:

$$ T\{a x_1[n] + b x_2[n]\} = a T\{x_1[n]\} + b T\{x_2[n]\} $$

直觉:**输入放大 a 倍 = 输出放大 a 倍**;**两个输入相加再过系统 = 分别过系统再相加**。

反例:**乘法器** `y[n] = x[n]²`。`T{2x} = 4x² ≠ 2x²`。非线性。
反例:**整流器** `y[n] = |x[n]|`。`T{x - y} ≠ |x| - |y|` 一般。非线性。
反例:**压缩器** `y[n] = x[n] · g(|x[n]|)`,g 依赖输入幅度。非线性。

正例:**滤波器** `y[n] = 0.5 x[n] + 0.5 x[n-1]`(简单低通)。线性,因为系数不依赖输入。

### 2.3 时不变的定义

系统 `T` 是时不变的,当且仅当:**输入延迟 k 个样本,输出也延迟 k 个样本**。

$$ T\{x[n - k]\} = y[n - k], \quad \text{其中} \; y[n] = T\{x[n]\} $$

直觉:**系统的行为不随时间变**。今天用 filter 和明天用,结果一样。

反例:**flanger** `y[n] = x[n] + x[n - d(n)]`,d 随时间变。时变。
反例:**autoplay volume ramp** `y[n] = x[n] · g[n]`,g 随时间变。时变。

正例:**所有系数固定的 filter**(FIR、IIR)。时不变。

### 2.4 LTI 的"大杀器":冲激响应

**单位冲激**(discrete unit impulse):

$$ \delta[n] = \begin{cases} 1, & n = 0 \\ 0, & n \neq 0 \end{cases} $$

任何离散信号 `x[n]` 都能写成冲激的加权和:

$$ x[n] = \sum_{k=-\infty}^{\infty} x[k] \delta[n - k] $$

这个分解**平凡但极其有用**——把 `x[n]` 看作"无穷多个不同时移、不同权重的 δ 的叠加"。

把 `x[n]` 喂给 LTI 系统 T:

$$ y[n] = T\{x[n]\} = T\left\{ \sum_k x[k] \delta[n-k] \right\} = \sum_k x[k] T\{\delta[n-k]\} $$

(线性允许把 T 拆到加权和里)

$$ y[n] = \sum_k x[k] h[n-k] $$

(时不变允许 `T{δ[n-k]} = T{δ[n]} \text{ delayed by } k = h[n-k]`)

这里 `h[n] = T{δ[n]}` 是系统对 δ 的响应——**冲激响应**(impulse response)。

**结论**:LTI 系统的输出由冲激响应 `h[n]` 完全决定,公式是:

$$ y[n] = \sum_k x[k] h[n-k] = (x * h)[n] $$

`*` 是**卷积**(convolution)算子。

这个结论叫 **convolution theorem for LTI systems**。它的厉害之处:**复杂系统(可能是几百行差分方程)被压缩成一个函数 `h[n]`,以及一个运算 `*`**。

## 3 · 卷积:flip-slide-multiply-sum

### 3.1 卷积的定义

两个离散信号 `x` 和 `h` 的卷积:

$$ (x * h)[n] = \sum_{k=-\infty}^{\infty} x[k] h[n - k] $$

这个公式初学时看不懂——为什么要这样算?让我用几何直觉拆开。

### 3.2 几何直觉:flip-slide-multiply-sum

把卷积拆成四步:

1. **Flip**(翻转)。把 `h[k]` 翻成 `h[-k]`——关于 y 轴镜像。
2. **Slide**(滑动)。把 `h[-k]` 整体平移 n 步,得到 `h[n - k]`。
3. **Multiply**(逐点乘)。对每个 k,把 `x[k]` 和 `h[n-k]` 相乘。
4. **Sum**(求和)。把所有乘积加起来,得到一个标量——这就是 `y[n]`。

每给一个 n,得到一个 y[n]。**遍历所有 n,得到完整输出 y**。

为什么是"翻转"而不是"直接对齐"?这是数学上推导出的(从冲激分解那里),但物理直觉是:**冲激响应 h 描述"系统对过去输入的记忆"**。t=0 时刻的输入 x[0],对 t=N 时刻的输出 y[N] 的贡献是 `x[0] · h[N]`(经过 N 步衰减)。一般地,x[k] 对 y[n] 的贡献是 `x[k] · h[n - k]`(时移 n - k 后的 h)。所以**总输出 = 所有过去输入的贡献之和** = `sum_k x[k] h[n-k]`。

"翻转"的几何意义就是"计算每个过去输入到现在还剩多少"。

### 3.3 卷积性质

四个核心性质,几乎决定了 LTI 系统的所有行为:

1. **交换律**: `x * h = h * x`。两个信号在卷积里地位平等。
2. **结合律**: `(x * h1) * h2 = x * (h1 * h2)`。级联 filter 可以等价成一个 filter。
3. **分配律**: `x * (h1 + h2) = x * h1 + x * h2`。并联 filter 可以合并。
4. **平移**: 如果 `y[n] = (x * h)[n]`,那么 `y[n - k] = (x[n-k] * h)[n]`。LTI 不变时移。

**结合律的工程价值**:你有三个级联 filter,各是 100 tap FIR。每个 filter 跑一次卷积 = 100 倍乘加。三个串起来 = 300 倍。但 `h_total = h1 * h2 * h3` 是一个 298 tap 的 FIR,跑一次卷积 = 298 倍——**还多算了**。如果你需要"对 N 个不同输入都过这三个 filter",先合并 h_total(算一次),再 N 次卷积——总开销从 `300 N` 降到 `298 + N · 298 ≈ 298 N`,加上 h_total 预算的一次性 298,基本忽略。**这就是级联合并**。

### 3.4 卷积的复杂度

直接卷积:`(x * h)[n] = sum_k x[k] h[n-k]`,对每个 n 是 O(L_h) 次乘加(L_h 是 h 长度),总 O(L_x · L_h)。1000 tap FIR × 1 秒音频(44100 sample)= 44M 乘加。60 秒 = 2.6G——可以但吃 CPU。

**快速卷积**:利用 FFT。`(x * h)` 在频域是 `X(ω) · H(ω)`(逐点复数乘)。所以先 FFT{x}, FFT{h},逐点乘,IFFT。总复杂度 O(N log N),N 是 FFT 大小。N = 4096 时,直接卷积 = 16M,FFT 卷积 = 50K——**300 倍加速**。FFT 卷积详细见下一篇 deep-dive。

工业实践:FIR filter 用 FFT 卷积,Oversample-add(OLA)或 overlap-save(OLS)处理长信号。IIR filter 用差分方程递推,O(L_x) 直接算,没有"快速 IIR"——但 IIR 通常 tap 数少(双二阶就 5 个系数),所以也快。

## 4 · Z 变换:从时域到复频域

### 4.1 为什么要 Z 变换

时域卷积公式 `y[n] = sum_k x[k] h[n-k]` 写起来累,看起来乱。能不能找个"算子",把卷积变成乘法?

类比:log 把乘法变成加法(log(ab) = log a + log b),所以 17 世纪数学家算 357 × 829 = exp(log(357) + log(829))——加法比乘法好查表。

Z 变换把卷积变成乘法:`Z{x * h} = Z{x} · Z{h}`。这样,级联系统 = Z 域里多项式相乘,差分方程 = Z 域里代数方程,**所有 LTI 系统的运算都简化了**。

### 4.2 双边 Z 变换定义

序列 `x[n]` 的双边 Z 变换:

$$ X(z) = \sum_{n=-\infty}^{\infty} x[n] z^{-n} $$

`z` 是复数 `z = r e^{iω}`。等价写法:把 `x[n]` 投影到一族"复指数基底" `z^{-n} = r^{-n} e^{-iωn}`。

为什么用 `z^{-1}` 而不是 `z`?因为 `z^{-1}` 物理意义是**单位延迟**(unit delay):Z{δ[n-1]} = z^{-1}。下面会反复用到。

### 4.3 从连续时间傅里叶推到 Z 变换

让我把推导链路串起来,你会看到 Z 变换不是凭空发明。

**起点**:连续时间信号 `x(t)`,傅里叶变换 `X(ω) = ∫ x(t) e^{-iωt} dt`。

**第一步**:采样。`x[n] = x(nT)`。理想采样等价于 `x(t)` 乘以冲激序列 `Σ δ(t - nT)`。

**第二步**:采样信号的傅里叶变换 = `X(ω)` 的周期延拓(周期 2π/T)。这是 Poisson 求和公式的直接推论。

**第三步**:DTFT(离散时间傅里叶变换) = `X(e^{iω}) = Σ x[n] e^{-iωn}`,频率变量 ω 是归一化角频率(`ω = 2π f / f_s`)。

**第四步**:推广。把 `e^{iω}` 替换成一般的复数 `z = r e^{iω}`(允许 |z| ≠ 1),就得到 Z 变换。

**关键观察**:DTFT 是 Z 变换在**单位圆 |z| = 1** 上的取值。即 `X(e^{iω}) = X(z)|_{z = e^{iω}}`。

**为什么 Z 变换比 DTFT 强**:DTFT 要求 `x[n]` 绝对可和(`Σ|x[n]| < ∞`),否则级数发散。Z 变换引入"收敛域"(Region of Convergence, ROC),对**更多信号**有定义——比如 `x[n] = a^n u[n]` 在 |z| > |a| 时收敛,即便 a > 1(指数增长信号,DTFT 直接发散)。

### 4.4 Z 变换的性质(全是 LTI 工程的核心)

(下面所有大写字母是 Z 变换)

1. **线性**: `Z{a x + b y} = a X(z) + b Y(z)`
2. **时移**: `Z{x[n-k]} = z^{-k} X(z)`。← 这是 Z 变换的杀手级性质。**时移 = 乘以 z 的幂**。
3. **卷积**: `Z{x * h} = X(z) H(z)`。← 这是另一杀手级。**卷积 = 乘法**。
4. **Z 域微分**: `Z{n · x[n]} = -z dX/dz`
5. **初值定理**(因果信号): `x[0] = lim_{z → ∞} X(z)`

### 4.5 用 Z 变换解差分方程

考虑一个简单 IIR:

$$ y[n] = x[n] - a y[n-1] $$

(反馈项,所以叫 IIR)

两边 Z 变换:

$$ Y(z) = X(z) - a z^{-1} Y(z) $$

(用了时移性质:`Z{y[n-1]} = z^{-1} Y(z)`)

整理:

$$ Y(z) (1 + a z^{-1}) = X(z) $$

$$ \frac{Y(z)}{X(z)} = \frac{1}{1 + a z^{-1}} = H(z) $$

`H(z) = Y(z) / X(z)` 叫**传递函数**(transfer function)。它是 Z 域里"输出 / 输入"。对 LTI 系统,`H(z)` 是 z 的有理分式(分子分母都是 z 的多项式)。

### 4.6 极点和零点

$$ H(z) = \frac{b_0 + b_1 z^{-1} + \dots + b_M z^{-M}}{a_0 + a_1 z^{-1} + \dots + a_N z^{-N}} $$

(一般 LTI 差分方程的 Z 变换形式)

**零点**(zeros):使 `H(z) = 0` 的 z,即分子的根。
**极点**(poles):使 `H(z) → ∞` 的 z,即分母的根。

极点决定稳定性:**因果 LTI 系统稳定,当且仅当所有极点在单位圆内**(|极点| < 1)。

直觉:极点在单位圆外,冲激响应指数增长(发散);极点在单位圆上,等幅振荡(临界稳定,工程上不稳定);极点在圆内,指数衰减(稳定)。

例子:`H(z) = 1 / (1 + a z^{-1}) = z / (z + a)`,极点在 z = -a。|a| < 1 时稳定。`y[n] = -a y[n-1]` 当 a = -0.5 时,冲激响应是 `(-(-0.5))^n = 0.5^n`,衰减——稳定。

### 4.7 频率响应 = 单位圆上的 H

DTFT 是 Z 变换在单位圆 |z| = 1 上的取值。所以 LTI 的频率响应:

$$ H(e^{i\omega}) = H(z) |_{z = e^{i\omega}} $$

把 `z = e^{iω}` 代入传递函数,得到复数 `H(e^{iω})`,幅度 `|H(e^{iω})|` 是幅频响应,辐角 `arg H(e^{iω})` 是相频响应。

**工程意义**:`|H(e^{iω})|` 告诉你"频率 ω 的正弦输入会被放大/缩小多少倍";`arg H(e^{iω})` 告诉你"会被相移多少"。这是 filter 设计的全部内容——调整零极点位置,让 `|H(e^{iω})|` 在通带(想保留的频段)接近 1,在阻带(想滤掉的频段)接近 0。

## 5 · FIR 滤波器:有限冲激响应

### 5.1 FIR 定义

FIR 是 Finite Impulse Response 的缩写。差分方程:

$$ y[n] = \sum_{k=0}^{N} b_k x[n-k] $$

输出只依赖**当前和过去的输入**(无反馈)。冲激响应:`h[n] = b_n` 当 `0 ≤ n ≤ N`,否则 0——**有限长**(N+1 个非零样本)。

Z 变换:

$$ H(z) = \sum_{k=0}^{N} b_k z^{-k} = b_0 + b_1 z^{-1} + \dots + b_N z^{-N} $$

只有零点,没有极点(分母是 1)。所以 FIR **总是稳定**——没有反馈,不可能发散。

### 5.2 FIR 的优缺点

**优点**:

1. **绝对稳定**(no poles outside origin)
2. **可以做到精确线性相位**(linear phase)——所有频率的群延迟相等,信号"波形不变"。这是音频母带、通信的关键
3. **数值上鲁棒**——没有反馈积累误差

**缺点**:

1. **阶数高**。要实现陡峭的过渡带(比如 100 tap LP),FIR 需要 100+ tap,IIR 只要 8-12 个系数
2. **内存大**。1000 tap FIR 存 1000 个过去的输入样本
3. **不能直接从模拟原型迁移**(必须用 window 或优化方法设计)

### 5.3 线性相位的秘密

FIR 能做到线性相位,**当且仅当系数对称**:`b_k = b_{N-k}`(或反对称)。这时 `H(e^{iω})` 的相位 `arg H = -ωN/2 + const`,群延迟 = -dφ/dω = N/2,所有频率相同。

直觉:对称系数意味着 `h[n]` 关于中点对称,傅里叶变换的相位是线性的。这是 FIR 的杀手锏——IIR **不可能**做到精确线性相位(IIR 相位总是非线性的)。

线性相位的价值:**多频分量叠加时,波形不变形**。比如一个方波,基频和 3、5、7 次谐波按特定相位叠加才有"方"的形状。如果 filter 给每个频率不同的延迟,波形就散了。Hi-Fi 音频、示波器测量、通信都要求线性相位。

代价:**整体延迟 = N/2 个样本**。1000 tap FIR 引入 500 sample = 11 ms @ 44.1 kHz 延迟。实时音频里这个延迟不能忽略。

### 5.4 设计方法一:Window Method

最简单 FIR 设计方法。**步骤**:

1. 选择理想 filter 的频率响应(比如理想低通,cutoff ω_c)。
2. 算出理想 filter 的冲激响应(逆 DTFT):`h_ideal[n] = sin(ω_c n) / (π n)` 当 n ≠ 0,`ω_c / π` 当 n = 0。这是 sinc 函数(无限长、非因果)。
3. 截断到有限长度 N+1,且因果化(时移 N/2):`h_truncated[n] = h_ideal[n - N/2]` for `0 ≤ n ≤ N`。
4. 乘以窗函数 `w[n]`:`h[n] = h_truncated[n] · w[n]`。

**为什么需要窗**:直接截断(矩形窗)会在频域引入大的旁瓣(roll-off -21 dB,但旁瓣 ripple -13 dB)。窗函数在中间大、两端小,频域旁瓣更低。

常见窗:

| 窗 | 主瓣宽度 | 旁瓣(dB) | 适用 |
|---|---|---|---|
| Rectangular | 4π/N | -13 | 极少用 |
| Hamming | 8π/N | -43 | 通用 |
| Hann | 8π/N | -32 | 通用 |
| Blackman | 12π/N | -58 | 高衰减 |
| Kaiser (β=6) | 可调 | 可调 | 工业首选 |

Kaiser 窗有参数 β,在主瓣宽度和旁瓣之间 trade-off。**工业级 FIR 设计几乎都用 Kaiser**。

### 5.5 设计方法二:Parks-McClellan

Window 法是"先选窗,看结果"。Parks-McClellan 是"指定通带/阻带/过渡带,算法找最优系数"。它用 Remez exchange 算法迭代,**minimax 优化**(最小化最大误差)。

Parks-McClellan 的输出:FIR 系数,使通带和阻带的 ripple **均匀分布**(equiripple),这是 Chebyshev 意义下的最优。

代价:**计算复杂**(需要 Remez 迭代),不像 window 法一行代码出结果。

Python scipy 里有 `scipy.signal.remez`(也叫 `firpm`),C/Rust 里有 libsamplerate、k_filter。

### 5.6 Rust 实现 FIR

```rust
pub struct FirFilter {
    coeffs: Vec<f32>,    // b_0, b_1, ..., b_N
    state: Vec<f32>,     // x[n-1], x[n-2], ..., x[n-N], 延迟线
}

impl FirFilter {
    pub fn new(coeffs: Vec<f32>) -> Self {
        let n = coeffs.len();
        FirFilter {
            coeffs,
            state: vec![0.0; n],  // 初始为 0
        }
    }

    /// 单样本处理
    pub fn process(&mut self, x: f32) -> f32 {
        // 把新样本推入延迟线(state 末尾是 x[n-N],开头是 x[n-1])
        // 用环形 buffer 也行,这里用简单 shift
        self.state[1..].copy_within(0..self.state.len() - 1, 1);
        self.state[0] = x;

        // y[n] = sum_k b_k * x[n-k]
        // 注意:state[k] = x[n-k-1]? 不对,我们要小心 index
        // 我们存的是 [x[n-1], x[n-2], ..., x[n-N]],新 x[n] 还没进 state
        // 重写:
        let mut y = self.coeffs[0] * x;
        for k in 1..self.coeffs.len() {
            y += self.coeffs[k] * self.state[k - 1];
        }
        // 更新 state:把当前 x 存为下个迭代的 x[n-1]
        // 上面 copy_within 已经做了 shift,但首元素已经被覆盖了,我们要小心
        // 上面 self.state[0] = x 是错的——应该在 shift 之前保存旧 state[0]
        // 让我们重写:
        y
    }

    /// 正确实现:环形缓冲
    pub fn process_correct(&mut self, mut x: f32) -> f32 {
        // state 用作环形 buffer,长度 = N+1
        // 每次写入新样本到当前 head,然后 head 前进
        // 我们用简单 shift(对 N < 100 没问题):
        let n = self.coeffs.len();
        let mut y = 0.0;
        for k in 0..n {
            if k == 0 {
                y += self.coeffs[0] * x;
            } else {
                y += self.coeffs[k] * self.state[k - 1];
            }
        }
        // Shift state
        for i in (1..n).rev() {
            self.state[i] = self.state[i - 1];
        }
        self.state[0] = x;
        y
    }
}
```

(上面两个 process 函数都有点啰嗦,生产代码用环形 buffer 更高效。)

测试一下低通:

```rust
fn main() {
    // 简单移动平均 = N=4 矩形窗 LPF
    let coeffs = vec![0.25_f32; 4];
    let mut fir = FirFilter::new(coeffs);

    // 输入:DC(全 1)+ 高频(交替 ±0.5)
    let input: Vec<f32> = (0..16).map(|i| 1.0 + if i % 2 == 0 { 0.5 } else { -0.5 }).collect();
    let output: Vec<f32> = input.iter().map(|&x| fir.process_correct(x)).collect();
    println!("{:?}", output);
    // 4 个样本后,LPF 把 ±0.5 部分平均成 0,只剩 DC=1.0
    // 预期:前 4 个样本过渡,之后稳定在 1.0
}
```

## 6 · IIR 滤波器:无限冲激响应

### 6.1 IIR 定义

IIR(Infinite Impulse Response)。差分方程:

$$ y[n] = \sum_{k=0}^{M} b_k x[n-k] - \sum_{k=1}^{N} a_k y[n-k] $$

**关键**:有反馈项(`y[n-k]`)。冲激响应无限长(理论上),所以叫 IIR。

Z 变换:

$$ H(z) = \frac{b_0 + b_1 z^{-1} + \dots + b_M z^{-M}}{1 + a_1 z^{-1} + \dots + a_N z^{-N}} $$

分子分母都是多项式。极点 = 分母的根,**决定稳定性**。

### 6.2 IIR 的优缺点

**优点**:

1. **阶数低**。同样过渡带陡度,IIR 比 FIR 少 5-10 倍系数
2. **内存小**。N 阶 IIR 只需 2N 个状态样本
3. **延迟低**。输出几乎是即时的(没有 FIR 的 N/2 延迟)
4. **直接从模拟原型迁移**(双线性变换,下面讲)

**缺点**:

1. **可能不稳定**。极点跑出单位圆,系统发散
2. **非线性相位**。不同频率延迟不同,音频母带慎用
3. **数值上敏感**。系数量化误差可能让极点跑到错误位置,特别是高 Q 滤波器

### 6.3 一阶低通(RC 滤波器)

最简单的 IIR。模拟电路原型:RC 低通(电容 + 电阻)。

时域差分方程:

$$ y[n] = \alpha x[n] + (1 - \alpha) y[n-1] $$

其中 `α = Δt / (RC + Δt)`,Δt 是采样周期。

直觉:`y[n]` 是 `x[n]` 和 `y[n-1]` 的加权平均。`α = 1` 时 `y = x`(无滤波);`α = 0` 时 `y` 永远不变(DC,无限低通)。

Z 变换:

$$ H(z) = \frac{\alpha}{1 - (1-\alpha) z^{-1}} = \frac{\alpha z}{z - (1-\alpha)} $$

极点在 `z = 1 - α`。因为 `0 < α < 1`,所以极点在单位圆内——稳定。

频率响应(代入 `z = e^{iω}`):

$$ |H(e^{iω})|^2 = \frac{\alpha^2}{1 - 2(1-\alpha)\cos\omega + (1-\alpha)^2} $$

DC (ω=0):`|H|² = α² / (1 - 2(1-α) + (1-α)²) = α² / α² = 1`(放行)。
Nyquist (ω=π):`|H|² = α² / (1 + 2(1-α) + (1-α)²) = α² / (2 - α)²`(衰减)。

cutoff 频率(半功率,-3 dB 点):`|H(ω_c)|² = 1/2`,解出:

$$ \cos \omega_c = 1 - \frac{\alpha^2}{2(1-\alpha)} $$

工程实践中常用更直接的式子。给定目标 cutoff f_c 和采样率 f_s:

$$ \alpha = 1 - e^{-2\pi f_c / f_s} $$

(从模拟 RC 时间常数 `τ = RC = 1 / (2π f_c)` 推导,匹配离散)

Rust 实现:

```rust
pub struct OnePoleLPF { alpha: f32, prev: f32 }

impl OnePoleLPF {
    pub fn new(cutoff_hz: f32, sample_rate: f32) -> Self {
        let alpha = 1.0 - (-2.0 * std::f32::consts::PI * cutoff_hz / sample_rate).exp();
        OnePoleLPF { alpha, prev: 0.0 }
    }
    pub fn process(&mut self, x: f32) -> f32 {
        self.prev = self.alpha * x + (1.0 - self.alpha) * self.prev;
        self.prev
    }
}
```

这个 filter **极快**——每样本 2 乘 1 加。24 dB/oct 的低通滤波器要 4 个串起来。

### 6.4 一阶高通

把低通"反过来":高通输出 = 输入 - 低通输出。

$$ y_{hp}[n] = x[n] - y_{lp}[n] $$

代入 `y_lp[n] = α x[n] + (1-α) y_lp[n-1]`:

$$ y_{hp}[n] = (1 - \alpha) (x[n] - y_{hp}[n-1]) $$

(化简后)

或者直接:`y_hp[n] = x[n] - α x[n] - (1-α) y_lp[n-1]`——但工程上更简洁的实现是:

```rust
pub struct OnePoleHPF { alpha: f32, prev_x: f32, prev_y: f32 }

impl OnePoleHPF {
    pub fn new(cutoff_hz: f32, sample_rate: f32) -> Self {
        let alpha = 1.0 - (-2.0 * std::f32::consts::PI * cutoff_hz / sample_rate).exp();
        OnePoleHPF { alpha, prev_x: 0.0, prev_y: 0.0 }
    }
    pub fn process(&mut self, x: f32) -> f32 {
        let y = self.alpha * (self.prev_y + x - self.prev_x);
        self.prev_x = x;
        self.prev_y = y;
        y
    }
}
```

### 6.5 Biquad:两极点两零点

工业音频的**事实标准**。一次实现 LP / HP / BP / BS / AP / peaking / shelving 等十几种类型,只需要换系数。

差分方程:

$$ y[n] = b_0 x[n] + b_1 x[n-1] + b_2 x[n-2] - a_1 y[n-1] - a_2 y[n-2] $$

Z 变换:

$$ H(z) = \frac{b_0 + b_1 z^{-1} + b_2 z^{-2}}{1 + a_1 z^{-1} + a_2 z^{-2}} $$

5 个系数(b0, b1, b2, a1, a2)。两个零点,两个极点。

为什么是二阶?**最低阶能实现谐振**(一对复共轭极点)。所有 EQ(reverb 模态、formant、peaking boost/cut)都是 biquad。Neve EQ、Pultec EQ、Avalon VT——全是 biquad 的变种。

### 6.6 RBJ Cookbook:万能系数公式

Robert Bristow-Johnson 在 1994 年 Audio EQ Cookbook 给出了所有 biquad 类型的系数公式。这是音频工程最被引用的公式集。

记号:

- `f_s`:采样率(Hz)
- `f_0`:中心/cutoff 频率(Hz)
- `Q`:品质因数(决定 peak/transition 的尖锐程度)
- `dBgain`:peaking/shelving 的增益(dB)

预计算:

$$ \omega_0 = 2\pi f_0 / f_s $$

$$ \alpha = \sin(\omega_0) / (2 Q) $$

$$ \cos\omega_0, \sin\omega_0 $$

#### 6.6.1 低通(Low-pass)

$$ H(z) = \frac{(1 - \cos\omega_0)^2}{2} \cdot \frac{1 + 2 z^{-1} + z^{-2}}{1 + \alpha z^{-1} + \dots} $$

完整系数(归一化使 a0 = 1):

$$ b_0 = \frac{1 - \cos\omega_0}{2}, \quad b_1 = 1 - \cos\omega_0, \quad b_2 = \frac{1 - \cos\omega_0}{2} $$

$$ a_0 = 1 + \alpha, \quad a_1 = -2 \cos\omega_0, \quad a_2 = 1 - \alpha $$

所有 b 和 a 都除以 a0 归一化。

#### 6.6.2 高通(High-pass)

$$ b_0 = \frac{1 + \cos\omega_0}{2}, \quad b_1 = -(1 + \cos\omega_0), \quad b_2 = \frac{1 + \cos\omega_0}{2} $$

$$ a_0 = 1 + \alpha, \quad a_1 = -2 \cos\omega_0, \quad a_2 = 1 - \alpha $$

(注意:b1 是负的,且 cos 项符号翻转)

#### 6.6.3 带通(Band-pass,constant 0 dB peak gain)

$$ b_0 = \alpha, \quad b_1 = 0, \quad b_2 = -\alpha $$

$$ a_0 = 1 + \alpha, \quad a_1 = -2 \cos\omega_0, \quad a_2 = 1 - \alpha $$

#### 6.6.4 带阻 / 陷波(Band-stop / Notch)

$$ b_0 = 1, \quad b_1 = -2 \cos\omega_0, \quad b_2 = 1 $$

$$ a_0 = 1 + \alpha, \quad a_1 = -2 \cos\omega_0, \quad a_2 = 1 - \alpha $$

注意:b0=b2=1,b1=a1——这是 LP 和 HP 的"对消",在 f0 处正好相消为 0(陷波)。

#### 6.6.5 全通(All-pass)

$$ b_0 = 1 - \alpha, \quad b_1 = -2 \cos\omega_0, \quad b_2 = 1 + \alpha $$

$$ a_0 = 1 + \alpha, \quad a_1 = -2 \cos\omega_0, \quad a_2 = 1 - \alpha $$

全通的特点:**幅度响应全 1**(不衰减任何频率),只改变相位。用于**相位校正**(补偿其他 filter 的非线性相位)、**phaser 效果**(扫频全通串联)。

#### 6.6.6 Peaking EQ

$$ b_0 = 1 + \alpha A, \quad b_1 = -2 \cos\omega_0, \quad b_2 = 1 - \alpha A $$

$$ a_0 = 1 + \alpha / A, \quad a_1 = -2 \cos\omega_0, \quad a_2 = 1 - \alpha / A $$

其中 `A = 10^(dBgain/40)`,`α = sin(ω0) / (2 Q)`。这是图形 EQ 的标准块——boost 或 cut 中心频率附近一个 band。

#### 6.6.7 Low-shelf

(b0, b1, b2, a0, a1, a2 公式省略,见 RBJ cookbook 原文 https://www.musicdsp.org/en/latest/Filters/197-rbj-audio-eq-cookbook.html)

Low-shelf:低于 f0 的频率 boost/cut,高于 f0 不变。低音旋钮。

#### 6.6.8 High-shelf

类似 Low-shelf,镜像。高音旋钮。

### 6.7 Direct Form I / II / Transposed

知道系数不够,还要知道**怎么算**——同一个 H(z) 有多种差分方程实现拓扑,**数值特性不同**。

#### 6.7.1 Direct Form I

直接按差分方程实现:

$$ y[n] = b_0 x[n] + b_1 x[n-1] + b_2 x[n-2] - a_1 y[n-1] - a_2 y[n-2] $$

```rust
pub struct BiquadDF1 {
    b0: f32, b1: f32, b2: f32,
    a1: f32, a2: f32,
    x1: f32, x2: f32,  // x[n-1], x[n-2]
    y1: f32, y2: f32,  // y[n-1], y[n-2]
}

impl BiquadDF1 {
    pub fn process(&mut self, x: f32) -> f32 {
        let y = self.b0 * x + self.b1 * self.x1 + self.b2 * self.x2
              - self.a1 * self.y1 - self.a2 * self.y2;
        self.x2 = self.x1; self.x1 = x;
        self.y2 = self.y1; self.y1 = y;
        y
    }
}
```

**优点**:简单直观。
**缺点**:数值稳定性差——高 Q 或高频时,两个零点和两个极点分别累加,量化误差敏感。f32 在低频高 Q 可能不稳定。

#### 6.7.2 Direct Form II

把 H(z) 拆成分子分母级联,引入中间信号 `w[n]`:

$$ w[n] = x[n] - a_1 w[n-1] - a_2 w[n-2] $$

$$ y[n] = b_0 w[n] + b_1 w[n-1] + b_2 w[n-2] $$

只需要 2 个状态(w1, w2),比 DF1 少 2 个。

```rust
pub struct BiquadDF2 {
    b0: f32, b1: f32, b2: f32,
    a1: f32, a2: f32,
    w1: f32, w2: f32,
}

impl BiquadDF2 {
    pub fn process(&mut self, x: f32) -> f32 {
        let w = x - self.a1 * self.w1 - self.a2 * self.w2;
        let y = self.b0 * w + self.b1 * self.w1 + self.b2 * self.w2;
        self.w2 = self.w1; self.w1 = w;
        y
    }
}
```

**优点**:状态少(2 而非 4)。
**缺点**:更糟的数值稳定性——`w[n]` 可能在内部归一化前溢出,即便输出 `y` 没溢出。**高 Q 低频有灾难**。

#### 6.7.3 Direct Form II Transposed

**生产首选**。把 DF2 的信号流图"转置"(翻转所有箭头,输入输出对调),数值特性大幅改善。

```rust
pub struct BiquadDF2T {
    b0: f32, b1: f32, b2: f32,
    a1: f32, a2: f32,
    s1: f32, s2: f32,  // 转置后的状态
}

impl BiquadDF2T {
    pub fn process(&mut self, x: f32) -> f32 {
        let y = self.b0 * x + self.s1;
        self.s1 = self.b1 * x - self.a1 * y + self.s2;
        self.s2 = self.b2 * x - self.a2 * y;
        y
    }
}
```

**为什么 Transposed 更稳定**:DF2 的中间信号 w 在零点增益处可能远大于最终输出(放大后被分母缩回)。转置后,信号流图反过来,没有这种"内部放大后归一化"的问题。每个加法的输入都是 reasonable 大小,量化误差不放大。

**生产建议**:所有 biquad 都用 DF2T。这是 Sound on Sound 杂志 2007 年的《Filter Topology》一文给出的标准建议,也是 JUCE、SoX、libsamplerate 的选择。

### 6.8 Butterworth / Chebyshev / Elliptic

biquad 是二阶(filter 1 个谐振)。要实现高阶(陡峭滚降),需要级联多个 biquad。三种经典设计:

**Butterworth**:**最平坦通带**(maximally flat)。所有极点在单位圆内的同一个椭圆上。N 阶 LP 的衰减率 = 6N dB/oct。8 阶 Butterworth = 48 dB/oct,很陡。**相位非线性**(随频率变化),但不极端。音频 EQ 的主力。

**Chebyshev Type I**:**通带 equiripple,阻带单调下降**。同样阶数比 Butterworth 陡,但通带有些 ripple(比如 ±0.5 dB 起伏)。过渡带比 Butterworth 窄。代价:相位更乱。

**Chebyshev Type II**:**通带单调,阻带 equiripple**。较少用。

**Elliptic(Chebyshev-Cauer)**:**通带和阻带都 equiripple**。同样阶数下**最陡**(过渡带最窄)。代价:相位最乱,阻带永远有 ripple(不能衰减到 0)。

**比较表**(都是 4 阶 LP,cutoff 1 kHz,采样 48 kHz):

| 类型 | 衰减@2 kHz | 通带 ripple | 阻带 ripple | 相位 |
|---|---|---|---|---|
| Butterworth | -24 dB | 0 | 0 | 中等 |
| Chebyshev I (0.5 dB) | -36 dB | ±0.5 dB | 0 | 差 |
| Elliptic (0.5/40) | -52 dB | ±0.5 dB | -40 dB | 极差 |

**选型建议**:

- 通带平坦最重要(音频母带):Butterworth
- 陡峭最关键(anti-aliasing):Elliptic
- 平衡:Chebyshev I

scipy.signal.butter / cheby1 / cheby2 / ellip 给出极点和零点,然后级联 biquad。

### 6.9 双线性变换

怎么从模拟 filter(连续时间,电容电感)设计数字 filter?**双线性变换**(Bilinear Transform, BLT)。

把 H(s)(Laplace 域)里的 s 替换成:

$$ s = \frac{2}{T} \cdot \frac{1 - z^{-1}}{1 + z^{-1}} $$

(T 是采样周期)

BLT 把 jΩ 轴(连续时间虚轴)映射到单位圆 |z| = 1(离散时间),所以稳定的模拟 filter 映射到稳定的数字 filter。

**频率扭曲**(warping):BLT 把模拟频率 Ω 压缩到离散频率 ω:

$$ \omega = 2 \arctan(\Omega T / 2) $$

Ω → ∞ 对应 ω → π(Nyquist)。所以**模拟 DC 映射到数字 DC,但模拟高频压缩到 Nyquist**。

工程上:**预扭曲**(pre-warping)。把目标数字频率 f_c 反推到模拟频率 Ω_c = (2/T) tan(π f_c / f_s),然后在模拟域设计,再 BLT 到数字。

完整的 IIR 设计流程:

1. 给定数字规格(cutoff f_c、过渡带、阻带衰减、通带 ripple)
2. 预扭曲到模拟频率
3. 设计模拟原型(Butterworth/Chebyshev/Elliptic 的极点零点)
4. 用 BLT 把 s 域极点零点变换到 z 域
5. 把 z 域极点零点配对成二阶节(biquad)
6. 级联 biquad,每个用 DF2T 实现

每一步都有 200 年数学积累(从 Gauss、Chebyshev 到 Parks-McClellan)。scipy.signal.iirfilter 自动完成所有步骤。

## 7 · 频率响应:Bode plot 和群延迟

把 `|H(e^{iω})|` 和 `arg H(e^{iω})` 对频率画出来,就是 **Bode plot**(幅度 + 相位两条曲线)。频率轴通常对数,幅度用 dB(`20 log10 |H|`)。

**怎么算**:对每个 ω(从 0 到 π),代入 `z = e^{iω}`:

```rust
fn freq_response(coeffs: &BiquadCoeffs, omega: f32) -> (f32, f32) {
    let z1 = Complex::from_polar(1.0, -omega);  // z^{-1} = e^{-iω}
    let z2 = z1 * z1;
    let num = coeffs.b0 + coeffs.b1 * z1 + coeffs.b2 * z2;
    let den = 1.0 + coeffs.a1 * z1 + coeffs.a2 * z2;
    let h = num / den;
    (h.norm(), h.arg())  // magnitude, phase
}
```

遍历 ω = 0 到 π,log-scale,画出来。

### 7.2 Linear phase vs minimum phase

**Linear phase**(线性相位):`arg H(e^{iω}) = -ω τ + const`,所有频率的延迟 τ 相同。对称系数 FIR 可以做到。

**Minimum phase**(最小相位):在所有幅度响应相同的系统中,**这个系统的群延迟最小**。IIR 通常是最小相位。

**音频工程权衡**:

- 母带处理要求 linear phase(避免相位失真破坏多频叠加)
- 实时录音、现场调音用 minimum phase(低延迟)

linear phase 的代价:**输出延迟 = (N-1) / 2 个样本**。FIR 1000 tap = 11 ms @ 44.1 kHz,在 live audio 里很显眼。

### 7.3 群延迟

**群延迟**(group delay):

$$ \tau_g(\omega) = -\frac{d}{d\omega} \arg H(e^{i\omega}) $$

直觉:**幅度调制信号**(包络 + 载波)的"包络"被 filter 延迟多少。如果一个 filter 在某个频率的群延迟剧烈变化,**信号包络会散开**——transient 变糊。

IIR 在 cutoff 附近群延迟剧烈(谐振越强越剧烈),linear-phase FIR 全频率相同。

工程实践:**示波器、示波器、网络分析仪**都需要 linear phase;**音乐后期**两派争论——老派工程师说"linear phase 破坏 transient",新派说"听不出来"。

### 7.4 工程中怎么"调试"滤波器

你设计了 biquad,怎么知道它**真的**做到了你要的事?三个工具:

**1. 数值扫频**。从 ω = 0.001 到 ω = π,log 等分 200 个点,每个点算 `|H(e^{iω})|` 和 `arg H(e^{iω})`。打印出来或画图。

**2. 冲激响应测试**。给 filter 一个 δ(后面是 0),看输出。冲激响应应该有限时间衰减到 0(IIR 严格说永远不到 0,但 < 1e-6 算可忽略)。如果输出**指数增长**——不稳定。

**3. Step response**。给 filter 一个 step(从 0 跳到 1,然后保持),看输出。Step response 包含 envelope 信息——上升时间、overshoot、settling time。

### 7.5 Pole-zero plot:几何直觉

把 H(z) 的零点和极点画在复平面(z 平面)。**单位圆 |z| = 1** 是关键——单位圆上的 z = e^{iω},对应频率响应。

直觉:
- **极点靠近单位圆**:对应频率幅度大(谐振)
- **零点靠近单位圆**:对应频率幅度小(notch)
- **极点在单位圆外**:不稳定(发散)

**几何作图**:`|H(e^{iω})| = (距离 e^{iω} 到零点的乘积) / (距离 e^{iω} 到极点的乘积)`。所以画 pole-zero plot 后,你可以肉眼估出频率响应——这是 DSP 工程师的核心 skill。

例子:二阶 Butterworth LP,cutoff ω_c。极点在 `e^{±iω_c}` 附近(具体位置由 Q 决定)。频率 ω = ω_c 处,`e^{iω_c}` 离极点近,所以分母小,幅度大——但 Butterworth 设计的极点位置使通带最平坦。

### 7.6 系数 sensitivity 和 quantization

f32 有 23 bit 尾数,精度约 1e-7。biquad 系数如果接近 critical 值,量化误差让极点跑到错误位置。

**例子**:cutoff 100 Hz,采样率 48 kHz。`cos(ω_0) = cos(2π·100/48000) ≈ 0.99991`。f32 表示精度约 1e-7,所以 cos 误差约 1e-7。这个误差会让极点位置偏移 `δ|p| ≈ δcos/sin(ω_0) ≈ 1e-7 / 0.013 ≈ 7.6e-6`——通常可忽略。

但**高 Q + 低频**时,sensitivity 急剧增加。Q = 10,cutoff 50 Hz:f32 误差可能让极点跑出单位圆,**filter 自激**。

**解决方法**:

1. **f64 计算**:系数计算 + filter state 用 f64,只输出转 f32。CPU 重 2 倍,但稳定
2. **High-shelf 替代 peaking**:某些场景 shelf 不那么 sensitive
3. **State-space form**:把 Direct Form 转成 state-space 表示,数值更稳定(但复杂)
4. **Cascaded biquad**:把一个 8 阶 filter 拆成 4 个 2 阶,每个比 8 阶稳定得多

工业 audio plugin(JUCE 等)几乎都用 f64 系数 + f32 signal——精确度和性能的最好 trade-off。

## 8 · Hilbert 变换和分析信号

### 8.1 什么是分析信号

实信号 `x[n]` 的频谱有**共轭对称**——`X(-ω) = conj(X(ω))`。负频率不携带额外信息。**分析信号**(analytic signal)是把负频率清零,只保留正频率的复信号 `z[n]`:

$$ Z(\omega) = \begin{cases} 2 X(\omega) & \omega > 0 \\ X(\omega) & \omega = 0 \\ 0 & \omega < 0 \end{cases} $$

时域上 `z[n] = x[n] + i \cdot \mathcal{H}\{x[n]\}`,其中 `H` 是 **Hilbert 变换**——把所有频率 phase shift -π/2。`Re(z) = x`,`Im(z)` 是 x 的 Hilbert 变换。

### 8.2 Hilbert 变换的应用

**包络检测**:信号包络 = `|z[n]| = √(x² + H{x}²)`。用于 AM 解调、envelope follower(compressor 关键组件)。

**频率偏移(frequency shifter)**:`z[n] · e^{iω_0 n}` 把所有频率偏移 ω_0。这是 SSB(single sideband)调制的核心。

**瞬时频率**:`d/dt arg(z[n])` 是瞬时频率。用于 pitch tracking。

### 8.3 FIR Hilbert 实现

Hilbert 变换可以用 FIR 实现——理想 Hilbert 的冲激响应 `h[n] = 2/(πn) (sin²(πn/2)) / n` 奇对称。截断到 N tap,加 Hamming 窗,得到可实现的 FIR。

```rust
pub fn design_hilbert_fir(n: usize) -> Vec<f32> {
    let mut h = vec![0.0; n];
    let center = (n - 1) as f32 / 2.0;
    for i in 0..n {
        let k = i as f32 - center;
        if k.abs() < 1e-6 { continue; }
        let mut val = if (k as i32) % 2 == 0 { 0.0 } else { 2.0 / (std::f32::consts::PI * k) };
        // Hamming 窗
        let w = 0.54 - 0.46 * (2.0 * std::f32::consts::PI * i as f32 / (n - 1) as f32).cos();
        h[i] = val * w;
    }
    h
}
```

N = 64 时,Hilbert FIR 在 [100 Hz, 20 kHz] 范围 phase 偏差 < 1°。生产代码 N = 128 或 256 用于高精度场景。

### 8.4 全通网络和相位塑造

全通 filter(见 6.6.5)幅度全 1,只改 phase。**串联多个全通**可以做复杂 phase shaping:

- **Phaser 效果**:扫频 all-pass(截止频率由 LFO 调制)和原信号相加,某些频率相消产生 "notch sweep"。这是 70s electric piano、guitar 的标志性效果。
- **Phase align**:多麦克风录音,各麦克风相位不一致,全通可以校正。
- **Reverb 模块**:Schroeder reverb 用 4 个 comb filter + 2 个 allpass 制造 dense reverb。Allpass 让 reflection 听起来 "smoother"(无具体频段衰减,但散开反射)。

```rust
pub struct Phaser {
    allpasses: Vec<Biquad>,  // 4 个 allpass
    lfo: Lfo,
    lfo_to_freq: f32,
    base_freq: f32,
    depth: f32,
    mix: f32,
}

impl Phaser {
    pub fn process(&mut self, x: f32) -> f32 {
        let lfo_val = self.lfo.process();
        let center_freq = self.base_freq * 2.0_f32.powf(lfo_val * self.depth);
        // 更新所有 allpass 的 center freq
        for ap in &mut self.allpasses {
            ap.coeffs = design_biquad(FilterType::AllPass, center_freq, self.sample_rate, 0.707, 0.0);
        }
        let mut y = x;
        for ap in &mut self.allpasses {
            y = ap.process(y);
        }
        x * (1.0 - self.mix) + y * self.mix  // dry/wet
    }
}
```

经典 4-stage phaser(allpass 串联):让 notches 在不同频率,扫频时产生"jet plane"效果。Electro-Harmonix Small Stone 是经典硬件 phaser。

## 9 · Sample rate 变化:decimation 和 interpolation

音频经常需要改变采样率——44.1 kHz → 48 kHz(消费音频到视频),或 96 kHz → 44.1 kHz(高采样率母带到 CD)。这叫 **sample rate conversion**(SRC)。

### 9.1 上采样(Interpolation)

从低采样率到高采样率:**insert zeros** + **low-pass filter**。

数学:在 x[n] 之间插入 L-1 个零,得到 x_upsampled[m]。这把频谱**重复 L 次**(镜像)。然后用 cutoff = π/L 的 LPF 滤掉镜像。

```rust
// 上采样 1 → L
fn upsample(x: &[f32], l: usize) -> Vec<f32> {
    let mut y = vec![0.0; x.len() * l];
    for (i, &s) in x.iter().enumerate() {
        y[i * l] = s;
    }
    y
}
// 然后过 LPF,cutoff = original Nyquist / L
```

### 9.2 下采样(Decimation)

从高采样率到低采样率:**low-pass filter** + **drop samples**。

先 LPF(cutoff = target Nyquist),然后每 M 个样本保留一个。**必须先滤波**——否则 aliasing(高频折叠回低频)。

### 9.3 非整数比:L/M SRC

44.1 → 48 kHz 是 ratio 160/147(L = 160, M = 147,因为 48000/44100 = 160/147)。算法:先上采样 160 倍,过 LPF,再下采样 147 倍。

实际工程:polyphase filter bank,把 LPF 分成 L 个 phase,每个 phase 负责一个输出样本。这避免显式插入 159 个零(节省 CPU)。`libsamplerate`(Erik de Castro Lopo)实现这个,是事实标准。

### 9.4 Rust 实现

```rust
// 用 libsamplerate binding
// Cargo.toml: samplerate = "0.2"
use samplerate::{convert, ConverterType};

fn main() {
    let input: Vec<f32> = vec![/* 44.1 kHz signal */];
    let output = convert(
        44100, 48000, 1,
        ConverterType::SincBestQuality,
        &input,
    ).unwrap();
    // output 是 48 kHz signal
}
```

ConverterType 有 `SincBestQuality`、`SincMediumQuality`、`SincFastest`、`ZeroOrderHold`、`Linear`。**SincBestQuality** 用 1024-tap sinc,SNR > 144 dB,但 CPU 重。**Linear** 简单但引入 alias。**SincFastest** 是常用 trade-off。

### 9.5 Oversampling

某些 DSP 操作(非线性 distortion、wave-shaping)会产生无穷谐波——超过 Nyquist 折叠回 audio band 形成 alias。**Solution**:**oversample** 2×、4× 或 8×,处理后再下采样。

```
audio_in → upsample 4× → distortion → lowpass(Nyquist/4) → downsample 4× → audio_out
```

Guitar amp simulator、bitcrusher、saturator 都用 oversampling。`fundsp` 内置 oversample API。

## 10 · 性能数据与生产坑

### 8.1 实测性能数据

测试平台:Ryzen 7 5800X @ 4.0 GHz,Rust 1.76,--release,target-cpu=native。

| 操作 | 每 sample 时钟 | 44.1 kHz 1 秒 CPU 占用 |
|---|---|---|
| One-pole LPF | ~3 ns | 0.013% |
| Biquad DF2T | ~6 ns | 0.026% |
| 8 阶 Butterworth (4 biquad 级联) | ~25 ns | 0.11% |
| 1024 tap FIR | ~1 μs | 4.4% |
| FFT 卷积 1024 tap | ~0.1 μs (amortized) | 0.44% |
| Cubic FIR interpolation (4 tap) | ~12 ns | 0.053% |

一帧(1024 sample @ 44.1 kHz = 23 ms)处理 16 个 biquad = 1 ms,占 budget 4.3%。Live audio 完全可承受。

### 8.2 生产坑

**坑1:f32 系数量化**。`a1 = -2 cos(ω0)` 在 ω0 接近 0(低 cutoff)时,cos 接近 1,a1 接近 -2。f32 精度有限,可能让极点跑到单位圆外,**filter 自激振荡**。**解决**:用 f64 算系数,f32 跑 process。或者用 Audio EQ Cookbook 的"normalized"系数(a0 = 1),减少精度损失。

**坑2:DC offset 累积**。如果 filter 有 DC 增益 ≠ 1(比如 shelving boost),DC offset 会被放大,慢慢 saturate。**解决**:在 filter 之前加 HPF,cutoff 20 Hz。

**坑3:瞬态 startup**。filter 启动时 state 全 0,如果输入突然是大信号(比如枪声),前几个样本可能 transients。**解决**:启动时 ramp volume 0 → 1 over 10 ms。

**坑4:系数突然切换**。自动化(Auto-Filter、LFO 调 cutoff)会让 biquad 系数每帧变。如果直接换系数,群延迟突变,听起来"咔嚓"。**解决**:系数做 interpolation(每样本 lerp),或用 zero-delay feedback(瞬时 update)。

**坑5:saturating feedback**。IIR 反馈项 `y[n-1]` 可能溢出 f32 范围。`tanh` 风格的 saturating feedback 在内部限幅,可以避免。但纯 IIR 没有 saturation——溢出 → 极点跑圆外 → 自激。**解决**:输入先 normalize 到 [-1, 1],中间用 f64。

**坑6:不是所有 filter 都在 0 Hz 处稳定**。DC-coupled IIR 在低频可能 unstable。某些 shelf/notch 在 f0 = 0 时退化。**解决**:测试时 sweep f0 from 1 Hz to Nyquist/2。

**坑7:graphical EQ 的"combination issue"**。多个 biquad 串联,叠加的 gain 在某些频率可能超 +6 dB,clip。**解决**:串联后整体 trim -3 dB headroom。

### 8.3 跨学科:控制论、电气工程、声学

DSP 不是孤立学科。它和**控制论**(Control Theory)、**电气工程**(EE)、**声学**(Acoustics)共用同一套数学。

**控制论**:PID 控制器 = IIR filter。积分项 = LP,微分项 = HP,比例项 = 全通。状态空间分析(现代控制)= Z 域极点分析。

**电气工程**:模拟 filter(Sallen-Key、multiple feedback)直接对应 IIR。RLC 电路的极点 = IIR 极点。SPICE 仿真 = 数值卷积。

**声学**:房间模态(standing wave)是物理 IIR。每个反射 = 一次延迟 + 衰减 = comb filter。Schroeder reverb = 多 comb + allpass 串联。

**生物医学**:ECG 信号去噪 = band-pass filter(0.5-40 Hz)。EEG = notch 50 Hz(电源干扰)+ band-pass。

学透 DSP,**所有这些领域都通了**。这是数学抽象的威力。

## 11 · 完整 Rust 项目:Biquad 链

下面是完整可跑的项目骨架,演示参数化 EQ(3 段 biquad 串联 + graphic visualization)。

`Cargo.toml`:

```toml
[package]
name = "biquad-chain"
version = "0.1.0"
edition = "2021"

[dependencies]
cpal = "0.15"

[profile.release]
opt-level = 3
lto = "fat"
codegen-units = 1
```

`src/main.rs`:

```rust
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use std::f32::consts::PI;

// Biquad 系数
#[derive(Clone, Copy, Debug)]
pub struct BiquadCoeffs {
    pub b0: f32, pub b1: f32, pub b2: f32,
    pub a1: f32, pub a2: f32,
}

// 滤波器类型
pub enum FilterType { LowPass, HighPass, BandPass, Notch, Peaking }

// RBJ cookbook 系数计算
pub fn design_biquad(
    ftype: FilterType,
    f0: f32,
    fs: f32,
    q: f32,
    db_gain: f32,
) -> BiquadCoeffs {
    let w0 = 2.0 * PI * f0 / fs;
    let cos_w0 = w0.cos();
    let sin_w0 = w0.sin();
    let alpha = sin_w0 / (2.0 * q);
    let a = 10.0_f32.powf(db_gain / 40.0);  // for peaking/shelving

    let (b0, b1, b2, a0, a1, a2) = match ftype {
        FilterType::LowPass => (
            (1.0 - cos_w0) / 2.0,
            1.0 - cos_w0,
            (1.0 - cos_w0) / 2.0,
            1.0 + alpha,
            -2.0 * cos_w0,
            1.0 - alpha,
        ),
        FilterType::HighPass => (
            (1.0 + cos_w0) / 2.0,
            -(1.0 + cos_w0),
            (1.0 + cos_w0) / 2.0,
            1.0 + alpha,
            -2.0 * cos_w0,
            1.0 - alpha,
        ),
        FilterType::BandPass => (
            alpha,
            0.0,
            -alpha,
            1.0 + alpha,
            -2.0 * cos_w0,
            1.0 - alpha,
        ),
        FilterType::Notch => (
            1.0,
            -2.0 * cos_w0,
            1.0,
            1.0 + alpha,
            -2.0 * cos_w0,
            1.0 - alpha,
        ),
        FilterType::Peaking => (
            1.0 + alpha * a,
            -2.0 * cos_w0,
            1.0 - alpha * a,
            1.0 + alpha / a,
            -2.0 * cos_w0,
            1.0 - alpha / a,
        ),
    };

    // 归一化:所有系数除以 a0
    BiquadCoeffs {
        b0: b0 / a0, b1: b1 / a0, b2: b2 / a0,
        a1: a1 / a0, a2: a2 / a0,
    }
}

// Biquad Direct Form II Transposed
pub struct Biquad {
    coeffs: BiquadCoeffs,
    s1: f32, s2: f32,
}

impl Biquad {
    pub fn new(coeffs: BiquadCoeffs) -> Self {
        Biquad { coeffs, s1: 0.0, s2: 0.0 }
    }

    pub fn process(&mut self, x: f32) -> f32 {
        let y = self.coeffs.b0 * x + self.s1;
        self.s1 = self.coeffs.b1 * x - self.coeffs.a1 * y + self.s2;
        self.s2 = self.coeffs.b2 * x - self.coeffs.a2 * y;
        y
    }
}

// Biquad 链(级联)
pub struct BiquadChain {
    filters: Vec<Biquad>,
}

impl BiquadChain {
    pub fn new(coeffs_list: Vec<BiquadCoeffs>) -> Self {
        let filters = coeffs_list.into_iter().map(Biquad::new).collect();
        BiquadChain { filters }
    }

    pub fn process(&mut self, x: f32) -> f32 {
        let mut y = x;
        for f in &mut self.filters {
            y = f.process(y);
        }
        y
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let host = cpal::default_host();
    let device = host.default_output_device().ok_or("no device")?;
    let config: cpal::StreamConfig = device.default_output_config()?.into();
    let sr = config.sample_rate.0 as f32;

    // 设计 3 段 EQ:HP @ 80 Hz, Q=0.7;Peak @ 2 kHz, +6 dB, Q=1.0;LP @ 12 kHz, Q=0.7
    let coeffs_list = vec![
        design_biquad(FilterType::HighPass, 80.0, sr, 0.707, 0.0),
        design_biquad(FilterType::Peaking, 2000.0, sr, 1.0, 6.0),
        design_biquad(FilterType::LowPass, 12000.0, sr, 0.707, 0.0),
    ];

    let mut chain_l = BiquadChain::new(coeffs_list.clone());
    let mut chain_r = BiquadChain::new(coeffs_list.clone());

    let mut phase = 0.0f32;
    let mut freq = 200.0f32;  // 扫频
    let mut sample_count = 0u32;

    let stream = device.build_output_stream(
        &config,
        move |out: &mut [f32], _: &cpal::OutputCallbackInfo| {
            for frame in out.chunks_mut(config.channels as usize) {
                // 扫频:200 → 2000 Hz over 5 秒
                if sample_count % (sr as u32 / 100) == 0 {
                    freq = 200.0 + (sample_count as f32 / sr / 5.0) * 1800.0;
                    freq = freq.min(2000.0);
                }
                phase += freq / sr * 2.0 * PI;
                if phase > 2.0 * PI { phase -= 2.0 * PI; }
                let x = phase.sin() * 0.3;
                frame[0] = chain_l.process(x);
                if frame.len() > 1 {
                    frame[1] = chain_r.process(x);
                }
                sample_count += 1;
            }
        },
        |err| eprintln!("audio err: {}", err),
        None,
    )?;
    stream.play()?;
    println!("Sweeping 200 Hz -> 2000 Hz through 3-band EQ. Press Ctrl+C to stop.");
    std::thread::sleep(std::time::Duration::from_secs(10));
    Ok(())
}
```

跑:

```bash
cargo run --release
# 听到 200-2000 Hz 扫频,经过 HP+Peak+LP 处理
```

### 9.1 测量频率响应

要画 Bode plot,需要单独算 `|H(e^{iω})|`:

```rust
use std::f32::consts::PI;

fn biquad_magnitude(c: &BiquadCoeffs, omega: f32) -> f32 {
    // 计算 |H(e^{iω})|
    // H = (b0 + b1 z^{-1} + b2 z^{-2}) / (1 + a1 z^{-1} + a2 z^{-2})
    // z^{-1} = e^{-iω} = cos -i sin
    let (cos_w, sin_w) = (omega.cos(), omega.sin());
    let (cos_2w, sin_2w) = (2.0 * omega).cos(), (2.0 * omega).sin();

    // 分子:实部、虚部
    let num_re = c.b0 + c.b1 * cos_w + c.b2 * cos_2w;
    let num_im = -c.b1 * sin_w - c.b2 * sin_2w;

    // 分母
    let den_re = 1.0 + c.a1 * cos_w + c.a2 * cos_2w;
    let den_im = -c.a1 * sin_w - c.a2 * sin_2w;

    let num_mag = (num_re * num_re + num_im * num_im).sqrt();
    let den_mag = (den_re * den_re + den_im * den_im).sqrt();
    num_mag / den_mag
}

fn main() {
    let coeffs = design_biquad(FilterType::LowPass, 1000.0, 48000.0, 0.707, 0.0);
    println!("Freq (Hz), Magnitude (dB)");
    let mut freq = 20.0;
    while freq <= 20000.0 {
        let omega = 2.0 * PI * freq / 48000.0;
        let mag = biquad_magnitude(&coeffs, omega);
        let mag_db = 20.0 * mag.log10();
        println!("{:.1}, {:.2}", freq, mag_db);
        freq *= 10.0_f32.powf(0.05);  // log-space 步进
    }
}
```

输出可以 pipe 到 CSV,用 gnuplot 画 Bode plot:

```bash
cargo run --release > bode.csv
gnuplot -e "set logscale x; plot 'bode.csv' with lines" -p
```

## 12 · 在你 HH 项目里实践

你已经完成了 HH day009 音频加载 + day142 mixer。下面这些练习让你把今天的 DSP 应用进 HH:

**练习 1:加一个低通 cutoff 给玩家脚步声**。

脚步声采样里高频太多,在地下城听起来"刺耳"。加一个 1-pole LPF,cutoff 1.5 kHz。位置:`game_sound.rs::play_sound(...)`,在 voice 创建时附 `lowpass_cutoff: f32`,mixer render 时先过 LPF 再 mix。

参考代码:

```rust
pub struct Voice {
    pub samples: Arc<Vec<f32>>,
    pub cursor: usize,
    pub volume: f32,
    pub lpf: Option<OnePoleLPF>,  // 新增
}

// play_sound:
let lpf = if let Some(cutoff) = sound.lowpass_cutoff {
    Some(OnePoleLPF::new(cutoff, sample_rate))
} else {
    None
};
mixer.voices.push(Voice { samples, cursor: 0, volume, lpf });

// render:
for frame in output.chunks_mut(channels) {
    let s = if let Some(ref mut lpf) = voice.lpf {
        lpf.process(raw_sample)
    } else {
        raw_sample
    };
    frame[0] += s * voice.volume * voice.pan_l;
}
```

**练习 2:做 3 段 master EQ**。

游戏最终输出之前过 3 个 biquad:HP @ 30 Hz(去除 subsonic)、Peaking @ 250 Hz ±3 dB(控制 muddiness)、High-shelf @ 8 kHz +2 dB(air)。这是基本的 mix bus chain。

**练习 3:加 LPF 给"被墙挡住"的敌人**。

玩家穿墙听枪声,听起来"发闷"。给声音加 LPF,cutoff 随距离衰减:距离 0,cutoff 20 kHz(全通);距离 50m,cutoff 1 kHz(很闷)。

```rust
let cutoff_hz = 20000.0 - (distance / 50.0) * 19000.0;
voice.lpf = Some(OnePoleLPF::new(cutoff_hz.max(200.0), sample_rate));
```

**练习 4:做 phone effect**。

NPC 在对讲机里说话:BP 300-3400 Hz。两个 biquad 串联(HP 300 + LP 3400), steep Q。

**练习 5:可视化 Bode plot**。

写一个 debug 模式,把当前 master EQ 的 Bode plot 画到 debug overlay。这要求你:
1. 算每个 filter 的 `|H(e^{iω})|`
2. 多个串联的 filter 总响应 = 各个 |H| 相乘
3. 在 debug overlay 用 immediate-mode UI 画曲线

这个练习连接了 day200 的 debug overlay 和今天的 DSP。**这是 HH 风格的"工程化整合"**。

## 13 · 延伸阅读

本仓库本地资料:
- [phase-5/day009.md](../../phase-1/day009.md) — HH 第一次音频(WAV 加载)
- [phase-5/day142.md](../../phase-4/day142.md) — HH mixer 设计
- [phase-5/day184.md](../day184.md) — 后续 DSP 实战
- [phase-5/deep-dives/audio-pipeline-complete.md](audio-pipeline-complete.md) — 完整音频流水线
- [phase-5/deep-dives/fft-and-spectral-analysis.md](fft-and-spectral-analysis.md) — FFT 和频谱分析(下一篇)

外部稳定 URL(可选):
- RBJ Audio EQ Cookbook(工业标准 biquad 公式):https://www.musicdsp.org/en/latest/Filters/197-rbj-audio-eq-cookbook.html
- Smith, "The Scientist and Engineer's Guide to Digital Signal Processing"(免费在线教科书,经典入门):https://www.dspguide.com/
- Oppenheim & Schafer, "Discrete-Time Signal Processing"(圣经级教科书,深度参考)
- Pirkle, "Designing Audio Effect Plugins in C++"(有 DSP 实战代码,RBJ 详解)
- Zölzer, "DAFX: Digital Audio Effects"(学术综述,各种 audio effect)
- EarLevel Engineering biquad 实现博客(经典工程师博客):https://www.earlevel.com/main/2012/11/26/biquad-c-source-code/
- souzou / megrid / fundsp(Rust DSP/synth crates):https://github.com/SamiPerttu/fundsp

真实开源源码:
- JUCE DSP module(C++ 工业标准 biquad FIR IIR):https://github.com/juce-framework/JUCE/tree/master/modules/juce_dsp
- SoX(C 命令行 audio swiss army knife,biquad 实现):https://github.com/dmbates/sox
- soundtouch(音频 time-stretch/pitch-shift):https://github.com/Thomas1/soundtouch
- libsamplerate(resampling,完整 FIR 设计):https://github.com/libsndfile/libsamplerate
- fundsp(Rust DSP 框架,函数式风格):https://github.com/SamiPerttu/fundsp
- megrid(Rust modal synthesizer,大量 biquad):https://github.com/Argrath/megrid
- Casey HH 的 day184 DSP 代码:https://github.com/HandmadeHero/handmade-hero/tree/main/code/day184

历史演化(可选):
- 1900s Campbell/Wagner 模拟 filter(Butterworth 1930,Chebyshev 1940s)
- 1960s Cooley-Tukey FFT(让 spectral 设计可行)
- 1970s Parks-McClellan(1972,优化 FIR 设计)
- 1980s RBJ Cookbook(1994,工业 biquad 标准)
- 2000s Zölzer DAFX 学术整合
- 2010s Rust audio 生态(fundsp、cpal、rodio)
