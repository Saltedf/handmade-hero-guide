
# 09C-8 · 把 HH 的一个真实 pass 迁到 Vulkan

## 0 · 你已经能画一个 mesh,但你还没赢过 OpenGL

先停下来,看看你身后的脚印。

从 [09C-1](09C-1-gpu-architecture-and-explicit-api.md) 你承认"GPU 不是快的 CPU"开始,你走过了一条很长的路:[09C-2](09C-2-instance-device-swapchain.md) 的 instance/device/swapchain,[09C-3](09C-3-command-buffers-and-synchronization.md) 的同步循环(fence/semaphore/barrier 各管谁等谁),[09C-4](09C-4-graphics-pipeline-first-triangle.md) 第一根 pipeline,[09C-5](09C-5-descriptors-and-uniforms.md) 的 descriptor,[09C-6](09C-6-textures-and-samplers.md) 的纹理,[09C-7](09C-7-depth-and-meshes.md) 的深度和真实 mesh。这些都是了不起的成就。但如果你诚实地看,它们全都是**玩具场景**——一个三角形、一个 mesh、一个旋转的立方体,在 Vulkan 上跑。它们证明你会用 Vulkan 这套 API,但没证明一件事:**Vulkan 真的能接管你 HH 游戏里实际的渲染工作。** 你的 HH 项目现在渲染主力还是 OpenGL(你在 phase-5 搭起来的那套),Vulkan 是一个并行的、孤立的实验。两者之间有一道鸿沟——只要没跨过去,Vulkan 对你的 HH 项目就永远只是"学了一下",而不是"用上了"。

这一篇就是来跨这道鸿沟的。你要做一件非常具体的事:**从你 HH 的渲染器里挑一个真实的 pass**(不透明几何 pass 最合适;做了 phase-6 就是 G-Buffer pass;只做了前向渲染就是那个前向光照 pass),把它**完整地迁到 Vulkan**,作为 OpenGL 后端旁边的一个**第二个可插拔后端**——两个后端实现同一个 `Renderer` trait([09B-2](09B-2-subsystems-modules-plugins.md) 定义好的那个)。然后在同一个游戏逻辑、场景、相机下,分别用两个后端渲染同一帧,**当画面肉眼一致**(再用一个快照 diff 兜底),你就证明了:Vulkan 不只是你会的 API,它是你 HH 游戏的第二颗心脏。

三角形是 Vulkan 的"hello world",迁移一个真实 pass 是 Vulkan 的"毕业设计"。前者跟着教程就能做,后者要你把 9C 一路学的东西**组织起来**,接到一个为 OpenGL 写的真实代码库上,处理 OpenGL 和 Vulkan 之间所有不愉快的概念摩擦。这一篇没什么新的 Vulkan 功能要学(你已经学完了),它纯粹是**综合**——把碎片拼成一个能用的整体。这种综合,是 9C 整个序列真正要让你掌握的东西。

## 1 · 你身后站着的三根支柱

动手之前,我必须把你身后三根关键支柱点出来,因为这一篇整个架构站在它们之上。

第一根是 [09B-2](09B-2-subsystems-modules-plugins.md) 的 `Renderer` trait。你在 9B-2 的做中学里,定义过一个 `Renderer` trait,把 OpenGL 后端实现成 `OpenglRenderer`,让游戏逻辑只依赖 trait。如果当时你偷懒了、没真做,这一篇会非常痛苦——你的 Vulkan 代码会和游戏逻辑死焊在一起。如果你做了,这一篇就清爽:你只是写一个 `VulkanRenderer` 实现 trait,游戏逻辑一行不改。**这一篇能成立,前提是你 9B-2 的抽象做对了**;没做对,先回去补,磨刀不误砍柴工。

第二根是 [09B-3](09B-3-frame-graph.md) 的 frame graph。在 9B-3 里你把渲染从"一串命令"改成了"声明 pass + graph 编译 + graph 执行"。这个抽象在这一篇会爆发出它真正的价值——**同一个 frame graph 声明,可以驱动两个完全不同的后端**。你声明"几何 pass,写 G-Buffer",graph 编译时根据当前后端生成对应的 OpenGL 调用或 Vulkan 命令缓冲。没有 frame graph,你就得为 OpenGL 和 Vulkan 各写一遍 pass 编排,而且两边的执行顺序、资源流转都要手动保持一致——双重地狱。frame graph 把"做什么"和"怎么做"分开了,这一篇你站在这个分离上:声明层共用,执行层各写各的。

