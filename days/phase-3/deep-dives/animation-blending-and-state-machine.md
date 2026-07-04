
# 动画混合与状态机:从单 clip 到 IK 的完整工程

> 你的角色现在能跑动画了——前提是它一直在播 walk 这一个 clip。但真实游戏不是这样。你按下摇杆,角色要先**从 idle 平滑过渡到 walk**(cross-fade),再**随着摇杆推到底从 walk 过渡到 run**(1D blend tree),左转时**上半身稍微转向左**(additive),脚踩在不平地面上时**脚踝贴地**(IK)。这一整套东西不是"加几个动画文件"能搞定的,它需要**动画状态机(Animation State Machine,ASM)**和**混合树(Blend Tree)**两套全新抽象。这一篇我们从零写一个 500 行 Rust 的 mini 动画系统,涵盖 cross-fade / 1D / 2D blend / additive / layer / FSM,然后完整推导 IK 的三大算法(CCD / FABRIK / Two-Bone IK),最后接到你的 HH 主角身上,让它在跑 / 走 / 跳之间无缝切换。

## 0 · 为什么要有这一篇

你已经啃完 [skeletal-animation-fundamentals](./skeletal-animation-fundamentals.md)。你的引擎能加载 glTF、跑 FK、算蒙皮矩阵、把 mesh 渲染出来。这时你的角色会"播动画"了。但是播动画和"看起来活"之间还差十万八千里。

**工业级的角色动画需要解决五件事**:

**第一,过渡**。从 walk 切到 run 时不能"啪"地一帧切换——那看起来像鬼畜视频。你需要 **cross-fade**:在 200ms 内把 walk 姿势线性插值到 run 姿势。听起来简单——blend 两个 pose 就行——但什么时候开始切?切多久?切到一半用户又改主意了怎么办?这是**状态机**的事。

**第二,参数化**。walk 和 run 不是两个独立 clip,而是同一个"移动"动作的两种速度。摇杆推 50%,角色应该是"中速走"——介于 walk 和 run 之间。这需要 **1D blend tree**:输入 speed 参数,输出加权混合。考虑转向就是 **2D blend tree**(locomotion blend)。

**第三,叠加**。角色跑动时手里拿枪,枪口要随视角转动——但 base run clip 没这个信息。你不可能为"跑步 + 持枪 + 看上方"重新录制 clip(组合爆炸)。**additive animation** 录一个"扭头向上看"作为 delta,**把 delta 叠加到 base run 上**,组合就出来了。

**第四,层次**。角色开枪时**下半身仍在跑**,**上半身在播放 fire clip**。你需要 **animation layer**:lower body 跑 locomotion,upper body 跑 attack / aim / interact。

**第五,环境适应**。角色站在斜坡上,脚要顺着斜坡角度——但 run clip 是按平地录的。**IK(逆向运动学)**:给定"脚的位置 = 斜坡接触点",反推"膝盖和髋关节应该怎么弯"。

这五件事**叠加**就是工业级角色动画。一个 AAA 主角的动画系统:7 个 layer × 3 个 blend tree × 12 个状态 × cross-fade 200ms × 30 个 IK 节点。Casey 在 HH 没正式讲这套(HH 用程序化 sprite 动画),但**任何要做 3D 角色的项目都绕不开**。

**学完这一篇,你应该能**:

- 用 200 行 Rust 写一个能跑的 cross-fade + 1D blend tree
- 在白纸上手推 CCD 和 FABRIK 的迭代公式(不是抄)
- 解释 Two-Bone IK 的极向量(pole vector)为什么必须存在
- 看懂 Unreal AnimBP、Unity Animator、Godot AnimationTree、bevy_animation 的代码结构
- 解释为什么 Motion Matching 正在取代传统 blend tree
- 在你的 HH 项目里加一个最简单的 locomotion 系统(speed → walk/run blend)

## 1 · 心智模型:从单 clip 到动画树

### 1.1 第一步直觉:角色是"姿势的函数"

你的角色每一帧都有一个**姿势(pose)**——一组 64 个 joint 的 local transform。单 clip 模式下 `pose = clip.sample(time)`,time 由游戏 tick 推动。但真实游戏里,pose 是**多个来源混合**出来的:

```
最终 pose =
   blend_tree.locomotion(speed, turn)        // 1: 主移动(locomotion,blend tree)
   .apply_layer(upper_body, "fire_clip")     // 2: 上半身开枪(layer)
   .add("look_delta", look_yaw)              // 3: 头部看(additive)
   .apply_ik("foot_L", ground_L)             // 4: 左脚贴地(IK)
   .apply_ik("foot_R", ground_R)             // 5: 右脚贴地(IK)
```

每一行是一个"姿势操作"。pose 是这些操作**串联**的结果。最终这个 pose 送到蒙皮系统,渲染出来。这套"操作串联"的抽象叫 **Animation Pose Pipeline**(动画姿势管线),或更通用的 **Animation Graph**(动画图)。

### 1.2 四种核心"姿势操作"

整个动画系统归根结底就四种操作:

**1. Sample(采样)**:`pose = clip[t]`。从 clip 读出某个时间点的 pose。基础操作。

**2. Blend(混合)**:`pose = α × pose_A + (1-α) × pose_B`。两个 pose 加权平均。α 从 0 到 1,从 A 平滑过渡到 B。**blend 在 pose 空间**(每根 joint 的 TRS 分量加权),不是 clip 空间。

**3. Add(叠加)**:`pose = pose_base + pose_delta`。把 delta pose 加到 base 上。delta 不是普通 pose,它表示"相对于 base 的偏移量"——如何计算 delta 是 §2.7 的核心。

**4. Override(覆盖)**:`pose[mask] = pose_override[mask]`。在 pose 子集(比如"上半身所有 joint")上用另一个 pose 覆盖。这是 layer 的基础。

四种操作的组合能表达任何动画需求。**Animation Graph 本质上就是这四种操作的 DAG(有向无环图)**。

### 1.3 状态机:在"操作图"之上加"切换"

光有操作图还不够,你还需要**控制什么时候切换到什么图**。这是状态机的事:

- **State(状态)**:每个 state 对应一个 pose pipeline(比如"locomotion 状态"对应 §1.2 的多步操作)。
- **Transition(过渡)**:从一个 state 切到另一个 state,带 cross-fade。
- **Parameter(参数)**:transition 的触发条件,比如 `speed > 0.5` 触发 idle → walk。

最简单的 FSM:

```
        speed > 0.1           speed > 5
  idle ─────────────► walk ──────────► run
   ▲                    │                 │
   │   speed < 0.1      │  speed < 3      │
   └────────────────────┴─────────────────┘
              (cross-fade 200ms)
```

每个箭头是一个 transition,带条件 + cross-fade 时长。Cross-fade 期间,角色同时在两个 state(α 从 0 到 1 平滑插值)。

### 1.4 HFSM:状态机的状态机

简单 FSM 处理不了"嵌套"。比如"地面移动"(walk / run / sprint)和"空中"(jump / fall / land)是**两层**:顶层 FSM(Grounded ↔ Airborne),Grounded 内部子 FSM(Idle ↔ Walk ↔ Run),Airborne 内部子 FSM(Jump ↔ Fall ↔ Land)。**HFSM(Hierarchical FSM)** 让 state 内部还能有 FSM。Unreal AnimBP、Unity Animator、Godot AnimationTree 全部是 HFSM。

### 1.5 Motion Matching:正在颠覆传统

2016 年后,业界开始用一种完全不同的方法——**Motion Matching**。它没有 state、没有 transition、没有 blend tree。而是把所有动画数据"碎成 1 帧一片"扔进数据库,每帧游戏给一个"目标"(玩家想要的速度 + 未来 0.5s 的轨迹),在数据库里搜"特征最接近的下一帧",切过去。Cross-fade 5-10 帧抹平切换。

这套方法是 Ubisoft 在《For Honor》(2017)首次大规模用,Naughty Dog《最后生还者 2》(2020)、Remedy《Control》(2019)、Santa Monica《战神》(2018)全部用 Motion Matching。**它取代了 blend tree 的"locomotion"部分**(但状态机层级、IK、additive 仍然存在)。我们 §9 简单介绍,深度留给未来专门的 deep-dive。

## 2 · 从零写 mini animation 系统

我们分 8 步走,每一步都有可运行的 Rust 代码,每一步都会踩坑再修。最终是一个 500 行的 mini 系统,涵盖 sample / blend / cross-fade / 1D / 2D blend / additive / layer / FSM。

### 2.1 Step 0:Pose 数据结构

第一步定义 pose——整个系统的核心数据类型。

```rust
// src/anim/pose.rs
#[derive(Clone, Debug)]
pub struct Transform {
    pub translation: [f32; 3],
    pub rotation: [f32; 4],    // unit quaternion (x, y, z, w)
    pub scale: [f32; 3],
}

#[derive(Clone, Debug)]
pub struct Pose {
    pub joints: Vec<Transform>,   // index = joint index
}

impl Pose {
    pub fn with_joint_count(n: usize) -> Self {
        Self { joints: vec![Transform::identity(); n] }
    }
    pub fn joint_count(&self) -> usize { self.joints.len() }
}

impl Transform {
    pub fn identity() -> Self {
        Self {
            translation: [0.0, 0.0, 0.0],
            rotation: [0.0, 0.0, 0.0, 1.0],   // identity quaternion
            scale: [1.0, 1.0, 1.0],
        }
    }
}
```

