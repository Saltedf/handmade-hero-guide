---
episode: 01
series: handmade-ray
title_en: "Basic Raytracer Setup"
title_zh: "基本光线追踪器搭建"
type: coding
difficulty: 2
duration: "2-3h"
hh_url: "https://guide.handmadehero.org/ray/ray00/"
domains: [graphics, math, rust]
prereqs: ["../phase-0/14-math-foundations", "ray00"]
---

# ray01 · 基本光线追踪器搭建

> ray00 你写了一个最小 raycaster——能渲染球体,但球是纯色,没有光照、没有深度感。这一集我们**升级到真正的 raytracer**:加相机参数化(可调 FOV、可调位置)、加法线计算(知道光线从哪个方向撞到球面)、加 Lambert 漫反射光照(球体有明暗变化)、加抗锯齿的第一步(每个像素采多次平均)。这一集之后,你的画面从"卡通片"变成"真实物体"——有光照、有立体感、有视觉深度。

## 0 · 为什么要有这一天

回到 ray00 的画面:三个球——绿、红、蓝——在渐变背景上。看起来是**卡通片**——每个球是纯色圆盘,**没有立体感**。你完全看不出哪个球是金属、哪个是塑料、哪个是玻璃;**它们看起来都像贴纸**。

为什么没有立体感?**因为缺少光照**。真实世界里,你看一个球,**靠近光源的一面亮、背面暗**,中间有过渡——这个明暗变化告诉你"这是个三维球",而不是"二维圆"。

ray00 的颜色函数 `obj.color` 直接返回球体颜色,**完全不算光照**。今天我们要**加 Lambert 漫反射光照**:

```
final_color = surface_color × light_intensity × max(0, N · L)
```

其中 `N` 是表面法线(垂直于表面的单位向量),`L` 是指向光源的单位向量,`N · L` 是它们的点积。光线直射表面(N 和 L 同向),点积 = 1,最亮;光线掠过表面(N ⊥ L),点积 = 0,最暗;光线在背面(N · L < 0),完全黑。

这是 [day041](../phase-2/day041.md) 提到的"Lambert 漫反射"公式的实现。Lambert 是计算机图形学最古老也最常用的光照模型(1760 年代 Lambert 提出,1960 年代进入 CG)。**80% 的"看着像 3D"的效果都来自 Lambert**。

但 Lambert 还不够"真实"。Lambert 假设物体是哑光的(像粉笔、哑光纸),**没有高光**。真实物体——金属、塑料、玻璃——还有 **specular highlight**(高光斑)。Phong / Blinn-Phong 模型加了这个:

```
final_color = ambient + diffuse(Lambert) + specular(Phong)
```

ray01 主要加 Lambert(漫反射),specular 留给 ray02(配合阴影射线和多种光源)。**先做对一件事再做下一件**——这是工业开发的节奏。

**相机参数化**也是 ray01 的工作。ray00 的相机是"硬编码"的——固定在原点、固定看 -z 方向、固定 FOV 60°。真实渲染器要支持任意相机位置、任意朝向、可调 FOV。我们用 `look_from` / `look_at` / `up` 三个参数定义相机(经典 gluLookAt 模型),加 FOV、宽高比、光圈(给景深用)。

为什么这件事重要?因为**任何 3D 渲染都要有相机系统**。光栅化用 MVP 矩阵(model-view-projection),光线追踪用 ray generation。两者数学等价(矩阵是 ray generation 的紧凑表示),**理解 ray generation 你看 MVP 矩阵不再神秘**。

最后我们**加入超级采样抗锯齿(SSAA)**的雏形——每个像素发射 N 条光线(亚像素位置不同),平均颜色。N=4 已经显著减少锯齿,N=16 接近完美。**这是后面 ray04 MSAA / 分布式光线追踪的基础**。

心理锚点:今天之后,你能:(1) 写一个 look-from / look-at 相机,生成任意角度的射线;(2) 计算射线-球相交后的表面法线,用 Lambert 公式给球加明暗;(3) 用 SSAA 减少画面锯齿;(4) 解释为什么 ray generation 等价于 MVP 矩阵。

## 1 · Casey 今天做了什么(Handmade Ray 脉络)

Casey 在 Handmade Ray ray00 的下半段(本集对应部分)做的:

1. **加表面法线**:在 `intersect` 返回 t 的同时,计算法线 `normal = (hit_point - sphere.center).normalize()`。法线是球面在交点处的单位向量(指向球外)。

2. **加 Lambert 漫反射**:光源在固定位置(比如 (5, 5, 0)),每个像素的颜色从 `obj.color` 改成 `obj.color * max(0, normal · light_dir)`。光线直射面亮,背面暗。

3. **加 ambient 项**:为防止背面完全黑,加一个常数环境光(比如 0.1)。`final = ambient + diffuse * (1 - ambient)`。

4. **加 SSAA**:每个像素发射 4 条光线(2×2 网格,亚像素位置),平均颜色。**渲染时间 4 倍,但锯齿显著减少**。

5. **加阴影**:从交点向光源发射阴影射线,如果中间有遮挡 → 该点在阴影里,diffuse = 0。

到 ray01 结束,画面有明暗、有阴影、有抗锯齿,**看起来像真正的 3D 渲染**。

## 2 · 心智模型

### 类比:光照是"立体感的语言"

