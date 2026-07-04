
# 运动学角色控制器

> 你跟着 [physics-engine-complete](physics-engine-complete.md) 写完了 500 行 Rust 物理引擎,Sequential Impulse 跑通了 4-body stack,你觉得自己懂物理了。今天你想把玩家做成游戏里的角色——你给玩家挂一个 dynamic rigid body,加 capsule collider,加 friction,加 lock_rotations。然后你按 WASD,角色动了。你松开 W,角色没停——它在地上滑行 0.3 秒才停(动量)。你按 D 想右转撞墙,角色斜着撞上去,瞬间被卡死,不再沿墙滑动(摩擦)。你走到斜坡上,角色慢慢往下滑。你看到楼梯想爬上去,角色一头撞在第一级台阶上。你按空格想跳,角色没反应——因为脚下其实"飘着" 1mm,ground detection 失败。你看着屏幕,角色像一个醉酒的箱子。它**根本不像一个角色**。
> 这一节告诉你:这个问题的根本不是参数调不对,而是**模型选错了**。玩家角色不是物理意义上的刚体——它是**游戏意义上的角色**。游戏工业对"角色"发明了一个完全不同的运行模型:**kinematic character controller**(运动学角色控制器,KCC)。它**主动欺骗物理引擎**,在精确性和手感之间,选择手感。今天我们从零写一个,在 HH 项目里跑起来,亲手感受那种"瞬间停住、贴墙滑动、爬楼梯、站斜坡"的手感差异。

## 0 · 为什么"刚体角色"是错的模型

先把错误示范讲清楚。你给玩家挂的那个 dynamic rigid body 有四个关键性质:它有**质量**(mass)和**质心**(center of mass),力对它做加速度 `a = F/m`;它有**动量**(momentum)`p = mv`,松手之后动量不会瞬间消失,要靠摩擦力慢慢消耗;它有**转动惯量**(moment of inertia),即使 `lock_rotations`,碰撞冲量施加在质心之外的接触点仍会产生力矩 `τ = r × F`;它受 **Coulomb 摩擦**约束 `|摩擦力| ≤ μN`,斜坡上 `N = mg·cos(θ)` 随坡度减小,坡度一大重力分量 `mg·sin(θ)` 超过 `μN`,角色就滑下去。

这四条性质对**箱子**是对的——箱子就是物理对象。但对**玩家控制的角色**全是错的。玩家期望:松开摇杆角色**立刻停下**(不要动量);推摇杆角色**朝那个方向走**(不被斜坡拽偏);撞墙斜着过去角色**沿墙滑动**(不被摩擦拽死);看到楼梯角色**自己爬上去**;站在 30° 斜坡角色**稳稳站住**。刚体物理一条都满足不了。这就是为什么**所有手感好的平台跳跃 / 动作 / FPS 游戏,玩家角色都不用 dynamic rigid body**。它们用的是 KCC。

**Kinematic**(运动学)在这里是个特定术语。物理引擎里物体分三种:**dynamic**(动态,受力学定律驱动)、**static**(静态,永远不动)、**kinematic**(运动学,由代码直接指定位置/速度,物理引擎不施加力学定律,但其他 dynamic 物体可以和它碰撞)。KCC 让玩家是 kinematic——它的位置不由 `F = ma` 决定,而由你的代码直接 `position += displacement` 决定。物理引擎**不再模拟角色**,角色成了代码"手动驾驶"的对象。

但"手动驾驶"不等于"无视世界"。角色还是要踩在地上不掉下去,还是不能穿墙,撞到箱子还是要把它推开。所以 KCC 的核心矛盾是:**位置由代码控制,但碰撞由物理世界约束**。怎么调和?这就是 KCC 算法要做的事。

## 1 · KCC 的心智模型:把角色当作"查询形状"

抽象掉所有细节,KCC 每帧的工作流程是这样的。第一步,**算位移**——你的代码根据输入算出"角色这一帧想往哪里走",一个 `Vec3 displacement`。这一步**完全不碰物理**,纯游戏逻辑。第二步,**扫描碰撞**——把这个胶囊从当前位置沿 `displacement` 滑过去,问物理引擎:"这一路上撞到了什么?"这叫 **capsule sweep**(胶囊扫描)或 **shape cast**(形状投射)。第三步,**滑动**——如果撞到了,不能简单停在碰撞点。要把 `displacement` **投影到碰撞面的切线方向**上,继续沿切线走剩余距离。这就是"贴墙滑动"的来源。第四步,**迭代**——一次扫描+滑动可能没把整段位移消化完(撞到墙之后沿墙滑动又会撞到另一堵墙)。所以要循环,直到位移消化完或迭代次数耗尽。第五步,**检测地面**——移动结束后向下扫一小段距离,看脚下有没有地面。

这是 **KCC 的全貌**。它和 [physics-engine-complete](physics-engine-complete.md) 里 dynamic rigid body 的根本差异在于:**dynamic body 是物理引擎被动地响应外界**,**KCC 是你的代码主动地查询世界然后自己决定走法**。前者像开车(踩油门,车自己响应路面),后者像走路(你看见地,自己抬脚)。走路的手感更像"角色"。

为什么是**胶囊(capsule)**而不是 box?回想 [voxel-collision](../../phase-8/deep-dives/voxel-collision.md) 里 Casey 把玩家从 AABB 换成 sphere 的理由:球在拐角处法线连续,AABB 在拐角只有 6 个轴方向。胶囊是 3D 版本的"球"——它是一根线段 + 半径,等价于"沿线段每个点都是个球"。胶囊的接触法线在拐角、楼梯边、斜坡交界处都是连续的,所以角色在那些地方过渡平滑。如果用 box,角色踩到楼梯边会"咯噔"一下——box 的角碰到台阶边,法线突变,角色被弹一下。这就是为什么所有现代 KCC 用胶囊。

