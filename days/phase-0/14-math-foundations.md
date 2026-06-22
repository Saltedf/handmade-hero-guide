---
article: 14
phase: 0
title: "数学基础:向量 / 点积 / 叉积 / 矩阵 / 数值积分(从零讲)"
type: concept
difficulty: 3
duration: "3-4h"
domains: [math, graphics, game, rust]
prereqs: ["03-rust-from-scratch-1"]
---

# 14 · 数学基础:向量 / 点积 / 叉积 / 矩阵 / 数值积分(从零讲)

> Phase 2 之后每一集都依赖数学。Casey 在 Day 41 把数学工具箱摆开,但他不教数学——他假设你学过。这一篇就是补这个假设:从"向量是什么"讲起,把向量 / 点积 / 叉积 / 矩阵 / 积分五大件从零讲透。如果你学校数学课没学(或忘了),这一篇救你后面 600 天。

## 0 · 为什么要有这一天

你写了一段代码让方块在屏幕上动:

```rust
x += 1;
y += 0;
```

方块的 (x, y) 每帧 +1,水平往右走。好。现在你想做下面任意一件事,你的代码会瞬间失控:

1. **让方块朝右上 45° 走** —— 是 `x += 1; y += ?`,y 加多少?
2. **让方块越走越快**(加速) —— 每帧速度增加,然后位置用新速度?
3. **让方块撞墙后按物理规律反弹** —— 反弹方向怎么算?
4. **让 NPC "看"玩家**(视野判断) —— NPC 朝向 · 玩家方向 = 多少时算"看到"?
5. **把整个游戏画面旋转 30°** —— 每个像素的新坐标怎么算?
6. **3D 立方体在屏幕上转** —— 3 个角度,3 个坐标,怎么映射到 2D 屏幕?

这 6 件事每一件都依赖你**手头有数学工具**:
- 1 用向量加法
- 2 用加速度 + 数值积分
- 3 用反射公式(点积)
- 4 用点积(角度)
- 5 用 2D 旋转矩阵
- 6 用 3D 投影矩阵

如果你不懂这些数学,你只能"目测调参"——效果差,改不动,易出 bug。**这一篇的目标**:让你不仅会用公式,还**理解为什么**——这样你后面看 Casey 任何手推公式,都能跟上。

**心理锚点**:这一篇读完,你能:
- 用向量 `(x, y)` 表示位置 / 速度 / 方向,知道加 / 减 / 数乘的几何意义
- 解释点积 `a · b = |a||b|cosθ` 为什么,知道它在游戏里 5 种用途
- 解释叉积的几何意义(2D 标量、3D 向量),会用法线公式
- 用 2×2 / 3×3 矩阵做旋转 / 缩放 / 平移,知道 4×4 齐次坐标干什么
- 用 Euler 积分让"位置 / 速度 / 加速度"在游戏中演化
- 用 Rust 实现以上所有

## 1 · 概念地图:游戏开发用的 5 大数学件

| 件 | 是什么 | 解决什么问题 |
|---|---|---|
| **向量(Vector)** | 一组数(2D 是 `(x,y)`,3D 是 `(x,y,z)`),表示位置/方向/位移 | "东西在哪、朝哪、走多远" |
| **点积(Dot Product)** | 两向量"乘积",得到一个数 | "两向量有多对齐 / 角度 / 投影" |
| **叉积(Cross Product)** | 两向量的"乘积",得到一个向量(3D)或标量(2D) | "两向量定义的平面法线 / 旋转方向" |
| **矩阵(Matrix)** | 数的二维表,表达线性变换 | 旋转 / 缩放 / 投影 / 复合变换 |
| **数值积分(Numerical Integration)** | 用计算机近似算微积分 | 让运动方程在每帧演化 |

**关键**:这些不是孤立的"数学概念",它们是工具。每个工具有一个**几何直觉**(为什么这么算)+ 一组**游戏应用**(拿来干嘛)。

## 2 · 心智模型

### 类比:数学是游戏的"几何语法"

数学课本教你向量 = "线性空间元素,满足 8 条公理",然后让你证 8 条公理。游戏开发不这么用——它把向量当作"屏幕上的箭头",关心:

- 这个箭头**多长**(长度)
- 这个箭头**朝哪**(方向)
- 两个箭头**加起来**是新箭头
- 两个箭头**有多对齐**(点积)

你只要理解这 4 个直觉,后面所有公式都是它们的代数表达。

### 第一原理:位置 / 位移 / 方向

在游戏世界里,我们关心 3 件事:

1. **位置(Position)**:小人在哪,记作 `P = (3, 5)`(屏幕坐标)
2. **位移(Displacement)**:从 A 到 B 走了多少,记作 `D = B - A`
3. **方向(Direction)**:小人的朝向,通常用单位向量(长度 1 的向量)

**关键洞察**:这三件事**用同一个数学对象表示——向量**。这听起来没什么,但这是数学的优雅之处:**位置和位移可以相加**(新位置 = 原位置 + 位移),**位移可以相减**(B 相对 A 的位移)。

```
位置:           A = (1, 2), B = (4, 6)
A 到 B 的位移:  D = B - A = (4-1, 6-2) = (3, 4)
新位置:         A + D = (1+3, 2+4) = (4, 6)  ✓ 等于 B
```

### 2.1 向量(Vector)

#### 严谨定义

向量是**有方向的数**,在 2D 用 `(x, y)` 表示,3D 用 `(x, y, z)`。

**几何表示**:从原点 (0,0) 指向点 (x,y) 的箭头。

**长度**(magnitude / norm):

```
2D:  |v| = √(x² + y²)
3D:  |v| = √(x² + y² + z²)
```

这就是**勾股定理**——从 (0,0) 到 (x,y) 的直线距离。

**单位向量**(unit vector):长度为 1 的向量。把任意向量变成单位向量叫**归一化(normalize)**:

```
v̂ = v / |v|
```

