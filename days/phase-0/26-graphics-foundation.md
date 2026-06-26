---
article: 26
phase: 0
title: "图形学基础:颜色 / 三角形 / 投影 / 光栅化 / 着色 / 纹理 / GPU"
type: concept
difficulty: 5
duration: "8-10h"
domains: [graphics, game, rust, linux, math]
prereqs: ["14-math-foundations", "20-math-foundation-extended"]
---

# 26 · 图形学基础:从像素到 GPU 渲染管线

> 你跟着 Handmade Hero 走到 Phase 1,Casey 教你"在内存里画一个像素"——你写 `backbuffer[y*W + x] = 0xFFFFFFFF`,这个白色的 32-bit 整数被显卡搬到屏幕上,你就看见了一个白点。这是**软件渲染**:CPU 算每个像素,GPU 只负责显示。但走到 Phase 5,Casey 突然让你写 `gl_Position = vec4(pos, 1.0)`、`gl_FragColor = vec4(1.0)`——**你在写 shader,在用 GPU 的几千个核并行算像素**。中间发生了什么?为什么"画三角形"突然变成一个工程难题?这一篇讲完,你能理解从"CPU 画一个像素"到"GPU 画一百万个三角形"之间所有底层概念。你不写一行 OpenGL,但你看任何 Phase 5+ 的代码都不会再被术语吓到。

## 0 · 为什么要有这一天

让我把镜头拉到一个具体场景。

你跟着 Handmade Hero 走到 Phase 1。Casey 教你这样画一条线:

```rust
fn draw_line(buf: &mut [u32], w: usize, x0: i32, y0: i32, x1: i32, y1: i32, color: u32) {
    let dx = (x1 - x0).abs();
    let dy = (y1 - y0).abs();
    let sx = if x0 < x1 { 1 } else { -1 };
    let sy = if y0 < y1 { 1 } else { -1 };
    let mut err = dx - dy;
    let (mut x, mut y) = (x0, y0);
    loop {
        buf[(y as usize) * w + (x as usize)] = color;
        if x == x1 && y == y1 { break; }
        let e2 = 2 * err;
        if e2 > -dy { err -= dy; x += sx; }
        if e2 < dx { err += dx; y += sy; }
    }
}
```

跑起来——线出来了。CPU 一个一个像素算,在 1080p 屏幕上一帧大概 200 万像素,CPU 一个核 4 GHz,理论上算一帧 0.5ms。你想"够了"。

然后你画一个旋转的 3D 角色,1 万个三角形,每个 100 像素——100 万像素的填充率,CPU 算每个像素要"插值 UV、采样纹理、做光照计算",一帧 CPU 算 50ms——**20 FPS**。你换 8 核并行,理论 4ms——但同步开销让你只到 10ms,**勉强 100 FPS**。然后你想加阴影、加反射、加后期处理——CPU 直接死亡。

**这就是为什么图形必须用 GPU**。GPU 不是"更快的 CPU",而是**完全不同的架构**:它有几千个核,每个核很慢但**一起跑同样的指令**(SIMT)。它**专门为"画像素"这种大批量、低分歧的工作设计**。CPU 是 4 个博士,GPU 是 4000 个本科生——你让 4 个博士解 4000 道简单算术题,他们慢死;你让 4000 个本科生一人一题,瞬间搞定。

但要用 GPU,你必须先理解一堆概念:**颜色空间、三角形、投影矩阵、光栅化、着色、纹理、shader、管线**。每个词都是一个深坑。Phase 5 直接教你写 OpenGL,但中间概念没铺垫——这一篇就是补这个坑。

让我把"看起来魔法"的东西拆开。你以后看到任何一段图形代码,都能回答:**这是处理哪个阶段的?为什么这样写?换一种写法会怎样?**

**学完今天,你应该能**:
- 解释 sRGB 和 gamma 2.2 不是一回事
- 解释为什么 GPU 用三角形而不是四边形或五边形
- 从零推导正交和透视投影矩阵
- 解释 z-buffer 为什么能解决遮挡
- 解释顶点着色器和片元着色器的边界
- 解释为什么纹理需要 mipmap
- 解释 GPU 的 SIMT 模型,以及 warp / wavefront 是什么
- 写一个最小的 wgpu 程序,画一个三角形
- 看懂 Phase 5 的 OpenGL 代码,不被任何术语吓到

## 1 · 颜色感知基础

### 1.1 你的眼睛是个奇怪的传感器

很多人以为"颜色是物理属性"——一个苹果"是"红色的。这是**朴素实在论**,错了。

物理世界只有**电磁波**,有频率(波长)和振幅(强度)。可见光波长大概 380nm(紫)到 740nm(红)。"红色"是这个光谱里的一段——更准确说,**你的眼睛的某个感受器对这段波长反应强烈**,你大脑把这种反应解释成"红"。

你的视网膜有三种**视锥细胞**(cone cell),按敏感波长分为 L、M、S:

- **L cone(Long)**:峰值约 560nm,对黄绿光敏感(其实也大量反应红光,所以俗称"红")
- **M cone(Medium)**:峰值约 530nm,对绿光敏感
- **S cone(Short)**:峰值约 420nm,对蓝光敏感

任何进入你眼睛的光,被这三种细胞"采样"成三个数字(L, M, S)。**这三个数字就是你看到的"颜色"的全部信息**。所以颜色本质是 3 维向量。

这个事实有个推论:**存在无穷多个不同的光谱,产生同样的 (L, M, S) 反应**——你看到的"红色"可能是单一 700nm 的红光,也可能是 600nm+650nm 混合。你的眼睛**无法区分**这两种物理输入,它们对你而言是"同一种红"。这叫**metamer**(同色异谱)。

整个显示技术的基石就是 metamer:**显示器只发三种纯色光(红绿蓝),你的眼睛被骗,以为是无数种颜色**。

### 1.2 CIE 1931 色度图:把所有可见颜色画出来

1931 年,国际照明委员会(CIE)做了一个实验:让人坐在暗室,调整三种纯色光的强度,直到混合光看起来等于某个测试光。他们收集了大量数据,构造了一个数学模型——**CIE 1931 色彩空间**。

CIE 1931 定义了三个**虚拟**基色 X、Y、Z(不是真实的光,是数学构造),任何可见光都能表示成 (X, Y, Z) 三个非负数。把 X、Y、Z 归一化成 (x, y) 二维坐标,所有可见颜色画在一张二维图上,这就是著名的**马蹄形色度图**(chromaticity diagram)。

色度图的关键性质:
- **马蹄边界**:对应**纯波长**(光谱色),从 380nm 紫到 740nm 红
- **底部直线**(紫线):紫不是纯波长,是红+蓝混合
- **内部**:所有可见颜色都在马蹄内
- **白点**:马蹄中心区域,各种"白"

色度图告诉你**哪些颜色"存在"**(物理可产生),以及**哪些颜色超出了你的显示器能力**。比如纯激光的绿光(spectral green)非常鲜艳,但你的显示器(用 LED 模拟绿)永远到不了那个鲜艳度——这是物理限制,不是技术不够好。

### 1.3 色彩空间:sRGB / AdobeRGB / DCI-P3 / Rec2020

CIE 1931 是"参考系",但日常用的是它的子集,叫**色彩空间**(color space)。一个色彩空间定义:**选三个基色(在 CIE 图上的三个点)、一个白点,这三点围成的三角形就是该空间能表示的颜色范围**(gamut)。

