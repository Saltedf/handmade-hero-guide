---
phase: 7
title_en: "Game UI Architecture (T7 Deep Dive 1/3)"
title_zh: "游戏 UI 架构:retained、immediate、hybrid 与子系统化"
type: deep-dive
difficulty: 4
duration: "2-3 小时"
domains: [game, rust, ui, engineering]
prereqs: ["immediate-mode-ui", "ui-data-binding-short"]
calibration: "游戏 UI 架构(retained vs immediate vs hybrid)+ UI 作为子系统 + 事件路由。这是 T7 游戏 UI 深度三联的第一篇(架构),第二篇讲布局引擎(ui-layout-engines),第三篇讲样式与动画。"
---

# 游戏 UI 架构:retained、immediate、hybrid

> 你的游戏 UI 是一锅粥。
>
> HUD 的血条写在 `render_hud()` 里,菜单写在 `menu_screen.rs` 里,设置面板的滑块又散在 `settings.rs` 里。三套代码,三种重画方式,三种输入处理。你新增一个"暂停覆盖"界面,得先想清楚——它在哪一帧画?输入先于还是后于游戏世界?会盖住 HUD 吗?写完发现按 ESC 菜单出现了,但游戏世界的手柄输入还在响——因为没人统一管"现在 UI 在前台还是游戏在前台"。
>
> 你用 Dear ImGui(就是 immediate-mode-ui 那套)写了调试工具,体验丝滑。于是想用 ImGui 把游戏 UI 也写了。三天后发现——血条能画,但加 0.2 秒平滑过渡得每帧手维护动画状态;玩家用 gamepad 在菜单间导航得自己撸焦点系统,因为 ImGui 鼠标优先;按钮 hover 高亮渐变,immediate 模式下"上一帧 hover 没 hover"得自己存。你越写越觉得不对劲——**这不是 UI 库的问题,是你根本没有 UI 架构**。
>
> 这一篇就是这个架构。它是 T7 "游戏 UI 深度"三联的第一篇(三篇:**架构**(本文)、**布局引擎**(ui-layout-engines)、**样式与动画**)。读完你会理解为什么游戏 UI 必须是独立子系统(不是散在游戏代码里的若干函数),retained / immediate / hybrid 三种范式各自的取舍,widget 树怎么组织,事件怎么路由,focus 怎么管,数据怎么绑——以及为什么 AAA 的 UI 团队几十人用几百万行的 retained 系统,而你的调试面板用 ImGui 几行就搞定。两件事都对,因为它们解决的不是同一个问题。

## 1 · 先想清楚:游戏 UI 跟应用 UI 不是一回事

进入"用什么架构"之前,先讲一个常被忽略、但定调整个讨论的事实——**游戏 UI 和桌面/移动应用 UI,虽然看起来都是"画按钮",但工程上几乎不是同一个东西**。拿 React 写网页的心智直接套游戏,会处处碰壁;反过来也一样。

桌面应用 UI(浏览器、IDE、办公软件)的特点:窗口可任意缩放,布局必须**流式响应**(reflow);用户主要用**鼠标 + 键盘**,点击是离散事件;UI 是**主体**,占据整个屏幕和整个交互;它**长时间停留**在某个状态(打开的对话框一直在那)。这些特点催生了 DOM、CSS、flexbox、accessibility tree、键盘焦点环——一整套为"长时间停留的、鼠标键盘驱动的、可变尺寸的"UI 准备的基础设施。

游戏 UI 几乎完全相反。尺寸**固定**(1080p、4K,几个档位,不流式);输入以**手柄 + 触屏**为主,手柄是 8 方向加几个按键,没有鼠标 hover 概念;UI 大部分时候是**叠在游戏世界之上**的薄层(HUD),主体是 3D 场景;UI 频繁**出现和消失**(对话、伤害飘字、提示、过场字幕),很多元素寿命只有几百毫秒;还要和**实时渲染**深度协作(世界空间血条、3D 化菜单),这是桌面应用完全没有的。

差异巨大,所以游戏 UI 走出自己的路:几乎都是**屏幕空间**(screen-space)的 2D 渲染,有自己的正交相机、自己的深度(永远在 3D 世界之上,但 UI 内部也有层叠);用**坐标 + 锚点**(anchor)定位,而不是流式布局(屏幕尺寸固定);必须有**手柄导航**(gamepad navigation)和**焦点系统**(focus system),因为手柄没有"鼠标移过去",焦点是 UI 的核心状态;还需要**世界-屏幕混合**(nameplate、3D 菜单)。

记住这个底色——**游戏 UI 是叠加在实时 3D 世界之上的、屏幕空间的、手柄/触屏驱动的、有自己的渲染和输入层的独立子系统**。后面所有架构选择,都从这个底色推出来。

## 2 · Immediate vs retained:那个根本的选择

现在讲整个游戏 UI 架构最核心的一刀——immediate 还是 retained。这个选择决定后面所有代码的形状。读过 [immediate-mode-ui](../../phase-5/deep-dives/immediate-mode-ui.md) 你已见过两种风格对比,这里从"游戏 UI 该用哪个"的角度重讲。

**Immediate-mode UI**(立即模式 UI,Dear ImGui / egui / Casey debug UI 那种):你**每帧重新声明**整个 UI——"在这画按钮,被点了吗?下面画滑块,值多少?"。UI 没有持久"对象",所有信息从函数参数进来,所有状态(被 hover、被点、被拖)当帧计算、当帧用完。伟大在于**无状态同步 bug**——UI 永远精确反映代码当前状态。对 hot-reload 极友好(代码改了下一帧立刻生效)。对工具软件统治级——Unreal Editor 某些面板、Blender 属性编辑器、Substance Painter 背后都是 immediate。

但 immediate 在"游戏 UI"上有天花板。不是"不能"做(egui 完全能画血条),而是几个**根本特性**和游戏 UI 需求**互相打架**。

