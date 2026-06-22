# 法线贴图:Tangent 空间、TBN 矩阵、法线贴图解码、混合

> 一个低模(几百三角形)在屏幕上展现出高模(几万三角形)的细节——这是法线贴图(normal mapping)做的魔法。本质是欺骗光照:不改变几何,只改变"每个像素看到的法线"。本文从 tangent 空间讲到 TBN 矩阵构建,从 DXT5nm 解码讲到三平面采样,让你彻底掌握这把图形学最常用的"作弊利器"。

## 0 · 为什么要有法线贴图

你做完 PBR 光照,立方体看起来不错——但太"光滑"。真实世界里哪怕一面墙也有起伏:砖缝、坑洼、风化痕迹。要让这些细节出现,你有两个选择:

1. **真建模**:把每块砖、每条缝都用三角形建出来。100 万三角形起步,渲染开销爆炸
2. **骗光照**:几何还是平的,但在每个像素上"骗"光照——告诉它这里法线不是朝外,而是斜了 30°。光照公式立刻算出一个"有阴影"的像素,看起来像有几何细节

第 2 个选择就是**法线贴图**(normal mapping)。它由 James Blinn 1978 年首次提出,90 年代末被游戏工业广泛采用,至今是 3D 渲染里最重要的优化技术之一。

**关键洞察**:光照公式只关心 N(法线)、L(光向)、V(视向)三个向量。N 不必来自几何顶点——可以来自纹理。把每个像素的 N 存进纹理,光照立刻变细腻。

**本文要解决的三个核心问题**:

1. **怎么存**:法线是单位向量,(x, y, z) ∈ [-1, 1]。但纹理是 [0, 1]。怎么编码?
2. **存什么空间**:法线可以在世界空间(world space)或切线空间(tangent space)。两者各有利弊,主流选切线空间——为什么?
3. **怎么用**:shader 拿到切线空间的法线,怎么转到世界空间给光照用?

**读完这一篇你能**:
- 写一个工具,把高模的法线烘焙到低模的法线贴图
- 在 shader 里构建 TBN 矩阵,把法线从切线空间转到世界空间
- 解释为什么法线贴图大多是蓝紫色(高 z、低 x/y)
- 知道 DXT5nm / BC5 这些 GPU 压缩格式怎么省一半空间

## 1 · 法线贴图存什么

### 编码:[-1, 1] → [0, 1]

单位法线 N = (x, y, z),每个分量 ∈ [-1, 1]。纹理通常是 8 位/channel,值域 [0, 1]。编码和解码:

```rust
fn encode(normal: Vec3) -> [u8; 3] {
    [
        ((normal.x * 0.5 + 0.5) * 255.0) as u8,
        ((normal.y * 0.5 + 0.5) * 255.0) as u8,
        ((normal.z * 0.5 + 0.5) * 255.0) as u8,
    ]
}

fn decode(rgb: [u8; 3]) -> Vec3 {
    Vec3 {
        x: (rgb[0] as f32 / 255.0) * 2.0 - 1.0,
        y: (rgb[1] as f32 / 255.0) * 2.0 - 1.0,
        z: (rgb[2] as f32 / 255.0) * 2.0 - 1.0,
    }
}
```

如果法线"几乎朝外",z ≈ 1,编码后 ≈ 255(蓝色);x、y ≈ 0,编码后 ≈ 128(中性)。所以**典型的法线贴图看起来是一片淡蓝紫色**(因为 R、G 接近中性,B 接近满)。

### 关键优化:存 (x, y),重建 z

单位法线满足 x² + y² + z² = 1,所以 z = √(1 - x² - y²)。**只存 (x, y),shader 现场算 z**。这有两个好处:

1. **省空间**:只需要 2 个通道而不是 3
2. **保证单位长度**:重建的 z 永远让法线归一化

这是 DXT5nm / BC5 压缩格式的核心思路——只用两个通道。

## 2 · 三个空间:世界、物体、切线

### 世界空间法线

存"在全局世界坐标系下的法线方向"。优点:shader 直接用,不用矩阵变换。缺点:**法线贴图绑死姿态**——物体一旋转,法线还是按原方向存,光照立刻错误。除非用动画/移动无关的静态物体,否则不用。

### 物体空间(模型空间)法线

存"在物体本地坐标系下的法线"。优点:物体旋转时,法线跟随旋转。缺点:**法线贴图绑死形状**——同样的方块,法线贴图只能贴到这个方块上,换一个模型不能用。

### 切线空间(tangent space)法线

这是主流选择。**思想**:法线贴图存"相对于表面局部坐标系的偏移"。局部坐标系由三个向量定义:

- **N**(normal):几何顶点的法线,垂直于表面
- **T**(tangent):沿纹理 U 方向的切线,在表面内
- **B**(bitangent, 也叫 binormal):沿纹理 V 方向的"次切线",= N × T

切线空间也叫 **TBN 空间**。法线贴图存的法线在这个空间里——典型值接近 (0, 0, 1),表示"和几何法线一致"。

**优势**:

1. **可重用**:同一张砖墙法线贴图可以贴在任何朝向的方块上
2. **可动画**:物体旋转时,法线自动跟随(因为切线空间也跟着旋转)
3. **节省带宽**:z 几乎总是接近 1(只存微小偏移)

## 3 · TBN 矩阵的构建

### 数学推导

给定一个三角形,顶点 P0, P1, P2,纹理坐标 UV0, UV1, UV2:

```
边向量:E1 = P1 - P0,  E2 = P2 - P0
UV 差:ΔUV1 = UV1 - UV0,  ΔUV2 = UV2 - UV0
```

切线空间的定义:E1 沿 U 方向、E2 沿 V 方向(理想情况)。但因为 UV 可能扭曲,E1 和 E2 不严格沿 UV——它们是 U 和 V 的组合:

```
E1 = ΔUV1.u * T + ΔUV1.v * B
E2 = ΔUV2.u * T + ΔUV2.v * B
```

写成矩阵:

```
| E1.x E1.y E1.z |   | ΔUV1.u  ΔUV2.u |   | T.x T.y T.z |
| E2.x E2.y E2.z | = | ΔUV1.v  ΔUV2.v | * | B.x B.y B.z |
```

右边的 2×2 矩阵求逆后乘左边,得到 T 和 B:

```
| T.x T.y T.z |     1     |  ΔUV2.v  -ΔUV2.u |   | E1.x E1.y E1.z |
| B.x B.y B.z | = ------- | -ΔUV1.v   ΔUV1.u | * | E2.x E2.y E2.z |
                           ΔUV1.u*ΔUV2.v - ΔUV1.v*ΔUV2.u
```

那个分数的分母就是行列式 `det = ΔUV1.u * ΔUV2.v - ΔUV1.v * ΔUV2.u`。

### Rust 实现

```rust
fn compute_tangent(
    p0: Vec3, p1: Vec3, p2: Vec3,
    uv0: Vec2, uv1: Vec2, uv2: Vec2,
    normal: Vec3,
) -> Vec3 {
    // 三个顶点位置 + UV,返回 tangent(单向量;bitangent 由 normal × tangent 算)
    let e1 = p1 - p0;
    let e2 = p2 - p0;
    let duv1 = uv1 - uv0;
    let duv2 = uv2 - uv0;
    
    let det = duv1.x * duv2.y - duv1.y * duv2.x;
    if det.abs() < 1e-9 {
        // UV 退化(可能 UV 共线),返回任意正交向量
        return orthogonal_tangent(normal);
    }
    let inv_det = 1.0 / det;
    
    let t = (e1 * duv2.y - e2 * duv1.y) * inv_det;
    // bitangent = (e2 * duv1.x - e1 * duv2.x) * inv_det;
    
    // Gram-Schmidt 正交化:tangent 减去 normal 方向的分量,再归一化
    let t = (t - normal * normal.dot(t)).normalized();
    
    // 处理"手性"(handedness):如果 B = N × T 和 UV 方向相反,翻转 T
    // 实战:存一个 sign 标志位(通常打包到 tangent.w)
    t
}
```

每行注释:

- `det` 是 2×2 矩阵行列式,= UV 三角形的有向面积的两倍
- `inv_det` 用于把公式 `T = (e1*duv2.y - e2*duv1.y) * inv_det` 算出
- Gram-Schmidt 正交化:**T 必须和 N 正交**(都垂直于表面),但 UV 扭曲会导致 T 有沿 N 的分量。减去这个分量,得到正交的 T
- 手性问题:有些 UV 镜像(对称 UV),会导致 B 方向反。打包一个 `tangent.w = ±1` 给 shader,shader 用它决定是否翻转

## 4 · 在 Shader 里使用

### 顶点 shader 输出

每个顶点要传:position、normal、tangent、uv。tangent 用 vec4,w 存 handedness sign。

### 片段 shader

