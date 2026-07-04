
# 22 · 信号基础:从声波到滤波器

> 你想给游戏加音效。你写代码:`device.write(samples)`。你跑游戏——喇叭出"咔咔"声,不是你想要的枪声。你打开 Audacity 录下"砰"一声,看波形——一万个数字排在一起,你看不出规律。你想"过滤掉低频,只保留高音",但你不知道怎么过滤。你想合成一段音乐,但写出来的"音符"听起来像电话铃声。这些问题的答案全在**信号处理(DSP)** 里。这一篇讲完,你能写一个能用的软件合成器、能做基本的滤波器、能看懂 FFT 的输出、能解释为什么 CD 采样率是 44.1 kHz。

## 0 · 为什么要有这一天

让我把镜头拉到具体场景。

你跟着 Handmade Hero 走到 Day 250,Casey 开始做声音。他用一个简单的合成器——给 `void OutputSoundSamples(int* samples, int count)` 函数填几个数字。Casey 写的代码大概是:

```c
for (int i = 0; i < count; i++) {
    samples[i] = (int)(sin(t) * 1000);
    t += 0.01;
}
```

你跟 Casey 写一样的代码,跑出来——"嗡嗡嗡"的声音。Casey 听起来正常,你听起来也对。然后你改 `t += 0.01` 为 `t += 0.005`——你期待"高八度"(像音乐里那样),但实际听到的是**一个完全不同的怪音**。你打印 t,发现 t 累加得很快,`sin(t)` 在快速振荡,但**为什么 0.005 不是 0.01 的一半频率**?

**真正的问题**:`sin(t)` 的频率取决于"每秒走多少 t"——也就是 **采样率**。CD 音频采样率 44100 Hz,意味着每秒 44100 个样本。如果每样本 t += 0.005,则每秒 t 增加 44100 × 0.005 = 220.5,也就是 `sin` 函数每秒完成 220.5 / (2π) ≈ 35 个完整周期,即 35 Hz。但你想要的是 440 Hz(标准 A4 音)。**你以为的频率和实际频率完全脱节**。

这是 DSP 的第一个陷阱:**离散时间 vs 连续时间**。

第二个陷阱:**Nyquist 定理**。你想合成 30000 Hz 的超声波(狗能听到),但 CD 采样率只有 44100 Hz。你跑代码——听到的是 14000 Hz 左右的"嗡嗡"声。这是**aliasing**——高频"折叠"成低频。理解 Nyquist 才能解释。

第三个陷阱:**量化**。你的样本是 i16,范围 [-32768, 32767]。你写 `samples[i] = sin(t) * 32767`,但**信号太小**(< 100)听不到,**信号太大**(> 32767)被截断失真。这就是**量化噪声**和**削顶失真**。

第四个陷阱:**滤波**。你想"过滤掉 1000 Hz 以下的低频",但你只会用 `if (freq < 1000) remove`——可问题是你在**时域**里,没有"频率"这个维度。要做这事必须**Fourier 变换**转到频域,处理,再转回来。或者用**FIR/IIR 滤波器**直接时域操作。

**这一篇覆盖**:
- 连续 vs 离散信号
- 采样定理 / Nyquist / aliasing(车轮幻觉)
- 量化 / SNR / dB
- 时域 vs 频域 / Fourier 直觉
- DFT 公式推导(求和 → 复指数)
- FFT 概念(留给后续)
- 卷积 / LTI 系统
- 滤波器分类(低/高/带通/带阻)
- Z 变换概念
- 心理声学(等响曲线、掩蔽)

**每一节**:数学推导 → Rust 代码 → 物理/感知直觉 → 三个例子 → 游戏应用。

**心理锚点**:这一篇读完,你能:
- 解释为什么 CD 采样率是 44.1 kHz(为了覆盖到 20 kHz 人耳上限)
- 解释为什么电影里车轮"倒转"(strobe light aliasing)
- 算量化位深对应的 SNR(信噪比)
- 推导 DFT 公式,理解为什么它是"投影到复指数基"
- 写一个 FFT demo(虽然本篇只讲概念,实现在后续 day)
- 解释为什么你"听不见"超低音量但有它存在(掩蔽效应)
- 写一个简单的低通滤波器

## 1 · 概念地图:DSP 的 8 大块

| 块 | 解决什么 | 关键工具 |
|---|---|---|
| **采样** | 连续→离散 | 采样定理 / Nyquist |
| **量化** | 实数→有限位深 | dB / SNR |
| **Fourier** | 时域↔频域 | DFT / FFT |
| **卷积** | 系统对信号的作用 | 卷积和 / 差分方程 |
| **LTI 系统** | 线性时不变 | 冲激响应 |
| **滤波器** | 选择性通过频率 | 低/高/带通/带阻 |
| **Z 变换** | 离散系统的代数分析 | Z 平面 / 极点零点 |
| **心理声学** | 人耳感知特性 | 等响曲线 / 掩蔽 |

---

## 2 · 心智模型

### 2.1 类比:信号是"波形",DSP 是"波形手术"

**声波**是空气压力的波动。你的耳膜感受到压力变化,大脑解释为"声音"。

**信号(Signal)**:就是一组数,表示某物理量随时间(或空间)的变化。音频信号 = 压力随时间;图像信号 = 颜色随位置;视频信号 = 颜色随位置和时间。

**DSP(Digital Signal Processing)**:对这些数做"手术"——放大、过滤、变换、压缩。

**核心直觉**:**所有信号都可以分解为不同频率的"纯正弦"叠加**。这是 Fourier 的伟大发现。声音"亮"是因为有高频成分,声音"闷"是因为低频。`ee` 元音高频多,`oo` 元音低频多。

DSP 的"手术"包括:
- **采样**:从连续波 → 离散点
- **量化**:从实数 → 有限位整数
- **变换**:时域 ↔ 频域(Fourier)
- **过滤**:去掉某些频率
- **混合**:多个信号叠加(卷积 / 调制)

### 2.2 第一原理:时间、振幅、频率

任何信号都由三个"维度"刻画:

- **时间(t)**:什么时候?单位秒(s)。
- **振幅(A)**:多大?单位取决于物理量(帕斯卡 / 伏特 / 无量纲)。
- **频率(f)**:每秒振荡多少次?单位赫兹(Hz)。

**正弦波**:`x(t) = A sin(2π f t + φ)`。三个参数 A, f, φ 完全刻画一个正弦波。

**关键洞察**:任何复杂信号(你说话、音乐、噪声)**都可以表示为大量正弦波的叠加**。这就是 Fourier 分析。

```rust
// 一个 1 秒的正弦波,采样率 44100
fn make_sine(freq: f32, sample_rate: u32, duration_s: f32) -> Vec<f32> {
    let n = (sample_rate as f32 * duration_s) as usize;
    (0..n)
        .map(|i| {
            let t = i as f32 / sample_rate as f32;
            (2.0 * std::f32::consts::PI * freq * t).sin()
        })
        .collect()
}

fn main() {
    let samples = make_sine(440.0, 44100, 1.0);  // A4 音
    println!("样本数: {}", samples.len());
    println!("前 5 个样本: {:?}", &samples[..5]);
}
```

---

## 3 · 连续 vs 离散信号

### 3.1 连续时间信号

**连续信号** `x(t)`:t 是连续实数。每个 t 都有 x 值。物理世界的信号都是连续的——声波、光强、温度。

**例子**:`x(t) = sin(2π·440·t)` 是 440 Hz 的连续正弦波。

### 3.2 离散时间信号

**离散信号** `x[n]`:n 是整数(0, 1, 2, ...)。只在"采样时刻"有值。

**采样操作**:`x[n] = x(n T_s)`,T_s 是采样周期(秒/样本),`f_s = 1/T_s` 是采样率(样本/秒,即 Hz)。

**例子**:对 440 Hz 正弦波以 44100 Hz 采样,采样周期 T_s ≈ 22.7 μs:

```
x[n] = sin(2π·440·n/44100)
     = sin(2π·440/44100·n)
     = sin(0.0627·n)
```

**Rust 代码例子**:连续 vs 离散。

```rust
// 连续:理论函数(计算机无法真正实现)
fn continuous_sine(freq: f32, t: f32) -> f32 {
    (2.0 * std::f32::consts::PI * freq * t).sin()
}

// 离散:实际采样
fn sampled_sine(freq: f32, sample_rate: u32, n: usize) -> f32 {
    let t = n as f32 / sample_rate as f32;
    continuous_sine(freq, t)
}

fn main() {
    let freq = 440.0;
    let sr = 44100;
    // 打印前 10 个采样点
    for n in 0..10 {
        let x = sampled_sine(freq, sr, n);
        let t = n as f32 / sr as f32;
        println!("n={:2}  t={:.6}  x={:+.4}", n, t, x);
    }
}
```

### 3.3 数字信号 = 离散 + 量化

**数字信号**:既离散(时间)又量化(振幅)。这是计算机能处理的。

**量化**:把连续的振幅(比如 -1.0 到 1.0 任意实数)映射到有限个离散值(比如 16 位整数 -32768 到 32767)。

**例**:量化到 16 位:
```
sample_real ∈ [-1.0, 1.0]
sample_i16 = round(sample_real * 32767)
```

---

## 4 · 采样定理与 Nyquist

### 4.1 Nyquist-Shannon 采样定理

**定理**:如果连续信号 x(t) 的最高频率成分是 f_max,那么采样率 `f_s ≥ 2 f_max` 就能完整保留信号信息(可以无失真重建)。

**Nyquist 频率**:`f_Nyquist = f_s / 2`。这是给定采样率下能表示的最大频率。

**例**:人耳听觉范围 20 Hz - 20 kHz。要无失真表示,f_s ≥ 40 kHz。**这就是为什么 CD 是 44.1 kHz**(略高于 40 kHz,留余量给滤波器滚降)。

**例**:电话音频 8 kHz 采样率,Nyquist = 4 kHz。所以电话只能传 4 kHz 以下声音——这就是为什么电话声音"闷"。

**例**:游戏音效 48 kHz(专业音频),Nyquist = 24 kHz,覆盖全人耳范围。

### 4.2 Aliasing(混叠)

**Aliasing**:如果信号有高于 Nyquist 的频率成分,这些成分会"折叠"到低频,产生失真。

**数学**:频率 f 的正弦波以 f_s 采样,看起来像频率 `|f - k·f_s|`(对所有整数 k,取最小正频率)。

**例**:f = 30000 Hz,f_s = 44100 Hz。Alias 频率 = |30000 - 44100| = 14100 Hz。所以 30 kHz 声音在 44.1 kHz 采样下听起来像 14.1 kHz。

**车轮幻觉**:电影 24 FPS。车轮有 12 根辐条,转速 2 圈/秒,看起来"车轮不动"(因为每帧辐条恰好对齐)。如果转速 2.5 圈/秒,看起来"车轮倒转"。这就是采样 aliasing——空间频率被帧率采样,产生错觉。

**strobe light 实验**:在 60 Hz 灯光下转风扇,你会看到风扇"静止"或"慢转"——同样 aliasing。

**Anti-aliasing 滤波器**:实际 ADC(模数转换器)在采样前用低通滤波器去掉 > Nyquist 的频率,防止 aliasing。这就是为什么 CD 录音需要"抗混叠滤波器"。

**Rust 代码例子**:演示 aliasing。

```rust
// 对高频信号低采样率采样,看 alias
fn main() {
    let true_freq = 35000.0;  // 35 kHz
    let sample_rate = 44100.0_f32;
    let nyquist = sample_rate / 2.0;  // 22050 Hz

    // 35000 > 22050,会 alias
    let alias_freq = (true_freq - sample_rate).abs();
    println!("真实频率: {} Hz", true_freq);
    println!("采样率: {} Hz", sample_rate);
    println!("Nyquist: {} Hz", nyquist);
    println!("Alias 频率: {} Hz", alias_freq);  // 9100 Hz

    // 听起来会像 9100 Hz 而不是 35000 Hz
}
```