下面把 KCC 拆成五个子问题——slide / slope / step / ground / ceiling——一个一个写。

## 2 · 子问题全景

**Slide**(沿墙滑动):角色撞墙后,把剩余位移投影到墙的切线。比如位移 `(1, 0, 0.5)`,撞到法线 `(1, 0, 0)` 的墙。投影后剩余 `(0, 0, 0.5)`——角色沿墙向北滑动。这一步是 KCC 手感的灵魂。

**Slope**(坡度处理):地面法线 `n` 和"上方向" `(0,1,0)` 的夹角就是坡度。低于 `max_walk_angle`(比如 45°)的坡角色可以站;高于的坡,角色滑下去(或者根本不被认作"地面",被 slide 当墙处理)。

**Step**(台阶处理):游戏世界有楼梯、马路牙子、地上的小石头。这些对 KCC 是"小障碍"——不应该阻挡角色,应该被"跨过"。算法:角色撞到一个低矮的东西(比如 0.3m 的台阶),先试着把角色抬到台阶高度,再向前扫描。如果抬起来之后能过去,就"跨"上去。

**Ground**(地面检测):每次移动后向下扫描一小段距离(比如 0.1m),看脚下有没有地面。有则 `on_ground = true`,角色可以跳;没有则进入空中状态。这一步还顺便给 slope 提供"我站在什么坡度的坡上"。

**Ceiling**(头顶检测):角色跳起来撞到天花板,这一帧的向上位移要被取消(不然角色头顶"穿"进天花板)。和 slide 类似,只是方向反过来。

这五个子问题相互交织——step 检测要在 slide 之前先做(否则 step 被当墙挡住),slope 要在 ground 检测时一起做(看地面法线)。整个 KCC 的工程难度不在于单个算法,而在于**把这五个流程串起来不互相打架**。

## 3 · 核心查询:胶囊扫描(capsule sweep)

KCC 一切的基础是**胶囊扫描**:给一个胶囊(线段 + 半径),一个起始位置,一个位移,问物理引擎——这一路上,胶囊最早在 `t ∈ [0, 1]` 的什么位置碰到东西?碰到的法线是什么?

数学上,这等价于"胶囊沿位移做 Minkowski 扫掠,求扫掠体和世界的最近交点"。物理引擎把这个封装成 API,你不写底层,只调用。Rapier 的 API 叫 `query_pipeline.cast_shape(...)`,PhysX 的叫 `sweep()`,Unity 的 PhysX binding 叫 `CapsuleCast`。它们都返回 `time_of_impact`(toi,标量 0 到 1)+ `hit_normal`(碰撞法线)。

```rust
/// 一次胶囊扫描。返回最早碰撞的 toi (0..=1) 和法线。
/// 如果整段位移都没碰撞,返回 None。
pub fn capsule_sweep(
    physics: &PhysicsWorld,
    capsule_segment_a: Vec3,
    capsule_segment_b: Vec3,
    radius: f32,
    displacement: Vec3,
) -> Option<SweepHit> {
    let shape = rapier3d::geometry::Capsule::new(capsule_segment_a, capsule_segment_b);
    let pose = rapier3d::math::Isometry3::translation(/* 玩家当前世界位置 */);
    physics.query_pipeline.cast_shape(
        &physics.bodies, &physics.colliders,
        &pose, &displacement.into(),
        &shape, rapier3d::pipeline::QueryFilter::default()
            .exclude_rigid_body(player_handle),
    ).map(|(collider_handle, hit)| SweepHit {
        toi: hit.time_of_impact,
        normal: hit.normal1.into(),
        collider: collider_handle,
    })
}

pub struct SweepHit {
    pub toi: f32,         // 0..=1,1 表示整段位移都没碰
    pub normal: Vec3,
    pub collider: ColliderHandle,
}
```

`toi`(time of impact)是 0 到 1 之间的标量,0 表示"已经在接触",1 表示"整段位移都没碰"。如果 `toi = 0.6`,意思是位移的前 60% 是自由的,后 40% 被挡住——所以你可以走 `displacement * 0.6` 这么远,然后处理碰撞。`toi` 为什么叫"时间"?因为它原本是连续碰撞检测(CCD)的术语——见 [physics-engine-complete](physics-engine-complete.md) 第 7 节。KCC 的胶囊扫描本质上就是一种 **sweep-based CCD**:不依赖离散采样,而是把整段位移当作一条"扫掠体",和世界做几何求交。这就是为什么 KCC **不会有 tunneling 问题**——它天生就是连续的。

注意一个关键细节:大多数物理引擎的 `cast_shape` 返回的 `toi` 是**保守的(conservative)**——它返回的碰撞点可能比真实最近点稍微"早一点"。结果是你可能"在真正撞墙之前一点点就停下",留下 1-2mm 的缝隙。KCC 通常加一个 `skin_width`(皮肤宽度,通常 0.01m),把胶囊半径稍微放大,扫描时用大半径,实际位置用小半径——把缝隙吸收掉。Unity 的 CharacterController 有 `skinWidth` 参数就是干这个的。

## 4 · 把位移消化掉:slide 算法

现在写 KCC 的主循环——把"想走的位移"消化成"实际走的位移"。算法叫 **slide**(滑动)或 **move and slide**。

