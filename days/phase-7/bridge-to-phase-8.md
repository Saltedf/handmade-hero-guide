---
phase: 7
type: bridge
title: "从 Phase 7 走到 Phase 8:功能完成,该性能收官"
domains: [game, graphics, performance, rust]
prereqs: ["day436", "day575"]
---

# Bridge · 从 Phase 7 到 Phase 8

> 你刚把 Phase 7 走完。140 天。你的游戏现在有完整的资产管线(PNG 解码、glTF 加载、热重载)、有 in-game 编辑器(可以在游戏里摆物体)、有 PBR 渲染、有导航网格和 AI。从功能上说,**这是个完整的游戏了**。你心想:就差最后的优化了。然后呢?——然后就是 Phase 8:**最后的性能优化 + 收官**。这是 Handmade Hero 全程最后 92 天,Casey 把光照系统升级到无限弹射 GI、空间查询用 k-d tree 优化、碰撞系统从 Minkowski 重写为体素化。**从"功能完成"到"商业品质"**。本文是过桥指南。

## §0 · 你已经走过的路

Phase 7 的 140 天,你完成了资产管线 + 编辑器 + 工具链的完整工程化。按时间顺序复盘:

- **Day 436-462**:PNG 解码器。从 bit 流手写 DEFLATE + Huffman + Reconstruction filters。**这是 HH 全程"造轮子含量"最高的一段**——87 天从 bit 解到像素。

- **Day 463-475**:资产热重载 + 资产管线升级。文件 watcher 检测变化,游戏实时看到。资产打包格式扩展。

- **Day 476-510**:in-game 编辑器。UI、选中、移动、复制、保存 / 加载、撤销 / 重做。**这是工业级游戏开发的工作流核心**。

- **Day 511-530**:glTF 加载。JSON + binary buffer,PBR 材质映射,骨骼动画。

- **Day 531-560**:导航网格 + A* 寻路。AI 移动基础设施。

- **Day 561-575**:整理 + 反思。Phase 7 收官。

Phase 7 全程最值得记住的三件事:

**第一,理解底层比调库更值**。Phase 7 你手写 PNG 解码器,不是为了"以后不用 image crate",而是为了**理解压缩算法的内部**——这种理解让你看任何压缩格式(gzip、JPEG、视频编码)都不迷路。**Casey 在 HH 里反复强调的"程序员尊严"就是这**。

**第二,资产管线是工业级游戏开发的核心**。商业游戏不用零散文件,用打包格式(.pak / .assets / .vpk)。Phase 7 你做的 `.hha` 升级版,虽然简单但概念一致。**Unreal、Unity 的资产管线 80% 是同样的概念**——只是更复杂的实现。

**第三,in-game 编辑器是协作核心**。没有 in-game 编辑器,你做的不是游戏,是技术 demo。**程序员写引擎,策划 / 美术用编辑器**——这是工业级分工。Phase 7 你写的 in-game 编辑器虽然简单,但**架构和 Unreal / Unity 一样**——选中、属性面板、撤销 / 重做、保存 / 加载。

接下来 Phase 8 是 Day 576-667(92 天),Handmade Hero 全程最后一段。主要内容:**最后优化 + 收官**。具体四件事:

1. **八面体光照编码**:间接光存储从球谐函数(SH)切换到八面体编码,更省内存 + 更高精度。
2. **无限弹射 GI**:基于八面体辐射场,光在场景里无限次弹射,逐步收敛到物理正确状态。**这是 HH 的视觉高潮**——画面从"扁平"跃升到"有空间感"。
3. **空间查询优化**:k-d tree、walk table,每帧 25 万次光线投射跑得动。
4. **碰撞系统重写**:从 Minkowski(Phase 2)重写为体素化方案,3D 体素场景更灵活。

Phase 8 完成后,你拥有**完整的、开源的、商业品质的游戏代码库**,以及从一个非程序员到"开源黑客"的全部能力。

## §1 · 进入 Phase 8 前的能力盘点

**A. 资产管线(Phase 7 核心)**
- [ ] 你能从 bit 流手写 PNG 解码(DEFLATE + Huffman + Reconstruction filters)。
- [ ] 你能加载 glTF 模型(JSON + binary buffer,PBR 材质映射)。
- [ ] 你能实现资产热重载(文件 watcher + 实时更新)。
- [ ] 你理解资产打包格式的设计(为什么 `.pak` / `.hha` 这样设计)。

