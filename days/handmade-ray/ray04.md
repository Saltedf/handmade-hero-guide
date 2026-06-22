---
episode: 04
series: handmade-ray
title_en: "Reflections, Recursion Depth, and Antialiasing"
title_zh: "反射、递归深度与抗锯齿"
type: coding
difficulty: 4
duration: "2-3h"
hh_url: "https://guide.handmadehero.org/ray/ray04/"
domains: [graphics, math, rust]
prereqs: ["ray03"]
---

# ray04 · 反射、递归深度与抗锯齿

> ray03 让你的 ray tracer 支持 Lambertian、Metal、Dielectric 材质,递归追踪反射 / 折射光线。但**画面有几个问题**:(1) 递归深度太浅时,玻璃球内部和金属球面反射的"层层镜像"看不到;(2) 递归太深时,性能爆炸;(3) 边缘锯齿明显;(4) 阴影是硬边,不像真实柔和阴影。今天我们解决这些——**深度反思、抗锯齿、软阴影、BRDF 数据加载**。这是 Handmade Ray 系列的收官,也是从"教学 ray tracer"升级到"工业 path tracer"前的最后一步。

## 0 · 为什么要有这一天

回到 ray03 的画面:三个球——哑光蓝、金属银、玻璃透明——在地板上,有阴影。**但还有问题**:

**问题 1:递归深度不够,反射层次缺失**。ray03 设 `max_depth = 5`,意思是光线最多反射 5 次就停。但真实场景里,**两面镜子对着放**会产生"无限镜像"——第一层、第二层、第三层……看到无穷远的镜像。5 次反射只能看到 5 层,后面被截断。**截断的视觉表现**是镜像深处变黑(因为递归深度到 0 返回黑色)。**解决**:增加深度,或者**用更聪明的方法**(importance / Russian Roulette)。

**问题 2:递归深度的性能爆炸**。每加一层深度,光线数量可能翻倍(分裂反射 + 折射)。深度 5 → 32 条,深度 10 → 1024 条。**Monte Carlo + path tracing** 用单条光线(Monte Carlo 选反射或折射),不会爆炸。**但 Monte Carlo 有噪声**——像素颜色随采样数收敛。**解决**:增加 samples + 加 importance sampling。

**问题 3:锯齿(aliasing)**。每像素一条光线,物体边缘有阶梯状锯齿。**SSAA**(ray01 提到)直接多次采样,但开销大。**MSAA**(光栅化用)只对边缘多次采样,但光线追踪没有"边缘像素"概念。**解决**:在 path tracing 里,**每像素多条光线本身就是抗锯齿**——只要采样数够,锯齿自动消失(分布式光线追踪)。

**问题 4:硬阴影**。ray03 阴影射线只发一条,光源是**点光源**,阴影是**硬边**(完全黑或完全亮)。**真实光源有面积**(灯泡是个球,不是点),阴影应该**柔和**(本影 → 半影渐变)。**解决**:**面积光 + 多阴影射线**,每条射线采样光源上不同位置,平均得到软阴影。

**问题 5:材质参数不真实**。Phong / Metal 的 specular 是工程近似,不是物理测量。**真实材质**(金属、塑料、织物)的 BRDF 需要实验测量,**MERL BRDF Database** 提供 100 种材质的测量数据。**加载测量 BRDF** 让材质更真实。**这是 Casey Handmade Ray ray04 的核心**——加载 MERL 数据。

今天我们做这些:

1. **Russian Roulette** 代替 max_depth:用概率终止递归,避免硬截断
2. **Importance Sampling** 减少噪声:按 BRDF 分布采样
3. **分布式光线追踪**:用 Monte Carlo 实现软阴影、运动模糊、景深
4. **MERL BRDF 加载**(对应 Casey ray04)
5. **Tone Mapping**:HDR 颜色映射到 LDR(显示)

心理锚点:今天之后,你能:(1) 解释 Russian Roulette 如何避免硬截断;(2) 实现软阴影(面积光 + 多采样);(3) 实现 importance sampling;(4) 加载 MERL BRDF 数据,让材质真实;(5) 用 Reinhard tone mapping 让画面色彩合理。

## 1 · Casey 今天做了什么(Handmade Ray 脉络)

Casey 在 Handmade Ray ray04 做的:

1. **加载 MERL BRDF 数据**:MERL 提供 100 种材质的测量 BRDF,每个材质是 90 × 90 × 180 的 3D 数组(θ_h, θ_d, φ_d 三个参数化)。Casey 写了 Rust 代码加载二进制数据,在 shader 里采样。

2. **替代解析 BRDF**:之前 Metal / Dielectric 用解析公式(reflect + cos 公式),ray04 用**测量的 BRDF 查表**。物理更真实,但**采样开销大**(三线性插值 + Monte Carlo)。

3. **重要性采样**:针对测量 BRDF 的 PDF(importance function),Monte Carlo 采样更高效。

4. **Russian Roulette**:深度大于阈值后,按 1/N 概率继续递归,**避免硬截断**。期望值不变,但避免深度爆炸。

到 ray04 结束,Casey 有了一个**接近工业级的 path tracer**:支持测量 BRDF、importance sampling、Russian Roulette。这个 raytracer 不是实时(1080p 渲染要几秒到几分钟),但**视觉接近物理真实**。

## 2 · 心智模型

