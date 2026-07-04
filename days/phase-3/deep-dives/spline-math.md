
# 样条数学深度专题

> 你的游戏里有三个症状:(1)过场动画的镜头在两个机位之间"硬切"——你写了 `pos = pos.lerp(target, 0.1)`,但每个机位之间过渡都很机械,方向感丢失;(2)UI 面板从屏幕外滑入,代码用的是 `x += dt * speed` 匀速直线,看起来像 PowerPoint 动画,毫无游戏感;(3)你想给一个 cinematic camera 设计一条蜿蜒穿过场景的路径,但你只能逐段手写「从这里到那里」,段与段接缝处曲线急转,玩家头晕。
>
> 这三个问题的共同根源:你缺一个工具——**spline(样条)**。样条就是「**给一堆控制点,返回一条穿过/贴近它们的平滑曲线**」的数学对象。一旦你看懂样条,你会发现游戏里到处都是它:相机路径是样条,动画曲线是样条,**CSS 的 ease-in-out 本质就是一个三次 Bézier**,projectile 抛物轨迹也可以用样条拟合。这一篇把曲线的数学从零讲透,聚焦游戏里真正需要的那几种(Bézier / Hermite / Catmull-Rom / B-spline),并在你的 Handmade Hero 项目里用 Rust 实现一条 cinematic camera path。

## 0 · 一个无样条的世界,你会写出什么

先建立痛点直觉。假设你要让镜头从 A = (0, 5, 10) 平滑走到 B = (10, 8, -5),再走到 C = (-3, 12, -15)。你最初的想法大概是:

```rust
// 帧率独立地把位置插值到下一个 waypoint
fn step(cam: &mut Camera, target: Vec3, dt: f32) {
    cam.pos = cam.pos.lerp(target, 1.0 - (-5.0 * dt).exp());
}
```

跑起来,镜头确实动了,但有几个问题立刻暴露出来。第一,**到达 B 的瞬间镜头有一个急转**——因为「A→B」和「B→C」是两条独立的直线,在 B 处方向突变,玩家眼睛会感觉到 jerk。第二,**速度无法预测**——指数 lerp 的「速度」由当前距离决定,A→B 段快,B→C 段慢,你没法控制「这条路径要 4.2 秒走完」。第三,**方向感丢失**——你的 look-at 还得另外手动 lerp,与位置 lerp 不同步,镜头会「先到位再看」,或者「先看再到位」。

这三个问题——接缝的 C1 不连续、速度不可控、位置和朝向解耦——的数学根因都是同一个:你用「**离散的直线段**」去逼近「**连续的曲线**」。直线段在端点没有定义切线,所以接缝必然急转;直线段没有弧长参数化,所以速度无法恒定;直线段是一维参数 t 的线性函数,没法自然延伸到「位置 + 朝向」这种多分量曲线。

样条就是解药:**它给你一个 `f(t) → point` 的函数**,t 从 0 到 1 走完整条曲线,而这条曲线在每一个内点都有定义良好的切线(平滑)、可参数化的弧长(匀速)、可同时插值任意多分量(位置 + 朝向一起走)。今天我们把这个 `f` 从零搭起来。

## 1 · 样条到底是什么

先把术语钉死。一条 **spline(样条)** 是一个**分段定义**的曲线函数 `S(t)`,它接受一个参数 `t ∈ [0, 1]`,返回曲线上一个点(通常是 2D 或 3D 向量)。「分段」是关键词:样条不是单一公式,而是由若干段(piece / segment)拼接而成,每一段是一个低阶多项式,段与段在接缝处满足某种**连续性条件**。

「**控制点(control points)**」是塑造曲线形状的一组点 `P₀, P₁, ..., Pₙ`。不同的样条类型,差别全在**「控制点和曲线的关系」**上:

- 曲线**穿过**所有控制点?这种叫 **interpolating(插值型)** 样条——Catmull-Rom 是代表。
- 曲线只是**贴近**控制点(被它们"拉"过去,但不一定经过)?这种叫 **approximating(逼近型)** 样条——Bézier 和 B-spline 属于这类。
- 曲线在端点处的**切线(tangent)** 是显式给定的?这是 **Hermite** 样条。

「**连续性**」用 C⁰ / C¹ / C² 这种记号描述,数字代表"几阶导数连续"。C⁰ 是位置连续(曲线不断开),C¹ 是切线连续(没有急转),C² 是曲率连续(没有加速度突变)。对人眼来说,**C¹ 是"看起来平滑"的最低门槛,C² 是"看起来丝滑"的标准**。我们今天实现的 Catmull-Rom 是 C¹,Bézier 在拼接时可以做到 C¹ 或 C²(取决于你怎么选接缝切线),B-spline 天生 C²。

最后,**参数 t 和"曲线长度"不是一回事**。t 是数学参数,等差的 t 不等于等距的弧长——曲线在"直"的地方 t 走得快,在"弯"的地方 t 走得慢。这个坑大到值得单开一节(第 7 节)讲。

理解了这些抽象定义,下面我们把每种样条的具体公式拆开,看它们各自适合什么场景。

## 2 · Bézier 曲线:一切的根基

### 2.1 从直觉到公式

Bézier(法语读"贝齐耶",工程师通常直接读 "beh-zee-ay" 或就叫"B 曲线")是法国工程师 Pierre Bézier 1960 年代在 Renault(雷诺)汽车公司发明用来设计车身的,同期 Paul de Casteljau 在 Citroën 也独立发明了同样的数学。游戏工业里,Bézier 是**一切缓动曲线的母语**——CSS 的 `ease-in-out` 内部就是一条三次 Bézier。

一条 Bézier 由 2~4 个控制点定义,游戏里 99% 用的是 **cubic(三次,4 个控制点)**,因为它是「最低阶能表达 S 形」的多项式,且足够平滑。我们先看最简单的 **quadratic(二次,3 个控制点)** 建立直觉,然后立刻上 cubic。

二次 Bézier `B(t)` 由三个点 `P₀, P₁, P₂` 定义:

```
B(t) = (1-t)²·P₀ + 2(1-t)t·P₁ + t²·P₂
```

它的几何画面是:曲线**从 P₀ 出发、到 P₂ 结束**,中间被 P₁ "拉"过去但不经过 P₁。把 (1-t) 和 t 想成权重,当 t=0 时全在 P₀,t=1 时全在 P₂,t=0.5 时是 `0.25·P₀ + 0.5·P₁ + 0.25·P₂`——一半的权重给中间点,所以曲线被"拉向" P₁。

三次 Bézier 是工业标准,4 个控制点 `P₀, P₁, P₂, P₃`:

```
B(t) = (1-t)³·P₀ + 3(1-t)²t·P₁ + 3(1-t)t²·P₂ + t³·P₃
```

把多项式展开成 t 的幂:

```
B(t) = (-P₀ + 3P₁ - 3P₂ + P₃)·t³
     + (3P₀ - 6P₁ + 3P₂)·t²
     + (-3P₀ + 3P₁)·t
     + P₀
```

这就是你能在每本图形学教材里看到的 **Bernstein 多项式**形式 `B_i^n(t) = C(n,i) t^i (1-t)^(n-i)`,n=3 时系数是 1, 3, 3, 1。

### 2.2 关键性质(为什么游戏爱它)

Bézier 有四条性质,记住它们,后面的所有应用都从这四条推出来:

**性质一:端点插值**。`B(0) = P₀`,`B(1) = P₃`——曲线一定**穿过首尾两个控制点**。

**性质二:端点切线**。`B'(0) = 3(P₁ - P₀)`,`B'(1) = 3(P₃ - P₂)`——曲线在 P₀ 处的切线方向就是 `P₀→P₁`,在 P₃ 处的切线方向就是 `P₂→P₃`。这就是为什么 UI 设计师调 ease 曲线靠拖动两个"手柄"——手柄方向就是切线方向,手柄长度就是切线强度(速度)。

**性质三:凸包性(convex hull)**。整条曲线被包在 4 个控制点形成的凸包里,绝不会"飞出去"。这给碰撞检测和包围盒计算带来巨大便利——Bézier 曲线的 AABB 就是 4 个控制点的 AABB 的并。

**性质四:中间控制点不一定被穿过**。`P₁` 和 `P₂` 只是"拉力",曲线通常**不经过**它们。这是 Bézier 适合"塑形"但**不适合"路径规划"** 的根本原因——你想让镜头经过特定的 6 个机位,Bézier 直接用是做不到的(需要拼接,见 2.4)。

### 2.3 de Casteljau 算法:优雅到令人发指

直接用 Bernstein 多项式算 `B(t)` 数值不稳定(高次幂浮点误差大),工业实践用 **de Casteljau 算法**——它是递归的线性插值,既稳定又美得像一首诗:

```
给定 P₀, P₁, P₂, P₃ 和参数 t:

第一层(在相邻控制点之间 lerp):
    Q₀ = lerp(P₀, P₁, t)
    Q₁ = lerp(P₁, P₂, t)
    Q₂ = lerp(P₂, P₃, t)

第二层(在 Q 之间 lerp):
    R₀ = lerp(Q₀, Q₁, t)
    R₁ = lerp(Q₁, Q₂, t)

第三层:
    B(t) = lerp(R₀, R₁, t)
```

每一层都只是相邻两点之间的线性插值,层与层之间递归套娃,最后一层出来的就是 Bézier 曲线上的点。这个算法有一个副产品:**倒数第二层的两个点 `R₀` 和 `R₁` 正好把曲线在参数 t 处劈成两段更短的 Bézier**——左半段由 `P₀, Q₀, R₀, B(t)` 定义,右半段由 `B(t), R₁, Q₂, P₃` 定义。这就是工业上"细分(subdivide)Bézier"的标准做法,可用于自适应细分(在弯曲处多分,在直的地方少分)和命中测试。

Rust 实现非常直接,我们用 `glam::Vec3`:

```rust
use glam::Vec3;

fn lerp(a: Vec3, b: Vec3, t: f32) -> Vec3 {
    a + (b - a) * t
}

/// 三次 Bézier,de Casteljau 算法
fn bezier_cubic(p0: Vec3, p1: Vec3, p2: Vec3, p3: Vec3, t: f32) -> Vec3 {
    let q0 = lerp(p0, p1, t);
    let q1 = lerp(p1, p2, t);
    let q2 = lerp(p2, p3, t);
    let r0 = lerp(q0, q1, t);
    let r1 = lerp(q1, q2, t);
    lerp(r0, r1, t)
}

/// 切线方向(对 t 求导)
fn bezier_cubic_tangent(p0: Vec3, p1: Vec3, p2: Vec3, p3: Vec3, t: f32) -> Vec3 {
    // B'(t) = 3(1-t)²(P1-P0) + 6(1-t)t(P2-P1) + 3t²(P3-P2)
    let u = 1.0 - t;
    3.0 * u * u * (p1 - p0) + 6.0 * u * t * (p2 - p1) + 3.0 * t * t * (p3 - p2)
}
```

de Casteljau 比展开多项式快吗?不,递归开销和展开形式差不多,但它**几何意义清晰**(你能可视化每一层)、**数值稳定**(没有高次幂)、**自然支持细分**(副产品),所以工业代码几乎全用它。

### 2.4 Bézier 的痛点:拼接

单段 cubic Bézier 只有 4 个控制点,**没法表达长路径**——你想做一条蜿蜒 50 米的相机轨道,4 个点显然不够。解决办法是**拼接**多段 Bézier:`S(t) = Bézier(P₀,P₁,P₂,P₃)` for `t ∈ [0,1)`,然后 `Bézier(P₃,P₄,P₅,P₆)` for `t ∈ [1,2)`,以此类推。注意段与段共享一个端点(P₃ 既是第一段终点又是第二段起点)。

**拼接的连续性问题**是 Bézier 实战的核心难点。两段在共享点 P₃ 处:

- **C⁰ 连续**(位置不断):第二段起点 = 第一段终点,自动满足(我们就是共享 P₃)。
- **C¹ 连续**(切线不急转):需要 `第一段终点切线 = 第二段起点切线`,即 `P₃ - P₂` 与 `P₄ - P₃` **共线且同向**,且长度比 = 1(严格 C¹)或任意正比(G¹ 视觉连续)。
- **C² 连续**(曲率不突变):更严格,需要 `P₅ - 2P₄ + P₃ = P₃ - 2P₂ + P₁`(二阶差分相等)。

实战中,要满足 C¹ 已经需要"调控制点"——你设计路径时不能随心所欲放点,得算着放。**这就是为什么 Bézier 不适合"路径规划"**:你想让镜头经过 5 个固定机位,你还得手动解出每个机位两侧的控制点满足切线连续,这个求解就是 Catmull-Rom 自动替你做的事。

## 3 · Hermite 曲线:我知道速度

### 3.1 何时用 Hermite

Hermite 样条回答的问题是:「**我知道曲线两端的**位置**和**速度**,请给我一条平滑曲线**」。典型场景:你的相机进入一个 cinematic shot 时以特定速度(切线方向 + 大小)进来,出去时也以特定速度离开——这两个速度是你**主动设计**的,不是从控制点推出来的。

