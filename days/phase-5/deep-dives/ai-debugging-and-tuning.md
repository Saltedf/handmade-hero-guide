
# AI 调试与调参:把不可见的状态变成可观测、可回放、可热调的系统

> 你的怪物一会儿像战术大师:它会绕侧翼、压枪线、扔手雷逼你出掩体,三秒钟把你打成盒子。下一会儿它又像个木头人:贴着墙来回滑步、对着空气开枪、把整个弹匣打进地板。你看不出区别在哪——因为区别不在这一帧,而在五秒前它做过的一个感知判断、一次行为树跳转、一条 navmesh 边的失败。游戏 AI 是整个项目里**最难调试**的子系统:渲染错了你看一眼就知道,性能卡了 Tracy 一开就明,但"AI 为什么这么蠢"这个问题,你盯着屏幕只能猜。今天这一篇是 T6 游戏 AI 深度序列的**收口篇**:它不讲任何新的决策架构,而是讲怎么把已经造出来的 AI——状态机、行为树、感知记忆、小队协作——变得**看得见、回得去、调得动、测得准**。读完它,你会知道:为什么 Casey 在 HH 里花了整整六集给 debug overlay 加 AI 视图;为什么 Resident Evil 4 的隐藏 DDA 至今仍是行业教科书;为什么"AI 参数全部走 CVar"不是洁癖,而是让你在不重新编译的前提下把怪物手感磨出来的唯一办法。这一篇假设你已经读完了 [`ai-patterns`](../../phase-2/deep-dives/ai-patterns.md)(决策架构)、[`navmesh-and-pathfinding`](../../phase-7/deep-dives/navmesh-and-pathfinding.md)(移动)、[`ai-perception-and-memory`](./ai-perception-and-memory.md)(感知)和 [`group-and-squad-ai`](./group-and-squad-ai.md)(协作)。今天我们补上最后一块拼图:**developability**——AI 不只要"会跑",还要能被你"看见、回放、调参、自适应"地开发出来。

## 0 · 你正盯着屏幕猜怪物为什么撞墙

把你自己放回那个真实场景:你刚把 perception range 从 18 米调到 25 米,跑了一局,怪物忽然就傻了。它在 T 字路口前停了三秒,然后慢慢转过身,朝反方向走,撞上了它刚刚绕过的那堵墙,继续往前蹭,直到卡死。你不知道它发生了什么——它看到了玩家吗?它选了哪条 navmesh 边?它跑的是行为树的哪个分支?它的 alertness 是多少?你打开了 `println!`,刷了一屏 log,但这些 log 散落在不同 system、不同帧、不同 NPC 上,你拼不出因果链。

这就是 AI 调试的核心症状:**你能看到的永远是症状(sympyon),而原因(cause)藏在五秒前的某个状态字段里,现在早就被覆盖了**。AI 行为是 emergent(涌现)的、有状态(stateful)的、肉眼不可见的(invisible)。这三条加在一起,让 AI 调试从"工程问题"退化成"猜谜游戏"。

这一篇的全部技术——debug 可视化、行为录制回放、CVar 热调、DDA 自适应、属性与快照测试——都服务于一个目的:**让 AI 的内部状态变成一个可观测、可回溯、可干预的运行系统**,让你从"盯着屏幕猜"进化到"看见状态、回放决策、热调参数"。

## 1 · 为什么 AI 是游戏里最难调试的子系统

先把这个判断讲透,你才知道下面那些工具为什么值得造。

渲染有 bug,你下一帧就看见:三角形穿模、贴图发紫、阴影飞出去——视觉证据直接落在屏幕上,你按 pause 就能定格。性能有问题,Tracy 一开,火焰图上一条 14 毫秒的 bar 直接指给你看是哪个 system。音频有 bug,录一段波形,频谱仪一开就能看出是 60Hz 工频干扰还是 phase 错位。这三类 bug 都有一个共同点:**症状即证据,证据和原因在同一帧、同一空间维度上呈现**。

AI 不一样。AI bug 的标准形态是"怪物三秒前做了一个愚蠢决定,五秒后才在画面上显出来"。一个守卫为什么走进墙里?可能的原因有:perception 在那一帧漏掉了墙的遮挡查询;navmesh 边缘生成时把墙边一格误判成了可走;行为树的 `MoveTo` 节点收到了一个错误目标坐标;steering 的 separation 力把它推过了 navmesh 边界;reaction time 计时器没归零导致它一直追着一个老目标;alertness 衰减曲线写得不对让它过早放弃搜索。**六种可能的根因,都发生在已经过去的帧里,你看不到任何一个**。

更糟的是,AI 行为是 emergent 的——单个 system 都对,组合起来就错。perception system 正确报告"看到玩家",pathfinding system 正确生成路径,steering system 正确施加力,但三者协同起来,怪物就在墙边抖动。这种 emergent bug 你没法靠"读单个 system 的代码"找到,你必须**看见它们在同一帧里的协同状态**。

所以 AI 调试工具的本质是:**把不可见的状态、被覆盖的历史、跨 system 的协同,统统变成你可以定格、回放、检视的可观测对象**。下面四节就是干这件事的四个杠杆,按"投入产出比"从高到低排:可视化(第一节,投入最小回报最大)、录制回放(第二节)、CVar 热调(第三节)、DDA(第四节),最后是测试(第五节)。

## 2 · 第一节杠杆:AI Debug 可视化——让不可见的状态变成屏幕上的几何

如果你只能做一件事情来改善 AI 调试,就做这一件:**把 AI 的所有内部状态画到屏幕上**。FOV cone(视野扇形)、hearing radius(听觉范围)、last-known-position(最后已知位置)标记、当前行为树节点高亮、当前 navmesh 路径线段、alertness 数值条——这些原本是 NPC 脑子里看不见的字段,一旦画出来,AI 立刻从黑盒变成玻璃盒。

这一节直接对接 [`debug-overlay-design`](./debug-overlay-design.md)(Day 176-234 那一整套 overlay 渲染管线)和 [09D debug viz] 的可视化规范。你不需要新造渲染器——`debug-overlay-design` 里那套 `DrawLayer { rects, texts, lines }` 已经够了。AI 可视化本质上是**往 lines 和 texts 这两个 layer 里塞几何**。

让我用一个最小的 Rust 模块把这个想法落地。假设你已经有 `DrawLayer`(lines + texts)、有 `Npc` 实体(含 `Transform`、`Perception`、`Brain`、`Path`、`Alertness` 组件):

