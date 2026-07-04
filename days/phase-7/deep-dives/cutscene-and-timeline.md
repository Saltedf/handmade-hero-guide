
# 过场与时间轴:Sequencer 系统

> 你的游戏玩法很棒。每一秒玩家都被你的手感牢牢抓住——跳跃弧线漂亮、命中反馈扎实、相机跟随流畅。但你想要一个**时刻**——主角推开酒馆大门,镜头缓缓上抬,反派坐在阴影里转过头,灯光打在他脸上,他开口:"你来晚了。"配乐在 2.4 秒后渐入,字幕同步出现,3.8 秒处门"砰"地被风吹开,4.5 秒主角的拳头攥紧。这不是玩法,这是**戏剧**(spectacle)——一段被精心编排的、动画 / 相机 / 音频 / 事件在精确时间点上协同播放的脚本序列。如果用 ad-hoc 代码写,你会得到一坨 `if elapsed > 2.4 { play_music() }`、`if elapsed > 3.8 { door.open() }`、`if elapsed > 4.5 { fist.clench() }` 散落在 update 函数里——加到第 20 个时间点时已经无法维护,改一个数字会破坏别处。专业工具是 **timeline / sequencer(时间轴 / 序列器)**:把整段 cinematic 当作**数据**——一个有总时长的容器,里面并排跑多条**轨道(track)**,每条轨道在不同时间点上有**关键帧(keyframe)**,所有轨道共享同一个**主时钟(master clock)**。这一篇我们从零写一个 mini timeline 系统,涵盖相机轨(走 spline-math 路径)、动画轨(播 clip)、音频轨(放对白 / 音乐)、事件轨(定时往事件总线发信号),并把它做成数据驱动的——设计师写一份 TOML/JSON 描述,运行时播放。这就是 Unreal Sequencer、Unity Timeline、Godot AnimationPlayer 背后的通用骨架。

## 0 · 一段用 if-else 拼出来的过场,你会写出什么

先建立痛点直觉。你接到一个需求:开场 10 秒的 cinematic。需求单写着——"0 秒开始,镜头从城门口飞向酒馆;2 秒,酒馆门被推开吱呀一声;3 秒,反派转过头说台词;3.5 秒,主题音乐渐入;5 秒,主角握紧拳头;7 秒,镜头推近到反派脸部特写;9.5 秒,淡出黑屏;10 秒,结束,把控制权交还玩家。"

你最初的实现大概是这样:

```rust
// src/game/intro_cinematic.rs
struct IntroCinematic {
    elapsed: f32,
    door_opened: bool,
    villain_turned: bool,
    music_started: bool,
    fist_clenched: bool,
    // ... 还有 6 个 bool
}

impl IntroCinematic {
    fn update(&mut self, dt: f32, world: &mut World) -> bool {
        self.elapsed += dt;
        if self.elapsed >= 2.0 && !self.door_opened {
            world.doors["tavern"].open();
            world.audio.play_sfx("door_creak");
            self.door_opened = true;
        }
        if self.elapsed >= 3.0 && !self.villain_turned {
            world.villain.anim.play("turn_head");
            world.audio.play_vo("villain_line_01");
            self.villain_turned = true;
        }
        if self.elapsed >= 3.5 && !self.music_started {
            world.audio.play_music("theme", fade_in: 1.5);
            self.music_started = true;
        }
        if self.elapsed >= 5.0 && !self.fist_clenched {
            world.hero.anim.play("clench_fist");
            self.fist_clenched = true;
        }
        // ... 还有十几行类似
        if self.elapsed >= 7.0 {
            // 镜头推近——但怎么从当前位置平滑过渡到特写?
            // 用 lerp?那 5 秒到 7 秒之间镜头在哪?
        }
        self.elapsed < 10.0
    }
}
```

跑起来你能感觉到三个根本问题。**第一,镜头没法平滑**——你想让镜头从 0 秒到 7 秒连续地飞过 5 个机位,但用 if-else 写只能是"在某时刻跳到某位置",平滑要么靠 lerp 凑(每段都要手算起止),要么靠样条(但你没把样条接进来)。**第二,改一个时间全乱**——导演说"反派转头从 3 秒改成 2.8 秒",你改完发现 2.8 秒时对白还没准备好(对白 2.5 秒触发),出现"先转头后开口"的逻辑错乱;你以为改一个数字很简单,但时间点是**相互关联**的,改一个就要重新检查所有。**第三,序列化噩梦**——这段 cinematic 完全写在代码里。美术想改"门推开的角度"、"音乐渐入时长"、"镜头推近速度",都要找程序员改代码、提交、编译、重启。一个 30 秒过场,美术和程序来回 50 次沟通。

这三个问题的共同根源:**你把"过场的编排"硬编码在"游戏逻辑"里了**。过场本质上是一份**数据**——一份描述"什么时候发生什么"的脚本。把它从代码里抽出来,变成可读、可编辑、可序列化的**时间轴数据**,所有问题就消失了。这就是 sequencer 的本质:让 cinematic 成为数据,让设计师像写乐谱一样编排过场。

## 1 · 过场是一个状态:从游戏状态栈的角度看

在动手写 timeline 之前,先回答一个更基础的问题:**过场在游戏架构里是什么?** 答案是——它是一个**游戏状态(game state)**。这一节直接接上 [game-state-management](../../phase-2/deep-dives/game-state-management.md) 的状态栈模型。

回顾一下:你的游戏有一组状态(MainMenu、Playing、Paused、GameOver),状态以栈的方式组织,新状态 push 上去盖住旧状态,pop 回到下层。过场在这个模型里是一个**特殊状态**——它把玩家的控制权接管过来,自己播放一段脚本,播完再交还控制权。从玩家视角,过场就是"游戏突然不让我操作了,屏幕上放了一段电影,然后我又能操作了"。

但过场状态和"暂停"状态不一样的地方在于,**它不是把整个世界冻结**。相反,过场状态下世界仍在跑——NPC 动画在播、音频在响、粒子在飞,只是**控制来源变了**:从"玩家输入驱动"切到"timeline 数据驱动"。这就是为什么过场状态需要做两件事:**限制 / 暂停玩家控制**,同时**让 cinematic 子系统接管**。

具体来说,过场状态进入时要做的事:

- 把玩家输入系统挂起(或限制——比如过场里允许按 ESC 跳过,但不允许移动)。
- 把 AI 系统挂起(NPC 不要自己乱动,由 timeline 接管它们的行为)。
- 把游戏物理可选地暂停(过场里通常物理还在跑,但玩家不参与;或者改成"kinematic"模式让物体按脚本移动)。
- 启动 cinematic 子系统:相机切到 timeline 控制的相机、音频系统准备对白和音乐、动画系统切换到"由 clip 直驱"模式。
- 启动主时钟,timeline 开始前进。

过场状态退出时做的事:

- 主时钟停在结尾,把所有轨道的"最终状态"提交给游戏世界(角色停在某姿势、相机停在某机位、音频停在某音量)。
- 把控制权交还给原状态(通常是 Playing):玩家输入重新启用、AI 重新启用、相机切回玩家相机(可以带一个 cross-fade 平滑过渡,避免突然跳切)。
- 触发过场后的 gameplay 事件(比如"过场结束 → 触发 boss 战"——这就是事件轨最后一帧的副作用)。

这里有一个**关键的架构决策**:过场状态 push 在栈顶,还是 in-place 替换?两种做法都存在。**Push 模式**:过场作为独立状态压栈,下层的 Playing 状态保留但被遮蔽。优点是退出时自动恢复,语义干净;缺点是 Playing 状态在过场期间仍可能被部分更新(取决于状态机实现),需要小心"挂起"的边界。**In-place 模式**:把 Playing 状态切到 Cinematic 状态,完全替换。优点是实现简单,缺点是恢复时要手动保存 / 还原游戏上下文。Unreal 的 Level Blueprint 触发的 cinematic 用的是 in-place(通过 `PlayerController::SetCinematicMode`),Unity 的 Timeline Playable Director 配合 Playable Graph 接管,本质也是 in-place。在我们的 mini 系统里,用 push 模式更符合 [game-state-management](../../phase-2/deep-dives/game-state-management.md) 的栈抽象。

