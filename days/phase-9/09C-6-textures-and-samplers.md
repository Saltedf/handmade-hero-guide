---
phase: 9
sequence: "9C"
module: 6
title_en: "Textures & Samplers"
title_zh: "纹理与采样器:给三角形一张皮肤"
type: deep-dive
difficulty: 4
duration: "3-4 小时"
domains: [graphics, gpu, rust]
prereqs: ["09C-5-descriptors-and-uniforms"]
calibration: "Vulkan image/sampler spec + vulkan-tutorial 'Texture Mapping' 实践"
---

# 09C-6 · 纹理与采样器

## 0 · 你的三角形是平涂的,而你想给它贴一张图

我先把那个让你这一篇难熬的场景放在眼前。

[09C-4](09C-4-graphics-pipeline-first-triangle.md) 你画出了那个著名的红绿蓝渐变三角形,[09C-5](09C-5-descriptors-and-uniforms.md) 你给它接上了 uniform buffer、让它能随时间旋转、随相机摆动。一切运行如常,验证层一声不响。可是你看了一眼那个旋转的三角形,觉得不对劲——它是一块**纯色**。颜色是 fragment shader 算出来的、写死在代码里的或者从一个 uniform 传进来的,**它身上没有画**。你想给它一张图——一块木纹、一堵砖墙、一个角色的脸——你想让 fragment shader 在决定每个像素的颜色时,**从一个二维的数据表里去查**:这个像素对应图上的哪个点,就用那一点的颜色。

这件事听起来简单(不就是"读一张图嘛"),但在 Vulkan 里,它牵出两个全新的、必须分开理解的概念:**image(图像)** 和 **sampler(采样器)**。image 是 GPU 上二维(或三维)的、带布局的像素数据存储——它和 buffer 同源但长得完全不一样,有 mip levels、有 layers、有一个会随用途改变的"layout(布局)"。sampler 是一个**和 image 完全独立**的对象,它描述的不是"数据是什么",而是"**怎么读**这个数据"——缩小用什么滤波、放大用什么滤波、坐标超出 0..1 怎么办、要不要各向异性(anisotropic)。这两个对象被组合在一起,绑进 [09C-5](09C-5-descriptors-and-uniforms.md) 你已经熟悉的 descriptor set,作为一个 **combined image sampler(组合图像采样器)** binding,fragment shader 就能对它发出一句 `texture(sampler, uv)` 的查询,拿到对应像素的颜色。

这一篇,你要走过一整条链:把一张 PNG 解码成内存里的像素数组;创建一个 GPU image;把像素数据塞进去(因为不能直接写,要用 staging buffer 中转);在三个时机插三道 layout 转换的 barrier;创建一个 sampler;把它们包成 descriptor 绑进 pipeline;改写 shader 让它读纹理。结束时你的旋转三角形会穿上一张图——这是从"程序生成颜色"到"用美术资产"的跨越,Vulkan 学习里最实用的几个里程碑之一。

我先告诉你为什么这一篇不能跳:Vulkan 里 image 这一类对象是**整个 API 里坑最多的**——layout 转换忘了或转错,验证层会炸响,而且报错信息不那么直观;staging buffer 模式你以为只是个"小细节",但它在你日后做任何 GPU 资源上传(顶点缓冲、cube map、storage image)时都会再次出现,是 Vulkan 的基本节奏;descriptor 的 image 部分和 09C-5 的 buffer 部分共用一套 descriptor set 机制但又多了 image 视图、sampler 这些料,理解它,你才算真正吃透了"CPU 怎么把 GPU 资源交给 shader"。

## 1 · 为什么 GPU 的 image 比一块内存复杂得多

你可能会想,纹理不就是一块连续的内存,每四个字节一个 RGBA 像素,排列成 width × height 的方阵吗?CPU 上你确实可以这么理解。但 GPU 上不行。

GPU 的 image 是**有结构的**。它的像素不是简单地一行行紧密排列在内存里——根据 GPU 的硬件设计,像素可能被分块(tile)、swizzle(打乱通道顺序)、压缩(BC/ASTC/ETC2 块压缩格式)成另一种内存形状,这些形状**对每种用途最优**。一个 image 被作为渲染目标(render target)写时,它的内存形状要适合 ROP(Raster Output Processor,光栅化输出处理器)快速写入;同一个 image 被作为纹理在 shader 里读时,它的形状要适合纹理采样器(texture sampler unit,一个独立的硬件单元)快速做滤波采样。**这两者最优的形状往往不同**。

所以 Vulkan 里,每个 image 在任何时刻都处于一个明确的 **layout(布局)** 状态——这个 layout 告诉 GPU 驱动"我现在内部像素排成什么形状"。当你改变用途(从"被拷贝写"到"被 shader 读"),你必须**显式地**让 image 的 layout 发生转换。这个转换,正是 [09C-3](09C-3-command-buffers-and-synchronization.md) 反复强调的 pipeline barrier 的核心职责之一——barrier 同时做三件事:等顺序、刷缓存、转 layout。这一篇你会把那个抽象概念,落到三个具体的 layout 上手做一遍。

除了 layout,image 还带来几个 buffer 没有的概念。**Mip levels(多级渐远纹理)**:同一张图,从原始分辨率开始,逐级对半缩小,生成一系列更低分辨率的版本(1/2、1/4、1/8……)。GPU 在采样远处的片元时,自动选一个尺寸合适的 mip level,避免在远处高频振荡产生摩尔纹(Moiré),同时大幅降低纹理带宽。**Array layers(数组层)**:一张 image 里其实可以叠多个相同尺寸的二维切片,典型用途是 cube map(6 个面叠成一张 image)、texture array(材质数组,shader 一次绑定多个贴图)。**Format(格式)**:image 的像素不是只有 RGBA8888,Vulkan 有一两百种 format,从 R8 单通道到 BC 块压缩、到 depth/stencil 格式;format 决定了每个像素占多少字节、GPU 怎么解释。