```rust
/// KCC 的主移动函数。把 desired_displacement 尽量消化,沿墙滑动。
pub fn move_and_slide(
    physics: &PhysicsWorld,
    player: &mut Player,
    desired_displacement: Vec3,
) -> Vec3 {
    let mut remaining = desired_displacement;
    let mut total_moved = Vec3::ZERO;
    const MAX_ITERATIONS: u32 = 4;
    const EPSILON: f32 = 1e-4;

    for _ in 0..MAX_ITERATIONS {
        if remaining.length_squared() < EPSILON * EPSILON { break; }

        let Some(hit) = capsule_sweep(
            physics,
            player.capsule_a(), player.capsule_b(), player.radius,
            remaining,
        ) else {
            player.position += remaining;
            total_moved += remaining;
            break;
        };

        // 沿 hit.toi 走完能走的部分(留一点 skin 防穿模)
        let safe_t = (hit.toi - 0.001f32).max(0.0);
        let safe_move = remaining * safe_t;
        player.position += safe_move;
        total_moved += safe_move;

        // 把剩余位移投影到碰撞面的切线
        // tangent = leftover - (leftover · n) * n
        let consumed = remaining * safe_t;
        let leftover = remaining - consumed;
        let n = hit.normal.normalize();
        remaining = leftover - n * leftover.dot(n);
    }
    total_moved
}
```

仔细看投影那一步。`leftover · n` 是 `leftover` 在法线方向上的分量(法线方向是被挡住的方向)。`leftover - (leftover · n) * n` 把这个分量减掉,剩下的就是切线分量——也就是"沿墙方向还能走多少"。这就是 **slide 投影**。

举个具体例子。位移 `(1, 0, 1)`(45° 斜向),撞到法线 `(1, 0, 0)` 的墙。`toi = 0.5`,意味着走到一半就撞上。前一半位移 `(0.5, 0, 0.5)` 自由走过去。后一半 `(0.5, 0, 0.5)`,法线方向分量 `0.5`,减掉变成 `(0, 0, 0.5)`——所以角色继续向北走 0.5。最终总位移 `(0.5, 0, 1.0)`。如果你不投影,角色会在墙前面停住,总位移 `(0.5, 0, 0.5)`——这就是"被卡住"的体验。投影之后,角色"滑过"了墙的拐角。

为什么有 `MAX_ITERATIONS`?因为 slide 之后可能又撞到另一堵墙。比如角色在 L 形拐角里,先撞东墙 slide 向北,又撞北墙 slide 向东(实际无路可走)。迭代到第 4 次就放弃,剩余位移丢弃。4 次通常够——超过 4 次基本就是被夹死了。`0.001f32` 那个 skin 让角色"差一点点"才撞到墙,留 1mm 缝隙——这是为了下一帧扫描不被浮点误差坑(上一帧贴墙的话,下一帧 `toi` 可能算成 0,角色被钉死)。

## 5 · 地面检测:我站在哪?

`move_and_slide` 之后,角色已经在新位置了。下一步:判断**是不是站在地面上**,以及**地面的法线是什么**(决定坡度)。算法:从胶囊底部向下扫一小段距离。如果碰到东西,`on_ground = true`,记录法线。

```rust
pub struct GroundInfo {
    pub on_ground: bool,
    pub normal: Vec3,
    pub slope_angle: f32,    // 弧度,0 = 平地,π/2 = 垂直墙
    pub is_walkable: bool,   // slope_angle < max_walk_angle
    pub point: Vec3,
}

pub fn detect_ground(
    physics: &PhysicsWorld,
    player: &Player,
    max_walk_angle: f32,
) -> GroundInfo {
    let probe_distance = 0.15;
    let probe_dir = Vec3::new(0.0, -1.0, 0.0);
    let hit = capsule_sweep(
        physics,
        player.capsule_a(), player.capsule_b(), player.radius,
        probe_dir * probe_distance,
    );
    match hit {
        Some(h) => {
            let normal = h.normal.normalize();
            let up = Vec3::new(0.0, 1.0, 0.0);
            let cos_angle = normal.dot(up).clamp(-1.0, 1.0);
            let slope_angle = cos_angle.acos();
            GroundInfo {
                on_ground: h.toi < 1.0, normal, slope_angle,
                is_walkable: slope_angle < max_walk_angle,
                point: player.position + probe_dir * probe_distance * h.toi,
            }
        }
        None => GroundInfo {
            on_ground: false, normal: up, slope_angle: 0.0,
            is_walkable: false, point: player.position,
        },
    }
}
```

为什么用 capsule sweep 而不是 ray cast 做地面检测?因为 ray 是一条无宽度的线,玩家站在斜坡边沿时,ray 可能从胶囊底部"漏"到斜坡外面,误判 `on_ground = false`,触发不该有的"下落"动画。胶囊有宽度,扫的时候整个胶囊底部都参与,边沿检测更稳。这是 [voxel-collision](../../phase-8/deep-dives/voxel-collision.md) 里 Casey 用 sphere 而不是 point 的同款道理——各向同性的形状对抗浮点抖动。

**max_walk_angle** 怎么定?经验值 45°(π/4)。陡于 45° 视为墙,角色走不上去;缓于 45° 视为可走斜坡。游戏里会细分——30° 以下完全自由,30°-45° 可以走但速度减半,45° 以上滑下去。这些参数都通过 [09B-4 CVars](../../phase-9/09B-4-cvars-and-dev-console.md) 实时调。

## 6 · 把坡度做对手感才对