```rust
// ai_debug.rs
use crate::draw::{DrawLayer, Color};
use crate::math::{Vec2, Vec3};
use crate::cvar::CVarStore;

/// 一个 AI debug 视图的总开关,本身是一个 CVar,可以在 console 里 `ai_debug 1` 打开。
/// 这就是 [09B-4 CVars for live AI tuning] 里讲的"用 CVar 驱动 debug 视图"。
pub struct AiDebugView {
    pub show_fov: bool,
    pub show_hearing: bool,
    pub show_lkp: bool,        // last-known-position
    pub show_path: bool,
    pub show_alertness: bool,
    pub show_bt_node: bool,    // 当前行为树节点
    pub show_target: bool,
}

impl AiDebugView {
    /// 从 CVar 仓库同步开关。这样 QA 在 console 里 `ai_debug.fov 0` 就能单独关掉视野。
    pub fn sync_from_cvars(&mut self, cvars: &CVarStore) {
        self.show_fov        = cvars.get_bool("ai_debug.fov");
        self.show_hearing    = cvars.get_bool("ai_debug.hearing");
        self.show_lkp        = cvars.get_bool("ai_debug.lkp");
        self.show_path       = cvars.get_bool("ai_debug.path");
        self.show_alertness  = cvars.get_bool("ai_debug.alertness");
        self.show_bt_node    = cvars.get_bool("ai_debug.bt");
        self.show_target     = cvars.get_bool("ai_debug.target");
    }
}

/// 把一个 NPC 的所有 debug 几何推进 DrawLayer。
/// 这是"AI 可视化"的核心:它不修改游戏状态,只读取状态并画几何。
pub fn draw_npc_debug(
    layer: &mut DrawLayer,
    view: &AiDebugView,
    pos: Vec2,
    facing: f32,                  // 朝向,弧度
    perc: &Perception,
    brain: &Brain,
    path: &Path,
    alertness: f32,
) {
    // 视野扇形:画两条边 + 一段弧(用 N 段折线近似)
    if view.show_fov {
        let half = perc.fov_radians * 0.5;
        let r = perc.sight_range;
        let left  = pos + Vec2::from_angle(facing - half) * r;
        let right = pos + Vec2::from_angle(facing + half) * r;
        // 颜色按"是否当前看到目标"区分:看到 = 红,没看到 = 黄
        let color = if perc.can_see_target { Color::RED } else { Color::YELLOW };
        layer.line(pos, left,  color);
        layer.line(pos, right, color);
        // 弧线:16 段折线近似
        let segs = 16;
        for i in 0..segs {
            let a0 = facing - half + (2.0 * half) * (i as f32 / segs as f32);
            let a1 = facing - half + (2.0 * half) * ((i + 1) as f32 / segs as f32);
            layer.line(pos + Vec2::from_angle(a0) * r,
                       pos + Vec2::from_angle(a1) * r, color);
        }
    }

    // 听觉范围:一个圆。比 FOV 大,因为听觉没有方向限制。
    if view.show_hearing {
        let segs = 24;
        let r = perc.hearing_range;
        for i in 0..segs {
            let a0 = std::f32::consts::TAU * (i as f32 / segs as f32);
            let a1 = std::f32::consts::TAU * ((i + 1) as f32 / segs as f32);
            layer.line(pos + Vec2::from_angle(a0) * r,
                       pos + Vec2::from_angle(a1) * r, Color::CYAN.alpha(0.4));
        }
    }

    // 最后已知位置:一个十字 + 时间戳文字
    if view.show_lkp {
        if let Some(lkp) = &perc.last_known_pos {
            let s = 0.5;
            layer.line(lkp.pos - Vec2::X * s, lkp.pos + Vec2::X * s, Color::MAGENTA);
            layer.line(lkp.pos - Vec2::Y * s, lkp.pos + Vec2::Y * s, Color::MAGENTA);
            layer.text(lkp.pos + Vec2::Y * 0.8,
                       &format!("LKP {:.1}s ago", lkp.age), Color::MAGENTA);
        }
    }

    // 当前 navmesh 路径:把 path.waypoints 连成折线
    if view.show_path && path.waypoints.len() >= 2 {
        for w in path.waypoints.windows(2) {
            layer.line(w[0], w[1], Color::GREEN.alpha(0.6));
        }
        // 终点画个方框
        let end = *path.waypoints.last().unwrap();
        let s = 0.3;
        layer.line(end - Vec2::X * s, end + Vec2::X * s, Color::GREEN);
        layer.line(end - Vec2::Y * s, end + Vec2::Y * s, Color::GREEN);
    }

    // 当前行为树节点:在 NPC 头顶用文字标
    if view.show_bt_node {
        layer.text(pos + Vec2::Y * 1.2, brain.current_node_name(), Color::WHITE);
    }

    // Alertness:在 NPC 头顶画一条小柱状图,0~1
    if view.show_alertness {
        let bar_pos = pos + Vec2::Y * 1.5;
        let w = 1.0;
        let h = 0.15;
        // 背景
        layer.rect(bar_pos, Vec2::X * w, Color::GRAY.alpha(0.3));
        // 前景
        let a = alertness.clamp(0.0, 1.0);
        let col = if a < 0.3 { Color::GREEN }
                  else if a < 0.7 { Color::YELLOW }
                  else { Color::RED };
        layer.rect(bar_pos, Vec2::X * (w * a), col);
    }
}
```

注意几个设计决定,它们都是从血泪里学出来的。

第一,**所有颜色按状态变色**,不按 NPC 类型变色。视野扇形看到目标时变红、没看到时变黄——这样你扫一眼屏幕就知道哪个 NPC 处于什么感知状态。如果你按 NPC 类型上色(红队红、蓝队蓝),你又要去读图例,失去了"一眼看懂"的价值。

第二,**几何要带 alpha**。FOV 扇形是半透明的,因为你要透过它看见后面的几何。`Color::YELLOW.alpha(0.4)` 这种写法很重要——debug 几何永远不该挡住游戏画面。

第三,**开关粒度要细**。不要只给一个 `ai_debug 0/1` 总开关,要给 `ai_debug.fov`、`ai_debug.path`、`ai_debug.bt` 这种分项开关。原因:你调试 perception 问题时只关心 FOV 和 LKP,把 path 和 bt 关掉减少视觉噪声;调试寻路时反过来。颗粒度越细,你越能聚焦到当前怀疑的 subsystem。

