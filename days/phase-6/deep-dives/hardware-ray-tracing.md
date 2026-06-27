---
phase: 6
title_en: "Hardware Ray Tracing: BVH, the RT Pipeline, Ray Query & Real-Time Denoising"
title_zh: "硬件光线追踪:BVH、RT 管线、Ray Query 与实时降噪"
type: deep-dive
difficulty: 5
duration: "3-4 小时"
domains: [graphics, gpu, engineering]
prereqs:
  - "phase-6/deep-dives/pbr-complete"
  - "phase-6/deep-dives/deferred-and-clustered"
  - "phase-6/deep-dives/spatial-acceleration"
  - "phase-9/09C-1-gpu-architecture-and-explicit-api"
calibration: "DXR / Vulkan RT / Ray Query + 实时降噪(SVGF) + 混合渲染管线"
---

# 硬件光线追踪:BVH、RT 管线、Ray Query 与实时降噪

> 你在 phase-3 用 `phase-3/deep-dives/rasterization-from-scratch.md` 把三角形一个一个投影到屏幕上,在 phase-6 用 `pbr-complete.md` 让光照遵守物理。你以为图形学已经到顶了——直到你试图画一个**真实**的反射:汽车后视镜里反射出另一辆车的轮辋;一池水里能看到池底的瓷砖,水面上还能看到天空;半透明的窗帘透出窗外树叶的颜色。这些效果光栅化做不到,或者要做就要堆无数 hack(planar reflection、cube reflection probe、SSAO、SSR),而且每一个 hack 都在某个场景崩。**硬件光线追踪**(hardware ray tracing,RTX / DXR / Vulkan RT)给了你另一条路:让 GPU 沿真实光路逐像素地走,反射、折射、软阴影、全局光照一次到位。这是现代实时图形的顶端,远超 HH 项目原始光栅化所能触及的范围——但它的代价是性能,以及一套全新的心智模型。这一篇带你从"为什么光栅化做不到"开始,爬到"RT 管线的着色器怎么写"和"实时 RT 为什么离不开降噪",最后落到"在你的 HH/Vulkan 后端加一道 Ray Query 阴影"。

## 0 · 一面镜子让光栅化露馅

想象你在做一个室内场景:墙上挂着一面有框的镜子。你想让镜子真实地反射出房间里的所有物体——桌子、灯、窗外景色、人物走动。

如果你只有光栅化,你有几条路。第一条是把场景再渲染一遍,把摄像机放在镜子的"镜像位置",把结果贴到镜面上——这叫 planar reflection(平面反射)。它能用,但只对**完全平面**的镜面有效,曲面镜子做不到;而且场景多一个反射面就要多渲染一次,十面镜子就是十倍开销。第二条是预渲染一张 cubemap(立方体贴图)贴到镜面上,这叫 reflection probe(反射探测器),但 cubemap 是**静态**的——人物在镜前走过,镜子里没人;而且 cubemap 的视点是固定的,物体靠近镜面时反射会有严重的视差错误。第三条是屏幕空间反射(screen-space reflection, SSR),把已经光栅化到 G-Buffer 的可见像素当成"反射源",沿反射方向在屏幕上步进——但 SSR 只能看到**屏幕里已经有**的东西,镜面反射到屏幕外的物体(被遮挡、或干脆在视野外)就反射不到,边缘会"消失",这是 SSR 的经典瑕疵。

光栅化在反射上露馅,本质原因只有一条:**光栅化是"从三角形到像素"的正向投影**。它问"这个三角形覆盖了哪些像素",而不是"这个像素看到了什么"。它天生不知道"从一个像素出发,沿视线方向走,撞到什么"。所以光栅化算不出反射:要算反射,你得从镜面上的像素,沿反射方向走出去,看会撞到什么——这是一个**反向**过程,光栅化的正向投影模型做不了。

软阴影、折射、焦散、全局光照,全都卡在同一件事上:它们都需要"从一点出发,沿某个方向,问场景里有什么"。光栅化是流水线,一次性把所有三角形扫一遍,它没有"从一个像素反向问"的能力。

光线追踪(ray tracing)就是来补这个缺口的。它从摄像机像素出发,沿视线方向射一条光线(raycast)进场景,问"这条光线撞到的第一个三角形是什么"——这就是这一像素的颜色来源。光线遇到镜子,沿反射方向再射一条新光线;遇到玻璃,沿折射方向再射一条新光线;遇到不透明表面,就停下来着色。**每一条光线都在模拟真实光线的反向传播路径**,所以反射、折射、阴影、GI 这些"光栅化做不到"的效果,在 RT 里都是天然的副产品——光线自己就会反弹。

那为什么我们直到 2018 年(NVIDIA RTX)才在消费级 GPU 上做实时 RT?因为光线的"问场景里有什么"这件事,远比光栅化的"扫三角形"贵得多。光栅化一次 draw call 扫几百万个三角形,GPU 几毫秒搞定;而光线追踪,每像素至少一条光线,1080p 就是两百万条,每条光线都要独立地"问场景"——如果场景有百万三角形,naive 做法是每条光线测试百万次相交,总共两百万 × 百万 = 两万亿次相交测试,这是不可能实时跑的。

RT 能实时,靠的是两件事:**BVH**(把相交测试从 O(N) 降到 O(log N)),以及**GPU 上专门的 RT 硬件单元**(NVIDIA 叫它 RT Core,AMD 叫它 Ray Accelerator)。这两件事加起来,才把 RT 从离线渲染(Pixar 的 RenderMan 跑一帧要几小时)拉到实时(60 FPS)。这一篇我们就沿着这条主线讲下去:先讲清 RT 和光栅化的根本区别,然后是 BVH,然后是 RT 管线的着色器模型,然后是 Ray Query(简化版的 RT),然后是实时 RT 的命门——降噪,最后是工程上怎么把 RT 和光栅化混着用(混合管线)。

## 1 · 光线追踪 vs 光栅化:两条数学上等价、工程上相反的路

先把这两条路线的根本区别讲透,因为后面所有的设计取舍都源于这里。

光栅化做的是**正向投影(forward projection)**。你有一个三角形,顶点在世界空间 `V0, V1, V2`,你用 model/view/projection 矩阵把它变换到裁剪空间,然后 GPU 的光栅化器(rasterizer)用硬件把这个三角形在屏幕上的覆盖范围扫一遍,对覆盖到的每个像素调用 fragment shader。它的循环结构是:**对每个三角形 → 对它覆盖的每个像素**。三角形在前的先处理,后面的三角形被深度缓冲(z-buffer,见 `phase-3/deep-dives/z-buffer-and-depth-testing.md`)裁掉。这个循环结构有一个极其重要的工程优势——**所有访问同一个三角形的像素是连续的**,顶点数据、纹理坐标可以从缓存里反复读,内存访问是合并的(coalesced,见 `phase-9/09C-1-gpu-architecture-and-explicit-api.md` 的显存层次那段)。这是光栅化快的根本原因。