### 类比:Path Tracing 是"光的民意调查"

想象你想知道"市民平均通勤时间"。**两种思路**:

**思路 A(穷举)**:问全市每一个人。准确,但**不可能实现**(几百万市民)。

**思路 B(民意调查)**:随机选 1000 人,问他们的通勤时间,平均。**统计上接近真实平均值**,误差可控(中心极限定理)。

Path Tracing 是**思路 B**:每像素**随机采样**光路(从相机出发,递归反射),累加颜色平均。**采样数越多越接近真实**,但**永远有噪声**(1/sqrt(N) 减少)。

**深度问题**:光可能无限反射(两面镜子),你**不能真无限追踪**。**Russian Roulette** 是"按概率决定是否继续追踪"——大部分光线早期终止,少数继续深入,**期望值正确**。**这是民意调查里的"按地区加权"思路**——不是简单截断,而是统计上等价。

### 严谨原理

#### 2.1 Russian Roulette

**问题**:递归深度上限 N 会"硬截断"——N 层后的反射完全丢失,画面有"黑洞"。

**解决**:不用固定上限,用**概率**决定是否继续递归。

```rust
fn ray_color(ray: &Ray, scene: &Scene, depth: u32) -> Color {
    // 基本上限(防止栈溢出)
    if depth >= 100 { return Color::ZERO; }

    if let Some(hit) = scene.hit(ray) {
        if let Some((attenuation, scattered)) = hit.material.scatter(ray, &hit) {
            // Russian Roulette:深度 > 5 后,按概率继续
            if depth > 5 {
                let continue_probability = 0.5;  // 50% 概率继续
                if rand::random::<f32>() > continue_probability {
                    return Color::ZERO;  // 终止
                }
                // 补偿:继续的部分除以 continue_probability,期望值不变
                return attenuation * ray_color(&scattered, scene, depth + 1) / continue_probability;
            }
            return attenuation * ray_color(&scattered, scene, depth + 1);
        }
        return Color::ZERO;
    }
    background(ray)
}
```

**关键**:
- `continue_probability = 0.5`,一半光线终止,一半继续
- 继续的部分**除以概率**补偿——期望值等于不截断的情况
- **平均 2 倍加速**(一半光线提前终止),**视觉结果不变**(统计上等价)

**数学证明**(简化):设原递归结果是 `E`,Russian Roulette 后期望:

```
E[RR] = (1 - p) * 0 + p * (E / p) = E
```

期望不变。**方差增加**(更多波动),但 N 个采样平均后方差按 `1/N` 减小。

#### 2.2 Importance Sampling

**问题**:Monte Carlo 用均匀采样,效率低——大部分采样方向对最终颜色贡献小。

**解决**:按 BRDF 分布**重要性采样**——高贡献方向多次采样,低贡献方向少采样。

**Lambert 的重要性采样**:**余弦加权半球采样**——cos(θ) 大的方向(法线方向)多采样,cos(θ) 小的方向(掠射)少采样。

```rust
fn cosine_weighted_sample(normal: Vec3) -> Vec3 {
    let r1: f32 = rand::random();
    let r2: f32 = rand::random();
    let phi = 2.0 * std::f32::consts::PI * r1;
    let cos_theta = (1.0 - r2).sqrt();
    let sin_theta = (1.0 - cos_theta * cos_theta).sqrt();
    let local = Vec3::new(
        sin_theta * phi.cos(),
        sin_theta * phi.sin(),
        cos_theta,  // z 轴朝法线方向
    );
    // 从局部坐标系转到世界坐标系(normal 是 z 轴)
    let (tangent, bitangent) = orthonormal_basis(normal);
    tangent * local.x + bitangent * local.y + normal * local.z
}

fn orthonormal_basis(n: Vec3) -> (Vec3, Vec3) {
    let a = if n.x.abs() > 0.9 { Vec3::new(0.0, 1.0, 0.0) } else { Vec3::new(1.0, 0.0, 0.0) };
    let t = n.cross(a).normalize();
    let b = n.cross(t);
    (t, b)
}
```

**为什么是 `cos_theta = (1 - r2).sqrt()`**?这是**逆变换采样(inverse transform sampling)**——按 PDF `p(θ) = cos(θ)` 反推采样位置。具体推导:

```
PDF: p(θ) = cos(θ)
CDF: P(θ) = ∫₀^θ cos(t) sin(t) dt = sin²(θ) / 2  (用 sin(t) dt = -d(cos(t)))
Inverse: sin(θ) = sqrt(2 * r),cos(θ) = sqrt(1 - 2 * r) = sqrt(1 - r')
```

实现细节略,**关键是按 BRDF 分布采样**。

**Metal 的重要性采样**:按**反射方向周围的 GGX 分布**采样(微表面 BRDF)。复杂,**ray04 不深入,留给 path tracing 课程**。

#### 2.3 分布式光线追踪(Distributed Ray Tracing)

Cook 1984 提出。**核心思想**:把多个"反锯齿 + 软阴影 + 景深 + 运动模糊"需求统一到**Monte Carlo 采样**框架。

**抗锯齿**:每像素 N 条光线,亚像素位置**随机**(不是 2x2 网格)。
**软阴影**:每交点 N 条阴影射线,光源位置**随机采样**(面积光)。
**景深**:每像素 N 条光线,光圈位置**随机采样**(薄透镜相机)。
**运动模糊**:每像素 N 条光线,时间**随机采样**(物体运动)。

