# 阴影映射:Shadow Map 算法、PCF、VSM、Cascaded Shadow Maps

> 光照回答了"光从哪里来",深度回答了"谁在前面"。但还有一个问题没回答:"光能不能照到这里?"如果光源和片段之间有遮挡物,这个片段就在阴影里。**阴影映射**(shadow mapping)用两次渲染解决这个问题——第一次从光源视角画深度,第二次测试主相机里的片段是否被光源看见。本文从 1978 年的原始算法讲到 PCF 软阴影,从 VSM 讲到 CSM 大场景,让你写出工业级的阴影系统。

## 0 · 为什么要有阴影映射

光照模型告诉我们"光打在表面反射多少",但**没考虑遮挡**。一盏灯照过来,中间有一根柱子,柱子背后的墙理论上应该比柱子前的墙暗——但你的光照公式不知道柱子在那里。结果就是场景"漂着",没立体感。

阴影是空间关系最直接的视觉线索。心理学家实验:即使去掉所有颜色和细节,只要保留阴影,人就能准确判断物体距离地面的高度。**没有阴影的场景看起来像照片贴在背景上**。

阴影算法分两大类:

1. **几何方法**(shadow volume / stencil shadow):精确,但 CPU 准备复杂,现在很少用
2. **图像方法**(shadow mapping):GPU 友好,简单,但有精度和锯齿问题

工业界几乎全部用图像方法,即**阴影映射**。它的核心思想极其简单:**渲染场景两次**——第一次从光源视角(画深度),第二次从相机视角(用第一次的深度做遮挡测试)。本文专注这个算法及其工业级改进。

**读完这一篇你能**:
- 实现 1978 年原始 shadow map 算法
- 解释为什么会出现 shadow acne(阴影痤疮)和 Peter Panning(彼得潘效应)
- 用 PCF 实现软阴影边缘
- 配置 CSM 让 1km 视距也有清晰阴影

## 1 · 原始 Shadow Map 算法

### 两遍渲染

**第一遍:从光源视角渲染**。

如果光源是方向光(像太阳),光源视角是一个"无限远"的正交相机。如果是点光源,需要 cubemap(6 个方向各渲染一次)。这里先讲方向光的简单情况。

```rust
// 第一遍
let light_view_proj = compute_light_view_proj(
    light_dir, scene_bounds,
);
// 渲染场景,只画深度到 shadow_map(深度纹理)
render_scene_depth_only(&light_view_proj, &mut shadow_map);
```

shadow_map 是一张专门的深度纹理,存"从光源看到的最近距离"。

**第二遍:从相机视角渲染,做阴影测试**。

```rust
// 第二遍
for fragment in scene {
    let world_pos = fragment.world_pos;
    let light_space_pos = light_view_proj * world_pos;
    
    // 光源空间深度(z 在 [0, 1])
    let current_depth = light_space_pos.z;
    
    // shadow map 在这一位置的深度
    let shadow_map_depth = sample(shadow_map, light_space_pos.xy);
    
    // 测试:这个片段是不是被遮挡?
    let in_shadow = current_depth > shadow_map_depth + bias;
    
    let light_factor = if in_shadow { 0.0 } else { 1.0 };
    // 把 light_factor 乘到光照公式上
}
```

### 直觉:为什么这样能算阴影?

光源视角下,看到的最近深度 = "光能照到的最近物体"。如果你当前片段的深度大于这个值,说明它被某个物体挡住了——它在阴影里。

## 2 · 经典问题:Shadow Acne

### 现象

第一次跑 shadow map,你看到阴影区域充满条纹状的"花纹"——亮暗交替,像被砂纸磨过。这叫 **shadow acne**(阴影痤疮)。

### 根因