第四,**开关本身必须是 CVar**(见 [09B-4]),不能是编译期常量。原因是 QA 测试时不会重新编译,他们只在 release build 的 console 里敲命令。如果你的开关是 `#[cfg(debug_assertions)]`,QA 永远摸不到这个工具。

第五,**绘制必须只读不改**。`draw_npc_debug` 只取 `&Perception`、`&Brain`,不取 `&mut`。这是纪律:debug 代码改了游戏状态,会引入"开了 debug 就不复现"的 bug,这种 bug 比原始 bug 还难查。

这一节我只画了六个东西——FOV、听觉、LKP、路径、行为节点、alertness。你的项目里还可以加:威胁评估热图(utility AI 的分数云)、小队阵型框(group-and-squad-ai 的 formation)、感知射线(每条 sight ray 的命中点)、状态机转移箭头。原则都一样:把脑子里看不见的字段画到屏幕上。**你一旦能看见 AI 在感知什么、决定什么,调试就从猜谜变成观察**。这是整个 AI 工具链里 ROI 最高的一节。

## 3 · 第二节杠杆:行为录制与回放——把"五秒前的决定"找回来

可视化解决了"现在看不见"的问题,但解决不了"五秒前发生了什么"。当 bug 发生时,你 pause 下来,FOV 扇形画的是当前帧的感知状态,但愚蠢的决策已经在五秒前做完了,当前帧的 debug 视图是干净的——你抓不到凶手。

你需要的是**录制(recording)**:每帧把每个 NPC 的关键决策和状态记下来,bug 出现时倒带回去,逐帧检视。这就是 determinism/replay([09A-4 determinism-and-replay])技术应用到 AI 调试上。

先想清楚你要记什么。不是所有状态都值得记——记太多会撑爆内存、写盘太慢、回放卡顿。最小可行的 AI 录制应该每帧、每个 NPC 记这几个字段:

```rust
// ai_recording.rs
use crate::math::Vec2;

/// 单个 NPC 在某一帧的 AI 快照。我们要把它写得**小**,
/// 因为 60FPS × 50 NPC × N 帧 = 几百万条记录。
#[derive(Clone, Copy)]
pub struct AiFrameSnap {
    pub frame: u32,
    pub npc_id: u32,
    pub pos: Vec2,                    // 位置
    pub facing: f32,                  // 朝向
    pub can_see_target: bool,         // 感知结果
    pub alertness: f32,               // u8 也行,这里用 f32 方便理解
    pub decision: DecisionTag,        // 这一帧做的关键决定
    pub decision_reason: ReasonTag,   // 决定的原因
}

/// 决定的标签——用 enum + repr(u8) 压到 1 字节。
/// 不要用 String:String 一进 recording,每帧分配,GCM 暴涨。
#[derive(Clone, Copy, PartialEq)]
#[repr(u8)]
pub enum DecisionTag {
    None = 0,
    StartChase,
    StopChase,
    StartSearch,
    StartAttack,
    StartFlee,
    Repath,           // 重新寻路
    GiveUpSearch,
    CallReinforcement, // 小队协作:呼叫增援
}

/// 决定的原因。同样压成 u8。
#[derive(Clone, Copy, PartialEq)]
#[repr(u8)]
pub enum ReasonTag {
    None = 0,
    SawTarget,
    HeardNoise,
    LostSight,
    Timeout,           // 反应时间到
    Damaged,           // 被打
    FriendCalled,      // 队友呼叫
    PathBlocked,       // 路径被堵
    PathInvalid,
}
```

把 `String` 拒之门外是这一节最重要的纪律。如果你给 `decision` 用 `String("StartChase because SawTarget at ...")`,50 个 NPC × 60 FPS × 60 秒 = 18 万条 String,每条几十字节,加上 `String` 的堆分配,你的 recording 系统会变成 GC 噩梦,而且 release build 里字符串拼接影响性能,让你"开录制就复现不了 bug"。用 `enum + repr(u8)`,一条记录压到 24 字节左右,18 万条也就 4MB,完全无压力。

录制循环本身很朴素:

```rust
pub struct AiRecorder {
    pub frames: Vec<AiFrameSnap>,
    pub capacity: usize,  // ring buffer 容量,默认保留最近 60 秒
}

impl AiRecorder {
    pub fn record(&mut self, snap: AiFrameSnap) {
        if self.frames.len() >= self.capacity {
            // 简单 ring:移除最旧。生产里用 deque 或 mmap 文件更优。
            self.frames.remove(0);
        }
        self.frames.push(snap);
    }

    /// 回放:按时间窗口查询某 NPC 的决策历史。
    /// 这是"找凶手"的核心 API:bug 发生在 frame F,你查 F-N..F 的所有 decision != None。
    pub fn decisions_for(&self, npc_id: u32, from_frame: u32, to_frame: u32)
        -> Vec<&AiFrameSnap>
    {
        self.frames.iter()
            .filter(|s| s.npc_id == npc_id
                     && s.frame >= from_frame
                     && s.frame <= to_frame
                     && s.decision != DecisionTag::None)
            .collect()
    }
}
```

实际怎么用?假设玩家报告"守卫在 0:42 卡住了"。你 pause,看 recorder 里 npc_id=17 在 frame 150000(约 0:42)之前的决策序列:

```
frame 149820  StartChase    SawTarget
frame 149840  Repath        PathBlocked
frame 149860  Repath        PathBlocked
frame 149880  Repath        PathBlocked
... (50 次 Repath/PathBlocked)
frame 150000  StopChase     LostSight
```

瞬间你就看见了:守卫在 149820 看到玩家,尝试寻路,路径被堵,连续 50 次重新寻路都失败,最后因为丢视野放弃追击。问题不在 perception,不在 brain,而在 **navmesh 在那个位置生成不出有效路径**——你立刻知道要去查 [`navmesh-and-pathfinding`](../../phase-7/deep-dives/navmesh-and-pathfinding.md) 里讲的 navmesh 边缘生成,而不是 perception system。

这就是录制回放相对于可视化更高一档的能力:**它给你时间维度**。可视化是横截面(某一帧),录制是时间序列(一段时间)。两者配合,你能从"卡死的当前帧"反推回"五秒前的错误决定",这是任何严肃 AI 调试必备的杠杆。

