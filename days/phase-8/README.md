
# Phase 8 · 光照优化 + 碰撞重构 + 收官(最终阶段)

> 这是 Handmade Hero 的**最后一程**。从 Day 576 到 Day 667,Casey 把前 7 个 Phase 累积的所有知识汇成"商业品质"——光照系统升级到实时无限弹射 GI、空间查询用 k-d tree 和 walk table 优化、碰撞系统从 Minkowski 重写为体素化方案。完成后,你拥有一个**完整的、开源的、商业品质的游戏代码库**,以及从一个非程序员到"开源黑客"的全部能力。

## 这一阶段在做什么

Phase 7 末尾,你的游戏已经能跑:有完整 3D 渲染、Phong 光照、PNG 资产、glTF 模型、地图编辑器。但还有几件事没做完:

1. **GI(全局光照)不够好**:Phase 7 末尾的球谐光照(SH)对间接光照精度不足,墙角"糊"
2. **raycast 慢**:每帧 25 万次光线投射,跑不到 60 FPS
3. **碰撞系统局限**:Phase 2 的 Minkowski 碰撞对 3D 体素场景不够灵活
4. **代码不够干净**:累积了 600+ 天的代码,需要最终重构

Phase 8 解决这四件事,完成整个 Handmade Hero。

**子问题 1:八面体光照编码**(Day 576-589)
Casey 把间接光存储从球谐函数(SH)切换到八面体编码(Octahedral Encoding)。八面体编码把"3D 方向"压到"2D 纹理",每个体素只需要一张 16×16 RGB 贴图(3KB),比 CubeMap(18KB)省 6 倍,比 SH 精度更高。

**子问题 2:无限弹射 GI**(Day 584-589)
基于八面体辐射场,Casey 实现迭代求解的"无限弹射 GI"——光在场景里无限次弹射,逐步收敛到物理正确状态。这是 Handmade Hero 的核心 GI 功能,完成后游戏视觉品质从"扁平"跃升到"有空间感"。

**子问题 3:raycast 优化**(Day 590-610)
每帧 25 万次光线投射是性能瓶颈。Casey 用多种加速结构:
- **Grid DDA**(Day 590):规则网格上高效 raycast
- **k-d tree**(Day 595-597):自适应空间划分,三角形场景
- **walk table**(Day 601-603):预算"光线穿过格子的序列",查表替代算
- **可见性矩阵**(Day 610):跳过被墙遮挡的体素对

**子问题 4:碰撞重构**(Day 611-650)
Phase 2 的 2D Minkowski 碰撞扩展到 3D 不够灵活。Casey 重写为**体素化碰撞**——把场景表示为 3D 体素网格,碰撞查询变成"网格 raycast + 距离场"。这统一了渲染、碰撞、AI 的空间查询接口。

**子问题 5:最终清理**(Day 651-667)
最后的清理:删冗余、统一接口、加文档。Day 667 是 Handmade Hero 的**最后一集**,完成后代码库就是 Casey 留下的"完成态"。

完成 Phase 8 后,你有:
- 一个**商业品质的开源游戏代码库**
- 从零实现实时 GI、k-d tree、walk table、体素碰撞的全部能力
- 用 perf、valgrind、flamegraph 定位性能问题的能力
- 给真实开源项目(bevy、glam、tokio)贡献代码的经验

## 学习目标

完成 Phase 8 后,你能:

- [ ] 解释八面体编码的数学原理,实现 encode / decode,理解失真分布
- [ ] 实现完整的 GI 系统:辐射场存储 + 迭代传播 + 漫反射卷积
- [ ] 实现 k-d tree 构造 + 遍历,理解 SAH 与中位数划分的取舍
- [ ] 实现 Grid DDA、walk table 等多种 raycast 加速结构,知道每种适合什么场景
- [ ] 用 SIMD(AVX2 / SSE)加速数学计算,5 倍以上提速
- [ ] 用 Rust 的 trait / module / OnceLock 组织大型代码库(> 1 万行)
- [ ] 用 perf / flamegraph / valgrind 定位性能瓶颈,优化到 60 FPS
- [ ] 实现可见性矩阵 / 遮挡检测等空间查询优化
- [ ] 写出 Casey 风格的"持续重构"代码,定期清理保持质量
- [ ] **完成 Handmade Hero 全部 667 集**,拥有开源发布品质的游戏

## 主题索引(按 4 域分类)

### 🎮 游戏编程

- **day576-580**:八面体编码(概念 + 边界 + 调试 + 失真)
- **day581-583**:间接光照 pipeline + 重构
- **day584**:无限弹射 GI(里程碑)
- **day585-589**:集中化 atlas + 采样 + SIMD + 相机对齐
- **day590-603**:raycast 优化(Grid DDA + k-d tree + walk table)
- **day604-610**:工具结构 + 清理 + 可视化调试 + 可见性
- **day611+**:体素碰撞重构(Phase 8 主体)
- **day650+**:最终清理 + 收官

### 🎨 图形学

