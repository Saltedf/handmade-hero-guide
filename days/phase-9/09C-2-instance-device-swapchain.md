
# 09C-2 · 实例、设备与交换链

## 0 · 从"理解 GPU"到"让 GPU 听你的"

上一篇你建立起了对 GPU 的心智模型——SIMT、显存层次、同步、显式哲学。你明白了 Vulkan 为什么要那么繁琐。但理解不等于掌控,这一篇开始,你要亲手写 Vulkan 代码,让 GPU 真正听你的指挥。

这一篇的目标很朴素,但也很有仪式感:你要让 Vulkan 接管一个窗口。结束时,屏幕上还画不出任何东西——没有三角形,没有像素,只是一个被 Vulkan 接管的、可以稳定显示的窗口。但这个"什么都不画"的窗口,背后是四个 Vulkan 核心对象的创建:instance、physical device、logical device、swapchain。这四个对象,是你和 GPU 之间所有后续交流的入口,每一个都有它存在的理由。理解它们,你才真正"进入了"Vulkan 的世界。

这一篇的代码量会比之前的 module 大,因为 Vulkan 的入门"税"就是这么大——你要创建一堆对象,才能拿到一个能画东西的环境。但我会带你逐个理解每个对象为什么存在,而不是让你背一堆 API。记住上一篇的话:Vulkan 的繁琐不是难,是显式。每一个对象,我都要让你在心里给它在"GPU 这台机器"上找到一个对应的位置。

## 1 · Instance:你和 Vulkan 运行时的连接

Vulkan 程序的第一步,是创建一个 instance。instance 是什么?你可以把它理解成"你的程序和 Vulkan 整个运行时之间的连接"。在你创建 instance 之前,你的程序对 Vulkan 一无所知——它不能查询有哪些 GPU、不能创建任何资源、不能做任何事。instance 是这个世界的入口。

创建 instance 时,你要告诉 Vulkan 两件关于你的程序的事。第一,你是谁——你的应用名、版本、你用的 Vulkan 版本。这些信息主要给驱动看,帮它做兼容性判断。第二,你需要哪些层(layers)和扩展(extensions)——这是 instance 创建里最重要的部分。

层是 Vulkan 一个极其重要的设计,你必须现在就理解它,因为它会救你无数次。Vulkan 的核心 API 是"信任你"的——你违反规则,它不报错,直接给你黑屏或崩溃。这种"不检查"是为了性能(检查要开销)。但你开发时需要检查,所以 Vulkan 提供了**验证层**(validation layers)——一组可选的、你开发时加载的代码,它在你调用每个 Vulkan API 时检查"你有没有违规",违规就立刻打印详细错误。验证层让 Vulkan 从"盲飞"变成"有详尽错误提示",是 Vulkan 开发的命脉。

所以,创建 instance 时,你要做的第一件重要的事,就是启用验证层(KHRONOS_validation)。开发时永远开着它,发布时关掉(为了性能)。这一开一关,是 Vulkan 开发的基本纪律。我上一篇说过,这里再强调一次:不开验证层写 Vulkan,等于不写编译器报错写 C++,你不是在编程,你是在受刑。

扩展是你需要的额外能力。比如你要显示到窗口,你需要一个"和窗口系统交互"的扩展(VK_KHR_surface,以及平台相关的,比如 Linux 的 VK_KHR_xcb_surface 或 Wayland 的)。这些扩展是 Vulkan 和操作系统窗口系统之间的桥梁,你不加它们,Vulkan 不知道怎么把画面显示到屏幕。

在 Rust 里,我们用 `ash` crate——它是 Vulkan API 的薄封装,几乎是 Vulkan C API 的直接映射。用它创建 instance 大概长这样:

```rust
use ash::{vk, Entry, Instance};

fn create_instance(entry: &Entry) -> Instance {
    let app_info = vk::ApplicationInfo {
        api_version: vk::make_api_version(0, 1, 3, 0),  // 用 Vulkan 1.3
        ..Default::default()
    };

    // 启用验证层(开发时)
    let layer_names = [c"VK_LAYER_KHRONOS_validation".as_ptr()];
    // 启用 surface 扩展(显示到窗口)
    let ext_names = [
        c"VK_KHR_surface".as_ptr(),
        c"VK_KHR_xcb_surface".as_ptr(),  // Linux/X11;Windows 用 VK_KHR_win32_surface
    ];

    let create_info = vk::InstanceCreateInfo::default()
        .application_info(&app_info)
        .enabled_layer_names(&layer_names)
        .enabled_extension_names(&ext_names);

    unsafe { entry.create_instance(&create_info, None) }
        .expect("failed to create Vulkan instance")
}
```

你看,光是创建 instance,你就要显式声明:我用哪个 Vulkan 版本、我开哪些层、我要哪些扩展。在 OpenGL 里这些是驱动替你猜的,在 Vulkan 里你亲口说。这就是显式。

注意最后那个 `unsafe` 块——Vulkan 几乎所有调用都是 unsafe 的,因为 Rust 编译器没法验证你有没有遵守 Vulkan 的规则(那些规则是运行时的、由验证层检查的)。所以你会在 ash 里看到大量的 `unsafe`。这不是 ash 设计差,这是 Vulkan 的本质——它把安全责任交给你,验证层替你检查。在 Rust 里,这意味着 Vulkan 调用是 unsafe,你要用 `unsafe` 块明确承认"我知道我在做什么"。

## 2 · Physical device:在多个 GPU 里挑一个

创建了 instance,你就能查询机器上有哪些 GPU 了。一台机器可能有多个 GPU——比如很多笔记本有一个核显和一个独显,服务器可能有几张计算卡。你要从里面挑一个最适合做图形的。

挑选的逻辑,体现了一个重要概念:**queue family(队列家族)**。GPU 不是只有一个"做事的入口",它有几个不同类型的队列家族,分别擅长不同的事。图形队列家族能做图形渲染(它保证某些图形操作可用),计算队列家族只做通用计算,传输队列家族专门做内存拷贝。一个 GPU 上,这些家族可能有多个实例(比如两个图形队列)。

你挑 GPU 的标准,主要是"它有没有一个支持图形 + 显示的队列家族"——因为你要画图并显示到屏幕。你遍历所有 physical device,对每一个查询它的队列家族,找一个同时支持 GRAPHICS 和 PRESENT(显示到 surface)的家族。找到了,这个 GPU 就合格。如果机器上有多个合格 GPU(比如核显和独显都合格),你还可以进一步挑——比如偏好 DEVICE_LOCAL 内存大的那个(通常是独显,性能强)。很多桌面程序默认选第一个合格的,但严肃的应用会做更聪明的选择。

```rust
fn pick_physical_device(instance: &Instance, surface: &Surface) -> vk::PhysicalDevice {
    let devices = unsafe { instance.enumerate_physical_devices() }.unwrap();
    for dev in devices {
        if let Some(family) = find_graphics_present_family(instance, dev, surface) {
            return dev;  // 用第一个合格的
        }
    }
    panic!("no suitable GPU found");
}
```

这个"遍历、查询能力、挑选"的过程,是你和 GPU 打交道的一个缩影。Vulkan 不会替你猜"用哪个 GPU"——它把所有 GPU 摆出来,让你基于你的需求显式挑选。OpenGL 默认用驱动选的那个,你管不了;Vulkan 让你掌控,代价是你要写挑选逻辑。

## 3 · Logical device:你打开 GPU 的"门"

挑好了 physical device(具体的硬件),下一步是创建 logical device。这个区别一开始容易让人糊涂,我讲清楚。

physical device 是"那块硬件"——它是 GPU 这个物理存在,你能查询它的能力(多少内存、支持哪些特性),但你不能直接用它做事。logical device 是你打开这块硬件的"门"——它是你和这块 GPU 之间的、一个带状态的连接,你通过它创建所有资源、提交所有工作。为什么要分这两层?因为同一个 physical device,你可以打开多个 logical device(多个进程各开一个,或一个进程开多个),它们共享硬件但各有各的状态。这种分离让 Vulkan 能精确管理"谁在用 GPU 的什么"。

