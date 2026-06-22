---
phase: 2
type: deep-dive
title: "碰撞检测全家桶:Minkowski → 空间网格 → GJK → BVH"
domains: [game, math, graphics]
duration: "3h"
prereqs: ["day048", "day050", "day051", "phase-0/14-math-foundations"]
---

# 碰撞检测全家桶 · Minkowski → 空间网格 → GJK → BVH

> 玩家撞墙、子弹打怪、相机穿过门——所有这些"两个东西碰到没?"的问题。看起来简单,但工业级碰撞检测是游戏引擎最复杂的子系统之一。Casey 在 HH Day 050 用 Minkowski 差解决 2D AABB,Day 051-055 加空间网格优化。这只是冰山一角。本文 3 小时讲完碰撞检测的全套:Minkowski 差、空间哈希、扫描剪枝、GJK、BVH、Ray Cast、Continuous Collision Detection。看完你能选对方案,看懂任何引擎的碰撞代码。

## 0 · 这篇文章解决什么问题

碰撞检测本质是回答**两个几何体是否相交**。看起来简单——两个圆相交,距离小于半径和;两个矩形相交,x/y 都重叠。但游戏里有 1000 个 entity,N² = 100万对碰撞检测,每帧做不完。所以碰撞检测的真正挑战不是"判相交",而是"快"。

本文回答 4 个核心问题:

1. **怎么判相交?**(几何算法)
2. **怎么避免 O(N²)?**(空间划分)
3. **怎么处理高速穿墙?**(CCD)
4. **怎么支持任意凸多边形?**(GJK)

读完你能:

- 解释 Minkowski 差、SAT、GJK 三个核心算法
- 实现一个空间哈希 / 四叉树 / BVH
- 处理 N=10000 entity 仍跑 60 FPS
- 选对碰撞算法(球 vs AABB vs OBB vs 凸多边形)
- 看懂 Box2D / Bullet / PhysX 的源码结构

## 1 · 碰撞检测的两步法

所有现代物理引擎的碰撞检测都是**两步法**(broad phase + narrow phase):

```
1000 个 entity
    ↓
[broad phase 粗筛] —— 快速排除明显不相交的对
    ↓
~50 对候选碰撞
    ↓
[narrow phase 精筛] —— 精确判断每对是否真的相交
    ↓
~5 对真碰撞
    ↓
[collision response] —— 推开 / 反弹 / 扣血
```

**粗筛**用近似的包围盒(AABB / Sphere),O(N log N) 或 O(N) 算法。
**精筛**用精确几何,O(1) 每对但前提是候选数量小。

两步法是性能的根源——把 O(N²) 拆成 O(N) + O(M),M << N²。

## 2 · Narrow Phase:几何相交算法

### 2.1 圆 vs 圆

最简单的。两个圆心距离 < 半径和,相交。

```rust
fn circle_circle(c1: Vec2, r1: f32, c2: Vec2, r2: f32) -> bool {
    let d = (c1 - c2).length();
    d < r1 + r2
}
```

优化:用距离平方避免 sqrt。

```rust
fn circle_circle_fast(c1: Vec2, r1: f32, c2: Vec2, r2: f32) -> bool {
    let d2 = (c1.x - c2.x).powi(2) + (c1.y - c2.y).powi(2);
    let r = r1 + r2;
    d2 < r * r
}
```

### 2.2 AABB vs AABB(2D 矩形)

**AABB = Axis-Aligned Bounding Box**(轴对齐包围盒)。两个 AABB:

```rust
struct AABB { center: Vec2, half: Vec2 }

fn aabb_aabb(a: AABB, b: AABB) -> bool {
    (a.center.x - b.center.x).abs() < a.half.x + b.half.x &&
    (a.center.y - b.center.y).abs() < a.half.y + b.half.y
}
```

这是 Day 050 Casey 用的方法。**4 次比较 + 4 次绝对值,O(1) 极快**。

### 2.3 Minkowski 差(深入)

#### 2.3.1 定义

两个集合 A 和 B 的 Minkowski 差定义:

```
A ⊖ B = { a - b | a ∈ A, b ∈ B }
```

直觉:把 B "反过来"贴着 A 的边滑动,扫过的形状。

**关键定理**:A 和 B 相交 ⟺ 原点(0, 0) 在 A ⊖ B 内。

#### 2.3.2 几何意义

把"A 和 B 是否相交"转化为"原点是否在某形状内"。这把"两个物体相交"问题变成"一个点在某形状内"问题——后者简单很多。

#### 2.3.3 AABB 的 Minkowski 差

两个 AABB 的 Minkowski 差是另一个 AABB:

```
A ⊖ B 的 center = A.center - B.center
A ⊖ B 的 half   = A.half + B.half
```

原点在 A ⊖ B 内 ⟺ |A.center - B.center| 在 x 和 y 上都 < A.half + B.half。

这就是 Casey 的 AABB 公式!

#### 2.3.4 圆的 Minkowski 差

两个圆的 Minkowski 差是一个更大的圆:

```
(A ⊖ B).center = A.center - B.center
(A ⊖ B).radius = A.radius + B.radius
```

原点在圆内 ⟺ |A.center - B.center| < A.radius + B.radius。

#### 2.3.5 多边形的 Minkowski 差

任意凸多边形的 Minkowski 差仍是凸多边形,但顶点不再是简单加减——要做"Minkowski sum"算法(凸包的扩展)。

这就是为什么 Casey 选 AABB——Minkowski 差是平凡的 AABB。

### 2.4 SAT(Separating Axis Theorem)

#### 2.4.1 定理

两个**凸**多边形不相交 ⟺ 存在一条"分离轴",两个多边形在该轴上的投影不重叠。

#### 2.4.2 算法

对每条边的法向量做投影,检查是否重叠。如果所有法向量都重叠,相交;否则不相交。

```rust
fn sat_polygon_polygon(p1: &[Vec2], p2: &[Vec2]) -> bool {
    for polygon in [p1, p2] {
        for i in 0..polygon.len() {
            let j = (i + 1) % polygon.len();
            let edge = polygon[j] - polygon[i];
            let normal = Vec2::new(-edge.y, edge.x);  // 边的法向量
            // 把 p1 和 p2 都投影到 normal 上
            let (min1, max1) = project(p1, normal);
            let (min2, max2) = project(p2, normal);
            if max1 < min2 || max2 < min1 {
                return false;  // 找到分离轴,不相交
            }
        }
    }
    true  // 没找到分离轴,相交
}

fn project(poly: &[Vec2], axis: Vec2) -> (f32, f32) {
    let mut min = f32::MAX;
    let mut max = f32::MIN;
    for p in poly {
        let proj = p.x * axis.x + p.y * axis.y;  // 点积
        min = min.min(proj);
        max = max.max(proj);
    }
    (min, max)
}
```

O(N + M) 复杂度,N 和 M 是两个多边形的顶点数。比 GJK 简单,但要求**凸**多边形。

#### 2.4.3 为什么 AABB 是 SAT 的特例

AABB 的法向量是 (1,0) 和 (0,1)。SAT 用这两个法向量投影,就是检查 x 和 y 上的重叠——和 Minkowski 公式等价。

AABB 是 SAT 在轴对齐矩形上的特例。

### 2.5 GJK(Gilbert-Johnson-Keerthi)

#### 2.5.1 解决什么问题

SAT 要求多边形是凸的。但实际游戏可能有任意形状(凹多边形、3D mesh)。GJK 解决**任意凸体**的相交问题(凹的拆成凸的)。

#### 2.5.2 核心思路

GJK 也用 Minkowski 差,但不显式构造 Minkowski 差(可能很大)。它迭代地"探索" Minkowski 差空间,看原点是否在里面。

#### 2.5.3 算法骨架

```
1. 初始化 simplex(单形):随机选一点
2. 计算支持函数(support function):
   support(direction) = 在 Minkowski 差上沿 direction 方向最远的点
   = argmax_{a in A, b in B} (a - b) · direction
   = argmax_a(a · direction) - argmin_b(b · direction)
3. 把 support 点加到 simplex
4. 检查原点是否在 simplex 内:
   - 是:相交,返回 true
   - 否:更新 direction(向原点方向),回到 step 2
5. 一定次数后还没找到,不相交
```