第三根是 [09A-1](09A-1-testable-game-architecture.md) 的可测架构。9A-1 让你把游戏逻辑做成了"确定、可控、不依赖具体后端"。这意味着当你切到 Vulkan 后端时,**同样的输入产生同样的输出**——这是后面做快照对比的前提。9A-1 的纪律,在这一篇第一次以"跨后端"的形式兑现它的回报。

## 2 · 迁移策略:先做最小的"像素一致"闭环

迁移一个真实 pass 听起来工程量巨大,我先把策略讲清楚。

核心策略是**最小闭环**:不要一次把整个渲染器都迁过去。挑**一个** pass(下面假设是不透明几何 pass),目标是让它在 Vulkan 后端上独立渲染出和 OpenGL 一致的画面。其他 pass(光照如果分开、UI、后处理)暂时还在 OpenGL 上跑——是的,你的游戏这一阶段是一个"混合后端",几何 pass 在 Vulkan,其他还在 OpenGL。这听起来怪,但它是迁移过程合理的中间态,你的 `Renderer` trait 应该允许"按 pass 分发"的粒度。等几何 pass 在 Vulkan 上稳定了,再一个一个把其他 pass 迁过去,每迁一个跑一次快照对比。这是增量、可控的过程,不是大爆炸式重写。

为什么是这个顺序?因为**几何 pass 是最简单、最基础的那个**——就是"画一堆三角形到 framebuffer",不涉及复杂光照、不涉及多 pass 之间的资源传递。它和你 09C-7 做过的"加载 mesh + 深度缓冲"几乎是一回事,只是 mesh 来自 HH 的真实资产,而不是 tutorial 的立方体。你 09C-7 的代码可以直接复用大部分。差异只在"数据从哪儿来"(从 HH 的资产系统来)和"结果写到哪儿"(写到 frame graph 给你的 attachment,不是你私有的 swapchain image)。这两处差异,正是这一篇要处理的核心工程问题。

最小闭环的验收标准,提前给你,让你心里有靶子:**用同一个测试场景(一个固定的、有几个 mesh 的关卡,固定相机角度,固定时间),分别在两个后端渲染几何 pass,存图,做快照 diff,差异应该在容忍范围内**(§6 讲怎么定阈值)。达到了,你就有了第一个像素一致的 Vulkan pass,迁移的大门就打开了。

## 3 · 后端接口的设计:trait 怎么允许第二个实现

你的 `Renderer` trait(9B-2 定义的)大概是这个形状:

```rust
pub trait Renderer {
    fn begin_frame(&mut self, ctx: &RenderContext);
    fn submit_mesh(&mut self, mesh: &MeshHandle, transform: &Mat4, material: &Material);
    fn end_frame(&mut self);
}
```

`RenderContext` 装这一帧的共享状态——相机矩阵、视口、时间、当前 frame graph 编译出的执行计划。`OpenglRenderer` 实现这套方法内部调 OpenGL 命令。你写一个 `VulkanRenderer`,实现同一套方法,内部调 Vulkan 命令。有几个设计点不在动手前想清楚,后面会反复返工。

第一,**资源句柄必须后端无关**。`MeshHandle`、`TextureHandle` 不能是 OpenGL 的 GLuint,也不能是 Vulkan 的 `vk::Buffer`,它必须是一个**抽象 ID**(比如 `u32` 索引),指向某后端内部的资源表。这样游戏逻辑提交一个 mesh 时给的是抽象 ID,具体这个 ID 在 OpenGL 后端对应一个 VAO、在 Vulkan 后端对应一个 vertex buffer + descriptor,由各后端自己查表。一个干净的做法是:每个后端维护一个 `HashMap<GenericId, BackendSpecificResource>`,资源加载时游戏逻辑拿到 GenericId,后端把对应的内部资源存进自己的表;渲染时游戏逻辑传 GenericId,后端查自己的表。

第二,**uniform 数据传输要统一**。游戏逻辑算出"这一帧 view matrix 是 X、proj 是 Y、这个 mesh 的 model matrix 是 Z",这套数据怎么传给后端?不能让游戏逻辑知道"OpenGL 用 `glUniformMatrix4fv`,Vulkan 用 push constant 或 descriptor"——那是后端实现细节。统一接口是:游戏逻辑把所有 uniform 打包成**后端无关的 struct**(`struct FrameUniforms { view, proj, time, ... }`、`struct ObjectUniforms { model, ... }`),交给后端,后端自己决定怎么送上 GPU——OpenGL `glUniform*` 上传到 UBO,Vulkan memcpy 进 mapped 的 uniform buffer 或塞进 push constant。这个数据打包层,是双后端的另一个关键接缝。

