
# 深入:UI 布局引擎(flexbox / anchor / constraint / responsive / HIDPI)

> 你把"开始游戏"按钮写在 `x=200, y=300`,把血条写在 `(10, 10)`,把设置面板居中在 `(960, 540)`。在你自己那台 1080p 显示器上一切完美——你录了 demo 视频,发到 itch.io,然后第一天就收到三条反馈:一个 4K 玩家说"按钮挤在左下角一个拳头大",一个 ultrawide 玩家说"主菜单歪在屏幕左半边",一个德国玩家说"Einstellungen 这个词太长,设置按钮的文字溢出了"。
>
> 这不是三个 bug,是同一个原罪——**硬编码像素坐标(hardcoded pixel coordinates)**。你假设了一个分辨率、一个宽高比、一个文本长度。任何一个假设破了,UI 就散架。修复方法不是"再多写几个 if 分辨率",而是把"这个按钮在 x=200"替换成"这个按钮居中、左右各留 20 点边距、宽度按文字内容自适应"——**用规则(rules)取代数字(numbers)**,再让一个**布局引擎(layout engine)**把规则算成具体的像素矩形,任何分辨率、任何文本长度都自动算对。
>
> 这一篇就是讲那个引擎:它接受什么规则,如何把它们解成每个控件的最终矩形,以及为什么 flexbox / anchor / constraint 三大流派各自擅长什么场景。读完你会在 HH 项目里把硬编码坐标换成可适配的布局,在 720p、1080p、4K、ultrawide、德语、日语下都不崩。

## 0 · 一个会让你失眠的下午

把镜头拉近。假设你的 HH 项目已经能渲染,你照着 `immediate-mode-editor.md` 里那套骨架做了一个主菜单,代码长这样:

```rust
fn draw_main_menu(ui: &mut Ui) {
    ui.button_at([200.0, 300.0], "Start Game");
    ui.button_at([200.0, 340.0], "Settings");
    ui.button_at([200.0, 380.0], "Quit");
}
```

`button_at` 是你前两天图省事加的辅助函数——直接把矩形坐标塞进去,跳过了任何布局计算。本机跑 1080p,一切正常,你截图发推说"主菜单做完了"。

第二天你打开笔记本调试,屏幕是 1366×768。菜单按钮还在 (200, 300)——但 768 高的屏幕上,(200, 300) 已经是屏幕中下方,三个按钮挤成一坨,和下面的版本号文字重叠。你心想"那加个缩放",于是写了 `button_at([200.0 * scale, 300.0 * scale], ...)`,1080p 和 768p 都过了。

第三天你的合作者用 4K 显示器跑——按钮在屏幕左上角一个手掌大的区域里,小到他要点准得用放大镜。`scale` 是 4 倍了,但 200×4=800 在 3840 宽的屏幕上仍然只是 1/5 的位置。问题不是"缩放",是"位置应该相对于屏幕中心而不是左上角"。

第四天你把游戏发到一个德国独立游戏 Discord,有人截图给你看:"Einstellungen" 比 "Settings" 长将近三倍,你那个固定 120 像素宽的按钮装不下,文字溢出到按钮外面。

四个分辨率、两个语种,六次返工。你意识到:**只要坐标是写死的数字,你就永远在补窟窿**。

布局引擎存在的意义就是让你不再写数字。你改写代码:

```rust
fn draw_main_menu(ui: &mut Ui) {
    ui.column(Align::Center, || {
        ui.button("Start Game");   // 宽度按文字自适应
        ui.button("Settings");
        ui.button("Quit");
    });
}
```

没有 `200`、没有 `300`、没有 `120`。你只说了三件事:这些按钮排成一列(column),整列水平居中(center),每个按钮的宽度由它自己的文字内容决定。**剩下的一切——具体矩形、缩放、DPI、文本宽度——都由布局引擎在每一帧算出来**。同一个调用,1080p 居中,4K 居中且按 DPI 放大,德语下 "Einstellungen" 那个按钮自动变宽,周围按钮跟着重新排版。这就是布局引擎的承诺,也是这一篇要讲清楚的东西。

## 1 · 为什么硬编码坐标是原罪

要把这个问题讲透,得说清楚硬编码坐标到底假设了什么。

第一,它假设了一个**固定分辨率**。坐标 (200, 300) 在 1920×1080 里是屏幕左 1/10、上 1/4 处;在 3840×2160 里是左 1/20、上 1/7 处——视觉位置完全变了。同一个数字,在不同分辨率下指向屏幕的不同区域。

第二,它假设了一个**固定宽高比**。横屏 16:9 下 (200, 300) 的按钮在屏幕左侧;竖屏 9:16( Switch 掌机模式、手机)下同一坐标的按钮几乎贴着中线。Ultrawide 21:9 下又偏左得更厉害。

第三,它假设了一个**固定文本尺寸**。"Settings" 在 14pt 字号下宽 60 像素,"Einstellungen" 在同字号下宽 130 像素,你写死的 120 像素按钮宽度只对其中一种成立。

第四,它假设了一个**固定 DPI**。一个 12 像素的字在 1080p 显示器(典型 96 DPI)和 4K 显示器设为 200% 缩放(逻辑 192 DPI)下,物理大小差一倍。如果你按物理像素硬编码,4K 上字小得看不清;如果你按物理像素 ×2,1080p 上字又太大。

这四个假设——分辨率、宽高比、文本尺寸、DPI——**任何一个不成立,UI 就错位**。而现实是玩家的硬件和语言几乎不可能全部匹配你的开发机。Steam 硬件调查里光是主显示器分辨率就有十几种,从 1366×768 到 3840×2160 都有人;Steam Deck 是 1280×800 16:10;Switch 掌机和底座分别是 720p 和 1080p;手机端横竖屏切换是运行时事件。

布局引擎的解法是**把数字推迟到运行时计算**。你在代码里只声明规则——"这个按钮在水平方向上居中,垂直方向上距底部 20 点,宽度等于它的文字宽度加左右各 12 点 padding"——具体坐标在你声明时不出现,在玩家运行游戏、引擎知道屏幕尺寸和 DPI 和字体度量之后,才被算出来。规则是常量,数字是函数的输出。这是布局引擎最核心的思维转换,接下来三节讲三种主流的规则系统。

