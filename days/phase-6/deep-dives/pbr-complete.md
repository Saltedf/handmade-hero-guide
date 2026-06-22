# PBR 完整剖析:从辐射度量学到 Cook-Torrance BRDF 与 IBL

> Lambert 漫反射到 Phong 镜面反射到 Blinn-Phong——40 年里图形学逐步逼近"真实"。但所有这些模型都靠美工凭手感调参数:K_d 多大、shininess 多大,换个光照场景就崩。**PBR**(Physically Based Rendering)的核心革命:**让光照公式遵守物理定律,所有参数有物理意义,美工调一次材质,所有光照场景都自然过渡**。本文从辐射度量学(radiometry)的基本物理量讲起,推到 BRDF 的数学定义,从 Cook-Torrance 的微表面理论推到 GGX / Fresnel / Smith 三件套,最后讲 IBL(基于图像的光照)和 tone mapping,让你看懂 Unreal 5 Lumen、Unity HDRP、Godot 4 SSS、Bevy pbr 的 shader 代码。

## 0 · 为什么要有 PBR

传统光照模型(Lambert、Phong、Blinn-Phong)在工程上有四个痛点:

**痛点一:不保证能量守恒**。Phong 的 `diffuse + specular` 可能超过入射光强——一个白纸在强光下变成纯白无细节。视觉上"爆白"(clipping),物理上违反能量守恒。

**痛点二:参数不物理**。Phong 的 K_d(漫反射系数)和 K_s(镜面系数)是 0~1 的经验数字,美工凭感觉调。换到不同光照场景(室内到户外、夜景到日景),同一材质看起来完全不一样——必须重新调一遍。

**痛点三:视角依赖不对**。真实金属从不同角度看反射光不同(Fresnel 效应),Phong 做不到。汽车漆、湿润塑料、皮革的视觉特征都依赖 Fresnel,Phong 模型完全无法表达。

**痛点四:材质不可移植**。A 工作室的 Phong 材质参数给 B 工作室,可能效果完全不一样(因为 B 的光照模型细节不同)。材质库、3D 扫描数据、Substance Painter 输出全都没法通用。

**PBR 给出系统化解决方案**。核心思路:**光照公式严格遵循物理定律**(能量守恒、Fresnel 方程、微表面理论),所有参数有物理意义(粗糙度、金属度、反照率),美工调一次材质,所有光照下都自然过渡。

2010 年 Disney 发布"Principled BRDF"论文,把 PBR 简化到 10 个直观参数(美工不用学物理),2014 年 Unreal Engine 4 默认 PBR,2020 年 PBR 是工业标准。今天 Unreal、Unity、Godot、Blender、Substance、Houdini、Filament(Google)、Bevy 全部用 PBR。**PBR 不是"高级选项",是默认选项**。

**读完这一篇你能**:

- 解释 radiometry 的 flux / irradiance / radiance 三件套,以及它们之间的积分关系
- 写出 BRDF 的数学定义,解释为什么它要满足能量守恒、对称性、非负
- 实现完整的 Cook-Torrance BRDF(D_GGX + F_Schlick + G_Smith),用 Rust 跑 CPU PBR 渲染
- 区分 metallic / roughness 工作流和 specular / glossiness 工作流,知道为什么主流选前者
- 实现 IBL(基于图像的光照):diffuse irradiance map + specular prefilter + BRDF LUT
- 解释为什么需要 tone mapping(ACES / Reinhard),HDR 颜色如何映射到 LDR 显示器
- 看 Unreal / Unity / Godot / Bevy 的 PBR shader 代码不被吓到

## 1 · 辐射度量学(Radiometry):光的物理量

PBR 是**基于物理**的,所以先讲清楚物理量。光照不是抽象的"亮度",是**电磁辐射**——有精确的物理量。

### 1.1 四个基本量

| 物理量 | 符号 | 单位 | 直觉 |
|---|---|---|---|
| **Radiant flux**(辐射通量) | Φ | W(Watt) | 光源每秒发出多少能量 |
| **Irradiance**(辐照度) | E | W/m² | 单位面积接收多少能量 |
| **Radiance**(辐射亮度) | L | W/(m²·sr) | 单位面积、单位立体角的能量(sr = steradian 球面度) |
| **Intensity**(辐射强度) | I | W/sr | 单位立体角的能量(用于点光源) |

**直观理解**:

- **Flux** 是总能量——一个灯泡每秒发 60 焦耳(60W)
- **Irradiance** 是表面接收的密度——1m² 的桌子接收灯泡,平均每平方米 X 瓦
- **Radiance** 是更细的密度——表面上某一点、从某一方向接收的能量(radiance 是不变量,沿光线传播不衰减)
- **Intensity** 是光源的角度密度——灯泡向某方向发光有多强

**为什么 radiance 是核心**?因为 camera sensor / 人眼看到的颜色正比于 radiance(沿视线方向的 radiance)。光照计算本质是算 radiance。

### 1.2 它们的关系(积分关系)

```
Irradiance E = ∫ L(ω) cos(θ) dω        (对所有方向积分)
                  ↑ 立体角  ↑ 表面法线夹角的余弦

Radiance L = d²Φ / (dA · cos(θ) · dω)   (单位面积、单位立体角的通量)
```

这些公式看起来抽象,但用直觉记住一句话:**所有光照计算都是 radiance 在某个表面、某个方向的积分**。

### 1.3 立体角(Solid Angle)

立体角是 2D 角度向 3D 的扩展。2D 里"角度"是弧度(rad),整个圆 2π rad。3D 里"立体角"是球面度(sr),整个球面 4π sr。

