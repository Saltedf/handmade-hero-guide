---
phase: 5
title_en: "Convolution Reverb and HRTF"
title_zh: "卷积混响与 HRTF:从脉冲响应到三维双耳音频"
type: deep-dive
difficulty: advanced
duration: 90
domains: [game, audio, rust, linux, math]
prereqs: [audio-effects, adaptive-audio-and-3d, dsp-fundamentals, fft-and-spectral-analysis, phase-0/22-signals-foundation]
calibration: "卷积混响(convolution reverb)+ 脉冲响应(IR)+ HRTF 空间音频深做"
bridges: ["day138", "day201", "day526"]
---

# 卷积混响与 HRTF

> 你的 HH 项目里 footstep 播出来还是同一个"嗒"。把它放在你刚搭好的 cathedral 大教堂、放在 1.5 米宽的 closet 储物间、放在 cave 洞穴里——播出来的还是那个"嗒"。枪声在大厅里、在巷道里听上去一模一样。打开 [audio-effects.md](./audio-effects.md) 你写了 Schroeder reverb、写了 Freeverb、写了 FDN,这些算法混响(algorithmic reverb)用 comb + allpass 或 feedback delay network **逼近**一个空间,听起来温暖、可调、CPU 友好——但它们是**合成的**,像一个"通用房间",不是某个具体的教堂。这一篇做的是另一件事:**把一个真实空间的"声学指纹"录下来,塞进你的代码**。你录到的那个脉冲响应(impulse response,IR)文件,描述了"这个空间对一声枪响如何回应"——把它和你的 dry footstep 卷起来,footstep 就**真的在这个空间里响**了。这就是 AAA 游戏音频"为什么听起来那么真实"的底层秘密。同一篇里,我们再把这个"用 IR 描述一个系统"的思路推到极致:HRTF(Head-Related Transfer Function)是**你的头、躯干、耳廓对来自某方向的声音如何塑形**的脉冲响应,把它和任何 mono 声音卷起来,耳机里的声音就从"在你脑壳里"跳到了"从左前方 1 米外传来"。这一篇把**卷积混响**和 **HRTF 双耳渲染**两件事,从数学第一性原理一直推到你 HH 项目里能跑的 Rust 代码。

## 0 · 一对耳塞,两个世界

先把"为什么值得做"摆在桌上。把你的 HH 项目编一个 release,戴上耳机,走进你刚做的 cathedral 房间。Footstep 响——还是你 8 个月前录的干 sample。你心里清楚这间教堂的穹顶应该让那一声"嗒"膨胀成一团羽白色的残响尾音,拖个 2.5 秒才慢慢散去。可是没有。你的 reverb send 给了一个 Freeverb,听感是"通用 hall",很温暖,但不是**这间**教堂——是任何一间教堂。

现在换一件事。打开某个 AAA 游戏,走进同一类空间。Footstep 响——你听到的是**那一间具体教堂的回声**:有穹顶特有的早期反射 timing,有石材墙面的高频散射,有侧廊形成的梳状 echo。为什么这么像?因为音频设计师带着录音设备去过**那一间教堂**,在祭坛前放了发令枪(或扫频扬声器),录下空间的整个响应,处理成一个两秒长的 WAV——脉冲响应。游戏运行时,你的 footstep sample 被拿来与这个 IR 做实时卷积,输出的是"你的 footstep 在那间教堂里真的播放一遍"会有的声音。**算法 reverb 逼近空间的统计特性,卷积混响复制空间的全部声学指纹。**代价当然有——卷积比 comb/allpass 贵得多,所以游戏只在"hero moments"(hero room、cinematic、cutscene)才上完整的卷积混响。这就是为什么你需要看懂这一篇:既要知道什么时候上卷积,也要知道为什么不是所有时候都上。

把这件事再推一步。耳机里听到的声音有个老问题:它"在你脑壳里",不在外面。原因是你用普通 stereo pan 把声音分到左右声道,但你的真实听觉系统靠的是**两只耳朵收到的差异**——时间差、强度差、耳廓带来的频谱凹槽——来反推声源方向。Stereo pan 只编码了"左右能量分配",丢掉了所有方向线索。HRTF 就是这个差异的频域表征,本质上是"从某个方向来的声音到达你鼓膜"的脉冲响应。把它和 mono 声音卷起来送到耳机,声音就从脑壳里跳到了外面——你能听见它在左前方、右后方、头顶上。这是 PS5 Tempest 3D Audio、Steam Audio、Resonance Audio、Oculus Audio 全部在做的事。**卷积混响与 HRTF 共享同一种数学操作——卷积——只是被卷的 IR 描述的系统不同:一个是房间,一个是头。**

读完这一篇,你应该能:

- 直观地、数学地、实现地解释**卷积**这一种操作:为什么它能把"空间"施加到"信号"上
- 解释**脉冲响应**为什么是 LTI(linear time-invariant)系统的完整表征,把这一篇和 [phase-0/22-signals-foundation](../../phase-0/22-signals-foundation.md) 接起来
- 解释为什么朴素的 O(N·M) 卷积在实时音频里不可行,以及 **FFT 卷积**如何把复杂度压到 O(N log N)
- 解释 **overlap-add / overlap-save** 为什么是实时音频的必须,以及 partitioned convolution 如何把延迟压到一帧以内
- 解释 **HRTF** 的物理意义,知道 HRIR(head-related impulse response)和 IR 在概念上的对应关系
- 推导 **ITD 与 ILD**(双耳时间差与强度差)这两个 HRTF 内含的主要线索
- 实现**移动声源的 HRTF 插值**,以及为什么 generic HRTF 是工程妥协
- 解释 Steam Audio、Oculus Audio、Resonance Audio 这些工业级 spatial audio middleware **内部到底在做什么**,让你能在选型时知道选的什么
- 在你 HH 项目里**真的卷一次**:抓一个 IR,卷一个 dry sample,听见那个空间;再用公开 HRTF 数据集写一个把 mono 声音绕头转一圈的 panner,戴上耳机听见它在你脑外

假设你已掌握:**[phase-0/22-signals-foundation](../../phase-0/22-signals-foundation.md)**(LTI 系统、Nyquist、Fourier 基础)、**[dsp-fundamentals](./dsp-fundamentals.md)**(FIR/IIR/卷积/离散信号)、**[fft-and-spectral-analysis](./fft-and-spectral-analysis.md)**(DFT、FFT、频域乘法)、**[audio-effects](./audio-effects.md)**(comb/allpass、算法 reverb、效果器链)、**[adaptive-audio-and-3d](../../phase-7/deep-dives/adaptive-audio-and-3d.md)**(panning law、距离衰减、HRTF 初步概念)。其中任何一项不熟,先回去补,这一篇在它们之上做加法。

## 1 · 卷积是什么:把信号"涂"在另一个信号的形状上

### 1.1 直觉先于公式

进入任何 DSP 教材,你会先看到一串吓人的求和号:`y[n] = Σ x[k] · h[n-k]`。先别管它。先建立一个画面。

想象你拿一支小印章,印章的凸起图案是一个叫 `h` 的形状(比如一段两秒的、逐渐衰减、带穹顶反射的曲线)。现在你拿一段叫 `x` 的信号(footstep),从左往右扫过去——在每个时刻 `n`,你看 `x` 在那一刻的瞬时值 `x[n]`,然后**用这个值去蘸一下印章 h**,在输出纸面上盖一个章。每个时刻盖的章都是同一个形状 `h`,但被 `x[n]` 缩放——`x[n]` 大,章盖得深;`x[n]` 小,章盖得浅。然后,所有这些盖在纸面上的章,**叠加**起来。叠出来的轨迹,就是卷积 `y = x ∗ h`。

把画面再精确一点。在时刻 `n = 0`,你拿 `x[0]` 盖一个 `x[0]·h[0], x[0]·h[1], x[0]·h[2], ..., x[0]·h[M-1]`——一个被缩放过的 h。在 `n = 1`,你又拿 `x[1]` 盖一个 `x[1]·h`,但这次盖的位置往后挪一格——`0, x[1]·h[0], x[1]·h[1], ..., x[1]·h[M-1]`。在 `n = 2`,再往后挪一格。一直盖到 `x` 结束。把所有这些"被缩放、被偏移的 h"按时间对齐**相加**,就是 `y[n]`。每一个 input sample 都"展开"成一整个 IR 的形状,所有展开的东西重叠、求和,出来的就是卷积。

