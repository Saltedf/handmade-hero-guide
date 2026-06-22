# 深入:k-d tree 构建与遍历(光线投射)

> Day 611-635 的光照系统大量用 raycast——从光源到 voxel 表面,看光路是否被挡。Casey 用 grid raycaster(DDA)。但工业级 ray tracer 用 **k-d tree**(k-dimensional tree)。本文讲 k-d tree 的构造、遍历、和 voxel grid raycaster 的对比。

## 1 · 为什么需要 k-d tree

考虑光线追踪场景:100 万个三角形,每帧 N 条光线(1080p = 2M 光线)。朴素做法:每条光线检查所有三角形,O(N*M) = 2 * 10^12,不可能实时。

**加速结构**(acceleration structure)的核心:**把空间分块,光线只查它经过的块**。

- **Uniform grid**:voxel 网格,DDA 遍历(Casey 用)
- **k-d tree**:二叉空间分割
- **BVH**(bounding volume hierarchy):层次包围盒
- **Octree**:八叉树

每种适合不同场景。k-d tree 适合**静态场景**(构造慢但遍历快),BVH 适合**动态场景**(更新快)。

## 2 · k-d tree 原理

### 2.1 定义

k-d tree 是二叉树,每个节点代表 k 维空间的一个 axis-aligned 切分平面。

```
       root: split x=5
       /          \
   x<5              x>=5
   /  \             /  \
 y<3   y>=3       z<2   z>=2
 /\     /\         /\    /\
...    ...        ...   ...
```

每个节点存:

- 切分轴(x / y / z)
- 切分位置
- 左右子节点(或叶子时,几何列表)

### 2.2 构造(中位数分割)

简单构造算法:

1. 选切分轴(循环 x → y → z → x ...)
2. 沿该轴排序所有三角形的中心
3. 取中位数作切分位置
4. 左子 = 中位数左侧,右子 = 右侧
5. 递归到叶子(三角数 < 阈值)

```rust
struct KdNode {
    axis: Axis, // X / Y / Z
    split: f32,
    left: Box<KdNode>,
    right: Box<KdNode>,
}

enum KdTree {
    Internal(KdNode),
    Leaf(Vec<usize>), // 三角形 index 列表
}

fn build(triangles: &[Triangle], depth: u32) -> KdTree {
    if triangles.len() <= 4 || depth > 20 {
        return KdTree::Leaf(/* triangle indices */);
    }
    let axis = match depth % 3 { 0 => Axis::X, 1 => Axis::Y, _ => Axis::Z };
    let mut centers: Vec<_> = triangles.iter().map(|t| t.center[axis]).collect();
    centers.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let split = centers[centers.len() / 2];
    let (left, right): (Vec<_>, Vec<_>) = triangles.iter().cloned()
        .partition(|t| t.center[axis] < split);
    KdTree::Internal(KdNode {
        axis, split,
        left: Box::new(build(&left, depth + 1)),
        right: Box::new(build(&right, depth + 1)),
    })
}
```

### 2.3 高级构造:SAH

中位数分割简单但不是最优。**Surface Area Heuristic**(SAH,表面积启发)是工业标准:

- 切分位置选"最小化遍历成本"
- 成本 = P(左) * C(左) + P(右) * C(右),P 是光线经过该子节点的概率(基于表面积)
- 试多个候选位置,选成本最小的

SAH 给最优 k-d tree(成本意义上),但构造慢 10 倍。实时渲染用预计算。

## 3 · 遍历(ray casting)

光线从相机出发,遍历 k-d tree。算法:**递归下降,先近后远**。

```rust
fn traverse(tree: &KdTree, ray: &Ray) -> Option<Hit> {
    let mut stack = Vec::new();
    let mut node = tree;
    loop {
        match node {
            KdTree::Leaf(triangles) => {
                for &idx in triangles {
                    if let Some(hit) = ray_triangle(ray, &scene.triangles[idx]) {
                        return Some(hit);
                    }
                }
                // 弹 stack 继续
                if let Some(parent) = stack.pop() {
                    node = parent;
                } else {
                    return None;
                }
            }
            KdTree::Internal(n) => {
                // 决定先去左还是右
                let t_split = (n.split - ray.origin[n.axis]) / ray.dir[n.axis];
                let (near, far) = if ray.origin[n.axis] < n.split {
                    (&n.left, &n.right)
                } else {
                    (&n.right, &n.left)
                };
                // 如果光线远端没进入远子树,只走近
                if t_split > ray.t_max || t_split < 0 {
                    stack.push(far);
                    node = near;
                } else {
                    // 同时穿两子树
                    node = near;
                    stack.push(far);
                }
            }
        }
    }
}
```