一个方向 ω 用球面坐标 (θ, φ) 表示——θ 是和法线的夹角(天顶角),φ 是绕法线的方位角。整个上半球的立体角 = 2π sr。

渲染里我们写积分 `∫_hemisphere L(ω) dω`——对所有上半球方向积分。这就是"所有方向来的光的贡献之和"。

## 2 · BRDF:双向反射分布函数

### 2.1 定义

光照计算的核心问题:**从方向 ω_i 来的光,有多少反射到方向 ω_o?**

数学上定义 BRDF:

```
f_r(ω_i, ω_o) = dL_o(ω_o) / dE_i(ω_i)
```

意思是:从 ω_i 来的辐照度(dE_i),产生多少 ω_o 方向的辐射亮度(dL_o)。比值 f_r 就是 BRDF。它是一个 4 维函数(两个方向各 2 个角度)。

单位:**sr⁻¹**(每球面度)。

### 2.2 BRDF 必须满足的物理约束

**非负**:f_r ≥ 0。光不能"反向"创造能量。

**对称性(Helmholtz reciprocity)**:f_r(ω_i, ω_o) = f_r(ω_o, ω_i)。互换光源和视角,结果一样。物理上光线可逆——光从 A 到 B 还是从 B 到 A,反射比例一样。

**能量守恒**:对所有入射方向积分,反射 ≤ 入射:

```
∫_hemisphere f_r(ω_i, ω_o) cos(θ_i) dω_i ≤ 1   (对所有 ω_o)
```

cos(θ_i) 是 Lambert 余弦定律项——表面倾斜时单位面积接收的能量少。

### 2.3 BRDF 的物理意义

- **diffuse**(漫反射):光从 ω_i 来,均匀反射到所有方向。BRDF 是常数 `albedo / π`。
- **specular**(镜面反射):光从 ω_i 来,集中反射到反射方向附近一个窄锥。BRDF 在反射方向有尖峰。
- **glossy**(光滑):介于 diffuse 和 mirror 之间。BRDF 在反射方向有较宽的峰。
- **retro-reflection**(回反射):光从 ω_i 来,优先沿原路返回。BRDF 在 ω_o = -ω_i 处有峰(如猫眼、路标)。

PBR 的 BRDF = diffuse 部分 + specular 部分,两者按 Fresnel 和金属度分配比例。

## 3 · Cook-Torrance BRDF:微表面理论

### 3.1 微表面理论的直觉

Robert Cook 和 Kenneth Torrance 1982 年提出:**真实表面在微观上是无数小镜子**。每个小镜子是完美镜面反射。我们看不见单个镜子,但它们的统计平均决定了宏观反射。

**粗糙度**(roughness)控制微表面的统计分布:

- roughness = 0:所有微表面法线和宏观法线对齐,完美镜子
- roughness = 1:微表面法线随机分布,纯漫反射外观(虽然技术上还是镜面,只是统计上像漫反射)

**关键洞察**:`roughness` 是物理参数(微表面斜率的统计量),不是美工凭感觉调的"shininess"。

### 3.2 Cook-Torrance 公式

```
f_r = k_d · f_lambert + k_s · f_cook_torrance
```

- `f_lambert = albedo / π` — 漫反射(Lambert 归一化版)
- `k_d = (1 - F) · (1 - metallic)` — 漫反射占比(金属没漫反射)
- `k_s = F` — 镜面占比(Fresnel 决定)
- `f_cook_torrance = (D · F · G) / (4 · (N·L) · (N·V))` — 微表面镜面反射

`D · F · G` 是著名的三件套,下面逐一讲。

### 3.3 D(NDF,Normal Distribution Function,法线分布函数)

**作用**:表示"有多少微表面的法线和半程向量 H 对齐"。H 是 L 和 V 的中间向量。

主流算法:**GGX / Trowbridge-Reitz**(1975, Walt Disney 2012 重新流行):

```
D = α² / (π · ((N·H)² · (α² - 1) + 1)²)

其中 α = roughness²
```

每行解释:

- `α = roughness²` — Disney 发现把 roughness 平方后视觉更线性(美工调 roughness 0.5 应该看起来"半粗糙",而不是 0.25 的效果)
- `(N·H)²` — 半程向量和法线的对齐程度
- 分母是 normalization,确保能量守恒

GGX 的特点:**长尾**(long tail)——比 Phong 的尖峰衰减慢,有"光晕"效果,更接近真实金属。

### 3.4 F(Fresnel 项,Schlick 近似)

**作用**:从这个角度,反射比例是多少。Augustin-Jean Fresnel 1820 年代提出精确方程,Schlick 1994 给出快速近似:

```
F = F0 + (1 - F0) · (1 - (V·H))^5
```

- `F0` — 垂直观察时的反射率(0 度入射)
- `(V·H)` — 视线和半程向量的对齐(等价于入射角余弦)

**F0 的取值**:

- **非金属**(dielectric):F0 ≈ 0.04(灰度,对所有非金属都一样,因为折射率差别小)
- **金属**(metal):F0 = albedo 本身(金属没漫反射,所有反射都是镜面,F0 直接用表面颜色)

**Fresnel 效应**:从掠射角(几乎平行表面)看任何材质,反射都接近 100%。这是菲涅尔方程的预测,也是 PBR 比传统光照更真实的关键——传统光照完全没这个效果。

### 3.5 G(Geometry Occlusion,Smith + Schlick-GGX)

**作用**:有多少微表面被其他微表面挡住(从视线方向看)或挡光(从光源方向看)。这是**几何遮蔽**项。