地面检测告诉我们 slope_angle,但**怎么用这个信息决定角色行为**才是 KCC 手感的关键。最朴素的思路:如果 `is_walkable` 正常移动,否则把这一面当墙处理。但这有个**致命问题**——你站在 44° 的可走斜坡上,下一帧重力把角色往下推 0.1m,胶囊扫描向下扫到斜坡,toi = 0.001(几乎贴着),slope_angle = 44°,walkable,所以 `on_ground = true`。但角色的 y 位置已经下移了 0.1m × 0.001 ≈ 0.0001m——这一帧掉一点点,下一帧又掉一点点。**角色缓慢地从斜坡上往下"渗"**。

这就是经典的 "slope slide" bug。解决方案:**在 walkable 斜坡上,把重力位移直接置零**。KCC 是 kinematic,不受力——重力由你的代码"模拟":

```rust
pub fn apply_gravity_for_kcc(
    player: &mut Player,
    ground: &GroundInfo,
    gravity: Vec3,
    dt: f32,
) -> Vec3 {
    if ground.on_ground && ground.is_walkable {
        Vec3::ZERO  // walkable 坡度上重力位移为零——角色被斜坡"托住"
    } else {
        player.velocity_y += gravity.y * dt;
        Vec3::new(0.0, player.velocity_y * dt, 0.0)
    }
}
```

这段代码的关键决定:**walkable 坡度上重力位移为零**。这"违反物理"(真实物理里坡上的物体仍受重力),但对游戏手感**正确**——玩家站在 30° 坡上,期望角色站稳不滑。如果游戏确实想模拟"陡坡上滑下来"(比如滑雪游戏),把 walkable 阈值调高,或者用更细的分层。

另一个常见 trick:**snap to ground**(吸附到地面)。角色在缓坡上行走时,每帧把角色 y 位置"贴"到地面高度,这样角色不会因为坡度的微小起伏而上下颠簸:

```rust
pub fn snap_to_ground(player: &mut Player, ground: &GroundInfo) {
    if ground.on_ground && ground.is_walkable {
        let capsule_bottom_y = player.position.y - player.capsule_half_height;
        let correction = ground.point.y - capsule_bottom_y;
        if correction.abs() < 0.1 {
            player.position.y += correction;  // 只在小范围内 snap
        }
    }
}
```

`snap_to_ground` 是 KCC 手感的一个隐藏冠军——它让角色下坡时不会"飘":每帧重力把角色往下推一点,snap 把它贴回地面,看起来平滑。

## 7 · 台阶:让角色会爬楼梯

写完 slide 和 slope,你的角色已经能跑、能跳、能贴墙滑、能站坡。但它**还是过不了楼梯**。每级台阶对 KCC 是一面 0.2m 高的墙——`capsule_sweep` 看到"墙",返回 `toi` 很小,角色被挡住。解决方法:**step detection**——在常规 slide 之前,先检测:如果挡住角色的是个**低矮的东西**(高度 < max_step_height),试着把角色抬高再扫一次。

```rust
pub const MAX_STEP_HEIGHT: f32 = 0.3;  // 30cm,典型楼梯台阶高度

pub fn try_step_up(
    physics: &PhysicsWorld,
    player: &mut Player,
    desired_displacement: Vec3,
) -> bool {
    let hit = capsule_sweep(
        physics, player.capsule_a(), player.capsule_b(),
        player.radius, desired_displacement,
    );
    let Some(_hit) = hit else { return false; };

    // 把胶囊抬到 max_step_height,再扫一次,看能不能过
    let mut player_raised = player.clone();
    player_raised.position.y += MAX_STEP_HEIGHT;
    let hit_raised = capsule_sweep(
        physics, player_raised.capsule_a(), player_raised.capsule_b(),
        player_raised.radius, desired_displacement,
    );
    if hit_raised.is_some() {
        return false;  // 抬高了还被挡——是高墙,不是台阶
    }

    // 抬高之后能过——是台阶。先抬上去,再向前移,再下落到台阶表面
    player.position.y += MAX_STEP_HEIGHT;
    player.position += desired_displacement;

    let down_probe = Vec3::new(0.0, -MAX_STEP_HEIGHT, 0.0);
    if let Some(ground_hit) = capsule_sweep(
        physics, player.capsule_a(), player.capsule_b(),
        player.radius, down_probe,
    ) {
        player.position += down_probe * ground_hit.toi;
    }
    true
}
```

注意第 2 步——**先抬高 max_step_height 再扫,如果不再被挡,才确认是台阶**。否则你给 KCC 一个 max_step_height = 0.3m,它会把 0.3m 高的矮墙也当台阶爬过去——这是 bug。工业级实现更精细——它先做 ray cast 探测障碍物的**实际高度**,只在确认"高度 < max_step_height 且不是 walkable slope"时才走 step 路径。Unity 的 CharacterController、Unreal 的 UCharacterMovementComponent 都有这种精细逻辑。

step 是 KCC 里最容易出 bug 的部分。常见症状:**角色在楼梯上"咯噔咯噔"**(每次 step 都有 y 突变)、**角色蹭台阶边沿后弹起来**、**角色在楼梯上速度变慢**。修复这些手感问题需要反复调 max_step_height、step 之后的 snap 速度、以及和动画系统的衔接。

## 8 · 把五件事拼起来:完整 KCC 主循环

下面把 slide、slope、step、ground 拼成完整的 KCC 每帧流程。Ceiling 检测嵌在 slide 里(撞到天花板时 slide 会自然处理——把向上分量投掉)。