```glsl
// GLSL
in vec3 v_world_pos;
in vec3 v_world_normal;
in vec4 v_world_tangent;  // xyz = tangent, w = handedness
in vec2 v_uv;

uniform sampler2D u_normal_map;

void main() {
    // 1. 归一化(顶点插值后可能不归一化)
    vec3 N = normalize(v_world_normal);
    vec3 T = normalize(v_world_tangent.xyz);
    float handedness = v_world_tangent.w;
    
    // 2. 算 bitangent
    vec3 B = cross(N, T) * handedness;
    
    // 3. 构建 TBN 矩阵(列:切线空间的 x/y/z 轴在世界空间的坐标)
    mat3 TBN = mat3(T, B, N);
    
    // 4. 采样并解码法线贴图
    vec3 sampled_normal = texture(u_normal_map, v_uv).rgb * 2.0 - 1.0;
    
    // 5. 转到世界空间
    vec3 world_normal = normalize(TBN * sampled_normal);
    
    // 6. 用 world_normal 做光照
    // ... 调用 PBR 或 Phong 函数
}
```

每行注释:

- `mat3(T, B, N)` — GLSL 用三个向量构造矩阵,每个向量是一列。所以矩阵第 1 列是 T、第 2 列是 B、第 3 列是 N。这表示"切线空间的 x 轴对应世界空间的 T 向量"——这正是把切线空间向量变换到世界空间的矩阵
- `texture(u_normal_map, v_uv).rgb * 2.0 - 1.0` — 解码:[0,1] → [-1,1]
- `TBN * sampled_normal` — 矩阵乘向量,把切线空间法线转到世界空间

### 世界空间到切线空间的反向操作

有时反过来用:把 L(光向)和 V(视向)转到切线空间,在切线空间做光照。这样 shader 不用每个片段都构建 TBN 矩阵(顶点 shader 算一次,插值给片段)。两种做法都常见,性能差不多。

## 5 · 法线贴图的压缩格式

法线贴图是 GPU 显存大户(每个像素 3-4 字节),所以工业界开发了**专门为法线优化的压缩格式**。

### DXT5nm(也叫 BC3 的法线变体)

Direct3D 9/10 时代主流。把法线的 x 存在 alpha 通道,y 存在 green 通道,R 和 B 通道不用(留作常量)。这样:

```
texture.rgb = (1, y, 1)  // R, B 无用,G 存 y
texture.a = x            // alpha 存 x
shader: xy = texture.ag;  z = sqrt(1 - x² - y²)
```

DXT5nm 利用 DXT5 的 alpha 通道是单独 8 位(精度高),而颜色通道用 DXT1 编码(精度低)。**只关心 x 和 y 的高精度**,这正是法线贴图需要的。

### BC5(BC = Block Compression,OpenGL 称 ETC2 的同类)

BC5 是 Direct3D 11+ 的现代法线格式。两个独立的 BC1 通道,各存 x 和 y,精度更高。GPU 原生支持硬件解码。

### 在 OpenGL 里用

```rust
// Rust + glow 调用 OpenGL
unsafe {
    gl.compressed_tex_image_2d(
        glow::TEXTURE_2D, 0,
        glow::COMPRESSED_RG_RGTC2 as i32,  // BC5 的 OpenGL 名
        width, height, 0,
        compressed_data.len() as i32,
        Some(&compressed_data),
    );
}

// 片段 shader:
// vec2 xy = texture(sampler, uv).rg * 2.0 - 1.0;
// float z = sqrt(max(0.0, 1.0 - dot(xy, xy)));
// vec3 N = vec3(xy, z);
```

## 6 · 法线混合(Triplanar / Blend)

### 问题

地形用一张法线贴图,所有地方都一样——单调。你想:草地用 A 法线,沙地用 B 法线,岩石用 C 法线,根据"高度图"或"权重纹理"混合。

### 简单线性混合(错!)

```glsl
vec3 n_a = texture(tex_a, uv).rgb * 2.0 - 1.0;
vec3 n_b = texture(tex_b, uv).rgb * 2.0 - 1.0;
vec3 blended = mix(n_a, n_b, weight);
```

问题:两个向量平均,结果不再是单位向量;而且法线被"压扁",视觉上损失细节。

### 正确做法:UDN 或 Whiteout 混合

**UDN**(Unreal Developer Network)方法:

```glsl
vec3 blend_udn(vec3 n1, vec3 n2, float w) {
    // 把 n2 当作"细节扰动"叠加到 n1
    vec3 result = vec3(n1.xy + n2.xy * w, n1.z);
    return normalize(result);
}
```

**Whiteout** 混合(更准):

```glsl
vec3 blend_whiteout(vec3 n1, vec3 n2, float w) {
    vec3 result = vec3(
        n1.xy * (1 - w) + n2.xy * w,  // xy 线性混合
        n1.z * n2.z                    // z 相乘
    );
    return normalize(result);
}
```