Support function 是关键——它对任意凸体都能算(只要你能找到"沿某方向最远的点")。

#### 2.5.4 实现

```rust
fn gjk_intersect(shape_a: &Shape, shape_b: &Shape) -> bool {
    let mut direction = Vec2::new(1.0, 0.0);
    let mut simplex = vec![support(shape_a, shape_b, direction)];

    direction = -simplex[0];  // 朝原点

    for _ in 0..50 {  // 最多迭代 50 次
        let next = support(shape_a, shape_b, direction);
        if next.dot(direction) < 0.0 {
            return false;  // 没越过原点,不可能相交
        }
        simplex.push(next);
        if simplex_contains_origin(&mut simplex, &mut direction) {
            return true;
        }
    }
    false
}

fn support(a: &Shape, b: &Shape, dir: Vec2) -> Vec2 {
    a.support(dir) - b.support(-dir)
}

trait Shape {
    fn support(&self, dir: Vec2) -> Vec2;  // 沿 dir 方向最远的点
}

impl Shape for Circle {
    fn support(&self, dir: Vec2) -> Vec2 {
        self.center + dir.normalized() * self.radius
    }
}

impl Shape for Polygon {
    fn support(&self, dir: Vec2) -> Vec2 {
        self.vertices.iter()
            .max_by(|a, b| {
                a.dot(dir).partial_cmp(&b.dot(dir)).unwrap()
            })
            .copied()
            .unwrap()
    }
}
```

2D 的 simplex 处理是简单的(三角形 vs 原点)。3D 复杂很多(四面体)。

#### 2.5.5 优势

- 任意凸体(球、AABB、OBB、多边形、3D mesh)
- 平均 O(1) 每对(迭代次数通常 < 5)
- 自然支持 swept test(物体移动时的扫掠)

#### 2.5.6 业界采用

- **Box2D** 用 GJK 做 narrow phase
- **Bullet Physics** 用 GJK
- **PhysX** 用 GJK 变种

### 2.6 OBB(Oriented Bounding Box)

OBB 是"有旋转的 AABB"。检查 OBB vs OBB 比 AABB 复杂:

1. SAT 用 OBB 的 4 条边法向量(2 个本体的 + 2 个对方的)
2. 不能用 Minkowski 的简化公式(旋转破坏了对称)

OBB 适合"长条形但有方向"的物体(汽车、剑)。

### 2.7 三角形 vs 三角形(3D)

3D 三角形相交是图形学经典问题。算法:Möller 算法(1997),用三角形所在平面的交线判断。

游戏里很少直接做三角形 vs 三角形(太慢),通常用包围盒先粗筛。

## 3 · Broad Phase:避免 O(N²)

### 3.1 暴力 O(N²) 的极限

1000 个 entity,N²=100万对,每对 narrow phase 10 ns → 10 ms / 帧。还能跑。
10000 个 entity,N²=1亿对 → 1 秒 / 帧。完蛋。

需要 broad phase 把 N² 降到 N log N 或 N。

### 3.2 空间划分(Spatial Partitioning)

把世界切成网格 / 树,每个 entity 放进它所在的格子。检测时只比较**同格子或相邻格子**的 entity 对。

#### 3.2.1 均匀网格(Uniform Grid)

把世界切成大小相等的格子。每个 entity 在哪个格子由 `entity.pos / cell_size` 算出。

```rust
struct UniformGrid {
    cell_size: f32,
    cells: HashMap<(i32, i32), Vec<EntityId>>,
}

impl UniformGrid {
    fn clear(&mut self) { self.cells.clear(); }
    fn insert(&mut self, id: EntityId, pos: Vec2) {
        let cx = (pos.x / self.cell_size) as i32;
        let cy = (pos.y / self.cell_size) as i32;
        self.cells.entry((cx, cy)).or_default().push(id);
    }
    fn nearby(&self, pos: Vec2) -> Vec<EntityId> {
        let cx = (pos.x / self.cell_size) as i32;
        let cy = (pos.y / self.cell_size) as i32;
        let mut result = Vec::new();
        for dx in -1..=1 {
            for dy in -1..=1 {
                if let Some(cell) = self.cells.get(&(cx + dx, cy + dy)) {
                    result.extend(cell.iter().copied());
                }
            }
        }
        result
    }
}
```

