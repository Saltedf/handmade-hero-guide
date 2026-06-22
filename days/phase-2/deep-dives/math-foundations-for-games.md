---
phase: 2
type: deep-dive
title: "游戏数学基础:向量、矩阵、积分、几何"
domains: [game, graphics, math]
duration: "3h"
prereqs: ["day041", "day042", "day043", "day047", "day050", "phase-0/14-math-foundations"]
---

# 游戏数学基础 · 向量、矩阵、积分、几何

> Day 041 Casey 摆了一张数学工具图,Day 042-050 逐个用上。Day 070 Phase 2 收官,你需要的所有 2D 数学都过了。Phase 3 进 3D,数学密度翻倍。本文 3 小时把游戏数学的所有基础打牢:向量代数、矩阵变换、数值积分、几何相交、四元数入门。看完你读任何游戏引擎源码、任何图形学论文都不会卡在数学上。

## 0 · 这篇文章解决什么问题

数学在游戏开发里"看不见但决定一切"。你写:

```rust
player.pos.x += 5.0;
```

这行代码涉及**位置(向量)**和**位移变化率(积分)**。

你写:

```rust
if aabb_overlap(player, wall) { ... }
```

涉及**集合相交(几何)**和**线性代数**。

你写:

```rust
let dir = (target - player).normalized();
player.vel = dir * 50.0;
```

涉及**向量减法**、**归一化**、**标量乘法**——三个向量代数操作。

如果不懂这些,你只能"复制粘贴代码",改一行就坏。Casey 在 Day 041-050 把这些基础全讲完,本文再系统化一遍——从最基础(为什么用向量不用 (x,y) 变量)到进阶(为什么用四元数不用欧拉角)。

读完你能:

- 解释点积、叉积的几何意义和游戏用途
- 实现完整的 Vec2 / Vec3 / Mat4
- 推导 Euler / Verlet 积分的公式和误差
- 理解 Minkowski 差 / SAT / GJK 的几何直觉
- 知道什么时候该用四元数

## 1 · 向量代数

### 1.1 什么是向量

**向量(vector)**= 有方向和大小的量。在 2D 里两个数 `(x, y)`,在 3D 里三个数 `(x, y, z)`。

向量表示什么?可以是:
- **位置**:小人现在在 (5, 3)
- **位移**:从 A 到 B 走了 (3, -2)
- **速度**:每秒走 (0, -10)(向下 10 像素/秒)
- **加速度**:每秒速度变化 (0, 9.8)(重力)
- **方向**(归一化后):朝 (1, 0) 方向看(东)

同一个向量类型,在不同上下文表示不同物理量。**这是向量的强大之处**——一套数学描述所有。

### 1.2 为什么不分开用 (x, y) 变量

```rust
// 朴素写法
let player_x = 5.0;
let player_y = 3.0;
let vel_x = 0.0;
let vel_y = -10.0;
player_x += vel_x * dt;
player_y += vel_y * dt;
```

vs

```rust
let mut player = Vec2::new(5.0, 3.0);
let vel = Vec2::new(0.0, -10.0);
player += vel * dt;
```

向量版本的优势:

1. **简洁**:一行 vs 多行
2. **泛化**:换 3D 只要改 Vec2 → Vec3,代码逻辑不变
3. **类型安全**:编译器帮你检查"位置 + 速度"是不是合法操作
4. **可优化**:Vec2 连续 8 字节内存,SIMD 一次处理 4 个

### 1.3 向量运算

#### 加法(Add)

```
(a, b) + (c, d) = (a+c, b+d)
```

直觉:两个箭头首尾相接。第一个走 `(a,b)`,第二个走 `(c,d)`,合计 `(a+c, b+d)`。

游戏里:**位移合成**、**位置 + 速度×dt = 新位置**。

#### 减法(Sub)

```
(a, b) - (c, d) = (a-c, b-d)
```

直觉:从 c 到 a 的位移。

游戏里:**算两个 entity 的距离向量** `(b.pos - a.pos)`。

#### 标量乘法(Scalar Mul)

```
k * (a, b) = (ka, kb)
```

直觉:箭头长度变 k 倍(k > 0 方向不变,k < 0 方向反转)。

