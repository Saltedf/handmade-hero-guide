---
phase: 9
sequence: "9G"
module: 6
title_en: "Professional Readiness Checklist"
title_zh: "专业就绪自检总清单:你能不能,现在、独立地,交付一款专业游戏"
type: deep-dive
difficulty: 3
duration: "2-3 小时"
domains: [game, engineering, graphics, audio, systems, physics, animation, gameplay, ai, ui, production, process, self-assessment]
prereqs: ["09G-5-gold-and-post-launch"]
calibration: "对照 Gregory《GEA》章目 + 本教程 9 轨道能力地图的专业就绪自检总清单"
---

# 09G-6 · 专业就绪自检总清单

## 0 · 走完了 9A 到 9G,然后呢

你刚走完 [09G-5](09G-5-gold-and-post-launch.md)。母版制作、上架、首日补丁、live-ops 闭环——你全都读过了,有的还在自己的 HH 项目里动手做过一遍。从 [09G-1 预制作与可玩原型](09G-1-preproduction-and-prototype.md)的"找到好玩",到 [09G-2 垂直切片](09G-2-vertical-slice.md)的"证明整条管线跑得通",到 [09G-3 Alpha、Beta 与内容量产管线](09G-3-alpha-beta-and-content-pipeline.md)的"从一段到整部",到 9G-4 认证与 TRC,再到 9G-5 母版与上架——整个 9G 序列讲完了"从点子到上架"的全流程。再往前数,[9A 测试与 QA](09A-1-testable-game-architecture.md) 给了你测试纪律,[9B 引擎架构](09B-1-game-loop-and-timestep.md) 给了你 game loop / frame graph / dev console,[9C Vulkan](09C-1-gpu-architecture-and-explicit-api.md) 给了你现代 GPU API,[9D GPU 调试](09D-gpu-debugging-toolchain.md) 给了你 RenderDoc,[9E 网络后端](09E-1-reliable-udp-transport.md) 给了你权威服务器与 matchmaking,[9F 构建 / 发布工程](09F-1-ci-cd-and-build-engineering.md) 给了你 CI 与可复现构建。Phase 9 的 30 个 module,你基本都过了一遍。

现在问你一个最朴素、最不好回答的问题:**你能不能,现在,独立地,交付一款专业水准的游戏?**

诚实地说,这个问题你不能用"感觉差不多"、"我觉得我懂了"、"Casey 和 Gregory 我都看过了"来回答。这些话没有信息量——它们是模糊的、自欺的、不可审计的。一个真正的职业游戏工程师,会用一个非常具体的形式来回答这个问题:**一份自检清单(professional readiness checklist)**。它把"专业就绪"这个词,拆解成几十个可观测、可勾选、可复盘的具体能力点。你勾的每一项都是"我真的能在项目里独立做到这一点",没勾的每一项都是"我下一个季度的工作"。

