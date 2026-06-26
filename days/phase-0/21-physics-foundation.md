---
article: 21
phase: 0
title: "物理基础:牛顿力学 / 碰撞 / 转动 / 振动 / 数值积分稳定性"
type: concept
difficulty: 4
duration: "5-6h"
domains: [physics, game, rust, math]
prereqs: ["20-math-foundation-extended"]
---

# 21 · 物理基础:从牛顿定律到稳定积分器

> 你的角色站在地上,你按下空格让他跳。代码看起来对:`velocity.y = 5.0`。你跑游戏——角色**直接瞬移到天上**,根本没有跳跃弧线。或者你做弹簧,代码 `acceleration = -k * x`,跑起来——弹簧**越弹越大,最后把整个屏幕炸了**。或者你做球落地反弹,代码 `velocity.y = -velocity.y`,跑起来——球**每弹一次变高一点**,几秒后球飞出宇宙。这些 bug 不是代码写错,是**物理不对**。这一篇讲完,你能 debug 上面所有问题,因为你会理解每个公式背后的物理。

## 0 · 为什么要有这一天

让我把镜头拉到一个具体场景。

你跟着 Casey 走到 Day 90,你做了第一个会跳的角色。代码:

```rust
fn update_player(player: &mut Player, dt: f32) {
    if player.is_jumping {
        player.velocity.y = 5.0;
        player.is_jumping = false;
    }
    player.velocity.y -= 9.8 * dt;
    player.position.y += player.velocity.y * dt;
}
```

你跑游戏,按下空格,角色飞起来。但**弧线怪怪的**——角色上升 0.3 秒就到顶点,然后下落 0.3 秒回到地面。理论上抛体运动顶点应该高很多,弧线应该圆润。你查代码,没问题。

**真正的问题**:`player.velocity.y = 5.0` 这行设的是"初速度"。但你的角色"体重"是多少?"5"的单位是 m/s 还是 km/h?你的 `dt` 是秒还是毫秒?9.8 是重力加速度,但你的游戏世界坐标是"米"还是"像素"?

**你以为你在写物理,其实你在写"无量纲数"**。所有数字关系混乱,导致角色像气球一样飘。

这是游戏物理的第一个陷阱:**单位**。

第二个陷阱:**积分器稳定性**。你做弹簧:

```rust
acceleration = -k * x;
velocity += acceleration * dt;
position += velocity * dt;
```

k = 100,dt = 0.016(60 FPS)。你跑——弹簧**疯狂振动**,振幅每秒翻倍,五秒后整个屏幕漂白。你减少 k 到 10——稍微好点,但还是发散。你减小 dt 到 0.001——稳了,但游戏慢得不能玩。

这是**显式 Euler 不稳定**。它对"刚性"系统(高频振动)数值发散。修复方法是 Verlet 或隐式 Euler——但你需要理解**为什么**。

第三个陷阱:**碰撞响应**。你的球落地:

```rust
if position.y < ground {
    velocity.y = -velocity.y;
}
```

跑游戏——球**每次反弹更高**。几秒后球出屏。原因:浮点误差累积 + 你没有处理"球已经穿过地面"的情况——下一帧它还在地面下,velocity 又被翻转,变成向下,球穿地。

修复方法:**冲量法 + 位置修正**——但你需要懂**动量守恒**。

**这一篇覆盖**:
- 牛顿三定律(数学 + 直觉 + 代码)
- 动量能量守恒 / 弹性非弹性碰撞
- 力矩 / 转动惯量 / 角动量
- 简谐振动 / 阻尼 / 受迫 / 共振
- 摩擦(静/动) / 空气阻力 / 流体阻力
- 数值积分稳定性(Euler 失败 / Verlet 稳定 / RK4 精确)
- SI 单位 vs 游戏单位(米/像素/秒/帧)

**每一节**:物理推导 → Rust 代码 → 直觉解释 → 三个例子 → 游戏应用。

**心理锚点**:这一篇读完,你能:
- 解释为什么 `F = ma` 不是定义而是定律
- 计算两个球的弹性碰撞后速度
- 知道为什么自行车不倒(角动量守恒)
- 解释为什么显式 Euler 让弹簧爆炸
- 写一个稳定的 Verlet 积分器
- 解释为什么 SI 单位(米/秒/千克)比"游戏单位"(像素/帧)可靠

## 1 · 概念地图:游戏物理的 7 大块

| 块 | 核心问题 | 关键公式 |
|---|---|---|
| **牛顿力学** | 力如何改变运动 | F = ma |
| **动量能量** | 碰撞中什么守恒 | p = mv, E = (1/2)mv² |
| **转动** | 旋转的力学 | τ = Iα |
| **振动** | 弹簧 / 摆 / 共振 | F = -kx |
| **阻力** | 摩擦 / 流体 | F = -bv 或 F = μN |
| **积分器** | 时间演化算法 | Euler / Verlet / RK4 |
| **单位** | 度量约定 | SI vs 游戏单位 |

---

## 2 · 心智模型

### 2.1 类比:物理是"自然界的规则"

数学告诉你"如果世界这样运作,会有什么后果"。物理告诉你"世界实际怎么运作"。

牛顿三定律不是数学定理,是**经验定律**——牛顿观察世界,总结出三条规则。这两条事实让物理和数学有本质区别:

1. **物理是近似**。`F = ma` 在低速(远低于光速)、宏观(远大于原子)下精确。但接近光速要相对论,原子尺度要量子力学。
2. **物理有量纲**。`5` 没意义,`5 米/秒` 有意义。所有物理公式都必须**量纲一致**——左右两边单位相同。

**游戏开发里"物理引擎"的含义**:模拟一套**类似现实但简化**的规则,让游戏物体看起来"自然"。游戏物理可以违反现实(子弹时间、低重力、双重跳跃),但**它内部必须自洽**——一旦规则不自洽,玩家立刻察觉"假"。

### 2.2 第一原理:质量、力、加速度

物理的"原子"是三个量:

- **质量(m)**:物体"抗拒运动改变"的程度。单位 kg。
- **位置(x)**:物体在哪。单位 m。
- **时间(t)**:演化参数。单位 s。

其他量从这三个派生:
- **速度(v)** = dx/dt,单位 m/s
- **加速度(a)** = dv/dt,单位 m/s²
- **力(F)** = ma,单位 N = kg·m/s²
- **动量(p)** = mv,单位 kg·m/s
- **能量(E)** = (1/2) m v² + m g h + ...,单位 J = kg·m²/s²

**关键洞察**:**单位是物理的"类型系统"**。就像 Rust 不让你把 `String` 加 `i32`,物理不让你把"米"加"秒"。所有正确公式量纲一致——这是最简单的物理 sanity check。

---

## 3 · 牛顿三定律

### 3.1 第一定律(惯性定律)

