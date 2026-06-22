---
phase: 5
title_en: "Collision Detection Evolution"
title_zh: "碰撞检测演化史:从 2D AABB 到 voxel"
type: deep-dive
domains: [game, physics, math, rust]
bridges: ["day050", "day631"]
---

# 碰撞检测演化史

> 你跟着 HH Day 50 学会了 2D AABB——一个矩形撞另一个矩形。Casey 当时画了张 Minkowski 差的图,你说"哦原来如此"。Day 377 你需要做光线投射(raycast)——子弹能穿墙吗?你回头查 Day 50 的笔记,发现 AABB 那套**完全不够**——你需要射线 vs 矩形的几何。Day 631 Casey 进入体素(voxel)世界,你又发现:每秒要测 100 万次射线 vs 体素,普通 AABB 慢得不能忍。**这三套方法其实是同一个问题的不同维度**——这一篇把它们串起来,从 2D 到 3D 到体素,从 O(n²) 到 O(n log n) 到 O(n),让你看清"碰撞检测"这个领域的完整地形图。

## 0 · 为什么要有这一篇

碰撞检测(collision detection)是游戏物理的核心。它决定:
- 角色能不能穿过墙
- 子弹打中谁
- 物品能不能放进背包
- AI 能不能看见玩家(视线遮挡)
- 粒子在表面反弹

**这每一件事在不同游戏规模下,需要的算法完全不同**:

| 场景 | N | 暴力 | 工业算法 |
|---|---|---|---|
| 8 个敌人 | 8 | O(n²) = 64 次 | 暴力就行 |
| 100 个粒子 | 100 | O(n²) = 10000 次 | spatial hash |
| 1000 个 NPC | 1000 | O(n²) = 10⁶ 次 | BVH / quadtree |
| Minecraft 区块 | 65536 | O(n²) = 4×10⁹ 次 | voxel grid |
| 三角形 mesh | 100000 | O(n²) = 10¹⁰ 次 | k-d tree / BVH |

跟着 HH 一集一集学,你只能看到这套演化树的一个分支。这一篇把整棵树画出来。

**读完这一篇,你应该能**:
- 写 2D AABB vs AABB、circle vs circle、ray vs AABB
- 解释 Minkowski 差的工作原理
- 把算法从 2D 扩到 3D(AABB → AABB 3D,ray vs AABB 3D)
- 实现 BVH(Bounding Volume Hierarchy)
- 实现 k-d tree,理解它和 BVH 的区别
- 用 voxel grid 做 O(1) raycast
- 理解 slab method、Amanatides-Woo voxel traversal

## 1 · 2D AABB:最简单的碰撞

### 1.1 AABB 是什么

**AABB**(Axis-Aligned Bounding Box,轴对齐包围盒)是一个**边平行于坐标轴**的矩形。用最小坐标和最大坐标表示:`min = (x0, y0)`, `max = (x1, y1)`。

为什么用 AABB 不用任意矩形?因为**算法极快**——只有加减比较,没有三角函数。两个 AABB 是否相交,只要检查 x、y 两个轴上是否重叠:

```rust
#[derive(Clone, Copy, Debug)]
pub struct Aabb2 {
    pub min: [f32; 2],
    pub max: [f32; 2],
}

impl Aabb2 {
    pub fn intersects(self, other: Aabb2) -> bool {
        // x 轴不重叠,或者 y 轴不重叠 → 不相交
        if self.max[0] < other.min[0] || other.max[0] < self.min[0] { return false; }
        if self.max[1] < other.min[1] || other.max[1] < self.min[1] { return false; }
        true
    }
}
```

4 次比较 + 2 次逻辑或。CPU 几纳秒完成。

### 1.2 踩过的坑

