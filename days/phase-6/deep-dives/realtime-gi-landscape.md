
# 实时全局光照全景:从光探针到路径追踪

> 你的 PBR 渲染器(见 `pbr-complete.md`)把**直接光**(direct light)做得很好——太阳打在金属球上,高光锐利、漫反射准确、能量守恒、金属/非金属区分清楚。你以为图形学已经到顶了。然后你做一个场景:一面鲜红的墙旁边站着一个穿白衣的人物。在真实世界里,墙的红色会"反弹"到人物的衣服上,衣服靠近墙的那一侧泛着一层粉红——这就是**间接光**(indirect light),也叫**色彩溢出**(color bleeding)。你的 PBR 渲染器算不出这种反弹。它在阴影里、在墙根下、在背光面,只有一个常数 `ambient = vec3(0.03)` 充当"环境光",所有像素的暗面都是同一个死灰。场景看起来扁平、生硬、没有空气感。真实世界的光会**弹**(bounce),弹一次是间接漫反射,弹两次是间接高光,弹无数次、所有弹道的累积就是**全局光照**(global illumination,GI)。把这种弹跳在 16 毫秒内实时算出来,是图形学几十年的永恒前沿。HH 项目在 phase-8 用"八面体辐射度贴图 + 体素迭代反弹"给了一个回答(见 `phase-8/deep-dives/tiled-lighting.md` 的 §9-§10 与 day576 的 octahedral encoding);这一篇要做的是**把整个现代实时 GI 的技术图谱摊开**:从最古老的 light probe 到最前沿的 ReSTIR 路径追踪 GI,让你看清每条路在哪、为什么这样设计、HH 站在哪里、你自己的引擎该选哪一条。

## 0 · 一面红墙让 PBR 露馅

想象你做完 `pbr-complete.md` 的练习,渲染了一个室内场景:一面正红的墙(`albedo = (0.9, 0.05, 0.05)`),墙前 30 厘米处立着一个白色立方体(`albedo = (0.9, 0.9, 0.9)`)。你点了一盏天花板上的点光源,光源直接照亮了墙和立方体朝上的面。你看了眼画面——**红墙是红的,白方块是白的,正确**。然后你蹲下来看方块朝向墙的那一面(背光面)。

真实世界(你拿个手机去拍)里,这一面会被墙反射的红光染成淡粉红——墙接收了点光源的红光,把它的一部分反弹出来,反弹出来的红光打在白方块上,白方块再把它反射进你的眼睛。这是**一次反弹的间接漫反射**。你的 PBR 渲染器算不出来。它的 fragment shader 在算这一面的颜色时,只考虑了**直接光**(从点光源直接到这一面),而这一面背对光源,直接光是零;然后它加上一个常数 `ambient = vec3(0.03)`,这一面就变成 `0.03 * (0.9, 0.9, 0.9) = (0.027, 0.027, 0.027)`——一个灰扑扑的死灰色,和墙的红色毫无关系。

更糟的是阴影。一个角色站在墙边,他的影子落在地上。真实世界里,影子**不是全黑的**——天空的光(天空作为巨大的面光源)和墙反弹的间接光会照亮影子的内部,影子内部甚至带着一点墙的颜色。你的渲染器算不出这种"被间接光照亮的阴影",影子就是一个常数灰,平贴在地上,像剪贴画。

这就是 PBR 的边界。PBR 的 BRDF(Cook-Torrance,见 `lighting-models.md` §4)算的是**给定入射光方向 ω_i 和出射方向 ω_o,表面反射多少光**。它需要你告诉它"入射光是从哪些方向来的、各方向多强"。对直接光,答案简单:从点光源那个方向来,强度是已知的。但真实世界的入射光不止来自点光源,还来自**所有其他表面反弹过来的光**——而那些表面的亮度,又取决于它们接收的光,其中一部分又是别的表面反弹来的……这是一个**递归**。离线渲染器(pbrt)的做法是**蒙特卡洛路径追踪**:从相机发视线光线,撞到表面后随机生成大量弹射方向(漫反射面在半球上按余弦分布采样,镜面面按 BRDF 采样),沿着这些方向再发新光线,递归若干跳(典型 8 跳以上),最后把所有路径累积起来得到一个像素的颜色。pbrt 渲染一帧 1080p 的图要**分钟到小时**——它每像素采样上千条光路。这就是离线 GI 的"正确答案"。

实时只有 16 毫秒。1080p 两百万像素,假设你全帧算 GI,每像素你能负担多少光路?算一道 GI ray 的 BVH traversal 大约 0.1~0.5 微秒(参见 `hardware-ray-tracing.md` §2-§3 关于 BVH 和 RT Core 的成本分析),每像素发**一条** GI ray,200 万像素 × 0.3 微秒 = 0.6 秒,远超 16 毫秒预算。即使你有 RT 硬件,1 spp(每像素 1 采样)的路径追踪 GI 是满屏噪声,必须靠 SVGF 那样的降噪(见 `hardware-ray-tracing.md` §5)反复在帧间累积——而累积要求运动矢量正确、要求像素在帧间能对得上、要求快速移动场景不产生 ghosting。所以"实时全路径追踪 GI"在可见的未来不是默认选项,它是高端 PC 的可选特性。

实时 GI 的真相是:**所有实时 GI 都是近似**(approximation)。没有任何一种实时 GI 算法能在 16 毫秒内算出物理正确的多跳间接光。每一种算法都是在**质量**(物理正确性、动态性、多跳)和**成本**(GPU 时间、内存、烘焙时间)之间做不同的取舍。这一篇要做的事就是把这些取舍讲清楚,让你看清整个技术图谱,然后把 HH 的八面体 GI 放在图谱上的正确位置——它**不是错的,也不是唯一的**,它是图谱上"静态几何 + 迭代反弹 + 光栅化友好"那一格,和 DDGI、VXGI、ReSTIR GI 是同一张地图上的不同路线。

## 1 · 为什么 GI 这么难:16 毫秒 vs 无限弹跳

把 GI 的根本难度说透,你才能理解后面所有算法为什么长那样。

GI 难,首先因为它是**一个积分方程**。某个表面点 `p`、法线 `n` 的出射辐亮度(radiance),是它接收的所有入射光(从上半球所有方向来的)、各自乘以 BRDF、再乘以余弦的**积分**:

```
L_out(p, ω_o) = ∫_Ω f_r(p, ω_i, ω_o) · L_in(p, ω_i) · (n · ω_i) dω_i
```

这个方程叫**渲染方程**(rendering equation,Kajiya 1986)。注意积分里的 `L_in(p, ω_i)`——它不是常数,它是"从方向 ω_i 进入 p 的光"。但这个 `L_in` 哪来的?**来自方向 ω_i 上、远处的某个表面 `p'` 的 `L_out(p', -ω_i)`**。也就是说 `L_in` 自己又是一个渲染方程——`L_out` 嵌套 `L_out`,无限递归。这就是 GI 的"难":它不是一个你算一次就完事的公式,是一个**自指**的积分方程,解它要把无穷弹跳全部展开。

离线渲染器(pbrt)的解法是**蒙特卡洛路径追踪**:把积分变成"采样若干方向、平均"——`L_out(p, ω_o) ≈ (1/N) Σ f_r · L_in · (n·ω_i) / pdf(ω_i)`。其中 `L_in` 沿采样方向发一条光线找到 `p'`,然后递归地用同样的蒙特卡洛估算 `L_out(p', ...)`,直到达到最大弹跳深度或俄罗斯轮盘决定停止。这是**数学上正确**的——N 趋于无穷时估算收敛到真值。但收敛慢,N 小时**方差大**(噪声大)。pbrt 渲染一个室内场景到没有可见噪声,通常需要每像素 1024~4096 条光路、8~16 跳,1080p 一帧要 10~60 分钟。

