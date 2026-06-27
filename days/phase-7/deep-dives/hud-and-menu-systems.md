---
phase: 7
type: deep-dive
title_en: "HUD, Menus, Settings & Focus Navigation"
title_zh: "HUD、菜单、设置与焦点导航(T7 游戏 UI 深度 part 3/3 收官)"
difficulty: 4
duration: "5h"
domains: [game, rust, ui, gameplay]
prereqs: [ui-layout-engines, game-ui-architecture]
calibration: "HUD/菜单/设置/背包屏 工程模式 + UI 动画/过渡 + 焦点导航"
---

# 深入:HUD、菜单、设置与焦点导航(T7 游戏 UI 深度 part 3/3 收官)

> Part 1(`game-ui-architecture`)你把 UI 架构立了起来——UI 子系统、widget 树、与游戏循环的耦合点。Part 2(`ui-layout-engines`)你解决了"窗口 1080p 还是 4K,UI 都摆得对"——布局引擎、约束求解。
>
> 但玩家真正看见的不是"架构",也不是"布局算法"。玩家看见的是:左上角血条、按 ESC 弹出的暂停菜单、点开齿轮后的视频设置、按 I 切换出来的背包。**这些是游戏交付给玩家的具体屏幕**。每一类都有自己的工程模式和最容易踩的坑。
>
> 这一篇是 T7 游戏 UI 深度序列的收官。我们逐一拆开四种 canonical 屏幕类型(HUD、菜单、设置、背包),讲清让 UI "感觉好"的动画与过渡,讲清让 UI "用手柄能玩"的焦点导航,最后把整条 UI 序列从架构到布局到具体屏幕串成一条线。
>
> **读完这一篇你能**:
> - 写一个不挡核心玩法的 HUD,并把它数据绑定到游戏状态
> - 用状态栈实现主菜单 / 暂停 / 游戏结束,不必引入"特殊标志位"
> - 把设置屏幕做成"CVar 编辑器",视频 / 音频 / 输入 / 无障碍全部 live-bind
> - 写一个能在鼠标和手柄间无缝切换的焦点系统,做到"拔掉鼠标也能玩"
> - 给 UI 加上克制但专业的过渡动画,让菜单"感觉贵"

## 0 · 一个真实的"UI 上线前夜"

假设今天是 HH 项目发布前两天。你做完所有玩法,跑通渲染和音频,打开游戏想录个发售预告片,然后你发现:

主菜单按方向键没反应,得用鼠标点。点 Start 进游戏,血条画在屏幕正中央挡住了角色。按 ESC 暂停,菜单"啪"地一下弹出来,没有动画,像 1995 年的 Windows 对话框。打开设置,音量滑块拖一下不会实时出声,要点 Apply 才生效。切到手柄,发现 Start 按钮没法用手柄选中——focus order 跳过了它。

**这些都不是"功能 bug"——功能都"做了"。这些是 UI 工程的最后一公里**。架构成型了,布局对了,但屏幕类型、过渡手感、焦点系统没打磨,玩家会觉得这个游戏"廉价"。UI 是玩家接触游戏的第一面和最后一面——main menu 是第一印象,game-over 是离场体验,**这两屏的质感定义了玩家对整个游戏的判断**。

## 1 · HUD:永远在玩家眼角的那个层

HUD(heads-up display,抬头显示)是游戏运行期间**常驻**的 UI 覆盖层——血量、弹药、小地图、目标标记、技能冷却。它的工程定位很特殊:**HUD 是游戏循环里每帧都渲染、但绝对不能挡核心玩法的那个层**。

最关键的一条准则:**永远不要遮挡屏幕中央**。玩家在屏幕中央看的是角色、准星、敌人、目标。血条放左上,弹药放右下,小地图放右上,目标标记是世界空间的(投影到 3D 目标上)。这听起来像废话,但 AAA 项目都翻过车——《命运 2》(Destiny 2)某个版本把活动进度条放在准星正下方,玩家瞄准时被挡视野,社区炸锅,一周内热修。

第二准则:**少即是多**(clean HUD / diegetic HUD 哲学)。一个杂乱的 HUD 比稀疏的更糟——玩家不知道该看哪里,认知负荷飙升。**Destiny** 是 clean HUD 的典范:平时屏幕上只有血条和弹药,其他信息只在按住 Tab 时短暂浮现。**Death Stranding** 把 HUD 推到 diegetic(叙事内)——信息显示在山姆手腕的设备上,不是"屏幕上的图标",而是"世界里的物体"。这种设计让 HUD 不再是 UI,而是世界的一部分。