```rust
pub fn update_character(
    physics: &PhysicsWorld,
    player: &mut Player,
    input: &InputState,            // 见 game-feel-01 / input-handling-for-games
    config: &CharacterConfig,      // 通过 CVar 配置,见 09B-4
    dt: f32,
) {
    // 阶段 1:根据输入算 desired_displacement
    let input_dir = compute_input_direction(input);
    let target_vel = input_dir * config.max_speed;
    let accel = if input_dir.length_squared() > 0.0 { config.ground_accel }
                else { config.ground_decel };
    let horizontal_vel = approach(player.horizontal_vel, target_vel, accel * dt);
    player.horizontal_vel = horizontal_vel;

    let ground = detect_ground(physics, player, config.max_walk_angle);
    let was_on_ground = player.on_ground;
    player.on_ground = ground.on_ground;

    if !ground.on_ground || !ground.is_walkable {
        player.velocity_y -= config.gravity * dt;
    } else {
        player.velocity_y = 0.0;
    }

    let can_jump = ground.on_ground
        || (was_on_ground && player.time_since_ground < config.coyote_time);
    if input.jump_pressed && can_jump {
        player.velocity_y = config.jump_velocity;
        player.on_ground = false;
    }

    let desired = Vec3::new(
        horizontal_vel.x * dt, player.velocity_y * dt, horizontal_vel.z * dt,
    );

    // 阶段 2:move_and_slide 消化位移
    let moved = move_and_slide(physics, player, desired);

    // 阶段 3:如果没动够,试 step
    let desired_h = (desired.x * desired.x + desired.z * desired.z).sqrt();
    let moved_h = (moved.x * moved.x + moved.z * moved.z).sqrt();
    if desired_h > moved_h + 1e-3 {
        let h_remaining = Vec3::new(desired.x - moved.x, 0.0, desired.z - moved.z);
        try_step_up(physics, player, h_remaining);
    }

    // 阶段 4:更新 ground 状态,snap
    let ground_after = detect_ground(physics, player, config.max_walk_angle);
    player.on_ground = ground_after.on_ground;
    player.ground_normal = ground_after.normal;
    player.time_since_ground = if ground_after.on_ground { 0.0 }
                               else { player.time_since_ground + dt };
    if ground_after.on_ground && ground_after.is_walkable {
        snap_to_ground(player, &ground_after);
    }
}

fn approach(current: Vec3, target: Vec3, max_delta: f32) -> Vec3 {
    let diff = target - current;
    let diff_len = diff.length();
    if diff_len <= max_delta { target }
    else { current + diff * (max_delta / diff_len) }
}
```

仔细看阶段 3——**step 在 move_and_slide 之后**。这是个工程决定:大多数情况 move_and_slide 就够了(平地、坡、墙),只在"水平位移没消化完"时才走 step。这样 step 的开销只在需要时才付,性能更好。同时 step 只处理水平剩余位移(不让 step 影响垂直——跳跃不该被 step 干预)。

阶段 4 的 `time_since_ground` 是 **coyote time**(郊狼时间)——玩家离开地面后,短时间内还能跳。这是平台跳跃游戏的标配手感,见 [game-feel-01](../../phase-2/deep-dives/game-feel-01-input-and-timing-feel.md)。`coyote_time` 通常 0.1-0.2s。

阶段 1 的 `approach` 函数是**加速度曲线**的核心——它让水平速度不是瞬切,而是逐渐从当前值变到目标值。`ground_accel` 控制起步多快,`ground_decel` 控制停下多快。这就是为什么松开 W 键角色"快速停下但不瞬切"——`ground_decel` 大于 `ground_accel`。这两个值是 game feel 的灵魂参数,见 [game-feel-short](../../phase-2/deep-dives/game-feel-short.md)。

## 9 · 与物理世界交互:推动 dynamic 物体

到这里 KCC 自己能动了,但它还是孤立的——撞到箱子,箱子不动。KCC 是 kinematic,默认和 dynamic 物体**单向交互**(dynamic 物体能挡住 kinematic,但 kinematic 不能推动 dynamic)。这就失去了"角色撞翻箱子"的手感。修复:KCC 每次 sweep 命中 dynamic 物体时,**手动给它施加一个冲量**。

```rust
/// 在 move_and_slide 里,每次 hit 命中时调用
pub fn push_dynamic_body_on_hit(
    physics: &mut PhysicsWorld,
    hit: &SweepHit,
    player_velocity: Vec3,
    player_mass: f32,
) {
    let Some(collider) = physics.colliders.get(hit.collider) else { return; };
    let Some(body_handle) = collider.parent() else { return; };
    let Some(body) = physics.bodies.get_mut(body_handle) else { return; };
    if !body.is_dynamic() { return; }

    let normal_velocity = player_velocity.dot(hit.normal);
    if normal_velocity < 0.0 {
        let impulse_magnitude = -normal_velocity * player_mass;
        body.apply_impulse(hit.normal * impulse_magnitude, true);
    }
}
```

这个 trick 让 KCC 处于**混合模式**:对玩家自己的运动,KCC 是 kinematic(代码直接控制位置);对世界中的 dynamic 物体,KCC 像一个"无穷质量的 dynamic body"(推别人但自己不被反推)。这正是 [physics-engine-complete](physics-engine-complete.md) 第 9.3 节里 lock_rotations + friction=0 那个玩家的进化版——前者还是 dynamic body(受力学),后者干脆 kinematic(完全代码控制)。`player_mass` 是个**虚拟量**——因为 KCC 不是真的 dynamic body,它没质量。这个值决定"推箱子的力度",Unity 的 CharacterController 有 `mass` 属性就是这个,默认 1.0。

## 10 · 工程坑与调试叙事

KCC 是 game feel 的"瓶颈代码"——所有手感 bug 都从这里冒出来。下面是工业项目里反复出现的几个坑。