第三,**frame graph 的执行回调要按后端分发**。在 9B-3,你的 frame graph 每个 pass 有回调。双后端时,回调不能写死成 OpenGL 或 Vulkan,它必须根据当前后端走不同路径。最干净的做法是,pass 声明时只描述"我读什么、写什么、用什么材质",**具体怎么画由后端在执行时决定**——frame graph 是后端无关的声明层,后端读这份声明、生成自己的命令。这个分离本来就是 frame graph 的精神(9B-3 反复强调过),双后端只是把它的价值放大了——写一遍 pass 声明,两个后端各跑各的。

这三点想清楚,你的 `VulkanRenderer` 就有了干净的容身之所。

## 4 · Vulkan 后端的内部:把 9C-2..7 串起来

这一节把 9C 学过的东西,在"一个真实几何 pass"语境下重新串一遍,聚焦于**它们怎么咬合成能跑的整体**,以及接缝处你以前没注意到的细节。

**资源上传**。OpenGL 里加载 mesh 是创建 VAO/VBO/IBO,`glBufferData` 上传。Vulkan 里(09C-5、09C-7)你创建 `vk::Buffer`、分配 `DEVICE_LOCAL` 内存、用 staging buffer 拷过去、插 barrier 等拷贝完成。关键强调:**资源上传发生在 mesh 加载时,不是每帧**。每帧只是"绑定已上传的 buffer,画"。新手常见错误是把上传写在每帧渲染循环里——这在 OpenGL 也错,在 Vulkan 错得更刺眼(每帧创建 buffer 极昂贵)。

**Pipeline 预烤**。几何 pass 只有一种渲染状态(不透明、写深度、关 blend、cull back),意味着你只需**一根 pipeline**,在游戏启动时创建好(09C-4 那套流程),它和 mesh 分离——同一根 pipeline 画一百个不同 mesh,只要它们用同一种渲染方式。这一点 OpenGL 不会让你明确感受到("pipeline"是隐式当前状态),Vulkan 让你看清:**pipeline 是关于"怎么画",mesh 是关于"画什么",两者正交**。

**Descriptor set 组织**。几何 pass 最少需要:一个 uniform buffer(装 view/proj,所有 mesh 共享),可能一个 per-mesh uniform(装 model matrix)。每帧 view matrix 变了怎么更新 descriptor?最干净的做法:为每一帧(ring buffer,MAX_FRAMES_IN_FLIGHT = 2)维护一个 uniform buffer,每帧 memcpy 新值进去(09C-3 同步保证这时 GPU 不读这块内存),descriptor 初始化时就绑到这块 buffer,之后不需重绑。model matrix 数据量小,用 push constant 更省事。

**命令缓冲录制**(9C-3 的核心)。`begin_frame`:等 fence、acquire image、begin cmd。`submit_mesh`:`cmd_bind_pipeline`(只在 pass 开始绑一次)、`cmd_bind_descriptor_sets`(绑 view/proj uniform)、`cmd_bind_vertex_buffers` + `cmd_bind_index_buffer`、`cmd_push_constants`(塞 model matrix)、`cmd_draw_indexed`。`end_frame`:end render pass、end cmd、`queue_submit`(关联 semaphores 和 fence)、`queue_present`。注意**录制按 mesh 一个一个来,但 pipeline 只绑一次**——这正是 pipeline 不可变带来的好处,绑一次画 N 次。

你的 `VulkanRenderer` 内部就是 9C-2..7 那些组件的一个**配置好的实例**。这一篇没有新组件,就是把已知组件配置成游戏可用的形态。"没有新东西,但需要综合"——这正是 capstone 的本质。

## 5 · Shader 翻译:GLSL 在两个世界里

迁移里逃不掉的麻烦事是 shader。你 OpenGL 后端用的 GLSL,不能原封不动喂给 Vulkan。两边 GLSL 长得像,但有几个具体差异要处理。