**统一的 N 次采样**同时解决所有问题,**避免每种效果单独处理**。这就是 path tracing 的优雅之处。

**软阴影**(分布式版):

```rust
struct AreaLight {
    center: Vec3,
    radius: f32,    // 光源半径
    color: Color,
}

impl AreaLight {
    fn random_point(&self) -> Vec3 {
        let r1: f32 = rand::random();
        let r2: f32 = rand::random();
        let phi = 2.0 * std::f32::consts::PI * r1;
        let r = self.radius * r2.sqrt();  // 均匀采样圆盘
        // 假设光源在 XZ 平面
        self.center + Vec3::new(r * phi.cos(), 0.0, r * phi.sin())
    }
}

fn shadow_factor(point: Vec3, light: &AreaLight, scene: &Scene) -> f32 {
    let mut visible = 0;
    let total = 16;
    for _ in 0..total {
        let light_point = light.random_point();
        if !in_shadow(point, light_point, scene) {
            visible += 1;
        }
    }
    visible as f32 / total as f32
}
```

**关键**:`visible / total` 是 0-1 之间,模拟**半影**——部分被遮挡的位置,光只到达一部分,**阴影柔和**。

#### 2.4 Tone Mapping(色调映射)

Path tracing 算出的颜色是**HDR(High Dynamic Range)**——超过 1.0 的浮点值,真实世界的光照强度差异巨大(阳光下 100000 lux,月光下 0.1 lux)。

**显示设备只能显示 [0, 1](LDR,Low Dynamic Range)**——8-bit per channel,255 是最亮。直接 clamp 会**烧毁高光**(亮的物体变成纯白一片)。

**Tone mapping**:把 HDR 映射到 LDR,**保留细节**。常用算法:

**Reinhard**:`final = color / (color + 1.0)`

简单,所有值映射到 [0, 1),1.0 映射到 0.5,100 映射到 0.99。**保留高光细节**。

**ACES**(电影工业标准):

```rust
fn aces_tonemap(x: Vec3) -> Vec3 {
    let a = 2.51; let b = 0.03; let c = 2.43; let d = 0.59; let e = 0.14;
    ((x * (a * x + b)) / (x * (c * x + d) + e)).clamp(Vec3::ZERO, Vec3::ONE)
}
```

更**对比度高、电影感强**,Unreal、Unity 默认用 ACES。

**Gamma 校正**:做完 tone mapping,从**线性空间**转到 sRGB:

```rust
fn gamma_correct(c: f32) -> f32 {
    if c <= 0.0031308 {
        12.92 * c
    } else {
        1.055 * c.powf(1.0 / 2.4) - 0.055
    }
}
```

**注意**:Casey 在主剧 day083+ 详细讲色彩空间。ray04 这里简化处理。

#### 2.5 MERL BRDF 加载(Casey ray04 核心)

MERL BRDF Database 提供 **100 种测量 BRDF**,每种是 90 × 90 × 180 的 3D 数组,**Rusinkiewicz 参数化**(θ_h, θ_d, φ_d):

- θ_h:half vector 和 normal 的夹角
- θ_d:diffuse vector 和 half 的夹角
- φ_d:diffuse vector 的方位角

**文件格式**:34.2 MB 二进制文件,头是 3 个 int(90, 90, 180),后面是 90×90×180×3 个 float(RGB)。

**加载代码**(简版):

```rust
use std::fs::File;
use std::io::Read;

struct MerlBrdf {
    data: Vec<f32>,  // 长度 90*90*180*3
}

impl MerlBrdf {
    fn load(path: &str) -> std::io::Result<Self> {
        let mut file = File::open(path)?;
        let mut header = [0u8; 12];
        file.read_exact(&mut header)?;
        let n_theta_h = i32::from_le_bytes(header[0..4].try_into().unwrap());
        let n_theta_d = i32::from_le_bytes(header[4..8].try_into().unwrap());
        let n_phi_d = i32::from_le_bytes(header[8..12].try_into().unwrap());
        assert_eq!(n_theta_h * n_theta_d * n_phi_d, 90 * 90 * 180 / 2);  // phi_d 对称,只存一半

        let mut raw = vec![0u8; (90 * 90 * 180 * 3 * 4) as usize];
        file.read_exact(&mut raw)?;
        let data: Vec<f32> = raw
            .chunks_exact(4)
            .map(|c| f32::from_le_bytes(c.try_into().unwrap()))
            .collect();
        Ok(Self { data })
    }

    fn sample(&self, theta_h: f32, theta_d: f32, phi_d: f32) -> Color {
        // 三线性插值
        let ih = (theta_h / (std::f32::consts::PI / 2.0) * 89.0) as usize;
        let id = (theta_d / (std::f32::consts::PI / 2.0) * 89.0) as usize;
        let ip = (phi_d / std::f32::consts::PI * 179.0) as usize;
        let idx = (ih * 90 + id) * 180 + ip;
        let r = self.data[idx * 3];
        let g = self.data[idx * 3 + 1];
        let b = self.data[idx * 3 + 2];
        Color::new(r, g, b)
    }
}
```

**真实材质**:Casey 用 MERL 数据让金属、塑料看起来像真实测量结果,**比解析 BRDF 真实**。

### Path tracing 完整主循环