**第一个设计决策**:为什么 pose 用 `(translation, rotation, scale)` 分解存,不直接存 `Mat4`?因为**插值**。pose 经常需要在两个之间插值。Mat4 之间插值是**几何错误**——直接 lerp 两个 4x4 矩阵,旋转部分会变形成非刚性矩阵。分解成 TRS 后,translation 和 scale 用 lerp,rotation 用 SLERP(球面线性插值),每个分量都正确。工业级引擎(OZZ、Unreal、Unity)都是 TRS 分解存。Bevy 0.13+ 也是。glTF 2.0 spec 也是。

**第二个设计决策**:Pose 应该**可复用 buffer**(不每次分配)。64-joint 角色,每帧 5-10 次 blend 操作,如果每次都分配新 Vec,allocation 会成为 hot path。所以 `Pose::joints` 是 Vec,在每次求值时**原地写入**。

### 2.2 Step 1:Sample(从 clip 取 pose)

承接 skeletal-animation 那篇的 AnimationClip,加一个 `sample_into(pose, t)` 把结果写到 pose buffer:

```rust
// src/anim/clip.rs
use crate::anim::pose::{Pose, Transform};

#[derive(Clone, Debug)]
pub struct Keyframe {
    pub time: f32,
    pub translation: [f32; 3],
    pub rotation: [f32; 4],
    pub scale: [f32; 3],
}

#[derive(Clone, Debug)]
pub struct JointTrack { pub keyframes: Vec<Keyframe> }

#[derive(Clone, Debug)]
pub struct AnimationClip {
    pub duration: f32,
    pub tracks: Vec<JointTrack>,    // index = joint index
}

impl AnimationClip {
    pub fn sample_into(&self, out: &mut Pose, t: f32) {
        let t = if self.duration > 0.0 { t.rem_euclid(self.duration) } else { 0.0 };
        for (i, track) in self.tracks.iter().enumerate() {
            if track.keyframes.is_empty() {
                out.joints[i] = Transform::identity();
                continue;
            }
            let (k0, k1, alpha) = self.find_keyframes(&track.keyframes, t);
            out.joints[i] = Transform {
                translation: lerp_vec3(k0.translation, k1.translation, alpha),
                rotation: slerp_quat(k0.rotation, k1.rotation, alpha),
                scale: lerp_vec3(k0.scale, k1.scale, alpha),
            };
        }
    }

    fn find_keyframes<'a>(&self, keys: &'a [Keyframe], t: f32) -> (&'a Keyframe, &'a Keyframe, f32) {
        // 生产用 binary search,这里给线性版本清晰
        for i in 0..keys.len() - 1 {
            if keys[i].time <= t && t <= keys[i + 1].time {
                let span = (keys[i + 1].time - keys[i].time).max(1e-6);
                let alpha = (t - keys[i].time) / span;
                return (&keys[i], &keys[i + 1], alpha);
            }
        }
        let last = keys.len() - 1;
        (&keys[last], &keys[last], 0.0)
    }
}
```

**坑 1:循环边界**。`t.rem_euclid(self.duration)` 用 `rem_euclid` 不是 `%`,因为 Rust 的 `%` 对负数返回负数。**坑 2:zero-duration** guard 一下避免除零 NaN。**坑 3:空 track** fallback 到 identity。**坑 4:keyframe 数 < 2** 走边界分支。

### 2.3 Step 2:Blend(两个 pose 加权混合)

```rust
// src/anim/blend.rs
use crate::anim::pose::{Pose, Transform};

/// out = α * a + (1 - α) * b。α=0 完全 b,α=1 完全 a
pub fn blend_pose(out: &mut Pose, a: &Pose, b: &Pose, alpha: f32) {
    let n = out.joints.len();
    debug_assert_eq!(a.joints.len(), n);
    debug_assert_eq!(b.joints.len(), n);

    let alpha = alpha.clamp(0.0, 1.0);
    for i in 0..n {
        let ja = &a.joints[i];
        let jb = &b.joints[i];
        out.joints[i] = Transform {
            translation: lerp_vec3(jb.translation, ja.translation, alpha),
            rotation: slerp_quat(jb.rotation, ja.rotation, alpha),
            scale: lerp_vec3(jb.scale, ja.scale, alpha),
        };
    }
}

pub fn lerp_vec3(a: [f32; 3], b: [f32; 3], t: f32) -> [f32; 3] {
    [a[0]+(b[0]-a[0])*t, a[1]+(b[1]-a[1])*t, a[2]+(b[2]-a[2])*t]
}

/// 球面线性插值(quaternion),Shoemake 1985
pub fn slerp_quat(a: [f32; 4], b: [f32; 4], t: f32) -> [f32; 4] {
    let mut dot = a[0]*b[0] + a[1]*b[1] + a[2]*b[2] + a[3]*b[3];
    // 双覆盖:q 和 -q 同旋转,选短路径
    let b = if dot < 0.0 { [-b[0], -b[1], -b[2], -b[3]] } else { b };
    dot = dot.abs();

    // 几乎平行时退化为 NLERP,避免 sin(θ_0) ≈ 0 的数值不稳
    if dot > 0.9995 {
        let mut r = [
            a[0]+(b[0]-a[0])*t, a[1]+(b[1]-a[1])*t,
            a[2]+(b[2]-a[2])*t, a[3]+(b[3]-a[3])*t,
        ];
        let n = (r[0]*r[0]+r[1]*r[1]+r[2]*r[2]+r[3]*r[3]).sqrt().max(1e-12);
        for x in r.iter_mut() { *x /= n; }
        return r;
    }

    let theta_0 = dot.acos();
    let sin_theta_0 = theta_0.sin();
    let s0 = ((1.0 - t) * theta_0).sin() / sin_theta_0;
    let s1 = (theta_0 * t).sin() / sin_theta_0;
    [s0*a[0]+s1*b[0], s0*a[1]+s1*b[1], s0*a[2]+s1*b[2], s0*a[3]+s1*b[3]]
}
```

**坑 5:SLERP 的"双覆盖"陷阱**。四元数 q 和 -q 表示同一旋转,但 SLERP 在 q 和 -q 之间会绕远路(走 360° 而不是最近的 0°)。代码用 `dot < 0` 判断,如果夹角 > 90°(dot<0),negate q1 选短弧。**这一步忘了,blend 偶发性抽搐**——某时刻角度跳变。Skeletal-animation 那篇在 DQS 里也提过同样的 sign flip。

**坑 6:dot 接近 1 时,SLERP 数值不稳**。`acos(0.9995) ≈ 0.03` 弧度,`sin ≈ 0.03`,除法爆炸。dot > 0.9995 时退化到 NLERP。Shoemake 1985 论文就讨论了这点。

### 2.4 Step 3:Cross-fade(状态切换)

Cross-fade 是 blend 的一个应用:**在一段时间内,α 从 0 到 1 平滑变化**。

```rust
// src/anim/cross_fade.rs
use crate::anim::{blend::blend_pose, pose::Pose};

pub struct CrossFade {
    pub from: Pose,
    pub to: Pose,
    pub duration: f32,
    pub elapsed: f32,
}

impl CrossFade {
    pub fn new(from: Pose, to: Pose, duration: f32) -> Self {
        Self { from, to, duration, elapsed: 0.0 }
    }
    pub fn update(&mut self, dt: f32) { self.elapsed += dt; }
    pub fn is_done(&self) -> bool { self.elapsed >= self.duration }

    pub fn evaluate_into(&self, out: &mut Pose) {
        let alpha = if self.duration > 0.0 {
            (self.elapsed / self.duration).clamp(0.0, 1.0)
        } else { 1.0 };
        // smoothstep 让过渡更自然(线性 alpha 看起来机械)
        let alpha_eased = alpha * alpha * (3.0 - 2.0 * alpha);
        blend_pose(out, &self.to, &self.from, alpha_eased);
    }
}
```

**坑 7:线性 α 看起来"机械"**。alpha 线性从 0 到 1,开始和结束**速度突变**(导数不连续)。视觉上"啪"启动"啪"停。换成 smoothstep(`α² × (3-2α)`),导数在 0 和 1 处都是 0,平滑。

**坑 8:Cross-fade 的"from pose"是冻结的还是流动的**?**Frozen**(冻结):开始时 snapshot from,过渡期间 from 不变。简单,但玩家还在移动时看起来"卡"了一下。**Flowing**(流动):from 持续从原 clip 采样。自然,但要保存 state。工业级(Unreal、Unity)默认 flowing。

### 2.5 Step 4:1D Blend Tree(参数化混合)

walk 和 run 不是两个独立状态,而是同一个"move"动作的两个端点。**1D blend tree** 接受一个 speed 参数,在 walk 和 run 之间混合。

```rust
// src/anim/blend_tree.rs
use crate::anim::{clip::AnimationClip, pose::Pose};

pub struct BlendNode1D {
    pub speed_threshold: f32,
    pub clip: AnimationClip,
}

pub struct BlendTree1D {
    pub nodes: Vec<BlendNode1D>,    // 按 threshold 升序排好
    pub times: Vec<f32>,             // 每个 clip 的播放时间
}

impl BlendTree1D {
    pub fn evaluate_into(&mut self, out: &mut Pose, speed: f32, dt: f32) {
        assert!(self.nodes.len() >= 2);
        for t in self.times.iter_mut() { *t += dt; }

        let (i0, i1, alpha) = self.find_segment(speed);

        let mut pose_a = Pose::with_joint_count(out.joint_count());
        let mut pose_b = Pose::with_joint_count(out.joint_count());
        self.nodes[i0].clip.sample_into(&mut pose_a, self.times[i0]);
        self.nodes[i1].clip.sample_into(&mut pose_b, self.times[i1]);
        crate::anim::blend::blend_pose(out, &pose_a, &pose_b, alpha);
    }

    fn find_segment(&self, speed: f32) -> (usize, usize, f32) {
        if speed <= self.nodes[0].speed_threshold {
            return (0, 0, 0.0);
        }
        let last = self.nodes.len() - 1;
        if speed >= self.nodes[last].speed_threshold {
            return (last, last, 0.0);
        }
        for i in 0..last {
            let s0 = self.nodes[i].speed_threshold;
            let s1 = self.nodes[i + 1].speed_threshold;
            if s0 <= speed && speed <= s1 {
                let alpha = (speed - s0) / (s1 - s0).max(1e-6);
                return (i, i + 1, alpha);
            }
        }
        unreachable!()
    }
}
```