shadow map 是一张低分辨率纹理(比如 1024×1024),每个 texel 覆盖场景中的一块区域。主相机渲染时,一个片段投影到 shadow map,可能落在某个 texel 的中心,也可能落在边缘。这个 texel 存的深度是"该 texel 覆盖区域的某个代表深度",但片段的真实深度可能略大或略小——结果是同一个表面上,有的片段被测试为"遮挡"(acne),有的不被测试为遮挡。

```
表面同一面,各片段 z 几乎相同,但 shadow map 采样位置不同,
有的采到"略浅的深度",有的采到"略深的深度",
产生条纹。
```

### 解决:Bias(偏移)

加一个偏移让测试更宽松:

```glsl
float bias = 0.005;
bool in_shadow = current_depth > shadow_map_depth + bias;
```

bias 让阴影"往后退一点",消除 acne。

但 bias 太大会引入另一个问题:**Peter Panning**(彼得潘效应)——物体看起来"飘"在地面上,因为接触面的阴影也被 bias 推掉了。

### 更好的解决:正面剔除

更好的做法是**渲染 shadow map 时剔除正面三角形,只渲染背面**。这样 shadow map 存的是"背面的深度",永远比正面深,自动消除 acne。

```rust
// 第一遍
gl.enable(glow::CULL_FACE);
gl.cull_face(glow::FRONT);  // 剔除正面,只渲染背面
render_scene_depth_only(&light_view_proj, &mut shadow_map);
gl.cull_face(glow::BACK);   // 恢复
```

代价:薄物体(单片叶子)可能完全被剔除,导致没阴影。

## 3 · 问题:硬边缘锯齿

### 现象

阴影边缘是黑白二值(在阴影 / 不在阴影),看起来像剪纸。真实阴影边缘是软的——这是物理上半影(penumbra)现象:光源有面积,边缘附近的点部分被照亮、部分被遮挡。

### PCF:Percentage-Close Filtering

最简单的软阴影:**采样多次,平均结果**。

```glsl
float shadow = 0.0;
vec2 texel_size = 1.0 / textureSize(shadow_map, 0);
for (int x = -1; x <= 1; x++) {
    for (int y = -1; y <= 1; y++) {
        float pcf_depth = texture(
            shadow_map,
            uv + vec2(x, y) * texel_size
        ).r;
        shadow += current_depth > pcf_depth + bias ? 0.0 : 1.0;
    }
}
shadow /= 9.0;
```

每行注释:

- `texel_size` = 1 / shadow_map 大小,表示一个 texel 在 UV 空间的尺寸
- 3×3 邻域采样,每个采样返回 0 或 1,平均得 0.0 ~ 1.0 的软阴影值
- 9 次采样让边缘从硬变软

工业级 PCF 用更大核(5×5、7×7)或泊松圆盘采样,边缘更软。

## 4 · 问题:精度(Shadow Map 深度分布)

Shadow map 也有深度缓冲精度问题。如果光源视角的 near/far 设不对,远处精度不足,产生 z-fighting 类问题。

解决方案:**tight frustum**(紧致视锥)——光源视角的近平面和远平面贴合场景包围盒。Casey 在 Day 430+ 会做这件事。

更进一步:**Cascaded Shadow Maps**(下面讲)用多个 shadow map 不同精度,覆盖不同距离。

## 5 · VSM:Variance Shadow Maps

PCF 每个片段要多次采样,昂贵。**VSM**(Variance Shadow Map)的想法:**预计算 shadow map 的统计量(均值 + 方差),用切比雪夫不等式一次性估算遮挡概率**。

### 算法

1. 第一遍渲染时,不只存深度,还存深度²。两张纹理:depth_mip(存 depth)、depth²_mip(存 depth²)。
2. 生成 mipmap(每级 mipmap 是上一级的均值)。
3. 第二遍测试时:

```glsl
float depth_mean = texture(depth_mip, uv).r;
float depth_sq_mean = texture(depth_sq_mip, uv).r;
float variance = depth_sq_mean - depth_mean * depth_mean;
variance = max(variance, 0.00001);  // 防数值噪声

// 切比雪夫上界:遮挡概率
float d = current_depth;
float t = (depth_mean > d) ? 0.0 :
    variance / (variance + (d - depth_mean) * (d - depth_mean));

float shadow = 1.0 - t;
```