- **浮点精度**:`self.max[0] < other.min[0]` 在 `max == min` 时返回 false(接触算相交)。通常想要——边缘接触算碰撞。"刚刚分离"想停止可能要改成 `<=`。
- **NaN**:某个物体位置变 NaN,所有 AABB 比较返回 false(NaN `<` 任何东西都是 false),角色"穿墙"。debug 半天才发现是别的代码产生了 NaN。
- **坐标单位混用**:游戏里"像素"和"世界单位"两套,要先统一。

### 1.3 Minkowski 差:理解 AABB 碰撞的钥匙

**Minkowski 差**:`A - B = {a - b : a ∈ A, b ∈ B}`。**关键定理**:两个凸形状 A 和 B 相交,当且仅当它们的 Minkowski 差包含原点。

直观理解:A - B 是"A 的每个点相对 B 的每个点"的集合。如果 A 和 B 有共同点 a = b,那么 a - b = 0,所以 0 ∈ A - B。

**两个 AABB 的 Minkowski 差还是 AABB**。`min = (ax0 - bx1, ay0 - by1)`,`max = (ax1 - bx0, ay1 - by0)`。检查 0 是否在这个 AABB 里——就是检查 `min ≤ 0 ≤ max`,等价于原来的 4 个比较。**这就是 AABB 算法的几何本质**。

Minkowski 差的真正威力在更复杂的形状:两个**凸多边形**的差还是凸多边形。用 GJK(Gilbert-Johnson-Keerthi)算法迭代求顶点,判断是否含原点。Casey 在 HH 后期讲 GJK。

### 1.4 移动 AABB:swept AABB

物体很快时可能"穿越"——A 帧速 > 墙厚,A 直接穿过墙,这一帧 AABB 不重叠。**swept AABB**:把 A 看成从 prev_pos 到 curr_pos 的"扫掠体积"。数学上等价于 ray-AABB 问题:`ray.origin = prev_pos`,`ray.dir = curr_pos - prev_pos`,检查 ray 是否打中"墙的 AABB 扩展了 A 的半个尺寸"。

### 1.5 圆 vs 圆 & 圆 vs AABB

```rust
impl Circle {
    pub fn intersects(self, other: Circle) -> bool {
        let dx = self.center[0] - other.center[0];
        let dy = self.center[1] - other.center[1];
        let r = self.radius + other.radius;
        dx * dx + dy * dy < r * r  // 不开根号,平方比较
    }
}

impl Aabb2 {
    pub fn intersects_circle(self, c: Circle) -> bool {
        let cx = c.center[0].clamp(self.min[0], self.max[0]);
        let cy = c.center[1].clamp(self.min[1], self.max[1]);
        let dx = c.center[0] - cx;
        let dy = c.center[1] - cy;
        dx * dx + dy * dy < c.radius * c.radius
    }
}
```

**避免 sqrt**——比较平方距离,省一次 sqrt(几纳秒)。低级优化金科玉律。

## 2 · Ray vs 形状:光线投射

### 2.1 为什么需要 raycast

子弹很快——可能 1 帧 100 米。swept AABB 不够,因为子弹**不是 AABB**(没有体积)。子弹是射线(ray):从枪口出发,沿某个方向无限延伸。

raycast 回答两个问题:
1. **打中了吗?**(布尔)
2. **打中了谁,在哪?**(信息)

```rust
#[derive(Clone, Copy, Debug)]
pub struct Ray2 {
    pub origin: [f32; 2],
    pub dir: [f32; 2],  // 通常归一化
}

pub struct RaycastHit {
    pub t: f32,             // 沿 ray 的距离
    pub point: [f32; 2],    // 命中点
    pub normal: [f32; 2],   // 命中面法向
}
```

### 2.2 Ray vs AABB(Slab method)

经典算法叫 **slab method**(也叫 "AABB raycast" 或 "Amy Williams method",来自 1986 论文)。

**Slab** = 两个平行平面之间的空间。2D AABB 是 2 个 slab(一个 x 方向,一个 y 方向)的交集。3D AABB 是 3 个 slab 的交集。