**最显眼的差异是顶点输入**。OpenGL 你写 `in vec3 position;`,驱动自动按 location 对应。Vulkan(准确地说是 SPIR-V)必须显式 `layout(location = 0) in vec3 position;`,location 要和你 vertex input state(09C-4)声明的 attribute binding 对上。**第二个差异是 uniform block**:OpenGL 写 `uniform mat4 viewProj;`,Vulkan 必须包进 block:`layout(set = 0, binding = 0) uniform UBO { mat4 viewProj; };`——`set` 和 `binding` 是 Vulkan descriptor 概念,OpenGL 没有。push constant 在 Vulkan 是 `layout(push_constant) uniform Push { mat4 model; };`,OpenGL 没有对应物。**第三个是 `gl_PerVertex`**:Vulkan vertex shader 必须显式声明 `out gl_PerVertex { vec4 gl_Position; };`(用了 gl_PointSize/gl_ClipDistance 也要声明),OpenGL 不要求。

怎么处理这三处差异?三条路。**第一条,维护两份源码**——直接但最痛苦,改一个改两份,长期必然不同步。不推荐。**第二条,一份源码用预处理宏区分**——`#ifdef VULKAN` 包裹 Vulkan 特有部分,`#else` 是 OpenGL 部分。编译时 OpenGL 目标不加宏,Vulkan 目标加 `-DVULKAN`。一份源码两个目标,大多数双后端引擎的折衷做法,推荐。**第三条,只写 Vulkan GLSL,OpenGL 用 SPIR-V-cross 反向翻译**——最干净(一份 shader),但工具链复杂,不适合 HH 教学项目规模。

推荐第二条。一份 shader,预处理宏区分。代价是文件里有些 `#ifdef`,可读性略降;收益是只维护一份逻辑。核心模式是把 Vulkan 特有的 `set/binding`、`gl_PerVertex`、`push_constant` 包在 `#ifdef VULKAN` 里,OpenGL 部分用 `#else` 走传统 `uniform` 声明;vertex shader 入口处也用 `#ifdef` 区分 model matrix 来自 push constant 还是普通 uniform。一份源码,两个目标。

Arch 上编两份目标:

```bash
glslangValidator -G geometry.vert -o geometry.vert.glsl.spv   # OpenGL 用 -G
glslangValidator -V -DVULKAN geometry.vert -o geometry.vert.spv  # Vulkan 用 -V
```

## 6 · 验证一致性:9A-3 的快照测试在跨后端上发威

Vulkan 后端能渲染几何 pass、屏幕上有画面了。下一个问题:**怎么知道这个画面和 OpenGL 的对得上?** 肉眼是起点,但不可靠——能看出"完全错了",看不出"暗了 5%"。这一节 [09A-3](09A-3-integration-and-snapshot-testing.md) 的快照测试有了它最伟大的用武之地。

回顾 09A-3:快照测试把一帧渲染结果存成基准图,以后每次重渲染都对比基准,差异超阈值就报错。它的价值不在"测正确性",在"测不变性"——在你没明确意图的情况下画面不该变。这个机制在**跨后端**场景下变成绝妙工具:你把 OpenGL 渲染的那一帧存为基准,Vulkan 渲染同一帧和基准对比。差异在阈值内,证明两个后端等价;超阈值,立刻知道 Vulkan 哪里发散了。

但跨后端有几个 9A-3 没专门讲的坑。**第一,两个后端浮点精度可能不同**——OpenGL 驱动和 Vulkan 驱动是两套代码,同一个矩阵乘法实现可能有微小差异(09A-3 说的"GPU 渲染不是逐像素确定"的放大版)。所以不能用太严的阈值。常见做法:把两边输出都降采样到 64×64(降采样平均掉高频噪声),然后允许每个像素差几个值;或用感知哈希(pHash)粗筛。**第二,要确保两个后端跑同一场景状态**——又回到 [09A-1](09A-1-testable-game-architecture.md) 的可测架构:测试场景必须确定(固定相机、固定时间、固定随机种子),否则两个后端画面不同你分不清是后端差异还是输入差异。**第三,y 翻转问题**——OpenGL 的 NDC y 轴朝上,Vulkan 朝下,同一 vertex shader 算出的 `gl_Position` 在两边画面是上下翻转的。不是 bug,是坐标系约定不同。修法:Vulkan projection matrix 乘一个 y 翻转矩阵,或 Vulkan viewport 的 `height` 取负值。这个差异没处理,快照 diff 会显示整张图翻转,差异巨大——这其实是好事,逼你立刻处理。