还有一个细节:**部分过场(ambient cinematic)**。不是所有过场都完全夺走控制——有些游戏(《半条命》系列)的过场是"玩家仍能走动,但房间里的 NPC 在演剧情"。这种叫 **in-game cinematic** 或 **scripted sequence**,它不切状态,只是在 Playing 状态里启动一个 timeline,timeline 只驱动 NPC 动画 / 对白 / 事件,**不接管相机**。我们的 timeline 系统要支持这两种模式——通过"哪些轨道是 active"来区分:全 cinematic 模式相机轨也 active,in-game 模式只有动画 / 音频 / 事件轨 active。这就是为什么 timeline 是一个**通用机制**,而 cinematic 只是它的一个用法。

## 2 · 时间轴的核心模型:轨道 + 关键帧 + 主时钟

现在进入正题——timeline 的核心数据模型。这一节的思路是:把一段过场抽象成一个数学对象,这个对象在每一帧能"求值"出当前世界应该处于的状态。

### 2.1 一段过场 = 一个有总时长的容器

一段 timeline 首先有一个**总时长(duration)**——10 秒、30 秒、2 分钟。在总时长内,时间从 0 单调前进到 duration(也允许暂停、回放、跳转,见 §7)。这个**当前时间(current time)**叫**主时钟(master clock)**,所有内容都以它为参考。

```rust
// src/cinematic/timeline.rs
#[derive(Clone, Debug)]
pub struct Timeline {
    pub duration: f32,
    pub tracks: Vec<Track>,
}
```

就这么简单。Timeline 是一个 duration 加一组 tracks。注意 duration 不是从 tracks 推出来的——它是显式声明的。即使所有 track 在 8 秒就结束,timeline 也可以声明 duration = 10 秒,最后 2 秒是"留白"(可能用来给玩家反应时间,或为下一段过场铺垫)。

### 2.2 轨道:并行的内容流

一条 **track(轨道)** 是一条**在时间轴上并行展开的内容流**。一个 timeline 里通常有多条轨道:

- **相机轨(camera track)**:控制相机位置和朝向,通常是一条沿 spline-math 路径的运动。
- **动画轨(animation track)**:控制某个角色的骨骼动画——"在 t=2.0 切到 walk clip,t=4.5 切到 idle clip"。
- **音频轨(audio track)**:播放对白(VO)、音乐(BGM)、音效(SFX)——"在 t=3.5 开始播 theme 音乐,渐入 1.5 秒"。
- **事件轨(event track)**:在精确时间点触发任意 gameplay 事件——"t=2.0 门推开"、"t=8.0 任务标志置为 boss_triggered"。
- **附加轨**:粒子轨(控制粒子特效启停)、光照轨(动态改变场景光照——"打追光灯")、UI 轨(显示 / 隐藏字幕、淡入淡出)。

每条 track 是一个**自包含的求值器**——给它当前主时钟的时间,它输出"我现在应该让世界处于什么状态"。tracks 之间**互不直接通信**,它们都只读主时钟、各自独立地驱动世界的一部分。这种解耦是 timeline 可扩展性的根源:加一条新 track(比如"物理冲量轨",在过场里给物体施加冲量)不需要改老 tracks。

```rust
// src/cinematic/track.rs
use crate::cinematic::context::CinematicContext;

#[derive(Clone, Debug)]
pub enum Track {
    Camera(CameraTrack),
    Animation(AnimationTrack),
    Audio(AudioTrack),
    Event(EventTrack),
}

impl Track {
    /// 每帧由 timeline 调用:t 是主时钟当前时间
    pub fn sample(&self, t: f32, ctx: &mut CinematicContext) {
        match self {
            Track::Camera(c) => c.sample(t, ctx),
            Track::Animation(a) => a.sample(t, ctx),
            Track::Audio(au) => au.sample(t, ctx),
            Track::Event(e) => e.sample(t, ctx),
        }
    }
}
```

`CinematicContext` 是 timeline 拿到的世界句柄——它能写相机、播音频、改角色动画、发事件。所有 track 通过这个 context 影响世界。

### 2.3 关键帧:轨道上的离散值

每条 track 由若干 **keyframe(关键帧)** 定义。一个 keyframe 是"**在时间 t 处,这条 track 应该具有的值**"。track 的 `sample` 函数做的事就是:给定当前主时钟 t,在 keyframes 里找到 t 所在的区间,**在两个相邻 keyframe 之间插值**(或刚好命中 keyframe 时直接返回)。

不同类型的 track,keyframe 的"值"含义不同:

- 相机轨:keyframe 的值是"机位"——一组 (position, look_at)。两个 keyframe 之间用 Catmull-Rom(见 [spline-math](../../phase-3/deep-dives/spline-math.md))平滑插值。
- 动画轨:keyframe 的值是"播放哪个 clip"。两个 keyframe 之间是"持续播这个 clip",切换 keyframe 时启动 cross-fade(见 [animation-blending-and-state-machine](../../phase-3/deep-dives/animation-blending-and-state-machine.md))。
- 音频轨:keyframe 的值是"启动哪个音频源,带什么参数(音量 / 渐入)"。音频 keyframe 通常是**一次性触发**——到了就播,不插值。
- 事件轨:keyframe 的值是"触发哪个事件,带什么 payload"。事件 keyframe 也是**一次性触发**。

注意一个微妙区别:**连续型 track**(相机、动画)的 keyframe 之间需要插值,track 在每个时间点都有一个值;**触发型 track**(音频、事件)的 keyframe 是离散时间点上的"动作",track 在两个 keyframe 之间是"空"的,只在命中 keyframe 那一刻做事。这个区别决定了 sample 函数的两种不同语义——**连续型是"读出当前值",触发型是"执行未执行的动作"**。下面两小节分别展开。

### 2.4 连续型采样:keyframe 之间的插值

以相机轨为例。给定 keyframes 列表 `[(0.0, frame_a), (3.0, frame_b), (7.0, frame_c)]`,当前时间 t=5.0,我们要算出当前的相机机位。流程:

1. 找到 t 所在的区间——5.0 落在 3.0 和 7.0 之间。
2. 计算局部 alpha = (5.0 - 3.0) / (7.0 - 3.0) = 0.5。
3. 在 frame_b 和 frame_c 之间按 alpha 插值。

但"在两个机位之间插值"不是简单的 lerp——那是 spline-math 里 §0 那个学生错误的开始。正确做法是把所有 keyframe 的 position 串成一条 Catmull-Rom 路径,所有 keyframe 的 look_at 也串成一条,然后用**弧长参数化**保证相机匀速。这就是为什么 [spline-math](../../phase-3/deep-dives/spline-math.md) 是本篇的前置——你直接复用那篇的 `CatmullRomPath` 就能拿到一个"穿过所有 keyframe 机位、整体平滑、匀速"的相机运动。

但这里有一个时间映射的小坑:keyframe 的时间戳不一定是匀分布的——`[0, 3, 7]` 这个序列,从 0 到 3 跨 3 秒,从 3 到 7 跨 4 秒。如果直接用主时钟 t 作为样条的全局参数 u,样条会"按 t 匀速走"——但样条的弧长在每个区间不同(3 秒那段可能弧长 10 米,4 秒那段可能弧长 8 米),导致相机的**空间速度**忽快忽慢。解决办法是给每个 keyframe 加一个**期望空间速度**或在 spline-math 的 `CatmullRomPath` 上做时间重映射——主时钟 t → 弧长 s → 样条位置。这一步在你的实现里会自然遇到,我们 §8 会展开。