把这些和 buffer 一对比,你就明白 image 为什么这么繁琐:buffer 就是一段连续内存,你写进去什么、读出来什么,中间没"形状"的概念;image 是一段**形状可变的、有等级的、有专用硬件单元的**资源,所以它需要一整套额外的机制来管理。理解 image 的多面性,是你日后学 render target(09C-7)、shadow map、G-buffer、post-processing input 的基础——它们全是 image,只是 layout 和用途不同。

## 2 · Staging buffer:你写不进 GPU 最优的 image 内存,只能"中转"一次

你已经在 09C-5 用 staging buffer 传过 uniform 数据(或者至少听说过它),但这一篇它要正式登场,而且这次它**不可省**——你必须用。

原因要回到 Vulkan 内存模型。GPU 上的内存,大致分两类。**Host-visible(主机可见)** 内存:CPU 能直接读写(它通常映射成 PCIe 上的一段),但 GPU 访问慢,因为每次都要走 PCIe。**Device-local(设备本地)** 内存:GPU 自己的高速显存,GPU 访问极快,但 CPU **不能直接写**(没有映射)。一个 image 如果要被 shader 高效采样,它必须存在 device-local 内存里,即所谓的 `MEMORY_PROPERTY_DEVICE_LOCAL_BIT`。但你的 PNG 解码出来的像素数组在 CPU 内存里,你怎么把它放进 CPU 写不进去的 device-local?

答案是经典的 staging pattern(中转模式)。第一步,你创建一个 **host-visible 的 staging buffer**,把 CPU 的像素数据 memcpy 进去(`map_memory` + 写 + `unmap_memory`)。第二步,你创建一个 **device-local 的 image**(它的内存对 CPU 不可写,但 GPU 极快访问)。第三步,你**提交一条 GPU 命令**——`vkCmdCopyBufferToImage`,这条命令在 GPU 上执行,把 staging buffer 的内容拷贝到 image 里。GPU 内部,GPU 自己从 staging buffer(走 PCIe 读)读到像素,然后写进 device-local image(走它自己的高速显存)。这之后,shader 高效采样 device-local image,而 staging buffer 就可以销毁了。

你也许会问:为什么不直接创建一个 host-visible 的 image 让 CPU 写,省掉中转?Vulkan 是允许 host-visible image 的,但这种 image 通常**不能被 shader 高效采样**(它没有 device-local 的高速形状),采样性能差一个数量级,且 host-visible image 在很多实现上功能受限(不支持 mip、不支持某些 format)。所以 staging pattern 不是 Vulkan 的"过度设计",它来自硬件本质:**GPU 高速访问的内存形状和 CPU 写入的内存形状不兼容,只能用一次中转把它们对接**。这个 pattern 在 Vulkan 里反复出现——你日后做动态顶点缓冲、storage image 上传、compute shader 输出读回,全是它。一次学会,终身受用。

staging pattern 还有一个常被忽略的隐含成本:那一次 `vkCmdCopyBufferToImage` 是 GPU 命令,你必须**提交、等 GPU 做完**才能销毁 staging buffer、才能让 image 进下一个 layout。这意味着纹理上传是一个**小型的"提交 + 等待"循环**——你通常在程序启动时建一个一次性的 command buffer、submit、`wait_for_fences`,做完一次性上传。在游戏运行时动态流式上传纹理(比如开放世界边走边加载),则需要更精细的 staging allocator 管理,这是一门独立的工程,这一篇先用最简单的"启动时一次性上传"版本。

## 3 · 三道 barrier:image 的 layout 在一次上传里的旅行

现在你要走完那三个 layout 转换。这是这一篇最容易出错的部分——错了,验证层会精确报,但你要会读它的报错。

一开始,image 刚被创建出来,它的 layout 是 **`UNDEFINED`**。这个 layout 的语义是"内容无意义,我可以任意写"。Vulkan 不允许你从 `UNDEFINED` 直接转到 `SHADER_READ_ONLY_OPTIMAL`(shader 高效读),因为转换 barrier 需要"在某个用途上可用",而 `UNDEFINED` 不是用途,是起点。

然后你要往 image 里拷贝数据,也就是 `vkCmdCopyBufferToImage` 这条命令要把它当**拷贝目标**用。在拷贝之前,你必须把 image 的 layout 从 `UNDEFINED` 转到 **`TRANSFER_DST_OPTIMAL`**(传输目标最优)。这是**第一道 barrier**:`UNDEFINED → TRANSFER_DST_OPTIMAL`。注意源 stage 选 `TOP_OF_PIPE`(其实没有源 access,因为 UNDEFINED),目的 stage 选 `TRANSFER`,目的 access 选 `TRANSFER_WRITE`。这一道 barrier 告诉 GPU:"从这一刻起,这个 image 的形状要适合被传输命令写"。

接着 `vkCmdCopyBufferToImage` 把 staging buffer 的像素拷贝进 image。拷贝完,image 里的数据有了,但 layout 还是 `TRANSFER_DST_OPTIMAL`,shader 不能读它(它不是 shader 友好的形状)。所以**第二道 barrier**:`TRANSFER_DST_OPTIMAL → SHADER_READ_ONLY_OPTIMAL`。源 stage `TRANSFER`,源 access `TRANSFER_WRITE`;目的 stage `FRAGMENT_SHADER`(因为你打算在 fragment shader 里采样),目的 access `SHADER_READ`。这一道 barrier 把 image 转成"shader 友好的、只读的"形状,从此 shader 就能高效采样它。

如果你要做 mipmap(下一节会讲),layout 转换会多几个来回:`TRANSFER_DST_OPTIMAL → TRANSFER_SRC_OPTIMAL`(让 blit 命令把它当源,生成下一级 mip),每生成一级都要在 dst 和 src 之间切一次。最后一级再从 `TRANSFER_SRC_OPTIMAL`(或 `TRANSFER_DST_OPTIMAL`)转到 `SHADER_READ_ONLY_OPTIMAL`。看起来繁琐,但每个 layout 都对应一个具体的 GPU 操作,barrier 让 GPU 的内存形状"恰好"对应当前的用途,这是 Vulkan 把硬件性能榨干的方式。