| 色彩空间 | 用途 | Gamut 大小 |
|---|---|---|
| **sRGB** | 网页 / 普通显示器 / 默认 | 最小(1996 年 HP+微软设计,匹配当时 CRT) |
| **AdobeRGB** | 专业摄影 | 比 sRGB 大,主要在青绿色区域扩展 |
| **DCI-P3** | 数字影院 / 苹果设备 | 比 sRGB 大,主要在红色区域扩展 |
| **Rec2020** | 4K/8K 电视(HDR) | 很大,覆盖 75% 可见颜色 |
| **ACES AP0** | 电影制作 | 极大,包含甚至"假想"颜色(超出可见) |

你写游戏,**默认所有纹理和颜色都是 sRGB**。如果你的显示器支持 P3(现代 MacBook、iPhone 都支持),你的游戏看起来比 sRGB 屏幕更鲜艳——但你必须正确处理"颜色管理",否则颜色会变得**过度饱和**(因为 P3 屏把 sRGB 数据当 P3 解释)。

### 1.4 色温:黑体辐射和"白"是相对的

一个铁块加热到 1000K,发红光;4000K,发白光;8000K,发蓝白光。这叫**黑体辐射**——任何物体加热都会发光,颜色随温度变化。**色温**就是用开尔文温度描述颜色。

- 1500K:蜡烛、火光,深橙
- 2700K:白炽灯,暖白(微黄)
- 4000K:中性白
- 6500K:**标准日光白**(sRGB 和大多数色彩空间的白点就是 6500K,D65)
- 10000K:阴天/北欧天空,蓝白

你的眼睛有个神奇能力:**自动白平衡**。你在蜡烛光下看白纸,它物理上是橙色的,但你的大脑"知道"它是白的,你看到的就是白。但相机不会——拍出来是橙的。所以相机有"白平衡"功能。

游戏里同样:**白天和黄昏的"白"是不同的**。Casey 在 HH 里经常调"环境光颜色",这就是手动白平衡。

### 1.5 Gamma 修正:为什么屏幕不是线性的

这是新手最容易翻车的概念。让我从现象开始。

你写代码:

```rust
let color = 0.5;  // 你想画一个"中等灰"
buf[y*W + x] = (color * 255.0) as u32;  // 写到 8-bit 像素
```

你以为这个像素的物理亮度是"最大亮度的 50%"。**错**。

CRT 显示器(老式显像管)有个物理特性:**输入信号和实际亮度不是线性关系**。输入 0.5(数字),实际亮度只有约 0.22(物理亮度)。具体说,亮度 ≈ 输入^2.5(2.5 是 CRT 的"gamma 值")。

```text
输入 0.0  → 亮度 0.0    (黑)
输入 0.5  → 亮度 0.5^2.5 ≈ 0.177  (中灰变成了深灰!)
输入 1.0  → 亮度 1.0    (白)
```

奇怪的是,现代 LCD/OLED 屏幕故意继承了 CRT 的这种非线性,**因为这恰好和人眼对暗色更敏感的特性匹配**——8-bit 在线性空间下,0-100 段人眼觉得都是"很暗",200-255 段人眼觉得都"差不多白"。把 8-bit 用在 gamma 空间下,暗区有更多码字,**视觉上均匀分布**。

**sRGB 曲线**是标准化的"gamma"(其实是分段函数,大致等于 gamma 2.2):

```text
sRGB 输入 0.0  → 线性亮度 0.0
sRGB 输入 0.5  → 线性亮度 ≈ 0.214
sRGB 输入 1.0  → 线性亮度 1.0
```

**为什么这对你写游戏有影响**?因为**光照计算必须在线性空间**。如果你直接在 sRGB 空间做 `lighting = albedo * light_intensity`,你得到的是错误结果(因为 (0.5)^2.2 * 2 ≠ 1.0,实际亮度翻倍后不是预期值)。

正确流程:
1. **读取纹理**(sRGB 编码)→ 自动转线性
2. **光照计算**(线性空间)
3. **写回 framebuffer**(线性)→ 转回 sRGB

```rust
// 错误:直接在 sRGB 空间混合
let blended = (a + b) / 2.0;

// 正确:转线性,混合,转回
let a_lin = srgb_to_linear(a);
let b_lin = srgb_to_linear(b);
let blended_lin = (a_lin + b_lin) / 2.0;
let blended = linear_to_srgb(blended_lin);
```

OpenGL 有 `GL_SRGB8_ALPHA8` 纹理格式和 `GL_FRAMEBUFFER_SRGB` 开关,**自动**在采样时转线性、写入时转回。Casey 在 HH 里特别强调这个,因为错了你的游戏就"看起来太暗或太亮"。

### 1.6 HDR:亮度动态范围

传统 sRGB 的亮度上限是"白"(线性 1.0),大概是显示器的 100 nit(每平方米 100 坎德拉)。但现实世界:太阳直射 16 亿 nit,室内灯 1000 nit,阴影里 10 nit。**sRGB 完全无法表达这种亮度差异**——超过 1.0 的部分被截断到白。

**HDR(High Dynamic Range)** 是解决方案:
- **HDR 显示器**:能发 1000-4000 nit 亮度(普通 sRGB 显示器只能 250-400)
- **HDR 格式**:每通道 10/12/16 bit,而不是 8 bit
- **色调映射**(tone mapping):把线性 HDR 值(可能 0-10000)压缩到屏幕能显示的范围(0-1000),让画面看起来"自然"

```rust
// Reinhard tone mapping(最简单的)
let hdr_color = light_intensity; // 0-10000
let ldr_color = hdr_color / (hdr_color + 1.0);  // 压缩到 0-1
```

现代 3A 游戏都支持 HDR(看《赛博朋克 2077》《对马岛之魂》)。Casey 在 HH 后期也会涉及。

## 2 · 数字图像

### 2.1 像素 / 分辨率 / 纵横比 / DPI

**像素**(pixel)= picture element,屏幕上最小的发光单位。每个像素有位置 和颜色。

**分辨率**(resolution)= 屏幕的像素网格大小,如 1920×1080 表示宽 1920 像素 × 高 1080 像素。

**纵横比**(aspect ratio)= 宽:高。1920:1080 = 16:9(标准高清)。4:3(老电视)、21:9(超宽屏)、32:9(超超宽)都有。

**DPI(Dots Per Inch)/ PPI(Pixels Per Inch)** = 物理密度。手机屏幕 5.5 寸对角线,1080p,PPI 算法:

```text
对角线像素数 = sqrt(1920² + 1080²) ≈ 2203
对角线英寸 = 5.5
PPI = 2203 / 5.5 ≈ 400
```

PPI 高的画面锐利(视网膜屏 ≥ 300),PPI 低的画面颗粒(老 CRT 显示器 72 PPI)。

### 2.2 颜色通道

一个像素的颜色,用什么编码?

**RGB**:三个通道(红、绿、蓝),每通道 0-1 或 0-255。**发光设备**(显示器)用这个,因为是加法混色(光叠加变白)。

**RGBA**:RGB + Alpha(不透明度)。Alpha = 1.0 完全不透明,0.0 完全透明。游戏/UI 几乎都用 RGBA,因为图层需要混合。

**CMYK**:青、品红、黄、黑。**反射设备**(印刷)用这个,因为是减法混色(油墨叠加吸收光变黑)。游戏基本不用。

### 2.3 位深

每通道用多少 bit?

- **8 bit**:每通道 0-255。最常见。"true color"。256 级灰度。
- **10 bit**:每通道 0-1023。HDR、专业摄影。"deep color"。1024 级灰度。
- **12 bit**:每通道 0-4095。专业电影摄影。
- **16 bit**:每通道 0-65535。HDR、医学图像。
- **32 bit float**:每通道 1.0 浮点,可超 1.0。GPU 内部计算、HDR 渲染。

位深低,**色带**(color banding)明显——天空渐变能看到一条条带子,因为相邻灰度差距太大。位深高,渐变平滑。

