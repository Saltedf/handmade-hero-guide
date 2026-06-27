# Handmade Hero · Rust + Arch 综合教程

> 借 Handmade Hero 667 天的实践脉络,把一个**只有基本编程概念**的小白,培养成**真正的开源极客**:精通 Linux 系统编程、Rust 开源生态、游戏编程、图形学,能流畅用代码表达想法,能为大多数开源软件自由贡献代码。

## 这份教程是什么(以及不是什么)

**是**:
- 一份自包含的综合教程——所有核心概念都在教程内讲透,不需要翻外部资料
- 以 Handmade Hero 667 天为脉络的实践项目
- 手把手、零跳步——每个新术语第一次出现必解释,每行代码必注释
- 涵盖四大领域:Linux 系统编程、Rust 开源生态、游戏编程、图形学
- 教你"学会学习"——不只是事实,而是建立心智模型和迁移能力

**不是**:
- Handmade Hero 视频的字幕翻译
- API 速查手册
- "请参考 X"的索引页(自包含是铁律)
- 装腔作势的"专家文"——我们用费曼类比 + 严谨理论

## 北斗星:两个目的地

这份教程有**两个目的地**,合起来才完整:

**目的地 1 · 发布一个商业品质的开源游戏(Phase 0-8,跟 Handmade Hero 667 天)**

完成这 667 天后,你能:

- **从零**用 Rust 写一个完整的游戏(2D / 3D / 音频 / 软渲染 + OpenGL)
- **读懂** Casey Muratori 的原版 C 代码 + Rust 翻译 + Linux 内核源码 + OpenGL spec
- **贡献** Rust 生态主流 crate(bevy / wgpu / glam / tokio / std)的代码
- **设计** 自定义内存分配器、线程池、渲染管线、shader 系统
- **调试** 用 perf / valgrind / gdb / flamegraph 定位任何性能问题
- **理解** 从晶体管到 shader 的完整链路,任何抽象层你都能下钻到底层

**目的地 2 · 成为职业游戏工程师,独立交付一款专业水准游戏(Phase 9)**

Handmade Hero **本身烂尾了——它从未"专业上架"**(无测试、无 CI、单平台、止步 OpenGL、过程式架构、后期草草)。Phase 9 补这一层,完成后你能:

- **测试**:给任何游戏系统写单元/property/snapshot/fuzz 测试,CI 守护
- **引擎架构**:game loop/timestep、frame graph、子系统分层、CVars/dev console
- **现代 GPU**:用 Vulkan 从零搭渲染,读得懂任何现代引擎后端
- **网络后端**:权威服务器、matchmaking、NAT/relay、复制裁剪
- **发布工程**:交叉编译、可复现构建、崩溃上报、多平台打包
- **交付**:走完预制作→垂直切片→认证→上架,**独立交付一款专业水准游戏**,并用代码自由表达想法和艺术创作

> Casey 教会你从零造一个游戏。Phase 9 教你把它做成产品。**两者都要。**

## 读者画像

**你会的**:变量、循环、条件、函数(任何语言的版本)
**你不会的**:Rust、Linux、图形学、游戏开发

如果你已经懂 Rust,Phase 0 可以快读或跳过。
如果你已经懂 Linux,Phase 0 部分篇目可以跳过。
但**所有 HH 天数教程(day001-day667)假设你完整学过 Phase 0**。

## 教程结构

```
days/
├── README.md              ← 你在看的这页
├── TEMPLATE.md            ← 每日模板(参考)
├── reference/             ← 参考资料(subagent 撰写时用)
│   ├── README.md          ← 外部资料索引
│   └── hh-slices/         ← HH 路线图 JSON 切片
├── phase-0/               ← 起步营(16 篇,小白到能跟 Phase 1)
├── phase-1/               ← Day 001-025 · 平台层
├── phase-2/               ← Day 026-070 · 2D 游戏
├── phase-3/               ← Day 071-110 · 3D 基础 + 软渲染
├── phase-4/               ← Day 112-175 · 性能 / 线程 / 资产
├── phase-5/               ← Day 176-260 · Debug 系统 + OpenGL 迁移
├── phase-6/               ← Day 261-435 · 深度缓冲 / 光照 / 压缩
├── phase-7/               ← Day 436-575 · PNG / 资产管线 / 编辑器
├── phase-8/               ← Day 576-667 · 光照优化 / 碰撞重构 / 收官(HH 烂尾处)
└── phase-9/               ← 职业工程 + 制作交付(无 HH 日,带你真正上架)
```