这件事的物理意义在音频里极其强大。如果 `h` 是一个房间对脉冲声(发令枪、扫频)的录音——IR——那么 `h[k]` 就是"枪响了之后第 k 个 sample 时,房间正在反弹回来的声波"。把这个 h 与你的 dry 信号 `x` 卷起来,等价于:**dry 信号的每一个瞬时分量,都触发一整个房间的响应**——所有这些响应叠加起来,就是你那声 dry footstep 在房间里真实响起来时会被录到的全部内容。**卷积就是你让一个 LTI 系统响应一个输入信号**。这就是为什么卷积混响听起来真实到吓人。

### 1.2 公式,以及与 LTI 系统的关系

直觉到位了,把公式摆出来。

离线、离散、有限长度的卷积:

```
y[n] = sum_{k=0}^{M-1} x[n - k] · h[k]
```

`x` 是 input 长度 N,`h` 是 IR 长度 M,`y` 是 output 长度 N + M - 1。这就是上一节那个"印章叠加"的精确写法:在时刻 n,把过去 M 个 input 样本 `x[n], x[n-1], ..., x[n-M+1]` 各自与 h 反过来对应相乘,再求和。

现在把它和 **LTI 系统**的概念接起来。如果你做过 [phase-0/22-signals-foundation](../../phase-0/22-signals-foundation.md),你见过这个论断:**任何 LTI(linear time-invariant)系统,被一个 impulse(单位脉冲)激励,产生的响应——impulse response,IR——完全决定了这个系统对一切输入的行为。** 也就是说,如果 `h` 是系统的 IR,那么系统对任意输入 `x` 的响应 `y` 就是 `y = x ∗ h`——卷积。这是因为 LTI 系统满足线性(linear)与时间不变(time-invariant),所以可以把 `x` 分解成一串加权、错位的 impulse,每个 impulse 触发一个加权、错位的 h,全部加起来——这恰好就是卷积。

房间是一个**近似** LTI 系统(忽略温度漂移、空气对流、人走动等慢变化),所以你录到的 IR 就**几乎**完全表征了这间房间的声学。把任意声音卷进这间房间的 IR,声音就"进了"这间房间。HRTF 同理:从某个方向到鼓膜的传递路径,在头不动时也是 LTI 系统,它的 IR——叫 HRIR(head-related impulse response)——完全表征了"从这个方向来的声音怎么被你的外耳塑形"。**卷积混响和 HRTF 是同一个数学操作的两件不同物理外衣。**

### 1.3 朴素实现的 Rust 代码与代价

把朴素卷积先用 Rust 写出来,你立刻就能感觉到这件事为什么不能这么干。

```rust
/// Naive O(N·M) convolution.
/// x: input, length N
/// h: impulse response, length M
/// returns y: length N + M - 1
pub fn convolve_naive(x: &[f32], h: &[f32]) -> Vec<f32> {
    let n = x.len();
    let m = h.len();
    let mut y = vec![0.0f32; n + m - 1];
    for i in 0..n {
        for j in 0..m {
            y[i + j] += x[i] * h[j];
        }
    }
    y
}
```

这是双层循环,`N × M` 次乘加。**别小看这个数**。一个两秒 IR @ 48 kHz 就是 M = 96000 个样本。一段五秒的 dry footstep 是 N = 240000。`N × M = 2.3 × 10^10` 次乘加——23 GHz 等价频率,跑一次能把整个核心吃掉好几秒。实时音频里(每帧 10 ms 480 sample)你只有几毫秒预算,这个数远远超出。朴素卷积**只在离线处理**(asset 预处理、录音棚后制)里用,实时游戏音频不能用。

而且注意上面那个 `y[i + j] +=`——它分配了一个 `N + M - 1` 的输出 buffer。实时音频里 input 是流式的(streaming),你不会拿到整段 x 一次性处理,而是拿到一小段一小段(典型 256、512、1024 sample 一块)。所以你需要的是**逐块卷积**——把"无限长流"切成"每帧一小块",卷积延迟不超过一个块的算法。这就把 FFT 卷积和 partitioned convolution 一并逼出来了。

## 2 · FFT 卷积:把 O(N·M) 压成 O(N log N)

### 2.1 卷积定理——为什么频域乘法等于时域卷积

如果你已经过了 [fft-and-spectral-analysis](./fft-and-spectral-analysis.md),DFT(离散傅里叶变换)对你不陌生。这里要把那个最关键的定理用起来——**卷积定理**(convolution theorem):

```
时域卷积  y[n] = x[n] ∗ h[n]
等价于
频域乘法  Y[k] = X[k] · H[k]
```

也就是说,把 `x` 和 `h` 各自做一次 DFT,得到频域系数 `X[k]` 和 `H[k]`;逐点相乘得到 `Y[k]`;再做一次 inverse DFT,得到 `y[n]`,这个 `y` 就和时域卷积得到的 `y` 一模一样(在 DFT 长度足够避免循环卷积缠绕的前提下,见下文)。

为什么这能省?DFT 朴素实现是 O(N²),但 FFT(快速傅里叶变换)把它压到 O(N log N)。`x` 与 `h` 都做一次 FFT 是 `2 × O(N log N)`,频域逐点乘法是 O(N),再做一次 inverse FFT 是 O(N log N)——总共 `O(N log N)`。**只要 N 大到一定程度,FFT 卷积就完胜朴素卷积**。多大?break-even 点大约在 IR 长度 M ≥ 64 处——也就是说几乎所有"房间响应级"的 IR 都该用 FFT 路径。

这件事的物理直觉是这样的。时域卷积的 N×M 次乘加之所以必要,是因为你在每个 input sample 都展开一整段 IR。但 IR 的频域表征 `H[k]` 是一组紧凑的"频带增益"——只要几百到几千个复数。input 的频域表征 `X[k]` 也是。两个信号在频域"按频带对齐相乘",等于"把每个频带按系统的传递函数塑形一下"。塑形完变回时域,就是卷积的结果。**频域操作与 LTI 系统的频域表征——频率响应——天然契合**,这是 DSP 里最美的一件事。

### 2.2 循环卷积、zero-padding 与 FFT 长度选择

有一个陷阱必须先讲清楚。DFT 给的不是线性卷积(linear convolution,长度 N+M-1),而是**循环卷积**(circular convolution)——把信号当成周期重复,乘出来的结果会在边界"缠绕"。直接 FFT → 乘 → IFFT,你会得到一个被循环缠绕过的 `y`,前半截被后半截"叠"上来,完全不能用。

解法是 **zero-padding**(零填充)。把 `x`(长 N)和 `h`(长 M)都补零到长度至少 `N + M - 1`,再做 FFT。补零以后,循环卷积的"缠绕区"落到了零填充的部分,不会污染有效结果。所以 FFT 卷积的标准做法是:取 FFT 长度 `L ≥ N + M - 1`(工程上取 2 的整数次幂,因为 radix-2 FFT 最快),把 `x` 与 `h` 各补零到 `L`,FFT、乘、IFFT,取前 `N + M - 1` 个 sample 作为输出。

```rust
use rustfft::{FftPlanner, num_complex::Complex};

/// One-shot FFT convolution. Output length: x.len() + h.len() - 1.
pub fn convolve_fft(x: &[f32], h: &[f32]) -> Vec<f32> {
    let n = x.len();
    let m = h.len();
    let out_len = n + m - 1;
    // Next power of two >= out_len, so circular convolution does not wrap.
    let fft_len = out_len.next_power_of_two();

    let mut planner = FftPlanner::<f32>::new();
    let forward = planner.plan_fft_forward(fft_len);
    let inverse = planner.plan_fft_inverse(fft_len);

    let mut x_buf: Vec<Complex<f32>> = x.iter()
        .map(|&v| Complex::new(v, 0.0))
        .collect();
    x_buf.resize(fft_len, Complex::zero());
    let mut h_buf: Vec<Complex<f32>> = h.iter()
        .map(|&v| Complex::new(v, 0.0))
        .collect();
    h_buf.resize(fft_len, Complex::zero());

    forward.process(&mut x_buf);
    forward.process(&mut h_buf);

    // Spectral multiply
    let mut y_buf: Vec<Complex<f32>> = x_buf.iter()
        .zip(h_buf.iter())
        .map(|(a, b)| a * b)
        .collect();

    inverse.process(&mut y_buf);

    // inverse FFT needs scale by 1/fft_len
    let scale = 1.0 / fft_len as f32;
    y_buf.iter().take(out_len).map(|c| c.re * scale).collect()
}
```

