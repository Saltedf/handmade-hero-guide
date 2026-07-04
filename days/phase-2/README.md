
# Phase 2 · 2D 游戏:从画一个方块到一个小世界

> 在 Phase 1 你搭好了"舞台"——能开窗口、能显示像素、能读输入。Phase 2 是真正"做游戏"的开始:你要让一个方块能跑能跳能撞墙能打架能发声。这 45 天是 Casey 把工程骨架变成"游戏感"的关键阶段。

## 这一阶段在做什么

Phase 1 的最后一天,你的程序能做这些事:打开一个 1280×720 的窗口,把一个 `Vec<u32>` 里的像素 push 到屏幕上,读键盘 WASD,播放一段正弦波。但你**还没有游戏**,你只有一个能显示像素的画框。

Phase 2 的核心问题是:**怎么把"一个像素画框"变成"一个游戏"?**

这个问题拆开看有四个独立的子问题,Casey 一个一个解决:

**子问题 1:游戏代码和平台代码怎么分?**(Day 26-30)
你前面写的所有东西都堆在 `main.rs` 里。但游戏代码(规则、物理、AI)和平台代码(开窗、显示、读输入)必须分开——否则你以后想换个平台(从桌面到 Web 到手机)就要重写整个游戏。Casey 用函数指针 + cdylib 实现这个分离,Rust 端要解决所有权、生命周期、热重载。

**子问题 2:游戏对象怎么表达?**(Day 30-40)
你的小人、怪物、子弹、地面方块……这些东西怎么在代码里表达?最朴素的想法是每个对象一个 struct,但很快你会撞到"互相引用"和"内存增长"的问题。Casey 演化出一套"稀疏数组 + 索引"的方案,这是后面 600 集所有实体系统的雏形。

**子问题 3:时间和运动怎么算?**(Day 41-50)
小人在屏幕上"移动"的本质是什么?给定每帧的输入,怎么算下一帧的位置?这涉及向量数学、运动方程、积分方法、碰撞检测。Casey 在这一阶段把游戏数学的核心全讲完了。

**子问题 4:资产怎么加载和管理?**(Day 50-70)
你的小人需要一张图(精灵),声音需要 WAV 文件,地图需要 bitmap。怎么从磁盘读到内存,怎么缓存,怎么在合适的时机释放?这是游戏工程化的最后一块拼图。

完成 Phase 2 后,你会有一个**真正能玩的小游戏**:小人在 2D 地图上跑跳、撞墙反弹、攻击怪物、有血量、有得分。虽然简陋,但**架构完整**——后面 600 集都是在它基础上加深加复杂,而不是推倒重来。

## 学习目标

完成 Phase 2 后,你能:

- [ ] 解释"平台层 / 游戏层"分离的架构,自己设计一个跨平台游戏框架
- [ ] 用 Rust 写出一个完整的 2D 实体系统(基于稀疏数组 + 索引)
- [ ] 实现一个支持热重载的 cdylib 游戏模块(改代码不重启程序)
- [ ] 推导并实现 2D 向量、点积、叉积、Minkowski 差碰撞、反射
- [ ] 解释 Euler 积分的原理和局限,知道什么时候该升级到 Verlet
- [ ] 写一个能加载 BMP / TGA / WAV 的资产管线
- [ ] 实现一个最简单的空间网格(Spatial Hash)加速碰撞检测
- [ ] 用 `gdb` 调试 Rust 程序,用 `valgrind` 检查内存泄漏
- [ ] 给一个真实的 Rust crate(如 `glam` 或 `bevy_ecs`)提一个 PR

## 主题索引(按 4 域分类)

### 🎮 游戏编程

- **day026-029**:游戏/平台分离架构,GameInput / GameMemory 结构
- **day030-035**:第一个实体(小人)、精灵渲染
- **day036-040**:动画、状态机雏形
- **day041**:游戏数学概览([day041.md](day041.md))
- **day042-046**:Vec2 / 速度 / 加速度 / Euler 积分
- **day047-049**:线段相交(攻击范围判定)
- **day050**:Minkowski 差碰撞(里程碑)
- **day051-055**:自定义 hash table(资产管理)
- **day056-060**:内存布局、对齐
- **day061-065**:Sim Region(局部模拟,大世界优化)
- **day066-070**:声音混合、Phase 2 收官

### 🎨 图形学

- **day030-035**:精灵渲染(矩形 blit)
- **day036-040**:透明度(Alpha blending)
- **day042-046**:向量在渲染里的角色
- **day050-055**:AABB 相交算法
- **day060+**:色彩空间初识(sRGB vs Linear)

### 🐧 Linux 系统编程