游戏里:**加速度 = 力 / 质量**、**位移 = 速度 × dt**。

#### 长度(Length / Magnitude)

```
|(a, b)| = sqrt(a² + b²)
```

勾股定理。**这是向量到原点的距离**。

游戏里:**算 entity 之间距离** `|(b.pos - a.pos)|`。

**优化**:用长度平方(`a² + b²`)避免 sqrt。比较时平方两边即可。

#### 归一化(Normalize)

```
v̂ = v / |v|
```

把长度变 1,只保留方向。**单位向量**。

游戏里:**朝某方向移动** `pos += dir * speed * dt`,dir 必须归一化。

**注意**:零向量 `(0,0)` 归一化未定义(0/0)。返回零向量(不报错)或 panic。

#### 点积(Dot Product)

```
a · b = ax*bx + ay*by
```

几何意义:`a · b = |a| |b| cos(θ)`,θ 是夹角。

游戏里:

- **判断方向关系**:a · b > 0 同侧,< 0 反侧,= 0 垂直
- **算投影**:a 在 b 方向上的投影长度 = (a · b) / |b|
- **算光照**(Lambert):`max(0, N · L)`
- **算视野**(NPC 能否看到玩家):`F · (P_player - P_npc) > 0`

#### 叉积(Cross Product,2D)

```
a × b = ax*by - ay*bx  (标量!)
```

几何意义:`a × b = |a| |b| sin(θ)`,符号告诉你 a 到 b 是顺时针(负)还是逆时针(正)。

游戏里:

- **判断点在直线哪侧**
- **三角形面积** = `|AB × AC| / 2`
- **线段相交**:两条线段相交 ⟺ 每条线段的两端点都在另一条的两侧

3D 叉积是**向量**,垂直于 a 和 b,右手定则确定方向。用于算三角形法线、力矩。

#### 反射(Reflect)

```
v' = v - 2(v · n)n
```

n 是墙的法向量(单位长度)。

游戏里:**弹球**、**光追反射**、**FPS 子弹跳**。

#### 旋转(Rotate 2D)

```
旋转 θ:
x' = x cos θ - y sin θ
y' = x sin θ + y cos θ
```

矩阵形式:

```
[x']   [cos θ  -sin θ] [x]
[y'] = [sin θ   cos θ] [y]
```

游戏里:**朝向旋转**(玩家转向目标)。

### 1.4 Rust 实现

```rust
#[derive(Copy, Clone, Debug, PartialEq)]
pub struct Vec2 { pub x: f32, pub y: f32 }

impl Vec2 {
    pub const ZERO: Self = Self { x: 0.0, y: 0.0 };

    pub const fn new(x: f32, y: f32) -> Self { Self { x, y } }

    pub fn dot(self, o: Self) -> f32 {
        self.x * o.x + self.y * o.y
    }

    pub fn cross(self, o: Self) -> f32 {
        self.x * o.y - self.y * o.x
    }

    pub fn length_squared(self) -> f32 { self.dot(self) }
    pub fn length(self) -> f32 { self.length_squared().sqrt() }

    pub fn normalized(self) -> Self {
        let len = self.length();
        if len > 1e-6 { Self::new(self.x / len, self.y / len) } else { Self::ZERO }
    }

    pub fn reflect(self, normal: Self) -> Self {
        // normal 必须归一化
        let d = self.dot(normal);
        Self::new(self.x - 2.0 * d * normal.x, self.y - 2.0 * d * normal.y)
    }

    pub fn rotate(self, theta: f32) -> Self {
        let (s, c) = theta.sin_cos();
        Self::new(self.x * c - self.y * s, self.x * s + self.y * c)
    }

    pub fn lerp(self, other: Self, t: f32) -> Self {
        Self::new(
            self.x + (other.x - self.x) * t,
            self.y + (other.y - self.y) * t,
        )
    }
}

impl std::ops::Add for Vec2 {
    type Output = Self;
    fn add(self, o: Self) -> Self { Self::new(self.x + o.x, self.y + o.y) }
}
impl std::ops::Sub for Vec2 {
    type Output = Self;
    fn sub(self, o: Self) -> Self { Self::new(self.x - o.x, self.y - o.y) }
}
impl std::ops::Mul<f32> for Vec2 {
    type Output = Self;
    fn mul(self, k: f32) -> Self { Self::new(self.x * k, self.y * k) }
}
impl std::ops::AddAssign for Vec2 {
    fn add_assign(&mut self, o: Self) { self.x += o.x; self.y += o.y; }
}
```