## 怎么用这份教程

### 学习节奏

- **每篇 phase-0 文章**:1-3 小时(读完 + 动手做完练习)
- **每个 dayNNN**:1.5-3 小时(读 → 跟 Casey 视频对照 → 写 Rust 代码 → 做练习)
- **每 phase** 末尾:回顾 + 提一个开源 PR

### 一天的标准流程

1. 读 §0 为什么,搞清动机
2. 看对应 HH 视频(Casey 原版,YouTube / B 站)
3. 读教程 §1-§6,做笔记(自己复述心智模型)
4. 写 Rust 代码实现当天功能
5. 做 §7 变式训练(Lv1 → Lv4)
6. 读 §8 落地代码,把代码跑通
7. (可选)Lv4 开源贡献,真实提 PR

### 不能跳的部分

- **§0 为什么**:决定你后面会不会"知道在干什么"
- **§2 心智模型**:决定你后面会不会"看不懂"
- **§7 变式训练**:决定你后面会不会"学完就忘"

## 各阶段路径

### Phase 0 · 起步营([phase-0/](phase-0/))

16 篇手把手,把"只会变量循环函数"的小白拉到能跟 Phase 1:

- 终端、shell、vim
- Arch Linux 配置、systemd、包管理
- Git / GitHub / PR 全流程
- Rust 从零(覆盖 The Rust Book 1-16 章精华)
- Linux 文件系统、进程、信号
- 编辑器、工具链、诊断工具
- 数学基础(线性代数从零)
- 读懂 C 和汇编(看 Casey 原版代码)

### Phase 1 · 平台层([phase-1/](phase-1/),Day 001-025,25 天)

搭建"舞台":开窗、显示像素、读输入、播音频、热重载。这是 Casey 把 Win32 翻译成 winit+softbuffer+cpal+gilrs+libloading 的实战。

里程碑:程序开窗,显示一个绿色方块,按键改变颜色。

### Phase 2 · 2D 游戏([phase-2/](phase-2/),Day 026-070,45 天)

真正做游戏:实体系统、运动、碰撞、AI、资产管线。

里程碑:WASD 控制小人在 2D 地图跑跳,撞墙反弹,攻击怪物,有得分。看 [day041.md](phase-2/day041.md) 作为样本。

### Phase 3 · 3D 基础 + 软渲染([phase-3/](phase-3/),Day 071-110,40 天)

从 2D 进入 3D。Casey 手写一个软件光栅化器(不用 GPU):投影、深度、纹理、光照全在 CPU 上做。

里程碑:屏幕上渲染一个带纹理的 3D 立方体,有简单光照。

### Phase 4 · 性能 / 线程 / 资产([phase-4/](phase-4/),Day 112-175,64 天)

工程化:SIMD、多线程、Arena 分配器、压缩资产、构建系统升级。

里程碑:游戏稳定 144 FPS,内存峰值受控,大世界无加载卡顿。

### Phase 5 · Debug 系统 + OpenGL 迁移([phase-5/](phase-5/),Day 176-260,85 天)

工具化 + GPU 化:profiling UI、immediate-mode debug overlay、切到 OpenGL。

里程碑:游戏内置 debug overlay(实时调参、看实体),渲染后端从 CPU 切 GPU。

### Phase 6 · 深度缓冲 / 光照 / 压缩([phase-6/](phase-6/),Day 261-435,175 天)

图形学深水区:深度缓冲算法、Phong / Blinn-Phong 光照、PBR 入门、纹理压缩、shader 系统、法线贴图。

里程碑:动态光照下的 3D 场景,有 specular highlight,有法线贴图细节。

### Phase 7 · PNG / 资产管线 / 编辑器([phase-7/](phase-7/),Day 436-575,140 天)

工程进阶:手写 PNG 解码器、glTF 模型加载、游戏内编辑器、热加载资产。

里程碑:游戏内置地图编辑器,实时编辑关卡,保存到 JSON。

### Phase 8 · 光照优化 / 碰撞重构 / 收官([phase-8/](phase-8/),Day 576-667,92 天)

收官:光照算法优化( tiled deferred)、3D 碰撞重构(体素)、最终性能 pass。

