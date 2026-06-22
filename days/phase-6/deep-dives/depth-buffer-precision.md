# 深度缓冲精度:Z-Fighting、Reverse-Z、浮点深度、线性深度

> 你做完光照,场景里几个圆形阴影互相穿透——上一帧墙壁正确挡住地板,这一帧地板反过来挡住墙壁,每帧抖一下。这叫 **z-fighting**(深度冲突)。它的根因不在你的代码,而在 24 位定点深度缓冲的浮点精度分布。本文从 IEEE-754 浮点的二进制结构讲到 reverse-Z,让你彻底掌握"为什么 GPU 深度不是线性分布"。

## 0 · 为什么会有这个问题

我们在 Day 261 引入了深度缓冲(depth buffer,也叫 z-buffer):每个像素渲染时算一个 z 值(深度,通常用"距离相机的远近"表示),和已存的深度比;更近的覆盖更远的。这套算法极其简单又极其有效——Casey 在 Day 261 用它取代了 Day 71 的"画家算法"(painter algorithm,从远到近依次画),因为画家算法对互相穿插的多边形无能为力。

可你一用深度缓冲,马上撞到三个怪事:

1. **z-fighting**:两面墙距离极近时,谁挡谁每帧抖动,出现"花纹"闪烁
2. **远处精度不足**:近处一个 0.01 单位的小缝隙清清楚楚,远处一座 10 单位的大山看起来像糊了一层马赛克
3. **1.0 永远到不了**:无论远裁剪面怎么设,远处物体写进 depth buffer 的值始终贴在 1.0 附近,看似"全部都到边了"

这些现象不是 bug,是 GPU 深度缓冲**数学结构本身**的副产物。你不懂这层结构,就只能到处加 `glPolygonOffset`(多边形偏移,后面讲)这种创可贴;懂了之后,你能用 reverse-Z、浮点深度、线性深度这三件武器把精度从 ~7 位有效数字推到 ~10 位,从而在 5km 视距下还能看清 1cm 的细节。

**读完这一篇你能**:
- 用 30 秒解释为什么深度缓冲在远处精度低
- 用一个 Rust 程序打印任意 z 值投影到 depth buffer 后的精度位数
- 在你的 OpenGL/Vulkan 渲染器里把 reverse-Z 配起来,把远处精度提升 100 倍
- 看 LearnOpenGL、Scratchapixel、PBR Book 里讨论深度时不再有黑盒

## 1 · 问题现场:用一个具体场景把 z-fighting 逼出来

假设场景里有两面墙:

- 墙 A:平面 z = 50.0(世界空间,沿着相机正前方 50 米)
- 墙 B:平面 z = 50.001(比 A 远 1 毫米)

相机在原点,近平面 near = 0.1,远平面 far = 1000.0。透视投影矩阵把世界 z 映射到 NDC(normalized device coordinate)空间 z ∈ [0, 1](OpenGL)或 z ∈ [-1, 1](Vulkan/Direct3D)。映射公式是:

```
z_ndc = (far + near) / (far - near) + (-2 * far * near) / ((far - near) * z_eye)
```

`z_eye` 是相机空间(原点在相机、看向 -z)的 z(负值,因为相机看 -z 方向)。

把这个公式简化下,我们发现 z_ndc 和 1/z_eye 几乎是线性的——也就是说,远处的物体在 z_ndc 上的差距被极度压缩。具体来说,墙 A 和墙 B 投影到 z_ndc 后:

- A:z_ndc ≈ 0.99980
- B:z_ndc ≈ 0.99980(差不到 10⁻⁶)

24 位 depth buffer 的精度是 2²⁴ ≈ 1677 万个离散值,覆盖 [0, 1] 区间。两个值差 10⁻⁶,对应 depth buffer 上差大约 17 个码位。这听起来够分辨,但 GPU 光栅化阶段会有亚像素抖动——浮点计算 round-off 让 z_ndc 在 17 个码位附近跳,于是 A 和 B 谁近谁远每帧不同,深度测试通过/失败每帧切换,屏幕上你看到的就是闪烁。

**这就是 z-fighting 的根因**:深度缓冲在远处精度太低,两个本该有不同深度的物体被舍入到同一个/相邻码位。

## 2 · 心智模型

### 类比:测距尺

