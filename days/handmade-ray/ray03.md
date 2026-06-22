---
episode: 03
series: handmade-ray
title_en: "Materials — Diffuse, Specular, Metal, Glass"
title_zh: "材质系统 — 漫反射、镜面、金属、玻璃"
type: coding
difficulty: 3
duration: "2-3h"
hh_url: "https://guide.handmadehero.org/ray/ray04/"
domains: [graphics, math, rust]
prereqs: ["ray02"]
---

# ray03 · 材质系统:漫反射、镜面、金属、玻璃

> ray02 给物体加了 Phong 光照——但所有物体**用同一种材质**(只在 color / specular_color / shininess 参数上不同)。真实场景里,金属球应该有**金属反射**(反射周围物体),玻璃球应该**透射 + 折射**(看到后面物体的变形)。今天我们抽象出**材质系统**——每种材质有独立的"如何响应入射光线"逻辑,光线追踪时**递归追踪次级光线**(反射、折射)。这一集让你的渲染器从"Phong 模型"升级到"真正的 ray tracing"。

## 0 · 为什么要有这一天

回到 ray02 的画面:球有高光斑,地板有棋盘格,双光源。**但所有物体都是"塑料感"**——光照直接 + 镜面高光,**没有反射、没有透射**。金属球看起来和塑料球一样,玻璃球根本不透光。

真实世界的物体材质差异极大:

- **哑光(泥土、粉笔)**:光均匀散射,无 specular,无反射
- **塑料(光泽)**:有 diffuse + 强 specular,不反射环境
- **金属(铁、铜、铝)**:几乎无 diffuse,**反射环境**(金属面像镜子)
- **镜面(完美镜子)**:100% 反射,无 diffuse
- **玻璃**:透射 + 折射(看到后面物体的变形)
- **水**:类似玻璃,但折射率不同
- **皮肤**:有 subsurface scattering(光从一侧入,另一侧出)

每种材质**对光的响应不同**——这就是 **BRDF(Bidirectional Reflectance Distribution Function)** 描述的:

```
BRDF: f(ω_in, ω_out) -> scalar
```

BRDF 描述"从 ω_in 方向入的光,有多少从 ω_out 方向出"。**Lambert** 是最简单的 BRDF(`f = albedo / π`,常数)。**Phong** 是加 specular 的 BRDF。**金属** 是几乎只有 specular 的 BRDF。**玻璃** 需要扩展到 **BTDF**(Bidirectional Transmittance,透射分布函数)+ BRDF。

光线追踪天然支持**任何材质**——因为光线追踪是**递归**的:光线撞到物体后,根据材质**生成新的光线**(反射、折射、散射),递归追踪。**这就是光线追踪相对光栅化的根本优势**——材质响应自然表达为"发射新光线"。

**材质系统的设计模式**:

```rust
trait Material {
    fn scatter(&self, ray_in: &Ray, hit: &HitRecord) -> Option<ScatterResult>;
}

struct ScatterResult {
    attenuation: Color,    // 光的衰减(被吸收多少)
    scattered: Ray,        // 新生成的光线(反射 / 折射 / 散射)
}
```

每种材质(Lambert / Metal / Dielectric)实现自己的 `scatter`。光线追踪主循环在相交后调用 `material.scatter()`,**递归追踪新光线**。

**递归深度**:每次递归深度 +1,直到达到上限(典型 5-10 层)或新光线衰减到 0。**无限递归会导致栈溢出**,必须有上限。

心理锚点:今天之后,你能:(1) 设计 Rust 的 Material trait;(2) 实现 Lambert、Metal、Dielectric(玻璃)三种材质;(3) 在 ray tracer 里递归追踪次级光线;(4) 解释为什么金属球反射环境、玻璃球折射背景。

## 1 · Casey 今天做了什么(Handmade Ray 脉络)

Casey 在 Handmade Ray ray04(BRDF 数据加载)之前,做了完整的材质系统:

1. **抽象材质**:把 Phong 拆出 `Material` 概念,每种材质决定如何响应入射光。

2. **Lambertian 材质**:ray01-02 的 diffuse 简化版——`scatter` 返回"沿随机半球方向的新光线", attenuation = albedo。**Monte Carlo 思路**——多次采样累积得到光照。

3. **Metal 材质**:`scatter` 返回**反射光线**(`reflect(ray.direction, normal)`),attenuation = metal color。**镜子或金属球**。

4. **Dielectric(玻璃)材质**:用 Snell 定律算**折射光线**,加 Fresnel 方程决定反射 vs 折射的比例。**玻璃球**。

5. **递归 ray_color**:主循环改成"ray → hit → material.scatter → recurse on scattered ray",递归深度上限 5。

到 ray03 结束,场景里可以混合各种材质:哑光球、金属球、玻璃球,**画面看起来像真实物体**。

## 2 · 心智模型

### 类比:材质是"光与物体的对话规则"

想象你(光线)走到不同物体前,**物体按"自己的规则"回应你**:

- **哑光墙**:"你照我,我朝四面八方均匀反弹"(Lambertian)
- **金属**:"你照我,我严格按反射定律反弹,颜色是我自己的颜色"(Metal)
- **玻璃**:"你照我,一部分你反弹回去(反射),一部分我让你穿过(折射),穿过时方向会变"(Dielectric)

每种"回应规则"就是材质。**光线追踪每次相交后,问物体"你如何回应"**,物体用 `scatter(ray_in) -> ray_out` 回答。

**递归**:`ray_out` 继续在场景里传播,撞到下一个物体,继续问"你如何回应"。**这就是光的物理传播**——光在场景里多次反射 / 折射,最终一部分进入相机。

### 严谨原理:BRDF 和材质