**栈式遍历**避免递归开销。stack 存"待访问的远端子树",优先走近端,如果近端没 hit 才回远端。

### 3.1 复杂度

平衡 k-d tree 遍历复杂度 **O(log N)**——N 三角形,树深 log N,每层 O(1) 工作。

100 万三角形,log2(10^6) ≈ 20 层。每条光线 20 节点访问 + 少量叶子三角形 = 极快。

对比朴素 O(N),加速 50000 倍。

## 4 · k-d tree vs grid vs BVH

### 4.1 Uniform grid

voxel grid 是 uniform grid 特例:

- 构造 O(1)(数据即结构)
- 遍历 O(grid cells traversed by ray)
- 适合**均匀分布**的几何

非均匀(三角形集中在某区域)时浪费——空 grid cell 仍遍历。

Casey 的 voxel raycaster 是 grid,**几何均匀**(每 voxel 1 三角形),所以 grid 简单有效。

### 4.2 BVH(Bounding Volume Hierarchy)

BVH 和 k-d tree 类似,但用 bounding box(包围盒)而不是切分平面:

```
root: AABB of entire scene
  /      \
left AABB   right AABB
  / \         / \
...  ...    ...  ...
```

遍历类似,但**几何在叶子**,不"分割空间"。

**优势**:支持动态场景——物体移动后,只更新该物体的 AABB,BVH 整体仍有效。k-d tree 要重建。

**劣势**:cache locality 比 k-d tree 略差(节点是 AABB,大)。

工业 RTX 渲染用 BVH(RTX 硬件加速 BVH)。

### 4.3 Octree

八叉树:每节点 8 个子节点(空间八分)。

- 简单
- 自适应(空区域合并)
- 但 vs k-d tree,k-d tree 分割更灵活(任意平面,不限于八分)

游戏用 octree 做 broad-phase collision,ray tracer 多用 k-d tree / BVH。

## 5 · Rust 实现

完整 k-d tree(ray trace triangles):

```rust
use glam::{Vec3, Vec4};

#[derive(Clone, Copy, Debug)]
struct Triangle { v0: Vec3, v1: Vec3, v2: Vec3 }

impl Triangle {
    fn center(&self) -> Vec3 {
        (self.v0 + self.v1 + self.v2) / 3.0
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
enum Axis { X, Y, Z }

impl Axis {
    fn next(self) -> Self {
        match self { Self::X => Self::Y, Self::Y => Self::Z, Self::Z => Self::X }
    }
    fn get(self, v: Vec3) -> f32 {
        match self { Self::X => v.x, Self::Y => v.y, Self::Z => v.z }
    }
}

enum KdTree {
    Leaf { triangles: Vec<usize> },
    Internal { axis: Axis, split: f32, left: Box<KdTree>, right: Box<KdTree> },
}

fn build(triangles: &[Triangle], indices: Vec<usize>, axis: Axis, depth: u32) -> KdTree {
    if indices.len() <= 4 || depth > 20 {
        return KdTree::Leaf { triangles: indices };
    }
    let mut centers: Vec<_> = indices.iter().map(|&i| axis.get(triangles[i].center())).collect();
    centers.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let split = centers[centers.len() / 2];
    let (left_idx, right_idx): (Vec<_>, Vec<_>) = indices.into_iter()
        .partition(|&i| axis.get(triangles[i].center()) < split);
    KdTree::Internal {
        axis, split,
        left: Box::new(build(triangles, left_idx, axis.next(), depth + 1)),
        right: Box::new(build(triangles, right_idx, axis.next(), depth + 1)),
    }
}

struct Ray { origin: Vec3, dir: Vec3, t_max: f32 }

fn ray_triangle(ray: &Ray, t: &Triangle) -> Option<f32> {
    // Möller-Trumbore 算法
    let edge1 = t.v1 - t.v0;
    let edge2 = t.v2 - t.v0;
    let h = ray.dir.cross(edge2);
    let a = edge1.dot(h);
    if a.abs() < 1e-8 { return None; }
    let f = 1.0 / a;
    let s = ray.origin - t.v0;
    let u = f * s.dot(h);
    if u < 0.0 || u > 1.0 { return None; }
    let q = s.cross(edge1);
    let v = f * ray.dir.dot(q);
    if v < 0.0 || u + v > 1.0 { return None; }
    let t_hit = f * edge2.dot(q);
    if t_hit > 1e-8 && t_hit < ray.t_max { Some(t_hit) } else { None }
}

fn traverse<'a>(tree: &'a KdTree, triangles: &'a [Triangle], ray: &mut Ray) -> Option<&'a Triangle> {
    let mut stack: Vec<(&KdTree, f32, f32)> = Vec::new();
    let mut current: &KdTree = tree;
    let mut t_min = 0.0;
    let mut t_max = ray.t_max;
    let mut result = None;

    loop {
        match current {
            KdTree::Leaf { triangles: tri_indices } => {
                for &idx in tri_indices {
                    if let Some(t) = ray_triangle(ray, &triangles[idx]) {
                        ray.t_max = t;
                        result = Some(&triangles[idx]);
                    }
                }
                if let Some((next, nt_min, nt_max)) = stack.pop() {
                    current = next;
                    t_min = nt_min;
                    t_max = nt_max.min(ray.t_max);
                } else {
                    return result;
                }
            }
            KdTree::Internal { axis, split, left, right } => {
                let origin_a = axis.get(ray.origin);
                let dir_a = axis.get(ray.dir);
                let t_split = if dir_a.abs() > 1e-8 {
                    (*split - origin_a) / dir_a
                } else if origin_a < *split {
                    -1.0
                } else {
                    1.0
                };
                let (near, far) = if origin_a < *split { (left, right) } else { (right, left) };
                if t_split >= t_max || t_split < 0 {
                    current = near;
                } else if t_split <= t_min {
                    current = far;
                } else {
                    stack.push((far, t_split, t_max));
                    current = near;
                    t_max = t_split;
                }
            }
        }
    }
}
```