光线追踪做的是**反向投影(backward projection)**,也叫 ray casting(光线投射)。你有一个像素,你知道它的视线方向 `d`(从摄像机出发),你构造一条参数化光线 `r(t) = o + t·d`,其中 `o` 是视点,`t` 是沿光线方向的距离参数。然后你去问场景:"这条光线撞到的**最近的**三角形是哪个,在 `t` 多大处?" 找到之后,你才对那个交点着色。它的循环结构是:**对每个像素(光线) → 对场景里所有三角形,找最近的交点**。

注意这个循环结构发生了根本性的反转。光栅化是"对三角形 → 对像素",所以同一个三角形的像素聚在一起、缓存命中率高。光线追踪是"对像素(光线) → 对三角形",所以同一个像素的光线要遍历所有三角形,而相邻像素(相邻光线)访问的三角形**几乎完全相同**——理论上仍然有 cache locality,但 locality 模式和光栅化相反,光栅化的硬件(rasterizer)对这种 access pattern 无能为力。

数学上这两条路是等价的:光栅化说"这个三角形覆盖了这些像素",RT 说"这个像素看到了这个三角形"——是同一件事的两个方向。但工程上,光栅化因为有专门的硬件(rasterizer)做"扫三角形"这件特定的事,它对那一个操作极快,快到能让百万三角形 16 毫秒搞定。而 RT 的"对每条光线遍历所有三角形"如果用 naive 算法,O(N) per ray,N = 百万三角形,200 万光线 × 百万 = 万亿级相交测试,完全跑不动。这就是为什么实时 RT 必须依赖下一节要讲的 BVH。

再说一次,RT **比光栅化更物理**。光栅化算阴影要专门画一遍 shadow map(见 `phase-6/deep-dives/shadow-mapping.md`),把场景从光源视角再投影一次——这是一个 hack,因为真实物理里阴影不是"再投影一次"产生的,而是"光线被挡住就到不了那个像素"产生的。光栅化算反射要用 planar reflection 或 SSR,也是 hack——真实物理里反射就是"光线撞到镜面,沿反射方向继续走"。光栅化算 GI(global illumination,全局光照)要用 lightmap 预烘焙或 voxel GI,也都是 hack——真实物理里 GI 就是"光线在场景里反复反弹,直到能量耗尽"。所有这些 hack,在 RT 里都不需要,因为 RT 的光线**自然会反弹**——你只要给光线一个反弹规则(撞到镜面就反射、撞到漫反射面就随机散射、撞到玻璃就折射),反射、折射、阴影、GI 全部是从同一个底层操作(光线的相交 + 反弹)里长出来的。RT 是物理上更"正"的渲染方法,光栅化是物理上更"省"的近似方法。

这就是为什么 RT 一直被认为是图形学的"圣杯"——它从原理上就能算出所有光学效果,而光栅化要为每一个效果单独设计 hack。RT 慢,不是因为它原理不对,是因为它的原理需要太多计算。BVH 让它便宜了几个数量级,RT 专用硬件让它再便宜几个数量级,二者叠加才把它推到实时的门槛里。

## 2 · BVH:让光线相交测试从 O(N) 降到 O(log N)

naive 的光线相交是 O(N):一条光线对场景里 N 个三角形逐个做相交测试,取最近的那个。N = 百万,光栅化场景里这不可接受。**BVH(Bounding Volume Hierarchy,层次包围盒)**是 RT 的命脉,它把这个 O(N) 降到 O(log N)。

BVH 的核心想法非常简单:**先不测三角形,先测一个能"包住一堆三角形"的简单形状(通常是 AABB,axis-aligned bounding box,轴对齐包围盒)。如果光线连这个外层盒子都没穿过,那它一定不会穿过盒子里的任何一个三角形,整组三角形可以一次性排除。** 只有当光线真的穿过了外层盒子,才需要进一步看里面的子盒子,一层一层往下钻,直到钻到叶子节点,叶子节点里只有少数几个三角形(通常 1 到 4 个),这才做精确的三角形相交。

BVH 是一棵树。根节点是一个大 AABB,包住整个场景的所有几何。每个内部节点有两个子节点,每个子节点是一个更小的 AABB,包住一部分几何。叶子节点里存着真正的三角形(或三角形索引)。整棵树把场景的 N 个三角形组织成一个二叉树,深度大约 log₂(N),对百万三角形大约 20 层。

光线遍历 BVH 的算法是这样的:从根节点开始,测试光线和这个节点的 AABB 是否相交。如果不相交,直接返回(这棵子树整个排除)。如果相交,递归地对两个子节点做同样的测试。如果一个子节点是叶子,对叶子里的每个三角形做精确相交测试,记录最近的命中。这就是 BVH traversal(遍历)。

一个关键优化:**优先访问更近的子节点**。光线在 BVH 里走的时候,两个子节点的 AABB 都可能和光线相交,但光线**先**进入哪一个、**后**进入哪一个,是确定的——AABB 相交测试会给你"进入这个盒子的最近 t 值"。你按 t 值从小到大排序,先访问近的子节点。如果近的子节点里已经找到了一个命中(设命中点在 t = 5),那么远的那棵子树,只要它的 AABB 进入 t > 5,就可以**整棵剪枝**(prune)——光线在那之前就已经撞到东西了,远子树里的所有三角形都不可能是"最近的",直接扔掉。这个剪枝把 BVH 的实际遍历代价进一步压低,常常比理论 log N 还要少。

读到这里你应该有个强烈的既视感:**这不就是 phase-8 的 kd-tree 吗?** 是的。请回看 `phase-8/deep-dives/kd-tree-traversal.md` 和 `phase-6/deep-dives/spatial-acceleration.md`。kd-tree 是空间划分树(spatial subdivision),把空间沿轴对齐平面递归切分;BVH 是物体划分树(object subdivision),把物体集合递归分成两组。两者都是用"层次包围盒 + 光线查询"的同一套思想,把"对每条光线测所有物体"降到"对每条光线测树高个盒子 + 少量物体"。HH 项目在 phase-8 用 kd-tree 做"一个空间点附近有什么"的查询,本质上和 BVH 的光线遍历是同一种数据结构哲学——**用空间/物体层次把暴力遍历压成对数遍历**。差别在于 BVH 是 RT 硬件直接加速的标准结构,而 kd-tree 是 HH 在 CPU 上为软件算法实现的空间加速结构。