```rust
fn ray_color(ray: &Ray, scene: &Scene, depth: u32) -> Color {
    if depth >= 100 { return Color::ZERO; }

    if let Some(hit) = scene.hit(ray) {
        // 直接光照(从光源采样)
        let direct_light = compute_direct_light(&hit, scene);

        // 间接光照(递归)
        let indirect = if let Some((attenuation, scattered)) = hit.material.scatter(ray, &hit) {
            // Russian Roulette
            if depth > 5 {
                let p = 0.5;
                if rand::random::<f32>() > p {
                    Color::ZERO
                } else {
                    attenuation * ray_color(&scattered, scene, depth + 1) / p
                }
            } else {
                attenuation * ray_color(&scattered, scene, depth + 1)
            }
        } else {
            Color::ZERO
        };

        direct_light + indirect
    } else {
        background(ray)
    }
}
```

**关键**:
- 直接光照(从 hit 点向光源发射阴影射线)和间接光照(递归)分离
- Russian Roulette 控制递归深度
- 累加得最终颜色

## 3 · 四域深入

### 3.1 · 🎮 游戏编程视角

**RTX 时代的 path tracing**:2018 RTX 后,游戏开始用 path tracing。Cyberpunk 2077 在 2023 年的"路径追踪覆盖"(PT Override)是工业级实时 path tracing。

**关键优化**:
- **ReSTIR**(Resampled Importance Sampling,2020 NVIDIA):智能采样缓存,显著降低噪声
- **ReBLX / SVGF**:时空降噪滤波,把噪声 sample 平滑成干净画面
- **DLSS**(Deep Learning Super Sampling):AI 超分,1080p 渲染 4K 输出

**Handmade Ray ray04 vs 现代 RTX**:

| | Handmade Ray(2015) | RTX(2023+) |
|---|---|---|
| 平台 | CPU 单线程 → 多线程 → SIMD | GPU RT cores |
| samples/pixel | 16-256 | 1-4 base + denoiser |
| 性能(1080p) | 几秒到几分钟 | 几十毫秒 |
| 噪声 | 取决于 samples | 降噪后无 |
| GI | 完整 path tracing | 完整 path tracing |
| 现代效果 | 支持软阴影 / 景深 | 加运动模糊 / 焦散 |

**学 Handmade Ray 让你看 RTX 不再是黑盒**——核心算法(path tracing + Russian Roulette + importance sampling)是 1980-1990 年代学术成果,**RTX 只是把它们硬件加速**。

### 3.2 · 🎨 图形学视角

**Path Tracing 的数学**(Kajiya 1986):

渲染方程:

```
L(p, ω) = L_e(p, ω) + ∫ f_r(p, ω_i, ω) L_i(p, ω_i) cos(θ_i) dω_i
```

Path Tracing 把这个积分用 Monte Carlo 求解:

```
L(p, ω) ≈ L_e(p, ω) + (1/N) Σ [f_r(p, ω_i, ω) L_i(p, ω_i) cos(θ_i) / pdf(ω_i)]
```

N 个随机方向 ω_i(按 pdf 分布采样),平均得 L(p, ω) 的无偏估计。

**Next Event Estimation**(NEE):不依赖递归遇到光源,**主动从 hit 点向光源发射阴影射线**:

```rust
let direct_light = sample_light(hit, scene);  // 直接光照
let indirect = ray_color(scatter_ray, depth + 1);  // 间接
return attenuation * (direct_light + indirect);
```

NEE 显著降低噪声(直接光照是主要光照来源)。

**Bidirectional Path Tracing**(BDPT):从相机和**光源**两端发射光线,在中间连接,**显著降低复杂场景噪声**(走廊、密室)。Lafortune 1993, Veach 1997。

**Metropolis Light Transport**(MLT):用 Metropolis-Hastings 算法,**根据已有光路探索附近光路**。Veach 1997,适合极复杂场景。

### 3.3 · 🐧 Linux 系统编程视角

**性能瓶颈分析**(path tracing):

```bash
# flamegraph
cargo flamegraph --bin handmade-ray --release
# 80% 时间在 ray_color / Material::scatter / Scene::hit
# 重点优化这三个函数

# Cache 分析
perf stat -e cache-misses ./target/release/handmade-ray
# Scene::hit 遍历 objects,如果 objects 数组大,cache miss 高
# 优化:BVH(只查可能撞的物体)

# SIMD 占比
perf stat -e fp_arith_inst_retired.scalar_single,fp_arith_inst_retired.128b_packed_single ./target/release/handmade-ray
# 看 SIMD 指令占比,> 50% 是好的
```

**BVH(Bounding Volume Hierarchy)加速**:

```rust
enum BvhNode {
    Leaf { object_indices: Vec<usize> },
    Branch { left: Box<BvhNode>, right: Box<BvhNode>, bounds: Aabb },
}

impl BvhNode {
    fn hit(&self, ray: &Ray, scene: &Scene) -> Option<HitRecord> {
        match self {
            Leaf { .. } => { /* 遍历 leaf 内的物体 */ }
            Branch { left, right, bounds } => {
                // 先检查 AABB,如果不撞,直接返回(剪枝)
                if bounds.intersect(ray).is_none() {
                    return None;
                }
                // 递归左右子树
                let left_hit = left.hit(ray, scene);
                let right_hit = right.hit(ray, scene);
                match (left_hit, right_hit) {
                    (Some(l), Some(r)) => Some(if l.t < r.t { l } else { r }),
                    (Some(l), None) => Some(l),
                    (None, Some(r)) => Some(r),
                    (None, None) => None,
                }
            }
        }
    }
}
```

