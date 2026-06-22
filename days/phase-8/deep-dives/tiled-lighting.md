# 深入:光照算法对比 — Tiled / Clustered / Deferred

> Phase 8 大量时间花在光照优化上(Day 576-652)。本文系统对比光照算法:**Forward / Deferred / Tiled Forward / Tiled Deferred / Clustered**,讲清每种原理、何时用、性能差异。

## 1 · 问题:多光源怎么算

考虑场景:N 个物体,M 个光源。每个物体的每个 fragment,要遍历所有 M 光源算 Lambert + specular。

朴素 forward 渲染:

```
for each object:
    for each light:
        shader: compute contribution
```

复杂度 O(N * M)。如果 N = 1M 像素(1080p),M = 100 光源,= 1 亿次计算。GPU 仍卡。

更糟的是**overdraw**——多个物体覆盖同一像素,后面物体覆盖前面,前面计算白费。

## 2 · Forward rendering(前向渲染)

最传统的做法:

```
for each object:
    for each light:
        shade
```

特点:

- 透明物体天然支持(按深度排序画)
- MSAA 天然支持(每样本着色)
- 多光源时性能爆炸
- 受 overdraw 影响

**适合**:光源少(< 8)、需要透明 / MSAA。

**Casey 早期**:Day 235-575 用 forward,光源少,够用。

## 3 · Deferred shading(延迟着色)

把"几何 pass"和"光照 pass"分离:

**Geometry pass**:画所有物体,但**不算光照**。把每个像素的几何属性(位置、法线、albedo)写到 G-buffer(G-buffer = 多张纹理)。

**Lighting pass**:每像素读 G-buffer,算所有光源的贡献。

```
Pass 1: for each object: write albedo, normal, position to G-buffer
Pass 2: for each pixel: for each light: shade using G-buffer
```

特点:

- 几何 pass 后,**光照只算可见像素**——无 overdraw 浪费
- 多光源时优势大(光照 pass 是 2D,不依赖物体数)
- **不支持透明**:G-buffer 只存最近像素,无法 multiple layer
- MSAA 困难(每样本一个 G-buffer,内存爆炸)
- G-buffer 占内存大(albedo RGB + normal RGB + position RGB,每像素 36+ 字节)

**适合**:多个不透明物体 + 多光源。FPS 游戏标配。

## 4 · Light volumes(光体积)

Deferred 的简单优化:每个光源有个"影响范围"(attenuation 决定,例 1/d² 衰减下影响半径约 5/d_intensity)。渲染时**只对光体积内的像素**算光。

```
for each light:
    draw sphere representing light volume
    in fragment shader: read G-buffer, compute contribution only if in volume
```

复杂度:O(sum of light volume pixels)。光源小、空间分散时,大幅减少。

但**光源重叠**时仍累加。重叠区域算多次。Tiled 解决这个。

## 5 · Tiled deferred(分块延迟)

把屏幕分成 16x16 或 32x32 的 tile。每个 tile:

1. **Culling pass**:扫所有光源,记录"哪些光影响这个 tile"
2. **Shading pass**:对 tile 内每像素,只算 culling 出的光

```
for each tile T:
    light_list[T] = [light for light in lights if affects(light, T)]
for each pixel p:
    T = tile_of(p)
    for light in light_list[T]:
        shade
```

复杂度:O(W * H + N_lights_per_tile_avg * W * H)。tile 平均影响光数 << 总光数,大幅减少。

**Culling 实现**:CPU 端(GPU compute shader)或 GPU 端。GPU compute shader 用 shared memory 共享 tile 内 culling 结果,极快。

**性能**:100 光源,朴素 deferred = 100 ops/pixel。Tiled(假设平均 5 光源/tile)= 5 ops/pixel,**20 倍加速**。

## 6 · Tiled forward(分块前向)

Tiled 思路应用到 forward:

1. **Culling pass**:同 tiled deferred
2. **Forward shading**:每物体只算 tile 内光

```
for each tile T:
    light_list[T] = ...
for each object:
    for each pixel p in object:
        T = tile_of(p)
        for light in light_list[T]: shade
```

特点:

- 支持透明(像 forward)
- 支持 MSAA
- 多光源时性能接近 deferred

这就是 Unity 的 Forward rendering pipeline,HDRP 用 tiled forward。

## 7 · Clustered(聚类)

Tiled 的 2D 推广到 3D。把视锥体(frustum)切成 3D grid——每个 cell 是一个"cluster"。

```
for each cluster C (in 3D):
    light_list[C] = [light for light in lights if affects(light, C)]
for each pixel p:
    C = cluster_of(p)
    for light in light_list[C]: shade
```

cluster 比 tile 更精确——tile 里光可能影响 tile 但不影响 tile 里的某些深度,cluster 分深度,精确剔除。

**性能**:比 tiled 再快 2-3 倍,因为更精确 culling。

**复杂度**:cluster 数 = tile 数 * 深度分层数(典型 32 深度层)。1 1080p tile (16x16) = 8100 tiles * 32 深度 = 260k clusters。可行。

DOOM(2016)首次大规模用 clustered,业界标杆。

## 8 · 性能对比

1080p,100 光源,100 万物体三角形:

| 算法 | 复杂度 | 实际帧时间(60Hz) |
|---|---|---|
| Forward | O(W*H * N_lights) | 不可能 60 FPS |
| Deferred | O(W*H * N_lights) | ~50 ms |
| Light volumes | O(sum light volume) | ~10 ms |
| Tiled deferred | O(W*H * avg_per_tile) | ~3 ms |
| Tiled forward | O(visible pixels * avg_per_tile) | ~5 ms |
| Clustered | O(W*H * avg_per_cluster) | ~1.5 ms |

