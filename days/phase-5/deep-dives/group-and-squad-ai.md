---
phase: 5
title_en: "Group & Squad AI"
title_zh: "群体与班组 AI:从涌现式鸟群到协同战术的完整推导"
type: deep-dive
difficulty: 4
duration: "2-3 小时"
domains: [game, rust, cs, ai]
prereqs: ["ai-patterns", "ai-perception-and-memory"]
calibration: "Millington《AI for Games》— 群体 AI(flocking / 编队 / 指挥 / squad 协调)"
---

# 群体与班组 AI:从涌现式鸟群到协同战术的完整推导

> 你的卫兵已经"够聪明"了。你按 [ai-patterns](../../phase-2/deep-dives/ai-patterns.md) 给他装了 behavior tree,按 ai-perception-and-memory 给他装了视野和听觉,他能在巡逻里发现玩家、追击、回血、撤退——单个看,他像模像样。然后你在大厅放五个这种卫兵,把玩家放进去。结果是灾难:五个人全部沿同一条 A* 路径冲向玩家,在唯一的门洞口挤成一团,谁也过不去,然后开始原地抖动(separation 没设,互相重叠);其中一个从侧面绕进来开枪,但他的四个队友正好挡在他和玩家之间,子弹穿模——五个聪明人合起来比一个 dumb NPC 还蠢。这是个人 AI 解决之后,**群体 AI(group AI)**才暴露出来的真问题。Casey 在 HH 里一个房间只放两三只怪物,所以从来没撞上这堵墙;但凡你想做一场"战斗"——士兵会包抄、会掩护、会有人 reload 时让队友顶上、会有人绕侧翼——你就必须把视线从"个体大脑"抬到"群体大脑"。这一篇就专讲这件事:从 Craig Reynolds 1986 年那三条 boids 规则,讲到 RTS 的 formation(编队),再到 F.E.A.R. 和 Halo 那种 squad tactics(班组战术)与 command hierarchy(指挥层级),最后落到你 HH 项目里。Ian Millington 在《AI for Games》第三部分"Group Movement"和"Group Behaviors"两章花了八十页讲这套,我们就把那条主线一气讲透。

## 0 · 五个聪明人堵死一扇门

把上面这个场景再写实一点。你 `git stash` 一下当前 HH 项目,打开 `update_combat` 函数,看每个 enemy 的 tick:

```rust
for enemy in enemies.iter_mut() {
    let path = astar(enemy.pos, world.player.pos, &world.navmesh);
    enemy.move_along(path, dt);
    if dist(enemy.pos, world.player.pos) < ATTACK_RANGE && can_see(enemy, world.player.pos) {
        enemy.fire(world.player.pos);
    }
}
```

每只 enemy 独立寻路、独立开火。逻辑上每只都对。但你跑起来,在门口会看到三件事:五条 A* 路径在门洞处完全重合(同一个 navmesh polygon,同一条 shortest path);没有任何一只 enemy 知道另外四只的存在——它们彼此就是"透明的墙";路径终点都指向玩家身前同一格,所以即便都挤过去了,它们也会叠在一起,炮口对穿。

**问题不在每只 enemy 不够聪明,问题在它们没有任何协调**。你可以给单个 enemy 升级到 GOAP、HTN、加上 tracy profile——都没用,因为瓶颈是 GROUP 层。Millington 在书的引言里专门点出来:individual competence does not aggregate into group competence——个人能力强不会自动累加成群体能力。协调要么从底层涌现(像鸟群),要么在顶层显式管理(像军队指挥);介于两者之间的灰色地带,就是这一篇的全部内容。

## 1 · 群体 AI 的两条路线:涌现 vs 显式管理

在你写代码之前,先把群体 AI 的"思想地图"理清楚。所有群体 AI 技术,本质上都在一条光谱上滑动。

光谱的**左端是涌现(emergent)**——没有任何中心权威,每个 agent 只看自己周围的邻居,根据局部规则行动,群体智能从这些局部规则的相互作用中"涌现"出来。Flocking(鸟群)是这一端的招牌:Reynolds 的 boids 里没有一只"领头鸟",但整群鸟能拐弯、能绕障、能撕裂再汇合。它的美在于便宜和自然——你不需要为每只鸟规划,整个群体就活了。

光谱的**右端是显式管理(explicit management)**——存在一个中心(指挥官、AI Director、squad leader),它给每个成员分配角色、位置、任务,成员严格执行。军事小队就是这一端的典型:指挥官说"你三点钟方向压制、你从侧翼包抄、你守后门",这是设计过的战术,不是涌现的。它的好处是可控、可导演;坏处是贵、不灵活、而且一旦指挥官挂了整个小队就瘫痪(真实军队也是这样)。

光谱的**中间**是 hybrid(混合)——大部分工业级 squad AI 都在这:有一个 squad-level 决策器决定大方向(谁压制、谁包抄),但底层执行仍然用 steering behaviors(包抄的那只 enemy 怎么绕开队友、怎么贴墙走)是涌现的。**这一篇按光谱从左到右讲**:先 flocking,再 formation,再 squad tactics,最后 command hierarchy。每往右一格,中心控制就强一分,群体行为就从"自然流动"变成"导演出来的戏剧"。

## 2 · Flocking:三条规则涌现一群鸟

### 2.1 Reynolds 的洞察

1986 年,Craig Reynolds 想模拟鸟群。最直接的做法是给每只鸟编一个"我要跟着鸟群"的程序,但你会发现——鸟群里根本没有"鸟群"这个实体。鸟群不是被指挥出来的,它是每一只鸟都遵守三条简单规则后**自动形成**的。Reynolds 把这种 agent 叫 boid(以下就统一叫 boid)。三条规则是:第一条 **separation(分离)**——不要挤到邻居身上,周围一定半径内的 boid 太近就产生一个反向推力;第二条 **alignment(对齐)**——把朝向调成跟邻居的平均朝向一致;第三条 **cohesion(凝聚)**——朝周围 boid 的几何中心移动一点,让群体保持在一起。

