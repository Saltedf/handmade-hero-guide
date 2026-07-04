
# 柔体、布料、流体与破坏深度专题

> 你跟着 Handmade Hero 走完了 [physics-engine-complete.md](physics-engine-complete.md),亲手写出 500 行 Sequential Impulse 引擎,4 个箱子能稳定叠在地面上,玩家跳上去不会抖。你以为物理引擎这扇门你已经推开了。然后你想给主角加一件披风,加一面在风中飘的旗帜,加一汪被打到会溅起的水,加一堵被炮弹击中后碎裂的砖墙。你打开 Rapier 的文档,翻完三遍——里面没有任何"布料"的 API,没有"水"的 API,没有"破碎"的 API。你以为是你没找到,跑到论坛去问,得到的答案是:**那些不是刚体物理,刚体引擎永远做不了**。你愣住了。箱子、球、角色都是刚体(rigid body)——它们的形状永远不变,只动 6 个自由度(位置 + 朝向)。但一面旗帜的形状**就是它本身的运动**,水没有"形状"可言,墙被打碎会变成几十块新的刚体。这是**完全另一类数学问题**,需要完全另一套求解器。今天这一篇,就打开刚体之外那扇门:从 Position-Based Dynamics(位置基础动力学,PBD)讲起,把布料、柔体、流体、破坏一一拆开,讲清楚每种用了什么数学、为什么用、怎么用 Rust 写出来,以及为什么 PBD 这个名字会在未来十年反复出现在你看到的每一篇游戏物理演讲里。
>
> 读完这一篇,你能解释为什么布料用 PBD 而不能用 Sequential Impulse,能写出 200 行 Rust 跑通一面会飘的布,能区分 SPH 和 Eulerian 流体的应用场景,能说出 Voronoi 破碎和预切割破碎的差别,能在自己 HH 项目里把一片布料挂在角色肩膀上,看着它在重力下自然垂下来。

## 0 · 为什么刚体物理做不了这些

在 [physics-engine-complete.md](physics-engine-complete.md) 里我们花了上万字讲清楚一件事:**刚体(rigid body)**是一个理想化对象,它有形状(几何)、有质量分布(密度),但**永远不变形**。两个刚体碰撞,各自形状不变,只是动量交换。整套 Sequential Impulse、Baumgarte、warm starting,都建立在这个"形状不变"的前提之上。

但你现在要做的事情,**全部都违反这个前提**。

一面旗帜在风中飘动——旗帜的**形状每一帧都在变**,从平整变成波浪,从波浪变成卷曲。如果你硬要用刚体来近似,只能把旗帜切成 1000 个小三角形刚体,然后用 joint 把它们连起来。但 1000 个三角形 + 几千个 joint 是一个**病态(ill-conditioned)的约束系统**——每一帧求解器要在几千个互相耦合的约束之间反复迭代, Sequential Impulse 的收敛速度在这种情况下急剧下降,你要么把 iterations 调到几百(帧率崩盘),要么眼睁睁看着旗帜抽搐成一团。这就是为什么 2000 年之前的游戏里,主角的披风要么是"贴在身上不动的贴图",要么是"完全脚本化的预录动画",几乎没有真正的物理披风。

水更夸张。一汪水里你有 10000 个"水分子",每个都要和邻居相互作用,水花溅起来时它们要分离,水滴落下时要汇合。如果你把每个水分子都做成一个小刚体,10000 个刚体两两碰撞是 O(N²) = 5000 万次碰撞检测,每帧跑不动;即便跑动了,水分子之间的"凝聚力"(让水聚成水滴而非散开的力)刚体物理也没有任何 API 可以表达。

破坏更有意思——一面墙本来是一个刚体,被炮弹击中后**变成几十个新的刚体**,每个碎片有自己的形状、速度、角速度。这看起来像是"刚体物理能做的事",但问题在于:**碎片怎么生成**?是在击中点周围按某种规则切割几何体吗?如何保证切出来的碎片是凸的(刚体引擎 narrowphase 要求凸)?如何让切割线和裂缝看起来真实(不是机械的网格切割,而是像石头崩裂那种不规则)?

这三个场景告诉你一件事:**刚体物理是一种特殊化(specialization)**,它假设"形状不变"。一旦这个假设不成立,你需要的是**完全不同的数学**。本篇要讲的,就是这些不同的数学。

具体地,刚体物理和软体/流体物理在数学结构上有三个根本差异。

第一,**自由度数量**。一个刚体在 3D 中有 13 个状态量(位置 3 + 四元数 4 + 线速度 3 + 角速度 3)。一片 32×32 网格的布料有 1024 个粒子,每个粒子 3 个位置分量,共 3072 个自由度——这是一片很小的布。一汪水用 SPH 模拟,10 万粒子很常见,共 30 万自由度。自由度数量直接决定求解器的复杂度——求解线性方程组是 O(N³),1024 个粒子是 10⁹ 次运算,根本不可能每帧跑。所以软体/流体物理的求解器**全部都是迭代近似**,而且迭代次数远比刚体求解器少(刚体 8-15 次,布料 PBD 通常 10-20 次,SPH 流体根本不解线性方程组,只做粒子间力累加)。

第二,**约束的"刚性"**。布料的纤维几乎不可拉伸——一根 1 米的纤维拉到 1.01 米就需要几千牛顿的力。在数学上这对应一个**刚度极高(stiffness)的约束**,在 [numerical-methods.md](numerical-methods.md) 里我们详细讲过:stiff 约束在显式积分器下会爆炸,必须用隐式方法或直接绕开力模型。Sequential Impulse 是基于力的(soft constraint 形式),面对布料这种高刚度会非常不稳定。这就是 PBD 出现的根本原因——**PBD 不算力,直接改位置**,从根上绕开了 stiff 问题。

第三,**碰撞的拓扑**。刚体物理里碰撞检测是"两两凸包"的 narrowphase,GJK + EPA 假设每个物体是一个凸包。但布料是 1024 个粒子组成的"非凸 mesh",水是 10 万个粒子组成的"无形状流体",这种几何用 GJK 是没法处理的。你需要的是**粒子-网格碰撞**、**粒子-粒子碰撞**、**mesh-mesh 碰撞**,这些和刚体物理的碰撞检测是两套完全不同的算法。

讲到这里你应该明白为什么这是"另一篇 deep-dive"而不是 [physics-engine-complete.md](physics-engine-complete.md) 的某一节了。下面我们一个一个展开。

## 1 · Position-Based Dynamics:绕开 stiff 问题的钥匙

整个柔体/布料物理在过去 20 年最重要的一篇论文,是 Matthias Müller 等人 2006 年发表的《Position Based Dynamics》。这篇文章的思想如此简洁而有效,以至于今天 Unity、Unreal、NVIDIA PhysX 内部的 cloth / soft body 模块,**核心算法都是 PBD 或 PBD 的变种**。这一节,我们彻底讲清楚 PBD 在做什么。

### 1.1 力-based 方法的死结

先回顾一下 [physics-engine-complete.md](physics-engine-complete.md) 里 Sequential Impulse 在做什么。每一步:
- 把外力(重力、风)累加到刚体上,变成加速度
- 用半隐式 Euler 把加速度积分成速度,把速度积分成位置
- 跑约束求解器(Sequential Impulse),调整速度让约束满足
- 用 Baumgarte 修正穿透

这是一套**力-速度-位置**(force-velocity-position)的流程。整条链条的关键是:**所有约束最终都通过修改"速度"来满足**。距离约束(`|A - B| = L`)写成"沿连线方向的相对速度 = 0",非穿透约束写成"沿法线方向的相对速度 ≤ 0"。

这套流程在刚体上工作得很好,因为刚体的"约束"是**硬度有限的**:一个 distance joint 的 stiffness 可以通过 soft constraint 的公式 `soft_mass = mass + h·damping + h²·stiffness` 任意调节,刚体物理根本不需要 stiffness 趋向无穷。

但布料不是这样。布料的纤维**几乎完全不可拉伸**——一根 1 米的纤维你拉到 1.001 米,物理上确实发生了拉伸,但对应的力是极大的(几千牛顿量级),在数学上这等价于 `stiffness → ∞`。把这种约束塞进 Sequential Impulse 的 soft constraint 公式,会发生什么?看公式 `soft_mass = mass + h·damping + h²·stiffness`,当 stiffness 极大时,`soft_mass` 极大,而冲量 `J = -(stiffness·C + damping·dC/dt) / soft_mass`,在 stiff 占主导时 `J ≈ -C / (h²·stiffness) · stiffness = -C / h²`——看起来还行?但问题是 `J` 应用到速度上之后,**位置变化 `Δx = v·h`** 走的步子很小,需要很多帧才能把约束误差 `C` 消除掉。这意味着在力-based 模型下,你的布料看起来总是"软塌塌"——明明应该不可拉伸的纤维,在游戏里被拉成原来的两倍长。

