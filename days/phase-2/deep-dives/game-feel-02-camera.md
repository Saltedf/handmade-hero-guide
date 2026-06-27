---
phase: 2
title_en: "Game Feel Part 2 — Camera Feel"
title_zh: "游戏手感(二):相机手感"
type: deep-dive
difficulty: intermediate
duration: "3h"
domains: [game, graphics, rust, math]
prereqs: ["camera-systems", "game-feel-01-input-and-timing-feel"]
calibration: "Steve Swink《Game Feel》— 相机手感(跟随/look-ahead/震屏/阻尼)"
---

# 游戏手感(二):相机手感

> 你的角色站在 HH 的房间里,按右键角色往右走。相机怎么动?最直接的写法——**相机坐标等于角色坐标**。编译运行,角色动了,镜头也动了,但你看一眼就觉得不对劲:角色一加速,镜头"啪"地瞬移过去;角色一停,镜头又"啪"地钉死。整个画面像被人拽着领子来回晃,玩两分钟眼睛发酸。这是**所有新手引擎都会撞上的第一面墙**:相机不能硬绑。
>
> 然后你加 `lerp`,相机柔和了,但又有新问题——按右走,镜头永远在角色后面追,看不见前方;被怪物打一下,屏幕纹丝不动,打击感为零;窗口从 60 Hz 屏拖到 144 Hz 屏,相机忽然变"木",跟在后面慢半拍。这三个问题指向同一件事:**你只写了相机的数学,没写相机的手感**。
>
> 这一篇是 [camera-systems](../../phase-3/deep-dives/camera-systems.md) 的手感续集。camera-systems 讲 view matrix、四元数、sphere sweep 这些**地基**——把相机当数学对象。今天我们把相机当**玩家的眼睛**:它会呼吸、会犹豫、会在你被打时颤抖、会比你先一步看向你要去的地方。这就是 Steve Swink 在《Game Feel》里说的 camera feel——整个游戏"手感好不好",相机贡献了至少三成。

## 0 · 相机是玩家的眼睛

很多教程把相机写成"一个跟随玩家的 entity",这是**致命的比喻**。相机不是"跟在玩家后面的小弟",相机**就是玩家本人**——更准确地说,是玩家在这个虚拟世界里的身体感官。玩 Super Mario Odyssey 时你不会想"我在控制 Mario,镜头在追我",大脑直接把那个视角当成自己的眼睛。这种"忘记相机存在"的沉浸感,正是相机手感调到位的标志。

反过来,只要相机有一丝"机械感"——角色急停时镜头抖一下、跳跃顶点时镜头滞后半拍、被击中时画面没反应——玩家立刻被拉回"我在操作一个程序"的清醒状态。**相机手感的天花板是"无感",地板是"恶心"**。camera sickness(晕 3D)是玩家弃游的第一大原因,超过剧情差和操作难,而它绝大多数时候不是 FOV 或 near plane 的问题,是**相机运动曲线**的问题。

**学完这一篇,你应该能**:用临界阻尼弹簧写一个无 overshoot、平滑到位的相机跟随;用 deadzone + look-ahead 表达"玩家的意图";用沿冲击方向的衰减震屏给打击加重量;用 `dt`-aware 的指数衰减公式保证相机在任意刷新率下表现一致;并理解为什么"相机参数没有公式,只能边玩边调"——以及为此必须把所有手感参数挂到 CVar(见 [09B-4](../../phase-9/09B-4-cvars-and-dev-console.md))。

## 1 · 第一面墙:硬绑相机为什么不"舒服"

最朴素的写法:

```rust
// camera_rigid.rs —— 硬绑相机(反面教材)
fn update_rigid(cam: &mut Camera, player_pos: Vec2) {
    cam.pos = player_pos;  // 每帧把相机钉在玩家身上
}
```

跑起来有三个症状。**症状一:微抖放大**。玩家位置每帧都在亚像素抖动(物理 substep、输入量化、动画 root motion 都注入噪声),硬绑相机把这些噪声百分之百传到画面,你盯着背景瓷砖缝看会发现它在单像素幅度颤动,累积 10 分钟开始头晕。**症状二:加减速没有过渡**。角色从静止到全速一帧之内发生,相机也跟着一帧从静止到全速,大脑的前庭系统(vestibular system)按**视觉运动的加速度**判断"我在不在动",速度瞬间跳变会让它误以为"被撞了一下"。**症状三:方向感缺失**。镜头永远在角色正上方/正后方,前方后方画面比例永远 1:1,但玩家关心的是"要去的地方",信息量均等等于前方信息没有突出,玩家感觉"看不清前面的路"。

解决它们的总思路是:**让相机成为一个有惯性、能预判玩家意图、对冲击有反应的独立物体**。下面三节分别解决这三件事。

## 2 · 阻尼跟随:用临界阻尼弹簧驯服速度

### 2.1 从 lerp 到指数衰减

最常见的"缓一点"写法是 lerp:`cam.pos.lerp(player_pos, 0.1)`。这句看起来温和,但有两个隐藏问题。**问题一**:这个 `0.1` 是"**每帧** 10%",在 60 FPS 下 5 帧追上 41%,在 144 FPS 下 5 帧(只 35ms)追上同样的 41%——同一台机器换块屏幕,相机"软硬度"就变了。这是相机手感的经典 bug,第 5 节会专门讲。**问题二**:lerp 是一阶系统,它只看"我现在离目标多远",不看自己的速度,**无法表达惯性**。玩家急停,lerp 立刻把速度砍掉一截,相机看起来"被瞬间拽住"。

