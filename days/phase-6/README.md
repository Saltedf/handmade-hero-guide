---
phase: 6
range: day261-435
days: 175
title: "Phase 6 · 深度缓冲 / 光照 / 压缩"
estimated: "5-6 个月"
prereqs: ["phase-0", "phase-1", "phase-2", "phase-3", "phase-4", "phase-5"]
domains: [game, graphics, math, linux, rust]
---

# Phase 6 · 深度缓冲 / 光照 / 压缩(Day 261-435)

> 这是 HH 全剧最长也最深的阶段——175 天,几乎等于前面 5 个阶段总和。Casey 把 profiler / debug UI 工具化推到极致,然后开始把游戏的渲染从"贴 sprite"扩展到真正的 3D:深度缓冲、Phong 光照、shadow、深度剥离、多网格光照传播、SIMD raycast。光照相关就占了 60 多集。

## 这一阶段在做什么

Phase 5 末尾你的游戏已经切到 OpenGL,GPU 接管渲染。Phase 6 是从"能用 GPU 画图"到"做出商业品质画面"的飞跃。

Phase 6 的核心问题分四块:

**子问题 1:Profiler 工具化(Day 261-270)**。Phase 5 末尾 profiler 是"能看",Phase 6 把它升级为"能用":柱状图、Top Clocks、frame slider、UI 控件库、布局系统、clip rect、debug links、helper 函数。这是从"内部工具"到"专业开发工具"的工程化。

**子问题 2:角色 + 移动系统(Day 270-285)**。Casey 把游戏从"自由 2D"改成"瓦片 + 混合"移动:traversable point 概念、spring 动画、状态机、2.5D Z 轴、standing_on 关系、事务性占据。这部分是游戏机制的核心,后面所有玩法都基于它。

**子问题 3:大世界架构(Day 277-280)**。从"单 Vec<Entity>"演化到"稀疏实体系统 → chunk-based storage → 流式加载"。这是从"小 demo"到"商业游戏"的关键架构演进。

**子问题 4:深度缓冲 + 光照(Day 290+)**。Casey 进入"图形学深水区":z-buffer 算法、Phong 光照、Blinn-Phong、法线变换、shadow map、深度剥离、PBR 入门、纹理压缩、SIMD raycast。这是 Phase 6 时间最长的部分(约 100 天),也是 HH 最深的图形学内容。

完成 Phase 6 后,你会有:

- 一个**工业级 profiler**(柱状图 / 火焰图 / Top Clocks / frame scrubbing)
- 一个**2.5D 动作游戏**(混合移动 + Z 轴 + spring 动画 + chunked world)
- 一个**带光照的 3D 渲染管线**(Phong + shadow + 法线贴图)

## 学习目标

完成 Phase 6 后,你能:

- [ ] 实现一个完整的 immediate-mode UI 框架(按钮 / 滑块 / 列表 / clip / 布局)
- [ ] 用 spring 物理驱动动画,知道 stiffness / damping 怎么调
- [ ] 解释 sparse entity system 和 generational index,实现一个简易 ECS
- [ ] 设计 chunk-based streaming world,支持无限大世界
- [ ] 实现事务性占据(两阶段提交),处理多 entity 冲突
- [ ] 实现 z-buffer 算法,知道为什么需要深度缓冲
- [ ] 推导 Phong / Blinn-Phong 光照方程,理解 ambient / diffuse / specular
- [ ] 实现法线贴图,知道 TBN 矩阵的作用
- [ ] 解释 shadow map 原理,实现基本阴影
- [ ] 用 SIMD 加速 ray-AABB 相交测试
- [ ] 给真实开源 crate(bevy_ecs / glam / bevy_pbr)提 PR

## 主题索引(按 4 域分类)

### 🎮 游戏编程

- **day261-269**:Profiler UI 工具化(环形数组 / 柱状图 / frame slider / 按钮 / 布局 / clip / debug links)
- **day270-275**:Traversable + 混合移动 + 状态机 + spring 动画 + 旋转剪切
- **day276-280**:身体动画调参 + 稀疏实体系统 + chunk-based world + 流式模拟重构
- **day281-285**:相机动画 + Z 轴 + standing_on + 头身重组 + 事务性占据
- **day290+**:深度缓冲、3D 几何、Phong 光照(主题深化)
- **day350+**:shadow mapping、深度剥离、SIMD raycast

### 🎨 图形学