BVH 的构建是一次性的(场景静态时只建一次,代价不高),更新是增量的(场景里有物体动起来,需要 rebuild 或 refit)。Rebuild 是完全重建,慢但质量好;refit 是"在原有结构上重新算 AABB 边界",快但 BVH 会逐渐退化(质量下降),实践中常用 hybrid 策略——每隔几帧 refit,定期 rebuild。BVH 的"质量"用 SAH(Surface Area Heuristic,表面积启发式)衡量:节点分裂时,选让"光线遍历的期望代价"最小的那个分裂位置,这个期望代价用子节点的表面积(光线穿过它的概率)和子节点里的三角形数(代价)估算。SAH 是 BVH 构建的金标准,工业级 BVH builder(包括 GPU 上的)几乎都用 SAH 或其变种。这些细节你不需要现在就实现——Vulkan / DX12 的驱动在你提交几何数据之后,会通过 acceleration structure build pass 帮你构建 BVH——但理解 BVH 是什么、为什么是 O(log N)、为什么和 kd-tree 同源,是理解 RT 性能的关键。

## 3 · RT 管线的着色器:一套和光栅化完全不同的编程模型

讲完了 BVH,我们现在能讲 RT 怎么在 GPU 上编程了。这里有一件你需要做好心理准备的事:**RT 的着色器编程模型,和光栅化的 vertex/fragment shader 完全不一样**。不是同一套东西加了几个 API,而是另一种思路。

光栅化的 shader 是 vertex shader(每个顶点调一次)+ fragment shader(每个像素调一次),它们都是同步的、线性的——你写 `color = shade(...)`,出函数就是这一像素的颜色,完事。RT 的 shader 是**多种 shader 协同 + 递归 trace** 的模型,DXR(DirectX Raytracing)和 Vulkan RT(Vulkan 的 ray tracing 扩展)都把它分成五种 shader。

第一种,**ray generation shader(光线生成着色器,RayGen)**。这是 RT 的入口,等价于光栅化里的"每像素调一次"。RayGen 每个线程对应一个像素(或一个采样),它的工作就是:**生成一条(或几条)光线,调用 `TraceRay()` 把光线交出去**。`TraceRay()` 是 RT 的核心内置函数,它说"按这条光线去 BVH 里找交点,找到的话执行 closest-hit shader,找不到的话执行 miss shader"。一个最简单的 RayGen 长这样:算出这一像素的视线方向 `d`,调用 `TraceRay(origin, dir, ...)`,返回值是这一像素的颜色。

第二种,**closest-hit shader(最近命中着色器)**。当 `TraceRay()` 在 BVH 里找到了光线的最近交点,它就跳进 closest-hit shader。这个 shader 知道"撞到了哪个三角形、撞在世界空间的哪个点、那个点的法线是什么、那一块几何的材质是什么",它的工作是**着色**——和光栅化的 fragment shader 几乎一样,算 PBR BRDF、采样纹理、采样 IBL。但 closest-hit 比光栅化的 fragment shader 多一个能力:**它可以再次调用 `TraceRay()`**。比如要做反射,closest-hit 里再发射一条反射光线,看那条光线撞到什么,把那个结果当反射颜色加进来。这就形成了**递归**:光线打到一个表面,可以再生成新的光线,新光线又可能打到另一个表面,再生光线……DXR 允许这种递归(有最大递归深度限制,Vulkan RT 也是)。这是 RT 着色模型和光栅化最不一样的地方——fragment shader 不能"自己调自己生成新像素",closest-hit 可以。

第三种,**miss shader(未命中着色器)**。当 `TraceRay()` 在 BVH 里**找不到**任何交点(光线一直飞出场景),它就跳进 miss shader。最典型的用途:miss shader 里采样天空盒(skybox)或环境贴图,把这个方向的天空颜色作为这条光线的"返回值"。这就是为什么"光线没撞到东西"在 RT 里不报错,而是返回天空色。

第四种,**any-hit shader(任意命中着色器)**。这个 shader 在 BVH traversal 过程中,每找到一个交点(不只是最近的,是任何交点)时都可能被调用。它的主要用途是**透明度裁剪**——比如一片树叶的 alpha 测试纹理,某一点 alpha = 0,光线在这里"应该穿过",any-hit shader 就告诉 traversal "忽略这个命中,继续找下一个"。any-hit 性能危险(它会在 traversal 中途打断,可能被调用很多次),实践中能不用就不用,实在要做 alpha 测试,优先考虑在 BVH build 阶段把透明三角形单独处理。

第五种,**intersection shader(相交着色器)**。这是给"非三角形几何"用的——比如你想用隐式球面、参数化曲线、SDF(signed distance field)做光线相交,BVH 里不存三角形而是存一个自定义的"几何"对象,intersection shader 就实现"这条光线和这个自定义对象的相交算法"。最常见的用例是 ray-marched SDF(沿着光线步进 SDF 找零点)或分析球面相交。如果你只用三角形,intersection shader 不用写,驱动会帮你处理。

这五种 shader 加在一起,就是 RT 的完整编程模型。和光栅化对照:光栅化是"vertex → rasterizer → fragment"的线性流水线;RT 是"RayGen → TraceRay → (BVH traversal 调度 closest-hit / miss / any-hit)"的递归调度模型。光栅化的 pipeline 是固定的、隐式的;RT 的 pipeline 是数据驱动的、显式的。这也意味着 RT 的调试更难——一条光线的执行路径可能跨越多个 shader、跨多次递归调用,RenderDoc 和 NSight Graphics 是你的命脉。

注意一个工程现实:**RT 着色器之间的调度是有硬件支持的**。NVIDIA 的 RT Core 直接在硬件上做 BVH traversal 和三角形相交,把结果回传给 SM(Streaming Multiprocessor)执行相应的 shader。这意味着 traversal 本身不占 SM 的算力,SM 只在"真的需要调 shader"时被唤醒。AMD 的 Ray Accelerator 是类似的设计。这就是为什么 RT 比软件光追快那么多——硬件把最热的那个循环(BVH traversal)做成了专门的电路。理解这一点很重要,因为它解释了 RT 性能的一个关键特性:**BVH traversal 是"几乎免费"的,真正贵的是 closest-hit shader 被调用的次数**。每次 closest-hit 调用都是一次完整的着色计算(PBR BRDF、纹理采样、可能再递归 TraceRay),所以 RT 性能主要取决于"每帧 trace 多少条光线、每条光线反弹多少次、每次命中要做多复杂的着色"。

## 4 · Ray Query:不用全套 RT 管线的简化路径

完整 RT 管线(RayGen + closest-hit + miss + any-hit + intersection)很强大,但也很重——你得写五个 shader,RT pipeline state object 也复杂,调试困难。在很多场景里你其实**不需要全套 RT 管线**,你只想要一个能力:**在一个普通的 compute shader 或 fragment shader 里,问一句"这条光线在 BVH 里有没有撞到东西?"** Vulkan RT 和 DXR 都提供了这个简化路径,叫 **Ray Query(内联光线追踪,inline ray tracing)**。