实时只有 16 毫秒。你能给 GI 的预算可能只有 2~3 毫秒(剩下的要留给直接光、阴影、反射、后处理、UI)。2 毫秒 / 0.3 微秒每 ray ≈ 6000 ray per millisecond per SM,GPU 有几十个 SM,粗算每帧能算百万级 ray,摊到 200 万像素,平均**每像素 0.5~2 条 ray**。这远远不够蒙特卡洛收敛——0.5 spp 的路径追踪 GI 噪声是天文数字。所以实时 GI 必须在两条路里二选一:**要么用很少的 ray + 强降噪**(RT GI 路线,DDGI+RT、ReSTIR GI);**要么完全不用 ray,用预计算 / 体积缓存的光照数据**(光栅化 GI 路线,light probe、irradiance volume、VXGI、HH 八面体 GI)。

第二条路是绝大多数实时 GI 的选择。它的核心思想是:**不要每像素实时算积分,而是把"空间每个位置的入射光分布"预先算好,存到一个数据结构里,运行时查询这个数据结构当作 `L_in`**。这是 light probe / irradiance volume / SH / 八面体贴图 / 体素 GI 的共同源头——它们都是把渲染方程的解**预先在空间中采样、缓存**。区别只在于"采什么、存什么、怎么查询、能否动态更新"。接下来几节就按"从最古老到最现代"的顺序讲。

## 2 · Light Probe 与 Irradiance Volume:整个工业的支柱

打开任何一个 3A 游戏,看它的"GI 设置",十有八九有一个选项叫 "Light Probe" 或 "Irradiance Volume"。这是实时 GI 的绝对主力,从 Unity 到 Unreal 到 Filament 到 Godot,所有现代引擎都支持它。理解 light probe 是理解整个 GI 图谱的基础。

**Light Probe(光探针)** 的核心想法极其简单:**在场景里一些"代表性"的位置,预先算好"从那个位置、看向所有方向,接收到的入射光分布",运行时像素根据自己的位置查找最近的探针、插值得到入射光**。

注意"预先算好"——这是关键的工程权衡。离线 GI 难,是因为它每像素实时积分;light probe 把积分**预先做了**,但只在**少数采样点**(探针位置)上做,而不是每像素做。如果场景里有 1000 个探针,每个探针的入射光分布只需要算一次(对静态场景),1000 次离线积分比 200 万次实时积分便宜得多,完全可以承受。

探针存什么?最直接的存法是**cubemap(立方体贴图)**——一个探针渲染它周围 6 个方向(上下左右前后)的辐亮度图。但 cubemap 贵:一张 256×256 的 cubemap,6 个面共 393216 个像素,每个像素 RGB 三个 float,12 字节,一个探针就要 4.5 MB。1000 个探针 = 4.5 GB。这显然不可行。

所以探针**不存完整 cubemap**,它存**入射光的低频部分**——这正是下一节要讲的 Spherical Harmonics(球谐函数)的用武之地。先记住结论:**一个探针通常只存几个 SH 系数(典型 9 个或 16 个 vec3),就够表达漫反射间接光**。9 个 vec3 = 108 字节,1000 个探针 = 108 KB——可以全部塞进 L2 cache,运行时查询极快。

**Irradiance Volume(辐照度体积)** 是 light probe 的工业化形态:**把整个场景空间划成一个 3D 网格,网格的每个格点放一个探针,每个探针存 SH 系数**。运行时,一个像素的世界坐标 `(x, y, z)` 落在网格的某个格子里,它根据自己相对于 8 个邻接格点的位置做**三线性插值**(trilinear interpolation),得到这个像素位置的入射 SH,然后用这个 SH 当作 `L_in` 算 PBR 漫反射。

这个架构的核心权衡是**静态 vs 动态**:

- **静态场景**(几何不变,只是相机和角色动):**烘焙一次**。在编辑器里点击"bake lighting",引擎对每个探针位置渲染一次辐照度 cubemap、压成 SH、存盘。运行时只查询,不重算。成本极低(每像素几次 SH 查找 + 插值),GI 质量极高(因为是离线算的)。这是 Unity 的 baked GI、Unreal 的 lightmass 烘焙、所有移动游戏的默认 GI 方案。
- **动态场景**(几何会变,墙被炸了、灯在动):烘焙的探针**失效**——你炸了一面墙,墙后空间的间接光全变了,但探针还是烘焙时的旧值。处理动态要么**周期性重算探针**(代价高),要么**部分动态**(只对动态物体附近的探针重算),要么干脆**放弃动态,只让静态几何有 GI、动态物体用别的方法**。这是工业现状——没有银弹,见第 7 节。

现在你能理解 HH 的八面体 GI 在这个图谱里的位置了(参见 `phase-8/deep-dives/tiled-lighting.md` 的 §9):HH 的"体素 + 八面体贴图"和 irradiance volume 是**同一种思路的变体**——都是"在空间离散点上预先存辐射度、运行时查询插值"。区别在于存储格式:irradiance volume 存 SH(低频漫反射),HH 存**完整的八面体 radiance map**(能表达高频,含镜面方向性);irradiance volume 通常烘焙一次,HH 在 phase-8 做的是**逐帧迭代反弹**(iterative bounce)——每帧用上一帧的辐射度计算这一帧的反弹,逐步收敛到多跳 GI 的解。两条路都是"体积缓存辐射度",HH 的更动态一些(每帧迭代)、表达力更强(八面体比 SH 高频)。这是 HH 作为教学项目在 GI 上的**一个有意识的设计选择**,不是过时,也不是最前沿——它处在 irradiance volume(静态烘焙)和 DDGI(动态 RT 探针)之间的中间格。

## 3 · 球谐函数:漫反射间接光的紧凑语言

上一节留了个悬念:探针怎么把一张 256×256 的 cubemap 压成几个 SH 系数?这一节就讲 Spherical Harmonics(球谐函数,SH)。

SH 是数学里"定义在球面上的正交基函数"——你可以把它理解成"二维傅里叶变换的球面版本"。傅里叶变换把一维信号(随时间变化的波)分解成一串正弦/余弦波,低频部分(缓慢变化的趋势)+ 高频部分(快速抖动的细节)。SH 做的是同样的事,但分解的是**定义在球面上的函数** f(θ, φ)——也就是"某个量随方向(球面上的位置)怎么变化"。

漫反射间接光就是一个球面函数。一个表面点 `p`,它接收的间接光来自上半球所有方向,每个方向的辐亮度 `L_in(p, ω_i)` 构成一个球面函数。漫反射 BRDF(粗糙表面)对入射光的方向**不敏感**——粗糙表面把入射光均匀散射,所以你不需要知道"这个方向的入射光精确是多少",你只需要知道"入射光的低频平均分布"就够算漫反射了。这正好是 SH 擅长的:**用少数几个 SH 系数,精准捕捉球面函数的低频部分**。

SH 的"阶"(band)对应频率:`l=0` 是常数项(整个球的平均),`l=1` 是线性项(三个方向梯度的差异),`l=2` 是二次项(更细的方向变化),依此类推。每阶 `l` 有 `2l+1` 个系数,所以前 3 阶(`l=0,1,2`)总共有 `1+3+5=9` 个系数。对 RGB 三个通道,9 个 vec3 = 27 个 float = 108 字节。

**关键的工程事实**:对漫反射间接光,**前 3 阶 SH(9 个系数)就够了**。这是 GPU Pro 和 SIGGRAPH 多年验证过的结论——漫反射 BRDF 是个低通滤波器,它把入射光的方向高频滤掉了,所以即使你存了高频 SH(`l=3` 及以上),漫反射积分时它们也几乎不贡献。Unity、Unreal、Filament、几乎所有商业引擎的 light probe 都用 SH3(9 系数)。少数要求高的会用 SH4(16 系数),收益边际。