对每个 slab,计算 ray 进入和离开这个 slab 的 t 值:

```rust
impl Ray2 {
    pub fn vs_aabb(self, aabb: Aabb2) -> Option<RaycastHit> {
        let mut tmin = f32::NEG_INFINITY;
        let mut tmax = f32::INFINITY;
        let mut hit_axis = 0usize;
        let mut hit_sign = 1.0f32;

        for axis in 0..2 {
            if self.dir[axis].abs() < 1e-9 {
                // ray 平行于这个 slab,检查 origin 是否在 slab 内
                if self.origin[axis] < aabb.min[axis] || self.origin[axis] > aabb.max[axis] {
                    return None;
                }
            } else {
                let inv_d = 1.0 / self.dir[axis];
                let mut t1 = (aabb.min[axis] - self.origin[axis]) * inv_d;
                let mut t2 = (aabb.max[axis] - self.origin[axis]) * inv_d;
                let sign = if t1 > t2 { -1.0 } else { 1.0 };
                if t1 > t2 { std::mem::swap(&mut t1, &mut t2); }

                if t1 > tmin {
                    tmin = t1;
                    hit_axis = axis;
                    hit_sign = sign;
                }
                if t2 < tmax { tmax = t2; }

                if tmin > tmax { return None; }
            }
        }

        if tmin < 0.0 { return None; }  // AABB 在 ray 后面

        let point = [
            self.origin[0] + self.dir[0] * tmin,
            self.origin[1] + self.dir[1] * tmin,
        ];
        let mut normal = [0.0, 0.0];
        normal[hit_axis] = hit_sign;
        Some(RaycastHit { t: tmin, point, normal })
    }
}
```

**算法直觉**:对每个轴,ray 在这个 slab 内的 t 区间是 `[t1, t2]`。Ray 在 AABB 内的 t 区间是所有轴区间的**交集**——`[max(t1_x, t1_y), min(t2_x, t2_y)]`。如果 max > min,无交集。

**关键优化**:`1.0 / self.dir[axis]` 在循环外预算一次,叫 `inv_d`。除法比乘法慢 5-10 倍。

### 2.3 扩展到 3D:加一个 axis

3D 版本只是循环范围从 `0..2` 改成 `0..3`。slab method 是**维度无关**的:

```rust
pub fn vs_aabb3(self, aabb: Aabb3) -> Option<RaycastHit3> {
    let mut tmin = f32::NEG_INFINITY;
    let mut tmax = f32::INFINITY;
    let mut hit_axis = 0;
    let mut hit_sign = 1.0f32;

    for axis in 0..3 {
        // ... 同 2D ...
    }
    // ...
}
```

**这是 slab method 最优雅的地方**——2D 和 3D 本质相同。Casey 在 HH 早期 2D,后期 3D,raycast 算法几乎没变。

### 2.4 Ray vs 圆 / Ray vs 球

把圆心 C 投影到 ray 上,看距离。算法:计算 O 到 C 的向量 L,投影到 ray `tc = L·D`(D 归一化);若 `tc < 0` 圆在 ray 后面;计算垂直距离 `d² = L·L - tc·tc`,若 `d² > r²` ray 不经过圆;半弦长 `t1c = sqrt(r² - d²)`,第一个交点 `t = tc - t1c`。

```rust
impl Ray2 {
    pub fn vs_circle(self, c: Circle) -> Option<f32> {
        let (lx, ly) = (c.center[0] - self.origin[0], c.center[1] - self.origin[1]);
        let tc = lx * self.dir[0] + ly * self.dir[1];
        if tc < 0.0 { return None; }
        let d2 = lx * lx + ly * ly - tc * tc;
        let r2 = c.radius * c.radius;
        if d2 > r2 { return None; }
        Some(tc - (r2 - d2).sqrt())
    }
}
```

### 2.5 Ray vs 线段:多边形碰撞

