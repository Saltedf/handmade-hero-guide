
# AI 感知与记忆深度专题

> 你跟着 [ai-patterns](../../phase-2/deep-dives/ai-patterns.md) 写完了你的第一个守卫 FSM。守卫在 `Patrol` 状态里走巡逻路径,某帧 `see_player(npc, world)` 返回 true,守卫切到 `Chase`。看起来"有 AI 味"了。但你在测试里发现一件怪事:玩家从守卫背后悄悄走近到 2 米,守卫**瞬间**转身追你;玩家躲进草丛,守卫**仍然**知道你的精确坐标,贴着草丛转圈;玩家从墙后跑到 50 米外,守卫**一路**沿你的真实位置追过来,像 GPS 一样。这就是**全知 AI(omniscient AI)**——它直接读世界里的玩家位置,每帧 60 次更新,无延迟、无遮挡、无遗忘。它既不公平(人类反应不可能这么快、这么准),也无趣(没有潜行、没有惊喜、没有"我刚才看见他往那边跑了"的拟人感)。今天这一篇,我们在守卫的"大脑"和"世界"之间插入一层——**感知(perception)**和**记忆(memory)**。感知让守卫通过眼睛和耳朵"知道"世界,而不是直接读坐标;记忆让守卫"记得"几秒前看到的事,并随着时间衰减。做完这一层,你的守卫会变成一个**世界里的生灵**:你绕到它背后它能被偷袭,你跑进草丛它失去你的精确位置但仍记得你最后出现的地方并去搜查,你逃出它的视野几秒后它会怀疑地挠挠头回到巡逻。这才是 stealth 游戏(Metal Gear、Splinter Cell、《最后生还者》)背后的真实架构。

## 0 · 为什么要有这一篇

### 0.1 全知问题:naive AI 直接读世界

我在 [ai-patterns](../../phase-2/deep-dives/ai-patterns.md) 的 FSM 例子里写过这样的代码:

```rust
fn update_npc(npc: &mut Npc, world: &World, dt: f32) {
    match npc.state {
        BrainState::Patrol => {
            patrol_behavior(npc, world, dt);
            if let Some(target) = see_player(npc, world) {   // ← 问题在这
                npc.target_pos = Some(target);
                npc.state = BrainState::Chase;
            }
        }
        // ...
    }
}

fn see_player(npc: &Npc, world: &World) -> Option<Vec2> {
    let player_pos = world.player.position;   // 直接读玩家坐标
    let dist = (player_pos - npc.position).length();
    if dist < NPC_SIGHT_RANGE {
        Some(player_pos)                       // 永远准确,永远即时
    } else {
        None
    }
}
```

注意 `see_player` 做的事:它直接拿 `world.player.position`,算个距离,就"看见"了。这里没有 FOV(视野锥)、没有 facing(朝向)、没有 line-of-sight(被墙挡住)、没有延迟、没有不确定性。玩家在守卫正后方 2 米,守卫"看见";玩家在墙后 5 米,守卫"看见";玩家在全黑的房间里,守卫"看见"。这是一个**传感器永远 100% 准确、覆盖 360 度、无视遮挡**的怪物。

这种 AI 在测试场景里能跑通,但放进游戏里玩家立刻感觉到不对劲:它不像一个生物,它像一个作弊的机器人。全知 AI 有两个本质问题。

第一,**不公平**。人类的反应有延迟(看见东西到做出反应 ~200ms),视野受限于眼睛朝向(~120 度双目、~200 度单目),会被遮挡(墙、家具、草丛),会忘记(刚才看见的人跑进巷子,2 秒后我记不清他具体在哪)。全知 AI 没有这些限制,反应是 16ms 一帧,视野 360 度,从不被遮挡,从不忘记。玩家和它对抗,**永远在不利位置**。

第二,**无趣**。全知 AI 把潜行(stealth)这种核心玩法直接消灭了。潜行游戏的核心循环是"看见/被看见"——玩家躲在阴影里、绕到背后、用噪音引开守卫。如果守卫全知,这些都无效,玩家只能正面硬刚或纯逃跑。Metal Gear、Splinter Cell、Hitman、《最后生还者》《Dishonored》这些以潜行为骨架的游戏,他们的**全部乐趣**都建立在"AI 不是全知的"这件事上。AI 必须能被骗、能被绕、能被声东击西。

**感知系统的角色**:在"大脑"(FSM / Behavior Tree / Utility)和"世界"之间,插入一层**传感器(sensor)**。大脑不直接读世界,大脑读传感器报告。传感器有自己的限制——范围(range)、视野(field of view)、遮挡(occlusion)、延迟(latency)、噪声(noise)。这一层让 AI"看见的不是真实世界,而是它感官所能捕捉的世界"。

```
世界(玩家、几何、声音)
        ↓
   [传感器] ← 视觉、听觉、嗅觉等
        ↓
   [记忆/黑板] ← 短期事实 + 衰减
        ↓
   [大脑: FSM / BT / Utility]
        ↓
   [行为: 寻路、攻击、巡逻]
```

**记忆系统的角色**:传感器是**瞬时**的——这一帧你看见了,下一帧玩家躲进草丛你就看不见。但生物有**短期记忆**:我 3 秒前看见他站在木箱后面,即便现在看不见,我也"记得"他在木箱后面,我应该过去查。记忆让 AI 不再只活在"现在这一帧",而是有**时间维度**——它会回忆、会怀疑、会逐渐遗忘。这是 Millington《AI for Games》里反复强调的核心架构模式:**黑板(blackboard)**——一个键值对存储,AI 的工作记忆,行为逻辑从中读取事实。

### 0.2 学完之后你能做什么

学完这一篇,你应该能:
- 解释为什么"AI 直接读玩家坐标"既不公平也无趣,感知/记忆如何修复这两点
- 用 Rust 实现一个**视觉感知**:FOV 锥 + 距离 + line-of-sight raycast(对接 [spatial-acceleration](../../phase-6/deep-dives/spatial-acceleration.md))
- 用 Rust 实现一个**听觉感知**:基于声音事件 + 距离/材质衰减
- 设计一个**感知更新周期**:不是每帧跑,而是 10Hz 分摊(staggered),避免帧率尖峰
- 实现一个**黑板**:`HashMap<FactKey, Fact>`,带时间戳和置信度,旧事实衰减
- 用感知/记忆驱动一个**警觉等级(unaware → suspicious → alerted)**,平滑过渡而非瞬切
- 在你的 HH 项目里给守卫 AI 上感知+记忆,对比旧的"全知"版本,亲手摸到"AI 像生灵"的临界点

这一篇是 [ai-patterns](../../phase-2/deep-dives/ai-patterns.md)(大脑)和 [navmesh-and-pathfinding](../../phase-7/deep-dives/navmesh-and-pathfinding.md)(腿)之间的**中间层**。三者合起来就是完整的"游戏 AI"。

## 1 · 视觉感知:看见玩家到底是什么意思

### 1.1 三个条件:在视野锥里 + 在距离内 + 没被挡住

我们从一个具体场景切入。守卫站在房间中央,面朝北。玩家在守卫的右后方(东南方向)5 米处,中间没有遮挡。这一帧,守卫"看见"玩家了吗?

直觉答案:**没看见**,因为玩家在守卫的视野外。守卫的眼睛朝北,玩家在东南,守卫的视野锥(field of view cone)只覆盖前方一片扇形区域,东南方向不在扇形里。

把这直觉形式化。一个 AI **看见** 一个目标,必须同时满足三个条件:

1. **目标在视野锥内(in FOV cone)**:目标方向与 AI 朝向(facing)的夹角 ≤ FOV/2。典型 FOV 是 90°-120°,夹角 ≤ 45°-60°。
2. **目标在视线距离内(within sight range)**:AI 到目标的距离 ≤ sight_range。典型 15-30 米。
3. **没被几何挡住(line-of-sight clear)**:从 AI 眼睛位置到目标位置,射线(raycast)不撞到任何遮挡几何(墙、家具、门)。

**前两个条件是廉价的**——向量点乘和距离平方比较,几个时钟周期。**第三个条件是昂贵的**——需要 raycast,而 raycast 要遍历场景几何或空间加速结构(BVH、网格),几十到几千时钟周期。

这种"两个便宜条件 + 一个昂贵条件"的结构,是感知优化的核心思路:**先做便宜的剔除,再做昂贵的精细检查**。先用 FOV 和距离剔除掉绝大多数目标,只对真正"可能看见"的目标跑 raycast。这是 [spatial-acceleration](../../phase-6/deep-dives/spatial-acceleration.md) 在 AI 里的典型用法——把所有可能阻挡视线的几何组织进 BVH,raycast 在 BVH 上跑,而不是线性扫描所有几何。

让我先把三个条件的几何写出来。

### 1.2 FOV 锥:向量点乘

