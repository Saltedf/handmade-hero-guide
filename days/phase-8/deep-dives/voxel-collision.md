# 深入:体素碰撞重构

> Phase 8 最重要的事件之一是 Casey 把 HH 的 3D 碰撞从 **Minkowski-based AABB** 重写为 **voxel-based sphere collision**。Day 636-645 共 10 集全花在这上面。本文系统性梳理这个重构:为什么要做、怎么做、和其他引擎对比。

## 1 · 背景:Minkowski 碰撞的局限

回顾 HH 早期的碰撞系统(Day 050 起):**Minkowski-based AABB**。两个 AABB 相交 ⟺ "它们的 Minkowski 差包含原点"。

这个算法对 2D / 早期 3D 够用,但有几个问题:

### 1.1 高速穿透(tunneling)

玩家高速移动(每帧位移 > 1 voxel),AABB 检测"新位置"是否非法。但**没检测轨迹中间**——物体可能"跳"过整个墙。

```
帧 N:  玩家在墙前
帧 N+1: 玩家在墙后(速度 5 voxel/帧)
帧 N+2: 玩家继续运动
```

中间帧"穿墙"——Minkowski 没拦住。

### 1.2 角落卡顿

AABB 撞 L 形墙拐角时,接触法线只有 ±x / ±y / ±z 6 种。玩家斜着靠近拐角,被推回 x 或 y(不连续),视觉"卡顿"。

### 1.3 多边形单元处理复杂

HH 的世界是 voxel grid,每 voxel 是 AABB。Minkowski 检测两个 AABB——但玩家 AABB 和**多个** voxel AABB 的交互需要逐个检测,效率低 + 容易遗漏。

## 2 · 重构的核心思路

Casey 的新方案有三个支柱:

### 2.1 Sphere 代替 AABB

把玩家 collision shape 从 AABB 改成球。球的优势:

- **各向同性**:任何方向接触法线都是球心到接触点的方向(连续,不限于 6 轴)
- **便宜**:球-voxel 距离只需 3 个 min/max + 1 sqrt
- **拐角顺滑**:球"滚过"拐角,法线连续变化

```rust
struct Sphere { center: Vec3, radius: f32 }

fn sphere_aabb_unembed(s: &Sphere, b: &Aabb) -> Option<Vec3> {
    let closest = s.center.clamp(b.min, b.max);
    let d = s.center - closest;
    let dist_sq = d.length_squared();
    if dist_sq >= s.radius * s.radius { return None; }
    let dist = dist_sq.sqrt();
    Some(d * (s.radius / dist - 1.0))
}
```

### 2.2 Iterative resolution

不"一次解所有约束",**多轮迭代**——每轮每个 voxel 算 unembed 向量,累加,clamp,推进。多轮后收敛。

```rust
fn resolve(pos: &mut Vec3, r: f32) -> bool {
    for _ in 0..16 {
        let push = compute_total_push(*pos, r);
        if push.length_squared() < 1e-8 { return true; }
        let len = push.length();
        let step = if len > 0.1 { push * (0.1 / len) } else { push };
        *pos += step;
    }
    false
}
```

每轮 clamp 防"瞬移",多轮防"未收敛"。

### 2.3 Voxel flood fill 收集

代替"扫固定 3x3x3 voxel",**从球心 BFS 扩散**,收集所有"距离 < r + ε"的 voxel。这保证不漏(即使球大或边界复杂)。

```rust
fn collect_collision_voxels(center: Vec3, r: f32) -> Vec<IVec3> {
    let start = center.round().as_ivec3();
    let thresh_sq = (r + 0.5) * (r + 0.5);
    let mut q = VecDeque::new();
    let mut vis = HashSet::new();
    q.push_back(start);
    vis.insert(start);
    let mut res = Vec::new();
    while let Some(v) = q.pop_front() {
        res.push(v);
        for d in 6_DIRECTIONS {
            let n = v + d;
            if vis.contains(&n) { continue; }
            if (n.as_vec3() - center).length_squared() > thresh_sq { continue; }
            vis.insert(n);
            q.push_back(n);
        }
    }
    res
}
```

## 3 · 完整算法

合并三步:

```rust
fn resolve_player_collision(player: &mut Player, world: &World) {
    for _ in 0..16 {
        let voxels = collect_collision_voxels(player.pos, player.radius);
        let mut total_push = Vec3::ZERO;
        let mut any = false;
        for v in voxels {
            if !world.is_solid(v) { continue; }
            let v_min = v.as_vec3() - Vec3::splat(0.5);
            let v_max = v.as_vec3() + Vec3::splat(0.5);
            let closest = player.pos.clamp(v_min, v_max);
            let d = player.pos - closest;
            let dist_sq = d.length_squared();
            if dist_sq < player.radius * player.radius && dist_sq > 1e-10 {
                let dist = dist_sq.sqrt();
                total_push += d * (player.radius / dist - 1.0);
                any = true;
            }
        }
        if !any { break; }
        let len = total_push.length();
        let step = if len > 0.1 { total_push * (0.1 / len) } else { total_push };
        player.pos += step;
    }
}
```

## 4 · 与其他引擎对比

### 4.1 Box2D

Box2D 是 2D 物理标杆,用 **polygon shape + sequential impulse**:

- 凸多边形(不只 AABB)
- GJK 检测相交
- 速度级约束求解(impulse-based)
- Baumgarte position correction(允许小穿透稳定)

Casey 的简化版相当于把 Box2D 的 polygon 简化为 sphere,把 sequential impulse 简化为"per-frame push"。

### 4.2 PhysX

