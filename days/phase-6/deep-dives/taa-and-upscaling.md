# TAA 与升采样:从 SSAA 到 DLSS / FSR / XeSS 的反走样全景

> 你跟着 HH 走到 Day 358,渲染管线已经能画出一个 3D 场景:模型、变换、深度缓冲、纹理、光照、阴影都有了。但你把相机绕物体转一圈,画面立刻**满是锯齿**——三角形边缘一格一格、远处铁丝网在闪烁、树叶纹理在跳舞。这是 **aliasing**(走样)——信号采样的根本问题。本文从 1970 年代 Crow 的反走样论文讲到 2026 年工业级 **DLSS 4 / FSR 4 / XeSS 2**,涵盖 SSAA、MSAA、FXAA、SMAA、TAA 五代空间算法,再到把 TAA 改造成 upscaler 的工程革命,让你在自己的 HH 项目里能写一个 mini TAA(从 jitter 到 resolve 的完整 GLSL),并看懂 Unreal TAA / DLSS SDK / FSR 2 / XeSS 的源码不被吓到。

## 0 · 为什么要有 TAA 与升采样

把镜头拉近,真实体验一个场景。

你完成 Day 358 后跑自己的渲染器。一个简单的桌椅模型,在屏幕上是 1920×1080。你打开相机环绕功能,慢慢转一圈——**桌子的木纹边缘全是锯齿**,像台阶一样一格一格;**椅子的细腿在远处不停闪烁**,一会儿清晰一会儿模糊;**地板上的瓷砖接缝处产生莫尔条纹**(moiré pattern),一圈一圈的彩色波纹。你以为是光照或纹理 bug,改了半天参数没用。

这不是 bug,是 **aliasing**(走样)。Nyquist-Shannon 采样定理告诉我们:**要把一个连续信号采样到离散像素而不失真,采样频率必须至少是信号最高频率的两倍**。三角形边缘是一条数学上"无限锐利"的曲线——它的频谱是无限的——你的 1080p 屏幕采样频率不够,失真必然发生。这就是你看到锯齿和闪烁的根本原因。

40 多年来图形学发展出五代主流反走样算法:

1. **SSAA**(Supersampling Anti-Aliasing,1980s)— 在更高分辨率渲染然后降采样。最暴力最贵,但质量最高。4× SSAA = 渲染 4× 像素再平均。
2. **MSAA**(Multi-Sample Anti-Aliasing,1996 SGI / 1999 NVIDIA)— 只在三角形边缘做多次采样,几何边缘干净,shader 只跑一次。便宜。
3. **FXAA**(Fast Approximate AA,2009 Timothy Lottes)— 后处理:对最终图像做边缘检测 + 模糊。极便宜但模糊全图。
4. **SMAA**(Enhanced Subpixel Morphological AA,2011 Jorge Jimenez)— FXAA 的进化,用 ML 启发的模式识别做边缘处理。质量更好但仍模糊。
5. **TAA**(Temporal Anti-Aliasing,1986 Vine / 2014 Unreal 4 工业化)— **利用上一帧的像素**。这是革命:不需要更多几何采样,只要把过去几帧的像素加进来。

TAA 之所以在 2014 年才普及(理论上 1986 年就有),是因为它需要一个稳定可重投影的几何管线——直到 Unreal Engine 4 的 "Temporal AA" 论文(Karlis 2014)把整套 jitter + velocity + reprojection + neighborhood clamping 流程工业化,所有 3A 游戏才转向 TAA。

接着 2018 年 NVIDIA DLSS 把 TAA 改造成**升采样器**(upscaler):既然 TAA 能从过去帧采样到"更多像素",那为什么不把它用在"分辨率提升"上?DLSS 1 用神经网络学这个映射,DLSS 2 用神经网络的运动矢量 + 时序累积,DLSS 3 加帧生成(frame generation),DLSS 4 用 transformer 替换 CNN。AMD FSR 1 是纯空间算法(EASU + RCAS),FSR 2 是开源的 TAAU 风格,FSR 3 加帧生成,FSR 4 用 ML。Intel XeSS 1 是神经网络,XeSS 2 加帧生成。Sony PSSR 是 PS5 Pro 的神经网络升采样。

到了 2026 年,几乎所有 3A 游戏都默认开某种 upscaler——不是因为它们想,而是因为**光追 + 高分辨率 + 60FPS 在物理上不可能同时达成**,upscaler 是唯一的妥协方案。理解 TAA / upscaling 是理解现代实时渲染的入场券。

**读完这一篇你能**:

- 用 Rust + glow(OpenGL)实现完整 mini TAA:Halton jitter、velocity buffer、reproject、history accumulation、neighborhood clamp
- 解释为什么 SSAA 是 4× 像素而 TAA 在 4 帧里达到等效覆盖
- 写出 FSR 1 的 EASU(Edge-Adaptive Spatial Upsampling)和 RCAS(Robust Contrast-Adaptive Sharpening)的 GLSL shader
- 区分 TAAU / DLSS / FSR / XeSS / PSSR 的算法差异、平台限制、视觉特性
- 诊断 TAA 的三大缺陷:ghosting(鬼影)、shimmering(闪烁)、soft edges(软化)
- 看 Unreal Engine 5、DLSS SDK、FSR 2 API、XeSS 源码不被吓到
- 在你的 HH 项目里集成一个简化的 TAA resolve pass

## 1 · 走样的物理本质:Nyquist 失守

### 1.1 一个像素就是一个采样点

不要把屏幕的像素想成"小方块"——这是 Alvy Ray Smith 1995 年著名文章《A Pixel Is Not A Little Square》里警告的常见误解。**像素是一个采样点**,在数学上是一个无面积的点。屏幕渲染就是把连续的二维光学信号(从场景投影出来的辐射亮度分布)在这些点上**采样**,然后显示器做重建(每个像素的亮度辐射到周围)。

```
连续信号 (场景的真实 radiance 分布)
    │
    │  采样:在每个像素中心读一个值
    ▼
离散信号 (frame buffer,1920×1080 个浮点数)
    │
    │  重建:显示器把每个值"涂"到周围区域
    ▼
观察图像(视网膜看到的连续图像)
```

走样发生在**采样**这一步。如果原始信号包含的高频成分超过了采样频率的奈奎斯特极限(Nyquist limit = 采样频率的一半),高频成分会**走样**成低频成分——锯齿和闪烁的根源。

### 1.2 三角形边缘的频谱是无限的

考虑一条三角形边缘。数学上,边缘是 step function(阶跃函数):内部 radiance=1,外部 radiance=0,边缘瞬间跳变。step function 的傅里叶变换是什么?

```
step function x(t):
    1 if t ≥ 0
    0 if t < 0

傅里叶变换 X(f) ∝ 1/(i·2πf)  (在 f=0 处有 δ)
```

X(f) 在所有频率 f 都不为零,且衰减很慢(O(1/f))。这意味着 step function 包含**无限高**的频率成分。

现在你采样:在 1920 列像素的中心,各采一点。Nyquist 说"采样频率的一半 = 960 cycles/width"是上限。原始信号有高于 960 的频率——这些频率**走样**成低于 960 的频率,出现在错误位置。视觉上:

- **静态场景下**:走样表现为锯齿(jaggies),边缘一格一格。
- **动态场景下**:每帧锯齿位置不同,边缘看起来在抖动,这就是 **shimmering**(闪烁)或叫 **crawling ants**(蚂蚁爬)。
- **高频纹理**(铁丝网、织物):走样产生 **moiré pattern**(莫尔条纹),彩色波纹。

### 1.3 反走样的两条路

解决走样有两条路:

**路 A:提高采样频率**(supersampling)。如果原始信号有 4000 cycles/width 的高频成分,你用 8000 像素采样就能完全表达。这就是 SSAA 的思路——把 1920×1080 渲染到 3840×2160(4× 像素),然后降采样回 1920×1080。**质量最高,代价最高**。

**路 B:信号预过滤**(prefiltering)。在采样前,用一个低通滤波器去掉超过 Nyquist 的频率成分。这样采样后没有走样(虽然细节丢了)。**质量打折,代价较低**。

工业界两个方案都用,而且经常组合。MSAA 是"路 A 的特化"(只在边缘多采样,不在 shader 多算)。FXAA/SMAA 是"路 B 的特化"(对最终图像做后处理)。TAA 是"路 A 的时序版"(在多帧里累积多个采样,等价于提高采样频率)。

### 1.4 理想的低通滤波器

数学上,完美的反走样需要在每个像素位置采样一个**像素足迹**内的所有信号,然后加权平均。这个加权函数叫**重建滤波器**(reconstruction filter)。

理论上最理想的低通滤波器是 **sinc 滤波器**:`sinc(x) = sin(πx) / (πx)`。它的傅里叶变换是矩形——完美截止高于 Nyquist 的频率。但 sinc 有两个致命问题:

1. 它是无限支持的(在所有 x 都不为零),实现不了
2. 它有 negative lobes(负值),会产生 ringing artifacts(振铃)

工业界用近似的有限支持滤波器:

- **Box filter**(盒滤波):简单平均,1/N。最便宜,质量差。
- **Triangle / Tent filter**(三角滤波):线性权重,质量中等。
- **Gaussian filter**(高斯):高斯权重,平滑但模糊。
- **Catmull-Rom**(3 次样条):有负 lobes,锐利,工业 TAA 标配。
- **Lanczos**(sinc 截断):有负 lobes,锐利但可能振铃。

TAA 的核心创新:**用 jitter + 时序累积,等价于在多个像素位置采样,然后用 Catmull-Rom 做重建**。这是真正的反走样,质量接近 SSAA 但只渲染 1× 像素。

## 2 · SSAA / MSAA / FXAA / SMAA:前 TAA 时代

### 2.1 SSAA:Supersampling(超采样)

SSAA 是最直接的反走样:在更高分辨率渲染,然后降采样。比如 1920×1080 显示,4× SSAA 渲染到 3840×2160,然后每 2×2 像素平均成一个,得到 1920×1080。

**优点**:反走样完美,几何边缘、纹理走样、shader 走样全部解决。

**缺点**:**贵**。4× SSAA 需要 4× 像素 shader 调用、4× 带宽、4× 显存。1080p 60FPS 的场景,4× SSAA 等价于 4K 60FPS,需要 4 倍 GPU 算力。在 RTX 4090 上,这还是够呛的。

SSAA 还有一个变种叫 **OGSSAA**(Ordered Grid SSAA):渲染到整数倍分辨率的规则网格,然后降采样。降采样用 box filter。这就是早期显卡的 "AA" 选项:2x / 4x / 8x。

另一个变种叫 **RGSSAA**(Rotated Grid SSAA):采样位置不是规则网格,而是旋转过的网格。这能更好捕捉接近水平或垂直的边缘(规则网格在 45° 之外的边缘效果差)。RGSSAA 是 PlayStation 1 时代的高级 SSAA。

现代游戏几乎不用 SSAA,因为代价太高。但它是**反走样的金标准**——所有其他算法的视觉质量都和它对比。

### 2.2 MSAA:Multi-Sample(多样本)

MSAA 是 SGI 在 1990 年代为 OpenGL 发明的。核心观察:**走样主要发生在几何边缘**——纹理内部的走样靠 mipmapping(已在 Day 359 讲过),shader 内部走样靠 LOD。所以**只需要在三角形边缘做多次采样**,shader 只跑一次。

MSAA 的实现:

1. **每像素 N 个 sub-sample 位置**(2x / 4x / 8x)。这些位置通常用 Quincunx 或旋转网格。
2. **顶点着色后,光栅化时**对每个 sub-sample 计算深度和模板。如果 sub-sample 在三角形内,记录深度并做深度测试。
3. **像素着色器只跑一次**(在像素中心)。颜色被复制到所有"三角形内"的 sub-sample。
4. **resolve**(解析)阶段:对每个像素的 N 个 sub-sample 颜色取平均,得到最终像素颜色。

```
4x MSAA 的一个像素:

  ●─────●     ● = sub-sample (有独立的 depth/stencil)
  │  X  │     X = pixel center(像素着色器在此运行)
  │     │
  ●─────●

如果三角形覆盖 3/4 个 sub-sample:
  pixel_color = (3 × shader_color + 1 × background) / 4
```

**优点**:几何边缘质量接近 SSAA,但 shader 只跑 1 次。比 SSAA 便宜 4 倍以上。

**缺点**:

1. **不能解决 shader 走样**:像 alpha-tested 物体(树叶、铁丝网)在 shader 里 discard 像素,MSAA 没用——因为这些"边缘"在 shader 内部产生,MSAA 不重新跑 shader。
2. **不能解决高频纹理走样**:如果 mipmap 链没正确生成,纹理仍然闪烁。
3. **不能解决 shading 走样**:像 PBR 镜面高光在像素中心可能错过或撞中,边缘看起来抖动。
4. **大 G-buffer 占用**:Deferred shading(延迟着色)用 G-buffer 存位置、法线、反照率。MSAA 的 G-buffer 需要 N 倍存储。这就是为什么 deferred 引擎很少用 MSAA——存储和带宽太贵。
5. **现代渲染中边缘占比下降**:大场景里 99% 的像素不在边缘,MSAA 收益小但代价大。

工业实践:2000-2010 年代 MSAA 是标准;2010 年后随着 deferred shading 流行和 PBR 高光走样变重要,MSAA 退居次要,TAA 接管。

OpenGL 里开 MSAA:

```rust
// 创建 multisample 纹理(4x)
let mut tex = 0;
gl.GenTextures(1, &mut tex);
gl.BindTexture(glow::TEXTURE_2D_MULTISAMPLE, tex);
gl.TexImage2DMultisample(
    glow::TEXTURE_2D_MULTISAMPLE,
    4,                              // samples = 4x
    glow::RGBA8,
    1920, 1080,
    glow::FALSE,                    // fixed sample locations
);

// 渲染后 resolve(自动通过 framebuffer blit)
gl.BlitFramebuffer(
    src_x0, src_y0, src_x1, src_y1,
    dst_x0, dst_y0, dst_x1, dst_y1,
    glow::COLOR_BUFFER_BIT,
    glow::LINEAR,   // box filter 平均
);
```

注意 `glow::LINEAR` 在 MSAA resolve 里实际是 box filter——把 4 个 sub-sample 平均。这是 GL 标准的强制行为,你没法选更好的滤波器。

### 2.3 FXAA:Fast Approximate AA(NVIDIA 2009)

FXAA 是 NVIDIA 的 Timothy Lottes 在 2009 年开源的。核心思想:**完全跳过几何,直接对最终图像做边缘检测 + 模糊**。

FXAA 算法(简化):

1. 把整个场景渲染到一个 LDR 纹理(注意:FXAA 在 LDR 上工作,HDR 上效果差)。
2. 对每个像素,采样它和 4 个邻居(上下左右)的亮度(luma)。
3. 计算亮度梯度。如果梯度大于阈值,这是个边缘像素。
4. 沿边缘垂直方向找两个端点(亮度最大和最小)。
5. 沿边缘方向做高斯模糊(节省:只模糊边缘,不模糊平坦区域)。
6. 输出模糊后的像素。

**优点**:

- **极便宜**:每像素只 5-10 次纹理采样,在 GTX 1060 上 1080p FXAA < 0.3 ms。
- **解决所有走样**(几何、shader、纹理):因为它是图像空间的。
- **不需要 velocity buffer、不需要 MSAA G-buffer**。

**缺点**:

- **模糊**:边缘被模糊,细节丢失。文字、UI、远处细节受影响最大。
- **不区分真实边缘和纹理**:树叶纹理也会被模糊。
- **静态质量尚可,动态下闪**:FXAA 每帧独立计算,边缘位置帧间不稳定。

FXAA 至今仍是**最便宜的反走样方案**——低配 PC、Switch、手机游戏的首选。Minecraft Java 版默认就是 FXAA。

参考实现:https://github.com/NVIDIA/FX/blob/master/FXAASample.hlsl 这里有 NVIDIA 官方源码。

### 2.4 SMAA:Enhanced Subpixel Morphological AA(Jorge Jimenez 2011)

SMAA 是 FXAA 的进化版,2011 年 Jorge Jimenez(那时在 Universidad de Zaragoza,后来去 Crytek)的论文。核心改进:**用机器学习启发的模式识别代替简单梯度**。

SMAA 分三步:

1. **Edge Detection**(边缘检测):用亮度梯度,但比 FXAA 更精细。结果是一个 edge texture(每个像素标记是否是边缘)。
2. **Pattern Matching**(模式识别):对每个边缘像素,看它的 4 个邻居形状,匹配到一个预定义的边缘模式(L / U / Z 形)。这是 SMAA 的核心:它知道"L 形边缘是文字拐角","Z 形边缘是斜线"等。
3. **Blending**(混合):根据模式,采样对应的"理想"反走样权重,做加权平均。

SMAA 还有一个变种 **SMAA T2x**:把 SMAA 和简化版 TAA 结合,4 帧里 2 帧 jitter + SMAA。这是 The Witcher 3 等游戏的方案。

**优点**:

- 质量比 FXAA 高得多,接近 MSAA 4x。
- 比较便宜(2-3 ms on 1080p GTX 1060)。
- 不需要 velocity buffer。

**缺点**:

- 仍然模糊,虽然比 FXAA 少。
- 仍然有 temporal shimmering(每帧独立)。
- 算法复杂度高,移植到 GLSL 需要大量预处理纹理(area texture、search texture)。

SMAA 至今是 **insufficient TAA 平台的 fallback**(老 GPU、移动端、VR 双目畸变下 TAA 难做)。

参考实现:https://github.com/iryoku/smaa 官方仓库,带 GLSL/D3D 移植。

## 3 · TAA:Temporal Anti-Aliasing(时序反走样)

### 3.1 TAA 的核心思想

TAA 的革命性在于:**既然 SSAA 是采样多个位置,而采样位置不必都在同一帧——我们可以把采样分布在时间上**。

具体怎么做?

1. **每帧 jitter(抖动)相机**:让相机的投影矩阵在每帧偏移一个**亚像素**距离(比如 0.2 像素)。这样每帧采样的位置不同。
2. **保留上一帧的渲染结果**(叫 history buffer)。
3. **重新投影(reproject)**:用 velocity buffer(每个像素的速度向量)算出"上一帧这个像素对应的物体,现在在哪个位置"。
4. **累积**:把上一帧的对应像素和当前帧加权平均,得到反走样后的结果。

如果 jitter 用 8 个位置循环,等价于 8× SSAA。但每帧只渲染 1× 像素——性价比爆炸。

TAA 的算法 1986 年由 Vine 等人在论文里提出,但工业级实现要等到 2014 年 Unreal Engine 4 的 temporal AA 论文(Petter Solberg Karis)。那时 GPU 才足够快、velocity buffer 才成熟、 deferred shading 才普及。从 UE4 开始,几乎所有 3A 游戏都用 TAA 或基于 TAA 的 upscaler。

### 3.2 TAA 完整管线

工业 TAA 的完整管线分六步:

```
帧 N-1 的 history buffer
         │
         │  3. reproject(用 velocity buffer 找上一帧对应像素)
         ▼
帧 N 渲染  ───►  2. velocity buffer  ───►  ┐
(jitter 投影)                              │
                                            │  4. neighborhood clamp
                                            ▼
                                     5. accumulate
                                            │
                                            ▼
                                  6. sharpen + 写入 history buffer
                                            │
                                            ▼
                                       最终输出
```

下面逐步展开。

### 3.3 步骤 1:Sub-pixel Jitter(Halton 序列)

Jitter 的目的:让每帧采样不同的亚像素位置。N 帧累积后,等价于在 N 个位置采样——这就是 SSAA。

**Halton 序列**是工业标准 jitter 序列。它是低差异性(low-discrepancy)序列——比伪随机更均匀。Halton(i, base) 用第 i 个整数,在给定的 base 进制下"翻转"它的位数,得到 [0, 1) 范围的值。

```rust
// Halton 序列生成
fn halton(index: i32, base: i32) -> f32 {
    let mut f = 1.0;
    let mut r = 0.0;
    let mut i = index;
    while i > 0 {
        f /= base as f32;
        r += f * ((i % base) as f32);
        i /= base;
    }
    r
}

// 用 Halton(2) 和 Halton(3) 生成 2D jitter
fn jitter(frame: u64) -> [f32; 2] {
    let i = (frame % 16) as i32 + 1;  // 16 个位置循环
    let x = halton(i, 2);
    let y = halton(i, 3);
    [x, y]
}
```

前 8 个 Halton(2,3) 序列点:

```
i=1: (1/2, 1/3)   ≈ (0.500, 0.333)
i=2: (1/4, 2/3)   ≈ (0.250, 0.667)
i=3: (3/4, 1/9)   ≈ (0.750, 0.111)
i=4: (1/8, 4/9)   ≈ (0.125, 0.444)
i=5: (5/8, 7/9)   ≈ (0.625, 0.778)
i=6: (3/8, 2/9)   ≈ (0.375, 0.222)
i=7: (7/8, 5/9)   ≈ (0.875, 0.556)
i=8: (1/16, 8/9)  ≈ (0.063, 0.889)
```

这些点在 [0,1)² 范围内分布均匀但不规则——没有规则网格的"沿轴 bias"。

把 jitter 应用到投影矩阵:

```rust
fn jittered_projection(proj: Mat4, frame: u64, width: u32, height: u32) -> Mat4 {
    let [jx, jy] = jitter(frame);
    // 把 [0, 1) 映射到 [-1, 1) 的 NDC 偏移,再除以分辨率
    let dx = (jx * 2.0 - 1.0) / width as f32;
    let dy = (jy * 2.0 - 1.0) / height as f32;
    
    // 投影矩阵的 [0][2] 和 [1][2] 元素控制 NDC 的 x/y 偏移
    let mut jittered = proj;
    jittered.x[2 + 0 * 4] += dx;  // 列主序的 m[2][0]
    jittered.x[2 + 1 * 4] += dy;  // 列主序的 m[2][1]
    jittered
}
```

注意 jitter 是**亚像素**的——偏移最多 1 像素。如果偏移大于 1 像素,就会出现明显的图像抖动。

为什么用 Halton 而不是规则网格或真随机?

- **规则网格**(OGSSAA 的逻辑):规则网格对水平/垂直边缘的覆盖率有限——采样点都和边缘平行,容易撞到同一个 sub-pixel 内。Halton 不规则,覆盖更均匀。
- **真随机**:每帧随机点不同,累积不稳定。Halton 是 deterministic 低差异序列,16 个点确定且分布良好。

工业 TAA 用 8 或 16 个 Halton 点循环。

### 3.4 步骤 2:Velocity Buffer(每像素速度)

要 reproject,我们需要知道"当前帧每个像素的物体,在上一帧时在哪个像素位置"。这就是 velocity——每像素的二维速度向量。

velocity 的计算:对每个顶点,知道它的当前 NDC 位置 `curr_ndc` 和上一帧 NDC 位置 `prev_ndc`(用上一帧的 view-projection 矩阵和上一帧的模型矩阵)。光栅化时插值到每个像素:

```glsl
// velocity vertex shader
#version 460 core

layout(location = 0) in vec3 in_pos;       // 当前帧顶点位置(世界空间)
layout(location = 1) in vec3 in_prev_pos;  // 上一帧顶点位置(世界空间)

uniform mat4 u_curr_view_proj;
uniform mat4 u_prev_view_proj;

out vec4 v_curr_clip;
out vec4 v_prev_clip;

void main() {
    v_curr_clip = u_curr_view_proj * vec4(in_pos, 1.0);
    v_prev_clip = u_prev_view_proj * vec4(in_prev_pos, 1.0);
    gl_Position = v_curr_clip;
}

// velocity fragment shader
#version 460 core

in vec4 v_curr_clip;
in vec4 v_prev_clip;

out vec2 out_velocity;

void main() {
    // 透视除法到 NDC
    vec2 curr_ndc = v_curr_clip.xy / v_curr_clip.w;
    vec2 prev_ndc = v_prev_clip.xy / v_prev_clip.w;
    
    // NDC [-1,1] → UV [0,1]
    vec2 curr_uv = curr_ndc * 0.5 + 0.5;
    vec2 prev_uv = prev_ndc * 0.5 + 0.5;
    
    // velocity = prev_uv - curr_uv(像素单位)
    out_velocity = prev_uv - curr_uv;
}
```

注意几点:

1. **需要上一帧的 view_proj 矩阵和上一帧的模型变换**。如果物体是动态的(动画角色、车辆),你要传上一帧的 bone matrix 或 model matrix。
2. **velocity 是 prev_uv - curr_uv**:意思是"从当前帧像素出发,回到上一帧对应像素的位移"。这种约定让 reproject 简单:`prev_uv = curr_uv + velocity`。
3. **静态物体不需要存 prev_pos**:可以用 `prev_view_proj * curr_world_pos`(假设物体没动)。只有动态物体需要单独的 prev_pos attribute(需要"motion vectors" vertex format)。

velocity buffer 用 RG16F 或 RG8 纹理。如果速度都很小(< 0.1),RG8 够了;高速运动(< 1.0)需要 RG16F。大型场景里飞机、赛车的 velocity 可能 > 1.0,需要更高精度。