注意 `inverse.process` 后乘 `1.0 / fft_len as f32`,这是大多数 FFT 库的约定——inverse 是 unscaled,需要自己除一下。RustFFT 的这个约定要小心,漏除会导致输出比正确值大 `fft_len` 倍——你的 reverb 立刻爆音。

**性能数据**:2 秒 IR (M=96000) 与 5 秒 input (N=240000) 卷积。朴素:`2.3 × 10^10` MAC。FFT 路径:`fft_len ≈ 2^19 ≈ 524288`,两次正 FFT + 一次逆 FFT,每次约 `5 × 524288 ≈ 2.6 M` 复数运算,共 `~8 M`——加上频域逐点乘法 `524288`,总共 `~10 M` 运算量。**约 2000 倍加速**。这就是 FFT 卷积的力量,也是为什么卷积混响能在 PC 上实时跑起来。

### 2.3 实时音频的困难:你不能等一整段信号到齐

上面那段代码有个隐藏的、致命的问题。它假设你**有完整的 `x` 在手**——一整段 input。可实时音频不是这样。音频 callback 每 10 ms 给你一个 480 sample 的块(block,也叫 frame/buffer,术语在不同系统里漂移,这里统一叫块),你必须在下个 10 ms 内把它处理完送回去。你没有"全部 input"。

如果你用一次性 FFT 卷积,只能等 `fft_len` 这么多 sample 全部到齐再算——`fft_len = 2^19` 时延迟是 10.9 秒,实时音频完全不能接受。所以实时卷积混响要做的是 **partitioned convolution**(分段卷积)——把长 IR 切成固定大小的小段,每段单独 FFT;每来一个 input 块,只做"一次 FFT + 几次频域乘加 + 一次 IFFT",输出延迟固定在一个块的大小。两种工业标准实现:**Overlap-Add(OLA,重叠相加)** 和 **Overlap-Save(OLS,重叠保留)**。它们的数学等价,工程上 OLS 略简单(不用做 overlap window 的加法,直接丢掉头一段),下面的实现就用 OLS。

### 2.4 Overlap-Save 实时分块卷积

先把思路说清楚。设每块大小 `B`(典型 256、512、1024)。FFT 长度 `L = 2B`——比一块大一倍。你维护一个长度 `L` 的 input history buffer——前 `B` 个是上一块的"历史",后 `B` 个是当前块。每次来一个新块,你:

1. 把 input history 向左推 `B` 位,把新块填到最右边;
2. 对这 `L` 个 sample 做 FFT,得到 `X[k]`;
3. 把 `X[k]` 与 IR 的每个 partition(每个长度 `B`,补零到 `L`)的 FFT 频域系数逐 partition 相乘并累加,得到 `Y[k]`;
4. 对 `Y[k]` 做 inverse FFT;
5. **只取后半段 `B` 个 sample 作为输出**——前半段被循环卷积污染了,要丢掉(这就是 "save" 的语义:保留后半,丢掉前半)。

IR partition 是这样得到的:原始长 IR(长 M)被切成 `P = ceil(M/B)` 段,每段长 `B`,每段补零到 `L = 2B` 再 FFT,得到 `P` 个频域 partition `H_0, H_1, ..., H_{P-1}`。每个 partition 对应"IR 的第 i 段在系统中起作用"。你要维护一个长度 `P` 的频域 delay line——`X` 的历史 FFT 频谱(每来一块就左移一格、写入新的),对每个 partition `i`,用历史频谱 `X_hist[i]` 与 `H_i` 相乘,所有 partition 累加。这是 partitioned convolution 的精髓,既保留了完整 IR 的效果,又把每块的延迟压在 `B` 个 sample(典型 1024 sample @ 48 kHz = 21 ms)。

```rust
use rustfft::{FftPlanner, num_complex::Complex};

pub struct PartitionedConvolver {
    block_size: usize,                 // B
    fft_len: usize,                    // L = 2B
    n_partitions: usize,               // P = ceil(M/B)
    ir_partitions: Vec<Vec<Complex<f32>>>, // P 个频域 IR 段
    // 频域 history,长度 P,每来一块左移、push 新的
    x_history_freq: Vec<Vec<Complex<f32>>>, // size P × L
    // 时域 input history,长度 L
    x_history_time: Vec<f32>,
    forward_fft: std::sync::Arc<dyn rustfft::Fft<f32>>,
    inverse_fft: std::sync::Arc<dyn rustfft::Fft<f32>>,
    acc_freq: Vec<Complex<f32>>,        // 频域累加器
    scratch: Vec<Complex<f32>>,         // 复用 scratch,不 alloc
}

impl PartitionedConvolver {
    /// ir: 时域 impulse response
    /// block_size: B,partition 大小,决定 latency = B / sample_rate
    pub fn new(ir: &[f32], block_size: usize) -> Self {
        let b = block_size;
        let l = b * 2;
        let n_partitions = (ir.len() + b - 1) / b;

        let mut planner = FftPlanner::<f32>::new();
        let forward_fft = planner.plan_fft_forward(l);
        let inverse_fft = planner.plan_fft_inverse(l);

        // Build IR partitions in frequency domain
        let mut ir_partitions = Vec::with_capacity(n_partitions);
        for p in 0..n_partitions {
            let start = p * b;
            let end = (start + b).min(ir.len());
            let mut buf: Vec<Complex<f32>> = ir[start..end]
                .iter()
                .map(|&v| Complex::new(v, 0.0))
                .collect();
            buf.resize(l, Complex::zero());
            forward_fft.process(&mut buf);
            ir_partitions.push(buf);
        }

        Self {
            block_size: b,
            fft_len: l,
            n_partitions,
            ir_partitions,
            x_history_freq: vec![vec![Complex::zero(); l]; n_partitions],
            x_history_time: vec![0.0; l],
            forward_fft,
            inverse_fft,
            acc_freq: vec![Complex::zero(); l],
            scratch: vec![Complex::zero(); l],
        }
    }

    /// Process exactly `block_size` input samples, produce `block_size` output.
    pub fn process_block(&mut self, input: &[f32], output: &mut [f32]) {
        let b = self.block_size;
        let l = self.fft_len;
        assert_eq!(input.len(), b);
        assert_eq!(output.len(), b);

        // 1. Shift time-domain history left by B, append new block on the right.
        //    x_history_time is [old_B | new_B]
        self.x_history_time[..b].copy_from_slice(&self.x_history_time[b..]);
        self.x_history_time[b..].copy_from_slice(input);

        // 2. FFT the new L-length input history.
        let mut x_freq: Vec<Complex<f32>> = self.x_history_time.iter()
            .map(|&v| Complex::new(v, 0.0))
            .collect();
        self.forward_fft.process(&mut x_freq);

        // 3. Shift frequency history left by 1, push new spectrum at end.
        //    x_history_freq[0] = oldest, x_history_freq[P-1] = newest
        for i in 0..self.n_partitions - 1 {
            std::mem::swap(&mut self.x_history_freq[i], &mut self.x_history_freq[i + 1]);
        }
        // Write the newest into the last slot.
        self.x_history_freq[self.n_partitions - 1] = x_freq;

        // 4. Accumulate: Y = sum_i x_history_freq[i] * ir_partitions[i]
        for c in self.acc_freq.iter_mut() { *c = Complex::zero(); }
        for i in 0..self.n_partitions {
            let x_hist = &self.x_history_freq[i];
            let h_part = &self.ir_partitions[i];
            for k in 0..l {
                self.acc_freq[k] = self.acc_freq[k] + x_hist[k] * h_part[k];
            }
        }

        // 5. IFFT.
        self.scratch.copy_from_slice(&self.acc_freq);
        self.inverse_fft.process(&mut self.scratch);

        // 6. Take the last B samples (overlap-save: discard the first B).
        let scale = 1.0 / l as f32;
        for i in 0..b {
            output[i] = self.scratch[b + i].re * scale;
        }
    }
}
```

(注意上面把 `x_freq` 存进 `x_history_freq` 用了 `=`——这其实是个所有权重写,生产代码会用 arena allocator 或 ring buffer 避免重复 alloc;这里写得直白,让你看清结构。)

