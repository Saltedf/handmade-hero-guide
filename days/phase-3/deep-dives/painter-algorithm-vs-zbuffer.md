# 画家算法 vs 深度缓冲

> 本文是 [day107.md](../day107.md)、[day110.md](../day110.md) 的延伸,完整对比 **Painter's Algorithm(画家算法)** 和 **Z-Buffer(深度缓冲)**——3D 渲染里解决「**遮挡**」的两种主流方案。Casey HH 在 Phase 3 用画家算法,Phase 5 切 OpenGL 后用 Z-Buffer。本文详细讲两者的算法、优缺点、何时用哪个。本文自包含,但建议先读 Day 107。

## 1 · 遮挡的根本问题

3D 渲染里多个物体在屏幕同一像素重叠时,**只有最近的应该被看到**。这是几何事实——光从最近物体出发打到观察者,后面物体的光被挡住了。

但渲染时你怎么保证「**最终像素颜色是最近物体的**」?物体画进 framebuffer 的顺序不一定按距离。两种主流解法:画家算法和 Z-Buffer。

## 2 · 画家算法

### 2.1 思路

画家算法来自油画——画家先画背景(远),再画中景,最后画前景(近)。后画的覆盖先画的,自然形成遮挡。

伪代码:

```
sort triangles by depth (far → near)
for triangle in sorted_triangles:
    draw(triangle)      # 直接覆盖 framebuffer
```

### 2.2 实现

Casey HH 用 sort key 编码深度(Day 089):

```rust
fn sort_key(z: f32, layer: u32, texture_id: u32) -> u64 {
    // z 在高位(决定主要顺序),其他在低位(batch 优化)
    let z_bits = (z as u64) & 0xFFFF_FFFF;          // 32 位 z
    let layer_bits = (layer as u64) << 56;          // 高 8 位 layer
    let tex_bits = (texture_id as u64) << 40;       // 中 16 位纹理
    layer_bits | tex_bits | z_bits
}

// 渲染时:
let mut commands: Vec<(u64, Command)> = ...;
commands.sort_by_key(|(k, _)| *k);      // 按 sort key 排序
for (_, cmd) in commands {
    draw(cmd);
}
```

排好序后,远处的先画,近处的后画覆盖——遮挡正确。

### 2.3 优点

- **简单**:不需要额外内存(无 zbuffer),只需要排序。
- **透明物体友好**:后画的 alpha blend 前画的,自然正确。
- **CPU 软渲染快**:排序 O(n log n) 很快,n 是三角形数。

### 2.4 缺点

- **排序成本**:O(n log n),n=10000 时 ~13 万次比较,可接受。
- **多边形相交失败**:两个三角形互相穿插(A 的一半挡 B,B 的一半挡 A),无法用简单排序解决——必须把三角形切分成更小的非相交片段。
- **循环遮挡**:三个三角形 A→B→C→A 互相挡,无法排序。
- **不可见物体也画**:画家算法不知道哪些被挡,所有都画——浪费像素填充率。

## 3 · 深度缓冲(Z-Buffer)

### 3.1 思路

Z-Buffer 换思路:**不排序,但每个像素记录当前最近的深度值**。新像素来时,比较深度,近的覆盖远的。

### 3.2 实现

```rust
pub struct ZBuffer {
    depth: Vec<f32>,         // 0=最近,1=最远
}

impl ZBuffer {
    fn test_and_write(&mut self, x: u32, y: u32, z: f32) -> bool {
        let i = (y * W + x) as usize;
        if z < self.depth[i] {           # 新像素更近
            self.depth[i] = z;
            true
        } else {
            false                         # 被遮挡,丢弃
        }
    }
}

fn draw_pixel_with_z(fb: &mut Vec<u32>, zb: &mut ZBuffer,
                     x: u32, y: u32, z: f32, color: u32) {
    if zb.test_and_write(x, y, z) {
        fb[(y * W + x) as usize] = color;
    }
}
```

每个像素独立判断,绘制顺序无关。

### 3.3 优点

- **顺序无关**:画家算法的痛点消失。
- **多边形相交自然处理**:每像素独立判断。
- **循环遮挡自然处理**:同样。
- **可 Early-Z 优化**:GPU 在 shader 前做 depth test,被遮挡的像素跳过 shader,省计算。

### 3.4 缺点

- **额外内存**:zbuffer 占 framebuffer 同样大小(1080p f32 = 8MB)。
- **透明物体不友好**:透明物体通常不写 zbuffer(否则挡住后面的),需特殊处理。
- **Z-Fighting**:非常接近的两个面深度精度不够,闪烁。详见 [z-buffer-and-depth-testing.md](z-buffer-and-depth-testing.md)。

## 4 · 透明物体的处理差异

这是两者最大实用差异。

### 4.1 画家算法 + 透明

简单——排序后从远到近画,透明物体的 alpha blend 自动正确:

```
1. 远处不透明墙(画)
2. 远处半透明玻璃(画,alpha blend 墙)
3. 中景不透明门(画,覆盖玻璃中心)
4. 前景半透明窗(画,alpha blend 门)
```

后画的覆盖 / blend 前画的,自然形成「**透明层叠**」。

### 4.2 Z-Buffer + 透明

Z-Buffer 单独处理透明很麻烦。考虑:

```
1. 不透明墙 z=10(画,写 zbuffer=10)
2. 半透明玻璃 z=5(画,alpha blend 墙,写 zbuffer=5)
3. 不透明门 z=8(测试 8 > 5,失败,不画——错!)
```

正确做法:**分两 pass**:

```
Pass 1:画所有不透明(开 z test + write)
Pass 2:画所有透明(开 z test,关 z write,从远到近排序)
```

