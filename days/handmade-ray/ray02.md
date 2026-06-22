---
episode: 02
series: handmade-ray
title_en: "More Primitives and Shading Basics"
title_zh: "更多原始体与着色基础"
type: coding
difficulty: 3
duration: "2-3h"
hh_url: "https://guide.handmadehero.org/ray/ray00/"
domains: [graphics, math, rust]
prereqs: ["ray01"]
---

# ray02 · 更多原始体与着色基础

> ray01 你有了球体 + Lambert 光照。但场景里**只有球**——你画不出地板、墙壁、棋盘格。今天我们**加更多几何**:平面(地板/墙)、三角形(任意形状)、矩形(门窗)。同时**升级光照**:加 Phong specular(让物体有高光斑),加多光源(主光 + 辅光 + 半球环境光)。这一集让你的场景从"几个球"变成"一个房间"——有地板、有墙、有物体,有完整光照。

## 0 · 为什么要有这一天

回到 ray01 的画面:三个球漂浮在空中,有一个看不见的"地板"(其实是大球的上半部分),渐变背景。**画面仍然抽象**——不像真实场景。

真实场景需要:
- **地板**(平面):房间地面、户外草地
- **墙**(平面 / 矩形):房间的四面墙
- **棋盘格**(矩形 + 程序化颜色):经典地面
- **三角形**(任意几何):桌子、椅子、岩石、角色

ray01 只有 Sphere,**画不出这些**。今天我们加 Plane(平面)、Triangle(三角形)、Rectangle(矩形,用两个三角形组成或独立算法)。

光照也要升级:
- ray01 只有 **Lambert 漫反射**——所有物体都是哑光的,没有高光
- 真实物体有 **Phong specular**——金属、塑料、玻璃有高光斑
- 真实场景有 **多光源**——主光 + 辅光 + 半球光

**Phong specular** 公式:

```
specular = specular_color × (R · V)^n
```

- `R = reflect(-L, N)` — 入射光 L 关于法线 N 的反射方向
- `V` — 视线方向(从交点到相机)
- `n` — shininess(镜面指数,越大高光越锐)
- `R · V` 大 → 视线接近反射方向 → 高光强

**反射公式**(ray00 / day041 提到):

```
reflect(L, N) = L - 2 * (L · N) * N
```

**多光源**:每个光源独立算 diffuse 和 specular,累加。每加一个光源要**多算一次** N · L 和 R · V。

**半球环境光**(Hemispheric Ambient):不是常数,而是**上半球一种颜色(天空蓝),下半球另一种颜色(地面棕)**,根据法线 y 分量插值。这模拟"环境光其实是从四面八方来的光,上半球多下半球少"。

为什么这一集重要?因为**任何渲染场景都需要多种几何和光照**。光栅化用 vertex buffer + index buffer 描述几何,光线追踪用 enum / trait 描述。**学懂多种相交算法,你以后看任何渲染器都能秒理解**——PBRT / Mitsuba / Cycles 都用类似抽象。

心理锚点:今天之后,你能:(1) 实现 Ray-Plane、Ray-Triangle(Möller-Trumbore)相交;(2) 写 Phong 光照(diffuse + specular);(3) 支持多光源叠加;(4) 实现半球环境光,让暗部有真实感;(5) 写棋盘格 procedural shader(基于位置的程序化颜色)。

## 1 · Casey 今天做了什么(Handmade Ray 脉络)

Casey 在 Handmade Ray 这部分主要做的:

1. **抽象 Hittable trait**:把 Sphere 升级到 trait,所有几何(Sphere、Plane、Triangle)实现同一接口。这对应 ray01 §3.4 提到的 Rust 设计模式。

2. **加 Plane**:平面相交算法最简单——把射线方程代入平面方程,解一个线性方程。

3. **加 Triangle**(Möller-Trumbore 算法):三角形相交的标准算法,1997 年 Möller 和 Trumbore 提出。计算量小(几十条浮点指令),GPU / CPU 都用。

4. **加 Phong specular**:在 ray01 的 Lambert 基础上加 specular 项,物体有高光。

5. **加棋盘格地板**:程序化纹理——根据 hit point 的 (x, z) 坐标计算颜色,生成黑白棋盘。

到 ray02 结束,场景有:房间(地板 + 墙)、多个物体(球 + 三角形)、Phong 光照、棋盘格地板。**画面看起来像真实场景**。

## 2 · 心智模型

### 类比:几何是"演员",着色是"化妆"

raytracer 渲染一帧画面,分两步:

1. **几何步**:射线和场景里的"演员"(物体)相交,找出"这个像素看到哪个演员的哪个部位"。
2. **着色步**:在相交点给"演员化妆"——算光照、加高光、决定颜色。

ray00 / ray01 的演员只有球,**每个演员化妆简单**(纯色 / Lambert)。ray02 加更多演员(平面、三角形),**化妆也升级**(Phong、棋盘格)。

**核心抽象**:`Hittable` trait 让所有演员说同一种语言——`intersect(ray) -> Option<HitRecord>`。每种几何的 intersect 算法不同(球是二次方程,平面是线性,三角形是重心坐标),但对外接口统一。

### 严谨原理:几何相交算法

#### 2.1 Ray-Plane 相交