工业游戏(God of War、Hollow Knight)用**弹簧物理(spring physics)**。把相机想象成被弹簧拴在玩家身上的重物:弹簧拉它过去,阻尼器(damper)消耗能量,它就能"刹住"甚至轻微 overshoot。

### 2.2 临界阻尼弹簧

弹簧方程是 `F = -k·x - c·v`(`x` 是相机到目标的距离,`v` 是相机速度,`k` 是刚度,`c` 是阻尼)。阻尼太小,相机在玩家身边来回弹几下才停——像果冻;阻尼太大,相机追不上玩家。存在一个**临界阻尼(critical damping)**值让弹簧**恰好不振荡、最快收敛**:`c = 2·√k`。更工程化的写法用"角频率"和"阻尼比"两个参数:

```rust
// camera_spring.rs —— 临界阻尼弹簧相机
use glam::Vec2;

pub struct SpringCamera {
    pub pos: Vec2,
    pub vel: Vec2,
    pub target: Vec2,
    /// 自然角频率(rad/s)——越大收敛越快。8 是"轻快",4 是"慵懒",15 很硬
    pub frequency: f32,
    /// 阻尼比。1.0 = 临界(不振荡、最快收敛);<1.0 欠阻尼(会 overshoot);>1.0 过阻尼
    pub damping_ratio: f32,
}

impl SpringCamera {
    pub fn update(&mut self, dt: f32) {
        // 半隐式 Euler(semi-implicit Euler),比纯 Euler 稳定
        let omega = self.frequency;
        let x = self.pos - self.target;
        let accel = -omega * omega * x - 2.0 * self.damping_ratio * omega * self.vel;
        self.vel += accel * dt;
        self.pos += self.vel * dt;
    }
}
```

`accel` 那一行对应微分方程 `ẍ + 2ζω·ẋ + ω²·x = 0`,阻尼比 `ζ = 1` 时就是临界阻尼。**为什么用半隐式 Euler 而不是显式 Euler**?因为显式 Euler 在 stiffness 大时能量累积爆炸——frequency 调到 30 时显式 Euler 让相机越跑越远,半隐式 Euler 能量守恒稳定。这是物理引擎常识(见 [physics-foundation](../../phase-0/21-physics-foundation.md)),相机代码同样适用。

**参数怎么调**。`frequency = 8`、`damping_ratio = 1.0` 是安全起点——轻快地跟上来,不弹。想要"弹性"手感(像 Hollow Knight 跳跃后镜头轻轻一沉),`damping_ratio` 调到 0.7;想要"沉稳"(像 Souls 系列),`frequency` 降到 4、`damping_ratio` 升到 1.2。**这些数没有公式,只能挂 CVar 边玩边调**(第 7 节)。

### 2.3 为什么不用 lerp 的更深层原因

lerp 本质是"无记忆的一阶系统",每帧只看"离目标多远",不看速度——**无法表达惯性**。弹簧是"二阶系统",它有 `vel` 状态。玩家急停时,弹簧相机速度还在,会**继续往前冲一段**再被阻尼拉回来——这就是"刹不住车的惯性",和真实世界的物理直觉一致,大脑接受毫不费力。**相机的"重量感"本质上来自二阶系统的速度状态**,不是参数本身。Vlambeer、Derek Yu 在演讲里反复强调 "camera is a physical object, not a function"——把相机当函数(lerp)它就是死的;把相机当物理对象(spring)它就活了。

## 3 · Look-ahead 与 Deadzone:让相机表达"意图"

阻尼解决了"加减速不平滑",但**没解决"看不见前面的路"**。

### 3.1 Look-ahead:相机比玩家先看一步

玩家往右走,说明他关心右边,相机就该往右偏一点。这叫 **look-ahead**(也叫 leading camera、predictive camera):

```rust
// camera_lookahead.rs
struct CameraWithLookAhead {
    spring: SpringCamera,
    pub look_ahead_factor: f32,  // 0.3 = 玩家速度的 30% 作为前置偏移
    pub look_ahead_max: f32,     // 最大距离,防高速时偏太远
}

impl CameraWithLookAhead {
    fn update(&mut self, player_pos: Vec2, player_vel: Vec2, dt: f32) {
        let offset = (player_vel * self.look_ahead_factor)
            .clamp_length_max(self.look_ahead_max);
        // 关键:offset 加到弹簧的 target,不是相机坐标
        // 这样 look-ahead 本身也被弹簧平滑
        self.spring.target = player_pos + offset;
        self.spring.update(dt);
    }
}
```

关键细节:`offset` 加到**弹簧的 target** 上,不是相机坐标。如果直接加坐标,玩家速度一变镜头就跳,又回到硬绑的机械感。把 `look_ahead_factor` 从 0 调到 0.3,玩家几乎立刻报告"视野舒服多了"——大脑能看到"要去的地方"。调到 0.8 又过了,相机跑在玩家前面太远,玩家觉得"我在追镜头"。**0.2 到 0.4 是横版/俯视的常见区间**,具体多少只能边玩边定。

