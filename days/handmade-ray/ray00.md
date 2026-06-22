---
episode: 00
series: handmade-ray
title_en: "Making a Simple Raycaster"
title_zh: "制作简单光线投射器"
type: concept
difficulty: 2
duration: "2-3h"
hh_url: "https://guide.handmadehero.org/ray/ray00/"
domains: [graphics, math, rust]
prereqs: ["phase-0/14-math-foundations", "phase-2/day041"]
---

# ray00 · 光线追踪入门

> 在 Casey 主剧 Phase 3,你学了**光栅化**——把 3D 三角形投影到 2D 屏幕,扫描线填充像素。这一集开始我们走**另一条路**:光线追踪(ray tracing)。光栅化是"形状 → 像素",光线追踪是"像素 → 形状"——对每个像素发射一条光线,看它撞到什么。这两个思路互为镜像,**学懂光线追踪你才真正理解光照、反射、阴影的本质**。

## 0 · 为什么要有这一天

把你拉回到一个真实场景。你跟着 Casey 写完了 Phase 3 的软光栅化器,渲染了一个带纹理的 3D 立方体。画面有了——立方体能旋转,有透视,有简单的 Lambert 光照。**但你想做更多**:

- **镜子**:画面里有一面镜子,镜子应该反射出对面的物体。光栅化做不到——光栅化只画物体本身,不知道"反射"。要做镜子,你得**手工**写一遍 "对面物体在镜子里的虚像",**每加一面镜子都要重写**。
- **玻璃**:一个玻璃杯,应该透出后面的物体,且物体在杯子里有折射变形。光栅化也做不到——透射和折射不是光栅化天然支持的。
- **柔和阴影**:物体的阴影应该是柔和过渡的(本影 → 半影),而不是硬边。光栅化的阴影图(shadow map)只能做硬阴影,柔和阴影需要专门的多 pass 算法。
- **焦散**:游泳池底的"水波光斑"是焦散(caustics),光线经水面折射聚焦。光栅化无法做。
- **全局光照(Global Illumination, GI)**:墙面接受从附近物体反弹的间接光(比如红色墙面让附近白色物体染上微红)。光栅化的"光照"是局部的——只算直接光,不算反弹光。

光栅化对这些效果**都不自然支持**,工业做法是"打补丁":cubemap 做反射、post-process 做折射、SSAO 做 GI 近似、shadow blur 做柔和阴影。**每个补丁都是 hack**,组合起来复杂、容易出 bug。

光线追踪**从设计上**就支持这些效果:**因为它模拟光的物理传播**。一条光线撞到镜子,自然反射;撞到玻璃,自然折射;每条光线可以发射阴影射线,自然得到阴影。**所有效果用同一套物理公式**。

为什么"光线追踪"听起来高级?因为它**计算量大**——每个像素至少一条光线,光线可能反射 N 次,每次反射再发射阴影射线,**计算量随反射深度指数增长**。传统上 1080p 渲染一帧要几分钟到几小时。

但**有两个变化让光线追踪在 2020 年代重回主流**:

1. **2018 年 RTX 显卡**:NVIDIA 推出硬件 ray tracing 单元(RT cores),把光线-AABB 相交加速到硬件级。光栅化 + 光线追踪混合渲染成为现实。
2. **2020 年 Cyberpunk 2077、2023 年 Alan Wake 2**:把 path tracing(完整光线追踪)作为游戏渲染方案,实时光线追踪不再是概念演示,而是商业产品。

**学光线追踪不再是为了"做电影",而是为了"做游戏"**。

这一集是 Handmade Ray 系列的开篇,我们从零开始,**用一个简化的 raycaster** 让你直观感受光线追踪的基本思路。Casey 原 ray00 直接写最朴素版本,但**我们要先理解概念**——为什么这种思路能工作、它和光栅化的本质差别、它能做什么不能做什么。**懂了概念,后面 ray01-04 的代码才有意义**。

心理锚点:今天之后,你能:(1) 解释光线追踪和光栅化的本质差别;(2) 用一个最小 raycaster 在 Rust 里渲染一个有球体的画面(纯色);(3) 知道"为什么光线追踪自然支持反射、阴影、GI";(4) 知道光线追踪的主要瓶颈(计算量)和解决方向(并行、加速结构、SIMD)。

## 1 · Casey 今天做了什么(Handmade Ray 脉络)

Casey 在 Handmade Ray ray00 做的事:

1. **从空白项目开始**:不像 Handmade Hero 主剧有完整平台层(窗口、输入、音频),Handmade Ray 是**单文件**项目——开个窗口,每帧把一个 `vec3 * width * height` 的 framebuffer blit 到屏幕。

2. **定义基本类型**:`Vec3`(三个 f32,加法、点积、叉积、归一化)、`Ray`(起点 + 方向)。

3. **写最小 raycaster**:对每个像素,从相机发射一条光线,光线在场景里和球体做相交测试。**只画背景渐变 + 一个绿色球体**——球体外是渐变背景,球体内是纯绿色。**没有光照,没有材质,只有"命中 / 不命中"**。

4. **抓帧确认结果**:Casey 抓了一帧 800×600 的画面,看到一个绿色圆球在渐变背景上。这就是 raycaster 的"hello world"——证明整条数据通路通了。

到 ray00 结束,Casey 没有任何光照、反射、阴影——**所有复杂效果留给 ray01-04**。这一集只是搭好骨架:Vec3 → Ray → 相交 → 颜色。**所有后续优化和效果都建立在这个骨架上**。

