
# T5-2 · 游戏输入工程:把按键抽象成动作

> 这是 **T5 游戏性序列**的输入工程专题,和 `game-feel-01-input-and-timing-feel.md` 是一对——那篇讲"游戏怎么处理玩家的意图"(input buffer、coyote time、可变跳跃高度),这一篇讲"游戏怎么**接收**玩家的意图"。两篇一起读才完整:那篇的输入缓冲(input buffer)**消费**的是这一篇产出的"动作";这一篇产不出干净的动作,那篇的缓冲就缓冲不到东西。所以 prereq 是 `game-feel-01`,顺序不能反。

## 0 · 你的硬编码,正在把玩家锁在门外

你刚做完 HH 的角色控制,代码长这样:`if key == W { pos.y += 1 }`、`if key == Space { jump() }`、`if key == J { attack() }`。你跑起来玩,手感不错,准备发给朋友。

第一个朋友是法国人,他用的是 AZERTY 键盘——他按"前"想按的键根本不是 W,是 Z。他按下你认定的"前",角色纹丝不动。第二个朋友只有一只手柄,没有键盘,他连"开始游戏"都过不去。第三个朋友是左撇子,他想用方向键移动、右手区按键跳,你的代码不允许。第四个朋友手部有运动障碍,需要把"冲刺"从长按改成单按切换,你的代码里"冲刺"和"按住 J"焊死在一起。

你的游戏,对这四个人,**完全不能玩**。不是难度问题,是**工程问题**——你的输入代码假设了"所有人用同一种 QWERTY 键盘、用同一套默认按键、用同样的方式按"。这个假设在任何真实玩家群体里都是错的。专业游戏项目的输入系统,要把这个假设彻底拆掉。

拆掉它的方式只有一个词:**把按键抽象成动作**(action abstraction)。这是这一篇的全部主题,也是后面所有——重绑定、多设备、本地化、无障碍——的地基。这一篇结束时,你的 HH 会从一个"只认 W 键"的 demo,变成一个 AZERTY、手柄、左手党、运动障碍玩家都能玩的游戏。改动量不大,但思路要先拐一个弯。

## 1 · 永远别问"按下了 W 吗"——问"MoveForward 这个动作激活了吗"

这一篇的核心,是游戏行业里一条几乎无人反对的设计原则,但它和初学者的直觉相反。初学者的直觉是"我想让角色向前,我就检测向前那个键"。原则反过来:**游戏逻辑永远不应该知道任何具体按键的存在**。

游戏逻辑应该知道的是**动作**(action)。MoveForward 是一个动作,Jump 是一个动作,Attack 是一个动作。游戏逻辑问的是"MoveForward 现在激活吗?"、"Jump 这一帧被触发了吗?"——至于 MoveForward 是从键盘的 W 来的、还是从方向键的 Up 来的、还是从手柄左摇杆推上来来的,**游戏逻辑不知道,也不关心**。在游戏逻辑和物理按键之间,有一层叫**输入映射**(input mapping)的中间层,它负责把"物理输入"翻译成"逻辑动作"。这一层是数据,不是代码——它是一张配置表,写着"W → MoveForward"、"Space → Jump"、"GamepadLeftStickUp → MoveForward"。

这个 indirection(间接层)看似只是把代码挪了个位置,但它解锁的能力是惊人的。当映射是数据,玩家就能改它——这就是**重绑定**(rebinding),你只需要让玩家改那张配置表,代码一行不用动。当映射是数据,多设备就自然支持——同一张表里可以同时有键盘项和手柄项,MoveForward 同时绑着 W 和左摇杆,谁先来用谁。当映射是数据,本地化也好做——法国玩家加载一张"Z → MoveForward"的默认表,代码完全一样。当映射是数据,无障碍的"按键重映射"自动就有了——它和"玩家自己重绑定"是同一件事。**一个 indirection,解决五个问题**,这就是软件工程里"加一层抽象"的典型回报。

把这套设计落到 Rust 里,先定义动作:

```rust
/// 游戏里所有的逻辑动作。游戏代码只认识这些枚举值,
/// 永远不直接碰任何具体按键 / 摇杆。
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub enum Action {
    MoveForward,
    MoveBackward,
    MoveLeft,
    MoveRight,
    Jump,
    Attack,
    Interact,
    Dash,
    // ...
}

/// 一个动作的"当前状态"。注意它分两种语义:
/// - 二值动作(跳、攻击):你关心 Pressed(这一帧刚按下)
///   和 Released(这一帧刚松开),它们是事件。
/// - 连续动作(移动):你关心 Axis 值,是状态。
pub enum ActionState {
    /// 二值:这一帧刚从松开变按下
    Pressed,
    /// 二值:这一帧刚从按下变松开
    Released,
    /// 二值:当前正按住
    Held,
    /// 模拟:归一化到 [-1, 1] 或 [0, 1] 的轴值
    Axis(f32),
}
```

注意 `ActionState` 里**故意混了事件和状态两种语义**(Pressed 是"刚刚发生"的事件,Held 是"现在如何"的状态),这是后面 §6 要专门讲的话题。这里先把字段放出来,细节等到那一节再展开。

定义完动作,游戏逻辑那边就干净了。移动代码长这样:

```rust
fn update_player(player: &mut Player, input: &ActionSet, dt: f32) {
    // 注意:这里没有一个 KeyCode、一个按钮、一个轴的影子。
    // 全是 Action。换设备、换按键,这段代码一行不改。
    let mv = Vector2::new(
        input.axis(Action::MoveRight) - input.axis(Action::MoveLeft),
        input.axis(Action::MoveForward) - input.axis(Action::MoveBackward),
    );
    player.vel = mv.normalize_or_zero() * MOVE_SPEED;

    if input.pressed(Action::Jump) {
        // 注意这里把"想跳"交给 game-feel-01 的输入缓冲去处理,
        // 不是直接 jump()。直接跳就没有 input buffer 的宽容度了。
        player.jump_buffer.press();
    }
    if input.pressed(Action::Attack) {
        player.attack();
    }
}
```

看到没有——这段代码**完全不知道**玩家用的是键盘还是手柄。它问的是"MoveForward 这个动作激活吗",动作怎么来的,是 input mapping 层的事。这就是动作抽象的威力。

## 2 · 输入映射:把"物理输入"翻译成"逻辑动作"的数据

现在讲中间层——输入映射(input mapping)怎么实现。这一层的输入是"物理输入源"(键盘、鼠标、手柄)给的原始事件和状态,输出是"动作状态"。它的核心是一张映射表,加上一个每帧执行的"翻译"过程。

物理输入源的抽象长这样——每一种设备都把自己包装成统一的"原始输入"接口:

```rust
/// 一个物理输入源的抽象。键盘、手柄、(可选)触摸都实现它。
pub trait InputSource {
    /// 轮询:某个按键 / 按钮现在按下了吗?(状态查询,用于 Held)
    fn is_key_down(&self, key: PhysicalKey) -> bool;
    /// 这一帧有没有"刚按下"的事件?(事件查询,用于 Pressed)
    fn take_pressed_events(&mut self) -> Vec<PhysicalKey>;
    /// 这一帧有没有"刚松开"的事件?
    fn take_released_events(&mut self) -> Vec<PhysicalKey>;
    /// 某个模拟轴的当前值(摇杆、触发器、鼠标移动)
    fn axis(&self, axis: PhysicalAxis) -> f32;
}

/// 物理按键的统一 ID。把键盘的 KeyA、手柄的 SouthButton、
/// 鼠标的 Left 都塞进同一个枚举——这样映射表能用一种类型表达所有设备。
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub enum PhysicalKey {
    Keyboard(KeyCode),
    Gamepad(gilrs::Button),
    Mouse(MouseButton),
}
```

这里的要点是:**所有设备的物理输入,都被归一化成 `PhysicalKey` / `PhysicalAxis` 这两个统一类型**。键盘按 A、手柄按 A(南方按钮/Xbox 的 A)、鼠标按左键,在映射层看都是"一个 PhysicalKey 被按下了"。归一化之后,映射表只用一种数据结构就能描述跨设备绑定。

然后是映射表本身。它就是一张"物理输入 → 动作"的多对多字典:

```rust
use std::collections::HashMap;

/// 一条绑定:某个物理输入,映射到某个逻辑动作,带有"作为轴还是作为按钮"的语义。
#[derive(Clone, Debug)]
pub enum Binding {
    /// 按钮型:按下=Pressed,松开=Released,持续按下=Held
    Button,
    /// 轴型:把物理轴(摇杆、触发器)的值原样作为这个动作的 Axis 值
    Axis { scale: f32 },
    /// 按键当轴用:按住=1.0,松开=0.0。键盘的"W=MoveForward"是这种。
    KeyAsAxis { negative: bool },
}

/// 玩家的完整绑定配置。这就是"映射是数据"那句承诺的兑现——
/// 这张表可以序列化、可以从文件加载、可以让玩家改。
#[derive(Clone, Debug, Default)]
pub struct InputBindings {
    /// PhysicalKey → (Action, Binding)
    /// 一个物理键可以绑多个动作(比如"按下左摇杆 = 冲刺 + 标记敌人")
    /// 一个动作也可以绑多个物理键(比如 Jump 绑 Space 和 GamepadSouth)
    pub map: HashMap<PhysicalKey, Vec<(Action, Binding)>>,
}

impl InputBindings {
    /// 默认绑定。这相当于"出厂按键",玩家可以全部改掉。
    pub fn default_qwerty() -> Self {
        let mut m = HashMap::new();
        m.insert(PhysicalKey::Keyboard(KeyCode::W),
                 vec![(Action::MoveForward, Binding::KeyAsAxis { negative: false })]);
        m.insert(PhysicalKey::Keyboard(KeyCode::S),
                 vec![(Action::MoveBackward, Binding::KeyAsAxis { negative: false })]);
        m.insert(PhysicalKey::Keyboard(KeyCode::A),
                 vec![(Action::MoveLeft, Binding::KeyAsAxis { negative: false })]);
        m.insert(PhysicalKey::Keyboard(KeyCode::D),
                 vec![(Action::MoveRight, Binding::KeyAsAxis { negative: false })]);
        m.insert(PhysicalKey::Keyboard(KeyCode::Space),
                 vec![(Action::Jump, Binding::Button)]);
        m.insert(PhysicalKey::Keyboard(KeyCode::J),
                 vec![(Action::Attack, Binding::Button)]);
        // 手柄默认绑定——同一个动作绑到不同设备
        m.insert(PhysicalKey::Gamepad(gilrs::Button::South),
                 vec![(Action::Jump, Binding::Button)]);
        m.insert(PhysicalKey::Gamepad(gilrs::Button::West),
                 vec![(Action::Attack, Binding::Button)]);
        Self { map: m }
    }
}
```

注意默认表里 `Jump` 同时绑了 `Space`(键盘)和 `GamepadSouth`(手柄)——这就是多设备的本质:**同一个动作绑到多个物理输入**,谁先被触发,动作就先激活。代码里没有任何"if 用键盘 then ... else if 用手柄 then ..."这种分支,映射表自然就把多设备统一了。

每帧的翻译过程——把这一帧的物理输入,根据映射表,翻译成 `ActionSet`(动作状态集合)给游戏逻辑用:

```rust
use std::collections::HashMap;

/// 这一帧所有动作的当前状态。游戏逻辑从这里读。
#[derive(Default)]
pub struct ActionSet {
    held: HashMap<Action, bool>,
    pressed_this_frame: HashMap<Action, bool>,
    released_this_frame: HashMap<Action, bool>,
    axis_value: HashMap<Action, f32>,
}

impl ActionSet {
    /// 这一帧这个动作"刚按下"吗?用于离散动作(跳、攻击)。
    /// 注意这是事件语义——只有从松开变按下的那一帧为 true。
    pub fn pressed(&self, a: Action) -> bool {
        *self.pressed_this_frame.get(&a).unwrap_or(&false)
    }
    pub fn released(&self, a: Action) -> bool {
        *self.released_this_frame.get(&a).unwrap_or(&false)
    }
    pub fn held(&self, a: Action) -> bool {
        *self.held.get(&a).unwrap_or(&false)
    }
    /// 这个动作当前的轴值。用于移动(键盘按住 = 1.0,摇杆 = 实际推杆量)。
    pub fn axis(&self, a: Action) -> f32 {
        *self.axis_value.get(&a).unwrap_or(&0.0)
    }
}

/// 输入映射器:每帧调用一次,把所有 InputSource 的原始输入,
/// 翻译成 ActionSet。这是中间层的主要类。
pub struct InputMapper {
    bindings: InputBindings,
    /// 上一帧每个 Action 是不是 held,用来算"刚按下 / 刚松开"。
    prev_held: HashMap<Action, bool>,
}

impl InputMapper {
    pub fn new(bindings: InputBindings) -> Self {
        Self { bindings, prev_held: Default::default() }
    }

    /// sources 是这一帧所有活跃设备的 InputSource 引用。
    /// 注意:多设备同时活跃——键盘和手柄一起喂进来。
    pub fn translate(&mut self, sources: &[&dyn InputSource]) -> ActionSet {
        let mut cur_held: HashMap<Action, bool> = Default::default();
        let mut axis_value: HashMap<Action, f32> = Default::default();

        // 第一步:对每个物理按键,查映射表,把状态写进对应动作。
        for src in sources {
            for (key, bound_actions) in &self.bindings.map {
                for (action, binding) in bound_actions {
                    let down = src.is_key_down(*key);
                    match binding {
                        Binding::Button => {
                            // 累积:多个键绑同一个动作,任一按下即视为按下
                            *cur_held.entry(*action).or_insert(false) |= down;
                        }
                        Binding::KeyAsAxis { negative } => {
                            let v = if down { 1.0 } else { 0.0 };
                            let v = if *negative { -v } else { v };
                            // 多个键绑同一个轴动作,取最大绝对值(常见做法)
                            let e = axis_value.entry(*action).or_insert(0.0);
                            if v.abs() > e.abs() { *e = v; }
                        }
                        Binding::Axis { scale } => {
                            // 这个 binding 需要查对应轴值,简化:这里假设
                            // key 隐含了一个 PhysicalAxis。生产代码会拆分 Key/Axis 绑定。
                            let _ = scale; // 省略:实际从 src.axis(...) 读
                        }
                    }
                }
            }
        }

        // 第二步:处理事件(刚按下 / 刚松开)。这里简化:用前后帧 held 差分推出来。
        // 真实实现可以从 InputSource 直接 take 事件,更精确。
        let mut pressed_this_frame = HashMap::new();
        let mut released_this_frame = HashMap::new();
        for (action, now_held) in &cur_held {
            let was_held = *self.prev_held.get(action).unwrap_or(&false);
            if *now_held && !was_held {
                pressed_this_frame.insert(*action, true);
            }
        }
        for (action, was_held) in &self.prev_held {
            let now_held = *cur_held.get(action).unwrap_or(&false);
            if *was_held && !now_held {
                released_this_frame.insert(*action, true);
            }
        }

        self.prev_held = cur_held.clone();

        ActionSet {
            held: cur_held,
            pressed_this_frame,
            released_this_frame,
            axis_value,
        }
    }
}
```

这段代码看起来长,核心就两步:**遍历所有设备的所有物理按键,查映射表,把状态累积到对应动作;然后比较前后帧,推出"刚按下/刚松开"事件**。注意几个设计点——多个物理键绑同一个动作时,我用"任一按下即视为按下"(`|=`),这是符合直觉的(W 和方向键 Up 都让 MoveForward 激活);轴动作用"取最大绝对值",避免两个相反方向抵消。这些细节是真实输入系统要处理的,生产框架(bevy_input、FNA)的实现都类似。

## 3 · 重绑定:让玩家自己改那张映射表

既然映射是数据(`InputBindings` 这个 struct),让玩家改它就是改数据——这叫**重绑定**(rebinding),是现代游戏的标配,也是欧盟 EAA 2025 法规对游戏的要求。

重绑定的交互流程是这样的:玩家进设置菜单,选"重映射按键",点击"跳跃"那一行,UI 显示"按下新按键...",然后玩家按下任意键——可能是 Space,可能是鼠标侧键,可能是手柄的某个按钮。游戏捕获这个按键,把它写进 `InputBindings`,保存到配置文件。下次游戏启动,加载这个文件,玩家的自定义按键就生效了。

捕获按键这一步,需要"监听下一个任意输入"的能力。代码上,把输入系统短暂切到一个"捕获模式":

```rust
/// 重绑定 UI 的状态。
pub enum RebindState {
    /// 空闲,不在重绑定流程
    Idle,
    /// 等待玩家按下新按键,绑定到这个动作
    WaitingFor(Action),
}

pub struct RebindUi {
    state: RebindState,
}

impl RebindUi {
    pub fn begin_rebind(&mut self, action: Action) {
        self.state = RebindState::WaitingFor(action);
    }

    /// 每帧调用。如果当前在 WaitingFor 状态,
    /// 就把这一帧收到的"任意按键事件"绑到目标动作。
    /// 返回 true 表示完成了重绑定(可以刷新 UI 显示)。
    pub fn update(
        &mut self,
        pressed_keys: &[PhysicalKey],
        bindings: &mut InputBindings,
    ) -> bool {
        match &self.state {
            RebindState::WaitingFor(action) => {
                if let Some(&key) = pressed_keys.first() {
                    // 一个动作原来绑的物理键清掉(简化:单一绑定;
                    // 多设备应该允许保留多绑定)
                    bindings.map.retain(|_, _| true); // 实际按 action 过滤
                    bindings.map.entry(key).or_default()
                        .push((*action, Binding::Button));
                    self.state = RebindState::Idle;
                    return true;  // 完成,UI 可以刷新
                }
                false
            }
            RebindState::Idle => false,
        }
    }
}
```

绑定表怎么持久化?最简单的就是 serde 序列化到一个文件:

```rust
// Cargo.toml: serde = { version = "1", features = ["derive"] }
use serde::{Serialize, Deserialize};

#[derive(Serialize, Deserialize)]
struct BindingsFile {
    /// 版本号——绑定格式以后会演进,留这个字段做迁移
    version: u32,
    bindings: InputBindings,
}

impl InputBindings {
    pub fn save(&self, path: &str) -> std::io::Result<()> {
        let f = BindingsFile { version: 1, bindings: self.clone() };
        let json = serde_json::to_string_pretty(&f).unwrap();
        std::fs::write(path, json)
    }

    pub fn load(path: &str) -> Option<Self> {
        let json = std::fs::read_to_string(path).ok()?;
        let f: BindingsFile = serde_json::from_str(&json).ok()?;
        // 这里可以 match f.version 做迁移
        Some(f.bindings)
    }
}
```

**重要细节**:绑定文件要带版本号。你的绑定格式第一版可能只有键盘,第二版加了手柄触发器轴,第三版改了轴的存储方式——没有版本号,老玩家的存档加载到新代码里直接崩。所有用户可编辑的配置文件都应该有 `version` 字段,这是工程常识,但新手最容易忘。

重绑定还涉及**冲突检测**——玩家把"跳跃"和"攻击"都绑到 Space,这怎么办?常见策略:要么禁止(弹窗提示"已绑定到攻击,是否覆盖"),要么允许多绑定(Space 同时触发跳和攻击,某些游戏允许)。前者更安全,后者更灵活。 Celeste 走的是"允许冲突,冲突时按动作优先级处理"——但 Celeste 的动作集很小,大型游戏一般禁止冲突。这个策略要在设计阶段定下来,影响 UI 流程。