#### 2.1 BRDF 数学

**BRDF(Bidirectional Reflectance Distribution Function)**:

```
f_r(ω_in, ω_out) = dL_out(ω_out) / dE_in(ω_in)
```

意思是"从 ω_in 方向进入的辐射照度,在 ω_out 方向产生的辐射度的导数"。简单说:**单位入射光,有多少被反射到出射方向**。

BRDF 的性质:
- **非负**:`f_r ≥ 0`(光不能"负反射")
- **能量守恒**:`∫ f_r(ω_in, ω_out) cos(θ_out) dω_out ≤ 1`(反射不超过入射)
- **可逆**:`f_r(ω_in, ω_out) = f_r(ω_out, ω_in)`(光路可逆)
- **对称**:`f_r` 关于方位角对称(各向同性)

**Lambert BRDF**:`f_r = albedo / π`,常数(所有方向均匀散射)。简单,但能量守恒严格。

**Phong BRDF**:`f_r = albedo / π + ks * (R · V)^n`,加 specular。

**Cook-Torrance BRDF**:`f_r = kD * D * G * F / (4 * (N·L) * (N·V))`,D 是微表面分布,G 是几何遮蔽,F 是菲涅尔。**PBR 标准**。

#### 2.2 Monte Carlo 路径追踪

光线追踪用 BRDF 的方式是 **Monte Carlo 采样**:

```
1. 光线撞到 P,材质 albedo = a, BRDF = f
2. 按 BRDF 分布采样一个出射方向 ω_out(随机)
3. 新光线从 P 沿 ω_out,递归追踪得 color_out
4. attenuation = f(ω_in, ω_out) * cos(θ) / pdf(ω_out)
5. final = attenuation * color_out
6. 重复多次采样,平均(每像素 N 条光线)
```

**为什么 Monte Carlo**?因为完整的渲染方程:`L_out = ∫ f_r * L_in * cos(θ) dω_in`,**没有解析解**(L_in 又是其他物体的 L_out,递归)。Monte Carlo 用随机采样**数值求解**——N 条光线平均,误差按 `1/sqrt(N)` 减小。

**Lambertian Monte Carlo**:

```rust
struct Lambertian { albedo: Color }

impl Material for Lambertian {
    fn scatter(&self, _ray_in: &Ray, hit: &HitRecord) -> Option<ScatterResult> {
        // 在半球内随机方向(单位半球采样)
        let direction = random_in_hemisphere(hit.normal);
        let scattered = Ray { origin: hit.point + hit.normal * 0.001, direction };
        Some(ScatterResult { attenuation: self.albedo, scattered })
    }
}
```

`random_in_hemisphere(normal)` 返回 normal 周围半球内的随机单位向量。多次采样平均 → 收敛到 Lambert 漫反射。

#### 2.3 Metal(完美反射)

```rust
struct Metal { albedo: Color, fuzz: f32 }

impl Material for Metal {
    fn scatter(&self, ray_in: &Ray, hit: &HitRecord) -> Option<ScatterResult> {
        let reflected = reflect(ray_in.direction.normalize(), hit.normal);
        // fuzz > 0 时,反射方向加随机扰动(模拟粗糙金属)
        let direction = if self.fuzz > 0.0 {
            reflected + random_in_unit_sphere() * self.fuzz
        } else {
            reflected
        };
        // 如果反射方向在表面背面(不应该),返回 None(吸收)
        if direction.dot(hit.normal) <= 0.0 {
            return None;
        }
        let scattered = Ray { origin: hit.point + hit.normal * 0.001, direction: direction.normalize() };
        Some(ScatterResult { attenuation: self.albedo, scattered })
    }
}
```

**fuzz**:粗糙度参数,0 = 完美镜面,大 = 哑光金属(像磨砂铝)。

#### 2.4 Dielectric(玻璃、水、透明物体)

**Snell 折射定律**:`n1 sin(θ1) = n2 sin(θ2)`

- n1:入射介质折射率(空气 1.0,水 1.33,玻璃 1.5)
- n2:折射介质折射率
- θ1:入射角(法线和入射方向的夹角)
- θ2:折射角

**Fresnel 方程**:决定**多少光反射、多少折射**。简化版用 **Schlick 近似**:

```
R(θ) = R0 + (1 - R0) * (1 - cos(θ))^5
R0 = ((n1 - n2) / (n1 + n2))^2
```

θ = 0(垂直入射):R = R0(典型玻璃约 4%)
θ = 90(掠射):R = 1(完全反射)

**实现**:

```rust
struct Dielectric { ior: f32 }  // index of refraction(玻璃 1.5)

impl Material for Dielectric {
    fn scatter(&self, ray_in: &Ray, hit: &HitRecord) -> Option<ScatterResult> {
        let attenuation = Color::ONE;  // 玻璃不吸收光
        let unit_direction = ray_in.direction.normalize();
        let cos_theta = (-unit_direction).dot(hit.normal).min(1.0);
        let sin_theta = (1.0 - cos_theta * cos_theta).sqrt();

        // 决定入射方向(进入 vs 离开玻璃)
        let (refraction_ratio, normal) = if cos_theta > 0.0 {
            // 光线在介质内,要出来
            (self.ior, hit.normal)
        } else {
            // 光线在外,要进入
            (1.0 / self.ior, -hit.normal)
        };

        // 检查是否能折射(全反射临界角)
        let cannot_refract = refraction_ratio * sin_theta > 1.0;
        let reflectance = schlick(cos_theta, refraction_ratio);

        let direction = if cannot_refract || reflectance > rand::random() {
            // 反射
            reflect(unit_direction, normal)
        } else {
            // 折射
            refract(unit_direction, normal, refraction_ratio)
        };

        let scattered = Ray { origin: hit.point + direction * 0.001, direction };
        Some(ScatterResult { attenuation, scattered })
    }
}

fn refract(uv: Vec3, n: Vec3, etai_over_etat: f32) -> Vec3 {
    let cos_theta = (-uv).dot(n).min(1.0);
    let r_out_perp = etai_over_etat * (uv + cos_theta * n);
    let r_out_parallel = -((1.0 - r_out_perp.length_squared()).abs().sqrt()) * n;
    r_out_perp + r_out_parallel
}

fn schlick(cosine: f32, ref_idx: f32) -> f32 {
    let r0 = ((1.0 - ref_idx) / (1.0 + ref_idx)).powi(2);
    r0 + (1.0 - r0) * (1.0 - cosine).powi(5)
}
```