想象你看两张照片:一张是**平面圆形**(纯色,没有明暗),另一张是**球的照片**(有明暗渐变)。你的大脑**瞬间**知道第二张是 3D,第一张是 2D——这个判断**完全来自光照信息**。

具体地,大脑用以下线索判断立体感:

- **明暗渐变**(shading):表面接受的光随角度变化,亮 → 暗的过渡告诉你表面曲率
- **阴影**(shadow):物体投射在其他物体上的阴影告诉你**空间关系**(谁在前谁在后)
- **高光**(highlight):镜面反射的亮斑告诉你**材质**(哑光无高光,金属有明显高光)
- **环境光遮蔽**(AO):角落的暗化告诉你**几何接触**(墙角比墙中央暗)

ray00 没有这些,**画面像剪贴画**。ray01 加上明暗(Lambert)和阴影,**画面像有阳光照射的物体**。

### 严谨原理:Lambert 漫反射

Lambert 光照模型基于一个物理直觉:**表面接受的光量和"光线方向与表面法线的夹角"有关**。具体地:

```
接受的辐射照度(irradiance) ∝ cos(θ)
```

θ 是光线方向(指向光源)和法线的夹角。

**为什么是 cos(θ)**?想象一束光,**斜着**射到表面。光束的截面积是固定的,但**光束在表面上的投影面积变大**(因为光斜着)。同样的光"摊"到更大面积,单位面积的光量减少。**单位面积光量 = 总光量 / 投影面积 = 总光量 × cos(θ)**。

这是 **Lambert 余弦定律**(1760 年),所有漫反射光照的基础。

数学上:`cos(θ) = N · L`(N 是法线,L 是指向光源的方向,都是单位向量)。

**Lambert 漫反射公式**:

```
final = surface_color × light_intensity × max(0, N · L)
```

**max(0, ...) 的作用**:如果光线在表面背面(N · L < 0),光根本照不到这一面,贡献 = 0(不是负数!)。

**关键点**:Lambert 假设物体表面**完全哑光**——光从某个方向射入,**均匀散射到所有方向**。这是哑光纸、粉笔、泥土的近似。但**不是金属、塑料、玻璃**(它们有 specular)。

### 法线计算

法线 N 是垂直于表面的单位向量,**指向表面外侧**。对球体,球面任一点的法线**从球心指向该点**:

```rust
fn sphere_normal(sphere: &Sphere, point: Vec3) -> Vec3 {
    (point - sphere.center).normalize()
}
```

为什么这样?球面上任一点 P,**球心到 P 的方向就是 P 点的法线**(因为球面是"等距离面",梯度方向就是法线)。归一化后是单位向量。

对其他几何,法线计算不同:
- **平面**:法线是平面的固定属性(创建时指定),和点无关
- **三角形**:法线 = 两条边的叉积,归一化
- **AABB(轴对齐包围盒)**:法线 = 6 个面之一,取决于射线从哪面进入

**ray02 / ray03 会讲这些**。

### 相机模型

**look-from / look-at 相机**:

```rust
struct Camera {
    look_from: Vec3,
    look_at: Vec3,
    up: Vec3,           // 世界坐标系的上方向(通常 (0,1,0))
    fov: f32,           // 视场角(度数)
    aspect_ratio: f32,  // 宽高比
}
```

**相机基向量**(三个相互正交的单位向量):

- `forward = (look_at - look_from).normalize()` — 相机看向的方向
- `right = forward.cross(up).normalize()` — 相机的右方
- `camera_up = right.cross(forward)` — 相机的上方(重新算,保证正交)

**为什么 `right.cross(forward)` 而不是直接用 `up`**?因为 `up` 是世界坐标系,可能不与 `forward` 正交。比如相机看向斜下方,世界 up 还在 (0,1,0),但相机的"上"应该跟着倾斜。**用 right × forward 重算保证正交**。

**射线生成**(对像素 (x, y)):

```rust
fn ray_for_pixel(&self, x: u32, y: u32) -> Ray {
    // 屏幕坐标 → NDC:[-1, 1]
    let u = (2.0 * (x as f32 + 0.5) / self.width as f32 - 1.0) * self.half_width;
    let v = (1.0 - 2.0 * (y as f32 + 0.5) / self.height as f32) * self.half_height;

    let direction = (self.forward + self.right * u + self.camera_up * v).normalize();
    Ray { origin: self.look_from, direction }
}
```

**关键参数**:
- `half_height = tan(fov / 2)`
- `half_width = half_height * aspect_ratio`
- `+0.5` 是因为像素中心在 (x + 0.5, y + 0.5)
- y 方向翻转:屏幕 y 向下,世界 y 向上

### 阴影射线

**阴影的本质**:光从光源出发,如果**中间被物体挡住**,光照不到目标点。

**算法**:从交点 P 向光源发射一条射线(阴影射线),如果射线在到光源的距离内**撞到其他物体**,则 P 在阴影里。

```rust
fn in_shadow(p: Vec3, light_pos: Vec3, scene: &Scene) -> bool {
    let direction = (light_pos - p).normalize();
    let distance = (light_pos - p).length();
    let shadow_ray = Ray { origin: p + direction * 0.001, direction };  // epsilon 防自相交

    for obj in &scene.objects {
        if let Some(t) = obj.intersect(&shadow_ray) {
            if t < distance {
                return true;  // 有遮挡
            }
        }
    }
    false
}
```

