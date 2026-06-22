# 光衰减:反平方律、距离衰减、色温、IBL

> 光在真空中传播时强度按 1/r² 衰减——这是 17 世纪牛顿就知道的物理事实。但游戏里你不真的解麦克斯韦方程组,你用一个简化的"距离衰减函数"骗 GPU。这个函数的设计直接决定你的光照看起来"对"还是"假"。本文从反平方律讲到 Light Item 衰减,从色温讲到基于图像的光照(IBL),让你写出"光照师调出来"而不是"程序员调出来"的光。

## 0 · 为什么要有光衰减

你的场景里有一盏路灯。PBR 公式给你 BRDF,但 BRDF 只告诉你"光打到表面反射多少"。**还没回答两个问题**:

1. **光有多强**:一盏灯从 1 米外照过来,和从 100 米外照过来,亮度差 1 万倍。差在哪?
2. **光的颜色**:钨丝灯偏黄、日光偏白、霓虹灯偏蓝。怎么表达?

第一个是**距离衰减**(distance attenuation),第二个是**光的颜色与色温**(color / temperature)。两者一起决定光照计算的最终结果。

**直觉**:光从光源向外辐射,能量分散到一个不断扩大的球面上。距离 r 时,球面面积 = 4πr²,所以单位面积的能量 ∝ 1/r²。这是反平方律(inverse-square law)的物理来源。

**实战挑战**:

1. **反平方律在 r→0 时发散**:r = 0 时光强无穷大,数学崩了。游戏里要 clamp。
2. **远处光太弱**:1/r² 让远距离光几乎为 0,GPU 浪费算力。游戏里给一个"截止半径"(cutoff radius)。
3. **环境光怎么办**:房间里的天花板、墙壁反射光,这些怎么表达?——这是 IBL(Image-Based Lighting,基于图像的光照)的事。

**读完这一篇你能**:
- 解释为什么游戏用 `1/r²` 但又要 clamp
- 用 Rust 写一个带衰减的点光源
- 知道 IBL 是什么、为什么主流 PBR 都用 IBL
- 看懂 LearnOpenGL / Filament 关于光照衰减的章节

## 1 · 反平方律:物理基础

### 几何推导

光源功率 P(单位:瓦特 W),向四面八方均匀辐射。距离 r 处,能量分布在球面 4πr² 上,所以**辐照度**(irradiance,单位面积接受的能量)为:

```
E(r) = P / (4π r²)
```

光强 I(单位:坎德拉 cd,即 W/sr)和功率的关系:`P = 4π I`(全方向积分)。所以:

```
E(r) = I / r²
```

这是反平方律。具体到 BRDF 渲染:

```
L_out = BRDF * L_in * cos(θ)
L_in = (light_color * light_intensity) / r²
```

### Rust 实现(朴素版)

```rust
fn point_light_attenuation(distance: f32) -> f32 {
    // 朴素反平方律
    if distance < 1e-6 {
        return f32::MAX;  // 避免除零
    }
    1.0 / (distance * distance)
}
```

**问题**:

1. `distance → 0` 时返回无穷大,亮度爆白
2. `distance` 很大时几乎为 0,但 GPU 仍在算光照——浪费
3. 没有"光的物理范围"概念——真实灯泡离 100 米外你听不到光,但 GPU 还在算

## 2 · 工程化:加 windowing 函数

### 加 cutoff

```rust
fn point_light_attenuation(distance: f32, light_radius: f32) -> f32 {
    // 在 light_radius 外完全没光
    if distance >= light_radius {
        return 0.0;
    }
    let attenuation = 1.0 / (distance * distance + 1e-4);
    // 在 cutoff 边缘 smooth 衰减到 0
    let cutoff_factor = 1.0 - (distance / light_radius).powi(4);
    attenuation * cutoff_factor.max(0.0)
}
```

每行注释:

- `light_radius` — 光源影响半径,超过这个距离光完全消失
- `+ 1e-4` — 避免在 distance = 0 时除零(还顺便给反平方律一个"上限")
- `cutoff_factor = 1 - (d/r)⁴` — smooth 衰减。指数 4 是经验值(看起来自然)

### Unreal 衰减公式

主流游戏引擎(Unreal、CryEngine)用更简洁的:

```
attenuation = 1 - (distance / radius)^4
attenuation = max(0, attenuation)^2 / (distance² + 1)
```

这两步合成一个公式,既满足物理直觉(近距离反平方),又有可控范围(cutoff radius)。

### Frostbite 的"smooth inverse"

DICE(Frostbite 引擎)提出:

```
attenuation = (1 - (d/r)²)² * (1/d²)
```

`windowing`(平滑窗口)和 `1/d²`(反平方)分开,组合后既保证距离衰减正确,又保证 cutoff 平滑。

## 3 · 聚光灯衰减

点光源向所有方向发光;聚光灯只在锥形方向发光。聚光灯有两个角度:

- **内锥角**(inner cone):完全亮度
- **外锥角**(outer cone):亮度衰减到 0

```rust
fn spot_light_attenuation(
    light_dir: Vec3,    // 光的朝向
    frag_to_light: Vec3,  // 从片段指向光源
    cos_inner: f32,     // 内锥角的 cos
    cos_outer: f32,     // 外锥角的 cos
) -> f32 {
    let cos_theta = light_dir.dot(-frag_to_light);  // fragment 在光锥内的角度
    if cos_theta < cos_outer {
        return 0.0;  // 在外锥外
    }
    // smooth 插值
    let t = (cos_theta - cos_outer) / (cos_inner - cos_outer);
    t.clamp(0.0, 1.0).powi(2)
}
```

总衰减 = 距离衰减 × 聚光衰减。

## 4 · 光的颜色与色温

### 色温(Color Temperature)

光源发射的光不是纯白——它有一个"主色调",用**色温**(color temperature,单位:开尔文 K)描述。

| 色温 (K) | 描述 | 颜色感受 |
|---|---|---|
| 1000 | 烛光 | 橙红 |
| 2700 | 钨丝灯 | 暖黄 |
| 3500 | 日出/日落 | 暖白 |
| 5500 | 正午日光 | 中性白 |
| 6500 | 阴天天空 | 冷白 |
| 10000 | 深蓝天光 | 深蓝 |

**直觉**:色温低 = 红黄(暖);色温高 = 蓝白(冷)。色温来自黑体辐射(Black-body radiation):加热铁块到不同温度,它会发不同颜色的光——1000K 暗红,3000K 橙黄,6000K 白炽,10000K 蓝白。

### 色温到 RGB:Planckian Locus

把色温 K 转成 RGB,需要查表或近似公式。Tanner Helland 给了一个工业界常用的经验公式:

```rust
fn color_temperature_to_rgb(kelvin: f32) -> Vec3 {
    // Tanner Helland 算法,温度范围 1000K-40000K
    let temp = (kelvin / 100.0).clamp(1.0, 400.0);
    
    // 红
    let r = if temp <= 66.0 {
        255.0
    } else {
        329.698727446 * (temp - 60.0).powf(-0.1332047592)
    };
    
    // 绿
    let g = if temp <= 66.0 {
        99.4708025861 * temp.ln() - 161.1195681661
    } else {
        288.1221695283 * (temp - 60.0).powf(-0.0755148492)
    };
    
    // 蓝
    let b = if temp >= 66.0 {
        255.0
    } else if temp <= 19.0 {
        0.0
    } else {
        138.5177312231 * (temp - 10.0).ln() - 305.0447927307
    };
    
    Vec3 {
        x: (r.clamp(0.0, 255.0) / 255.0),
        y: (g.clamp(0.0, 255.0) / 255.0),
        z: (b.clamp(0.0, 255.0) / 255.0),
    }
}
```

每段解释:

- 经验公式的分段(66K、19K)来自黑体辐射在不同温度段的不同行为
- 1000K 时输出 (1, 0.43, 0)——橙红
- 5500K 时输出接近 (1, 1, 0.97)——中性白
- 10000K 时输出 (0.65, 0.84, 1)——冷蓝

游戏里用法:美术把光"色温"参数调到 5500K(日光)或 2700K(暖灯),引擎自动转成 RGB,光照颜色就对了。

## 5 · IBL:基于图像的光照

### 反平方律解决不了的问题

反平方律只描述**直接光**(从光源直接到达表面)。但现实里有大量**间接光**:光从光源打到墙,墙反射到桌子,桌子反射到你的角色——每一次反射都是一束新光。

精确模拟每一束反射是光线追踪的活,实时渲染太贵。**IBL** 用一个简化:**把环境光预计算成一张 cubemap(立方体贴图),游戏时采样它**。

### IBL 的两部分

PBR + IBL 把光照拆两部分:

1. **Diffuse IBL**:漫反射部分。从 cubemap 采样,但要做积分(因为漫反射收所有方向的光)
2. **Specular IBL**:镜面反射部分。也积分,但加上 Fresnel 和 roughness 影响

预计算:`irradiance_map`(漫反射预积分图)和 `prefiltered_env_map`(镜面预滤波图)。

### Diffuse IBL 预计算

```glsl
// 离线 shader,对每个 cubemap 像素:
// 从该方向出发,采样半球所有方向,平均得 irradiance
vec3 irradiance = vec3(0.0);
vec3 up = vec3(0.0, 1.0, 0.0);
vec3 right = cross(up, normal);
up = cross(normal, right);

float sample_delta = 0.025;
float nr_samples = 0.0;
for (float phi = 0.0; phi < 2.0 * PI; phi += sample_delta) {
    for (float theta = 0.0; theta < 0.5 * PI; theta += sample_delta) {
        vec3 tangent_sample = vec3(
            sin(theta) * cos(phi),
            sin(theta) * sin(phi),
            cos(theta)
        );
        vec3 sample_vec = tangent_sample.x * right + 
                          tangent_sample.y * up + 
                          tangent_sample.z * normal;
        irradiance += texture(environment_map, sample_vec).rgb *
                      cos(theta) * sin(theta);
        nr_samples += 1.0;
    }
}
irradiance = PI * irradiance / nr_samples;
```

每行注释:

- 半球采样:用球坐标 (θ, φ) 遍历上半球
- `cos(theta) * sin(theta)` 是球坐标的雅可比,加权每个采样点
- 最后乘 π 是为了能量守恒(漫反射 BRDF 里的 1/π 和它抵消)

### Specular IBL 预滤波

镜面反射的入射方向取决于视角和 roughness,所以不能用单一 irradiance map。**预滤波**:对每个 roughness 级别,生成一张"模糊"的 cubemap(roughness 越大越模糊)。运行时根据 roughness 采样对应 mip。

### 运行时使用

```glsl
// 主 shader
vec3 irradiance = texture(irradiance_map, N).rgb;
vec3 diffuse_diff = irradiance * albedo;

vec3 R = reflect(-V, N);
vec3 prefiltered = textureLod(prefiltered_map, R, roughness * MAX_LOD).rgb;
vec2 brdf = texture(brdf_lut, vec2(NdotV, roughness)).rg;
vec3 specular = prefiltered * (F * brdf.x + brdf.y);

vec3 ambient = (kD * diffuse_diff + specular) * ao;
```

每行注释:

- `irradiance_map[N]` — 漫反射环境光
- `reflect(-V, N)` — 镜面反射方向,用来采样 prefiltered_map
- `textureLod` 的第三参数是 mip level——roughness 越大,采样越模糊的 mip
- `brdf_lut` 是另一张 LUT(查找表),横轴 NdotV、纵轴 roughness,存 BRDF 的两个补偿项

### 复杂度对比

| 方法 | 直接光 | 间接光 | 总光源数 |
|---|---|---|---|
| 反平方律点光 | ✓ | ✗ | 受限于 shader 性能 |
| 反平方律 + 简化环境光 | ✓ | 全局常量 | 无限(环境) |
| IBL | ✓ | cubemap 采样 | 无限(方向) |