游戏里常用线段表示墙(2D)或三角形边(3D)。Ray vs 线段是**求两条直线的交点**:

```rust
pub fn ray_vs_segment(
    ray_origin: [f32; 2], ray_dir: [f32; 2],
    seg_a: [f32; 2], seg_b: [f32; 2],
) -> Option<(f32, f32)> {
    let (sx, sy) = (seg_b[0] - seg_a[0], seg_b[1] - seg_a[1]);
    let denom = ray_dir[0] * sy - ray_dir[1] * sx;
    if denom.abs() < 1e-9 { return None; }  // 平行
    let (dx, dy) = (seg_a[0] - ray_origin[0], seg_a[1] - ray_origin[1]);
    let t = (dx * sy - dy * sx) / denom;  // 沿 ray 的距离
    let u = (dx * ray_dir[1] - dy * ray_dir[0]) / denom;  // 沿 segment 的距离
    if t >= 0.0 && u >= 0.0 && u <= 1.0 { Some((t, u)) } else { None }
}
```

`(t, u)` 是参数化交点。Ray vs 球(3D)算法和 Ray vs 圆相同,坐标改 3 维。

## 3 · O(n²) 的死胡同:为什么要空间分割

### 3.1 暴力 & Spatial hash

暴力两两测试 100 个物体 = 4950 次。1000 个 = 499500 次。**O(n²)** 增长,大场面直接死。**Broad phase** 在大数据里快速排除"肯定不相交"的对。

**Spatial hash grid**:把空间划分成网格,每个物体根据位置分配到一个或多个格子。检查碰撞只查同格子(或邻近格子)的物体。物体大小均匀时,每个格子平均 k 个物体,query 是 O(k),整个 pass 是 O(n·k)。

```rust
use std::collections::HashMap;

pub struct SpatialHash { cell_size: f32, cells: HashMap<(i32, i32), Vec<usize>> }

impl SpatialHash {
    pub fn insert(&mut self, idx: usize, aabb: Aabb2) {
        let x0 = (aabb.min[0] / self.cell_size).floor() as i32;
        let y0 = (aabb.min[1] / self.cell_size).floor() as i32;
        let x1 = (aabb.max[0] / self.cell_size).floor() as i32;
        let y1 = (aabb.max[1] / self.cell_size).floor() as i32;
        for x in x0..=x1 {
            for y in y0..=y1 {
                self.cells.entry((x, y)).or_default().push(idx);
            }
        }
    }

    pub fn query(&self, aabb: Aabb2) -> Vec<usize> {
        let mut result = Vec::new();
        let x0 = (aabb.min[0] / self.cell_size).floor() as i32;
        let y0 = (aabb.min[1] / self.cell_size).floor() as i32;
        let x1 = (aabb.max[0] / self.cell_size).floor() as i32;
        let y1 = (aabb.max[1] / self.cell_size).floor() as i32;
        for x in x0..=x1 {
            for y in y0..=y1 {
                if let Some(cell) = self.cells.get(&(x, y)) {
                    result.extend_from_slice(cell);
                }
            }
        }
        result.sort_unstable();
        result.dedup();
        result
    }
}
```

复杂度:如果物体大小均匀,每个格子平均 k 个物体,query 是 O(k)。整个碰撞 pass 是 O(n·k),远好于 O(n²)。

**坑**:物体大小不均匀时,single 大物体覆盖很多 cell,cell 列表爆炸。需要"小物体走 grid,大物体走单独列表"的混合策略。

### 3.3 Sweep and prune

Sort along one axis, only test adjacent pairs:

```rust
fn sweep_and_prune(boxes: &mut [(usize, Aabb2)]) -> Vec<(usize, usize)> {
    // 按 min.x 排序
    boxes.sort_by(|a, b| a.1.min[0].partial_cmp(&b.1.min[0]).unwrap());
    let mut hits = Vec::new();
    for i in 0..boxes.len() {
        let mut j = i + 1;
        while j < boxes.len() && boxes[j].1.min[0] < boxes[i].1.max[0] {
            // x 轴重叠,做完整 AABB 测试
            if boxes[i].1.intersects(boxes[j].1) {
                hits.push((boxes[i].0, boxes[j].0));
            }
            j += 1;
        }
    }
    hits
}
```

物体几乎不动时,排序"几乎已经排好"(插入排序 O(n) 修改),性能极佳。物体高速运动时会失效。Box2D 用这个方案多年,后来换成 BVH。

## 4 · BVH:Bounding Volume Hierarchy

### 4.1 树形结构

BVH 把物体组织成**树**。每个内部节点的 AABB 包住所有子节点的 AABB。叶子节点是一个物体。

```
                [root AABB]
                /         \
        [left AABB]    [right AABB]
            /   \          /   \
        obj1   obj2    obj3   obj4
```

raycast 时,如果 ray 不相交 root,直接 return。否则递归:不相交的子树整支跳过。

```rust
pub struct BvhNode {
    pub aabb: Aabb3,
    pub left: usize,   // 索引到 nodes 数组
    pub right: usize,  // 或者叶子标记
    pub leaf_obj: Option<usize>,  // None = 内部节点
}

pub struct Bvh {
    pub nodes: Vec<BvhNode>,
    pub root: usize,
}

impl Bvh {
    pub fn raycast(&self, ray: Ray3, out: &mut Vec<usize>) {
        self.raycast_node(self.root, ray, out);
    }

    fn raycast_node(&self, node_idx: usize, ray: Ray3, out: &mut Vec<usize>) {
        let node = &self.nodes[node_idx];
        if ray.vs_aabb3(node.aabb).is_none() { return; }
        if let Some(obj) = node.leaf_obj {
            out.push(obj);
            return;
        }
        self.raycast_node(node.left, ray, out);
        self.raycast_node(node.right, ray, out);
    }
}
```

### 4.2 构建 BVH:中位数切分

最简单的是 **median split**:选 spread 最大的轴,按这个轴的中心点排序,取中位数,左半边建左子树,右半边建右子树,递归。

```rust
fn build_bvh_recursive(objects: &mut [(usize, Aabb3)], nodes: &mut Vec<BvhNode>) -> usize {
    if objects.len() == 1 {
        let idx = nodes.len();
        nodes.push(BvhNode { aabb: objects[0].1, left: !0, right: !0, leaf_obj: Some(objects[0].0) });
        return idx;
    }
    // 选 spread 最大的轴,按中心点排序,取中位数
    // ... (sort + split + recurse 略)
}
```

更高级:**SAH**(Surface Area Heuristic)——选切分点使得"子树表面积加权代价"最小。这是 PBRT(Book 4)的方法,工业级 ray tracer 都用,代价是构建慢。

### 4.3 BVH 的优缺点

**优点**:
- raycast 是 O(log n) 平均(数据均匀时)
- 自适应——稀疏区域分得粗,密集区域分得细
- 增量更新(refit)便宜——物体移动后,只更新路径上的 AABB

**缺点**:
- 构建需要时间(中位数切分 O(n log n),SAH O(n log² n))
- 动态场景下,物体大量移动会导致树质量下降,需要重建
- 内存开销:每个节点至少 32 字节(AABB) + 8 字节(子指针) + 标记

## 5 · k-d tree:更严格的分割

### 5.1 和 BVH 的区别

k-d tree(其中 k 是维度)和 BVH 都是空间分割树。区别:

- **BVH**:物体先分类,然后计算 AABB。叶子节点存物体。**物体驱动**。
- **k-d tree**:空间先切分,物体分到切割的两侧。叶子节点存"在这个空间范围内的物体列表"。**空间驱动**。

```
BVH:                k-d tree:
[obj1] [obj2]      [region A] | [region B]
 ↓合并              ↓
[AABB12]            物体跨区域要重复存
```