**关键细节**:
- **epsilon offset**:`p + direction * 0.001`,阴影射线起点稍微离开表面,防止阴影射线和**刚才相交的表面**再次相交(浮点误差导致)
- **distance check**:只检查阴影射线上**到光源之前**的交点,超过光源的不算(可能在光源背后的物体)

### SSAA(超级采样抗锯齿)

**锯齿(aliasing)**:像素是离散的,边缘像素要么属于物体要么不属于,**产生阶梯状的边缘**。

**SSAA 的思路**:每个像素**发射多条光线**(亚像素位置不同),**平均颜色**。N 条光线对应 N 个亚像素位置。

```rust
fn ray_cast_with_ssaa(x: u32, y: u32, samples: u32, scene: &Scene, camera: &Camera) -> Color {
    let mut color = Color::ZERO;
    let sqrt_samples = (samples as f32).sqrt() as u32;
    for sy in 0..sqrt_samples {
        for sx in 0..sqrt_samples {
            // 亚像素位置
            let sub_x = x as f32 + (sx as f32 + 0.5) / sqrt_samples as f32;
            let sub_y = y as f32 + (sy as f32 + 0.5) / sqrt_samples as f32;
            let ray = camera.ray_for_subpixel(sub_x, sub_y);
            color += ray_cast_with_lighting(&ray, scene);
        }
    }
    color / samples as f32
}
```

**常用采样数**:
- 1 sample:无 SSAA,锯齿明显
- 4 samples(2×2):显著减少锯齿,常用
- 16 samples(4×4):高质量,工业离线渲染用
- 64+:接近完美

**计算量**:SSAA 是**直接倍增**渲染时间——4 samples = 4 倍时间。**这是 SSAA 的最大缺点**,工业上用 MSAA(只对边缘像素多次采样)或 FXAA(后处理滤波)减少开销。

**ray04 会讲分布式光线追踪(distributed ray tracing)**,SSAA 的进阶版——除了抗锯齿,还做软阴影、运动模糊、景深,都用同一套多次采样框架。

### ray generation 和 MVP 矩阵的关系

光栅化用 **MVP 矩阵**(Model-View-Projection):

```
clip_pos = P × V × M × model_pos
```

- M(model):模型空间 → 世界空间
- V(view):世界空间 → 相机空间
- P(projection):相机空间 → clip 空间(应用透视除法)

光线追踪用 **ray generation**:

```
ray.direction = forward + right * u + up * v
```

**两者数学上等价**!MVP 矩阵可以**反推**出 ray generation:

```
反投影:从像素 (x, y) 反推到 NDC → 反 P 矩阵 → 反 V 矩阵 → 世界射线
```

具体地:

```rust
// 反投影(从屏幕到 3D 射线)
let ndc = vec3(
    2.0 * x / width - 1.0,
    1.0 - 2.0 * y / height,
    -1.0,  // 近平面
);
let clip = vec4(ndc.x, ndc.y, ndc.z, 1.0);
let view = inverse_projection * clip;
let world = inverse_view * view;
let ray_dir = (world.xyz() / world.w - camera_pos).normalize();
```

`inverse_projection` 和 `inverse_view` 是 P 和 V 的逆矩阵。**反推 ray generation 等价于用 MVP 矩阵的逆**。

光栅化用正向矩阵(model → screen),光线追踪用逆向(屏幕 → world)。**两者是同一物理过程的两个方向**。

## 3 · 四域深入

### 3.1 · 🎮 游戏编程视角

游戏开发里光照和相机的标准做法:

**Phong 光照模型**(ray01 加 Lambert,ray02 加 Phong):

```
final = ambient + diffuse * (N · L) + specular * (R · V)^n
```

- `ambient`:常数项,模拟间接光
- `diffuse`:Lambert 漫反射
- `specular`:Phong 镜面反射(R 是 L 关于 N 的反射方向,V 是视线方向)
- `n`:shininess(镜面指数),越大高光越小越锐

**Blinn-Phong**(优化版,业界标准):

```
half = normalize(L + V)
specular = (N · half)^n
```

`half` 是 L 和 V 的中间方向,用 `N · half` 替代 `R · V`。**计算更简单**(不用算 R),**视觉几乎一样**,是 OpenGL 固定管线和早期 GLSL 的标准。

**PBR(Physically Based Rendering)**(Unreal、Unity 标配):

```
final = (kD * diffuse + kS * specular) * radiance
```

- `kD`:漫反射系数(非金属)
- `kS`:镜面系数(金属)
- `radiance`:入射光的辐射度
- `specular`:Cook-Torrance BRDF(微表面模型)

PBR 是 Lambert 和 Phong 的**物理正确版**,**albedo**(漫反射率)和 **metalness**(金属度)是材质属性。学完 ray01-03 你看 PBR 不再神秘。

**相机**:游戏用 **camera transform**(第一人称、第三人称、轨道)。Look-from / look-at 是基础,加 mouse control(鼠标转视角)、follow target(跟随目标)等。

### 3.2 · 🎨 图形学视角

光照模型的历史演化:

| 年代 | 模型 | 描述 |
|---|---|---|
| 1760 | Lambert 余弦定律 | 漫反射基础 |
| 1973 | Phong | 加 specular(highlight) |
| 1977 | Blinn-Phong | half-vector 优化 |
| 1986 | Cook-Torrance | 微表面模型(PBR 基础) |
| 1990s | Ward | 各向异性反射 |
| 2010+ | Disney Principled BRDF | 工业标准 PBR 参数 |
| 2015+ | MERL BRDF Database | 测量 BRDF(ray04 用) |