把这三道 barrier 和 [09C-3](09C-3-command-buffers-and-synchronization.md) 讲的"barrier 同时管顺序、缓存、layout"对照看——这里你亲眼看到了 layout 那一维。再和 [09B-3 frame graph](../phase-9/09B-3-frame-graph.md) 对照:在 frame graph 里,你只要声明"这个纹理在这个 pass 是只读输入、在下一个 pass 是可写 render target",frame graph **自动算出**每一步的 layout 转换和精确的 stage/access,生成 barrier,你手写这三道的过程,正是 frame graph 在你背后默默做的事。所以这一篇手写,不是"以后天天这么写",而是"理解了,日后 frame graph 替你写时你才能信任它、debug 它"。

## 4 · 完整的 image 创建 + 上传代码

把前面三节拼成一段完整的、能跑的 Rust(ash)代码。这段代码长,但每一块都对应前面讲过的概念,我加了注释,你跟着读一遍就能对上。

```rust
use ash::{vk, Device};

/// 从 CPU 侧的像素数据,创建一个 device-local 的、被填充好的 image。
/// 返回 (image, image_memory)。
fn create_texture_image(
    device: &Device,
    physical_device: vk::PhysicalDevice,
    graphics_queue: vk::Queue,
    command_pool: vk::CommandPool,
    allocator: &gfx_memory::Allocator,  // 你自己的内存分配器
    pixels: &[u8],          // RGBA8 像素,行优先
    width: u32,
    height: u32,
    mip_levels: u32,
) -> (vk::Image, vk::DeviceMemory) {
    // —— 1. staging buffer:host-visible,可被 CPU 写 ——
    let buffer_size = (pixels.len()) as vk::DeviceSize;
    let staging_create = vk::BufferCreateInfo::default()
        .size(buffer_size)
        .usage(vk::BufferUsageFlags::TRANSFER_SRC)         // 关键:用作拷贝的源
        .sharing_mode(vk::SharingMode::EXCLUSIVE);
    let staging_buffer = unsafe {
        device.create_buffer(&staging_create, None).unwrap()
    };
    let staging_mem = allocator.allocate_for_buffer(
        staging_buffer,
        vk::MemoryPropertyFlags::HOST_VISIBLE | vk::MemoryPropertyFlags::HOST_COHERENT,
    );

    // 把像素 memcpy 进 staging buffer
    let ptr = unsafe {
        device.map_memory(staging_mem, 0, buffer_size, vk::MemoryMapFlags::empty())
    }.unwrap();
    unsafe {
        std::ptr::copy_nonoverlapping(pixels.as_ptr(), ptr as *mut u8, pixels.len());
        device.unmap_memory(staging_mem);
    }

    // —— 2. 创建 device-local image ——
    let image_create = vk::ImageCreateInfo::default()
        .image_type(vk::ImageType::TYPE_2D)
        .format(vk::Format::R8G8B8A8_SRGB)                 // 贴图通常用 sRGB 编码
        .extent(vk::Extent3D { width, height, depth: 1 })
        .mip_levels(mip_levels)
        .array_layers(1)
        .samples(vk::SampleCountFlags::TYPE_1)
        .tiling(vk::ImageTiling::OPTIMAL)                  // 关键:GPU 内部最优形状
        .usage(
            vk::ImageUsageFlags::TRANSFER_DST              // 被拷贝写
                | vk::ImageUsageFlags::TRANSFER_SRC        // 若做 mip blit,也要 src
                | vk::ImageUsageFlags::SAMPLED,            // 被 shader 采样
        )
        .sharing_mode(vk::SharingMode::EXCLUSIVE)
        .initial_layout(vk::ImageLayout::UNDEFINED);       // 起点
    let image = unsafe {
        device.create_image(&image_create, None).unwrap()
    };
    let image_mem = allocator.allocate_for_image(
        image,
        vk::MemoryPropertyFlags::DEVICE_LOCAL,             // 关键:device-local
    );

    // —— 3. 一次性命令缓冲,提交给 GPU 执行拷贝 + layout 转换 ——
    let cmd = begin_one_time_command(device, command_pool);

    // Barrier 1: UNDEFINED → TRANSFER_DST_OPTIMAL
    let mut barrier = vk::ImageMemoryBarrier::default()
        .old_layout(vk::ImageLayout::UNDEFINED)
        .new_layout(vk::ImageLayout::TRANSFER_DST_OPTIMAL)
        .src_queue_family_index(vk::QUEUE_FAMILY_IGNORED)
        .dst_queue_family_index(vk::QUEUE_FAMILY_IGNORED)
        .image(image)
        .subresource_range(
            vk::ImageSubresourceRange::default()
                .aspect_mask(vk::ImageAspectFlags::COLOR)
                .base_mip_level(0)
                .level_count(mip_levels)             // 整张图一起转
                .base_array_layer(0)
                .layer_count(1),
        )
        .src_access_mask(vk::AccessFlags::NONE)       // UNDEFINED 起点没有源 access
        .dst_access_mask(vk::AccessFlags::TRANSFER_WRITE);
    unsafe {
        device.cmd_pipeline_barrier(
            cmd,
            vk::PipelineStageFlags::TOP_OF_PIPE,
            vk::PipelineStageFlags::TRANSFER,
            vk::DependencyFlags::empty(),
            &[], &[],
            std::slice::from_ref(&barrier),
        );
    }

    // —— vkCmdCopyBufferToImage:把 staging buffer 的内容拷进 image ——
    let region = vk::BufferImageCopy::default()
        .buffer_offset(0)
        .buffer_row_length(0)              // 0 表示紧密排列
        .buffer_image_height(0)
        .image_subresource(
            vk::ImageSubresourceLayers::default()
                .aspect_mask(vk::ImageAspectFlags::COLOR)
                .mip_level(0)
                .base_array_layer(0)
                .layer_count(1),
        )
        .image_offset(vk::Offset3D { x: 0, y: 0, z: 0 })
        .image_extent(vk::Extent3D { width, height, depth: 1 });
    unsafe {
        device.cmd_copy_buffer_to_image(
            cmd,
            staging_buffer,
            image,
            vk::ImageLayout::TRANSFER_DST_OPTIMAL,
            std::slice::from_ref(&region),
        );
    }

    // —— 如果有 mip,这里循环地 vkCmdBlitImage 生成 ——
    // 见 §6 的代码,这里假设 mip_levels=1 跳过

    // Barrier 3: TRANSFER_DST_OPTIMAL → SHADER_READ_ONLY_OPTIMAL
    barrier.old_layout = vk::ImageLayout::TRANSFER_DST_OPTIMAL;
    barrier.new_layout = vk::ImageLayout::SHADER_READ_ONLY_OPTIMAL;
    barrier.src_access_mask = vk::AccessFlags::TRANSFER_WRITE;
    barrier.dst_access_mask = vk::AccessFlags::SHADER_READ;
    unsafe {
        device.cmd_pipeline_barrier(
            cmd,
            vk::PipelineStageFlags::TRANSFER,
            vk::PipelineStageFlags::FRAGMENT_SHADER,
            vk::DependencyFlags::empty(),
            &[], &[],
            std::slice::from_ref(&barrier),
        );
    }

    end_one_time_command_and_submit(device, cmd, command_pool, graphics_queue);

    // —— staging buffer 可以销毁了 ——
    unsafe {
        device.destroy_buffer(staging_buffer, None);
        device.free_memory(staging_mem, None);
    }

    (image, image_mem)
}

/// 录制一个一次性命令缓冲(对应 09C-3 讲过的"一次性提交"模式)
fn begin_one_time_command(
    device: &ash::Device,
    command_pool: vk::CommandPool,
) -> vk::CommandBuffer {
    let alloc_info = vk::CommandBufferAllocateInfo::default()
        .command_pool(command_pool)
        .level(vk::CommandBufferLevel::PRIMARY)
        .command_buffer_count(1);
    let cmd = unsafe {
        device.allocate_command_buffers(&alloc_info).unwrap()[0]
    };
    let begin_info = vk::CommandBufferBeginInfo::default()
        .flags(vk::CommandBufferUsageFlags::ONE_TIME_SUBMIT);
    unsafe {
        device.begin_command_buffer(cmd, &begin_info).unwrap();
    }
    cmd
}

/// 结束 + 提交 + 等 fence + 释放命令缓冲
fn end_one_time_command_and_submit(
    device: &ash::Device,
    cmd: vk::CommandBuffer,
    command_pool: vk::CommandPool,
    queue: vk::Queue,
) {
    unsafe {
        device.end_command_buffer(cmd).unwrap();
        let fence = device
            .create_fence(&vk::FenceCreateInfo::default(), None)
            .unwrap();
        let submit_info = vk::SubmitInfo::default()
            .command_buffers(std::slice::from_ref(&cmd));
        device
            .queue_submit(queue, std::slice::from_ref(&submit_info), fence)
            .unwrap();
        device
            .wait_for_fences(std::slice::from_ref(&fence), true, u64::MAX)
            .unwrap();
        device.destroy_fence(fence, None);
        device.free_command_buffers(command_pool, std::slice::from_ref(&cmd));
    }
}
```