读作 "v hat"。如果 `v = (3, 4)`,`|v| = 5`,`v̂ = (0.6, 0.8)`。

#### 向量运算

**加法**(几何:平行四边形法则 / 三角形法则):

```
(1, 2) + (3, 4) = (4, 6)
```

直觉:两个箭头**首尾相接**,新箭头从第一个起点指向第二个终点。

**减法**:

```
(4, 6) - (1, 2) = (3, 4)
```

直觉:从 A 到 B 的位移。

**数乘(scalar multiplication)**:

```
3 * (1, 2) = (3, 6)
```

直觉:把箭头拉长 3 倍(方向不变)。负数会反向:`-1 * (1, 2) = (-1, -2)`。

#### 为什么要用向量而不是分开的 (x, y)?

代码对比:

```rust
// ❌ 笨:用两个独立变量
let player_x: f32 = 0.0;
let player_y: f32 = 0.0;
let velocity_x: f32 = 1.0;
let velocity_y: f32 = 1.0;
player_x += velocity_x * dt;
player_y += velocity_y * dt;

// ✅ 好:用向量
let mut player = Vec2::new(0.0, 0.0);
let velocity = Vec2::new(1.0, 1.0);
player = player + velocity * dt;
```

第二个版本**一行搞定**,而且:
- 类型上区分"位置 / 速度"(都是 Vec2)
- 易于扩展 3D:把 Vec2 换 Vec3
- 操作语义清晰(`+` 是位移合成)

#### Rust 实现

```rust
#[derive(Copy, Clone, Debug, PartialEq)]
pub struct Vec2 {
    pub x: f32,
    pub y: f32,
}

impl Vec2 {
    pub const ZERO: Self = Self { x: 0.0, y: 0.0 };
    pub const ONE: Self = Self { x: 1.0, y: 1.0 };

    pub fn new(x: f32, y: f32) -> Self {
        Self { x, y }
    }

    pub fn add(self, other: Self) -> Self {
        Self { x: self.x + other.x, y: self.y + other.y }
    }

    pub fn sub(self, other: Self) -> Self {
        Self { x: self.x - other.x, y: self.y - other.y }
    }

    pub fn scale(self, k: f32) -> Self {
        Self { x: self.x * k, y: self.y * k }
    }

    pub fn length(self) -> f32 {
        // 勾股定理:√(x² + y²)
        self.x.hypot(self.y)   // Rust 的 f32::hypot,等价于 (x²+y²).sqrt()
    }

    pub fn length_squared(self) -> f32 {
        // 不开根号,常用于比较(避免 sqrt 开销)
        self.x * self.x + self.y * self.y
    }

    pub fn normalize(self) -> Self {
        let len = self.length();
        if len > 1e-6 {
            self.scale(1.0 / len)
        } else {
            Self::ZERO   // 零向量没有方向,我们定义返回零向量
        }
    }
}
```

**关键注释**:
- `#[derive(Copy)]` —— Vec2 是 8 字节(两个 f32),按值复制比引用快
- `length_squared` —— 经常用于"比较两个长度",不开根号省 50+ 周期
- `1e-6` —— 浮点零容忍阈值,因为浮点比较不可靠
- `hypot()` —— 标准库提供的 `(x² + y²).sqrt()`,数值更稳定(避免中间溢出)

### 2.2 点积(Dot Product)

#### 定义

2D:
```
a · b = ax * bx + ay * by
```

3D:
```
a · b = ax * bx + ay * by + az * bz
```

读作 "a dot b"。结果是一个**标量**(普通数字,不是向量)。

#### 几何意义:为什么是 cosθ

**定理**:`a · b = |a| |b| cos(θ)`,θ 是 a 和 b 的夹角。

**推导**(关键!这一段让你彻底理解点积):

设 `|a| = α`,`|b| = β`。考虑 `a - b` 的长度:

```
|a - b|² = (a - b) · (a - b)
         = a·a - a·b - b·a + b·b
         = |a|² - 2(a·b) + |b|²
         = α² - 2(a·b) + β²
```

另一方面,根据**余弦定理**(初中学过的):

```
|a - b|² = α² + β² - 2αβ cos(θ)
```

两个等式联立,消去 |a - b|² 和 α² + β²:

```
-2(a·b) = -2αβ cos(θ)
a · b = αβ cos(θ) = |a| |b| cos(θ)   □
```

#### 直觉

`a · b = |a| |b| cos(θ)` 告诉你:

| θ | cos(θ) | a·b |
|---|---|---|
| 0°(同向) | 1 | `\|a\|\|b\|`(最大正值) |
| 60° | 0.5 | `\|a\|\|b\| / 2` |
| 90°(垂直) | 0 | **0** |
| 120° | -0.5 | `-\|a\|\|b\| / 2` |
| 180°(反向) | -1 | `-\|a\|\|b\|`(最大负值) |

**直觉**:点积衡量"两个箭头有多对齐"。
- 同向 → 大正数
- 垂直 → 0
- 反向 → 大负数

#### 用点积算角度

```
cos(θ) = (a · b) / (|a| |b|)
θ = acos((a · b) / (|a| |b|))
```

如果 a 和 b 都是单位向量(长度 1),简化为:

```
θ = acos(a · b)
```

**游戏技巧**:很多场合你**不需要算 θ**,只要看 a·b 的符号:
- `a · b > 0`:两向量同向半边(θ < 90°)
- `a · b == 0`:垂直
- `a · b < 0`:反向半边(θ > 90°)

#### 用点积做投影

把向量 a 投影到向量 b 方向上的长度:

```
proj_length = a · b̂    (b̂ 是 b 的单位向量)
proj_vector = (a · b̂) b̂
```

#### 游戏里的 5 大用途