- **day576-580**:球面参数化(八面体 vs CubeMap vs SH)
- **day582**:Lambert BRDF 卷积
- **day584**:辐射度方法(Radiosity)+ 迭代求解
- **day590-603**:光线追踪加速结构(DDA / k-d tree / BVH / walk table)
- **day600**:Slab method + 法线推导
- **day608**:可视化(Heatmap / Normal Colored / Atlas Direct)
- **day610**:可见性矩阵(visibility matrix)

### 🐧 Linux 系统编程

- **day587**:AVX2 SIMD intrinsics
- **day590-603**:perf / valgrind / flamegraph 性能分析
- **day591**:独立 benchmark + 分位数统计
- **day592**:自定义 trace 系统(应用级)
- **day593**:Valgrind / ASan / UBSan 验证
- **day603**:OnceLock 全局静态数据
- **day605**:cargo clippy / cargo fmt / cargo doc

### 🦀 Rust 生态

- **day576**:SIMD intrinsics(`#[target_feature]`)
- **day583**:Trait + module 系统重构
- **day585**:数据导向设计(SoA vs AoS)
- **day587**:SIMD 友好代码(`is_x86_feature_detected!`)
- **day594**:Copy 语义 + struct 表达
- **day595**:Arena allocation(避免 Box 递归)
- **day601-603**:OnceLock / const 常量
- **day605**:Trait 抽象 + 静态 vs 动态分发

## 跨日专题(关键 deep-dives)

### 1. 八面体编码系列(Day 576-589)

- 数学原理:3D 球面 → 2D 平面映射
- 失真分析:雅可比矩阵、Frobenius 范数
- 边界处理:wrap vs padding
- 卷积:镜面 atlas → 漫反射标量
- 法线对齐:look-at 矩阵
- 工业级:Engelhardt & Dachsbacher 2010

### 2. 无限弹射 GI(Day 581-609)

- 辐射度方程:`B = E + ρ × Σ F × B`
- 迭代求解:Jacobi(double-buffering)
- 收敛性:Gauss-Seidel vs Jacobi
- 能量守恒:不变量检查
- 工业方案:DDGI、Lumen 对比

### 3. 空间加速结构(Day 590-610)

- Grid DDA:Amanatides-Woo 1987
- k-d tree:Bentley 1975,BVH 对比
- Walk Table:预计算 + 查表
- SAH(Surface Area Heuristic)
- 可见性矩阵:PVS(Quake)
- 工业级:RTX TLAS/BLAS

### 4. 性能工程(Day 587, 591-593)

- SIMD:AVX2 / SSE intrinsics
- Benchmark:criterion + 手写计时器
- Trace:应用级 instrumentation
- Profile:perf / flamegraph
- 验证:Valgrind / ASan / UBSan

## 阶段项目验收

完成 Phase 8 后,你的 Rust 项目应该能:

- [ ] 运行后开窗 1920×1080,稳定 60 FPS(完成所有优化)
- [ ] 玩家移动时,墙面间接光实时更新,无颤抖 / 闪烁
- [ ] 墙角 / 屋内有自然的间接光(无限弹射 GI)
- [ ] 光源移动时,场景光照平滑过渡
- [ ] raycast 性能:每帧 25 万次光线投射 < 4 ms
- [ ] `cargo run --release` 跑 30 分钟不崩溃,内存稳定不增长
- [ ] `cargo test` 所有 unit test 通过
- [ ] `cargo clippy` 无 warning
- [ ] `cargo doc` 生成完整文档
- [ ] 代码总行数 < 50000 行(经过重构)

## 开源贡献实践(本阶段)

Phase 8 是开源贡献的"毕业篇"。建议 2-3 个 PR:

推荐目标(按难度递增):