里程碑:**Handmade Hero 功能完成**——但诚实说,这是 HH 的(烂尾)收官:无测试、无 CI、单平台、止步 OpenGL。要变成"专业上架品质",继续 Phase 9。

### Phase 9 · 职业工程 + 制作交付([phase-9/](phase-9/),无 HH 日,30 个 module)

**补完 Handmade Hero 烂尾留下的全部职业缺口**,让你能独立交付一款专业水准游戏。七条多讲次序列(每条对标一门大学课程/教材):

- **9A 测试与 QA(4)** · **9B 引擎架构(4)**(对标 Gregory《GEA》)
- **9C 现代 GPU API / Vulkan(8)**(对标 CMU 15-469)· **9D GPU 调试**
- **9E 网络后端(4)**(对标 Gaffer on Games)
- **9F 构建 / 发布工程(3)** · **9G 制作与交付(6)**(原型→垂直切片→认证→上架)
- 收尾:**capstone** —— 交付你自己的原创游戏垂直切片

里程碑:**你交付了 Casey 没交付的东西** —— 一款可上架品质的原创游戏,开源发布。

## 课程轨道(Course Tracks)

整个教程重组为 **9 条课程轨道**,每条对标一门真实大学课程或一本专业教材——这把"广度 + 深度"显式化、可审计。667 个 day 文件是 T1-T5 的天然课程 spine(渐进造游戏),deep-dive 是各轨的理论深化,Phase 9 补 T8/T9 职业层。

| 轨道 | 领域 | 对标课程/教材 | 主要承载 |
|---|---|---|---|
| **T1** | 实时图形 / 渲染 | CMU 15-462/662 + Berkeley CS184 + pbrt + Real-Time Rendering + CMU 15-469 | phase-3/5/6/7/8 + 9C(Vulkan)+ 9D + 图形顶端 deep-dive |
| **T2** | 数字音频 / DSP | Stanford CCRMA 320A/B/C + Julius Smith | phase-0/22 + phase-4/5/7 + 音频深度序列 |
| **T3** | 系统编程 | MIT 6.S081(xv6)+ CSAPP | phase-0 系统篇 + phase-1/4/5 + 系统深度序列 |
| **T4** | 物理与动画 | CMU 15-464 + 15-763 + Box2D/Rapier | phase-2/3/4/8 + 物理动画顶端 deep-dive |
| **T5** | 游戏性编程 | CMU 15-466 + Swink《Game Feel》+ Nystrom《GPP》 | phase-2/5/7/8 + 游戏手感/输入/状态/事件/玩法系统 |
| **T6** | 游戏 AI(游戏性子领域) | Millington《AI for Games》+ Rabin | phase-2(ai-patterns)+ phase-7(navmesh)+ AI 深度 |
| **T7** | 游戏 UI / 交互(游戏性子领域) | 响应式 + WCAG 可访问性 + 数据驱动 UI | phase-5/7 + UI 架构/布局/HUD deep-dive |
| **T8** | 职业工程 | Gregory《GEA》全章目 + CMU 15-469/466 + Gaffer | **Phase 9**(9A-9F) |
| **T9** | 制作与交付 | 行业制作阶段 + TRC/TCR | **Phase 9**(9G + capstone) |

> **核心原则**:T1-T5 的 spine(667 day 文件)**不重造**;新内容只补**四大支柱(T1/T2/T3/T5)的顶端深度 + T6/T7 子领域 + T8/T9 职业层**,以及 **HH 烂尾处(phase-8)的补深**。每条轨道的完整 spine 图与 module 清单见各 phase README 与 Phase 9 README。

## 专业能力地图(毕业自检)

下面是"专业游戏程序员"的能力矩阵。完成 Phase 9 后,每一项都不再是 🔴。**用它定位你还缺什么。**

