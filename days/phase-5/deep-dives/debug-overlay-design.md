# Debug Overlay 设计:数据收集 → 布局 → 渲染

> Phase 5 前 35 集都在造 debug 系统。这个 deep-dive 把 overlay 架构讲透:**数据收集 → 布局 → 渲染** 三段流水线,以及 immediate-mode UI 如何与渲染管线整合。

## 1 · Overlay 架构总览

in-game overlay 的核心问题:

- **数据从哪来**:profiler events、debug variables、watch values
- **怎么布局**:文字、曲线、树形、表格
- **怎么渲染**:CPU 软渲染或 GPU text rendering
- **怎么交互**:点击、悬停、键盘

四阶段流水线:

```
游戏代码 → [收集 events] → [布局 UI elements] → [渲染 batched draw calls] → 屏幕
              ↑                                                       ↓
              └─────── 输入(键盘 / 鼠标)←──── [输入处理] ←──────────┘
```

每帧重新跑整个流水线(immediate-mode)。

## 2 · 阶段 1:数据收集

### 2.1 profiler event 流

```rust
// 游戏代码每帧 push events
TIMED_BLOCK!("physics_step");  // 宏展开成 begin / end event
debug_value("player/pos", state.player.pos);

// 收集器
pub struct ProfilerState {
    pub events: Vec<DebugEvent>,
    pub frame_index: u32,
    pub thread_id: ThreadId,
}
```

事件类型(Day 213):

- `BeginBlock { guid, time }`
- `EndBlock { guid, time }`
- `Value { guid, value }`
- `Toggle { guid, on }`

### 2.2 begin/end 配对

profiler block 用栈算法:

```rust
pub fn begin_block(&mut self, guid: u64, time: u64) {
    self.events.push(DebugEvent::Begin { guid, time, frame: self.frame_index });
    self.block_stack.push((guid, time));
}

pub fn end_block(&mut self, time: u64) {
    if let Some((guid, start_time)) = self.block_stack.pop() {
        self.events.push(DebugEvent::End { guid, time, frame: self.frame_index });
        let duration = time - start_time;
        self.durations.entry(guid).or_default().push(duration);
    }
}
```

block 嵌套(嵌套函数调用):

```rust
fn game_update() {
    begin_block("physics");      // outer
    for body in bodies {
        begin_block("integrate");  // inner
        integrate(body);
        end_block();  // integrate
    }
    end_block();  // physics
}
```

stack 保证 begin/end 配对,即使函数提前 return(用 RAII / Drop guard)。

### 2.3 跨帧 ring buffer

只保留最近 N 帧 event:

```rust
pub struct RingBuffer<T, const N: usize> {
    data: [T; N],
    head: usize,  // 下一个写入位置
    len: usize,
}

impl<T: Clone + Default, const N: usize> RingBuffer<T, N> {
    pub fn push(&mut self, value: T) {
        self.data[self.head] = value;
        self.head = (self.head + 1) % N;
        if self.len < N { self.len += 1; }
    }

    pub fn iter_recent(&self, count: usize) -> impl Iterator<Item = &T> {
        let start = if self.len == N {
            self.head  // 最旧的在 head(因为刚 wrap)
        } else {
            0
        };
        let actual_count = count.min(self.len);
        (0..actual_count).map(move |i| &self.data[(start + i) % N])
    }
}
```

UI 画历史曲线时,用 `iter_recent(300)` 拿最近 300 帧。

### 2.4 线程安全(Day 178)

profiler event 来自多线程(game + workers):

```rust
use std::sync::Mutex;

pub struct ThreadSafeProfiler {
    inner: Mutex<ProfilerState>,
}

impl ThreadSafeProfiler {
    pub fn begin_block(&self, guid: u64) {
        let time = rdtsc();
        let mut guard = self.inner.lock().unwrap();
        guard.begin_block(guid, time);
    }
}
```

或用 thread-local profiler + 主线程合并(避免锁)。Casey Day 182 优化 ThreadId 获取,避免 `std::thread::current()` 开销。

## 3 · 阶段 2:布局

### 3.1 Layout cursor

immediate-mode layout 用 cursor:

```rust
pub struct UiContext {
    cursor: Vec2,
    line_height: f32,
    indent: u32,
    max_x_in_line: f32,
}

impl UiContext {
    pub fn advance(&mut self, w: f32, h: f32) -> Rect {
        let rect = Rect { x: self.cursor.x, y: self.cursor.y, w, h };
        self.cursor.x += w;
        self.max_x_in_line = self.max_x_in_line.max(self.cursor.x);
        rect
    }

    pub fn new_line(&mut self) {
        self.cursor.x = self.indent as f32 * 16.0;
        self.cursor.y += self.line_height;
    }

    pub fn indent(&mut self) { self.indent += 1; }
    pub fn unindent(&mut self) { self.indent = self.indent.saturating_sub(1); }
}
```

游戏代码:

```rust
ui.text("Hello");
ui.same_line();  // 不 advance y
ui.text("World");
ui.new_line();
ui.indent();
ui.text("Indented");
```

