---
phase: 2
type: bridge
title: "从 Phase 2 走到 Phase 3:2D 走完,准备进 3D"
domains: [game, graphics, math, rust]
prereqs: ["day026", "day070"]
---

# Bridge · 从 Phase 2 到 Phase 3

> 你刚把 Phase 2 走完。45 天。屏幕上有一个能跳能撞墙的角色,有一个能滚动的地图,有怪物、子弹、金币、音效、关卡、状态机、碰撞。你做的已经不是"一个能动的方块"——是一个**真正的小游戏**。你坐在那里看自己写的游戏跑起来,角色按方向键往前走,撞墙,跳起来,接到金币,叮——播一段你写的混音。你心想:这就是做游戏。然后呢?然后就是:**从 2D 走进 3D**。Phase 3 是 Handmade Hero 全程数学密度最大的一段——你之前用 `(x, y)` 描述世界,Phase 3 开始你要用 `(x, y, z)`。本文是过桥指南。

## §0 · 你已经走过的路

Phase 2 的 45 天,你做了一件大事:**把一个空窗口变成一个能玩的游戏**。按时间顺序复盘:

- **Day 26-32**:从"一个能动的方块"到"一个能撞墙的方块"。Casey 引入了 entity 的概念(`struct Entity { pos, vel, ... }`),AABB 碰撞检测,分轴碰撞响应。第一周结束时,你有了 2D 游戏最核心的三个东西:**位置、速度、碰撞**。

- **Day 33-40**:精灵图 + 动画 + 玩家控制器 + 跳跃曲线。从"方块"到"角色",从"按方向键就动"到"按方向键有加速度、跳跃有曲线、有手感"。这段时间 Casey 大量时间花在"调参数"——跳跃高度、重力系数、加速度大小。你第一次感受到**游戏感是调出来的,不是写出来的**。

- **Day 41-45**:架构整理。`day041` 是 HH 全程的教学金标——Casey 拉一张白纸,把"游戏架构"画给观众看,讲为什么平台层和游戏层要分开,讲为什么 entity 系统要演化。Phase 2 第一次架构重组。

- **Day 46-55**:entity 系统演化。从"Vec + index"到"sparse array + generation index"。这是工业级 ECS 的雏形——Casey 在这一段解决"use-after-free"(用了已销毁 entity 的 index)、"entity 的字段浪费"(墙不需要 hp 字段)、"遍历效率"(遍历所有怪物时遍历所有 entity 浪费)三个问题。

- **Day 56-65**:地图 + 关卡 + AI。地图从硬编码数组变成"加载 + 编辑器生成的数据",怪物 AI 从"随机走"演化成"看到玩家追玩家"。这是 2D 游戏第一个"内容"扩展——你不再是一个 demo,你是一个有内容的游戏。

- **Day 66-70**:音效集成 + 收尾。Phase 1 你写的音频系统(正弦波 + DirectSound),Phase 2 真正用起来——吃金币叮一声,跳跃咚一声,失败呃啊。Phase 2 收官,你有一个**完整可玩的 2D 游戏 demo**。

Phase 2 全程最值得记住的两件事:

**第一,entity 系统的演化**。Day 46-55 的 10 天,Casey 把 entity 从"`Vec<Entity>` 一把梭"演化到"sparse array + generation index + 类型分组"。这个演化的每一步都解决一个具体问题。你看完这 10 天,对**任何**严肃代码库的"实体管理"部分都能秒懂——因为所有引擎都走过了类似的演化路径。**`/home/sun/src/handmade-hero-guide/days/phase-2/deep-dives/entity-system.md`** 这一篇 25 KB 的深度文章把这些演化总结了一遍,建议 Phase 2 走完时回头看一次。

**第二,跳跃曲线的手感调参**。Day 33-40 你写的跳跃代码,实际只用了十几行——重力 + 初速度 + 时间。但**调参调了好几天**。Casey 直播里反复试"重力 1000 像素/秒² 还是 1500?""初速度 400 还是 500?""按住跳跳多高?"。这是 HH 全程"审美维度"最重的一段时间。**写代码是工程,调手感是设计**,Phase 2 让你第一次真切地体会到这两者的差别。