把一张 cubemap 压成 SH,数学上是"投影":对每个 SH 基函数 `Y_l^m(ω)`,把 cubemap 的辐亮度 `L(ω)` 乘以这个基函数、在球面上积分,得到这个系数。在 GPU 上,这个积分用蒙特卡洛估算:对 cubemap 的每个像素(它代表一个方向 ω),累加 `L(ω) · Y_l^m(ω) · solid_angle(ω)`,最后归一化。一个简单的 GLSL compute shader 做投影长这样:

```glsl
// 输入:一张 cubemap,输出:9 个 vec3 的 SH 系数
// 每个 SH 系数 L_l^m = ∫ L(ω) Y_l^m(ω) dω
// 数值积分:对 cubemap 每个像素(代表一个方向 ω,有一个微小立体角 dω)
//          累加 L(ω) * Y_l^m(ω) * dω,最后除以总立体角(4π)归一化

layout(set = 0, binding = 0) uniform samplerCube env_cubemap;
layout(set = 0, binding = 1, std430) buffer SHCoeffs {
    vec3 sh[9];   // 9 个 vec3,RGB 各 9 个系数
};

const float[9] SH_BASIS_L0_TO_L2[/* evaluated per-direction in main */];

// SH basis functions Y_l^m(θ, φ), 前 3 阶的解析形式
// 这些是把球面方向 (x,y,z) 映射到 SH 基函数值的公式
vec3 sh_basis(int idx, vec3 dir) {
    // dir 是单位方向向量
    float x = dir.x, y = dir.y, z = dir.z;
    switch (idx) {
        case 0: return vec3(0.282095);                          // Y_0^0
        case 1: return vec3(0.488603 * y);                      // Y_1^-1
        case 2: return vec3(0.488603 * z);                      // Y_1^0
        case 3: return vec3(0.488603 * x);                      // Y_1^1
        case 4: return vec3(1.092548 * x * y);                  // Y_2^-2
        case 5: return vec3(1.092548 * y * z);                  // Y_2^-1
        case 6: return vec3(0.315392 * (3.0 * z * z - 1.0));    // Y_2^0
        case 7: return vec3(1.092548 * x * z);                  // Y_2^1
        case 8: return vec3(0.546274 * (x * x - y * y));        // Y_2^2
    }
    return vec3(0.0);
}

void main() {
    // 一个 workgroup 把整个 cubemap 投影到 SH
    // cubemap 分辨率 R,总像素数 6 * R * R
    // 每个线程处理若干像素,累加 L(ω) * Y(ω) * dω
    // (实际工程用 reduce/scan,这里给概念伪代码)
    // ...
    // 累加完,sh[idx] = sum / (4 * PI)  // 归一化
}
```

运行时反过来用:**给定一个像素的法线 n,从 SH 系数重建它接收的间接光**。重建比投影便宜得多——它是 SH 系数和"法线方向的 SH 基函数值"的点积:

```glsl
// fragment shader 里,从 SH 系数 + 法线 n,重建 n 方向的入射辐照度
vec3 sh_irradiance(vec3 sh[9], vec3 n) {
    n = normalize(n);
    return sh[0] * 0.282095
         + sh[1] * 0.488603 * n.y
         + sh[2] * 0.488603 * n.z
         + sh[3] * 0.488603 * n.x
         + sh[4] * 1.092548 * n.x * n.y
         + sh[5] * 1.092548 * n.y * n.z
         + sh[6] * 0.315392 * (3.0 * n.z * n.z - 1.0)
         + sh[7] * 1.092548 * n.x * n.z
         + sh[8] * 0.546274 * (n.x * n.x - n.y * n.y);
}

// 主着色
vec3 n = normalize(normal);
vec3 indirect_diffuse_irradiance = sh_irradiance(probe_sh, n);
// 漫反射间接光 = albedo * irradiance / PI
vec3 indirect_diffuse = albedo * indirect_diffuse_irradiance / PI;
```

这个重建在 GPU 上极便宜——9 次乘加。每像素算一次,1080p 200 万像素 × 9 次乘加 = 1800 万次乘加,现代 GPU 几十微秒就跑完。这就是 light probe / irradiance volume 运行时成本极低的根本原因。

注意一个工程细节:**SH 重建只给漫反射间接光,不给镜面间接光**。镜面反射是高频的(它关心"反射方向那个具体方向上有多亮"),SH 这种低频表示表达不了。镜面间接光要用**完整 cubemap**(prefilter environment map,见 `pbr-complete.md` §6 IBL)或**屏幕空间反射**(SSR,见 `hardware-ray-tracing.md` §0)或**RT 反射**(见 `hardware-ray-tracing.md` §6)。一个完整的间接光系统是 **SH 漫反射 + cubemap/SSR/RT 镜面** 的组合,GI 通常专指漫反射部分(虽然严格 GI 含两者)。

读到这里你应该意识到 HH 八面体 GI 的一个有意思的取舍:HH 用八面体 map 存**完整的 radiance**(不只是 SH 低频),所以它理论上可以同时提供漫反射和高频间接光(只要 shader 按方向采样八面体贴图)。这是它比纯 SH irradiance volume 表达力强的地方;代价是**内存和带宽大得多**(八面体 map 是 256×256 或更大的纹理,SH 是 9 个 vec3)。这是一种"用空间换频率分辨率"的设计。你做自己的引擎时,要根据自己的内存预算和频率需求选——绝大多数场景 SH3 已经够,需要镜面间接才上完整 radiance。

## 4 · DDGI:动态探针的现代答案

Irradiance volume 烘焙一次的方案对静态场景完美,但游戏不能只有静态场景——玩家会炸墙、灯会移动、日夜会交替。当几何或光源变了,烘焙的探针就失效。能不能让探针**每帧自己更新**,跟着场景一起变?

**DDGI(Dynamic Diffuse Global Illumination,动态漫反射全局光照)** 是这个问题的现代答案。它由 Epic Games 和 McGuire 等人在 2018-2019 年间提出,是 Unreal Engine 5 Lumen 的 diffuse GI 部分的基础思路之一,也被 Unity HDRP、Godot 4、Filament(部分)采用。DDGI 的核心思想是:**把 irradiance volume 从"烘焙一次"改成"每帧用 RT 光线动态更新",再加上巧妙的探针布局和过滤,得到一个动态、可信、性能可控的 GI 系统**。

DDGI 的工作流分三步。第一步,**每帧从每个探针发若干条光线**——通常是 32~256 条,光线方向用预生成的均匀半球分布(避免蒙特卡洛噪声)。这些光线打什么?在 RT 硬件上(见 `hardware-ray-tracing.md` §2 BVH),光线查 BVH 找最近交点;在没有 RT 硬件时,DDGI 也能用 depth pyramid(深度金字塔)或 voxel SDF(体素距离场)做软件 ray-march,只是精度低一些。光线命中后,从命中点的 G-Buffer 或一个简化的着色缓存里取**那一帧已经算好的直接光亮度**——注意,这一步取的是"上一帧已经着色好的结果",所以 DDGI 本质是**时序的**:这一帧的 GI 用上一帧的直接光,这样能避免无限递归。

第二步,**把每条光线的命中亮度压成 SH**。每个探针 32~256 条光线,正好够投影成 SH3(9 系数),这一步和 §3 的 cubemap 投影到 SH 是同一件事,只不过"输入"不是 cubemap 而是这 32~256 个稀疏采样点。

第三步,**时序平滑 + 探针重定位**。每一帧的 SH 估算有噪声(采样太少),所以 DDGI 把新算的 SH 和上一帧的 SH 做指数滑动平均(`new = lerp(old, new_sample, α)`,`α ≈ 0.1~0.2`),噪声被帧间累积抹平。这是时序降噪的极简版本——比 SVGF 简单得多,因为 SH 本身就是低频的(噪声天然小),不需要复杂的空间滤波。