第一个架:**动画别扭**。血条加 0.2 秒平滑过渡——上一帧 80,这一帧 50,想 200ms 缓动到 50。immediate 里你得自己存"当前显示血量""目标血量""过渡进度",每帧手动更新。一个控件还好,十个就要一套状态管理基础设施——而这件事 retained 天生帮你做了(对象保留状态,你只改目标值,系统自动 tween)。

第二个架:**手柄导航难**。手柄导航核心是"焦点"——当前哪个控件被选中,按上下左右焦点移到哪个邻居。这要求控件之间互相"知道"彼此存在,形成可遍历的图。但 immediate 每帧控件都是临时构造的,它们之间没有持久引用——上一帧 button #3 和这一帧 button #3 是两个不同的临时对象。要做手柄导航,得自己用全局 focus state 加每帧 ID 重建焦点图,这是 egui 后来不得不补的能力,补得很费劲。

第三个架:**样式系统弱**。游戏 UI 要"漂亮"——hover 时柔和高亮、按下弹性反馈、面板渐变背景、文字描边阴影。immediate 库默认样式是"程序员审美"(ImGui 那个灰色方块),优先"够用、快"。要做商业级别 UI 视觉,你得在 immediate 之上自己叠样式系统——这时已经在重新发明 retained 了。

**Retained-mode UI**(保留模式 UI)反过来:你**一次构建**一棵 UI 元素树(Panel 包 Button,Button 包 Text),这棵树**持续存在**;改属性(`button.label = "Pause"`、`panel.visible = false`)来更新 UI,系统负责把变化反映到屏幕——包括动画、布局、重绘。DOM 是 retained;Qt / GTK / Win32 是 retained;Unity 的 UI Toolkit、Unreal 的 UMG、Godot 的 Control、Bevy UI 都是 retained。

Retained 的好处正好补 immediate 短板:**动画、样式、手柄导航都天然顺滑**。对象持续存在,给 button 设目标 hover 状态,系统每帧自动 tween;对象间有真实引用,焦点系统遍历 widget 树就能算邻居;样式做成独立层(style sheet / theme),和结构解耦。这些是"打磨过的游戏 UI"必须的能力,所以商业游戏的 HUD 和菜单几乎都 retained。

代价是**机制重**:管 widget 树生命周期(创建、销毁、复用)、做 dirty tracking(哪些 widget 变了需要重 layout)、解决"状态同步"(代码状态和 widget 状态怎么一致——这正是 [ui-data-binding-short](ui-data-binding-short.md) 主题)。这些机制本身就是几千行代码。retained 的"门槛"比 immediate 高——写 immediate 的 button 是一行,写 retained 的 button 框架是一周。

结论:**调试工具、编辑器、内部面板用 immediate;面向玩家的 HUD、菜单、对话框用 retained**。这是行业事实分工,几乎每个商业引擎都同时有两套:Unreal 有 Slate 风格编辑器工具,同时有 UMG 这种 retained 给游戏 UI;Unity 有 IMGUI 给编辑器,有 UI Toolkit 给游戏;Casey 的 HH 全 immediate,因为他的"游戏 UI"极简(就一个调试覆盖),没打磨需求。

第三条路是 **hybrid**(混合):一棵 retained 的 widget 树,但在动态列表、临时浮层等地方用 immediate 的便利构建。很多现代 UI 框架其实是 hybrid——egui 内部用 retained 缓存布局,对外暴露 immediate API;React 表面"声明式"(像 immediate),底层是 retained 的 fiber 树。hybrid 不是和稀泥,它承认两种范式各有优势。HH 项目最终很可能也走 hybrid:debug UI 用 immediate,游戏 UI 用 retained,两者共享同一个渲染后端和输入源。

## 3 · 为什么游戏 UI 必须是独立子系统

理解了 immediate / retained 的取舍,下一个问题更宏观——**你的 UI 代码应该住在引擎的哪里**。如果 UI 散在 gameplay 各个角落(HUD 在 player.rs,菜单在 menu.rs,设置在 settings.rs),那不管选哪种模式都是没架构。这一节讲为什么 UI 必须是**独立子系统**(first-class subsystem),呼应 [09B-2](../../phase-9/09B-2-subsystems-modules-plugins.md) 的分层思想。

先看 UI 的"覆盖面"。UI 不是某个 gameplay 功能,它**叠加在所有 gameplay 之上**:游戏进行中画 HUD,按 ESC 弹暂停菜单,过场有字幕,加载有进度条,死亡有结算界面,设置能随时调音量。这些场景横跨你的整个 [game-state-management](../../phase-2/deep-dives/game-state-management.md)——menu、play、pause、cutscene,每个 state 都需要 UI,而 UI 必须知道"现在在哪个 state"才能正确显示。如果 UI 散在各处,你就得在每个 state 代码里重复"该画什么 UI"的逻辑——就是开头那锅粥。

UI 还有自己的**三层独立基础设施**,都不该和 gameplay 共用:

第一层是**输入层**。UI 输入和 gameplay 输入语义完全不同——gameplay 关心"玩家按了攻击键",UI 关心"焦点在哪个控件、玩家按了确认键、当前焦点控件接到事件"。UI 需要自己的焦点系统、自己的导航逻辑(上下左右在控件树里移动焦点)、自己的输入消费规则(一个 click 要么被 UI 吃掉、要么穿透到 gameplay——这决定"点 UI 上的按钮会不会同时开枪")。这部分在 [input-handling-for-games](../../phase-2/deep-dives/input-handling-for-games.md) 讲过,这里只要记住:UI 输入是独立层,不能和 gameplay 输入搅在一起。