**关键细节**:
- `cos_theta > 0` 判断光线在玻璃内 vs 外
- 全反射(`cannot_refract`):光从密介质到疏介质(玻璃到空气),入射角超过临界角,**全部反射**,无折射
- Fresnel 反射概率:`schlick > rand::random()`,Monte Carlo 选择反射或折射

### 递归 ray_color

主循环改成递归:

```rust
fn ray_color(ray: &Ray, scene: &Scene, depth: u32) -> Color {
    if depth == 0 {
        return Color::ZERO;  // 递归上限,黑
    }

    if let Some((hit, obj)) = find_closest_hit(ray, scene) {
        if let Some(scatter) = obj.material.scatter(ray, &hit) {
            // 递归追踪新光线
            return scatter.attenuation * ray_color(&scatter.scattered, scene, depth - 1);
        } else {
            return Color::ZERO;  // 被吸收
        }
    } else {
        // 背景
        let t = 0.5 * (ray.direction.y + 1.0);
        return vec3(0.3, 0.5, 1.0).lerp(vec3(1.0, 1.0, 1.0), t);
    }
}
```

**关键**:
- `depth` 限制递归深度(典型 5-10),防止无限递归
- `attenuation * ray_color(...)` 是颜色累乘——每次反射衰减
- 多次反射后,颜色趋向 0(光被吸收),不再贡献

**为什么 attenuation 用乘法**?物理上,光经过红色物体反射 → 红光;再经过绿色物体反射 → 红光 × 绿光 = 黄光(物理上,如果两物体都全反射的话)。**乘法累乘是 BRDF 能量守恒的表达**。

### 完整材质系统的 Rust 设计

```rust
use std::sync::Arc;

trait Material: Send + Sync {
    fn scatter(&self, ray_in: &Ray, hit: &HitRecord) -> Option<ScatterResult>;
}

struct ScatterResult {
    attenuation: Color,
    scattered: Ray,
}

// 三种基础材质
struct Lambertian { albedo: Color }
struct Metal { albedo: Color, fuzz: f32 }
struct Dielectric { ior: f32 }

impl Material for Lambertian {
    fn scatter(&self, _ray_in: &Ray, hit: &HitRecord) -> Option<ScatterResult> {
        let direction = (hit.normal + random_unit_vector()).normalize();
        let scattered = Ray {
            origin: hit.point + hit.normal * 0.001,
            direction: if direction.length_squared() > 1e-6 { direction } else { hit.normal },
        };
        Some(ScatterResult { attenuation: self.albedo, scattered })
    }
}

// Metal 和 Dielectric 同上

struct Object {
    shape: Shape,
    material: Arc<dyn Material>,
}
```

**`Arc<dyn Material>`** 是因为:
- `dyn Material`:trait object,运行时多态(支持不同材质)
- `Arc`:原子引用计数,多线程共享材质(Scene 在多线程间共享)

### 随机数和半球采样

**半球随机采样**算法:

```rust
use rand::Rng;

fn random_unit_vector() -> Vec3 {
    let mut rng = rand::thread_rng();
    let a: f32 = rng.gen_range(0.0..2.0 * std::f32::consts::PI);
    let z: f32 = rng.gen_range(-1.0..1.0);
    let r = (1.0 - z * z).sqrt();
    Vec3::new(r * a.cos(), r * a.sin(), z)
}

fn random_in_hemisphere(normal: Vec3) -> Vec3 {
    let v = random_unit_vector();
    if v.dot(normal) > 0.0 { v } else { -v }  // 保证在 normal 半球内
}

fn random_in_unit_sphere() -> Vec3 {
    let mut rng = rand::thread_rng();
    loop {
        let p = Vec3::new(
            rng.gen_range(-1.0..1.0),
            rng.gen_range(-1.0..1.0),
            rng.gen_range(-1.0..1.0),
        );
        if p.length_squared() < 1.0 {
            return p;
        }
    }
}
```

**为什么用 `thread_rng`**?`thread_rng` 是线程本地的快速 PRNG(基于 ChaCha8),不用每次分配,适合高频调用(每像素多次)。

**Casey ray02 替换 rand()**:Casey 在 Handmade Ray ray02 专门讲为什么标准 `rand()` 不够好——质量差、慢、跨平台不一致。他用 XorShift 或 PCG(Permuted Congruential Generator)替代。Rust 的 `rand` crate 默认用 ChaCha8,质量够,**生产用 rand 即可**。

## 3 · 四域深入

### 3.1 · 🎮 游戏编程视角

游戏开发里材质的几个层次:

1. **简单参数化材质**(ray03):每个物体 color + shininess + metalness,用 Phong 模型
2. **贴图材质**:albedo texture + normal texture + roughness texture,丰富细节
3. **PBR 材质**(Unreal、Unity):metallic-roughness workflow,完整物理 BRDF
4. **复杂材质**(Disney Principled):20+ 参数,艺术家友好

