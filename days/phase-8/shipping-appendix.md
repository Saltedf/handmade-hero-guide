---
phase: 8
type: appendix
title_en: "Shipping Appendix (Short)"
title_zh: "发布附录(简版)"
domains: [game, rust, shipping, platform]
duration: "2h"
---

# 发布附录:Steam / 主机 / 移动 / Web(简版)

> 你的游戏做完了。Rust 二进制 50MB,在 Linux 跑得好。下一步——上架 Steam。你打开 Steamworks 后台,看见一堆 SDK、API、证书、NDA、平台分成。每个平台规则不同,每条规则踩坑都是 1-2 周延期。
>
> 这份附录简版覆盖主流发布平台,从 Steam SDK 到 Steam Deck Verified,讲清楚每条路径的工程要点。

## 0 · Steam SDK / Steamworks

Steam 是 PC 游戏最大平台(2026 年 ~75% PC 游戏市场份额)。Steam 提供 Steamworks SDK,让游戏集成:

- **成就(Achievements)**:玩家完成特定目标,Steam 自动记录。Game 改用 Steam API 触发 `SteamUserStats()->SetAchievement("achievement_id")`
- **云存档(Cloud Saves)**:玩家在不同电脑玩同一存档。Steam 自动同步 `steamapps/compatdata/<appid>/pfx/...` 下的文件
- **Workshop**:mod 系统(参考 `scripting-and-modding.md`)
- **排行榜(Leaderboards)**:全球分数榜
- **多人(Lobby / Matchmaking / P2P)**:通过 Steam 网络中继
- **统计(Stats)**:玩家累计游戏时长 / 击杀数等
- **Rich Presence**:好友列表显示玩家状态("正在玩第 3 关")
- **Overlay**:Shift+Tab 打开 Steam 内嵌 UI

Rust 集成用 `steamworks` crate:

```toml
[dependencies]
steamworks = "0.11"
```

```rust
use steamworks::Client;

fn main() {
    let (client, single) = Client::init_app(480).unwrap();  // 480 = Spacewar 测试 app
    
    // callback 线程
    std::thread::spawn(move || {
        loop {
            single.run_callbacks();
            std::thread::sleep(std::time::Duration::from_millis(16));
        }
    });
    
    // 触发成就
    let stats = client.user_stats();
    stats.set_achievement("FIRST_WIN").unwrap();
    stats.store_stats().unwrap();
}
```

`Client::init_app(app_id)` 需要 Steam 客户端运行 + 玩家拥有这个 app。开发期间用 `480`(Spacewar,Valve 给开发者的测试 app)或自己的 app_id(Steam Direct 注册后获得)。

`steam_appid.txt` 文件让游戏知道自己的 app_id(放在 binary 同目录):

```
1234560
```

发布时把 Steam API DLL/SO 打包进游戏目录。Steam 看不到 SDK 的游戏无法上 Steam(强制要求至少基础 Steam 集成)。

## 1 · Epic Online Services

Epic Games 的跨平台 SDK。一次集成,所有平台(PC / 主机 / 移动)都有:

- 跨平台账号连接(Epic / Steam / PlayStation / Xbox / Switch 同一身份)
- 跨平台好友 / 邀请
- 跨平台匹配
- 跨平台语音
- 反作弊(Easy Anti-Cheat 集成)
- 用户 progresión

**最大卖点**:**跨平台多人**。一个 Steam 玩家能和 PSN 玩家联机(传统上平台之间不互通)。Fall Guys、Fortnite、Rocket League 都用 EOS 做跨平台。

Rust 生态 EOS 绑定不成熟,主要靠 C SDK + FFI:`eos-rs` 是社区尝试,2026 年还在早期。游戏集成 EOS 通常是 C/C++ 代码做桥接。

**Epic 抽成 12%**(Steam 30%,Epic 12%,所以部分开发者签 Epic 独占)。

## 2 · 主机 NDA(不能讲技术细节)

发布到 PlayStation / Xbox / Switch **必须签 NDA**(Non-Disclosure Agreement)。NDA 内容大致:

- 不能公开 SDK 文档
- 不能公开 devkit 硬件细节
- 不能讨论 cert(认证)流程的具体测试项
- 不能讨论平台分成具体比例(只说"市场标准")
- 不能泄露其他开发者的认证问题

所以**主机开发细节不能在这份附录里讲**。能讲的:

**流程**:

1. 注册开发者账号(PlayStation Partners、ID@Xbox、Nintendo Developer Portal)
2. 购买 / 租赁 devkit(几万美元,或免费借给认证开发者)
3. 用平台 SDK 在 devkit 上 build
4. 提交 cert(platform certification),平台测试
5. cert 通过后发布

cert 测试内容包括:崩溃 / 性能 / TRC(Technical Requirements Checklist,平台制定的标准)、内容审查(ESRB / PEGI 评级)、本地化覆盖、无障碍基本要求。

**典型时间线**:提交到发布 6-12 周。一次 cert 失败要 2-4 周修复 + 重新提交。**所以主机发布要预留 6 个月 buffer**。

