---
phase: 7
type: deep-dive
title_en: "UI Data Binding & State Management (Short)"
title_zh: "UI 数据绑定与状态管理(简版)"
domains: [game, rust, ui]
duration: "1.5h"
---

# 深入:UI 数据绑定与状态管理(简版)

> 你用 immediate mode 写了 200 个 UI 控件。游戏跑起来,玩家点一个按钮,UI 是变了——但是数据呢?你发现自己满屏幕写 `if ui.button("start") { game_state.start(); }`。每个 UI 控件都手动接游戏状态,每个状态变化都手动触发 UI 刷新。**UI 代码和游戏代码搅在一起,变成一碗面条**。
>
> 这就是 immediate mode UI 的代价——简单,但不 scale。当游戏复杂到 1000 个 UI 控件 + 500 个状态变量,immediate mode 的"每帧重画"变成"每帧重新连接 1000 条逻辑"。
>
> 这份简版讨论 UI 状态管理的另一条路:**数据绑定(data binding)**——把 UI 控件和游戏状态用"声明式"连接,状态变化 UI 自动更新。

## 0 · 立即模式 vs 保留模式

我们已经有 `immediate-mode-editor.md` 详细讲了 immediate mode。简单回顾:

- **Immediate mode**:每帧调用 `ui.button("foo")`,函数返回是否点击。状态在调用栈里。
- **Retained mode**:建一棵 widget 树(`Button::new().text("foo")`),引擎持有这棵树,事件通过回调投递。

Immediate mode 适合调试 UI / 工具 UI。Retained mode 适合复杂应用 UI / 大型菜单。

两者都有 trade-off:

| 特性 | Immediate | Retained |
|---|---|---|
| 心智模型 | 命令式,所见即所得 | 声明式,描述结构 |
| 状态管理 | 程序员手动 | 引擎持有 |
| 性能 | 每帧重画(简单 UI OK,复杂 UI 慢) | 仅变化时重画 |
| 动画 | 难(每帧重建) | 易(引擎追踪状态) |
| 数据流 | 双向手动 | 单向 / 双向自动 |
| 适用场景 | debug / tool / HUD | 菜单 / dialog / 设置 |

很多商业游戏用混合:HUD 用 immediate(简单、低延迟),菜单用 retained(动画、复杂结构)。

## 1 · 数据绑定:Elm / MVVM / SwiftUI 模式

数据绑定是"声明 UI 与状态关系"的技术。三个主流模式:

**Elm Architecture(Model-View-Update)**。Elm 语言首创,Rust 生态的 Iced、Yew 都用这个。

```
Model (state) → View (render UI) → Update (handle messages → new Model)
```

UI 是 Model 的纯函数。用户点击触发一个 `Message`,update 函数接受 old model + message,返回 new model。new model 触发 view 重新计算。

```rust
enum Message {
    StartGame,
    Quit,
    VolumeChanged(f32),
}

struct Model {
    screen: Screen,
    volume: f32,
}

fn view(model: &Model) -> Element<Message> {
    match model.screen {
        Screen::MainMenu => column![
            button("Start").on_press(Message::StartGame),
            slider(0.0..=1.0, model.volume, Message::VolumeChanged),
            button("Quit").on_press(Message::Quit),
        ].into()
    }
}

fn update(model: Model, msg: Message) -> Model {
    match msg {
        Message::StartGame => Model { screen: Screen::Game, ..model },
        Message::VolumeChanged(v) => Model { volume: v, ..model },
        Message::Quit => std::process::exit(0),
    }
}
```

**MVVM(Model-View-ViewModel)**。WPF / Xamarin / Android 主流。Model 是数据,ViewModel 是 Model 的 UI 友好视图,View 通过 `binding` 自动同步 ViewModel。

```csharp
// C# / WPF 示例
public class PlayerViewModel : INotifyPropertyChanged {
    private int hp;
    public int Hp {
        get => hp;
        set { hp = value; OnPropertyChanged("Hp"); }
    }
}
// XAML: <TextBlock Text="{Binding Hp}" />
// Hp 变化时 UI 自动更新
```

Rust 生态对 MVVM 支持弱,因为 MVVM 依赖运行时反射(`INotifyPropertyChanged`),Rust 没运行时反射。Slint 是 Rust 生态最接近 MVVM 的方案。

**SwiftUI / Compose 模式(声明式 + diff)**。UI 是状态的函数声明,框架 diff 新老声明,只更新变化的部分。