视野锥判断的数学非常简单——**向量点乘**。从 AI 到目标的方向向量 `to_target = (target - eye).normalize()`,AI 的朝向向量 `facing`(单位向量)。两个单位向量的点乘等于它们夹角的余弦:

```
dot = to_target · facing = cos(angle)
```

如果 `dot ≥ cos(FOV/2)`,则夹角 ≤ FOV/2,目标在视野锥内。

```rust
// 文件: src/ai/perception.rs

#[derive(Clone, Copy, Debug)]
pub struct Vec2 {
    pub x: f32,
    pub y: f32,
}

impl Vec2 {
    pub fn sub(self, o: Self) -> Self { Self { x: self.x - o.x, y: self.y - o.y } }
    pub fn dot(self, o: Self) -> f32 { self.x * o.x + self.y * o.y }
    pub fn length_sq(self) -> f32 { self.x * self.x + self.y * self.y }
    pub fn normalize(self) -> Self {
        let len = self.length_sq().sqrt();
        if len > 1e-8 { Self { x: self.x / len, y: self.y / len } }
        else { Self { x: 0.0, y: 0.0 } }
    }
    /// 从弧度(0 = +x 方向, 逆时针为正)构造单位向量
    pub fn from_angle(rad: f32) -> Self {
        Self { x: rad.cos(), y: rad.sin() }
    }
}

/// 视觉传感器配置
#[derive(Clone, Debug)]
pub struct SightConfig {
    pub fov_rad: f32,         // 全视野角度(90° = 1.5708 rad),目标在 ±fov/2 内
    pub range: f32,           // 视线最大距离(米)
    pub range_sq: f32,        // 距离平方(避免 sqrt)
    pub cos_half_fov: f32,    // 预计算的 cos(fov/2)
    pub eye_offset: Vec2,     // 眼睛相对 NPC 中心的偏移(2D 里一般 0)
}

impl SightConfig {
    pub fn new(fov_deg: f32, range: f32) -> Self {
        let fov_rad = fov_deg.to_radians();
        Self {
            fov_rad,
            range,
            range_sq: range * range,
            cos_half_fov: (fov_rad * 0.5).cos(),
            eye_offset: Vec2 { x: 0.0, y: 0.0 },
        }
    }
}

/// FOV + 距离检查(不含遮挡)。返回 Some(dist_sq) 表示目标在锥内且在距离内。
/// 返回 None 表示目标已被 FOV 或距离剔除。
pub fn in_sight_cone(
    cfg: &SightConfig,
    eye_pos: Vec2,
    facing: Vec2,
    target: Vec2,
) -> Option<f32> {
    let to_target = target.sub(eye_pos);
    let dist_sq = to_target.length_sq();
    if dist_sq > cfg.range_sq {
        return None;
    }
    if dist_sq < 1e-8 {
        // 目标就在眼睛位置,默认可见(避免零向量 normalize)
        return Some(0.0);
    }
    let dir = to_target.normalize();
    let cos_angle = dir.dot(facing);
    if cos_angle >= cfg.cos_half_fov {
        Some(dist_sq)
    } else {
        None
    }
}
```

**几个细节值得点出**:

- **用 `range_sq` 而不是 `range`**:距离判断用平方比较 `dist_sq > range_sq`,避免开方。这是游戏编程的常识优化,但对每帧 N 个 NPC × M 个目标来说累计影响明显。
- **预计算 `cos_half_fov`**:FOV 配置不变,`cos(fov/2)` 是常量,构造时算一次。每帧每次判断只做点乘 + 比较,几十纳秒。
- **零向量保护**:目标恰好在眼睛位置时 `to_target` 是零向量,`normalize` 会得到 NaN。返回 `Some(0.0)` 表示"零距离目标默认可见",避免 NaN 污染下游。
- **`facing` 必须是单位向量**:点乘的几何含义(等于 cos 角)依赖双方都是单位向量。如果 facing 是从旋转角度算的,务必先 `from_angle` 归一化。

这套 FOV 锥判断**忽略**了遮挡——它只回答"几何上目标在不在我的视觉锥里"。这是第一道便宜筛子,把大部分目标剔除掉。

### 1.3 遮挡:line-of-sight raycast

通过 FOV 锥筛子之后,目标可能仍然被墙挡住。这时候我们需要做 line-of-sight(LOS)检查:**从 AI 眼睛位置朝目标发射一条射线,如果射线在到达目标之前撞到了遮挡几何,则目标不可见**。

LOS 是感知系统里最贵的部分。它的成本取决于场景几何的组织方式:

- **朴素**:射线遍历场景所有三角形,做线段-三角形相交测试。N 个三角形,O(N) 每条射线。10000 三角形的场景,100 个 NPC 每帧各发一条射线,= 100 万次相交测试/帧,几毫秒。
- **空间加速结构(BVH / 八叉树 / 网格)**:射线在加速结构里走,只测试它真正穿越的节点里的几何。详见 [spatial-acceleration](../../phase-6/deep-dives/spatial-acceleration.md)。典型加速 10-100 倍。

为了这一节自包含,我写一个最朴素的 LOS(线段 vs 一组 AABB 墙),生产代码请对接你的物理引擎或 BVH:

```rust
/// 轴对齐矩形障碍(2D)
#[derive(Clone, Copy, Debug)]
pub struct AabbObstacle {
    pub min: Vec2,
    pub max: Vec2,
    pub blocks_sight: bool,   // 有些障碍(玻璃、栅栏)挡移动但不挡视线
}

/// 线段 vs AABB 的相交测试(slab method)。
/// 返回 true 表示线段撞到 AABB(即被遮挡)。
fn segment_hits_aabb(start: Vec2, end: Vec2, b: AabbObstacle) -> bool {
    let d = end.sub(start);
    let mut tmin = 0.0f32;
    let mut tmax = 1.0f32;

    // X 轴 slab
    if d.x.abs() < 1e-8 {
        // 射线平行 Y 轴;起点必须在 b 的 X 范围内
        if start.x < b.min.x || start.x > b.max.x {
            return false;
        }
    } else {
        let t1 = (b.min.x - start.x) / d.x;
        let t2 = (b.max.x - start.x) / d.x;
        let (t1, t2) = if t1 < t2 { (t1, t2) } else { (t2, t1) };
        tmin = tmin.max(t1);
        tmax = tmax.min(t2);
        if tmin > tmax { return false; }
    }

    // Y 轴 slab
    if d.y.abs() < 1e-8 {
        if start.y < b.min.y || start.y > b.max.y {
            return false;
        }
    } else {
        let t1 = (b.min.y - start.y) / d.y;
        let t2 = (b.max.y - start.y) / d.y;
        let (t1, t2) = if t1 < t2 { (t1, t2) } else { (t2, t1) };
        tmin = tmin.max(t1);
        tmax = tmax.min(t2);
        if tmin > tmax { return false; }
    }

    // 相交区间 [tmin, tmax] 与 [0, 1] 有交集,且交点不是终点(目标自身位置)
    // tmin < 1 表示障碍在线段中间,不是终点之后
    tmin < 1.0 && tmax > 0.0
}

/// Line-of-sight:从 eye 到 target 是否被任意障碍挡住。
/// 返回 true = 视线清晰(没被挡),false = 被挡。
pub fn line_of_sight_clear(
    eye: Vec2,
    target: Vec2,
    obstacles: &[AabbObstacle],
) -> bool {
    for ob in obstacles {
        if !ob.blocks_sight { continue; }
        if segment_hits_aabb(eye, target, *ob) {
            return false;
        }
    }
    true
}
```

**关于 `tmin < 1.0` 的细节**:线段参数化 `p(t) = start + t * d,t ∈ [0, 1]`。`t = 1` 对应终点(目标)。如果障碍在 `t = 1` 处,说明障碍"贴着"目标,这种情况一般不算遮挡(目标本身就站在障碍旁)。`tmin < 1.0` 排除"障碍只在终点处"的情形。生产代码可能要求更严格——比如 `tmin < 0.98`,给目标一个 2% 的容差。

**关于 `blocks_sight` 字段**:不是所有障碍都挡视线。玻璃窗挡移动但不挡视线,矮灌木挡视线但允许移动(玩家可以钻过去),栅栏可能"半挡"(用概率或半透明遮挡)。一个布尔字段是简化版,生产里会用 `occlusion: f32` 表示遮挡强度,视野穿过多次累计遮挡到 0 就看不见。

把 FOV、距离、LOS 三段串起来,我们就有了完整的"看见"判断:

```rust
/// 完整的视觉感知:FOV + 距离 + 遮挡。
/// 返回 Some(目标信息) 表示看见,None 表示没看见。
pub fn can_see(
    cfg: &SightConfig,
    eye_pos: Vec2,
    facing: Vec2,
    target: Vec2,
    obstacles: &[AabbObstacle],
) -> Option<f32> {
    let dist_sq = in_sight_cone(cfg, eye_pos, facing, target)?;
    if !line_of_sight_clear(eye_pos, target, obstacles) {
        return None;
    }
    Some(dist_sq)
}
```

这是 short-circuit:`in_sight_cone` 失败直接 return None,不跑 LOS。绝大多数目标会被前两步剔除,只有少数"真的可能看见"的目标才付出 LOS 成本。

### 1.4 LOS 的性能现实与优化

让我给你一个量级感。假设场景里有 50 个 NPC,玩家是唯一目标,每个 NPC 每帧发一条 LOS 射线(在通过 FOV 之后)。

如果玩家在某个 NPC 的 FOV 内,该 NPC 发一条射线;如果不在,该 NPC 不发。典型场景下,50 个 NPC 里大约 5-10 个的 FOV 覆盖玩家(其他 NPC 朝别的方向)。所以每帧 5-10 条射线。

每条射线在朴素实现下遍历 1000 个 AABB,大约 10 微秒。10 条射线 = 100 微秒/帧。在 60FPS(16.67ms 帧预算)里完全可以接受。但场景变大、几何变多时,朴素 LOS 会爆。

**优化思路**(按收益从大到小):

1. **空间加速结构**(最大收益)。把 AABB 装进 BVH 或均匀网格,射线只测试穿越的节点里的 AABB。详见 [spatial-acceleration](../../phase-6/deep-dives/spatial-acceleration.md)。典型 10-100x 加速。
2. **降低 LOS 频率**(中收益)。NPC 不需要每帧都 LOS。每 100-200ms 跑一次足够——人类反应也是这个尺度。下一节专门讲这个。
3. **共享 LOS 查询**(小收益)。两个 NPC 都想知道"能不能看见玩家",他们的射线高度相似。可以缓存"本帧已经做过的 LOS 查询",相同 (eye, target) 复用结果。
4. **粗-细两阶段**(中收益)。先用粗网格(每格 1 米)近似 LOS,粗测试通过后再用精细几何 LOS。粗测试可以用预计算的"可见性网格"(visibility grid)——离线对每个格子算"从这个格子能看到哪些格子",运行时 O(1) 查表。
5. **并行化**(小收益)。多个 NPC 的 LOS 互不依赖,可以 `rayon` 并行。但 LOS 已经很便宜了,并行开销可能抵消收益。

工业 stealth 游戏(《最后生还者》《Splinter Cell》)用**预计算可见性网格 + 运行时精细 LOS** 的组合。预计算网格把场景切成 1-2 米的格子,离线跑"每对格子之间视线是否被挡",存成布尔矩阵(N² 个 bit,N = 格子数)。运行时 LOS 第一步查矩阵(O(1)),通过后再发精细射线(处理动态障碍)。这种"预计算 + 运行时"的混合,把 LOS 成本压到亚微秒。

## 2 · 听觉感知:声音事件与衰减

### 2.1 听觉不是"减号版的视觉"

视觉的核心问题是"被遮挡",听觉的核心问题是"传播"。声音从声源发出,通过空气(和水、墙、地板)传播,沿途被吸收和散射。**听觉和视觉是两种完全不同的感知**,不要把听觉当成"减号版的视觉"。

视觉:精确(你知道目标的精确位置)、方向性(只在视野锥内)、被遮挡(墙挡)、即时(光速)。
听觉:不精确(你知道"那边有声音",但位置模糊)、全向(360° 都能听)、绕障(墙后能听到但更弱)、有延迟(声速 ~340m/s,30 米外延迟 ~88ms)。

听觉的本质是**事件驱动**的。不是 NPC 每帧"扫描周围有没有声音",而是**世界产生声音事件,声音事件被分发到附近的 NPC**。这是 [event-systems-and-gameplay-foundations](event-systems-and-gameplay-foundations.md) 在 AI 里的直接应用——声音就是一个事件,玩家踩到玻璃碎片产生一个 `SoundEvent` 事件,事件总线把事件分发给附近的 NPC,NPC 的听觉组件接收事件并决定怎么反应。

让我先把数据结构搭出来。

```rust
/// 声音类型。决定基础响度和"语义"(脚步 vs 枪声 vs 爆炸)。
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum SoundKind {
    Footstep,
    FootstepLoud,        // 跑步、跳落
    Gunshot,
    Explosion,
    Voice,               // NPC 喊话、玩家说话
    BreakGlass,          // 打碎玻璃(stealth 游戏经典)
    DoorOpen,
    BodyFall,            // 尸体落地
}

/// 一个声音事件。由世界产生,分发给附近 NPC。
#[derive(Clone, Debug)]
pub struct SoundEvent {
    pub kind: SoundKind,
    pub source_pos: Vec2,
    pub base_loudness: f32,   // 在 1 米处的响度(dB 或任意线性单位)
    pub timestamp: f32,       // 发出时刻(用于回声 / 延迟)
}

impl SoundEvent {
    /// 每种声音的默认响度和传播距离。
    pub fn new(kind: SoundKind, pos: Vec2, time: f32) -> Self {
        let (loudness, _) = match kind {
            SoundKind::Footstep       => (0.4, 8.0),     // 8 米内
            SoundKind::FootstepLoud   => (0.8, 20.0),
            SoundKind::Gunshot        => (3.0, 80.0),    // 极远
            SoundKind::Explosion      => (10.0, 200.0),
            SoundKind::Voice          => (0.6, 15.0),
            SoundKind::BreakGlass     => (1.0, 25.0),
            SoundKind::DoorOpen       => (0.5, 12.0),
            SoundKind::BodyFall       => (1.2, 30.0),
        };
        Self { kind, source_pos: pos, base_loudness: loudness, timestamp: time }
    }
}
```

### 2.2 距离衰减 + 材质衰减

声音随距离衰减,这是物理学常识(逆平方定律 intensity ∝ 1/r²,但游戏里常用更平缓的衰减模型让游戏性更好)。除此之外,声音**穿过墙**会被额外吸收——这是听觉相对视觉的关键差异:墙完全挡住视觉,但只**衰减**听觉(墙后你听得到,只是更弱)。

```rust
/// 听觉配置
#[derive(Clone, Debug)]
pub struct HearingConfig {
    pub threshold: f32,        // NPC 能听到的最小响度(0 = 聋,越大越迟钝)
    pub max_range: f32,        // 不再监听的最大距离(性能剪枝用)
    pub max_range_sq: f32,
}

impl HearingConfig {
    pub fn new(threshold: f32, max_range: f32) -> Self {
        Self { threshold, max_range, max_range_sq: max_range * max_range }
    }
}

/// 障碍物对声音的衰减系数。墙衰减 0.3(透 30%),门衰减 0.7,玻璃衰减 0.5。
#[derive(Clone, Copy, Debug)]
pub struct SoundObstacle {
    pub min: Vec2,
    pub max: Vec2,
    pub transmission: f32,   // 穿过后响度乘以这个值,0 = 完全挡住,1 = 不衰减
}

/// 听到一个声音事件吗?返回 Some(到达响度) 或 None。
pub fn can_hear(
    cfg: &HearingConfig,
    ear_pos: Vec2,
    event: &SoundEvent,
    obstacles: &[SoundObstacle],
) -> Option<f32> {
    let to_source = event.source_pos.sub(ear_pos);
    let dist_sq = to_source.length_sq();
    if dist_sq > cfg.max_range_sq {
        return None;
    }
    let dist = dist_sq.sqrt().max(0.001);

    // 距离衰减:用 1/(1 + dist) 模型,比逆平方更平缓,游戏性更好
    let atten_distance = 1.0 / (1.0 + dist * 0.3);

    // 障碍衰减:数射线穿过的"衰减障碍"数量,每穿过一个响度乘以 transmission
    let mut atten_obstacle = 1.0;
    for ob in obstacles {
        if ob.transmission >= 1.0 { continue; }
        if segment_hits_aabb(ear_pos, event.source_pos, AabbObstacle {
            min: ob.min, max: ob.max, blocks_sight: true,
        }) {
            atten_obstacle *= ob.transmission;
        }
    }

    let loudness_at_ear = event.base_loudness * atten_distance * atten_obstacle;
    if loudness_at_ear >= cfg.threshold {
        Some(loudness_at_ear)
    } else {
        None
    }
}
```

**关于衰减模型的选择**:逆平方定律(1/r²)在游戏里往往太陡——10 米外的脚步声只剩 1%,基本听不见,这让听觉感知形同虚设。游戏里更常用 `1/(1 + dist*k)` 或 `max(0, 1 - dist/max_range)` 这种线性/双曲衰减,让听觉作用范围可控。Millington《AI for Games》建议听觉范围用**响度归一化**:`effective_range = base_loudness * max_radius`,响度高的声音(枪声)有效范围 100 米,低的声音(脚步)8 米。