**坑 9:播放时间同步**。walk 1.0s 一周期,run 0.6s。如果各自独立播,blend 出来腿摆动周期会**错相**(左腿 walk 抬起时左腿 run 落下),视觉上"踩到自己的脚"。**周期同步**:把两 clip 时间归一化到 [0, 1) 的"周期相位",强制两 clip 用同一相位。详见 §8.2。

**坑 10:边界 blend 退化**。如果 speed 落在 segment 之外,要正确返回 `(last, last, 0)`——两个都是最后一个 node,blend 出来是最后一个 clip。如果不处理边界,`i + 1` 越界。

### 2.6 Step 5:2D Blend Tree(Locomotion)

加上"转向",参数变成 (speed, turn)。常用布局是 5 个 clip:idle、walk-forward、walk-left、walk-right、run-forward。2D locomotion 最常见的是 **barycentric blend**(三角剖分):

```
          walk-forward (s=2)
              /\
             /  \
            /    \
   walk-left──────walk-right
   (s=2,t=-1)    (s=2,t=+1)
            \    /
             \  /
              \/
            idle (s=0)
```

5 个 clip 排成两个三角形(上、下)。给定 (speed, turn),先判断在哪个三角形里,再用三角形的**重心坐标** barycentric 做 3 路 blend。

```rust
// src/anim/blend_tree_2d.rs
pub struct BlendNode2D {
    pub speed: f32,
    pub turn: f32,
    pub clip: AnimationClip,
}

pub struct BlendTree2D {
    pub triangles: Vec<[usize; 3]>,
    pub nodes: Vec<BlendNode2D>,
    pub times: Vec<f32>,
}

impl BlendTree2D {
    pub fn evaluate_into(&mut self, out: &mut Pose, speed: f32, turn: f32, dt: f32) {
        for t in self.times.iter_mut() { *t += dt; }
        let tri = self.find_triangle(speed, turn).unwrap_or(self.triangles[0]);
        let (w0, w1, w2) = barycentric(
            (self.nodes[tri[0]].speed, self.nodes[tri[0]].turn),
            (self.nodes[tri[1]].speed, self.nodes[tri[1]].turn),
            (self.nodes[tri[2]].speed, self.nodes[tri[2]].turn),
            (speed, turn),
        );

        let mut poses = [Pose::with_joint_count(out.joint_count()); 3];
        for (i, &ni) in tri.iter().enumerate() {
            self.nodes[ni].clip.sample_into(&mut poses[i], self.times[ni]);
        }
        crate::anim::blend::blend_pose_weighted(out, &poses, &[w0, w1, w2]);
    }

    fn find_triangle(&self, s: f32, t: f32) -> Option<[usize; 3]> {
        for &tri in &self.triangles {
            let (w0, w1, w2) = barycentric(
                (self.nodes[tri[0]].speed, self.nodes[tri[0]].turn),
                (self.nodes[tri[1]].speed, self.nodes[tri[1]].turn),
                (self.nodes[tri[2]].speed, self.nodes[tri[2]].turn),
                (s, t),
            );
            if w0 >= 0.0 && w1 >= 0.0 && w2 >= 0.0 {
                return Some(tri);
            }
        }
        None
    }
}

/// 重心坐标:把 P 表示为 A, B, C 的加权组合。返回 (w_A, w_B, w_C),和为 1
fn barycentric(a: (f32,f32), b: (f32,f32), c: (f32,f32), p: (f32,f32)) -> (f32, f32, f32) {
    let v0 = (b.0 - a.0, b.1 - a.1);
    let v1 = (c.0 - a.0, c.1 - a.1);
    let v2 = (p.0 - a.0, p.1 - a.1);
    let den = v0.0 * v1.1 - v1.0 * v0.1;
    if den.abs() < 1e-6 { return (1.0, 0.0, 0.0); }
    let inv = 1.0 / den;
    let w1 = (v2.0 * v1.1 - v1.0 * v2.1) * inv;
    let w2 = (v0.0 * v2.1 - v2.0 * v0.1) * inv;
    (1.0 - w1 - w2, w1, w2)
}
```

**坑 11:三角形朝向**。`den = v0.0*v1.1 - v1.0*v0.1` 是 2D 叉积。顺时针顶点顺序 den 是负,逆时针是正。**离线预处理:统一所有三角形为逆时针**。

**坑 12:凸包 vs 任意拓扑**。5 个 clip 排两个三角形容易,15 个 clip 自由分布需要 **Delaunay triangulation** 离线预处理。Rust crate `spade` 提供 Delaunay。

**坑 13:边界 clamp**。如果 (speed, turn) 在凸包外,所有三角形都不包含它。生产实现要**最近边投影**——clamp 到凸包边界。

### 2.7 Step 6:Additive Animation(叠加)

Additive 是动画系统的精髓——它解决了"组合爆炸"。base 跑步 + 任意 look delta = 跑步时朝任意方向看。

```rust
// src/anim/additive.rs
use crate::anim::pose::{Pose, Transform};

/// 把 additive delta 叠加到 base 上
pub fn apply_additive(out: &mut Pose, base: &Pose, additive: &Pose, alpha: f32) {
    let n = out.joints.len();
    for i in 0..n {
        let b = &base.joints[i];
        let d = &additive.joints[i];
        out.joints[i] = Transform {
            translation: [
                b.translation[0] + alpha * d.translation[0],
                b.translation[1] + alpha * d.translation[1],
                b.translation[2] + alpha * d.translation[2],
            ],
            rotation: quat_mul(b.rotation, quat_pow(d.rotation, alpha)),
            // scale:乘法群
            scale: [
                b.scale[0] * (1.0 + alpha * (d.scale[0] - 1.0)),
                b.scale[1] * (1.0 + alpha * (d.scale[1] - 1.0)),
                b.scale[2] * (1.0 + alpha * (d.scale[2] - 1.0)),
            ],
        };
    }
}

/// 把普通 clip 转成 additive delta(相对于 reference pose)
/// delta.translation = clip.translation - ref.translation
/// delta.rotation    = ref.rotation⁻¹ × clip.rotation   (SO(3) 的"差")
/// delta.scale       = clip.scale / ref.scale             (乘法群的"差")
pub fn make_additive(reference: &Pose, clip: &Pose) -> Pose {
    let mut out = Pose::with_joint_count(reference.joints.len());
    for i in 0..reference.joints.len() {
        let b = &reference.joints[i];
        let c = &clip.joints[i];
        out.joints[i] = Transform {
            translation: [
                c.translation[0] - b.translation[0],
                c.translation[1] - b.translation[1],
                c.translation[2] - b.translation[2],
            ],
            rotation: quat_mul(quat_inverse(b.rotation), c.rotation),
            scale: [
                c.scale[0] / b.scale[0].max(1e-6),
                c.scale[1] / b.scale[1].max(1e-6),
                c.scale[2] / b.scale[2].max(1e-6),
            ],
        };
    }
    out
}
```

**关键洞察:additive 不是"差"就是"积"**。translation 是向量空间,减法对。但 rotation 在 SO(3) 群上,**没有减法**,只能用群运算 `base⁻¹ × clip` 得到旋转 delta。scale 是乘法群,scale delta 是**商**,不是差。如果用错:scale=2.0 的 base 加上 delta=1.0 应该保持 2.0,但用减法 `delta = clip.scale - base.scale = -1`,叠加 `2 + (-1) = 1`,**漂移了**。

**坑 14:reference pose 选择**。reference 不是 bind pose,而是**"参考姿势"**(通常 stand_ready)。reference 选错(用 bind T-pose),additive 语义乱。Unreal 称 reference 为 "Base Pose",OZZ 称 "base layer"。

### 2.8 Step 7:Animation Layer(部位覆盖)

```rust
// src/anim/layer.rs
use crate::anim::pose::Pose;

/// 决定某个 joint 是否被当前 layer 影响
pub trait BlendMask {
    fn weight(&self, joint_index: usize) -> f32;
}

/// 简单的"按 joint 名字" mask
pub struct NameMask {
    pub joint_indices: Vec<usize>,   // 影响的 joint(预解析)
    pub weight: f32,
}

impl BlendMask for NameMask {
    fn weight(&self, joint_index: usize) -> f32 {
        if self.joint_indices.contains(&joint_index) { self.weight } else { 0.0 }
    }
}

/// 把 override 叠到 base 上,只覆盖 mask 指定的 joint
pub fn apply_layer(out: &mut Pose, base: &Pose, override_pose: &Pose, mask: &dyn BlendMask) {
    let n = out.joints.len();
    for i in 0..n {
        let w = mask.weight(i);
        if w >= 0.999 {
            out.joints[i] = override_pose.joints[i].clone();
        } else if w > 0.0 {
            crate::anim::blend::blend_joint(
                &mut out.joints[i], &base.joints[i], &override_pose.joints[i], w,
            );
        } else {
            out.joints[i] = base.joints[i].clone();
        }
    }
}
```