提高 stiffness?好,你把 stiffness 调到 10⁶。然后 [numerical-methods.md](numerical-methods.md) 告诉你会发生什么:显式积分器在 stiff 系统下**数值不稳定**,半隐式 Euler 也撑不住,某一步速度突然变成 10⁸,布料粒子瞬间飞到屏幕外。这就是为什么 1990 年代的游戏里几乎没有真正的物理布料——力-based 方法在这条路上是个死结。

### 1.2 PBD 的核心思想:直接改位置

PBD 的天才之处在于绕开整条"力-速度-位置"的链条,**直接在位置层面做约束**。算法是:

```
每帧:
    1. 对每个粒子,用外力做一次预测位置(predict)
       p_i_predicted = p_i + v_i·dt + (F_ext / m_i)·dt²
    2. 对每个约束(距离、弯曲、碰撞),迭代 K 次:
       直接修改 p_i_predicted,让约束 C(p) = 0(或 ≤ 0)被满足
    3. 用约束后的位置反推速度:
       v_i_new = (p_i_predicted - p_i) / dt
    4. 把 p_i 设为 p_i_predicted
```

关键在第 2 步:**PBD 不算力,不更新速度,直接投影位置**。每一步约束求解就是把粒子位置"挪一下",让它满足约束。一个距离约束 `|p_a - p_b| = L`,如果当前位置 `|p_a - p_b| = L + δ`(被拉长了 δ),PBD 就直接把 a 和 b 各向中间挪 δ/2(质量相等时),一步到位。

这种方法的优点是**无条件稳定**。无论你设的"目标距离" L 是多少,无论 stiffness 看起来多大,PBD 不会数值爆炸——它最多就是"约束没完全满足",但位置永远是有限的、可控的。stiffness 在 PBD 里被一个 0-1 的参数 `k` 控制,表示"每次迭代把约束误差消除多少比例"。`k = 1` 意味着完全消除(完全刚性),`k = 0.5` 意味着每次消除一半(模拟弹性)。

```rust
// PBD 单步主循环
pub fn pbd_step(particles: &mut [Particle], constraints: &[Constraint],
                ext_forces: &dyn Fn(&Particle) -> Vec3, dt: f32,
                iterations: usize) {
    let n = particles.len();
    
    // 1. 预测位置(用半隐式 Euler 思路)
    // 注意外力直接进 predicted position,不更新真实的 velocity
    for p in particles.iter_mut() {
        let accel = ext_forces(p) / p.inv_mass.recip();  // a = F/m
        p.velocity += accel * dt;
        p.predicted_position = p.position + p.velocity * dt;
    }
    
    // 2. 约束求解(投影 Gauss-Seidel)
    for _ in 0..iterations {
        for c in constraints {
            project_constraint(c, particles);  // 直接改 predicted_position
        }
    }
    
    // 3. 用约束后位置反推速度,提交位置
    for p in particles.iter_mut() {
        p.velocity = (p.predicted_position - p.position) / dt;
        p.position = p.predicted_position;
    }
}
```

注意第三个微妙之处:**PBD 把速度当作"位置的派生量",而不是独立状态**。速度永远是从位置变化反推出来的(`v = (p_new - p_old) / dt`),这意味着速度永远不会"爆炸"——只要位置可控,速度就可控。这是 PBD 无条件稳定的根源。

### 1.3 单个距离约束的投影

PBD 最常用、最简单的约束是**距离约束(distance constraint)**:两个粒子 a、b 应该保持距离 L。约束函数 `C(p_a, p_b) = |p_a - p_b| - L`。当 `C ≠ 0` 时,我们要把 `p_a` 和 `p_b` 各挪一点,让 `C = 0`。

推导:对 `C` 求梯度 `∇C`(对 `p_a` 和 `p_b` 分别求偏导),得到约束的"法线方向":

```
∇_{p_a} C = (p_a - p_b) / |p_a - p_b| =: n
∇_{p_b} C = -n
```

PBD 的投影公式(来自 Müller et al. 2006)是:

```
Δp_a = -  (w_a / (w_a + w_b)) · C · n
Δp_b = +  (w_b / (w_a + w_b)) · C · n
```

其中 `w_a = 1/m_a` 是 a 的**倒数质量**(inverse mass)。这个公式的物理意义:**质量大的粒子挪得少,质量小的粒子挪得多**;两个等质量粒子各挪一半。如果 a 是钉死的(静态粒子,`w_a = 0`),只有 b 移动。

加上 stiffness `k ∈ [0, 1]`:

```
Δp_a = -k · (w_a / (w_a + w_b)) · C · n
```

`k = 1` 完全刚性,`k = 0.5` 半刚性(每次只消除一半误差)。Rust 实现:

```rust
#[derive(Copy, Clone, Debug)]
pub struct DistanceConstraint {
    pub a: usize,            // 粒子 a 的索引
    pub b: usize,            // 粒子 b 的索引
    pub rest_length: f32,    // 静止长度 L
    pub stiffness: f32,      // 0.0 ~ 1.0
}

pub fn project_distance(c: &DistanceConstraint, particles: &mut [Particle]) {
    let pa = particles[c.a].predicted_position;
    let pb = particles[c.b].predicted_position;
    let delta = pa - pb;
    let dist = delta.length();
    if dist < 1e-9 { return; }  // 避免除零
    
    let n = delta / dist;
    let c_err = dist - c.rest_length;  // 约束误差 C
    let wa = particles[c.a].inv_mass;
    let wb = particles[c.b].inv_mass;
    let w_sum = wa + wb;
    if w_sum <= 0.0 { return; }  // 两个都钉死
    
    // 带 stiffness 的位移
    let correction_a = -c.stiffness * (wa / w_sum) * c_err;
    let correction_b =  c.stiffness * (wb / w_sum) * c_err;
    
    particles[c.a].predicted_position += n * correction_a;
    particles[c.b].predicted_position += n * correction_b;
}
```

这是 PBD 的"核心 10 行"。理解了这 10 行,你就理解了 PBD 的精髓——所有更复杂的约束(弯曲约束、体积约束、碰撞约束)都是同一个模板:**算约束误差 `C`,算梯度方向 `n`,按倒数质量分配位移**。

### 1.4 为什么 PBD 对布料这么合适

回到布料的问题。布料的纤维几乎不可拉伸,在力-based 模型下是"stiffness = ∞"的 stiff 系统,数值不稳定。但在 PBD 下,"不可拉伸"就是 `stiffness = 1`,每次迭代**完全消除距离误差**。无论迭代多少次,粒子位置永远在有限范围内,PBD 不会爆炸。

更进一步,PBD 有一个绝佳的性质:**stiffness 的"有效刚度"随迭代次数增加而增加**。`k = 0.5` 迭代 10 次,等效刚度接近 `1 - (1 - 0.5)^10 ≈ 0.999`,几乎是刚性的。这意味着你可以用很小的 `k`(每次迭代只修一小部分误差,数值上稳定)和较多的迭代次数,等效得到非常刚硬的约束。这种"小步累积"的特性让 PBD 在数值稳定性上远胜力-based 方法。

PBD 的弱点是**精度低**——它是位置层面的迭代近似,不像 Implicit Euler 那样能严格求解 stiff ODE。但游戏物理不需要精度,需要的是"看起来对"。PBD 把"看起来对"和"无条件稳定"同时拿到手,这就是它统治布料/柔体物理 20 年的原因。

## 2 · 布料:PBD 的经典应用

讲完 PBD 的原理,布料就是它的直接应用。一片布料在数学上是什么?**一张 2D 网格的粒子,加上三类约束**:

### 2.1 布料的三类约束

**结构约束(structural constraints)**:网格上水平、垂直相邻粒子之间的距离约束。这是布料最基本的"网格"——12×12 个粒子,水平 11×12 = 132 条边,垂直 11×12 = 132 条边,共 264 条结构约束。这些约束阻止布料在网格方向上被撕裂或拉伸。

**剪切约束(shear constraints)**:网格上对角线相邻粒子之间的距离约束。每个"格子"有两条对角线,11×11 个格子共 242 条剪切约束。这些约束阻止布料被"剪切"——沿对角线方向滑动变形。