**平面定义**:一个点 P0 和法线 N。平面上任意点 P 满足 `(P - P0) · N = 0`(P - P0 垂直于 N)。

代入射线方程 `P = ray.origin + t * ray.direction`:

```
(ray.origin + t * ray.direction - P0) · N = 0
t * (ray.direction · N) = (P0 - ray.origin) · N
t = (P0 - ray.origin) · N / (ray.direction · N)
```

**关键**:
- 如果 `ray.direction · N == 0`,射线和平面平行,**不相交**
- 如果 `ray.direction · N > 0`,射线从平面背面射来(平面法线指向"外侧",射线和法线同向 = 背面)
- 通常我们要求 `ray.direction · N < 0`,射线**从正面**撞平面

```rust
struct Plane {
    point: Vec3,
    normal: Vec3,
    color: Color,
}

impl Plane {
    fn intersect(&self, ray: &Ray) -> Option<HitRecord> {
        let denom = ray.direction.dot(self.normal);
        if denom.abs() < 1e-6 {
            return None;  // 平行
        }
        let t = (self.point - ray.origin).dot(self.normal) / denom;
        if t > 0.001 {
            let point = ray.at(t);
            // 法线方向:如果射线从背面来,翻转法线(让我们看到的面有正确法线)
            let normal = if denom < 0.0 { self.normal } else { -self.normal };
            Some(HitRecord { t, point, normal })
        } else {
            None
        }
    }
}
```

**法线翻转**:`denom = ray.direction · normal`,如果 `denom < 0`,射线**迎着法线**(从正面来);`denom > 0` 射线**和法线同向**(从背面来)。背面来时翻转法线,保证 `normal` 总是指向射线来的方向,后续光照计算正确。

#### 2.2 Ray-Triangle 相交(Möller-Trumbore)

三角形是 3 个顶点 V0、V1、V2。射线方程:`P = O + t * D`。三角形内任意点用重心坐标:`P = V0 + u * (V1 - V0) + v * (V2 - V0)`,`u ≥ 0, v ≥ 0, u + v ≤ 1`。

**Möller-Trumbore 算法**(1997):

```rust
impl Triangle {
    fn intersect(&self, ray: &Ray) -> Option<HitRecord> {
        let edge1 = self.v1 - self.v0;
        let edge2 = self.v2 - self.v0;
        let h = ray.direction.cross(edge2);
        let a = edge1.dot(h);
        if a.abs() < 1e-6 {
            return None;  // 射线平行三角形
        }
        let f = 1.0 / a;
        let s = ray.origin - self.v0;
        let u = f * s.dot(h);
        if u < 0.0 || u > 1.0 {
            return None;  // 三角形外
        }
        let q = s.cross(edge1);
        let v = f * ray.direction.dot(q);
        if v < 0.0 || u + v > 1.0 {
            return None;  // 三角形外
        }
        let t = f * edge2.dot(q);
        if t > 0.001 {
            let point = ray.at(t);
            let normal = edge1.cross(edge2).normalize();
            // 法线翻转(同 Plane)
            let normal = if normal.dot(ray.direction) < 0.0 { normal } else { -normal };
            Some(HitRecord { t, point, normal })
        } else {
            None
        }
    }
}
```

**算法核心**:
- `edge1 × edge2` 给出三角形法线
- 重心坐标 (u, v) 决定交点是否在三角形内
- 一行串乘 + 点积,~50 条浮点指令,极快

**为什么 Möller-Trumbore 流行**?因为它**不需要预计算法线**(每次直接算),且**计算量小**。GPU 上是标准。

#### 2.3 Ray-AABB 相交(轴对齐包围盒)

AABB(Axis-Aligned Bounding Box)是"轴对齐的长方体",常用作加速结构(BVH、K-d tree)的节点。Ray-AABB 用 **Slab Method**:

```rust
struct Aabb {
    min: Vec3,
    max: Vec3,
}

impl Aabb {
    fn intersect(&self, ray: &Ray) -> Option<(f32, f32)> {
        let mut t_min = f32::NEG_INFINITY;
        let mut t_max = f32::INFINITY;

        for i in 0..3 {  // 对每个轴 x, y, z
            let inv_d = 1.0 / ray.direction[i];
            let mut t0 = (self.min[i] - ray.origin[i]) * inv_d;
            let mut t1 = (self.max[i] - ray.origin[i]) * inv_d;
            if inv_d < 0.0 {
                std::mem::swap(&mut t0, &mut t1);
            }
            t_min = t_min.max(t0);
            t_max = t_max.min(t1);
            if t_min > t_max {
                return None;  // 不相交
            }
        }
        Some((t_min, t_max))
    }
}
```

**核心思想**:对每个轴算"射线进入这个轴的 slab(平面)"的 t 区间,三个轴的区间**相交**就是射线在 AABB 内的 t 区间。如果区间为空 → 不相交。

AABB 主要用于**加速结构**(BVH):大量物体时,先用 AABB 快速排除"明显不撞的物体",再做精确相交。Handmade Ray 不深入 BVH(留给主剧 Phase 8),但 ray03 会用 AABB 思路做 SIMD 优化。

### Phong 光照(加 specular)

```
final_color = ambient + Σ(diffuse_i + specular_i) for each light i

diffuse_i = surface_color × light_color_i × max(0, N · L_i)
specular_i = specular_color × light_color_i × max(0, R_i · V)^n

R_i = reflect(-L_i, N)  -- 入射光的反射方向
V = normalize(camera - hit_point)  -- 视线方向
n = shininess  -- 镜面指数
```

