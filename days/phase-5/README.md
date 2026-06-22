---
phase: 5
range: day176-260
days: 85
title: "Debug 系统 + OpenGL 迁移:让游戏能调自己,让渲染上 GPU"
estimated: "10-12 周"
prereqs: ["phase-0", "phase-1", "phase-2", "phase-3", "phase-4"]
domains: [game, graphics, linux, rust, debug]
---

# Phase 5 · Debug 系统 + OpenGL 迁移

> 前 175 集,Casey 一直在用 `printf` 和断点调游戏——能调,但每次想知道"这一帧哪个函数最慢"都要重新编译加计时。Phase 5 的前 60 集他把这件事彻底解决:游戏内置 profiler / debug UI / introspection,按 F4 就能看火焰图、编辑变量、查任何字段的当前值。后 25 集是另一个分水岭——Day 235 起 Casey 终于切到 OpenGL,把渲染从 CPU 搬到 GPU。

## 这一阶段在做什么

Phase 4 结束时,你的游戏已经能 144 FPS 稳定跑,内存受控,资产压缩。但你**调任何参数仍然要重新编译重启游戏**。Casey 在 Day 176 直面这个问题:他要给游戏装一套"自省镜",让游戏边跑边报告自己的内部状态。

Phase 5 拆成两大子任务:

**子任务 A:Debug 系统(Day 176-234,约 60 集)**

把"调试"从被动工具(gdb / printf)升级为**主动游戏功能**:
- 自动性能计数器(进入函数记 cycle,退出记 cycle,差值 = 耗时)
- 跨线程安全的 profiler(用原子操作)
- 时间维度历史(ring buffer 存最近 N 帧)
- 在游戏内画图表、火焰图、树视图
- immediate-mode UI(每帧重新声明,自动同步)
- introspection(运行时枚举结构体字段,显示/编辑)
- 鼠标点击实体 → 在 debug UI 看它的所有字段

**子任务 B:OpenGL 迁移(Day 235-260,约 25 集)**

把渲染管线从 CPU(我们手写的软光栅化器)搬到 GPU(OpenGL 4.x)。Casey 在 Windows 上用 wglCreateContext,Rust 学习者用 `glutin` + `glow`:
- OpenGL context 创建(Pixel Format / ARB 扩展)
- GLSL shader 编译链接(Vertex + Fragment)
- 顶点缓冲 + 索引缓冲(VBO / EBO)
- 异步纹理下载(`glFenceSync`)
- VSync + sRGB 色彩管理

完成 Phase 5 后,你会有一个**自带调试器的游戏**:F4 打开 profiler,看到每帧每个函数的 cycle 数;点任何怪物,UI 显示它的速度、血量、状态;按 F5 重编译代码热重载,游戏世界状态不丢。

## 学习目标

完成 Phase 5 后,你能:

- [ ] 实现一个零侵入的 cycle-level profiler(RAII guard + `rdtsc` / `clock_gettime`)
- [ ] 用原子操作写跨线程安全的计数器,解释 `Ordering::Relaxed` 为什么够
- [ ] 实现 immediate-mode UI(每帧重建,基于 ID 哈希保留状态)
- [ ] 设计 introspection 系统,运行时枚举结构体字段并显示
- [ ] 在 Rust 里用 `glutin` + `glow` 创建 OpenGL 4.x context
- [ ] 写 GLSL shader,编译链接,绑定 VAO/VBO
- [ ] 用 `glFenceSync` 做异步纹理下载
- [ ] 解释 immediate-mode vs retained-mode UI 的取舍
- [ ] 给 `puffin` / `egui` / `glam` 等真实 crate 提一个 PR

## 主题索引(按 4 域分类)

### 🎮 游戏编程

- **day176-180**:debug 基础设施,自动性能计数器,ring buffer 历史
- **day181-190**:debug 事件录制,调试 UI 框架雏形
- **day191-200**:环形菜单、自重编译、debug 树视图、immediate-mode UI
- **day201-210**:debug UI 集成,鼠标拾取实体,introspection 起步
- **day211-234**:debug 收尾、过场动画、排序键、radix sort O(n)
- **day235-260**:OpenGL context、shader、纹理下载、VSync