主流算法:**Smith geometry function + Schlick-GGX**:

```
G = G_sub(N, V) · G_sub(N, L)

G_sub(N, X) = N·X / (N·X · (1 - k) + k)

k 直接版本(非 IBL):   k = (roughness + 1)² / 8
k IBL 版本(用于环境光): k = roughness² / 2
```

每行解释:

- 分别对 V(视线)和 L(光源)算几何遮蔽,相乘
- `N·X` — 表面和方向的对齐
- `k` 是 roughness 的函数,粗糙表面遮蔽更多

### 3.6 分母:4 · (N·L) · (N·V)

这个 4 是 Cook-Torrance 论文推导出的 normalization 因子。`(N·L)` 是光源和表面法线的对齐(光强投影),`(N·V)` 是视线和法线的对齐(视角投影)。

加 `1e-4` 防除零(当 N·L 或 N·V 接近 0 时,视角几乎平行表面,有数值不稳定)。

## 4 · Metalness 工作流:金属 vs 非金属

PBR 把材质分成两类,用 `metallic` 参数(0~1)混合。

### 4.1 金属(metal / conductor)

- **没有漫反射**:金属的电子是自由的,光进入金属立刻被吸收(变成热量),不散射出来
- **F0 = albedo**:金属的所有反射都是镜面,F0 直接等于表面颜色
- **典型 F0**:铜 (0.95, 0.64, 0.54)、金 (1.0, 0.71, 0.29)、铝 (0.91, 0.92, 0.92)

### 4.2 非金属(dielectric / insulator)

- **有漫反射 + 镜面反射**:光进入非金属内部,散射出来形成漫反射;表面反射形成镜面
- **F0 ≈ 0.04**:对所有非金属都差不多(水 0.02、塑料 0.04~0.05、玻璃 0.04)
- **albedo 决定漫反射颜色**

### 4.3 Metallic-Roughness 工作流(主流)

主流引擎(Unreal、Unity、Godot、Bevy、Filament)用这套:

- `baseColor`(RGB 纹理)— 非金属时是漫反射颜色,金属时是 F0
- `metallic`(灰度纹理)— 0 非金属,1 金属
- `roughness`(灰度纹理)— 0 光滑,1 粗糙

**为什么主流选这套?** 美工更直观(看到颜色就知道是金属还是非金属),纹理更紧凑(只需 RGB + 2 灰度 = 5 通道),Substance Painter / Quixel 默认输出这套。

### 4.4 Specular-Glossiness 工作流(备选)

另一种 PBR 工作流:

- `diffuse`(RGB)— 漫反射颜色(金属时为黑)
- `specular`(RGB)— F0(金属和非金属都用 RGB 表达)
- `glossiness`(灰度)— 1 - roughness

更灵活(每个材质的 F0 可独立调),但纹理更多(3 RGB + 1 灰度 = 10 通道),美工更易出错(把金属的 specular 调错)。Unity HDRP 支持两套,Unreal 只支持 metallic-roughness。

## 5 · 完整 Cook-Torrance Rust 实现

下面是完整的 PBR BRDF 实现,纯 Rust,可在 CPU 上跑(也可改写为 GLSL)。