**弯曲约束(bending constraints)**:网格上隔一格的粒子(跨过中间粒子的"二跳"邻居)之间的距离约束。这些约束阻止布料过度折叠——一片平的布可以轻轻折叠,但不能折成纸飞机那种锐角。弯曲约束对应布料的"硬度",决定了旗帜是硬挺地飘还是软塌塌地垂。

```rust
pub fn build_cloth_grid(cols: usize, rows: usize, spacing: f32,
                        origin: Vec3) -> (Vec<Particle>, Vec<DistanceConstraint>) {
    let mut particles = Vec::with_capacity(cols * rows);
    let mut constraints = Vec::new();
    
    // 1. 生成粒子
    for j in 0..rows {
        for i in 0..cols {
            let p = origin + Vec3::new(i as f32 * spacing, 0.0, j as f32 * spacing);
            particles.push(Particle {
                position: p,
                predicted_position: p,
                velocity: Vec3::ZERO,
                inv_mass: 1.0,  // 默认动态
            });
        }
    }
    
    let idx = |i: usize, j: usize| j * cols + i;
    
    // 2. 结构约束(水平 + 垂直)
    for j in 0..rows {
        for i in 0..cols {
            if i + 1 < cols {
                constraints.push(DistanceConstraint {
                    a: idx(i, j), b: idx(i + 1, j),
                    rest_length: spacing, stiffness: 1.0,
                });
            }
            if j + 1 < rows {
                constraints.push(DistanceConstraint {
                    a: idx(i, j), b: idx(i, j + 1),
                    rest_length: spacing, stiffness: 1.0,
                });
            }
        }
    }
    
    // 3. 剪切约束(两条对角线)
    let diag = (spacing * spacing * 2.0).sqrt();
    for j in 0..(rows - 1) {
        for i in 0..(cols - 1) {
            constraints.push(DistanceConstraint {
                a: idx(i, j), b: idx(i + 1, j + 1),
                rest_length: diag, stiffness: 0.5,  // 剪切稍弱
            });
            constraints.push(DistanceConstraint {
                a: idx(i + 1, j), b: idx(i, j + 1),
                rest_length: diag, stiffness: 0.5,
            });
        }
    }
    
    // 4. 弯曲约束(跨过邻居的"二跳")
    for j in 0..rows {
        for i in 0..cols {
            if i + 2 < cols {
                constraints.push(DistanceConstraint {
                    a: idx(i, j), b: idx(i + 2, j),
                    rest_length: spacing * 2.0, stiffness: 0.1,  // 弯曲更弱
                });
            }
            if j + 2 < rows {
                constraints.push(DistanceConstraint {
                    a: idx(i, j), b: idx(i, j + 2),
                    rest_length: spacing * 2.0, stiffness: 0.1,
                });
            }
        }
    }
    
    (particles, constraints)
}
```

`stiffness` 的差别决定了布料的"性格":结构约束 1.0(几乎不可拉伸),剪切 0.5(允许少量剪切变形),弯曲 0.1(很容易折叠)。这种递减的 stiffness 模式是布料物理的工业标配——CUDA Cloth、PhysX Cloth、Marvelous Designer 都用类似的差异设置。

### 2.2 把布料"钉"在墙上:静态粒子

一片自由落体的布料没什么意思——它就掉到地上。要让布料变成"旗帜"或"披风",你需要把它的一部分粒子**钉死**。在 PBD 里钉死一个粒子就是设它的 `inv_mass = 0`,这样所有涉及它的约束投影都会**只移动另一端的粒子**,被钉的粒子永远不动。

```rust
// 把布料最左上角和最右上角的粒子钉死(挂一根晾衣绳)
particles[idx(0, 0)].inv_mass = 0.0;
particles[idx(cols - 1, 0)].inv_mass = 0.0;
```

钉完之后跑 PBD,布料就会从两个挂点垂下来,中间因为重力 + 距离约束形成一个弧形。把钉点换成角色肩膀上的两个固定世界坐标,你就有了主角的披风。

### 2.3 风力:外力

布料最迷人的瞬间是它在风里飘。风在 PBD 里就是**外力**,在每帧第 1 步预测位置时加进去:

```rust
let ext_forces = |p: &Particle| -> Vec3 {
    let mut f = Vec3::new(0.0, -9.81 / p.inv_mass, 0.0);  // 重力(注意 F = m·g)
    
    // 风力:假设风沿 +x 方向,大小 wind_strength
    let wind_dir = Vec3::new(1.0, 0.0, 0.3).normalize();
    let wind_strength = 5.0;
    
    // 关键:风力和粒子法线有关
    // 简化:用一个全局风向,所有粒子都受同样的力
    // 进阶:根据粒子所在网格的法线,做"迎风面"和"背风面"的区别
    f += wind_dir * wind_strength;
    
    f
};
```

简单的"全局风"是均匀的力,效果一般——所有粒子被同样推动,布料只是平移。要做出"波浪"效果,风力需要随时间变化,**或者**根据粒子面的法线方向变化。法线可以从邻居粒子的叉积算出来:

```rust
// 估算粒子 (i, j) 的法线:用两个邻居方向的叉积
fn estimate_normal(particles: &[Particle], cols: usize, i: usize, j: usize) -> Vec3 {
    let idx = |i: usize, j: usize| j * cols + i;
    let center = particles[idx(i, j)].predicted_position;
    let right = particles.get(idx(i + 1, j)).map(|p| p.predicted_position)
                 .unwrap_or(center);
    let up    = particles.get(idx(i, j + 1)).map(|p| p.predicted_position)
                 .unwrap_or(center);
    let n = (right - center).cross(&(up - center));
    n.normalize_or_zero()
}

// 然后风力大小 ∝ max(0, wind_dir · normal)
// 迎风面风力大,平行风面几乎不受力
fn wind_force(p: &Particle, normal: Vec3, wind_dir: Vec3, wind_speed: f32) -> Vec3 {
    let facing = wind_dir.dot(normal).max(0.0);  // 0 ~ 1
    wind_dir * (wind_speed * facing / p.inv_mass.max(1e-6))
}
```

这就是为什么真实旗帜会"波浪式"飘动——旗帜的不同部分法线方向不同,迎风面受力大,侧面几乎不受力。这种"局部法线"的细节让 PBD 布料和真实旗帜看起来一模一样。

### 2.4 碰撞:布料和角色

布料挂在一个角色身上,它要和角色的身体碰撞——披风不能穿进胸膛。布料 vs 角色碰撞是经典的**粒子 vs 凸包**碰撞:每个布料粒子,如果它穿进了角色的 collider(比如一个 sphere 或 capsule),就把它推到 collider 表面外。

PBD 处理碰撞的方式特别简洁——**碰撞也是一种约束**,在迭代求解阶段被投影:

```rust
pub struct SphereCollisionConstraint {
    pub particle: usize,
    pub sphere_center: Vec3,
    pub sphere_radius: f32,
}

pub fn project_sphere_collision(c: &SphereCollisionConstraint,
                                 particles: &mut [Particle]) {
    let p = particles[c.particle].predicted_position;
    let delta = p - c.sphere_center;
    let dist = delta.length();
    
    // 如果粒子穿进球内,推到球面
    if dist < c.sphere_radius && dist > 1e-9 {
        let n = delta / dist;
        particles[c.particle].predicted_position =
            c.sphere_center + n * c.sphere_radius;
    } else if dist <= 1e-9 {
        // 退化情况:粒子恰在球心,推向任意方向(取 +y)
        particles[c.particle].predicted_position =
            c.sphere_center + Vec3::new(0.0, c.sphere_radius, 0.0);
    }
}
```

每个角色的 collider(Sphere / Capsule / Box)都对应一种 `CollisionConstraint`。每帧 PBD 在迭代阶段不仅跑距离约束,也跑碰撞约束——把穿透的粒子推出来。这种"碰撞也是约束"的统一视角是 PBD 的另一个优点:你不需要单独写 collision response 系统,所有"不许这样"的规则都长一个样。

注意,布料粒子之间的**自碰撞(self-collision)** 是另一个量级的难题——一片 32×32 的布料有 1024 个粒子,两两碰撞检测是 50 万次,而且布料非常薄,容易"穿插"。生产级布料引擎会用空间哈希(spatial hash,详见 [../phase-6/deep-dives/spatial-acceleration.md](../../phase-6/deep-dives/spatial-acceleration.md))加速自碰撞,但代价仍然巨大。许多游戏直接放弃自碰撞,接受布料偶尔穿模以换取性能。

## 3 · 柔体:体积化的 PBD

布料是 2D 网格 + 距离约束。柔体(soft body)是 3D 网格 + 距离约束——本质上是同一个 PBD 框架,只是维度多了一维。