- **day262-267**:UI 渲染(柱状图 / Top Clocks / clip rect)
- **day273-276**:动画系统(sprite 切换 / 程序化运动 / spring / squash and stretch)
- **day275**:2D 仿射变换(旋转 / 缩放 / 剪切,矩阵 + 反向映射)
- **day281-282**:相机系统 + 2.5D
- **day290+**:深度缓冲、3D 渲染管线、MVP 矩阵
- **day310+**:Phong / Blinn-Phong 光照模型
- **day330+**:法线贴图 / TBN 矩阵
- **day350+**:shadow map / 深度剥离
- **day400+**:PBR 入门(Cook-Torrance BRDF)

### 🐧 Linux 系统编程

- **day261**:环形数组 vs `perf` ring buffer(零拷贝)
- **day265**:Layout 系统 vs i3 / GTK 布局
- **day267**:clip rect vs X11 clip mask
- **day270**:离散空间 vs X11 desktop grid
- **day278-280**:chunk streaming vs Linux page cache / mmap
- **day283**:standing_on 关系 vs Linux mount / device tree
- **day285**:事务性占据 vs Linux journal / PostgreSQL ACID

### 🦀 Rust 生态

- **day261**:const generics(`Box<[T; N]>`),`std::array::from_fn`
- **day263-268**:immediate-mode UI / Option<T> 状态 / enum link target
- **day270**:`#[derive(Eq, Hash)]` + HashMap key
- **day274**:Spring struct(Copy + 16 字节)+ 半隐式 Euler
- **day275**:`Mat2` + 矩阵 inverse + 反向映射渲染
- **day277**:generational index(手写 + slotmap)
- **day278-280**:HashMap / BTreeMap + 两阶段跨 chunk 移动 + 测试驱动重构
- **day284**:组合优于继承,Rust 无继承的哲学
- **day285**:Result / Option 表达事务失败,HashSet / HashMap 检测冲突
- **day290+**:OpenGL binding(`glow` / `wgpu`),shader 编译

## 跨日专题(deep-dives/)

(本阶段预留的深度文章,后续填充)

- [deep-dives/profiler-architecture.md](deep-dives/profiler-architecture.md) — 工业级 profiler 的架构:Chrome tracing / Unreal Insights / RenderDoc 的对比
- [deep-dives/spring-physics.md](deep-dives/spring-physics.md) — Spring 物理 + 数值积分方法(Euler / Verlet / RK4)的对比
- [deep-dives/entity-system-evolution.md](deep-dives/entity-system-evolution.md) — 实体系统演化:从 OOP 到 ECS 到 archetype-based
- [deep-dives/chunk-streaming.md](deep-dives/chunk-streaming.md) — Chunk streaming 的工程实现:Minecraft / Skyrim / Zelda BOTW 的策略对比
- [deep-dives/depth-buffer.md](deep-dives/depth-buffer.md) — 深度缓冲全家桶:z-buffer / w-buffer / floating-point depth / reverse-Z
- [deep-dives/lighting-models.md](deep-dives/lighting-models.md) — 光照模型演化:Lambert / Phong / Blinn-Phong / PBR
- [deep-dives/shadow-mapping.md](deep-dives/shadow-mapping.md) — Shadow map 全家桶:basic / PCF / VSM / CSM
- [deep-dives/simd-raycast.md](deep-dives/simd-raycast.md) — SIMD raycast 完整实现:`__m128` 8-wide slab test

## 阶段项目验收

完成这一阶段后,你的 Rust 项目应该能:

### Profiler 工具

- [ ] 开 debug overlay,F1 toggle
- [ ] 60 帧历史柱状图(颜色按耗时编码)
- [ ] Top Clocks 视图(累计耗时 Top 10)
- [ ] Frame slider scrubbing(拖动看任意历史帧)
- [ ] 实时调参(stiffness / damping 等可调)
- [ ] profiler 自己 0 allocation(环形数组)

### 角色系统

- [ ] WASD 控制角色,目标 tile 离散,过渡平滑(spring)
- [ ] 角色有头 + 身体两部分,头部独立旋转(朝向鼠标)
- [ ] 走路 / idle / 撞墙状态切换
- [ ] 撞墙时身体 squash + spring 回弹
- [ ] Z 轴跳跃 + 阴影 + 落地检测
- [ ] 可以站在移动平台上跟随

### 大世界

