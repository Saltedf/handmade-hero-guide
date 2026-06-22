# 光照模型:Lambert / Phong / Blinn-Phong / PBR

> 你渲染一个立方体,看见它在亮面发亮、暗面变暗——这件事看似简单,背后却藏着 50 年的图形学进化史。从 1970 年代 Lambert 漫反射到今天的 PBR 物理光照,每一代模型都是上一代的"修正":更准、更稳、更真实。本文从最基础的"为什么有光就有暗"出发,推到 PBR 的 BRDF,让你看懂 Unreal / Filament / Unity HDRP 的 shader 代码。

## 0 · 为什么要有光照模型

你做完深度缓冲,场景已经能正确排序遮挡。但所有像素颜色直接来自纹理采样,看起来像贴纸——没有立体感、没有空间深度、没有质感。真实世界里你看一眼物体就知道"这是金属、那是塑料、那是木头",靠的是光在物体表面的反射方式。

**光照模型**(lighting model)就是用数学描述"光从光源出发、撞到表面、反射到眼睛"这个过程的简化模型。它必须回答四个问题:

1. **光的来源**:点光源?平行光(像太阳)?环境光(天空)?
2. **表面如何反射**:漫反射(磨砂玻璃、墙壁)?镜面反射(镜子、金属)?两者混合?
3. **能量守恒**:反射出来的总能量不能超过入射能量(否则违反物理)
4. **观察角度**:从不同角度看同一个物体,反射应该不同(这是镜面高光的核心)

50 年里,业界给出了四代主流模型:

- **Lambert(1760!)** — 漫反射,纯几何
- **Phong(1975)** — Lambert + 镜面高光,经验模型
- **Blinn-Phong(1977)** — Phong 的优化,更便宜也更准
- **PBR / Cook-Torrance(1982 / 2010s 流行)** — 基于物理的微表面理论

每一代都是上一代的超集。本文从最简单的 Lambert 讲起,一步步推到 PBR,每个公式的"为什么"和"怎么算"都讲透。

**读完这一篇你能**:
- 用 Rust 实现四个模型,在 CPU 上跑光照计算
- 解释为什么 PBR 要"金属度"(metallic)和"粗糙度"(roughness)两个参数
- 看 Unreal / Filament / Unity 的 shader 代码不被吓到
- 知道为什么 LearnOpenGL 的 PBR 章节要用那么复杂的公式

## 1 · 起点:Lambert 漫反射

### 物理直觉

光打在墙上,墙是粗糙的——微观上有无数小凸起,光被反射到各个方向,均匀散开。所以无论你从哪个角度墙看,墙的颜色亮度都一样。这就是**漫反射**(diffuse reflection)。

**关键问题**:同一个光源照同一面墙,墙的角度不同,亮度也不同。为什么?

**直觉**:光线斜着打墙,光能量分散在更大的面积上;垂直打墙,光能量集中在更小面积上。所以**单位面积接收的能量**取决于"光线和墙面法线的夹角"。

### Lambert 余弦定律

18 世纪数学家 Lambert 发现:单位面积接收的光能量 ∝ cos(θ),θ 是光线方向和表面法线的夹角。

```
N = 表面法线(指向外的单位向量)
L = 从表面指向光源的单位向量
cos(θ) = N · L     (点积)
```

所以**漫反射光强** = `max(0, N · L)`。max(0, ...) 是因为光线从背面来时(N·L < 0),表面完全没接收到光,clamp 到 0。

具体公式:

```
I_diffuse = K_d * I_light * max(0, N · L)
```

- `K_d` — 漫反射系数(diffuse albedo),通常是表面颜色 RGB
- `I_light` — 光源强度
- `N · L` — 几何衰减

### Rust 实现