进阶一档,录制可以做成**完整 replay**:不只记 AI 决策,还记所有玩家输入,这样你能从 recorder 里精确复现整个 session。这要求你的游戏是 deterministic 的([09A-4 determinism-and-replay] 那一篇讲的所有坑——IEEE 754 跨平台、RNG 决定性、计时器),但一旦做到,你就能把 QA 报的 bug 录制直接加载到开发机,100% 复现,逐帧 step。这就是 snapshot testing 的基础设施——见下一节。

## 4 · 第三节杠杆:CVar 热调——AI 参数必须能边玩边改

到这里你大概已经看出 AI 调参的痛点了:怪物 sight range 是 25 米还是 18 米?reaction time 是 0.3 秒还是 0.8 秒?aggression 评分的曲线长什么样?这些问题**没有理论答案**,只有 playtest 答案。你必须反复跑、反复感受、反复调。如果你每次改一个参数都要重新编译——按 [09B-4] 里那个"40 秒编译"的噩梦——你调一组参数要 100 次迭代,100 × 40 秒 = 67 分钟,纯等编译。这种迭代速度下,你根本磨不出手感。

解法只有一个:**所有 AI 参数必须是 CVar**(console variable),让你在游戏运行时通过 console 改:`ai.guard.sight_range 22`、`ai.guard.reaction_time 0.45`、`ai.guard.accuracy 0.7`,改完立刻生效,不用编译,不用重启,甚至不用暂停。这一节就是讲怎么把 AI 参数 CVar 化,以及 CVar 化之后调参工作流变成什么样。

先看一个 AI 参数表怎么用 CVar 重新组织。原本你可能是写死的常量:

```rust
// 旧:硬编码,改一个数字要等 40 秒编译
const SIGHT_RANGE: f32 = 18.0;
const REACTION_TIME: f32 = 0.5;
const ACCURACY: f32 = 0.6;
```

改成 CVar:

```rust
// ai_params.rs
use crate::cvar::{CVarStore, CVarDecl};

/// 一组 NPC 模板的 AI 参数,全部由 CVar 提供。
/// 注意:这不存"当前值",它每次 update 都从 CVarStore 现读——
/// 这样 console 里改 CVar 立即影响 AI 行为,无需同步。
pub struct AiParams {
    sight_range:     CVarDecl<f32>,
    fov_degrees:     CVarDecl<f32>,
    hearing_range:   CVarDecl<f32>,
    reaction_time:   CVarDecl<f32>,
    aggression:      CVarDecl<f32>,   // 0..1,影响 utility AI 的攻击评分
    accuracy:        CVarDecl<f32>,   // 0..1,射击散布
    alertness_decay: CVarDecl<f32>,   // 每秒衰减多少
    search_duration: CVarDecl<f32>,   // 失去目标后搜索多久
}

impl AiParams {
    /// 注册所有 CVar。在游戏启动时调用一次。
    /// default / min / max 是这里的灵魂:clamp 防止 QA 输入 NaN 或负数把 AI 弄崩。
    pub fn register(cvars: &mut CVarStore, archetype: &str) -> Self {
        let p = format!("ai.{}.", archetype);  // e.g. "ai.guard."
        Self {
            sight_range: cvars.declare_f32(&format!("{}sight_range", p), 18.0, 1.0, 100.0),
            fov_degrees: cvars.declare_f32(&format!("{}fov_degrees", p),   90.0, 10.0, 360.0),
            hearing_range: cvars.declare_f32(&format!("{}hearing_range", p), 12.0, 0.0, 50.0),
            reaction_time: cvars.declare_f32(&format!("{}reaction_time", p), 0.5, 0.0, 5.0),
            aggression: cvars.declare_f32(&format!("{}aggression", p), 0.6, 0.0, 1.0),
            accuracy:  cvars.declare_f32(&format!("{}accuracy", p), 0.6, 0.0, 1.0),
            alertness_decay: cvars.declare_f32(&format!("{}alertness_decay", p), 0.15, 0.0, 1.0),
            search_duration: cvars.declare_f32(&format!("{}search_duration", p), 8.0, 0.0, 60.0),
        }
    }

    /// 把这些参数应用到具体 NPC 实例上。
    /// 在 brain update 前 fetch,这样这一帧 CVar 的值就生效。
    pub fn fetch(&self, cvars: &CVarStore) -> ResolvedAiParams {
        ResolvedAiParams {
            sight_range:     cvars.get_f32_clamped(&self.sight_range),
            fov_degrees:     cvars.get_f32_clamped(&self.fov_degrees),
            hearing_range:   cvars.get_f32_clamped(&self.hearing_range),
            reaction_time:   cvars.get_f32_clamped(&self.reaction_time),
            aggression:      cvars.get_f32_clamped(&self.aggression),
            accuracy:        cvars.get_f32_clamped(&self.accuracy),
            alertness_decay: cvars.get_f32_clamped(&self.alertness_decay),
            search_duration: cvars.get_f32_clamped(&self.search_duration),
        }
    }
}

/// 一帧里"快照下来"的 AI 参数。update 函数拿这个,而不是 CVarStore 引用。
pub struct ResolvedAiParams {
    pub sight_range: f32,
    pub fov_degrees: f32,
    pub hearing_range: f32,
    pub reaction_time: f32,
    pub aggression: f32,
    pub accuracy: f32,
    pub alertness_decay: f32,
    pub search_duration: f32,
}
```

几个设计点要讲清楚。

**为什么 `register` 时要带 min/max**。因为 QA 会在 console 里瞎敲,他们会输 `ai.guard.sight_range -5`、`ai.guard.accuracy 9999`、`ai.guard.reaction_time NaN`。如果没有 clamp,你的 perception system 会用 `-5` 当 sight range,射线查询返回空,怪物变瞎;用 `9999` 当 accuracy,枪枪爆头,玩家毫无体验;用 `NaN` 当 reaction time,所有比较都返回 false,行为树卡死。min/max 是防御性的,不写不行。

**为什么按 archetype 命名空间化**(`ai.guard.sight_range` 而不是 `ai.sight_range`)。因为同一游戏里有多种 NPC——guard、sniper、dog、boss——它们的参数语义同名但数值天差地别。guard 的 sight_range 是 18,sniper 是 60,boss 是 80。命名空间化让你同时调多个 archetype,而不会互相覆盖。

