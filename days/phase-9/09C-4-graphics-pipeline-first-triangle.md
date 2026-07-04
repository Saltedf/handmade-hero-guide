
# 09C-4 · 图形管线与第一个三角形

## 0 · 你的窗口是黑的,而这是你亲手造成的

我先把那个你盼望已久的场景放在你面前。

[09C-2](09C-2-instance-device-swapchain.md) 你有了窗口,[09C-3](09C-3-command-buffers-and-synchronization.md) 你写对了同步循环——acquire、submit、present,CPU 和 GPU 各跑各的、在 fence 那个汇合点重新对齐,验证层一声不吭。一切都是对的,可是屏幕仍然是黑的。因为到目前为止,你提交给 GPU 的命令缓冲里**什么也没画**——你只 begin、end 了几个空命令(顶多 clear 了一下)。同步再正确,空命令画不出三角形。

这一篇,你要往那个空命令缓冲里塞进第一笔真正的内容——`vkCmdDraw(cmd, 3, 1, 0, 0)`,画三个顶点。提交、present,然后那个著名的、五颜六色的三角形就会出现在屏幕上。这是整个 Vulkan 序列最有成就感的时刻之一:五百行的真相,至此你亲手走完了一遍。

但通往那一行 `vkCmdDraw` 的路,要穿过 Vulkan 整个序列里**最繁琐**的一个对象——graphics pipeline(图形管线)。如果你还记得 [09C-1](09C-1-gpu-architecture-and-explicit-api.md) 里我说的"画一个三角形五百行",其中相当一部分就是这根管线。一个 `vkCreateGraphicsPipelines` 调用,要喂给它一打 create-info 结构体:vertex input、input assembly、tessellation、viewport/scissor、rasterizer、multisampling、depth stencil、color blend、dynamic state,再加 pipeline layout 和 render pass。每一项都不能省,每一项填错都是黑屏或验证层炸响。

我先用一句话告诉你为什么 Vulkan 在这里把繁琐推到顶峰:**因为这个 pipeline 对象,是整帧渲染状态的、被烤熟的、不可变的描述**。Vulkan 把它做成不可变对象,不是折磨你,是用一次性高昂的创建代价,换来此后每一次 `vkCmdBindPipeline` + `vkCmdDraw` 几乎免费——这正是 [09C-1](09C-1-gpu-architecture-and-explicit-api.md) "显式哲学"在工程上的具象。理解这个权衡,你就理解了为什么这一篇要把每个 stage 当作一个"配料"来讲解:你不是在背 API,你是在亲手烤一份只烤一次、之后能复用千百万次的配方。

## 1 · 把"管线"想成一份烤熟的配方

OpenGL 的渲染状态,你一定记得是什么感觉。在 [phase-5 的 opengl-context-creation](../phase-5/deep-dives/opengl-context-creation.md) 里你画过东西——你在 draw 之前调一堆 `glUseProgram`、`glBindVertexArray`、`glEnable(GL_BLEND)`、`glViewport`,然后 `glDrawArrays`,然后下一帧又是这一串。每一帧、每一次 draw,你都在重新设一遍状态。OpenGL 是一台**可变状态机**——状态是"当前激活的",你随时改,驱动在 draw 时读当前的快照。

这个模型有一个深层的代价:每一次 draw,驱动都必须**检查当前状态是否合法、是否需要补丁**。两段代码用不同的 blend 模式,驱动不知道你下次会不会又改,所以它保守地、在每次 draw 前重做一遍校验和状态差分。这部分开销在你画几十个物体时看不见,当你画十万个 draw call 时,它就是性能的隐形天花板。

Vulkan 选择了相反的设计。你把"渲染这一类东西需要的全部状态"——用哪些 shader、顶点数据长什么样、用三角面还是线段、blend 怎么算、视口多大——一次性组装成一个 **pipeline 对象**。这个对象一旦创建,就是**不可变的(immutable)**:你不能修改它的任何字段,要变,就再创建一个新的。你可能会问:这不是更麻烦吗?要准备十种渲染状态,岂不是要创建十个 pipeline?

对,而且这正是关键。创建 pipeline 的时候,Vulkan 驱动**一次性**地把所有状态做了完整校验、并把它**预编译成 GPU 能直接吃的硬件命令序列**。GPU 的命令处理器在 `vkCmdBindPipeline` 时,几乎只是切换一个指针;在 `vkCmdDraw` 时,所有状态都已经在 GPU 上"装填好了",驱动不再参与。这就是 [09C-3](09C-3-command-buffers-and-synchronization.md) 反复说的"录制和执行分离"在 pipeline 层面的延续:pipeline 是"状态的预制",命令缓冲是"动作的预制",两者结合,draw call 的运行时开销被压到接近硬件极限。

所以正确的心智模型是:**OpenGL 是"边炒边调味",Vulkan 是"事先配好调料包,下锅时直接倒进去"**。前者灵活但每次都要校验,后者死板但运行时极快。一个游戏里,你能数得清"有几种渲染方式"——不透明几何一种、透明几何一种、UI 一种、后处理一种、阴影一种,加起来撑死几十种。每种烤一个 pipeline,一次性成本,运行时近乎免费地切换。这是 Vulkan 用"创建时繁琐"换"运行时廉价"的典型交易。