### 4.3 不同采样率的选择

| 应用 | 采样率 | Nyquist | 理由 |
|---|---|---|---|
| 电话 | 8 kHz | 4 kHz | 语音可懂,带宽省 |
| VoIP | 16 kHz | 8 kHz | 语音更清晰 |
| CD | 44.1 kHz | 22 kHz | 覆盖全人耳 |
| DVD | 48 kHz | 24 kHz | 视频/电影标准 |
| 专业录音 | 96 kHz | 48 kHz | 留余量做处理 |
| 母带 | 192 kHz | 96 kHz | 极致处理空间 |

**为什么 CD 是 44.1 不是 40**:历史原因 + 工程余量。早期数字录音用录像带存储,扫描频率和视频行频决定了 44.1 kHz。后来成为标准。

---

## 5 · 量化、SNR、dB

### 5.1 量化

**量化(Quantization)**:把连续振幅映射到有限离散值。

**均匀量化**:每个量化阶相同大小。`Δ = (max - min) / 2^B`,B 是位深。

**位深(Bits)**:
- 8 位:256 个值,音质差(早期游戏音效)
- 16 位:65536 个值,CD 音质
- 24 位:1600 万个值,专业录音
- 32 位浮点:几乎无限精度,内部处理用

**量化误差**:`e = x_quantized - x_original`,范围 `[-Δ/2, Δ/2]`。

### 5.2 SNR(信噪比)

**SNR = 信号功率 / 噪声功率**(对数刻度)。

**量化噪声功率**:`σ² = Δ²/12`(均匀分布假设)。

**量化 SNR 公式**:`SNR_dB ≈ 6.02·B + 1.76 dB`(B 是位深)。

**例**:
- 16 位:SNR ≈ 96 dB(CD 动态范围)
- 24 位:SNR ≈ 144 dB(专业)
- 8 位:SNR ≈ 50 dB(游戏音效)

**直觉**:每多 1 位,SNR 增加 6 dB(动态范围翻倍)。

### 5.3 dB(分贝)

**dB(Decibel)**:对数比 `dB = 10·log10(P/P_ref)`(功率)或 `20·log10(A/A_ref)`(振幅)。

**为什么对数**:人耳响度感知是对数——10 倍声压听起来"响一倍",而 10 倍声压是 +20 dB。

**常用 dB 参考**:
- 0 dB SPL(声压级):听觉阈值
- 60 dB SPL:正常对话
- 100 dB SPL:地铁
- 120 dB SPL:疼痛阈值
- 130 dB SPL:喷气式飞机起飞

**数字 dBFS(dB Full Scale)**:0 dBFS = 最大数字值(无 clipping),负值表示小于最大。

**Rust 代码例子**:量化与 SNR。

```rust
// 把 [-1, 1] 浮点量化为 i16
fn quantize_to_i16(x: f32) -> i16 {
    let clamped = x.clamp(-1.0, 1.0);
    (clamped * 32767.0).round() as i16
}

// 把 i16 反量化回浮点
fn dequantize_from_i16(s: i16) -> f32 {
    s as f32 / 32767.0
}

// 计算信号的 RMS(Root Mean Square)
fn rms(samples: &[f32]) -> f32 {
    let sum_sq: f32 = samples.iter().map(|&x| x * x).sum();
    (sum_sq / samples.len() as f32).sqrt()
}

// 计算 SNR(信号 RMS / 误差 RMS,转 dB)
fn snr_db(signal_rms: f32, error_rms: f32) -> f32 {
    20.0 * (signal_rms / error_rms).log10()
}

fn main() {
    let mut signal = vec![0.0_f32; 1000];
    for i in 0..1000 {
        signal[i] = (2.0 * std::f32::consts::PI * 440.0 * i as f32 / 44100.0).sin() * 0.5;
    }

    // 量化 + 反量化,看误差
    let quantized: Vec<i16> = signal.iter().map(|&x| quantize_to_i16(x)).collect();
    let recovered: Vec<f32> = quantized.iter().map(|&s| dequantize_from_i16(s)).collect();

    let errors: Vec<f32> = signal.iter().zip(recovered.iter())
        .map(|(&s, &r)| s - r).collect();

    let s_rms = rms(&signal);
    let e_rms = rms(&errors);
    println!("信号 RMS: {}", s_rms);
    println!("误差 RMS: {}", e_rms);
    println!("SNR: {:.2} dB", snr_db(s_rms, e_rms));
    println!("理论 16 位 SNR: ~96 dB(信号 -6 dB 时实际 ~90 dB)");
}
```

---

## 6 · 时域 vs 频域

### 6.1 时域(Time Domain)

**时域表示**:信号随时间的振幅曲线。横轴时间,纵轴振幅。

**Audacity 默认显示**就是时域——你看到声波的"形状"。

**例**:正弦波在时域是正弦曲线。白噪声在时域是"杂乱无章"的随机数。

### 6.2 频域(Frequency Domain)

**频域表示**:信号在不同频率上的能量分布。横轴频率,纵轴振幅(或能量)。

**例**:正弦波在频域是**单个尖峰**(只在那个频率有能量)。白噪声在频域是**平坦的**(所有频率都有相同能量)。

**例**:人声在频域有"基频 + 谐波"结构。基频 100-300 Hz(男低女高),谐波是基频整数倍。

### 6.3 时频表示(Spectrogram)

**时频图**:把信号切成短段,每段做 FFT,横轴时间,纵轴频率,颜色表示能量。

这就是 Audacity 的"频谱视图",也是 Shazam 识别歌曲的关键特征。

---

## 7 · Fourier 变换

### 7.1 Fourier 级数(周期信号)

**Fourier 级数**:任何周期信号 x(t)(周期 T)可以表示为正弦余弦的和:

```
x(t) = a_0/2 + Σ_(n=1)^∞ [a_n cos(2π n f₀ t) + b_n sin(2π n f₀ t)]
其中 f₀ = 1/T 是基频。
```

**等价复数形式**:`x(t) = Σ_(n=-∞)^∞ c_n e^(i 2π n f₀ t)`。