接下来 Phase 3 是 Day 71-111(41 天),主要内容:**把 2D 游戏升级为 3D**。3D 数学(向量、矩阵、四元数)、3D 软件光栅化(投影、裁剪、深度缓冲)、3D 几何(立方体、平面、相机)、3D 渲染(纹理映射、Phong 光照)。Phase 3 是 HH 全程数学密度最大的一段——你之前在 2D 里靠 `x` 和 `y` 两个数搞定的事,Phase 3 里要用矩阵乘法、点乘叉乘、投影变换。

## §1 · 进入 Phase 3 前的能力盘点

进 Phase 3 之前,你要确认你具备下面的能力。每一项打勾再进。

**A. 2D 向量数学**
- [ ] 能写出 `Vec2 { x: f32, y: f32 }` 的基本运算:`Add`、`Sub`、`Mul<f32>`(标量乘)、`Dot`(点乘)。
- [ ] 能解释点乘的几何意义:`a · b = |a| * |b| * cos(θ)`。两个向量方向相同时点乘最大(正值),垂直时为 0,反向时最小(负值)。
- [ ] 能写出 `Vec2::length` 和 `Vec2::normalize`,知道"normalize 是除以长度"。
- [ ] 能用向量算"两球是否碰撞":`distance(a.center, b.center) < a.radius + b.radius`。

**B. 碰撞检测**
- [ ] 能写出 `aabb_intersect(a: Rect, b: Rect) -> bool`:`a.x < b.x + b.w && a.x + a.w > b.x && a.y < b.y + b.h && a.y + a.h > b.y`。
- [ ] 能解释"分轴碰撞响应":先按 X 移动检查碰撞,再按 Y 移动检查碰撞。这样可以正确处理"贴墙滑行"。
- [ ] 知道"连续碰撞检测(CCD)"是什么——快速运动的物体可能在一帧内穿过薄的墙。Phase 3 你做 3D 时也会遇到,2D 学会了 3D 容易。
- [ ] 能写出"圆 vs 圆"和"AABB vs AABB"两种碰撞检测。**AABB vs AABB 用的更多**,因为玩家、怪、墙通常都是矩形。

**C. 实体系统**
- [ ] 能解释"sparse array"是什么——一个稀疏数组,内部用 `Vec<Option<Entity>>`,删除的 entity 设为 `None`,但 index 不变。
- [ ] 能解释"generation index"是什么——entity 销毁后内存复用,但 generation 加 1。如果你拿着旧 index + 旧 generation 来访问,会发现 generation 不匹配,知道"这个 entity 已经死了"。
- [ ] 能写出"返回 entity 句柄"的代码:`EntityHandle { index: u32, generation: u32 }`。所有跨函数引用 entity 都用 handle,不用 `&mut Entity`。
- [ ] 能解释"为什么不用 `Rc<RefCell<Entity>>`"——Rust 的 Rc 有运行时开销,RefCell 借用检查在运行时,RefCell panic 比游戏 crash 更难调试。Casey 在 HH 里全程手写 sparse array。

**D. 游戏循环 + 状态机**
- [ ] 能写出"游戏状态机"的 Rust enum:
  ```rust
  enum GameState {
      MainMenu,
      Playing { level: u32, score: u32 },
      Paused,
      GameOver,
  }
  ```
  并用 `match` 处理每个状态的 update / render。
- [ ] 能解释"主菜单 → 游戏 → 暂停 → 游戏结束"的状态转换怎么实现——`MainMenu` 里按 Enter 切到 `Playing`;`Playing` 里按 Esc 切到 `Paused`;等等。
- [ ] 能解释 `dt`(delta time)和"游戏内时间"的区别——dt 是真实时间,游戏内时间可能倍速(`dt * 2.0` 慢动作倒着用就是加速)。
- [ ] 知道"暂停"的实现:`if let GameState::Paused = state { return; }`——update 直接 return,渲染照常。

**E. 渲染基础**
- [ ] 能写出 `draw_bitmap(buf, x, y, bitmap)`,把一块 `&[u32]` 内存拷贝到后缓冲的指定位置。
- [ ] 能解释"透明色"和"alpha 混合"的区别——透明色是"指定一个颜色当透明,跳过拷贝",alpha 混合是"按 alpha 值加权混合源和目标"。
- [ ] 能写出最简单的 alpha 混合:`dst = src * alpha + dst * (1 - alpha)`,每个颜色通道分开算。
- [ ] 知道 sprite sheet 是什么——一张大图,内部切成多个小 sprite,通过 `(frame % total_frames) * frame_width` 算偏移。

