
# 深入:无障碍 a11y(简版)

> 你做了一个游戏,UI 字体 12px,菜单选项鼠标点击,所有反馈靠颜色区分。**你在无意中拒绝了 20% 的潜在玩家**——视力障碍的看不清、运动障碍的没法精确点击、色盲分不清红绿。
>
> 无障碍(accessibility,缩写 a11y,因为 "accessibility" 有 11 个字母在 a 和 y 之间)不是"额外功能",是"让所有玩家能玩"的基本工程。CD Projekt Red 公开数据:**《赛博朋克 2077》30% 玩家用了至少一个无障碍选项**。Naughty Dog 说《最后生还者 2》超过 50% 玩家调整了 a11y 设置。**这不是边缘需求**。

## 0 · 为什么 a11y

三条理由,从商业到道德:

**市场**。全球 16% 人口有某种残疾(WHO 数据)。游戏玩家中残疾比例类似。如果你的游戏完全无视 a11y,你拒绝了 1/6 的潜在客户。**商业上不理性**。

**道德**。游戏是文化产品,所有人都有权利参与。残疾玩家经常在论坛说"我想玩 XX 但游戏没字幕我听不到对话"——这种被排除的痛苦是真实的。

**法律**。越来越多国家立法要求软件 a11y。美国 ADA(1990)、欧盟 European Accessibility Act(2025 年 6 月生效)、日本 JIS X 8341。游戏行业还在豁免边缘,但**趋势是必须合规**。

## 1 · 视障

**色盲模式**(8% 男性、0.5% 女性有某种色盲)。游戏用红绿区分敌我,红绿色盲看不清。解决方案:

- **色盲安全色板**:用 Okabe-Ito 调色板(8 色,所有色盲都能区分)
- **形状区分**:除了颜色,加形状/图标。敌人红色三角形,友方蓝色圆形——颜色失效,形状仍能区分
- ** Daltonize 后处理**:fragment shader 把颜色重新映射到色盲可见范围。Uncharted 4 用这个

**高对比度模式**。深色背景配浅色字,或者反相。文字 outline 让低视力玩家能看清。

**字体大小**。UI 字体 12px 在 4K 屏不可读。给玩家"UI scaling"选项,允许放大到 200% / 300%。**Last of Us 2 有 6 档 UI 缩放**。

**屏幕阅读器**。给盲人玩家。游戏需要把 UI 暴露给 OS 的 a11y API(Windows UI Automation、macOS NSAccessibility、Linux AT-SPI)。Rust 生态的 a11y 支持很弱(`accesskit` 是开源尝试)。

**字号 / 字体**。Dyslexia-friendly 字体(OpenDyslexic)对阅读障碍玩家友好。

## 2 · 听障

**字幕**(所有对话都有字幕,包括音效"门开了")。**70% 玩家玩游戏时不开声音**(Mute 玩家)。子字幕不只是听障玩家受益。

- 字幕字体足够大
- 字幕背景半透明黑(白字在亮背景上看不见)
- 区分说话人(用颜色或前缀)
- 同步音效字幕:[开门声]、[爆炸]

**视觉反馈替代音效**。脚步声 → 屏幕边缘震动;血量低 → 屏幕边缘红光;队友喊话 → UI 闪光。Fortnite 的 "Visualize Sound Effects" 选项是经典实现。

## 3 · 运动障碍

**按键重映射**(controller / 键盘)。所有按键可改。**这是法律要求的**(欧盟 EAA 2025 要求)。Rust 游戏里实现:

```rust
struct KeyBindings {
    jump: KeyCode,
    move_left: KeyCode,
    move_right: KeyCode,
    attack: KeyCode,
    // ...
}

impl Default for KeyBindings {
    fn default() -> Self {
        Self {
            jump: KeyCode::Space,
            move_left: KeyCode::A,
            move_right: KeyCode::D,
            attack: KeyCode::J,
            // ...
        }
    }
}

// 设置菜单允许玩家改任何键
```

