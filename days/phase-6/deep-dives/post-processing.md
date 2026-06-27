# 后处理全景:从 HDR 到 Tone Mapping、Bloom、DOF、Motion Blur 与 Color Grading

> 你跑通了 PBR,光照看起来不错。但你截一张图和电影比,差着"那一层东西"。原因之一:你把每帧渲染的 RGB 直接写进了 LDR(0~1)的 swapchain,而你 GPU 内部计算的光照强度其实可以到 10、50、甚至 1000——它们被默默 clamp 成 1.0,所有高光细节都炸成一片纯白。原因之二:你完全没有任何"摄影机感"——没有 bloom 的高光晕染、没有 DOF 的远近虚实、没有 motion blur 的运动模糊、没有 color grading 的电影色调。今天的主题**post-processing**(后处理)就是把渲染管线最后一道关——拿一张 HDR 图像,经过几十个 2D 滤波 pass,把它变成一张"看起来像电影"的画面。本文从信号处理的卷积定理讲起,推到 Reinhard / ACES / Uchimura tone mapping 的数学曲线,从高斯金字塔推到 Karnis bloom,从 Circle of Confusion 推到散景 DOF,最后用 Rust + glow + GLSL 写一个能跑的 mini post-process pipeline,让你看懂 Unreal PostProcess、Unity URP Post Processing、Godot 4 PostProcess、Bevy 的 source code。

## 0 · 为什么要有 post-processing

让我们把镜头拉近,看看一个"没有 post-processing"的游戏画面长什么样。你的渲染管线是这样的:

```
游戏几何体 → 顶点着色 → 片段着色(PBR + 光照)→ 写 swapchain → 显示
```

最后一步"写 swapchain"意味着你把每个像素的 RGB 写到 framebuffer,然后操作系统的 compositor 把它显示出来。看起来正常,但有四个致命问题:

**问题一:dynamic range 不够**。你的 framebuffer 格式大概率是 `R8G8B8A8_UNORM`——每个 channel 8 bit,范围严格在 [0,1]。但真实世界的光照强度跨度极大:阳光直射的高光可以到 100,000 lux,室内阴影可能只有 50 lux——比值 2000:1。8-bit 装不下这种动态范围。结果:你 PBR 算出来的"255 的镜面高光"被 clamp 成 1.0,高光完全过曝,所有亮处都炸成纯白,没有任何细节。

**问题二:颜色线性空间错误**。8-bit 的 0.5 在显示器上**不是** 50% 亮度。显示器有 gamma 曲线(sRGB),输入 0.5 实际显示大约 21.4% 亮度。如果你直接把线性空间的计算结果写到 swapchain,画面整体偏暗、对比度错。post-processing pipeline 的最后一步要做"gamma correction",把线性转回 sRGB,这一步通常和 tone mapping 合并。

**问题三:缺少电影感**。真实摄影机镜头有"瑕疵":高光会晕开(bloom)、远处会模糊(DOF)、快速移动会拖影(motion blur)、边缘会变暗(vignette)、波长折射率不同导致颜色分离(chromatic aberration)、胶片颗粒(film grain)、镜头畸变(lens distortion)。**这些瑕疵恰恰是"电影感"的来源**——你看到一张照片就知道它是拍的,因为镜头有这些物理特性。游戏画面太"干净"反而显得假。post-processing 就是把这些瑕疵**故意加回去**。

**问题四:风格化需求**。同一个游戏,你想做"冷色赛博朋克"、"暖色怀旧日式"、"高对比度黑色电影"(film noir),每种风格需要不同的色调曲线。Color grading(调色)是 post-processing 的核心 pass,让你在画面成型后用一张 3D LUT 改变整体色调,而不用重渲染。

**post-processing 给出系统化解决方案**。核心思路:**在 PBR 之后、显示之前,加一个"中间缓冲区"(post-process buffer),在它上面跑一连串 2D 滤波 pass,每个 pass 做一件事**(tone mapping、bloom、DOF、color grading...),最后输出到 swapchain。

2010 年代后期,这套管线成为业界标准:Unreal 的 PostProcessVolume、Unity URP 的 Volume、Godot 4 的 WorldEnvironment、Bevy 的 PostProcessing 全部基于这个范式。

**读完这一篇你能**:

- 解释为什么 LDR pipeline 已死,HDR pipeline 是现代标配
- 推导 Reinhard / Filmic / ACES / Uchimura tone mapping 的数学曲线,知道为什么 ACES 是工业标准
- 解释 luminance / histogram auto-exposure 的工程权衡
- 实现 separable blur 的 Gaussian bloom,理解为什么要用 downsample pyramid
- 解释 Circle of Confusion 的光学原理,区分 scatter vs gather DOF
- 实现 velocity buffer 驱动的 motion blur
- 区分 1D LUT / 3D LUT / shaper LUT,知道为什么电影调色用 3D LUT
- 用 Rust + glow 写一个能跑的 mini post-process pipeline,集成到 HH 项目
- 看 Unreal / Unity / Godot / Bevy 的 post-process 源码不被吓到

## 1 · HDR pipeline 全景:为什么 LDR 已死

先回答最根本的问题:**为什么不直接渲染到 LDR swapchain,而要先渲染到 HDR 中间 buffer 再处理?**

### 1.1 LDR pipeline 的死亡

LDR(Low Dynamic Range)指的是 pixel 值范围严格在 [0,1] 的图像格式,典型是 `R8G8B8A8_UNORM`(每个 channel 8 bit)。早期 OpenGL / Direct3D 的默认 framebuffer 就是 LDR。LDR pipeline 是:

```
顶点着色 → 片段着色(算光照,clamp 到 [0,1])→ 写 LDR swapchain → 显示
```

这套 pipeline 看起来简单,但有一个致命问题:**所有光照计算结果在写 swapchain 之前就被 clamp 了**。一个像素的光照计算结果是 (3.5, 2.1, 0.8)——一个很亮的高光,8-bit framebuffer 把它 clamp 成 (1.0, 1.0, 0.8)。**信息丢失了**。后续你没法区分"原始 3.5"和"原始 1.5",因为它们都变成了 1.0。

这导致几个具体问题:

- **高光区域无细节**。所有亮处都炸成白色,看不清反光的纹理。
- **bloom 无法实现**。bloom 需要"提取亮度大于阈值的部分",但 LDR 里没有大于 1 的部分,所以提取不到。
- **tone mapping 无意义**。tone mapping 是把 HDR(>1)压缩到 LDR(0~1),LDR 已经在 [0,1] 里了,再 tone map 是空操作。
- **多次叠加失真**。光照叠加(光 1 + 光 2 + 光 3)在 clamp 后做加法——如果三个光都到了 1.0,1.0 + 1.0 + 1.0 = 3.0,clamp 后还是 1.0,无法区分三种光的相对强度。

2000 年代游戏都是 LDR,所以光照看起来"平"——所有亮处都同样亮,所有暗处都同样暗。这就是为什么 Half-Life 2、Doom 3 时代的画面感觉"扁"。

### 1.2 HDR pipeline 的崛起

HDR(High Dynamic Range)指的是 pixel 值范围远超 [0,1] 的图像格式,典型是 `R16G16B16A16_SFLOAT`(每 channel 16 bit float,范围最大 ~65504)。HDR pipeline:

```
顶点着色 → 片段着色(算光照,允许 > 1)→ 写 HDR 中间 buffer(16-bit float)
   → post-processing(tone map、bloom、DOF、color grading...)
   → 写 LDR swapchain(8-bit)→ 显示
```

关键变化:**光照计算结果**保留在 float buffer 里,**post-processing 在 HDR 域做**,**只在最后一步才 tone map 到 LDR 显示**。

这带来的能力:

- **bloom 可行**:HDR buffer 里有大量 > 1 的像素,bloom pass 提取它们,做模糊,叠加回去。
- **tone mapping 有意义**:把 0~100 的 HDR 压缩到 0~1 LDR,曲线决定压缩方式。
- **物理光照单位**:light 用 candela / lux / lumen(物理单位),数值可以到几千几万,计算时不 clamp。
- **多次叠加精确**:float 精度足够,光照叠加精确。
- **auto-exposure 可行**:测量当前 HDR buffer 的平均亮度,动态调整 exposure。

2006 年 Valve 在 Half-Life 2: Lost Coast 第一次在游戏里演示 HDR(那次"Lost Coast"技术 demo 主要是 HDR showcase)。2007 年 Crysis 大规模用 HDR。2010 年代后,HDR pipeline 是 3A 游戏标配。今天 Unreal、Unity、Godot、Bevy 全部默认 HDR。

### 1.3 格式选择

实际工程里,HDR buffer 用什么格式?有几个选择,各有权衡:

| 格式 | 每 channel bit | 字节数/像素 | 范围 | 精度 | 用途 |
|---|---|---|---|---|---|
| `R8G8B8A8_UNORM` | 8 | 4 | [0,1] | 低 | LDR swapchain、UI |
| `R10G10B10A2_UNORM` | 10 | 4 | [0,1] | 中低 | HDR swapchain(显示器 10-bit) |
| `R11G11B10_FLOAT` | 11/11/10 | 4 | [0, +∞) | 中 | HDR 中间 buffer(精度换体积) |
| `R16G16B16A16_SFLOAT` | 16 | 8 | ±65504 | 高 | HDR 中间 buffer(主力) |
| `R32G32B32A32_SFLOAT` | 32 | 16 | ±10^38 | 极高 | 计算 buffer(几乎不用) |

主流选择是 `R16G16B16A16_SFLOAT`(简称 RGBA16F)。8 字节/像素,精度足够(11 bit mantissa,比 RGBA8 的 8 bit 强 8 倍),范围足够(±65504 覆盖几乎所有光照场景)。

`R11G11B10_FLOAT`(简称 R11G11B10F)更省,4 字节/像素,但 alpha 通道只有 2 bit(实际就是没 alpha),并且 R/G 的精度只有 11 bit,B 只有 10 bit——做高动态 bloom 时可能有 banding 伪影。

### 1.4 完整的 HDR pipeline

工业级 HDR pipeline 长这样:

```
G-buffer(geometry pass)  → 位置、法线、反照率、材质参数
  ↓
Lighting pass  → 算 PBR 光照,写 HDR color buffer(16F)
  ↓
[可选] SSAO / SSR  → 屏幕空间环境光遮蔽、屏幕空间反射(都在 HDR)
  ↓
[可选] Volumetric fog / atmosphere  → 大气散射(在 HDR)
  ↓
[可选] Motion vectors velocity buffer  → 给 motion blur / TAA 用
  ↓
[可选] Depth of field  → 散景模糊(HDR)
  ↓
Bloom  → 高光提取 + 高斯金字塔 + 合成(HDR)
  ↓
Auto-exposure  → 计算平均亮度,生成 exposure 值
  ↓
Exposure + Tone mapping  → HDR * exposure → ACES → LDR
  ↓
Color grading (3D LUT)  → 调色(LDR)
  ↓
[可选] Vignette / Chromatic aberration / Film grain / Lens distortion  → 镜头瑕疵(LDR)
  ↓
Gamma / sRGB OETF  → 线性 → sRGB(8-bit swapchain)
  ↓
Display
```

后面几节我会逐个 pass 拆开讲。先记住关键点:**所有光照相关计算在 HDR 域,color grading 和镜头瑕疵在 LDR 域**(因为它们是人造风格化效果,不依赖物理光照)。

## 2 · Tone mapping:从 Reinhard 到 ACES 的完整推导

Tone mapping 是 post-processing 的灵魂。它做的事:**把 HDR(0~∞)的像素值,通过一条非线性曲线,压缩到 LDR(0~1)的像素值**,保留视觉上的高光细节和暗部细节。

### 2.1 为什么不能线性压缩

最 naive 的方案:`output = input / max_input`,线性映射。听起来合理,实际是灾难。

假设场景里最亮的像素是 100(太阳)。线性映射:`output = input / 100`。一个室内物体亮度 0.5,映射后 = 0.005——**几乎纯黑**。一个室内物体的真实亮度,在画面里看不见。

为什么?因为人眼对亮度的感知是**对数**的(Weber-Fechner 定律)。从 0.005 到 0.01 的视觉差异,人眼感觉和从 0.5 到 1.0 一样(都是"翻一倍")。线性压缩把暗部信息全压没了。