**F. 数学准备(Phase 3 关键)**
- [ ] 知道"矩阵"是什么——一个二维数字表格,行 × 列。Phase 3 你大量用 3x3、4x4 矩阵。
- [ ] 知道"矩阵乘法"是什么——`C = A * B` 中 `C[i][j] = sum_k A[i][k] * B[k][j]`。**不满足交换律**:`A * B != B * A`。
- [ ] 能解释"线性变换"是什么——`f(x) = a*x + b`,输入输出是直线关系。Phase 3 的旋转、缩放、错切都是线性变换。
- [ ] 知道"齐次坐标"是什么——2D 点 `(x, y)` 用 `(x, y, 1)` 表示,3D 点 `(x, y, z)` 用 `(x, y, z, 1)` 表示。多出来的 `1` 让"平移"也能用矩阵乘法表示。
- [ ] 知道什么是"投影"——3D 点 `(x, y, z)` 投影到 2D 屏幕 `(sx, sy)`,最简单是 `sx = x / z, sy = y / z`(透视投影)。Phase 3 你会反复写这个。

**怎么用这张清单**:逐项打勾。哪一项打不上勾,回到 Phase 2 对应 day 补。Phase 3 第一周(3D 数学入门)就会用 §F 全部,你 §F 一项不通,Phase 3 第 1 天就卡。

## §2 · 自测题

下面 6 道题,先自己答再读参考答案。

### 题 1(2D 向量)

给定两个 2D 向量 `a = (3, 4)` 和 `b = (1, 0)`,计算:
1. `a + b`
2. `a · b`(点乘)
3. `a` 的长度
4. `a` 的 normalize 后的向量(单位向量)
5. `a` 和 `b` 之间的夹角(度数)

**参考答案**:

1. `a + b = (3 + 1, 4 + 0) = (4, 4)`
2. `a · b = 3*1 + 4*0 = 3`
3. `|a| = sqrt(3² + 4²) = sqrt(9 + 16) = sqrt(25) = 5`
4. `normalize(a) = (3/5, 4/5) = (0.6, 0.8)`
5. `cos(θ) = (a · b) / (|a| * |b|) = 3 / (5 * 1) = 0.6`,所以 `θ = acos(0.6) ≈ 53.13°`

这 5 个运算你都要会手算。Phase 3 在 3D 里它们完全一样,只是多一个分量。

### 题 2(AABB 碰撞)

写一个 Rust 函数 `aabb_intersect(a: Rect, b: Rect) -> bool`,其中 `Rect { x: f32, y: f32, w: f32, h: f32 }`,`x, y` 是左上角坐标,`w, h` 是宽高。然后解释:如果两个 AABB 都是"静止的",碰撞检测有多复杂?如果两个都"快速运动",会出什么问题?

**参考答案**:

```rust
#[derive(Copy, Clone)]
struct Rect { x: f32, y: f32, w: f32, h: f32 }

fn aabb_intersect(a: Rect, b: Rect) -> bool {
    // 两个矩形相交的充要条件:在 X 和 Y 两个轴上都"投影重叠"
    let overlap_x = a.x < b.x + b.w && a.x + a.w > b.x;
    let overlap_y = a.y < b.y + b.h && a.y + a.h > b.y;
    overlap_x && overlap_y
}
```

复杂度分析:
- 两个静止 AABB,O(1)——4 个比较 + 2 个 AND。
- 一帧内做 N 个 entity 互相碰撞,O(N²)——双重循环。1000 个 entity 是 100 万次检测,每次 ~10ns,总共 10ms,刚好够 60 FPS。**这是为什么严肃游戏要做"空间划分"**(BVH、网格、quadtree),把 N² 降到 N log N。

快速运动的问题:**tunneling(穿透)**。一颗子弹每帧前进 1000 像素,但墙只有 50 像素厚。这一帧子弹在墙左边,下一帧子弹在墙右边——aabb_intersect 永远返回 false,子弹穿墙。