### 3.2 关键细节:look-ahead 也要"减速"

新手常犯的错:玩家急停(速度从 600 突变 0),`offset` 也瞬间归零,弹簧收到突变目标,**猛烈往回冲**——比没 look-ahead 更难受。工业做法:look-ahead 用玩家速度的**平滑版**:

```rust
// 每帧更新 smoothed_vel(帧率独立)
let alpha = 1.0 - (-dt * 10.0).exp();  // 10Hz 平滑
self.smoothed_vel = self.smoothed_vel.lerp(player_vel, alpha);
let offset = self.smoothed_vel * self.look_ahead_factor;
```

玩家急停时 `smoothed_vel` 慢慢降到 0,offset 慢慢收回,弹簧收到的是**连续变化**的目标,运动完全顺滑。这种 "smoothed velocity" 在游戏开发里到处都是——动画 root motion、AI 转向、相机 look-ahead,本质都是"不要把原始输入直接喂给下游,先平滑一道"。

### 3.3 Deadzone:小动作不惊动相机

玩家**站着不动**,但他在按微小的方向键抖动(或手柄摇杆死区外漂移),玩家速度在 ±5 px/s 间漂移。这通过 look-ahead 传到相机目标,相机在 ±1.5px 间小幅晃动——单帧看不出,**累积起来又是晕 3D 元凶**。

解决方案是 **deadzone**(死区):设一个"容差框",玩家在框内时相机目标**冻结**,只有走出框相机才重新定位。

```rust
// camera_deadzone.rs
pub struct DeadZone {
    pub half_size: Vec2,
    pub anchor: Vec2,  // 死区中心在世界坐标的位置
}

impl DeadZone {
    /// 玩家走出死区的部分,锚点跟随;框内锚点不动
    pub fn update(&mut self, player_pos: Vec2) -> Vec2 {
        let delta = player_pos - self.anchor;
        if delta.x.abs() > self.half_size.x {
            let over = delta.x.abs() - self.half_size.x;
            self.anchor.x += over * delta.x.signum();
        }
        if delta.y.abs() > self.half_size.y {
            let over = delta.y.abs() - self.half_size.y;
            self.anchor.y += over * delta.y.signum();
        }
        self.anchor
    }
}
```

逻辑是:**玩家走出死区多远,锚点就跟多远,把玩家刚好拉回死区边缘**。玩家小幅抖动时锚点不动,相机目标不动,相机自然也不动。Deadzone 是消除"亚像素抖动"最干净的手段。**尺寸是关键参数**:太小(5px)等于没死区;太大(200px)玩家走到屏幕边缘相机才动,觉得"跟角色脱节"。横版的 deadzone 通常是**横向宽、纵向窄**——横版角色横向移动多、纵向跳跃少,你希望横向给玩家更多自由(更大死区),但纵向紧跟(否则跳跃时看不到地面)。Super Mario World 的死区就是个经典"扁矩形"。

### 3.4 把三者叠起来

三层不是互斥而是**层层叠加**:

```rust
// camera_pipeline.rs
impl GameCamera {
    pub fn update(&mut self, player_pos: Vec2, player_vel: Vec2, dt: f32) -> Vec2 {
        // 1. deadzone 基于真实玩家位置决定"锚点"
        let anchor = self.deadzone.update(player_pos);
        // 2. look-ahead 在锚点上加预测偏移(用 smoothed_vel)
        self.lookahead.update(anchor, player_vel, dt);
        // 3. spring 把最终目标平滑到相机当前位置
        self.lookahead.spring.pos
    }
}
```

每层解决一个具体问题:deadzone 解决"小动作放大",look-ahead 解决"看不见前面的路",spring 解决"加减速没过渡"。**顺序不能乱**:deadzone 必须基于真实玩家位置做决策,spring 基于决策后的目标做执行——如果你先平滑再 deadzone,玩家急停时平滑后的位置还在框内但真实位置已出去,会看到"玩家明明在动相机却钉死"的诡异画面。

## 4 · 相机震屏:打击感的"重量"

平地手感顺了,但游戏还没有**打击感**。玩家被怪物打一下屏幕纹丝不动,角色落地镜头没反应——游戏感觉"飘"。这一节讲相机震屏(camera shake),Vlambeer 在 "The Art of Screenshake" 把它列为 juice 第一元素(详见 [game-feel-short](./game-feel-short.md) 和 [game-feel-03](./game-feel-03-feedback-juice.md))。但要警告一句:**震屏是相机手感里最容易"做过"的部分**,半节篇幅在讲"克制"。

### 4.1 Trauma 模型:振幅按平方衰减

工业标准算法来自 Squirrel Eiserfeld GDC 2015 "Juice It or Lose It"。维护一个 `trauma`(创伤值,0..1),事件触发时加量,每帧按指数衰减,**最终偏移 = trauma² · max_offset**。

为什么平方?人脑对刺激的感知是非线性的——线性衰减的震屏看起来"平",小事件和大事件差别不明显;平方曲线让大事件振幅远超小事件,**玩家能从震屏强度读出"事件有多严重"**。这是震屏作为"游戏语言"的基础。

