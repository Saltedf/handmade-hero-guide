# Immediate-Mode UI:从 Casey 到 Dear ImGui

> Day 196 引入 immediate-mode UI,Day 212 把 debug draw 也变成 immediate-mode。这个 deep-dive 把 immediate-mode UI 讲透,对比 Casey 自制 debug UI、Dear ImGui、egui、iced 这四个实现,让你理解为什么 immediate-mode 在游戏工具里占统治地位。

## 0 · 为什么 immediate-mode 赢了

写 UI 有两种风格:

- **Retained mode**(传统):UI 是持久对象树,改属性触发重绘。Qt / MFC / GTK / Win32 / DOM 都是这个风格
- **Immediate mode**(现代):每帧重新声明整个 UI,无持久状态。Casey HH / Dear ImGui / egui / iced 都是

游戏工具行业几乎全切到 immediate mode,原因:

1. **无状态同步 bug**:retained mode 的"状态不一致"问题(immediate 立刻反映代码状态)消失
2. **Hot-reload 友好**:每帧重新声明,代码改了下一帧立刻生效,无残留状态
3. **简单**:`if button("Click me") { do_thing(); }` 一行写完
4. **性能**:无 widget 树遍历、无 layout 复杂计算

但 immediate mode 有代价:

- 每帧重画 → CPU 占用相对高(但绝对值极小,几十 μs)
- 不能"set and forget"(代码必须每帧调)
- ID 系统必须解决"同一个 widget 在不同位置"的冲突

## 1 · Casey 的 debug UI(教学极简版)

Casey 在 HH Day 196+ 的 debug UI 是 immediate mode 的最简版本:

```c
// 每帧调用
if (debug_button("Show FPS", mouse_pos)) {
    toggle_debug_show_fps();
}
```

`debug_button` 函数:

1. 计算 button rect(基于当前 layout cursor)
2. 检查 mouse_pos 是否在 rect 内
3. 检查 mouse 是否这一帧 click
4. 如果 click,返回 true
5. 画 button(背景色 + 文字)
6. advance layout cursor

无持久 widget 对象——所有信息从函数参数来,所有状态(被 hover? 被 click?)在函数内计算。

**ID 隐含在调用顺序里**:`debug_button` 第一次调用 = button #1,第二次 = button #2。如果代码控制流改变(button 出现在 if 里),ID 会错乱。这是 Casey 的简化 tradeoff。

## 2 · Dear ImGui(工业标准)

Dear ImGui(2014 年 Omar Cornut 创建)是 Casey 思想的工业级实现,成为游戏工具事实标准:

```cpp
ImGui::Begin("My Window");
if (ImGui::Button("Click Me")) {
    counter++;
}
ImGui::Text("Counter = %d", counter);
ImGui::End();
```

特点:

- **显式 ID**:每个 widget 接受可选 ID 参数,解决 Casey 的"调用顺序 ID"问题
- **Layout 系统**:自动排版(水平 / 垂直 / 自由)
- **持久状态**:用 ID hash 把"展开 / 折叠"等状态存到全局 map
- **C++ 模板**:类型安全的 vector / color input
- ** docking / multi-viewport**:多窗口、可拖出主窗口

Dear ImGui 用在:

- 游戏开发工具(Unreal Insights、Unity Editor 扩展)
- 数据可视化(Blender 视图、Substance Painter)
- 实时调试(机器人、汽车仪表)

## 3 · egui(Rust 生态)

egui(Rust immediate-mode UI,2020 年)是 Dear ImGui 的 Rust 风格重写:

```rust
egui::CentralPanel::default().show(&ctx, |ui| {
    if ui.button("Click Me").clicked() {
        counter += 1;
    }
    ui.label(format!("Counter = {}", counter));
});
```

特点:

- **Rust 所有权友好**:无 raw pointer,用 Context + Id 索引状态
- **wasm 支持**:编译到 web,跑在 canvas
- **集成熟**:与 winit / glow / wgpu 集成
- **API 链式**:`ui.button("...").clicked()` 优雅

egui 在 Rust 游戏开发社区事实标准。`bevy_egui` 集成 bevy 引擎。

## 4 · iced(Elm 风格的"第三种")

iced 是 Rust 的 Elm 风格 UI 库——**介于 immediate 和 retained 之间**:

```rust
// The Elm Architecture: Model-View-Update
enum Message {
    ButtonClicked,
}

fn view(state: &State) -> Element<Message> {
    column![
        button("Click Me").on_press(Message::ButtonClicked),
        text(format!("Counter = {}", state.counter)),
    ].into()
}

fn update(state: &mut State, msg: Message) {
    match msg {
        Message::ButtonClicked => state.counter += 1,
    }
}
```

特点:

- **声明式 + 不可变**:每帧 view 函数返回新 UI 树(类似 React JSX)
- **消息驱动**:用户交互发 Message,update 函数处理
- **跨平台**:desktop / web / native

iced 是 retained 模式的现代化,不是 immediate mode。但它继承了 immediate 的"无状态同步 bug"——view 是纯函数,状态在外部 model。

## 5 · 四者对比