```rust
use std::f32::consts::PI;

#[derive(Copy, Clone, Debug)]
pub struct Vec3 { pub x: f32, pub y: f32, pub z: f32 }

impl Vec3 {
    pub fn new(x: f32, y: f32, z: f32) -> Self { Self { x, y, z } }
    pub fn dot(self, o: Self) -> f32 { self.x*o.x + self.y*o.y + self.z*o.z }
    pub fn scale(self, k: f32) -> Self { Self::new(self.x*k, self.y*k, self.z*k) }
    pub fn add(self, o: Self) -> Self { Self::new(self.x+o.x, self.y+o.y, self.z+o.z) }
    pub fn sub(self, o: Self) -> Self { Self::new(self.x-o.x, self.y-o.y, self.z-o.z) }
    pub fn mul_comp(self, o: Self) -> Self { Self::new(self.x*o.x, self.y*o.y, self.z*o.z) }
    pub fn length(self) -> f32 { self.dot(self).sqrt() }
    pub fn normalized(self) -> Self {
        let l = self.length();
        if l > 1e-6 { self.scale(1.0/l) } else { Self::new(0.0, 0.0, 0.0) }
    }
}

/// D_GGX: 法线分布函数(Trowbridge-Reitz GGX)
/// 返回 [0, ∞),值越大表示更多微表面对齐 H
fn d_ggx(n: Vec3, h: Vec3, roughness: f32) -> f32 {
    let a = roughness * roughness;
    let a2 = a * a;
    let ndoth = n.dot(h).max(0.0);
    let ndoth2 = ndoth * ndoth;

    let denom = ndoth2 * (a2 - 1.0) + 1.0;
    // 防止除零:denom 接近 0 时(GGX 的奇异点)返回 0
    if denom.abs() < 1e-7 { return 0.0; }
    a2 / (PI * denom * denom)
}

/// F_Schlick: Fresnel 近似
/// cos_theta: V·H(或 L·H,等价)
/// f0: 垂直入射反射率(对每个 RGB 通道)
fn f_schlick(cos_theta: f32, f0: Vec3) -> Vec3 {
    let ct = cos_theta.min(1.0);  // 数值稳定
    let factor = (1.0 - ct).powi(5);
    f0.add(Vec3::new(1.0, 1.0, 1.0).sub(f0).scale(factor))
}

/// G_Smith: 几何遮蔽(Schlick-GGX 组合)
fn g_smith(n: Vec3, v: Vec3, l: Vec3, roughness: f32) -> f32 {
    // k 在直接光照下用 (roughness + 1)^2 / 8(IBL 用 roughness^2 / 2)
    let r = roughness + 1.0;
    let k = (r * r) / 8.0;
    let g_sub = |n: Vec3, x: Vec3| -> f32 {
        let ndotx = n.dot(x).max(0.0);
        ndotx / (ndotx * (1.0 - k) + k + 1e-7)
    };
    g_sub(n, v) * g_sub(n, l)
}

/// Cook-Torrance specular BRDF
fn cook_torrance_specular(
    n: Vec3, v: Vec3, l: Vec3, h: Vec3,
    f0: Vec3, roughness: f32,
) -> Vec3 {
    let d = d_ggx(n, h, roughness);
    let f = f_schlick(v.dot(h).max(0.0), f0);
    let g = g_smith(n, v, l, roughness);

    let ndotv = n.dot(v).max(0.0);
    let ndotl = n.dot(l).max(0.0);
    let denom = 4.0 * ndotv * ndotl + 1e-7;

    f.scale(d * g / denom)
}

/// 完整 PBR BRDF
///
/// base_color: RGB 0..1
/// metallic: 0 非金属, 1 金属
/// roughness: 0 光滑, 1 粗糙
/// n: 表面法线(单位)
/// l: 指向光源(单位)
/// v: 指向相机(单位)
pub fn pbr_brdf(
    base_color: Vec3,
    metallic: f32,
    roughness: f32,
    n: Vec3,
    l: Vec3,
    v: Vec3,
) -> Vec3 {
    let n = n.normalized();
    let l = l.normalized();
    let v = v.normalized();
    let h = l.add(v).normalized();  // 半程向量

    // F0: 非金属 0.04,金属 = base_color
    let f0_dielectric = Vec3::new(0.04, 0.04, 0.04);
    let f0 = f0_dielectric.scale(1.0 - metallic).add(base_color.scale(metallic));

    // Specular 部分
    let spec = cook_torrance_specular(n, v, l, h, f0, roughness);

    // Fresnel 用于计算 k_s 和 k_d
    let f = f_schlick(v.dot(h).max(0.0), f0);

    // k_d = (1 - F) * (1 - metallic)
    // 金属没漫反射,所以乘 (1 - metallic)
    let kd = Vec3::new(1.0, 1.0, 1.0).sub(f).scale(1.0 - metallic);

    // Diffuse 部分(Lambert 归一化)
    let diff = kd.mul_comp(base_color).scale(1.0 / PI);

    // 总 BRDF
    diff.add(spec)
}

/// 单点光源的着色
///
/// 加上距离衰减和 N·L 项,得到最终像素颜色(HDR, 可能 > 1.0)
pub fn shade_point_light(
    base_color: Vec3,
    metallic: f32,
    roughness: f32,
    n: Vec3,           // 表面法线
    world_pos: Vec3,   // 片段世界坐标
    light_pos: Vec3,
    light_color: Vec3, // 已包含强度
    cam_pos: Vec3,
) -> Vec3 {
    let l = light_pos.sub(world_pos).normalized();
    let v = cam_pos.sub(world_pos).normalized();
    let ndotl = n.dot(l).max(0.0);
    if ndotl == 0.0 { return Vec3::new(0.0, 0.0, 0.0); }  // 背面无光

    let brdf = pbr_brdf(base_color, metallic, roughness, n, l, v);

    // 距离衰减(反平方)
    let dist = light_pos.sub(world_pos).length();
    let attenuation = 1.0 / (dist * dist + 1e-4);

    // 出射 radiance = BRDF * E_i * N·L
    // E_i = light_color * attenuation
    brdf.mul_comp(light_color).scale(attenuation * ndotl)
}
```

每段注释:

- `f0` 的混合:金属和非金属通过 `metallic` 线性插值。`f0_dielectric.scale(1-metallic) + base_color.scale(metallic)` 是工业标准做法
- `kd = (1 - F) * (1 - metallic)`:Fresnel 给镜面,剩余给漫反射;金属无漫反射
- `denom` 加 `1e-7` 避免除零
- `powi(5)` 比 `powf(5.0)` 快——前者用整数指数,GPU 友好
- `shade_point_light` 加距离衰减(反平方定律),反平方在物理上严格正确,但视觉上太刺,工业实践用 `1/(dist² + 1)` 之类的"反平方 + 平滑过渡"

## 6 · IBL:基于图像的光照

PBR 单点光源看起来不错,但真实场景有**环境光**——天空、地面、周围物体反射的光。环境光从四面八方来,不是单一方向。

**IBL**(Image-Based Lighting)用一张环境贴图(通常 cubemap,从场景拍摄的全景图)表达环境光。PBR 的 IBL 分两部分:

### 6.1 Diffuse IBL(Irradiance Map)

**问题**:Lambert 漫反射需要对所有方向积分环境光。每次片段计算积分太贵。

**解决**:预先把环境光 cubemap 卷积成 **irradiance map**——每个 texel 存"从这个法线方向看的所有半球的平均 radiance"。运行时按法线采样,一次纹理查询就拿到环境光的 diffuse 贡献。

```
IrradianceMap[n] = ∫_hemisphere Environment[ω] · cos(θ) dω
```

预计算一次,运行时直接用。

### 6.2 Specular IBL(Prefilter Environment Map + BRDF LUT)

Specular 部分更复杂,因为反射方向取决于 roughness。PBR 用两个纹理表达:

**Prefiltered Environment Map**:对每个 roughness 级别,预先用 GGX 分布卷积环境光。生成 mipmap chain,每级对应一个 roughness(0 级 = 镜面,顶级 = 完全粗糙)。运行时按 roughness 选 mip 级别采样。

**BRDF LUT(2D 查找表)**:把 Cook-Torrance BRDF 的"剩余部分"(主要是 F 和 G 的组合)预计算成 2D 纹理,坐标是 (N·V, roughness)。运行时按这两个值采样,拿到 (scale, bias) 用于 Fresnel 修正。

合起来:specular IBL = PrefilteredEnvMap[reflection · roughness] · (F0 * scale + bias)

这是 Split-Sum Approximation(Karis 2013, Unreal Engine 4 SIGGRAPH course),把昂贵的预计算拆成两张可缓存纹理。

### 6.3 IBL Rust 实现伪代码

```rust
fn precompute_irradiance_map(env_map: &Cubemap) -> Cubemap {
    let mut irradiance = Cubemap::new(32, 32, 6);  // 低分辨率即可
    for face in 0..6 {
        for y in 0..32 {
            for x in 0..32 {
                let n = cubemap_pixel_to_normal(face, x, y, 32);
                // 对所有上半球方向积分
                let mut sum = Vec3::new(0.0, 0.0, 0.0);
                let samples = 1024;  // 蒙特卡洛采样
                for _ in 0..samples {
                    let wi = random_hemisphere_sample(n);
                    let cos_theta = n.dot(wi).max(0.0);
                    sum = sum.add(env_map.sample(wi).scale(cos_theta));
                }
                irradiance.set_pixel(face, x, y, sum.scale(PI / samples as f32));
            }
        }
    }
    irradiance
}
```

## 7 · Tone Mapping:HDR 到 LDR 的映射

PBR 计算的颜色是 **HDR**(High Dynamic Range)——可能 > 1.0(强光下铜反射 5.0、太阳直射 100.0)。但显示器只能显示 [0, 1] LDR。直接 clamp 会让强光变白,暗部不变,视觉上"爆白"。

**Tone mapping** 把 HDR 平滑映射到 [0, 1]:

### 7.1 Reinhard(简单)

```
c' = c / (1 + c)
```

简单,但亮部对比度不够。适合"轻量级"场景。

### 7.2 ACES Filmic(主流)

```
// ACES Narkowicz 近似
fn aces_tonemap(c: Vec3) -> Vec3 {
    let a = 2.51; let b = 0.03; let c = 2.43; let d = 0.59; let e = 0.14;
    Vec3::new(
        (c.x * (a * c.x + b)) / (c.x * (c.x * c + d) + e),
        (c.y * (a * c.y + b)) / (c.y * (c.y * c + d) + e),
        (c.z * (a * c.z + b)) / (c.z * (c.z * c + d) + e),
    )
}
```

ACES(Academy Color Encoding System)是电影工业标准,曲线 S 形——暗部对比度好,亮部平滑过渡到白,色彩保留好。Unreal、Unity、Godot 默认 ACES。

### 7.3 Tone Mapping 必须在最后

PBR 流程:

```
Linear 计算 (光照, IBL)        ← 物理空间,值域 [0, ∞)
    ↓
Tone Mapping (ACES)            ← HDR → LDR,值域 [0, 1]
    ↓
Gamma 校正 (sRGB)              ← 输出显示器,值域 [0, 1]
```

顺序不能颠倒。Tone mapping 必须在线性空间做,做完再 sRGB encode。

## 8 · GLSL Fragment Shader(完整 PBR)

```glsl
#version 330 core

in vec3 v_world_pos;
in vec3 v_world_normal;
in vec2 v_uv;

out vec4 frag_color;

uniform vec3 u_cam_pos;

// 材质
uniform sampler2D u_albedo;
uniform float u_metallic;
uniform float u_roughness;

// 光源
uniform vec3 u_light_pos;
uniform vec3 u_light_color;
uniform float u_light_intensity;

// IBL
uniform samplerCube u_irradiance_map;
uniform samplerCube u_prefilter_map;
uniform sampler2D u_brdf_lut;

const float PI = 3.14159265359;

// D, F, G 函数(略,见 Rust 版本)
float distribution_ggx(vec3 N, vec3 H, float roughness);
vec3 fresnel_schlick(float cos_theta, vec3 F0);
float geometry_smith(vec3 N, vec3 V, vec3 L, float roughness);

void main() {
    vec3 albedo = texture(u_albedo, v_uv).rgb;
    vec3 N = normalize(v_world_normal);
    vec3 V = normalize(u_cam_pos - v_world_pos);
    vec3 R = reflect(-V, N);

    // F0
    vec3 F0 = mix(vec3(0.04), albedo, u_metallic);

    // 直接光照
    vec3 Lo = vec3(0.0);
    {
        vec3 L = normalize(u_light_pos - v_world_pos);
        vec3 H = normalize(V + L);
        float dist = length(u_light_pos - v_world_pos);
        float attenuation = 1.0 / (dist * dist);
        vec3 radiance = u_light_color * u_light_intensity * attenuation;

        // Cook-Torrance
        float NDF = distribution_ggx(N, H, u_roughness);
        vec3 F = fresnel_schlick(max(dot(H, V), 0.0), F0);
        float G = geometry_smith(N, V, L, u_roughness);

        vec3 numerator = NDF * F * G;
        float denominator = 4.0 * max(dot(N, V), 0.0) * max(dot(N, L), 0.0) + 0.001;
        vec3 specular = numerator / denominator;

        vec3 kS = F;
        vec3 kD = (vec3(1.0) - kS) * (1.0 - u_metallic);

        float NdotL = max(dot(N, L), 0.0);
        Lo += (kD * albedo / PI + specular) * radiance * NdotL;
    }

    // IBL ambient
    vec3 kS = fresnel_schlick(max(dot(N, V), 0.0), F0);
    vec3 kD = (vec3(1.0) - kS) * (1.0 - u_metallic);
    vec3 irradiance = texture(u_irradiance_map, N).rgb;
    vec3 diffuse = irradiance * albedo;

    const float MAX_REFLECTION_LOD = 4.0;
    vec3 prefiltered = textureLod(u_prefilter_map, R, u_roughness * MAX_REFLECTION_LOD).rgb;
    vec2 brdf = texture(u_brdf_lut, vec2(max(dot(N, V), 0.0), u_roughness)).rg;
    vec3 specular = prefiltered * (kS * brdf.x + brdf.y);

    vec3 ambient = (kD * diffuse + specular);

    vec3 color = ambient + Lo;

    // Tone mapping (ACES)
    color = (color * (2.51 * color + 0.03)) / (color * (2.43 * color + 0.59) + 0.14);

    // Gamma 校正
    color = pow(color, vec3(1.0 / 2.2));

    frag_color = vec4(color, 1.0);
}
```

