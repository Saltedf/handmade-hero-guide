
# Bridge · 从 Handmade Hero 到职业世界

> 你做到了。667 天。从零开始,从一个空白窗口,到一个有完整渲染管线、PBR 光照、无限弹射 GI、资产管线、in-game 编辑器、碰撞系统、AI、音频混音的商业品质游戏代码库。**你做的事 99% 的程序员做不到**。现在你坐在这里,看着自己写的几万行代码,心想:然后呢?——这篇文章就是回答"然后呢"。Handmade Hero 不是终点,是起点。本文盘点你走过的全部 667 天,给你下一阶段的具体路径——找工作、做开源、写自己的项目、持续学习。

## §0 · 你已经走过的路(667 天盘点)

667 天是一段很长的时间。约 1 年 10 个月。在这段时间里你从"不会写窗口程序"到"理解商业游戏的每一行代码"。这是值得反复回看的一段旅程。

按 phase 盘点:

**Phase 0(预备)**:
- 装好工具链(Rust、Visual Studio Code / Neovim、git)。
- 读 Handmade Hero 的 intro,理解 Casey 的"从零开始"哲学。
- 心理准备——这是一个长跑,不是冲刺。

**Phase 1(Day 1-25,平台层)**:
- Win32 / winit 开窗,后缓冲,主循环,输入,音频。
- 平台层和游戏层分离(C ABI dll + 函数指针)。
- 热重载(`LoadLibrary` / `dlclose` + 文件 watcher)。
- **核心能力**:理解"什么是平台层",能从零搭一个。

**Phase 2(Day 26-70,2D 游戏)**:
- 玩家控制器、跳跃曲线、碰撞检测、entity 系统、sparse array + generation index、地图 / 关卡、AI、状态机、音效。
- **核心能力**:能做 2D 游戏,理解 ECS 演化路径,有"游戏感"的审美。

**Phase 3(Day 71-111,3D 渲染)**:
- 3D 向量数学、变换矩阵、view / projection、软件光栅化、Phong 光照、z-buffer、法线贴图。
- **核心能力**:3D 数学的直觉,软件光栅化的完整理解,GPU 工作原理的"软件版"理解。

**Phase 4(Day 112-175,工程化)**:
- SIMD、多线程、lock-free 数据结构、arena allocator、`.hha` 资产打包、音频混音、TrueType 字体。
- **核心能力**:性能优化心智,lock-free 编程,工业级内存管理。

**Phase 5(Day 176-235,GPU + ECS + 网络)**:
- OpenGL / shader / FBO、immediate-mode UI、archetype-based ECS、系统调度、网络多人(预测 + 回滚)。
- **核心能力**:GPU 编程,工业级 ECS,游戏网络同步。

**Phase 6(Day 236-435,渲染深化)**:
- Blinn-Phong → PBR、阴影映射 + CSM、IBL、HDR + tone mapping、bloom、TAA、延迟渲染 + 聚簇。
- **核心能力**:工业级渲染管线,接近 AAA 的视觉品质。

**Phase 7(Day 436-575,资产 + 工具链)**:
- 手写 PNG 解码、glTF 加载、资产热重载、in-game 编辑器、A* 寻路。
- **核心能力**:理解底层(从 bit 到像素),工业级工作流,数据驱动设计。

**Phase 8(Day 576-667,优化 + 收官)**:
- 八面体编码、无限弹射 GI、k-d tree 加速、体素化碰撞。
- **核心能力**:GI 实现(图形学圣杯),空间数据结构,商业品质游戏代码库。

把这 8 个 phase 加起来,你掌握了:

- **图形学**:从软光栅到 PBR 到 GI,完整链路。
- **游戏开发**:从平台层到游戏逻辑到工具链,完整链路。
- **性能优化**:从 SIMD 到多线程到 GPU,完整工具箱。
- **底层理解**:从 bit 到内存到线程到 GPU,完整层次。
- **工程化**:从单文件到模块化到 ECS 到资产管线,完整演化路径。

**这些能力组合起来,你已经是顶级的"系统程序员 + 图形程序员"候选人**。这不是夸张——能做到这一步的人在全球程序员里不到 1%。

