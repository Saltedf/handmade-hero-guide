# 知识体系连贯性审计报告

**审计依据**: Casey 官方 Episode Guide(`Handmade Hero — Episode Guide.html`, 669 集)
**对照对象**: 本教程 `days/` 目录(744 个 Markdown 文件)
**审计目的**: 找出知识断裂处、覆盖盲点、跨阶段衔接问题
**结论先行**: 整体覆盖 99.6%, 但存在 **3 个缺失日** + **若干主题断裂** + **2-3 个完全缺失的关键概念**

---

## 一、硬性缺失(必补)

### 1.1 缺失的 dayNNN 文件(3 个)

| 缺失日 | 标题 | 所在 phase | 影响 |
|---|---|---|---|
| `day001qa` | Setting Up the Windows Build - Q&A | phase-1 | Phase 1 开篇 Q&A 缺失 |
| `day002qa` | Opening a Win32 Window - Q&A | phase-1 | Phase 1 开篇 Q&A 缺失 |
| `day111` | Resolution-Independent Ground Chunks | phase-3 | **真缺一日**(我之前误以为 Casey 跳过了) |

`day111` 是 Phase 3 → Phase 4 的过渡集,讨论"如何让地面瓦片随分辨率独立"。这是 HiDPI / 多显示器 / responsive design 的关键基础,**必须补写**。

### 1.2 完全缺失的核心概念(HH 没讲但教程必须自包含)

通过主题扫描,以下核心图形学/游戏开发概念在 HH 669 集标题里**一次都没出现**:

| 缺失概念 | 严重度 | 应放位置 |
|---|---|---|
| **Shadow Mapping**(阴影映射) | 高 | `phase-6/deep-dives/shadow-mapping.md` — 现有该文件但 HH 无对应日,需完全自创 |
| **PBR / Cook-Torrance**(基于物理的渲染) | 高 | `phase-6/deep-dives/pbr-complete.md` — HH 只用 Lambert/Phong,但现代引擎标配 PBR |
| **Network Multiplayer**(网络多人) | 中 | `phase-8/deep-dives/network-multiplayer.md` — HH 单机 |
| **GPU Profiling / RenderDoc**(GPU 调试) | 中 | `phase-6/deep-dives/gpu-debugging.md` — HH 浅讲 |
| **Build System (Bazel / Buck2)**(工业级构建) | 中 | `phase-0/16-build-systems.md` — 仅讲 cargo |
| **CI/CD for Games**(持续集成) | 中 | `phase-0/17-ci-cd.md` — 完全未讲 |
| **Cross-compilation**(交叉编译) | 低 | `phase-0/18-cross-compile.md` — 完全未讲 |

---

## 二、跨阶段主题断裂(知识连贯性问题)

### 2.1 主题在阶段间出现"长跳"

下表列出主题在 HH 时间线上出现的分布, gaps > 100 天 表示读者可能"忘记"该领域知识:

| 主题 | 出现日 | 最大 gap | 断裂影响 |
|---|---|---|---|
| **Audio** | day009-020 → day138-141 → day526 | **384 天** | 读者从 Day 141 到 Day 526 期间完全没接触音频,Phase 7 的"single-buffer streaming"显得突兀 |
| **Collision** | day050 → day377 → day631 | **296 天** | Phase 2 的 Minkowski 差到 Phase 6 的 ray-AABB 中间无碰撞主题 |
| **Multithreading** | day122-165 → day246 → day350 → day430 | **103 天** | Phase 5 中段无并发,Phase 6 突然用 thread pool,读者忘了 atomic |
| **SIMD** | day117 → day337 → day431 → day550 | **219 天** | Phase 3 完全无 SIMD,Phase 4 突然用 |
| **Editor** | day023 → day198 → day488 | **289 天** | Phase 5 编辑器雏形到 Phase 7 真正编辑器中间断裂 |
| **Frame Buffer** | day004 → day117 | **112 天** | 基础概念散落 |
| **Particles** | day155 → day336 → day533 | **193 天** | 主题反复重启 |