tone mapping 的核心:**用一条感知均匀的曲线压缩**,让暗部细节保留、亮部细节(高光)也保留、中段对比度合适。

### 2.2 Reinhard tone mapping(2002)

Erik Reinhard 在 2002 年的论文"Photographic Tone Reproduction for Digital Images"提出了一条简洁曲线:

```
output = input / (input + 1)
```

推导:

```
input = 0   → output = 0
input = 0.5 → output = 0.333
input = 1   → output = 0.5
input = 4   → output = 0.8
input = 10  → output = 0.909
input = ∞   → output = 1
```

这条曲线有几个优点:

- **单调递增**(input 越大 output 越大,顺序对)
- **永远 < 1**(不需要 clamp,自然收敛)
- **暗部近似线性**(input 很小时 `input / (input+1) ≈ input`,中段开始压缩)
- **亮部收敛到 1**(不会爆白,但保留了"越来越接近 1"的渐变信息)

GLSL 实现:

```glsl
vec3 reinhard(vec3 hdr) {
    return hdr / (hdr + vec3(1.0));
}
```

但 Reinhard 有两个问题:

**问题一:亮部对比度不够**。input = 10 → output = 0.909;input = 50 → output = 0.980。50 倍亮度差在 output 上只差 0.07,高光区域看不出层次。

**问题二:暗部偏灰**。output 中段(0.4~0.6)覆盖的 input 范围太宽,导致中段对比度也偏低,画面整体看起来"雾蒙蒙"。

### 2.3 Filmic tone mapping(Unreal 2010)

2010 年 Triumph Studios 的 Natalya Tatarchuk 在 GDC 演讲"Uncharted 2: HDR Lighting"(后来被 Unreal 4 采用),提出了一条电影摄影机胶片模拟曲线。

首先,人观察大量 film 数据,发现真实胶片的响应曲线(用 log-log 坐标)大致是一条 **S 形曲线**(sigmoid)。Reinhard 是单边收敛,而 sigmoid 是双边都收敛——暗部收敛到 0,亮部收敛到 1,中段斜率高(对比度强)。

Naughty Dog 的 John Hable 把这条曲线用一个**有理函数**(rational function,多项式之比)拟合:

```
f(x) = (x * (A*x + C*B) + D*E) / (x * (A*x + B) + D*F)
```

其中 A~F 是拟合参数,Naughty Dog 用的:
- A = 0.15 (shoulder strength)
- B = 0.50 (linear strength)
- C = 0.10 (linear angle)
- D = 0.20 (toe strength)
- E = 0.02 (toe numerator)
- F = 0.30 (toe denominator)

GLSL 实现:

```glsl
vec3 filmic_uncharted(vec3 x) {
    const float A = 0.15;
    const float B = 0.50;
    const float C = 0.10;
    const float D = 0.20;
    const float E = 0.02;
    const float F = 0.30;
    return ((x*(A*x+C*B)+D*E)/(x*(A*x+B)+D*F)) - E/F;
}

vec3 filmic(vec3 hdr) {
    vec3 exposed = hdr * 2.0;  // exposure bias
    vec3 curr = filmic_uncharted(exposed);
    vec3 white_scale = vec3(1.0) / filmic_uncharted(vec3(11.2));
    return curr * white_scale;
}
```

关键点:**white_scale 是为了把"白点"(最亮显示成纯白的输入值)固定在 11.4**——任何大于 11.4 的输入都映射到 1.0。这是电影摄影机胶片的标准白点。

Filmic 的优点:**亮部对比度比 Reinhard 强**(sigmoid 中段陡),**整体色彩感觉"电影感"**。

### 2.4 ACES tone mapping(2017+,工业标准)

2017 年起,业界大量采用 **ACES**(Academy Color Encoding System)的近似曲线。ACES 是奥斯卡标准委员会(The Academy)制定的色彩管理标准,本意是用于电影后期调色。游戏界发现它的 tone map 曲线特别适合实时渲染。

ACES 的完整公式很复杂(涉及 12 个步骤的颜色空间变换),但 Narkowicz 2016 年的论文"ACES Filmic Tone Mapping Curve"提出了一个简化拟合:

```
f(x) = (x * (2.51*x + 0.03)) / (x * (2.43*x + 0.59) + 0.14)
```

GLSL:

```glsl
vec3 aces_narkowicz(vec3 x) {
    const float a = 2.51;
    const float b = 0.03;
    const float c = 2.43;
    const float d = 0.59;
    const float e = 0.14;
    return clamp((x*(a*x+b))/(x*(c*x+d)+e), 0.0, 1.0);
}
```

为什么 ACES 比 Filmic 强?

- **更高对比度**:曲线中段更陡,亮部肩部更明显。
- **更好的颜色一致性**:ACES 设计考虑了 chroma(色彩)在不同亮度下的退化,Filmic 没考虑。
- **行业标准**:电影调色师都用 ACES,游戏匹配 ACES 就和电影后期 pipeline 兼容。
- **HDR 显示器友好**:ACES 曲线对 1000 nit / 4000 nit / 10000 nit 的 HDR 显示器都有合理的扩展。

今天 Unreal 5、Unity HDRP、Godot 4、Bevy 都默认 ACES 或 ACES 近似。

### 2.5 Uchimura tone mapping(2017)

Hajime Uchimura(日本图形程序员)提出一条曝光和对比度都可调的 tone mapper:

```
struct UchimuraParams {
    float max_brightness;  // 最大亮度,通常 1.0
    float contrast;        // 对比度,0.5 左右
    float linear_section;  // 线性段起点,0.1 左右
    float black;           // 黑场,0.0
    float pedestal;        // 抬黑,0.0
};

vec3 uchimura(vec3 x, UchimuraParams p) {
    float l0 = ((p.linear_section - p.black) * p.contrast) / p.linear_section;
    float L1 = (1.0 / (p.max_brightness - (1.0 / p.contrast)));
    float S0 = p.black + p.linear_section;
    float S1 = p.max_brightness * p.linear_section + p.pedestal;

    vec3 w0 = 1.0 - smoothstep(0.0, p.linear_section, x);
    vec3 w2 = step(p.linear_section + p.max_brightness, x);
    vec3 w1 = 1.0 - w0 - w2;

    vec3 T = vec3(l0) * x + S0;
    vec3 S = p.max_brightness * x - (p.max_brightness - S1) / (1.0 + L1 * p.max_brightness) + S1;
    vec3 L = p.pedestal + x;

    return T * w0 + L * w1 + S * w2;
}
```

Uchimura 的特点:**有线性段**——中段是线性的(对比度好),只有 shoulder 和 toe 用曲线。这让中段色彩还原准确,适合写实风格。

### 2.6 各 curve 对比

| Tone mapper | 公式 | 优点 | 缺点 | 谁用 |
|---|---|---|---|---|
| **Reinhard** | `x/(x+1)` | 简单,稳定 | 中段偏灰,高光无层次 | 教学用,工业已淘汰 |
| **Filmic (Hable)** | 有理函数 + 拟合参数 | 电影感强,Uncharted 用 | 颜色一致性一般 | Unreal 4 早期、Uncharted 2 |
| **ACES (Narkowicz)** | 有理函数 + ACES 拟合 | 颜色一致,HDR 友好,工业标准 | 略偏红(部分人不喜欢) | Unreal 4.27+、Unity HDRP、Bevy、Godot 4 |
| **Uchimura** | 分段(线性 + shoulder + toe) | 中段色彩准确 | 参数多,调参难 | Halo、个性化项目 |
| **Khodachenko** | 优化版 ACES | 蓝色通道修正 | 实现复杂 | 一些 AAA |

工业实践:**默认 ACES**。除非你有强烈的色彩准确需求(医疗影像、建筑可视化)或强烈风格化(卡通、像素艺术),否则 ACES 是无脑选择。

## 3 · Exposure:让玩家看得见

Tone mapping 把 HDR 压缩到 LDR,但**压缩的"中心点"在哪?**——这由 exposure 决定。

### 3.1 Exposure 的物理意义

摄影里的 exposure(曝光)就是**进光量**。光圈大、快门慢、ISO 高 → exposure 大 → 画面亮。游戏里没有真实光圈,但我们模拟这个概念:**给 HDR 像素值乘一个 exposure 系数,然后 tone map**。

```
final_pixel = tone_map(hdr_pixel * exposure)
```

exposure 大 → hdr_pixel 被放大 → tone map 后整体更亮。
exposure 小 → hdr_pixel 被缩小 → tone map 后整体更暗。

关键问题:**exposure 怎么决定?**

### 3.2 三种 exposure 策略

**手动 exposure**。开发者写死一个值,比如 `exposure = 1.5`。优点:简单,可控。缺点:玩家从室内走到室外,室内合适的话室外过曝,室外合适的话室内太暗。早期游戏大量用手动,比如 Half-Life 2。

**Auto-exposure(基于平均亮度)**。每帧测量 HDR buffer 的平均亮度,根据它调整 exposure——暗的场景 exposure 自动变大,亮的场景 exposure 自动变小。这就是人眼的"暗适应 / 亮适应"机制。今天的标准。

**基于 histogram 的 auto-exposure**。简单平均亮度容易被极端值(几个超亮像素)拉偏。Histogram 方案把像素亮度分布做直方图,取**中位数**(或某个百分位,如 70% 分位)作为参考亮度,避免被极值带偏。Unreal 默认用 histogram 方案。

### 3.3 平均亮度的计算

平均亮度怎么算?数学上:

```
L_avg = exp( average( log(L_pixel + epsilon) ) )
```

为什么用 log 的平均?因为亮度感知是对数的——100 → 200 的差异和 0.1 → 0.2 的差异在感知上一样。直接平均会被几个亮像素拉爆,log 平均让所有像素"权重相近"。

GPU 上计算这个的算法叫 **reduction**:

1. 把 HDR buffer 渲染到一张 1/16 分辨率的 buffer(reduce 16x)。
2. 把那张 buffer 再 reduce 到 1/16(累计 1/256)。
3. 继续直到 1x1 像素——这一个像素就是平均亮度。
4. 对那张 1x1 buffer 做 exp,得到 L_avg。

伪代码:

```glsl
// reduce shader(把 N x N 缩到 1 x 1)
vec3 reduce_4x4(sampler2D src, vec2 uv) {
    vec3 sum = vec3(0.0);
    for (int y = 0; y < 4; y++) {
        for (int x = 0; x < 4; x++) {
            vec3 c = texture(src, uv + vec2(x, y) * texel_size).rgb;
            sum += log(c + vec3(0.00001));
        }
    }
    return sum / 16.0;
}
```

### 3.4 Exposure 计算

有了 L_avg,怎么算 exposure?Reinhard 论文给出:

```
exposure = key_value / L_avg
```

key_value 是"摄影师设定的曝光偏好",通常 0.18(反射率为 18% 灰的中性灰)。

然后做平滑(否则会闪烁):

```
exposure_smoothed = lerp(exposure_smoothed, exposure_target, adaptation_rate * dt)
```

adaptation_rate 控制适应速度——人眼暗适应需要几分钟,游戏里我们加速到 1-3 秒。

GLSL:

```glsl
uniform float u_exposure;  // 从 CPU 传来(CPU 维护 smoothed 值)

vec3 apply_exposure(vec3 hdr) {
    return hdr * u_exposure;
}
```

### 3.5 Histogram-based auto-exposure

Unreal 的 histogram exposure:

1. 把 HDR buffer reduce 到一张 64x64 的亮度直方图(64 个 bin)。
2. 计算 70% 百分位(80% 太亮,60% 太暗,70% 经验值)。
3. 用这个百分位亮度做 exposure。

优点:不被少数超亮像素(太阳、爆炸)拉偏。
缺点:GPU 上算百分位开销大,需要 compute shader + shared memory + sort。

工业实现:Unreal 用 compute shader 算 histogram,每帧 ~0.2ms(1080p)。Unity URP 用更简单的 reduction,稍微快但精度差。

## 4 · Bloom:高光晕染