**PBR 的核心参数**:
- **albedo**:基础颜色
- **metallic**:金属度(0 = 哑光,1 = 金属)
- **roughness**:粗糙度(0 = 镜面,1 = 哑光)
- **normal**:法线贴图(伪造细节)
- **AO**:环境光遮蔽贴图

**PBR vs Phong**:PBR 物理正确(specular 自动随角度变化、能量守恒),Phong 是工程近似(可能违反能量守恒)。但**视觉差别不大,很多人不在意**。**PBR 主要价值在"参数空间一致"**——同一组参数在不同光照下都看起来"对",艺术家更好调。

### 3.2 · 🎨 图形学视角

折射率(IOR)和真实材质:

| 材质 | IOR |
|---|---|
| 真空 | 1.0 |
| 空气(1 atm) | 1.0003 |
| 水 | 1.333 |
| 玻璃(普通) | 1.5 |
| 玻璃(高铅) | 1.7 |
| 钻石 | 2.42 |
| 蓝宝石 | 1.77 |
| 石英 | 1.46 |

**钻石 IOR 高(2.42)**,所以钻石有强烈的折射和全反射,看起来"闪"。**渲染钻石用 Dielectric { ior: 2.42 }**。

**菲涅尔效应**:几乎任何材质在掠射角(接近 90°)都反射增强。**这就是为什么水面在远处看起来反光强**(光以掠射角入射,大部分反射)。**Phong 不模拟菲涅尔**,所以水面看起来"太透明"。**PBR 模拟**(Fresnel-Schlick 近似)。

**色散(dispersion)**:真实玻璃**不同波长折射率略不同**(红光 vs 蓝光),产生彩虹色边。**Phong / Dielectric 单 IOR 不模拟色散**——简单 raytracer 渲染玻璃看不到彩虹边。**PBRT 等科研渲染器支持色散**(用 wavelength 而不是 RGB)。

### 3.3 · 🐧 Linux 系统编程视角

**多线程并行**(ray03 之后开始重要):

```rust
use rayon::prelude::*;

framebuffer
    .par_chunks_mut(width * 3)
    .enumerate()
    .for_each(|(y, row)| {
        let mut rng = rand::thread_rng();
        for x in 0..width {
            let mut color = Color::ZERO;
            for _ in 0..samples {
                let ray = camera.ray_for_pixel(x as u32, y as u32);
                color += ray_color(&ray, &scene, 5);
            }
            // ...
        }
    });
```

**`par_chunks_mut`** 把 framebuffer 按行分块,每块一个线程,**互不干扰**(像素间无共享状态)。

**rayon 的工作窃取(work-stealing)**:每线程有本地队列,空闲线程从其他线程"偷"任务,负载均衡好,**几乎线性加速**(8 核 → 7.5x 加速)。

**SIMD 友好的材质布局**:把相同材质的物体放一起,循环里 match 简单,内层循环 SIMD 化。**异质材质列表**会有 vtable 开销,但通常 10-20%,可接受。

**XorShift 替代 rand**(Casey ray02):

```rust
struct XorShiftRng { state: u64 }

impl XorShiftRng {
    fn new(seed: u64) -> Self { Self { state: seed.max(1) } }
    fn next_u32(&mut self) -> u32 {
        let mut x = self.state;
        x ^= x << 13; x ^= x >> 7; x ^= x << 17;
        self.state = x;
        x as u32
    }
    fn next_f32(&mut self) -> f32 {
        self.next_u32() as f32 / u32::MAX as f32
    }
}
```

**XorShift 优势**:4 条 XOR/shift 指令,**极快**;**线程本地**(每线程一个 state,无锁);**质量足够** Monte Carlo。Casey ray02 用类似实现。

### 3.4 · 🦀 Rust 生态视角

**Material trait 的所有权**:

```rust
trait Material: Send + Sync {
    fn scatter(&self, ray_in: &Ray, hit: &HitRecord) -> Option<ScatterResult>;
}
```

**`Send + Sync`**:Material 需要在线程间共享(Scene 在多线程间),所以加 `Send + Sync`。Material 只读不写,**自然 Sync**。

**`Arc<dyn Material>`**:Arc 是原子引用计数,线程安全的引用计数。`dyn Material` 是 trait object。**多个 Object 共享同一材质**(比如场景里多个红色哑光球),用 Arc 共享。

**替代方案:`Arc<MaterialEnum>`**:

```rust
enum MaterialEnum {
    Lambertian { albedo: Color },
    Metal { albedo: Color, fuzz: f32 },
    Dielectric { ior: f32 },
}
```

**enum 比 trait object 高效**(无 vtable),但**扩展性差**(不能第三方加新材质)。**生产 raytracer 用 enum**,Handmade Ray 教学用 trait。

**Rust 的 trait object 限制**:trait 必须是 **object safe**——不能有泛型方法、不能返回 `Self`、不能 `Sized` 限制。`Material` 满足,可以 trait object。

### 3.5 · 🔢 数学视角

**渲染方程(Rendering Equation,Kajiya 1986)**:

```
L_out(p, ω_out) = L_emit(p, ω_out) + ∫_Ω f_r(p, ω_in, ω_out) * L_in(p, ω_in) * cos(θ_in) dω_in
```

- L_out:点 p 沿 ω_out 方向的辐射度
- L_emit:点 p 自身发光(光源)
- 积分:所有入射方向 ω_in 的贡献累加
- f_r:BRDF
- L_in:从 ω_in 方向来的辐射度(其他物体的 L_out)
- cos(θ):Lambert 余弦定律

**渲染方程是积分方程,L_in 又是其他点的 L_out**——递归,**无解析解**。光线追踪用 Monte Carlo 数值求解。