这几个坑处理完,你的快照 diff 应该能跑出"差异在容忍范围内"。那一刻你有了 Vulkan 后端的第一个客观证明:它和 OpenGL 渲染等价。这个证明比"肉眼看差不多"硬得多——它是机器验证、可重复、放进 CI 持续守护的。以后每次改 Vulkan 后端,跑一次快照,过了就没改坏等价性。

## 7 · 测性能:Vulkan 到底赢在哪里

后端等价了,下一个问题当然是——**Vulkan 比 OpenGL 快多少?** 你迁移它不是为了等价,是为了快。

测的方法是 [phase-4 Tracy](../phase-4/deep-dives/profiling-with-tracy.md) 的本行。你在两个后端都埋 Tracy zone(在 `begin_frame` 和 `end_frame` 各放一个),跑同一帧,看 CPU 端 frame time。重点关注 **CPU frame time**,不是 GPU frame time——Vulkan 相对 OpenGL 的主要优势是**降低 CPU 端驱动开销**,不是 GPU 端更快(GPU 在两个 API 下做同样的光栅化工作,差不多快)。Vulkan 的赢点在 CPU。具体说,OpenGL 每次 `glDraw*` 驱动都要:检查状态合法性、可能补丁 shader、翻译命令、插入必要同步——这些每帧每次 draw 重做。Vulkan 里,状态校验和命令翻译在 pipeline 创建时就做完了(09C-4 烤熟的配方),运行时 `vkCmdDraw` 几乎只是往命令缓冲追加几条机器命令,驱动不参与。这个差距在 draw call 多时就是 CPU 帧时间的差。

现在说你可能不想听、但必须听到的真相:**对一个简单几何 pass、画几十个 mesh,Vulkan 的 CPU 优势可能小到几乎测不出来**。跑 Tracy 你可能看到 OpenGL 2.0ms/frame,Vulkan 1.8ms——有差距但不大,你甚至怀疑工程量值不值。这个怀疑合理,我必须诚实告诉你:**简单渲染负载,Vulkan 优势不显著**。

Vulkan 的优势是**随复杂度放大**的。当管线有几十个 pass、上千个 draw call、复杂资源流转——OpenGL 驱动开销累积成天花板,Vulkan 低开销优势才显现。画几个 mesh 的几何 pass,是 Vulkan 优势最小化的场景。所以测出差距小,**不要因此否定 Vulkan**——那是因为测试场景还没复杂到让它发挥。你应该在 dev log 里诚实地记:"在这个简单 pass 上,Vulkan vs OpenGL CPU 帧时间差距是 X ms,预期 pass 数和 draw call 增加后这个差距会扩大。"这种诚实的测量和诚实的预期,是职业工程师和教程复读机的区别。

另一个测量点是**驱动稳定性的间接体现**——Vulkan 的 frame time 通常比 OpenGL 更平稳(帧时间方差更小),因为 Vulkan 没有 OpenGL 驱动那种"偶尔做一次大开销状态整理"的非确定行为。看 Tracy 的 frame time 直方图,Vulkan 分布更窄。这个"稳定性"虽不直接是平均性能,但意味着更少掉帧、更平滑的体验,在实际游戏感受上是实打实的优势。

## 8 · 迁移过程中你会踩的几个真实坑

我把迁移里最容易咬人的坑提前告诉你,让你夜里 debug 时知道这些坑存在、有名字、有解法。

**第一个,y 翻转**(§6 提过)。Vulkan 和 OpenGL NDC y 轴方向相反,画面上下颠倒先怀疑这个。修法:projection matrix 乘 y 翻转,或 Vulkan viewport height 取负。两个修法不要同时用,会翻两次变回原样(然后你又怀疑别的问题)。**第二个,深度范围**。OpenGL 深度默认 [-1, 1],Vulkan 是 [0, 1]。projection matrix 在 OpenGL 里把 z 映射到 [-1, 1],直接拿 Vulkan 用,深度测试会错——近处可能被远处错误遮挡,或整个场景深度全是垃圾。修法:Vulkan 后端 projection matrix 的 z 映射改成 [0, 1](很多数学库有 `projection_vulkan_clip_matrix`,或手写 z 缩放)。这个坑不会黑屏,但画面"深度错乱",非常迷惑人。

