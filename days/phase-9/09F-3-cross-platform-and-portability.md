---
phase: 9
sequence: "9F"
module: 3
title_en: "Cross-Platform & Portability"
title_zh: "跨平台与可移植性:让你的引擎活在每台机器上"
type: deep-dive
difficulty: 4
duration: "2-3 小时"
domains: [game, rust, engineering, linux]
prereqs: ["09F-2-release-engineering-and-live-ops", "09B-2-subsystems-modules-plugins"]
calibration: "平台抽象层设计 + 主机 TRC/TCR + 移动 + Web/WASM 概念 + 可移植心智(SCOPE: 桌面核心 + 概念性覆盖其余)"
---

# 09F-3 · 跨平台与可移植性

## 0 · 它在你这台 Arch 上跑得很美——然后呢

你的引擎终于跑起来了。你在自己那台装着 Arch + sway + mesa-git 的笔记本上,从空白的 `main.rs` 一路写到能加载关卡、跑物理、出声音、画 60 帧。你截了张图发到群里,有人问:"能编个 Windows 版给我试试吗?我朋友想玩。"你愣了一下,打开你的代码,开始搜 `/home/`、搜 `X11`、搜 `evdev`、搜 `dlopen`——发现这些东西像藤壶一样长满了你的代码外壳。你想编个 Windows 版,但 cargo 一切到 `x86_64-pc-windows-gnu` 就报几十个找不到符号的错。

这一刻你撞上的,是 Casey 在 Handmade Hero 里全程回避、但任何想"把游戏给别人玩"的人都必须直面的一个问题:**可移植性(portability)**。一台机器上能跑,叫 demo;能在你不知道型号、不知道系统、不知道 GPU 驱动版本的别人机器上稳定跑,才叫产品。这一篇讲的,就是怎么让你的引擎,从一个"在我的机器上能跑"的程序,变成一个"在它该跑的任何机器上都能跑"的工程产物。

这件事没有任何神秘配方,核心就是一条朴素到几乎是套话的原则,但很多人没真的理解它的分量——**写代码时,假设核心逻辑对平台一无所知**。下文我会把这条原则一点点拆开,讲它怎么落地成具体的 trait、cfg、目录结构,以及它在主机(console)、移动、Web 这些更 exotic 的目标上,变成什么样的具体约束。

## 1 · 可移植心智:最重要的一节,请认真读

我想先不讲任何代码,讲一种"思维方式"。因为代码可以查文档抄,思维方式抄不来,而可移植性这件事,90% 的失败都来自思维方式错位,而不是某个具体 API 用错。

可移植心智的核心是这样一句话:**你的核心代码,必须假设没有任何平台特定的东西存在**。这条听起来像废话,但落实起来非常反直觉,因为"平台特定的东西"远比你以为得多。我列几种你最可能踩的,你体会一下它们的隐蔽程度。

第一,文件路径。你在 Linux 上写 `format!("/home/{}/.config/mygame/save.json", user)`——这串字符串在 Windows 上没有任何意义(Windows 没有 `/home`,用户目录是 `C:\Users\...`,路径分隔符是反斜杠)。可移植的写法是,核心代码永远不拼路径字符串,而是问平台层要一个"用户存档目录",拿到一个 `PathBuf`,核心代码只往这个 PathBuf 里追加文件名,不关心它底层是 `/` 还是 `\`。Casey 在 HH 里 Day 一样会撞这个——他用了 `../data/` 这种相对路径,这在 Win32 上的语义和 Linux 不完全一致(驱动器根的解析不同)。

第二,字节序和指针大小。你在 x86_64 上写 `size_t` 是 8 字节,跨到 32 位 ARM 就是 4 字节;你在小端机器上写 `f32.to_le_bytes()` 之外的内存 cast,跨到大端机器(虽然现在少见,但 WebAssembly 的 SIMD、某些主机模拟器层会暴露这种问题)数据就错乱。可移植的代码不假设字节序,要么显式用 `to_le_bytes` / `from_le_bytes` 序列化,要么用 `#[repr(C)]` 配合明确的整型(`u32` 而不是 `usize`,因为 `usize` 在不同平台上大小不同)。

第三,直接调用 OS API。你在核心代码里 `std::process::Command::new("notify-send")` 弹通知——Linux 上能跑,Windows 上根本没有这个二进制。可移植的代码不直接调 OS API,所有 OS 调用都封装在平台层后面,核心代码通过一个 `Platform::notify(msg)` trait 方法调,具体怎么实现是平台层的事。

第四,线程模型假设。你假设可以随便 `std::thread::spawn`——在 WebAssembly 上历史上没有线程(现在有,但有诸多约束),在主机上有些沙箱环境线程创建受控。可移植的代码不假设"我能随时开线程",而是把并发抽象成一个调度器(详见 09B-2 的中央调度),由平台层决定实际跑几个线程。