```rust
// camera_shake.rs —— Trauma 震屏模型
use glam::Vec2;

pub struct CameraShake {
    trauma: f32,           // 0..1
    pub max_offset: f32,   // 最大偏移(像素)
    pub decay_tau: f32,    // 衰减时间常数(秒)。0.3 ≈ 300ms 衰减到 37%
    pub noise_freq: f32,   // 噪声频率(Hz)。30 是"剧烈颤抖",8 是"沉重摇晃"
    seed_x: u32,
    seed_y: u32,
    t: f32,
}

impl CameraShake {
    /// severity 0..1。小弹片 0.1,大爆炸 0.8
    pub fn add_trauma(&mut self, severity: f32) {
        // 累加封顶 1.0,防多次小冲击叠加成无限震屏
        self.trauma = (self.trauma + severity).min(1.0);
    }

    pub fn update(&mut self, dt: f32) -> Vec2 {
        self.trauma *= (-dt / self.decay_tau).exp();        // 帧率独立衰减
        let amp = self.trauma * self.trauma * self.max_offset; // 平方曲线
        self.t += dt * self.noise_freq;
        // 两个独立噪声(生产环境用 Perlin/Simplex)
        Vec2::new(
            pseudo_noise(self.t, self.seed_x) * amp,
            pseudo_noise(self.t, self.seed_y) * amp,
        )
    }
}

fn pseudo_noise(t: f32, seed: u32) -> f32 {
    let s = seed as f32;
    (t.sin() * 2.0 + (t * 1.7 + s).sin() * 1.3 + (t * 0.5 - s).sin() * 0.7) / 4.0
}
```

`add_trauma` 是**累加**的——同帧多次小冲击合成大冲击(三个小弹片 ≈ 一个大弹片)。trauma 封顶 1.0 防止玩家被连击后震屏永远不停。振幅用 `trauma²` 保证大事件冲击力远超小事件。

### 4.2 方向性震屏:沿冲击方向偏

无方向震屏(x/y 都是独立噪声,镜头在原地"哆嗦")对小事件够用,但对**有明确方向**的冲击(爆炸从右边来、玩家从高处落地)感觉不对——大脑会困惑"能量从哪个方向来?"。工业做法是**沿冲击方向加有向偏移**,再叠加无向噪声:

```rust
// directional_shake.rs
pub struct DirectionalShake {
    base: CameraShake,
    impulse: Vec2,  // 当前有向冲击累计(也衰减)
    pub impulse_decay_tau: f32,
}

impl DirectionalShake {
    /// impact_dir 是"冲击来自的方向"(归一化),severity 是强度
    pub fn add_impact(&mut self, impact_dir: Vec2, severity: f32) {
        self.impulse += impact_dir * severity;  // 偏移方向是"远离冲击源"
        self.base.add_trauma(severity);
    }

    pub fn update(&mut self, dt: f32) -> Vec2 {
        self.impulse *= (-dt / self.impulse_decay_tau).exp();
        self.base.update(dt) + self.impulse
    }
}
```

玩家从高处落地,震屏**先向下沉一下**再无向颤抖;被右边爆炸打到,镜头**先向左冲一下**再随机抖。这种"先有向、后无向"的两段式震屏,是 Hyper Light Drifter、Celeste 这些手感顶级作品的标配。

### 4.3 克制:震屏最大的艺术

到这里你已经会写震屏,但 **90% 的新手会把它做坏**——不是因为算法错,而是**用得太狠**。

**第一,震屏要分严重性**。普通走路不震,普通攻击小震(trauma 0.1),暴击中震(0.3),boss 大招重震(0.6),过场大爆炸顶震(0.9)。每个事件都震 0.5,玩家 5 分钟内就麻木——震屏失去"信息量"变成纯粹恶心源。把 severity 写成事件属性,不写死在 `add_trauma(0.5)` 里。**第二,总时长不超过 400ms**。`decay_tau = 0.3` 已经够;再长玩家会觉得"画面一直在晃",前庭系统超载。Celeste 震屏通常 150-250ms,瞬间发生瞬间结束,反而比长震屏更有冲击力。**第三,永远给关闭选项**——10-20% 的玩家有前庭敏感,震屏会让他们恶心头痛。**震屏强度必须做成 accessibility 选项**(详见 [accessibility-short](../../phase-7/deep-dives/accessibility-short.md)),从 0% 到 100% 可调,在很多国家这是法律要求(参见 WCAG 2.2 vestibular disorder 条款)。**第四,震屏不是唯一反馈**——一个"打击"应该有多重反馈:震屏、hitstop(见 [game-feel-01](./game-feel-01-input-and-timing-feel.md))、粒子(见 [particle-systems-cpu](../../phase-3/deep-dives/particle-systems-cpu.md))、音效、color flash。只有震屏没有 hitstop 的打击,感觉像"画面坏了"而不是"打中了"。我们在 [game-feel-03](./game-feel-03-feedback-juice.md) 会专门讲怎么把这些反馈**编排**成连贯的"打击时刻"。

### 4.4 把震屏接到 pipeline 上

震屏输出是**屏幕空间偏移**,在 spring 算完位置**之后**叠加,**不参与弹簧物理**:

```rust
let cam_pos = camera.update(player_pos, player_vel, dt);
let shake_offset = shake.update(dt);
let final_cam_pos = cam_pos + shake_offset;  // 震屏不进弹簧
```

