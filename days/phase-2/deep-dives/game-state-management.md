---
phase: 2
title_en: "Game State Management: State Machines & State Stacks"
title_zh: "游戏状态管理:状态机与状态栈,以及为什么 if 旗标必然失败"
type: deep-dive
difficulty: 3
duration: "2-3 小时"
domains: [game, rust, engineering]
prereqs: ["09B-1", "entity-system"]
calibration: "Gregory《Game Engine Architecture》(application layer / state 章)+ Robert Nystrom《Game Programming Patterns》State 章节 + 09B-2 子系统生命周期"
---

# 游戏状态管理 · 状态机与状态栈

## 0 · 你的 HH 游戏只有一种模式,然后你想加一个主菜单

你跟完 HH,游戏只有一个模式:playing。玩家进场,角色能跑能跳能砍,代码清爽,逻辑集中在一个 `update` 函数里。你心里觉得这游戏挺完整。然后有一天你想给它加一个像样的开始——主菜单。所以你在 `update` 开头写了一句 `if in_menu { draw_menu(); } else { play(); }`。看着无害,你提交了。

接下来你想要暂停。`if paused { /* 啥也不做 */ } else { play(); }`。然后是 game over,你想让角色死了之后停在死亡画面上几秒:`if game_over { draw_death_overlay(); } else { ... }`。再然后是 loading,因为你想换关卡。再然后是 settings overlay,可以叠在主菜单上,也可以叠在暂停界面里。

三周后,你打开 `update`,发现它长成了一棵藤蔓。最外层是 `if in_menu`,里面套着 `if paused`,里面又套着 `if settings_open`,中间还夹着 `if loading`,每一层里都散落着 `if game_over`。你想在 settings overlay 里改一下音量,但音量更新的逻辑现在被嵌在四层 `if` 里面,你必须同时满足"在 menu + 在 paused + 在 settings + 不在 game_over"才能跑到那行代码。你想加个新的 debug overlay,发现它要插入到至少四个分支里,每插一处都可能弄坏另一处。你的 play 逻辑本身,被这一堆条件压在底下,基本读不下去。

这是几乎所有自学期开发者都会撞到的一堵墙。它的根子不是"你加功能加得太多",而是"你对游戏在任意时刻**处于什么模式**这件事,没有一个明确的模型"。你有的只是一堆互相纠缠的布尔旗标(`in_menu`、`paused`、`game_over`、`settings_open`、`loading`),它们之间的合法组合是少数,但你的代码允许任何组合——于是大部分组合是 bug,而且你不知道什么时候会触发。

这一篇给你那个缺失的模型。模型有两个零件:**游戏状态**(game state)和**状态栈**(state stack)。前者把"游戏当前在干什么"显式地表达出来,后者把"暂停叠在游戏上"这种天然嵌套的关系摆平。两个零件加起来,让你那一树藤蔓般的 `if` 坍缩成一个干净的分派:游戏问"我现在在哪个状态?",然后只跑那个状态的逻辑。别的状态,它根本不碰。这就是职业引擎组织游戏性时最底层的抽象,也是你接下来加 debug 模式、过场动画、多人大厅时不会弄坏现有功能的前提。

## 1 · 先把"游戏状态"这件事说清楚

在你写那堆 `if` 之前,我们先停下来,问一个更基础的问题:一个游戏,在任意时刻,到底处于哪几种"模式"之一?你会发现,无论游戏多复杂,它的高层模式都是一个有限的集合,而且**任意时刻它只能处在其中一个**——这是关键的洞察。

一个典型的成品游戏,大概有这么几种高层状态。游戏刚启动时,它处在 **Boot(启动)**:这一阶段的任务是加载最关键的资源(比如启动画面、字体、主菜单背景),初始化引擎子系统。这个阶段玩家基本看不到游戏世界,看到的是一个 logo 或者一个加载条。Boot 结束之后,游戏进入 **Menu(菜单)**:标题画面,可能挂着"开始游戏 / 设置 / 退出"几个按钮。在这里,角色不在跑,怪物不在 AI,物理世界不存在——只有 UI 在响应。玩家点"开始游戏",游戏进入 **Loading(加载)**:加载关卡、生成初始实体、热流入资源(这和 [scene-and-level-management](../../phase-7/deep-dives/scene-and-level-management.md) 直接相关)。Loading 完毕,游戏进入 **Play(游戏中)**:这是玩家真正玩的部分,物理在跑、AI 在跑、规则在判定。玩家按 Esc 暂停,游戏进入 **Pause(暂停)**:物理停了、AI 停了、规则停了,但画面可能还停在最后一帧,上面盖一层暂停 UI。最后,角色死了或通关了,游戏进入 **GameOver(结束)**:Play 的世界可能还显示着,但顶上盖一层结算画面。