### 2.4 像素格式

GPU 不是按"通道"存,而是按"打包后的整数"或"浮点"存。常见格式(命名规则:R=Red,数字=bit 数):

| 格式 | 每通道 bit | 总 bit | 用途 |
|---|---|---|---|
| **R8G8B8A8**(RGBA8) | 8/8/8/8 | 32 | 通用,UI / 纹理 |
| **R8G8B8**(RGB8) | 8/8/8 | 24 | 不带 alpha 的纹理 |
| **B8G8R8A8** | 8/8/8/8 | 32 | Windows / DirectX 默认(BGR 顺序!) |
| **R10G10B10A2** | 10/10/10/2 | 32 | HDR 颜色,alpha 只有 2 bit(够做 mask) |
| **R16G16B16A16 float** | 16/16/16/16 | 64 | HDR 浮点渲染目标 |
| **R32G32B32A32 float** | 32/32/32/32 | 128 | 高精度 HDR |
| **R8**(单通道) | 8 | 8 | 灰度图、mask |
| **D24S8** | 24+8 | 32 | depth(24) + stencil(8) |
| **D32 float** | 32 | 32 | depth,浮点(更精确) |

GPU 写代码必须显式指定格式。错了纹理采样乱套。

### 2.5 直方图 / 动态范围

**直方图**(histogram)= 把所有像素的亮度统计成柱状图。横轴是亮度(0-255),纵轴是该亮度像素的数量。

照片软件(Photoshop、Lightroom)都显示直方图。游戏里也用,做**自动曝光**(auto exposure):每帧算直方图,根据平均亮度调相机曝光值,让玩家进洞穴眼睛"适应"黑暗。

**动态范围**(dynamic range)= 最暗和最亮的比。8-bit 渲染动态范围 255:1(48 dB),HDR 可以做到 10000:1。动态范围不够,亮部和暗部细节丢失——这是为什么 HDR 重要。

## 3 · 三角形与多边形

### 3.1 为什么游戏用三角形

为什么不画四边形?为什么不画五边形?**为什么 3D 渲染的"基本图元"是三角形?**

理由有四:

**第一,三点一定共面**。任意三个点必然在同一平面上(数学定理)。这意味着一个三角形**没有内部曲率**,渲染时不需要内插"高度"。如果你用四边形,四个点可能不共面(想象一张扭曲的纸),光栅化会出问题。

**第二,凸性保证**。三角形永远是凸多边形。凸多边形光栅化简单——扫描线从一边到另一边,中间所有像素都在三角形内。凹多边形要复杂得多。

**第三,插值定义清晰**。三角形有三个顶点,可以用**重心坐标**(下面讲)把任意内部点表示成三个顶点的加权和。颜色、UV、法线都可以这样插值。

**第四,GPU 硬件优化**。几十年的 GPU 硬件都围绕三角形设计——固定功能的光栅化单元专门处理三角形。换成其他图元,GPU 跑不动。

游戏模型用"看起来是四边形"的网格——其实是两个三角形拼的。Maya/Blender 里你画的"四边形",导出时被切成三角形,这叫**三角化**(triangulation)。

### 3.2 顶点 / 边 / 面

**顶点**(vertex)= 一个 3D 点,带额外属性(法线、UV、颜色)。
**边**(edge)= 两个顶点的连线。
**面**(face / triangle / polygon)= 三个或更多顶点围成的多边形。

一个游戏角色模型,典型的数据:

```rust
struct Mesh {
    positions: Vec<[f32; 3]>,   // 顶点位置
    normals:   Vec<[f32; 3]>,   // 顶点法线
    uvs:       Vec<[f32; 2]>,   // 纹理坐标
    indices:   Vec<u32>,        // 三角形索引,每 3 个一组
}
```

1 万个三角形的角色,positions 有 1 万-5 万个顶点(顶点共享),indices 有 3 万个 u32(每个三角形 3 个)。

### 3.3 法线 / 切线 / 副切线(TBN)

**法线**(normal)= 垂直于表面的单位向量。光照计算必备(Lambert 用法线和光源方向的点积)。

**切线**(tangent)= 沿纹理 U 方向的向量。
**副切线**(bitangent / binormal)= 沿纹理 V 方向的向量。

法线、切线、副切线构成 **TBN 矩阵**,**把切线空间(纹理空间的法线贴图)转到世界空间**。法线贴图(normal map)是骗 GPU"这里有细节"的技术,需要 TBN 矩阵。

```rust
// TBN 矩阵
let tbn = Mat3::from_cols(tangent, bitangent, normal);
// 把法线贴图采样出来的颜色,转成世界空间法线
let sampled_normal = texture_lookup(normal_map, uv);  // 0-1
let tangent_normal = sampled_normal * 2.0 - 1.0;       // 转到 -1 到 1
let world_normal = tbn * tangent_normal;               // 转到世界空间
```

### 3.4 Winding order / back-face culling

三角形从相机看,有"正面"和"反面"。**winding order**(绕序)规定:顶点按什么顺序排列时算"正面"。

- **Counter-clockwise(CCW)**:从相机看,顶点逆时针排列 = 正面。OpenGL 默认。
- **Clockwise(CW)**:从相机看,顶点顺时针排列 = 正面。DirectX 默认。

**背面剔除**(back-face culling)= GPU 在光栅化前,**跳过背对相机的三角形**,不渲染。3D 封闭模型(角色、地形)内部你看不到,内部三角形不用画,节省 50% 渲染时间。

```rust
// OpenGL 默认
glEnable(GL_CULL_FACE);
glCullFace(GL_BACK);  // 剔除背面
glFrontFace(GL_CCW);  // CCW 算正面
```

如果你的模型 winding 反了,你会看到"角色内部,外面看不见"——这是经典的 bug。Casey 在 HH 里也踩过。

### 3.5 三角形面积 / 重心坐标

**三角形面积**(向量叉积法):

```rust
fn triangle_area(a: Vec3, b: Vec3, c: Vec3) -> f32 {
    let ab = b - a;
    let ac = c - a;
    ab.cross(ac).length() * 0.5
}
```

**重心坐标**(barycentric coordinates)= 把三角形内部任意点 P 表示成三个顶点的加权和:`P = α*A + β*B + γ*C`,其中 `α + β + γ = 1`。

给定 P,怎么算 α, β, γ?用面积比:

```rust
fn barycentric(a: Vec2, b: Vec2, c: Vec2, p: Vec2) -> (f32, f32, f32) {
    let area = (b - a).cross(c - a);  // 全三角形有向面积 * 2
    let alpha = (b - p).cross(c - p) / area;
    let beta = (c - p).cross(a - p) / area;
    let gamma = (a - p).cross(b - p) / area;
    (alpha, beta, gamma)
}
```

P 在三角形内 ⟺ α, β, γ ∈ [0, 1]。

重心坐标是 GPU 光栅化的数学基础。**每个像素 P,算它的 (α, β, γ),然后插值顶点属性**:`color_at_p = α * color_a + β * color_b + γ * color_c`。

### 3.6 重心插值 vs 透视正确插值

但这里有个**深度陷阱**。3D 投影后,三角形的边不再是直线(透视变形)。**屏幕空间的 α, β, γ ≠ 投影前空间**。

如果直接用屏幕空间的 α, β, γ 插值,纹理在斜面上会"扭曲"。

**透视正确插值**(perspective-correct interpolation):插值前**先把顶点属性除以 w**(clip space 的 w 分量),插值后再乘回去。