#### 3.2.2 选择 cell_size

- 太小:entity 跨多个 cell,insert / query 慢
- 太大:每 cell entity 太多,query 慢
- 经验值:cell_size ≈ 2 × entity 平均大小

Casey 在 Day 051-055 用的就是均匀网格。

#### 3.2.3 复杂度

- insert: O(1) 每 entity,O(N) 总
- query: O(9 × cell_density),常量时间
- 总 broad phase: O(N)

10000 个 entity → 10000 次 insert + query,几毫秒。

#### 3.2.4 局限

- 世界大小变化时,cell 数量爆炸(地图 100000×100000,cell 10x10 → 1亿 cells)
- entity 大小差异大时,小 cell 装不下大 entity,大 cell 浪费小 entity 空间

### 3.3 四叉树(Quadtree,2D)

#### 3.3.1 思想

层次化网格。世界是一个大方格,如果某个方格里 entity 太多,把它拆成 4 个子方格。递归到合适粒度。

```
┌───────────────┐
│               │
│   ┌───┬───┐   │
│   │ A │ B │   │
│   ├───┼───┤   │
│   │ C │ D │   │
│   └───┴───┘   │
│               │
└───────────────┘
```

A B C D 是子节点。如果 D 里 entity 还多,继续拆 D。

#### 3.3.2 实现

```rust
struct Quadtree {
    bounds: AABB,             // 这个节点覆盖的区域
    entities: Vec<EntityId>,  // 叶节点存的 entity
    children: Option<Box<[Quadtree; 4]>>,  // 4 个子节点
    max_entities: usize,      // 拆分阈值
}

impl Quadtree {
    fn new(bounds: AABB, max_entities: usize) -> Self {
        Self { bounds, entities: Vec::new(), children: None, max_entities }
    }

    fn insert(&mut self, id: EntityId, pos: Vec2) {
        if let Some(children) = &mut self.children {
            // 已经拆分,递归 insert 到对应子节点
            for child in children.iter_mut() {
                if child.bounds.contains(pos) {
                    child.insert(id, pos);
                    return;
                }
            }
            return;
        }
        // 没拆,加到本节点
        self.entities.push(id);
        // 需要拆吗?
        if self.entities.len() > self.max_entities {
            self.split();
            // 把本节点的 entity 重新分发到子节点
            let entities = std::mem::take(&mut self.entities);
            for eid in entities {
                let pos = ...; // 查 entity 位置
                for child in self.children.as_mut().unwrap().iter_mut() {
                    if child.bounds.contains(pos) {
                        child.entities.push(eid);
                        break;
                    }
                }
            }
        }
    }

    fn split(&mut self) {
        let c = self.bounds.center;
        let h = self.bounds.half * 0.5;
        let children = [
            Quadtree::new(AABB { center: Vec2::new(c.x - h.x, c.y - h.y), half: h }, self.max_entities),
            Quadtree::new(AABB { center: Vec2::new(c.x + h.x, c.y - h.y), half: h }, self.max_entities),
            Quadtree::new(AABB { center: Vec2::new(c.x - h.x, c.y + h.y), half: h }, self.max_entities),
            Quadtree::new(AABB { center: Vec2::new(c.x + h.x, c.y + h.y), half: h }, self.max_entities),
        ];
        self.children = Some(Box::new(children));
    }

    fn query(&self, region: AABB) -> Vec<EntityId> {
        let mut result = Vec::new();
        if !self.bounds.intersects(region) { return result; }
        result.extend(self.entities.iter().copied());
        if let Some(children) = &self.children {
            for child in children.iter() {
                result.extend(child.query(region));
            }
        }
        result
    }
}
```