注意每一件事:每个状态里,**跑的系统是不同的**(Boot 不跑物理,Play 跑物理,Pause 不跑物理),**输入的处理是不同的**(Menu 上方向键是选按钮,Play 上方向键是移动角色),**渲染的内容是不同的**(Loading 渲染加载条,Play 渲染世界,Pause 渲染世界 + 暂停覆盖层)。也就是说,状态不是"加几行 if 区分一下",状态是一种**完全不同的运行模式**,每个模式有自己的一套 update、input、render 行为。

把这个洞察写成代码,就是给它一个名字。在 Rust 里,我们用一个 enum:

```rust
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum GameState {
    Boot,
    Menu,
    Loading,
    Play,
    Pause,
    GameOver,
}
```

就这一行,已经比一堆布尔旗标强太多了。为什么?因为 enum 的值是**互斥的**——你处在 Play 就不可能同时处在 Menu,编译器和类型系统会替你强制这件事。而你的旧代码里,`in_menu` 和 `in_play` 是两个独立的 bool,你可以不小心同时把它们都设成 true,然后游戏行为变得诡异且没人知道为什么。enum 把这种"非法组合"在类型层面就扼杀了。

但这只是第一步。光有一个 enum 标签,你的 update 还是会写成 `match state { Boot => ..., Menu => ..., ... }`,而且每个分支会迅速膨胀。真正的解法,是把"每个状态的行为"封装到状态本身——也就是接下来要讲的状态机。

## 2 · 把它做成状态机:每个状态带 enter / exit / update / render

状态机(state machine)是一个老得不能再老的概念,但它在游戏里的应用是恰到好处的。核心想法是:**每一个状态,自己知道怎么进入、怎么离开、每帧怎么更新、每帧怎么渲染。** 游戏主循环不再去关心"现在是不是暂停"——它只问状态机:"你现在是哪个状态?好,你跑那个状态自己的 update。"分派这件事,在状态机内部一次性完成。

我们先定义一个 trait,把"一个状态的行为"抽象出来:

```rust
trait GameStateT {
    fn on_enter(&mut self, ctx: &mut GameContext);
    fn on_exit(&mut self, ctx: &mut GameContext);
    fn update(&mut self, ctx: &mut GameContext, dt: f32);
    fn render(&self, ctx: &RenderContext);
}
```

这四个方法是状态机的全部。`on_enter` 在状态**成为当前状态的那一刻**调用一次,适合做一次性初始化(切主菜单 BGM、开始异步加载)。`on_exit` 在状态**被替换掉的那一刻**调用一次,适合做释放资源和写存档(存档见 [savegame-and-serialization](../../phase-8/deep-dives/savegame-and-serialization.md))。`update` 每帧调用,跑真正的逻辑;`render` 每帧调用,画该画的东西。

然后我们用一个 `Box<dyn GameStateT>` 持有当前状态:

```rust
struct Game {
    current: Box<dyn GameStateT>,
    ctx: GameContext,
}

impl Game {
    fn switch(&mut self, mut new_state: Box<dyn GameStateT>) {
        self.current.on_exit(&mut self.ctx);
        std::mem::swap(&mut self.current, &mut new_state);
        self.current.on_enter(&mut self.ctx);
    }

    fn tick(&mut self, dt: f32) {
        self.current.update(&mut self.ctx, dt);
        self.current.render(&self.ctx.render);
    }
}
```

注意 `switch` 方法干了三件事,顺序很重要:先 `on_exit` 旧状态,再把旧状态换成新状态,再 `on_enter` 新状态。`on_exit` 必须在旧状态被换走之前调用,因为它可能还要读旧状态的内部数据(比如把分数写存档);`on_enter` 必须在新状态就位之后调用,因为它要初始化新状态的内部数据。这个顺序是状态机最容易被写错的地方,如果弄反,你会遇到"on_enter 里访问的字段还没初始化"这种 panic。

具体到 Menu 状态,它的实现大概长这样:

```rust
struct MenuState {
    selected: usize,
    items: Vec<&'static str>,
}

impl MenuState {
    fn new() -> Self {
        Self { selected: 0, items: vec!["开始游戏", "设置", "退出"] }
    }
}

impl GameStateT for MenuState {
    fn on_enter(&mut self, ctx: &mut GameContext) {
        ctx.audio.play_music("menu_theme.ogg");
    }
    fn on_exit(&mut self, ctx: &mut GameContext) { /* 释放菜单资源 */ }
    fn update(&mut self, ctx: &mut GameContext, _dt: f32) {
        if ctx.input.was_pressed(Action::Up) {
            self.selected = (self.selected + self.items.len() - 1) % self.items.len();
        }
        if ctx.input.was_pressed(Action::Down) {
            self.selected = (self.selected + 1) % self.items.len();
        }
        if ctx.input.was_pressed(Action::Confirm) {
            match self.selected {
                0 => ctx.request_state_change(StateRequest::Push(Box::new(LoadingState::new()))),
                1 => ctx.request_state_change(StateRequest::Push(Box::new(SettingsState::new()))),
                2 => ctx.quit = true,
                _ => {}
            }
        }
    }
    fn render(&self, ctx: &RenderContext) {
        ctx.draw_menu_background();
        for (i, item) in self.items.iter().enumerate() {
            let highlighted = i == self.selected;
            ctx.draw_menu_item(item, i, highlighted);
        }
    }
}
```