解决方案:
- **CCD(连续碰撞检测)**:把子弹的运动看成"线段",做"线段 vs AABB"相交。
- **多步推进**:每帧分 10 个小步,每步推进 100 像素,每步检查碰撞。计算量乘以 10。
- **限制最大速度**:简单粗暴——但游戏感觉差。

### 题 3(entity 系统)

下面这段 Rust 代码有什么 bug?如何修?

```rust
struct World {
    entities: Vec<Option<Entity>>,
}

impl World {
    fn spawn(&mut self, e: Entity) -> usize {
        self.entities.push(Some(e));
        self.entities.len() - 1  // 返回 index 作为句柄
    }

    fn despawn(&mut self, index: usize) {
        self.entities[index] = None;
    }

    fn get(&self, index: usize) -> Option<&Entity> {
        self.entities[index].as_ref()
    }
}
```

**参考答案**:

Bug:**use-after-free**——句柄失效。

场景:
1. `let player = world.spawn(player_entity);  // player == 5`
2. `world.despawn(5);  // entities[5] = None`
3. 后续某处:`world.spawn(monster);  // 因为 push 到末尾,index 是 6,不是 5。`——这部分没问题
4. **但是**:`world.entities.push(Some(e))` 不会复用 `None` 的槽位。所以 index 单调增,直到 Vec 撑爆内存。
5. 真正的 bug 在另一种场景:
   1. `let i = world.spawn(player);  // i == 5`
   2. 某代码持有 `i` 跨多个函数调用
   3. `world.despawn(5);  // entities[5] = None`
   4. **如果你优化成"复用空槽"**:`world.spawn(monster);  // 槽 5 复用,monster 进 entities[5]`
   5. 现在持有旧 `i = 5` 的代码访问 entities[5],拿到的是 **monster**,不是已死的 player。**类型对了但语义错了**。

修复:**generation index**。

```rust
struct World {
    entities: Vec<Option<Entity>>,
    generations: Vec<u32>,  // 每个 index 对应的"代"
}

#[derive(Copy, Clone, PartialEq, Eq)]
struct Handle {
    index: usize,
    generation: u32,
}

impl World {
    fn spawn(&mut self, e: Entity) -> Handle {
        // 找一个空槽(简化版,生产用 free list)
        for i in 0..self.entities.len() {
            if self.entities[i].is_none() {
                self.generations[i] += 1;  // 槽位复用,代 +1
                self.entities[i] = Some(e);
                return Handle { index: i, generation: self.generations[i] };
            }
        }
        self.entities.push(Some(e));
        self.generations.push(0);
        Handle { index: self.entities.len() - 1, generation: 0 }
    }

    fn get(&self, h: Handle) -> Option<&Entity> {
        // 关键:检查 generation 是否匹配
        if self.generations[h.index] == h.generation {
            self.entities[h.index].as_ref()
        } else {
            None  // 旧句柄,entity 已死
        }
    }
}
```

generation 不匹配时返回 None,**不会错误返回别的 entity**。这是工业级 ECS 的核心。

### 题 4(齐次坐标)

为什么 3D 图形要用 4D 向量 `(x, y, z, w)` 和 4x4 矩阵,而不是 3D 向量 `(x, y, z)` 和 3x3 矩阵?

**参考答案**:

为了**用矩阵乘法表示平移**。

3x3 矩阵乘 3D 向量:`M * v`,结果是 `M * v = (a*v.x + b*v.y + c*v.z, ...)`,**永远过原点**。无论 M 是什么,`M * (0, 0, 0) = (0, 0, 0)`——原点被固定。所以平移("加一个常数向量")**不可能**用 3x3 矩阵乘表示。

4x4 矩阵乘 4D 向量(齐次坐标):

```
| 1 0 0 tx |   | x |   | x + tx |
| 0 1 0 ty | * | y | = | y + ty |
| 0 0 1 tz |   | z |   | z + tz |
| 0 0 0 1  |   | 1 |   |   1    |
```

平移完美表达成矩阵乘法。所以 3D 图形全程用 4D 向量 `(x, y, z, w)`,其中 `w` 一般是 1(点)或 0(方向向量)。`w = 0` 时平移部分 `tx, ty, tz` 不影响——这正确表达了"方向不受平移影响"。

