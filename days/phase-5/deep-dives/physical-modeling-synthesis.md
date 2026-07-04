
# 物理建模合成

> 你刚刚用 subtractive synth 做了一把不错的"synth 吉他"——锯齿波 + 带通滤波 + 短 envelope,听起来像是"吉他"。可玩家在你耳边反馈:"它听起来太合成器了,不像真正的拨弦。"你想到了**采样合成**——直接录一把真吉他,触发时播放。但采样有它自己的问题:88 个音高 × 8 个力度层 × 4 个 round robin = 几千个采样,占几十 GB;而且**每个采样是死的**——你没法"在播放中改变拨弦位置"。**真正想突破这个困境,你得回到物理**:一根真实的弦是什么?是一段绷紧的钢丝,两端固定,中间被手指或拨片扰动了。物理学家告诉你,这根弦服从一维波动方程(d'Alembert 1747),波沿着弦往返传播,在两端反射,沿途损失能量。如果你**直接数值模拟这个波动方程**,你就得到了一根"虚拟弦"——它会**像真弦一样响应**:换个张力,音高变;换拨弦位置,音色变;轻轻拨 vs 狠狠拨,decay 不一样。这就是 **物理建模合成**(physical modeling synthesis),是 Stanford CCRMA 的 **Julius O. Smith III** 用半生建立的领域。这一篇我们从最简单的 Karplus-Strong(20 行代码做出一根弦)一路推到 digital waveguide(双向延迟线)、modal synthesis(模态合成),最终在 HH 项目里用 cpal 跑出第一个能"调张力、调拨弦位置"的程序化弦乐器——这是合成器走向"乐器"的关键一步。

## 0 · 为什么要有这一篇

你已经在 [synthesis-and-instruments](synthesis-and-instruments.md) 里走过减法合成、FM、wavetable、Karplus-Strong 这套大家族。那些方法有一个共性:**它们都在塑造某种波形或频谱**——saw、square、FM 边带、白噪 + 平均——来"接近"目标声音。它们是**信号层面的近似**。

但乐器不是信号,乐器是**物理对象**。一根真实的吉他弦,它的音色不是"因为我把它设计成某种波形",而是因为"它是这么长、这么紧、这么粗、被这么拨了一下"。如果你**模拟这根弦的物理过程**,声音是物理的副产物——它**自动**具备你想要的全部表现力。

这件事为什么游戏开发者特别要学?让我给几个具体的工程场景。

**场景一**:你的角色扮演游戏里有一把"魔法竖琴"。玩家可以在房间里走过去,鼠标按下,拖动鼠标改变"拨弦力度",松开时播放音。如果用采样,你最多录 5 种力度——拖动鼠标只能在这 5 种之间跳,听起来生硬。如果用 Karplus-Strong + 物理参数,**拨弦力度直接是 noise burst 的振幅,拨弦位置直接是延迟线初始扰动的形状**——拖动鼠标时音色连续变化,无限细分。

**场景二**:你的 roguelike 关卡每层都有"环境乐器"——某种神秘的钟、风铃、共鸣石。每层 procedural 生成,**每层的钟都需要不同的音色**。如果用采样,你得录几百种钟。如果用 modal synthesis,**每个钟就是一组模态频率 + 模态衰减**——几行参数,**随机生成 thousands 种不同音色的钟**,体积是零。

**场景三**:你想做"弦被切断"的音效——玩家斩断了吊桥的绳索,绳索应该发出"嘣"的断裂声,然后共鸣衰减。**采样很难做这件事**(谁去录断绳?),但物理建模可以:**把弦的张力参数突然设为某个低值,同时把拨弦能量设到最大**——你会听到一根"松弦"被狠狠扯响,衰减迅速,音色怪异。这就是物理参数变化带来的**自然乐器响应**。

**场景四**:移动端 / Web 端游戏。下载几十 GB 的钢琴采样库不现实。但**Pianoteq 风格的物理建模钢琴**整个引擎 < 50 MB,音质接近采样,响应比采样更真实。物理建模是"小体积 + 高表现力"的天作之合。

**读完这一篇,你应该能**:

- 解释 subtractive / FM / wavetable 合成和物理建模合成的**根本范式差异**——前者塑造波形,后者模拟物理
- 写出 d'Alembert 一维波动方程,理解为何它的通解是"两束反向行波之和"
- 从零实现 Karplus-Strong 算法,逐行解释为什么"白噪 + 延迟线 + 平均"会发出弦的声音
- 把 Karplus-Strong 推广到 digital waveguide(双向延迟线),实现 string 与 bridge 的波阻抗接头(junction)
- 解释 modal synthesis(模态合成)适合什么对象、不适合什么对象,以及如何从一根金属棒的物理参数算出它的模态频率
- 在 Rust + cpal 里写一个可交互调参的物理建模弦乐器
- 评估物理建模在游戏制作中的真实成本:CPU、调音难度、和采样的 hybrid 取舍

读者基线:完成 HH [phase-0/22-signals-foundation](../../phase-0/22-signals-foundation.md) 信号基础 + [phase-5/day009](../../phase-1/day009.md) 音频 + [dsp-fundamentals](dsp-fundamentals.md) DSP 基础 + [synthesis-and-instruments](synthesis-and-instruments.md) 合成基础 + [fft-and-spectral-analysis](fft-and-spectral-analysis.md) FFT(下面用 FFT 分析弦的谐波结构)。

## 1 · 范式转变:从塑造波形到模拟物理

让我先把这件事的"思想跳跃"讲清楚。这是这一篇最关键的一段。

减法合成的 mental model 是这样的:我手里有一个"泛音丰富的源"(saw、square),我要"从里面挑出想要的频率"——用 filter 切掉不要的部分。FM 合成的 mental model 类似:我用一个振荡器调另一个,通过 modulation index 控制谐波丰富度,**结果还是一个频谱塑形的过程**。它们的共同点是:**直接操作信号或频谱**,至于"这个信号是怎么产生的"——不关心。

物理建模合成的 mental model 完全不同。它问的问题不是"这个声音的频谱是什么形状",而是"**这个声音是从什么物理对象里出来的,那个物理对象遵循什么方程**"。一旦你有了方程,你**数值积分**它,声音是积分的输出。你不"设计频谱",频谱**自动**从物理里出来。

这件事的威力在哪?让我用一个具体例子。一把吉他弦,音高由弦长、张力、线密度决定:

$$ f_0 = \frac{1}{2L} \sqrt{\frac{T}{\mu}} $$

L 是弦长(米),T 是张力(牛顿),μ 是线密度(kg/米)。**你只要改变这三个物理参数,音高自然变**——不需要"重新设计波形"。同样,拨弦的位置决定哪些谐波被激发——拨中间,奇次谐波强(因为中点是基频的腹点、二次谐波的节点);拨靠近 bridge 处,所有谐波都被激发,音色"亮"。**你只要改变扰动在弦上的位置,音色自然变**——不需要"重新调 filter cutoff"。

这种**参数 → 自然声音变化**的关系,是采样合成做不到的(采样是离散的、有限的),也是 subtractive / FM 合成做不到的(那些合成器和"拨弦位置"没有自然对应)。**物理建模是唯一让"虚拟乐器"具备"真实乐器表现力"的合成范式**。这就是为什么 Julius Smith 在 Stanford CCRMA 花了 40 年研究它,以及为什么 Yamaha VL1(1993,第一个商用物理建模合成器)虽然商业失败但学术意义重大。

物理建模的主要分支有三个,我们逐一深入:**waveguide synthesis**(波导合成,Smith 的主战场,适合弦和管)、**modal synthesis**(模态合成,适合刚性共振体——钟、马林巴、木块)、**mass-spring synthesis**(质点-弹簧模型,适合任意几何——膜、壳、布料)。这一篇重点讲前两个,质点-弹簧模型因为计算太重在游戏里罕见,只做概览。

## 2 · 弦的物理:d'Alembert 波动方程

要模拟弦,先要知道弦服从什么方程。这是 1747 年法国数学家 d'Alembert 给出的——**一维波动方程**(1D wave equation):

$$ \frac{\partial^2 y}{\partial t^2} = c^2 \frac{\partial^2 y}{\partial x^2} $$

`y(x, t)` 是弦在位置 x、时间 t 的横向位移(垂直于弦的振动方向)。`c` 是波速:

$$ c = \sqrt{\frac{T}{\mu}} $$

T 是张力,μ 是线密度。**这个方程说的是:弦上每一点的横向加速度,正比于它位置的"曲率"**(`∂²y/∂x²` 是空间二阶导,描述弦在该点的弯曲程度)。直觉:如果弦在该点比邻居高,它会被往下拉;如果比邻居低,被往上推。**这种"邻居拉扯"传播出去就是波**。

### 2.1 d'Alembert 通解:两束反向行波

这个偏微分方程有一个非常优美的通解,d'Alembert 自己给出的:

$$ y(x, t) = y_r(x - ct) + y_l(x + ct) $$

`y_r(x - ct)` 是一束**向右传播**的波(c 是波速,所以 t 增加时,形状 `y_r` 整体向右移动 ct);`y_l(x + ct)` 是一束**向左传播**的波。**弦上的总位移 = 两束反向行波之和**。

这个结论非平凡。它告诉我们:**任何弦的振动,无论多复杂,都可以分解为一束向右的波 + 一束向左的波**。这两束波各自保持形状(在无损弦上),只是在弦的两端被反射。

为什么这件事在数字合成里重要?因为它给了我们一个**计算上极其便宜**的模拟方法:**不用数值积分偏微分方程**(那种网格离散化、CFL 条件、稳定性 headache),**只需要两根延迟线**——一根存"向右的波"的历史,一根存"向左的波"的历史,每一步都让它们各前进一个采样,在端点处理反射。这就是下一节 digital waveguide 的核心思想。Karplus-Strong 是它的简化特例。

### 2.2 边界条件:为什么弦会有谐波

弦的两端是固定的(吉他的 bridge 和 nut)。固定端意味着 `y(0, t) = y(L, t) = 0`。这个边界条件对通解 `y_r + y_l` 施加约束:在 x = 0,必须有 `y_r(-ct) + y_l(ct) = 0`,即 `y_l(ct) = -y_r(-ct)`——**向左的波是向右的波在端点的"负镜像"**。物理上这是**反射时相位翻转**(fixed-end reflection)。

把这个边界条件 + 通解 + 周期性(波在弦上往返)结合起来,你会发现只有某些特定频率的波能稳定存在——它们形成驻波(standing wave),频率是 `f_n = n · c / (2L)`,n = 1, 2, 3, ...。**这就是弦的谐波系列**(harmonic series),n=1 是基频,n=2 是二次谐波,以此类推。这就是为什么吉他、小提琴、钢琴都发出**谐波结构**的声音——这是物理决定的,不是设计出来的。

物理建模合成最优雅的地方是:**这套谐波结构自动从模拟里出来**——你不需要"知道"弦有谐波,你只要正确模拟波动方程,谐波自己就出现了。这就是 [synthesis-and-instruments](synthesis-and-instruments.md) 里 Karplus-Strong 那段说的"白噪 → 弦振动模式"的深层原因。

### 2.3 损耗:为什么弦的声音会衰减

真实弦有几个损耗机制:空气阻力(高频损耗更重)、弦内部摩擦(热损耗)、端点不完全刚性(能量传到琴体)。这些损耗让弦的振动随时间衰减,而且**高频衰减比低频快**——这就是为什么"刚拨下去时亮,几秒后闷"。

数学上,损耗项加进波动方程:

$$ \frac{\partial^2 y}{\partial t^2} + 2b \frac{\partial y}{\partial t} = c^2 \frac{\partial^2 y}{\partial x^2} $$

(多了 `2b ∂y/∂t` 阻尼项,b 是阻尼系数)。或者更准确的模型——频率相关阻尼,高频损耗更重。

工程上的处理:**不直接数值解这个带阻尼的方程**,而是在 waveguide 的反馈回路里加一个低通滤波器(模拟频率相关损耗)和一个全极点增益(模拟整体能量衰减)。**滤波器的频率响应直接对应物理损耗的频率特性**——这是 waveguide 合成最妙的设计之一。

## 3 · Karplus-Strong:二十行代码做出一根弦

理论讲够了。让我们看一个**简单到难以置信**但**听起来就是弦**的算法——Karplus-Strong。这是 [synthesis-and-instruments](synthesis-and-instruments.md) 提过的"20 行代码做出吉他"的完整版本,这里我们逐行讲解为什么。

**Kevin Karplus 和 Alex Strong** 1983 年在 *Computer Music Journal* 发表了算法,标题是 "Digital Synthesis of Plucked-String and Drum Timbres"。算法极简,但**它就是一根 waveguide 弦的简化版**——只是当时作者还没意识到这个联系,是 Julius Smith 后来(1985+)推广到完整 waveguide 理论的。

### 3.1 算法描述

Karplus-Strong 用一个**环形延迟线**(circular buffer),长度 N 对应基频 `f_0 = f_s / N`(f_s 是采样率)。算法循环:

1. **初始化**:把延迟线填满随机数(白噪,范围 [-1, 1])。这就是"拨弦"——白噪包含所有频率,等价于同时激发了弦的所有振动模式。
2. **每个采样**:输出 `buffer[head]`(这是当前的"弦振动")。
3. **更新**:把 `buffer[head]` 替换成 `(buffer[head] + buffer[next]) / 2 × decay`,其中 next 是 head 的下一个位置,decay 是个略小于 1 的系数(比如 0.996)。
4. **前进**:head 加一(模 N)。

就这么简单。让我们逐项分析为什么这能发出弦的声音。

### 3.2 三个机制的物理解读

**机制一:延迟线长度 N 决定基频**。延迟线是一个长度为 N 的环,信号绕一圈需要 N 个采样。所以**任何信号经过这个环都会被强加一个周期 T = N / f_s**。在频域上,长度 N 的延迟环是一个**梳状滤波器**(comb filter)——在 `f_s / N, 2 f_s / N, 3 f_s / N, ...` 这些频率处增益最大(因为信号绕一圈回来正好同相)。**这就是弦的谐波系列**。N = 100,f_s = 44100,基频 = 441 Hz,二次谐波 882 Hz,三次 1323 Hz,等等。

**机制二:平均操作 `(cur + next) / 2` 是低通滤波器**。这是 [dsp-fundamentals](dsp-fundamentals.md) 里讲过的最简单的一阶 FIR 低通——`y[n] = 0.5 x[n] + 0.5 x[n-1]`,频率响应 `|H(e^{iω})| = |cos(ω/2)|`,DC 处 1,Nyquist 处 0。**高频被衰减,低频保留**。这件事每次循环都发生一次,所以高频损耗**比低频快**——正好对应真实弦的物理损耗(空气阻力对高频更重)。这就是为什么 Karplus-Strong 弦"刚拨时亮,几秒后变闷"——和真弦一样!

**机制三:decay 系数 < 1 是整体能量损耗**。乘以 0.996 每采样意味着每秒衰减 `0.996^44100 ≈ 0`(几乎衰减完)。但这个衰减率和频率无关——所有频率都按同样比例衰减。**这是简化**(真实物理损耗是频率相关的),但效果足够好。

把三个机制合起来:**白噪初始**(激发所有模式)→ **延迟环**(只保留谐波频率)→ **平均低通**(高频快速损耗)→ **整体 decay**(低频慢速损耗)= **吉他/班卓琴/竖琴的拨弦衰减特征**。这就是为什么 Karplus-Strong 听起来像真弦。

### 3.3 Rust 实现

```rust
pub struct KarplusStrong {
    buffer: Vec<f32>,
    head: usize,
    decay: f32,
    /// 一阶低通的反馈系数,控制亮度衰减
    /// brightness = 1.0 时无低通(bright);brightness = 0.5 是经典 KS
    brightness: f32,
    /// 上一拍低通输出,用于一阶 IIR 低通
    lp_state: f32,
}

impl KarplusStrong {
    /// 创建一根弦。freq 是目标基频,sample_rate 是采样率。
    pub fn new(freq: f32, sample_rate: f32) -> Self {
        let n = (sample_rate / freq).round() as usize;
        let n = n.max(2);
        // 初始化:白噪拨弦
        // 注:生产代码用一个固定 seed 的 PRNG,避免 thread_rng 在 audio thread 上开销
        let mut rng_state: u32 = 0x1234_5678;
        let buffer: Vec<f32> = (0..n)
            .map(|_| {
                // xorshift32,简单且无 alloc
                rng_state ^= rng_state << 13;
                rng_state ^= rng_state >> 17;
                rng_state ^= rng_state << 5;
                (rng_state as f32 / u32::MAX as f32) * 2.0 - 1.0
            })
            .collect();
        KarplusStrong {
            buffer,
            head: 0,
            decay: 0.996,
            brightness: 0.5,
            lp_state: 0.0,
        }
    }

    /// 用任意"拨弦形状"excite 延迟线。
    /// excitation[i] 在 [0, 1) 内表示沿弦的归一化位置(i / N)。
    /// 比如拨弦位置 p ∈ [0, 1): excitation[i] = max(0, 1 - |i/N - p| * scale)
    pub fn excite_with(&mut self, excitation: &[f32]) {
        let n = self.buffer.len();
        for i in 0..n {
            let e = if i < excitation.len() { excitation[i] } else { 0.0 };
            // 把拨弦形状注入(覆盖之前的振动)
            self.buffer[i] = e;
        }
        self.head = 0;
        self.lp_state = 0.0;
    }

    /// 简单白噪拨弦(等价于在所有位置注入相同能量)。
    pub fn excite_noise(&mut self) {
        let mut rng_state: u32 = 0x9e37_79b9;
        for i in 0..self.buffer.len() {
            rng_state ^= rng_state << 13;
            rng_state ^= rng_state >> 17;
            rng_state ^= rng_state << 5;
            self.buffer[i] = (rng_state as f32 / u32::MAX as f32) * 2.0 - 1.0;
        }
        self.head = 0;
        self.lp_state = 0.0;
    }

    pub fn process(&mut self) -> f32 {
        let n = self.buffer.len();
        let cur = self.buffer[self.head];
        let next = self.buffer[(self.head + 1) % n];

        // 一阶低通:y[n] = brightness * cur + (1 - brightness) * lp_state
        // brightness = 0.5 时退化为经典 KS 的 (cur + next) / 2
        // 用 IIR 形式可以让低通"更软",模拟更平滑的高频损耗
        let lp_out = self.brightness * cur + (1.0 - self.brightness) * self.lp_state;
        self.lp_state = lp_out;

        // 写回 buffer(注入到下一个位置,等价于延迟线推进)
        let new_value = lp_out * self.decay;
        self.buffer[self.head] = new_value;

        // 推进 head
        self.head = (self.head + 1) % n;

        cur
    }

    /// 实时改 decay(整体衰减率)。0.99 = 慢,0.95 = 快。
    pub fn set_decay(&mut self, decay: f32) {
        self.decay = decay.clamp(0.0, 1.0);
    }

    /// 实时改 brightness(高频损耗)。1.0 = 无损耗(bright),0.1 = 强损耗(闷)。
    pub fn set_brightness(&mut self, brightness: f32) {
        self.brightness = brightness.clamp(0.0, 1.0);
    }
}
```

注意几个工程细节。**第一**,白噪生成用 xorshift32 而不是 `rand` crate——audio thread 上不允许 alloc,也不允许系统调用,`rand::thread_rng()` 内部有 mutex,会引发音频卡顿。xorshift32 是 4 个位运算,几纳秒,完全 deterministic,适合物理建模的 reproducible 音色。**第二**,`brightness` 参数把"经典 KS 的固定平均"推广为可调一阶低通——brightness = 0.5 严格等价 `(cur + next) / 2`,brightness 越小,高频损耗越快,音色越闷;brightness = 1.0 时低通完全关闭,你得到一根"无损耗理想弦",声音永远不衰减(理论上)。**第三**,`excite_with` 允许你注入任意拨弦形状——下一节会讲这如何用来控制音色。

跑一下:

```rust
let mut string = KarplusStrong::new(220.0, 44100.0);  // A3
string.excite_noise();
// 渲染 2 秒
let mut samples = Vec::with_capacity(2 * 44100);
for _ in 0..samples.capacity() {
    samples.push(string.process());
}
// 写到 wav(见完整项目骨架),你会听到一个干净的拨弦音,A3,持续约 1-2 秒衰减
```

试参数:`new(110.0, ...)` 是 A2(低八度,更"低沉");`set_brightness(0.2)` 是闷音(像 palm-muted 吉他);`set_decay(0.99)` 是长 sustain(像钢琴低音弦)。

### 3.4 用拨弦位置塑形音色

真实吉他手知道:**拨弦位置不同,音色差异巨大**。拨靠近 bridge,音色亮(所有谐波都被激发);拨靠近弦中央,音色柔(奇次谐波主导,因为中点是偶次谐波的节点)。Karplus-Strong 可以**直接**模拟这个——只要把白噪替换成"沿弦位置分布的扰动"。

数学上,拨弦位置 p ∈ [0, 1) 把一个三角形分布注入弦:`excitation[i] = max(0, 1 - |i/N - p| * width)`。这个三角形的中心在 p,宽度由拨片大小决定。**为什么三角形?** 因为理想拨弦是弦在某点被瞬间扰动了某个形状——三角形是"拨片在某点抬起弦"的最简单近似。

物理上,这个初始形状决定哪些谐波被激发。**拨在 p = 0.5 处**(弦中央),偶次谐波在中点是节点,所以**只激发奇次谐波**——音色像 clarinet(空、木管感);**拨在 p = 0.3**(靠近 bridge 1/3 处),三次谐波在中点附近是腹点,所以**所有谐波都被激发**,音色亮。这就是 [synthesis-and-instruments](synthesis-and-instruments.md) 里 "pluck position" 概念的物理来源。

```rust
/// 根据"拨弦位置"和"拨片宽度"生成 excitation 形状。
/// pluck_pos ∈ [0, 1):0 = 一端,0.5 = 中央
/// pick_width ∈ [0.01, 0.3]:拨片大小(归一化弦长)
pub fn pluck_shape(string_len: usize, pluck_pos: f32, pick_width: f32) -> Vec<f32> {
    let mut shape = vec![0.0; string_len];
    let center = pluck_pos.clamp(0.0, 1.0) * string_len as f32;
    let half_width = (pick_width * 0.5 * string_len as f32).max(1.0);
    for i in 0..string_len {
        let dist = (i as f32 - center).abs();
        let val = (1.0 - dist / half_width).max(0.0);
        // 加一点随机扰动模拟拨片粗糙度
        let noise = (hash_f32(i as u32) - 0.5) * 0.05;
        shape[i] = val + noise;
    }
    shape
}

fn hash_f32(n: u32) -> f32 {
    let mut x = n.wrapping_mul(2654435761);
    x ^= x >> 16;
    x = x.wrapping_mul(0x85eb_ca6b);
    x ^= x >> 13;
    (x as f32 / u32::MAX as f32).max(0.0).min(1.0)
}
```

把这个 shape 传给 `string.excite_with(&pluck_shape(...))`,你会立刻听到差异——拨中央音色柔,拨靠近端点音色亮。**没有任何 filter、没有任何 envelope,音色变化完全来自初始扰动的空间分布**。这就是物理建模"参数 → 自然音色变化"的威力。

## 4 · Digital Waveguide:Karplus-Strong 的广义化

Karplus-Strong 是个美妙的特例,但它有几个局限:**它只模拟一根均匀弦的最低阶模式**,不能处理"弦两端有不同损耗"、"弦和 bridge 之间有质量耦合"、"弦上有按弦点(改变有效长度)"这些更复杂的物理。

**Julius O. Smith III** 在 1985 之后系统化的 **digital waveguide**(数字波导)理论把这些都涵盖了。他的核心洞察是:**d'Alembert 通解 `y = y_r + y_l` 直接对应两根延迟线**——一根存"向右传播的波"的历史,一根存"向左传播的波"的历史。这件事**不需要离散化偏微分方程**,只要正确处理**端点的反射**(junction,接头),就完全等价于模拟无损弦。

Smith 的著作 *Physical Audio Signal Processing*(在线免费,见延伸阅读)是这个领域的圣经,整个 CCRMA 物理建模传统建立在这本书上。

### 4.1 双向延迟线

回想 d'Alembert 通解:`y(x, t) = y_r(x - ct) + y_l(x + ct)`。在数字域,我们用两个环形 buffer:

- **upper waveguide** `upper[0..N]` 存"向右传播的波"。`upper[i]` 是 x = i · Δx 处的右行波采样。每过一个采样周期,所有波向右移一位(用环形 buffer 的 head 指针实现,而不是真的移数据)。
- **lower waveguide** `lower[0..N]` 存"向左传播的波"。

**弦的总位移** = upper + lower(在每个空间点)。这是 d'Alembert 通解的离散对应。

弦的物理长度 L 对应 buffer 长度 N,`N = round(L · f_s / c)`。一根 A3 (220 Hz) 弦,f_s = 44100,N = 200 个采样 = 4.5 ms 的延迟。**两根 buffer 各 200 个 f32 = 1.6 KB**——内存几乎为零。

### 4.2 反射和接头

弦的两端发生反射。理想固定端:右行波到达 x = L 时,被反射成左行波,且**相位翻转**(`y_l = -y_r`,因为 `y(L, t) = 0` 要求 `y_r + y_l = 0`)。

真实端点不是完全刚性——bridge 把一部分能量传给琴体(发出声音),一部分反射回弦。**这可以用波阻抗(impedance)接头建模**。波阻抗 `Z = √(Tμ)`,描述弦"抵抗波传播的程度"。当波从阻抗 Z_1 的介质传到阻抗 Z_2 的介质,反射系数和透射系数是:

$$ R = \frac{Z_2 - Z_1}{Z_2 + Z_1}, \quad T = \frac{2 Z_2}{Z_2 + Z_1} $$

如果 Z_2 → ∞(完全刚性端),R = 1, T = 0——全反射。如果 Z_2 = Z_1(完美匹配),R = 0, T = 1——无反射,能量完全传过(像吉他 bridge 把能量传给音板)。如果 Z_2 < Z_1(弦接到更"软"的东西,比如弦的自由端),R < 0——反射带相位翻转。

**在 waveguide 里**,我们在每个端点用一个"滤波反射函数"。理想固定端的反射是 `R(z) = -1`(直接取负);真实 bridge 的反射是 `R(z) = -H(z)`,`H(z)` 是一个低通滤波器(模拟琴体对高频的吸收)和全极点增益(模拟能量损耗)的乘积。**这就是 waveguide 比 Karplus-Strong 强的地方**:反射可以任意复杂,只要是 LTI 的就可以用滤波器建模。

### 4.3 一个简化的 waveguide 实现

下面是一个简化但**完整**的单弦 waveguide。它有 upper / lower 双向延迟线,理想 nut(全反射,-1 增益),带低通的 bridge(模拟琴体损耗)。

```rust
/// 一阶低通(同 dsp-fundamentals.md 的 OnePoleLPF)
pub struct OnePoleLPF {
    pub alpha: f32,
    pub state: f32,
}
impl OnePoleLPF {
    pub fn new(cutoff_hz: f32, sample_rate: f32) -> Self {
        let alpha = 1.0 - (-2.0 * std::f32::consts::PI * cutoff_hz.min(sample_rate * 0.49) / sample_rate).exp();
        OnePoleLPF { alpha, state: 0.0 }
    }
    pub fn process(&mut self, x: f32) -> f32 {
        self.state = self.alpha * x + (1.0 - self.alpha) * self.state;
        self.state
    }
}

pub struct WaveguideString {
    /// 向右传播的波(upper delay line)
    upper: Vec<f32>,
    /// 向左传播的波(lower delay line)
    lower: Vec<f32>,
    head: usize,
    /// bridge 反射滤波器(模拟琴体损耗)
    bridge_lpf: OnePoleLPF,
    /// bridge 整体增益(典型 0.95-0.99)
    bridge_gain: f32,
    /// nut 反射增益(理想固定端是 -1)
    nut_gain: f32,
    /// 总输出增益(把弦振动耦合到空气)
    pickup_gain: f32,
}

impl WaveguideString {
    pub fn new(freq: f32, sample_rate: f32) -> Self {
        let n = (sample_rate / freq).round() as usize;
        let n = n.max(2);
        WaveguideString {
            upper: vec![0.0; n],
            lower: vec![0.0; n],
            head: 0,
            // bridge 低通:cutoff 6 kHz,模拟典型吉他琴体对高频的吸收
            bridge_lpf: OnePoleLPF::new(6000.0, sample_rate),
            bridge_gain: 0.98,
            nut_gain: -1.0,  // 理想固定端,反射带相位翻转
            pickup_gain: 0.5,
        }
    }

    /// 拨弦:把初始扰动 split 成 upper + lower 两束反向行波。
    /// 拨弦形状 y(x) 分解为 y_r = y_l = y / 2(d'Alembert 通解的初始条件)
    pub fn excite(&mut self, shape: &[f32]) {
        let n = self.upper.len();
        for i in 0..n {
            let s = if i < shape.len() { shape[i] } else { 0.0 };
            self.upper[i] = 0.5 * s;
            self.lower[i] = 0.5 * s;
        }
        self.head = 0;
    }

    pub fn process(&mut self) -> f32 {
        let n = self.upper.len();
        // 1. 读取 pickup 位置(此处取 head 位置)的总位移
        let y_upper = self.upper[self.head];
        let y_lower = self.lower[self.head];
        let output = (y_upper + y_lower) * self.pickup_gain;

        // 2. 让 upper 向右移动一位,lower 向左移动一位
        //    实现上:我们让 head 推进,等价于波在移动
        //    在新 head 位置之前,先处理端点反射

        // upper 到达右端(bridge),被反射成 lower,经过低通 + 增益
        // bridge 反射:lower_new = -bridge_gain * LPF(upper_at_bridge)
        let upper_at_bridge = self.upper[self.head];
        let bridge_reflected = -self.bridge_gain * self.bridge_lpf.process(upper_at_bridge);

        // lower 到达左端(nut),被全反射,带相位翻转
        let lower_at_nut = self.lower[self.head];
        let nut_reflected = self.nut_gain * lower_at_nut;

        // 3. 注入反射波到对应的另一根延迟线
        //    upper 的下一拍从 nut_reflected 开始(向右传播)
        //    lower 的下一拍从 bridge_reflected 开始(向左传播)
        self.upper[self.head] = nut_reflected;
        self.lower[self.head] = bridge_reflected;

        // 4. 推进 head(波向各自方向传播一个采样)
        self.head = (self.head + 1) % n;

        output
    }
}
```

注意这个实现做了一个简化:它把 upper 和 lower 都存在**同一个 buffer index 空间**里,通过 head 指针的推进隐含地表达"波在传播"。更严格的实现是两根独立延迟线、各自 head 推进、在端点交换数据——但数学上完全等价,这里这样写更紧凑。

**Karplus-Strong 是 waveguide 的什么特例?** 当 bridge 反射滤波器是一个简单的一阶低通(`(cur + next) / 2`),nut 反射是理想 -1,并且我们只看总位移 `upper + lower`(不分上下),那么 upper 和 lower 完全对称、可以合并成单根延迟线——**这就是 Karplus-Strong**。所以 Karplus-Strong 假设了"弦两端对称损耗",这是简化;waveguide 允许 bridge 和 nut 有不同的反射特性,可以模拟"nut 几乎全反射,bridge 大量损耗"这种更真实的物理。

### 4.4 波导合成的扩展:管乐、膜、共鸣体

Waveguide 不限于弦。**管乐**(flute、clarinet、trumpet)是另一类一维波导——空气柱代替弦,两端是开口或闭口(不同的反射系数)。**reed 乐器**(单簧管、萨克斯)在吹嘴处有一个非线性 reed 阀门——压力差推动 reed 开合,这是个非线性边界条件,需要数值求解。Yamaha VL1(1993)就是用 waveguide + reed 模型做的萨克斯,**音色和响应都非常真实**——吹气力度变化时,音色从纯净 tone 过渡到 overblown 的谐波嘶嘶声,这是采样做不到的。

**膜**(drum head)和**壳**(bell body)是二维、三维波导——需要网格化,每个节点连四个邻居。计算量是一维的几百倍,实时需要 GPU。学术界有 2D waveguide 研究,工业上罕见。

**共鸣体**(琴体、房间)可以用 waveguide 网络(connected waveguides)建模——多个 waveguide 在 junction 处耦合,模拟能量在琴体各部分传播。**这就是物理建模 reverb** 的思路,比 Schroeder reverb(见 [dsp-fundamentals](dsp-fundamentals.md) §10.3)更真实,但 CPU 重得多。

## 5 · Modal Synthesis:模态合成

弦和管子是一维连续体,适合 waveguide。**但很多乐器是刚性共振体**——钟、马林巴音条、木块、玻璃碗。这些物体的振动不能用一维波导描述,它们有更复杂的几何。

但这些物体有一个共同特性:**它们的振动可以分解为一组离散的"模态"(mode)**,每个模态是一个特定频率的驻波,有自己的频率、衰减率、初始振幅。**敲击物体 = 同时激发多个模态**。模态合成(model synthesis)就是**直接合成这些模态**——而不是模拟波动方程。

数学上,模态合成输出信号是:

$$ y(t) = \sum_{k=1}^{K} A_k e^{-t / \tau_k} \cos(2 \pi f_k t + \phi_k) $$

每个模态 k 有四个参数:**频率 f_k、衰减时间 τ_k、初始振幅 A_k、初始相位 φ_k**。**整个声音就是 K 个独立衰减正弦的叠加**。

这是 [synthesis-and-instruments](synthesis-and-instruments.md) §2.7 additive synthesis 的近亲——区别是 additive 通常用于周期信号(谐波),modal 用于瞬态共振体(模态可以是非谐波)。也和 [fft-and-spectral-analysis](fft-and-spectral-analysis.md) 紧密相关——你可以用 FFT 分析真实钟声的录音,提取模态参数,然后用 modal 重建。

### 5.1 为什么 modal 适合刚性共振体

一根金属棒(马林巴音条)被敲击后,振动模式由棒的几何和材料决定。理想均匀棒的弯曲振动频率:

$$ f_n = \frac{\pi}{2 L^2} \sqrt{\frac{EI}{\rho S}} \cdot \beta_n^2 $$

L 是棒长,E 是杨氏模量,ρ 是密度,I 是截面惯量,S 是截面积,β_n 是第 n 个振动模式的特征值(β_1 ≈ 1.875, β_2 ≈ 4.694, β_3 ≈ 7.855, ...)。

注意 `β_n` 不是整数比(β_2/β_1 ≈ 2.5,不是 2),所以**棒的振动模式是非谐波**(inharmonic)。这就是为什么马林巴、铃铛听起来"金属感"——它们的频率成分不是简单的 1f, 2f, 3f,而是 1f, 2.5f, 3.95f, ... 这种不规则间隔。

模态合成直接合成这些非谐波模态——每个模态一个独立衰减正弦。**K = 5-10 个模态就足够模拟一个马林巴音条**。CPU 开销是 K 个 sin + K 个 exp,每采样 ~100 ns,**极轻**。

### 5.2 Rust 实现

```rust
pub struct Mode {
    pub freq: f32,
    pub decay: f32,      // 振幅每秒衰减系数(典型 0.1-10,越大衰减越快)
    pub amplitude: f32,
    pub phase: f32,      // 初始相位
    // 内部状态
    phase_inc: f32,
    current_amp: f32,
    active: bool,
}

impl Mode {
    pub fn new(freq: f32, decay: f32, amplitude: f32, sample_rate: f32) -> Self {
        Mode {
            freq,
            decay,
            amplitude,
            phase: 0.0,
            phase_inc: freq / sample_rate,
            current_amp: 0.0,
            active: false,
        }
    }

    pub fn excite(&mut self, intensity: f32) {
        self.current_amp = self.amplitude * intensity;
        self.active = true;
    }

    pub fn process(&mut self, dt: f32) -> f32 {
        if !self.active { return 0.0; }
        let y = self.current_amp * (self.phase * 2.0 * std::f32::consts::PI).cos();
        self.phase += self.phase_inc;
        if self.phase >= 1.0 { self.phase -= 1.0; }
        // 指数衰减:amp *= exp(-decay * dt)
        self.current_amp *= (-self.decay * dt).exp();
        if self.current_amp < 1e-5 { self.active = false; }
        y
    }
}

pub struct ModalVoice {
    modes: Vec<Mode>,
}

impl ModalVoice {
    /// 从一组模态参数构建
    pub fn new(mode_params: &[(f32, f32, f32)]) -> Self {
        // mode_params: [(freq, decay, amplitude), ...]
        let sr = 44100.0;  // 假设固定采样率
        let modes = mode_params.iter()
            .map(|&(f, d, a)| Mode::new(f, d, a, sr))
            .collect();
        ModalVoice { modes }
    }

    pub fn excite(&mut self, intensity: f32) {
        for m in &mut self.modes {
            m.excite(intensity);
        }
    }

    pub fn process(&mut self) -> f32 {
        let dt = 1.0 / 44100.0;
        self.modes.iter_mut().map(|m| m.process(dt)).sum()
    }
}
```

### 5.3 几个常见的 modal 音色配方

**马林巴音条**(基础频率 f,前 4 个模态近似):

```rust
let marimba_params = [
    (1.0 * f, 3.0, 1.0),    // 基频,慢衰减
    (2.5 * f, 8.0, 0.5),    // 第一个非谐波
    (4.0 * f, 12.0, 0.3),
    (6.0 * f, 18.0, 0.15),
];
```

**金属木块**(更亮的非谐波):

```rust
let woodblock_params = [
    (1.0 * f, 8.0, 1.0),
    (2.0 * f, 10.0, 0.6),
    (3.5 * f, 14.0, 0.3),
];
```

**钟**(非常 inharmonic,长 sustain):

```rust
let bell_params = [
    (1.0 * f, 1.5, 1.0),       // hum tone
    (2.0 * f, 2.0, 0.6),       // prime
    (2.4 * f, 3.0, 0.4),       // tierce(非谐波!)
    (3.0 * f, 4.0, 0.3),       // quint
    (4.5 * f, 5.0, 0.2),       // octave
    (5.4 * f, 6.0, 0.15),
];
```

调这些参数,**耳朵是唯一裁判**。从这些起始值开始,微调频率比和衰减时间,你能做出从马林巴到教堂钟的所有打击乐。**这就是为什么 modal synthesis 适合 procedural 生成的游戏乐器**——每个钟、每个木块、每个共鸣石都是一组参数,几行 JSON 就能存,而不是几十 MB 的采样。

### 5.4 从录音提取模态参数

更高级的玩法:**录一个真实钟,用 FFT 分析它的频谱,自动提取模态参数**。这就是 [fft-and-spectral-analysis](fft-and-spectral-analysis.md) 的应用。

流程是:

1. 录钟声(几秒钟的衰减)。
2. 对整段录音做 FFT(或 STFT),找出频谱里的 peak——每个 peak 对应一个模态。
3. 对每个 peak,跟踪它的振幅随时间衰减,拟合指数曲线 `A(t) = A_0 exp(-t/τ)`,得到 τ。
4. 把所有 (freq, τ, A_0) 喂给 ModalVoice——你就有了"这个钟的程序化模型"。

这件事在学术上叫 **modal analysis**,在工业上 Pianoteq (Modartt) 用类似的(但更精细的)方法建模钢琴,整个钢琴引擎 < 50 MB,音质接近 GB 级采样库。

## 6 · Mass-Spring 模型(概览)

第三种物理建模方法是 **mass-spring**(质点-弹簧),由 Claude Cadoz 在 1980s 的 GENESIS 系统开创。思想最物理:**把物体离散化为质点网格,质点之间用弹簧连接,用 Runge-Kutta 或 Verlet 直接数值积分运动方程**。

每个质点服从牛顿第二定律 `F = ma`,力来自连接它的所有弹簧(Hooke 定律 `F = -kx`)加上阻尼(`F = -bv`)。**理论上可以模拟任意几何**——膜、壳、3D 物体、布料、液体表面。**这是最"通用"的物理建模方法**。

但代价巨大:**几千个质点的网格需要几千次力的计算和积分,每秒几万次**。实时需要 GPU,即便如此也只够简单的物体。游戏里 mass-spring 几乎只用于**特殊场景**(虚拟乐器实验室、物理 sandbox),很少用于实际游戏音频。

在 HH 项目里我们不实现 mass-spring,但要知道它存在,以及它和 waveguide / modal 的关系——**waveguide 是 mass-spring 在一维连续体上的解析解**(避免数值积分),**modal 是 mass-spring 在刚性体上的特征分解**(避免数值积分)。**两种方法都是用解析洞察降低计算量**——这是物理建模合成最深刻的工程智慧。

## 7 · 为什么游戏开发者要在乎物理建模

讲完了三种方法,让我们退一步看:**物理建模合成对游戏开发究竟意味着什么?**

**第一,参数化和表现力**。物理建模乐器是**参数化的**——音高、音色、衰减都是连续参数,不是离散采样。这意味着玩家的**任何输入**都可以**直接**映射到声音参数:鼠标 Y → 拨弦位置;鼠标拖动距离 → 拨弦力度;按键时间 → 弦长(滑音)。**玩家每一下操作都得到独特的声音响应**——这是采样做不到的(subtractive / FM 也做不到,因为它们的参数和"乐器表现力"没有自然对应)。

**第二,小体积**。一个 Pianoteq 风格的物理建模钢琴 < 50 MB,而同质量的采样库 30+ GB。**对移动端、Web 端、独立游戏,这个差异是决定性的**。Karplus-Strong 弦乐器整个引擎几百行 Rust 代码,几百 KB 编译后——零采样资产。

**第三,procedural 生成友好**。Roguelike 每层 procedural 生成,如果每层要有不同的"环境乐器",物理建模是唯一可行的——modal synthesis 一个钟就是一组 (freq, decay, amp) 参数,随机生成参数就得到无限种钟。采样要录真钟,不可能 procedural。

**第四,叙事和物理一致**。游戏世界里,玩家砍断了吊桥绳索。如果用采样,你得录"断绳"音效(几乎不可能);如果用物理建模,你**直接改变物理参数**——把弦张力突然降低、把弦的损耗突然提高。声音会自然地响应物理事件,**视觉和听觉在物理上一致**。这种"物理一致性"是游戏世界沉浸感的核心。

**第五,与自适应音乐系统的契合**。自适应音乐系统要求音乐响应游戏状态——血量低时紧张、敌人靠近时危险、解谜成功时欢快。物理建模乐器天然适合这种响应:把"紧张"映射到弦张力(高张力 = 高音 = 紧张)、"危险"映射到拨弦力度(大力拨 = 强烈)、"欢快"映射到模态亮度(brightness 高 = 明亮)。**自适应音乐需要参数化的乐器,物理建模是最好的参数化乐器**。

## 8 · 生产现实:成本、调音、Hybrid 取舍

物理建模不是银弹。在生产中它有几个**严重**的代价,你必须知道。

**代价一:CPU 比 subtractive synth 重**。Karplus-Strong 单 voice 几纳秒/采样,64 voice < 1% CPU——可承受。但完整的 waveguide(带复杂 bridge 滤波)+ modal(K 个模态)每 voice 可能 50-200 ns,64 voice 是 3-12% CPU,在低端硬件(手机、Switch)上吃紧。**评估目标平台**,不要假设桌面性能。

**代价二:调音极难**。物理参数(张力、损耗系数、阻尼)和**感知**参数(音色亮不亮、衰减长不长)之间的关系**不直观**。给一个 sound designer 一组物理参数,他很难预测会出什么声音。这就是为什么 Yamaha VL1(1993)商业失败——音乐家买了之后,调不出想要的音色,觉得"这是个研究玩具不是乐器"。**解决方法**:在你的引擎里**封装感知参数**(brightness ∈ [0, 1]、sustain ∈ [0, 1]),把物理参数藏在底层,让 sound designer 调感知参数,引擎内部映射到物理参数。

**代价三:某些音色物理建模做不好**。**人声**很难用物理建模——声带 + 声道 + 鼻腔 + 肺的耦合极其复杂,目前没有好的物理模型。**钢琴**也难——一根键按下,三个弦同时振动 + 它们之间的微弱耦合 + dampers 的复杂动力学,Pianoteq 是少数做好的。**多弦乐器**(吉他、小提琴)**单弦建模已经成熟**,但弦之间的耦合(body resonance)是开放问题。

**Hybrid 取舍**。生产中常用 **hybrid 物理 + 采样**:

- **音色 body 用采样**:吉他琴体的共鸣、钢琴音板染色,这些是物理建模难以精确的部分,直接录采样
- **音高响应和表现力用物理建模**:弦本身用 waveguide,提供参数化和连续响应
- **混合器把它们融合**:waveguide 输出 → 卷积(用琴体的 impulse response)→ 最终输出

这种 hybrid 是 Ableton Tension(物理建模弦)、Pianoteq(物理建模钢琴)、Apple's Logic Studio Instruments 的事实做法。**对你自己的游戏**,**简单的 Karplus-Strong + 一点采样染色已经足够好**——不需要追求 Yamaha VL1 的复杂度。

## 9 · 在你 HH 项目里动手(做中学红线)

理论够了。现在你在 HH 项目里加一个**可交互调参的 Karplus-Strong 弦乐器**。这是你第一个物理模型。**目标**:用鼠标在屏幕上"拨弦"——鼠标 X 改变拨弦位置(音色),鼠标 Y 改变音高(弦长),按下时长改变拨弦力度。每一下"拨"都得到独特的弦音,响应连续。

新建一个 binary crate(`cargo new --bin hh-karplus`),`Cargo.toml` 加 `cpal = "0.15"`,release profile 用 `opt-level = 3`、`lto = "fat"`、`codegen-units = 1`。把 §3.3 的 `KarplusStrong` 和 §3.4 的 `pluck_shape` 复制到 `src/dsp.rs`(把 `xorshift32` 提到模块级别)。

**多弦复音 wrapper**。一个 voice 对应一根弦,所有 voice 共享一个 mixer:

```rust
// src/voice.rs
use crate::dsp::KarplusStrong;

pub struct StringVoice {
    pub string: KarplusStrong,
    pub active: bool,
    pub age_samples: u32,
}

impl StringVoice {
    pub fn new(sample_rate: f32) -> Self {
        StringVoice {
            string: KarplusStrong::new(220.0, sample_rate),
            active: false, age_samples: 0,
        }
    }

    /// 触发这根弦。freq 音高,pluck_pos 拨弦位置 [0, 1),intensity 力度 [0, 1]。
    pub fn trigger(&mut self, freq: f32, pluck_pos: f32, intensity: f32, sample_rate: f32) {
        self.string = KarplusStrong::new(freq, sample_rate);
        let n = self.string.buffer.len();
        let width = 0.1 + intensity * 0.1;
        let mut shape = crate::dsp::pluck_shape(n, pluck_pos, width);
        for s in &mut shape { *s *= intensity; }
        self.string.excite_with(&shape);
        self.active = true;
        self.age_samples = 0;
    }

    pub fn process(&mut self) -> f32 {
        if !self.active { return 0.0; }
        let y = self.string.process();
        self.age_samples += 1;
        // 静音判定:输出幅度 < 阈值持续 100 ms
        if y.abs() < 1e-4 && self.age_samples > 4410 { self.active = false; }
        y
    }
}
```

**主循环 + cpal 输出**(骨架,完整 callback 模板见 [synthesis-and-instruments](synthesis-and-instruments.md) §12):

```rust
// src/main.rs
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use std::sync::{Arc, Mutex};
mod dsp; mod voice;
use voice::StringVoice;

pub struct StringSynth {
    pub voices: Vec<StringVoice>,
    pub sample_rate: f32,
}

impl StringSynth {
    pub fn new(num_voices: usize, sr: f32) -> Self {
        let voices = (0..num_voices).map(|_| StringVoice::new(sr)).collect();
        StringSynth { voices, sample_rate: sr }
    }
    pub fn trigger(&mut self, freq: f32, pluck_pos: f32, intensity: f32) {
        let sr = self.sample_rate;
        // 找空闲 voice,voice stealing 用最老的
        let voice = self.voices.iter_mut().find(|v| !v.active)
            .or_else(|| self.voices.iter_mut().min_by_key(|v| v.age_samples)).unwrap();
        voice.trigger(freq, pluck_pos, intensity, sr);
    }
    pub fn render(&mut self, output: &mut [f32]) {
        for sample in output.iter_mut() {
            let mut sum = 0.0_f32;
            for v in &mut self.voices { if v.active { sum += v.process(); } }
            *sample = sum.tanh() * 0.5;
        }
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let host = cpal::default_host();
    let device = host.default_output_device().ok_or("no output device")?;
    let config: cpal::StreamConfig = device.default_output_config()?.into();
    let sr = config.sample_rate.0 as f32;

    let synth = Arc::new(Mutex::new(StringSynth::new(8, sr)));
    let synth_audio = synth.clone();

    // 五声音阶 A minor pentatonic: A C D E G
    // 每个音用不同拨弦位置——听音色差异
    let freqs = [220.0_f32, 261.63, 293.66, 329.63, 392.0];
    let pluck_positions = [0.5_f32, 0.3, 0.4, 0.2, 0.45];
    let intensities = [0.5_f32, 0.8, 0.6, 1.0, 0.7];
    let mut step = 0usize;
    let mut last_trigger = std::time::Instant::now();

    let stream = device.build_output_stream(
        &config,
        move |out: &mut [f32], _: &cpal::OutputCallbackInfo| {
            if last_trigger.elapsed() > std::time::Duration::from_millis(600) {
                let mut s = synth_audio.lock().unwrap();
                s.trigger(freqs[step], pluck_positions[step], intensities[step]);
                step = (step + 1) % freqs.len();
                last_trigger = std::time::Instant::now();
            }
            synth_audio.lock().unwrap().render(out);
        },
        |err| eprintln!("audio err: {}", err),
        None,
    )?;
    stream.play()?;
    println!("Karplus-Strong demo. 注意拨弦位置不同 → 音色不同(中央柔和 / 端点亮)。");
    std::thread::sleep(std::time::Duration::from_secs(15));
    Ok(())
}
```

跑 `cargo run --release`,你会听到五个弦音,**音色明显不同**——这是物理建模"参数 → 自然音色变化"的第一次直接体验。

**扩展一:接真实鼠标**。用 `winit` 或 `gilrs` 接鼠标事件,X 归一化到拨弦位置,Y 映射到音高,按下时长映射到力度,在事件回调里调 `synth.trigger(...)`。

**扩展二:FFT 可视化**。集成 [fft-and-spectral-analysis](fft-and-spectral-analysis.md) 的代码,实时显示弦音频谱。你会看到 Karplus-Strong 的谐波系列(基频 + 整数倍谐波),并看到"拨中央"时偶次谐波弱、"拨端点"时偶次谐波强——**这是物理建模的物理意义,频谱可视化让你直接看到**。

**扩展三:加 modal bell**。在 `StringVoice` 旁加 `BarVoice`(用 §5.2 的代码),随机化钟的模态参数,做出"每个房间一个不同的钟"的效果。这就是 [synthesis-and-instruments](synthesis-and-instruments.md) 练习 6 的物理建模版本——比 FM bell 更真实,因为模态是从真实钟的物理参数来的。

做完这个练习,你拥有:**一个能响应交互输入的物理建模弦乐器,集成在 HH 项目的音频系统里**。这是合成器从"波形塑形"走向"乐器模拟"的关键一步。把它放在游戏世界的"魔法竖琴"位置——玩家拖动鼠标调拨弦位置,听到音色连续变化,这种交互的细腻是采样无法提供的。

## 10 · 练习

**Lv1**:跑通 §9 的最小 Karplus-Strong 项目,听到五个不同音色的弦音。修改 `freqs` 数组为你喜欢的旋律,确认音色跟随拨弦位置变化。

**Lv2**:在 §9 的项目里加入实时参数控制。绑定三个键盘键:↑/↓ 调 brightness(0.1 到 1.0,步长 0.05),←/→ 调 decay(0.95 到 0.999)。听 brightness 调节时弦的"亮度"如何变化,decay 调节时衰减时长如何变化。**这是物理参数 → 感知参数的第一次映射练习**。

**Lv3**:实现一个 modal synthesis 的钟,参数随机化。每个钟生成时:基础频率 f ∈ [200, 800] Hz 随机,模态比在 [(1.0, 2.0, 2.4, 3.0, 4.5), (1.0, 2.0, 2.7, 4.2, 5.8)] 之间随机插值。把 10 个不同的钟放进游戏的 procedural 房间,玩家进入房间时触发对应的钟声。**这是 procedural 音效生成的真实场景**。

**Lv4**(挑战):实现一个完整的 waveguide string(用 §4.3 的代码),带可调 bridge 反射滤波器。然后把 waveguide string 和 modal synthesis **混合**:waveguide 弦 + 一组共鸣模态(模拟琴体共鸣),输出 = waveguide 输出 + modal 输出 × 0.3。这就是 hybrid 物理 + 模态的实际做法。在 FFT 可视化里对比"纯 waveguide" vs "hybrid"的频谱差异——hybrid 应该有更丰富的低频共鸣(模拟琴体)。

## 11 · 延伸阅读

本仓库本地资料:

- [phase-0/22-signals-foundation.md](../../phase-0/22-signals-foundation.md) — 信号基础(LTI、卷积、Z 变换的物理基础)
- [phase-5/deep-dives/dsp-fundamentals.md](dsp-fundamentals.md) — DSP 基础(滤波器实现,这一篇大量用到 OnePoleLPF)
- [phase-5/deep-dives/synthesis-and-instruments.md](synthesis-and-instruments.md) — 声音合成与乐器(Karplus-Strong 初识、subtractive、FM、wavetable 的全景)
- [phase-5/deep-dives/fft-and-spectral-analysis.md](fft-and-spectral-analysis.md) — FFT 和频谱分析(用 FFT 提取模态参数,可视化 Karplus-Strong 谐波)
- [phase-5/deep-dives/audio-effects.md](audio-effects.md) — 音频效果(reverb、compressor,物理建模输出常经过这些后处理)

外部稳定 URL:

- **Julius O. Smith III, *Physical Audio Signal Processing***(在线,waveguide 圣经,Stanford CCRMA):https://ccrma.stanford.edu/~jos/pasp/
- **Smith, *Introduction to Digital Filters***(在线,滤波器设计与 waveguide 反射滤波):https://ccrma.stanford.edu/~jos/filters/
- **Karplus & Strong 1983, "Digital Synthesis of Plucked-String and Drum Timbres"**(*Computer Music Journal*):https://www.cs.cmu.edu/~music/music.psp/KarplusStrong.pdf
- **Smith 1985, "A New Approach to Digital Reverberation using Closed Form Reflection Filters"**(waveguide 早期论文):https://ccrma.stanford.edu/~jos/pasp/
- **Cadoz, Luciani, Florens 1993, "CORDIS-ANIMA: a Modeling and Simulation System for Sound and Image Synthesis"**(mass-spring 模型):https://doi.org/10.1162/comj.17.1.29
- **Cook 2002, *Real Sound Synthesis for Interactive Applications***(AK Peters,游戏向物理建模):https://www.routledge.com/Real-Sound-Synthesis-for-Interactive-Applications/Cook/p/book/9781568811688
- **Pirkle, *Designing Software Synthesizer Plug-Ins in C++***(含 waveguide 和 modal 章节,JUCE 实现):https://www.routledge.com/Designing-Software-Synthesizer-Plug-Ins-in-C-with-Audio-DSP/Pirkle/p/book/9781138583931
- **Modartt Pianoteq**(商业物理建模钢琴,可以直接听和对比采样):https://www.modartt.com/
- **Yamaha VL1**(1993 第一个商用 waveguide 物理建模合成器,历史意义):https://www.yamaha.com/

真实开源源码:

- **STK (Synthesis ToolKit in C++)**(Stanford CCRMA,Perry Cook 维护,包含 waveguide、modal、Karplus-Strong 的教学实现):https://github.com/thestk/stk
- **megrid**(Rust modal synthesizer,这一篇 §5 的灵感来源):https://github.com/Argrath/megrid
- **fundsp**(Rust DSP 框架,可以用它快速搭 waveguide 链):https://github.com/SamiPerttu/fundsp
- **ZynAddSubFX**(open source,含 ADnote 谐波 + 物理建模混合引擎):https://github.com/zynaddsubfx/zynaddsubfx

历史演化:

- **1747 d'Alembert** 一维波动方程的通解(双反向行波)——整个 waveguide 合成的数学起点
- **1866 Helmholtz** *On the Sensations of Tone*——模态 / 谐波理论的物理基础
- **1983 Karplus & Strong** 算法(20 行做出弦)
- **1985 Julius Smith** 系统化 digital waveguide 理论(Stanford)
- **1993 Yamaha VL1** 第一个商用 waveguide 合成器(商业失败,学术成功)
- **1996 Claude Cadoz** GENESIS mass-spring 系统(物理 sandbox 乐器)
- **2000s Modartt Pianoteq** 物理建模钢琴,商业成功
- **2010s Ableton Tension / Collision** 物理建模乐器进入主流 DAW
- **2020s** 物理建模 + 神经网络混合(Meta RAVE、Google DDSP,用 NN 学习物理参数)
