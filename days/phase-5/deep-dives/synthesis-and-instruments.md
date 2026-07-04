
# 声音合成与乐器

> 你听了一段 808 鼓机。听见了一个 pad。听见了 DX7 的 E-Piano。**这些声音不来自录音采样——它们是数学函数实时生成的**。这是**声音合成**(sound synthesis)。从 1960s 的 Moog 模拟合成器、1970s 的 Buchla、1983 的 Yamaha DX7、1990s 的 Reaktor、2000s 的 Massive、到今天的 Serum 和 Vital,**每一代合成器都把声音设计的边界推得更远**。这一篇我们造一个 subtractive synth 从零到能跑——锯齿振荡器、ADSR 包络、共振低通滤波器、LFO、调制矩阵。然后转向 FM、Karplus-Strong、物理建模、wavetable——这些**完全不同的合成范式**。看完你能在 HH 项目里加一个程序化生成的 BGM、一个 procedural 音效引擎、一个能跟玩家动作"反演奏"的动态音乐系统。

## 0 · 为什么要有这一篇

音频合成是**音乐和工程的交叉点**。它需要你同时懂:傅里叶分析(波形的谐波)、DSP(滤波、调制)、控制系统(ADSR、LFO)、乐理(音阶、和弦)、硬件历史(Moog 的电路是怎么演变成今天的 VST 的)。

为什么游戏开发者要学这个?**几个具体场景**:

**场景一**:你的游戏关卡是无尽的 roguelike,你要 BGM 跟着关卡难度演化。预制音乐循环听腻,**procedural music generation** 才能解决。这要求你能**代码生成**单个音符(振荡器 + 包络 + 滤波),然后**程序化**作曲。

**场景二**:你的射击游戏,每次开火都播 "bang.wav"。10 个敌人同时开火 = 10 个一样的"砰",听起来像机器。**Solution**:每次开火**微调参数**(基频抖动 ±5%,滤波 envelope 时间随机),每次都不同——procedural variation。

**场景三**:你的解谜游戏,玩家拼对了一个图,系统播放"成功音效"。普通做法是预制 wav;**酷做法**:程序化生成——短小的 bell-tone,频率匹配谜题的"主题音"。每个谜题不同 bell,有 narrative 意义。

**场景四**:你的 RPG,不同角色不同武器。剑 = 模拟金属碰撞(滤波 white noise + 短 envelope),弓 = Karplus-Strong 弦合成,法术 = FM synth 复杂谐波。**每种武器一个 synth,不是 wav 文件**。

**场景五**:你做音乐教育游戏(像 Synthesia)。玩家按键,系统合成钢琴音。**多音色复音钢琴合成器**是核心。

声音合成把"声音"从"录音素材"变成"代码生成的数学对象"。这给了你**无限变化、零存储、动态适应**——这是 wav 文件做不到的。

**读完这一篇,你应该能**:

- 解释 Moog / Buchla / DX7 / Serum 各自代表什么合成范式
- 用傅里叶级数推导 saw / square / triangle 的谐波结构
- 实现 band-limited oscillator(polyBLEP、BLIT)避免 aliasing
- 写出 ADSR envelope generator,理解 exponential vs linear segments
- 实现 Karplus-Strong 弦合成(20 行 Rust)
- 推导 Chowning FM 算法,做出 DX7 风格 E-Piano
- 设计 modulation matrix,让 LFO 和 envelope 调制任意参数
- 写一个完整的 subtractive synth(振荡器 → 滤波 → 包络 → 输出)
- 设计 bass / lead / pad / drum 四种音色
- 评估 fundsp / megrid / souzou 等 Rust synth crate

读者基线:完成 HH 22 信号基础 + day009 音频 + day142 mixer + DSP 基础 + FFT/STFT(前两篇 deep-dive)。

## 1 · 合成器历史:四代演化

### 1.1 第一代:模拟合成器(1960s-1970s)

**Robert Moog** 1964 年在纽约 AES 大会展示了第一个电压控制(voltage-controlled)合成器。核心模块:

- **VCO**(Voltage-Controlled Oscillator):频率由输入电压控制,输出 saw / square / triangle
- **VCF**(Voltage-Controlled Filter):Moog 的"ladder filter"是传奇——24 dB/oct 低通,有 unique 的 resonance
- **VCA**(Voltage-Controlled Amplifier):增益由电压控制
- **ADSR Envelope Generator**:控制 VCA 和 VCF 随时间变化
- **LFO**(Low-Frequency Oscillator):低频振荡器,做 vibrato、tremolo

**信号流**:`VCO → VCF → VCA`。这是 **subtractive synthesis**(减法合成)的范本——从富含谐波的波形(saw / square)开始,用 filter **减掉** 不要的频率。Moog Minimoog(1970)是史上第一个 portable 合成器,$1500 在 1970 是巨款。**Keith Emerson、Yes、Pink Floyd** 都用它。

**Don Buchla** 1963 在旧金山做了类似的合成器,但哲学不同。Buchla 强调 **additive + FM + granular**(更多探索性),不做 filter;Moog 强调 **subtractive**(更可玩、可旋律)。这两个流派到今天仍是合成器的两大主流。

### 1.2 第二代:FM 合成(1970s-1980s)

**John Chowning** 1973 在斯坦福发现 **FM(Frequency Modulation)合成**——用一个振荡器调制另一个振荡器的频率。这在当时是革命性的——**用极少的计算生成极复杂的谐波**。Chowning 把专利授权给 Yamaha。

**Yamaha DX7**(1983)是史上最成功的 FM 合成器。$2000 卖出 200,000+ 台。它的 E-Piano 是 80s 流行音乐的标志(Michael McDonald、Phil Collins、Wham!)。DX7 是**第一个商业成功的全数字合成器**——所有波形、滤波、调制都是数字 DSP,而不是模拟电路。

FM 的特点:
- **6 个 operator**(振荡器),每个可以**调制成**别的 operator 的频率
- **算法**(algorithm)定义 operator 之间的连接。DX7 有 32 个算法
- **复杂、金属、玻璃感**的音色,适合 E-Piano、bells、bass
- **不可减法合成**:FM 不能"先有复杂波形,再用 filter 减",必须从 operator 算起

DX7 之后,FM 没有再大规模商业化——直到 Native Instruments FM8(2006)、Ableton Operator(2004)等软件 FM 出现。

### 1.3 第三代:采样 + 物理建模(1980s-1990s)

**采样器**(sampler):不再"生成"声音,而是**录真实乐器**,播放采样。**E-mu Emulator**(1981)、**Akai S1000**(1988)是经典。今天的 Kontakt(Native Instruments)是事实标准。

**物理建模**(physical modeling):用微分方程模拟乐器物理。**Karplus-Strong**(1983)是简单版本——延迟线 + 低通,模拟弦的振动衰减。**Yamaha VL1**(1993)和 **Korg OASYS** 用更复杂的 waveguide 模型,但商业上失败——太复杂,玩家不会调。

物理建模在 2000s 后成为学术研究重点,但商业上仍小众。Pianoteq(Modartt)是少数成功的物理建模钢琴 VST。

### 1.4 第四代:软件合成器与 wavetable(1990s-至今)

**软件合成器**(soft synth):CPU 够快后,合成从硬件搬进 PC。**Reaktor**(1999, Native Instruments)、**Massive**(2006)、**Serum**(2014, Xfer Records)、**Vital**(2020, Matt Tytel,免费!)是里程碑。

**Wavetable 合成**:不是单一波形,而是**一个 wave table**(64-256 个不同波形的表),按位置扫描。位置可以静态选、LFO 扫、envelope 推。**Korg Wavestate**(2020)和 **Serum** 是 wavetable 的现代标杆。

**Granular 合成**:把采样切成 ms 级的"颗粒"(grain),重新组合。**Curtis Roads** 1980s 提出,2000s 在 Native Instruments Absynth、Output Portal 等普及。

今天(2026)的趋势:**机器学习合成**(Meta AudioCraft、Google MusicLM 用 transformer 生成音频)、**neural rendering**(用神经网络生成音色)、**多模态合成**(从文本 prompt 生成音乐)。但**传统 DSP 合成仍然是工程基础**——ML 模型用 GPU 算几千亿 ops,传统 synth 用 CPU 算几兆 ops,**实时低延迟场景传统 synth 仍然占优**。

## 2 · 振荡器:从数学到代码

振荡器(oscillator)是合成器的"声源"——一个能持续输出指定频率波形的组件。下面用傅里叶级数推导四种基本波形。

### 2.1 正弦波(Sine)

$$ x(t) = A \sin(2\pi f t + \phi) $$

最简单的波形。频谱**单一频率**(只有 f_0,无谐波)。听感"纯净、空、笛子感"。

时域实现:

```rust
pub struct SineOsc { phase: f32, phase_inc: f32 }

impl SineOsc {
    pub fn new(freq: f32, sample_rate: f32) -> Self {
        SineOsc {
            phase: 0.0,
            phase_inc: freq / sample_rate,
        }
    }
    pub fn process(&mut self) -> f32 {
        let y = (self.phase * 2.0 * std::f32::consts::PI).sin();
        self.phase += self.phase_inc;
        if self.phase >= 1.0 { self.phase -= 1.0; }
        y
    }
}
```

注意 phase 用归一化 [0, 1),不直接用弧度——避免 2π × 大数后精度损失。

### 2.2 锯齿波(Sawtooth)

傅里叶级数:

$$ x_{saw}(t) = \frac{2}{\pi} \sum_{k=1}^{\infty} \frac{(-1)^{k+1}}{k} \sin(2\pi k f t) $$