```
Pass 1:墙(z=10),门(z=8)。zbuffer 写 8(门更近)。
Pass 2:玻璃(z=5)。test 5 < 8 通过,但 write=false,玻璃 alpha blend 门。
```

这是 Day 235 切 OpenGL 后的标准流程。

## 5 · 性能对比

### 5.1 CPU 软渲染

画家算法通常更快。原因:

- 无额外内存读写(zbuffer 占内存带宽)。
- 排序成本 O(n log n) 对几千个三角形可忽略。
- 透明物体一次性画完,不用分 pass。

### 5.2 GPU 渲染

Z-Buffer 更快。原因:

- GPU 硬件原生支持 depth test,几乎免费。
- 画家算法的全局排序对 GPU 并行不友好(GPU 喜欢每个像素独立)。
- Early-Z 优化跳过被遮挡的 shader,省百万次计算。

## 6 · 何时用哪个

| 场景 | 推荐 |
|---|---|
| **CPU 软渲染,少多边形** | 画家算法 |
| **CPU 软渲染,海量多边形** | Z-Buffer(避免排序成本) |
| **GPU 渲染** | Z-Buffer + 不透明先画 + 透明后画(sort key 辅助) |
| **2D 游戏(无真 3D)** | 画家算法(sort key) |
| **2.5D(Casey HH)** | 画家算法 |
| **3D FPS / RPG** | Z-Buffer |
| **大量透明粒子** | Z-Buffer + 深度排序粒子(粒子之间用画家) |
| **CAD / 建筑可视化** | Z-Buffer + Reversed-Z |

Casey HH 选画家算法因为:Phase 3 是 2.5D,2.5D 物体的 z 是离散楼层,sort key 简单有效。Phase 5 切 OpenGL 后,3D 物体大量,启用 Z-Buffer 自然。

## 7 · 混合方案

实际项目常混合两者:

- **不透明用 Z-Buffer**:正确高效。
- **透明用画家算法 + sort key**:按 z 排序。
- **特殊场景(粒子、UI)**:可能用 Order-Independent Transparency(OIT),GPU 高级技术。

OIT 有几种实现:

- **Depth Peeling**:多次渲染,每层 peeling 一层透明。质量好但贵(每层一次渲染)。
- **Per-Pixel Linked List**:fragment shader 把透明 fragment 写入 per-pixel linked list,最后排序合成。中间档。
- **Weighted Blended OIT**:简化版,用加权混合近似,质量一般但便宜。Bevy 默认用这种。

## 8 · Rust 实战对比

```rust
// === 画家算法 ===
pub struct PainterRenderer {
    framebuffer: Vec<u32>,
    commands: Vec<(f32 /* z */, Command)>,
}

impl PainterRenderer {
    pub fn submit(&mut self) {
        self.commands.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap()); // 远到近
        for (_, cmd) in &self.commands {
            self.draw_command(cmd);
        }
    }
}

// === Z-Buffer ===
pub struct ZBufferRenderer {
    framebuffer: Vec<u32>,
    zbuffer: Vec<f32>,
}

impl ZBufferRenderer {
    pub fn draw_pixel(&mut self, x: u32, y: u32, z: f32, color: u32) {
        let i = (y * W + x) as usize;
        if z < self.zbuffer[i] {
            self.zbuffer[i] = z;
            self.framebuffer[i] = color;
        }
    }
}
```

画家算法的入口是 `submit`(统一排序后画),Z-Buffer 的入口是 `draw_pixel`(每像素判断)。架构思路完全不同。

## 9 · 历史演化

**1970s**:画家算法(Newell, Newell, Sancha 1972)在 CAD 用,但多边形相交问题大。

**1974**:Edwin Catmull 发明 Z-Buffer,解决相交问题。

**1980s**:SGI 工作站硬件 Z-Buffer,商业化。

**1996**:3dfx Voodoo 第一个消费 GPU,Z-Buffer 硬件加速。

**2000s**:GPU Early-Z 优化,Reversed-Z 精度技巧普及。

**2010s**:OIT 技术成熟,混合方案成为主流(不透明 Z-Buffer + 透明 OIT 或 sort)。

**2020s**:Mesh shading 让光栅化更灵活,Z-Buffer 概念不变。

Casey HH 让你两种都体验——Phase 3 手写画家,Phase 5+ 用 GPU Z-Buffer。理解两者让你能选择适合场景的工具。

## 10 · 总结对比表

| 方面 | 画家算法 | Z-Buffer |
|---|---|---|
| **排序成本** | O(n log n) | O(1) per pixel |
| **多边形相交** | 失败 | 正确 |
| **循环遮挡** | 失败 | 正确 |
| **透明物体** | 友好 | 需分 pass |
| **额外内存** | 无 | zbuffer 同 framebuffer |
| **CPU 性能** | 好 | 一般 |
| **GPU 性能** | 差(并行不友好) | 好(硬件加速 + Early-Z) |
| **Casey HH 用** | Phase 3 | Phase 5+(OpenGL) |

## 11 · 延伸阅读

- [Wikipedia Painter's Algorithm](https://en.wikipedia.org/wiki/Painter%27s_algorithm) — 历史与算法。
- [Wikipedia Z-Buffering](https://en.wikipedia.org/wiki/Z-buffering) — Catmull 1974 原论文背景。
- [LearnOpenGL Depth Testing](https://learnopengl.com/Advanced-OpenGL/Depth-testing) — GPU Z-Buffer 实战。
- [Order-Independent Transparency](https://developer.nvidia.com/content/transparency-or-transparency) — NVIDIA OIT 教程。
- [Weighted Blended OIT Paper](http://jcgt.org/published/0002/02/09/) — McGuire & Bavoil 2013。
- Casey HH Day 107(Z 层 fade)和 Day 235(OpenGL 切换)。