**ray01 用 Phong**,这是教学标准——简单、能展示核心概念。ray04 会触及 MERL 测量 BRDF(Casey 原版做的)。

**法线插值**(Gouraud vs Phong shading):

- **Flat shading**:每个三角形一个法线,三角形之间硬边
- **Gouraud shading**:每个顶点一个法线,fragment 颜色从顶点颜色插值
- **Phong shading**:每个顶点一个法线,fragment 法线从顶点法线插值,**然后**算光照

**Phong shading** 是现代标准(ray01 不区分,因为我们直接从相交算法线,不是从顶点)。

### 3.3 · 🐧 Linux 系统编程视角

Linux 上做 ray tracer 性能优化的工具:

**CPU 信息**:

```bash
lscpu
# Architecture:        x86_64
# CPU(s):              16           # 16 个逻辑核
# Thread(s) per core:  2            # 每核 2 线程(超线程)
# Core(s) per socket:  8
# Model name:          Intel(R) Core(TM) i7-...
# CPU MHz:             ...
# Virtualization:      VT-x
# Flags:               fpu vme de pse ... avx avx2 avx512f ...
#                                              ^^^ SIMD 指令集

cat /proc/cpuinfo | grep -c "^processor"  # 逻辑核数
```

**SIMD 指令集**:

```bash
cat /proc/cpuinfo | grep "flags" | head -1 | tr ' ' '\n' | grep -E "(sse|avx|fma)"
# sse sse2 ssse3 sse4_1 sse4_2  -- 4-wide(128-bit)
# avx avx2 fma                   -- 8-wide(256-bit)
# avx512f avx512cd ...           -- 16-wide(512-bit),高端 CPU
```

**性能分析**:

```bash
# 单帧渲染时间
hyperfine --runs 10 './target/release/handmade-ray'

# Cache miss 分析
perf stat -e cache-misses,cache-references,L1-dcache-load-misses ./target/release/handmade-ray

# 内存带宽
sudo perf stat -e dram_reads,dram_writes ./target/release/handmade-ray

# 火焰图
cargo flamegraph --bin handmade-ray --release
```

**多线程**(ray01 不用,但讲一下 ray02 的预热):

```bash
# 设置程序用多少核
taskset -c 0-7 ./target/release/handmade-ray  # 只用 0-7 核
```

### 3.4 · 🦀 Rust 生态视角

Rust 实现 raytracer 的关键模式:

**Scene 共享**(后续多线程用):

```rust
use std::sync::Arc;

let scene = Arc::new(scene);  // 原子引用计数,线程安全
// 每个线程 clone 一份 Arc(只增加引用计数,不复制数据)
```

**trait-based 几何**(支持多种相交):

```rust
trait Hittable {
    fn intersect(&self, ray: &Ray) -> Option<HitRecord>;
}

struct HitRecord {
    t: f32,
    point: Vec3,
    normal: Vec3,
    material: Arc<dyn Material>,  // 材质 trait object
}

struct Sphere { center: Vec3, radius: f32, material: Arc<dyn Material> }
struct Plane { point: Vec3, normal: Vec3, material: Arc<dyn Material> }
struct Triangle { v0: Vec3, v1: Vec3, v2: Vec3, material: Arc<dyn Material> }

impl Hittable for Sphere { /* ... */ }
impl Hittable for Plane { /* ... */ }
impl Hittable for Triangle { /* ... */ }

struct Scene {
    objects: Vec<Box<dyn Hittable>>,  // 异质列表
}
```

**`Box<dyn Hittable>`** 是 trait object——运行时多态。每个 object 是堆上的不同类型(Sphere / Plane / Triangle),通过 vtable 调用 intersect。

**性能注意**:trait object 有 vtable 开销。生产 raytracer 用 **enum**(编译时多态):

```rust
enum Shape {
    Sphere { center: Vec3, radius: f32 },
    Plane { point: Vec3, normal: Vec3 },
    Triangle { v0: Vec3, v1: Vec3, v2: Vec3 },
}

impl Shape {
    fn intersect(&self, ray: &Ray) -> Option<HitRecord> {
        match self {
            Shape::Sphere { center, radius } => sphere_intersect(*center, *radius, ray),
            Shape::Plane { point, normal } => plane_intersect(*point, *normal, ray),
            Shape::Triangle { v0, v1, v2 } => triangle_intersect(*v0, *v1, *v2, ray),
        }
    }
}
```

`enum` 的 `match` 编译时展开,**无 vtable 开销**,SIMD 友好。**Casey 在 Handmade Ray 用 enum-like 做法**(C 用 tagged union)。

### 3.5 · 🔢 数学视角:坐标系与变换

光线追踪的标准坐标系:

- **右手坐标系(RHS)**:x 右、y 上、z **向后**(相机看向 -z)
- **左手坐标系(LHS)**(DirectX):x 右、y 上、z **向前**(相机看向 +z)

**右手** vs **左手**:区别在 z 方向。**RHS 是图形学/物理标准**(OpenGL、PBRT、glam 用 RHS)。**LHS 是 DirectX 历史包袱**。

**叉积方向**:右手系下,`forward × up = right`(不是 `up × forward`)。具体:

```
forward × up = (forward.y * up.z - forward.z * up.y,
                forward.z * up.x - forward.x * up.z,
                forward.x * up.y - forward.y * up.x)
```

记忆:**右手定则**——食指 forward,中指 up,大拇指 right。

**矩阵** vs **ray generation**:

光栅化用 4×4 矩阵,因为:
- 模型变换:平移、旋转、缩放(需要 4×4 才能表示平移)
- 视图变换:相机变换
- 投影:透视除法(z 除法)

光线追踪用 ray generation,因为:
- 不需要"变换所有顶点"
- 直接从屏幕像素反推世界射线
- 矩阵对单个像素反推是 overkill

**数学等价性**:`ray.direction = forward + right * u + up * v` 等价于 `inverse(view_proj) * vec4(u, v, -1, 1)`。两者给出同一条射线。

## 4 · 认知地图

### 4.1 上级

- **光照模型** — Lambert / Phong / Blinn-Phong / PBR / Cook-Torrance
- **相机模型** — pinhole / thin lens / orthographic
- **抗锯齿(Antialiasing)** — SSAA / MSAA / FXAA / TAA
- **阴影算法** — shadow ray / shadow map / shadow volume

### 4.2 同级(并行方案)

| 方案 | 关键差别 | 何时用 | 本项目选了哪个 |
|---|---|---|---|
| Lambert 漫反射 | 无 specular | 哑光材质 | ✅ ray01 |
| Phong 模型 | 加 specular | 一般材质 | ray02 |
| Blinn-Phong | half-vector 优化 | 实时渲染 | HH 后期 |
| PBR(Cook-Torrance) | 物理正确 | 现代渲染器 | ray04 触及 |
| Look-from / Look-at | 直观 | ray tracer | ✅ ray01 |
| Euler angles(俯仰偏航) | 紧凑 | FPS 相机 | HH 主剧用 |
| Quaternion | 无万向锁 | 动画 | HH 不用 |

### 4.3 下级

- **Vec3 / Ray / Camera 数据结构** — 类型
- **Ray-Sphere 相交** — 二次方程
- **法线计算** — 球面、平面、三角形
- **Lambert 公式** — `max(0, N · L)`
- **阴影射线** — 阻挡测试
- **SSAA** — 亚像素采样
- **trait / enum 设计** — Rust 多态模式

## 5 · 对照与变奏

### 光栅化 MVP vs 光线追踪 ray generation

| 步骤 | 光栅化 | 光线追踪 |
|---|---|---|
| 几何变换 | vertex shader 用 MVP 变换所有顶点 | 不变换(直接世界空间) |
| 像素生成 | 三角形扫描线填充 | 每像素发射射线 |
| 投影 | 透视除法 | ray direction |
| 法线 | vertex normal 插值 | 直接从相交计算 |
| 光照 | fragment shader | ray 颜色计算 |
| 阴影 | 第二次渲染(shadow map) | 阴影射线 |

**核心等价**:两者都解决"3D → 2D"问题,但**方向不同**。光栅化是"3D 物体 → 2D 像素"(push),光线追踪是"2D 像素 → 3D 物体"(pull)。**Pull 模型支持递归**,这是光线追踪的根本优势。

### SSAA vs MSAA

| | SSAA | MSAA(Multi-Sample AA) |
|---|---|---|
| 采样数 | 每像素 N×N 全采样 | 每像素 N 次,**只在边缘** |
| 计算量 | N² 倍 | N 倍 |
| 何时用 | 离线 / 教学 | 实时渲染(主流 GPU) |
| 视觉质量 | 最好 | 好 |

**SSAA** 把每个像素当 N×N 个亚像素,每个亚像素都跑完整 ray tracer。**MSAA** 只在几何边缘处多次采样,内部还是 1 次。**MSAA 是 SSAA 的优化版**——大部分像素不需要多次采样。

光线追踪用 **SSAA / 分布式光线追踪**——因为光线追踪没有"边缘像素"概念,每个像素都一样。MSAA 是 GPU 光栅化的产物。

### 历史演化

- **1968 Appel**:第一个 raycasting(光线投射,无递归)
- **1979 Whitted**:递归 ray tracing(反射、折射)
- **1984 Cook**:分布式光线追踪(SSAA + 软阴影 + 景深)
- **1986 Kajiya**:路径追踪(Monte Carlo GI)
- **2018+ RTX**:GPU 实时光线追踪

**ray01 主要在 1968 Appel 阶段**——raycasting + Lambert + 阴影。**ray04 接近 1984 Cook**——分布式采样。完整 path tracing(1986 Kajiya)在主剧 Phase 8。

## 6 · 关联

- **铺垫**:
  - [ray00.md](ray00.md) — 光线追踪入门(raycaster 基础)
  - [../phase-0/14-math-foundations.md](../phase-0/14-math-foundations.md) — 向量数学
  - [../phase-2/day041.md](../phase-2/day041.md) — Lambert 余弦定律的直觉
- **当天**:ray01 — 基本 raytracer(光照、阴影、SSAA)
- **后续**:
  - [ray02.md](ray02.md) — 平面、Phong 光照(加 specular)
  - [ray03.md](ray03.md) — 材质系统(金属、玻璃)
  - [ray04.md](ray04.md) — 反射、抗锯齿
  - 主剧 [../phase-6/day261.md](../phase-6/day261.md) — 深度缓冲(光栅化对应物)