**Skinning 和 morph target animation 的 velocity**:每个骨骼动画的顶点要在 GPU 端同时跑当前帧和上一帧的 bone matrix。这是骨骼动画 + TAA 集成的复杂点。Unreal Engine 的 GpuSkinnedVelocity.cpp 干的就是这个——它额外跑一次 skinned mesh 的 velocity pass。

### 3.5 步骤 3:Reproject(重投影)

有了 velocity buffer,我们可以从 history buffer 采样。reproject 就是"用 velocity 偏移当前像素坐标,得到上一帧对应位置"。

```glsl
// TAA resolve shader 第一步:reproject
vec2 curr_uv = gl_FragCoord.xy / uResolution;
vec2 velocity = texture(uVelocity, curr_uv).rg;
vec2 prev_uv = curr_uv - velocity;  // 注意符号(根据 velocity 约定)

vec4 history_color = texture(uHistoryTexture, prev_uv);
```

注意:

1. **`prev_uv = curr_uv - velocity`** 还是 `prev_uv = curr_uv + velocity`?这取决于 velocity 的定义。如果 velocity = `prev_uv - curr_uv`(prev - curr),那 `prev_uv = curr_uv + velocity`。如果 velocity = `curr_uv - prev_uv`(curr - prev),那 `prev_uv = curr_uv - velocity`。前一种约定更常见,我们采用 `prev_uv = curr_uv + velocity`。

2. **prev_uv 通常不是整数**:它是浮点数,落在像素之间的位置。所以采样 history buffer 要用**双线性插值**(GL_LINEAR)。这本身是一次"软采样",反走样的另一来源。

3. **遮挡问题**:如果当前像素的物体在上一帧被另一个物体遮挡(比如角色从墙后走出来),从 history buffer 采样到的是墙的颜色——错误的。这就是 **ghosting** 的根源,TAA 最大的痛点。后面讲怎么用 neighborhood clamp 缓解。

4. **屏幕外问题**:如果 prev_uv 跑出 [0, 1] 范围(比如相机剧烈转动),没有 history 可用——直接用当前帧颜色。

### 3.6 步骤 4:Neighborhood Clamping(防止 ghosting)

Ghosting 是 TAA 的核心缺陷:当一个物体进入新区域,history buffer 还没它的历史,reproject 采到错误的旧像素——画面留下物体的"鬼影"。TAA 工业 paper 提供了多种缓解策略,**neighborhood clamping** 是最常用的一种。

核心思想:**如果 history 颜色和当前帧颜色的差异过大,说明 history 不可靠——把它 clamp 到当前帧局部颜色范围内**。

具体步骤:

1. 采样当前像素周围的 3×3 或 5×5 邻居,计算它们的颜色范围(min/max 或更紧的包围)。
2. 如果 history 颜色在这个范围内,直接用 history。
3. 如果 history 超出范围,clamp 到边界。

最简单的 clamp:

```glsl
vec3 curr = texture(uCurrentColor, uv).rgb;
vec3 history = texture(uHistoryColor, prev_uv).rgb;

// 3x3 邻居采样
vec3 neighbor_min = curr;
vec3 neighbor_max = curr;
for (int y = -1; y <= 1; y++) {
    for (int x = -1; x <= 1; x++) {
        if (x == 0 && y == 0) continue;
        vec2 offset = vec2(x, y) / uResolution;
        vec3 c = texture(uCurrentColor, uv + offset).rgb;
        neighbor_min = min(neighbor_min, c);
        neighbor_max = max(neighbor_max, c);
    }
}

// clamp
vec3 clamped_history = clamp(history, neighbor_min, neighbor_max);
```

简单 min/max clamp 有问题:**它在 HDR 颜色上不稳定**(几个极亮的像素让范围太大),而且**它在高光边缘产生颜色偏移**。

工业改进:**variance clipping**(方差裁剪)。计算邻居的均值 μ 和方差 σ²,假设颜色服从正态分布,clamp 到 [μ - γσ, μ + γσ](γ ≈ 1.0)。这给出更紧的包围盒。

```glsl
vec3 mean = (sum_of_neighbors / 9.0);
vec3 variance = (sum_of_squares / 9.0) - mean * mean;
vec3 sigma = sqrt(max(variance, vec3(0.0)));
vec3 neighbor_min = mean - 1.0 * sigma;
vec3 neighbor_max = mean + 1.0 * sigma;
vec3 clamped_history = clamp(history, neighbor_min, neighbor_max);
```

Unreal Engine 的 TAA 用的是 variance clipping + 一个细节:在 YCoCg 颜色空间做 clamp(而不是 RGB),因为 YCoCg 的亮度(luma)和色度(chroma)分离,clamp 更准确。

### 3.7 步骤 5:Accumulate(累积)

有了 clamped history 和当前帧颜色,加权平均:

```glsl
// alpha 是 history 的权重:0.8 ~ 0.95
// 高 alpha = 更平滑(history 主导),但 ghosting 更严重
// 低 alpha = 更锐利(当前帧主导),但反走样效果差
float alpha = 0.9;

vec3 result = mix(curr_color, clamped_history, alpha);
```

alpha 选择是关键 trade-off:

- **alpha = 1.0**:完全用 history,当前帧几乎不贡献。无锯齿但严重 ghosting。
- **alpha = 0.0**:完全用当前帧,等价于无 TAA。无 ghosting 但有锯齿。
- **alpha = 0.8-0.9**:工业典型值。

**adaptive alpha**:动态调整 alpha——在动态区域降低 alpha(更多用当前帧,减少 ghosting),在静态区域提高 alpha(更多用 history,减少锯齿)。Unreal 用 neighbor variance 调 alpha:

```glsl
float adaptive_alpha = mix(alpha * 0.5, alpha, length(variance) / (length(variance) + 0.1));
```

**新像素的 alpha reset**:如果一个像素是"新出现的"(velocity 不连续或 reproject 跑出屏幕),alpha = 0(完全用当前帧)。

### 3.8 步骤 6:Catmull-Rom 重建(可选)

history buffer 采样使用双线性插值,这是 box 滤波器的等价。box 滤波器有负 lobes 不锐利,所以图像模糊。

工业 TAA 用 **Catmull-Rom** 5-tap 滤波器代替 bilinear。Catmull-Rom 是 3 次样条,有负 lobes,锐利但可能振铃。

```glsl
// 5-tap Catmull-Rom(基于双线性优化的版本)
// 参考:https://gist.github.com/TheRealMJP/b1837c9c3314cd0c61a3
vec3 SampleCatmullRom(sampler2D tex, vec2 uv, vec2 texelSize) {
    // 把 uv 中心移到最近的 1/3 像素
    vec2 position = uv * texelSize.zw;  // position in pixels
    vec2 centerPosition = floor(position - 0.5) + 0.5;
    vec2 f = position - centerPosition;
    vec2 f2 = f * f;
    vec2 f3 = f2 * f;
    
    // Catmull-Rom 基函数
    vec2 w0 = -0.5 * f3 + f2 - 0.5 * f;
    vec2 w1 = 1.5 * f3 - 2.5 * f2 + 1.0;
    vec2 w2 = -1.5 * f3 + 2.0 * f2 + 0.5 * f;
    vec2 w3 = 0.5 * f3 - 0.5 * f2;
    
    // 5 个 tap(优化版本,利用硬件 bilinear)
    vec2 w12 = w1 + w2;
    vec2 tc12 = texelSize * (centerPosition + w2 / w12);
    vec3 c12 = texture(tex, tc12).rgb;
    
    vec2 tc0 = texelSize * (centerPosition - 1.0);
    vec2 tc3 = texelSize * (centerPosition + 2.0);
    vec3 c0 = texture(tex, tc0).rgb;
    vec3 c3 = texture(tex, tc3).rgb;
    
    vec3 color = (w0.x + w0.y) * c0 +
                 (w12.x * w0.y + w0.x * w12.y) * vec3(texture(tex, vec2(tc12.x, tc0.y)).rgb +
                                                      texture(tex, vec2(tc0.x, tc12.y)).rgb) +
                 w12.x * w12.y * c12 +
                 (w12.x * w3.y + w3.x * w12.y) * vec3(texture(tex, vec2(tc12.x, tc3.y)).rgb +
                                                      texture(tex, vec2(tc3.x, tc12.y)).rgb) +
                 (w3.x + w3.y) * c3;
    return color;
}
```

(上面这个 5-tap 优化版本利用了硬件 bilinear——把 w1 和 w2 加权采样合并到一次纹理查询里,从 9-tap 降到 5-tap。)

Catmull-Rom 让 TAA 结果更锐利——但同时也减弱了反走样效果(因为负 lobes 增加高频)。工业实践通常 Catmull-Rom 后再做一次 RCAS-style sharpening。

### 3.9 完整 TAA Resolve Shader

把上面所有步骤合起来:

```glsl
#version 460 core

layout(location = 0) out vec4 out_color;

uniform sampler2D uCurrentColor;   // 当前帧(已 jitter 渲染)
uniform sampler2D uHistoryColor;   // 上一帧累积结果
uniform sampler2D uVelocity;       // velocity buffer
uniform vec2 uTexelSize;           // 1.0 / resolution

in vec2 v_uv;

// 在 YCoCg 颜色空间做 clamp(更紧的包围盒)
vec3 RGB_to_YCoCg(vec3 rgb) {
    return vec3(
        0.25 * rgb.r + 0.5 * rgb.g + 0.25 * rgb.b,
        0.5 * rgb.r - 0.5 * rgb.b,
       -0.25 * rgb.r + 0.5 * rgb.g - 0.25 * rgb.b
    );
}

vec3 YCoCg_to_RGB(vec3 ycocg) {
    vec3 rgb;
    rgb.r = ycocg.x + ycocg.y - ycocg.z;
    rgb.g = ycocg.x + ycocg.z;
    rgb.b = ycocg.x - ycocg.y - ycocg.z;
    return rgb;
}

void main() {
    vec2 uv = v_uv;
    
    // --- 1. Reproject ---
    vec2 velocity = texture(uVelocity, uv).rg;
    vec2 prev_uv = uv + velocity;
    
    // --- 2. 当前帧颜色 ---
    vec3 curr = texture(uCurrentColor, uv).rgb;
    
    // --- 3. 邻居范围(YCoCg 空间)---
    vec3 neighbor_sum = vec3(0.0);
    vec3 neighbor_sum_sq = vec3(0.0);
    const int radius = 1;
    for (int y = -radius; y <= radius; y++) {
        for (int x = -radius; x <= radius; x++) {
            vec2 offset = vec2(x, y) * uTexelSize;
            vec3 c = RGB_to_YCoCg(texture(uCurrentColor, uv + offset).rgb);
            neighbor_sum += c;
            neighbor_sum_sq += c * c;
        }
    }
    float N = float((2 * radius + 1) * (2 * radius + 1));
    vec3 mean = neighbor_sum / N;
    vec3 variance = abs(neighbor_sum_sq / N - mean * mean);
    vec3 sigma = sqrt(max(variance, vec3(1e-6)));
    
    // 95% 置信区间(γ = 1.0 大约是 1 σ)
    vec3 neighbor_min = mean - 1.0 * sigma;
    vec3 neighbor_max = mean + 1.0 * sigma;
    
    // --- 4. 采样 history(Catmull-Rom 简化为 bilinear)---
    vec3 history_raw = texture(uHistoryColor, prev_uv).rgb;
    vec3 history_ycocg = RGB_to_YCoCg(history_raw);
    
    // --- 5. Clamp history 到当前帧邻居范围 ---
    vec3 clamped_history_ycocg = clamp(history_ycocg, neighbor_min, neighbor_max);
    vec3 clamped_history = YCoCg_to_RGB(clamped_history_ycocg);
    
    // --- 6. Adaptive alpha(高方差区降低 alpha,减少 ghosting)---
    float v_sigma = length(sigma);
    float alpha = mix(0.85, 0.95, smoothstep(0.0, 0.1, v_sigma));
    
    // --- 7. 屏幕外 reset ---
    bool valid = all(lessThanEqual(prev_uv, vec2(1.0))) && 
                 all(greaterThanEqual(prev_uv, vec2(0.0)));
    if (!valid) alpha = 0.0;
    
    // --- 8. Accumulate ---
    vec3 result = mix(curr, clamped_history, alpha);
    
    // --- 9. 轻微 sharpening(可选)---
    // 用 unsharp mask
    // result = result + 0.1 * (result - blurred);
    
    out_color = vec4(result, 1.0);
}
```