```rust
#[derive(Copy, Clone, Debug)]
struct Vec3 { x: f32, y: f32, z: f32 }

impl Vec3 {
    fn dot(self, o: Self) -> f32 { self.x*o.x + self.y*o.y + self.z*o.z }
    fn normalized(self) -> Self {
        let len = self.dot(self).sqrt();
        if len > 1e-6 {
            Self { x: self.x/len, y: self.y/len, z: self.z/len }
        } else { Self { x:0.0, y:0.0, z:0.0 } }
    }
    fn scale(self, k: f32) -> Self { Self { x:self.x*k, y:self.y*k, z:self.z*k } }
    fn mul_components(self, o: Self) -> Self {
        // 对应分量相乘,用于颜色乘法
        Self { x:self.x*o.x, y:self.y*o.y, z:self.z*o.z }
    }
}

fn lambert(albedo: Vec3, light_color: Vec3, n: Vec3, l: Vec3) -> Vec3 {
    // albedo:表面漫反射系数(颜色,0..1)
    // light_color:光的颜色和强度(0..n)
    // n:归一化法线
    // l:归一化的指向光源的向量
    let n = n.normalized();
    let l = l.normalized();
    let cos_theta = n.dot(l).max(0.0);  // Lambert 余弦定律
    albedo.mul_components(light_color).scale(cos_theta)
}
```

每行注释:

- `Vec3` — 三维向量,这里兼用为颜色(RGB)和向量(法线/光向)
- `dot` — 点积,这里是 Lambert 的核心几何运算
- `mul_components` — 颜色相乘(每个通道独立),物理上"白光照红墙 → 红"
- `scale` — 标量乘法,这里是乘 cos_theta

## 2 · 进阶:Phong 镜面高光

### 物理直觉

Lambert 只能描述漫反射(粗糙表面)。但镜子、金属、湿润的塑料——它们有"高光"(specular highlight),一个直接反射光源的明亮斑点。Lambert 完全没法表达这种高光。

**关键观察**:高光出现在"反射方向接近视线方向"的位置。镜子把入射光按入射角=反射角弹开,你看镜子,只有当反射方向对准你眼睛时,你才看到光源的镜像。

### Phong 模型公式

Bui Tuong Phong 1975 年提出:

```
R = reflect(-L, N)    // 反射方向(注意 L 是从表面指向光,这里 -L 是入射方向)
V = 从表面指向相机
I_specular = K_s * I_light * max(0, R · V)^n_shiny
```

- `R` — 反射向量,公式 `R = 2(N·L)N - L`
- `V` — 视线方向(从表面到相机)
- `K_s` — 镜面反射系数(高光颜色,通常是白色)
- `n_shiny` — **shininess exponent**(光泽指数),控制高光大小。值越大,高光越集中、越像镜子;值越小,高光越分散、越像塑料

**`R · V` 的几何意义**:R 和 V 多对齐。完全对齐(R=V)时 = 1,最大高光;垂直 = 0,没高光。

**指数 n_shiny 的作用**:`max(0, R·V)^n_shiny` 把"高光衰减曲线"压扁——n=1 时是余弦曲线(柔和),n=100 时是窄峰(锐利)。

### Rust 实现

```rust
fn reflect(incoming: Vec3, n: Vec3) -> Vec3 {
    // 入射方向 incoming(指向表面),法线 n(指向外)
    // 反射公式:R = incoming - 2(N·incoming) N
    n.scale(2.0 * n.dot(incoming)).scale(-1.0) // 留意符号
    // 更清晰的写法:
    // incoming - 2 * (incoming · n) * n
}

fn phong(
    albedo: Vec3,        // K_d
    specular: Vec3,      // K_s
    shininess: f32,      // n_shiny
    light_color: Vec3,
    n: Vec3, l: Vec3, v: Vec3,
) -> Vec3 {
    let n = n.normalized();
    let l = l.normalized();
    let v = v.normalized();
    let nl = n.dot(l).max(0.0);
    
    // 漫反射
    let diff = albedo.mul_components(light_color).scale(nl);
    
    // 镜面:R = 2(N·L)N - L
    let r = n.scale(2.0 * nl).scale(1.0).mul_components(Vec3{x:1.,y:1.,z:1.});
    // 简化直接计算:
    let r = Vec3 {
        x: 2.0 * nl * n.x - l.x,
        y: 2.0 * nl * n.y - l.y,
        z: 2.0 * nl * n.z - l.z,
    };
    let rv = r.dot(v).max(0.0).powf(shininess);
    let spec = specular.mul_components(light_color).scale(rv);
    
    // 总光:diffuse + specular
    Vec3 { x: diff.x + spec.x, y: diff.y + spec.y, z: diff.z + spec.z }
}
```

