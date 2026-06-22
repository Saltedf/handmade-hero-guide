# 阴影映射:从 1978 年 Williams 到 PCF / VSM / CSM 工业级管线

> 光照模型告诉你"光从哪里来、表面怎么反射",但有一个关键问题没回答:**这个片段能不能被光照亮?** 如果光源和片段之间有遮挡物,这个片段就在阴影里——光照公式算出再亮的颜色,也应该是黑的。**阴影映射**(shadow mapping)用两次渲染解决这个问题:第一次从光源视角画深度图,第二次从相机视角拿每个片段问"光能看到我吗"。本文从 1978 年 Lance Williams 的原始论文讲到工业级 PCF + CSM,涵盖阴影痤疮、彼得潘效应、光渗漏等真实 bug 的根因和修复,让你能写出和 Unreal / Unity / Godot / Bevy 同级的阴影系统。

## 0 · 为什么要有阴影映射

把一个 3D 模型放到场景里,打开灯。光照模型算出每个像素的反射颜色——但**所有像素都被照亮了**,连柱子背后、桌子底下、角色脚下的位置都亮着。视觉上场景"漂"在地面之上,没有立体感,没有空间深度。

心理学家 Loomis 1950 年代做过实验:把一个球的照片去掉所有阴影,人判断不出球离地多高;加回阴影,瞬间准确。**阴影是空间关系最直接的视觉线索**——它告诉你"这个物体和地面接触在哪、距地面多远、面对光源的是哪一面"。

阴影算法分两大流派:

1. **几何方法**(shadow volume / stencil shadow):用物体几何算精确的"阴影体",CPU 准备复杂。Doom 3 用这个,惊艳一时但工程太重,现在很少用
2. **图像方法**(shadow mapping):从光源视角渲染一张深度图,主相机视角渲染时查询这张深度图。GPU 友好,工程简单,但有精度和锯齿问题

工业界 99% 用图像方法,即**阴影映射**。它的核心思想极其简单:**渲染场景两次**——第一次从光源视角(画深度),第二次从相机视角(用第一次的深度做遮挡测试)。这一思路 1978 年 Lance Williams 在 ACM 论文里首次提出,40 多年来工业界做了无数改进:PCF 软阴影(1987)、VSM 方差阴影(2006)、CSM 级联阴影(2006)、SDSM 自动调参(2010)、Ray-traced shadows(2018+ RTX 时代)。今天我们把这些都讲到。

**读完这一篇你能**:

- 用 Rust + glow(OpenGL) 实现完整 shadow map 管线
- 解释 shadow acne(阴影痤疮)和 Peter Panning(彼得潘效应)为什么是相反问题
- 用 PCF 实现软阴影边缘,用 VSM 实现一次性采样的快阴影
- 配置 CSM 让 1km 视距也有清晰阴影(游戏工业标配)
- 知道 reverse-Z(reversed depth bias)如何在大场景中避免 acne
- 看 Unreal / Unity / Godot / Bevy 的阴影代码不被吓到

## 1 · 原始 Shadow Map 算法(Williams 1978)

### 1.1 两遍渲染流程

**第一遍:从光源视角渲染**。

如果光源是方向光(像太阳,光平行射来),光源视角是一个"无限远"的正交相机。如果是点光源(灯泡,光向四面八方),需要 cubemap——6 个方向各渲染一次。这里先讲方向光,简单。

```rust
// 第一遍
let light_view_proj: Mat4 = compute_light_view_proj(light_dir, scene_bounds);
// 渲染场景,只画深度到 shadow_map(一张专门的深度纹理)
render_scene_depth_only(&light_view_proj, &mut shadow_map);
// 不画颜色,只画深度——这是 shadow map 的精髓
```

`shadow_map` 是一张深度纹理(通常 2048×2048,24 位整数深度)。它存的是"从光源看出去,每个方向的最近物体距离"。

**第二遍:从相机视角渲染,做阴影测试**。

```rust
// 第二遍
for fragment in scene {
    let world_pos = fragment.world_pos;
    // 把世界坐标用 light_view_proj 变到光源的 NDC 空间
    let light_space_pos = light_view_proj * world_pos;
    
    // 光源空间深度(z 在 [0, 1] 范围,OpenGL convention)
    let current_depth = light_space_pos.z * 0.5 + 0.5;
    
    // 从 shadow map 采样这一位置的深度
    let shadow_map_depth = sample(shadow_map, light_space_pos.xy * 0.5 + 0.5);
    
    // 测试:这个片段是不是被遮挡?
    // 如果片段深度 > shadow_map 深度,说明"光看不到它",它在阴影里
    let in_shadow = current_depth > shadow_map_depth + bias;
    
    let light_factor = if in_shadow { 0.0 } else { 1.0 };
    // 把 light_factor 乘到光照公式上
    let color = lit_color * light_factor;
}
```

### 1.2 直觉:为什么这样能算阴影?

光源视角下,看到的最近深度 = "光能照到的最近物体表面"。如果你当前片段的深度**大于**这个值,说明光源和它之间有别的物体挡着——它在阴影里。

简单画图:

```
       光源(方向光,箭头方向)
        ↓↓↓↓↓↓↓↓↓↓
        ┌────柱子────┐
        ↓            ↓
        ↓            ↓
   ─────┴────────────┴─────地面─────
        A            B
                     C  (柱子背后地面)
```

- 地面 A、B 处:从光源视角看,深度就是地面距离,**不被遮挡**,亮。
- 地面 C 处:从光源视角看,深度是柱子顶部的距离(柱子挡在前),但 C 的实际深度是地面距离(更远)。`current > shadow_map_depth + bias` → 在阴影里。

shadow map 算法的优雅之处:**只渲染深度,不渲染颜色**,所以第一遍极快(GPU 只跑 vertex shader + early-z)。第二遍查询就是一次纹理采样,也快。所以工业界都用它。

### 1.3 为什么不需要存"哪个物体挡住"?

一个经典疑问:shadow map 只存了"光看到的最近深度",没存"是哪个物体"。这够吗?

够了。因为我们问的问题是"光能不能照到这个片段",不是"哪个物体挡住光"。**最近深度 < 片段深度 ⟺ 有东西挡着**——什么物体挡的不重要。这个简化让 shadow map 极轻量。

## 2 · 经典 Bug:Shadow Acne(阴影痤疮)

### 2.1 现象

第一次跑 shadow map,你看到阴影区域充满条纹状的"花纹"——亮暗交替,像被砂纸磨过。这叫 **shadow acne**(阴影痤疮)。条纹是规则的正弦曲线,出现在所有面向光源的平面上。

### 2.2 根因

shadow map 是一张低分辨率纹理(2048×2048),每个 texel 覆盖场景中的一块区域(假设场景是 100m × 100m,每 texel 覆盖 5cm × 5cm)。主相机渲染时,一个片段投影到 shadow map 上,可能落在某个 texel 的中心,也可能落在边缘。

这个 texel 存的深度是"该 texel 覆盖区域的某个代表深度"(实际上是该区域内**最近**的几何)。但片段的真实深度可能略大或略小——结果是同一个表面上,有的片段被测试为"遮挡"(acne),有的不被测试为遮挡。

ASCII 图:

```
shadow map 视角下,每个 texel 覆盖场景的一块:
        ↓
┌──┬──┬──┬──┬──┐
│ T0│ T1│ T2│ T3│ T4│   ← texel 网格,每 texel 存一个深度
└──┴──┴──┴──┴──┘
真实表面是斜的:
   /
  /
 /
/
阴影测试:从主相机看到的片段 P,在 texel T2 上。
T2 存的深度是它覆盖区域的最近深度,而 P 的实际深度略大于这个值(因为斜面),
所以 P 被判为"遮挡"——但 P 实际就在表面上,没被遮挡!
```

这种"角度差"导致的虚假阴影就是 acne。

### 2.3 解决 1:加 Bias(偏移)

最直接的修复:加一个偏移让测试更宽松。

```glsl
float bias = 0.005;
bool in_shadow = current_depth > shadow_map_depth + bias;
```

bias 让阴影"往后退一点",把片段的"测试深度"调小,只要 acne 引起的偏差小于 bias,acne 就消失。

但 bias 太大会引入另一个问题:**Peter Panning**(彼得潘效应)——物体看起来"飘"在地面上,因为接触面的阴影也被 bias 推掉了(下面 §3 讲)。

### 2.4 解决 2:正面剔除(Front-face Culling)

更聪明的做法:**渲染 shadow map 时剔除正面三角形,只渲染背面**。这样 shadow map 存的是"背面的深度",永远比正面深——主相机看到的正面片段深度永远小于 shadow map 深度,自动消除 acne。

```rust
// 第一遍
unsafe {
    gl.enable(glow::CULL_FACE);
    gl.cull_face(glow::FRONT);  // 剔除正面,只渲染背面
    render_scene_depth_only(&light_view_proj, &mut shadow_map);
    gl.cull_face(glow::BACK);   // 恢复
}
```

代价:薄物体(单片叶子、布料)可能完全被剔除,导致没阴影——两面都被剔了。所以工业实践是**正面剔除 + 适度 bias**,两者配合。

### 2.5 解决 3:反向 Z(reversed depth)

更现代的方案:用 **reverse-Z**——把 near 设很远(或 far 设很近),让深度精度分布对场景有利。这本身不直接解决 acne,但让 bias 数值更可控。Casey HH 没用 reverse-Z(他软渲染,自己控制),但 wgpu / OpenGL 后端你写 shadow map 时强烈推荐。

## 3 · 经典 Bug:Peter Panning(彼得潘效应)

### 3.1 现象

加了大 bias 后,acne 消失了——但物体看起来"飘"在地面上。物体和地面的接触面没有阴影,像是物体被钉子撑起来。这就是 Peter Panning(彼得潘效应)——名字来自童话里彼得潘飞起来时影子分离的画面。

### 3.2 根因

物体和地面的接触面是阴影的"起点"——物体底部刚好接触地面,这里应该是阴影最浓的地方。但 bias 把测试推后了,接触面被算成"不在阴影里",所以接触区域是亮的——视觉上物体像被撑起来,没接触地面。