你把这些"假设"一条条剥掉之后,剩下的核心代码——游戏规则、物理、动画曲线、ECS 查询——应该是**纯逻辑**,给它同样的输入,不管跑在哪台机器上,输出都一样。这就是 [phase-2/platform-game-separation](../phase-2/deep-dives/platform-game-separation.md) 里 Casey 那个三明治架构的精神内核:游戏层只看接口层(`GameMemory` / `GameInput` / `GameOffscreenBuffer`),看不到任何平台类型。这一篇做的事情,本质上就是把那个三明治架构**一般化、规整化、trait 化**,从"两个层"扩展到"任意多个平台后端"。

为什么这条心智这么重要?因为它决定了你的代码**未来能不能扩展**。如果你今天写代码时假设了"这是 Linux",那明天加 Windows 你要回去改核心代码——核心代码一改就要重测,重测就要重新发版,成本爆炸。反过来,如果你今天写代码时就坚持"核心不知道平台",那明天加 Windows 你只需要写一个新的平台层实现,核心代码一行不动——加平台变成"加一个文件",而不是"改一百个文件"。这个差距,是业余项目和职业项目的本质差距之一。

## 2 · 平台抽象层:把 phase-2 的三明治一般化

有了心智,我们看怎么把它落成代码。落地的核心是一个叫**平台抽象层(platform abstraction layer,PAL)**的东西,它就是 09B-2 讲的"分层思想"在跨平台这一维度的具体兑现。

PAL 的形态是若干个 trait,定义了"游戏核心对平台的所有需求"。最关键的几个:`Platform`(问平台要时间、要路径、要通知能力)、`Window`(拿到一个可以画图的窗口句柄)、`Input`(每帧的输入快照)、`AudioSink`(把样本推给音频设备)。游戏核心在每一帧,只调用这些 trait 上的方法,从不直接调任何 OS API。

我们看一个最小但真实的 `Platform` trait 长什么样:

```rust
// src/platform.rs —— 平台抽象层接口
// 这个文件必须没有任何 platform 特定的 import,只有 trait 定义
use std::path::PathBuf;
use std::time::Duration;

pub trait Platform: 'static {
    /// 返回用户存档目录,跨平台
    fn save_dir(&self) -> PathBuf;

    /// 返回资源(只读资产)目录
    fn asset_dir(&self) -> PathBuf;

    /// 系统启动后经过的时间(用于 dt 计算)
    fn now(&self) -> Duration;

    /// 弹一个 OS 原生通知(无则 no-op)
    fn notify(&self, _msg: &str) {}

    /// 是否在主线程(Rust 的 wasm 和某些主机要求 UI 操作在主线程)
    fn is_main_thread(&self) -> bool { true }

    /// 退出码:某些主机平台要求"通过特定的退出路径",不能直接 std::process::exit
    fn request_exit(&mut self) {}
}
```

注意几件事。第一,所有方法都返回**跨平台的类型**——`PathBuf` 而不是 `&str`,`Duration` 而不是 `u64` 毫秒。第二,有些方法给了默认实现(`notify` 默认 no-op),因为不是所有平台都有通知系统——核心代码可以放心调 `platform.notify("Auto-saved")`,在没通知系统的平台上它就是空操作,核心代码不崩溃、不分支。第三,trait 加了 `'static` 约束,这是为了能在 winit 的 event loop 里跨 await 持有(后面具体讲)。

接下来,每个具体平台写一个实现。Linux 桌面的实现大概是:

```rust
// src/platform/linux.rs
use crate::platform::Platform;
use std::path::PathBuf;
use std::time::{Duration, Instant};

pub struct LinuxPlatform {
    start: Instant,
    save_dir: PathBuf,
    asset_dir: PathBuf,
}

impl LinuxPlatform {
    pub fn new() -> Self {
        // 跨平台地查 $XDG_DATA_HOME / $HOME/.local/share
        let save_dir = dirs::data_dir()
            .unwrap_or_else(|| PathBuf::from("."))
            .join("handmade-hero");
        std::fs::create_dir_all(&save_dir).ok();
        Self {
            start: Instant::now(),
            save_dir,
            asset_dir: PathBuf::from("assets"),
        }
    }
}

impl Platform for LinuxPlatform {
    fn save_dir(&self) -> PathBuf { self.save_dir.clone() }
    fn asset_dir(&self) -> PathBuf { self.asset_dir.clone() }
    fn now(&self) -> Duration { self.start.elapsed() }

    fn notify(&self, msg: &str) {
        // 用 notify-rs crate,它内部抽象了 freedesktop notifications
        // 注意:不是 std::process::Command::new("notify-send")——那是 hardcoded 路径
        // 实际项目里把 notify-rs 包成一个字段,这里简化
        let _ = msg;
    }
}
```