齐次坐标的另一个好处:**投影矩阵**(透视、正交)自然落在 4x4 里。透视投影把 z 分量"塞进" w,投影后 `(x/w, y/w)` 就是屏幕坐标。

### 题 5(矩阵不满足交换律)

给定两个变换:旋转 R(绕 Z 轴 90°)和平移 T(沿 X 轴 100 单位)。`R * T` 和 `T * R` 应用到原点 `(0, 0, 0)` 上,结果分别是什么?

**参考答案**(用 2D 简化,3D 同理):

旋转矩阵(绕原点 90°):
```
R = | 0 -1 |
    | 1  0 |
```

平移矩阵(齐次坐标):
```
T = | 1 0 100 |
    | 0 1 0   |
    | 0 0 1   |
```

`T * R`(先旋转后平移):
```
T * R = | 0 -1 100 |
        | 1  0 0   |
        | 0  0 1   |
```
应用到原点 `(0, 0, 1)`:`(0*0 + -1*0 + 100*1, 1*0 + 0*0 + 0*1, 1) = (100, 0, 1)`。**先转 90 度(原点不动),再平移到 (100, 0)**。

`R * T`(先平移后旋转):
```
R * T = | 0 -1 0 |
        | 1  0 100 |
        | 0  0 1 |
```
应用到原点 `(0, 0, 1)`:`(0*0 + -1*0 + 0*1, 1*0 + 0*0 + 100*1, 1) = (0, 100, 1)`。**先平移到 (100, 0),再绕原点转 90 度,跑到 (0, 100)**。

两个结果完全不同。这是为什么写图形代码时要**极其小心矩阵乘法顺序**。

惯例:**列向量约定下**(数学/OpenGL 主流),`M = T * R` 表示"先 R 后 T"。`*` 号从右往左读。Phase 3 你要熟练这个约定。

### 题 6(2D → 3D 的转换)

把下面这段 2D 碰撞响应代码改成 3D:

```rust
fn resolve_collision(pos: &mut Vec2, vel: &mut Vec2, hit_wall: (bool, bool)) {
    // hit_wall = (hit_x, hit_y),X 和 Y 是否撞墙
    if hit_wall.0 {
        vel.x = 0.0;  // X 方向停下
    }
    if hit_wall.1 {
        vel.y = 0.0;
    }
}
```

**参考答案**:

3D 版本:

```rust
fn resolve_collision(pos: &mut Vec3, vel: &mut Vec3, hit_wall: (bool, bool, bool)) {
    if hit_wall.0 { vel.x = 0.0; }
    if hit_wall.1 { vel.y = 0.0; }
    if hit_wall.2 { vel.z = 0.0; }
}
```

3D 多一个 Z 分量,但**逻辑完全一样**。这就是 2D 数学和 3D 数学的真正关系:**3D 是 2D 加一个分量**。

实际 3D 碰撞响应比这复杂——3D 里"墙"是面,有法向量(normal),碰撞响应通常按"法向量方向"反弹。但**核心思路**和 2D 一致:**碰撞方向上速度归零,其他方向保留**。

```rust
// 3D 碰撞响应(法向量版)
fn resolve_collision_along_normal(vel: &mut Vec3, normal: Vec3) {
    let v_dot_n = vel.dot(&normal);  // 速度在法向量上的分量
    if v_dot_n < 0.0 {  // 朝向墙
        *vel = *vel - normal * v_dot_n;  // 减去法向量方向的分量
    }
}
```

这个法向量版同时适用于 2D 和 3D,只是 Vec3 vs Vec2。

## §3 · 心智切换:从 (x, y) 到 (x, y, z)

Phase 2 的 45 天,你的世界是 2D 的:每个位置是 `(x, y)`,每个速度是 `(vx, vy)`。你的代码里没有 z,没有"深度"。屏幕坐标系就是世界坐标系,世界 1 单位 = 屏幕 1 像素。

Phase 3 的 41 天,你的世界变成 3D:每个位置是 `(x, y, z)`,每个速度是 `(vx, vy, vz)`。世界不再等于屏幕——你要把 3D 世界**投影**到 2D 屏幕。这是巨大的心智切换。