你看,Menu 状态完全不知道 Play 状态长什么样,也完全不知道 Loading 状态长什么样。它只通过 `ctx.request_state_change` 表达"我想切到某个状态",至于切不切、什么时候切,是状态机外部的事。**状态之间的耦合,被压到了"请求"这一层,状态之间不再互相直接调用。** 这是状态机最大的解耦价值——你想加一个新的状态(比如 Credits),你不需要改任何已有状态的内部代码,只需要让它有一个新的 `request_state_change` 目标。

但等一下。注意上面我写的是 `StateRequest::Push`,不是 `Switch`。这里我埋了一个伏笔,这个伏笔是这一篇的核心:为什么切到 Loading 不是"切换",而是"压栈"?这就引出了状态机最大的盲点——也是它必须升级为状态栈的原因。

## 3 · 状态机的盲点:暂停不是"切换",是"叠加"

让我们用暂停来戳穿状态机的盲点。

玩家正在 Play 状态玩游戏,按 Esc 暂停。如果用纯状态机,你会这么做:从 Play 切换到 Pause。但这里有个根本性的问题——**切换意味着 Play 状态被销毁了**。Play 状态的 `on_exit` 会被调用,它会按照 09B-2 子系统生命周期那一套,把物理子系统停掉、把当前关卡的世界状态卸载、把 AI 上下文清空。等玩家从暂停回到游戏时,你得重新进入 Play 状态——重新加载关卡、重新生成实体、重新初始化 AI。玩家暂停两秒再继续,世界整个重建一遍。

这不是一个无伤大雅的低效——这是**根本性的错误**。暂停的语义是"冻结当前世界,在它上面盖一层 UI",而不是"销毁当前世界,玩家想继续就重新创建一个"。玩家的进度、怪物的位置、子弹的飞行轨迹、AI 的状态机,所有这些都不应该因为按了一下 Esc 而丢失或重建。换句话说,Pause 状态不是 Play 状态的**替代品**,它是 Play 状态的**叠加层**——它在 Play 之上,不取代 Play。

更糟的是,settings overlay 可以叠在 pause 之上。你点暂停菜单里的"设置",就出现 settings 界面——这个界面叠在 pause 之上,pause 又叠在 play 之上。从 settings 退出来,回到 pause;从 pause 退出来,回到 play。这是一个**栈**——后进先出,每一层都是它下面那一层的叠加。

扁平的状态机模型不了这个。栈能。

## 4 · 状态栈:用一个栈代替单个 `current`

把状态机的"一个 current"升级成"一个状态栈",是这一篇的关键洞察。状态栈(state stack)的核心规则是:**栈顶的状态是"活跃状态"(active state),只有它的 `update` 被调用**——栈下面那些状态虽然还活着,但它们每帧不更新,只是可能被渲染(取决于它们想让玩家看到什么)。把一个新状态压入栈顶(push),意味着"在当前状态之上叠加一层";从栈顶弹出一个状态(pop),意味着"撤销最上面这一层,下面那层重新活跃"。

这就是暂停的精确模型:暂停,就是把 PauseState 压栈——PlayState 还在栈底,但它的 update 不再被调用(物理停了、AI 停了),它的 render 可能还被调用(画面停在最后一帧,从 PauseState 顶上透出来);玩家按 Esc 退出暂停,就把 PauseState 弹出栈——PlayState 重新成为栈顶,它的 update 重新被调用(物理恢复、AI 恢复),世界无缝继续。Pause 的 enter/exit 不销毁任何 Play 的数据,因为它从没"取代"过 Play,只是叠在它上面。

代码上,这个改造很干净。把 `current: Box<dyn GameStateT>` 换成 `stack: Vec<Box<dyn GameStateT>>`:

```rust
struct Game {
    stack: Vec<Box<dyn GameStateT>>,
    ctx: GameContext,
    pending: Vec<StateRequest>,
}

enum StateRequest {
    Push(Box<dyn GameStateT>),
    Pop,
    Switch(Box<dyn GameStateT>),  // = Pop + Push,两个原子操作
    Quit,
}

impl Game {
    fn push(&mut self, mut s: Box<dyn GameStateT>) {
        if let Some(top) = self.stack.last_mut() {
            top.on_suspend(&mut self.ctx);  // 见下面"暂停语义"那一节
        }
        s.on_enter(&mut self.ctx);
        self.stack.push(s);
    }

    fn pop(&mut self) -> Option<Box<dyn GameStateT>> {
        let popped = self.stack.pop()?;
        popped.on_exit(&mut self.ctx);
        if let Some(top) = self.stack.last_mut() {
            top.on_resume(&mut self.ctx);
        }
        Some(popped)
    }

    fn tick(&mut self, dt: f32) {
        // 关键:只跑栈顶的 update
        if let Some(top) = self.stack.last_mut() {
            top.update(&mut self.ctx, dt);
        }
        // 关键:从栈底往栈顶依次 render——这样上层覆盖下层
        for s in self.stack.iter() {
            s.render(&self.ctx.render);
        }
        // 处理这一帧积攒下来的状态切换请求
        self.drain_requests();
    }

    fn drain_requests(&mut self) {
        let pending = std::mem::take(&mut self.pending);
        for req in pending {
            match req {
                StateRequest::Push(s) => self.push(s),
                StateRequest::Pop    => { self.pop(); }
                StateRequest::Switch(s) => { self.pop(); self.push(s); }
                StateRequest::Quit => self.ctx.quit = true,
            }
        }
    }
}
```

注意两件事。第一,`tick` 里 update 只调栈顶,而 render 从栈底到栈顶**全部**调用。这个不对称是有意的——叠加层的状态(像 Pause)需要看到底下 Play 还在画面上(否则暂停就是黑屏),所以 Play 的 render 还在跑;但 Play 的 update 不能跑(否则物理没真停),所以 Play 的 update 被屏蔽了。这是栈模型对"暂停"语义的精确表达:**视觉上还在,行为上冻结**。

第二,我引入了两个新的状态方法:`on_suspend` 和 `on_resume`。它们和 `on_enter`/`on_exit` 不一样。`on_exit` 是"这个状态被彻底销毁"时调用,而 `on_suspend` 是"这个状态被压在下面、暂时不活跃"时调用——它不销毁数据,只是做一些"挂起"的清理,比如把音量降到很低但不停止播放。`on_resume` 是反过来。这四个方法区分了两种完全不同的状态变化:切换(switch,旧状态死,新状态生)和叠加(push/pop,旧状态挂起,新状态生然后死,旧状态恢复)。这是状态栈相比扁平状态机多出来的精细度,正是这精细度让你能干净地表达暂停。

把这四个方法加到 trait 里:

```rust
trait GameStateT {
    fn on_enter(&mut self, ctx: &mut GameContext) {}
    fn on_exit(&mut self, ctx: &mut GameContext) {}
    fn on_suspend(&mut self, ctx: &mut GameContext) {}   // 被压到栈下时
    fn on_resume(&mut self, ctx: &mut GameContext) {}    // 重新成为栈顶时
    fn update(&mut self, ctx: &mut GameContext, dt: f32);
    fn render(&self, ctx: &RenderContext);
}
```

默认实现是空的,这样简单状态(比如 Boot 这种不需要挂起逻辑的)不用关心 suspend/resume,只有需要精确控制叠加行为的状态才覆写它们。PauseState 通常会覆写 `on_enter` 把音量降下来、`on_exit` 把音量恢复;PlayState 通常会覆写 `on_suspend` 释放鼠标(因为菜单需要鼠标)、`on_resume` 重新锁定鼠标。

## 5 · 把状态栈接到 ECS 系统激活上:每个状态点亮不同的系统组

讲到这里,你应该感觉到状态栈和 [entity-system](entity-system.md) 是天然搭档。一个游戏的 ECS,有几十上百个系统(system)——物理系统、动画系统、AI 系统、玩家输入系统、UI 输入系统、相机系统、粒子系统、音频系统等等。在 Play 状态,这些系统该跑的全跑;在 Pause 状态,物理/AI/玩家输入这一组该停;在 Menu 状态,世界相关的系统整个组都不应该存在(因为世界没加载)。

如果你不在状态栈层面控制系统的开关,你会落回到那一树 `if`:每个系统内部都得问"我现在该不该跑",每个系统的代码都被这种"自我检查"污染。**正确的做法是让状态来决定哪些系统活跃**,这是 09B-2 子系统生命周期在状态层面的体现——每个状态进入时点亮一组系统,退出时熄灭一组系统。

在 ECS 里,这通常表达成"系统集合"(system set)或者"调度标签"(schedule label)。Bevy 用 `SystemSet`,我们这里用一个简化的版本:每个状态声明它要跑哪些系统组,主循环按栈顶状态的声明来调度。

