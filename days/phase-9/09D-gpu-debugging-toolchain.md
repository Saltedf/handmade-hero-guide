---
phase: 9
sequence: "9D"
module: 1
title_en: "GPU Debugging Toolchain"
title_zh: "GPU 调试工具链:RenderDoc、Vulkan debug marker、timestamp、shader printf"
type: deep-dive
difficulty: 4
duration: "3-4 小时"
domains: [graphics, gpu, rust, engineering, tooling]
prereqs: ["09C-8-migrate-hh-pass-to-vulkan"]
calibration: "RenderDoc/PIX/Nsight 实操 + Vulkan debug markers/timestamps/shader-printf"
---

# 09D · GPU 调试工具链

## 0 · 屏幕是黑的,而 `println!` 救不了你

你的 Vulkan 渲染器跑起来了。[09C-8](09C-8-migrate-hh-pass-to-vulkan.md) 你把 HH 的几何 pass 迁到了 Vulkan,验证层一声不吭,你截图发朋友圈,觉得你赢了。然后你加了第二张纹理,或者改了 fragment shader 里的一行——重新跑,屏幕又黑了。或者更阴险,屏幕不是全黑,而是颜色偏了半个色阶,或者贴图只显示了左上角的四分之一,或者 mesh 似乎在那里但被某种看不见的力量扯成了奇怪的几何形。

你做了所有 CPU 程序员会做的事:加 `println!`、用 `dbg!`、写日志。你打印了 vertex buffer 的内容,看着那些 `0.5` `-0.3` `1.0` 一行行刷过,确认数据是对的。你打印了 uniform buffer 上传前的矩阵,用 `glam::Mat4::to_cols_array` 反算每一项,确认 MVP 矩阵是对的。你打印了 descriptor set 绑了哪个纹理、哪个 binding。一切,在 CPU 这边,都是对的。但屏幕依然是错的。

这就是 GPU 调试和 CPU 调试的分水岭,你必须刻在脑子里:**GPU 的工作,你在 CPU 上看不见。** 那条命令缓冲一旦 `vkQueueSubmit`,就跨过了一条边界,进入了 [09C-1](09C-1-gpu-architecture-and-explicit-api.md) 反复强调的那个独立处理器——它有自己的时钟、自己的几千个线程、自己的显存。你的 `println!` 跑在 CPU 线程上,GPU 上的 fragment shader 是不是真的把你想要的 UV 采样进了对的纹素,你看不到。命令缓冲是"录制好的剧本",但剧本被一个你看不见的演员在另一个舞台演了一遍,你看不见他的脸。CPU 调试工具(gdb、println、Tracy 的 CPU lane)在这里全部失效——它们告诉你的是"剧本写了什么"、"提交了什么",而不是"演出来什么样"。

这一篇就是来给你装备那台 X 光机的。GPU 调试和 CPU 调试是两种工艺,工具完全不同。CPU 调试的核心动作是"打断点 + 看变量",GPU 调试的核心动作是"**抓一帧,然后逐 draw call 地 X 光透视**"——你要能把一帧里第 47 次 `vkCmdDraw` 的输入顶点、绑定的纹理、shader 的源码、uniform 的当前值、以及这次 draw 之前和之后 framebuffer 的样子,全部摊开来检查。这种能力,在 CPU 编程里没有对应物(CPU 你有 valgrind、有 sanitizer,但没有"抓一帧逐指令看状态");它是 GPU 这种"批量、异步、SIMT"机器逼出来的特殊工具类。学会用它,你才真正从"会用 GPU"跨到"**能 debug GPU**"——后者是工业级图形工程师和"读过 Vulkan 教程的人"之间真正的分水岭。

而且我要先告诉你一个反直觉的事实,它决定了这一篇的精神底色:**GPU 调试工具不是"出事才装的",而是"第一天就该装好、永远开着的"**。原因后面会展开,但请你先记住——等你屏幕黑了再装工具,你会面对一个完全没打 debug 标记的渲染器,那个 X 光机拍出来的是一片匿名 blob,你看不懂。生产级引擎从第一行代码就在每根 pipeline、每个 pass、每个 descriptor 上打了名字,这样出事时 X 光片才读得懂。这一篇不只是教你用工具,是教你**把工具的标记从一开始就编进你的渲染器**。

## 1 · 你要面对的两类 GPU bug

动手装工具之前,先理清你要 debug 的到底是什么。GPU 的 bug 大致分两类,工具也分两类——这两类的错位,是新手最常见的"工具用错了"的根源。

第一类,**正确性 bug**:画面错了。黑屏、颜色偏、贴图错位、mesh 扭曲、深度冲突、透明排序错、shader 算出来不是我想要的。这一类的核心特征是"**GPU 算了,但算错了**"——命令都执行了,没崩溃,没报错,只是结果和你期望的不一样。CPU 程序员对这种 bug 的本能反应是"加断点、看变量",但在 GPU 上你不能打断点(后面 shader printf 那节会讲为什么);你要做的是**事后取证**——抓一帧,逐 draw call 回放,看每一个中间状态。这类 bug 的工具是 **RenderDoc**、PIX、Nsight Graphics 这类**图形调试器(graphics debugger)**:它们的核心能力是"抓一帧,完整地、可回放地、可检视地保存下来,让你像看慢镜头回放一样检查每一个绘制步骤"。

第二类,**性能 bug**:画面是对的,但帧率太低。这一类的核心特征是"**GPU 算对了,但太慢了**"——某个 draw call 在 GPU 上跑了 12ms,把你的 16ms 帧预算吃光了一半。CPU 程序员对这种 bug 的本能反应是"开 profiler",这个直觉在 GPU 上仍然对——但**不是 RenderDoc**(RenderDoc 抓帧会让 GPU 跑得非常慢,它根本不能用来测性能),你要用的是 **GPU timestamp query** + **Tracy 的 GPU lane**(在 [phase-4 的 profiling-with-tracy](../phase-4/deep-dives/profiling-with-tracy.md) 已经讲过基础)。或者更深的厂商工具:NVIDIA 的 Nsight Graphics、AMD 的 Radeon GPU Profiler,它们能告诉你某个 shader 占了多少个 SM 周期、texture bandwidth 是多少、register pressure 高不高——这种深度,通用工具给不了。

记住这个分工,它在这一篇和后面所有 GPU 工作里都成立:**画面错 → 图形调试器(RenderDoc);帧率低 → GPU profiler(timestamp + Tracy + 厂商工具)**。把 RenderDoc 当 profiler 用、把 profiler 当 debugger 用,都是新手典型的弯路。这一篇两者都讲,但中心在 RenderDoc——因为性能 bug 的工具链 phase-4 已经铺过基础了,而正确性 bug 的工具链(RenderDoc 这条线)是你现在最缺的。

## 2 · RenderDoc:跨厂商、跨 API 的图形调试器

我把这一篇绝大多数篇幅给 RenderDoc,理由是它在 Linux 上能跑、跨 NVIDIA/AMD/Intel、跨 Vulkan/D3D/OpenGL/Metal、开源免费、是 indie 和中型工作室事实上的标准。其他工具(PIX、Nsight)更专精,但 RenderDoc 是你必须先掌握的"主武器",它代表了一整类工具的工作方式。学会了 RenderDoc,PIX 几乎是同一套思路的 D3D 版本,Nsight 是同一套思路加更深 counter 的 NVIDIA 版本。

RenderDoc 的工作模型,要用一句话讲清楚:**它在你的程序和 GPU 驱动之间插入一层,完整地记录一帧之内你的程序发给 GPU 的所有 API 调用、所有资源、所有中间状态,然后让你在 GUI 里逐个 draw call 地回放、检视**。注意"完整地记录"和"逐个回放"这两件事——前者意味着抓一帧会让你的程序变慢、内存占用暴涨(RenderDoc 自己要存所有纹理、buffer 的快照),所以**抓帧时不要测性能**;后者意味着你拿到的是一份**可重放的静态艺术品**,你可以反复看这一帧,看一百次都行,帧本身不变。