探针重定位(relocation)是 DDGI 的另一个巧思:探针网格固定在空间里,但场景里有些探针**在墙里**(被几何遮挡)——这些探针算出来的 GI 是错的(它们看到的是墙内部)。DDGI 让每个探针维护一个"周围最近几何的距离",如果探针发现自己被几何包住,它**就近移动**到一个自由空间的位置(沿它看到的最远方向移一点)。这样动态场景里探针总能找到"合理的采样位置",不会被卡在几何里产生黑斑。

DDGI 还在每个探针里存一个**深度图**(每条光线对应一个深度),用于做**背向遮挡判断**(backface culling):像素查询探针时,如果像素在探针的某个深度方向"被墙挡住"(像素到探针的方向上,探针侧的深度比像素近),就不用这个探针的 SH,改用邻接的其他探针。这避免了"墙两侧的探针互相串色"的经典瑕疵(墙左边红光、右边蓝光,如果不过滤会变成紫色)。

一个极简的 DDGI 探针更新 compute shader 长这样(简化到概念级):

```glsl
#version 460
#extension GL_EXT_ray_query : enable

// 每个 workgroup 一个探针,每条光线一个线程
layout(local_size_x = 64, local_size_y = 1, local_size_z = 1) in;

layout(set = 0, binding = 0) uniform accelerationStructureEXT topLevelAS;
layout(set = 0, binding = 1) uniform sampler2DArray gbuffer_albedo;   // 命中点取色
layout(set = 0, binding = 2) uniform sampler2DArray gbuffer_world_pos;
layout(set = 0, binding = 3, std430) buffer ProbeSH     { vec3 sh[]; };
layout(set = 0, binding = 4, std430) buffer ProbeDepth  { float depth[]; };

const uint PROBE_RAYS = 64;       // 每探针 64 条光线
const uint PROBE_SH   = 9;
const uint PROBE_COUNT = /* grid_x * grid_y * grid_z */;

// 预生成的均匀球面采样方向(64 个),用 fibonacci sphere 或 halton
const vec3 ray_dirs[64] = /* ... */;

void main() {
    uint probe_idx = gl_WorkGroupID.x;
    uint ray_idx   = gl_LocalInvocationID.x;
    if (probe_idx >= PROBE_COUNT || ray_idx >= PROBE_RAYS) return;

    vec3 probe_pos = /* 网格坐标转世界坐标 */;
    vec3 dir = ray_dirs[ray_idx];

    // 发一条 ray query 到 BVH(允许软件版替换为 voxel ray-march)
    rayQueryEXT rq;
    rayQueryInitializeEXT(rq, topLevelAS,
        gl_RayFlagsNoneEXT, 0xFF,
        probe_pos, 0.001, dir, 100.0, 0);
    while (rayQueryProceedEXT(rq)) {}

    // 取命中点的上一帧直接光亮度(从 G-Buffer 简化)
    vec3 hit_radiance;
    float hit_distance;
    if (rayQueryGetIntersectionTypeEXT(rq, true) == gl_RayQueryCommittedIntersectionTriangleEXT) {
        vec3 hit_pos = rayQueryGetIntersectionBarycentricsEXT /* ... 重建 hit_pos */;
        hit_radiance = sample_direct_light_at(hit_pos);  // 从上一帧光照缓存查
        hit_distance = length(hit_pos - probe_pos);
    } else {
        hit_radiance = sample_skybox(dir);  // miss → 天空光
        hit_distance = 1000.0;
    }

    // 把这一条光线的贡献投影到 SH 基函数
    vec3 basis = sh_basis(ray_idx_to_basis_index(ray_idx), dir);
    vec3 contribution = hit_radiance;  // / pdf,均匀采样时 pdf = 1/(4π)

    // 用 shared memory 在 workgroup 内 reduce,得到 9 个 SH 系数
    shared vec3 sh_acc[9];
    // ... reduce 过程省略 ...
    // 写回 sh[probe_idx * 9 + i]
    // 写回 depth[probe_idx * PROBE_RAYS + ray_idx] = hit_distance
}
```

DDGI 的工程吸引力在于:**它不需要烘焙**(完全动态)、**它兼容低端硬件**(软件 ray-march 版能在没有 RT 的 GPU 上跑)、**它的运行时成本可预测**(探针数 × 每探针光线数 × BVH traversal 单价,你能精确预算)。代价是**它的二次反弹不严格**(依赖上一帧直接光,通常只有"一次反弹"的近似)、**它的精度受探针密度限制**(粗网格 = 模糊 GI,细网格 = 内存爆)。DDGI 是当前"足够好、足够快"的动态漫反射 GI 标杆,Unreal 5 Lumen 在没有 RT 硬件时主用它,Unity HDRP 的 Enlighten 后继也走这条路。

注意 DDGI 和 §2 irradiance volume 的关系:**DDGI 就是动态版的 irradiance volume**。区别仅在于探针 SH 怎么来——烘焙(静态)vs 每帧 RT 重算(动态)。理解了 §2-§3,DDGI 只是"换了数据来源的同一个数据结构"。

## 5 · VXGI 与体素锥追踪:被超越但仍重要的历史一步

讲完 DDGI 这个现代主力,回头讲一个**已经被超越但概念上仍然重要**的方法:VXGI(Voxel Global Illumination,体素全局光照)。

VXGI 由 NVIDIA 在 2014 年左右提出(GDC 2015, Cyril Crassin 的博士工作),是早期"完全动态、不需要烘焙"GI 的代表。它的核心想法:**把整个场景体素化(voxelize)成一个稀疏体素八叉树(sparse voxel octree,SVO),然后从被着色像素出发,沿一个"圆锥(cone)"在体素树里行进,沿途累加体素里存的辐亮度——这种"圆锥追踪"近似于在体素场景里查 GI**。

为什么用"圆锥"而不是"光线"?因为漫反射间接光不是从一个方向来的,是从半球所有方向来的——一个像素要积分整个半球的入射光。VXGI 的近似是:**用若干条圆锥来覆盖半球**,每条圆锥代表"一组相近方向的光",圆锥越远张角越大、覆盖体素越粗(走八叉树的高层节点),近处张角小、覆盖体素越细。典型配置是发 5~9 条圆锥覆盖半球,每条圆锥在体素八叉树里 march,沿途累加辐亮度,最后所有圆锥加权平均,得到这一像素的漫反射间接光。

VXGI 的体素化是关键工程难点。场景可能几百万三角形,要实时把它们光栅化进体素八叉树,NVIDIA 用了**保守光栅化**(conservative rasterization,确保三角形即使只擦边也写进体素)+ **体素化的 compute shader pipeline**。体素八叉树存储用 GPU 上的 bindless buffer,每个节点存子节点指针和这个体素的法线分布、反照率、辐亮度。这一套对 GPU 的依赖很重,需要特定的扩展和相当大的显存。

VXGI 的优缺点同样明显。优点:**完全动态**(几何变了重新体素化,几毫秒)、**多跳反弹**(可以在体素上迭代光照传播)、**比 light probe 表达更连贯**(体素是连续场,不像探针有插值瑕疵)。缺点:**精度受限**(体素粒度有限,小物体细节会被吃掉)、**显存大**(场景越大体素树越爆)、**圆锥追踪是粗糙近似**(5~9 条圆锥远不足以精确积分半球)、**GPU 负担重**(体素化 + 追踪都是 compute-heavy)。