#### 3.3.3 复杂度

- insert: O(log N) 平均
- query: O(log N + K),K 是返回的 entity 数

#### 3.3.4 优势 vs 均匀网格

- 自适应密度(密集区多拆,稀疏区少拆)
- 大世界友好(只有非空节点占内存)

#### 3.3.5 劣势

- 实现复杂(递归、内存分配)
- 不适合"每帧重建"(每帧 insert N 次,慢)

游戏里**每帧重建均匀网格更快**(简单 + cache 友好),四叉树适合静态世界。

### 3.4 八叉树(Octree,3D)

3D 版本,每节点拆成 8 个子节点(2³)。3D 游戏标准。

### 3.5 BVH(Bounding Volume Hierarchy)

#### 3.5.1 思想

每个 entity 包一个 AABB,所有 AABB 构成一棵树。**内部节点**的 AABB 是其子节点的并集。

```
       [root AABB]
       /    \
   [L AABB] [R AABB]
   /   \    /   \
  e1   e2  e3   e4
```

查询"哪些 entity 和 region 相交"时,从 root 开始递归——如果当前节点 AABB 不和 region 相交,剪枝整个子树。

#### 3.5.2 优势

- entity 可以移动(只需更新 entity 的 AABB + 父链)
- 不依赖空间划分的固定网格
- 适合动态场景

#### 3.5.3 劣势

- 树的平衡是难题(插入 / 删除可能导致不平衡)
- 实现 BVH 比四叉树复杂

#### 3.5.4 业界采用

- **Ray Tracing**(实时光追):BVH 是标准加速结构
- **Bullet Physics**:动态 BVH
- **PhysX**:BVH 变种

### 3.6 Sweep and Prune(扫描剪枝)

#### 3.6.1 思想

把所有 entity 的 AABB 在 x 轴上投影成 (min_x, max_x) 区间。如果两个区间重叠,x 轴上可能碰撞。

把所有 interval 按 min_x 排序,扫描。当遇到 min_x > 某 max_x 时,这对不再碰撞。

#### 3.6.2 复杂度

排序 O(N log N),扫描 O(N + M),M 是 x 重叠的对数。

#### 3.6.3 优势

- 简单,容易实现
- 增量友好(entity 移动小时,排序几乎不变)

#### 3.6.4 业界采用

Box2D 用 SAP 做 broad phase。

### 3.7 网格 vs 四叉树 vs BVH vs SAP 对比

| 方案 | 复杂度 | 实现 | 动态 | 适用场景 |
|---|---|---|---|---|
| 均匀网格 | O(N) | 简单 | 每帧重建 | entity 大小均匀 |
| 四叉树 | O(N log N) | 中等 | 中等 | 大世界,密度不均 |
| 八叉树 | O(N log N) | 中等 | 中等 | 3D 版四叉树 |
| BVH | O(N log N) | 难 | 好 | 动态场景,ray tracing |
| SAP | O(N log N) | 中等 | 好 | entity 大小差异大 |

**Casey 在 HH 用均匀网格**——游戏 entity 大小相近,网格最简单。

## 4 · Continuous Collision Detection(CCD)

### 4.1 穿墙问题

Day 068 讲过:高速 entity 一帧位移大于 entity 半径时,离散碰撞检测可能跳过墙。

### 4.2 Sub-stepping

把 dt 拆成 N 个小步,每步做离散检测。

```rust
fn update_ccd_substep(e: &mut Entity, dt: f32, walls: &[Wall]) {
    let substeps = 4;
    let sub_dt = dt / substeps as f32;
    for _ in 0..substeps {
        e.pos += e.vel * sub_dt;
        for w in walls {
            if aabb_overlap(e, w) {
                resolve(e, w);
                break;
            }
        }
    }
}
```

### 4.3 Ray Cast / Sweep Test

把 entity 当一个点,从起点射到终点,和所有墙求交。第一个交点是 entity 的终点。

