---
phase: 9
sequence: "9C"
module: 5
title_en: "Descriptors & Uniforms"
title_zh: "描述符与统一缓冲:让 CPU 把数据吹进 shader"
type: deep-dive
difficulty: 4
duration: "3-4 小时"
domains: [graphics, gpu, rust]
prereqs: ["09C-4-graphics-pipeline-first-triangle"]
calibration: "Vulkan descriptor system spec + vulkan-tutorial 'Descriptor Sets'"
---

# 09C-5 · 描述符与统一缓冲

## 0 · 你的三角形好看,可它一动不动

我先把那个你盼望已久的下一个小目标放在你面前。

[09C-4](09C-4-graphics-pipeline-first-triangle.md) 你画出了红绿蓝渐变的三角形——五百行的真相,你亲手走完了。你截了图,写进 dev log。然后你盯着它看了三秒,心里冒出一个朴素的念头:它能不能转起来?

不能。因为目前为止,你给 GPU 的所有数据都是**写死在 shader 源码里**的——三个顶点位置硬编码在 `triangle.vert` 里,颜色硬编码在同一份文件里。GPU 每一帧跑的都是同一份 shader,产出的是同一个三角形。要让它动,你得让 GPU 每一帧看到一个**不同的**变换矩阵(Model-View-Projection,简称 MVP),把那三个写死的顶点旋转到不同的角度。可问题是:这个矩阵是 CPU 上算出来的、每帧都在变的浮点数,你怎么把它"喂"给 GPU 上正在跑的 vertex shader?

这是图形编程的一个根本问题,比"画三角形"本身更根本:**CPU 怎么把数据送到 GPU 上的 shader 手里?** OpenGL 时代这个问题被隐藏在 `glUniformMatrix4fv` 这种一行调用背后,你觉得它天经地义。Vulkan 把它彻底摊开,让你看清楚这条数据通道的每一层结构——这一篇就是讲这条通道的。学完它,你的三角形就能旋转;再进一步,09C-6 你会把**纹理**(一张二维像素图)也走通同一条通道,三角形就从"色块"变成"贴图几何"。

但你要先理解一件事:Vulkan 把"CPU 到 shader 的数据通道"做成了一套**分层的、显式的**系统,叫 **descriptor(描述符)** 系统。它有四层对象,初看极其繁琐——为什么传一个矩阵要创建四个对象?我的回答是:这四个对象,每一个都在解决 OpenGL 那行 `glUniform*` 背后藏起来的一个工程问题。把它们一个一个讲清楚,你就理解了为什么 Vulkan 要这么设计,以及这套设计如何让"画十万个物体"在 GPU 上跑得飞快。

这一篇的层级是:先讲清楚为什么 OpenGL 的"按名字设 uniform"在 GPU 规模下撑不住,然后一层一层地把 Vulkan 的 descriptor 系统搭起来——descriptor set layout 是 schema、descriptor pool 是内存来源、descriptor set 是实际绑定的数据、pipeline layout 是 shader 看到的接口、最后在 draw 之前 `vkCmdBindDescriptorSets` 把数据接上。中间插一节讲 uniform buffer 的内存细节(尤其是那个臭名昭著的 std140 对齐陷阱),再讲讲 push constant 这个"小数据专用"的轻量替代,最后给你看生产引擎的"真路子"——bindless resources。

## 1 · OpenGL 的 uniform 模型,为什么 GPU 上撑不住

要理解 Vulkan 的 descriptor 在解决什么,先得看清 OpenGL 在做什么、它在哪里碰到了天花板。

OpenGL 里你写 shader,在 GLSL 里声明一个 `uniform mat4 mvp;`,这就是一个"全局变量"——对每个顶点/像素都一样、但每帧可以变。CPU 端,你在 draw 之前调 `glUseProgram(shader)`、拿到 `mvp` 这个 uniform 的 location(一个整数 handle,通过名字字符串 `glGetUniformLocation("mvp")` 查到),然后 `glUniformMatrix4fv(loc, 1, GL_FALSE, &mvp[0][0])`,把 16 个 float 写进去。然后 `glDrawArrays` 调用,vertex shader 跑的时候,那个 `mvp` 变量就是你刚写的值。

这个模型对新手极其友好——名字一查、值一写、完事。但它在 GPU 工程上有两个深层问题,你画一百个物体时还看不到,画十万个时就窒息了。

第一个问题,**字符串查找是 CPU 侧的开销**。`glGetUniformLocation("mvp")` 每次都要把字符串和 shader 里所有的 uniform 名字做匹配,找到那个 location。你不会真的每帧查——你会缓存 location——但 driver 内部,每次 `glUniform*` 调用,仍然要做"这个 location 对应 driver 内部哪块显存"的查找。这个查找在 driver 进程里、在每帧每个 uniform 上、每个 draw 上都发生。draw call 多了,这部分 CPU 时间惊人。

第二个问题更深层,**driver 不知道 uniform 的 layout,无法预编译绑定**。OpenGL 允许你在任意时刻 set uniform——你 draw 之前 set、draw 之后还可以再 set 然后下一个 draw 又用。driver 不能在 compile shader 时就把"uniform 怎么绑到硬件寄存器"烤死,因为它不知道你下一帧会不会改。于是 driver 在每个 draw 前都要做一次"把 uniform 当前值装填到硬件寄存器"的工作,这部分工作没法省掉。GPU 硬件层面,uniform 走的是固定的寄存器或专用的常量缓冲区,但 OpenGL 把"映射"这件事推迟到 draw 时,留了一个永远省不掉的 driver 步骤。

Vulkan 的设计哲学你已经在 [09C-1](09C-1-gpu-architecture-and-explicit-api.md) 见过——**把所有 driver 推迟的工作,提前到创建时一次性做掉,运行时几乎免费**。这个哲学用在"CPU 到 shader 的数据通道"上,产物就是 descriptor 系统:你**一次性**告诉 Vulkan"我的 shader 需要 binding 0 上一个 uniform buffer、binding 1 上一个 sampled image",Vulkan 把这个 schema 校验完、把硬件层面的绑定预排好,此后每一帧你只是把数据写进已经排好的槽位,**没有运行时查找、没有 driver 介入**。这就是为什么 descriptor 系统有四层对象——每一层都在帮 driver 把工作前移。