1. **光照(Lambert 漫反射)**:`brightness = max(0, N · L)`
   - N:表面法线(垂直于表面的单位向量)
   - L:从表面指向光源的单位向量
   - N·L=1:光直射,最亮
   - N·L=0:光平行掠过,边缘
   - N·L<0:光在背面(用 max(0, ...) 截断成黑)

2. **AI 视野判断**:NPC 朝向 F,NPC 到玩家方向 P(都归一化)
   - `F · P > cos(half_fov)`:玩家在 NPC 视野内
   - half_fov:视野半锥角(60° 视野对应 half_fov = 30°)

3. **背面剔除**(3D):三角形法线 N,相机到三角形方向 V
   - `N · V > 0`:三角形背朝相机,不画
   - 这是性能优化(渲染一半三角形不画)

4. **运动方向判定**:玩家速度 V,某目标方向 D
   - `V · D > 0`:玩家在朝目标移动
   - 用于"是否需要转身"

5. **距离投影**(2D 平台游戏):玩家 P,墙的法线 N
   - 玩家到墙的"穿透深度" = `(P - wall_point) · N`

#### Rust 实现

```rust
impl Vec2 {
    pub fn dot(self, other: Self) -> f32 {
        self.x * other.x + self.y * other.y
    }

    /// 投影 self 到 other 方向上的向量
    pub fn project_onto(self, other: Self) -> Self {
        let denom = other.dot(other);   // |other|²
        if denom > 1e-6 {
            let k = self.dot(other) / denom;
            other.scale(k)
        } else {
            Self::ZERO
        }
    }

    /// 和 other 的夹角(弧度)
    pub fn angle_to(self, other: Self) -> f32 {
        let cos = self.dot(other) / (self.length() * other.length());
        // 浮点精度可能让 cos > 1 或 < -1,clamp 一下
        cos.clamp(-1.0, 1.0).acos()
    }
}
```

**注释**:
- `project_onto` 用 `(a·b)/|b|² * b` 而不是 `(a·b̂)b̂`,省一次归一化
- `clamp(-1.0, 1.0)` 防止 acos 收到浮点误差导致的 -1.000001(NaN)

### 2.3 叉积(Cross Product)

#### 2D 叉积:标量

```
a × b = ax * by - ay * bx
```

结果是一个**标量**(普通数字)。

**几何意义**:`a × b = |a| |b| sin(θ)`,**符号**告诉你从 a 到 b 是顺时针(负)还是逆时针(正)。

| a × b 的符号 | 含义 |
|---|---|
| > 0 | b 在 a 的"左侧"(从 a 逆时针转到 b 角度 < 180°) |
| = 0 | a 和 b 共线 |
| < 0 | b 在 a 的"右侧"(从 a 顺时针转到 b 角度 < 180°) |

#### 2D 叉积的用途

1. **判断点在直线哪侧**:有向线段从 A 到 B,点 P
   ```
   side = (B - A) × (P - A)
   ```
   `side > 0`:P 在 AB 左侧;`side < 0`:右侧;`side = 0`:在线上。

2. **线段相交判断**:两条线段 AB 和 CD 相交 ⟺
   - C 和 D 在 AB 两侧(`(B-A)×(C-A)` 和 `(B-A)×(D-A)` 异号)
   - A 和 B 在 CD 两侧(`(D-C)×(A-C)` 和 `(D-C)×(B-C)` 异号)

3. **三角形面积**:`|AB × AC| / 2`

#### 3D 叉积:向量

```
a × b = (ay*bz - az*by,
         az*bx - ax*bz,
         ax*by - ay*bx)
```

**几何意义**:
- 长度:`|a × b| = |a| |b| sin(θ)`(平行四边形面积)
- 方向:**垂直于 a 和 b 所在平面**,按**右手定则**确定

**右手定则**:右手食指指 a,中指指 b,大拇指指的方向就是 a × b 的方向。

```
            ↑ a × b (大拇指)
            |
       b ───┼─── (食指指 a,向纸里;中指指 b,向右)
            |
            a (向纸里,故 a × b 向上)
```

#### 3D 叉积的用途

1. **算三角形法线**:三个顶点 P0, P1, P2
   ```
   N = (P1 - P0) × (P2 - P0)
   N = N.normalize()
   ```
   这是光照计算的基础(法线 = 表面"朝外"的方向)。

2. **扭矩(torque)**:力 F 作用在 r 处,扭矩 = r × F

3. **角动量**:L = r × p

4. **判断旋转方向**:刚体绕轴旋转,角速度向量 ω,某点速度 v = ω × r

#### Rust 实现

```rust
impl Vec2 {
    /// 2D 叉积,返回标量
    pub fn cross(self, other: Self) -> f32 {
        self.x * other.y - self.y * other.x
    }
}

// 3D 版本
#[derive(Copy, Clone, Debug, PartialEq)]
pub struct Vec3 {
    pub x: f32,
    pub y: f32,
    pub z: f32,
}

impl Vec3 {
    pub fn new(x: f32, y: f32, z: f32) -> Self {
        Self { x, y, z }
    }

    /// 3D 叉积,返回向量(垂直于两输入向量所在平面)
    pub fn cross(self, other: Self) -> Self {
        Self {
            x: self.y * other.z - self.z * other.y,
            y: self.z * other.x - self.x * other.z,
            z: self.x * other.y - self.y * other.x,
        }
    }

    pub fn dot(self, other: Self) -> f32 {
        self.x * other.x + self.y * other.y + self.z * other.z
    }

    pub fn length(self) -> f32 {
        (self.x * self.x + self.y * self.y + self.z * self.z).sqrt()
    }

    pub fn normalize(self) -> Self {
        let len = self.length();
        if len > 1e-6 {
            Self {
                x: self.x / len,
                y: self.y / len,
                z: self.z / len,
            }
        } else {
            Self::new(0.0, 0.0, 0.0)
        }
    }
}
```

**叉积公式记忆**:对每个分量,**循环置换**(x→y→z→x):
- x 分量:用 y 和 z(去掉 x 那一"行")
- y 分量:用 z 和 x
- z 分量:用 x 和 y

