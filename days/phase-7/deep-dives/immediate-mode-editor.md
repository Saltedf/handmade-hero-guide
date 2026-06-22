# Immediate-Mode 编辑器:vs Retained-Mode 的架构、性能、可访问性

> 你的游戏需要调试菜单——按 F1 显示 FPS,按 F2 调光强,按 F3 切换 wireframe。你怎么写这个 UI?HTML / Qt / GTK 的那一套按钮、回调、布局,在游戏里太重。**Immediate-Mode GUI**(立即模式 GUI)是游戏行业的方案——简单、动态、不需要"保留状态"。本文从"为什么"讲到"怎么写一个能用的",让你看懂 Dear ImGui / egui / Nuklear 的源码。

## 0 · 为什么游戏需要不同的 UI 模式

Web 程序员用 React 写 UI:声明一个组件树,框架保留状态、对比差异、更新 DOM。这叫**保留模式**(retained mode)。Qt、GTK、WinForms、WPF、Android View 系统——全部是保留模式。

但游戏调试 UI 用保留模式,你会发现:

1. **状态同步地狱**:游戏数据每帧变,你要写代码把数据"推"到 UI 控件;用户改 UI,又要把控件状态"拉"回游戏数据。双向同步,bug 高发
2. **动态控件难**:调试面板要根据场景显示不同控件(选中敌人时显示敌人属性,选中光时显示光属性)。保留模式要 destroy / create 控件,代码乱
3. **样式不匹配**:游戏是 GPU 渲染的,Qt 是 CPU 渲染 + 软件合成,两者风格对不齐

**Immediate-Mode GUI**(IMGUI)抛弃这一切:

```rust
// 每帧重新画整个 UI
fn draw_debug_ui(ui: &mut Ui, game: &mut Game) {
    ui.text(&format!("FPS: {}", game.fps));
    game.light_intensity = ui.slider("Light", 0.0..=10.0, game.light_intensity);
    if ui.button("Reset") {
        game.reset();
    }
}
```

每帧调用,每帧"重建"整个 UI。没有"控件对象",没有"事件回调",没有"状态同步"。**调用即声明**。

这个想法是 Casey Muratori 在 2005 年演讲 "Semantics of Retained Mode UIs" 里系统化的(实际游戏行业用了更早)。Dear ImGui / egui / Nuklear / conrod 全是这个模式。

**读完这一篇你能**:
- 解释 immediate-mode 和 retained-mode 的本质区别
- 用 Rust 实现一个能用的 immediate-mode UI 库
- 知道何时用 IMGUI(调试 UI)何时用 retained(玩家 UI)
- 看 Dear ImGui 源码不被吓到
- 评估自己项目该选哪种 UI 模式

### 真实场景:为什么 Casey 强烈推荐 IMGUI

让我们把镜头拉近。假设你做一款 3D 游戏,需要一个 debug overlay——按 F1 显示 FPS、F2 调光强、F3 切换 wireframe。

**用保留模式**(Qt / GTK / Web):你需要写 N 个 widget 类,每个 widget 有 state(visible / value / hover),通过 signal / callback 处理事件。每帧游戏数据变,你要更新 widget state;用户改 widget,你要回写到游戏。**双向同步代码占整个 UI 系统的 50%**。

**用立即模式**(Dear ImGui / egui):每帧重新调用 `ui.slider(...)`、`ui.button(...)`,**没有 widget 类、没有 state 同步**。代码量减少 60-80%。

Casey 在 HH 视频里反复演示这个差异。他写 debug UI 用 IMGUI,几千行代码搞定了完整的 debug overlay + 变量编辑器 + profiler。如果用保留模式,同样功能要几万行代码。

### IMGUI 的工业级应用

**Dear ImGui**(C++,2014-现在):游戏行业标准。Unity、Unreal、Godot 的 debug overlay 都基于 Dear ImGui 风格。Discord、Valve、Blizzard 内部工具用 Dear ImGui。

**egui**(Rust,2020-现在):Rust IMGUI 金标。Bevy 引擎的 inspector、RustRocket、Rerun.io 都用 egui。

**Nuklear**(C,2016-现在):嵌入式友好,单文件。

**conrod**(Rust,2015-2020):Pure Rust IMGUI,早期项目。