把这个动机刻在脑中,接下来这四层每出现一个,你都问自己一句:**它在帮 driver 省掉 OpenGL 时代哪一步运行时工作?** 这是理解 Vulkan 的钥匙。

## 2 · 第一层:Descriptor set layout——shader 的数据 schema

第一层对象叫 **descriptor set layout(描述符集布局)**。它的角色是 schema——一份契约,声明"这根 pipeline 的 shader,会从外面接进几个 binding、每个 binding 是什么类型的资源、绑在哪个 shader stage"。

我先把一个最简单的例子放在你面前。你想给 vertex shader 一个 uniform buffer 装 MVP 矩阵。GLSL 端,你这么声明:

```glsl
// triangle.vert(09C-5 版本)
#version 450

layout(binding = 0) uniform UBO {
    mat4 mvp;
};

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
    gl_Position = mvp * vec4(positions[gl_VertexIndex], 0.0, 1.0);
    fragColor = colors[gl_VertexIndex];
}
```

注意那个 `layout(binding = 0) uniform UBO { mat4 mvp; }`——这就是 shader 声明"我要在 binding 0 上拿到一个 uniform buffer,里面装一个 mat4"。CPU 端,你要"对齐"地声明一份 schema,就是 descriptor set layout:

```rust
let ubo_binding = vk::DescriptorSetLayoutBinding::default()
    .binding(0)                                              // 对应 GLSL 的 binding = 0
    .descriptor_type(vk::DescriptorType::UNIFORM_BUFFER)     // 资源类型:UBO
    .descriptor_count(1)                                     // 这个 binding 上有几个 UBO(数组的话 >1)
    .stage_flags(vk::ShaderStageFlags::VERTEX);              // 只有 vertex shader 用它

let layout_info = vk::DescriptorSetLayoutCreateInfo::default()
    .bindings(std::slice::from_ref(&ubo_binding));

let descriptor_set_layout = unsafe {
    device.create_descriptor_set_layout(&layout_info, None)
}.unwrap();
```

这个 `descriptor_set_layout` 对象,就是 schema 的实例化。它没有数据——它只是声明"binding 0 是一个 UBO、给 vertex shader 用"。数据是后面的事。你可能会问:为什么不直接给数据?为什么要先做一份声明?

答案正是 Vulkan 哲学的体现:**这份声明让 driver 在创建 pipeline 时就能校验 shader 的资源需求和 CPU 提供的资源是否匹配**。如果 shader 声明 binding 0 是 UBO 但你的 descriptor set layout 没声明 binding 0,或者类型对不上(声明是 UBO 但绑的是 sampled image),pipeline 创建失败,**在创建时报错**,而不是画到一半黑屏。OpenGL 时代这种"shader 和 uniform 不匹配"的错误是运行时的、模糊的,Vulkan 把它前移到创建时、明确的。

还有一个细节值得留意:**binding 是数字索引,不是名字**。GLSL 里 `layout(binding = 0)`,CPU 端 `.binding(0)`,两边用数字对齐——没有字符串查找,这就是"运行时无查找"的源头。一个 descriptor set layout 可以有多个 binding(0、1、2……),每个 binding 独立声明类型和 stage。生产引擎里,一个 layout 可能有十几个 binding:几个 UBO(相机矩阵、模型矩阵、灯光参数)、若干 sampled image(漫反射贴图、法线贴图、阴影贴图)、可能还有 storage buffer(粒子位置数组)。每个 binding 的类型和 stage 都在这份 schema 里声明。

descriptor set layout 是"schema 层"——它告诉你**结构**,不告诉你**数据**。数据来源是下一层。

## 3 · 第二层:Descriptor pool——descriptor 的内存池

第二层对象叫 **descriptor pool(描述符池)**。它的角色是**内存来源**——descriptor 不是凭空存在的,它占用 driver 的内部数据结构(可能是 GPU 上的常量区、可能是 driver 维护的映射表),这些数据结构需要从某个池里分配。pool 就是这个池。

为什么需要 pool,而不是像别的对象那样 `create` 出来?因为 descriptor 在一个游戏里**数量巨大**。一个游戏关卡里,可能有几千个物体,每个物体有自己的 MVP 矩阵、自己的贴图,这些资源绑定信息每一个都是一个 descriptor set。如果每创建一个 descriptor set 都和 driver 单独通信一次,创建开销会成为加载时间的瓶颈。pool 的设计是:你一次性告诉 driver"我大概会创建 1000 个 descriptor set,每个用这种那种 binding",driver 一次性把那块内存准备好,之后你从 pool 里 `allocate` descriptor set 是 O(1) 的、几乎免费。

```rust
let pool_size = vk::DescriptorPoolSize::default()
    .ty(vk::DescriptorType::UNIFORM_BUFFER)   // 这个池分配的 descriptor 类型
    .descriptor_count(1000);                   // 池里准备 1000 个这种 descriptor

let pool_info = vk::DescriptorPoolCreateInfo::default()
    .pool_sizes(std::slice::from_ref(&pool_size))
    .max_sets(1000)                            // 整个池最多分配 1000 个 set
    .flags(vk::DescriptorPoolCreateFlags::empty());  // 注意:不加 FREE_DESCRIPTOR_SET 标志

let descriptor_pool = unsafe {
    device.create_descriptor_pool(&pool_info, None)
}.unwrap();
```

这里有几个**生产现实**要拎出来,因为它们和你以后调优直接相关。

第一,**池的 size 要给够,但不可以"超额"**。你声明 1000 个 UNIFORM_BUFFER descriptor,池就只能给这么多。超出会分配失败。所以生产引擎会根据场景预估上限——比如"场景里最多 5000 个物体,每个 3 个 binding,总共 15000",池给到这个上限。这是手动管理,但只发生在加载时,不在每帧。