## 7 · 变式训练

### Lv1 · 概念辨析

**题**:Lambert 漫反射公式 `max(0, N · L)` 里的 `max(0, ...)` 为什么必要?如果去掉会怎样?

**参考解答**:

`N · L` 可能是负数(光在表面背面)。如果不去掉负数:

```
final = surface_color × light_intensity × (N · L)
```

光在背面时,`(N · L) < 0`,`final < 0`(负数)。负数颜色**物理上无意义**——光不能"反吸收"。在数学上,负数会**减去其他光源的贡献**,得到错误的总光量。

`max(0, ...)` 是"光不能从背面照过来"的物理表达。去掉会导致:
1. 背面颜色变成负数,转换 u8 时溢出(下溢到 255 或 0)
2. 多光源叠加时,负值抵消正值,总光量错误
3. 物理上不正确

**所有漫反射光照都要 max(0, ...)**,这是 CG 的"常识"。

### Lv2 · 动手实践

**题**:扩展 ray00 的代码,加:
1. Lambert 漫反射光照(光源在 (5, 5, 0))
2. 阴影射线
3. SSAA 4 samples

完成标准:渲染出三个球,每个球有明暗渐变(高光在光源方向),球之间互相投射阴影,边缘锯齿明显减少。

**参考解答**(只列关键改动,基于 ray00 代码):

```rust
#[derive(Clone)]
struct Sphere {
    center: Vec3,
    radius: f32,
    color: Color,
}

// 加 HitRecord(返回比 t 更丰富的信息)
struct HitRecord {
    t: f32,
    point: Vec3,
    normal: Vec3,
}

impl Sphere {
    fn intersect(&self, ray: &Ray) -> Option<HitRecord> {
        let oc = ray.origin - self.center;
        let half_b = oc.dot(ray.direction);
        let c = oc.dot(oc) - self.radius * self.radius;
        let discriminant = half_b * half_b - c;
        if discriminant < 0.0 {
            return None;
        }
        let sqrt_d = discriminant.sqrt();
        let t = (-half_b - sqrt_d).max(-half_b + sqrt_d);  // 选正的最小
        if t <= 0.001 {
            return None;
        }
        let point = ray.at(t);
        let normal = (point - self.center).normalize();
        Some(HitRecord { t, point, normal })
    }
}

struct Light {
    position: Vec3,
    color: Color,
}

fn in_shadow(point: Vec3, light_pos: Vec3, scene: &Scene) -> bool {
    let to_light = light_pos - point;
    let distance = to_light.length();
    let direction = to_light / distance;
    // offset 防自相交
    let shadow_ray = Ray { origin: point + direction * 0.001, direction };
    for obj in &scene.objects {
        if obj.intersect(&shadow_ray).is_some() {
            // 注意:这里 intersect 已经返回最近 t,但我们只关心"是否在 distance 内有遮挡"
            return true;
        }
    }
    false
}

fn ray_cast_with_lighting(ray: &Ray, scene: &Scene, light: &Light) -> Color {
    let mut closest = Option::<(HitRecord, Color)>::None;
    for obj in &scene.objects {
        if let Some(hit) = obj.intersect(ray) {
            if closest.is_none() || hit.t < closest.as_ref().unwrap().0.t {
                closest = Some((hit, obj.color));
            }
        }
    }

    if let Some((hit, color)) = closest {
        // Lambert 漫反射
        let to_light = (light.position - hit.point).normalize();
        let n_dot_l = hit.normal.dot(to_light).max(0.0);

        // 阴影检查
        let in_shadow = in_shadow(hit.point, light.position, scene);

        let ambient = 0.1;
        let diffuse = if in_shadow { 0.0 } else { n_dot_l };
        let light_factor = ambient + diffuse * (1.0 - ambient);

        color * light_factor
    } else {
        // 背景渐变
        let t = 0.5 * (ray.direction.y + 1.0);
        vec3(0.3, 0.5, 1.0).lerp(vec3(1.0, 1.0, 1.0), t)
    }
}

fn render_ssaa(scene: &Scene, camera: &Camera, light: &Light, samples: u32) -> Vec<u8> {
    let sqrt_samples = (samples as f32).sqrt() as u32;
    let mut framebuffer = vec![0u8; (camera.width * camera.height * 3) as usize];

    for y in 0..camera.height {
        for x in 0..camera.width {
            let mut color = Color::ZERO;
            for sy in 0..sqrt_samples {
                for sx in 0..sqrt_samples {
                    let sub_x = x as f32 + (sx as f32 + 0.5) / sqrt_samples as f32;
                    let sub_y = y as f32 + (sy as f32 + 0.5) / sqrt_samples as f32;
                    let ray = camera.ray_for_subpixel(sub_x, sub_y);
                    color += ray_cast_with_lighting(&ray, scene, light);
                }
            }
            color /= samples as f32;

            let i = (y * camera.width + x) as usize * 3;
            framebuffer[i] = (color.x.clamp(0.0, 1.0) * 255.0) as u8;
            framebuffer[i + 1] = (color.y.clamp(0.0, 1.0) * 255.0) as u8;
            framebuffer[i + 2] = (color.z.clamp(0.0, 1.0) * 255.0) as u8;
        }
    }
    framebuffer
}
```