**关于射线穿过障碍**:这其实是把"墙后能听到"建模成"射线穿墙,每穿一堵墙响度乘 transmission"。砖墙 transmission = 0.2(透 20%),木门 0.6,玻璃 0.5。这是粗略模型,生产 stealth 游戏会用**传播路径**(propagation path)——找从声源到耳朵的"最便宜路径"(可以绕过墙、穿过门、走走廊),用 navmesh 或 flood fill 在格子图上跑 Dijkstra,路径长度决定衰减。这一篇不展开传播路径,那是更深的专题。

### 2.3 听觉的不精确性

听觉比视觉更模糊——视觉告诉你目标的精确位置,听觉只告诉你"那边有声音"。在游戏里这个不精确性怎么建模?

最简单做法:**听到声音后,NPC 知道声源的精确位置,但只在黑板里写一个"扰动过的位置"**——把真实位置加一个随机偏移(半径 2-5 米),NPC 去查的是这个扰动位置,而不是真实位置。响度越低扰动越大(听得很模糊),响度高扰动小(听得很清楚)。

```rust
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};

/// 伪随机偏移:把"听到但模糊"建模为位置加噪声。
/// 用确定性的 hash(避免每帧噪声跳来跳去)。
pub fn noisy_position(
    true_pos: Vec2,
    loudness: f32,
    seed: u64,
) -> Vec2 {
    // 响度 1.0+ → 扰动 0(精确),响度 0.3 → 扰动大
    let noise_radius = ((1.0 / loudness).min(10.0) - 1.0).max(0.0) * 3.0;
    let mut h = DefaultHasher::new();
    seed.hash(&mut h);
    let r = (h.finish() as f32) / (u64::MAX as f32);
    let a = (h.finish().wrapping_mul(2654435761) as f32) / (u64::MAX as f32);
    let angle = a * std::f32::consts::TAU;
    Vec2 {
        x: true_pos.x + r.cos() * noise_radius,
        y: true_pos.y + angle.sin() * noise_radius * 0.5,
    }
}
```

我用了**确定性 hash** 而不是 `rand::random()`——同一帧同一个声音事件,所有 NPC 应该算出**相同的扰动位置**(他们听到的是同一个声音),而每帧重新生成扰动位置会让 NPC 的"记忆位置"每帧都跳,行为会非常神经质。确定性 hash 给同一个 (sound, time) 一个稳定的扰动。

听觉感知的输出是一个**不精确的位置**——这是 stealth 游戏的核心张力。玩家知道"NPC 听到了我,但 NPC 不知道我的精确位置",所以 NPC 会**朝扰动位置走过去搜查**,玩家可以趁机溜走。这种"半知道"的状态,正是 stealth 玩法的灵魂。

## 3 · 感知更新周期:不要每帧跑感知

### 3.1 感知不需要 60Hz

写完视觉和听觉,直接放到每帧 update 里跑是新手最常犯的错。每帧跑感知意味着 NPC 每秒"扫描"60 次世界——这既浪费(感知的代价是 raycast,贵),又不真实(人类反应 ~200ms,NPC 16ms 反应像机器)。

**感知频率应该是 5-10Hz**(每 100-200ms 跑一次)。这个频率的理由有两层:

1. **生物反应时间**:人类视觉反应 ~200ms,听觉 ~150ms。NPC 用 100-200ms 的感知频率,行为自然带着"反应延迟",玩家可以利用(快速闪过 NPC 视野,在 NPC 反应过来之前躲进草丛)。这是 stealth 游戏的核心节奏。
2. **性能**:感知每秒跑 10 次 vs 60 次,成本差 6 倍。50 个 NPC 每帧各跑一次 LOS = 50 条射线;改成 10Hz 且分摊,每帧平均 0.83 条射线。差异巨大。

### 3.2 分摊(staggered):避免帧率尖峰

如果所有 NPC 都在同一帧跑感知,那一帧会突然出现 50 条 LOS,造成帧时间尖峰(spike)。**分摊**思路:把 NPC 的感知 tick 错开到不同帧。

```rust
/// 每个感知组件带一个"下次 tick 时刻"和"tick 间隔"。
#[derive(Clone, Debug)]
pub struct PerceptionTick {
    pub next_update: f32,           // 下次跑感知的时刻(秒)
    pub interval: f32,              // tick 间隔(0.1-0.2 秒)
    pub phase_offset: f32,          // 错相(让不同 NPC tick 不同步)
}

impl PerceptionTick {
    pub fn new(interval: f32, phase: f32) -> Self {
        Self { next_update: phase, interval, phase_offset: phase }
    }

    /// 当前时刻是否到了 tick 时刻?如果是,推进 next_update。
    pub fn should_tick(&mut self, now: f32) -> bool {
        if now >= self.next_update {
            // 推进到下一个 tick;如果已经过了多个 tick,跳过中间的(避免补帧)
            let skipped = ((now - self.next_update) / self.interval).ceil();
            self.next_update += self.interval * skipped.max(1.0);
            true
        } else {
            false
        }
    }
}

/// 给一组 NPC 初始化时,phase 在 [0, interval) 上均匀分布。
pub fn make_staggered_ticks(n: usize, interval: f32) -> Vec<PerceptionTick> {
    (0..n).map(|i| {
        let phase = (i as f32 / n as f32) * interval;
        PerceptionTick::new(interval, phase)
    }).collect()
}
```

**`skipped` 那行的细节**:如果某帧 dt 异常大(比如游戏暂停后恢复),`now` 可能跳过多个 tick 间隔。朴素做法 `next_update += interval` 会让你接下来每帧都触发 tick(因为 next_update 还在 now 后面),造成连环 tick 风暴。我用 `ceil((now - next_update) / interval)` 一次性跳到 now 之后的下一个 tick,避免补帧。这是工程细节,但漏了它会在暂停恢复后看到感知系统卡几秒。

### 3.3 优先级:远的 NPC tick 更慢

进阶优化:**根据 NPC 与玩家的距离动态调整 tick 频率**。离玩家近的 NPC(20 米内)每 100ms tick 一次(反应快),离玩家远的 NPC(50 米外)每 500ms tick 一次(反应慢、便宜)。这模拟了"远处 NPC 不重要"的 LOD 思想,同时把感知成本花在玩家会注意的地方。

```rust
pub fn dynamic_interval(dist_to_player: f32) -> f32 {
    if dist_to_player < 20.0 { 0.1 }
    else if dist_to_player < 50.0 { 0.2 }
    else { 0.5 }
}
```

这是 perception LOD(level of detail),和渲染 LOD 思路一致——离玩家远的对象降低精度。AAA 游戏的 AI 感知系统都有这一层,Ubisoft 在 GDC 演讲里多次提到他们的 perception LOD 系统。

## 4 · 黑板:AI 的短期记忆

### 4.1 感知是瞬时的,记忆是持久的

到这里我们有了一个工作良好的感知系统:NPC 每隔 100-200ms 用 FOV+LOS 看一下,通过声音事件听到响动。但这些感知结果是**瞬时的**——这一帧 NPC 看见玩家在 (10, 5),下一帧玩家躲到墙后,NPC 的"看见"输出变成 None。如果 NPC 大脑直接消费瞬时感知,会发生这种事:玩家在视野里跑过 0.1 秒,NPC 切到 Chase;玩家躲到墙后,NPC 这一帧没看见,大脑立刻忘记玩家存在,切回 Patrol;玩家再露头 0.1 秒,NPC 切 Chase;玩家躲回去,Patrol……NPC 像个金鱼,记忆只有 7 秒。

**记忆系统解决这个问题**。感知产生**事实(fact)**,事实写入**黑板(blackboard)**,黑板带时间戳,行为逻辑从黑板读事实。事实会**衰减**——老的事实置信度降低;事实会被**取代**——新的、更可靠的事实覆盖旧的同类事实。

黑板是 Millington《AI for Games》反复强调的核心架构模式。它是 AI 的工作记忆(working memory),一个键值对存储,键是事实类型,值是带时间戳和置信度的事实。

### 4.2 黑板的数据结构