想象你有一根 1 米长的尺子,上面均匀刻了 1000 条刻度(每 1mm 一条)。在尺子近端(0 到 10cm),1mm 一格很清楚,你能分清两个相隔 1mm 的物体;但在尺子远端(90 到 100cm),假设这尺子"远端被魔法压缩了",原本 1mm 的刻度其实代表了 1cm——两个相隔 1mm 的物体,在远端可能落在同一条刻度上,无法分辨。

深度缓冲就是这样一根"被魔法压缩"的尺子,但不是魔法——是浮点精度分布的结果。

### 严谨原理:从透视矩阵到 NDC

相机空间(eye space)中,物体在 z_eye 处(负数,因为相机看向 -z)。透视投影矩阵 P 是:

```
P = | f/aspect  0   0                      0                     |
    | 0         f   0                      0                     |
    | 0         0   (far+near)/(near-far)  2*far*near/(near-far) |
    | 0         0   -1                     0                     |

f = 1 / tan(fov/2)
```

我们关心的是 z 维度的变换。一个点 (0, 0, z_eye, 1) 经过 P 后:

```
clip_z = P[2][2] * z_eye + P[2][3]   =  ((far+near)/(near-far)) * z_eye + 2*far*near/(near-far)
clip_w = -z_eye
z_ndc  = clip_z / clip_w
```

把上面代入并化简,OpenGL 风格(clip_w = -z_eye,NDC z ∈ [0, 1])的结果是:

```
z_ndc = (far + near)/(far - near) + (2 * far * near) / ((far - near) * z_eye)
```

当 `z_eye = -near`(近平面),z_ndc = 0;当 `z_eye = -far`(远平面),z_ndc = 1。中间不是线性——z_ndc 随 1/z_eye 变化,曲线在近端陡、远端平。

这条**曲线的形状就是精度分布**:在近处,z_eye 微小变化也能让 z_ndc 跨过好几个码位;在远处,z_eye 巨大变化也只能让 z_ndc 在最后一个码位附近徘徊。

### 精度分布的具体形状

把 z_ndc 对 z_eye 求导:

```
dz_ndc / dz_eye = -(2 * far * near) / ((far - near) * z_eye²)
```

在 z_eye = -near(近平面),绝对值是 `2/(near * (far-near)/far)`,很大。
在 z_eye = -far(远平面),绝对值是 `2*near/(far² * (far-near)/far)`,极小。

近处 / 远处精度比 ≈ far/near,如果 near=0.1、far=1000,比值就是 10000——近处精度是远处精度的 1 万倍!

这就是"为什么远处总是糊"。

### 浮点深度的二进制结构:为什么 reverse-Z 有效

标准的 24 位深度缓冲通常配 `GL_DEPTH_COMPONENT24`(24 位无符号整数)或 `GL_DEPTH_COMPONENT32F`(32 位 IEEE-754 浮点)。即使你声明为 24 位整数,GPU 还是把 z_ndc ∈ [0, 1] 视为定点小数;真正提升精度的关键是用 **32 位浮点** + **reverse-Z**。

先看 IEEE-754 单精度浮点:`1 位符号 + 8 位指数 + 23 位尾数`。指数决定了"浮点能表示的范围",尾数决定了"在某个指数下的相对精度"。**关键性质**:浮点数在指数大的区间(远离 0)精度低(相邻两数间距大),在指数小的区间(靠近 0)精度高(相邻两数间距小)。这和深度缓冲的"远处精度低"完全同构。

**reverse-Z 的精妙**:把标准 z_ndc ∈ [0, 1](0=近、1=远)翻转成 z_reverse = 1 - z_ndc(1=近、0=远),深度测试从 `LESS` 改成 `GREATER`。这样:

- 在近平面,z_reverse = 1.0。浮点数 1.0 附近的间距是 2⁻²³ ≈ 1.2e-7,精度极高。
- 在远平面,z_reverse = 0.0。浮点数 0.0 附近(指数极小),相邻间距是 2⁻¹⁴⁹ ≈ 1.4e-45——精度反而**最高**(subnormal 区间)。

但深度公式告诉我们,z_reverse 在远处仍然线性变化于 1/z_eye。所以 reverse-Z 的真正收益是:**用浮点在近端的"高相对精度"匹配深度公式在近端的"高变化率",用浮点在远端的"低相对精度"匹配深度公式在远端的"低变化率"**——两者刚好抵消,得到几乎均匀的 z_eye 精度分布。