**B. in-game 编辑器**
- [ ] 你能写 in-game 编辑器的核心——选中、属性面板、保存 / 加载、撤销 / 重做。
- [ ] 你理解"数据驱动"——游戏逻辑通用,具体内容放资产。
- [ ] 你能区分"引擎"和"游戏"——引擎是通用代码,游戏是资产 + 少量胶水代码。

**C. PBR + 光照(Phase 6+7 综合)**
- [ ] 你能写 Cook-Torrance BRDF 完整实现。
- [ ] 你理解 IBL(Image-Based Lighting)。
- [ ] 你理解"球谐函数"(Spherical Harmonics,SH)——一种把"球面上的函数"用几个系数表示的方法,Phase 8 GI 早期用,后期切换到八面体编码。
- [ ] 你理解"间接光"——光从墙壁 / 地板弹射,照亮阴影区。

**D. 性能基础(Phase 4+5+6 综合)**
- [ ] 你能用 Tracy profiler 找性能瓶颈。
- [ ] 你理解 SIMD、多线程、cache 友好的内存布局。
- [ ] 你理解 GPU 性能瓶颈——draw call、状态切换、纹理带宽、shader 复杂度。
- [ ] 你理解 lock-free 数据结构(Phase 4)。

**E. 数学准备(Phase 8 关键)**
- [ ] 你理解"辐射度"(radiance)和"辐照度"(irradiance)的物理意义。
- [ ] 你理解"立体角"(solid angle)——球面上一块区域的"角度大小"。
- [ ] 你理解"蒙特卡洛积分"(Monte Carlo integration)——用随机采样近似积分。GI 算法核心。
- [ ] 你理解"k-d tree"——空间划分数据结构,光线投射加速。

**F. 心理建设**
- [ ] 你接受了"Phase 8 是最后冲刺,做完 HH 就结束"——会有毕业感 + 不舍。
- [ ] 你接受了"GI 是图形学最难的主题之一"——无限弹射 GI 涉及大量数学。
- [ ] 你接受了"HH 结束不是终点,是新起点"——之后你要自己选项目做。

## §2 · 自测题

下面 6 道题。

### 题 1(八面体编码)

什么是八面体编码(octahedral encoding)?为什么它比球谐函数(SH)更适合 GI?

**参考答案**:

**八面体编码**:把 3D 单位向量(球面上的点)映射到 2D 正方形(八面体展开图)的编码方法。

```
3D 单位向量 (x, y, z),|x|² + |y|² + |z|² = 1
↓
2D 八面体坐标 (u, v),u, v ∈ [-1, 1]
```

映射方法:
1. 把球面投影到八面体(8 个三角面组成的多面体)。
2. 把八面体展开成 2D 正方形(每个三角面贴在正方形上)。
3. 在 2D 正方形上采样。

优点:
- **存辐射度**:每个体素存一张 16x16 RGB 贴图(3KB),记录"从这个方向来的光的颜色和强度"。
- **采样高效**:一次 2D 纹理采样,比 SH 的"9 个系数点乘"快。
- **精度高**:固定分辨率,不丢细节。

对比球谐函数(SH):
- SH 存 9 个系数(每通道)→ 27 个 float = 108 字节。
- 八面体编码 16x16 RGB = 768 字节,但**精度远超 SH**。
- SH 适合"低频"光照(整体明暗),不适合"高频"光照(锐利反射)。
- 八面体编码两个都适合。

Phase 8 早期 Casey 把间接光存储从 SH 切换到八面体编码,**视觉品质大幅提升**(墙角不再"糊")。

### 题 2(无限弹射 GI)

什么是"无限弹射全局光照"(infinite-bounce GI)?为什么它比"单次弹射 GI"更好?

**参考答案**:

**全局光照(GI)**:模拟光在场景中弹射,产生间接光。**直接光**是光直接照到物体,**间接光**是光弹射后照到物体(墙壁反射的光照亮阴影区)。

**单次弹射 GI**:光从光源出发,弹一次墙壁,然后到摄像机。**计算快但效果不完整**——颜色渗透(color bleeding)只在第一层。

**无限弹射 GI**:光在场景里无限次弹射,逐步收敛到"物理正确"状态。每次弹射,光的能量按材质反射率衰减,直到能量可以忽略。