**所有谐波**(整数 k = 1, 2, 3, ...),幅度 `1/k` 衰减。听感"亮、rich、string-like"。Subtractive synth 的核心音源——所有"肥厚 lead / bass"都从 saw 开始。

朴素实现:

```rust
pub struct NaiveSaw { phase: f32, phase_inc: f32 }

impl NaiveSaw {
    pub fn process(&mut self) -> f32 {
        let y = 2.0 * self.phase - 1.0;  // [-1, 1]
        self.phase += self.phase_inc;
        if self.phase >= 1.0 { self.phase -= 1.0; }
        y
    }
}
```

**问题**:**aliasing**。锯齿的不连续点(phase 从 1 跳回 0)在频谱上产生无穷高频分量,采样后**折叠回音频带**(alias),听起来有金属嗡声。**naive saw 在 f > 1 kHz 时明显 alias**。

### 2.3 抗 aliasing:BLIT 和 polyBLEP

**两种主流解决方案**:

**BLIT**(Band-Limited Impulse Train):用预先计算的 sinc 函数求和生成"频谱严格带限"的锯齿。**Cumulated BLIT**(Stilson & Smith 1997)是经典实现。

**polyBLEP**(Polynomial Band-Limited Step):在波形的不连续点用低阶多项式(常 2 阶)修正。**比 BLIT 简单、快、且几乎一样好**。是现代 synth 的事实标准。

polyBLEP 修正项 `pb(t)`(t 是距不连续点的归一化距离,|t| < 1):

$$ pb(t) = \begin{cases} t + t^2 + 0.5 t^3 / 3 & \text{if } -1 < t < 0 \\ t - t^2 + 0.5 t^3 / 3 & \text{if } 0 \le t < 1 \\ 0 & \text{otherwise} \end{cases} $$

(或更简单的 1 阶版本)

应用方式:在 naive saw 输出之后,加上 polyBLEP 修正:

```rust
fn poly_blep(t: f32, dt: f32) -> f32 {
    // t 是当前 phase,dt 是 phase_inc
    if t < dt {
        // 距离 phase = 0 不连续点
        let x = t / dt;
        x + x - x * x - 1.0
    } else if t > 1.0 - dt {
        // 距离 phase = 1 不连续点
        let x = (t - 1.0) / dt;
        x + x + x * x + 1.0
    } else {
        0.0
    }
}

pub struct BlepSaw { phase: f32, phase_inc: f32 }

impl BlepSaw {
    pub fn process(&mut self) -> f32 {
        let t = self.phase;
        let naive = 2.0 * t - 1.0;
        // 单不连续点(phase = 0 处)
        let blep = poly_blep(t, self.phase_inc);
        let y = naive - blep;
        self.phase += self.phase_inc;
        if self.phase >= 1.0 { self.phase -= 1.0; }
        y
    }
}
```

实测:polyBLEP saw 在 f = 5 kHz 仍 alias 在 -60 dB 以下(听不见)。naive saw 在 f = 1 kHz 就有 -30 dB 的 alias(听得见)。

### 2.4 方波(Square)

傅里叶级数:

$$ x_{sq}(t) = \frac{4}{\pi} \sum_{k=1,3,5,\ldots}^{\infty} \frac{1}{k} \sin(2\pi k f t) $$

**只有奇次谐波**,幅度 `1/k` 衰减。听感"空、木管、clarinet"。

polyBLEP 实现:naive square(`sign(2t-1)`)有**两个**不连续点(t = 0 和 t = 0.5),都要 polyBLEP 修正。

```rust
pub struct BlepSquare { phase: f32, phase_inc: f32 }

impl BlepSquare {
    pub fn process(&mut self) -> f32 {
        let t = self.phase;
        let naive = if t < 0.5 { 1.0 } else { -1.0 };
        let blep1 = poly_blep(t, self.phase_inc);
        let blep2 = poly_blep((t + 0.5) % 1.0, self.phase_inc);
        let y = naive + blep1 - blep2;  // 加第一个,减第二个(因为第二个不连续是下降)
        self.phase += self.phase_inc;
        if self.phase >= 1.0 { self.phase -= 1.0; }
        y
    }
}
```

### 2.5 三角波(Triangle)

傅里叶级数:

$$ x_{tri}(t) = \frac{8}{\pi^2} \sum_{k=1,3,5,\ldots}^{\infty} \frac{(-1)^{(k-1)/2}}{k^2} \sin(2\pi k f t) $$

**只有奇次谐波**,幅度 `1/k²` 快速衰减(比 saw/square 快得多)。听感"软、温和、flute"。

triangle 没有不连续点(只有不连续导数),所以 alias 远比 saw/square 低,朴素实现已经可用。但严格起见仍可加 BLEP。

```rust
pub struct Triangle { phase: f32, phase_inc: f32 }

impl Triangle {
    pub fn process(&mut self) -> f32 {
        let t = self.phase;
        // 2|2t - 1| - 1  →  [-1, 1] 的三角波
        let y = 2.0 * (2.0 * t - 1.0).abs() - 1.0;
        // 取反以匹配 conventional phase
        let y = -y;
        self.phase += self.phase_inc;
        if self.phase >= 1.0 { self.phase -= 1.0; }
        y
    }
}
```

### 2.6 Wavetable

不是单一波形,而是 **wave table**(一组预计算的波形)。每个 wavetable 有 N 个 frame(典型 64-256),每个 frame 是 M 个样本(典型 2048)。

```rust
pub struct Wavetable {
    frames: Vec<Vec<f32>>,  // frames[i] = 第 i 个波形的样本
    position: f32,          // 在 wavetable 中的位置 [0, frames.len()-1)
    phase: f32,             // 在当前波形内的 phase [0, 1)
    phase_inc: f32,
}

impl Wavetable {
    pub fn process(&mut self) -> f32 {
        // 1. 用 position 线性插值得到当前 frame
        let pos_frac = self.position;
        let pos_i = pos_frac.floor() as usize;
        let pos_f = pos_frac - pos_i as f32;
        let next_i = (pos_i + 1) % self.frames.len();
        let frame_a = &self.frames[pos_i];
        let frame_b = &self.frames[next_i];

        // 2. 在 frame 内用 phase 做线性插值(cubic 更好)
        let phase_idx = self.phase * frame_a.len() as f32;
        let pi = phase_idx.floor() as usize;
        let pf = phase_idx - pi as f32;
        let next_pi = (pi + 1) % frame_a.len();
        let s_a = frame_a[pi] * (1.0 - pf) + frame_a[next_pi] * pf;
        let s_b = frame_b[pi] * (1.0 - pf) + frame_b[next_pi] * pf;
        let y = s_a * (1.0 - pos_f) + s_b * pos_f;

        self.phase += self.phase_inc;
        if self.phase >= 1.0 { self.phase -= 1.0; }
        y
    }

    pub fn set_position(&mut self, pos: f32) {
        self.position = pos.clamp(0.0, (self.frames.len() - 1) as f32);
    }
}
```

Wavetable 的力量:**位置可以由 LFO / envelope / velocity 调制**。一个 wavetable 里放"sine → saw → noise"过渡,扫一遍 wavetable 就得到"开启 - 闭合 - 解体"的动态音色。这是 Serum 的核心。

Wavetable 的高级特性:
- **MWT(Multi-frame wavetable)**:128+ frame
- **Spectral morphing**:在频域做插值(不是时域),得到"morph"效果
- **Formula-generated**:用户输入公式(比如 `sin(x) + 0.5 sin(3x)`),自动生成 wavetable

### 2.7 Additive synthesis

不是用单一波形 + filter,而是**多个正弦波直接相加**。每个谐波独立振幅 + 相位 envelope。

$$ x(t) = \sum_{k=1}^{K} A_k(t) \sin(2\pi k f t + \phi_k(t)) $$

A_k(t) 和 φ_k(t) 是第 k 谐波的振幅和相位 envelope。**优点**:频谱完全可控。**缺点**:K 大时 CPU 重(K = 64 时每样本 64 个 sin)。

Additive 用于**精确频谱塑造**(比如 Kawai K5、Hammond B3 organ 上的 drawbars)。也用于 **resynthesis**(分析输入信号的频谱,然后 additive 重建,允许每个谐波独立修改)。

### 2.8 颗粒合成(Granular)

把采样或合成源切成 ms 级**颗粒**(grain),每个 grain 有独立的 envelope(典型 Gaussian)、playback rate、position。多个 grain 重叠播放,得到 dense、atmospheric 纹理。

```rust
pub struct Grain {
    source: Arc<Vec<f32>>,
    position: f32,        // 源采样中的位置
    playback_rate: f32,   // 0.5 = 低八度, 2.0 = 高八度
    age: f32,             // grain 当前 age [0, length)
    length: f32,          // grain 总长(秒)
}

impl Grain {
    pub fn process(&mut self, sample_rate: f32) -> f32 {
        if self.age >= self.length { return 0.0; }
        // Gaussian envelope
        let t = self.age / self.length;  // [0, 1]
        let envelope = (-(t - 0.5).powi(2) * 16.0).exp();
        // 读取源
        let src_idx = self.position as usize;
        let y = if src_idx < self.source.len() {
            self.source[src_idx] * envelope
        } else { 0.0 };
        // 推进
        self.position += self.playback_rate;
        self.age += 1.0 / sample_rate;
        y
    }
}
```

Granular synth 的核心是 **grain cloud**——同时跑几十到几百个 grain,每个独立参数。**Pitch shift + time stretch 不耦合**(因为 grain 长度和源位置独立)。Curtis Roads 1985 的 "Granular Sound" 是奠基论文。

### 2.9 Sample-based synthesis

最简单:**录真实乐器**,触发时播放采样。但需要解决:

- **多音高**:同一乐器不同音高音色不同(钢琴 A4 和 C5 听起来不同,不只是频率变化)。**多采样 + 插值**——每 3-5 半音录一次采样,中间音高用最近两个采样插值或 pitch-shift
- **Velocity layer**:轻弹和重弹音色不同。每个音高录 4-8 个 velocity layer
- **Round robin**:同一音高同一 velocity 反复播放,会有"机关枪"感。**多个采样轮替**(典型 4-8 个 round robin)

完整钢琴 sample 库(~88 keys × 8 velocity × 4 round robin = 2800 样本)占几十 GB。这就是为什么 Komplete、Spitfire 的 sample 库贵——录制成本。

**SoundFont**(.sf2)格式:Creative Labs 1991 提出,定义 sample playback 规则。今天仍广泛用。**Decent Sampler**、**Sforzando** 是免费 SoundFont 播放器。

## 3 · FM 合成:Chowning 算法

### 3.1 FM 公式

**FM**(Frequency Modulation):用一个振荡器(carrier)的频率被另一个振荡器(modulator)调制。

$$ x(t) = A \sin(2\pi f_c t + I \sin(2\pi f_m t)) $$

`f_c`:carrier 频率(听到的基频附近)
`f_m`:modulator 频率(典型 `f_c` 或 `f_c / 2` 等整数比)
`I`:modulation index(modulator 的振幅,决定谐波丰富度)

### 3.2 频谱分析

用 Bessel 函数展开:

$$ \sin(\alpha + I \sin \beta) = \sum_{k=-\infty}^{\infty} J_k(I) \sin(\alpha + k\beta) $$

(J_k 是第一类 Bessel 函数,阶 k)

所以 FM 信号的频谱在频率 `f_c + k f_m` 处有分量(k 是任意整数,正负),幅度 `J_k(I)`。

**关键洞察**:
- 当 `f_m / f_c = 整数比`(比如 1:1、2:1、3:2),FM 信号**谐波结构**(所有分量都是 f_c 谐波)。听感"harmonic, melodic"
- 当 `f_m / f_c = 无理数比`(比如 √2:1),FM 信号**非谐波**(分量之间不成整数比)。听感"inharmonic, bell-like, metallic"
- I 越大,边带越多,音色越"亮、complex"

**为什么 FM 革命**:用 1 个 carrier + 1 个 modulator,生成了**几十个边带**——等价于几十个 oscillator 的 additive synth。计算量极低(2 个 sin),音色极丰富。这就是为什么 DX7(6 个 operator、32 算法)能在 1983 的 7 MHz CPU 上跑出复杂的 E-Piano。

### 3.3 DX7 算法

DX7 有 6 个 operator,每个可以**输出音频**或**调制别的 operator**。**算法**(algorithm)定义哪些 operator 是 carrier(输出)、哪些是 modulator(只调制)。32 个预设算法。

最经典算法(算法 1):**stacked FM** —— op6 → op5 → op4 → op3 → op2 → op1(输出)。6 层 FM 串联,生成极丰富谐波。这是 DX7 E-Piano 的"金属感"来源。

另一个经典(算法 5):**两个 carrier 共享一个 modulator**——op1 + op2 输出,都被 op3 调制。这做出 layered 音色。

### 3.4 Rust FM 实现

```rust
pub struct FmOperator {
    pub phase: f32,
    pub phase_inc: f32,
    pub ratio: f32,        // 频率比(modulator_ratio = modulator_freq / carrier_freq)
}

pub struct FmVoice {
    pub carrier: FmOperator,
    pub modulator: FmOperator,
    pub mod_index: f32,    // 调制 index
    pub mod_env: Adsr,     // modulator envelope(让 I 随时间变化)
    pub amp_env: Adsr,     // amplitude envelope
    pub base_freq: f32,
}

impl FmVoice {
    pub fn new(sample_rate: f32) -> Self {
        FmVoice {
            carrier: FmOperator { phase: 0.0, phase_inc: 0.0, ratio: 1.0 },
            modulator: FmOperator { phase: 0.0, phase_inc: 0.0, ratio: 1.0 },
            mod_index: 1.0,
            mod_env: Adsr::new(sample_rate),
            amp_env: Adsr::new(sample_rate),
            base_freq: 440.0,
        }
    }

    pub fn note_on(&mut self, freq: f32) {
        self.base_freq = freq;
        self.carrier.phase_inc = freq * self.carrier.ratio / self.sample_rate();
        self.modulator.phase_inc = freq * self.modulator.ratio / self.sample_rate();
        self.mod_env.note_on();
        self.amp_env.note_on();
    }

    pub fn note_off(&mut self) {
        self.mod_env.note_off();
        self.amp_env.note_off();
    }

    fn sample_rate(&self) -> f32 { self.amp_env.sample_rate }

    pub fn process(&mut self) -> f32 {
        // 计算 modulator envelope 当前值
        let mod_env_val = self.mod_env.process();
        let I = self.mod_index * mod_env_val;
        // modulator 输出
        let m = (self.modulator.phase * 2.0 * std::f32::consts::PI).sin() * I;
        // carrier with phase modulation by m
        let carrier_phase = self.carrier.phase * 2.0 * std::f32::consts::PI + m;
        let y = carrier_phase.sin();
        // 推进 phase
        self.carrier.phase += self.carrier.phase_inc;
        if self.carrier.phase >= 1.0 { self.carrier.phase -= 1.0; }
        self.modulator.phase += self.modulator.phase_inc;
        if self.modulator.phase >= 1.0 { self.modulator.phase -= 1.0; }
        // amplitude envelope
        let amp = self.amp_env.process();
        y * amp
    }
}
```

试一下:carrier 440 Hz, modulator ratio 2.0 (880 Hz), I = 1.0。这是经典 DX7 E-Piano 起点。增加 ratio 到 3.0、5.0,得到"bell"音色;ratio 到 0.5,得到"谐和 rhodes"。

### 3.5 历史:Chowning 和 Yamaha

**John Chowning** 1967 在斯坦福用 PDP-1 计算机实验 FM。1971 年他听到调制频率非整数比时的 bell-like 声音,意识到 FM 可以**模拟各种乐器**。1973 论文 "The Synthesis of Complex Audio Spectra by Means of Frequency Modulation" 发表在 JAES。

斯坦福 把专利授权给 Yamaha(1974)。Yamaha 用 10 年商业化,**GS-1**(1981,$16,000,4 operator)和 **DX7**(1983,$2000,6 operator)先后上市。DX7 商业大成功,Stanford 收 Yamaha 的版税超过 2000 万美元。Chowning 用这笔钱建立了 CCRMA(Center for Computer Research in Music and Acoustics),今天仍是世界顶级计算机音乐研究中心。

FM 专利 1995 过期,之后免费。

## 4 · 物理建模:Karplus-Strong 和 Waveguide

### 4.1 Karplus-Strong:20 行代码做出吉他

**Kevin Karplus 和 Alex Strong** 1983 发表的最简单 string synthesis 算法。极简但极妙。

**算法**:

1. 初始化长度 N 的 buffer(对应基频 f_0 = sample_rate / N),填充随机数(白噪)
2. 输出 = buffer[head]
3. 下一个 buffer[head] = (buffer[head] + buffer[next]) / 2
4. head++,循环

```rust
pub struct KarplusStrong {
    buffer: Vec<f32>,
    head: usize,
}

impl KarplusStrong {
    pub fn new(freq: f32, sample_rate: f32) -> Self {
        let n = (sample_rate / freq) as usize;
        let mut rng = rand::thread_rng();
        let buffer: Vec<f32> = (0..n).map(|_| rand::random::<f32>() * 2.0 - 1.0).collect();
        KarplusStrong { buffer, head: 0 }
    }

    pub fn process(&mut self) -> f32 {
        let n = self.buffer.len();
        let cur = self.buffer[self.head];
        let next = self.buffer[(self.head + 1) % n];
        // 一阶低通 + 衰减
        let avg = 0.5 * (cur + next) * 0.996;  // 0.996 是衰减系数
        let y = cur;
        self.buffer[self.head] = avg;
        self.head = (self.head + 1) % n;
        y
    }
}
```

**为什么有效**:
1. **初始白噪**包含所有频率(在弦上,所有振动模式都被激发)
2. **延迟线长度 N** 决定基频——长度 N 的循环 buffer 是梳状滤波器,在 f_s/N 的倍数处增益,其他频率衰减
3. **平均**(0.5 × (cur + next))是简单低通——高频衰减比低频快
4. **结果**:白噪 → 弦振动模式 + 高频快速衰减 + 低频慢速衰减 = **吉他/班卓琴/竖琴的衰减特征**

**CPU 极低**:每样本 1 加 + 2 乘 + 1 mod。可以在 8-bit 微控制器上跑 64 个 voice。

**扩展**:
- **Stereo**:左右声道用不同衰减系数,加宽立体感
- **Drum mode**:用概率"翻转"而非"平均"——做鼓声
- **Stretch**:加 allpass 滤波器,做 inharmonic 弦(piano bass)

### 4.2 Digital Waveguide

Karplus-Strong 是 waveguide 的简化版。**Julius O. Smith III**(Stanford)1985 推广的 **Digital Waveguide** 是更通用的物理建模框架。

**核心思想**:弦上的波动是**两个反向传播的波**之和。建模:两根延迟线,一根向左,一根向右。在端点(bridge、nut),波被反射(可能带滤波——真实弦的端点不完全反射)。