接下来怎么用这些能力?本文给你 5 条路径。

## §1 · 进入职业世界前的能力盘点

**A. 系统编程能力**
- [ ] 你能从零写一个有窗口、画像素、读输入的程序(Phase 1)。
- [ ] 你能写多线程代码,理解原子操作和内存顺序(Phase 4)。
- [ ] 你能写 SIMD 加速代码,理解 cache 友好布局(Phase 4)。
- [ ] 你能写自己的内存分配器(arena / pool)(Phase 4)。
- [ ] 你能解析二进制文件格式(PNG / glTF / 自定义)(Phase 7)。

**B. 图形编程能力**
- [ ] 你能写 Phong / Blinn-Phong shader(Phase 3+5)。
- [ ] 你能写完整 PBR 渲染器(Cook-Torrance)(Phase 6)。
- [ ] 你能实现 shadow mapping + CSM + PCF(Phase 6)。
- [ ] 你能实现 IBL + HDR + tone mapping + bloom + TAA(Phase 6)。
- [ ] 你能实现基础 GI(Phase 8 八面体编码 + 几次弹射)。

**C. 游戏开发能力**
- [ ] 你能从零做一个 2D 游戏(Phase 2)。
- [ ] 你能从零做一个 3D 游戏骨架(Phase 3+5+6)。
- [ ] 你能写 in-game 编辑器(Phase 7)。
- [ ] 你能写资产管线(Phase 7)。
- [ ] 你能写碰撞系统(Phase 2 + Phase 8)和 AI(Phase 7)。

**D. Rust 生态熟练**
- [ ] 你熟练 Rust 所有权 / 借用 / 生命周期。
- [ ] 你熟练 unsafe Rust(`*mut T`、FFI、SIMD intrinsic)。
- [ ] 你熟练 async / await(虽然 HH 没用,但工业项目常用)。
- [ ] 你熟练 cargo workspace、feature、build script。
- [ ] 你熟悉 Rust 图形 / 游戏生态(winit、wgpu、bevy、glow、image 等)。

**E. Linux / 工具链熟练**
- [ ] 你能在 Arch Linux 上配置开发环境(Phase 1 已做)。
- [ ] 你熟练 git(分支、合并、rebase、cherry-pick)。
- [ ] 你熟练 gdb / lldb 调试(Phase 1 已做)。
- [ ] 你能用 RenderDoc / Tracy profile 图形 / 性能(Phase 4+5)。
- [ ] 你能写 shell script、Makefile、systemd service(工具集成)。

**F. 软件工程**
- [ ] 你能设计模块化架构(Phase 4+5)。
- [ ] 你能做重构(Phase 8)。
- [ ] 你能写测试(unit、integration、property)。
- [ ] 你能做 code review(读懂别人的代码、提改进意见)。
- [ ] 你能写文档(API doc、设计 doc、用户 doc)。

**G. 心理 / 职业准备**
- [ ] 你接受了"找工作不只是技术,还有面试 + 简历 + 人脉"。
- [ ] 你接受了"开源贡献是建立 reputation 的核心"。
- [ ] 你接受了"持续学习是程序员的常态,不是阶段性任务"。
- [ ] 你接受了"金钱 / 工作生活平衡是合理考虑,不是出卖理想"。

**怎么用这张清单**:逐项打勾。每一项都是你 667 天积累的能力。**写简历时这些就是你的"技能栈"**。

## §2 · 自测题

下面 6 道题,从"技术"到"职业"过渡。

### 题 1(技术总览)

如果用一句话向一个非程序员(比如 HR)解释你 667 天做了什么,你会怎么说?(目标:让外行也理解你的能力规模)

**参考答案**(模板,自己改):

"我用近两年时间,从零开始(不用现成的游戏引擎),独立写了一个完整的 3D 游戏代码库。这包括:窗口系统、3D 渲染管线(基于物理的光照模型)、动画系统、人工智能、物理碰撞、声音处理、资产管线、内置编辑器。技术栈是 Rust + OpenGL + Linux,代码量约 X 万行。这个项目对标 Handmade Hero,一个国际知名的游戏开发教学项目。"