第二层是**渲染层**。UI 几乎总是屏幕空间 2D,有自己的正交投影、自己的深度缓冲策略(永远在 3D 世界之上,但 UI 内部按 z-order 排序)、自己的批次合并(UI 的字图、九宫格图集、shader 通常和 3D 世界分开)。还要处理"屏幕分辨率适配"——同一套 UI 在 1080p 和 4K 上要正确缩放,这是 3D 渲染不操心的事。

第三层是**更新层**。UI 有自己的每帧更新:动画 tween 推进、布局重算、数据绑定刷新、焦点动画。这些和 gameplay 更新(物理、AI)是独立的循环,有自己的优先级——通常 UI 更新在 gameplay 之后(UI 反映 gameplay 结果)、渲染之前(渲染要用 UI 最终状态)。

把这三层独立出来,你就得到一个清晰的 UI 子系统。接口长这样:输入系统把这一帧原始输入喂给 UI,UI 自己消化(更新焦点、推进动画、刷新绑定),然后把这帧要画的东西提交给渲染器。gameplay 不知道 UI 存在,UI 也不知道 gameplay 细节——两者通过数据绑定(后面 §8 讲)或明确事件沟通。这就是 09B-2 讲的"分层 + 单向依赖"在 UI 上的落地。

UI 一旦成了独立子系统,那锅粥就化解:HUD、菜单、设置都注册到这个 UI 子系统,由它统一调度(哪个该显示、哪个该响应输入、哪个画在哪个之上)。新增一个 screen,你只是往 UI 子系统加一个 widget 子树,不动其他代码。

## 4 · 一个最小的 UI 子系统长什么样

讲了这么多"应该怎么样",这一节给你看一个能跑的骨架。用 Rust 写一个最小的 retained-mode UI 子系统,你能看到 widget 树、事件路由、focus、数据绑定怎么拼起来。后面章节逐个展开,这里先给全景。

先定义核心——widget。一个 widget 是树里的一个节点,有样式、布局提示、子节点、事件处理钩子。

```rust
/// 一个 widget 的唯一标识,用于 focus、数据绑定、动画状态索引
#[derive(Clone, Copy, Debug, Hash, PartialEq, Eq)]
pub struct WidgetId(u64);

/// widget 的样式(简化版,完整版在第三篇讲)
#[derive(Clone, Debug, Default)]
pub struct Style {
    pub bg_color: Option<[f32; 4]>,
    pub text_color: Option<[f32; 4]>,
    pub font_size: Option<f32>,
    pub padding: Option<f32>,
}

/// 布局提示:告诉布局引擎"我想多大、怎么摆"。完整布局引擎在 ui-layout-engines
#[derive(Clone, Debug, Default)]
pub struct LayoutHints {
    pub width: Option<f32>,
    pub height: Option<f32>,
    pub margin: Option<[f32; 4]>, // top right bottom left
}

/// 事件:从输入系统路由到 widget 的离散信号
#[derive(Clone, Debug)]
pub enum UiEvent {
    Clicked { x: f32, y: f32 },
    Focused,
    Unfocused,
    GamepadNav(NavDir),
    ValueChanged(f32), // 滑块之类
}

#[derive(Clone, Copy, Debug)]
pub enum NavDir { Up, Down, Left, Right }

/// widget 的共同接口。trait object 让树里能装异构节点(Button/Panel/Text 各是不同 struct)
pub trait Widget: std::fmt::Debug {
    fn id(&self) -> WidgetId;
    fn style(&self) -> &Style;
    fn layout_hints(&self) -> &LayoutHints;
    fn children(&self) -> &[Box<dyn Widget>];
    fn handle_event(&mut self, ctx: &mut UiContext, event: &UiEvent);
    fn render(&self, ctx: &mut UiContext, rect: Rect); // 屏幕空间
}

/// 贯穿整个 UI 子系统的上下文:提供渲染器、focus、动画、数据绑定的入口
pub struct UiContext<'a> {
    pub renderer: &'a mut UiRenderer,
    pub focus: &'a mut FocusState,
    pub animations: &'a mut AnimationStore,
    pub bindings: &'a mut BindingHub,
}
```

几个关键决策值得停下讲。第一,widget 用 `Box<dyn Widget>` 装在 `children` 里——树里能装不同类型的节点(Button、Panel、Text 各是不同 struct)。trait object 有运行时开销,但 UI 节点几百到几千,这点开销可忽略,换的是树的灵活性。第二,每个 widget 有稳定 `WidgetId`——这是 focus、动画状态、数据绑定的索引键;没有稳定 ID,就没法跨帧追踪"这个 button 现在 hover 进度多少"。第三,`UiContext` 把子系统各层(renderer、focus、动画、绑定)入口打包,通过 `handle_event` / `render` 传给 widget——widget 不需要全局引用,所有依赖通过 context 显式传入(呼应 09B-2 的"依赖显式化")。

有了 widget 定义,UI 子系统的主循环长这样:

```rust
pub struct UiSubsystem {
    root: Box<dyn Widget>,
    focus: FocusState,
    animations: AnimationStore,
    bindings: BindingHub,
    renderer: UiRenderer,
    pending_events: Vec<UiEvent>, // 这一帧积攒的事件,update 阶段路由
}

impl UiSubsystem {
    /// 从输入系统喂原始输入,UI 自己翻译成 UiEvent
    pub fn ingest_input(&mut self, raw: &RawInput) {
        // 鼠标点击 → UiEvent::Clicked;手柄方向 → UiEvent::GamepadNav
        // 还涉及 hit-test(点击落在哪个 widget 上)
        for event in translate_input(raw, &self.focus, &self.root) {
            self.pending_events.push(event);
        }
    }

    /// 每帧更新:推进动画 → 路由事件 → 刷新数据绑定
    pub fn update(&mut self, dt: f32) -> bool /* event_consumed_by_ui */ {
        self.animations.tick(dt); // 1. 推进动画(focus 高亮、平滑过渡)

        // 2. 把积攒事件路由给(聚焦的 / 命中的)widget
        let mut ctx = UiContext {
            renderer: &mut self.renderer, focus: &mut self.focus,
            animations: &mut self.animations, bindings: &mut self.bindings,
        };
        for event in self.pending_events.drain(..) {
            route_event(&mut self.root, &mut ctx, &event);
        }

        self.bindings.poll_and_apply(&mut self.root); // 3. 数据绑定刷新
        self.last_frame_consumed_input
    }

    /// 渲染:布局 → 提交 draw list
    pub fn render(&mut self, screen_w: f32, screen_h: f32) {
        let root_rect = Rect::new(0.0, 0.0, screen_w, screen_h);
        let mut ctx = UiContext { /* 同上 */ };
        layout_subtree(&mut self.root, &mut ctx, root_rect); // 算法在 ui-layout-engines
        self.root.render(&mut ctx, root_rect);
    }
}
```

