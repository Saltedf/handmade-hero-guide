---
phase: 3
range: day071-110
days: 40
title: "3D 基础与软件渲染:从 2.5D 到带光照的立体世界"
estimated: "6-8 周"
prereqs: ["phase-0", "phase-1", "phase-2"]
domains: [game, graphics, math, linux, rust]
---

# Phase 3 · 3D 基础与软件渲染:从 2.5D 到带光照的立体世界

> 在 Phase 2 你做了一个完整 2D 游戏——小人能跑能跳能撞墙能攻击。Phase 3 把这个 2D 世界抬起来:加 z 轴让多楼层成为可能,加 premultiplied alpha 让 sprite 边缘干净,加 push buffer 让渲染器后端可换,加光照让画面立体。这 40 天是 Casey 把工程骨架变成「视觉精致 + 架构成熟」的关键阶段。

## 这一阶段在做什么

Phase 2 的最后一天,你的游戏有:WASD 控制小人在 2D 地图跑跳,撞墙反弹,攻击怪物,有得分。但地图是**平面**的——所有 entity 在 z=0,楼上楼下根本没法做。sprite 边缘有**黑边**——传统 alpha blending 的瑕疵。游戏代码**直接耦合 framebuffer**——以后想换 OpenGL 渲染要全改。

Phase 3 的核心问题是:**怎么把 2D 平面游戏变成「视觉精致 + 架构成熟」的 2.5D 游戏?**

这个问题拆开看有四个独立的子问题,Casey 一个一个解决:

**子问题 1:怎么加 z 轴,让多楼层、跳跃、楼梯成为可能?**(Day 071-080)
你的 entity 位置从 Vec2 升级到 Vec3。碰撞从 2D AABB 升级到 3D AABB 长方体。引入 traversable(可遍历物)概念——楼梯、斜坡、平台。地面从隐式规则变成显式 entity。这是 Phase 3 的**几何基础**。

**子问题 2:怎么做出程序化、无限变化的地面?**(Day 081-087)
你不能让美术画 1000 张不同的草地。Casey 用程序化合成——5 张小图组合产生无限变化。加缓存让性能可接受。加 chunk 对齐让世界无缝。加 alpha 边缘过渡让 tile 之间没有可见缝。这是 Phase 3 的**视觉基础**。

**子问题 3:怎么让渲染架构支持后期换后端?**(Day 088-089)
游戏代码不再直接写 framebuffer,而是 push 命令到 buffer。渲染器消费 buffer,翻译成具体操作(软件 blit 或 OpenGL draw call)。每条命令有 sort key,渲染前排序自动实现层 / 深度 / batching。这是 Phase 3 的**架构基础**。

**子问题 4:怎么让画面立体(光照 + 法线贴图 + 透视投影)?**(Day 090-110)
引入 base(基底)概念,正式化「位置 + 朝向」。加坐标变换让旋转矩形 / 纹理四边形可渲染。sRGB → Linear 转换让光照计算物理正确。Lambert 漫反射让 sprite 从「贴纸」变成「立体」。法线贴图让低模看起来像高模。透视投影让远的物体变小。这是 Phase 3 的**图形学核心**。

完成 Phase 3 后,你会有一个**真正立体的游戏**:多楼层建筑、带光照的 sprite、可旋转的物体、透视投影。架构上,**渲染层和游戏层彻底解耦**——Day 235 切 OpenGL 时游戏代码零改动。

## 学习目标

完成 Phase 3 后,你能:

- [ ] 解释 2D vs 2.5D vs 3D 的差别,知道每种的适用场景
- [ ] 用 Rust 实现完整的 Vec3 + 3D AABB 碰撞系统
- [ ] 实现多楼层建筑——楼上楼下 entity 互不影响
- [ ] 设计 traversable 系统(楼梯、斜坡、平台、电梯)
- [ ] 解释 premultiplied alpha 的原理,实现并消除 sprite 黑边
- [ ] 实现程序化合成 + 缓存 + chunk 系统(无缝大世界)
- [ ] 设计 push buffer + sort key 的渲染架构
- [ ] 用 Rust 写 sort key 位编码(64-bit pack layer/z/texture/sub)
- [ ] 解释 base 概念,实现 base 变换(局部 ↔ 世界坐标)
- [ ] 实现旋转矩形 / 纹理四边形的光栅化
- [ ] 解释 sRGB vs Linear 色彩空间,做正确的光照计算
- [ ] 实现 Lambert 漫反射 + 法线贴图
- [ ] 推导透视投影公式,实现分辨率无关渲染
- [ ] 给一个真实 Rust crate(glam / parry / bevy_render)提一个 PR