```rust
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
enum SystemGroup {
    Boot,
    UiInput,        // 菜单/settings 的输入
    WorldSim,       // 物理 + AI + 规则
    PlayerControl,  // 玩家操作角色
    Cinematic,      // 过场动画
    DebugOverlay,   // 调试覆盖层
    Renderer,
    Audio,
}

trait GameStateT {
    fn active_groups(&self) -> &'static [SystemGroup] { &[] }
    // ... 其他方法
}

impl GameStateT for PlayState {
    fn active_groups(&self) -> &'static [SystemGroup] {
        &[SystemGroup::WorldSim, SystemGroup::PlayerControl,
          SystemGroup::Renderer, SystemGroup::Audio]
    }
    // ...
}

impl GameStateT for PauseState {
    fn active_groups(&self) -> &'static [SystemGroup] {
        // 注意:WorldSim / PlayerControl 都不在这里
        &[SystemGroup::UiInput, SystemGroup::Renderer, SystemGroup::Audio]
    }
    // ...
}
```

主循环在调度时,只跑"栈顶状态声明的那几个组"对应的系统:

```rust
impl Game {
    fn run_active_systems(&mut self, world: &mut World, dt: f32) {
        let active: HashSet<SystemGroup> = self.stack.last()
            .map(|s| s.active_groups().iter().copied().collect())
            .unwrap_or_default();
        if active.contains(&SystemGroup::WorldSim)     { run_world_sim(world, dt); }
        if active.contains(&SystemGroup::PlayerControl){ run_player_control(world, &self.ctx.input); }
        if active.contains(&SystemGroup::UiInput)      { run_ui_input(world, &self.ctx.input); }
        // ... 其他组
    }
}
```

这样一来,每个系统自己**不需要**问"我现在该不该跑"——它只关心本职工作。是否跑它,是状态机根据当前状态决定的。`physics_system` 永远只算物理,它不知道 Pause 是什么,也不需要知道。**状态栈管理"什么在跑",ECS 管理"跑的是什么"**——分工明确,互不污染。这正是 09B-2 子系统生命周期在状态层面的体现:那一篇讲子系统怎么启动关闭,这一篇讲状态怎么决定哪些子系统该启动。两层合作,引擎就有了"按模式精确开关功能"的能力。

## 6 · 状态切换不是瞬时的:Loading 和过渡本身是状态

到现在我们假装状态切换是瞬时的——`Switch` 一调,旧状态退出,新状态进入,下一帧就在新状态里了。但真实游戏里,从 Menu 切到 Play 几乎从不瞬时。Play 状态需要加载关卡——读关卡文件、生成几百个实体、热流入贴图和模型(这是 [scene-and-level-management](../../phase-7/deep-dives/scene-and-level-management.md) 的主题),可能持续几百毫秒到几秒。在此期间你不能让玩家盯着冻结的画面,你要画一个 LoadingScreen。

这意味着 **Loading 本身是一个状态**:它压在 Menu 之上,显示加载条,背后异步推进资源加载,完成后再 `Switch` 到 Play。不是所有状态切换都是瞬时的,有些切换本身就需要一个状态来"承载过渡"——状态机足够灵活,可以用一个状态来表达"我现在正在做切换这件事"。

```rust
struct LoadingState {
    target_level: LevelId,
    progress: f32,
    async_ops: Vec<AsyncLoad>,
}

impl GameStateT for LoadingState {
    fn on_enter(&mut self, ctx: &mut GameContext) {
        // 启动异步加载,见 scene-and-level-management
        self.async_ops = ctx.assets.start_load(self.target_level);
    }
    fn update(&mut self, ctx: &mut GameContext, _dt: f32) {
        // 推进异步操作,看是否完成
        let done = self.async_ops.iter()
            .filter(|op| op.is_done())
            .count();
        self.progress = done as f32 / self.async_ops.len() as f32;
        if self.progress >= 1.0 {
            // 加载完成,切换到 Play
            let world = ctx.assets.finalize_load(self.target_level);
            ctx.request_state_change(StateRequest::Switch(
                Box::new(PlayState::new(world))
            ));
        }
    }
    fn render(&self, ctx: &RenderContext) {
        ctx.draw_loading_bar(self.progress);
    }
    fn active_groups(&self) -> &'static [SystemGroup] {
        &[SystemGroup::Renderer]  // 加载期间啥都不模拟,只画加载条
    }
}
```

这里有个设计上的微妙之处。`LoadingState` 不直接构造 PlayState 然后切换——它通过 `request_state_change` 表达意图,真正的切换由 `Game::drain_requests` 在这一帧的 update 结束时统一执行。为什么不在 update 中途直接调 `Switch`?因为此时 `self` 还在被借用,且逻辑上是"半完成的状态在切换"。`request_state_change` 把切换推迟到 update 完全结束后再做,保证了状态切换的原子性。**所有状态切换都应该走"请求-延迟-执行"这条路,不要在 update 里直接动栈。**