**陈述**:不受外力的物体保持静止或匀速直线运动。

**数学**:`F = 0 ⟹ v = const`。

**直觉**:物体"不愿意改变运动状态"。这个"不愿意"的程度 = 质量。重物难推动(改变 v 从 0),也难停住(改变 v 从大)。

**反直觉点**:日常生活中"不受力的物体停下来"是因为**摩擦力**。在无摩擦的太空,飞船一旦加速到某速度,关引擎后**永远以该速度飞**。

**游戏应用**:太空模拟游戏(Elite Dangerous、Star Citizen)正确实现这点——飞船没有"自动减速"。地球上的游戏(马里奥)违反这定律——角色不按键就停,因为有"虚拟摩擦"。这种"违反物理"是游戏设计选择,不是 bug。

**Rust 代码例子**:无摩擦世界。

```rust
struct Body {
    pos: [f32; 2],
    vel: [f32; 2],
}

fn update_no_force(body: &mut Body, dt: f32) {
    // 第一定律:无外力,匀速直线运动
    body.pos[0] += body.vel[0] * dt;
    body.pos[1] += body.vel[1] * dt;
}

fn main() {
    let mut b = Body { pos: [0.0, 0.0], vel: [3.0, 4.0] };
    for i in 0..5 {
        update_no_force(&mut b, 1.0);
        println!("t={}  pos={:?}", i + 1, b.pos);
    }
    // 输出:t=1 pos=[3,4], t=2 pos=[6,8], ... 匀速
}
```

### 3.2 第二定律(F = ma)

**陈述**:物体的加速度等于作用力除以质量。

**数学**:`F = ma` 或等价 `a = F/m`。

**直觉**:同样的力,作用在轻物体上得到大加速度,作用在重物体上得到小加速度。卡车和小轿车踩同样油门,小轿车加速快。

**这是定律不是定义**:`F = ma` 不是"力的定义",是**经验关系**。力的定义来自"弹簧测力计读数"。ma 是被测出来的,不是定义出来的。

**向量形式**:力是向量,加速度同方向。`F⃗ = m a⃗`。

**多个力合成**:合力 = 所有力的向量和。`F_total = F₁ + F₂ + ...`,然后 `a = F_total / m`。

**例子 1**:5 kg 物体受 10 N 力,加速度 `a = F/m = 10/5 = 2 m/s²`。

**例子 2**:5 kg 物体受重力(向下 49 N)和支持力(向上 49 N),合力 0,加速度 0,物体静止在地面。

**例子 3**:自由落体,只受重力 `F = mg`,所以 `a = F/m = g = 9.8 m/s²`(与质量无关!)——这就是伽利略"比萨斜塔实验"的物理。

**游戏应用**:这是物理引擎的核心方程。每帧:
1. 算合力(重力 + 弹簧 + 摩擦 + 用户输入 + ...)
2. 算加速度 `a = F/m`
3. 更新速度 `v += a dt`
4. 更新位置 `x += v dt`

```rust
struct Body {
    mass: f32,
    pos: [f32; 2],
    vel: [f32; 2],
}

fn update_with_force(body: &mut Body, force: [f32; 2], dt: f32) {
    // F = ma  →  a = F/m
    let acc = [force[0] / body.mass, force[1] / body.mass];
    body.vel[0] += acc[0] * dt;
    body.vel[1] += acc[1] * dt;
    body.pos[0] += body.vel[0] * dt;
    body.pos[1] += body.vel[1] * dt;
}

fn main() {
    // 5 kg 物体受 (10, 0) N 力,5 秒
    let mut b = Body {
        mass: 5.0,
        pos: [0.0, 0.0],
        vel: [0.0, 0.0],
    };
    for _ in 0..5 {
        update_with_force(&mut b, [10.0, 0.0], 1.0);
        println!("pos={:?}  vel={:?}", b.pos, b.vel);
    }
    // 5 秒后:vel = [10, 0],pos = [30, 0]
    // 因为 a = 2 m/s²,5 秒后 v = 10 m/s,位移 = (1/2)·2·25 = 25
    // 但 Euler 积分只近似,v 5秒=10, x 累加 = 2+4+6+8+10 = 30(误差)
}
```

### 3.3 第三定律(作用与反作用)

**陈述**:每个作用力都有大小相等、方向相反的反作用力。

**数学**:`F_AB = -F_BA`(A 对 B 的力 = 负的 B 对 A 的力)。

**直觉**:你推墙,墙推你。墙没动是因为它连着地(地球)。火箭就是第三定律——喷气向后,火箭向前。

**反直觉点**:第三定律**两力作用在不同物体上**。马对车的力作用在车上,车对马的力作用在马上。它们**不能抵消**(因为作用对象不同)。

**例子 1**:你 70 kg,地球推你向上 686 N(支撑力),你推地球向下 686 N。地球质量太大,几乎不动;你也不动(因为合力 = 0)。

**例子 2**:枪发射子弹,子弹向前 100 g × 500 m/s = 50 kg·m/s 动量。枪向后 50 kg·m/s 动量。如果枪 1 kg,枪速度 = 50/1 = 50 m/s 后退。

**游戏应用**:碰撞响应。两个物体碰撞时,冲量 J 作用在 A 上,−J 作用在 B 上,保证动量守恒(等价于第三定律的瞬时版本)。

```rust
// 两球碰撞,弹性碰撞(动能守恒)
fn elastic_collision_1d(
    m1: f32, v1: &mut f32,
    m2: f32, v2: &mut f32,
) {
    // 公式来自动量 + 动能守恒推导
    let v1_new = ((m1 - m2) * *v1 + 2.0 * m2 * *v2) / (m1 + m2);
    let v2_new = ((m2 - m1) * *v2 + 2.0 * m1 * *v1) / (m1 + m2);
    *v1 = v1_new;
    *v2 = v2_new;
}

fn main() {
    let mut v1 = 5.0_f32;  // 1 号球 5 m/s 向右
    let mut v2 = 0.0_f32;  // 2 号球静止
    elastic_collision_1d(1.0, &mut v1, 1.0, &mut v2);
    println!("碰撞后: v1={}, v2={}", v1, v2);
    // 输出: v1=0, v2=5
    // 等质量弹性碰撞:速度交换

    // 重碰轻:保龄球撞乒乓球
    let mut v1 = 5.0_f32;
    let mut v2 = 0.0_f32;
    elastic_collision_1d(5.0, &mut v1, 0.1, &mut v2);
    println!("保龄球 v1={}, 乒乓球 v2={}", v1, v2);
    // 输出: v1 ≈ 4.8, v2 ≈ 9.8
    // 保龄球几乎不变速,乒乓球飞快
}
```

---

## 4 · 动量、能量、碰撞

### 4.1 动量守恒

