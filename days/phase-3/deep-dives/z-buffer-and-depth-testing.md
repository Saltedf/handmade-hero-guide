# 深度缓冲与深度测试

> 本文是 [day107.md](../day107.md)、[day108.md](../day108.md) 的延伸,完整解释**深度缓冲(Z-Buffer)**——3D 渲染里解决「**遮挡**」的标准方案。Casey HH 在 Phase 3 用的是 sort key 排序(画家算法),Phase 5 切到 OpenGL 后会启用 GPU 深度缓冲。本文从零讲清两者差异、Z-Buffer 算法、Z-Fighting 问题、深度精度。本文自包含,但建议先读 Day 107 和 Day 108。

## 1 · 遮挡问题

3D 渲染有个根本问题:**当多个物体在屏幕同一像素重叠时,谁应该被看到**?

物理上答案简单——离观察者最近的应该被看到。但渲染顺序不一定按距离——你可能先画远物体再画近物体,也可能反过来。怎么保证最终像素颜色是最近物体的?

两种主流解法:

1. **画家算法(Painter's Algorithm)**:按距离从远到近排序,远物体先画,近物体后画覆盖。Casey HH 用这种。
2. **深度缓冲(Z-Buffer / Depth Buffer)**:每个像素除了颜色,还存深度值。画新像素时,比较深度,近的覆盖远的。

两者各有 trade-off,本文详细对比。

## 2 · 画家算法

画家算法的思路来自油画——画家先画背景(远),再画中景,最后画前景(近)。后画的覆盖先画的,自然形成遮挡。

实现:

```
1. 把所有要画的物体按 z 从远到近排序
2. 按顺序逐个画(直接覆盖 framebuffer)
```

优点:**简单**。透明物体友好(后画的和前面 alpha blend)。CPU 软渲染易实现。

缺点:**排序成本 O(n log n)**;**多边形相交时排序无解**(两个三角形互相穿插,没有简单的「谁在前」);**循环遮挡** —— 三个三角形 A→B→C→A 互相挡,无法排序。

Casey HH 用 sort key 解决排序——把「**z 深度**」编码到 u64 sort key 的高位(Day 089)。sort 后从远到近画。

## 3 · 深度缓冲算法

Z-Buffer 算法(Edwin Catmull, 1974 年发明)换思路:**不排序,但每个像素记录当前最近的深度值**。

实现:

```
framebuffer: Vec<u32>            // 颜色缓冲
zbuffer: Vec<f32>                // 深度缓冲,初始化为 +∞

fn draw_pixel(x, y, z, color):
    if z < zbuffer[y * W + x]:   # 新像素更近
        zbuffer[y * W + x] = z
        framebuffer[y * W + x] = color
    # 否则丢弃(被遮挡)
```

绘制顺序无关——每个像素独立判断「**新来的更近吗**」。这解决了画家算法的痛点。

优点:**顺序无关**;**多边形相交自然处理**;**O(1) per pixel**。

缺点:**内存开销**(zbuffer 占 framebuffer 同样大小,1080p 约 8MB f32);**透明物体不友好**(透明物体通常不写 zbuffer,否则会挡住后面的透明物体);**深度精度问题**(Z-Fighting,见下)。

GPU 普遍用 Z-Buffer。Casey HH 的 CPU 软渲染用画家算法(因为没那么多多边形,sort 够快)。

## 4 · 深度值的来源

每个像素的深度值从哪来?**投影矩阵计算**。Day 108 推导过:`NDC_z = (a·Z + b) / (-Z)`,其中 a, b 是投影矩阵 m22, m23。

OpenGL NDC Z 范围 [-1, 1],然后 viewport transform 把 NDC Z 映射到 [0, 1] 存入 depth buffer:

```
depth = (NDC_z + 1) / 2
```

`depth = 0` 对应 near 平面,`depth = 1` 对应 far 平面。深度测试通常用 `less`(更小的 depth 值 = 更近 = 通过)。

## 5 · Z-Fighting 问题

**Z-Fighting**:两个面非常接近(距离差小于深度精度),深度测试无法区分,渲染结果闪烁(一帧 A 在前,下一帧 B 在前)。

为什么有这个问题?透视投影下深度不是线性分布——`depth = (a·Z + b) / (-Z)` 是 1/Z 函数,近处精度高(深度值变化大),远处精度低(深度值变化小)。

具体例子:FOV=60°, near=0.1, far=1000。near 处 depth=0,near+0.001 处 depth ≈ 0.001。far-1 处 depth ≈ 0.999,far 处 depth=1。同样的世界距离(0.001 vs 1),近处深度差 0.001,远处深度差 0.000001——精度差 1000 倍。

解决方案:

1. **增大 near 平面**:near=0.1 改 near=1.0,精度大幅提升。但 near 太大会裁掉近处物体。
2. **缩小 far 平面**:far=1000 改 far=100,远处精度提升。
3. **Reversed-Z**:把 depth 反转(1=near, 0=far),配合浮点深度缓冲(f32)让精度分布更均匀。这是现代引擎标准做法。
4. **Polygon offset**:强制让某些多边形深度偏移一点,避免共面 z-fighting。

Casey HH 在 Phase 3 不涉及(用画家算法)。Phase 5 切 OpenGL 后要处理。

## 6 · 深度测试功能(GPU)

OpenGL depth test 的标准 API:

```c
glEnable(GL_DEPTH_TEST);                                  // 启用
glDepthFunc(GL_LESS);                                     // 比较函数:更近通过
glDepthMask(GL_TRUE);                                     // 写入 zbuffer
glClear(GL_DEPTH_BUFFER_BIT);                             // 清 zbuffer 到 1.0

// 透明物体时关 depth write(避免挡住后面):
glDepthMask(GL_FALSE);
draw_transparent();
glDepthMask(GL_TRUE);
```

`glDepthFunc` 可选 `GL_NEVER / GL_LESS / GL_EQUAL / GL_LEQUAL / GL_GREATER / GL_NOTEQUAL / GL_GEQUAL / GL_ALWAYS`。Casey HH 用 `GL_LESS`(更近通过)。

**Early-Z(早深度测试)**:GPU 在 fragment shader 之前做深度测试,丢弃被遮挡的像素,省 shader 计算。但要求 shader 不修改 depth(`layout(depth_any)` GLSL qualifier)。Casey HH 在 Phase 6+ 的 shader 里会注意这个。

## 7 · 透明物体与深度缓冲

透明物体和深度缓冲冲突。考虑:

```
1. 不透明墙 z=10(画)
2. 半透明玻璃 z=5(画)
3. 不透明门 z=8(在墙和玻璃之间)
```

如果全部开 depth test + write:

1. 墙写 zbuffer[10], framebuffer[墙色]
2. 玻璃 z=5 < 10,通过测试,写 zbuffer[5], framebuffer[玻璃色 blend 墙]
3. 门 z=8 > 5,**测试失败,不画**——错误!门在玻璃后面但应该在玻璃和墙之间。

正确做法:**分两 pass**:

- Pass 1:只画不透明物体,开 depth test + write。
- Pass 2:画透明物体,开 depth test,**关 depth write**,从远到近排序。

这样:

1. Pass 1 画墙(z=10)和门(z=8),depth buffer 写 8(门更近)。
2. Pass 2 画玻璃(z=5),depth=5 < 8 通过测试,但不写 depth,玻璃色 blend 门。

这就是 Day 235 切 OpenGL 后的标准渲染流程。Casey HH Phase 3 用画家算法简化了这个——所有物体一视同仁,从远到近画,透明和不透明混在一起。

## 8 · Reversed-Z 现代技巧

传统 depth buffer 用 `[0=近, 1=远]`,f32 精度在 0 附近高、在 1 附近低,但透视投影后远处深度值集中在 1 附近——**精度最差的地方遇到最多的物体**。

Reversed-Z 技巧:把 depth 反转,`[1=近, 0=远]`。配合 f32(指数分布,1 附近精度低、0 附近精度高),远处深度集中在 0 附近,精度反而高。

实现:

- 投影矩阵 m22, m23 反号。
- `glDepthFunc(GL_GREATER)`(更大 = 更近 = 通过)。
- `glClearDepth(0.0)`(清 depth buffer 到 0,不是 1)。

Upchurch 和 Wynn 2012 的 NVIDIA 论文证明:Reversed-Z + f32 depth buffer 在 `near=0.1, far=1e6` 这种极端范围下精度都足够。现代游戏引擎(Unreal、Unity HDRP)默认用 Reversed-Z。

## 9 · Rust 实现示例

CPU 软渲染 zbuffer(教学用):

```rust
pub struct ZBuffer {
    pub width: u32,
    pub height: u32,
    pub depth: Vec<f32>,         // 0 = 最近,1 = 最远(初始化 1.0)
}

impl ZBuffer {
    pub fn new(w: u32, h: u32) -> Self {
        Self {
            width: w, height: h,
            depth: vec![1.0; (w * h) as usize],
        }
    }

    pub fn test_and_write(&mut self, x: u32, y: u32, z: f32) -> bool {
        let i = (y * self.width + x) as usize;
        if z < self.depth[i] {                    # 更近,通过
            self.depth[i] = z;
            true
        } else {
            false
        }
    }

    pub fn clear(&mut self) {
        for d in &mut self.depth { *d = 1.0; }
    }
}

pub fn draw_triangle_with_zbuffer(
    framebuffer: &mut [u32],
    zbuffer: &mut ZBuffer,
    vertices: &[([f32; 2], f32, u32); 3],         # (screen_pos, depth, color)
) {
    // 简化:只画三角形 bounding box 内的像素
    let min_x = vertices.iter().map(|v| v.0[0]).fold(f32::INFINITY, f32::min) as i32;
    let max_x = vertices.iter().map(|v| v.0[0]).fold(f32::NEG_INFINITY, f32::max) as i32;
    let min_y = vertices.iter().map(|v| v.0[1]).fold(f32::INFINITY, f32::min) as i32;
    let max_y = vertices.iter().map(|v| v.0[1]).fold(f32::NEG_INFINITY, f32::max) as i32;

    for y in min_y.max(0)..=max_y.min(zbuffer.height as i32 - 1) {
        for x in min_x.max(0)..=max_x.min(zbuffer.width as i32 - 1) {
            // 重心坐标插值(简化:实际要用 barycentric coordinates)
            let (bx, by, bz) = barycentric_interpolation(vertices, x as f32, y as f32);
            if bx < 0.0 || by < 0.0 || bz < 0.0 { continue; }    # 在三角形外

            let depth = bx * vertices[0].1 + by * vertices[1].1 + bz * vertices[2].1;
            let color = vertices[0].2;     # 简化:用第一个顶点颜色

            if zbuffer.test_and_write(x as u32, y as u32, depth) {
                framebuffer[(y as u32 * zbuffer.width + x as u32) as usize] = color;
            }
        }
    }
}
```

`barycentric_interpolation` 是「重心坐标插值」,用于在三角形内插值任意顶点属性。本文不展开,Day 093 的纹理四边形已经讲过类似原理。

## 10 · 性能考虑

Z-Buffer 的开销:

- **内存**:zbuffer 占 framebuffer 同样大小(1080p f32 = 8MB)。GPU 显存。
- **每像素读写**:每个像素一次 depth 比较 + 可能一次 depth write。GPU 硬件原生。
- **Early-Z 优化**:GPU 在 shader 前做 depth test,被遮挡的 fragment 直接跳过 shader 计算。性能提升 2-10×。

CPU 软渲染 zbuffer 慢——内存带宽瓶颈。Casey HH 不用 zbuffer 是对的(他的 polygon 数量少,sort key 够)。Phase 5 切 OpenGL 后用 GPU zbuffer 性能起飞。

## 11 · 总结

| 方面 | 画家算法 | Z-Buffer |
|---|---|---|
| **排序** | O(n log n) 全局 | O(1) 每像素 |
| **相交多边形** | 失败 | 正确 |
| **透明物体** | 友好 | 需要特殊处理 |
| **内存** | 无额外 | zbuffer(同 framebuffer) |
| **CPU vs GPU** | CPU 友好 | GPU 友好 |
| **Casey HH 用** | Phase 3 | Phase 5+(OpenGL) |

理解两者差异和 trade-off,你就理解了 3D 渲染里「**遮挡**」这一根本问题的完整解空间。Casey HH 在 Phase 3 用画家算法是务实——少代码、CPU 友好、够教学。Phase 5 切 GPU 后用 Z-Buffer 是必然——GPU 硬件加速、大规模多边形。

## 12 · 延伸阅读

- [LearnOpenGL Depth Testing](https://learnopengl.com/Advanced-OpenGL/Depth-testing) — OpenGL depth buffer 完整教程。
- [Upchurch & Wynn 2012 NVIDIA Reversed-Z Paper](https://www.nvidia.com/en-us/drivers/depthbounds/) — Reversed-Z 精度分析。
- [Scratchapixel Rendering Triangle with Z-Buffer](https://www.scratchapixel.com/lessons/3d-basic-rendering/rasterization-practical-implementation) — CPU 软渲染 zbuffer 实现。
- [Catmull 1974 Z-Buffer Original Paper](https://en.wikipedia.org/wiki/Z-buffering) — 历史背景。
- [OpenGL glDepthFunc spec](https://www.khronos.org/registry/OpenGL-Refpages/gl4/html/glDepthFunc.xhtml) — 官方文档。