```swift
// SwiftUI
struct PlayerView: View {
    @State var hp: Int = 100
    var body: some View {
        Text("HP: \(hp)")
        Button("Damage") { hp -= 10 }
    }
}
```

Rust 生态里 Xilem、Floem 都在探索这个模式。

## 2 · Rust 生态:iced / egui / kas / druid / slint

Rust GUI 生态现状(2026):

**egui** — Immediate mode。最流行,适合工具 UI 和游戏内 UI。无数据绑定,程序员手动管。我们已经用过。

**iced** — Elm architecture 的 Rust 实现。声明式 + MVVM-lite。`iced` 是 Rust 后端最好的"严肃应用"GUI 库。Rust 旗舰项目(Feather Wallet、Coyim 等用)。

```toml
[dependencies]
iced = "0.13"
```

```rust
use iced::widget::{button, column, text};
use iced::{Center, Element};

pub fn main() -> iced::Result {
    iced::run("Counter", App::update, App::view)
}

#[derive(Default)]
struct App {
    count: i32,
}

#[derive(Debug, Clone, Copy)]
enum Message {
    Increment,
}

impl App {
    fn update(&mut self, message: Message) {
        match message {
            Message::Increment => self.count += 1,
        }
    }

    fn view(&self) -> Element<Message> {
        column![
            text(format!("Count: {}", self.count)).size(50),
            button("Increment").on_press(Message::Increment),
        ]
        .align_x(Center)
        .into()
    }
}
```

**Slint** — 自有 DSL 描述 UI,类似 QML。Rust 后端 + C++ / JS 后端。声明式 + 编译时数据绑定。

```slint
// .slint 文件
export component PlayerView inherits Window {
    in property <int> hp;
    
    Text {
        text: "HP: " + root.hp;
    }
}
```

Slint 是 Rust GUI 里**最像传统商业 GUI**(Qt 风格)的方案。商业友好(双授权),适合做产品的完整 UI。

**Xilem** — Raph Levien(Linebender 团队)的实验项目。声明式 + diff-based。愿景是"SwiftUI for Rust"。2026 年还在 alpha,但架构理念最先进。

**egui / iced / slint 选型**:

- 游戏 HUD / debug UI:**egui**(低延迟,简单)
- 游戏菜单 / 设置面板:**iced**(声明式,清晰)
- 完整产品 UI(包括 OS 集成):**Slint**(双授权,工业级)
- 等等 Xilem 成熟(2027+):观望

## 3 · Reactive 流派:Signal / Observable / FRP

数据绑定的底层是"响应式编程"(Reactive Programming)。三个主要抽象:

**Signal(SolidJS / leptos 风格)**。一个值 + 自动追踪的依赖关系。Signal 变化时,所有读取它的地方自动更新。

```rust
// leptos 风格(伪代码)
let count = create_signal(0);
create_effect(move || {
    println!("count is now: {}", count.get());
});
count.set(5);  // 打印 "count is now: 5"
```

Signal 是 2026 年最热的 reactive 原语,因为它性能好(细粒度追踪)、心智简单。Rust 生态的 `leptos` 用 signal 做前端。

**Observable(RxJS / ReactiveX)**。事件流 + map / filter / merge 算子。

```rust
// 伪代码
let clicks: Observable<ClickEvent> = button.on_click();
let positions = clicks.map(|c| c.position);
positions.subscribe(|p| println!("clicked at {:?}", p));
```

Observable 强大但复杂。学习曲线陡,适合复杂异步流。Rust 生态用 `futures::Stream` 表达类似概念。

**FRP(Functional Reactive Programming)**。时间是个函数,Yampa / reactive-banana 风格。学术性强,工业用得少。

游戏 UI 用 **Signal** 模式最自然——状态变化驱动 UI 重画,粒度细,性能好。

## 4 · 状态机 / 状态管理

游戏 UI 通常有"模式"——主菜单、设置、游戏中、暂停、游戏结束。这些模式之间的转换是状态机。

```rust
enum Screen {
    MainMenu,
    Settings { previous: Box<Screen> },
    InGame,
    Paused,
    GameOver { score: u32 },
}

struct GameState {
    screen: Screen,
    player_hp: i32,
    volume: f32,
    // ... 100 个其他字段
}
```

集中式 state(单一 GameState struct)的好处:**所有 UI 状态在一处可读**。坏处:state 变大,update 函数变长。

工业级方案:**state 分层**。

```rust
struct GameState {
    meta: MetaState,      // 玩家档案 / 成就 / 全局
    session: SessionState, // 单局游戏状态
    ui: UiState,          // UI 当前状态(菜单 / 游戏 / 暂停)
    settings: Settings,   // 用户的偏好(音量 / 键位)
}
```