**坑 16:Joint 名字 vs joint index**。美术在 Blender 里命名("spine_01"),运行时是 index。`NameMask::joint_indices` 在**加载时**一次性解析名字→index,运行时不要做 string lookup。**坑 17:Mask 的"半权重 joint"**。joint A 在 mask 内(weight=1),子 joint B 在 mask 外(weight=0),B 的 local transform 来自 base,但 B 的 global(= global(A) × local(B))会让 B "跟随 A 然后突然转向"——视觉断裂。工业级方案是 **mask 平滑带**——从 mask 边界向外梯度衰减(羽化)。Unreal 的 "Layered Blend per Bone" 提供 `blend_depth` 参数控制衰减。

### 2.9 Step 8:Mini FSM

最后把以上所有东西串起来。最简单的 FSM:

```rust
// src/anim/fsm.rs
use crate::anim::{clip::AnimationClip, cross_fade::CrossFade, pose::Pose};

#[derive(Clone, Copy, PartialEq)]
pub enum AnimStateKind { Idle, Walk, Run, Jump }

pub struct AnimState {
    pub kind: AnimStateKind,
    pub clip: AnimationClip,
    pub time: f32,
}

pub struct Transition {
    pub from: AnimStateKind,
    pub to: AnimStateKind,
    pub condition: Box<dyn Fn(&Params) -> bool>,
    pub fade_duration: f32,
}

pub struct Params {
    pub speed: f32,
    pub is_grounded: bool,
}

pub struct AnimFSM {
    pub current: AnimState,
    pub transition: Option<CrossFade>,
    pub transitions: Vec<Transition>,
}

impl AnimFSM {
    pub fn update(&mut self, params: &Params, dt: f32, out: &mut Pose) {
        // 更新 transition
        if let Some(cf) = &mut self.transition {
            cf.update(dt);
            if cf.is_done() {
                self.transition = None;
            } else {
                cf.evaluate_into(out);
                return;
            }
        }
        // 更新当前 state 播放时间
        self.current.time += dt;
        // 检查 transitions
        for t in &self.transitions {
            if t.from == self.current.kind && (t.condition)(params) {
                let mut from_pose = Pose::with_joint_count(out.joint_count());
                self.current.clip.sample_into(&mut from_pose, self.current.time);
                self.current.kind = t.to;
                let to_pose = Pose::with_joint_count(out.joint_count());
                self.transition = Some(CrossFade::new(from_pose, to_pose, t.fade_duration));
                self.transition.as_mut().unwrap().evaluate_into(out);
                return;
            }
        }
        self.current.clip.sample_into(out, self.current.time);
    }
}
```

**坑 18:`Box<dyn Fn>` 的性能**。transition condition 用 trait object,每帧 N × M 次 dynamic dispatch。生产用 enum + match 替代。

**坑 19:transition 中途又触发 transition**。cross-fade 进行到一半,玩家又满足新 transition 条件怎么办?三种策略:**finish**(等当前 fade 完再触发)、**interrupt**(立刻切断,从当前 blended pose 开始新 fade)、**queue**(排队)。Unreal AnimBP 默认 interrupt。

至此 500 行 Rust 写完了一个 mini 动画系统,涵盖 sample / blend / cross-fade / 1D blend / 2D blend / additive / layer / FSM。


## 3 · 第一性原理:blend 权重的数学

这一节手推 blend 数学,你会看到为什么 translation 用 lerp,rotation 用 slerp,scale 用 lerp 但 additive 用商。

### 3.1 Translation 的 lerp

translation 是 R³ 向量空间。向量空间是**线性空间**——加法和数乘封闭,且满足 8 条公理。两个 translation a, b 的加权平均 `αa + (1-α)b` 仍然是合法 translation,α ∈ [0, 1] 时几何上是从 a 到 b 的直线段。这是 **convex combination**(凸组合)。

### 3.2 Rotation 的 SLERP:为什么不能 lerp

rotation 不是向量空间,是 **SO(3) 群**(special orthogonal 3D rotation group)。SO(3) 不是线性空间——你不能"加"两个旋转得到一个旋转(R1 + R2 在矩阵空间里仍然是矩阵,但**不一定是正交矩阵**)。

四元数是 SO(3) 的"双重覆盖"——每个 rotation 对应两个 ±q。四元数本身活在 S³ 球面(单位 4D 球面)。两个四元数 q0, q1 在 S³ 上的插值,不能用 lerp(lerp 走弦内直线,中间结果不在 S³ 上,长度不为 1,不是合法 rotation)。

**SLERP 推导**:我们要在 q0 和 q1 之间找一个 q(t),满足 q(0)=q0、q(1)=q1、q(t) 在 S³ 上、沿大圆(geodesic)匀角速。设 q(t) = a(t) q0 + b(t) q1。条件 |q(t)| = 1 展开成 `a² + b² + 2ab(q0·q1) = 1`。结合"绕 q0 旋转 tθ"约束解出:

```
a(t) = sin((1-t)θ) / sin(θ)
b(t) = sin(tθ) / sin(θ)
```

其中 θ = arccos(q0·q1)。这就是 §2.3 代码里的公式。**几何直觉**:SLERP 在 S³ 大圆上等角速运动,类比于 2D 圆上等角速弧升到 4D。**双覆盖问题**:q 和 -q 是同一旋转,但 q0·q1 可能是 ±cos(θ)。如果 dot < 0,SLERP 走长弧(>180°),我们 negate q1 选短弧。

### 3.3 Scale 的 lerp 和乘法群

scale 也是 R³ 中的向量,但**语义上是乘法**——scale=2 意思是"放大 2 倍",不是"加 2"。但 lerp 在 scale 上仍工作,因为 {(x,y,z) : x>0, y>0, z>0} 对 lerp 封闭(两个正数的凸组合是正数),视觉上平滑。

但 **additive 的 scale 不是 lerp**。base scale=2.0,delta scale="放大 1.5 倍",叠加应该得到 3.0。加法 `2.0 + 1.5 = 3.5` 错;乘法 `2.0 × 1.5 = 3.0` 对。所以 §2.7 `make_additive` 算 `clip.scale / base.scale`(商),`apply_additive` 用 `base.scale × delta ^ α`。

### 3.4 加权混合:slerp 推广不到 N 路

二路 blend 用 slerp 很美。但 N 路(N > 2)怎么办?

最简单扩展:**slerp(a, b, t) 二分法嵌套**——slerp(slerp(a, b, t1), c, t2)。但这不**对称**——结果依赖嵌套顺序。

工业级方案:**NLERP(NLERP)**——每分量 lerp + normalize:

```
q_blend = (w0 q0 + w1 q1 + ... + wn qn) / |w0 q0 + w1 q1 + ... + wn qn|
```

wi 是权重(和为 1)。NLERP 不是匀角速——两个 quat 之间距离短的"快走",距离长的"慢走"。视觉上几乎看不出来,工业普遍接受。

对**精确匀角速**有 SLERP 的 N 路推广,叫 **Squad**(spherical quadrangle,Shoemake 1987)。但 Squad 只支持 4 路,数学复杂,工业很少用。Unreal 用 NLERP。

## 4 · IK:从端点反推关节

正向运动学(FK):给定 joint 角度,算末端位置。这是 skeletal-animation 那篇做的。**逆向运动学(IK)**反过来——给定末端位置(target),算 joint 角度。

为什么需要 IK?因为动画师录的 clip 是"通用姿势",但游戏运行时**末端需要精确**:脚要踩在斜坡上(不是悬空)、手要抓门把手(不是穿过)、头要朝玩家(视线对准)。这些 target 是 runtime 决定的,clip 录制时不知道。所以需要"反推"。

我们推三个算法:**CCD**(迭代)、**FABRIK**(迭代,更快)、**Two-Bone IK**(解析,2-bone 链专用)。

### 4.1 CCD(Cyclic Coordinate Descent)

**问题**:N 个 joint 串联成链 `joint_0 → ... → joint_{N-1}`,每个 joint 一个旋转自由度 θ_i。末端 effector 是 joint_{N-1} 的端点。给定 target T,求 θ_i 让 effector 到 T。

**CCD 思路**:从链的末端往前迭代,每次只调一个 joint 的 θ_i,让"从 joint_i 看 effector 的方向"对齐"从 joint_i 看 target 的方向"。

**完整推导**(2D 版,3D 类比):设 joint_i 在 world-space 位置 p_i(由 joint_0..i-1 的 θ 决定)。effector e = p_{N-1}。target T。每次迭代:

```
for i from N-2 down to 0:    # 从靠近 effector 的 joint 开始
    v_e = e - p_i
    v_t = T - p_i
    angle_delta = atan2(cross(v_e, v_t), dot(v_e, v_t))
    θ_i += angle_delta
    recompute_positions()    # downstream joint 全部重算
```

重复 5-20 次迭代通常收敛。**为什么从末端开始**?调整末端 joint 影响 effector 最大,先把它尽量对准 target,再调前面 joint 推 effector 到 target。

**Rust 实现**(2D 简化):