还有一个好处容易被忽视:**不可变对象是线程友好的**。OpenGL 的状态机绑死在当前线程(那个 context 所在线程),你没法多线程准备状态。Vulkan 的 pipeline 是个 handle,你可以在任意线程上 `vkCreateGraphicsPipelines`(只要该线程有自己的 device 句柄),然后把结果交给主线程的命令缓冲使用。大型引擎在加载关卡时,后台线程把几百个 pipeline 预烤好,主线程几乎零等待——这是 OpenGL 架构上做不到的事。

## 2 · 配方里有哪些料:逐个 stage 的 create-info

现在我要带你走一遍组成 pipeline 的那十来个 create-info 结构体。我不会把每个字段都列出来——那只是 spec 的复读,没有意义。我会讲每一个 stage **控制什么、它典型的设置是什么、为什么这么设**。你读完这一节,应该能在脑子里画出这根管线的形状:顶点进来,经过哪些站,变成屏幕上的像素。

**Vertex input(顶点输入)**。这一站告诉 GPU:你给的顶点数据,内存里长什么样。一个顶点可能包含 position(vec3)、color(vec3)、uv(vec2),它们在内存里如何排列、各占几个字节、shader 里哪个 location 接它们。在我们这第一个三角形里,你可以**完全不提供顶点缓冲**——巧妙地用 shader 里硬编码的三个顶点位置(这是 vulkan-tutorial 的著名手法,vertex shader 里写死三个角的输出),所以 vertex input stage 是"空的"(binding count 0、attribute count 0)。这个偷懒只在画第一个三角形时用,真实项目里你会绑真实的顶点缓冲(09C-7 会做),但你必须知道:**即使没有顶点数据,这个 stage 结构体本身也得填好交上去**,因为 Vulkan 要求 pipeline 是完整的配方,缺一不可。

**Input assembly(输入装配)**。这一站决定 GPU 怎么把顶点组装成图元。最常用的设置是 `TRIANGLE_LIST`——每三个顶点一个三角形;还有 `TRIANGLE_STRIP`(连续顶点共享形成带状三角形)、`LINE_LIST`、`POINT_LIST` 等。还有一个字段 `primitive_restart`,在 strip 模式下用一个特殊索引值"断开"带子。第一个三角形你填 `TRIANGLE_LIST` 就行。

**Tessellation / Geometry shader stages**。这是可选的曲面细分和几何着色器。第一个三角形完全不需要,你会跳过。但要知道,在真实引擎里,曲面细分是 LOD(细节层次)的核心机制——远处的山用低多边形,走近时 tessellation shader 动态细分出更多顶点。这一站先空着。

**Viewport / Scissor(视口与裁剪矩形)**。视口决定"3D 渲染结果映射到 swapchain image 的哪个矩形区域",scissor 决定"哪些像素被裁掉不写"。第一个三角形里,你填整个 swapchain image 大小的 viewport 和 scissor。这里有一个细节我要提:**Vulkan 默认要求 viewport 和 scissor 是 pipeline 状态的一部分**——也就是说,你想动态改窗口大小、改 viewport,理论上要重建 pipeline。这显然太蠢,所以 Vulkan 提供了 `dynamic state` 机制(下面会讲),让你把 viewport/scissor 标为"动态"——pipeline 里不写死值,运行时在命令缓冲里 `vkCmdSetViewport` 设。这是几乎所有真实 Vulkan 程序都开的动态状态。

**Rasterizer(光栅化器)**。这一站把三角形"涂"成像素。关键字段包括 `polygon mode`(`FILL` 填充、`LINE` 只画线框、`POINT` 只画顶点),`cull mode`(`NONE` / `FRONT` / `BACK`,背面剔除在这设),`front face`(`COUNTERCLOCKWISE` 或 `CLOCKWISE`,决定哪个方向算"正面")。第一个三角形填 `FILL`、`NONE`、`COUNTERCLOCKWISE`。注意 cull mode 不要手抖填成 `BACK`,否则如果顶点绕向错了,三角形会被剔除成黑屏——这是经典的第一个三角形 bug。

**Multisampling(多重采样抗锯齿)**。MSAA(Multi-Sample Anti-Aliasing)在这一站配置。第一个三角形不开 MSAA(`rasterization_samples = 1`)。要开 MSAA,你需要先在 swapchain 创建时请求 `sample_count`,然后这里设成对应的采样数。MSAA 是性能和画质之间最划算的交易之一,但不是这一篇的主题。

**Depth/stencil(深度与模板)**。深度测试让你正确处理"近的物体挡住远的物体",模板测试做各种掩码效果。第一个三角形没有深度缓冲,这一站全部 disabled。09C-7 你加深度缓冲时,会在这里开启深度写入和深度比较。

