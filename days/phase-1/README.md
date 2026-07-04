
# Phase 1 · 平台层:从空白 exe 到热重载的舞台

> Handmade Hero 的前 25 天是整个项目的"地基"。Casey 手把手演示如何用纯 Win32 API 创建窗口、分配后缓冲、播声音、读输入,最后把这些封装成一个可重用的"平台层"。这一阶段看似简单,但它示范了一个极其重要的架构原则——**游戏代码与平台代码彻底分离**,游戏逻辑只通过 Casey 自己设计的几个函数指针与平台通信。这是后续 600 多集健康演化的关键。

## 这一阶段在做什么

Phase 1 的核心目标:**搭一个"舞台"**——能开窗、能显示像素、能读输入、能播音频、能热重载。这是后面所有"演剧"(游戏逻辑)的基础。

你想象要演一部大戏。你不能直接演,你得先:

- **盖剧院**(开窗)
- **铺舞台**(后缓冲 + 显示)
- **接通电源**(主循环 + 时间)
- **装麦克风**(音频)
- **装监控**(输入)
- **搭后台**(平台 / 游戏分离)
- **加翻新机制**(热重载)

这 25 天就是盖剧院。剧院盖好,后面 642 天演剧——你只管剧的内容(游戏逻辑),不再操心剧院。

### 四个子问题

Phase 1 的工作可以拆成四个独立的子问题:

**子问题 1:怎么和 OS 打交道?**(Day 1-10)

- 配 build 系统(我们用 cargo,Casey 用 build.bat)
- 在屏幕上开窗口(Win32 → winit)
- 分配一块内存当"后缓冲",画完后 swap 到屏幕
- 处理键盘 / 手柄输入
- 初始化音频设备
- 用高精度计时器测帧时间

这 10 天的产出:**一个能开窗、显示像素、读键盘、播音的 demo**。但代码全堆在 main 里,平台和游戏逻辑混在一起。

**子问题 2:平台 / 游戏怎么分?**(Day 11-14)

这是 HH 全剧最重要的架构决策。Casey 把代码拆成两层:

- **平台层**(platform layer):开窗、显示、读输入、播音频。和 OS / 硬件打交道。
- **游戏层**(game layer):游戏规则、物理、AI、渲染。**完全不知道**自己在 Windows 还是 Linux。

两层之间通过 Casey 设计的几个函数通信:

- `update_and_render(memory, input, dt) → sound_buffer`——游戏主循环
- `game_memory`——状态容器,平台层分配,游戏使用
- `game_input`——输入快照,平台层每帧填充

这种分离让游戏代码**可移植**(换个平台层,游戏代码不变),**可测试**(状态外置,可注入),**可热重载**(状态在平台层,代码可换)。

**子问题 3:输入 / 音频 / 时间怎么 polished?**(Day 15-20)

- 统一输入(键盘 + 手柄 → controller 数组)
- 帧率锁定(sleep + spin 混合)
- 音频同步(cursor 算法)
- 调试方法论

这 6 天的产出:**一个工业级的平台层**——稳定、低延迟、可调试。

**子问题 4:热重载** (Day 21-23)

这是 Phase 1 的"杀手锏"。游戏代码编成 cdylib,平台层用 libloading 加载。改代码后:

1. cargo-watch 检测文件变化
2. 自动 cargo build
3. 平台层检测 .so mtime 变化
4. libloading reload
5. **下一帧用新代码,游戏状态完整保留**

整个循环 1-3 秒,你完全不切终端。这种迭代速度让 Casey 两年开发 667 集成为可能。

### Phase 1 的产出

完成 Phase 1 后,你有:

- ✅ 一个完整的跨平台平台层(Linux / Windows / macOS)
- ✅ 能开窗、显示、读输入、播音频
- ✅ 热重载工作流(改代码 → 1-3 秒看到效果)
- ✅ 状态外置的 GameMemory 设计
- ✅ 平台 / 游戏分离的清晰边界
- ✅ Rust + winit + softbuffer + cpal + gilrs + libloading 的工具链

里程碑:程序开窗,显示一个彩色方块,按键控制方块,有声音,改游戏代码不重启就生效。

## 学习目标

完成 Phase 1 后,你能:

- [ ] 解释"平台层 / 游戏层"分离的架构,自己设计一个跨平台游戏框架
- [ ] 在 Rust + winit 里开窗口、用 softbuffer 显示后缓冲
- [ ] 用 cpal 播放正弦波 / 方波 / WAV 文件
- [ ] 用 winit + gilrs 统一键盘和手柄输入
- [ ] 实现精确帧率锁定(sleep + spin 混合)
- [ ] 实现 GameMemory 结构(permanent + transient)
- [ ] 实现 cdylib + libloading 的热重载
- [ ] 用 cargo-watch 自动 build,实现 sub-3-second dev loop
- [ ] 解释 Win32 / winit / Linux(winit)的对应关系
- [ ] 用 gdb / valgrind / perf / rr 调试 Rust 程序
- [ ] 给一个 Rust crate(winit / cpal / libloading / softbuffer 等)提一个 PR

## 主题索引(按 4 域分类)

### 🎮 游戏编程

- **day001-005**:build 系统、窗口、后缓冲、动画
- **day006**:首次输入(键盘 + 手柄)
- **day007-009**:DirectSound 初始化、方波、变调正弦波
- **day010**:QueryPerformanceCounter / Instant
- **day011**:🔥 平台 / 游戏分离(全剧最重要架构决策)
- **day012-013**:平台无关音频 / 输入
- **day014**:GameMemory(状态外置,热重载基础)
- **day015**:混音器(多声源叠加)
- **day016**:粒子系统(对象池 + AoS)
- **day017**:统一键盘 + 手柄(适配器模式)
- **day018**:帧率锁定(sleep + spin)
- **day019-020**:音频同步 + 调试方法论
- **day021-023**:🔥 热重载(cdylib + libloading + cargo-watch)
- **day024**:重构(代码清理)
- **day025**:🎉 Phase 1 收官

### 🎨 图形学

- **day003-004**:双缓冲、row-major 内存布局
- **day005**:图形 API 选型(为什么用软渲染而非 OpenGL)
- **day016**:粒子渲染(像素直接画)
- **day024**:代码 polish

### 🐧 Linux 系统编程

- **day002**:Wayland / X11 / WindowProc 概念
- **day003**:mmap / Box<[u8]> vs VirtualAlloc
- **day007-008**:ALSA / PipeWire / DirectSound 对应
- **day010**:clock_gettime / Instant vs QPC
- **day011**:平台抽象的 Linux 投影
- **day014**:mmap / brk / 进程地址空间
- **day017**:evdev / libinput / XInput 对应
- **day019-020**:调试工具(gdb / valgrind / perf / rr)
- **day021**:dlopen / dlsym / ELF 符号表
- **day023**:inotify / 文件监听 / debounce

### 🦀 Rust 生态

- **day001**:cargo / workspace / build.rs
- **day002-003**:winit / softbuffer / Box<[u8]>
- **day006**:HashSet / winit KeyCode
- **day007-009**:cpal / Arc<Mutex>
- **day011**:trait / 所有权 / 跨边界设计
- **day012-013**:Result / Option / error handling
- **day014**:Arena / Cell / unsafe / 裸指针
- **day015**:Arc<Mutex> / 回调线程 / Mix
- **day016**:Copy / Vec / 对象池 / DOD
- **day017**:bitflags / edge vs level
- **day018**:Instant / Duration / spin_loop
- **day019-020**:tracing / dbg! / cargo test / cargo bench
- **day021**:🔥 cdylib / libloading / Symbol / Box::leak
- **day022-023**:AtomicBool / signal-hook / cargo-watch
- **day024**:rustfmt / clippy / rust-analyzer 重构
- **day025**:profile / cargo audit / 整体测试

## 跨日专题(deep-dives/)

- [deep-dives/platform-game-separation.md](deep-dives/platform-game-separation.md) — 为什么 / 怎么分离平台和游戏代码;从 naive `main.rs` 到 cdylib 热重载架构的演化
- [deep-dives/win32-to-winit.md](deep-dives/win32-to-winit.md) — 常见 Win32 API 到 winit 等价物的映射;winit 抽象了什么,没抽象什么
- [deep-dives/hot-reload-rust.md](deep-dives/hot-reload-rust.md) — Rust 完整热重载:cdylib + libloading + cargo-watch + 状态保留

## 阶段项目验收

完成 Phase 1 后,你的 Rust 项目应该能:

- [ ] 运行后开窗 1280×720,稳定 60 FPS
- [ ] 窗口里显示动态画面(彩色方块移动 / 闪烁)
- [ ] 键盘 WASD / 方向键控制方块移动
- [ ] 手柄也能控制(可选)
- [ ] 按空格触发"动作"(变色 / 跳跃 / 发声)
- [ ] 能听到声音(方波 / 正弦波 / WAV)
- [ ] 改一行游戏代码 → cargo build → 1-3 秒内游戏反映新代码(热重载)
- [ ] 关窗口正常退出(不 crash)
- [ ] `cargo run --release` 跑 5 分钟,内存稳定不增长
- [ ] `cargo test` / `cargo clippy` / `cargo fmt --check` 都 clean