过渡(transitions)还有更花哨的形式——黑屏淡入淡出(fade to black)、白屏闪光、章节卡转场。这些都是用一个特殊的"过渡状态"实现的:它压在两个状态之间,执行一段定时动画(比如 0.5 秒从透明渐变到全黑),动画到中点时执行底层的状态切换,动画到终点时把自己弹出栈。过渡本身被建模成一个状态——可组合、可复用、不污染它连接的两个状态。骨架大致是:一个 `FadeTransition { elapsed, duration, inner_target }`,update 里累计 elapsed,半程时 `Switch(inner_target)`,全程时 `Pop` 自己;render 里画一个全屏黑色 quad,alpha 从 0 升到 1 再降到 0。具体代码留作 §10 的练习,这里你要记住的是模式本身:**让一切都成为状态,包括"状态之间的变化"本身**——这是状态机最优雅的用法,也是职业引擎几乎都会有的设施。

## 7 · 和 09B-1 的固定步长循环怎么配合

状态栈和 [09B-1 讲的固定步长循环](../../phase-9/09B-1-game-loop-and-timestep.md)是必须合作的两个层。09B-1 讲的是"心跳怎么跳得稳"——累加器、固定 dt、插值渲染;状态栈讲的是"心跳每跳一下该跳谁"——是 Play 的 update,还是 Pause 的 update,还是 Menu 的 update。

合作的关键点:**模拟步进(step)只在 Play 这种"模拟世界"的状态里被调用**。在 Menu、Loading、Pause、GameOver 这些状态下,累加器可以照样累积真实时间,但**不该调用 step 推进世界**。暂停的精确实现就是:"这一帧累加器满了 FIXED_DT,但我处在 Pause,所以不 step。"固定步长循环的 `while accum >= FIXED_DT { step(); accum -= FIXED_DT; }` 这个内层循环,只在 Play 状态里跑;在 Pause 状态,这个内层循环被跳过,但渲染照常发生。

把状态栈接到 09B-1 那个循环骨架里,大概是这样:

```rust
const FIXED_DT: f64 = 1.0 / 60.0;
const MAX_FRAME: f64 = 0.25;

fn main() {
    let mut game = Game::new();  // 启动时栈里只有 BootState
    let mut accum: f64 = 0.0;
    let mut last = Instant::now();

    loop {
        let now = Instant::now();
        let mut frame = now.duration_since(last).as_secs_f64();
        last = now;
        if frame > MAX_FRAME { frame = MAX_FRAME; }
        accum += frame;

        // 处理输入——这一层每个状态都要收输入
        game.collect_input();

        // 模拟:只在栈顶是"模拟型"状态时才推进世界
        let should_simulate = game.stack.last()
            .map(|s| s.active_groups().contains(&SystemGroup::WorldSim))
            .unwrap_or(false);

        while accum >= FIXED_DT && should_simulate {
            let prev = game.snapshot_world();
            game.step_world(FIXED_DT as f32);  // 只跑 WorldSim 那一组系统
            accum -= FIXED_DT;
        }
        // 注意:如果 should_simulate 是 false,累加器不消耗。
        // 但要避免它无限累积——回到 Play 时会一次性跑很多步。
        // 简单做法:不模拟时把累加器清零(玩家不在意暂停期间"积攒"的时间)
        if !should_simulate {
            accum = 0.0;
        }

        // 每帧都跑的非模拟 update(菜单的 UI 逻辑、Loading 的进度推进、Pause 的输入)
        if let Some(top) = game.stack.last_mut() {
            top.update(&mut game.ctx, frame as f32);
        }

        // 每帧都渲染——从栈底到栈顶
        for s in game.stack.iter() {
            s.render(&game.ctx.render);
        }

        game.drain_requests();
        if game.ctx.quit { break; }
    }
}
```

注意几个微妙的地方。`should_simulate` 决定了固定步长循环是否消费累加器——这是状态机对循环的"放行/截断"控制。当不该模拟时,我把累加器清零,这一点要权衡:不清零的话,玩家暂停两分钟,回到 Play 时会一次性跑 7200 步把世界推进两分钟——这显然不是玩家想要的;清零就抹掉了暂停期间的"模拟债务",世界从暂停的那一刻继续。UI/菜单这种**不需要固定步长**的逻辑,直接用 `frame`(真实 dt)跑——菜单的输入响应不需要确定性,真实 dt 就够。什么用固定 dt、什么用真实 dt,这种区分是状态栈和固定步长合作的精髓。