**系数计算**:

```
a_n = (2/T) ∫_0^T x(t) cos(2π n f₀ t) dt
b_n = (2/T) ∫_0^T x(t) sin(2π n f₀ t) dt
```

**几何直觉**:把信号"投影"到 cos 和 sin 基函数上。系数 = 投影长度。

### 7.2 连续 Fourier 变换

**Fourier 变换(FT)**:对非周期信号:

```
X(f) = ∫_-∞^∞ x(t) e^(-i 2π f t) dt
x(t) = ∫_-∞^∞ X(f) e^(i 2π f t) df
```

**意义**:`X(f)` 是频率 f 处的"频率成分"。|X(f)| 是振幅谱,arg X(f) 是相位谱。

### 7.3 离散 Fourier 变换(DFT)

**DFT**:对 N 点离散信号 x[0], x[1], ..., x[N-1]:

```
X[k] = Σ_(n=0)^(N-1) x[n] · e^(-i 2π k n / N),  k = 0, 1, ..., N-1
```

**欧拉公式**:`e^(iθ) = cos θ + i sin θ`。所以:

```
X[k] = Σ x[n] [cos(2π k n / N) - i sin(2π k n / N)]
     = Σ x[n] cos(...) - i Σ x[n] sin(...)
```

**几何直觉**(关键!):X[k] 是 x[n] 在"频率 k 的复指数基"上的投影。

把 x[n] 想象成 N 维向量。e_k[n] = e^(i 2π k n / N) 是这 N 维空间里的一个"基向量"(对每个 k 不同)。所有 e_k 组成正交基。X[k] = ⟨x, e_k⟩(内积)。

**这就是 DFT**:**信号在"频率基"上的分解**,类似 Gram-Schmidt 但用复指数。

**反 DFT**:

```
x[n] = (1/N) Σ_(k=0)^(N-1) X[k] · e^(i 2π k n / N)
```

**频率含义**:X[k] 对应频率 `f_k = k · f_s / N`。k = 0 是 DC(直流,平均),k = 1 是基频(信号长度倒数),k = N/2 是 Nyquist。

**Rust 代码例子**:手动 DFT(慢,但展示概念)。

```rust
// 慢速 DFT,O(N²)
fn dft(signal: &[f32]) -> Vec<(f32, f32)> {
    let n = signal.len();
    let mut spectrum = vec![(0.0_f32, 0.0_f32); n];  // (实部, 虚部)
    for k in 0..n {
        let mut re = 0.0;
        let mut im = 0.0;
        for (i, &x) in signal.iter().enumerate() {
            let angle = -2.0 * std::f32::consts::PI * k as f32 * i as f32 / n as f32;
            re += x * angle.cos();
            im += x * angle.sin();
        }
        spectrum[k] = (re, im);
    }
    spectrum
}

fn magnitude(re: f32, im: f32) -> f32 {
    (re * re + im * im).sqrt()
}

fn main() {
    // 8 点信号,内含 1 个完整周期 + 2 个完整周期
    let n = 8;
    let signal: Vec<f32> = (0..n)
        .map(|i| {
            let t = i as f32 / n as f32;
            (2.0 * std::f32::consts::PI * 1.0 * t).sin()  // 频率 1
            + 0.5 * (2.0 * std::f32::consts::PI * 2.0 * t).sin()  // 频率 2
        })
        .collect();

    println!("信号: {:?}", signal);
    let spectrum = dft(&signal);
    for k in 0..n/2 + 1 {
        let mag = magnitude(spectrum[k].0, spectrum[k].1) * 2.0 / n as f32;
        println!("k={}: magnitude = {:.4}", k, mag);
    }
    // 预期:k=1 振幅大(信号有频率 1), k=2 振幅中等(信号有频率 2, 0.5 倍), 其他接近 0
}
```

**预期输出**:k=1 振幅 ≈ 1.0,k=2 振幅 ≈ 0.5,其他接近 0。这"完美"地反映了原信号成分。

### 7.4 FFT(快速 Fourier 变换)

DFT 直接计算 O(N²)。**FFT** 用分治算法把复杂度降到 O(N log N)。

**核心思想**(Cooley-Tukey):把 N 点 DFT 拆成两个 N/2 点 DFT(偶数和奇数索引),递归。要求 N 是 2 的幂。

```rust
// Cooley-Tukey FFT,递归版本(教学用,工业用迭代版)
fn fft(signal: &mut Vec<(f32, f32)>) {
    let n = signal.len();
    if n <= 1 {
        return;
    }
    assert!(n.is_power_of_two(), "FFT 需要 N 是 2 的幂");

    // 拆分奇偶
    let mut even: Vec<_> = signal.iter().step_by(2).copied().collect();
    let mut odd: Vec<_> = signal.iter().skip(1).step_by(2).copied().collect();

    fft(&mut even);
    fft(&mut odd);

    // 合并
    for k in 0..n/2 {
        let angle = -2.0 * std::f32::consts::PI * k as f32 / n as f32;
        let (c, s) = angle.cos_sin();
        let t = (c * odd[k].0 - s * odd[k].1, s * odd[k].0 + c * odd[k].1);
        signal[k] = (even[k].0 + t.0, even[k].1 + t.1);
        signal[k + n/2] = (even[k].0 - t.0, even[k].1 - t.1);
    }
}

trait CosSin { fn cos_sin(self) -> (f32, f32); }
impl CosSin for f32 { fn cos_sin(self) -> (f32, f32) { (self.cos(), self.sin()) } }

fn main() {
    // 8 点正弦波
    let n = 8;
    let mut signal: Vec<(f32, f32)> = (0..n)
        .map(|i| {
            let t = i as f32 / n as f32;
            let v = (2.0 * std::f32::consts::PI * 1.0 * t).sin();
            (v, 0.0)
        })
        .collect();

    fft(&mut signal);

    for k in 0..n {
        let mag = (signal[k].0.powi(2) + signal[k].1.powi(2)).sqrt();
        println!("k={}: mag = {:.4}", k, mag);
    }
}
```