## 2 · Anchor 布局:钉在边角

最古老也最简单的布局模型是**锚布局(anchor-based layout)**。它的核心动作就一个:**把控件钉在父容器的某个边、角或中心,再加一个偏移量**。

想象你在装修一面墙挂画。你不会说"这幅画挂在 x=340, y=210"——你会说"这幅画挂在我这面墙的正中,稍微偏右一点点",或者"挂在左上角,离左边 20 公分,离顶 15 公分"。锚布局就是这种表达方式。

每个控件声明两个锚点:**水平锚**(left / center / right / stretch)和**垂直锚**(top / middle / bottom / stretch)。组合起来就是经典的九宫格——左上、上中、右上、左中、正中、右中、左下、下中、右下,加上 stretch 模式表示"水平/垂直方向占满"。

```rust
// 一个简化的锚布局:每个控件指定两个锚点和一个像素偏移
#[derive(Clone, Copy)]
enum HAnchor { Left, Center, Right, Stretch }
#[derive(Clone, Copy)]
enum VAnchor { Top, Middle, Bottom, Stretch }

struct Anchored {
    h: HAnchor,
    v: VAnchor,
    offset: Vec2,     // 相对锚点的逻辑偏移(不是绝对坐标)
    size: Vec2,       // 控件本身大小(stretch 时忽略其中对应维度)
}

fn resolve(anchor: &Anchored, parent: Rect) -> Rect {
    use HAnchor::*; use VAnchor::*;
    let x = match anchor.h {
        Left    => parent.left() + anchor.offset.x,
        Center  => parent.center_x() - anchor.size.x * 0.5 + anchor.offset.x,
        Right   => parent.right() - anchor.size.x - anchor.offset.x,
        Stretch => parent.left() + anchor.offset.x,
    };
    let w = match anchor.h {
        Stretch => parent.width() - anchor.offset.x * 2.0,
        _       => anchor.size.x,
    };
    // 垂直方向同理
    // ...
    Rect::new(x, /* y */, w, /* h */)
}
```

注意这里的 `offset` 是**相对锚点的逻辑偏移**,不是屏幕绝对坐标。"右上角的血条,离右边 16 点,离顶 16 点"在 1080p 解出来是 (1920-16-w, 16);在 4K 解出来是 (3840-16-w, 16)——位置自动跟着分辨率走。这就是 anchor 解决"分辨率适配"的方式:它把"距离屏幕右边的像素数"作为不变量,而不是"距离屏幕左边的像素数"。任何分辨率下,血条永远贴着右上角。

锚布局最适合的场景是 **HUD 元素**——血条、小地图、弹药计数、技能冷却图标——这些东西天生就该贴着屏幕的某个角或边,玩家移动视角时它们不动。Unreal UMG(Unreal Motion Graphics)的 anchors 面板就是这套模型,Unity 老的 uGUI Canvas 也用 anchors。一个 AAA 游戏的 HUD 90% 用 anchor,只有需要排成一行(比如技能栏的六个格子)时才额外加一个水平排列的容器。

锚布局的局限是它**不擅长表达控件之间的相对关系**。"按钮 A 在按钮 B 右边 8 个像素"这种话 anchor 说不出,你只能各自钉住位置,中间的 8 像素间距是靠人脑算出来的。一旦你想要"A 和 B 在一个水平居中的组里,等间距排列",anchor 就开始力不从心——这就是下一节约束布局要解决的问题。

## 3 · Constraint 布局:Cassowary 与线性规划

如果 anchor 是"各自钉死",那**约束布局(constraint-based layout)**就是"声明关系,让求解器解出来"。

约束布局的代名词是 **Cassowary** 算法——1996 年 Badros、Borning、Stasko 等人在论文《The Cassowary Linear Arithmetic Constraint Solving Algorithm》里提出的,用**线性规划(linear programming)**的单纯形法变体来解 UI 约束。Apple 的 Auto Layout 是 Cassowary 最广为人知的工业实现,Java 的 Swing GroupLayout、Python 的 Kiwi、Rust 的 `cassowary` crate 都是同一族算法。

约束是什么样子?就是一行形如"线性表达式 = / ≥ / ≤ 线性表达式"的不等式:

```
button_a.right + 8 == button_b.left      // A 在 B 左边,间距 8
button_b.right + 8 == button_c.left
container.center_x == row.center_x       // 整行水平居中
button_a.width >= 80                      // 最小宽度
button_a.width + button_b.width + button_c.width + 16 == container.width
                                          // 三个按钮加间距正好填满容器
```

Cassowary 把所有约束收集起来,加上一组"软"偏好(soft constraints,违反了不是错误但会被惩罚,比如"我倾向于所有按钮等宽"),然后丢给一个增量单纯形求解器去算每个变量的最优值——`button_a.left`、`button_b.width` 等等。结果是每个控件的具体矩形。这个过程对游戏 UI 来说是逐帧重解的,但现代实现(增量求解)通常在微秒级,几百个控件完全不是负担。

约束布局的力量在于**它能表达任意线性关系**。"这两个按钮等高"、"这列的宽度跟它的标签等宽"、"如果窗口宽于 1000,侧边栏固定 300;否则侧边栏隐藏"——这些在 anchor 里要么做不到要么要靠手写 if/else,在约束布局里都是一行约束。Apple 的 Auto Layout 之所以能驱动 iOS 上千种设备尺寸的复杂界面,就是因为约束布局在数学上保证了一致性。

代价是**调试困难**和**约束冲突**。当两个约束互相矛盾(比如"A 宽 100"和"A 宽 200"同时存在,且都是硬约束),求解器要么报错要么打破其中一个,日志里是一串抽象的变量名,新人看了不知道哪个约束是元凶。Apple 给 Auto Layout 加了一堆可视化调试工具(NSLayoutConstraint 的 identifier、视图调试器)就是因为这个问题。另一个代价是**性能不稳定**——单纯形法的最坏情况是指数级,虽然实际 UI 上几乎不会触发,但极端的约束图可能让一帧的布局耗时暴增。Cassowary 论文里的"增量"改进主要是为了让逐帧的小改动(比如动画一个约束的常数项)能复用上一次的解,而不是从头解。