### 3.3 解决

- **减小 bias**:acne 和 Peter Panning 互为相反问题,bias 找平衡点
- **避免薄物体**:物体必须有体积,这样正面剔除不会让整个物体消失
- **用更精确的 bias**:不同表面斜率需要不同 bias。Slope-scaled bias:`bias = constant_bias + slope_scale * tan(θ)`,θ 是表面法线和光源的夹角。OpenGL `glPolygonOffset` 内建支持这个

```glsl
// slope-scaled bias
float slope = 1.0 - dot(N, L);  // 表面和光源的反夹角余弦
float bias = 0.005 + 0.05 * slope;
```

这是工业级 shadow map 的标配。

## 4 · 经典 Bug:硬边缘锯齿

### 4.1 现象

阴影边缘是黑白二值(在阴影 / 不在阴影),看起来像剪纸,边缘锯齿明显。真实阴影边缘是软的——这是物理上半影(penumbra)现象:光源有面积,边缘附近的点部分被照亮、部分被遮挡,产生平滑过渡。

### 4.2 PCF:Percentage-Closer Filtering

最简单的软阴影:**采样多次,平均结果**。1987 年 Reeves 等人在 Pixar 提出。

```glsl
float shadow = 0.0;
vec2 texel_size = 1.0 / textureSize(shadow_map, 0);
for (int x = -1; x <= 1; x++) {
    for (int y = -1; y <= 1; y++) {
        float pcf_depth = texture(
            shadow_map,
            uv + vec2(x, y) * texel_size
        ).r;
        shadow += current_depth - bias > pcf_depth ? 0.0 : 1.0;
    }
}
shadow /= 9.0;
```

每行注释:

- `texel_size` = 1 / shadow_map 大小,表示一个 texel 在 UV 空间的尺寸
- 3×3 邻域采样,每个采样返回 0 或 1(被遮挡或没被),平均得 0.0 ~ 1.0 的软阴影值
- 9 次采样让边缘从硬变软

工业级 PCF 用更大核(5×5、7×7)或泊松圆盘采样(Poisson disk sampling,32 个随机方向),边缘更软且性能可控。

### 4.3 PCF 的代价

每个片段 9~49 次纹理采样,在 1080p 上是 200~1000 万次 fragment 计算,即使 GPU 也有压力。优化:

- **早出**(early-out):如果片段明显在阴影深处(NDC 边界外、shadow map 外),直接返回 0.0,跳过 PCF
- **预设过滤**(pre-filtered shadow map):预先在 GPU 上把 shadow map 模糊一次,主 shader 只采样一次——但简单模糊会破坏正确性,需要 PCF 的特殊变种
- **VSM**(下一节):用统计量预计算,运行时一次采样

## 5 · VSM:Variance Shadow Maps

PCF 每个片段要多次采样,昂贵。**VSM**(Variance Shadow Map,Donnelly & Lauritzen 2006)的想法:**预计算 shadow map 的统计量(均值 + 方差),用切比雪夫上界不等式一次性估算遮挡概率**。

### 5.1 算法

**第一遍**渲染时,不只存深度 `d`,还存深度² `d²`。两张纹理:

- `depth_mip` — 存 depth,并生成 mipmap(每级 mipmap 是上一级的均值)
- `depth_sq_mip` — 存 depth²,并生成 mipmap

**第二遍**测试时:

```glsl
// 一次采样,拿到均值
float depth_mean = texture(depth_mip, uv).r;
float depth_sq_mean = texture(depth_sq_mip, uv).r;

// 方差 = E[X²] - E[X]²
float variance = depth_sq_mean - depth_mean * depth_mean;
variance = max(variance, 0.00001);  // 防数值噪声(数值不稳定时方差可能为负)

// 切比雪夫上界:深度 > current 的概率
float d = current_depth;
float t;
if (depth_mean > d) {
    t = 0.0;  // 均值比 current 大,说明光被完全挡住,直接 0(其实这里有更细的逻辑)
} else {
    // 切比雪夫上界不等式:P(X ≥ t) ≤ σ²/(σ² + (t-μ)²)
    t = variance / (variance + (d - depth_mean) * (d - depth_mean));
}

float shadow = 1.0 - t;
```

每行解释:

- 切比雪夫不等式告诉概率上界——"深度大于当前片段的概率"上界是 σ²/(σ²+(d-μ)²)
- 这是个统计近似,只需一次纹理采样(每级 mipmap)
- mipmap 自带"模糊",所以 VSM 的阴影边缘天然软

### 5.2 VSM 优势

- **极快**:一次纹理采样,不像 PCF 要 9~49 次
- **天然软阴影**:mipmap 提供了不同程度的"模糊",边缘柔和
- **支持 mipmap**:大场景下远处自动用粗 mipmap,精度自适应

### 5.3 VSM 劣势:Light Bleeding(光渗漏)

**问题**:两个遮挡物重叠时,统计量失真,边缘出现亮带。具体说:物体 A 阴影里有物体 B,B 的阴影本应该完全黑,但 VSM 算出来 B 的阴影中间有一道亮——因为方差被 A 和 B 共同贡献,公式给出错误的"概率"。