**reflect 公式**:

```rust
fn reflect(incident: Vec3, normal: Vec3) -> Vec3 {
    incident - 2.0 * incident.dot(normal) * normal
}
```

**注意**:这里 `incident` 是"光射来的方向"(指向交点),不是"指向光源的方向"。`R_i = reflect(-L_i, N)`,`L_i` 是指向光源的方向,`-L_i` 是光射来的方向。

**shininess 参数**(n):
- n = 2:大圆斑(塑料哑光)
- n = 32:中亮斑(塑料光面)
- n = 128:小亮斑(金属)
- n = 1024:极锐亮斑(镜面)

### 多光源叠加

```rust
fn ray_cast_multi_light(ray: &Ray, scene: &Scene, lights: &[Light], ambient: Color) -> Color {
    if let Some((hit, material)) = find_closest_hit(ray, scene) {
        let n = hit.normal;
        let v = -ray.direction;  // 视线方向(指向相机,因为 ray 从相机射出)

        let mut total_color = ambient;  // 环境光

        for light in lights {
            let l = (light.position - hit.point).normalize();
            let n_dot_l = n.dot(l).max(0.0);
            if n_dot_l == 0.0 {
                continue;  // 光在背面
            }

            // 阴影检查
            if in_shadow(hit.point, light.position, scene) {
                continue;
            }

            // Diffuse
            let diffuse = material.color * light.color * n_dot_l;

            // Specular
            let r = reflect(-l, n);
            let r_dot_v = r.dot(v).max(0.0);
            let specular = material.specular_color * light.color * r_dot_v.powf(material.shininess);

            total_color += diffuse + specular;
        }

        total_color
    } else {
        background(ray)
    }
}
```

**关键**:`v = -ray.direction`,因为 ray.direction 是从相机指向场景,视线方向是反过来(从场景指向相机)。

### 半球环境光

```
hemisphere_ambient = lerp(ground_color, sky_color, (N.y + 1) / 2)
```

N.y ∈ [-1, 1],映射到 [0, 1]:N 朝上(y=1) → 全用 sky_color;N 朝下(y=-1) → 全用 ground_color。

```rust
fn hemisphere_ambient(normal: Vec3, sky: Color, ground: Color) -> Color {
    let t = 0.5 + 0.5 * normal.y;  // [-1, 1] → [0, 1]
    sky.lerp(ground, 1.0 - t)  // 注意:t=1 时全 sky,t=0 时全 ground
}
```

**为什么半球环境光好**?因为真实世界的环境光**不是均匀**——上方天空明亮,下方地面较暗。半球环境光模拟这个,**比常数 ambient 真实**。

### 程序化棋盘格

```rust
fn checkerboard_color(point: Vec3, color1: Color, color2: Color, scale: f32) -> Color {
    let x = (point.x * scale).floor() as i32;
    let z = (point.z * scale).floor() as i32;
    if (x + z).rem_euclid(2) == 0 {
        color1
    } else {
        color2
    }
}
```

**核心**:`floor(point * scale)` 把世界坐标转成网格坐标,根据网格 (x + z) 的奇偶决定颜色。

**变种**:
- 麻木点 (point.x, point.y) → XY 平面棋盘格(墙面)
- 三维棋盘格:(x + y + z) 奇偶 → 体积棋盘格(大理石)
- 加 smoothstep 平滑边缘 → 抗锯齿棋盘格

## 3 · 四域深入

### 3.1 · 🎮 游戏编程视角

游戏开发里几何描述的标准:

| 表示 | 用途 | 优缺点 |
|---|---|---|
| 隐式几何(Implicit) | 球、平面、AABB | 数学公式,易相交,但难做复杂形状 |
| 显式几何(Explicit) | 三角形网格 | 灵活(任何形状),但相交复杂 |
| 程序化(Procedural) | 噪声、分形 | 无限细节,但参数难调 |
| 体积(Voxel) | MC、地形 | 易修改,但内存大 |
| CSG(Constructive Solid Geometry) | CAD | 易编辑,但渲染复杂 |

**主流游戏**:三角形网格 + skeletal animation。**Handmade Ray 用隐式 + 少量三角形**——教学简化。

**着色器(Shader)模式**:现代渲染把 Phong 写成 fragment shader,GPU 并行算每像素。Handmade Ray 在 CPU 上算,但 shader 思路一致——每像素 / 每交点独立算光照。

### 3.2 · 🎨 图形学视角

Phong vs Blinn-Phong:

**Phong**(原版):
```
specular = (R · V)^n
R = reflect(-L, N)  -- 反射方向(需要算)
```

**Blinn-Phong**(优化版):
```
specular = (N · H)^n
H = normalize(L + V)  -- half vector(中间方向,只需加法)
```

**为什么 Blinn 更好**?
1. **计算量小**:`H = (L + V) / |L + V|` 比 `R = reflect(-L, N)` 简单
2. **数值稳定**:R 计算涉及 `2 * dot`,精度损失;H 是简单加法
3. **视觉几乎一致**:n_Blinn ≈ 4 * n_Phong 给出类似高光

