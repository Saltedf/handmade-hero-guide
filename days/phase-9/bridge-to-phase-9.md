---
phase: 9
type: bridge
title: "从 Phase 8 走到 Phase 9:Casey 烂尾了,你得自己上架"
domains: [game, graphics, engineering, rust, linux]
prereqs: ["phase-8"]
---

# Bridge · 从 Phase 8 到 Phase 9

> 你刚把 Phase 8 走完。667 天。从零到一,你跟完了 Casey Muratori 的 Handmade Hero 全程。你有一个能跑的、带实时 GI 的、商业品质**外表**的开源游戏代码库。**但有一个 Casey 没告诉你、你需要现在就认清的事实:Handmade Hero 烂尾了。** 不是说 Casey 没录完 667 集——他录完了。是说**这个项目从未真正"专业上架"**:它没有测试、没有 CI、单平台、从不发布、用的是上个世代的 OpenGL、Casey 的过程式架构经不起规模化、最后那段(phase-8)明显收尾草草。**如果你止步于此,你拥有的是一件精美的学习作品,不是一个能交付的产品。** Phase 9 就是补这一层。本文是过桥指南——从"跟完教程的人"走到"能独立交付一款专业水准游戏的开源工程师"。

## §0 · 你已经走过的路

先用一句话复盘你 667 天造的东西,这样你知道自己站在哪:

- **Phase 0**(起步营):终端、Arch、Git、Rust 从零、Linux 文件系统/进程、数学基础、读 C 和汇编。
- **Phase 1**(平台层,day001-025):开窗、显示像素、读输入、播音频、热重载。把 Win32 翻译成 winit+softbuffer+cpal+gilrs+libloading。
- **Phase 2**(2D 游戏,day026-070):实体系统、运动、碰撞、AI、资产管线。WASD 跑跳撞墙打怪得分。
- **Phase 3**(3D 基础+软渲染,day071-110):手写软件光栅化器。投影、深度、纹理、光照全在 CPU。
- **Phase 4**(性能/线程/资产,day112-175):SIMD、多线程、Arena 分配器、压缩资产。稳定 144 FPS。
- **Phase 5**(Debug+OpenGL,day176-260):profiling UI、debug overlay、切到 OpenGL。
- **Phase 6**(深度/光照/压缩,day261-435):深度缓冲、Phong/Blinn-Phong、PBR 入门、纹理压缩、shader、法线贴图。
- **Phase 7**(PNG/资产/编辑器,day436-575):手写 PNG 解码、glTF、in-game 编辑器、热加载。
- **Phase 8**(光照优化/碰撞/收官,day576-667):八面体 GI、无限弹射、k-d tree、体素碰撞。

**你做到了一件了不起的事**:从只会变量循环函数,到读得懂 Casey 的 C 代码、写得出来 Rust 版本、下钻得到 Linux 内核和 OpenGL spec。这是真功夫。

但 Phase 8 结束时的你,**还不是职业游戏工程师**。下面是诚实的差距盘点。

## §1 · 进入 Phase 9 前:诚实的差距盘点

下面每一项,打勾表示你**现在就会**,没打勾就是 Phase 9 要补的。**别不好意思——Casey 也没教你这些,因为 HH 本身就没做到。**

**A. 测试(HH 全程零测试)**
- [ ] 你能给游戏逻辑写单元测试,而不是"跑起来看看对不对"。
- [ ] 你能写 property test 验证数学函数(比如"对所有合法输入,矩阵乘法可结合")。
- [ ] 你能给渲染器写快照测试/视觉回归(改了 shader,知道画面没崩)。
- [ ] 你有一条 CI,每次 push 自动跑测试、挡住破坏。
- [ ] 你会做 fuzz 测试,让解析器(PNG/glTF/存档)在随机输入下不崩。

**B. 引擎架构(HH 是过程式单文件)**
- [ ] 你的游戏 loop 是固定步长+累加器+插值,而不是"每帧随便 dt"。
- [ ] 你的子系统(渲染/物理/音频/输入)有清晰分层和生命周期,不是一坨。
- [ ] 你有 frame graph / render graph,渲染 pass 声明式调度。
- [ ] 你有 CVars / dev console,能在运行时调参,而不是改代码重编译。
- [ ] 你有反射/RTTI,支持数据驱动的序列化与脚本。

**C. 现代 GPU(HH 止步 OpenGL)**
- [ ] 你理解 GPU 硬件(SIMT、显存层次、warp/wavefront),而不是把 GPU 当"快的 CPU"。
- [ ] 你能解释为什么需要 Vulkan/D3D12 这样的显式 API,以及它和 OpenGL 的本质区别。
- [ ] 你写过 Vulkan:instance/device/swapchain、command buffer、同步(fence/semaphore/barrier)。
- [ ] 你能用 RenderDoc 抓一帧、定位渲染 bug。

**D. 网络(HH 单机)**
- [ ] netcode 模型(lockstep/rollback/state-sync)你懂(phase-5 学过),但你**没搭过**权威服务器。
- [ ] 你没做过 matchmaking、NAT 穿透、relay、interest management。
- [ ] (Phase 9 补这些。)

**E. 发布(HH 从不发布)**
- [ ] 你没做过交叉编译(在 Linux 上产出 Windows 构建)。
- [ ] 你没有可复现构建、没有资产校验、没有 CI 自动出包。
- [ ] 你没走过"垂直切片→alpha→beta→认证→gold→上架"的流程。
- [ ] (Phase 9 补这些。)

数一数你打了几个勾。**多数读者这里能打的勾不多——这不是你的错,是 HH 的边界。** Phase 9 就是把这五块(A-E)系统性补上。