这段话有两个关键:**"从零开始"(强调深度)和"完整代码库"(强调广度)**。HR 听到这种描述,会比"我会 Rust 和 OpenGL"印象深刻 10 倍。

### 题 2(职业方向选择)

下面 5 个职业方向,各自需要什么核心能力?哪个最匹配你 HH 学到的?

A. 游戏程序员(Unity / Unreal / 自研引擎)
B. 图形程序员(GPU 渲染、shader、可视化)
C. 系统程序员(操作系统、嵌入式、数据库)
D. Web 后端 / 基础设施
E. AI / 机器学习

**参考答案**:

**A. 游戏程序员**:HH 直接对口。核心能力:游戏循环、ECS、渲染管线、物理、AI、工具链。**你 HH 学的全部都用得上**。Unity / Unreal 的"使用"很容易学(几周),理解"原理"才是 HH 教你的。

**B. 图形程序员**:HH 高度对口。核心能力:OpenGL / Vulkan / DirectX、shader、PBR、阴影、后处理、GI。HH Phase 3+5+6+8 教的是图形学的完整链路,**你 HH 完成时已经具备图形程序员的入门能力**。补足:Vulkan / DirectX 12(显式 GPU API)、compute shader、光追。

**C. 系统程序员**:HH 大部分对口。核心能力:多线程、内存管理、二进制解析、FFI、unsafe Rust。HH Phase 1+4+7 大量涉及这些。补足:操作系统内核(进程调度、虚拟内存、文件系统)、网络协议栈、数据库内部。

**D. Web 后端**:HH 部分对口。核心能力:HTTP、数据库、并发、分布式。HH 教的多线程 / 性能 / Rust 转移得过去,但 Web 特定的(HTTP、SQL、Redis、Kubernetes)要另学。**不推荐直接走这条路**,HH 学的太多东西用不上。

**E. AI / ML**:HH 不对口。核心能力:Python、PyTorch / TensorFlow、统计学、线性代数。HH 教的图形学数学有一部分重叠(矩阵、积分),但 ML 的核心(神经网络、梯度下降、概率论)是另一套。**兴趣驱动的话可以转**,但 HH 学的大部分用不上。

**最匹配**:A(游戏)和 B(图形)。**HH 是为这两个方向量身定做的**。

### 题 3(开源贡献)

你 HH 毕业后,想给开源项目贡献代码。下面 5 个项目,你最有可能成功贡献哪个?为什么?

A. Linux 内核
B. Rust 编译器(rustc)
C. Bevy 游戏引擎
D. wgpu(Rust WebGPU 实现)
E. serde(Rust 序列化库)

**参考答案**:

**最可能成功:C(Bevy)和 D(wgpu)**。

理由:
- **Bevy 是 Rust 生态旗舰游戏引擎**,你 HH 学的 ECS、渲染、shader、资产管线**直接对口**。Bevy 的 issue tracker 有大量"good first issue"标签,适合新手入门。
- **wgpu 是 Rust 的 WebGPU 实现**,你 HH 学的 OpenGL / shader / GPU 概念直接对口。wgpu 也有大量新手友好 issue。

较难:
- **A(Linux 内核)**:需要深入内核知识(进程调度、内存管理、文件系统),HH 没教。**不推荐新手尝试**,学习曲线陡峭。
- **B(rustc)**:需要编译器知识(词法、语法、类型检查、借用检查),HH 没教。学习曲线陡峭。
- **E(serde)**:成熟项目,issue 少且大多是高难度设计问题。**新手不容易找到能贡献的 issue**。

**推荐路径**:
1. 在 GitHub 选 Bevy 或 wgpu。
2. 读 CONTRIBUTING.md,设置开发环境。
3. 在 issue tracker 找 `good first issue` 标签。
4. 选一个,自己尝试修复。
5. 提 PR,等 review。
6. 根据 review 改进,合并。

**第一个 PR 不一定要大**——文档改进、测试补充、bug 修复都行。**建立信任**比"PR 大小"重要。

### 题 4(简历项目)

你 HH 完成的代码库本身是一个简历项目,但**怎么在简历上呈现**才能最大化效果?给一个模板。