```rust
// 顶点属性 a 在屏幕空间插值前
let a_per_w = a / w;
// 屏幕空间插值
let interpolated_per_w = α * (a_a/w_a) + β * (a_b/w_b) + γ * (a_c/w_c);
// 插值 1/w 也要
let one_over_w = α * (1.0/w_a) + β * (1.0/w_b) + γ * (1.0/w_c);
// 还原
let interpolated = interpolated_per_w / one_over_w;
```

这是 GPU 硬件自动做的,**你不用手写**,但要理解**为什么需要**。OpenGL 的 `noperspective` qualifier 可以关掉这个自动修正(很少用)。

## 4 · 投影

### 4.1 为什么要投影

3D 世界(顶点是 (x, y, z))要画到 2D 屏幕上(像素 (px, py)),必须**投影**(project)。两种主要投影:

- **正交投影**(orthographic):平行线保持平行。CAD、2D 游戏、isometric 游戏。
- **透视投影**(perspective):远的东西小,近的东西大。3D 游戏、现实摄影。

### 4.2 正交投影矩阵推导

正交投影:**无视深度,直接把 3D box 映射到 2D 屏幕矩形**。

定义 box:left, right, bottom, top, near, far(六个面)。我们要把 box 内的 3D 点 (x, y, z) 映射到 **NDC**(Normalized Device Coordinates)立方体 [-1, 1]^3,这样 GPU 后续步骤标准化。

线性变换:`x_ndc = a*x + b`。要满足:
- x = left → x_ndc = -1
- x = right → x_ndc = +1

解方程:
```
-1 = a*left + b
+1 = a*right + b
相减: 2 = a*(right - left),即 a = 2/(right - left)
代入: b = -1 - a*left = -(right + left)/(right - left)
```

所以:
```
x_ndc = (2/(right-left)) * x - (right+left)/(right-left)
y_ndc = (2/(top-bottom)) * y - (top+bottom)/(top-bottom)
z_ndc = (-2/(far-near)) * z - (far+near)/(far-near)
```

写成 4×4 矩阵(齐次坐标,下面解释):

```text
|  2/(r-l)      0           0           -(r+l)/(r-l)  |
|  0            2/(t-b)     0           -(t+b)/(t-b)  |
|  0            0           -2/(f-n)    -(f+n)/(f-n)  |
|  0            0           0            1            |
```

注意 z 翻转(near 是 +1,far 是 -1,右手坐标系习惯)。这个矩阵**就是 OpenGL 的 `glOrtho`**。

### 4.3 透视投影矩阵推导

透视:**模拟小孔成像**。相机在原点,前方 near 平面、far 平面。一个 3D 点 (x, y, z) 投影到 near 平面:

由相似三角形:

```text
near        x'
-----  =  -----
z            x
```

即 `x' = near * x / z`,同理 `y' = near * y / z`。**这是关键的一步:除以 z**。

但矩阵乘法是线性的,**矩阵不能"除法"**。怎么搞?用齐次坐标——把 (x, y, z, 1) 变成 (x, y, z, z),然后**透视除法**(后面 GPU 自动做)。

定义投影矩阵(相机朝 -z,fovy 是垂直视场角,aspect = 宽/高):

```text
| 1/(aspect*tan(fovy/2))  0             0              0             |
| 0                       1/tan(fovy/2) 0              0             |
| 0                       0             -(f+n)/(f-n)   -2fn/(f-n)    |
| 0                       0             -1             0             |
```

矩阵乘法后:`(x', y', z', w') = M * (x, y, z, 1)`,其中 w' = -z(原来是 z,矩阵把 z 拷贝到 w)。

然后**透视除法**:`x_ndc = x' / w', y_ndc = y' / w', z_ndc = z' / w'`。这就实现了"除以 z"。

这个矩阵**就是 OpenGL 的 `glPerspective`**(老版本)或 glm 的 `perspective`。

### 4.4 FOV / aspect ratio / near/far plane

- **FOV(Field of View)** = 视场角。垂直 FOV 90 度很广(鱼眼),60 度是 FPS 标准,30 度是望远镜。
- **aspect ratio** = 屏幕宽/高。16:9 屏 = 1.78。4:3 = 1.33。
- **near plane** = 相机前最近的可见距离。一般 0.1。
- **far plane** = 相机前最远的可见距离。一般 100-10000。

**near plane 不能太近**。near = 0.001 会让 z-buffer 精度崩溃(下面讲)。Casey 在 HH 强调:**near 设为 0.1 比设为 0.01 好得多**。

### 4.5 NDC / Clip space

- **Clip space** = 顶点着色器输出空间。`gl_Position = (x, y, z, w)`。
- **NDC(Normalized Device Coordinates)** = 透视除法后的空间,(x/w, y/w, z/w) ∈ [-1, 1]^3。
- **Window space** = NDC 经过 viewport 变换,得到屏幕像素坐标。x_window = (x_ndc + 1) * width / 2。

GPU 流水线:`World space → View space → Clip space (VS 输出) → 透视除法 → NDC → Viewport 变换 → Window space`。

### 4.6 Clip space / culling

**Clip space** 之外(任何分量 |.| > w)的顶点,GPU **裁剪**(clip)。比如一个三角形一个顶点在 clip space 外,GPU 算三角形和 clip box 的交线,把原三角形切成多个三角形(都在 clip box 内)。

**齐次坐标**(homogeneous coordinates)= 用 4 维 (x, y, z, w) 表示 3D 点。w = 1 是普通点,w = 0 是"方向"(向量)。所有矩阵运算用 4×4,统一处理平移(3×3 矩阵无法表示平移)。

**透视除法**(perspective division)= 把 clip space 的 (x, y, z, w) 除以 w,得到 NDC。**这是 GPU 自动做的**,VS 后、光栅化前。

## 5 · 光栅化直觉

### 5.1 光栅化 = 连续几何 → 离散像素

你给 GPU 一个三角形(三个顶点),它要把三角形覆盖的像素涂上颜色。这个**连续 → 离散**的过程叫**光栅化**(rasterization)。

直觉:对每个像素中心 (px+0.5, py+0.5),判断是否在三角形内。如果在,涂色。但这太慢——GPU 用专门的**光栅化单元**(rasterizer)硬件,并行算几百个像素。

### 5.2 Top-left rule

如果像素中心**正好在三角形边上**,算"在三角形内"还是"外"?

GPU 用 **top-left rule**:如果像素中心在三角形的**上边**或**左边**(y 较小或 x 较小,严格定义是边的方向),算"在三角形内";否则"外"。

这个规则的目的是**避免相邻三角形重叠或缝隙**。两个共享一条边的三角形,这条边上的像素只能归属其中一个,否则要么重叠(双涂)要么缝隙(没人涂)。

### 5.3 Z-buffer 算法

3D 场景有遮挡——前面的物体挡住后面的。**怎么知道哪个像素是前面、哪个是后面**?

**Z-buffer**(也叫 depth buffer)是经典答案:每个像素除了颜色,还存一个 **z 值**(深度)。光栅化时:

```text
对每个像素 P:
    算 P 的深度 z(插值顶点 z)
    如果 z < zbuffer[P]:  // 当前比存的近
        zbuffer[P] = z     // 更新深度
        colorbuffer[P] = 当前颜色  // 更新颜色
    else:
        不画(被遮挡)
```

z-buffer 简单、通用、O(像素数)。所有现代 GPU 都用它。

但有个**精度问题**:z 在 near 和 far 之间被映射到 [0, 1](NDC z)。z 不是均匀分布的——**靠近 near 的 z 精度高,靠近 far 的 z 精度低**。这叫 **z-fighting**:两个相近的远距离物体,z-buffer 区分不开,看起来闪烁。

修复:
- near 不要太近(0.1 比 0.001 好)
- far 不要太远(1000 比 100000 好)
- 用 **Reversed-Z**(把 near 映射到 1,far 映射到 0):精度分布反过来,far 处精度更好。OpenGL 默认 [0, 1],DirectX 默认 [1, 0](reversed)。