**动量(Momentum)**:`p = mv`(向量)。单位 kg·m/s。

**动量守恒定律**:孤立系统(无外力)的总动量恒定。

**推导**:由牛顿第三定律,F_AB = −F_BA。所以系统总力 = F_AB + F_BA = 0,总动量变化率 = 0,动量恒定。

**例子 1**:枪 + 子弹。开始总动量 0。发射后子弹 50 kg·m/s 向前,枪 50 kg·m/s 向后,总和 0。

**例子 2**:台球开球。母球 1 m/s 撞一排球(总质量同),最后所有球分散,但总动量 = 1 m/s × 总质量。

**例子 3**:火箭。火箭向后喷燃料(动量 −p),火箭向前得 +p(总动量仍 0)。

### 4.2 能量守恒

**动能(Kinetic Energy)**:`KE = (1/2) m v²`(标量)。单位 J。

**势能(Potential Energy)**:取决于位置。重力势能 `PE = mgh`。弹簧势能 `PE = (1/2) k x²`。

**机械能守恒**:无摩擦时,KE + PE 恒定。

**例子**:抛体运动。最高点时 v_y = 0,KE 最小,PE 最大;最低点 PE 最小,KE 最大。`(1/2) m v_y² + m g h = const`。

### 4.3 弹性 vs 非弹性碰撞

**弹性碰撞**:动能 + 动量都守恒。例:台球(近似)、台球。

**非弹性碰撞**:只动量守恒,动能损失(转化为热、声、形变)。例:橡皮球碰地(每次弹低一点)、两车相撞。

**完全非弹性碰撞**:碰撞后两物体粘一起。例:子弹打进木块。

**弹性碰撞公式**(1D):见上面 Rust 代码。

**完全非弹性碰撞公式**(1D):
```
v_final = (m1·v1 + m2·v2) / (m1 + m2)
```

**例子 1**:1 kg 5 m/s 球撞 1 kg 静止球,弹性 → 速度交换(5, 0 → 0, 5)。

**例子 2**:1 kg 5 m/s 球撞 1 kg 静止球,完全非弹性 → 都 2.5 m/s(总动能从 12.5 J 降到 6.25 J,损失一半)。

**例子 3**:1 kg 5 m/s 球撞墙(质量极大),弹性 → 反弹 -5 m/s。完全非弹性 → 停在墙边 0 m/s。

**Rust 代码例子**:带恢复系数的碰撞(介于弹性和完全非弹性之间)。

```rust
fn collide_with_restitution(
    m1: f32, v1: &mut f32,
    m2: f32, v2: &mut f32,
    e: f32,  // 恢复系数 0=完全非弹性, 1=完全弹性
) {
    let m_total = m1 + m2;
    let v_cm = (m1 * *v1 + m2 * *v2) / m_total;  // 质心速度
    // 在质心系中,碰撞后速度反向 * e
    let u1 = *v1 - v_cm;
    let u2 = *v2 - v_cm;
    *v1 = v_cm - e * u1;
    *v2 = v_cm - e * u2;
}

fn main() {
    // 测试不同恢复系数
    for &e in &[1.0, 0.7, 0.5, 0.0] {
        let mut v1 = 5.0_f32;
        let mut v2 = 0.0_f32;
        collide_with_restitution(1.0, &mut v1, 1.0, &mut v2, e);
        println!("e={}: v1={}, v2={}", e, v1, v2);
    }
    // 输出:
    // e=1: v1=0, v2=5      (完全弹性,速度交换)
    // e=0.7: v1=-1.5, v2=6.5
    // e=0.5: v1=-2.5, v2=7.5
    // e=0: v1=-5, v2=10    (质心系反演,总动量守恒)
    // 注意:等质量时 v1+v2=5 始终,动量守恒
}
```

**关键洞察**:**恢复系数 e 是碰撞"弹性"的标量参数**。游戏里不同材质设不同 e:橡胶球 e=0.9,木球 e=0.5,泥团 e=0.1。

### 4.4 冲量

**冲量(Impulse)**:`J = ∫ F dt`(力对时间的积分)。单位 N·s = kg·m/s(同动量)。

**冲量-动量定理**:`J = Δp`(冲量 = 动量变化)。

**碰撞响应就是冲量法**:碰撞瞬间施加一个大冲量,改变两物体的动量。

```rust
// 冲量法碰撞响应(2D,只考虑法线方向)
struct Ball {
    pos: [f32; 2],
    vel: [f32; 2],
    radius: f32,
    mass: f32,
    restitution: f32,
}

fn collide(a: &mut Ball, b: &mut Ball) {
    let dx = b.pos[0] - a.pos[0];
    let dy = b.pos[1] - a.pos[1];
    let dist = (dx*dx + dy*dy).sqrt();
    if dist >= a.radius + b.radius {
        return;  // 没碰
    }

    // 法线(从 a 指向 b)
    let nx = dx / dist;
    let ny = dy / dist;

    // 相对速度沿法线分量
    let rvx = b.vel[0] - a.vel[0];
    let rvy = b.vel[1] - a.vel[1];
    let vel_along_normal = rvx * nx + rvy * ny;

    if vel_along_normal > 0.0 {
        return;  // 已经分离
    }

    // 冲量大小
    let e = a.restitution.min(b.restitution);
    let j = -(1.0 + e) * vel_along_normal / (1.0/a.mass + 1.0/b.mass);

    // 应用冲量
    a.vel[0] -= (j / a.mass) * nx;
    a.vel[1] -= (j / a.mass) * ny;
    b.vel[0] += (j / b.mass) * nx;
    b.vel[1] += (j / b.mass) * ny;

    // 位置修正(防止穿透)
    let penetration = a.radius + b.radius - dist;
    let total_inv_mass = 1.0/a.mass + 1.0/b.mass;
    let correction = penetration / total_inv_mass;
    a.pos[0] -= correction / a.mass * nx * 0.8;
    a.pos[1] -= correction / a.mass * ny * 0.8;
    b.pos[0] += correction / b.mass * nx * 0.8;
    b.pos[1] += correction / b.mass * ny * 0.8;
}
```

---

## 5 · 转动力学

### 5.1 力矩

**力矩(Torque)**:`τ = r × F`(r 是力的作用点到转轴的位移向量)。单位 N·m。

**直觉**:力矩是"扭"的效果。同样力,作用在离转轴远的地方,力矩大。这就是为什么门把手离门轴远——开门省力。

**2D 简化**:`τ = r · F · sin(θ)`,θ 是 r 和 F 的夹角。垂直于 r 的力分量 × r 的长度。

**例子 1**:扳手拧螺母,30 cm 长,垂直用力 20 N,力矩 = 0.3 × 20 = 6 N·m。

**例子 2**:开门,门把手 1 m 离门轴,垂直用力 5 N,力矩 = 5 N·m。