**Monte Carlo 积分**:

```
∫ f(x) dx ≈ (1/N) Σ f(x_i) / p(x_i)
```

x_i 是按概率密度 p(x) 采样的随机数。N 个采样平均,误差按 `1/sqrt(N)` 减小。

**重要性采样(importance sampling)**:不要均匀采样,按 BRDF 分布**重要性采样**——高概率方向多次采样,低概率方向少采样。**显著减少噪声**(相同采样数下)。

Lambert BRDF 的重要性采样:沿法线方向**余弦加权半球采样**(cosine-weighted hemisphere),PDF = cos(θ) / π。

```rust
fn cosine_weighted_hemisphere(normal: Vec3) -> Vec3 {
    let r1: f32 = rand::random();
    let r2: f32 = rand::random();
    let phi = 2.0 * std::f32::consts::PI * r1;
    let sqrt_r2 = r2.sqrt();
    let x = phi.cos() * 2.0 * sqrt_r2;
    let y = phi.sin() * 2.0 * sqrt_r2;
    let z = (1.0 - r2).abs().sqrt();
    // z 是 normal 方向的分量
    let (u, v) = orthonormal_basis(normal);
    u * x + v * y + normal * z
}
```

**收益**:同样 100 samples/像素,**余弦加权比均匀采样噪声少 2-3 倍**。工业 path tracer 都用。

## 4 · 认知地图

### 4.1 上级

- **渲染方程(Rendering Equation)** — 光照传输的完整数学
- **BRDF / BTDF / BSDF** — 材质响应的数学描述
- **Monte Carlo 方法** — 数值积分,处理高维积分
- **递归光线追踪** — Whitted 风格,递归反射/折射

### 4.2 同级(并行方案)

| 方案 | 关键差别 | 何时用 | 本项目选了哪个 |
|---|---|---|---|
| Phong(直接光照) | 不递归,无反射 | 简单场景 | ray01-02 |
| Whitted ray tracing | 镜面反射 + 折射,递归 | 镜面/玻璃 | ✅ ray03 |
| Path tracing | Monte Carlo GI | 物理正确 GI | ray04 触及 |
| Photon mapping | 光子缓存 | 焦散 | 不用 |
| Bidirectional path tracing | 双向追踪 | 复杂场景(走廊) | 不用 |

### 4.3 下级

- **BRDF / BTDF / Fresnel** — 物理模型
- **Snell 定律** — 折射数学
- **Schlick 近似** — Fresnel 简化
- **递归 ray_color** — 主循环结构
- **Monte Carlo 采样** — 数值方法
- **重要性采样** — 优化技巧
- **Material trait** — Rust 设计

## 5 · 对照与变奏

### Whitted ray tracing vs Path tracing

| | Whitted(1980) | Path tracing(1986) |
|---|---|---|
| 反射 / 折射 | 完美镜面(一条光线) | Monte Carlo 采样(多条光线) |
| 漫反射 | 不递归(用直接光照) | 递归(每条光线反射后继续) |
| GI | 不支持 | 支持(path tracing = GI) |
| 收敛 | 一条光线,无收敛问题 | N 条光线,1/sqrt(N) 收敛 |
| 噪声 | 无(确定性) | 有(N 小时明显) |
| 计算量 | 小 | 大(每像素 N 条) |

**Handmade Ray ray03**:Lambertian 用 Monte Carlo(已经是 path tracing 思路),Metal / Dielectric 用 Whitted(单条反射)。**混合模式**——介于 Whitted 和 path tracing 之间。

### 材质参数对比

| 材质 | albedo | metallic | roughness | IOR |
|---|---|---|---|---|
| 哑光塑料 | 0.8 | 0 | 0.8 | n/a |
| 光泽塑料 | 0.7 | 0 | 0.3 | n/a |
| 镜面塑料 | 0.5 | 0 | 0.05 | n/a |
| 铁 | 0.6 | 1 | 0.5 | n/a |
| 铜 | 0.9, 0.6, 0.4 | 1 | 0.3 | n/a |
| 铝 | 0.9 | 1 | 0.6 | n/a |
| 镜子 | 1.0 | 1 | 0.0 | n/a |
| 玻璃 | 1.0 | 0 | 0.0 | 1.5 |
| 水 | 1.0 | 0 | 0.0 | 1.33 |
| 钻石 | 1.0 | 0 | 0.0 | 2.42 |

### 历史演化

- **1980 Whitted**:递归 ray tracing(反射、折射)
- **1982 Cook**:分布式光线追踪(软阴影、景深)
- **1986 Kajiya**:渲染方程 + path tracing
- **1990s Arvo**:photon mapping
- **1997 Veach**:bidirectional path tracing、MLT
- **2010+ Disney Principled BRDF**(Disney 2012)
- **2015+ Mitsuba 2/3、PBRT-v3**:教育/科研标准
- **2018+ RTX**:GPU path tracing

## 6 · 关联

- **铺垫**:
  - [ray02.md](ray02.md) — 几何 + Phong 光照
  - [../phase-2/day044.md](../phase-2/day044.md) — 反射向量
  - [../phase-0/14-math-foundations.md](../phase-0/14-math-foundations.md) — 数学基础
- **当天**:ray03 — 材质系统
- **后续**:
  - [ray04.md](ray04.md) — 反射、抗锯齿、BRDF 数据
  - 主剧 [../phase-6/day375.md](../phase-6/day375.md) — PBR 入门

## 7 · 变式训练

### Lv1 · 概念辨析

**题**:为什么 Dielectric 材质用 `rand::random() < reflectance` 决定反射 vs 折射?为什么不是直接计算"反射比例 + 折射比例"?