Whiteout 更准:保持了高频细节不被平滑掉。

### 三平面投影(Triplanar Mapping)

更复杂的情况:模型没有 UV(比如程序生成的地形),怎么贴法线?**三平面投影**:对 x、y、z 三个轴分别投影纹理,根据法线方向加权混合。

```glsl
vec3 triplanar_normal(
    sampler2D normal_map,
    vec3 world_pos, vec3 normal, float scale
) {
    vec3 blend = abs(normal);
    blend /= dot(blend, vec3(1.0));  // 权重归一化
    
    vec3 x_normal = texture(normal_map, world_pos.yz * scale).rgb * 2.0 - 1.0;
    vec3 y_normal = texture(normal_map, world_pos.xz * scale).rgb * 2.0 - 1.0;
    vec3 z_normal = texture(normal_map, world_map.xy * scale).rgb * 2.0 - 1.0;
    
    // 注意:每个投影的法线要在对应面的切线空间里
    // 这里简化(假设法线贴图几乎朝外),实战要构建 TBN
    
    return normalize(
        x_normal * blend.x + y_normal * blend.y + z_normal * blend.z
    );
}
```

(简化的线性混合,实战需要更复杂的"切线空间混合")。

## 7 · 烘焙:从高模生成法线贴图

工具链:Blender / Substance Painter / xNormal 都能做这件事。原理:

1. 高模(几百万三角形)有所有细节
2. 低模(几百三角形)只有轮廓
3. 对低模每个顶点(或片段),从顶点沿法线方向射线,撞到高模的表面
4. 记录高模表面在那个交点的法线(世界空间)
5. 转到低模顶点的切线空间
6. 写到纹理

这是离线过程,游戏运行时只用低模 + 烘焙好的法线贴图,看起来和用高模差不多。

## 8 · 历史

- 1978:James Blinn 在 SIGGRAPH 论文里首次描述"凹凸贴图"(bump mapping),用灰度图扰动法线
- 1996:Krishnamurthy & Levoy 首次描述现代法线贴图(从高模采样)
- 2000s:游戏工业(Half-Life 2、Doom 3)广泛采用
- 2010s:PBR + 法线贴图成为标配;BC5 格式普及
- 2020s:神经法线贴图(深度学习压缩)、Mesh Shader 时代的细节渲染

## 9 · 关联 Day

- **铺垫**:Day 041 向量数学;Day 271 光照;Day 275 法线概念
- **当天**:本篇是法线贴图专题
- **后续**:Day 320+ 法线贴图实战;Day 415 视差贴图(更高级的法线欺骗)

## 10 · 变式训练

### Lv1 · 概念辨析

**题**:为什么法线贴图典型看起来是淡蓝紫色?解释颜色和法线分布的关系。

**参考解答**:切线空间法线贴图存的是"相对于几何法线的偏移"。绝大多数像素的偏移很小,x、y ≈ 0,z ≈ 1。编码到 [0,1]:x、y ≈ 0.5(中性),z ≈ 1.0(满)。在 RGB 显示下,(0.5, 0.5, 1.0) 就是淡蓝紫色。**颜色越蓝,法线越接近几何法线**(无偏移);**颜色越偏红/绿/黄,法线偏移越大**。

### Lv2 · 动手实践

**题**:写个 Rust 程序,生成一张 256×256 的法线贴图,内容是"高度图 h(x,y) = sin(x) * cos(y)"。然后保存成 PNG。

**提示**:法线 = 高度图梯度 (-dh/dx, -dh/dy, 1) 归一化。

**参考解答**:

```rust
use image::{ImageBuffer, Rgb, RgbImage};

fn main() {
    let w = 256;
    let h = 256;
    let mut img: RgbImage = ImageBuffer::new(w, h);
    let scale = 20.0;  // 高度图频率
    
    for y in 0..h {
        for x in 0..w {
            let fx = x as f32 / w as f32 * scale;
            let fy = y as f32 / w as f32 * scale;
            // 高度 h = sin(fx) * cos(fy)
            // 梯度:dh/dx = cos(fx) * cos(fy) * (scale / w) ... 简化用解析:
            let dhdx = f32::cos(fx) * f32::cos(fy);
            let dhdy = -f32::sin(fx) * f32::sin(fy);
            let strength = 2.0;  // 控制法线贴图强度
            let n = Vec3 {
                x: -dhdx * strength,
                y: -dhdy * strength,
                z: 1.0,
            }.normalized();
            img.put_pixel(x, y, Rgb([
                ((n.x * 0.5 + 0.5) * 255.0) as u8,
                ((n.y * 0.5 + 0.5) * 255.0) as u8,
                ((n.z * 0.5 + 0.5) * 255.0) as u8,
            ]));
        }
    }
    img.save("normal_map.png").unwrap();
}
```