**例子 3**:跷跷板,小孩(20 kg)坐 2 m 处,大人坐 0.5 m 处,大人多重才能平衡?平衡条件:力矩相等,`20·g·2 = m·g·0.5`,m = 80 kg。

### 5.2 转动惯量

**转动惯量(Moment of Inertia)**:`I = ∫ r² dm`(质量分布对转轴的"二阶矩")。单位 kg·m²。

**直觉**:质量衡量"抗拒平动改变",转动惯量衡量"抗拒转动改变"。同样质量,质量集中在边缘(轮子)比集中在中心(铅球)转动惯量大。

**常见形状的 I**(绕质心):

- 质点(距轴 r):`I = mr²`
- 细杆(长 L,绕中心):`I = (1/12) mL²`
- 实心圆盘(半径 R):`I = (1/2) mR²`
- 实心球(半径 R):`I = (2/5) mR²`
- 球壳(半径 R):`I = (2/3) mR²`

**平行轴定理**:`I = I_cm + md²`,d 是新轴到质心轴的距离。

**例子 1**:1 kg 圆盘,半径 0.5 m,绕中心轴:`I = (1/2)(1)(0.25) = 0.125 kg·m²`。

**例子 2**:同一圆盘,绕边缘轴:`I = 0.125 + 1·0.25 = 0.375 kg·m²`(平行轴定理)。

**例子 3**:花样滑冰旋转。运动员收臂 → I 减小 → 角速度增加(角动量守恒,见下)。

### 5.3 角动量

**角动量(Angular Momentum)**:`L = Iω`(ω 是角速度,rad/s)。单位 kg·m²/s。

**角动量守恒**:无外力矩时,L 恒定。`Iω = const`。

**直觉**:外力矩改变角动量,就像外力改变动量。无外力矩时,如果 I 变小,ω 必变大。

**例子 1**:花样滑冰。运动员质量 50 kg,身体展开时 I = 4 kg·m²,ω = 2 rad/s。收臂后 I = 1 kg·m²,L = 4·2 = 1·ω' → ω' = 8 rad/s。转速翻 4 倍。

**例子 2**:地球绕太阳。轨道角动量守恒——近日点(半径小)速度快,远日点(半径大)速度慢。

**例子 3**:自行车为什么不倒。旋转的轮子有角动量,要保持方向(角动量守恒)。转弯需要力矩,而重力试图让车倒下时,角动量的方向改变产生进动,反而让车保持直立。

**Rust 代码例子**:角动量守恒模拟。

```rust
struct Skater {
    angular_momentum: f32,  // 守恒
    moment_of_inertia: f32,
}

impl Skater {
    fn angular_velocity(&self) -> f32 {
        self.angular_momentum / self.moment_of_inertia
    }
    fn tuck_arms(&mut self) {
        // 收臂 → I 减小
        self.moment_of_inertia *= 0.25;
        // L 不变
    }
    fn extend_arms(&mut self) {
        self.moment_of_inertia *= 4.0;
    }
}

fn main() {
    let mut s = Skater {
        angular_momentum: 8.0,  // L = 8
        moment_of_inertia: 4.0, // ω = 2
    };
    println!("展开: I={}, ω={}", s.moment_of_inertia, s.angular_velocity());
    s.tuck_arms();
    println!("收臂: I={}, ω={}", s.moment_of_inertia, s.angular_velocity());
    s.extend_arms();
    println!("展开: I={}, ω={}", s.moment_of_inertia, s.angular_velocity());
}
```

---

## 6 · 振动:从弹簧到共振

### 6.1 简谐振动

**胡克定律**:`F = -kx`(弹簧力,反比位移)。k 是弹簧常数,N/m。

**运动方程**(牛顿第二定律):`ma = -kx`,即 `m d²x/dt² = -kx`。

**解**:`x(t) = A cos(ωt + φ)`,其中 `ω = √(k/m)` 是角频率,A 是振幅,φ 是相位。

**周期**:`T = 2π/ω = 2π √(m/k)`。

**频率**:`f = 1/T`。

**例子 1**:1 kg 物体挂 100 N/m 弹簧,周期 T = 2π √(1/100) = 0.628 s,频率 1.59 Hz。

**例子 2**:单摆(小角度),`T = 2π √(L/g)`。1 米摆,周期 T = 2π √(1/9.8) = 2.0 s。

**例子 3**:LC 振荡电路,`T = 2π √(LC)`。电路也"振动"——能量在电容和电感之间交换。

**Rust 代码例子**:模拟无阻尼简谐振动(显式 Euler,会发散,见后)。

```rust
struct Spring {
    mass: f32,
    k: f32,
    pos: f32,
    vel: f32,
}

fn euler_step(s: &mut Spring, dt: f32) {
    let force = -s.k * s.pos;
    let acc = force / s.mass;
    s.vel += acc * dt;
    s.pos += s.vel * dt;
}

fn main() {
    let mut s = Spring { mass: 1.0, k: 100.0, pos: 1.0, vel: 0.0 };
    let dt = 0.001;  // 小 dt
    let steps = 10000;
    for i in 0..steps {
        euler_step(&mut s, dt);
        if i % 1000 == 0 {
            println!("t={:.2}  pos={:.4}", i as f32 * dt, s.pos);
        }
    }
}
```

### 6.2 阻尼

**阻尼力**(粘性):`F_d = -b v`,b 是阻尼系数。

**运动方程**:`ma = -kx - bv`。

**解**(三种情况,看 `b² vs 4mk`):
- **欠阻尼**(b² < 4mk):振荡衰减,`x(t) = A e^(-γt) cos(ω't + φ)`,γ = b/(2m)。
- **临界阻尼**(b² = 4mk):最快回到平衡不振荡。汽车悬挂设计目标。
- **过阻尼**(b² > 4mk):缓慢回到平衡,不振荡。

**例子 1**:汽车悬挂。设计成接近临界阻尼,过坑后车体迅速平稳,不振荡。

**例子 2**:门自动关闭器。过阻尼——关门缓慢,不撞门框。

**例子 3**:吉他弦。欠阻尼——长时间振荡(发声)。

### 6.3 受迫振动与共振

**受迫**:施加周期性外力 `F(t) = F₀ cos(ω_d t)`,ω_d 是驱动频率。

**运动方程**:`ma = -kx - bv + F₀ cos(ω_d t)`。

**稳态解**:`x(t) = A(ω_d) cos(ω_d t - φ)`,振幅 A 依赖 ω_d。

**共振**:当 ω_d ≈ ω₀(系统固有频率),振幅极大。

**例子 1**:塔科马海峡桥 1940 年坍塌——风激励频率接近桥的固有频率,共振导致振幅爆炸。

**例子 2**:歌剧演员震碎玻璃——唱出玻璃固有频率。