第二,**flags 默认不带 `FREE_DESCRIPTOR_SET`**。意思是你可以从池里 `allocate` set、可以整个池 `reset`(一次性清空所有 set),但不能单独 `free` 一个 set。这个限制是 driver 友好的——单独 free 会让池内部产生碎片,driver 要维护空闲链表。Vulkan 默认不让你这么做,逼你用"reset 整个池"这种粗粒度方式管理。如果你的引擎需要单独 free(比如物体动态卸载),你要显式加 `FREE_DESCRIPTOR_SET` flag,接受性能代价。大多数引擎选择"每帧 reset 整个池,重新分配所有 set"——因为 descriptor set 内容每帧都要重写,重置再分配比逐个更新便宜。

第三,**池的"类型"和"数量"是一个二维预算**。`pool_sizes` 是一个数组,你可以一次声明多种类型的预算:1000 个 UNIFORM_BUFFER + 500 个 COMBINED_IMAGE_SAMPLER + 200 个 STORAGE_BUFFER。`max_sets` 是 set 总数上限,不管每个 set 里是什么。这两个预算是独立的——你可能用 100 个 set、每个用 10 个 binding,也可能用 1000 个 set、每个 1 个 binding,池都得容纳。

descriptor pool 是"内存来源层"——它告诉你 descriptor 从**哪儿来**。具体到每个 descriptor set 里写什么数据,是下一层。

## 4 · 第三层:Descriptor set——实际绑定的数据

第三层对象叫 **descriptor set(描述符集)**,这是这一篇的主角——所有别的对象都是为它服务的。descriptor set 是**实际绑定的数据**:它把"binding 0 是一个 UBO"这个声明,变成"binding 0 是这块具体的 uniform buffer、偏移 0、范围 64 字节"这种**具体引用**。

你从 pool 里 allocate 一个 set,这个 set 的"形状"由 descriptor set layout 决定:

```rust
let set_alloc_info = vk::DescriptorSetAllocateInfo::default()
    .descriptor_pool(descriptor_pool)
    .set_layouts(std::slice::from_ref(&descriptor_set_layout));

let descriptor_set = unsafe {
    device.allocate_descriptor_sets(&set_alloc_info)
}.unwrap()[0];
```

allocate 出来的 set,此刻**还没有具体数据**——它有 binding 0 这个槽位,但槽位是空的。你要往槽位里"写"具体引用,告诉它"binding 0 指向这块 uniform buffer"。这个写操作叫 `vkUpdateDescriptorSets`,在 ash 里是 `device.update_descriptor_sets`:

```rust
let buffer_info = vk::DescriptorBufferInfo::default()
    .buffer(uniform_buffer)        // 你创建的 uniform buffer 的 handle
    .offset(0)
    .range(std::mem::size_of::<MvpUbo>() as u64);   // 64 字节(mat4)

let write = vk::WriteDescriptorSet::default()
    .dst_set(descriptor_set)                          // 写到哪个 set
    .dst_binding(0)                                   // 写到 binding 0
    .dst_array_element(0)
    .descriptor_type(vk::DescriptorType::UNIFORM_BUFFER)
    .buffer_info(std::slice::from_ref(&buffer_info));

unsafe {
    device.update_descriptor_sets(std::slice::from_ref(&write), &[]);
}
```

注意 `update_descriptor_sets` 是**一次写完、之后只读**的。你写完之后,descriptor set 的 binding 0 就指向了那个 uniform buffer——只要不重新 update,它永远指向那里。这是和 OpenGL 的根本区别:OpenGL 是每次 draw 前 `glUniform*` 写值;Vulkan 是写一次 descriptor set,之后无数个 draw 都用这份引用,你只是每帧更新 uniform buffer **里的内容**(buffer 的 handle 不变)。这就是"binding 一次,数据流变"的模型——driver 知道 binding 是稳定的,可以在 pipeline 创建时把"binding 0 → 哪个硬件寄存器/常量槽"的映射烤死,draw 时只是把寄存器指针切到那个 buffer。

还有一个关键概念:**descriptor set 和 uniform buffer 是两个不同的对象**。uniform buffer 是一段 GPU 可读的内存(里面装 64 字节的矩阵),descriptor set 是"指向那段内存的引用"。GPU 跑 shader 时,通过 descriptor set 找到 buffer,再从 buffer 读数据。这个间接层看起来多余,但它的价值在于**解耦**——同一个 buffer 可以被多个 descriptor set 引用,同一个 descriptor set 也可以引用 buffer 的不同区段(offset/range)。生产引擎里,你会把所有物体的 MVP 矩阵打包进**一个**大 uniform buffer,然后用"动态偏移"(dynamic uniform buffer)的技巧,让每个 draw 用同一个 descriptor set、不同 offset 访问各自那块——后面讲动态对齐时还会回到这点。

descriptor set 是"数据层"——它告诉你 binding **具体指向哪**。但 shader 怎么"看到"这个 set 呢?这是下一层。

## 5 · 第四层:Pipeline layout——shader 看到的接口

第四层对象叫 **pipeline layout(管线布局)**,它在 [09C-4](09C-4-graphics-pipeline-first-triangle.md) 你已经见过——当时它是"空的",因为第一个三角形没数据。现在你要往里塞东西了。

pipeline layout 是 **shader 看到的接口**:它告诉 pipeline"我的 shader 会用到几个 descriptor set、每个 set 是什么 layout,以及有哪些 push constant(下一节讲)"。它是 descriptor set layout 的"集合包装"。

为什么需要这一层包装,不能直接把 descriptor set layout 喂给 pipeline?因为 Vulkan 支持同时绑定**多个** descriptor set——典型的设计是 set 0 是"全局相机"UBO(每个 draw 都用同一份)、set 1 是"材质"(每个材质一份)、set 2 是"物体"UBO(每个 draw 一份)。pipeline layout 就是把这些 set layout 按顺序排好,告诉 pipeline"set 0 是这个 layout、set 1 是那个 layout……"。draw 的时候,你 `vkCmdBindDescriptorSets` 绑定多个 set,GPU 按 layout 描述去解析。

```rust
let pipeline_layout_info = vk::PipelineLayoutCreateInfo::default()
    .set_layouts(std::slice::from_ref(&descriptor_set_layout));  // 只有 set 0

let pipeline_layout = unsafe {
    device.create_pipeline_layout(&pipeline_layout_info, None)
}.unwrap();
```