Ray Query 的核心是一个内置对象(Vulkan 里叫 `rayQueryEXT`,DXR 里叫 `RayQuery`),你在普通 shader 里创建它,初始化它(传光线起点、方向、最大距离、要查的 BVH),然后调一个 `Proceed()` 函数让它走一步 BVH traversal。每调一次 `Proceed()`,要么返回 true(还在走、找到一个候选命中),要么返回 false(traversal 结束,所有候选都看过了)。在 traversal 过程中,你可以查"当前命中是不是真的命中"(对 alpha-tested 几何,在这里做透明度测试)、"当前命中的几何信息",最后从 query 里取出最近的命中结果(或确认没命中)。

Ray Query 的本质是:**把 BVH traversal 这件事,从"硬件调度 + 多 shader 协同"的隐式模型,变成"在单个 shader 里显式控制"的内联模型**。它不需要 RayGen / closest-hit / miss 这套结构,你在普通的 fragment shader 里就能用——比如你在写光栅化的 fragment shader,算完 PBR 颜色后,顺手发一条 Ray Query 到光源方向,看有没有被遮挡,有就给阴影。这就是 RT 阴影最简单的实现方式,你完全不用搭 RT 管线,只用 Ray Query 在已有的光栅化管线里加一道查询。

什么时候用完整 RT 管线,什么时候用 Ray Query?经验法则:**如果你需要光线反弹**(反射、折射、多跳 GI),用完整 RT 管线,因为递归 trace 用 RayGen + closest-hit 写最自然。如果你**只需要单次光线查询**(阴影 ray、AO ray、单次反射、单次折射),用 Ray Query,因为它的开销更低、更可控、能嵌入到现有的光栅化或 compute 管线里。现代引擎(Unreal 5、Unity HDRP、Bevy)的 RT 阴影、RT AO、RT 反射初版几乎都用 Ray Query 起步,因为简单、快、易调试;只在需要复杂光线调度(多跳、 importance sampling)时才升级到完整 RT 管线。

Ray Query 还有一个微妙但重要的优势:**它天然兼容光栅化的 G-Buffer**(见 `phase-6/deep-dives/deferred-and-clustered.md`)。你在光栅化阶段把 G-Buffer(世界坐标、法线、材质)画好,然后在第二个 pass 里用 compute shader 读 G-Buffer,对每个像素发 Ray Query——这是一个**两阶段**的工作流(光栅化出 G-Buffer → 用 G-Buffer 驱动 RT 查询),比"纯 RT 管线一镜到底"更工程友好。这也就是下一节要讲的混合管线的核心思想。

## 5 · 噪声与降噪:实时 RT 的命门

到这里你可能会想,既然 RT 这么自然、BVH 又让它便宜了、RT Core 又帮我们做了硬件加速,那我直接对每个像素发一条视线光线,光线撞到东西就反弹一两次,反射、折射、阴影、GI 一次全有了,不就实时 RT 了吗?

这个想法缺一个致命的环节:**积分**。真实世界的光照不是"一条光线",是"从半球的无数方向来的无数条光线的积分"。PBR 里 diffuse IBL 要积分整个上半球(见 `phase-6/deep-dives/pbr-complete.md` 的 §6),GI 要积分所有弹过一次以上的光路,软阴影是面积光源上每个点都发一条 shadow ray 的积分。这些积分都没有解析解,RT 用**蒙特卡洛方法**(Monte Carlo)估算——从被积的方向分布里随机采样几个方向,平均它们的贡献,作为积分的近似。但蒙特卡洛估算的代价是**方差**(variance)——也就是噪声。采样越少,噪声越大;要噪声小,采样就要多。

这就是实时 RT 的命门。你每帧只有 16 毫秒,1080p 两百万像素,假设每像素你能负担 1 条光线(1 sample per pixel,1 spp)。1 spp 的蒙特卡洛估算**噪声极大**——画面上每个像素的"光线有没有被遮挡"、"反射方向撞到什么"都只有 1 次随机采样,完全不可用。1 spp 的 RT 阴影,看上去就像满屏雪花点;1 spp 的 RT GI,看上去像满屏静电。这是为什么"实时 RT"不是靠硬件一个春天就实现的——硬件只能让你**实时地**算每像素 1 条光线,但这 1 条光线产生的噪声让画面根本不能用。

降噪(denoising)就是来解决这个问题的。实时 RT 的实际架构是:**用很少的采样(1~4 spp)生成一张噪声图,然后用降噪器从噪声里"猜"出干净的图**。猜的过程利用了几个关键事实:**真实的图像是平滑的**(相邻像素的反射、阴影、GI 大部分时候差异不大,可以互相借用信息);**图像是时序连贯的**(上一帧的这一像素,大概率也算了类似的光路,可以拿过来平均);**G-Buffer 知道每个像素的几何和材质**(知道哪些像素是"同一个表面",可以放心地在它们之间平均,知道哪些像素跨过物体边界,不能平均)。一个好的降噪器同时利用**空间**(spatial)和**时序**(temporal)信息,把 1 spp 的噪声图"过滤"成视觉上接近 1000 spp 的干净图。

业界最经典的实时降噪算法是 **SVGF(Spatio-Temporal Variance-Guided Filtering,时空方差引导滤波,SIGGRAPH 2017)**。它的核心思路:**先用时序累积**(把过去 30 帧的 1 spp 累积成 30 spp,但要用运动矢量 motion vector 找到上一帧对应像素,避开"过去那帧已经是别的东西"的问题);**然后用空间滤波**在累积图上去掉剩余噪声,但空间滤波的强度要"按内容自适应"——平坦区域可以大刀阔斧地模糊,边缘和高频区域要小心保留。SVGF 用**方差**(variance)指导这个自适应:方差大的地方说明"信号确实有波动"(可能是真细节,要保留),方差小的地方说明"信号本来就平稳,只是采样噪声"(可以狠狠模糊)。SVGF 还用 G-Buffer 的世界坐标和法线做"edge-stopping"——只在同一个表面(法线一致、深度连续)内做空间平均,跨表面的不平均,这样不会把阴影模糊到不该有阴影的地方。

SVGF 是基础,后续工作(ReLAX、A-SVGF、signals-from-G-Buffer 路线)在它上面优化。NVIDIA 和 AMD 都在自家驱动里内置了基于深度学习的降噪器,进一步利用神经网络的先验做更好的去噪。但无论用什么算法,**降噪器的本质都是"用各种约束从噪声里反推干净信号"**,这个反推永远是 lossy 的——细节可能被模糊掉、快速移动的场景可能 ghosting(上一帧的残影没擦干净)、极暗或极亮区域可能 vignette(色调被压缩)。所以**实时 RT 不是"真实的物理",是"近真实的物理 + 聪明的降噪"**,这是工程现实,不是技术债——所有人都接受这个权衡,因为没人能跑得起 1000 spp 的实时 RT。