**第三个,顶点绕向(culling 方向)**。OpenGL 默认逆时针为正面,Vulkan 也默认逆时针——但两个 API 对"逆时针"的定义基于不同屏幕坐标系(因为 y 翻转),同一 mesh 的三角形在 OpenGL 是正面、在 Vulkan 可能被识别成背面 cull 掉。表现:某些三角形消失。修法:Vulkan 后端先 cull mode 设 NONE 确认所有三角形画出来,再调 front_face(CW/CCW)让 culling 和 OpenGL 一致。**第四个,color space 不一致**。swapchain 在 Vulkan 用 `B8G8R8A8_SRGB`,但 OpenGL framebuffer 是线性,两个后端输出颜色会差一档。修法:确认 sRGB 转换在两个后端的同一阶段发生——要么都在 shader 输出时转换、framebuffer 用 linear;要么 shader 输出线性、framebuffer 自动转换(OpenGL `GL_SRGB8_ALPHA8`,Vulkan `_SRGB` format)。混用就出错。

**第五个,release 模式关掉验证层后某些错误沉默变坏**。开发时一定开验证层(09C-1 强调过),但你为测性能在 release 关掉验证层后,某些原本验证层会拦的错误(pipeline layout 不匹配)可能直接导致渲染错误但不崩溃。所以**测性能也要偶尔开验证层跑一遍**,确认没累积新违例。

这五个坑你大概率撞上至少两个。撞上时回头查这一节,对号入座。

## 9 · 在你 HH 项目里动手(做中学红线)

这是 9C 序列的毕业动手环节。做完它,你就完成了整个 9C。我拆成清晰步骤,但每一步可能比预期花更多时间——这是正常的,毕业从来不轻松。

第一步,**确认 9B-2 Renderer trait 做对了**。检查 trait 是否真让游戏逻辑不依赖具体后端。自检:把 `OpenglRenderer` 整个注释掉,游戏逻辑应该还能编译(只是不能渲染)。编译不过,说明有地方直接依赖了 OpenGL 类型,回去把那些依赖抽进 trait。这步不做,后面全是灾难。

第二步,**搭起 VulkanRenderer 骨架**。把 09C-2..7 写过的 Vulkan 代码组织成一个 `VulkanRenderer` 结构体,持有 instance、device、swapchain、command pool、ring buffer 的 cmd/fence/semaphore、pipeline、descriptor pool。让它实现 `Renderer` trait 所有方法,但 `submit_mesh` 暂空。在 main 里加一个开关(用 [09B-4](09B-4-cvars-and-dev-console.md) 的 CVar,或一个简单常量),让你运行时切换后端。先确认两个后端都能"启动、清屏、present"——Vulkan 后端此时显示清屏色,不画任何 mesh。

第三步,**接通资源加载**。让 mesh 加载代码同时给两个后端注册资源——OpenGL 后端创建 VAO/VBO,Vulkan 后端创建 vertex buffer + staging 上传。`MeshHandle` 是后端无关 ID,两个后端各自维护内部表。加载一个简单测试 mesh(立方体),确认它在两个后端的内部表里都注册了。

第四步,**实现 VulkanRenderer::submit_mesh**(核心)。`begin_frame`:等 fence、acquire image、begin cmd、begin render pass(用 09C-4 创建的 render pass 和 framebuffer)、bind pipeline。`submit_mesh`:bind vertex/index buffer、更新或 push model matrix、bind 这一帧 view/proj descriptor、`cmd_draw_indexed`。`end_frame`:end render pass、end cmd、submit、present。这一步把 09C-3..7 所有东西串起来,你会撞上 §8 列的坑,逐个修。

第五步,**处理 shader**。按 §5 方法用预处理宏把几何 shader 改成双目标。用 glslangValidator 编两份 SPIR-V,确认 OpenGL 后端那份还能工作(Vulkan 改动不能破坏 OpenGL),Vulkan 后端加载那份 Vulkan SPIR-V。

第六步,**让画面出来**。在 Vulkan 后端下跑测试场景,你应该看到几何 pass 渲染的画面。黑屏或错乱就按 §8 的坑排查。先肉眼确认画面"大致对"——几何形状对、相机角度对、没有明显错乱。

第七步,**做快照 diff**。按 §6 方法,在固定测试场景下(固定相机、时间、种子)分别用两个后端渲染几何 pass,存图,快照对比。调整阈值到合理范围(允许微小浮点差异,拒绝大块区域发散)。目标:diff 在容忍范围内。diff 大就定位发散区域(y 翻转?深度错乱?color space?),修,重测。