注意三段式:**ingest_input → update → render**,对应一帧三个阶段。`update` 里又分三步(动画、事件、绑定),顺序重要——先推进动画(本帧事件能看到动画结果),再路由事件(widget 处理事件可能改状态),最后刷数据绑定(把游戏状态新值反映到 widget)。不是教条,但是大多数 UI 框架的事实顺序,可作思考起点。`update` 返回的 `event_consumed_by_ui` 是 §5 要讲的"输入穿透"信号——告诉 gameplay 这帧 UI 是否吃掉了输入。

骨架还差几个拼图:`route_event` 怎么送事件到正确 widget(下一节)、`FocusState` 怎么管手柄导航(下下节)、`BindingHub` 怎么接游戏状态(再后面)。但骨架本身已能让你看清:UI 子系统是有清晰边界、有自己的循环和状态的独立模块——不再是散在 gameplay 里的几个函数。

## 5 · 事件路由:从输入到 widget 的旅程

现在展开一个被严重低估的话题——事件路由(event routing)。很多教程讲 UI 直接跳到"怎么画按钮",但事件路由才是 UI 子系统的真正脊梁。一个按钮画得再漂亮,click 事件送不到它手上(或送错了),UI 就是一张静态海报。

游戏 UI 的事件路由,本质是 [event-systems-and-gameplay-foundations](../../phase-5/deep-dives/event-systems-and-gameplay-foundations.md) 那套事件系统的**专门化版本**——只服务 UI,有自己的路由规则。拆成三件事讲:hit-test、bubble/tunnel、capture。

**第一件:hit-test**(命中测试)。鼠标点击进来,坐标 (x, y),要算出"这个点落在哪个 widget 上"。看起来简单——遍历 widget 树,看哪个 rect 包含这个点——但有两个细节。一是 **z-order**:同一屏幕坐标可能被多个 widget 覆盖(弹窗盖住底下按钮),要从最上层(最后画的)往最下层查,第一个命中的就是目标。二是 **不可命中**:有些 widget(透明面板、纯装饰文字)声明 `pointer_events: None`,鼠标点击应穿透它们到下面的可命中 widget。健壮的 hit-test 要处理这两件事,实现成对 widget 树的深度优先遍历(从顶层开始,先查子节点再查自己)。

```rust
/// 从顶层开始,找最深的、可命中的、rect 包含 point 的 widget
pub fn hit_test(root: &dyn Widget, point: [f32; 2], layout: &LayoutCache) -> Option<WidgetId> {
    for child in root.children().iter().rev() { // 子节点画在父之上,后画的在上
        if let Some(hit) = hit_test(child.as_ref(), point, layout) {
            return Some(hit);
        }
    }
    let rect = layout.rect_of(&root.id())?;
    if rect.contains(point) && root.is_pointer_target() {
        Some(root.id())
    } else {
        None
    }
}
```

**第二件:bubble 和 tunnel**(冒泡和隧道)。一旦知道点击命中的是 button #7,要把 `UiEvent::Clicked` 送过去。但很多时候父容器也想"知道"这个事件——一个 Panel 想拦截所有内部按钮的点击(判断"用户是否在面板里活动"),或滚动容器想在按钮处理之前先判断"这个点击是不是想拖滚动条"。这就需要事件在树里**流动**。

业界两个经典方向:**bubbling**(冒泡)从目标 widget 往上流向根——目标先处理,然后父节点,然后祖父,到根。**tunneling**(隧道)反过来,从根往下流到目标——父容器先看到,有机会拦截(返回 `handled`),然后才到目标。WPF 同时实现了这两个(叫 `Bubble` 和 `Preview` 事件)。游戏 UI 通常简化为 bubbling——目标先处理,父节点按需拦截,够用。

```rust
/// 把事件从命中目标往上冒泡,任何一层可标记 handled 截断
pub fn route_event(root: &mut Box<dyn Widget>, ctx: &mut UiContext, event: &UiEvent) {
    let path = build_path_to_root(root, ctx, event); // 目标到根的路径
    for widget_id in path {
        let widget = find_widget_mut(root, widget_id);
        widget.handle_event(ctx, event);
        if ctx.event_consumed() { break; }
    }
}
```

这里有个游戏 UI 特有的微妙点——**输入穿透**(input passthrough)。如果玩家点了 UI 按钮,这个点击不应同时触发 gameplay(比如开枪)。但如果玩家点的是 HUD 上一个透明区域,这个点击应穿透到 3D 世界。所以 UI 子系统要给 gameplay 一个明确信号:"这帧的鼠标点击我吃掉了" / "我没吃,你处理"。这是 UI 和 gameplay 输入分界的关键约定,缺了它就出现"点 UI 同时开枪"的经典 bug。