第三准则:**idle 时淡出**(fade non-essential elements when idle)。血条满且没受伤时,慢慢淡到 30% 透明度;弹药不动 5 秒后淡出。**Splatoon** 是教科书——它的 ink 量条在稳定输出时几乎不可见,只在低 ink 警告时高亮。

工程上,HUD 的核心是**数据绑定**(见 `ui-data-binding-short`)。HUD 不应自己持有血量数字,它应订阅 player state,state 一变 HUD 自动更新。这是 immediate mode UI 的天然优势——每帧重画时直接读 state,UI 和状态永远不会脱节。

看 HH 的 HUD 实现:

```rust
// hud.rs
pub struct Hud {
    // HUD 只持有"显示状态",不持有"游戏数据"
    hp_flash_t: f32,        // 受伤时血条闪红的动画剩余秒数
    idle_since: f32,        // 距离上次受伤 / 开火多久(秒)
}

impl Hud {
    pub fn update(&mut self, dt: f32, state: &GameState) {
        let (now, last_damaged, last_fired) = state.read(|s|
            (s.time, s.player.last_damaged_at, s.player.last_fired_at));

        if (now - last_damaged).abs() < 0.05 { self.hp_flash_t = 0.4; self.idle_since = 0.0; }
        if (now - last_fired).abs()   < 0.05 { self.idle_since = 0.0; }
        else                              { self.idle_since += dt; }

        self.hp_flash_t = (self.hp_flash_t - dt).max(0.0);
    }

    pub fn draw(&self, ctx: &mut UiCtx, state: &GameState, layout: &LayoutEngine) {
        // 1. 用布局引擎钉到左上角(不在中央)
        let hp_rect = layout.anchor(LayoutAnchor::TopLeft, Margin::new(24., 24., 240., 16.));

        // 2. idle 时降低不透明度(关键:不挡玩法)
        let alpha = if self.idle_since < 3.0 { 1.0 }
                    else { (1.0 - (self.idle_since - 3.0) * 0.5).max(0.3) };

        let (hp, max_hp) = state.read(|s| (s.player.hp, s.player.max_hp));
        ctx.push_alpha(alpha);
        self.draw_bar(hp_rect, hp as f32 / max_hp as f32, Color::RED,
                      flash: self.hp_flash_t / 0.4);
        ctx.pop_alpha();
    }
}
```

注意:**HUD 不持久化 hp**,每帧从 state 读;**HUD 持有"动画时间"这种纯 UI 状态**,因为闪烁、淡出是显示层的概念,不属于游戏逻辑;**alpha 通过 `push_alpha` 作用域化**,不污染后续 draw。

常见反模式:**HUD 自己持有 hp 副本,通过事件同步**。这种写法在大项目会出"UI 显示 50 血,实际已经 30 血"的脱节 bug。**事件驱动的 UI 同步在直接读 state 面前是反模式**——除非 HUD 跑在另一个进程(网络多人),否则直接读 state 比发事件更可靠。

## 2 · 菜单:玩家接触游戏的第一面和最后一面

菜单是游戏里**最被低估的复杂度**。看起来"不就是一个按钮列表",但 main menu、pause menu、game-over 是玩家最高频接触的三屏,**这三屏的质量等于玩家对游戏品质的直觉判断**。

菜单的本质是**聚焦交互(focused interaction)**:屏幕中央一个选项列表,当前选中项高亮,up/down 移动 focus,confirm 确认,cancel 返回。这套模型在键盘、手柄、鼠标上**都应该一致工作**——这是本文后半段焦点导航的重点。

工程上,菜单的关键是**和状态栈(state stack)的整合**(见 `game-state-management`)。新手段是写一堆 bool:`bool in_main_menu; bool in_pause_menu;`——然后 update 函数里全是 `if in_main_menu && !in_pause_menu { ... }`。这种代码在状态叠加时(暂停菜单里打开设置)迅速崩溃。**正确做法是状态栈**:

```rust
// state.rs
pub enum Screen { MainMenu, InGame, PauseMenu, Settings { tab: SettingsTab }, Inventory, GameOver { score: u32 } }

pub struct GameState {
    /// 栈顶是当前活动 screen。[InGame, PauseMenu] 表示游戏中按 ESC 弹暂停菜单——
    /// InGame 仍渲染(暂停菜单半透明叠在上面),PauseMenu 接收输入。
    screen_stack: Vec<Screen>,
}

impl GameState {
    pub fn toggle_pause(&mut self) {
        match self.screen_stack.last() {
            Some(Screen::InGame)    => self.screen_stack.push(Screen::PauseMenu),
            Some(Screen::PauseMenu) => { self.screen_stack.pop(); }
            _ => {}
        }
    }
}
```