**修复变种**:

- **LVSM**(Layered VSM):把深度分多层,每层独立算 VSM
- **EVSM**(Exponential VSM):用指数函数代替深度,精度更高,光渗漏更少
- **MSM**(Moment Shadow Maps):用 4 阶矩代替 1 阶矩(均值)和 2 阶矩(方差),精度更高

工业界主流仍是 PCF(简单可靠)。VSM 适合特殊场景(如 VR 需要少采样)。

## 6 · CSM:Cascaded Shadow Maps

### 6.1 问题:大场景下的精度

一张 2048×2048 的 shadow map 覆盖 1km × 1km 的场景——每 texel 代表 0.5m,远处物体阴影全是锯齿。但用更大 shadow map(8192×8192)爆显存(8K 纹理 × 4 bytes = 64MB),且 GPU 采样慢。

**核心矛盾**:玩家附近需要高精度阴影(看清楚脚下金币的阴影),远处只需要低精度(远处的山影模糊也无所谓)。但单一 shadow map 精度均匀——浪费远处的精度,又不够近处的精度。

### 6.2 CSM 解决方案

**把视锥分成多段(级联)**,每段用独立的 shadow map。近段覆盖小区域(精度高),远段覆盖大区域(精度低)。

```
Cascade 0: 0~10m,    shadow map 2048×2048,精度 0.5cm/texel  (玩家附近)
Cascade 1: 10~50m,   shadow map 2048×2048,精度 2.5cm/texel
Cascade 2: 50~200m,  shadow map 2048×2048,精度 10cm/texel
Cascade 3: 200~1000m,shadow map 2048×2048,精度 50cm/texel   (远景)
```

shader 根据片段的相机空间深度,选择对应级联的 shadow map 做测试。

### 6.3 实现

```glsl
// 顶点 shader:把片段的 view_depth 传给片段
in float v_view_depth;

// 片段 shader:
uniform sampler2DArray shadow_cascades;  // 4 张 shadow map 用数组纹理
uniform vec4 cascade_endpoints;          // 每级 cascade 的远端距离
uniform mat4 light_view_proj[4];         // 每级 cascade 有独立 light_view_proj

void main() {
    int cascade_idx = 0;
    if (v_view_depth < cascade_endpoints.x) cascade_idx = 0;
    else if (v_view_depth < cascade_endpoints.y) cascade_idx = 1;
    else if (v_view_depth < cascade_endpoints.z) cascade_idx = 2;
    else cascade_idx = 3;
    
    // 选对应级联的 light_view_proj
    vec4 light_space_pos = light_view_proj[cascade_idx] * vec4(world_pos, 1.0);
    // 透视除法 + NDC 到 [0, 1]
    vec3 proj_coords = light_space_pos.xyz / light_space_pos.w;
    proj_coords = proj_coords * 0.5 + 0.5;
    
    // 用 sampler2DArray 采样对应层
    float shadow_map_depth = texture(
        shadow_cascades,
        vec3(proj_coords.xy, float(cascade_idx))
    ).r;
    
    // 测试 + PCF
    float shadow = current_depth > shadow_map_depth + bias ? 0.0 : 1.0;
    // ...
}
```

### 6.4 级联间接缝

不同级联的 shadow map 在拼接处可能有可见接缝(精度不同导致阴影密度不同)。工业做法:

- **blend zone**:在级联边界 5~10% 范围内,线性插值两个级联的阴影值
- **PCF 跨级联**:在边界附近用两个级联都做 PCF,平均

```glsl
// blend zone 处理
float cascade_blend = 0.1;  // 边界附近 10% blend
float dist_to_boundary = ...;  // 当前片段到级联边界的距离
if (dist_to_boundary < cascade_blend) {
    float t = dist_to_boundary / cascade_blend;
    float shadow_a = sample_cascade(cascade_idx, ...);
    float shadow_b = sample_cascade(cascade_idx + 1, ...);
    shadow = mix(shadow_a, shadow_b, t);
}
```

### 6.5 SDSM:Sample Distribution Shadow Maps

CSM 的级联边界是手工调的。**SDSM**(2010)用 GPU 反馈循环:每帧统计上一帧的实际深度分布,自动调整级联边界紧贴场景。这是工业级 CSM 的现代做法,Unreal Engine 4 默认开。

## 7 · Cube Shadow Map:点光源

点光源向所有方向发光,需要 cubemap(6 个面的纹理)做 shadow map。

```rust
// 6 个面的 view matrix
let faces = [
    Mat4::look_at_rh(light_pos, light_pos + Vec3::X,  Vec3::Y),  // +X
    Mat4::look_at_rh(light_pos, light_pos - Vec3::X,  Vec3::Y),  // -X
    Mat4::look_at_rh(light_pos, light_pos + Vec3::Y,  -Vec3::Z), // +Y(注意 up)
    Mat4::look_at_rh(light_pos, light_pos - Vec3::Y,  Vec3::Z),  // -Y
    Mat4::look_at_rh(light_pos, light_pos + Vec3::Z,  Vec3::Y),  // +Z
    Mat4::look_at_rh(light_pos, light_pos - Vec3::Z,  Vec3::Y),  // -Z
];
// 透视投影,90 度 FOV
let proj = Mat4::perspective_rh(90.0_f32.to_radians(), 1.0, 0.1, 100.0);
```