**Color blend(颜色混合)**。这一站决定新画出来的像素颜色,怎么和 framebuffer 里已有的颜色合并。最简单的设置是"直接覆盖"(关掉 blend),新像素就是最终颜色。透明物体要用 blend:典型的 alpha blend 是 `src color * src alpha + dst color * (1 - src alpha)`。第一个三角形关掉 blend 就行。但 blend 还有一个必须填的小字段——`attachment color write mask`,通常是 `R | G | B | A`,告诉 GPU "这四个通道都要写"。新手偶尔会漏这个 mask 导致黑屏。

**Dynamic state(动态状态)**。这一站列出"哪些 pipeline 状态我打算运行时动态改"。我们刚说了 viewport 和 scissor 应该动态设,所以这里填一个 `[DYNAMIC_VIEWPORT, DYNAMIC_SCISSOR]` 的列表。运行时,你在命令缓冲里 `vkCmdSetViewport` 和 `vkCmdSetScissor`,GPU 用你设的当前值,而不是 pipeline 里的(因为 pipeline 里压根没存)。

把这十来个结构体准备好,你就有了一份"完整的配方料"。但还有两样东西必须先有,你才能把它们送进烤箱:pipeline layout 和 render pass。

## 3 · Pipeline layout 和 Render pass:配方的两个上下文

**Pipeline layout** 描述的是"这根 pipeline 的 shader 需要从 CPU 那边拿什么数据"。在 [09C-5](09C-5-descriptors-and-uniforms.md) 你会学到 descriptor(描述符)——它是 CPU 把数据(矩阵、纹理)传给 GPU 的标准通道。pipeline layout 就是"这根 pipeline 会用到的所有 descriptor set layout 和 push constant 的声明"。

第一个三角形其实不需要任何外部数据——顶点位置 shader 里写死,颜色也写死。所以你的 pipeline layout 可以是空的:

```rust
let pipeline_layout = unsafe {
    device.create_pipeline_layout(
        &vk::PipelineLayoutCreateInfo::default(),  // 空:没 descriptor set、没 push constant
        None,
    )
}.unwrap();
```

但这个空对象不能省——pipeline 创建时必须给它一个 layout,即使里面什么都没有。这个空 layout 你以后会扩展:09C-5 加 uniform buffer 时,你会创建一个 descriptor set layout 描述"一个 uniform buffer binding",把它喂进 pipeline layout。所以 pipeline layout 是 shader 和外部数据世界的**接口契约**。

**Render pass** 描述的是"这根 pipeline 要往哪些 attachment 上画"。一个 attachment 就是 framebuffer 里的一个图像槽位——最常见的就是 swapchain image(颜色 attachment),可能还有深度图像(深度 attachment)。render pass 告诉 GPU:这些 attachment 在 pass 开始时是什么 layout、pass 结束时应该是什么 layout、要不要在开头 clear、blend 之后存到哪。

第一个三角形只需要一个颜色 attachment,format 就是你的 swapchain image format(在 09C-2 创建 swapchain 时你拿到过):

```rust
let color_attachment = vk::AttachmentDescription::default()
    .format(swapchain_format)              // 比如 B8G8R8A8_SRGB
    .samples(vk::SampleCountFlags::TYPE_1) // 没 MSAA
    .load_op(vk::AttachmentLoadOp::CLEAR)  // pass 开始时清成 clear color
    .store_op(vk::AttachmentStoreOp::STORE)// pass 结束时把结果存起来供 present
    .initial_layout(vk::ImageLayout::UNDEFINED)            // 开始时不在乎它原来是什么
    .final_layout(vk::ImageLayout::PRESENT_SRC_KHR);       // 结束后转成"可 present"的 layout
```

注意那个 `final_layout = PRESENT_SRC_KHR`——它和 [09C-3](09C-3-command-buffers-and-synchronization.md) 讲的 layout 转换是连起来的:render pass 自动把 swapchain image 从"被渲染写"的 layout 转成"可被 present"的 layout,你不需要手动插 barrier。这是 render pass 替你做的便利。

然后一个 subpass 引用这个 attachment,render pass 就成了。完整的 render pass 比 vulkan-tutorial 里展示的要复杂得多——多 attachment、多 subpass、subpass dependency(描述 subpass 之间的同步)——但第一个三角形只需要一个 attachment、一个 subpass。讲深了,这其实就是 [09B-3 frame graph](09B-3-frame-graph.md) 在自动生成的东西——frame graph 知道每个 pass 用了哪些 attachment、什么 layout,它自动合成 render pass。你现在手写一个最简单的 render pass,是在亲手做 frame graph 平时替你做的事。

**Vulkan 1.3 之后的简化:dynamic rendering**。Vulkan 1.3 引入了 `VK_KHR_dynamic_rendering`,让你**完全不用创建 render pass 对象**——你在 pipeline 里用一个 `PipelineRenderingCreateInfo` 声明 attachment 的 format,然后在命令缓冲里 `vkCmdBeginRendering` 直接开始,`vkCmdEndRendering` 结束。这对新手友好得多,而且很多现代引擎已经在用。但 vulkan-tutorial 和大多数教材仍然基于经典 render pass 写,我这里也跟着走一遍经典流程——你理解了 render pass,dynamic rendering 就是"省略了它"。两者底层做的是同一件事。