Hermite 由 4 个量定义:两个端点 `P₀, P₁` 和两个端点切线(速度向量)`m₀, m₁`。它的基函数形式是:

```
H(t) = (2t³ - 3t² + 1)·P₀         // h00(t):起点位置权重
     + (t³ - 2t² + t)·m₀           // h10(t):起点切线权重
     + (-2t³ + 3t²)·P₁             // h01(t):终点位置权重
     + (t³ - t²)·m₁                // h11(t):终点切线权重
```

四个基函数 `h00, h10, h01, h11` 叫 **Hermite 基函数**,它们的设计目标是:在 t=0 和 t=1 处各自取特定值,使得位置和切线在端点处精确满足约束(你可以代入 t=0 验证:`H(0) = 1·P₀ + 0·m₀ + 0·P₁ + 0·m₁ = P₀`;对 t 求导再代入 0,得 `H'(0) = m₀`)。

### 3.2 Hermite 和 Bézier 的等价性

数学上一个重要事实:**Hermite 和 cubic Bézier 是同一条曲线的两种参数化**。给定 Hermite 的 `(P₀, m₀, P₁, m₁)`,对应的 Bézier 控制点是:

```
B0 = P₀
B1 = P₀ + m₀/3
B2 = P₁ - m₁/3
B3 = P₁
```

也就是说,如果你有一组 Hermite 参数,你可以直接转成 Bézier 用 de Casteljau 算。反过来,Bézier 也可以转 Hermite(对 UI 缓动调试很有用——CSS 调的是 Bézier 控制点,但内部计算可能用 Hermite 基更快)。

### 3.3 Rust 实现

```rust
/// Hermite 三次曲线
fn hermite_cubic(p0: Vec3, m0: Vec3, p1: Vec3, m1: Vec3, t: f32) -> Vec3 {
    let t2 = t * t;
    let t3 = t2 * t;
    let h00 =  2.0*t3 - 3.0*t2 + 1.0;
    let h10 =        t3 - 2.0*t2 + t;
    let h01 = -2.0*t3 + 3.0*t2;
    let h11 =        t3 -      t2;
    p0*h00 + m0*h10 + p1*h01 + m1*h11
}
```

实战经验:**Hermite 是"已知速度"场景的最佳选择**。如果你不知道速度,只给位置,Catmull-Rom 会替你从位置推速度(见第 4 节);但如果你**就是要精确控制**「相机以 5 m/s 进入这个机位,3 m/s 离开」,直接用 Hermite。

## 4 · Catmull-Rom:游戏的真爱

### 4.1 它解决了什么

回到我们的痛点:你给镜头一串 waypoints `(P₀, P₁, P₂, P₃, P₄)`,你**只想要曲线穿过这 5 个点且整体平滑**,不想手算每个点的切线。Catmull-Rom 就是为你而生的。

**Catmull-Rom 性质**:曲线**穿过所有控制点**(interpolating),且在穿过每个控制点时**切线自动连续**(C¹)。这是游戏工业最爱的组合——"我画点,你画线,线还顺滑"。

它的设计哲学是这样的:在每个内部控制点 `Pᵢ` 处,切线方向就用「前一个点到下一个点」的方向,即 `mᵢ = (P_{i+1} - P_{i-1}) / 2`。这是一个简单到离谱的"中心差分"切线估计,但效果出奇地好——它假设曲线在 Pᵢ 处的瞬时速度等于「整个相邻区间平均速度」,在大多数游戏路径上这是一个合理的局部线性近似。

### 4.2 数学推导

给定四个控制点 `P₀, P₁, P₂, P₃`,我们要构造**从 P₁ 到 P₂ 的那一段**(注意:Catmull-Rom 是分段定义,4 个点定义"中间"那一段,P₀ 和 P₃ 是"幽灵点"提供边界切线信息)。把 P₁ 当 Hermite 的起点,P₂ 当终点:

```
起点切线 m₁ = (P₂ - P₀) / 2
终点切线 m₂ = (P₃ - P₁) / 2
```

然后直接套 Hermite 公式(第 3 节):

```
CR(t) = hermite(P₁, m₁, P₂, m₂, t),   t ∈ [0, 1]
```

展开就是 Catmull-Rom 标准式:

```
CR(t) = 0.5 · [ 2·P₁
              + (-P₀ + P₂)·t
              + (2P₀ - 5P₁ + 4P₂ - P₃)·t²
              + (-P₀ + 3P₁ - 3P₂ + P₃)·t³ ]
```

那个 `0.5` 系数就是切线除以 2 留下的痕迹。这个公式每一项都是 4 个点的线性组合,系数加起来恒等于 1(这是 affine 不变性——曲线随控制点平移而平移,符合几何直觉)。

### 4.3 Rust 实现:Catmull-Rom 段

```rust
use glam::Vec3;

/// Catmull-Rom 一段:从 p1 到 p2,p0 和 p3 是邻接幽灵点
fn catmull_rom_segment(
    p0: Vec3, p1: Vec3, p2: Vec3, p3: Vec3, t: f32,
) -> Vec3 {
    let t2 = t * t;
    let t3 = t2 * t;
    0.5 * (2.0 * p1
         + (-p0 + p2) * t
         + (2.0*p0 - 5.0*p1 + 4.0*p2 - p3) * t2
         + (-p0 + 3.0*p1 - 3.0*p2 + p3) * t3)
}

/// 完整路径:n 个控制点,n-1 段。u ∈ [0, n-1] 是全局参数
fn catmull_rom_path(points: &[Vec3], u: f32) -> Vec3 {
    let n = points.len();
    assert!(n >= 4, "Catmull-Rom 至少需要 4 个点(首尾幽灵)");
    let seg = (u.floor() as usize).min(n - 2);
    let local_t = u - seg as f32;
    // 处理边界:首尾段用 clamp 复用端点作幽灵
    let p0 = points[seg.saturating_sub(1)];
    let p1 = points[seg];
    let p2 = points[seg + 1];
    let p3 = points[(seg + 2).min(n - 1)];
    catmull_rom_segment(p0, p1, p2, p3, local_t)
}
```

**注意边界处理**:整条路径有 `n` 个点就有 `n-1` 段,但首段(`P₀ → P₁`)和末段(`P_{n-2} → P_{n-1}`)缺一个幽灵点。两种处理方式:(1) 复制端点(`P₋₁ = P₀`,这会让端点处切线为零,曲线在端点处"停一下"),或 (2) 镜像(`P₋₁ = 2P₀ - P₁`,切线方向更自然)。上面代码用的是方式 (1),简单稳健。

### 4.4 Catmull-Rom 的两个变种