**ICE Editor**(Unity 内部):Unity 用 IMGUI 做 editor,2010+。

**Unreal Editor UMG**:混合模式——editor 用 IMGUI,runtime UI 用 retained。

这些是工业级 IMGUI 的"全家福"。

### IMGUI 的"哲学深度"

IMGUI 不只是技术,还是一种**哲学**——**函数式编程**的应用。

- **Retained mode** 类似 OOP——对象有 state,方法操作 state,对象长期存在。
- **Immediate mode** 类似 FP——函数无 state,输入 → 输出,不保留任何东西。

Casey 在演讲里说:**"IMGUI 是函数式 UI"**。这是它**为什么简洁**的根本原因——没有 state = 没有 state 同步 bug。

OOP UI 的复杂度来自 state 同步。FP UI 的简洁来自无 state。这是软件工程的**根本权衡**。

### 实战练习:读完本文后

读完本文,你应该做这些项目练手:

1. **写一个 100 行的 mini IMGUI**。从零开始,Rust + wgpu + 一个 font。支持 button、slider、text。
2. **用它做一个 debug overlay**。在你的游戏里加 FPS、坐标、cheat key 显示。
3. **加 layout 系统**。水平 / 垂直 layout,padding / margin。
4. **加 clip rect**。Scrollable list。
5. **加 docking**。可选,复杂。

时间预算:每个 1-3 天。完成后你彻底理解 IMGUI。

## 1 · Retained Mode vs Immediate Mode:核心对比

### Retained Mode(保留模式)

经典 Web / 桌面:

```javascript
// 创建一次
const button = document.createElement('button');
button.textContent = 'Reset';
button.onclick = () => game.reset();
document.body.appendChild(button);

// 后续:框架保留 button,管理事件、样式、布局
```

特点:

- 控件有"持久身份",创建后存活
- 状态显式存储(`button.textContent = ...`)
- 事件通过回调(`onclick`)
- 框架负责布局、渲染、生命周期

### Immediate Mode(立即模式)

游戏调试 UI:

```rust
// 每帧调用
fn draw_ui(ui: &mut Ui, game: &mut Game) {
    if ui.button("Reset") {  // 返回 true 表示"这一帧被点击"
        game.reset();
    }
}
```

特点:

- 控件**无持久身份**——每帧重建
- 状态存在调用方代码(`game.light_intensity` 直接是源真值)
- 事件通过**返回值**(`button()` 返回 true 表示这一帧点击)
- 调用方负责布局(或 UI 库提供自动布局,但每次调用都重新计算)

### 关键洞察

IMGUI 的核心洞察:**UI 的"状态"应该和数据的状态合一,不该有独立的 UI 状态**。游戏数据(`light_intensity`)本身就是真值,UI 只是显示和编辑它的视图。每帧重画,数据驱动,没有同步问题。

## 2 · IMGUI 的核心机制

### ID 系统

每个控件需要一个唯一 ID 用于:

- 鼠标点击检测(知道"我"被点了)
- 键盘焦点(知道"我"现在有焦点)
- 动画状态(知道"我"上一帧的状态)

最简单:用**调用顺序**作为 ID。第一个调用的 button 是 ID 0,第二个是 ID 1,依此类推。这就是为什么 IMGUI 的 UI 函数必须**每帧按相同顺序调用**——顺序错位,ID 就乱。

```rust
// 每帧 ID 一致
ui.button("Reset");   // ID 0
ui.button("Pause");   // ID 1
ui.button("Quit");    // ID 2
```

更高级的 IMGUI(Dear ImGui)用**字符串标签**作为 ID:

```cpp
ImGui::Button("Reset##main_menu");  // "##" 后是 ID,前是显示文本
```

### 鼠标交互

```rust
impl Ui {
    fn button(&mut self, label: &str) -> bool {
        let id = self.next_id();
        let rect = self.layout.allocate(self.button_size);
        
        let hovered = self.mouse.pos.is_inside(rect);
        let active = hovered && self.mouse.pressed;
        
        // 画
        self.draw_rect(rect, if active { PRESSED_COLOR } 
                              else if hovered { HOVER_COLOR }
                              else { NORMAL_COLOR });
        self.draw_text(label, rect.center());
        
        // 返回:这一帧被点击了吗?
        active && self.mouse.just_released
    }
}
```