## 4 · Shader 模块:Spir-V 是 Vulkan 的母语

OpenGL 时代,你的 shader 是 GLSL 或 HLSL 源码,运行时由驱动编译。Vulkan 不接受 GLSL 源码,它只接受 **SPIR-V**——一种跨厂商、跨语言的、二进制的 shader 中间表示。

SPIR-V 这个设计有几个深远的好处。第一,**跨厂商**——同一个 SPIR-V 二进制在 NVIDIA、AMD、Intel、Mobile GPU 上都能跑,行为一致,因为编译它的不是各家驱动(各家驱动有 bug),而是统一的离线编译器。第二,**离线编译**——你可以在打包游戏时把 GLSL/HLSL 编译成 SPIR-V,游戏运行时不再有 shader 编译,加载快、启动无卡顿。第三,**跨语言**——GLSL、HLSL、甚至新的 Slang,都能编成 SPIR-V,这意味着你的 shader 不再绑死 GLSL。

第一个三角形你需要两个 shader:一个 **vertex shader**(处理顶点位置,决定三角形画在屏幕哪),一个 **fragment shader**(决定三角形每个像素什么颜色)。最经典的 vulkan-tutorial 例子,vertex shader 里硬编码三个顶点的位置和颜色,fragment shader 直接输出插值后的颜色——这就是那个"五颜六色三角形"的来源。

GLSL 长这样(为了清晰我贴源码,你后面会把它编成 SPIR-V):

```glsl
// triangle.vert
#version 450

vec2 positions[3] = vec2[](
    vec2( 0.0, -0.5),
    vec2( 0.5,  0.5),
    vec2(-0.5,  0.5)
);

vec3 colors[3] = vec3[](
    vec3(1.0, 0.0, 0.0),
    vec3(0.0, 1.0, 0.0),
    vec3(0.0, 0.0, 1.0)
);

layout(location = 0) out vec3 fragColor;

void main() {
    gl_Position = vec4(positions[gl_VertexIndex], 0.0, 1.0);
    fragColor = colors[gl_VertexIndex];
}
```

```glsl
// triangle.frag
#version 450

layout(location = 0) in vec3 fragColor;
layout(location = 0) out vec4 outColor;

void main() {
    outColor = vec4(fragColor, 1.0);
}
```

注意 `gl_VertexIndex`——这是 Vulkan 内置的"当前顶点索引",因为我们没绑顶点缓冲,用 draw 的 vertex count=3 驱动这个索引在 0/1/2 之间循环。颜色的 `location=0` 在 vertex 输出和 fragment 输入对齐,光栅化会自动对三个顶点的颜色做**重心插值**,这就是为什么三角形内部颜色是平滑过渡的——红→绿→蓝。这个插值机制本身值得你在脑中画一画:每个像素被三角形覆盖时,根据它到三个顶点的距离算权重,加权混合三个顶点的颜色。

把 GLSL 编成 SPIR-V,有几种方式。**shaderc** 是 Google 出的库,内嵌了 glslang,可以在你的 Rust 程序里运行时编译 GLSL 字符串成 SPIR-V。**glslangValidator** 是命令行工具,可以把 GLSL 文件编成 `.spv` 二进制,你在程序里加载这个文件。**shaderc-rs** 是 shaderc 的 Rust 绑定。Arch 上:

```bash
sudo pacman -S shaderc glslang
```

你可以在 build.rs 里调用 glslangValidator,把 `shaders/*.vert`、`shaders/*.frag` 在编译期编成 `.spv` 嵌进二进制;也可以运行时用 shaderc-rs 编译。教学上为了简单,直接用命令行:

```bash
glslangValidator -V triangle.vert -o triangle.vert.spv
glslangValidator -V triangle.frag -o triangle.frag.spv
```

`-V` 表示编 SPIR-V(Vulkan 用),`-G` 是 OpenGL 用的,别搞混。

拿到 SPIR-V 字节码,你创建 shader module。一个 shader module 就是一段 SPIR-V 的封装,可以被 pipeline 引用:

```rust
fn create_shader_module(device: &ash::Device, spirv: &[u32]) -> vk::ShaderModule {
    let create_info = vk::ShaderModuleCreateInfo::default()
        .code(spirv);
    unsafe {
        device.create_shader_module(&create_info, None).unwrap()
    }
}

// 加载文件、读成 &[u32](注意是 u32 数组,不是 u8)
let vert_code = include_bytes!("../shaders/triangle.vert.spv");
let vert_spirv = cast_slice_to_u32(vert_code);  // 你写一个工具函数,处理对齐
let vert_module = create_shader_module(&device, vert_spirv);
let frag_module = create_shader_module(&device, frag_spirv);
```

shader module 本身还**没指定它是什么 stage**(vertex? fragment?)。这个指定发生在 pipeline 的 `PipelineShaderStageCreateInfo` 里:

```rust
let vert_stage = vk::PipelineShaderStageCreateInfo::default()
    .stage(vk::ShaderStageFlags::VERTEX)
    .module(vert_module)
    .name(c"main");   // 入口函数名,大多数情况是 "main"

let frag_stage = vk::PipelineShaderStageCreateInfo::default()
    .stage(vk::ShaderStageFlags::FRAGMENT)
    .module(frag_module)
    .name(c"main");
```

这两个 stageCreateInfo 进 pipeline 的 shader stages 数组。pipeline 创建后,你就可以销毁 shader module——pipeline 把 SPIR-V 拷进了自己内部,module 只是创建期的临时容器。

## 5 · 把所有料送进烤箱:`vkCreateGraphicsPipelines`

到这里,你准备好了一切:vertex input、input assembly、viewport/scissor(动态)、rasterizer、multisampling、color blend、dynamic state,加上 shader stages、pipeline layout、render pass。现在你把它们组装成一个 `GraphicsPipelineCreateInfo`,送给 `vkCreateGraphicsPipelines`。

这个调用本身出奇地简单:

```rust
let pipeline_info = vk::GraphicsPipelineCreateInfo::default()
    .stages(&[vert_stage, frag_stage])
    .vertex_input_state(&vertex_input)
    .input_assembly_state(&input_assembly)
    .viewport_state(&viewport_state)        // 即使 viewport 是动态的,这里也要给 count=1
    .rasterization_state(&rasterizer)
    .multisample_state(&multisampling)
    .color_blend_state(&color_blend)
    .dynamic_state(&dynamic_state)
    .layout(pipeline_layout)
    .render_pass(render_pass)
    .subpass(0);                             // 这根 pipeline 用于 render_pass 的第 0 个 subpass

let pipeline = unsafe {
    device.create_graphics_pipelines(
        vk::PipelineCache::null(),          // 先不用 cache,09C-8 再讲
        &[pipeline_info],
        None,
    )
}.unwrap()[0];   // 返回值是 Result<Vec<Pipeline>, (Vec<Pipeline>, Result)>;第一个三角形只建一个
```

注意几个新手容易掉进去的坑。第一个坑,**`viewport_state` 即使内容是动态的,这个结构体本身也不能省**——它里面有一个 `viewport_count` 和 `scissor_count`,告诉 GPU "我会动态设几个 viewport"。`count=1` 是典型值(单视口),你后面在命令缓冲里 `vkCmdSetViewport(cmd, 0, &[viewport])` 提供这一个视口。如果 pipeline 里写了 dynamic_viewport 但 viewport_state 给 count=0,验证层会报。

第二个坑,**`color_blend_state` 里每个 attachment 都要有一个 blend state**。你的 render pass 有 1 个颜色 attachment,这里就要给一个 attachment 的 blend 配置。新手有时把 `attachment_count` 写成 0,然后 fragment shader 输出颜色但 framebuffer 不更新——黑屏。

第三个坑,**`subpass` 索引要对得上**。你的 render_pass 只有一个 subpass(index 0),pipeline 必须声明它服务于 subpass 0。多 subpass 的 render pass(G-buffer pass + lighting pass 这种)里,不同的 pipeline 服务于不同的 subpass,索引错了会 fail pipeline creation。

`vkCreateGraphicsPipelines` 的执行时间,可能是你整个程序里最长的一次调用——它做了所有 shader 编译(把 SPIR-V 翻译成 GPU 的 ISA)、所有状态校验、所有命令序列的预烤。这就是为什么我说"创建时昂贵、运行时廉价":这一次调用的代价,分摊到了此后千百万次 `vkCmdDraw` 上。**Pipeline cache**(`vk::PipelineCache`)是把这次代价再摊薄的工具——驱动把编译结果存进 cache,下次创建相同 pipeline 时直接复用,极大地缩短启动时间和关卡切换时的卡顿。生产代码必备,但第一个三角形可以先不用。

`vkCreateGraphicsPipelines` 返回时,如果验证层炸响(它会非常详细地告诉你哪个字段错了),逐条修;不要在验证层报错的情况下继续往下走——这些错误你忽略一个,后面就是黑屏地狱。

## 6 · framebuffer:render pass 和 swapchain image 之间的桥

在你能开始 render pass 之前,还有一个对象要创建——**framebuffer**。framebuffer 是 render pass 的"实例化":render pass 描述了"我需要 1 个颜色 attachment、format 是 X",framebuffer 就是"我现在把这个具体的 swapchain image view 绑到这个 attachment 上"。

每个 swapchain image 你需要一个对应的 framebuffer(双缓冲就两个):

```rust
let framebuffers: Vec<vk::Framebuffer> = swapchain_image_views.iter().map(|view| {
    let attachments = &[*view];
    let create_info = vk::FramebufferCreateInfo::default()
        .render_pass(render_pass)
        .attachments(attachments)
        .width(swapchain_extent.width)
        .height(swapchain_extent.height)
        .layers(1);
    unsafe { device.create_framebuffer(&create_info, None).unwrap() }
}).collect();
```