**为什么 `fetch` 而不是直接持有值**。因为 CVar 是全局可变的(console 随时改),如果你把值快照到 NPC 组件里存着,console 改了 CVar 也不会影响已经快照过的 NPC。所以正确做法是**每帧 update 前 fetch**,保证这一帧所有 NPC 都用最新的 CVar 值。这是性能/正确性的权衡:fetch 是几次 hashmap 查询,NPC 多了的开销也就几百纳秒,完全可接受。

**CVar 化之后的调参工作流**长什么样。你打开游戏,左半屏是游戏画面,右半屏是 console。你跑一局,觉得怪物反应太慢,console 敲 `ai.guard.reaction_time 0.3`,下一秒就生效,怪物立刻变快。你继续玩,觉得太凶,敲 `ai.guard.aggression 0.4`,怪物立刻保守一点。100 次迭代你 10 分钟跑完,而不是 67 分钟等编译。**这就是 CVar 化的 ROI——把"调参"从"编译-运行-评估"的三步慢循环,变成"边玩边改"的一步快循环**。

最后一个关键点:**CVar 必须能持久化**。你在 console 里调了 100 个值,手感正好,然后你关游戏——这些值丢了,你又要从头调。CVar 系统要支持 `cvar_save ai.cfg` 和 `cvar_load ai.cfg`,把当前所有 CVar 序列化到文件,下次启动自动加载。这个文件就是设计师调出来的"AI 配置",最终会进入 release build 的默认值。这是 CVar 从"调试工具"升级成"设计师工作流"的关键一步——[09B-4 CVars for live AI tuning] 那一篇专门讲这个,这里不重复。

## 5 · 第四节杠杆:动态难度调整(DDA)——让 AI 自己调参适配玩家

前面三节都是"开发者调 AI",这一节是"AI 调自己来适配玩家"——Dynamic Difficulty Adjustment(DDA)。

先讲清楚 DDA 要解决什么问题。游戏设计的圣杯是**心流通道(flow channel)**:玩家技能和挑战难度匹配时,玩家进入"心流"状态——既不无聊(挑战太低),也不挫败(挑战太高)。但玩家技能是连续变量,你的游戏发售后会被各种水平的玩家玩:硬核玩家三小时通关,休闲玩家卡在第二关。固定难度(Difficulty: Easy/Normal/Hard)只有三档,粒度太粗,照顾不到中间所有玩家。DDA 的思路是:**游戏实时观察玩家表现,动态调整 AI / 经济 / 资源难度,把玩家始终维持在心流通道里**。

 Resident Evil 4 的隐藏 DDA 是这一块的教科书案例(它的存在是 Scurrilous 的 GDC 演讲之后才广为人知的)。游戏偷偷监控玩家的:死亡次数、受击率、剩余弹药、剩余血量、爆头率。如果你死了三次,下一次 reload 时游戏悄悄把敌人的 HP 调低 10%、把掉落物的弹药量调高 20%、把某些 QTE 的时间窗口加长。**玩家完全不知道难度被调过**,只觉得"刚才那一段好难,这一段终于缓过来了"——其实缓过来是游戏故意让你缓的。这种隐藏 DDA 在设计上非常有效,但也非常危险,我们待会儿讲为什么。

先用 Rust 把一个最小 DDA 系统写出来,你就能看清它的结构:

```rust
// dda.rs

/// 玩家表现的实时度量。DDA 的"输入"。
/// 注意所有字段都是滑动窗口平均,不是瞬时值——否则 DDA 会抖动。
pub struct PlayerPerformance {
    pub recent_death_rate: f32,    // 最近 N 分钟死亡次数(滑动平均)
    pub recent_accuracy:   f32,    // 最近命中率
    pub recent_damage_taken: f32,  // 每分钟受击量
    pub recent_progress_speed: f32,// 每分钟推进的关卡进度(0..1)
    pub ammo_efficiency: f32,      // 每发弹药造成的伤害
}

/// DDA 的"输出":一组难度乘子,作用到 AI 参数和资源掉落上。
pub struct DifficultyMultipliers {
    pub ai_accuracy:   f32,   // 1.0 = 不变,0.8 = AI 准度降 20%
    pub ai_aggression: f32,   // 1.0 = 不变,1.2 = AI 更激进 20%
    pub ai_reaction:   f32,   // 反应时间乘子(>1 更慢,<1 更快)
    pub enemy_hp:      f32,   // 敌人 HP 乘子
    pub ammo_drops:    f32,   // 弹药掉落数量乘子
    pub heal_drops:    f32,   // 治疗物品掉落乘子
}

/// DDA 的核心:把玩家表现映射到难度乘子。
/// 这是设计性最强的函数——下面的曲线就是"游戏手感"本身。
pub fn compute_dda(perf: &PlayerPerformance) -> DifficultyMultipliers {
    // 综合分:0 = 玩家挣扎,1 = 玩家碾压,0.5 = 心流
    // 每一项映射到 [0,1]:death rate 高 -> 分低;accuracy 高 -> 分高;等等。
    let struggle = 0.0
        + perf.recent_death_rate.clamp(0.0, 3.0) / 3.0 * 0.4   // 死得多 -> 挣扎
        + (1.0 - perf.recent_accuracy.clamp(0.0, 1.0)) * 0.2    // 打不准 -> 挣扎
        + (1.0 - perf.recent_progress_speed.clamp(0.0, 1.0)) * 0.2
        + (1.0 - perf.ammo_efficiency.clamp(0.0, 1.0)) * 0.2;
    // struggle ∈ [0, 1]:0 = 碾压,1 = 挣扎

    // 把 struggle 映射到难度乘子。
    // 关键:用平滑曲线,不要线性——线性 DDA 会让玩家感觉到"难度在调"。
    // 这里用 smoothstep:在 struggle=0.5 附近变化最慢,极端处变化快。
    let ease = smoothstep(0.0, 1.0, struggle);  // 玩家越挣扎, ease 越接近 1

    DifficultyMultipliers {
        // 玩家挣扎 -> AI 准度降、AI 慢、敌人血薄、弹药多
        ai_accuracy:   lerp(1.0, 0.55, ease),
        ai_aggression: lerp(1.0, 0.60, ease),
        ai_reaction:   lerp(1.0, 1.80, ease),    // 反应时间放大
        enemy_hp:      lerp(1.0, 0.75, ease),
        ammo_drops:    lerp(1.0, 1.50, ease),
        heal_drops:    lerp(1.0, 1.80, ease),
    }
}

fn smoothstep(edge0: f32, edge1: f32, x: f32) -> f32 {
    let t = ((x - edge0) / (edge1 - edge0)).clamp(0.0, 1.0);
    t * t * (3.0 - 2.0 * t)
}

fn lerp(a: f32, b: f32, t: f32) -> f32 {
    a + (b - a) * t
}
```