无限弹射的效果:
- **颜色渗透更深**:红墙旁的白墙,会持续接收红光(多次弹射累积)。
- **角落变亮**:阴影区的角落,直接光照不到,但间接光经过几次弹射后照亮。
- **物理正确**:结果和真实光的行为一致。

算法(简化版):
```
for each voxel V:
    radiance[V] = initial_emission(V)  # 自发光(光源)
    
for bounce in 1..∞:
    for each voxel V:
        for each direction D in 16x16 octahedral map:
            ray_from_V_in_direction_D
            if hit voxel V':
                incoming_radiance[V][D] = radiance[V']  # 从 V' 来的光
        # V 的辐射度 = 自发光 + 收集的所有入射光 × 反射率
        new_radiance[V] = emission[V] + albedo[V] * integrate_incoming(V)
    
    if converged(bounce):  # 变化小于阈值,停止
        break

render(camera): 用 radiance[V] 渲染
```

这是"光线追踪"风格的 GI,在 CPU 上跑(每帧 25 万次光线投射)。**Phase 8 中期 Casey 实现这套**。

### 题 3(k-d tree)

什么是 k-d tree?它怎么加速光线投射?

**参考答案**:

**k-d tree**:k 维二分搜索树。把空间递归地用轴对齐平面分成两半。

构造:
```
build_kdtree(triangles, depth):
    if triangles.length < threshold:
        return Leaf(triangles)
    axis = depth % 3  # X / Y / Z 轮换
    split = median(triangles.map(|t| t.center[axis]))
    left = triangles.filter(|t| t.center[axis] < split)
    right = triangles.filter(|t| t.center[axis] >= split)
    return Node(axis, split, build_kdtree(left, depth+1), build_kdtree(right, depth+1))
```

查询(光线投射):
```
ray_hit_kdtree(node, ray):
    if node is Leaf:
        for triangle in node.triangles:
            if ray_triangle_intersect(ray, triangle):
                return true
        return false
    # node 是内部节点,看光线先经过左还是右
    t_split = (node.split - ray.origin[node.axis]) / ray.direction[node.axis]
    if t_split > 0:
        # 光线先进入左子树
        if ray_hit_kdtree(node.left, ray): return true
        # 然后右子树
        if ray_hit_kdtree(node.right, ray): return true
    else:
        # 反过来
        ...
    return false
```

加速效果:暴力光线投射是 O(N)(N 是三角形数),k-d tree 是 O(log N)。

100 万三角形场景:
- 暴力:每次光线 100 万次相交测试。
- k-d tree:每次光线 ~20 次相交测试(log2(1M) ≈ 20)。

**加速 50000 倍**。

Phase 8 中后期 Casey 大量用 k-d tree,GI 的 25 万次光线投射才能跑得动。

### 题 4(体素化碰撞)

什么是体素化碰撞(Voxel-based collision)?它比 Minkowski 碰撞有什么优势?

**参考答案**:

**Minkowski 碰撞**(Phase 2 Casey 做的):两个形状的碰撞检测,通过"Minkowski 差"判断。对凸多边形效果好,但对复杂形状(凹形 / 开放表面)复杂度高。

**体素化碰撞**:把世界划分成 3D 网格(体素),每个体素标记"是固体还是空气"。碰撞检测变成"查询玩家所在体素是否固体"。

体素化碰撞的优势:
1. **O(1) 查询**:玩家在体素 `(x, y, z)`,直接查 `grid[x][y][z]`,O(1)。Minkowski 是 O(N)(N 是物体数)。
2. **任意形状**:凹形、开放表面、洞、悬挂,都用同一种方式表达。Minkowski 对凹形很麻烦。
3. **修改容易**:破坏一堵墙,把对应体素从"固体"改为"空气"。Minkowski 要重建碰撞形状。
4. **并行友好**:每个体素独立,多线程处理无锁。

体素化碰撞的劣势:
1. **内存占用**:每个体素 1 字节(或 1 bit),1km × 1km × 0.1km 地图,1cm 体素是 1TB。需要稀疏存储或 LOD。
2. **精度**:体素大小决定精度。1cm 体素对 FPS 够,对太空模拟不够。

Phase 8 后期 Casey 把 Phase 2 的 Minkowski 碰撞重写为体素化方案,**简化代码 + 加速**。Minecraft 的碰撞就是体素化(每方块是体素)。