**性能数据**:2 秒 IR @ 48 kHz,partition size 1024 sample。`P = ceil(96000 / 1024) = 94` 个 partition。每块(1024 sample = 21 ms 音频)你要做的:`1 次 FFT-2048 + 94 次复数乘加(每次 2048 点)+ 1 次 IFFT-2048`。FFT-2048 约 22k 复数运算,94 次 × 2048 点乘加 = 192k 运算,再加 22k。**每块约 240k 运算,折合每秒 11.4 M 运算**,在现代 CPU 上是单核 0.5% 左右——比朴素卷积的"占满一个核心"低了三个数量级。延迟 1024 sample @ 48 kHz = 21.3 ms,人类能感知但游戏可接受。

调小 partition size 会减延迟但增 CPU——1024 是大部分 PC 游戏的 sweet spot。VR 等低延迟场景用 256 或 512 sample,但 CPU 成本会翻 4 倍到 16 倍。游戏选型时这件事必须算清——后面 §6 会回到这个 trade-off。

### 2.5 与算法 reverb 的对比

到这一步,把 [audio-effects](./audio-effects.md) 里讲的算法 reverb 与卷积混响放在一起对比。算法 reverb(Schroeder、Freeverb、FDN)用几十到几百个 comb/allpass 加上 feedback matrix,**模拟**房间的统计特性——echo density、衰减率、频段相关 damping。它参数化好(调一个 roomsize 旋钮,RT60 立刻变),CPU 极轻(单个 Freeverb 实例 ~2% 单核),听感"温暖但通用"。卷积混响用一段录好的 IR 直接做卷积,**复制**房间的全部声学指纹——早期反射的具体 timing、墙面材质引起的频谱细节、空间几何的特殊模式——但参数化差(要换房间得换 IR),CPU 重(partitioned convolution ~0.5% 单核,但要几十个声源同时卷就很贵),有 latency。

工业实践是**分层混响**(hybrid reverb):大空间(cathedral、cave、hall)用卷积混响只做"hero moments"——玩家进入这间大厅,卷积混响打开,听感瞬间升级;普通走廊、小房间用算法 reverb,便宜快速。FMOD 和 Wwise 都支持把 reverb send 同时分给算法 aux bus 和卷积 aux bus,空间类型决定 send 比例。

## 3 · 脉冲响应:怎么录、怎么用、是什么

### 3.1 IR 录制——sine sweep 与 deconvolution

录 IR 的核心想法很简单:在目标空间里放一个"已知形状"的激励声,用麦克风录房间的响应,然后**反向卷积**——把已知激励的"逆滤波器"应用到录音上,剥离掉激励本身,剩下纯净的房间响应。直观讲,你想要的是房间对"理想脉冲"(数学上的 δ 函数,无限窄、面积 1)的响应,但你不能真发一个理想脉冲(扬声器物理上发不出来,而且能量太集中会损坏设备)。所以发一个**能量分散但频谱已知**的激励,再用反卷积把响应"还原"成对 δ 的响应。

工业标准是 **exponential sine sweep**(指数扫频正弦):激励是 `sin(ω(t) · t)`,频率从 20 Hz 扫到 20 kHz,**指数增长**(每倍频程花同样长的时间,与人耳对数的频率感知匹配)。指数扫频的好处是:它的 inverse filter 是"时间反向的扫频",把这个 inverse filter 与录到的响应卷积,得到的就是房间的 IR——而且谐波失真(扬声器非线性引入的)会被推到 IR 的负时间区,直接剪掉,得到一个干净的 IR。

简化伪代码:

```rust
/// Generate exponential sine sweep from f0 to f1 over T seconds at sample_rate.
pub fn exp_sweep(f0: f32, f1: f32, duration_secs: f32, sample_rate: f32) -> Vec<f32> {
    let n = (duration_secs * sample_rate) as usize;
    let mut sweep = Vec::with_capacity(n);
    let t_total = duration_secs;
    // Exponential rate: f(t) = f0 * (f1/f0)^(t/T)
    let ratio = (f1 / f0).ln() / t_total;
    let two_pi = std::f32::consts::TAU;
    let mut phase = 0.0f32;
    let dt = 1.0 / sample_rate;
    for i in 0..n {
        let t = i as f32 * dt;
        let freq = f0 * (ratio * t).exp();
        phase += two_pi * freq * dt;
        sweep.push(phase.sin());
    }
    sweep
}

/// Inverse filter is the time-reversed sweep, scaled so deconvolution is unity.
pub fn inverse_filter(sweep: &[f32]) -> Vec<f32> {
    let n = sweep.len();
    // Amplitude envelope inverse (so we boost low frequencies that the sweep spends less time on per Hz)
    let f0 = 20.0f32;
    let f1 = 20000.0f32;
    let mut inv = Vec::with_capacity(n);
    for k in 0..n {
        let t = k as f32 / n as f32;
        // Frequency at position k in the sweep
        let freq = f0 * ((f1 / f0).ln() * t).exp();
        // Inverse amplitude proportional to 1/sqrt(freq) (pink-ish weighting)
        let env = (1.0 / freq).sqrt() * 100.0; // scale constant arbitrary
        inv.push(sweep[n - 1 - k] * env);
    }
    inv
}

/// Deconvolve: IR = recorded_response ∗ inverse_filter
/// (Implementation: do it via FFT multiplication.)
pub fn extract_ir(recorded: &[f32], inverse_filter: &[f32]) -> Vec<f32> {
    convolve_fft(recorded, inverse_filter)
}
```

