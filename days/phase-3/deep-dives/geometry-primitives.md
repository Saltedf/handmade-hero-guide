
# 几何图元深度专题

> 你跟着 HH Day 60 写碰撞检测。你的玩家是一个 AABB(轴对齐包围盒),墙也是 AABB。你写了 `aabb_vs_aabb` 函数,工作正常。然后你做一个旋转的怪物——它是一个 OBB(有向包围盒)。你试图用 AABB 测试它,但旋转后包围盒变大,碰撞精度极差。你查资料,发现 OBB vs OBB 用 SAT(Separating Axis Theorem)。SAT 又是什么?接下来你想做圆形子弹,要测 circle vs segment——直线段。然后你想做一个 capsule(胶囊)角色,因为 AABB 在斜坡上卡住……这是 HH 39 集涉及几何的全部,今天我们一次说透。

## 0 · 为什么要有这一篇

几何图元是游戏引擎、物理引擎、CAD、机器人学、计算机图形学的共同基础。Handmade Hero 用了 39 集涉及几何(从 day 50 的"点 vs 平面"到 day 200 的 convex hull + GJK)。一个看起来"简单"的概念(比如"线段"),背后有十几种数学表示,每种适合不同场景。

**这一篇要回答**:

1. Point / Line / Plane 各自有几种数学表示?哪种适合哪种场景?
2. AABB / OBB / Circle / Sphere / Capsule / Polygon 各自适合什么?
3. 凸包(convex hull)算法:Graham scan / Quickhull / Gift wrapping
4. Minkowski sum / difference 是什么?它在碰撞检测中怎么用?
5. subdivision surface 怎么让 3D 模型变平滑?
6. 参数化表示 vs 隐式表示 vs explicit 表示

**学完这一篇,你应该能**:
- 为不同场景选正确的图元(避免"用 AABB 杀圆形物体")
- 用 Rust 从零实现 SAT、GJK
- 解释凸包算法的复杂度和权衡
- 在游戏物理引擎里正确使用 capsule
- 理解 subdivision surface 的 Catmull-Clark 算法

## 1 · Point / Line / Plane

### 1.1 Point

最简单的图元。二维 (x, y),三维 (x, y, z),N 维 (x₁, x₂, ..., xₙ)。

```rust
type Point2 = glam::Vec2;
type Point3 = glam::Vec3;
```

### 1.2 Line 的三种表示

**1. Parametric(参数化)**:`P(t) = A + t·(B - A)`,t 是参数(任意实数)。线段 t∈[0,1]。

```rust
struct Line2 { a: Vec2, b: Vec2 }
impl Line2 {
    fn at(&self, t: f32) -> Vec2 {
        self.a + (self.b - self.a) * t
    }
}
```

**2. Implicit(隐式)**:`ax + by + c = 0`。判断点在直线哪侧:`d = a·x + b·y + c`。

```rust
struct Line2D { a: f32, b: f32, c: f32 }
impl Line2D {
    fn side(&self, p: Vec2) -> f32 {
        self.a * p.x + self.b * p.y + self.c
    }
    // side > 0 在线一侧,< 0 在另一侧,= 0 在线上
}
```

**3. Explicit(显式)**:`y = mx + b`。不能表达垂直线(m = ∞),少用。

**何时用什么**:
- **碰撞检测**:implicit(快速 side 测试)。
- **渲染 / 动画**:parametric(沿曲线插值)。
- **教学**:explicit(直觉)。

### 1.3 Line segment intersection

```rust
fn seg_seg_intersect(p1: Vec2, p2: Vec2, p3: Vec2, p4: Vec2) -> Option<Vec2> {
    let d1 = p2 - p1;
    let d2 = p4 - p3;
    let denom = d1.x * d2.y - d1.y * d2.x;
    if denom.abs() < 1e-9 { return None; }  // 平行

    let t = ((p3 - p1).x * d2.y - (p3 - p1).y * d2.x) / denom;
    let u = ((p3 - p1).x * d1.y - (p3 - p1).y * d1.x) / denom;

    if t < 0.0 || t > 1.0 || u < 0.0 || u > 1.0 { return None; }
    Some(p1 + d1 * t)
}
```