### 5.4 Early-z / late-z

GPU 优化:**early-z**。如果在片元着色器跑之前,depth test 就能判定被遮挡,**直接跳过片元着色器**,省 GPU 时间。

但有个条件:**片元着色器不能修改 depth**。如果你在 FS 里写 `gl_FragDepth = ...`,GPU 不能 early-z,必须 late-z(完整跑 FS 再 depth test)。

性能优化规则:**尽量不在 FS 里写 depth**。如果必须写,可以用 `layout(depth_unchanged)` qualifier 告诉 GPU"我不改,你还能 early-z"(OpenGL 4.2+)。

### 5.5 Anti-aliasing

像素中心在三角形内 = 完全涂色,在三角形外 = 不涂。**这导致锯齿**(jaggies)——斜边看起来是阶梯状。

**反走样**(anti-aliasing, AA)是解决方案。几种主流方案:

- **SSAA(Super-Sampling AA)**:渲染 2×2 = 4 倍分辨率,最后下采样到 1×。最简单、最贵(4 倍 GPU 工作)。质量最高。
- **MSAA(Multi-Sampling AA)**:只在三角形**边缘**做 super-sample,片元着色器还是 1×。比 SSAA 便宜。**游戏主流**。
- **FXAA(Fast Approximate AA)**:**后处理**——渲染完后,在屏幕空间检测边缘、模糊。很便宜,质量一般。
- **TAA(Temporal AA)**:每帧用**不同的 sub-pixel offset**采样,多帧累积。现代 3A 游戏主流(虚幻 5 默认)。有 ghosting(快速移动有残影)问题,需要 motion vector 补偿。

## 6 · 着色(shading)概念

### 6.1 Flat / Gouraud / Phong shading

**Flat shading**:每个三角形一个颜色。**法线取三角形面法线**,光照算一次。结果"facetted"(每个三角形分明),低多边形风格(Low-poly)用这个。

**Gouraud shading**:每个顶点算光照,**三角形内部颜色重心插值**。计算便宜,但高光(specular)在三角形大时看不清(因为插值的是颜色,不是法线)。

**Phong shading**(注意不是 Phong **光照**):每个像素**插值法线**,光照**每像素算**。质量最好(高光清晰),计算最贵。现代 GPU 默认就是这个。

```rust
// Flat: 一个三角形一次光照
let color = lambert(triangle_face_normal, light_dir);
for pixel in triangle { framebuffer[pixel] = color; }

// Gouraud: 三个顶点算光照,插值颜色
let c0 = lambert(vertex_normal[0], light_dir);
let c1 = lambert(vertex_normal[1], light_dir);
let c2 = lambert(vertex_normal[2], light_dir);
for pixel in triangle {
    let (a, b, c) = barycentric(pixel);
    framebuffer[pixel] = a*c0 + b*c1 + c*c2;
}

// Phong: 插值法线,每像素算光照
for pixel in triangle {
    let (a, b, c) = barycentric(pixel);
    let n = (a*vertex_normal[0] + b*vertex_normal[1] + c*vertex_normal[2]).normalize();
    framebuffer[pixel] = lambert(n, light_dir);
}
```

### 6.2 顶点着色 vs 像素着色

**顶点着色**(vertex shading):每个顶点算一次。便宜(顶点少)。粒度粗(三角形内部细节模糊)。

**像素着色**(pixel shading, fragment shading):每个像素算一次。贵(像素多)。粒度细。

现代 GPU 渲染管线:**VS(每顶点)** → 光栅化 → **FS(每像素)**。VS 算"位置变换 + 顶点属性准备",FS 算"颜色计算"。

### 6.3 材质属性:PBR 基础

**材质**(material)= 表面的光学属性。现代 PBR(Physically Based Rendering)用几个标准属性:

- **albedo**(反射率):**纯色,无光照**。木头 albedo 是棕,金属 albedo 是灰。
- **normal**(法线):表面朝向。可用法线贴图(normal map)模拟凹凸细节。
- **roughness**(粗糙度):0-1。0 = 镜面(完美反射),1 = 完全漫反射(哑光)。
- **metallic**(金属度):0-1。0 = 非金属(木头、塑料),1 = 金属(铁、金)。
- **AO**(Ambient Occlusion,环境光遮蔽):0-1。缝隙里 AO 低(暗),凸出部位 AO 高(亮)。模拟"环境光被自己几何体遮挡"。

PBR 让材质"看起来真实"——同一组参数在所有光照环境下都合理。这是过去 10 年游戏图形的最大革命。

### 6.4 光照模型

- **Lambert**(漫反射):`color = albedo * max(0, dot(N, L)) * light_color`。最简单,适合哑光表面。
- **Phong**(specular):Lambert + 高光项 `specular = pow(max(0, dot(R, V)), shininess)`。
- **Blinn-Phong**:Phong 改进,用 half vector 算高光,**更便宜、效果差不多**。
- **Cook-Torrance / PBR**:基于物理的微表面理论,BRDF(双向反射分布函数)。复杂但真实。

```rust
// Lambert(漫反射)
let n_dot_l = max(0.0, dot(normal, light_dir));
let diffuse = albedo * light_color * n_dot_l;

// Blinn-Phong(高光)
let half = (light_dir + view_dir).normalize();
let n_dot_h = max(0.0, dot(normal, half));
let specular = light_color * pow(n_dot_h, shininess);

let color = diffuse + specular;
```

PBR 是 Cook-Torrance 模型,实现复杂,你以后看 Bevy / Unreal 代码会看到。

## 7 · 纹理映射

### 7.1 UV 坐标

**纹理**(texture)= 2D 图像(也可以 1D / 3D / cube)。**UV 坐标** = 纹理上的 2D 坐标,U 是横向,V 是纵向,都是 [0, 1]。

每个顶点带 UV,GPU 光栅化时**插值 UV**,每个像素的 UV 用来**采样**纹理。这就是把 2D 图像"贴"到 3D 模型上的原理。

```rust
// 顶点
struct Vertex { pos: Vec3, uv: Vec2 }

// 三角形
let vertices = [
    Vertex { pos: (0, 0, 0), uv: (0.0, 0.0) },  // 左下角,U=V=0
    Vertex { pos: (1, 0, 0), uv: (1.0, 0.0) },  // 右下角,U=1,V=0
    Vertex { pos: (1, 1, 0), uv: (1.0, 1.0) },  // 右上角,U=V=1
];
```

### 7.2 纹理过滤

像素 UV 是浮点数(如 (0.5, 0.5)),但纹理是离散像素网格。**怎么采样**?

- **Nearest**(最近邻):取最近的纹理像素。便宜、像素化(8-bit 风格)。Minecraft 用这个。
- **Linear**(双线性):取最近 4 个纹理像素,加权平均。平滑、模糊。3D 游戏默认。
- **Mip / Trilinear**:多级渐远纹理(下面)+ 双线性,level 之间再做线性。

### 7.3 Mipmap

远处三角形占屏幕 1 像素,但纹理本身是 1024×1024。**采样时遍历整张纹理?** 不,会**严重 aliasing**(闪烁)。

**Mipmap**:预先生成**金字塔**——1024×1024 → 512×512 → 256×256 → ... → 1×1。GPU 根据屏幕大小,**自动选合适级别**。

```text
Level 0:  1024×1024(原纹理)
Level 1:   512×512
Level 2:   256×256
...
Level 10:  1×1(全纹理平均色)
```

总内存增加 1/3(几何级数和)。质量提升巨大。**几乎所有 3D 游戏都开 mipmap**。