为什么不加到 spring 的 target 上?因为弹簧是"低通滤波器",会把高频震屏噪声滤掉,震屏就震不起来。震屏必须绕过所有平滑。铁律:**smooth 走 smooth 路径,impact 走 impact 路径,两者在最后合成**。

## 5 · 帧率独立性:相机手感的"隐形杀手"

你的相机现在看起来很好,但把它从 60 Hz 屏拖到 144 Hz 屏,会发现诡异现象:**相机变"硬"了**——跟随更紧、震屏更短、整个手感"快了一截"。这不是错觉,是最难调试的手感 bug 之一,因为你需要两块不同刷新率的屏幕才能复现。

### 5.1 为什么 lerp 0.1 在不同帧率下不一样

`cam.pos.lerp(target, 0.1)` 的 `0.1` 是"**每帧** 10%"。60 FPS 下追到 50% 用 6.6 帧 = 110ms;144 FPS 下追到 50% 用 6.6 帧 = 46ms。144 Hz 屏上相机"软"了一半,变成"硬绑"。这种"高刷屏上手感变化"在所有用 lerp 的代码里都存在,但因为相机是玩家**每帧都看着**的对象,它最显眼。

### 5.2 正确写法:dt-aware 的指数衰减

正确的"每秒衰减一定比例"写法是**把衰减率换算到 dt 上**。指数衰减有漂亮性质:`e^(-λ·t)` 在时间 `t` 后衰减到 `e^(-λ·t)`,**与采样频率无关**:

```rust
// frame_rate_independent.rs
/// decay_rate 是"每秒衰减比例"(Hz)。5.0 ≈ 200ms 衰减一半,10.0 ≈ 100ms 衰减一半
fn smooth_towards(current: Vec2, target: Vec2, decay_rate: f32, dt: f32) -> Vec2 {
    let alpha = 1.0 - (-decay_rate * dt).exp();
    current.lerp(target, alpha)
}
```

`alpha = 1.0 - (-decay_rate * dt).exp()` 是相机手感里**最重要的一行代码**。60 Hz 下 `alpha ≈ 0.074`,144 Hz 下 `alpha ≈ 0.031`,两个 alpha 不同但**每秒衰减比例都是 `e^(-decay_rate)`**,相机表现完全一致。**所有时间相关参数都用"每秒"单位**(Hz、秒、rad/s),绝不写 `0.1 per frame`——这是手感代码的卫生底线。这个原则在 [game-feel-01](./game-feel-01-input-and-timing-feel.md) 讲输入和时间手感时已经讲过,相机上完全适用。

### 5.3 弹簧和震屏的帧率独立

第 2.2 节的弹簧用半隐式 Euler(`vel += accel * dt; pos += vel * dt`),**已经是帧率独立的**。但半隐式 Euler 在 frequency 高时仍会失稳——经验法则 `dt · frequency < 0.1` 才稳定。60 Hz 下 frequency 上限约 6,相机够用,但"硬弹簧"不够。要做超高频率弹簧(打击瞬间 squash & stretch 用,frequency 30+),用**解析解**而不是数值积分:

```rust
// critically_damped_analytic.rs
/// 从 (x0, v0) 出发,临界阻尼追向 0,在时间 t 后的位置和速度。
/// 对 ẍ + 2ζω·ẋ + ω²·x = 0 在 ζ=1 时的解析解。
fn critical_spring_solve(x0: f32, v0: f32, omega: f32, t: f32) -> (f32, f32) {
    let e = (-omega * t).exp();
    let pos = (x0 + (v0 + omega * x0) * t) * e;
    let vel = (v0 - omega * (v0 + omega * x0) * t) * e;
    (pos, vel)
}
```

解析解**完全无视 dt 大小**——1ms 还是 100ms 结果都物理精确。代价是只能处理临界阻尼,但相机够用。frequency 不超过 10 就用半隐式 Euler,要做"硬刹"(frequency 20+)就换解析解。

震屏代码已经用了 `(-dt / decay_tau).exp()`,trauma 衰减帧率独立。但有个隐藏坑:**噪声频率 `noise_freq`**。`noise_freq = 22` 意味着每秒采样 22 次,`self.t += dt * noise_freq` 是对的。但如果写成"每帧加 0.3",60 Hz 下噪声频率是 18 Hz,144 Hz 下变成 43 Hz——震屏"颤抖速度"完全不同。**所有频率参数都要用 Hz,不要用 per-frame**。

**自检方法**:60 Hz 和 144 Hz 下录制同一段游戏,逐帧对比相机轨迹。时间轴上重合 = 帧率独立;有可见差异 = 某参数漏了 dt。这是相机手感 QA 的标准流程,发布前必跑。

## 6 · 不同类型的相机:同一套原则,不同写法

到此用的是横版/俯视 2D 相机作例子。但相机手感的**原则是通用的**——阻尼、意图投影、克制——只是不同游戏类型在**具体写法**上差异巨大。

