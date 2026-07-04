
# 09C-3 · 命令缓冲与同步

## 0 · 你提交了工作,GPU 却"还没开始做"

我先用一个场景,把你带到这一篇的核心问题面前。

你的游戏要渲染一帧。你在 CPU 上算好了所有数据(变换矩阵、网格、贴图),现在你要把这些"渲染指令"交给 GPU 去执行。你调了一个"提交(submit)"的 API,把工作交给了 GPU。然后,你的 CPU 代码紧接着执行下一行——你想立刻读回 GPU 刚画的结果,做点后处理。

你的程序崩了,或者读到了一堆垃圾数据。

为什么?因为那个"提交",**不是同步执行**。CPU 调了 submit 之后,不会等 GPU 做完——它立刻继续往下跑。GPU 在另一个处理器上,异步地、按自己的节奏,执行你提交的工作。当你的 CPU 代码下一行去读结果时,GPU 可能才刚刚开始、甚至还没开始,你读到的是上一次的、或者未初始化的内存。

这是 GPU 编程和 CPU 编程分道扬镳的地方,也是整个 Vulkan 序列最难的一篇。在 CPU 编程里,你执行 `y = f(x); z = g(y);`,语言保证 f 先做完、y 有值了,g 才执行。这种"顺序执行、前一步完成后一步才开始"是 CPU 编程的默认假设,你从不操心它。但一旦涉及两个独立的处理器(CPU 和 GPU),这个假设彻底失效——它们各有各的时钟、各自并行地跑,没有任何自动的"等一下"机制。你必须**显式地**告诉它们"这里要等",否则它们会各跑各的,产生数据竞争。

这一篇就是讲"怎么显式地等"的——也就是同步(synchronization)。Vulkan 提供了几种同步原语,每一种对应一类同步需求。理解它们、用对它们,是 Vulkan 编程的命脉;用错它们,你的程序要么崩溃、要么画面错误、要么性能莫名其妙跌一半,而且这些错误往往是间歇性的、不可复现的,debug 起来让人发疯。

我会带你慢慢建立这个心智模型,因为它真的需要时间。这一篇你大概率会反复读、反复卡,这是正常的——同步是 GPU 编程里最反直觉的部分,每个 Vulkan 学习者都在这里挣扎过。爬过这一篇,剩下的 Vulkan 序列就轻松多了。

## 1 · 为什么 GPU 不能像 CPU 那样"顺序执行"

要把同步讲清楚,得先讲清楚 GPU 的工作方式为什么和 CPU 这么不一样。

CPU 执行你的代码,是"一条指令接一条指令",前一条做完后一条才开始(从程序员视角看,乱序执行等优化是透明的)。你想让一段计算"等"另一段,你直接把它们写成一前一后,语言和硬件保证顺序。

GPU 的工作方式完全不同。GPU 是一个**异步的命令处理器**。你(CPU)不是一条一条地给 GPU 发指令,而是把一大批指令**录制(record)**进一个"命令缓冲(command buffer)",然后一次性**提交(submit)**给 GPU 的某个队列(queue)。GPU 收到这批命令后,放在自己的队列里,**在未来的某个时刻**,按顺序执行它们。你的 CPU 在 submit 之后立刻继续干别的事(比如准备下一帧),它不等 GPU 执行完。

这种"录制一大堆命令,批量提交,GPU 异步执行"的模式,是 GPU 高性能的来源——CPU 和 GPU 真正并行工作,CPU 录制第 N+1 帧的命令时,GPU 在执行第 N 帧。但这个模式也带来了同步问题:既然 CPU 和 GPU 在并行跑,它们怎么协调"谁先谁后"、"什么时候数据准备好了"?

这就是同步要解决的根本问题。同步不是"让 GPU 跑得对"(那是渲染逻辑的事),同步是"让 CPU 和 GPU 这两个并行跑的处理器,在需要协调的地方正确地等彼此"。

先建立这个基本图像:命令缓冲是你**录制**给 GPU 的工作清单,submit 是你把这个清单**交**给 GPU,GPU 在队列里**异步执行**。CPU submit 后不等,继续跑。这是同步问题的土壤。

## 2 · 命令缓冲:录制与执行的分离