### 2.5 触发型采样:未执行动作的扫描

以事件轨为例。给定 keyframes `[(2.0, "open_door"), (3.8, "wind_gust"), (5.0, "clench_fist")]`,每帧 sample(t) 时我们要做的是:**找出所有 time <= t 且"还没执行过"的 keyframe,执行它们,标记为已执行**。

```rust
// src/cinematic/event_track.rs
#[derive(Clone, Debug)]
pub struct EventKeyframe {
    pub time: f32,
    pub event_id: String,        // 走事件总线
    pub payload: serde_json::Value,
    pub fired: bool,             // 运行时状态:这一帧是否已触发
}

#[derive(Clone, Debug, Default)]
pub struct EventTrack {
    pub keyframes: Vec<EventKeyframe>,
}

impl EventTrack {
    pub fn sample(&mut self, t: f32, ctx: &mut CinematicContext) {
        for kf in &mut self.keyframes {
            if !kf.fired && kf.time <= t {
                ctx.event_bus.dispatch(&kf.event_id, kf.payload.clone());
                kf.fired = true;
            }
        }
    }
}
```

这里有几个**关键设计点**。第一,`fired` 是运行时状态,不是数据——序列化到磁盘时它是 false,加载后第一次播放时按时间推进逐个触发。第二,**正常播放**和**跳转 / 回退**的处理不一样。正常播放时,t 单调递增,逐个触发未触发的 keyframe 没问题。但跳转(比如玩家按 ESC 跳过,见 §7)时,t 从 2.0 一下跳到 10.0,中间 3.8 秒和 5.0 秒的事件**应该被触发吗**?这是个产品决策——通常跳过时,中间事件**全部触发**(因为它们可能是"任务标志置位"这种影响后续 gameplay 的关键事件),只是不再播中间的动画 / 音频。第三,**回退**(timeline 倒放,debug 用)时,`fired` 状态需要重置——已经触发的事件无法"撤销",所以回退一般不支持事件轨,只支持连续型 track。

### 2.6 主时钟:唯一的真理之源

整个 timeline 的核心是那个**主时钟**。所有 track 都读它,所有插值都以它为参考。主时钟的实现极简:

```rust
pub struct TimelinePlayer {
    pub timeline: Timeline,
    pub clock: f32,             // 主时钟
    pub playing: bool,          // 暂停 / 播放
    pub speed: f32,             // 播放速率(支持慢动作过场)
}

impl TimelinePlayer {
    pub fn update(&mut self, dt: f32, ctx: &mut CinematicContext) -> bool {
        if self.playing {
            self.clock += dt * self.speed;
        }
        if self.clock >= self.timeline.duration {
            self.clock = self.timeline.duration;
            // 最后一帧 sample 让所有 track 到达终态
            self.sample_all(ctx);
            return false; // 播完
        }
        self.sample_all(ctx);
        true
    }

    fn sample_all(&mut self, ctx: &mut CinematicContext) {
        let t = self.clock;
        for track in &mut self.timeline.tracks {
            // 注意:事件轨需要 &mut self(改 fired),所以这里要小心借用
            track.sample(t, ctx);
        }
    }
}
```

**借用检查坑**:Rust 里 `timeline.tracks` 和 `ctx` 在同一函数里都要可变借用,但它们是不同对象,所以没问题。但 event track 的 `sample` 既要改自己的 `fired`(需要 `&mut EventTrack`)又要 dispatch 到 event bus(需要 `&mut CinematicContext`),这一步在 trait 设计上要把"track 自己的状态"和"context 状态"分开,我们 §3 会看到完整的接口。

## 3 · 四种 track 的完整实现

这一节给出四条核心 track 的 Rust 实现,每条都接上对应子系统。

### 3.1 CinematicContext:track 看到的世界

先把"track 能影响世界"的接口钉死。track 不直接持有 world 引用,而是通过一个 context 抽象——这样 timeline 可以在不同 host 里复用(过场、菜单背景动画、tutorial 提示都用同一套)。

```rust
// src/cinematic/context.rs
use crate::{audio::AudioSystem, render::Camera, event_bus::EventBus};

pub struct CinematicContext<'a> {
    pub camera: &'a mut Camera,
    pub audio: &'a mut AudioSystem,
    pub event_bus: &'a mut EventBus,
    pub anim_override: &'a mut AnimOverrideSystem,  // 直接给角色喂 pose
}
```

`AnimOverrideSystem` 是一个简单的"按实体 ID 覆盖动画"的子系统——timeline 的动画轨直接把某个角色的当前 pose 写进去,跳过正常的 FSM。这是过场里"角色按脚本演"的实现方式——见 [animation-blending-and-state-machine](../../phase-3/deep-dives/animation-blending-and-state-machine.md) §2 里 FSM 的"override"概念,过场就是临时把角色从 FSM 切到 override 模式。

### 3.2 相机轨:Catmull-Rom 路径 + 弧长参数化

相机轨把 keyframe 的机位串成一条 Catmull-Rom 路径,用 [spline-math](../../phase-3/deep-dives/spline-math.md) §8 的 `CatmullRomPath` 做匀速运动。

```rust
// src/cinematic/camera_track.rs
use crate::spline::CatmullRomPath;
use glam::Vec3;

#[derive(Clone, Debug)]
pub struct CameraKeyframe {
    pub time: f32,
    pub position: Vec3,
    pub look_at: Vec3,
    pub fov: f32,           // 可选,允许过场中变焦
}

#[derive(Clone)]
pub struct CameraTrack {
    pub keyframes: Vec<CameraKeyframe>,
    // 预计算的两条路径(位置 + look_at),按 keyframe 时间分布
    path_pos: CatmullRomPath,
    path_look: CatmullRomPath,
    // keyframe 时间戳(供时间→弧长重映射)
    key_times: Vec<f32>,
    key_arc_pos: Vec<f32>,  // 每个 keyframe 在 path_pos 上的累积弧长
    key_arc_look: Vec<f32>,
}

impl CameraTrack {
    pub fn new(keyframes: Vec<CameraKeyframe>) -> Self {
        assert!(keyframes.len() >= 2, "相机轨至少 2 个 keyframe");
        let positions: Vec<Vec3> = keyframes.iter().map(|k| k.position).collect();
        let look_ats: Vec<Vec3> = keyframes.iter().map(|k| k.look_at).collect();
        let path_pos = CatmullRomPath::new(positions);
        let path_look = CatmullRomPath::new(look_ats);
        // 计算每个 keyframe 在 path 上的累积弧长
        // (CatmullRomPath 已有 total_length,这里把每段长度按 keyframe 切分)
        let key_times: Vec<f32> = keyframes.iter().map(|k| k.time).collect();
        let key_arc_pos = compute_cumulative_arc(&path_pos, keyframes.len());
        let key_arc_look = compute_cumulative_arc(&path_look, keyframes.len());
        Self { keyframes, path_pos, path_look, key_times, key_arc_pos, key_arc_look }
    }

    pub fn sample(&self, t: f32, ctx: &mut CinematicContext) {
        // 把主时钟 t 映射到两条路径的弧长 s
        let (s_pos, s_look) = self.map_time_to_arc(t);
        let pos = self.path_pos.sample_at_arc_length(s_pos);
        let look = self.path_look.sample_at_arc_length(s_look);
        ctx.camera.pos = pos;
        ctx.camera.forward = (look - pos).normalize_or_zero();
        // FOV 插值(线性,够用)
        let fov = self.interpolate_scalar(t, |k| k.fov);
        ctx.camera.fov = fov;
    }

    fn map_time_to_arc(&self, t: f32) -> (f32, f32) {
        // 找 t 所在的 keyframe 区间 [i, i+1]
        let i = self.find_segment(t);
        let t0 = self.key_times[i];
        let t1 = self.key_times[i + 1];
        let alpha = if t1 > t0 { (t - t0) / (t1 - t0) } else { 0.0 };
        let s_pos = lerp(self.key_arc_pos[i], self.key_arc_pos[i + 1], alpha);
        let s_look = lerp(self.key_arc_look[i], self.key_arc_look[i + 1], alpha);
        (s_pos, s_look)
    }

    fn find_segment(&self, t: f32) -> usize {
        for i in 0..self.key_times.len() - 1 {
            if self.key_times[i] <= t && t < self.key_times[i + 1] {
                return i;
            }
        }
        self.key_times.len() - 2
    }
}
```