创建好 pipeline layout,你 [09C-4](09C-4-graphics-pipeline-first-triangle.md) 的 `vkCreateGraphicsPipelines` 就用这个 layout——pipeline 创建时,driver 已经知道"shader 需要 binding 0 上的 UBO、绑在 vertex stage"。这份信息被烤进了 pipeline 对象。运行时你 bind pipeline + bind descriptor set,driver 几乎只是切指针,没有校验、没有查找。

注意一个**重要的工程实践**:pipeline layout 创建之后,所有用它的 descriptor set 都必须"兼容"——也就是说,你 bind 的 descriptor set 必须是用兼容的 set layout allocate 出来的,否则验证层报错。这个"layout 兼容性"是 Vulkan descriptor 系统的一个核心规则——它保证了 pipeline 烤死的"binding 映射"在运行时不会被破坏。生产引擎会用 **Push-only/Immurable layout** 或者更新的 `VK_EXT_descriptor_buffer` 把这套规则管理起来,但对第一个旋转三角形,你只要记住:**一个 pipeline layout、一个 set layout、一个 set,三者一一对应**。

## 6 · 第五个动作:Bind,在 draw 之前

四层对象都讲完了,最后一步是把 descriptor set 接到 pipeline 上,这个动作发生在**命令缓冲录制时**,在 `cmd_bind_pipeline` 之后、`cmd_draw` 之前:

```rust
unsafe {
    device.cmd_bind_descriptor_sets(
        cmd,
        vk::PipelineBindPoint::GRAPHICS,   // 这根 pipeline 是 graphics 的
        pipeline_layout,
        0,                                  // 从 set 0 开始绑
        std::slice::from_ref(&descriptor_set),  // 要绑的 set
        &[],                                // 动态偏移(本节不用,留空)
    );
}
```

bind 之后,直到你下一次 bind 同一个 binding 位置上的别的 set,这个 set 都"挂着",后续所有 draw 都用它。这就是为什么"set 0 全局、set 1 材质、set 2 物体"的分层设计能省 binding——你画一千个物体时,set 0 bind 一次,set 1 在切换材质时 bind,set 2 每个 draw bind 一次。bind 操作本身是廉价的(就是切指针),所以这个分层不是性能优化,是**代码组织**的优化——让你按"变化频率"组织 binding。

到这里,Vulkan descriptor 系统的五层(schema、内存来源、数据、shader 接口、bind 动作)就全部讲完了。它们的关系,我帮你串一遍:descriptor set layout 是 schema(声明结构),你拿它和 pool 一起 allocate 出 descriptor set(空槽位),你 update descriptor set 把它指向真实的 uniform buffer(填数据),你把 descriptor set layout 包进 pipeline layout(给 pipeline 用),最后在 draw 之前 bind descriptor set(GPU 知道去哪读数据)。这五层之间的协作图,你画一遍贴在墙上,以后写 Vulkan 代码的速度会快一倍。

## 7 · Uniform buffer:那段装矩阵的 GPU 内存

descriptor 的"槽"是引用,真正装数据的是 **uniform buffer(统一缓冲,UBO)**——一段 GPU 可读、CPU 可写的 buffer,里面装 MVP 矩阵。

创建 UBO 和创建别的 buffer 没什么区别(详细的 buffer 创建在 [09C-2](09C-2-instance-device-swapchain.md) 已经讲过 vkBuffer 的套路,这里聚焦 UBO 特有的部分):

```rust
#[repr(C)]
#[derive(Clone, Copy)]
struct MvpUbo {
    mvp: [[f32; 4]; 4],   // mat4,GLSL 里 16 字节对齐
}

let ubo_size = std::mem::size_of::<MvpUbo>() as vk::DeviceSize;

let buffer_info = vk::BufferCreateInfo::default()
    .size(ubo_size)
    .usage(vk::BufferUsageFlags::UNIFORM_BUFFER)
    .sharing_mode(vk::SharingMode::EXCLUSIVE);

let uniform_buffer = unsafe {
    device.create_buffer(&buffer_info, None)
}.unwrap();

// 分配绑定的内存(VkDeviceMemory),用 vkGetBufferMemoryRequirements + vkAllocateMemory + vkBindBufferMemory
// 详细步骤和 09C-2 的 vertex buffer 完全一样
```

UBO 的关键不在创建,而在**两个细节**:怎么把 CPU 上的矩阵写进去(std140 对齐),以及**每帧怎么更新**。

### 7.1 std140 对齐:那个让新手发疯的陷阱

GLSL 里 `uniform UBO { mat4 mvp; }` 这种结构体,在 GPU 端用的是一种叫 **std140** 的内存布局规则。std140 是 OpenGL/Vulkan 的标准布局,目的是让"shader 里声明的结构体"和"CPU 端的内存布局"可以独立、可移植地匹配——不依赖任何编译器的 ABI。但 std140 的规则和 C/Rust 的默认 `#[repr(C)]` **不完全一样**,这就是新手最容易踩的坑。

std140 的核心规则,我用大白话讲:每个 `mat4` 占 64 字节、起始地址按 16 字节对齐(这是 `#[repr(C)]` 的 `[[f32;4];4]` 也满足的,所以我们的 `MvpUbo` 没事)。但**陷阱在嵌套结构体的数组和 vec3**:一个 `vec3` 在 std140 里**按 16 字节对齐**(不是 12),因为它被当作 vec4 处理——这是因为某些 GPU 硬件读取 vec3 时,实际上是按 vec4 的 lane 读,如果只占 12 字节,数组里下一个元素就和它部分重叠。所以 std140 把 vec3 数组的每个元素撑到 16 字节。一个 `vec3 arr[3]` 在 std140 里占 48 字节(每个 16),而不是 36 字节。

这个陷阱在你的 UBO 只有 `mat4 mvp` 时不会触发(mat4 正好 16 字节对齐),但你只要往 UBO 里加更多字段(再加一个 vec3 light_pos,或者一个 vec4 数组),就要小心。CPU 端的 Rust 结构体必须**显式按 std140 对齐**,有几种做法:第一种,手动加 padding 字段;第二种,用一个专门做 std140 对齐的 crate(比如 `crevice`,它自动生成 std140 兼容的 Rust 类型);第三种,用 `bytemuck` 加 `#[repr(C, align(16))]`。

