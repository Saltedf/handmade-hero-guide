# 投影矩阵完整推导

> 本文是 [day108.md](../day108.md) 的延伸,把透视投影和正交投影矩阵的所有公式从头推导一遍。如果你看了 Day 108 还想更深一层理解(OpenGL 投影矩阵每一项怎么来的、为什么 OpenGL NDC Z 是 [-1, 1] 而 Vulkan 是 [0, 1]、left-handed 和 right-handed 坐标系的差别),本文给你完整答案。本文自包含,但建议先读 Day 108 建立直觉。

## 1 · 为什么需要投影矩阵

3D 渲染的核心是「**把世界 3D 点映射到屏幕 2D 像素**」。这个映射有两步:**viewing transform**(相机怎么看)和 **projection transform**(怎么压扁)。我们今天讲 projection。

Projection 要做两件事:

1. **位置变换**:把世界 `(x, y, z)` 变到屏幕 `(sx, sy, depth)`。
2. **深度保留**:虽然位置压扁了,但深度 `z` 信息要保留(给深度缓冲用),否则无法做遮挡。

矩阵能编码这种变换,且 GPU 硬件原生支持 4×4 矩阵乘法(几千个顶点并行算)。所以投影矩阵是 3D 渲染的基础数据结构。

## 2 · 小孔成像物理模型

世界点 `P = (X, Y, Z)`,相机在原点看 `-z` 方向(OpenGL 约定)。在 `z = -d` 处放成像平面(d > 0,焦点距离)。P 在成像平面上的投影点 `(x', y', -d)` 必须满足「**和原点共线**」——光从 P 出发经过针孔(原点)打到成像平面。

共线条件:存在标量 `t`,使得 `(x', y', -d) = t × (X, Y, Z)`。从 z 分量:`-d = t·Z`,所以 `t = -d/Z`。代入 x, y:

```
x' = -d·X / Z
y' = -d·Y / Z
```

当 `Z < 0`(P 在相机前方,OpenGL 约定),`-Z > 0`,`x' = d·X / (-Z) = d·X / |Z|`。这就是透视投影的核心:**除以 Z**。

## 3 · 透视投影矩阵推导

### 3.1 设计目标

我们要构造一个 4×4 矩阵 `M`,使得 `M · (X, Y, Z, 1)^T` 后,w 除法的结果就是屏幕坐标。

具体说,`M · (X, Y, Z, 1)^T = (clip_x, clip_y, clip_z, clip_w)`。w 除法:`(clip_x/clip_w, clip_y/clip_w, clip_z/clip_w)` 应该等于 `(d·X/(-Z), d·Y/(-Z), depth_mapping(Z))`。

### 3.2 让 w = -Z

设置 `M` 最后一行为 `[0, 0, -1, 0]`,这样 `clip_w = 0·X + 0·Y + (-1)·Z + 0·1 = -Z`。这是矩阵化「除以 Z」的关键。

### 3.3 让 clip_x = d·X

`clip_x` 是矩阵第一行乘向量:`m00·X + m01·Y + m02·Z + m03·1`。我们想要 `clip_x/clip_w = d·X/(-Z)`,即 `clip_x = -d·X`。

简化矩阵第一行为 `[m00, 0, 0, 0]`,则 `clip_x = m00·X`。要 `clip_x = -d·X`,但 `-d·X / (-Z) = d·X/Z`(注意符号),其实想的是 `clip_x / clip_w = d·X/(-Z)`,代入 `clip_w = -Z`,得 `clip_x = d·X`。所以 `m00 = d`。

但 OpenGL 标准把 d 表达成 FOV 和 aspect 的函数:`d = 1 / tan(FOV/2)`,这样 m00 = `d / aspect`(x 方向额外除以 aspect 让屏幕宽高比正确)。

### 3.4 让 clip_y = d·Y

类似,`m11 = d`。y 方向不除 aspect(只有 x 除)。

### 3.5 深度映射 clip_z

这是最 tricky 的部分。我们希望 `clip_z / clip_w` 把 Z 从 `[near, far]`(都为负,OpenGL 约定)映射到 NDC Z `[-1, 1]`。

设 `clip_z = a·Z + b`,`clip_w = -Z`。要求:

```
当 Z = -near:(a·(-near) + b) / near = -1
当 Z = -far:(a·(-far) + b) / far = 1
```

展开:

```
-near·a + b = -near      ... (1)
-far·a + b = far         ... (2)
```

(2) - (1):`-far·a + near·a = far + near`,`a·(near - far) = far + near`,`a = (far + near) / (near - far) = -(far + near) / (far - near)`。

代回 (1):`b = -near + near·a = -near + near·(-(far+near)/(far-near))`。

