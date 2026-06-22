# 从零写光栅化器

> 本文是 [day092.md](../day092.md)、[day093.md](../day093.md) 的延伸,完整讲解**软件光栅化器(software rasterizer)**的实现——把 3D 三角形画到 2D framebuffer 的所有算法。Casey HH 在 Phase 3 手写这些,GPU 内部也是同一套数学。本文自包含,但建议先读 Day 092-093。

## 1 · 光栅化器是什么

光栅化(rasterization)是「**把几何(三角形)变成像素**」的过程。3D 渲染管线的最后一步——投影后得到屏幕坐标的三角形,光栅化器决定「**哪些屏幕像素在这个三角形内**,并对每个像素调用 shader 算颜色」。

输入:三角形 3 个顶点(屏幕坐标 + 各种属性如颜色、UV、法线)。
输出:三角形覆盖的所有像素 + 插值后的属性。

```
       vertex 0
       /  \
      /    \
     / 三角形\
    /        \
   vertex 1----vertex 2

   ↓ 光栅化

   像素 像素 像素 像素
   像素 像素 像素
   像素 像素
   像素
```

## 2 · 核心问题:点在三角形内吗?

光栅化的核心算法是「**点-三角形包含测试**」。给定屏幕点 `(px, py)` 和三角形 3 个顶点 `(x0,y0), (x1,y1), (x2,y2)`,判断点是否在三角形内。

### 2.1 叉积法

利用叉积的方向性。对每条边,计算「**点在这条边的哪一侧**」。如果点在 3 条边的同一侧(都是左侧或都是右侧),点在三角形内。

```
edge0 = (x1-x0, y1-y0)
edge1 = (x2-x1, y2-y1)
edge2 = (x0-x2, y0-y2)

point_vec0 = (px-x0, py-y0)
point_vec1 = (px-x1, py-y1)
point_vec2 = (px-x2, py-y2)

cross0 = edge0.x * point_vec0.y - edge0.y * point_vec0.x
cross1 = edge1.x * point_vec1.y - edge1.y * point_vec1.x
cross2 = edge2.x * point_vec2.y - edge2.y * point_vec2.x

# 如果三个 cross 同号(全正或全负),点在三角形内
in_triangle = (cross0 >= 0 && cross1 >= 0 && cross2 >= 0) ||
              (cross0 <= 0 && cross1 <= 0 && cross2 <= 0)
```

2D 叉积就是「**z 分量**」——告诉我们点在边的哪一侧。

### 2.2 重心坐标法

更优雅的方法是「**重心坐标(barycentric coordinates)**」。三角形内任意点 P 可以表示为 `P = α·V0 + β·V1 + γ·V2`,其中 `α + β + γ = 1`,且 `α, β, γ ≥ 0`(在三角形内)。

```
α = area(P, V1, V2) / area(V0, V1, V2)
β = area(V0, P, V2) / area(V0, V1, V2)
γ = 1 - α - β

# 面积用叉积
area(a, b, c) = ((b.x-a.x) * (c.y-a.y) - (b.y-a.y) * (c.x-a.x)) / 2
```

重心坐标的好处:**顶点属性直接插值**。比如顶点颜色 `C0, C1, C2`,P 的颜色 = `α·C0 + β·C1 + γ·C2`。UV、法线、深度同理。这是 GPU fragment shader 拿到的「**插值属性**」。

## 3 · 光栅化主循环

有了点-三角形测试,光栅化就是:

```python
def rasterize_triangle(framebuffer, v0, v1, v2, color):
    # 计算三角形 bounding box
    min_x = min(v0.x, v1.x, v2.x)
    max_x = max(v0.x, v1.x, v2.x)
    min_y = min(v0.y, v1.y, v2.y)
    max_y = max(v0.y, v1.y, v2.y)

    # 遍历 bounding box 内每个像素
    for py in range(min_y, max_y + 1):
        for px in range(min_x, max_x + 1):
            # 算重心坐标
            α, β, γ = barycentric(px + 0.5, py + 0.5, v0, v1, v2)
            if α >= 0 and β >= 0 and γ >= 0:        # 在三角形内
                framebuffer[py * width + px] = color
```

`+0.5` 是「**像素中心采样**」——像素坐标 (px, py) 的中心是 (px+0.5, py+0.5),这样像素不会一直采样到边界。

## 4 · 顶点属性插值

三角形 3 个顶点有不同颜色 / UV / 法线。光栅化时,每个像素插值得到这些属性。