到 2019 年以后,VXGI 基本被 **DDGI** 取代——DDGI 用更便宜的探针 + RT ray 达到了类似的动态效果,不需要体素化的复杂基础设施。Unreal Engine 4 早期用过 VXGI 的实验,后期切到 Lumen(DDGI + RT + surface cache);NVIDIA 自己的 VXGI demo 也停止维护。但 VXGI 的**核心洞见——把场景离散化成体素,在体素上传播光照——依然活在不同形式里**:HH 的八面体 GI 也是"体素化场景 + 体素上迭代光照"(虽然 HH 用光栅化投影到八面体而不是真体素);Unreal 5 Lumen 的 **Surface Cache**(把场景表面光栅化到一个体素化的卡片数组,作为辐射度缓存)是 VXGI 思想的现代化身;SDFGI(Godot 4)用 SDF + 体素标记,是 VXGI 的另一个变体。所以学 VXGI 不是为了实现它,是为了**理解"场景离散化 + 光照传播"这一大类方法的原理**,这能帮你理解 HH 的八面体 GI、Lumen Surface Cache、SDFGI 这些后继者。

把 VXGI 和 HH 八面体 GI 对比,你能看到 HH 的位置:HH 用"光栅化投影 + 体素上的八面体贴图",是 VXGI"体素 + 光照传播"思路的轻量化教学版;VXGI 用完整的稀疏八叉树 + 圆锥追踪,是工业级实现。两者的本质都是"预先把场景离散化,在离散化数据上算或缓存 GI",区别在离散的粒度(八面体 256² vs 体素 64³~256³)和传播方式(光栅化 vs 圆锥)。

## 6 · ReSTIR GI:路径追踪的实时化尖端

到现在讲的所有方法(SH probe、irradiance volume、DDGI、VXGI、八面体 GI)都是**非路径追踪**的——它们都用了某种"预缓存 / 离散化"的中间表示(SH、体素、八面体贴图),不是直接对渲染方程做蒙特卡洛。这一节讲图谱的另一端:**用路径追踪本身做实时 GI**——靠 ReSTIR 这一类现代算法,把每像素 1 条光线的稀疏采样,通过时空复用,做到接近 64 spp 的视觉质量。

**ReSTIR(Resampled Spatiotemporal Importance Resampling,时空重采样重要性采样)** 是 NVIDIA 和 Carnegie Mellon 在 SIGGRAPH 2020 提出的算法,后续工作 ReSTIR GI(2021)、ReSTIR PT(2022,完整路径追踪版本)把它扩展到多跳 GI。ReSTIR 的核心思想不在"算更准的光路",而在"**聪明地复用稀疏采样**"。

理解 ReSTIR 要先理解一个数学技巧——**重采样(resampling)**。蒙特卡洛估算积分 `∫ f(x) dx` 的标准做法是从某个分布 `p(x)` 采样 N 个点 `x_i`,估算 `(1/N) Σ f(x_i) / p(x_i)`。如果 `p(x)` 接近 `f(x)` 的形状(importance sampling),方差小;否则方差大。重采样是另一种思路:**先从某个" Proposal"分布(可能不好,但好采样)生成 M 个候选(M 大),然后从这 M 个里按"权重"挑 N 个保留——这 N 个保留的样本,等价于从"被权重重新塑形过"的更好分布里采样**。

ReSTIR 把这个思路用到像素之间和帧之间:**每个像素每帧只发 1 条光线(1 spp),但这条光线被存到一个"蓄水池"(reservoir)里;像素和它的邻接像素互相交换蓄水池里的样本(空间复用);像素和上一帧同位置的像素(用 motion vector 找到)也交换蓄水池(时间复用)。最终这个像素的 GI 不是它自己 1 spp 的结果,而是它周围 N 个像素 × 过去 M 帧累积起来的 M×N 个样本里,按权重挑出的等效采样**。