### 1.4 Plane

3D 平面的标准表示:`n · P + d = 0`,n 是法向量(单位),d 是从原点的偏移。

```rust
struct Plane { normal: Vec3, d: f32 }
impl Plane {
    fn from_point_normal(p: Vec3, n: Vec3) -> Self {
        Self { normal: n, d: -n.dot(p) }
    }
    fn side(&self, p: Vec3) -> f32 {
        self.normal.dot(p) + self.d
    }
    // side > 0:正侧,< 0:负侧,= 0:在平面上
}
```

**用途**:摄像机视锥体的 6 个面(近平面 / 远平面 / 4 个侧面),用于视锥剔除(frustum culling)。

## 2 · 2D 图元

### 2.1 AABB(Axis-Aligned Bounding Box)

轴对齐包围盒——边和坐标轴对齐。两个 corner 表示(min, max)。

```rust
#[derive(Clone, Copy)]
struct AABB2 { min: Vec2, max: Vec2 }

impl AABB2 {
    fn from_center_size(center: Vec2, size: Vec2) -> Self {
        let half = size * 0.5;
        Self { min: center - half, max: center + half }
    }

    fn contains(&self, p: Vec2) -> bool {
        p.x >= self.min.x && p.x <= self.max.x
        && p.y >= self.min.y && p.y <= self.max.y
    }

    fn intersects(&self, other: &AABB2) -> bool {
        self.min.x <= other.max.x && self.max.x >= other.min.x
        && self.min.y <= other.max.y && self.max.y >= other.min.y
    }
}
```

**优点**:**碰撞测试极快**(4 个比较),**易理解**。
**缺点**:**不能旋转**——一旦旋转,AABB 必须重新计算(变大)。

**何时用**:tile-based 游戏、space partitioning(BVH / quadtree 的内部节点)、first-pass broadphase 碰撞检测。

### 2.2 OBB(Oriented Bounding Box)

有向包围盒——可以旋转。中心 + 两个正交方向 + 半尺寸。

```rust
struct OBB2 {
    center: Vec2,
    axes: [Vec2; 2],   // 单位正交轴(local X, local Y)
    half_extents: Vec2,
}
```

**OBB vs OBB**:用 SAT(Separating Axis Theorem)。

#### SAT(Separating Axis Theorem)

定理:两个凸多边形**不重叠** ⟺ 存在一条轴(投影方向),两个多边形在这条轴上的投影**不重叠**。

对 OBB-OBB,测试 4 条轴:两个 OBB 各自的两条边法线。

```rust
fn obb_obb_separating(a: &OBB2, b: &OBB2) -> bool {
    let axes: [Vec2; 4] = [a.axes[0], a.axes[1], b.axes[0], b.axes[1]];
    for axis in axes {
        let (a_min, a_max) = project_obb(a, axis);
        let (b_min, b_max) = project_obb(b, axis);
        if a_max < b_min || b_max < a_min {
            return true;  // 分离轴存在,不重叠
        }
    }
    false  // 重叠
}

fn project_obb(o: &OBB2, axis: Vec2) -> (f32, f32) {
    let center = o.center.dot(axis);
    let r = o.half_extents.x * o.axes[0].dot(axis).abs()
          + o.half_extents.y * o.axes[1].dot(axis).abs();
    (center - r, center + r)
}
```

SAT 通用——3D 凸体之间也可以,只是测试轴变多(每个面的法线 + 每对边的 cross product)。

### 2.3 Circle / Sphere

```rust
struct Circle { center: Vec2, radius: f32 }

impl Circle {
    fn contains(&self, p: Vec2) -> bool {
        (p - self.center).length_squared() <= self.radius * self.radius
    }

    fn intersects(&self, other: &Circle) -> bool {
        let r = self.radius + other.radius;
        (other.center - self.center).length_squared() <= r * r
    }
}
```

**注意**:`length_squared` 而非 `length`——避免 sqrt,2-3 倍快。

3D 版叫 Sphere,代码几乎相同(替换 Vec2 为 Vec3)。

### 2.4 Polygon