**关键设计**:主时钟 t 通过 keyframe 的时间戳"分段"映射到弧长 s。每个 keyframe 之间的时间区间对应路径的一段弧长——这样**时间均匀推进时,空间速度由 keyframe 间距决定**。如果你想让相机匀速,应该让 keyframe 之间的时间差与它们之间的空间距离成正比。我们的实现里,keyframe 时间是设计师手填的——他们需要凭手感调"3 秒走 10 米、4 秒走 8 米",这就是过场设计的工艺。

### 3.3 动画轨:clip 直驱 + cross-fade

动画轨控制角色"过场里演什么"。每个 keyframe 说"从时间 t 开始,这个角色播 clip X"。两个 keyframe 之间是"持续播当前 clip",切换 keyframe 时启动一次 cross-fade。

```rust
// src/cinematic/animation_track.rs
use crate::animation::{AnimationClip, Pose, cross_fade::CrossFade};

#[derive(Clone)]
pub struct AnimKeyframe {
    pub time: f32,
    pub entity_id: u32,           // 哪个角色
    pub clip: AnimationClip,
    pub fade_duration: f32,       // 切到这个 clip 的 cross-fade 时长
}

#[derive(Clone)]
pub struct AnimationTrack {
    pub keyframes: Vec<AnimKeyframe>,
    // 运行时状态
    current_clip_index: HashMap<u32, usize>,  // 每个角色当前播到第几个 keyframe
    current_time: HashMap<u32, f32>,          // 当前 clip 内的播放时间
    cross_fade: HashMap<u32, Option<CrossFade>>,
    pose_buffer: Pose,
}
```

每帧 sample 时:

1. 检查每个 entity 的当前 keyframe 时间——如果主时钟 t 越过了下一个 keyframe 的时间,启动 cross-fade(从当前 pose 到新 clip 的第 0 帧)。
2. 更新 cross-fade 和当前 clip 的播放时间。
3. 把算出的 pose 写入 `ctx.anim_override`,跳过 FSM。

```rust
impl AnimationTrack {
    pub fn sample(&mut self, t: f32, ctx: &mut CinematicContext) {
        for kf in &self.keyframes {
            let eid = kf.entity_id;
            let cur_idx = self.current_clip_index.get(&eid).copied().unwrap_or(0);
            // 检查是否需要切到下一个 keyframe
            if cur_idx + 1 < self.keyframes_for(eid).len() {
                let next_kf = self.next_keyframe(eid, cur_idx);
                if t >= next_kf.time {
                    let from_pose = self.pose_buffer.clone();
                    let to_clip = &next_kf.clip;
                    let mut to_pose = Pose::with_joint_count(self.pose_buffer.joint_count());
                    to_clip.sample_into(&mut to_pose, 0.0);
                    let cf = CrossFade::new(from_pose, to_pose, next_kf.fade_duration);
                    self.cross_fade.insert(eid, Some(cf));
                    self.current_clip_index.insert(eid, cur_idx + 1);
                    self.current_time.insert(eid, 0.0);
                }
            }
        }
        // 更新每个 entity 的 pose
        for eid in self.current_clip_index.keys() {
            // ... 更新 cross_fade 或直接 sample 当前 clip
            let pose = self.compute_entity_pose(*eid, t);
            ctx.anim_override.set_pose(*eid, pose);
        }
    }
}
```

注意动画轨的 cross-fade 跟 [animation-blending-and-state-machine](../../phase-3/deep-dives/animation-blending-and-state-machine.md) §2.4 里讲的 gameplay cross-fade 是**同一个 CrossFade**——过场和 gameplay 共用底层组件,这是好的复用。区别在于过场里 clip 切换由 timeline 触发,gameplay 里由 FSM transition 触发。

### 3.4 音频轨:对白 / 音乐 / 音效

音频轨在 keyframe 时间点触发音频播放。区别于相机 / 动画的"持续值",音频是"一次性触发"——但触发后音频会持续响(对白 5 秒、音乐 30 秒),所以音频轨本质上是"**在某时刻启动一个持续事件**"。

```rust
// src/cinematic/audio_track.rs
#[derive(Clone, Debug)]
pub struct AudioKeyframe {
    pub time: f32,
    pub source: String,           // 音频文件 ID
    pub kind: AudioKind,          // VO / BGM / SFX
    pub volume: f32,
    pub fade_in: f32,             // 渐入时长(秒)
    pub fade_out: f32,            // 在 keyframe 的 end_time 处渐出
    pub end_time: Option<f32>,    // 音乐 / 环境音有结束时间;对白通常 None(自然播完)
}

#[derive(Clone, Debug, PartialEq)]
pub enum AudioKind { Vo, Bgm, Sfx }

#[derive(Clone, Debug, Default)]
pub struct AudioTrack {
    pub keyframes: Vec<AudioKeyframe>,
    pub started: Vec<bool>,       // 每个 keyframe 是否已触发
    pub active_handles: Vec<(usize, AudioHandle)>,  // (keyframe index, 音频系统返回的句柄)
}
```

每帧 sample:

```rust
impl AudioTrack {
    pub fn sample(&mut self, t: f32, ctx: &mut CinematicContext) {
        // 触发新 keyframe
        for (i, kf) in self.keyframes.iter().enumerate() {
            if !self.started[i] && kf.time <= t {
                let handle = match kf.kind {
                    AudioKind::Vo => ctx.audio.play_vo(&kf.source, kf.volume, kf.fade_in),
                    AudioKind::Bgm => ctx.audio.play_music(&kf.source, kf.volume, kf.fade_in),
                    AudioKind::Sfx => ctx.audio.play_sfx(&kf.source, kf.volume),
                };
                self.active_handles.push((i, handle));
                self.started[i] = true;
            }
        }
        // 检查需要渐出的
        for (i, handle) in self.active_handles.iter_mut() {
            if let Some(end) = self.keyframes[*i].end_time {
                if t >= end && !handle.stopping {
                    ctx.audio.fade_out(handle, self.keyframes[*i].fade_out);
                    handle.stopping = true;
                }
            }
        }
    }
}
```

**关键工程点**:音频轨要和 [adaptive-audio-and-3d](./adaptive-audio-and-3d.md) 紧密配合——过场里的对白是 2D 音频(不基于位置),但音乐可能基于场景情绪动态调整(切换 layer)。在过场期间,通常**屏蔽 adaptive music 系统**——音乐完全由 timeline 控制,避免两层音乐系统打架。过场结束后再恢复 adaptive。

### 3.5 事件轨:与游戏事件总线合一

事件轨是最有意思的一条——它把 timeline 和 gameplay **缝在一起**。每个 keyframe 说"在时间 t,把事件 X 发到事件总线"。事件总线是 [event-systems-and-gameplay-foundations](../../phase-5/deep-dives/event-systems-and-gameplay-foundations.md) 里那个所有 gameplay 系统都在用的同一个 bus。

```rust
// 已经在 §2.5 给出完整实现,这里补充触发逻辑
impl EventTrack {
    pub fn sample(&mut self, t: f32, ctx: &mut CinematicContext) {
        for kf in &mut self.keyframes {
            if !kf.fired && kf.time <= t {
                ctx.event_bus.dispatch(&kf.event_id, kf.payload.clone());
                kf.fired = true;
            }
        }
    }
}
```