```rust
fn ray_vs_aabb(origin: Vec2, dir: Vec2, aabb: AABB) -> Option<f32> {
    // slab method
    let t1 = (aabb.min().x - origin.x) / dir.x;
    let t2 = (aabb.max().x - origin.x) / dir.x;
    let tmin = t1.min(t2);
    let tmax = t1.max(t2);
    // 同理 y
    let t3 = (aabb.min().y - origin.y) / dir.y;
    let t4 = (aabb.max().y - origin.y) / dir.y;
    let tmin = tmin.max(t3.min(t4));
    let tmax = tmax.min(t3.max(t4));
    if tmax < 0.0 || tmin > tmax { None }
    else { Some(tmin.max(0.0)) }
}
```

### 4.4 Speculative Contacts

物理引擎高级特性——预测下一帧可能碰撞,提前"占位"防止穿墙。Box2D 4.x 用这个。

## 5 · 碰撞响应(Collision Response)

检测只是第一步。检测到碰撞后,怎么响应?

### 5.1 阻挡(Block)

最简单:把 entity 推回到碰撞前的位置。

```rust
fn block(e: &mut Entity, wall: &Wall) {
    // 计算最小推开方向
    let dx = (e.pos.x - wall.center.x).abs() - (e.half + wall.half.x);
    let dy = (e.pos.y - wall.center.y).abs() - (e.half + wall.half.y);
    if dx > dy {
        e.pos.x = wall.center.x + (e.half + wall.half.x) * e.pos.x.signum();
    } else {
        e.pos.y = wall.center.y + (e.half + wall.half.y) * e.pos.y.signum();
    }
}
```

### 5.2 Wall Sliding(滑墙)

撞墙不要停,沿墙滑:

```rust
fn slide(e: &mut Entity, wall: &Wall) {
    // 把速度的"撞墙分量"清零,保留"沿墙分量"
    let normal = wall.normal();  // 墙的法向量
    let v_dot_n = e.vel.dot(normal);
    if v_dot_n < 0.0 {  // 朝墙移动
        e.vel -= normal * v_dot_n;  // 去掉垂直分量
    }
}
```

Casey 在 HH 用这个——玩家撞墙不死板停下,而是滑过墙。

### 5.3 反弹(Bounce)

弹性碰撞:

```rust
fn bounce(e: &mut Entity, wall: &Wall, restitution: f32) {
    let normal = wall.normal();
    let v_dot_n = e.vel.dot(normal);
    if v_dot_n < 0.0 {
        // v' = v - (1 + e) * (v · n) * n
        // e 是弹性系数(0 = 完全非弹性,1 = 完全弹性)
        e.vel -= normal * ((1.0 + restitution) * v_dot_n);
    }
}
```

### 5.4 推开(Push)

推开两个相交的 entity:

```rust
fn push_apart(a: &mut Entity, b: &mut Entity) {
    let delta = b.pos - a.pos;
    let dist = delta.length();
    let overlap = (a.half + b.half) - dist;
    if overlap > 0.0 {
        let push = delta.normalized() * (overlap * 0.5);
        a.pos -= push;
        b.pos += push;
    }
}
```

## 6 · 完整 Rust 实现(2D 游戏)

下面是一个完整的 2D 碰撞检测系统(用均匀网格 + AABB + wall sliding)。