这个工作模型有几个推论你要想清楚。第一,**RenderDoc 抓的是"一帧",不是"程序运行的过程"**。你启动游戏,渲染 5000 帧,RenderDoc 在某一帧上按下 capture,它存下的是这一帧——只有这一帧——里你提交给 GPU 的所有命令。如果你要 debug 的 bug 是"游戏运行 10 分钟后开始漏内存导致渲染错乱",RenderDoc 没法直接帮(那是性能/资源泄漏,要用别的工具);它擅长的是"**这一帧画面错了,这一帧里哪一步算错了**"。第二,**RenderDoc 抓的是 API 层,不是硬件层**。它看到的是你提交的 Vulkan 命令、绑定的资源、设置的常量,它不知道 GPU 硬件内部某个 warp 在哪个时钟周期跑了什么——那是 Nsight 这种厂商工具的地盘。所以 RenderDoc 能告诉你"vertex shader 收到的 UV 是 0.7",但它不能告诉你"采样这个 UV 的纹理 fetch 占了几个周期"。

第三,也是新手最容易忽略的:**RenderDoc 在 Linux 上需要你以特定方式启动程序,而且 Wayland 支持有限**。在 X11 下,你直接在 RenderDoc GUI 里填你的可执行路径、工作目录、参数,点 Launch,RenderDoc 就 fork 你的进程并注入它的拦截层。但 Vulkan 程序在 Wayland 下要靠 VK_KHR_external_memory 之类的扩展才能被 RenderDoc 干净地拦截——遇到抓帧失败,先 `echo $XDG_SESSION_TYPE` 看看是不是 Wayland,是的话切到 X11 或者用 `GDK_BACKEND=x11` 之类的环境变量跑。这不是 RenderDoc 的锅,是 Linux 显示服务器过渡期的现实,你做图形开发迟早要撞上。

装它,在 Arch 上是一行:

```bash
sudo pacman -S renderdoc
```

装完,在应用菜单或者终端启动 `renderdoc`(`qrenderdoc` 是它的 GUI,`renderdoccmd` 是命令行)。GUI 启动后,左下 "Launch Application" 那里填可执行路径和工作目录,Environment 里加上 `VK_INSTANCE_LAYERS=VK_LAYER_LUNARG_standard_validation`(或者你已经在代码里开验证层就不用),Executable Path 指向你 `cargo build` 出来的 debug 二进制(在 `target/debug/your_game`),然后 Launch。你的游戏会启动,RenderDoc 主窗口会有一个 "Capture" 按钮(F12 或者 F11,看版本),按下它就抓当前帧。抓完后,主窗口的 Capture 列表里会出现那一帧,双击打开,你就进入了 X 光机的内部。

## 3 · 一帧的解剖:Pipeline State、Texture Viewer、Buffer Viewer

打开一份 capture,你会看到一个分成多栏的窗口。新手第一眼会懵——这么多面板、这么多 tab、这么多树状结构。我带你走一遍一个真实场景,把每个面板是干嘛的讲清楚。场景是这样:你 09C-7 加了一张贴图,三角形应该显示这张图,但屏幕上贴图被压缩成了左上角四分之一(典型 UV 范围错)。你 capture 这一帧,现在要找出问题在哪。

**Event Browser(事件浏览器)** 是最左边的面板,它列出了这一帧内你提交的所有 API 调用,按顺序排列。每个调用是一个事件,有编号(E1、E2……)和类型(VkQueueSubmit、VkCmdBeginRenderPass、VkCmdBindPipeline、VkCmdDraw……)。这一帧里你的渲染应该长这样:`vkAcquireNextImage` → `vkQueueSubmit`(里面包着 `vkCmdBeginRenderPass`、`vkCmdBindPipeline`、`vkCmdBindVertexBuffers`、`vkCmdBindDescriptorSets`、`vkCmdDraw`、`vkCmdEndRenderPass`)→ `vkQueuePresentKHR`。你在 Event Browser 里点击 `vkCmdDraw` 那一行——这是真正的"画"动作,前面都是准备,到 draw 才真的往 framebuffer 上写像素。点中它,右边所有面板就显示**这一次 draw 时,GPU 的完整状态**。

**Pipeline State(管线状态)** 是你这次 debug 的主战场。它把当前 draw 用到的 graphics pipeline 完整地展开——你点开 "Vertex Input",能看到绑定的 vertex buffer 的 binding、stride、attribute 的 location/format/offset。你点开 "Input Assembly",能看到是 TRIANGLE_LIST 还是 STRIP。点开 "Rasterizer",cull mode、front face、polygon mode 都在。点开最关键的 "Vertex Shader"——RenderDoc 会**反编译**当前绑定的 shader,显示源码(如果 SPIR-V 里有 debug info,它甚至能显示原始 GLSL 行号),并且**逐行展示当前这次 draw 用的 uniform 值**。你在这能看见 vertex shader 里 `gl_Position` 是怎么算的、UV 是怎么从 attribute 流过来的、MVP 矩阵的当前 16 个浮点数是什么。我们的 UV 错位 bug,你多半会在这一栏发现:`a_uv` 的 attribute 格式被设成了 `R32G32_SFLOAT` 但 stride 给成了 32 字节(实际一个顶点是 24 字节),所以 GPU 每跳一个顶点就多走 8 字节,UV 自然错位——这种 bug 你 `println!` 一万年也看不见,因为 vertex buffer 的字节在内存里是对的,错的是 pipeline 里描述它的"配方"。

**Texture Viewer(纹理查看器)** 是你看图的面板。它最上面有一个下拉框,列了当前所有可查看的纹理——swapchain image、你绑定的纹理、depth attachment、各种中间 render target。选一个,它就把这张纹理显示出来,你可以缩放、看 mipmap 层级、看不同通道(R / G / B / A 单独看,像素范围会标出来)。最强大的功能在底部:**Pixel History(像素历史)**。你选 swapchain image,然后右键点击画面上"UV 错位"那个区域的某个像素,选 Pixel History——RenderDoc 会列出**这一帧里所有写过这个像素的 draw call**。我们的场景只有一个 draw call,所以列表里就一行;但在真实场景里(几十上百个 draw call),Pixel History 是你回答"为什么这个像素是这个颜色"的神器——你能看到每个 draw call 写之前的颜色、写之后的内容、blend 的中间结果。新人第一次用 Pixel History 会震惊:这种能力 CPU 编程里完全没有,这是 GPU 调试独有的"事后取证"。

**Buffer Viewer(buffer 查看器)** 让你看 vertex buffer、index buffer、uniform buffer 的原始内容。你点开 vertex buffer 标签,RenderDoc 显示一个表格:每行一个顶点,每列一个属性(position.x、position.y、position.z、uv.x、uv.y、normal……)。你可以一眼看出"啊,第 47 个顶点的 UV 是 (-0.3, 1.4),超出了 [0,1] 范围,采样 wrap 模式下自然显示成左上角四分之一"——这是经典 UV 越界。**Buffer Viewer 看的是"原始字节怎么被解析成结构"**,它既能告诉你字节是什么,也能告诉你 pipeline 把这些字节解析成了什么(因为它读 pipeline 的 vertex input 描述)。这个 panel 在 debug 顶点数据、index buffer 错位、uniform 上传错位时是救命工具。