## §2 · 为什么 Handmade Hero 会"烂尾"

理解 HH 为什么烂尾,你才能理解 Phase 9 要补的东西**为什么是这些**。三个原因:

**第一,HH 的目标是"教",不是"上架"。** Casey 从第一天就声明:这是一个**教学项目**,目的是展示"一个人能不能从零做一个游戏"。它的成功标准是"讲清楚每个决策",不是"卖出去多少份"。所以 Casey 会花 87 天手写 PNG 解码器(教学价值极高),但**不会花一天写自动测试**(对教学叙事没贡献)。

**第二,HH 的架构是"探索式"的。** Casey 反复演示"先让它跑,再重构"。这在教学上很爽(你能看到思路演化),但结果是:**代码库没有一个稳定的"引擎架构"**——它是 667 天累积的、为叙事优化的、过程式的代码。商业引擎正好相反:先定架构,再填功能。

**第三,后期 Casey 的精力转移了。** phase-8(day576-667)的内容密度明显下降(本教程审计:37 个短文件,40% 低于 18KB 红线)。Casey 后期更多投入性能研究(如 *Performance-Aware Programming*),HH 的收官变得草草。**这就是"烂尾"的字面含义:不是没做完,是做得不够深。**

**结论**:HH 教给你的(从零造轮子、理解底层、过程式思维)是**真本事**;HH 没教你的(测试、架构、现代 API、发布)是**职业门槛**。Phase 9 补后者,但你**不要丢掉前者**——HH 式的"造轮子"精神是你区别于"只会调库的工程师"的护城河。

## §3 · Phase 9 的七条序列(预告)

Phase 9 把上面 A-E 的差距拆成七条**多讲次序列**(每条对标一门大学课程/一本专业书,不是单篇科普):

- **9A 测试与 QA(4 module)**:可测架构 → 单元/property → 集成/快照 → fuzz/回归。从 0 测试建到 CI 守护的回归网。
- **9B 引擎架构(4 module)**(对标 Gregory《GEA》):game loop/timestep → 子系统/插件/反射 → frame graph → CVars/dev console。
- **9C Vulkan 序列(8 module)**(对标 CMU 15-469):GPU 架构 → instance/swapchain → 同步 → 管线 → descriptor → 纹理 → 深度/mesh → **把 HH 一个 pass 迁到 Vulkan**。这是图形支柱的深度攀登。
- **9D GPU 调试(1 module)**:RenderDoc/PIX/Nsight 抓帧、timestamp、shader 调试。
- **9E 网络后端(4 module)**(对标 Gaffer on Games):可靠 UDP → 权威服务器/状态同步 → interest management → matchmaking/NAT/relay。
- **9F 构建/发布工程(3 module)**:CI/CD + 交叉编译 + 可复现构建 → release/live-ops → 跨平台/可移植。
- **9G 制作与交付(6 module)**:预制作/原型 → **垂直切片** → alpha/beta/内容量产 → **认证/TRC** → gold/上架/售后 → **专业就绪总清单**。

详见 [phase-9/README.md](README.md)。

## §4 · 做中学:Phase 9 不是"读完",是"造完"

Phase 9 的每个 module 都有一条**硬红线**:含「**在 HH 项目里动手**」节——给你**增量、可跑、可验证**的构建步骤(改哪个文件、加什么代码、跑出来看到什么)。序列内的 module 是递进的:后一个建立在前一个的产物上。

举几个例子:
- **9A-1** 教你把 HH 游戏的一个纯函数(比如碰撞检测)改成可测的,然后在 HH 项目里给它写第一个单元测试,跑 `cargo test` 看到绿。
- **9B-1** 教你把 HH 的"每帧随便 dt"loop 重构成固定步长+累加器,在游戏里看到"144 Hz 显示器下物理不加速"。
- **9C-4** 教你在 HH 项目里加一个 Vulkan 后端,跑出第一个三角形。
- **9G-2** 教你给 HH 游戏做一段"垂直切片"——把一小段玩法打磨到发布品质。

**Phase 9 的终点不是"读完 30 篇文章",是 capstone**:[capstone-creative-project.md](capstone-creative-project.md) —— **用所学一切,做一款属于你自己的原创游戏的垂直切片,打磨到可上架品质,开源发布。** 你交付了 Casey 没交付的东西。这就是"开源极客大师 + 能用编程自由表达想法和艺术创作"的毕业证明。

## §5 · 进入 Phase 9 前的最后自检

在开始 9A 之前,确认你**真的**跟完了 phase 0-8(至少 phase-0 全部 + 每个 phase 的 README + 至少若干 day 文件 + 关键 deep-dive)。Phase 9 假设你:

- [ ] 能读能写 Rust(所有权/trait/Result/泛型/lifetime)。
- [ ] 理解 HH 的整体架构(平台层 / 游戏 / 资产)。
- [ ] 跟过至少一次"软件光栅化"(phase-3)和"OpenGL 迁移"(phase-5)。
- [ ] 用过 cargo / git / 基本的 perf 或 flamegraph。
- [ ] 有一个能跑的 HH 游戏代码库(哪怕是早期版本),Phase 9 的"动手"要在它上面做。

如果以上某项缺,回去补——**Phase 9 不会重教 Rust 或 HH 基础**。

---

准备好了?[phase-9/README.md](README.md) 看七条序列的地图,然后从 **9A-1 testable-game-architecture** 或 **9B-1 game-loop-and-timestep** 开始(推荐 9B → 9A → 9C 路径)。

> *"Casey 教会你从零造一个游戏。Phase 9 教你把它做成产品。两者都要。"*