理解了降噪的命门地位,你就理解了一个反直觉的事实:**降低 RT 画质 ≠ 减少 spp**。减少 spp 只会让降噪器更挣扎,最终画质可能更差。更好的策略是**用更聪明的采样**(importance sampling,优先采样贡献大的方向)、**用更聪明的降噪**(更强的约束、更好的时序一致性)、**用更聪明的光线**——比如 ReSTIR(Spatiotemporal Reservoir Resampling,时空蓄水池重采样)这种现代 GI 算法,它的核心贡献不是"算更准的光路",而是"在像素之间、帧之间聪明地复用稀疏采样",让 1 spp 的输入能做到接近 64 spp 的视觉质量。这是实时 RT 的最前沿,在 `phase-6/deep-dives/gpu-compute-fundamentals.md` 里有相关铺垫。

## 6 · 混合渲染管线:用 RT 补光栅化的短板

讲完上面所有概念,现在能讲工业实际怎么用 RT 了——一个反直觉的事实:**没有任何现代引擎把整帧画面用 RT 渲染**(至少目前没有)。即便你 GPU 是顶配 RTX 4090,你也绝不会"每个像素都发视线光线 + 一次反射光线 + 一次 GI 光线 + 一次阴影光线"地纯 RT 渲染。原因很简单:**太贵了**。光栅化在"对三角形扫像素"这件事上比 RT 快几十倍,你为什么要用更慢的 RT 去做光栅化已经做得很好的事?

现代实时 RT 的实际架构是 **混合渲染管线(hybrid rendering pipeline)**:**用光栅化把 G-Buffer 渲染出来,然后用 RT 选择性地补光栅化做不好的部分**。光栅化能做的——直接光照、可见性、深度、法线、材质——交给光栅化,它快、它成熟、它的工具链最完整。光栅化做不好的——反射、软阴影、GI——交给 RT,但要节制地用,只对"画面上视觉收益最高"的部分发 RT 光线。

具体怎么分工?一个典型的现代混合 RT 渲染器长这样。第一步,**光栅化 G-Buffer pass**——和 `phase-6/deep-dives/deferred-and-clustered.md` 里讲的延迟渲染完全一样,把世界坐标、法线、反照率、roughness、metallic 写到 G-Buffer 里。第二步,**RT shadow pass**——一个 compute shader 读 G-Buffer,对每个像素从世界坐标朝光源方向发一条 Ray Query,看是否被 BVH 中的几何遮挡,产生一张阴影 mask。这一步用 RT 的好处是:它能算出**精准**的软阴影——对面积光源,在光源表面上采样若干点发若干条 ray,自动产生软阴影半影区,不需要 PCF 或 CSM 这些光栅化的阴影 hack。第三步,**RT reflection pass**——对 G-Buffer 里 roughness 低(镜面性强)的像素,从世界坐标沿反射方向发 Ray Query,撞到的几何用 G-Buffer(或一个简单的着色近似)返回颜色,产生反射图。roughness 高的像素跳过——它们不需要精确反射,IBL 已经够了。第四步,**RT GI pass**——这一步最复杂,算法选项很多(DDGI + RT、ReSTIR GI、Photon Mapping),核心都是"从 G-Buffer 的像素发若干条 GI ray,反弹一次,把反弹点的辐照度累积回来,形成 GI 图"。GI ray 数量受预算限制,通常 1~2 spp,然后强烈依赖降噪。

这一套架构的核心洞见是 **"RT 不是替代光栅化,是补光栅化"**。每加一个 RT pass,你都要回答一个问题:**这个 pass 解决的视觉效果,光栅化当前是怎么做的?RT 替换它的视觉收益有多大?性能开销值不值?** 如果光栅化的 SSR 在某个场景已经够用,你就不上 RT 反射;如果光栅化的 CSM 在大场景里阴影品质不够,你就上 RT 阴影。这种"按需引入 RT"的工程哲学,是 Unreal 5 Lumen、Unity HDRP、Godot 4 SDFGI+RT 这些工业方案共同的设计。

关于 GI 这块,有一个值得对比的细节。HH 项目在 phase-8 用了 **基于光栅化的 GI 方案**——回看 `phase-8/deep-dives/tiled-lighting.md` 和 Casey 在 HH day 570+ 里的实现。HH 的 GI 思路是"用光栅化把场景的辐照度投影到 octahedral(八面体)贴图 / 体素上,运行时采样这些预计算的数据",完全不发任何光线。这个方案的好处是**不需要 RT 硬件**——任何 GPU 都能跑,跨平台兼容性极好。代价是**精度受限**——octahedral map 的分辨率和更新频率限制了 GI 的细节和动态性,大场景的二次反弹也做不到。这是 HH 作为"教学项目"做的务实选择。而现代商业引擎(Unreal 5 Lumen、Unity HDRP)在有 RT 硬件时,会切换到 **RT GI 路线**(ReSTIR GI 或 DDGI+RT),发真实的 GI 光线,得到更准确、更动态的全局光照。两条路线的目标是一样的(全局光照),实现路径完全不同——HH 是光栅化的近似,RT GI 是物理的真实。它们是"老路"和"新路"的关系,RT 是图形学的方向,光栅化 GI 是没有 RT 硬件时的妥协。理解这个对比能帮你判断:**什么时候坚持用光栅化方案,什么时候值得上 RT**。答案永远是看目标平台——你要支持老 GPU 或移动端,光栅化 GI;你要做高端 PC/主机,RT GI。

## 7 · 生产现实:RT 不是默认开,是高端特性

讲到这里,作为一个工程师,你必须面对一个生产现实:**RT 是 gated feature(门控特性),不是默认 feature**。RT 需要 NVIDIA RTX(20 系及以上)、AMD RDNA2 及以上、Intel Arc 及以上的 GPU 才支持;老 GPU、集成显卡、移动端(手机/平板)绝大多数**没有 RT 硬件**。如果你的游戏要在 Steam 上卖,根据 Steam Hardware Survey,RT-capable 的 GPU 装机量目前大约 50-60%(2025 年),还有一半玩家跑不了 RT。

工程上的应对策略是 **design a fallback(为没有 RT 的硬件设计光栅化的降级方案)**。你的引擎要先检测 GPU 是否支持 RT(在 Vulkan 里查 device extension `VK_KHR_ray_tracing_pipeline` 或 `VK_KHR_ray_query`;在 DX12 里查 `D3D12_FEATURE_D3D12_OPTIONS5::RaytracingTier`),然后:

- **支持 RT**:走 RT 路线,跑 RT 阴影、RT 反射、RT GI。
- **不支持 RT**:走光栅化路线,跑 CSM 阴影、SSR 反射、lightmap 或 voxel GI。