**主流 GPU 都用 Blinn-Phong**。Handmade Ray 用 Phong 因为更直观,ray04 可改成 Blinn。

**Phong 的局限**:
- 物理不正确(specular 可能比光源还亮)
- 不能表示菲涅尔效应(掠射时反射增强)
- 不能表示各向异性(刷毛金属)

**PBR**(Cook-Torrance)解决这些,但需要更多数学(微表面、菲涅尔、几何遮蔽)。**ray04 会触及**。

### 3.3 · 🐧 Linux 系统编程视角

Linux 上 triangle mesh 的标准格式:

- **OBJ**(Wavefront):文本格式,简单,广泛支持(Blender 默认导出)
- **glTF**(GL Transmission Format):JSON + 二进制 buffer,现代 Web/工业标准
- **FBX**(Autodesk):专有,游戏工业用
- **STL**(3D 打印):triangle soup,简单但冗余

**加载 OBJ 的 Rust crate**:

```toml
[dependencies]
obj = "0.10"  # 简单 OBJ 加载
tobj = "4.0"  # 更完整的 OBJ 加载
gltf = "1.4"  # glTF 加载
```

```rust
use tobj;

let (models, materials) = tobj::load_obj("model.obj", &tobj::LoadOptions::default())
    .unwrap();
for model in models {
    let mesh = &model.mesh;
    println!("Model {}: {} vertices, {} indices",
             model.name, mesh.positions.len() / 3, mesh.indices.len() / 3);
    // 把 positions 转成三角形列表
    for chunk in mesh.positions.chunks(9) {  // 3 vertices × 3 coords
        let v0 = Vec3::new(chunk[0], chunk[1], chunk[2]);
        let v1 = Vec3::new(chunk[3], chunk[4], chunk[5]);
        let v2 = Vec3::new(chunk[6], chunk[7], chunk[8]);
        // 加入 scene.objects
    }
}
```

### 3.4 · 🦀 Rust 生态视角

Hittable trait 的 Rust 设计:

```rust
trait Hittable: Send + Sync {  // 多线程用,需 Send + Sync
    fn intersect(&self, ray: &Ray) -> Option<HitRecord>;
    fn bounding_box(&self) -> Aabb;  // BVH 加速结构用
}

#[derive(Clone)]
enum Shape {
    Sphere { center: Vec3, radius: f32 },
    Plane { point: Vec3, normal: Vec3 },
    Triangle { v0: Vec3, v1: Vec3, v2: Vec3 },
}

impl Hittable for Shape {
    fn intersect(&self, ray: &Ray) -> Option<HitRecord> {
        match self {
            Shape::Sphere { center, radius } => sphere_intersect(*center, *radius, ray),
            Shape::Plane { point, normal } => plane_intersect(*point, *normal, ray),
            Shape::Triangle { v0, v1, v2 } => triangle_intersect(*v0, *v1, *v2, ray),
        }
    }
    fn bounding_box(&self) -> Aabb {
        match self {
            Shape::Sphere { center, radius } => Aabb {
                min: *center - Vec3::splat(*radius),
                max: *center + Vec3::splat(*radius),
            },
            // ...
        }
    }
}

struct Object {
    shape: Shape,
    material: Arc<dyn Material>,  // 材质分离,见 ray03
}

struct Scene {
    objects: Vec<Object>,
}
```

**enum vs trait object**:
- `enum`:编译时展开,match 高效,SIMD 友好,**生产用**
- `trait object (Box<dyn Hittable>)`:运行时多态,有 vtable 开销,但**可扩展**(第三方可加新几何)

Handmade Ray 用 enum(像 Casey C 版的 tagged union),Ray Tracing in One Weekend Rust 移植版用 trait object。两者都行,**enum 性能更好**。

### 3.5 · 🔢 数学视角

**重心坐标(Barycentric Coordinates)** 是三角形内的局部坐标系。三角形 V0V1V2 内任一点 P 可以写成:

```
P = α * V0 + β * V1 + γ * V2
α + β + γ = 1
α, β, γ ≥ 0  (在三角形内)
```

(α, β, γ) 是重心坐标。**Möller-Trumbore 算法的 u, v** 实际是 (β, γ),α = 1 - u - v。

**重心坐标的应用**:
- 相交测试:判断点是否在三角形内
- 插值:顶点属性(法线、颜色、UV)用 (α, β, γ) 加权平均
- 渲染:fragment shader 用重心坐标插值 vertex 属性

**Phong shading**(1975 Phong)就是用重心坐标插值法线,fragment 处算光照——**光栅化的核心技巧**。光线追踪中,因为相交直接得到法线,**不需要插值**,但重心坐标仍用于纹理坐标(uv)插值。

**光照的辐射度量**:
- Radiance L(W/sr/m²):单位立体角单位面积的光强
- Irradiance E(W/m²):单位面积的总入射光
- Intensity I(W/sr):点光源单位立体角的光强

Phong 模型不严格物理,只是工程近似。**PBR 严格物理**,但实现复杂(参考 ray04)。

## 4 · 认知地图

### 4.1 上级

- **几何表示** — Implicit / Explicit / Procedural / Voxel
- **光照模型** — Lambert / Phong / Blinn-Phong / PBR
- **加速结构** — BVH / K-d tree / Grid(ray03+ 触及)
- **材质模型** — Matte / Metal / Glass / Plastic(ray03 主角)