最后是 **Shader(着色器面板)**——你点 Pipeline State 里某个 shader stage,会跳到对应的反编译窗口。RenderDoc 反编译 SPIR-V 的能力这几年进步很大,基本能还原成可读的 GLSL。更骚的功能是 **shader 编辑重跑**——你直接在 RenderDoc 里改 shader 源码,点 "Save and Reload",RenderDoc 在 capture 内部重编 shader、重新跑那一帧、显示新结果。这是定位"shader 算法对不对"的快速反馈环——你不用每次改 shader 都重启游戏、重新抓帧,在 capture 里直接试。这个功能在 SPIR-V 重编上依赖 driver 支持,某些驱动会失败,但试一试总是值得的。

把上面这几个面板组合起来,你就能完成一次完整的"事后取证"。回到我们的 UV 越界 bug:在 Event Browser 点中那次 draw → Pipeline State 里看 vertex input stride → 发现 stride 是 32 但你的顶点结构是 24 字节 → 改 pipeline 创建代码,stride 改回 24 → 重跑游戏,贴图正常。**整个 debug 过程没改一行业务逻辑,只改了 pipeline 描述里的一个数字**——这种 bug,任何 CPU 工具都定位不到,只有图形调试器能精确定位。这就是为什么我说"GPU 调试的核心动作是逐 draw call X 光",这一节你应该已经建立了对"X 光机能拍出什么"的直观感受。

## 4 · 调试一次"颜色偏暗"的真实 bug

让我把上一节的面板介绍,串成一个完整的真实调试叙事,你能照着搬到自己的项目里。这是一个我亲手 debug 过的 bug,场景非常典型。

**症状**:fragment shader 里我做了简单的 Lambert 光照,期望 mesh 显示成中性灰,但实际显示成一种很暗的深灰,几乎看不见。

**错误的直觉**:`println!` MVP 矩阵——对。`println!` 光照方向——对。`println!` 光照颜色(0.5, 0.5, 0.5)——对。一切 CPU 数据都对。我开始怀疑是 fragment shader 写错了——但我盯着 `diffuse = max(dot(normal, light_dir), 0) * light_color`,看不出毛病。

**用 RenderDoc**:capture 一帧,在 Event Browser 点那次 draw,直接跳到 Texture Viewer 看 swapchain image——确认画面是暗的(像素 RGB 大概是 0.05,0.05,0.05)。然后回到 Pipeline State,点开 Fragment Shader,RenderDoc 反编译出来,我看 `texture` 那一行——它采样了 `sampler2D u_albedo`,但**我这次 draw 根本不应该采样 albedo 纹理**(这是无纹理 mesh)。继续往下看,fragment shader 把 `diffuse * tex_color` 算出来了,`tex_color` 默认值是 (0,0,0,0)——因为没绑纹理时,采样器返回的是黑色,乘以光照就是接近黑。

**真相**:我在创建 descriptor set 时,本来不该绑 albedo binding 的 mesh,我复制粘贴了一个绑了 albedo 的 descriptor 模板,没把那个 binding 解绑。`vkCmdBindDescriptorSets` 把一个绑了黑色纹理的 set 绑上了,fragment shader 老老实实采样,得到黑色。CPU 那边我打印的"光照参数"全对,但 GPU 这边 fragment shader 用的不是我以为的"无纹理"分支,而是采样了一个我没意识到还绑着的纹理。

**修复**:descriptor set 创建代码里,根据 mesh 是否有纹理走不同模板,无纹理的 mesh 用一个空 binding 而不是复制粘贴。这是个 5 行的 fix,但**只用 CPU 工具我可能要花一整天**——因为我根本不会想到去怀疑 descriptor binding,我以为我打印过 descriptor 是对的(我打印的是 CPU 端的 descriptor layout,不是运行时绑的那个 set 的内容)。RenderDoc 在 Pipeline State 里直接显示"当前这次 draw 绑的 descriptor set 的每一个 binding 内容是什么",我才看见那个 albedo binding 不该在那里。

这个案例讲完了,我希望你抽身出来看一件事:**GPU 调试的本质,是看见"运行时绑定的资源是什么",而不是"代码里我以为绑定的是什么"**。代码里你写 `bind_descriptor_set(set_a)`,你以为绑的是 set_a,但 set_a 是怎么创建的、它在 GPU 上的真实内容是什么、它有没有被前面的命令改过——这些 CPU 端看不见,只有图形调试器能拍给你看。培养这种"不要相信我以为,去看 GPU 看到的"心智,是 GPU 工程师的核心能力。

## 5 · 给你的渲染器打标记:VK_EXT_debug_utils

到这里你应该已经体会到 RenderDoc 的强大,但你也应该已经看出一个隐患:**默认情况下,RenderDoc 的 capture 里所有东西都是匿名的**。pipeline 显示成 "Pipeline 0x1234abcd",descriptor set 显示成 "Descriptor Set 7",texture 显示成 "Image 0xabcd",你打开 capture 一片"哪个是哪个"。在只有 1 个 draw call 的玩具 demo 里这无所谓,在你 HH 真实项目里(几十个 pipeline、上百个纹理、上千个 draw call)这是灾难——你看着一堆匿名 ID,根本不知道哪一行对应"玩家 mesh 的不透明 pipeline"、哪一行对应"G-Buffer 的 normal attachment"。X 光机拍出来了,但你读不懂那张片。

这就是 Vulkan 给你准备的第一个 debug 扩展该上场的地方:**`VK_EXT_debug_utils`**。这个扩展提供三件事,我一个个讲:**object naming**(给 Vulkan 对象打人类可读的名字)、**command region**(把命令缓冲里的一段命令标记成一个有名字的区域)、**message labeling**(给单次 draw call 加标签)。

Object naming 是最常用也最值的。你创建 pipeline 时,顺手给它打一个名字:

```rust
use ash::ext::debug_utils;

fn name_object(device: &ash::Device, object: u64, object_type: vk::ObjectType, name: &str) {
    #[cfg(feature = "debug")]
    {
        let name_c = std::ffi::CString::new(name).unwrap();
        let info = vk::DebugUtilsObjectNameInfoEXT::default()
            .object_type(object_type)
            .object_handle(object)
            .object_name(&name_c);
        let fp = device
            .fp_fn::<debug_utils::Device>()  // 概念示意,真实代码用 loader 加载
            .set_debug_utils_object_name;
        unsafe { fp(device.handle(), &info); }
    }
}

// 给 pipeline 打名字
name_object(
    &device,
    vk::Pipeline::as_raw(opaque_pipeline),
    vk::ObjectType::PIPELINE,
    "opaque_geometry_pipeline",
);

// 给 image 打名字
name_object(
    &device,
    vk::Image::as_raw(albedo_texture),
    vk::ObjectType::IMAGE,
    "hero_albedo_texture",
);
```

这一段代码看起来繁琐,实际效果是:在 RenderDoc 的 capture 里,这些对象不再显示成匿名 ID,而是显示成 "opaque_geometry_pipeline"、"hero_albedo_texture"。Event Browser 里每次 `vkCmdBindPipeline` 后面会标 "(opaque_geometry_pipeline)",Texture Viewer 的下拉框里你能直接找到 "hero_albedo_texture"。一个用 debug 名字标记过的 capture,和没标记过的 capture,可读性是天壤之别——前者你能像读代码一样读 capture,后者你只能猜。

Command region(debug marker region)是第二件事。你可以在录制命令缓冲时,把一段命令包成一个有名字的 region:

```rust
// 概念示意
unsafe {
    let label = vk::DebugUtilsLabelEXT::default()
        .label_name(c"shadow_pass")
        .color([0.5, 0.3, 0.1, 1.0]);  // 可选,给 region 上色
    fp.cmd_begin_debug_utils_label(cmd, &label);

    // ... 录制 shadow pass 的所有 cmd:bind pipeline、bind descriptor、draw、draw、draw ...

    fp.cmd_end_debug_utils_label(cmd);
}
```