Bloom 是最显眼的 post-process 效果——所有亮物周围一圈柔和光晕。原理听起来朴素(提取亮部 → 模糊 → 叠加),但实现起来坑很多,涉及信号处理的卷积分离技巧、金字塔降采样、性能与质量的精细权衡。

### 4.1 直觉:为什么有 bloom

摄影机镜头是物理实体,光线通过镜头时:

- 鎬片(aperture)边缘会衍射光线。
- 镜片之间会有内部反射(ghost / flare)。
- 灰尘和指纹会散射光。

这些散射让"亮像素"的光溢出到周围像素——亮像素越大,溢出越远。这就是 bloom 的物理来源。

游戏里我们模拟这个:**提取亮度大于阈值(比如 1.0)的像素,做高斯模糊,叠加回去**。

### 4.2 Naive bloom(错)

最 naive 的 bloom:

```glsl
// 提取亮部
vec3 bright_pass = max(hdr - 1.0, 0.0);
// 模糊(blur kernel = 5x5 高斯)
vec3 blurred = gaussian_blur_5x5(bright_pass);
// 叠加回去
vec3 result = hdr + blurred * intensity;
```

这个实现看起来对,实际不行:

**问题一:5x5 高斯太小**。真实 bloom 应该扩散到几十像素(大光晕),5x5 只覆盖 2-3 像素,根本看不出效果。
**问题二:大高斯 kernel 性能差**。21x21 高斯 = 441 次纹理采样 per pixel,1080p 下 200 万像素 * 441 = 9 亿次采样,完全跑不动。

### 4.3 Separable Gaussian Blur

第一个优化:高斯核是**可分离的**(separable)。一个 2D 高斯核 `G(x,y) = G(x) * G(y)`,所以可以先按 X 方向做 1D 卷积,再按 Y 方向做 1D 卷积,结果完全一样,但采样从 N² 降到 2N。

```
2D 高斯:21x21 = 441 采样
Separable:21 + 21 = 42 采样  ← 10 倍加速
```

数学证明:

```
G_2D(x, y) = (1 / (2π σ²)) * exp(-(x² + y²) / (2σ²))
           = exp(-x²/(2σ²)) * exp(-y²/(2σ²)) * (1 / (2π σ²))
           = G_1D(x) * G_1D(y)   (相差一个常数,可以归一)
```

所以 2D 卷积可以分解为两个 1D 卷积的级联。

GLSL(pass 1, 水平 blur):

```glsl
uniform sampler2D u_input;
uniform vec2 u_texel_size;
uniform int u_kernel_size;  // 比如 21

out vec3 frag_color;

void main() {
    vec3 sum = vec3(0.0);
    float total_weight = 0.0;
    float sigma = float(u_kernel_size) / 6.0;
    
    for (int i = -u_kernel_size/2; i <= u_kernel_size/2; i++) {
        float x = float(i);
        float weight = exp(-x*x / (2.0 * sigma * sigma));
        vec2 offset = vec2(float(i) * u_texel_size.x, 0.0);
        sum += texture(u_input, v_uv + offset).rgb * weight;
        total_weight += weight;
    }
    
    frag_color = sum / total_weight;
}
```

pass 2(垂直 blur)就是把 `vec2(float(i) * u_texel_size.x, 0.0)` 换成 `vec2(0.0, float(i) * u_texel_size.y)`。

### 4.4 Downsample Pyramid:解决大 kernel

第二个优化:用 downsample pyramid。

要做 64 像素半径的 bloom,21x21 kernel 不够(扩散 10 像素左右)。要做 64 像素半径,需要 129x129 kernel,即使 separable 也是 258 采样,太慢。

**解法:把图缩小,在小图上做 blur,再放大**。

具体步骤:

1. 把 HDR buffer downsample 到 1/2 分辨率(540p if 主屏 1080p)。
2. 继续到 1/4(270p)。
3. 继续到 1/8(135p)。
4. 继续到 1/16(67p)。

形成 4 层金字塔。每层做一次 separable blur(13-tap 就够了),最后把每层 blur 结果**累加**回原始分辨率:

```
bloom = upsample(blur_1/2) + upsample(blur_1/4) + upsample(blur_1/8) + upsample(blur_1/16)
```

为什么有效?在小图(1/16)上做 13-tap blur,等价于在原图上做 13 * 16 = 208-tap blur。所以**金字塔让我们用小 kernel 模拟大 kernel**。

Unreal 的 bloom 用 5 个 mip level(叫 Bloom1~Bloom5),每个 mip 都做 separable blur。Unity URP 类似。Godot 4 用 4 个 mip。

GLSL(bloom 合成 pass):

```glsl
uniform sampler2D u_bloom_mip0;  // 1/2
uniform sampler2D u_bloom_mip1;  // 1/4
uniform sampler2D u_bloom_mip2;  // 1/8
uniform sampler2D u_bloom_mip3;  // 1/16

out vec3 frag_color;

void main() {
    vec3 bloom = vec3(0.0);
    bloom += texture(u_bloom_mip0, v_uv).rgb * 0.15;
    bloom += texture(u_bloom_mip1, v_uv).rgb * 0.30;
    bloom += texture(u_bloom_mip2, v_uv).rgb * 0.50;
    bloom += texture(u_bloom_mip3, v_uv).rgb * 0.80;
    frag_color = bloom;
}
```

每个 mip 的权重不同——大 mip(小半径、清晰光晕)权重小,小 mip(大半径、模糊光晕)权重大。这样形成多层光晕,从近到远渐变。

### 4.5 Karnis Bloom(2014+,现代标准)

Brian Karnis(Sucker Punch,做 Infamous: Second Son)在 SIGGRAPH 2014 提出**高质 bloom**:

1. Downsample 时用 **13-tap 高斯加权 + bilinear**(不是简单 bilinear),保留高频细节。
2. Upsample 时用 **9-tap high-quality filter**(不是 bilinear),避免放大产生 boxy 伪影。
3. 每个 mip 用**不同的 threshold**(高 mip 用更高 threshold,只让超亮像素扩散到很远)。

Karnis bloom 比 Unreal 4 默认 bloom 慢约 30%,但视觉质量显著好——光晕边缘更柔和,没有 boxy 块状感。今天的 Unity HDRP、Unreal 5 Lumen、Bevy 都用 Karnis 或类似方案。

### 4.6 性能数据

| Bloom 方案 | 1080p GPU 耗时 | 质量 | 用谁 |
|---|---|---|---|
| Naive 21x21 | ~6ms | 差 | 无人用 |
| Separable 21-tap | ~1.5ms | 一般 | 移动平台 |
| Pyramid 4 mip + 13-tap | ~0.7ms | 好 | Unreal 4 默认 |
| Karnis pyramid | ~1.0ms | 优秀 | Unreal 5、Unity HDRP |

## 5 · DOF (Depth of Field):散景模糊

DOF 模拟摄影机的焦距效果——焦点处的物体清晰,远近物体模糊。

### 5.1 光学原理:Circle of Confusion

摄影机镜头聚焦一个物体时,它的光锥聚焦到 sensor 上一点——清晰。不在焦距上的物体,光锥聚焦到 sensor 前(或后),sensor 上看到一个圆——**Circle of Confusion (CoC)**。

CoC 半径公式(薄透镜近似):

```
CoC = |aperture * (focus_distance - object_distance) / object_distance|
      * (sensor_distance / focus_distance)
```

简化:CoC 和**光圈大小**(aperture)、**距离焦平面的偏差**(focus_distance - object_distance)成正比。光圈越大、偏离越远,模糊越强。

游戏里我们不模拟真实光圈,但用 CoC 的概念定义每个像素的模糊半径:

```glsl
// 简化的 CoC 计算
float compute_coc(float depth, float focus_distance, float focus_range) {
    return clamp(abs(depth - focus_distance) / focus_range, 0.0, 1.0);
}
```

`focus_distance` 是焦点距离(玩家在看哪),`focus_range` 是焦距范围(多大范围内还清晰)。

### 5.2 Scatter vs Gather

DOF 实现有两种思路:**scatter** 和 **gather**。

**Scatter**(发散):对每个像素,根据它的 CoC,**把它的颜色写到周围 N 个像素**。CoC 越大,写到越多像素。

```glsl
// scatter DOF(伪代码)
for each pixel p:
    coc = compute_coc(p.depth);
    for each neighbor q in coc_radius(p):
        write_to_q(p.color, weight(coc));
```

优点:物理正确(模拟光散开)。缺点:GPU 上 scatter 是噩梦——GPU 的 fragment shader 是"对每个输出像素并行",scatter 是"对每个输入像素",完全反向。需要 unordered access view(UAV)或 imageStore,性能差。

**Gather**(汇聚):对每个输出像素,**采样周围 N 个输入像素**。CoC 越大,采样越多。

```glsl
// gather DOF(伪代码)
for each output pixel q:
    coc_q = compute_coc(q.depth);
    color_sum = 0;
    weight_sum = 0;
    for each input pixel p in radius(coc_q):
        w = weight(coc_q, p.coc);
        color_sum += p.color * w;
        weight_sum += w;
    q.color = color_sum / weight_sum;
```

优点:GPU 友好(标准 texture sampling)。缺点:有半透明排序问题(近处半透明物体应该挡住背景模糊,但 gather 看不见前面)。

工业实践:**gather 主流**(Unreal、Unity、Godot、Bevy 全部 gather)。

### 5.3 Bokeh 散景形状

真实摄影机的散景(as in 焦外的光斑)形状由**光圈叶片数和形状**决定。圆形光圈产生圆形散景,六角形光圈产生六角形散景。

游戏里要模拟这个,常用**bokeh splatting**:

1. 把图像分解为"焦点内"(清晰,直接保留)和"焦点外"(模糊,需要 splat)。
2. 对焦点外像素,根据 CoC 大小,**splat** 一张 bokeh sprite(圆形 / 六角形 / 八角形 sprite texture)到周围。
3. 累加 bokeh sprites 得到最终散景。

这个 splatting 在 GPU 上同样有 scatter 问题,通常用**compute shader + atomic add**或**预先排序的 splat list**实现。Unreal 用 compute shader 实现 bokeh DOF,代价 ~1.5ms(1080p)。

简化版 DOF 直接用大半径高斯模糊(不模拟 bokeh 形状),性能 0.5ms,但散景是"圆形 blob",没有真实光圈感。低端平台常用这种。

### 5.4 多方案权衡

| DOF 方案 | 性能(1080p) | 质量 | 适合 |
|---|---|---|---|
| Simple Gaussian | 0.3ms | 低(没有 bokeh 形状) | 移动端 |
| Separable Gaussian + CoC | 0.5ms | 中(圆形散景) | 独立游戏 |
| Bokeh splatting | 1.5ms | 高(真实光圈形状) | AAA |
| Dual-buffer DOF(分前后景,各自模糊) | 1.0ms | 中高(避免前后景互相泄漏) | Unreal 默认 |

工业坑:**前后景泄漏**。如果近处(焦外)像素和远处(焦外)像素混在一起做模糊,模糊后近处像素会"泄漏"到远处,反之亦然。视觉上看起来"前景模糊的边缘有背景颜色"。解法:**双缓冲 DOF**——把前景和背景分开到两个 buffer,各自模糊,最后合成时**根据 depth 决定哪个 buffer 优先**。

## 6 · Motion Blur:速度模糊

Motion blur 模拟"快速移动的物体在快门时间内拖影"的视觉效果。

### 6.1 为什么需要 motion blur

电影摄影机快门时间 = 1/48 秒(24fps 电影)。物体移动时,快门打开期间它在 sensor 上划过一段轨迹——形成模糊。

游戏没有真实快门,每帧渲染是"瞬时"的。结果:60fps 时快速移动的物体看起来"跳变",视觉上**不连续**。

加 motion blur 后:快速移动物体在画面里"拖影",视觉上更流畅——这是 24fps 电影看起来比 30fps 游戏流畅的原因之一(motion blur 掩盖了帧间隔)。

### 6.2 Velocity Buffer

要做 motion blur,需要知道"每个像素在两帧之间移动了多少"。这由 **velocity buffer** 提供。

velocity buffer 通常在 geometry pass 生成:每个 vertex 算 `current_clip_pos - previous_clip_pos`,作为 velocity attribute 传给 fragment shader,插值后写到 velocity buffer(RG16F 或 RG8)。