这个 shader 是教学版本——真实工业 TAA 多了上百行优化(快速 neighbor 采样、 Catmull-Rom、Tonemap 空间切换、velocity 用、blending 顺序等)。

### 3.10 Ping-pong History Buffer

TAA 的 history buffer 是个 ping-pong(双缓冲):

- 帧 N:从 history_A 读,resolve 后写 history_B
- 帧 N+1:从 history_B 读,resolve 后写 history_A
- 帧 N+2:从 history_A 读,resolve 后写 history_B
- ...

这样 history 永远是上一帧的 result。GL 实现:

```rust
// 创建两个 history 纹理
let mut history_textures = [0u32; 2];
for i in 0..2 {
    let mut tex = 0;
    gl.GenTextures(1, &mut tex);
    gl.BindTexture(glow::TEXTURE_2D, tex);
    gl.TexImage2D(glow::TEXTURE_2D, 0, glow::RGBA16F, w, h, 0,
                  glow::RGBA, glow::HALF_FLOAT, None);
    gl.TexParameteri(glow::TEXTURE_2D, glow::TEXTURE_MIN_FILTER, glow::LINEAR as i32);
    gl.TexParameteri(glow::TEXTURE_2D, glow::TEXTURE_MAG_FILTER, glow::LINEAR as i32);
    history_textures[i] = tex;
}

// 渲染循环
let mut frame = 0u64;
loop {
    let read_idx = (frame % 2) as usize;
    let write_idx = ((frame + 1) % 2) as usize;
    
    // 1. 用 jittered projection 渲染当前帧到 current_color
    let jittered_proj = jittered_projection(proj, frame, w, h);
    render_scene(jittered_proj, &mut current_color_fbo);
    
    // 2. 渲染 velocity buffer
    render_velocity(prev_view_proj, view_proj, &mut velocity_fbo);
    
    // 3. TAA resolve:读 current_color + history_textures[read_idx],写 history_textures[write_idx]
    taa_resolve_pass(&current_color, &history_textures[read_idx], &velocity,
                     &mut history_textures[write_idx]);
    
    // 4. 最终输出 = history_textures[write_idx]
    blit_to_screen(&history_textures[write_idx]);
    
    // 5. 更新 prev_view_proj
    prev_view_proj = view_proj;
    frame += 1;
}
```

## 4 · TAA 的缺陷与缓解

### 4.1 Ghosting(鬼影)

**现象**:角色从墙后走出来,墙的边缘留下角色的"鬼影"几帧才消失。射击游戏特别明显——快速移动的物体后留尾巴。

**根因**:reproject 错误。当前帧像素的物体在上一帧不在那个位置(被遮挡或刚刚进入屏幕),采样 history buffer 得到错误的旧像素。neighborhood clamp 缓解但不彻底。

**缓解策略**:

1. **Neighborhood clamp**:前面讲过,把 history clamp 到当前帧邻居范围。
2. **Velocity rectification**:检查 reproject 后的颜色是否和当前帧邻居一致;差异过大就降低 alpha。
3. **Disocclusion detection**:用 Hi-Z buffer(层次深度缓冲)检测当前像素是否是新可见的。如果是,alpha = 0。
4. **Object ID buffer**:渲染一个"每像素物体 ID"的 buffer。如果当前帧和上一帧 reproject 后的 ID 不一致,说明像素换了物体——alpha = 0。

工业方案(从简单到复杂):

- Unreal Engine 4 默认 TAA:neighborhood clamp + variance。
- Unreal Engine 5 默认 TAA + TSR(Temporal Super-Resolution):加 Hi-Z based disocclusion。
- The Coalition(Gears 5)的 TAA:object ID buffer,精确检测 disocclusion。

### 4.2 Shimmering(闪烁)

**现象**:静态画面下完美;一动起来,远处细节(铁丝网、树叶、瓷砖)在不停闪烁。**这是 TAA 在动态下质量比静态差的原因**。

**根因**:高频细节在 jitter 下每帧采到不同位置,neighborhood clamp 不能完全"对齐"这些采样。clamp 的范围是当前帧邻居,但邻居本身在 jitter 下每帧不同——所以累积结果帧间不稳定。

**缓解策略**:

1. **更大的 neighborhood**:5×5 而不是 3×3,clamp 范围更紧。代价是更模糊。
2. **Higher alpha**:0.95 而不是 0.85,history 主导更稳定。但 ghosting 更严重。
3. **Frequency separation**:把图像分解为低频和高频,只对低频做 TAA,高频用空间算法。这是 difficult to do 的工业技巧。

shimmering 是 TAA 最难根治的缺陷。即便 DLSS 4 也仍然有 shimmering——只是神经网络版本比纯 TAA 弱一些。

### 4.3 Soft Edges(软化)

**现象**:图像看起来"涂了一层凡士林"——锐度不够,细节模糊。

**根因**:

1. Neighborhood clamp 把边缘 clamp 到平均,损失锐度。
2. Bilinear 采样 history 是 box filter,本身模糊。
3. Adaptive alpha 在边缘降低 alpha,反而保留当前帧锯齿。

**缓解策略**:

1. **Catmull-Rom 替代 bilinear**:前面讲过。
2. **Post-TAA sharpening**:RCAS(robust contrast-adaptive sharpening)或 CAS。FSR 1 的 RCAS 就是干这个的。
3. **Sub-pixel feature recovery**:对于"小于一个像素"的特征(细线、点),用专门的 shader 恢复。

工业方案:几乎所有 TAA 实现都加 RCAS 或 CAS 后处理。

## 5 · TAA 改进:工业级变体

### 5.1 Unreal Engine 5 TSR

UE5 的 TSR(Temporal Super-Resolution)是工业级 TAA 的代表作(2022 年随 UE5 发布)。它把 TAA 和 upscaler 合二为一——可以是 100% 分辨率(纯 TAA),也可以是 50% 分辨率(TAAU 风格升采样)。

关键特性:

1. **Hi-Z based reprojection**:用层次深度缓冲检测 disocclusion,精确度高。
2. **Frequency-aware accumulation**:对低频用长 history(alpha=0.95),对高频用短 history(alpha=0.7),频率分离。
3. **History blur on flicker**:如果 history 闪烁,自动 blur。
4. **Sub-pixel detail reconstruction**:用 Catmull-Rom + frequency 调整恢复细节。

源码在 https://github.com/EpicGames/UnrealEngine 的 `Engine/Source/Runtime/Renderer/Private/TemporalAA/` 目录。核心文件 `TemporalAA.cpp` 和 `TemporalAAShaders.usf`(UE5 的 .usf 是 Unreal Shader File)。

### 5.2 Insomniac's TAA(在 Ratchet & Clank: Rift Apart)

Insomniac 的 GDC 2022 演讲"Modern TAA for PS5"详细讲了他们的 TAA。核心创新:

1. **Object ID based reprojection**:每个物体有唯一 ID,velocity buffer 包含 ID。disocclusion 检测精确。
2. **VRS-compatible**:配合 Variable Rate Shading(可变着色率)。
3. **PS5 专用优化**:用 PS5 的 hardware sampler 加速 neighborhood clamp。

但 Insomniac 没开源。

### 5.3 Sharpening Filter(RCAS)

RCAS 是 FSR 1 的两个组件之一(EASU + RCAS)。RCAS 本质是个 contrast-adaptive sharpening:

```glsl
// RCAS 简化版(FSR 1 官方)
// 输入:中心像素和 4 个邻居,以及 sharpness 参数
vec3 RCAS(sampler2D tex, vec2 uv, vec2 texel_size, float sharpness) {
    vec3 b = texture(tex, uv + vec2(0, -1) * texel_size).rgb;
    vec3 d = texture(tex, uv + vec2(-1, 0) * texel_size).rgb;
    vec3 e = texture(tex, uv).rgb;  // 中心
    vec3 f = texture(tex, uv + vec2(1, 0) * texel_size).rgb;
    vec3 h = texture(tex, uv + vec2(0, 1) * texel_size).rgb;
    
    // 亮度最小/最大,用于限制锐化幅度(防止 halo)
    float bL = dot(b, vec3(0.299, 0.587, 0.114));
    float dL = dot(d, vec3(0.299, 0.587, 0.114));
    float eL = dot(e, vec3(0.299, 0.587, 0.114));
    float fL = dot(f, vec3(0.299, 0.587, 0.114));
    float hL = dot(h, vec3(0.299, 0.587, 0.114));
    
    float minL = min(bL, min(dL, min(eL, min(fL, hL))));
    float maxL = max(bL, max(dL, max(eL, max(fL, hL))));
    float range = maxL - minL;
    
    // 锐化权重
    float hitMin = eL / (4.0 * minL + 0.0001);
    float hitMax = (1.0 - eL) / (4.0 * (1.0 - maxL) + 0.0001);
    float lobe = max(-hitMin, min(hitMax, sharpness));
    
    // 应用
    vec3 sum = b + d + f + h;
    vec3 result = (e + lobe * (e * 4.0 - sum)) / (1.0 + 4.0 * lobe);
    
    return result;
}
```

完整 FSR 1 的 RCAS 在 https://github.com/GPUOpen-Effects/FidelityFX-FSR 的 `ffx-fsr/ffx_rcas.h`。RCAS 比 NVIDIA 的 CAS 更"鲁棒"——不容易产生 halo artifact。

## 6 · 升采样(Upscaling):TAA 的工程革命

### 6.1 为什么要升采样

到了 2018 年,4K 显示器普及,光追(RTX)发布。**问题**:4K + 光追 + 60FPS 在物理上不可能同时达成。RTX 2080 Ti(当时的旗舰)在 4K + RT 在 Control 里只有 25 FPS。

解决方案:**降低实际渲染分辨率,然后升采样到显示器分辨率**。比如 4K 显示器渲染 1080p,4 倍像素节省。但简单的 bilinear upsample 看起来太模糊——这就是 upscaler 的需求:**智能升采样,质量接近原生 4K**。

TAA 给了一个聪明的角度:**既然 TAA 在 N 帧累积采样到不同位置,那 N 帧累积本身就在做"超采样"——为什么不把它直接用在升采样上?**

这就是 **TAAU**(Temporal Anti-Aliasing Upscaler)的思路,Unreal Engine 4.19 引入。

### 6.2 TAAU:Unreal 的简单方案

TAAU 的核心思想:**渲染分辨率低于显示分辨率,但 TAA 累积到显示分辨率**。比如 1920×1080 显示,渲染 1280×720(0.66 scale),但 history buffer 是 1920×1080。

```
render color @ 1280x720  →  TAA resolve  →  output @ 1920x1080
history @ 1920x1080 ──────┘
```

TAA resolve 时,从 1920×1080 的 history reproject 后采样,和 1280×720 的当前帧累积,结果写入 1920×1080。这等价于"4 帧累积等价于 1920×1080 渲染"。

**优点**:实现简单(就是 TAA 加 scale 参数),便宜。

**缺点**:质量打折——1280×720 渲染的细节本身就少,TAA 没法凭空创造。所以 TAAU 在 0.5x 以下 scale 看起来明显模糊。

工业使用:UE4 默认 upscaler,Gears 5、Fortnite 等大量 UE 游戏都用。

### 6.3 DLSS:NVIDIA 的神经网络方案

DLSS(Deep Learning Super Sampling)是 NVIDIA 2018 年随 RTX 20 系发布的。核心思想:**用神经网络学习"低分辨率 → 高分辨率"的映射**。

**DLSS 1**(2018):CNN 神经网络,每帧独立。每游戏训练一个模型。质量参差不齐(每游戏训练一次太贵),最终被淘汰。

**DLSS 2**(2020):时序神经网络。用 velocity buffer 做 reprojection,神经网络处理 history + 当前帧 + velocity → 高分辨率。**统一模型**(不再每游戏训练),质量飞跃。Control、Death Stranding、Cyberpunk 2077 等大量游戏使用。

**DLSS 3**(2022,RTX 40 系):DLSS 2 + Frame Generation(帧生成)。用 optical flow(光流)算法生成中间帧,等价于"插帧"。Cyberpunk 2077 在 RTX 4090 上 4K + RT + Path Tracing 从 35 FPS 提到 100+ FPS。

**DLSS 4**(2025,RTX 50 系):用 transformer 替换 CNN。Transformer 的注意力机制对高频细节重建更好,质量比 DLSS 3 显著提升。还引入 Multi-Frame Generation(多帧生成,一次生成 3 帧)。

DLSS SDK 源码在 https://github.com/NVIDIA/DLSS —— SDK 本身开源,但预训练的神经网络模型只在 NVIDIA GPU 上跑(用 Tensor Core)。

DLSS 算法(简化描述):