**慢动作 / game speed**。运动障碍玩家反应慢。允许游戏速度调到 50% / 75%。**Celeste 的"Assist Mode"是行业标杆**——玩家可以无限体力、慢动作、无敌,游戏体验仍完整。

**Aim assist**。手柄瞄准困难,提供 magnet / slowdown 选项。所有主流射击游戏都有。

**一键多操作 / 切换模式**。需要长按的功能(冲刺、攀爬)改成"按一下切换"。**Xbox Adaptive Controller** 是为运动障碍设计的硬件——大按钮、脚踏板接口。

**去掉 QTE(quick time event)**。QTE 要求毫秒级反应,运动障碍玩家完全玩不了。如果一定要 QTE,提供"暂停 QTE 直到按键"选项。

## 4 · 认知

**难度选项**。多档难度,允许"故事模式"(几乎打不死)和"噩梦模式"。The Witcher 3、Hades、Celeste 都是好例子。

**提示系统**。卡关时给提示。Hades 的"神之赐福"是动态难度调整——玩家死得多,下一局给更强 buff。

**暂停**。**真暂停**,不是"假装暂停"——任何时刻按 ESC 暂停,游戏完全冻结,玩家可以上厕所 / 接电话 / 哄孩子。实时游戏(电竞)不能暂停,但单机游戏几乎都应该有暂停。**Cult of the Lamb 把"随时暂停"作为卖点**。

**简化 UI**。复杂 HUD 让认知负荷高的玩家过载。提供"minimal HUD"模式。

**教程可重看**。所有教程存在菜单里,玩家可以重看。Hades 的"神谕"系统。

## 5 · UI scaling / 色盲模拟器 / 字体

**UI Scaling** 工程实现:

```rust
struct Settings {
    ui_scale: f32,  // 0.5..=3.0
}

fn render_text(text: &str, x: f32, y: f32, base_size: f32, settings: &Settings) {
    let actual_size = base_size * settings.ui_scale;
    font.draw(text, x, y, actual_size);
}

fn render_ui(ui: &mut Ui, settings: &Settings) {
    ui.set_scale(settings.ui_scale);
    ui.button("Start");  // 自动按 scale 放大
}
```

UI scaling 涉及**布局重算**——字体大了,按钮要变大,容器要变宽。Immediate mode UI(egui)原生支持 scaling,retained mode 要重布局。

**色盲模拟器**(开发工具,不是给玩家用)。在开发期间看游戏"在色盲眼里长什么样"。Rust 实现:fragment shader 应用色盲矩阵:

```glsl
// 退化 4 种色盲:protanopia(红盲)、deuteranopia(绿盲)、tritanopia(蓝盲)、achromatopsia(全色盲)
vec3 simulate_protanopia(vec3 color) {
    mat3 m = mat3(
        0.567, 0.433, 0.0,
        0.558, 0.442, 0.0,
        0.0,   0.242, 0.758
    );
    return m * color;
}
```

开发时按 F8 切换色盲模式,看游戏是否可玩。**Last of Us 2 在开发期间强制团队成员轮流用各种色盲模式测试**。

**Dyslexia-friendly font**。OpenDyslexic 字体专门为阅读障碍设计(字母底部加重,防止上下颠倒)。

## 6 · Rust 实践:无障碍 API

Rust 生态 a11y 还不成熟。最相关:

- **accesskit**:Rust 写的跨平台 a11y 桥接。暴露 UI 树给 Windows UI Automation / macOS NSAccessibility / Linux AT-SPI / Web ARIA
- **egui-accesskit**:egui + accesskit 集成

```toml
[dependencies]
egui = "0.27"
egui_accesskit = "0.13"
```