### Lv3 · 迁移设计

**题**:法线贴图本质是"存每个像素的偏移向量"。除了法线,还有什么可以用类似的"每像素向量"表达?设计一个场景。

**提示**:向量场可以是任意东西——视差贴图的视差方向、各向异性高光的方向(头发!)、流动的水流方向……

### Lv4 · 开源贡献

**题**:Renderdoc 是开源的 GPU 调试器,GitHub: https://github.com/baldurk/renderdoc

1. clone 它
2. 看它的 Texture Viewer 怎么显示法线贴图(它会自动 [0,1] → [-1,1] 解码)
3. 找源码:renderdoc/Code/Tools/TextureViewer
4. 可能的贡献:加一个新的法线显示模式(比如显示"几何法线 vs 法线贴图法线的偏差"),提 PR

## 11 · Rust / Arch 落地代码

完整工具:从 OBJ 模型 + 高度图,生成法线贴图。

```toml
# Cargo.toml
[package]
name = "normal_baker"
version = "0.1.0"
edition = "2021"

[dependencies]
image = "0.25"
glam = "0.29"
obj = "0.10"  # 简单 OBJ 加载
```

```rust
// src/main.rs
use glam::{Vec3, Vec2};
use image::{ImageBuffer, Rgb, RgbImage};

#[derive(Copy, Clone)]
struct Vertex {
    pos: Vec3,
    uv: Vec2,
    normal: Vec3,
    tangent: Vec3,
}

fn build_tbn(v0: Vertex, v1: Vertex, v2: Vertex) -> (Vec3, Vec3, Vec3) {
    let e1 = v1.pos - v0.pos;
    let e2 = v2.pos - v0.pos;
    let duv1 = v1.uv - v0.uv;
    let duv2 = v2.uv - v0.uv;
    let det = duv1.x * duv2.y - duv1.y * duv2.x;
    let inv = if det.abs() > 1e-9 { 1.0 / det } else { 0.0 };
    let mut t = (e1 * duv2.y - e2 * duv1.y) * inv;
    // Gram-Schmidt
    t = (t - v0.normal * v0.normal.dot(t)).normalize();
    let b = v0.normal.cross(t);
    (t, b, v0.normal)
}

fn main() {
    // ... 加载模型 + 高度图 + 烘焙
    // 简化版:把上面 Lv2 的高度图法线生成扩展到任意 OBJ
    println!("用法:normal_baker <model.obj> <heightmap.png> <output_normal.png>");
}
```

Arch 上工具链:

```bash
# 装图形工具
sudo pacman -S blender substance-painter-patch-tool  # 美术工具(AUR)
# 或开源替代
sudo pacman -S xnormal  # 专门的烘焙工具(AUR)

# 看模型法线
sudo pacman -S renderdoc  # GPU 调试
renderdoc &  # GUI 抓一帧看 fragment shader 的 TBN

# 调试法线贴图(终端预览)
sudo pacman -S imagemagick
identify -verbose normal_map.png | head -20
# 输出示例:
#   Image: normal_map.png
#     Format: PNG ...
#     Geometry: 256x256
#     Colorspace: sRGB
#     Channel statistics:
#       Red: min: 50, max: 200, mean: 128.5  # 中性红
#       Green: min: 60, max: 190, mean: 127.8  # 中性绿
#       Blue: min: 200, max: 255, mean: 240.0  # 高蓝(法线朝外)
```

## 12 · 延伸阅读

本仓库本地:

- `days/phase-6/deep-dives/lighting-models.md` — 光照模型(法线喂给光照)
- `days/phase-6/deep-dives/texture-compression.md` — BCn 压缩(法线贴图专门的 BC5)

外部稳定 URL:

- LearnOpenGL Normal Mapping: https://learnopengl.com/Advanced-Lighting/Normal-Mapping
- Scratchapixel Texturing: https://www.scratchapixel.com/lessons/3d-basic-rendering/introduction-to-shading
- Terathon Tangent Space 论文: http://www.terathon.com/code/tangent.html

真实开源源码:

- Filament 法线采样: https://github.com/google/filament/blob/main/shaders/src/getters.fs
- mikktspace(切线空间标准): https://github.com/mmikk/MikkTSpace
- bgfx 法线烘焙工具: https://github.com/bkaradzic/bgfx/tree/master/tools/texturev