实际生产用 [Farina 2000 的方法](https://www.aes.org/e-lib/browse.cfm?elib=15645)(Angelo Farina 提出的标准 sine sweep 法),还有 starting pistol、balloon pop 等替代激励——这些"瞬态声"更简单(直接发一个近似脉冲,录到的就是近似 IR),但能量谱不可控,信噪比差,现在专业录音都用 sine sweep。

### 3.2 IR 数据库——Open AIR 与商业 IR 库

你不用自己录。网上有大量公开 IR 库,最著名的是 **Open AIR(Open Acoustic Impulse Response Library)**,由 Leeds 大学维护,提供世界各地著名空间的免费 IR——从 York Minster 大教堂到 Hamilton Mausoleum(号称世界最长混响时间),从地下车站到录音棚 booth。下载都是 WAV 文件,直接 load 到你的卷积引擎。商业 IR 库如 Altiverb(里头几百个 IR)、LiquidSonics Reverberate 自带的 IR 包,质量更高但要付费。

IR 是 **stereo 或 multichannel** 的——左声道录的是房间左半部分的响应,右声道是右半部分。立体声卷积就是 input 同时与左、右 IR 各卷一次,输出 stereo。**真正的房间 IR 还有"空间维度"——true stereo(4 通道)、Ambisonic(360°)、甚至 WAVES 等 B-format IR——做空间化混响**,这一篇先聚焦 stereo IR。

### 3.3 IR 作为 LTI 假设的边界

最后讲清楚一件事:房间不是完全 LTI 的。温度变了声速变、空气对流变、人在房间里走动改变反射路径——这些都让房间是"慢时变"系统,不是严格 LTI。但**对几秒级别的音频事件,房间近似 LTI 是个非常合理的工作假设**,工程上 IR 录一次能在游戏里用很久。这条 LTI 假设的边界,你心里要有数——如果你录 IR 时温度 20 度,游戏运行时模拟的也是 20 度(声速 343 m/s),用起来没问题;如果你想做"温度 35 度时声音怎么变"这种细节,光卷积一个 IR 就不够了,要参数化 IR 模型或 FIR 变分模型——这超出这一篇范围,知道边界在哪即可。

## 4 · HRTF:从空间到双耳

### 4.1 为什么 stereo pan 给不出真正的方位

[adaptive-audio-and-3d](../../phase-7/deep-dives/adaptive-audio-and-3d.md) 那篇里讲过 stereo pan law(constant power pan):左声道 `cos(θ)`,右声道 `sin(θ)`,把 mono 声音按角度分配左右能量。这能让声音"在左"或"在右",但**听感是在你脑壳里左右挪动**,不是从外面来。原因:真实听觉靠的不只是"左右能量分配",还有一连串其他线索——主要的有 ITD(双耳时间差)、ILD(双耳强度差)、pinna effect(耳廓频谱塑形);次要的还有 head shadow、torso reflection、reverberation 距离线索。Stereo pan 只动了其中一个(ILD 的近似版),其他全丢。

**HRTF(Head-Related Transfer Function)就是这一切线索的频域总编码**。它的定义是:从 3D 空间中某个方向 (方位角 azimuth θ, 仰角 elevation φ) 到达听者鼓膜的频率响应。HRTF 的时域版本——它的 inverse Fourier transform——叫 **HRIR**(head-related impulse response),是一个有限长的脉冲响应,典型 128 到 512 sample 长。HRIR 与 IR 的关系一目了然:**它们是同一种东西**——一个是房间对脉冲的响应,一个是从某方向到鼓膜这个 LTI 系统对脉冲的响应。所以你卷积一个 mono 声音用房间 IR 得到"在这间房里"的声音;卷积同一个 mono 声音用 HRIR,得到"从那个方向来的"声音。**同一种数学,两种物理应用。**

### 4.2 HRIR 的物理来源——ITD、ILD、pinna effect

HRTF 内含的物理线索来自三件事:

**ITD(Inter-aural Time Difference,双耳时间差)**——声波绕过头部到达较远耳朵时多走的距离,产生时间差。简化模型(把头当球,声源在前半平面方位角 θ):

```
ITD(θ) ≈ (r / c) · (θ + sin θ)        for θ in [-π/2, π/2]   (Woodworth 公式)
```

`r` 是头半径(典型 8.75 cm),`c` 是声速 343 m/s。最大 ITD(θ = ±90°)约 0.6 ms——对应 48 kHz 下约 29 个 sample。这个时间差主要在低频(< 1.5 kHz)有效,因为低频波长远大于头,phase difference 不模糊;高频 ITD 因为 phase wrapping 大脑无法解读。

**ILD(Inter-aural Level Difference,双耳强度差)**——头部对高频声波是障碍物(head shadow effect),声源同侧耳朵接收的高频强度远高于对侧。低频(波长 > 头直径 ≈ 17.5 cm,即 < 2 kHz)几乎无 ILD;高频(> 4 kHz)ILD 可达 -20 dB(对侧)。简化模型:

```
ILD(f, θ) ≈ 1.5 · (f/1000) · sin(θ)   [dB, capped at ~20 dB, valid f < 4 kHz]
```

**Pinna effect(耳廓效应)**——耳廓的凹凸对入射声波反射、衍射,产生**方位相关的频谱凹槽**(spectral notch)。这些 notch 的频率位置编码了仰角——人脑根据 notch 模式判断声源在前/后/上/下。Pinna effect 的频域表征非常 individual——每个人的耳廓形状不同,notch 频率位置不同。这就是为什么 generic HRTF(用别人的 HRTF)对很多人定位不准的原因(后面 §5 会展开)。

**Head shadow、torso、shoulder reflection**——头、肩膀、躯干都对声波有衍射和反射,带来更复杂的频域塑形,尤其在中频(800 Hz - 4 kHz)和侧后方方位。所有这些效应加起来,合成 HRTF 的完整频谱。

### 4.3 HRIR 与卷积——binaural 渲染流程

HRTF 的工程使用方法是把 mono 信号同时卷两个 HRIR——左耳一个、右耳一个——得到一个 stereo 双耳信号,送给耳机。

```
mono x[n]
    │
    │ source direction (θ, φ)
    ▼
   ┌────────────────────────┐
   │  HRIR_L(θ, φ) ∗ x → y_L │  → 左耳耳机
   │  HRIR_R(θ, φ) ∗ x → y_R │  → 右耳耳机
   └────────────────────────┘
```

简化版 Rust(单方向、固定 HRIR):

```rust
/// Process a mono block through a pair of HRIRs → binaural stereo output.
pub struct HrtfFilter {
    hrir_l: Vec<f32>,    // length T, typically 128
    hrir_r: Vec<f32>,
    history: Vec<f32>,   // length T
    pos: usize,
    ir_len: usize,
}

impl HrtfFilter {
    pub fn new(hrir_l: Vec<f32>, hrir_r: Vec<f32>) -> Self {
        let ir_len = hrir_l.len();
        assert_eq!(hrir_r.len(), ir_len);
        Self {
            hrir_l, hrir_r,
            history: vec![0.0; ir_len],
            pos: 0,
            ir_len,
        }
    }

    /// Replace HRIR (e.g. when source direction changes). Smoothly crossfade to avoid clicks.
    pub fn set_hrir(&mut self, new_l: &[f32], new_r: &[f32]) {
        // Production: crossfade over ~10ms. Simple version: just copy.
        self.hrir_l[..new_l.len()].copy_from_slice(new_l);
        self.hrir_r[..new_r.len()].copy_from_slice(new_r);
    }

    pub fn process(&mut self, input: &[f32], out_l: &mut [f32], out_r: &mut [f32]) {
        let t = self.ir_len;
        for (i, &x) in input.iter().enumerate() {
            self.history[self.pos] = x;
            let mut sum_l = 0.0f32;
            let mut sum_r = 0.0f32;
            for k in 0..t {
                let idx = (self.pos + t - k) % t;
                sum_l += self.hrir_l[k] * self.history[idx];
                sum_r += self.hrir_r[k] * self.history[idx];
            }
            out_l[i] = sum_l;
            out_r[i] = sum_r;
            self.pos = (self.pos + 1) % t;
        }
    }
}
```

HRIR 长度通常很短(128 或 256 sample),所以**直接做时域卷积**比 FFT 卷积还快——FFT 卷积的 fixed overhead(FFT plan、complex arithmetic)在短 IR 下不划算。这跟房间 IR(M = 96000)完全相反——HRTF 走时域路径,房间混响走 FFT 路径。**实现路径的选择取决于 IR 长度**,这是实战知识。

**性能数据**:128-tap HRIR,每 sample 256 次 MAC(左 + 右各 128)。48 kHz 立体声输出 = 48000 × 256 = 12.3 M MAC/秒,在现代 CPU 上 ~0.5% 单核。一个游戏同时处理 32 个声源 = 16% 单核——可以接受。如果用 SIMD(SSE 4-way 或 AVX 8-way)优化,可降到 4% 左右。

### 4.4 HRTF 数据集与 SOFA 格式

HRTF 不是你"算"出来的——它是**测出来的**。在消声室(anechoic chamber,四面六面都是吸声尖楔的房间,模拟自由场)里,把探针麦克风塞到受试者的耳道入口,从各个方向(angle grid,典型 azimuth 5°-10° 步进,elevation 5°-10° 步进,覆盖球面)用小扬声器播放 sine sweep,录到响应、deconvolution 得到 HRIR。每个方向得到一对 HRIR(左 + 右)。一组完整测量,叫做一个 HRTF 数据集。

工业上常用的公开数据集:

- **MIT KEMAR(1994,Gardner & Martin)**:最早的经典数据集,用一个 KEMAR 假人模型测,710 个方向。许多早期 3D 音频系统都基于它。
- **CIPIC(UC Davis)**:45 个真人受试者,每个 1250 个方向——最早的大规模个体化数据集,适合研究个体差异。
- **IRCAM Listen**:50 个真人受试者,187 个方向,中等密度。
- **ARI HRTF / SADIE**:Acoustics Research Institute 提供,高分辨率(2113 方向),现代研究用。

数据集格式上,工业标准是 **SOFA(Spatially Oriented Format for Acoustics)**——一个基于 NetCDF 的开放文件格式,定义了 HRTF、HRIR、BRIR(binaural room IR,带房间的 HRTF)等的存储标准。SOFA 是 AES 标准化,所有现代 3D 音频工具(FMOD、Wwise、Steam Audio、Resonance Audio)都支持加载 SOFA 文件。

## 5 · 移动声源的 HRTF 插值与个体化

### 5.1 角度插值——最近邻 vs 三线性 vs 球面插值

游戏里声源几乎都是动的——NPC 走动、子弹飞过、车辆从左开到右。每帧(60 FPS = 16 ms)声源方向都在变,HRTF 跟着变。可你测的 HRIR 是离散方向 grid(比如 5° 步进),不是连续函数。怎么办?

**最简单——最近邻(nearest neighbor)**:找 grid 上最接近当前方向的 HRIR,直接用。问题是切换时有"咔哒"——HRIR 突变等同于在 input 上施加一个瞬时变化,听感是周期性的 click。

**改进——crossfade 平滑切换**:当方向跨过 grid 边界时,在 ~10 ms 内做新旧 HRIR 的 crossfade。这把 click 变成了"轻微 whoosh",可接受但不够细腻。

**真正干净——球面插值 / 双线性插值**:在 HRIR grid 上做插值——找到当前方向周围的 4 个 grid 点(类似 2D 纹理 bilinear),按当前方向在 4 个 grid 点之间的位置,对 HRIR 的每个 tap 做加权平均。结果 HRIR 是 4 个相邻 HRIR 的连续混合,听感是声源平滑移动。

简化实现(方位角 + 仰角双线性,假设 grid 等角度):

```rust
/// Bilinear interpolation of HRIR over azimuth/elevation grid.
/// grid: nested [azimuth_idx][elevation_idx] → (hrir_l, hrir_r)
pub fn interpolate_hrir(
    grid: &[Vec<(Vec<f32>, Vec<f32>)>],  // [az][el]
    azimuth: f32,                          // radians
    elevation: f32,
    azimuth_step: f32,                     // e.g. 5° in radians
    elevation_step: f32,
) -> (Vec<f32>, Vec<f32>) {
    let n_az = grid.len();
    let n_el = grid[0].len();
    // Compute fractional indices
    let az_f = (azimuth / azimuth_step).floor() as usize % n_az;
    let el_f = (elevation / elevation_step).clamp(0.0, (n_el - 1) as f32);
    let el_idx = el_f.floor() as usize;
    let el_frac = el_f - el_idx as f32;
    let el_next = (el_idx + 1).min(n_el - 1);
    // Wrap azimuth (circular)
    let az_next = (az_f + 1) % n_az;

    let t_len = grid[az_f][el_idx].0.len();
    let mut out_l = vec![0.0f32; t_len];
    let mut out_r = vec![0.0f32; t_len];
    for k in 0..t_len {
        let l = grid[az_f][el_idx].0[k] * (1.0 - el_frac) * (1.0) // weights implicit 4-corner
              + grid[az_f][el_next].0[k] * el_frac
              + grid[az_next][el_idx].0[k] * (1.0 - el_frac)
              + grid[az_next][el_next].0[k] * el_frac;
        out_l[k] = l * 0.5; // normalize 4-corner sum
        let r = grid[az_f][el_idx].1[k] * (1.0 - el_frac)
              + grid[az_f][el_next].1[k] * el_frac
              + grid[az_next][el_idx].1[k] * (1.0 - el_frac)
              + grid[az_next][el_next].1[k] * el_frac;
        out_r[k] = r * 0.5;
    }
    (out_l, out_r)
}
```

(上面把 azimuth 维度的 frac 省略了——完整版要在 az 维度也做加权。这里展示了 4 角 bilinear 的整体结构,真实代码补全所有 4 个 weight。)

更精致的实现用 **spherical interpolation**(球面插值,如 slerp)或基于 HRTF 主成分分析(PCA)的 **structured interpolation**——后者把 HRTF 数据集压缩成低维基函数,任意方向通过基函数加权生成,平滑性极好。Steam Audio 内部用的就是这种参数化插值。

### 5.2 个体化问题——为什么 generic HRTF 对有些人无效

最让人头疼的事:**每个人的耳朵形状不同,pinna effect 的频谱 notch 频率位置就不同**。用别人的 HRTF(叫 generic HRTF),大脑的"听觉皮层后处理"找不到熟悉的 notch 模式,定位精度下降——尤其是前后混淆(front-back confusion,把前面的声源听成后面的)和仰角分辨。

工业妥协:**用 generic HRTF 配合一个适度的 reverb tail**——reverb 提供距离和环境线索,帮大脑定位。这是 Steam Audio、Resonance Audio、Oculus Audio 默认的模式。高端方案是个体化 HRTF——给每个用户测一组(像配眼镜那样测耳廓),或者用摄像头 + ML 从耳廓照片估出 HRTF。Sony PS5 的 Tempest 3D Audio 在往这个方向走(用 5 个问题让用户选择头像形状,从一组预制 HRTF 里挑最接近的)。完全个体化的方案目前还在研究中,游戏工业普遍接受 generic HRTF + reverb 的妥协。

### 5.3 距离与 HRTF 的耦合

HRTF 处理的是**方向**,不处理距离。距离线索来自三件事:

- **整体能量衰减**(1/r 反平方律,见 [adaptive-audio-and-3d](../../phase-7/deep-dives/adaptive-audio-and-3d.md) 的距离衰减公式);
- **Direct-to-Reverberant Ratio(DRR)**——近处 direct sound 占主导,远处 reverb(房间反射)占主导。这是大脑判断"室内距离"的最强线索。游戏中通过把 HRTF 处理后的 dry signal 与卷积混响(用房间 IR)处理后的 wet signal 按距离比例混合来实现;
- **高频衰减**——空气对高频有吸收(尤其 > 2 kHz),远处声源高频衰减更明显。游戏中加一个距离相关的 lowpass 实现。

完整 pipeline:

```
mono x[n]
   │
   ├──────────── HRTF (θ, φ) ∗ ───────────────→ y_dry (双耳 direct)
   │                                              │
   │       ┌── room IR ∗ ── diffuse HRTF ∗ ──→ y_wet (双耳 reverb)
   │       │                                      │
   │       └─ distance-dependent energy mix ──────┤
   │                                              ▼
   └────────────────────────────────→ mix → stereo headphone out
```

`y_wet` 用的是 "diffuse-field HRTF"——把所有方向 HRTF 平均后得到的一对"环境感" HRIR,代表 reverb 从四面八方来的合成方向响应。这是 Steam Audio 等中间件处理 spatialized reverb 的标准做法。

## 6 · 工业级 middleware 与选型

### 6.1 Steam Audio

Steam Audio(Valve)是免费、跨平台的 spatial audio middleware,与 Steam SDK 一起分发。它提供:

- **Binaural rendering** 用 HRTF(自带 HRTF 数据集,或加载 SOFA);
- **Convolution reverb**(用房间 IR,支持 true stereo / Ambisonic IR);
- **Hybrid reverb**(用参数化模型算早期反射 + convolution 算晚期);
- **Occlusion / obstruction / transmission**——基于几何 ray tracing 算遮挡;
- **Source / listener** 抽象,与游戏引擎(Unreal、Unity)或自定义引擎集成。

Steam Audio 的核心思路:**给你一套封装好的、生产级的 spatial audio 引擎,你不用自己从 HRTF 数据集开始写**。Rust binding 是社区维护的——直接用 C API + FFI 是常见的接入方式。

### 6.2 Oculus Audio(Meta)

Oculus Audio SDK 主要为 VR 头显设计,**强制低延迟**(VR 头动到声变 < 20 ms,否则破坏沉浸感)。它的算法与 Steam Audio 类似(HRTF + 卷积混响 + occlusion),但更强调:

- 极低 latency(支持 256 sample partition);
- 与 VR 头部追踪(Meta Quest)深度集成;
- 内置 room acoustic modeling(基于几何,实时算早期反射)。

### 6.3 Resonance Audio(Google)

Google 的 Resonance Audio,早期为 AR/VR 设计(原 GVR Audio SDK),与 Daydream、Cardboard、Tango 一起出现,后来独立成 spatial audio 库。它强调:

- 高性能(mobile-friendly,适合手机);
- Ambisonic 中间表示——所有声源先 pan 到 Ambisonic 域(球谐函数),最后一次性 binaural 解码;
- 与 Web Audio API / Unity / Unreal 集成。

Ambisonic 路线是 Resonance Audio 的特色:**当声源很多时,每个声源都做一次 binaural 渲染太贵,先 pan 到 Ambisonic 域(便宜的 operation),最后一次性 binaural 解码(只做一次)**。这是一种"延迟 binaural"的优化,工业上 Resonance Audio 用得最多,Steam Audio 也支持。

### 6.4 选型决策

选型要算清这几件事:

- **平台**:Meta Quest / Sony PSVR 选 Oculus Audio 或 Sony Tempest;PC / Mac / Mobile 选 Steam Audio 或 Resonance Audio;
- **延迟**:VR 必须 ≤ 20 ms,选支持小 partition(256-512 sample)的;
- **生态**:已经在用 FMOD / Wwise,优先看它们的内置 spatializer(都基于某种 HRTF + 混响组合),不一定需要单独接 Steam Audio;
- **开源 vs 闭源**:Steam Audio 和 Resonance Audio 都开放(免费,非严格 OSS),自己改得起;FMOD / Wwise 闭源,但工程化最好。

理解这一篇的原理后,你不再被这些工具的"营销术语"困惑——所有工具内部都在做同一组核心操作:HRIR 卷积、房间 IR 卷积、距离衰减、几何遮挡。区别在算法细节(HRTF 数据集、reverb 是 convolution 还是 hybrid、occlusion 是 ray cast 还是 voxel)、性能优化(Ambisonic 路径、SIMD)、生态集成。

### 6.5 扬声器 vs 耳机——crosstalk cancellation

最后讲一个常被忽略的工程现实。HRTF 的全部线索**只在耳机里成立**——它预设了"左耳信号只到左耳,右耳信号只到右耳"。但用扬声器时,左扬声器的声音会被头阻挡后才到右耳,这个"串扰"(crosstalk)破坏了 HRTF 的双耳分离假设,让听感"回到普通 stereo"。

要让扬声器也能重放 binaural 信号,要做 **crosstalk cancellation**(串扰消除)——用反相滤波器预先补偿串扰路径。这是 1960s Bauer 提出的思路,现代实现有oshi Chowning 早期工作、Baalman 的 crosstalk cancellation 等。但 crosstalk cancellation 对听音位置极敏感(甜区 sweet spot 很小,头偏几厘米就失效),且房间反射会进一步破坏,所以游戏在家用扬声器场景几乎不用——**HRTF 等于绑定耳机使用**。

扬声器 3D audio 的另一条路是 **wave field synthesis / Ambisonic decoding to speaker array**——这是大型 venue(影院、planetarium)的技术,家用游戏罕见。所以家用游戏的"3D audio"基本默认就是"耳机 + HRTF"。Sony PS5 的 Tempest 3D Audio 是个例外——它做了 TV speaker 也能感知的 3D,但底层仍是 HRTF + 复杂的 speaker-aware crosstalk cancellation,效果比耳机弱。

## 7 · 在你 HH 项目里动手(做中学红线)

这一节是这一篇的实践红线——做完这几件事,你才真的"会用卷积和 HRTF"。

### 7.1 落地 1:抓 IR,卷一个 dry sample,听见那个空间

第一步,**抓一段 IR**。两条路:

- 从 Open AIR(lib.openairlib.net)下载一个 WAV 格式 IR,比如 "York Minster Cathedral" 的 stereo IR;
- 或自己录——在你的客厅或任何你想"借"的空间,用手机录一个气球爆裂或一本厚书合上的瞬态声。这质量不高,但你能体会 IR 录制的过程。

第二步,**抓一段 dry 音频**。最好是 footstep 或一句 vocal——没有 reverb 的纯干声。

第三步,**离线跑一次 FFT 卷积**(用上面 §2.2 的 `convolve_fft`)。把 dry 与 IR 卷一遍,写到一个 WAV 文件,听一听。这一步的"哇"时刻——同一个 footstep,卷上不同 IR,你能听到它在不同空间里的真实声音。

```rust
fn load_wav_mono(path: &str) -> Vec<f32> {
    // Use hound crate to load WAV, convert to mono f32
    let mut reader = hound::WavReader::open(path).unwrap();
    let spec = reader.spec();
    let samples: Vec<f32> = reader.samples::<i16>()
        .map(|s| s.unwrap() as f32 / 32768.0)
        .collect();
    // If stereo, average to mono
    if spec.channels == 2 {
        samples.chunks(2).map(|c| (c[0] + c[1]) * 0.5).collect()
    } else {
        samples
    }
}

fn save_wav_mono(path: &str, samples: &[f32], sample_rate: u32) {
    let spec = hound::WavSpec {
        channels: 1,
        sample_rate,
        bits_per_sample: 16,
        sample_format: hound::SampleFormat::Int,
    };
    let mut writer = hound::WavWriter::create(path, spec).unwrap();
    for &s in samples {
        let v = (s.clamp(-1.0, 1.0) * 32767.0) as i16;
        writer.write_sample(v).unwrap();
    }
}

// Usage:
//   let dry = load_wav_mono("footstep_dry.wav");
//   let ir = load_wav_mono("york_minster_ir.wav");
//   let wet = convolve_fft(&dry, &ir);
//   save_wav_mono("footstep_in_york.wav", &wet, 48000);
```

这一步是 offline 的,不要担心 CPU——上面那个 footstep + York Minster IR 的卷积,FFT 路径在一秒内能跑完。

### 7.2 落地 2:实时 partitioned convolution reverb 进 audio callback

进 audio thread。把 §2.4 的 `PartitionedConvolver` 接进你的 audio callback:

```rust
pub struct ConvolutionReverbEffect {
    convolver: PartitionedConvolver,
    // For stereo: two convolvers (or one stereo convolver)
    left: PartitionedConvolver,
    right: PartitionedConvolver,
}

impl ConvolutionReverbEffect {
    pub fn new(ir_left: &[f32], ir_right: &[f32], block_size: usize) -> Self {
        Self {
            convolver: PartitionedConvolver::new(ir_left, block_size), // unused
            left: PartitionedConvolver::new(ir_left, block_size),
            right: PartitionedConvolver::new(ir_right, block_size),
        }
    }
}

impl AudioEffect for ConvolutionReverbEffect {
    fn process(&mut self, input: &[f32], output: &mut [f32]) {
        // input is interleaved stereo
        let n_frames = input.len() / 2;
        let bs = self.left.block_size;
        debug_assert_eq!(n_frames, bs, "audio callback block must match partition size");

        // Split input to mono L and R (or sum to mono first for cheaper path)
        let mut mono = vec![0.0f32; bs];
        for i in 0..bs {
            mono[i] = input[i * 2] + input[i * 2 + 1] * 0.5; // slight L bias
        }
        let mut out_l = vec![0.0f32; bs];
        let mut out_r = vec![0.0f32; bs];
        self.left.process_block(&mono, &mut out_l);
        self.right.process_block(&mono, &mut out_r);

        for i in 0..bs {
            output[i * 2] = out_l[i];
            output[i * 2 + 1] = out_r[i];
        }
    }

    fn reset(&mut self) {
        // Reset history buffers — left/right structs each hold their own state.
    }
}
```

(`AudioEffect` trait 来自 [audio-effects](./audio-effects.md) §1.2。)

把一个 dry mono source 喂进这个 effect,听到它**真的在那间教堂里**。注意 latency——`block_size = 1024` 时,21 ms 的延迟。如果你的 HH 项目 audio callback 块大小是 480,要么把 partition size 设到 480(效率略差,FFT-960 不是 power of 2),要么做内部 buffering 累积到 1024 再处理。这是 partitioned convolution 集成的真实复杂度。

### 7.3 落地 3:HRTF panner——把 mono 绕头转一圈

最有"啊哈"时刻的练习。**下载 MIT KEMAR 数据集**(compact form,710 个方向的 HRIR,每个 128 sample)。写一个 panner:

```rust
pub struct KemarPanner {
    // HRIR dataset indexed by (azimuth_idx, elevation_idx)
    dataset: KemarDataset,
    // Current direction (smoothly interpolated)
    current_azimuth: f32,
    current_elevation: f32,
    // Two HRTF filters (L / R), reused across frames
    filter_l: HrtfFilter,
    filter_r: HrtfFilter,
}

impl KemarPanner {
    pub fn new(dataset: KemarDataset) -> Self {
        let (hrir_l, hrir_r) = dataset.lookup(0.0, 0.0);
        Self {
            dataset,
            current_azimuth: 0.0,
            current_elevation: 0.0,
            filter_l: HrtfFilter::new(hrir_l.to_vec(), vec![]),
            filter_r: HrtfFilter::new(vec![], hrir_r.to_vec()),
        }
    }

    pub fn set_direction(&mut self, azimuth: f32, elevation: f32) {
        // Smooth direction change to avoid clicks
        let smooth = 0.05;
        self.current_azimuth = self.current_azimuth * (1.0 - smooth) + azimuth * smooth;
        self.current_elevation = self.current_elevation * (1.0 - smooth) + elevation * smooth;
        // Interpolate HRIR
        let (hrir_l, hrir_r) = self.dataset.interpolate(self.current_azimuth, self.current_elevation);
        self.filter_l.set_hrir(&hrir_l, &hrir_l); // simplified: same HRIR to both filters
        // (Real implementation has separate filter per ear; shown simplified for clarity.)
    }

    pub fn process(&mut self, input: &[f32], out_l: &mut [f32], out_r: &mut [f32]) {
        // Run two HRTF filters in parallel
        self.filter_l.process(input, out_l, out_r); // simplified
    }
}
```

(把 `filter_l` / `filter_r` 设计成结构对、再修一下 trait——上面是结构示意。完整实现请参考 [adaptive-audio-and-3d](../../phase-7/deep-dives/adaptive-audio-and-3d.md) §3.3 的 `HrtfRenderer`,它已经把 L/R HRIR 同时处理。)

**测试方法**:生成一段 4 秒的 mono 噪声或一段 vocal,**用 LFO 让 azimuth 从 -π 缓慢扫到 π**(elevation 保持 0)。导出 stereo WAV,**戴上耳机听**。第一次听到声音真的从左前方绕到正前方再绕到右后方,你就懂 HRTF 的魔法。

### 7.4 落地 4:把卷积混响与 HRTF 串起来——完整的 spatial reverb

终极练习。把这两件事拼起来:

```
mono source x
    │
    ├────────→ HRTF (θ, φ) ∗ → dry 双耳
    │
    └──→ room IR ∗ → diffuse HRTF ∗ → wet 双耳
                                  │
                                  ▼
                        按 distance 调 wet/dry 比例
```

实现思路:把你的 HRTF panner 处理一遍得到 dry 双耳;同时把 source 喂进 `PartitionedConvolver`(用房间 IR),输出 wet mono;再把 wet mono 通过一对 diffuse-field HRIR(把所有方向 HRTF 平均得到)处理,变成 wet 双耳;最后把 dry 与 wet 按距离衰减比例混合,送到耳机。这就是 Steam Audio 内部做的事。

```rust
pub struct SpatializedReverb {
    dry_panner: KemarPanner,
    room_convolver_l: PartitionedConvolver,
    room_convolver_r: PartitionedConvolver,
    diffuse_hrir_l: Vec<f32>,
    diffuse_hrir_r: Vec<f32>,
    distance: f32,
    ref_distance: f32,
}

impl SpatializedReverb {
    pub fn process(&mut self, input: &[f32], out_l: &mut [f32], out_r: &mut [f32]) {
        let bs = input.len();
        // 1. Dry path: HRTF
        let mut dry_l = vec![0.0f32; bs];
        let mut dry_r = vec![0.0f32; bs];
        self.dry_panner.process(input, &mut dry_l, &mut dry_r);
        // 2. Wet path: room convolution
        let mut wet_l = vec![0.0f32; bs];
        let mut wet_r = vec![0.0f32; bs];
        self.room_convolver_l.process_block(input, &mut wet_l);
        self.room_convolver_r.process_block(input, &mut wet_r);
        // (Apply diffuse HRIR to wet path here — omitted for brevity.)
        // 3. Mix based on distance (closer = more dry, farther = more wet)
        let dry_gain = 1.0 / (1.0 + self.distance / self.ref_distance);
        let wet_gain = 1.0 - dry_gain;
        for i in 0..bs {
            out_l[i] = dry_l[i] * dry_gain + wet_l[i] * wet_gain;
            out_r[i] = dry_r[i] * dry_gain + wet_r[i] * wet_gain;
        }
    }
}
```

这是 pro-grade spatial audio 的核心结构。再加 distance attenuation、occlusion、Doppler,你就有了 Steam Audio 级别的引擎。

## 8 · 练习

**Lv 1(基础)**:用 §2.2 的 `convolve_fft` 把一段你录的或下载的 dry vocal 与一段 Open AIR IR 卷积,导出 WAV 听效果。换 3 个不同 IR,听同一个 vocal 在不同空间里的变化。

**Lv 2(理解)**:实现 §2.4 的 `PartitionedConvolver`,接到你 HH 项目的 audio callback 里(用 [audio-effects](./audio-effects.md) 的 `AudioEffect` trait)。测延迟——用 `cargo build --release` 跑,在 callback 里加 timestamp log,验证输出延迟 = `block_size / sample_rate`。然后实测 CPU 占用(用 `perf` 或 Tracy),验证 §2.4 给的性能数据。

**Lv 3(深入)**:实现 §5.1 的 HRIR bilinear interpolation,接 §7.3 的 KemarPanner。**测听感**——找一个朋友做盲测,让他/她闭眼,你用 azimuth 控制让声音在 8 个方位(前、右前、右、右后、后、左后、左、左前)随机出现,记录他/她判断正确率。应该 > 70%(前后混淆是主要的错误来源)。

**Lv 4(进阶)**:实现 §7.4 的 `SpatializedReverb`,接 dry HRTF + 房间卷积 + diffuse HRIR + 距离 wet/dry 混合。**做个 demo**:键盘控制 listener 在一个虚拟房间走动,声音从固定 source 发出。走近 source 听到更干、更响;走远听到更多房间残响、更柔和、感觉更远。这是 spatial audio 完整体验。

## 9 · 延伸阅读

本仓库相关:

- [audio-effects.md](./audio-effects.md) — 效果器全解(Schroeder reverb、Freeverb、FDN、压缩器、EQ),这一篇的姊妹篇,算法 reverb 路线
- [adaptive-audio-and-3d.md](../../phase-7/deep-dives/adaptive-audio-and-3d.md) — 自适应音乐与 3D 空间音频,这一篇的扩展应用(panning law、距离衰减、occlusion、Doppler、voice chat)
- [dsp-fundamentals.md](./dsp-fundamentals.md) — DSP 基础(FIR/IIR/卷积),这一篇的前置
- [fft-and-spectral-analysis.md](./fft-and-spectral-analysis.md) — FFT 与频谱分析,FFT 卷积的数学基础
- [phase-0/22-signals-foundation.md](../../phase-0/22-signals-foundation.md) — 信号基础,LTI 系统与脉冲响应的理论根基

外部稳定 URL:

- Open AIR IR 库:https://openair.lib.ed.ac.uk/
- SOFA 格式标准:https://www.sofaconventions.org/
- MIT KEMAR HRTF 数据集:https://sound.media.mit.edu/resources/KEMAR.html
- CIPIC HRTF 数据集:https://www.ece.ucdavis.edu/cipic/spatial-sound/hrtf-data/
- ARI HRTF(SADIE):https://www.kfs.oeaw.ac.at/index.php?option=com_content&view=article&id=8&Itemid=8
- Steam Audio 文档:https://valvesoftware.github.io/steam-audio/
- Resonance Audio 文档:https://resonance-audio.github.io/resonance-audio/
- Oculus Audio SDK:https://developer.oculus.com/documentation/native/audio-ovraudio/
- Farina 2000 "Simultaneous Measurement of Impulse Response and Distortion with a Swept-Sine Technique"(AES):https://www.aes.org/e-lib/browse.cfm?elib=15645
- Gardner & Martin 1994 "HRTF Measurements of a KEMAR Dummy-Head Microphone"(MIT Media Lab Perceptual Computing TR #280)
- Blauert "Spatial Hearing: The Psychophysics of Human Sound Localization"(MIT Press,revised edition)
- Begault & Treman "3-D Sound for Virtual Reality and Multimedia"(2000)
- Vorländer "Auralization: Fundamentals of Acoustics, Modelling, Simulation, Algorithms and Acoustic Virtual Reality"(Springer)

开源源码:

- `rustfft`:https://github.com/ejmahler/rustfft — 这一篇 FFT 卷积的底层
- `realfft`:https://github.com/HEnquist/realfft — real-to-complex FFT wrapper,简化 real audio 处理
- `hound`:https://github.com/ruuda/hound — WAV 读写
- Steam Audio(参考实现,C++):https://github.com/ValveSoftware/steam-audio
- Resonance Audio(Google,C++):https://resonance-audio.github.io/resonance-audio/developer-guides
- `libmysofa`:https://github.com/hoene/libmysofa — SOFA 文件加载(C,Rust binding 可自写)

---

写到这里,你的工具箱里多了两件利器:**卷积混响**和 **HRTF 渲染**。它们共用同一种数学操作——卷积——只是被卷的脉冲响应描述的系统不同,一个是房间,一个是头。卷积混响把"借用真实空间"做到了极致,代价是 CPU 和 latency;HRTF 把"在耳机里还原外部声场"做到了极致,代价是个体化差异和扬声器失效。

接下来:**关掉 IDE 旁的扬声器,戴上耳机,打开你的 HH 项目,把 York Minster 的 IR 接进 footstep 的 send。第一次听到你的 footstep 在那座千年教堂里真的响起来,你就懂这一篇的全部**。然后给一个 NPC 加上 HRTF panner,让它在你身后绕一圈走——你回头去找那个声音,会发现你的头真的在转,而它已经从左后方绕到了右前方。**空间音频的魔法,从你戴上耳机、闭上眼睛、听见声音"在外面"的那一瞬间开始。**