**例子 3**:游乐场的秋千——周期性蹬地(驱动),匹配秋千频率(固有),每次荡高。

**游戏应用**:避免物理引擎里的"共振参数"——某弹簧系统 k 和 m 选错,激励频率接近 ω₀,数值爆炸。

### 6.4 显式 Euler 失败的原因

为什么 `vel += acc * dt; pos += vel * dt;` 让弹簧爆炸?

**分析**:简谐振动能量 `E = (1/2) m v² + (1/2) k x²` 应该守恒。

但显式 Euler 每步:
```
v_new = v_old + (-k/m · x_old) dt
x_new = x_old + v_new dt
```

计算新能量 `E_new = (1/2) m v_new² + (1/2) k x_new²`,展开:

```
E_new = (1/2) m (v + (-k/m x) dt)² + (1/2) k (x + v dt + ...)²
      ≈ E_old + (k²/m x² + k v²) dt²  (一阶项抵消,二阶项正)
```

**Euler 每步能量增加**!所以弹簧越弹越大,最终爆炸。

**修复**:用 **symplectic Euler**(半隐式):

```
v_new = v_old + (-k/m · x_old) dt
x_new = x_old + v_new dt  ← 用新 v
```

只改一行——但能量误差"振荡"而非"累积",稳定。

或者用 **Verlet**(更精确):

```
x_new = 2x_old - x_prev + a dt²
x_prev = x_old
x_old = x_new
```

或者 **RK4**(更精确,但贵):

见第 20 篇 11.1 节的 RK4 代码。

**Rust 代码例子**:三种积分器对比弹簧。

```rust
struct State {
    pos: f32,
    vel: f32,
}

const M: f32 = 1.0;
const K: f32 = 100.0;

fn force(pos: f32) -> f32 { -K * pos }

// 显式 Euler(不稳定)
fn explicit_euler(s: &mut State, dt: f32) {
    let acc = force(s.pos) / M;
    s.vel += acc * dt;
    s.pos += s.vel * dt;  // 用更新后的 v
}

// 实际上"显式 Euler"是 v 先更新,x 用新 v。这是 semi-implicit,稍稳。
// 真正的"显式 Euler"是 x 先用旧 v,然后 v 更新:
fn true_explicit_euler(s: &mut State, dt: f32) {
    s.pos += s.vel * dt;  // 用旧 v
    let acc = force(s.pos) / M;
    s.vel += acc * dt;
}

// Symplectic / Semi-implicit Euler(能量稳定)
fn semi_implicit_euler(s: &mut State, dt: f32) {
    let acc = force(s.pos) / M;
    s.vel += acc * dt;     // 先更新 v
    s.pos += s.vel * dt;   // 再用新 v 更新 x
}

// Velocity Verlet(更精确,O(dt⁴) 误差)
fn verlet(s: &mut State, dt: f32, prev_acc: &mut f32) {
    s.pos += s.vel * dt + 0.5 * *prev_acc * dt * dt;
    let new_acc = force(s.pos) / M;
    s.vel += 0.5 * (*prev_acc + new_acc) * dt;
    *prev_acc = new_acc;
}

fn main() {
    let dt = 0.01;
    let steps = 5000;

    let mut s = State { pos: 1.0, vel: 0.0 };
    for _ in 0..steps {
        true_explicit_euler(&mut s, dt);
    }
    println!("True Euler: pos={}, vel={}", s.pos, s.vel);

    let mut s = State { pos: 1.0, vel: 0.0 };
    for _ in 0..steps {
        semi_implicit_euler(&mut s, dt);
    }
    println!("Semi-implicit: pos={}, vel={}", s.pos, s.vel);

    let mut s = State { pos: 1.0, vel: 0.0 };
    let mut prev_acc = force(s.pos) / M;
    for _ in 0..steps {
        verlet(&mut s, dt, &mut prev_acc);
    }
    println!("Verlet: pos={}, vel={}", s.pos, s.vel);
}
```

**预期观察**:
- True Euler:位置和速度**指数增长**(发散)。
- Semi-implicit:位置和速度**振幅稳定**(略小漂移)。
- Verlet:位置和速度**精确振荡**(几乎不发散)。

这就是为什么**所有严肃物理引擎用 Verlet 或类似 symplectic 积分器**。

---

## 7 · 摩擦与阻力

### 7.1 干摩擦

**静摩擦**(没滑动):`F_s ≤ μ_s N`。μ_s 是静摩擦系数,N 是法向力。

**动摩擦**(滑动):`F_k = μ_k N`,方向与运动相反。

**关键洞察**:静摩擦是"≤",可以是 0 到 μ_s N 之间任何值,刚好抵消使物体不动的力。动摩擦是确定的 μ_k N。

**μ_s > μ_k**(总是):推箱子启动难,推开了反而省力。

**例子 1**:10 kg 箱子在地面(μ_s = 0.5, μ_k = 0.3)。最大静摩擦 = 0.5 × 10 × 9.8 = 49 N。推力 < 49 N,箱子不动;推力 = 49 N,箱子刚好要动;推力 > 49 N,箱子加速。一旦动了,动摩擦 = 0.3 × 10 × 9.8 = 29.4 N,净力 = 推力 - 29.4。

**例子 2**:斜坡上的箱子刚好不滑的角度 `tan(θ_c) = μ_s`。μ_s = 0.5 → θ_c ≈ 27°。

**例子 3**:刹车。最大刹车力 = μ N = μ m g,最大减速度 = μ g。μ = 0.8(干沥青) → 减速度 7.8 m/s²,从 100 km/h(28 m/s)刹停需要 3.6 秒,距离 50 m。

### 7.2 流体阻力

**线性阻力**(低速):`F = -bv`。b 是阻力系数。

**二次阻力**(高速):`F = -c v |v|` 或 `F = -(1/2) ρ C_d A v²`,ρ 是流体密度,C_d 是阻力系数(球约 0.5),A 是横截面积。

**终端速度**:阻力 = 重力时,物体停止加速。

线性:`bv = mg → v_t = mg/b`。

二次:`(1/2) ρ C_d A v² = mg → v_t = √(2mg / (ρ C_d A))`。

**例子 1**:跳伞运动员。m = 70 kg,展开伞 C_d A ≈ 1 m²,空气 ρ = 1.2 kg/m³,终端速度 v_t = √(2·70·9.8 / (1.2·0.5·1)) ≈ 48 m/s(172 km/h)。和实际吻合。

**例子 2**:雨滴。质量小,v_t 也小,所以雨滴不会砸死人。

**例子 3**:游戏里"水流影响角色"。设二次阻力,角色在水里移动慢,符合直觉。