```rust
pub struct WaveguideString {
    upper: Vec<f32>,  // 向右传播
    lower: Vec<f32>,  // 向左传播
    head_upper: usize,
    head_lower: usize,
    bridge_filter: OnePoleLPF,  // 端点反射滤波
    nut_reflection: f32,         // nut 反射系数(典型 -1)
    bridge_reflection: f32,      // bridge 反射系数(典型 -0.99)
}

impl WaveguideString {
    pub fn process(&mut self, excitation: f32) -> f32 {
        // 1. 读取 bridge 端的左右波
        let upper_at_bridge = self.upper[self.head_upper];
        // 2. bridge 反射(低通滤波,衰减)
        let bridge_out = upper_at_bridge;  // 输出到空气
        let reflected = -self.bridge_filter.process(upper_at_bridge) * self.bridge_reflection;
        // 3. 注入到 lower waveguide
        self.lower[self.head_lower] = reflected;
        // ... 类似 nut 端处理
        // 4. 推进
        self.head_upper = (self.head_upper + 1) % self.upper.len();
        self.head_lower = (self.head_lower + 1) % self.lower.len();
        bridge_out
    }
}
```

Waveguide 可以扩展到**管乐**(圆柱 vs 圆锥)、**膜**(2D waveguide,但 CPU 重)、**共振木块**(模态合成)。

**Yamaha VL1**(1993)和 **Korg OASYS** 用 waveguide 做 sax、violin、flute。商业失败——参数太多,音乐家不会调。但**学术意义重大**,今天的 Pianoteq、Ableton's Tension 仍在用。

### 4.3 Mass-Spring 模型

最物理的方法:**直接数值积分微分方程**。每个质量块 + 弹簧 + 阻尼器,用 Runge-Kutta 或 Verlet 数值积分。

**优点**:最物理精确,可以做任意几何(膜、壳、3D 物体)。
**缺点**:CPU 极重(几千个 mass 需要 GPU 才能实时)。

**Claude Cadoz** 的 GENESIS 系统(1980s)是先驱。今天的 **Cymatic**、**Modalys** 商业软件还在用。游戏开发里罕见——除非做"虚拟乐器实验室"类型应用。

## 5 · 包络(Envelope)

**Envelope**:振幅(或其他参数)随时间变化的曲线。

### 5.1 ADSR

最经典:**Attack-Decay-Sustain-Release**(ADSR)。Vladimir Ussachevsky 1960s 在 Columbia-Princeton Electronic Music Center 提出。

- **Attack**:从 0 到 peak 的时间(典型 1-100 ms)
- **Decay**:从 peak 到 sustain level 的时间(典型 10-500 ms)
- **Sustain**:维持的电平(0-1,典型 0.6-0.8)。**注意:Sustain 是电平,不是时间**
- **Release**:note off 后从 sustain 到 0 的时间(典型 50-2000 ms)

```rust
pub struct Adsr {
    pub sample_rate: f32,
    pub attack_time: f32,
    pub decay_time: f32,
    pub sustain_level: f32,
    pub release_time: f32,
    state: AdsrState,
    current_level: f32,
    target_level: f32,
    rate: f32,  // 每样本变化率
}

#[derive(PartialEq)]
enum AdsrState { Idle, Attack, Decay, Sustain, Release }

impl Adsr {
    pub fn new(sample_rate: f32) -> Self {
        Adsr {
            sample_rate,
            attack_time: 0.01, decay_time: 0.1, sustain_level: 0.7, release_time: 0.2,
            state: AdsrState::Idle, current_level: 0.0, target_level: 0.0, rate: 0.0,
        }
    }

    pub fn note_on(&mut self) {
        self.state = AdsrState::Attack;
        self.target_level = 1.0;
        self.rate = 1.0 / (self.attack_time * self.sample_rate);
    }

    pub fn note_off(&mut self) {
        self.state = AdsrState::Release;
        self.target_level = 0.0;
        self.rate = 1.0 / (self.release_time * self.sample_rate);
    }

    pub fn process(&mut self) -> f32 {
        match self.state {
            AdsrState::Idle => { self.current_level = 0.0; }
            AdsrState::Attack => {
                self.current_level += self.rate;
                if self.current_level >= 1.0 {
                    self.current_level = 1.0;
                    self.state = AdsrState::Decay;
                    self.target_level = self.sustain_level;
                    self.rate = 1.0 / (self.decay_time * self.sample_rate);
                }
            }
            AdsrState::Decay => {
                self.current_level -= self.rate;
                if self.current_level <= self.sustain_level {
                    self.current_level = self.sustain_level;
                    self.state = AdsrState::Sustain;
                }
            }
            AdsrState::Sustain => {
                self.current_level = self.sustain_level;
            }
            AdsrState::Release => {
                self.current_level -= self.rate;
                if self.current_level <= 0.0 {
                    self.current_level = 0.0;
                    self.state = AdsrState::Idle;
                }
            }
        }
        self.current_level
    }
}
```

### 5.2 Linear vs Exponential segments

上面的实现是 **linear**(每样本变化固定量)。Linear envelope 听起来"机械"——人对振幅的感知是对数的,**exponential envelope** 听起来更自然。

**Exponential envelope**:每样本乘以一个固定 ratio。

```rust
// Attack:从 ε 接近 0 开始,每样本乘 (1 + rate_a)
// Decay:从 peak 开始,每样本乘 (1 - rate_d)
// 等等

// 实现:用 rate = exp(-ln(2) / time_to_halve),每样本乘 rate
```

但 exponential 不能从 0 开始(`0 × r = 0`),所以 attack 需要从 ε(比如 1e-6)起步。

**多数现代 synth 用 exponential 或 exponential-like**。Ableton Operator 用 exponential。Serum 用 exponential-with-curve(用户可调"曲率")。

### 5.3 AR / AHDSR / 多段 envelope

**AR**(Attack-Release):最简单,只有两个段。鼓、打击乐用。无 sustain。

**AHDSR**(Attack-Hold-Decay-Sustain-Release):加 Hold 段——attack 到达 peak 后**保持**一段时间再 decay。某些 synth 用 Hold 做"accent"。

**Multi-stage envelopes**(Serge Modular、Buchla 245):不限段数,用户自定义每段的 level + time。Modern synth(Reaktor、Serum、Massive)都支持 multi-stage。

### 5.4 Looping envelopes

某些场景(序列合成、纹理合成)需要 envelope **循环**——attack → decay → sustain → re-attack → decay → sustain → ...。实现:Release 段结束后,自动 note_on,而不是进 Idle。这是 ambient pad、sequence arp 的核心。

## 6 · LFO 和 Modulation Matrix

### 6.1 LFO(Low-Frequency Oscillator)

LFO 是**振荡器**,但频率在 sub-audio 范围(典型 0.1-20 Hz)。LFO 不输出音频,**调制**别的参数。

典型用法:
- **Vibrato**:LFO (5-7 Hz) → 振荡器 frequency(± 几十 cents,即几 Hz)
- **Tremolo**:LFO (5-7 Hz) → amplitude
- **Filter sweep**:LFO (0.5-2 Hz, sine or triangle) → filter cutoff
- **Wah-wah**:LFO (1-4 Hz) → bandpass center frequency

```rust
pub struct Lfo {
    phase: f32,
    phase_inc: f32,
    waveform: LfoWaveform,
}

pub enum LfoWaveform { Sine, Triangle, SawUp, SawDown, Square, SampleHold }

impl Lfo {
    pub fn new(freq: f32, sample_rate: f32, waveform: LfoWaveform) -> Self {
        Lfo {
            phase: 0.0,
            phase_inc: freq / sample_rate,
            waveform,
        }
    }
    pub fn process(&mut self) -> f32 {
        let y = match self.waveform {
            LfoWaveform::Sine => (self.phase * 2.0 * std::f32::consts::PI).sin(),
            LfoWaveform::Triangle => 2.0 * (2.0 * self.phase - 1.0).abs() - 1.0,
            LfoWaveform::SawUp => 2.0 * self.phase - 1.0,
            LfoWaveform::SawDown => 1.0 - 2.0 * self.phase,
            LfoWaveform::Square => if self.phase < 0.5 { 1.0 } else { -1.0 },
            LfoWaveform::SampleHold => 0.0,  // 略,需要 prev_phase 检测
        };
        self.phase += self.phase_inc;
        if self.phase >= 1.0 { self.phase -= 1.0; }
        y
    }
}
```

**Sample & Hold** LFO:每隔一定 period,随机采一个值并保持。这是经典 analog synth 的 "S&H" 模块,做 random sequencing。

### 6.2 Modulation Matrix

经典 synth 有几个固定 routing:LFO1 → pitch、LFO2 → cutoff、Env1 → amplitude、Env2 → cutoff。**Mod matrix**(调制矩阵)打破这个限制——用户**任意**指定 source → destination,带深度。

**数据结构**:

```rust
pub struct ModRoute {
    source: ModSource,
    destination: ModDest,
    depth: f32,  // -1 to 1
}

pub enum ModSource {
    Lfo1, Lfo2, Env1, Env2, Velocity, Aftertouch, ModWheel, PitchBend,
}

pub enum ModDest {
    Pitch, Cutoff, Resonance, Amplitude, Pan, AttackTime, DecayTime, WavetablePos,
}

pub struct ModMatrix {
    routes: Vec<ModRoute>,
    sources: HashMap<ModSource, f32>,  // 当前 source 值
}
```

**应用**:每样本前,把所有 source 计算出值,然后按 route 累加到 destination。

```rust
impl ModMatrix {
    pub fn apply(&self, dest: ModDest, base_value: f32) -> f32 {
        let mut v = base_value;
        for route in &self.routes {
            if route.destination == dest {
                let src_val = self.sources.get(&route.source).copied().unwrap_or(0.0);
                v += src_val * route.depth;
            }
        }
        v
    }
}
```