注意 y 分量是**负号**:`az*bx - ax*bz`,不是 `ax*bz - az*bx`。这是右手定则的结果。

### 2.4 反射向量

速度 v 撞到墙(法线 n)后反弹,新速度:

```
v' = v - 2 (v · n) n
```

**推导**(透彻理解):

把 v 分解成两个分量:
- **垂直墙**的分量:`v_perp = (v · n) n`(n 是单位法线)
- **平行墙**的分量:`v_para = v - v_perp`

撞墙时:
- 平行分量**不变**(无摩擦)
- 垂直分量**反向**:`v_perp' = -v_perp = -(v · n) n`

新速度:

```
v' = v_para + v_perp'
   = (v - v_perp) - v_perp
   = v - 2 v_perp
   = v - 2 (v · n) n   □
```

**注意**:n 必须是**单位向量**(长度 1),否则公式不对。

#### Rust 实现

```rust
impl Vec2 {
    /// 反射:v 撞法线 n 后反弹。n 必须是单位向量。
    pub fn reflect(self, n: Self) -> Self {
        let d = self.dot(n);
        self.sub(n.scale(2.0 * d))
    }
}
```

#### 验证

```
v = (1, -1)   (向右下走)
n = (0, 1)    (地面向上)
v · n = (1)(0) + (-1)(1) = -1
v' = v - 2(-1) * (0, 1)
   = (1, -1) + (0, 2)
   = (1, 1)    ✓ 向右上反弹
```

### 2.5 矩阵(Matrix)

#### 定义

矩阵是数的二维表。2×2 矩阵:

```
    ┌       ┐
M = │ a  b │
    │ c  d │
    └       ┘
```

3×3、4×4 类似。

#### 矩阵 × 向量 = 向量(线性变换)

2×2 矩阵乘 2D 向量:

```
┌ a b ┐ ┌ x ┐   ┌ a*x + b*y ┐
│     │ │   │ = │           │
└ c d ┘ └ y ┘   └ c*x + d*y ┘
```

直觉:矩阵是一个**变换**——把输入向量"扭曲"成输出向量。

#### 旋转矩阵

2D 旋转 θ 角度:

```
R(θ) = ┌ cos θ   -sin θ ┐
       │                 │
       └ sin θ    cos θ ┘
```

**为什么是这个?**(从直觉推):

考虑把单位向量 (1, 0) 旋转 θ:
- 旋转后 x = cos θ(原 x 在新方向的投影)
- 旋转后 y = sin θ

所以 R(θ) * (1, 0) = (cos θ, sin θ)。这是 R 的第一列。

类似,(0, 1) 旋转 θ 变成 (-sin θ, cos θ)。这是第二列。

把两列拼起来,就是 R(θ)。

**关键洞察**:**矩阵的列就是基向量变换后的位置**。这是矩阵最直观的理解。

#### 矩阵乘法(复合变换)

矩阵 A × 矩阵 B = 矩阵 C,意思是"先做 B,再做 A"。

```
C[i][j] = Σ A[i][k] * B[k][j]
         k
```

直觉:C 的 (i, j) 是 A 的第 i 行 · B 的第 j 列(把行列都看作向量)。

2×2 矩阵乘 2×2:

```
┌ a b ┐ ┌ e f ┐   ┌ ae+bg  af+bh ┐
│     │ │     │ = │                 │
└ c d ┘ └ g h ┘   └ ce+dg  cf+dh ┘
```

#### 缩放矩阵

```
S(sx, sy) = ┌ sx  0  ┐
            │        │
            └ 0   sy ┘
```

把 (x, y) 缩放成 (sx*x, sy*y)。

#### 平移问题:为什么需要 4×4

2D 平移很简单——加一个向量:`new_pos = pos + translation`。

但**旋转 / 缩放是矩阵乘,平移是加**——两套操作不统一。统一方法是**齐次坐标(homogeneous coordinates)**:

把 2D 向量 (x, y) 写成 3D (x, y, 1)。最后那个 1 是"齐次坐标"。然后 3×3 矩阵可以同时做旋转 / 缩放 / 平移:

```
T(tx, ty) = ┌ 1  0  tx ┐
            │ 0  1  ty │
            │ 0  0  1  │
            └          ┘
```

T * (x, y, 1) = (x + tx, y + ty, 1)。平移完成。

**3D 同理**:用 4D (x, y, z, 1),4×4 矩阵。这是 OpenGL / Vulkan / DirectX 的统一表示。

#### MVP 矩阵链(图形学核心)

3D 模型在屏幕上画出来,经过一连串变换:

```
模型坐标 ──Model──► 世界坐标 ──View──► 相机坐标 ──Projection──► 裁剪坐标 ──透视除法──► NDC ──Viewport──► 屏幕坐标
```

每个箭头是一个矩阵乘法。整个链路叫 MVP(Model-View-Projection)。

- **Model 矩阵**:把模型从"自己的坐标系"转到"世界坐标系"(包含位置、旋转、缩放)
- **View 矩阵**:把世界从"世界坐标系"转到"相机视角坐标系"(相机的逆变换)
- **Projection 矩阵**:把 3D 投影到 2D 屏幕(透视 / 正交)

游戏引擎里每个物体每帧都算 MVP,送给 GPU 渲染。这是 Phase 3+ 的核心。

#### Rust 实现