**参考答案**:

```
Handmade Hero 项目复刻(Rust + Linux)| 个人项目 | 2024-2026
https://github.com/yourname/handmade-hero-rust

从零开始(不使用现成游戏引擎)独立实现完整的 3D 游戏代码库。
- 平台层:用 winit + cpal + 自定义 dll 热重载,跨平台运行。
- 渲染:OpenGL 4.6 实现的 PBR 渲染管线,包括 IBL、cascaded shadow maps、
  bloom、TAA。延迟渲染路径支持 64 个动态光源。
- 资产管线:从 bit 流手写 PNG 解码器(DEFLATE + Huffman + Reconstruction filters);
  实现 glTF 模型加载;资产热重载工作流。
- 工具:in-game 编辑器(immediate-mode UI),支持选中、属性编辑、撤销 / 重做、
  关卡保存 / 加载。
- 性能:SIMD 加速关键循环;lock-free work queue 多线程;arena allocator;
  k-d tree 加速光线投射。基准:1080p 60+ FPS。
- 代码量:X 万行 Rust(含 Y 千行 GLSL)。
```

关键点:
- **量化**:具体数字(FPS、代码量、光源数)。
- **关键词**:PBR、IBL、CSM、TAA、SIMD、lock-free、arena——HR / 工程师都能搜。
- **链接**:GitHub 链接是必须的,代码要能跑。
- **简洁**:整段不超过 8 行。

**禁忌**:
- 不要写"学习了 Handmade Hero"——HR 不在乎你"学了"什么,在乎你"做了"什么。
- 不要写"理解了 ECS 概念"——要写"实现了 archetype-based ECS,支持 N 个系统并行调度"。
- 不要长篇大论——一页简历的项目描述不超过半页。

### 题 5(技术面试准备)

游戏公司 / 图形公司的技术面试常问什么?列出至少 5 类问题。

**参考答案**:

1. **C++ / Rust 基础**:内存管理(智能指针、借用检查)、虚函数 / trait、模板 / 泛型、UB(Undefined Behavior)。
2. **数据结构 + 算法**:LeetCode 风格(虽然 Casey 不屑,但工业面试常考)。重点:动态规划、图算法、字符串。
3. **图形学**:Phong / Blinn-Phong 公式、shadow mapping 原理、PBR 公式、deferred vs forward、GPU pipeline 阶段。
4. **数学**:矩阵乘法、点乘 / 叉乘、四元数、欧拉角 vs 四元数、投影矩阵。
5. **系统设计**:多线程同步、lock-free 数据结构、cache 友好布局。
6. **性能**:profile 工具使用、SIMD、内存层次。
7. **游戏特定**:游戏循环、ECS、固定时间步、网络同步(锁步 vs 状态同步)。
8. **debugging**:race condition 怎么定位、内存泄漏怎么找、GPU 渲染 bug 怎么排查。

**准备策略**:
- **LeetCode 中等难度刷 100 题**(不情愿但必要)。
- **图形学**:复习 Phase 3+5+6+8 的笔记,PBR 公式要会手推。
- **系统设计**:Phase 4 多线程 + Phase 5 ECS 的笔记。
- **mock interview**:找朋友 / 在线平台(pramp.com)模拟面试。

面试准备的"工作量":**全职 1-2 个月**,边工作的话 3-6 个月。**这个时间别省**——准备不充分,你的 HH 项目在简历筛选通过后,技术面挂掉一样白搭。

### 题 6(持续学习)

HH 结束后,你打算"持续学习"。下面哪些资源最值得投入时间?

A. ACM 论文(SIGGRAPH / GPU Gems)
B. GDC 演讲(Game Developers Conference)
C. 行业博客(jendrikllarena、Allen Chou、Self-Shadow)
D. 在线课程(Coursera、Udemy)
E. 自己做项目
F. 读其他游戏引擎源码(Unreal、Godot、Bevy)

**参考答案**:

**最值得:E、F、C**。