1. 当前帧(低分辨率)+ velocity buffer + depth buffer 输入
2. 神经网络推理由 Tensor Core 加速
3. 网络内部学习到了"如何从 history 累积 + 当前帧 + 几何信息重建高分辨率"
4. 输出高分辨率图像

DLSS 2 的神经网络是 Convolutional Neural Network with temporal accumulation——细节是 NVIDIA 商业机密,大致是 U-Net 结构 + attention。

### 6.4 FSR 1:AMD 的空间方案

AMD FSR 1(FidelityFX Super Resolution 1,2021)是**纯空间算法**——不用时序信息,不用神经网络。它就是高质量的 edge-adaptive spatial upscaler。

FSR 1 两个 pass:

1. **EASU**(Edge-Adaptive Spatial Upsampling):边缘自适应的空间升采样。对每个高分辨率像素,看它的低分辨率邻居,根据局部梯度决定如何混合。算法细节复杂,核心是 **directional lanczos**——根据边缘方向选择最佳 1D lanczos 滤波器。
2. **RCAS**(Robust Contrast-Adaptive Sharpening):锐化。前面讲过。

EASU 简化版 GLSL:

```glsl
// FSR EASU 简化(完整版见 AMD 官方源码)
// 关键思想:对每个目标像素,根据源图像的局部梯度方向
// 选择最佳的 1D lanczos 滤波器,并应用
vec3 FSR_EASU(sampler2D src, vec2 uv, vec2 src_texel, vec2 dst_texel) {
    vec2 pos = uv * src_texel / dst_texel;  // 转到源像素坐标
    vec2 fp = fract(pos);
    vec2 p = floor(pos);
    
    // 4-tap lanczos(每方向)
    vec3 sum = vec3(0.0);
    float total_weight = 0.0;
    for (int y = -1; y <= 2; y++) {
        for (int x = -1; x <= 2; x++) {
            vec2 sample_pos = (p + vec2(x, y)) * src_texel;
            vec3 c = texture(src, sample_pos).rgb;
            
            // Lanczos-2 kernel
            float wx = lanczos2(fp.x - float(x));
            float wy = lanczos2(fp.y - float(y));
            float w = wx * wy;
            
            sum += c * w;
            total_weight += w;
        }
    }
    return sum / total_weight;
}

float lanczos2(float x) {
    if (abs(x) >= 2.0) return 0.0;
    if (x == 0.0) return 1.0;
    float px = pi * x;
    return sin(px) * sin(px * 0.5) / (px * px * 0.5);
}
```

完整 FSR 1 源码:https://github.com/GPUOpen-Effects/FidelityFX-FSR。EASU 完整版有 ~500 行,因为做了大量优化(把 16-tap 优化到 8-tap,用硬件 bilinear 的特性,做了边缘方向检测)。

**优点**:**跨平台**(AMD/NVIDIA/Intel/Mobile 都能跑),**开源**,**便宜**。

**缺点**:**质量打折**——纯空间算法没法恢复"小于一个像素"的细节。在 0.5x scale 下质量明显不如 DLSS。

### 6.5 FSR 2:AMD 的时序方案

AMD FSR 2(2022)是**类 TAAU** 的时序算法,但开源 + 跨平台。算法基本是 TAA + reprojection + neighborhood clamp,AMD 实现的版本。

FSR 2 vs DLSS 2:DLSS 用神经网络做"细节重建",FSR 2 用启发式算法(深度感知的 reproject、对象 ID 检测、autoreactive mask 等)。质量在 0.7x 以上 scale 接近 DLSS,0.5x scale 差一些。

FSR 2 源码:https://github.com/GPUOpen-LibrariesAndSDKs/FidelityFX-SDK。整个 SDK 是 C++ + HLSL/GLSL,几百个文件。

### 6.6 FSR 3 & Frame Generation

FSR 3(2023)加 **Frame Generation**(帧生成)。用 AMD 的 Optical Flow 硬件(或者跨平台的 GPU compute shader)算 motion vectors,然后在两帧之间生成中间帧。

光学流量(optical flow)是计算机视觉经典算法——Horn-Schunck 1981。FSR 3 用 GPU 加速版,在 AMD GPU 上有专用硬件(RDNA 3)。

FSR 4(2025,PS5 Pro 用了类似技术)用 ML 替换启发式。但 AMD 没发布 FSR 4 的 PC 版本(可能是模型训练问题)。

### 6.7 XeSS:Intel 的神经网络方案

XeSS(Xe Super Sampling,2021)是 Intel Arc GPU 的方案。和 DLSS 类似用神经网络,但**用 IEEE 标准的 DP4a 指令**(8-bit 整数点积)而非 NVIDIA Tensor Core,所以**跨平台**——能在 AMD/NVIDIA/Intel GPU 上跑(虽然 Intel GPU 上更快)。

XeSS 神经网络比 DLSS 2 略小(参数少),质量在 DLSS 2 和 FSR 2 之间。

XeSS 源码:https://github.com/intel/xess。

### 6.8 PSSR:Sony 的方案

PSSR(PlayStation Spectral Super Resolution,2024,PS5 Pro)是 Sony 的神经网络 upscaler。细节 Sony 没公开,只知道它用 PS5 Pro 的专用 ML 硬件加速。

PSSR 的特点:**专门为 PS5 Pro 的硬件定制**(8.5 TFLOPS ML 算力),极低延迟(< 2 ms)。

### 6.9 升采样方案对比表

| 方案 | 年份 | 厂商 | 算法 | 平台 | 质量评价 | 性能(4K) |
|---|---|---|---|---|---|---|
| TAAU | 2018 | Epic | TAA + upscale | 全平台 | 中等 | < 1 ms |
| DLSS 1 | 2018 | NVIDIA | CNN,每游戏训练 | RTX 20+ | 低-中(初始) | 2-3 ms |
| DLSS 2 | 2020 | NVIDIA | CNN + 时序 | RTX 20+ | 高 | 1-2 ms |
| DLSS 3 | 2022 | NVIDIA | DLSS 2 + Frame Gen | RTX 40+ | 极高 | 2-3 ms |
| DLSS 4 | 2025 | NVIDIA | Transformer + 多帧 | RTX 50+ | 极高+ | 2-4 ms |
| FSR 1 | 2021 | AMD | EASU + RCAS(空间) | 全平台 | 中等(0.7x+) | 0.5-1 ms |
| FSR 2 | 2022 | AMD | TAA + upscale | 全平台 | 高(0.7x+) | 1-2 ms |
| FSR 3 | 2023 | AMD | FSR 2 + Frame Gen | 全平台 | 高 | 2-3 ms |
| XeSS | 2021 | Intel | 神经网络(DP4a) | 全平台 | 中-高 | 1-2 ms |
| PSSR | 2024 | Sony | 神经网络(PS5 Pro) | PS5 Pro | 高 | < 2 ms |

**选型建议**:

- **NVIDIA RTX 40+**:DLSS 3 / 4,质量最好。
- **NVIDIA RTX 20-30**:DLSS 2(不支持 Frame Gen)。
- **AMD / Intel GPU**:FSR 2/3 或 XeSS。
- **跨平台发行**:FSR 2(全 GPU 都能跑,质量稳定)。
- **移动 / Switch**:FSR 1(便宜)+ 算法降级。
- **PS5**:游戏自带 upscaler(通常 FSR 2 + 定制)。
- **PS5 Pro**:PSSR。
- **VR**:不用 TAA(相位差导致眩晕),用 MSAA 或 SSAA。

### 6.10 帧生成(Frame Generation)

帧生成是 2022 年开始的新趋势。核心思想:**渲染 30 FPS,然后帧生成到 60 FPS**——用户看到 60 FPS 的流畅度,但 GPU 只渲染 30 FPS 的内容。

帧生成的算法:

1. 渲染帧 N。
2. 渲染帧 N+1。
3. 在帧 N 和 N+1 之间生成一个"中间帧"(用 motion vector 插值)。
4. 显示顺序:帧 N → 中间帧 → 帧 N+1 → ...

帧生成有两个挑战:

1. **Motion vector 准确性**:光学流量算法对快速运动、复杂场景不准。
2. **UI 处理**:UI 在帧间不变,插值会让 UI 模糊。解决方案:UI 后处理叠加,不进帧生成。

DLSS 3 的帧生成是 NVIDIA 专属(用 Optical Flow Accelerator 硬件)。FSR 3 是软件实现(任何 GPU 都能跑,但慢一些)。

帧生成的"60 FPS"和原生 60 FPS 不一样——输入延迟更高(因为 GPU 在生成你看到的帧时,你的输入还没反映)。所以 DLSS 3 配合 NVIDIA Reflex(降低输入延迟)使用。

## 7 · 历史演化:从 SSAA 到 DLSS 4

让我把 50 年的反走样历史串起来,你会看到每一步都是对前一步的工程化或革命化。

**1978 - Williams shadow map**:Lance Williams 在同一篇论文里实际就提了"用更高分辨率采样减少锯齿"的思想——SSAA 的雏形。

**1986 - Vine TAA**:Vine 等人在论文 "Real-Time Temporal Anti-Aliasing" 第一次提出时序反走样。但那时 GPU 还不存在,论文被埋没。

**1996 - SGI MSAA**:SGI 的 OpenGL Workstation 实现了 MSAA,硬件加速。这是 MSAA 的工业起点。

**1999 - NVIDIA GeForce 256 MSAA**:第一款消费级 MSAA 显卡。MSAA 进入游戏。

**2000-2010 - MSAA 黄金时代**:DirectX 9-10,Halo、Crysis、Call of Duty 全部用 MSAA。8x MSAA 是高端显卡标配。

**2009 - FXAA**:NVIDIA Timothy Lottes 发布 FXAA,后处理反走样开始流行。廉价、跨平台。

**2011 - SMAA**:Jorge Jimenez 发布 SMAA,后处理反走样的质量上限。

**2011 - In-Order TAA**(PlayStation 3 时代):一些 PS3 独占(如 Killzone 3)用了简化的 TAA。但 PS3 GPU 太弱,TAA 效果有限。

**2014 - Unreal Engine 4 TAA**:Karis 的 GDC 演讲"High Quality Temporal Supersampling"工业化了 TAA。从此 UE4 默认 TAA,所有 3A 跟进。

**2016 - DX12 + Variable Rate Shading**:DX12 标准化,GPU 厂商可以暴露更多硬件特性。

**2018 - DLSS 1 + RTX**:NVIDIA 发布 RTX + DLSS。DLSS 1 质量差,但概念革命。

**2019 - TAAU(Unreal 4.19)**:Unreal 把 TAA 改造成 upscaler,4K 游戏开始可行。

**2020 - DLSS 2**:NVIDIA 用统一神经网络替换每游戏训练,质量飞跃。这是 DLSS 真正普及的版本。

**2021 - FSR 1**:AMD 发布开源空间 upscaler。

**2022 - DLSS 3 + FSR 2 + XeSS**:三家都发布了下一代方案。UE5 发布。

**2023 - FSR 3**:FSR 加帧生成,全平台 60+ FPS。

**2024 - PSSR(PS5 Pro) + DLSS 3.5(Ray Reconstruction)**:DLSS 3.5 用神经网络替换传统 denoiser,光追画质革命。PS5 Pro 发布 PSSR。

**2025 - DLSS 4(transformer) + Multi-Frame Generation**:RTX 50 系发布。Transformer 替换 CNN,一次生成 3 帧。

**2026(当前)**:主流 3A 游戏全部用 upscaler,纯原生分辨率渲染成为奢侈选项。Ray Reconstruction(DLSS 3.5+)开始替换传统光追 denoiser。

## 8 · 跨学科联结:信号处理与贝叶斯滤波

### 8.1 TAA 是贝叶斯估计

TAA 的本质:**用过去观测(history)和当前观测(当前帧),估计真实信号**。这是经典贝叶斯估计问题。

数学上,TAA 在做的事:

```
后验 = (先验 × 似然) / 证据
       ↑        ↑
       history  current
```

- **先验(history)**:过去几帧累积的估计,带不确定性(variance)。
- **似然(current)**:当前帧的观测,带噪声(jitter 造成的亚像素变化)。
- **后验(result)**:累积后的新估计。

Neighborhood clamp 在贝叶斯框架里相当于:**限制先验的范围**(prior truncation),防止 history 太离谱。

**Kalman filter**(卡尔曼滤波器)是这种"线性 + 高斯"贝叶斯估计的闭式解,1960 年 Rudolf Kalman 提出。TAA 可以理解为"非线性 Kalman filter"——非线性因为 clamp 操作不是线性的。机器人 SLAM、自动驾驶定位、导弹制导都用 Kalman filter 或其变体(EKF、UKF)。TAA 是同一思想在图形学的应用。