在讲同步之前,先把命令缓冲讲透,因为它是 Vulkan 工作模型的核心,也是 9B-3 frame graph 操作的基本单元。

命令缓冲的设计,体现了一个重要的工程思想:**录制和执行分离**。你创建一个命令缓冲,调用一堆"往里录"的 API——begin、bind pipeline、set viewport、bind vertex buffer、draw、end。这些调用**不执行任何渲染**,它们只是把"将来要执行的指令"录进缓冲。录制完了,你 submit,GPU 才在未来某个时刻真正执行这些指令。

为什么要这样设计,而不是"调一个 draw 就立刻画一个"?两个原因。第一,**性能**。GPU 执行命令有固定的、不小的启动开销(状态切换、驱动通信)。如果你每画一个三角形都和 GPU 通信一次,通信开销会压垮性能。批量录制、一次提交,把通信开销摊薄到一大批命令上,GPU 高效执行。第二,**并行**。录制在 CPU 上,执行在 GPU 上,两者并行——CPU 录第 N+1 帧时,GPU 执行第 N 帧,流水线满载。

但录制和执行分离带来一个直接后果:**录制时,你不能知道执行时的状态**。你录"用顶点缓冲 A 画",但录制这一刻,A 里有没有数据、数据对不对,你不知道——因为 A 的内容可能是 GPU 在执行之前的命令时填进去的。这种"录制时不知道执行时状态"的特性,是同步复杂度的根源之一——你必须在录制时,显式声明"这些命令之间的依赖关系、资源的 state 转换",因为 GPU 执行时,只按你声明的来,不会自己推断。

Vulkan 里,命令缓冲从 command pool 创建。pool 是和某个 queue family 绑定的(图形 pool 给图形 queue 用)。你可以创建多个命令缓冲,典型的是每个 swapchain image 一个(双缓冲就两个),这样你录制第 N 帧(用命令缓冲 A)时,GPU 在执行第 N-1 帧(用命令缓冲 B),两者不冲突。

```rust
// 录制一个命令缓冲(还不会执行)
fn record_command_buffer(
    cmd: vk::CommandBuffer, pipeline: vk::Pipeline, /* ... */
) {
    unsafe {
        device.begin_command_buffer(cmd, &begin_info).unwrap();
        device.cmd_bind_pipeline(cmd, vk::PipelineBindPoint::GRAPHICS, pipeline);
        // ... 设 viewport、绑顶点缓冲、绑描述符 ...
        device.cmd_draw(cmd, 3, 1, 0, 0);  // 画 3 个顶点
        device.end_command_buffer(cmd).unwrap();
    }
}

// 提交(交给队列,GPU 未来某时刻执行)
fn submit_command_buffer(cmd: vk::CommandBuffer, queue: vk::Queue, fence: vk::Fence) {
    let submit_info = vk::SubmitInfo::default()
        .command_buffers(std::slice::from_ref(&cmd));
    unsafe {
        device.queue_submit(queue, &[submit_info], fence).unwrap();
    }
    // 注意:这里返回时,GPU 可能还没开始执行 cmd!
}
```

那个 `queue_submit` 的返回,是初学者最常误解的点——它返回了,你以为"画完了",其实 GPU 可能根本没开始。submit 只是"把命令放进了队列"。这就是为什么你需要 fence——下一节讲。

## 3 · 三种同步原语,各自管一类"等"

Vulkan 提供三种同步原语,它们的区分不在于"原理不同",而在于"用在哪里"。这是初学者最容易混的地方——我把它讲清楚,你就不会用错。

第一种是**fence(栅栏)**,它管的是 **CPU 等 GPU**。典型场景:CPU submit 了一帧的命令,然后 CPU 想知道"GPU 做完了没有,我好回收/重用那个命令缓冲"。你不能假设 submit 完就做完了——你必须在 submit 时关联一个 fence,然后 CPU 在合适的时候"等这个 fence"——等到了,说明 GPU 确实做完了,你可以安全地重用那个命令缓冲。fence 是 CPU 和 GPU 之间的桥梁,CPU 等的那个端。