威力:**新加一个屏幕只要往栈里 push 一种新 Screen**。暂停菜单里点 Settings,push `Screen::Settings`,Settings 出来 cancel,pop 回 PauseMenu——零特殊代码。游戏循环按栈顶决定 update / draw 谁:

```rust
fn update(state: &mut GameState, input: &Input, dt: f32) {
    match state.screen_stack.last() {
        Some(Screen::InGame)      => game_world::update(state, input, dt),
        Some(Screen::PauseMenu)   => pause_menu::update(state, input),  // InGame 不 update = 真暂停
        Some(Screen::MainMenu)    => main_menu::update(state, input),
        _ => {}
    }
}
```

这是真暂停(true pause)的实现——InGame 在 PauseMenu 栈下时**完全不接收 update**,世界冻结。这种暂停是单机游戏的无障碍要求(见 `accessibility-short`)。

最后,**菜单要打磨**(polish matters)。玩家每次按 ESC 都看暂停菜单,这个屏的视觉品质会被反复审视。**菜单的打磨成本远低于玩法,但回报极高**——它是性价比最高的"显贵"工作。HUD 用 immediate 没问题(无动画、无 focus),菜单用 retained 加层状态最舒服——这种"按屏幕类型混合 immediate / retained"是工业级 UI 子系统的常态(见 `immediate-mode-editor`)。

## 3 · 设置屏幕:被严重低估的工程复杂度

设置屏幕(settings screen)是游戏 UI 里**最容易被低估**的一屏。看起来就是一堆滑块和开关,实际上它是整个游戏配置系统的前端——视频、音频、输入、无障碍、语言,每一项都映射到一个 **CVar**(configuration variable,配置变量)。理解设置屏的最高抽象:**设置屏本质上是一个 CVar 编辑器**。

你有一堆全局配置变量(`r.vsync`、`s.volume_master`、`i.key_jump`、`a.colorblind_mode`),设置屏的工作就是把每个 CVar 绑定到一个 widget(滑块、开关、下拉、按键选择器),让玩家改,改完实时生效。**Easy to underbuild, very visible when wrong**——你以为设置屏是个杂活,上线那天社区会发帖:"为什么改音量要点 Apply?为什么色盲模式藏在高级里?"

先定义简化的 CVar 系统:

```rust
// cvar.rs
#[derive(Clone)]
pub enum CVarValue { Float(f32), Bool(bool), Enum(String) }

pub struct CVar {
    pub name: &'static str,
    pub value: CVarValue,
    pub on_change: Option<fn(&CVarValue)>,  // live-apply 回调
    pub needs_restart: bool,
}

pub struct CVarRegistry { vars: Arc<RwLock<HashMap<&'static str, CVar>>> }

impl CVarRegistry {
    pub fn set(&self, name: &str, value: CVarValue) {
        if let Some(c) = self.vars.write().get_mut(name) {
            c.value = value.clone();
            if let Some(apply) = c.on_change { apply(&value); }  // live-apply,不要 Apply 按钮
        }
    }
    pub fn get(&self, name: &str) -> Option<CVarValue> {
        self.vars.read().get(name).map(|c| c.value.clone())
    }
}
```

`on_change` 是设置屏体验的灵魂——**用户改了滑块,效果立刻发生,不要 Apply 按钮**。"Apply 才生效"是 90 年代 Windows 控制面板的遗毒,在游戏里不可接受。唯一例外是 `needs_restart: true` 的 CVar(某些图形 API 设置要重启),要在 widget 旁明确标 "Requires restart"。

设置屏代码本身极薄——它只做"取 CVar → 画 widget → 写回 CVar":

```rust
// settings_screen.rs
fn draw_video(ctx: &mut UiCtx, reg: &CVarRegistry, focus: &mut FocusState) {
    // 分辨率:Enum,widget = 下拉框
    let cur = match reg.get("r.resolution").unwrap() { CVarValue::Enum(s) => s, _ => String::new() };
    let opts = ["1280x720", "1920x1080", "2560x1440", "3840x2160"];
    let new = ctx.dropdown("Resolution", &opts, &cur, focus);
    if new != cur { reg.set("r.resolution", CVarValue::Enum(new.into())); }

    // FOV:Float,widget = 滑块
    let fov = reg.get("r.fov").and_then(|v| match v { CVarValue::Float(f) => Some(f), _ => None }).unwrap_or(90.0);
    let nf = ctx.slider("Field of View", 70.0..=110.0, fov, focus);
    if (nf - fov).abs() > 0.01 { reg.set("r.fov", CVarValue::Float(nf)); }
}
```