注意几个新手容易栽的细节。第一,`vkCmdCopyBufferToImage` 要求 image 的 layout **已经是 `TRANSFER_DST_OPTIMAL`**,所以 Barrier 1 必须先于拷贝命令,顺序反了验证层会精确报。第二,`BufferImageCopy` 里 `buffer_row_length(0)` 和 `buffer_image_height(0)` 是一个特殊的"紧密排列"约定——你 staging buffer 里像素就是一行一行紧密排的,填 0 让 Vulkan 按默认的 image extent 算行距,不要乱填别的值。第三,如果你的 image format 是 SRGB 的(贴图常用),像素字节序解释成 sRGB 编码,**采样时硬件会自动转线性**;你在 staging buffer 写入的像素值,应该是 sRGB 编码的(也就是 PNG 文件里直接存的那份)。搞混 sRGB 是经典 bug,看到"贴图过亮或过暗"就检查 format。

## 5 · Image view:image 的"窗口"

你创建了 image,但 shader 不能直接用 image——它必须通过 **image view(图像视图)** 来引用。这个抽象和 09C-2 创建 swapchain image 之后还要再建一个 image view 是同一回事:image 是底层数据,image view 是"从某种视角看这个 image"。

为什么要这一层?因为同一个 image 可以被多种方式看。比如一张 cube map image 有 6 层 array layer,你可以建一个 view 选其中某一层(当作普通 2D 贴图),也可以建一个 view 把全部 6 层当作 cube map。一张有多个 mip 的 image,你可以建一个 view 只看某一 mip level(做 debug),也可以建一个看全部 mip。view 还指定 image 的 format 怎么解释(可以做 swizzle,把通道顺序重排)。所以 view 是"image + 一个观察视角"的组合,shader 永远引用 view,不直接引用 image。

对你的纹理 image,view 创建简单:

```rust
fn create_image_view(
    device: &ash::Device,
    image: vk::Image,
    format: vk::Format,
) -> vk::ImageView {
    let create_info = vk::ImageViewCreateInfo::default()
        .image(image)
        .view_type(vk::ImageViewType::TYPE_2D)
        .format(format)
        .subresource_range(
            vk::ImageSubresourceRange::default()
                .aspect_mask(vk::ImageAspectFlags::COLOR)
                .base_mip_level(0)
                .level_count(vk::REMAINING_MIP_LEVELS)    // 涵盖所有 mip
                .base_array_layer(0)
                .layer_count(1),
        );
    unsafe {
        device.create_image_view(&create_info, None).unwrap()
    }
}
```