创建 logical device 时,你要指定:用哪个 physical device、你要创建哪些 queue(从哪个 queue family、创建几个)、你要开哪些设备层的扩展(比如 swapchain 扩展 VK_KHR_swapchain,你需要它来显示)、你要启用哪些特性(比如 geometry shader、tessellation,如果用的话)。

```rust
fn create_logical_device(
    instance: &Instance, physical: vk::PhysicalDevice, family: u32,
) -> (Device, vk::Queue) {
    let priorities = [1.0];  // 这个队列的优先级
    let queue_create_info = vk::DeviceQueueCreateInfo::default()
        .queue_family_index(family)
        .queue_priorities(&priorities);

    let extensions = [c"VK_KHR_swapchain".as_ptr()];
    let create_info = vk::DeviceCreateInfo::default()
        .queue_create_infos(std::slice::from_ref(&queue_create_info))
        .enabled_extension_names(&extensions);

    let device = unsafe { instance.create_device(physical, &create_info, None) }.unwrap();
    let queue = unsafe { device.get_device_queue(family, 0) };
    (device, queue)
}
```

那个 queue 优先级是个细节,但值得注意——Vulkan 让你给队列设优先级,告诉驱动"这个队列的工作更重要,调度时优先"。这在多队列场景(比如同时有图形队列和传输队列)有用。又是显式控制。

logical device 是你后续一切 Vulkan 操作的"基地"。你创建的所有 buffer、image、pipeline、command buffer,都是从 logical device 上创建的。它就是那扇门,你进门之后,才能用 GPU。

## 4 · Swapchain:GPU 画的东西怎么上屏

instance、physical device、logical device 这三个建好了,你有了一个能和 GPU 对话的通道。但你还没法显示任何东西——GPU 能渲染,但渲染到哪里?渲染结果怎么到屏幕?这就是 swapchain(交换链)解决的问题。

显示器刷新是有节奏的——比如每 1/60 秒刷新一次。你的游戏渲染速度可能和刷新率不同步——你可能渲染得更快、更慢、或波动。如果直接把"GPU 正在画的那个缓冲"显示到屏幕,会出现撕裂(tearing)——屏幕上半部分是新帧、下半部分是旧帧,因为屏幕读到一半时 GPU 换帧了。

swapchain 解决这个问题,靠的是"用多个缓冲、交替使用"。它维护一组 image(通常是 2 到 3 个),GPU 往其中一个画(这个叫"当前渲染目标"),显示器显示另一个(这个叫"当前显示"),两者不同,互不干扰。GPU 画完一帧,告诉 swapchain"这一帧好了",swapchain 把它和显示的那个交换(所以叫交换链),显示器下次刷新就显示新帧。这种"画一个、显示一个、交换"的机制,既避免了撕裂,又让 GPU 和显示器各自按自己的节奏工作。

创建 swapchain 时,你要做几个决策。第一,用几个 image。两个(双缓冲)是最小可用,三个(三缓冲)让 GPU 有更多余量、更不容易卡,但多占显存。第二,用什么呈现模式(present mode)。FIFO(先入先出)是 vsync 模式,稳定无撕裂但可能增加延迟;IMMEDIATE 是不等 vsync 立即呈现,延迟低但可能撕裂;MAILBOX 是两者的折中(三缓冲 + vsync,低延迟无撕裂,但不是所有平台支持)。这些选择影响游戏的延迟和流畅度,是 9B-1 讲的"帧节奏"在 GPU 层面的延续。第三,图像格式(颜色空间、像素格式)和分辨率。