## 2 · 心智模型

### 类比:光线追踪是"反向问路"

想象你站在一片陌生的小镇,想找到邮局。**两种思路**:

**思路 A(光栅化)**:你拿一张地图,从所有可能的邮局位置出发,把它们投影到你能看到的视野里。如果邮局在你的视野内,地图上有标记;不在的话,看不到。这是"**从物体到像素**"。

**思路 B(光线追踪)**:你站在原地不动,对视野里**每个方向**发射一条视线,沿着视线方向看,直到撞到某个物体。撞到邮局 → 邮局的颜色画到这个方向;撞到树 → 树画到这个方向;什么都没撞到 → 天空的颜色。这是"**从像素到物体**"。

**关键差别**:
- 光栅化:**遍历所有物体**,问"它在屏幕哪里?"
- 光线追踪:**遍历所有像素**,问"这个像素看到什么?"

物理上,**思路 B 才是光传播的真实方向**——光从光源出发,经多次反射,最终进入你的眼睛。光线追踪是**反向**追踪这条光路(从眼睛出发,反推到光源)。

### 严谨原理:射线和相交

光线追踪的核心数据结构是 **Ray(射线)**:

```rust
#[derive(Copy, Clone, Debug)]
struct Ray {
    origin: Vec3,    // 起点
    direction: Vec3, // 方向(通常归一化为单位向量)
}
```

射线参数化:**射线上任意一点** = `origin + t * direction`,t 是参数(t ≥ 0 表示射线方向上,t < 0 表示反方向)。

**光线追踪的核心问题**:这条射线和场景里的几何(球、平面、三角面)在哪个 t 处相交?**最小的 t** 是最近的相交点。

### Ray-Sphere 相交

最经典的相交算法。球体定义:`|p - center|² = radius²`(p 是球面上一点,center 是球心,radius 是半径)。

把射线方程 `p = origin + t * direction` 代入:

```
|(origin + t * direction) - center|² = radius²
```

设 `oc = origin - center`(向量,从球心指向射线起点),展开:

```
|oc + t * direction|² = radius²
(oc + t * direction) · (oc + t * direction) = radius²
oc · oc + 2t * (oc · direction) + t² * (direction · direction) = radius²
```

因为 `direction` 是单位向量,`direction · direction = 1`,简化:

```
t² + 2(oc · direction) * t + (oc · oc - radius²) = 0
```

这是关于 t 的二次方程 `at² + bt + c = 0`:

- a = `direction · direction` = 1
- b = `2 * (oc · direction)`
- c = `oc · oc - radius²`

解二次方程:

```
discriminant = b² - 4ac
if discriminant < 0: 无解(射线不交球)
if discriminant = 0: 一解(射线擦边)
if discriminant > 0: 两解(射线穿过球)
```

两个解:

```
t1 = (-b - √discriminant) / (2a)  // 近交点(射线进入球)
t2 = (-b + √discriminant) / (2a)  // 远交点(射线穿出球)
```

光线追踪用 t1(最近交点),如果 t1 < 0(球在射线背后)则用 t2,如果 t2 也 < 0 则不相交(球完全在射线背后)。

### 朴素 raycaster 的伪代码

```rust
fn ray_cast(ray: &Ray, scene: &Scene) -> Color {
    let mut closest_t = f32::INFINITY;
    let mut hit_object: Option<&Object> = None;

    for obj in &scene.objects {
        if let Some(t) = obj.intersect(ray) {
            if t > 0.0 && t < closest_t {
                closest_t = t;
                hit_object = Some(obj);
            }
        }
    }

    if let Some(obj) = hit_object {
        obj.color  // 命中:返回物体颜色
    } else {
        background_color(ray)  // 未命中:返回背景
    }
}

fn render(scene: &Scene, camera: &Camera, framebuffer: &mut [Color]) {
    for y in 0..height {
        for x in 0..width {
            let ray = camera.ray_for_pixel(x, y);
            framebuffer[y * width + x] = ray_cast(&ray, scene);
        }
    }
}
```

**这就是 Casey ray00 的全部**。500 行 Rust 代码,没有光照、没有材质,只是"命中 / 未命中"。但**它已经是个完整的 raycaster**——所有后续扩展都在 `obj.intersect` 和 `obj.color` 这两个地方加。

### 相机的射线生成

对每个屏幕像素 (x, y),相机生成一条射线。最简单的**针孔相机模型(pinhole camera)**:

```
                    up (y+)
                    ↑
                    │    image plane
                    │   ┌──────────┐
                    │   │          │  ← width × height 像素
                    │   │          │
              eye → │   └──────────┘
                    │
                    └──────────→ forward (z-)
                    
                    right (x+)
```

相机在 `eye`,看向 `forward`(通常是 -z),`up` 是上方,`right` 是右方。**像平面(image plane)** 在 forward 方向距离 1(或任意正数)的位置,大小由 FOV(field of view)决定。

对像素 (x, y),射线方向:

```rust
fn ray_for_pixel(&self, x: u32, y: u32) -> Ray {
    // 归一化到 [-1, 1]
    let ndc_x = (2.0 * (x as f32 + 0.5) / self.width as f32 - 1.0) * self.aspect_ratio * tan(self.fov / 2.0);
    let ndc_y = (1.0 - 2.0 * (y as f32 + 0.5) / self.height as f32) * tan(self.fov / 2.0);
    // 注意 y 方向:屏幕坐标系 y 向下,世界坐标 y 向上,所以要翻转

    let direction = (self.forward + self.right * ndc_x + self.up * ndc_y).normalize();
    Ray { origin: self.eye, direction }
}
```