记住这个心智模型:image 是数据,image view 是数据的"如何被引用"——它和 swapchain image view 同构,你日后做 render pass 的 attachment 也要给 attachment 一个 image view,机制完全一样。

## 6 · Sampler:那个"怎么读"的独立对象

到这里,你的 image 数据已经在 GPU 上、shape 是 shader 友好的、view 也建好了。但 fragment shader 还不能采样它——你还需要一个 **sampler(采样器)** 对象。

sampler 这个名字有点误导,它**不存储任何像素数据**。它的职责是回答 fragment shader 每一次采样请求里的"怎么采"问题。具体说,fragment shader 会发出"我要采样坐标 的像素"的请求,这个坐标 是浮点数(通常是顶点 uv 插值过来的)。sampler 决定:如果 正好落在某个像素中心,直接读那个像素;如果落在两个像素之间(缩小时,多个像素要被合成一个;放大时,坐标落在像素之间),怎么估?如果 超出了 0..1 的范围(模型表面的 uv 可能因为展开不当跑出去了,或者你故意用 wrap 模式做平铺),怎么处理?要不要用 anisotropic filtering(各向异性滤波,看斜角时画质更好)?

sampler 通过四个核心字段回答这些问题。**minification filter(缩小滤波)和 magnification filter(放大滤波)**:当采样目标比源像素更密(缩小)或更稀(放大)时,用什么插值方法。`NEAREST`(最近邻)直接取最近的像素,快但有锯齿;`LINEAR`(双线性)取周围 4 个像素加权平均,平滑但糊。**mipmap mode**:缩小时,在 mip level 之间也做插值(`LINEAR`)或选最近的(`NEAREST`)——这控制 mip 切换是否平滑。**Address mode(寻址模式)**: 超出 0..1 怎么办。`REPEAT`(平铺,坐标 mod 1)像砖墙那样无限重复;`MIRRORED_REPEAT`(镜像平铺);`CLAMP_TO_EDGE`(钳到边缘像素)适合做 UI 边缘;`CLAMP_TO_BORDER`(钳到指定颜色)适合做 debug 边框。这三个(u、v、w 三个方向)可以分别设,但通常三个方向设成一样。**Anisotropy**:开 `max_anisotropy` 到 4 或 16,斜看时画质显著提升,代价是一些 GPU 周期。这是任何现代游戏都该开的设置。

```rust
fn create_sampler(
    device: &ash::Device,
    physical_device: vk::PhysicalDevice,
    mip_levels: u32,
) -> vk::Sampler {
    let properties = unsafe {
        device.handle().get_physical_device_properties(physical_device)
            .limits
    };
    let create_info = vk::SamplerCreateInfo::default()
        .mag_filter(vk::Filter::LINEAR)
        .min_filter(vk::Filter::LINEAR)
        .mipmap_mode(vk::SamplerMipmapMode::LINEAR)
        .address_mode_u(vk::SamplerAddressMode::REPEAT)
        .address_mode_v(vk::SamplerAddressMode::REPEAT)
        .address_mode_w(vk::SamplerAddressMode::REPEAT)
        .mip_lod_bias(0.0)
        .anisotropy_enable(true)
        .max_anisotropy(properties.max_sampler_anisotropy)   // 用硬件支持的最大值
        .compare_enable(false)
        .compare_op(vk::CompareOp::ALWAYS)
        .min_lod(0.0)
        .max_lod(mip_levels as f32)                          // 让 GPU 用到全部 mip
        .border_color(vk::BorderColor::INT_OPAQUE_BLACK)
        .unnormalized_coordinates(false);                    // 用归一化坐标(0..1)
    unsafe {
        device.create_sampler(&create_info, None).unwrap()
    }
}
```

这里我要强调 sampler 设计上最关键、最反直觉的一点:**sampler 和 image 是解耦的**。你在 09C-5 学的 descriptor 里,buffer 是一段数据,descriptor 指向它;你可能以为 sampler 也"附在 image 上",但它不是。sampler 是一个**独立的对象**,image view 也是独立对象,你只是在 descriptor 里把它们**组合**起来。这意味着同一张 image,你可以配多个 sampler——一个用 NEAREST 适合像素艺术风,一个用 LINEAR 适合写实风,一个 wrap 模式适合砖墙,一个 clamp 模式适合角色贴图——image 数据只存一份,sampler 创建几个,极轻量。这个解耦是 Vulkan(以及现代图形 API 共同的)一个核心抽象,深刻理解它,你以后做"同一张材质贴图用在不同对象上、配不同滤波策略"会非常自然。

注意 `unnormalized_coordinates(false)` 这个字段——它决定采样坐标是 0..1 的归一化(常见)还是 0..width 的像素坐标(很少用)。99% 的情况你应该用归一化坐标,因为 shader 里 uv 是归一化的,而且如果换贴图分辨率,归一化坐标不用改。

## 7 · Mipmaps:免费的质量提升,但要会生成

我前面提过 mip levels,这里把它讲完整,因为它是"花一次性的 CPU/GPU 工作换持续的性能和质量"的典型优化,任何贴图都该开。

mipmap 的核心动机:当一个物体离相机很远时,它在屏幕上只占几个像素,但它的纹理是 1024×1024 的,GPU 采样时,屏幕一个像素对应纹理上一大块区域,如果只用基础分辨率采样,GPU 会在那一大块区域里"随机"采几个像素,产生**摩尔纹(Moiré pattern)**——一种刺眼的、闪烁的高频噪声。同时,采基础分辨率意味着 GPU 每次采样都要从内存读大量没必要的像素,纹理带宽被浪费。

mipmap 的解决方案:预先把纹理逐级缩小(1024→512→256→128→64……→1),存成一系列 mip level。GPU 在采样时,根据"这个片元在屏幕上多大、对应纹理多大面积",自动选择合适的 mip level(或两个 mip 之间做三线性插值)。远处的片元用低分辨率 mip,既消除摩尔纹,又显著降低带宽(因为低 mip 在 GPU 缓存里命中率高得多)。