**为什么事件轨如此重要**:它让过场能"穿透"到 gameplay——过场不是孤立的"小电影",它能改变游戏状态。典型用法:

- **任务标志**:`t=8.0` 发事件 `quest/tavern_intro/completed`,触发后续任务链。
- **生成物体**:`t=4.2` 发事件 `spawn/explosion`,事件处理器在场景里生成爆炸 prefab。
- **改变环境**:`t=6.0` 发事件 `weather/rain_start`,天气系统开始下雨。
- **触发战斗**:`t=10.0`(过场结束)发事件 `combat/boss_phase_1_start`,BOSS 战开始。

这些事件**走的是和正常 gameplay 完全一样的代码路径**——`quest/tavern_intro/completed` 这个事件无论是过场发的还是玩家完成 NPC 任务触发的,handler 都是一样的。这就是 §0 那个学生犯的错的根源修复——他没有"事件"概念,只能把"门推开"硬编码在 cinematic 代码里,而 timeline 把它变成一个数据驱动的事件,handler 在 gameplay 那边写,过场只是"定时触发"。

事件轨和事件总线的统一,是 sequencer 系统**架构上最重要的设计决策**。它意味着**过场就是 gameplay,只是被时间编排了**。没有"过场代码"和"gameplay 代码"的割裂——过场是一个特殊的 gameplay 状态,它的 update 函数读 timeline 数据。

## 4 · 数据驱动:把过场写成 TOML

到此 timeline 的 runtime 已经齐了。但还有最后一步——把 timeline 数据从代码里**抽出来**,变成可读、可编辑、可序列化的数据。设计师写一份文件,运行时加载播放。这就是 [scripting-and-modding](../../phase-8/deep-dives/scripting-and-modding.md) 里"数据驱动"模式在 cinematic 上的应用——content multiplier 模式:一份 timeline 数据 = 一段过场,100 份 timeline 数据 = 100 段过场,代码不变。

### 4.1 为什么是数据驱动

回忆 §0 那个 if-else 实现的痛苦——美术要改"门推开时间从 2.0 改成 1.8",要找程序员。100 段过场 = 100 个 if-else 函数,改起来是地狱。数据驱动让 timeline 成为**配置文件**:美术在编辑器里改一个数字、保存、热重载、立即看到效果。程序员只维护 runtime 代码,不碰具体过场内容。

这是工业级引擎的核心模式:Unreal 的 Sequencer 存 `.uasset`(Level Sequence 资产),Unity 的 Timeline 存 `.playable`,Godot 的 AnimationPlayer 存 `.tscn` 内嵌或 `.res`。所有这些都是**序列化的 timeline 数据**——track 列表、每个 track 的 keyframe 列表、每个 keyframe 的值。runtime 加载这些资产,实例化成 timeline 对象,播放。

### 4.2 用 TOML/JSON 描述 timeline

下面是一份完整的 10 秒过场 TOML 数据,接的就是我们 §0 那个酒馆开场例子:

```toml
# assets/cinematics/tavern_intro.toml
duration = 10.0

[[tracks.camera]]
keyframes = [
    { time = 0.0,  position = [0, 5, 30],   look_at = [0, 2, 0],    fov = 60 },
    { time = 3.0,  position = [5, 4, 15],   look_at = [2, 2, 0],    fov = 60 },
    { time = 7.0,  position = [3, 3, 5],    look_at = [3, 3, 0],    fov = 50 },
    { time = 10.0, position = [3, 3.2, 3],  look_at = [3, 3.2, 0],  fov = 35 },
]

[[tracks.animation]]
keyframes = [
    { time = 0.0, entity = "hero",   clip = "idle_to_walk", fade = 0.3 },
    { time = 0.0, entity = "villain", clip = "sit_idle",     fade = 0.0 },
    { time = 3.0, entity = "villain", clip = "turn_head",    fade = 0.2 },
    { time = 5.0, entity = "hero",   clip = "clench_fist",  fade = 0.15 },
    { time = 7.0, entity = "villain", clip = "lean_forward", fade = 0.3 },
]

[[tracks.audio]]
keyframes = [
    { time = 2.0,  source = "sfx/door_creak",   kind = "sfx", volume = 0.8, fade_in = 0.0 },
    { time = 3.5,  source = "bgm/theme",        kind = "bgm", volume = 0.7, fade_in = 1.5, end_time = 9.5, fade_out = 1.0 },
    { time = 3.2,  source = "vo/villain_line1", kind = "vo",  volume = 1.0, fade_in = 0.0 },
]

[[tracks.event]]
keyframes = [
    { time = 2.0,  event = "door/open",        payload = { door_id = "tavern", angle = 90 } },
    { time = 6.0,  event = "weather/rain_start", payload = { intensity = 0.4 } },
    { time = 8.0,  event = "lighting/spotlight", payload = { target = "villain", intensity = 1.2 } },
    { time = 10.0, event = "quest/tavern_intro/completed" },
    { time = 10.0, event = "cinematic/end",    payload = { next_state = "Playing" } },
]
```

**这就是过场的"剧本"**。设计师打开这个文件,调数字、加 keyframe、改时间戳——立即生效。程序员不参与。这份文件可以放进版本控制、可以 diff、可以 review、可以热重载。100 段过场就是 100 份这样的文件,runtime 代码一行不变。

### 4.3 加载与反序列化

用 `serde` 把 TOML 反序列化成 §2 的 `Timeline` 结构。这要求 timeline 的所有字段都 derive `Deserialize`。我们用 `serde_json::Value` 作为 event payload 的灵活载体——事件 handler 自己再解析 payload。

```rust
// src/cinematic/loader.rs
use serde::Deserialize;

#[derive(Deserialize)]
struct TimelineFile {
    duration: f32,
    #[serde(default)]
    #[serde(rename = "tracks.camera")]
    camera: Vec<CameraTrackFile>,
    #[serde(default)]
    #[serde(rename = "tracks.animation")]
    animation: Vec<AnimationTrackFile>,
    #[serde(default)]
    #[serde(rename = "tracks.audio")]
    audio: Vec<AudioTrackFile>,
    #[serde(default)]
    #[serde(rename = "tracks.event")]
    event: Vec<EventTrackFile>,
}

// 每个 TrackFile 是反序列化的中间结构,加载后转成 runtime 的 Track
pub fn load_timeline(toml_text: &str, asset_db: &AssetDatabase) -> anyhow::Result<Timeline> {
    let file: TimelineFile = toml::from_str(toml_text)?;
    let mut tracks = Vec::new();
    for ct in file.camera {
        let keyframes: Vec<CameraKeyframe> = ct.keyframes.into_iter().map(|k| CameraKeyframe {
            time: k.time,
            position: Vec3::from(k.position),
            look_at: Vec3::from(k.look_at),
            fov: k.fov.unwrap_or(60.0),
        }).collect();
        tracks.push(Track::Camera(CameraTrack::new(keyframes)));
    }
    for at in file.animation {
        let keyframes: Vec<AnimKeyframe> = at.keyframes.into_iter().map(|k| AnimKeyframe {
            time: k.time,
            entity_id: asset_db.entity_id(&k.entity),
            clip: asset_db.load_clip(&k.clip),
            fade_duration: k.fade,
        }).collect();
        tracks.push(Track::Animation(AnimationTrack::new(keyframes)));
    }
    // ... audio / event 类似
    Ok(Timeline { duration: file.duration, tracks })
}
```

**关键工程点**:`asset_db.load_clip(&k.clip)` 是异步资源加载——过场开始前要 preload 所有引用的 clip / 音频,否则播放时会卡顿。生产实现里,过场有一个 **preload 阶段**(显示 loading 屏幕 / 黑屏),所有资源加载完后才进入播放阶段。我们的 mini 实现里假设同步加载,真实项目用 [asset-pipeline](../../phase-2/deep-dives/asset-pipeline.md) 那套异步流。