**生产代码强烈推荐 `crevice` 这类库**——它让你写 `struct UBO { mvp: Mat4, light: Vec3 }`,库自动在 Rust 端按 std140 撑出 padding,你 `as_bytes()` 直接喂给 Vulkan。手算对齐在结构体变复杂后会出错,而且错误是隐性的(数据看起来对、画面错)。这是这一篇给你的一个"工程纪律":**UBO 结构体永远用 crevice 或等价库,不要手算 std140**。

还有一个相关的、更阴间的陷阱叫 **min UBO alignment**。Vulkan 实现可能要求 UBO 起始地址按某个最小值对齐(常见 256 字节,某些移动 GPU 是 16 或 32)。你可以 `vkGetPhysicalDeviceProperties` 查 `min_uniform_buffer_offset_alignment`。如果你的 UBO 比这个小、又想用 dynamic uniform buffer(下面讲),就要把 UBO 撑到这个对齐的倍数。第一个旋转三角形只有单个 UBO、不用 dynamic,这个陷阱先不触发,但你要知道它存在——它会在你做"一个大 UBO 装多个物体矩阵"时跳出来。

### 7.2 每帧更新 UBO:持久映射 + 写入

每帧你想让三角形旋转一个角度,就要把新的 MVP 矩阵写进 UBO。两种写法。

第一种,**持久映射(persistent mapping)**——你在创建 UBO 时,把它的 `VkDeviceMemory` `vkMapMemory` 一次,拿到一个 CPU 可写的指针,从此 CPU 直接写指针、GPU 直接读内存,不再 unmap。这是 Vulkan 的标准做法,比 OpenGL 的 `glBufferData` 每帧重传快得多。需要你的 memory property 有 `HOST_VISIBLE`(CPU 能看到) + `HOST_COHERENT`(CPU 写完 GPU 立刻可见,不需要显式 flush)——这两个 flag 几乎所有实现都支持,你 allocate memory 时选带有这两个 flag 的 memory type 就行。

```rust
// 把 host 可见的 memory map 出来,CPU 端持有这个指针
let ptr: *mut u8 = unsafe {
    device.map_memory(ubo_memory, 0, ubo_size, vk::MemoryMapFlags::empty())
}.unwrap() as *mut u8;

// 每帧:算 MVP,写进 mapped memory
fn update_ubo(ptr: *mut u8, angle: f32) {
    let mvp = compute_mvp(angle);   // 你用 nalgebra/glm 算出来的 [[f32;4];4]
    unsafe {
        std::ptr::copy_nonoverlapping(
            mvp.as_ptr() as *const u8,
            ptr,
            std::mem::size_of::<MvpUbo>(),
        );
    }
}
```

第二种,**double/triple-buffered UBO**——你为每个 swapchain image 准备**一份独立的 UBO**(双缓冲就两个),每个 image 对应一份。为什么?因为 CPU 在写第 N 帧的 UBO 时,GPU 可能还在读第 N-1 帧的 UBO——如果只有一个 UBO,CPU 写覆盖了 GPU 还在读的数据,画面错乱。这是 [09C-3](09C-3-command-buffers-and-synchronization.md) 同步问题的延续:CPU 和 GPU 并行跑,共享数据要分桶。最简单的做法是"每个 swapchain image 一份 UBO",用 `current_image_index` 切换。

```rust
// 三个 swapchain image,三份 UBO,三个 mapped 指针
let uniform_buffers: Vec<vk::Buffer> = (0..swapchain_image_count).map(|_| {
    create_ubo(&device, ubo_size)
}).collect();
let mapped_ptrs: Vec<*mut u8> = ...;   // 每份 UBO 都 map 出来

// 每帧,只更新当前 image_index 对应的那份
update_ubo(mapped_ptrs[image_index as usize], angle);
```

**生产代码的更优解**是用一个统一的"staging buffer" + triple-buffer ring——一个大的 HOST_VISIBLE buffer,CPU 写环形队列,GPU 读。但第一个旋转三角形,"每个 swapchain image 一份 UBO"完全够用,概念清晰。

## 8 · Push constants:小数据的轻量通道

到这里你已经能用 UBO + descriptor 把 MVP 喂给 GPU 了,你的三角形可以转。但在结束这一篇之前,我要讲一个**重要的替代方案**——**push constants(推送常量)**,它是 Vulkan 提供的另一条 CPU→shader 数据通道,用法完全不同,适用场景也完全不同。

push constants 是一种**通过命令缓冲直接传数据**的机制。你不创建 buffer、不创建 descriptor set,你在录制命令缓冲时,直接 `vkCmdPushConstants` 把几个字节"塞"进命令流,GPU 执行这条命令时,数据就在 shader 的 push constant block 里。

```glsl
// shader 端
layout(push_constant) uniform PushConstants {
    mat4 mvp;
} pc;
```

```rust
// CPU 端,录制命令缓冲时
unsafe {
    device.cmd_push_constants(
        cmd,
        pipeline_layout,
        vk::ShaderStageFlags::VERTEX,
        0,                                                          // offset
        std::mem::size_of::<MvpUbo>() as u32,                       // size
        &mvp as *const _ as *const u8,                              // 数据指针
    );
}
```

push constants 的**优点**:没有创建 buffer、没有 descriptor set、没有 pool,极简。**缺点**:容量极小,spec 保证的最小容量只有 **128 字节**(具体实现可能更多,NVIDIA 一般是 256 字节)。128 字节,只够放两个 mat4 + 一些零碎,放不下大数组。

那 push constants 和 UBO 怎么选?我给你一个清晰的判据:**数据小(几个矩阵、几个 vec)、每个 draw 都不同,用 push constants;数据大(数组、灯光列表)或者一个 set 多个 draw 共享,用 UBO + descriptor**。MVP 矩阵恰好是 push constants 的甜点场景——一个 mat4 是 64 字节,远小于 128;每个 draw 的 MVP 不同。很多引擎把 MVP 这种 per-draw 数据走 push constants,把"相机参数"、"场景灯光列表"这种 per-frame 数据走 UBO。