在 RenderDoc 的 Event Browser 里,这一段命令会被折叠成一个 "shadow_pass" 的 region,你能展开看里面的细节,也能折叠起来只看 region 级别的概览。在真实渲染器里(几十个 pass),region 让 capture 从"几百个扁平 draw call"变成"shadow pass、G-Buffer pass、lighting pass、transparent pass、post-process pass"这样的结构化视图——和你的 [09B-3 frame graph](09B-3-frame-graph.md) 一一对应。这是把 capture 从"原始 API 流"翻译成"渲染管线语义"的关键标记。

第三件,message label,是给单次 draw call 加注释,通常用得少,但在你做 GPU profiler 时有用——单次 draw 加一个 tag,profiler 把这个 draw 显示成你给的名字。日常调试 region + object name 就够了。

我必须强调一个反直觉但极其重要的工程原则:**debug 标记应该从渲染器的第一行代码就开始打,而不是"等出事再加"**。原因是双重的。第一,如果你等出事再加,你会面对一个"要不要给几百个对象补打标记"的庞大重构,你的本能是拖延,然后你的下一次 debug 仍然是匿名 capture 的痛苦。第二,debug 标记的开销几乎为零——这个扩展的 call 在生产 release 里完全可以编译进去(不像验证层那样有几十个百分点开销),`set_debug_utils_object_name` 也就是几十纳秒,而且现代驱动会忽略它(在 driver 不支持 VK_EXT_debug_utils 时),所以你可以在 release build 里也留着。许多大厂(Insomniac、Naughty Dog)的内部规范就是"**任何 Vulkan 对象创建后必须立刻打 debug 名字,否则 code review 不过**",这是 GPU 工程的卫生习惯,而不是优化。

实现上,我建议你把 debug 标记封装成一个 trait,所有"创建 Vulkan 对象"的工厂函数都自动给它打名字:

```rust
pub trait VkObjectWithName: Sized {
    fn raw_handle(&self) -> u64;
    fn object_type() -> vk::ObjectType;
}

pub fn create_and_name<T: VkObjectWithName>(
    device: &ash::Device,
    name: &str,
    create_fn: impl FnOnce() -> T,
) -> T {
    let obj = create_fn();
    #[cfg(feature = "debug_names")]
    name_object(device, obj.raw_handle(), T::object_type(), name);
    obj
}

// 调用方:
let pipeline = create_and_name(
    &device,
    "opaque_geometry_pipeline",
    || create_opaque_pipeline(&device, ...),
);
```

这种设计让"创建即打标记"变成默认行为,新人写代码自动获得 debug 名字,完全不需要纪律。这就是 [phase-4 profiling-with-tracy](../phase-4/deep-dives/profiling-with-tracy.md) 里讲 Tracy zone macro 时说的同一个原则在 GPU 这边的翻版:**instrumentation 不能靠纪律,要靠默认**。

## 6 · GPU timestamp query:测一帧里 GPU 到底花了多久

正确性 bug 用 RenderDoc 解决了,现在我们处理第二类——性能 bug。GPU 性能调试的核心工具是 **timestamp query(时间戳查询)**,这是 GPU 自己告诉你"我在这个时间点在做什么"的机制。

CPU profiler 测时间的方法是 `Instant::now()`,你已经在 [phase-4 profiling-with-tracy](../phase-4/deep-dives/profiling-with-tracy.md) 写过 `let t0 = Instant::now(); expensive(); let t1 = Instant::now(); let dt = t1 - t0;`。这在 CPU 上工作,是因为 CPU 你直接在跑代码的线程上,`Instant::now()` 读的是同一个时钟。但 GPU 不行——你 `vkQueueSubmit` 之后,CPU 立刻继续跑,去准备下一帧;GPU 在后面异步执行。CPU 上的 `Instant::now()` 测的是"submit 这个调用花了几纳秒",不是"GPU 执行这些命令花了几毫秒"——这两件事差几个数量级。

GPU timestamp query 解决这个问题,机制是这样的。你在创建 device 时打开一个 `QueryPool`,类型是 `TIMESTAMP`,里面能存 N 个 64 位时间戳。然后你在录制命令缓冲时,在你想测的位置插 `vkCmdWriteTimestamp`——这个命令告诉 GPU "当你执行到这一行的时候,把当前的 GPU 时钟值写进 query pool 的第 K 个槽位"。GPU 异步执行到这行时,会真的把它的内部时钟(纳秒级精度)写到 query pool。CPU 之后用 `vkGetQueryPoolResults` 把这些时间戳读回来,算两个时间戳的差,就是这两点之间 GPU 上花了多少纳秒。

代码长这样:

```rust
// 创建 query pool,装 64 个时间戳
let query_pool = unsafe {
    let info = vk::QueryPoolCreateInfo::default()
        .query_type(vk::QueryType::TIMESTAMP)
        .query_count(64);
    device.create_query_pool(&info, None).unwrap()
};

// 在命令缓冲里,记录每一段 pass 的时间戳
unsafe {
    // pass 开始前:写一个时间戳到 slot 0
    device.cmd_write_timestamp(
        cmd,
        vk::PipelineStageFlags::TOP_OF_PIPE,  // 在 pipeline 起始阶段写
        query_pool,
        0,
    );

    device.cmd_begin_render_pass(cmd, &shadow_pass_info, vk::SubpassContents::INLINE);
    // ... shadow pass 的 draw ...
    device.cmd_end_render_pass(cmd);

    // shadow pass 结束后:写时间戳到 slot 1
    device.cmd_write_timestamp(
        cmd,
        vk::PipelineStageFlags::BOTTOM_OF_PIPE,
        query_pool,
        1,
    );

    // lighting pass ...
    device.cmd_write_timestamp(cmd, vk::PipelineStageFlags::BOTTOM_OF_PIPE, query_pool, 2);
    // post-process pass ...
    device.cmd_write_timestamp(cmd, vk::PipelineStageFlags::BOTTOM_OF_PIPE, query_pool, 3);
}

// 几帧之后(GPU 是异步的,timestamp 要等命令执行完才能读)
// 把 slot 0..3 读回来
let mut timestamps = [0u64; 4];
unsafe {
    device.get_query_pool_results(
        query_pool,
        0,                          // start query
        4,                          // query count
        &mut timestamps,
        vk::QueryResultFlags::RESULT_64 | vk::QueryResultFlags::RESULT_WAIT_AVAILABLE,
    ).unwrap();
}

// 算每个 pass 的 GPU 耗时
// 注意:GPU timestamp 的单位需要先 query VK_KHR_calendar_sync 或者
// device properties 的 timestampPeriod(纳秒 per tick)来换算
let ns_per_tick = physical_device_properties.limits.timestamp_period;
let shadow_ns = (timestamps[1] - timestamps[0]) as f32 * ns_per_tick;
let lighting_ns = (timestamps[2] - timestamps[1]) as f32 * ns_per_tick;
let post_ns = (timestamps[3] - timestamps[2]) as f32 * ns_per_tick;
println!("shadow: {:.2} ms", shadow_ns / 1e6);
println!("lighting: {:.2} ms", lighting_ns / 1e6);
println!("post: {:.2} ms", post_ns / 1e6);
```

这段代码的核心是:**这些时间戳是 GPU 自己写的,不是 CPU 测的**。所以它们反映的是 GPU 真实的执行时间——你看见 "shadow pass 在 GPU 上花了 1.8 ms",这是 GPU 报告的,不是 CPU 估算的。这就是为什么 timestamp query 是 GPU 性能调试的唯一权威手段。