**第三件:capture**(捕获)。考虑拖动滑块:玩家在滑块上按下鼠标,然后拖动——拖动过程中鼠标可能移出滑块 rect,但滑块仍要继续接收鼠标移动事件(否则拖动断了)。这需要 capture——widget "捕获"输入后,后续鼠标事件直接送到它手上,跳过 hit-test。capture 是 UI 级状态(不是 gameplay 的),由 focus 系统管理。

```rust
pub struct FocusState {
    pub focused: Option<WidgetId>,  // 当前聚焦 widget(手柄导航和键盘确认)
    pub captured: Option<WidgetId>, // 当前捕获输入的 widget(按下没松开时)
    pub hovered: Option<WidgetId>,  // 当前 hover 的 widget(鼠标模式才有)
}
```

`focused`、`captured`、`hovered` 三个状态覆盖 UI 输入几乎所有场景:键盘和手柄走 `focused`,拖动和持续交互走 `captured`,鼠标悬停反馈走 `hovered`。事件进来,优先级通常是 `captured > focused > hovered > hit_test_new`——先看有没有 widget 抓着输入不放,再看聚焦的,再看 hover 的,最后才做新的命中测试。这个优先级是经验沉淀,记住能少踩很多坑。

事件路由讲完,你就理解了 UI 子系统的"神经"——它把离散输入信号精确送到正确 widget,沿途允许容器拦截,还处理了拖动这种"持续交互"的特殊情况。这一层做对了,后面所有 UI 控件(按钮、滑块、列表)都能在干净的基座上长出来。

## 6 · 焦点系统:手柄导航的灵魂

上一节提到 focus,这一节专门展开,因为**手柄导航是游戏 UI 区别于桌面 UI 的最大特征**,而它的核心就是焦点系统。如果这节没做好,你的游戏在手柄玩家眼里就是"菜单很难用",但又说不出哪里难用——这就是焦点系统没设计好。

为什么手柄 UI 必须有焦点?因为手柄没有"鼠标移过去"。鼠标 UI 里"哪个控件被考虑"由鼠标位置决定;手柄 UI 里"哪个控件被考虑"必须是一个**显式的、离散的状态**,这个状态就是 focus。玩家按上下方向键,focus 从当前控件移到上/下邻居;按确认键,当前 focus 的控件被激活。整个交互语义建立在 focus 之上。

focus 系统的核心数据结构是 **focus graph**(焦点图)——记录"每个控件,按上/下/左/右,分别应该 focus 到哪个控件"。理想情况下这个图从 widget 树布局自动算出(水平排列的按钮左右是邻居;垂直排列的上下是邻居),但实际游戏 UI 经常有跨容器跳转、环形菜单、网格导航,所以很多游戏会**手动指定 focus 邻居**(explicit focus neighbours),允许设计师精确控制导航体验。

```rust
/// 一个控件的焦点邻居(可手动指定,缺失时由布局自动算)
#[derive(Clone, Copy, Debug, Default)]
pub struct FocusNeighbours {
    pub up: Option<WidgetId>,
    pub down: Option<WidgetId>,
    pub left: Option<WidgetId>,
    pub right: Option<WidgetId>,
}

pub struct FocusState {
    pub focused: Option<WidgetId>,
    pub neighbours: HashMap<WidgetId, FocusNeighbours>,
    pub on_focus_changed: Option<Box<dyn FnMut(Option<WidgetId>, Option<WidgetId>)>>,
}

impl FocusState {
    /// 玩家按方向键,移动焦点
    pub fn navigate(&mut self, dir: NavDir) {
        let Some(current) = self.focused else { self.focus_first(); return; };
        let next = self.neighbours.get(&current)
            .and_then(|n| match dir {
                NavDir::Up => n.up, NavDir::Down => n.down,
                NavDir::Left => n.left, NavDir::Right => n.right,
            });
        if let Some(next_id) = next {
            let prev = self.focused;
            self.focused = Some(next_id);
            if let Some(cb) = self.on_focus_changed.as_mut() { cb(prev, self.focused); }
        }
    }
}
```

焦点系统有几个游戏 UI 特有的坑要避免。

第一个坑:**进入和退出 UI 的焦点管理**。玩家在玩游戏(手柄控制角色),按键打开菜单——手柄输入语义从"控制角色"切到"控制 UI",focus 必须立刻移到菜单的第一个可聚焦控件。如果 focus 没设好,玩家按方向键什么也不发生,以为游戏卡了。反过来关闭菜单时 focus 要"还给"游戏。这个切换是 UI 子系统和 gameplay 输入的边界,要显式管理,不能靠运气。

第二个坑:**focus 环**。环形菜单(武器轮盘、表情轮盘)按右绕一圈应回到起点;列表最后一项按"下"应停住(或绕回第一项,看设计)。这些是设计师选择,你的 focus 系统要能表达——所以 `FocusNeighbours` 是个图,不是树,允许环。

第三个坑:**focus 的可视化**。当前 focus 的控件必须有**清晰高亮**(边框、缩放、底色),否则玩家不知道"我现在选哪个"。这个高亮通常还要带动画(focus 切换时柔和过渡),所以 focus 系统要和动画系统协作——focus 变化时触发一个 tween,而不是瞬切。这个细节是"打磨过"和"没打磨"的分水岭。

第四个坑,也最重要——**输入冲突**。当 UI 显示时 gameplay 还在跑(比如 HUD 总在但游戏在玩),手柄方向键同时被 UI 和 gameplay 需要。规则通常是:**UI 在前台(菜单、暂停)时,gameplay 不接收导航输入;HUD 在但菜单没开时,导航输入归 gameplay**。这个规则由一个"UI 是否捕获导航"的标志位表达,UI 子系统每帧告诉输入层"我这帧要不要导航输入"。这就是 [input-handling-for-games](../../phase-2/deep-dives/input-handling-for-games.md) 里讲的"输入分层"在 UI 上的具体化。