**FFT 是 DSP 最重要的算法**。Phase 5 会有专门 day 讲 FFT 在频谱分析的应用。

---

## 8 · 卷积与 LTI 系统

### 8.1 卷积(Convolution)

**连续卷积**:`(f * g)(t) = ∫_-∞^∞ f(τ) g(t - τ) dτ`。

**离散卷积**:`(x * h)[n] = Σ_(k=-∞)^∞ x[k] h[n - k]`。

**直觉**:卷积是"滑动平均的推广"——h 是"权重函数",x 是"输入",输出是"x 的加权和,权重来自 h"。

**几何操作**:
1. 把 h 翻转(flip)
2. 平移 h(translate)
3. 与 x 逐点相乘(multiply)
4. 求和(integrate)

这是"flip-slide-multiply-sum"四步。

### 8.2 LTI 系统

**线性时不变(LTI)**系统满足:
- **线性**:`T[a x₁ + b x₂] = a T[x₁] + b T[x₂]`(放大叠加守恒)
- **时不变**:输入延迟 t₀,输出也延迟 t₀(系统性质不随时间变)

**核心定理**:LTI 系统完全由其**冲激响应 h[n]** 决定。输出 = 输入卷积冲激响应:`y[n] = (x * h)[n]`。

**冲激响应**:输入单位冲激 δ[n](n=0 时为 1,其他为 0)的输出。

**例**:移动平均是 LTI 系统。h[n] = (1/3) for n=0,1,2;else 0。`(x * h)[n] = (x[n] + x[n-1] + x[n-2]) / 3`。

### 8.3 卷积定理

**定理**:**时域卷积 = 频域相乘**。

```
y = x * h   ⟺   Y(f) = X(f) · H(f)
```

这就是为什么 FFT 重要——卷积直接计算 O(N²),用 FFT 卷积 O(N log N)。

**应用**:FIR 滤波器在时域是卷积,在频域是乘法。设计滤波器时,在频域定 H(f),反 Fourier 得 h[n],然后卷积。

**Rust 代码例子**:简单卷积(移动平均)。

```rust
// 离散卷积
fn convolve(signal: &[f32], kernel: &[f32]) -> Vec<f32> {
    let n = signal.len();
    let m = kernel.len();
    let mut out = vec![0.0; n + m - 1];
    for i in 0..n {
        for j in 0..m {
            out[i + j] += signal[i] * kernel[j];
        }
    }
    out
}

fn main() {
    // 输入:阶跃信号
    let signal: Vec<f32> = vec![1.0, 1.0, 1.0, 1.0, 1.0];
    // 核:移动平均 (3 点)
    let kernel: Vec<f32> = vec![1.0/3.0, 1.0/3.0, 1.0/3.0];

    let result = convolve(&signal, &kernel);
    println!("卷积结果: {:?}", result);
    // 预期:开始处上升,中间稳定 1.0,结束处下降
}
```

---

## 9 · 滤波器

### 9.1 滤波器分类

| 类型 | 通过什么 | 阻止什么 | 应用 |
|---|---|---|---|
| **低通(Low Pass)** | 低频 | 高频 | 去毛刺、模糊、低音 |
| **高通(High Pass)** | 高频 | 低频 | 边缘检测、高音、去 DC |
| **带通(Band Pass)** | 中频某段 | 两端 | 选特定频率 |
| **带阻(Band Stop)** | 两端 | 中频某段 | 去 50/60 Hz 工频 |

### 9.2 FIR 滤波器

**FIR(Finite Impulse Response)**:输出只依赖输入,不依赖过去输出。

```
y[n] = Σ_(k=0)^(M) b_k · x[n-k]
```

是有限长冲激响应(冲激响应 = 系数 b_k)。

**特点**:总是稳定(因为没反馈)。线性相位(如果系数对称)。

### 9.3 IIR 滤波器

**IIR(Infinite Impulse Response)**:输出依赖输入和过去输出(反馈)。

```
y[n] = Σ_(k=0)^(M) b_k · x[n-k] - Σ_(k=1)^(N) a_k · y[n-k]
```

**特点**:用更少系数达到陡峭滚降。但可能不稳定(极点在单位圆外)。相位非线性。

### 9.4 简单一阶低通滤波器

最简单的低通:`y[n] = α · x[n] + (1-α) · y[n-1]`。

α 控制截止频率。`α = 1` 不过滤,`α = 0` 完全过滤。

**截止频率近似**:`f_c ≈ α · f_s / (2π)`。

**Rust 代码例子**:一阶低通。

```rust
struct LowPass {
    alpha: f32,
    prev: f32,
}

impl LowPass {
    fn new(alpha: f32) -> Self {
        Self { alpha, prev: 0.0 }
    }
    fn process(&mut self, x: f32) -> f32 {
        self.prev = self.alpha * x + (1.0 - self.alpha) * self.prev;
        self.prev
    }
}

fn main() {
    let mut lp = LowPass::new(0.1);  // 平滑
    // 输入:阶跃
    let inputs: Vec<f32> = (0..50).map(|_| 1.0).collect();
    let outputs: Vec<f32> = inputs.iter().map(|&x| lp.process(x)).collect();
    for (i, &y) in outputs.iter().enumerate().take(10) {
        println!("n={}: y={:.4}", i, y);
    }
    // 输出:缓慢上升到 1.0(低通响应)
}
```

### 9.5 简单一阶高通滤波器

**高通**:输出 = 输入 - 低通。

```
y[n] = x[n] - lp(x[n])
```

或者直接公式:`y[n] = α · (y[n-1] + x[n] - x[n-1])`。

```rust
struct HighPass {
    alpha: f32,
    prev_y: f32,
    prev_x: f32,
}

impl HighPass {
    fn new(alpha: f32) -> Self {
        Self { alpha, prev_y: 0.0, prev_x: 0.0 }
    }
    fn process(&mut self, x: f32) -> f32 {
        let y = self.alpha * (self.prev_y + x - self.prev_x);
        self.prev_y = y;
        self.prev_x = x;
        y
    }
}
```

---