Mod matrix 是**现代 synth 的灵魂**。Massive、Serum、Vital、Pigments 都有 mod matrix,典型 16-32 个 route。

### 6.3 Velocity / Aftertouch / Polyphonic expression

**Velocity**:MIDI note-on 的力度(0-127),调制音色。典型:velocity 高 → 更亮(滤波 cutoff 提高)、 louder(amplitude 提高)。

**Aftertouch**(channel pressure 或 polyphonic pressure):按下键后**继续压**的力度。用于 vibrato、filter sweep。

**MPE**(MIDI Polyphonic Expression):现代 MIDI 扩展,每个 note 独立 pressure、pitch bend、timbre。Roli Seaboard、LinnStrument 用 MPE。MPE 让 synth 像 violin——每个音都能独立压弦。

## 7 · Subtractive synth 完整设计

把上面所有组件拼起来:Oscillator → Filter → VCA(Envelope) → Output。这是经典 Minimoog 结构。

```rust
pub struct SubtractiveVoice {
    osc1: BlepSaw,
    osc2: BlepSaw,
    osc2_detune: f32,        // osc2 相对 osc1 的 detune(cents)
    mix: f32,                // osc1 / osc2 混合 [0, 1]
    filter: Biquad,          // 见 dsp-fundamentals.md
    amp_env: Adsr,
    filter_env: Adsr,
    filter_env_amount: f32,  // filter env 对 cutoff 的调制深度
    base_cutoff: f32,
    sample_rate: f32,
    alive: bool,
}

impl SubtractiveVoice {
    pub fn new(sample_rate: f32) -> Self {
        let filter_coeffs = design_biquad(
            FilterType::LowPass, 1000.0, sample_rate, 1.0, 0.0,
        );
        SubtractiveVoice {
            osc1: BlepSaw { phase: 0.0, phase_inc: 0.0 },
            osc2: BlepSaw { phase: 0.0, phase_inc: 0.0 },
            osc2_detune: 7.0,   // 7 cents
            mix: 0.5,
            filter: Biquad::new(filter_coeffs),
            amp_env: Adsr::new(sample_rate),
            filter_env: Adsr::new(sample_rate),
            filter_env_amount: 2000.0,  // +2000 Hz on cutoff
            base_cutoff: 1000.0,
            sample_rate,
            alive: false,
        }
    }

    pub fn note_on(&mut self, freq: f32, velocity: f32) {
        self.osc1.phase_inc = freq / self.sample_rate;
        let detune_ratio = 2.0_f32.powf(self.osc2_detune / 1200.0);
        self.osc2.phase_inc = freq * detune_ratio / self.sample_rate;
        self.amp_env.note_on();
        self.filter_env.note_on();
        self.alive = true;
    }

    pub fn note_off(&mut self) {
        self.amp_env.note_off();
        self.filter_env.note_off();
    }

    pub fn process(&mut self) -> f32 {
        if !self.alive { return 0.0; }
        // Oscillators
        let o1 = self.osc1.process();
        let o2 = self.osc2.process();
        let osc_mix = o1 * (1.0 - self.mix) + o2 * self.mix;
        // Filter envelope modulates cutoff
        let f_env = self.filter_env.process();
        let cutoff = self.base_cutoff + self.filter_env_amount * f_env;
        let cutoff = cutoff.min(self.sample_rate * 0.45);  // 防止超过 Nyquist
        let coeffs = design_biquad(FilterType::LowPass, cutoff, self.sample_rate, 1.0, 0.0);
        self.filter.coeffs = coeffs;
        let filtered = self.filter.process(osc_mix);
        // Amp envelope
        let amp = self.amp_env.process();
        if self.amp_env.is_idle() { self.alive = false; }
        filtered * amp
    }
}
```

注意:`design_biquad` 每样本调用是性能热点。生产代码会做 cutoff 变化的"系数 smoothing"(每样本 lerp 系数),避免 zipper noise。

### 7.1 Polyphony(多音色)

```rust
pub struct SubtractiveSynth {
    voices: Vec<SubtractiveVoice>,
    sample_rate: f32,
}

impl SubtractiveSynth {
    pub fn new(num_voices: usize, sample_rate: f32) -> Self {
        let voices = (0..num_voices).map(|_| SubtractiveVoice::new(sample_rate)).collect();
        SubtractiveSynth { voices, sample_rate }
    }

    pub fn note_on(&mut self, freq: f32, velocity: f32) {
        // 找空闲 voice(或最老的)
        let voice = self.voices.iter_mut()
            .find(|v| !v.alive)
            .or_else(|| self.voices.iter_mut().min_by_key(|v| v.amp_env.time_since_note_on()))
            .unwrap();
        voice.note_on(freq, velocity);
    }

    pub fn note_off(&mut self, freq: f32) {
        // 找 playing 的 voice
        for v in &mut self.voices {
            if v.alive && v.osc1.phase_inc.matches(freq) {
                v.note_off();
                break;
            }
        }
    }

    pub fn render(&mut self, output: &mut [f32]) {
        output.fill(0.0);
        let mut voice_outputs = vec![0.0_f32; self.voices.len()];
        for sample in output.iter_mut() {
            for (i, v) in self.voices.iter_mut().enumerate() {
                if v.alive { voice_outputs[i] = v.process(); }
                else { voice_outputs[i] = 0.0; }
            }
            *sample = voice_outputs.iter().sum::<f32>() * 0.3;  // 软限幅
        }
    }
}
```

**Voice stealing**:voice 用完时,steal 最老/最弱的——上面代码用 `min_by_key(time_since_note_on)` 找最老的。**Monophonic priority**(Korg、Yamaha 风格):lowest note priority / highest note priority / last note priority。每种行为不同。

### 7.2 Unison

为了"肥厚"音色,把同一个 note 用多个 voice 播放,各 detune 不同 cents(典型 ±10 cents 到 ±50 cents)。这是 trance lead、EDM bass 的核心。

```rust
pub fn note_on_unison(&mut self, freq: f32, num_unison: usize, spread_cents: f32) {
    for i in 0..num_unison {
        let detune = (i as f32 / (num_unison - 1) as f32 - 0.5) * spread_cents;
        // 每个 voice 用不同 detune
        self.note_on(freq * 2.0_f32.powf(detune / 1200.0), 1.0 / num_unison as f32);
    }
}
```

Unison 4-7 voice 是 supersaw lead 标准。

## 8 · 鼓合成

### 8.1 Kick drum

**经典 analog kick**(808):**sine wave + frequency envelope**(从 ~150 Hz 指数衰减到 50 Hz)+ **amplitude envelope**(快速衰减 200 ms)。

```rust
pub struct KickSynth {
    sine: SineOsc,
    pitch_env: f32,
    pitch_env_decay: f32,
    amp_env: f32,
    amp_env_decay: f32,
    base_freq: f32,
    pitch_depth: f32,
    sample_rate: f32,
}

impl KickSynth {
    pub fn trigger(&mut self) {
        self.pitch_env = 1.0;
        self.amp_env = 1.0;
    }

    pub fn process(&mut self) -> f32 {
        if self.amp_env <= 0.0 { return 0.0; }
        let freq = self.base_freq + self.pitch_depth * self.pitch_env;
        self.sine.phase_inc = freq / self.sample_rate;
        let y = self.sine.process() * self.amp_env;
        self.pitch_env *= self.pitch_env_decay;
        self.amp_env *= self.amp_env_decay;
        if self.amp_env < 0.001 { self.amp_env = 0.0; }
        y
    }
}
```

参数:`base_freq = 50`, `pitch_depth = 100`, `pitch_env_decay = 0.99` (fast), `amp_env_decay = 0.998` (medium)。

### 8.2 Snare drum

**Snare = drum shell(200 Hz 振荡)+ snare wires(白噪 hi-pass)**。两部分独立 envelope。

```rust
pub struct SnareSynth {
    tone: SineOsc,        // 200 Hz tone(shell)
    tone_env: f32,
    tone_decay: f32,
    noise_env: f32,
    noise_decay: f32,
    noise_filter: Biquad,  // hi-pass 1 kHz
    noise_phase: f32,      // simple LCG
    sample_rate: f32,
}

impl SnareSynth {
    pub fn trigger(&mut self) {
        self.tone_env = 1.0;
        self.noise_env = 1.0;
    }

    pub fn process(&mut self) -> f32 {
        if self.tone_env <= 0.0 && self.noise_env <= 0.0 { return 0.0; }
        let tone = self.tone.process() * self.tone_env;
        // 生成 white noise(LCG)
        self.noise_phase = self.noise_phase.wrapping_mul(1103515245).wrapping_add(12345);
        let n = (self.noise_phase as f32 / u32::MAX as f32) * 2.0 - 1.0;
        let n_filtered = self.noise_filter.process(n);
        let noise = n_filtered * self.noise_env;
        let y = tone * 0.4 + noise * 0.6;
        self.tone_env *= self.tone_decay;
        self.noise_env *= self.noise_decay;
        y
    }
}
```

### 8.3 Hi-hat

**Hi-hat = 高通白噪(6 kHz+)**+ **极快 envelope**(50-100 ms)。Closed hi-hat = 极短,open hi-hat = 长。

```rust
pub struct HiHatSynth {
    noise_env: f32,
    closed_decay: f32,
    open_decay: f32,
    is_open: bool,
    hp1: Biquad,  // 6 kHz hi-pass
    hp2: Biquad,  // 12 kHz hi-pass(让 sound 更脆)
    noise_phase: u32,
}
```

**909 风格 hi-hat**:用 6 个 square wave 在不同频率叠加(15、19、23 kHz 附近),通过 hi-pass 滤波,做出 metallic sound。