focus 系统做好了,你的游戏在手柄玩家眼里就是"菜单好用"。它是看不见的工程——玩家不知道你做了什么,但少了它玩家会立刻觉得别扭。这种"不做就被骂、做了不被察觉"的基础设施,正是 UI 子系统的典型工作。

## 7 · widget 树的构建与生命周期

讲了事件和 focus,这一节回头看 widget 树本身——怎么构建、更新、销毁。这是 retained mode 的核心机制,理解了它你才算真懂 retained。

retained mode 的"retained"体现在——**树持续存在,你改它而不是重建它**。这看起来简单,但牵涉一个关键问题:你什么时候构建树、什么时候改树?

两种风格。第一种是**一次性构建 + 增量修改**:游戏启动时构建好整棵 UI 树(主菜单、HUD、设置面板都先建好,设置面板默认隐藏),运行时只改属性(`panel.visible = true`、`button.label = "Resume"`、`health_bar.value = 0.7`)。简单、性能好(树结构不变,只改值),适合 UI 结构固定的游戏。缺点是动态内容(背包物品列表)不好处理——物品数量变化时你要手动加/删子节点。

第二种是**声明式重建**(react-style):每帧(或每次状态变化)从"状态"重新生成 widget 树描述,系统对比新旧树,只对差异部分做修改。这是 React diff 算法的精神,也是 iced、egui 内部的做法。好处是**动态内容天然支持**——你只描述"当前状态对应的 UI 应该长什么样",增删节点系统自动处理。代价是 diff 有计算开销,且实现复杂(要解决 widget 身份、状态保留等难题)。

游戏 UI 通常是**混合**——结构固定的部分(主菜单骨架、HUD 框架)用一次性构建,动态列表部分用声明式重建。你不需要全栈声明式(那个工程量很大),只要在动态区域(列表、网格)实现一个轻量的 diff 即可。

```rust
/// 动态列表容器:每帧根据数据重建子节点,用 ID 复用旧节点(保留动画/状态)
pub fn rebuild_list(list: &mut ListWidget, items: &[ListItemData], ctx: &mut UiContext) {
    let mut new_children: Vec<Box<dyn Widget>> = Vec::with_capacity(items.len());
    for item in items {
        let id = WidgetId(item.stable_id); // 用数据的稳定 ID,不用下标
        if let Some(mut existing) = list.take_child(id) {
            existing.update_data(item, ctx); // 复用:只更新数据,保留动画进度/hover 状态
            new_children.push(existing);
        } else {
            let mut w = build_item_widget(id, item); // 新增:创建并触发入场动画
            ctx.animations.start(id, Anim::FadeIn { duration: 0.15 });
            new_children.push(w);
        }
    }
    list.children = new_children; // 消失的子节点被丢弃
}
```

注意关键细节——动态列表用**数据的稳定 ID** 作为 widget ID,而不是数组下标。如果用下标,列表中间插入元素时后面所有元素下标都变了,它们的 widget 身份就乱了(动画状态、focus 都会错位)。稳定 ID 让"同一个逻辑元素"在数据变化前后对应同一个 widget,这是声明式 UI 的根基。React 的 `key`、Vue 的 `:key`、egui 的 `ui.push_id` 都是同一个道理。

生命周期还有一类问题:**widget 销毁时机**。一个面板被关闭(`visible = false`),它的子树是销毁还是只是不画?销毁的话,如果里面有未完成的动画、未保存的输入,会丢;不销毁的话,内存累积。游戏 UI 通常**池化**(pooling)——隐藏的 widget 不销毁,放进池子,下次需要同类 widget 时从池子取出复用。这避免频繁分配,也保留了状态。和 3D 渲染里的对象池是同一个思想。

widget 树这一节看起来琐碎,但它是 retained mode "持久状态"从哪来的答案。immediate mode 没这个问题(每帧重建),retained mode 的全部复杂性集中在这里——树的构建、更新、身份、销毁。把这些想清楚,你才算真懂 retained。

## 8 · 数据绑定:游戏状态和 UI 的桥

最后一节讲数据绑定,它是 UI 子系统和 gameplay 之间的桥。呼应 [ui-data-binding-short](ui-data-binding-short.md),那里讲"为什么 immediate mode 手动同步会失控",这里从架构角度补全"一个完整绑定层怎么设计"。

问题本质:游戏有一个**权威状态**(authoritative state)——玩家血量、弹药、当前关卡、得分。UI 要**反映**这个状态——血条、弹药数、关卡名、得分板。两边同步,就是数据绑定。

最朴素的做法是**命令式手动同步**——gameplay 每次改了血量,顺手调一句 `hud.health_bar.set_value(new_health)`。UI 简单时没问题,但有两个越来越严重的问题。一是**耦合**:gameplay 必须知道 UI 存在、知道 UI 有哪些控件,这让 gameplay 没法脱离 UI 测试或复用。二是**遗漏**:gameplay 改了血量但忘了调 UI(或调错控件),UI 就和真实状态不一致,这种 bug 极难发现。

**声明式数据绑定**(declarative data binding)是解法。核心思想:**UI 不被 gameplay 直接操作,而是订阅(subscribe)它关心的状态;状态变了,UI 自动收到通知并更新**。这样 gameplay 不知道 UI 存在(只管改自己的状态),UI 也不知道 gameplay 细节(只管订阅关心的字段)。两边通过**绑定中枢**(binding hub)解耦。