IBL 让你场景里"无处不在的环境光"变成一个采样,极大提升真实感。

## 6 · 通用光源类型

游戏里常用的光源类型:

| 类型 | 描述 | 衰减方式 |
|---|---|---|
| 方向光(directional) | 太阳光,无限远 | 无距离衰减 |
| 点光源(point / omni) | 灯泡,全方向 | 1/r² + windowing |
| 聚光(spot) | 手电筒,锥形 | 1/r² × 角度 windowing |
| 面光源(area) | 显示器、灯板 | 复杂积分 |
| 区域聚光(area spot) | 顶部光带 | 真实阴影 |

工业界用 Light Item(虚幻术语)/ Light Component(Bevy 术语)统一描述光源,不同参数决定类型。

## 7 · 历史

- 17 世纪:Newton 提出反平方律(光学版)
- 19 世纪:Maxwell 方程组给出反平方律的理论基础
- 1976:Whitted 光线追踪,首次精确模拟直接光
- 1986:Kajiya 渲染方程,统一所有光照
- 1998:Pixar 用 IBL 概念(预积分环境光)
- 2004:RAM(Reflectance and Appearance Map),Precomputed Radiance Transfer
- 2007:Crysis 1 大规模使用 IBL 风格
- 2014:UE4 PBR + IBL,工业界标配

## 8 · 关联 Day

- **铺垫**:Day 041 数学(向量的距离);Day 271 光照基础;Day 280 PBR
- **当天**:本篇是光衰减专题
- **后续**:Day 420+ 多光源管理;Day 430+ 阴影映射;Day 440 延迟着色

## 9 · 变式训练

### Lv1 · 概念辨析

**题**:为什么反平方律在游戏中要加 windowing(平滑截止),而不是直接 1/r²?

**参考解答**:三个原因:
1. **避免奇点**:1/r² 在 r=0 时无穷,数学和图形上都不友好
2. **GPU 性能**:远处光几乎为 0 但仍在算,加 cutoff 让 GPU 在 cutoff 外直接跳过
3. **美术控制**:windowing 让美术能精确控制"这盏灯影响多大区域"——这比物理 1/r² 更重要(光本身就是空间设计工具)

### Lv2 · 动手实践

**题**:写个 Rust 程序,把一盏点光源放到原点,在 100×100 的格子上画出光的强度热图(颜色从黑到白)。

**提示**:用 image crate。

**参考解答**:

```rust
use image::{ImageBuffer, Rgb, RgbImage};

fn main() {
    let w = 100; let h = 100;
    let mut img: RgbImage = ImageBuffer::new(w, h);
    let light_radius = 50.0;
    let intensity = 5000.0;
    
    for y in 0..h {
        for x in 0..w {
            let dx = x as f32 - w as f32 / 2.0;
            let dy = y as f32 - h as f32 / 2.0;
            let d = (dx * dx + dy * dy).sqrt();
            
            // Frostbite smooth inverse
            let attenuation = if d < light_radius {
                let r = d / light_radius;
                (1.0 - r * r) * (1.0 - r * r) / (d * d + 1.0)
            } else { 0.0 };
            
            let c = (intensity * attenuation).clamp(0.0, 1.0);
            img.put_pixel(x, y, Rgb([
                (c * 255.0) as u8,
                (c * 255.0) as u8,
                (c * 255.0) as u8,
            ]));
        }
    }
    img.save("light_heatmap.png").unwrap();
}
```

### Lv3 · 迁移设计

**题**:声波也按 1/r² 衰减(空气中)。游戏里你能听到爆炸声的距离取决于爆炸强度和"听阈"。设计一个简化版的"声音衰减系统",类比光衰减。

**提示**:声音有"频率依赖衰减"(高频衰减快),光也有(蓝色更易散射)。两者都可以加频率通道。

### Lv4 · 开源贡献