### 题 5(蒙特卡洛积分)

什么是蒙特卡洛积分?它在 GI 里怎么用?

**参考答案**:

**蒙特卡洛积分**:用随机采样近似定积分。

```
∫ f(x) dx ≈ (1/N) * Σ f(x_i) / p(x_i)

其中 x_i 是按概率密度 p(x) 采样的随机数,N 是采样数
```

直觉:**随机选 N 个点,平均它们的函数值,就是积分的近似**。N 越大越准。

在 GI 里用:
- **计算间接光**:对每个像素,要积分"半球上所有方向来的光"——这是连续积分。
- **采样**:随机选 N 个方向,每个方向射光线,取回光照值。
- **平均**:N 个方向的光照平均,作为像素的间接光。

```glsl
// 伪 shader
vec3 indirect_light = vec3(0);
int N = 32;  // 32 个采样
for (int i = 0; i < N; i++) {
    vec3 random_dir = random_hemisphere_dir(normal);
    vec3 hit_pos = ray_cast(pos, random_dir);
    vec3 incoming = sample_radiance(hit_pos);
    indirect_light += incoming * dot(normal, random_dir);
}
indirect_light /= N;
indirect_light *= 2 * PI;  // 半球立体角
```

蒙特卡洛的特点:
- **N 小 → 噪声大**:8 个采样,画面有"颗粒"。
- **N 大 → 慢**:1024 个采样,几乎无噪声但极慢。
- **TAA 帮忙**:时间累积(每帧不同采样),TAA 平滑噪声。

工业级 GI 路径追踪器(Unreal Lumen、CryEngine SVOGI、Dice Frostbite RTGI)都用蒙特卡洛 + 时序累积。Phase 8 Casey 的实现也是。

### 题 6(Phase 7 反思)

Phase 7 收尾时,你相比 Phase 6 收尾,主要增加了什么能力?给出至少 4 条。

**参考答案**:

1. **资产管线**:从"零散文件"到"打包格式 + 热重载",启动加载快、运行时可改资产。
2. **in-game 编辑器**:能在游戏里编辑关卡、光照、物体,无需重新编译。
3. **glTF 加载**:能加载工业级 3D 模型格式,带 PBR 材质 + 骨骼动画。
4. **PNG 解码**:从 bit 流手写完整解码器,理解压缩算法底层。
5. **导航网格 + A***:AI 能在场景里寻路,绕开障碍。
6. **数据驱动**:游戏逻辑和资产分离,策划 / 美术能独立工作。
7. **工具链**:打包工具、加载工具、编辑器工具的完整链路。

## §3 · 心智切换:从"功能完成"到"性能收官"

Phase 7 的 140 天,你的心智是"**功能 + 工具链**"——PNG、glTF、in-game 编辑器、A* 寻路,你追求"功能完整"和"工作流顺"。

Phase 8 的 92 天,你的心智要切换到"**性能 + 收官**"——八面体编码、无限弹射 GI、k-d tree、体素化碰撞,你追求"跑得快"和"商业品质"。

具体 5 条切换:

**1. 从"功能正确"到"商业品质"**。
Phase 7 你的游戏功能完整,但 GI 简单(单次弹射),墙角"糊",空间感不够。
Phase 8 你写无限弹射 GI,墙角变亮、颜色渗透,**视觉品质从"独立游戏"跃升到"AAA"**。

心智切换:**最后 10% 的视觉品质,要花 50% 的工程时间**。Phase 8 就是这 50%。商业游戏和独立游戏的差距,90% 在这最后 10%。

**2. 从"O(N) 算法"到"O(log N) 数据结构"**。
Phase 7 你的 GI 是暴力射线投射,O(N),N 是三角形数。100 万三角形跑不动。
Phase 8 你用 k-d tree,O(log N),同样场景跑得动。

心智切换:**算法复杂度是性能的"天花板"**。再怎么 SIMD、再怎么多线程,O(N²) 算法在 N=1M 时是 1 万亿次操作,跑不动。**先选对数据结构,再谈优化**。

**3. 从"经验值"到"物理正确"**。
Phase 7 你的 GI 用"经验衰减"(光随距离平方衰减)。
Phase 8 你的 GI 用"物理正确"——蒙特卡洛积分,光在场景里真实弹射。