### 4.4 编辑器:可视化作者体验

TOML 文件虽然可读,但设计师真正需要的是**可视化编辑器**——一条横向的时间轴,上面是各条 track,track 上是可拖动的 keyframe 块,选中 keyframe 能改它的值。这是 Unreal Sequencer / Unity Timeline 窗口的样子。我们的 mini 系统不做编辑器(那是一个独立的、庞大的 GUI 项目),但 runtime 数据结构的设计要**为编辑器留好接口**——所有字段都是可序列化的、所有 keyframe 都有稳定 ID(用于编辑器的 undo/redo)、track 顺序有意义(编辑器里显示顺序)。

如果你想给 HH 项目做一个最简单的 timeline 编辑器,可以从一个 **imgui 窗口**起步:横向滚动条代表时间,每条 track 一行,每个 keyframe 是一个小方块,拖动方块改时间,双击改值。这是周末项目级别的工程量,但能把你的 timeline 系统从"程序员写 TOML"提升到"设计师拖界面"——一个数量级的生产力提升。

## 5 · 跳过、暂停、分支:线性之外

到此我们有一个能播放的 timeline。但真实过场还有三个**产品级需求**——跳过(玩家按 ESC 跳过)、暂停(系统暂停 / 玩家暂停)、分支(对话中途出选项,玩家选择影响后续)。这一节处理它们。

### 5.1 跳过:jump-to-end 的清理逻辑

玩家按 ESC,过场要立刻跳到结尾,把控制权交还。听起来简单——把 `clock` 设到 `duration`,下一帧 update 自然结束。但坑在于:**跳过时,事件轨的"中间事件"怎么办**?

回忆 §2.5,事件轨的 keyframe 有 `fired` 状态。如果 clock 从 2.0 跳到 10.0,中间 3.8 秒和 5.0 秒的事件——按"正常 sample"逻辑,会全部触发(因为 `kf.time <= t` 全部满足)。**这通常是正确行为**——这些事件可能是"任务标志置位"、"物体生成",跳过过场不应该让玩家错过这些 gameplay 后果。所以**跳过 = 把所有未触发的事件全部触发**,然后结束。

但**音频和动画的中间 keyframe 不应该全部触发**——你不想跳过时把所有对白都放一遍。所以**事件轨在跳过时触发全部,其他轨在跳过时只取最后一个 keyframe 的状态**。这要求每种 track 实现 `jump_to_end` 方法:

```rust
pub trait TrackTrait {
    fn sample(&mut self, t: f32, ctx: &mut CinematicContext);
    fn jump_to_end(&mut self, ctx: &mut CinematicContext);  // 跳过时调用
}

impl TrackTrait for EventTrack {
    fn jump_to_end(&mut self, ctx: &mut CinematicContext) {
        // 全部触发
        for kf in &mut self.keyframes {
            if !kf.fired {
                ctx.event_bus.dispatch(&kf.event_id, kf.payload.clone());
                kf.fired = true;
            }
        }
    }
}

impl TrackTrait for CameraTrack {
    fn jump_to_end(&mut self, ctx: &mut CinematicContext) {
        // 直接取最后一个 keyframe
        let last = self.keyframes.last().unwrap();
        ctx.camera.pos = last.position;
        ctx.camera.forward = (last.look_at - last.position).normalize_or_zero();
        ctx.camera.fov = last.fov;
    }
}
```

跳过流程:

```rust
impl TimelinePlayer {
    pub fn skip(&mut self, ctx: &mut CinematicContext) {
        // 1. 让所有 track 跳到结尾(事件全部触发,其他取终态)
        for track in &mut self.timeline.tracks {
            track.jump_to_end(ctx);
        }
        // 2. 主时钟设到结尾
        self.clock = self.timeline.duration;
        self.playing = false;
        // 3. 下一帧 update 会返回 false,触发状态切换
    }
}
```

**坑**:`jump_to_end` 触发事件时,事件 handler 可能访问世界状态——但世界的某些状态(比如角色位置)还停留在过场中间的位置,handler 可能出错。生产实践:`jump_to_end` 先做"非事件 track 的 jump"(把世界状态推到结尾),**然后**再触发事件。顺序很重要。

### 5.2 暂停:主时钟冻结

暂停最简单——`self.playing = false`,主时钟不再前进。但 sample 仍然每帧调用,让所有 track 在当前时间保持"冻结快照"。这用于:

- **系统暂停**(玩家切到桌面、手柄断线):过场冻结,恢复后继续。
- **玩家主动暂停**(罕见,但有些游戏允许):过场暂停,显示"按 ESC 继续"。
- **debug**:开发者暂停过场逐帧检查。

注意暂停时音频也要暂停——`ctx.audio.pause_all()`,恢复时 `resume_all()`。这是 `CinematicContext` 在暂停模式下的特殊行为,需要在 update 函数里判断 `playing` 标志。

### 5.3 分支:对话选项打断线性 timeline

分支过场是最复杂的情况。经典例子:《质量效应》对话中,玩家选择"威胁 / 劝说 / 攻击",过场根据选择走不同分支。这破坏了 timeline 的"线性"假设——主时钟不再单调前进,而是可能"跳到另一个时间点继续播"。

实现上有两种思路:

**思路 A:多 timeline + 跳转**。把对话拆成多个小 timeline(intro_timeline、threaten_branch、persuade_branch、attack_branch),每个分支是一个独立 timeline。在 intro_timeline 的某 keyframe 发事件 `dialog/choice_prompt`,UI 弹出选项。玩家选择后,触发对应分支 timeline 的播放。每个分支 timeline 自己有 duration 和终态。

**思路 B:单 timeline + 条件 keyframe**。给每个 keyframe 加 `condition` 字段——只有满足条件才触发。timeline 里同时存在多个分支的 keyframe,根据游戏状态选择性地激活。

```toml
[[tracks.event]]
keyframes = [
    { time = 3.0, event = "dialog/choice", payload = { options = ["threaten", "persuade"] } },
    { time = 4.0, event = "branch/threaten/anim",   condition = "choice == threaten" },
    { time = 4.0, event = "branch/persuade/anim",  condition = "choice == persuade" },
]
```

`condition` 在 sample 时求值——`choice` 是一个游戏状态变量,玩家选择后被设置。条件不满足的 keyframe 被跳过(不触发事件,不被 sample)。

**生产实践**:Unreal Sequencer 用的是**思路 A 的变种**——Sequencer 本身是线性的,但通过 Blueprint 在关键帧上触发"分支决策",决策结果跳到不同的 Sequencer 资产。Unity Timeline 类似,通过 Signal Receiver 触发分支。我们的 mini 实现推荐思路 A——多个小 timeline 比一个带条件的复杂 timeline 更易理解和维护。

## 6 · 生产现实:工业级 sequencer 长什么样

我们写的 mini timeline 是 sequencer 的"骨架"——主时钟 + 轨道 + 关键帧 + 事件集成。工业级引擎在这个骨架上加了海量功能,但**核心模式完全一样**。这一节巡礼三大引擎的 sequencer,让你知道你的 mini 系统在工业里对应什么。

**Unreal Engine Sequencer**(UE5):工业级 sequencer 的金标准。一个 Level Sequence 资产里,你可以加任意多条 track——Camera Cuts(相机切换轨,支持多机位剪辑)、Animation(动画轨,直接绑定 Skeletal Mesh)、Audio、Event(通过 Blueprint 触发)、Transform(物体 transform 关键帧)、Material(材质参数关键帧)、Particle、Lighting、等等几十种。Sequencer 的强大在于**它和 Unreal 的每个子系统都有预集成**——你不需要自己写 track 类型,引擎已经为几乎所有可动画属性提供了 track。源码在 `Engine/Source/Runtime/MovieScene/`,核心是 `UMovieSceneScene` 和 `UMovieSceneTrack`。Sequencer 还支持**子序列**(Subsequence,一个序列嵌套另一个,实现"片头 + 主过场 + 片尾"的复用)、**Take Recorder**(在编辑器里录制玩家操作作为过场)、**Cinematic 关卡可见性**(过场里某些物体显示 / 隐藏)。