```rust
use std::collections::HashMap;
use std::time::Instant;

/// 事实键。不同种类的事实:最后看见的玩家位置、最后听见的声音位置、
/// 怀疑度、当前目标、记忆中的敌人列表等。
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum FactKey {
    LastSeenPlayerPos,
    LastHeardSoundPos,
    LastSeenTimestamp,      // 什么时候最后一次看见
    LastHeardTimestamp,
    Suspicion,              // 怀疑度 [0, 1]
    KnownThreats,           // 已知威胁列表(简化版用一个聚合值)
    InvestigateTarget,      // 去搜查的位置
}

/// 一个事实。带写入时间戳、置信度、可选的"原始数据"。
#[derive(Clone, Debug)]
pub struct Fact {
    pub written_at: f32,        // 写入时刻(秒)
    pub confidence: f32,        // [0, 1],1 = 完全可信
    pub value: FactValue,
}

#[derive(Clone, Debug)]
pub enum FactValue {
    Position(Vec2),
    Scalar(f32),
    Timestamp(f32),
    Empty,                      // "我知道这个键没有值"(显式遗忘)
}

/// 黑板。AI 的工作记忆。
#[derive(Clone, Debug, Default)]
pub struct Blackboard {
    pub facts: HashMap<FactKey, Fact>,
}

impl Blackboard {
    pub fn new() -> Self { Self { facts: HashMap::new() } }

    /// 写入一个事实(覆盖同键旧值)。
    pub fn set(&mut self, key: FactKey, value: FactValue, confidence: f32, now: f32) {
        self.facts.insert(key, Fact {
            written_at: now,
            confidence,
            value,
        });
    }

    pub fn get(&self, key: FactKey) -> Option<&Fact> {
        self.facts.get(&key)
    }

    /// 读一个位置事实,如果存在且置信度 > 阈值。
    pub fn get_position(&self, key: FactKey, min_confidence: f32) -> Option<Vec2> {
        match self.facts.get(&key) {
            Some(f) if f.confidence >= min_confidence => match &f.value {
                FactValue::Position(p) => Some(*p),
                _ => None,
            },
            _ => None,
        }
    }

    /// 显式遗忘一个键(写入 Empty 而不是删除,保留"曾经知道"的痕迹)。
    pub fn forget(&mut self, key: FactKey, now: f32) {
        self.facts.insert(key, Fact {
            written_at: now,
            confidence: 0.0,
            value: FactValue::Empty,
        });
    }

    /// 更新所有事实的置信度:旧的衰减。返回置信度过低应清除的事实。
    pub fn decay(&mut self, now: f32, half_life: f32) {
        for f in self.facts.values_mut() {
            let age = now - f.written_at;
            // 指数衰减:confidence *= 0.5 ^ (age / half_life)
            let factor = 0.5f32.powf(age / half_life.max(0.001));
            f.confidence *= factor;
        }
        // 清除低置信度事实(除了显式 Empty,那些保留)
        self.facts.retain(|_, f| f.confidence >= 0.05 || matches!(f.value, FactValue::Empty));
    }
}
```

**几个设计决定值得讨论**:

- **`FactValue` 是 enum**:不同种类的事实有不同类型(位置、标量、时间戳)。enum 让黑板统一存储异构数据,Rust 的模式匹配让读取安全。生产代码可能用 `Box<dyn Any>` 或泛型,但 enum 在大多数场景足够,且性能更好(无堆分配)。
- **`confidence` 是 [0, 1] 浮点**:0 = 完全不可信,1 = 完全可信。直接看见玩家写 1.0,听见扰动过的声音写 0.5(模糊),猜测写 0.2。行为逻辑根据置信度决定反应强度——置信度 1.0 直接 Chase,0.5 走过去 Investigate,0.2 转头看一眼。
- **`decay` 用半衰期**:配置 `half_life`(典型 5-10 秒),每秒置信度乘 0.5^(1/half_life)。10 秒前看见的玩家,置信度只剩 50%,30 秒前只剩 12.5%。这让"老记忆自然变弱"——NPC 几秒前看见你,会立刻 Chase;30 秒前看见你,只会巡逻式地走过去看一眼。
- **`forget` 不删除而是写 Empty**:保留"曾经知道过"的痕迹,行为逻辑可以读 `Empty` 决定"我之前知道但现在忘了,该转换思路"。删除会丢失这个信息。
- **`retain` 清除极低置信度**:避免黑板无限膨胀。0.05 阈值意味着"几乎完全遗忘"才清除。

### 4.3 感知写黑板,行为读黑板

黑板是感知和行为之间的**唯一接口**。感知系统只写黑板,行为系统只读黑板——这是 Millington 强调的解耦。这种解耦让感知和行为可以独立演化:加一个新的感知(比如嗅觉),只在黑板上加一个键,行为逻辑根据这个键决定反应;加一个新的行为(比如"搜查"),只读黑板里已有的 `LastSeenPlayerPos`。

```rust
/// 视觉感知系统。每 tick 跑一次。
pub fn sight_system(
    cfg: &SightConfig,
    eye_pos: Vec2,
    facing: Vec2,
    target: Option<Vec2>,    // 玩家位置,None = 玩家不存在或已死亡
    obstacles: &[AabbObstacle],
    bb: &mut Blackboard,
    now: f32,
) {
    match target {
        Some(t) => {
            if let Some(_) = can_see(cfg, eye_pos, facing, t, obstacles) {
                // 看见了:写入高置信度事实
                bb.set(FactKey::LastSeenPlayerPos, FactValue::Position(t), 1.0, now);
                bb.set(FactKey::LastSeenTimestamp, FactValue::Timestamp(now), 1.0, now);
            }
            // 没看见:黑板里的旧 LastSeenPlayerPos 保留(那是记忆,不是实时)
            // 它会随着 decay 自然降低置信度
        }
        None => {
            // 玩家不存在,清空相关事实
            bb.forget(FactKey::LastSeenPlayerPos, now);
        }
    }
}

/// 听觉感知系统。事件驱动。
pub fn hearing_system(
    cfg: &HearingConfig,
    ear_pos: Vec2,
    events: &[SoundEvent],
    obstacles: &[SoundObstacle],
    bb: &mut Blackboard,
    now: f32,
) {
    let mut loudest: Option<(f32, Vec2)> = None;
    for ev in events {
        if let Some(loudness) = can_hear(cfg, ear_pos, ev, obstacles) {
            // 选最响的(简化:同一 tick 内多个声音,响度最高的是主要刺激)
            match &loudest {
                None => loudest = Some((loudness, ev.source_pos)),
                Some((prev_l, _)) if loudness > *prev_l => {
                    loudest = Some((loudness, ev.source_pos));
                }
                _ => {}
            }
        }
    }
    if let Some((loudness, source)) = loudest {
        // 听到了:写入扰动位置,置信度 = 响度的某种映射
        let noisy = noisy_position(source, loudness, now.to_bits() as u64);
        let conf = (loudness * 0.7).min(0.9);   // 听觉永远不如视觉准确
        // 只在新事实置信度更高时覆盖旧事实
        let should_overwrite = match bb.get(FactKey::LastHeardSoundPos) {
            Some(old) => old.confidence < conf || (now - old.written_at) > 1.0,
            None => true,
        };
        if should_overwrite {
            bb.set(FactKey::LastHeardSoundPos, FactValue::Position(noisy), conf, now);
            bb.set(FactKey::LastHeardTimestamp, FactValue::Timestamp(now), conf, now);
        }
    }
}
```

**关于"只在置信度更高时覆盖"**:这是 Millington 的"事实取代"原则——新的、更可靠的事实覆盖旧的、不可靠的。视觉(置信 1.0)覆盖听觉(置信 0.5),强听觉覆盖弱听觉。但要小心一个反直觉情况:你看见玩家在 A,玩家躲起来,3 秒后你听见玩家在 B——这时候听觉的 0.5 置信度应该覆盖视觉的衰减后 0.3 置信度。代码里的 `old.confidence < conf` 处理这个,但要注意 decay 已经把视觉置信度从 1.0 降到 0.3 了,所以新听觉事实能写入。这是 decay 的另一个作用——让老事实"为更新的事实腾位置"。

## 5 · 警觉等级:感知驱动状态平滑切换

### 5.1 不要瞬切

感知和记忆给了 NPC 关于世界的"印象",但 NPC 还需要一个**整体状态**——警觉等级(alertness level)。这是连接感知和行为的关键中间层。常见三级模型:

- **Unaware(未察觉)**:正常巡逻,感知阈值高(只反应近距离强刺激)。
- **Suspicious(怀疑)**:听到什么/瞥见什么,但没有目标,开始搜查、转头看、走向可疑位置。感知阈值低(更敏感)。
- **Alerted(警觉/战斗)**:明确发现玩家,追击、攻击。感知阈值最低(几乎不会被甩掉)。

**关键设计**:警觉等级之间**不要瞬切**。从 Unaware 瞬切到 Alerted,NPC 像触发了开关;从 Alerted 瞬切回 Unaware,NPC 像失忆。现实里警觉是**渐变**的——你听到一声响,开始怀疑(suspicion 上升),没找到东西怀疑度慢慢下降;你瞥见玩家,suspicion 急升,看见玩家全身 suspicion 满,你 Alerted。