```python
def rasterize_with_attributes(v0, v1, v2):
    for px, py in bounding_box:
        α, β, γ = barycentric(px, py, v0, v1, v2)
        if α >= 0 and β >= 0 and γ >= 0:
            # 插值颜色
            color = α * v0.color + β * v1.color + γ * v2.color
            # 插值 UV(纹理坐标)
            uv = α * v0.uv + β * v1.uv + γ * v2.uv
            # 插值深度
            depth = α * v0.depth + β * v1.depth + γ * v2.depth
            # 用 uv 采样纹理得到最终颜色
            tex_color = sample_texture(uv)
            draw_pixel(px, py, color * tex_color, depth)
```

注意:**深度插值**在透视投影下不正确。因为透视投影后深度是 `1/Z` 函数,直接线性插值 Z 会得到错误结果。正确做法是**透视正确插值(perspective-correct interpolation)**:对每个属性 `A`,实际插值 `A/Z`,然后除以插值后的 `1/Z`。Day 235 切 OpenGL 后 GPU 硬件自动做。

## 5 · Scanline 光栅化

上面那个 bounding box 方法对每个像素做完整重心坐标计算——慢。优化:**Scanline 光栅化**,按行处理,每行只算两个边界点。

```
算法:
1. 把 3 个顶点按 y 排序:v0 (top), v1 (middle), v2 (bottom)
2. 三角形分上半(v0→v1)和下半(v1→v2)两段
3. 对每个 y,在 v0→v2 边和 v0→v1 边(或 v1→v2 边)上找 x_left, x_right
4. 画 x_left 到 x_right 的水平线
```

每行只算两次「**边和水平线交点**」,然后填充。比每像素重心坐标快 3-10×。

Casey HH Day 092-093 用类似优化。

## 6 · 优化:Tile-based 光栅化

GPU 现代做法:**Tile-based 光栅化**。把屏幕分成 16×16 或 32×32 的小块(tile)。对每个 tile,确定哪些三角形覆盖它,然后 tile 内光栅化。

好处:tile 内像素在 L1 cache,内存访问局部性好。移动 GPU(PowerVR、Mali、Adreno)全用 tile-based,省带宽省电。

CPU 软渲染也可以用——Casey HH 没用,因为他的三角形数量少,bounding box 够。Day 121+ SIMD 优化时会涉及。

## 7 · Rust 实现示例

完整最小光栅化器:

```rust
pub struct Vertex {
    pub x: f32,
    pub y: f32,
    pub color: [f32; 3],
}

pub struct Rasterizer {
    pub width: u32,
    pub height: u32,
    pub framebuffer: Vec<[u8; 4]>,
}

impl Rasterizer {
    pub fn new(w: u32, h: u32) -> Self {
        Self {
            width: w, height: h,
            framebuffer: vec![[0, 0, 0, 255]; (w * h) as usize],
        }
    }

    fn edge(ax: f32, ay: f32, bx: f32, by: f32, cx: f32, cy: f32) -> f32 {
        (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    }

    pub fn triangle(&mut self, v0: Vertex, v1: Vertex, v2: Vertex) {
        let min_x = v0.x.min(v1.x).min(v2.x).floor() as i32;
        let max_x = v0.x.max(v1.x).max(v2.x).ceil() as i32;
        let min_y = v0.y.min(v1.y).min(v2.y).floor() as i32;
        let max_y = v0.y.max(v1.y).max(v2.y).ceil() as i32;

        let area = Self::edge(v0.x, v0.y, v1.x, v1.y, v2.x, v2.y);
        if area.abs() < 1e-6 { return; }       // 退化三角形
        let inv_area = 1.0 / area;

        for py in min_y.max(0)..=max_y.min(self.height as i32 - 1) {
            for px in min_x.max(0)..=max_x.min(self.width as i32 - 1) {
                let pxc = px as f32 + 0.5;
                let pyc = py as f32 + 0.5;

                // 重心坐标(用 edge function)
                let w0 = Self::edge(v1.x, v1.y, v2.x, v2.y, pxc, pyc) * inv_area;
                let w1 = Self::edge(v2.x, v2.y, v0.x, v0.y, pxc, pyc) * inv_area;
                let w2 = 1.0 - w0 - w1;

                if w0 >= 0.0 && w1 >= 0.0 && w2 >= 0.0 {
                    // 插值颜色
                    let r = (w0 * v0.color[0] + w1 * v1.color[0] + w2 * v2.color[0]) * 255.0;
                    let g = (w0 * v0.color[1] + w1 * v1.color[1] + w2 * v2.color[1]) * 255.0;
                    let b = (w0 * v0.color[2] + w1 * v1.color[2] + w2 * v2.color[2]) * 255.0;
                    self.framebuffer[(py as u32 * self.width + px as u32) as usize] =
                        [r as u8, g as u8, b as u8, 255];
                }
            }
        }
    }
}

fn main() {
    let mut r = Rasterizer::new(800, 600);
    r.triangle(
        Vertex { x: 400.0, y: 100.0, color: [1.0, 0.0, 0.0] },  // 顶 红
        Vertex { x: 100.0, y: 500.0, color: [0.0, 1.0, 0.0] },  // 左下 绿
        Vertex { x: 700.0, y: 500.0, color: [0.0, 0.0, 1.0] },  // 右下 蓝
    );
    // 保存 PNG 略
}
```

