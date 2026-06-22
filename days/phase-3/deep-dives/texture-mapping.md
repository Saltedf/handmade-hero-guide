# 纹理映射完整指南

> 本文是 [day093.md](../day093.md)、[day097.md](../day097.md) 的延伸,完整讲清**纹理映射(texture mapping)**的所有核心概念:UV 坐标、纹理采样、双线性/三线性插值、Mipmap、Wrap 模式、纹理压缩。Casey HH 在 Phase 3 软渲染里手写这些,Phase 5 切 OpenGL 后用 GPU 硬件做。本文自包含,但建议先读 Day 093。

## 1 · 为什么需要纹理映射

3D 物体的几何形状由顶点定义(三角形/四边形)。但同一形状(比如一个矩形面)可以有不同「**外观**」——木门、铁门、玻璃门。差别在表面颜色、纹理、细节。如果用「**每个顶点一个颜色**」来表达,需要海量顶点(一扇门的木纹可能需要百万像素细节),不现实。

**纹理映射**给出优雅解法:**用一张 2D 图(纹理)包裹 3D 物体表面**。每个顶点除了位置 `(x, y, z)`,还有「**纹理坐标 (u, v)**」表示「这个顶点对应纹理的哪个像素」。三角形内的像素通过插值得到 UV,然后用 UV 采样纹理得到颜色。

这样几何(几百顶点)+ 纹理(一张图)就能表达复杂物体外观。是 3D 渲染的基础工具。

## 2 · UV 坐标

纹理坐标 `(u, v)` 是「**纹理图上的位置**」,通常范围 [0, 1]。`u = 0, v = 0` 是纹理左下角,`u = 1, v = 1` 是右上角。

为什么 UV 用 [0, 1] 而不是像素索引?**分辨率无关**。一张 256×256 的纹理和一张 4K 纹理,同一个 UV (0.5, 0.5) 都对应中心——便于跨分辨率使用。

例子:一个矩形面的 4 个顶点 UV:

```
(0, 0) ──── (1, 0)
  │           │
  │   矩形面    │
  │           │
(0, 1) ──── (1, 1)
```

整个纹理正好拉伸贴满矩形面。

更复杂的物体(球、人形)的 UV 展开是「**UV unwrapping**」,需要 3D 建模工具(Blender、Maya)。本文不展开,但理解 UV 是纹理映射的基础。

## 3 · 纹理采样:从 UV 到颜色

给定一个 UV `(u, v)` 和一张纹理图 `T` (宽 W, 高 H),怎么得到颜色?

**最近邻采样(nearest neighbor)**:

```
px = round(u * (W - 1))
py = round(v * (H - 1))
color = T[py * W + px]
```

快但有锯齿(放大时像素方块明显)。

**双线性插值(bilinear)**:

```
fx = u * (W - 1)
fy = v * (H - 1)
x0 = floor(fx); y0 = floor(fy)
x1 = x0 + 1;    y1 = y0 + 1
dx = fx - x0;   dy = fy - y0

# 4 个邻居
p00 = T[y0*W + x0]
p10 = T[y0*W + x1]
p01 = T[y1*W + x0]
p11 = T[y1*W + x1]

# 双线性插值
top = lerp(p00, p10, dx)
bottom = lerp(p01, p11, dx)
color = lerp(top, bottom, dy)
```

慢一点(4 次采样 + 3 次 lerp)但平滑无锯齿。

Casey HH 用双线性。GPU 硬件原生支持双线性,几乎免费。

## 4 · Mipmap

放大纹理(近距离看)用双线性没问题。但**缩小纹理(远距离看)**时有问题:

- 一个远处的小三角形,屏幕只占 10 像素,但纹理是 1024×1024。
- 每个屏幕像素采样纹理,UV 跳跃很大,只采到几个零散像素。
- 结果:**严重的摩尔纹(moiré)和闪烁**。

**Mipmap** 解法:**预先把纹理缩小成多个分辨率级别**(金字塔)。1024→512→256→128→64→32→16→8→4→2→1,共 11 级。采样时根据像素在纹理上的覆盖范围,选合适的级别。