这不是"两套代码"那么简单——你的引擎要在两条路径之间共享尽可能多的代码(G-Buffer 是一样的、PBR BRDF 是一样的、tone mapping 是一样的),只在"产生阴影、反射、GI 的具体算法"上分叉。这就需要 **frame graph(帧图,见 `phase-9/09B-3-frame-graph.md`)** 的帮助——frame graph 让你把渲染表达成一系列 pass 的依赖图,RT pass 和光栅化 pass 可以作为同一个 graph 的两个可选节点,根据 GPU 能力开关。frame graph 还自动帮你管理 pass 之间的同步(barrier)、临时资源的生命周期,这在"光栅化 + RT 混合"的复杂管线里是救命稻草。如果你跳过了 09B-3,在做混合 RT 之前一定要回去补——你不可能手写"光栅化 G-Buffer → RT 阴影 → RT 反射 → 降噪 → RT GI → 降噪 → 合成"这么多 pass 的 barrier,frame graph 是必经之路。

另一个生产现实是 **RT 的成本和 RT 硬件的代际强相关**。RTX 20 系(第一代 RT)的 RT 性能弱,你能跑 0.5 spp 的 RT 反射;RTX 30/40 系的 RT 性能大幅提升,你能跑 1~2 spp 的 RT 反射 + RT GI + RT 阴影。所以在做画质预算时,不能假设"RT 开了就一定好"——在低端 RT GPU 上,RT 的性能开销可能让整帧掉到 30 FPS 以下,这时候关闭 RT 反而画质更好(因为你能用节省的时间做更高的光栅化分辨率、更多的 IBL 采样)。这就是为什么工业引擎都把 RT 设置暴露给用户——它不是开关,是滑块。

## 8 · 在你 HH 项目里动手:加一道 Ray Query 阴影(做中学红线)

现在轮到你了。如果你有一块支持 RT 的 GPU(RTX 20 系及以上,或 AMD RDNA2 及以上),用你 phase-9 学到的 Vulkan 后端,给你的 HH 渲染器加一道 RT 阴影 pass。这道 pass 的目的是:**用 Ray Query 替换或对比你现有的 shadow mapping**(`phase-6/deep-dives/shadow-mapping.md`),让你亲眼看到 RT 阴影的精准性——没有 acne、没有 peter-panning、软阴影半影自动产生。

第一步,**确认你的 Vulkan 后端支持 Ray Query**。在 `phase-9/09C-8-migrate-hh-pass-to-vulkan.md` 完成的基础上,你已经在创建 Vulkan device 时拿到了 `VkPhysicalDevice`。现在你要在 device creation 时,请求 `VK_KHR_ray_query` 扩展(device extension)和 `VK_KHR_acceleration_structure` 扩展(device extension,因为 Ray Query 依赖 BVH acceleration structure)。同时,你的 Vulkan 实例需要 `VK_KHR_get_physical_device_properties2` instance extension。用 `vulkaninfo | grep -i ray_query` 检查你的 GPU 是否支持。在 Rust 里用 `ash` crate 的话,代码骨架大致是:

```rust
// 假设你已有 ash 的 Instance 和 PhysicalDevice
let ray_query_available = /* 查 device extension properties,找 "VK_KHR_ray_query" */;
let accel_struct_available = /* 查 "VK_KHR_acceleration_structure" */;

if !ray_query_available || !accel_struct_available {
    eprintln!("此 GPU 不支持 Ray Query,跳过 RT 阴影 pass,用现有 shadow map");
    return;
}

// 创建 device 时启用这两个扩展
let enabled_device_extensions = [
    // ... 你现有的扩展 ...
    vk::KhrRayQueryFn::name().as_ptr(),
    vk::KhrAccelerationStructureFn::name().as_ptr(),
    vk::KhrDeferredHostOperationsFn::name().as_ptr(),  // accel struct build 需要
    vk::KhrBufferDeviceAddressFn::name().as_ptr(),      // accel struct 需要
    vk::KhrShaderNonSemanticInfoFn::name().as_ptr(),
];
```

第二步,**构建 BVH(acceleration structure)**。Ray Query 需要一个底层 acceleration structure(bottom-level AS,BLAS),它包住你的场景几何。Vulkan 里你创建一个 `VkAccelerationStructureKHR` 对象,把你的顶点/索引 buffer 提交给一个 `vkCmdBuildAccelerationStructuresKHR` command,驱动会构建 BVH。这一步的关键是:你的几何数据要在 GPU buffer 里,buffer 要开启 `VK_BUFFER_USAGE_ACCELERATION_STRUCTURE_BUILD_INPUT_READ_ONLY_BIT_KHR` 和 device address(`vkGetBufferDeviceAddressKHR`)。BLAS 一帧里 build 一次即可,如果几何动态变化,每帧 rebuild 或 refit。

```rust
// 伪代码:构建 BLAS
let geometry = vk::AccelerationStructureGeometryKHR::builder()
    .geometry_type(vk::GeometryTypeKHR::TRIANGLES)
    .triangles(&triangles_info)  // 顶点/索引 buffer 的 device address
    .build();

let build_info = vk::AccelerationStructureBuildGeometryInfoKHR::builder()
    .ty(vk::AccelerationStructureTypeKHR::BOTTOM_LEVEL)
    .flags(vk::BuildAccelerationStructureFlagsKHR::PREFER_FAST_TRACE)
    .geometry_count(1)
    .p_geometries(&geometry)
    .build();

// scratch buffer + dst AS buffer + vkCmdBuildAccelerationStructuresKHR(...)
```

第三步,**写 Ray Query 阴影 shader**。这是一个 compute shader(或 fragment shader,看你的管线设计),输入是 G-Buffer 里的世界坐标和法线(从 `phase-6/deep-dives/deferred-and-clustered.md` 那一套 G-Buffer 读),输出是一张阴影 mask。对每个像素,从世界坐标朝光源方向发一条 Ray Query,查询 BLAS,看是否被遮挡:

```glsl
#version 460
#extension GL_EXT_ray_query : enable

layout(set = 0, binding = 0) uniform accelerationStructureEXT topLevelAS;
layout(set = 0, binding = 1) uniform sampler2D gbuffer_world_pos;
layout(set = 0, binding = 2) uniform sampler2D gbuffer_normal;
layout(set = 0, binding = 3, rgba8) uniform image2D shadow_mask;

layout(push_constant) uniform PushConstants {
    vec3 light_pos;
    float light_radius;     // 面积光源半径(用于软阴影)
    uint frame_index;       // 帧索引,用于时序累积
};

void main() {
    ivec2 px = ivec2(gl_GlobalInvocationID.xy);
    vec3 world_pos = texelFetch(gbuffer_world_pos, px, 0).rgb;
    vec3 normal    = texelFetch(gbuffer_normal, px, 0).rgb;
    if (length(normal) < 0.5) { return; }  // 空像素(天空),跳过

    // 软阴影:在面积光源上随机采样 N 个点
    const uint N_SAMPLES = 4;  // 1 spp 噪声大,这里 4 spp 起步
    float occluded = 0.0;
    for (uint i = 0; i < N_SAMPLES; ++i) {
        vec3 offset = sample_disk(light_radius, frame_index, px, i);
        vec3 to_light = (light_pos + offset) - world_pos;
        float dist = length(to_light);
        vec3 dir = to_light / dist;

        // Ray Query:从 world_pos 沿 dir 发光线,看 BLAS 里有没有东西挡着
        rayQueryEXT rq;
        rayQueryInitializeEXT(rq, topLevelAS,
            gl_RayFlagsTerminateOnFirstHitEXT,  // 阴影只要"有没有挡",最近不重要
            0xFF,                                // mask:所有几何
            world_pos + normal * 0.001,          // 沿法线偏移,避免自遮挡
            0.001,                               // t_min
            dir,
            dist - 0.01,                         // t_max:不到光源不算挡
            0.0);                                // payload(不用)

        // Proceed 走 BVH,直到结束(因为有 TerminateOnFirstHit,第一个命中就停)
        while (rayQueryProceedEXT(rq)) {
            // 可选:这里做 alpha-tested 几何的透明度判断
            // if (alpha < 0.5) { rayQueryConfirmIntersectionEXT(rq); }
        }

        if (rayQueryGetIntersectionTypeEXT(rq, true) == gl_RayQueryCommittedIntersectionNoneEXT) {
            // 没有命中:这条光线没被挡,光源可见
            // 这一个 sample 不贡献遮挡
        } else {
            occluded += 1.0;
        }
    }

    float shadow = 1.0 - occluded / float(N_SAMPLES);  // 0 全阴影,1 全亮

    // 时序累积:把当前帧的 shadow 和上一帧混合,降噪
    // (简化版,实际 SVGF 要复杂得多)
    float prev = imageLoad(shadow_mask, px).r;
    float alpha = 0.1;  // 时序权重,越大越平滑但越滞后
    float filtered = mix(prev, shadow, alpha);
    imageStore(shadow_mask, px, vec4(filtered));
}
```

这个 shader 里几个关键点要理解:`gl_RayFlagsTerminateOnFirstHitEXT` 告诉 Ray Query"找到第一个命中就停",因为阴影只需要"有没有挡",不需要"最近挡在哪",这能省一半 BVH traversal;`world_pos + normal * 0.001` 的法线偏移等价于 shadow mapping 里的 bias,避免自遮挡;`t_max = dist - 0.01` 防止光线"刚好穿过"光源所在的几何;最后的时序累积是最朴素的降噪——真正工业级要上 SVGF。

第四步,**把 RT 阴影 mask 用到光照 pass 里**。在你的延迟光照 shader 里,把"采样 shadow map 算阴影"换成"采样 RT 阴影 mask 算阴影",其他完全不变。这样你的 RT 阴影直接替换了 shadow mapping,你能立刻看到差异。

第五步,**验证正确性**。在你的 HH 项目里保留两套阴影代码——shadow mapping(已有)和 RT 阴影(新加)。用一个按键(比如你 phase-9 的 dev console CVar,见 `phase-9/09B-4-cvars-and-dev-console.md`)在两者之间切换,观察同一个场景在两种阴影下的差异。重点观察:

- **acne(阴影痘)**:shadow mapping 经常出 acne,需要调 bias;RT 阴影用法线偏移 + t_max 之后,acne 应该消失或大幅减少。
- **peter-panning(彼得潘阴影,物体和阴影脱节)**:shadow mapping 调大 bias 会出现;RT 阴影理论上没有。
- **软阴影半影**:shadow mapping 用 PCF 模糊,半影品质受分辨率限制;RT 阴影对面积光源自然产生软半影,品质更高。
- **大场景精度**:shadow mapping 受 CSM 级数限制,远处阴影品质差;RT 阴影精度一致(取决于 BVH 几何精度),远处近处一样准。

如果你的画面切换后,RT 阴影更干净、更准、半影更自然,你就成功了。

**如果你没有 RT GPU**——别担心,这一节的学习价值对你依然成立。你要做的是:**读上面这段 shader 代码,理解每一步在干什么**(RayGen 等价物、BVH 查询、TerminateOnFirstHit、法线偏移、时序累积),然后**写一段文档(注解 / README)解释:在你的 HH 项目里,如果将来在 RT GPU 上加这道 pass,会怎么改;以及当前没有 RT 时,fallback 路径(继续用 shadow mapping)的合理性**。这个练习的核心不是"必须跑通 RT",而是"理解 RT 阴影和光栅化阴影在原理上的差别",后者在两套硬件上都能学到。

## 9 · 练习

### Lv1 · 概念辨析

**题**:为什么光栅化做不出物理正确的镜面反射?SSR(screen-space reflection)是光栅化的反射方案,它的根本瑕疵是什么?

**参考解答**:光栅化的本质是"从三角形到像素"的正向投影,它问的是"这个三角形覆盖了哪些像素",天生不知道"从这个像素出发,沿视线方向走,会撞到什么"。镜面反射需要从镜面像素沿反射方向反向查询场景,这超出了光栅化的能力。SSR 的 hack 是:把已经光栅化到 G-Buffer 的可见像素当"反射源",沿反射方向在屏幕空间步进找匹配的像素。SSR 的根本瑕疵是它**只能反射屏幕里已经有的东西**——反射对象如果在屏幕外(被遮挡或在视野外),SSR 反射不到;并且 SSR 在屏幕空间步进,深度不连续处会有严重的接缝。这些瑕疵不是优化问题,是 SSR 用光栅化做反射的原理性限制。RT 反射没有这些问题,因为它真正地从镜面像素发反射光线,穿过整个场景。

### Lv2 · 动手实践

**题**:在你的 HH/Vulkan 项目里,实现第 8 节描述的 Ray Query 阴影 pass(或如果没 RT GPU,完成文档版本的练习)。完成标准:能在画面里看到 RT 阴影,且与现有 shadow mapping 切换时,RT 阴影在 acnae / peter-panning / 软阴影半影三个维度上至少有一个明显改善。

**参考解答**:照第 8 节五步走。最容易卡的是第二步 BVH build 和 shader 里的 Ray Query 调用。BVH build 卡的话,开 Vulkan validation layer(见 `phase-9/09C-1-gpu-architecture-and-explicit-api.md` 第 6 节强调过的),它会把 acceleration structure 构建的细节错误精确报出来。Ray Query 调用卡的话,用 RenderDoc 或 NSight Graphics 单步看 rayQueryProceedEXT 的返回值,确认 BVH traversal 是不是真的在走(常见错误是 rayQueryInitializeEXT 的参数错了,t_min/t_max 设反,导致光线瞬间结束)。验证标准:把场景设成"一个球在地上,一个点光源",RT 阴影应该给出球下方一个干净的圆形阴影(边缘略软,因为是面积光源采样的软阴影);shadow mapping 切过来,你应该看到至少一个 bias 引起的瑕疵(acne 或 peter-panning)。