具体有 5 条:

**1. 屏幕不再是世界**。
Phase 2:世界坐标 `(100, 200)` 直接画到屏幕 `(100, 200)`。Phase 3:世界坐标 `(3, 4, 5)` 经过 view 矩阵、projection 矩阵变换后,才变成屏幕坐标。中间隔着几层变换,**调试时要能在脑子里"反向追踪"**。

**2. 多了一维就多了一类错误**。
2D 里"在墙左边"和"在墙右边"两种状态。3D 里"在墙前面 / 后面 / 左面 / 右面 / 上面 / 下面"六种状态。bug 的可能性乘以几倍。**早期你写 3D 代码会大量出"为什么我的立方体看起来是扁的"这种 bug**,90% 是某个矩阵写错了。

**3. 视角**(camera / view)是新概念。
Phase 2 你的"摄像机"就是屏幕的一个 offset——`cam_x, cam_y`,画的时候减掉。Phase 3 摄像机是一个有"位置 + 朝向 + 上方向"的对象,view 矩阵把世界变换到"摄像机视角"。**摄像机本身有 6 个自由度**(位置 3 + 朝向 3),自由度增加带来表达力,也带来复杂度。

**4. 投影**(projection)是新概念。
2D 没有"远近"——所有东西都在同一个平面。3D 有"远近",远的看起来小,近的看起来大。这叫**透视投影**,用一个 4x4 矩阵表达。Phase 3 你要写投影矩阵,**手算一次投影矩阵**(画在纸上)能极大加深理解。

**5. 性能突然变重要**。
2D 游戏每帧画几千个像素,几十个 sprite,几百次碰撞检测,现代 CPU 任何代码都跑得动。3D 游戏每帧画几十万像素(每个三角形覆盖的像素),几百次三角面,碰撞检测从"点 vs AABB"变成"球 vs 三角形 vs BVH"。**性能**从 Phase 3 开始变成头号问题。Phase 4 全程专门讲优化,Phase 3 是优化的"伏笔"。

**心智切换的具体练习**:Phase 3 第一周(3D 数学入门)每天画一次"坐标系图"——画一个 3D 笛卡尔坐标系,标出 X、Y、Z 三个方向,然后随便点几个点 `(1, 2, 3)`、`(-1, 0, 2)`,看清楚它们在哪个象限。**这是把 3D 直觉建立起来的最快方法**。Casey 在 HH 视频里反复在白板上画坐标系,不是因为他不会用图形软件,是因为**画一遍,理解深一层**。

切换的最大陷阱是**死记公式**——把投影矩阵、view 矩阵、各种变换矩阵当"魔法数字"硬背。Phase 3 你做不下去的根本原因,通常不是"代码不会写",而是"不知道这个矩阵在做什么"。**每个矩阵你都要会用白板推导一遍**。我不会把推导写在这——你自己推一遍,记一辈子。我推荐 `/home/sun/src/handmade-hero-guide/days/phase-3/deep-dives/projection-matrices.md`,那里有完整的从"为什么需要投影"到"4x4 矩阵每一项的几何意义"。

## §4 · 进 Phase 3 第一周学习路径

下面是 Phase 3 第 1-7 天的逐日学习路径。

**Day 71-72(对应 HH day71-72)**:**3D 向量 + 矩阵入门**。
重点:`Vec3`、`Vec4`(齐次坐标)、`Mat4`(4x4 矩阵)。点乘、叉乘的几何意义。**叉乘是 Phase 2 没有的新东西**——两个 3D 向量叉乘得到一个**垂直于两者**的向量,长度是它们张的平行四边形面积。
产出:你能写出 `Vec3` 全部运算,手算 `(1, 0, 0) × (0, 1, 0) = (0, 0, 1)`。
建议:画 10 张坐标系图。

**Day 73-74(对应 HH day73-74)**:**变换矩阵**。
重点:平移矩阵、旋转矩阵(绕 X / Y / Z 三个轴)、缩放矩阵。矩阵乘法链:`M = T * R * S`(先缩放,再旋转,再平移——读顺序从右往左)。**这一段最容易写错**,任何顺序错了,模型就飞了。
产出:你能写出一个立方体从局部坐标变换到世界坐标的代码。
建议:在纸上手算一次 `T * R` 应用到原点。