标准 Catmull-Rom 有两个常见缺陷,工业界有两个改良变种,你应当知道:

**Uniform vs Centripetal**:标准 Catmull-Rom 是 **uniform**(均匀)参数化,即每段都对应 t ∈ [0,1] 不考虑控制点间距。当控制点间距悬殊时(比如 P₁P₂ 距离 1m,P₂P₃ 距离 100m),uniform 会让曲线在 P₂ 附近**自交形成小环(self-intersection loop)**——你看路径回放会看到镜头"打了个小嗝"。

**Centripetal Catmull-Rom**(向心参数化)解决了这个问题:它给每段重新分配 t 范围,使 t 的变化率与控制点间距的平方根(模拟"向心"运动)成正比,从而**消除自交和 overshoot**。实现上,你需要按 `√|P_{i+1} - Pᵢ|` 重新参数化每一段。工业级 cinematic 路径几乎都用 centripetal 变种。

**Tension / Bias / Continuity 参数(Kochanek-Bartels)**:把切线公式 `mᵢ = (P_{i+1} - P_{i-1})/2` 推广为 `mᵢ = ((1-tension)(1+bias)(1-continuity)/2)·(Pᵢ - P_{i-1}) + ((1-tension)(1-bias)(1+continuity)/2)·(P_{i+1} - Pᵢ)`。三个参数让动画师调出"先快后慢""overshoot""停顿"等手感。这就是 3ds Max / Maya 里 TCB spline 的来源。

### 4.5 为什么游戏爱 Catmull-Rom

总结 Catmull-Rom 的优势:

- **穿过所有控制点**——设计师摆点所见即所得。
- **C¹ 自动平滑**——不用手算切线。
- **局部性**——移动一个点只影响相邻 4 段(两段在前,两段在后),改一段不会扰动整条曲线。
- **实现极简**——20 行 Rust 就能跑。

这是为什么 Unity 的 AnimationCurve、Unreal 的 spline component、bevy 的早期 curve 工作默认都是 Catmull-Rom 系列。如果你的项目只需要一种样条,**用 Catmull-Rom**。

## 5 · B-spline:严谨的工程学

### 5.1 什么时候才需要 B-spline

Catmull-Rom 不够用的场景是:**你要更强的平滑(C² 曲率连续)和更细的局部控制**。Catmull-Rom 是 C¹,在控制点处切线连续但曲率可以跳变——视觉上偶尔能看到"略微的拐"。B-spline(spline 工业的"通用底盘",全称 basis spline)是 C²(对三次而言),且**移动一个控制点只影响局部 k+1 段(k = degree)**,控制更精细。

代价是 B-spline **不穿过控制点**(approximating)——曲线被控制点"拉",但不会精确经过它们。这在 CAD(设计汽车外形)里是优点(光滑度比"精确经过"更重要),但在游戏路径规划里是缺点(你想镜头经过特定机位)。

### 5.2 核心概念:knot vector

B-spline 比 Bézier 复杂的地方在于引入了 **knot vector(节点向量)**——一个非递减序列 `u₀ ≤ u₁ ≤ ... ≤ uₘ`,定义每段样条的参数边界。knot 的"重复度"控制曲线在该处的连续性:重复度 = 阶数 + 1 时曲线在该点插值(穿过),重复度 < 阶数时是逼近。

最常见的是 **clamped uniform knot vector**,形如 `[0, 0, 0, 0, 1, 2, ..., n, n, n, n]`(三次,首尾各重复 4 次让曲线经过首尾控制点),中间均匀分布。这种配置下行曲线**经过首尾控制点**(像 Bézier),但中间仍然逼近。

### 5.3 Cox-de Boor 递归

B-spline 的基函数 `N_{i,p}(u)` 由 **Cox-de Boor 递归**定义:

```
p = 0(阶零,分段常数):
    N_{i,0}(u) = 1  if uᵢ ≤ u < u_{i+1}, else 0

p > 0:
    N_{i,p}(u) = (u - uᵢ)/(u_{i+p} - uᵢ) · N_{i,p-1}(u)
              + (u_{i+p+1} - u)/(u_{i+p+1} - u_{i+1}) · N_{i+1,p-1}(u)
```

这是一个比 de Casteljau 更通用的递归——de Casteljau 是 Cox-de Boor 在 Bézier 特例(单段,knot 全 0 和 1)下的退化形式。基函数算出来后,曲线就是 `S(u) = Σ N_{i,p}(u) · Pᵢ`。

### 5.4 Rust 实现骨架