### 2.2 修复方案:新增"阶段桥"专题

针对每个断裂,在 phase-N/deep-dives/ 下新增**桥接专题**:

| 桥接专题 | 位置 | 作用 |
|---|---|---|
| `audio-pipeline-complete.md` | phase-5/deep-dives/ | 把 Phase 1 音频基础 → Phase 4 混音 → Phase 7 流式串成一条线 |
| `collision-evolution.md` | phase-5/deep-dives/ | Minkowski → AABB → Raycast → Voxel 的演化 |
| `threading-journey.md` | phase-5/deep-dives/ | Phase 4 atomics → Phase 5 lock-free → Phase 6 工作池 |
| `simd-progression.md` | phase-3/deep-dives/ | 标量 → SSE → AVX → portable-simd 的演化 |
| `editor-architecture.md` | phase-5/deep-dives/ | Phase 5 debug UI → Phase 7 game editor 的演化 |
| `particle-systems.md` | phase-4/deep-dives/ | 把 day155/336/533 串起来 |

### 2.3 阶段间"过渡检查点"

每个 phase 切换处加 `prereqs-check.md`:
- `phase-1/prereqs-check.md`: Phase 0 的哪些篇你必须先读 + 自测题
- `phase-2/prereqs-check.md`: Phase 1 学完后必须掌握的能力
- ...

这些**不是新内容**, 是把现有内容重新组织成"检查清单",帮助读者自检。

---

## 三、内容深度盲点

通过对 day001-667 标题的关键词聚类,以下概念在 HH 中反复出现但我们教程可能未充分深化:

### 3.1 高频主题(应该有专题深度)

| 主题 | HH 集数 | 我们有专题? |
|---|---|---|
| Lighting(光照) | 72 集 | ✓ `phase-6/deep-dives/lighting-models.md` 等 |
| Debug(调试) | 84 集 | ✓ `phase-5/deep-dives/*` 多个 |
| Asset Pipeline(资产管线) | 51 集 | ✓ `phase-7/deep-dives/asset-pipeline-architecture.md` |
| Geometry(几何) | 39 集 | ✗ 缺 `phase-3/deep-dives/geometry-primitives.md` |
| Voxel(体素) | 37 集 | ✓ `phase-8/deep-dives/voxel-collision.md` |
| Font(字体) | 26 集 | ✗ 缺 `phase-4/deep-dives/font-rendering.md` |
| Memory(内存) | 22 集 | ✓ `phase-4/deep-dives/arena-allocator.md` |
| Sort(排序) | 18 集 | ✗ 缺 `phase-5/deep-dives/sorting-algorithms.md`(虽然有 day232) |
| UI | 19 集 | ✓ `phase-5/deep-dives/immediate-mode-ui.md` |
| AI/Brain(AI) | 15 集 | ✗ 缺 `phase-2/deep-dives/ai-patterns.md` |
| Raycast(光线投射) | 15 集 | ✓ `phase-8/deep-dives/kd-tree-traversal.md` |
| Camera(相机) | 16 集 | ✗ 缺 `phase-3/deep-dives/camera-systems.md` |
| OpenGL | 16 集 | ✓ `phase-5/deep-dives/opengl-context-creation.md` 等 |

**需要新增 4 个 deep-dive**: font-rendering, sorting-algorithms, ai-patterns, camera-systems, geometry-primitives。

### 3.2 数学链断裂

HH 数学路径: day041(概览)→ day042-050(向量 / 碰撞)→ day101(矩阵)→ day361(3D 旋转矩阵)→ day553(余弦加权球面分布)

**问题**: day101 到 day361 之间 260 天,读者可能忘了矩阵。`phase-3/deep-dives/projection-matrices.md` 存在但仅讲投影,不讲变换矩阵的演化。

**修复**: 新增 `phase-3/deep-dives/matrix-transform-chain.md` — 完整的 model → world → view → clip → NDC → screen 链。