**卡在墙角(slide 失效)**。症状:角色斜着冲向 L 形墙拐角被卡住。诊断:`MAX_ITERATIONS` 不够。L 形拐角要先撞东墙 slide 向北,再撞北墙 slide 向东——两次迭代就到极限。修复:把 `MAX_ITERATIONS` 提到 6 或 8。但不要无限迭代——如果真被夹死,迭代再多也出不来,反而卡 CPU。加个 `remaining.length() < epsilon` 提前退出。

**跳跃后悬空一帧**。症状:玩家按空格起跳,起飞那一帧画面"顿"了一下。诊断:跳跃修改了 `velocity_y`,但起跳那一帧仍然跑了 `detect_ground`,而 `on_ground` 还是 true(重力还没把角色拉离地面),`velocity_y` 又被清零。修复:跳跃后立即把 `on_ground` 置 false。或把清零条件改成 `ground.on_ground && player.velocity_y <= 0.0`。

**站在斜坡边沿掉下去**。症状:角色从平台走到斜坡边沿,本来应该顺坡下去,结果"掉"进空中。诊断:`detect_ground` 的 probe 距离太短。胶囊底部正好"骑"在斜坡边,probe 0.15m 向下扫可能扫到斜坡外面。修复:把 probe 距离调到 0.3m;或用 sphere overlap 而不是 sweep;或引入 coyote time 容错。

**撞墙时角色"弹一下"**。症状:角色高速撞墙,撞墙瞬间被弹回一小段。诊断:`skin` 那个 `0.001f32` 在高速时不够。胶囊其实穿透了墙 0.001m,下一帧 slide 把胶囊推回去,产生"弹"的视觉。修复:把 skin 提到 `0.01f32`;或用 **speculative contact**——见 [physics-engine-complete](physics-engine-complete.md) 第 7.3 节。

**Step 之后角色上下颠簸**。症状:角色在楼梯上爬,每爬一级台阶 y 坐标抖一下。诊断:step 算法把角色抬高 max_step_height(0.3m),如果实际台阶只有 0.15m,角色多抬了 0.15m,然后"砸"下来。修复:step 之前先 ray cast 测出障碍物的**实际高度**,只抬到实际高度;或引入 step 速度限制——每帧最多抬 0.1m,几帧才完成一个 step。

**数值 NaN**。症状:角色位置突然变 NaN。诊断:某次 capsule sweep 返回的法线是零向量(物理引擎在退化几何上的 bug),`n.normalize()` 是 NaN,传播到所有计算。修复:`if normal.length_squared() < 1e-10 { return default; }`。这是 [physics-engine-complete](physics-engine-complete.md) 第 11.1 节的同款教训——NaN 静默传播,防御性检查是 KCC 代码的标配。

## 11 · 跨学科联结

KCC 不只是物理,它在多个游戏子系统的交叉点上。

**和动画系统**:KCC 的输出 `on_ground`、`horizontal_vel`、`slope_angle`、`is_stepping` 是动画状态机的输入。如果 KCC 状态抖动(`on_ground` 在边沿反复 true/false),动画也跟着抖——出现"忽站忽跳"的抽搐。解法:**KCC 状态加迟滞**(hysteresis),`on_ground` 从 true 变 false 需要持续 false 几帧。

**和网络同步**:多人游戏里,客户端要预测其他玩家的位置。KCC 是确定性的——给定输入序列,位置序列可复现。但浮点不一致(不同 CPU)会导致预测漂移。见 [network-prediction-and-rollback](../../phase-5/deep-dives/network-prediction-and-rollback.md)。KCC 的迭代次数、slide 投影顺序,都要在客户端和服务端一致。

**和游戏手感**:KCC 的本质是 game feel 的代码层。所有"这游戏手感好/差"的判断,最终落到 KCC 的几个参数——`max_speed`、`ground_accel`、`ground_decel`、`air_accel`、`coyote_time`、`jump_velocity`、`max_walk_angle`、`max_step_height`。这些参数应该全部通过 [CVars](../../phase-9/09B-4-cvars-and-dev-console.md) 暴露,设计师在游戏运行时实时调,调到满意为止。

**和固定时间步**:KCC 的迭代算法在 dt 变化时行为不同——dt 大时一帧位移长,可能跳过墙的薄处;dt 小时迭代多但精度高。这就是为什么 KCC **必须在固定时间步下运行**——见 [09B-1 game loop and timestep](../../phase-9/09B-1-game-loop-and-timestep.md)。`physics.step()` 跑在 fixed timestep 上,渲染用插值平滑。

## 12 · 工业实践对比

**Unity CharacterController**:最经典的 KCC 实现。`CharacterController.Move(displacement)` 内部就是 move_and_slide + step + slope。参数 `slopeLimit`、`stepOffset`、`skinWidth` 都是上面讲过的概念。closed-source(C++ 底层),你不能改算法,只能调参数。

**Unreal UCharacterMovementComponent**:比 Unity 更复杂,支持游泳、飞行、爬梯子、行走等多种模式。`FindFloor`(找地面)、`MoveAlongFloor`(沿地面走)、`StepUp`(爬台阶)等函数和我们写的一一对应。open(C++ 源码可读),你可以 fork 改算法。

**Havok hkCharacterController**:商业引擎,质量最高。支持角色穿窄缝、复杂碰撞响应、和动画的紧密集成。AAA 大作标配。

**Bevy + bevy_rapier 的 KCC**:Rust 生态。Rapier 没自带 KCC,你要么自己写(用 `QueryPipeline::cast_shape`),要么用社区 crate。我们这一节的代码就是 bevy_rapier 风格的 KCC。