这正好是 [ai-patterns](../../phase-2/deep-dives/ai-patterns.md) 里 FSM 的**状态平滑过渡**问题。FSM 本身是离散的(Patrol/Chase/Attack),但驱动 FSM 切换的应该是**连续的 suspicion 标量**,而不是布尔事件。这是 utility 思想混入 FSM 的常见做法。

### 5.2 suspicion 标量 + 阈值切换

```rust
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum AlertLevel {
    Unaware,
    Suspicious,
    Alerted,
}

#[derive(Clone, Debug)]
pub struct Alertness {
    pub level: AlertLevel,
    pub suspicion: f32,        // [0, 1] 连续值,驱动 level 切换
    // 阈值(用 hysteresis 避免在阈值附近抖动)
    pub thresh_suspicious: f32,    // suspicion 超过这个升到 Suspicious
    pub thresh_alerted: f32,       // 超过这个升到 Alerted
    pub thresh_calm: f32,          // 降到这个以下回到 Unaware
    pub thresh_stand_down: f32,    // Alerted 降到这个以下回到 Suspicious
}

impl Alertness {
    pub fn new() -> Self {
        Self {
            level: AlertLevel::Unaware,
            suspicion: 0.0,
            thresh_suspicious: 0.3,
            thresh_alerted: 0.7,
            thresh_calm: 0.1,
            thresh_stand_down: 0.4,
        }
    }

    /// 根据当前 suspicion 更新 level。带 hysteresis。
    pub fn update_level(&mut self) {
        self.level = match self.level {
            AlertLevel::Unaware => {
                if self.suspicion >= self.thresh_alerted { AlertLevel::Alerted }
                else if self.suspicion >= self.thresh_suspicious { AlertLevel::Suspicious }
                else { AlertLevel::Unaware }
            }
            AlertLevel::Suspicious => {
                if self.suspicion >= self.thresh_alerted { AlertLevel::Alerted }
                else if self.suspicion < self.thresh_calm { AlertLevel::Unaware }
                else { AlertLevel::Suspicious }
            }
            AlertLevel::Alerted => {
                if self.suspicion < self.thresh_stand_down { AlertLevel::Suspicious }
                else { AlertLevel::Alerted }
            }
        };
    }
}
```

注意 **hysteresis(滞后)**:从 Unaware 升到 Suspicious 用阈值 0.3,从 Suspicious 降回 Unaware 用阈值 0.1(更低)。这避免了 suspicion 在 0.3 附近抖动时,NPC 在 Unaware/Suspicious 间乒乓切换。Alerted ↔ Suspicious 同理。这是 [ai-patterns](../../phase-2/deep-dives/ai-patterns.md) 提到的 utility AI "乒乓问题"在 FSM 里的对应解法。

### 5.3 suspicion 怎么升降

suspicion 是一个 [0, 1] 的连续值,**根据感知事件累积或衰减**:

- 看见玩家:suspicion 急升(每秒 +1.5)。
- 看见玩家部分身体(只在视野边缘闪过):suspicion 中速升(+0.5/秒)。
- 听到声音:suspicion 慢升(+0.3/秒)。
- 什么都没感知到:suspicion 自然衰减(-0.2/秒,Unaware 时更慢)。

```rust
/// 感知驱动 suspicion 更新。每帧调用(这是连续值,不依赖 tick)。
pub fn update_suspicion(
    alert: &mut Alertness,
    bb: &Blackboard,
    now: f32,
    dt: f32,
) {
    let seen_recently = match bb.get(FactKey::LastSeenTimestamp) {
        Some(f) => now - f.written_at < 0.3,    // 0.3 秒内看见过
        None => false,
    };
    let heard_recently = match bb.get(FactKey::LastHeardTimestamp) {
        Some(f) => now - f.written_at < 1.0,
        None => false,
    };

    let delta = if seen_recently {
        1.5    // 看见:suspicion 急升
    } else if heard_recently {
        0.3    // 听见:慢升
    } else {
        // 没刺激:衰减。Alerted 时衰减慢(战斗状态下不会很快放松),Unaware 时快
        match alert.level {
            AlertLevel::Alerted => -0.15,
            AlertLevel::Suspicious => -0.25,
            AlertLevel::Unaware => -0.5,
        }
    };

    alert.suspicion = (alert.suspicion + delta * dt).clamp(0.0, 1.0);
    alert.update_level();
}
```

**关于 `seen_recently` 的时间窗口**:黑板里的 `LastSeenTimestamp` 是上次**确实看见**的时刻(不是记忆衰减的时刻)。如果距离这个时刻 < 0.3 秒,说明"我刚看见玩家",suspicion 急升。0.3 秒这个窗口刚好对应感知 tick 间隔——一个 tick 内(0.1-0.2 秒)如果看见玩家,事实被写入,接下来一两帧 `seen_recently` 都是 true,suspicion 升。

**关于 Alerted 衰减慢**:这是"不轻易放过"的设计——一旦 NPC 进入战斗状态,即便玩家躲起来,NPC 也不会立刻冷静。这给了玩家压力(躲一次不够,要躲够时间),也是 stealth 游戏的标准节奏。

### 5.4 警觉等级反过来调制感知

有趣的是,警觉等级不只被感知驱动,**它也反过来调制感知**。Alerted 的 NPC 视野更远(sight_range 加 50%)、感知阈值更低(听到更轻的声音)、tick 频率更高(反应更快);Unaware 的 NPC 视野正常、阈值高、tick 慢。这是合乎直觉的——警觉状态下感官更敏锐。

```rust
pub fn effective_sight_config(base: &SightConfig, level: AlertLevel) -> SightConfig {
    let mut c = base.clone();
    match level {
        AlertLevel::Unaware => {}                          // 默认
        AlertLevel::Suspicious => {
            c.range *= 1.2;                                 // 视野 +20%
            c.range_sq = c.range * c.range;
            c.cos_half_fov = (c.fov_rad * 0.5 * 0.9).cos(); // 视野锥 +10%
        }
        AlertLevel::Alerted => {
            c.range *= 1.5;                                 // 视野 +50%
            c.range_sq = c.range * c.range;
            c.cos_half_fov = (c.fov_rad * 0.5 * 0.8).cos(); // 视野锥 +20%
        }
    }
    c
}

pub fn effective_hearing_threshold(base: f32, level: AlertLevel) -> f32 {
    match level {
        AlertLevel::Unaware => base,
        AlertLevel::Suspicious => base * 0.7,    // 听觉更灵敏(阈值低 = 听到更轻的声音)
        AlertLevel::Alerted => base * 0.4,
    }
}
```

**反馈循环的妙处**:suspicion 升 → AlertLevel 升 → 感知更敏锐 → 更容易感知到玩家 → suspicion 升得更快。这是一个正反馈循环,模拟"警觉螺旋上升"——一旦 NPC 起疑,会越来越敏锐,玩家需要赶紧甩掉它,否则会被锁定。反向也是:玩家躲得够久,suspicion 衰减 → AlertLevel 降 → 感知迟钝 → 更难发现玩家 → suspicion 衰减更快。这是 stealth 游戏"躲得够久就脱险"的机制基础。

## 6 · 整合:完整的感知+记忆+警觉 pipeline

把前面 5 节串起来,完整的 NPC 感知 pipeline 是这样:

```rust
/// 一个 NPC 的完整感知状态。
pub struct NpcPerception {
    pub sight: SightConfig,
    pub hearing: HearingConfig,
    pub tick: PerceptionTick,
    pub blackboard: Blackboard,
    pub alertness: Alertness,
    pub facing: Vec2,           // 当前朝向(由行为系统更新,例如巡逻转向)
}

impl NpcPerception {
    pub fn new(sight_fov_deg: f32, sight_range: f32, hearing_threshold: f32) -> Self {
        Self {
            sight: SightConfig::new(sight_fov_deg, sight_range),
            hearing: HearingConfig::new(hearing_threshold, sight_range * 2.0),
            tick: PerceptionTick::new(0.15, 0.0),    // 每 150ms tick
            blackboard: Blackboard::new(),
            alertness: Alertness::new(),
            facing: Vec2::from_angle(0.0),
        }
    }

    /// 每帧调用。dt 是真实帧时间,now 是当前游戏时间。
    /// 做的事:1) 如果到 tick 时刻,跑视觉;2) 听觉是事件驱动外部 push;3) 始终更新 suspicion。
    pub fn update(
        &mut self,
        now: f32,
        dt: f32,
        eye_pos: Vec2,
        player_pos: Option<Vec2>,
        sight_obstacles: &[AabbObstacle],
        pending_sounds: &[SoundEvent],
        sound_obstacles: &[SoundObstacle],
    ) {
        // 1. suspicion 每帧更新(连续值,不依赖 tick)
        update_suspicion(&mut self.alertness, &self.blackboard, now, dt);

        // 2. 警觉等级调制感知配置
        let effective_sight = effective_sight_config(&self.sight, self.alertness.level);
        let effective_hearing_thresh = effective_hearing_threshold(
            self.hearing.threshold, self.alertness.level
        );
        let effective_hearing = HearingConfig {
            threshold: effective_hearing_thresh,
            ..self.hearing.clone()
        };

        // 3. 视觉感知:到 tick 才跑
        if self.tick.should_tick(now) {
            sight_system(
                &effective_sight,
                eye_pos,
                self.facing,
                player_pos,
                sight_obstacles,
                &mut self.blackboard,
                now,
            );
        }

        // 4. 听觉感知:处理这一帧收到的声音事件
        hearing_system(
            &effective_hearing,
            eye_pos,
            pending_sounds,
            sound_obstacles,
            &mut self.blackboard,
            now,
        );

        // 5. 记忆衰减:每 N 秒跑一次(便宜,可以每帧跑,但每秒一次足够)
        // half_life 5 秒:5 秒前的记忆置信度减半
        self.blackboard.decay(now, 5.0);
    }
}
```