**横版平台(platformer)**是相机手感教科书案例。Super Mario World、Celeste、Hollow Knight 都被反复研究。特点:玩家横向移动多、纵向跳跃少、需要看清前方落点。配置通常是横向 deadzone 较宽、纵向 deadzone 较窄(跳跃时紧跟,否则看不到地面);look-ahead 主要横向;spring 偏软(frequency 6-8);跳跃落地触发小震屏(trauma 0.15)。Celeste 还有独门技巧:**玩家朝一个方向持续移动时,deadzone 动态扩大**——明确朝一个方向走时给更多自由,原地探索时收窄。这种"基于玩家意图动态调整 deadzone"是 Celeste 手感顶级的核心。

**双摇杆射击(twin-stick)**的相机完全不同。Nuclear Throne、Enter the Gungeon 的特点:移动方向和瞄准方向独立——左摇杆移动,右摇杆射击。工业做法是 **look-ahead 跟瞄准方向**而不是移动方向——玩家关心的"要射击的地方"而不是"要走到的地方"。你边后退边射击,镜头应偏向射击方向(看清敌人),而不是偏向移动方向(只看清自己背后)。Nuclear Throne 还有一个标志性设计:**击杀瞬间相机有个微小"推进"(zoom-in 5%)持续 200ms 然后回弹**——每次击杀都有"分量",是 Vlambeer 反复强调的 "every kill should feel like an event"。

**赛车(racing)**的特点是高速移动、相机在车后。look-ahead 不适用——车前方就是玩家要去的地方,look-ahead 等于"镜头再往前偏",反而看不见车。赛车相机用**滞后跟随(trailing camera)**:相机位置基于车的**过去位置**而不是当前位置,镜头永远比车慢半拍——这种"滞后"反而符合直觉(你坐在车里向前开,眼睛看到的本来就是"已经开过的地方"加"前方")。赛车 spring 通常很**硬**(frequency 12-15),高速时不能滞后太多否则车开出屏幕,但又不能太硬否则急转弯镜头来不及转看不见弯道后的路。很多赛车游戏为不同车速写不同 spring 参数。

**3D 第三人称(third-person 3D)**是最复杂的——要在 3D 空间轨道环绕玩家,还要做碰撞(不能穿墙)。技术细节在 [camera-systems](../../phase-3/deep-dives/camera-systems.md) 讲过(sphere sweep、collision),我们这里只讲手感。关键参数是 **target offset**——相机看向的目标位置不是玩家脚下,而是头部上方(+1.5m),让画面有"居高临下"的视角。God of War 的 target offset 甚至**根据战斗状态动态变化**——平时偏上(看清环境),战斗中偏下(看清敌人)。3D 第三人称的 spring 通常**在两个独立轴上**——距离 spring 较硬(防穿墙时距离突变),角度 spring 较软(转向有"漂移感")。这种**多轴独立 spring** 是把"一个相机"拆成"多个自由度"分别调参的工业做法。

**共通的三原则**。虽然写法千差万别,所有这些游戏都遵循:**第一,相机是物理对象不是函数**——用 spring 不用 lerp,让相机有惯性。**第二,相机表达玩家意图**——look-ahead 投射"要去哪里",target offset 投射"在看哪里",deadzone 表达"在做什么";相机不是"跟随玩家的工具",是**玩家感官的延伸**。**第三,克制比堆料重要**——震屏分严重性,deadzone 不要太大,spring 不要太硬。**相机手感的天花板是"无感"**,任何让玩家"注意到相机存在"的设计都是失败的。

## 7 · CVar 调参:相机手感没有公式

讲完所有算法,我们要面对残酷事实:**相机手感没有公式可以推**。frequency 应该是 6 还是 9?look-ahead_factor 0.2 还是 0.4?deadzone 80px 还是 120px?trauma 平方还是 1.5 次方?这些问题没有任何理论能给答案,唯一方法是**边玩边调**。这意味着所有相机参数**必须能在游戏运行时实时修改**——这就是 CVar(console variable)的作用。把参数暴露到调试控制台,玩家边玩边敲命令改参数,改完立刻看到效果。这个工作流在 [09B-4](../../phase-9/09B-4-cvars-and-dev-console.md) 专门讲,这里给一个相机手感 CVar 范例:

```rust
// camera_cvars.rs —— 相机手感的 CVar 配置
use std::sync::atomic::{AtomicF32, Ordering};

pub struct CVar {
    name: &'static str,
    value: AtomicF32,
    description: &'static str,
}

impl CVar {
    pub const fn new(name: &'static str, default: f32, desc: &'static str) -> Self {
        Self { name, value: AtomicF32::new(default), description: desc }
    }
    pub fn get(&self) -> f32 { self.value.load(Ordering::Relaxed) }
    pub fn set(&self, v: f32) { self.value.store(v, Ordering::Relaxed); }
}

// 全局 CVar 表
pub static CV_FREQUENCY: CVar = CVar::new("cam_freq", 8.0, "spring 角频率,越大越硬");
pub static CV_DAMPING_RATIO: CVar = CVar::new("cam_damping", 1.0, "阻尼比,1=临界,<1=弹,>1=稳");
pub static CV_LOOKAHEAD_FACTOR: CVar = CVar::new("cam_lookahead", 0.3, "look-ahead 系数");
pub static CV_LOOKAHEAD_MAX: CVar = CVar::new("cam_lookahead_max", 180.0, "look-ahead 最大距离");
pub static CV_DEADZONE_X: CVar = CVar::new("cam_deadzone_x", 80.0, "横向死区半宽");
pub static CV_DEADZONE_Y: CVar = CVar::new("cam_deadzone_y", 40.0, "纵向死区半宽");
pub static CV_SHAKE_MAX: CVar = CVar::new("cam_shake_max", 16.0, "震屏最大偏移(像素)");
pub static CV_SHAKE_TAU: CVar = CVar::new("cam_shake_tau", 0.3, "震屏衰减时间常数(秒)");
pub static CV_SHAKE_FREQ: CVar = CVar::new("cam_shake_freq", 22.0, "震屏噪声频率(Hz)");
```