`PipelineStageFlags` 是这里一个微妙但重要的概念。`vkCmdWriteTimestamp` 接受一个 pipeline stage 参数,告诉 GPU "在 pipeline 的哪个阶段写时间戳"。`TOP_OF_PIPE` 是 pipeline 的最开始(GPU 接到这条命令立刻写),`BOTTOM_OF_PIPE` 是 pipeline 的最末尾(所有 stage 都跑完才写)。所以 `shadow_pass` 的开始用 `TOP_OF_PIPE`,结束用 `BOTTOM_OF_PIPE`,你能测出从 GPU 开始执行到完全结束的墙钟时间。这个 stage 选择直接决定你测的是"开始/结束调度"还是"开始/结束执行",搞混了会得到误导性的数字。

这里有几个新手必踩的坑,我提前讲。第一,**timestamp 的单位不是直接的纳秒**——GPU 写的是它的内部 tick 计数,你需要用 `limits.timestamp_period`(每个 tick 是多少纳秒)换算。有些 GPU 这个值是 1(1 tick = 1 ns),有些是 0.5(2 tick = 1 ns),不查就出大错。第二,**timestamp 有数量限制**——`limits.max_query_pools`、`max_timestamp_compute_queries` 之类,某些移动 GPU 只允许每帧 4096 个 timestamp,所以你不能给每个 draw call 都打,要按 pass 分组。第三,**timestamp 读回是异步的**——你不能 submit 后立刻 `vkGetQueryPoolResults`,那时 GPU 还没跑完,你要么用 `RESULT_WAIT_AVAILABLE`(阻塞 CPU 等,违背异步哲学),要么轮询 `vkGetQueryPoolResults` 看是否 ready,要么用 fence 等命令缓冲完成后读。生产代码常用 ring buffer——你这一帧读上一帧的 timestamp,接受 1 帧延迟,避免阻塞。

把 timestamp 接进 Tracy 是顺理成章的下一步。Tracy 的 GPU zone([phase-4 已经讲过原理](../phase-4/deep-dives/profiling-with-tracy.md))底层就是这么实现的——它替你管理 query pool 的 ring buffer、替你异步读 timestamp、替你把 GPU 时间戳和 CPU 时间戳对齐(用一个 calibration zone 测两者时钟差),让你在 Tracy 的统一时间线里看见 CPU lane 和 GPU lane 并排显示。在 Rust 这边,你想自己 raw 写 Vulkan timestamp 用上面的代码,你想用 Tracy 一站式管理就引入 `tracy-client` + 它的 GPU hook。我推荐**先用 raw timestamp 跑通,理解它怎么工作,再用 Tracy 包装**——这样 Tracy 给你的 GPU lane 不是黑箱,你知道它底下在做什么。这种"先用底层理解,再用高层工具"的顺序,是这个序列的精神。

GPU timestamp 在生产里和 §5 的 debug marker 是天生一对。RenderDoc 的 capture 里,你打的 `vkCmdBeginDebugUtilsLabelEXT` region 会自动显示成时间轴上的彩色块,而 timestamp query 让你量化每个块花了多久。**理想状态:你的 frame graph(09B-3)自动给每个 pass 发 debug marker + 自动配 timestamp query,你抓帧 / 看 Tracy 都不需要手动加标记**——这就是为什么 frame graph 不只是性能优化工具,它也是 debug 工具的基础设施。后面 09E 你做 Vulkan 后端时,会真切体会这点。

## 7 · shader printf:终于,你能在 shader 里 print 了

回到正确性调试。前面几节你学会了用 RenderDoc 看每个 draw call 的状态,但有一种 bug RenderDoc 也不太能帮——**shader 内部计算错了**。RenderDoc 能告诉你"vertex shader 输入了这些 attribute、用了这些 uniform、输出了这个 gl_Position",但它**不能告诉你 vertex shader 中间某一行算的局部变量是什么**。比如你的 fragment shader 里 `vec3 half_vec = normalize(light_dir + view_dir); float spec = pow(dot(normal, half_vec), 32);`——你怀疑 spec 算出来不对,但你没办法看 half_vec 的值。RenderDoc 给你的是"边界"(输入输出),不是"内部"。

CPU 程序员的本能是加断点、加 print。GPU 之前没有真正的 print——shader 是 SIMT 在几千个线程上并行跑的,你 print 哪个线程的?如果每个线程都 print,几百万条 print 把显示和性能都炸了。所以在很长一段时间里,GPU 调试 shader 的"行业标准"是**把变量值编码成颜色输出**——你想看 normal,就 `outColor = vec4(normal * 0.5 + 0.5, 1.0);` 让 normal 变成可视颜色;你想看 UV,就 `outColor = vec4(uv, 0.0, 1.0);`。这个手法在 [phase-5 shader-basics](../phase-5/deep-dives/shader-basics.md) 已经讲过,简单有效,但代价大:你要改 shader 重新编译、重启游戏、抓帧、看颜色、再改回——一个调试循环要好几分钟。

现代 Vulkan 给了一个真正的 print:`VK_KHR_shader_non_semantic_info` 扩展(也叫 shader printf,或者 debug printf)。你在 shader 里写 `debugPrintfEXT(...)`——是的,GLSL 里能写 printf——编译成 SPIR-V 时这个调用会被保留,GPU 执行 shader 时,printf 的输出会被驱动捕获并通过 debug messenger 回调送回你的 CPU 程序。这样你终于在 shader 里能 print 了。

GLSL 里启用 printf,你要在 shader 顶部加 `#extension GL_KHR_shader_non_semantic_info : enable`,然后:

```glsl
#version 450
#extension GL_KHR_shader_non_semantic_info : enable

layout(location = 0) in vec2 a_uv;
layout(location = 0) out vec4 frag_color;

void main() {
    debugPrintfEXT("uv = (%.3f, %.3f)\n", a_uv.x, a_uv.y);
    frag_color = vec4(a_uv, 0.0, 1.0);
}
```

这个 shader 编译成 SPIR-V 时(用 `glslangValidator -VKHR` 或 shaderc),`debugPrintfEXT` 会被保留为非语义指令(non-semantic instruction),驱动认得这个扩展就在 GPU 上执行 print。CPU 端你要做的:开 `VK_KHR_shader_non_semantic_info` 这个 device extension,并且**关键**——printf 的输出是通过验证层的 debug messenger 流的,你要开 [09C-3](09C-3-command-buffers-and-synchronization.md) 讲过的验证层,printf 才能被路由回来。所以 printf 本质是验证层的功能,不是 driver 的功能,不要在 release 关了验证层然后奇怪 printf 不出。

shaderc / glslangValidator 编译时:

```bash
glslangValidator -VKHR --amb -o mesh.frag.spv mesh.frag
# -VKHR:VKHR 扩展模式(允许 GL_KHR_* 非语义指令)
```

CPU 端的回调长这样(你 09C-3 应该已经有 debug messenger,只要确认它的 message type 包含 `GENERAL`):

```rust
unsafe extern "system" fn debug_callback(
    _severity: vk::DebugUtilsMessageSeverityFlagsEXT,
    message_type: vk::DebugUtilsMessageTypeFlagsEXT,
    p_callback_data: *const vk::DebugUtilsCallbackDataEXT,
    _user_data: *mut std::ffi::c_void,
) -> vk::Bool32 {
    let msg = unsafe { (*p_callback_data).p_message };
    let c_str = unsafe { std::ffi::CStr::from_ptr(msg) };
    
    // shader printf 会以 "UNASSIGNED" 之类的 id 通过 message type = GENERAL 流过来
    eprintln!("[Vulkan] {}", c_str.to_string_lossy());
    vk::FALSE
}
```

跑起来,你的游戏控制台会出现 `uv = (0.234, 0.781)`、`uv = (0.412, 0.901)` 这样的输出——这是 GPU 上每个 fragment 调用 fragment shader 时 print 出来的 UV。

这里有几个你必须知道的现实。第一,**printf 在 GPU 上极慢**,每个线程一条 printf,几十万个 fragment = 几十万条输出,日志洪流且会拖慢 GPU。所以 **printf 只用于定位单个像素**——你通常加一个 guard,只在某个特定像素 print:

```glsl
void main() {
    if (abs(gl_FragCoord.x - 512.0) < 1.0 && abs(gl_FragCoord.y - 384.0) < 1.0) {
        debugPrintfEXT("uv at (512,384) = (%.4f, %.4f)\n", a_uv.x, a_uv.y);
    }
    // ...
}
```

这样你只 print 屏幕中心那个像素的 UV,几十万线程只 print 一条,性能可接受,信号也清晰。第二,**printf 的输出是异步的**——和 timestamp 一样,GPU 异步执行,你的 CPU 控制台可能延迟几帧才看到输出,要耐心。第三,**驱动支持参差**——NVIDIA 在 Vulkan 这块支持得早,AMD 略晚,某些移动 GPU 完全不支持。Linux Mesa 从 21.x 起对 NVIDIA / Intel 都支持得不错。

shader printf 不是日常工具,但当你 debug "shader 内部某个中间值错了"时,它是唯一能精确定位的工具。配合 RenderDoc(看 draw call 的输入输出)+ shader printf(看 shader 内部中间值),你有了 GPU 正确性调试的完整闭环。

## 8 · 其他工具:PIX、Nsight、Mesa 的 Linux 工具

RenderDoc 是主武器,但你应该知道还有其他工具,各有擅长。

**PIX** 是微软出品的、Windows + Xbox 上的图形调试器,完全免费。如果你做 D3D12 开发(在 Windows / Xbox 上),PIX 几乎是必装——它的 D3D12 支持深度比 RenderDoc 深。PIX 的工作模型和 RenderDoc 高度一致:抓一帧、逐 draw call 检视、看 pipeline state、看 texture、看 buffer、看 pixel history。它的特色是**shader debugging**——抓帧后,你可以选一个像素,PIX 让你**单步执行 fragment shader**,看每个变量在每一行的值,像 gdb 调试 CPU 代码一样。这是 RenderDoc 没有的能力(RenderDoc 只能反编译看源码,不能单步)。PIX 还能做 GPU timing capture、内存分析,功能比 RenderDoc 更"全套"。缺点是 Windows-only,你不能在 Linux 上跑 PIX。如果你跨平台开发,RenderDoc 是你的 Linux 主力,PIX 是 Windows 上的"加强版"。

**NVIDIA Nsight Graphics** 是 NVIDIA 出的、只支持 NVIDIA GPU 的图形调试 + 性能分析工具,免费。它和 RenderDoc / PIX 的最大不同是**深度**——Nsight 能告诉你 RenderDoc 看不见的硬件层数据:某个 shader 占了多少个 SM(Symmetric Multiprocessor)周期、texture bandwidth 是多少 GB/s、register pressure(register 使用量)有没有导致 occupancy(占空比)下降。这些数据对**极致 GPU 优化**是金矿,但对日常调试杀鸡用牛刀。Nsight 在 Linux 上支持得不错(Nsight Graphics 有 Linux 版),如果你是 NVIDIA 卡,可以同时装 RenderDoc(日常)+ Nsight(深度性能)。

**AMD Radeon Developer Tool Suite** 是 AMD 的对应工具集,包括 Radeon GPU Profiler(性能)、Radeon Memory Visualizer(显存布局)、Radeon Developer Tool(通用调试)。如果你是 AMD 卡,这些是你深度调试的主力。

**Mesa 的 Linux 工具**——这是 Linux 用户独有的福利,值得专门一节。Mesa 是开源的 OpenGL/Vulkan 实现,你的 Intel / AMD / 部分 NVIDIA 卡在 Linux 上跑的就是 Mesa。Mesa 提供一组命令行工具,不需要 GUI,极轻量。`vulkaninfo` 你 [09C-1 装过](09C-1-gpu-architecture-and-explicit-api.md),看 device 能力。`vkcube` / `vkcubepp` 是 Vulkan 的 hello world 测试。`vkvia`(Vulkan Capability Viewer)看更细的能力。`synchronization2` validation 是 Mesa 内置的同步检查器。最有用的是 `MESA_VK_WSI_PRESENT_MODE=immediate` 这种环境变量——你能强制 swapchain 的 present mode 调试 tearing 问题。`RADV_PERFTEST=...` 是 Mesa 的 RADV(Radeon Vulkan driver)的调试开关。当你遇到"在 NVIDIA 上跑得好,AMD/Mesa 上有诡异问题"时,这些 Mesa 工具是你的本地诊断手段。

**MangoHud** / **GOverlay**——这是 Linux 上的轻量 overlay,显示帧率、frame time、GPU 利用率、显存占用。它不是调试器,是"在玩游戏时看一眼 GPU 健康"的快速工具,适合在用户机器上诊断"是不是 GPU 满载了"。配合 vulkaninfo + RenderDoc,你在 Linux 上有完整的工具链。

什么时候用哪个?给你一个心智模型。**日常画面对错 bug**(90% 的 debug 工作):RenderDoc(跨平台)或 PIX(Windows D3D)。**性能 bug,要量化每个 pass GPU 时间**:自己写 timestamp query + Tracy(见 §6)。**性能 bug,要深挖硬件 occupancy / bandwidth**:Nsight Graphics(NVIDIA)或 Radeon GPU Profiler(AMD)。**Linux 特定问题**:Mesa 的命令行工具 + 环境变量。这套组合,你在 indie / 中型工作室能遇到的 99% GPU debug 场景都能覆盖。

## 9 · device lost:Vulkan 最让人心慌的崩溃

讲了一般 bug,现在讲一个特别让人崩溃的:**device lost(设备丢失)**。你 submit 了一帧,GPU 执行时撞上了某种硬件级别的错误(通常是非法内存访问、shader 无限循环、超时),驱动放弃了 GPU 状态,返回你一个 `VK_ERROR_DEVICE_LOST`。之后这个 device 就死了,所有后续的 vkQueueSubmit 都返回 DEVICE_LOST,你的程序基本只能退出。GPU 编程里,这是和 segfault 同等级别的灾难。

DEVICE_LOST 的可怕之处在于它**几乎不告诉你为什么**。驱动层面的 device lost,可能来自:shader 里写了 `while (true) {}` 让 GPU watchdog 超时(TDR,Timeout Detection and Recovery)、shader 写越界内存(`imageStore` 到 image 之外)、vertex buffer 地址错乱导致 GPU 读了未映射页、显存被 OOM 干掉、driver 自己的 bug。驱动通常只给你一个 "GPU hang on queue 0" 的消息,具体哪个命令、哪个 shader 触发的,你不一定能拿到。你必须自己**二分**地找。

排查 DEVICE_LOST 的策略,我整理成一个清单:

第一步,**开验证层**。99% 的 DEVICE_LOST 在验证层下会先报具体错误——你某个 descriptor 绑了空 buffer、某个 pipeline 的 vertex input 描述和实际 buffer 不匹配、某个 shader 用了不存在的 binding。验证层是"为什么 Vulkan 会拒绝你"的权威解释器,在它说话之前,任何猜测都是浪费时间。这是 [09C-3](09C-3-command-buffers-and-synchronization.md) 反复强调的"没开验证层写 Vulkan 等于盲飞",DEVICE_LOST 是验证层价值的最佳证明。

第二步,**二分 draw call**。如果验证层没报错,但 submit 还是 DEVICE_LOST,问题出在某个具体 draw 里。你 comment 掉一半 draw(或者在你的渲染器里加一个 "只画前 N 个 mesh" 的开关),看还崩不崩。崩 → 问题在剩下那半;不崩 → 问题在 comment 掉的那半。log(N) 次二分你能锁定到具体那个 draw call。这是 CPU 调试里也用的通用手法(bisect),但在 GPU 上特别重要——因为 GPU 异步,你没法直接看"哪个命令触发了崩溃",你只能二分。