### 3.3 Rust 工具链盲点

教程覆盖: cargo, rustup, rust-analyzer, mold, perf, valgrind, gdb, flamegraph。

**未覆盖**:
- **sccache**(分布式编译缓存) — 仅在某天提及
- **cargo nextest**(下一代测试运行器) — 完全未提
- **cargo deny** / **cargo audit**(安全审计) — 未提
- **cross**(交叉编译) — 未提
- **cargo workspace 深入**(虚拟 manifest / workspace dependencies) — 浅讲
- **rust-objcopy / rust-lld**(binary 体积优化) — 未提
- **miri**(unsafe 检查器) — 仅简单提

**修复**: 新增 `phase-0/16-rust-toolchain-deep.md`(目前 phase-0 是 16 篇,加这个变 17)。

---

## 四、与 Casey 风格的偏离

Casey 视频里讨论的几个"软件工程哲学",我们教程可能没充分独立出来:

1. **Exploration-based architecture**(Day 27 提出)— HH 反复演示"先让它跑,再重构",但教程里没有独立专题。
2. **YAGNI**(Day 54) — 已在多日提及,但无专题。
3. **Rule of Three**(Day 27) — 抽象时机的"三出现原则"。
4. **Data-Oriented Design** — Phase 4+ 反复体现,但无专题。
5. **Debug-driven development** — Casey 调试方法论,无专题。

**修复**: 新增 `phase-0/19-software-craftsmanship.md` — 把这些哲学集中讲。

---

## 五、Handmade Ray 系列定位问题

现有 `days/handmade-ray/` 有 ray00-04 共 5 集, 但**没说什么时候读**。

**修复**: 
- 在 `days/README.md` 明确 Handmade Ray 在 Phase 8 之前( raycasting 预习)读
- 在 `phase-7/README.md` 加 "进 Phase 8 前必读 Handmade Ray" 提醒

---

## 六、优先级排序

### P0 必修(立刻)
1. 补写 `day111.md`
2. 补写 `day001qa.md`, `day002qa.md`
3. 新增 `phase-6/deep-dives/shadow-mapping.md`(完全缺失)
4. 新增 `phase-6/deep-dives/pbr-complete.md`(完全缺失)

### P1 重要(本周内)
5. 新增 4 个跨阶段桥接 deep-dive: audio-pipeline, collision-evolution, threading-journey, simd-progression
6. 新增 4 个高频主题 deep-dive: font-rendering, sorting-algorithms, ai-patterns, camera-systems
7. 新增 `phase-0/16-rust-toolchain-deep.md`(工具链)
8. 新增 `phase-0/17-ci-cd.md`(CI/CD)

### P2 有用(后续)
9. 各 phase 加 `prereqs-check.md`
10. 新增 matrix-transform-chain, editor-architecture, particle-systems, geometry-primitives 等 deep-dive
11. 新增 `phase-0/19-software-craftsmanship.md`
12. Handmade Ray 系列定位明确化

### P3 锦上添花
13. 新增 network-multiplayer, gpu-debugging, cross-compile 等 deep-dive
14. 风格调整为 tsoding 风(更多动手 / 试错 / 调试 narrative)

---

## 七、结论

**整体评估**: 当前知识体系覆盖率 85% 左右,**Phase 1-3 强,Phase 4-8 中等,跨阶段桥接弱**。

**最大问题**:
1. 3 天内容缺失(易补)
2. Shadow / PBR 这两个现代图形学核心完全缺失(必修)
3. 跨阶段主题断裂(读者可能"忘记")
4. Phase 0 工具链不完整(缺 CI/CD / sccache / nextest 等)

**修复总工作量**:
- ~3 个 day 文件(每个 25-40 KB)
- ~10 个 deep-dive(每个 12-25 KB)
- ~2 个 Phase 0 新篇(每个 15-30 KB)
- 共 ~12-15 个新文件,300-500 KB

完成后,本教程将真正做到"自包含的、专家级的、连贯的" — 而不是 HH 注脚。