每行解释:

- 切比雪夫不等式:P(X ≥ t) ≤ σ²/(σ² + (t-μ)²),告诉我们"深度大于当前片段的概率"上界
- 这是个统计近似,只需一次纹理采样,不像 PCF 要多次

VSM 优势:**极快**(一次采样),**软阴影天然**(因为 mipmap 自带模糊)。

VSM 劣势:**光渗漏**(light bleeding)——两个遮挡物重叠时,统计量失真,边缘出现亮带。需要 LVSM(Layered VSM)等改进。

## 6 · CSM:Cascaded Shadow Maps

### 问题:大场景下的精度

一张 2048×2048 的 shadow map 覆盖 1km × 1km 的场景——每 texel 代表 0.5m,远处物体阴影全是锯齿。但用更大 shadow map 又爆显存。

### CSM 解决方案

**把视锥分成多段(级联)**,每段用独立的 shadow map。近段覆盖小区域(精度高),远段覆盖大区域(精度低)。

```
Cascade 0: 0~10m, shadow map 2048×2048,精度 0.5cm/texel
Cascade 1: 10~50m, shadow map 2048×2048,精度 2.5cm/texel
Cascade 2: 50~200m, shadow map 2048×2048,精度 10cm/texel
Cascade 3: 200~1000m, shadow map 2048×2048,精度 50cm/texel
```

shader 根据片段的相机空间深度,选择对应级联的 shadow map 做测试。

### 实现

```glsl
// 顶点 shader:把片段的 view_depth 传给片段
in float v_view_depth;

// 片段 shader:
uniform sampler2DArray shadow_cascades;  // 4 张 shadow map 用数组纹理
uniform vec4 cascade_endpoints;  // 每级 cascade 的远端距离

void main() {
    int cascade_idx = 0;
    if (v_view_depth < cascade_endpoints.x) cascade_idx = 0;
    else if (v_view_depth < cascade_endpoints.y) cascade_idx = 1;
    else if (v_view_depth < cascade_endpoints.z) cascade_idx = 2;
    else cascade_idx = 3;
    
    // 选对应级联的 light_view_proj
    vec4 light_space_pos = light_view_proj[cascade_idx] * vec4(world_pos, 1.0);
    // 测试
    // ...
}
```

级联间过渡平滑:在级联边界附近,混合两个级联的阴影值,避免可见接缝。

## 7 · Cube Shadow Map:点光源

点光源向所有方向发光,需要 cubemap(6 个面的纹理)做 shadow map。OpenGL 用 `GL_TEXTURE_CUBE_MAP`,Vulkan 用 `VK_IMAGE_CREATE_CUBE_COMPATIBLE_BIT`。

第一遍:6 次渲染,每个面朝向 ±X、±Y、±Z。或者**几何着色器**一次性渲染 6 面。

第二遍:从片段到光源的方向采样 cubemap,得到该方向最近深度。