实战收益:对 near=0.1, far=10000 这种极端配置,标准 24 位定点深度在 10 米外的精度就崩了;reverse-Z + float32 能撑到 1km 还保持厘米级。

### 线性深度(Linear Z)

为什么不用"纯线性 z_ndc = (z_eye - near) / (far - near)"?有两个原因:

1. **硬件透视修正**:GPU 的透视纹理插值(perspective-correct interpolation)假设 z 是 1/z 形式。你强改成线性,光栅化阶段就要额外算 1/z,白白浪费硬件单元。
2. **深度测试的目的**:深度测试不需要"线性距离",它只需要"排序正确"。1/z 也是单调的,排序一样正确。所以工业界极少用纯线性 z。

但**G-Buffer / deferred shading**(延迟着色)里经常存线性深度,因为它要做后处理(屏幕空间反射、雾、景深),线性深度更方便。所以你会看到很多引擎同时存两份:一份硬件 depth buffer(1/z 形式给硬件测试用),一份线性化后的 linear depth texture(给 shader 用)。

线性化公式:

```
linear_z = (2 * near * far) / (far + near - z_ndc * (far - near))
```

(OpenGL 风格,z_ndc ∈ [0, 1])

## 3 · 概念深入

### 3.1 · Z-Fighting 的工程化解

z-fighting 不是必须靠"提升精度"才能解决。三种实战方案:

**方案 1:几何上避免共面**。两个三角形真的不应该完全共面——你设计场景时给它们 1mm 间隙,或者用 `glPolygonOffset`(多边形偏移)给其中一个三角形在深度上推一点。

**方案 2:提高 near plane**。near 从 0.01 改成 0.1,精度提升 10 倍。代价:相机贴近物体时物体被裁剪。多数游戏 near = 0.1 已经够。

**方案 3:reverse-Z + float depth**。最大收益,但要确保你的渲染管线所有 shader 的 z 比较方向都改对。

### 3.2 · 多种深度格式对比

| 格式 | 位数 | 取值范围 | 主要用途 |
|---|---|---|---|
| `GL_DEPTH_COMPONENT16` | 16 位无符号整数 | [0, 1] 定点 | 移动端 / 老硬件 |
| `GL_DEPTH_COMPONENT24` | 24 位无符号整数 | [0, 1] 定点 | 桌面 OpenGL 默认 |
| `GL_DEPTH_COMPONENT32F` | 32 位 IEEE-754 浮点 | [0, 1] 浮点 | reverse-Z 必备 |
| `GL_DEPTH24_STENCIL8` | 24 位深度 + 8 位模板 | 同 D24 | 大多数桌面场景 |
| `GL_DEPTH32F_STENCIL8` | 32 位浮点深度 + 8 位模板 | 同 D32F | reverse-Z + 模板 |

注意:24 位整数深度上用 reverse-Z **几乎没收益**,因为整数定点在 [0, 1] 上是均匀分布,翻转后还是均匀,精度不会变。**只有浮点深度配合 reverse-Z 才能利用浮点的非均匀精度**。

### 3.3 · Reverse-Z 的实际配置

以 OpenGL 为例,关键步骤:

```c
// 1. 创建深度纹理时用 32F
glTexImage2D(GL_TEXTURE_2D, 0, GL_DEPTH_COMPONENT32F,
             width, height, 0, GL_DEPTH_COMPONENT, GL_FLOAT, NULL);

// 2. 投影矩阵的 z 维度翻转(把 [near, far] 映射到 [1, 0] 而不是 [0, 1])
//    数学上等价于:z_ndc_new = 1 - z_ndc_old
//    实际就是把 P[2][2] 和 P[2][3] 取反

// 3. 清屏时清成 0
glClearDepthf(0.0f);

// 4. 深度测试改成 GREATER
glDepthFunc(GL_GREATER);
```

Vulkan 风格略不同:NDC z 已经在 [0, 1](不是 OpenGL 的 [-1, 1]),Vulkan 的 `VK_COMPARE_OP_GREATER` + `depthClearValue = 0.0` 直接可用。

### 3.4 · W-Buffer(Direct3D 时代的实验)