PhysX 是 NVIDIA 的 3D 物理,游戏标配:

- 多种 shape(球 / 胶囊 / OBB / convex / triangle mesh)
- TGS(Temporal Gauss-Seidel)求解器
- CCD(continuous collision detection)防 tunneling
- GPU 加速(PhysX 4+)

Casey 没做 CCD(玩家速度有限),没用 GPU(碰撞量小)。

### 4.3 Havok

Havok 是商业引擎标杆(很多 AAA 用):

- hkpAgent 多约束求解
- 高质量 character controller
- Ragdoll / vehicle / destruction 模块

Casey 远没 Havok 全面,但教学价值高——能看到每个决定。

### 4.4 Bullet

Bullet 是开源物理(Blender 用):

- Open source,跨平台
- btDiscreteDynamicsWorld 类似 PhysX
- MoveIT / 机器人领域用

Bullet 是"自建物理引擎"的好参考。

### 4.5 Rapier(Rust)

Rapier 是 Rust 2D / 3D 物理:

- 现代 Rust API
- bevy_rapier 集成 Bevy
- pipeline 类似 PhysX

如果你做 Rust 游戏,可以直接用 Rapier,不自己写。但理解 Casey 的实现能让你**读得懂 Rapier 源码**。

## 5 · 重构的工程价值

### 5.1 简化优先

Casey 的 voxel 碰撞比 Box2D / PhysX 简单几个数量级。**为什么不用现成库?**因为:

- 教学价值——学生看到每个算法
- 控制力——HH 想要"知道每个边角"的代码
- 性能——HH 场景固定(voxel + sphere),不需要 general physics

### 5.2 调试工具的关键作用

Day 638-644 的录制器是重构成功的关键——**没有它,Casey 无法诊断角落 bug**。这印证:**性能优化和重构必须有可视化工具**,否则盲调。

### 5.3 增量重构

Casey 没一次性重写——他 Day 636 加 unembed,Day 637 切球,Day 640-643 调角落 bug,Day 645 切中心约定。每一步可回滚,可测试。

这就是 **strangler vine pattern**——新代码逐步"包裹"老代码,最后老代码被替换。

## 6 · 性能分析

HH voxel 碰撞的性能:

| 操作 | 复杂度 | 实际耗时 |
|---|---|---|
| 球-AABB 距离 | O(1) | ~50 ns |
| Flood fill (27 voxels) | O(1) | ~1 μs |
| Iterative resolve (16 轮) | O(N voxels) | ~10 μs |
| 总 / 玩家 / 帧 | | ~15 μs |

60 FPS 帧预算 16.6 ms,碰撞占 0.1%。完全可接受。

对比 PhysX:同样场景 PhysX ~100 μs / 实体。HH 自建快 6 倍,因为简单(sphere + voxel,无 general shape)。

## 7 · 局限性

Casey 的方案的局限:

- **大物体**:球 r > 5 时 flood fill 扫太多 voxel。要 hierarchical broad phase(octree)
- **细长物体**:剑 / 鞭子,球不合适。要 capsule
- **非凸物体**:复杂 shape(树、椅子),球不准。要 convex decomposition
- **关节约束**:ragdoll 关节,需要 constraint solver。Casey 没做

这些是商业物理引擎解决的,HH 不在范围内。

## 8 · 给你的建议

如果你想给自己游戏加碰撞,几个路径:

### 8.1 小项目:用 Casey 风格

直接抄 Casey 的方案——球 + voxel + iterative resolve。代码 < 500 行,理解每一行。

### 8.2 中项目:用 capsule

需要胶囊时,扩展球-胶囊:

```rust
struct Capsule { a: Vec3, b: Vec3, r: f32 }

fn capsule_aabb_unembed(c: &Capsule, b: &Aabb) -> Option<Vec3> {
    let closest_on_segment = closest_point_on_segment(c.a, c.b, /* center of aabb */);
    let sphere = Sphere { center: closest_on_segment, radius: c.r };
    sphere_aabb_unembed(&sphere, b)
}
```

### 8.3 大项目:用 Rapier

集成 `rapier3d`,直接用。学习其 API,理解其 pipeline。读源码,看看工业级怎么写。

### 8.4 超大项目:用 PhysX / Havok

AAA 游戏级,集成 PhysX(Unreal 内置)或 Havok(商业 license)。

## 9 · 总结

Casey 的 voxel 碰撞重构是 HH 最重要的工程事件之一。它展示了:

- **抽象选择的影响**:AABB vs sphere 决定整个手感和代码复杂度
- **算法工程的平衡**:iterative resolution + flood fill 简单但有效
- **调试工具的关键作用**:录制器让重构可控
- **从零做 vs 用库**:理解每行 vs 调用 API,各有价值

你看完 HH 这部分,不仅"会用"碰撞,更**懂为什么**。这是 Casey 留下的真正遗产。

## 10 · 延伸阅读

本仓库本地:
- [day636.md](../day636.md) - day645.md 的全部 10 集
- [day050.md](../phase-2/day050.md) - 早期 Minkowski
- [phase-0/14-math-foundations.md](../phase-0/14-math-foundations.md) - 数学基础

外部稳定 URL:
- Box2D manual: https://box2d.org/documentation/
- Real-Time Collision Detection: https://realtimecollisiondetection.net/
- Erin Catto GDC 2014: https://box2d.org/files/ErinCatto_NumericalMethods_GDC2014.pdf

真实开源源码:
- Rapier: https://github.com/dimforge/rapier
- Box2D: https://github.com/erincatto/box2d
- Bullet: https://github.com/bulletphysics/bullet3