游戏行业里约束布局用得不多,因为大多数游戏 UI 不需要那么多关系——HUD 用 anchor 就够了,菜单用下一节的 flexbox 就够了。但如果你做的是一个**复杂表单**或者**编辑器面板**(比如一个关卡编辑器的属性检查器,要列几十个字段,字段之间还有"如果勾了 A,B 才显示"这种依赖),约束布局是最干净的模型。Rust 生态的 `cassowary` crate([https://docs.rs/cassowary](https://docs.rs/cassowary))是一个简洁的参考实现,读它的源码(~1000 行)是理解这个算法的最佳途径。

## 4 · Flexbox:Web 的答案,现代 UI 的默认

第三种模型是 **flexbox**,CSS Flexible Box Layout 的简称,W3C 在 2012 年标准化,从那以后席卷了 Web、React Native、Flutter 的 Row/Column、Bevy UI、Slint 等几乎所有现代 UI 框架。**它是 2026 年做响应式 UI 的默认选择**。

flexbox 的核心心智模型是:**子元素在一根主轴(main axis)上排列,沿交叉轴(cross axis)对齐,容器里多余的空间按比例分配给能伸缩的子元素**。

主轴是 row(水平)或 column(垂直)。容器有一组子元素,每个子元素声明三个数:**`flex_grow`**(空间富裕时,这个子元素能多吃几份)、**`flex_shrink`**(空间紧张时,这个子元素能被压缩)、**`flex_basis`**(不伸缩时的基础尺寸)。容器还声明主轴上的对齐(`justify_content`:start / center / end / space-between / space-around)和交叉轴上的对齐(`align_items`:start / center / end / stretch)。

举个具体例子。一个底部技能栏:屏幕宽度 1920,要装 6 个等宽技能图标,左右各留 16 边距,图标之间 8 间距。flexbox 描述是:

```rust
// 用 taffy crate(Rust 的 flexbox 实现,Bevy UI 在用)
use taffy::prelude::*;

fn skill_bar() -> TaffyTree<()> {
    let mut tree = TaffyTree::new();
    let mut slots = Vec::new();
    for _ in 0..6 {
        let slot = tree.new_leaf(Style {
            flex_grow: 1.0_f32,    // 6 个 slot 平分剩余空间
            flex_basis: length(0.0),
            aspect_ratio: 1.0,      // 正方形
            ..Default::default()
        }).unwrap();
        slots.push(slot);
    }
    let root = tree.new_with_children(Style {
        display: Display::Flex,
        direction: FlexDirection::Row,
        justify_content: Some(JustifyContent::SpaceBetween),
        align_items: Some(AlignItems::Center),
        padding: rect(0.0, 16.0, 0.0, 16.0),  // 左右各 16
        size: Size { width: length(1920.0), height: length(64.0) },
        ..Default::default()
    }, &slots).unwrap();
    tree.set_root(root).unwrap();
    tree
}
```

1920 宽下,6 个 slot 各分到 (1920 - 32 - 5×8) / 6 ≈ 308 像素。如果玩家切到 1280 宽,引擎重算:每个 slot 变成 (1280 - 32 - 40) / 6 ≈ 201 像素。如果再切到 ultrawide 3440,每个 slot 变成 558 像素。**代码没动一个字**,布局自动跟着屏幕走。这就是 flexbox 的威力——你声明"等分、居中、留边",其余的全是引擎的事。

flexbox 比 anchor 强的地方在于它**自然地表达了"一群控件之间的关系"**:技能栏的 6 个格子等分、表单的标签和输入框成对排列、设置面板的若干行垂直堆叠。anchor 表达不出"等分";constraint 能表达但啰嗦。flexbox 恰好卡在中间——足够强,又足够简洁,这正是它成为现代 UI 默认布局的原因。

flexbox 的代价是**它的语义有边界**。它处理一维(一行或一列)很好,二维网格(grid)就力不从心(CSS 后来加的 Grid Layout 才是二维的)。它也不擅长表达"A 在 B 左边且 B 在 C 上方"这种跨容器的关系——那些是约束布局的领地。所以现代 UI 框架的策略通常是**flexbox 做默认,constraint 或 grid 做补充**。Rust 生态里,`taffy`([https://docs.rs/taffy](https://docs.rs/taffy))是 Bevy UI、iced 的底层布局引擎,实现了完整的 CSS Block Layout + Flexbox + CSS Grid,是这一篇推荐的实战选择。

## 5 · 响应式布局:同一个 UI,不同形态

到此为止我们假设"UI 的结构不变,只是尺寸变"。但真实情况更激烈——窗口缩到一定宽度后,横排的菜单项就该改成竖排;窄屏时侧边栏该折叠成汉堡按钮;横屏时技能栏在底部,竖屏时该挪到右侧。这种**结构随空间改变**的布局叫**响应式布局(responsive layout)**。

响应式有两个主要技术:**flex wrap** 和**断点(breakpoints)**。

flex wrap 是 flexbox 自带的能力——一行装不下就自动换行。想象一个成就列表:宽屏下每行 4 个成就卡片,1280 宽下每行 3 个,720 宽下每行 2 个。代码只是 `flex_direction: Row, flex_wrap: Wrap`,引擎自己决定换几行。每个卡片声明固定基础宽度(比如 280 点)+ 不伸缩,引擎在容器宽度里能塞几个塞几个,塞不下的自动到下一行。**这是最简单的响应式**——零分支代码,纯数学。

断点是更显式的响应式——你在代码里说"当容器宽度 < 600 时,主轴从 Row 改成 Column"。这适合那种不只是换行、而是整个布局结构都要重组的场景。比如主菜单:宽屏下左侧是 logo + 一列按钮,右侧是预览图;窄屏下变成上下结构,logo 在顶部,按钮居中,预览图隐藏。

```rust
fn main_menu_style(container_width: f32) -> Style {
    if container_width >= 800.0 {
        // 横屏:左右两栏
        Style {
            display: Display::Flex,
            direction: FlexDirection::Row,
            ..Default::default()
        }
    } else {
        // 窄屏:上下堆叠
        Style {
            display: Display::Flex,
            direction: FlexDirection::Column,
            ..Default::default()
        }
    }
}
```

断点的阈值(800、600)是**逻辑点(logical points)**不是物理像素——这带我们到下一节的关键概念。

为什么游戏 UI 需要响应式?因为 PC 玩家的硬件差异远大于移动端。Steam 上同一个游戏可能跑在 1366×768 笔记本、1920×1080 桌面、2560×1080 ultrawide、3840×2160 4K、Steam Deck 1280×800,以及各种窗口化模式下的任意中间尺寸。**一个不响应式的 UI,在某一群玩家的屏幕上必然是错的**。响应式不是"加分项",是 PC 平台的基本要求。这也是为什么 Web 的 CSS 经验——媒体查询、flexbox、grid——对 PC 游戏开发者直接有用,你们解决的是同一个问题。

## 6 · 分辨率无关与 HIDPI:逻辑点、物理像素、DPI 缩放

到现在我们说的"宽度 1920"是哪种像素?是显卡 swapchain 的物理像素,还是某种逻辑单位?这一节把这件事讲透——它是 4K 显示器出现后所有游戏 UI 都必须面对的概念。

核心区分是**逻辑点(logical point)**和**物理像素(physical pixel)**,两者之间靠 **DPI 缩放因子(scale factor)**换算:`物理像素 = 逻辑点 × scale_factor`。

为什么需要这个区分?因为同样一块物理屏幕,显卡可以输出不同数量的像素。一台 27 寸 4K 显示器在 Windows 默认设置下,scale_factor 是 1.5(150%)——显卡输出 3840×2160 物理像素,但应用看到的逻辑尺寸是 2560×1440。这台显示器上,一个"12pt 字"应该有多高?答案是**12 个逻辑点对应的物理像素**——也就是 12 × 1.5 = 18 个物理像素。这样字的视觉大小(在屏幕上的物理毫米数)和一台 scale=1 的 1080p 显示器上的 12pt 字一致。

游戏 UI 该怎么用这套机制?答案是**所有 UI 坐标和尺寸都用逻辑点声明,渲染时乘以 scale_factor 转成物理像素**。你的代码里出现 `font_size: 14`、`padding: 12`、`button_height: 36`——这些都是逻辑点。引擎在最后一步把它们乘以 scale_factor,得到 framebuffer 里的真实像素坐标。

```rust
struct UiSurface {
    scale_factor: f32,   // 由窗口系统给出(winit::window::scale_factor)
    // ...
}

impl UiSurface {
    /// 接受逻辑坐标,渲染物理像素
    fn logical_to_physical(&self, p: Vec2) -> Vec2 {
        p * self.scale_factor
    }
}

// 主菜单里你写的是逻辑点
const FONT_SIZE: f32 = 14.0;       // pt
const BUTTON_H: f32 = 36.0;        // pt
const PADDING: f32 = 12.0;         // pt

// 在 1080p scale=1 下,14pt 字渲染成 14 物理像素
// 在 4K scale=2 下,14pt 字渲染成 28 物理像素——视觉大小相同
```

注意 scale_factor 是**运行时从窗口系统拿的**,不是你能假设的常量。`winit` crate 提供 `window.scale_factor()`,macOS 上 retina 屏返回 2.0,Windows 上由用户在"显示设置"里调,4K 显示器通常 1.5 或 2.0,Linux Wayland 上是混合的。**玩家拖动游戏窗口到另一台显示器,scale_factor 可能就变了**——你的 UI 代码必须能在每一帧响应这个变化。这个话题在 `days/phase-9/09F-3-cross-platform-and-portability.md` 里有更详细的跨平台讨论,这里只点出 UI 这一侧的责任。

逻辑点/物理像素这套机制要真正"看起来对",还有一个**资产缩放(asset scaling)**的问题。你的图标是位图,设计稿在 1080p scale=1 下是 36×36 物理像素。在 4K scale=2 下,引擎把它放大到 72×72——但位图放大是模糊的(双线性插值)。两个解法:

第一,**矢量资产(vector assets)**。SVG、TTF 图标字体、引擎自己的矢量格式(Bevy 的 `bevy_svg`、Unreal 的 Slate vector)。矢量图可以任意缩放不失真,是 UI 图标的首选,代价是 GPU 上 tessellation 略重。

第二,**多倍率位图(@2x / @3x)**。准备同一张图的 1x、2x、3x 三个版本,引擎按当前 scale_factor 选最近的版本。这是 iOS / macOS / Android 的传统做法,Web 的 `image-set()` 也是这个思路。代价是资产体积 3 倍,但渲染清晰。游戏行业通常 1x 设计在 1080p,2x 用于 4K,3x 几乎不用(8K 还没普及)。

字体是个特例——TrueType / OpenType 是矢量的,**字号天然支持任意 DPI**,所以你不需要为不同 DPI 准备不同字体,只需要按 scale_factor 调整 glyph 渲染时的网格度量(glyph atlas 的尺寸)。但要小心**字体光栅化的 hinting**——12pt 字在 96 DPI 下光栅化成 12 像素,hinting 会把笔画对齐到像素网格让字看起来锐利;同一字号在 192 DPI 下光栅化成 24 像素,hinting 的策略不同。优秀的 UI 字体(Inter、Roboto)和光栅化器(freeype + harfbuzz)会处理好这些,你只需要保证字体在逻辑 12pt 下渲染,scale_factor 由引擎管。

把这一节总结成一句话:**UI 用逻辑点思考,DPI 缩放是引擎和窗口系统的事**。这个思维一旦建立,你的 UI 就自然适配任何显示器。

## 7 · 文本驱动尺寸:让本地化"just work"

回到开头那个 "Einstellungen" 溢出的 bug。它的根因是按钮宽度写死了,而文字宽度是变的。修复方法是**让控件尺寸跟着内容走**——按钮的宽度等于"文字宽度 + 左右 padding"。这一节讲清楚怎么实现。

基础是**字体度量(font measurement)**。给定一个字符串、一种字体、一个字号,你需要算出这个字符串渲染出来的精确宽度(以及高度,虽然高度通常由 line height 决定)。这件事比看起来复杂:

字符串不是按字符数 × 单字符宽度算宽度的——**字距调整(kerning)**让相邻字符的间距随组合变化(fi、AV、To 这种组合的间距和单独字符不同),**连字(ligature)**让多个字符合并成一个字形(fi → ﬁ),**复杂文字 shaping**(阿拉伯文、天城文)会让一串字符变形重排。所以宽度计算必须经过完整的 **shaping 管线**(HarfBuzz / Rust 的 `rustybuzz` / `swash`),拿到一串 positioned glyph,每个 glyph 有自己的 advance(前进量),advance 之和才是字符串的真实宽度。

```rust
use swash::text::cluster::CharCluster;
use swash::shape::ShapeContext;

struct FontMeasure {
    context: ShapeContext,
    // 字体句柄、size 等
}

impl FontMeasure {
    /// 返回字符串在指定字号下的逻辑宽高(单位:pt)
    fn measure(&self, text: &str, font_size: f32) -> Vec2 {
        let mut shaper = self.context.builder(font).size(font_size).build();
        let mut width = 0.0;
        let mut ascent = 0.0_f32;
        let mut descent = 0.0_f32;
        shaper.add_str(text);
        shaper.shape(|cluster| {
            width += cluster.advance();
            // 记录每个 glyph 的 y_offset 来推 ascent/descent
        });
        let line_height = font_size * 1.2;  // 简化,实际读 OS/2 表的 hhea
        Vec2::new(width, line_height)
    }
}
```

有了字体度量,接下来是**布局如何利用它**。flexbox 的核心机制——`measure` 阶段——就是干这个的:引擎自底向上调用每个叶子控件的 `measure(text)`,叶子返回它"想要"的尺寸,父容器收集这些想要的尺寸,加上自己的对齐和伸缩规则,自顶向下分配最终矩形。下一节展开。

让控件尺寸跟随内容有两个 flexbox 习惯用法。第一,**flex_basis 设为 auto**(CSS 默认),意思是"基础尺寸 = 内容尺寸";同时 `flex_grow: 0, flex_shrink: 0`,意思是"不伸不缩,就用我的内容尺寸"。这样按钮就严格等于它的文字加 padding。第二,**flex_grow: 1, flex_shrink: 1, flex_basis: 0**,意思是"我不在乎自己的内容尺寸,把我等分到所有兄弟里"——这适合技能栏那种格子,格子的大小不该由图标尺寸决定。

把这两套混着用就解决本地化问题:菜单里每个按钮 `basis: auto, grow: 0`,所以德语下那个按钮变宽,英语下那个按钮变窄,**整列居中对齐时,无论谁变宽,布局都自动重排**。这就是为什么 modern UI 框架(iced、Bevy UI、Flutter)都默认控件尺寸跟内容——它让 i18n 几乎免费。`localization-short.md` 里详细讲了 i18n 工程化,这里强调的是布局这一侧:你的 UI 必须是 content-aware 的,本地化才能不返工。

## 8 · 两遍布局:measure 与 arrange

所有现代 UI 框架(Bevy UI、WPF、Flutter、Unity UI Toolkit)都使用同一个布局算法骨架,叫**两遍布局(two-pass layout)**:**measure pass 自底向上,arrange pass 自顶向下**。理解这两遍是理解布局引擎的关键——本节把它讲清楚。

考虑一棵 UI 树:根容器 `Root`,里面一个 `Column`,Column 里三个 `Button`,每个 Button 里一个 `Text`。这一帧要算每个节点的最终矩形。怎么做?

**Measure pass(自底向上)**。先从最深的叶子开始,问每个叶子:"在父容器给你的约束(比如'宽度 ≤ 300')下,你**想要**多大?"叶子根据内容回答——Text 报告它的字符串度量尺寸,Image 报告它的源图尺寸,Button 把里面 Text 的想要尺寸加上 padding。然后父节点收集所有子节点的"想要尺寸",根据布局规则决定自己的想要尺寸——Column 想要的高度是三个子节点想要高度之和加间距,想要的宽度是三个子节点想要宽度的最大值。一路向上,根节点最后报告它想要的尺寸(通常根节点的"想要尺寸"会直接被窗口大小覆盖,因为根必须填满窗口)。

```rust
// 简化的 measure 递归
fn measure(node: &Node, ctx: &mut Ctx, constraints: Size<Option<f32>>) -> Vec2 {
    match node {
        Node::Text(t) => ctx.font.measure(&t.string, t.size),
        Node::Button(b) => {
            let inner = measure(&b.child, ctx, constraints.shrink(b.padding));
            inner + b.padding * 2.0  // 加上 padding
        }
        Node::Column(c) => {
            let mut total_h = 0.0;
            let mut max_w = 0.0_f32;
            for child in &c.children {
                let want = measure(child, ctx, constraints);
                total_h += want.y + c.gap;
                max_w = max_w.max(want.x);
            }
            Vec2::new(max_w, total_h - c.gap)  // 最后一个 gap 不算
        }
        // ... 其他节点类型
    }
}
```

**Arrange pass(自顶向下)**。根节点知道自己的最终矩形(= 窗口矩形),它把这个矩形按规则分配给子节点。"Column 在 1080×1920 的窗口里水平居中,垂直从顶部 100 开始"——那么 Column 的最终矩形是 `(center_x - col_w/2, 100, col_w, col_h)`。Column 再把这个矩形按"竖向堆叠 + 居中对齐"分给三个 Button——每个 Button 拿到一个具体的 `(x, y, w, h)`。Button 再把自己的矩形分给里面的 Text(扣掉 padding)。Text 拿到最终位置,准备渲染。

```rust
// 简化的 arrange 递归
fn arrange(node: &mut Node, ctx: &mut Ctx, final_rect: Rect) {
    node.set_rect(final_rect);   // 写回每个节点的最终矩形
    match node {
        Node::Text(_) => { /* 叶子,结束 */ }
        Node::Button(b) => {
            let inner = final_rect.shrink(b.padding);
            arrange(&mut b.child, ctx, inner);
        }
        Node::Column(c) => {
            let mut y = final_rect.top();
            for child in &mut c.children {
                let want = child.desired_size;   // measure 阶段记下的
                let h = want.y;
                let x = match c.align_h {
                    AlignH::Center => final_rect.center_x() - want.x * 0.5,
                    AlignH::Left   => final_rect.left(),
                    AlignH::Right  => final_rect.right() - want.x,
                };
                arrange(child, ctx, Rect::new(x, y, want.x, h));
                y += h + c.gap;
            }
        }
        // ...
    }
}
```

为什么非要两遍?**因为子节点想要的尺寸依赖父节点给的约束,而父节点想要的尺寸又依赖子节点想要什么**——这是个鸡生蛋的问题。两遍布局的解法是:第一遍假设父节点给的约束宽松(`Size::NONE` 表示"任意"),让子节点把"想要"报上来;第二遍父节点有了完整信息后,把"想要"和"实际能给"取交集(可能要压缩子节点),下达最终决定。

这个谈判过程解释了一个常见困惑:为什么 `flex_grow: 1` 的元素在有富余空间时会变大,而 `flex_basis: auto` 的不会?答案在 measure 和 arrange 的细节里——measure 阶段每个子节点都报自己的 basis(auto 就是内容尺寸);arrange 阶段父节点算出剩余空间(容器尺寸 - 所有 basis 之和),按 `flex_grow` 比例分给那些 grow > 0 的子节点,grow = 0 的子节点尺寸不变。这是 flexbox 的核心机制,也是 taffy 的核心实现。读懂这两遍递归,你就读懂了任何 flexbox 实现的 90%。

性能上要注意:**measure 是 O(节点数),arrange 也是 O(节点数),合起来是 O(N)**。一棵上千节点的复杂 UI,单帧布局成本通常在 100 微秒级——可接受。但要警惕 measure 的重复触发——文字内容不变时,measure 结果可以缓存(`desired_size` cache),只有内容或字体或字号变时才重算。Bevy UI 和 taffy 都做了这种 dirty 标记。你在自己写布局时也要做这个优化,否则每帧重新 shape 整个 UI 树会很贵( shaping 是字体度量里最重的部分)。

## 9 · 在你 HH 项目里动手(做中学红线)

把上面的概念落到 HH 项目里。这一节的产出是:**你的主菜单和 HUD 从硬编码坐标改成布局引擎驱动,在 720p / 1080p / 4K / ultrawide 四种分辨率下都正确**。分三步走,每一步都能独立验证。

**第一步:HUD 改用 anchor**。打开你的 HUD 渲染代码,找到所有写死的 `(x, y)`。血条改成右上锚(`HAnchor::Right, VAnchor::Top, offset: (16, 16)`)、技能栏改成下中锚、小地图改成右下锚。验证方法:把窗口拉到 1280×720、1920×1080、2560×1080 三种尺寸,血条永远贴右上角,距离右边和上边永远 16 逻辑点。这就是 anchor 的胜利——三种分辨率同一个规则。

```rust
// HH: hud.rs
struct HudLayout {
    hp_bar: Anchored,
    skill_bar: Anchored,
    minimap: Anchored,
}

impl HudLayout {
    fn new() -> Self {
        Self {
            hp_bar: Anchored {
                h: HAnchor::Right, v: VAnchor::Top,
                offset: Vec2::new(16.0, 16.0),
                size: Vec2::new(240.0, 24.0),
            },
            skill_bar: Anchored {
                h: HAnchor::Center, v: VAnchor::Bottom,
                offset: Vec2::new(0.0, 24.0),
                size: Vec2::new(480.0, 64.0),
            },
            minimap: Anchored {
                h: HAnchor::Right, v: VAnchor::Bottom,
                offset: Vec2::new(16.0, 16.0),
                size: Vec2::new(180.0, 180.0),
            },
        }
    }

    fn layout(&self, viewport: Rect) -> HudRects {
        HudRects {
            hp_bar: resolve(&self.hp_bar, viewport),
            skill_bar: resolve(&self.skill_bar, viewport),
            minimap: resolve(&self.minimap, viewport),
        }
    }
}
```

**第二步:主菜单按钮做内容尺寸**。把主菜单从 `button_at([200, 300], "Start")` 改成"按文字度量算宽度 + 左右 padding 12 + 垂直堆叠 + 整列居中"。这一步是验证字体度量能不能跑通——按钮宽度严格等于 `measure("Start Game", 14pt).x + 24`。验证方法:把字符串改成 "Einstellungen"(假装德语)或一个长中文,按钮**应该自动变宽**,不溢出。如果你的 `measure` 还没接 shaping,接上 `swash` 或 `cosmic-text` crate。

```rust
// HH: main_menu.rs
use taffy::prelude::*;

struct MainMenu {
    tree: TaffyTree<()>,
    root: NodeId,
    buttons: Vec<NodeId>,
    font_measure: FontMeasure,
}

impl MainMenu {
    fn new(font_measure: FontMeasure) -> Self {
        let mut tree = TaffyTree::new();
        let mut buttons = Vec::new();

        for label in ["Start Game", "Settings", "Quit"] {
            // 测量文字,决定按钮 basis
            let text_size = font_measure.measure(label, 14.0);
            let btn = tree.new_leaf(Style {
                size: Size {
                    width: length(text_size.x + 24.0),  // +padding
                    height: length(text_size.y + 16.0),
                },
                margin: rect(4.0, 0.0, 4.0, 0.0).into(),
                ..Default::default()
            }).unwrap();
            buttons.push(btn);
        }

        let root = tree.new_with_children(Style {
            display: Display::Flex,
            direction: FlexDirection::Column,
            align_items: Some(AlignItems::Center),  // 交叉轴居中
            justify_content: Some(JustifyContent::Center),
            size: Size::AUTO,   // 让 root 撑满父(由调用方塞 viewport)
            ..Default::default()
        }, &buttons).unwrap();

        Self { tree, root, buttons, font_measure }
    }

    fn layout(&mut self, viewport: Rect) {
        // 把 viewport 作为 root 的最终矩形
        self.tree
            .set_style(self.root, Style {
                size: Size {
                    width: length(viewport.width()),
                    height: length(viewport.height()),
                },
                ..Default::default()
            }).ok();
        self.tree.compute_layout(self.root, Size::MAX).unwrap();
    }

    fn button_rect(&self, i: usize) -> Rect {
        let layout = self.tree.layout(self.buttons[i]).unwrap();
        let order = layout.order;
        let loc = layout.location;
        let size = layout.size;
        Rect::new(
            loc.x + viewport.left(),   // 需要把 taffy 的局部坐标转回屏幕坐标
            loc.y + viewport.top(),
            size.width,
            size.height,
        )
    }
}
```

**第三步:接 DPI 缩放**。把你的 `UiSurface` 改成持有 `scale_factor`,所有渲染前把逻辑矩形乘以 `scale_factor`。验证方法:在 Windows 上把 4K 显示器设为 150% 缩放,游戏窗口里 14pt 字应该明显比 scale=1 时大,但布局不崩(按钮跟着放大,但仍然居中、仍然等比例)。

```rust
// HH: ui_surface.rs
struct UiSurface {
    scale_factor: f32,
    viewport_logical: Rect,   // 逻辑点
}

impl UiSurface {
    fn update_from_window(&mut self, window: &winit::window::Window) {
        self.scale_factor = window.scale_factor() as f32;
        let inner = window.inner_size().to_logical::<f32>(self.scale_factor as _);
        self.viewport_logical = Rect::new(
            0.0, 0.0,
            inner.width, inner.height,
        );
    }

    /// 布局在逻辑空间算,渲染到物理空间
    fn physical_rect(&self, logical: Rect) -> Rect {
        Rect::new(
            logical.left() * self.scale_factor,
            logical.top() * self.scale_factor,
            logical.width() * self.scale_factor,
            logical.height() * self.scale_factor,
        )
    }
}
```

走完这三步,你的 UI 应该在 720p / 1080p / 4K / ultrawide 四种窗口下都正确——HUD 贴边、菜单居中、按钮自适应文字。**这一节的"做完了"标准是:打开游戏,把窗口从最小拖到最大,UI 始终不破。**

如果在这一步你卡在"窗口缩放时画面延迟一帧才响应",那是事件处理的同步问题——窗口 resize 事件和 UI 布局不在同一帧处理。把 `update_from_window` 放到主循环开头、`layout` 紧随其后、渲染最后,通常就解决了。

## 10 · 练习

### Lv1 · 概念辨析

**题**:为什么 anchor 布局在"6 个技能栏格子等分屏幕宽度"这个需求下力不从心,而 flexbox 几乎是为此设计的?用 measure/arrange 两遍布局的语言解释。

**参考答案**:anchor 只能表达"这个控件相对于父容器的位置",不能表达"这个控件相对于兄弟控件的位置"。6 个格子等分屏幕宽度时,每个格子的位置依赖另外 5 个格子的尺寸——这是兄弟之间的关系,anchor 抓不到,你只能手算 `slot_w = (screen_w - paddings - gaps) / 6` 然后给每个 slot 一个写死的 anchor offset,这退化回了硬编码。flexbox 通过 `flex_grow: 1` 把这个"等分"语义直接表达成 measure 阶段的一个属性——measure 时每个 slot 报 basis=0、grow=1,arrange 时父容器算出剩余空间按 grow 比例分,6 个 slot 自然等分。**flexbox 把"等分"编码进了布局规则本身,anchor 把它甩给了程序员算术**——这就是表达能力的差异。

### Lv2 · 动手实践

**题**:在你的 HH 项目里把主菜单的硬编码坐标换成 anchor + 内容尺寸(本节"做中学"红线第二步)。验证:换分辨率、把 "Settings" 改成 "Einstellungen",UI 都不破。

**完成标准**:720p / 1080p / 4K 三种窗口下菜单居中且不溢出;改字符串后按钮宽度自动跟着变。

**参考解答**:见本节第 9 节的 `MainMenu::new` 和 `layout`。关键点:(1) 用 `FontMeasure::measure` 算每个按钮的文字宽度;(2) 按钮 `width: text_size.x + 24`(左右各 12 padding);(3) taffy 的 Column + `align_items: Center` 让整列水平居中。

### Lv3 · 设计迁移

**题**:你接到一个需求——游戏内一个 4×4 的库存网格(背包),每格 64×64 逻辑点,格子之间 4 点间距,整个网格在屏幕上居中,且当窗口宽度 < 400 时自动从 4 列变成 2 列(响应式)。用 flexbox + 断点描述这个布局的 style(伪代码或 taffy 调用),不要写实际渲染。

**提示**:每个格子 `flex_basis: 64, flex_grow: 0`,容器 `flex_wrap: Wrap, gap: 4`;断点切换容器的 `direction` 在 Row(宽屏)和 Column(窄屏)之间,或者保持 Row 但调 `basis` 让一行装不下 4 个就自动换行(更优雅)。

**参考答案**:

```rust
fn inventory_grid_style(container_w: f32) -> Style {
    let cols = if container_w >= 400.0 { 4 } else { 2 };
    Style {
        display: Display::Flex,
        direction: FlexDirection::Row,
        flex_wrap: FlexWrap::Wrap,
        align_items: Some(AlignItems::Center),
        justify_content: Some(JustifyContent::Center),
        // gap 是 CSS Grid 才有的统一属性;taffy 用 padding/margin 模拟
        size: Size::AUTO,
        // 每个 slot 的 basis = (container_w - gap*(cols-1)) / cols
        // 简化:让 slot flex_grow: 1, max_width: 64,这样宽屏多列窄屏少列
        ..Default::default()
    }
}
// 每个 slot:
// Style { flex_grow: 1.0, flex_basis: length(64.0),
//        max_size: Size { width: length(64.0), height: length(64.0) },
//        aspect_ratio: 1.0, ... }
```

关键是 `flex_wrap: Wrap` + 每个 slot `max_width: 64` + `flex_grow: 1`——宽屏下一行能塞 4 个就塞 4 个(grow 把它们撑到 max),窄屏下塞不下第 4 个就自动换到下一行。这是 flexbox 的响应式威力,几乎没有显式断点分支。

### Lv4 · 开源贡献

**题**:clone Bevy 引擎([https://github.com/bevyengine/bevy](https://github.com/bevyengine/bevy)),找到 `crates/bevy_ui/src/layout/` —— 它是 taffy 的封装。读 `ui_node.rs` 和 `layout.rs`,理解 Bevy 如何把 ECS 组件(`Node`, `Style`)翻译成 taffy 的 `TaffyTree`。然后做一个小贡献:

1. 找一个 issue 标 `C-bevy-ui`、`good-first-issue` 标签
2. 或者:给文档加一个"如何调试布局"的章节(看 taffy 输出的 `Layout` 结构)
3. 或者:写一个 `bevy_ui_debug_overlay`,运行时画出每个 `Node` 的最终矩形和 `desired_size`,这对调试布局极有用

读 Bevy UI 源码的同时也读 `taffy` 本身的源码([https://github.com/DioxusLabs/taffy](https://github.com/DioxusLabs/taffy))——它是目前 Rust 生态最完整的 flexbox + grid 实现,源码注释非常详细,是学习 flexbox 算法的最佳材料。

## 11 · 延伸阅读与下一篇

本仓库内交叉链接(按建议阅读顺序):

- `days/phase-7/deep-dives/game-ui-architecture.md` —— UI 系统的整体架构(retained vs immediate、widget 树、事件路由)。本篇假设你读过它。
- `days/phase-7/deep-dives/ui-data-binding-short.md` —— UI 控件如何绑定到游戏状态。布局决定"控件在哪儿",数据绑定决定"控件显示什么",两者共同构成 UI 系统。
- `days/phase-7/deep-dives/immediate-mode-editor.md` —— 调试 UI 的 immediate mode 风格,它内部的 `Layout::allocate` 是最简化的布局引擎,本篇的 flexbox 是它的"工业化版本"。
- `days/phase-7/deep-dives/hud-and-menu-systems.md` —— **下一篇(part 3/3)**。本篇讲了布局的"几何",下一篇讲 HUD 和菜单的"功能"——状态切换、暂停菜单的模态栈、HUD 元素的信息密度设计。布局引擎是 HUD/菜单的底座,读完两篇你就能从零做一个完整的主菜单 + HUD。
- `days/phase-7/deep-dives/accessibility-short.md` —— 布局正确是无障碍的前提:屏幕阅读器需要正确的控件树,键盘导航需要正确的 Tab 顺序(由布局顺序决定)。响应式 + 内容尺寸让低视力玩家放大字体时 UI 不破。
- `days/phase-7/deep-dives/localization-short.md` —— 内容驱动尺寸让本地化"just work"。本篇第 7 节是这一结合点。
- `days/phase-9/09F-3-cross-platform-and-portability.md` —— DPI / HIDPI 的跨平台细节(macOS retina、Windows 缩放、Linux Wayland 混合 DPI),本篇第 6 节的延伸。
- `spline-math`(phase-0 数学地基)—— UI 动画的曲线(easing、bezier)用 spline 数学。布局给出"目标矩形",动画给出"从当前矩形到目标矩形的时间曲线",两者结合才有顺滑的 UI 过渡。

外部稳定 URL:

- Cassowary 论文(Badros et al., 1996):[https://www.cs.washington.edu/research/constraining/cassowary/](https://www.cs.washington.edu/research/constraining/cassowary/)
- CSS Flexbox 规范(W3C):[https://www.w3.org/TR/css-flexbox-1/](https://www.w3.org/TR/css-flexbox-1/) —— flexbox 的权威定义,任何实现都是这个规范的实例化。
- taffy 文档(Rust):[https://docs.rs/taffy](https://docs.rs/taffy) —— Bevy UI、iced、Dioxus 共同的底层布局引擎。
- cosmic-text(Rust 文本布局):[https://github.com/pop-os/cosmic-text](https://github.com/pop-os/cosmic-text) —— System76 的 Cosmic 桌面用的文本库,集成了 shaping + measure + layout,可以作为字体度量那一节的工业级参考。
- swash(Rust shaping):[https://github.com/dfrg/swash](https://github.com/dfrg/swash) —— 纯 Rust 的字体 shaping 和度量库。
- Apple Auto Layout Guide:[https://developer.apple.com/library/archive/documentation/UserExperience/Conceptual/AutolayoutPG/](https://developer.apple.com/library/archive/documentation/UserExperience/Conceptual/AutolayoutPG/) —— Cassowary 在工业界最完整的实现文档,即使你不做 iOS 也值得读。
- Unreal UMG Anchors:[https://docs.unrealengine.com/5.0/en-US/umg-anchor-designers-in-unreal-engine/](https://docs.unrealengine.com/5.0/en-US/umg-anchor-designers-in-unreal-engine/) —— anchor 布局在游戏引擎里的视觉化实现。

**生产现实的提醒**:你日常会用框架自带的布局,而不是手写——Bevy UI 的 flexbox(底层 taffy)、Unreal UMG 的 anchors 和 Unified Grid、Unity 的 UI Toolkit(UXML/CSS,底层是约束 + flex 混合)、Godot 的 Container 节点(anchor + flex 风格)。**理解本篇讲的三大模型和两遍布局,不是为了让你重写一个 taffy,而是让你能看懂这些框架在做什么、为什么这么表现、出问题时往哪儿找**。区别"我的显示器上看着没问题"和"所有玩家的显示器上都对",就在这一份理解里。

下一篇 `hud-and-menu-systems.md` 把这套布局底座用在具体的 HUD 和菜单功能上——暂停菜单的模态栈、HUD 的信息密度、过场动画里的 UI 切换。