第三步,**抓 RenderDoc 帧**。但要注意——DEVICE_LOST 通常发生在 GPU 执行期间,RenderDoc 在 capture 时也会让 GPU 执行命令,所以 capture 可能触发同样的崩溃,你拿不到 capture。这种情况下,你在 RenderDoc 里**降低渲染负载**(少画 mesh、关后处理),让 capture 能成功,然后逐步加回去,二分出问题区。RenderDoc 的好处是即使 capture 失败,它前一段的 API 流你能看,你能在 Event Browser 里看到崩溃前最后一次成功执行的命令。

第四步,**检查超时**。Linux / Windows 有 GPU watchdog(Windows 是 TDR,默认 2 秒;Linux Mesa 也有类似机制)。你的 shader 如果跑超过这个时间,driver 强制 reset,报 DEVICE_LOST。debug 时你可以临时延长 watchdog(Windows: 改注册表 `TdrDelay`;Linux: 某些驱动通过环境变量),先让 GPU 跑完,看到底是不是计算量太大、shader 写得太低效。

第五步,**显存 OOM 检查**。Vulkan 有 `VK_EXT_memory_budget` 扩展,你能 query 每种内存类型的当前占用。如果你的程序每帧分配纹理不释放(典型的资源泄漏),某帧 OOM,driver 可能报 DEVICE_LOST 而不是 OUT_OF_MEMORY(取决于 driver 行为)。在生产里你应该 hook 每一次 `vkAllocateMemory` 计数,定期查 budget,提前告警。

DEVICE_LOST 是 Vulkan 编程里最痛苦的部分之一,因为它破坏了你的反馈环——你 submit 后看不到执行结果。学会这套排查心法,你才不会在 device lost 时束手无策。

## 10 · 生产现实:把 X 光机焊进你的渲染器

讲到这里,你应该已经看清这一篇的真正主题——不是"工具的清单",而是"**怎样让你的渲染器从第一天就准备好被 debug**"。我必须把这个原则推到底,因为它决定了你职业生涯里 GPU debug 的痛苦程度。

新手的心态是"先让东西跑起来,debug 工具以后再说",于是写了一个完全没打 debug 标记的渲染器,等到第一个真 bug 出现(总是会出现,而且总是出现在你最忙的时候),他抓一份匿名 capture,看见一堆 "Pipeline 0x1234abcd",崩溃,然后花一周打补丁式地给现有代码加 debug 名字。这种事我见过太多次。

正确的心态是:**debug 基础设施是你渲染器架构的一部分,不是后期优化**。具体到 Vulkan,你应该:

第一,**所有 Vulkan 对象创建时立即打 debug 名字**(§5 讲过的 `VK_EXT_debug_utils`)。封装成 trait,让"创建即命名"是默认行为,新写的代码自动获得。

第二,**所有 pass 在录制命令缓冲时用 `cmd_begin_debug_utils_label` / `cmd_end_debug_utils_label` 包 region**(§5)。最好让你的 [frame graph(09B-3)](09B-3-frame-graph.md) 自动发这些 marker——每加一个 pass 自动配 region 名字,你写代码的人不用手动加。这就是为什么 frame graph 不只是性能抽象,它也是 debug 抽象。

第三,**所有 pass 自动配 GPU timestamp query**(§6)。同样,frame graph 自动给每个 pass 的 begin/end 配 timestamp,你不需要手动埋点。这样你的 Tracy GPU lane 永远显示完整的 per-pass 时间,出 bug 时直接看。

第四,**这些 debug 标记全部 feature-gated**,在 release 里可以关闭(虽然开销很小,但更干净):

```rust
[features]
debug = ["dep:debug_utils_loader"]  # 启用 debug 名字、region、shader printf

[profile.release]
# release 也可以保留 debug feature,因为开销几乎为零
# 但某些发行版会想关掉
```

第五,**和 CPU profiling 整合**。你 [phase-4 已经有 Tracy CPU profiling](../phase-4/deep-dives/profiling-with-tracy.md),GPU timestamp 加上之后,你应该用 Tracy 的 GPU zone(它内部就是 timestamp query + calibration)把 GPU lane 接进同一个 Tracy 时间线。CPU 的 "render_submit" zone 和 GPU 的 "shadow_pass" / "lighting_pass" zone 在同一条时间线上,你能看见 "CPU submit 用了 0.3 ms,GPU 执行 shadow 用了 1.8 ms,GPU 执行 lighting 用了 4.2 ms" 这种**CPU 和 GPU 一体化视图**——这是定位"卡帧是 CPU 准备慢还是 GPU 算慢"的唯一精确方法。

这一节我希望你抽身看一件事:GPU 工具链不是几个独立工具的集合,它是一个**和你的渲染器共同生长的、深度耦合的调试基础设施**。RenderDoc / Tracy / Nsight 是"显示端",你的渲染器是"信号源",如果信号源没打好标记,显示端再强也读不出有用信息。生产级引擎(Unreal、Bevy)的渲染层之所以 debug 体验好,不是因为它们的 RenderDoc 用得熟,是因为它们的代码里 debug 标记打得密、打得早、打得自动。这是你要在你 HH 项目里建立的习惯。

## 11 · 在你 HH 项目里动手(做中学红线)

这一篇的动手,把你 09C-7/09C-8 的 Vulkan 后端"装上 X 光机"。结束时,你能用 RenderDoc 抓一份 HH 的帧,看到带语义名字的 pipeline / texture / pass,并且能用 GPU timestamp 报告每帧每段 GPU 耗时。

第一步,**装 RenderDoc**。Arch 上 `sudo pacman -S renderdoc`。如果你是 NVIDIA,可选 `sudo pacman -S nsight-graphics`(可选,RenderDoc 已经够这一篇用)。启动 RenderDoc GUI,确认它能跑。

第二步,**修改你的 Vulkan 后端,接入 `VK_EXT_debug_utils`**。在 instance creation 时,把 `VK_EXT_DEBUG_UTILS_EXTENSION_NAME` 加进 enabled extension 列表(你 09C-2 应该已经有这个)。在 device creation 时,把同样的扩展加进 device extension 列表(为了 `cmd_begin_debug_utils_label` 等 device 级函数)。加载这些函数指针(ash 在 `ash::ext::debug_utils` 模块里直接给了 typed wrapper,你不用手动 load)。

第三步,**写一个 `name_object` 工具函数**(§5 给了代码)。给它配一个 trait `VkObjectWithName`,让 pipeline / image / buffer / render pass / framebuffer / descriptor set 都实现。每个对象创建后,立刻 `name_object` 给它打一个有意义的名字:`"opaque_geometry_pipeline"`、`"hero_albedo_texture"`、`"swapchain_image_0"` 等。

第四步,**给所有 pass 加 region**。你 09C-8 迁移的那个 pass,在 `cmd_begin_render_pass` 之前调 `cmd_begin_debug_utils_label(c"opaque_geometry_pass")`,在 `cmd_end_render_pass` 之后调 `cmd_end_debug_utils_label`。如果你已经接入 frame graph,这一步应该自动,你只是确认。

第五步,**抓一份 RenderDoc 帧**。在 RenderDoc GUI 里填你的 HH 可执行路径,Launch。HH 启动后,等画面稳定,按 F12 抓一帧。打开 capture,在 Event Browser 里你应该看见 region "opaque_geometry_pass",里面 `vkCmdBindPipeline` 后面标着 "(opaque_geometry_pipeline)",Texture Viewer 里你应该能找到 "hero_albedo_texture"。**这就是验收点:capture 里你能用语义名字找到你的资源,而不是匿名 ID**。