```rust
struct Polygon2 { vertices: Vec<Vec2> }

impl Polygon2 {
    fn centroid(&self) -> Vec2 {
        self.vertices.iter().copied().sum::<Vec2>() / self.vertices.len() as f32
    }

    // 计算多边形面积(Shoelace formula)
    fn area(&self) -> f32 {
        let mut sum = 0.0;
        let n = self.vertices.len();
        for i in 0..n {
            let j = (i + 1) % n;
            sum += self.vertices[i].x * self.vertices[j].y;
            sum -= self.vertices[j].x * self.vertices[i].y;
        }
        sum.abs() * 0.5
    }

    // Point-in-polygon(射线法)
    fn contains(&self, p: Vec2) -> bool {
        let mut inside = false;
        let n = self.vertices.len();
        let mut j = n - 1;
        for i in 0..n {
            let vi = self.vertices[i];
            let vj = self.vertices[j];
            if (vi.y > p.y) != (vj.y > p.y) {
                let x_intersect = (vj.x - vi.x) * (p.y - vi.y) / (vj.y - vi.y) + vi.x;
                if p.x < x_intersect { inside = !inside; }
            }
            j = i;
        }
        inside
    }
}
```

**凸 vs 凹**:凸多边形 SAT 适用,凹不行。凹要分解成多个凸(delaunay 三角化 / HACD)。

## 3 · 3D 图元

### 3.1 3D AABB

```rust
struct AABB3 { min: Vec3, max: Vec3 }

impl AABB3 {
    fn center(&self) -> Vec3 { (self.min + self.max) * 0.5 }
    fn size(&self) -> Vec3 { self.max - self.min }
    fn intersects(&self, other: &AABB3) -> bool {
        self.min.x <= other.max.x && self.max.x >= other.min.x
        && self.min.y <= other.max.y && self.max.y >= other.min.y
        && self.min.z <= other.max.z && self.max.z >= other.min.z
    }
}
```

### 3.2 Sphere

```rust
struct Sphere { center: Vec3, radius: f32 }
```

### 3.3 Capsule

胶囊:一个线段 + 半径。两端是球,中间是圆柱。

```rust
struct Capsule {
    a: Vec3,    // 线段起点
    b: Vec3,    // 线段终点
    radius: f32,
}
```

**为何用 capsule**:角色(人形)的最佳碰撞形状。AABB 角色在斜坡上会卡住,OBB 复杂。capsule 的圆弧让它能平滑滑过斜坡和台阶。

**Capsule vs Capsule**:用最短距离——两个线段的最短距离 vs 半径和。

```rust
fn capsule_capsule_distance(a: &Capsule, b: &Capsule) -> f32 {
    let (pa, pb) = closest_points_between_segments(a.a, a.b, b.a, b.b);
    (pb - pa).length() - a.radius - b.radius
}

fn closest_points_between_segments(p1: Vec3, p2: Vec3, p3: Vec3, p4: Vec3) -> (Vec3, Vec3) {
    // ... 算法略,查 Real-Time Collision Detection 一书
    unimplemented!()
}
```

### 3.4 Mesh

三角形网格——大多数 3D 模型的表示。

```rust
struct Mesh {
    vertices: Vec<Vec3>,
    normals: Vec<Vec3>,
    indices: Vec<[u32; 3]>,  // 三角形索引
}
```

**Mesh vs Mesh 碰撞**:O(N²) 三角形对——慢。所以游戏物理用 capsule / AABB 做近似,mesh 只在"精确接触"时用(比如 raycast 检测击中)。

## 4 · Convex Hull(凸包)

### 4.1 定义

凸包:包含所有点的**最小凸形状**。想象在所有点外面套一根橡皮筋,橡皮筋的形状就是凸包。

工业用途:
- **碰撞检测**:复杂物体用其凸包做近似(GJK 算法)。
- **形状分析**:识别物体外形。
- **渲染优化**:剔除背面。

### 4.2 Gift Wrapping(Jarvis March)

最直觉的算法:从最左点开始,反复"绕绳子"——找下一个最右的点(对当前点所有其他点都"右转")。

复杂度:O(Nh),h 是凸包顶点数。最坏 O(N²)。