**关键**:
- 屏幕坐标 (x, y) 原点在左上角,y 向下;世界坐标 y 向上,**翻转 y**
- NDC(normalized device coordinates)归一化到 [-1, 1],中心是 (0, 0)
- FOV 决定视野范围(典型 60-90 度),`tan(fov/2)` 是 half image plane height
- aspect_ratio = width / height,校正屏幕长宽比

### 光线追踪 vs 光栅化的本质差别

| 维度 | 光栅化 | 光线追踪 |
|---|---|---|
| **核心循环** | for each object → for each pixel | for each pixel → for each object |
| **几何处理** | 把三角形投影到屏幕 | 在 3D 空间做相交测试 |
| **复杂度** | O(triangles) | O(pixels × objects) |
| **反射** | 不天然支持,要 hack | 天然支持,递归追踪反射光线 |
| **阴影** | shadow map hack | 阴影射线,精确 |
| **GI** | SSAO / LPV 等近似 | path tracing,物理正确 |
| **GPU 友好** | 是(并行度高) | 部分(像素间独立,但物体遍历串行) |
| **性能** | 实时 | 离线 / 实时(需加速结构) |

**核心洞察**:**光线追踪的"像素独立"性质让它天然并行**——每个像素的光线独立,可以并行算。Casey ray01 就利用这个加多线程。

### 为什么光线追踪更"物理"

光栅化只算"物体在屏幕上画什么颜色",**不模拟光的传播**。它的光照模型是**局部**的:每个像素独立算光照,**不知道光从哪来、往哪去**。