**Day 75-76(对应 HH day75-76)**:**view 矩阵 + 摄像机**。
重点:view 矩阵把世界坐标变换到"摄像机视角"——摄像机放在哪里、看哪里、上方向是什么。最简单的构造:`look_from`, `look_at`, `up` 三个向量构造 view 矩阵。
产出:你能让一个立方体出现在摄像机视野里。
建议:第一人称摄像机(`look_from` 是玩家位置,`look_at` 是玩家位置加朝向)是 FPS 的基础,熟悉它。

**Day 77-78(对应 HH day77-78)**:**投影矩阵**。
重点:透视投影矩阵把 3D 变换到"裁剪空间"(clip space),再除以 w 得到 NDC(normalized device coordinate,`[-1, 1]^3` 立方体),再映射到屏幕。**这段是 Phase 3 数学的高潮**——投影矩阵的每一项都有几何意义。
产出:你能在屏幕上看到一个真正的 3D 立方体(透视下,远的面小,近的面大)。
建议:`/home/sun/src/handmade-hero-guide/days/phase-3/deep-dives/projection-matrices.md` 这一篇读完。

**Day 79-81(对应 HH day79-81)**:**软件光栅化入门**。
重点:把一个三角形从"3 个 3D 顶点"画到"屏幕上一堆像素"。这叫**光栅化**(rasterization)。最简单的算法是"扫描线填充"——找出三角形 bounding box,逐像素判断是否在三角形内,在的话填色。
产出:屏幕上有一个三角形。
坑:深度排序。两个三角形重叠时,哪个画前面?(Phase 3 用画家算法——按深度排序,远的先画近的后画。Phase 4 用 z-buffer——每个像素存深度,更近的覆盖更远的。)

**Day 82-83(对应 HH day82-83)**:**纹理映射入门**。
重点:每个三角形顶点除了 3D 位置,还有 2D 纹理坐标 `(u, v)`(贴图上的位置)。光栅化时,**对每个像素,根据其重心坐标插值 u, v**,然后从纹理图取颜色。
产出:三角形上有图。
坑:透视投影下,纹理坐标需要**透视校正**(perspective correction)。Phase 3 你先忽略,Phase 4 修。

**Day 84(对应 HH day84)**:**反思 + 整理**。
重点:第 1-2 周代码量大增,你要做架构整理——把数学库独立成 `math.rs`,把光栅化器独立成 `rasterizer.rs`,把场景数据(三角形列表)独立成 `scene.rs`。

第一周结束你应该有:一个能在屏幕上显示 3D 立方体的程序,立方体有纹理,能旋转。

## §5 · 实战项目建议

光看视频不够。下面三个项目,任选一个自己写。

### 项目 A:3D 模型查看器

从零写一个 OBJ 模型查看器。技术栈:Rust + 自己的软件光栅化器(不用 GPU)。

需求:
- 读 `.obj` 文件(纯文本格式,每行 `v x y z` 是顶点,`f v1 v2 v3` 是三角面)。
- 用 Phase 3 学的变换 + 投影 + 光栅化,画到屏幕。
- 支持鼠标拖动旋转模型,滚轮缩放。
- 支持基本光照(Phong)。

时间预算:2-3 周。

为什么推荐:OBJ 是 3D 模型的"hello world",做出来你能看任何 3D 模型。**而且软件光栅化让你从底层理解 GPU 在做什么**——GPU 不过是你这个软件光栅化器的硬件加速版。Phase 5 你学 OpenGL 时回头看,会发现 OpenGL 的大部分概念你已经会了。

### 项目 B:3D 第一人称走廊(demo)

从零写一个 FPS 风格的走廊,玩家在里面走。

需求:
- 用几个立方体拼一个简单走廊(地板、天花板、左右墙)。
- WASD 移动,鼠标看,空格跳。
- 墙壁有纹理。
- 玩家撞墙不能穿。

时间预算:2 周。

为什么推荐:第一人称摄像机是 Phase 3 最实用的技术。做完这个 demo,你基本就懂了所有 FPS 的核心。Minecraft、Doom、Quake 都是这套机制扩展出来的。