Windows 的实现结构上一模一样,只是 `save_dir` 改成查 `dirs::data_dir()`(它在 Windows 上返回 `C:\Users\<user>\AppData\Roaming`),`notify` 改成用 Windows toast。**核心代码改了什么?零**。这就是 PAL 的力量:加一个平台 = 加一个文件,游戏逻辑不动。

那么主程序怎么选平台?这里 Rust 的 `cfg` 系统就登场了,我们下一节专门讲它。这一节的关键是建立这个直觉:**平台差异,封在 trait 实现里;核心逻辑,只看 trait**。这个直觉一旦建立,后面所有的 cfg、feature flag、目标三元组(target triple)都是它的工具而已。

## 3 · Rust 的 cfg:平台选择,不是逻辑分支

Rust 的条件编译系统(`cfg`)是这一篇的主力工具,但它也是新手最容易滥用的地方。我先讲它的正确用法,再讲它最常见的滥用——后者比前者重要。

`cfg` 是 attribute,告诉编译器"这段代码只在某些条件下编译进去"。最常见的用法是按目标操作系统选平台实现:

```rust
// src/main.rs
mod platform;

#[cfg(target_os = "linux")]
mod platform_linux;
#[cfg(target_os = "linux")]
use platform_linux::LinuxPlatform as HostPlatform;

#[cfg(target_os = "windows")]
mod platform_windows;
#[cfg(target_os = "windows")]
use platform_windows::WindowsPlatform as HostPlatform;

#[cfg(target_os = "macos")]
mod platform_macos;
#[cfg(target_os = "macos")]
use platform_macos::MacosPlatform as HostPlatform;

fn main() {
    let platform: HostPlatform = HostPlatform::new();
    run_game(platform);
}

/// run_game 接收的是 trait object,这里游戏核心开始
fn run_game<P: Platform>(platform: P) {
    // ... 游戏主循环,完全不知道 P 具体是什么
}
```

注意这里的关键纪律:**`cfg` 只用来"选择哪个 impl 编译进来",不用来"在游戏逻辑里分支"**。也就是说,`cfg` 出现的位置应该是平台层、是 impl 块的开关,而**不是**游戏核心代码里。下面这个写法是滥用:

```rust
// 反例:cfg 散落到核心代码里
fn update_player(player: &mut Player, input: &Input) {
    player.x += input.move_x;

    // 不要这样!
    #[cfg(target_os = "windows")]
    {
        // Windows 专属的某种特殊行为
    }
    #[cfg(not(target_os = "windows"))]
    {
        // 其他平台的行为
    }
}
```

这种写法的危害是:你编译 Windows 版本时,看到的是一份代码;你编译 Linux 版本时,看到的是另一份代码。两份代码不同步演进,你改了 Linux 版的行为忘了改 Windows 版,然后 Windows 玩家遇到 bug——但你本地从来只跑 Linux,所以测试覆盖不到。`cfg` 散落得越多,你的代码事实上就变成了 N 份独立的代码库,可移植性的初衷(一份代码到处跑)反而被破坏了。

正确做法是把平台差异收敛到 PAL 实现里。如果"Windows 上的某种行为"真的存在,它应该作为 `Platform` trait 的一个方法暴露出来,由 `WindowsPlatform` 实现成 Windows 专属行为,其他平台实现成默认行为(或 no-op)。游戏核心代码永远写一份,它调 `platform.something()`,具体行为由 trait 实现决定——这就是上一节讲的"封在 trait 实现里"的纪律的延伸。

`cfg` 还能用于 feature flag,表达"可选能力",而不是"平台差异"。比如你的引擎支持"启用 Vulkan 后端"和"只启用 OpenGL 后端",可以用 cargo feature:

```toml
# Cargo.toml
[features]
default = ["renderer-opengl"]
renderer-opengl = []
renderer-vulkan = ["ash"]          # 启用 vulkan 时才拉 ash 依赖
```

```rust
// src/renderer/mod.rs
#[cfg(feature = "renderer-opengl")]
mod opengl;
#[cfg(feature = "renderer-opengl")]
pub use opengl::OpenglRenderer;

#[cfg(feature = "renderer-vulkan")]
mod vulkan;
#[cfg(feature = "renderer-vulkan")]
pub use vulkan::VulkanRenderer;
```

这里 `cfg(feature = ...)` 的纪律和 `cfg(target_os = ...)` 一样:它选择"哪个后端编译进来",不改变游戏逻辑。游戏核心拿到的始终是一个 `dyn Renderer` trait 对象(这就是 [09B-2](09B-2-subsystems-modules-plugins.md) 里说的"把渲染抽象成 trait"),它不知道也不关心底下是 OpenGL 还是 Vulkan。这种 cfg 用法是健康的——它让你能在一台没装 Vulkan SDK 的开发机上照样编译(只开 `renderer-opengl`),在 CI 矩阵里两个都测。