ReSTIR 的工程实现要点:**蓄水池数据结构**(存"被选中的那条光线、它的权重、当前累积的样本总数 M,这几个量)、**空间复用**(`shared memory` 在 workgroup 内、或 `subgroupShuffle` 在 warp 内交换相邻像素的蓄水池)、**时间复用**(从上一帧的历史缓冲、用 motion vector 重投影)、**可见性重算**(复用过来的样本光路可能在新像素位置被几何挡,需要重新查 BVH 验证,见 `hardware-ray-tracing.md` §4 Ray Query)。

一个 ReSTIR GI 的极简 compute shader 概念:

```glsl
#version 460
#extension GL_EXT_ray_query : enable

// 1. 每像素 1 条 GI ray(1 spp)
// 2. 把这条 ray 存到本像素的 reservoir
// 3. 和邻接像素、上一帧的 reservoir 重采样复用
// 4. 复用后,用最终的 reservoir 里的 ray 方向发一条 ray,取命中亮度

struct Reservoir {
    vec3  light_dir;     // 这一条被选中的样本方向
    float weight_sum;    // 累积权重
    uint  M;             // 累积样本数
};

void main() {
    ivec2 px = ivec2(gl_GlobalInvocationID.xy);
    uint  seed = hash(px, frame_index);

    // 步骤 1:本帧生成 1 个候选样本(从 BRDF importance sampling)
    Reservoir r;
    vec3 sample_dir = sample_brdf_important(pixel_normal, pixel_roughness, seed);
    float w_sample  = brf_weight(sample_dir);
    update_reservoir(r, sample_dir, w_sample, /* M_local= */ 1);

    // 步骤 2:空间复用——和邻接像素交换 reservoir
    Reservoir left  = load_reservoir_neighbor(px + ivec2(-1, 0));
    Reservoir right = load_reservoir_neighbor(px + ivec2(+1, 0));
    Reservoir up    = load_reservoir_neighbor(px + ivec2(0, -1));
    Reservoir down  = load_reservoir_neighbor(px + ivec2(0, +1));
    merge_reservoir(r, left);
    merge_reservoir(r, right);
    merge_reservoir(r, up);
    merge_reservoir(r, down);
    // 注意:merge 时要重新算可见性(避免把被遮挡的样本带过来)
    // 重算可见性:对每个被合并的样本方向发一条 shadow ray

    // 步骤 3:时间复用——和上一帧同像素位置(重投影)合并
    vec2  prev_uv = reproject(px, motion_vector);
    Reservoir prev = load_history_reservoir(prev_uv);
    merge_reservoir(r, prev);

    // 步骤 4:用最终的样本发 GI ray,取命中辐亮度
    vec3 gi_dir = r.light_dir;
    rayQueryEXT rq;
    rayQueryInitializeEXT(rq, topLevelAS,
        gl_RayFlagsNoneEXT, 0xFF,
        pixel_world_pos + normal * 0.001,
        0.001, gi_dir, 100.0, 0);
    while (rayQueryProceedEXT(rq)) {}
    vec3 hit_radiance = (miss) ? sky_radiance(gi_dir)
                                : sample_direct_light_at(hit_pos);

    // 步骤 5:输出(仍然有噪声,需要 SVGF 之类的时序降噪进一步处理)
    imageStore(gi_output, px, vec4(hit_radiance, 1.0));
    save_history_reservoir(px, r);  // 给下一帧
}
```

ReSTIR GI 的工程吸引力在于:**它是路径追踪的,所以物理正确(多跳、镜面间接、焦散都自然能算)**,而前面 DDGI/VXGI 都是只能算漫反射、不能算镜面间接的近似。代价是它**强依赖 RT 硬件**(ray query 是命脉)、**强依赖高质量降噪**(1 spp 即使被 ReSTIR 复用到等效 64 spp 也还是有残留噪声,要 SVGF 进一步过滤)、**强依赖 motion vector 准确**(快速移动场景的时序复用会失效)。所以 ReSTIR GI 是**高端 PC / 次世代主机**的方案,不能跨平台到移动端和老 GPU。

Unreal Engine 5 Lumen 在有 RT 硬件时(高画质模式)切到接近 ReSTIR GI 的路径追踪 GI;NVIDIA 自己的 RTX DI / RTX GI 项目就在这条路上;EA Seed 的 PICA PICA demo 是早期工业参考(见 `hardware-ray-tracing.md` §9 延伸阅读)。这是实时 GI 的"最前沿",不是默认选项,是未来方向。

把 ReSTIR GI 放在图谱上:它是**最右端(物理最正确、质量最高、成本最高)**;DDGI 是中段(动态、可信、不严格);irradiance volume + 烘焙是左端(静态、最高质量、零运行时成本);HH 八面体 GI 在中段偏左(动态性中等、表达力中等、跨平台)。理解了这个图谱,你就能根据自己的目标平台和画质预算,选一条路。

## 7 · 生产现实:没有银弹,混合才是工业真相

讲了这么多方法,作为工程师你必须面对一个生产现实:**没有任何一个 3A 游戏用单一的 GI 方法**。所有工业级的实时 GI 都是**多种方法的混合**——静态几何用烘焙(质量高、免费)、动态物体和动态光照用 DDGI 或 RT GI(贵但动态)、远距离或低预算用 SH probe 占位、镜面间接用 cubemap/SSR/RT 单独算。Lumen、Enlighten、Unity GI、Godot SDFGI 全部都是混合系统。

为什么会这样?回到 §1 的根本难处——GI 是一个不可能在 16 毫秒内完整解的积分方程,所有方法都是近似,而每种近似的"擅长场景"和"失败场景"不同。烘焙擅长静态、失败于动态;DDGI 擅长大场景漫反射、失败于小物体细节;RT GI 擅长一切但开销大、失败于低端硬件;SH probe 擅长远景、失败于近景高频。一个能跑在不同硬件、不同场景类型上的引擎,只能**按场景区域和硬件能力选择不同的方法**。

具体怎么混合?以 Unreal 5 Lumen 为例(它的设计是公开的,可以读 Epic 的 GDC 演讲):**屏幕空间的表面光栅化缓存(Surface Cache)** 提供一跳的辐射度(类似 VXGI 的简化);**Screen Space GI** 在屏幕空间快速估算近距离间接光(类似 SSR 但算漫反射);**距离场光线追踪(Distance Field Ray Tracing)** 处理多跳反弹(软件 RT,精度有限但跨平台);**有 RT 硬件时切到真 RT** 做最后的多跳精修;**Shadow ray 和镜面反射 ray** 是独立的 RT pass。所有这些 pass 通过 **frame graph(帧图,见 `phase-9/09B-3-frame-graph.md`)** 编排成依赖图——frame graph 决定 pass 的执行顺序、资源的生命周期、barrier 的插入,这是为什么 frame graph 是"混合 GI 引擎"的命脉(参见 `hardware-ray-tracing.md` §7 的同一论点)。

帧图在这里的关键作用是:**它让多种 GI 算法可以并行存在、按场景切换、自动管理资源**。你在帧图里定义 GI pass:`bake_irradiance_volume_pass`、`ddgi_update_pass`、`rt_gi_pass`、`svgf_denoise_pass`,每个 pass 声明它的输入(哪些 G-Buffer、哪些上一帧的 GI buffer)和输出(这一帧的 GI buffer),帧图编译器根据当前帧的设置(开 RT?开 DDGI?烘焙静态?)**只调度需要的 pass**,自动把它们的输入输出连起来、插入同步屏障。如果你不用帧图,手写这些 pass 的依赖和资源,你会被同步屏障和临时资源的生命周期淹没——这就是为什么 §8 的动手实践里,如果你有 RT GPU,做 DDGI 升级时**第一件事是把它表达成帧图里的一个节点**,而不是手写 command buffer。

帧图还有另一个隐藏的好处:**GI 是一个时序算法**(DDGI 要上一帧的 SH,ReSTIR 要上一帧的 reservoir),帧图能帮你正确处理"上一帧的资源"——把上一帧的 history buffer 标记成"persistent resource",帧图自动保留它跨帧。这是手写代码最容易出 bug 的地方(用错了 history buffer → ghosting 或 flickering)。

关于硬件能力的生产现实同样重要:**GI 必须有 fallback 路径**。高端 PC 走 RT GI(ReSTIR / DDGI+RT),中端走 DDGI(软件 ray-march),低端走 SH probe(完全静态),移动端走烘焙(没有任何动态)。你的引擎要在三到四条路径之间切换,共享尽可能多的代码(G-Buffer、PBR BRDF、tone mapping 全部一样),只在"GI 的具体算法"上分叉。这又回到了 `hardware-ray-tracing.md` §7 的"RT 是 gated feature"那段——GI 是更大的 gated feature,RT GI 是 GI 的子集,需要更细粒度的能力检测和 fallback。

## 8 · 在你 HH 项目里动手:加一个最小 Irradiance Volume GI(做中学红线)

现在轮到你了。这一节的动手实践,无论你有没有 RT GPU 都能做——基础版不需要 RT,只需要光栅化和 compute shader。你的目标是:**在 HH 项目里加一个最小的 irradiance volume GI**,用烘焙的 SH probe + 三线性插值,提供漫反射间接光;然后**和你现有的常数 ambient 对比**,亲眼看见间接光如何让场景"活起来"。如果你有 RT GPU,§8.5 给了一个进阶选项——把烘焙的 probe 升级成 DDGI 式的动态更新。

第一步,**设计探针网格**。在你 HH 的场景包围盒里,放一个 8×4×8 的探针网格(共 256 个探针),探针间距根据场景大小定(比如 2 米一格)。每个探针存 9 个 vec3 的 SH3 系数(108 字节),全部 256 探针 = 27 KB——一个 `VkShaderStorageBuffer` 就够。把网格坐标 → 世界坐标的变换做成一个 uniform。

第二步,**烘焙探针**(离线 / 编辑器阶段)。对每个探针位置,渲染一张低分辨率 cubemap(64×64 就够,SH 不需要高频),把它投影成 SH3 系数。烘焙可以在你的 HH 主程序里加一个 "bake GI" 模式——按一个键(`B`),触发对所有探针的渲染和投影,把结果写到 GPU buffer。烘焙阶段你要用真实光源(已有的直接光 + shadow map),让 cubemap 反映"如果有光从各个方向打过来,会怎样"。

```rust
// 烘焙伪代码(Rust 主程序,跑一次)
fn bake_irradiance_volume(
    probes: &mut [ProbeSH],   // 256 个探针,每个 9 个 Vec3
    scene: &Scene,
    gpu: &GpuContext,
) {
    for (idx, probe) in probes.iter_mut().enumerate() {
        let probe_world_pos = grid_to_world(idx);

        // 渲染 6 个面 cubemap,得到环境辐亮度
        let cubemap = render_cubemap_at(&gpu, &scene, probe_world_pos, 64);

        // 把 cubemap 投影成 SH3(9 个 Vec3)
        let sh = project_cubemap_to_sh3(&cubemap);
        *probe = sh;
    }
}

fn project_cubemap_to_sh3(cubemap: &Cubemap) -> ProbeSH {
    let mut sh = ProbeSH::zero();
    for face in 0..6 {
        for y in 0..cubemap.size {
            for x in 0..cubemap.size {
                let dir = cubemap_pixel_to_dir(face, x, y, cubemap.size);
                let radiance = cubemap.sample(face, x, y);
                let solid_angle = cubemap_pixel_solid_angle(x, y, cubemap.size);
                // 累加到 9 个 SH 基函数上
                for i in 0..9 {
                    let basis = sh_basis_fn(i, dir);
                    sh.coeffs[i] += radiance * basis * solid_angle;
                }
            }
        }
    }
    // 归一化(除以总立体角 4π)
    for c in sh.coeffs.iter_mut() {
        *c = *c / (4.0 * std::f32::consts::PI);
    }
    sh
}
```

这一步的关键工程细节:**cubemap 要包含直接光(含高亮的灯泡像素)**、**cubemap 的纹理格式用 RGBA16F 或 RGBA32F(HDR,灯泡可能 > 1.0)**、**SH 投影要在 linear 空间(不是 sRGB)做,最后显示再 gamma**。这些细节错了,GI 会发暗或发灰。

第三步,**写查询 shader**。在你的延迟光照 pass 里,每个像素根据它的世界坐标,在探针网格里查找 + 三线性插值,得到这个像素位置的 SH,然后用 §3 的 SH 重建函数算出间接漫反射辐照度,加入颜色:

```glsl
// 在你现有的延迟光照 shader 里,加上这段 indirect diffuse
layout(set = 1, binding = 0) uniform Probes {
    vec3  grid_origin;     // 网格 (0,0,0) 探针的世界坐标
    vec3  grid_spacing;    // 每格的距离
    uvec3 grid_dims;       // 8x4x8
};
layout(set = 1, binding = 1, std430) readonly buffer ProbeBuffer {
    vec4 sh_coeffs[];      // 每个 probe 9 个 vec3(对齐成 vec4 数组)
};

vec3 sample_irradiance_volume(vec3 world_pos, vec3 normal) {
    // 1. 算出 world_pos 在网格里的连续坐标
    vec3 uvw = (world_pos - grid_origin) / grid_spacing;
    vec3 base = floor(uvw);
    vec3 frac = uvw - base;

    // 2. 取 8 个邻接探针,做三线性插值
    vec3 interpolated_irradiance = vec3(0.0);
    for (uint dz = 0; dz < 2; ++dz) {
        for (uint dy = 0; dy < 2; ++dy) {
            for (uint dx = 0; dx < 2; ++dx) {
                uvec3 cell = uvec3(base) + uvec3(dx, dy, dz);
                // 边界 clamp
                cell = min(cell, grid_dims - uvec3(1));

                uint probe_idx = cell.x + grid_dims.x * (cell.y + grid_dims.y * cell.z);
                vec3 probe_sh[9];
                for (uint i = 0; i < 9; ++i) {
                    probe_sh[i] = sh_coeffs[probe_idx * 9 + i].xyz;
                }

                // SH 重建(用 §3 的 sh_irradiance 函数)
                vec3 probe_irradiance = sh_irradiance(probe_sh, normal);

                // 三线性权重
                float wx = mix(1.0 - frac.x, frac.x, float(dx));
                float wy = mix(1.0 - frac.y, frac.y, float(dy));
                float wz = mix(1.0 - frac.z, frac.z, float(dz));
                interpolated_irradiance += probe_irradiance * wx * wy * wz;
            }
        }
    }
    return interpolated_irradiance;
}

// 主着色(在你 PBR 直接光算完之后)
vec3 indirect_diffuse_irradiance = sample_irradiance_volume(world_pos, normal);
vec3 indirect_diffuse = albedo * indirect_diffuse_irradiance / PI;
vec3 final_color = direct_light + indirect_diffuse;  // 直接 + 间接
```

第四步,**验证视觉效果**。做一个测试场景:红墙 + 白方块 + 天花板灯。烘焙后,白方块朝向墙的那一面应该是粉红色(墙的红光反弹过来),阴影的内部应该是带色的软灰(不是死黑)。用 CVar(见 `phase-9/09B-4-cvars-and-dev-console.md`)切换 "GI 开 / 关",你应该看到 GI 开时整个场景"立体感"显著提升,色彩溢出和阴影内填充最明显。

排错常见问题:

- **GI 关闭和开启看不出差别** → 检查 SH 投影是否在 linear 空间(不在 sRGB)、检查 SH 基函数常数是否正确(Y_0^0 = 0.282095,这是最常错的地方)、检查 cubemap 是否包含直接光(不是只有环境贴图)。
- **GI 过亮 / 过暗** → SH 投影的归一化系数错了(应是 `1/(4π)` 不是 `1/(4π/3)`)、或 albedo 在 SH 重建后忘了除 π。
- **GI 在墙两侧串色** → 缺少 §4 DDGI 里的"背向遮挡"过滤;简单版可以在插值时根据像素到探针的方向做几何可见性测试(如果探针到像素的连线和像素法线点积 < 0,降低这个探针的权重)。
- **探针在墙里产生黑斑** → 烘焙时检查每个探针位置是否在自由空间(用你的体素碰撞或 BVH 查询),墙里的探针跳过烘焙或移到墙边。

第五步(可选,有 RT GPU),**升级到 DDGI 风格动态探针**。如果你的 GPU 支持 `VK_KHR_ray_query`(查 `vulkaninfo`,见 `hardware-ray-tracing.md` §8 第一步),把烘焙改成每帧一次的 compute pass:每个探针发 64 条 ray query,从命中点的 G-Buffer 取上一帧直接光,投影成 SH,做帧间指数平滑(α=0.1)。这就是 §4 的极简 DDGI。注意这一步**强烈建议先用 frame graph 表达**——把 ddgi_update_pass 作为一个节点,声明输入(上一帧 SH、G-Buffer)、输出(这一帧 SH),让帧图帮你处理同步和历史缓冲,不要手写。

完成上述五步后,你就拥有了一个从烘焙 irradiance volume 到(可选)DDGI 的完整 GI 系统。和 HH 的八面体 GI 对比(见 `phase-8/deep-dives/tiled-lighting.md`):你的 irradiance volume 用 SH(低频,只漫反射),HH 用八面体 map(高频,含方向性);你的更便宜,HH 表达力更强;你的烘焙一次,HH 每帧迭代。两个都是有效的工业级 GI 方案,你通过自己实现一个,理解了 GI 图谱上的"SH / 体积缓存"这一格;通过和 HH 八面体对比,理解了"完整 radiance / 体积缓存"那一格;通过(可选)升级 DDGI,理解了"动态 / RT 光线"那一格。**这就是这一篇要在你脑里建立的全景**。

## 9 · 练习

### Lv1 · 概念辨析

**题**:为什么漫反射间接光用 SH3(9 系数)就够,但镜面间接光必须用完整 cubemap?如果用 SH3 表达镜面反射会出什么问题?

**参考解答**:漫反射 BRDF 是一个低通滤波器——粗糙表面把入射光散射到几乎所有方向,所以它对入射光的方向变化不敏感,只需要入射光的低频(平均)分布就能算出准确的漫反射。SH3 正好捕捉球面函数的前 3 阶低频部分,所以够用。镜面反射相反,它对方向极敏感——一个镜子的反射色完全取决于"反射方向那一个具体方向上有多亮",哪怕入射光只在那一个方向有微小差异,镜面反射就完全不同。SH3 表达不了这种高频方向信号——它会把"反射方向上有一个亮点"平滑成一个模糊的发光区。用 SH3 做镜面反射,反射会变成一片污浊的辉光,完全失去"反射具体物体"的能力。这就是为什么镜面间接光必须用完整 cubemap(prefilter env map,见 `pbr-complete.md` §6)或 RT 反射(`hardware-ray-tracing.md` §6)——它们能保留高频方向信息。

### Lv2 · 动手实践

**题**:实现 §8 的最小 irradiance volume GI(基础版,不需要 RT GPU)。完成标准:能在画面里看到色彩溢出(红墙旁的白方块泛粉红),并且 GI 开关切换时有明显视觉差异。

**参考解答**:照 §8 五步走。最容易卡的两点:**SH 投影的基函数常数**和 **SH 重建函数的系数**——这两个数必须严格匹配(都用 SH3 的解析系数,Y_0^0=0.282095,Y_1^*=0.488603,Y_2^* 见 §3 代码),错一个符号整个 GI 就发灰或发蓝。验证方法:渲染一个纯白房间(四面墙都是 albedo=(1,1,1)),GI 应该让所有面接近一致的中灰,不应有明显的颜色偏移;然后再加红墙,色彩溢出应该出现。如果纯白房间 GI 就偏色,说明 SH 系数错了。烘焙 cubemap 时,先在一张图里把 cubemap 的 6 个面可视化出来,确认它正确反映了场景(灯、墙、地板都对),再投影到 SH。

### Lv3 · 迁移设计

**题**:你已经有了一个烘焙的 irradiance volume。现在场景里加了一个**可移动的火把**(玩家可以举着走)。火把的间接光(它照亮附近墙面,墙面反弹照亮角色)应该如何处理?烘焙的 irradiance volume 显然失效(火把位置变了)。描述三种可能的工程方案,以及各自的取舍。

**提示与参考方向**:

- **方案 A:把火把当作"特殊光源",在运行时直接在 fragment shader 里**单独算它的间接光——用一个简单的近似(比如对附近的探针位置预计算"火把在它这里的 SH 贡献",运行时叠加到烘焙 SH 上)。优点:便宜;缺点:火把以外的动态光源要为每种单独写代码,扩展性差。
- **方案 B:对火把附近的探针**做局部重烘焙(每帧只更新火把半径内的几个探针,重渲染小 cubemap + 投影 SH)。优点:质量好、局部化便宜;缺点:实现复杂(要管理"哪些探针是动态的、哪些是静态的"两套 buffer),多光源时管理复杂。
- **方案 C:整体上 DDGI**(§4 那一套),所有探针都每帧动态更新,火把作为"动态光源"自然就被算进去。优点:统一架构,所有动态光源都自动处理;缺点:成本高(每帧 256 探针 × 64 ray = 16384 ray query,在没有 RT 的 GPU 上跑不动)。

工业里最常见的是方案 B 的变体(Lumen 的"动态物体附近 Surface Cache 加密更新"+ 静态区走烘焙)。选择取决于动态光源数量、目标硬件、开发周期。

### Lv4 · 开源贡献

**题**:Bevy 的 GI 实现在 `crates/bevy_pbr` 里(目前是 light probe + 烘焙,后续在加 SDFGI / DDGI)。Clone 它,看它的 light probe 实现:

```bash
gh repo clone bevyengine/bevy
cd bevy
grep -rn "LightProbe\|irradiance_volume\|spherical_harmonic" --include="*.rs" --include="*.wgsl" -l
```

可能贡献方向:

- **文档**:Bevy 的 GI 路线图(`bevy_pbr/README` 或 RFC)里对"什么时候上 DDGI、什么时候上 SDFGI"的取舍说明,补一段"对照本篇的图谱,BBevy 当前在哪一格、未来计划往哪走"。
- **测试**:light probe 的 SH 投影 / 重建的单元测试覆盖,常缺一个"渲染一个已知场景、验证 SH 重建的颜色数值"的端到端测试。
- **Bug**:GitHub 上 `global illumination` / `light probe` label 的未解决 issue,常有一些边角 case(探针在几何内、超大场景的网格自动放置、SH 系数精度)。
- **性能**:用 `cargo flamegraph` 抓 Bevy 的烘焙 pass,看 cubemap 渲染和 SH 投影的占比,可能能找到并行化点。

**示例 PR 方向**(不要照抄):"docs(bevy_pbr): add GI technique landscape note explaining where Bevy's current light probe sits",目标是让贡献者在不读完整 GI 文献的情况下,理解 Bevy 当前的位置和未来路线。

## 10 · 延伸阅读

本仓库本地(强烈建议按顺序读):

- `days/phase-6/deep-dives/pbr-complete.md` —— PBR 的物理基础、BRDF 和 IBL(镜面间接光的 cubemap 路线,本篇 SH 的镜面对应物)。
- `days/phase-6/deep-dives/lighting-models.md` —— Lambert / Phong / PBR 的演进,理解直接光的 BRDF 是 GI 的基础。
- `days/phase-6/deep-dives/deferred-and-clustered.md` —— G-Buffer 和延迟渲染。DDGI、ReSTIR GI 都依赖 G-Buffer,这一篇是基础。
- `days/phase-6/deep-dives/hardware-ray-tracing.md` —— BVH、RT 管线、Ray Query、SVGF 降噪。DDGI+RT 和 ReSTIR GI 完全建立在这一篇之上。
- `days/phase-6/deep-dives/gpu-compute-fundamentals.md` —— GPU compute 的基础,本篇所有 GI 算法的探针更新和投影都在 compute shader 里跑。
- `days/phase-8/deep-dives/tiled-lighting.md` —— HH 的光栅化 GI 方案(含 §9 Casey 的选择、§12 现代趋势的 RT GI 提及),是本篇对照的核心基准。
- `days/phase-9/09B-3-frame-graph.md` —— 帧图。混合 GI 引擎的命脉,管理多 pass 的依赖、资源、同步。
- `days/phase-9/09C-6-textures-and-samplers.md` —— 纹理和采样器。cubemap、八面体 map、SH buffer 在 GPU 上的布局基础。

外部稳定 URL(长期有效):

- Real-Time Rendering, 4th ed., Chapter 11(Global Illumination)— 实时 GI 的工业教科书综述,覆盖本篇所有方法和取舍。
- McGuire et al., "Dynamic Diffuse Global Illumination with Ray-Traced Irradiance Fields"(DDGI 原论文,JCGT 2019):https://research.nvidia.com/publication/2019-03_Dynamic-Diffuse-Global
- Crassin et al., "Interactive Indirect Lighting Using Voxel Cone Tracing"(VXGI 原论文,I3D 2011):https://research.nvidia.com/publication/interactive-indirect-lighting-using-voxel-cone-tracing
- Bitterli et al., "Spatiotemporal reservoir resampling for real-time ray tracing with dynamic direct lighting"(ReSTIR 原论文,SIGGRAPH 2020):https://research.nvidia.com/publication/2020-07_RESTIR-Path-Resampling
- Ouyang et al., "ReSTIR GI: Path Resampling for Real-Time Path Tracing"(ReSTIR GI,SIGGRAPH 2021):https://research.nvidia.com/publication/2021-06_ReSTIR-GI
- PBRT(Physically Based Rendering)在线书第 5 章(Color Radiometry)和第 14 章(Light Transport),渲染方程和路径追踪的圣经:https://www.pbr-book.org/4ed/Light_Transport
- Sloan, "Stupid Spherical Harmonics (SH) Tricks"(SH 工程实践的经典 GDC 演讲,讲 SH 投影 / 重建 / 旋转的工程细节):https://www.ppsloan.org/publications/StupidSH36.pdf
- Epic Games, "Lumen: Real-time Global Illumination and Reflections in Unreal Engine 5"(GDC 2021 演讲,工业级混合 GI 的最佳实践):https://www.unrealengine.com/en-US/blog/a-first-look-at-unreal-engine-5
- Godot 4 SDFGI 设计文档(GitHub 上的 design RFC,讲 SDF + 体素标记的 GI 思路):https://github.com/godotengine/godot-proposals/issues/146

真实开源源码:

- Bevy 的 light probe 实现(Rust + WGSL):https://github.com/bevyengine/bevy —— 在 `crates/bevy_pbr` 搜 `light_probe` / `irradiance_volume`。
- Filament 的 IBL 和 SH 实现(Google 的 PBR 引擎,C++):https://github.com/google/filament —— `libs/filament/src/details/RenderPass.cpp` 里的环境光部分,`tools/cmgen` 是 cubemap → SH 的工具。
- NVIDIA Falcor(实时渲染研究框架,C++,含 DDGI、ReSTIR 参考实现):https://github.com/NVIDIA/Falcor —— 学 DDGI 和 ReSTIR 最完整的工业参考。
- Unreal Engine 5 Lumen(需要 Epic 账号):https://github.com/EpicGames/UnrealEngine —— `Engine/Source/Runtime/Renderer/Private/Lumen/`,工业级混合 GI 实现的全貌。