| 域 | 子能力 | 状态 | 去哪学 |
|---|---|---|---|
| **图形** | 软件光栅化 / 投影 / 深度 / 纹理 | ✅ | phase-3 |
| | 实时光照 / PBR / deferred / TAA / GI | ✅ | phase-6/8 |
| | 现代 GPU API(Vulkan)/ 硬件光追 | ✅ | 9C / hardware-ray-tracing |
| | GPU 调试 / 现代渲染技术 / frame graph | ✅ | 9B-3 / 9D / modern-rendering |
| **音频** | DSP / FFT / 合成 / 效果 / 3D / 自适应 | ✅ | phase-5/7 |
| | 物理建模合成 / 卷积混响 / 编解码 / 软合成器 | ✅ | 音频深度序列 |
| **系统** | shell/arch/fs/进程/工具链/平台层 | ✅ | phase-0/1 |
| | 内存/并发/SIMD/cache | ✅ | phase-4 |
| | 虚拟内存/异步IO/动态链接/调度/读内核 | ✅ | 系统深度序列 |
| **物理/动画** | 刚体/约束/CCD/island/骨骼/蒙皮 | ✅ | phase-3/4/8 |
| | 柔体布料流体 / 角色控制器 / 高级动画(IK/重定向) | ✅ | T4 顶端 deep-dive |
| **游戏性** | ECS / AI 决策 / 寻路 / 确定性 / 脚本 | ✅ | phase-2/5/7/8 |
| | 游戏手感 / 输入 / 状态机 / 事件系统 / 玩法系统 | ✅ | T5 游戏性序列 |
| **AI** | 感知/记忆 / 群体 / AI 调试 | ✅ | T6 AI 深度 |
| **UI** | UI 架构 / 布局引擎 / HUD-菜单 | ✅ | T7 UI 深度 |
| **工程** | 测试/QA / CI/CD / 构建发布 | ✅ | 9A / 9F |
| | 引擎架构 / frame graph / CVars | ✅ | 9B |
| **交付** | 制作生命周期 / 垂直切片 / 认证 / 上架 | ✅ | 9G + capstone |
| | 网络后端 / 跨平台 / live-ops | ✅ | 9E / 9F |

> 图例:✅ 已覆盖(去对应 phase/篇) · 🟡 部分/待深化(去对应序列) · 🔴 完全缺(Phase 9 补)。

## 风格金标

撰写规范 / 风格锚:
- [TEMPLATE.md](TEMPLATE.md) — 每日教程模板
- [phase-0/00-terminal-basics.md](phase-0/00-terminal-basics.md) — Phase 0 文章样本
- [phase-2/day041.md](phase-2/day041.md) — HH 日样本
- [phase-2/README.md](phase-2/README.md) — 阶段 README 样本

## 检查你的进度

### Phase 0 完成自检

- [ ] 能用 vim 改配置文件,不紧张
- [ ] 装好 Arch,熟悉 pacman / AUR
- [ ] 注册 GitHub,fork → clone → PR 流程跑通一次
- [ ] Rust 基础能读(变量、所有权、enum、trait、Result)
- [ ] 看懂 Rust 编译器报错,知道 E0xxx 错误码是什么
- [ ] 知道 strace / gdb / perf 怎么用
- [ ] 能写出 3D Math Primer 里的向量、点积、叉积

### 每个 Phase 完成自检

- [ ] 该 phase 的所有 dayNNN.md 都读完
- [ ] 至少做了 §7 的 Lv1 + Lv2
- [ ] 至少一个 Lv3 迁移题你想出了答案
- [ ] 至少一次 Lv4 开源贡献,提交了 PR
- [ ] 该 phase 的 README 列出的"阶段项目验收"全部通过

## 这份教程的局限

- **Handmade Hero 本身烂尾**:HH 是绝佳的学习载体,但不是"上架品质"的游戏(无测试/无 CI/单平台/止步 OpenGL/过程式架构/后期草草)。Phase 9 显式跨越这个边界,但**你要同时保留 HH 的"造轮子"精神**——那是你区别于"只会调库的工程师"的护城河。
- **不能替代动手**:看懂 ≠ 会写。每天必须动手写代码。
- **不能替代视频**:HH 视频里 Casey 的思路、卡点、纠正是教程无法完全复刻的。
- **不能替代真实项目经验**:教程内的项目规模有限,真正的提升来自给开源项目贡献代码。

## 反馈与协作

教程本身在 GitHub(若你 fork 这份仓库),发现错误欢迎提 issue / PR。这是真正的开源协作训练。

## 致谢

- **Casey Muratori**:Handmade Hero 原创者
- **Rust 社区**:Rust Book / cargo / std / 无数 crate
- **Arch Linux 社区**:Arch Wiki 是 Linux 知识的宝库
- **所有免费教育资源**:3D Math Primer / LearnOpenGL / Game Programming Patterns / PBR Book ……

---

**下一步**:[phase-0/README.md](phase-0/README.md) 开始起步营,或直接跳 [phase-2/day041.md](phase-2/day041.md) 看样本格式。