运行后看到一个三角形,顶点红、左下绿、右下蓝,内部是平滑的颜色渐变(顶点颜色插值)。

## 8 · 抗锯齿(Anti-Aliasing)

光栅化的边界天然锯齿——像素要么全在三角形内,要么全在外。**Anti-Aliasing(AA)** 软化边界。

**MSAA(Multi-Sample AA)**:每像素采 4/8/16 个子样本,平均。GPU 硬件支持。质量好性能不错。

**SSAA(Supersample AA)**:渲染 2× 分辨率然后 downsample。最简单但最贵。

**FXAA(Fast Approximate AA)**:后处理,在 framebuffer 上检测边缘并模糊。便宜但模糊。

**TAA(Temporal AA)**:跨帧累积采样,效果好但需要 motion vector。现代引擎主流。

Casey HH Phase 3 无 AA,Day 235+ 切 OpenGL 后可启用 MSAA。

## 9 · 性能数据

软件光栅化(单核 CPU):

- 1080p 单三角形 bounding box 法:~1ms。
- 1080p scanline 法:~0.3ms。
- SIMD 优化:~0.1ms。
- 1080p 一帧 1000 个三角形:~100ms(无优化)→ 10ms(SIMD)。

GPU 同样工作:<1ms(硬件并行)。

软件光栅化主要瓶颈是**像素填充率**(pixel fill rate)——每秒能写多少像素。CPU 软渲染 ~1 G pixel/s,GPU ~50 G pixel/s。

## 10 · Rust 生态

- **`swbuf` / `minifb`**:简单 framebuffer 抽象,光栅化器自己写。
- **`softbuffer`**:rust-windowing 出品,Wayland/X11/Win 跨平台。
- **`tiny-skia`**:2D 矢量光栅化器,Skia 子集。
- **`vger`**:Bevy 用的简单 2D 光栅化器。
- **`lyon`**:路径光栅化(SVG 风格)。

Casey HH 教学版手写所有这些,理解原理后用生态库就是 API 翻译。

## 11 · 历史演化

**1970s**:Edwin Catmull 在 Utah 大学做第一个软件光栅化器。
**1980s**:SGI 工作站硬件光栅化,但贵。
**1996**:3dfx Voodoo 第一个消费 GPU,光栅化硬件加速。
**2000s**:GPU 通用化,可编程 shader,光栅化仍是固定管线。
**2010s**:Tile-based 光栅化在移动 GPU 普及,软件光栅化退出主流(除了教学和工具)。
**2020s**:Mesh shading 让光栅化可编程,但传统光栅化仍是主流。

Casey HH 教软件光栅化让你理解 GPU 黑盒——硬件加速不变内核。

## 12 · 延伸阅读

- [Scratchapixel Rasterization Practical Implementation](https://www.scratchapixel.com/lessons/3d-basic-rendering/rasterization-practical-implementation) — 从零实现软件光栅化。
- [LearnOpenGL Hello Triangle](https://learnopengl.com/Getting-started/Hello-Triangle) — GPU 硬件光栅化。
- [The Barycentric Trick](https://www.scratchapixel.com/lessons/3d-basic-rendering/rasterization-practical-implementation/rasterization-stage) — 重心坐标详解。
- [Tiny Renderer Wiki](https://github.com/ssloy/tinyrenderer/wiki) — 500 行 C++ 从零写光栅化器,经典教学。
- [ryan-isaksen's Software Rasterization in Rust](https://github.com/ryanisaacg/softbuffer) — Rust 软渲染参考。