## 8 · Rust 实现:简化 Shadow Map

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
            // 设置参数(关键:不用 mipmap、用 CLAMP_TO_EDGE)
            gl.tex_parameter_i32(TEXTURE_2D, TEXTURE_MIN_FILTER, LINEAR as i32);
            gl.tex_parameter_i32(TEXTURE_2D, TEXTURE_MAG_FILTER, LINEAR as i32);
            gl.tex_parameter_i32(TEXTURE_2D, TEXTURE_WRAP_S, CLAMP_TO_BORDER as i32);
            gl.tex_parameter_i32(TEXTURE_2D, TEXTURE_WRAP_T, CLAMP_TO_BORDER as i32);
            // 边界外采样返回 1.0(不在阴影里)
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
    
    pub fn compute_light_view_proj(
        light_dir: Vec3,
        scene_bounds: AABB,
    ) -> Mat4 {
        // 正交投影,贴合场景包围盒
        let light_pos = scene_bounds.center() - light_dir * scene_bounds.radius();
        let view = Mat4::look_at_rh(light_pos, scene_bounds.center(), Vec3::Y);
        // 正交投影
        let proj = Mat4::orthographic_rh(
            -scene_bounds.radius(), scene_bounds.radius(),
            -scene_bounds.radius(), scene_bounds.radius(),
            -scene_bounds.radius(), scene_bounds.radius(),
        );
        proj * view
    }
}
```

每行注释:

- `DEPTH_COMPONENT24` — 24 位整数深度(够 shadow map 用)
- `CLAMP_TO_BORDER` + border color = 1.0 — shadow map 外的像素视为"最近"(不在阴影里)
- `look_at_rh` — RH(right-handed)是 OpenGL/Vulkan 标准
- `orthographic_rh` — 正交投影(方向光);点光源用透视投影

## 9 · Fragment Shader 完整示例

```glsl
#version 330 core

in vec3 v_world_pos;
in vec3 v_world_normal;
in vec2 v_uv;

out vec4 frag_color;

uniform vec3 u_cam_pos;
uniform vec3 u_light_dir;
uniform vec3 u_light_color;
uniform mat4 u_light_view_proj;
uniform sampler2D u_shadow_map;
uniform sampler2D u_albedo;
uniform float u_bias;

void main() {
    vec3 N = normalize(v_world_normal);
    vec3 L = normalize(-u_light_dir);  // 方向光指向反方向
    vec3 V = normalize(u_cam_pos - v_world_pos);
    
    // 光照(简化 Lambert)
    vec3 albedo = texture(u_albedo, v_uv).rgb;
    float cos_theta = max(dot(N, L), 0.0);
    vec3 lit_color = albedo * u_light_color * cos_theta;
    
    // 阴影
    vec4 light_space = u_light_view_proj * vec4(v_world_pos, 1.0);
    vec3 proj_coords = light_space.xyz / light_space.w;
    proj_coords = proj_coords * 0.5 + 0.5;  // NDC [-1,1] → [0,1]
    
    float current_depth = proj_coords.z;
    
    // PCF 3x3
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
    
    // 范围外不在阴影里
    if (proj_coords.z > 1.0) shadow = 1.0;
    
    vec3 final = lit_color * shadow;
    frag_color = vec4(final, 1.0);
}
```

每段注释:

- `proj_coords.xyz / proj_coords.w` — 透视除法
- `* 0.5 + 0.5` — 把 NDC [-1, 1] 映射到 [0, 1] 供纹理采样
- `current_depth - u_bias` — shadow acne 偏移
- `proj_coords.z > 1.0 → shadow = 1.0` — 超出 shadow map 远平面的不在阴影里

## 10 · 历史

- 1978: Lance Williams 首次提出 shadow casting(intervals, 类似 shadow map)
- 1986: Reeves et al. 提出 PCF(percentage-closer filtering)
- 1990s: shadow map 成 OpenGL/D3D 主流
- 2006: Donnelly & Lauritzen 提出 VSM
- 2006: Engeld & Dimitrov 提出 CSM
- 2010s: CSM + PCF 成主流;软阴影变种层出不穷
- 2020s: Ray-traced shadows 在 RTX/DLSS 时代成为可能

## 11 · 关联 Day

- **铺垫**:Day 261 深度缓冲;Day 280 光照;Day 290 投影矩阵
- **当天**:本篇是 shadow map 专题
- **后续**:Day 440+ CSM 实战;Day 480+ 延迟着色 + 阴影优化

## 12 · 变式训练

### Lv1 · 概念辨析

**题**:Shadow acne 和 Peter Panning 互为相反问题——解释为什么 bias 太小造成前者,bias 太大造成后者。

**参考解答**:**bias 太小**,shadow map 精度限制导致同一表面上的相邻片段在 shadow map 上深度有微小差异,有的片段被测试为"遮挡",有的"不遮挡",产生条纹(acne)。**bias 太大**,把片段的测试深度推到比实际位置更远——结果连"接触地面的物体"也在阴影测试中失败(因为地面深度 + bias 已经超出物体深度),物体与地面之间的阴影消失,物体看起来"飘"在地面上(Peter Panning)。

### Lv2 · 动手实践

**题**:在你的渲染器里加 shadow map。要求:方向光、PCF 3x3、bias 可调。

完成标准:立方体在地面上投下阴影,阴影边缘软。

**参考解答**:三步走——
1. 实现 shadow map FBO(深度纹理,24 位)
2. 第二遍渲染,把 light_view_proj 传给 shader
3. PCF 在 fragment shader 里做(见上面的 GLSL)

### Lv3 · 迁移设计

**题**:声音也有"遮挡"——墙挡住声音时,墙后有"声影区"。类比 shadow map,设计一个简化的声影计算。

**提示**:声波不像光,会绕射(diffraction)——这是 shadow map 没有的特性。你的设计要不要考虑绕射?

### Lv4 · 开源贡献

**题**:Bevy 的 PBR 阴影,GitHub: https://github.com/bevyengine/bevy

1. clone 它
2. 看 `crates/bevy_pbr/src/render/light.rs` 和 shadow 相关代码
3. 找 CSM 实现
4. 可能的贡献:加文档 / 改进 PCF 采样模式 / 提一个新特性

## 13 · Rust / Arch 落地代码

完整的 shadow map 管线骨架:

```rust
// 1. 创建 shadow map
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
        render_scene(&shadow_map.light_view_proj, &shadow_shader);
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