每行注释:

- `next_id()` — ID 分配
- `layout.allocate(size)` — 自动布局(下面讲)
- `hovered` — 鼠标在按钮上
- `active` — 鼠标在按钮上且按下
- 返回 `just_released` 表示"按下 → 释放"——按钮被点击的语义

### 文本输入(更复杂)

文本输入需要"持久状态"(光标位置、选区、当前文本)。但 IMGUI 不存持久状态——怎么搞?

答:**用 ID 作为 key,把持久状态存到 UI 库内部的全局表**。

```rust
struct Ui {
    text_inputs: HashMap<WidgetId, TextInputState>,
}

struct TextInputState {
    text: String,
    cursor_pos: usize,
    selection: Option<(usize, usize)>,
    // ...
}

impl Ui {
    fn text_input(&mut self, id: &str, value: &mut String) {
        let widget_id = hash(id);
        let state = self.text_inputs.entry(widget_id)
            .or_insert_with(TextInputState::default);
        
        // 处理键盘
        if self.has_focus(widget_id) {
            for c in &self.input.typed_chars {
                state.text.push(*c);
            }
            // 处理 backspace、delete、方向键...
        }
        
        // 更新外部 value
        *value = state.text.clone();
        
        // 画
        self.draw_text(&state.text, ...);
    }
}
```

每段注释:

- UI 库内部存"持久状态",用 ID 索引
- 调用方传 `&mut String` 接收最新文本
- 状态在 UI 库里,数据在调用方——但每次调用同步,所以"看起来"合一

这就是 Dear ImGui 的设计——大部分控件无状态,少数(text input、scrollbar)用内部表存。

## 3 · 布局

Retained Mode 用 CSS / Qt Layout 等显式布局。IMGUI 用**自动布局**:

```rust
impl Layout {
    fn allocate(&mut self, size: Vec2) -> Rect {
        // 简单:线性堆叠
        let rect = Rect {
            pos: self.cursor,
            size,
        };
        self.cursor.y += size.y + self.spacing;
        rect
    }
}
```

每调一次 `allocate`,光标下移。换行用 `ui.new_line()` 或 `ui.same_line()`。

高级 IMGUI 提供更复杂的布局:

- 水平 / 垂直组
- 表格(列对齐)
- 树状结构(折叠 / 展开)

布局参数(对齐、间距、padding)在每次调用时传,不是预设。这就是为什么 IMGUI 代码看起来很"程序化":

```rust
ui.horizontal(|ui| {
    ui.label("Name:");
    ui.text_input(&mut self.name);
});
ui.horizontal(|ui| {
    ui.label("Age:");
    ui.slider(&mut self.age, 0..=120);
});
```

`horizontal` 闭包让里面的控件按水平排列,出闭包后回到垂直。

## 4 · 渲染

IMGUI 的渲染极简:每帧 UI 库产出**绘制命令列表**(draw list),游戏直接渲染。

```rust
struct DrawCmd {
    vertices: Vec<Vertex>,  // [pos, uv, color]
    indices: Vec<u32>,
    texture: TextureId,
}

impl Ui {
    fn render(&self) -> Vec<DrawCmd> {
        self.draw_list.clone()
    }
}
```

游戏把 DrawCmd 转成 OpenGL/Vulkan 顶点缓冲,渲染。整个过程 < 1ms(几百个控件)。

## 5 · 完整 IMGUI 骨架(Rust)