**没有第四条规则**。没有"跟着队长"。没有"目标在哪"。没有中心。但只要这三条规则加上合适的权重,鸟群就会自然地拐弯、撕裂、绕障——你看上去就像有一个统一的意志在指挥。这是复杂系统理论里 emergence(涌现)最经典的演示之一,也是为什么 Millington 把它放在群体 AI 章节的开篇:**它告诉你,复杂的群体行为不一定需要复杂的群体大脑,可能只需要简单的局部规则**。

### 2.2 三个 steering 力,Rust 实现

[ai-patterns](../../phase-2/deep-dives/ai-patterns.md) 第 6 节已经给了 seek / flee / separation 的雏形,这里把 flocking 的三个力写完整。boid 的 `Vec2` 复用 ai-patterns 里那套(包含 `add` / `sub` / `scale` / `normalize` / `truncate`),不再重复。三个力的实现有一个共同的形态——把邻居循环一遍,把某个量(方向差、速度、位置)累加,归一化成 steering force:

```rust
const VIEW_RADIUS: f32 = 60.0;
const MAX_SPEED:   f32 = 90.0;   // 像素/秒
const MAX_FORCE:   f32 = 300.0;

#[derive(Clone, Copy)]
struct Boid { pos: Vec2, vel: Vec2 }

// separation:力的大小和距离成反比(越近推得越狠),所以方向向量要除以距离
fn separation(self_b: &Boid, neighbors: &[Boid]) -> Vec2 {
    let mut steer = Vec2::ZERO;
    let mut count = 0;
    for n in neighbors {
        let diff = self_b.pos.sub(n.pos);
        let d = diff.length();
        if d > 1e-3 && d < VIEW_RADIUS {
            steer = steer.add(diff.normalize().scale(1.0 / d));  // 反比加权
            count += 1;
        }
    }
    if count == 0 { return Vec2::ZERO; }
    steer.scale(1.0 / count as f32).normalize().scale(MAX_SPEED)
        .sub(self_b.vel).truncate(MAX_FORCE)
}

// alignment:邻居速度的平均方向
fn alignment(self_b: &Boid, neighbors: &[Boid]) -> Vec2 {
    let mut sum_vel = Vec2::ZERO;
    let mut count = 0;
    for n in neighbors {
        let d = self_b.pos.sub(n.pos).length();
        if d > 1e-3 && d < VIEW_RADIUS { sum_vel = sum_vel.add(n.vel); count += 1; }
    }
    if count == 0 { return Vec2::ZERO; }
    sum_vel.scale(1.0 / count as f32).normalize().scale(MAX_SPEED)
        .sub(self_b.vel).truncate(MAX_FORCE)
}

// cohesion:邻居位置的几何中心,seek 过去
fn cohesion(self_b: &Boid, neighbors: &[Boid]) -> Vec2 {
    let mut center = Vec2::ZERO;
    let mut count = 0;
    for n in neighbors {
        let d = self_b.pos.sub(n.pos).length();
        if d > 1e-3 && d < VIEW_RADIUS { center = center.add(n.pos); count += 1; }
    }
    if count == 0 { return Vec2::ZERO; }
    let center = center.scale(1.0 / count as f32);
    center.sub(self_b.pos).normalize().scale(MAX_SPEED)
        .sub(self_b.vel).truncate(MAX_FORCE)  // = seek(self_b, center)
}
```

把三个力加权求和,flocking 就有了:

```rust
const W_SEPARATION: f32 = 1.5;  // 通常分离权重最大,否则会重叠
const W_ALIGNMENT: f32 = 1.0;
const W_COHESION:  f32 = 1.0;

fn flocking(self_b: &Boid, all: &[Boid]) -> Vec2 {
    let neighbors: Vec<Boid> = all.iter()
        .filter(|n| { let d = self_b.pos.sub(n.pos).length(); d > 1e-3 && d < VIEW_RADIUS })
        .map(|n| *n).collect();
    let sep = separation(self_b, &neighbors).scale(W_SEPARATION);
    let ali = alignment (self_b, &neighbors).scale(W_ALIGNMENT);
    let coh = cohesion  (self_b, &neighbors).scale(W_COHESION);
    sep.add(ali).add(coh).truncate(MAX_FORCE)
}

fn update_boid(b: &mut Boid, all: &[Boid], dt: f32) {
    let accel = flocking(b, all);
    b.vel = b.vel.add(accel.scale(dt)).truncate(MAX_SPEED);
    b.pos = b.pos.add(b.vel.scale(dt));
}
```

### 2.3 调权重的手感

这里要讲清楚一件事:**flocking 是一套"调参"游戏**,不是写完就工作的。Reynolds 自己都说三权重的搭配对群体感影响极大。给你一组经验起点——separation 通常最大(不然会重叠),cohesion 和 alignment 几乎相等。但你要看效果反推:群体太散拉不到一起,cohesion 不够;变成一坨黏在一起的果冻,cohesion 太重 / separation 太轻;群体往一个方向冲停不下来拐不了弯,alignment 太重——所有 boid 一旦朝一个方向对齐就再也散不开。

实际工程里,你会反复在 tracy 里看 boid 的速度向量,反复调这三个数,直到群体感觉"对"。这个过程没法跳过,因为"对"是主观的——你模拟鸟就要轻盈、模拟鱼就要稠密、模拟丧尸人群就要沉重且容易分裂。**没有一组合适所有游戏的权重**,这就是为什么 flocking 库通常把权重作为参数暴露给使用者。

### 2.4 性能:O(N²) 和它的解法

注意上面 `flocking` 函数第一步——**每只 boid 都要遍历所有 boid 找邻居**。N 只 boid 就是 O(N²)。100 只没问题,1000 只就开始卡,10000 只就直接死机。

工业解法是**空间划分(spatial partitioning)**——把空间切成格子(grid),每只 boid 只在自己所在的格子以及相邻 8 格里找邻居,复杂度降到接近 O(N)。这个主题在 [spatial-acceleration](../../phase-6/deep-dives/spatial-acceleration.md) 里有完整推导,这里给你最朴素的 grid 思路:

```rust
struct SpatialGrid {
    cell_size: f32,
    cells: HashMap<(i32, i32), Vec<usize>>,
}
impl SpatialGrid {
    fn rebuild(&mut self, boids: &[Boid]) {
        self.cells.clear();
        for (i, b) in boids.iter().enumerate() {
            let k = ((b.pos.x / self.cell_size) as i32, (b.pos.y / self.cell_size) as i32);
            self.cells.entry(k).or_default().push(i);
        }
    }
    fn query_neighbors(&self, p: Vec2, radius: f32) -> Vec<usize> {
        let mut out = Vec::new();
        let (cx, cy) = ((p.x / self.cell_size) as i32, (p.y / self.cell_size) as i32);
        let span = (radius / self.cell_size).ceil() as i32;
        for dx in -span..=span { for dy in -span..=span {
            if let Some(b) = self.cells.get(&(cx + dx, cy + dy)) { out.extend(b); }
        }}
        out
    }
}
```

`cell_size` 取 `VIEW_RADIUS` 是常见选择——这样 query 时只看 3x3 的格子就够覆盖视野半径。把每帧的 `rebuild` + `query` 替换掉 `flocking` 里那个 O(N²) 的 filter,flocking 立刻能撑到几千只 boid。

### 2.5 flocking 的局限:它只是"看起来像一群"

现在 flocking 跑起来了,鸟群活灵活现。但你要清楚它的边界:**flocking 解决的是"运动看起来像一群",而不是"群体在做什么"**。一群鸟绕过电线杆,是涌现的;但一群士兵会不会包抄、一群丧尸会不会分散搜索房间,flocking 一概不管——它只管"贴着飞"。所以 flocking 适合:鸟、鱼、人群背景、丧尸潮的宏观流动。它**不适合**直接拿来当战术小队的运动模型——士兵的运动是有目的、有角色的,得用下一节的 formation 和 squad tactics。

很多新人会把 flocking 当万能的"群体 AI"——这是误解。Reynolds 自己也说,boids 是 motion 模型,不是 decision 模型。把它和 decision(后面要讲的 squad brain)叠起来用,才是完整的群体 AI。

## 3 · Formation:让群体保持一个形状

### 3.1 从"自由流动"到"维持队形"

flocking 的群体是没有形状的——它会拉伸、撕裂、再合拢,这是它的魅力。但军队不是这样的。一支小队应该保持 wedge(楔形)、line(横线)、column(纵列)这种**预定义形状**,跟着队长整体移动——这是 RTS 单位"群组移动"和军事小队"齐步推进"的核心。这套技术叫 **formation(编队)**。

formation 的核心思想是:**给每个 agent 分配一个 slot(槽位),这个 slot 是相对于"编队中心"的偏移**。agent 的任务从"追玩家"变成"维持自己的 slot 位置"。当整个编队向前移动时,所有 slot 也跟着移动,每个 agent 各自 seek 自己的 slot,群体就维持住了形状。这是一个非常优雅的抽象——它把"群体保持队形"问题,转化成了 N 个独立的"seek 一个目标点"问题。而 seek 是 ai-patterns 里早就写过的、最基础的 steering behavior。**群体行为被分解成了 N 个个体行为**,这是 formation 模型的工程优势。

### 3.2 slot 的定义和编队的形状

```rust
#[derive(Clone, Copy)]
struct Slot { offset: Vec2 } // 相对于 formation 中心的局部坐标偏移

// 横线:每个 slot 在 X 轴上均匀分布
fn formation_line(count: usize, spacing: f32) -> Vec<Slot> {
    (0..count).map(|i| {
        let x = (i as f32 - (count as f32 - 1.0) / 2.0) * spacing;
        Slot { offset: Vec2 { x, y: 0.0 } }
    }).collect()
}

// 楔形(V 字):队首在前,后面左右展开
fn formation_wedge(count: usize, spacing: f32) -> Vec<Slot> {
    (0..count).map(|i| {
        let row = i / 2;
        let side = if i % 2 == 0 { -1.0 } else { 1.0 };
        let depth = if i == 0 { 0.0 } else { 1.0 };
        Slot { offset: Vec2 {
            x: side * ((row as f32 + 1.0) * 0.5) * spacing * depth,
            y: -row as f32 * spacing,
        }}
    }).collect()
}
```

`column` 和 `line` 是镜像(Y 轴上展开),不重复列。**注意一个工程细节**:slot 的 offset 是**局部坐标**(相对于 formation 中心的朝向)。当 formation 旋转时,所有 slot 也跟着转。

### 3.3 formation center 和 slot 的世界坐标

formation 不是一个抽象概念——它有一个**位置**和一个**朝向**,这两者决定每个 slot 在世界坐标里的位置。最朴素的做法是用"队长(leader)"作为 formation center——队长在哪,队形中心就在哪;队长朝哪,队形就朝哪:

```rust
struct Formation {
    center_pos: Vec2,  // 通常 = leader.pos
    heading:   f32,    // 弧度,通常 = leader.vel 的方向
    slots:     Vec<Slot>,
}
impl Formation {
    // 把局部 slot offset 旋转 + 平移到世界坐标
    fn slot_world_pos(&self, i: usize) -> Vec2 {
        let s = &self.slots[i];
        let (cos, sin) = (self.heading.cos(), self.heading.sin());
        let rotated = Vec2 { x: s.offset.x * cos - s.offset.y * sin,
                             y: s.offset.x * sin + s.offset.y * cos };
        self.center_pos.add(rotated)
    }
}

struct SquadMember { slot_idx: usize, pos: Vec2, vel: Vec2 /* ... */ }

fn update_member(m: &mut SquadMember, f: &Formation, dt: f32) {
    let target = f.slot_world_pos(m.slot_idx);
    let force = target.sub(m.pos).normalize().scale(MAX_SPEED).sub(m.vel).truncate(MAX_FORCE);
    m.vel = m.vel.add(force.scale(dt)).truncate(MAX_SPEED);
    m.pos = m.pos.add(m.vel.scale(dt));
}
```