加一项设置只要:在 registry 注册一个 CVar + 在对应 tab 加三行 widget 代码,**不需要碰任何业务逻辑文件**。

无障碍(见 `accessibility-short`)和本地化(见 `localization-short`)选项天然属于设置屏。`a.colorblind_mode`、`a.ui_scale`、`a.subtitle_size`、`l.language` 都是 CVar。**不要把 a11y 选项藏在"高级"里**——Naughty Dog 公开过数据,把 a11y 放在主设置一级 tab,使用率提高数倍。

反模式:**硬编码设置 UI**:`if fullscreen_btn.clicked { config.fullscreen = !config.fullscreen; renderer.set_fullscreen(...); }`。这种写法把 UI、配置、渲染耦合在一个 if 里——加一项设置改三处。**CVar 系统是配置层的解耦**,UI 只读写 CVar,CVar 自己知道怎么 apply。

## 4 · 背包与角色屏:状态最重的 UI

背包屏(inventory screen)和角色屏(character screen)是游戏里**状态最重**的 UI——核心数据(物品、装备、属性)随时在变,UI 必须实时反映。复杂度全部来自两件事:**选择 / 光标的状态管理**,和**鼠标拖放 vs 手柄光标的两套交互**。

工程上,背包屏持有两类状态:**UI 临时状态**(选中 slot、拖拽中的 item、tooltip),和**游戏状态**(inventory 内容,属于 GameState)。前者放 UI 子系统,后者通过数据绑定读。

```rust
// inventory_screen.rs
pub struct InventoryScreen {
    cursor: (usize, usize),        // 手柄光标位置 (row, col)
    selected: Option<usize>,       // 鼠标点击 / 手柄 confirm 选中的 slot
    dragging: Option<usize>,       // 鼠标拖拽中的 slot
    tooltip_for: Option<usize>,
    grid_cols: usize,
}

impl InventoryScreen {
    pub fn update(&mut self, state: &GameState, input: &Input) -> InventoryAction {
        // 手柄光标移动(关键:focus 系统)
        if input.gp_up    { self.cursor.0 = self.cursor.0.saturating_sub(1); }
        if input.gp_down  { self.cursor.0 += 1; }
        if input.gp_left  { self.cursor.1 = self.cursor.1.saturating_sub(1); }
        if input.gp_right { self.cursor.1 += 1; }
        let cursor_idx = self.cursor.0 * self.grid_cols + self.cursor.1;

        // 手柄 confirm:第一次选,第二次 swap(A→B = A B 交换)
        if input.gp_confirm {
            if let Some(a) = self.selected {
                return InventoryAction::Swap { a, b: cursor_idx };
            }
            self.selected = Some(cursor_idx);
        }

        // tooltip 跟随当前活跃输入设备(见 input-handling-for-games)
        self.tooltip_for = if input.is_gamepad_active() { Some(cursor_idx) }
                           else { self.slot_at(input.mouse_x, input.mouse_y) };
        InventoryAction::None
    }
}
```

工程要点:**手柄和鼠标各自有独立的"选择"概念**(鼠标 hover + click,手柄 cursor + confirm),两套并存互不干扰;**Swap 用统一的 InventoryAction 出口**,无论鼠标拖还是手柄双 confirm,落到游戏逻辑的都是同一个 enum 变体,游戏逻辑不关心来源。复杂度不可消除,但**清晰的状态分层让复杂度可管理**:UI 临时状态归 InventoryScreen,游戏状态归 GameState,行为归 InventoryAction。任何背包 bug 都能定位到这三层之一。

## 5 · UI 动画与过渡:让 UI "感觉贵"的那 100ms

到现在讲的屏幕都"功能正确"——HUD 显示血量,菜单能选,设置改了生效。但**功能正确不等于感觉好**。一个"啪"地瞬间出现的暂停菜单感觉廉价;一个微微缩放 + 淡入的暂停菜单感觉精致。UI 动画不是装饰,是**质感信号**。

UI 动画分两类:**widget 入场动画**(单个 widget 出现时的微动画)和**屏幕过渡动画**(两个屏幕之间的转场)。两者用的都是同一套缓动(easing)和补间(tweening)数学,和 game feel 用的一样(见 `spline-math`、game-feel-03)。