**调参流程**:打开游戏和调试控制台(通常按 `~`),边玩边敲 `cam_freq 7`、`cam_lookahead 0.25`、`cam_shake_max 12`,每次改完跑一段路、跳一下、被打一下,感受变化。Steve Swink 在《Game Feel》里说,一个商业游戏的相机参数平均调 200-500 次才定稿。**几个直觉**:相机"跟不上玩家"通常是 frequency 太低,调高;相机"抖"(小动作就晃)是 deadzone 太小或 look-ahead 太大;打击感"飘"是震屏 max 太小或 tau 太短;震屏"恶心"反过来调。这些直觉只能在反复玩的过程中建立,**没有任何文档能替代**。

**退出条件**:把游戏给一个没玩过的朋友试玩,他玩 5 分钟**没主动提"相机"**——既没说"看不清路",也没说"头晕",更没说"镜头怪怪的"——这时候相机手感就到位了。任何关于相机的反馈(无论正负)都说明相机还没"无感"。这是终极验收标准,也是最难达到的标准。

## 8 · 在你 HH 项目里动手(做中学红线)

按顺序做完,你的 HH 就有了工业级相机手感。

**步骤 1:加阻尼弹簧跟随**。打开相机更新代码(Casey 在 Day 80 左右开始有相机概念),把硬绑 `camera_pos = player_pos` 换成本文第 2.2 节的 `SpringCamera`。先用 `frequency = 8`、`damping_ratio = 1.0` 跑起来,确认相机不再"瞬移"。

**步骤 2:加 look-ahead**。在弹簧 target 上加 `smoothed_vel * 0.3` 偏移,记住用第 3.2 节的 `smoothed_vel`,不要直接喂原始速度。试运行:往右走相机往右偏;急停相机平滑收回而不是猛地回头。

**步骤 3:加 deadzone**。加第 3.3 节的 `DeadZone`,先设 `half_size = (80, 40)`。试运行:松开手柄让角色站着,确认相机完全不动;小幅度走动相机仍不动;走出 deadzone 相机平滑跟上。

**步骤 4:加震屏**。实现第 4.1 节的 `CameraShake`,接到测试触发器(按 `K` 键触发 `add_trauma(0.5)`)。改 `decay_tau` 从 0.3 到 0.8 确认震屏变长;改 `max_offset` 从 16 到 4 确认变小。然后实现第 4.2 节的 `DirectionalShake`,接到角色落地事件——`impact_dir = Vec2::Y`(向下),`severity = 0.15`。从高处跳下,确认镜头"先下沉再颤抖"。

**步骤 5:全部挂 CVar**。把步骤 1-4 所有参数(`frequency`、`damping_ratio`、`look_ahead_factor`、`look_ahead_max`、`deadzone half_size`、`max_offset`、`decay_tau`、`noise_freq`、`impulse_decay_tau`)挂到 CVar。如果还没 CVar 系统,先把 [09B-4](../../phase-9/09B-4-cvars-and-dev-console.md) 的最小实现搭起来。打开控制台确认能实时改每个参数。

**步骤 6:调参**。打开游戏和控制台,按第 7 节流程**边玩边调**。重点调三件事:平地跑动相机是否"无感"(既不滞后也不僵硬);跳跃落地震屏是否"有重量"(既不飘也不恶心);急停急转相机是否"连贯"(不猛回头、不滞后半拍)。预计 3-5 小时,没有捷径。

**步骤 7:帧率独立性测试(最关键的验收)**。如果电脑有两块屏(60 Hz 和 144 Hz),拖来拖去跑同一段路;否则用 `--lock-fps 60` 和 `--lock-fps 144` 参数分别在两个帧率下录制视频,逐帧对比相机轨迹。具体查三件事:**相机追上玩家用的时间是否一致**(都应 ~200ms);**震屏衰减完用的时间是否一致**(都应 ~400ms);**look-ahead 偏移量是否一致**(同速度下相同)。任何一项不一致,说明某参数漏了 dt——常见错误:lerp 用了"per frame"因子(改成第 5.2 节的 `1 - exp(-λ·dt)`)、噪声频率用了"per frame"(改成 Hz)、震屏 trauma 衰减忘了乘 dt。**这是相机手感 QA 的必须环节,不要跳过**。

完成后你的 HH 相机达到工业级水准。下一步探索 [game-feel-03-feedback-juice](./game-feel-03-feedback-juice.md)(把相机震屏和 hitstop、粒子、音效编排成完整"打击时刻")以及 [game-feel-04](game-feel-04-audio-and-polish.md)(动画与控制手感)。

## 9 · 练习