### 8.2 TAA 是多帧 super-resolution

TAA 等价于"多帧超分辨率"(multi-frame super-resolution, MFSR)。MFSR 在卫星遥感、医学影像、 microscopy 用了几十年——把多张低分辨率照片(每张有微小位移)合成一张高分辨率图。

TAA 的 jitter 是人为制造"亚像素位移",让每帧采样到不同的"高分辨率网格"位置。N 帧累积后,理论上可以恢复 N× 的分辨率。这就是 TAAU 的数学基础。

### 8.3 信号处理:Anti-aliasing filter

TAA 的累积操作可以理解为**线性时不变(LTI)滤波器**。每帧加权历史,alpha 决定滤波器的"响应时间":

```
y[n] = (1-α) x[n] + α y[n-1]
```

这是个一阶 IIR 低通滤波器。它的频率响应是:

```
H(ω) = (1-α) / (1 - α e^(-iω))
```

- α=0:无滤波,完全用当前帧。
- α=0.9:截止频率约 0.05 × Nyquist,强低通。
- α=1:无穷低通(只有 DC 通过)。

所以高 alpha 在频域意味着"更激进的低通",这就是为什么 α=0.95 看起来"更稳定但更模糊"。

工业 TAA 的 alpha 不是常数(adaptive alpha),这是非线性时变滤波器——分析起来更复杂,但效果更好。

## 9 · 性能数据

### 9.1 各 AA 算法成本(1080p,RTX 4070)

| 算法 | 渲染分辨率 | AA pass 耗时 | 总开销 |
|---|---|---|---|
| 无 AA | 1080p | 0 | 0% |
| FXAA | 1080p | 0.3 ms | ~2% |
| SMAA 1x | 1080p | 1.2 ms | ~7% |
| TAA | 1080p | 1.5 ms(resolve) + 0.5 ms(velocity) | ~12% |
| MSAA 4x | 1080p | ~4 ms(resolve + extra bandwidth) | ~25% |
| SSAA 4x | 2160p | 0(直接降采样) | +300%(渲染代价) |

(粗略数据,实际因场景和硬件差异很大)

### 9.2 升采样性能(4K 输出,RTX 4070)

| 方案 | 渲染分辨率 | upscale 耗时 | 总耗时 vs 原生 |
|---|---|---|---|
| 原生 4K TAA | 2160p | 5 ms | 100%(基准) |
| TAAU 0.66 | 1440p | 2 ms | 65% |
| TAAU 0.5 | 1080p | 1.5 ms | 45% |
| FSR 1 0.66 | 1440p | 0.8 ms | 60% |
| FSR 2 0.66 | 1440p | 2 ms | 65% |
| FSR 3 0.66 + FG | 1440p | 4 ms | 65% 但 FPS 翻倍 |
| DLSS 2 质量(0.66) | 1440p | 1.5 ms | 60% |
| DLSS 3 质量 + FG | 1440p | 3 ms | 60% 但 FPS 翻倍 |
| DLSS 4 质量 | 1440p | 2 ms | 60% |

(基于 Cyberpunk 2077 RT 复杂场景估算)

### 9.3 内存占用

| 数据 | 1080p 大小 | 4K 大小 |
|---|---|---|
| Velocity buffer(RG16F) | 4 MB | 16 MB |
| History buffer × 2(RGBA16F) | 16 MB | 64 MB |
| Current color | 8 MB | 32 MB |
| Object ID(可选) | 4 MB | 16 MB |
| **TAA 总计** | **32 MB** | **128 MB** |
| **DLSS 内部状态** | +50 MB | +200 MB |

4K + DLSS 总共 ~330 MB——这就是为什么 PS5/Xbox Series X 把 16 GB 内存当标准。

### 9.4 实际游戏数据点

- **Cyberpunk 2077 + RT Overdrive + DLSS 4 Performance**: RTX 5090 上 4K 145 FPS。原生 4K 无 DLSS 在 RTX 4090 上 12 FPS。
- **Alan Wake 2 + Path Tracing + DLSS 3.5**: RTX 4070 上 4K 50 FPS。无 DLSS 不可能跑(0.5 FPS)。
- **Hogwarts Legacy + FSR 3 + FG**: RX 7900 XTX 上 4K 130 FPS。
- **Ratchet & Clank: Rift Apart + Insomniac TAA + FSR 2**: PS5 上性能模式 4K 60 FPS。
- **Spider-Man 2 + DLSS 3**: RTX 4070 上 4K 100 FPS。

数据来源:Digital Foundry、PC Gamer、ComputerBase 等的 2024-2025 评测。

## 10 · 在你 HH 项目里实践

下面把上面所有内容整合,在你 HH 项目里加一个 mini TAA。

### 10.1 集成步骤

假设你的 HH 项目已经有了 Day 358 的渲染管线(模型、变换、深度缓冲、纹理、shader)。集成 TAA 需要:

1. **加 velocity buffer pass**:渲染每个物体的当前帧和上一帧位置,算 velocity 写入 RG16F 纹理。
2. **加 history buffer**:两个 RGBA16F 纹理,ping-pong。
3. **加 jitter**:修改投影矩阵。
4. **加 TAA resolve pass**:运行上面写的 resolve shader。
5. **加 RCAS sharpening**(可选):锐化输出。
6. **(可选)加 scale 参数,变成 TAAU**。

### 10.2 Rust 代码框架

```rust
// src/taa.rs
use glow::*;
use std::mem;

pub struct TaaRenderer {
    pub current_color: TextureRef,
    pub velocity_buffer: TextureRef,
    pub history: [TextureRef; 2],
    pub resolve_program: ProgramRef,
    pub velocity_program: ProgramRef,
    pub width: u32,
    pub height: u32,
    pub scale: f32,        // 1.0 = 纯 TAA,< 1.0 = TAAU
    pub frame: u64,
    pub prev_view_proj: Mat4,
    pub jitter_sequence: Vec<[f32; 2]>,
}

impl TaaRenderer {
    pub fn new(gl: &Context, w: u32, h: u32) -> Self {
        let render_w = (w as f32) as u32;
        let render_h = (h as f32) as u32;
        
        // 创建纹理
        let current_color = create_color_texture(gl, render_w, render_h, RGBA16F);
        let velocity_buffer = create_color_texture(gl, render_w, render_h, RG16F);
        let history_a = create_color_texture(gl, w, h, RGBA16F);
        let history_b = create_color_texture(gl, w, h, RGBA16F);
        
        // 加载 shaders
        let resolve_program = compile_program(gl, TAA_RESOLVE_VS, TAA_RESOLVE_FS);
        let velocity_program = compile_program(gl, VELOCITY_VS, VELOCITY_FS);
        
        // Halton 序列(16 个点)
        let jitter_sequence = (1..=16)
            .map(|i| [halton(i, 2), halton(i, 3)])
            .collect();
        
        Self {
            current_color,
            velocity_buffer,
            history: [history_a, history_b],
            resolve_program,
            velocity_program,
            width: w,
            height: h,
            scale: 1.0,
            frame: 0,
            prev_view_proj: Mat4::identity(),
            jitter_sequence,
        }
    }
    
    pub fn jittered_projection(&self, base_proj: Mat4) -> Mat4 {
        let i = (self.frame % 16) as usize;
        let [jx, jy] = self.jitter_sequence[i];
        
        let render_w = (self.width as f32 * self.scale) as u32;
        let render_h = (self.height as f32 * self.scale) as u32;
        
        let dx = (jx * 2.0 - 1.0) / render_w as f32;
        let dy = (jy * 2.0 - 1.0) / render_h as f32;
        
        let mut p = base_proj;
        p.m[2][0] += dx;  // 根据你的 Mat4 布局调整
        p.m[2][1] += dy;
        p
    }
    
    pub fn render_frame<F>(&mut self, gl: &Context, view_proj: Mat4, render_scene: F)
    where F: FnOnce(Mat4) {
        // 1. jittered projection
        let jittered_vp = self.jittered_projection(view_proj);
        
        // 2. 渲染当前帧 + velocity
        render_scene(jittered_vp);
        
        // 3. TAA resolve
        let read_idx = (self.frame % 2) as usize;
        let write_idx = ((self.frame + 1) % 2) as usize;
        
        unsafe {
            gl.UseProgram(self.resolve_program);
            gl.BindFramebuffer(FRAMEBUFFER, self.fbo_write);
            gl.FramebufferTexture2D(FRAMEBUFFER, COLOR_ATTACHMENT0, TEXTURE_2D,
                                     self.history[write_idx], 0);
            gl.Viewport(0, 0, self.width as i32, self.height as i32);
            
            // 绑定 input textures
            gl.ActiveTexture(TEXTURE0);
            gl.BindTexture(TEXTURE_2D, self.current_color);
            gl.Uniform1i(gl.GetUniformLocation(self.resolve_program, "uCurrentColor"), 0);
            
            gl.ActiveTexture(TEXTURE1);
            gl.BindTexture(TEXTURE_2D, self.history[read_idx]);
            gl.Uniform1i(gl.GetUniformLocation(self.resolve_program, "uHistoryColor"), 1);
            
            gl.ActiveTexture(TEXTURE2);
            gl.BindTexture(TEXTURE_2D, self.velocity_buffer);
            gl.Uniform1i(gl.GetUniformLocation(self.resolve_program, "uVelocity"), 2);
            
            gl.Uniform2f(gl.GetUniformLocation(self.resolve_program, "uTexelSize"),
                         1.0 / self.width as f32, 1.0 / self.height as f32);
            
            // 绘制 fullscreen quad
            draw_fullscreen_quad(gl);
        }
        
        // 4. 更新状态
        self.prev_view_proj = view_proj;
        self.frame += 1;
    }
    
    pub fn final_output(&self) -> TextureRef {
        let write_idx = ((self.frame + 1) % 2) as usize;  // 注意 frame 已 +1
        // 等价:(self.frame % 2) as usize,因为 frame 已经 increment 了
        // 但实际是:刚 render 时是 frame,write_idx = (frame+1) % 2,frame 后 += 1,
        // 所以最后 write_idx = (frame) % 2
        self.history[(self.frame % 2) as usize]
    }
}

fn halton(index: i32, base: i32) -> f32 {
    let mut f = 1.0_f32;
    let mut r = 0.0_f32;
    let mut i = index;
    while i > 0 {
        f /= base as f32;
        r += f * ((i % base) as f32);
        i /= base;
    }
    r
}
```

### 10.3 Velocity Vertex Shader

注意 velocity pass 需要上一帧的变换。最简单方法:每个物体保存 `prev_model_matrix`,每帧 update:

```rust
// 在你的 SceneObject 结构里加:
struct SceneObject {
    // ... 已有字段
    model_matrix: Mat4,
    prev_model_matrix: Mat4,
}

// 每帧更新
fn update_objects(objects: &mut [SceneObject], dt: f32) {
    for obj in objects {
        // 先存上一帧
        obj.prev_model_matrix = obj.model_matrix;
        // 再更新到当前帧
        obj.model_matrix = compute_new_model_matrix(obj);
    }
}
```

velocity shader 接收上一帧和当前帧的 view_proj + model:

```glsl
#version 460 core

layout(location = 0) in vec3 in_pos;  // 静态物体可以省略 prev_pos(用 prev_matrix * pos)
layout(location = 1) in vec3 in_prev_pos;  // 蒙皮动画需要

uniform mat4 uCurrViewProj;
uniform mat4 uPrevViewProj;
uniform mat4 uCurrModel;
uniform mat4 uPrevModel;

out vec4 vCurrClip;
out vec4 vPrevClip;

void main() {
    vec4 curr_world = uCurrModel * vec4(in_pos, 1.0);
    vec4 prev_world = uPrevModel * vec4(in_prev_pos, 1.0);
    vCurrClip = uCurrViewProj * curr_world;
    vPrevClip = uPrevViewProj * prev_world;
    gl_Position = vCurrClip;
}
```

### 10.4 调试技巧

TAA 的调试比一般 shader 难——bug 在多帧累积后才显现。技巧:

1. **可视化 velocity buffer**:`out_color = vec4(velocity * 10.0, 0.0, 1.0)`(放大 10 倍便于观察)。静态区域应该是黑色,运动物体有颜色梯度。
2. **可视化 jitter**:把 jitter offset 加到当前像素颜色上,`out_color = current + vec4(jitter_offset, 0, 0)`。每帧颜色应该轻微闪。
3. **关掉 history clamp**:用 `result = mix(curr, history, 0.9)` 但不 clamp,你会立刻看到 ghosting。然后再开 clamp,观察 ghosting 是否消失。
4. **冻结时间**:暂停场景,观察 jitter 是否在 16 帧后收敛(应该越来越平滑)。
5. **逐帧观察**:用 RenderDoc 抓 16 帧,看 history buffer 演化。