B-spline 完整实现有 80+ 行,这里只给骨架展示结构,完整版你可以参考 [kurbo](https://github.com/linebender/kurbo) 或 [lyon_geom](https://docs.rs/lyon_geom) 的源码:

```rust
struct BSpline {
    degree: usize,         // 阶数(三次 = 3)
    knots: Vec<f32>,       // 节点向量
    control_points: Vec<Vec3>,
}

impl BSpline {
    fn evaluate(&self, u: f32) -> Vec3 {
        // 1. 找到 u 落在哪个 knot span
        let span = self.find_span(u);
        // 2. 算该 span 内非零的 degree+1 个基函数
        let mut n = [0.0_f32; 4];
        self.basis_funs(span, u, &mut n);
        // 3. 加权求和
        let mut pt = Vec3::ZERO;
        for j in 0..=self.degree {
            pt += n[j] * self.control_points[span - self.degree + j];
        }
        pt
    }
    // find_span / basis_funs 见 Cox-de Boor 实现
}
```

**实战判断**:99% 的游戏项目不需要 B-spline。你只在以下情况需要它:(a) 你在做 CAD 类工具(关卡编辑器的造型工具);(b) 你需要 C² 且接受"不穿过控制点";(c) 你需要严格的"局部控制,移动一个点不动远处"——B-spline 的局部性比 Catmull-Rom 还强(影响段数从 4 降到 k+1)。否则,**用 Catmull-Rom 就够了**。

## 6 · 弧长参数化:从"数学曲线"到"能用"

### 6.1 问题的本质

样条的 `f(t)` 返回曲线上的点,但 t 是**纯数学参数**,**不对应走过的距离**。直观演示:想象一条 Catmull-Rom 路径,某些控制点挤得很密(形成尖弯),某些控制点散得很开(直道)。对均匀的 t 步长 `t = 0, 0.1, 0.2, ...`,在直道上每步走过的距离很大,在弯道上每步走过的距离很小——曲线在直道"快",在弯道"慢"。

对你的 cinematic camera 来说,这意味着镜头会**忽快忽慢**——直道飞驰,弯道爬行。这种"参数化导致的非匀速"叫 **non-uniform parameterization**,是 spline 系统的头号用户体验杀手。

要解决这个问题,我们需要 **arc-length parameterization(弧长参数化)**:重新参数化曲线,让新的参数 `s`(弧长)从 0 到 L(总长度),`s` 等差对应**距离**等差,从而曲线匀速运动。

### 6.2 数学上做不到精确,只能数值近似

理论上,我们要找 `s(t)` = "从曲线起点走到参数 t 处的弧长",公式是积分:

```
s(t) = ∫₀ᵗ ||f'(τ)|| dτ
```

对 Catmull-Rom,`||f'(τ)||` 是一个根号下多项式的积分,**没有解析解**(closed form)。所以工业实践全用**数值近似**:预计算一个 `t → s` 查找表,运行时反向查 `s → t`。

具体算法:

```rust
struct ArcLengthTable {
    /// 在 t = i/N 处的累积弧长
    samples: Vec<(f32, f32)>,  // (t_i, s_i)
    total_length: f32,
}

fn build_arc_length_table(
    path: impl Fn(f32) -> Vec3,
    deriv: impl Fn(f32) -> Vec3,
    n_samples: usize,
) -> ArcLengthTable {
    let mut samples = Vec::with_capacity(n_samples + 1);
    let mut s = 0.0;
    let mut prev = path(0.0);
    samples.push((0.0, 0.0));
    for i in 1..=n_samples {
        let t = i as f32 / n_samples as f32;
        let cur = path(t);
        s += (cur - prev).length();  // 欧氏距离近似弧长
        samples.push((t, s));
        prev = cur;
    }
    ArcLengthTable { samples, total_length: s }
}
```

**精度优化**:`(cur - prev).length()` 用直线段近似弧长,在弯曲处低估。更精确的做法是用 **Gaussian quadrature** 直接积 `||f'(τ)||`,4 点 Gauss 在每段能精确积分 7 次多项式,误差远低于直线段。但对游戏应用(不是 CAD),N=1000 的直线段查表已经够用,偏差 < 0.5%。

### 6.3 反向查找:从想要的位置推 t

播放时,玩家说"我要走 30% 的路径",即 `s = 0.3 * total_length`。我们要反查 `t` 使得 `s(t) = 0.3 * total_length`。

**线性查找**(简单):遍历 samples 找到 `s` 落在哪个区间 `[sᵢ, s_{i+1}]`,然后在 `[tᵢ, t_{i+1}]` 内做线性插值估算 t。

**二分查找**(更快):samples 已按 s 排序,二分定位区间,O(log N) 而非 O(N)。

```rust
fn t_for_arc_length(table: &ArcLengthTable, target_s: f32) -> f32 {
    // 二分查找
    let mut lo = 0usize;
    let mut hi = table.samples.len() - 1;
    while hi - lo > 1 {
        let mid = (lo + hi) / 2;
        if table.samples[mid].1 < target_s {
            lo = mid;
        } else {
            hi = mid;
        }
    }
    // 线性插值
    let (t0, s0) = table.samples[lo];
    let (t1, s1) = table.samples[hi];
    let alpha = (target_s - s0) / (s1 - s0);
    t0 + (t1 - t0) * alpha
}
```

这样,播放循环变成:

```rust
// 走完路径耗时 4.2 秒,匀速
let elapsed = ...;
let s = (elapsed / 4.2).min(1.0) * table.total_length;
let t = t_for_arc_length(&table, s);
let cam_pos = catmull_rom_path(&points, t * (points.len() - 1) as f32);
```

这就是"smooth curve"和"usable constant-speed path"的分水岭——前者只有 `f(t)`,后者有 `f(t) + 弧长表`。

## 7 · 样条在游戏里的五个真实应用

样条之所以是"无处不在的隐形工具",是因为它在五个截然不同的子系统里都是正确答案。把这五个场景记熟,你就知道在哪儿用它们。

### 7.1 Cinematic camera path

最经典的应用。给定 5 个机位 `(pos, look_at)`,每对 `(pos, look_at)` 各自走一条 Catmull-Rom 路径,sync 同一个弧长参数 s,镜头就**匀速平滑穿过所有机位**且始终看正确的方向。这就是第 8 节 HH 实战要做的事。Unity 的 Cinemachine 的 `dolly track`、Unreal 的 Sequencer spline track 都是这个套路。

### 7.2 UI 缓动(easing curve)

任何 UI 动画——面板滑入、按钮 hover 缩放、modal 弹出——本质都是「**值随时间从 a 走到 b,但走的方式不是匀速**」。`v(t) = lerp(a, b, ease(t))` 里的 `ease(t)` 就是一个 Bézier 曲线!**CSS 的 `cubic-bezier(p1x, p1y, p2x, p2y)`** 直接把 Bézier 的两个中间控制点暴露给前端工程师。`ease-in-out` 等价于 `cubic-bezier(0.42, 0, 0.58, 1)`,即 P₁=(0.42, 0), P₂=(0.58, 1)。

注意一个细节:UI easing 用 Bézier 时,参数 t 是**时间**而不是 x 坐标——CSS 用 Bézier 的 y 分量作输出值,x 分量作"时间百分比",需要从 x 反查 t(用牛顿法或二分)。这是为什么 CSS easing 函数本质上是一个**用 Bézier 表达的单调缓动曲线**,和 cinematic path 那种 2D/3D 几何 Bézier 是同一数学不同用法。这一点在 [game-feel-03-feedback-juice](../../phase-2/deep-dives/game-feel-03-feedback-juice.md) 里有更详细的实战,这里只点出「easing 曲线就是 Bézier」这个数学事实。

### 7.3 动画曲线(关键帧插值)

 skeletal animation 里,一个骨骼的 translation/rotation 在多个 keyframe 上有关键值,中间帧需要插值。**线性插值**会让运动机械,工业实践是**用 Hermite 或 Catmull-Rom 在关键帧之间做曲线插值**——位置用 Catmull-Rom,旋转用 quaternion 的 squad(球面四边形插值,本质是球面 Hermite)。这就是为什么 [animation-blending-and-state-machine](animation-blending-and-state-machine.md) 里讨论的「transform 混合」会自然用到样条插值——transform 的每个分量都可以是 spline 输入。

### 7.4 程序化轨迹

projectile(抛射物)、missile trail、beam 武器的轨迹,可以是采样一条样条得到的——比纯物理弹道更可控(美术可以"塑造"轨迹)。粒子系统的 ribbon 渲染也常用 Catmull-Rom 平滑粒子历史位置,避免折线感。这条思路在 [particle-systems-cpu](particle-systems-cpu.md) 里有进一步应用。

### 7.5 关卡设计:Spline mesh deformation

Unreal 的 `spline mesh component` 让你沿一条样条"刷"出一个模型(围栏、河流、公路)——本质上把网格顶点的局部坐标沿样条变换到世界。这是 procedural 关卡设计的核心工具,数学上就是「**沿样条累积 local-to-world 矩阵**」:每段样条给你一个 position + tangent + normal,TBN 三轴构成一个 transform 矩阵,顶点乘上它就贴到样条上。

## 8 · 在你 HH 项目里动手(做中学红线)

把上面所有数学变成可跑的代码。目标是:**给 cinematic camera 装一条 Catmull-Rom 路径,弧长参数化,匀速播放,并实现一个 cubic Bézier easing 用在 UI 上**。

### 8.1 第一步:Catmull-Rom 数据结构

在你的 HH 项目新建 `spline.rs`:

```rust
// handmade_hero/src/spline.rs
use glam::{Vec3, Quat};

/// 一条 Catmull-Rom 路径,带弧长参数化表
pub struct CatmullRomPath {
    pub points: Vec<Vec3>,
    /// 每段(共 points.len() - 1 段)各自的弧长表
    arc_tables: Vec<ArcLengthTable>,
    pub total_length: f32,
}

#[derive(Clone)]
struct ArcLengthTable {
    /// (local_t, cumulative_arc_length_within_segment)
    samples: Vec<(f32, f32)>,
}

impl CatmullRomPath {
    pub fn new(points: Vec<Vec3>) -> Self {
        assert!(points.len() >= 2, "至少需要 2 个控制点");
        let n_seg = points.len() - 1;
        let mut arc_tables = Vec::with_capacity(n_seg);
        let mut total = 0.0_f32;
        for seg in 0..n_seg {
            // 幽灵点:首段左端点用 points[0] 复制,末段右端点用 points[len-1] 复制
            let p0 = if seg == 0 { points[0] } else { points[seg - 1] };
            let p1 = points[seg];
            let p2 = points[seg + 1];
            let p3 = if seg + 2 < points.len() { points[seg + 2] } else { points[seg + 1] };
            // 用高密度采样建表
            let n_samples = 64;
            let mut samples = Vec::with_capacity(n_samples + 1);
            let mut s = 0.0;
            let mut prev = catmull_rom_segment(p0, p1, p2, p3, 0.0);
            samples.push((0.0, 0.0));
            for i in 1..=n_samples {
                let t = i as f32 / n_samples as f32;
                let cur = catmull_rom_segment(p0, p1, p2, p3, t);
                s += (cur - prev).length();
                samples.push((t, s));
                prev = cur;
            }
            total += s;
            arc_tables.push(ArcLengthTable { samples });
        }
        Self { points, arc_tables, total_length: total }
    }

    /// 用全局弧长 s 查询曲线上的点(保证匀速)
    pub fn sample_at_arc_length(&self, mut s: f32) -> Vec3 {
        if s <= 0.0 { return self.points[0]; }
        if s >= self.total_length { return *self.points.last().unwrap(); }
        // 找到 s 落在第几段
        let mut seg = 0;
        let mut seg_offset = 0.0;
        let mut accum = 0.0;
        for (i, table) in self.arc_tables.iter().enumerate() {
            let seg_len = table.samples.last().unwrap().1;
            if accum + seg_len >= s {
                seg = i;
                seg_offset = s - accum;
                break;
            }
            accum += seg_len;
        }
        // 段内二分
        let table = &self.arc_tables[seg];
        let mut lo = 0usize;
        let mut hi = table.samples.len() - 1;
        while hi - lo > 1 {
            let mid = (lo + hi) / 2;
            if table.samples[mid].1 < seg_offset { lo = mid; } else { hi = mid; }
        }
        let (t0, s0) = table.samples[lo];
        let (t1, s1) = table.samples[hi];
        let local_t = t0 + (t1 - t0) * (seg_offset - s0) / (s1 - s0);
        // 重新取出该段的 4 个点
        let p0 = if seg == 0 { self.points[0] } else { self.points[seg - 1] };
        let p1 = self.points[seg];
        let p2 = self.points[seg + 1];
        let p3 = if seg + 2 < self.points.len() { self.points[seg + 2] } else { self.points[seg + 1] };
        catmull_rom_segment(p0, p1, p2, p3, local_t)
    }
}

#[inline]
fn catmull_rom_segment(p0: Vec3, p1: Vec3, p2: Vec3, p3: Vec3, t: f32) -> Vec3 {
    let t2 = t * t;
    let t3 = t2 * t;
    0.5 * (2.0 * p1
         + (-p0 + p2) * t
         + (2.0*p0 - 5.0*p1 + 4.0*p2 - p3) * t2
         + (-p0 + 3.0*p1 - 3.0*p2 + p3) * t3)
}
```

### 8.2 第二步:5 个机位的 cinematic camera path

在 `camera.rs` 或主 loop 里加 cinematic state:

```rust
pub struct CinematicState {
    pub path_pos: CatmullRomPath,    // 相机位置路径
    pub path_look: CatmullRomPath,   // look-at 目标路径
    pub elapsed: f32,
    pub duration: f32,               // 总播放时长(秒)
}

impl CinematicState {
    pub fn new(cam_points: Vec<Vec3>, look_points: Vec<Vec3>, duration: f32) -> Self {
        assert_eq!(cam_points.len(), look_points.len());
        Self {
            path_pos: CatmullRomPath::new(cam_points),
            path_look: CatmullRomPath::new(look_points),
            elapsed: 0.0,
            duration,
        }
    }
    pub fn update(&mut self, dt: f32, cam: &mut Camera) -> bool {
        self.elapsed += dt;
        if self.elapsed >= self.duration {
            return false; // 播完
        }
        // 弧长比例(匀速)
        let s_frac = self.elapsed / self.duration;
        let s_pos = s_frac * self.path_pos.total_length;
        let s_look = s_frac * self.path_look.total_length;
        let pos = self.path_pos.sample_at_arc_length(s_pos);
        let look = self.path_look.sample_at_arc_length(s_look);
        cam.pos = pos;
        cam.forward = (look - pos).normalize();
        true
    }
}
```

在 main loop 里:

```rust
let mut cinematic = CinematicState::new(
    vec![
        Vec3::new(0.0, 5.0, 10.0),
        Vec3::new(8.0, 7.0, 2.0),
        Vec3::new(12.0, 4.0, -5.0),
        Vec3::new(4.0, 9.0, -12.0),
        Vec3::new(-6.0, 6.0, -8.0),
    ],
    vec![
        Vec3::ZERO,
        Vec3::new(2.0, 1.0, 0.0),
        Vec3::new(4.0, 0.0, -3.0),
        Vec3::new(2.0, 2.0, -6.0),
        Vec3::new(-1.0, 1.0, -4.0),
    ],
    4.2, // 4.2 秒走完
);

// 主循环
while running {
    let dt = ...;
    if !cinematic.update(dt, &mut camera) {
        // 播完,切回游戏相机
    }
    render(&camera);
}
```

跑起来你应该看到镜头平滑、匀速地穿过 5 个机位,每个机位处镜头方向都看向指定的 look-at 点。**对比一下第 0 节那个 lerp 版本**——你的镜头不再有"急转",不再忽快忽慢。这就是样条的力量。

### 8.3 第三步:cubic Bézier easing

接下来给 UI 加一个 Bézier 缓动。先实现 1D Bézier + 反查(从 x 求 t):

```rust
/// 1D 三次 Bézier(P0=0, P3=1 是固定的,P1, P2 是控制参数)
pub struct CubicBezierEase {
    pub p1: f32,  // 控制点 1 的 y 值(x 由 reparam 给)
    pub p2: f32,
}

impl CubicBezierEase {
    pub fn ease_in_out() -> Self {
        // 等价 CSS cubic-bezier(0.42, 0, 0.58, 1)
        Self { p1: 0.42, p2: 0.58 }
    }
    pub fn ease_in() -> Self {
        Self { p1: 0.42, p2: 1.0 }
    }
    pub fn ease_out() -> Self {
        Self { p1: 0.0, p2: 0.58 }
    }
    /// 输入时间 t ∈ [0,1],返回缓动后的值 ∈ [0,1]
    pub fn sample(&self, x: f32) -> f32 {
        // CSS 约定:x 是时间,y 是输出。我们要从 x 反查 t。
        let t = self.solve_t_for_x(x);
        // 用 t 同时算 x 和 y 分量(注意 P0.x=0, P3.x=1)
        // 这里 P1.x = self.p1, P2.x = self.p2 是错的——CSS 的两个数是
        // (P1.x, P1.y) 和 (P2.x, P2.y)。我们用更直观的接口:
        // 让用户直接传 (P1x, P1y, P2x, P2y)
        self.bezier_y(t)
    }
    fn solve_t_for_x(&self, x: f32) -> f32 {
        // 牛顿法 4 次迭代(对 cubic Bézier x 分量单调时收敛极快)
        let mut t = x; // 初始猜测
        for _ in 0..8 {
            let x_val = self.bezier_x(t) - x;
            if x_val.abs() < 1e-6 { return t; }
            let dx = self.bezier_x_deriv(t);
            if dx.abs() < 1e-6 { break; }
            t -= x_val / dx;
        }
        t.clamp(0.0, 1.0)
    }
    fn bezier_x(&self, t: f32) -> f32 { self.p1x_blend(t) }
    fn bezier_y(&self, t: f32) -> f32 { self.p1y_blend(t) }
    // ... 见下方完整实现
}
```

完整版接口更清晰——让用户直接传 CSS 风格 4 个数。这里给出最终干净版本:

```rust
pub struct CubicBezierEase {
    pub p1x: f32, pub p1y: f32,
    pub p2x: f32, pub p2y: f32,
}

impl CubicBezierEase {
    pub fn new(p1x: f32, p1y: f32, p2x: f32, p2y: f32) -> Self {
        Self { p1x, p1y, p2x, p2y }
    }
    /// 从时间 x ∈ [0,1] 反查 t,再算 y
    pub fn at(&self, x: f32) -> f32 {
        let t = self.solve_t_for_x(x);
        self.bezier_component(t, self.p1y, self.p2y)
    }
    fn solve_t_for_x(&self, x: f32) -> f32 {
        let mut t = x;
        for _ in 0..8 {
            let err = self.bezier_component(t, self.p1x, self.p2x) - x;
            if err.abs() < 1e-6 { return t; }
            let deriv = self.bezier_deriv(t, self.p1x, self.p2x);
            if deriv.abs() < 1e-6 { break; }
            t -= err / deriv;
        }
        // 退到二分保底(牛顿发散时)
        let mut lo = 0.0_f32;
        let mut hi = 1.0_f32;
        for _ in 0..32 {
            t = 0.5 * (lo + hi);
            let xv = self.bezier_component(t, self.p1x, self.p2x);
            if (xv - x).abs() < 1e-6 { return t; }
            if xv < x { lo = t; } else { hi = t; }
        }
        t
    }
    #[inline]
    fn bezier_component(&self, t: f32, p1: f32, p2: f32) -> f32 {
        // P0 = 0, P3 = 1
        let u = 1.0 - t;
        3.0 * u * u * t * p1 + 3.0 * u * t * t * p2 + t * t * t
    }
    #[inline]
    fn bezier_deriv(&self, t: f32, p1: f32, p2: f32) -> f32 {
        let u = 1.0 - t;
        3.0 * u * u * p1 + 6.0 * u * t * (p2 - p1) + 3.0 * t * t * (1.0 - p2)
    }
}
```

### 8.4 第四步:用 easing 驱动 UI 滑入

UI 面板从 `x = -300` 滑到 `x = 0`,用 ease-out:

```rust
pub struct SlideInAnim {
    pub start_x: f32,
    pub end_x: f32,
    pub elapsed: f32,
    pub duration: f32,
    pub ease: CubicBezierEase,
}

impl SlideInAnim {
    pub fn new() -> Self {
        Self {
            start_x: -300.0,
            end_x: 0.0,
            elapsed: 0.0,
            duration: 0.35,
            ease: CubicBezierEase::new(0.0, 0.58, 1.0, 1.0), // ease-out
        }
    }
    pub fn update(&mut self, dt: f32) -> f32 {
        self.elapsed += dt;
        let x = (self.elapsed / self.duration).min(1.0);
        let eased = self.ease.at(x);
        self.start_x + (self.end_x - self.start_x) * eased
    }
    pub fn done(&self) -> bool { self.elapsed >= self.duration }
}
```

跑起来你应该看到面板**先快后慢**滑入,停在目标位置,完全没有 PowerPoint 那种"机器人匀速"的感觉。**这就是 [game-feel-03-feedback-juice](../../phase-2/deep-dives/game-feel-03-feedback-juice.md) 里讲的 juice 的核心——而 juice 的数学骨架,就是你今天写的 cubic Bézier**。

### 8.5 第五步:验证(肉眼 + 数据)

肉眼:镜头路径回放,在每个机位不应有急转;UI 滑入有"减速到停"的手感。

数据:在 cinematic 路径上每 0.1 秒采样一次位置,记录相邻采样距离。**匀速意味着这些距离应该全部接近相等**(误差 < 1%)。如果你看到某些段距离 3 倍于其他段,说明弧长参数化有 bug——通常是段间累积弧长统计错误。

到此 spline 从抽象数学变成你游戏里实际跑的代码——相机路径匀速平滑,UI 有手感。数学不再是死的公式。

## 9 · 练习

**Lv1(理解)**:把 Catmull-Rom 的切线公式 `mᵢ = (P_{i+1} - P_{i-1})/2` 改成 `mᵢ = (P_{i+1} - P_{i-1})`(不除 2),观察 cinematic 路径的形状变化。预期:曲线在每个机位处"急转更猛",因为切线长度变成 2 倍。理解切线**长度**和切线**方向**分别控制什么。

**Lv2(实现)**:给 `CatmullRomPath` 加 **centripetal 变种**:在 `new()` 里把每段的局部 t 重新按 `√|P_{i+1} - Pᵢ|` 加权分配。设置 5 个间距悬殊的控制点(比如 [0, 1, 2, 50, 51]),对比 uniform 和 centripetal 版本——uniform 版本在密集区附近应能看到自交小环,centripetal 版本应该消除掉。

**Lv3(综合)**:实现 **Kochanek-Bartels TCB spline**(tension / bias / continuity 三个参数),把它接到你的 cinematic camera 上。给每个机位加不同的 tension(比如中段 tension=0.5 让镜头"减速过弯"),观察效果。这是 Maya/3ds Max 动画曲线的数学。

**Lv4(挑战)**:实现 **squad 球面四边形插值**(spherical quadrangle interpolation)——Catmull-Rom 的 quaternion 版本,用于旋转曲线。用它在 cinematic 里同时插值相机的位置(Catmull-Rom)和朝向(squad),保证相机 roll/pitch/yaw 全部平滑。需要先理解 [camera-systems](camera-systems.md) 里的 quaternion 内容和 [phase-0/20-math-foundation-extended](../../phase-0/20-math-foundation-extended.md) 的四元数章节。

## 10 · 生产现实:用现成的还是自己写

工业引擎都有 spline 库:**Unreal** 有 `USplineComponent`(Catmull-Rom)和 `USplineMeshComponent`(沿样条变形网格);**Unity** 有 `AnimationCurve`(Hermite 风格)和 Cinemachine 的 dolly;**Bevy** 在 0.13 之后引入了 `bevy::math::curve` 模块,支持 cubic Bézier / Catmull-Rom / 各种 easing 函数,生态在快速成熟。

**什么时候用现成的**:绝大多数情况下,用引擎自带的。它们已经处理了边界、弧长、序列化、编辑器集成,你只需要"放控制点"。

**什么时候自己写**:三个场景。第一,你在写自己的引擎(像 Handmade Hero 这种教学项目),从零理解每个数学选择。第二,引擎的 spline 不支持你要的功能(比如你要 centripetal Catmull-Rom + 自定义 TCB 参数 + 弧长参数化,Bevy 的标准库未必全有)。第三,你要极致优化——固定长度查表、SIMD 批量求值、GPU 上跑样条。在这些场景下,理解 Cox-de Boor 递归、de Casteljau 算法、Bernstein 多项式的等价关系,让你能从引擎文档的字里行间读出"它在做什么",并能写出更好的版本。

样条是个有趣的工具——它在游戏里**无处不在**却又**隐形**。今天你打开了这层隐形的幕布,从数学到 Rust 实现到 cinematic camera 部署,把曲线的力量握在了自己手里。下次你看到 Unity 的 AnimationCurve 窗口、Unreal 的 Sequencer spline track、CSS 的 cubic-bezier 滑块——你能透过 UI 看到底层的 Bernstein 多项式、de Casteljau 递归、Cox-de Boor 公式,知道每一条曲线在哪里平滑、在哪里急转、为什么。这就是数学成熟度,也是 [cutscene-and-timeline](../../phase-7/deep-dives/cutscene-and-timeline.md) 这种上层工具能站在你肩膀上的原因。

## 11 · 延伸阅读

- [Pomax 的 Bézier primer](https://pomax.github.io/bezierinfo/) — 业界公认最完整的 Bézier 在线教程,从初等数学讲到高级算法(自适应细分、弧长参数化、命中测试),全程带交互式 demo。读这一份抵十本教材。
- [Spline MNIST visualization (Jason Davies)](https://www.jasondavies.com/animated-bezier/) — Bézier 控制点如何塑造曲线的可视化,直观到令人窒息。
- [Catmull-Rom 原始论文(1974)](https://www.cs.cmu.edu/~fp/courses/graphics/asrt/catmull-rom.pdf) — Edwin Catmull(Pixar 创始人之一)和 Raphael Rom 的原文,简短精到。
- [Twilight Edge: Centripetal Catmull-Rom](https://www.cemyuksel.com/research/catmullrom_param/) — Cem Yuksel 关于 centripetal / chordal / uniform 三种参数化对比的研究,带图说明自交问题。
- [The Continuity of Splines (Freya Holmer)](https://www.youtube.com/watch?v=jvPPXbo87ds) — 一小时视频讲解 C⁰/C¹/C² 连续性,业界最佳直觉建立材料,看完你会"看"到样条。
- [kurbo crate](https://github.com/linebender/kurbo) — Rust 的高质量 2D 曲线库,Linebender(Rust GUI 生态)出品。源码读起来就是一本 spline 工程手册。
- [lyon_geom crate](https://docs.rs/lyon_geom/latest/lyon_geom/) — Rust 的图形几何库,包含 Bézier / quadratic / cubic / arc 的完整实现,Mozilla Servo 团队出品。
- [Cox-de Boor 递归的 Wikipedia](https://en.wikipedia.org/wiki/De_Boor%27s_algorithm) — B-spline 求值的标准算法,带伪代码。
- 内部延伸:[projection-matrices](projection-matrices.md)(投影矩阵,spline 路径上的点最终要经过投影到屏幕);[camera-systems](camera-systems.md)(本篇 spline 应用最直接的载体);[game-feel-03-feedback-juice](../../phase-2/deep-dives/game-feel-03-feedback-juice.md)(easing 曲线 = Bézier,本篇给出了数学根基);[cutscene-and-timeline](../../phase-7/deep-dives/cutscene-and-timeline.md)(cinematic 系统的 spline 应用上层);[animation-blending-and-state-machine](animation-blending-and-state-machine.md)(transform 的样条插值);[phase-0/20-math-foundation-extended](../../phase-0/20-math-foundation-extended.md)(向量、矩阵、多项式的基础数学)。