```rust
#[derive(Copy, Clone, Debug)]
pub struct Mat2 {
    pub m: [[f32; 2]; 2],   // m[row][col]
}

impl Mat2 {
    pub fn identity() -> Self {
        Self { m: [[1.0, 0.0], [0.0, 1.0]] }
    }

    pub fn rotation(theta: f32) -> Self {
        let (s, c) = theta.sin_cos();
        Self { m: [[c, -s], [s, c]] }
    }

    pub fn scaling(sx: f32, sy: f32) -> Self {
        Self { m: [[sx, 0.0], [0.0, sy]] }
    }

    /// 矩阵 × 向量
    pub fn mul_vec(self, v: Vec2) -> Vec2 {
        Vec2::new(
            self.m[0][0] * v.x + self.m[0][1] * v.y,
            self.m[1][0] * v.x + self.m[1][1] * v.y,
        )
    }

    /// 矩阵 × 矩阵
    pub fn mul_mat(self, other: Self) -> Self {
        let mut result = Self { m: [[0.0; 2]; 2] };
        for i in 0..2 {
            for j in 0..2 {
                result.m[i][j] = self.m[i][0] * other.m[0][j]
                               + self.m[i][1] * other.m[1][j];
            }
        }
        result
    }
}
```

### 2.6 数值积分:Euler 积分

#### 微积分复习(从零)

**速度**是位置的变化率。如果你 1 秒走 5 米,你的速度是 5 m/s。

数学写法:`v = dp/dt`,读作 "p 对 t 的导数"。意思是"无穷小时间内的位置变化"。

**积分**是导数的逆运算:`p(t) = ∫ v(t) dt`。意思是"把所有瞬时的速度加起来,得到位置"。

#### 计算机不能"积分"

计算机不能做无穷小,只能做**离散步骤**。所以我们用**数值积分**——把时间切成小段(每段 dt),每段假设速度不变。

**Euler 积分**(最简单):

```
每一步:
    位置 += 速度 * dt
    速度 += 加速度 * dt
```

直觉:这一帧的 dt 内,我假设速度是常数,所以位置变化 = 速度 * dt。

#### 验证 Euler 积分

自由落体(加速度 = g = 9.8 m/s²,初始速度 = 0,初始位置 = 0):

```
t=0:    p=0,   v=0
t=0.1:  v = 0 + 9.8 * 0.1 = 0.98
        p = 0 + 0.98 * 0.1 = 0.098
t=0.2:  v = 0.98 + 9.8 * 0.1 = 1.96
        p = 0.098 + 1.96 * 0.1 = 0.294
...
```

解析解:`p(t) = 0.5 * g * t² = 0.5 * 9.8 * 0.2² = 0.196`

Euler 给的是 0.294,实际是 0.196——**Euler 高估了**!为什么?因为 Euler 用了"t=0.1 时的速度"更新 p,但实际 t=0 到 0.1 之间速度在变。

#### 半隐式 Euler(更准)

```
速度 += 加速度 * dt       ← 先更新速度
位置 += 速度 * dt         ← 用新速度更新位置
```

差别:顺序变了。这个版本用**新速度**更新位置,误差小得多。

实测半隐式 Euler 对自由落体:

```
t=0.1:  v = 0.98, p = 0.098  (顺序变后,这一步不变)
t=0.2:  v = 1.96, p = 0.098 + 1.96 * 0.1 = 0.294  (还是这个,但累计误差更稳定)
```

实际游戏里 dt = 1/60 秒,Euler 误差小到看不出。Casey 选 Euler 就是这个理由——**够用**。

#### 为什么不用更精确的方法?

| 方法 | 误差 | 计算量 | 何时用 |
|---|---|---|---|
| 显式 Euler | O(dt) | 1× | 60 FPS 游戏(够) |
| 半隐式 Euler | O(dt) | 1× | 60 FPS 游戏(更稳) |
| Verlet | O(dt²) | 1.5× | 布料、弹簧系统 |
| RK4(Runge-Kutta 4) | O(dt⁴) | 4× | 轨道力学、精确仿真 |

游戏里 60 FPS,dt 已经很小,误差 < 0.001。RK4 4 倍代价换 < 0.0001 误差,不值。**够用是工程哲学**——Casey 反复强调。

#### Rust 实现

```rust
struct PhysicsBody {
    position: Vec2,
    velocity: Vec2,
    acceleration: Vec2,
}

impl PhysicsBody {
    /// 半隐式 Euler 积分
    fn step(&mut self, dt: f32) {
        // 先更新速度
        self.velocity = self.velocity.add(self.acceleration.scale(dt));
        // 再用新速度更新位置
        self.position = self.position.add(self.velocity.scale(dt));
    }
}
```

3 行代码,你游戏里 90% 物理就是这套。

## 3 · 四域深入

### 3.1 · 🎮 游戏编程视角

数学工具在游戏里的具体应用,贯穿 Casey 整套教程:

- **Day 42-43(Vec2 + Euler)**:小人移动、跳跃(重力)
- **Day 44(反射)**:小人撞墙反弹,弹球游戏
- **Day 47-48(点积 + 叉积)**:玩家攻击范围、视线判断
- **Day 50(Minkowski 差)**:AABB 矩形碰撞
- **Day 60+(向量 + 插值)**:相机跟随(平滑插值)
- **Day 70+(Vec3 + 矩阵)**:进入 3D 渲染
- **Day 100+(叉积 + 法线)**:光照计算
- **Day 200+(SIMD 优化)**:把所有数学用 SIMD 重写

每个数学工具被反复用,所以 Casey 自己手写不依赖库。这是 HH 哲学:**控制每一行代码**。

#### 数据布局:为什么 Casey 不用 glam

游戏数学的性能瓶颈不在运算,在**内存访问**。

- AoS(Array of Structs):`[Vec2; 1000]` 每个向量连续 8 字节
- SoA(Struct of Arrays):`{ xs: [f32; 1000], ys: [f32; 1000] }`

AOS 对"一次处理一个向量"友好;SOA 对"同时处理很多向量的同一个分量"友好(SIMD)。

Casey 在 Day 1-200 用 AoS(简单),Day 200+ 性能优化时切 SoA。glam 默认 AoS,所以 Casey 不用——他要极致控制。

### 3.2 · 🎨 图形学视角

图形学是数学最密集的领域之一。每一帧画面:

1. **顶点变换**:每个顶点过 MVP 矩阵链
2. **光栅化**:三角形覆盖哪些像素?用**重心坐标**(本篇没讲,Phase 3 详)
3. **深度测试**:z-buffer 比浮点数大小
4. **光照**:N · L(漫反射)、R · V(镜面)
5. **纹理采样**:UV 坐标 → 双线性插值

**色彩空间**也是数学坑:PNG 存 sRGB(非线性),光照必须**线性空间**算,最后再转回 sRGB 显示。算错色彩全暗。

本篇讲的向量 / 矩阵 / 积分是图形学的最低门槛。Phase 3 起每集都会用。

### 3.3 · 🐧 Linux 系统编程视角

Linux 上的数学库:
- `libm`(glibc 一部分)提供 `sqrt`, `sin`, `cos`
- Rust 的 `f32::sqrt()` 底层调 `libm` 的 `sqrtf`,在 x86_64 编译成 `sqrtss` 硬件指令
- SIMD:`<immintrin.h>`(C)或 `std::arch::x86_64`(Rust)

```bash
# 验证 Rust sqrt 是硬件指令
echo 'pub fn f(x: f32) -> f32 { x.sqrt() }' > /tmp/a.rs
rustc --emit asm -O --crate-type lib /tmp/a.rs -o /tmp/a.s
grep sqrt /tmp/a.s
# 输出:sqrtss  ...
# 不是 call sqrtf@PLT(libm 函数)
```

游戏数学在 CPU 上做(快速、低延迟);渲染数学在 GPU 做(大规模并行)。HH Day 235 之前全 CPU 软渲染,之后切 OpenGL 把渲染搬到 GPU。**但数学公式完全一样**,只是执行单元不同。

### 3.4 · 🦀 Rust 生态视角

Rust 表达游戏数学的几个层次:

**层次 1:手写(本篇风格)** —— 学习阶段,理解每一行
**层次 2:用 glam** —— 工业级,优化好,API 简洁
**层次 3:用 nalgebra** —— 科学计算,泛型维度,泛型数学

```rust
// glam 风格
use glam::Vec2;
let v = Vec2::new(1.0, 2.0);
let len = v.length();
let unit = v.normalize();
let dot = v.dot(Vec2::new(3.0, 4.0));
```

**所有权**:`Vec2` 是 Copy(8 字节),函数传值不用引用,避免借用打架。

**SIMD**:glam 用 `#[repr(C, align(16))]` 让 Vec4 对齐 16 字节,直接 `_mm_load_ps`。Casey 在 Day 200+ 手写等价代码。

## 4 · 认知地图

### 4.1 上级

- **线性代数(Linear Algebra)** — 向量空间 / 线性变换 / 矩阵
- **微积分(Calculus)** — 变化率(导数)/ 累积(积分)
- **数值方法(Numerical Methods)** — 用计算机近似解数学问题
- **解析几何(Analytic Geometry)** — 用代数研究几何

### 4.2 同级(数据布局)

| 布局 | 内存 | SIMD |
|---|---|---|
| AoS `[Vec2; N]` | 每个向量 8 字节连续 | 中等 |
| SoA `{ xs: Vec<f32>, ys: Vec<f32> }` | xs 和 ys 分开 | 极高(直接 SIMD load) |
| AoSoA(混合) | 块内 AoS,块间 SoA | 高 + cache 友好 |

### 4.3 下级

- **勾股定理** — 向量长度的基础
- **余弦定理** — 点积几何推导
- **右手定则** — 叉积方向
- **齐次坐标** — 4×4 矩阵统一变换
- **欧拉角 / 四元数** — 3D 旋转表示(本篇没讲,Phase 3 详)

## 5 · 对照与变奏

### 同一问题不同方法

**问题**:判断两个矩形是否重叠。

| 方法 | 复杂度 | 适用 |
|---|---|---|
| 逐边比较 | 简单 | 教学 |
| Minkowski 差 | 中等 | AABB 碰撞(Casey 用) |
| SAT(Separating Axis Theorem) | 中等 | 任意凸多边形 |
| GJK(Gilbert-Johnson-Keerthi) | 复杂 | 任意凸形,3D |

游戏开发没有"最好算法",只有"刚好够用"。

### 2D vs 3D 数学

| | 2D | 3D |
|---|---|---|
| 向量 | (x, y),2 个分量 | (x, y, z),3 个分量 |
| 点积 | 标量 | 标量(公式同) |
| 叉积 | 标量(伪) | 向量 |
| 旋转 | 一个角度 + 2×2 矩阵 | 3 个角度 / 四元数 |
| 法线 | 旋转 90° 即可 | 叉积算 |

3D 数学复杂度比 2D 大得多,但**核心概念**(向量 / 点积 / 矩阵)一样。先 2D 学透,3D 自然过渡。

### 历史

- **古希腊**:欧几里得几何(尺规作图)
- **17 世纪**:笛卡尔发明解析几何(代数 + 几何)
- **19 世纪**:向量 / 矩阵 / 行列式形式化
- **20 世纪**:计算机 + 数值方法
- **21 世纪**:GPU + SIMD 把数学硬件化

你学这一篇,等于把 400 年数学压缩到几小时。

## 6 · 关联 Day

- **铺垫**:[03-rust-from-scratch-1.md](03-rust-from-scratch-1.md)(Rust 基础)
- **当天**:本篇
- **后续**:
  - [day041](../phase-2/day041.md)(Casey 数学概览)
  - [day042](../phase-2/day042.md) / [day043](../phase-2/day043.md)(Vec2 + Euler)
  - [day044](../phase-2/day044.md)(反射)
  - [day047](../phase-2/day047.md) / [day048](../phase-2/day048.md)(线段相交)
  - [day050](../phase-2/day050.md)(Minkowski 碰撞)
  - Phase 3+(3D 矩阵 / 投影)
  - Phase 6(深度缓冲 / 光照)