每层独立更新,UI 只读取自己关心的层。修改音量不触发 session 重置。

**Redux / Flux 风格**:所有状态变化走 dispatcher。`game_state.dispatch(Action::VolumeChanged(0.5))`,reducer 函数处理 action 返回新 state。**Rust 里不太流行**——Rust 的 ownership 已经强制了"谁可以改 state",不需要额外 dispatcher 抽象。

**状态机库**:`statig` 是 Rust 生态最流行的层级状态机 crate。`rails` / `sm` 也是选项。对独立游戏,手写 enum + match 通常就够,不需要库。

## 5 · 实战:HH 的状态分层

给 Handmade Hero 设计状态:

```rust
// state.rs
use std::sync::Arc;
use parking_lot::RwLock;

#[derive(Clone)]
pub struct GameState {
    inner: Arc<RwLock<GameStateInner>>,
}

struct GameStateInner {
    screen: Screen,
    player: Player,
    settings: Settings,
    mods: ModList,
}

impl GameState {
    pub fn new() -> Self {
        Self {
            inner: Arc::new(RwLock::new(GameStateInner {
                screen: Screen::MainMenu,
                player: Player::default(),
                settings: Settings::default(),
                mods: ModList::default(),
            })),
        }
    }

    pub fn read<F, T>(&self, f: F) -> T
    where F: FnOnce(&GameStateInner) -> T {
        f(&self.inner.read())
    }

    pub fn write<F, T>(&self, f: F) -> T
    where F: FnOnce(&mut GameStateInner) -> T {
        f(&mut self.inner.write())
    }
}

#[derive(Clone, Debug)]
pub enum Screen {
    MainMenu,
    Settings,
    InGame,
    Paused,
    GameOver { score: u32 },
}

#[derive(Clone, Default)]
pub struct Player {
    pub hp: i32,
    pub x: f32,
    pub y: f32,
    pub inventory: Vec<Item>,
}

#[derive(Clone, Default)]
pub struct Settings {
    pub volume_master: f32,
    pub volume_music: f32,
    pub volume_sfx: f32,
    pub vsync: bool,
}
```

UI 系统读取 state:

```rust
fn render_main_menu(state: &GameState) -> UiAction {
    let action = state.read(|s| {
        // 只读 access,持有时间短
        let mut ui = ui::begin();
        if ui.button(&format!("Volume: {:.0}%", s.settings.volume_master * 100.0)) {
            UiAction::OpenSettings
        } else if ui.button("Start Game") {
            UiAction::StartGame
        } else {
            UiAction::None
        }
    });
    action
}
```

**关键模式**:`Arc<RwLock<T>>` 让多个系统(渲染、输入、网络、脚本)并发读 / 写 state。读多写少场景 RwLock 比 Mutex 高效。`parking_lot::RwLock` 比标准库快 2-3 倍,且不支持 poisoning(适合游戏)。

## 6 · 反模式

**反模式 1:UI 控件持有 state**。`Button { text: "...", pressed: false, ... }`。这种"按钮自己记 pressed 状态"的设计让 state 分散在 widget 树里,难维护。**应该**:state 集中,UI 是 state 的纯函数。

**反模式 2:全局可变 static**。`static mut VOLUME: f32 = 1.0;`。线程不安全、测试困难、模块化差。**应该**:用 `Arc<RwLock<T>>` 显式传递。

**反模式 3:deeply nested model**。`game.session.player.inventory.items[3].durability`。访问路径长,update 函数臃肿。**应该**:扁平化 state(子 struct 是合理粒度),或用 lens 库(`druid` 的 lens)。

**反模式 4:每帧 clone 整个 state**。`state.read(|s| s.clone())` 每帧 60 次,clone 一个 1MB 的 state 浪费 CPU。**应该**:read 内联回调,只 copy 需要的字段。

## 7 · 延伸

- `immediate-mode-editor.md`(immediate mode 完整讨论)
- Iced 文档:https://docs.rs/iced/
- Slint 文档:https://slint.dev/
- Leptos(Rust 前端框架,signal 模式参考):https://leptos.dev/
- "Scaling Game UIs"(GDC 2024 演讲,AAA 游戏的 state 管理)
- `days/phase-2/day041.md`(教学风格金标)

数据绑定和状态管理是 UI 工程的核心。Immediate mode 适合小 UI,数据绑定适合大 UI。两者都在 Rust 生态有成熟工具,**关键是按项目规模选对工具**。