第八步,**测性能**。开 Tracy(两个后端都埋 zone),跑同一帧,记录 CPU frame time。dev log 里诚实记下:OpenGL X ms,Vulkan Y ms,差距多少,以及你对差距大小的判断(简单 pass 差距小是正常的)。

第九步,**commit**。这篇的 commit 是 9C 序列的毕业证书,commit message 要写得有分量——记录你迁了哪个 pass、踩了哪些坑、快照 diff 结果、性能对比。这个 commit 以后回头看会很有成就感。

验收标准:**Vulkan 后端能独立渲染几何 pass,画面和 OpenGL 后端肉眼一致并通过快照 diff(容忍范围内),验证层零报错,性能数据记录在 dev log,commit 已提交**。达到这个标准,你正式从 9C 毕业。

## 10 · 9C 序列收口:你身后那条长长的路

这是 9C 最后一篇正文,我必须停下来,带你回头看这八篇走过的整条路。这种回头看不是仪式感,是让你**确认你真正拥有了什么**——爬了这么久的山,你得知道自己到了哪。

八篇之前,[09C-1](09C-1-gpu-architecture-and-explicit-api.md) 你从"GPU 不是快的 CPU"开始。那篇告诉你 OpenGL 几十行画三角形,是驱动替你做了另外四百多行;Vulkan 把那四百多行还给你,代价繁琐,回报控制力。当时这一切对你还只是抽象的承诺。八篇之后,你亲手走了那四百多行——你不再"相信"这个承诺,你**验证**了它。[09C-2](09C-2-instance-device-swapchain.md) 你建立了 Vulkan 的入口,[09C-3](09C-3-command-buffers-and-synchronization.md) 你穿过了整个序列最难的一篇(理解 GPU 异步执行模型,fence/semaphore/barrier 各司其职——这一篇你卡多久都不冤,因为这是 CPU 编程和 GPU 编程真正分道扬镳的地方),[09C-4](09C-4-graphics-pipeline-first-triangle.md) 你烤出第一根 pipeline 看到红绿蓝三角形——五百行的真相你亲手走完了一遍,[09C-5](09C-5-descriptors-and-uniforms.md) 三角形能动,[09C-6](09C-6-textures-and-samplers.md) 加了纹理,[09C-7](09C-7-depth-and-meshes.md) 加了深度和真实 mesh。然后这一篇 [09C-8],你把这一切组装成真实后端,接进 HH 游戏,和 OpenGL 并肩,通过快照验证等价,通过 Tracy 测性能。

走到这里,你拥有了什么?

第一,你拥有了**真正的 GPU 理解**。这不是"会用 Vulkan API"那种理解——API 是表象,会褪色,会过时(将来你可能会用 WebGPU、DX12、Metal)。你拥有的是更深层的东西:SIMT 执行模型、显存层次对性能的决定性、同步是跨处理器协调问题、状态预制和运行时开销的权衡、命令缓冲录制和执行的分离。这些是**所有**现代图形 API 背后的硬件真相。Vulkan 是它们里最诚实的那个,你通过 Vulkan 看清了它们共有的骨骼。学完 9C,你以后学任何图形 API 都是"换皮",骨骼你已经懂了。

第二,你拥有了一个**工作的 Vulkan 后端**。这不是玩具,这是你 HH 游戏的第二颗心脏,它真的在渲染你游戏的画面。你以后会往里加更多 pass(光照、阴影、后处理、UI),每加一个就更完整一分。等到某天 OpenGL 后端能被完全取代,你就有了纯 Vulkan 的 HH 引擎——商业引擎级别的架构。

第三,你拥有了**让这件事可维护的关键中间层——frame graph**。没有 frame graph,你 Vulkan 的几十个 pass 是不可维护的——手写屏障写到崩溃,资源流转乱成一团。frame graph([09B-3](09B-3-frame-graph.md))是 Vulkan 这种显式 API 还能保持理智的关键盾牌。这一篇迁一个 pass 还能勉强手写屏障,等你迁三个、五个 pass,frame graph 的价值会指数级上升。9C 的设计就是把 Vulkan 繁琐的真相给你看清(9C-1..7),然后告诉你"但你有 frame graph,你不需要长期忍受这种繁琐"(9C-8 把它接进真实场景)。**学底层是为了在更高抽象上自由**——这句话在 9C 开头(09C-1)说过,在结尾(这一篇)你亲身体验了它的兑现。

恭喜你走完了 9C。这不容易,你值得为自己骄傲。

## 11 · 练习