**参考解答**:

物理上,**光在玻璃表面既反射又折射**——一部分光(比例 = reflectance)反射,另一部分(比例 = 1 - reflectance)折射。**总光强 = 反射 + 折射**。

**光线追踪用单条光线模拟光的传播**,不能"分裂"。两种处理方式:

1. **分裂(split)**:每次相交产生两条新光线(反射 + 折射),**指数爆炸**(深度 5 → 32 条光线)。**开销不可接受**。
2. **Monte Carlo 选择**:按 reflectance 概率随机选反射或折射,**单条光线**。多次采样平均 → 收敛到正确比例。

**第二种是工业标准**。N 次采样里,reflectance * N 次反射、(1-reflectance) * N 次折射,**期望值正确**。误差按 `1/sqrt(N)` 减小。

**关键洞察**:光线追踪用 Monte Carlo 把"光的统计行为"用单条光线表示,**降低计算量,但增加噪声**。

### Lv2 · 动手实践

**题**:实现完整 Material trait,场景里有三个球:Lambertian(蓝)、Metal(灰)、Dielectric(玻璃,ior=1.5)。递归深度 5,4 samples/像素。

完成标准:三个球**视觉差异明显**——Lambertian 球哑光蓝,Metal 球反射环境(背景渐变在球上),Dielectric 球透明(看到背景透过球)。

**参考解答**:见 §2 的完整代码。Material trait + Lambertian / Metal / Dielectric 三个实现 + 递归 ray_color。

主函数:

```rust
let scene = Scene {
    objects: vec![
        Object {
            shape: Shape::Sphere { center: vec3(-1.5, 0.0, -5.0), radius: 1.0 },
            material: Arc::new(Lambertian { albedo: vec3(0.2, 0.3, 0.8) }),
        },
        Object {
            shape: Shape::Sphere { center: vec3(0.0, 0.0, -5.0), radius: 1.0 },
            material: Arc::new(Metal { albedo: vec3(0.9, 0.9, 0.9), fuzz: 0.0 }),
        },
        Object {
            shape: Shape::Sphere { center: vec3(1.5, 0.0, -5.0), radius: 1.0 },
            material: Arc::new(Dielectric { ior: 1.5 }),
        },
        Object {
            shape: Shape::Plane { point: vec3(0.0, -1.0, 0.0), normal: vec3(0.0, 1.0, 0.0) },
            material: Arc::new(Lambertian { albedo: vec3(0.5, 0.5, 0.5) }),
        },
    ],
};
```

### Lv3 · 迁移设计

**题**:你被要求做**金属漆(car paint)材质**——基底是哑光颜色 + 上层是高光泽 clearcoat。如何用现有 Lambertian / Metal 组合实现?

**提示**:
- 真实汽车漆是两层:基底哑光(颜色)+ 顶层透明光泽
- raytracer 里可以用一个材质**按概率选** Lambert 或 Metal(混合材质)
- 类似 Dielectric 的反射 / 折射选择

### Lv4 · 开源贡献

**题**:`rend3` 是 Rust 的现代 PBR 渲染器,GitHub: https://github.com/BVE-Reborn/rend3

1. clone 仓库,看它的 Material 系统
2. 找 PBR material 实现
3. **可能的贡献方向**:
   - doc 改进
   - 加 IBL(Image-Based Lighting)支持
   - 加新材质(比如 Disney Principled)
4. 写 PR 描述

## 8 · Rust / Arch 落地代码

### 完整 ray03 代码