```rust
use glam::*;

#[derive(Default)]
pub struct InputState {
    pub mouse_pos: Vec2,
    pub mouse_down: bool,
    pub mouse_just_pressed: bool,
    pub mouse_just_released: bool,
    pub typed_chars: Vec<char>,
}

#[derive(Default)]
pub struct Ui {
    pub input: InputState,
    pub cursor: Vec2,
    pub draw_cmds: Vec<DrawCmd>,
    pub hot: Option<u32>,      // 鼠标悬停的控件
    pub active: Option<u32>,   // 当前交互的控件
    pub next_widget_id: u32,
}

impl Ui {
    pub fn begin(&mut self, input: InputState) {
        self.input = input;
        self.cursor = Vec2::new(10.0, 10.0);
        self.hot = None;  // 每帧重算
        self.draw_cmds.clear();
        // active 保留(用于按住拖动)
    }
    
    pub fn button(&mut self, label: &str) -> bool {
        let id = self.next_widget_id;
        self.next_widget_id += 1;
        
        let size = Vec2::new(80.0, 24.0);
        let rect = Rect { pos: self.cursor, size };
        self.cursor.y += size.y + 4.0;
        
        let hovered = rect.contains(self.input.mouse_pos);
        if hovered {
            self.hot = Some(id);
        }
        
        let mut clicked = false;
        if hovered && self.input.mouse_just_pressed {
            self.active = Some(id);
        }
        if self.active == Some(id) && self.input.mouse_just_released {
            self.active = None;
            if hovered {
                clicked = true;
            }
        }
        
        let color = if self.active == Some(id) {
            [0.4, 0.4, 0.4, 1.0]
        } else if hovered {
            [0.3, 0.3, 0.3, 1.0]
        } else {
            [0.2, 0.2, 0.2, 1.0]
        };
        self.draw_rect(rect, color);
        self.draw_text(label, rect.center(), [1.0, 1.0, 1.0, 1.0]);
        
        clicked
    }
    
    pub fn slider(&mut self, label: &str, value: &mut f32, min: f32, max: f32) {
        let id = self.next_widget_id;
        self.next_widget_id += 1;
        
        let size = Vec2::new(150.0, 16.0);
        let rect = Rect { pos: self.cursor, size };
        self.cursor.y += size.y + 4.0;
        
        let hovered = rect.contains(self.input.mouse_pos);
        if hovered {
            self.hot = Some(id);
        }
        if hovered && self.input.mouse_just_pressed {
            self.active = Some(id);
        }
        if self.input.mouse_just_released {
            self.active = None;
        }
        
        if self.active == Some(id) {
            // 鼠标位置决定 value
            let t = ((self.input.mouse_pos.x - rect.pos.x) / rect.size.x)
                .clamp(0.0, 1.0);
            *value = min + t * (max - min);
        }
        
        let t = (*value - min) / (max - min);
        let knob_x = rect.pos.x + t * rect.size.x;
        
        self.draw_rect(rect, [0.2, 0.2, 0.2, 1.0]);
        self.draw_rect(
            Rect { pos: Vec2::new(knob_x - 4.0, rect.pos.y - 2.0),
                   size: Vec2::new(8.0, rect.size.y + 4.0) },
            [0.8, 0.8, 0.8, 1.0],
        );
        self.draw_text(
            &format!("{}: {:.2}", label, value),
            rect.pos + Vec2::new(0.0, -14.0),
            [1.0, 1.0, 1.0, 1.0],
        );
    }
    
    pub fn end(&mut self) -> Vec<DrawCmd> {
        std::mem::take(&mut self.draw_cmds)
    }
    
    fn draw_rect(&mut self, rect: Rect, color: [f32; 4]) {
        // 简化:实际用 vertex/index buffer
        self.draw_cmds.push(DrawCmd::Rect { rect, color });
    }
    
    fn draw_text(&mut self, text: &str, pos: Vec2, color: [f32; 4]) {
        self.draw_cmds.push(DrawCmd::Text { text: text.into(), pos, color });
    }
}

#[derive(Copy, Clone)]
struct Rect {
    pos: Vec2,
    size: Vec2,
}

impl Rect {
    fn contains(&self, p: Vec2) -> bool {
        p.x >= self.pos.x && p.x <= self.pos.x + self.size.x &&
        p.y >= self.pos.y && p.y <= self.pos.y + self.size.y
    }
    fn center(&self) -> Vec2 {
        self.pos + self.size * 0.5
    }
}

enum DrawCmd {
    Rect { rect: Rect, color: [f32; 4] },
    Text { text: String, pos: Vec2, color: [f32; 4] },
}
```

每段注释:

- `hot` 和 `active` 是 IMGUI 的核心状态——`hot` = 鼠标悬停,`active` = 当前按住
- `begin` 时清 hot(每帧重算),`active` 跨帧保留(为了按住拖动)
- `button` 返回 `clicked`:只在"按下 + 释放在同一控件上"为 true
- `slider` 用 active 状态跟踪拖动
- `draw_cmds` 每帧重建,游戏一次渲染

## 6 · 使用示例