### Lv3 · 迁移设计

**题**:RT 阴影解决了 shadow mapping 的瑕疵,但 RT 也能做**反射**。把第 8 节的 Ray Query 阴影 pass 改造成一个 **Ray Query 反射 pass**:对 G-Buffer 里 roughness < 0.3 的像素,沿反射方向发 Ray Query,把命中点的 G-Buffer 颜色作为反射色。这个 pass 和 RT 阴影 pass 在结构上有哪些相同、哪些不同?为什么反射 pass 通常只对低 roughness 像素发 RT 光线?

**提示**:结构上相似——都从 G-Buffer 读世界坐标和法线,都发 Ray Query,都查同一个 BVH。不同在于:反射需要**最近命中**(不是 TerminateOnFirstHit),因为反射要知道"反射到了什么",所以要走完整 BVH traversal 找最近交点;反射需要反弹一次(closest-hit 等价物),而阴影只问"有没有挡"。反射通常只在低 roughness 像素发 RT 的原因是:**高 roughness 的反射是模糊的、各向同性的**,IBL(prefilter environment map,见 `pbr-complete.md` §6)已经能很好近似,RT 反射的额外收益微乎其微,但 RT 开销一样;只在镜面性强的低 roughness 区域,RT 反射才能提供 IBL 给不了的"精确反射具体物体"的效果,值得那笔 RT 开销。这是混合渲染管线"RT 补光栅化短板"哲学的典型应用——按视觉收益分配 RT 预算。

### Lv4 · 开源贡献

**题**:Bevy 0.13+ 有 RT 支持(`bevy_render` 里基于 wgpu 的 ray tracing)。clone 它,找到 RT 相关代码,看它的混合渲染管线是怎么组织的:

```bash
gh repo clone bevyengine/bevy
cd bevy
grep -r "ray_query\|RayQuery\|acceleration_structure" --include="*.rs" --include="*.wgsl" -l
```

可能贡献方向:
- 文档:RT pass 在 README 或 module comment 里说明不全,补一段"什么时候用 RT,什么时候 fallback 光栅化"的工程指南。
- 测试:RT pipeline 在不同 GPU 上的兼容性测试(NVIDIA / AMD / Intel 行为差异)。
- Bug:GitHub 上找 `ray tracing` / `ray query` label 的未解决 issue,常有一些边角 case(BVH 在动态几何上的 refit 问题、Ray Query 在某些 driver 上的精度问题)。
- 性能:用 `cargo flamegraph` 或 RenderDoc 抓 Bevy 的 RT pass,看 BVH traversal / shader 执行的占比,可能能找到优化点。

**示例 PR 方向**(不要照抄):"docs: explain when Bevy's RT pipeline falls back to rasterization, and which features are gated",目标是让用户在不读源码的情况下,知道他的 GPU 能跑哪些 RT 特性。

## 10 · 延伸阅读

本仓库本地(强烈建议按顺序读):

- `days/phase-6/deep-dives/pbr-complete.md` —— PBR 的物理基础,BRDF 和 IBL。RT 的 closest-hit shader 着色逻辑就是 PBR,你必须先理解 PBR 才能写好 RT shader。
- `days/phase-6/deep-dives/deferred-and-clustered.md` —— G-Buffer 和延迟渲染。混合 RT 管线的第一步就是光栅化 G-Buffer,这一篇是它的基础。
- `days/phase-6/deep-dives/spatial-acceleration.md` —— 空间加速结构概览。BVH 是其中之一,这一篇给了空间加速的通用哲学。
- `days/phase-8/deep-dives/kd-tree-traversal.md` —— HH 项目的 kd-tree,和 BVH 同源(都是层次包围 + 查询)。强烈对比阅读,理解"为什么是同一种思想"。
- `days/phase-8/deep-dives/tiled-lighting.md` —— HH 的光栅化 GI 方案,作为 RT GI 的对比。
- `days/phase-9/09C-1-gpu-architecture-and-explicit-api.md` —— GPU 架构和 SIMT,理解 RT Core 在 GPU 上的位置。
- `days/phase-9/09C-6-textures-and-samplers.md` —— 纹理和采样器,G-Buffer 在 GPU 上的布局基础。
- `days/phase-3/deep-dives/rasterization-from-scratch.md` —— 从零写光栅化,理解 RT 想要取代/补充的那条正向投影流水线。

外部稳定 URL(长期有效):

- DXR(DirectX Raytracing)官方 spec:https://microsoft.github.io/DirectX-Specs/d3d/Raytracing.html
- Vulkan Ray Tracing 教程(Vulkan Tutorial):https://docs.vulkan.org/tutorial/latest/30_ray_tracing/00_base_code.html
- NVidia DXR Tutorial(入门经典):https://developer.nvidia.com/rtx/raytracing/dxr/DX12-Raytracing-tutorial-Part-1
- Scratchapixel Ray Tracing 章节:https://www.scratchapixel.com/lessons/3d-basic-rendering/introduction-to-ray-tracing
- PBRT(Physically Based Rendering)在线书第 4 章(Primitives and Intersection Acceleration),BVH 的圣经:https://www.pbr-book.org/4ed/Geometry_and_Transformation/Bounding_Boxes
- SVGF 原论文(Spatio-Temporal Variance-Guided Filtering,SIGGRAPH 2017):https://research.nvidia.com/publication/2017-07_Spatiotemporal-Variance-Guided-Filtering
- ReSTIR 原论文(SIGGRAPH 2020):https://research.nvidia.com/publication/2020-07_RESTIR-Path-Resampling
- EA Seed 的 PICA PICA demo 技术分享(早期实时 RT GI 的工业参考):https://www.ea.com/seed/news/pica-pica-demo-real-time-ray-tracing
- NVIDIA DLRR(深度学习降噪)白皮书,理解神经降噪的方向:https://research.nvidia.com/publication/2019-06_Ray-Tracing-Denoising

真实开源源码:

- Bevy 的 RT 实现(WGSL + Rust):https://github.com/bevyengine/bevy —— 在 `crates/bevy_pbr` 和 `crates/bevy_render` 里搜 ray tracing。
- Falcor(NVIDIA 的实时 RT 研究框架,C++):https://github.com/NVIDIA/Falcor —— 学 SVGF、ReSTIR、RT GI 最完整的参考实现。
- NWShader / Quake II RTX(早期 RT demo,id Software + NVIDIA):https://github.com/NVIDIA/Q2RTX —— 把一个老光栅化游戏改成 RT 的工程范本,看你光栅化代码怎么"嫁接" RT。