```rust
// Cargo.toml:
// [dependencies]
// glam = "0.29"
// image = "0.25"
// indicatif = "0.17"
// rand = "0.8"
// rayon = "1.10"

use glam::{Vec3, vec3};
use indicatif::{ProgressBar, ProgressStyle};
use rand::Rng;
use rayon::prelude::*;
use std::sync::Arc;

type Color = Vec3;

#[derive(Copy, Clone, Debug)]
struct Ray { origin: Vec3, direction: Vec3 }

impl Ray {
    fn at(&self, t: f32) -> Vec3 { self.origin + self.direction * t }
}

#[derive(Clone, Debug)]
struct HitRecord { t: f32, point: Vec3, normal: Vec3, material: Arc<dyn Material> }

trait Material: Send + Sync {
    fn scatter(&self, ray_in: &Ray, hit: &HitRecord) -> Option<(Color, Ray)>;
}

#[derive(Clone)]
enum Shape {
    Sphere { center: Vec3, radius: f32 },
    Plane { point: Vec3, normal: Vec3 },
}

struct Object {
    shape: Shape,
    material: Arc<dyn Material>,
}

impl Shape {
    fn intersect(&self, ray: &Ray, material: &Arc<dyn Material>) -> Option<HitRecord> {
        match self {
            Shape::Sphere { center, radius } => {
                let oc = ray.origin - *center;
                let half_b = oc.dot(ray.direction);
                let c = oc.dot(oc) - radius * radius;
                let disc = half_b * half_b - c;
                if disc < 0.0 { return None; }
                let sqrt_d = disc.sqrt();
                let t = if -half_b - sqrt_d > 0.001 { -half_b - sqrt_d }
                        else if -half_b + sqrt_d > 0.001 { -half_b + sqrt_d }
                        else { return None; };
                let p = ray.at(t);
                let n = (p - *center).normalize();
                Some(HitRecord { t, point: p, normal: n, material: material.clone() })
            }
            Shape::Plane { point, normal } => {
                let denom = ray.direction.dot(*normal);
                if denom.abs() < 1e-6 { return None; }
                let t = (*point - ray.origin).dot(*normal) / denom;
                if t > 0.001 {
                    let p = ray.at(t);
                    let n = if denom < 0.0 { *normal } else { -*normal };
                    Some(HitRecord { t, point: p, normal: n, material: material.clone() })
                } else { None }
            }
        }
    }
}

struct Scene { objects: Vec<Object> }

impl Scene {
    fn hit(&self, ray: &Ray) -> Option<HitRecord> {
        let mut closest: Option<HitRecord> = None;
        for obj in &self.objects {
            if let Some(hit) = obj.shape.intersect(ray, &obj.material) {
                if closest.is_none() || hit.t < closest.as_ref().unwrap().t {
                    closest = Some(hit);
                }
            }
        }
        closest
    }
}

// 材质实现
struct Lambertian { albedo: Color }
impl Material for Lambertian {
    fn scatter(&self, _ray_in: &Ray, hit: &HitRecord) -> Option<(Color, Ray)> {
        let mut rng = rand::thread_rng();
        let r1: f32 = rng.gen_range(0.0..2.0 * std::f32::consts::PI);
        let r2: f32 = rng.gen();
        let sqrt_r2 = r2.sqrt();
        let x = r1.cos() * 2.0 * sqrt_r2;
        let y = r1.sin() * 2.0 * sqrt_r2;
        let z = (1.0 - r2).abs().sqrt();
        // 简化:把 (x, y, z) 视为 normal 周围半球内随机方向
        let direction = (hit.normal * z + Vec3::new(x, y, 0.0)).normalize();
        let direction = if direction.dot(hit.normal) > 0.0 { direction } else { -direction };
        let scattered = Ray {
            origin: hit.point + hit.normal * 0.001,
            direction,
        };
        Some((self.albedo, scattered))
    }
}

struct Metal { albedo: Color, fuzz: f32 }
impl Material for Metal {
    fn scatter(&self, ray_in: &Ray, hit: &HitRecord) -> Option<(Color, Ray)> {
        let reflected = reflect(ray_in.direction.normalize(), hit.normal);
        let mut rng = rand::thread_rng();
        let fuzz_dir = if self.fuzz > 0.0 {
            let r1: f32 = rng.gen_range(0.0..2.0 * std::f32::consts::PI);
            let r2: f32 = rng.gen();
            let r = self.fuzz * r2.sqrt();
            Vec3::new(r * r1.cos(), r * r1.sin(), 0.0)
        } else {
            Vec3::ZERO
        };
        let direction = (reflected + fuzz_dir).normalize();
        if direction.dot(hit.normal) <= 0.0 {
            return None;
        }
        Some((self.albedo, Ray { origin: hit.point + hit.normal * 0.001, direction }))
    }
}

struct Dielectric { ior: f32 }
impl Material for Dielectric {
    fn scatter(&self, ray_in: &Ray, hit: &HitRecord) -> Option<(Color, Ray)> {
        let mut rng = rand::thread_rng();
        let unit_dir = ray_in.direction.normalize();
        let cos_theta = (-unit_dir).dot(hit.normal).min(1.0);
        let sin_theta = (1.0 - cos_theta * cos_theta).sqrt();
        let (ratio, normal) = if cos_theta > 0.0 {
            (self.ior, hit.normal)
        } else {
            (1.0 / self.ior, -hit.normal)
        };
        let cannot_refract = ratio * sin_theta > 1.0;
        let reflectance = schlick(cos_theta, ratio);
        let direction = if cannot_refract || reflectance > rng.gen::<f32>() {
            reflect(unit_dir, normal)
        } else {
            refract(unit_dir, normal, ratio)
        };
        Some((Color::ONE, Ray { origin: hit.point + direction * 0.001, direction }))
    }
}

fn reflect(l: Vec3, n: Vec3) -> Vec3 { l - 2.0 * l.dot(n) * n }

fn refract(uv: Vec3, n: Vec3, etai_over_etat: f32) -> Vec3 {
    let cos_theta = (-uv).dot(n).min(1.0);
    let r_out_perp = etai_over_etat * (uv + cos_theta * n);
    let r_out_parallel = -((1.0 - r_out_perp.length_squared()).abs().sqrt()) * n;
    r_out_perp + r_out_parallel
}

fn schlick(cosine: f32, ref_idx: f32) -> f32 {
    let r0 = ((1.0 - ref_idx) / (1.0 + ref_idx)).powi(2);
    r0 + (1.0 - r0) * (1.0 - cosine).powi(5)
}

// 递归 ray_color
fn ray_color(ray: &Ray, scene: &Scene, depth: u32) -> Color {
    if depth == 0 { return Color::ZERO; }
    if let Some(hit) = scene.hit(ray) {
        if let Some((attenuation, scattered)) = hit.material.scatter(ray, &hit) {
            return attenuation * ray_color(&scattered, scene, depth - 1);
        }
        return Color::ZERO;
    }
    let t = 0.5 * (ray.direction.y + 1.0);
    vec3(0.3, 0.5, 1.0).lerp(vec3(1.0, 1.0, 1.0), t)
}

struct Camera {
    look_from: Vec3, forward: Vec3, right: Vec3, up: Vec3,
    half_width: f32, half_height: f32, width: u32, height: u32,
}

impl Camera {
    fn new(look_from: Vec3, look_at: Vec3, vup: Vec3, fov_deg: f32, width: u32, height: u32) -> Self {
        let forward = (look_at - look_from).normalize();
        let right = forward.cross(vup).normalize();
        let up = right.cross(forward);
        let aspect = width as f32 / height as f32;
        let half_height = (fov_deg.to_radians() / 2.0).tan();
        let half_width = half_height * aspect;
        Self { look_from, forward, right, up, half_width, half_height, width, height }
    }
    fn ray_for(&self, x: f32, y: f32) -> Ray {
        let u = (2.0 * x / self.width as f32 - 1.0) * self.half_width;
        let v = (1.0 - 2.0 * y / self.height as f32) * self.half_height;
        Ray {
            origin: self.look_from,
            direction: (self.forward + self.right * u + self.up * v).normalize(),
        }
    }
}

fn render(scene: &Scene, camera: &Camera, samples: u32, max_depth: u32) -> Vec<u8> {
    let sqrt_spp = (samples as f32).sqrt() as u32;
    let progress = ProgressBar::new((camera.width * camera.height) as u64);
    let width = camera.width;

    let fb: Vec<u8> = (0..camera.height)
        .into_par_iter()
        .flat_map(|y| {
            let mut row = vec![0u8; (width * 3) as usize];
            for x in 0..width {
                let mut color_sum = Color::ZERO;
                for sy in 0..sqrt_spp {
                    for sx in 0..sqrt_spp {
                        let sub_x = x as f32 + (sx as f32 + 0.5) / sqrt_spp as f32;
                        let sub_y = y as f32 + (sy as f32 + 0.5) / sqrt_spp as f32;
                        let ray = camera.ray_for(sub_x, sub_y);
                        color_sum += ray_color(&ray, scene, max_depth);
                    }
                }
                let color = color_sum / (sqrt_spp * sqrt_spp) as f32;
                let i = (x * 3) as usize;
                row[i] = (color.x.clamp(0.0, 1.0) * 255.0) as u8;
                row[i+1] = (color.y.clamp(0.0, 1.0) * 255.0) as u8;
                row[i+2] = (color.z.clamp(0.0, 1.0) * 255.0) as u8;
            }
            progress.inc(width as u64);
            row
        })
        .collect();
    progress.finish();
    fb
}

fn main() {
    let scene = Scene {
        objects: vec![
            Object {
                shape: Shape::Sphere { center: vec3(-1.5, 0.0, -5.0), radius: 1.0 },
                material: Arc::new(Lambertian { albedo: vec3(0.2, 0.3, 0.8) }),
            },
            Object {
                shape: Shape::Sphere { center: vec3(0.0, 0.0, -5.0), radius: 1.0 },
                material: Arc::new(Metal { albedo: vec3(0.9, 0.9, 0.9), fuzz: 0.0 }),
            },
            Object {
                shape: Shape::Sphere { center: vec3(1.5, 0.0, -5.0), radius: 1.0 },
                material: Arc::new(Dielectric { ior: 1.5 }),
            },
            Object {
                shape: Shape::Plane { point: vec3(0.0, -1.0, 0.0), normal: vec3(0.0, 1.0, 0.0) },
                material: Arc::new(Lambertian { albedo: vec3(0.5, 0.5, 0.5) }),
            },
        ],
    };
    let camera = Camera::new(
        vec3(0.0, 1.0, 0.0), vec3(0.0, 0.0, -5.0), vec3(0.0, 1.0, 0.0), 60.0, 800, 600
    );

    let fb = render(&scene, &camera, 4, 5);
    image::save_buffer("output.png", &fb, 800, 600, image::ExtendedColorType::Rgb8).unwrap();
}
```