```rust
fn gift_wrap(points: &[Vec2]) -> Vec<Vec2> {
    if points.len() < 3 { return points.to_vec(); }
    let mut hull = Vec::new();

    // 找最左点
    let mut leftmost = 0;
    for i in 1..points.len() {
        if points[i].x < points[leftmost].x { leftmost = i; }
    }

    let mut p = leftmost;
    loop {
        hull.push(points[p]);
        let mut q = (p + 1) % points.len();
        for i in 0..points.len() {
            // 如果 i 比 q 更"右转",更新 q
            if cross(points[p], points[i], points[q]) > 0.0 {
                q = i;
            }
        }
        p = q;
        if p == leftmost { break; }
    }
    hull
}

// cross(o, a, b) > 0:左转,< 0:右转,= 0:共线
fn cross(o: Vec2, a: Vec2, b: Vec2) -> f32 {
    (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x)
}
```

### 4.3 Graham Scan

按角度排序所有点,然后用栈扫描——左转 push,右转 pop。

复杂度:O(N log N)(主要在排序)。

```rust
fn graham_scan(mut points: Vec<Vec2>) -> Vec<Vec2> {
    if points.len() < 3 { return points; }

    // 找最下点(若并列,取最左)
    let mut bottom = 0;
    for i in 1..points.len() {
        if points[i].y < points[bottom].y
        || (points[i].y == points[bottom].y && points[i].x < points[bottom].x) {
            bottom = i;
        }
    }
    points.swap(0, bottom);
    let pivot = points[0];

    // 按对 pivot 的极角排序
    points[1..].sort_by(|a, b| {
        let angle_a = (a.y - pivot.y).atan2(a.x - pivot.x);
        let angle_b = (b.y - pivot.y).atan2(b.x - pivot.x);
        angle_a.partial_cmp(&angle_b).unwrap()
    });

    // 扫描
    let mut hull: Vec<Vec2> = vec![points[0], points[1]];
    for i in 2..points.len() {
        while hull.len() >= 2 {
            let n = hull.len();
            if cross(hull[n-2], hull[n-1], points[i]) <= 0.0 {
                hull.pop();
            } else { break; }
        }
        hull.push(points[i]);
    }
    hull
}
```

### 4.4 Quickhull

借鉴 quicksort 的分治思路。找两个极点,把点分成两半,每半找最远的点构成三角形,递归。

复杂度:平均 O(N log N),最坏 O(N²)(但实际比 Graham 快)。

```rust
fn quickhull(points: &[Vec2]) -> Vec<Vec2> {
    if points.len() < 3 { return points.to_vec(); }

    // 找最左、最右
    let (mut left, mut right) = (0, 0);
    for (i, p) in points.iter().enumerate() {
        if p.x < points[left].x { left = i; }
        if p.x > points[right].x { right = i; }
    }

    let mut hull = Vec::new();
    hull.push(points[left]);
    let upper = find_hull(points, left, right, true);
    hull.extend(upper);
    hull.push(points[right]);
    let lower = find_hull(points, right, left, false);
    hull.extend(lower);
    hull
}

fn find_hull(points: &[Vec2], a: usize, b: usize, upper: bool) -> Vec<Vec2> {
    // 找到离 ab 最远的点(在 upper 或 lower 侧)
    let sign = if upper { 1.0 } else { -1.0 };
    let mut far_idx = None;
    let mut max_dist = 0.0;
    for (i, p) in points.iter().enumerate() {
        let d = sign * cross(points[a], points[b], *p);
        if d > 0.0 && d > max_dist {
            max_dist = d;
            far_idx = Some(i);
        }
    }
    if let Some(c) = far_idx {
        let mut result = Vec::new();
        result.push(points[c]);
        result.extend(find_hull(points, a, c, upper));
        result.extend(find_hull(points, c, b, upper));
        result
    } else {
        Vec::new()
    }
}
```

**Rust crate**:`chull`(纯 Rust,Graham + Quickhull)、`parry2d / parry3d`(物理库,带凸包)。

### 4.5 3D 凸包

3D 凸包算法:Quickhull 3D / Incremental。复杂度 O(N log N) 平均。