```rust
fn create_swapchain(/* ... 物理设备、surface、队列家族 ... */) -> (vk::SwapchainKHR, Vec<vk::Image>) {
    let create_info = vk::SwapchainCreateInfoKHR::default()
        .image_array_layers(1)
        .image_usage(vk::ImageUsageFlags::COLOR_ATTACHMENT)
        .image_sharing_mode(vk::SharingMode::EXCLUSIVE)
        .pre_transform(vk::SurfaceTransformFlagsKHR::IDENTITY)
        .composite_alpha(vk::CompositeAlphaFlagsKHR::OPAQUE)
        .present_mode(vk::PresentModeKHR::FIFO)   // vsync
        .clipped(true)
        .image_color_space(vk::ColorSpaceKHR::SRGB_NONLINEAR)
        .image_format(vk::Format::B8G8R8A8_SRGB)
        .min_image_count(2)                        // 双缓冲
        /* ... surface、extent、queue indices ... */;

    let swapchain = unsafe { swapchain_loader.create_swapchain(&create_info, None) }.unwrap();
    let images = unsafe { swapchain_loader.get_swapchain_images(swapchain) }.unwrap();
    (swapchain, images)
}
```

你看,光是一个 swapchain,你要决定:几个缓冲、什么呈现模式、什么颜色格式、什么分辨率、要不要裁剪窗口外的像素……每一个都是显式决策。OpenGL 把这些藏进驱动,你管不了;Vulkan 让你逐个定。这种控制力,让你能针对你的游戏(竞速要低延迟选 IMMEDIATE/MAILBOX,慢节奏叙事选 FIFO 省电)做最优选择。

swapchain 还引入了一个你以后会反复打交道的概念:**image 的生命周期和所有权**。swapchain 的 image 是驱动拥有、你借用的——你从 swapchain 里"获取(acquire)"一个 image 来画,画完"呈现(present)"回去。这个"获取-画-呈现"的循环,是你每一帧渲染的基本节奏。下一篇 09C-3 讲同步时,这个循环会成为核心——因为"获取"和"呈现"都涉及 CPU 和 GPU 的协调,正是同步发挥作用的地方。

## 5 · 把这一篇放到整张地图里

你可能在想,创建一堆对象,结果屏幕上啥都没有,这有什么意义。意义在于,你刚刚搭好了所有后续渲染的地基。让我把这一篇创建的对象,放到整张 Vulkan 地图里,你就明白它们的位置了。

instance 是顶层入口——它代表"你的程序在使用 Vulkan"。physical device 是"你选了哪块 GPU"。logical device 是"你打开了这块 GPU 的门,可以用了"。queue 是"你通过这个通道给 GPU 提交工作"。swapchain 是"GPU 画的东西显示到屏幕的机制"。这五个对象,是任何 Vulkan 图形程序都要先建好的基础设施。建好之后,你才能进入"实际渲染"——下一篇开始,你会创建 command buffer(把工作打包提交给 queue)、pipeline(告诉 GPU 怎么渲染)、同步原语(协调 CPU/GPU),最终在 09C-4 画出三角形。

我特别想让你注意到一件事:这一篇创建的每个对象,你在 9B-3 的 frame graph 里都会再遇到。frame graph 内部,正是用这些对象来组织渲染——它知道 swapchain 的 image 是最终输出,它管理各种 transient image 的生命周期,它在你声明的 pass 之间协调对这些对象的访问。所以你现在忍受的这些繁琐的对象创建,是 frame graph 之所以能帮你自动管理的基础——它自动化的,正是你现在手动的这些。短期手动,长期(通过 frame graph)自动,这就是 Vulkan 的工程节奏。

## 6 · 把这一篇用到你的 HH 项目上

这一篇的做中学,是给你 HH 项目加一个"Vulkan 后端"的骨架。我建议你做成一个和现有 OpenGL 后端并存的、独立的模块,这样你既有 fallback,又能渐进迁移。

第一步,加 ash 依赖。在你的 Cargo.toml 里加 `ash`(Vulkan 绑定)、`ash-window`(和 winit 窗口集成)、`raw-window-handle`(跨平台窗口句柄)。这些是 Rust 生态写 Vulkan 的标准组合。