心智切换:**物理正确的渲染,看起来"自然"**。经验值在某些场景"破功",物理正确在所有场景都"对"。

**4. 从"快速迭代"到"工程纪律"**。
Phase 7 你写代码,先让它跑,反复改。
Phase 8 你的代码量大(累积了 575 天的代码),**重构成必修课**——Minkowski → 体素化碰撞是重构,SH → 八面体编码是重构。

心智切换:**重构不是"推倒重来",是"在功能不变的前提下改架构"**。Phase 8 Casey 多次重构,每次重构游戏功能不变,但代码更清晰 / 更快。

**5. 从"学生"到"毕业生"**。
Phase 7 你还在"学",Casey 演示什么你学什么。
Phase 8 完成后,HH 结束。**你不再是学生,你是"开源黑客"**——之后的项目要你自己选、自己设计、自己实现。

心智切换:**毕业不是终点,是新起点**。HH 教的是"地基",之后你要自己盖楼。**这个心智切换是 Phase 8 最后 1 天的核心**,Casey 在 Day 667 直播里专门讨论"HH 之后做什么"。

切换的最大陷阱:**优化错地方**。Phase 8 你学了一堆优化技术(八面体编码、k-d tree、体素化),可能想"什么都优化一遍"。**这是错的**。

正确策略(Casey 在 HH 里反复说):
1. **Profile**(Tracy)找最慢的 20%。
2. **优化这 20%**。
3. **再 Profile,迭代**。

测量优先于优化,**永远**。Phase 8 全程的核心纪律。

## §4 · 进 Phase 8 第一周学习路径

**Day 576-589(对应 HH day576-589)**:**八面体光照编码**。
重点:从球谐函数(SH)切换到八面体编码。每个体素存 16x16 RGB 贴图(3KB)代替 9 个 SH 系数。
产出:间接光存储更省内存,精度更高。
建议:结合 Phase 6 的 PBR 和 IBL 知识理解。

**Day 590-610(对应 HH day590-610)**:**无限弹射 GI**。
重点:基于八面体辐射场,迭代求解光的无限次弹射。蒙特卡洛积分。收敛判断。
产出:画面有"空间感",角落变亮,颜色渗透。
建议:这是 Phase 8 数学最难的部分,坚持下来视觉回报巨大。

**Day 611-630(对应 HH day611-630)**:**k-d tree + 空间查询优化**。
重点:k-d tree 构造、查询。walk table(预计算"光从 A 到 B 怎么走")。每帧 25 万次光线投射跑得动。
产出:GI 性能从"5 FPS"提升到"30+ FPS"。

**Day 631-650(对应 HH day631-650)**:**体素化碰撞系统**。
重点:从 Minkowski 重写为体素化方案。3D 体素网格,O(1) 查询。
产出:碰撞更准、更快,代码更简洁。

**Day 651-665(对应 HH day651-665)**:**最终整理 + bug 修复**。
重点:整个代码库 667 天累积,做最后整理。修复累积的 bug。
产出:代码可发布、可维护。

**Day 666-667(对应 HH day666-667)**:**HH 收官**。
重点:Casey 在最后两集讨论"HH 之后做什么"——开源贡献、商业开发、个人项目。
产出:**你毕业了**。

第一周结束你应该有:八面体编码实现,准备进 GI 深化。

## §5 · 实战项目建议

### 项目 A:简化 GI demo

写一个简化的 GI demo(不必完整无限弹射,做几次弹射)。技术栈:Rust + 你的渲染器 + CPU 光线投射。

需求:
- 加载一个简单场景(几个立方体)。
- 每个体素存"从这个方向来的光"(用八面体编码)。
- 光源照亮一些体素。
- 几次弹射后,间接光出现(墙角变亮)。
- 可视化(画屏幕看 GI 效果)。

时间预算:1-2 个月。

为什么推荐:**GI 是图形学最难的主题**,做一个简化版让你彻底理解。Unreal Lumen / CryEngine SVOGI 是更复杂版本,你做完这个再看那些代码就懂了。

### 项目 B:简单体素引擎(类 Minecraft)

写一个简化的 Minecraft 风格体素引擎。技术栈同上。

需求:
- 3D 体素网格(至少 64x64x64)。
- 玩家第一人称走动(WASD + 鼠标)。
- 挖方块(左键)、放方块(右键)。
- 简单光照(直接光 + 间接光的简化版)。
- 用 Phase 7 的 glTF 加载玩家手部模型。