**Rust 在主机的挑战**:平台 SDK 是 C++ / C#,Rust 桥接需要手写 FFI。Rust 编译到 PS5 / Xbox Series 的工具链不成熟。**当前工业实践:核心引擎 Rust,主机 SDK 用 C++,通过 FFI 连**。或者完全 C++ 主机版 + Rust PC 版双维护。

## 3 · iOS / App Store

iOS 发布要点:

- **语言**:原生 Swift / Objective-C。Rust 用 `cargo lipo` 或 `cargo build --target aarch64-apple-ios` 交叉编译成静态库,Swift 调用
- **图形 API**:Metal(不是 OpenGL / Vulkan)。Rust 用 `metal-rs` 或 wgpu(Metal 后端)
- **App Store 审核**:1-2 周,严格(内容、隐私、内购规则)。苹果会拒绝"看起来像信用卡游戏但有真钱内购"的应用
- **抽成**:30%(年订阅 2 年后 15%)。Epic vs Apple 官司后允许"外部链接付费"
- **App Tracking Transparency**:必须问玩家是否允许追踪(IDFA)
- **Sign in with Apple**:如果你提供 Google / Facebook 登录,必须提供 Apple 登录

**Rust + iOS 工程模式**:

```bash
# 编译 Rust 为 iOS 静态库
rustup target add aarch64-apple-ios aarch64-apple-ios-sim
cargo build --release --target aarch64-apple-ios --lib
# 生成 libyourgame.a

# Xcode 项目链接这个 .a,Swift 调用 Rust 导出的 C 函数
```

```rust
// Rust 暴露给 Swift
#[no_mangle]
pub extern "C" fn game_init() {
    // 游戏初始化
}

#[no_mangle]
pub extern "C" fn game_render_frame() {
    // 渲染一帧
}
```

Swift 端:

```swift
// bridging header
import Foundation

@_silgen_name("game_init")
func game_init()
@_silgen_name("game_render_frame")
func game_render_frame()

// SwiftUI view
struct GameView: UIViewRepresentable {
    func makeUIView(context: Context) -> MTKView {
        let view = MTKView()
        game_init()
        return view
    }
    
    func updateUIView(_ uiView: MTKView, context: Context) {
        game_render_frame()
    }
}
```

## 4 · Google Play

Android 发布:

- **图形**:Vulkan / OpenGL ES。Rust 用 wgpu(Vulkan 后端)
- **架构**:arm64-v8a、armeabi-v7a、x86_64。**arm64 占 99%,可以只发 arm64**
- **APK vs AAB**:Play Console 强制 AAB(Android App Bundle),不接 APK。AAB 是上传格式,Google Play 自动按用户设备生成 APK
- **审核**:1-7 天,比 Apple 宽松
- **抽成**:30%(年收入 < 100万美元 降到 15%)
- **Google Play Games for PC**:Google 让 Android 游戏在 PC 跑(Windows)。Rust 游戏本来就在 PC 跑,这条对你没用

**Rust + Android 工程**:

```bash
rustup target add aarch64-linux-android
cargo install cargo-ndk
cargo ndk -t arm64-v8a build --release --lib
# 生成 libyourgame.so
```

`.so` 放进 Android Studio 项目的 `app/src/main/jniLibs/arm64-v8a/`。Java / Kotlin 调用:

```kotlin
external fun gameInit()
external fun gameRenderFrame()

companion object {
    init {
        System.loadLibrary("yourgame")
    }
}
```

## 5 · WebAssembly / WebGL

把 Rust 游戏编译成 WebAssembly,跑在浏览器里:

```bash
rustup target add wasm32-unknown-unknown
cargo build --release --target wasm32-unknown-unknown
# 生成 .wasm 文件

# 用 wasm-bindgen 生成 JS 桥接
cargo install wasm-bindgen-cli
wasm-bindgen --out-dir web target/wasm32-unknown-unknown/release/yourgame.wasm
```

WebGL 渲染:Rust 用 `wgpu`(WebGL 后端)或 `web-sys` 直接调 WebGL API。

**Wasm 游戏注意**:

- **文件系统**:浏览器不能直接访问文件系统。`std::fs::read` 会失败。用 `js-sys` 调 JS 的 Fetch API 拿资源
- **二进制大小**:Rust 编译到 Wasm 通常 5-20 MB。要 wasm-opt / twiggy 优化
- **音频**:浏览器有特殊音频策略(autoplay policy,需要用户交互后才能播音)
- **多人**:WebRTC / WebSocket。HTTP polling 不够实时
- **性能**:Wasm 大概是原生的 70-90%,慢的主要是 JS 调 Wasm 的边界

 itch.io、CrazyGames、Poki 这些平台支持 Wasm 游戏。

## 6 · itch.io / GOG / Humble

**itch.io**:独立游戏友好,无审核,15 分钟上架。抽成可选(开发者自己定,可以设 0)。**首发 demo / game jam 用 itch.io 是首选**。

**GOG**(Good Old Games,CD Projekt 子公司):DRM-free 为主。审核比 Steam 严,只接"他们觉得有市场"的游戏。Rust 游戏没问题。