### 3.2 不同 widget

每个 widget 用 cursor + 自己大小:

```rust
impl UiContext {
    pub fn text(&mut self, s: &str) {
        let size = self.measure_text(s);
        let rect = self.advance(size.x, size.y);
        self.draw_text(s, rect);
    }

    pub fn button(&mut self, label: &str) -> bool {
        let size = self.measure_text(label) + padding(10.0, 5.0);
        let rect = self.advance(size.x, size.y);
        let clicked = self.handle_click(rect);
        self.draw_button(rect, label, clicked);
        clicked
    }

    pub fn plot_line(&mut self, history: &[f32], width: f32) {
        let height = 60.0;
        let rect = self.advance(width, height);
        self.draw_line_chart(history, rect);
    }
}
```

### 3.3 自动布局 vs 手动

immediate-mode 默认 **flow layout**(水平 + 自动换行):

```rust
ui.text("FPS:");
ui.same_line();
ui.text(format!("{:.1}", fps));
ui.new_line();
ui.text("Frame Time:");
ui.same_line();
ui.text(format!("{:.2}ms", frame_time));
```

复杂场景(网格、表格)需要显式位置:

```rust
ui.cursor = Vec2::new(100.0, 50.0);  // 跳到位置
ui.text("Positioned text");
```

### 3.4 树形布局

debug hierarchy(Day 219)展开需要 indent:

```rust
fn draw_node(ui: &mut Ui, name: &str, value: &DebugValue, depth: u32) {
    for _ in 0..depth { ui.indent(); }
    ui.text(&format!("{}: {}", name, value));
    for _ in 0..depth { ui.unindent(); }
}

fn draw_tree(ui: &mut Ui, tree: &TreeNode) {
    draw_node(ui, &tree.name, &tree.value, 0);
    if let Some(children) = tree.children() {
        for child in children {
            draw_tree(ui, child);  // 递归,depth 自然增加
        }
    }
}
```

## 4 · 阶段 3:渲染

### 4.1 CPU 软渲染(早期)

Casey 在 Day 176-234 用 CPU 软渲染:

- 文字:bitmap font,直接 blit 像素
- 矩形 / 线:画 framebuffer
- 曲线:连线

简单粗暴,几百 widget 几微秒。

### 4.2 GPU 渲染(后期)

Day 235+ 切 GL 后,overlay 也用 GPU:

```rust
struct OverlayRenderer {
    text_shader: Program,
    text_atlas: Texture,  // 字体图集
    line_vao: VertexArray,
    line_vbo: Buffer,
}

impl OverlayRenderer {
    fn render(&mut self, gl: &Context, draw_calls: &[DrawCall]) {
        unsafe {
            gl.disable(glow::DEPTH_TEST);  // overlay 永远在前
            gl.enable(glow::BLEND);
            gl.blend_func(glow::SRC_ALPHA, glow::ONE_MINUS_SRC_ALPHA);

            gl.use_program(Some(self.text_shader));

            // Batch:把所有文字 vertex 收集到一个 VBO
            let mut verts: Vec<TextVertex> = vec![];
            for call in draw_calls {
                collect_text_verts(&mut verts, call);
            }
            self.upload_and_draw(gl, &verts);
        }
    }
}
```

### 4.3 文字渲染

游戏 overlay 文字渲染方案:

- **Bitmap font**:每个字符是预渲染的小图,UV 索引。简单,字体不灵活
- **Distance field font**:bitmap + distance field 算法,支持任意缩放
- **GPU font rasterization**:用 compute shader 在 GPU 端栅格化(fancy)

casey 选 bitmap font(简单)。Rust crate:`glyph_brush`、`rusttype`、`ab_glyph`。

```rust
use glyph_brush::{GlyphBrush, GlyphBrushBuilder};

let font = glyph_brush::FontRef::bytes(&font_bytes).unwrap();
let mut brush: GlyphBrush<DepthTarget> = GlyphBrushBuilder::using_font(font).build();

// 每帧
brush.queue(Section::new("Hello, World!").with_screen_position((10.0, 10.0)));
brush.process_queued(|rect, tex_data| {
    // 上传 tex_data 到 GL
}).unwrap();
```

### 4.4 Batched draw call

immediate-mode UI 每帧几百 widget。如果每个 widget 一个 draw call,GPU 调用开销大。**Batching** 把同类型 widget 收集到一次 draw call:

```rust
struct DrawLayer {
    rects: Vec<RectVertex>,    // 所有矩形
    texts: Vec<TextVertex>,    // 所有文字
    lines: Vec<LineVertex>,    // 所有线段
}

impl DrawLayer {
    fn add_rect(&mut self, rect: Rect, color: Color) {
        // 矩形 = 2 个三角形 = 6 个 vertex
        self.rects.extend_from_slice(&[
            RectVertex { pos: rect.top_left(), color },
            RectVertex { pos: rect.top_right(), color },
            RectVertex { pos: rect.bottom_right(), color },
            // 第二个三角形...
        ]);
    }

    fn flush(&mut self, gl: &Context) {
        // 一次 draw call 画所有矩形
        unsafe {
            gl.buffer_data_u8_slice(glow::ARRAY_BUFFER, bytemuck::cast_slice(&self.rects), glow::DYNAMIC_DRAW);
            gl.draw_arrays(glow::TRIANGLES, 0, self.rects.len() as i32);
        }
        self.rects.clear();
    }
}
```