## 主题索引(按 4 域分类)

### 🎮 游戏编程

- **day071**:Vec3 定位(2D→2.5D,Casey 把 entity 位置改成 Vec3)
- **day072**:3D 包含测试(3D AABB 函数完善)
- **day073**:临时重叠(CCD 启发式,跳过头顶的物理)
- **day074**:楼梯 / traversable(z 线性插值,上楼下楼)
- **day075**:台阶高度(MAX_STEP 自动跨 / 撞)
- **day076**:entity 高度(height 字段正式化)
- **day077**:接地点(OnGround / InAir 状态机)
- **day078**:多碰撞体积(Boss 多 part,弱点 / 护甲)
- **day079**:地面作为 entity(显式化,多楼层基础)
- **day080**:碰撞循环顺序(先 z 后 x/y)
- **day085**:transient buffer(特效系统,过期自动消失)

### 🎨 图形学

- **day081**:程序化合成(程序化生成的入门)
- **day082**:缓存合成结果(memoization 经典优化)
- **day083**:Premultiplied alpha(消除 sprite 黑边)
- **day084**:滚动地面缓冲(部分更新优化)
- **day085**:transient buffer(分层渲染)
- **day086**:chunk 对齐(无缝大世界)
- **day087**:无缝地面纹理(tile 边缘过渡)
- **day088**:push buffer(渲染架构里程碑)
- **day089**:sort key(批处理 + 层 + 深度)
- **day090**:基底(坐标变换基础)
- **day091-093**:2D 旋转矩阵 / 旋转矩形 / 纹理四边形(本 README 范围外,Day 091+ 由后续 subagent 续写)
- **day094**:sRGB 转 linear(色彩学最重要转折)
- **day096-103**:Lambert 光照 / 法线贴图 / 反射向量 / 矩阵
- **day108-110**:透视投影 / 分辨率无关 / 反投影

### 🐧 Linux 系统编程

- **day071-072**:浮点精度与 epsilon(IEEE 754 实践)
- **day082**:缓存思想(page cache 类比)
- **day086**:chunk / page 对齐(Linux 内存管理类比)
- **day088**:producer-consumer 模式(管道 / Wayland 类比)
- **day090**:相对 vs 绝对路径(cwd / chroot 类比)

### 🦀 Rust 生态