每个 vertex 的 velocity 有两种来源:

**Camera motion**(相机移动):即使物体不动,相机一动,屏幕上像素也移动了。velocity = `current_clip - previous_clip`,其中 previous_clip 用**上一帧的 view-projection 矩阵**。

**Object motion**(物体动画):骨骼动画 / 物理移动。velocity = `current_world - previous_world`,转换到 clip space。

Vertex shader 代码:

```glsl
// vertex shader
out vec4 v_curr_clip;
out vec4 v_prev_clip;

void main() {
    vec4 world_pos = model * vec4(in_position, 1.0);
    v_curr_clip = view_proj_curr * world_pos;
    v_prev_clip = view_proj_prev * prev_model * vec4(in_prev_position, 1.0);
    gl_Position = v_curr_clip;
}
```

```glsl
// fragment shader
in vec4 v_curr_clip;
in vec4 v_prev_clip;
out vec2 frag_velocity;

void main() {
    vec2 curr_ndc = v_curr_clip.xy / v_curr_clip.w;
    vec2 prev_ndc = v_prev_clip.xy / v_prev_clip.w;
    vec2 velocity = (curr_ndc - prev_ndc) * 0.5;  // NDC 范围 [-1,1],半转为 [-0.5, 0.5]
    frag_velocity = velocity;
}
```

### 6.3 Motion Blur Pass

有了 velocity buffer,motion blur 算法:

1. 对每个输出像素,沿 velocity 方向采样 N 个点。
2. 累加这些点的颜色,平均。

```glsl
uniform sampler2D u_color;
uniform sampler2D u_velocity;

const int SAMPLES = 16;

out vec3 frag_color;

void main() {
    vec2 velocity = texture(u_velocity, v_uv).rg;
    float velocity_len = length(velocity);
    
    if (velocity_len < 0.001) {
        frag_color = texture(u_color, v_uv).rgb;
        return;
    }
    
    vec3 color_sum = vec3(0.0);
    float total_weight = 0.0;
    
    // 沿 velocity 方向采样(对称,从 -0.5*velocity 到 +0.5*velocity)
    for (int i = 0; i < SAMPLES; i++) {
        float t = float(i) / float(SAMPLES - 1) - 0.5;  // [-0.5, 0.5]
        vec2 sample_uv = v_uv + velocity * t;
        vec3 sample_color = texture(u_color, sample_uv).rgb;
        color_sum += sample_color;
        total_weight += 1.0;
    }
    
    frag_color = color_sum / total_weight;
}
```

### 6.4 进阶:Tile-based Max Velocity Optimization

朴素 motion blur 在 1080p 上每个像素采样 16 次,总采样 3300 万次,~3ms。能不能更快?

**Tile-based max velocity**:

1. 把屏幕分成 16x16 tile。
2. 每个 tile 用 compute shader 算出**该 tile 内的最大 velocity**。
3. Pixel shader 根据**所在 tile 的 max velocity**决定采样数(快移动 tile 多采样,慢移动 tile 少采样)。

Unreal、Unity 都用这套优化,把 motion blur 从 3ms 压到 0.8ms。

### 6.5 现代用法:TAA

今天大部分 AAA 游戏 **不用独立 motion blur pass**——他们用 TAA(Temporal Anti-Aliasing)。TAA 利用 velocity buffer 在**时间维度**做抗锯齿,顺带产生 motion blur 副作用(因为 TAA 把多帧混合,自然产生拖影)。

TAA 的 motion blur 不如独立 pass 强烈,但视觉上"自然",不需要额外 GPU 开销。

## 7 · Color Grading:调色

Color grading 是把"raw 渲染"变成"有风格的画面"。一个游戏从冷蓝赛博朋克到暖黄怀旧日式,核心差别就是 color grading。

### 7.1 调色的本质