一个柔体例子:挤压的橡胶球。在 PBD 里建模成一个**四面体网格(tetrahedral mesh)**——球的内部填满小四面体,每个四面体的 4 个顶点是一个粒子,每条边是一个距离约束。这样球被压扁时,内部结构会抵抗变形,松手后恢复原状。

```rust
// 一个简化的柔体:球的表面 + 几条内部连接
pub fn build_soft_sphere(center: Vec3, radius: f32, segments: usize)
    -> (Vec<Particle>, Vec<DistanceConstraint>) {
    let mut particles = Vec::new();
    let mut constraints = Vec::new();
    
    // 1. 球面粒子
    for j in 0..segments {
        for i in 0..segments {
            let theta = (i as f32 / segments as f32) * std::f32::consts::TAU;
            let phi   = (j as f32 / segments as f32) * std::f32::consts::PI;
            let p = center + radius * Vec3::new(
                theta.sin() * phi.sin(),
                phi.cos(),
                theta.cos() * phi.sin(),
            );
            particles.push(Particle {
                position: p, predicted_position: p,
                velocity: Vec3::ZERO, inv_mass: 1.0,
            });
        }
    }
    
    // 2. 表面距离约束(球面网格的边)
    let idx = |i: usize, j: usize| j * segments + (i % segments);
    for j in 0..segments {
        for i in 0..segments {
            let p1 = particles[idx(i, j)].position;
            let p2 = particles[idx(i + 1, j)].position;
            let p3 = particles[idx(i, j + 1.min(segments - 1))].position;
            constraints.push(DistanceConstraint {
                a: idx(i, j), b: idx(i + 1, j),
                rest_length: (p1 - p2).length(), stiffness: 1.0,
            });
            if j + 1 < segments {
                constraints.push(DistanceConstraint {
                    a: idx(i, j), b: idx(i, j + 1),
                    rest_length: (p1 - p3).length(), stiffness: 1.0,
                });
            }
        }
    }
    
    // 3. 关键:把表面粒子和球心连起来,抵抗体积压缩
    // 球心粒子(固定不动作为锚点;或者让它也参与模拟)
    let center_idx = particles.len();
    particles.push(Particle {
        position: center, predicted_position: center,
        velocity: Vec3::ZERO, inv_mass: 0.0,  // 锚定
    });
    for i in 0..(segments * segments) {
        let r = (particles[i].position - center).length();
        constraints.push(DistanceConstraint {
            a: i, b: center_idx,
            rest_length: r, stiffness: 0.3,  // 体积约束稍弱
        });
    }
    
    (particles, constraints)
}
```

把球心连到每个表面粒子的约束就是**体积约束的简化形式**——它阻止球被压扁(压扁时表面粒子离球心距离变小,违反约束)。完整的体积约束(对应 Diku 等人 2008 年的论文)会更精确地维护四面体体积,但简化版已经够用。

柔体在游戏里常见的用途是:挤扁的轮胎(车子驶过石头时轮胎变形)、可以被角色压扁的果冻怪、子弹打到墙上留下凹陷。这些都是同一个 PBD 框架,只是粒子和约束的拓扑不同。

## 4 · 流体:粒子(SPH)与网格(Eulerian)两条路

刚体、布料、柔体——它们都是**离散的**对象,由有限个粒子组成。流体不同,流体在物理直觉上是**连续介质**——一杯水不是"10000 个水分子",它是一团连续的物质。这种连续性带来了新的数学挑战,也催生了两大类截然不同的模拟方法:**拉格朗日(Lagrangian)视角**和**欧拉(Eulerian)视角**。

### 4.1 两种视角的根本差别

**拉格朗日视角**(粒子法):跟踪每一个流体"微团"的运动。每个微团是一个粒子,有位置、速度,跟着流体一起移动。SPH(Smoothed Particle Hydrodynamics,光滑粒子流体动力学)是这种视角的代表。

**欧拉视角**(网格法):固定一个空间网格,在每个网格点跟踪"经过这点的流体"的速度、密度、压力。流体在动,但网格不动——你是在"被动观察"流过的物质。 jos stam 1999 年的 Stable Fluids 是这种视角的代表。

打个比方:Lagrangian 像是"坐在河流的一片叶子上,跟着叶子漂",你看到的是叶子身边的局部水流;Eulerian 像是"站在桥上盯着一个固定的水面区域",你看到的是不同时刻流过这片区域的不同水。两者数学上等价(都解 Navier-Stokes 方程),但实现完全不同,适用场景也不同。

### 4.2 SPH:粒子流体

SPH 把流体建模为大量粒子,每个粒子代表一小团流体。核心思想:**每个粒子受到的力来自它的"邻居"粒子**(距离在某个 kernel 半径 h 内的粒子)。

SPH 有三种力:**压力**(让粒子不要挤在一起)、**粘性**(让粒子速度和邻居接近)、**重力**(向下)。压力来自密度——粒子挤在一起密度高,产生向外的推力。

SPH 的标准算法(Monaghan 1992,变形无数):

```rust
// SPH 单步(简化版)
pub fn sph_step(particles: &mut [SphParticle], dt: f32, h: f32) {
    let n = particles.len();
    
    // 1. 算每个粒子的密度
    for i in 0..n {
        let mut density = 0.0;
        for j in 0..n {
            let r = (particles[i].position - particles[j].position).length();
            if r < h {
                density += particles[j].mass * kernel_poly6(r, h);
            }
        }
        particles[i].density = density;
    }
    
    // 2. 算每个粒子的压力(F = -∇p / ρ + μ∇²v + g)
    for i in 0..n {
        let mut force = Vec3::new(0.0, -9.81, 0.0);  // 重力
        for j in 0..n {
            if i == j { continue; }
            let r_vec = particles[i].position - particles[j].position;
            let r = r_vec.length();
            if r < h && r > 1e-9 {
                // 压力力
                let p_i = pressure_from_density(particles[i].density);
                let p_j = pressure_from_density(particles[j].density);
                let p_avg = (p_i + p_j) * 0.5;
                force -= r_vec / r
                       * p_avg / particles[j].density
                       * particles[j].mass
                       * kernel_spiky_gradient(r, h);
                
                // 粘性力
                let v_diff = particles[j].velocity - particles[i].velocity;
                force += v_diff
                       * VISCOSITY / particles[j].density
                       * particles[j].mass
                       * kernel_viscosity_laplacian(r, h);
            }
        }
        particles[i].force = force;
    }
    
    // 3. 积分(半隐式 Euler)
    for p in particles.iter_mut() {
        let accel = p.force / p.density.max(1e-6);
        p.velocity += accel * dt;
        p.position += p.velocity * dt;
    }
}
```

注意这里 SPH **不是 PBD**——它回到了"力-based"的积分流程,因为它没有需要"刚性满足"的约束。流体的"约束"(不可压缩)是软的——水可以被挤压,只是会反弹。所以 SPH 用显式力,用半隐式 Euler 积分。

但有一个问题:**SPH 的"力"非常 stiff**(密度变化时压力急剧上升),所以 SPH 也面对 [numerical-methods.md](numerical-methods.md) 里讲的 stiff 问题。标准 SPH 需要**很小的 dt**(典型 0.001 秒,比游戏帧 dt = 1/60 ≈ 0.017 小 17 倍),意味着 SPH 流体每帧要 substep 10-20 次,非常慢。这就是为什么 3A 游戏里真正的 SPH 流体很少,大多是"看起来像水的简化粒子"。

`kernel` 函数是 SPH 的精髓——它们是带"权重衰减"的样条函数,让远离的粒子贡献小,近处的贡献大。具体形式(Poly6、Spiky gradient、Viscosity Laplacian)是 Müller et al. 2003 年《Particle-Based Fluid Simulation for Interactive Applications》定下来的,沿用至今。

SPH 的优点是**适合飞溅**:水花、瀑布、水从杯子里倒出来——这些场景有大量"分离的水团",Lagrangian 粒子天然能表现。缺点是**不适合大体积静态水**:一汪游泳池用 SPH 要 100 万粒子,每帧 O(N²) 邻居搜索(用空间哈希优化到 O(N),详见 [../phase-6/deep-dives/spatial-acceleration.md](../../phase-6/deep-dives/spatial-acceleration.md)),性能仍然吃紧。

### 4.3 Eulerian 流体:Stable Fluids

Eulerian 视角把空间划分成固定网格,在每个网格点跟踪密度、速度、压力。经典算法由 Jos Stam 在 1999 年 SIGGRAPH 论文《Stable Fluids》提出,核心是 **Navier-Stokes 方程的算子分裂(operator splitting)求解**:

```
1. Advection(对流):把速度场沿自身"流"过去
2. Diffusion(扩散):应用粘性(让速度场变平滑)
3. Force application:加重力等外力
4. Projection(投影):解 Poisson 方程,让速度场无散度(不可压缩)
```

第 4 步最关键——**不可压缩流体**意味着 `∇·v = 0`(速度场的散度为零)。这等价于解一个 Poisson 方程 `∇²p = ρ·∇·v / dt`,需要 Jacobi 迭代或共轭梯度法。这一步是 Eulerian 流体性能瓶颈(典型 50-100 次 Jacobi 迭代)。

Eulerian 流体的优点是**适合大体积稳定水**:游泳池、湖面、烟雾。缺点是**不适合飞溅**:网格固定,飞溅出去的水滴离开网格就丢了。游戏里常用**混合(hybrid)方法**:主体用 Eulerian 网格,飞溅用粒子(Fluid Particles Method)。

完整 Eulerian 流体实现比较复杂(涉及大量数值方法,Poisson 求解器、双线性插值、半拉格朗日对流),Rust 实现一个简化版本大约 300 行。本篇不展开,推荐读 Stam 原论文 + Gusko 的 FluidSim 库(https://github.com/mbrogten/fluidsim-lite)。

### 4.4 选择指南

具体场景怎么选?

- **少量飞溅水花**(打水漂、瀑布、水球):SPH,粒子数 500-5000,可行。
- **大体积静态水**(游泳池、湖面):Eulerian 网格,32×32×32 即可,但 Poisson 求解器要优化。
- **真正大规模流体**(海洋、洪水):**不做物理,做"假流体"**。海洋用 FFT 波浪(Gerstner waves)生成高度场,不用流体物理。这是工业标配——海洋战争游戏里的"水"是着色器算的,不是物理。
- **烟雾**:Eulerian,密度场可视化成烟雾,烟雾上升的对流用 Stam 的 Stable Fluids 直接套。

注意一个重要事实:**3A 游戏里几乎没有真正的流体物理**。绝大多数"水"是着色器假水(Gerstner 波 + 折射 + 反射),只是看起来像水。真正物理流体只在特定场景(打水漂的小水花、被打破的水箱)短暂出现。这是性能预算的必然——完整流体物理 1ms 都跑不动,而假水 0.05ms。

## 5 · 破坏:刚体被切碎的艺术

破坏(destruction / fracture)是另一类"刚体之外"的现象。本质上,破坏是**一个刚体在受力时分裂成多个新刚体**。这看起来像刚体物理能做的事,但难点不在物理,而在**几何**——你怎么决定一面墙被打中后裂成哪些碎片?

### 5.1 预破碎(pre-fractured)

最简单也最常用的方法。美工在 DCC 工具(Maya / Blender / Houdini)里**预先把一面墙切成几十块**,导出时每块是一个独立的 mesh。游戏中墙是一个静态刚体,被打中时:**移除原刚体,生成几十个新的动态刚体**,每个对应一块碎片,各自下落、滚动、最终 sleep。

```rust
// 破碎触发
pub fn fracture_wall(world: &mut World, wall_handle: BodyHandle,
                     hit_point: Vec3, hit_force: Vec3,
                     fragments: &[FragmentMesh]) {
    // 1. 移除原墙体
    world.remove_body(wall_handle);
    
    // 2. 为每个碎片生成一个动态刚体
    for frag in fragments {
        let body = RigidBodyBuilder::dynamic()
            .translation(frag.world_position)
            .build();
        let handle = world.bodies.insert(body);
        let collider = ColliderBuilder::convex_mesh(&frag.vertices).build();
        world.colliders.insert_with_parent(collider, handle, &mut world.bodies);
        
        // 3. 给每个碎片一个初始速度(从击中点向外散开)
        let dir = (frag.world_position - hit_point).normalize();
        world.bodies.get_mut(handle).unwrap()
            .apply_impulse(dir * hit_force.length() * 0.3, true);
    }
}
```

预破碎的优点是**完全可控**——美工决定每块碎片的大小、形状,视觉上一致。缺点是**每次破坏看起来都一样**——同一面墙无论从哪里打,碎成的形状都相同。Half-Life 2 的可破坏墙就是预破碎,打 100 次都是同样的碎片。

### 5.2 Voronoi 破碎

要做出"每次破坏看起来不同"的效果,需要**程序化破碎(procedural fragmentation)**。最经典算法是 **Voronoi shatter**——在墙体内部撒 K 个随机种子点,每个种子点对应一块碎片,碎片是"所有离该种子最近的点"组成的区域。

Voronoi 破碎生成的碎片形状**自然**——多边形,大小不一,边角不规则,非常像真实的石头或玻璃破碎。Houdini 的 Voronoi Fracture 节点是工业标配。

```rust
// 简化:Voronoi 在 3D 中切割凸包
pub fn voronoi_fracture(mesh: &Mesh, seed_count: usize) -> Vec<Mesh> {
    let bbox = mesh.bounding_box();
    let mut seeds = Vec::with_capacity(seed_count);
    for _ in 0..seed_count {
        // 在 bbox 内随机撒种子
        let s = Vec3::new(
            rand::range(bbox.min.x, bbox.max.x),
            rand::range(bbox.min.y, bbox.max.y),
            rand::range(bbox.min.z, bbox.max.z),
        );
        seeds.push(s);
    }
    
    // 对 mesh 的每个面,用每个种子点做"切割平面"剖分
    // (具体实现要参考 Computational Geometry,本节略)
    // 简化:返回 K 个碎片,每个对应一个种子
    seeds.iter().map(|s| clip_mesh_by_voronoi_cell(mesh, s, &seeds)).collect()
}
```

真实实现 Voronoi 切割涉及凸包剖分、平面切割 mesh 等计算几何,代码量不小。Unity 的 `Houdini Engine for Unity` 和 Unreal 的 `Apex Destruction` 都内置 Voronoi 切割。

### 5.3 破坏和游戏性的耦合

破坏不仅仅是视觉——它和**玩法(gameplay)**紧密耦合。一堵可破坏的墙可以成为**新的路径**:玩家打穿墙找到一条新路。一个被破坏的掩体不能再挡子弹——这就改变了战场拓扑。这是为什么破坏在 3A 射击游戏里非常昂贵但价值极高——它**改变了关卡几何**,需要物理、AI 导航、渲染都同步更新。

```rust
// 破坏后,AI 导航网格要重建
world.navigation.rebuild_after(fractured_region);

// 破坏后,渲染要切换到"破碎"版本的 mesh
world.renderer.swap_mesh(wall_handle, &fractured_combined_mesh);
```

这种"破坏触发多个子系统更新"的耦合是破坏系统的工程难点。Unreal Chaos 物理引擎 5.0 专门为破坏设计了 `GeometryCollection` 数据结构,把破坏的几何、物理、渲染状态整合到一个对象里,大幅简化耦合。

### 5.4 破坏的dt稳定性

破坏会突然从 1 个刚体变成 30 个刚体,这 30 个刚体在生成的瞬间可能彼此重叠(碎片是从原始几何切出来的,边界紧贴)。第一帧物理求解时,大量"穿透"导致 Baumgarte 修正项极大,引发剧烈抖动甚至穿透。解决方法:

- 给每个碎片一个**微小的初始偏移**(沿 Voronoi cell 法线方向 0.5mm),避免重叠
- 第一帧启用**额外的 solver iterations**(比如 30 次),让穿透快速消除
- 碎片之间启用 **CCD**(详见 [physics-engine-complete.md](physics-engine-complete.md) §7),防止飞溅时穿透
- 给碎片一个**生命周期**——5 秒后自动消失,避免几百个碎片卡在地上吃 CPU

```rust
// 碎片生命周期管理
pub fn update_fragments(world: &mut World, dt: f32) {
    let mut to_remove = Vec::new();
    for (handle, frag) in &mut world.fragments {
        frag.lifetime -= dt;
        if frag.lifetime < 0.0 {
            to_remove.push(*handle);
        }
    }
    for h in to_remove {
        world.remove_body(h);
    }
}
```

碎片生命周期管理是性能关键。一片战场打完可能产生几百块碎片,如果不清理,每帧物理时间会持续上升。常用对象池(见 [object-pooling-and-game-perf.md](object-pooling-and-game-perf.md))复用刚体槽位,避免反复分配释放。

## 6 · dt 与稳定性:数字地基

讲完所有"算法"之后,我们必须回到一个贯穿 [physics-engine-complete.md](physics-engine-complete.md) 和 [numerical-methods.md](numerical-methods.md) 的主题:**时间步长 dt 决定一切**。

### 6.1 软体/流体比刚体更敏感

刚体物理对 dt 的容忍度尚可——1/60 的 dt 在大多数刚体场景下能稳定跑(详见 [physics-engine-complete.md](physics-engine-complete.md) §15.5 fixed timestep)。但软体和流体物理比刚体**严格得多**:

- **布料**:dt 太大会"穿模"——一个粒子在一帧内移动了"两格"距离,跳过了它本该碰撞的角色。
- **流体 SPH**:dt 太大会**爆炸**——密度计算用当前位置,但位置已经移动了一大步,密度突变,压力突变,粒子瞬间飞出。
- **Eulerian 流体**:dt 太大会**对流不稳定**——半拉格朗日对流需要 CFL 条件(Courant-Friedrichs-Lewy),`dt·v_max < dx`(网格大小),违反这个条件对流会数值振荡。

经验数据:
- 布料 PBD:每帧 substep 4-8 次,dt' = 1/240 到 1/480
- SPH 流体:每帧 substep 10-20 次,dt' = 1/600 到 1/1200
- Eulerian 流体:CFL 数 0.5,根据 `v_max` 自适应 dt

### 6.2 substepping 是标配

这就是为什么所有生产级软体/流体引擎都用 **substepping**(子步进,详见 [../phase-9/09B-1-game-loop-and-timestep.md](../../phase-9/09B-1-game-loop-and-timestep.md))——把一帧分成 K 个 sub-step,每个 sub-step 用 dt/K 跑完整物理。代价是 K 倍 CPU 时间,但稳定性换来了。

```rust
// HH 主循环里的 substep
const SUBSTEPS: usize = 8;
const TARGET_DT: f32 = 1.0 / 60.0;
let sub_dt = TARGET_DT / SUBSTEPS as f32;

for _ in 0..SUBSTEPS {
    // 1. 预测位置
    predict_positions(&mut cloth_particles, sub_dt);
    // 2. 约束迭代
    for _ in 0..SOLVER_ITERATIONS {
        project_all_constraints(&mut cloth_particles, &constraints);
        handle_collisions(&mut cloth_particles, &character);
    }
    // 3. 更新速度和位置
    update_velocities(&mut cloth_particles, sub_dt);
}
```

注意 substepping 让 PBD 的"等效刚度"也提升——每个 sub-step 都跑一次约束迭代,等于把迭代次数翻倍。这就是为什么 PBD 在小 dt 下表现尤其好:**它同时利用了"小 dt 更稳定"和"多迭代更刚性"两个因素**。

### 6.3 PBD 的稳定性优势

回到本篇开头那个"为什么布料用 PBD"的问题。除了绕开 stiff 问题,PBD 还有一个稳定性优势:**PBD 对 dt 的容忍度比力-based 方法高得多**。

力-based 方法在 stiff 系统下 dt 必须 < `2 / sqrt(stiffness / mass)`,stiffness 大时 dt 必须极小。PBD 没有 stiffness 的"显式表示",它的 `k` 参数是 0-1,无所谓多大,迭代位置永远是有限的。即使 dt 大,PBD 最多是"约束没完全满足"(布料看起来有点软),不会爆炸。

这就是为什么 PBD 是软体/布料物理的事实标准——它把"稳定性 vs stiffness"的死结解开了。在 dt 不能无限小的实时游戏场景下,PBD 是已知最好的折衷。

## 7 · 生产现实:这些都是奢侈品

讲完所有理论,我们必须面对工业现实:**完整的布料 + 流体 + 破坏,是电影级工作量,3A 游戏负担不起全部**。

具体说,以下是 3A 游戏的"软体预算":

- **布料**:只给主角和重要 NPC 加物理布料。路人 NPC 的衣服是 baked animation 或 vertex shader 假布料(骨骼驱动的简单晃动)。
- **流体**:绝大多数"水"是 shader 假水(FFT 波浪 + 折射),不做物理。物理流体只用于"水花飞溅"等小范围短暂场景,粒子数控制在 500 以内。
- **破坏**:破坏是**触发式**的——只有特定剧情点的特定墙可破坏,不是所有墙都可破坏。 Battlefield 系列的"Levolution" 大型破坏都是脚本化的,不是真实物理。
- **柔体**:几乎不做。少数游戏(Overwatch 的某些角色)有柔体道具,但都是简化版。

这些奢侈品需要 **GPU compute 加速**(详见 [../phase-6/deep-dives/gpu-compute-fundamentals.md](../../phase-6/deep-dives/gpu-compute-fundamentals.md))。布料物理从 CPU 移到 GPU compute,可以跑 10000 粒子的布料(主角全身衣物都是物理布料);SPH 流体在 GPU 上可以跑 10 万粒子;破坏在 GPU 上可以实时做 Voronoi 切割。NVIDIA FleX 是这一思路的代表作——所有 PBD 物理统一在 GPU 上跑。

**Middleware 是常规选择**。绝大多数游戏不自己写布料/流体引擎,而是用现成 middleware:
- **NVIDIA PhysX Cloth**:CPU/GPU 布料,Unity 和 Unreal 集成
- **NVIDIA FleX / Flow**:GPU 加速的 PBD 物理(布料、流体、柔体统一)
- **Houdini Engine**:破坏预处理(Voronoi 切割)
- **Marvelous Designer**:布料离线模拟(电影和过场动画用)

## 8 · 在你 HH 项目里动手(做中学红线)

理论听够了,现在动手。**目标:在你 HH 项目里写 200 行 Rust,实现一个最小可跑的 PBD 布料,挂在角色身上,在重力下自然垂下,撞到球(角色)会被推开**。

这是你写的第一个软体物理模拟,PBD 求解器之后可以直接扩展到柔体,反过来也能改善刚体物理的稳定性。

### 8.1 项目结构

```bash
cd /home/sun/src/handmade-hero-guide
cargo new --bin hh-cloth --name hh_cloth
cd hh-cloth
```

`Cargo.toml`:

```toml
[package]
name = "hh_cloth"
version = "0.1.0"
edition = "2021"

[dependencies]
# 纯标准库实现,不需要外部依赖
# 如果想用 nalgebra 做向量,加上:
# nalgebra = "0.33"

[profile.release]
opt-level = 3
debug = true  # 用 perf 分析
```

### 8.2 Vec3 与 Particle

我们手写一个最小 `Vec3`(避免引依赖,如果你想用 nalgebra 替换也行):

```rust
// src/main.rs
#[derive(Copy, Clone, Debug, Default)]
pub struct Vec3 {
    pub x: f32,
    pub y: f32,
    pub z: f32,
}

impl Vec3 {
    pub const ZERO: Self = Self { x: 0.0, y: 0.0, z: 0.0 };
    pub fn new(x: f32, y: f32, z: f32) -> Self { Self { x, y, z } }
    
    pub fn dot(self, o: Self) -> f32 {
        self.x * o.x + self.y * o.y + self.z * o.z
    }
    
    pub fn cross(self, o: Self) -> Self {
        Self::new(
            self.y * o.z - self.z * o.y,
            self.z * o.x - self.x * o.z,
            self.x * o.y - self.y * o.x,
        )
    }
    
    pub fn length(self) -> f32 { self.dot(self).sqrt() }
    
    pub fn normalize(self) -> Self {
        let len = self.length();
        if len > 1e-10 { Self::new(self.x / len, self.y / len, self.z / len) }
        else { Self::ZERO }
    }
    
    pub fn normalize_or_zero(self) -> Self { self.normalize() }
}

impl std::ops::Add for Vec3 {
    type Output = Self;
    fn add(self, o: Self) -> Self { Self::new(self.x + o.x, self.y + o.y, self.z + o.z) }
}
impl std::ops::Sub for Vec3 {
    type Output = Self;
    fn sub(self, o: Self) -> Self { Self::new(self.x - o.x, self.y - o.y, self.z - o.z) }
}
impl std::ops::Mul<f32> for Vec3 {
    type Output = Self;
    fn mul(self, s: f32) -> Self { Self::new(self.x * s, self.y * s, self.z * s) }
}
impl std::ops::AddAssign for Vec3 {
    fn add_assign(&mut self, o: Self) { self.x += o.x; self.y += o.y; self.z += o.z; }
}

#[derive(Copy, Clone, Debug)]
pub struct Particle {
    pub position: Vec3,
    pub predicted_position: Vec3,
    pub velocity: Vec3,
    pub inv_mass: f32,  // 0 表示钉死
}
```

### 8.3 约束

```rust
#[derive(Copy, Clone, Debug)]
pub struct DistanceConstraint {
    pub a: usize,
    pub b: usize,
    pub rest_length: f32,
    pub stiffness: f32,  // 0.0 ~ 1.0
}

#[derive(Copy, Clone, Debug)]
pub struct SphereCollider {
    pub center: Vec3,
    pub radius: f32,
}

pub fn project_distance(c: &DistanceConstraint, particles: &mut [Particle]) {
    let pa = particles[c.a].predicted_position;
    let pb = particles[c.b].predicted_position;
    let delta = pa - pb;
    let dist = delta.length();
    if dist < 1e-9 { return; }
    
    let n = delta * (1.0 / dist);
    let c_err = dist - c.rest_length;
    let wa = particles[c.a].inv_mass;
    let wb = particles[c.b].inv_mass;
    let w_sum = wa + wb;
    if w_sum <= 0.0 { return; }
    
    let k = c.stiffness;
    particles[c.a].predicted_position += n * (-k * wa / w_sum * c_err);
    particles[c.b].predicted_position += n * ( k * wb / w_sum * c_err);
}

pub fn project_sphere_collisions(particles: &mut [Particle], colliders: &[SphereCollider]) {
    for p in particles.iter_mut() {
        if p.inv_mass == 0.0 { continue; }
        for c in colliders {
            let d = p.predicted_position - c.center;
            let dist = d.length();
            if dist < c.radius {
                if dist > 1e-9 {
                    let n = d * (1.0 / dist);
                    p.predicted_position = c.center + n * c.radius;
                } else {
                    // 退化:粒子在球心,推向 +y
                    p.predicted_position = c.center + Vec3::new(0.0, c.radius, 0.0);
                }
            }
        }
    }
}
```

### 8.4 PBD 主循环

```rust
pub struct ClothSim {
    pub particles: Vec<Particle>,
    pub constraints: Vec<DistanceConstraint>,
    pub colliders: Vec<SphereCollider>,
    pub iterations: usize,
    pub substeps: usize,
    pub gravity: Vec3,
    pub wind: Vec3,
}

impl ClothSim {
    pub fn step(&mut self, dt: f32) {
        let sub_dt = dt / self.substeps as f32;
        
        for _ in 0..self.substeps {
            // 1. 预测位置(用外力 + 现速度)
            for p in self.particles.iter_mut() {
                if p.inv_mass == 0.0 { continue; }
                let accel = self.gravity + self.wind * p.inv_mass.recip();
                p.velocity += accel * sub_dt;
                p.predicted_position = p.position + p.velocity * sub_dt;
            }
            
            // 2. 约束迭代
            for _ in 0..self.iterations {
                for c in &self.constraints {
                    project_distance(c, &mut self.particles);
                }
                project_sphere_collisions(&mut self.particles, &self.colliders);
            }
            
            // 3. 反推速度,提交位置
            for p in self.particles.iter_mut() {
                if p.inv_mass == 0.0 { continue; }
                p.velocity = (p.predicted_position - p.position) * (1.0 / sub_dt);
                // 加点阻尼避免数值振荡(0.99 表示每帧损失 1%)
                p.velocity = p.velocity * 0.99;
                p.position = p.predicted_position;
            }
        }
    }
}
```

注意第 3 步那个 `* 0.99` 是**数值阻尼**——PBD 在迭代中可能引入微小的高频振荡(位置在每个 sub-step 间反复跳动),阻尼让这些振荡快速衰减。阻尼太大会让布料"沉重",太小会"抽搐",0.99 是经验值。

### 8.5 装配一面布料

```rust
fn main() {
    let cols = 12;
    let rows = 12;
    let spacing = 0.1;  // 10cm
    let origin = Vec3::new(-0.55, 1.5, 0.0);  // 挂在 1.5m 高
    
    let (mut particles, mut constraints) = build_cloth_grid(cols, rows, spacing, origin);
    
    // 把布料顶部两角钉死(晾衣绳挂法)
    let idx = |i: usize, j: usize| j * cols + i;
    particles[idx(0, 0)].inv_mass = 0.0;
    particles[idx(cols - 1, 0)].inv_mass = 0.0;
    // 中间也钉一个,让布料形成"屋顶"形状
    particles[idx(cols / 2, 0)].inv_mass = 0.0;
    
    // 加一个球作为障碍物(角色)
    let colliders = vec![
        SphereCollider { center: Vec3::new(0.0, 0.8, 0.0), radius: 0.3 },
    ];
    
    let mut sim = ClothSim {
        particles, constraints, colliders,
        iterations: 16,
        substeps: 4,
        gravity: Vec3::new(0.0, -9.81, 0.0),
        wind: Vec3::new(0.5, 0.0, 0.2),  // 微风
    };
    
    // 跑 300 帧(5 秒)
    let dt = 1.0 / 60.0;
    for frame in 0..300 {
        sim.step(dt);
        
        // 输出布料中心粒子的位置,看是否稳定收敛
        let center = &sim.particles[idx(cols / 2, rows / 2)];
        println!("frame {}: center at ({:.3}, {:.3}, {:.3}), vel.y = {:.3}",
                 frame, center.position.x, center.position.y, center.position.z,
                 center.velocity.y);
    }
}
```

`build_cloth_grid` 函数在 §2.1 已经给出。粘进项目跑,你应该看到:

- **正确行为**:布料从初始水平位置开始,因为重力下垂,中心向下垂落。前 30 帧布料形状剧烈变化(从平到弧),后 270 帧在重力 + 风 + 阻尼下稳定下来,中心粒子的 y 坐标在某个值附近做小幅振荡(±2mm)。布料和球碰撞,在球的上方滑过去,不会被球穿透。
- **典型 bug**:
  - **布料抖动成团**:iterations 不够,加 substep 或 iterations。
  - **布料"穿过"球**:每个 substep 粒子移动太多,把 substep 加到 8。
  - **布料缩成一团**:`stiffness` 太低或约束拓扑错误,检查 build_cloth_grid 的连接。
  - **布料瞬间飞出**:某个粒子的 `predicted_position` 变成 NaN,检查 `project_distance` 里 `dist < 1e-9` 的兜底。

### 8.6 验证 PBD 的稳定性

把 `gravity` 从 -9.81 改成 -98.1(10 倍重力),`wind` 从 0.5 改成 50.0(暴风),布料会变形更剧烈,但**不会爆炸**——位置永远是有限的。这就是 PBD 无条件稳定的体现。如果换成力-based 方法,这种参数 1 帧就 NaN。

把 `substeps` 从 4 改成 1(不 substep),再跑——布料会"抖动"得更明显(约束没完全收敛),但仍然不会爆炸。把 `substeps` 改回 4,再把 `iterations` 从 16 改成 4——布料看起来更"软"(每帧只迭代 4 次,等效刚度低),但仍稳定。

这种**"参数变化只影响视觉,不影响稳定性"**的性质,就是 PBD 在游戏工业占统治地位的根本原因。Casey 在 HH 里如果做到布料物理,PBD 是不二选择——他能控制参数让"看起来对",不用操心数值爆炸。

### 8.7 把布料挂到角色上

现在把这面布料挂到你 HH 项目的角色身上。每个 substep 开始前,把钉死粒子的 `position` 同步到角色肩膀的世界坐标:

```rust
// 在 HH game_update 里
let left_shoulder  = character_bone_world_position("shoulder.l");
let right_shoulder = character_bone_world_position("shoulder.r");

// 更新钉死粒子的位置(让布料跟着角色走)
sim.particles[idx(0, 0)].position = left_shoulder;
sim.particles[idx(cols - 1, 0)].position = right_shoulder;
sim.particles[idx(0, 0)].predicted_position = left_shoulder;
sim.particles[idx(cols - 1, 0)].predicted_position = right_shoulder;

// 把角色的 collider 加进 sim.colliders
sim.colliders.clear();
for body_part in character.colliders() {
    sim.colliders.push(SphereCollider {
        center: body_part.world_position,
        radius: body_part.radius,
    });
}

sim.step(frame_dt);

// 把布料的 mesh 顶点同步到 particle.position(渲染)
for (i, vertex) in cloth_render_mesh.vertices_mut().enumerate() {
    vertex.position = sim.particles[i].position;
}
```

跑起来,你就有了 HH 项目里的第一个软体物理披风。角色走动,披风跟着飘;角色跳跃落地,披风"嗖"地往上扬;角色撞墙,披风被夹在中间挤一下。这一切都来自你亲手写的 200 行 PBD 代码。

### 8.8 性能与扩展

这个 12×12 的布料有 144 个粒子、约 600 个约束,每帧 4 substep × 16 iteration = 64 次约束迭代,总共 ~38000 次约束投影。Rust 在 release 模式下 ~0.3ms / 帧,完全在 60 FPS 预算内。

扩展方向:
- **更大的布料**:32×32 = 1024 粒子,~3ms / 帧,仍可接受。要上 64×64(4096 粒子)就需要 SIMD 或 GPU compute 了。
- **自碰撞**:加上 spatial hash 加速粒子间碰撞(见 [../phase-6/deep-dives/spatial-acceleration.md](../../phase-6/deep-dives/spatial-acceleration.md))。
- **更真实的弯曲**:把"二跳距离约束"换成 Müller 2006 论文的 dihedral angle 约束(角度约束,而不是距离),布料折叠更自然。
- **流体扩展**:用 SPH 框架替换 ClothSim,粒子结构相似,加密度计算和压力力。

这个 PBD 框架是统一的——你换了粒子拓扑和约束类型,就能做出布料、柔体、绳索、甚至流体(用 PBD 解不可压缩约束,即 PCISPH/Position-Based Fluids,Macklin & Müller 2013)。PBD 是一个真正"用一套算法统一软体物理"的范式。

## 9 · 练习

### Lv1 · 概念辨析

**题**:解释下面三组术语的差别。

1. PBD(位置基础动力学)vs Sequential Impulse(顺序冲量求解)
2. SPH(Lagrangian 粒子流体)vs Eulerian(网格流体)
3. 预破碎 vs Voronoi 破碎

**参考要点**:

1. **PBD vs SI**:SI 在速度层面工作,通过修改速度满足约束,适合刚度有限的刚体;PBD 在位置层面工作,直接投影位置,适合 stiffness 极高的布料。PBD 无条件稳定,SI 在 stiff 系统下会爆炸。PBD 的"stiffness"是 0-1 的迭代比例参数,不是真实物理刚度。
2. **SPH vs Eulerian**:SPH 跟着流体一起移动(Lagrangian),适合飞溅和水花;Eulerian 固定网格,适合大体积稳定流体。SPH 算粒子间力,Eulerian 解 Navier-Stokes 算子分裂。SPH 不需要解 Poisson 方程,Eulerian 需要(投影步)。
3. **预破碎 vs Voronoi**:预破碎是美工在 DCC 工具里手动切,完全可控但每次破坏看起来都一样;Voronoi 是程序化随机种子切割,每次破坏看起来不同但形状不规则。

### Lv2 · 动手验证

**题**:用本篇的 hh_cloth 代码跑 12×12 布料,记录 300 帧的中心粒子 y 坐标。回答:

1. 布料最终(300 帧)的中心 y 是多少?它是否在做小幅振荡?
2. 把 `stiffness` 全部从 1.0/0.5/0.1 改成 0.3/0.2/0.05(更软),中心 y 会怎么变?
3. 把 `iterations` 从 16 改成 64,中心 y 振荡幅度变小还是变大?为什么?

**完成标准**:输出 CSV 文件,Python/Excel 画图,3 组参数对比。

### Lv3 · 迁移设计

**题**:你的 HH 角色有一件披风(用本篇 PBD 实现)。玩家报告 bug:角色高速跑动时,披风"穿进"角色后背。

**思考**:
1. 你怎么定位这个 bug?(提示:在每个 substep 加日志,看粒子位置和角色 collider 的距离)
2. 可能的根本原因有哪些?(提示:substep 数、iterations、collider 形状、预测位置步长)
3. 你的修复方案是什么?

**提示**:
- 跑动速度大,意味着每帧位置变化大,substep 数要增加
- 披风粒子在每个 substep 移动的距离必须小于 collider 半径,否则会穿透
- iterations 数会影响碰撞约束的执行次数,但要小心"碰撞 vs 距离约束"互相干扰

### Lv4 · 扩展实现

**题**:把本篇的 PBD 布料改成**绳索**——一条由 N 个粒子连成的链,一端钉死,另一端挂一个重物(用一个 inv_mass 很大的粒子)。

1. 写 `build_rope(length: f32, segments: usize)`,返回粒子链和距离约束
2. 重物用 `inv_mass = 0.1`(很重),其他粒子 `inv_mass = 1.0`
3. 跑起来,绳索应该被重物拉直,做钟摆运动
4. 加一个 SphereCollider 让绳索绕过球摆动

**完成标准**:Rust 代码 + 跑起来的输出 + 用 Python 画重物位置随时间的轨迹(应该是阻尼振荡)。

## 10 · 延伸阅读

本仓库内部资料:

- [physics-engine-complete.md](physics-engine-complete.md) — Phase 4 刚体物理引擎完整推导,本篇的预备
- [numerical-methods.md](numerical-methods.md) — Phase 4 ODE 求解器七种兵器,理解 PBD 的稳定性基础
- [../phase-3/deep-dives/particle-systems-cpu.md](../../phase-3/deep-dives/particle-systems-cpu.md) — Phase 3 CPU 粒子系统,SPH 的预备
- [../phase-6/deep-dives/spatial-acceleration.md](../../phase-6/deep-dives/spatial-acceleration.md) — Phase 6 空间加速结构,SPH 邻居搜索和布料自碰撞用
- [../phase-6/deep-dives/gpu-compute-fundamentals.md](../../phase-6/deep-dives/gpu-compute-fundamentals.md) — Phase 6 GPU compute,大规模 PBD / SPH 的实现平台
- [../phase-9/09B-1-game-loop-and-timestep.md](../../phase-9/09B-1-game-loop-and-timestep.md) — Phase 9 时间步与 substep,软体/流体对 dt 的容忍度
- [object-pooling-and-game-perf.md](object-pooling-and-game-perf.md) — Phase 4 对象池,碎片生命周期管理用

外部稳定 URL:

- **Matthias Müller et al., "Position Based Dynamics" (2006)** — PBD 奠基论文,所有现代布料/柔体物理的源头。免费 PDF:https://matthias-research.github.io/pages/publications/posBasedDyn.pdf
- **Müller et al., "Particle-Based Fluid Simulation for Interactive Applications" (2003)** — SPH 流体经典论文。PDF:https://matthias-research.github.io/pages/publications/sca03.pdf
- **Jos Stam, "Stable Fluids" (1999)** — Eulerian 流体革命性论文,所有游戏流体仿真基础。PDF:https://d2f99xq7viti1u.cloudfront.net/legacy/stable_fluids.pdf
- **Macklin & Müller, "Position Based Fluids" (2013)** — 把 PBD 思路扩展到流体,统一了 PBD 框架。PDF:https://mmacklin.com/pbf_sig_preprint.pdf
- **Müller et al., "Detailed Rigid Body Simulation with Split Impulse" (2008)** — PBD 和刚体物理的融合
- **Ten Minute Physics (Matthias Müller) YouTube 频道**:https://www.youtube.com/@TenMinutePhysics — NVIDIA Research 大神,10 分钟讲一个软体/流体主题,代码全部开源
- **NVIDIA FleX 文档**:https://developer.nvidia.com/flex — GPU 加速的 PBD 统一物理库
- **Jos Stam《The Art of Fluid Animation》**(2015)— 流体动画圣经,从 Stable Fluids 一路讲到现代
- **Box2D作者 Erin Catto, "Soft Constraints" (GDC 2011)** — soft constraint 推导,理解力-based 软约束为什么不如 PBD:PDF 见 https://box2d.org/publications/

真实开源源码:

- **PhysX Cloth(NVIDIA)**:https://github.com/NVIDIA-Omniverse/PhysX — 看 `Cloth` 类,工业级 PBD 布料实现
- **NVIDIA FleX**:https://github.com/NVIDIAGameWorks/FleX — GPU PBD 统一物理
- **BParted / bevy_xpbd(Rust)**:https://github.com/Jondolf/bevy_xpbd — Rust 的 PBD 实现,Bevy 集成
- **fluid-engine-dev(LBM)**:https://github.com/doyubkim/fluid-engine-dev — 完整的 Eulerian 流体参考实现,C++
- **Stable Fluids Web Demo**:https://github.com/sevengers/Pbf3d — PBD 流体 demo
- **pbd-rs(Rust PBD 实验库)**:https://github.com/whorr/phenom-compute — 可作 Rust 学习参考

这一篇到这里。下次你看到 Casey 在 HH 视频里说"我们能不能给角色加一件披风",你知道他即将踩进一个完全不同于刚体的世界——stiff 系统的数值爆炸,力-based 方法的死结,PBD 这把"位置投影"的钥匙。你不再会用刚体物理强行逼近布料,而是会从 PBD 主循环开始,200 行代码写出一面会飘的布。这就是刚体之外的世界——更难,但更美。