**Lv1(基础)**:把第 2.2 节的 `SpringCamera` 接到 HH,只调 `frequency` 和 `damping_ratio`。记录下你觉得最舒服的两组值(一组偏软、一组偏硬),并写一段话描述为什么两组都"可以",各自适合什么场景。

**Lv2(进阶)**:实现第 3 节完整 pipeline(deadzone + look-ahead + spring),并为 deadzone 加"动态尺寸"——玩家持续朝一个方向移动时,deadzone 在那个方向扩大(参考第 6 节的 Celeste 技巧)。提示:维护 `movement_consistency` 标量,玩家持续移动时增大,改向时归零。

**Lv3(挑战)**:实现第 4.2 节的 `DirectionalShake`,接到 HH "角色被击中"事件。然后做 A/B 测试:把震屏切到纯无向(注释掉 impulse 部分),让一个朋友分别玩两个版本各 5 分钟,问哪个"打击感更好"。记录反馈,思考为什么方向性震屏感觉更好(或更差)。

**Lv4(工程)**:在 Lv2 基础上做完整"帧率独立性审计"。列出所有时间相关参数(`frequency`、`look_ahead smoothing rate`、`shake decay_tau`、`shake noise_freq`、`impulse decay_tau`),逐个核对是否用"每秒"单位。然后在 60 Hz 和 144 Hz 下录制同一段操作,用脚本对比两条相机轨迹在时间轴上的差异。代码正确时差异应小于 5%;有参数漏了 dt 时修复后差异应归零。把审计过程和发现的问题写成简短报告。

## 10 · 延伸阅读与下一篇

相机不是孤立存在的——它是玩家感官系统的一部分。下面材料把相机放回更大语境:

- **Steve Swink《Game Feel》(2009)**——本篇 calibration 出处。Swink 用整章讲相机,提出 "camera is the player's eyes" 心智模型,详细分析 Super Mario 64、Guitar Hero 的相机参数。游戏手感领域圣经。
- **Squirrel Eiserfeld "Juice It or Lose It" (GDC Europe 2013)**——震屏 trauma 模型源头演讲。YouTube 有完整视频,必看。
- **Vlambeer "The Art of Screenshake" (GDC 2013)**——Nuclear Throne 的相机和震屏设计哲学。
- **GDC 2015 "A Tour of Hedgehog Dev Tools"**——Sonic 系列相机调试工具,展示 AAA 平台游戏怎么调 deadzone。
- **[camera-systems](../../phase-3/deep-dives/camera-systems.md)**(phase-3)——本篇前置,讲 view matrix、四元数、sphere sweep 这些**地基**。跳过它本篇 spring 和震屏代码能看懂,但相机碰撞、cinematic 切换、HiDPI 处理会接不上。
- **[game-feel-01-input-and-timing-feel](./game-feel-01-input-and-timing-feel.md)**(本系列 part 1)——输入延迟、输入缓冲(input buffering)、土狼时间(coyote time)。相机是输出端手感,输入端手感同样关键。
- **[game-feel-03-feedback-juice](./game-feel-03-feedback-juice.md)**(本系列 part 3,下一篇)——把相机震屏和 hitstop、粒子、color flash、音效**编排**成连贯的"打击时刻"。本篇讲震屏本身,part 3 讲震屏怎么和其他反馈协同。
- **[game-feel-04-animation-and-control-feel](game-feel-04-audio-and-polish.md)**(本系列 part 4)——动画手感与控制手感。相机的 look-ahead 和角色动画 root motion 有微妙耦合,part 4 会展开。
- **[particle-systems-cpu](../../phase-3/deep-dives/particle-systems-cpu.md)**(phase-3)——震屏通常和粒子一起出现(爆炸 = 震屏 + 粒子 + 音效)。这篇讲粒子系统的工业实现。
- **[09B-4 CVar 调参](../../phase-9/09B-4-cvars-and-dev-console.md)**(phase-9)——本篇第 7 节依赖的 CVar 系统。如果引擎还没有运行时参数修改能力,这篇是必读前置。
- **[accessibility-short](../../phase-7/deep-dives/accessibility-short.md)**(phase-7)——震屏的可访问性。本篇第 4.3 节反复强调的"必须给关闭选项"在这里完整讨论。

**下一篇**:[game-feel-03-feedback-juice](./game-feel-03-feedback-juice.md)——从单个反馈元素(震屏、粒子、hitstop)走向"反馈编排"。我们会拆解 Celeste 的一个完整"打击时刻":从玩家按攻击键那一帧开始,逐毫秒分析音效、粒子、震屏、hitstop、color flash 各自在什么时刻触发、持续多久、怎么相互错峰,最终合成一个让玩家"心跳加速"的瞬间。相机震屏是其中一环,但只是其中一环。

相机手感是游戏开发里最"玄学"的部分——它没有任何公式,完全靠反复玩反复调。但正因为如此,它是区分"能跑的游戏"和"好玩的商业作品"的最大分水岭之一。能跑但相机僵硬的游戏,玩家玩 10 分钟就放弃;相机手感调到位的游戏,玩家会不知不觉玩 10 小时。把这一篇的代码全部接到 HH 里,把所有参数挂 CVar,**接下来一周每天玩半小时边玩边调**——一周后你的 HH 会感觉像换了一个人做的。