### 7.4 各向异性过滤(Anisotropic Filtering)

mipmap 在**斜视角**(地板延伸到远方)有问题——会过度模糊。**各向异性过滤**采样时,**沿屏幕投影方向**多个样本(而不是 isotropic 一圈),保持斜视角清晰。

质量更高,代价是 GPU 时间。现代 GPU 16x 各向异性很便宜(几个 % 性能),所有 3A 游戏都开 16x。

### 7.5 寻址模式

UV 超出 [0, 1] 怎么办?

- **Wrap / Repeat**:平铺。0.5 → 0.5,1.5 → 0.5。地砖、墙纸用这个。
- **Mirror**:镜像。0.5 → 0.5,1.5 → 0.5(反向),2.5 → 0.5(再次反向)。
- **Clamp / Clamp to Edge**:截断到 [0, 1]。0.5 → 0.5,-0.5 → 0.0,1.5 → 1.0。
- **Border**:超出范围用固定 border 颜色。

```rust
// OpenGL
glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT);
glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT);
glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR);
glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
```

## 8 · Shader 概念

### 8.1 Shader = GPU 上跑的小程序

**Shader**(着色器)= 在 GPU 上运行的小程序。你用专门的着色器语言写,编译成 GPU 指令,GPU 在渲染时调用。

为什么叫"着色器"——最初(20 年前)只用来"着色"(算光照颜色)。今天 shader 做的事远超"着色"——可以扭曲几何(顶点 shader 可以移动顶点)、可以做后处理(片元 shader 改整个屏幕)、可以做物理模拟(compute shader)。

### 8.2 GLSL / HLSL / WGSL

三种主流着色器语言:

- **GLSL**(OpenGL Shading Language):OpenGL / OpenGL ES 用。C 风格语法。和 C 很像,但加了一些类型(`vec3`, `mat4`, `sampler2D`)。
- **HLSL**(High-Level Shading Language):DirectX 用。语法略不同,但概念一致。
- **WGSL**(WebGPU Shading Language):WebGPU 用。Rust 风格语法(更现代)。
- **MSL**(Metal Shading Language):苹果 Metal 用。基于 C++。

三种语言**做的事一样**,只是语法糖不同。学一种,切换不难。

```glsl
// GLSL 顶点着色器
#version 410 core

in vec3 position;
in vec2 uv;

uniform mat4 mvp;

out vec2 v_uv;

void main() {
    gl_Position = mvp * vec4(position, 1.0);
    v_uv = uv;
}
```

```glsl
// GLSL 片元着色器
#version 410 core

in vec2 v_uv;
out vec4 frag_color;

uniform sampler2D my_texture;

void main() {
    frag_color = texture(my_texture, v_uv);
}
```

### 8.3 顶点着色器 / 片元着色器

**顶点着色器(VS, Vertex Shader)**:每顶点调用一次。输入:顶点属性(position, normal, uv)。输出:`gl_Position`(clip space 位置)+ 任意 varying(传给 FS)。

**片元着色器(FS, Fragment Shader)**:每像素调用一次(更准确是每 fragment)。输入:VS 输出的 varying(已插值)。输出:`frag_color`(像素颜色)+ 可选 `gl_FragDepth`。

VS 和 FS 是**两个独立的 shader**,编译成两个 GPU 程序,**链接**成一个 program。

### 8.4 几何 / compute shader

**几何着色器(GS, Geometry Shader)**:每图元(三角形)调用一次。可以输出 0 个或多个图元(动态生成几何)。**很少用**,因为性能差。现代替代是 mesh shader。

**Compute shader**:不是图形管线一部分,**通用 GPU 计算**。可以读写 arbitrary buffer,做物理、AI、粒子。**GPGPU(General Purpose GPU)** 的入口。

```glsl
// Compute shader(算 buffer 里每个元素 * 2)
#version 430 core

layout(local_size_x = 64) in;
layout(std430, binding = 0) buffer MyBuffer {
    float data[];
};

void main() {
    uint idx = gl_GlobalInvocationID.x;
    if (idx < data.length()) {
        data[idx] *= 2.0;
    }
}
```

### 8.5 Uniform / attribute / varying

shader 变量分三类:

- **attribute / in**(VS 输入):**每顶点不同**。从顶点缓冲读。
- **uniform**:**所有顶点/像素相同**。从 CPU 传(每帧或每次 draw)。如 mvp 矩阵、光源位置。
- **varying / out → in**(VS 输出,FS 输入):**插值**后的值。

```glsl
// VS
in vec3 position;          // attribute(每顶点)
uniform mat4 mvp;          // uniform(全 draw 一样)
out vec3 v_world_pos;      // varying(插值后给 FS)

// FS
in vec3 v_world_pos;       // 从 VS 接收(插值)
uniform vec3 light_pos;    // uniform
out vec4 frag_color;       // 输出到 framebuffer
```

### 8.6 Shader 变体 / uber shader

不同材质用不同 shader(木头 vs 金属 vs 透明)。两种策略:

- **多个 shader program**:每种材质一个 program。**切换 program 慢**(GPU 状态切换)。适合材质少。
- **Uber shader + 宏**:一个大 shader,用 `#ifdef` 切换特性。一个 program 通过 `#define` 编译出多个变体。**切换便宜**(只是 uniform 不同)。现代引擎主流。

```glsl
// Uber shader
#ifdef FEATURE_NORMAL_MAP
    vec3 n = texture(normal_map, uv).xyz * 2.0 - 1.0;
    n = normalize(tbn * n);
#else
    vec3 n = vertex_normal;
#endif
```

编译时 `#define FEATURE_NORMAL_MAP` 决定。Bevy 用这个模式,所以它有"shader variants"概念。

## 9 · GPU 架构总览

### 9.1 SIMT:GPU 的执行模型

**SIMT(Single Instruction, Multiple Threads)** = 单指令多线程。GPU 不是 SIMD(单指令多数据,像 AVX),而是 SIMT——**32 个线程同时执行同一条指令**,但每个线程有自己的寄存器和 PC(程序计数器)。

如果 32 个线程都执行 `if (x > 0) { A } else { B }`,其中 16 个 x > 0,16 个 x ≤ 0——**两条分支都执行**,只是另一分支的结果被丢弃。这叫 **warp divergence**(分支分歧),性能杀手。

```rust
// 坏:warp divergence
if pixel.x < width / 2 {
    color = red;
} else {
    color = blue;
}

// 好:用 mix 替代 if
let t = step(width / 2, pixel.x);  // 0 或 1
color = mix(red, blue, t);
```

### 9.2 Warp / Wavefront

- **NVIDIA 叫 warp**:32 个线程一组。
- **AMD 叫 wavefront**:64 个线程一组。
- **Intel 叫 sub-slice / thread slice**:变长。

一个 warp 内的线程**同步执行**——同一指令,不同数据。光栅化时,**每个 warp 处理一个三角形的部分像素**(8×4 的像素块)。

### 9.3 SM / CU

- **NVIDIA SM(Streaming Multiprocessor)**:GPU 的"核"。一个 SM 内有几十个 CUDA core、几个特殊功能单元(SFU)、寄存器堆、shared memory。一片 GPU 有几十个 SM。
- **AMD CU(Compute Unit)**:AMD 等价物。架构类似。

RTX 4090 有 128 个 SM,每个 SM 有 128 个 CUDA core,总共 16384 个 CUDA core。**这是为什么 GPU 比 CPU 快这么多——核数多 100 倍**。

### 9.4 GPU 内存层级

GPU 内存比 CPU 复杂,有几个层级(由近到远):