补充一个易踩的点:`cfg` 的判断在编译期完成,所以你**不能**用 `cfg` 来根据"用户机器上有没有 Vulkan 驱动"做运行时选择。运行时选择是另一回事——你需要在 `main` 里 try 一下 Vulkan,失败 fallback 到 OpenGL,这是普通的运行时分支,跟 `cfg` 无关。新手容易把这两者混淆,写出一堆 `cfg!()` 运行时调用的怪代码,事实上 `cfg!()` 返回的是编译期常量,在 Windows 版里永远是 windows,不能用来检测运行时环境。

## 4 · 平台扩展:加一个新平台是什么体验

讲了心智、PAL、cfg,我们用"加一个新平台"这个具体动作,把三者串起来体验一下。这一节非常短,因为它要传递的就一个直觉:**加平台是廉价的**。

假设你已经按前两节的方式组织了代码:有 `Platform` trait,有 `LinuxPlatform` 和 `WindowsPlatform` 两个实现,核心代码只依赖 trait。现在你想加 macOS 支持。你需要做什么?

写一个 `src/platform_macos.rs`,实现 `MacosPlatform`,它内部用 Cocoa(通过 `objc2` crate)创建窗口、用 CoreAudio 推样本、用 `dirs::data_dir()` 拿到 `~/Library/Application Support/handmade-hero` 作为存档目录。然后在 `main.rs` 加三行:

```rust
#[cfg(target_os = "macos")]
mod platform_macos;
#[cfg(target_os = "macos")]
use platform_macos::MacosPlatform as HostPlatform;
```

完事。`run_game` 函数、游戏逻辑、ECS、物理、动画、资产管线——一行不改。你 `cargo build --target x86_64-apple-darwin`(在 macOS 上),出来一个 `.app`,丢给朋友,他能玩。

对比一下"如果当初没做 PAL,代码里到处是 `#[cfg(target_os = "linux")]` 和直接调 `evdev`"的情况:加 macOS 你要回到每一处 cfg,加上 macOS 分支;每一个直接调的 OS API,都要找 macOS 对应物;改完之后,因为之前 Linux 和 Windows 是两份独立演进的代码,你大概率在 macOS 上撞到一堆"这两个分支行为不一致"的 bug。加平台的成本,从"加一个文件"变成了"重写半个引擎"。这就是为什么 PAL 要从 day 1 就做,不是"以后再说"——以后再做的成本是 day 1 做的十倍。

## 5 · 主机概念:TRC/TCR 与"为多平台设计"

讲完桌面三平台(Win/Mac/Linux),我们往外扩一步,讲讲主机(console:PlayStation、Xbox、Switch)。这里有个重要的前提声明:**主机开发需要授权(license)和受 NDA 保护的 devkit**,本文不会、也不能讲任何 NDA 内容。下面讲的都是公开资料、Sony/Microsoft/Nintendo 官方公开的开发者文档、GDC 演讲里反复说过的东西。但理解这些公开的概念,对你"为多平台设计"至关重要。

主机和 PC 最大的区别,不是硬件(虽然硬件也有差异),而是**认证(certification)**。Sony、Microsoft、Nintendo 各自维护一份叫 **TRC**(Technical Requirements Checklist,Sony 用语)或 **TCR**(Technical Certification Requirements,Microsoft 用语)或类似的文档,它是"你的游戏想上我们的平台,必须满足的几百到上千条规则"。这些规则涵盖了你能想到和想不到的方方面面,我举几类你体会一下。

第一类,稳定性。规则可能是"连续运行 24 小时,崩溃次数不超过 N 次"、"内存峰值不超过系统预留之外的部分"。这些规则逼着你做好 9F-2 讲的崩溃监控和内存预算。

第二类,用户交互一致性。规则可能是"按手柄的 PS 按钮必须能弹出系统菜单"、"用户在系统层挂起游戏(suspend),回来时游戏必须正确恢复,不能崩溃"、"手柄光(light bar)的行为必须遵循系统级设置"。这些规则意味着你不能假设"我的游戏独占输入设备",事实上主机的 OS 在你的游戏上面随时可能插手,你必须正确响应系统事件。

第三类,存档和退出。规则可能是"任何时候用户按系统的'回到主菜单'键,游戏必须在 N 秒内回到主菜单"、"存档失败必须给用户明确提示,不能静默丢失"、"游戏内必须有'退出'选项,不能让用户只能强制关机"。听起来像废话,但很多 PC 游戏移植到主机就栽在这些规则上——PC 上你随便崩,用户重启;主机上你崩,认证就不过,游戏上不了架。

第四类,平台特性集成。规则可能是"必须支持系统的成就(achievement)系统"、"必须支持主机特定的分享功能(比如 Switch 的截图按钮、PS 的分享菜单)"、"必须用主机的特定社交/在线服务 API"。这些规则意味着你的游戏不能假设"我的存档存在本地文件就行",你可能需要把存档同步到云端(主机的云存档服务),把成就上报到主机平台。