这就是 formation 的全部核心。**一行 leader 决定整个小队的运动**——leader 走,slots 跟着走,每个 member seek 自己的 slot。

### 3.4 slot 分配的学问:谁站哪

上面假设 `slot_idx` 是固定的。但实际工程里,slot 分配是个有意思的小问题:**当小队刚刚组队时,谁站 0 号、谁站 3 号?** 最简单的做法是按"当前距离"分配——给每个 member 找一个最近的未占用的 slot,这是一个**二分图最小权匹配**问题(assignment problem),用匈牙利算法可以求最优解。但工业里常用更便宜的贪心:把所有 member 按"到最近 slot 的距离"排序,从最远的开始,每个挑当前剩下的最近的 slot。这个贪心不保证最优,但通常足够好:

```rust
fn assign_slots(members: &mut [SquadMember], f: &Formation) {
    let mut unassigned: Vec<usize> = (0..members.len()).collect();
    let mut taken = vec![false; f.slots.len()];
    while !unassigned.is_empty() {
        // 找"最急迫"的 member——它到最近可用 slot 的距离最大,优先给它分
        let (mi, slot) = unassigned.iter()
            .map(|&mi| {
                let best = (0..f.slots.len()).filter(|&si| !taken[si])
                    .map(|si| (si, members[mi].pos.sub(f.slot_world_pos(si)).length()))
                    .min_by(|a, b| a.1.partial_cmp(&b.1).unwrap()).unwrap();
                (mi, best.0, best.1)
            })
            .max_by(|a, b| a.2.partial_cmp(&b.2).unwrap())
            .map(|(mi, s, _)| (mi, s)).unwrap();
        members[mi].slot_idx = slot;
        taken[slot] = true;
        unassigned.retain(|&x| x != mi);
    }
}
```

**为什么先给"最远"的 member 分配?** 因为如果一个 member 已经离某个 slot 很近,它去哪个 slot 都行,弹性大;而最远的 member 选项最少,优先满足它,避免它最后被迫绕一个大圈。这是经典的"最受限者优先(least flexible first)"启发式,在调度和 constraint solving 里反复出现。

### 3.5 rigid 和 soft 两种 formation

到这里你写的 formation 是 **rigid(刚性)** 的——slots 相对 center 严格固定,小队像一个刚体。这种在 RTS 里很常见(《星际》的人族机枪兵群组保持一个圆)。但 rigid 有个问题:小队转弯时,外侧的 member 要跑很长一段距离才能跟上,看起来僵硬。**soft(柔性)formation** 是另一种选择——slots 不严格固定,而是有"软约束":member 会朝自己的 slot 走,但允许偏离,偏离越大吸引力越大。这种 formation 转弯时,外侧 member 会"抄近路"切内圈,看起来更自然:

```rust
// soft 版本:slot 力随距离衰减,允许偏离
fn soft_slot_force(m: &SquadMember, f: &Formation) -> Vec2 {
    let target = f.slot_world_pos(m.slot_idx);
    let to_target = target.sub(m.pos);
    let d = to_target.length();
    let strength = (d / SLOT_SOFT_RADIUS).min(1.0) * MAX_SPEED;
    to_target.normalize().scale(strength).sub(m.vel).truncate(MAX_FORCE)
}
```

把 soft slot force 加到 boid 的 flocking 力里(separation + 一个朝 slot 的软拉),就是 RTS 单位群组移动的常见配方。很多 modern RTS 用 soft 版本。

## 4 · Squad Tactics:从队形到协同战斗

### 4.1 formation 解决的是"走",没解决"打"

现在你的小队能保持 wedge 形状齐步走了。但战斗一开,问题立刻来了:五个人保持 wedge 全部朝玩家开枪,这跟"五个人排成一排送死"没区别。真正的战术小队要分工——**有人压制(suppress)、有人包抄(flank)、有人掩护撤退、有人 reload 时让队友顶上**。formation 解决的是"小队怎么走",squad tactics 解决的是"小队怎么打"。这是群体 AI 里最难、也最有意思的部分。

squad tactics 的核心是引入一个 **squad-level 大脑(squad brain / squad commander)**——一个不在场景里出现、但管理整个小队的决策器。它给每个成员分配**角色(role)**:你是 suppressor、你是 flanker、你是 rearguard。每个角色对应一组不同的行为(suppressor 朝玩家方向持续开火制造压力,不必瞄准;flanker 绕到玩家侧后方攻击)。

### 4.2 角色:role 是行为的"模板"

```rust
#[derive(Clone, Copy, PartialEq)]
enum SquadRole {
    Suppress,    // 压制:朝玩家方向持续射击,不必命中,让玩家不敢探头
    Flank,       // 包抄:绕到玩家侧翼或后方
    Pin,         // 牵制:守在玩家可能的撤退路线上
    Rearguard,   // 后卫:警戒小队后方
    ReloadCover, // 正在 reload,退到掩体后
}
struct SquadMember { role: SquadRole, slot_idx: usize, pos: Vec2, vel: Vec2 /* ammo, health ... */ }

// 每个 role 对应一段 steering + attack 行为。下面把"压制"和"包抄"两段写完整——
// 它们最能体现"role 是行为模板"这件事。其余 role 思路类似(Pin 蹲守玩家撤退路线上;
// Rearguard 缓慢跟随小队后方;ReloadCover seek 最近掩体)。
fn update_member_by_role(m: &mut SquadMember, ctx: &SquadContext, dt: f32) {
    match m.role {
        SquadRole::Suppress => {
            // 不追求命中,追求火力压制。通常不动,守一个位置。
            m.vel = Vec2::ZERO;
            let dir = ctx.player_pos.sub(m.pos).normalize();
            m.fire_toward(ctx.player_pos.add(dir.scale(50.0))); // 故意打偏一点
        }
        SquadRole::Flank => {
            // 绕到玩家侧翼:沿"玩家朝向的垂直方向"移动
            let to_player = ctx.player_pos.sub(m.pos).normalize();
            let flank_dir = Vec2 { x: -to_player.y, y: to_player.x }; // 90 度旋转
            let target = ctx.player_pos.add(flank_dir.scale(80.0));
            m.pos = seek_and_step(m.pos, m.vel, target, MAX_SPEED, dt);
            if m.pos.sub(target).length() < 20.0 { m.role = SquadRole::Suppress; } // 到位切换
        }
        // Pin / Rearguard / ReloadCover:都是"seek 一个 role-specific 目标点",
        // 区别只是 target 怎么算。这里略,模式跟 Flank 一致。
        _ => { /* 见练习 Lv4:完整实现 */ }
    }
}
// 复用的 seek-and-integrate:把 seek 力转成速度和位置更新
fn seek_and_step(pos: Vec2, vel: Vec2, target: Vec2, max_speed: f32, dt: f32) -> Vec2 {
    let force = target.sub(pos).normalize().scale(max_speed).sub(vel).truncate(MAX_FORCE);
    let new_vel = vel.add(force.scale(dt)).truncate(max_speed);
    pos.add(new_vel.scale(dt))
}
```