- **E(自己做项目)**:学习效率最高。HH 教的是"怎么学",真学要靠做。**毕业后的第一个 6 个月,做一个"自己的小项目"**(不是 HH 的复刻,是自己的设计)。
- **F(读源码)**:Bevy、Godot 都是开源的,读源码让你看到"工业级实现"和"HH 实现"的差别。**特别推荐 Bevy**——Rust 写的,现代设计。
- **C(行业博客)**:Allen Chou(物理)、Self-Shadow(图形)、jendrikllarena(GPU)是顶级工程师的博客,每篇都值得精读。

值得但不优先:
- **A(ACM 论文)**:图形学顶级会议(SIGGRAPH)的论文代表最前沿。**但读论文门槛高**,适合 HH 之后 1-2 年再读。
- **B(GDC 演讲)**:GDC 演讲是行业经验分享,**值得看但量很大**。挑感兴趣的看。

不太推荐:
- **D(在线课程)**:Coursera / Udemy 的图形 / 游戏课程,深度通常不如 HH。**HH 之后没必要再上课**——你应该能自学。

**持续学习的核心心智**:**HH 教的是地基,之后要盖楼**。盖楼要靠"做项目 + 读源码 + 读博客",不是"上课"。**你已经具备自学能力**。

## §3 · 心智切换:从"学生"到"职业"

HH 的 667 天,你的心智是"**学生**"——Casey 教什么你学什么,有明确的教学节奏,有"对答案"(看 Casey 怎么做)。

HH 结束后,你的心智要切换到"**职业**"——没有人告诉你"今天做什么",没有人给你"对答案",你要**自己选方向、自己定标准、自己评估结果**。

具体 6 条切换:

**1. 从"教学驱动"到"问题驱动"**。
HH 给你"今天做光照"。毕业后没人给你。
你要自己发现"我的项目缺什么",自己决定"先做什么"。

心智切换:**找问题比解决问题更难**。学生时代问题是给的,职业时代问题是找的。**找问题的能力,要靠做项目练**——做一个项目,你会发现一堆"我想加但还没加"的东西,这就是问题。

**2. 从"完美主义"到"完成主义"**。
HH 的代码 Casey 反复打磨,接近"完美"。但你的项目要发版、要给用户用,**不能无限打磨**。

心智切换:**Done is better than perfect**。一个能用的 v0.1,比一个永远在改的 v1.0 强 100 倍。**学会说"先这样,下个版本改"**。

**3. 从"独自工作"到"协作"**。
HH 全程你一个人写代码。职业世界你和别人合作——code review、design review、pair programming。

心智切换:**协作能力 = 沟通能力 + 工程能力**。沟通(写清楚 PR description、清楚解释设计)占 50%,工程能力占 50%。**不擅长沟通的工程师,职业天花板很低**。

**4. 从"个人风格"到"团队风格"**。
HH 你完全按自己风格写代码。
职业世界团队有代码规范、设计规范、命名规范。

心智切换:**风格不重要,一致重要**。**遵守团队规范,不坚持个人偏好**(在团队规范没规定的地方,可以提建议)。

**5. 从"学习优先"到"产出优先"**。
HH 学习是第一目标。
职业世界产出是第一目标(给公司、给用户、给社区)。

心智切换:**学习是副产品,产出是主产品**。**做项目时选"高产出"而不是"高学习"**——比如做一个简单的工具,产出明确,学习副产品;而不是做一个复杂的引擎,学习高但产出模糊。

**6. 从"金钱无关"到"价值交换"**。
HH 是个人学习,和金钱无关。
职业世界你的时间值钱,**你的工资 = 你的产出的市场价值**。

心智切换:**关心工资不是出卖理想**。一个能拿高工资的工作,意味着你在做"市场认可的有价值的事"。**理想和金钱不冲突**——找到"既理想又能挣钱"的交集,是最优解。

切换的最大陷阱:**HH 心态固化**。HH 教的"从零开始"哲学很好,但**职业世界大多数场景不应该从零开始**——用现成库、用现成框架、用现成工具,效率高 10 倍。

正确策略:**HH 教的是理解,不是规范**。理解了底层,用库时知道库在做什么;但**不要因为"我会从零写"就拒绝用库**——除非你证明用库不够好。

## §4 · 职业路径第一年学习路径

下面是 HH 毕业后第一年的具体路径(假设你 6 月毕业,目标是第二年 6 月找到好工作)。