行为系统(在 [ai-patterns](../../phase-2/deep-dives/ai-patterns.md) 里的 FSM / BT / Utility)从这个 `NpcPerception` 读取决策依据:

```rust
/// 行为系统读感知,决定动作。这是 FSM 的转移函数。
pub fn decide_action(perception: &NpcPerception, now: f32) -> NpcAction {
    let bb = &perception.blackboard;
    let alert = perception.alertness.level;

    match alert {
        AlertLevel::Alerted => {
            // 战斗状态:有 LastSeenPlayerPos 就追,没有就搜查
            if let Some(pos) = bb.get_position(FactKey::LastSeenPlayerPos, 0.4) {
                NpcAction::Chase(pos)
            } else if let Some(pos) = bb.get_position(FactKey::LastSeenPlayerPos, 0.1) {
                NpcAction::Investigate(pos)    // 记忆模糊了,去最后看见的位置搜
            } else if let Some(pos) = bb.get_position(FactKey::LastHeardSoundPos, 0.3) {
                NpcAction::Investigate(pos)
            } else {
                NpcAction::Search               // 完全丢了,系统性搜索
            }
        }
        AlertLevel::Suspicious => {
            // 怀疑:去听见/瞥见的位置查
            if let Some(pos) = bb.get_position(FactKey::LastSeenPlayerPos, 0.4) {
                NpcAction::Investigate(pos)
            } else if let Some(pos) = bb.get_position(FactKey::LastHeardSoundPos, 0.3) {
                NpcAction::Investigate(pos)
            } else {
                NpcAction::AlertedPatrol        // 警觉巡逻(慢、转头频繁)
            }
        }
        AlertLevel::Unaware => {
            NpcAction::Patrol                   // 正常巡逻
        }
    }
}

#[derive(Clone, Debug)]
pub enum NpcAction {
    Patrol,
    AlertedPatrol,
    Investigate(Vec2),
    Chase(Vec2),
    Search,
}
```

注意 `get_position` 的 `min_confidence` 参数——不同动作对置信度的要求不同。Chase 要求 LastSeenPlayerPos 置信度 ≥ 0.4(我记得比较清楚才追);Investigate 只要 ≥ 0.1(模糊记忆也值得查一眼)。这是黑板置信度直接影响行为的具体体现——记忆的"清晰度"决定 NPC 的"果断度"。

`Investigate` 动作会让 NPC 用 [navmesh-and-pathfinding](../../phase-7/deep-dives/navmesh-and-pathfinding.md) 寻路到记忆位置,到达后**清除**该记忆(`forget(LastSeenPlayerPos)`),表示"我搜过了,这里没东西"。这给了玩家**主动甩开 NPC 的策略**——你跑到 A 点,NPC 看见,你绕远路跑到 B 点;NPC 跑到 A 点(记忆位置)搜了一圈,没找到,forget,suspicion 衰减,回到巡逻。这是 stealth 游戏的"诱敌"玩法基础。

## 7 · 生产现实:为什么 stealth 游戏全部依赖这一层

### 7.1 Stealth 游戏的感知-记忆-警觉三件套

让我把这一篇的架构和经典 stealth 游戏的实践对照一下。

**Metal Gear Solid 系列**:Kojima Productions 在 GDC 多次分享过他们的"AI 状态机 + 感知锥"。MGS 的感叹号头部图标(!)就是 suspicion 跨过 `thresh_alerted` 阈值的视觉化——玩家看见 NPC 头上出现 !,知道 NPC 切到了 Alerted。MGS 的"!状态"持续几秒后会降回 Suspicious(脑袋上的 ?),再降回 Normal。这正是本篇的 alertness 三级模型。

**Splinter Cell**:Ubisoft 的"光与影"系统的核心是**视觉感知对光照敏感**——NPC 在黑暗中看不见玩家(视觉 sight_range 根据目标位置的亮度动态调整),玩家躲在阴影里 = 视觉失效。这把"光照"变成了一个感知参数。Chaos Theory 的 NPC 还有听觉感知,玩家的脚步声根据地面材质(金属、木地板、水)响度不同,玩家可以"蹲走"降低脚步响度。这都是本篇框架内的扩展。

**The Last of Us / The Last of Us Part II**:Naughty Dog 的 NPC 是工业级"群组感知"的典范——一个 NPC 听见声音,会**通过 voice(喊话)事件**把信息广播给附近的其他 NPC,其他 NPC 的 suspicion 间接上升。这是 [group-and-squad-ai](group-and-squad-ai.md) 的核心:感知在群体里传播。

**Dishonored**:Arkane 的"混乱"系统让 NPC 的 suspicion 持续累积——瞥见尸体、听到打斗、发现失踪的同僚,suspicion 一点一点累加,直到集体 Alerted。这是黑板里的 `Suspicion` 键被多个事件累加写入。

### 7.2 为什么这一层是"游戏 AI"的标志

游戏圈常说"游戏 AI 不是学术 AI",这一篇就是这句话的最佳注脚。学术 AI 关心"最优决策",游戏 AI 关心"看起来像生灵"。一个 NPC 用 A* 找到最短路径、用 Utility AI 选了最优攻击动作,但它如果**全知**,玩家会觉得它在作弊;它如果**没有记忆**,玩家会觉得它是金鱼。让 NPC"看见的不是世界而是感官捕捉的世界""记得几秒前的事并逐渐遗忘""因为瞥见你而逐渐警觉、因为找不到你而逐渐冷静"——这些不是决策算法,而是**让决策算法看起来有生命**的包装层。

Millington《AI for Games》把感知、记忆、决策分成三章,反复强调三者解耦。这一篇就是把 Millington 的感知/记忆章节在 Rust 里落地的版本。当你写完这一篇的代码,你的守卫会从一个"读坐标的机器人"变成"会瞥见、会怀疑、会搜查、会遗忘的生灵"——这种差异是 stealth 游戏全部乐趣的来源。

### 7.3 和大脑、腿的关系

最后我想强调三者的分工。一个完整的"游戏 AI"由三层组成:

- **大脑**(decision):FSM / BT / Utility / GOAP。决定"做什么"。来自 [ai-patterns](../../phase-2/deep-dives/ai-patterns.md)。
- **感知+记忆**(perception+memory):看见/听见/记得。决定"知道什么"。本篇。
- **腿**(navigation):NavMesh + A* + steering + crowd。决定"怎么走到那里"。来自 [navmesh-and-pathfinding](../../phase-7/deep-dives/navmesh-and-pathfinding.md)。

三者通过黑板解耦:感知写黑板,大脑读黑板写动作,动作系统读动作执行寻路。这种分层让每一层可以独立调优——加新感知不影响大脑逻辑,改大脑算法不影响感知实现,换寻路库不影响其他两层。这是工业游戏 AI 架构的基石。

## 8 · 在你 HH 项目里动手(做中学红线)

把这一篇的所有代码落到你的 Handmade Hero Rust 项目里,给你的守卫 AI 装上感知和记忆。

**第 1 步:复制代码模块**。在你的 `src/ai/` 下新建 `perception.rs`,把本篇的 `SightConfig`、`in_sight_cone`、`line_of_sight_clear`、`can_see`、`HearingConfig`、`SoundEvent`、`can_hear`、`Blackboard`、`Fact`、`Alertness`、`NpcPerception` 全部贴进去。把 `AabbObstacle` / `SoundObstacle` 对接到你现有的关卡几何(把你的墙列表转换成 `Vec<AabbObstacle>`)。

**第 2 步:给守卫加感知组件**。在你的守卫 entity 上加 `NpcPerception`:

```rust
// 在你的 spawn 守卫函数里
commands.entity(guard_entity)
    .insert(NpcPerception::new(
        100.0,    // FOV 100 度
        20.0,     // sight_range 20 米
        0.3,      // 听觉阈值
    ));
```