1. **`bevy_pbr`**(https://github.com/bevyengine/bevy)— 光照探针。读 `light_probe.rs`,看八面体实现;补 doc / test / example
2. **`glam`**(https://github.com/bitshifter/glam)— SIMD 数学。读 Vec3 实现;补 edge case 测试
3. **`bvh`**(https://github.com/svenstaro/bvh)— BVH 光追。读构造算法;补 doc
4. **`criterion`**(https://github.com/Brookke/criterion-rs)— Benchmark 工具。读统计实现;补 doc
5. **`rayon`**(https://github.com/rayon-rs/rayon)— 并行迭代。读 plumbing;补 doc

PR 类型建议:
- **文档**(最容易):补 doc、补公式推导、补 example
- **测试**(中等):补 edge case、补 SIMD 一致性测试
- **示例**(中等):加 runnable example
- **性能**(高难度):SIMD 优化、cache 优化
- **bug**(高难度):读源码找 bug

完成 Phase 8 = 你已经是合格的开源贡献者。

## 本阶段用到的 reference/ 资料

主要依据的本地 HH slice:[days/reference/hh-slices/phase-8.json](../reference/hh-slices/phase-8.json)(92 集 lesson 数据)

外部资料(按需 WebFetch):
- Engelhardt & Dachsbacher "Octahedral Normal Vectors"(2010):八面体编码原始论文
- Amanatides & Woo "A Fast Voxel Traversal Algorithm for Ray Tracing"(1987):Grid DDA
- Möller & Trumbore ray-triangle(1997):光-三角相交
- LearnOpenGL PBR / IBL 章节:辐射度理论
- Real-Time Rendering 4th ed. §10 / §16 / §17(GI / 碰撞 / 加速结构)
- PBR Book: https://www.pbr-book.org/

## 庆祝:你完成了 Handmade Hero

完成 Day 667 后,你做到了 Casey Muratori 设定的全部目标:

- 667 集 HH 全部完成
- 从零用 Rust 写出跨平台游戏框架
- 理解从晶体管到 shader 的完整链路
- 能给主流开源项目贡献代码
- 具备"持续学习"的能力——这是黑客的真正标志

**接下来的路**:

1. **关掉视频,自己做一个新游戏**:验证你真的吃透了 Casey 的架构
2. **深度参与开源**:从贡献者变 maintainer(bevy / wgpu / glam 等)
3. **学习新领域**:网络、AI、数据库、操作系统——你的基础已经够硬,新领域学得很快
4. **教别人**:写博客、做视频、带新人——教学是最好的学习

**Handmade Hero 不只是"做一个游戏",它是一种"亲手做一切"的哲学**。带着这种哲学,你可以在任何工程领域取得成功。

## Phase 8 详细天数列表

### Day 576-580:八面体编码系列

- [day576](day576.md) — 八面体编码(概念,5 星)
- [day577](day577.md) — 加八面体光照图集
- [day578](day578.md) — 采样八面体图集
- [day579](day579.md) — 调试八面体着色
- [day580](day580.md) — 调查八面体插值

### Day 581-589:间接光照 pipeline

- [day581](day581.md) — 准备八面体间接光照
- [day582](day582.md) — 镜面贴图转漫反射
- [day583](day583.md) — 精简新光照管线
- [day584](day584.md) — 启用无限弹射光照(里程碑)
- [day585](day585.md) — 集中化光图集处理
- [day586](day586.md) — 完成间接漫反射采样
- [day587](day587.md) — 优化镜面到漫反射变换
- [day588](day588.md) — 光照体素对齐相机
- [day589](day589.md) — 采样球对齐八面体贴图

### Day 590-610:raycast 优化系列

- [day590](day590.md) — 开始光线投射优化
- [day591](day591.md) — 制作独立光照性能测试
- [day592](day592.md) — 捕获全部光照数据
- [day593](day593.md) — 调试光照验证
- [day594](day594.md) — 从中心-半径切换到最小-最大
- [day595](day595.md) — 草拟 K-d 树循环(概念,5 星)
- [day596](day596.md) — 充实 K-d 树遍历
- [day597](day597.md) — 基础 K-d 树构造
- [day598](day598.md) — 为光线投射探索体素划分
- [day599](day599.md) — 实现网格光线投射后处理
- [day600](day600.md) — 更好的 AABB 法线推导
- [day601](day601.md) — 草拟步进表生成器
- [day602](day602.md) — 网格光线追踪器的提前终止
- [day603](day603.md) — 网格光线投射器表生成
- [day604](day604.md) — 加体素工具结构
- [day605](day605.md) — 清理光照代码
- [day606](day606.md) — 可视化调试网格光线投射
- [day607](day607.md) — 完成调试网格光线投射器
- [day608](day608.md) — 可视化光照值
- [day609](day609.md) — 减少不可访问体素的光贡献
- [day610](day610.md) — 移除错误体素-体素反射

### Day 611-667:体素碰撞重构 + 收官(后续 Phase 8)

(Day 611-667 由后续 phase-8 文件覆盖,涉及体素碰撞重构和最终清理。)

## 给 Phase 8 学生的建议

### 时间安排

Phase 8 是 92 天,内容密集。建议:
- **每天 1-2 小时**:1 集视频 + 1 天教程
- **每周一次回顾**:回顾本周主题,做笔记
- **每月一次实战**:完成 1 个 Lv3 / Lv4 变式训练
- **完成时**:庆祝!这是 Handmade Hero 的最后一程

### 心态调整

- **不要赶进度**:理解比速度重要
- **不要跳过重构**:重构是工程化的核心
- **不要怕 SIMD**:上手了就发现很简单
- **不要纠结"最优"**:够好就停,工程是权衡

### 遇到困难时

- 重读相关 Phase 0 文章(基础概念)
- 看 Casey 原版视频的对应片段
- 在 GitHub 看 Handmade Hero 原版 C 代码
- 在 Rust 用户论坛提问

### 完成后

- 写一篇"我完成了 Handmade Hero"的博客,分享你的代码
- 找一个 Rust 开源项目,开始贡献
- 自己设计一个小游戏,用 HH 学到的方法实现

---

**这是最后一阶段。你已经走过了 575 天的旅程。最后 92 天,我们一起把它完成。**