mip 的生成有两种方式。第一,**离线生成**:你用工具(image crate、ImageMagick)在打包阶段就生成好带 mip 的纹理文件(KTX2、DDS 格式支持),运行时直接加载。这是生产代码的做法,这一篇不展开。第二,**运行时 GPU 生成**:你只加载原始分辨率 mip 0,然后用 `vkCmdBlitImage` 命令,从 mip 0 生成 mip 1,从 mip 1 生成 mip 2……每生成一级,做一次 layout 转换。代码大致是:

```rust
// 假设 image 当前 layout 是 TRANSFER_DST_OPTIMAL,且 mip 0 已填好
// 先把 mip 0 转成 TRANSFER_SRC_OPTIMAL,因为 blit 要它当源
{
    let barrier = vk::ImageMemoryBarrier::default()
        .old_layout(vk::ImageLayout::TRANSFER_DST_OPTIMAL)
        .new_layout(vk::ImageLayout::TRANSFER_SRC_OPTIMAL)
        .src_access_mask(vk::AccessFlags::TRANSFER_WRITE)
        .dst_access_mask(vk::AccessFlags::TRANSFER_READ)
        // ... subresource_range 选 base_mip_level=0, level_count=1
        .image(image);
    // cmd_pipeline_barrier(cmd, TRANSFER, TRANSFER, ...)
}

// 循环:从 mip i 生成 mip i+1
for i in 0..(mip_levels - 1) {
    // blit:src 是 mip i,dst 是 mip i+1,各占 image 的不同 mip level
    let mut src_barrier = /* 把 mip i+1 从 UNDEFINED 转成 TRANSFER_DST_OPTIMAL */ ;
    let mut dst_barrier = /* 把 mip i 从 SRC 转成 DST... */ ;
    // ... cmd_pipeline_barrier ...
    let blit_region = vk::ImageBlit::default()
        .src_subresource(/* mip i */)
        .src_offsets([
            vk::Offset3D { x: 0, y: 0, z: 0 },
            vk::Offset3D { x: mip_width as i32, y: mip_height as i32, z: 1 },
        ])
        .dst_subresource(/* mip i+1 */)
        .dst_offsets([
            vk::Offset3D { x: 0, y: 0, z: 0 },
            vk::Offset3D { x: (mip_width / 2) as i32, y: (mip_height / 2) as i32, z: 1 },
        ]);
    unsafe {
        device.cmd_blit_image(
            cmd,
            image, vk::ImageLayout::TRANSFER_SRC_OPTIMAL,
            image, vk::ImageLayout::TRANSFER_DST_OPTIMAL,
            std::slice::from_ref(&blit_region),
            vk::Filter::LINEAR,
        );
    }
    // blit 后,把 mip i+1 从 DST 转成 SRC(下一轮它要当源)
    // ...
    mip_width = (mip_width / 2).max(1);
    mip_height = (mip_height / 2).max(1);
}

// 最后把所有 mip 一起转成 SHADER_READ_ONLY_OPTIMAL
```

我刻意省略了循环里那一组 SRC/DST barrier 的细节——这正是一个写起来繁琐、错了验证层会精确报、frame graph 会自动替你做的典型场景。你只要理解:**每个 mip level 在生成过程中,layout 在 SRC 和 DST 之间来回切换,因为它一会儿当源一会儿当目标**。生成完所有 mip,做最后一道 barrier 把整个 image(所有 mip)转成 `SHADER_READ_ONLY_OPTIMAL`。

mip 数量怎么算?从原始分辨率开始,每次除以 2 直到 1,有几个层次就有几个 mip level:1024×1024 的图,有 `floor(log2(1024)) + 1 = 11` 个 mip。`max_lod` 设成 mip 数,让 GPU 用到全部 mip。

## 8 · Combined image sampler descriptor:把 image 和 sampler 绑进 shader

你现在有了 image、image view、sampler,要把它们交给 shader 用。这正是 [09C-5](09C-5-descriptors-and-uniforms.md) descriptor set 机制的延伸。

回忆 09C-5:descriptor set 是 shader 引用外部资源的标准通道,它由若干 binding 组成,每个 binding 是一种类型的资源。09C-5 你绑的是 uniform buffer(`DescriptorType::UNIFORM_BUFFER`),这一篇你绑一个 **combined image sampler**(`DescriptorType::COMBINED_IMAGE_SAMPLER`)——这个 descriptor type 把一对(image view, sampler)作为一个单元绑定。这是 Vulkan(以及 OpenGL legacy)最常用的纹理绑定方式,因为大多数情况你确实需要"用某个采样策略读某张图"。Vulkan 也允许把 image view 和 sampler 拆成两个独立 descriptor(`SAMPLED_IMAGE` 和 `SAMPLER`),但 combined 更紧凑,先用它。

descriptor set layout 里多一个 binding:

```rust
let binding = vk::DescriptorSetLayoutBinding::default()
    .binding(1)                                              // binding 0 给 uniform buffer(09C-5),1 给纹理
    .descriptor_type(vk::DescriptorType::COMBINED_IMAGE_SAMPLER)
    .descriptor_count(1)
    .stage_flags(vk::ShaderStageFlags::FRAGMENT)            // 只在 fragment shader 用
    .immutable_samplers(None);                              // 这里也可以传一个静态 sampler
let layout_create = vk::DescriptorSetLayoutCreateInfo::default()
    .bindings(&[uniform_binding, binding]);
```

注意几个细节。第一,`stage_flags` 必须是 `FRAGMENT`——你只在 fragment shader 里采样纹理,如果填 VERTEX(罕见)或 ALL_GRAPHICS(浪费,会让 vertex shader 也能访问),不是不行,但通常 FRAGMENT 就够了。第二,Vulkan 支持一种叫 **immutable sampler(不可变采样器)** 的优化:你在 descriptor set layout 创建时就**把 sampler 句柄嵌进去**,descriptor set 用这个 layout 创建后,这个 binding 的 sampler 永远是它,不能在运行时改。这避免了某些驱动的间接开销,生产代码常用。第一个三角形先用动态 sampler(`immutable_samplers(None)`),通过 `write_descriptor_sets` 在运行时把 sampler 写进 descriptor。