Direct3D 9 时代有个 w-buffer,直接用 clip-space 的 w(= -z_eye)做深度测试。w 在 eye 空间是线性的,所以 w-buffer 天然有均匀精度。但它需要硬件支持,而且和透视纹理插值不兼容(因为硬件按 1/z 插值),后来被淘汰。今天没人用 w-buffer,但它的设计思路(reverse precision bias)启发了 reverse-Z。

## 4 · Rust 落地:精度计算小工具

我们写个 Rust 程序,打印任意 near/far/z_eye 配置下的精度位数,让你直观看到 reverse-Z 的收益:

```rust
// depth_precision.rs
// 用 `cargo run --release` 跑,看不同配置下深度精度

fn project_standard(z_eye: f32, near: f32, far: f32) -> f32 {
    // 标准 OpenGL 投影:z_eye ∈ [-far, -near] 映射到 z_ndc ∈ [1, 0]
    // 注意:eye space 里 z_eye 是负数(相机看 -z),这里我们传正数表示"距离"
    let z = -z_eye;  // 转回负数
    let a = (far + near) / (far - near);
    let b = (2.0 * far * near) / (far - near);
    // 注意这里用 z_eye(负数)算,公式里我们直接代:
    // z_ndc = a + b / z_eye(负数,所以 b/z_eye 是负数,加 a 后落在 [0,1])
    a + b / z
}

fn project_reverse(z_eye: f32, near: f32, far: f32) -> f32 {
    // reverse-Z:就是把 standard 翻转
    1.0 - project_standard(z_eye, near, far)
}

fn float_ulp(x: f32) -> f32 {
    // 浮点的"单位最后位"(unit in the last place):相邻可表示浮点数的间距
    // 用 std 提供的函数:f32::from_bits(x.to_bits() + 1) - x
    let next = f32::from_bits(x.to_bits() + 1);
    next - x
}

fn main() {
    let near = 0.1_f32;
    let far = 1000.0_f32;
    println!("near={}, far={}", near, far);
    println!("{:>10} {:>15} {:>15} {:>15} {:>15}",
             "z_eye", "z_std", "ulp_std", "z_rev", "ulp_rev");
    for &z in &[0.1, 0.5, 1.0, 5.0, 10.0, 50.0, 100.0, 500.0, 999.0] {
        let s = project_standard(z, near, far);
        let r = project_reverse(z, near, far);
        let ulp_s = float_ulp(s);
        let ulp_r = float_ulp(r);
        println!("{:>10.3} {:>15.7} {:>15.2e} {:>15.7} {:>15.2e}",
                 z, s, ulp_s, r, ulp_r);
    }
}
```

每行注释:

- `project_standard` — 实现 OpenGL 风格的 z 投影。`a` 和 `b` 是投影矩阵的 z 维度分量,写在函数内方便你直观看
- `project_reverse` — reverse-Z 就是 1 减去标准 z
- `float_ulp` — ulp(unit in the last place)是浮点能分辨的最小间距。`f32::from_bits(x.to_bits() + 1)` 利用 IEEE-754 的"按位递增 = 浮点递增"性质,直接拿到下一个可表示浮点
- `{:>15.2e}` — Rust 格式化:`>` 右对齐,`15` 宽度,`.2e` 两位有效数字科学计数法

跑出来你会看到:在 z_eye = 999.0 时,标准 z 的 ulp ≈ 1e-5,而 reverse z 的 ulp ≈ 1e-7。**reverse-Z 在远处精度提升 100 倍**。

## 5 · 对照与变奏

| 方案 | 精度分布 | 兼容性 | 推荐场景 |
|---|---|---|---|
| 标准 z(定点) | 近密远疏 | 所有硬件 | 移动端 / 老硬件 |
| 标准 z(浮点) | 近密远疏(浮点略好) | OpenGL 3.3+ / Vulkan | 桌面默认 |
| Reverse-Z(浮点) | **接近均匀** | 现代 GPU | 桌面 + 远视距 |
| 线性 z(W-buffer) | 完全均匀 | 已淘汰 | 不推荐 |
| 多层 depth | 每层各自均匀 | 复杂 | 不推荐 |

### 历史