**Unity Timeline**:同样是 track-based,通过 Playable Director 播放。核心抽象是 `TrackAsset` 和 `PlayableAsset`,所有 track 类型继承自这两个基类。Unity 的特色是 **Playable Graph**——一个比 timeline 更底层的图结构,timeline 编译成 Playable Graph 后由 Playable Graph 求值。这意味着 timeline 和 Animator、Audio 都统一在 Playable 框架下。Timeline 的 track 类型比 Sequencer 少(AnimationTrack、AnimationTrack、SignalTrack 等),但通过 `PlayableAsset` 自定义 track 类型很方便。

**Godot AnimationPlayer**:Godot 的方案略不同。AnimationPlayer 是一个节点,它持有 Animation 资源(里面是 track + keyframe),可以播放、混合、队列。Godot 4 引入 AnimationTree 后,AnimationPlayer 主要用于"过场 / UI 动画",AnimationTree 用于"角色 locomotion"——分工明确。Godot 的 track 概念同样统一——任何属性的 keyframe(位置、旋转、颜色、可见性、调用方法)都是 track。

**关键观察**:三大引擎的 sequencer 在**抽象上完全等价**——都是 timeline + track + keyframe + 事件触发。差别只在"track 类型的丰富度"和"编辑器体验"。你的 mini 系统就是它们的内核——理解了 mini,你看 Sequencer / Timeline / AnimationPlayer 的文档能立刻看懂。

**一个常被忽略的事实**:**即便游戏"没有过场"也用 timeline**。比如:

- **Tutorial 提示**:新手教学"按 W 移动"——一个 3 秒的 timeline,UI 轨显示提示、音频轨播放配音、事件轨在结束触发"标记教学完成"。
- **关卡入场动画**:玩家进入新区域,镜头自动扫一遍场景——一个 timeline,纯相机轨。
- **装备切换动画**:角色从背剑到持剑,1.5 秒的 timeline,动画轨播 clip、音频轨放金属碰撞声、事件轨在结束发"weapon_ready"。
- **死亡 / 复活序列**:角色死亡,2 秒慢动作 timeline(速度 0.3),动画播死亡、音频放哀嚎、事件触发重生。

这些都是 timeline 的应用——任何"有起止时间、多系统协同、可数据驱动编排"的场景,timeline 都是正确工具。这就是为什么 sequencer 是工业引擎的标配,而不是"专门给电影化 3A 游戏的可选模块"。

## 7 · 性能、内存、调试

把 timeline 系统的工程数据列出来,你才能 budget。

### 7.1 性能开销

每帧 timeline update 的开销:

- 主时钟前进:几个 cycle,可忽略。
- 每个 track 的 sample:相机轨 O(K)(K = keyframe 数,通常 5-20),动画轨 O(E × K)(E = 实体数,通常 1-5),音频轨 O(K),事件轨 O(K)。
- 一个 20 keyframe、4 条 track 的过场,每帧总开销约几百次比较 + 几次插值 = 几微秒。**几乎为零**。

**真正的开销在 track 的副作用**:相机更新触发 view matrix 重算、音频触发解码和混音、事件触发 handler(handler 可能很重——比如生成爆炸就是粒子 + 物理 + 音频)。这些开销属于对应的子系统,不属于 timeline 本身。

### 7.2 内存

timeline 数据本身很小:一个 20 keyframe 的过场,4 条 track,序列化后约 5-10 KB。100 段过场 = 1 MB,完全可忽略。重的是**引用的资源**——clip、音频文件、prefab。这些在 preload 阶段加载,timeline 本身只持有引用。

### 7.3 调试叙事:三个典型 bug

**Bug A:过场结束后角色"瞬移"**。过场结束时,角色从 timeline override 切回 FSM,FSM 不知道角色应该是什么姿势——直接从过场最后姿势"啪"地跳到 FSM 当前姿势。**修复**:过场结束前,把过场最后帧的 pose **注入 FSM 作为"当前姿势"**,FSM 从这个姿势开始播——这就是 animation-blending-and-state-machine 那篇 §2.4 的 flowing cross-fade 思路。

**Bug B:事件触发两次**。同一事件 `door/open` 在过场和 gameplay 都被订阅。过场触发时 handler 执行,handler 内部又触发了别的 Gameplay 事件,层层传递,door 被打开了两次(动画重启)。**修复**:事件 handler 要**幂等**——`door.open()` 内部检查 `if !self.is_open { ... }`。这是 [event-systems-and-gameplay-foundations](../../phase-5/deep-dives/event-systems-and-gameplay-foundations.md) 里强调的"事件 handler 应当幂等"原则在过场的体现。

**Bug C:弧长参数化在不同机器上结果不同**。Catmull-Rom 路径的弧长表是预计算的浮点累积,不同机器 / 编译器 / 优化级别下浮点结果微小差异累积,导致相机在 keyframe 之间"略微偏移"。**修复**:预计算在**加载时**做一次(不是每次播放),把弧长表存进 timeline 资产。所有机器用同一份预计算结果。这是工业级 sequencer 的标准做法——预烘焙(baking)。

## 8 · 在你 HH 项目里动手(做中学红线)

把上面所有概念变成可跑的代码。目标:**给 HH 项目装一个最小可用的 timeline 系统,写一份 10 秒过场 TOML,作为过场状态播放**。

### 8.1 第一步:目录结构

在你的 HH 项目 `src/` 下新建 `cinematic/` 子模块:

```
src/cinematic/
  mod.rs            // 重导出
  timeline.rs       // Timeline, TimelinePlayer
  track.rs          // Track enum, TrackTrait
  context.rs        // CinematicContext
  camera_track.rs
  animation_track.rs
  audio_track.rs
  event_track.rs
  loader.rs         // TOML 反序列化
```

复用你已经写好的子系统:`src/spline.rs`([spline-math](../../phase-3/deep-dives/spline-math.md) §8 的 `CatmullRomPath`)、`src/animation/`([animation-blending-and-state-machine](../../phase-3/deep-dives/animation-blending-and-state-machine.md) §2 的 `AnimationClip` / `CrossFade`)、`src/audio.rs`([adaptive-audio-and-3d](./adaptive-audio-and-3d.md) 的 `AudioSystem`)、`src/event_bus.rs`([event-systems-and-gameplay-foundations](../../phase-5/deep-dives/event-systems-and-gameplay-foundations.md) 的事件总线)。

### 8.2 第二步:TimelinePlayer 完整骨架

```rust
// src/cinematic/timeline.rs
use crate::cinematic::{context::CinematicContext, track::Track};

#[derive(Clone)]
pub struct Timeline {
    pub duration: f32,
    pub tracks: Vec<Track>,
}

pub struct TimelinePlayer {
    pub timeline: Timeline,
    pub clock: f32,
    pub playing: bool,
    pub speed: f32,
}

impl TimelinePlayer {
    pub fn new(timeline: Timeline) -> Self {
        Self { timeline, clock: 0.0, playing: true, speed: 1.0 }
    }

    /// 返回 true 表示还在播,false 表示播完
    pub fn update(&mut self, dt: f32, ctx: &mut CinematicContext) -> bool {
        if self.playing {
            self.clock += dt * self.speed;
        }
        if self.clock >= self.timeline.duration {
            self.clock = self.timeline.duration;
        }
        // sample 所有 track
        let t = self.clock;
        for track in &mut self.timeline.tracks {
            track.sample(t, ctx);
        }
        self.clock < self.timeline.duration
    }

    pub fn skip(&mut self, ctx: &mut CinematicContext) {
        // 先让连续型 track 跳到终态
        for track in &mut self.timeline.tracks {
            track.jump_to_end(ctx);
        }
        self.clock = self.timeline.duration;
        self.playing = false;
    }
}
```