09B-1 反复强调"模拟时间和真实时间分开",状态栈补上了这个分工的另一半:**模拟时间在什么状态下应该流,在什么状态下不应该流。** 固定步长保证模拟稳定,状态栈保证模拟在合适的模式下进行。

## 8 · 输入也是状态相关的:同一个按键在不同状态下含义不同

到此为止我们讲了 update 和 render 怎么按状态分派,还有一个隐藏的复杂度——输入。同一个方向键上下,在 Play 状态意味着"角色前后移动",在 Menu 状态意味着"光标上下选菜单",在 Settings 状态意味着"调滑块"。如果你的输入处理是全局的 `process_input`,它迟早要变成又一棵 `if state == X { ... } else if state == Y { ... }` 的藤蔓。

正确的做法和 update 一样——**让每个状态自己消费自己的输入**。我们的 trait 里 `update` 已经收到了 `&mut GameContext`,而 `GameContext` 持有这一帧的输入快照,所以每个状态的 update 自然只消费自己关心的输入。PlayState 只看 WASD 和鼠标;MenuState 只看方向键和确认。状态之间不互相干扰。

这种"每个状态只消费自己的输入"自然解决了输入分发器的藤蔓问题。它引出一个隐含约定:**栈底的状态失去输入权**——下面的状态虽然在栈里,但它收不到输入,因为它不 update。只有一个常见的例外:有些游戏想让"按 Esc"在 Play 状态触发暂停——Esc 不应该被 PlayState 自己消费(它不知道 PauseState 存在),所以更优雅的做法是把 Esc 定义为"全局快捷键",由状态机本身监听,触发 `Push(Box::new(PauseState))`。这种"少数全局快捷键 + 多数状态自处理"的混合模式是职业引擎常用的折中。事件系统本身(按键按下/抬起 vs 按住)在 [event-systems-and-gameplay-foundations](../../phase-5/deep-dives/event-systems-and-gameplay-foundations.md) 那一篇详细讲,这里只点到"状态栈决定了输入归谁"。

## 9 · 把这些用到你的 HH 项目上(做中学红线)

现在轮到你把你跟完的 HH 游戏从一堆旗标重构到状态栈。你能把藤蔓般的 `if` 坍缩成几个干净的状态,会觉得世界一下清爽了。

先把你 `main.rs` 或 platform 层里的 `update` 函数看一遍,把所有 `if in_menu` / `if paused` / `if game_over` / `if loading` 旗标全部标记出来——它们的每一个分支都是即将消失的代码。识别出它们各自代表的行为:菜单分支会变成 MenuState,playing 分支变成 PlayState,paused 分支变成 PauseState,game-over 分支变成 GameOverState,可能还有 LoadingState。

然后定义 `GameStateT` trait,先只放 `on_enter`/`on_exit`/`update`/`render` 四个方法,默认实现全空——suspend/resume 等你需要"暂停时降音量"时再加。定义 `GameContext`,至少持有输入快照、音频引擎句柄、资源管理器句柄、和 `pending: Vec<StateRequest>`。把现在的 playing 行为整体搬进 `PlayState::update`,菜单行为搬进 `MenuState::update`,暂停行为搬进 `PauseState::update`。这里不重写逻辑,只是把行为从原来纠缠的位置剥离出来——`PlayState::update` 里不再有 `if paused`,因为暂停时这个 update 根本不被调用。

接下来把 `Game::current: Box<dyn GameStateT>` 改成 `Game::stack: Vec<Box<dyn GameStateT>>`,实现 `push`/`pop`/`Switch` 和 `tick`(update 栈顶,render 栈底到栈顶)。小心 `Switch`——它是 `Pop + Push` 的组合,要按正确顺序:on_exit 旧状态、弹出栈、on_enter 新状态、压入栈。

然后搭一条完整流程:启动时栈里只有 MenuState;玩家选"开始游戏",触发 `Push(LoadingState)`;LoadingState 加载完成,`Switch` 到 PlayState;玩家按 Esc,触发 `Push(PauseState)`;暂停菜单选"继续",`Pop` 回 Play;选"返回主菜单",`Switch` 到 Menu(此时栈底 PlayState 真的被销毁,on_exit 触发,这是合理的——你确实想离开这局游戏)。

最后做四个验证。第一,完整走一遍 Menu → Loading → Play → Pause → Play → GameOver → Menu,确认每个切换按预期工作,暂停期间画面冻结但不停在黑屏上。第二,给 PauseState 加 `on_enter` 降音量 / `on_exit` 恢复音量,确认背景音真的变小——suspend/resume 语义生效。第三,在 Play 里加全局 Esc 监听,Esc 直接 `Push(PauseState)`,确认全局快捷键能跑通。第四,在 Pause 上叠一个 SettingsState,确认三层栈(Menu → Play → Pause → Settings,Menu 在最底但你看不到它)能正常工作,从 Settings 逐层 Pop 回到 Play——这第四个验证特别重要,它检验你是否真的理解了栈模型,而不只是会做两层。