## 2 · 矩阵代数

### 2.1 为什么用矩阵

向量运算只能表达"加法、缩放"。复杂变换(旋转 + 平移 + 缩放组合)需要矩阵。

矩阵让你:

- 把多个变换"打包"成一个矩阵
- 复合变换 = 矩阵乘法
- 同一个矩阵应用到所有顶点

### 2.2 2D 仿射变换

2D 平面变换用 3×3 矩阵(齐次坐标)。把 (x, y) 加一个虚拟的 1 → (x, y, 1)。

```
[x']   [a b c] [x]
[y'] = [d e f] [y]
[1 ]   [0 0 1] [1]
```

#### 平移

```
[1 0 tx]
[0 1 ty]
[0 0 1 ]
```

#### 缩放

```
[sx 0  0]
[0  sy 0]
[0  0  1]
```

#### 旋转(2D)

```
[cos θ  -sin θ  0]
[sin θ   cos θ  0]
[0       0      1]
```

#### 复合

矩阵乘法。先平移 T,后旋转 R,总变换 = R × T(注意顺序:右边的先应用)。

### 2.3 3D 变换

3D 用 4×4 矩阵(齐次坐标 (x, y, z, 1))。

#### 平移

```
[1 0 0 tx]
[0 1 0 ty]
[0 0 1 tz]
[0 0 0 1]
```

#### 绕 X 轴旋转

```
[1    0       0    ]
[0  cos θ  -sin θ ]
[0  sin θ   cos θ ]
```

#### 绕 Y / Z 类似

#### 缩放

对角矩阵 `[sx, sy, sz, 1]`。

### 2.4 MVP 矩阵

3D 图形学最经典的链:

```
模型空间 (object coords)
    ↓ Model matrix(模型到世界)
世界空间 (world coords)
    ↓ View matrix(世界到相机)
相机空间 (eye coords)
    ↓ Projection matrix(相机到裁剪)
裁剪空间 (clip coords)
    ↓ 透视除法
NDC(规范化设备坐标)
    ↓ Viewport transform
屏幕像素
```

总变换 = Projection × View × Model。

### 2.5 Rust 实现简版

```rust
#[derive(Copy, Clone, Debug)]
pub struct Mat4(pub [[f32; 4]; 4]);  // row-major

impl Mat4 {
    pub fn identity() -> Self {
        Self([
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ])
    }

    pub fn translation(tx: f32, ty: f32, tz: f32) -> Self {
        let mut m = Self::identity();
        m.0[0][3] = tx;
        m.0[1][3] = ty;
        m.0[2][3] = tz;
        m
    }

    pub fn scaling(sx: f32, sy: f32, sz: f32) -> Self {
        let mut m = Self::identity();
        m.0[0][0] = sx;
        m.0[1][1] = sy;
        m.0[2][2] = sz;
        m
    }

    pub fn rotation_x(theta: f32) -> Self {
        let (s, c) = theta.sin_cos();
        let mut m = Self::identity();
        m.0[1][1] = c; m.0[1][2] = -s;
        m.0[2][1] = s; m.0[2][2] = c;
        m
    }

    pub fn mul(self, o: Self) -> Self {
        let mut result = [[0f32; 4]; 4];
        for i in 0..4 {
            for j in 0..4 {
                for k in 0..4 {
                    result[i][j] += self.0[i][k] * o.0[k][j];
                }
            }
        }
        Self(result)
    }

    pub fn transform_point(self, p: [f32; 3]) -> [f32; 3] {
        let homogeneous = [p[0], p[1], p[2], 1.0];
        let mut result = [0f32; 4];
        for i in 0..4 {
            for k in 0..4 {
                result[i] += self.0[i][k] * homogeneous[k];
            }
        }
        // 透视除法(如果 w != 1)
        [result[0] / result[3], result[1] / result[3], result[2] / result[3]]
    }
}
```

## 3 · 数值积分

### 3.1 什么是积分