```rust
fn main() {
    let mut ui = Ui::default();
    let mut light = 1.0_f32;
    let mut show_fps = true;
    
    // 游戏主循环
    loop {
        let input = poll_input();
        ui.begin(input);
        
        // 调试面板
        if show_fps {
            ui.label(&format!("FPS: {}", fps));
        }
        ui.checkbox("Show FPS", &mut show_fps);
        ui.slider("Light Intensity", &mut light, 0.0, 10.0);
        if ui.button("Reset Light") {
            light = 1.0;
        }
        
        let cmds = ui.end();
        render(cmds);
    }
}
```

每帧 UI 代码"重新画一遍",数据直接和游戏变量交互。**没有同步代码**。

## 7 · 可访问性(Accessibility)

IMGUI 一个被诟病的点:**可访问性差**。

- 屏幕阅读器(JAWS / NVDA / VoiceOver)依赖 UI 控件树和 ARIA 角色,IMGUI 没有显式控件树
- 键盘导航(Tab 切换控件)需要状态,IMGUI 默认无状态
- 高对比度模式依赖控件身份,IMGUI 无持久身份

这是真实问题。解决方案:

1. **egui 的 a11y 集成**:egui 通过 `egui-winit` + AccessKit 桥接到系统 a11y 服务,把每帧的 UI 转成"虚拟控件树"
2. **Dear ImGui 的局限**:基本无 a11y 支持,只适合调试 UI,不适合发布
3. **混合模式**:玩家 UI 用 retained(Web / Qt / 系统组件),调试 UI 用 immediate

游戏行业共识:**调试 UI 用 IMGUI(开发者用,无 a11y 需求),玩家 UI 用 retained 或保留模式 a11y 化的 IMGUI(egui + AccessKit)**。

## 8 · 何时用 IMGUI

| 场景 | 推荐 |
|---|---|
| 游戏内调试 UI | IMGUI |
| 编辑器 UI(场景编辑器、属性面板) | IMGUI |
| 数据可视化仪表盘 | IMGUI |
| 玩家面对的 UI(主菜单、HUD) | Retained(IMGUI 也行) |
| 移动 App UI | Retained |
| 需要完整 a11y 的产品 | Retained |

游戏调试 UI / 编辑器 = IMGUI 标配。发布产品 UI = 看情况。

## 9 · 性能

### IMGUI 性能特点

- **CPU 重**:每帧重建控件树、重算布局、重画
- **GPU 轻**:输出 draw list,一次渲染
- **无开销子集**:可选是否调用某些 UI 代码(`if debug_mode { draw_debug_ui(); }`)

典型开销:几百个控件 < 1ms CPU。对游戏帧率影响极小。

### Retained 性能

- **CPU 轻**:状态变化才更新
- **GPU 重**:可能多层合成(DOM/CSS)
- **创建/销毁开销**:控件树变化时大

Web 浏览器复杂页面每帧 ~10ms CPU。游戏里太重。

## 10 · 历史

- 1990s:游戏内部工具用 IMGUI 风格(Quake console、Half-Life 调试)
- 2005: Casey Muratori 演讲 "Semantics of Retained Mode UIs",系统化 IMGUI 概念
- 2014: Omar Cornut 发布 Dear ImGui(C++),工业标准
- 2017-: egui(Rust)、Nuklear、conrod 等大量 IMGUI 库
- 2020s: egui + AccessKit 解决 a11y

## 11 · 关联 Day

- **铺垫**:Day 176 debug overlay;Day 200 input handling;Day 220 文本渲染
- **当天**:本篇是 immediate-mode UI 专题
- **后续**:Day 500+ 编辑器实战;Day 600+ 发布版 UI

## 12 · 变式训练

### Lv1 · 概念辨析

**题**:为什么 IMGUI 没有显式的"控件树"还能工作?retained mode 的"树"承担了什么角色?

**参考解答**:Retained mode 的"控件树"承担三个角色:(1) 持久身份(每个控件有唯一对象)(2) 布局/绘制顺序(树决定渲染顺序)(3) 事件路由(点击事件沿树冒泡)。IMGUI 不需要树,因为:(1) 身份用"调用顺序 + ID hash"模拟;(2) 顺序就是绘制顺序;(3) 事件直接 return,无需路由。"调用顺序"取代"控件树"——这就是 immediate 的本质。

### Lv2 · 动手实践