做完这四个验证,你的 HH 游戏就跨过了"游戏性组织"这道门槛。提交信息可以写 "refactor gameplay into state stack with push/pop overlays"。

## 10 · 练习

练习一(概念辨析,Lv1)。有人问:"我用扁平状态机,不就行了吗?暂停的时候我设 `paused = true`,update 里加个 `if !paused { simulate() }` 就行了,为什么要弄成栈?" 想清楚栈相比扁平状态机多给了你什么——重点是"叠加"这个语义(暂停不销毁 Play,settings 可以叠在 pause 上),以及状态之间的耦合被压到了"请求"层。把答案用自己的话写出来,如果你只能说"更清晰"这种空话,说明你还没真懂。

练习二(动手实践,Lv2)。完成 §9 的全部六步重构。把你之前 update 里的所有旗标代码量总和统计一下,重构之后这些旗标代码全部消失,只换成了几个状态类——直观对比代码行数和嵌套层数。

练习三(过渡状态,Lv3)。给你的 HH 游戏加一个 `FadeTransition` 状态——从 Menu 切到 Play 时不瞬间切换,而是先压入 FadeTransition,它在 0.3 秒内画面渐黑,中点时切换底层到 Play,再 0.3 秒画面渐亮,然后把自己弹出栈。这样你就有了 3A 游戏里那种"淡入淡出"的转场效果。注意 FadeTransition 的 `active_groups` 应该返回什么——过渡期间通常不模拟世界(否则切换发生在哪一刻不明确)。

练习四(状态栈的边界,Lv4)。考虑这个场景:玩家在 Play 状态按了"打开 debug overlay"的全局快捷键,debug overlay 是 Push 上来的状态。玩家在 debug overlay 里又按了 Esc 想暂停。Esc 应该触发 Push(PauseState),还是被 debug overlay 自己消费(关闭 debug overlay)? 设计你的策略并陈述理由。这个练习没有标准答案,但它逼你思考状态栈里"输入归谁"这个真实的设计问题——职业游戏每加一个新状态,都要重新讨论输入优先级。

## 11 · 延伸阅读

本仓库内紧密相关的几篇:

- [09B-1 游戏循环与固定步长](../../phase-9/09B-1-game-loop-and-timestep.md) 是这一篇的循环层底座——这一篇讲"心跳每跳一下跳谁",那一篇讲"心跳怎么跳得稳",两层合起来才有完整的时间模型。
- [09B-2 子系统生命周期](../../phase-9/09B-2-subsystems-modules-plugins.md) 是状态栈的子系统层底座——这一篇的状态激活/停用,底层是那一篇讲的子系统启动/关闭顺序。
- [entity-system](entity-system.md) 解释了 ECS 的系统(system)概念,这一篇的 `SystemGroup` 调度建立在那之上。
- [event-systems-and-gameplay-foundations](../../phase-5/deep-dives/event-systems-and-gameplay-foundations.md) 讲输入事件怎么在系统间分发,这一篇的"输入归栈顶状态"是它的一个上层应用。
- [scene-and-level-management](../../phase-7/deep-dives/scene-and-level-management.md) 讲关卡怎么加载,这一篇的 LoadingState 是它的承载者。
- [savegame-and-serialization](../../phase-8/deep-dives/savegame-and-serialization.md) 讲存档,这一篇的状态 on_enter/on_exit 是触发存档写入的天然时机。

外部经典:

- Robert Nystrom《Game Programming Patterns》的 "State" 一章,网上免费可读,把状态机讲得非常透彻,而且讲了栈式状态机(frozen state stack),强烈推荐——这一篇的很多思路源自它。
- Jason Gregory《Game Engine Architecture》第三版的第 6 章(Application Layer),里面有专门的"Game State Machine"小节,讲顽皮狗在《最后生还者》《神秘海域》里是怎么用状态机组织游戏流程的,工业级实现长什么样。
- Bevy 引擎的 `bevy_state` crate,把状态机做成了 ECS 的 first-class 概念,State / NextState / OnEnter / OnExit 这套 API 直接对应这一篇讲的那些概念,看它能对号入座。

最后,这一篇的"状态栈"和 [phase-9/09B-2 子系统生命周期](../../phase-9/09B-2-subsystems-modules-plugins.md) 是同一件事的两个视角:状态栈是上层指挥(决定哪些子系统该活跃),生命周期是下层执行(子系统按什么顺序启动关闭)。读完这两篇,你就有了"按模式精确开关功能"的完整心智。