### 8.3 第三步:CutsceneState 接到状态栈

接 [game-state-management](../../phase-2/deep-dives/game-state-management.md) 的状态栈:

```rust
// src/game/cutscene_state.rs
use crate::{cinematic::*, states::State, input::Input};

pub struct CutsceneState {
    player: TimelinePlayer,
    ctx_builder: CinematicCtxBuilder,
    skip_requested: bool,
}

impl CutsceneState {
    pub fn new(timeline: Timeline, ctx_builder: CinematicCtxBuilder) -> Self {
        Self {
            player: TimelinePlayer::new(timeline),
            ctx_builder,
            skip_requested: false,
        }
    }
}

impl State for CutsceneState {
    fn update(&mut self, dt: f32, input: &Input, world: &mut World, state_stack: &mut StateStack) {
        if input.just_pressed(Key::Escape) {
            self.skip_requested = true;
        }

        let mut ctx = self.ctx_builder.build(world);
        if self.skip_requested {
            self.player.skip(&mut ctx);
            state_stack.pop();
            return;
        }

        let still_playing = self.player.update(dt, &mut ctx);
        if !still_playing {
            // 过场结束,触发收尾事件(timeline 最后一帧的事件已经发了)
            state_stack.pop();
        }
    }

    fn render(&self, renderer: &mut Renderer) {
        // 过场渲染——通常是游戏世界 + 黑边(letterbox)+ 字幕
        renderer.render_world();
        renderer.draw_letterbox();  // 上下黑边
    }
}
```

### 8.4 第四步:加载 TOML 并启动过场

```rust
// 在某个 gameplay 触发点
fn trigger_tavern_intro(state_stack: &mut StateStack, asset_db: &AssetDatabase) {
    let toml_text = std::fs::read_to_string("assets/cinematics/tavern_intro.toml").unwrap();
    let timeline = cinematic::loader::load_timeline(&toml_text, asset_db).unwrap();
    let ctx_builder = CinematicCtxBuilder::new();
    state_stack.push(Box::new(CutsceneState::new(timeline, ctx_builder)));
}
```

跑起来,你应该看到:进入酒馆时屏幕加黑边,镜头从城门口平滑飞向酒馆(经过 4 个机位,匀速),2 秒门被推开吱呀响,3 秒反派转头说话,3.5 秒音乐渐入,5 秒主角握拳,6 秒开始下雨,8 秒追光灯打在反派脸上,10 秒过场结束黑边消失,控制权交还玩家。**整个过程,你没有写一行 if elapsed > X 的代码**——全由 TOML 数据驱动。

### 8.5 验证清单

- [ ] `cargo build` 无 warning
- [ ] 进入酒馆触发过场,屏幕出现上下黑边
- [ ] 镜头平滑穿过 4 个机位,无急转(肉眼检查)
- [ ] 改 TOML 里某个 keyframe 时间(比如把 villain 转头从 3.0 改 2.5),无需重编译,重启游戏立即生效
- [ ] 按 ESC 过场跳过,中间事件全部触发(用 debug log 验证 `quest/tavern_intro/completed` 被发),控制权立即交还
- [ ] 过场结束后,玩家相机平滑切回(无跳切),游戏可正常操作
- [ ] 100 帧内帧时间稳定在 16.6ms 以下

## 9 · 练习

**Lv1(理解)**:把 `tavern_intro.toml` 里相机的 keyframe 数从 4 个减到 2 个(只保留首尾),观察镜头运动的变化。预期:从直线段变成了平滑曲线,但失去了中间机位的"塑造"。理解为什么多 keyframe 的 Catmull-Rom 比 2 个 keyframe 的 lerp 看起来"更像电影"。

**Lv2(实现)**:给 timeline 加一个 **UI 轨(SubtitleTrack)**——在 keyframe 时间点显示字幕,持续 N 秒后消失。把它接到 §8 的 tavern intro 里,让 villain 的对白同时显示字幕。提示:UI 轨是连续型(每帧 sample 当前应该显示什么字幕),不是触发型。

**Lv3(综合)**:实现 **SubsequenceTrack**(子序列轨)——一个 track 的 keyframe 是"在时间 t 启动另一个 timeline"。这让过场可以嵌套("主过场"里嵌一段"角色特写小过场")。要求:子 timeline 完成后主 timeline 才能 sample 到下一段时间区间。这本质上是 timeline 的递归——你需要管理子 timeline 的 clock 和生命周期。

**Lv4(挑战)**:实现 **分支过场**——在 tavern intro 的 3 秒处插入一个"玩家选择威胁 / 劝说"的对话选项(用 [event-systems-and-gameplay-foundations](../../phase-5/deep-dives/event-systems-and-gameplay-foundations.md) 的事件弹出 UI),玩家选择后过场跳到不同分支 timeline(你写两份不同的 TOML)。处理主时钟的中断与跳转,处理事件轨在跳转时的清理(中间未触发的事件怎么办)。

## 10 · 延伸阅读

本仓库本地资料:[animation-blending-and-state-machine](../../phase-3/deep-dives/animation-blending-and-state-machine.md)(动画轨直接复用 CrossFade 和 AnimationClip)、[spline-math](../../phase-3/deep-dives/spline-math.md)(相机轨的 Catmull-Rom 路径基础)、[adaptive-audio-and-3d](./adaptive-audio-and-3d.md)(音频轨与 adaptive music 的协作)、[game-state-management](../../phase-2/deep-dives/game-state-management.md)(过场作为一个状态)、[event-systems-and-gameplay-foundations](../../phase-5/deep-dives/event-systems-and-gameplay-foundations.md)(事件轨和事件总线的合一)、[camera-systems](../../phase-3/deep-dives/camera-systems.md)(过场相机 vs 玩家相机的切换)、[game-feel-02-camera](../../phase-2/deep-dives/game-feel-02-camera.md)(过场相机的电影感来源)、[scripting-and-modding](../../phase-8/deep-dives/scripting-and-modding.md)(数据驱动过场与 mod 友好性)。

外部稳定 URL:

- Unreal Engine Sequencer 官方文档:https://docs.unrealengine.com/5.0/en-US/unreal-engine-sequencer-movie-tool/
- Unity Timeline 官方文档:https://docs.unity3d.com/Manual/TimelineSection.html
- Godot AnimationPlayer 文档:https://docs.godotengine.org/en/stable/tutorials/animation/index.html
- Unreal Sequencer 源码(需登录):https://github.com/EpicGames/UnrealEngine — `Engine/Source/Runtime/MovieScene/`
- Unity Timeline 源码:https://github.com/Unity-Technologies/com.unity.timeline
- GDC 2017 "Cinematic Design in Gears of War 4":https://www.gdcvault.com/play/1024385/(工业级过场设计工艺)
- GDC 2018 "Technical Art of God of War":https://www.gdcvault.com/play/1025461/(Sequencer 在线性过场与开放世界的混合用法)

---

**总结**:timeline / sequencer 的本质,是把"过场"从**代码**变成**数据**——一份描述"什么时候发生什么"的脚本。它的核心抽象是主时钟 + 多条并行 track + keyframe + 事件集成。这套抽象威力巨大:它不仅驱动电影化过场,还驱动 tutorial、关卡入场、装备切换、死亡序列——任何"有起止时间、多系统协同、可数据驱动编排"的场景。把过场从代码里抽出来,变成设计师可编辑的数据,你的项目就从"程序员的小作坊"迈进了"内容工厂"——这就是工业级游戏引擎的隐形骨架。