| 特性 | Casey | Dear ImGui | egui | iced |
|---|---|---|---|---|
| 范式 | Immediate | Immediate | Immediate | Elm(MVU) |
| 语言 | C | C++ | Rust | Rust |
| 状态管理 | 调用顺序 | ID hash | ID hash | External model |
| Layout | 手动 | 自动 | 自动 | 自动 |
| Docking | 无 | 有 | 有(部分) | 无 |
| Web | 无 | emscripten | wasm | wasm |
| Hot-reload | 是 | 是 | 是 | 是(部分) |
| 用例 | 教学 | 游戏 tools | Rust 游戏 tools | Rust 应用 |

## 6 · Immediate-mode 实现原理

### 6.1 ID 系统

每帧重新声明,但状态(展开 / 折叠 / 输入文字)需要跨帧保留。解决:**ID hash**。

```rust
struct Ui {
    id_stack: Vec<u64>,  // 嵌套 ID
}

impl Ui {
    fn push_id(&mut self, id: u64) { self.id_stack.push(id); }
    fn pop_id(&mut self) { self.id_stack.pop(); }
    fn current_id(&self) -> u64 {
        // hash 整个 stack
        self.id_stack.iter().fold(0, |acc, &id| hash_combine(acc, id))
    }
}
```

游戏代码:

```rust
ui.push_id(42);
if ui.button("Click") { /* ... */ }  // ID = hash(42, "button")
ui.pop_id();
```

### 6.2 Layout cursor

```rust
struct Ui {
    cursor_pos: Vec2,
    max_x: f32,  // 当前行最大 x
    line_height: f32,
}

impl Ui {
    fn advance(&mut self, w: f32, h: f32) -> Rect {
        let rect = Rect { x: self.cursor_pos.x, y: self.cursor_pos.y, w, h };
        self.cursor_pos.x += w;
        self.max_x = self.max_x.max(self.cursor_pos.x);
        rect
    }

    fn new_line(&mut self) {
        self.cursor_pos.x = 0;
        self.cursor_pos.y += self.line_height;
    }
}
```

### 6.3 输入处理

```rust
struct Input {
    mouse_pos: Vec2,
    mouse_down: bool,
    mouse_clicked_this_frame: bool,
}

impl Ui {
    fn button(&mut self, label: &str) -> bool {
        let rect = self.advance(100.0, 30.0);
        let hovered = rect.contains(self.input.mouse_pos);
        let clicked = hovered && self.input.mouse_clicked_this_frame;

        // 渲染
        let color = if clicked { Color::ACTIVE }
                    else if hovered { Color::HOVER }
                    else { Color::NORMAL };
        self.draw_rect(rect, color);
        self.draw_text(label, rect.center());

        clicked
    }
}
```

### 6.4 状态持久化(展开 / 折叠)

```rust
struct CollapsingHeader {
    open: HashMap<u64, bool>,  // 持久状态
}

impl CollapsingHeader {
    fn show(&mut self, ui: &mut Ui, id: u64, label: &str, content: impl FnOnce(&mut Ui)) {
        let is_open = self.open.entry(id).or_insert(false);
        if ui.button(if *is_open { "[-]" } else { "[+]" }) {
            *is_open = !*is_open;
        }
        ui.same_line();
        ui.text(label);
        if *is_open {
            ui.indent();
            content(ui);
            ui.unindent();
        }
    }
}
```

`HashMap<u64, bool>` 跨帧保留,但通过 ID 索引,hot-reload 后状态保留。

## 7 · 性能:为什么 immediate mode 不慢

直觉上"每帧重新声明"听起来浪费。实际:

- 单个 widget 处理几微秒(几条 if + 几个 draw call)
- 一帧 UI 几十到几百 widget,总 CPU < 1ms
- 没有 widget 树遍历、没有 layout 复杂计算
- 没有 dirty tracking 开销

对比 retained mode:

- Qt / GTK 的 widget 树可能几千节点
- Layout 是 O(N²)(有些情况)
- 状态变更触发 signal / slot,大量回调
- 实际更慢

immediate mode 在 UI 层面更快,但**渲染层**仍要 batch(egui 内部收集所有 widget 的 vertex,一次 draw call)。

## 8 · 工程实践

### 8.1 何时用 immediate mode

- 游戏 debug UI / 工具
- 内部编辑器
- 快速原型
- 实时数据可视化

### 8.2 何时用 retained mode

- 复杂桌面应用(VS Code、Photoshop)
- 移动 app(iOS / Android 原生)
- 需要无障碍(accessibility)支持
- 需要复杂文本编辑(富文本)

### 8.3 Rust 选择

- 游戏工具:egui
- 跨平台应用:iced / slint / tauri
- Web:tutorial 用 egui(wasm)或 iced(wasm)

## 9 · 阅读源码

- Dear ImGui:`https://github.com/ocornut/imgui` 看 `imgui.cpp` 的 `Button()` 函数
- egui:`https://github.com/emilk/egui` 看 `egui/src/widgets/button.rs`
- iced:`https://github.com/iced-rs/iced` 看 `core/src/element.rs`

## 10 · 关联 Day

- [day196](../day196.md) immediate-mode 入门
- [day212](../day212.md) 调试 UI 集成到游戏代码
- [day220](../day220.md) 层级中显示数据块
- [day251](../day251.md) 调试层级完成

## 11 · 延伸阅读

- Immediate Mode GUI 论文(原 Casey 视频):https://caseymuratori.com/000_002
- Dear ImGui FAQ:https://github.com/ocornut/imgui/blob/master/docs/FAQ.md
- egui demo:https://github.com/emilk/egui/blob/master/egui_demo_lib/src/demo.rs