最后,**Steam Input** 和操作系统的输入重映射(Windows 的"游戏控制器"设置、macOS 的 Controller Mapper)在外部也能改按键。你的游戏不应该和它们打架——如果玩家在 Steam Input 里把"按 A"映射成了"按 B",你这边收到的物理按键就是 B,你按 B 处理即可。Steam Input 还有一个更强的功能:它能把 Steam 的虚拟动作直接喂给游戏(通过 Steam Input API),这样游戏连"动作映射"都可以外包给 Steam。这是 PC 游戏的常见集成方式。

## 4 · 多设备:键盘 + 鼠标 + 手柄 + 触摸,统一在一套动作下

现在专门讲多设备。多设备的本质,是同一个游戏同时支持**多种物理输入方式**,而且要让玩家**随时切换**——比如玩家用键盘玩了 10 分钟,拿起手柄,游戏应该立刻切到手柄 UI(按钮提示从"按 Space"变成"按 A")。

这个"随时切换"的能力叫**热插拔**(hot-swap),它的实现关键是:**每一帧都要轮询所有设备,而不是只轮询"当前活跃设备"**。如果你的代码是"启动时检测到键盘就用键盘,检测到手柄就用手柄",玩家中途拿手柄就拿不起来。正确做法是——所有设备每帧都喂给 InputMapper,谁有输入就用谁。设备可以在 `sources: &[&dyn InputSource]` 这个数组里动态增减,玩家插上手柄,gilrs 检测到了,下一帧就多了一个 source。

用 gilrs 处理手柄。gilrs(Game Input Library for Rust in Style)是 Rust 生态里最成熟的手柄库,支持 Xbox / PlayStation / Switch Pro / 各种第三方手柄,跨平台(Linux evdev、Windows xinput、macOS IOKit)。它的 API 给你的是"标准化的手柄按钮和轴"——无论玩家插的是 Xbox 手柄还是 PS 手柄,你看到的都是 `Button::South`(南方按钮)、`Button::LeftThumb`(左摇杆按下)、`Axis::LeftStickX` 这种**抽象按钮名**,不用关心底层差异。

把 gilrs 包成 InputSource:

```rust
// Cargo.toml: gilrs = "0.10"
use gilrs::{Gilrs, Event, EventType, Button, Axis};

pub struct GamepadSource {
    gilrs: Gilrs,
    /// 这一帧累积的事件,translate 完后清空
    pressed_events: Vec<PhysicalKey>,
    released_events: Vec<PhysicalKey>,
    /// 当前每个按钮的按下状态
    button_down: std::collections::HashSet<Button>,
}

impl GamepadSource {
    pub fn new() -> Self {
        Self {
            gilrs: Gilrs::new().expect("failed to init gilrs"),
            pressed_events: Vec::new(),
            released_events: Vec::new(),
            button_down: Default::default(),
        }
    }

    /// 每帧开头调用,把 gilrs 队列里的事件抽出来累积。
    pub fn poll_events(&mut self) {
        // 重要:这一步要在主循环的最开头做,见 §6 关于延迟的讨论
        while let Some(Event { event, .. }) = self.gilrs.next_event() {
            match event {
                EventType::ButtonPressed(b, _) => {
                    self.button_down.insert(b);
                    self.pressed_events.push(PhysicalKey::Gamepad(b));
                }
                EventType::ButtonReleased(b, _) => {
                    self.button_down.remove(&b);
                    self.released_events.push(PhysicalKey::Gamepad(b));
                }
                EventType::Disconnected => { /* 处理手柄拔掉 */ }
                _ => {}
            }
        }
    }
}

impl InputSource for GamepadSource {
    fn is_key_down(&self, key: PhysicalKey) -> bool {
        match key {
            PhysicalKey::Gamepad(b) => self.button_down.contains(&b),
            _ => false,
        }
    }
    fn take_pressed_events(&mut self) -> Vec<PhysicalKey> {
        std::mem::take(&mut self.pressed_events)
    }
    fn take_released_events(&mut self) -> Vec<PhysicalKey> {
        std::mem::take(&mut self.released_events)
    }
    fn axis(&self, axis: PhysicalAxis) -> f32 {
        match axis {
            // 注意:这里只查"第一个"连接的手柄——多手柄要扩展
            PhysicalAxis::Gamepad(a) => {
                self.gilrs.gamepads().next()
                    .and_then(|(_, gp)| Some(gp.value(a)))
                    .unwrap_or(0.0)
            }
            _ => 0.0,
        }
    }
}
```

**设备识别 UI**(device-aware UI prompts)是多设备的另一个工程点。当玩家用手柄时,UI 应该显示"按 A 跳跃";切到键盘,显示"按 Space 跳跃"。实现方式:InputMapper 维护一个"最近用过的设备"字段,每次某设备产生输入就更新这个字段。UI 渲染时查这个字段,选对应的提示图标。Steam 的游戏库几乎所有支持多设备的游戏都这么做——塞尔达、艾尔登法环、Hades 都是。

最后**触摸**。触摸输入和键盘/手柄的抽象层级不一样——触摸是"屏幕上某个点被按下了",不是"某个按钮被按下"。触摸要映射成动作,要么通过虚拟手柄(virtual gamepad,屏幕上画两个摇杆按钮,触摸它们等价于推摇杆),要么通过"点击屏幕某区域 = 触发某动作"。移动端游戏几乎都用前者。这一篇不深入触摸——它的工程量和键盘手柄加起来一样大——但**动作抽象层天然支持触摸**:你只要写一个 `TouchSource: InputSource`,把触摸事件包装成 PhysicalKey / PhysicalAxis,后面所有映射、动作、游戏逻辑都不用改。这就是抽象层的红利。

## 5 · 死区与模拟轴处理:摇杆永远不在零点

讲完按钮,讲摇杆。摇杆是**模拟输入**(analog input)——它给的不是"按下 / 没按下"的二值,是 -1.0 到 +1.0 之间的连续值。这个连续值是摇杆手感的核心(推一半 = 走一半速度),但它带来了一个工程问题:**摇杆永远不在精确的零点**。

物理上,摇杆的弹簧让它松手时回到中心,但机械公差、磨损、灰尘,让它"回中"的位置总有几度的偏差。你读 gilrs 的 `Axis::LeftStickX`,即使玩家完全没碰摇杆,你也会读到 0.03、-0.05、0.02 这种小噪声值。如果你直接把这个值当成"移动量",角色会**自己慢慢飘**——玩家没碰摇杆,角色却往外走。这是摇杆游戏最经典的一个 bug,几乎所有新手都踩过。

修法叫**死区**(deadzone):定义一个内半径,摇杆在这个半径内的值统统当成零;定义一个外半径,摇杆在这个半径外的值就是满量程;内外之间做**归一化**(normalize),让响应曲线平滑。代码:

```rust
/// 摇杆死区配置。一个轴一对(inner, outer)半径。
#[derive(Clone, Copy, Debug)]
pub struct Deadzone {
    /// 内半径:[0, 1]。摇杆绝对值 <= inner 时,输出 0。
    pub inner: f32,
    /// 外半径:[inner, 1]。摇杆绝对值 >= outer 时,输出 ±1。
    pub outer: f32,
}

impl Default for Deadzone {
    fn default() -> Self {
        // 业界常用默认值。inner=0.05 防止漂移,outer=0.95 给满量程一点裕度。
        Self { inner: 0.05, outer: 0.95 }
    }
}

impl Deadzone {
    /// 把原始摇杆值,经过死区处理,变成干净的 [-1, 1] 输出。
    pub fn apply(&self, raw: f32) -> f32 {
        let mag = raw.abs();
        if mag <= self.inner {
            0.0  // 死区内,忽略
        } else if mag >= self.outer {
            raw.signum()  // 满量程
        } else {
            // 内外之间:线性归一。这样响应曲线在 inner 处从 0 开始平滑上升。
            // 注意:从 0 开始,不是从 raw 开始——否则死区边缘会有跳变。
            let sign = raw.signum();
            let t = (mag - self.inner) / (self.outer - self.inner);
            sign * t
        }
    }
}
```

死区有两个常见错误。**第一个错误是"只在单轴上做死区"**——把 X 和 Y 分别过一遍死区。这叫**轴向死区**(axial deadzone),它有个问题:当摇杆推到一个对角线方向(比如 X=0.1, Y=0.1,摇杆总幅度 0.14),每个轴单独看都过了 0.1 的死区,角色就动了——但玩家可能只是手抖了一下。更稳的做法是**圆形死区**(radial deadzone):把 X 和 Y 看成一个二维向量,算它的长度,长度小于 inner 才忽略。圆形死区更符合摇杆的物理直觉(玩家"没推够"是一个二维概念,不是 X 没推够且 Y 没推够)。

```rust
/// 圆形死区:把 (x, y) 当成一个向量,长度小于 inner 时整体归零。
/// 这是更稳的做法,推荐用于左摇杆(移动)。
pub fn apply_radial_deadzone(x: f32, y: f32, dz: &Deadzone) -> (f32, f32) {
    let mag = (x * x + y * y).sqrt();
    if mag <= dz.inner {
        (0.0, 0.0)
    } else if mag >= dz.outer {
        // 满量程:保持方向,长度为 1
        let s = 1.0 / mag;
        (x * s, y * s)
    } else {
        // 归一化:把长度从 [inner, outer] 映射到 [0, 1]
        let t = (mag - dz.inner) / (dz.outer - dz.inner);
        let s = t / mag;
        (x * s, y * s)
    }
}
```

**第二个错误是"死区值用死的常量"**。每根摇杆、每个手柄的物理特性都不一样——磨损的手柄死区要更大(中心漂移更厉害),高端手柄死区可以更小(中心更准)。死区应该做成**可配置**,而且理想情况下**每个手柄独立配置**——存到手柄 ID 对应的配置里。Steam Input 之所以强大,部分原因就是它给每个手柄单独存配置。在你的 HH 里,先做一个全局死区 CVar(`g_gamepad_deadzone_inner`, `g_gamepad_deadzone_outer`,见 `09B-4`),够用了。

死区之外还有**敏感度曲线**(sensitivity curve)——归一化后的值,不一定是线性的。FPS 游戏常常用指数曲线(推一点 = 慢慢走,推到底 = 全速),让玩家有"精细瞄准"和"快速转身"两档控制。曲线可以用一个查找表(LUT)实现,玩家可调。Celeste 的摇杆响应曲线就是精心调过的,它不是线性的。这些都是模拟输入工程的进阶话题,但**死区是地基,敏感度曲线是上层**——先做死区。

## 6 · 事件 vs 轮询:两种语义,缺一不可

现在讲一个看起来抽象、但工程影响巨大的区分:**事件**(event)和**轮询**(polling)。这是输入系统两种不同的"读取"语义,你之前在 §1 的 `ActionState` 里看到 Pressed(事件)和 Held(状态)混在一起,现在解释为什么。

**轮询**是"现在如何"——游戏每一帧问一次"MoveForward 现在激活吗?",得到一个布尔或一个浮点。轮询适合**连续状态**:角色移动是连续的(你在每一帧根据"现在按住移动键吗"决定速度),用轮询。`is_key_down` / `held` / `axis` 都是轮询语义。

**事件**是"发生过"——游戏不问"现在如何",而是接收"刚才发生过什么"的通知。事件带时间戳,描述一个**离散**的发生:玩家在 T 时刻按下了一次跳键,这是一次性的事件,不会持续。事件适合**离散动作**:跳跃、攻击、互动、菜单确认——这些是"发生一次就完了"的动作,游戏关心的是"这一帧有没有刚按下",不是"现在按住吗"。`pressed_this_frame` / `released_this_frame` 是事件语义。

为什么不能只用一种?**因为两者各有盲区**。如果你只用轮询处理跳跃——每帧查"跳键现在按住吗"——玩家按住跳键不放,游戏每一帧都会判定"在按住",角色会**每一帧都跳一次**(或者按你的实现,只跳一次,但松开重按的行为很奇怪)。你需要的是"刚按下的那一瞬间触发跳",这是事件语义。反过来,如果你只用事件处理移动——每次按键/松键触发一次事件——玩家按住不放,只触发一次"按下"事件,你拿到这一次事件后,后续怎么知道玩家还在按?你得自己维护"按住状态",这就退化成轮询了。

**好的输入系统两种都提供**。`ActionSet` 里的 `held`(轮询)和 `pressed_this_frame`(事件)就是两套并存。游戏逻辑根据动作性质选用:移动用 `held` 或 `axis`,跳跃攻击用 `pressed`。

事件的另一个用途是和 `game-feel-01` 的**输入缓冲**(input buffer)对接。输入缓冲存的不是"按住状态",是"按下事件"——它需要在玩家**按下**的那一刻把意图写入 buffer,然后过期。所以"按下"必须是事件,不能是轮询状态。回忆一下 `game-feel-01` 的代码:

```rust
// 在 §1 的 update_player 里:
if input.pressed(Action::Jump) {  // 事件语义
    player.jump_buffer.press();   // 把事件交给 buffer
}
// 而 buffer 的消费(consume)在物理 step 里做,见 game-feel-01
```

这就是为什么这一篇是 `game-feel-01` 的 prereq 反过来读——`game-feel-01` 的缓冲**消费**这一篇**产出**的事件。两篇是上下游。