## 10 · Z 变换

### 10.1 定义

**Z 变换**:`X(z) = Σ_(n=0)^∞ x[n] z^(-n)`。

**作用**:把差分方程变成代数方程,用代数工具分析滤波器。

### 10.2 性质

- **延迟**:`x[n-k]` 的 Z 变换 = `z^(-k) X(z)`。
- **卷积定理**:`x * h` 的 Z 变换 = `X(z) H(z)`。

### 10.3 极点零点

滤波器的传递函数 `H(z) = B(z) / A(z)`,B 和 A 是多项式。

- **零点(Zero)**:B(z) = 0 的 z 值。频率响应"凹陷"处。
- **极点(Pole)**:A(z) = 0 的 z 值。频率响应"峰值"处。
- **稳定性**:所有极点在单位圆 |z| = 1 内。

**直觉**:极点靠近单位圆 → 该频率被放大(共振)。零点在单位圆上 → 该频率完全被消除。

**例**:低通滤波器极点在正实轴上(接近 +1),零点在 z = -1(高频被消除)。

### 10.4 设计滤波器的标准流程

1. 在频域指定 H(f)(通带、阻带、过渡带、衰减)。
2. 用 Z 变换找极点零点。
3. 写出 H(z) 的多项式比。
4. 反推差分方程系数 b_k, a_k。
5. 在代码里实现。

工业级用 `scipy.signal` 或 MATLAB 函数(butter, cheby1, ellip)自动算系数。Rust 用 `biquad` crate。

---

## 11 · 心理声学

人耳不是麦克风。听觉感知有一系列"非线性",影响音频编码。

### 11.1 等响曲线

**Fletcher-Munson 曲线**(1933):人耳对不同频率的灵敏度不同。

- **3-4 kHz 最敏感**(耳道共振频率)
- **低频(< 100 Hz)不敏感**(需要更大声压才能听起来一样响)
- **极高频(> 15 kHz)不敏感**

**例**:同样 60 dB SPL 的 1 kHz 和 100 Hz 声音,1 kHz 听起来"响得多"。要让 100 Hz 听起来一样响,需要 ~75 dB SPL。

**应用**:
- **HiFi 系统**有"响度"按钮——低音量时提升低频,补偿 Fletcher-Munson。
- **音频压缩**(MP3、AAC)利用这点——低频"听不见"的部分不编码,节省比特。

### 11.2 掩蔽(Masking)

**掩蔽**:一个声音让另一个声音"听不见"。

**同时掩蔽**:1000 Hz 强音 + 1100 Hz 弱音 → 听不见 1100 Hz(被掩蔽)。

**前向掩蔽**:强音停止后短时间内,弱音听不见(几毫秒到 200 毫秒)。

**后向掩蔽**:强音开始前短时间内,弱音也听不见(几毫秒)。

**应用**:**MP3 / AAC 的核心压缩机制**——基于掩蔽模型丢弃"听不见"的频率成分,大幅减少数据量而听感不变。

### 11.3 临界频带

人耳把音频分成 24 个"临界频带"(critical bands),每个带内频率互相掩蔽。这是 Bark 尺度的基础。

**应用**:
- 音频压缩的"子带编码"
- 音高感知实验
- 助听器设计

### 11.4 立体声与空间感

**双耳效应**:左右耳听到声音的微小时间差(ITD,< 1 ms)和强度差(ILD),大脑解码为方向。

**HRTF(Head-Related Transfer Function)**:头部对来自不同方向声音的频率响应。3D 音频(杜比全景声、Sony 360 Reality Audio)用 HRTF 让耳机有空间感。

**游戏应用**:FPS 游戏的"听声辩位"依赖双耳效应 + HRTF。

---

## 12 · 四域深入

### 12.1 · 🎮 游戏编程视角

游戏音频的三层:

**采样层**:把 WAV/OGG 文件读出来,通过混音器合成。SDL_mixer、FMOD、Wwise 都做这层。

**合成层**:用代码生成声音(不依赖预录样本)。**适合程序化音乐、动态音效**。Casey 在 Handmade Hero Day 250+ 用合成器做基础音。

**效果层**:加滤波器、混响、压缩、变调等效果。FMOD / Wwise 自带,自己实现也常见。

### 12.2 · 🎨 图形学视角

DSP 在图形里的应用:

**图像处理**:图像 = 2D 信号。卷积 = 模糊 / 锐化 / 边缘检测。Gaussian blur 是 2D Gaussian 卷积。

**程序化纹理**:Perlin 噪声、Worley 噪声是"频域设计"的——控制不同频率成分生成自然外观。

**反走样**:MSAA、SSAA、FXAA、TAA 都是抗 aliasing(虽然不是声音的 aliasing,概念一致——高频折叠成低频的伪影)。

**信号重建**:纹理过滤(双线性、三线性、各向异性)是低通滤波,防止采样 aliasing。

### 12.3 · 🐧 Linux 系统编程视角

Linux 音频栈:

```
应用 → PulseAudio/PipeWire → ALSA → 内核驱动 → 硬件
```

**ALSA(Advanced Linux Sound Architecture)**:内核级音频驱动。直接 ALSA 编程最底层,延迟最低。

**PulseAudio**:桌面用,网络透明,有混音。延迟稍高。

**PipeWire**:新一代,统一 PulseAudio 和 JACK(专业音频),低延迟。

**JACK**:专业音频,实时调度。

游戏开发常用 ALSA(低延迟)或 PulseAudio(易用)。Rust 的 `cpal` crate 跨平台抽象底层 API。

```bash
# 看 Linux 音频设备
aplay -l

# 看当前音频服务
systemctl --user status pipewire pulseaudio

# 看 ALSA 配置
cat /proc/asound/cards
```

### 12.4 · 🦀 Rust 生态视角

Rust 音频生态:

- **cpal**:跨平台音频 IO(类似 PortAudio)。
- **rodio**:基于 cpal 的高层播放库。
- **rustfft**:FFT 实现。
- **biquad**:双二阶(IIR)滤波器。
- **dasp**:Digital Audio Signal Processing,综合工具。
- **fundsp**:合成器框架。
- **kira**:游戏音频引擎。