第二步,创建 instance,开验证层。这一步你一定要确认验证层真的开了——故意写一个违规调用(比如用一个不存在的扩展名),确认验证层打印了红色错误。如果没打印,你的验证层没生效,后面你会盲飞。这一步的验证比写代码本身重要。

第三步,枚举 physical device,挑一个,打印它的属性(名字、内存大小、队列家族)。看看 `vulkaninfo` 的输出和你的代码查询的结果对不对得上。这一步让你确认"你确实在和正确的 GPU 对话"。

第四步,创建 logical device 和 queue。把 queue 句柄存好,后面所有工作都通过它提交。

第五步,创建 surface(连接到你的 winit 窗口)和 swapchain。给 swapchain 的 image 各创建一个 image view(这是 Vulkan 里"怎么看这个 image"的句柄,09C-4 会用到)。

做完这五步,你跑程序,应该看到一个黑色的、由 Vulkan 接管的窗口。它什么都没画,但它稳定地存在,不崩溃,验证层不报错。这就是这一篇的成功标准。截图,提交 commit——这是你 Vulkan 后端的第一个脚印。

这一步你大概率会踩几个坑。验证层会报一些错(比如某个创建信息的字段没填对),逐个修——这些错误信息是金子,它们精确告诉你哪里违规。swapchain 可能因为 surface 大小为 0(窗口还没真正显示)而创建失败,你需要处理"窗口最小化时 swapchain 重建"这种边界情况。这些坑,正是 Vulkan "显式" 的代价,踩过一次你就长记性了。

## 7 · 练习

练习一,概念辨析。physical device 和 logical device 为什么要分开?physical device 是硬件本身(可查询、不可直接用),logical device 是你和硬件的带状态连接(可创建资源、提交工作)。分开让多个 logical device 共享一个 physical device 成为可能(多进程、多上下文),也让你能精确控制"启用硬件的哪些特性"。

练习二,概念辨析。swapchain 的 FIFO、IMMEDIATE、MAILBOX 三种呈现模式,分别适合什么场景?FIFO(vsync)适合慢节奏、省电、无撕裂要求的(叙事游戏);IMMEDIATE 适合追求最低延迟、不在乎撕裂的(某些竞技);MAILBOX 是低延迟+无撕裂的折中,但不是所有平台支持。选择取决于你的游戏类型和目标平台。

练习三,动手实践。完成前面 §6 的五步,得到一个 Vulkan 接管的黑窗口。在 commit message 里,记录你遇到的前三个验证层错误和怎么修的——这个记录对日后(以及给后来人)极其宝贵。

练习四,迁移设计。给你的引擎(9B-2 的 Renderer trait)加一个 VulkanRenderer 实现,目前它只能创建 instance/device/swapchain,还画不出东西。但这个骨架让你在 09C-3/4 能逐步往里加渲染能力,最终在 09C-8 完成迁移。把"空骨架"先搭起来,是大型重构的正确节奏——你不会等到一切就绪才动手,你先搭骨架、再填血肉。

## 8 · 延伸阅读与下一篇

这一篇涉及的所有 API 细节,Vulkan 官方 spec 是最终参考,但它庞大难读。更友好的是 vulkan-tutorial.com(有 Rust/ash 版本)和 vkguide.dev,它们用循序渐进的方式讲 Vulkan,这一篇的内容在那里有更详细的代码。对照阅读,能补全我省略的边角细节。

下一篇 [09C-3](09C-3-command-buffers-and-synchronization.md) 是整个 Vulkan 序列、甚至整个 Phase 9 最难的一篇——command buffer 和同步。你要理解 GPU 的异步执行模型,学会用 semaphore、fence、pipeline barrier 协调 CPU 和 GPU、协调 pass 之间的依赖。这一篇你会卡很久,卡住是正常的,因为它是 GPU 编程区别于 CPU 编程的核心地带。带上这一篇建立的对象地图(instance/device/queue/swapchain),下一篇你会往里填"怎么给 GPU 提交工作、怎么保证顺序"。爬过下一篇,剩下的 Vulkan(画三角形、传数据、加纹理)就是体力活了。