```rust
/// 一个可观察的状态单元:UI 订阅它,值变化时通知所有订阅者
pub struct Observable<T: Clone + PartialEq> {
    value: T,
    subscribers: Vec<Box<dyn FnMut(&T) + 'static>>,
}

impl<T: Clone + PartialEq> Observable<T> {
    pub fn new(value: T) -> Self { Self { value, subscribers: Vec::new() } }
    /// gameplay 写:值真的变了才通知
    pub fn set(&mut self, new_value: T) {
        if self.value != new_value {
            self.value = new_value.clone();
            for sub in &mut self.subscribers { sub(&self.value); }
        }
    }
    /// UI 读 + 订阅:订阅者在值变化时被调用
    pub fn subscribe(&mut self, callback: impl FnMut(&T) + 'static) {
        callback(&self.value); // 立即调一次,让 UI 拿到当前值
        self.subscribers.push(Box::new(callback));
    }
}

/// 游戏状态:用 Observable 包装需要被 UI 监听的字段
pub struct GameState {
    pub health: Observable<f32>,
    pub ammo: Observable<u32>,
    pub score: Observable<u64>,
}

/// UI 子系统启动时,把 widget 绑定到 state
pub fn bind_hud(hud: &mut HudWidgets, state: &mut GameState) {
    let bar = hud.health_bar.handle();
    state.health.subscribe(move |&h| { bar.set_value(h); });
    // 类似绑弹药、得分
}
```

这段展示了一个最小但完整的绑定层。几个要点:**gameplay 只管 `state.health.set(...)`**,不关心 UI;**UI 只管 subscribe**,不关心 gameplay;**Observable 自动去重**(值没变不通知),避免无谓刷新;**订阅时立即调一次**,让 UI 拿到初始值。这套机制让 gameplay 和 UI 彻底解耦——gameplay 可单独测试(没有 UI),UI 也可单独测试(喂模拟 state)。

数据绑定还有一个游戏 UI 特有的考量——**性能**。一个 Observable 每次 set 都遍历所有订阅者,如果某帧有大量状态变化(炸弹伤害 100 个敌人,触发 100 个血量更新),订阅者回调可能一帧内被调很多次,而 UI 实际只需最终值。所以职业实现会用**批量通知**——一帧内 set 多次只通知一次(用 dirty flag),或**延迟到 UI update 阶段**统一应用。这是 ui-data-binding-short 那篇讲的"批量刷新"思想,UI 控件超过几百个时变得重要。

数据绑定的极端形式是**响应式 UI**(reactive UI),整个 UI 树都从状态自动派生,UI 代码完全不命令式操作控件。React、Elm、iced 是这个方向代表。游戏 UI 通常不做这么极端,但会在"高度数据驱动"部分(血条、计分板、背包)用响应式,在"高度交互"部分(菜单、设置)用命令式。这种务实混合是职业做法。

## 9 · 在你 HH 项目里动手(做中学红线)

这一篇的做中学,是把 HH 项目的 UI 从"散装"重构成"子系统"。中等规模重构,可能花几个晚上,但回报巨大——以后每加一个 UI 界面,都站在干净的基座上。建议分几步,每步验证。

**第一步:建立 UI 子系统的骨架。** 新建 `ui/` 模块,把第 4 节的 `UiSubsystem`、`Widget` trait、`UiContext`、`Style`、`LayoutHints`、`UiEvent` 落进去。先不用完美,能编译跑通一个空 UI 子系统即可。主循环改一下:gameplay update 之后、render 之前调 `ui.update(dt)`;render 末尾调 `ui.render(screen_w, screen_h)`。这一步把"UI 有自己的更新和渲染阶段"这个结构立起来。

**第二步:实现三个最基本的 widget——Panel、Text、Button。** 用这三个能搭出大多数界面。Button 要支持 click(走 §5 事件路由),要有 hover/focused 两种状态样式切换(哪怕只是颜色变化)。这一步你会第一次感受到 retained 的"对象持续存在"——给 button 改 label,下一帧真的变了,不用每帧重画。

```rust
#[derive(Debug)]
pub struct Button {
    id: WidgetId,
    label: String,
    style: Style,
    layout: LayoutHints,
    on_click: Option<Box<dyn FnMut(&mut UiContext)>>,
}

impl Button {
    pub fn new(id: WidgetId, label: impl Into<String>) -> Self {
        Self {
            id, label: label.into(), style: Style::default(),
            layout: LayoutHints { width: Some(120.0), height: Some(36.0), ..Default::default() },
            on_click: None,
        }
    }
    pub fn on_click(mut self, f: impl FnMut(&mut UiContext) + 'static) -> Self {
        self.on_click = Some(Box::new(f)); self
    }
}

impl Widget for Button {
    fn id(&self) -> WidgetId { self.id }
    fn style(&self) -> &Style { &self.style }
    fn layout_hints(&self) -> &LayoutHints { &self.layout }
    fn children(&self) -> &[Box<dyn Widget>] { &[] }
    fn handle_event(&mut self, ctx: &mut UiContext, event: &UiEvent) {
        if let UiEvent::Clicked { .. } = event {
            if let Some(f) = self.on_click.as_mut() { f(ctx); }
            ctx.consume_event(); // 冒泡截断
        }
    }
    fn render(&self, ctx: &mut UiContext, rect: Rect) {
        let is_focused = ctx.focus.focused == Some(self.id);
        let is_hovered = ctx.focus.hovered == Some(self.id);
        let bg = if is_focused { [0.3, 0.6, 1.0, 1.0] }
                 else if is_hovered { [0.4, 0.4, 0.45, 1.0] }
                 else { [0.25, 0.25, 0.3, 1.0] };
        ctx.renderer.draw_nine_slice(rect, bg);
        ctx.renderer.draw_text(&self.label, rect.center());
    }
}
```

**第三步:实现一个最小的 focus 系统。** 落地第 6 节的 `FocusState`,先只支持手柄方向键导航(上下左右)和确认键。把按钮们注册进 focus 图(用布局自动算邻居:水平排列的互为左右,垂直排列的互为上下)。验证:用手柄在主菜单按钮间导航,focus 高亮跟着移动,确认键能触发按钮。