化简 b:`b = -near·(far - near + far + near) / (far - near) = -near·(2·far) / (far - near) = -2·far·near / (far - near)`。

所以:

```
m22 = a = -(far + near) / (far - near)
m23 = b = -2·far·near / (far - near)
```

注意:OpenGL 用列优先存储,`m22` 在数组下标 [2][2] 或 flat [10],`m23` 在 [2][3] 或 flat [11]。

### 3.6 完整 OpenGL 投影矩阵

```
M = | d/aspect  0    0                          0                          |
    | 0         d    0                          0                          |
    | 0         0    -(far+near)/(far-near)     -2·far·near/(far-near)     |
    | 0         0    -1                         0                          |
```

其中 `d = 1 / tan(FOV_y / 2)`。

`glPerspective(fovy, aspect, near, far)` 老式 OpenGL 函数就是构造这个矩阵。Modern OpenGL 用 `glm::perspective`(C++)或 `glam::Mat4::perspective_rh_gl`(Rust)。

### 3.7 验证

代入具体数字:FOV=90°, aspect=1, near=1, far=100。

```
d = 1 / tan(45°) = 1
m00 = 1/1 = 1
m11 = 1
m22 = -(100+1)/(100-1) = -101/99 ≈ -1.0202
m23 = -2·100·1 / 99 = -200/99 ≈ -2.0202
m32 = -1
```

验证 Z = -1(near):clip_z = -1.0202·(-1) + (-2.0202) = 1.0202 - 2.0202 = -1。clip_w = -(-1) = 1。NDC_z = -1/1 = -1。✓

验证 Z = -100(far):clip_z = -1.0202·(-100) + (-2.0202) = 102.02 - 2.0202 ≈ 100。clip_w = 100。NDC_z = 100/100 = 1。✓

完美映射。

## 4 · 正交投影矩阵

正交投影**不除以 Z**——所有距离物体一样大。用于 2D 游戏、CAD、UI。

矩阵设计:w 分量始终 1(不被 Z 影响)。`M · (X, Y, Z, 1)^T = (X, Y, depth_mapping(Z), 1)`。w 除法除以 1,无效果。

```
M_ortho = | 2/(r-l)    0           0           -(r+l)/(r-l)   |
          | 0          2/(t-b)     0           -(t+b)/(t-b)   |
          | 0          0           -2/(f-n)    -(f+n)/(f-n)   |
          | 0          0           0           1                             |
```

其中 l, r, t, b, n, f 是 left / right / top / bottom / near / far 边界。矩阵把 [l, r]³ 立方体映射到 NDC [-1, 1]³。

`glm::ortho(left, right, bottom, top, near, far)` / `glam::Mat4::orthographic_rh_gl` 构造这个矩阵。

Casey HH Day 026-107 用的就是正交投影(虽然 Casey 不显式构造矩阵,而是直接 `(x, y) → (x, y)` 屏幕坐标)。Day 108 切到透视投影。

## 5 · 坐标系差异:LH vs RH

不同图形 API 用不同坐标系约定,这是初学者的常见困惑来源。

**Right-Handed(RH)**:OpenGL 约定。+X 右,+Y 上,+Z **朝向观察者(出屏幕)**。相机看 -Z 方向。世界深处 Z 是负的。

**Left-Handed(LH)**:DirectX 约定。+X 右,+Y 上,+Z **朝向远处(进屏幕)**。相机看 +Z 方向。世界深处 Z 是正的。

**Vulkan** 是混合:XY 同 RH,但 Y 翻转(NDC Y 朝下,匹配屏幕)。Z 范围 [0, 1] 而不是 [-1, 1]。

矩阵差异:

- RH 投影矩阵 m32(行 3 列 2)= -1(`clip_w = -Z`)。
- LH 投影矩阵 m32 = +1(`clip_w = +Z`)。
- Vulkan 投影矩阵额外翻转 Y(m11 = -d),且 m22, m23 把 Z 映射到 [0, 1] 而不是 [-1, 1]。

`glam` 提供多个变体:`perspective_rh_gl` / `perspective_lh` / `perspective_rh_vulkan` / `perspective_lh_dx`。Casey HH 用 OpenGL RH,所以 `perspective_rh_gl`。

## 6 · 实战:Rust 实现

完整 Rust 代码:

```rust
use glam::{Mat4, Vec3};

fn perspective_rh_gl(fov_y: f32, aspect: f32, near: f32, far: f32) -> Mat4 {
    let f = 1.0 / (fov_y / 2.0).tan();
    let nf = 1.0 / (near - far);
    Mat4::from_cols_array(&[
        f / aspect, 0.0, 0.0,                0.0,
        0.0,        f,   0.0,                0.0,
        0.0,        0.0, (far + near) * nf,  2.0 * far * near * nf,
        0.0,        0.0, -1.0,               0.0,
    ])
}

fn orthographic_rh_gl(left: f32, right: f32, bottom: f32, top: f32,
                      near: f32, far: f32) -> Mat4 {
    let rpl = right + left;
    let rml = right - left;
    let tpb = top + bottom;
    let tmb = top - bottom;
    let fpn = far + near;
    let fmn = far - near;
    Mat4::from_cols_array(&[
        2.0/rml,   0.0,      0.0,        0.0,
        0.0,       2.0/tmb,  0.0,        0.0,
        0.0,       0.0,      -2.0/fmn,   0.0,
        -rpl/rml,  -tpb/tmb, -fpn/fmn,   1.0,
    ])
}

// 测试
fn main() {
    let p = perspective_rh_gl(60.0_f32.to_radians(), 16.0/9.0, 0.1, 100.0);
    println!("perspective:\n{:?}", p);

    let o = orthographic_rh_gl(-10.0, 10.0, -5.0, 5.0, 0.1, 100.0);
    println!("orthographic:\n{:?}", o);

    // 验证:一个 z = -5 的点
    let v = Vec3::new(1.0, 1.0, -5.0);
    let clip_p = p * v.extend(1.0);
    let ndc = clip_p.truncate() / clip_p.w;
    println!("ndc for (1, 1, -5) under perspective: {:?}", ndc);
    // 期望 ndc.z 在 (-1, 1) 之间,因为 -5 在 near(-0.1) 和 far(-100) 之间
}
```

`glam::Mat4::from_cols_array` 把 16 个 f32 解释为列优先(column-major)4×4 矩阵。OpenGL / Vulkan 默认列优先;D3D 默认行优先。

## 7 · 调试技巧

投影矩阵写错时,常见症状:

**画面全黑**:near/far 范围错。比如 near=10, far=100,但所有 entity 都在 z=-5(在 near 平面之前,被裁掉)。调试:打印 mvp 矩阵,验证 m22, m23 公式。

**画面镜像**:RH/LH 混淆。比如用了 `perspective_lh` 但相机在 z=-5 看 -z 方向(应该是 RH)。调试:检查 camera view matrix 的方向。

**Depth buffer 失效**:Z 范围映射错。OpenGL NDC Z 是 [-1, 1],如果用了 Vulkan 矩阵(映射到 [0, 1]),depth buffer 写入值不对,遮挡错误。

**FOV 不对**:`tan(FOV/2)` 单位是弧度,如果你传角度没转弧度,FOV 错误。Casey HH 用弧度,代码里看到 `60.0_f32.to_radians()` 转换。

**Aspect 错**:水平拉伸或压扁。aspect 应该是 `width / height`。如果你写成 `height / width` 就反了。

## 8 · 历史演化

**1980 年代 SGI OpenGL**:固定管线 `glFrustum` / `glOrtho` 构造投影矩阵,内部用硬件做 w 除法。

**2000 年代可编程 shader**:OpenGL 3.0+ 移除固定管线,投影矩阵在 vertex shader 里手算 `gl_Position = proj * view * model * vec4(pos, 1.0)`。

**2010 年代 Vulkan / D3D12**:显式 pipeline state,投影矩阵完全由应用构造,GPU 只负责执行。

**2020 年代 wgpu / WebGPU**:跨平台抽象,Rust 主流。投影矩阵在 WGSL shader 里应用,API 一致。

每一次升级都让投影矩阵更「**显式**」——开发者完全掌控。Casey HH 在 CPU 软渲染上手写,让你理解每一次升级背后的不变内核。

## 9 · 延伸阅读

- [Song Ho Ahn's Projection Matrix Derivation](https://www.songho.ca/opengl/gl_projectionmatrix.html) — 业界最经典的推导文档,有图有公式。
- [LearnOpenGL Camera](https://learnopengl.com/Getting-started/Camera) — view + projection 完整教程。
- [Scratchapixel Perspective and Orthographic Projection Matrix](https://www.scratchapixel.com/lessons/3d-basic-rendering/perspective-and-orthographic-projection-matrix.html) — 从零推导。
- [OGLdev OpenGL Projection Matrix](https://www.ogldev.org/www/tutorial12/tutorial12.html) — 老牌 OpenGL 教程。
- [glm source code](https://github.com/g-truc/glm/blob/master/glm/ext/matrix_clip_space.inl) — C++ GLM 库的投影矩阵实现,和本文 Rust 版完全对应。
- [glam source code](https://github.com/bitshifter/glam/blob/main/src/mat4.rs) — Rust glam 库实现。