10/10 通过 = Phase 1 毕业,进入 Phase 2。

## 开源贡献实践(本阶段)

找 1-2 个本阶段主题相关的 Rust crate / Linux 工具,读源码,提一个 PR:

推荐目标(按难度递增):

1. **`softbuffer`**(https://github.com/rust-windowing/softbuffer)— 显示后缓冲的薄层。读 `src/`,看 Linux wl_shm 后端
2. **`cpal`**(https://github.com/RustAudio/cpal)— 跨平台音频。读 `src/host/alsa/` 看 Linux 后端
3. **`gilrs`**(https://gitlab.com/gilrs-project/gilrs)— 游戏手柄。读 evdev 集成
4. **`libloading`**(https://github.com/nagisa/rust_libloading)— Rust 热重载基础。读 `src/os/unix/` 看 dlopen 封装
5. **`winit`**(https://github.com/rust-windowing/winit)— 跨平台窗口。读 `src/platform_impl/linux/`

PR 类型建议(从易到难):

- 文档(doc comment 补全 / 错别字 / 公式推导)
- 测试(补 edge case)
- 示例(加一个 runnable example)
- bug(找小 bug 修)
- 重构(只在你能完全理解原代码时做)

## Phase 1 完成自检

- [ ] 能用 vim 改 Cargo.toml 不紧张
- [ ] 装好 Rust 工具链(rustup / rustfmt / clippy / rust-analyzer / cargo-watch)
- [ ] cargo new → cargo run 流程跑通
- [ ] 解释 ownership / borrow / lifetime 三个核心概念
- [ ] 写出 Box / Vec / Arc / Mutex 何时用
- [ ] 看懂 Rust 编译器错误,知道 E0xxx 错误码
- [ ] 用 winit 写出 hello window
- [ ] 用 softbuffer 显示一个像素
- [ ] 用 cpal 播放 1 秒正弦波
- [ ] 用 gilrs 读手柄状态
- [ ] 解释 cdylib / no_mangle / extern "C"
- [ ] 实现 cdylib 热重载 demo
- [ ] 用 gdb / valgrind 调试 Rust 程序
- [ ] 给一个 Rust crate 提了 PR(可选,但推荐)

如果 80%+ 你能勾上,Phase 1 扎实。如果 < 50%,回顾相关 day。

## 本阶段用到的 reference/ 资料

主要依据的本地 HH slice:[days/reference/hh-slices/phase-1.json](../reference/hh-slices/phase-1.json)(25 集 lesson 数据)

外部资料(按需 WebFetch):

- The Rust Book:https://doc.rust-lang.org/book/
- winit 文档:https://docs.rs/winit/
- softbuffer 文档:https://docs.rs/softbuffer/
- cpal 文档:https://docs.rs/cpal/
- libloading 文档:https://docs.rs/libloading/
- Arch Wiki Wayland:https://wiki.archlinux.org/title/Wayland
- Arch Wiki PipeWire:https://wiki.archlinux.org/title/PipeWire
- Casey HH 原版 C 代码:https://github.com/HandmadeHero/handmade-hero

## 进入 Phase 2

完成 Phase 1 后,进入 Phase 2([phase-2/README.md](../phase-2/README.md))。

Phase 2(Day 26-70,45 天)的主题是**真正做游戏**:

- 实体系统(稀疏数组 + 索引)
- 运动 / 物理(向量、Euler 积分、碰撞)
- 资产管线(BMP / WAV 加载)
- 空间优化(空间网格、Sim Region)
- 多人本地

里程碑:WASD 控制小人在 2D 地图跑跳,撞墙反弹,攻击怪物,有得分。

样本天文件:[day041.md](../phase-2/day041.md)(游戏数学类型概览)。

---

**Phase 1 教学方法回顾**:

- **手把手**:每个新术语第一次出现必解释,每行 Rust 代码有注释,每条 shell 命令有参数 + 输出
- **零跳步**:没有"显然 / 简单 / 易得",所有概念从头讲
- **自包含**:不需要翻外部资料,所有核心内容在 day 文件里
- **HH 为脉络**:Casey 在 Win32 做什么,我们在 Linux + Rust 做什么
- **4 域并重**:游戏编程、图形学、Linux 系统编程、Rust 生态