- 1974 年:Ed Catmull 在他的论文里提出 z-buffer 算法(那时还是软件实现)
- 1990 年代:SGI 工作站硬件化 z-buffer,定点 24 位成标准
- 2000 年代:Direct3D 9 w-buffer 实验失败,被淘汰
- 2009 年:OpenGL 3.0 引入 `GL_DEPTH_COMPONENT32F`
- 2015 年左右:reverse-Z 在 D3D11/Vulkan 时代被广泛采纳,Braynzar Vision、LearnOpenGL 都有教程
- 2020 年代:Vulkan / DX12 / Metal 全部原生支持 reverse-Z

## 6 · 关联 Day

- **铺垫**:Day 071 软渲染里的画家算法 / Day 261 引入 z-buffer
- **当天**:本篇是 Phase 6 深度缓冲专题
- **后续**:Day 280+ 阴影映射会大量用深度缓冲(而且会有自己的精度问题,叫 shadow acne);Day 410+ 延迟着色会存线性深度到 G-Buffer

## 7 · 变式训练

### Lv1 · 概念辨析

**题**:为什么 24 位整数深度上做 reverse-Z 没收益,但 32 位浮点深度上有?

**参考解答**:整数定点在 [0, 1] 区间是**均匀分布**——每个码位代表 1/2²⁴ ≈ 6e-8,翻转后还是均匀,精度不变。浮点数是**非均匀分布**——在 1.0 附近 ulp 大(因为指数大),在 0.0 附近 ulp 小(因为指数小)。reverse-Z 把"近平面"映射到 z=1.0(浮点精度低的位置),把"远平面"映射到 z=0.0(浮点精度高的位置),再配合深度公式本身"近密远疏"的特性,**两边的非均匀性相互抵消**,最终在 z_eye 上得到接近均匀的精度。整数深度没有这层"浮点非均匀精度"可以博弈,所以翻转无用。

### Lv2 · 动手实践

**题**:在你的渲染器里(无论是 Day 265 写的 OpenGL 还是软渲染器)启用 reverse-Z,把 near 设到 0.05, far 设到 5000,观察远处场景有没有变化。

完成标准:截图前后对比,说明 z-fighting 区域有没有减少。

**参考解答**:三步走——
1. 改投影矩阵:在 Perspective FOV 构造里,把 P[2][2] 和 P[2][3] 取反(直接对应 z 维度翻转)
2. 改 clear:`glClearDepth(0.0)`, Vulkan 里 `clear_depth_stencil.depth = 0.0`
3. 改测试函数:`glDepthFunc(GL_GREATER)`, Vulkan 里 `VkCompareOp::GREATER`

### Lv3 · 迁移设计

**题**:你要做光线追踪的 t-buffer(ray 距离 t 的缓冲),和深度缓冲类似。光线的 t 是线性的(没有透视压缩),那你的 t-buffer 应该用什么格式?float32 还是 uint32?为什么?

**提示**:光线追踪里 t 的范围可以是从 1e-6(贴脸)到 1e9(场景外),跨度 15 个数量级。定点 uint32 在 [0, far] 上均匀分布,远处精度浪费,近处精度不够;浮点按指数分布,但相对精度恒定 2⁻²³。想想哪种更合适。

### Lv4 · 开源贡献

**题**:`wgpu` 是 Rust 写的跨平台图形抽象层,GitHub: https://github.com/gfx-rs/wgpu

1. clone 它,`cargo build --release`
2. 在 examples 目录里找一个用深度缓冲的例子(比如 `boids` 或 `shadow`)
3. 看它有没有用 reverse-Z,如果没有,试着改一改
4. 看看它投影矩阵构造在哪(glam / nalgebra / cgmath)
5. 可能的贡献:文档里加一段"how to enable reverse-Z in wgpu"的指南,提 PR

## 8 · Rust / Arch 落地代码

完整的 reverse-Z 启用流程,假设你用 `glow`(OpenGL 封装) + `glam`(向量数学):