## 6 · 性能基准

100 万三角形场景,1080p(2M 光线):

| 算法 | 时间 |
|---|---|
| Naive(每光线查所有) | 几小时 |
| Uniform grid | ~50 ms |
| BVH | ~10 ms |
| k-d tree (median split) | ~5 ms |
| k-d tree (SAH) | ~3 ms |
| RTX 硬件 | <1 ms |

k-d tree + SAH 是软件 ray tracer 的极限。

## 7 · 何时用 k-d tree

### 7.1 适合

- 静态场景(构造一次,反复查询)
- 高密度几何(三角形多)
- 高质量 ray tracing(CGI / 离线渲染)

### 7.2 不适合

- 动态场景(每帧重建慢)
- 简单几何(三角形少,uniform grid 够)
- 实时游戏(BVH 更适合)

### 7.3 Casey 为什么不用

HH 的世界是 voxel grid,几何均匀——uniform grid(DDA)已经够好。k-d tree 是 over-engineering。

但 Casey 在 Day 611-615 提到了 k-d tree 作为可选优化——如果未来加复杂几何(角色 mesh),可以考虑。

## 8 · 现代 RTX

NVIDIA RTX(2018+)硬件加速 ray tracing:

- **RT core**:专门做 BVH 遍历 + triangle intersection
- **Tensor core**:DLSS 等 ML 应用
- **API**:DXR(DirectX Raytracing)/ Vulkan Ray Tracing

RTX 把 k-d tree / BVH 的"软件"遍历变成"硬件"——每条光线纳秒级。

未来 RTX 普及后,游戏 ray tracing 不再是奢侈品。但 HH 时代(2014-2024)RTX 还在早期,Casey 用 grid。

## 9 · 总结

k-d tree 是 ray tracing 的核心加速结构。它的关键贡献:

- **O(log N) 遍历**:从 O(N) 加速 50000 倍
- **自适应分割**:密集区域分割深,稀疏浅
- **SAH 最优**:工程上接近理论最优

Casey 的 HH 没用 k-d tree(voxel grid 够),但理解 k-d tree 让你能读懂现代 ray tracer(PBRT、Mitsuba、Embree)。

Rust 生态:`bvh` crate、`kdtree` crate 提供实现。

## 10 · 延伸阅读

本仓库本地:
- [day611.md](../day611.md) - day635.md 光照系统
- [day641.md](../day641.md) - flood fill

外部稳定 URL:
- PBRT Chapter 4 (Primitives and Intersection Acceleration): https://www.pbr-book.org/3ed-2018/Primitives_and_Intersection_Acceleration
- Real-Time Rendering Chapter 19 (ray tracing)
- Wald's thesis on SAH: https://www.gpu.cz/projects/DiplomaWald.pdf

真实开源源码:
- Embree(Intel's ray tracer): https://github.com/embree/embree
- bvh crate: https://github.com/jonas-schievink/bvh