注意这套代码本身并不复杂——复杂的是**谁、什么时候、分配什么 role**。这就回到 squad brain。

### 4.3 squad brain:小队的"指挥官"

squad brain 是一个独立的 entity,它不渲染、不碰撞,只负责**根据小队和玩家的当前态势,分配 role 给每个成员**。它的 tick 大概长这样:

```rust
struct Squad {
    members: Vec<SquadMember>,
    target: Option<Vec2>,
    last_role_assign_time: f32,
}
impl Squad {
    fn tick(&mut self, now: f32, dt: f32) {
        self.last_role_assign_time += dt;
        if self.last_role_assign_time < 2.0 { return; }  // 2 秒一次,减少抖动 + 省 CPU
        self.last_role_assign_time = 0.0;
        let Some(player_pos) = self.target else { return; };
        let alive: Vec<usize> = (0..self.members.len())
            .filter(|&i| self.members[i].health > 0.0).collect();
        if alive.is_empty() { return; }
        for &i in &alive { self.members[i].role = SquadRole::Suppress; } // 默认全压制

        // 挑 flanker:挑"已经在玩家侧面方向"的成员(它们移动距离短,能更快就位)
        let mut by_flank: Vec<usize> = alive.clone();
        by_flank.sort_by(|&a, &b| flank_score(&self.members[b], player_pos)
            .partial_cmp(&flank_score(&self.members[a], player_pos)).unwrap());
        self.members[by_flank[0]].role = SquadRole::Flank;
        if alive.len() >= 4 { self.members[by_flank[1]].role = SquadRole::Flank; }

        // 挑 rearguard:血量最低的退后方
        if alive.len() >= 3 {
            let rg = *alive.iter().min_by(|&&a, &&b|
                self.members[a].health.partial_cmp(&self.members[b].health).unwrap()).unwrap();
            self.members[rg].role = SquadRole::Rearguard;
        }
    }
}
// flank_score:已经在侧面的成员更适合当 flanker
fn flank_score(m: &SquadMember, player_pos: Vec2) -> f32 {
    let to_player = player_pos.sub(m.pos);
    let dist = to_player.length().max(1.0);
    let lateral = 1.0 - (to_player.x / dist).abs();   // |cos θ| 越小越在侧面
    let proximity = 1.0 / (dist / 200.0 + 1.0);        // 距离玩家不太远
    lateral * proximity
}
```

这段代码不算长,但它做的事非常重要——**它把"五个 enemy 各自追玩家"换成了"五个有分工的小队成员:两个压制、一个包抄、一个后卫、一个看情况"**。这就是 squad tactics 的核心。**注意一个工程细节**:role 分配不是每帧做,而是 2 秒一次。原因是——如果每帧都重新评估 flank score,成员会在 flank 和 suppress 之间疯狂切换(两个 member 的 flank score 几乎相等,谁先谁后取决于浮点噪声),看起来像抽搐。这种"决策不要做太频繁"的频率控制,在 ai-perception-and-memory 里也会专门讲(perception tick 频率),是 AI 工程的通用智慧。

### 4.4 共享感知:小队作为一个有机体

squad tactics 还有一个常被忽略但极其关键的部分:**成员之间要共享感知(share perception)**。一只 enemy 看到玩家从左边溜过去,如果它是孤狼,这条信息只对它自己有用;如果它在 squad 里,这条信息应该**立刻广播给所有队友**,否则左边的 flanker 还在守一个 5 秒前看到的位置,而玩家早跑了。

这就是为什么这一篇和 [event-systems-and-gameplay-foundations](event-systems-and-gameplay-foundations.md) 直接相关。每个成员的 perception 系统(ai-perception-and-memory)看到玩家时,不只是更新自己的 `target`,而是往 squad 的 **shared blackboard(共享黑板)** 写一条 `PlayerSpotted { pos, time }` 事件,squad brain 把它综合成"当前对玩家的最新认知",再分发给所有成员:

```rust
struct SquadBlackboard {
    last_known_player_pos: Option<Vec2>,
    last_seen_time: f32,
    alertness: f32, // 0.0 = 平静,1.0 = 完全警觉
}
// 成员的 perception 触发时
fn on_member_spotted_player(squad: &mut Squad, _mi: usize, player_pos: Vec2, now: f32) {
    squad.blackboard.last_known_player_pos = Some(player_pos);
    squad.blackboard.last_seen_time = now;
    squad.blackboard.alertness = 1.0;
    // 没看到玩家的成员会同步通知,他们的 target 也跟着更新
}
```

**这是一个非常深的工程转变**——squad 不再是 N 个独立 AI 的集合,而是一个**有机体**:任何一只的感知立刻成为全队的感知。这也是为什么真实军队训练强调通讯——单兵感知有限,但通讯能让小队的"感知范围"扩大到所有成员视野的并集。F.E.A.R. 的 AI 之所以看起来那么聪明,很大程度不是因为单兵智能高,而是因为他们共享感知、协同行动,把"五只 dumb 但协同的 enemy"演成了"一支聪明的 squad"。