push constants 还有一个隐藏的优势:**没有同步问题**。你 push 的数据是命令缓冲的一部分,GPU 执行这条命令时读到,不存在"CPU 在写 GPU 在读"的并发——因为命令缓冲一旦 submit,GPU 读到的就是 push 时刻的快照(CPU 不能再改这段数据,直到命令缓冲被回收)。这就是为什么 push constants 不需要 double-buffer,而 UBO 需要——这是它"轻量"的另一面。

对你的第一个旋转三角形,你可以用 push constants 实现,代码会比 UBO 版本短得多(没有 buffer 创建、没有 descriptor set 四层)。但我建议你**先用 UBO 走通一遍**,因为 UBO 是 descriptor 系统的"入门案例",09C-6 你加纹理时还要再用 descriptor sampled image——push constants 教不了你 descriptor 系统的运作。先用 UBO 学 descriptor,push constants 作为"我也知道有这条捷径"的备选。

## 9 · 把它装到 09C-4 的三角形上:MVP 更新,三角形旋转

到这里所有概念都讲完了,我把整个数据流串一遍,让你看清"三角形旋转"这件事是怎么发生的。

CPU 端,你每一帧做三件事。第一,**算 MVP 矩阵**:用 `nalgebra` 或 `glam` 这种数学库,根据当前时间 `angle = elapsed * rotation_speed`,构造一个绕 Z 轴的旋转矩阵 R,然后 `mvp = projection * view * R`。第二,**写进 UBO**:把矩阵 copy 到当前 image_index 对应的 mapped 指针。第三,**录制命令缓冲**时,bind descriptor set(指向 UBO),draw。

GPU 端,vertex shader 拿到 binding 0 上的 UBO,读出 `mvp`,把每个顶点位置乘以 `mvp`,得到旋转后的位置。光栅化把旋转后的位置涂成像素,fragment shader 输出颜色——你看到三角形在转。

完整的一帧循环(在 09C-3 同步循环基础上加 UBO 部分):

```rust
fn render_frame(
    device: &ash::Device,
    cmd: vk::CommandBuffer,
    pipeline: vk::Pipeline,
    pipeline_layout: vk::PipelineLayout,
    descriptor_sets: &[vk::DescriptorSet],   // 每个 swapchain image 一个 set
    framebuffer: vk::Framebuffer,
    render_pass: vk::RenderPass,
    extent: vk::Extent2D,
    mapped_ptrs: &[*mut u8],                 // 每个 UBO 的 mapped 指针
    image_index: u32,
    elapsed: f32,
) {
    // 1. 算 MVP(用 glam 举例)
    let angle = elapsed * std::f32::consts::FRAC_PI_2;   // 每秒 90 度
    let rotation = Mat4::from_angle_z(Rad(angle));
    let view = Mat4::look_at_rh(Vec3::new(0.0, 0.0, 3.0), Vec3::ZERO, Vec3::Y);
    let aspect = extent.width as f32 / extent.height as f32;
    let projection = Mat4::perspective_rh_gl(45.0_f32.to_radians(), aspect, 0.1, 10.0);
    let mvp = projection * view * rotation;
    let mvp_bytes: [[f32; 4]; 4] = mvp.to_cols_array_2d();

    // 2. 写进当前 image 的 UBO
    unsafe {
        std::ptr::copy_nonoverlapping(
            &mvp_bytes as *const _ as *const u8,
            mapped_ptrs[image_index as usize],
            std::mem::size_of::<[[f32; 4]; 4]>(),
        );
    }

    // 3. 录制命令缓冲
    unsafe {
        device.begin_command_buffer(cmd, &vk::CommandBeginInfo::default()).unwrap();

        let clear_color = vk::ClearValue {
            color: vk::ClearColorValue { float32: [0.0, 0.0, 0.0, 1.0] },
        };
        let rp_info = vk::RenderPassBeginInfo::default()
            .render_pass(render_pass)
            .framebuffer(framebuffer)
            .render_area(vk::Rect2D {
                offset: vk::Offset2D::ZERO,
                extent,
            })
            .clear_values(std::slice::from_ref(&clear_color));

        device.cmd_begin_render_pass(cmd, &rp_info, vk::SubpassContents::INLINE);
        device.cmd_bind_pipeline(cmd, vk::PipelineBindPoint::GRAPHICS, pipeline);

        let viewport = vk::Viewport {
            x: 0.0, y: 0.0,
            width: extent.width as f32, height: extent.height as f32,
            min_depth: 0.0, max_depth: 1.0,
        };
        device.cmd_set_viewport(cmd, 0, std::slice::from_ref(&viewport));
        device.cmd_set_scissor(cmd, 0, std::slice::from_ref(&vk::Rect2D {
            offset: vk::Offset2D::ZERO,
            extent,
        }));

        // 4. bind descriptor set(指向当前 image 的 UBO)
        device.cmd_bind_descriptor_sets(
            cmd,
            vk::PipelineBindPoint::GRAPHICS,
            pipeline_layout,
            0,
            std::slice::from_ref(&descriptor_sets[image_index as usize]),
            &[],
        );

        device.cmd_draw(cmd, 3, 1, 0, 0);
        device.cmd_end_render_pass(cmd);
        device.end_command_buffer(cmd).unwrap();
    }
}
```

注意一个细节:**descriptor set 也要每个 image 一份**(`descriptor_sets[image_index]`),因为每个 set 指向不同的 UBO——你创建了 `swapchain_image_count` 个 UBO,就要创建同样数量的 descriptor set,每个 set 指向一个 UBO。bind 时按 image_index 选。这是 UBO 路径下"同步分桶"的完整实现。

跑起来,你应该看到三角形从初始位置开始、绕 Z 轴匀速旋转(透视投影下,远的边变小、近的边变大,所以不再是等腰三角形——这是"3D 化"的第一次信号)。验证层一声不吭。

## 10 · 生产现实:bindless resources,这是真正的大杀器