```rust
// src/anim/ik/ccd.rs
#[derive(Clone, Debug)]
pub struct CcdJoint {
    pub position: [f32; 2],     // world-space,初始
    pub angle: f32,
}

pub fn solve_ccd(joints: &mut [CcdJoint], target: [f32; 2], iterations: usize) {
    let n = joints.len();
    if n < 2 { return; }
    for _ in 0..iterations {
        for i in (0..n - 1).rev() {
            let p_i = current_position(joints, i);
            let e = current_position(joints, n - 1);
            let v_e = [e[0] - p_i[0], e[1] - p_i[1]];
            let v_t = [target[0] - p_i[0], target[1] - p_i[1]];
            let cross = v_e[0] * v_t[1] - v_e[1] * v_t[0];
            let dot = v_e[0] * v_t[0] + v_e[1] * v_t[1];
            joints[i].angle += cross.atan2(dot);
        }
    }
}

fn current_position(joints: &[CcdJoint], i: usize) -> [f32; 2] {
    let mut pos = [0.0, 0.0];
    let mut acc_angle = 0.0;
    for j in 0..=i {
        acc_angle += joints[j].angle;
        let bone_len = if j + 1 < joints.len() {
            let dx = joints[j+1].position[0] - joints[j].position[0];
            let dy = joints[j+1].position[1] - joints[j].position[1];
            (dx*dx + dy*dy).sqrt()
        } else { 0.0 };
        pos[0] += bone_len * acc_angle.cos();
        pos[1] += bone_len * acc_angle.sin();
    }
    pos
}
```

**坑 20:CCD 收敛但抖动**。每步可能 overshoot。**改进**:加 damping,每步只应用 delta 的一部分。**坑 21:joint 角度限制**。人肘只能往一个方向弯。CCD 不加约束会"反弯肘"。**修复**:每次更新后 clamp θ_i 到 [-limit, +limit]。**性能**:O(N),N=10 的链 10 次迭代共 100 次操作,完全可以承担。

### 4.2 FABRIK(Forward And Backward Reaching Inverse Kinematics)

FABRIK(Aristidou et al. 2011)比 CCD **更快、更稳定、视觉更平滑**。工业 IK 的主力。

**核心思路**:不操作 angle,直接操作 joint 位置。两阶段循环:

1. **Backward pass**:从 effector 往 root,把每个 joint "拉到" target 附近。
2. **Forward pass**:从 root 往 effector,把每个 joint "拉回" root 附近(backward 破坏了 root 位置)。
3. 重复直到收敛。

**完整推导**:设 joint 初始位置 p_0..p_{N-1}。bone i 长度 `d_i = |p_{i+1} - p_i|`(常数)。

**Backward**:
```
p_{N-1} := T
for i from N-2 down to 0:
    direction = (p_i - p_{i+1}).normalize()
    p_i := p_{i+1} + direction * d_i
```

effector 在 target 上了,但 root 偏离原位。**Forward**:
```
p_0 := root_original
for i from 1 to N-1:
    direction = (p_i - p_{i-1}).normalize()
    p_i := p_{i-1} + direction * d_i
```

root 回原位,但 effector 可能偏离 target。重复 backward + forward,每次迭代**误差减半**(linear convergence),5-10 次迭代达到亚毫米精度。

**Rust 实现**:

```rust
// src/anim/ik/fabrik.rs
pub fn solve_fabrik(
    positions: &mut Vec<[f32; 3]>,
    root: [f32; 3], target: [f32; 3], iterations: usize,
) {
    let n = positions.len();
    if n < 2 { return; }
    let bone_lengths: Vec<f32> = (0..n-1)
        .map(|i| vec3_dist(positions[i], positions[i+1])).collect();
    let total_len: f32 = bone_lengths.iter().sum();

    // 不可达:拉伸到最大
    if vec3_dist(root, target) > total_len {
        let dir = vec3_normalize([target[0]-root[0], target[1]-root[1], target[2]-root[2]]);
        let mut acc = root;
        positions[0] = root;
        for i in 0..n-1 {
            acc[0] += dir[0] * bone_lengths[i];
            acc[1] += dir[1] * bone_lengths[i];
            acc[2] += dir[2] * bone_lengths[i];
            positions[i+1] = acc;
        }
        return;
    }

    let mut new_pos = positions.clone();
    for _ in 0..iterations {
        // Backward
        new_pos[n-1] = target;
        for i in (0..n-1).rev() {
            let dir = vec3_normalize([
                new_pos[i][0] - new_pos[i+1][0],
                new_pos[i][1] - new_pos[i+1][1],
                new_pos[i][2] - new_pos[i+1][2],
            ]);
            new_pos[i] = [
                new_pos[i+1][0] + dir[0] * bone_lengths[i],
                new_pos[i+1][1] + dir[1] * bone_lengths[i],
                new_pos[i+1][2] + dir[2] * bone_lengths[i],
            ];
        }
        // Forward
        new_pos[0] = root;
        for i in 0..n-1 {
            let dir = vec3_normalize([
                new_pos[i+1][0] - new_pos[i][0],
                new_pos[i+1][1] - new_pos[i][1],
                new_pos[i+1][2] - new_pos[i][2],
            ]);
            new_pos[i+1] = [
                new_pos[i][0] + dir[0] * bone_lengths[i],
                new_pos[i][1] + dir[1] * bone_lengths[i],
                new_pos[i][2] + dir[2] * bone_lengths[i],
            ];
        }
        if vec3_dist(new_pos[n-1], target) < 1e-4 { break; }
    }
    *positions = new_pos;
}

fn vec3_dist(a: [f32; 3], b: [f32; 3]) -> f32 {
    let d = [a[0]-b[0], a[1]-b[1], a[2]-b[2]];
    (d[0]*d[0] + d[1]*d[1] + d[2]*d[2]).sqrt()
}
fn vec3_normalize(v: [f32; 3]) -> [f32; 3] {
    let n = vec3_dist(v, [0.0; 3]).max(1e-12);
    [v[0]/n, v[1]/n, v[2]/n]
}
```

**坑 22:不可达情况**。target 距离 > 链总长,backward + forward 永远收敛不了。guard:直接拉伸到最大(朝 target 方向伸到 max)。**坑 23:joint constraint**。FABRIK 默认每个 joint 是球关节(3 DOF 无限制)。加 cone / ellipsoid 约束需要 extension。**生产 hack**:先 FABRIK 再 clamp 角度。

**性能**:FABRIK 单次迭代 O(N),N=10 大约 200 次操作,10 次迭代 2000 次。**比 CCD 快 2-3 倍**,因为不需要每次迭代后重算 FK。

### 4.3 Two-Bone IK(解析解,2-bone 链)

人腿和人臂都是"3 个 joint,2 根 bone"的链(shoulder → elbow → wrist,或 hip → knee → ankle)。这种简单结构有**解析解**(closed-form)。Two-Bone IK 是工业 IK 的最常用形态——Unreal `FAnimNode_TwoBoneIK`、Unity `Animator.IK` 都基于它。

**完整推导**(3D):设 root = shoulder/hip 位置(固定)、mid = elbow/knee(待求)、end = wrist/ankle(待求,接近 target)、target(给定)、pole(极向量,给定,决定 mid 在哪个方向)。bone 长度 `len_a = |mid - root|`、`len_b = |end - mid|`,求 `L = |target - root|`。

**用余弦定理算 mid**:考虑三角形 (root, mid, target)。已知三边长 len_a, len_b, L(期望 end = target,把 end 视作 target)。**关键洞察**:mid 在 root-target 连线的某个垂直平面里,具体在哪个平面由 pole vector 决定。

```
cos_angle_at_root = (len_a² + L² - len_b²) / (2 × len_a × L)
angle_at_root = acos(clamp(cos_angle_at_root, -1, 1))
dir_root_to_target = normalize(target - root)
axis = normalize(cross(dir_root_to_target, pole - root))
mid = root + len_a × rotate(dir_root_to_target, by angle_at_root around axis)
```

**为什么需要 pole**:triangle (root, mid, target) 在 3D 里**有无限个解**——mid 可以绕 root-target 轴旋转一周,每个角度都是一个解。pole 决定"mid 在哪一侧"——膝盖朝前还是朝后。**没有 pole,IK 解不唯一**。这是新手 IK 写不对的最常见原因。

**完整 Rust 实现**:

```rust
// src/anim/ik/two_bone.rs
pub struct TwoBoneIkInput {
    pub root: [f32; 3], pub mid: [f32; 3], pub end: [f32; 3],
    pub target: [f32; 3], pub pole: [f32; 3],
    pub soften: f32,            // 0..1,边缘软化
}

pub fn solve_two_bone(input: &TwoBoneIkInput) -> ([f32; 3], [f32; 3]) {
    let len_a = vec3_dist(input.root, input.mid);
    let len_b = vec3_dist(input.mid, input.end);
    if len_a < 1e-6 || len_b < 1e-6 { return (input.mid, input.target); }

    let max_len = len_a + len_b;
    let stretchable_len = max_len * (1.0 - input.soften);
    let dist = vec3_dist(input.root, input.target).min(stretchable_len);

    let cos_at_root = (len_a*len_a + dist*dist - len_b*len_b) / (2.0 * len_a * dist);
    let angle_at_root = cos_at_root.clamp(-1.0, 1.0).acos();

    let dir_root_to_target = vec3_normalize([
        input.target[0] - input.root[0],
        input.target[1] - input.root[1],
        input.target[2] - input.root[2],
    ]);
    let pole_vec = [
        input.pole[0] - input.root[0],
        input.pole[1] - input.root[1],
        input.pole[2] - input.root[2],
    ];
    let axis = vec3_normalize(vec3_cross(dir_root_to_target, pole_vec));
    let rotated = rotate_around_axis(dir_root_to_target, axis, angle_at_root);
    let new_mid = [
        input.root[0] + len_a * rotated[0],
        input.root[1] + len_a * rotated[1],
        input.root[2] + len_a * rotated[2],
    ];
    let dir_mid_to_target = vec3_normalize([
        input.target[0] - new_mid[0],
        input.target[1] - new_mid[1],
        input.target[2] - new_mid[2],
    ]);
    let new_end = [
        new_mid[0] + len_b * dir_mid_to_target[0],
        new_mid[1] + len_b * dir_mid_to_target[1],
        new_mid[2] + len_b * dir_mid_to_target[2],
    ];
    (new_mid, new_end)
}

/// Rodrigues 公式:v' = v cos(θ) + (k × v) sin(θ) + k(k·v)(1-cos(θ))
fn rotate_around_axis(v: [f32; 3], axis: [f32; 3], angle: f32) -> [f32; 3] {
    let (cos, sin) = (angle.cos(), angle.sin());
    let cross = vec3_cross(axis, v);
    let dot = axis[0]*v[0] + axis[1]*v[1] + axis[2]*v[2];
    let omc = 1.0 - cos;
    [
        v[0]*cos + cross[0]*sin + axis[0]*dot*omc,
        v[1]*cos + cross[1]*sin + axis[1]*dot*omc,
        v[2]*cos + cross[2]*sin + axis[2]*dot*omc,
    ]
}

fn vec3_cross(a: [f32; 3], b: [f32; 3]) -> [f32; 3] {
    [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
}
```