[game-state-management](../../phase-2/deep-dives/game-state-management.md) 里讲的"游戏状态在多个系统间同步"在这里又一次出现——shared blackboard 本质上就是一种小范围的 game state,只是它的 owner 是 squad 而不是整个 world。

## 5 · Command Hierarchy:让大规模战斗变得可管理

### 5.1 一个 commander 管多少个 squad?

到这里你有一个能协同的 squad 了。但大型战斗不是一队 5 人,是 50 人——10 个 squad。如果你只有一个 squad brain 管 50 个人,role 分配会变得极其复杂(50 个角色?哪有那么多角色),而且 50 个人共享一个 blackboard,通讯爆炸。

**Command Hierarchy(指挥层级)** 是答案:你不止有 squad brain,还有一层 **commander(指挥官)** 在 squad brain 之上。commander 不直接管单个 soldier,它管的是 squad:commander 说"squad A 守东门、squad B 进攻西门、squad C 预备队";每个 squad brain 收到指令后,自己决定"我手里这五个人,谁守、谁攻";每个 soldier 只关心"squad 给我的 role 是什么,我执行"。这是经典的**分层控制(hierarchical control)**,真实军队就是这么组织的:班长管 10 人,排长管 3 个班,连长管 3 个排。每一层只和它直接下一层通讯,通讯路径短、决策复杂度可控。

```rust
struct Commander { squads: Vec<Squad>, strategy: Strategy, strategy_timer: f32 }

#[derive(Clone)]
enum Strategy {
    HoldTheLine { sector: Vec2 },
    Assault { target_sector: Vec2 },
    FallingBack { rally_point: Vec2 },
    Sweep { area: Vec2 },
}
#[derive(Clone)]
enum SquadOrder { Attack { target: Vec2 }, Defend { point: Vec2 }, Reserve,
                  Regroup { point: Vec2 }, Search { area: Vec2 } }

impl Commander {
    fn tick(&mut self, world: &World, dt: f32) {
        self.strategy_timer += dt;
        if self.strategy_timer < 5.0 { return; }   // 5 秒一次战略评估
        self.strategy_timer = 0.0;
        self.strategy = self.evaluate_strategy(world);
        for (i, squad) in self.squads.iter_mut().enumerate() {
            squad.order = match (&self.strategy, i) {
                (Strategy::Assault { target_sector }, _) =>
                    SquadOrder::Attack { target: *target_sector },
                (Strategy::HoldTheLine { sector }, 0 | 1) =>
                    SquadOrder::Defend { point: *sector },
                (Strategy::HoldTheLine { .. }, _) => SquadOrder::Reserve,
                (Strategy::FallingBack { rally_point }, _) =>
                    SquadOrder::Regroup { point: *rally_point },
                (Strategy::Sweep { area }, _) => SquadOrder::Search { area: *area },
            };
        }
    }
    fn evaluate_strategy(&self, world: &World) -> Strategy {
        // 简化:看双方总血量比
        let our_hp: f32 = self.squads.iter().flat_map(|s| s.members.iter())
            .map(|m| m.health).sum();
        if our_hp < world.enemy_total_hp * 0.5 {
            return Strategy::FallingBack { rally_point: world.our_spawn };
        }
        if let Some(threat) = world.main_threat_sector {
            return Strategy::Assault { target_sector: threat };
        }
        Strategy::HoldTheLine { sector: world.center }
    }
}
```

commander 的关键设计:**它的工作是给 squad 分配"战略意图",而不是给 soldier 分配"战术动作"**。战略意图粗粒度(攻击、防御、撤退、搜索),战术动作(suppress、flank、reload)是 squad brain 自己决定的。这种"上一级管意图、下一级管执行"的分工,正是层次化 AI 的精髓,也是为什么指挥层级能 scale——你把复杂度分散到不同层,每一层都不需要太聪明。

### 5.2 hierarchical AI 的 scale 优势

来算笔账。假设你有 50 个 enemy,战场是攻城战。**如果不分层**(50 个独立 AI):每个 enemy 自己决策(我在哪、玩家在哪、我该干嘛),每个 enemy 还要感知周围其他 49 个 enemy 的状态来避免冲突——决策复杂度 O(N²),感知复杂度 O(N²),50 人就是 2500 次 pairwise 检查。**如果分两层**(10 个 squad × 5 人,加一个 commander):commander 做一次战略评估(10 个 squad 的状态),每个 squad brain 做一次战术评估(5 个成员的状态),每个 member 做一次个体执行(只看自己 + squad blackboard)。总复杂度大约是 O(N) 个体 + O(N/5) squad + O(1) commander。**层级化把 O(N²) 拆成了 O(N)**。

这是为什么 AAA 大型战斗 AI 几乎都用 hierarchical 结构。Halo 的 marines、《战地》的 bot、Total War 的几千人军队——都是某种形式的层级 AI。Millington 在《AI for Games》专门有一章 "Hierarchical Game AI" 讲这个 pattern。

### 5.3 失效模式:当指挥链断了

hierarchical AI 有一个真实军队也有的问题:**指挥链一旦断裂,下属就瘫痪**。commander 挂了,squad 收不到指令,就开始 idle 或随机乱走;squad leader 挂了,成员失去 role,退化成 dumb 单兵。工程上的处理:**每一层都应该有一个 fallback 行为(fallback behavior)**。commander 通讯中断时,squad 应该按上一次收到的指令继续行动一段时间,然后退到自己的默认行为(比如"搜索并攻击");squad 失去 blackboard 时,member 应该退化成独立的 dumb AI(就是你在 ai-patterns 里最早写的那种 FSM)。这种"层级降级"的设计,让 AI 看起来"在压力下还能撑住",而不是一断线就全员死机。这其实和 [event-systems-and-gameplay-foundations](event-systems-and-gameplay-foundations.md) 里讲的"事件系统要能容忍订阅者缺失"是一个道理——**任何中心化的设计,都必须想清楚中心失效时怎么办**。

## 6 · 协调的代价 vs 收益:生产现实