```rust
use egui_accesskit::AccessKit;

fn main() -> eframe::Result<()> {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default(),
        ..Default::default()
    };
    
    eframe::run_simple_native("Accessible App", options, move |ctx, _ui| {
        // 启用 accesskit
        egui_accesskit::init(ctx, 0 /* root node id */);
        
        egui::CentralPanel::default().show(ctx, |ui| {
            if ui.button("Click me").clicked() {
                println!("Clicked!");
            }
        });
    })
}
```

启用后,屏幕阅读器(NVDA / JAWS / VoiceOver)能朗读 UI 控件。**这是盲人玩家用游戏的前提**。

游戏比应用 UI 难做 a11y——游戏 UI 不是控件树,是 3D 渲染画面。游戏 a11y 需要"音频描述"(旁白讲游戏状态)、"navigate by audio cue"等创新模式。**Last of Us 2 的 blind accessibility 是行业奇迹**——盲人玩家可以玩通整个游戏,通过音频提示。

## 7 · a11y checklist

游戏无障碍的最低 checklist:

**视觉**
- [ ] 字体可缩放(至少 200%)
- [ ] 色盲安全(颜色不是唯一区分手段)
- [ ] 高对比度模式
- [ ] UI 元素足够大(可点区域 >= 44x44 px,Apple HIG 标准)

**听觉**
- [ ] 所有对话字幕
- [ ] 音效视觉反馈替代
- [ ] 音量独立控制(主音量 / 音乐 / 音效 / 语音)

**运动**
- [ ] 全按键重映射
- [ ] 切换模式(hold vs toggle)
- [ ] 不依赖双击 / 长按精确时机
- [ ] Aim assist(射击游戏)
- [ ] 难度选项

**认知**
- [ ] 随时暂停(单机)
- [ ] 教程可重看
- [ ] 检查点足够密集
- [ ] 简化 HUD 选项

**硬件**
- [ ] 支持 Xbox Adaptive Controller(本质是标准 gamepad API,只要支持 gamepad 就支持)
- [ ] 支持自定义输入设备(Steam Input)
- [ ] 不依赖 motion control(或提供按键替代)

这个 checklist 来自 [Game Accessibility Guidelines](https://gameaccessibilityguidelines.com/),业界标准。

## 8 · 反模式

**反模式 1:"普通玩家优先"**。设计师说"加 a11y 会破坏 normal 玩家体验"。**错**——a11y 是可选的,默认 off。普通玩家体验完全不变。

**反模式 2:"我们的目标用户不需要"**。所有玩家都从 a11y 受益。字幕对静音玩游戏的玩家有用,UI scaling 对 4K 屏玩家有用。**通用设计原则:为边缘设计的产品对所有人都更好**。

**反模式 3:a11y 最后做**。游戏做完才加字幕、可重映射,成本极高。**应该**:架构层考虑——所有 UI 字符串可外化(配合 i18n)、所有输入抽象成 action(不是硬编码 keycode)、所有 UI 控件可缩放。

**反模式 4:把 a11y 当"困难模式"**。"色盲模式"按钮放在"难度选项"旁边是错误 framing。a11y 是适配,不是挑战。**应该**:放在独立"Accessibility"菜单。

## 9 · 延伸

- Game Accessibility Guidelines:https://gameaccessibilityguidelines.com/(业界圣经,分 Basic / Intermediate / Advanced)
- AbleGamers Charity:https://ablegamers.org/
- Xbox Accessibility Guidelines:https://learn.microsoft.com/en-us/gaming/xbox/
- accesskit:https://github.com/AccessKit/accesskit
- "Accessibility in Games"(GDC 演讲系列)
- Last of Us 2 a11y 案例研究:https://www.playstation.com/culture/the-last-of-us-part-ii-accessibility/
- Celeste 的 Assist Mode 设计:https://maddythorson.medium.com/celeste-designing-assist-mode-656f13c7b5e4
- Can I Play That?(残疾玩家评测游戏):https://caniplaythat.com/

无障碍不是慈善,是工程,是市场,是法律。**所有游戏项目都应该从 day 1 把 a11y 纳入架构**。提前 1 个月设计,后期改造成本 10 倍。
