# Handmade Ray · 光线追踪迷你系列

> Casey Muratori(Handmade Hero 作者)在 2015 年录制了一个 **5 集光线追踪迷你系列**,演示如何从零写一个 CPU 光线投射器(raycaster),逐步加多线程、SIMD 优化、采样 BRDF。这个系列**和 Handmade Hero 主线剧情平行**——主剧做软光栅化(Phase 3+),Handmade Ray 做光线追踪,两条路最终在 Phase 8 汇合成 Casey 完整的图形学体系。

## 这是什么

**Handmade Ray**(简称 HR)是 Casey 录制的 5 集配套系列:

| 集 | 标题 | 时长 |
|---|---|---|
| ray00 | 制作简单光线投射器(Making a Simple Raycaster) | 1h |
| ray01 | 多线程(Multithreading) | 1h |
| ray02 | 替换 rand() 并为 SIMD 准备(Replacing rand() and Preparing for SIMD) | 1h |
| ray03 | 用 SSE2 与 AVX2 优化(Optimizing with SSE2 and AVX2) | 1h |
| ray04 | 加载采样的 BRDF 数据(Loading sampled BRDF data) | 1h |

5 小时合计,**完整演示一个 CPU 光线追踪器的工业化构建过程**——从最朴素的版本到 SIMD 优化、采样 BRDF。

## 为什么单独写

主剧 HH 在 Phase 3(Day 071-110)做的是**软光栅化**(software rasterization)——把 3D 三角形投影到 2D 屏幕,扫描线填充。光栅化是**实时渲染主流**(所有 GPU 都做光栅化),但**不是唯一的渲染方法**。

**光线追踪(ray tracing)** 是另一种渲染方法:对每个屏幕像素,**反向发射一条光线**,光线在场景里传播,撞到物体时计算光照,可能再次反射(reflect)、折射(refract)、产生阴影(shadow ray)。光线追踪**物理上更正确**,但**计算量极大**,传统上只用于电影 / 离线渲染。

2018 年 NVIDIA 推出 RTX 显卡后,**实时光线追踪**成为可能。Cyberpunk 2077、Alan Wake 2 等大作已经把光线追踪作为核心渲染技术。**学光线追踪不再是"未来技能",而是当下图形工程师的必备**。

Handmade Ray 这个迷你系列教你:

- **从零写一个光线追踪器**(ray00):vector math、ray-shape 相交、shading
- **多线程并行**(ray01):光线追踪天然可并行(每像素独立),用 thread pool
- **替换 rand() 为高质量随机**(ray02):Monte Carlo 积分需要好的随机数
- **SIMD 优化**(ray03):用 SSE2 / AVX2 把 4-8 条光线一起算
- **采样 BRDF**(ray04):用测量数据(MERL BRDF Database)替代解析模型

这是**CPU 光线追踪的最小完整工业实现**——学会它,你以后看 RTX 渲染器、Path Tracer、Mitsuba、Cycles 都能秒理解。

## 学习目标

完成这个 5 集系列,你能:

1. **用 Rust 从零写一个 CPU 光线追踪器**(800 行内),支持:
   - Ray-AABB、Ray-Sphere、Ray-Triangle 相交
   - Lambert / Phong / 金属 / 玻璃材质
   - 阴影、反射、抗锯齿(MSAA)
   - Monte Carlo 全局光照(path tracing 基础)

2. **理解光栅化 vs 光线追踪的本质差异**,知道何时该用哪种

3. **多线程 + SIMD 加速 CPU 计算**,把单线程 1 FPS 的朴素版本提升到 30+ FPS

4. **读懂工业 RTX 渲染器的核心数据结构**(BVH、SAH、denoiser)

5. **阅读真实开源光线追踪器**(PBRT、Mitsuba、Cycles)的关键代码

## 系列结构(本教程扩展版)

Casey 原 5 集聚焦"性能优化"(ray00 写最小版,ray01-04 全是优化)。**初学者光看 Casey 的版本会吃力**——Casey 假设你已懂向量、光照、相交算法,直接跳到并行优化。

本教程把 Handmade Ray **拆成 5 集 + 1 个 README**,但**内容扩展**——把 Casey 跳过的"基础"补回来,同时保留 Casey 的优化思路。