# 用 Renderdoc 抓帧看 shadow map
renderdoc &
# 1. 启动你的程序
# 2. 在 Renderdoc 里抓一帧
# 3. Texture Viewer 看 shadow map 纹理(深度纹理,Renderdoc 自动可视化)
# 4. 确认阴影正确生成

# 常见问题排查:
# Q: 阴影全是黑
# A: bias 太大,把所有片段推到阴影里。调小 bias(从 0.001 起)
#
# Q: 阴影全是白(没有阴影)
# A: light_view_proj 算错,或 shadow map 没正确绑定。检查 uniform
#
# Q: 阴影 acne
# A: bias 不够,或没用 cull_face(FRONT)
#
# Q: Peter Panning(物体飘)
# A: bias 太大,或 cull_face(FRONT) 让薄物体消失
```

## 14 · 延伸阅读

本仓库本地:

- `days/phase-6/deep-dives/depth-buffer-precision.md` — 阴影映射的精度
- `days/phase-6/deep-dives/light-attenuation.md` — 光源基础

外部稳定 URL:

- LearnOpenGL Shadow Mapping: https://learnopengl.com/Advanced-Lighting/Shadows/Shadow-Mapping
- LearnOpenGL CSM: https://learnopengl.com/Guest-Articles/2021/CSM
- Scratchapixel Shading: https://www.scratchapixel.com/lessons/3d-basic-rendering/introduction-to-shading
- Ogre Shadow Mapping: https://ogrecave.github.io/ogre/api/latest/_shadow-mapping.html
- GPU Gems CSM: https://developer.nvidia.com/gpugems/gpugems3/part-ii-shading-lighting-and-shadows/chapter-10-parallel-split-shadow

真实开源源码:

- bgfx shadow example: https://github.com/bkaradzic/bgfx/tree/master/examples/18-ibl
- Filament shadows: https://github.com/google/filament/blob/main/filament/src/details/RenderPass.cpp
- Bevy PBR shadows: https://github.com/bevyengine/bevy/blob/main/crates/bevy_pbr/src/render/light.rs