`Camera::ray_for_subpixel` 是 ray00 `ray_for_pixel` 的连续版(参数是 f32)。

### Lv3 · 迁移设计

**题**:你被要求做一个**正交相机**(orthographic camera),所有射线方向相同(不像透视相机从同一点发散)。射线如何生成?和透视相机相比,渲染结果有什么视觉差别?

**提示**:
- 正交:每像素射线方向 = forward(固定),起点 = eye + right * u + up * v
- 用途:CAD / 2D 游戏 / 美术风格游戏
- 视觉:没有"近大远小",所有物体大小一样

### Lv4 · 开源贡献

**题**:`Ray Tracing in One Weekend`(Peter Shirley)是经典教学 ray tracer,有 Rust 移植版。

1. 在 GitHub 找 Rust 移植:`gh search repos "ray tracing in one weekend rust"`
2. clone 一两个,读源码
3. **可能的贡献方向**:
   - 加 doc 改进
   - 加测试覆盖
   - 加新 primitive(三角形、立方体)
   - 加 SIMD 优化(对应 Casey ray03)
4. 写 PR 描述

## 8 · Rust / Arch 落地代码

### 完整 raytracer(Lambert + 阴影 + SSAA)

下面是 ray01 完整可跑代码(在 ray00 基础上加光照):

```rust
// Cargo.toml 同 ray00

use glam::{Vec3, vec3};
use indicatif::{ProgressBar, ProgressStyle};
use std::time::Instant;

type Color = Vec3;

#[derive(Copy, Clone, Debug)]
struct Ray {
    origin: Vec3,
    direction: Vec3,
}

impl Ray {
    fn at(&self, t: f32) -> Vec3 {
        self.origin + self.direction * t
    }
}

#[derive(Clone)]
struct Sphere {
    center: Vec3,
    radius: f32,
    color: Color,
}

#[derive(Clone, Debug)]
struct HitRecord {
    t: f32,
    point: Vec3,
    normal: Vec3,
}

impl Sphere {
    fn intersect(&self, ray: &Ray) -> Option<HitRecord> {
        let oc = ray.origin - self.center;
        let half_b = oc.dot(ray.direction);
        let c = oc.dot(oc) - self.radius * self.radius;
        let discriminant = half_b * half_b - c;
        if discriminant < 0.0 {
            return None;
        }
        let sqrt_d = discriminant.sqrt();
        // 选最小的正 t
        let t = if -half_b - sqrt_d > 0.001 {
            -half_b - sqrt_d
        } else if -half_b + sqrt_d > 0.001 {
            -half_b + sqrt_d
        } else {
            return None;
        };
        let point = ray.at(t);
        let normal = (point - self.center).normalize();
        Some(HitRecord { t, point, normal })
    }
}

struct Scene {
    objects: Vec<Sphere>,
}

struct Light {
    position: Vec3,
    color: Color,
}

struct Camera {
    look_from: Vec3,
    forward: Vec3,
    right: Vec3,
    up: Vec3,
    half_width: f32,
    half_height: f32,
    width: u32,
    height: u32,
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

    fn ray_for_subpixel(&self, x: f32, y: f32) -> Ray {
        let u = (2.0 * x / self.width as f32 - 1.0) * self.half_width;
        let v = (1.0 - 2.0 * y / self.height as f32) * self.half_height;
        let direction = (self.forward + self.right * u + self.up * v).normalize();
        Ray { origin: self.look_from, direction }
    }
}

fn find_closest_hit(ray: &Ray, scene: &Scene) -> Option<(HitRecord, Color)> {
    let mut closest: Option<(HitRecord, Color)> = None;
    for obj in &scene.objects {
        if let Some(hit) = obj.intersect(ray) {
            if closest.is_none() || hit.t < closest.as_ref().unwrap().0.t {
                closest = Some((hit, obj.color));
            }
        }
    }
    closest
}

fn in_shadow(point: Vec3, light_pos: Vec3, scene: &Scene) -> bool {
    let to_light = light_pos - point;
    let distance = to_light.length();
    let direction = to_light / distance;
    let shadow_ray = Ray { origin: point + direction * 0.001, direction };

    for obj in &scene.objects {
        if let Some(hit) = obj.intersect(&shadow_ray) {
            if hit.t < distance {
                return true;
            }
        }
    }
    false
}

fn ray_cast(ray: &Ray, scene: &Scene, light: &Light) -> Color {
    if let Some((hit, color)) = find_closest_hit(ray, scene) {
        // Lambert
        let to_light = (light.position - hit.point).normalize();
        let n_dot_l = hit.normal.dot(to_light).max(0.0);
        let shadowed = in_shadow(hit.point, light.position, scene);
        let ambient = 0.1;
        let diffuse = if shadowed { 0.0 } else { n_dot_l };
        let factor = ambient + diffuse * (1.0 - ambient);
        color * light.color * factor
    } else {
        // 背景渐变
        let t = 0.5 * (ray.direction.y + 1.0);
        vec3(0.3, 0.5, 1.0).lerp(vec3(1.0, 1.0, 1.0), t)
    }
}

fn render(scene: &Scene, camera: &Camera, light: &Light, samples_per_pixel: u32) -> Vec<u8> {
    let sqrt_spp = (samples_per_pixel as f32).sqrt() as u32;
    let total = (camera.width * camera.height) as u64;
    let progress = ProgressBar::new(total);
    progress.set_style(ProgressStyle::default_bar()
        .template("{wide_bar} {pos}/{len} ({eta})").unwrap());

    let mut fb = vec![0u8; (camera.width * camera.height * 3) as usize];

    for y in 0..camera.height {
        for x in 0..camera.width {
            let mut color_sum = Color::ZERO;
            for sy in 0..sqrt_spp {
                for sx in 0..sqrt_spp {
                    let sub_x = x as f32 + (sx as f32 + 0.5) / sqrt_spp as f32;
                    let sub_y = y as f32 + (sy as f32 + 0.5) / sqrt_spp as f32;
                    let ray = camera.ray_for_subpixel(sub_x, sub_y);
                    color_sum += ray_cast(&ray, scene, light);
                }
            }
            let color = color_sum / (sqrt_spp * sqrt_spp) as f32;

            let i = (y * camera.width + x) as usize * 3;
            fb[i] = (color.x.clamp(0.0, 1.0) * 255.0) as u8;
            fb[i + 1] = (color.y.clamp(0.0, 1.0) * 255.0) as u8;
            fb[i + 2] = (color.z.clamp(0.0, 1.0) * 255.0) as u8;

            progress.inc(1);
        }
    }
    progress.finish();
    fb
}

fn main() {
    let scene = Scene {
        objects: vec![
            Sphere { center: vec3(0.0, 0.0, -5.0), radius: 1.0, color: vec3(0.2, 0.8, 0.2) },
            Sphere { center: vec3(-2.0, 0.0, -7.0), radius: 0.7, color: vec3(0.8, 0.2, 0.2) },
            Sphere { center: vec3(2.0, 0.0, -6.0), radius: 0.5, color: vec3(0.2, 0.2, 0.8) },
            Sphere { center: vec3(0.0, -101.0, -5.0), radius: 100.0, color: vec3(0.5, 0.5, 0.5) },  // 地面
        ],
    };
    let light = Light {
        position: vec3(5.0, 5.0, 0.0),
        color: vec3(1.0, 1.0, 1.0),
    };
    let camera = Camera::new(
        vec3(0.0, 1.0, 0.0),
        vec3(0.0, 0.0, -5.0),
        vec3(0.0, 1.0, 0.0),
        60.0,
        800, 600,
    );

    let start = Instant::now();
    let fb = render(&scene, &camera, &light, 4);  // 4 samples per pixel
    println!("Render: {:?}", start.elapsed());

    image::save_buffer("output.png", &fb, 800, 600, image::ExtendedColorType::Rgb8).unwrap();
}
```