**Humble Bundle**:bundle 销售 + 商店。审核流程类似 GOG。

## 7 · Steam Deck Verified

Steam Deck 是 Valve 的掌机(AMD APU、Linux SteamOS)。Verified 是 Valve 给"在 Deck 上完美运行"的认证:

- **Verified**:无需调整即可玩。**所有 UI 字体在 7" 屏可读、所有操作用手柄可完成、原生分辨率 1280x800 流畅**
- **Playable**:能玩但有警告(比如"需要手动切换键盘")。多数游戏在这里
- **Unsupported**:不能玩(比如需要 VR)
- **Unknown**:Valve 还没测

**Verified 对开发者的影响**:玩家在 Deck 上看 store,Verified 排在前面。Verified 游戏销量在 Deck 用户群比 Playable 高 30-50%。

**让游戏 Verified 的工程要点**:

- **手柄完整支持**。键盘 / 鼠标依赖会被降级
- **UI 字体可读**。7" 1280x800 屏,12px 字看不清,放大到 16px+
- **分辨率支持**。原生 1280x800,不要假设 16:9
- **Linux 兼容**。Deck 跑 SteamOS(Linux)。Rust 跨平台原生支持 Linux,通常没问题
- **性能**。Deck APU ~GT 1030 级别。游戏要在中画质 60 FPS

**Proton**(Valve 的 Wine fork)让 Windows 游戏跑在 Linux。如果你只发 Windows 版,Proton 可以让玩家在 Deck 玩——但性能打折。**直接发 Linux 版本对 Verified 评分更好**。

Rust 游戏天生跨平台,Linux 版本几乎免费获得。**没理由不发 Linux 版本**。

## 8 · 发布 checklist

完整发布前 checklist:

**Steam**
- [ ] Steam Direct 注册完成($100 一次性)
- [ ] app_id 申请
- [ ] Steamworks SDK 集成
- [ ] 商店页面(art、video、description)
- [ ] Coming Soon 页面至少 2 周
- [ ] Achievement / Cloud Save 测试
- [ ] 至少 5 种语言支持
- [ ] Steam Deck Verified 测试

**Epic(可选)**
- [ ] Epic Developer 注册
- [ ] EOS SDK 集成
- [ ] Store page

**主机(可选,需 NDA)**
- [ ] PlayStation Partners 注册
- [ ] ID@Xbox 注册
- [ ] Nintendo Developer Portal 注册
- [ ] devkit 申请
- [ ] 平台 SDK 集成
- [ ] cert 提交(预留 6 个月)
- [ ] ESRB / PEGI / CERO 评级

**iOS / Android(可选)**
- [ ] Apple Developer $99/年
- [ ] Google Play Developer $25 一次
- [ ] 跨平台编译链
- [ ] 应用图标 / 截图
- [ ] 隐私政策 / 服务条款
- [ ] 内购审核

**Web(可选)**
- [ ] Wasm 编译
- [ ] 资源压缩(50MB+ 的 Wasm 用户流失)
- [ ] 自动播放策略处理

**通用**
- [ ] 多语言(至少 EN / 中文 / 西班牙语)
- [ ] 无障碍基础(参考 `accessibility-short.md`)
- [ ] 隐私政策 + 服务条款
- [ ] 客服邮箱 / Discord
- [ ] 退款机制(平台提供,自己也要知道)
- [ ] 媒体 / 主播 copy
- [ ] Day-1 patch 计划

发布是项目最复杂的部分,工程只是 1/3。市场、运营、客服各占 1/3。**Rust 程序员倾向低估发布复杂度**。预留 3-6 个月做发布准备,不要拖到代码"完成"才开始。

## 9 · 延伸

- Steamworks 文档:https://partner.steamgames.com/doc/
- Epic Online Services:https://dev.epicgames.com/docs/
- PlayStation Partners:https://register.playstation.net/
- ID@Xbox:https://www.xbox.com/en-us/Developers/id
- Nintendo Developer Portal:https://developer.nintendo.com/
- Apple Developer:https://developer.apple.com/
- Google Play Console:https://play.google.com/console/
- itch.io 上传指南:https://itch.io/developers
- GOG 开发者:https://devportal.gog.com/
- Steam Deck Verified:https://partner.steamgames.com/doc/store/frontend/steam_deck
- ProtonDB(看你的游戏在 Linux 兼容性):https://www.protondb.com/
- Rust + Android 教程:https://mozilla.github.io/firefox-browser-architecture/experiments/2017-09-21-rust-on-android.html
- Rust + iOS 教程:https://github.com/shepmaster/rust-ios-facebook
- Wasm 游戏参考:https://rustwasm.github.io/

**发布策略总结**:Steam 是 PC 主战场,Day-1 上 Steam + Deck Verified。主机是 reach 扩展,需要 6 个月 buffer。iOS / Android 看 game genre(休闲 / 三消向合适,硬核向不合适)。Web 是 demo / 试玩好渠道,完整游戏性能 / 大小挑战大。

发布完成不是终点,是起点。**游戏发布后第 1 个月决定销量 80%**——预埋 patch / 社区运营 / 客服流程,这些比发布本身更影响长期成功。