**Rust crate**:`chull`、`parry3d`、`cdcollide`。

## 5 · Minkowski Sum / Difference

### 5.1 定义

**Minkowski Sum** A ⊕ B = {a + b : a ∈ A, b ∈ B}。
**Minkowski Difference** A ⊖ B = {a - b : a ∈ A, b ∈ B}。

**直观理解**:A ⊕ B 是"把 B 沿 A 的所有点平移,扫过的区域"。
A ⊖ B 是"把 -B 沿 A 平移"——即"A 用 B '扫描' 的所有位置"。

### 5.2 关键定理

**A 和 B 重叠 ⟺ 原点 ∈ A ⊖ B**。

这是 GJK(Gilbert-Johnson-Keerthi)算法的核心。GJK 用 Minkowski Difference 检测碰撞——不需要计算整个 Minkowski Difference,只需要判断原点是否在内。

### 5.3 GJK 算法(简化)

```rust
fn gjk_intersect(a: &Shape, b: &Shape) -> bool {
    let mut simplex: Vec<Vec2> = Vec::new();
    let d = Vec2::X;
    simplex.push(support(a, b, d));
    let mut d = -simplex[0];

    loop {
        let new_point = support(a, b, d);
        if new_point.dot(d) < 0.0 {
            return false;  // 沿 d 方向找不到更远的点,不重叠
        }
        simplex.push(new_point);
        if contains_origin(&mut simplex, &mut d) {
            return true;
        }
    }
}

// Support 函数:Minkowski Difference 在方向 d 上的极点
fn support(a: &Shape, b: &Shape, d: Vec2) -> Vec2 {
    a.furthest_point(d) - b.furthest_point(-d)
}
```

GJK 复杂度:大多数情况 O(1)(simplex 几次迭代就收敛)。最坏 O(N) 但极罕见。

**优点**:适用于**任何**凸形状——AABB、Sphere、Capsule、Polygon、Mesh(凸),只要能算 support 函数。
**缺点**:不直接给穿透深度。需要 EPA 算法补完。

工业库:`parry2d / parry3d`(Rust)、Bullet Physics 的 GJK(C++)、Box2D 的 GJK。

## 6 · Subdivision Surfaces

### 6.1 模型

Subdivision surface 让一个粗糙的多边形网格**变平滑**。Catmull-Clark 算法(1978)是工业标准——Maya、Blender、Pixar 都用它。

思路:**每次细分,把每个面分成 4 个小面,新顶点位置按权重平均**。重复几次,网格变光滑,最终收敛到一个光滑曲面。

### 6.2 Catmull-Clark 步骤

每次细分:
1. **Face vertex**:每个面中心加一个新顶点(面的所有顶点平均)。
2. **Edge vertex**:每条边加一个新顶点(边的两端 + 共享该边的两个面中心,4 个点平均)。
3. **更新原有 vertex**:周围面中心和边端点的加权平均。

```rust
fn catmull_clark_subdivide(mesh: &Mesh) -> Mesh {
    // 实现略,几百行
    unimplemented!()
}
```

### 6.3 用途

- **角色建模**:Maya / Blender 的 subdivision surface modifier。
- **动画电影**:Pixar 用 OpenSubdiv 库渲染。
- **游戏**:静态模型离线 subdiv,然后 bake 成 normal map(运行时不用真实 subdiv,用 normal map 模拟)。

### 6.4 Rust 生态

| crate | 用途 |
|---|---|
| `isotope` | subdivision surface |
| `meshopt` | 网格优化 |
| `gltf` | 加载 .gltf 模型(支持 subdiv) |

## 7 · 参数化 vs 隐式 vs Explicit

### 7.1 三种表示

**Parametric(参数化)**:用参数 t 表示。`P(t) = (cos t, sin t, t)`。
- 优点:沿曲线容易采样(t 从 0 到 1)。
- 缺点:判断点在曲线上难(解方程)。

**Implicit(隐式)**:用方程表示。`x² + y² - r² = 0`。
- 优点:判断点在内 / 外 / 上容易(代入方程)。
- 缺点:沿曲线采样难(求根)。