### 项目 C:3D 模拟太阳系

从零写一个 3D 太阳系。

需求:
- 太阳在中心,8 个行星绕太阳转。
- 每个行星有自己的速度、半径、颜色。
- 鼠标拖动改变视角。
- 行星有纹理(随便找图)。

时间预算:1-2 周。

为什么推荐:太阳系是练习**层级变换**的好题目——行星绕太阳转,卫星绕行星转,用矩阵栈(`push / pop`)实现。`push` 把当前矩阵存起来,`pop` 取出。**层级变换是骨骼动画的基础**,Phase 3 学了,Phase 5 做动画就用得上。

### 不推荐的项目

- **完整 3D 游戏**:Phase 3 还没教性能优化,大场景跑不动。
- **Phong 光照的复杂场景**:光照是 Phase 5-6 的事,Phase 3 知道概念就行。
- **骨骼动画**:Phase 3 后期 Casey 演示,但完整实现留到 Phase 5。

## §6 · 推荐配合的 deep-dive

`/home/sun/src/handmade-hero-guide/days/phase-2/deep-dives/` 里有几篇进 Phase 3 前值得读的:

### `entity-system.md`(强推荐)

25 KB 的 entity 系统演化文章,从"朴素 struct"到"工业 ECS"。Phase 2 你跟 Casey 走过了这个演化,这篇让你**把演化逻辑结构化**——每一阶段解决什么问题、引入什么新问题。

Phase 3 Casey 不会重新发明 entity 系统(他在 Phase 2 已经定型),Phase 3 直接用 Phase 2 的版本,所以这篇读完 Phase 3 一开始你就稳了。

### `math-foundations-for-games.md`(强推荐)

2D 数学基础。Phase 3 你要做 3D 数学,**2D 数学必须先熟练**。这篇覆盖:向量运算、矩阵运算、三角函数、几何变换。Phase 3 第一周你天天用这些。

### `collision-detection.md`(推荐)

2D 碰撞的完整覆盖。Phase 3 后期(3D 碰撞)和 Phase 5(物理)都要用。**先读 2D 版**,因为 3D 是 2D 的扩展,2D 懂了 3D 容易。

### `rust-cdylib-and-ffi.md`(可选)

Phase 2 的某个时点你也许好奇"`#[no_mangle] pub extern "C" fn` 到底做了什么"。这篇彻底讲清楚 Rust 的 FFI。**不是必需**,但有疑问时来读。

---

`/home/sun/src/handmade-hero-guide/days/phase-3/deep-dives/` 里的推荐(Phase 3 第一周开始读):

### `rasterization-from-scratch.md`(强推荐)

软件光栅化的完整推导。Phase 3 Day 79-83 你做光栅化时,这篇是**必读的参考**。Casey 在视频里花了好几集讲光栅化,这篇把视频内容浓缩成可索引的文字。

### `projection-matrices.md`(强推荐)

投影矩阵的完整几何推导。Phase 3 Day 77-78 必读。

### `simd-progression.md`(后期再读)

SIMD 优化。Phase 4 才用得到,Phase 3 先知道概念即可。

---

## 结语

Phase 2 是"做 2D 游戏",Phase 3 是"做 3D 游戏"。表面看差别是"多一个 z 分量",实际差别是**整套世界观的扩展**——从平面到立体,从直接坐标到投影变换,从"屏幕就是世界"到"屏幕是世界的某个视角的投影"。

Phase 3 第一周你会觉得"什么矩阵什么投影,看不懂"。**坚持一周**,自己手算几次,画几张坐标系图,然后突然有一天就通了——你看着自己写的 3D 立方体在屏幕上旋转,你能清楚地反向追踪"屏幕上这个像素对应 3D 空间的哪个点经过了哪些变换"。**那一刻就是 3D 数学的"开窍时刻"**。

Casey 在 HH 里反复说:"数学不是用来背的,是用来用的"。Phase 3 第一周你被矩阵折磨,但只要坚持写代码、画图、调试,一周后这些矩阵就是你的肌肉记忆。然后 3D 游戏的大门就开了。

下一站:Day 71。准备好你的纸和笔,准备好画第一个 3D 坐标系。