- 像素覆盖 1 texel → 用 level 0(原始)。
- 像素覆盖 4 texel → 用 level 1(1024 的一半)。
- 像素覆盖 16 texel → 用 level 2。

**三线性插值(trilinear)**:在两个相邻 level 各做一次双线性,然后两个 level 之间再 lerp 一次。总共 8 个 texel 采样 + 7 次 lerp。最平滑但最慢。

GPU 硬件原生支持 mipmap + 三线性。Casey HH 在 Phase 3 不用(纹理小,无摩尔纹),Phase 5 切 OpenGL 后启用。

## 5 · Wrap 模式

UV 超过 [0, 1] 时怎么处理?

- **Repeat**(重复):`u = u mod 1`,平铺重复。适合地板砖、墙纸。
- **Mirror**(镜像):`u = 1 - |u mod 2 - 1|`,来回镜像。
- **Clamp to Edge**(钳位):`u = clamp(u, 0, 1)`,边缘像素拉伸。
- **Border**(边界):超出范围用预设颜色。

OpenGL: `glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)`。

Casey HH 在 Phase 3 默认 clamp(超界不画),Phase 5 加 repeat 模式支持。

## 6 · 纹理过滤模式总结

| 缩小(远) | 放大(近) | 模式 |
|---|---|---|
| Nearest | Nearest | 最快,像素方块感(像素艺术) |
| Bilinear | Bilinear | 平滑,适合普通纹理 |
| Trilinear(Mipmap) | Bilinear | 缩小用 mipmap,近处双线性 |
| Anisotropic | Anisotropic | 高质量,处理斜视角 |

**Anisotropic Filtering(各向异性过滤)**:斜视角(地面到远处)时普通 mipmap 模糊。Anisotropic 沿像素覆盖椭圆采样多个 texel,清晰但贵(8x / 16x)。GPU 硬件支持。

## 7 · 纹理压缩

1024×1024 RGBA 纹理 = 4MB。一个场景几百张纹理 = 几个 GB。带宽和显存都是问题。

**S3TC(DXT)**:业界标准,4×4 像素块压缩到 8 字节(原 64 字节,压缩率 8:1)。GPU 硬件解压。
**BCn(Block Compression)**:D3D 名字,等同 S3TC 的不同变体。
**ASTC**:移动 / 现代 GPU 标准,压缩率可调(2:1 到 8:1),质量好。
**ETC**:Android 标准。

Casey HH 在 Phase 3 用未压缩 BMP。Phase 7 的 PNG 解码是另一种压缩(无损,运行时解压到内存)。Phase 8+ 可能涉及 BCn / ASTC。

## 8 · 法线贴图的特殊性

普通纹理存 RGB 颜色。法线贴图存「**法线向量**」(垂直于表面的单位向量),用 RGB 三通道编码 XYZ:[-1, 1] → [0, 255]。

采样法线贴图时,要注意:

1. 不能在 sRGB 空间采样(法线是「**数据**」不是「**颜色**」,sRGB 转换会破坏)。
2. 采样后必须**归一化**(length = 1),否则点积结果错。
3. 切线空间(tangent space)变换——法线贴图通常在切线空间,需要 TBN(tangent, bitangent, normal)矩阵变到世界空间。

Casey HH Day 097-103 详细处理这些。GPU 上用 sampler2D(不是 sampler2D_srgb)自动避免 sRGB 污染。

## 9 · Rust 实现示例

最小化的纹理采样:

```rust
pub struct Texture {
    pub width: u32,
    pub height: u32,
    pub pixels: Vec<[u8; 4]>,       // RGBA
}

impl Texture {
    pub fn sample_nearest(&self, u: f32, v: f32) -> [u8; 4] {
        let px = (u.clamp(0.0, 1.0) * (self.width - 1) as f32).round() as u32;
        let py = (v.clamp(0.0, 1.0) * (self.height - 1) as f32).round() as u32;
        self.pixels[(py * self.width + px) as usize]
    }

    pub fn sample_bilinear(&self, u: f32, v: f32) -> [u8; 4] {
        let fx = u.clamp(0.0, 1.0) * (self.width - 1) as f32;
        let fy = v.clamp(0.0, 1.0) * (self.height - 1) as f32;
        let x0 = fx.floor() as u32;
        let y0 = fy.floor() as u32;
        let x1 = (x0 + 1).min(self.width - 1);
        let y1 = (y0 + 1).min(self.height - 1);
        let dx = fx - fx.floor();
        let dy = fy - fy.floor();

        let p00 = self.pixels[(y0 * self.width + x0) as usize];
        let p10 = self.pixels[(y0 * self.width + x1) as usize];
        let p01 = self.pixels[(y1 * self.width + x0) as usize];
        let p11 = self.pixels[(y1 * self.width + x1) as usize];

        let lerp_u8 = |a: u8, b: u8, t: f32| -> u8 {
            (a as f32 + (b as f32 - a as f32) * t) as u8
        };

        [
            lerp_u8(lerp_u8(p00[0], p10[0], dx), lerp_u8(p01[0], p11[0], dx), dy),
            lerp_u8(lerp_u8(p00[1], p10[1], dx), lerp_u8(p01[1], p11[1], dx), dy),
            lerp_u8(lerp_u8(p00[2], p10[2], dx), lerp_u8(p01[2], p11[2], dx), dy),
            lerp_u8(lerp_u8(p00[3], p10[3], dx), lerp_u8(p01[3], p11[3], dx), dy),
        ]
    }
}
```

注意:`u.clamp(0.0, 1.0)` 是 clamp wrap 模式。Repeat 模式用 `u.fract()`(取小数部分,自动循环)。Mirror 模式更复杂——`u = 1.0 - (u.fract() * 2.0 - 1.0).abs()`。

## 10 · 性能考虑

纹理采样是 GPU 上的热路径。优化:

- **Mipmap**:必须开,避免远距离摩尔纹。
- **压缩纹理**:BCn / ASTC,GPU 硬件解压,带宽节省 4-8×。
- **纹理图集(atlas)**:多张小纹理合并成大图,减少 GPU 状态切换。
- **Texture array**:同尺寸纹理堆栈,GPU 一个 bind 切换。
- **Bindless texture**:大量纹理不用每个 bind,直接 64 位 handle 引用。

CPU 软渲染(Casey HH)纹理采样是性能瓶颈。一个 256×256 纹理的双线性采样每像素 ~50ns,1080p 像素 = 50ms。Casey HH 用 SIMD(`_mm_*`)加速 4 倍,Day 121+ 详细讲。

## 11 · 历史演化

**1974**:Edwin Catmull 博士论文首次提出纹理映射。
**1980**:Mipmap 被 Lance Williams 发明,解决远距离采样问题。
**1990s**:GPU 硬件支持纹理采样(3dfx Voodoo, 1996),早期没 mipmap。
**2000s**:可编程 shader 允许自定义采样逻辑(各向异性过滤、自定义过滤)。
**2010s**:压缩纹理(BCn / ASTC)普及,移动 GPU 主导。
**2020s**:硬件 ray tracing 让纹理采样进 ray pipeline,Virtual Texturing(GPU 流式加载超大纹理)。

Casey HH 让你在 CPU 软渲染上手写所有这些,真正理解 GPU 黑盒内部。

## 12 · 延伸阅读

- [LearnOpenGL Textures](https://learnopengl.com/Getting-started/Textures) — OpenGL 纹理完整教程。
- [Scratchapixel Texture Mapping](https://www.scratchapixel.com/lessons/3d-basic-rendering/texturing) — 从零实现纹理映射。
- [Real-Time Rendering 4th Ed. Chapter 6](https://www.realtimerendering.com/) — 纹理映射学术版。
- [Mipmap Original Paper (Williams 1983)](https://en.wikipedia.org/wiki/Mipmap) — 历史。
- [D3D BCn Compression Spec](https://docs.microsoft.com/en-us/windows/win32/direct3d10/d3d10-graphics-programming-guide-resources-block-compression) — 微软官方文档。
- [ASTC Spec](https://www.khronos.org/registry/ASTC/specs/) — Khronos 标准。