每段注释:

- `F0 = mix(vec3(0.04), albedo, u_metallic)` — 非金属 0.04,金属 albedo
- `kD = (1 - kS) * (1 - metallic)` — 金属无漫反射
- `textureLod(u_prefilter_map, R, roughness * MAX_LOD)` — 按 roughness 选 mip 级别
- `brdf = texture(u_brdf_lut, vec2(NdotV, roughness)).rg` — 2D 查找表,r 是 scale,g 是 bias
- Tone mapping 在最后,gamma 校正紧跟其后

## 9 · 引擎对比

主流引擎的 PBR 管线各有侧重。

### Unreal Engine 5

- **BRDF**:默认 Cook-Torrance GGX
- **IBL**:用 Lumen 全局光照系统(GPU 算实时 GI,不再依赖预计算 irradiance map)
- **Tone mapping**:ACES Filmic
- **特殊**:Nanite 虚拟几何(微多边形)、Lumen GI——PBR 5.0 后大幅扩展
- **Material Editor**:节点式材质编辑器,美工可视化连结 BRDF 节点

### Unity HDRP

- **BRDF**:GGX +Disney Principled
- **IBL**:预计算 + 实时反射探测器(Reflection Probe)
- **Tone mapping**:ACES、Linear、Neutral 可选
- **特殊**:Subsurface scattering(SSS)用于皮肤、蜡;Hair/ Fur material 专用 shader

### Godot 4

- **BRDF**:GGX + Burley(disney 漫反射)
- **IBL**:ReflectionProbe + GIProbe(实时 Voxel GI)
- **Tone mapping**:Linear、Reinhard、Filmic、ACES
- **特殊**:SDF Shadows、Voxel GI、Forward+/Mobile/Compatibility 三套渲染管线

### Bevy bevy_pbr crate

- **BRDF**:Cook-Torrance GGX,完全在 `bevy_pbr` crate 实现
- **IBL**:环境贴图 + irradiance map
- **Tone mapping`:多种(TonyMcMapface、ACES、Reinhard 等)
- **设计哲学**:模块化、ECS 驱动、组件可热替换;Crate 层级清晰——`bevy_pbr`(高阶)依赖 `bevy_render`(底阶)
- **代码可读**:推荐读源码学 PBR 实现,比 Unreal 简洁得多

## 10 · 历史

- **1760** Lambert 余弦定律(漫反射的几何基础)
- **1820** Fresnel 方程(精确反射率)
- **1975** Phong 模型
- **1977** Blinn-Phong
- **1981** Cook & Torrance "A Reflectance Model for Computer Graphics",微表面理论
- **1982** Beckmann distribution(早期 NDF)
- **1975** GGX / Trowbridge-Reitz
- **2007** Disney 主导 GGX 复活
- **2010** Disney "Principled BRDF" SIGGRAPH,把 PBR 简化到 10 参数
- **2012** Karis "Real Shading in Unreal Engine 4",Split-Sum Approximation
- **2014** Unreal Engine 4 默认 PBR
- **2016** Unity 5 默认 PBR(Standard Shader)
- **2020** Unreal 5 Lumen,实时 GI 取代静态 IBL
- **2022** Bevy 0.10 PBR pipeline 成熟

## 11 · 关联 Day

- **铺垫**:Day 041 数学概览(点积);Day 094 sRGB ↔ linear(光照必须 linear 空间);`days/phase-6/deep-dives/lighting-models.md`(Lambert → Phong → Blinn-Phong → PBR 引子)
- **当天**:本篇是 PBR 完整剖析(Phase 6 光照深度)
- **后续**:`days/phase-6/deep-dives/normal-mapping.md`(PBR 配法线贴图);Day 480+ 延迟着色 + 多光源;Day 500+ IBL cubemap 预计算

## 12 · 变式训练

### Lv1 · 概念辨析

**题**:PBR 引入"能量守恒"约束,它解决的实际问题是什么?为什么传统 Phong 模型不能?

**参考解答**:**没能量守恒**意味着反射出来的光多于入射,违反物理。视觉上的后果:美工调一组 K_d 和 K_s,在暗光下看着对,在强光下白得发糊(因为 K_d + K_s 没动态调整,总贡献超出范围)。**有能量守恒**意味着 K_d + K_s ≤ 入射(PBR 通过 Fresnel + Smith 自动满足),美工调一次,所有光照下都自然过渡。这把"调材质"从"凭手感"变成"有规范",材质可以跨场景复用、跨引擎迁移(Substance Painter 出的材质图通用)。

### Lv2 · 动手实践

**题**:写一个 Rust 程序,在 512×512 PNG 上用 PBR 渲染一个金属球(铜)。光源在右上前方。

完成标准:输出 PNG,球右上角有明显高光,左下角有环境光(暗但不全黑),整体色调像铜。

**参考解答**:见 §5 的 `pbr_brdf` 函数 + 以下主程序:

```rust
use image::{ImageBuffer, Rgb, RgbImage};