## 7 · 变式训练

### Lv1 · 概念辨析

**题**:`(3, 4)` 和 `(4, -3)` 的点积是多少?它们有什么特殊关系?为什么?

**参考解答**:
```
(3, 4) · (4, -3) = 3*4 + 4*(-3) = 12 - 12 = 0
```

点积为 0 ⟹ 两向量垂直。

为什么?`a · b = |a||b|cos(θ)`,|a| 和 |b| 都非零,所以 `cos(θ) = 0`,即 θ = 90°。

这是个有用的"快速构造垂直向量"技巧:`(x, y)` 的垂直向量是 `(-y, x)` 或 `(y, -x)`。在 2D 里算"垂直于运动方向的左右方向"时直接用。

### Lv2 · 动手实践

**题**:在 Rust 里实现 Vec2 / Vec3 / Mat2,写一个 main 测试:

- `(3, 4).length()` == 5
- `(1, 0).dot((0, 1))` == 0(垂直)
- `(1, 0).cross((0, 1))` == 1(逆时针)
- `(0, 1).cross((1, 0))` == -1(顺时针)
- `(1, -1).reflect((0, 1))` ≈ `(1, 1)`(撞地反弹)
- `Mat2::rotation(π/2)` * `(1, 0)` ≈ `(0, 1)`(旋转 90°)
- `(0, 1, 0).cross((1, 0, 0))` ≈ `(0, 0, -1)`(3D 叉积,右手定则)

完成标准:所有 assert_eq! 通过(浮点用 abs < 1e-6)。

**参考解答**:

```rust
#[derive(Copy, Clone, Debug, PartialEq)]
struct Vec2 { x: f32, y: f32 }

impl Vec2 {
    fn new(x: f32, y: f32) -> Self { Self { x, y } }
    fn add(self, o: Self) -> Self { Self { x: self.x + o.x, y: self.y + o.y } }
    fn sub(self, o: Self) -> Self { Self { x: self.x - o.x, y: self.y - o.y } }
    fn scale(self, k: f32) -> Self { Self { x: self.x * k, y: self.y * k } }
    fn dot(self, o: Self) -> f32 { self.x * o.x + self.y * o.y }
    fn cross(self, o: Self) -> f32 { self.x * o.y - self.y * o.x }
    fn length(self) -> f32 { self.x.hypot(self.y) }
    fn reflect(self, n: Self) -> Self {
        let d = self.dot(n);
        self.sub(n.scale(2.0 * d))
    }
}

#[derive(Copy, Clone, Debug, PartialEq)]
struct Vec3 { x: f32, y: f32, z: f32 }

impl Vec3 {
    fn new(x: f32, y: f32, z: f32) -> Self { Self { x, y, z } }
    fn cross(self, o: Self) -> Self {
        Self {
            x: self.y * o.z - self.z * o.y,
            y: self.z * o.x - self.x * o.z,
            z: self.x * o.y - self.y * o.x,
        }
    }
}

struct Mat2 { m: [[f32; 2]; 2] }

impl Mat2 {
    fn rotation(theta: f32) -> Self {
        let (s, c) = theta.sin_cos();
        Self { m: [[c, -s], [s, c]] }
    }
    fn mul_vec(&self, v: Vec2) -> Vec2 {
        Vec2::new(
            self.m[0][0] * v.x + self.m[0][1] * v.y,
            self.m[1][0] * v.x + self.m[1][1] * v.y,
        )
    }
}

fn approx_eq(a: f32, b: f32) -> bool { (a - b).abs() < 1e-6 }
fn vec2_approx_eq(a: Vec2, b: Vec2) -> bool {
    approx_eq(a.x, b.x) && approx_eq(a.y, b.y)
}

fn main() {
    // 1. 长度
    assert!(approx_eq(Vec2::new(3.0, 4.0).length(), 5.0));

    // 2. 垂直
    assert!(approx_eq(Vec2::new(1.0, 0.0).dot(Vec2::new(0.0, 1.0)), 0.0));

    // 3. 2D 叉积:逆时针为正
    assert!(approx_eq(Vec2::new(1.0, 0.0).cross(Vec2::new(0.0, 1.0)), 1.0));

    // 4. 反过来:顺时针为负
    assert!(approx_eq(Vec2::new(0.0, 1.0).cross(Vec2::new(1.0, 0.0)), -1.0));

    // 5. 反射
    let r = Vec2::new(1.0, -1.0).reflect(Vec2::new(0.0, 1.0));
    assert!(vec2_approx_eq(r, Vec2::new(1.0, 1.0)));

    // 6. 旋转矩阵 90°
    let r = Mat2::rotation(std::f32::consts::FRAC_PI_2);
    let rotated = r.mul_vec(Vec2::new(1.0, 0.0));
    assert!(vec2_approx_eq(rotated, Vec2::new(0.0, 1.0)));

    // 7. 3D 叉积(右手定则)
    let c = Vec3::new(0.0, 1.0, 0.0).cross(Vec3::new(1.0, 0.0, 0.0));
    assert!(approx_eq(c.x, 0.0));
    assert!(approx_eq(c.y, 0.0));
    assert!(approx_eq(c.z, -1.0));

    println!("All math tests passed!");
}
```

### Lv3 · 迁移设计

**题**:3D 球体和 3D 平面的碰撞检测。算法:
- 球心 C,半径 r
- 平面:一点 P 和法线 N(单位向量)
- 球心到平面的距离:`d = (C - P) · N`
- 碰撞 ⟺ `|d| < r`
- 碰撞后球心修正:`C' = C - (d - sign(d) * r) * N`(把球推到平面正确侧)

写出 Rust 函数 `fn sphere_plane_collide(c: Vec3, r: f32, p: Vec3, n: Vec3) -> Option<Vec3>`,返回修正后的球心(无碰撞返回 None)。

**提示**:用本篇的 dot / sub / scale。