### 🎨 图形学

- **day235**:OpenGL context 创建(Pixel Format)
- **day236**:GPU 概念概览(顶点 / 片段 / 光栅化)
- **day237-239**:用 OpenGL 显示图像 / 渲染游戏
- **day241-244**:OpenGL 升级,异步纹理下载
- **day256**:gamma 校正,frame buffer 的 sRGB 处理

### 🐧 Linux 系统编程

- **day177**:`rdtsc` vs `clock_gettime(CLOCK_MONOTONIC)`,为什么用 cycle
- **day178**:`pthread_self` vs `gettid`,线程 ID 获取
- **day192**:inotify + libloading 做文件监视触发热重载
- **day235**:glX vs wgl vs EGL,Wayland 下的 OpenGL
- **day243-244**:`glFenceSync` 在 Linux Mesa 上的行为

### 🦀 Rust 生态

- **day177**:RAII Drop guard 实现 timer(不用宏)
- **day178**:`AtomicU64` + `Ordering::Relaxed`
- **day196**:`imgui` / `egui` / `iced` immediate vs retained
- **day206**:introspection(手写 trait,讨论 `bevy_reflect`)
- **day235**:`glutin` / `glow` / `wgpu` 三选一
- **day243**:异步纹理下载的 Rust async 模型

## 跨日专题(deep-dives/)

(本阶段 deep-dives 可在阶段后期补充)

## 阶段项目验收

完成这一阶段后,你的 Rust 项目应该能:

- [ ] 按 F4 打开 in-game profiler,看到每个函数的 cycle 计数和耗时
- [ ] profiler 显示最近 300 帧的帧时间曲线图
- [ ] profiler 支持下钻,点开 `update` 看到 `update_player` / `update_monsters` / `update_audio`
- [ ] 鼠标点屏幕上任何怪物,debug UI 显示它的所有字段(位置、速度、血量)
- [ ] F5 触发热重载,改 Rust 游戏代码后游戏世界状态保留
- [ ] 切换到 OpenGL 渲染后端,画面与软渲染一致(像素级)
- [ ] OpenGL VSync 开启,稳定 60 FPS,无 tearing
- [ ] sRGB 色彩正确(纹理颜色与软渲染一致)
- [ ] 异步纹理下载,加载大纹理不卡帧

## 开源贡献实践(本阶段)

推荐目标(按难度递增):

1. **`puffin`**(https://github.com/EmbarkStudios/puffin)— Rust 生态最好的 profiler,和 Casey 的设计很像。读 `src/data.rs` 理解 frame data
2. **`egui`**(https://github.com/emilk/egui)— immediate-mode UI 库。读 `src/ui.rs` 看 immediate-mode 实现
3. **`glow`**(https://github.com/grovesNL/glow)— OpenGL 包装,跨平台。读 `src/native.rs`
4. **`glutin`**(https://github.com/rust-windowing/glutin)— OpenGL context 创建。读 `src/api/glx/mod.rs`(Linux)
5. **`bevy_reflect`**(https://github.com/bevyengine/bevy)— Rust introspection 库。读 `crates/bevy_reflect`

PR 类型建议:doc 补全、edge case test、example、小 bug fix。

## 本阶段用到的 reference/ 资料

主要依据的本地 HH slice:[days/reference/hh-slices/phase-5.json](../reference/hh-slices/phase-5.json)(85 集 lesson 数据)

外部资料(按需 WebFetch):
- Dear ImGui FAQ — https://github.com/ocornut/imgui/blob/master/docs/FAQ.md
- LearnOpenGL Hello Triangle — https://learnopengl.com/Getting-started/Hello-Triangle
- The Rust Book ch.16 Fearless Concurrency — https://doc.rust-lang.org/book/ch16-00-concurrency.html
- Brendan Gregg perf examples — https://www.brendangregg.com/perf.html
- Casey HH 原版 C 代码 — https://github.com/HandmadeHero/handmade-hero