**Month 1-2(7-8 月):整理 + 第一个个人项目**。
- 整理 HH 代码:清理、加文档、写 README、上传 GitHub。
- 第一个个人项目:选一个**比 HH 小但完整**的项目。比如:
  - 一个简单的物理引擎(2D 刚体)。
  - 一个 GPU 粒子编辑器。
  - 一个轻量级 Roguelike 游戏。
- 目标:**完成 v1.0**(发布在 itch.io 或 GitHub Releases)。

**Month 3-4(9-10 月):第一个开源贡献**。
- 选 Bevy / wgpu / 其他 Rust 项目。
- 修复 3-5 个 issue,提 3-5 个 PR,至少 1 个合并。
- 在社区(Discord、Forum)参与讨论,建立存在感。

**Month 5-6(11-12 月):深入一个领域**。
- 选你最感兴趣的领域(渲染 / 物理 / 工具链 / 网络),深入。
- 读 5-10 篇顶级论文 / 博客。
- 在个人项目里实现一个"高级特性"——比如 PBR 升级、TAA 实现、网络多人。

**Month 7-8(1-2 月):面试准备**。
- 简历定稿(用 §2 题 4 模板)。
- LeetCode 刷 100 题(中等难度)。
- 图形 / 系统 / 算法面试题复习。
- mock interview 5+ 次。

**Month 9-10(3-4 月):投简历 + 面试**。
- 投 30+ 公司(目标公司 + 备选)。
- 面试 10+ 家,拿 offer 2-5 个。
- 协商 offer(不要接受第一个,先比较)。

**Month 11-12(5-6 月):入职 + 适应**。
- 接受 offer,准备入职。
- 入职第一个月:熟悉代码、熟悉流程、认识团队。
- 入职第三个月:做出第一个 measurable contribution。

**时间预算**:全职 12 个月。如果你在职转行,可能要 18-24 个月。**关键是节奏稳定**——每周至少 20 小时投入。

## §5 · 实战项目建议

下面 5 个项目,任选 1-2 个作为 HH 之后的"个人项目"。

### 项目 A:物理引擎

从零写一个 2D 刚体物理引擎。技术栈:Rust。

需求:
- 重力、速度、加速度。
- 圆 vs 圆、AABB vs AABB、圆 vs AABB 碰撞。
- 碰撞响应(冲量法)。
- 关节约束(距离、铰链)。
- 序列化 / 反序列化(保存 / 加载场景)。

时间预算:3-6 个月。

为什么推荐:**物理是游戏开发的高门槛主题**,做一个简化版让你彻底理解。Box2D、Chipmunk、Rapier 都是这个领域的成熟库,你做完后读源码会顺畅。

### 项目 B:GPU 粒子编辑器

写一个 GPU 粒子编辑器(类 Unreal Niagara 简化版)。技术栈:Rust + OpenGL + immediate-mode UI。

需求:
- GPU 上更新粒子位置(compute shader 或 transform feedback)。
- 多个发射器,各自参数(发射率、生命周期、初速度)。
- 颜色 / 大小 / 速度的曲线编辑。
- 保存 / 加载粒子配置(JSON)。
- 实时预览。

时间预算:3-6 个月。

为什么推荐:**GPU 粒子是商业游戏的标配**。做完这个项目,你看 Unreal Cascade / Niagara、Unity Particle System 都不迷路。

### 项目 C:Roguelike 游戏

做一个简化版 Roguelike(类 Vampire Survivors)。技术栈:Rust + 你 HH 的代码。

需求:
- 程序生成的地图(perlin noise / cellular automata)。
- 多种敌人,各自 AI。
- 玩家升级系统(经验、技能)。
- 多种武器 / 道具。
- 简单 UI(主菜单、HUD、暂停)。
- 音效 / 音乐。
- 完整的游戏循环(开始 → 玩 → 死亡 / 通关 → 重新开始)。

时间预算:6-12 个月。

为什么推荐:**完成度高、市场认可**。Roguelike 是独立游戏最热门的品类(参考 Hades、Slay the Spire、Vampire Survivors),做完能在 itch.io / Steam 上发布。**而且 HH 学的几乎所有东西都用得上**。