写入 descriptor 的部分和 09C-5 写 uniform buffer 几乎一样,只是 descriptor info 不同:

```rust
let image_info = vk::DescriptorImageInfo::default()
    .image_layout(vk::ImageLayout::SHADER_READ_ONLY_OPTIMAL)  // 必须是 image 当前的 layout
    .image_view(texture_view)
    .sampler(texture_sampler);

let write = vk::WriteDescriptorSet::default()
    .dst_set(descriptor_set)
    .dst_binding(1)
    .dst_array_element(0)
    .descriptor_type(vk::DescriptorType::COMBINED_IMAGE_SAMPLER)
    .image_info(std::slice::from_ref(&image_info));
unsafe {
    device.update_descriptor_sets(std::slice::from_ref(&write), &[]);
}
```

这里有一个特别容易出错的点——`image_info.image_layout` **必须等于 image 在被采样时的实际 layout**。你的 image 经过 Barrier 3 已经是 `SHADER_READ_ONLY_OPTIMAL`,这里就填它。填错(比如填了 `TRANSFER_DST_OPTIMAL`),验证层会立刻报 `image layout ... doesn't match descriptor layout`,这是 texture 上手最常见的报错之一。

绑定 descriptor set 和 09C-5 完全一样——你已经在 pipeline 录制时 `cmd_bind_descriptor_sets`,把整个 set(包含 binding 0 的 uniform buffer + binding 1 的纹理)绑到 graphics pipeline,shader 就能同时看到 uniform 和纹理。

## 9 · Shader 端:GLSL 的 sampler2D

shader 那边,语法非常简单。一个 `sampler2D` 类型的 uniform(注意:它的"location"是 descriptor binding),一次 `texture()` 调用采样。

```glsl
// textured.frag
#version 450

layout(location = 0) in vec3 fragColor;
layout(location = 1) in vec2 fragUv;             // 顶点 uv 经过插值
layout(location = 0) out vec4 outColor;

layout(binding = 0) uniform UniformBufferObject {
    mat4 model;
    mat4 view;
    mat4 proj;
} ubo;

layout(binding = 1) uniform sampler2D texSampler; // 对应 descriptor set binding 1

void main() {
    vec4 texColor = texture(texSampler, fragUv);
    outColor = texColor;        // 或者 texColor * vec4(fragColor, 1.0) 做调制
}
```

注意 `binding = 1` 和 descriptor set layout 里的 binding 1 对应——这是 09C-5 讲过的 binding 索引一致原则。`texture()` 函数会自动用绑定的 sampler 配置(滤波、地址模式)对绑定的 image 在 `fragUv` 处采样,返回一个 vec4。如果你要做"顶点颜色 × 纹理颜色"的调制(modulate),就在 shader 里乘一下,这是最经典的材质混合方式。

对应的 vertex shader 要把 uv 从顶点缓冲传出来(或者像 09C-4 那样 shader 里硬编码):

```glsl
// textured.vert
#version 450

layout(location = 0) in vec2 inPosition;
layout(location = 1) in vec3 inColor;
layout(location = 2) in vec2 inUv;

layout(location = 0) out vec3 fragColor;
layout(location = 1) out vec2 fragUv;

layout(binding = 0) uniform UniformBufferObject {
    mat4 model;
    mat4 view;
    mat4 proj;
} ubo;

void main() {
    gl_Position = ubo.proj * ubo.view * ubo.model * vec4(inPosition, 0.0, 1.0);
    fragColor = inColor;
    fragUv = inUv;
}
```

到这里整条链就通了:PNG → 像素数组 → staging buffer → device-local image(三道 barrier)→ image view → sampler → combined image sampler descriptor → fragment shader `texture()` → 像素颜色。

## 10 · 在你 HH 项目里动手(做中学红线)

这一篇的动手,是把你 09C-5 的旋转三角形从纯色变成贴了图的旋转三角形。结束时屏幕上一个三角形转着、上面贴着一张你能看懂的图(木纹、Brick、卡通脸——随便你),验证层零报错。这一篇验证层报错会比较多,而且 image layout 是新手最容易出问题的领域,做好心理准备。

第一步,**准备一张 PNG 贴图**。用你 [phase-7 texture pipeline](../phase-7/deep-dives/texture-pipeline.md) 里写的 PNG 解码器,或者直接用 `image` crate(`cargo add image`),加载一张 256×256 或 512×512 的 RGBA PNG。把解码结果(一个 `Vec<u8>` 像素数组、宽度、高度)拿到手。

第二步,**写 `create_texture_image`**。参考 §4 的代码,创建 staging buffer、创建 device-local image、提交一条一次性命令缓冲执行 Barrier 1 → 拷贝 → Barrier 3(这一步先不做 mip,mip_levels=1)。这一步完整跑通,验证层应该一声不响;如果有报错,大概率是 `src_access_mask` / `dst_access_mask` 和 stage 没对上,或者 `image_subresource_range` 写错了,逐条读验证层报错对照 §3 的 stage/access 表修。

第三步,**创建 image view 和 sampler**。参考 §5、§6 的代码。sampler 开 anisotropy,max_anisotropy 用 `physical_device_properties.limits.max_sampler_anisotropy`(这是硬件支持的最大值,通常 16)。

第四步,**扩展 descriptor set layout**:在 09C-5 那个 uniform buffer binding 之外,加一个 binding=1 的 combined image sampler(§8 的代码)。`update_descriptor_sets` 写入 image_info。pipeline layout 用这个新的 layout 重建。