**第 3 步:把感知接入主循环**。在你的 AI update system 里,把原来直接读玩家坐标的代码替换成感知:

```rust
// 旧代码(全知):
// let player_pos = world.player.position;
// if (player_pos - guard.pos).length() < SIGHT_RANGE {
//     guard.state = Chase;
//     guard.target = player_pos;
// }

// 新代码(感知驱动):
let player_pos = if world.player.alive { Some(world.player.position) } else { None };
let sight_obs: Vec<AabbObstacle> = world.walls.iter()
    .map(|w| AabbObstacle { min: w.min, max: w.max, blocks_sight: true })
    .collect();
let sound_obs: Vec<SoundObstacle> = world.walls.iter()
    .map(|w| SoundObstacle {
        min: w.min, max: w.max,
        transmission: w.material.sound_transmission(),
    })
    .collect();

// 每帧调用
guard.perception.update(
    world.time,
    dt,
    guard.position,
    player_pos,
    &sight_obs,
    &pending_sound_events,
    &sound_obs,
);

// 行为读感知
let action = decide_action(&guard.perception, world.time);
apply_action(guard, action, &navmesh);
```

**第 4 步:产生声音事件**。在你的玩家移动代码里,根据移动状态产生 `SoundEvent`:

```rust
// 玩家每走一步产生一个脚步声事件
if player.is_walking && player.step_timer <= 0.0 {
    pending_sound_events.push(SoundEvent::new(
        if player.is_running { SoundKind::FootstepLoud } else { SoundKind::Footstep },
        player.position,
        world.time,
    ));
    player.step_timer = if player.is_running { 0.3 } else { 0.5 };
}
player.step_timer -= dt;
```

**第 5 步:测试和观察**。这一步最重要——跑游戏,亲手对比感知版和旧的全知版。

- **潜行测试**:从守卫背后 2 米走过,守卫**不应该**反应(FOV 不覆盖后方)。绕到守卫侧后方进入视野锥边缘,守卫的 suspicion 应该慢慢升起,头上(如果你有 debug 可视化)显示 suspicion 条;完全进入视野锥,suspicion 急升,守卫切到 Alerted 追你。
- **遮挡测试**:在守卫和玩家之间放一道墙,守卫**不应该**看见墙后的玩家。LOS raycast 应该挡住视线。
- **听觉测试**:在墙后跑(脚步声响),守卫**应该**听见但不知道精确位置,会朝一个扰动过的位置走过去搜查。蹲走(脚步声弱),守卫**不应该**听见。
- **记忆测试**:让守卫看见你跑进一个房间,然后你从后门溜走。守卫应该跑到你最后被看见的位置(记忆),到达后搜一圈(清除记忆),suspicion 衰减,慢慢回到巡逻。
- **脱战测试**:进入 Alerted 状态后躲进草丛 30 秒,守卫应该逐渐冷静(Alerted → Suspicious → Unaware),最终回到巡逻。

**第 6 步:可视化调试**。在 debug overlay 里画守卫的 FOV 锥(一个扇形)、sight_range 圆、当前 suspicion 条、黑板里的 LastSeenPlayerPos(一个点 + 置信度颜色)、当前 AlertLevel(颜色编码:绿/黄/红)。这种可视化是感知系统的命脉——没有它你完全不知道为什么守卫"该反应时没反应"或"不该反应时反应了"。

完成这一篇后,你的守卫 AI 在行为上会产生**质变**——从一个全知的机器人,变成一个有视野盲区、会被骗、会搜查、会遗忘的生灵。这就是 stealth 游戏的核心可玩性来源。把这个版本提交,跑给朋友玩,看他们能不能利用守卫的视野盲区潜行过去——如果可以,你的感知系统真的工作了。

## 9 · 练习

**Lv 1**:修改 `SightConfig::new`,让守卫的 FOV 变成 60 度(更窄)、sight_range 变成 30 米(更远)。跑游戏观察守卫行为变化——更窄的 FOV 让侧后方更安全,更远的 sight_range 让正面更危险。

**Lv 2**:在 `SoundKind` 里加一个新的 `Whistle`(玩家吹口哨),响度 0.5、传播 15 米。在玩家按某个键时产生这个事件。利用它把守卫从巡逻位置吸引到指定地点——这是 stealth 游戏的"声东击西"玩法。

**Lv 3**:给黑板加一个新的 `FactKey::KnownPlayerSpeed`,记录玩家最后被看见时的速度(从连续两帧位置差计算)。行为系统利用它做**预测外推**——玩家消失时,根据最后速度推算玩家现在大概的位置,去推算位置搜查而不是最后看见的位置。这是从"记忆"升级到"推断"。

**Lv 4**:实现**群组感知广播**——一个 NPC 切到 Alerted 时,产生一个 `SoundEvent::Voice`(它喊话了),附近的其他 NPC 通过听觉感知"听见"这个喊声,他们的 suspicion 也间接上升。这是 [group-and-squad-ai](group-and-squad-ai.md) 的核心机制。提示:在 `decide_action` 切到 Alerted 时,往 `pending_sound_events` 推一个 Voice 事件,源头是该 NPC 位置。

## 10 · 延伸阅读与下一篇

**必读**:
- Ian Millington《AI for Games》第三版,第 10 章(World Interacting:感知)、第 11 章(Memory)。这是本篇的 calibration 来源,Millington 的黑板架构是工业标准。
- Brett Lajzer "A Brief Look at Game AI"(GDC Vault)——感知系统的工业概述。
- Bobby Anguelov "Game AI"系列博客,有 Splinter Cell 风格感知系统的实现细节。

**经典论文与演讲**:
- Mateas & Stern "A Behavior Language: Storytelling in Façade"(AIIDE 2005)——虽然 Façade 不是 stealth 游戏,但他们的事实/记忆系统对本篇架构有直接影响。
- Ubisoft GDC 演讲 "Splinter Cell: Conviction AI"(GDC 2011)——讲解了他们的"感知-传播-群组"系统。
- Naughty Dog "The Last of Us: AI"(GDC 2014)——NPC 群组感知与"通过 voice 事件传播警觉"。

**Rust 生态**:
- `bigbrain` crate([ai-patterns](../../phase-2/deep-dives/ai-patterns.md) 里介绍过)有 scorer/action 抽象,可以和本篇的黑板结合——黑板作为 scorer 的输入。
- `bevy_rapier` 提供 raycast,可以直接用作本篇的 LOS 实现,代替朴素 `segment_hits_aabb`。
- Bevy 的 `Events<T>` 资源正好可以承载 `SoundEvent`,在 [event-systems-and-gameplay-foundations](event-systems-and-gameplay-foundations.md) 里有完整介绍。

**跨学科**:感知系统在机器人学里对应**传感器融合(sensor fusion)**——机器人有激光雷达、摄像头、IMU,传感器融合把这些异构数据合并成对世界的一致估计(Kalman filter、particle filter)。游戏 AI 比机器人简单(传感器噪声可控、世界确定),但概念一致。读 Thrun《Probabilistic Robotics》前几章可以看到"信念状态(belief state)"就是黑板带置信度的形式化。

**本系列上下文**:
- 铺垫:[ai-patterns](../../phase-2/deep-dives/ai-patterns.md) 提供了大脑(FSM/BT/Utility),[navmesh-and-pathfinding](../../phase-7/deep-dives/navmesh-and-pathfinding.md) 提供了腿(NavMesh + A* + funnel),[spatial-acceleration](../../phase-6/deep-dives/spatial-acceleration.md) 提供了 raycast 的加速结构(LOS 的性能支柱),[event-systems-and-gameplay-foundations](event-systems-and-gameplay-foundations.md) 提供了声音事件的分发机制
- 当天:本篇,感知+记忆,夹在大脑和腿之间
- 下一篇:[group-and-squad-ai](group-and-squad-ai.md)——当一个 NPC 通过 voice 事件把自己的警觉广播给附近同伴,你就有了群体 AI 的种子。下一篇展开"群组感知共享、队形、协同搜索、指挥链"等群体智能主题,本篇的黑板是它的基础。

---

**最终建议**:感知+记忆是 stealth 游戏和"可信 NPC"的灵魂。从最简单的 FOV+距离判断开始,加上 LOS,加上声音事件,加上黑板,加上 alertness——每一层都让 NPC 更像生灵。在你的 HH 项目里,这一篇的代码量不大(几百行),但跑起来后行为质变,这是游戏 AI 最值得投入的层。写完后,关掉 debug overlay,自己当玩家潜行穿过守卫区——如果你能利用守卫的盲区成功潜行,如果你被瞥见后能躲够时间脱战,如果守卫会去查你最后被看见的位置然后挠挠头离开——你的感知+记忆系统真的活了。这就是从"全知 AI"到"会看会听会忘的生灵"的完整旅程。