### Arch Linux 命令

```bash
# 1. 加依赖
cat >> Cargo.toml << 'EOF'
rand = "0.8"
rayon = "1.10"
EOF

# 2. 编译运行
cargo run --release
# 三个球:哑光蓝、金属银、玻璃透明

# 3. 多线程加速对比(改 rayon 的 for_each vs iter)
# rayon 应该 8 核 → 7x 加速

# 4. 看 CPU 利用率
sudo pacman -S htop
htop
# 跑 raytracer 时所有核应该打满

# 5. flamegraph(看 ray_color / Material::scatter 占比)
cargo flamegraph --bin handmade-ray --release

# 6. 验证反射方向正确性(单测)
cargo test reflect

# 7. 验证 Schlick 近似
# F(0°) = R0, F(90°) = 1
# Rust 单测:
# assert!((schlick(0.0, 1.5) - ((1.0-1.5)/(1.0+1.5)).powi(2)).abs() < 1e-6);
# assert!((schlick(1.0, 1.5) - 1.0).abs() < 1e-6);
```

**Troubleshooting**:

- 玻璃球全黑:Dielectric 实现里 `cos_theta > 0` 判断错,可能进入了死循环或全部吸收。检查 normal 方向。
- 金属球没反射:Metal 的 fuzz 太大,反射方向跑进表面里,被 reject。改 fuzz = 0。
- 噪声大:samples 不够,加到 16 或 64。
- 性能慢:max_depth 太大,降到 3;或 samples 太多。
- 颜色饱和:递归衰减不够,加 max_depth 限制。

## 9 · 延伸阅读(可选补充,非必需)

本仓库本地:
- [ray02.md](ray02.md) — 几何 + Phong
- [ray04.md](ray04.md) — 反射、抗锯齿、BRDF
- [../phase-2/day044.md](../phase-2/day044.md) — 反射向量

外部稳定 URL(可选):
- Ray Tracing in One Weekend 第 7-10 章(Materials): https://raytracing.github.io/books/RayTracingInOneWeekend.html
- Scratchapixel Materials: https://www.scratchapixel.com/lessons/3d-basic-rendering/introduction-to-shading
- PBBR-Book Chapter 5-8: https://www.pbr-book.org/3ed-2018/Reflection_Models
- Snell's Law(Wikipedia): https://en.wikipedia.org/wiki/Snell%27s_law

真实开源源码:
- Rust path tracer smallpt: https://github.com/cebtenzzre/smallpt-rs
- Casey Handmade Ray ray04 BRDF: https://guide.handmadehero.org/ray/ray04/