第二种是 **semaphore(信号量)**,它管的是 **GPU 内部的、跨提交的顺序**。典型场景:一帧的渲染分几步——先 acquire 一个 swapchain image(这是 GPU 操作),然后渲染到这个 image(另一个提交),然后 present 这个 image(又一个操作)。这三个操作必须按顺序,而且"渲染"必须在"acquire 完成"之后开始,"present"必须在"渲染完成"之后开始。但这些都在 GPU 侧,CPU 不直接参与每个的等待——你用 semaphore 把它们串起来:acquire 关联一个 image_available semaphore,render submit 时"等"这个 semaphore 并"触发"一个 render_finished semaphore,present 时"等"render_finished。这样 GPU 内部,这三个操作被 semaphore 串成正确的顺序。semaphore 是 GPU 和 GPU 之间的桥梁(跨 submit 或跨 queue)。

第三种是 **pipeline barrier(管线屏障)**,它管的是 **同一个 command buffer 内部的、命令之间的顺序和资源状态**。典型场景:你在同一个命令缓冲里,先有一个 pass 把数据写到一个 image,后面一个 pass 要读这个 image。如果什么都不做,GPU 可能重排或提前读,读到没写完的数据。你在这两个命令之间插一个 pipeline barrier,告诉 GPU"这里要等前面写完,而且这个 image 的 state 要从'可写'转成'可读'"。barrier 是最细粒度的同步——它管命令缓冲内部的命令顺序,以及资源的 layout/memory 转换。

把这三种记住:fence 是 CPU 等 GPU,semaphore 是 GPU 等 GPU(跨 submit),barrier 是命令缓冲内部命令等命令。区分的钥匙是"谁在等谁、在哪一层"。用错层(比如该用 barrier 的地方用了 fence,或者该用 semaphore 的地方忘了),就出 bug。

## 4 · 一帧的完整循环:三种原语怎么协作

把这三种原语放到一帧的渲染循环里,你能看清它们怎么协作。这是这一篇最值得理解的部分——大多数 Vulkan 同步 bug,都是在这个循环的某个环节用错了原语。

一帧的开始,你 acquire 一个 swapchain image——向 swapchain 申请"我要往这个 image 画"。这个操作是异步的,GPU 需要时间,所以它关联一个 image_available semaphore,GPU 拿到 image 后会触发这个 semaphore。

然后你 submit 你的渲染命令缓冲。在 submit 时,你告诉 GPU:"等 image_available semaphore 被触发后再开始执行(确保 image 拿到了)",并且"执行完后触发 render_finished semaphore"。同时,你关联一个 fence,in_flight_fence——CPU 后面用它来知道这一帧 GPU 做完了。

submit 之后,CPU 立刻继续(不等 GPU)。CPU 去做 present 操作:把刚渲染好的 image 显示到屏幕。present 时,你告诉 swapchain:"等 render_finished semaphore 被触发后再 present(确保渲染完了才显示)"。

然后 CPU 进入下一帧的循环。但在重用命令缓冲之前,它必须等 fence——确保上一帧的 GPU 工作真的做完了,才能重用那个命令缓冲(否则 CPU 录新命令时,GPU 还在执行旧的,冲突)。这个等 fence,是一帧循环的"汇合点"——CPU 和 GPU 在这里重新同步。

整个循环用到了全部三种原语:image_available 和 render_finished semaphore 串联了 GPU 内部的 acquire→render→present 顺序;in_flight fence 让 CPU 知道何时能重用命令缓冲;而你命令缓冲内部,各个 pass 之间的顺序和资源转换,用 pipeline barrier 保证。一帧的同步,是三种原语各司其职的协奏。

这个循环里有两个特别容易出错的地方,我点出来。第一,你不能在 acquire 之后、submit 之前,直接碰那个 image——因为 image 还在被 acquire 操作占用。你必须用 semaphore 等它就绪。第二,fence 的等待必须发生在你重用命令缓冲之前,而不是之后——很多新手把 wait 放错位置,导致"录制覆盖了正在执行的命令缓冲",画面错乱或崩溃。

## 5 · Pipeline barrier:最难的一个,也是 frame graph 救你的那个

三种原语里,fence 和 semaphore 相对直观(它们像信号灯)。但 pipeline barrier 是最微妙、最容易出错的,值得单独深讲——而且,好消息是,9B-3 的 frame graph 最终会替你自动处理它,所以你受的苦是有限的。但你要理解它在做什么,才能信任 frame graph 替你做的。