理解了这些规则,你就能理解一句业界格言:"**designed for console from day 1**,比 port later 容易十倍"。为什么?因为 TRC/TCR 这些规则,很多是**架构层面**的要求,不是后期可以打补丁的。比如"系统挂起恢复后不崩溃"——如果你的游戏假设"我永远不会被挂起"(比如在初始化时锁定了某些 GPU 资源,假设它们一直可用),那么挂起恢复时这些资源可能失效,游戏崩溃。要满足这条规则,你必须在架构层面把"挂起/恢复"作为生命周期的一部分(就像 09B-2 讲的初始化/关闭是生命周期的一部分一样),从一开始就设计好。等到移植阶段再发现"我的架构不支持挂起",你就要重构核心循环——成本巨大。

所以,即使你现在根本不打算上主机,**用"主机思维"设计你的游戏,本身就是一种防御性的可移植性投资**。具体怎么做?让你的游戏循环能响应"被挂起"事件(在 winit 里是 `Suspended` / `Resumed` 事件);让你的资产加载能从"任意路径"加载,不硬编码本地文件系统(为云存档、主机的虚拟文件系统留口子);让你的存档系统是异步的、可失败的(不假设"存档一定成功");让你的输入系统能接入"非键盘鼠标的输入设备"(包括手柄、触摸,以及主机的特殊输入)。这些设计,在 PC 上看起来是"过度工程",但它们正是主机认证要查的东西,你做了它们,未来某天上主机就顺理成章;没做,未来上主机就要从头改。

GDC 上有大量公开演讲讲这些,Jason Gregory 的《Game Engine Architecture》第三版也花了整整一章讲"主机引擎架构",值得作为延伸阅读。这里我们只讲概念,因为实操层面没有 devkit 你做不了——但概念层面的"为多平台设计",你现在就能做,也应该做。

## 6 · 移动概念:触屏、热预算、生命周期

接下来讲移动(iOS / Android)。同样,这不是手把手教程(那需要 Mac + Xcode / Android Studio + NDK 的环境,且细节高度版本相关),而是讲"移动"这个目标平台,在可移植性设计上,逼着你考虑哪些 PC 上不存在的问题。

第一,输入。PC 有键盘鼠标,主机有手柄,移动只有触屏(以及加速度计、陀螺仪)。触屏的语义和键盘完全不同——键盘是离散事件(按下、松开),触屏是连续的多个接触点,每个接触点有位置、压力、生命周期(down/move/up)。如果你的 `Input` trait 只表达了"按钮状态",那你到了移动就要重新设计这个 trait。可移植的做法是,`Input` trait 同时支持"离散按钮"(把触屏的某些区域映射成虚拟按钮)和"原始指针事件"(让游戏能直接读触摸点),两种风格都暴露——这样在 PC 上键盘映射成虚拟按钮,在移动上触屏也映射成虚拟按钮 + 原始指针,游戏逻辑可以两种都用。

第二,性能 / 散热 / 续航预算。手机的 SoC 比你想象得强,但它**没有风扇**。你跑满 GPU 几分钟,SoC 温度上来,系统会**降频**——你的 60 帧突然掉到 30 帧,不是因为代码慢了,是因为硬件被锁频了。这种"热节流(thermal throttling)"是移动平台的核心约束。可移植的设计必须包含"动态画质"——监测帧时间,发现要掉帧了,主动降低渲染分辨率、关掉某些效果,而不是死扛到被系统强制降频。这种动态调整在 PC 上也有用(不同配置的 PC),但在移动上是刚需。

第三,内存压力。手机的 RAM 远比 PC 小(旗舰机 8-12 GB,中端机 4-6 GB,且 OS 占了一大半),且 OS 随时可能因为内存紧张杀掉后台 App(包括你的游戏)。可移植的资产管线必须支持**流式加载(streaming)**,不能"启动时把所有资产加载进内存"——这在 PC 上能跑,在移动上直接 OOM。流式加载意味着你的资产要能分块、按需加载,详见后续 phase 讲的资产管线。

第四,也是最特殊的——**App 生命周期**。在 PC 上,你的进程从启动到退出,一直活跃。在移动上,用户随时可能按 Home 键,你的 App 被切到后台——这时 OS 可能暂停你的进程(不给 CPU 时间片),可能回收你的 GPU 资源,甚至可能直接杀掉你的 App(用户切换到别的 App,内存不够,你的 App 被终结)。你的游戏必须正确响应这些事件:`onPause` / `onResume`(Android)或 `applicationDidEnterBackground` / `applicationWillEnterForeground`(iOS)。被切到后台时,你要停止渲染、停止音频、保存状态(防止被杀后丢档);回到前台时,你要重建可能被回收的 GPU 资源、恢复音频。这套生命周期处理,和上一节讲的"主机挂起/恢复"在架构上是一回事——你的游戏循环必须把"挂起"和"恢复"当作正常事件,不能崩溃。