这里有几个设计原则要拎出来讲。

**所有输入用滑动窗口平均,不用瞬时值**。如果你用"上一帧的命中率",DDA 会疯狂抖动:玩家一发打偏,accuracy 跳到 0,DDA 立刻把难度调低,玩家下一发命中,又调回来。这种抖动玩家感受得到,体验极差。正确做法是 30 秒或 60 秒的滑动窗口平均,这样玩家连续打偏 10 秒才会让 DDA 反应过来。窗口长度本身就是 CVar:`dda.window_seconds 60`。

**输出曲线要平滑,不要线性**。上面的 `smoothstep` 就是干这个的。线性 DDA(`struggle * 0.5`)在边界附近变化太快,玩家一死两次难度立刻砍半,他能感觉到。`smoothstep` 在中段(0.5 附近)变化最慢,极端处变化快,这样大多数玩家(处于中段)感觉不到难度变化,只有真正挣扎的玩家才得到显著帮扶。这是 RE4 隐藏 DDA 不被玩家察觉的关键技巧。

**DDA 输出和 CVar 系统如何配合**。看上面的 `DifficultyMultipliers`——它的字段和 [`ai-patterns`](../../phase-2/deep-dives/ai-patterns.md) 里讲的 AI 参数同构。落地的做法是:DDA 系统每帧(或每 N 帧)算出 `DifficultyMultipliers`,然后把这些乘子乘到 CVar fetch 出来的基础值上。NPC 的"实际 sight range" = `cvar.ai.guard.sight_range * 1.0`(DDA 通常不调 sight range,因为这会改变 perception,体感太明显);"实际 accuracy" = `cvar.ai.guard.accuracy * dda.ai_accuracy`。这样设计师用 CVar 调"基础难度曲线",DDA 在基础上做"实时微调",两层职责清晰。

**DDA 的设计张力**。这是这一节最重要的一段话,值得仔细读。DDA 有一个内在矛盾:**透明的 DDA 让玩家觉得"游戏在响应我",太明显的 DDA 让玩家觉得"游戏在操纵我"**。前者是好体验,后者是糟糕体验——玩家如果意识到"我一死难度就降",他会觉得自己的胜利不是赢来的,是游戏施舍的,成就感瞬间崩塌。所以 DDA 设计的精髓是:**调,但别让玩家看出来在调**。技巧包括:用长滑动窗口(60 秒以上,玩家察觉不到短时变化)、用平滑曲线(避免突变)、不要在玩家"接近胜利"时调难度(那最容易被看出来)、把帮扶"伪装"成游戏内的偶然(比如让掉落物"恰好"出现在玩家路径上,而不是直接加血量上限)。RE4 的 DDA 至今被反复研究,就是因为它做到了"玩家完全感觉不到"。

**一个反向的设计警告**。不要把 DDA 当作平衡性差的借口。如果你的基础难度曲线就崩了(硬核玩家觉得太简单、休闲玩家觉得太难,中间断层),DDA 救不了你——它只能在合理的基础上微调。先把基础难度调好,再上 DDA,顺序不能反。DDA 是 polish,不是 fix。

最后,DDA 是否公开是一个**游戏定位问题**,不是技术问题。竞技类游戏(《英雄联盟》《CS》)绝不公开 DDA——玩家会觉得被操纵。叙事类游戏(RE4、《最后生还者》)用隐藏 DDA 提升体验——玩家要的是故事流畅,不是被卡死。你做 HH 这种单机 RPG,隐藏 DDA 是合理的;如果你做 PVP,完全不要 DDA,公平是底线。

## 6 · 第五节杠杆:测试 AI——把涌现的 bug 关进笼子

到这里我们有了可视化、录制、CVar、DDA——但这些都是"开发者手动观察"的工具。AI 还需要一个"自动化"的防线:**测试**。AI 测试是整个 QA 序列([09A testing-and-qa])里最难的子问题,因为 AI 行为大部分是 emergent 的,你没法写"`attack()` 应该返回 true"这种单元测试——AI 的 bug 是"在某种世界状态下,某个 NPC 走向某种愚蠢行为",这种 bug 难以枚举、难以重现、难以断言。

但难不等于不做。AI 测试可以拆成两层:**决定性部分用 snapshot/property test,涌现部分用 behavioral test**。

决定性部分是指那些"输入相同世界状态,输出必然相同"的纯函数。最典型的就是 perception 查询:给定 NPC 位置、玩家位置、遮挡几何,LOS(line of sight)查询必须返回确定结果。这种东西可以 snapshot 测试([09A-3 snapshot testing]):

```rust
// tests/perception_snapshot.rs
use crate::ai::perception::{compute_los, World几何};

#[test]
fn snapshot_guard_los_to_player_through_pillar() {
    let world = World几何::load("tests/fixtures/t_junction.geom");
    let guard_pos = Vec2::new(10.0, 5.0);
    let player_pos = Vec2::new(10.0, 20.0);
    let pillar = vec![/* 柱子的遮挡多边形 */];

    let result = compute_los(guard_pos, player_pos, &pillar, &world);

    // snapshot:第一次跑生成 .snap 文件,之后每次跑对比。
    // 柱子位置改了,perception 行为变了,这个 test 会失败——
    // 你立刻知道你的 navmesh / 遮挡改动影响了 perception。
    insta::assert_yaml_snapshot!(result);
}
```

`insta::assert_yaml_snapshot!` 是 Rust snapshot 测试的事实标准。第一次跑生成 `.snap` 文件(内容是 perception 结果的 YAML 序列化),之后每次跑对比——柱子位置改了、LOS 算法改了,这个 test 就 fail,迫使你 review 改动是否预期。这就是 [09A-3 snapshot testing AI] 的核心思路:**对 AI 的决定性部分,snapshot 测试是把"我以为这次改动没影响 X"这个假设强制验证一遍的最便宜手段**。

property test 适合 perception 这种纯函数的"边界情况"探测:

```rust
use proptest::prelude::*;

proptest! {
    #[test]
    fn los_symmetric(pos1 in any::<[f32; 2]>(), pos2 in any::<[f32; 2]>()) {
        let p1 = Vec2::from_array(pos1);
        let p2 = Vec2::from_array(pos2);
        let world = World几何::empty();
        // 视线是对称的:A 看得见 B,B 就看得见 A。
        // 这是个"不变量",property test 自动枚举输入验证它。
        prop_assert_eq!(compute_los(p1, p2, &[], &world).visible,
                        compute_los(p2, p1, &[], &world).visible);
    }
}
```

property test 帮你发现"LOS 在某个奇怪角度下不对称"这种边界 bug,这种 bug 手写单元测试永远覆盖不全。

涌现部分(behavioral)就难了——"50 个 NPC 一起追玩家时,有没有 NPC 卡墙"这种问题没法 snapshot。这里可行的策略是**统计性断言**:

```rust
// 跑 100 次"50 NPC 围攻玩家 60 秒"的场景,统计每个 NPC 的"卡墙时间"。
// 断言:没有任何 NPC 卡墙超过总时长的 5%。
#[test]
fn stress_no_npc_gets_stuck() {
    let mut max_stuck_ratio = 0.0;
    for seed in 0..100 {
        let mut sim = Simulation::with_seed(seed);
        sim.spawn_npcs(50);
        sim.run_seconds(60.0);
        for npc in sim.npcs() {
            let stuck = npc.stuck_time / 60.0;
            max_stuck_ratio = max_stuck_ratio.max(stuck);
        }
    }
    assert!(max_stuck_ratio < 0.05,
            "some NPC was stuck {:.0}% of the time", max_stuck_ratio * 100.0);
}
```

这种测试不告诉你"哪个 NPC 在哪一帧卡了",但它告诉你"我有没有把卡墙 regression 引进来"。配合第三节的录制系统,测试一旦 fail,你可以从那个 seed 重放整个 simulation,用 debug 可视化逐帧看 NPC 在哪里卡住。**测试 = 自动哨兵,录制 = 案发现场重放,可视化 = 显微镜**——三者配合才是完整的 AI 测试方案。

最后一句告诫:**不要试图 snapshot 测整个行为树 tick 的输出**。BT 输出是非决定性的(running state、随机扰动、计时器),snapshot 整个输出会得到 flaky test。只 snapshot 那些 pure function 的输出(perception query、utility score 计算、navmesh path generation 给定输入),把 BT 当 black box 用 behavioral test 盖住。这两层分开,你的 AI 测试套件才能既敏感又稳定。

## 7 · 在你 HH 项目里动手(做中学红线)

这一节是这一篇的"实战作业",按顺序做完它,你就能在自己的项目里把"猜 AI bug"切换成"看见、回放、热调 AI"。

**第 1 步:搭一个最小的 AI debug overlay**。复用 [`debug-overlay-design`](./debug-overlay-design.md) 那一套 `DrawLayer`,实现本篇第 2 节的 `AiDebugView` 和 `draw_npc_debug`。先做三个开关:`ai_debug.fov`(FOV 扇形 + can_see_target 染色)、`ai_debug.path`(navmesh 路径折线)、`ai_debug.bt`(当前行为树节点文字)。这三个开关足够让你看见 80% 的 AI bug。alertness bar 和 LKP 标记可以稍后加。

**第 2 步:把 AI 决策录下来**。实现本篇第 3 节的 `AiRecorder`。每帧每个 NPC 录一条 `AiFrameSnap`(只录 `decision != None` 的帧,节省内存),默认 ring buffer 60 秒。在 console 加一个命令 `ai_decisions <npc_id>`,打印该 NPC 最近 60 秒的所有决策序列——这就是你"找五秒前凶手"的工具。

**第 3 步:把所有 AI 参数 CVar 化**。挑一个 archetype(比如 guard),按本篇第 4 节的 `AiParams::register` 把它的 8 个参数全部注册成 CVar,带 min/max clamp。然后实际玩 30 分钟,只用 console 调参,把怪物手感磨到你满意,期间不重新编译一次。最后 `cvar_save ai_guard.cfg`,把这些值固化。

**第 4 步:加一个最简 DDA**。按本篇第 5 节的 `compute_dda`,只监控 `recent_death_rate` 一个输入,只调 `ai_accuracy` 和 `ammo_drops` 两个输出,窗口 60 秒,曲线用 smoothstep。跑两局:一局故意死 5 次(验证 AI 变菜、弹药变多),一局全程无伤(验证 DDA 不动作,没把难度莫名提高)。**验证 DDA 在大多数情况下不动作**——这是它"不被察觉"的前提。

**第 5 步:为 perception 写一个 snapshot test**。挑一个有遮挡的关卡 fixture,实现本篇第 6 节的 `snapshot_guard_los_to_player_through_pillar`,跑 `cargo insta review` 接受初始 snapshot。然后故意改一下 LOS 算法(比如把遮挡多边形的某个顶点偏移 1 单位),看 test 是否 fail——这验证 snapshot 真的能抓 regression。

做完这五步,你的 AI 工具链就完整了:**可视化(看)、录制(回)、CVar(调)、DDA(自适应)、测试(防回归)**。对比之前"只盯屏幕猜"的状态,你会发现 AI 开发的体感完全不一样——你不再害怕改 perception 算法,因为你有 overlay 和 snapshot 兜底;你不再害怕调参数,因为 CVar 让你 10 秒一迭代;你不再害怕"QA 报了一个不知道怎么复现的 bug",因为录制给你现场。

## 8 · 练习

**Lv1(基础)**。给 `AiDebugView` 加一个新开关 `ai_debug.formation`,在 [group-and-squad-ai](./group-and-squad-ai.md) 讲的小队阵型上画一个方框,显示每个 squad member 的目标 slot 位置。颜色用 alpha 0.5,不要挡游戏画面。

**Lv2(进阶)**。把 `AiRecorder` 改成 mmap 文件版本——录制时不写内存 ring buffer,直接 mmap 一个文件,把 `AiFrameSnap` 顺序写进去。这样录制可以无限长(60 分钟也不撑爆内存),且崩溃后文件还在,你可以离线分析。注意对齐和 padding——`AiFrameSnap` 的大小要是 8 的倍数,方便 mmap。