光线追踪**模拟光的传播**:
- 直接光:从光源发射光线,撞到物体,光照度
- 阴影:从物体点向光源发射**阴影射线**,如果中间有遮挡 → 阴影
- 反射:从物体点按反射定律发射**次级光线**,递归追踪
- 折射:类似反射,但用 Snell 定律(Snell's Law)
- GI:从物体点向半球方向发射**多条光线**,递归追踪,累加

每条光线**携带光的物理信息**(颜色、强度),递归传播,最终累加到像素颜色。**这是工业 PBR 渲染器的基础**。

## 3 · 四域深入

### 3.1 · 🎮 游戏编程视角

游戏开发里光线追踪的应用:

| 场景 | 何时用 | 实现成本 |
|---|---|---|
| 反射(水面、镜子) | 实时 RTX | 中(RT cores 加速) |
| 焦散 | 离线 / RTX 高端 | 高 |
| 阴影 | 实时 RTX | 中 |
| GI | 实时 RTX 或离线 | 高 |
| 角色头发渲染 | 实时 RTX | 中 |

**RTX 时代(2018+)**:主流游戏开始用混合渲染——光栅化画主要几何,光线追踪画反射、阴影、GI。Cyberpunk 2077 在 2023 年加入"路径追踪覆盖"(path tracing override),完全用光线追踪渲染——**这是工业级实时光线追踪的里程碑**。

**Handmade Ray 的位置**:Casey 写这个系列是 2015 年,RTX 还不存在。他用纯 CPU 做光线追踪,**目标不是实时**,而是**教学**——展示光线追踪的最小实现和优化路径。今天学,你能理解 RTX 渲染器的 CPU fallback、调试工具、dev mode。

### 3.2 · 🎨 图形学视角

光线追踪的工业实现层次:

1. **Raycasting(光线投射)**:每像素一条光线,只算最近交点。Casey ray00 做的。无光照,无反射。
2. **Ray tracing(光线追踪)**:加上光照、阴影、反射、折射。递归深度 1-3 层。**Whitted 风格**(1980 Turner Whitted 提出)。Casey ray01-04 做的。
3. **Path tracing(路径追踪)**:每像素多条光线(采样),Monte Carlo 积分得到 GI。**物理正确**。PBRT-Book 描述的。
4. **Bidirectional path tracing / Metropolis light transport**:更高级的采样策略,解决 path tracing 在某些场景收敛慢的问题。科研级。
5. **Photon mapping**:光子从光源发射,缓存到 photon map,反向查找。Jensen 1996。

**Handmade Ray 主要在 1-2 层**(raycasting + 基础 ray tracing),ray04 触及 3(BRDF 采样)。完整 path tracing 在主剧 Phase 8。

**数学基础**:
- 几何:向量、点积、叉积、归一化(Phase 0 数学基础)
- 相交:Ray-Sphere、Ray-Plane、Ray-Triangle(ray00-02)
- 反射:公式 `v' = v - 2(v·n)n`(day044)
- 折射:Snell 定律 `n1 sin(θ1) = n2 sin(θ2)`(ray03 玻璃材质)
- Monte Carlo:`E[f] ≈ (1/N) Σ f(x_i)`,x_i 随机采样(ray04)

### 3.3 · 🐧 Linux 系统编程视角

Linux 上跑光线追踪的工业工具:

**Mitsuba 3**(科研 path tracer,Python API):
```bash
sudo pacman -S mitsuba3  # 或 pip install mitsuba3
```

**Cycles**(Blender 的 path tracer,C++/CUDA):
```bash
sudo pacman -S blender
# Blender 内置 Cycles,可选 CPU/GPU
```

**OSPRay**(Intel 出的科学可视化 ray tracer):
```bash
sudo pacman -S ospray
```

**自己写的 raytracer 性能分析**:

```bash
# 多线程性能
nproc  # CPU 核数
# raytracer 单线程 1 FPS → 多线程 N FPS(N = 核数)

# SIMD 性能
cat /proc/cpuinfo | grep -E "(sse|avx)" | head -1
# 看 CPU 支持的 SIMD 指令集(SSE / SSE2 / AVX / AVX2 / AVX-512)

# Cache miss 分析
perf stat -e cache-misses,cache-references ./your_raytracer
# 高 cache miss 说明数据布局不友好

# 火焰图
cargo install flamegraph
cargo flamegraph --bin your_raytracer
# 看哪个函数最热
```

**SIMD 友好的 Ray 结构**:朴素 Ray 是 `{ Vec3 origin, Vec3 direction }`(24 字节)。SIMD 优化版本用 **SoA(Struct of Arrays)**:

```rust
struct RayPacket4 {
    origin_x: [f32; 4],
    origin_y: [f32; 4],
    origin_z: [f32; 4],
    direction_x: [f32; 4],
    direction_y: [f32; 4],
    direction_z: [f32; 4],
}
```

这样一条 SSE 指令(_mm_add_ps)同时处理 4 条光线的 x 分量。**4-wide SSE 加速 4 倍,8-wide AVX 加速 8 倍**。Casey ray03 做这个。

### 3.4 · 🦀 Rust 生态视角

Rust 上写 ray tracer 的几个 crate:

| Crate | 角色 |
|---|---|
| `glam` | 向量数学(SIMD 优化) |
| `rand` / `rand_chacha` | 随机数(Monte Carlo 用) |
| `image` | PNG / JPEG I/O |
| `rayon` | 数据并行(把每帧像素 ray cast 并行化) |
| `indicatif` | 进度条(渲染 1080p 要几秒,要进度反馈) |
| `crossbeam` | 多线程(自己写线程池) |

**最小 ray tracer 的 Cargo.toml**:

```toml
[package]
name = "handmade-ray"
version = "0.1.0"
edition = "2021"

[dependencies]
glam = "0.29"
image = "0.25"
indicatif = "0.17"

[profile.release]
opt-level = 3
lto = "fat"      # link-time optimization,提升 10-20%
codegen-units = 1  # 单线程 codegen,更好的优化
```

**rayon 加速**(ray01 会讲):

```rust
use rayon::prelude::*;

framebuffer
    .par_chunks_mut(width)
    .enumerate()
    .for_each(|(y, row)| {
        for (x, pixel) in row.iter_mut().enumerate() {
            let ray = camera.ray_for_pixel(x as u32, y as u32);
            *pixel = ray_cast(&ray, &scene);
        }
    });
```

`par_chunks_mut` 把 framebuffer 分成行,**每行一个任务,并行执行**。8 核 CPU 加速近 8 倍。

**所有权角度**:`Scene` 在多线程间共享,Rust 要求 `Send + Sync`。`Scene` 里如果只有 `Vec<Sphere>`(immutable),自然 `Sync`。如果有 `Mutex<T>`,需要小心锁粒度。

### 3.5 · 🔢 数学视角(向量复习)

向量是光线追踪的"基本粒子"。完整向量数学复习:

**Vec3 定义**:

```rust
#[derive(Copy, Clone, Debug, PartialEq)]
struct Vec3 { x: f32, y: f32, z: f32 }
```

**基本运算**:

```rust
impl Vec3 {
    fn new(x: f32, y: f32, z: f32) -> Self { Self { x, y, z } }
    fn add(self, o: Self) -> Self { Self::new(self.x + o.x, self.y + o.y, self.z + o.z) }
    fn sub(self, o: Self) -> Self { Self::new(self.x - o.x, self.y - o.y, self.z - o.z) }
    fn mul_scalar(self, k: f32) -> Self { Self::new(self.x * k, self.y * k, self.z * k) }
    fn mul_componentwise(self, o: Self) -> Self { Self::new(self.x * o.x, self.y * o.y, self.z * o.z) }  // 颜色乘法用
    fn dot(self, o: Self) -> f32 { self.x * o.x + self.y * o.y + self.z * o.z }
    fn cross(self, o: Self) -> Self {
        Self::new(
            self.y * o.z - self.z * o.y,
            self.z * o.x - self.x * o.z,
            self.x * o.y - self.y * o.x,
        )
    }
    fn length(self) -> f32 { self.dot(self).sqrt() }
    fn length_squared(self) -> f32 { self.dot(self) }  // 不开方,快
    fn normalized(self) -> Self {
        let len = self.length();
        if len > 1e-6 { self.mul_scalar(1.0 / len) } else { Self::new(0.0, 0.0, 0.0) }
    }
}
```

**几何意义**:
- **加法**:向量合成(平行四边形法则)
- **减法**:求位移
- **点积**:`a · b = |a||b|cos(θ)`,衡量"对齐程度"
- **叉积**:`|a × b| = |a||b|sin(θ)`,方向垂直于 a 和 b(右手定则)
- **长度**:`|v| = √(x² + y² + z²)`,欧几里得距离
- **归一化**:除以长度,得到单位向量

**Ray-Sphere 相交的数学**(用上面的运算):

```rust
fn ray_sphere_intersect(ray: &Ray, sphere: &Sphere) -> Option<f32> {
    let oc = ray.origin.sub(sphere.center);
    let a = ray.direction.dot(ray.direction);  // 通常 = 1(单位向量)
    let b = 2.0 * oc.dot(ray.direction);
    let c = oc.dot(oc) - sphere.radius * sphere.radius;
    let discriminant = b * b - 4.0 * a * c;
    if discriminant < 0.0 {
        None
    } else {
        let sqrt_d = discriminant.sqrt();
        let t1 = (-b - sqrt_d) / (2.0 * a);
        let t2 = (-b + sqrt_d) / (2.0 * a);
        if t1 > 0.0001 { Some(t1) }  // 近交点,epsilon 防止自相交
        else if t2 > 0.0001 { Some(t2) }
        else { None }
    }
}
```

**关键点**:`t > 0.0001` 而不是 `t > 0`,因为浮点精度问题——光线打到物体表面后,从表面反射的次级光线**起点正好在表面上**,浮点误差可能让 t 略小于 0,**自相交**(物体和自己相交)。0.0001 是常用的 epsilon。

## 4 · 认知地图

### 4.1 上级

- **渲染算法** — 把 3D 场景变 2D 图像的方法(光栅化、光线追踪、路径追踪、photon mapping)
- **光照传输(Light Transport)** — 光从光源到相机的物理传播
- **数值方法** — Monte Carlo 积分、迭代求解
- **并行计算** — 多线程、SIMD、GPU

### 4.2 同级(并行方案)

| 方案 | 关键差别 | 何时用 | 本项目选了哪个 |
|---|---|---|---|
| Raycasting | 命中/未命中,无光照 | 教学 / 阴影测试 | ✅ ray00 |
| Whitted ray tracing | 加光照、反射、折射 | 镜面反射、玻璃 | ✅ ray01-04 |
| Path tracing | Monte Carlo GI | 物理正确 GI | Phase 8 |
| Photon mapping | 光子缓存 | 焦散、复杂 GI | HH 不用 |
| Rasterization + hacks | 光栅化为主 | 实时渲染(主流游戏) | HH Phase 3 主线 |

### 4.3 下级

- **Vec3 / Ray 数据结构** — 基本类型
- **Ray-Sphere 相交** — 二次方程求解
- **Ray-Plane 相交** — 线性方程(ray02)
- **Ray-Triangle 相交** — Möller-Trumbore 算法(ray02)
- **Camera model** — 针孔相机、FOV、aspect ratio
- **Background sampling** — 渐变天空、环境贴图
- **Framebuffer** — 像素颜色数组

## 5 · 对照与变奏

### 光栅化 vs 光线追踪:同一场景的两种渲染

**场景**:一个金属球在棋盘地板上,背景是天空。

**光栅化渲染**:
1. 把棋盘地板的三角形投影到屏幕
2. 把球的三角形投影到屏幕
3. 用 z-buffer 决定每个像素画哪个
4. 像素着色:棋盘地板有纹理,球有金属 BRDF(但反射要 cubemap)
5. 阴影:画两次(相机视角 + 光源视角)
6. 总计:每帧 N 次绘制,N 个三角形

**光线追踪渲染**:
1. 对每个像素发射一条光线
2. 光线撞到棋盘 → 在交点发射阴影射线(到光源) + 反射射线(按反射定律)
3. 反射射线撞到球 → 在交点再次发射阴影 + 反射射线
4. 递归追踪,累加颜色
5. 总计:每像素 1 + N 条光线,N = 反射深度

**视觉效果对比**:

| 效果 | 光栅化 | 光线追踪 |
|---|---|---|
| 直接光照 | ✅ 简单 | ✅ 简单 |
| 阴影 | ⚠️ shadow map hack | ✅ 自然 |
| 镜面反射 | ⚠️ cubemap 近似 | ✅ 精确 |
| 折射 | ⚠️ post-process hack | ✅ 自然 |
| GI | ⚠️ SSAO / LPV 近似 | ✅ 路径追踪 |
| 性能 | ✅ 实时 | ⚠️ 需加速结构 |

**结论**:**两者不是二选一,现代渲染器混合用**。光栅化做主体,光线追踪做高质量反射 / 阴影 / GI。

### 历史演化

- **1968 Appel**:第一个光线投射(casting),用于 CAD 渲染
- **1979 Whitted**:递归光线追踪(加反射、折射),论文 "Recursion Tracing"
- **1986 Kajiya**:路径追踪(完整 GI),论文 "The Rendering Equation"
- **1990s-2000s**:光栅化主导游戏,光线追踪只在电影
- **2018 NVIDIA RTX**:硬件加速,实时光线追踪开始
- **2020+**:DirectX 12 Ultimate / Vulkan RT,主流游戏集成光线追踪

### CPU vs GPU 光线追踪

| 维度 | CPU | GPU |
|---|---|---|
| 编程模型 | Rust + rayon + SIMD | GLSL/HLSL/WGSL compute shader |
| 性能 | 1080p 几秒 | 1080p 几毫秒(RTX) |
| 灵活性 | 高(任意数据结构) | 中(需要适配 GPU 内存模型) |
| 调试 | 容易(gdb / println) | 难(RenderDoc shader debugger) |
| 开发速度 | 快 | 慢 |

**Handmade Ray 选 CPU**:Casey 强调"自己控制每一个细节",CPU 让代码透明、可调试。**学完 CPU 版本,你理解了原理,再切 GPU(RTX shader)水到渠成**。

## 6 · 关联

- **铺垫**:
  - [phase-0/14-math-foundations.md](../phase-0/14-math-foundations.md) — 线性代数(向量、点积、叉积)
  - [phase-2/day041.md](../phase-2/day041.md) — 游戏数学概览
  - [phase-3/day071.md](../phase-3/day071.md) — 3D 渲染起步(光栅化,作对比)
- **当天**:ray00 — 光线追踪入门
- **后续**:
  - [ray01.md](ray01.md) — 基本 raytracer(球体相交、shading)
  - [ray02.md](ray02.md) — 平面、阴影、Phong
  - [ray03.md](ray03.md) — 材质系统
  - [ray04.md](ray04.md) — 反射、抗锯齿
  - 主剧 Phase 8 — SIMD 加速 raycast

## 7 · 变式训练

### Lv1 · 概念辨析

**题**:为什么光线追踪天然支持反射,而光栅化不支持?用"循环方向"的角度回答。

**参考解答**:

**光栅化的循环**是 `for each object, for each pixel`:遍历物体,把每个物体画到屏幕。**物体是 input,像素是 output**。画完一个物体就完了,**物体之间没有交互**——画镜子时不知道"镜子要反射对面什么",因为对面物体还没画(或者已经画了,但被覆盖了)。

**光线追踪的循环**是 `for each pixel, for each object`:遍历像素,每像素发射光线。**像素是 input,物体是 output**。一条光线撞到镜子后,**自然地发射次级光线**——次级光线继续遍历物体,撞到对面的物体。**反射在算法层面是递归**,不需要特殊代码。

**关键洞察**:**光栅化是"分发"模型,光线追踪是"请求"模型**。光栅化把物体分发到像素,光线追踪从像素请求物体信息。请求模型**支持递归**(一个请求触发另一个请求),分发模型**不支持**。

### Lv2 · 动手实践

**题**:在 Rust 里实现最小 raycaster,渲染一个 800×600 的画面:背景是渐变(从上方蓝色到下方白色),中央有一个绿色球体(球心在 (0, 0, -5),半径 1.0)。

完成标准:
- 程序运行后生成 `output.png`
- 用 `eog output.png` 查看画面
- 看到一个绿色圆球在渐变背景上

**参考解答**:

```rust
// Cargo.toml:
// [dependencies]
// glam = "0.29"
// image = "0.25"

use glam::{Vec3, vec3};

type Color = Vec3;

struct Ray {
    origin: Vec3,
    direction: Vec3,
}

impl Ray {
    fn at(&self, t: f32) -> Vec3 {
        self.origin + self.direction * t
    }
}

struct Sphere {
    center: Vec3,
    radius: f32,
    color: Color,
}

impl Sphere {
    fn intersect(&self, ray: &Ray) -> Option<f32> {
        let oc = ray.origin - self.center;
        let a = ray.direction.dot(ray.direction);  // 通常 = 1
        let b = 2.0 * oc.dot(ray.direction);
        let c = oc.dot(oc) - self.radius * self.radius;
        let discriminant = b * b - 4.0 * a * c;
        if discriminant < 0.0 {
            None
        } else {
            let sqrt_d = discriminant.sqrt();
            let t1 = (-b - sqrt_d) / (2.0 * a);
            let t2 = (-b + sqrt_d) / (2.0 * a);
            if t1 > 0.001 {
                Some(t1)
            } else if t2 > 0.001 {
                Some(t2)
            } else {
                None
            }
        }
    }
}

struct Scene {
    objects: Vec<Sphere>,
}

fn ray_cast(ray: &Ray, scene: &Scene) -> Color {
    let mut closest_t = f32::INFINITY;
    let mut hit_color: Option<Color> = None;

    for obj in &scene.objects {
        if let Some(t) = obj.intersect(ray) {
            if t < closest_t {
                closest_t = t;
                hit_color = Some(obj.color);
            }
        }
    }

    if let Some(color) = hit_color {
        color
    } else {
        // 渐变背景:从蓝(上)到白(下)
        let t = 0.5 * (ray.direction.y + 1.0);  // [-1, 1] → [0, 1]
        let blue = vec3(0.3, 0.5, 1.0);
        let white = vec3(1.0, 1.0, 1.0);
        blue.lerp(white, t)
    }
}

fn render(scene: &Scene, width: u32, height: u32) -> Vec<u8> {
    let aspect_ratio = width as f32 / height as f32;
    let mut framebuffer = vec![0u8; (width * height * 3) as usize];

    let eye = vec3(0.0, 0.0, 0.0);
    let forward = vec3(0.0, 0.0, -1.0);  // 看向 -z
    let up = vec3(0.0, 1.0, 0.0);
    let right = vec3(1.0, 0.0, 0.0);

    let fov = 60.0f32.to_radians();
    let half_height = (fov / 2.0).tan();
    let half_width = half_height * aspect_ratio;

    for y in 0..height {
        for x in 0..width {
            // NDC:[-1, 1]
            let u = (2.0 * (x as f32 + 0.5) / width as f32 - 1.0) * half_width;
            let v = (1.0 - 2.0 * (y as f32 + 0.5) / height as f32) * half_height;

            let direction = (forward + right * u + up * v).normalize();
            let ray = Ray { origin: eye, direction };
            let color = ray_cast(&ray, scene);

            // 转换到 [0, 255]
            let i = (y * width + x) as usize * 3;
            framebuffer[i] = (color.x.clamp(0.0, 1.0) * 255.0) as u8;
            framebuffer[i + 1] = (color.y.clamp(0.0, 1.0) * 255.0) as u8;
            framebuffer[i + 2] = (color.z.clamp(0.0, 1.0) * 255.0) as u8;
        }
    }

    framebuffer
}

fn main() {
    let scene = Scene {
        objects: vec![
            Sphere {
                center: vec3(0.0, 0.0, -5.0),
                radius: 1.0,
                color: vec3(0.2, 0.8, 0.2),  // 绿色
            },
        ],
    };

    let width = 800;
    let height = 600;
    let framebuffer = render(&scene, width, height);

    image::save_buffer("output.png", &framebuffer, width, height, image::ExtendedColorType::Rgb8)
        .unwrap();
    println!("Saved output.png");
}
```

**每行解释**:
- `glam::Vec3` 是 SIMD 优化的 3D 向量,不用手写
- `ray.at(t)` 计算射线上 t 处的点
- `intersect` 实现二次方程求解(详见 §2)
- `0.001` 是 epsilon,防止自相交
- `lerp` 是 glam 的线性插值,`a.lerp(b, t) = a + (b - a) * t`
- `clamp(0.0, 1.0)` 限制颜色范围(防止超过 1.0 的浮点值在转 u8 时溢出)

### Lv3 · 迁移设计

**题**:你被要求做一个**2D raycaster**(像 Wolfenstein 3D 那种早期 FPS),而不是 3D。差别是什么?2D 简化在哪里?提示:射线是 2D 不是 3D,相交是 Ray-Line 而不是 Ray-Sphere。

**提示**:
- 2D 场景是俯视图,玩家有位置 + 朝向
- 每个屏幕列发射一条 2D 射线
- 射线撞到墙壁后,根据距离决定这一列的高度
- 比 3D 简单很多,但思路完全一致

### Lv4 · 开源贡献

**题**:`rust-gpu` 是 Rust 生态用 Rust 写 GPU shader 的项目,GitHub: https://github.com/EmbarkStudios/rust-gpu

1. clone 仓库:
   ```bash
   gh repo clone EmbarkStudios/rust-gpu
   cd rust-gpu
   ```
2. 看里面的 examples,有没有 ray tracer 例子?
3. **可能的贡献方向**:
   - examples 里加一个简单的 ray tracer(基于本日的代码)
   - doc 里讲"Rust 写 shader vs GLSL"的对比
   - 测试覆盖
4. 写 PR 描述

## 8 · Rust / Arch 落地代码

### 完整可跑的 raycaster

下面是 Lv2 的扩展版,**加上指示器(进度条)、性能测量、可配置的输出尺寸**。

```rust
// src/main.rs
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

impl Sphere {
    fn intersect(&self, ray: &Ray) -> Option<f32> {
        let oc = ray.origin - self.center;
        let a = ray.direction.dot(ray.direction);
        let half_b = oc.dot(ray.direction);  // 用 half-b 简化,避免 2*
        let c = oc.dot(oc) - self.radius * self.radius;
        let discriminant = half_b * half_b - a * c;
        if discriminant < 0.0 {
            None
        } else {
            let sqrt_d = discriminant.sqrt();
            let t1 = (-half_b - sqrt_d) / a;
            let t2 = (-half_b + sqrt_d) / a;
            if t1 > 0.001 {
                Some(t1)
            } else if t2 > 0.001 {
                Some(t2)
            } else {
                None
            }
        }
    }
}

struct Scene {
    objects: Vec<Sphere>,
}

impl Scene {
    fn new() -> Self {
        Self { objects: Vec::new() }
    }
    fn add_sphere(&mut self, sphere: Sphere) {
        self.objects.push(sphere);
    }
}

fn ray_cast(ray: &Ray, scene: &Scene) -> Color {
    let mut closest_t = f32::INFINITY;
    let mut hit_color: Option<Color> = None;

    for obj in &scene.objects {
        if let Some(t) = obj.intersect(ray) {
            if t < closest_t {
                closest_t = t;
                hit_color = Some(obj.color);
            }
        }
    }

    if let Some(color) = hit_color {
        color
    } else {
        // 渐变背景
        let t = 0.5 * (ray.direction.y + 1.0);
        vec3(0.3, 0.5, 1.0).lerp(vec3(1.0, 1.0, 1.0), t)
    }
}

struct Camera {
    eye: Vec3,
    forward: Vec3,
    up: Vec3,
    right: Vec3,
    half_width: f32,
    half_height: f32,
    width: u32,
    height: u32,
}

impl Camera {
    fn new(eye: Vec3, look_at: Vec3, up: Vec3, fov_deg: f32, width: u32, height: u32) -> Self {
        let forward = (look_at - eye).normalize();
        let right = forward.cross(up).normalize();
        let camera_up = right.cross(forward);  // 重新算 up 保证正交

        let aspect_ratio = width as f32 / height as f32;
        let half_height = (fov_deg.to_radians() / 2.0).tan();
        let half_width = half_height * aspect_ratio;

        Self {
            eye, forward, up: camera_up, right,
            half_width, half_height, width, height,
        }
    }

    fn ray_for_pixel(&self, x: u32, y: u32) -> Ray {
        let u = (2.0 * (x as f32 + 0.5) / self.width as f32 - 1.0) * self.half_width;
        let v = (1.0 - 2.0 * (y as f32 + 0.5) / self.height as f32) * self.half_height;
        let direction = (self.forward + self.right * u + self.up * v).normalize();
        Ray { origin: self.eye, direction }
    }
}

fn render(scene: &Scene, camera: &Camera) -> Vec<u8> {
    let total_pixels = (camera.width * camera.height) as u64;
    let progress = ProgressBar::new(total_pixels);
    progress.set_style(ProgressStyle::default_bar()
        .template("{wide_bar} {pos}/{len} ({eta})").unwrap()
        .progress_chars("=> "));

    let mut framebuffer = vec![0u8; (camera.width * camera.height * 3) as usize];

    for y in 0..camera.height {
        for x in 0..camera.width {
            let ray = camera.ray_for_pixel(x, y);
            let color = ray_cast(&ray, scene);

            let i = (y * camera.width + x) as usize * 3;
            framebuffer[i] = (color.x.clamp(0.0, 1.0) * 255.0) as u8;
            framebuffer[i + 1] = (color.y.clamp(0.0, 1.0) * 255.0) as u8;
            framebuffer[i + 2] = (color.z.clamp(0.0, 1.0) * 255.0) as u8;

            progress.inc(1);
        }
    }

    progress.finish();
    framebuffer
}

fn main() {
    let mut scene = Scene::new();
    scene.add_sphere(Sphere {
        center: vec3(0.0, 0.0, -5.0),
        radius: 1.0,
        color: vec3(0.2, 0.8, 0.2),
    });
    scene.add_sphere(Sphere {
        center: vec3(-2.0, 0.0, -7.0),
        radius: 0.7,
        color: vec3(0.8, 0.2, 0.2),
    });
    scene.add_sphere(Sphere {
        center: vec3(2.0, 0.0, -6.0),
        radius: 0.5,
        color: vec3(0.2, 0.2, 0.8),
    });

    let width = 800;
    let height = 600;
    let camera = Camera::new(
        vec3(0.0, 0.0, 0.0),
        vec3(0.0, 0.0, -5.0),
        vec3(0.0, 1.0, 0.0),
        60.0,
        width,
        height,
    );

    let start = Instant::now();
    let framebuffer = render(&scene, &camera);
    let duration = start.elapsed();
    println!("Render took: {:?}", duration);

    image::save_buffer("output.png", &framebuffer, width, height, image::ExtendedColorType::Rgb8)
        .unwrap();
    println!("Saved output.png");
}
```

### Arch Linux 命令

```bash
# 1. 创建项目
cd ~/src
cargo new --bin handmade-ray
cd handmade-ray

# 2. 加依赖
cat >> Cargo.toml << 'EOF'

[dependencies]
glam = "0.29"
image = "0.25"
indicatif = "0.17"

[profile.release]
opt-level = 3
lto = "fat"
codegen-units = 1
EOF

# 3. 把上面代码粘到 src/main.rs,编译运行
cargo run --release
# 输出:
# Render took: 50ms  (或类似)
# Saved output.png

# 4. 查看结果
sudo pacman -S eog  # GNOME 图片查看器
eog output.png &

# 5. 性能分析
sudo pacman -S perf
perf stat ./target/release/handmade-ray
# 输出 cycles, instructions, cache-misses 等

# 6. 看汇编验证 SIMD(glam 的 Vec3 是否 SIMD 化)
cargo rustc --release -- --emit asm --target-cpu native
find target/release/deps/ -name "handmade_ray-*.s" | head -1 | xargs grep -E "(mulps|addps|sqrtps|divps)" | head -10
# 应该看到 SIMD 指令(SSE / AVX)

# 7. 看时间细分(用 hyperfine)
sudo pacman -S hyperfine
hyperfine --runs 10 './target/release/handmade-ray'
# 输出平均时间、标准差

# 8. flamegraph 找热点
cargo install flamegraph
sudo pacman -S perl # flamegraph 需要
cargo flamegraph --bin handmade-ray --release
# 输出 flamegraph.svg,用浏览器打开
# 应该看到 ray_cast 和 Sphere::intersect 占大头
```

**Troubleshooting**:

- 球体看不到:检查球的位置和半径,可能不在视野内。试着把球放在 (0, 0, -2) 半径 0.5。
- 颜色异常:确保所有颜色在 [0, 1] 范围,clamp 一下。
- 球变形:检查 aspect_ratio 计算,可能 width/height 用反。
- 性能慢:确保用 `--release`,debug 模式慢 100 倍。
- glam Vec3 不是 SIMD:检查 glam feature flags,Cargo.toml 加 `glam = { version = "0.29", features = ["bytemuck"] }`,默认应该是 SIMD 化的。

## 9 · 延伸阅读(可选补充,非必需)

本仓库本地:
- [README.md](README.md) — Handmade Ray 系列总览
- [ray01.md](ray01.md) — 下一集
- [../phase-0/14-math-foundations.md](../phase-0/14-math-foundations.md) — 数学基础

外部稳定 URL(可选):
- Ray Tracing in One Weekend(Shirley 免费): https://raytracing.github.io/books/RayTracingInOneWeekend.html
- Scratchapixel Rendering Introduction: https://www.scratchapixel.com/lessons/3d-basic-rendering/what-is-ray-tracing.html
- PBRT-Book Chapter 1 & 3: https://www.pbr-book.org/3ed-2018/Introduction/Introduction
- Casey Handmade Hero ray00: https://guide.handmadehero.org/ray/ray00/

真实开源源码:
- Rust path tracer 参考实现:`smallpt-rs`(https://github.com/cebtenzzre/smallpt-rs)
- glam crate Vec3: https://github.com/bitshifter/glam/blob/main/src/f32/vec3.rs