**Explicit(显式)**:`y = f(x)`。
- 优点:简单。
- 缺点:不能表达垂直线 / 多值函数。

### 7.2 例:圆

- Parametric:`P(t) = (r cos t, r sin t)`
- Implicit:`x² + y² - r² = 0`
- Explicit:`y = ±√(r² - x²)`(双值,麻烦)

### 7.3 何时用什么

| 场景 | 推荐 |
|---|---|
| 碰撞检测(点在形状内?) | Implicit |
| 路径动画(沿曲线移动) | Parametric |
| Ray marching | Implicit(用 SDF) |
| 网格生成 | Parametric |

**现代 SDF 趋势**:把所有形状用 SDF(Signed Distance Field)表示,统一 implicit 形式。GPU shader 里 ray marching 渲染。Inigo Quilez 的网站 https://iquilezles.org/ 是 SDF 圣经。

## 8 · 游戏中的图元选择

### 8.1 角色碰撞

| 形状 | 适用 |
|---|---|
| AABB | 简单 2D 游戏(Mario 风格) |
| Circle | 2D 圆形敌人(弹幕游戏) |
| Capsule | 3D 人形角色(工业标配) |
| OBB | 旋转的车辆 / 长方形敌人 |

### 8.2 子弹

| 形状 | 适用 |
|---|---|
| Ray(射线) | 即时枪击(HitScan) |
| Sphere | 投射物(火球) |
| Line segment + radius = Capsule | 高速投射物(防 tunneling) |

### 8.3 环境

| 形状 | 适用 |
|---|---|
| AABB | Tile-based 关卡 |
| Triangle soup | 复杂静态几何(BSP) |
| Heightmap | 地形 |

### 8.4 Broadphase vs Narrowphase

工业物理引擎分两阶段:

1. **Broadphase(粗相)**:AABB 重叠测试,O(N²) 或 O(N log N)(BVH / sweep-and-prune)。找"可能碰撞对"。
2. **Narrowphase(细相)**:精确测试(SAT / GJK)。

Rapier(Rust 物理引擎)用 BVH + GJK/EPA 这套。

## 9 · Rust 实战速查

```rust
use glam::{Vec2, Vec3};

// AABB
let a = AABB2::from_center_size(Vec2::ZERO, Vec2::new(2.0, 2.0));
let b = AABB2::from_center_size(Vec2::new(1.0, 0.0), Vec2::new(1.0, 1.0));
assert!(a.intersects(&b));

// Circle
let c1 = Circle { center: Vec2::ZERO, radius: 1.0 };
let c2 = Circle { center: Vec2::new(0.5, 0.0), radius: 1.0 };
assert!(c1.intersects(&c2));

// Sphere distance
let dist = (s1.center - s2.center).length() - s1.radius - s2.radius;
let overlaps = dist < 0.0;
```

### 9.1 Crate 推荐

| crate | 用途 |
|---|---|
| `glam` | 数学 |
| `parry2d / parry3d` | 完整碰撞 + 凸包 + GJK |
| `rapier2d / rapier3d` | 物理引擎(基于 parry) |
| `ncollide2d` | parry 老版本,2D |
| `chull` | 凸包 |

## 10 · 延伸阅读

- **Real-Time Collision Detection**(Christer Ericson):碰撞检测圣经。
- **Geometric Tools**(David Eberly):https://www.geometrictools.com/
- Inigo Quilez 的 SDF 文章:https://iquilezles.org/articles/distfunctions/
- GJK 算法原始论文:https://ieeexplore.ieee.org/document/2083
- Catmull-Clark subdivision 论文:https://www.cs.drexel.edu/~david/Classes/PDM/Subdivision.pdf
- OpenSubdiv(Pixar):https://github.com/PixarAnimationStudios/OpenSubdiv
- Rapier 物理引擎:https://rapier.rs/
- parry 碰撞库:https://www.parry.rs/
- Red Blob Games 的几何文章:https://www.redblobgames.com/
- Casey HH 几何相关 day 列表:Day 50 / 55 / 60 / 70 / 80 / 95 / 110 / 130 / 145 / 160 / 180 / 200