**积分 = 累积变化**。

- 速度是位置的积分:`position(t) = ∫ velocity(t) dt`
- 加速度是速度的积分:`velocity(t) = ∫ acceleration(t) dt`

游戏不解析解积分,用数值方法。

### 3.2 Euler 积分(最简单)

```
每帧:
    v += a * dt
    p += v * dt
```

误差 O(dt)。dt 越小越准。60 FPS 的 dt = 1/60,误差 ~ 1.7%,游戏完全可接受。

**优点**:极简,1 行
**缺点**:能量不守恒(模拟弹簧会"爆炸"),不适合物理引擎

### 3.3 半隐式 Euler(Semi-implicit)

```
每帧:
    v += a * dt       ← 先更新 v
    p += v * dt       ← 用新的 v 算 p
```

注意和 Euler 的区别:Euler 用**旧 v**算 p,半隐式用**新 v**算 p。

**优点**:能量更好守恒,稳定性高
**缺点**:仍然 1 阶精度

Casey 在 HH 用这个(或 Euler)。

### 3.4 Verlet 积分

```
保存上一帧 position(p_prev)。
每帧:
    p_new = 2*p - p_prev + a * dt²
    p_prev = p
    p = p_new
```

**优点**:能量极好守恒,2 阶精度,不需要显式存 v
**缺点**:对突变加速度响应慢

适合布料、绳子、粒子系统。

### 3.5 RK4(Runge-Kutta 4 阶)

每步算 4 次 derivative,加权平均。**4 阶精度**,误差 O(dt⁴)。

**优点**:精度极高
**缺点**:4 倍计算量,游戏不用(性价比低)

适合轨道力学、精确科学仿真。

### 3.6 游戏怎么选

| 场景 | 推荐 |
|---|---|
| 一般游戏(玩家移动) | Euler / 半隐式 Euler |
| 物理(弹簧、布料) | Verlet |
| 精确仿真(航天) | RK4 |
| 大量粒子 | Verlet(GPU 友好) |

Casey 在 HH 用半隐式 Euler。Phase 4+ 性能优化时考虑 Verlet。

## 4 · 几何相交

### 4.1 距离

- **点到点**:`|(a - b)|`
- **点到线段**:线段 AB,点 P。先参数化:`t = clamp((P-A)·(B-A) / |B-A|², 0, 1)`,最近点是 `A + t*(B-A)`。距离 = `|P - closest|`。
- **点到平面**(3D):`(P - plane_point) · plane_normal`

### 4.2 投影

- **点 P 到方向 d 的投影长度**:`P · d`(d 归一化)
- **向量 a 到 b 的投影向量**:`(a · b / |b|²) * b`

### 4.3 重心坐标(Barycentric)

三角形 ABC 内一点 P,可以表示为 `αA + βB + γC`,其中 `α + β + γ = 1`。

`α, β, γ` 就是重心坐标。游戏里用于:

- 判断点在三角形内(所有 α, β, γ 都在 [0, 1])
- 插值顶点属性(颜色、UV、法线)

### 4.4 线段相交(2D)

两条线段 AB 和 CD。相交 ⟺ 满足 4 个条件:

1. C 和 D 在 AB 的两侧:`(B-A) × (C-A)` 和 `(B-A) × (D-A)` 异号
2. A 和 B 在 CD 的两侧:`(D-C) × (A-C)` 和 `(D-C) × (B-C)` 异号

```rust
fn segments_intersect(a: Vec2, b: Vec2, c: Vec2, d: Vec2) -> bool {
    let d1 = (b - a).cross(c - a);
    let d2 = (b - a).cross(d - a);
    let d3 = (d - c).cross(a - c);
    let d4 = (d - c).cross(b - c);
    (d1 * d2 < 0.0) && (d3 * d4 < 0.0)
}
```

### 4.5 AABB 相交(2D)

Day 050 讲过:

```
|a.center - b.center| < a.half + b.half(分量级)
```

### 4.6 球 vs 球(3D)

```
|c1 - c2| < r1 + r2
```

### 4.7 圆 vs 线段(2D)

圆心 C,半径 r。线段 AB。算 C 到 AB 的最近点 Q。如果 |C - Q| < r,相交。