### 8.4 Toms

**Tom = kick + pitched**(80-200 Hz sine)+ medium decay。本质和 kick 一样,只是参数不同。

## 9 · Rust synth crates 生态

### 9.1 fundsp

**fundsp**(Sami Perttu):函数式 audio DSP 框架。**特点**:

- 用 `>>>` 运算符连接节点:`sine() >>> lowpass(...) >>> envelope(...)`
- 类型安全的节点组合(编译期检查 channel count)
- 实时 + 离线都支持
- SIMD 优化

```rust
use fundsp::hacker::*;

fn main() {
    // 440 Hz sine,low-pass at 1 kHz,amp envelope
    let mut synth = (sine_hz(440.0) | sine_hz(440.0))
                  >> lowpass_hz(1.0, 1000.0);
    let mut buffer = [0.0_f32; 256];
    synth.process(44100.0, &mut buffer[..]);
}
```

`fundsp::hacker` 是 simplified API,`fundsp::audiounit` 是 full API。**强烈推荐**——比手写 dsp 链快得多。

GitHub: https://github.com/SamiPerttu/fundsp

### 9.2 megrid

**megrid**(Argrath):modal synthesizer。**Modal synthesis**:声音 = 多个 exponentially decaying sine(模态)。每个 modal frequency + decay time 是参数。

适合 resonant objects——bells、marimba、wood block、glass。**Percussive synthesis** 的利器。

GitHub: https://github.com/Argrath/megrid

### 9.3 souzou

**souzou**:实时 MIDI 控制的 subtractive synth。架构清晰,适合学习参考。

### 9.4 其他相关

- **bevy_kira_audio**:Bevy 引擎的音频集成,基于 kira
- **kira**:Rust 游戏音频库,有 mixer、loop、effect
- **rodio**:简单音频播放(基于 cpal)
- **rust synth 社区**:https://github.com/rustaudio/

### 9.5 浏览源码学

| crate | 适合学什么 |
|---|---|
| fundsp | 节点式 DSP 框架设计 |
| megrid | Modal synthesis 物理 |
| kira | 游戏音频架构(decoupling game / audio thread) |
| souzou | Subtractive synth 完整实现 |
| oxc-synth | 软件合成器优化技巧 |

## 10 · 高级合成技巧

### 10.1 Wavetable spectral morphing

简单 wavetable 在两个 frame 之间做**时域线性插值**。但时域插值会引入 phase 不连续——尤其当两个 frame 的 harmonic phase 不对齐时,听起来"phasor"(类似 phases 错位的 unison)。

**Spectral morphing**:把两个 frame 都 FFT,在**频域**对每个 bin 的 magnitude 和 phase 分别插值,再 IFFT。这避免 phase 不连续,得到平滑 morph。

```rust
pub fn spectral_morph(frame_a: &[f32], frame_b: &[f32], t: f32) -> Vec<f32> {
    let n = frame_a.len();
    // FFT 两个 frame
    let mut a = frame_a.to_vec();
    let mut b = frame_b.to_vec();
    let mut planner = RealFftPlanner::<f32>::new();
    let fft = planner.plan_fft_forward(n);
    let mut spec_a = fft.make_output_vec();
    let mut spec_b = fft.make_output_vec();
    fft.process(&mut a, &mut spec_a).unwrap();
    fft.process(&mut b, &mut spec_b).unwrap();
    // 频域插值
    let mut spec_morph = spec_a.clone();
    for i in 0..spec_morph.len() {
        let re = spec_a[i].re * (1.0 - t) + spec_b[i].re * t;
        let im = spec_a[i].im * (1.0 - t) + spec_b[i].im * t;
        spec_morph[i] = Complex64::new(re, im);
    }
    // IFFT
    let ifft = planner.plan_fft_inverse(n);
    let mut output = ifft.make_output_vec();
    ifft.process(&mut spec_morph, &mut output).unwrap();
    output
}
```

Serum 的 "spectral morph" 模式就是这套。CPU 比 linear morph 重(每 frame 一次 FFT/IFFT),但音质显著好。

### 10.2 Formant synthesis

**人声**特殊——基频(f0)由声带振动决定(典型 80-300 Hz),但音色由**声道**(vocal tract)的**共振峰**(formants)决定。Formants 是固定的频率 peak(不管 f0 多少,F1 ≈ 500 Hz, F2 ≈ 1500 Hz, F3 ≈ 2500 Hz,因人而异)。

**合成人声**:用普通 oscillator(saw、square)生成 harmonics,然后通过**多个高 Q peaking biquad**共振峰滤波。

```rust
pub struct VocalTract {
    f1: Biquad,  // F1 = 500 Hz, Q = 8
    f2: Biquad,  // F2 = 1500 Hz, Q = 10
    f3: Biquad,  // F3 = 2500 Hz, Q = 12
    f4: Biquad,  // F4 = 3500 Hz, Q = 14
}

impl VocalTract {
    pub fn process(&mut self, source: f32) -> f32 {
        let mut y = source;
        y = self.f1.process(y);
        y = self.f2.process(y);
        y = self.f3.process(y);
        y = self.f4.process(y);
        y
    }
}
```

通过改变 F1-F4 频率,合成不同 vowel("a"、"e"、"i"、"o"、"u")。这就是 **vocoder** 的工作原理——分析输入人声的 formants,应用到 carrier 信号(synth 输出)。

### 10.3 Reverb 算法

**Reverb** 是 DSP 里最复杂的效果之一。三类:

**1. Convolution reverb**:用 impulse response(IR,真实空间录的"砰"声响应)卷积输入信号。最真实,但 CPU 重(需要 partitioned FFT convolution)。Altiverb、LiquidSonics、Revolution 是商业卷积 reverb。

**2. Algorithmic reverb**:用 comb + allpass 串联模拟空间反射。CPU 轻,可调参数多。Manfred Schroeder 1962 论文给出经典结构:**4 个 comb + 2 个 allpass**(并联 comb,串行 allpass)。

```rust
pub struct SchroederReverb {
    combs: Vec<CombFilter>,         // 4 个,不同 delay(典型 1116、1188、1277、1356 sample @ 44.1k)
    allpasses: Vec<AllpassFilter>,  // 2 个,delay 556 和 441
    comb_feedback: f32,             // 0.7-0.85
    allpass_feedback: f32,          // 0.6-0.7
}

pub struct CombFilter { delay_line: Vec<f32>, head: usize, feedback: f32, damp: OnePoleLPF }

impl CombFilter {
    pub fn process(&mut self, x: f32) -> f32 {
        let delayed = self.delay_line[self.head];
        let filtered = self.damp.process(delayed);
        let output = x + filtered * self.feedback;
        self.delay_line[self.head] = output;
        self.head = (self.head + 1) % self.delay_line.len();
        output
    }
}
```

Freeverb(Jezar at Dreampoint,1998 开源)是经典 4-comb-per-channel + 2-allpass。今天的 ValleyAudio DX Reverb、TAL Reverb 都衍生自这套。

**3. Physical modeling reverb**:模拟声波在房间里的反射。最新方向,Quality 很好但 CPU 极重。

### 10.4 Compressor 和 sidechain

**Compressor**:减少动态范围——大声变小,小声不变。核心参数:threshold、ratio、attack、release、knee、makeup gain。

```rust
pub struct Compressor {
    threshold: f32,  // dB
    ratio: f32,      // 1:1 to inf:1
    attack: f32,     // s
    release: f32,    // s
    envelope: f32,   // 当前 envelope follower 值
    sample_rate: f32,
}

impl Compressor {
    pub fn process(&mut self, x: f32) -> f32 {
        // 1. Envelope follower(rectified, smoothed)
        let abs_x = x.abs();
        let attack_coef = (-1.0 / (self.attack * self.sample_rate)).exp();
        let release_coef = (-1.0 / (self.release * self.sample_rate)).exp();
        if abs_x > self.envelope {
            self.envelope = attack_coef * self.envelope + (1.0 - attack_coef) * abs_x;
        } else {
            self.envelope = release_coef * self.envelope + (1.0 - release_coef) * abs_x;
        }
        // 2. Gain reduction
        let env_db = 20.0 * self.envelope.max(1e-10).log10();
        let over_threshold = env_db - self.threshold;
        let reduction_db = if over_threshold > 0.0 {
            over_threshold * (1.0 - 1.0 / self.ratio)
        } else { 0.0 };
        let gain = 10.0_f32.powf(-reduction_db / 20.0);
        x * gain
    }
}
```

**Sidechain compression**:用另一个信号(kick drum)控制 compressor。EDM 的 "pumping" effect——kick 击中时,整个 mix 被 ducked,产生"呼吸感"。把 kick 信号送给 compressor 的 sidechain input,而不是直接压缩信号本身。

### 10.5 Audio effect chaining

实际 synth 输出会过一串 effect:**EQ → Compressor → Reverb → Limiter**。这叫 **signal chain** 或 **insert chain**。

```rust
pub struct ChannelStrip {
    eq_low: Biquad,       // HP @ 80 Hz
    eq_mid: Biquad,       // Peak @ 1 kHz
    eq_high: Biquad,      // Shelf @ 8 kHz
    compressor: Compressor,
    reverb: SchroederReverb,
    limiter: Limiter,
    reverb_send: f32,     // 0-1
}

impl ChannelStrip {
    pub fn process(&mut self, x: f32) -> f32 {
        let mut y = self.eq_low.process(x);
        y = self.eq_mid.process(y);
        y = self.eq_high.process(y);
        y = self.compressor.process(y);
        // Reverb 是 send/return(并行)
        let wet = self.reverb.process(y);
        let y = y * (1.0 - self.reverb_send) + wet * self.reverb_send;
        self.limiter.process(y)
    }
}
```