到这里你已经会用 descriptor 画一个旋转三角形,但我要给你一个**前向视角**——你刚刚学到的"每个物体一个 descriptor set、每个 draw 之前 bind"这套流程,在真实引擎里**根本不是这么用的**。真实引擎用的是 **bindless resources(无绑定资源)**,也叫 **descriptor indexing**(Vulkan 1.2 的核心特性)。

讲清楚为什么。你想象一个场景:一万个物体,每个一个网格、一个 MVP、一个漫反射贴图。按你刚学的方法,你要给每个物体准备一个 descriptor set、每个 draw 之前 bind 一次。一万个 bind call,即使每个 bind 只是切指针,加起来也是不小的 CPU 开销——而且更糟的是,你要管理一万个 descriptor set 的生命周期,内存碎片、池上限、reset 时机,全都是麻烦。

bindless 的思路是反过来:**只 bind 一个 descriptor set 一次,这个 set 里"装着"所有物体的资源(所有贴图、所有 buffer),shader 通过"索引"访问当前物体的那一部分**。具体说,descriptor set 里的某个 binding 声明"我是不定长 sampled image 数组",你在更新 set 时把所有贴图都绑进去(可能上千张),shader 端用一个 `texture_index`(从 push constant 或 vertex attribute 来)做 `textures[texture_index]` 访问。同样,所有 MVP 矩阵打包进一个 storage buffer(或一个大 UBO),shader 用 `mvp_buffer[draw_id]` 访问。

这个模型下,你**每帧只 bind 一次 descriptor set**,然后画一万个 draw,每个 draw 只是 push 一个 index——bind 次数从一万降到一,driver 几乎完全不参与绘制,这是 GPU-driven rendering 的基础。你后面在 [09B-3 frame graph](09B-3-frame-graph.md) 之外学的 GPU-driven pipeline、indirect draw,都建立在 bindless 之上。

Vulkan 1.2 把 descriptor indexing 升级成了 core 特性(`VK_EXT_descriptor_indexing` 已并入 core),你不用再开 extension、不用再查 feature——直接用。它的核心 API 变化:descriptor set layout 里某个 binding 可以标 `PARTIALLY_BOUND`(只有部分元素被实际绑了)或者 `VARIABLE_DESCRIPTOR_COUNT`(数组长度运行时定),`update_descriptor_sets` 可以只更新数组里的某个元素。shader 端要加 `#extension GL_EXT_nonuniform_qualifier : enable`,用 `nonuniformEXT` 标记"这个索引在不同 invocation 上可能不同",GPU 才能正确处理 divergence。

我提这一切,不是要你第一个旋转三角形就上 bindless——那是 09C-6 以后的事。是让你**知道这条路的终点在哪**,这样你今天学的"单个 descriptor set"不会让你误以为"Vulkan 一直这么用"。今天学的四层对象、bind 的概念,是 bindless 的地基;bindless 是把这套机制推到极致——"bind 一次,管一切"。你以后做 HH 项目的渲染器,做几百物体场景时,会回到这条路上。现在打好地基,是为了那时能上得去。

## 11 · 在你 HH 项目里动手(做中学红线)

这一篇的做中学,是把 09C-4 那个静态的彩色三角形,**升级成绕 Z 轴旋转的三角形**。结束时,你的窗口里三角形匀速转动,验证层干净。

第一步,**装数学库**。在 HH 项目的 `Cargo.toml` 里加 `glam`(或者 `nalgebra`,看你喜好)。`glam` 更轻、API 更直接,推荐。`cargo add glam` 即可,Arch 上不需要额外系统包。

第二步,**改 shader**。把 09C-4 的 `triangle.vert` 加上 `layout(binding = 0) uniform UBO { mat4 mvp; };`,把 `gl_Position = vec4(positions[gl_VertexIndex], 0.0, 1.0);` 改成 `gl_Position = mvp * vec4(positions[gl_VertexIndex], 0.0, 1.0);`。fragment shader 不变。重新 `glslangValidator -V` 编出新的 `.spv`。

第三步,**创建 descriptor set layout**。一个 binding,binding 0,UNIFORM_BUFFER,vertex stage。代码用我 §2 给的样板。验证创建成功。

第四步,**创建 descriptor pool 和 descriptor set**。pool size 给 100(留余量),先给一个 set 就行。注意:虽然你最终要每个 image 一份 set,但**先用一份 set 验证通路**——只让一个 image 能用、其他黑屏也没关系,先确认 descriptor 机制跑通。allocate 出一个 set。

第五步,**创建 UBO**。用 09C-2 的 buffer 创建套路,usage 是 UNIFORM_BUFFER,memory flag 是 HOST_VISIBLE | HOST_COHERENT。`map_memory` 拿到指针,持久持有。size 至少 64 字节(mat4)。第一份就行,先跑通。

第六步,**update descriptor set**,把 binding 0 指向你的 UBO(offset 0,range 64)。代码用我 §4 的样板。

第七步,**重建 pipeline layout**,从 09C-4 的空 layout 改成包含你的 descriptor set layout。然后**重建 pipeline**(`vkCreateGraphicsPipelines` 那一步的 pipeline_layout 参数换成新的)。pipeline 本身其它 create-info 不变。

第八步,**改录制函数**。在 `cmd_bind_pipeline` 之后、`cmd_draw` 之前,加 `cmd_bind_descriptor_sets`。代码用我 §9 的样板。

第九步,**在 main loop 里加 MVP 更新**。每帧算 `angle = elapsed * 0.5`(每秒约 28 度,慢一点便于观察),构造 rotation / view / projection,把 mvp 写进 mapped pointer。然后跑 acquire→record→submit→present 的循环(09C-3 已经写好)。

第十步,**跑,看屏幕,看验证层**。三角形应该匀速旋转。如果黑屏或验证层报错,按下面排查清单查。

第十一步(可选但强烈建议),**扩展到每个 image 一份 UBO + 一份 set**。创建 N 份 UBO 和 N 份 set,update 每个 set 指向对应 UBO,bind 时按 image_index 选。这一步消除"CPU 在写、GPU 在读"的潜在冲突,是正确做法。

验收标准:**三角形绕 Z 轴匀速旋转,透视投影下边长有变化(3D 效果),验证层零报错,跑稳定**。截一张旋转中的图存到 dev log。