```rust
// 模拟下落物体(空气阻力),求终端速度
struct Falling {
    mass: f32,
    vel: f32,
    pos: f32,
}

fn step_with_drag(f: &mut Falling, dt: f32, drag_coef: f32) {
    let g = 9.8;
    let drag = drag_coef * f.vel * f.vel.abs();  // 二次阻力
    let force = f.mass * g - drag;  // 重力 - 阻力
    let acc = force / f.mass;
    f.vel += acc * dt;
    f.pos += f.vel * dt;
}

fn main() {
    let mut f = Falling { mass: 70.0, vel: 0.0, pos: 0.0 };
    // drag_coef = (1/2) ρ C_d A
    let drag = 0.5 * 1.2 * 0.5 * 1.0;
    let dt = 0.01;
    for i in 0..5000 {
        step_with_drag(&mut f, dt, drag);
        if i % 500 == 0 {
            println!("t={:.1}  v={:.2} m/s", i as f32 * dt, f.vel);
        }
    }
    // 输出应该接近终端速度 ≈ 48 m/s
}
```

---

## 8 · 单位:SI vs 游戏单位

这是新手最容易忽略、却最容易引发 bug 的事。

### 8.1 SI 单位

国际单位制(SI)从 7 个基本单位推导一切:

- **米(m)**:长度
- **千克(kg)**:质量
- **秒(s)**:时间
- **安培(A)**:电流
- **开尔文(K)**:温度
- **摩尔(mol)**:物质的量
- **坎德拉(cd)**:发光强度

物理常用派生:
- 力:N = kg·m/s²
- 能量:J = kg·m²/s² = N·m
- 功率:W = J/s
- 压强:Pa = N/m²

### 8.2 游戏单位的陷阱

新手常写:
```rust
player.x += 5;  // 5 是什么?米?像素?每秒像素?
```

如果"5"是"每帧像素",但你的游戏 60 FPS:
- 每秒移动 5 × 60 = 300 像素/秒
- 在 1080p(1920 像素宽)屏幕,跨屏用 6.4 秒
- 在 4K 屏(3840 像素宽),跨屏 12.8 秒——你的游戏在 4K 上变慢!

如果"5"是"每秒米":
- 角色速度 5 m/s
- 在 1080p 屏幕,假设 100 像素/米的渲染比例,每秒移动 500 像素
- 4K 屏渲染比例 200 像素/米,每秒移动 1000 像素——游戏速度看起来一样(但跨屏时间不同,这是合理的)

**正确做法**:**游戏世界用 SI 单位**(米、秒、kg),**渲染时换算成像素**。

```rust
struct World {
    player_pos: Vec2,  // 米
    player_vel: Vec2,  // m/s
    pixels_per_meter: f32,
}

fn update(w: &mut World, dt: f32) {
    // dt 是秒
    w.player_vel.y -= 9.8 * dt;  // 重力 m/s²
    w.player_pos += w.player_vel * dt;  // 米
}

fn render(w: &World) -> ScreenPos {
    ScreenPos {
        x: w.player_pos.x * w.pixels_per_meter,
        y: w.player_pos.y * w.pixels_per_meter,
    }
}
```

**好处**:
1. **物理公式直接用**:9.8 m/s² 是重力加速度,不需要换算。
2. **帧率独立**:60 FPS 和 144 FPS 物理行为一致(因为 dt 是秒)。
3. **分辨率独立**:渲染时按比例缩放,不同分辨率下"游戏速度"相同。
4. **可调试**:打印"5 m/s"比"5 单位"有意义。

### 8.3 dt 与固定时间步

**陷阱**:dt 是上一帧的实际时间。如果某帧卡顿 dt 突然变大,物理就"跳"一下,可能穿墙。

**修复**:**固定时间步**(Fixed Timestep):

```rust
const FIXED_DT: f32 = 1.0 / 60.0;
let mut accumulator = 0.0;

fn game_loop(actual_dt: f32) {
    accumulator += actual_dt;
    while accumulator >= FIXED_DT {
        physics_update(FIXED_DT);  // 物理永远用 FIXED_DT
        accumulator -= FIXED_DT;
    }
    // 渲染可以用插值平滑
    let alpha = accumulator / FIXED_DT;
    render interpolate(state, prev_state, alpha);
}
```

**这就是 Box2D / PhysX 的核心架构**。Casey 在 Handmade Hero 也强调"fixed timestep"的重要性。

### 8.4 角度:弧度 vs 度

数学公式用**弧度**(rad)。游戏 UI 用**度**(°)。

转换:`1 rad = 180/π 度 ≈ 57.3°`,`1° = π/180 rad ≈ 0.0175 rad`。

**为什么弧度**:微积分里 `d/dx sin(x) = cos(x)` 只有 x 用弧度才对。度的话有个 π/180 的因子。

**Rust 例子**:

```rust
use std::f64::consts::PI;

let deg = 45.0;
let rad = deg * PI / 180.0;
println!("45° = {} rad", rad);
println!("sin(45°) = {}", rad.sin());  // 用弧度
```

---

## 9 · 四域深入

### 9.1 · 🎮 游戏编程视角

游戏物理引擎的演化:

**1970s**:无物理。物体匀速直线移动,碰撞用 AABB 重叠判断。

**1980s**:简单物理。重力 + 跳跃,马里奥。

**1990s**:刚体物理。Quake 用 BSP + 简单冲量响应。

**2000s**:工业级引擎。Havok、PhysX、Box2D。完整刚体动力学、约束、关节。

**2010s**:软体物理、流体、PBD(Position Based Dynamics)。

**2020s**:GPU 物理、机器学习物理(可微分物理)。

游戏物理的"游戏感"(game feel)和"真实物理"经常矛盾。马里奥的跳跃弧线**违反真实物理**(空中变向),但符合玩家直觉。好的游戏物理需要"看起来对",而非"严格对"。

### 9.2 · 🎨 图形学视角

图形和物理在以下场景交叉:

**碰撞检测**:用 BVH / SAT / GJK,见 Phase 4。

**布料模拟**:Verlet 积分 + 距离约束。每种布料都是大量粒子 + 约束。

**头发**:类似布料,但每个粒子链长。Unreal 用 HairWorks / Strand-based hair。

**流体**:SPH(Smoothed Particle Hydrodynamics)、PIC / FLIP。

**破坏效果**:Voronoi 碎片 + 刚体物理。

### 9.3 · 🐧 Linux 系统编程视角

物理引擎在 Linux 上的工具:

- **Box2D**:C++ 2D 物理,Rust 绑定 `box2d-rs`。
- **Bullet / PhysX**:C++ 3D 物理。
- **rapier**:纯 Rust 2D + 3D,Bevy 用。
- **nphysics**:Rust,被 rapier 替代。

```bash
# 装 rapier 例子
cargo add rapier3d
```

Linux 内核里也有物理——调度器的"虚拟运行时间"就像一个"公平力"调整。

### 9.4 · 🦀 Rust 生态视角