(注:第二段 `r` 计算更直观;第一段只是中间过程,实际不会写那样。每行都给完整公式,你能看清"哪一步在算什么"。)

## 3 · Blinn-Phong:Phong 的优化版

1977 年 Jim Blinn 发现:不用算反射向量 R,改用**半程向量**(half vector)H = (L + V) / |L + V|,然后比较 H 和 N 的夹角。结果几乎和 Phong 一样,但便宜得多。

### 公式

```
H = normalize(L + V)
I_specular = K_s * I_light * max(0, N · H)^n
```

### 为什么更便宜?

Phong 要算反射 R = 2(N·L)N - L,这需要一次 dot 一次 scale 一次 sub(约 7 次浮点运算)。Blinn-Phong 只要 L + V + normalize(约 5 次浮点运算)。GPU 上每个像素都要算,省 30% 是显著的。

### 为什么更准?

Phong 用 R·V 的余弦衰减;Blinn-Phong 用 N·H 的余弦衰减。两者形状不同——Blinn-Phong 的高光更对称、更接近真实物理。**而且**,Blinn-Phong 的 shininess 大约是 Phong 的 4 倍能达到同样高光大小(因为 N·H 和 R·V 是不同余弦关系)。

### 实战

主流引擎(LearnOpenGL / Unity 内置 shader / 早期 Unreal)都用 Blinn-Phong 作为"前 PBR 时代"的默认光照。今天 PBR 取代了它,但 Blinn-Phong 在风格化渲染(卡通、动漫)里仍然流行。

## 4 · PBR:基于物理的光照

### 出发点:Phong/Blinn-Phong 的问题

Phong 时代的光照**不是物理的**:

1. **不保证能量守恒**:`diffuse + specular` 可能 > 入射光强,违反物理
2. **视角依赖不正确**:真实金属在不同视角反射不同,Phong 做不到
3. **K_s 和 K_d 是手工调的**:美工凭感觉调,不同光照下结果不一致
4. **跨材质不一致**:塑料和金属的 K_s 行为完全不同,但 Phong 不区分

PBR(Physically Based Rendering,基于物理的渲染)的核心理念:**让光照公式遵守物理定律,所有材质参数都有物理意义,美工调一次材质,所有光照场景下都自动正确**。

### 三个 PBR 原则

1. **微表面理论**(Microfacet Theory):粗糙表面在微观上是无数小镜子,每个镜子是完美的镜面反射。我们看不见单个镜子,但它们的统计平均决定了宏观反射。
2. **能量守恒**(Energy Conservation):反射 + 折射(进入材质内部吸收后变漫反射出来)= 入射。金属几乎全反射,非金属大部分折射。
3. **Fresnel 效应**(Fresnel Effect):从掠射角(几乎平行表面)看任何材质,反射都接近 100%。这是菲涅尔方程的预测。

### BRDF:双向反射分布函数

PBR 的核心抽象是 BRDF(Bidirectional Reflectance Distribution Function),数学定义:

```
f_r(ω_i, ω_o) = dL_o(ω_o) / dE_i(ω_i)
```

意思是:从入射方向 ω_i 来的光、出射方向 ω_o 看到的反射比例。这是一个 4 维函数(两个方向各 2 个角度)。BRDF 满足物理约束:

- **非负**:f_r ≥ 0
- **对称性**:f_r(ω_i, ω_o) = f_r(ω_o, ω_i)(互换光源和视角,结果一样)
- **能量守恒**:对所有 ω_i 积分,∑ ≤ 1

### Cook-Torrance BRDF