framebuffer 的 width/height 要等于 swapchain extent,layers 是 1(除非你做立体渲染或渲染 cube map)。framebuffer 和 render pass 是配套的——framebuffer 的 attachment 数量、format 必须和 render pass 声明的一致,否则创建失败。

现在你有了 pipeline、framebuffer,加上 09C-3 已经准备好的命令缓冲和同步,就可以录第一条真正的渲染命令了。

## 7 · 录制 draw 命令:那个五百行的顶峰时刻

这是这一篇的高潮——你要往 09C-3 那个空命令缓冲里,塞进真正画三角形的命令。把每一步想清楚,这是你这一篇要做中学的核心。

完整的一段录制长这样:

```rust
fn record_frame(
    device: &ash::Device,
    cmd: vk::CommandBuffer,
    pipeline: vk::Pipeline,
    framebuffer: vk::Framebuffer,
    render_pass: vk::RenderPass,
    extent: vk::Extent2D,
    image_available: vk::Semaphore,
    render_finished: vk::Semaphore,
    in_flight: vk::Fence,
    image_index: u32,
) {
    unsafe {
        // —— 录制开始 ——
        device.begin_command_buffer(cmd, &vk::CommandBeginInfo::default()).unwrap();

        // —— 开始 render pass ——
        let clear_color = vk::ClearValue {
            color: vk::ClearColorValue { float32: [0.0, 0.0, 0.0, 1.0] },  // 黑色清屏
        };
        let render_area = vk::Rect2D {
            offset: vk::Offset2D { x: 0, y: 0 },
            extent,
        };
        let render_pass_info = vk::RenderPassBeginInfo::default()
            .render_pass(render_pass)
            .framebuffer(framebuffer)
            .render_area(render_area)
            .clear_values(std::slice::from_ref(&clear_color));

        // SUBPASS_CONTENTS_INLINE:命令直接录在主命令缓冲里,不开 secondary command buffer
        device.cmd_begin_render_pass(cmd, &render_pass_info, vk::SubpassContents::INLINE);

        // —— 绑定 pipeline ——
        device.cmd_bind_pipeline(cmd, vk::PipelineBindPoint::GRAPHICS, pipeline);

        // —— 动态状态:viewport 和 scissor(因为 pipeline 把它们标成了 dynamic)——
        let viewport = vk::Viewport {
            x: 0.0, y: 0.0,
            width:  extent.width  as f32,
            height: extent.height as f32,
            min_depth: 0.0, max_depth: 1.0,
        };
        let scissor = vk::Rect2D {
            offset: vk::Offset2D { x: 0, y: 0 },
            extent,
        };
        device.cmd_set_viewport(cmd, 0, std::slice::from_ref(&viewport));
        device.cmd_set_scissor(cmd, 0, std::slice::from_ref(&scissor));

        // —— 画!3 个顶点、1 个 instance、顶点起点 0、instance 起点 0 ——
        device.cmd_draw(cmd, 3, 1, 0, 0);

        // —— 结束 render pass、结束录制 ——
        device.cmd_end_render_pass(cmd);
        device.end_command_buffer(cmd).unwrap();
    }
}
```

`vkCmdDraw` 的四个参数:`vertexCount=3`(画 3 个顶点,因为 vertex shader 里硬编码了 3 个位置)、`instanceCount=1`(实例化绘制,这里画一份)、`firstVertex=0`(从顶点 0 开始)、`firstInstance=0`(从 instance 0 开始)。这 3 个顶点经过 input assembly 组装成一个三角形,经过 rasterizer 涂成像素,每个像素跑 fragment shader,颜色写进 framebuffer。

注意命令的顺序——`cmd_begin_render_pass` 必须在 `cmd_bind_pipeline` 之前,因为 render pass 开始之后,GPU 才知道往哪个 framebuffer 渲染,绑定 pipeline 才有意义。`cmd_draw` 必须在 pipeline bind 之后。`cmd_end_render_pass` 在最后。这个顺序错了,验证层会精确报错。

然后回到 09C-3 的同步循环——acquire、record、submit(关联 image_available、render_finished、in_flight fence)、present。这次 submit 的命令缓冲里有了真正的画图命令,GPU 执行它,屏幕上就出现了三角形。 Submit 这一步和 09C-3 完全一样——同步那一篇已经做好了,这里你只是换了命令缓冲的内容。

`present` 之后,你应该看到屏幕上出现一个红绿蓝渐变的三角形,黑底。验证层一声不吭。这是 Vulkan 学习最值得截屏的一刻——五百行,你亲手写完了一遍,你看到了三角形。

## 8 · 第一个三角形最常见的五个 bug

我把新手在这一篇最容易踩的坑总结一下,不是为了罗列,是因为这些 bug 都长一个样——黑屏,而验证层不一定每次都抓得到。

第一个,**rasterizer 的 cull mode 填了 BACK,但顶点绕向错了**。Vulkan 默认逆时针为正面(`front_face = COUNTERCLOCKWISE`),你的三角形顶点如果绕成了顺时针,而 cull mode 是 BACK,整张三角形被背面剔除,黑屏。第一个三角形建议把 cull mode 设成 NONE,先把三角形画出来,以后再加剔除。