**输入采样时机**(input sampling timing)是事件/轮询之外另一个关键点,直接影响输入延迟(见 `game-feel-01` §6)。回忆一下:输入延迟的"第二段"是"游戏从队列取事件到状态更新的延迟"——如果你的游戏在帧的**末尾**才轮询输入,这一帧的渲染就用不上这次的输入,白白多一帧延迟。**正确做法是在每一帧的最开头轮询**。这是 phase-1 平台层(platform layer)的职责——平台层在事件循环里把 OS 的事件收集起来,游戏主循环(`09B-1` 的固定步长循环)每一帧开头先调用 `poll_events()`,把所有待处理事件抽出来,喂给 InputMapper,然后再做物理 step 和渲染。

```rust
// 主循环骨架(简化,真实结构见 09B-1):
loop {
    let frame_start = Instant::now();

    // 1. 平台层:把 OS 事件队列里所有待处理事件抽出来
    //    注意:这是帧的第一件事,不能放后面
    platform.poll_os_events();
    keyboard.poll_events();
    gamepad.poll_events();  // gilrs 的事件队列

    // 2. 翻译:把所有设备的原始输入,变成 ActionSet
    let actions = input_mapper.translate(&[&keyboard, &gamepad]);

    // 3. 固定步长模拟(09B-1):消费 actions,推进物理
    while accumulator >= FIXED_DT {
        sim.step(&actions, FIXED_DT);
        accumulator -= FIXED_DT;
    }

    // 4. 渲染
    renderer.draw();

    // 5. 等下一帧(vsync 或 sleep)
    frame_limiter.wait(frame_start);
}
```

注意一个微妙处:fixed step 是 1/60 秒,但渲染可能跑在 144 Hz——也就是说一帧渲染之间,可能没有 step。`actions` 是这一帧采样的输入,**在多个 step 之间是同一个值**——玩家在两个 step 之间按下跳键,这个跳要等下一次采样才能被 step 看到。这就是输入延迟的一部分来源。极致优化的游戏会让 step 也用最新采样,但这破坏了"固定步长"的纯净——一般不这么做,接受这一帧延迟。

## 7 · 无障碍:动作抽象是无障碍输入的地基

讲到这里,你应该能看出来:**动作抽象本身就是无障碍(accessibility)设计的核心**。这一节不重复 `accessibility-short.md` 的全部内容(那篇是 phase-7 的无障碍总论),只讲输入工程和无障碍的交集。

无障碍输入的本质,是**让每个玩家用自己能用的方式,触发同一套动作**。运动障碍玩家可能用 Xbox Adaptive Controller(本质就是一组大按钮 + 脚踏板接口,通过标准 gamepad API 接入),你的游戏只要支持 gamepad(gilrs),就自动支持它——Adaptive Controller 在 gilrs 看来就是一个普通手柄。视觉障碍玩家可能用屏幕阅读器配合单键操作,你的游戏只要支持重绑定,玩家就能把所有动作绑到几个最方便的键上。认知障碍玩家可能需要"按一下切换"而不是"长按",这种模式切换(见下面)住在动作层。

输入工程对无障碍的具体贡献,有三个层次:

**第一层,重映射**。这是无障碍的最低要求,也是欧盟 EAA 2025 的法律要求。§3 讲的重绑定机制,本身**就是**无障碍的核心——玩家根据自己的身体条件,把动作绑到任何能按的键上。一个用嘴叼棍操作的玩家,可能只能按两三个键;重映射让他把"最重要的几个动作"绑到这几个键上,游戏就能玩。`accessibility-short.md` §3 提到的 KeyBindings struct,本质就是这一篇的 InputBindings 的简化版。**重映射不是无障碍的"额外功能",是动作抽象的自然产物**——只要你的输入系统用了动作抽象,重绑定几乎是免费的。

**第二层,模式切换(hold vs toggle)**。有些动作的设计是"长按"——比如冲刺要按住 Shift,攀爬要按住对应键。运动障碍玩家长时间按住困难(肌肉疲劳),需要"按一下切换"——按一下进入冲刺,再按一下退出。这种模式切换应该在**动作层**实现,不在游戏逻辑里。InputMapper 维护每个动作的 `HoldToggle` 状态,玩家在设置里选:

```rust
/// 每个动作的"激活模式"。
#[derive(Clone, Copy, PartialEq)]
pub enum ActivationMode {
    /// 标准:按住 = 激活,松开 = 失活(默认)
    Hold,
    /// 切换:每次按下翻转激活状态。无障碍模式常用。
    Toggle,
}

pub struct ActionMode {
    modes: HashMap<Action, ActivationMode>,
    /// Toggle 模式下,当前是否"逻辑上激活"
    toggled_on: HashMap<Action, bool>,
}

impl ActionMode {
    /// 把"物理按下事件"翻译成"逻辑激活状态",考虑模式。
    pub fn is_active(&mut self, action: Action, pressed_this_frame: bool, held: bool) -> bool {
        match self.modes.get(&action).copied().unwrap_or(ActivationMode::Hold) {
            ActivationMode::Hold => held,  // 标准:看物理按住
            ActivationMode::Toggle => {
                if pressed_this_frame {
                    let cur = *self.toggled_on.get(&action).unwrap_or(&false);
                    self.toggled_on.insert(action, !cur);
                }
                *self.toggled_on.get(&action).unwrap_or(&false)
            }
        }
    }
}
```

注意 Toggle 模式有个**反直觉的设计点**:松开事件不应该影响逻辑激活状态(否则和 Hold 没区别)。Toggle 模式下,只有"按下"事件能切换状态,松开被忽略。这就是为什么 §1 把事件(Pressed)和状态(Held)分开——Toggle 模式需要的是事件,不是状态。

**第三层,自适应控制器和切换控制**(switch control)。严重运动障碍玩家可能用单一开关(头部吹气、眨眼)配合"扫描选择"——屏幕上的可选项循环高亮,玩家在想要的那一项高亮时触发开关。这种交互完全不是传统按键能表达的,但它的输出可以包装成一个"按某 PhysicalKey"事件,接入你的 InputSource 接口。**只要你的输入系统是抽象的**,任何奇怪的输入设备都能接入,游戏逻辑不用改一行。这就是抽象层的红利——你以为在为"普通手柄玩家"设计抽象,实际上为所有可能的输入设备铺好了路。

`accessibility-short.md` 里讲的所有这些(色盲模式、字幕、慢动作),都建立在"输入是抽象的"这个地基上。如果你的输入系统从 day 1 就用了动作抽象,无障碍改造的成本极低;如果你硬编码了按键,后期改造成本会爆炸(那是"返工",不是"添加")。这就是为什么 `accessibility-short.md` §8 反复强调"无障碍 day 1 纳入架构"——架构的核心一条就是动作抽象。