- **day029**:文件 IO(读 BMP),`open`/`read`/`close` vs mmap
- **day037**:`clock_gettime` vs `gettimeofday`,帧率限制
- **day040+**:cpal 音频回调
- **day055**:动态内存分配(`malloc` / mmap,custom allocator 的动机)
- **day060**:错误码 vs errno,从 C 调用 Linux syscall

### 🦀 Rust 生态

- **day026-029**:cdylib / libloading / 函数指针 + 所有权陷阱
- **day030-035**:Vec<T> 的内存模型,Box<[T]> vs Vec<T>
- **day041-050**:手写 Vec2 + trait 实现 + Copy 语义
- **day050+**:unsafe 边界(FII 调 Casey 的 C 代码)
- **day055**:HashMap vs 手写,SlotMap 代际索引
- **day060**:arena 分配器(bumpalo crate)
- **day070**:rustc 的 inline 提示,profile-guided optimization

## 跨日专题(deep-dives/)

- [deep-dives/platform-game-separation.md](deep-dives/platform-game-separation.md) — 平台/游戏分离的演化:从 Win32 callback 到 Casey 的 GameMemory,再到 Rust cdylib 的所有权设计
- [deep-dives/entity-system.md](deep-dives/entity-system.md) — 实体系统的演化:从朴素 struct 到 ECS,Casey 选了哪条路
- [deep-dives/hot-reload.md](deep-dives/hot-reload.md) — 热重载的完整链路:build 系统 → libloading → 状态保持
- [deep-dives/collision-detection.md](deep-dives/collision-detection.md) — 碰撞检测全家桶:Minkowski → 空间网格 → GJK → BVH
- [deep-dives/asset-pipeline.md](deep-dives/asset-pipeline.md) — 资产管线:文件格式解析、缓存、热重载、压缩
- [deep-dives/math-foundations-for-games.md](deep-dives/math-foundations-for-games.md) — 游戏数学全集:向量、矩阵、积分、几何
- [deep-dives/rust-cdylib-and-ffi.md](deep-dives/rust-cdylib-and-ffi.md) — Rust cdylib + FFI 的所有权、lifetime、unsafe 完整指南

## 阶段项目验收

完成这一阶段后,你的 Rust 项目应该能:

- [ ] 运行后开窗 1280×720,稳定 60 FPS
- [ ] WASD 控制小人在 2D 地图上跑动,Shift 加速跑
- [ ] 小人能撞墙反弹,反弹角度符合物理直觉
- [ ] 鼠标左键攻击,攻击范围内有怪物则扣血
- [ ] 怪物会朝玩家移动(简单 AI)
- [ ] 击杀怪物得分,显示在屏幕一角
- [ ] 按空格播放音效,WAV 从磁盘加载
- [ ] 改游戏代码 → cargo build → 自动热重载,游戏不重启
- [ ] `cargo run --release` 跑 30 分钟不崩溃,内存稳定不增长

## 开源贡献实践(本阶段)

找 1-2 个本阶段主题相关的 Rust crate / Linux 工具,读源码,提一个 PR:

推荐目标(按难度递增):

1. **`glam`**(https://github.com/bitshifter/glam)— 数学库。读 `src/f32/vec2.rs`,看 Vec2 实现;找一个 doc / test / example 不全的 API,补一个
2. **`slotmap`**(https://github.com/orlp/slotmap)— 代际索引容器,和 Casey 的实体系统异曲同工。读源码理解 generation 机制
3. **`bevy_ecs`**(https://github.com/bevyengine/bevy)— 业界最流行的 ECS。读 archetype / storage 部分
4. **`libloading`**(https://github.com/nagisa/rust_libloading)— Rust 热重载基础。读 `src/os/unix/mod.rs` 理解 dlopen 封装
5. **`cpal`**(https://github.com/RustAudio/cpal)— 跨平台音频。读 Linux ALSA 后端

PR 类型建议(从易到难):
- 文档(doc comment 补全 / 错别字 / 公式推导)
- 测试(补 edge case)
- 示例(加一个 runnable example)
- bug(找小 bug 修)
- 重构(只在你能完全理解原代码时做)

## 本阶段用到的 reference/ 资料

主要依据的本地 HH slice:[days/reference/hh-slices/phase-2.json](../reference/hh-slices/phase-2.json)(45 集 lesson 数据)

外部资料(按需 WebFetch):
- The Rust Book ch.4(所有权)+ ch.10(trait / lifetime)+ ch.19(unsafe / FFI)
- 3D Math Primer ch.4(向量)— https://gamemath.com/book/vectors.html
- LearnOpenGL Transformations — https://learnopengl.com/Getting-started/Transformations
- Game Programming Patterns(Service Locator / Component / State)— https://gameprogrammingpatterns.com/
- Casey HH 原版 C 代码 — https://github.com/HandmadeHero/handmade-hero