**Handmade Hero 的角色控制**:Casey 在 HH 里**不写完整 KCC**——他用 [voxel-collision](../../phase-8/deep-dives/voxel-collision.md) 的 sphere + iterative unembed,游戏逻辑层直接控制位置。这是"KCC 思想的极简实现"——不做 sweep,只做 unembed。优点:代码极短(< 500 行);缺点:没有 slide(撞墙就停),没有 step(走不了楼梯)。Casey 的游戏是 zelda-like,不需要复杂平台跳跃,所以够用。如果你做 platformer,需要完整的 KCC。

## 13 · 在你 HH 项目里动手(做中学红线)

这一节把上面的算法落地到你 HH 项目。假设你已经完成 [physics-engine-complete](physics-engine-complete.md),在 HH 里集成了 Rapier。

**第一周:从 dynamic body 切到 kinematic**。第 1 天,把玩家的 `RigidBody::Dynamic` 改成 `RigidBody::KinematicPositionBased`。运行游戏,角色不再受重力——它停在原地。这是预期行为——KCC 不受力,完全由代码控制。第 2-3 天,写最小 `move_and_slide`:只做 sweep + slide 投影,没有 slope / step / ground。代码 ~80 行。运行游戏:角色能走、能贴墙滑动,但一松开 W 就瞬停。**这一刻你已经感觉到 KCC 和 dynamic body 的差别**——dynamic body 那种"惯性滑行"消失了。第 4 天,加 `detect_ground`(~30 行)。打印 `on_ground` 状态,跑、跳、看落地时状态变化。第 5 天,加 `apply_gravity_for_kcc` + `snap_to_ground`。角色能站坡、能下坡不颠。**此时你的 KCC 已经超过 80% 业余游戏开发者的角色控制**。

**第二周:加 step,加 push,加 game feel**。第 6-7 天,加 `try_step_up`。搭一个楼梯场景,跑过去,角色自动爬楼梯。这一步最费时——step 的 bug 最多,准备好用 F2 debug overlay(画 capsule、画 hit normal、画 ground normal)反复调。第 8 天,加 `push_dynamic_body_on_hit`。场景里放几个箱子,角色撞过去把箱子撞翻。这是 KCC 和 dynamic world 的连接。第 9-10 天,加加速度曲线(`ground_accel` / `ground_decel` / `air_accel`)、coyote time、jump buffer。这些是 game feel 的灵魂,见 [game-feel-01](../../phase-2/deep-dives/game-feel-01-input-and-timing-feel.md)。把所有参数挂到 [CVars](../../phase-9/09B-4-cvars-and-dev-console.md),运行时调试。

**对比实验:KCC vs dynamic body**。写一个测试场景:同样的地图,两套角色控制。按 F3 切换。玩 5 分钟,记录体验差异:松开摇杆 dynamic body 滑 0.3s 停下,KCC 0.05s 停下;撞墙斜着走 dynamic body 被摩擦卡住,KCC 沿墙滑动;走楼梯 dynamic body 撞台阶,KCC 自动爬;站 30° 坡 dynamic body 缓慢下滑,KCC 稳站;跳起撞天花板 dynamic body 弹一下,KCC 平滑停止向上。这些差异就是 game feel 的具象——它们不是抽象的"手感好/差",而是**具体的、可量化的、可调参的物理行为**。

**CVars 配置示例**:

```rust
fn register_character_cvars(cvars: &mut CVarRegistry) {
    cvars.register_f32("char.max_speed", 8.0, "角色最大水平速度 m/s");
    cvars.register_f32("char.ground_accel", 60.0, "地面加速度 m/s²");
    cvars.register_f32("char.ground_decel", 100.0, "地面减速度 m/s²(>accel 才有快速停下的手感)");
    cvars.register_f32("char.air_accel", 20.0, "空中加速度 m/s²(小于地面,空中操控弱)");
    cvars.register_f32("char.gravity", 25.0, "重力 m/s²(游戏感通常 > 9.81,让跳跃更脆)");
    cvars.register_f32("char.jump_velocity", 9.0, "跳跃初速度 m/s");
    cvars.register_f32("char.coyote_time", 0.15, "郊狼时间 s");
    cvars.register_f32("char.jump_buffer", 0.15, "跳跃缓冲 s(落地前按跳也算)");
    cvars.register_f32("char.max_walk_angle", 0.785, "最大行走坡度 rad(π/4 = 45°)");
    cvars.register_f32("char.max_step_height", 0.3, "最大台阶高度 m");
    cvars.register_f32("char.skin_width", 0.01, "胶囊皮肤宽度 m");
    cvars.register_f32("char.ground_probe", 0.15, "地面探测距离 m");
    cvars.register_f32("char.push_mass", 1.0, "推动 dynamic 物体的虚拟质量");
}
```

设计师在 console 里敲 `char.ground_accel 80`,立刻感觉角色更"敏捷";敲 `char.gravity 35`,跳跃变得更"脆"。这就是参数化手感的威力——所有"这游戏手感对不对"的判断,都落到这十几个数上。

## 14 · 练习

### Lv1 · 概念辨析

用自己的话解释以下三对概念,每个写 50 字:**kinematic body** vs **dynamic body**(在物理引擎语境下);**slide 投影** vs **直接停在碰撞点**(对手感的影响);**walkable slope** vs **non-walkable slope**(KCC 怎么区分对待)。

参考思路(自己先想):dynamic body 受力学定律,kinematic body 由代码直接控制位置;slide 投影让位移沿墙切线继续走,直接停下让玩家被墙完全卡住;walkable slope 视为"地面"(重力置零、可站),non-walkable slope 视为"墙"(用 slide 处理,角色滑下去)。