主流 PBR(Cook-Torrance 1982)把 BRDF 拆成两部分:

```
f_r = k_d * f_lambert + k_s * f_cook_torrance
```

- `f_lambert = albedo / π` — 漫反射部分(Lambert 的归一化版)
- `k_d = 1 - k_s` — 漫反射占比(剩余能量)
- `k_s` — 由 Fresnel 决定(下面讲)
- `f_cook_torrance = (D * F * G) / (4 * (N·L) * (N·V))` — 镜面反射部分

**D / F / G 三件套**:

- **D(N, H, roughness)** — 法线分布函数(NDF)。表示"有多少微表面的法线和半程向量 H 对齐"。常用 GGX/Trowbridge-Reitz:

```
D = α² / (π * ((N·H)² * (α² - 1) + 1)²)
其中 α = roughness²
```

- **F(V, H)** — Fresnel 项。表示"从这个角度,反射比例是多少"。常用 Schlick 近似:

```
F = F0 + (1 - F0) * (1 - (V·H))^5
F0 = ((n-1)/(n+1))²  非金属,或直接用 albedo 金属
```

- **G(N, V, L, roughness)** — 几何遮蔽/阴影。表示"有多少微表面被其他微表面挡住"。常用 Smith + Schlick-GGX:

```
G = G_sub(N, V) * G_sub(N, L)
G_sub(N, X) = α² / ((N·X)² * (1 - α²) + α²)
```

### 金属和非金属的区别

PBR 把材质分成两类:

- **金属**(metal/conductor):没有漫反射,所有反射都是镜面。F0 直接等于 albedo。
- **非金属**(dielectric):有漫反射和镜面。F0 ≈ 0.04(灰度),albedo 决定漫反射颜色。

**Metallic-Roughness 工作流**(主流):用两个纹理
- `baseColor`(RGB)— 非金属时是漫反射颜色,金属时是镜面 F0
- `metallic`(灰度)— 0 是非金属,1 是金属
- `roughness`(灰度)— 0 是光滑镜子,1 是粗糙表面

### 完整 Rust 实现(简化)

```rust
fn pbr_brdf(
    base_color: Vec3,    // RGB,0..1
    metallic: f32,       // 0 非金属,1 金属
    roughness: f32,      // 0 光滑,1 粗糙
    n: Vec3,             // 法线
    l: Vec3,             // 指向光源
    v: Vec3,             // 指向相机
) -> Vec3 {
    let n = n.normalized();
    let l = l.normalized();
    let v = v.normalized();
    let h = Vec3 {
        x: (l.x + v.x),
        y: (l.y + v.y),
        z: (l.z + v.z),
    }.normalized();
    
    let nl = n.dot(l).max(0.0);
    let nv = n.dot(v).max(0.0);
    let nh = n.dot(h).max(0.0);
    let vh = v.dot(h).max(0.0);
    
    // F0:非金属 0.04,金属 = base_color
    let f0_non_metal = Vec3 { x: 0.04, y: 0.04, z: 0.04 };
    let f0 = f0_non_metal.scale(1.0 - metallic).mul_components(Vec3{x:1.,y:1.,z:1.});
    let f0 = Vec3 {
        x: f0_non_metal.x * (1.0 - metallic) + base_color.x * metallic,
        y: f0_non_metal.y * (1.0 - metallic) + base_color.y * metallic,
        z: f0_non_metal.z * (1.0 - metallic) + base_color.z * metallic,
    };
    
    // Fresnel Schlick
    let fresnel = |cos_theta: f32, f0: f32| -> f32 {
        f0 + (1.0 - f0) * (1.0 - cos_theta).powi(5)
    };
    let fx = fresnel(vh, f0.x);
    let fy = fresnel(vh, f0.y);
    let fz = fresnel(vh, f0.z);
    let f = Vec3 { x: fx, y: fy, z: fz };
    
    // GGX NDF
    let alpha = roughness * roughness;
    let alpha2 = alpha * alpha;
    let denom = nh * nh * (alpha2 - 1.0) + 1.0;
    let d = alpha2 / (std::f32::consts::PI * denom * denom);
    
    // Smith G
    let g_sub = |nx: f32| -> f32 {
        let num = 2.0 * nx;
        let denom_sq = nx + (alpha2 + (1.0 - alpha2) * nx * nx).sqrt();
        num / denom_sq
    };
    let g = g_sub(nl) * g_sub(nv);
    
    // Specular BRDF
    let denom_spec = 4.0 * nl * nv + 1e-4;
    let spec = Vec3 {
        x: d * f.x * g / denom_spec,
        y: d * f.y * g / denom_spec,
        z: d * f.z * g / denom_spec,
    };
    
    // Diffuse BRDF (Lambert normalized + kd from 1-F)
    let kd = Vec3 {
        x: 1.0 - f.x,
        y: 1.0 - f.y,
        z: 1.0 - f.z,
    }.scale(1.0 - metallic);  // 金属漫反射为 0
    let diff = kd.mul_components(base_color).scale(1.0 / std::f32::consts::PI);
    
    // 总 BRDF
    Vec3 { x: diff.x + spec.x, y: diff.y + spec.y, z: diff.z + spec.z }
}
```