第一遍:6 次渲染,每个面朝向 ±X、±Y、±Z。或者**几何着色器**一次性渲染 6 面(OpenGL `gl_Layer`)。第二遍:从片段到光源的方向采样 cubemap,得到该方向最近深度。

OpenGL 用 `GL_TEXTURE_CUBE_MAP`,Vulkan 用 `VK_IMAGE_CREATE_CUBE_COMPATIBLE_BIT`,wgpu 用 `TextureViewDimension::Cube`.

## 8 · Rust + glow 完整实现

`glow` 是 Rust 跨平台 OpenGL 包装(OpenGL 3.3 / OpenGL ES 3.0 / WebGL 2)。下面是一个完整 shadow map 管线骨架。

```rust
// shadow_map.rs
use glow::*;
use glam::*;

pub struct ShadowMap {
    pub texture: glow::Texture,
    pub framebuffer: glow::Framebuffer,
    pub light_view_proj: Mat4,
    pub size: u32,
}

impl ShadowMap {
    pub fn new(gl: &Context, size: u32) -> Self {
        unsafe {
            let texture = gl.create_texture().unwrap();
            gl.bind_texture(TEXTURE_2D, Some(texture));
            gl.tex_image_2d(
                TEXTURE_2D, 0, DEPTH_COMPONENT24 as i32,
                size as i32, size as i32, 0,
                DEPTH_COMPONENT, UNSIGNED_INT, None,
            );
            // 关键 sampler 参数:不用 mipmap、CLAMP_TO_BORDER 防边界
            gl.tex_parameter_i32(TEXTURE_2D, TEXTURE_MIN_FILTER, LINEAR as i32);
            gl.tex_parameter_i32(TEXTURE_2D, TEXTURE_MAG_FILTER, LINEAR as i32);
            gl.tex_parameter_i32(TEXTURE_2D, TEXTURE_WRAP_S, CLAMP_TO_BORDER as i32);
            gl.tex_parameter_i32(TEXTURE_2D, TEXTURE_WRAP_T, CLAMP_TO_BORDER as i32);
            // 边界外采样返回 1.0(深度最大 = 不在阴影里)
            let border = [1.0, 1.0, 1.0, 1.0];
            gl.tex_parameter_f32_slice(
                TEXTURE_2D, TEXTURE_BORDER_COLOR, &border,
            );

            let framebuffer = gl.create_framebuffer().unwrap();
            gl.bind_framebuffer(FRAMEBUFFER, Some(framebuffer));
            gl.framebuffer_texture_2d(
                FRAMEBUFFER, DEPTH_ATTACHMENT,
                TEXTURE_2D, Some(texture), 0,
            );
            // 不画颜色,只画深度
            gl.draw_buffers(&[NONE]);
            gl.read_buffer(NONE);

            Self {
                texture, framebuffer,
                light_view_proj: Mat4::IDENTITY,
                size,
            }
        }
    }

    /// 计算方向光的 light_view_proj
    /// 正交投影贴合场景包围盒(tight frustum,提高精度)
    pub fn compute_light_view_proj(
        light_dir: Vec3,
        scene_bounds: AABB,
    ) -> Mat4 {
        // 光源位置 = 场景中心 - 光方向 * 场景半径
        // (足够远,保证正交投影下整个场景在 frustum 内)
        let light_pos = scene_bounds.center() - light_dir * scene_bounds.radius();
        let view = Mat4::look_at_rh(light_pos, scene_bounds.center(), Vec3::Y);
        // 正交投影:对称,半径 = 场景半径(简化;工业级用 tight frustum)
        let proj = Mat4::orthographic_rh(
            -scene_bounds.radius(), scene_bounds.radius(),
            -scene_bounds.radius(), scene_bounds.radius(),
            -scene_bounds.radius(), scene_bounds.radius(),
        );
        proj * view
    }
}

/// 一个简单的 AABB,用于场景包围
pub struct AABB {
    pub center: Vec3,
    pub radius: f32,
}
impl AABB {
    fn center(&self) -> Vec3 { self.center }
    fn radius(&self) -> f32 { self.radius }
}
```

每行注释:

- `DEPTH_COMPONENT24` — 24 位整数深度,够 shadow map 用(16 位精度差,32 位浪费)
- `CLAMP_TO_BORDER` + border = 1.0 — shadow map UV 超出 [0, 1] 时返回深度 1.0(最远),视为"不在阴影里"
- `look_at_rh` — RH(right-handed)是 OpenGL/Vulkan 标准
- `orthographic_rh` — 正交投影(方向光);点光源用透视投影
- `tight frustum` 是核心优化:不是固定 ±radius,而是计算实际可见场景在光源视角下的 bounding box——精度最大化

## 9 · 完整 GLSL Fragment Shader(PCF 3×3)