提交 commit 时,在 message 里记录:你踩过的对齐坑(如果有)、UBO 是否做了 multi-image buffer、用了 push constants 还是 UBO。这些记录以后回头看时,会帮你回忆起整条数据通道的形状。

## 12 · descriptor 系统最常见的五个 bug

我把新手在这一篇最容易踩的坑总结一下,作为你黑屏时的排查清单。

第一个,**descriptor set layout 的 binding 和 shader 的 binding 对不上**。shader 写 `layout(binding = 0)`,CPU 端 set layout 写 `.binding(0)`,数字要完全一致。新手有时写 0 写 1 写混,验证层会报"shader 要求的 binding 在 set 里不存在"。

第二个,**update descriptor set 时 buffer_info 的 range 错了**。range 是"这个 binding 上 GPU 能访问的字节数",你写 `range = size_of::<MvpUbo>()`,64 字节。如果你写 0 或者写了一个不正确的值(比如忘了 `as u64`),GPU 读 UBO 时越界或读不到数据,vertex shader 拿到全 0 矩阵,三角形要么不画、要么画在屏幕外。

第三个,**pipeline layout 没包含 descriptor set layout**。pipeline_layout_info 的 `set_layouts` 是空的(09C-4 的状态),但你 bind 了一个 set——验证层会报"pipeline layout 不支持这个 set"。

第四个,**UBO 没有按 min uniform buffer offset alignment 对齐**。第一个旋转三角形单个 UBO 不触发,但你做 dynamic UBO 时(一个 buffer 装多份),offset 必须按 `min_uniform_buffer_offset_alignment` 对齐,通常要写一个 `align_to(size, alignment)` 工具函数。新手常忽略这个 alignment,导致 dynamic offset 错位、画面错乱。

第五个,**忘了 multi-buffer UBO,导致 CPU/GPU 数据竞争**。只有一个 UBO,CPU 写第 N 帧、GPU 读第 N-1 帧,数据被覆盖,画面闪烁或崩溃。验证层**不一定**报(它不模拟精确时序),你要靠"每帧一份 UBO"这个工程纪律来防。

黑屏排查顺序:验证层报错没(报了就修)、shader 的 binding 和 set layout 的 binding 对得上没、update 时 range 对没、pipeline_layout 含 set_layout 没、UBO 是不是 multi-buffer。这套排查清单在你做 descriptor 的夜里会救你。

## 13 · 练习

练习一,Lv1 概念辨析。descriptor 系统为什么是"分层"的(schema、内存来源、数据、shader 接口),而不是像 OpenGL 那样一行 `glUniform*` 搞定?因为 Vulkan 把 OpenGL driver 在每次 draw 时做的"查找 location、装填常量、校验匹配"全部前移到创建时,分层让每一步都成为可校验、可缓存的不可变对象。请把这个权衡用一句话复述。

练习二,Lv1 概念辨析。push constants 和 UBO 什么时候选哪个?push constants 适合"小数据(几十字节)、每个 draw 都不同";UBO 适合"大数据、或多个 draw 共享"。MVP 这种 per-draw 数据,两条路都能走,生产里常见的是 push constants。请解释为什么 push constants 不需要 double-buffer,而 UBO 需要。

练习三,Lv2 动手实践。完成前面 §11 的全部步骤,让你的三角形绕 Z 轴匀速旋转。要求:验证层干净、用了 multi-image buffer(每个 swapchain image 一份 UBO)、用了 glam 或 nalgebra 算 MVP。把验证层日志、屏幕截图、踩坑记录写进 commit message。

练习四,Lv3 迁移设计。在不实际写代码的前提下,你 HH 渲染器里"主相机 + 100 个物体"的场景如果迁到 Vulkan,你怎么设计 descriptor set 的分层?(典型答案:set 0 是全局相机 UBO,整个 frame 一次 bind;set 1 是物体 UBO 数组 + draw_id,push constants 传 draw_id。或者:set 0 全局,set 1 per-material, MVP 走 push constant。)把这个设计写在你的 dev log 里,讨论你为什么这么分层。

练习五,Lv4 开源探索。在 Vulkan 1.2 的 spec 或 Sascha Willems 的 examples 里找到 `descriptor-indexing` 这个例子,读它怎么用 `VARIABLE_DESCRIPTOR_COUNT` 和 `nonuniformEXT`。**不要运行**,只在脑子里回答:它和你的"每个物体一个 descriptor set"做法相比,bind 次数减少了多少?为什么这种模式叫"GPU-driven"?把你的理解写进 dev log,09C-6 你会用上类似的思路。

## 14 · 延伸阅读与下一篇

这一篇最权威的参考是 Vulkan spec 的 *Resource Descriptors* 章节,以及 *Descriptor Sets* 小节里关于 layout compatibility、update-after-bind 这些规则的细节。最友好的实践教程仍然是 vulkan-tutorial.com 的 "Descriptor sets" 和 "Uniform buffers" 那几节,它和你这一篇走的是同一条路。Sascha Willems 仓库里的 `descriptors`、`pushconstants`、`dynamicuniformbuffer` 三个例子是这一篇每个概念的"可运行范本",强烈建议至少读一遍 dynamic uniform buffer 那个——它会让你彻底理解 min alignment 这件事。

`crevice` 这个 crate 的文档值得读一下,它解释了 std140/std430 的所有规则,以及它怎么自动生成对齐的 Rust 类型——你写 production Vulkan 代码几乎一定会用它或等价库。

下一篇 [09C-6](09C-6-textures-and-samplers.md),你的三角形要从"色块"升级成"贴图几何"——你会在同一条 descriptor 通道上,加一种新的资源类型 **sampled image**(加上它的好搭档 sampler)。09C-6 会教你图像(image)的内存布局、layout 转换(barrier 复习)、sampler 的过滤模式,以及怎么在 descriptor set layout 里再加一个 binding、shader 里 `texture(sampler2D)` 怎么采样。descriptor 系统你已经懂了,09C-6 只是再加一种 descriptor 类型——这个学起来比这一篇轻得多。当你的三角形贴上第一张纹理,你就拥有了 3D 渲染的三大基石(几何、变换、纹理)中的第三个。