### 6.1 squad tactics 是贵的

讲到这里你可能已经闻到味道了:**squad brain + 共享感知 + role 分配 + blackboard 通讯,这套东西不便宜**。每个 squad 每 2 秒做一次 role 分配(O(N²) 的成员配对评估),每帧每个成员都要查 blackboard、广播感知事件,commander 每 5 秒做一次战略评估还要遍历所有 squad……一个 5 人 squad 的 CPU 成本可能抵得上 30 只 dumb enemy。

Millington 在书的"Performance Considerations"小节里很直白:rich squad behavior is expensive, and you should spend it deliberately。意思是——别一股脑给所有 enemy 都上 squad AI,**给那些"玩家会注意到协同"的 enemy 上**。一只杂兵死活玩家不关心,dumb 就好;一支精英小队、一场 boss 战的副官群、玩家会反复交手的对手——这些才值得花 CPU 做协调。

### 6.2 "几个聪明的 vs 一群 dumb"的感知经济学

这是游戏 AI 的一个反直觉但很重要的洞察,最早由 Halo 的 AI 工程师 Damian Isbell 提出:**玩家对"群体智能"的感知,主要来自少数几个显著的个体表现,而不是整体的统计**。意思是:你做 30 只 dumb 敌人,玩家觉得"这是一群蠢货";你做 5 只协调良好的敌人,1 只从侧翼绕过来打中玩家、1 只在 reload 时退到掩体、3 只持续压制——玩家会觉得"卧槽这群人真聪明"。**5 只协调的敌人给玩家的"AI 智能"印象,远大于 30 只 dumb 的**。

这是因为人类对"故事性的事件"敏感,对"统计平均"麻木。一只敌人 flank 你打中你,这是一个故事;30 只敌人朝你跑,这是噪音。所以——**生产里,花 CPU 做少数 enemy 的协调,比堆 dumb enemy 数量更有性价比**。这是为什么 F.E.A.R. 一场战斗通常只有 4-6 个 soldier,但每个都让你觉得"这帮人真难缠"。

### 6.3 动态难度和 squad 协调

进一步,你可以把 squad 的"协调程度"当作动态难度(dynamic difficulty)的旋钮——这是 ai-debugging-and-tuning 那一篇的主题,这里先点一下。玩家打得顺,squad brain 启用所有 role(suppress + flank + pin),开始上压力;玩家死了几次,squad brain 暂时只允许 suppress,关掉 flank,让玩家喘口气。**协调度本身是一个可调的难度参数**,而且比"调 enemy 血量"或"调 enemy 伤害"更隐蔽——玩家不会察觉 enemy 变笨了,只会觉得"运气好一点"。这是高档动态难度的做法。

## 7 · 在你 HH 项目里动手(做中学红线)

讲了一堆,现在到落地。这一节的"做中学红线"分两个阶段——**先做 flocking(纯涌现),再做 squad(显式协调)**。两步都做完,你 HH 项目里的 enemy 群体就会从"一团乱"进化成"一支小队"。

### 7.1 第一步:做一个 flocking 演示(纯涌现,建立直觉)

先不要碰你的 enemy。开一个新的 entity 类型——一群鸟、一群鱼、一群粒子,什么都行,只要它们能移动。给它们全部加上 `Boid` 组件,跑 2.2 的 `flocking` 函数。观察:调一调 `W_SEPARATION` / `W_ALIGNMENT` / `W_COHESION` 这三个数。让群体从屏幕一边飞到另一边。**这是红线,你必须做这一步**——因为只有亲手调过这三权重,你才会对"涌现"有体感,才能在后面 squad AI 里判断"这个运动该用涌现还是显式"。调到群体"看起来像一群"为止。然后把 `W_COHESION` 调到 0,看群体散开;调到 5,看群体黏成一坨。这种实验是 flocking 学习的核心。

### 7.2 第二步:加空间划分,flocking 撑到上千只

当你 flocking 跑 200 只 boid 时,tracy 里大概率看到 `flocking` 这个函数吃掉一坨帧时间。这就是 2.4 节讲的 O(N²)。把 `SpatialGrid` 那段代码加进去,`cell_size = VIEW_RADIUS`。再看 tracy——帧时间应该明显下降。**这一步也是红线**——它教会你"看起来简单的群体行为背后是什么性能代价"。任何你想做大规模群体(bird、fish、crowd、丧尸潮)的项目,这一步逃不掉。

### 7.3 第三步:做一个 3-4 人的 enemy squad(显式协调)

现在动你的 enemy。挑出 3-4 只,做成一个 `Squad`。先做最简单的——给它们一个 `formation_wedge`,加 leader(让 leader 直接 seek 玩家),其他成员按 3.3 的方法 seek 自己的 slot world position。跑起来,看它们能不能维持楔形追玩家。**红线检查**:在门洞处,leader 应该会卡(因为还是 dumb seek),但其他成员应该保持楔形而不是叠成一团。如果还是叠了,检查 `slot_world_pos` 算对了没——slot 的世界位置必须随 leader 旋转。

### 7.4 第四步:加 role 分配(真正的 squad tactics)

加上 4.2 的 `SquadRole` 和 4.3 的 `squad brain`。开始时只放两个 role:`Suppress` 和 `Flank`。让 squad brain 每 2 秒重新分配 role,挑两个成员当 suppressor(原地不动朝玩家方向开火),一个当 flanker(绕侧翼)。**红线检查**:玩家站在原地不动,squad 应该有 2 只原地开火、1 只从侧面绕过来。玩家转头打 flanker,suppressor 继续开火压制(因为它们的 role 没变);玩家转头打 suppressor,flanker 继续绕(直到 2 秒后 squad brain 重新评估)。这一步是"群体 AI 是另一门学问"的实感时刻——你会发现让 4 只 enemy 协同,比让 1 只 enemy 变聪明难得多。

### 7.5 第五步:加 shared blackboard(共享感知)