### 4.8 三角形 vs 三角形(3D)

经典 Möller 算法。本质:三角形 ABC 所在平面把空间分两半,如果三角形 DEF 的三个顶点都在同一半,不相交;否则可能有交,继续细分。

游戏里很少直接做三角形 vs 三角形(慢),用包围盒预筛。

## 5 · 四元数入门

### 5.1 为什么用四元数

3D 旋转有 3 种表示:

1. **欧拉角(Yaw / Pitch / Roll)**:直观,但有 Gimbal Lock(万向锁)问题——某方向旋转后,另两个轴重合,失去自由度
2. **旋转矩阵**:稳定,但 9 个数(冗余),插值困难
3. **四元数(Quaternion)**:4 个数,无 Gimbal Lock,插值平滑(slerp)

### 5.2 四元数定义

```
q = w + xi + yj + zk   (i, j, k 是虚单位)
或 (w, x, y, z) 向量形式
```

单位四元数(`|q| = 1`)表示 3D 旋转。

绕轴 u(单位向量)旋转 θ:

```
q = (cos(θ/2), sin(θ/2)*u.x, sin(θ/2)*u.y, sin(θ/2)*u.z)
```

### 5.3 四元数乘法

```
q1 * q2 = ...复杂公式,见维基百科
```

四元数乘法**不交换**(`q1 * q2 != q2 * q1`)。

### 5.4 旋转复合

两个旋转 q1 和 q2,复合 = q2 * q1(注意顺序,先 q1 后 q2)。

### 5.5 Slerp(球面线性插值)

```
slerp(q1, q2, t) = (q1 * sin((1-t)*θ) + q2 * sin(t*θ)) / sin(θ)
```

θ 是 q1 和 q2 的夹角。

用于动画:角色从姿势 A 平滑过渡到姿势 B。

### 5.6 Rust 实现简版

```rust
#[derive(Copy, Clone, Debug)]
pub struct Quat { pub w: f32, pub x: f32, pub y: f32, pub z: f32 }

impl Quat {
    pub fn identity() -> Self { Self { w: 1.0, x: 0.0, y: 0.0, z: 0.0 } }

    pub fn from_axis_angle(axis: Vec3, theta: f32) -> Self {
        let half = theta * 0.5;
        let s = half.sin();
        Self {
            w: half.cos(),
            x: axis.x * s,
            y: axis.y * s,
            z: axis.z * s,
        }
    }

    pub fn mul(self, o: Self) -> Self {
        Self {
            w: self.w*o.w - self.x*o.x - self.y*o.y - self.z*o.z,
            x: self.w*o.x + self.x*o.w + self.y*o.z - self.z*o.y,
            y: self.w*o.y - self.x*o.z + self.y*o.w + self.z*o.x,
            z: self.w*o.z + self.x*o.y - self.y*o.x + self.z*o.w,
        }
    }
}
```

Casey 在 Phase 3(3D)开始用四元数。Phase 2(2D)不需要——2D 旋转只有一个角度,普通 `f32` 足够。

## 6 · 三角函数速查

游戏里常用的:

- `sin / cos`:旋转、波形、振荡
- `atan2(y, x)`:从向量算角度
- `sqrt`:长度、距离(用 `mul_add` 加速)
- `pow / exp / log`:少见(指数衰减、对数缩放)
- `abs / min / max / clamp`:基本工具

注意:**避免在热路径用 sin/cos**——它们 10-15 cycles。预算用 LUT(查找表)或泰勒展开。

## 7 · 浮点数精度陷阱

### 7.1 浮点不严格相等

```rust
let a = 0.1 + 0.2;
let b = 0.3;
assert!(a == b);  // 失败!a 实际是 0.30000000000000004
```

永远用 `abs(a - b) < epsilon`(epsilon = 1e-6 或更小)。

### 7.2 大数加小数

```rust
let big = 1e10;
let small = 1e-10;
let sum = big + small;  // 等于 big,small 被吃掉
```

f32 只有 24 位尾数(约 7 位十进制)。`1e10 + 1e-10 = 1e10`,精度丢失。

游戏里:position 不要无限累加。世界大到一定程度要"rebase"(把所有 entity 平移到原点附近)。

### 7.3 NaN 传播

