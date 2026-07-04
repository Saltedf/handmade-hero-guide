
# 深入:本地化与国际化(简版)

> 你的游戏发布了。销量 5000 份,大部分美国。一个日本玩家发邮件问你:"有日语版吗?"你打开 source,发现自己写满了 `ui.show_message("Game Over")` 这种硬编码英文字符串。你想翻译——结果发现游戏里有 **1200 个字符串**,分散在 50 个源文件里。**你的"英文 only"决定不是技术决定,是销售决定——你放弃了 80% 的潜在市场**。
>
> 这份简版讨论怎么让游戏"可翻译",从工具到文化适配。

## 0 · i18n vs L10n

两个缩写,经常混用但意义不同:

- **i18n(internationalization)**:让你的代码**支持**多语言。把字符串外化、用 ICU 数字格式、Unicode 文本渲染。i18n 是**工程**——改代码架构。
- **L10n(localization)**:把游戏**翻译**成具体语言。L10n 是**翻译**——找译员、改图、调 UI。

记忆口诀:**i18n 是容器,L10n 是水**。你先造多语言容器(i18n),再灌具体语言(L10n)。

数字 18 / 10 是 "internationalizatio**n**" / "localizatio**n**" 中间被省略的字母数。

## 1 · gettext vs fluent:两大流派

字符串外化(storage)的主流方案两派:

**gettext 流派**(POSIX 标准,1970s)。所有字符串都用 `_("key")` 包裹,运行时 gettext 库按当前 locale 查找翻译。

```rust
use gettextrs::gettext;
println!("{}", gettext("Game Over"));
// 英文 locale:"Game Over"
// 日文 locale:"ゲームオーバー"
```

优点:成熟,几乎所有语言都有库。缺点:键(key)就是英文原文,改英文 → 翻译失效。性别 / 复数处理笨拙(要 `ngettext`)。

**fluent 流派**(Mozilla 2017)。把翻译当成"资源文件",每个 locale 一个 `.ftl` 文件。键和值分离。

```
# locales/en-US/main.ftl
game-over = Game Over
hello-user = Hello, { $name }!

# locales/ja-JP/main.ftl
game-over = ゲームオーバー
hello-user = こんにちは、{ $name }さん!
```

```rust
let bundle = fluent_bundle(...);
let msg = bundle.get_message("hello-user").unwrap();
let args = hashmap!("name" => "Hero");
println!("{}", bundle.format_pattern(msg.value, &args));
```

优点:键和值彻底分离;支持参数化(`{ $name }`);复数 / 性别原生支持。缺点:生态比 gettext 新,工具少。

**游戏工业主流是 gettext 流派**(因为工具链成熟),但 fluent 在 Mozilla 系产品和现代 SaaS 流行。Rust 游戏:fluent-rs 是首选。

## 2 · Rust crate:fluent-rs / rust-i18n

**rust-i18n**:轻量,简单。一个 YAML 文件管所有 locale,编译时嵌入 binary。适合独立游戏。

```toml
[dependencies]
rust-i18n = "3"
```

```yaml
# locales/en.yml
en:
  game_over: "Game Over"
  hello: "Hello, {name}!"

# locales/ja.yml
ja:
  game_over: "ゲームオーバー"
  hello: "こんにちは、{name}さん!"
```

```rust
use rust_i18n::t;
rust_i18n::i18n!("locales");  // 编译时加载

fn main() {
    rust_i18n::set_locale("ja");
    println!("{}", t!("hello", name = "Hero"));
    // 输出: こんにちは、Heroさん!
}
```

rust-i18n 的设计哲学:**0 运行时开销**(宏展开成 `&'static str`)、0 外部依赖(纯 Rust)、独立游戏友好。

**fluent-rs**:Mozilla 官方 Rust 实现。功能强,生态广,但复杂度高。

```toml
[dependencies]
fluent = "0.16"
fluent-bundle = "0.16"
unic-langid = "0.9"
```

```rust
use fluent::{FluentBundle, FluentResource};
use unic_langid::LanguageIdentifier;

let en_ftl = r#"
    welcome = Welcome to Handmade Hero, { $name }!
    items-count = { $count ->
        [one] You have one item.
       *[other] You have { $count } items.
    }
"#;

let langid: LanguageIdentifier = "en".parse().unwrap();
let res = FluentResource::try_new(en_ftl.into()).unwrap();
let mut bundle = FluentBundle::new(vec![langid]);
bundle.add_resource(res).unwrap();

let msg = bundle.get_message("welcome").unwrap();
let mut args = fluent::FluentArgs::new();
args.set("name", "Hero");
let pattern = msg.value.unwrap();
let mut errors = vec![];
let output = bundle.format_pattern(pattern, Some(&args), &mut errors);
println!("{}", output);
// 输出: Welcome to Handmade Hero, Hero!
```

fluent 的**复数**语法(`{ $count -> [one] ... [other] ... }`)是它最强大的特性。每种语言的复数规则不同(英文 one/other,中文只有 other,阿拉伯文有 6 种!),fluent 内置 ICU 复数规则,自动按 locale 选对的分支。