第二个,**color blend attachment 的 color write mask 写成了 0**(或者忘了给 attachment)。fragment shader 算了颜色,但 mask 告诉 GPU "不要写任何通道",结果 framebuffer 不更新,黑屏。检查 `color_write_mask = R | G | B | A`。

第三个,**viewport 的 height 是负数**。Vulkan 的 viewport y 轴朝下(和 OpenGL 朝上相反),有些教程会写 `height = -extent.height` 来"翻转"。第一个三角形不要这么玩,直接 `height = extent.height`,先把三角形画出来,坐标系的事 09C-7 再处理。

第四个,**忘了 `cmd_bind_pipeline`**。这一步漏了,GPU 不知道用哪根 pipeline,`cmd_draw` 行为未定义(通常是验证层炸响 + 不画任何东西)。检查 bind 必须在 begin_render_pass 之后、draw 之前。

第五个,**render pass 的 color attachment format 和 swapchain format 不一致**。你 swapchain 是 `B8G8R8A8_SRGB`,render pass attachment 也必须是这个 format。新手有时把 swapchain 用 SRGB 但 render pass 写成 UNORM,验证层会报 layout/format mismatch。

遇到黑屏,排查顺序:验证层有没有报错(90% 报了)、cull mode 是不是 NONE、color write mask 是不是 RGBA、bind_pipeline 在不在、viewport 是不是正值。这套排查心法,在你画第一个三角形的夜里会救你几次。

## 9 · 在你 HH 项目里动手(做中学红线)

这一篇的动手,是把你 09C-2/09C-3 的 Vulkan backend 升级到能真正画三角形。结束时你的窗口里出现一个红绿蓝渐变三角形,验证层完全干净。

第一步,**装 shader 工具,准备两个 shader 文件**。在 Arch 上 `sudo pacman -S shaderc glslang`。在你 HH 项目的 `shaders/` 目录下创建 `triangle.vert` 和 `triangle.frag`,内容用我前面给的 GLSL(或者 vulkan-tutorial 的版本)。用 `glslangValidator -V` 把它们编成 `.spv`,确认产物存在。

第二步,**加载 SPIR-V,创建 shader module**。在你的 Vulkan 后端代码里,写一个 `create_shader_module(spirv: &[u32]) -> vk::ShaderModule`。考虑用 `include_bytes!` 把 `.spv` 嵌进二进制,写一个小工具把它 cast 成 `&[u32]`(注意字节序和对齐)。

第三步,**创建 pipeline layout**(空的就行)和 **render pass**(一个颜色 attachment,format 等于你的 swapchain image format,initial_layout UNDEFINED,final_layout PRESENT_SRC_KHR)。验证这两个对象创建成功。

第四步,**填那十来个 create-info**。Vertex input 空、input assembly TRIANGLE_LIST、rasterizer FILL+NONE cull、multisampling 1 sample、color blend 关闭但 write mask RGBA、dynamic state 是 viewport+scissor、shader stages 是 vert+frag。把它们组装进 `GraphicsPipelineCreateInfo`,调 `vkCreateGraphicsPipelines`。开验证层,确认无报错。

第五步,**创建 framebuffer**。每个 swapchain image view 一个 framebuffer,绑到 render pass,extent 等于 swapchain extent。

第六步,**修改你 09C-3 的命令缓冲录制函数**:在 begin 之后,`cmd_begin_render_pass`(给 clear color)、`cmd_bind_pipeline`、`cmd_set_viewport`、`cmd_set_scissor`、`cmd_draw(cmd, 3, 1, 0, 0)`、`cmd_end_render_pass`、end。同步循环的其余部分不变。

第七步,**跑,看屏幕,看验证层**。三角形应该出现,验证层应该一声不响。如果有报错,逐条修;如果是黑屏无报错,按 §8 的排查清单逐项查。

验收标准:**屏幕出现红绿蓝渐变三角形,持续运行稳定,验证层零报错**。截一张图存到你的 dev log 里——这是你 Vulkan 旅程的里程碑,以后回头看,你会记得这一刻。

提交 commit 时,在 message 里记录你踩过的坑(cull mode?color mask?坐标系?),这些记录以后你会感谢自己。

## 10 · 生产现实:你不会手写 pipeline,但你需要懂它

我必须告诉你一件事,免得你以为"以后写引擎就是天天手写 pipeline"。

真实的游戏引擎里,**没人手写 `GraphicsPipelineCreateInfo`**。原因有两个。第一,一个商业引擎有几百上千种渲染状态组合(不同的材质、不同的 pass、不同的 LOD),手写每个 pipeline 不现实。第二,这些状态本来就被 [09B-3 frame graph](09B-3-frame-graph.md) 和材质系统(material system)在更高的抽象层管着——材质定义了"用什么 shader、blend 怎么开、cull mode",frame graph 定义了"render pass 长什么样、attachment 几个",它们**自动合成**出 pipeline create-info。