**BVH 把复杂度从 O(N) 降到 O(log N)**——10000 个物体的场景,BVH 让每条光线只检查 log(10000) ≈ 13 个节点。**主剧 Phase 8 详细讲 BVH**。

**MERL BRDF 数据布局**:34 MB 文件 mmap 到内存,直接索引访问:

```rust
use memmap2::Mmap;

let file = File::open("merl.brdf")?;
let mmap = unsafe { Mmap::map(&file)? };
let data: &[f32] = bytemuck::cast_slice(&mmap[12..]);  // 跳过 header
// 直接按索引访问,零拷贝
```

### 3.4 · 🦀 Rust 生态视角

**Path tracer 的多线程架构**:

```rust
use rayon::prelude::*;
use std::sync::Arc;

let scene = Arc::new(scene);

framebuffer
    .par_chunks_mut(width * 3)
    .enumerate()
    .for_each(|(y, row)| {
        // 每线程独立 PRNG(避免锁)
        let mut rng = rand::rngs::SmallRng::from_entropy();
        for x in 0..width {
            let mut color_sum = Color::ZERO;
            for _ in 0..samples {
                let ray = camera.ray_for_pixel(x as u32, y as u32, &mut rng);
                color_sum += ray_color(&ray, &scene, 0, &mut rng);
            }
            // 写入 row
        }
    });
```

**关键**:
- `Arc<Scene>` 共享 scene(线程安全)
- `SmallRng` 线程本地 PRNG(快)
- `par_chunks_mut` 行级并行,无锁

**Rust trait object vs enum** in path tracer:

```rust
// 方案 1:trait object
struct Object { shape: Shape, material: Box<dyn Material> }

// 方案 2:enum
enum Material { Lambertian(Color), Metal(Color, f32), Dielectric(f32) }
struct Object { shape: Shape, material: Material }
```

**方案 2(enum)更快**——无 vtable,SIMD 友好。Casey 在 ray04 用类似方案。**生产 path tracer 都用 enum 或 tagged union**。

### 3.5 · 🔢 数学视角

**Monte Carlo 积分**:

```
∫_Ω f(x) dx ≈ (1/N) Σ_i f(x_i) / p(x_i)
```

x_i ~ p(x),误差 ~ σ / sqrt(N),σ = sqrt(Var[f/p]).

**Importance sampling**:选 p(x) ∝ |f(x)|,使 σ 最小。

**Russian Roulette**:无偏的概率截断。设 p = 终止概率,继续的概率 (1-p)。期望:

```
E[final] = p * 0 + (1-p) * E[full] / (1-p) = E[full]
```

无偏。方差增加,但样本数足够时方差按 `1/N` 减小。

**Path tracing 完整公式**:

```
L(p, ω) = L_e(p, ω) + (1/N) Σ_i [
    BRDF(p, ω_i, ω) * L_in(p, ω_i) * cos(θ_i) / pdf(ω_i)
]
```

每条采样 path 贡献一个 sample,平均得 L 的估计。

**PDF 选择**:

- Lambert BRDF:PDF = cos(θ) / π(余弦加权)
- Phong BRDF:PDF = (n+1) / (2π) * cos(θ)^n(镜面加权)
- GGX BRDF:复杂(微表面分布)

## 4 · 认知地图

### 4.1 上级

- **Path Tracing** — Monte Carlo 数值求解渲染方程
- **Russian Roulette** — 概率截断,无偏
- **Importance Sampling** — 按分布采样,降方差
- **Tone Mapping** — HDR → LDR 映射
- **测量 BRDF** — 真实材质数据(MERL)

### 4.2 同级(并行方案)

| 方案 | 关键差别 | 何时用 | 本项目选了哪个 |
|---|---|---|---|
| 固定 max_depth | 简单,但硬截断 | 教学 | ray03 |
| Russian Roulette | 无偏概率截断 | path tracing | ✅ ray04 |
| Next Event Estimation | 主动从光源采样 | 直接光照优化 | ✅ ray04 |
| Bidirectional Path Tracing | 双向追踪 | 复杂场景 | HH 不用 |
| Photon Mapping | 光子缓存 | 焦散 | HH 不用 |
| MERL BRDF | 测量数据 | 真实材质 | ✅ ray04(Casey) |
| Analytical BRDF | 公式 | 教学 / 简单 | ray01-03 |

### 4.3 下级

- **Russian Roulette 实现** — 概率截断 + 补偿
- **Importance Sampling** — 余弦加权 / GGX 分布
- **面积光采样** — 均匀圆盘采样
- **MERL BRDF 加载** — 二进制解析
- **Tone Mapping** — Reinhard / ACES
- **BVH 加速** — 树形空间索引
- **NEE** — 直接光照分离

## 5 · 对照与变奏

### 不同 path tracing 算法对比