fn main() {
    let width = 512;
    let height = 512;
    let mut img: RgbImage = ImageBuffer::new(width, height);

    // PBR 参数(铜)
    let base_color = Vec3::new(0.95, 0.64, 0.54);
    let metallic = 1.0;
    let roughness = 0.3;

    // 光源
    let light_pos = Vec3::new(5.0, 5.0, 5.0);
    let light_color = Vec3::new(1.0, 1.0, 1.0).scale(100.0);  // 强光
    let cam_pos = Vec3::new(0.0, 0.0, 5.0);

    // 环境 ambient(简化 IBL)
    let ambient = Vec3::new(0.05, 0.05, 0.05);

    for y in 0..height {
        for x in 0..width {
            let dx = (x as f32 - width as f32 / 2.0) / (width as f32 / 4.0);
            let dy = -(y as f32 - height as f32 / 2.0) / (height as f32 / 4.0);
            let r2 = dx * dx + dy * dy;
            if r2 > 1.0 { continue; }
            let dz = (1.0 - r2).sqrt();
            let p = Vec3::new(dx, dy, dz);
            let n = p;

            let direct = shade_point_light(
                base_color, metallic, roughness,
                n, p, light_pos, light_color, cam_pos,
            );

            // 简化 IBL:固定 ambient(实际应从 irradiance map 采样)
            let total = direct.add(ambient.mul_comp(base_color));

            // Tone mapping(Reinhard 简化版)
            let mapped = Vec3::new(
                total.x / (1.0 + total.x),
                total.y / (1.0 + total.y),
                total.z / (1.0 + total.z),
            );

            // sRGB gamma 校正
            let gamma_correct = |c: f32| -> u8 {
                let c = c.max(0.0).min(1.0);
                (c.powf(1.0 / 2.2) * 255.0) as u8
            };
            img.put_pixel(x, y, Rgb([
                gamma_correct(mapped.x),
                gamma_correct(mapped.y),
                gamma_correct(mapped.z),
            ]));
        }
    }
    img.save("pbr_copper_sphere.png").unwrap();
    println!("Saved pbr_copper_sphere.png");
}
```

`Cargo.toml`:

```toml
[dependencies]
image = "0.25"
```

跑起来:

```bash
mkdir -p ~/src/pbr_copper && cd ~/src/pbr_copper
# 把代码粘进去
cargo run --release
# 输出:Saved pbr_copper_sphere.png
```

打开 PNG,看到铜色金属球,右上角高光。

### Lv3 · 迁移设计

**题**:PBR 描述光的反射,同样的微表面统计理论可以描述**声波反射**——墙面粗糙度决定回声特性。把 GGX NDF 类比到声学,设计一个简单回声模拟器。

**提示**:声波在墙面上的散射也有 specular(镜面反射,听得清的回声)+ diffuse(漫反射,模糊背景)的区分。`roughness` 等价于"墙面纹理相对于声波波长的大小"。声频高(波长几毫米),墙面纹理几厘米就算粗糙;声频低(波长几米),墙面纹理几厘米算光滑。

**思考方向**:取 GGX 公式,把 NDF 解读为"反射方向能量分布",在声学场景里算回声方向分布。这是建筑声学(Architectural Acoustics)的工业方法。

### Lv4 · 开源贡献

**题**:Bevy 的 PBR 实现是 Rust 生态里最完整的。GitHub: https://github.com/bevyengine/bevy

1. clone 它:

   ```bash
   gh repo clone bevyengine/bevy
   cd bevy/crates/bevy_pbr
   ```

2. 读 PBR shader 代码:

   ```bash
   cd render/src
   grep -l "pbr" *.rs
   # 重点关注 pbr_material.wgsl, light.rs, mesh.rs
   ```

3. 读 BRDF 实现(WGSL shader):

   ```bash
   find . -name "*.wgsl" -exec grep -l "ggx\|cook_torrance\|fresnel" {} \;
   ```

4. 可能贡献方向:

   - 文档:某个 PBR 参数没解释清楚(`perceptual_roughness` vs `roughness`,什么是 `specular_transmission`)
   - 测试:边缘 case 测试覆盖(roughness=0、metallic=0.5 的中间值)
   - 性能:`cargo flamegraph` 找 BRDF 计算的 hot spot
   - Bug:GitHub 找一个 "PBR" / "lighting" label 的未解决 issue

5. PR 草稿:

   - 标题
   - 改动文件
   - 动机(为 Bevy 用户带来什么)
   - 验证步骤

**示例**(不要照抄):

```
PR 标题:docs: clarify perceptual_roughness vs roughness in StandardMaterial
文件:crates/bevy_pbr/src/pbr_material.rs
动机:StandardMaterial 的 perceptual_roughness 字段没说明它和"raw roughness"的关系。
     读 source 才知道 bevy 内部存的是 perceptual_roughness,squaring 后给 BRDF。
     加一段 doc comment 解释 Disney convention + 给推荐值范围。