**题**:Bevy 是 Rust 主流游戏引擎,GitHub: https://github.com/bevyengine/bevy

1. clone 它
2. 看 `crates/bevy_pbr/src/light/`
3. 找点光源衰减函数(`PointLight`、`aulight_attenuation`)
4. 可能的贡献:加文档注释解释衰减公式选择,或加一个新的"区域光"(area light)类型

## 10 · Rust / Arch 落地代码

一个完整的点光 + 衰减 + 色温 PBR 片段 shader 片段:

```glsl
// Fragment shader
#version 330 core

in vec3 v_world_pos;
in vec3 v_world_normal;
in vec2 v_uv;

out vec4 frag_color;

uniform vec3 u_cam_pos;
uniform vec3 u_light_pos;
uniform vec3 u_light_color;
uniform float u_light_intensity;
uniform float u_light_radius;
uniform float u_light_temperature;  // K

uniform sampler2D u_albedo;
uniform sampler2D u_normal_map;
uniform float u_metallic;
uniform float u_roughness;

void main() {
    vec3 N = normalize(v_world_normal);
    vec3 V = normalize(u_cam_pos - v_world_pos);
    vec3 L = u_light_pos - v_world_pos;
    float dist = length(L);
    L /= dist;
    
    // 色温调色
    vec3 light_color_temp = color_temperature(u_light_temperature);
    vec3 light_color = u_light_color * light_color_temp;
    
    // 衰减
    float r = dist / u_light_radius;
    float attenuation = (1.0 - r * r) * (1.0 - r * r);
    attenuation /= (dist * dist + 1.0);
    if (dist >= u_light_radius) attenuation = 0.0;
    
    // PBR BRDF(假设调 pbr_brdf 函数)
    vec3 brdf = pbr_brdf(
        texture(u_albedo, v_uv).rgb,
        u_metallic, u_roughness,
        N, L, V
    );
    
    // 最终光
    float cos_theta = max(dot(N, L), 0.0);
    vec3 radiance = light_color * u_light_intensity * attenuation;
    vec3 final_color = brdf * radiance * cos_theta;
    
    // Tone map + gamma
    final_color = final_color / (final_color + 1.0);  // Reinhard
    final_color = pow(final_color, vec3(1.0 / 2.2));
    
    frag_color = vec4(final_color, 1.0);
}
```

Arch 工具链:

```bash
# 装工具
sudo pacman -S shaderc glslang  # GLSL 编译器
sudo pacman -S mesa-demos       # 示例
sudo pacman -S renderdoc        # GPU 调试

# 编译 shader
glslangValidator -V fragment.glsl -o fragment.spv
# -V 编译 Vulkan SPIR-V 二进制

# 看编译错误
glslangValidator -V fragment.glsl 2>&1 | head -20

# 在 Renderdoc 里看光照参数
renderdoc &
# 抓一帧,在 Pipeline State 里看 uniform,确认 light_intensity 真的传进去了
```

## 11 · 延伸阅读

本仓库本地:

- `days/phase-6/deep-dives/lighting-models.md` — BRDF
- `days/phase-6/deep-dives/shadow-mapping.md` — 阴影(光的可见性)

外部稳定 URL:

- LearnOpenGL Light casters: https://learnopengl.com/Lighting/Light-casters
- LearnOpenGL IBL: https://learnopengl.com/PBR/IBL/Diffuse-irradiance
- PBR Book: https://www.pbr-book.org/3ed-2018/Light_Sources
- Frostbite 光衰减论文: https://seblagarde.wordpress.com/2012/01/08/pi-or-not-to-pi-in-game-lighting-equation/
- Tanner Helland 色温: https://tannerhelland.com/2012/09/18/convert-temperature-rgb-algorithm-code.html

真实开源源码:

- Filament Light: https://github.com/google/filament/blob/main/filament/src/Froxelizer.cpp
- Bevy PBR Light: https://github.com/bevyengine/bevy/blob/main/crates/bevy_pbr/src/light/mod.rs