### Lv2 · 动手实现

在 HH 项目里实现第 4 节的 `move_and_slide` 和第 5 节的 `detect_ground`。要求:在你的 Rapier 集成里调用 `QueryPipeline::cast_shape` 做 capsule sweep;搭一个测试地图:平地 + 一堵墙 + 一个 30° 斜坡 + 一段 3 级楼梯;角色能跑、能贴墙滑、能站坡、能爬楼梯;用 F2 debug overlay 画出 capsule、地面法线、slide 后的实际位移。**完成标准**:跑 5 分钟无 NaN、无穿模、楼梯能爬上去、墙能滑过去、斜坡不滑下。

### Lv3 · 迁移设计

你的 HH 项目里有一个 bug:玩家高速跑过两个相邻 voxel 的接缝时,角色被"卡"了一下。诊断步骤和修复方案是什么?

提示(自己想):接缝处两个 voxel 表面不连续(浮点误差导致微小缝隙/凸起);胶囊扫到接缝的法线是斜的(不是纯垂直);slide 投影把"纯水平"位移投影成"斜向上",角色被推起来一下;解决思路——snap_to_ground 吸收垂直小位移、或用 capsule overlap 而非 sweep 做地面检测。

### Lv4 · 开源贡献

在 GitHub 找一个 Rust 的 KCC 实现(比如 `bevy_character_controller`、`heron`、`bevy_rapier` 的 example)。读源码,找一个能改进的地方:它有没有 step 算法?如果有,实现是不是健壮(会不会被高墙当台阶爬)?它的 slide 投影有没有处理"夹在两面墙之间"的情况?它的 ground detection 是 ray 还是 capsule?写一个 PR draft,提出你的改进方案。

参考方向(不照抄):很多 Rust KCC crate 没有 step,加一个 `try_step_up` 是有价值的 PR;有的 crate 用 ray 做 ground detection,改成 capsule overlap 能解决边沿误判,这也是好 PR。

## 15 · 延伸阅读

### 15.1 内部链接

- [physics-engine-complete](physics-engine-complete.md) — 本篇的物理基础,Sequential Impulse、CCD、约束求解
- [voxel-collision](../../phase-8/deep-dives/voxel-collision.md) — Casey 在 HH 里把 AABB 改 sphere 的重构,展示碰撞抽象的影响
- [collision-detection](../../phase-2/deep-dives/collision-detection.md) — Phase 2 的碰撞检测基础,GJK / EPA / SAT
- [collision-evolution](../../phase-5/deep-dives/collision-evolution.md) — 碰撞系统的演化,从 HH 早期到现代
- [game-feel-01](../../phase-2/deep-dives/game-feel-01-input-and-timing-feel.md) — 输入如何驱动控制器,加速度曲线、coyote time、jump buffer
- [game-feel-short](../../phase-2/deep-dives/game-feel-short.md) — Game feel 的全景,本篇 KCC 是它的代码层
- [09B-1](../../phase-9/09B-1-game-loop-and-timestep.md) — 固定时间步,KCC 必须跑在固定 dt 上
- [09B-4](../../phase-9/09B-4-cvars-and-dev-console.md) — CVars,KCC 的所有参数都通过它实时调
- [input-handling-for-games](../../phase-2/deep-dives/input-handling-for-games.md) — 输入处理,KCC 的 `input` 参数从这来
- [network-prediction-and-rollback](../../phase-5/deep-dives/network-prediction-and-rollback.md) — 多人游戏里 KCC 的网络同步

### 15.2 外部资料

- **Unity CharacterController 文档**:https://docs.unity3d.com/ScriptReference/CharacterController.html — 工业级 KCC 的 API 参考,`Move` / `slopeLimit` / `stepOffset` 等概念都是本篇讨论的。
- **Unreal UCharacterMovementComponent 源码**:UE 源码 `Engine/Source/Runtime/Engine/Private/GameFramework/CharacterMovementComponent.cpp`。强烈推荐读 `FindFloor`、`MoveAlongFloor`、`StepUp` 三个函数。
- **Glenn Fiedler "Kinematic Character Controller"**:https://gafferongames.com/post/physics_in_3d/ — 网络物理大神,有专门的 KCC 章节。
- **Rapier character controller example**:https://github.com/dimforge/rapier/tree/master/examples2d — Rapier 官方的 KCC example,Rust 实现,本篇代码风格参考它。

## 16 · 总结

回到开头那个场景——你的玩家角色像醉酒的箱子。读到这里,你应该知道:那个箱子模型是**错的抽象**——dynamic rigid body 模拟物理对象,KCC 模拟游戏角色,两个抽象解决不同问题。KCC 的核心是**胶囊扫描 + slide + step + slope + ground**,五个子算法各自简单,合起来决定角色手感。KCC 是 kinematic,不受力学定律,代码直接控制位置;但通过 sweep 查询世界,与 dynamic 物体交互。所有"手感参数"通过 CVars 暴露,设计师运行时调,这是 game feel 的工程化。KCC 跑在固定时间步上,dt 必须恒定。Unity / Unreal / Havok 都有官方 KCC,思想都一样,差异在覆盖度和集成深度。

KCC 是 game feel 的"最后一公里"——它不是物理引擎的一部分,它是**游戏代码和物理世界的接口**。理解了它,你就理解了"为什么有些游戏跑起来感觉对、有些感觉错"的工程根源。下次你玩一个手感好的游戏,你能反过来推它的 `ground_accel` / `coyote_time` 大概是多少——这就是工程师看游戏的方式。