**题**:在你的游戏里加 IMGUI 调试面板。要求:FPS 显示、3 个 slider 调光强、按 R 重置。

完成标准:面板可见、可交互、不卡帧。

**参考解答**:见上面的 Rust 骨架。关键:

1. 实现最小 IMGUI(button + slider + label)
2. 每帧前 `ui.begin(input)`,每帧后 `ui.end()` 渲染
3. UI 代码直接读写 game 变量

### Lv3 · 迁移设计

**题**:用 IMGUI 思路设计一个"游戏内 REPL"(命令行)。每帧画输入框 + 输出文本,输入命令执行。要解决哪些问题?

**提示**:文本输入需要持久状态(光标、文本),用 ID → state 映射。命令历史需要内存,跨帧保留。

### Lv4 · 开源贡献

**题**:egui 是 Rust 主流 IMGUI,GitHub: https://github.com/emilk/egui

1. clone 它
2. 看 `crates/egui/src/`:`ui.rs`、`widgets/`
3. 看 AccessKit 集成(`crates/egui-winit/src/`)
4. 可能的贡献:加新 widget / 改进文档 / 加键盘导航支持

## 13 · Rust / Arch 落地代码

完整的 IMGUI 调试面板(用 egui):

```toml
# Cargo.toml
[dependencies]
eframe = "0.29"  # egui + 窗口
```

```rust
// src/main.rs
use eframe::egui;

fn main() -> eframe::Result {
    let options = eframe::NativeOptions::default();
    eframe::run_simple_native("Debug UI", options, |ctx, _frame| {
        egui::SidePanel::left("debug").show(ctx, |ui| {
            ui.heading("Debug");
            ui.label(&format!("FPS: {:.0}", 60.0));  // 替换实际 FPS
            
            ui.add(egui::Slider::new(&mut 1.0_f32, 0.0..=10.0).text("Light"));
            
            if ui.button("Reset").clicked() {
                println!("Reset");
            }
            
            ui.collapsing("Camera", |ui| {
                ui.label("Camera settings...");
            });
        });
    })
}
```

每行注释:

- `eframe` — egui 的窗口框架,自动创建窗口、处理输入
- `SidePanel::left` — 左侧面板
- `Slider::new(&mut value, range)` — slider 直接绑定变量
- `clicked()` — 返回这一帧是否被点击
- `collapsing` — 折叠组

Arch 工具链:

```bash
# 装 Rust
curl https://sh.rustup.rs -sSf | sh
source ~/.cargo/env

# 创建项目
cargo new my_ui
cd my_ui
cargo add eframe
cargo run --release

# 看渲染性能
sudo pacman -S renderdoc
renderdoc &
# 抓一帧看 egui 的 draw list

# Profile
sudo pacman -S perf valgrind
perf record ./my_ui
perf report
```

排错:

```bash
# 1. 控件 ID 冲突
#    报错:Two widgets with same ID
#    原因:多次调用同名 button
#    解决:加 ## unique 后缀
#    egui: ui.button("My##unique");

# 2. 拖动 slider 时鼠标不在 slider 上但还跟着
#    原因:active 状态没释放
#    排查:检查 mouse_just_released 处理

# 3. 字体错乱
#    原因:egui 默认字体不全(CJK)
#    解决:加载中文字体
#    ctx.set_fonts(FontDefinitions::with_cjk());
```

## 14 · 延伸阅读

本仓库本地:

- `days/phase-7/deep-dives/asset-pipeline-architecture.md` — 编辑器需要加载资产
- `days/phase-7/deep-dives/gltf-and-model-loading.md` — 编辑器编辑模型

外部稳定 URL:

- Casey Muratori IMGUI 演讲: https://caseymuratori.com/000_2015.html
- Dear ImGui 文档: https://github.com/ocornut/imgui/wiki
- egui 文档: https://docs.rs/egui
- AccessKit(无障碍): https://accesskit.dev/
- Nuklear(单文件 C): https://github.com/Immediate-Mode-UI/Nuklear

真实开源源码:

- Dear ImGui: https://github.com/ocornut/imgui
- egui: https://github.com/emilk/egui
- conrod(Rust IMGUI): https://github.com/PistonDevelopers/conrod
- iced(Rust,retained 风格): https://github.com/iced-rs/iced