第五步,**改写 shader**。vertex shader 加 uv 输出(§9),fragment shader 加 `sampler2D` 和 `texture()` 调用。`glslangValidator -V` 编译成 `.spv`。顶点数据要么用顶点缓冲传 uv(09C-7 才正式做顶点缓冲,这里你可以先用 shader 硬编码 uv,比如根据顶点位置生成),要么走最简化的路——直接在 fragment shader 用 `gl_FragCoord.xy / resolution` 做 uv。

第六步,**跑,看屏幕,看验证层**。你应该看到三角形上贴着你的 PNG,随着时间旋转。验证层应该零报错。常见报错和它们的意思:报 `image layout mismatch` 大多是 image_info.image_layout 字段填错,或 barrier 漏写;报 `invalid image subresource` 是 subresource_range 算错了;报 `vkCmdCopyBufferToImage called on image with invalid layout` 是 Barrier 1 没执行或顺序错了。

第七步,**加 mip**(选做但推荐)。把 mip_levels 改成 `floor(log2(max(w, h))) + 1`,用 §7 的 blit 循环生成所有 mip。再跑,确认远处看三角形时摩尔纹消失。这一步是检验你是否真的理解 layout 转换的试金石。

验收标准:**屏幕上一个旋转三角形,贴着一张清晰可辨的 PNG,缩放和远处都不闪摩尔纹(若加了 mip),验证层零报错**。把验证层日志、屏幕截图、踩坑记录写进 commit message——image layout 是新手坑,这些记录以后你会感谢自己。

## 11 · 练习

练习一,Lv1 概念辨析。GPU 的 image 和 buffer 有什么本质区别?为什么 image 需要 layout 而 buffer 不需要?用自己的话回答:buffer 是一段连续内存,内部没有"形状"概念,GPU 怎么放就怎么读;image 是有结构的,GPU 在不同用途下(被拷贝写、被 shader 读、被 render target 写)需要不同的内部形状来对每种用途最优,layout 就是声明当前形状,用途变化时要转换。把这一点用一句话复述给你的同学听。

练习二,Lv1 概念辨析。为什么 sampler 和 image 是解耦的?因为同一张 image 可以被多种采样策略读(NEAREST / LINEAR、wrap / clamp),sampler 描述的是"怎么读",image 描述的是"读什么",分开后一份 image 可以配多个 sampler,极灵活。在你 HH 项目里,你打算用一份材质贴图配几种 sampler?写进你的 dev log。

练习三,Lv2 动手实践。完成 §10 的全部七步(第七步 mip 选做),在你的 HH 项目里画出贴了图的旋转三角形。验证层必须零报错。把屏幕截图和验证层日志贴进 commit。这是这一篇的核心交付物。

练习四,Lv3 迁移设计。在不实际写代码的前提下,你能在纸上(或脑中)回答:你 HH 渲染器里如果加载一张 cube map(天空盒),image 创建需要改哪些字段?(`array_layers=6`、view type `TYPE_CUBE`)它的 layout 转换和普通 2D 贴图有何异同?(cube map 也要 UNDEFINED → TRANSFER_DST → SHADER_READ_ONLY,但 subresource_range 要涵盖 6 个 layer,而且 view type 是 cube。)把这个设计写在 dev log 里,你日后做天空盒会用到。

练习五,Lv4 开放问题。Vulkan 还有一种 descriptor type 叫 `STORAGE_IMAGE`(storage image,shader 可读可写,常用于 compute shader 输出)。它和 `SAMPLED_IMAGE` / `COMBINED_IMAGE_SAMPLER` 的 layout 不同(`GENERAL` layout)、用法不同、性能特征也不同。研究一下,用一段文字回答:storage image 和 sampled image 在 GPU 硬件层面有什么不同?为什么 storage image 通常更慢?这个练习把你从"会用纹理"推到"理解 GPU 上 image 这一资源类的全貌",为 09D compute shader 序列做准备。

## 12 · 延伸阅读与下一篇

这一篇最权威的参考是 Vulkan spec 的 *Resource Creation* 章节(关于 image 和 sampler 的 create-info 字段全表)以及 *Image Layout* 段落(每种 layout 的精确语义)——前者告诉你字段填什么,后者告诉你 layout 转换的精确规则。最友好的实践教程是 vulkan-tutorial.com 的 "Image Creation" / "Image View and Sampler" / "Texture Image" / "Shader Combination" / "Framebuffers Revisited" 那几节,它和你这一篇走的是同一条路,可以对照读。Sascha Willems 的 Vulkan examples 仓库里 "texture" 一章有可运行的完整示例,值得收藏。

关于 staging buffer 模式的工程化,任何严肃的 GPU 资源管理库(gfx-rs 的 `gpu-allocator`、vma、AMD 的 vma)都内置了 staging allocator,处理"运行时动态上传"的复杂性,你 HH 项目里后期应该接入一个,而不是每次自己写 staging。这是从"教学级"到"生产级"必经的一步。

GPU 纹理采样的硬件原理(texture cache、mip 选择算法、各向异性滤波的实现),Real-Time Rendering 第四版的纹理一章讲得最透彻,你在 phase-6 已经过——这一篇是这些概念在 Vulkan API 上的落地。Phase-7 的 [texture pipeline](../phase-7/deep-dives/texture-pipeline.md) 讲了贴图加载、压缩、流式上传的工程实现,这一篇是它的 Vulkan 后端落地,两者可以对照读。

下一篇 [09C-7](09C-7-depth-and-meshes.md),你的渲染要处理"几何"了——目前为止你画的三角形要么是 shader 硬编码的、要么只有一个;真正引擎里你要画成百上千个三角形组成的网格。下一篇你学 **framebuffer 的多 attachment、深度缓冲(depth buffer)**、**顶点缓冲和索引缓冲的正式管理**,以及用这些把你的三角形换成一组真实的 3D 几何。image 和 sampler 这一篇已经给你了"贴图"的能力,下一篇是"几何"的能力,两者合起来,你的引擎才真正能画"东西"。