- **寄存器(register)**:每线程,最快,但有限(每个 SM 几万个寄存器,分给同时跑的线程)。
- **Shared memory / L1 cache**:每 SM,**用户可控**(显式声明 shared),几十 KB。线程间通信。
- **L2 cache**:全 GPU 共享,几 MB。
- **VRAM(显存)**:所有 GPU 内存,几 GB-几十 GB。带宽 1 TB/s(比 CPU DRAM 快 10 倍)。
- **PCIe / host memory**:CPU 那边,最慢。

shader 写代码要考虑数据局部性——访问 VRAM 比访问 shared 慢 100 倍,比寄存器慢 1000 倍。

### 9.5 渲染管线总览

GPU 图形管线的阶段(简化):

```
[Input Assembler]
       ↓  读顶点缓冲,装配三角形
[Vertex Shader]
       ↓  每顶点调用一次,变换位置
[Tessellation / Geometry Shader(可选)]
       ↓  细分或生成几何
[Clip / Cull]
       ↓  裁剪 + 剔除
[Rasterizer]
       ↓  三角形 → 像素
[Fragment Shader]
       ↓  每像素调用一次,算颜色
[Output Merger / ROP]
       ↓  depth test, blend, 写 framebuffer
[Framebuffer]
```

每个阶段硬件专门优化,可以**并行**(VS 处理顶点 0、1、2 的同时,FS 处理上一个 draw 的像素)。

### 9.6 现代 GPU 演化:固定 → 可编程 → mesh shader / ray tracing

**第一代(1990s)**:**固定管线**(fixed-function)。`glBegin(GL_TRIANGLES); glVertex3f(...); glEnd();`。GPU 内部硬编码所有逻辑(变换、光照、混合),你只能开关参数。灵活度极低。

**第二代(2000s)**:**可编程 shader**。VS 和 FS 可写代码。`glCreateShader`, `glShaderSource`。灵活度飞跃,但 GS / tessellation 还是固定。

**第三代(2010s)**:**compute shader + GPGPU**。GPU 不再只画图,可以通用计算。CUDA / OpenCL / compute shader。

**第四代(2020s)**:**mesh shader + ray tracing**。
- **Mesh shader**:替代 IA + VS + GS,程序员**直接控制 GPU 处理哪些三角形**(cull、LOD 在 GPU 上做)。
- **Ray tracing(RT)**:GPU 硬件加速光线追踪(BVH 遍历 + 三角形求交)。RTX、RDNA2+。

虚幻 5 的 Nanite / Lumen 用 mesh shader + RT,跑百万级三角形实时光追。

## 10 · 渲染管线总览

### 10.1 Forward rendering

**前向渲染**(forward rendering)= 标准管线。每个物体,每个光源,所有计算在 FS 里做。

```text
for object in scene:
    for light in lights:
        shade(object, light)
```

简单。但**光照多时慢**(O(物体数 × 光源数))。1 万物体 × 100 光源 = 100 万次 shader 调用。

### 10.2 Deferred shading

**延迟着色**(deferred shading)分两步:
1. **Geometry pass**:渲染所有几何,把 position / normal / albedo / ... 存到 **G-buffer**(多张纹理,每张存一个属性)。**不**算光照。
2. **Lighting pass**:对每个光源,**读 G-buffer**,在屏幕空间算光照。

```text
# Geometry pass
for object in scene:
    write_to_gbuffer(object)  # 只算 position/normal/albedo,不算光照

# Lighting pass
for light in lights:
    for pixel in screen:
        shade_from_gbuffer(pixel, light)
```

**光照复杂度 O(像素数 × 光源数)**,不再依赖物体数。100 光源完全可行。

代价:**G-buffer 占内存大**(几张 1080p 纹理,几十 MB),**MSAA 难做**(G-buffer 像素多采样),**透明物体不能**(只能 forward)。

### 10.3 Forward+ / Clustered

**Forward+ / Clustered Forward** = forward + 光源分桶。把视锥体分成 3D 网格(cluster),每个 cluster 记录"哪些光源影响我"。FS 时只算影响当前 cluster 的光源(通常 < 10 个)。

兼顾 forward 的灵活(MSAA、透明)和 deferred 的多光源。**现代 3A 引擎主流**(虚幻 5 默认)。

### 10.4 可视化管线图

```text
       ┌─────────────────┐
       │   Application   │ ← 你的游戏代码
       │   (CPU)         │   决定画什么
       └────────┬────────┘
                │ draw calls
       ┌────────▼────────┐
       │  Driver (CPU)   │ ← OpenGL/Vulkan/DirectX driver
       │  命令翻译        │   转成 GPU 命令
       └────────┬────────┘
                │ GPU commands
       ┌────────▼────────┐
       │  GPU Pipeline   │
       │                 │
       │  IA → VS → RS → │
       │      FS → OM    │
       │                 │
       │  (硬件并行)      │
       └────────┬────────┘
                │
       ┌────────▼────────┐
       │   Display       │ ← 屏幕
       └─────────────────┘
```

## 11 · Rust + wgpu 简易 demo

### 11.1 wgpu 介绍

**wgpu** = Rust 的现代图形 API,基于 WebGPU 标准。**跨平台**(OpenGL/Vulkan/DirectX 12/Metal 一套 API)。Bevy、rend3 等都用 wgpu。

为什么不用 raw OpenGL:
- OpenGL API 设计老旧(全局状态机)
- 不跨平台(Mac 已弃用 OpenGL)
- 没有 modern features(bindless, mesh shader)

wgpu 的核心概念:
- **Instance**:wgpu 入口
- **Adapter**:物理 GPU
- **Device**:逻辑 GPU(命令队列)
- **Queue**:命令提交通道
- **Buffer / Texture**:GPU 内存
- **Pipeline**:shader + 状态配置
- **Bind group**:uniform / texture 绑定

### 11.2 最小三角形 demo

完整 wgpu 项目比较长,这里给一个**简化骨架**。**不要展开成完整 wgpu tutorial**,Phase 5 会做。

`Cargo.toml`:
```toml
[package]
name = "wgpu-triangle"
version = "0.1.0"
edition = "2021"

[dependencies]
wgpu = "0.20"
winit = "0.29"
pollster = "0.3"
bytemuck = { version = "1.14", features = ["derive"] }
```