- **day071**:手写 Vec3 + trait 实现(Copy / Add / Sub)
- **day072**:测试驱动开发(#[cfg(test)] mod tests)
- **day076**:派生字段陷阱(不存派生量,需要时算)
- **day078**:enum dispatch(sum type 替代虚函数)
- **day079**:serde 数据驱动(toml / json 加载世界)
- **day082**:HashMap entry API + LRU
- **day083**:premultiplied pixel struct
- **day084**:Vec<u32> + copy_from_slice(memcpy 加速)
- **day085**:Vec::retain(原地过滤)
- **day088**:Renderer trait(多后端注入)
- **day089**:u64 位编码 sort key
- **day090**:Base struct + Deref pattern
- **day071+**:`#[inline]` 提示、SIMD intrinsic、`const`、`unsafe`

## 跨日专题

Phase 3 有几个**贯穿多日**的专题,理解专题比单日细节重要:

### 专题 1:从 2D 到 2.5D 的演化(Day 071-080)

这是 Phase 3 第一阶段的脉络:

1. **Day 071**:Vec3 加 z 轴
2. **Day 072**:3D AABB 碰撞函数(数学完善)
3. **Day 073**:临时重叠(CCD,玩家跳过头顶)
4. **Day 074**:traversable(楼梯 / 斜坡)
5. **Day 075**:台阶高度(自动跨小台阶)
6. **Day 076**:height 字段(身高正式化)
7. **Day 077**:接地点(物理状态机)
8. **Day 078**:多碰撞体积(Boss 多 part)
9. **Day 079**:地面作为 entity(多楼层基础)
10. **Day 080**:碰撞循环顺序(先 z 后 x/y)

完成这个专题,你有一个完整的 2.5D 物理系统——多楼层、楼梯、跳跃、平台、Boss 多 part。

### 专题 2:程序化地面生成(Day 081-087)

1. **Day 081**:alpha blend 程序化合成
2. **Day 082**:tile cache(memoization)
3. **Day 083**:premultiplied alpha(消除黑边)
4. **Day 084**:滚动地面 buffer
5. **Day 085**:transient buffer(特效层)
6. **Day 086**:chunk 对齐(无缝大世界)
7. **Day 087**:tile 边缘过渡

完成这个专题,你有无限变化的、无缝的、视觉精致的地面系统。

### 专题 3:渲染架构(Day 088-105)

1. **Day 088**:push buffer(命令模式)
2. **Day 089**:sort key(批处理)
3. **Day 090-093**:base + 旋转 + 纹理四边形
4. **Day 094-095**:sRGB / linear(premultiplied + gamma)
5. **Day 096-103**:光照 / 法线贴图 / 反射
6. **Day 104-105**:y-up 渲染 / API 清理

完成这个专题,你有完整的软件渲染器——支持光照、法线贴图、旋转 / 缩放、可换后端。Day 235 切 OpenGL 时游戏代码零改动。

### 专题 4:透视投影(Day 106-110)

1. **Day 106**:世界缩放(可调)
2. **Day 107**:Z 层渐隐(多楼层视觉)
3. **Day 108**:透视投影(除以 z)
4. **Day 109**:分辨率无关渲染
5. **Day 110**:屏幕边界反投影

完成这个专题,你的游戏支持真 3D 透视,在不同分辨率下视觉一致,可以做视锥剔除。

## 阶段项目验收

完成这一阶段后,你的 Rust 项目应该能:

- [ ] 多楼层建筑:玩家走楼梯从 1F 到 2F,楼上楼下怪互不影响
- [ ] 程序化地图:每次启动世界略有不同(随机种子)
- [ ] sprite 边缘干净:premultiplied alpha,无黑边
- [ ] 大世界无缝:chunk 系统,玩家走到哪里都能流畅渲染
- [ ] 爆炸特效:生成 + 渐隐 + 自动消失
- [ ] 渲染架构:push buffer + sort key,可换后端
- [ ] 旋转 sprite:base 变换,玩家旋转时武器跟着旋转
- [ ] 光照:Lambert 漫反射,sprite 有立体感
- [ ] 法线贴图:平面上模拟凹凸细节
- [ ] 透视投影:远处的物体看起来小
- [ ] 分辨率无关:不同分辨率显示器视觉一致
- [ ] `cargo run --release` 跑 30 分钟稳定 60 FPS

## 开源贡献实践(本阶段)

找 1-2 个本阶段主题相关的 Rust crate / Linux 工具,读源码,提一个 PR:

推荐目标(按难度递增):

1. **`glam`**(https://github.com/bitshifter/glam)— 数学库。Day 071-090 的核心数学库
2. **`parry`**(https://github.com/dimforge/parry)— 碰撞检测库。Day 071-080 的碰撞
3. **`noise-rs`**(https://github.com/Razaekel/noise-rs)— 噪声库。Day 081 的程序化生成
4. **`lru`**(https://github.com/jeromefroe/lru-rs)— LRU 缓存。Day 082 的缓存
5. **`moka`**(https://github.com/moka-rs/moka)— 高性能缓存。Day 082 进阶
6. **`bevy_render`**(https://github.com/bevyengine/bevy)— Bevy 渲染。Day 088-089 的渲染架构
7. **`bevy_tnua`**(https://github.com/idanarye/bevy_tnua)— 角色控制器。Day 075-077 的平台物理
8. **`bevy_ecs_tilemap`**(https://github.com/StarArawn/bevy_ecs_tilemap)— Tilemap。Day 081-087 的 tile 系统
9. **`bevy_hanabi`**(https://github.com/djeedai/bevy_hanabi)— 粒子系统。Day 085 的特效

PR 类型建议(从易到难):
- 文档(doc comment 补全 / 公式推导 / 示例)
- 测试(补 edge case)
- 示例(加 runnable example)
- bug(找小 bug 修)
- 性能(只在你能完全理解原代码时做)

## Phase 3 的关键转折点

Phase 3 有几个**概念上的转折点**,理解它们比记住代码重要:

### 转折点 1:从隐式规则到显式数据(Day 079)

Phase 2 的「地面 = z=0」是隐式规则。Phase 3 的「地面 = entity」是显式数据。这一转变让多楼层、材质、动态变化都成为可能。

**通用思想**:**把隐式规则变成显式数据**,数据驱动设计。

### 转折点 2:从直接耦合到抽象层(Day 088)

Phase 2 的「游戏代码直接写 framebuffer」是直接耦合。Phase 3 的「游戏代码 push 命令,渲染器消费」是抽象层。这一转变让换后端成为可能。

**通用思想**:**依赖倒置**,高层不依赖低层,两者都依赖抽象。

### 转折点 3:从硬编码到 sort key(Day 089)

Phase 2 的「按 push 顺序渲染」是硬编码。Phase 3 的「按 sort key 排序」是数据驱动。这一转变让 batching 自然发生。

**通用思想**:**用数据描述意图**,而非用代码顺序。

### 转折点 4:从直觉色彩到物理色彩(Day 094)

Phase 2 的「在 sRGB 空间算光照」是直觉错误。Phase 3 的「转 linear 算完再转 sRGB」是物理正确。这一转变让光照真实。

**通用思想**:**理解工具的语义**(sRGB 是显示编码,不是计算编码)。

## 本阶段用到的 reference/ 资料

主要依据的本地 HH slice:[days/reference/hh-slices/phase-3.json](../reference/hh-slices/phase-3.json)(40 集 lesson 数据)

外部资料(按需 WebFetch):
- 3D Math Primer ch.4-5(向量 / 矩阵): https://gamemath.com/book/
- LearnOpenGL Transformations / Coordinate Systems: https://learnopengl.com/
- Scratchapixel(渲染理论): https://www.scratchapixel.com/
- PBR Book(基于物理的渲染): https://www.pbr-book.org/
- Casey HH 原版 C 代码: https://github.com/HandmadeHero/handmade-hero

## 延伸专题(后续 phase 详讲)

Phase 3 引入但**不深入**的话题,后续 phase 会展开:

- **4×4 矩阵**(Day 101-102 完整讲;Day 361+ 3D 旋转矩阵)
- **透视投影矩阵**(Day 108 入门;Day 359+ OpenGL 用)
- **法线贴图的切线空间**(Day 097 引入;Day 102 完整)
- **PBR / Cook-Torrance**(Phase 6 详讲)
- **GPU 渲染**(Day 235+ 切 OpenGL,Phase 5)
- **多线程渲染**(Phase 4 性能优化)

## Phase 3 后的下一步

完成 Phase 3 后,你有一个**架构成熟**的 2.5D 游戏。下一步:

- **Phase 4**(Day 112-175):性能 / 线程 / 资产。SIMD 优化、多线程、arena 分配器、压缩资产。让你的游戏稳定 144 FPS。
- **Phase 5**(Day 176-260):Debug 系统 + OpenGL 迁移。把渲染从 CPU 切到 GPU,加 profiling UI。
- **Phase 6**(Day 261-435):深度缓冲 / 光照 / 压缩。Phong 光照、PBR、纹理压缩。

Phase 3 是 Casey HH **架构层面**最重要的一段——push buffer / chunk 系统 / multi-floor 物理 / 程序化生成 / 光照入门,都是后续 600 集的基础。**慢慢来,确保每个概念都吃透**,后面会快很多。

---

**本阶段文件清单**(本 subagent 撰写范围 day071-090):

- [day071.md](day071.md) — 转换为完整 3D 定位
- [day072.md](day072.md) — 正确的 3D 包含测试
- [day073.md](day073.md) — 临时重叠的实体
- [day074.md](day074.md) — 实体沿楼梯上下移动
- [day075.md](day075.md) — 基于台阶高度的条件移动
- [day076.md](day076.md) — 实体高度与碰撞检测
- [day077.md](day077.md) — 实体接地点
- [day078.md](day078.md) — 每个实体多个碰撞体
- [day079.md](day079.md) — 定义地面
- [day080.md](day080.md) — 碰撞循环中处理可遍历物
- [day081.md](day081.md) — 用重叠位图创建地面
- [day082.md](day082.md) — 缓存合成位图
- [day083.md](day083.md) — Premultiplied alpha
- [day084.md](day084.md) — 滚动地面缓冲
- [day085.md](day085.md) — 暂时地面缓冲
- [day086.md](day086.md) — 地面缓冲对齐世界区块
- [day087.md](day087.md) — 无缝地面纹理
- [day088.md](day088.md) — Push buffer 渲染(里程碑)
- [day089.md](day089.md) — Sort key + 渲染命令类型
- [day090.md](day090.md) — 基底 第一部分

Day 091-110 由后续 subagent 续写(2D 旋转矩阵、纹理四边形、sRGB/Linear、Lambert 光照、法线贴图、反射、矩阵、y-up 渲染、世界缩放、Z 层渐隐、透视投影、分辨率无关、反投影)。