barrier 难,因为它同时管两件相关但不同的事:顺序和资源状态转换。

顺序的部分好理解:barrier 说"前面的命令必须完成后面的才能开始"。但只保证顺序还不够——还涉及缓存。GPU 的内存访问经过多层缓存,一个 pass 写数据,数据可能还在缓存里、没到显存;下一个 pass 读,可能从显存读到旧值。barrier 在保证顺序的同时,还负责**刷新缓存**——确保前一个 pass 写的数据,真的对后一个 pass 可见。这是 barrier 的"可见性(visibility)"职责。

资源状态转换的部分更微妙。Vulkan 里,一个 image(或 buffer)有"layout"的概念——同一个 image,作为渲染目标和作为着色器纹理,它内部的像素排列、缓存策略可能不同。你在不同 pass 里用同一个 image 做不同用途,它的 layout 要转换。barrier 就是声明这种转换的地方:"这个 image,从 COLOR_ATTACHMENT_OPTIMAL layout(适合被渲染目标写)转换到 SHADER_READ_ONLY_OPTIMAL layout(适合被着色器读)"。barrier 同时做"等顺序 + 刷缓存 + 转 layout"三件事。

barrier 之所以难用对,是因为它有几十种参数组合——源 stage、目的 stage、源 access、目的 access、旧 layout、新 layout,这些组合必须精确描述你的资源在什么时候、以什么方式被用。组合错了,要么验证层报错(好的情况),要么没报错但画面错(坏的情况),要么性能暴跌(更隐蔽)。一个常见的错误是"过度同步"——用 `TOP_OF_PIPE`/`BOTTOM_OF_PIPE` 这种最保守的 stage,让 GPU 强行全停,性能掉一半。正确的 barrier,应该精确到"最小必要"的 stage 和 access,让 GPU 尽量并行。

这就是为什么 frame graph 那么值钱——9B-3 讲过,frame graph 知道每个资源在整个帧里的生命旅程,它能自动算出"每个资源在每个 pass 边界,需要什么精确的 barrier",既保证正确又最小化同步开销。你手写 barrier,在十几个 pass 的管线上,几乎不可能做到最优;frame graph 替你做到了。所以这一篇你学 barrier,主要是为了**理解**,而不是为了以后手写——理解了,你才能信任 frame graph 替你做的,也能在它出错时(画面异常)看懂问题。这是 frame graph 时代的"必要背景知识"。

## 6 · 同步的隐形 bug,和怎么对付它们

我得单独讲同步 bug 的可怕性,因为不强调它,你会低估同步的重要性,然后被坑得很惨。

同步 bug 的核心特征是:**它们不报错,而且和时序相关**。你少插一个 barrier,GPU 可能"恰好"在大多数情况下按你期望的顺序执行(因为执行时间碰巧对),你的程序看起来正常。但在某些机器、某些负载、某些时刻,GPU 的调度让顺序错了,数据竞争发生,画面闪烁或崩溃。这种 bug 在你的开发机上不复现,在玩家那里偶发,你抓不到、修不了。

唯一能系统对付这种 bug 的办法,是**两层防御**。第一层,验证层——它能抓住一部分同步违规(比如你完全忘了同步),虽然不是所有(它不模拟精确时序)。永远开着。第二层,frame graph——它从架构上消除了"手动 barrier 忘了/错了"这类错误,因为它自动生成。两层合起来,把同步 bug 从"随机爆炸"降级到"基本可控"。这也是为什么我反复强调 9B-3 是 9C 的前置——没有 frame graph,手写 Vulkan 同步是一个专家级、易错的活;有了它,你声明 pass 依赖,同步自动正确。

还有一个调试同步问题的具体技巧,值得记住。当你怀疑画面问题是同步导致的(闪烁、撕裂、随机黑块),临时在所有 pass 之间插"最保守的、全同步的 barrier",看问题是否消失。如果消失了,说明确实是某个 barrier 不够,你可以二分地缩小到具体哪个 pass。如果没消失,说明问题在别处(渲染逻辑、数据)。这种"用过度同步测试"是排查同步 bug 的标准手法——它牺牲性能换取确定性,帮你定位问题。

## 7 · 把同步用到你的 HH 项目上