数据是大致量级,实际取决于场景、GPU。

## 9 · Casey 的选择

Casey 在 Day 611-652 优化光照,选了**类似 tiled deferred 的思路**:

- 预计算光表(类似 G-buffer,但是离线)
- 每个 surface voxel 只算影响它的光源(类似 culling)
- 中心约定让查询 O(1)(类似 cluster)

Casey 没用 GPU compute shader 做实时 culling,而是**预计算 culling 结果**——简化版 tiled deferred。

## 10 · 各算法何时用

### Forward

- 光源 < 8
- 大量透明物体
- MSAA 必需
- 移动平台(不支持复杂 G-buffer)

### Deferred

- 多光源(8-50)
- 少透明
- 物体多但光照简单

### Tiled Forward

- 多光源
- 需要透明 + MSAA
- Unity HDRP / UE5 Lumen 部分用

### Tiled Deferred

- 多光源(50-500)
- 不需要透明
- 经典 PC FPS 游戏

### Clustered

- 超多光源(500+)
- 复杂场景(室内 + 室外)
- DOOM Eternal、Cyberpunk 2077 等

## 11 · 实现细节

### G-buffer 布局

典型 deferred 的 G-buffer:

```
RT0: albedo.rgb + ao.a   (RGBA8)
RT1: normal.rgb + rough.a (RGBA16F)
RT2: position.rgb + metal.a (RGBA32F or packed)
```

每像素 ~20 字节。1080p G-buffer = 1920 * 1080 * 20 = 40 MB。多张 RT 同时写,GPU bandwidth 大。

MRT(Multiple Render Targets)是 GPU 渲染 G-buffer 的核心功能。

### Light culling 算法

**Tiled**:对每个 tile,扫所有光,检查 tile 包围盒 vs 光体积球:

```rust
for tile in tiles {
    for light in lights {
        if intersects(tile_aabb, light_sphere) {
            tile.light_list.push(light)
        }
    }
}
```

GPU compute shader 实现:每个 tile 一个 thread group,shared memory 共享 light_list。

**Clustered**:类似,但是 3D AABB vs 球。

### Light list 存储

每 tile / cluster 的 light list 长度可变。两种存储:

1. **固定长度数组**:每 tile 最多 64 光,容易但浪费
2. **链表**:每 tile 起始 index + 长度,链表存所有光 id。紧凑但 cache miss

工业用混合:**bounded linked list**——固定最大长度,超出截断。

## 12 · 现代趋势(2020+)

### Bindless rendering

不用 bind light textures / buffers,直接 GPU virtual address。light 数从"draw call 受限"变成"memory 受限"——可以一次画百万光。

### Mesh shading

DX12 Ultimate / Vulkan 的 mesh shader,把传统 vertex pipeline 替换。更适合 culling + GPU-driven rendering。

### Hardware ray tracing

RTX / DXR 把光追硬件化。每个光实时 ray-trace shadow / reflection。Casey 没用(硬件没普及),但是未来方向。

### Neural rendering

DLSS / XeSS / FSR 等用 ML 超分。Neural radiance cache 用 ML 估计 GI。这些是 2020+ 主流。

## 13 · Rust 生态实践

Rust 的现代渲染库:

- **wgpu**:Vulkan / Metal / DX12 / WebGL 抽象层
- **bevy_pbr**:基于 wgpu,实现 deferred / forward / clustered
- **rend3**:高层渲染库
- **kajiya**:RTX 渲染实验

```rust
// bevy_pbr 用 clustered 示例(bevy 0.10+)
App::new()
    .add_plugins(DefaultPlugins)
    .add_plugin(BevyPbrPlugin)
    .insert_resource(ClusteredRenderingConfig {
        max_lights_per_cluster: 64,
        cluster_size: UVec3::new(16, 16, 32),
    })
    .run();
```

## 14 · 给你的建议

### 学习路径

1. 实现 naive forward
2. 加 light volume culling
3. 实现 deferred(G-buffer + lighting pass)
4. 实现 tiled culling
5. 实现 clustered(可选)

每步 benchmark,看性能曲线。

### 项目选择

- **2D 游戏**:forward 够,别过度工程
- **3D 室内游戏**:deferred + tiled
- **3D 开放世界**:clustered + streaming
- **FPS + 多人**:clustered,优化 draw call

### 用现成库

bevy_pbr 已经有 clustered,直接用。除非你要学,不要自建。

## 15 · 总结

光照算法的选择**决定游戏渲染性能天花板**。Forward 简单但贵,Deferred 复杂但快,Tiled / Clustered 是 deferred 的细化。

Casey 的 HH 选了"离线 tiled deferred"——预计算光表,简化实时开销。这是 1990s 风格,但对教学价值极高——你能看到 culling、attenuation、迭代收敛等核心概念。

现代引擎的 clustered / mesh shading 等优化,核心思路一样:**减少每像素计算的光数**。HH 给你基础,你可以扩展到现代实现。

## 16 · 延伸阅读

本仓库本地:
- [day611.md](../day611.md) - day652.md 光照优化全程
- [day576.md](../day576.md) - octahedral encoding

外部稳定 URL:
- DOOM 2016 SIGGRAPH: http://advances.realtimerendering.com/s2016/Siggraph2016IdTech6.pdf
- Unity URP docs: https://docs.unity3d.com/Packages/com.unity.render-pipelines.universal@latest
- Unreal Lumen: https://docs.unrealengine.com/5.0/en-US/lumen-global-illumination-and-reflections-in-unreal-engine/

真实开源源码:
- bevy_pbr: https://github.com/bevyengine/bevy/tree/main/crates/bevy_pbr
- wgpu examples: https://github.com/gfx-rs/wgpu/tree/trunk/wgpu/examples