```toml
[dependencies]
cpal = "0.15"
rustfft = "6.2"
```

---

## 13 · 认知地图

### 13.1 上级

- **信号与系统**:DSP 的数学理论框架。
- **信息论**:Shannon 的"通信数学理论"。比特率、熵、信道容量。
- **通信原理**:调制、解调、信道编码。
- **心理声学**:人耳感知特性。

### 13.2 同级

| 分支 | 研究什么 |
|---|---|
| 1D 信号处理 | 音频 |
| 2D 信号处理 | 图像 |
| 3D 信号处理 | 视频、体积数据 |
| 自适应信号处理 | 系统参数自动调整 |
| 统计信号处理 | 含噪声的信号估计 |

### 13.3 下级

- 采样 / 量化 / Fourier / 卷积 / LTI / 滤波器 / Z 变换 / 心理声学

---

## 14 · 对照与变奏

### 14.1 时域 vs 频域

| 时域 | 频域 |
|---|---|
| 振幅随时间 | 振幅随频率 |
| Audacity 默认视图 | Audacity 频谱视图 |
| 直接录音得到 | Fourier 变换得到 |
| 卷积 | 乘法 |
| 微分 | 乘 j 2π f |
| 延迟 | 乘 e^(-j 2π f τ) |

### 14.2 FIR vs IIR

| FIR | IIR |
|---|---|
| 有限冲激响应 | 无限冲激响应 |
| 无反馈 | 有反馈 |
| 总是稳定 | 可能不稳定 |
| 线性相位(可设计) | 非线性相位 |
| 阶数高 | 阶数低 |
| 计算量大 | 计算量小 |

### 14.3 历史

- **1807**:Fourier 提出热传导的 Fourier 级数。
- **1933**:Fletcher-Munson 等响曲线。
- **1948**:Shannon 信息论 + 采样定理。
- **1965**:Cooley-Tukey FFT 算法(引爆 DSP)。
- **1980s**:CD 数字音频普及。
- **1990s**:MP3 利用心理声学压缩。
- **2000s**:GPU 通用计算 + 实时 DSP。
- **2010s**:神经网络降噪(AirPods Pro、Sony 降噪)。

---

## 15 · 关联 Day

- **铺垫**:[20-math-foundation-extended.md](20-math-foundation-extended.md) — 微积分、复数、Fourier 的数学基础;[21-physics-foundation.md](21-physics-foundation.md) — 振动是声波的基础
- **当天**:22-signals-foundation(本篇)
- **后续**:Phase 5 有专门的 FFT / 频谱分析 day;Phase 4 物理引擎的弹性波也是 DSP 应用

---

## 16 · 变式训练

### Lv1 · 概念辨析

**题**:为什么 CD 采样率是 44.1 kHz,不是 40 kHz?

**参考解答**:Nyquist 要求 f_s ≥ 2 × 20 kHz = 40 kHz。但实际需要"抗混叠滤波器"——它不是理想矩形,有滚降过渡带。40 kHz 滤波器要在 20 kHz 完全通过、20.0001 kHz 完全阻止,工程上做不到。44.1 kHz 给了 2.05 kHz 过渡带,模拟滤波器可以做到。这是工程权衡。

### Lv2 · 动手实践

**题**:写一个 Rust 程序,生成 1 秒 440 Hz 正弦波,量化到 16 位,用 cpal 播放。

**完成标准**:听到清晰的"A4 音"。

**参考答案骨架**:

```rust
use cpal::traits::{StreamTrait, DeviceTrait};

fn main() {
    let host = cpal::default_host();
    let device = host.default_output_device().unwrap();
    let config = device.default_output_config().unwrap();
    let sample_rate = config.sample_rate().0;
    let channels = config.channels() as usize;

    let mut sample_idx = 0usize;
    let stream = device.build_output_stream(
        &config.into(),
        move |data: &mut [f32], _: &cpal::OutputCallbackInfo| {
            for frame in data.chunks_mut(channels) {
                let t = sample_idx as f32 / sample_rate as f32;
                let v = (2.0 * std::f32::consts::PI * 440.0 * t).sin() * 0.5;
                for sample in frame.iter_mut() {
                    *sample = v;
                }
                sample_idx += 1;
            }
        },
        |e| eprintln!("error: {}", e),
        None,
    ).unwrap();
    stream.play().unwrap();
    std::thread::sleep(std::time::Duration::from_millis(1000));
}
```

### Lv3 · 迁移设计

**题**:你想给游戏加"水下音效"——所有声音低通滤波,听起来闷闷的。设计一个方案。

**提示**:
- 水下听音:高频被水吸收,剩低频。
- 一阶低通:见 9.4 节代码。
- 设计截止频率:大约 1-2 kHz。
- α = 2π f_c / f_s,或用更精确公式。

### Lv4 · 开源贡献

**题**:rustfft GitHub: https://github.com/ejmahler/rustfft

1. Clone,看 `src/lib.rs` 的算法结构。
2. 对比本篇的简化版,看工业代码加了什么(radix-4、SIMD、特殊长度优化)。
3. 写一个 PR:补一个 example 演示频谱分析。

---

## 17 · Rust / Arch 落地代码

### 17.1 综合 demo:正弦波 + DFT + 滤波器