RenderDoc 用法:在 `gl.FramebufferTexture2D` 前后设 breakpoint,抓帧后看纹理。URL: https://renderdoc.org/

### 10.5 集成 FSR 1 RCAS 锐化

如果你的 TAA 结果看起来太软,集成 RCAS 锐化:

```rust
// 在 TAA resolve 后,加一个 RCAS pass
let sharpened = rcas_pass(gl, &taa_result, sharpness = 0.2);
blit_to_screen(&sharpened);
```

RCAS shader 用前面的代码,sharpness 参数 0.0-1.0,推荐 0.1-0.3(0.5 太锐)。

### 10.6 进阶:把它变成 upscaler

把 TAA 变 TAAU 只需要改两处:

1. **render_w = w * scale,render_h = h * scale**:当前帧和 velocity buffer 是低分辨率。
2. **history 仍然是 w × h**:TAA resolve 时双线性采样 history 自动处理 upsample。

```rust
let scale = 0.66;  // 0.5, 0.66, 0.77, 1.0
let render_w = (w as f32 * scale) as u32;
let render_h = (h as f32 * scale) as u32;
```

render_w/h 渲染,histroy w/h 累积——这是 TAAU 的核心。

质量打折:在 scale = 0.5 下,当前帧信息少,TAA 难以重建。FSR 2 / DLSS 通过更复杂的 disocclusion 处理和细节重建缓解。你的 mini TAAU 在 0.5x 下看起来会模糊,但 0.77x 接近原生 TAAU。

### 10.7 在 HH C 代码里(可选)

Casey 的 Handmade Hero 是 C + Handmade 数学库。如果你要把 TAA 移植到 HH 的 C 代码,核心算法不变,只是 API 调用换成 OpenGL C API:

```c
// HH 风格的 TAA jitter
internal void
ApplyJitterToProj(mat4 *Proj, u32 FrameIndex, u32 Width, u32 Height)
{
    u32 Index = (FrameIndex % 16) + 1;
    float Jx = Halton(Index, 2);
    float Jy = Halton(Index, 3);
    
    float Dx = (Jx * 2.0f - 1.0f) / (float)Width;
    float Dy = (Jy * 2.0f - 1.0f) / (float)Height;
    
    // 列主序 Proj[2][0] 和 Proj[2][1]
    Proj->E[2][0] += Dx;
    Proj->E[2][1] += Dy;
}

internal float
Halton(u32 Index, u32 Base)
{
    float F = 1.0f;
    float R = 0.0f;
    u32 I = Index;
    while(I > 0)
    {
        F /= (float)Base;
        R += F * (float)(I % Base);
        I /= Base;
    }
    return R;
}
```

Casey 在 Day 510+ 谈到 AA 时会用到类似的 jitter 函数。你可以提前理解,届时不会陌生。

## 11 · 完整 GLSL TAA Resolve Shader(可直接编译)

下面是完整可编译的 TAA resolve shader,你可以直接放进自己的项目:

```glsl
#version 460 core

// Vertex shader - 全屏三角形
out vec2 v_uv;

void main() {
    // 顶点位置:一个大三角形覆盖全屏
    vec2 positions[3] = vec2[](
        vec2(-1.0, -1.0),
        vec2( 3.0, -1.0),
        vec2(-1.0,  3.0)
    );
    gl_Position = vec4(positions[gl_VertexID], 0.0, 1.0);
    v_uv = gl_Position.xy * 0.5 + 0.5;
}
```

```glsl
#version 460 core

// Fragment shader - TAA resolve
in vec2 v_uv;
out vec4 out_color;

uniform sampler2D uCurrentColor;
uniform sampler2D uHistoryColor;
uniform sampler2D uVelocity;
uniform vec2 uTexelSize;

// 颜色空间转换(在 YCoCg 做 clamp 更稳定)
vec3 RGB2YCoCg(vec3 c) {
    return vec3(
        0.25 * c.r + 0.5 * c.g + 0.25 * c.b,
        0.5 * c.r - 0.5 * c.b,
       -0.25 * c.r + 0.5 * c.g - 0.25 * c.b
    );
}

vec3 YCoCg2RGB(vec3 c) {
    return vec3(
        c.x + c.y - c.z,
        c.x + c.z,
        c.x - c.y - c.z
    );
}

// 9-tap neighborhood sampling(YCoCg 空间)
void SampleNeighborhood9(out vec3 mean, out vec3 sigma) {
    vec3 sum = vec3(0.0);
    vec3 sum_sq = vec3(0.0);
    
    for (int y = -1; y <= 1; y++) {
        for (int x = -1; x <= 1; x++) {
            vec2 offset = vec2(x, y) * uTexelSize;
            vec3 c = RGB2YCoCg(texture(uCurrentColor, v_uv + offset).rgb);
            sum += c;
            sum_sq += c * c;
        }
    }
    
    mean = sum / 9.0;
    vec3 variance = abs(sum_sq / 9.0 - mean * mean);
    sigma = sqrt(max(variance, vec3(1e-6)));
}

void main() {
    // 1. 当前帧颜色
    vec3 curr = texture(uCurrentColor, v_uv).rgb;
    
    // 2. Reproject(velocity = prev_uv - curr_uv)
    vec2 velocity = texture(uVelocity, v_uv).rg;
    vec2 prev_uv = v_uv + velocity;
    
    // 3. 检查 prev_uv 是否在屏幕内
    bool valid = all(greaterThanEqual(prev_uv, vec2(0.0))) &&
                 all(lessThanEqual(prev_uv, vec2(1.0)));
    
    // 4. 邻居采样(YCoCg 空间,做 variance clipping)
    vec3 mean, sigma;
    SampleNeighborhood9(mean, sigma);
    
    // 5. Clamp 范围(mean ± 1.5 sigma,可调)
    vec3 neighbor_min = mean - 1.5 * sigma;
    vec3 neighbor_max = mean + 1.5 * sigma;
    
    // 6. 采样 history
    vec3 history = texture(uHistoryColor, prev_uv).rgb;
    vec3 history_ycocg = RGB2YCoCg(history);
    
    // 7. Clamp history 到 neighborhood 范围
    vec3 clamped_ycocg = clamp(history_ycocg, neighbor_min, neighbor_max);
    vec3 clamped_history = YCoCg2RGB(clamped_ycocg);
    
    // 8. Adaptive alpha
    // - 高方差区域(边缘、动态)用低 alpha
    // - 低方差区域(平坦、静态)用高 alpha
    float v_sigma = length(sigma);
    float base_alpha = 0.9;
    float alpha = mix(base_alpha, 0.6, smoothstep(0.0, 0.2, v_sigma));
    
    // 9. 屏幕外或不可信的 history:alpha = 0
    if (!valid) alpha = 0.0;
    
    // 10. Accumulate
    vec3 result = mix(curr, clamped_history, alpha);
    
    out_color = vec4(result, 1.0);
}
```

把这两个 shader 保存为 `taa_resolve.vs` 和 `taa_resolve.fs`,在 Rust 里编译并使用,你就有了完整的 mini TAA。

## 12 · 真实引擎源码导览

### 12.1 Unreal Engine 5 TAA / TSR

GitHub: https://github.com/EpicGames/UnrealEngine

关键文件:
- `Engine/Source/Runtime/Renderer/Private/TemporalAA/TemporalAA.cpp`:主逻辑。
- `Engine/Source/Runtime/Renderer/Private/TemporalAA/TemporalAAHistorySubsurface.cpp`:SSS 优化的 history 处理。
- `Engine/Shaders/Private/TemporalAA/TemporalAA.usf`:主 resolve shader。
- `Engine/Shaders/Private/TemporalAA/TemporalAAReproject.usf`:reproject shader。

阅读顺序建议:

1. 先看 `TemporalAA.cpp::AddTemploralAAResolvePass`,看 TAA 整体管线怎么组织。
2. 看 `TemporalAA.usf` 的 main 函数,看 resolve shader 的入口。
3. 看 `TemporalAAReproject.usf`,看 velocity + reproject 怎么做。
4. 看 TSR(Temporal Super-Resolution)的同名文件,看 upscaler 怎么扩展 TAA。

UE5 的 TAA 实现是工业级最完整的——700+ 行 C++ + 几千行 shader。读起来吃力,但是金标准。

### 12.2 FSR 2 源码

GitHub: https://github.com/GPUOpen-LibrariesAndSDKs/FidelityFX-SDK

关键文件:
- `sdk/src/backends/shared/ffx_fsr2.cpp`:主逻辑。
- `sdk/src/components/fsr2/ffx_fsr2_tcr_autogen.h`:reactive mask 自动生成。
- `sdk/shaders/fsr2/`:所有 HLSL/GLSL shader。
  - `ffx_fsr2_accumulate_pass.hlsl`:TAA 累积 pass(对应我们的 resolve shader)。
  - `ffx_fsr2_reconstruct_dilated_velocity.h`:velocity 重建。
  - `ffx_fsr2_compute_luminance_pyramid.h`:luminance 金字塔(用于 HDR 处理)。

FSR 2 的 shader 比 UE5 TAA 更"模块化"——每个文件处理一个小问题,易于阅读。建议从 `ffx_fsr2_accumulate_pass.hlsl` 开始,看核心 TAA 累积逻辑。

### 12.3 DLSS SDK

GitHub: https://github.com/NVIDIA/DLSS

DLSS SDK 不开源(只有二进制库),但 SDK 接口开源。看 `Include/nvsdk_ngx_defs.h`,理解 DLSS 的输入输出:

```c
typedef struct {
    NVSDK_NGX_Resourcedecl inWidth, inHeight;
    NVSDK_NGX_Resourcedecl outWidth, outHeight;
    NVSDK_NGX_Handle *pInColor;
    NVSDK_NGX_Handle *pInDepth;
    NVSDK_NGX_Handle *pInMotionVectors;
    float              *pInJitterOffsetX;  // 我们前面讲的 jitter!
    float              *pInJitterOffsetY;
    // ...
} NVSDK_NGX_D3D11_DLSS_EvalParams;
```

你会看到 DLSS 接收的输入和 TAA 一致:低分辨率颜色、深度、运动矢量、jitter offset。差别是 DLSS 用神经网络代替手工 resolve shader。

### 12.4 XeSS

GitHub: https://github.com/intel/xess

XeSS 部分开源——common API 开源,核心模型二进制。看 `xess/include/xess.h` 接口。和 DLSS 接口几乎一样,差别是 XeSS 用 DP4a 指令(全平台)而 DLSS 用 Tensor Core(NVIDIA 专用)。

## 13 · 开源贡献机会

### 13.1 Bevy 引擎的 TAA / upscaler

Bevy 是 Rust 生态的旗舰游戏引擎,GitHub: https://github.com/bevyengine/bevy

Bevy 的主仓库有 `crates/bevy_render/src/view/window/screenshot.rs` 等,但 TAA 实现还在 `bevy_render` 的较早期。社区有 `bevy_taa` 等独立 crate。

可以贡献的方向:

1. **Bevy 主仓库 TAA 实现**:为 Bevy 加原生 TAA 支持。
2. **bevy_fsr / bevy_dlss wrapper**:为社区 crate 加 Rust 绑定。
3. **TAA 调试工具**:可视化 velocity buffer、history buffer 的工具。
4. **文档**:为 Bevy 的 AA 选择写文档(MSAA / TAA / FXAA 各自的权衡)。

### 13.2 wgpu / rend3 / kiss3d

更底层的 Rust 图形生态(wgpu 是 Rust 的 Vulkan/Metal/DX12 抽象)也需要 TAA / upscaler。rend3 是基于 wgpu 的 PBR 引擎,GitHub: https://github.com/rend3/rend3——TAA 实现还在 RFC 阶段。

### 13.3 FSR / XeSS 的 Rust 绑定

`fsr-rs` 是 FSR 2 的 Rust 绑定,在 GitHub: https://github.com/EmbarkStudios/fsr-rs。这是 Embark Studios(The Finals 开发商)维护的。可以贡献:

1. **FSR 3 Frame Generation 支持**。
2. **更好的 API 设计**。
3. **示例项目**。

### 13.4 TAA 教学 demo

社区一直在找好的 TAA 教学 demo——简单、自包含、带可视化。你的 mini TAA 项目打包到 GitHub,加上注释,是很好的贡献。参考已存在的:https://github.com/TheRealMJP/MAS(全 AA 方案对比 demo)。

## 14 · 常见 Bug 与 Troubleshooting