验证:cargo doc -p bevy_pbr --open,确认渲染正确。
```

## 13 · Rust / Arch 落地代码

完整可跑的 CPU PBR 渲染器(基于 §5 BRDF + §12 Lv2 主程序):

```bash
# 1. 创建项目
cargo new --bin pbr_cpu
cd pbr_cpu
cargo add image

# 2. 把 §5 的 BRDF 代码 + §12 Lv2 的主程序写进 src/main.rs

# 3. 跑
cargo run --release
# 输出: Saved pbr_copper_sphere.png

# 4. 改参数实验
# 改 metallic = 0.0,roughness = 0.5 → 哑光塑料球
# 改 metallic = 1.0,roughness = 0.0 → 镜子球(高光极锐)
# 改 metallic = 1.0,roughness = 1.0 → 粗糙金属球(像月球表面)
```

Arch 工具链:

```bash
# 装图像查看器(快速预览 PNG)
sudo pacman -S feh sxiv
feh pbr_copper_sphere.png &

# 装图形调试(如果你后续接 wgpu / glow)
sudo pacman -S renderdoc vulkan-tools mesa-utils

# 看 GPU 信息
glxinfo | grep "OpenGL renderer"
vulkaninfo --summary

# 用 perf 看 CPU PBR 渲染瓶颈
sudo pacman -S perf
cargo build --release
perf record -g ./target/release/pbr_cpu
perf report | head -30
# pbr_brdf 应该是 hot function(占 80%+ CPU)

# 用 flamegraph 可视化
cargo install flamegraph
sudo flamegraph -o flame.svg ./target/release/pbr_cpu
# 浏览器打开 flame.svg

# 测试 IBL(进阶)
# 1. 下载 HDR 环境图(https://hdrihaven.com 免费)
# 2. 写一个 ibl_precompute.rs 把 HDR 转成 irradiance map + prefilter map
# 3. 在 main 里加 ambient = irradiance_map.sample(n) * albedo / pi
```

### Troubleshooting

**问题1**:球是黑的。
**原因**:light_color 强度不够。PBR 用真实光照强度,衰减是反平方,5 米距离衰减 1/25 = 4%。需要 light_color 乘 100 才能在球上看到效果。
**解决**:把 `light_color` 调到 `Vec3::new(1.0, 1.0, 1.0).scale(100.0)` 或更大。

**问题2**:球过曝(纯白)。
**原因**:没 tone mapping。PBR 输出是 HDR(可能 > 1.0),需要 tone map 才能正确显示在 LDR 屏上。
**解决**:用 Reinhard `c' = c / (1 + c)` 或 ACES(见 §7)。

**问题3**:高光在错误位置。
**原因**:H = (L + V) / |L + V| 算错,或光源方向反了。L 是"从表面指向光源",不是反方向。
**解决**:在 BRDF 输出后打印 brdf.x,看是不是合理值(~0.1~1.0)。

**问题4**:金属球看起来像塑料。
**原因**:F0 算错。金属 F0 = base_color,不是 0.04。
**解决**:检查 `f0` 混合:`f0_dielectric.scale(1-metallic) + base_color.scale(metallic)`。metallic=1 时应等于 base_color。

**问题5**:粗糙度看起来"反"了(roughness=0 是粗糙,=1 是光滑)。
**原因**:Disney convention 是 `α = roughness²`,但有些代码用 `α = (1 - roughness)²`。统一约定。
**解决**:确认 `α = roughness²`,roughness=0 是镜子(α=0,NDF 是狄拉克 delta),roughness=1 是完全粗糙。

## 14 · 延伸阅读

本仓库本地:

- `days/phase-6/deep-dives/lighting-models.md` — Lambert → Phong → Blinn-Phong → PBR 引子
- `days/phase-6/deep-dives/normal-mapping.md` — PBR 配法线贴图(微表面法线扰动)
- `days/phase-6/deep-dives/shadow-mapping.md` — PBR 配阴影
- `days/phase-6/deep-dives/light-attenuation.md` — 距离衰减、IBL

外部稳定 URL:

- LearnOpenGL PBR 理论(入门经典):https://learnopengl.com/PBR/Theory
- LearnOpenGL PBR Lighting:https://learnopengl.com/PBR/Lighting
- LearnOpenGL PBR IBL:https://learnopengl.com/PBR/IBL/Diffuse-irradiance
- PBR Book(在线免费,Pharr & Humphreys):https://www.pbr-book.org/3ed-2018/Reflection_Models
- Scratchapixel materials:https://www.scratchapixel.com/lessons/3d-basic-rendering/introduction-to-shading
- Disney Principled BRDF 论文(2012):https://disney-animation.s3.amazonaws.com/library/s2012_pbs_disney_brdf_notes_v2.pdf
- Karis UE4 Real Shading(SIGGRAPH 2013):https://blog.selfshadow.com/publications/s2013-shading-course/karis/s2013_pbs_epic_notes_v2.pdf
- Filament 文档(Google PBR 实现):https://google.github.io/filament/Filament.html

真实开源源码:

- Filament BRDF shader(C++):https://github.com/google/filament/blob/main/shaders/src/brdf.fs
- bgfx PBR shader:https://github.com/bkaradzic/bgfx/blob/master/examples/common/shaderlib.sh
- Bevy PBR(WGSL,Rust):https://github.com/bevyengine/bevy/blob/main/crates/bevy_pbr/src/render/pbr_fragment.wgsl
- Casey HH 原版 day281+ PBR C 代码:https://github.com/HandmadeHero/handmade-hero