Rust 生态里,移动跨平台的主流路径是 `cargo-ndk`(Android)和 `cargo-lipo`(iOS),它们把 Rust 代码编译成 `.so` / `.a` 静态库,然后用 Kotlin / Swift 写一个薄薄的壳调 Rust。Bevy 在这条路径上已经走得相当远,可以作为参考。但对你的 HH 项目,我的建议是:**先在桌面上把 PAL 做扎实,移动是远期目标**。移动的开发迭代周期(编译、部署到设备、调试)远比桌面慢,在桌面上把架构打磨好,移动移植会顺很多。

## 7 · Web/WASM 概念:浏览器沙箱与 wasm32 目标

最后一块是 Web,目标是 `wasm32-unknown-unknown`(或更具体的 `wasm32-unknown-emscripten`)。Web 是一个特殊的"平台",因为它不是操作系统,而是浏览器沙箱——你的代码跑在一个受限环境里,这个环境有它自己的一套约束。

第一,线程。WebAssembly 历史上是单线程的,WebWorker 可以做并发但共享内存受限(`SharedArrayBuffer` 需要 COOP/COEP 头,部署复杂)。如果你的代码到处 `std::thread::spawn`,到 WASM 上要么不可用,要么需要重写。可移植的设计在 Web 上把并发抽象成"任务调度器",由平台层决定是开真线程(PC)还是用 WebWorker + SharedArrayBuffer(Web),还是干脆单线程跑(Web 的最简路径)。Bevy 的 `TaskPool` 就是这么做的——它内部抽象了不同的执行后端。

第二,文件系统。浏览器没有真正的文件系统,你写 `std::fs::read("assets/player.png")` 在 WASM 上要么失败,要么依赖某个 polyfill(比如 wasm-bindgen 的虚拟 FS,把资产打进 wasm 里)。可移植的资产加载不直接用 `std::fs`,而是通过 `Platform::load_asset(name) -> Vec<u8>` 这样的 trait 方法,Web 实现用 `fetch()` HTTP 请求(异步),PC 实现用 `std::fs::read`。注意 Web 的 fetch 是异步的,这意味着 PAL 的某些方法在 Web 上天然是异步的——这是把异步引入 PAL 的一个动机(Rust 里用 `async fn` 或返回 `Future`)。

第三,GPU。Web 的 GPU 是 WebGL(基于 OpenGL ES)或 WebGPU(更新的标准,接近 Vulkan/Metal/D3D12 的抽象)。你的渲染层如果直接用 `gl` crate 调 OpenGL,在 Web 上能跑(WebGL 就是 OpenGL ES),但性能和功能受限;如果你用 `wgpu`(一个跨平台 GPU 抽象层,自动编译到 Vulkan/Metal/D3D12/WebGPU),那一份渲染代码同时覆盖桌面和 Web。Bevy 的渲染就是基于 wgpu 的,这是它能"一份代码跑桌面 + Web"的关键。

第四,下载体积。Web 用户每次访问你的页面,都要下载 wasm 文件 + 资产。一个 50MB 的 wasm(在 PC 上无所谓)在 Web 上是灾难——加载慢、流量贵、用户没耐心。Web 项目对二进制体积极度敏感,你需要用 `wasm-opt` 压缩、用 `twiggy` 分析体积、把大资产拆出来按需 fetch(不打包进 wasm)。这又回到我们前面说的"流式加载"——它在 Web 上和移动上一样关键,理由不同(移动是为了省内存,Web 是为了省首次下载量)。

Rust 编译 WASM 的基本流程是:

```bash
# 装 wasm32 target
rustup target add wasm32-unknown-unknown

# 编译(没有 main,因为 Web 不用传统 main)
cargo build --target wasm32-unknown-unknown --lib

# 用 wasm-bindgen 生成 JS 胶水代码
wasm-bindgen --target web \
    target/wasm32-unknown-unknown/debug/libhandmade_hero.wasm \
    --out-dir web/

# 之后用任意静态服务器托管 web/ 目录
# 在 web/ 里有一个 JS 文件 + 一个 wasm 文件 + 一个 index.html
```

如果你的项目用了 `wgpu` + `winit`(都支持 wasm32),理论上加几行 cfg + 一个 index.html,你的游戏就能在浏览器里跑。这是 Rust 游戏开发生态近年来最大的进步之一——五年前"WASM 跑游戏"还是实验性的,现在已经是生产可行的路径。但仍然有约束(线程、文件、体积),所以"在桌面上把 PAL 做好,Web 移植自然落地"的策略,在 Web 上同样适用。

## 8 · 在你 HH 项目里动手(做中学红线)

理论讲完了,这一节是这篇的"做中学红线"——我建议你在你的 HH 项目上,具体做下面这几件事,把可移植性从概念变成验证过的事实。我按优先级排,前面的是必须做的,后面的视你精力而定。