```glsl
#version 330 core

in vec3 v_world_pos;
in vec3 v_world_normal;
in vec2 v_uv;

out vec4 frag_color;

uniform vec3 u_cam_pos;
uniform vec3 u_light_dir;        // 方向光,单位向量,光的传播方向
uniform vec3 u_light_color;
uniform mat4 u_light_view_proj;
uniform sampler2D u_shadow_map;
uniform sampler2D u_albedo;
uniform float u_bias;            // 通常 0.001~0.01

void main() {
    vec3 N = normalize(v_world_normal);
    vec3 L = normalize(-u_light_dir);  // 方向光反向 = 指向光源
    vec3 V = normalize(u_cam_pos - v_world_pos);

    // Lambert 光照(简化;真实游戏用 PBR)
    vec3 albedo = texture(u_albedo, v_uv).rgb;
    float cos_theta = max(dot(N, L), 0.0);
    vec3 lit_color = albedo * u_light_color * cos_theta;

    // 阴影:世界 → 光源 NDC
    vec4 light_space = u_light_view_proj * vec4(v_world_pos, 1.0);
    vec3 proj_coords = light_space.xyz / light_space.w;
    proj_coords = proj_coords * 0.5 + 0.5;  // NDC [-1,1] → [0,1]

    float current_depth = proj_coords.z;

    // PCF 3×3:9 次采样平均
    float shadow = 0.0;
    vec2 texel_size = 1.0 / textureSize(u_shadow_map, 0);
    for (int x = -1; x <= 1; x++) {
        for (int y = -1; y <= 1; y++) {
            float pcf_depth = texture(
                u_shadow_map,
                proj_coords.xy + vec2(x, y) * texel_size
            ).r;
            shadow += (current_depth - u_bias > pcf_depth) ? 0.0 : 1.0;
        }
    }
    shadow /= 9.0;

    // 超出 shadow map 远平面:不在阴影里(否则远处一片黑)
    if (proj_coords.z > 1.0) shadow = 1.0;
    // shadow map 范围外:不在阴影里
    if (proj_coords.x < 0.0 || proj_coords.x > 1.0 ||
        proj_coords.y < 0.0 || proj_coords.y > 1.0) shadow = 1.0;

    vec3 final = lit_color * shadow;
    frag_color = vec4(final, 1.0);
}
```

每段注释:

- `proj_coords.xyz / proj_coords.w` — 透视除法,NDC 空间
- `* 0.5 + 0.5` — 把 NDC [-1, 1] 映射到 [0, 1] 供纹理采样
- `current_depth - u_bias` — shadow acne 偏移
- `proj_coords.z > 1.0 → shadow = 1.0` — 超出 shadow map 远平面的不在阴影里
- `proj_coords.x/y` 范围检查 — shadow map 边界外,CLAMP_TO_BORDER 已经处理,但显式 check 更稳

## 10 · 引擎对比

主流游戏引擎的 shadow map 管线大同小异,差异在工程优化和细节。

### Unreal Engine 5

- **CSM**:默认 4 级级联,可配置到 8 级
- **SDSM**:统计动态级联分布(自动调参)
- **PCF + 5×5 kernel**:默认软阴影
- **Ray-traced shadows**:Lumen 系统在 RTX 显卡上自动启用,光线追踪求交替代 shadow map 测试,锐利无限细节
- **Modular shadows**:每个光源独立 shadow map,支持点光源 cubemap

### Unity HDRP(高清晰度渲染管线)

- **CSM**:方向光 4 级级联
- **PCF / VSM**:可切换
- **Contact shadows**:屏幕空间 ray-marched 阴影,物体接触面附近的精细阴影(避免 Peter Panning)
- **Shadow mask**:静态物体烘焙到 lightmap,动态物体用 shadow map,合并

### Godot 4

- **CSM**:方向光 4 级
- **PCF**:可调 kernel 大小
- **VSM** 实验:Godot 4.x 在尝试 VSM
- **SDF Shadows**:用 signed distance field 而不是 depth texture(性能更好,但准备阶段复杂)

### Bevy(bevy_pbr crate)

- **CSM**:方向光,可配置级联数
- **PCF**:默认 5×5
- **Point light shadows**:cubemap
- **Spot light shadows**:单张 depth texture(透视投影)
- **设计哲学**:模块化,每个光源类型独立 system,容易扩展

## 11 · 历史

- **1978** — Lance Williams "Casting Curved Shadows on Curved Surfaces",首次提出 shadow map 概念。论文只有 5 页,但奠定 40 年的研究方向
- **1987** — Reeves et al. "Rendering Antialiased Shadows Using Depth Maps",提出 PCF
- **1990s** — OpenGL / Direct3D 把 depth texture 标准化,shadow map 成主流
- **2006** — Donnelly & Lauritzen VSM;Engel & Dimitrov CSM,同年提出
- **2010** — Lauritzen 等 SDSM,自动调级联分布
- **2014** — Unreal Engine 4 默认 CSM + PCF
- **2018** — NVIDIA RTX,实时光线追踪阴影
- **2020+** — DLSS / SSR + RT shadows 混合方案