练习一,Lv1 概念辨析。为什么迁移一个真实 pass 比画 tutorial 三角形难得多,即使"Vulkan 知识"你已经学完了?因为迁移要你把碎片知识组织成可用整体、处理 OpenGL 和 Vulkan 之间的概念摩擦(y 翻转、深度范围、shader 差异)、把 Vulkan 后端接到一个为 OpenGL 写的真实代码库上。这是综合的难度,不是新知识的难度。用两三句话向同学解释"综合"和"新学"为什么是两种不同的难。

练习二,Lv2 设计思考。你的 Renderer trait 如果最初只考虑了 OpenGL,迁 Vulkan 时会遇到哪些返工?(至少举三个:资源句柄必须抽象化、uniform 数据必须打包成后端无关 struct、frame graph pass 回调必须按后端分发。)想清楚这些,你能体会为什么 9B-2 强调"一开始就为可替换设计"——后置补抽象比一开始就抽象痛苦得多。

练习三,Lv2 概念辨析。OpenGL 和 Vulkan 之间有三个著名视觉差异:y 翻转、深度范围([-1,1] vs [0,1])、color space 处理。各用一句话说明每个差异是什么、怎么修。这三个差异没处理,你的快照 diff 会显示什么?

练习四,Lv3 动手实践。完成 §9 全部九步。这是这篇的核心交付物,也是 9C 序列的毕业证书。提交 commit,在 commit message 里记录踩过的坑、快照结果、性能数据。如果你只能做 9C 的一个练习,就是这个。

练习五,Lv4 工程深化。把你的 Vulkan 后端的第二个 pass 也迁过去——比如简单的前向光照(fragment shader 里算一个方向光的漫反射)。这要求你处理两个 pass 之间的资源传递(几何 pass 的 G-Buffer 或 depth 给光照 pass),也就是 frame graph 真正开始发力的场景。把第二个 pass 也通过快照 diff,你的 Vulkan 后端就不再是"几何 pass 的玩具",而是能做实际渲染工作的引擎部件。这个练习可以延伸到 9C 之后几周慢慢做。

## 12 · 延伸阅读与下一篇

这一篇延伸阅读,首推 vulkan-tutorial.com 的 "Drawing" 和 "Swapchain Recreation" 章节——它和这篇做的是同一件事的简化版(把简单场景跑在 Vulkan 上),可对照读,看你处理真实 HH 代码时的复杂度比 tutorial 高多少。Sascha Willems 的 Vulkan examples 仓库有大量"真实的"渲染例子(不只是三角形),特别是 `deferred` 和 `gltfloading`,值得读它们怎么组织真实 pass 的代码。要看生产级双后端架构,Bevy 的 `bevy_render` 是教科书级的——它同时支持多种后端,抽象层设计极其干净,你这篇挣扎过的接口问题它都有成熟解法。

关于 OpenGL 到 Vulkan 概念映射的官方参考,Khronos 的 *Vulkan Guide* 有一章 "OpenGL to Vulkan",逐项列了两个 API 的对应和差异(y 翻转、深度范围、clip space 都在),迁移时遇到不一致先查这个表。

GPU 性能分析方面,[phase-4 的 Tracy](../phase-4/deep-dives/profiling-with-tracy.md) 已经给你打过底,这篇你第一次把它用在"跨后端对比"上。Tracy 官方文档关于 GPU zone 的部分(把 GPU 命令缓冲的执行也标 zone)值得读——它让你不只看到 CPU frame time,还能看到 GPU 端实际执行时间线,这是更深一层的性能洞察。

9C 序列到此正式收口。下一篇进入 [09D](09D-gpu-debugging-toolchain.md) GPU 调试——既然你有了真实 Vulkan 后端,一定会遇到各种"画面错了但不知道为什么"的时刻,09D 讲 Vulkan 调试工具生态:验证层进阶用法、RenderDoc 帧抓取与逐 draw 分析、SPIR-V 反汇编与 shader 调试、GPU 性能分析工具。这些是你日后维护 Vulkan 后端、追查渲染 bug 的命脉。你在 9C 写过的代码,会在 09D 的工具下被照亮——你会看到你那些 `vkCmdDraw` 在 GPU 上到底做了什么,看到你的 descriptor 实际绑了什么数据,看到你的 pipeline 状态在每一帧里长什么样。Vulkan 的"显式"特性让调试比 OpenGL 容易得多(因为一切都看得见),09D 就是带你用上这套可见性。