第一步,**审计你的代码里的平台假设**。打开你的 HH 项目,搜这几个东西:任何硬编码的路径字符串(尤其是 `/` 或 `\` 开头的)、任何直接对 `std::fs` 的调用(在游戏核心代码里,不在平台层)、任何 `cfg(target_os` 在游戏核心代码里的出现(它应该只出现在平台层)、任何 `usize` 用在序列化场景(应该用 `u32` / `u64`)、任何假设线程的代码(`std::thread::spawn` 在核心循环里)。把搜到的东西列成一个清单。这个清单就是你的"可移植性债务"。

第二步,**引入一层薄的 `Platform` trait**(如果你还没有的话)。哪怕它一开始只有三个方法:`save_dir() -> PathBuf`、`asset_dir() -> PathBuf`、`now() -> Duration`。把你核心代码里所有直接访问文件系统的位置,改成通过这个 trait 访问。这一步是把 phase-2/platform-game-separation 的三明治,在 Rust 里正式 trait 化——它和 09B-2 的子系统分层是同一个原则的不同切面。

第三步,**把你的游戏编到第二个目标上**。这一步是可移植性的"证明",理论说一万遍不如真的编一次。两个推荐路径:

路径 A(更现实):从 Linux 交叉编译到 Windows。这是 9F-1 讲的交叉编译的直接应用:

```bash
# 装 Windows GNU target
rustup target add x86_64-pc-windows-gnu

# 装 mingw 工具链(Arch 上)
sudo pacman -S mingw-w64-gcc

# 编译
cargo build --target x86_64-pc-windows-gnu --release

# 产物在
# target/x86_64-pc-windows-gnu/release/handmade-hero.exe
# 拷贝到 Windows 机器(或 wine)上跑,验证它行为一致
```

如果这一步报错,恭喜——这些错误就是你的"隐藏平台假设",`cfg` 报不出来的、运行时才暴露的假设,会在编译另一个目标时变成编译错误暴露出来。修一个少一个。

路径 B(更有野心):编 WASM,跑在浏览器里。前提是你用了 `winit` + `wgpu`(或软光栅)且没有直接调 OS API。如果用了,`cargo build --target wasm32-unknown-unknown` 应该能过,然后用 `wasm-bindgen` 包装一下,丢到静态服务器上,你就能在浏览器里玩你的游戏。这是一次非常 rewarding 的体验——你写了一份 Rust 代码,它在你的 Arch 笔记本上跑,同时也在你朋友的 Windows 上跑,还在任何人的浏览器里跑,行为完全一致。这就是可移植性的兑现时刻。

第四步(可选但极有价值),**给你的 PAL 写一个 mock 实现用于测试**。这就是 9A-1 一直强调的"可测架构"在跨平台维度的兑现。你写一个 `MockPlatform`,它实现 `Platform` trait,但 `save_dir` 返回一个 `tempfile::tempdir()` 的临时目录,`now` 返回你可控的虚拟时间。你的游戏核心逻辑可以在 CI 里(没有任何窗口、GPU、音频设备的环境下)完整跑起来,因为它依赖的是 `MockPlatform`,不是真实平台。这是 PAL 一个被低估的副产物——它不只让你跨平台,还让你"脱离平台"测试,而脱离平台测试是 CI 的基础(详见 9F-1)。

做完这几步,你的 HH 项目就不再是"在我的 Arch 上能跑的 demo",而是"一个有 PAL 抽象、有跨平台证明、可在 CI 里测试的可移植引擎"。这个状态是后续所有平台扩展(主机、移动、Web)的地基。

## 9 · 练习

练习一(Lv1,概念辨析)。下面两段代码,哪个符合可移植心智,哪个违反?为什么?A:`let save_path = format!("/home/{}/.save", username);`。B:`let save_path = platform.save_dir().join("save.dat");`。请用自己的话解释 B 为什么优于 A,以及 A 在 Windows 上具体会怎么坏。

练习二(Lv2,动手实践)。完成 §8 的第一步和第二步——审计你的 HH 项目,列出平台假设清单,然后引入一个最小的 `Platform` trait 并把至少三处直接文件系统访问改成通过 trait。提交一个 commit,commit message 写明你解开了哪几处假设。这是把这篇落到代码上的最低门槛。

练习三(Lv3,跨平台证明)。完成 §8 的第三步——选择路径 A(交叉编译到 Windows)或路径 B(编译到 WASM),让你的游戏在第二个目标上跑起来。写一份简短的报告:哪些假设在编译第二个目标时暴露了?你怎么修的?运行行为是否和原平台一致?这个练习的价值不在于"编出一个 exe",而在于"暴露并修复隐藏假设"。

练习四(Lv4,设计进阶)。为你的 `Platform` trait 加上"挂起/恢复"生命周期事件(对应主机的 suspend/resume,移动的后台/前台,Web 的页面隐藏/可见)。在你的游戏循环里正确处理这两个事件:挂起时停止渲染和音频,恢复时重建 GPU 资源。验证方法:在 PC 上模拟,按某个调试键触发"挂起",几秒后触发"恢复",游戏应该正确恢复不崩溃。这个练习是为未来主机/移动做的"防御性架构投资"。

## 10 · 9F 序列收口

这一篇是 9F 序列(构建、发布、运维、可移植)的最后一篇。我花一节把这个序列串起来,让你看清这四件事是怎么连成一个完整的"工程闭环"。

9F-1 讲的是**构建与交叉编译**——怎么用 cargo 的 target 三元组、CI 矩阵、缓存策略,让你的代码在多平台上 reproducibly 地变成二进制产物。9F-2 讲的是**发布工程与 live-ops**——怎么版本化、怎么分发、怎么监控线上崩溃、怎么热修。9F-3(本篇)讲的是**可移植性**——怎么从架构层面,让你的代码本身对平台无感,从而"加一个平台"变成"加一个文件"而不是"重写半个引擎"。

这三件事的关系是这样的:可移植性(9F-3)是地基——如果你的代码本身不可移植,那 9F-1 的交叉编译编不出来,9F-2 的"在多个平台监控崩溃"也无从谈起。有了可移植性,9F-1 让你能在 CI 里 reproducibly 地为每个目标平台产出二进制——这是"ship"的前置。有了 reproducible 的多平台二进制,9F-2 让你能在每个平台上分发给用户、监控线上健康、热修问题——这是"maintain"的能力。这三步合起来,把你的 HH 项目从一个"在我的机器上能跑的程序",变成了一个"能 reproducibly 构建、能多平台分发、能线上维护、且未来能扩展到新平台"的**工程产物**。

这正是 Handmade Hero 这门课**结构性缺失的那一层**。Casey 的教学极其精彩地覆盖了"怎么从零写一个游戏的内部"——开窗、画像素、播声音、热重载、内联优化——但 HH 全程假设"我跑在 Win32 上,永远只跑在 Win32 上",从未讲过"怎么让这个游戏跑到别的平台上"。这不是 Casey 的疏忽,而是 HH 的范围选择——他要讲的是"游戏的内部",不是"游戏的工程化"。但你想做一个真正能给别人玩、能持续维护、能商业化的产品,工程化这一层是必须补上的,而这正是 9F 这三篇做的事。

补完 9F,你的 HH 项目在工程层面就不再是 demo 了。接下来 9G 序列会进入新的主题(从 [09G-1](09G-1-...) 开始),继续把你的引擎往更深的维度推进。但 9F 这一关过了,你就有了"把一个游戏真正 ship 出去"的能力——这个能力,是任何想走职业游戏开发路线的人,绕不过去的一关。

## 11 · 延伸阅读与下一篇

本仓库内,这一篇的主题和以下几篇强相关,推荐连读:[09B-2](09B-2-subsystems-modules-plugins.md) 讲的子系统分层和 trait 化,是 PAL 的架构基础;[phase-2/platform-game-separation](../phase-2/deep-dives/platform-game-separation.md) 的三明治架构,是 PAL 的思想源头;[phase-1/win32-to-winit](../phase-1/deep-dives/win32-to-winit.md) 的迁移故事,是"从平台特定到平台抽象"在窗口系统上的具体案例;[09F-1](09F-1-ci-cd-and-build-engineering.md) 讲的交叉编译,是这一篇 §8 路径 A 的工具基础;[phase-0/09-editor-toolchain](../phase-0/09-editor-toolchain.md) 讲的工具链,是理解 target 三元组和 cfg 系统的前置。

外部参考:Jason Gregory《Game Engine Architecture》第三版有一整章讲主机引擎架构和平台抽象,是这一主题最权威的参考;wgpu 的文档(docs.rs/wgpu)和 Bevy 的 `bevy_window` / `bevy_render` crate 源码,是 PAL 在 Rust 生态里的工业级实现,读它们比读任何书都直观;Sony / Microsoft / Nintendo 各自的公开开发者门户(developer.playstation.com / developer.microsoft.com / developer.nintendo.com)有公开的 TRC/TCR 概述文档,虽然完整版需要授权,但公开部分已经足够你建立"主机认证"的心智模型。GDC Vault 上有大量"shipping on console"主题的演讲,免费可看,强烈推荐。

下一篇 [09G-1](09G-1-...) 将开启 9G 序列的新主题。在进入 9G 之前,建议你把 9F 这三篇的做中学红线至少做一遍——构建一个 reproducible 的 release、引入一个版本与分发策略、做出一个能在第二个平台上跑的 PAL 抽象。这三件事做完,你就拥有了"ship"的能力,这是后续所有更高级工程能力的前提。