Rust 物理生态:

- **rapier**:目前最完整的纯 Rust 物理。Sebastien Crozet 写的(也是 nalgebra 作者)。
- **bevy_rapier**:Bevy 集成。
- **physx-rs**:PhysX 的 Rust 绑定(NVIDIA 官方物理)。

为什么 Rust 适合物理:**代数数据类型**(ADT)让"刚体 vs 软体 vs 流体"的表达自然;**所有权**让物理对象生命周期清晰;**无 GC**让性能可预测(物理引擎不能停顿)。

---

## 10 · 认知地图

### 10.1 上级

- **经典力学**:牛顿框架,本篇范围。
- **分析力学**:拉格朗日 / 哈密顿形式,更抽象但更强大。
- **连续介质力学**:流体、弹性体。
- **量子力学**:微观,游戏用不上但概念有趣。

### 10.2 同级

| 分支 | 研究什么 |
|---|---|
| 牛顿力学 | 力与运动 |
| 热力学 | 温度、熵、能量 |
| 电磁学 | 电荷、磁场 |
| 相对论 | 高速、引力 |

### 10.3 下级

- 牛顿三定律 / 动量能量 / 转动 / 振动 / 阻力 / 积分器 / 单位

---

## 11 · 对照与变奏

### 11.1 积分器对比

| 方法 | 误差 | 稳定性 | 复杂度 | 适用 |
|---|---|---|---|---|
| 显式 Euler | O(dt) | 差(发散) | 最低 | 教学 |
| Semi-implicit Euler | O(dt) | 好(symplectic) | 低 | 简单游戏 |
| Verlet | O(dt²) | 好(symplectic) | 中 | 粒子 / 布料 |
| RK4 | O(dt⁴) | 中 | 高 | 高精度需求 |
| Implicit Euler | O(dt) | 极好 | 高(要解方程) | 僵硬系统 |
| Verlet 时间中心 | O(dt²) | 好 | 中 | 通用 |

**经验法则**:游戏物理用 Semi-implicit Euler 或 Verlet。需要精确(科学计算)用 RK4。

### 11.2 SI vs 游戏单位 vs 无量纲

| 系统 | 长度 | 时间 | 质量 |
|---|---|---|---|
| SI | 米 | 秒 | 千克 |
| CGS | 厘米 | 秒 | 克 |
| 英制 | 英尺 | 秒 | 磅 |
| 游戏世界 | "米"(自定义) | 秒 | "kg"(自定义) |
| 量子物理(原子单位) | 玻尔半径 | ħ/E_h | 电子质量 |

**关键**:你的游戏内部单位**可以是任何东西**,只要一致。但用 SI 让你直接复用物理公式,所以推荐。

### 11.3 历史

- **17 世纪**:牛顿《自然哲学的数学原理》(1687)。
- **18 世纪**:欧拉刚体动力学。
- **19 世纪**:拉格朗日、哈密顿分析力学。
- **20 世纪**:数值方法成熟(计算机诞生后)。Verlet 1967 年提出。
- **21 世纪**:游戏物理引擎工业化。GPU 物理兴起。

---

## 12 · 关联 Day

- **铺垫**:[20-math-foundation-extended.md](20-math-foundation-extended.md) — 数学基础,本篇大量使用
- **当天**:21-physics-foundation(本篇)
- **后续**:[22-signals-foundation.md](22-signals-foundation.md) — 信号处理,用本篇的振动概念;Phase 2 / 4 物理代码都用本篇

---

## 13 · 变式训练

### Lv1 · 概念辨析

**题**:为什么显式 Euler 让弹簧爆炸,而 Semi-implicit Euler 不会?

**参考解答**:显式 Euler 每步能量增加 O(dt²)(正的二阶项),持续累积导致振幅指数增长。Semi-implicit Euler(先更新 v,再用新 v 更新 x)是 symplectic——能量误差"振荡"在真值附近,不单调增长。对周期性系统(弹簧、轨道),symplectic 性质是关键的。

### Lv2 · 动手实践

**题**:写一个 Rust 程序,模拟球从 100 米高落下,空气阻力二次,计算落地的速度和时间。

**完成标准**:落地速度 ≈ 48 m/s(接近终端速度)。

**参考解答**:

```rust
struct Falling { vel: f32, pos: f32 }
const M: f32 = 70.0;
const DRAG: f32 = 0.5 * 1.2 * 0.5 * 1.0;  // (1/2)ρ C_d A

fn step(f: &mut Falling, dt: f32) {
    let g = 9.8_f32;
    let drag_force = DRAG * f.vel * f.vel.abs();
    let net = M * g - drag_force;
    let acc = net / M;
    f.vel += acc * dt;
    f.pos -= f.vel * dt;  // pos 减小=下落
}

fn main() {
    let mut f = Falling { vel: 0.0, pos: 100.0 };
    let mut t = 0.0;
    let dt = 0.001;
    while f.pos > 0.0 {
        step(&mut f, dt);
        t += dt;
    }
    println!("落地 t = {:.2} s, v = {:.2} m/s", t, f.vel);
}
```

### Lv3 · 迁移设计

**题**:你的角色控制有 bug——按下跳跃键后角色飞到天上,然后下落到地面"卡住"。诊断每个可能的原因。

**提示**:
- "飞到天上" → 初速度太大?单位混乱(像素 vs 米)?
- "下落" → 重力对吗?(应该用 SI g=9.8,不是任意值)
- "卡住" → 没碰撞响应?位置修正没做?半隐式 vs 半隐式?

### Lv4 · 开源贡献

**题**:rapier GitHub: https://github.com/dimforge/rapier

1. Clone,看 `src/integration/integrator.rs`。
2. 对比本篇的 Semi-implicit Euler 实现,看工业代码加了什么。
3. 写一个 PR:补一个 example 演示弹性碰撞。

---

## 14 · Rust / Arch 落地代码

### 14.1 综合物理 demo:弹跳球(Euler / Verlet / RK4 对比)