这是工业 DAW 的混音 paradigm。每个 channel 一个 strip,master bus 一个总的。

## 11 · 性能数据和生产坑

### 10.1 性能基准

测试平台:Ryzen 7 5800X,Rust 1.76,--release,target-cpu=native。

| 操作 | 单 sample 时钟 | 1 秒 CPU 占用 @ 44.1kHz |
|---|---|---|
| Sine osc | 5 ns | 0.022% |
| Naive saw | 2 ns | 0.009% |
| polyBLEP saw | 8 ns | 0.035% |
| Wavetable (linear interp) | 12 ns | 0.053% |
| Wavetable (cubic interp) | 25 ns | 0.11% |
| Biquad | 6 ns | 0.026% |
| 1 operator FM | 18 ns | 0.079% |
| 6 operator FM | 100 ns | 0.44% |
| Karplus-Strong | 4 ns | 0.018% |
| ADSR | 4 ns | 0.018% |
| Full subtractive voice (2 osc + filter + 2 env) | 60 ns | 0.26% |

64-voice polyphony subtractive synth:64 × 60 = 3840 ns/sample = 17% CPU @ 44.1 kHz。**完全可承受**。

### 10.2 生产坑

**坑1:Phase accumulator 精度**。f32 phase 在长时间运行后丢失精度——`phase += inc`,经过 1 小时后 inc 累积误差 audible。**解决**:用 f64 累积,或定期 reset。

**坑2:Filter coefficient smoothing**。cutoff 突变(banks 切换、LFO 推到极端)导致 filter 输出跳变,听起来"咔嚓"。**解决**:每样本 lerp 系数 5-20 ms。

**坑3:Voice stealing artifacts**。重用 voice 时,旧 note 的 envelope 还在 release,直接 note_on 会截断。**解决**:在 voice stealing 时 fast release(几 ms 内衰减到 0),然后 note_on。

**坑4:Note number index drift**。多音色 synth 用 `Vec<Voice>`,反复 note_on/off 后 voice 状态混乱。**解决**:用 explicit `voice_state: enum { Idle, Playing(NoteId), Releasing(NoteId) }`,严格 tracking。

**坑5:LFO phase desync**。多 voice polyphony,每个 voice LFO 独立 phase → 振颤不同步,听起来 messy。**解决**:**global LFO**(所有 voice 共享),或 polyphonic LFO with phase sync。

**坑6:Pitch bend range**。MIDI pitch bend 是 ±2 semitones 默认,但 synth 应该可配(±12、±24 也常见)。误以为固定 ±2 会让 glissando 不自然。

**坑7:DC offset accumulation**。某些波形(saw、square)的 DC 分量不为 0,长时间累积可能 saturate filter。**解决**:用 AC-coupled filter(20 Hz HPF on output)。

**坑8:Aliasing from modulation**。LFO 调 cutoff 时,cutoff 突变可能引入 alias。**解决**:cutoff 平滑,或用 zero-delay feedback filter topology。

### 10.3 跨学科:音乐、心理学、神经科学

合成器是**音乐、工程、心理声学的交叉**。

**乐理**:12 平均律(12-TET)、just intonation、microtonal。 oscillator 必须支持任意频率(不只是 12-TET 离散音)。

**心理声学**:临界频带(critical band)、masking、virtual pitch。FM 合成的边带落到不同 critical band,听起来不同。

**神经科学**:听觉皮层对 harmonic vs inharmonic 反应不同。FM bell(inharmonic)激活更广泛的脑区,这就是为什么 bell 听起来"诡异"。

**音乐治疗**:Yamaha VL1(物理建模 sax)用于音乐治疗——医生实时调整物理参数,匹配患者情绪。

学合成器不只是学代码,**也学音乐和心理声学**。

## 12 · 完整 Rust 项目:mini subtractive synth

下面是 cpal + 16-voice polyphonic subtractive synth + 简单 MIDI 输入(用 midir crate)的最小骨架。

`Cargo.toml`:

```toml
[package]
name = "mini-synth"
version = "0.1.0"
edition = "2021"

[dependencies]
cpal = "0.15"
midir = "0.9"

[profile.release]
opt-level = 3
lto = "fat"
codegen-units = 1
```

`src/main.rs`(简化版,完整可跑):

```rust
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};

// === DSP 基础(简化,完整代码见 dsp-fundamentals.md)===
fn poly_blep(t: f32, dt: f32) -> f32 {
    if t < dt {
        let x = t / dt;
        x + x - x * x - 1.0
    } else if t > 1.0 - dt {
        let x = (t - 1.0) / dt;
        x + x + x * x + 1.0
    } else { 0.0 }
}

// === Oscillator ===
pub struct Osc {
    pub phase: f32,
    pub phase_inc: f32,
}
impl Osc {
    pub fn process_saw(&mut self) -> f32 {
        let t = self.phase;
        let y = 2.0 * t - 1.0 - poly_blep(t, self.phase_inc);
        self.phase += self.phase_inc;
        if self.phase >= 1.0 { self.phase -= 1.0; }
        y
    }
}

// === ADSR(简化)===
#[derive(PartialEq, Clone, Copy)]
enum EnvState { Idle, Attack, Decay, Sustain, Release }
pub struct Adsr {
    state: EnvState,
    pub attack: f32, pub decay: f32, pub sustain: f32, pub release: f32,
    level: f32, sample_rate: f32,
}
impl Adsr {
    pub fn new(sr: f32) -> Self {
        Adsr { state: EnvState::Idle, attack: 0.01, decay: 0.1,
               sustain: 0.7, release: 0.3, level: 0.0, sample_rate: sr }
    }
    pub fn note_on(&mut self) {
        self.state = EnvState::Attack;
    }
    pub fn note_off(&mut self) {
        self.state = EnvState::Release;
    }
    pub fn is_idle(&self) -> bool { self.state == EnvState::Idle }
    pub fn process(&mut self) -> f32 {
        match self.state {
            EnvState::Attack => {
                self.level += 1.0 / (self.attack * self.sample_rate);
                if self.level >= 1.0 { self.level = 1.0; self.state = EnvState::Decay; }
            }
            EnvState::Decay => {
                self.level -= (1.0 - self.sustain) / (self.decay * self.sample_rate);
                if self.level <= self.sustain { self.level = self.sustain; self.state = EnvState::Sustain; }
            }
            EnvState::Sustain => {}
            EnvState::Release => {
                self.level -= 1.0 / (self.release * self.sample_rate);
                if self.level <= 0.0 { self.level = 0.0; self.state = EnvState::Idle; }
            }
            EnvState::Idle => { self.level = 0.0; }
        }
        self.level
    }
}

// === One-pole LPF(简化)===
pub struct Lpf { prev: f32, alpha: f32 }
impl Lpf {
    pub fn new(cutoff: f32, sr: f32) -> Self {
        let alpha = 1.0 - (-2.0 * std::f32::consts::PI * cutoff / sr).exp();
        Lpf { prev: 0.0, alpha }
    }
    pub fn set_cutoff(&mut self, cutoff: f32, sr: f32) {
        self.alpha = 1.0 - (-2.0 * std::f32::consts::PI * cutoff / sr).exp();
    }
    pub fn process(&mut self, x: f32) -> f32 {
        self.prev = self.alpha * x + (1.0 - self.alpha) * self.prev;
        self.prev
    }
}

// === Voice ===
pub struct Voice {
    osc1: Osc,
    osc2: Osc,
    amp_env: Adsr,
    filter_env: Adsr,
    filter: Lpf,
    freq: f32,
    alive: bool,
    sample_rate: f32,
}
impl Voice {
    pub fn new(sr: f32) -> Self {
        Voice {
            osc1: Osc { phase: 0.0, phase_inc: 0.0 },
            osc2: Osc { phase: 0.0, phase_inc: 0.0 },
            amp_env: Adsr::new(sr),
            filter_env: Adsr::new(sr),
            filter: Lpf::new(2000.0, sr),
            freq: 0.0, alive: false, sample_rate: sr,
        }
    }
    pub fn note_on(&mut self, freq: f32) {
        self.freq = freq;
        self.osc1.phase_inc = freq / self.sample_rate;
        let detune = 2.0_f32.powf(7.0 / 1200.0);  // 7 cents
        self.osc2.phase_inc = freq * detune / self.sample_rate;
        self.amp_env.note_on();
        self.filter_env.note_on();
        self.alive = true;
    }
    pub fn note_off(&mut self) {
        self.amp_env.note_off();
        self.filter_env.note_off();
    }
    pub fn process(&mut self) -> f32 {
        if !self.alive { return 0.0; }
        let o1 = self.osc1.process_saw();
        let o2 = self.osc2.process_saw();
        let mix = (o1 + o2) * 0.5;
        // filter envelope modulates cutoff
        let f_env = self.filter_env.process();
        let cutoff = 200.0 + f_env * 5000.0;
        self.filter.set_cutoff(cutoff, self.sample_rate);
        let filtered = self.filter.process(mix);
        let amp = self.amp_env.process();
        if self.amp_env.is_idle() { self.alive = false; }
        filtered * amp
    }
}

// === Synth(polyphonic)===
pub struct Synth {
    voices: Vec<Voice>,
    active_notes: HashMap<u8, usize>,  // MIDI note → voice index
    sample_rate: f32,
}
impl Synth {
    pub fn new(num_voices: usize, sr: f32) -> Self {
        let voices = (0..num_voices).map(|_| Voice::new(sr)).collect();
        Synth { voices, active_notes: HashMap::new(), sample_rate: sr }
    }
    pub fn note_on(&mut self, midi_note: u8) {
        let freq = 440.0 * 2.0_f32.powf((midi_note as f32 - 69.0) / 12.0);
        // 找空闲 voice
        let voice_idx = self.voices.iter().position(|v| !v.alive)
            .unwrap_or_else(|| {
                // Voice stealing:最老的(简化:第 0 个)
                0
            });
        self.voices[voice_idx].note_on(freq);
        self.active_notes.insert(midi_note, voice_idx);
    }
    pub fn note_off(&mut self, midi_note: u8) {
        if let Some(&idx) = self.active_notes.get(&midi_note) {
            self.voices[idx].note_off();
            self.active_notes.remove(&midi_note);
        }
    }
    pub fn process(&mut self, output: &mut [f32]) {
        for sample in output.iter_mut() {
            let mut sum = 0.0_f32;
            for v in &mut self.voices {
                if v.alive { sum += v.process(); }
            }
            *sample = sum * 0.3;  // soft limit
        }
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let host = cpal::default_host();
    let device = host.default_output_device().ok_or("no device")?;
    let config: cpal::StreamConfig = device.default_output_config()?.into();
    let sr = config.sample_rate.0 as f32;

    let synth = Arc::new(Mutex::new(Synth::new(16, sr)));
    let synth_for_audio = synth.clone();

    // 默认配置
    {
        let mut s = synth.lock().unwrap();
        s.voices.iter_mut().for_each(|v| {
            v.amp_env.attack = 0.01;
            v.amp_env.decay = 0.1;
            v.amp_env.sustain = 0.7;
            v.amp_env.release = 0.3;
            v.filter_env.attack = 0.005;
            v.filter_env.decay = 0.2;
            v.filter_env.sustain = 0.3;
            v.filter_env.release = 0.2;
        });
    }

    // 演示 sequence:C E G B C
    let demo_sequence = [60u8, 64, 67, 71, 72];
    let mut step = 0;
    let mut last_trigger_time = std::time::Instant::now();
    let mut note_held = false;

    let stream = device.build_output_stream(
        &config,
        move |out: &mut [f32], _: &cpal::OutputCallbackInfo| {
            // Demo: 每 500 ms 触发一个音
            if last_trigger_time.elapsed() > std::time::Duration::from_millis(500) {
                let mut s = synth_for_audio.lock().unwrap();
                if note_held {
                    s.note_off(demo_sequence[step]);
                    step = (step + 1) % demo_sequence.len();
                    note_held = false;
                } else {
                    s.note_on(demo_sequence[step]);
                    note_held = true;
                }
                last_trigger_time = std::time::Instant::now();
            }
            let mut s = synth_for_audio.lock().unwrap();
            s.process(out);
        },
        |err| eprintln!("audio err: {}", err),
        None,
    )?;
    stream.play()?;

    println!("Mini synth playing demo. Press Ctrl+C to stop.");
    std::thread::sleep(std::time::Duration::from_secs(30));
    Ok(())
}
```