加上 4.4 的 `SquadBlackboard`。让任何一只 member 的 perception 系统(就是 ai-perception-and-memory 那一篇写的)看到玩家时,更新 blackboard 的 `last_known_player_pos` 和 `last_seen_time`。所有成员的 target 不再各自计算,而是从 blackboard 读。**红线检查**:玩家躲到墙后,只有 flanker 因为绕侧面能看到玩家。flanker 一看到玩家,2 个 suppressor 应该立刻转头朝那个方向开火——尽管它们自己视野里根本没玩家。这就是"协同感知",是 squad 战术的灵魂。

### 7.6 第六步(可选):加 commander,做两支 squad 对战

如果你还精力饱满,做两个 squad,加一个 commander,让它们分守两个门、或一攻一守。这是 command hierarchy 的实感。这一步不做也不影响主线,但做完你会理解为什么 AAA 战斗 AI 都用层级结构。

## 8 · 练习

### 8.1 Lv1 · 调权重的手感

跑 flocking 演示,三个练习:找一组权重让群体像"鸟"(轻盈、容易分裂再合拢);找一组权重让群体像"鱼群"(稠密、整体感强);找一组权重让群体像"丧尸潮"(沉重、撕裂后不容易合拢)。把三组权重记下来,你以后做任何群体运动都要复用这套调参经验。

### 8.2 Lv2 · obstacle avoidance

flocking 现在不会避障——撞墙就穿过去。给 boid 加第四条规则:**obstacle avoidance**——前方一定距离内有障碍物时,产生一个垂直方向的避让力。提示:可以用 raycast 探前方,有 hit 就朝 hit normal 的垂直方向加力。这会让你理解 Reynolds 原论文里"为什么有时候要加第四第五条规则"——基础三条只解决"群体内"的协调,加更多规则是为了和"群体外"的环境交互。

### 8.3 Lv3 · 动态编队切换

实现 squad 能在 wedge、line、column 三种编队间动态切换。指挥官下发"切换到 wedge",slots 重新计算,成员平滑过渡到新 slot(不是瞬移,而是 seek 新位置)。难点是过渡的平滑——切编队时,所有成员会同时朝新位置冲,可能互相穿插,看起来乱。挑战:用 soft formation 让过渡更自然。

### 8.4 Lv4 · 完整的 F.E.A.R. 风格 squad

完整实现一个 4 人 squad,role 集合包括 Suppress / Flank / Pin / ReloadCover / Rearguard。要求:共享感知(blackboard);role 动态分配,每 2 秒评估一次,考虑成员血量、弹药、距玩家距离;至少 2 个 suppressor、1 个 flanker、1 个 rearguard;reload 时成员自动切到 ReloadCover,退到最近掩体;reload 完回归原 role;在 tracy 里 profile,squad brain 这部分的 CPU 占比应低于 5%。做完这个,你就拿到了工业级 squad AI 的入门证书。F.E.A.R. 的实际 squad AI 比这个更复杂(用 GOAP 做战术决策),但骨架是一样的。

## 9 · 延伸阅读与下一篇

这一篇是群体 AI 的主干,但还有几条岔路值得深挖。

**Reynolds 的原始论文与网站**:https://www.red3d.com/cwr/steer/ —— 不仅是 flocking,Reynolds 把所有 steering behaviors(seek / flee / arrival / pursuit / wander / obstacle avoidance / leader following)都列在这里,带 Java applet 演示。这是任何做游戏 AI 的人的必读书。

**Millington《AI for Games》第三版**第三部分:八十页专讲 group movement 和 group behaviors,包括我们这里没展开的 **flocking with leadership**(领头鸟机制)、**formation patterns 的更多变种**、**emergent formations**(没有显式 slot 但群体自发形成形状)。这是我们这一篇的"完整版"。

**FEAR AI 论文**(免费 PDF):https://cdn.cloudflare.steamstatic.com/apps/valve/2015/Ors_LeClerc_FEAR_AI.pdf —— Jeff Orkin 讲 F.E.A.R. 的 squad AI 怎么做出来的,核心是用 GOAP 做战术决策(我们这里简化成 role enum,工业级会更有意思)。

**Halo 2 的 AI GDC talk**:Damian Isbell 的 "AI in Halo 2: The Behavior Tree Era"——Halo 的 marine squad 协调是群体 AI 的里程碑,Isbell 讲了他们怎么用 BT + shared blackboard 实现 squad behavior,以及为什么"少数协调的敌人比大量 dumb 敌人更有效"。

**Left 4 Dead 的 AI Director**:GDC 2008 的 talk——L4D 没用传统 squad AI,而是用 AI Director 在更高层级决定"什么时候、什么地点、出多少 zombie",这是 command hierarchy 的极端形态(Director 直接管理 spawn 节奏,而不是 squad 内的 role)。如果你对动态难度感兴趣,这个必看。

**与你 HH 项目其他模块的关系**:[ai-patterns](../../phase-2/deep-dives/ai-patterns.md) 给了 steering behaviors 和 FSM/BT/GOAP 的基础,本篇假设你已经读完;ai-perception-and-memory 讲单兵怎么看,这一篇讲看了之后怎么 share;[navmesh-and-pathfinding](../../phase-7/deep-dives/navmesh-and-pathfinding.md) 给 formation 移动和 flanker 包抄的寻路;[event-systems-and-gameplay-foundations](event-systems-and-gameplay-foundations.md) 里 shared blackboard 本质上就是一个 event bus;[game-state-management](../../phase-2/deep-dives/game-state-management.md) 里 squad blackboard 是一种局部 game state;[spatial-acceleration](../../phase-6/deep-dives/spatial-acceleration.md) 是 flocking 的 O(N²) 解法。

**下一篇 → ai-debugging-and-tuning**:这一篇的 squad AI 写完了,但你一定会遇到"为什么这个 squad 不按我设计的来"——role 抖动、blackboard 同步 bug、formation 散架、性能超标。下一篇专讲 AI 的调试与调参——AI log、可视化 inspector、replay、tuning pipeline、以及怎么在 tracy 里 profile AI 系统。这是把"能跑的 AI"变成"量产的 AI"的最后一公里。