| 集 | 标题 | 重点 | 时长 |
|---|---|---|---|
| ray00 | 光线追踪入门 | 什么是 ray tracing、vs 光栅化、最小 raycaster | 2-3h |
| ray01 | 基本 raytracer | 相机、射线、球体相交、shading 基础 | 2-3h |
| ray02 | 更多原始体 + 光照 | 平面、阴影、Phong 光照 | 2-3h |
| ray03 | 材质系统 | Lambert、Phong、金属、玻璃 | 2-3h |
| ray04 | 反射、递归深度、抗锯齿 | 镜面反射、MSAA、景深 | 2-3h |

**对应 Casey 原版的覆盖关系**:
- 本 ray00-01 ≈ Casey ray00(基础 + 球体)
- 本 ray02-03 ≈ Casey ray04(材质 + BRDF)
- 本 ray04 + 性能部分 = Casey ray01-03(多线程 + SIMD)

**性能优化**(多线程 + SIMD)在本系列末尾简略涉及,**完整 SIMD 优化**会在主剧 Phase 8(Day 580+)讲。

## 怎么和主剧配合

主剧 HH 的渲染学习路径:

```
Phase 3(3D 软光栅化):  Day 071-110   ──┐
                                        │  并行两条路
Handmade Ray:           ray00-04     ──┘
                                        
Phase 6 深度缓冲 + 光照: Day 261-435   ── 主剧进入图形学深水区
Phase 8 收官:           Day 576-667   ── 主剧合流,Casey 用 SIMD 做 raycast
```

**推荐学习顺序**:

1. **完成 Phase 0-2**(基础 + 2D 游戏)——确保你懂 Rust、向量、光照基础
2. **Phase 3 软光栅化**(Day 071-110)——理解传统光栅化,作为对比
3. **穿插 Handmade Ray** ray00-04——学光线追踪,加深对光照、几何的理解
4. **Phase 6 光照 / 压缩**(Day 261-435)——回到主剧深入图形学
5. **Phase 8 收官**——看 Casey 用 SIMD 加速 raycast(就是 Handmade Ray 优化版的延伸)

**如果你只想学光线追踪**,可以直接跳过 Phase 3,从 Phase 0 + Phase 1 完成后直接进 Handmade Ray。但**建议先做 Phase 3**——理解光栅化能让你更好地欣赏光线追踪的优雅。

## 风格

每集结构和主剧 dayNNN 一致:
- §0 为什么(动机)
- §1 Casey 做了什么(HR 脉络)
- §2 心智模型(核心抽象)
- §3 四域深入(图形 / 系统 / Rust / 数学)
- §4 认知地图
- §5 对照与变奏
- §6 关联
- §7 变式训练(Lv1-Lv4)
- §8 Rust 落地代码
- §9 延伸阅读

**所有数学公式手推**,所有 Rust 代码每行注释,**完全自包含**。

## 参考资源(本系列编写时使用的稳定 URL)

- **Ray Tracing in One Weekend**(Peter Shirley 免费):https://raytracing.github.io/books/RayTracingInOneWeekend.html —— 教学版 ray tracer
- **Scratchapixel**(在线图形学教材):https://www.scratchapixel.com/ —— 渲染原理
- **PBRT-Book**(Physically Based Rendering,免费):https://www.pbr-book.org/ —— 工业级 Path Tracer 教科书
- **Casey 原 Handmade Ray 视频**:https://guide.handmadehero.org/ray/ —— Casey 原版
- **MERL BRDF Database**:https://www.merl.com/brdf/ —— 测量 BRDF 数据(ray04 用)

## 阅读次序

新读者:从 [ray00.md](ray00.md) 开始,逐集读完。

已懂基础想看优化:跳到 ray03 / ray04。

只想看最终代码:每集 §8 都有完整可跑的 Rust 代码,可以拼起来。

## 风格金标

本系列参考主剧风格:
- [phase-0/14-math-foundations.md](../phase-0/14-math-foundations.md) — 线性代数基础
- [phase-2/day041.md](../phase-2/day041.md) — 游戏数学概览
- [phase-3/day071.md](../phase-3/day071.md) — 3D 渲染起步

---

**下一集**:[ray00.md — 光线追踪入门](ray00.md)