### Arch Linux 命令

```bash
# 1. 编译运行
cd ~/src/handmade-ray
cargo run --release
# 输出:
# Render: 230ms  (4 samples,800x600)
# Saved output.png

# 2. 查看
eog output.png &

# 3. 性能对比:1 sample vs 4 samples vs 16 samples
# 改 samples_per_pixel 参数,跑三次,记录时间

# 4. SIMD 验证
cargo rustc --release -- --emit asm --target-cpu native
find target/release/deps/ -name "*.s" | head -1 | xargs grep -E "(mulps|addps)" | wc -l
# 应该看到大量 SIMD 指令

# 5. Cache miss
sudo pacman -S perf
perf stat -e cache-misses,cache-references ./target/release/handmade-ray
# 看 cache miss 比例

# 6. flamegraph
cargo flamegraph --bin handmade-ray --release
# 看 ray_cast / Sphere::intersect / in_shadow 占比

# 7. 对比 glam vs 手写 Vec3
# 写两个版本对比性能
hyperfine --runs 5 './target/release/glam_version'
hyperfine --runs 5 './target/release/handwritten_version'
# glam 版本应该快 10-30%(SIMD 优化)
```

**Troubleshooting**:

- 球的明暗反了:检查 `normal` 方向,应该指向**球外**(从球心指向交点)。
- 阴影方向错:检查 `in_shadow` 的 `direction` 和 `distance`,应该从交点指向光源。
- 阴影看不到:光源距离太远或角度不对,改光源位置到 (5, 5, 0) 或 (5, 5, -3)。
- 性能慢:samples 太多,降到 1 或 2。
- 颜色饱和:`clamp(0.0, 1.0)` 防止溢出,但更好做法是 **tone mapping**(ray04 讲)。

## 9 · 延伸阅读(可选补充,非必需)

本仓库本地:
- [ray00.md](ray00.md) — 光线追踪入门
- [ray02.md](ray02.md) — 下一集(平面、Phong)
- [../phase-0/14-math-foundations.md](../phase-0/14-math-foundations.md) — 数学基础

外部稳定 URL(可选):
- Ray Tracing in One Weekend 第 4-6 章:https://raytracing.github.io/books/RayTracingInOneWeekend.html
- Scratchapixel Ray-Plane / Ray-Sphere 相交:https://www.scratchapixel.com/lessons/3d-basic-rendering/minimal-ray-tracer-rendering-simple-shapes
- LearnOpenGL Basic Lighting: https://learnopengl.com/Lighting/Basic-Lighting
- glam Camera Look-At: https://docs.rs/glam/latest/glam/f32/struct.Mat4.html#method.look_at_rh

真实开源源码:
- Rust RT in One Weekend: https://github.com/lenzjr/raytracing-rs
- glam Mat4 look_at: https://github.com/bitshifter/glam/blob/main/src/f32/mat4.rs