第六步,**加 GPU timestamp**。创建一个 64-slot 的 `QueryPool`(§6 给了代码)。在你 record_frame 里,pass 开始前 `cmd_write_timestamp(slot=0)`,pass 结束后 `cmd_write_timestamp(slot=1)`。几帧后(用 ring buffer 处理异步)读 query pool,算出 GPU 耗时,`println!` 到控制台。**这是第二个验收点:你能看到"opaque pass 在 GPU 上花了多少毫秒"**。

第七步,**可选但强烈推荐**:把 timestamp 接进 Tracy。引入 `tracy-client` crate([phase-4 已经讲过怎么集成](../phase-4/deep-dives/profiling-with-tracy.md)),用 `tracy_client::span!` 给 CPU 代码加 zone,用 tracy 的 Vulkan GPU hook([`tracy_client::gpu`] 或自己写 raw timestamp 喂给 tracy)给 GPU pass 加 zone。开 Tracy server 跑 HH,你应该看见 CPU zone 和 GPU zone 在同一时间线上。

第八步,**故意引入一个 bug,然后用工具定位**。把某个 mesh 的 vertex buffer stride 改错(比如 24 改成 32),跑 HH,mesh 应该显示扭曲或错位。抓 RenderDoc 帧,在 Pipeline State → Vertex Input 里看 stride,在 Buffer Viewer 里看顶点数据,定位 bug,改回。**这一步是为了让你形成"症状 → 工具 → 定位"的肌肉记忆**。

验收标准:**RenderDoc 抓帧能看到带语义名字的 pipeline/texture/pass + GPU timestamp 报告每帧每段耗时 + 能用 RenderDoc 定位你故意引入的 bug**。把抓到的 capture 截图、timestamp 输出、bug 定位过程记录在 commit message 里。

提交 commit 时,记得在 message 里写:**这次提交给你的 Vulkan 后端加上了从第一天就该有的 debug 基础设施**。这个心智从今以后要带着,任何新加的 Vulkan 对象、新加的 pass,默认就要打名字、配 timestamp。

## 12 · 练习

练习一,Lv1 概念辨析。GPU 调试为什么不能用 CPU 的 `println!`?因为 GPU 的工作异步发生在 GPU 这个独立处理器上,`println!` 跑在 CPU 线程看不见 GPU 的执行状态——你能看到的是"CPU 提交了什么",不是"GPU 执行了什么"。用一句话复述这个边界给你同学听,并说清楚 RenderDoc 是怎么跨过这条边界的(答:它在 API 层完整记录所有命令和状态,事后让你逐 draw call 检视,而不是实时打断点)。

练习二,Lv1 工具分类。RenderDoc 和 Tracy 分别解决哪类问题?为什么不能用 RenderDoc 测性能?RenderDoc 解决正确性 bug(画面错),Tracy 解决性能 bug(帧率低);RenderDoc 抓帧会让 GPU 跑得非常慢(它要存所有纹理快照),在它里面测出的 GPU 时间毫无参考价值。把这条分工记到你的 dev log 里。

练习三,Lv2 动手实践。完成 §11 的全部八步。重点提交:抓到的 RenderDoc capture 截图(显示带名字的 pipeline / texture / region),GPU timestamp 的 console 输出,以及你故意引入 bug 后用 RenderDoc 定位的全过程截图。

练习四,Lv3 设计迁移。你的 HH 项目如果以后接第二个 Vulkan 后端(比如一个 compute-only 后端),你 §11 设计的 `name_object` / `VkObjectWithName` trait 怎么扩展?写一个设计文档(不用实现),说明 trait 怎么覆盖新对象类型,frame graph 怎么自动给新后端的 pass 配 region 和 timestamp。这个练习让你思考"debug 基础设施作为渲染器架构的一部分"是怎么演化的。

练习五,Lv4 shader printf 实战。给你的 HH 项目加一个 shader printf 路径:开 `VK_KHR_shader_non_semantic_info`,在 fragment shader 的某个特定像素位置(用 `gl_FragCoord` guard)加 `debugPrintfEXT`,通过验证层的 debug messenger 路由回控制台。跑起来确认你能看到 GPU 端 print 的变量值。提交时记录:你怎么处理 printf 异步到达的问题、怎么避免日志洪流、怎么确认 driver 支持。

练习六,Lv4 开源贡献。找一个开源 Vulkan 项目(Bevy 的 renderer、Sascha Willems 的 examples、vkguide),检查它的 Vulkan 对象创建代码——是否所有对象都打了 debug 名字?如果没有,提交一个 PR 给所有对象补 debug 名字(开源项目非常欢迎这类"我学的时候发现这块没标记清楚"的改动)。提交前先 issue 沟通项目维护者,看他们的代码风格偏好。

## 13 · 延伸阅读与下一篇

这一篇最权威的实践参考是 RenderDoc 官方的文档(`renderdoc.org/docs/`)和它的 YouTube 频道(Baldur Karlsson 本人的演示视频,把每个面板的用法演给你看)。Khronos 的 `VK_EXT_debug_utils` 规范在 Vulkan registry,虽然枯燥,但里面 region color、object naming 的字段定义最权威。Tracy 的 GPU zone 文档在 `github.com/wolfpld/tracy/releases/latest/download/tracy.pdf` 的 GPU profiling 章节,它讲清楚了 timestamp query + CPU/GPU 时钟对齐的工程细节——和 §6 这一篇是互补关系,你两份都读最完整。

PIX 的文档在 `devblogs.microsoft.com/directx/pix/`,NVIDIA Nsight Graphics 的官方教程在 `developer.nvidia.com/nsight-graphics`,这两个是 Windows / NVIDIA 上的深度工具,你在 Linux 上用得少,但跨平台工作时要知道。Mesa 的 Vulkan 调试环境变量在 Mesa 文档(`docs.mesa3d.org/envvars.html`)里有完整列表,Linux 用户必读。

`VK_KHR_shader_non_semantic_info` 和 shader printf 的官方规范在 Vulkan registry 的 KHR 扩展文档,glslang 对它的支持在 `github.com/KhronosGroup/glslang` 的 README。Hans-Kristian Arntzen(Granite 的作者,frame graph 的发明人之一)有几篇博客讲"frame graph 自动生成 debug marker / timestamp"的工程实现,你 09E 写 Vulkan 后端时可以参考。

CPU 端 profiling 的全套基础在 [phase-4 的 profiling-with-tracy deep-dive](../phase-4/deep-dives/profiling-with-tracy.md),它讲了 Tracy 的 zone / plot / frame / lock / memory 五大原语 + Rust 集成两条路线 + 五个真实性能 bug 案例。这一篇讲 GPU 端,和它配套读,你就有了 CPU + GPU 一体化 profiling 的完整心智。

shader 调试的"颜色编码法"在 [phase-5 的 shader-basics](../phase-5/deep-dives/shader-basics.md) 讲过,是 shader printf 出现之前的"古典"手法,但在某些 driver 不支持 printf 时仍然有用,作为后备方案你应该掌握。

下一篇 [09E-1](09E-1-reliable-udp-transport.md),你要从"会用 Vulkan API"走到"**设计一个跨后端的渲染抽象层**"——Render Hardware Interface(RHI)或者类似的抽象。你这一篇打下的"debug 标记基础设施",在 RHI 里会被进一步抽象:RHI 的接口里有 `name_object` / `begin_region` / `end_region` / `query_timestamp` 这些方法,每个后端(Vulkan、D3D12、Metal)各自实现。这是把 Vulkan 学到的东西泛化到"任何现代图形 API 都能 debug"的关键一步,也是你 HH 项目从"Vulkan 实验"走向"专业渲染架构"的转折。带着这一篇建立的"debug 基础设施优先"的心智,你在设计 RHI 时会自动让它从第一天就支持 debug。