**坑 24:soften 参数**。当 dist 接近 max_len(链几乎伸直),cos 接近 1,acos 在 1 附近**导数无限**(数值不稳)。soften 把 dist clamp 到 (1-ε) × max_len。**Unreal 默认 soften = 0.1**。**坑 25:pole 语义**。pole 可位置(world-space)或方向(model-space)。Unreal 用位置,Unity 用位置 + 方向。**坑 26:target 不可达时的 stretch**。target 比 max_len 远时,要么"伸长 bone"(stretch)、要么"clamp 到 max_len 伸直"。Unreal `Stretch` 参数控制。

### 4.4 三种 IK 算法对比

| 算法 | DOF | 速度 | 精度 | Constraint 支持 | 用途 |
|---|---|---|---|---|---|
| CCD | N-joint 链 | 慢(迭代 10-20) | 收敛但可能抖 | 加 angle limit | 长链(tail / tentacle / 蜈蚣腿) |
| FABRIK | N-joint 链 | 中(迭代 5-10) | 高 | 难(需 extension) | 中长链(spine / finger) |
| Two-Bone IK | 固定 3 joint | 极快(解析) | 精确 | 简单(angle + pole) | 肢体(arm / leg) |
| Jacobian transpose | N-joint | 慢(矩阵求逆) | 高 | 容易 | 机器人学,工业 IK |
| DLS / Levenberg-Marquardt | N-joint | 极慢 | 极高 | 容易 | 离线工具(Maya IK) |

游戏 runtime 99% 用 Two-Bone IK + FABRIK(分别处理肢体和长链)。CCD 在某些 indie 引擎用,Jacobian 系列在机器人 / 离线工具用。

## 5 · 真实引擎源码级参考

### 5.1 Unreal Engine 5 AnimBP

Unreal 是工业级动画系统的金标准。源码在 https://github.com/EpicGames/UnrealEngine(需登录)。核心概念:

- **AnimBP(Animation Blueprint)**:HFSM。状态机节点 `AnimNodes/AnimNode_StateMachine.h`。
- **AnimNode_BlendSpace**:2D / 3D blend tree。
- **AnimNode_TwoBoneIK**:`AnimNodes/AnimNode_TwoBoneIK.cpp` 第 30 行 `EvaluateSkeletalControl_AnyThread` → 调用 `AnimationCore::SolveTwoBoneIK`,实现就是 §4.3 那一套。
- **AnimGraphRuntime** module:所有运行时节点在 `Source/Runtime/AnimGraphRuntime/Private/AnimNodes/`。

Unreal 的特殊设计:Animation system 跑在 **Worker Thread**(多线程),通过 `FAnimInstanceProxy` 同步。单角色 ~5μs,100 个角色并行 5ms,充分利用多核。

### 5.2 Unity Animator / Playables

Unity 的 Animator 是 C# 闭源 + C++ native backend。DOTS 版本源码公开:https://github.com/Unity-Technologies/EntityComponentSystemSamples/tree/master/Animation。核心数据结构是 **AnimationClip / AnimatorState / AnimatorController**(`AnimatorController` 是 HFSM)。IK 通过 `OnAnimatorIK()` 回调暴露,在 MonoBehaviour 里 `Animator.SetIKPosition(AvatarIKGoal.LeftFoot, target)`。

### 5.3 Godot AnimationTree

完全开源:https://github.com/godotengine/godot/blob/master/scene/animation/animation_tree.cpp。

```
scene/animation/animation_tree.cpp (Godot 4.x)
  Line 50:  void AnimationTree::_process(float p_delta) {
  Line 65:      // 从 root node 递归求值
  Line 200: void AnimationRootNode::_bind_methods() { ... }
```

节点类型:`AnimationNodeAnimation`(单 clip)、`AnimationNodeBlendSpace1D/2D`、`AnimationNodeBlendTree`、`AnimationNodeStateMachine`、`AnimationNodeAdd2/Add3`(additive)、`AnimationNodeOneShot`。打开 `animation_blend_space_2d.cpp` 第 280 行 `_process`,逻辑跟 §2.6 一样——Delaunay 三角剖分 + barycentric。

### 5.4 Bevy `bevy_animation`

仓库:https://github.com/bevyengine/bevy/tree/main/crates/bevy_animation

- `crates/bevy_animation/src/lib.rs` — AnimationPlayer + AnimationClip
- `crates/bevy_animation/src/graph.rs` — AnimationGraph(blend tree),用 petgraph 存储
- `crates/bevy_animation/src/transition.rs` — AnimationTransitions(cross-fade)

打开 `graph.rs`(Bevy 0.14):

```
crates/bevy_animation/src/graph.rs
  Line 80:  pub struct AnimationGraph {
  Line 85:      pub nodes: petgraph::stable_graph::StableGraph<Node, (), Directed, u32>,
  Line 150: pub enum Node { Clip(..), Blend(..), Add(..), Override(..), ... }
```

`transition.rs` 第 30 行的 `AnimationTransitions::play` 和 `tick` 跟我们的 `CrossFade` 一对一。Bevy 的状态机目前(0.14)还在开发中,issue #11232 跟踪。

### 5.5 OZZ(参考 C++ 工业)

仓库:https://github.com/ozz-animation/ozz-animation。Ubisoft 开源的"低层动画 runtime",没有 state machine、没有 blend tree UI,但提供高性能 primitive。

- `src/animation/runtime/blending_job.cc` — N 路 blend
- `src/animation/runtime/sampling_job.cc` — clip 采样
- `src/animation/runtime/ik_two_bone_job.cc` 第 60 行 `IKTwoBoneJob::Run` — Two-Bone IK 实现
- `include/ozz/animation/runtime/ik_aim_job.h` — Aim IK(单 joint 朝 target)

跟 §4.3 推导完全一致——OZZ 是教科书级参考实现。

## 6 · 历史演化:从木偶到神经动画

- **1970s**:每关键帧手画,无混合。LucasArts《Day of the Tentacle》(1993)仍这样。
- **1995**:《Super Mario 64》首次大规模用 cross-fade。
- **1999**:Sega《Shenmue》首次提出 blend tree。
- **2003**:Unreal Engine 2 引入 AnimTree,3D blend tree 工业化。
- **2009**:Unity Mecanim(后改名 Animator)。
- **2014**:Unreal Engine 4 AnimBP,HFSM + blend tree 完整化。
- **2016**:Ubisoft《For Honor》首次大规模用 Motion Matching(论文 2018 发布)。
- **2017**:Godot 引入 AnimationTree。
- **2020**:Naughty Dog《最后生还者 2》Motion Matching 登峰造极。
- **2022**:Bevy 0.10 引入 AnimationGraph。
- **2024**:Motion Matching 在 mid-tier 引擎(Godot 4.x、Defold)逐步普及。

**当前格局**:传统 blend tree 仍是 indie / 中型项目主流,Motion Matching 在 AAA 大厂普及,神经动画还在研究阶段。

## 7 · 性能数据

把动画系统的每一步 cycle / ms / byte 数字列出来,你才能 budget。

| 操作 | cycle / 元素 | ms (1 角色, 64 joint) | 备注 |
|---|---|---|---|
| Sample clip (1 joint) | 80 cycle | 0.005 ms (64 joint) | OZZ sampling_job |
| Blend (1 joint) | 60 cycle | 0.004 ms (64 joint) | OZZ blending_job |
| Cross-fade (1 frame) | 80 cycle | 0.005 ms | blend + 一个额外 sample |
| 1D blend tree (2 路) | 200 cycle | 0.013 ms | 2 sample + 1 blend |
| 2D blend tree (3 路) | 300 cycle | 0.019 ms | 3 sample + 1 weighted blend |
| Additive apply (1 joint) | 70 cycle | 0.005 ms | quat_mul + add |
| Layer apply (1 joint) | 50 cycle | 0.003 ms | blend with mask |
| Two-Bone IK | 1500 cycle | 0.0005 ms | 解析,1 IK |
| FABRIK (5 iter, 10 joint) | 10000 cycle | 0.003 ms | 迭代 |
| FK (skeletal 的) | 50 cycle | 0.003 ms | 64 joint |

**1 帧动画总预算**(64-joint 角色):

```
1 个 clip sample:        0.005 ms
1 次 blend (cross-fade):  0.004 ms
1 次 additive:           0.005 ms
1 次 layer:              0.003 ms
2 个 Two-Bone IK:        0.001 ms
1 次 FK:                 0.003 ms
─────────────────────────────────
总计:                    0.021 ms
```