所以你这一篇学的东西,在生产里的实际形态是:**你写一个材质系统,它读材质定义,生成 pipeline create-info,调 `vkCreateGraphicsPipelines`,缓存结果**。frame graph 替你做了 render pass 的部分;材质系统替你做了 pipeline 的部分;两者都不需要你手填那些字段。

那为什么你还要手写一遍?因为**你只有亲手做过一遍,才能理解材质系统和 frame graph 在自动生成什么**。否则,材质系统对你就是黑盒——它出一个 pipeline 你就用,你不知道那个 pipeline 长什么样、为什么长那样、出 bug 了怎么 debug。这一篇手写 pipeline,是让你**理解 pipeline 是什么**,以便日后你能信任并控制那些自动生成它的系统。这正是这个序列反复强调的:**学底层是为了在更高抽象上自由**。

还有一点关于 pipeline cache。生产代码必用 `vk::PipelineCache`——第一次创建一个 pipeline 时,驱动把编译结果存进 cache;下次(下次启动、下次关卡加载)遇到相同 pipeline,直接从 cache 复用,创建时间从几百毫秒降到几毫秒。你应该把 cache 序列化到磁盘,跨启动复用。这是 Vulkan 启动性能优化的第一招,你以后在 HH 项目里会用到。

## 11 · 练习

练习一,Lv1 概念辨析。Vulkan 的 graphics pipeline 对象是不可变的,你为什么要重建而不是修改?因为 Vulkan 的设计是用"一次性高昂的创建(校验 + 预编译)"换"运行时廉价的 bind/draw",不可变让驱动可以放心地预烤硬件命令、不需要预留"被修改"的余量。把这个权衡用一句话复述给你的同学听。

练习二,Lv1 概念辨析。dynamic state 是干什么用的?它解决"viewport/scissor 需要动态改但 pipeline 不可变"的矛盾——你把 viewport 标为动态,pipeline 里不存具体值,运行时在命令缓冲里 `cmd_set_viewport` 设。第一个三角形你应该把 viewport 和 scissor 设成动态,为什么?(因为窗口大小变化时不需要重建 pipeline。)

练习三,Lv2 动手实践。完成前面 §9 的全部七步,在你的 HH 项目里画出红绿蓝渐变三角形。把验证层日志、屏幕截图、踩坑记录写进 commit message。这是这一篇的核心交付物。

练习四,Lv3 迁移设计。在不实际写代码的前提下,你能在纸上(或脑中)回答:你 HH 渲染器里的"不透明几何 pass"如果迁到 Vulkan,它的 pipeline 需要哪些 create-info?(vertex input 有 position+normal+uv,有顶点缓冲;input assembly TRIANGLE_LIST;rasterizer FILL+BACK cull;不开 MSAA;深度测试开;color blend 关闭但 write mask RGBA;dynamic viewport/scissor。)把这个迁移设计写在你的 dev log 里,09C-7 你会真正实现它。

练习五,Lv4 开源贡献。找一个开源的 Vulkan 项目(Bevy 的 renderer、vkguide、Sascha Willems 的 examples),找到它创建 pipeline 的代码,读它怎么用 pipeline cache、怎么把材质参数映射到 create-info。提交一个 PR 把它的文档或注释改清楚(开源项目非常欢迎这类"我学的时候发现这块没解释清楚"的改动)。这个练习把你从"会用 pipeline"推到"能读懂生产级 pipeline 代码"。

## 12 · 延伸阅读与下一篇

这一篇最权威的参考是 Vulkan spec 的 *Graphics Pipelines* 章节,以及 *Pipelines* 概念章节里关于 pipeline cache 的部分——前者告诉你每个字段精确含义,后者告诉你为什么 pipeline cache 这么值钱。最友好的实践教程是 vulkan-tutorial.com 的 "Graphics Pipeline Basics" 那一章(Drawing/Fixed functions/Render passes/Conclusion 几节),它和你这一篇走的是同一条路,可以对照读。Sascha Willems 的 Vulkan examples 仓库里有大量可运行的 pipeline 例子,值得收藏作为日后参考。

GPU 光栅化管线本身的硬件原理(顶点经过 T&L、clip/cull、光栅化、像素 shader、ROP),任何一本图形学教材(Real-Time Rendering 第四版、《RTR》虎书)都讲得透彻——你在 phase-5/6 已经学过,这一篇是这些概念在 Vulkan API 上的落地。

下一篇 [09C-5](09C-5-descriptors-and-uniforms.md),你的三角形要"动起来"。目前为止你的数据(顶点位置、颜色)都是写死在 shader 里的,这显然不实用。下一篇你学 **descriptor(描述符)** 和 **uniform buffer**——这是 CPU 把数据(变换矩阵、时间、相机位置)动态传给 GPU 的标准通道。学完 09C-5,你能让三角形随时间旋转、随相机移动,真正成为"3D 程序"而不是"静态演示"。pipeline 已经烤好了,接下来就是把外部数据流接进去。