### 4.2 同级(并行方案)

| 方案 | 关键差别 | 何时用 | 本项目选了哪个 |
|---|---|---|---|
| Phong specular | 用 R · V | 教学 | ✅ ray02 |
| Blinn-Phong | 用 N · H | 主流实时 | ray04 可改 |
| Cook-Torrance | 微表面模型 | PBR | ray04 触及 |
| 多光源循环 | 每光源独立算 | 任何场景 | ✅ ray02 |
| Deferred shading | 先存 G-buffer 再算光照 | 多光源场景(光栅化) | 不适用 ray tracer |
| Light culling | 只算可见光源 | 性能优化 | HH 主剧用 |

### 4.3 下级

- **Ray-Sphere / Plane / Triangle / AABB 相交** — 几何算法
- **Möller-Trumbore 算法** — 三角形相交
- **Slab Method** — AABB 相交
- **重心坐标** — 三角形内插值
- **Phong / Blinn-Phong** — 光照模型
- **半球环境光** — 改进的 ambient
- **程序化纹理** — 棋盘格、噪声

## 5 · 对照与变奏

### 隐式 vs 显式几何

| | 隐式(Implicit) | 显式(Explicit) |
|---|---|---|
| 表示 | 数学公式 f(x,y,z) = 0 | 顶点列表 + 拓扑 |
| 例 | 球、平面、椭圆 | 三角形网格、quad mesh |
| 相交 | 解方程(快) | 遍历三角形(慢) |
| 法线 | 解析公式 | 顶点插值 |
| 形状限制 | 严格(只参数化形状) | 无限(任何形状) |
| 编辑 | 改参数 | 移动顶点 |

**Handmade Ray 用混合**:球和平面用隐式,任意形状用三角形。**工业渲染器同样**——CAD 用隐式曲面,游戏用三角形,两者在 ray tracer 里共存。

### Forward shading vs Deferred shading

| | Forward(前向着色) | Deferred(延迟着色) |
|---|---|---|
| 流程 | 每物体 → 像素 | 先存 G-buffer,后算光照 |
| 多光源开销 | O(objects × lights) | O(objects + pixels × lights) |
| 透明物体 | 直接支持 | 不支持(要 forward pass) |
| 用途 | 透明 / 少光源 | 多光源场景 |

**Forward** 是光线追踪天然模式(每交点算光照)。**Deferred** 是 GPU 光栅化的优化(把几何 pass 和光照 pass 分开,光照只算屏幕可见像素)。**Handmade Ray 用 Forward**。

### 历史演化

- **1975 Phong**:Phong 光照 + Phong shading
- **1977 Blinn**:Blinn-Phong 优化
- **1986 Cook-Torrance**:物理 BRDF
- **1997 Möller-Trumbore**:快速三角形相交
- **2010+ Disney Principled BRDF**:工业 PBR 标准
- **2020+ RTX + DLSS**:实时光线追踪 + AI 降噪

## 6 · 关联

- **铺垫**:
  - [ray01.md](ray01.md) — 基本 raytracer(Lambert + SSAA)
  - [../phase-2/day041.md](../phase-2/day041.md) — 游戏数学(反射、点积)
  - [../phase-2/day044.md](../phase-2/day044.md) — 反射向量
- **当天**:ray02 — 更多原始体 + Phong 光照
- **后续**:
  - [ray03.md](ray03.md) — 材质系统(金属、玻璃)
  - [ray04.md](ray04.md) — 反射、抗锯齿、BRDF
  - 主剧 [../phase-6/day275.md](../phase-6/day275.md) — 光照模型深入

## 7 · 变式训练

### Lv1 · 概念辨析

**题**:Möller-Trumbore 算法里,如果 `u + v > 1`,意味着什么?为什么这是"不相交"?

**参考解答**:

Möller-Trumbore 把三角形内任一点表示为 `P = V0 + u * edge1 + v * edge2`,其中 `edge1 = V1 - V0`,`edge2 = V2 - V0`。

**约束**:`u ≥ 0`(在 V0V1 边的 V2 一侧)、`v ≥ 0`(在 V0V2 边的 V1 一侧)、`u + v ≤ 1`(在 V1V2 边的 V0 一侧)。

这三个约束**定义三角形的内部**。如果 `u + v > 1`,交点在 **V1V2 边的"V0 反侧"**——即**三角形外**,虽然可能在 V0V1 和 V0V2 的延长线之间,但**已经超出三角形边界**。

类似地,`u < 0` 或 `v < 0` 也是三角形外。Möller-Trumbore 用这三个条件快速 reject,避免不必要的计算。

### Lv2 · 动手实践

**题**:在 ray01 基础上加:
1. Plane(地板)
2. Phong specular(给球加高光)
3. 棋盘格地板(平面颜色根据位置变化)
4. 第二个光源(辅光)

完成标准:画面有棋盘格地板、球有高光斑、双光源。

**参考解答**(关键代码):