- [ ] chunk-based world,16x16 / 32x32 tile per chunk
- [ ] 玩家移动时 chunk 按需加载 / 卸载
- [ ] entity 跨 chunk 自动迁移
- [ ] 内存占用只与"加载 chunk 数"成正比

### 多 entity

- [ ] 至少 10 个 entity(玩家 + NPC + 怪物)
- [ ] 怪物 AI 追玩家(简单 A*)
- [ ] 事务性占据,不会"两 entity 卡同一格"

### 图形(Day 290+ 阶段)

- [ ] 3D 几何渲染带深度缓冲
- [ ] Phong 光照(ambient + diffuse + specular)
- [ ] 法线贴图细节
- [ ] 基本 shadow map

### 工程

- [ ] profiler 自己被 profiler(元套娃)
- [ ] cargo test 覆盖核心系统(entity / chunk / spring)
- [ ] cargo bench 测关键路径
- [ ] `cargo run --release` 跑 30 分钟稳定,内存不增长

## 开源贡献实践(本阶段)

找 1-2 个本阶段主题相关的 Rust crate / Linux 工具,读源码,提一个 PR:

推荐目标(按难度递增):

1. **`heapless`**(https://github.com/japaric/heapless)— 嵌入式无堆数据结构,有 ring buffer / sparse storage。读 `spsc::Queue` 理解 day261 的环形数组工业版
2. **`slotmap`**(https://github.com/orlp/slotmap)— generational index 容器,和 day277 的实体系统异曲同工
3. **`keyframe`**(https://github.com/HannesMann/keyframe)— 动画 + 缓动,和 day274 的 spring 互补
4. **`taffy`**(https://github.com/DioxusLabs/taffy)— flexbox / grid 引擎,和 day265 的布局系统同构
5. **`bevy_ecs_tilemap`**(https://github.com/StarArawn/bevy_ecs_tilemap)— chunk-based tilemap,和 day278-280 同构
6. **`bevy_pbr`**(https://github.com/bevyengine/bevy)— PBR 渲染,day400+ 的内容
7. **`glam`**(https://github.com/bitshifter/glam)— 数学库,day275 / 290+ 用到

PR 类型建议(从易到难):

- 文档(doc comment 补全 / 错别字 / 公式推导)
- 测试(补 edge case)
- 示例(加一个 runnable example)
- bug(找小 bug 修)
- 重构(只在你能完全理解原代码时做)

## 阶段节奏建议

Phase 6 是 HH 最长阶段(175 天)。建议节奏:

### 第一段(Day 261-285,本批教程):Profiler + 角色系统

约 25 天,内容密集但相对独立。每 1-2 天 1 集,1.5 个月完成。

### 第二段(Day 286-340):深度缓冲 + 光照基础

约 55 天。每集涉及大量数学(矩阵 / 光照方程),建议每 2-3 天 1 集,留时间消化。完成这段你能渲染带光照的 3D 立方体。

### 第三段(Day 341-400):高级光照 + Shadow + 法线贴图

约 60 天。每集难度高,建议每 3-4 天 1 集,大量手推公式。完成这段你做出商业感的 3D 场景。

### 第四段(Day 401-435):PBR + SIMD + 收官

约 35 天。PBR 是图形学最深部分,慢慢啃。完成这段你毕业了"图形学入门"。

## 心理准备

Phase 6 是 HH 最艰难的阶段:

- **数学密集**:矩阵 / 微分方程 / 概率论 / 几何,要回头查 phase-0 数学基础
- **概念密集**:z-buffer / Phong / shadow map / PBR,每个都是图形学的硬骨头
- **代码量大**:175 天累计代码可能 5 万行
- **节奏慢**:Casey 经常一集集调试同一个 bug,这是真实工程

建议:

- 遇到难集**暂停**,手推公式直到理解
- 用 `cargo doc` + clippy 帮自己保持代码质量
- 每 30 天做一次"回顾周",不学新内容,复习 + 整理笔记
- 在 GitHub 公开你的进度,接受社区反馈

完成 Phase 6,你就跨过了"初学者 → 进阶者"的鸿沟。后面 Phase 7 / Phase 8 是收官,相对轻松。

## 本阶段用到的 reference/ 资料

主要依据的本地 HH slice:[days/reference/hh-slices/phase-6.json](../reference/hh-slices/phase-6.json)(175 集 lesson 数据)

外部资料(按需 WebFetch):

- LearnOpenGL Lighting 章节:https://learnopengl.com/Lighting/Colors
- PBR Book(在线版):https://pbr-book.org/
- Real-Time Rendering(附录在线):http://www.realtimerendering.com/
- 3D Math Primer:https://gamemath.com/
- Disney Animation 12 Principles:https://en.wikipedia.org/wiki/Twelve_basic_principles_of_animation
- "Game Feel" by Steve Swink
- Casey HH 原版 C 代码:https://github.com/HandmadeHero/handmade-hero
- Brendan Gregg Flame Graphs:https://www.brendangregg.com/flamegraphs.html

## 与其他阶段的关系

| 阶段 | 关系 |
|---|---|
| Phase 0(起步) | 本阶段涉及的所有数学(线性代数 / 微分方程)在 phase-0/14-math-foundations.md |
| Phase 1(平台层) | 本阶段的 OpenGL / shader 基于 Phase 1 的窗口 / 上下文管理 |
| Phase 2(2D 游戏) | 本阶段的角色移动是 Phase 2 的延续(更复杂) |
| Phase 3(3D 软渲染) | 本阶段的深度缓冲 / 光照在 Phase 3 基础上深化 |
| Phase 4(性能) | 本阶段的 SIMD / chunk streaming 用到 Phase 4 的优化技巧 |
| Phase 5(Debug + OpenGL) | 本阶段直接接续 Phase 5 末尾,把 OpenGL 渲染器升级 |
| Phase 7(PNG / 资产) | 本阶段的光照需要资产(法线贴图 / HDR 环境),Phase 7 教你怎么加载 |
| Phase 8(收官) | Phase 8 在 Phase 6 基础上做最终优化(tiled deferred 等) |

## 已完成天数索引

### Wave 1: Profiler 工具化(Day 261-269)

- [day261.md](day261.md) — 改成静态帧数组(环形 buffer)
- [day262.md](day262.md) — 绘制多帧性能图表(柱状图)
- [day263.md](day263.md) — 加调试帧滑块(scrubbing)
- [day264.md](day264.md) — 性能分析器加按钮(按下 + 抬起语义)
- [day265.md](day265.md) — 清理 UI 布局代码(layout 系统)
- [day266.md](day266.md) — 加顶级时钟性能视图(Top Clocks)
- [day267.md](day267.md) — 加逐元素裁剪矩形(clip rect)
- [day268.md](day268.md) — 合并调试链接与组(debug link + group)
- [day269.md](day269.md) — 清理菜单绘制(Extract Function 重构)

### Wave 2: 角色系统(Day 270-285)

- [day270.md](day270.md) — 创建可遍历点(Traversable 概念)
- [day271.md](day271.md) — 混合瓦片式移动(目标导向运动)
- [day272.md](day272.md) — 显式移动过渡(状态机)
- [day273.md](day273.md) — 动画概览(sprite / spring / 骨骼)
- [day274.md](day274.md) — 弹簧动态动画(Hooke + damping)
- [day275.md](day275.md) — 向渲染器传递旋转与剪切(2D 仿射变换)
- [day276.md](day276.md) — 调整身体动画(参数调优)
- [day277.md](day277.md) — 稀疏实体系统(generational index)
- [day278.md](day278.md) — 实体存储移到世界区块(chunk-based)
- [day279.md](day279.md) — 完成世界区块实体存储(跨 chunk 移动 + 卸载)
- [day280.md](day280.md) — 清理流式实体模拟(测试驱动重构)
- [day281.md](day281.md) — 房间之间动画相机(spring 相机)
- [day282.md](day282.md) — Z 轴移动与相机运动(2.5D)
- [day283.md](day283.md) — 让"站立"成为更严格的概念(standing_on)
- [day284.md](day284.md) — 重组头与身体代码(组合优于继承)
- [day285.md](day285.md) — 可遍历物的事务性占据(两阶段提交)

### Wave 3-7: Day 286-435(后续填充)

后续 wave 会覆盖:

- Day 286-310:深度缓冲 / 3D 几何基础
- Day 311-340:Phong / Blinn-Phong 光照
- Day 341-380:Shadow map / 法线贴图
- Day 381-410:多网格光照传播 / SIMD raycast
- Day 411-435:PBR 入门 / Phase 6 收官

## 下一步

读完 Wave 1-2(Day 261-285)后,你可以:

1. 继续 Wave 3+ Day 286+(深度缓冲 + 光照)
2. 暂停做 Phase 6 第一段验收(看上方"阶段项目验收"清单)
3. 给一个开源 crate 提 PR(看上方"开源贡献实践")
4. 回顾 Phase 0-5,把基础再巩固一遍

Phase 6 是 HH 最长阶段,**耐心比速度重要**。一集一集跟下来,175 天后你会站在图形学的入口,准备好进入 Phase 7。

## 阅读策略:不同背景读者的路径建议

### 路径 A:图形学新手(从零开始)

如果你从来没写过 shader 或做图形渲染,推荐的阅读顺序:

1. **Day 261-265**:Z 缓冲与 3D 几何基础。先理解"为什么 3D 渲染需要深度排序",再看具体实现。
2. **Day 266-280**:透视投影、相机、变换矩阵。这是图形学的"乘法口诀",必须熟练。
3. **Day 281-300**:光照基础(Lambert 漫反射)。读完你应该能用 GLSL 写一个最简单的 lit shader。
4. **暂停**:动手做一个 demo——画一个带光照的立方体,自己写 vertex + fragment shader。这一步至关重要,**没有亲手写过 shader,后面的内容都浮于表面**。
5. **Day 301-340**:排序规则、空间网格、深度优化。这部分是工程性内容,可以快读。
6. **Day 341-380**:Shadow mapping、法线贴图、深度精度。读这部分要随时回头看 Day 266 的相机矩阵。
7. **Day 381-410**:GI、体素、多光源。这是 Phase 6 的高潮,前面的基础都在这里用到。
8. **Day 411-435**:PBR 入门。PBR 把前面所有概念统一到一个框架——Lambert、Phong、Fresnel 都成了 Cook-Torrance BRDF 的特例。

### 路径 B:有图形经验,补 HH 工程细节

如果你做过 OpenGL / Vulkan / Unity shader,但想学 Casey 的工程方法:

- 直接跳到 Day 295+(sort_rule + bounds)
- 重点看 Day 305(memory arena)、Day 309-310(空间网格)
- Day 341+(shadow)看 Casey 怎么手写 GPU 资源管理
- Day 381+(GI)对比工业级 bevy_solari / Unreal Lumen 的差异

### 路径 C:重点学算法理论

如果你想深入理解算法(Lambert/Phong/Cook-Torrance 推导、reverse-Z 数学、BCn 压缩字节布局):

- 先读本目录下的 `deep-dives/` 子目录的 6 篇专题
- 再回到 day 文件看 Casey 的实现
- 配合外部资源:LearnOpenGL、Scratchapixel、Physically Based Rendering(在线免费书)

## Phase 6 的核心理论速查

以下是 Phase 6 涉及的核心数学公式,作为速查表:

### Lambert 漫反射

```
L_o(ω_o) = (ρ_d / π) · E · cos θ
        = (ρ_d / π) · ∫_Ω L_i(ω_i) · (N · ω_i) dω_i
```

其中 ρ_d 是 albedo,E 是辐照度,N 是法线,ω_i 是入射方向。1/π 是因为漫反射假设出射在半球均匀分布。

### Phong 镜面反射

```
L_spec = k_s · (R · V)^n
R = 2(N·L)N - L   (反射向量)
```

R 是入射光 L 关于法线 N 的反射,n 是 shininess(指数)。

### Blinn-Phong(优化版)

```
L_spec = k_s · (N · H)^n
H = (L + V) / |L + V|   (半向量)
```

H 是光线方向和视线方向的中间向量。Blinn-Phong 比 Phong 省 1 个 dot,但视觉上几乎一样。

### Cook-Torrance BRDF(PBR)

```
f_r = k_d · (ρ_d / π) + k_s · (D · G · F) / (4 · (N·L) · (N·V))
```

- D: Normal distribution function(GGX / Beckmann)
- G: Geometry function(Schlick model)
- F: Fresnel term(Schlick approximation:`F = F_0 + (1 - F_0)(1 - cos θ)^5`)

这是 PBR 的核心,Phase 6 Day 411+ 详细推导。

### Reverse-Z

```
z_ndc = a + b / z_view,其中 a = far / (far - near),b = far · near / (near - far)
```

通常投影后 z_ndc 在 [-1, 1](OpenGL)或 [0, 1](DirectX)。**Reverse-Z** 把 near 映射到 1,far 映射到 0——这样近处有更多 float 精度(f32 在 1 附近精度最高)。Phase 6 Day 350+ 详细推导。

### BC1 压缩(DXT1)

每 4×4 像素块 = 8 字节(原 16 像素 × RGBA = 64 字节,压缩比 8:1):

```
字节 0-1: color0 (RGB565, 16 bits)
字节 2-3: color1 (RGB565, 16 bits)
字节 4-7: 4×4 lookup table(每像素 2 bits,索引到 color0/color1/插值)
```

color0 > color1 时,4 种颜色:color0, color1, (2·c0+c1)/3, (c0+2·c1)/3。BC1 不带 alpha;BC2/BC3 加 alpha;BC4/BC5 单/双通道;BC6H HDR;BC7 高质量 LDR。

### 球谐函数(Spherical Harmonics)

球谐是定义在球面上的正交基函数。低频光照(Lambert 漫反射 GI)通常用 L2 球谐(9 个系数):

```
L(p) ≈ Σ_{l=0..2, m=-l..l} c_l^m · Y_l^m(p)
```

Y_l^m 是球谐基(实数形式),c_l^m 是系数。9 个 RGB 系数 = 27 个 float 描述一个点的入射光分布——足够重建间接光的低频部分。工业 light probe(Irradiance Volume、DDGI)都用 L2 SH。

## 实战资源清单

### 必装软件(Arch Linux)

```bash
# 图形调试
sudo pacman -S renderdoc vulkan-tools mesa-demos

# 性能剖析
sudo pacman -S perf valgrind
paru -S flamegraph  # 或 cargo install flamegraph

# GPU 监控
sudo pacman -S radeontop nvtop

# shader 开发
sudo pacman -S shaderc glslang
paru -S glsl_analyzer  # LSP for GLSL

# 资源工具
sudo pacman -S astc-encoder
paru -S basis-universal
```

### 关键 crate

| Crate | 用途 |
|---|---|
| `wgpu` | 跨平台 GPU 抽象(Vulkan/Metal/DX12/WebGPU) |
| `glam` | 向量/矩阵数学(SIMD 优化) |
| `rend3` | 高层渲染抽象(基于 wgpu) |
| `bevy_solari` | bevy 的 GI / lightmap |
| `basis-universal-rs` | 纹理压缩(BasisU / KTX2) |
| `gltf` | glTF 3D 格式加载 |

### 在线资源

- [LearnOpenGL](https://learnopengl.com/) — 现代 OpenGL 教程,Phase 6 内容的实战版
- [Scratchapixel](https://www.scratchapixel.com/) — 从零学光线追踪 / 路径追踪
- [Physically Based Rendering(在线书)](https://www.pbr-book.org/) — 离线渲染圣经
- [Khronos GLSL spec](https://www.khronos.org/registry/OpenGL/specs/gl/GLSLangSpec.4.60.pdf)
- [The Book of Shaders](https://thebookofshaders.com/) — fragment shader 入门

## 学习节奏建议

Phase 6 是 175 天,如果每天 2 小时,需要 350 小时——相当于大学一门 9 学分课程。建议节奏:

- **工作日**:每天 1 个 day 文件(读 + 跑代码)
- **周末**:整合一周内容,做小项目
- **每月**:回头重读一篇 deep-dive,加深理解
- **里程碑**:Day 280(相机完整)、Day 340(Phong 完整)、Day 380(shadow 完整)、Day 410(GI 完整)、Day 435(PBR 入门完整)

每个里程碑做一个 demo(自己写的小场景),验证理解。如果 demo 跑不起来,回头重读对应 day。

## 写给迷茫的读者

如果你在某一天卡住(看不懂代码、跑不起来 demo、不知道为什么 Casey 这么写),不要灰心。HH 的难度是真实的——Casey 是工业顶级程序员,他在视频中讲得很自然的内容,你可能要花 5-10 倍时间消化。

几个具体建议:

1. **不要跳**。Phase 6 是连续的,Day N 用到 Day N-1 的代码。跳过去会越读越懵。
2. **动手跑代码**。读 10 遍不如跑 1 遍。clone Casey 的代码,自己跑,改参数看变化。
3. **画图**。矩阵变换、光线追踪、shadow map——画在纸上比看屏幕强。
4. **问问题**。Handmade Hero 社区(handmade.network)、bevy Discord、Reddit r/rust_gamedev 都有热心人。
5. **休息**。卡住时离开电脑,散步 30 分钟。大脑在后台仍在处理,经常散步回来突然"啊我懂了"。

Phase 6 是 HH 的"长征",但走完之后,你具备写一个商业级 3D 渲染引擎的全部基础。这是值得的。