这一篇的做中学,是在你 09C-2 搭好的 Vulkan 骨架上,实现"一帧的同步循环"。结束时你还画不出三角形(那要 09C-4 的 pipeline),但你能正确地 acquire、submit(空命令)、present,并且 CPU/GPU 协调无误、验证层不报错。这是画出任何东西之前的必要地基。

第一步,创建命令池和几个命令缓冲(每个 swapchain image 一个)。

第二步,创建同步原语:每个 image 一个 in_flight fence(让 CPU 知道何时能重用),还有一对 semaphore(image_available 和 render_finished)。

第三步,实现一帧的循环。循环开头,等上一帧的 fence(确保上一帧 GPU 做完)。然后 acquire 一个 swapchain image(关联 image_available semaphore)。录制对应的命令缓冲——现在还没东西画,就录一个 begin/end 之间的空命令,或者一个简单的 clear。submit 命令缓冲(等 image_available、触发 render_finished、关联 fence)。present(等 render_finished)。回到循环开头。

第四步,开验证层跑,确认没有任何同步相关的错误。这一步是关键——如果你的循环里同步用错了(比如 fence 等待位置错、semaphore 关联错),验证层大概率会报。逐个修。

第五步,跑一段时间,确认稳定——不崩溃、不闪烁、验证层持续干净。同步 bug 往往要跑一会才偶发,所以"跑稳定"是验证的一部分。

做完这五步,你就有了一个同步正确的 Vulkan 帧循环。它是 09C-4 画三角形的基础——09C-4 你只要往那个空命令缓冲里录"真正画三角形的命令",画面就出来了,因为同步已经对了。这就是为什么这一篇要先于"画东西"——同步是地基,地基不对,画什么都是错的。

## 8 · 练习

练习一,概念辨析。fence、semaphore、pipeline barrier 分别管什么?fence 管 CPU 等 GPU(跨处理器);semaphore 管 GPU 内部跨 submit 的顺序(acquire→render→present);barrier 管同一命令缓冲内命令之间的顺序 + 缓存可见性 + 资源 layout 转换。把"谁等谁、在哪一层"想清楚,你就不会用错。

练习二,概念辨析。为什么 submit 之后,CPU 不能立刻重用那个命令缓冲?因为 submit 只是"把命令放进了 GPU 队列",GPU 可能还没执行完。如果 CPU 立刻重写那个命令缓冲,会覆盖正在执行的数据。你必须用 fence 等到 GPU 确认执行完,才能重用。

练习三,动手实践。完成前面 §7 的同步循环,得到一个稳定、验证层干净的空帧循环。在 commit message 里,记录验证层报过的同步错误和你怎么修的——这些记录是日后无价的参考。

练习四,迁移设计。在你脑中(或纸上),把你 HH 渲染器的几个 pass(几何、光照、后处理)映射成"命令缓冲里的几个段",标出每个段之间需要什么 barrier(资源 layout 怎么转、什么 stage 到什么 stage)。这个练习让你为 09B-3 的 frame graph 实现做准备——frame graph 自动生成的,正是你这里手算的这些 barrier。手算一遍,你才理解 frame graph 在替你做什么。

## 9 · 延伸阅读与下一篇

Vulkan 同步是这个领域最深的主题之一,没有之一。官方 spec 的 synchronization 章节是最终参考,但极难读。更友好的是网上那篇著名的 "Yet another blog on Vulkan synchronization"(搜得到),它用大量图解把 stage、access、layout 讲透了,几乎是 Vulkan 学习者的必读。如果你想看"正确的同步长什么样",frame graph 的实现源码(比如 Bevy 的 render graph、Unreal 的 RDG)是最好的范本——它们自动生成的 barrier,每一个都是"正确且最优"的范例。

下一篇 [09C-4](09C-4-graphics-pipeline-first-triangle.md),你终于要画出那个著名的三角形了。有了这一篇正确的同步地基,09C-4 你只需要创建 graphics pipeline(告诉 GPU 怎么渲染)、写一个最小的 vertex/fragment shader、往命令缓冲里录 draw 命令——三角形就出来了。同步已经对了,剩下的就是"画什么"。那个五百行的三角形,到这里你才真正理解它每一行在做什么、为什么需要。爬过这一篇最难的同步,后面 09C-4 到 09C-8 是有成就感的应用阶段。