**入场动画**的常见模式:**scale + fade**。按钮从 90% scale + 0% alpha 缓动到 100% + 100% alpha,持续 120-200ms,缓动用 ease-out-cubic。这组合覆盖 90% 的入场需求。**不要用线性插值(linear)**——线性感觉机械,UI 几乎永远用 ease-out(开始快,结束慢,有"减速到位"的感觉)。

```rust
// easing.rs
pub fn ease_out_cubic(t: f32) -> f32 {
    let t = t - 1.0;
    t * t * t + 1.0
}
pub fn lerp(a: f32, b: f32, t: f32) -> f32 { a + (b - a) * t }
```

**屏幕过渡**的常见模式:**fade**(全屏淡入淡出)、**slide**(新屏从右滑入,旧屏向左滑出,有"层级"暗示)、**scale + fade**(新屏从 95% 放大到 100%,精致感最强)。时长 200-350ms——再长玩家觉得"卡",再短感觉不到。过渡期间要禁止输入(防止半透明菜单里误点)。

```rust
// transitions.rs
pub struct Transition { kind: TransitionKind, progress: f32, duration: f32, block_input: bool }
pub enum TransitionKind { Fade, SlideRight, ScaleFade }

impl Transition {
    pub fn draw(&self, ctx: &mut RenderCtx,
                from: impl Fn(&mut RenderCtx), to: impl Fn(&mut RenderCtx)) {
        let t = self.progress.min(1.0);
        match self.kind {
            TransitionKind::ScaleFade => {
                let eased = ease_out_cubic(t);
                ctx.push_alpha(eased);
                ctx.push_scale(0.95 + 0.05 * eased);
                to(ctx);
                ctx.pop_scale(); ctx.pop_alpha();
            }
            TransitionKind::SlideRight => {
                let off_from = -lerp(0., 200., ease_in_out(t));
                let off_to   =  lerp(200., 0., ease_in_out(t));
                ctx.push_offset(off_from, 0.); from(ctx); ctx.pop_offset();
                ctx.push_offset(off_to,   0.); to(ctx);   ctx.pop_offset();
            }
            TransitionKind::Fade => { /* 略 */ }
        }
    }
}
```

UI 动画的**最高准则是克制**(restraint applies)。动画的存在是让 UI "感觉响应灵敏",不是"让玩家等"。一个 600ms 的菜单入场让玩家每次开菜单都浪费 600ms——**响应性永远高于美观**。准则:**任何动画的时长不应超过玩家"开始烦躁"的阈值(约 300ms)**;动画进行中如果玩家已经按键,应该立即 skip 到终态。一条工程经验——**UI 动画做短的、快的、ease-out 的,几乎不会错**;做得长、慢、bounce 的,大概率会过。

另一个易错点:**动画驱动状态**。新人写 UI 动画容易把"动画进度"和"逻辑状态"绑死——按钮 hover 动画跑 200ms,期间逻辑状态是 "hover_animating",其他系统要等动画结束才能 interact。**这是错的**。逻辑状态应该瞬时切换(鼠标进入按钮 = 立即 hover),动画只是从旧视觉态过渡到新视觉态的过程。**逻辑和动画解耦,动画是单向装饰,绝不阻塞逻辑**。

## 6 · 焦点导航:让 UI "用手柄能玩"

焦点导航(focus navigation)是 PC 游戏 UI 里**最被忽视、最影响体验**的工程领域。鼠标用户用 UI 没任何障碍——他能精确点击屏幕任何位置。但手柄用户没有"指针",他只能**导航**:用左摇杆或方向键移动焦点(focus),用 A/Enter 确认,用 B/Cancel 返回。**这意味着 UI 上的每一个可交互 widget,都必须能被"焦点到达"**。

这是 PC 游戏开发的盲区——开发者在 PC 上用鼠标测试一切顺利,游戏发到 Steam Deck / Xbox / PS5,玩家插手柄发现一半按钮选不到、focus 顺序乱跳、当前焦点没视觉指示——直接弃游。**Ship without focus system and gamepad players suffer**,这不是夸张。

焦点系统的四条铁律:

**第一,每个可交互 widget 必须可 focusable**。按钮、滑块、开关、下拉、列表项——任何能交互的元素都必须能被焦点到达。`disabled` 的 widget 不参与焦点。这条要被 widget 框架强制,不靠程序员记得——基类 widget 应有 `fn is_focusable(&self) -> bool`。