### 项目 D:小型 3D 引擎

写一个简化的 3D 引擎(类 Bevy 简化版)。技术栈:Rust + wgpu + ECS。

需求:
- ECS 数据结构 + 系统调度。
- 场景图(scene graph)。
- PBR 渲染管线。
- 资产管理(异步加载)。
- 简单物理(集成 rapier 或自写)。
- 脚本系统(Lua 或 Rust script)。
- 编辑器(immediate-mode UI)。

时间预算:6-12 个月。

为什么推荐:**这是 HH 的"扩展版"**。HH 完成时你有一个"游戏代码库",做完这个你有"自己的引擎"。**引擎开发是图形程序员的最高职位方向**(Bevy、Fyrox 都是开源引擎,作者从个人项目起步)。

### 项目 E:实时可视化工具

做一个实时数据可视化工具。技术栈:Rust + wgpu + 数据处理。

需求:
- 读 CSV / JSON 大文件(百万行)。
- GPU 加速渲染(散点图、热力图、3D 图)。
- 交互(缩放、平移、过滤)。
- 多视图联动(选一个图的数据,其他图高亮)。

时间预算:3-6 个月。

为什么推荐:**这个项目"找工作友好"**——数据可视化在金融、医疗、科研都有需求。HH 学的图形 + 性能直接对口,但应用领域不同,**展示你能跨领域**。

### 不推荐的项目

- **从零写一个完整的 MMO**:工作量太大,1 年做不完。
- **AI / 机器学习项目**:HH 没教,要从头学。
- **Web 前端项目**:HH 没教,要从头学。

## §6 · 推荐配合的资料

下面是 HH 毕业后持续学习的"核心资料库"。每条都是经过筛选的顶级资源。

### 书(必读)

**1. Real-Time Rendering, 4th Edition**(Tomas Akenine-Möller 等)
- 图形学圣经。覆盖几乎所有渲染技术。**HH 教的是基础,这本书是完整参考**。
- 读完这本书,你看任何 SIGGRAPH 论文都不会完全迷路。

**2. Physically Based Rendering: From Theory to Implementation**(Matt Pharr 等)
- 路径追踪的完整实现。免费在线(pbr-book.org)。
- HH Phase 8 的 GI 是简化版,这本书是工业级版。**读完这本书,你能写自己的光线追踪器**。

**3. Game Engine Architecture, 3rd Edition**(Jason Gregory)
- Naughty Dog 主程写的游戏引擎架构书。覆盖游戏引擎的几乎所有子系统。
- HH 教的是"怎么做",这本书教"怎么组织"。

**4. Rust Atomics and Locks**(Mara Bos)
- Rust 多线程 + 原子操作的完整讨论。**Phase 4 你学的 lock-free 在这里有更深入的解释**。

**5. Designing Data-Intensive Applications**(Martin Kleppmann)
- 系统设计的圣经。虽然不是图形 / 游戏书,但**任何严肃系统程序员都该读**。

### 博客(订阅)

**1. Self-Shadow**(selfshadow.blogspot.com)
- Stephen Hill 的图形学博客。SIGGRAPH 演讲常客。**PBR / IBL / GI 顶级资源**。

**2. Allen Chou / Ming-Lun "Allen" Chou**(allenchou.net)
- 游戏物理、游戏编程博客。**联盟 awards 多次获奖**。

**3. jendrikllarena / Jendrik Illner**(jendrikillner.com)
- 图形学博客 + 每周精选链接。**保持对行业前沿的认知**。

**4. Eddie Lee / Recurse Center**(notes.eatonphil.com)
- 系统编程博客。**数据库 / 操作系统 / 编译器顶级资源**。

**5. Casey Muratori / Handmade Hero**(handmadehero.org)
- HH 之外,Casey 还有大量博客和视频。**直播的"问答环节"尤其有价值**。

### 论文 / 演讲(挑感兴趣的读)

**1. SIGGRAPH**(annually)
- 图形学顶级会议。每年有"Real-Time Live!"、"Courses"、"Advances in Real-Time Rendering"等环节,**游戏图形最前沿**。