### 14.1 整个画面"鬼影"

**症状**:移动相机时所有物体后留尾巴,停止运动后才稳定。

**原因**:alpha 太高(history 主导过多),或 neighborhood clamp 太松。

**诊断**:
1. 把 alpha 改成 0.0,看是否消失(如果消失,确认是 TAA 累积问题)。
2. 把 alpha 改成 0.5,看是否减轻。
3. 检查 neighborhood clamp 范围是否太宽(sigma 系数 1.5 改成 1.0)。

**修复**:adaptive alpha + 紧的 clamp 范围。

### 14.2 边缘仍然锯齿

**症状**:开了 TAA 但三角形边缘仍然锯齿。

**原因**:
1. **jitter 没生效**:检查 projection 矩阵是否每帧变化。
2. **velocity buffer 错误**:velocity 应该接近 0 在静态区域。可视化检查。
3. **alpha 太低**:0.5 太低,改成 0.9。
4. **history buffer 没正确 ping-pong**:检查读写索引。

### 14.3 屏幕角落有奇怪的颜色

**症状**:屏幕四个角或边缘有红色/绿色/蓝色的奇怪颜色。

**原因**:neighborhood clamp 在边缘采到屏幕外的值(GL 默认是黑色或 repeat)。

**修复**:纹理用 `glow::CLAMP_TO_EDGE` 边界:

```rust
gl.TexParameteri(glow::TEXTURE_2D, glow::TEXTURE_WRAP_S, glow::CLAMP_TO_EDGE as i32);
gl.TexParameteri(glow::TEXTURE_2D, glow::TEXTURE_WRAP_T, glow::CLAMP_TO_EDGE as i32);
```

### 14.4 高速运动物体消失或闪烁

**症状**:高速运动的物体(子弹、车辆)在画面里消失或闪烁。

**原因**:
1. **velocity buffer 精度不够**:RG8 在高速下精度不够,换 RG16F。
2. **Object ID 检测**:物体在上一帧被遮挡,history 是错误颜色。需要 disocclusion detection。
3. **Neighborhood clamp 太紧**:把快速运动物体的颜色 clamp 掉了。

**修复**:高速物体场景考虑用 object ID buffer 做精确 disocclusion。

### 14.5 文字 UI 也被 TAA 模糊

**症状**:游戏 UI 文字看起来软。

**原因**:TAA 在 UI 上也运行了。

**修复**:UI 在 TAA 之后绘制——TAA 只对 3D 场景,UI 是后处理。

```rust
// 渲染顺序
render_3d_scene_with_jitter();      // 1. 3D 场景(带 jitter)
render_velocity();                   // 2. velocity
taa_resolve();                       // 3. TAA
rcas_sharpen();                      // 4. 锐化
render_ui_on_top();                  // 5. UI(在 TAA 之后,不被 TAA 影响)
swap_buffers();
```

## 15 · 展望:2026 之后

### 15.1 神经网络 denoiser(DLSS 3.5 RR)

DLSS 3.5 引入了 **Ray Reconstruction**(RR)——用神经网络替换传统光追 denoiser。传统光追每像素采样 1-4 个光线路径,然后用 SVGF / ReLAX 等 denoiser 时序累积到无噪声图像。RR 用神经网络代替 denoiser,质量更高。

RR 的革命意义:**光追管线和 TAA / upscaler 融合**——神经网络同时处理 denoise、TAA、upscale,不再分离 pass。

### 15.2 Transformer-based upscaler(DLSS 4)

DLSS 4 用 transformer 替换 CNN。Transformer 的自注意力机制能更好捕捉长程依赖,质量显著提升。

未来方向:diffusion model based upscaler(更慢但质量飞跃)。

### 15.3 全屏神经渲染

终极方向:神经网络直接从场景参数(G-buffer、lighting)输出最终像素,跳过传统光栅化管线。这是 NVIDIA 的 "Instant Neural Graphics"(NeRF 实时化)研究方向。

但目前(2026)还太慢,2-3 年内不可能工业落地。

### 15.4 你的角色

作为 HH 学习者,你现在的任务是:**理解 TAA / upscaler 的算法原理**,这样未来神经网络方案出现时,你知道它在解决什么问题(走样 + 信号重建)、为什么之前用 TAA(便宜、跨平台)、为什么转用神经网络(质量更好,但需要专用硬件)。

工业界永远在权衡——TAA 不是"最佳",是"特定约束下的最佳"。理解了约束,你才能判断新方案是否真的更好。

## 16 · 关联 Day

- **铺垫**:Day 358(深度缓冲)— TAA 需要 depth 做 disocclusion;Day 359(mipmap / 纹理)— 走样的另一半;Day 360+(光照)— PBR 高光在 TAA 下的 shimmering
- **当天**:这篇 deep dive
- **后续**:HH 项目可能后续会涉及 AA(估计在 Day 500+),那时回头读这一篇,你会看到 Casey 的 C 实现 vs 本文的 Rust / GLSL 实现的对应关系。

## 17 · 自检清单

读完这一篇,你应该能回答:

1. 为什么 step function 的频谱是无限的,这和锯齿有什么关系?
2. SSAA 4× 和 MSAA 4x 在像素 shader 调用次数上有什么差别?
3. FXAA 为什么模糊?SMAA 比它强在哪?
4. Halton 序列比规则网格好在哪?比真随机呢?
5. Velocity buffer 的 RG16F 和 RG8 怎么选?精度有什么影响?
6. Reproject 后 prev_uv 在屏幕外,怎么处理?
7. Neighborhood clamp 在 YCoCg 空间比 RGB 空间好在哪?
8. Adaptive alpha 怎么实现?为什么在边缘降低 alpha?
9. TAA 的 ghosting 和 shimmering 哪个更难根治,为什么?
10. TAAU 和 TAA 在算法上的差别是什么?
11. DLSS 2 和 FSR 2 的核心差别(神经网络 vs 启发式)?
12. 为什么 FSR 1 在 0.5x scale 下质量差?
13. 帧生成为什么有"输入延迟"问题?
14. Catmull-Rom 比 bilinear 好在哪?有什么代价?
15. RCAS 锐化的原理是什么,sharpness 参数怎么调?

如果你能流畅回答 12 题以上,你就理解了 TAA / upscaler 的核心。剩下的是工程实践——把这些算法在你的 HH 项目里跑起来,看它们在真实场景下的表现。

## 18 · 延伸阅读

外部稳定 URL:

- **The Graphics Codex**(MJP 的博客)— 包含 TAA / FSR / DLSS 大量深度文章:https://blog.demofox.org/
- **Interpolation of TAA**(Karis 2014 GDC)— UE4 TAA 工业化论文:https://www.advances.realtime-translation.com/s2014/
- **FSR 1 白皮书**:https://gpuopen.com/fidelityfx-superresolution/
- **FSR 2 白皮书**:https://gpuopen.com/fidelityfx-superresolution-2/
- **DLSS SDK 文档**:https://github.com/NVIDIA/DLSS
- **XeSS 文档**:https://github.com/intel/xess
- **TheRealMJP/MSAAFilter**(探索 MSAA 滤波器的 demo):https://github.com/TheRealMJP/MSAAFilter
- **TheRealMJP/SortibleAlphaTested**(TAA + alpha test 经典 demo):https://github.com/TheRealMJP/AlphaTestedGS

真实开源源码:

- **Unreal Engine 5 TAA/TSR**:https://github.com/EpicGames/UnrealEngine 的 `Engine/Source/Runtime/Renderer/Private/TemporalAA/`
- **FSR 2 完整源码**:https://github.com/GPUOpen-LibrariesAndSDKs/FidelityFX-SDK 的 `sdk/src/components/fsr2/`
- **DLSS SDK 接口**:https://github.com/NVIDIA/DLSS
- **XeSS 接口**:https://github.com/intel/xess
- **Bevy TAA 探索**:https://github.com/bevyengine/bevy/pulls?q=TAA
- **Casey HH Day 510+ AA 讨论**(视频片段):https://guide.handmadehero.org/code/

## 结语

TAA 和 upscaler 是现代实时渲染的核心技术——它解决的不是"边缘锯齿"一个具体问题,而是**信号重建**这个根本问题。从 1978 年 Williams 的反走样思想,到 2014 年 Karis 工业化 TAA,到 2020 年 DLSS 2 用神经网络重建细节——这是 50 年信号处理和图形学的融合。

你读完这一篇,应该具备了:

1. **从零写 TAA** 的能力——Halton、velocity、reproject、clamp、accumulate 五件套。
2. **理解工业方案** 的能力——看 UE5 / FSR / DLSS 源码不被吓到。
3. **诊断 TAA bug** 的能力——ghosting、shimmering、soft edges 的根因和缓解。
4. **判断未来方向** 的能力——RR、transformer upscaler、neural rendering 都建立在 TAA 的基础上。

接下来在你 HH 项目里跑一个 mini TAA。第一次看到 jitter 工作起来、history buffer 累积出无锯齿画面,你会感受到"图形学的魔法"——这是值得享受的时刻。

---

**附录 A**:Halton 16 点序列(可直接 copy)

| i | Halton(2) | Halton(3) | (x, y) 像素偏移(假设像素中心采样) |
|---|---|---|---|
| 1 | 0.500 | 0.333 | (+0.0, +0.083) |
| 2 | 0.250 | 0.667 | (-0.250, +0.417) |
| 3 | 0.750 | 0.111 | (+0.250, -0.389) |
| 4 | 0.125 | 0.444 | (-0.375, -0.056) |
| 5 | 0.625 | 0.778 | (+0.125, +0.278) |
| 6 | 0.375 | 0.222 | (-0.125, -0.278) |
| 7 | 0.875 | 0.556 | (+0.375, +0.056) |
| 8 | 0.063 | 0.889 | (-0.437, +0.389) |
| 9 | 0.563 | 0.037 | (+0.063, -0.463) |
| 10 | 0.313 | 0.370 | (-0.187, -0.130) |
| 11 | 0.813 | 0.704 | (+0.313, +0.204) |
| 12 | 0.188 | 0.148 | (-0.312, -0.352) |
| 13 | 0.688 | 0.481 | (+0.188, -0.019) |
| 14 | 0.438 | 0.815 | (-0.062, +0.315) |
| 15 | 0.938 | 0.259 | (+0.438, -0.241) |
| 16 | 0.031 | 0.593 | (-0.469, +0.093) |

偏移 = (Halton - 0.5) × 1.0 像素。

**附录 B**:常用 AA 算法的 Rust crate

- `wgpu`:跨平台 GPU 抽象,可以用来实现 TAA。
- `glow`:OpenGL wrapper(本文用的)。
- `rend3`:基于 wgpu 的 PBR 引擎,可以参考其架构。
- `bevy_render`:Bevy 的渲染子系统。
- `fsr-rs`:FSR 2 Rust 绑定。
- `xc2-render`:社区项目,实现了 TAA + FSR。

**附录 C**:术语对照表

| 英文 | 中文 | 解释 |
|---|---|---|
| Aliasing | 走样 | 采样频率不足导致的高频信号失真 |
| Anti-aliasing | 反走样 | 减少走样的算法 |
| Jitter | 抖动 | 亚像素位置偏移,用于时序采样 |
| Reproject | 重投影 | 把上一帧像素位置映射到当前帧 |
| Velocity buffer | 速度缓冲 | 每像素的二维速度向量 |
| History buffer | 历史缓冲 | 上一帧累积结果(双缓冲) |
| Neighborhood clamp | 邻域截断 | 把 history 限制到当前帧邻居范围 |
| Ghosting | 鬼影 | TAA 缺陷:运动物体后留尾巴 |
| Shimmering | 闪烁 | TAA 缺陷:动态下高频细节抖动 |
| Disocclusion | 新可见 | 物体从遮挡中露出 |
| Upscaling | 升采样 | 把低分辨率图像升到高分辨率 |
| Frame Generation | 帧生成 | 用 motion vector 插值生成中间帧 |
| Super-sampling | 超采样 | 在更高分辨率渲染再降采样 |
| Multi-sampling | 多采样 | 只在边缘多次采样 |
| Catmull-Rom | 卡特穆尔-罗姆 | 3 次样条插值,有负 lobes |
| Lanczos | 兰乔斯 | sinc 滤波器的截断近似 |
| RCAS | 鲁棒对比度自适应锐化 | FSR 1 的 sharpening pass |
| EASU | 边缘自适应空间升采样 | FSR 1 的 upscaler pass |
| Tensor Core | 张量核心 | NVIDIA 的矩阵加速硬件 |
| DP4a | 4 元素点积 a | Intel/AMD/NVIDIA 都支持的 8-bit 整数点积指令 |