```rust
// src/main.rs - 综合物理 demo

#[derive(Clone, Copy)]
struct Body {
    pos: f32,
    vel: f32,
}

const G: f32 = 9.81;
const DT: f32 = 0.01;
const RESTITUTION: f32 = 0.7;
const GROUND: f32 = 0.0;
const INITIAL_HEIGHT: f32 = 10.0;

// 显式 Euler(本篇建议你避免,但对比用)
fn euler(b: &mut Body, dt: f32) {
    let acc = -G;
    b.vel += acc * dt;
    b.pos += b.vel * dt;
    if b.pos < GROUND {
        b.pos = GROUND;
        b.vel = -b.vel * RESTITUTION;
    }
}

// Semi-implicit(symplectic)Euler
fn semi_implicit(b: &mut Body, dt: f32) {
    let acc = -G;
    b.vel += acc * dt;
    b.pos += b.vel * dt;
    if b.pos < GROUND {
        b.pos = GROUND;
        b.vel = -b.vel * RESTITUTION;
    }
}

// Velocity Verlet(对自由落体 = 半隐式,但概念上不同)
fn verlet(b: &mut Body, prev_acc: &mut f32, dt: f32) {
    b.pos += b.vel * dt + 0.5 * *prev_acc * dt * dt;
    let new_acc = -G;
    b.vel += 0.5 * (*prev_acc + new_acc) * dt;
    *prev_acc = new_acc;
    if b.pos < GROUND {
        b.pos = GROUND;
        b.vel = -b.vel * RESTITUTION;
    }
}

// RK4(对自由落体也退化,但形式上完整)
fn rk4(b: &mut Body, dt: f32) {
    // dy/dt = [v, -g]
    let k1v = b.vel;
    let k1a = -G;
    let k2v = b.vel + 0.5 * dt * k1a;
    let k2a = -G;
    let k3v = b.vel + 0.5 * dt * k2a;
    let k3a = -G;
    let k4v = b.vel + dt * k3a;
    let k4a = -G;
    b.pos += dt / 6.0 * (k1v + 2.0*k2v + 2.0*k3v + k4v);
    b.vel += dt / 6.0 * (k1a + 2.0*k2a + 2.0*k3a + k4a);
    if b.pos < GROUND {
        b.pos = GROUND;
        b.vel = -b.vel * RESTITUTION;
    }
}

fn simulate(name: &str, mut step: impl FnMut(&mut Body, f32)) {
    let mut b = Body { pos: INITIAL_HEIGHT, vel: 0.0 };
    let mut t = 0.0;
    let mut bounces = 0;
    let mut prev_height = INITIAL_HEIGHT;
    while t < 5.0 {
        step(&mut b, DT);
        t += DT;
        if (b.pos - GROUND).abs() < 0.01 && b.vel.abs() < 0.5 && prev_height > 0.5 {
            bounces += 1;
            if bounces >= 8 { break; }
        }
        prev_height = b.pos;
    }
    println!("{}: 5 秒后 pos={:.3}, vel={:.3}, 反弹约 {} 次", name, b.pos, b.vel, bounces);
}

fn main() {
    println!("初始高度 {} 米,恢复系数 {}", INITIAL_HEIGHT, RESTITUTION);
    println!("---");
    simulate("Explicit Euler", euler);
    simulate("Semi-implicit Euler", semi_implicit);
    let mut pa = -G;
    simulate("Verlet", |b, dt| {
        let mut p = pa;
        verlet(b, &mut p, dt);
        pa = p;
    });
    simulate("RK4", rk4);
}
```

### 14.2 用 rapier

```toml
[dependencies]
rapier2d = "0.21"
```

```rust
use rapier2d::prelude::*;

fn main() {
    let mut rigid_body_set = RigidBodySet::new();
    let mut collider_set = ColliderSet::new();
    let mut integration_parameters = IntegrationParameters::default();
    let mut physics_pipeline = PhysicsPipeline::new();
    let mut island_manager = IslandManager::new();
    let mut joint_set = JointSet::new();
    let mut ccd_solver = CCDSolver::new();

    // 创建地面
    let ground = RigidBodyBuilder::fixed().translation(vector![0.0, 0.0]).build();
    let ground_handle = rigid_body_set.insert(ground);
    collider_set.insert(
        ColliderBuilder::cuboid(10.0, 0.5).build(),
        ground_handle,
        &mut rigid_body_set,
    );

    // 创建动态球
    let ball = RigidBodyBuilder::dynamic()
        .translation(vector![0.0, 10.0])
        .build();
    let ball_handle = rigid_body_set.insert(ball);
    collider_set.insert(
        ColliderBuilder::ball(0.5).restitution(0.7).build(),
        ball_handle,
        &mut rigid_body_set,
    );

    // 模拟 100 步
    for _ in 0..100 {
        physics_pipeline.step(
            &Vector::zeros(),
            &integration_parameters,
            &mut island_manager,
            &mut rigid_body_set,
            &mut collider_set,
            &mut joint_set,
            &mut ccd_solver,
            &(),
            &(),
        );
        let ball_pos = rigid_body_set[ball_handle].translation();
        println!("ball pos: ({:.3}, {:.3})", ball_pos.x, ball_pos.y);
    }
}
```

### 14.3 Arch 验证物理常数

```bash
# 检查你机器上的 g(海拔、纬度会微调)
python3 -c "
import math
# 标准重力
g = 9.80665  # m/s²,标准值
print(f'g = {g} m/s²')
print(f'地球半径 = 6.371e6 m')
print(f'第一宇宙速度 = {math.sqrt(g * 6.371e6):.1f} m/s ≈ 7.9 km/s')
"

# 看 CPU 信息(为性能优化参考)
lscpu | grep -E "MHz|GHz|cache"

# 时间精度(物理仿真用)
python3 -c "
import time
print(f'时间分辨率 = {time.get_clock_info(\"perf_counter\").resolution} 秒')
"
```

### 14.4 Troubleshooting

**问题1**:角色"瞬移到天上"。
原因:跳跃初速度单位错(像素/帧 vs m/s)。
解决:用 SI 单位,跳跃初速度约 5 m/s 是合理的(让角色跳 1 米高)。

**问题2**:弹簧爆炸。
原因:显式 Euler 不稳定。
解决:换 Semi-implicit 或 Verlet;或减小 dt;或减小 k。

**问题3**:球每次反弹更高。
原因:浮点误差 + 没位置修正。
解决:反弹时强制 `pos.y = ground + radius`,然后翻转速度。

**问题4**:物理在 60 FPS 和 144 FPS 表现不同。
原因:用渲染 dt 做物理。
解决:固定时间步,见 8.3 节。

**问题5**:角色穿墙。
原因:dt 太大,单步位移 > 墙厚。
解决:固定时间步 + 子步进;或用 sweep test(连续碰撞检测)。

---

## 15 · 延伸阅读(可选补充,非必需)

本仓库本地资料:
- [20-math-foundation-extended.md](20-math-foundation-extended.md) — 数学基础,本篇大量使用
- [22-signals-foundation.md](22-signals-foundation.md) — 信号处理,振动是信号的物理基础
- [14-math-foundations.md](14-math-foundations.md) — 简化版数学基础

外部稳定 URL:
- Game Physics Engine Development(书):https://www.routledge.com/Game-Physics-Engine-Development/Millington/p/book/9781138690 Redis
- Box2D 文档:https://box2d.org/documentation/
- Real-Time Collision Detection(书):https://www.routledge.com/Real-Time-Collision-Detection/Ericson/p/book/9781558607323
- GDC 物理 vault:https://gdcvault.com/