**2. GDC**(annually)
- 游戏开发者大会。**业界顶级工程师分享实战经验**。GDC Vault 有免费演讲。

**3. GPU Gems**(developer.nvidia.com)
- NVIDIA 的 GPU 编程指南,3 本免费在线。**虽然老,但基础概念不过时**。

**4. Disney Principled BRDF**(Burley 2012)
- PBR 的奠基论文。**Phase 6 PBR 的源头**。

**5. Unreal Lumen**(Karis 2021)
- Unreal 5 的实时 GI 演讲。**Phase 8 GI 的工业级版**。

### 社区(参与)

**1. Handmade Hero Community**(handmade.network)
- Casey 社区的延伸。**讨论"从零开始"哲学、系统编程、独立游戏开发**。

**2. Bevy Discord**(bevyengine.org)
- Rust 旗舰游戏引擎的社区。**讨论 ECS、渲染、引擎架构**。

**3. r/rust_gamedev**(reddit.com)
- Rust 游戏开发 subreddit。**周报是行业动态的好来源**。

**4. Graphics Programming Discord**(discord.gg)
- 图形学社区。**讨论 shader、渲染、GPU 编程**。

**5. Lobste.rs**(lobste.rs)
- 系统编程社区。**深度技术讨论,质量比 Hacker News 高**。

### 工具链(持续关注)

**1. Rust**(rust-lang.org)
- 关注 annual roadmap、新版本特性。

**2. Bevy**(bevyengine.org)
- 关注 major release、设计讨论。

**3. wgpu / WebGPU**(wgpu.rs)
- 关注 WebGPU 标准演化。

**4. Tracy profiler / RenderDoc**(github)
- 关注新版本、新特性。

---

## 结语:写给毕业的你

你做到了 99% 的程序员做不到的事。667 天,从零到一个完整的游戏代码库。

但 HH 不是终点。HH 教的是"怎么学"。**毕业之后,真正的学习才开始**。

下面是我对毕业后的你的几条建议,来自 Casey 在 Day 667 直播里反复说的:

**1. 继续做项目,不要"学完就停"**。HH 教的能力,如果不持续用,半年就生疏。**毕业后第一个月,就开始下一个项目**。

**2. 开源贡献,建立 reputation**。开源是你"职业身份证"的一部分。**HR 不看你简历说"我会 Rust",看 GitHub**。Bevy / wgpu / Tracy / RenderDoc 都欢迎贡献。

**3. 找到同好,不要孤立**。HH 是孤独的旅程。毕业后找到社区(Handmade Network、Bevy Discord、图形学 Discord),和同好讨论、协作。

**4. 平衡生活,长期主义**。程序员职业是 30-40 年。HH 667 天是其中一段。**不要因为"刚毕业很有热情"就每天工作 14 小时**,会燃尽。**长期稳定 > 短期爆发**。

**5. 教别人,加深理解**。写博客、做视频、回答社区问题。**教别人是最高效的学习**——你能讲清楚,才证明你真懂。

**6. 不忘初心**。你为什么开始 HH?是因为对游戏 / 图形 / 系统编程的热爱。**毕业后无论选哪条路,别丢了这份热爱**。工作可以变,热爱不能丢。

**最后一句话**:**Casey 在 HH 末尾说,他做 HH 的目标不是教你怎么做一个游戏,是教你"怎么思考"**。如果你 667 天里学到了"怎么思考",你毕业了。剩下的路,你自己走。

下一站:**你自己定**。

---

> "The best way to predict the future is to invent it." — Alan Kay
>
> "The people who are crazy enough to think they can change the world are the ones who do." — Steve Jobs
>
> "Make it work, make it right, make it fast." — Kent Beck
>
> "If you can't explain it simply, you don't understand it well enough." — Albert Einstein
>
> "The most important property of a program is whether it accomplishes the intention of its user." — Carlo Pescio
>
> "Computer science is no more about computers than astronomy is about telescopes." — Edsger Dijkstra
>
> "There are only two hard things in Computer Science: cache invalidation and naming things." — Phil Karlton

带着 HH 教你的所有能力,去创造你自己的东西。
