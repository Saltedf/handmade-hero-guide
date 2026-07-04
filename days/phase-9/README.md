
# Phase 9 · 职业工程 + 制作交付:从烂尾到真正上架

> 你跟完了 Handmade Hero 的 667 天。但有一个没人明说的事实:**Handmade Hero 本身烂尾了——它从未"专业上架"。** Casey 的项目是绝佳的**学习载体**,但它不是一款"上架品质"的游戏:没有测试、没有 CI、没有现代 GPU API、单平台、从不发布、后期收尾草草(phase-8 那 37 个短文件就是映射)。**如果你止步于 day667,你拥有的是一个精致的 demo,不是一个能交付的产品。** Phase 9 就是补这一层:**用职业工程纪律和完整制作流程,把你从"跟完教程的人"变成"能独立交付一款专业水准游戏的开源工程师"。**

## 这一阶段在做什么

Phase 9 **没有 Handmade Hero 的天数**——它是纯"going pro"内容。按七条序列组织(每条都是对标真实大学课程/教材的**多讲次渐进构建**,不是单篇科普):

| 序列 | 主题 | 模块数 | 校准源 |
|---|---|---|---|
| **9A** | 测试与 QA | 4 | 软件工程测试 + 游戏可测性 |
| **9B** | 引擎架构 | 4 | Gregory《Game Engine Architecture》 |
| **9C** | 现代 GPU API(Vulkan) | 8 | CMU 15-469 + Vulkan spec |
| **9D** | GPU 调试工具链 | 1 | RenderDoc/PIX/Nsight 实操 |
| **9E** | 网络后端基础设施 | 4 | Gaffer on Games |
| **9F** | 构建 / 发布工程 | 3 | 工业 CI/CD + release eng |
| **9G** | 制作与交付 | 6 | 行业制作阶段 + TRC/TCR |

**共 30 个 module**。每个 module:① 标校准源;② 渐进构建进你的 HH 游戏代码库(做中学);③ 序列内前后依赖;④ ≥30KB,金牌 deep-dive 格式。

### 为什么是这七条(每条对应 HH 缺的一块)

**9A 测试与 QA** —— HH 全程**零**测试。商业游戏不能崩。这条教你把游戏写得**可测**,并建立从单元到回归的完整测试网。

**9B 引擎架构** —— HH 是 Casey 的过程式单文件风格,没有"引擎架构"可言。商业引擎有 game loop/timestep、子系统分层、插件、frame graph、CVars/dev console。这条把这些补成体系(对标 Gregory《GEA》)。

**9C Vulkan** —— HH 止步于 OpenGL(还是迁移来的)。**现代专业渲染必须懂显式 GPU API。** 这是图形支柱的"深度攀登":8 个 module 从 GPU 架构爬到把 HH 一个渲染 pass 迁移到 Vulkan。

**9D GPU 调试** —— 渲染 bug 用 printf 调不出来。RenderDoc/PIX/Nsight 是职业工具。综合现有散落的 19 处提及。

**9E 网络后端** —— HH 是单机。netcode **模型**(lockstep/rollback)你已在 phase-5 学过,但**基础设施**(权威服务器、matchmaking、NAT 穿透、复制裁剪)没人讲。这条补上。

**9F 构建 / 发布工程** —— HH 从不发布。商业游戏要交叉编译、可复现构建、资产校验、CI 守护、跨平台打包。这条把 phase-0/17 的 CI 基础扩展到工业级。

**9G 制作与交付** —— **HH 完全没有的"上架"层。** 预制作、可玩原型、**垂直切片**、alpha/beta、**认证/TRC**、gold 母版、上架与售后。这是"烂尾 demo"到"专业交付"的鸿沟。

## 里程碑

- **9A 后**:你的 HH 游戏有一条 CI 守护的回归测试网,改代码不再心慌。
- **9B 后**:游戏有固定步长 loop、子系统分层、frame graph、dev console —— 真正的"引擎"骨架。
- **9C 后**:你能用 Vulkan 渲染 HH 的一个 pass —— 跨过 OpenGL 的天花板。
- **9F 后**:一条命令产出 Windows + Linux 的可发布构建。
- **9G + capstone 后**:**你交付了 Casey 没交付的东西** —— 一款原创游戏的垂直切片,打磨到可上架品质,开源发布。

## 怎么走这一阶段(学习节奏)

Phase 9 的七条序列**不必严格顺序**,但有依赖:

```
9B(引擎架构)─┐
              ├─→ 9C(Vulkan,依赖 9B 的 frame-graph 概念)
9A(测试)───┘
9D(GPU 调试)可与 9C 并行
9E(网络后端)独立,但依赖 phase-5 的 netcode 模型
9F(构建发布)独立,随时可做
9G(制作交付)→ 最后,capstone 是它的收尾
```

**推荐路径**:9B → 9A → 9C(+9D)→ 9E/9F(并行)→ 9G → capstone。

每个 module 标准 1.5-3 小时(读 + 在 HH 项目动手 + 变式训练)。

## 北斗星:Phase 9 完成后你能做什么

- **测试**:给任何游戏系统写单元/property/snapshot/fuzz 测试,搭 CI 守护。
- **引擎架构**:设计 game loop、子系统分层、frame graph、dev console —— 不再是"一个 main 循环"。
- **现代 GPU**:用 Vulkan 从零搭渲染,理解 command buffer/sync/descriptor —— 读得懂任何现代引擎的渲染后端。
- **GPU 调试**:用 RenderDoc 抓帧、定位任何渲染 bug。
- **网络后端**:搭权威服务器、matchmaking、复制裁剪 —— 做得出可联机的游戏。
- **发布工程**:一条命令产出多平台可复现构建,带崩溃上报与 telemetry。
- **交付**:走过预制作→垂直切片→认证→上架全流程,**独立交付一款专业水准游戏**。

## 能力地图指针

Phase 9 对应主 README「专业能力地图」中的 **T8 职业工程** + **T9 制作与交付** 两轨。完成 Phase 9 后,这两轨的子能力全部 ✅,整个能力地图无 🔴 —— 你达到"专业就绪"。

## 外部校准源(供下钻)

- **CMU 15-469** Visual Computing Systems(GPU 架构 + 显式 API 深度)
- **CMU 15-466** Computer Game Programming
- **Gregory《Game Engine Architecture》**(引擎子系统圣经,本阶段多次对照其章目)
- **Gaffer on Games**(Glenn Fiedler 的 netcode 系列)
- **Vulkan Tutorial / Specification**(9C 的主参考)
- **Tim Cain 的游戏制作 9 阶段**(9G 的流程框架)
- **TRC/TCR 公开清单**(索尼/微软的上架认证要求,桌面核心对照)

## 关联

- 入口:[bridge-to-phase-9.md](bridge-to-phase-9.md) —— "HH 烂尾了,这里带你真正上架"
- 序列详见各 module(命名前缀 `09A-` ~ `09G-`)
- capstone:[capstone-creative-project.md](capstone-creative-project.md) —— 交付你自己的原创游戏垂直切片
- 上游:[phase-8/README.md](../phase-8/README.md) —— HH 的(烂尾)收官