**100 个角色并行**:2.1 ms。完全在 60 FPS 预算(16.6 ms)内。

**字节统计**(64-joint 角色):
- Pose buffer(运行时):64 × 40B (3+4+3 floats × 4B + padding) = **2.5 KB**
- AnimationClip(原始):64 joint × 30 frame × 3 channel × 16B = 90 KB(1 秒)
- AnimationClip(压缩):约 18 KB(80% 压缩,见 §11)
- Blend mask:64 × 1B(每 joint 1 byte weight)= 64 B

**100 个角色**:100 × (2.5 KB pose buffer + 90 KB clip shared) = 大约 100 MB clip 数据 + 250 KB pose buffer。clip 数据是瓶颈——所以 §11 动画压缩非常重要。

## 8 · 生产坑 + 调试叙事

### 8.1 坑 A:Cross-fade 看起来"鬼畜"

**现象**:从 idle 切到 walk,角色上半身"咔咔"抽搐,然后才平滑。

**诊断**:cross-fade 的 from pose 是 frozen 的(见 §2.4 坑 8)。frozen 的 idle 在 T-pose 边界附近,cross-fade 期间 from "凝固",但 to 是 walk 在动,blend 时上半身不动 + 下半身在走 → 视觉上"上不动下动"很怪。

**修复**:frozen → flowing。CrossFade 保存的不是 pose snapshot,而是"clip 引用 + 当前时间"。每帧 update 时从两个 clip 各自 sample 然后 blend。多了一次 sample,但视觉自然。

### 8.2 坑 B:Blend tree 在 50% speed 时"腿打架"

**现象**:walk + run 在 speed=2.5(50%)时,左腿 walk 抬起同时左腿 run 落下,blend 出来左腿"上下各一下"。

**诊断**:walk 周期 1.0s,run 周期 0.6s。两 clip 独立播放,t=0.5 时 walk 周期相位 0.5(右腿抬起),run 周期相位 0.83(左腿刚落下)。**相位错位**。

**修复**:周期同步。统一时间归一化为 [0, 1) 相位,强制两 clip 用同一相位:

```rust
let phase = (self.global_time % 1.0).abs();
let t_walk = phase * self.nodes[0].clip.duration;
let t_run = phase * self.nodes[1].clip.duration;
```

**关键**:两 clip 的"事件对齐"(左脚着地时刻)需要美术在录制时对齐——Maya / MotionBuilder 有 "timeline align" 工具。如果不对齐,周期同步也没用。

### 8.3 坑 C:IK 让脚"穿过"地面

**现象**:角色站在斜坡上,脚 IK 到斜坡接触点,但某些角度下脚"穿过"地面。

**诊断**:IK target 在斜坡上,但 IK 算出的脚踝位置在斜坡内部(因为角色 root 还在水平地面,链不够长)。

**修复**:多层 IK:1) 先把 root 上抬(调整 root height 让链可达);2) 跑 Two-Bone IK;3) 跑"脚跟贴地"single-joint IK(只旋转 ankle 让脚跟朝向地面法线)。这是《最后生还者》的"foot planting"系统。完整版还要"步幅预测"——根据预测 root 未来几帧的轨迹,提前选落脚点。这就接近 Motion Matching 了。

### 8.4 坑 D:Additive 在某些姿态下"扭曲"

**现象**:base 跑步 + look delta(头部扭向左),某些 base 帧时角色头部"突然抽一下"。

**诊断**:additive delta 是相对于参考姿势算的。但 base clip 在不同帧,某些 joint 已经偏离参考姿势很远——additive delta 是"局部旋转",叠加到 base 上时,如果 base 已经在极限姿态,叠加 delta 后超过 joint 限制,出现"反弹"。

**修复**:不是所有 joint 都适合 additive。**只对 spherical joint(球关节,如 neck)用 additive**,对 hinge joint(铰链关节,如 elbow)避免。美术需要明白哪些 joint 适合 additive 录制。

### 8.5 坑 E:状态切换时的"动画缓存泄漏"

**现象**:角色从 Walk 切到 Run 再切回 Walk,Walk 播放时间不连续——从 0.5s 跳到 0.0s。

**诊断**:每个 AnimState 实例化时 `time = 0`。切换时新 state 从 0 开始播。

**修复**:state 持久化。每个 state 在 FSM 实例化时**预创建**,切换时只切 active 标志,time 持续累积(即便不 active)。但这又有问题:中间流逝时间可能让 clip "快进"很多。**真正的工业方案**:**phase sync**——Walk 和 Run 共享一个全局 phase 时间,切换时根据 phase 反算 clip 内时间。这跟坑 B 的周期同步是一回事。

## 9 · Motion Matching 简介

Motion Matching 是 2016 年后逐渐取代传统 blend tree 的新方法。简单介绍,深度留给未来 deep-dive。

### 9.1 核心思路

把所有动画数据"碎成"1 帧一片。每帧记录 **Pose**(所有 joint 的 local transform)、**Trajectory**(未来 0.5s/1.0s/1.5s 的 root 位置和方向)、**Foot contact**(左右脚是否着地)、**Tags**(攻击 / 防御 / 受伤)。运行时每帧:

1. 从输入设备读"期望未来 0.5s 的 trajectory"。
2. 在数据库里搜"特征最接近的下一帧"。
3. 跳到那一帧,继续播。
4. Cross-fade 5-10 帧抹平跳跃。

### 9.2 优点

- **无需 blend tree**:不用美术调"5 个 clip 在 2D 空间如何分布"
- **无需 transition 规则**:数据库自动找最佳下一帧
- **更自然**:每帧都是真实 mocap,没有 blend 产生的"中间姿势"
- **响应快**:输入变化立刻响应(下一帧就跳)

### 9.3 缺点

- **数据量大**:5 分钟 mocap × 30 fps = 9000 帧 × 几 KB/帧 = 几十 MB
- **响应"过快"**:输入抖动会让动画"飘"——需要输入滤波
- **不适合特定动作**:精确攻击、特定时机还是 state machine 更可控
- **搜索昂贵**:每帧 KD-tree 搜索几微秒,100 个角色并行吃力

### 9.4 工业实践