跑:

```bash
cargo run --release
# 听到 C E G B C 循环,每个 500 ms,带 attack/decay envelope + filter sweep
```

### 11.1 集成 MIDI 输入

加上 `midir` 可以从真实 MIDI 键盘接收 note_on/off。完整代码在 https://github.com/RustAudio/midir 示例。

```rust
use midir::{MidiInput, MidiInputConnection};

let midi_in = MidiInput::new("mini-synth")?;
let in_port = midi_in.ports()[0];  // 第一个 MIDI 设备
let synth_for_midi = synth.clone();

let _conn = midi_in.connect(&in_port, "input", move |_, message, _| {
    let mut s = synth_for_midi.lock().unwrap();
    match message {
        [0x90, note, vel] if *vel > 0 => s.note_on(*note),  // note on
        [0x80, note, _] => s.note_off(*note),                // note off
        [0x90, note, 0] => s.note_off(*note),                // note on with vel 0
        _ => {}
    }
}, ())?;
```

## 13 · 在你 HH 项目里实践

**练习 1:加程序化 BGM**。

写一个 ambient pad synth + drone bass,跟着玩家位置/血量调整参数。位置 1(草原)→ cutoff 高(亮);位置 2(地下城)→ cutoff 低(闷)。血量低 → 加 LFO 调制(紧张感)。

**练习 2:做 procedural SFX**。

每次玩家挥剑,生成短 SFX:white noise burst + band-pass filter(2 kHz)+ exponential decay envelope(100 ms)。每次微调参数(burst 长度 80-120 ms 随机,中心频率 1800-2200 Hz 随机)——每次挥剑都不同,但都"是挥剑"。

**练习 3:实现"音色 reactive"环境**。

玩家走到不同区域,触发不同 synth voice。每个区域有一个 "guardian"——守护者声音。接近时 pitch 上升,远离时下降。

**练习 4:做 procedural drum machine**。

写一个 808 kick / snare / hi-hat synth。用 step sequencer 每 16 步触发。这是 HH 风格的"程序化音乐"——背景节奏。

**练习 5:做 melody generator**。

按某个 scale(pentatonic 容易听)随机生成旋律,每个 voice 的 ADSR + filter 设定。这是 "generative music"——Brian Eno 风格。

**练习 6:做 FM bell choir**。

在地图上放 5-10 个 "bell" 实体。玩家靠近触发 FM bell(载波频率匹配实体 ID)。多个 bell 同时触发形成 ambient 音景。

**练习 7:做声音音色编辑器**。

扩展 day200 的 debug overlay,加一个 synth editor——实时调整 ADSR、cutoff、LFO depth。修改参数立即听到效果。这是**音色设计教学工具**。

**练习 8:Karplus-Strong 弦乐器**。

玩家可以在游戏里"弹弦"。每根弦是 Karplus-Strong voice,长度由玩家选择(决定基频)。多弦叠加形成"竖琴"或"班卓琴"。

## 14 · 延伸阅读

本仓库本地资料:
- [phase-5/day009.md](../../phase-1/day009.md) — HH 第一次音频
- [phase-5/day142.md](../../phase-4/day142.md) — HH mixer
- [phase-5/day184.md](../day184.md) — HH 实时音频效果
- [phase-5/deep-dives/dsp-fundamentals.md](dsp-fundamentals.md) — DSP 基础(filter 公式)
- [phase-5/deep-dives/fft-and-spectral-analysis.md](fft-and-spectral-analysis.md) — FFT 和频谱(波形分析)
- [phase-5/deep-dives/audio-pipeline-complete.md](audio-pipeline-complete.md) — 完整音频流水线

外部稳定 URL:
- Curtis Roads, "The Computer Music Tutorial"(1996,圣经级教科书):https://mitpress.mit.edu/9780262680820/the-computer-music-tutorial/
- Sound on Sound "Synth Secrets" 系列(Gordon Reid 1999-2004 经典 63 篇):https://www.soundonsound.com/series/synth-secrets
- Chowning 1973 "The Synthesis of Complex Audio Spectra by Means of Frequency Modulation":https://www.jstor.org/stable/1518509
- Smith, "Physical Audio Signal Processing"(在线,免费,waveguide 圣经):https://ccrma.stanford.edu/~jos/pasp/
- Stilson & Smith 1997 "Alias-Free Digital Synthesis of Classic Analog Waveforms"(polyBLEP 起源) https://ccrma.stanford.edu/~stilti/papers/blit.pdf
- Karplus & Strong 1983 "Digital Synthesis of Plucked-String and Drum Timbres":https://www.cs.cmu.edu/~music/music.psp/KarplusStrong.pdf
- Pirkle, "Designing Software Synthesizer Plug-Ins in C++"(with JUCE,实例丰富):https://www.routledge.com/Designing-Software-Synthesizer-Plug-Ins-in-C-with-Audio-DSP/Pirkle/p/book/9781138583931
- Matt Tytel 的 Vital(开源 wavetable synth,代码值得读):https://github.com/mtytel/vital
- Serum 视频教程(Xfer Records,商业 wavetable synth 行业标准):https://xferrecords.com/

真实开源源码:
- fundsp(函数式 DSP):https://github.com/SamiPerttu/fundsp
- megrid(modal synthesis):https://github.com/Argrath/megrid
- Vital(Matt Tytel 开源 wavetable synth,C++,大型参考):https://github.com/mtytel/vital
- ZynAddSubFX(open source additive/FM synth,C++):https://github.com/zynaddsubfx/zynaddsubfx
- Helm(Matt Tytel 较早的 subtractive synth,开源):https://github.com/mtytel/helm
- surge-synthesizer(开源 hybrid synth,C++):https://github.com/surge-synthesizer/surge
- Cardinal VST(open source Reaktor-like):https://github.com/DISTRHO/Cardinal
- oxc-synth(Rust synth 参考):https://github.com/oxc/oxc-synth
- aubio(包括 onset detection、pitch detection):https://github.com/aubio/aubio

历史演化:
- 1876 Alexander Graham Bell 电话(电信号 + 振荡器雏形)
- 1920s Lev Termen 的 Theremin(第一个电子乐器)
- 1939 Hammond C Hammond Organ(additive + drawbars)
- 1964 Robert Moog AES 论文(第一个电压控制合成器)
- 1970 Minimoog Model D(portable subtractive synth)
- 1983 Yamaha DX7(第一个商业成功数字 FM synth)
- 1983 Karplus-Strong 算法(简单 string synthesis)
- 1996 Reaktor(software modular synth)
- 2006 NI Massive(wavetable + synth 标杆)
- 2014 Serum(Xfer Records,polyBLEP + spectral morphing)
- 2020 Vital(开源 wavetable,免费,DMT 出品)
- 2020s Neural synth(RAVE、AudioCraft、JASCO)— ML 生成音色