这一篇就是那份清单。它不是又一篇技术讲解,它是 9G 序列的收口,也是 Phase 9、甚至整个 Handmade Hero 综合教程的"毕业答辩"。我把 README 的 [能力地图 / 毕业自检](../README.md#专业能力地图毕业自检) 那张表,从"一个 phase 学完之后的勾选"扩展成"我现在到底是不是一个专业游戏工程师"的终审。我会一条轨道一条轨道地走,先把"什么算就绪"用散文讲透,再给出可勾选的条目。**这不是一份自夸的纸,是一面照妖镜**——你越诚实,它越有用。

## 1 · 为什么要用清单:高负荷下,记忆会撒谎

在讲具体内容之前,我得先把"为什么清单本身有意义"这件事讲清楚,因为很多人(尤其是技术自信的程序员)对清单有天然抵触——觉得"我自己心里清楚我会什么,为什么要走这种官僚流程"。这种抵触本身就是你需要清单的证据,我会讲清楚为什么。

看一个看似无关的领域。现代航空业有一个被反复研究的发现:**经验丰富的飞行员,在紧急情况下,仍然会忘记极其基本的操作步骤**。引擎起火,机长脑子里清楚"应该切断燃油、调整俯仰、找最近的跑道",但压力、疲劳、肾上腺素之下,他会漏掉某一步——而漏掉的这一步,在事后看是不可理解的:"他明明知道啊,他飞了二十年"。航空业对这个问题的回应不是"训练更多的经验"——经验已经满了。它的回应是 **checklist(清单)**:起飞前、巡航、紧急情况,每一项都有一个清单,机长和副机长一起念、一起勾。外科手术、核电运维、麻醉管理,这些"出错的代价不可承受"的领域,全部用清单。Atul Gawande 的《The Checklist Manifesto》把这件事讲透了:**清单不是为了教外行,是为了防止专家在高负荷下漏掉已知的东西**。

游戏开发不是开飞机,出错不会死人。但游戏开发有一个和航空相似的核心特征:**它是高负荷、长周期、多系统并行的认知任务,而出错的代价(项目烂尾、上架延期、上架后崩、差评雪崩)虽然不致命,却足以毁掉职业生涯**。在这种任务里,人的判断会系统性地失真——你会高估自己已经掌握的东西("Vulkan 我看完了 9C 八个 module,我肯定能写"),你会低估自己忽略的东西("frame graph 我大概知道是干嘛的,应该没问题"),你会因为"已经投入这么多了"而拒绝承认某条轨道真的没准备好。这些失真不是道德问题,是认知偏差,而认知偏差在高负荷下会放大。**清单是外部化的认知**——它把"什么算 ready"这个判断,从你脑子里搬到纸上,让你没法对自己打太极。

这就是为什么这一篇的形式就是清单。不是因为我懒得写散文,而是因为**清单是这个场景下唯一诚实的工具**。下面每一节,我会先用散文讲"这条轨道上的'就绪'长什么样、为什么这些条目是就绪的标准",然后给你一组 `- [ ]` 条目。你要做的不是"读完觉得有道理",而是**真的打开你的 HH 项目,对照每一条,问自己'我在我的项目里做到这一点了吗',然后诚实勾选**。勾完之后,你的未勾选项,就是你下一个季度的个人 roadmap。

## 2 · T1 实时图形与渲染:能不能独立 ship 一个渲染器

第一条轨道,也是 Handmade Hero 综合教程投入最重的轨道——实时图形。能力地图里这一条横跨 phase-3(软件光栅化)、phase-5(OpenGL 迁移)、phase-6(深度缓冲 / 光照 / PBR)、phase-7(glTF / 法线贴图)、phase-8(tiled deferred),一直到 Phase 9 的 [9C Vulkan 八讲](09C-1-gpu-architecture-and-explicit-api.md) 和 [9D GPU 调试](09D-gpu-debugging-toolchain.md),以及图形顶端的 deep-dive。就绪不是"我看过这些文章",就绪是**你能独立地把一个渲染器从需求到 ship 全程走完,而且能在它出 bug 的时候调试出来**。

什么叫"独立 ship 一个渲染器"?拆开看。第一层是**算法层**——投影、深度、纹理采样、Phong / Blinn-Phong、PBR 的 BRDF、法线贴图、shadow map,这些你不仅"知道公式",还能在白板上推导,还能解释为什么是这么推的。phase-3 和 phase-6 走完之后,这一层你应该扎实。但光有算法层不叫就绪,因为算法要落到硬件上。第二层是 **API 层**——你能不能在 Vulkan 这种显式 API 上,从 instance / device / swapchain 一路搭到能画一个带纹理、带深度、带 uniform 的 mesh?[9C 的八个 module](09C-4-graphics-pipeline-first-triangle.md) 走完之后,你应该至少能跑通 HH 的一个 pass。就绪的标准不是"我跟过 tutorial",是"给我一个新的渲染需求(比如加一个后处理 bloom),我能从需求分析、pipeline 设计、descriptor 布局、sync 安排,独立实现到能跑"。第三层是**调试层**——渲染出了 bug(画面是黑的、mesh 没出现、深度 fighting),你能不能用 RenderDoc / PIX / Nsight 抓一帧、逐 draw call 看下去、定位到是 vertex shader 算错、还是 descriptor 没绑定、还是 sync 没排对?这是 [9D](09D-gpu-debugging-toolchain.md) 的核心。一个"会写 shader 但不会用 RenderDoc"的人,在真实项目里是 ship 不出去的——因为他遇到 bug 会卡死。

第四层,是更高阶的**工程化层**:frame graph([9B-3](09B-3-frame-graph.md))——能不能把渲染 pass 编排成一个声明式的图,自动推导屏障、自动管理 transient 资源?能不能做现代渲染技术(deferred / clustered / TAA / GI),而不只是 forward rendering?这些是图形顶端的 deep-dive。一个就绪的图形工程师,具备前三层是底线,具备第四层是竞争力。

下面这组勾选项,问的就是这四层。

- [ ] 我能在白板上推导透视投影矩阵、深度缓冲的精度特性、Phong 与 Blinn-Phong 的差别,以及 PBR 中 diffuse + specular 的能量守恒
- [ ] 我用 Vulkan(或同等显式 API)从 instance 起步,独立搭出一条能渲染带纹理 mesh 的 graphics pipeline,并能解释每一步(instance / physical device / queue family / command pool / swapchain / render pass / pipeline / descriptor)为什么存在
- [ ] 我能在 Vulkan 里正确处理同步(semaphore / fence / pipeline barrier / image layout transition),能解释为什么"没排对"会变成 race condition 或 validation error
- [ ] 给我一个新的渲染需求(例如加后处理 bloom、加 shadow map、加 clustered forward),我能独立从设计到实现做到能跑,不依赖教程手把手
- [ ] 渲染出了 bug,我能熟练用 RenderDoc(或 PIX / Nsight)抓帧、逐 draw call / 逐 shader 检查、定位根因——而不是靠 printf 或瞎试
- [ ] 我理解 frame graph 的概念,能在我的引擎里用声明式方式编排多 pass 渲染,并自动推导资源和屏障

## 3 · T2 数字音频与 DSP:能不能把声音做到"专业品质"

第二条轨道,音频。能力地图里它从 phase-0 的数学基础,经过 phase-4 / 5 / 7 的音频实战,再到 Phase 5 的音频深度序列(DSP 基础、合成与乐器、音频效果、FFT 与频谱分析、自适应音频与 3D)。Handmade Hero 本身对音频的覆盖相对轻(Casey 只做了一个简单的混音器和波形播放),所以这条轨道的深度主要来自 deep-dive。

音频的"就绪"和图形的"就绪"在结构上很像,也是分层的。底层是 **DSP 基础**——你能不能用代码实现一个 IIR / FIR 滤波器?能不能解释卷积、z 变换、 Nyquist 采样定理、走样(aliasing)为什么会发生?这一层不扎实,后面的合成、效果、混响都是空中楼阁。第二层是**合成与采样**——能不能从波形出发合成一个音色(减性合成、FM、加性)、能不能做物理建模合成(弦、管的偏微分方程离散化)、能不能写一个简单的软合成器(software synth)?这是 phase-5 的合成序列。第三层是**效果与空间**——能不能实现混响(卷积混响或反馈延迟网络)、压缩、失真、合唱、flanger?能不能做 3D 空间化(HRTF、距离衰减、声障遮挡)?能不能做**自适应音频**(根据游戏状态动态切换音乐层、战斗时叠 layer、潜行时降 layer)?这是从 phase-5 自适应音频到 phase-7 自适应音乐系统。第四层是**编解码与运行时**——能不能实现或正确使用 ADPCM、Opus、Vorbis 解码?能不能做一个不阻塞游戏循环的流式音频系统(streaming audio,而不是一次性加载)?这一层决定你游戏的内存占用和加载速度。

就绪的总体感觉是:**给你一段游戏片段(例如"玩家进入洞穴,从外面下雨的环境过渡到洞穴内回响的脚步声"),你能独立把这段音频体验从需求拆到实现**——选什么音色、怎么合成或采样、加什么效果、怎么做空间化、怎么和游戏状态联动、怎么不卡帧。下面这组条目问的就是这件事。

- [ ] 我能用代码实现一个低通 / 高通 / 带通滤波器(IIR / FIR),并解释截止频率、相位、稳定性
- [ ] 我理解采样定理与走样,知道为什么音频要抗混叠滤波、为什么要过采样
- [ ] 我能从波形出发合成一个有质感的音色(减性、FM、或物理建模至少一种),并能把它做成一个能被 MIDI / 游戏事件触发的软合成器
- [ ] 我能实现至少一种空间化效果(立体声 pan、HRTF、或简单的距离衰减 + 声障),并解释 HRTF 与简单 pan 的差别
- [ ] 我能实现卷积混响或反馈延迟网络混响,并能解释冲激响应(impulse response)是什么、为什么卷积能产生混响
- [ ] 我能做一个自适应音频系统:游戏状态(战斗 / 探索 / 潜行)切换时,音乐 layer 平滑过渡,听不到突变
- [ ] 我理解流式音频的工程约束,我的音频系统不会因为解码阻塞游戏循环导致掉帧

## 4 · T3 系统编程:内存、并发、IO 是不是真的在掌控之中

第三条轨道,系统编程。这条轨道是 Handmade Hero 的"造轮子精神"最集中的体现——phase-0 给你地基(终端、shell、文件系统、进程),phase-1 给你平台层(开窗、读输入、播音频、热重载),phase-4 给你性能 / 线程 / 资产(SIMD、Arena、压缩、构建系统),phase-5 给你 debug 系统。然后是系统深度序列把虚拟内存、异步 IO、动态链接、调度、读内核源码这些"顶端"补上。

系统的就绪,问的是一个非常具体的事:**当你的游戏出现性能问题、内存问题、奇怪的崩溃、跨平台兼容问题时,你能不能下钻到底层找到原因?** 一个"会用 cargo build 但不知道链接器在干什么"的工程师,在 HH 的语境里不算就绪——因为 HH 的整个精神就是"从晶体管到 shader 你都能下钻"。具体到子能力。**内存**方面:你能不能写一个 Arena / pool / free list 分配器,知道为什么游戏要用自定义分配器而不是 system malloc?能不能解释 cache locality、false sharing、alignment 对帧率的影响?能不能用 valgrind / AddressSanitizer 找到内存错误?**并发**方面:你能不能写一个线程池 / 工作窃取调度器,知道 mutex / RwLock / atomic / channel 各自的代价?能不能避免数据竞争和死锁,能不能解释 memory ordering(Acquire / Release / SeqCst)?能不能把游戏循环里的并行任务(rayon 的 par_iter 背后是什么)调度到所有核上?**IO**方面:能不能实现异步 IO(io_uring / epoll / tokio),让资产加载不卡主线程?能不能解释虚拟内存、page fault、mmap 为什么能用来做"零拷贝"资产加载?**可观测性**方面:能不能用 perf / flamegraph / Tracy 看到 60FPS 帧里每一毫秒花在哪、哪个函数是热点?

就绪的总体感觉:**你的游戏的每一毫秒、每一个字节、每一次系统调用,你都能解释**。这不是夸张,这是 phase-4 / phase-5 / phase-8 的工程现实——Casey 反复强调的"知道你的游戏在做什么"。

- [ ] 我能在我的项目里实现 Arena / pool / free list 至少一种自定义分配器,并解释它相对 system malloc 的优势
- [ ] 我能用 perf / flamegraph / Tracy 定位一个帧率热点,解释某毫秒花在哪个函数上,并据此优化
- [ ] 我理解 cache locality、false sharing、alignment 对性能的影响,能在代码里主动用这些原理
- [ ] 我能写一个线程池或工作窃取调度器,理解 mutex / RwLock / atomic / channel 的代价与适用场景
- [ ] 我理解 Rust 的 Acquire / Release / SeqCst memory ordering,能解释为什么"用错了"是数据竞争
- [ ] 我能用 AddressSanitizer / valgrind / Miri 定位内存错误和数据竞争
- [ ] 我理解虚拟内存、page fault、mmap,能用 mmap 做零拷贝资产加载或解释为什么 io_uring 能加速 IO

## 5 · T4 物理与动画:刚体、约束、骨骼、IK 是不是站得住

第四条轨道,物理与动画。能力地图里这条从 phase-2 的 2D 碰撞、phase-3 的 3D 基础、phase-4 的性能优化、phase-8 的碰撞重构(体素),到 T4 顶端的 deep-dive(刚体动力学完整、柔体布料流体、骨骼动画基础、动画混合与状态机、几何处理、角色控制器)。

这条轨道的就绪,问的是:**你能不能不依赖现成物理引擎(PhysX / Rapier / Box2D),独立实现游戏需要的物理和动画系统,并且知道它们的数学和数值方法?** 注意"不依赖现成引擎"是 HH 的精神——不是说职业游戏开发真要自己写物理引擎(Naughty Dog 也用 Havok),而是说**你必须懂到底层,才能在现成引擎出问题时下钻、才能在游戏需要定制(角色控制器、布料、特殊约束)时不被卡住**。具体子能力:**刚体动力学**——能不能实现积分(显式 / 隐式 / 半隐式 Euler)、能不能解释为什么显式 Euler 在弹簧上会爆炸、能不能做碰撞检测(broadphase: AABB / sweep and prune / BVH;narrowphase: GJK / EPA / SAT)、能不能做约束求解(sequential impulse / position-based dynamics)、能不能做 island sleeping 让静止物体不消耗 CPU?**CCD 与稳定性**——高速运动物体会不会穿透?数值积分会不会能量泄漏让物体越弹越高?**骨骼动画**——能不能实现骨骼层级(skeleton hierarchy)、蒙皮(skinning,顶点受多骨骼权重)、动画混合(blend tree / 状态机)、IK(逆向运动学,两足 IK 让脚踩在不平地形上)?**角色控制器**——这是 game feel 的物理基础,能不能做一个"贴着地面走、上下坡不飞、被推不动、能跳能蹲"的胶囊控制器,而不是用刚体?

就绪的总体感觉:**游戏里凡是动的东西,从角色的脚到飘的旗子,你都能解释它在物理上发生了什么、能调它的参数、能修它的 bug**。

- [ ] 我能解释显式 / 隐式 / 半隐式 Euler 积分的差别,知道显式 Euler 在弹簧系统上为什么会爆炸
- [ ] 我能实现一个 2D 或 3D 碰撞检测(broadphase 至少一种 + narrowphase 的 SAT / GJK 至少一种),并能解释它们的复杂度
- [ ] 我能实现一个简单的约束求解器(sequential impulse 或 position-based dynamics),让堆叠的物体不抖、不穿透
- [ ] 我理解 CCD(连续碰撞检测)为什么能解决高速穿透,并在我的项目里对高速物体启用
- [ ] 我能实现骨骼层级与蒙皮,能加载一个 glTF 模型并在屏幕上播放它的动画
- [ ] 我能实现一个两足 IK,让角色的脚踩在不平地面上不悬空、不穿透
- [ ] 我能写一个角色控制器(胶囊 + 贴地 + 跳跃 + 蹲伏),手感对,而不是用刚体凑合

## 6 · T5 游戏性编程:手感、输入、状态、玩法系统是不是真的"好玩"

第五条轨道,游戏性编程。这是 Handmade Hero 667 天的天然 spine——phase-2 的实体 / 运动 / 碰撞 / AI,phase-5 的 debug overlay,phase-7 的关卡编辑器,phase-8 的碰撞重构,以及 T5 顶端的游戏手感 / 输入 / 状态机 / 事件系统 / 玩法系统 deep-dive。这条轨道的校准源是 CMU 15-466 + Swink《Game Feel》+ Nystrom《Game Programming Patterns》。

游戏性的就绪,是最难用清单量化的——因为"好玩"是主观的。但"好玩"背后的**工程能力**是可以量化的,清单查的就是这些工程能力。具体拆。**手感(game feel)**——你能不能解释 Swink 说的"游戏手感三要素"(输入响应、模拟、表达)?能不能实现 coyote time(离开平台后还有一小段时间能跳)、input buffering(提前按跳键落地后立即起跳)、acceleration / deceleration 曲线让移动"有重量"?这些是 phase-5 和 T5 顶端的核心内容。**输入**——能不能处理多种输入设备(键盘 / 手柄 / 触屏)、能不能做输入重映射(input remapping)、能不能在低帧率下保证输入响应不延迟(把输入采样从 update 拆出来)?**状态机与行为**——能不能写一个干净的有限状态机(FSM)或行为树(behavior tree),让角色在不同状态(idle / run / attack / hurt)之间切换不卡、不漏?能不能用 hierarchy state machine(分层状态机)处理"在地面上"和"在空中"两层?**事件与系统**——能不能做一个事件总线(event bus)/ 观察者模式,让"玩家死亡"事件触发音乐切换、UI 弹窗、存档、telemetry,而不用把死亡逻辑写成几百行 if-else?**ECS**——能不能用 ECS 架构组织你的实体,而不是用 inheritance hell(继承地狱)?这些 phase-2 / phase-5 / phase-8 都练过。

就绪的总体感觉:**给你一个"角色控制"的需求,你能从输入采样、到状态机、到手感曲线、到动画触发、到音效播放、到粒子反馈,完整地、不卡壳地实现出来,而且手感是对的**。

- [ ] 我能解释 Swink《Game Feel》的"输入响应 / 模拟 / 表达"三要素,并在我的角色控制里能看到这三层都在
- [ ] 我的角色控制实现了 coyote time、input buffering、加速度曲线,手感"有重量"而不是飘
- [ ] 我能处理多种输入设备(键盘 / 手柄至少两种),支持输入重映射
- [ ] 我能把输入采样从 update 循环里拆出来,保证低帧率下输入响应延迟最小
- [ ] 我能写一个干净的分层有限状态机或行为树,角色状态切换不卡、不漏、可调试
- [ ] 我能用事件总线 / 观察者模式解耦系统(死亡事件触发音乐 + UI + 存档 + telemetry,不死循环几百行 if-else)
- [ ] 我能解释 ECS 相对继承架构的优势,并在我的项目里用 ECS 组织实体

## 7 · T6 游戏 AI:感知、决策、寻路、群体是不是能撑起一个有挑战的游戏

第六条轨道,游戏 AI。能力地图里它是 T5 游戏性的子领域,主要承载在 phase-2 的 ai-patterns、phase-7 的 navmesh、以及 T6 AI 深度序列。校准源是 Millington《AI for Games》和 Rabin 的 GDC AI summits。

AI 的就绪,问的是:**你游戏里的 NPC,有没有让你觉得"它在做有意义的事"的智能,而不是机械地追你或卡住?** 具体子能力。**感知**——NPC 怎么"看见"玩家?视线检测(LOS, line of sight)、视野锥(FOV cone)、听觉范围(脚步声触发警觉)、记忆(上次看到玩家的位置,一段时间内还记得)?**决策**——状态机、行为树、效用系统(utility AI,根据多个需求打分选行为)、GOAP(Goal-Oriented Action Planning,给目标和可用动作,自己规划序列)?**寻路**——A* 在网格上(基础)、navmesh 导航网格(连续空间,phase-7)、路径平滑(steering behaviors,不要机械地走折线)、避障(群体里 NPC 之间不挤)?**群体协调**——flocking(鸟群 / 鱼群的行为)、编队(formation,士兵保持阵型移动)、群体战术(包抄、火力压制)?**调试**——AI 是最难调的,因为你不知道"NPC 为什么这么干"。能不能在游戏里画 AI 的感知范围、决策树、当前路径、记忆位置?这是 AI 调试 overlay 的核心。

就绪的总体感觉:**你游戏里的 NPC,有可信的感知、可解释的决策、流畅的移动、能调的难度,而不是"追着玩家撞墙"**。

- [ ] 我能实现 NPC 的感知系统:视线检测、视野锥、听觉范围、记忆(上次感知到的玩家位置会保留一段时间)
- [ ] 我能实现至少两种 AI 决策结构(有限状态机 / 行为树 / 效用系统),并能解释它们各自适合什么场景
- [ ] 我能在网格或 navmesh 上实现 A* 寻路,并解释 open list / closed list / 启发函数
- [ ] 我能实现路径平滑与 steering behaviors,让 NPC 移动自然而不是机械走折线
- [ ] 我能实现至少一种群体行为(flocking / 编队 / 群体战术)
- [ ] 我的 AI 系统有调试 overlay,能在游戏里看到 NPC 的感知范围、决策树状态、当前路径

## 8 · T7 游戏 UI 与交互:菜单、HUD、可访问性是不是专业品质

第七条轨道,游戏 UI。它是 T5 游戏性的另一个子领域,承载在 phase-5 的 debug UI、phase-7 的菜单 / HUD、以及 T7 UI 深度序列(布局引擎、响应式 UI、可访问性)。校准源是响应式 UI 思想 + WCAG 可访问性 + 数据驱动 UI。

UI 的就绪,问的是:**玩家从打开游戏到能玩、到能调选项、到能退出,这整个体验是不是流畅、专业、对所有人都友好?** 这条轨道在 indie 里被严重低估——很多 indie 游戏"核心好玩,但 UI 像 placeholder,选项菜单只有音量,色盲玩家看不清,手柄玩家无法到设置"。UI 不专业,整个游戏就感觉不专业。具体子能力。**架构**——你能不能写一个数据驱动的 UI 系统(UI 元素从数据 / 脚本生成,而不是硬编码)?immediate-mode(GUI 每帧重新声明)还是 retained-mode(状态持久化)?两者各有什么代价?**布局**——你能不能实现一个简单的 flexbox / grid 布局引擎,让 UI 在不同分辨率 / 长宽比下自适应?你的 UI 在 16:9、21:9、4:3 上都对吗?**输入**——UI 既能用鼠标点,也能用手柄 / 键盘导航吗?这是 cert([9G-4](09G-4-certification-and-trc.md) 假设)的硬性 TRC 要求(手柄必须能从启动到主菜单全程导航)。**可访问性**——色盲模式(改调色板)、字幕(对话必须有字幕)、字体大小可调、按键重映射、减少动效(reduce motion,前庭敏感玩家)、色彩对比度达标(WCAG AA / AAA)?可访问性不是"nice to have",是 ship 时必须考虑的,部分平台 TRC 把它列为强制项。**本地化**——UI 文本能不能在不改代码的前提下切换语言?文本长度在德语(长)和中文(短)之间差很多,UI 能不能自适应?

就绪的总体感觉:**任意一个玩家,包括色盲、用 手柄、不说英语的玩家,都能从启动到玩到退出全程顺畅**。

- [ ] 我能实现一个数据驱动的 UI 系统,UI 元素从数据 / 脚本生成,而不是硬编码在代码里
- [ ] 我的 UI 在多种长宽比(16:9、21:9、4:3)和分辨率下自适应,不错位
- [ ] 我的 UI 全程支持手柄 / 键盘 / 鼠标三种输入,手柄能从启动画面导航到主菜单、设置、开始游戏(满足 TRC)
- [ ] 我的游戏有色盲模式(至少三种:红绿、蓝黄、全色盲)和对话字幕
- [ ] 我的 UI 字体大小可调,色彩对比度达到 WCAG AA
- [ ] 我的游戏支持至少两种语言,UI 文本从外部数据加载,切换语言不需要改代码

## 9 · T8 工程与引擎架构:测试、CI、引擎分层是不是工业级

第八条轨道,工程与引擎架构。这是 Phase 9 的核心补层——[9A 测试与 QA](09A-1-testable-game-architecture.md) 四讲,[9B 引擎架构](09B-1-game-loop-and-timestep.md) 四讲,对标 Gregory《Game Engine Architecture》全章目。这条轨道的就绪,是把"游戏能跑"变成"游戏是工程化产品"的鸿沟。

工程的就绪,问的是三件事:**测试、引擎架构、构建发布**。**测试**——你能不能给任何游戏系统写单元测试?能不能写 property test(对一组随机输入,某个不变量总成立)?snapshot test(渲染输出和上次一样,没回归)?fuzz test(随机数据喂进解析器,不 panic)?你的项目有 CI([09F-1](09F-1-ci-cd-and-build-engineering.md))守护,每次 push 自动跑测试、跑 cook、跑 lint,red build 不进 main 吗?[9A-4 fuzz 与确定性回归](09A-4-fuzz-determinism-and-regression.md) 给了你完整测试网的最小骨架。**引擎架构**——你的 game loop 是固定步长(fixed timestep)还是可变步长([09B-1](09B-1-game-loop-and-timestep.md))?你的子系统(渲染、音频、物理、游戏逻辑)是分层还是 monolithic?能不能做插件([09B-2](09B-2-subsystems-modules-plugins.md))让 modder 扩展?有没有 frame graph([09B-3](09B-3-frame-graph.md))声明式编排渲染 pass?有没有 CVars / dev console([09B-4](09B-4-cvars-and-dev-console.md))让你运行时调参不用重编?这些都是"职业引擎"和"一个 main 循环"的差别。**构建发布**——一条命令产出多平台可复现构建吗?有崩溃上报吗?有 telemetry 吗?这些在 [09F](09F-2-release-engineering-and-live-ops.md) 走过。

这条轨道还有一个独有的维度——**Gregory《GEA》章目覆盖**。Gregory 的《Game Engine Architecture》是 Naughty Dog 主程写的引擎子系统圣经,它的章目本身就是"引擎工程师能力地图"。我把它在本教程的覆盖列出来,你可以一一对照(下一节细讲)。就绪的总体感觉:**你的代码库有测试网守护、有清晰的子系统分层、有运行时调试工具、有一键构建发布——它"看起来像一个引擎",而不是"一堆 main"**。

- [ ] 我的游戏项目有 CI(或同等自动化),每次 push 自动跑测试 / cook / lint,失败 build 不进 main
- [ ] 我能给任何游戏系统写单元测试,关键系统还有 property test 或 snapshot test
- [ ] 我的关键解析器(存档 / 资产 / 网络协议)有 fuzz test,不会因为畸形输入 panic
- [ ] 我的 game loop 是固定步长,物理 / 模拟确定,渲染解耦([09B-1](09B-1-game-loop-and-timestep.md))
- [ ] 我的引擎有清晰的子系统分层,能做插件扩展,不是 monolithic main
- [ ] 我的引擎有 dev console / CVars,运行时能调参、能开关 debug overlay,不重编
- [ ] 我能用一条命令产出 Windows + Linux 可复现构建,带崩溃上报和 telemetry([09F-1](09F-1-ci-cd-and-build-engineering.md) / [09F-2](09F-2-release-engineering-and-live-ops.md))

## 10 · Gregory《GEA》章目覆盖:引擎子系统的横向审计

上一节的 T8 主要查"工程纪律",这一节我专门做一次 **Gregory《Game Engine Architecture》章目级覆盖**——这是对引擎子系统知识广度的横向审计,因为 Gregory 这本书的章目结构本身就是"一个引擎工程师需要知道什么"的事实标准。我假设你读过它(或在 [bridge-to-phase-9](bridge-to-phase-9.md) / [Phase 9 README](README.md) 知道它是 9B 的校准源)。下面把它的主要部分(part)对照本教程的覆盖, narrate 一遍,你可以一项一项自查。

**Part I 基础(Foundation)**——为什么需要游戏引擎、工具链、软件工程基础、SDK、CFG。这部分对应 phase-0 / phase-4 的工程地基,以及 [9F-1 CI / CD](09F-1-ci-cd-and-build-engineering.md) 的工具链。就绪:你理解为什么"引擎"是独立于"游戏"的一层,你的工具链(cargo / CI / cooker)是工业级的。

**Part II 引擎架构(Engine Architecture)**——game loop、timestep、子系统分层、内存管理、容器、配置。对应 [9B-1 game loop 与 timestep](09B-1-game-loop-and-timestep.md)、[9B-2 子系统 / 模块 / 插件](09B-2-subsystems-modules-plugins.md)、[9B-4 CVars / dev console](09B-4-cvars-and-dev-console.md),以及 phase-4 的 Arena / SIMD / cache、phase-5 的容器与配置。就绪:你的引擎有清晰的 loop 模型、子系统分层、内存策略、配置系统。

**Part III 并发(Concurrency)**——线程、job system、SIMD、lock-free 数据结构。对应 phase-4 的多线程与 SIMD,以及 [9B-2](09B-2-subsystems-modules-plugins.md) 的 job 调度,和 T3 系统深度序列里的并发内容。就绪:你能把游戏循环里的并行任务调度到所有核,SIMD 用在热点上,无锁结构用在正确的地方。

**Part IV 数学与支撑系统(Math and Support Systems)**——线性代数、几何、随机数、RTTI / 反射、序列化、CRC / 哈希。对应 phase-0 的数学基础、phase-7 的序列化(savegame)、phase-8 的存档版本演化([09F-2](09F-2-release-engineering-and-live-ops.md))。就绪:你理解引擎为什么需要反射(运行时知道字段名 / 类型,做编辑器、序列化、网络同步),能实现或正确使用序列化框架。

**Part V 资源管理(Resource Management)**——资源数据库、GUID、引用计数、cooking、热加载。对应 phase-7 的资产管线架构、phase-9 [09G-3](09G-3-alpha-beta-and-content-pipeline.md) 的 cook + hot reload。就绪:你的资产有 GUID、有引用计数、有 cook 管线、有 hot reload——这是 [09G-3](09G-3-alpha-beta-and-content-pipeline.md) §3 的核心骨架。

**Part VI 人类接口设备(Human Interface Devices)**——键盘、鼠标、手柄、触摸、输入缓冲。对应 phase-1 的输入层、phase-5 的输入采样,以及 T5 游戏性顶端关于"输入响应不延迟"的讨论。就绪:你的输入系统能处理多设备、做重映射、在低帧率下不延迟。

**Part VII 调试与性能分析(Debugging and Profiling)**——日志、断言、profiling、stats overlay。对应 phase-5 的 debug overlay、[09D GPU 调试](09D-gpu-debugging-toolchain.md),以及 T3 的 perf / Tracy。就绪:你有运行时 profiling 工具、有日志 / 断言、能调试 GPU 和 CPU 两边。

**Part VIII 渲染(Rendering)**——管线、shader、光照、材质、后处理。对应 phase-3 / 5 / 6 / 7 / 8 全部图形内容,[9C Vulkan](09C-1-gpu-architecture-and-explicit-api.md),以及图形顶端 deep-dive(deferred / clustered / TAA / GI / GPU compute / post-processing)。就绪:见 T1,你不仅会写渲染器,还能 debug 它。

**Part IX 动画(Animation)**——骨骼、蒙皮、blend tree、IK、压缩。对应 T4 顶端的骨骼动画基础、动画混合与状态机、几何处理。就绪:见 T4,你能从 glTF 加载骨骼、做蒙皮、做 blend、做 IK。

**Part X 碰撞与物理(Collision and Rigid Body Dynamics)**——broadphase、narrowphase、求解器、island。对应 phase-2 / 3 / 8 的碰撞,T4 顶端的物理引擎完整 deep-dive。就绪:见 T4。

**Part XI 音频(Audio)**——音频引擎、混音、空间化。对应 T2 的 DSP / 合成 / 效果 / 空间 / 自适应。就绪:见 T2。

**Part XII 游戏性基础(Gameplay Foundations)**——game object model、ECS、事件、脚本、对象引用、调度。对应 T5 的 ECS / 事件总线 / 状态机,phase-2 / 5 / 7 / 8 的玩法系统。就绪:你的玩法系统不是 inheritance hell,是 ECS 或类似的扁平组件模型。

**Part XIII 实时事件(Some Real-World Systems)**——案例分析。这一部分是引擎综合案例,本教程对应的"案例"就是你 HH 项目本身——你的引擎长什么样,就是这一部分的实操答案。

走完这一节,你对照 Gregory 的每一部分(part),都应该能指着自己的项目说"这一部分在我的代码里有对应实现"。任何指不出来的部分,就是你下次回炉的入口。**这不是要你逐章背 Gregory,而是说一个职业引擎工程师,这些 part 在脑子里有清晰的地图,缺哪块补哪块**。

## 11 · T9 制作与交付:能不能走完全流程,从点子到上架

第九条轨道,也是 9G 序列本身,制作与交付。校准源是行业制作阶段(原型 → 垂直切片 → alpha → beta → cert → gold → live)。这条轨道的就绪,问的是最综合的问题:**给你一个全新的游戏点子和若干时间,你能不能独立走完全流程,把它 ship 出去?**

这条轨道的就绪,是前面八条轨道的**综合应用**——你要同时调用图形 / 音频 / 系统 / 物理 / 动画 / 游戏性 / AI / UI / 工程,把它们组织成一个能 ship 的产品。能力地图上这条最初是 🔴 完全缺,Phase 9 的 9G + capstone 把它补上。具体子能力按制作阶段拆:**预制作**——能不能找到好玩([09G-1](09G-1-preproduction-and-prototype.md)),用最便宜的方式验证核心机制,而不是直接开始建最终成品?**垂直切片**——能不能做一段最终品质的内容,证明整条管线跑得通([09G-2](09G-2-vertical-slice.md))?**Alpha / Beta / 量产**——能不能在量产阶段守住"feature freeze / content freeze",对抗 feature creep 和完美主义?能不能做内容管线([09G-3](09G-3-alpha-beta-and-content-pipeline.md))?**Cert**——能不能读懂 TRC / TCR 清单,把合规检查提前到 production 阶段(9G-4)?**Gold**——能不能制作母版,跑通 release candidate 循环?**上架与 live-ops**——能不能在发售后第一时间响应崩溃,做 patch、telemetry 到 action 的闭环([09G-5](09G-5-gold-and-post-launch.md))?

就绪的总体感觉:**你不只是会写游戏代码,你知道"做完一款游戏"这件事的全流程纪律,能在每个阶段切换到正确的纪律,而不是用原型阶段的心态去做 Beta 阶段的活**。

- [ ] 我能在开始 production 之前,用灰盒原型验证核心机制是否好玩,而不是直接建最终成品([09G-1](09G-1-preproduction-and-prototype.md))
- [ ] 我能做一段最终品质的垂直切片,证明整条管线从资产到打包到目标硬件跑得通([09G-2](09G-2-vertical-slice.md))
- [ ] 我能在 Alpha 阶段冻结 feature list,对抗 feature creep,任何新 feature 走 change request 流程
- [ ] 我能在 Beta 阶段切换到"修复者"心态,做 bug triage(severity × priority),接受 known shippables ship([09G-3](09G-3-alpha-beta-and-content-pipeline.md))
- [ ] 我有内容管线:增量 cook + hot reload + 多核 + CI 验证,迭代速度足以支撑量产
- [ ] 我读懂至少一份平台的 TRC / TCR 清单,把合规检查持续验证(9G-4)
- [ ] 我能制作 release candidate,跑通 cert → 修 → RC 循环,达到 gold([09G-5](09G-5-gold-and-post-launch.md))
- [ ] 我有 live-ops 基础设施:崩溃上报、telemetry 到 action 闭环,能在发售后 24 小时内定位并修复线上火灾([09F-2](09F-2-release-engineering-and-live-ops.md))

## 12 · 两个目的地的合流:就绪 = 同时是开源极客 + 职业工程师

走到这儿,把九条轨道的勾选都摆出来了。但我要把视角拉回到 README 的 [两个目的地](../README.md#北斗星两个目的地)——因为就绪不是任何单一轨道的达标,而是**两个目的地的合流**。

**目的地 1:发布一个商业品质的开源游戏(Phase 0-8,跟 Handmade Hero 667 天)。** Casey 教会你从零造一个游戏。完成这 667 天后,你能从零用 Rust 写一个完整的游戏(2D / 3D / 音频 / 软渲染 + OpenGL),读懂 Casey 原版 C + Rust 翻译 + Linux 内核源码 + OpenGL spec,贡献 Rust 生态主流 crate,设计自定义内存分配器 / 线程池 / 渲染管线 / shader 系统,用 perf / valgrind / gdb / flamegraph 定位任何性能问题,理解从晶体管到 shader 的完整链路。这个目的地的就绪,主要查 T1 / T2 / T3 / T4 / T5——造轮子的能力。

**目的地 2:成为职业游戏工程师,独立交付一款专业水准游戏(Phase 9)。** Phase 9 教你把它做成产品。完成 Phase 9 后,你能给任何游戏系统写单元 / property / snapshot / fuzz 测试搭 CI 守护,设计 game loop / timestep / frame graph / 子系统分层 / CVars / dev console,用 Vulkan 从零搭渲染,搭权威服务器 / matchmaking / NAT / relay / 复制裁剪,做交叉编译 / 可复现构建 / 崩溃上报 / 多平台打包,走完预制作 → 垂直切片 → 认证 → 上架,**独立交付一款专业水准游戏**。这个目的地的就绪,主要查 T6 / T7 / T8 / T9——工程纪律和交付能力。

Casey 教会你从零造一个游戏。Phase 9 教你把它做成产品。**两者都要。** README 那句"两个目的地合起来才完整",在就绪检查上落成非常具体的一句话:**就绪 = 你同时具备"造轮子的开源极客能力"和"做成产品的职业工程师能力"**。任何一个目的地缺位,都不是真就绪。只有目的地 1 没 2,你是一个能造引擎但 ship 不出产品的极客,在 indie 角色上会卡在"完成了 80% 然后烂尾"(这恰恰是 HH 本身的命运);只有目的地 2 没 1,你是一个会用现成引擎和库做产品、但底层出问题就抓瞎的"调库工程师",这正是 README 反复警告你要避免的反面形象。两个目的地合流,你才是一个真正完整的、独立的专业游戏工程师。

走这一节,我希望你回头看 §2-§11 的所有勾选项,带着这个合流的视角重新审视一遍:**我哪些条目是"目的地 1"(造轮子),哪些是"目的地 2"(做成产品)?两边都齐了吗?** 大多数学习者会发现目的地 1 比 2 强(因为 667 天的体量都在 1),或反过来(从工程背景进来的学习者)。看见这个不平衡,就是这一节的价值。

## 13 · 9G 序列收口:从"找到好玩"到"能独立 ship"

做完这一份自检,9G 序列也走到了它的收口。让我把这条序列的整体形状讲清楚,方便你定位自己在哪。

9G 一共六个 module,讲的是一个完整的故事:**怎么做一款游戏,从点子到上架**。[9G-1 预制作与可玩原型](09G-1-preproduction-and-prototype.md) 回答"这个游戏到底值不值得做",用最便宜的方式找到好玩、消除最大风险。[09G-2 垂直切片](09G-2-vertical-slice.md) 回答"我能不能把核心 fun 通过整条管线以最终品质做出来",用一段最终品质的内容证明整条管线跑得通。[09G-3 Alpha、Beta 与内容量产管线](09G-3-alpha-beta-and-content-pipeline.md) 回答"我能不能把一段切片放大成整款游戏",讲清 Alpha(feature complete)和 Beta(content complete)的纪律转变、内容管线速度、bug triage、playtest 与 telemetry。9G-4 认证与 TRC 回答"平台方认为'做完'是什么标准",让你把合规检查提前到 production 而不是 cert 阶段才发现。[09G-5 母版与上架](09G-5-gold-and-post-launch.md) 回答"release candidate 怎么过 cert、母版怎么制作、上架那天会发生什么",以及售后 live-ops 的第一周。然后是这一篇,9G-6,不再讲新流程,而是**让你停下来,对照整条 9G 和整个 Phase 9,问自己"我真的就绪了吗"**。

这条序列的核心 take-away 不是任何具体技术,是**"在正确时刻切换纪律"的感知能力**——预制作阶段舍得扔,切片阶段舍得提前打磨,Alpha 阶段冻结 feature,Beta 阶段切换到修复者,cert 阶段服从清单,gold 阶段果断 ship,live-ops 阶段第一时间响应。这种感知能力是职业制作人和 indie 烂尾者的本质差距。Casey 的 Handmade Hero 烂尾,烂就烂在它没走这条序列——它停留在"原型阶段"好几年,既没有切片冻结,也没有量产纪律,最后草草收尾。9G 这条序列就是补这一层,讲完它,你拥有了 Casey 没交付的"上架层"。

## 14 · Phase 9 / 全教程收口:从变量循环到独立交付

再把视角拉远一档。9G 是 Phase 9 的最后一序列,Phase 9 是整个 Handmade Hero 综合教程的最后一个 phase。这一篇 9G-6 是 Phase 9 的收口之一(另一个收口是 capstone),所以它也是整个教程的"毕业自检"。

让我把整个教程的弧线讲一遍,因为走到这一步的人值得停下来看一眼来路。你从 [phase-0 起步营](../phase-0/00-terminal-basics.md) 开始——那时你只会变量、循环、条件、函数,不会 Rust、不会 Linux、不会图形学、不会游戏开发。Phase 0 的 16 篇文章手把手把你拉到能跟 Phase 1:终端 / shell / vim、Arch Linux、Git / GitHub PR、Rust 从零、文件系统 / 进程 / 信号、编辑器工具链、数学基础、读 C 和汇编。然后 Phase 1 的 25 天,Casey 把 Win32 翻译成 winit + softbuffer + cpal + gilrs + libloading,你搭起了平台层——开窗、显示像素、读输入、播音频、热重载。Phase 2 的 45 天,你做了第一个真游戏:实体、运动、碰撞、AI、资产。Phase 3 的 40 天,从 2D 进 3D,你手写了软件光栅化器——投影、深度、纹理、光照全在 CPU 上。Phase 4 的 64 天,工程化:SIMD、多线程、Arena、压缩资产、构建系统。Phase 5 的 85 天,工具化 + GPU 化:profiling UI、debug overlay、切到 OpenGL。Phase 6 的 175 天,图形深水区:深度缓冲、Phong / Blinn-Phong、PBR、纹理压缩、shader 系统、法线贴图。Phase 7 的 140 天,工程进阶:手写 PNG 解码、glTF 加载、游戏内编辑器、热加载资产。Phase 8 的 92 天,光照优化、碰撞重构、最终性能 pass——**Handmade Hero 功能完成,但诚实说,烂尾处**。然后是 Phase 9 的 30 个 module:9A 测试、9B 引擎架构、9C Vulkan、9D GPU 调试、9E 网络后端、9F 构建发布、9G 制作交付——**补完 HH 烂尾留下的全部职业缺口**。

你现在站在 [README 北斗星](../README.md#北斗星两个目的地) 描述的那个点上。Phase 0 之前你只会变量循环;现在你拥有从晶体管到 shader 的完整链路理解,拥有把游戏从点子做到上架的全流程纪律,拥有用代码自由表达想法和艺术创作的能力。你完成了两个目的地:你是一个能发布商业品质开源游戏的开源极客,也是一个能独立交付专业水准游戏的职业工程师。**这两个身份合起来,就是这份教程的"毕业定义"**。

但请注意——这一篇不是一个"恭喜你毕业"的庆祝稿,它是一份"你真的毕业了吗"的对照表。所以最重要的工作还在 §15。

## 15 · 在你 HH 项目里动手:走一次诚实的自检

这是这一篇的红线动作,也是整个 Phase 9 的最后一个"做中学"。我要你**真的做这件事**,不是读完觉得有道理就翻页。

打开你的 HH 项目仓库,新开一个 markdown 文件叫 `professional-readiness-audit.md`(或者你喜欢的名字),把 §2 到 §11 的所有 `- [ ]` 条目拷进去,改成你的项目版本。然后,一条一条,对照你**当前的代码库和能力**,诚实勾选。每一条勾选都问自己三个问题:(1) 我的项目里有没有这个东西的实现?(2) 我能不能解释它怎么工作、为什么这么写?(3) 如果给我一个新需求改它,我能独立做到吗?三个都是 yes 才勾。

我预期你会有三类结果。第一类,**全部勾上**:你这一项真的就绪了,祝贺,继续保持。第二类,**部分勾上**(比如七条勾了四条):这没事,这是真实的学习者状态——把没勾的那三条记下来,它们就是你接下来一个季度的针对性练习。比如你发现 T1 的"frame graph"那一条没勾,你的下个月就是啃 [9B-3](09B-3-frame-graph.md) + 在自己引擎里搭一个最小 frame graph;T6 的"行为树"没勾,你的下个月是看 Millington 的行为树章节 + 给你的 NPC 加一个行为树。第三类,**整条轨道几乎全空**:这暗示你这条轨道根本没学透,可能你只读了 deep-dive 没动手,或者只跟了 phase 但没做变式训练。这是最有价值的发现——它告诉你回头看哪。

做完第一次自检,**把这份 audit 季度复查一次**。每三个月,坐下来,对着同一份清单重新勾一遍——已勾的仍然成立吗(有些可能因为长期没用而忘了)?未勾的现在能勾了吗(经过三个月针对性练习)?新增的项目能力要不要加进清单(比如你学了 ray tracing,加一条 T1 的新勾选项)?**这份持续更新的 audit 文档,就是你的"职业能力账本"**。职业工程师和业余的分水岭,不在于前者什么都会、后者什么都不会,而在于前者清楚地知道自己会什么、不会什么、下一步学什么;后者一团混沌,"感觉差不多"。这份 audit 就是把混沌变成清晰的工具。

这是整个教程给你的最后一个方法论:**不是教你"现在学会了什么",而是教你"如何持续知道自己学会了什么"**。学会一件事是一次性的,持续知道自己学会了什么是终身的——后者更难,也更重要。任何职业领域的高手,本质上都在用类似的清单做自我审计。游戏工程师也一样。

走完这一节,你就完成了 Phase 9 的所有学习内容。下一篇 [capstone-creative-project](capstone-creative-project.md) 不是再讲新东西,而是你**真的去做一款自己的游戏**——原创的核心机制、自己的美术 / 音频方向、完整的预制作 → 切片 → 量产 → 认证(自检) → 上架(开源发布)。capstone 是这份教程的"毕业作品",它是你把 9G-6 这份清单的每一条都"用进真实项目"的证明。一份勾选清单本身没有意义,**让它有意义的,是你真的用这份清单背后的能力,做出了一款能 ship 的游戏**。

## 16 · 练习

**练习一(难度 1),概念题。** 用你自己的话回答:(a) 为什么"用清单自检"比"凭感觉判断我会了"更可靠?Gawande《The Checklist Manifesto》讲的核心机制是什么?它和"经验"是什么关系?(b) 把"目的地 1"和"目的地 2"用你自己的语言复述一遍。为什么两个目的地必须合流,任何一个缺位都不算真就绪?给一个具体的"只有 1 没 2"和"只有 2 没 1"的反面角色描述。(c) 解释 severity 和 priority 的差别(回看 [09G-3 §5](09G-3-alpha-beta-and-content-pipeline.md)),并说明 triage 这套思路为什么也适用于"自检未勾选项的优先级排序"。

**练习二(难度 2),动手实践——核心动作。** 完成 §15 的第一次自检 audit。在你的 HH 项目仓库里建 `professional-readiness-audit.md`,把 §2-§11 所有条目拷进去并对照当前项目诚实勾选。产出是**一份填好的 audit 文档** + 一段总结:你的强项集中在哪几条轨道、弱项集中在哪几条、下一步三个月的具体学习计划(指向具体 module / deep-dive / phase)。这份文档是你这份教程结束后第一个季度的 roadmap。

**练习三(难度 3),工程扩展。** 自检清单本身也可以工程化。给你 HH 项目加一个 `tools/readiness-audit` 子 crate,把 §2-§11 的条目做成结构化数据(例如 RON / TOML 文件),工具读它,对你的代码库做**自动检测**(例如:"我的项目有没有 CI 配置文件"——查 `.github/workflows/`;"有没有自定义分配器"——grep `Arena` / `Pool`;"有没有 dev console"——查 CVar 系统)。产出一份自动报告:哪些条目机器能验证已就绪、哪些需要人脑勾。讨论:机器能验证的部分和不能验证的部分,对自检的可靠性各有什么贡献?

**练习四(难度 4),综合反思题。** 这是这份教程最后一道 Lv4。写一份两到三页的"毕业反思"——不是自夸,是诚实复盘:(a) 走完 phase-0 到 phase-9,你在哪几个时刻感觉"我真正理解了某件事"?这些时刻的共同特征是什么?(b) 哪些轨道你强、哪些弱?为什么?(c) 你下一步做什么——是接着 capstone 做原创游戏,是给 Rust 生态主流 crate 提 PR,是去游戏公司求职,还是别的?为什么这个选择最适合你当前的状态?(d) 这份教程最大的局限是什么?你打算用什么方式补它?考的不是技术,是**自我认知**——一个职业工程师最重要的元能力。

## 17 · 延伸阅读与下一篇

清单思想方面,**Atul Gawande《The Checklist Manifesto》** 是这一篇 §1 的核心来源,讲航空、外科、建筑、投资等领域如何用清单对抗高负荷下的认知失败,中文译本叫《清单革命》。**Jason Gregory《Game Engine Architecture》(第三版)** 的全部章目结构是 §10 横向审计的依据——不要求你逐章背,但要求你脑子里有它的地图,知道每个 part 大致讲什么、自己的项目里对应在哪。**Glenn Fiedler《Gaffer on Games》** 全系列是 T9 网络与制作方面的工业实践参考。**Tim Cain 的 GDC / YouTube 系列** 对 production stages 的实务讲解,在 [09G-3](09G-3-alpha-beta-and-content-pipeline.md) 已推荐过,这里再推荐一次——他的"production 阶段纪律"内容直接对应这份自检的 T9。

工业实践方面,**Game Developer(gamedeveloper.com)的 postmortem 栏目** 依然是最有价值的反思资料库——每个 postmortem 都是一份"我们以为就绪了但其实没就绪"的清单。**Linear / Jira 的 severity vs priority 文档**、**WCAG 可访问性指南**、**各平台 TRC / TCR 公开清单**(Sony / Microsoft / Nintendo / Steam)都是这份自检里对应轨道的权威标准。

走完这一篇,9G 序列完整收口:从"找到好玩"([9G-1](09G-1-preproduction-and-prototype.md))到"切片证明"([9G-2](09G-2-vertical-slice.md))到"量产纪律"([09G-3](09G-3-alpha-beta-and-content-pipeline.md))到"合规认证"(9G-4)到"母版与上架"([09G-5](09G-5-gold-and-post-launch.md))到这一篇的"专业就绪自检"。Phase 9 的学习内容到此全部讲完——9A 测试、9B 引擎架构、9C Vulkan、9D GPU 调试、9E 网络后端、9F 构建发布、9G 制作交付,30 个 module。整份 Handmade Hero 综合教程的"教学部分"到此结束。

下一篇不再讲新内容,而是让你**真的去做**——[capstone-creative-project](capstone-creative-project.md):交付你自己的原创游戏垂直切片,从预制作、切片、量产到上架(开源发布)。它是这份教程的毕业作品,是你把 9G-6 这份清单的所有勾选项**用进一个真实项目**的证明。Casey 在 Day 667 停下了,你不会停下——你继续走完,做出一款 Casey 没交付的、可上架品质的、你自己的游戏。这份教程给你的所有能力,在 capstone 里汇成一个作品。