**选型建议**:独立游戏用 `rust-i18n`(简单、编译时检查、足够);需要严肃多语言(20+ 语言)用 `fluent-rs`(更强大的复数 / 性别 / 选择)。

## 3 · 字符串外化 / ICU / 复数形式

**字符串外化**的工程要点:

1. **永不硬编码用户可见字符串**。`ui.show_message("Game Over")` 是反模式。改成 `ui.show_message(t!("game_over"))`。
2. **键命名一致**。建议 `namespace.context.detail` 风格:`menu.main.start_button`、`combat.hit.critical`。
3. **保留 context**。同一英文 "Fire" 在不同场景翻译不同(武器"火"vs 动作"开火")。Fluent 用 attribute 解决:`weapon-fire = Fire .tooltip = ...`。
4. **给译员留注释**。gettext 用 `/// TRANSLATORS: This is the fire attack button tooltip`。

**ICU**(International Components for Unicode)是 i18n 的基础库,IBM 起源。提供:

- 数字格式:`1234567.89` → `1,234,567.89`(美国)/ `1.234.567,89`(德国)/ `123,4567.89`(中国)
- 日期格式:不同国家顺序(M/D/Y vs D/M/Y vs Y/M/D)
- 货币:`$10.00` vs `10,00 €` vs `¥10`
- 复数形式:每种语言的复数规则
- 性别 / 大小写

Rust 的 ICU 库是 `icu`(Unicode 维护,rust_icu 项目)。rust-i18n / fluent 都基于它。

**复数形式**特别难。不同语言复数规则天差地别:

- 英语:1 = singular,其他 = plural(2 类)
- 中文:没有复数概念(1 类)
- 法语:0 / 1 = singular,其他 = plural(2 类)
- 阿拉伯语:0、1、2、少量、多数、其他(6 类!)
- 俄语:结尾 1 / 结尾 2-4 / 其他(3 类)
- 波兰语:复杂,4 类

简单 `if (count == 1) { ... } else { ... }` 在阿拉伯文 / 俄文 / 波兰文根本不对。必须用 ICU 复数规则。fluent 原生支持。

## 4 · 中文 / 阿拉伯文 RTL / 日文混合

**字符集**。游戏支持多语言意味着 Unicode 渲染。Latin、CJK、阿拉伯、希伯来、天城文、泰文...rusttype / ab_glyph / swash 等 Rust 字体库都支持 Unicode。

**RTL(Right-to-Left)**。阿拉伯文 / 希伯来文从右往左写。UI 布局也要镜像——按钮在右、菜单从右展开。CSS 有 `direction: rtl`,Rust UI 库(egui / iced)需要手动处理。

```rust
fn is_rtl(locale: &str) -> bool {
    matches!(locale, "ar" | "he" | "fa" | "ur")
}

fn render_button(text: &str, locale: &str) {
    let x = if is_rtl(locale) { screen_right - button_width } else { screen_left };
    draw_text(text, x, ...);
}
```

**Bidirectional text(混合)**。一段话里同时有 RTL 和 LTR 文字(阿拉伯文里出现英文数字),需要 Unicode Bidirectional Algorithm(UBA)处理。复杂算法,Rust 用 `unicode-bidi` crate。

**CJK(中日韩)**。字符多(70000+ 汉字),字体文件大(20 MB+)。**字体子集化**很关键——只打包游戏实际用到的字符,字体从 20MB 缩到 2MB。`fontdue` / `ab_glyph` 配合 `subset` 工具。

**日文混合**。一段文字里同时有汉字 / 平假名 / 片假名 / 英文 / 数字,字体回退复杂(单一字体可能没有所有字形)。

## 5 · 字体回退(font stack)

CSS 的 `font-family: "Helvetica, Arial, sans-serif"` 是 font stack——找不到第一个用第二个。游戏 UI 同样需要。

```rust
struct FontStack {
    fonts: Vec<Font>,  // 按优先级排序
}

impl FontStack {
    fn glyph(&self, c: char) -> Option<&Glyph> {
        // 第一个有这个字符的字体
        for font in &self.fonts {
            if let Some(g) = font.glyph(c) {
                return Some(g);
            }
        }
        None  // 最后回退到 .notdef(豆腐块 □)
    }
}
```

游戏 UI 的 font stack 典型配置:

```
[游戏专用字体, 系统字体, Noto Sans CJK, Noto Sans Arabic, Emoji 字体]
```

Noto 是 Google 的开源字体,支持全球所有语言("No Tofu" = 没有豆腐块)。

## 6 · 文化适配:数字 / 日期 / 货币 / 颜色 / 图标

**数字**。`1234.56` 在不同地区写法不同。Rust 用 `icu::decimal::DecimalFormatter`:

```rust
use icu::decimal::DecimalFormatter;
let fmt = DecimalFormatter::try_new_unstable(&lang!("de").into(), Default::default()).unwrap();
let s = fmt.format(&1234.56.into());
// 德国: "1.234,56"(点分隔千,逗号小数)
```

**日期**。`2026/06/26` vs `26.06.2026` vs `Jun 26, 2026`。Rust 用 `icu::datetime`。

**货币**。`$10.00` vs `10,00 €` vs `¥10`(注意符号位置)。

**颜色**。文化差异大:

- 中国:红色 = 喜庆(红包)
- 西方:红色 = 警告 / 危险
- 中东:绿色 = 宗教(伊斯兰)
- 印度:白色 = 哀悼

游戏里"危险"用红色,在中国玩家可能感觉"喜庆"——这是文化误读。多语言游戏需要按区域调色板。

**图标**。OK 手势(👌)在美国 = OK,在巴西 = 中指。游戏图标要检查目标市场文化敏感度。

**排版习惯**。日本文章横排 / 竖排都用。日本 RPG 游戏经常竖排对话。

## 7 · 实战:HH 加多语言

给 Handmade Hero 加 i18n:

```toml
[dependencies]
rust-i18n = "3"
```

```yaml
# locales/en.yml
en:
  menu:
    start: "Start Game"
    settings: "Settings"
    quit: "Quit"
  combat:
    damage: "{count} damage"
    critical: "Critical! {count} damage"

# locales/zh-CN.yml
zh-CN:
  menu:
    start: "开始游戏"
    settings: "设置"
    quit: "退出"
  combat:
    damage: "{count} 点伤害"
    critical: "暴击!{count} 点伤害"
```

```rust
// i18n.rs
use rust_i18n::t;

rust_i18n::i18n!("locales");

pub fn set_locale(locale: &str) {
    rust_i18n::set_locale(locale);
}

pub fn current() -> String {
    rust_i18n::locale().to_string()
}

// 在 UI 代码里
fn render_main_menu() {
    let start_text = t!("menu.start");
    if ui.button(&start_text) {
        start_game();
    }
}

// 带参数的翻译
fn show_damage(amount: i32) {
    let msg = t!("combat.damage", count = amount);
    ui.show_message(&msg);
}
```

启动时根据系统语言:

```rust
fn detect_locale() -> &'static str {
    // Linux: 看 LANG 环境变量
    // Windows: GetUserDefaultLocaleName
    // macOS: NSLocale
    let sys = std::env::var("LANG").unwrap_or_default();
    if sys.starts_with("zh") { "zh-CN" }
    else if sys.starts_with("ja") { "ja" }
    else { "en" }
}
```

设置菜单允许切换:

```rust
fn settings_ui() {
    ui.label("Language");
    if ui.button("English") { set_locale("en"); }
    if ui.button("中文") { set_locale("zh-CN"); }
    if ui.button("日本語") { set_locale("ja"); }
}
```

热切换(rust-i18n 不支持,需要重启;fluent-rs 支持)。游戏内"切语言立刻生效"是 UX 加分项,需要 fluent-rs + UI 重渲染机制。

## 8 · 反模式

**反模式 1:字符串拼接**。`format!("Game Over - Score: {}", score)`。译员看到 "Game Over - Score: {}" 完整字符串才能翻译,但代码里是拼接的。**应该**:整个模板字符串都外化,`t!("game_over_with_score", score = score)`。

**反模式 2:翻译测试只在英文 build**。你不翻译就发现不了"被截断的字符串"(德语比英语长 30%)。**应该**:开发期间切换到"长字符串测试 locale"(de_DE 是经典选择),看 UI 是否撑得开。

**反模式 3:机器翻译直接用**。Google Translate 翻译游戏文本,语气生硬。**应该**:专业译员 + 上下文文档。预算 $0.05-$0.15 / 字。

**反模式 4:忽略非语言元素**。英文 "Press X to jump" 的 X 是按键提示。德语应该是 "Drücke X zum Springen"——但 X 在德语区键盘是同一位置,没问题。日文应该用〇(PS 手柄)还是 X(Xbox)?**文化适配不只是文字**。

## 9 · 延伸

- gettext 文档:https://www.gnu.org/software/gettext/
- Fluent 项目:https://projectfluent.org/
- rust-i18n:https://github.com/longbridge/rust-i18n
- fluent-rs:https://github.com/projectfluent/fluent-rs
- ICU for Rust:https://github.com/unicode-org/icu4x
- "Game Localization Handbook"(Catherine Ullrich 书,业界圣经)
- IGF(IGDA Localization SIG):https://igda.org/sigs/game-localization-sig/
- Crowdin / Lokalise / Phrase(翻译管理 SaaS,管理多译员协作)

L10n 不是"发布前一天找翻译",是从 day 1 就要设计的工程。**游戏卖到 10 个语言市场通常收入翻 3-5 倍**(参考:Stardew Valley 翻译到 12 种语言,80% 销量在非英语市场)。提前 1 个月做 i18n 架构,后期 L10n 成本降 10 倍。