时间预算:1-2 个月。

为什么推荐:**体素引擎是 HH Phase 8 综合的实战**。包含:渲染(Phase 6 PBR)、碰撞(Phase 8 体素化)、编辑(in-game 编辑器简化版)、性能(k-d tree 加速光线)。

### 项目 C:k-d tree 光线投射 demo

写一个 k-d tree 加速的光线投射器。技术栈:Rust。

需求:
- 加载一个三角形场景(从 glTF 或 .obj)。
- 构造 k-d tree。
- 从摄像机射光线,每个光线 O(log N) 找到相交三角形。
- 输出深度图或简单着色图。
- benchmark:对比暴力 O(N) 的速度。

时间预算:2-3 周。

为什么推荐:**k-d tree 是空间数据结构的经典**。理解了它,你看任何 3D 引擎的"加速结构"(BVH、k-d tree、octree)都不迷路。

## §6 · 推荐配合的 deep-dive

`/home/sun/src/handmade-hero-guide/days/phase-7/deep-dives/` 里进 Phase 8 前值得读的:

### `gltf-and-model-loading.md`(强推荐)

glTF 完整加载。Phase 8 GI 用复杂模型,先把加载搞稳。

### `asset-pipeline-architecture.md`(强推荐)

资产管线架构。Phase 8 优化包含资产加载的性能。

### `navmesh-and-pathfinding.md`(推荐)

A* 寻路。Phase 8 空间查询优化和 A* 是同一类问题(图搜索 + 加速结构)。

---

`/home/sun/src/handmade-hero-guide/days/phase-8/` 里的特殊文件:

### `shipping-appendix.md`(强推荐,Day 660+ 读)

发布附录。HH 完成后,游戏怎么打包发布、怎么写 README、怎么宣传、怎么应对社区。

---

`/home/sun/src/handmade-hero-guide/days/phase-8/deep-dives/`(如果有)和重读 Phase 5-7 的关键文章:

### `ecs-evolution.md`(重读,Phase 5)

Phase 8 最后整理时,ECS 是核心数据结构。重读这篇让你看清楚"自己的 ECS 还能怎么优化"。

### `threading-journey.md`(重读,Phase 5)

Phase 8 性能优化大量用多线程,重读这篇。

### `arena-allocator.md`(重读,Phase 4)

Phase 8 最后整理,内存管理是核心。重读这篇。

### `profiling-with-tracy.md`(重读,Phase 4)

Phase 8 全程 Profile,这篇是工具手册。

---

## 结语

Phase 7 是"工程化",Phase 8 是"收官"。Phase 7 完成时你的游戏功能完整,Phase 8 完成时你的游戏**商业品质**。

Phase 8 第一周(八面体编码)你会觉得"为什么要换,SH 不够吗"。**坚持下来**,你会发现八面体编码精度更高、内存更省,**这是工业级 GI 的标准做法**——Dice Frostbite、CryEngine SVOGI 都用类似方案。

Phase 8 中期(无限弹射 GI)你会觉得"数学好难,蒙特卡洛积分看不懂"。**坚持下来**,你会发现 GI 是图形学的圣杯,**理解了 GI,你看任何渲染技术都不迷路**——光线追踪、路径追踪、Lumen、RTGI 都是 GI 的变种。

Phase 8 后期(k-d tree、体素化碰撞)你会觉得"为什么 Phase 2 不这样做"。**坚持下来**,你会发现**好的代码是迭代出来的**——Phase 2 的 Minkowski 在那时是对的,Phase 8 的体素化在此时是对的。每个阶段用合适的工具。

Phase 8 最后两天的收官(Day 666-667)是最值得期待的。**Casey 在直播里讨论"HH 之后做什么"**——开源贡献、商业开发、个人项目、教学。**这一刻你不是 HH 的观众,你是 HH 的毕业生**。

Phase 8 全程的核心心智是:**最后的 10%,需要 50% 的努力,值得 100% 的回报**。HH 全程 667 天,Phase 8 是最后冲刺。**坚持到 Day 667,你完成了一件 99% 的人完成不了的事**——从零开始,理解一个商业游戏的每一行代码。

下一站:Day 576。最后的冲刺,准备毕业。