```rust
// 完整代码大约 300 行,这里给关键部分

#[derive(Clone, Copy, Debug)]
struct AABB { center: Vec2, half: Vec2 }

impl AABB {
    fn intersects(self, other: AABB) -> bool {
        (self.center.x - other.center.x).abs() < self.half.x + other.half.x &&
        (self.center.y - other.center.y).abs() < self.half.y + other.half.y
    }
}

struct UniformGrid {
    cell_size: f32,
    cells: HashMap<(i32, i32), Vec<usize>>,
}

impl UniformGrid {
    fn new(cell_size: f32) -> Self {
        Self { cell_size, cells: HashMap::new() }
    }

    fn rebuild(&mut self, entities: &[Entity]) {
        self.cells.clear();
        for (i, e) in entities.iter().enumerate() {
            if !e.alive { continue; }
            let cx = (e.pos.x / self.cell_size) as i32;
            let cy = (e.pos.y / self.cell_size) as i32;
            self.cells.entry((cx, cy)).or_default().push(i);
        }
    }

    fn query(&self, pos: Vec2) -> Vec<usize> {
        let cx = (pos.x / self.cell_size) as i32;
        let cy = (pos.y / self.cell_size) as i32;
        let mut result = Vec::new();
        for dx in -1..=1 {
            for dy in -1..=1 {
                if let Some(cell) = self.cells.get(&(cx + dx, cy + dy)) {
                    result.extend(cell.iter().copied());
                }
            }
        }
        result
    }
}

fn update_with_collisions(
    entities: &mut Vec<Entity>,
    grid: &mut UniformGrid,
    dt: f32,
) {
    grid.rebuild(entities);

    for i in 0..entities.len() {
        if !entities[i].alive { continue; }
        // 移动
        entities[i].pos += entities[i].vel * dt;
        // 检测
        let candidates = grid.query(entities[i].pos);
        for &j in &candidates {
            if i == j || !entities[j].alive { continue; }
            let aabb_i = AABB { center: entities[i].pos, half: entities[i].half };
            let aabb_j = AABB { center: entities[j].pos, half: entities[j].half };
            if aabb_i.intersects(aabb_j) {
                resolve_collision(entities, i, j);
            }
        }
    }
}
```

## 7 · 业界方案对比

### 7.1 Box2D(2D 物理)

- **Broad Phase**:Sweep and Prune(也支持动态树)
- **Narrow Phase**:GJK + EPA(用于穿透深度)
- **CCD**:可选 sub-stepping 或 ray cast
- **License**:MIT

### 7.2 Bullet Physics(3D)

- **Broad Phase**:动态 AABB 树(BVH)
- **Narrow Phase**:GJK
- **CCD**:sub-stepping
- **License**:Zlib

### 7.3 PhysX(NVIDIA)

- **Broad Phase**:BVH
- **Narrow Phase**:GJK + SAT 混合
- **CCD**:speculative contacts
- **License**:BSD-3

### 7.4 Rapier(Rust)

- **Broad Phase**:BVH
- **Narrow Phase**:GJK + EPA
- **License**:Apache-2.0

### 7.5 avian(Rust,bevy 风格)

- 基于 Rapier 或 xpbd
- **License**:MIT/Apache

### 7.6 Casey HH

- **Broad Phase**:均匀网格
- **Narrow Phase**:Minkowski AABB(不做任意多边形)
- **CCD**:vel clamp(简单版)
- **License**:开源(CC0)

## 8 · 何时选什么

| 场景 | 推荐 |
|---|---|
| 2D 游戏,entity 都是 AABB | Casey 方案(均匀网格 + Minkowski) |
| 2D 游戏,有圆 / 多边形 | Box2D / Rapier 2D |
| 3D 游戏,简单几何 | Rapier 3D / avian |
| 3D 游戏,AAA 物理 | PhysX / Bullet |
| 大世界,稀疏 entity | 四叉树 / 八叉树 |
| ray tracing | BVH |
| 极速 entity | CCD + ray cast |

## 9 · 延伸阅读

本仓库:
- [day048.md](day048.md) —— 线段相交
- [day050.md](day050.md) —— Minkowski 差
- [day051.md](day051.md) —— 分离更新频率
- [day055.md](day055.md) —— hash 世界存储
- [day068.md](day068.md) —— vel clamp 防穿墙
- [day069.md](day069.md) —— 碰撞规则表

外部:
- Real-Time Collision Detection (Ericson): https://realtimecollisiondetection.net/
- Box2D 文档(CCD chapter): https://box2d.org/documentation/
- GJK 算法可视化: https://www.youtube.com/watch?v=Qupqu1xe7Io
- SAT 解释: https://www.sevenson.com.au/programming/sat/

开源源码:
- Rapier(Rust 2D/3D 物理): https://github.com/dimforge/rapier
- avian: https://github.com/Jondolf/avian
- Box2D: https://github.com/erincatto/box2d
- Casey HH Day 050: https://github.com/HandmadeHero/handmade-hero/tree/main/code/day050