**第二,focus 顺序必须合理**。默认顺序是"声明顺序",但 2D 布局应该按视觉位置(从上到下、从左到右)。常见 bug:按钮代码顺序是 [Start, Settings, Quit],但视觉布局 Settings 在最上面——focus 顺序就乱了。**正确做法:focus 系统读布局引擎的几何信息(part 2 的输出),按位置自动排序**。

**第三,当前焦点必须有清晰的视觉指示**。玩家需要一眼看出"现在按 A 会触发哪个按钮"。常见指示:outline 边框、scale 放大、背景高亮。**Last of Us 2 是行业标杆**:温和高亮 + 微小 scale,既清晰又不抢戏。

**第四,跨屏 focus 转移必须正确**。从主菜单进设置,焦点应自动落到设置第一个 widget;从设置返回,焦点应回到刚才进入设置的按钮(focus memory)。没有它,玩家每次返回都从顶部重新导航,烦躁累积。

看 HH 的焦点系统:

```rust
// focus.rs
use slotmap::SlotMap;
slotmap::new_key_type! { pub struct FocusId; }

pub struct FocusSystem {
    widgets: SlotMap<FocusId, Rect>,         // 由 layout 引擎给出
    order: Vec<FocusId>,                     // 按 geometry 排好的顺序
    current: Option<FocusId>,
    history: Vec<FocusId>,                   // 跨屏返回时恢复
}

impl FocusSystem {
    pub fn register(&mut self, rect: Rect) -> FocusId {
        let id = self.widgets.insert(rect);
        self.order.push(id);
        id
    }

    /// 按 layout 几何排序(从上到下、从左到右),不是声明顺序
    pub fn sort_by_geometry(&mut self) {
        self.order.sort_by_key(|&id| {
            let r = self.widgets[id];
            ((r.y * 1000.) as i64, (r.x * 100.) as i64)
        });
    }

    pub fn move_focus(&mut self, dir: Direction) {
        let i = self.current.and_then(|id| self.order.iter().position(|&x| x == id)).unwrap_or(0);
        let next = match dir {
            Direction::Down | Direction::Next => (i + 1).min(self.order.len() - 1),
            Direction::Up   | Direction::Prev => i.saturating_sub(1),
            _ => i,
        };
        self.current = self.order.get(next).copied();
    }

    pub fn enter_screen(&mut self)  { self.current = self.order.first().copied(); }
    pub fn leave_screen(&mut self)  { if let Some(c) = self.current { self.history.push(c); } self.current = None; }
    pub fn restore(&mut self)       { self.current = self.history.pop().or_else(|| self.order.first().copied()); }
}
```

**焦点顺序由 layout 几何决定**,不是声明顺序——这是 part 2 的布局引擎和 part 3 的焦点系统的天然耦合点。布局引擎已经算出了每个 widget 的 `Rect`,焦点系统拿来排序就行。

**鼠标和手柄的共存**是另一个易错点。理想行为:鼠标动一下,UI 知道用户切到鼠标模式,焦点隐藏(鼠标自己就是指示);手柄方向键一动,UI 切回手柄模式,焦点重新显示并跟随手柄移动。**永远不要在鼠标移动时把手柄焦点强行跟随鼠标**——两种输入会打架。两套输入各自维护自己的"指示器",UI 根据最近活跃输入设备决定显示哪个:

```rust
pub struct InputMode { last_active: InputSource }  // Mouse / Gamepad / Keyboard

impl InputMode {
    pub fn update(&mut self, input: &Input) {
        if input.mouse_delta.length() > 0.5 { self.last_active = InputSource::Mouse; }
        if input.gamepad_any_pressed         { self.last_active = InputSource::Gamepad; }
    }
    pub fn should_show_focus_ring(&self) -> bool {
        matches!(self.last_active, InputSource::Gamepad | InputSource::Keyboard)
    }
}
```

这套共存模式参考了 Web 的 `:focus-visible` CSS 伪类——只有"键盘 / 手柄"导航时显示焦点环,鼠标点击不显示。这是 PC + 主机双栖游戏的标准做法。

最后:**焦点指示必须在第一帧就出现**。如果焦点环在入场动画结束后才显示,玩家前 200ms 看不到"现在按 A 会发生什么"。**焦点指示是 UI 的"地基可见性",优先级高于一切装饰动画**。

## 7 · T7 游戏 UI 序列收口:从架构到屏幕到导航

我们走完了 T7 游戏 UI 深度序列的全部三部分。回过头看这条线:

**Part 1(`game-ui-architecture`)** 解决"UI 子系统在游戏引擎里的位置"——UI 是渲染管线的一个层,是游戏循环的一个 phase,是事件系统的一个消费者。架构层决定了 UI 怎么和渲染、输入、状态、音频系统耦合,决定了 immediate mode 和 retained mode 的边界,决定了 UI 的更新和渲染顺序。没有架构,UI 是"散落在各处的一堆 widget 调用"。

**Part 2(`ui-layout-engines`)** 解决"UI 在屏幕上的几何"——约束求解、anchor / flow / grid 布局、DPI / UI scaling、4K 自适应。布局引擎让"摆放"从硬编码 px 升级为声明式约束,让游戏在任何分辨率都对齐。没有布局引擎,UI 是"写死在 1920x1080 的一堆 magic number"。

**Part 3(本篇)** 解决"玩家实际看见的具体屏幕"——HUD、菜单、设置、背包的工程模式,让 UI "感觉好"的动画与过渡,让 UI "用手柄能玩"的焦点导航。这部分把抽象的架构和算法落到具体的屏幕类型上,每一类都给出了 recurring pattern 和典型反模式。

**三者合起来,定义了"一个专业游戏的 UI 子系统"应该具备的能力**:能在游戏循环里正确更新和渲染且不破坏玩法;能在任意分辨率 / DPI / aspect ratio 上摆对;能用数据绑定和 GameState 单向同步;有四种 canonical 屏幕类型的成熟工程模式(HUD 不挡玩法、菜单走状态栈、设置是 CVar 编辑器、背包状态最重);有动画 / 过渡系统让 UI "感觉贵"但不超过 300ms;有焦点系统让任何 widget 都能手柄到达、focus 顺序由几何决定、鼠标手柄无缝共存;有本地化和无障碍通道(见 `localization-short`、`accessibility-short`),UI 字符串可外化、UI 元素可缩放、a11y 选项集成在设置屏。

**UI 是玩家体验的一半**。这话不是修辞——玩家打开游戏看见的第一屏是 UI,关闭游戏看见的最后一屏是 UI,按 ESC 看见的是 UI,死亡后看见的是 UI,改设置时操作的是 UI。玩法再好,UI 拉胯,玩家会觉得这个游戏"糙"。**工程化 UI 不是可选项,是基本功**。

T7 是 HH 项目里 UI 的总集——把架构、布局、屏幕、动画、导航五条线全跑通,你的 UI 子系统就从"能用的 UI"升级到"专业的 UI"。这些能力会贯穿 T8(网络多人 UI 同步)和 T9(制作交付的最终 UI 打磨)。**UI 没有终点,只有持续打磨**——但有了这三篇的工程基础,你的打磨是有方向的。

## 8 · 在你 HH 项目里动手(做中学红线)

把 part 1 和 part 2 的成果接上,把 HH 的 UI 推到"专业 UI"水准。完成后你的 UI 子系统在架构、布局、屏幕、动画、焦点五个维度全部上线。

**第一步:HUD 数据绑定 + 布局自适应**。打开 HUD 代码,确认:(a) HUD 不持有 hp / ammo 副本,每帧从 `GameState` 读;(b) HUD 用布局引擎的 `anchor` 钉到边角,不在屏幕中央留任何元素;(c) 实现 idle 淡出——血条满且 3 秒未受伤降到 30% 透明度;(d) 受伤时血条闪红 400ms。验证:在 1280x720 和 3840x2160 两档分辨率下,HUD 都正确贴边、不挡角色。

**第二步:主菜单 + 暂停菜单走状态栈**。把现有的 `bool in_main_menu; bool in_pause_menu;` 全删掉,改用 `Vec<Screen>` 状态栈。验证:暂停菜单里打开设置(栈变成 `[InGame, PauseMenu, Settings]`),从设置返回暂停菜单,从暂停菜单返回游戏——每步都正确恢复,焦点也跟随恢复。

**第三步:设置屏做 CVar 编辑器**。建 `CVarRegistry`,把 video / audio / input / accessibility 设置全部注册成 CVar。重写设置屏,每个 widget 只做"读 CVar → 画 → 写回 CVar",`on_change` 处理实际 apply。验证:拖音量滑块时背景音乐实时变化(不要 Apply 按钮);改 UI scale 后整个 UI 实时重新布局。

**第四步:加 UI 过渡动画**。给主菜单入场、暂停菜单弹出、设置进入都加 250ms 的 scale-fade 过渡,缓动用 ease-out-cubic。验证:过渡期间禁止输入;过渡中玩家按键,过渡立即 skip 到终态。**关键验证:连按 ESC 不会因为动画重叠卡死**。