**Lv3(高级)**。实现一个"AI 离线回放器"——独立于游戏运行的工具,读取 mmap 录制文件,把 NPC 在每一帧的位置、FOV、决策渲染到一个 2D 俯视图上。可以暂停、单帧 step、按 NPC id 过滤、按 decision 类型过滤。这是把第 2 节可视化和第 3 节录制合起来的"AI 时间机器"——你拿到 QA 的录制文件,在这个工具里逐帧找凶手。

**Lv4(研究)**。研究 Resident Evil 4 的 DDA 公开资料(Scurrilous 的 GDC 演讲、mod 社区逆向出的参数表),在你 HH 项目里实现一个"RE4 风格"的隐藏 DDA——监控玩家受击率、弹药存量、爆头率,用 smoothstep + 长滑动窗口调整 AI 准度、敌人血量、掉落。找三个朋友盲测:看他们能不能在不知道有 DDA 的情况下感觉到难度被调整过。这个练习会让你真正理解"DDA 要不被察觉"有多难。

## 9 · 延伸阅读

- [debug-overlay-design](./debug-overlay-design.md)——本篇第 2 节可视化的渲染基础设施(Day 176-234 那套 overlay 管线)。
- [09B-4 CVars for live AI tuning]——本篇第 4 节 CVar 系统的完整规范,含持久化、命名空间、designer workflow。
- [09A-3 Snapshot testing AI]——本篇第 6 节 snapshot 测试的方法论。
- [09A-4 determinism-and-replay](../../phase-8/deep-dives/determinism-and-replay.md)——本篇第 3 节完整 replay 的决定性基础,跨平台 IEEE 754、PCG RNG。
- [09D Debug viz]——AI 可视化的通用规范,本篇第 2 节是其 AI 子集。
- [ai-patterns](../../phase-2/deep-dives/ai-patterns.md)——决策架构(FSM / HFSM / BT / Utility / GOAP / HTN),本篇假设你已读完。
- [ai-perception-and-memory](./ai-perception-and-memory.md)——感知与记忆系统,本篇可视化的"被画对象"。
- [navmesh-and-pathfinding](../../phase-7/deep-dives/navmesh-and-pathfinding.md)——移动与寻路,本篇录制系统帮你定位的常见 bug 源。
- [group-and-squad-ai](./group-and-squad-ai.md)——小队协作,Lv1 练习的画图对象。
- Casey HH AI debug 相关 Day:Day 196(immediate-mode UI 集成)、Day 219(debug hierarchy 树形展示)——是 AI overlay 落地的基建。
- GDC 演讲 "Dynamic Difficulty Adjustment in Resident Evil 4"——DDA 隐藏调整的经典案例分析。
- GDC Vault: "The Illusion of Intelligence: AI in F.E.A.R."——讲 AI 工具链如何支撑 GOAP 调试,值得对照本篇第 3 节读。
- `insta` crate(Rust snapshot testing):https://insta.rs/
- `proptest` crate(Rust property testing):https://altsysrq.github.io/proptest-book/

## 10 · T6 游戏 AI 深度序列收口

这一篇是 T6 游戏 AI 深度序列的最后一篇,值得停下来回望整个序列搭起来的东西。

序列的第一篇是 [`ai-patterns`](../../phase-2/deep-dives/ai-patterns.md),讲**决策架构**:从最朴素的 FSM,到分层的 HFSM,到工业级的 Behavior Tree、Utility AI,再到规划的 GOAP 和 HTN。那一篇回答的是"AI 用什么结构做决定"。

第二篇是 [`navmesh-and-pathfinding`](../../phase-7/deep-dives/navmesh-and-pathfinding.md),讲**移动**:从 grid A* 到 Recast/Detour 的 NavMesh,从 Funnel Algorithm 到 RVO 避障。那一篇回答的是"AI 决定去哪里之后,怎么走过去"。

第三篇是 [`ai-perception-and-memory`](./ai-perception-and-memory.md),讲**感知与记忆**:视野扇形、听觉范围、LOS 查询、last-known-position 记忆、alertness 衰减。那一篇回答的是"AI 怎么知道世界发生了什么"。

第四篇是 [`group-and-squad-ai`](./group-and-squad-ai.md),讲**协作**:formation 阵型、squad coordination、呼叫增援、shared perception。那一篇回答的是"多个 AI 怎么协同"。

第五篇,也就是这一篇,讲**developability**:可视化让 AI 状态看得见,录制让历史回得去,CVar 让参数热调得动,DDA 让难度自适配玩家,测试让 regression 防得住。这一篇回答的是"AI 造出来之后,怎么把它开发、调试、调优、发布出去"。

把这五篇拼起来,你就有了游戏 AI 工程的完整闭环:**会决定、会移动、会感知、会协作、能被开发调试调优**。这就是 game AI engineering 的全貌。任何一个 AAA 工作室的 AI team,不管用什么引擎什么语言,本质上都在做这五件事——区别只在每一件事的深度和工具链的成熟度。

游戏 AI 的一个深层真相,值得在序列结尾点出来:**真正"好玩"的 AI,不是最聪明的 AI,而是最被精心调过的 AI**。F.E.A.R. 的 Replica Soldier 之所以让人记得,不是因为它真的"聪明"——它的 GOAP 在现代标准下并不复杂——而是因为它的每个参数(perception range、reaction time、cover preference、flanking likelihood)都被设计师用工具链反复调过,让它的行为看起来"刚刚好地聪明"。Halo 的 Covenant 之所以经典,也不是因为算法多高级,而是因为 Bungie 的 AI team 有最好的 debug overlay 和录制回放工具,能把 emergent 行为的每一个边界都打磨过。

**AI 的好坏,80% 取决于工具链,20% 取决于算法**。一个有完整可视化 + 录制 + CVar + 测试的项目,用最简单的 FSM 也能调出比"用 GOAP 但没有调试工具"的项目好十倍的 AI 体验。这就是这一篇,也是整个 T6 序列,最想留给你的判断:**先把工具链造好,再考虑用更高级的算法**。Handmade Hero 里 Casey 用 FSM 实现 AI,但他花了远超 FSM 本身的精力造 debug overlay——他知道工具链是 multiplier,算法是 base,没有 multiplier 的 base 永远调不出手感。

读完这一篇,你的 HH 项目应该有了一套不输 AAA 工作室的 AI 工具链雏形。后面 Phase 6(渲染)、Phase 7(工具)、Phase 8(发布)会继续扩展这套工具链,但 AI 这一块,你已经有完整的闭环了。下一个序列见。