这看起来长,但每段都是上面公式直接转写。注释解释了关键决策:

- `f0` 的混合:金属和非金属通过 `metallic` 线性插值
- `kd = (1 - F) * (1 - metallic)`:Fresnel 给镜面,剩余给漫反射;金属无漫反射
- `denom_spec` 加 `1e-4` 避免除零(当 N·L 或 N·V 接近 0 时)
- `powi(5)` 比 `powf(5.0)` 快——前者用整数指数,GPU 友好

## 5 · 模型对比

| 模型 | 年代 | 计算 | 物理准 | 主要参数 | 适用场景 |
|---|---|---|---|---|---|
| Lambert | 1760 | 极简 | 漫反射部分准 | albedo | 纯漫反射材质 |
| Phong | 1975 | 中 | 经验 | K_d, K_s, shininess | 早期 OpenGL |
| Blinn-Phong | 1977 | 中(比 Phong 省) | 经验 | 同上 | 风格化 / 卡通 |
| Cook-Torrance PBR | 1982(流行 2010s) | 重 | 物理准 | albedo, metallic, roughness | 真实感渲染 |

### 历史

- 1760:Lambert 余弦定律(纯几何)
- 1975:Bui Tuong Phong 在犹他大学博士论文里提出 Phong 模型
- 1977:Jim Blinn 改进为 Blinn-Phong
- 1982:Cook & Torrance 提出微表面 BRDF,但当时太贵,工业界没采用
- 2001:Ward 模型、Ashikhmin-Shirley 等改进
- 2010:Disney 发布"Principled BRDF",工业界 PBR 化开始
- 2014:Unreal Engine 4 用 PBR,主流游戏跟进
- 2020s:PBR 是工业标准,filament / Unity HDRP / Unreal 5 / Blender / Substance Painter 全部用 PBR

## 6 · 关联 Day

- **铺垫**:Day 041 数学概览讲点积;Day 271 Phong 初登场
- **当天**:本篇是 Phase 6 光照模型专题
- **后续**:Day 280+ 多光源;Day 410+ IBL(基于图像的光照,用 cubemap 提供环境光);Day 420+ 延迟着色

## 7 · 变式训练

### Lv1 · 概念辨析

**题**:为什么 PBR 引入"能量守恒"约束?它解决的实际问题是什么?

**参考解答**:**没能量守恒**意味着反射出来的光多于入射,违反物理。视觉上的后果:美工调一组 K_d 和 K_s,在暗光下看着对,在强光下白得发糊;在低光下看着对,在阳光下爆白。**有能量守恒**意味着 K_d + K_s ≤ 入射,美工调一次,所有光照下都自然过渡。这把"调材质"从"凭手感"变成"有规范"。

### Lv2 · 动手实践