### Lv4 · 开源贡献

**题**:`glam` 是 Bevy 的数学库,GitHub: https://github.com/bitshifter/glam

1. clone,读 `src/f32/vec3.rs` 里 `reflect` 和 `project_onto` 的实现
2. 对比本篇实现的差别(命名 / 处理边界 / SIMD)
3. **可能的贡献**:
   - 某个函数缺 doctest,加一个
   - 某个 doc 解释不清楚(如没说"为什么归一化"),补一段
   - 找 good first issue
4. fork → branch → 改 → PR(参考 [12-opensource-pr-flow.md](12-opensource-pr-flow.md))

写下你打算提的 PR。

## 8 · Rust / Arch 落地代码

### 完整的 Vec2 + 物理 demo

```rust
// src/main.rs —— 一个完整的物理 demo

#[derive(Copy, Clone, Debug)]
struct Vec2 { x: f32, y: f32 }

impl Vec2 {
    fn new(x: f32, y: f32) -> Self { Self { x, y } }
    fn add(self, o: Self) -> Self { Self { x: self.x + o.x, y: self.y + o.y } }
    fn sub(self, o: Self) -> Self { Self { x: self.x - o.x, y: self.y - o.y } }
    fn scale(self, k: f32) -> Self { Self { x: self.x * k, y: self.y * k } }
    fn dot(self, o: Self) -> f32 { self.x * o.x + self.y * o.y }
    fn length(self) -> f32 { self.x.hypot(self.y) }
    fn normalize(self) -> Self {
        let len = self.length();
        if len > 1e-6 { self.scale(1.0 / len) } else { Self::new(0.0, 0.0) }
    }
    fn reflect(self, n: Self) -> Self {
        self.sub(n.scale(2.0 * self.dot(n)))
    }
}

struct Ball {
    pos: Vec2,
    vel: Vec2,
}

impl Ball {
    fn step(&mut self, dt: f32, gravity: Vec2) {
        // 半隐式 Euler
        self.vel = self.vel.add(gravity.scale(dt));
        self.pos = self.pos.add(self.vel.scale(dt));

        // 地面在 y=0,法线向上
        if self.pos.y < 1.0 {
            self.pos.y = 1.0;
            // 反射(垂直分量)
            let n = Vec2::new(0.0, 1.0);
            self.vel = self.vel.reflect(n);
            // 摩擦:速度乘 0.8(损失能量)
            self.vel = self.vel.scale(0.8);
        }
    }
}

fn main() {
    let mut ball = Ball {
        pos: Vec2::new(0.0, 10.0),
        vel: Vec2::new(2.0, 0.0),
    };
    let gravity = Vec2::new(0.0, -9.8);
    let dt = 1.0 / 60.0;

    for frame in 0..180 {   // 3 秒
        ball.step(dt, gravity);
        if frame % 30 == 0 {
            println!("t={:5.2}: pos=({:6.2}, {:6.2})  vel=({:6.2}, {:6.2})",
                frame as f32 * dt, ball.pos.x, ball.pos.y, ball.vel.x, ball.vel.y);
        }
    }
}
```

跑:

```bash
cargo new physics-demo
cd physics-demo
# 把代码粘进 src/main.rs
cargo run --release
# 输出:每 30 帧打印球的位置和速度,看到反弹
```

### Arch 验证浮点和汇编

```bash
# 1. 看 sqrt 是硬件指令
echo 'pub fn f(x: f32) -> f32 { x*x + 2.0*x + 1.0 }' > /tmp/a.rs
rustc --emit asm -O --crate-type lib /tmp/a.rs -o /tmp/a.s
grep -E "mulss|addss|sqrtss" /tmp/a.s
# 应该看到 mulss(乘)、addss(加),没有 call ...

# 2. 看 SIMD 是否启用
cat > /tmp/simd.rs << 'EOF'
pub fn sum_squares(xs: &[f32]) -> f32 {
    xs.iter().map(|x| x * x).sum()
}
EOF
rustc -O -C target-cpu=native --emit asm --crate-type lib /tmp/simd.rs -o /tmp/simd.s
grep -E "addps|mulpd" /tmp/simd.s
# 用 target-cpu=native 时,可能看到 SIMD 指令

# 3. 看 libm
nm -D /usr/lib/libm.so.6 | grep -E " T (sqrt|sinf|cosf)"
```

### Troubleshooting

- **`(0.1 + 0.2 != 0.3)`**:浮点精度。`f32` / `f64` 不能精确表示 0.1。用 `abs(a-b) < epsilon` 比较
- **sqrt 慢**:debug 模式 sqrt 不内联。用 `--release`
- **NaN / Infinity**:0/0 → NaN;1/0 → Infinity。检查除零、负数 sqrt
- **角度 vs 弧度**:Rust 的 sin/cos 用**弧度**。角度变弧度:`rad = deg * π / 180`

## 9 · 延伸阅读(可选补充,非必需)

本仓库本地:
- [day041](../phase-2/day041.md) — Casey 数学概览
- [phase-0/README.md](README.md)

外部稳定 URL:
- 3D Math Primer(免费在线书,本篇很多内容参考):https://gamemath.com/book/
  - 第 4 章 Vectors:https://gamemath.com/book/vectors.html
  - 第 5 章 Multiple Coordinate Spaces:https://gamemath.com/book/coords.html
  - 第 7 章 Matrices:https://gamemath.com/book/matrices.html
- LearnOpenGL Transformations:https://learnopengl.com/Getting-started/Transformations
- Linear Algebra Done Right(Sheldon Axler):经典教材
- Game Programming Patterns:https://gameprogrammingpatterns.com/

真实开源源码:
- glam Vec3 实现:https://github.com/bitshifter/glam/blob/main/src/f32/vec3.rs
- Casey HH day042 Vec2:https://github.com/HandmadeHero/handmade-hero/tree/main/code/day042