```rust
#[derive(Clone)]
enum Shape {
    Sphere { center: Vec3, radius: f32 },
    Plane { point: Vec3, normal: Vec3 },
}

impl Shape {
    fn intersect(&self, ray: &Ray) -> Option<HitRecord> {
        match self {
            Shape::Sphere { center, radius } => sphere_intersect(*center, *radius, ray),
            Shape::Plane { point, normal } => plane_intersect(*point, *normal, ray),
        }
    }
}

fn plane_intersect(point: Vec3, normal: Vec3, ray: &Ray) -> Option<HitRecord> {
    let denom = ray.direction.dot(normal);
    if denom.abs() < 1e-6 {
        return None;
    }
    let t = (point - ray.origin).dot(normal) / denom;
    if t > 0.001 {
        let hit_point = ray.at(t);
        let n = if denom < 0.0 { normal } else { -normal };
        Some(HitRecord { t, point: hit_point, normal: n })
    } else {
        None
    }
}

struct Material {
    color: Color,
    specular_color: Color,
    shininess: f32,
}

fn checkerboard(point: Vec3, scale: f32, c1: Color, c2: Color) -> Color {
    let x = (point.x * scale).floor() as i32;
    let z = (point.z * scale).floor() as i32;
    if (x + z).rem_euclid(2) == 0 { c1 } else { c2 }
}

fn ray_cast_phong(ray: &Ray, scene: &Scene, lights: &[Light]) -> Color {
    let mut closest: Option<(HitRecord, &Object)> = None;
    for obj in &scene.objects {
        if let Some(hit) = obj.shape.intersect(ray) {
            if closest.is_none() || hit.t < closest.as_ref().unwrap().0.t {
                closest = Some((hit, obj));
            }
        }
    }
    let Some((hit, obj)) = closest else {
        let t = 0.5 * (ray.direction.y + 1.0);
        return vec3(0.3, 0.5, 1.0).lerp(vec3(1.0, 1.0, 1.0), t);
    };

    let mat = &obj.material;
    // 棋盘格:地板颜色按位置算
    let surface_color = match &obj.shape {
        Shape::Plane { .. } => checkerboard(hit.point, 0.5, vec3(0.9, 0.9, 0.9), vec3(0.1, 0.1, 0.1)),
        _ => mat.color,
    };

    let v = -ray.direction;  // 视线
    let mut total = vec3(0.05, 0.05, 0.06);  // ambient(冷色调)

    for light in lights {
        let l = (light.position - hit.point).normalize();
        let n_dot_l = hit.normal.dot(l).max(0.0);
        if n_dot_l == 0.0 {
            continue;
        }
        if in_shadow(hit.point, light.position, scene) {
            continue;
        }
        // Diffuse
        let diffuse = surface_color * light.color * n_dot_l;
        // Specular
        let r = reflect(-l, hit.normal);
        let r_dot_v = r.dot(v).max(0.0);
        let specular = mat.specular_color * light.color * r_dot_v.powf(mat.shininess);
        total += diffuse + specular;
    }
    total
}

fn reflect(l: Vec3, n: Vec3) -> Vec3 {
    l - 2.0 * l.dot(n) * n
}
```

主函数加 Plane:

```rust
let scene = Scene {
    objects: vec![
        Object {
            shape: Shape::Sphere { center: vec3(0.0, 0.0, -5.0), radius: 1.0 },
            material: Material {
                color: vec3(0.2, 0.8, 0.2),
                specular_color: vec3(1.0, 1.0, 1.0),
                shininess: 32.0,
            },
        },
        Object {
            shape: Shape::Plane { point: vec3(0.0, -1.0, 0.0), normal: vec3(0.0, 1.0, 0.0) },
            material: Material {
                color: vec3(0.5, 0.5, 0.5),
                specular_color: vec3(0.0, 0.0, 0.0),  // 地板无 specular
                shininess: 1.0,
            },
        },
    ],
};
let lights = vec![
    Light { position: vec3(5.0, 5.0, 0.0), color: vec3(1.0, 1.0, 1.0) },  // 主光
    Light { position: vec3(-3.0, 2.0, 0.0), color: vec3(0.3, 0.3, 0.4) },  // 辅光(冷)
];
```

### Lv3 · 迁移设计

**题**:你被要求做**程序化木纹纹理**——根据平面上的 (x, y) 坐标生成木纹颜色(深浅条纹 + 一点噪声扰动)。算法是什么?如何避免条纹过于规则?

**提示**:
- 基础:用 sin(x * frequency) 生成条纹
- 扰动:加 Perlin 噪声让条纹不完美
- 颜色映射:把 [0, 1] 值映射到木纹色板(深棕 → 浅棕)

### Lv4 · 开源贡献

**题**:`bvh` crate 是 Rust 的 BVH 实现(加速结构),GitHub: https://github.com/svenstaro/bvh

1. clone 仓库
2. 找 Ray-AABB / Ray-Triangle 实现
3. **可能的贡献方向**:
   - 加 doc 改进(解释算法选择)
   - 加测试(Möller-Trumbore 边界条件)
   - 加 SIMD 版本(对应 Casey ray03)
4. 写 PR 描述

## 8 · Rust / Arch 落地代码

### 完整 ray02 代码