**第四步:实现一个最小的数据绑定。** 落地第 8 节的 `Observable<T>`,把游戏的"血量"和"弹药"用 `Observable` 包装。建一个 HUD 子树(血条 widget、文字 widget),订阅这两个 Observable。验证:改游戏里的血量,HUD 血条自动跟着变,gameplay 代码完全不出现 `hud.health_bar` 这样的引用。

**第五步:对比 immediate debug UI。** 保留之前的 egui / ImGui 调试 UI(不要删,它有它的价值),让游戏同时跑两套——immediate 调试 UI(retained 之外)和 retained 游戏 UI。观察差异:调试 UI 每帧重画、改代码立刻生效;游戏 UI 持久存在、动画平滑、手柄导航顺滑。这种并置会让你**亲身感受**两种范式各自的甜点。

做完这五步,HH 项目就有了第一个真正的 UI 子系统。后面 [ui-layout-engines](ui-layout-engines.md) 会在这个骨架上把布局算法补全(现在用的还是固定坐标),第三篇会把样式系统、动画、九宫格这些打磨细节补上。这个子系统会一路陪你到 capstone。

## 10 · 练习

**练习一(概念,Lv1)。** 用一段话(不超过 200 字)解释:为什么 immediate-mode UI 适合调试工具、不适合面向玩家的游戏 UI?从动画、手柄导航、样式系统三个角度各给一个具体理由。这个练习检验你是否真的理解第 2 节的核心 trade-off,而不只是记住"immediate 给工具用"这个结论。

**练习二(动手,Lv2)。** 完成第 9 节第一步和第二步——建好 UI 子系统骨架,实现 Panel、Text、Button,在屏幕上画出一个静态主菜单(三个按钮:"New Game"、"Load"、"Quit")。验证:鼠标点击按钮能触发事件、回调能跑通。提交 commit,在 commit message 贴一张截图。

**练习三(动手 + 设计,Lv3)。** 在练习二基础上加 focus 系统,让主菜单支持手柄导航。挑战点:实现 focus 切换时的**柔和高亮动画**(用 `AnimationStore` 跑 0.15 秒颜色 tween,而不是瞬切)。再实现一个细节——按 ESC 从游戏切到菜单时 focus 自动落到"New Game";再按 ESC 或选"Quit",focus 还给游戏。这个练习逼你处理 focus 系统所有现实细节,做完你的菜单就有了商业游戏的手感。

**练习四(进阶,Lv4)。** 把 HH 项目的某个 dynamic 列表(背包、关卡选择、武器轮盘任选)用第 7 节的"声明式重建 + 稳定 ID"实现。关键验证:列表中间插入元素时,focus 不跳错位置、入场动画正确播放、元素状态(选中标记)保留。然后写一段反思:为什么用下标做 ID 会出问题?用稳定 ID 解决了什么本质问题?这个练习让你亲手实现 React/egui 的核心 diff 思想,理解为什么所有现代 UI 框架都要解决"元素身份"这件事。

## 11 · 延伸阅读与下一篇

这一篇讲 UI 子系统的**架构骨架**——widget 树、事件路由、focus、数据绑定。这些概念在桌面 UI 领域有大量经典文献,因为游戏 UI 架构思想很多是从桌面 UI 借来的。想往深里挖,WPF 的《Programming WPF》by Chris Sells 讲 dependency property 和 routed event,是第 5、6 节的祖师爷;React 官方文档"Reconciliation"那一章,把第 7 节的"声明式重建"讲得最透彻;Elm 文档把第 8 节"响应式绑定"的纯粹形式展示出来。游戏方向,Jason Gregory《Game Engine Architecture》第三版"Gameplay Foundations"那章有几节专门讲 Naughty Dog 怎么组织游戏 UI 子系统,值得对照读。

框架源码方面,Bevy UI(`crates/bevy_ui/`)是 Rust 生态最值得读的 retained UI 实现——`NodeBundle`、`Interaction`、`FocusPolicy` 几乎一一对应这一篇的 widget、event、focus。Godot 的 `Control` 节点体系(Control、Container、Theme)是另一个完整参考,文档对 focus 和导航讲得特别清楚。Unreal 的 UMG 偏 C++ 重一些,但 `UWidget`、`UPanelWidget` 类层次是 AAA 引擎 UI 架构的范例——你会发现它的设计思想和这一篇一模一样,只是规模和细节更庞大。

想知道"为什么 immediate mode 赢了游戏工具"的另一半故事,回头读 [immediate-mode-ui](../../phase-5/deep-dives/immediate-mode-ui.md)——那篇讲 immediate 实现细节,和这一篇的 retained 形成完整对照。想深入数据绑定,读 [ui-data-binding-short](ui-data-binding-short.md),那里讲了更细的批量刷新、脏标记、响应式模式。focus 和输入的更广背景在 [input-handling-for-games](../../phase-2/deep-dives/input-handling-for-games.md),gameplay 事件系统在 [event-systems-and-gameplay-foundations](../../phase-5/deep-dives/event-systems-and-gameplay-foundations.md)。UI 无障碍(a11y)和 focus 系统紧密相关——好的 focus 系统是 a11y 的基础,读 [accessibility-short](accessibility-short.md) 和 [localization-short](localization-short.md) 把 UI 子系统的"对所有人可用"补全。后面 [hud-and-menu-systems](hud-and-menu-systems.md) 会专门讲 HUD 和菜单的设计模式,站在这一篇的架构之上。

下一篇 [ui-layout-engines](ui-layout-engines.md) 是这个三联的**第二篇**——布局引擎。这一篇用了固定坐标和简单的水平/垂直排列,但真正的 UI 需要流式布局、约束求解、容器嵌套、文本换行、滚动裁剪。布局引擎是 UI 子系统里数学最密集、也最容易写错的部分,下一篇会把核心算法(rect-packing、cassowary 约束求解、flexbox)讲透。读完它,你的 UI 子系统就有了真正能用的布局能力,不再需要给每个控件手填坐标。