```rust
let nan = 0.0 / 0.0;  // NaN
let x = nan + 1.0;   // 还是 NaN
let y = nan < 1.0;   // false
let z = nan == nan;  // false(NaN 不等于自己)
```

NaN 像病毒,任何运算都传播。游戏代码每个 update 后检查 NaN,发现就 panic(防止"角色瞬移到 NaN 位置"的 bug)。

### 7.4 Infinity

```rust
let inf = 1.0 / 0.0;  // f32 不 panic,返回 inf
```

`inf - inf = NaN`,`inf * 0 = NaN`。小心。

## 8 · 游戏数学工具箱速查

| 我要做什么 | 用什么 |
|---|---|
| 算两个 entity 距离 | `|(b.pos - a.pos)|` |
| 算朝某方向移动 | `pos += dir.normalized() * speed * dt` |
| 判断玩家在 NPC 视野内 | `npc.facing.dot((player.pos - npc.pos).normalized()) > cos(half_fov)` |
| 反弹(撞墙) | `v = v.reflect(wall.normal)` |
| 算光照(Lambert 漫反射) | `max(0, N · L) * light_color` |
| 旋转 2D 向量 | `(x*cos - y*sin, x*sin + y*cos)` |
| 旋转 3D 朝向 | 用四元数 |
| 平滑跟随(camera) | `pos = pos.lerp(target, 0.1)` |
| 缓动 | `ease_in_out(t) = t * t * (3 - 2*t)` |
| 判断点在三角形内 | 重心坐标 |
| 判断两线段相交 | 叉积 4 次比较 |

## 9 · Rust crate 推荐

### 9.1 glam(推荐,Bevy 默认)

```toml
[dependencies]
glam = "0.29"
```

```rust
use glam::{Vec2, Vec3, Mat4, Quat};
```

- 性能极好(SIMD)
- API 简洁
- Bevy 默认

### 9.2 nalgebra(科学计算)

```toml
nalgebra = "0.33"
```

- 泛型维度(`Vector2<f32>`, `Vector3<f32>`, ...)
- 矩阵分解(SVD, 特征值)
- 适合仿真,游戏不用

### 9.3 cgmath(老牌,逐渐被 glam 取代)

类似 glam,API 风格更接近 C++ GLM。

### 9.4 pathfinding(寻路)

```toml
pathfinding = "4"
```

A* / Dijkstra / BFS 等寻路算法。

### 9.5 Casey HH 风格(手写)

Phase 1-3 学习时手写,理解每一行。Phase 5+ 切 glam。

## 10 · 业界数学库对比

| 引擎 / 库 | 数学库 | 特点 |
|---|---|---|
| Unity | Mathf + Mathf3 + 自带 | C# 风格,函数式 |
| Unreal | FVector / FMatrix(C++) | 和 UE 类型系统深度集成 |
| Godot | Vector2/3 (C++) | 教学清晰 |
| Casey HH | hand_math.h(C) | 最简朴,教学 |
| Bevy | glam | SIMD,工业级 |
| three.js | THREE.Vector3 | JS,GC 友好 |

数学库的核心概念都一样,差别在表达和优化程度。

## 11 · 延伸阅读

本仓库:
- [day041.md](day041.md) —— 游戏数学概览
- [day042.md](day042.md) —— Vec2 详细
- [day043.md](day043.md) —— 运动方程
- [day044.md](day044.md) —— 反射
- [day047.md](day047.md) —— 向量长度
- [day048.md](day048.md) —— 线段相交
- [day050.md](day050.md) —— Minkowski 碰撞
- [phase-0/14-math-foundations.md](../phase-0/14-math-foundations.md) —— 线性代数基础

外部:
- 3D Math Primer(免费在线): https://gamemath.com/
- LearnOpenGL Transformations: https://learnopengl.com/Getting-started/Transformations
- Essence of Linear Algebra(3Blue1Brown 视频): https://www.3blue1brown.com/topics/linear-algebra
- Real-Time Rendering (Akenine-Möller et al): https://www.realtimerendering.com/

开源源码:
- glam: https://github.com/bitshifter/glam
- nalgebra: https://github.com/dimforge/nalgebra
- cgmath: https://github.com/rustgd/cgmath