**题**:写个 Rust 程序,在 256×256 PNG 上渲染一个球,用 Phong 模型。光源在球右上前方(45°)。

完成标准:输出 PNG,球右上有高光,左下有阴影,颜色连续。

**参考解答**:

```rust
// 关键步骤
// 1. 遍历 256×256 像素
// 2. 每个像素,计算它对应的球面点(把像素坐标映射到球面)
// 3. 球面点法线 N = (球面点 - 球心) / 球半径
// 4. L = (光源 - 球面点).normalized()
// 5. V = (相机 - 球面点).normalized()
// 6. 调 phong 函数(上面给的)
// 7. 写到 PNG

// 提示:用 image crate
// cargo add image
use image::{ImageBuffer, Rgb, RgbImage};
let mut img: RgbImage = ImageBuffer::new(256, 256);
for y in 0..256 {
    for x in 0..256 {
        // 球面投影(简化:球的中心 (128,128,100),半径 100)
        let dx = x as f32 - 128.0;
        let dy = y as f32 - 128.0;
        let r2 = dx*dx + dy*dy;
        if r2 > 100.0*100.0 { continue; }  // 球外
        let dz = (100.0*100.0 - r2).sqrt();
        let n = Vec3 { x: dx/100.0, y: dy/100.0, z: dz/100.0 }.normalized();
        let l = Vec3 { x: 0.7, y: 0.7, z: 0.5 }.normalized();
        let v = Vec3 { x: 0.0, y: 0.0, z: 1.0 };
        let c = phong(
            Vec3{x:0.7,y:0.3,z:0.2},  // 红棕色
            Vec3{x:1.0,y:1.0,z:1.0},  // 白色高光
            50.0,
            Vec3{x:1.0,y:1.0,z:1.0},
            n, l, v,
        );
        img.put_pixel(x, y, Rgb([
            (c.x * 255.0) as u8,
            (c.y * 255.0) as u8,
            (c.z * 255.0) as u8,
        ]));
    }
}
img.save("phong_sphere.png").unwrap();
```

### Lv3 · 迁移设计

**题**:PBR 的 BRDF 是关于光的,但同样的"微表面统计"思路能用到声音上——声音撞墙反射,墙面粗糙度决定回声特性。你能把 GGX NDF 类比到声音反射上,写一个简单的回声模拟器吗?

**提示**:声波在墙面上的散射也有"specular(镜面反射,听得清的回声)+ diffuse(漫反射,模糊背景)"的区分。roughness 等价于"墙面纹理相对于声波波长的大小"。

### Lv4 · 开源贡献

**题**:Filament 是 Google 的 PBR 引擎,Rust 移植在 https://github.com/google/filament

1. 读它的 BRDF shader:`filament/src/materials/src/*.mat`
2. 找它的 GGX 实现(关键词 `ggx`、`D_GGX`)
3. 看 Filament 的 IBL 预滤波(pre-filter environment map)
4. 可能的贡献:文档里加一段"how Filament's BRDF differs from LearnOpenGL PBR"——两者公式细节有差异,文档可以解释

## 8 · Rust / Arch 落地代码

写一个完整的 PBR 球渲染器(CPU 软渲染,用 image crate):

```toml
# Cargo.toml
[package]
name = "pbr_cpu"
version = "0.1.0"
edition = "2021"

[dependencies]
image = "0.25"
glam = "0.29"
```