| 算法 | 复杂度 | 噪声 | 适用 | 提出年 |
|---|---|---|---|---|
| Path Tracing | O(N pixels × N samples) | 中 | 一般场景 | 1986 |
| Bidirectional Path Tracing | O(2N) | 低 | 复杂场景 | 1993 |
| Metropolis Light Transport | 自适应 | 极低 | 极复杂 | 1997 |
| Photon Mapping | O(N photons + N queries) | 中(有偏) | 焦散 | 1996 |
| VCM / UPS | BDPT + PM | 低 | 通用 | 2012 |

### Tone Mapping 算法

| 算法 | 公式 | 特点 |
|---|---|---|
| Reinhard | `c / (c + 1)` | 简单,常用 |
| Reinhard Extended | `c * (1 + c/L²) / (1 + c)` | 有白点 |
| ACES Filmic | 多项式 | 电影感强 |
| Hable / Uncharted 2 | 复杂 | 游戏用 |
| Filmic (John Hable) | 改进 Hable | Uncharted 用 |

**主流游戏**:ACES(Unreal、Unity 默认)。

### 历史演化

- **1980 Whitted**:递归 ray tracing
- **1984 Cook**:分布式光线追踪
- **1986 Kajiya**:Path Tracing + 渲染方程
- **1996 Jensen**:Photon Mapping
- **1997 Veach**:BDPT + MLT
- **2014 Heitz**:Multiple Importance Sampling(GGX)
- **2018+ RTX**:GPU 实时
- **2020+ ReSTIR**:实时低噪声 path tracing

## 6 · 关联

- **铺垫**:
  - [ray03.md](ray03.md) — 材质系统
  - [ray02.md](ray02.md) — Phong 光照
  - [README.md](README.md) — Handmade Ray 总览
- **当天**:ray04 — 反射、递归深度、抗锯齿、BRDF
- **后续**:
  - 主剧 [../phase-8/day580.md](../phase-8/day580.md)+ — SIMD 加速 raycast
  - 主剧 [../phase-8/day640.md](../phase-8/day640.md)+ — BVH 加速结构

## 7 · 变式训练

### Lv1 · 概念辨析

**题**:Russian Roulette 为什么"除以 continue_probability"补偿?如果不补偿会怎样?

**参考解答**:

设原递归期望 E。Russian Roulette 后:

```
50% 终止 → 贡献 0
50% 继续 → 贡献 attenuation * ray_color(...) = X
```

**平均**:`0.5 * 0 + 0.5 * X = 0.5 X`。**期望变成原来的一半**——画面变暗!

**补偿**:继续的部分**除以 0.5**:

```
50% 终止 → 0
50% 继续 → X / 0.5 = 2X
```

平均:`0.5 * 0 + 0.5 * 2X = X`。**期望恢复原值**,无偏。

**如果不补偿**:画面整体变暗(因为补偿没做,期望减半),且**深度越大越暗**(每层都减半),**完全错误**。

**关键**:Russian Roulette 必须配合补偿才无偏。补偿公式:`contribution / p_continue`。

### Lv2 · 动手实践

**题**:在 ray03 基础上加:
1. Russian Roulette(深度 > 5 后,50% 终止,补偿)
2. 面积光(半径 0.5)+ 软阴影
3. ACES tone mapping

完成标准:阴影柔和(从中心向外渐变),画面色彩合理(不会过曝),深度 > 5 的反射不丢失。

**参考解答**(关键代码):

```rust
fn ray_color(ray: &Ray, scene: &Scene, depth: u32) -> Color {
    if depth >= 100 { return Color::ZERO; }
    if let Some(hit) = scene.hit(ray) {
        if let Some((attenuation, scattered)) = hit.material.scatter(ray, &hit) {
            // Russian Roulette
            if depth > 5 {
                let p = 0.5;
                if rand::random::<f32>() > p {
                    return Color::ZERO;
                }
                return attenuation * ray_color(&scattered, scene, depth + 1) / p;
            }
            attenuation * ray_color(&scattered, scene, depth + 1)
        } else {
            Color::ZERO
        }
    } else {
        let t = 0.5 * (ray.direction.y + 1.0);
        vec3(0.3, 0.5, 1.0).lerp(vec3(1.0, 1.0, 1.0), t)
    }
}

fn aces_tonemap(c: Vec3) -> Vec3 {
    let a = 2.51; let b = 0.03; let c = 2.43; let d = 0.59; let e = 0.14;
    ((c * (a * c + b)) / (c * (c * c + d) + e)).clamp(Vec3::ZERO, Vec3::ONE)
}

// 加 AreaLight
struct AreaLight {
    center: Vec3,
    radius: f32,
    color: Color,
}

impl AreaLight {
    fn random_point(&self) -> Vec3 {
        let r1: f32 = rand::random();
        let r2: f32 = rand::random();
        let phi = 2.0 * std::f32::consts::PI * r1;
        let r = self.radius * r2.sqrt();
        self.center + Vec3::new(r * phi.cos(), 0.0, r * phi.sin())
    }
}

fn shadow_factor(point: Vec3, light: &AreaLight, scene: &Scene, n_samples: u32) -> f32 {
    let mut visible = 0;
    for _ in 0..n_samples {
        let light_point = light.random_point();
        if !in_shadow(point, light_point, scene) {
            visible += 1;
        }
    }
    visible as f32 / n_samples as f32
}

// 渲染时应用 tone mapping
let color = aces_tonemap(color_sum / samples as f32);
let color = vec3(
    color.x.powf(1.0 / 2.2),  // gamma 校正(粗略,不是真正 sRGB)
    color.y.powf(1.0 / 2.2),
    color.z.powf(1.0 / 2.2),
);
```