调色是输入(R, G, B) → 输出 (R', G', B') 的映射。最简单的映射是**逐 channel**:`R' = f(R), G' = g(G), B' = b(B)`——三个 1D 函数。这叫 **1D LUT**。

但 1D LUT 不能表达"颜色之间的相互作用"。比如想让"红色偏暖,但只在亮处偏暖"——这个映射依赖 R 和亮度(亮度依赖 R+G+B),1D LUT 做不到(它是独立 channel)。

要表达任意 RGB → RGB 映射,需要 **3D LUT**——一个三维查找表,R、G、B 各一个维度。表里每个 (r, g, b) 位置存一个 (r', g', b') 输出。

### 7.2 1D LUT

1D LUT 是一个 256x1 的纹理(对 8-bit 输入)。每个 channel 一张。

```glsl
uniform sampler2D u_lut_r;  // 256x1
uniform sampler2D u_lut_g;
uniform sampler2D u_lut_b;

vec3 apply_1d_lut(vec3 color) {
    vec3 result;
    // texture(u_lut_r, color.r) 的 x 坐标是 [0,1],对应 [0,255] 索引
    result.r = texture(u_lut_r, vec2(color.r, 0.5)).r;
    result.g = texture(u_lut_g, vec2(color.g, 0.5)).g;
    result.b = texture(u_lut_b, vec2(color.b, 0.5)).b;
    return result;
}
```

1D LUT 适合**简单调色**——白平衡(整体偏冷或偏暖)、对比度、亮度。

### 7.3 3D LUT

3D LUT 是一个 NxNxN 的 3D 纹理。N 典型是 32(32x32x32 = 32768 个 entry,够用)。每个 entry 存一个 (r', g', b')。

```glsl
uniform sampler3D u_lut_3d;  // 32x32x32

vec3 apply_3d_lut(vec3 color) {
    return texture(u_lut_3d, color).rgb;
}
```

GPU 上 3D texture sampling 自带 trilinear 插值——你查询 (0.13, 0.45, 0.67),GPU 自动在周围 8 个 entry 之间做三线性插值,得到平滑结果。

3D LUT 适合**复杂调色**——电影感、暖黄怀旧、冷蓝赛博朋克、黑白、双重色调。电影工业全部用 3D LUT(DaVinci Resolve、Lustre、Baselight)。

工业实践:**预先在 Photoshop / DaVinci 里调一张参考图,导出 .cube 文件(LUT 标准格式),引擎读取后转换为 3D texture**。开发者改调色不用改 shader,只换 LUT 资源。

### 7.4 Shaper LUT

3D LUT 有个精度问题:N=32 时每个维度只有 32 个 entry,中间值靠插值。如果调色曲线变化剧烈(比如 S-curve 对比度强化),32 个 entry 可能不够,出现 banding。

解法:**shaper LUT**。在 3D LUT 之前用一个 1D LUT 把输入"非线性化"(类似 gamma),让暗部和亮部占用更多 entry,中段占用较少。这样 3D LUT 在感知空间里分布,32 个 entry 也够。

具体流程:

```
input linear → shaper 1D LUT (gamma 2.2 → perceptual)
              → 3D LUT (在 perceptual 空间调色)
              → inverse shaper 1D LUT (perceptual → linear)
              → output
```

电影工业大量用 shaper LUT。Unity HDRP 用 shaper LUT 提升调色精度。

### 7.5 LUT 烘焙

如何在引擎里生成 3D LUT?**反向映射**:

1. 取一张**调色前**的参考图(渲染的截图)。
2. 在 Photoshop / DaVinci 里调到想要的风格。
3. 引擎跑一个"identity LUT"(32x32x32,每个 entry 等于自己的位置)经过同样的 Photoshop / DaVinci 调色——得到"调色后 LUT"。
4. 引擎加载这个 LUT 资源,运行时采样。

或者更直接:**用 DaVinci 导出 .cube 文件**,引擎解析。

Unreal 用 LUT 资源 (`UTextureRenderTargetCube`),Unity 用 `Texture3D`,Godot 用 `FastLUT` 资源。

## 8 · 镜头瑕疵:Vignette / CA / Grain / Distortion

这些效果都是"小瑕疵",单独看没什么,但组合起来给画面"摄影机感"。

### 8.1 Vignette(暗角)

镜头物理上,进光在边缘比中心弱(镜片边缘的透光率低 + 镜头遮蔽)。结果:**画面四角偏暗**。

```glsl
vec3 apply_vignette(vec3 color, vec2 uv) {
    vec2 center = uv - 0.5;
    float dist = length(center);
    float vignette = smoothstep(0.8, 0.3, dist);  // 中心 1.0,边缘 0.0
    return color * vignette;
}
```

性能:几条算术,几乎免费。

### 8.2 Chromatic Aberration(色散)

镜头玻璃对不同波长光的折射率不同(色差),RGB 三色在边缘会"错开"。**画面边缘 RGB 三色分离**,中心基本无 CA。

```glsl
vec3 apply_chromatic_aberration(sampler2D tex, vec2 uv) {
    vec2 center = uv - 0.5;
    float dist = length(center);
    
    // 三个 channel 用不同方向位移(模拟波长差异)
    float amount = 0.003 * dist;  // 越靠边缘越强
    vec2 dir = normalize(center);
    
    float r = texture(tex, uv - dir * amount).r;
    float g = texture(tex, uv).g;
    float b = texture(tex, uv + dir * amount).b;
    
    return vec3(r, g, b);
}
```

性能:3 次纹理采样,基本免费。但**过度 CA 会很刺眼**,游戏里通常只用很轻微量(amount < 0.005)。

### 8.3 Film Grain(胶片颗粒)

真实胶片有感光化学颗粒,产生随机噪点。游戏模拟这个,加上"老电影感"。

```glsl
// 用一个 pre-baked noise texture
uniform sampler2D u_grain;
uniform float u_time;
uniform float u_grain_intensity;

vec3 apply_film_grain(vec3 color, vec2 uv) {
    // grain 随时间偏移,看起来"在动"
    vec2 grain_uv = uv * vec2(800.0, 600.0) / 64.0 + u_time * 10.0;
    float grain = texture(u_grain, grain_uv).r;  // 0~1
    grain = (grain - 0.5) * u_grain_intensity;  // 偏离 0.5
    return color + vec3(grain);
}
```

注意:grain 在 LDR 之后加(它不是物理光照效果)。

### 8.4 Lens Distortion(镜头畸变)

广角镜头(鱼眼)有桶形畸变(barrel distortion),长焦镜头有枕形畸变(pincushion)。游戏模拟这个:

```glsl
vec2 apply_lens_distortion(vec2 uv) {
    vec2 center = uv - 0.5;
    float r2 = dot(center, center);
    
    // 桶形畸变:radius = radius * (1 + k * r²)
    float k = 0.1;  // 正 = 桶形,负 = 枕形
    center *= 1.0 + k * r2;
    
    return center + 0.5;
}

vec3 distorted_sample(sampler2D tex, vec2 uv) {
    vec2 distorted_uv = apply_lens_distortion(uv);
    if (distorted_uv.x < 0.0 || distorted_uv.x > 1.0 || 
        distorted_uv.y < 0.0 || distorted_uv.y > 1.0) {
        return vec3(0.0);  // 出界
    }
    return texture(tex, distorted_uv).rgb;
}
```

性能:多一次纹理采样 + 几条算术,几乎免费。

## 9 · 屏幕空间效果:SSR 与 SSAO 概念

虽然这两个通常不算"post-processing"(它们发生在 lighting pass 里,不是最后),但概念上属于"屏幕空间技巧",值得一提。

### 9.1 Screen-Space Reflections (SSR)

PBR 计算反射时,通常用 IBL(environment probe / cube map)做近似。但 IBL 是**全局环境**,不知道场景具体几何。SSR 用 **depth buffer + color buffer 做光线追踪**——对每个像素,沿反射方向步进,看是否击中其他场景像素。

SSR 算法(ray march):

```glsl
vec3 ssr_ray_march(sampler2D color_tex, sampler2D depth_tex, 
                   vec3 view_pos, vec3 reflect_dir) {
    vec3 ray_pos = view_pos;
    vec3 ray_dir = reflect_dir;
    
    const int MAX_STEPS = 64;
    const float STEP_SIZE = 0.1;
    
    for (int i = 0; i < MAX_STEPS; i++) {
        ray_pos += ray_dir * STEP_SIZE;
        vec4 clip = view_proj * vec4(ray_pos, 1.0);
        vec2 uv = (clip.xy / clip.w) * 0.5 + 0.5;
        
        if (uv.x < 0.0 || uv.x > 1.0 || uv.y < 0.0 || uv.y > 1.0) break;
        
        float scene_depth = linearize_depth(texture(depth_tex, uv).r);
        float ray_depth = clip.w;  // 简化,实际要更小心
        
        if (abs(ray_depth - scene_depth) < 0.05 && ray_depth < scene_depth) {
            return texture(color_tex, uv).rgb;
        }
    }
    
    return vec3(0.0);  // 没击中
}
```

SSR 局限:**只能反射屏幕上看见的东西**。屏幕外的物体反射不到,屏幕背面的物体反射不到。所以 SSR 通常和 IBL 结合——SSR 命中用 SSR,没命中 fallback 到 IBL。

### 9.2 Screen-Space Ambient Occlusion (SSAO)

PBR 的 ambient 光照通常用 IBL 提供。但 IBL 假设环境光**从所有方向均匀来**,不考虑场景几何的遮挡——角落里(墙缝、家具下)实际接收的环境光少(因为被周围物体挡住)。SSAO 模拟这个:

```glsl
float ssao(sampler2D depth_tex, vec2 uv, vec3 view_pos, vec3 normal) {
    const int KERNEL_SIZE = 16;
    vec3 samples[KERNEL_SIZE];  // 预生成的半球采样点
    
    float occlusion = 0.0;
    for (int i = 0; i < KERNEL_SIZE; i++) {
        vec3 sample_pos = view_pos + samples[i];
        vec4 clip = view_proj * vec4(sample_pos, 1.0);
        vec2 sample_uv = (clip.xy / clip.w) * 0.5 + 0.5;
        
        float scene_depth = linearize_depth(texture(depth_tex, sample_uv).r);
        float sample_depth = clip.w;
        
        if (sample_depth < scene_depth) occlusion += 1.0;
    }
    
    return 1.0 - occlusion / float(KERNEL_SIZE);
}
```

性能:SSAO 16 samples per pixel = ~1ms(1080p)。SSAO 是 indie / mobile 标配,AAA 更高级的方案有 GTAO、HBAO、RTAO(光线追踪 AO)。

## 10 · 现代:Full Pipeline 顺序与性能优化

### 10.1 完整 pipeline 顺序

工业标准 post-process 顺序:

```
HDR 阶段:
  1. Lighting buffer(16F)
  2. SSAO / SSR(乘到 lighting buffer)
  3. [可选] Volumetric fog 合成
  4. [可选] DOF(需要 depth + color)
  5. [可选] Motion blur(需要 velocity)
  6. Bloom extract(bright pass)
  7. Bloom blur(pyramid,4-5 层)
  8. Bloom 合成(加到 color)
  9. Auto-exposure(测量 L_avg,计算 exposure)
  10. Exposure * Tone mapping(HDR → LDR)

LDR 阶段:
  11. Color grading(3D LUT)
  12. Vignette
  13. Chromatic aberration
  14. Film grain
  15. [可选] Lens distortion
  16. Gamma correction(线性 → sRGB)
  17. 写 swapchain
```

顺序的理由:

- DOF 和 motion blur 在 bloom 之前——避免高光被模糊后 bloom 边缘锯齿。
- Bloom 在 exposure + tone mapping 之前——bloom 需要 HDR 数据(>1)。
- Color grading 在 tone mapping 之后——调色针对显示颜色(LDR)。
- 镜头瑕疵在 color grading 之后——它们是"显示端"效果。
- Gamma correction 必须最后——LDR 在 8-bit 之前先线性,LUT 和瑕疵在 sRGB 显示空间。

### 10.2 半分辨率优化

不是所有 pass 都需要全分辨率。Half-res(半分辨率)是常用优化:

- **Bloom extract**:half-res(光晕本来就要模糊,半分辨率看不出)。
- **Bloom blur**:quarter-res 甚至 1/16(金字塔本身就是多分辨率)。
- **DOF**:half-res(模糊区域看不清细节)。
- **Motion blur**:half-res(同上)。
- **SSAO**:half-res(ambient 光照本来就很弱,看不出分辨率)。
- **Color grading**:全分辨率(调色精度要求高)。
- **Vignette / CA / grain / distortion**:全分辨率(这些都是细节效果)。

性能:半分辨率 = 1/4 像素数 = 大约 4x 加速。Unreal 5 默认 bloom 在 half-res,DOF 在 half-res,SSAO 在 half-res。

### 10.3 Ping-Pong Buffer

post-processing 是一连串 pass,每个 pass 读上一个 pass 的输出,写下一个 pass 的输入。如果每个 pass 都用新 buffer,内存爆炸。

解法:**ping-pong buffer**——两个 buffer,A 和 B。Pass 1 读 A 写 B,Pass 2 读 B 写 A,Pass 3 读 A 写 B...交替使用。

```rust
struct PostProcessPipeline {
    buffer_a: Framebuffer,  // HDR RGBA16F
    buffer_b: Framebuffer,
    
    fn run(&mut self, hdr_input: &Framebuffer) -> &Framebuffer {
        // Pass 1: copy input to A
        self.blit(hdr_input, &mut self.buffer_a);
        
        // Pass 2: bloom, A → B
        self.bloom_pass(&self.buffer_a, &mut self.buffer_b);
        
        // Pass 3: tone map, B → A
        self.tone_map_pass(&self.buffer_b, &mut self.buffer_a);
        
        // Pass 4: color grade, A → B
        self.color_grade_pass(&self.buffer_a, &mut self.buffer_b);
        
        // ...继续 ping-pong
        
        &self.buffer_b
    }
}
```

两个 buffer 够大多数 pipeline。如果某个 pass 需要同时读历史数据(比如 TAA),可能需要第三个 buffer。

## 11 · 现代:TAA、VRS、DLSS

post-processing 领域近 5 年的革命:

### 11.1 TAA(Temporal Anti-Aliasing)

传统 MSAA 太贵(4x MSAA = 4 倍着色开销)。TAA 利用**时间维度**:每帧用不同的 sub-pixel jitter(亚像素偏移),渲染时混入历史帧,得到超采样效果。

TAA 关键依赖 velocity buffer(给 motion blur 用的同一个)——历史帧要根据 velocity"对齐"到当前帧,否则快速移动物体有 ghosting(残影)。

TAA 现在是 AAA 标配(Unreal 默认 TAA,Unity HDRP 默认 TAA),约 0.5ms(1080p)。

### 11.2 Variable Rate Shading (VRS)

VRS(DirectX 12 / Vulkan 1.2+)允许**不同区域用不同着色率**——屏幕中心全分辨率(玩家在看),屏幕角落 1/4 着色率(模糊也无所谓)。降低 GPU 负载 20-40%。

VRS 集成在 post-process pipeline 之前(它是 shading 阶段的优化),但和 post-process 紧密相关——比如 VR 渲染用 foveated VRS(眼睛中央清晰,周围模糊)。

### 11.3 DLSS / FSR / XeSS

DLSS(Deep Learning Super Sampling,NVIDIA)、FSR(FidelityFX Super Resolution,AMD)、XeSS(Intel)用 **AI / 传统算法把低分辨率渲染升采样到高分辨率**。比如 1080p 渲染,DLSS 输出 4K 画面。

这些技术位于 post-process pipeline 末尾——所有 post effect 在低分辨率做,最后用 DLSS 升采样。性能:1080p DLSS 比 4K native 快 4 倍。

DLSS / FSR 内部用 motion vector(同 velocity buffer)+ 历史帧 + AI 模型,产生高质量升采样。

## 12 · 历史:从 Half-Life 2 到 Unreal 5

后处理演化时间线:

| 年 | 里程碑 | 贡献 |
|---|---|---|
| 2002 | Reinhard 论文 | 第一条系统化 tone mapping |
| 2005 | Half-Life 2: Lost Coast | 第一次在游戏里演示 HDR |
| 2007 | Crysis | 大规模 HDR pipeline 工业化 |
| 2010 | Uncharted 2 Filmic | Filmic tone mapping + bloom pyramid |
| 2010 | GDC 2010 Talk | Naughty Dog 公布 Filmic 公式 |
| 2014 | SIGGRAPH Karnis Bloom | 高质 bloom pyramid |
| 2014 | Infamous: Second Son | Karnis bloom 工业化 |
| 2016 | Narkowicz ACES 简化 | ACES tone mapping 进入游戏 |
| 2017 | Unreal 4.15 | ACES 默认 |
| 2018 | Unity HDRP | ACES + LUT + Bloom standard |
| 2020 | Unreal 5 Lumen | 全套 post-process + GI |
| 2022 | Godot 4 | post-process 完整 |
| 2024 | Bevy 0.13 | post-process 集成 |

## 13 · 跨学科:信号处理与图像处理

post-processing 本质是**信号处理**(signal processing)在 2D 图像上的应用。理解这一点能让你看懂很多设计权衡。

### 13.1 卷积

后处理大部分 pass 本质是**卷积**(convolution):

```
output(x, y) = ∑∑ input(x-i, y-j) * kernel(i, j)
```

高斯模糊、bloom、DOF、motion blur、SSAO、SSR 都是卷积。

### 13.2 Nyquist 采样定理

信号处理的 Nyquist 定理:**采样率必须 ≥ 信号最高频率的 2 倍**。游戏渲染的"采样率"是屏幕分辨率,"信号"是几何细节频率。如果场景有 1 像素宽的电线,1080p 渲染 = Nyquist 极限,会**走样**(aliasing,锯齿)。AA(抗锯齿)就是 Nyquist 的应对。

### 13.3 频域视角

高斯模糊在频域是**低通滤波**(只保留低频,去掉高频)。bloom 提取亮度 + 模糊,本质是"提取低频亮部,叠加回去"——把高频细节融入低频光晕。

理解这个让你知道:**所有"模糊"类 post-process 在频域都是低通**。要避免不同 pass 互相影响,可以在频域设计互补的 filter。

## 14 · 在你 HH 项目里实践

让我们把上面的知识落到 HH 项目。Casey 在 Handmade Hero 后期 Day 230+ 加了 OpenGL,我们可以基于 OpenGL 写一个 mini post-process pipeline。

### 14.1 项目结构

```
hh_post_process/
├── Cargo.toml
├── src/
│   ├── main.rs
│   ├── renderer.rs        # 渲染主循环
│   ├── post_process.rs    # post-process pipeline
│   └── shaders/
│       ├── hdr_to_ldr.frag    # tone map + gamma
│       ├── bloom_extract.frag # bright pass
│       ├── bloom_blur.frag    # separable gaussian
│       ├── bloom_composite.frag
│       ├── color_grade.frag   # 3D LUT
│       └── lens.frag          # vignette + CA + grain
└── assets/
    └── film_lut.cube      # 3D LUT
```

### 14.2 Cargo.toml

```toml
[package]
name = "hh_post_process"
version = "0.1.0"
edition = "2021"

[dependencies]
glow = "0.13"           # OpenGL wrapper
glutin = "0.31"         # window + GL context
nalgebra = "0.33"       # 矩阵
image = "0.25"          # 读 LUT texture

[profile.release]
opt-level = 3
lto = true
```

### 14.3 HDR framebuffer 创建

```rust
// renderer.rs
use glow::*;

pub struct HdrFramebuffer {
    pub fbo: FramebufferKey,
    pub color_texture: TextureKey,
    pub depth_texture: TextureKey,
    pub width: i32,
    pub height: i32,
}

impl HdrFramebuffer {
    pub fn new(gl: &Context, width: i32, height: i32) -> Self {
        unsafe {
            // 创建 HDR color texture:RGBA16F
            let color_texture = gl.create_texture().unwrap();
            gl.bind_texture(TEXTURE_2D, Some(color_texture));
            gl.tex_image_2d(
                TEXTURE_2D,
                0,
                RGBA16F as i32,  // HDR!
                width,
                height,
                0,
                RGBA,
                FLOAT,
                None,
            );
            gl.tex_parameter_i32(TEXTURE_2D, TEXTURE_MIN_FILTER, LINEAR as i32);
            gl.tex_parameter_i32(TEXTURE_2D, TEXTURE_MAG_FILTER, LINEAR as i32);
            
            // depth texture
            let depth_texture = gl.create_texture().unwrap();
            gl.bind_texture(TEXTURE_2D, Some(depth_texture));
            gl.tex_image_2d(
                TEXTURE_2D,
                0,
                DEPTH_COMPONENT32F as i32,
                width,
                height,
                0,
                DEPTH_COMPONENT,
                FLOAT,
                None,
            );
            
            // 创建 FBO
            let fbo = gl.create_framebuffer().unwrap();
            gl.bind_framebuffer(FRAMEBUFFER, Some(fbo));
            gl.framebuffer_texture_2d(
                FRAMEBUFFER,
                COLOR_ATTACHMENT0,
                TEXTURE_2D,
                Some(color_texture),
                0,
            );
            gl.framebuffer_texture_2d(
                FRAMEBUFFER,
                DEPTH_ATTACHMENT,
                TEXTURE_2D,
                Some(depth_texture),
                0,
            );
            
            HdrFramebuffer {
                fbo,
                color_texture,
                depth_texture,
                width,
                height,
            }
        }
    }
}
```

### 14.4 Tone mapping shader

```glsl
// hdr_to_ldr.frag
#version 330 core

in vec2 v_uv;
out vec4 frag_color;

uniform sampler2D u_hdr;
uniform float u_exposure;

// ACES filmic tone mapping
vec3 aces_tonemap(vec3 x) {
    const float a = 2.51;
    const float b = 0.03;
    const float c = 2.43;
    const float d = 0.59;
    const float e = 0.14;
    return clamp((x * (a * x + b)) / (x * (c * x + d) + e), 0.0, 1.0);
}

void main() {
    vec3 hdr = texture(u_hdr, v_uv).rgb;
    
    // 1. Apply exposure
    vec3 exposed = hdr * u_exposure;
    
    // 2. Tone map (ACES)
    vec3 ldr = aces_tonemap(exposed);
    
    // 3. Gamma correction (linear → sRGB approximate)
    vec3 gamma_corrected = pow(ldr, vec3(1.0 / 2.2));
    
    frag_color = vec4(gamma_corrected, 1.0);
}
```

### 14.5 Bloom extract shader

```glsl
// bloom_extract.frag
#version 330 core

in vec2 v_uv;
out vec4 frag_color;

uniform sampler2D u_hdr;
uniform float u_threshold;  // 比如 1.0

void main() {
    vec3 hdr = texture(u_hdr, v_uv).rgb;
    
    // 软阈值:不是 hard cut,而是 smoothstep,避免边缘锯齿
    float brightness = dot(hdr, vec3(0.2126, 0.7152, 0.0722));  // Rec.709 luminance
    float soft_threshold = 0.5;
    float knee = 0.5;
    
    float contribution = max(brightness - u_threshold, 0.0);
    contribution = mix(contribution, contribution * contribution / (knee * 4.0), soft_threshold);
    
    frag_color = vec4(hdr * (contribution / max(brightness, 0.00001)), 1.0);
}
```

### 14.6 Separable Gaussian blur shader

```glsl
// bloom_blur.frag
#version 330 core

in vec2 v_uv;
out vec4 frag_color;

uniform sampler2D u_input;
uniform vec2 u_texel_size;
uniform vec2 u_direction;  // (1, 0) for horizontal, (0, 1) for vertical
uniform int u_kernel_size;  // 比如 13

void main() {
    float weights[7];
    weights[0] = 0.1974;
    weights[1] = 0.1747;
    weights[2] = 0.1209;
    weights[3] = 0.0655;
    weights[4] = 0.0278;
    weights[5] = 0.0092;
    weights[6] = 0.0024;
    
    vec3 sum = texture(u_input, v_uv).rgb * weights[0];
    
    for (int i = 1; i < 7; i++) {
        vec2 offset = u_direction * u_texel_size * float(i) * 1.5;  // 1.5 = spread
        sum += texture(u_input, v_uv + offset).rgb * weights[i];
        sum += texture(u_input, v_uv - offset).rgb * weights[i];
    }
    
    frag_color = vec4(sum, 1.0);
}
```

### 14.7 Post-process pipeline 主循环(Rust)

```rust
// post_process.rs
use glow::*;

pub struct PostProcessPipeline {
    // HDR framebuffers(ping-pong)
    pub hdr_a: HdrFramebuffer,
    pub hdr_b: HdrFramebuffer,
    
    // Bloom pyramid framebuffers
    pub bloom_mip0: HdrFramebuffer,  // 1/2 resolution
    pub bloom_mip1: HdrFramebuffer,  // 1/4
    pub bloom_mip2: HdrFramebuffer,  // 1/8
    pub bloom_mip3: HdrFramebuffer,  // 1/16
    
    // Shaders
    pub tone_map_shader: ProgramKey,
    pub bloom_extract_shader: ProgramKey,
    pub bloom_blur_shader: ProgramKey,
    pub bloom_composite_shader: ProgramKey,
    pub color_grade_shader: ProgramKey,
    pub lens_shader: ProgramKey,
    
    // LUT
    pub lut_3d: TextureKey,
    
    // State
    pub exposure: f32,
    pub smoothed_exposure: f32,
}

impl PostProcessPipeline {
    pub fn apply(&mut self, gl: &Context, dt: f32) {
        unsafe {
            // === HDR 阶段 ===
            
            // 1. Bloom extract: hdr_a → bloom_mip0
            self.run_pass(gl, self.bloom_extract_shader, &self.hdr_a, &self.bloom_mip0);
            
            // 2. Downsample pyramid: mip0 → mip1 → mip2 → mip3
            for (src, dst) in [
                (&self.bloom_mip0, &self.bloom_mip1),
                (&self.bloom_mip1, &self.bloom_mip2),
                (&self.bloom_mip2, &self.bloom_mip3),
            ] {
                self.run_blur_pass(gl, src, dst, (1.0, 0.0));
                self.run_blur_pass(gl, dst, dst, (0.0, 1.0));
            }
            
            // 3. Upsample pyramid: mip3 → mip2 → mip1 → mip0 (累加)
            self.run_bloom_composite(gl);
            
            // 4. Auto-exposure(简化版:CPU 读回 1x1 reduction buffer)
            // 真实工业实现会用 compute shader 在 GPU 上做 reduction
            let target_exposure = self.compute_target_exposure(gl);
            self.smoothed_exposure += (target_exposure - self.smoothed_exposure) * (1.0 - (-dt * 3.0).exp());
            
            // 5. Tone map + bloom 合成 + color grade + lens(一个 mega shader)
            // 或者分 pass:hdr_a → tone_map → hdr_b
            //          → bloom_composite → hdr_b
            //          → color_grade → hdr_a
            //          → lens → swapchain
            
            // === 写到 swapchain ===
            gl.bind_framebuffer(FRAMEBUFFER, None);  // 默认 framebuffer = swapchain
            self.draw_fullscreen(gl, self.lens_shader, &self.hdr_a);
        }
    }
    
    fn run_pass(&self, gl: &Context, shader: ProgramKey, src: &HdrFramebuffer, dst: &HdrFramebuffer) {
        unsafe {
            gl.bind_framebuffer(FRAMEBUFFER, Some(dst.fbo));
            gl.viewport(0, 0, dst.width, dst.height);
            gl.use_program(Some(shader));
            gl.active_texture(TEXTURE0);
            gl.bind_texture(TEXTURE_2D, Some(src.color_texture));
            gl.uniform_1_i32(gl.get_uniform_location(shader, "u_input"), 0);
            self.draw_fullscreen_quad(gl);
        }
    }
    
    fn draw_fullscreen_quad(&self, gl: &Context) {
        // VAO with 2 triangles covering [-1, 1] clip space
        // ... 简化,实际要绑定 VAO/IBO
    }
    
    fn compute_target_exposure(&self, _gl: &Context) -> f32 {
        // 简化:返回固定值
        // 工业实现:gl.read_pixels 1x1 reduction buffer,exp 得到 L_avg
        let l_avg = 0.18;  // 中性灰
        let key_value = 0.18;
        key_value / l_avg.max(0.0001)
    }
}
```

### 14.8 Color grading shader

```glsl
// color_grade.frag
#version 330 core

in vec2 v_uv;
out vec4 frag_color;

uniform sampler2D u_ldr;
uniform sampler3D u_lut;  // 32x32x32

void main() {
    vec3 color = texture(u_ldr, v_uv).rgb;
    
    // 3D LUT 在 [0,1] 范围采样
    // 注意:32x32x32 时,我们要把 UV 从 [0,1] 缩放到 [0.5/32, 31.5/32]
    // 避免 edge texel sampling
    float lut_size = 32.0;
    vec3 lut_uv = color * (lut_size - 1.0) / lut_size + 0.5 / lut_size;
    
    vec3 graded = texture(u_lut, lut_uv).rgb;
    
    frag_color = vec4(graded, 1.0);
}
```

### 14.9 Lens effects shader

```glsl
// lens.frag
#version 330 core

in vec2 v_uv;
out vec4 frag_color;

uniform sampler2D u_ldr;
uniform sampler2D u_grain;
uniform float u_time;
uniform float u_vignette_intensity;
uniform float u_ca_intensity;
uniform float u_grain_intensity;

vec3 apply_vignette(vec3 color, vec2 uv) {
    vec2 center = uv - 0.5;
    float dist = length(center);
    float vignette = smoothstep(0.85, 0.3, dist);
    return color * mix(1.0, vignette, u_vignette_intensity);
}

vec3 apply_chromatic_aberration(sampler2D tex, vec2 uv) {
    vec2 center = uv - 0.5;
    float dist = length(center);
    vec2 dir = dist > 0.001 ? normalize(center) : vec2(0.0);
    float amount = u_ca_intensity * dist;
    
    float r = texture(tex, uv - dir * amount).r;
    float g = texture(tex, uv).g;
    float b = texture(tex, uv + dir * amount).b;
    
    return vec3(r, g, b);
}

vec3 apply_film_grain(vec3 color, vec2 uv) {
    vec2 grain_uv = uv * vec2(1920.0, 1080.0) / 128.0 + u_time * 17.0;
    float grain = texture(u_grain, grain_uv).r;
    grain = (grain - 0.5) * 2.0 * u_grain_intensity;
    return color + vec3(grain);
}

void main() {
    vec3 color = apply_chromatic_aberration(u_ldr, v_uv);
    color = apply_vignette(color, v_uv);
    color = apply_film_grain(color, v_uv);
    
    frag_color = vec4(color, 1.0);
}
```

### 14.10 集成到 HH 主循环

```rust
// main.rs
fn main() {
    let (gl, window, event_loop) = init_glow();
    
    let mut renderer = Renderer::new(&gl);
    let mut post_process = PostProcessPipeline::new(&gl, 1920, 1080);
    
    let mut last_time = instant::Instant::now();
    
    event_loop.run(move |event, _, control_flow| {
        // 计算帧间隔
        let now = instant::Instant::now();
        let dt = (now - last_time).as_secs_f32();
        last_time = now;
        
        // 1. 渲染场景到 HDR framebuffer
        unsafe {
            gl.bind_framebuffer(FRAMEBUFFER, Some(post_process.hdr_a.fbo));
            gl.viewport(0, 0, post_process.hdr_a.width, post_process.hdr_a.height);
            gl.clear_color(0.0, 0.0, 0.0, 1.0);
            gl.clear(COLOR_BUFFER_BIT | DEPTH_BUFFER_BIT);
            
            renderer.draw_scene(&gl);  // PBR 光照,允许 RGB > 1.0
        }
        
        // 2. Post-process pipeline
        post_process.apply(&gl, dt);
        
        // 3. Swap
        window.swap_buffers().unwrap();
    });
}
```

### 14.11 调试叙事:常见坑

**坑一:bloom 太强**。你设了 `bloom_intensity = 1.5`,画面全是光晕,看不清物体。
诊断:`renderdoc` 抓帧,看 bloom composite 那一步的 buffer 是不是已经爆白。
修复:`bloom_intensity` 从 0.3 开始,慢慢加。

**坑二:tone map 后画面偏红**。ACES 公式在亮处有轻微红偏。
诊断:在 GIMP 里打开 tone map 后的截图,检查 R/G/B 通道。
修复:在 tone map 后加一点颜色校正(`color.r *= 0.95`),或换 Uchimura tone mapper。

**坑三:auto-exposure 闪烁**。玩家从室内走到室外,画面亮度跳变。
诊断:输出 smoothed_exposure 值,看它是否平滑。
修复:把 `adaptation_rate` 从 3.0 降到 1.0(适应慢)。

**坑四:color grading LUT banding**。调色后画面有"色带"。
诊断:全黑 / 全白场景截图,在 Photoshop 里看 histogram 是否有"台阶"。
修复:用 shaper LUT,或把 LUT size 从 32 提到 64。

**坑五:motion blur 残影**。物体移动后,旧的图像"印"在屏幕上没消。
诊断:静止画面,看残影。
修复:检查 velocity buffer 是否正确归零(物体不动时 velocity 应该是 0)。

## 15 · 真实引擎源码导览

### 15.1 Unreal Engine 5 PostProcess

源码:`Engine/Source/Runtime/Renderer/Private/PostProcess/`

关键文件:
- `PostProcessing.cpp`:pipeline 主入口
- `PostProcessMaterial.cpp`:post-process material(开发者自定义 pass)
- `PostProcessBloomSetup.cpp` / `PostProcessBloomDown.cpp` / `PostProcessBloomUp.cpp`:bloom pyramid
- `PostProcessTonemap.cpp`:tone mapping
- `PostProcessEyeAdaptation.cpp`:auto-exposure
- `PostProcessMaterialInputs.h`:输入输出定义

Unreal 把每个 pass 拆成单独文件,通过 `FPostProcessing::Render` 串联。每个 pass 是 `FPostProcessPass` 的子类,有 `Setup` 和 `Process` 方法。

GitHub: https://github.com/EpicGames/UnrealEngine/blob/ue5-main/Engine/Source/Runtime/Renderer/Private/PostProcess/PostProcessing.cpp

### 15.2 Unity HDRP Post Processing

源码:`com.unity.render-pipelines.high-definition/Runtime/PostProcessing/`

关键文件:
- `PostProcessSystem.cs`:pipeline 主入口
- `Bloom.cs`:bloom 实现
- `Tonemapping.cs`:tone mapping
- `ColorAdjustments.cs`:color grading
- `MotionBlur.cs`:motion blur
- `DepthOfField.cs`:DOF

Unity 用 C# 写 post-process pipeline,shader 在 HDR 文件夹(`PostProcessing/Shaders/`)。每个 effect 是 `VolumeComponent` 子类,可以通过 Volume 系统在场景里插值。

GitHub: https://github.com/Unity-Technologies/Graphics/blob/master/Packages/com.unity.render-pipelines.high-definition/Runtime/PostProcessing/PostProcessSystem.cs

### 15.3 Godot 4 PostProcess

源码:`servers/rendering/renderer_rd/`

关键文件:
- `environment.cpp`:Environment 资源(包含所有 post-process 参数)
- `renderer_scene_render_rd.cpp`:主渲染流程
- `effects_rd.cpp`:具体 effect 实现
- shader:`servers/rendering/renderer_rd/shaders/` 下有 `tone_mapper.glsl`、`bloom.glsl`、`bokeh_dof.glsl`、`motion_blur.glsl`

Godot 4 用 RenderingDevice 抽象(Vulkan / Metal / D3D12),post-process 用 compute shader 实现。

GitHub: https://github.com/godotengine/godot/blob/master/servers/rendering/renderer_rd/effects_rd.cpp

### 15.4 Bevy PostProcessing

源码:`crates/bevy_render/src/render_phase/post_processing/`

Bevy 在 0.13 加入 post-processing 模块。和 Unreal/Unity 类似的 pipeline,但用 ECS 设计——每个 effect 是 `Component`,通过 `PostProcessPhaseItem` 串联。

GitHub: https://github.com/bevyengine/bevy/blob/main/crates/bevy_render/src/render_phase/post_processing/

### 15.5 Filament(Google)

源码:`filament/backend/src/postprocessing/`

Filament 是 Google 的 PBR 渲染器(用于 Android)。post-process 极其精简——只有 tone mapping、bloom、color grading、FXAA。代码量小,适合学习。

GitHub: https://github.com/google/filament/blob/main/filament/src/materials/PostProcessMaterial.cpp

## 16 · 性能数据汇总

1080p(1920x1080)、RTX 3060、Vulkan 的典型耗时:

| Pass | 全分辨率 | 半分辨率 | 1/4 分辨率 |
|---|---|---|---|
| Tone mapping | 0.10ms | - | - |
| Bloom extract | 0.20ms | 0.05ms | - |
| Bloom blur(4 mip × separable) | 0.50ms | 0.13ms | - |
| Bloom composite | 0.30ms | - | - |
| Auto-exposure reduction | 0.20ms | - | - |
| DOF(simple Gaussian) | 0.40ms | 0.10ms | - |
| DOF(bokeh splatting) | 1.50ms | 0.40ms | - |
| Motion blur(tile-based) | 0.80ms | 0.20ms | - |
| SSAO | 1.00ms | 0.25ms | - |
| SSR | 2.00ms | 0.50ms | - |
| Color grading(3D LUT) | 0.15ms | - | - |
| Lens effects(CA + vignette + grain) | 0.10ms | - | - |
| **完整 pipeline** | **~6.25ms** | **~3.0ms** | - |

工业 60fps budget = 16.6ms,post-process 占 20-40% 是常见。优化空间:half-res、tile-based、compute shader、TAA 替代 MSAA、DLSS 替代 native resolution。

## 17 · 延伸阅读

本仓库本地资料:
- [days/phase-5/day235.md](../../phase-5/day235.md) — OpenGL 集成,本文的 framebuffer 基础
- [days/phase-6/deep-dives/pbr-complete.md](pbr-complete.md) — PBR 完整剖析,本文的 tone mapping 上游
- [days/phase-6/deep-dives/lighting-models.md](lighting-models.md) — 光照模型
- [days/phase-6/deep-dives/shadow-mapping.md](shadow-mapping.md) — 阴影(本文 pipeline 中常合并)

外部稳定 URL:
- Reinhard 2002 论文:https://www.cs.utah.edu/~reinhard/cdrom/
- Narkowicz ACES:https://knarkowicz.wordpress.com/2016/01/06/aces-filmic-tone-mapping-curve/
- Uchimura tone mapper:https://www.desmos.com/calculator/vslm9nt5wm
- Karnis Bloom(原帖):https://community.khronos.org/t/bloom-with-glsl/57530
- Unreal PostProcessVolume doc:https://docs.unrealengine.com/5.0/en-US/post-process-volume/
- Unity HDRP Volume:https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@latest
- ACES Central:https://acescentral.com/
- Khronos glTF KHR_bloom:https://github.com/KhronosGroup/glTF

真实开源源码:
- Unreal PostProcess: https://github.com/EpicGames/UnrealEngine/blob/ue5-main/Engine/Source/Runtime/Renderer/Private/PostProcess/PostProcessing.cpp
- Unity HDRP PostProcess: https://github.com/Unity-Technologies/Graphics/blob/master/Packages/com.unity.render-pipelines.high-definition/Runtime/PostProcessing/PostProcessSystem.cs
- Godot 4 Effects: https://github.com/godotengine/godot/blob/master/servers/rendering/renderer_rd/effects_rd.cpp
- Bevy PostProcessing: https://github.com/bevyengine/bevy/blob/main/crates/bevy_render/src/render_phase/post_processing/mod.rs
- Filament Bloom: https://github.com/google/filament/blob/main/filament/src/materials/PostProcessMaterial.cpp

## 18 · 关联 Day

- **铺垫**:[day235](../../phase-5/day235.md) — OpenGL 基础,framebuffer 是本文 HDR buffer 的基础
- **当天**:本文是 phase-6 的 deep-dive,不分具体 day
- **后续**:[day362](../day362.md) 之后的 anti-aliasing、[day262](../day262.md) 的 lighting integration 都会用到本文 pipeline

## 19 · 进阶专题:Karnis Bloom 完整实现

让我把 Karnis bloom 的 downsample 和 upsample filter 完整展开。这是工业级 bloom 的核心,值得单独一节。

### 19.1 为什么 13-tap

Karnis 的洞察:**bilinear downsample(取 4 邻居平均)在亮像素附近会丢失高频信息**,产生 boxy 块状感。13-tap 加权滤波用 13 个采样点(中心 + 4 个 corner + 8 个 edge 中点),通过精心设计的权重,**在保留高频的同时做降采样**。

13 个采样点的几何:

```
[3]   [2]   [3]
   [1] [1] [1]
[2] [1] [0] [1] [2]
   [1] [1] [1]
[3]   [2]   [3]
```

数字是相对权重(归一化前)。中心(0)权重最高,4 个直邻(1)次高,4 个对角邻(2)更低,4 个远角(3)最低。

Karnis downsample GLSL:

```glsl
#version 330 core

in vec2 v_uv;
out vec4 frag_color;

uniform sampler2D u_input;
uniform vec2 u_texel_size;

void main() {
    vec2 ts = u_texel_size;
    
    // 13-tap 加权
    vec3 a = texture(u_input, v_uv + vec2(-2.0, -2.0) * ts).rgb;
    vec3 b = texture(u_input, v_uv + vec2( 0.0, -2.0) * ts).rgb;
    vec3 c = texture(u_input, v_uv + vec2( 2.0, -2.0) * ts).rgb;
    
    vec3 d = texture(u_input, v_uv + vec2(-1.0, -1.0) * ts).rgb;
    vec3 e = texture(u_input, v_uv + vec2( 1.0, -1.0) * ts).rgb;
    
    vec3 f = texture(u_input, v_uv + vec2(-2.0,  0.0) * ts).rgb;
    vec3 g = texture(u_input, v_uv + vec2( 0.0,  0.0) * ts).rgb;
    vec3 h = texture(u_input, v_uv + vec2( 2.0,  0.0) * ts).rgb;
    
    vec3 i = texture(u_input, v_uv + vec2(-1.0,  1.0) * ts).rgb;
    vec3 j = texture(u_input, v_uv + vec2( 1.0,  1.0) * ts).rgb;
    
    vec3 k = texture(u_input, v_uv + vec2(-2.0,  2.0) * ts).rgb;
    vec3 l = texture(u_input, v_uv + vec2( 0.0,  2.0) * ts).rgb;
    vec3 m = texture(u_input, v_uv + vec2( 2.0,  2.0) * ts).rgb;
    
    // 权重(Karnis 经验值)
    vec3 result = g * 0.5;
    result += (d + e + i + j) * 0.125;
    result += (b + f + h + l) * 0.03125;
    result += (a + c + k + m) * 0.015625;
    result /= 1.1875;  // 归一化常数
    
    frag_color = vec4(result, 1.0);
}
```

### 19.2 Upsample Filter(9-tap)

Upsample 也用加权 filter,不是简单 bilinear。9 个采样点(中心 + 4 直邻 + 4 对角):

```glsl
#version 330 core

in vec2 v_uv;
out vec4 frag_color;

uniform sampler2D u_input;
uniform sampler2D u_higher_mip;  // 上一 mip(高分辨率)
uniform vec2 u_texel_size;
uniform float u_bloom_intensity;

void main() {
    vec2 ts = u_texel_size;
    
    vec3 a = texture(u_input, v_uv + vec2(-1.0, -1.0) * ts).rgb;
    vec3 b = texture(u_input, v_uv + vec2( 1.0, -1.0) * ts).rgb;
    vec3 c = texture(u_input, v_uv + vec2(-1.0,  1.0) * ts).rgb;
    vec3 d = texture(u_input, v_uv + vec2( 1.0,  1.0) * ts).rgb;
    
    vec3 e = texture(u_input, v_uv + vec2(-2.0,  0.0) * ts).rgb;
    vec3 f = texture(u_input, v_uv + vec2( 2.0,  0.0) * ts).rgb;
    vec3 g = texture(u_input, v_uv + vec2( 0.0, -2.0) * ts).rgb;
    vec3 h = texture(u_input, v_uv + vec2( 0.0,  2.0) * ts).rgb;
    
    vec3 center = texture(u_input, v_uv).rgb;
    
    vec3 result = center * 0.125;
    result += (a + b + c + d) * 0.5;
    result += (e + f + g + h) * 0.125;
    
    // 合成到高分辨率 mip(累加)
    vec3 higher = texture(u_higher_mip, v_uv).rgb;
    frag_color = vec4(mix(higher, result, u_bloom_intensity), 1.0);
}
```

### 19.3 完整 Karnis pyramid 主循环(Rust)

```rust
// Karnis bloom pyramid
pub fn run_karnis_bloom(&mut self, gl: &Context) {
    unsafe {
        // 1. Bright pass:hdr_a → bloom_mip0(1/2 分辨率)
        // 同时做 13-tap downsample
        self.run_pass_with_downsample(
            gl,
            self.bloom_extract_shader,  // 内部用 13-tap
            &self.hdr_a,
            &self.bloom_mip0,
        );
        
        // 2. 降采样链:mip0 → mip1 → mip2 → mip3
        // 每个 step 都用 13-tap
        self.run_13tap_downsample(gl, &self.bloom_mip0, &self.bloom_mip1);
        self.run_13tap_downsample(gl, &self.bloom_mip1, &self.bloom_mip2);
        self.run_13tap_downsample(gl, &self.bloom_mip2, &self.bloom_mip3);
        
        // 3. 升采样链:mip3 → mip2 → mip1 → mip0(每个 step 9-tap + 累加)
        self.run_9tap_upsample(gl, &self.bloom_mip3, &mut self.bloom_mip2);
        self.run_9tap_upsample(gl, &self.bloom_mip2, &mut self.bloom_mip1);
        self.run_9tap_upsample(gl, &self.bloom_mip1, &mut self.bloom_mip0);
        
        // 4. 最终 bloom_mip0 累加到主 HDR buffer
        // 这一步在 tone mapping 之前
        self.run_bloom_apply(gl, &self.bloom_mip0, &self.hdr_a);
    }
}
```

### 19.4 视觉对比:三种 bloom

| Bloom 方案 | 边缘伪影 | 性能(1080p) | 散景质量 |
|---|---|---|---|
| Bilinear downsample + bilinear upsample | 严重 boxy | 0.4ms | 差 |
| Separable 13-tap blur on each mip | 轻微 boxy | 0.6ms | 中 |
| Karnis 13-tap downsample + 9-tap upsample | 无伪影,光滑 | 0.9ms | 优秀 |

Karnis 多花的 0.3ms 在所有 3A 项目里都值——bloom 是画面里最显眼的效果之一,伪影会立刻被玩家看见。

## 20 · 进阶专题:Histogram Auto-Exposure 完整实现

我前面提到了 histogram auto-exposure,这里展开完整 compute shader 实现。

### 20.1 Histogram 构建

目标:在 GPU 上算 HDR buffer 的亮度直方图(64 bins)。

```glsl
#version 430 core
layout(local_size_x = 16, local_size_y = 16) in;

layout(rgba16f, binding = 0) readonly uniform image2D u_hdr;
layout(std430, binding = 1) coherent buffer Histogram {
    uint bins[64];
} histogram;

shared uint local_bins[64];

void main() {
    ivec2 pos = ivec2(gl_GlobalInvocationID.xy);
    ivec2 size = imageSize(u_hdr);
    
    if (pos.x >= size.x || pos.y >= size.y) return;
    
    // 初始化 shared memory(只 thread 0 做)
    if (gl_LocalInvocationIndex == 0) {
        for (int i = 0; i < 64; i++) local_bins[i] = 0;
    }
    barrier();
    
    // 读 HDR pixel,算 luminance
    vec3 color = imageLoad(u_hdr, pos).rgb;
    float lum = dot(color, vec3(0.2126, 0.7152, 0.0722));
    
    // log scale 映射到 [0, 63]
    float log_lum = log(max(lum, 0.0001));
    int bin = int(clamp((log_lum + 12.0) / 16.0 * 64.0, 0.0, 63.0));
    
    // atomic add 到 local bin
    atomicAdd(local_bins[bin], 1);
    
    barrier();
    
    // 把 local bins 累加到 global bins
    if (gl_LocalInvocationIndex < 64) {
        atomicAdd(histogram.bins[gl_LocalInvocationIndex], local_bins[gl_LocalInvocationIndex]);
    }
}
```

### 20.2 从 Histogram 计算 Exposure

```glsl
#version 430 core
layout(local_size_x = 1) in;

layout(std430, binding = 1) readonly buffer Histogram {
    uint bins[64];
} histogram;

layout(std430, binding = 2) coherent buffer Exposure {
    float value;
} exposure;

uniform float u_target_luminance;
uniform float u_adaptation_rate;
uniform float u_dt;
uniform float u_low_percentile;   // 0.7
uniform float u_high_percentile;  // 0.95

void main() {
    // 累计总数
    uint total = 0;
    for (int i = 0; i < 64; i++) total += histogram.bins[i];
    
    if (total == 0) return;
    
    // 找 70% 分位的 bin
    uint target_count = uint(float(total) * u_low_percentile);
    uint cumulative = 0;
    int target_bin = 32;
    for (int i = 0; i < 64; i++) {
        cumulative += histogram.bins[i];
        if (cumulative >= target_count) {
            target_bin = i;
            break;
        }
    }
    
    // bin → log luminance
    float log_lum = float(target_bin) / 64.0 * 16.0 - 12.0;
    float median_lum = exp(log_lum);
    
    // Target exposure
    float target_exposure = u_target_luminance / max(median_lum, 0.0001);
    
    // Smooth adaptation
    float current = exposure.value;
    float t = 1.0 - exp(-u_dt * u_adaptation_rate);
    float new_exposure = mix(current, target_exposure, t);
    
    exposure.value = new_exposure;
}
```

### 20.3 两个 pass 的调度

```rust
// Rust 端调度
pub fn run_auto_exposure(&mut self, gl: &Context, dt: f32) {
    unsafe {
        // Pass 1: 构建 histogram
        // dispatch: ceil(width/16) x ceil(height/16) x 1
        let groups_x = (self.width + 15) / 16;
        let groups_y = (self.height + 15) / 16;
        gl.use_program(Some(self.histogram_shader));
        gl.bind_image_texture(0, self.hdr_a.color_texture, 0, false, 0, READ_ONLY, RGBA16F);
        gl.dispatch_compute(groups_x, groups_y, 1);
        gl.memory_barrier(SHADER_STORAGE_BARRIER_BIT);
        
        // Pass 2: 计算 exposure(单个 work group)
        gl.use_program(Some(self.exposure_compute_shader));
        gl.uniform_1_f32(self.target_lum_loc, 0.18);
        gl.uniform_1_f32(self.adapt_rate_loc, 2.0);
        gl.uniform_1_f32(self.dt_loc, dt);
        gl.dispatch_compute(1, 1, 1);
        gl.memory_barrier(SHADER_STORAGE_BARRIER_BIT);
    }
}
```

性能:1080p histogram pass ~0.3ms,exposure pass ~0.01ms。比 reduction 方案(0.2ms)稍慢,但抗极端值能力显著强——画面里 99% 是暗场景 + 1% 是高光(比如爆炸瞬间),histogram 不会被那 1% 拉偏,而 reduction 方案会瞬间过曝。

## 21 · 调试叙事:从 bug 到修复的真实案例

让我把生产环境里的真实 bug 排查过程记下来,作为以后你遇到类似问题时的参考。

### 21.1 案例 1:bloom 边缘光晕闪烁

**症状**:画面左下角有一个亮物(火把),每帧 bloom 光晕大小微微变化,看起来"呼吸"。

**诊断过程**:
1. RenderDoc 抓帧,逐 pass 看 buffer。Bright pass buffer 在火把周围有亮像素,符合预期。
2. Downsample 链中,mip0(1/2 分辨率)的火把区域有一个孤立的 1 像素亮点。这是问题——1 像素亮点在不同帧采样到不同的 downsample cell,产生闪烁。
3. Root cause:bright pass 的 threshold 是 hard cut(`if (lum > 1.0)`),边缘像素在亮 / 不亮之间跳变。

**修复**:把 hard threshold 改成 soft threshold(用 smoothstep)。修复后 downsample 不再被边缘跳变拉偏,光晕稳定。

### 21.2 案例 2:tone mapping 后天空出现 banding

**症状**:游戏天空是渐变蓝,tone mapping 后出现明显的水平色带(8 个明显台阶,而不是平滑渐变)。

**诊断过程**:
1. 看 HDR buffer(ACES 之前)——天空渐变平滑,无 banding。
2. 看 LDR buffer(ACES 之后)——banding 明显。
3. Root cause:ACES 把 HDR(0~50 范围)压缩到 LDR(0~1),但 LDR 是 8-bit。渐变蓝从 RGB(0.2,0.4,0.8)到 RGB(0.3,0.5,0.9)的 0.1 差距,在 8-bit 下是 25 个台阶——足够,但 ACES 曲线把这个差距压缩到 0.05,只剩 12 个台阶,banding 出现。

**修复**:用 dithering 在 tone map 后加随机噪声,把 8-bit banding"打散"成肉眼看不到的高频噪点:

```glsl
// 在 tone map 之后,color grading 之前
float dither = (interleaved_gradient_noise(gl_FragCoord.xy) - 0.5) / 255.0;
ldr += vec3(dither);
```

`interleaved_gradient_noise` 是一个 hash 函数,产生 [0,1] 的伪随机值。dithering 加 1/255 的噪声,人眼看不到,但让 banding 消失。

### 21.3 案例 3:color grading LUT 太暗

**症状**:加载一个电影调色 LUT(从 DaVinci 导出的 .cube),画面整体变暗 30%。

**诊断过程**:
1. 在 DaVinci 里看 LUT 预览,调色是"中性偏暖",不是变暗。
2. 看引擎里 LUT 采样结果——确实更暗了。
3. Root cause:**色彩空间不匹配**。DaVinci 的 LUT 是 sRGB 空间→sRGB 空间的映射(即调色前的像素已经是 sRGB),但我的引擎在 **线性空间**做 LUT 采样(ACES 之后还没做 gamma correction)。线性 → sRGB LUT 的结果 = 比 DaVinci 预览暗(sRGB 比线性在暗部更亮)。

**修复**:调整 pipeline 顺序——先做 gamma correction(linear → sRGB),再做 color grading LUT。或者:在 LUT 内部包含 linear → sRGB → 调色 → sRGB → linear 的完整转换(shaper LUT)。

第二种方案是工业标准——电影 LUT 都假设 sRGB 输入输出,游戏引擎用 shaper LUT 做色彩空间转换。

## 22 · 总结:为什么 post-processing 难

post-processing 的工程难点不在单个 pass,而在于**全 pipeline 的协调**:

1. **顺序敏感**。Color grading 在 tone mapping 之前 vs 之后,结果完全不同。Bloom 在 DOF 之前 vs 之后,bloom 形状完全不同。每个 pass 的位置都要想清楚。
2. **色彩空间地狱**。linear、sRGB、Rec.709、Rec.2020、ACEScg、ACEScct——每个 pass 在哪个空间做,转换在哪做,错一个就颜色不对。
3. **分辨率权衡**。half-res 加速 4 倍,但有些 effect 不能 half-res(出现 aliasing)。每个 effect 单独决定。
4. **性能预算**。60fps budget 16.6ms,post-process 占多少?加新 effect 必须从旧 effect 里挤时间。
5. **跨硬件兼容**。Mobile GPU 和 desktop GPU 能力差 10 倍,同一套 post-process 要在不同平台跑——通常用 quality settings 切换。

读完这一篇,你应该能:
- 在自己的 Rust 渲染器里加 HDR pipeline + tone mapping + bloom
- 调 Unreal / Unity / Godot / Bevy 的 post-process 参数时知道每个参数在做什么
- 看真实引擎源码的 post-process 文件不慌
- 遇到 bloom / tone map / color grade 的 bug 时,有系统的诊断思路
- 理解 post-processing 不仅是"加效果",是**渲染管线的最后一道架构**

下一阶段你会接触到 TAA、ray tracing、variable rate shading——这些技术都在 post-processing 的基础上演化。**post-processing 是现代渲染管线的"语言"**,你必须先熟练掌握它,才能跟上图形学的下一个十年。