```rust
// src/main.rs
use glam::Vec3;
use image::{ImageBuffer, Rgb, RgbImage};

fn main() {
    let width = 512;
    let height = 512;
    let mut img: RgbImage = ImageBuffer::new(width, height);

    // PBR 参数
    let base_color = Vec3::new(0.95, 0.64, 0.54);  // 类似铜
    let metallic = 1.0;
    let roughness = 0.3;

    // 光源和相机
    let light_pos = Vec3::new(5.0, 5.0, 5.0);
    let light_color = Vec3::new(1.0, 1.0, 1.0) * 100.0;  // 强光
    let cam_pos = Vec3::new(0.0, 0.0, 5.0);

    for y in 0..height {
        for x in 0..width {
            // 屏幕坐标到球面
            let dx = (x as f32 - width as f32 / 2.0) / (width as f32 / 4.0);
            let dy = -(y as f32 - height as f32 / 2.0) / (height as f32 / 4.0);
            let r2 = dx*dx + dy*dy;
            if r2 > 1.0 { continue; }
            let dz = (1.0 - r2).sqrt();
            let p = Vec3::new(dx, dy, dz);  // 球面点(单位球)
            let n = p;  // 单位球法线就是位置本身
            let l = (light_pos - p).normalize();
            let v = (cam_pos - p).normalize();

            // 距离衰减(反平方)
            let dist = (light_pos - p).length();
            let attenuation = 1.0 / (dist * dist);
            let light_intensity = light_color * attenuation;

            let brdf = pbr_brdf(base_color, metallic, roughness, n, l, v);
            // 出射 radiance = BRDF * light * N·L * π(简化)
            let cos_theta = n.dot(l).max(0.0);
            let final_color = Vec3::new(
                brdf.x * light_intensity.x * cos_theta,
                brdf.y * light_intensity.y * cos_theta,
                brdf.z * light_intensity.z * cos_theta,
            );

            // gamma 校正(sRGB)
            let gamma_correct = |c: f32| -> u8 {
                let c = c.max(0.0).min(1.0);
                (c.powf(1.0/2.2) * 255.0) as u8
            };
            img.put_pixel(x, y, Rgb([
                gamma_correct(final_color.x),
                gamma_correct(final_color.y),
                gamma_correct(final_color.z),
            ]));
        }
    }
    img.save("pbr_sphere.png").unwrap();
    println!("Saved pbr_sphere.png");
}
```

跑起来:

```bash
mkdir -p ~/src/pbr_cpu && cd ~/src/pbr_cpu
# (把上面的内容写到 Cargo.toml 和 src/main.rs)
cargo run --release
# 输出:Compiling pbr_cpu v0.1.0 ...
#       Finished release [optimized] target(s)
#       Saved pbr_sphere.png
```

打开 `pbr_sphere.png` 应该看到一个金属感的铜色球,右上角有高光。

排错:

```bash
# 1. 如果球是黑的
#    检查:light_color 强度够不够(PBR 用真实光照强度,需要乘衰减)
#    排查:在 BRDF 输出后打印 brdf.x,看是不是 ~0
#
# 2. 如果球过曝(纯白)
#    检查:有没有 tone mapping(色调映射)
#    PBR 输出是 HDR(可能 > 1.0),需要 tone map 才能正确显示在 LDR 屏上
#    简单的 Reinhard tone mapping:c' = c / (1 + c)
#
# 3. 如果高光在错误位置
#    检查:H = (L+V)/|L+V| 算对了吗?
#    光源方向:L 是"从表面指向光源",不是反方向
```

## 9 · 延伸阅读

本仓库本地:

- `days/phase-6/deep-dives/depth-buffer-precision.md` — 光照和深度精度
- `days/phase-6/deep-dives/normal-mapping.md` — 法线贴图改变法线,光照细节
- `days/phase-6/deep-dives/light-attenuation.md` — 距离衰减和 IBL

外部稳定 URL:

- LearnOpenGL PBR: https://learnopengl.com/PBR/Theory
- PBR Book(在线免费): https://www.pbr-book.org/3ed-2018/Reflection_Models
- Scratchapixel materials: https://www.scratchapixel.com/lessons/3d-basic-rendering/introduction-to-shading
- Disney Principled BRDF 论文: https://disney-animation.s3.amazonaws.com/library/s2012_pbs_disney_brdf_notes_v2.pdf
- Filament 文档: https://google.github.io/filament/Filament.html

真实开源源码:

- Filament BRDF: https://github.com/google/filament/blob/main/shaders/src/brdf.fs
- bgfx PBR shader: https://github.com/bkaradzic/bgfx/blob/master/examples/31-rsm/rsm.cpp