每帧 3 个 draw call(rects / texts / lines)而不是几百。

## 5 · 阶段 4:输入处理

### 5.1 鼠标

```rust
struct Input {
    mouse_pos: Vec2,
    mouse_down: bool,
    mouse_clicked: bool,  // 这一帧 down 边沿
    mouse_released: bool,
}

impl Ui {
    fn button(&mut self, rect: Rect) -> bool {
        let hovered = rect.contains(self.input.mouse_pos);
        hovered && self.input.mouse_clicked
    }
}
```

### 5.2 焦点

如果一个 widget 在 drag(滑块拖动),其他 widget 不该响应点击。用全局 focus:

```rust
struct Ui {
    active_widget: Option<u64>,  // 当前 drag 的 widget ID
}

impl Ui {
    fn slider(&mut self, id: u64, value: &mut f32) -> bool {
        let rect = self.layout_slider();
        let hovered = rect.contains(self.input.mouse_pos);

        if self.active_widget.is_none() && hovered && self.input.mouse_clicked {
            self.active_widget = Some(id);
        }
        if self.active_widget == Some(id) && self.input.mouse_released {
            self.active_widget = None;
        }

        let changed = if self.active_widget == Some(id) {
            *value = compute_new_value(rect, self.input.mouse_pos);
            true
        } else {
            false
        };
        changed
    }
}
```

### 5.3 键盘

文本输入框需要键盘焦点:

```rust
struct Ui {
    text_input_focus: Option<u64>,
    text_buffer: String,
}

impl Ui {
    fn text_input(&mut self, id: u64, value: &mut String) -> bool {
        let rect = self.layout_text_input(value);
        let hovered = rect.contains(self.input.mouse_pos);

        if hovered && self.input.mouse_clicked {
            self.text_input_focus = Some(id);
            self.text_buffer = value.clone();
        }

        if self.text_input_focus == Some(id) {
            for key in &self.input.keys_pressed {
                // 处理 backspace / enter / char
            }
            *value = self.text_buffer.clone();
            true
        } else {
            false
        }
    }
}
```

## 6 · 完整 overlay 渲染

```rust
fn render_debug_overlay(
    state: &GameState,
    profiler: &ProfilerState,
    debug: &DebugState,
    input: &Input,
    ui: &mut UiContext,
    draw_layer: &mut DrawLayer,
) {
    ui.set_cursor(Vec2::new(10.0, 10.0));

    // FPS
    ui.text(&format!("FPS: {:.1}", profiler.fps()));
    ui.new_line();

    // Frame time 曲线
    let frame_times: Vec<f32> = profiler.history("frame_time").into();
    ui.plot_line(&frame_times, 200.0);
    ui.new_line();

    // Profiler blocks(按耗时排序)
    ui.text("Profiler:");
    ui.new_line();
    ui.indent();
    let mut blocks: Vec<_> = profiler.top_blocks(10).into_iter()
        .map(|(name, dur)| (name.to_string(), dur))
        .collect();
    blocks.sort_by(|a, b| b.1.cmp(&a.1));
    for (name, dur) in &blocks {
        ui.text(&format!("{}: {:.2}ms", name, *dur as f32 / 1_000_000.0));
        ui.new_line();
    }
    ui.unindent();

    // Debug variables(树形)
    ui.text("Variables:");
    ui.new_line();
    ui.indent();
    draw_tree(ui, &debug.root);
    ui.unindent();

    // Flush 所有 draw calls
    draw_layer.flush(&state.gl);
}
```

## 7 · 性能分析

debug overlay 自身的耗时也是 debug 目标。**递归**:overlay 显示 overlay 自己的耗时。

```rust
let overlay_start = rdtsc();
render_debug_overlay(...);
let overlay_time = rdtsc() - overlay_start;
debug_value("debug/overlay_time_ms", overlay_time as f32 / 1_000_000.0);
```

典型耗时:

- 数据收集:10 μs(扫 events)
- 布局:50 μs(几百 widget)
- 渲染:200 μs(几万 vertex)
- 总:~260 μs = 0.26 ms

144 FPS 帧预算 6.9ms,overlay 占 4%。

## 8 · 关联 Day

- [day176](../day176.md) 调试基础
- [day196](../day196.md) immediate-mode UI
- [day210](../day210.md) 数据存储合并
- [day212](../day212.md) UI 集成到游戏代码
- [day229](../day229.md) 排序渲染元素

## 9 · 延伸阅读

- Dear ImGui internals:https://github.com/ocornut/imgui/wiki
- egui rendering:https://github.com/emilk/egui/tree/master/epaint
- glyph_brush:https://docs.rs/glyph_brush