`src/main.rs`:
```rust
use wgpu::util::DeviceExt;

// 顶点结构:[x, y, r, g, b]
#[repr(C)]
#[derive(Copy, Clone, bytemuck::Pod, bytemuck::Zeroable)]
struct Vertex([f32; 2], [f32; 3]);

const VERTICES: &[Vertex] = &[
    Vertex([-0.5, -0.5], [1.0, 0.0, 0.0]),  // 左下,红
    Vertex([ 0.5, -0.5], [0.0, 1.0, 0.0]),  // 右下,绿
    Vertex([ 0.0,  0.5], [0.0, 0.0, 1.0]),  // 顶,  蓝
];

// WGSL shader
const SHADER: &str = r#"
@vertex
fn vs_main(
    @location(0) position: vec2f,
    @location(1) color: vec3f,
) -> @builtin(position) vec4f {
    return vec4f(position, 0.0, 1.0);  // 直接当 NDC,z=0
}

@fragment
fn fs_main(
    @location(0) color: vec3f,
) -> @location(0) vec4f {
    return vec4f(color, 1.0);  // 输出颜色
}
"#;

fn main() {
    pollster::block_on(run());
}

async fn run() {
    // 1. 创建 instance / adapter / device
    let instance = wgpu::Instance::default();
    let adapter = instance
        .request_adapter(&wgpu::RequestAdapterOptions::default())
        .await
        .unwrap();
    let (device, queue) = adapter
        .request_device(&wgpu::DeviceDescriptor::default(), None)
        .await
        .unwrap();

    // 2. 创建 vertex buffer(把顶点数据传到 GPU)
    let vertex_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
        label: Some("Vertex Buffer"),
        contents: bytemuck::cast_slice(VERTICES),
        usage: wgpu::BufferUsages::VERTEX,
    });

    // 3. 编译 shader
    let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: Some("Shader"),
        source: wgpu::ShaderSource::Wgsl(SHADER.into()),
    });

    // 4. 创建 pipeline(VS + FS + 状态)
    let pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
        label: Some("Pipeline Layout"),
        bind_group_layouts: &[],
        push_constant_ranges: &[],
    });

    let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
        label: Some("Render Pipeline"),
        layout: Some(&pipeline_layout),
        vertex: wgpu::VertexState {
            module: &shader,
            entry_point: "vs_main",
            buffers: &[wgpu::VertexBufferLayout {
                array_stride: std::mem::size_of::<Vertex>() as u64,
                step_mode: wgpu::VertexStepMode::Vertex,
                attributes: &[
                    wgpu::VertexAttribute { offset: 0, shader_location: 0, format: wgpu::VertexFormat::Float32x2 },
                    wgpu::VertexAttribute { offset: 8, shader_location: 1, format: wgpu::VertexFormat::Float32x3 },
                ],
            }],
        },
        fragment: Some(wgpu::FragmentState {
            module: &shader,
            entry_point: "fs_main",
            targets: &[Some(wgpu::TextureFormat::Bgra8UnormSrgb.into())],
        }),
        primitive: wgpu::PrimitiveState::default(),
        depth_stencil: None,
        multisample: wgpu::MultisampleState::default(),
        multiview: None,
    });

    // 5. 主循环(简化,实际要 + winit 窗口)
    // 每帧:写命令,提交到 queue
    println!("Pipeline created: {:?}", pipeline);
    println!("In real code, this would render a triangle in a winit window.");
    println!("See Phase 5 for the full windowed example.");
}
```

跑:
```bash
cargo new --bin wgpu-triangle
cd wgpu-triangle
# 粘贴上面代码到 Cargo.toml 和 src/main.rs
cargo run
```

这不会真正显示窗口(简化),但展示了 wgpu 的核心步骤:
1. **instance/adapter/device**:打开 GPU
2. **vertex buffer**:顶点数据 → GPU
3. **shader**:WGSL 编译成 GPU 程序
4. **pipeline**:把 VS + FS + 状态打包
5. **render pass**:每帧绘制

**这个 demo 只是个骨架**,真正的窗口化 demo 涉及 winit 集成、swap chain、event loop——Phase 5 会展开。

## 12 · 跨学科联结

图形学和别的领域关联紧密。理解这些联结,你看图形学不再"孤立":

**联结一:数据库 query plan ≈ 渲染管线**。
数据库 SQL 经过 parser → planner → optimizer → executor。每一步**变换输入**,产出下一步的输入。图形管线:**vertices → VS → clip → rasterize → FS → framebuffer**。每个阶段变换数据。**这是"流式处理"模式**,出现在 stream processing、ETL pipeline、signal processing 里。

**联结二:编译器 AST pass ≈ shader pipeline**。
Rust 编译器:`源码 → AST → HIR → MIR → LLVM IR → 机器码`。每一步**降级**(lowering),从抽象到具体。图形管线:`世界坐标 → view space → clip space → NDC → window space`。每一步**变换坐标系**。两个领域都用"分阶段 pass"管理复杂度。

**联结三:CPU 缓存层级 ≈ GPU 内存层级**。
CPU:register → L1 → L2 → L3 → DRAM。GPU:register → shared/L1 → L2 → VRAM。**两个都是金字塔,越往上越快越小**。优化思路相同:**数据局部性**(locality)— 把热数据放在快的层。

**联结四:SIMD vs SIMT**。
CPU 的 AVX:**SIMD**(单指令多数据)。一条指令,16 个 float 同时算。**程序员显式**用 intrinsics。GPU:**SIMT**(单指令多线程)。一条指令,32 个 warp 线程同时算。**硬件自动** SIMD 化。两者都是"指令级并行",但 GPU 把这做到极致。

**联结五:函数式编程 ≈ shader**。
shader 是**纯函数**(给定输入,固定输出,无副作用)。FS 每像素调用一次,**互不影响**。这和 map-reduce / 函数式 map 一致。**为什么 GPU 适合函数式**?因为函数式天然并行(无共享状态),GPU 几千核正好。

**联结六:文件系统 / 数据压缩 ≈ 纹理压缩**。
磁盘文件用 zlib / lz4 压缩。**纹理也压缩**(BC1-BC7 / ETC / ASTC),但 GPU 解码时**直接采样**(不解压整个文件)。这是文件系统思想的 GPU 适配——存压缩格式,用的时候流式解码。

---

## 13 · 总结

今天我们走过图形学基础的**所有大概念**:颜色感知(CIE、sRGB、gamma、HDR)、数字图像(像素、通道、位深、格式)、三角形(法线、TBN、winding、重心坐标)、投影(正交、透视、NDC、齐次坐标)、光栅化(top-left rule、z-buffer、early-z、AA)、着色(flat/Gouraud/Phong、PBR 材质、光照模型)、纹理(UV、过滤、mipmap、各向异性、寻址模式)、shader(GLSL/HLSL/WGSL、VS/FS/GS/compute、uniform/varying)、GPU 架构(SIMT、warp、SM、内存层级)、渲染管线(forward/deferred/forward+)、Rust+wgpu 入门。

**这些概念是 Phase 5 OpenGL 和 Phase 7 现代 GPU 的地基**。Phase 1 的软件渲染让你**亲手**画像素,理解"光栅化"的字面意思。Phase 5 的 OpenGL 让你**用 GPU** 画像素,但概念框架是今天这篇。Phase 7 的 mesh shader / ray tracing 是今天管线概念的延伸——你理解了基础,就能跟上前沿。

**最重要的几条**:
- **颜色不是物理,是感知**。sRGB 不是线性,gamma 不是 sRGB。
- **三角形是 GPU 的原子**。三点共面、凸、易插值、硬件优化。
- **矩阵变换坐标系**。World → View → Clip → NDC → Window,每步一个矩阵。
- **z-buffer 解决遮挡,但有精度问题**。near 不要太近。
- **shader 是 GPU 上跑的小程序**。VS 每顶点,FS 每像素。
- **GPU = SIMT**。几千核跑同一指令,适合像素级并行。

下一篇:看你继续往下走的 Phase 1 软件 rendering,会反复用到今天的概念——只是 CPU 自己手算光栅化、插值、着色。

## 14 · 延伸阅读(可选补充,非必需)

本仓库本地资料:
- [14-math-foundations.md](14-math-foundations.md) — 矩阵 / 向量数学基础
- [20-math-foundation-extended.md](20-math-foundation-extended.md) — 线性代数扩展(矩阵乘法、齐次坐标深入)
- [days/phase-1/day001.md](../phase-1/day001.md) — HH 第一天的 software rendering 起点
- [days/phase-5/day235.md](../phase-5/day235.md) — OpenGL 集成起点

外部稳定 URL(可选):
- Physically Based Rendering(在线书,PBRT):https://www.pbr-book.org/
- Learn OpenGL(经典 OpenGL 教程):https://learnopengl.com/
- WebGPU spec:https://www.w3.org/TR/webgpu/
- wgpu 仓库 + examples:https://github.com/gfx-rs/wgpu
- Casey Handmade Hero 系列(很多 graphics 概念的视频讲解):https://hero.handmade.network/
- scratchapixel(图形学在线教材):https://www.scratchapixel.com/
- Real-Time Rendering(经典书,Akenine-Möller 等):图书馆或网上找