## 12 · 关联 Day

- **铺垫**:Day 261 深度缓冲原理;Day 280 光照;Day 290 投影矩阵;本仓库 `days/phase-6/deep-dives/lighting-models.md` Lambert / Phong / PBR BRDF
- **当天**:本篇是 shadow map 专题(Phase 6 光照延伸)
- **后续**:Day 440+ CSM 实战;Day 480+ 延迟着色 + 多光源阴影;Day 500+ ray-traced shadows 实验

## 13 · 变式训练

### Lv1 · 概念辨析

**题**:Shadow acne 和 Peter Panning 互为相反问题——解释为什么 bias 太小造成前者,bias 太大造成后者。

**参考解答**:

- **bias 太小**:shadow map 精度限制导致同一表面上相邻片段在 shadow map 上深度有微小差异,有的片段被测试为"遮挡",有的"不遮挡",产生条纹(acne)。
- **bias 太大**:把片段的测试深度推到比实际位置更远——结果连"接触地面的物体"也在阴影测试中失败(因为地面深度 + bias 已经超出物体深度),物体与地面之间的阴影消失,物体看起来"飘"在地面上(Peter Panning)。

两者互为相反:bias 太小,虚假阴影(本应不在阴影里却判为在);bias 太大,缺失阴影(本应在阴影里却判为不在)。工业级方案:slope-scaled bias + front-face culling,自动平衡。

### Lv2 · 动手实践

**题**:在你的渲染器里加 shadow map。要求:

1. 方向光光源
2. PCF 3×3 软阴影
3. bias 可通过 uniform 调整
4. 立方体在地面上投下阴影

完成标准:立方体在地面上有清晰的阴影,阴影边缘软,无明显 acne。

**参考解答**:三步走——

1. 实现 shadow map FBO(深度纹理,24 位)
2. 第二遍渲染,把 light_view_proj 传给 shader
3. PCF 在 fragment shader 里做(见 §9 的 GLSL)

排查:

- 阴影全黑:bias 太大,把所有片段推到阴影里
- 没阴影:light_view_proj 算错,或 shadow map 没正确绑定到 sampler
- acne:bias 不够,或没用 cull_face(FRONT)

### Lv3 · 迁移设计

**题**:声音也有"遮挡"——墙挡住声音时,墙后有"声影区"(acoustic shadow)。类比 shadow map,设计一个简化的声影计算。

**提示**:声波不像光,会绕射(diffraction)——这是 shadow map 没有的特性。你的设计要不要考虑绕射?如果简化忽略绕射,声影区和光阴影几何上几乎一样——只是声源通常是点声源,用 cubemap shadow map。如果考虑绕射,shadow map 还要存"边缘的相位",复杂得多。

**思考方向**:UEFN、Wwise 等音频中间件用的就是"shadow map" 思路——从声源 cubemap 渲染"可见度",每帧或预计算。绕射用 Huygens-Fresnel 原理近似。

### Lv4 · 开源贡献

**题**:Bevy 的 PBR 阴影,GitHub: https://github.com/bevyengine/bevy

1. clone 它:

   ```bash
   gh repo clone bevyengine/bevy
   cd bevy
   ```

2. 看 PBR 阴影代码:

   ```bash
   cd crates/bevy_pbr/src/render
   grep -l "shadow" *.rs
   # 重点关注 light.rs, shadow.rs, mesh.rs
   ```

3. 读 CSM 实现,找它的级联边界计算逻辑

4. 可能贡献方向:

   - 文档:CSM 的级联 blend zone 没文档,加 doc comment 解释参数语义
   - 测试:某个边缘 case 没测试覆盖(如 cascade 数 = 1 的退化情况)
   - 性能 profile:用 `cargo flamegraph` 看 shadow map 渲染瓶颈
   - Bug 复现:GitHub issue 找一个 "shadow" 标签的未解决 issue,本地复现

5. PR 描述草稿:

   - 标题(`docs:` / `test:` / `fix:` / `perf:` 前缀)
   - 改动文件
   - 动机(为 Bevy 用户带来什么)
   - 验证(`cargo test -p bevy_pbr` 输出)

**示例**(不要照抄):

```
PR 标题:docs: clarify CSM cascade blend zone in DirectionalLight docs
文件:crates/bevy_pbr/src/light/directional.rs
动机:DirectionalLight 的 shadow_settings 字段没说明 cascade blend zone 单位。
     用户调参时困惑——是 0..1 还是米?
     加一段 doc comment 解释 + 给个推荐值范围。
验证:cargo doc -p bevy_pbr --open,确认渲染正确。
```

## 14 · Rust / Arch 落地代码

完整 shadow map 管线骨架:

```rust
// 1. 初始化 shadow map
let shadow_map = ShadowMap::new(&gl, 2048);

// 2. 主循环
loop {
    // 第一遍:从光源视角渲染场景深度
    shadow_map.light_view_proj = ShadowMap::compute_light_view_proj(
        light_dir, scene_aabb,
    );
    unsafe {
        gl.bind_framebuffer(FRAMEBUFFER, Some(shadow_map.framebuffer));
        gl.viewport(0, 0, shadow_map.size as i32, shadow_map.size as i32);
        gl.clear(DEPTH_BUFFER_BIT);
        gl.enable(CULL_FACE);
        gl.cull_face(FRONT);  // 只画背面,消除 acne
        gl.color_mask(false, false, false, false);  // 不画颜色,有些 GPU 这能加速
        render_scene(&shadow_map.light_view_proj, &shadow_shader);
        gl.color_mask(true, true, true, true);
        gl.cull_face(BACK);
    }

    // 第二遍:从相机视角渲染,做阴影测试
    unsafe {
        gl.bind_framebuffer(FRAMEBUFFER, None);
        gl.viewport(0, 0, window_w, window_h);
        gl.clear(COLOR_BUFFER_BIT | DEPTH_BUFFER_BIT);

        // 绑定 shadow map 给主 shader
        gl.active_texture(TEXTURE1);
        gl.bind_texture(TEXTURE_2D, Some(shadow_map.texture));
        gl.uniform_1_i32(main_shader.uniform("u_shadow_map"), 1);
        gl.uniform_matrix_4_f32_slice(
            main_shader.uniform("u_light_view_proj"),
            false,
            &shadow_map.light_view_proj.to_cols_array(),
        );

        render_scene(&camera_view_proj, &main_shader);
    }

    window.swap_buffers();
}
```

Arch 工具链:

```bash
# 装调试工具
sudo pacman -S renderdoc
sudo pacman -S mesa-utils
sudo pacman -S vulkan-tools  # GPU 信息

# 看 OpenGL 信息(确认支持 3.3+)
glxinfo | grep "OpenGL version"
# 输出:OpenGL version string: 4.6 (Compatibility Profile)

# 用 Renderdoc 抓帧看 shadow map
renderdoc &
# 1. 启动你的程序(在 Renderdoc 里 launch)
# 2. 按 F12 抓一帧
# 3. Texture Viewer 里看 shadow map 纹理(深度纹理,Renderdoc 自动可视化)
# 4. 确认阴影正确生成、bias 合理

# 用 NVIDIA Nsight(如果你用 NVIDIA GPU)
sudo pacman -S nsight-graphics
nsight-graphics &
# 更专业的 GPU profiling

# 常见问题排查
# Q: 阴影全黑
# A: bias 太大,把所有片段推到阴影里。调小 bias(从 0.001 起)
#    检查 light_view_proj 矩阵传递是否正确(uniform location 错导致拿 identity matrix)
#
# Q: 阴影全白(没有阴影)
# A: light_view_proj 算错,或 shadow map 没正确绑定到 sampler
#    用 Renderdoc 看 shadow map 内容是不是全黑(没渲染到)
#
# Q: 阴影 acne
# A: bias 不够,或没用 cull_face(FRONT)
#    调大 bias 到 0.005~0.01
#
# Q: Peter Panning(物体飘)
# A: bias 太大,或 cull_face(FRONT) 让薄物体消失
#    改用 slope-scaled bias,bias 根据表面斜率动态算
#
# Q: 阴影边缘锯齿严重
# A: PCF kernel 太小或没用 PCF
#    改成 5×5 PCF,或泊松圆盘采样
#
# Q: 远处阴影消失
# A: shadow_map_size 不够大,或 CSM 级联不够
#    增加 shadow map 到 4096,或上 CSM
```

## 15 · 延伸阅读

本仓库本地:

- `days/phase-6/deep-dives/depth-buffer-precision.md` — 阴影映射的精度问题(深度分布不均)
- `days/phase-6/deep-dives/light-attenuation.md` — 光源基础(点光源距离衰减)
- `days/phase-6/deep-dives/lighting-models.md` — Lambert / Phong / PBR BRDF

外部稳定 URL:

- LearnOpenGL Shadow Mapping(入门经典):https://learnopengl.com/Advanced-Lighting/Shadows/Shadow-Mapping
- LearnOpenGL CSM(级联阴影):https://learnopengl.com/Guest-Articles/2021/CSM
- Scratchapixel Shading:https://www.scratchapixel.com/lessons/3d-basic-rendering/introduction-to-shading
- Ogre Shadow Mapping:https://ogrecave.github.io/ogre/api/latest/_shadow-mapping.html
- GPU Gems CSM(NVIDIA 经典文章):https://developer.nvidia.com/gpugems/gpugems3/part-ii-shading-lighting-and-shadows/chapter-10-parallel-split-shadow
- MSDN Direct3D 11 Shadow Mapping:https://learn.microsoft.com/en-us/windows/win32/direct3d/advanced-effects

真实开源源码:

- bgfx shadow example:https://github.com/bkaradzic/bgfx/tree/master/examples/18-ibl
- Filament shadows(C++):https://github.com/google/filament/blob/main/filament/src/details/RenderPass.cpp
- Bevy PBR shadows(Rust):https://github.com/bevyengine/bevy/blob/main/crates/bevy_pbr/src/render/light.rs
- Casey HH 原版 day261+ shadow map C 代码:https://github.com/HandmadeHero/handmade-hero