```rust
// 完整 demo:生成正弦波 → DFT → 低通滤波 → 再 DFT 对比

fn generate_signal(sr: u32, dur: f32) -> Vec<f32> {
    let n = (sr as f32 * dur) as usize;
    (0..n).map(|i| {
        let t = i as f32 / sr as f32;
        // 440 Hz + 5000 Hz 混合
        (2.0 * std::f32::consts::PI * 440.0 * t).sin() * 0.6
        + (2.0 * std::f32::consts::PI * 5000.0 * t).sin() * 0.4
    }).collect()
}

fn dft(signal: &[f32]) -> Vec<f32> {
    let n = signal.len();
    (0..n/2).map(|k| {
        let mut re = 0.0_f32;
        let mut im = 0.0_f32;
        for (i, &x) in signal.iter().enumerate() {
            let angle = -2.0 * std::f32::consts::PI * k as f32 * i as f32 / n as f32;
            re += x * angle.cos();
            im += x * angle.sin();
        }
        (re * re + im * im).sqrt() * 2.0 / n as f32
    }).collect()
}

struct LowPass { alpha: f32, prev: f32 }
impl LowPass {
    fn new(alpha: f32) -> Self { Self { alpha, prev: 0.0 } }
    fn process(&mut self, x: f32) -> f32 {
        self.prev = self.alpha * x + (1.0 - self.alpha) * self.prev;
        self.prev
    }
}

fn main() {
    let sr = 44100;
    let signal = generate_signal(sr, 0.1);  // 100 ms
    println!("原始信号 {} 个样本", signal.len());

    let spectrum = dft(&signal);
    // 找峰值
    let (peak_bin, peak_mag) = spectrum.iter().enumerate()
        .skip(1)  // 跳过 DC
        .max_by(|a, b| a.1.partial_cmp(b.1).unwrap())
        .map(|(i, &m)| (i, m))
        .unwrap();
    let peak_freq = peak_bin as f32 * sr as f32 / signal.len() as f32;
    println!("原始峰值: bin {}, freq ≈ {} Hz, mag = {:.4}", peak_bin, peak_freq, peak_mag);

    // 低通滤波
    let mut lp = LowPass::new(0.05);
    let filtered: Vec<f32> = signal.iter().map(|&x| lp.process(x)).collect();

    let filtered_spectrum = dft(&filtered);
    let (peak_bin2, peak_mag2) = filtered_spectrum.iter().enumerate()
        .skip(1)
        .max_by(|a, b| a.1.partial_cmp(b.1).unwrap())
        .map(|(i, &m)| (i, m))
        .unwrap();
    let peak_freq2 = peak_bin2 as f32 * sr as f32 / filtered.len() as f32;
    println!("滤波后峰值: bin {}, freq ≈ {} Hz, mag = {:.4}", peak_bin2, peak_freq2, peak_mag2);
    // 预期:滤波后 5000 Hz 峰值大幅减小,440 Hz 保持
}
```

### 17.2 用 cpal 实时播放

```toml
[dependencies]
cpal = "0.15"
```

```rust
use cpal::traits::{StreamTrait, DeviceTrait, HostTrait};

fn main() {
    let host = cpal::default_host();
    let device = host.default_output_device().expect("无音频设备");
    let config = device.default_output_config().unwrap();
    let sr = config.sample_rate().0;
    let channels = config.channels() as usize;

    let mut phase = 0.0_f32;
    let stream = device.build_output_stream(
        &config.into(),
        move |data: &mut [f32], _: &cpal::OutputCallbackInfo| {
            for frame in data.chunks_mut(channels) {
                let v = phase.sin() * 0.3;
                phase += 2.0 * std::f32::consts::PI * 440.0 / sr as f32;
                if phase > 2.0 * std::f32::consts::PI {
                    phase -= 2.0 * std::f32::consts::PI;
                }
                for s in frame.iter_mut() {
                    *s = v;
                }
            }
        },
        |e| eprintln!("{}", e),
        None,
    ).unwrap();
    stream.play().unwrap();
    println!("播放 440 Hz,按 Ctrl+C 停止");
    std::thread::sleep(std::time::Duration::from_secs(3));
}
```

### 17.3 Arch 音频配置

```bash
# 检查音频服务
systemctl --user status pipewire pipewire-pulse wireplumber

# 看音频设备
aplay -l
arecord -l

# 测试播放
speaker-test -c 2 -t wav

# 录音测试(需要麦克风)
arecord -d 3 test.wav && aplay test.wav

# 调音量
alsamixer
# 或
pactl set-sink-volume @DEFAULT_SINK@ 50%

# 看实时音频频谱(需要 pulseaudio 或 pipewire-pulse)
# 装 sox 和_pulse 工具
sudo pacman -S sox pulseaudio pulseaudio-alsa
# 然后看实时频谱
pacat --record -d alsa_output.pci-0000_00_1b.0.analog-stereo.monitor |
  sox -t raw -r 44100 -e signed -b 16 -c 2 - -n stat
```

### 17.4 Troubleshooting

**问题1**:听到"咔咔"声而非正弦波。
原因:相位累加不正确(没 % 2π),或振幅太大 clipping。
解决:每步 `phase += 2π·f/sr`,振幅 ≤ 0.5(留余量)。

**问题2**:440 Hz 在 44100 Hz 听起来怪。
原因:可能 alias——确认频率 < Nyquist(22050)。440 < 22050 应该没事,看是不是别的 bug。

**问题3**:DFT 输出全是 0。
原因:可能信号长度太小,或 k=0 (DC) 占主导,看 magnitude / N 而非 magnitude。

**问题4**:FFT 报"N 不是 2 的幂"。
原因:Cooley-Tukey 要求 N = 2^k。
解决:截断或补零到下一个 2 的幂。

**问题5**:滤波后波形变形。
原因:IIR 不稳定(极点单位圆外),或 α 太极端。
解决:α 在 (0, 1) 之间,接近 1 = 几乎不过滤,接近 0 = 强过滤。

---

## 18 · 延伸阅读(可选补充,非必需)

本仓库本地资料:
- [20-math-foundation-extended.md](20-math-foundation-extended.md) — 数学基础,本篇用 Fourier
- [21-physics-foundation.md](21-physics-foundation.md) — 物理,振动是声波源
- [14-math-foundations.md](14-math-foundations.md) — 简化版数学

外部稳定 URL:
- The Scientist and Engineer's Guide to Digital Signal Processing(免费在线):https://www.dspguide.com/
- Stanford CCRMA DSP 书:https://ccrma.stanford.edu/~jos/
- Allen Downey 的 Think DSP(Python):https://greenteapress.com/wp/think-dsp/
- 3Blue1Brown Fourier 变换可视化:https://www.youtube.com/watch?v=spUNpyF58BY