**第五步(最关键):焦点系统 + 纯手柄测试**。把所有可交互 widget 注册进 `FocusSystem`,focus 顺序由 layout 几何自动排序,焦点指示(温和 outline + 微小 scale)在第一帧就出现。然后——**拔掉鼠标**,只用手柄玩 HH 的全部 UI 流程:主菜单 → 游戏 → 按 Start 弹暂停 → 进设置 → 改音量 → 返回 → 进背包 → swap 两个物品 → 返回游戏。

这个流程里你会发现一堆 focus 漏洞:某按钮忘注册、focus 顺序乱跳、跨屏焦点丢失、视觉指示太弱。**逐个修,直到全程手柄流畅**。这是 PC 游戏最容易跳过的测试,但它是"专业 UI"和"业余 UI"的分水岭。一个能在 4K 屏 + 手柄 + 日语 locale 下流畅操作的 UI,是真正交付级 UI,也是 T8 / T9 的坚实基础。

## 9 · 练习

**Lv 1 · 静态 HUD**。给 HH 加最简 HUD——左上角血条(满血红色),右上角弹药数字。固定位置,不做动画,不做数据绑定(硬编码 `hp = 100`)。目标:先让 HUD 出现在屏幕上。

**Lv 2 · HUD 数据绑定 + idle 淡出**。把 Lv 1 的 HUD 接到 `GameState`,血量从 state 读。实现 idle 3 秒淡出、受伤 400ms 闪烁。在 720p / 1080p / 4K 三档分辨率下验证 HUD 贴边正确(用布局引擎,不要硬编码 px)。

**Lv 3 · 状态栈 + 设置屏 CVar 化**。把 main menu / pause / settings 全部改成 `Vec<Screen>` 状态栈。把现有设置全部注册成 CVar,设置屏代码改写成 "取 CVar → 画 widget → 写回 CVar" 三行模式。验证设置改了实时生效(音量滑块拖动时背景音乐立即变化)。

**Lv 4 · 焦点系统 + 纯手柄通关测试(毕业题)**。实现完整的 `FocusSystem`(register / sort_by_geometry / move_focus / enter_screen / leave_screen / restore)。给所有可交互 widget 加焦点环视觉指示(温和 outline + 微小 scale)。加 250ms scale-fade 屏幕过渡动画(ease-out-cubic)。然后**拔鼠标,只用手柄**:从主菜单开始,经过游戏、暂停、设置(改一次音量)、背包(swap 一次物品)、返回游戏。修完所有 focus 漏洞,直到全程流畅。这题做对,你的 UI 工程能力达到独立游戏交付水平。

## 10 · 延伸阅读

**序列内交叉引用**:
- `game-ui-architecture.md`(T7 UI part 1:UI 子系统在游戏引擎里的位置,本文是它的延续)
- `ui-layout-engines.md`(T7 UI part 2:布局引擎、约束求解、UI scaling,本文 HUD / 菜单的几何全由它产出)
- `immediate-mode-editor.md`(immediate mode UI 完整讨论,HUD 通常用 immediate)
- `accessibility-short.md`(无障碍选项,本文设置屏的 a11y tab 全部来自这里)
- `localization-short.md`(本地化,UI 字符串外化,设置屏的 Language tab)
- `ui-data-binding-short.md`(数据绑定,Hud / inventory 屏的 state 同步基础)

**跨序列交叉引用**:
- `game-state-management.md`(状态栈、game state 分层,本文菜单走 state stack 的来源)
- `input-handling-for-games.md`(鼠标 + 手柄共存,本文焦点系统的输入侧基础)
- `spline-math.md`(UI 过渡动画的缓动函数数学基础,ease-out-cubic / Bezier)
- game-feel-03(UI 动画和 game feel 共用同一套 tweening 数学)

**外部资源**:
- Game Accessibility Guidelines(https://gameaccessibilityguidelines.com/):a11y 选项放在设置屏哪里、叫什么名字,业界标准
- Material Design Motion(https://m3.material.io/styles/motion/overview):Google 的 UI 动画时长 / 缓动指南,easing 选型工业参考
- "Designing Game UI for Consoles"(GDC 演讲系列):焦点导航、手柄 UI、跨平台 UI 实战
- "The UI of The Last of Us Part II"(Naughty Dog GDC):focus 指示、a11y 集成的行业天花板
- iced 文档(https://docs.rs/iced/):声明式 UI + 数据绑定的 Rust 实现参考
- Dear ImGui / egui 的 focus API:看 immediate mode 库怎么解决"immediate 下的 focus 持久化"