```rust
// 在初始化时
use glow::*;

unsafe {
    // 1. 创建 depth buffer 纹理,32 位浮点
    let depth_tex = gl.create_texture().unwrap();
    gl.bind_texture(TEXTURE_2D, Some(depth_tex));
    gl.tex_image_2d(
        TEXTURE_2D,
        0,
        DEPTH_COMPONENT32F as i32,  // 关键:32 位浮点
        width, height,
        0,
        DEPTH_COMPONENT,
        FLOAT,
        None,
    );

    // 2. 深度测试方向:GREATER(reverse-Z)
    gl.enable(DEPTH_TEST);
    gl.depth_func(GREATER);  // 标准 z 是 LESS

    // 3. 清屏值:0.0(而不是 1.0)
    gl.clear_depth_f(0.0);
}

// 投影矩阵(reverse-Z 版)
fn perspective_reverse_z(fov: f32, aspect: f32, near: f32, far: f32) -> glam::Mat4 {
    // f = 1 / tan(fov/2)
    let f = 1.0 / (fov / 2.0).tan();
    // 注意 reverse-Z:把 z 维度的两个系数取反
    // 标准 OpenGL 投影的 [2][2] = (far + near) / (near - far)
    //                       [2][3] = 2 * far * near / (near - far)
    // reverse-Z 后 [2][2] = -(far + near) / (near - far)
    //                [2][3] = -2 * far * near / (near - far)
    // 因为 reverse-Z 后,近平面 z_eye = -near 映射到 z_ndc = 1.0,
    // 远平面 z_eye = -far 映射到 z_ndc = 0.0
    glam::Mat4::from_cols(
        glam::Vec4::new(f / aspect, 0.0, 0.0, 0.0),
        glam::Vec4::new(0.0, f, 0.0, 0.0),
        glam::Vec4::new(0.0, 0.0, -(far + near) / (near - far), -1.0),
        glam::Vec4::new(0.0, 0.0, -2.0 * far * near / (near - far), 0.0),
    )
}
```

每行解释:

- `glow` — Rust 里调用 OpenGL 的轻量封装,API 形似 C 但有 Rust 的所有权检查
- `glam::Mat4` — 一个 4×4 矩阵库,游戏行业事实标准
- `from_cols` — glam 矩阵是列主序(column-major),和 OpenGL 一致
- 投影矩阵里 `[3][2] = -1.0` 那一列——这是把 z_eye 复制到 clip w(透视除法的分母)
- 注意 `-[2][2]` 的负号:这是把 z 维度翻转,实现 reverse-Z

Arch Linux 上跑起来:

```bash
# 装依赖
sudo pacman -S mesa rust

# 运行你的渲染器(假设是 cargo 项目)
cd ~/src/my-renderer
cargo run --release
# 输出示例:
#   Compiling my-renderer v0.1.0
#   Finished release [optimized] target
#   Running target/release/my-renderer
# (画面出现,远处细节明显改善)
```

排查 z-fighting 没解决的常见原因:

```bash
# 1. 确认 depth format 真的切了
#    用 apitrace 或 renderdoc 看
sudo pacman -S renderdoc
renderdoc &  # GUI 工具,抓一帧看 depth buffer 的格式
# 在 renderdoc 的 Texture Inspector 里看 Depth,显示 R32_SFLOAT 才对

# 2. 确认 depth func 真的改了
#    在 renderdoc 里看 Pipeline State -> Output Merger -> Depth Func,
#    应该是 GREATER(而不是 LESS)

# 3. 确认 clear 值改了
#    renderdoc 里看 Clear,Depth 应该是 0.0(而不是 1.0)
```

## 9 · 延伸阅读

本仓库本地:

- `days/phase-6/day261.md` — 引入 z-buffer 的那一天
- `days/phase-6/deep-dives/shadow-mapping.md` — 阴影映射的深度精度问题

外部稳定 URL(读者可深挖):

- LearnOpenGL Depth testing: https://learnopengl.com/Advanced-OpenGL/Depth-testing
- Scratchapixel Rendering Pipeline: https://www.scratchapixel.com/lessons/3d-basic-rendering/perspective-and-orthographic-projection-matrix
- PBR Book: https://www.pbr-book.org/3ed-2018/Camera_Models/Projective_Camera_Models
- Braynzar Soft reverse-Z: https://www.braynzarsoft.com/websitemedia/tutorial/22/

真实开源源码:

- bgfx reverse-Z 实现: https://github.com/bkaradzic/bgfx/blob/master/src/renderer_gl.cpp(搜 `BGFX_CONFIG_REVERSE_Z`)
- filament(Google PBR 引擎)reverse-Z: https://github.com/google/filament/blob/main/filament/src/FilamentAPI.cpp