```rust
// Cargo.toml:
// [dependencies]
// glam = "0.29"
// image = "0.25"
// indicatif = "0.17"

use glam::{Vec3, vec3};
use indicatif::{ProgressBar, ProgressStyle};

type Color = Vec3;

#[derive(Copy, Clone, Debug)]
struct Ray { origin: Vec3, direction: Vec3 }

impl Ray {
    fn at(&self, t: f32) -> Vec3 { self.origin + self.direction * t }
}

#[derive(Clone, Debug)]
struct HitRecord { t: f32, point: Vec3, normal: Vec3 }

#[derive(Clone)]
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

fn sphere_intersect(center: Vec3, radius: f32, ray: &Ray) -> Option<HitRecord> {
    let oc = ray.origin - center;
    let half_b = oc.dot(ray.direction);
    let c = oc.dot(oc) - radius * radius;
    let disc = half_b * half_b - c;
    if disc < 0.0 { return None; }
    let sqrt_d = disc.sqrt();
    let t = if -half_b - sqrt_d > 0.001 { -half_b - sqrt_d }
            else if -half_b + sqrt_d > 0.001 { -half_b + sqrt_d }
            else { return None; };
    let point = ray.at(t);
    let normal = (point - center).normalize();
    Some(HitRecord { t, point, normal })
}

fn plane_intersect(point: Vec3, normal: Vec3, ray: &Ray) -> Option<HitRecord> {
    let denom = ray.direction.dot(normal);
    if denom.abs() < 1e-6 { return None; }
    let t = (point - ray.origin).dot(normal) / denom;
    if t > 0.001 {
        let p = ray.at(t);
        let n = if denom < 0.0 { normal } else { -normal };
        Some(HitRecord { t, point: p, normal: n })
    } else { None }
}

fn triangle_intersect(v0: Vec3, v1: Vec3, v2: Vec3, ray: &Ray) -> Option<HitRecord> {
    let edge1 = v1 - v0;
    let edge2 = v2 - v0;
    let h = ray.direction.cross(edge2);
    let a = edge1.dot(h);
    if a.abs() < 1e-6 { return None; }
    let f = 1.0 / a;
    let s = ray.origin - v0;
    let u = f * s.dot(h);
    if u < 0.0 || u > 1.0 { return None; }
    let q = s.cross(edge1);
    let v = f * ray.direction.dot(q);
    if v < 0.0 || u + v > 1.0 { return None; }
    let t = f * edge2.dot(q);
    if t > 0.001 {
        let p = ray.at(t);
        let mut n = edge1.cross(edge2).normalize();
        if n.dot(ray.direction) > 0.0 { n = -n; }
        Some(HitRecord { t, point: p, normal: n })
    } else { None }
}

#[derive(Clone)]
struct Material {
    color: Color,
    specular_color: Color,
    shininess: f32,
    checkerboard: bool,
}

struct Object {
    shape: Shape,
    material: Material,
}

struct Scene { objects: Vec<Object> }

struct Light { position: Vec3, color: Color }

struct Camera {
    look_from: Vec3, forward: Vec3, right: Vec3, up: Vec3,
    half_width: f32, half_height: f32,
    width: u32, height: u32,
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
        Ray {
            origin: self.look_from,
            direction: (self.forward + self.right * u + self.up * v).normalize(),
        }
    }
}

fn reflect(l: Vec3, n: Vec3) -> Vec3 { l - 2.0 * l.dot(n) * n }

fn in_shadow(point: Vec3, light_pos: Vec3, scene: &Scene) -> bool {
    let to_light = light_pos - point;
    let distance = to_light.length();
    let direction = to_light / distance;
    let shadow_ray = Ray { origin: point + direction * 0.001, direction };
    for obj in &scene.objects {
        if let Some(hit) = obj.shape.intersect(&shadow_ray) {
            if hit.t < distance { return true; }
        }
    }
    false
}

fn checkerboard(point: Vec3, scale: f32, c1: Color, c2: Color) -> Color {
    let x = (point.x * scale).floor() as i32;
    let z = (point.z * scale).floor() as i32;
    if (x + z).rem_euclid(2) == 0 { c1 } else { c2 }
}

fn ray_cast(ray: &Ray, scene: &Scene, lights: &[Light], ambient: Color) -> Color {
    let mut closest: Option<(HitRecord, &Object)> = None;
    for obj in &scene.objects {
        if let Some(hit) = obj.shape.intersect(ray) {
            if closest.is_none() || hit.t < closest.as_ref().unwrap().0.t {
                closest = Some((hit, obj));
            }
        }
    }
    let Some((hit, obj)) = closest else {
        let t = 0.5 * (ray.direction.y + 1.0);
        return vec3(0.3, 0.5, 1.0).lerp(vec3(1.0, 1.0, 1.0), t);
    };

    let surface_color = if obj.material.checkerboard {
        checkerboard(hit.point, 0.5, vec3(0.9, 0.9, 0.9), vec3(0.1, 0.1, 0.1))
    } else {
        obj.material.color
    };

    let v = -ray.direction;
    let mut total = ambient;

    for light in lights {
        let l = (light.position - hit.point).normalize();
        let n_dot_l = hit.normal.dot(l).max(0.0);
        if n_dot_l == 0.0 { continue; }
        if in_shadow(hit.point, light.position, scene) { continue; }
        let diffuse = surface_color * light.color * n_dot_l;
        let r = reflect(-l, hit.normal);
        let r_dot_v = r.dot(v).max(0.0);
        let specular = obj.material.specular_color * light.color * r_dot_v.powf(obj.material.shininess);
        total += diffuse + specular;
    }
    total
}

fn render(scene: &Scene, camera: &Camera, lights: &[Light], samples: u32) -> Vec<u8> {
    let sqrt_spp = (samples as f32).sqrt() as u32;
    let progress = ProgressBar::new((camera.width * camera.height) as u64);
    let mut fb = vec![0u8; (camera.width * camera.height * 3) as usize];

    for y in 0..camera.height {
        for x in 0..camera.width {
            let mut color = Color::ZERO;
            for sy in 0..sqrt_spp {
                for sx in 0..sqrt_spp {
                    let sub_x = x as f32 + (sx as f32 + 0.5) / sqrt_spp as f32;
                    let sub_y = y as f32 + (sy as f32 + 0.5) / sqrt_spp as f32;
                    let ray = camera.ray_for_subpixel(sub_x, sub_y);
                    color += ray_cast(&ray, scene, lights, vec3(0.05, 0.05, 0.06));
                }
            }
            let color = color / (sqrt_spp * sqrt_spp) as f32;
            let i = (y * camera.width + x) as usize * 3;
            fb[i] = (color.x.clamp(0.0, 1.0) * 255.0) as u8;
            fb[i+1] = (color.y.clamp(0.0, 1.0) * 255.0) as u8;
            fb[i+2] = (color.z.clamp(0.0, 1.0) * 255.0) as u8;
            progress.inc(1);
        }
    }
    progress.finish();
    fb
}

fn main() {
    let scene = Scene {
        objects: vec![
            Object {
                shape: Shape::Sphere { center: vec3(0.0, 0.0, -5.0), radius: 1.0 },
                material: Material {
                    color: vec3(0.2, 0.8, 0.2),
                    specular_color: vec3(0.8, 0.8, 0.8),
                    shininess: 64.0,
                    checkerboard: false,
                },
            },
            Object {
                shape: Shape::Sphere { center: vec3(-2.0, 0.0, -7.0), radius: 0.7 },
                material: Material {
                    color: vec3(0.8, 0.2, 0.2),
                    specular_color: vec3(1.0, 1.0, 1.0),
                    shininess: 128.0,
                    checkerboard: false,
                },
            },
            Object {
                shape: Shape::Plane { point: vec3(0.0, -1.0, 0.0), normal: vec3(0.0, 1.0, 0.0) },
                material: Material {
                    color: vec3(0.5, 0.5, 0.5),
                    specular_color: vec3(0.0, 0.0, 0.0),
                    shininess: 1.0,
                    checkerboard: true,
                },
            },
        ],
    };
    let lights = vec![
        Light { position: vec3(5.0, 5.0, 0.0), color: vec3(1.0, 1.0, 1.0) },
        Light { position: vec3(-3.0, 2.0, 0.0), color: vec3(0.3, 0.3, 0.5) },
    ];
    let camera = Camera::new(
        vec3(0.0, 1.0, 0.0), vec3(0.0, 0.0, -5.0), vec3(0.0, 1.0, 0.0), 60.0, 800, 600
    );

    let fb = render(&scene, &camera, &lights, 4);
    image::save_buffer("output.png", &fb, 800, 600, image::ExtendedColorType::Rgb8).unwrap();
}
```