## 8 · 生产现实:你不会从零手搓

讲完原理,讲工程现实。在真实项目里,你**很少**会从零写一个 InputMapper——成熟的游戏框架都已经提供了。但**动作抽象的设计仍然是你必须做对的**——框架给你工具,你决定动作集怎么定义、绑定表怎么组织、模式切换怎么暴露给玩家。这是设计决策,不是工程实现决策。

**Rust 生态**:

- **bevy_input**:Bevy 引擎的输入模块。原生支持 KeyboardInput / MouseButton / GamepadEvent,有 `Input<KeyCode>` 资源做状态查询,有 `Axis<...>` 做模拟值。Bevy 0.13+ 引入了 `bevy::input::InputSystem` 和 `bevy::ecs::system::SystemParam`,可以方便地写 `fn player_ctrl(keys: Res<Input<KeyCode>>, ...)`。Bevy 没有内置的"动作层",社区有 `leafwing-input-manager` 这个 crate,它提供完整的动作抽象(Action、InputMap、重新绑定 UI),API 设计和这一篇讲的基本一致。如果你用 Bevy,强烈推荐用 leafwing-input-manager 而不是自己写。

- **gilrs**:这一篇用的手柄库。它和具体引擎解耦,可以独立用(像这一篇的 GamepadSource 这样包装),也可以接入 Bevy(实际 bevy_input 的 gamepad 部分就是基于 gilrs)。

- **macroquad / ggez / winit**:这些更轻量的 Rust 游戏框架,通常给你 winit 的 KeyboardInput 事件 + 自己处理手柄(gilrs)。它们不提供动作抽象,你需要按这一篇的方式自己写一层。

**其他语言/引擎**(参考,便于横向理解):

- **Unreal Engine**:Enhanced Input 系统(UE5 推荐)。完整动作抽象——`UInputAction`(动作)、`UInputMappingContext`(映射表)、`UInputModifier`(修饰器,死区、敏感度曲线)、`UInputTrigger`(触发条件)。设计成熟,直接对应这一篇的概念。
- **Unity**:新的 Input System(package)取代了旧的 Input Manager。`InputAction`(动作)、`InputActionAsset`(绑定表,可序列化)、`InputBinding`(物理输入到动作的映射)。Unity 的 Input System 在多设备抽象上做得尤其好(`InputDevice` 基类)。
- **Godot**:Input Map 系统。`InputEvent`(物理事件)、`InputAction`(动作),在 Project Settings 里可视化配置。Godot 4 加了更多死区控制。

**通用原则**:无论用什么框架,你的职责是——

1. **定义清楚动作集**(Action 枚举)。这是游戏设计的一部分,要和设计师一起定。动作名应该是动词(Move、Jump、Attack、Interact),不是按键名。
2. **决定哪些动作支持重绑定,哪些不支持**。一般所有玩法动作可重绑,系统动作(全屏切换、暂停)有默认但不重绑。
3. **决定模式切换策略**(哪些动作支持 Hold / Toggle)。
4. **决定死区、敏感度曲线的默认值**,并暴露成 CVar / 设置项。

这些都是设计决策,框架帮不了你。这一篇的价值在于让你**理解框架背后的设计**,这样你用框架时知道每个配置项意味着什么、改错了会怎样。

## 9 · 在你 HH 项目里动手(做中学红线)

把这一篇的所有东西落到你的 Handmade Hero 项目。这是把"动作抽象"从概念变成你肌肉记忆的环节。

第一步,**前提检查**。先确认你的 HH 主循环已经按 `09B-1` 改造成固定步长,并且按 `game-feel-01` 实现了输入缓冲。这一篇的 ActionSet 要喂给缓冲,所以缓冲必须先在。

第二步,**重构输入:从硬编码到动作层**。把你 HH 里所有 `if key == W`、`if key == Space` 这种代码,全部删掉。新增 `Action` 枚举(至少 MoveForward、MoveBackward、MoveLeft、MoveRight、Jump、Attack),新增 `InputBindings`、`InputMapper`、`ActionSet`(直接用这一篇的代码)。把 `gilrs` 加到 Cargo.toml,实现 `KeyboardSource` 和 `GamepadSource`。在主循环开头,调用所有 source 的 `poll_events`,喂给 InputMapper,得到 ActionSet。

第三步,**改写角色控制**。把你的角色控制代码改成只读 ActionSet——`if actions.pressed(Action::Jump) { jump_buffer.press() }`、`let mv = vec2(actions.axis(MoveRight) - actions.axis(MoveLeft), ...)`。代码里**不应出现任何 KeyCode 或 Button**。改完后,把默认绑定改成 QWERTY + gamepad 各一份(用 `InputBindings::default_qwerty()`)。

第四步,**加死区**。在你的 GamepadSource 里,读摇杆值的地方,过一遍 `apply_radial_deadzone`。死区值先用 0.05 / 0.95,然后接 CVar(`g_gamepad_deadzone_inner`, `g_gamepad_deadzone_outer`)。

第五步,**存档加载绑定**。用 serde 把 InputBindings 序列化到一个 `bindings.json`。游戏启动时,如果文件存在就加载,不存在就用默认。绑定变化时(玩家改了)自动保存。

第六步,**做一个简单的重绑定 UI**。最简版:在 dev console(见 `09B-4`)里输入 `rebind Jump`,游戏进入"等待按键"模式,玩家按下任何键,那个键绑到 Jump。完整版做一个设置菜单,但 dev console 版本足以验证机制。

第七步,**验证多设备热插拔**。这一步是这一篇最有意思的验证。游戏跑起来,先用键盘玩(角色移动、跳跃、攻击都正常)。然后**插上手柄**(或启动一个虚拟手柄),**不重启游戏**,用手柄推摇杆移动角色,用手柄 A 键跳跃。角色应该立刻响应手柄。拔掉手柄,回到键盘,角色立刻响应键盘。如果你的代码实现了 §4 讲的"每帧轮询所有设备",这个热插拔应该自然工作。

第八步,**关闭单个能力,感受回归**(和 `game-feel-01` §9 一样的练习思路)。把死区设成 0(`g_gamepad_deadzone_inner = 0`),玩两分钟——你应该立刻看到"角色自己飘",这就是没死区的后果。把所有手柄绑定删掉,只剩键盘——手柄玩家立刻不能玩,这就是没多设备的后果。把动作抽象**临时**改回 `if key == W`(只在一处),玩两分钟——你应该感受到"我改一个键要改代码"的痛苦,这就是没动作抽象的后果。每个能力单独关掉,你才亲身体会到它解决了什么。