### Lv3 · 迁移设计

**题**:你被要求做**景深效果**(depth of field)——相机有光圈,远处的物体模糊,近处的物体清晰。如何用 path tracing 实现?提示:薄透镜相机(thin lens camera)。

**提示**:
- 针孔相机:每像素一条光线,从同一点出发
- 薄透镜相机:光线从光圈上的**随机点**出发,聚焦在 focal plane
- 远处物体的光线散布范围大 → 模糊
- 近处物体光线集中 → 清晰

### Lv4 · 开源贡献

**题**:`rust-pathtracer` 是 Rust 社区的一个 path tracer,GitHub 上有多个实现。

1. 找一个:`gh search repos "rust path tracer"`
2. clone,读源码
3. **可能的贡献方向**:
   - 加 BVH 加速(如果没实现)
   - 加 importance sampling
   - 加 tone mapping 选项(Reinhard / ACES / Filmic)
   - 加 MERL BRDF 加载
4. 写 PR 描述

## 8 · Rust / Arch 落地代码

### 完整 ray04 代码(关键扩展)

在 ray03 基础上加 Russian Roulette、面积光、tone mapping:

```rust
// 完整代码基于 ray03,这里列关键改动

use glam::{Vec3, vec3};
use rand::Rng;
use rayon::prelude::*;
use std::sync::Arc;

// ... ray03 的所有定义 ...

// AreaLight 软阴影
struct AreaLight {
    center: Vec3,
    radius: f32,
    color: Color,
}

impl AreaLight {
    fn random_point(&self) -> Vec3 {
        let mut rng = rand::thread_rng();
        let r1: f32 = rng.gen_range(0.0..2.0 * std::f32::consts::PI);
        let r2: f32 = rng.gen();
        let r = self.radius * r2.sqrt();
        self.center + Vec3::new(r * r1.cos(), 0.0, r * r1.sin())
    }
}

fn shadow_factor(point: Vec3, light: &AreaLight, scene: &Scene, n_samples: u32) -> f32 {
    let mut visible = 0;
    for _ in 0..n_samples {
        let light_point = light.random_point();
        let to_light = light_point - point;
        let distance = to_light.length();
        let direction = to_light / distance;
        let shadow_ray = Ray { origin: point + direction * 0.001, direction };
        let mut blocked = false;
        for obj in &scene.objects {
            if let Some(h) = obj.shape.intersect(&shadow_ray, &obj.material) {
                if h.t < distance {
                    blocked = true;
                    break;
                }
            }
        }
        if !blocked { visible += 1; }
    }
    visible as f32 / n_samples as f32
}

// Russian Roulette
fn ray_color(ray: &Ray, scene: &Scene, light: &AreaLight, depth: u32) -> Color {
    if depth >= 100 { return Color::ZERO; }
    if let Some(hit) = scene.hit(ray) {
        // 直接光照(从面积光采样)
        let direct = if let Some(lambert) = hit.material.as_lambertian() {
            let l = (light.center - hit.point).normalize();
            let n_dot_l = hit.normal.dot(l).max(0.0);
            let shadow = shadow_factor(hit.point, light, scene, 8);
            lambert.albedo * light.color * n_dot_l * shadow
        } else {
            Color::ZERO
        };

        // 间接光照(递归 + Russian Roulette)
        let indirect = if let Some((attenuation, scattered)) = hit.material.scatter(ray, &hit) {
            if depth > 5 {
                let p = 0.5;
                if rand::random::<f32>() > p {
                    Color::ZERO
                } else {
                    attenuation * ray_color(&scattered, scene, light, depth + 1) / p
                }
            } else {
                attenuation * ray_color(&scattered, scene, light, depth + 1)
            }
        } else {
            Color::ZERO
        };

        direct + indirect
    } else {
        let t = 0.5 * (ray.direction.y + 1.0);
        vec3(0.3, 0.5, 1.0).lerp(vec3(1.0, 1.0, 1.0), t)
    }
}

// Tone mapping
fn aces_tonemap(c: Vec3) -> Vec3 {
    let a = 2.51; let b = 0.03; let cc = 2.43; let d = 0.59; let e = 0.14;
    let num = c * (a * c + b);
    let den = c * (cc * c + d) + e;
    (num / den).clamp(Vec3::ZERO, Vec3::ONE)
}

fn gamma_correct(c: Vec3) -> Vec3 {
    vec3(c.x.powf(1.0 / 2.2), c.y.powf(1.0 / 2.2), c.z.powf(1.0 / 2.2))
}

fn render(scene: &Scene, camera: &Camera, light: &AreaLight, samples: u32) -> Vec<u8> {
    let sqrt_spp = (samples as f32).sqrt() as u32;
    let width = camera.width;
    let height = camera.height;

    let fb: Vec<u8> = (0..height)
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
                        color_sum += ray_color(&ray, scene, light, 0);
                    }
                }
                let mut color = color_sum / (sqrt_spp * sqrt_spp) as f32;
                color = aces_tonemap(color);
                color = gamma_correct(color);

                let i = (x * 3) as usize;
                row[i] = (color.x * 255.0) as u8;
                row[i+1] = (color.y * 255.0) as u8;
                row[i+2] = (color.z * 255.0) as u8;
            }
            row
        })
        .collect();
    fb
}
```