### Arch Linux 命令

```bash
# 1. 编译运行
cargo run --release
# 应该输出棋盘格地板 + 两个球(有高光斑)+ 阴影

# 2. 装模型查看器(看 OBJ 模型用)
sudo pacman -S meshlab
meshlab model.obj &

# 3. 测试 Möller-Trumbore 边界
cargo test triangle_intersect

# 4. 性能对比(ray01 vs ray02,加 Plane 和多光源开销)
hyperfine --runs 5 './target/release/ray01'
hyperfine --runs 5 './target/release/ray02'

# 5. 火焰图
cargo flamegraph --bin handmade-ray --release
# 看 in_shadow 占比(多光源 + 阴影射线开销)
```

**Troubleshooting**:

- 棋盘格大小不对:调整 `scale` 参数,0.5 = 每格 2 米,1.0 = 每格 1 米。
- 高光看不见:`shininess` 太低,改成 32 或 64;`specular_color` 太暗,改成 (1,1,1)。
- 阴影太黑:加 ambient 或加辅光。
- 平面看不到:检查平面 normal 方向(应该指向相机能看到的一侧)。
- 三角形背面:`if n.dot(ray.direction) > 0 { n = -n; }` 翻转法线。

## 9 · 延伸阅读(可选补充,非必需)

本仓库本地:
- [ray01.md](ray01.md) — 上一集
- [ray03.md](ray03.md) — 下一集
- [../phase-2/day044.md](../phase-2/day044.md) — 反射向量

外部稳定 URL(可选):
- Möller-Trumbore 论文: https://en.wikipedia.org/wiki/M%C3%B6ller%E2%80%93Trumbore_intersection_algorithm
- Scratchapixel Ray-Triangle: https://www.scratchapixel.com/lessons/3d-basic-rendering/ray-tracing-rendering-a-triangle
- LearnOpenGL Basic Lighting: https://learnopengl.com/Lighting/Basic-Lighting
- PBRT Triangle Intersection: https://www.pbr-book.org/3ed-2018/Shapes/Triangle_Meshes

真实开源源码:
- bvh crate: https://github.com/svenstaro/bvh
- Casey HH 原版 C 代码 raycaster: https://github.com/HandmadeHero/handmade-hero