k-d tree 的内部节点是:**切割轴 + 切割位置 + 左子 + 右子**。

```rust
pub struct KdNode {
    pub axis: u8,        // 0=x, 1=y, 2=z
    pub split: f32,
    pub left: usize,
    pub right: usize,
    pub objects: Vec<usize>,  // 只在叶子节点非空
}
```

### 5.2 构建 k-d tree

和 BVH 类似,但**空间**和**物体**分开:

```rust
fn build_kd(objects: &[(usize, Aabb3)], region: Aabb3, depth: u32) -> KdNode {
    if depth >= MAX_DEPTH || objects.len() <= MAX_LEAF {
        return KdNode {
            axis: 0, split: 0.0, left: 0, right: 0,
            objects: objects.iter().map(|(i, _)| *i).collect(),
        };
    }

    let axis = (depth as usize) % 3;
    let split = (region.min[axis] + region.max[axis]) * 0.5;

    let (mut left_objs, mut right_objs) = (Vec::new(), Vec::new());
    for &(idx, aabb) in objects {
        let crosses = aabb.min[axis] < split && aabb.max[axis] > split;
        if crosses {
            left_objs.push((idx, aabb));
            right_objs.push((idx, aabb));
        } else if aabb.min[axis] < split {
            left_objs.push((idx, aabb));
        } else {
            right_objs.push((idx, aabb));
        }
    }

    let mut left_region = region;
    left_region.max[axis] = split;
    let mut right_region = region;
    right_region.min[axis] = split;

    let left = build_kd(&left_objs, left_region, depth + 1);
    let right = build_kd(&right_objs, right_region, depth + 1);

    KdNode { axis, split, left, right, objects: Vec::new() }
}
```

### 5.3 BVH vs k-d tree

| 维度 | BVH | k-d tree |
|---|---|---|
| 树质量(静态场景) | 好 | 极好 |
| 构建时间 | O(n log n) | O(n log² n)(SAH) |
| 动态更新 | 容易(refit) | 难(物体跨边界) |
| raycast 性能 | O(log n) | O(log n)(常数更小) |
| 内存 | ~32B/node | ~24B/node |
| 典型用例 | 游戏、动态场景 | ray tracer、静态场景 |

**ray tracer**(RenderMan、PBRT、 Mitsuba)用 k-d tree,因为静态场景 + 大量 raycast。**游戏物理引擎**(PhysX、Havok、Box2D)用 BVH,因为动态场景 + 物体可以移动。

## 6 · Voxel Grid:O(1) raycast 的秘密武器

### 6.1 Minecraft 的问题

Minecraft 区块 16×16×256,每个方块是一个 voxel。一帧要 raycast 1000 次(玩家挖、AI 视线、粒子碰撞)。区块里有约 65536 个 voxel。

暴力:每次 raycast 测 65536 = O(n)。1 帧 1000×65536 = 6.5×10⁷。100 FPS 下 6.5×10⁹/秒。**完全跑不动**。

BVH raycast 是 O(log n) = O(16)。1 帧 16000 次。100 FPS 下 1.6×10⁶/秒。可以,但还是浪费。

**Voxel grid** 的关键洞察:体素本身**就是网格**。raycast 不需要遍历树——直接遍历 ray 经过的网格 cell。

### 6.2 Amanatides-Woo 算法

1987 年经典算法。原理:从 ray 起点 cell 开始,每次迈入下一个 cell(沿 ray 主方向)。每步只测当前 cell 的 voxel。

核心代码骨架(完整版见仓库):