### MERL BRDF 加载(Casey ray04 核心)

```rust
// Cargo.toml:[dependencies]
// memmap2 = "0.9"
// bytemuck = "1.14"

use memmap2::Mmap;
use std::fs::File;

struct MerlBrdf {
    data: Vec<f32>,  // 90 * 90 * 180 * 3
}

impl MerlBrdf {
    fn load(path: &str) -> std::io::Result<Self> {
        let file = File::open(path)?;
        let mmap = unsafe { Mmap::map(&file)? };

        // Header:3 个 i32(90, 90, 180)
        let header = &mmap[..12];
        let n0 = i32::from_le_bytes(header[0..4].try_into().unwrap());
        let n1 = i32::from_le_bytes(header[4..8].try_into().unwrap());
        let n2 = i32::from_le_bytes(header[8..12].try_into().unwrap());
        assert_eq!(n0, 90);
        assert_eq!(n1, 90);
        assert_eq!(n2, 180);

        let data: Vec<f32> = bytemuck::cast_slice(&mmap[12..]).to_vec();
        Ok(Self { data })
    }

    fn sample(&self, theta_h: f32, theta_d: f32, phi_d: f32) -> Color {
        let half_pi = std::f32::consts::FRAC_PI_2;
        let pi = std::f32::consts::PI;
        // 离散化到 90/90/180 网格
        let ih = ((theta_h / half_pi * 89.0) as usize).min(89);
        let id = ((theta_d / half_pi * 89.0) as usize).min(89);
        let ip = ((phi_d / pi * 179.0) as usize).min(179);
        let idx = ((ih * 90 + id) * 180 + ip) * 3;
        Color::new(
            self.data[idx].max(0.0),
            self.data[idx + 1].max(0.0),
            self.data[idx + 2].max(0.0),
        )
    }
}
```

### Arch Linux 命令

```bash
# 1. 装依赖
cat >> Cargo.toml << 'EOF'
memmap2 = "0.9"
bytemuck = { version = "1.14", features = ["derive"] }
EOF

# 2. 下载 MERL BRDF 数据(科研用)
# 访问 https://www.merl.com/brdf/
# 下载某个材质(如 aluminum.binary),约 4 MB

# 3. 编译运行
cargo run --release
# 输出:渲染一帧 5-30 秒(看 samples / max_depth / 物体数)

# 4. 性能分析
hyperfine --runs 3 './target/release/handmade-ray'
# 1080p 16 samples 应该 5-15 秒(看 CPU)

# 5. 火焰图
cargo flamegraph --bin handmade-ray --release
# 看 ray_color / Material::scatter / Scene::hit 占比
# BVH 加速前 Scene::hit 占 50%+

# 6. 多核验证
nproc  # 16
MANGOHUD=1 ./target/release/handmade-ray
# 看 GPU(其实没用 GPU,这里看 CPU)所有核应该打满

# 7. SIMD 验证(glam)
cargo rustc --release -- --emit asm --target-cpu native
find target/release/deps/ -name "*.s" | head -1 | xargs grep -c "_mm256"
# 应该看到 AVX 指令数(几百条)

# 8. tone mapping 验证
# 把一张过曝的图,改 tone mapping 算法,看视觉差别
# Reinhard vs ACES vs Filmic 各有风格

# 9. MERL 数据查看(用 numpy)
sudo pacman -S python-numpy
python3 -c "
import numpy as np
data = np.fromfile('aluminum.binary', dtype=np.float32, offset=12)
data = data.reshape(90, 90, 180, 3)
print('shape:', data.shape)
print('max:', data.max())
print('mean:', data.mean())
"
```

**Troubleshooting**:

- 噪声大:samples 不够,加到 64 或 256。
- 性能慢:max_depth 大,加 Russian Roulette。
- 颜色饱和 / 偏白:加 tone mapping。
- 玻璃球黑:Dielectric 实现错,检查 cos_theta 和 refract。
- 阴影硬:面积光 radius 太小,加到 0.5 或 1.0。
- MERL 加载失败:header 不是 90/90/180,可能下载错文件。

## 9 · 延伸阅读(可选补充,非必需)

本仓库本地:
- [ray03.md](ray03.md) — 材质系统
- [README.md](README.md) — Handmade Ray 总览
- [../phase-8/day580.md](../phase-8/day580.md) — SIMD 加速(主剧 Phase 8)

外部稳定 URL(可选):
- Ray Tracing: The Rest of Your Life(Shirley 第 3 本, importance sampling): https://raytracing.github.io/books/RayTracingTheRestOfYourLife.html
- PBRT-Book Chapter 13-14(Monte Carlo + Light Transport): https://www.pbr-book.org/3ed-2018/Monte_Carlo_Integration
- MERL BRDF Database: https://www.merl.com/brdf/
- Rusinkiewicz BRDF 参数化: https://www.cs.princeton.edu/~smr/papers/brdf/
- ACES Tone Mapping: https://knarkowicz.wordpress.com/2016/01/06/aces-filmic-tone-mapping-curve/

真实开源源码:
- PBRT-Book 源码(C++): https://github.com/mmp/pbrt-v3
- Mitsuba 3(科研 path tracer): https://github.com/mitsuba-renderer/mitsuba3
- Casey Handmade Ray ray04: https://guide.handmadehero.org/ray/ray04/