做完这一篇的红线,你的 HH 输入应该从"只认 W"进化到"AZERTY、手柄、左手党、运动障碍玩家都能玩"。这是一个值得 commit 的里程碑,提交信息可以写 "refactor input to action abstraction with rebinding and multi-device support"。

## 10 · 练习

**练习一(概念,Lv1)**:有人跟你说"动作抽象就是加了个 enum,没什么用"。想清楚反驳他。提示——回忆 §0 的四个朋友:AZERTY、手柄、左撇子、运动障碍,你的硬编码把这四个人全锁在外面。把"硬编码"换成"动作抽象",这四个人怎么分别受益?具体说哪条能力(AZERTY 默认表、多设备绑定、重绑定、模式切换)对应哪个朋友。讲清楚动作抽象不是"加了个 enum",而是"加了一层 indirection,这层 indirection 同时解锁了五个能力"。

**练习二(动手,Lv2)**:完成前面 §9 的全部八步,提交 commit。重点保证第七步(多设备热插拔)和第八步(关闭单个能力感受回归)你真的做过——光写代码不验证,不算完成。热插拔需要你有一只 USB 手柄或能装虚拟手柄软件(x360ce、vJoy)。

**练习三(设计,Lv3)**:在你的 HH 里实现**模式切换**(Hold / Toggle)给冲刺(Dash)动作。设计上:Dash 默认 Hold(按住 = 冲刺,松开 = 停),但在设置里允许切换成 Toggle(按一下进入冲刺,再按一下退出)。考虑:Toggle 模式下,如果玩家在冲刺中按了 Pause,游戏暂停,恢复后 Dash 还是"激活"状态吗?讲清楚你的设计选择和理由。这个练习的关键是体会"模式切换住在动作层,不在游戏逻辑层"——游戏逻辑还是只问"Dash 现在激活吗",它不知道激活是 Hold 来的还是 Toggle 来的。

**练习四(进阶,Lv4)**:做一个**敏感度曲线**(sensitivity curve)给你的 HH 摇杆。死区之后,摇杆值不直接用,过一条曲线:写一个 LUT(lookup table),把归一化后的 [0, 1] 输入映射到 [0, 1] 输出。LUT 用 CVar 可调(`g_stick_curve` 0 = 线性,1 = 指数,2 = S 曲线)。把三种曲线都试一遍,玩你的 HH,感受差别——线性 = 推一半走一半,指数 = 推一点走很慢推到底走全速(精细瞄准友好),S 曲线 = 中间一段敏感两端平缓(适合赛车)。讲清楚每种曲线适合什么类型的游戏。这个练习是 §5 死区的进阶,让你体会"模拟输入的处理不止死区,还有曲线"。

## 11 · 延伸阅读与下一篇

这一篇的设计思想,源头是游戏行业十几年的输入工程实践总结。理论方面,**Scott Meyers** 在《Effective C++》里讲的"加一层 indirection"是软件工程的通用原则,动作抽象是它在游戏输入上的应用。更具体的游戏输入理论,推荐 **Squirrel Eiserloh** 的 GDC 演讲"The Matrix Captured"(GDC 2018)——讲输入抽象和数据驱动,虽然是 C++ 例子但概念完全适用于 Rust。

工程实践方面,几个值得读的源码:

- **leafwing-input-manager**(https://github.com/Leafwing-Studios/leafwing-input-manager):Rust 生态最完整的动作抽象实现,Bevy 集成。直接读它的 `Action`、`InputMap`、`Axis` 源码,和这一篇的概念一一对应。
- **bevy_input**(Bevy 引擎):`crates/bevy_input/src/`,看它怎么抽象 KeyboardInput / GamepadEvent / MouseButton。
- **Unreal Engine Enhanced Input 文档**:虽然不是 Rust,但它的设计是行业最成熟的,`UInputAction`、`UInputMappingContext`、`UInputModifier` 这套抽象值得理解。它的 Modifier 系统(死区、曲线、缩放都作为可堆叠的 modifier)比这一篇的实现更优雅,值得借鉴。
- **Unity Input System 文档**:同理,`InputAction` / `InputActionAsset` 的设计。

Rust 生态:
- **gilrs**:https://gitlab.com/gilrs-project/gilrs。手柄库的源码,看它怎么把 Xbox / PS / Switch 手柄抽象成统一的 `Button` / `Axis`。
- **accesskit**:https://github.com/AccessKit/accesskit。Rust 的无障碍桥接,和这一篇 §7 讲的 a11y 集成。

这一篇和教程里几个模块紧密绑定。**`game-feel-01-input-and-timing-feel.md`** 是它的下游——这一篇产出的"动作"喂给那篇的"输入缓冲"。两篇一起读,你才完整理解"从玩家物理按下到游戏执行"的整条管线。**`accessibility-short.md`**(phase-7)是无障碍的总论,这一篇 §7 是它在输入层的特化。**`localization-short.md`**(phase-7)讲本地化,默认绑定表(法语 AZERTY、德语 QWERTZ)是本地化在输入层的体现。**`09B-4-cvars-and-dev-console.md`**(phase-9)是工具链——这一篇的所有死区、敏感度、缓冲窗口都应该是 CVar,运行时可调。**phase-1 的平台层**是输入采样的源头——OS 事件队列在平台层收集,这一篇的 InputSource 接口包的就是它。**`game-state-management.md`** 讲游戏状态机,UI 状态(菜单 / 游戏中 / 暂停)会影响哪些动作可激活——比如暂停时 Jump 不该触发,这种"动作可用性"是状态机管理的,这一篇的动作层负责"采样",状态机负责"过滤"。

下一篇(game-feel 序列的后续)会从输入继续往上搭——讲**相机手感**(`game-feel-02-camera.md`)。相机的平滑跟随、look-ahead(角色移动方向上提前露出一点视野)、相机 deadzone(注意这个 deadzone 和摇杆 deadzone 是两回事——一个是相机不动的范围,一个是摇杆不响应的范围,概念同源但用途不同),都会显著影响游戏感觉。如果说这一篇讲的是"游戏怎么接收玩家的意图",camera 那篇讲的是"游戏怎么展示自己"。

最后一句:这一篇讲的所有概念——动作抽象、映射是数据、多设备归一化、死区、事件 vs 轮询——加起来不到 200 行 Rust 代码。但它们是"任何玩家都能玩你的游戏"的全部基础。写完它们,验证热插拔,关掉再打开每个能力,亲手感受差别——这个流程走完,你就理解了为什么所有专业游戏项目都把"输入抽象成动作"作为 day 1 的工程决策,而不是后期可加可不加的功能。