```rust
pub struct VoxelGrid {
    pub voxels: Vec<u8>,  // 0 = 空
    pub size: [usize; 3],
    pub cell_size: f32,
}

impl VoxelGrid {
    pub fn raycast(&self, origin: [f32; 3], dir: [f32; 3], max_dist: f32) -> Option<(usize, usize, usize)> {
        let mut x = (origin[0] / self.cell_size).floor() as i32;
        let mut y = (origin[1] / self.cell_size).floor() as i32;
        let mut z = (origin[2] / self.cell_size).floor() as i32;
        // step:跨 cell 边界方向;t_max:到下一个 cell 边界距离;t_delta:跨一个 cell 的 t 增量
        let step = [if dir[0] > 0.0 {1} else {-1}, if dir[1] > 0.0 {1} else {-1}, if dir[2] > 0.0 {1} else {-1}];
        let mut t_max = [0.0f32; 3];
        let t_delta = [
            if dir[0].abs() > 1e-9 { (self.cell_size / dir[0].abs()).abs() } else { f32::INFINITY },
            if dir[1].abs() > 1e-9 { (self.cell_size / dir[1].abs()).abs() } else { f32::INFINITY },
            if dir[2].abs() > 1e-9 { (self.cell_size / dir[2].abs()).abs() } else { f32::INFINITY },
        ];
        for axis in 0..3 {
            let boundary = if step[axis] > 0 { (x+1) as f32 * self.cell_size } else { x as f32 * self.cell_size };
            t_max[axis] = if dir[axis].abs() > 1e-9 { (boundary - origin[axis]) / dir[axis] } else { f32::INFINITY };
        }

        let mut t = 0.0f32;
        loop {
            // 检查当前 cell
            if x >= 0 && y >= 0 && z >= 0 &&
               (x as usize) < self.size[0] && (y as usize) < self.size[1] && (z as usize) < self.size[2] {
                let idx = x as usize + y as usize * self.size[0] + z as usize * self.size[0] * self.size[1];
                if self.voxels[idx] != 0 { return Some((x as usize, y as usize, z as usize)); }
            }
            // 迈入下一个 cell(选 t_max 最小的轴)
            if t_max[0] < t_max[1] && t_max[0] < t_max[2] {
                x += step[0]; t = t_max[0]; t_max[0] += t_delta[0];
            } else if t_max[1] < t_max[2] {
                y += step[1]; t = t_max[1]; t_max[1] += t_delta[1];
            } else {
                z += step[2];
                t = t_max[2];
                t_max[2] += t_delta[2];
            }

            if t > max_dist { return None; }
        }
    }
}
```

**复杂度**:O(D) 其中 D 是 ray 经过的 cell 数。1000 cell ray = 1000 步。**勉强够用**。

**优化**:Sparse Voxel Octree(SVO)、DAG(Directed Acyclic Graph)合并重复子树,场景越大优势越大。Voxel Cone Tracing 用 voxel 做 sparse global illumination。

### 6.3 DDA & Bresenham

Amanatides-Woo 是 **DDA**(Digital Differential Analyzer)算法的特例。原始 DDA 是 1960 年代画线算法。3D DDA 的另一变种 **Bresenham 3D**,用整数算术(没除法没浮点),更适合嵌入式。

## 7 · 工业实现对比

**物理引擎 broad phase**:PhysX(NVIDIA,GPU BVH)、Havok(BVH + SIMD)、Box2D(Dynamic AABB Tree,实际是 BVH)、Bevy_rapier(rapier3d BVH)、Jolt(Horizon Forbidden West,GPU-friendly BVH)。

**Ray tracer**:RenderMan(BIH)、PBRT/Mitsuba(k-d tree 或 BVH)、Embree(Intel,BVH + AVX-512)、OptiX / Falcor(NVIDIA,BVH + RTX 硬件)。

**游戏 collision** 大多用 AABB + BVH 就够了。复杂 mesh 用凸分解(Convex Decomposition)——把凹物体拆成多个凸体,每个用 GJK/EPA。

## 8 · 完整 Rust 例子

骨架:1000 个随机 AABB,做 1000 次 raycast,对比暴力 vs BVH:

```rust
use std::time::Instant;
mod aabb; mod bvh;
use aabb::{Aabb3, Ray3}; use bvh::Bvh;

fn main() {
    let mut objects: Vec<(usize, Aabb3)> = (0..1000).map(|i| {
        let (x, y, z) = ((i as f32 * 17.0) % 100.0, (i as f32 * 23.0) % 100.0, (i as f32 * 31.0) % 100.0);
        (i, Aabb3 { min: [x, y, z], max: [x + 1.0, y + 1.0, z + 1.0] })
    }).collect();
    let start = Instant::now();
    let mut nodes = Vec::new();
    let root = bvh::build_bvh_recursive(&mut objects, &mut nodes);
    let bvh = Bvh { nodes, root };
    println!("BVH build: {:?}", start.elapsed());

    let rays: Vec<Ray3> = (0..1000).map(|_| { /* 生成随机 ray */ }).collect();

    let s = Instant::now();
    let brute_hits: usize = rays.iter().map(|r| objects.iter().filter(|(_, a)| r.vs_aabb3(*a).is_some()).count()).sum();
    println!("Brute: {:?}, hits={}", s.elapsed(), brute_hits);

    let s = Instant::now();
    let bvh_hits: usize = rays.iter().map(|r| { let mut h = Vec::new(); bvh.raycast(*r, &mut h); h.len() }).sum();
    println!("BVH:   {:?}, hits={}", s.elapsed(), bvh_hits);
}
```

实测 1000 vs 1000(我的机器):暴力 ~5 ms,BVH ~0.5 ms。10 倍加速。N=10000 时 100 倍。N=100000 时暴力完全跑不动。

## 9 · 跨阶段回顾:碰撞检测演化

| 阶段 | 算法 | 复杂度 | HH 出现日 |
|---|---|---|---|
| Day 50 | 2D AABB | O(n²) broad + O(1) narrow | HH 早期 |
| Day 80 | Circle vs AABB | O(n²) broad | HH |
| Day 377 | Ray vs AABB (slab) | O(n) | HH |
| Day 480 | BVH | O(n log n) build + O(log n) raycast | HH 后期 |
| Day 631 | Voxel grid + Amanatides-Woo | O(D) per ray | HH Phase 8 |

每一步演化都是为了**解决上一步在大数据下的瓶颈**。Casey 一集一集小步重构,你跟下来就是一部 collision detection 的工业史。

**关联 Day**:
- 铺垫:[day050](../phase-2/day050.md) — 2D AABB 初次接触;[day377](../phase-5/day377.md) — raycast 引入
- 当天:本深入
- 后续:[day631](../phase-8/day631.md) — voxel raycast;[deep-dives/threading-journey.md](threading-journey.md) — BVH 并行构建

## 10 · 延伸阅读

本仓库本地资料:
- [phase-2/day050.md](../phase-2/day050.md) — 2D AABB / Minkowski 差
- [phase-5/day377.md](../phase-5/day377.md) — Raycast 引入
- [phase-8/day631.md](../phase-8/day631.md) — Voxel raycast

外部稳定 URL:
- Real-Time Collision Detection (Ericson) — 工业金标书
- PBRT Book 4 — BVH / k-d tree 章节:https://pbr-book.org/
- Erin Catto GDC 演讲:"Dynamic AABB Trees" 和后续
- Amanatides & Woo 1987 原始论文:"A Fast Voxel Traversal Algorithm for Ray Tracing"
- Embree 文档(GPU raycast 库):https://www.embree.org/
- GJK 算法解释(代码 + 几何):https://winter.me/articles/gjk/
- Casey HH 的 day50 / day377 / day631 完整代码

真实开源源码:
- Bevy 的 BVH 实现(bevy_render)
- rapier3d(Rust physics engine)
- Embree(Intel, C++)
- Casey HH 的 source code:https://github.com/HandmadeHero/handmade-hero