**Hybrid**:Motion Matching 做 locomotion(走 / 跑),state machine 做动作(攻击 / 受伤 / 死亡)。这是《最后生还者 2》《战神》《Control》的方案。Rust crate `bevy_motion_match`(https://github.com/jay2606/bevy_motion_match)是 Bevy 的 Motion Matching 实验。

## 10 · 动画压缩

动画数据是仓库体积大头。一个角色 30 个 clip × 5 秒 × 30 fps × 64 joint × 3 channel × 16B = 13 MB。压缩到 2-3 MB 是常规目标。OZZ、Unreal、Unity 都内置压缩。

### 10.1 三种压缩技术

**1. Keyframe reduction(关键帧减少)**:不是每帧都存,只存"对插值曲线重要的帧"。Catmull-Rom 样条拟合 + 误差阈值,丢掉误差小的中间帧。压缩比 3-5x。

**2. Quantization(量化)**:32-bit float → 16-bit。translation 量化到 1mm 精度,rotation 用三字节 quaternion(每分量 8 bit),scale 一般不存(默认 1.0)。压缩比 2x。

**3. Track deduplication**:多个 clip 共享相同 track(idle 的所有 joint 不动,只存 root)。压缩比 1.5x。

### 10.2 OZZ 的压缩

OZZ 用 **track range + quantization**:每条 track 记录 [min, max],每个值用 16 bit 量化到这个范围,加上 keyframe reduction。总压缩比 5-10x。256-joint 角色的 5 秒 clip:720 KB 压到 80 KB。源码:`src/animation/offline/optimize.cc`(主入口)、`decimate.h`(keyframe reduction)、`track.cc`(keyframe 存储)。

### 10.3 不要做的事

- **不要量化 quaternion 的 w 分量**:从 xyz 重建 `w = sqrt(1 - x² - y² - z²)`,但符号丢失——q 和 -q 不同。**解决**:存 xyz + sign bit。
- **不要在 runtime 解压**:解压在加载时做,runtime 用的 pose 是全精度。
- **不要给每帧存 bind pose offset**:bind pose 是常数,存一次。

## 11 · 跨学科联结

**机器人学**:IK 不是游戏发明的。1960s 机器人学就在做 6-DOF 机械臂的 IK。Denavit-Hartenberg 参数、Jacobian matrix、Manipulability ellipsoid 都是机器人学概念。游戏 IK 容忍误差(脚差 5cm 看不出),机器人需要精确(否则机械手抓不到零件)。游戏 IK 用迭代近似,机器人用解析 + 数值混合。参考:Springer《Robotics: Modelling, Planning and Control》(Siciliano) 第 4 章。

**控制论和状态机**:FSM 是控制论经典抽象。Wiener 1948《Cybernetics》定义"控制论"为"动物和机器的控制与通信"。游戏 FSM 和数字电路 FSM 是同一个数学对象(`(S, Σ, δ, s_0, F)` 五元组)。区别是游戏 FSM 软实时(可偶尔卡),数字电路 FSM 硬实时(必须按时钟周期完成)。

**生物力学**:人形动画的 joint 限制来自生物力学。肘只能弯 ~145°(active extension),肩能三轴旋转但有限制,膝盖只能屈伸(1 DOF)。建模师不遵守这些限制,动画就"反人类"。运动科学的"步态分析"(gait analysis)研究真实人走路模式,是 locomotion 动画的科学基础。mocap 数据本质就是采集的真实步态。

**信息论**:动画压缩跟信息论紧密关联。Shannon 的率失真理论(rate-distortion theory)告诉我们:在允许的最大误差 ε 下,信号至少需要多少 bit 编码。这就是量化背后的数学。参考:Cover & Thomas《Elements of Information Theory》第 13 章。

## 12 · 开源贡献机会

**Bevy animation graph**:https://github.com/bevyengine/bevy/issues 找标了 `A-Animation` 的 issue。可贡献方向:Animation State Machine(目前 Bevy 没内置,issue #11232 跟踪)、2D Blend Space(目前只有 1D)、Additive blending API(目前不完整)、Animation compression(目前 Bevy 不压缩)。

**Godot AnimationTree**:https://github.com/godotengine/godot/blob/master/scene/animation/。可贡献:Motion Matching 节点(Godot 4.x 还没内置)、State machine transition 的 "interrupt" 模式(目前只支持 finish)、IK 节点的 pole vector 改进。

**OZZ Rust binding**:`ozz-animation-rs` 维护不活跃。可贡献:Rust 原生的 OZZ 等价实现、Bevy 后端的 OZZ integration。

**独立 crate**:Rust 生态缺少专门的 animation state machine crate。你可以做一个 HFSM + 数据驱动(从 glTF 或 .anim.ron 加载)+ Bevy integration 的 crate。

## 13 · 在你 HH 项目里实践

具体到你的 Handmade Hero Rust 项目,要落地动画系统,改哪些文件。

### 13.1 加新文件

在你的 `src/animation/` 目录(或对应目录)新建:`pose.rs`、`blend.rs`、`cross_fade.rs`、`blend_tree.rs`、`additive.rs`、`layer.rs`、`fsm.rs`,以及 `ik/` 子模块(`two_bone.rs` / `fabrik.rs` / `ccd.rs`)。这些都对应 §2 和 §4 的代码。

### 13.2 HH 主角的 walk → run 系统

最简化的实战:HH 主角根据键盘 W 按住时间(代表摇杆推力)在 idle → walk → run 之间切换。

```rust
// src/game/player_anim.rs
use crate::animation::{pose::Pose, blend_tree::BlendTree1D};

pub struct PlayerAnim {
    pub blend_tree: BlendTree1D,
    pub current_speed: f32,                // 0..6 m/s
}

impl PlayerAnim {
    pub fn new(idle: AnimationClip, walk: AnimationClip, run: AnimationClip) -> Self {
        Self {
            blend_tree: BlendTree1D {
                nodes: vec![
                    BlendNode1D { speed_threshold: 0.0, clip: idle },
                    BlendNode1D { speed_threshold: 2.0, clip: walk },
                    BlendNode1D { speed_threshold: 5.0, clip: run },
                ],
                times: vec![0.0; 3],
            },
            current_speed: 0.0,
        }
    }

    pub fn update(&mut self, dt: f32, target_speed: f32, out: &mut Pose) {
        // 平滑 speed(避免抖动)
        self.current_speed += (target_speed - self.current_speed) * (1.0 - (-dt * 5.0).exp());
        self.blend_tree.evaluate_into(out, self.current_speed, dt);
    }
}

// 在主循环
fn game_update(state: &mut GameState, dt: f32) {
    let target_speed = compute_target_speed_from_input(&state.input);
    let mut pose = Pose::with_joint_count(state.skeleton.joint_count());
    state.player_anim.update(dt, target_speed, &mut pose);
    state.skeleton.apply_pose(&pose);
    state.skeleton.compute_global_poses(...);
    state.renderer.upload_skinning_palette(...);
}
```

跑起来,按 W 角色开始 walk,持续按住逐渐加速到 run。整个过程**没有状态切换**——blend tree 连续插值,没有 cross-fade 需求。

### 13.3 加 jump 状态(用 FSM)

加跳跃需要切到 jump clip(不连续),这时引入 FSM。基本结构:

```rust
#[derive(Clone, Copy, PartialEq)]
enum PlayerState { Grounded, Jumping, Falling }

pub struct PlayerAnimV2 {
    pub state: PlayerState,
    pub blend_tree: BlendTree1D,           // 地面移动
    pub jump_clip: AnimationClip,
    pub fall_clip: AnimationClip,
    pub cross_fade: Option<CrossFade>,
    pub jump_time: f32,
}

impl PlayerAnimV2 {
    pub fn update(&mut self, dt: f32, target_speed: f32, is_grounded: bool, out: &mut Pose) {
        let new_state = if !is_grounded {
            PlayerState::Falling
        } else if self.state == PlayerState::Jumping {
            PlayerState::Grounded
        } else {
            PlayerState::Grounded
        };

        if new_state != self.state {
            // 触发 cross-fade(从当前 pose 到新 state 的第 0 帧)
            self.state = new_state;
        }

        match self.state {
            PlayerState::Grounded => self.blend_tree.evaluate_into(out, target_speed, dt),
            PlayerState::Jumping => {
                self.jump_time += dt;
                self.jump_clip.sample_into(out, self.jump_time);
            }
            PlayerState::Falling => self.fall_clip.sample_into(out, 0.0),
        }
    }
}
```

### 13.4 加 IK 让脚贴地

最后加 Two-Bone IK,让角色脚踩在不平地面上:

```rust
fn apply_foot_ik(
    pose: &mut Pose,
    skeleton: &Skeleton,
    world_poses: &[[f32; 4]; 4],   // 已做完 FK 的 world matrices
    ground_heights: &GroundHeights, // 左右脚下方的地面高度
) {
    for (foot, ground_h) in [
        ("foot_L", ground_heights.left),
        ("foot_R", ground_heights.right),
    ] {
        let ankle_idx = skeleton.joint_index("ankle").unwrap();
        let knee_idx = skeleton.joint_index("knee").unwrap();
        let hip_idx = skeleton.joint_index("hip").unwrap();

        let root = translation_of(world_poses[hip_idx]);
        let mid = translation_of(world_poses[knee_idx]);
        let end = translation_of(world_poses[ankle_idx]);

        // target = 脚踝抬到地面以上 5cm
        let target = [end[0], ground_h + 0.05, end[2]];
        let pole = [root[0], root[1] + 0.5, root[2] + 1.0];  // 膝盖朝前

        let (new_mid, new_end) = solve_two_bone(&TwoBoneIkInput {
            root, mid, end, target, pole, soften: 0.1,
        });
        // 把新的 mid / end 转换回 local space(因为 pose 是 local)
        // ... (需要 inverse parent transform)
    }
}
```

跑起来,角色站在斜坡上脚踝贴地。这就是工业级"foot planting"的最简版。

### 13.5 验证清单

- [ ] cargo build,无 warning
- [ ] 跑游戏,角色 walk → run 平滑过渡
- [ ] 跳跃时角色切到 jump clip,cross-fade 200ms
- [ ] 角色站在斜坡上,脚踝贴地(IK 生效)
- [ ] 100 帧以内帧时间稳定在 16.6ms 以下(60 FPS)
- [ ] cargo test --test animation 跑通所有 blend / IK 单元测试

### 13.6 Arch Linux 工具链

```bash
# 装 binary 分析(看动画系统的内存占用)
sudo pacman -S valgrind massif-visualizer perf

# 跑 massif(内存 profile)
valgrind --tool=massif ./target/release/handmade_hero
ms_print massif.out.* | less

# perf 性能 profile
perf record -g --call-graph=dwarf ./target/release/handmade_hero
perf report --sort=overhead,symbol | grep -i animation
```

## 14 · 延伸阅读

本仓库本地资料:[skeletal-animation-fundamentals.md](./skeletal-animation-fundamentals.md)(本篇前置)、[camera-systems.md](./camera-systems.md)、[days/phase-3/day095.md](../day095.md)、[days/phase-3/day099.md](../day099.md)。

外部稳定 URL:
- Aristidou et al. FABRIK 论文(2011):https://www.academia.edu/10193439/FABRIK_A_fast_iterative_solver_for_the_Inverse_Kinematics_problem
- Shoemake SLERP 论文(1985) ACM SIGGRAPH: https://doi.org/10.1145/325165.325242
- Kovar et al. Motion Graphs(2002, Motion Matching 鼻祖):https://research.cs.wisc.edu/graphics/Gallery/kovar-papers/motiongraphs/motiongraphs.pdf
- Unreal AnimBP 官方文档:https://docs.unrealengine.com/5.0/en-US/animation-blueprints-in-unreal-engine/
- Bevy Animation(社区书):https://bevy-cheatbook.github.io/features/animation.html

真实开源源码:
- Bevy bevy_animation:https://github.com/bevyengine/bevy/tree/main/crates/bevy_animation
- OZZ ozz-animation:https://github.com/ozz-animation/ozz-animation
- Godot AnimationTree:https://github.com/godotengine/godot/blob/master/scene/animation/animation_tree.cpp
- Unreal Engine(需登录):https://github.com/EpicGames/UnrealEngine — `Engine/Source/Runtime/AnimGraphRuntime/`
- Unity DOTS Animation:https://github.com/Unity-Technologies/EntityComponentSystemSamples/tree/master/Animation
- bevy_motion_match(实验):https://github.com/jay2606/bevy_motion_match

---

**总结**:动画系统的本质是**把多个 pose 来源按规则混合**。所有花哨的功能(blend tree、additive、layer、HFSM)都是 §1.2 的四种操作(Sample / Blend / Add / Override)的组合。IK 是另一类问题(反推 joint),但同样可以归结为"在 pose 空间求解"。把这些原子操作组合起来,任何动画需求都能表达。

下一篇深潜会是 Motion Matching 的完整实现——从 mocap 数据到 runtime 搜索的端到端。
