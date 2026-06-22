---
phase: 2
title_en: "AI Patterns Deep Dive"
title_zh: "AI 模式深度专题"
type: deep-dive
domains: [game, rust, cs]
---

# AI 模式深度专题

> 你跟着 HH Day 130 写完了怪物 AI。怪物有两种状态:"巡逻"和"追击",用 `enum BrainState { Patrol, Chase }` 加一个 `match` 实现。看起来够用了。但你心痒:你的 RPG 里 NPC 越来越多,从 5 个涨到 50 个。`match` 越来越长——巡逻 NPC 要不要走到声音源?NPC 看到玩家要不要先评估威胁再决定追或逃?多种行为同时被触发时谁优先?你开始把 `match` 改写成嵌套 if/else,代码迅速腐烂。今天这一篇,我们把游戏 AI 的所有主流模式拆开——从最简单的 state machine 到最复杂的 GOAP / HTN——告诉你每种适合什么场景,以及在 Rust 里怎么落地。

## 0 · 为什么要有这一篇

游戏 AI 不是学术 AI。游戏 AI 不需要"真的智能",它需要**看起来智能 + 工程可控 + 性能可控**。Handmade Hero 里 Casey 用了 15 集涉及 AI:Brain state machine、路径寻找、感知(perception)、决策频率。这些技术不是孤立的——它们组成一个"AI 工具箱",根据 NPC 复杂度选合适的工具。

**AI 模式按复杂度递增**:

1. **Hardcoded / Scripted AI**(1970s):if-else 写死,Space Invaders。
2. **Finite State Machine (FSM)**(1980s):Pac-Man 的幽灵、Mario 的敌人。
3. **Hierarchical FSM (HFSM)**(1990s):分层的 FSM,Quake 的 bot。
4. **Behavior Tree**(2000s):Halo 2 引入,今天 AAA 的标配。
5. **Utility AI**(2005+):The Sims 用,基于"评分选最优行为"。
6. **GOAP**(2006,F.E.A.R.):目标导向,规划一系列动作达到目标。
7. **HTN**(2010+,Transformer / Ghost Recon):层次化任务网络,设计师指定任务分解。
8. **MCTS / Reinforcement Learning**(2015+):AlphaGo 风格,棋牌游戏 / 训练 NPC。

每个层次解决前一层的痛点。Casey 在 HH 里只用到 FSM,但工业级游戏 AI 工具箱需要全部。

**这一篇要回答**:
- FSM / HFSM / Behavior Tree / Utility AI / GOAP / HTN 各自的优缺点
- Steering behaviors(seek / flee / wander / flock)——群体 AI 的基础
- Pathfinding: BFS / DFS / Dijkstra / A*
- ECS 怎么和 AI 结合(bevy_atb / bigbrain crate)
- Rust 里如何高效实现每个模式

**学完这一篇,你应该能**:
- 选择正确的 AI 模式(避免"用 GOAP 杀鸡")
- 用 Rust 实现一个 behavior tree
- 解释 A* 和 Dijkstra 的精确差别
- 在 Bevy 里用 bigbrain crate 集成 utility AI
- 调试 AI("为什么 NPC 卡在墙边?")的思路

## 1 · Finite State Machine(FSM)

### 1.1 模型

最简单的 AI 模型。NPC 在有限的状态集合里切换,每个状态对应一种行为。

```
状态集 S = { Patrol, Chase, Attack, Flee }
转移函数 δ: S × Event → S
δ(Patrol, SeePlayer) = Chase
δ(Chase, LostPlayer) = Patrol
δ(Chase, InRange) = Attack
δ(Attack, LowHealth) = Flee
```

Casey 在 HH Day 130 用 Rust enum + match 实现这个:

```rust
#[derive(Clone, Copy, PartialEq)]
enum BrainState {
    Patrol,
    Chase,
    Attack,
    Flee,
}

struct Npc {
    state: BrainState,
    health: f32,
    target_pos: Option<Vec2>,
    // ...
}

fn update_npc(npc: &mut Npc, world: &World, dt: f32) {
    match npc.state {
        BrainState::Patrol => {
            patrol_behavior(npc, world, dt);
            // 检查转移条件
            if let Some(target) = see_player(npc, world) {
                npc.target_pos = Some(target);
                npc.state = BrainState::Chase;
            }
        }
        BrainState::Chase => {
            chase_behavior(npc, world, dt);
            if !can_see_player(npc, world) {
                npc.target_pos = None;
                npc.state = BrainState::Patrol;
            } else if dist_to_player(npc, world) < ATTACK_RANGE {
                npc.state = BrainState::Attack;
            }
        }
        BrainState::Attack => {
            attack_behavior(npc, world);
            if npc.health < 30.0 {
                npc.state = BrainState::Flee;
            }
        }
        BrainState::Flee => {
            flee_behavior(npc, world, dt);
            if npc.health > 70.0 {
                npc.state = BrainState::Patrol;
            }
        }
    }
}
```

**优点**:简单、调试容易、性能可预测。
**缺点**:状态多时转移组合爆炸。N 个状态 × M 个事件 = N·M 个转移。N=20 时 400 条转移,代码爆炸。

### 1.2 推动状态机的核心问题:状态爆炸

考虑一个稍微复杂的 NPC:
- 巡逻 / 追击 / 攻击 / 逃跑 / 搜索 / 警觉 / 死亡 / 眩晕(7 个主要状态)
- 看到玩家 / 听到声音 / 受击 / 玩家离开视野 / 健康低 / 眩晕结束(6 个事件)

7 × 6 = 42 条转移。每条都是手写 if。这种规模勉强能维护,但加一个状态(比如"睡觉")就要加 6 条转移。

**Hierarchical FSM(HFSM)** 解决这个:把状态分组。比如"Combat"父状态包含 "Chase / Attack / Flee"子状态。父状态的转移(比如"被击晕"→"眩晕")适用于所有子状态,不用每条写一遍。

```rust
enum HState {
    Combat(CombatState),
    Patrol(PatrolState),
    Stunned,
    Dead,
}

enum CombatState { Chase, Attack, Flee }
enum PatrolState { Wander, Investigate }

fn update(npc: &mut Npc, world: &World, dt: f32) {
    // 先处理全局转移(父级)
    if npc.health <= 0.0 {
        npc.state = HState::Dead;
        return;
    }
    if npc.stun_timer > 0.0 {
        npc.state = HState::Stunned;
        npc.stun_timer -= dt;
        return;
    }

    // 再处理当前状态
    match &mut npc.state {
        HState::Combat(cs) => update_combat(npc, cs, world, dt),
        HState::Patrol(ps) => update_patrol(npc, ps, world, dt),
        HState::Stunned => { /* 无行为 */ }
        HState::Dead => { /* 无行为 */ }
    }
}
```

## 2 · Behavior Tree(BT)

### 2.1 模型

Behavior Tree 是 Halo 2 引入的工业级 AI 设计。它用树状结构组织行为,避免 FSM 的状态爆炸。

BT 的核心节点类型:

- **Action**:做一件事(攻击、移动)。返回 Success / Failure / Running。
- **Condition**:判断条件(血量 < 30%?)。返回 Success / Failure。
- **Sequence**:依次执行子节点,**任一失败则失败**。AND 语义。
- **Selector**(Fallback):依次执行子节点,**任一成功则成功**。OR 语义。
- **Decorator**:修饰子节点(Invert / Retry / Repeat)。
- **Parallel**:并行执行多个子节点。

### 2.2 Rust 实现

```rust
enum NodeStatus { Success, Failure, Running }

trait Node {
    fn tick(&mut self, ctx: &mut NpcCtx) -> NodeStatus;
}

// Action 节点:闭包
struct Action<F: FnMut(&mut NpcCtx) -> NodeStatus>(F);
impl<F> Node for Action<F> where F: FnMut(&mut NpcCtx) -> NodeStatus {
    fn tick(&mut self, c: &mut NpcCtx) -> NodeStatus { (self.0)(c) }
}

// Sequence:依次执行,任一失败就停
struct Sequence { children: Vec<Box<dyn Node>>, current: usize }
impl Node for Sequence {
    fn tick(&mut self, c: &mut NpcCtx) -> NodeStatus {
        while self.current < self.children.len() {
            let status = self.children[self.current].tick(c);
            match status {
                NodeStatus::Success => self.current += 1,
                NodeStatus::Failure => {
                    self.current = 0;  // 重置
                    return NodeStatus::Failure;
                }
                NodeStatus::Running => return NodeStatus::Running,
            }
        }
        self.current = 0;
        NodeStatus::Success
    }
}

// Selector:依次执行,任一成功就停
struct Selector { children: Vec<Box<dyn Node>>, current: usize }
impl Node for Selector {
    fn tick(&mut self, c: &mut NpcCtx) -> NodeStatus {
        while self.current < self.children.len() {
            let status = self.children[self.current].tick(c);
            match status {
                NodeStatus::Failure => self.current += 1,
                NodeStatus::Success => {
                    self.current = 0;
                    return NodeStatus::Success;
                }
                NodeStatus::Running => return NodeStatus::Running,
            }
        }
        self.current = 0;
        NodeStatus::Failure
    }
}
```

构造一个 BT:

```rust
// NPC 行为:
// 优先级:1) 满血时追击玩家
//         2) 血量低时逃跑
//         3) 没看见玩家时巡逻
let tree = Selector {
    children: vec![
        Box::new(Sequence {
            children: vec![
                Box::new(Action(|c| if c.health > 30.0 { Success } else { Failure })),
                Box::new(Action(|c| { chase_player(c); Running })),
            ],
            current: 0,
        }),
        Box::new(Sequence {
            children: vec![
                Box::new(Action(|c| if c.health <= 30.0 { Success } else { Failure })),
                Box::new(Action(|c| { flee(c); Running })),
            ],
            current: 0,
        }),
        Box::new(Action(|c| { patrol(c); Running })),
    ],
    current: 0,
};
```

每帧 `tree.tick(&mut ctx)`。BT 自动按优先级选择行为。

**优点**:
- 模块化(每个节点独立)
- 复用(同一节点可以在多个树里用)
- 可视化(图形编辑器能直接画)
- 易扩展(加新行为 = 加新节点)

**缺点**:
- 节点状态需要管理(running state)
- 性能(virtual call 比 match 慢)
- 不善于"长期规划"(每次 tick 都是从根开始选)

工业 BT 库:Rust 的 `bevy-behavior-tree`,UE 的 Behavior Tree。

## 3 · Utility AI

### 3.1 模型

Utility AI 来自 The Sims(2000 年)。它的思路:**给每个行为打分,选分数最高的执行**。

每个行为有一个或多个 "consideration"(考虑因素),每个 consideration 是一个函数,把世界状态映射到 [0, 1] 分数。所有 consideration 的分数通过某种方式(乘积 / 平均)组合成行为的 utility。

```rust
struct Behavior {
    name: &'static str,
    considerations: Vec<Box<dyn Fn(&NpcCtx) -> f32>>,
    action: Box<dyn Fn(&mut NpcCtx)>,
}

fn pick_behavior(behaviors: &[Behavior], ctx: &NpcCtx) -> Option<&Behavior> {
    behaviors.iter()
        .map(|b| (b, b.considerations.iter().map(|c| c(ctx)).product::<f32>()))
        .max_by(|a, b| a.1.partial_cmp(&b.1).unwrap())
        .map(|(b, _)| b)
}
```

例子:NPC 是否攻击?

```rust
let attack = Behavior {
    name: "attack",
    considerations: vec![
        Box::new(|c| 1.0 - c.health / 100.0),        // 血量越低越想攻击(背水一战)
        Box::new(|c| 1.0 - c.target_dist / 100.0),    // 离玩家越近越想攻击
        Box::new(|c| if c.has_ammo { 1.0 } else { 0.0 }),
    ],
    action: Box::new(|c| do_attack(c)),
};
```

3 个 consideration 分数相乘,得到 attack 的总 utility。同样算 flee、patrol、investigate 的 utility,选最高。

**优点**:
- 自然地表达"权衡"(血量低 + 距离远 = 逃跑,血量低 + 距离近 = 拼命)。
- 不需要明确状态切换。
- 加新行为 = 加新 Behavior + 评分函数。

**缺点**:
- 调试难(为什么 NPC 选了 A 不选 B?分数差异极小)。
- 平衡难(每个 consideration 函数都要手调)。
- 容易出现"乒乓":两个分数相近,每帧切来切去。解法:加 hysteresis(滞后阈值)。

工业库:Rust 的 `bigbrain`(Bevy 插件)、Dave Mark 的 IUtility AI 库。

## 4 · GOAP(Goal-Oriented Action Planning)

### 4.1 模型

GOAP 来自 F.E.A.R.(2006)。思路:**给 AI 一个目标(杀玩家),让 AI 自己规划一系列动作达成目标**。

形式化:A* 搜索,但搜索空间不是物理位置,而是**世界状态**。

世界状态:一组 key-value,比如:
- `player_alive: true`
- `has_weapon: true`
- `weapon_loaded: false`
- `near_player: false`

每个动作有:
- **precondition**:执行前必须满足(`has_weapon == true && near_player == true`)
- **effect**:执行后改变状态(`weapon_loaded := false, player_alive := false`)
- **cost**:代价

GOAP 用 A* 在"状态空间"搜索:从当前状态到目标状态(比如 `player_alive == false`)的最便宜动作序列。

### 4.2 Rust 实现(简化)

```rust
use std::collections::HashMap;

type WorldState = HashMap<String, bool>;

#[derive(Clone)]
struct Action {
    name: &'static str,
    precondition: WorldState,
    effect: WorldState,
    cost: f32,
}

fn goap(start: WorldState, goal: WorldState, actions: &[Action]) -> Option<Vec<Action>> {
    // A* search
    // 节点 = WorldState + 已执行动作列表
    // h = 未满足的 goal 个数
    // ...
    // 简化,真实实现需要 priority queue
    unimplemented!()
}

fn main() {
    let actions = vec![
        Action {
            name: "pickup_weapon",
            precondition: [("has_weapon", false)].into(),
            effect: [("has_weapon", true)].into(),
            cost: 5.0,
        },
        Action {
            name: "reload",
            precondition: [("has_weapon", true), ("weapon_loaded", false)].into(),
            effect: [("weapon_loaded", true)].into(),
            cost: 2.0,
        },
        Action {
            name: "move_to_player",
            precondition: [].into(),
            effect: [("near_player", true)].into(),
            cost: 3.0,
        },
        Action {
            name: "shoot",
            precondition: [("has_weapon", true), ("weapon_loaded", true), ("near_player", true)].into(),
            effect: [("player_alive", false), ("weapon_loaded", false)].into(),
            cost: 1.0,
        },
    ];

    let start: WorldState = [
        ("player_alive", true), ("has_weapon", false),
        ("weapon_loaded", false), ("near_player", false),
    ].into();
    let goal: WorldState = [("player_alive", false)].into();

    let plan = goap(start, goal, &actions).unwrap();
    for a in &plan {
        println!("→ {}", a.name);
    }
    // 输出:
    // → pickup_weapon
    // → reload
    // → move_to_player
    // → shoot
}
```

GOAP 自己想出了"先捡武器,再装弹,再走过去,最后开枪"这条 plan。设计师不需要写这个序列——只需要定义原子动作和它们的前置/效果,AI 自动规划。

**优点**:
- 极强的"涌现"(emergent)行为。
- 设计师只需要定义动作,不用手写 plan。
- NPC 看起来"会思考"。

**缺点**:
- 计算贵(A* 在大状态空间慢)。需要限制状态变量数量(< 20)和动作数量(< 30)。
- 调试难(为什么 AI 选了这个 plan?)。
- 平衡难(调 cost 影响 plan,但很难预测)。

工业级 GOAP 库:Rust 的 `gw_runner`、C++ 的 IGameplayAction。

## 5 · HTN(Hierarchical Task Network)

### 5.1 模型

HTN 来自 High Level / Ghost Recon。思路:**设计师指定任务如何分解**。

HTN 有两种任务:
- **Primitive Task**:可执行(类似 GOAP 的 Action)。
- **Compound Task**:分解为子任务(类似函数调用)。

Compound Task 有多种 decomposition(分解方式),根据世界状态选一种。

例:NPC 任务"打败玩家":
- Compound: DefeatPlayer
  - 分解 1(玩家弱): Approach → Attack → Loot
  - 分解 2(玩家强): Stealth → Setup → Ambush → Attack
  - 分解 3(没武器): FindWeapon → Approach → Attack

每种分解有 precondition。

### 5.2 HTN vs GOAP

| 特性 | GOAP | HTN |
|---|---|---|
| 谁规划 | AI 自动(A*) | 设计师手动(写分解规则) |
| 涌现 | 高(意外行为多) | 低(设计师控制) |
| 调试 | 难 | 容易(知道在哪个分解) |
| 平衡 | 难(cost) | 容易(改分解规则) |
| 适用 | 开放沙盒 | 关卡式游戏 |

工业用 HTN 的多——可控性比 GOAP 强,且大部分游戏不需要太强的涌现。

## 6 · Steering Behaviors

### 6.1 模型

Steering behaviors 是 Craig Reynolds 1999 年提出。它们解决"如何让 NPC 自然地移动",而不是"决定去哪"。基本思路:**计算一个 steering force,把 NPC 向目标推**。

经典 steering behaviors:

- **Seek**:朝目标移动。`force = (target - pos).normalized() * max_speed - velocity`
- **Flee**:远离目标。`force = (pos - target).normalized() * max_speed - velocity`
- **Arrive**:像 seek 但接近目标时减速。
- **Wander**:随机游走(用"前方圆圈上随机点"做 jitter)。
- **Pursuit**:预测 seek(假设目标匀速,预测它未来位置然后 seek)。
- **Evade**:预测 flee。
- **Separation**:避开附近的同类。
- **Alignment**:匹配附近的同类方向。
- **Cohesion**:向附近的同类中心移动。
- **Flocking**:Separation + Alignment + Cohesion 三合一,模拟鸟群 / 鱼群。

### 6.2 Rust 实现

```rust
#[derive(Clone, Copy)]
struct Vec2 { x: f32, y: f32 }
impl Vec2 {
    fn sub(self, o: Self) -> Self { Self { x: self.x - o.x, y: self.y - o.y } }
    fn add(self, o: Self) -> Self { Self { x: self.x + o.x, y: self.y + o.y } }
    fn scale(self, s: f32) -> Self { Self { x: self.x * s, y: self.y * s } }
    fn length(self) -> f32 { (self.x * self.x + self.y * self.y).sqrt() }
    fn normalize(self) -> Self {
        let l = self.length();
        if l > 0.0 { self.scale(1.0 / l) } else { Self { x: 0.0, y: 0.0 } }
    }
    fn truncate(self, max: f32) -> Self {
        if self.length() > max { self.normalize().scale(max) } else { self }
    }
}

struct Boid {
    pos: Vec2,
    vel: Vec2,
}

fn seek(b: &Boid, target: Vec2, max_speed: f32) -> Vec2 {
    let desired = target.sub(b.pos).normalize().scale(max_speed);
    desired.sub(b.vel)
}

fn flee(b: &Boid, threat: Vec2, max_speed: f32, panic_dist: f32) -> Vec2 {
    let dist = b.pos.sub(threat).length();
    if dist > panic_dist { return Vec2 { x: 0.0, y: 0.0 }; }
    let desired = b.pos.sub(threat).normalize().scale(max_speed);
    desired.sub(b.vel)
}

fn separation(b: &Boid, others: &[Boid]) -> Vec2 {
    let mut force = Vec2 { x: 0.0, y: 0.0 };
    let mut count = 0;
    for o in others {
        let d = b.pos.sub(o.pos).length();
        if d > 0.0 && d < 30.0 {
            force = force.add(b.pos.sub(o.pos).normalize().scale(1.0 / d));
            count += 1;
        }
    }
    if count > 0 { force.scale(1.0 / count as f32) } else { force }
}

fn flocking(b: &Boid, others: &[Boid], max_speed: f32) -> Vec2 {
    let sep = separation(b, others).scale(1.5);
    let ali = alignment(b, others).scale(1.0);
    let coh = cohesion(b, others).scale(1.0);
    sep.add(ali).add(coh).truncate(max_speed)
}

fn alignment(b: &Boid, others: &[Boid]) -> Vec2 { /* ... */ Vec2 { x: 0.0, y: 0.0 } }
fn cohesion(b: &Boid, others: &[Boid]) -> Vec2 { /* ... */ Vec2 { x: 0.0, y: 0.0 } }

// 每帧
fn update_boid(b: &mut Boid, others: &[Boid], dt: f32, max_speed: f32, max_force: f32) {
    let accel = flocking(b, others, max_speed).truncate(max_force);
    b.vel = b.vel.add(accel.scale(dt)).truncate(max_speed);
    b.pos = b.pos.add(b.vel.scale(dt));
}
```

**用途**:
- 鸟群 / 鱼群(标志性例子)
- RTS 单位群组移动
- 城市里 NPC 行人流

Rust crate:`steering`、Bevy 的 `bevy-atb`。

## 7 · 寻路算法

### 7.1 模型

寻路是 AI 的"腿"——决定去哪之后,怎么走过去。所有寻路算法都在**图**上工作:节点 + 边。游戏里图的常见形态:
- **Grid**:2D 网格,每格是节点,4/8 邻居。
- **Waypoint**:关卡设计师放的"路径点"。
- **Navigation Mesh (NavMesh)**:关卡几何的凸分解,每个多边形是节点。

### 7.2 BFS / DFS

```rust
use std::collections::{VecDeque, HashSet};

// BFS:广度优先。最短路径(无权图)。
fn bfs(start: usize, goal: usize, adj: &Vec<Vec<usize>>) -> Option<Vec<usize>> {
    let mut visited = HashSet::new();
    let mut parent = std::collections::HashMap::new();
    let mut queue = VecDeque::new();
    queue.push_back(start);
    visited.insert(start);

    while let Some(node) = queue.pop_front() {
        if node == goal {
            // reconstruct path
            let mut path = vec![goal];
            let mut cur = goal;
            while cur != start {
                cur = *parent.get(&cur).unwrap();
                path.push(cur);
            }
            path.reverse();
            return Some(path);
        }
        for &next in &adj[node] {
            if visited.insert(next) {
                parent.insert(next, node);
                queue.push_back(next);
            }
        }
    }
    None
}
```

- **BFS**(广度优先):逐层扩展。在**无权图**上找最短路径。
- **DFS**(深度优先):一头扎到底。不保证最短,但内存少。

### 7.3 Dijkstra

带权图上的最短路径。用优先队列(min-heap),每次取当前 cost 最小的节点扩展。

```rust
use std::collections::{BinaryHeap, HashMap};
use std::cmp::Ordering;

#[derive(PartialEq, Eq)]
struct State { cost: u32, node: usize }
impl Ord for State {
    fn cmp(&self, o: &Self) -> Ordering {
        o.cost.cmp(&self.cost)  // min-heap(逆序)
    }
}
impl PartialOrd for State { fn partial_cmp(&self, o: &Self) -> Option<Ordering> { Some(self.cmp(o)) } }

fn dijkstra(start: usize, goal: usize, adj: &Vec<Vec<(usize, u32)>>) -> Option<u32> {
    let mut dist = HashMap::new();
    let mut heap = BinaryHeap::new();
    dist.insert(start, 0u32);
    heap.push(State { cost: 0, node: start });

    while let Some(State { cost, node }) = heap.pop() {
        if node == goal { return Some(cost); }
        if cost > *dist.get(&node).unwrap_or(&u32::MAX) { continue; }
        for &(next, w) in &adj[node] {
            let new_cost = cost + w;
            if new_cost < *dist.get(&next).unwrap_or(&u32::MAX) {
                dist.insert(next, new_cost);
                heap.push(State { cost: new_cost, node: next });
            }
        }
    }
    None
}
```

**复杂度**:O((V + E) log V)(用 heap)。

### 7.4 A*

A* 是 Dijkstra 加启发式。核心:**评估函数 f = g + h**,g 是已走 cost,h 是"估计到目标的剩余 cost"(启发式)。

A* 比 Dijkstra 快,因为 h 引导搜索方向——优先扩展"看起来更接近目标"的节点。

```rust
fn astar(start: usize, goal: usize, adj: &Vec<Vec<(usize, u32)>>,
         h: impl Fn(usize) -> u32) -> Option<u32> {
    let mut g_score = HashMap::new();
    let mut f_score = HashMap::new();
    let mut heap = BinaryHeap::new();

    g_score.insert(start, 0u32);
    f_score.insert(start, h(start));
    heap.push(State { cost: h(start), node: start });

    while let Some(State { cost: _, node }) = heap.pop() {
        if node == goal {
            return Some(*g_score.get(&goal).unwrap());
        }
        let cur_g = *g_score.get(&node).unwrap();
        for &(next, w) in &adj[node] {
            let tentative_g = cur_g + w;
            if tentative_g < *g_score.get(&next).unwrap_or(&u32::MAX) {
                g_score.insert(next, tentative_g);
                let f = tentative_g + h(next);
                f_score.insert(next, f);
                heap.push(State { cost: f, node: next });
            }
        }
    }
    None
}
```

**h 的选择**:
- **Manhattan distance**(|dx| + |dy|):grid 上 4 邻居,保证 admissible(不高估)。
- **Euclidean distance**(√(dx² + dy²)):grid 上 8 邻居或自由移动。
- **Chebyshev distance**(max(|dx|, |dy|)):grid 上 8 邻居。

**关键**:h 必须 admissible(不高估真实剩余 cost),否则 A* 不保证最优。h = 0 时,A* 退化到 Dijkstra。

### 7.5 Rust crate

| crate | 用途 |
|---|---|
| `pathfinding` | 通用,A* / Dijkstra / BFS / DFS |
| `petgraph` | 图算法库 |
| `astar` | 专门的 A* |

工业级游戏寻路库:Recast & Detour(C++,NavMesh + A*),Bevy 的 `bevy_pathmesh`。

## 8 · ECS + AI

### 8.1 思路

Bevy 等 ECS 引擎里,AI 不再是"一个 Npc struct 持有 state",而是"AI 是组件组合":
- `Brain: FSM` 组件
- `Perception: 视野范围、可见实体` 组件
- `Steering: vel、target` 组件
- `Path: Vec<Vec2>` 组件

System 按顺序执行:Perception → Brain → Steering → Path → Movement。

```rust
#[derive(Component)]
struct Brain { state: BrainState }

#[derive(Component)]
struct Perception { range: f32, visible: Vec<Entity> }

fn perception_system(
    mut query: Query<(Entity, &mut Perception, &Transform)>,
    others: Query<(Entity, &Transform, With<Player>)>,
) {
    for (entity, mut perc, tf) in query.iter_mut() {
        perc.visible.clear();
        for (other_e, other_tf, _) in others.iter() {
            let d = tf.translation.distance(other_tf.translation);
            if d < perc.range {
                perc.visible.push(other_e);
            }
        }
    }
}

fn brain_system(
    mut query: Query<(&mut Brain, &Perception)>,
) {
    for (mut brain, perc) in query.iter_mut() {
        if !perc.visible.is_empty() {
            brain.state = BrainState::Chase;
        } else {
            brain.state = BrainState::Patrol;
        }
    }
}
```

### 8.2 Bevy AI 库

| crate | 用途 |
|---|---|
| `bigbrain` | Utility AI for Bevy |
| `bevy-atb` | Behavior tree |
| `bevy_rapier` | 物理 + 碰撞,辅助 perception |
| `bevy_pathmesh` | NavMesh 寻路 |

`bigbrain` 用法:

```rust
use bigbrain::prelude::*;

app.add_plugins(BigBrainPlugin);

// 给 NPC 加 AI
commands.entity(npc)
    .insert(Thinker::build()
        .picker(FirstToScore { threshold: 0.8 })
        .when(All { score: 0.0 }, AttackAction)
        .when(All { score: 0.0 }, FleeAction)
        .otherwise(PatrolAction));

// Action 实现
#[derive(Component, Clone)]
struct AttackAction;
impl Action for AttackAction {
    fn build(&self, cmd: &mut Commands, action: Entity, _actor: Entity) { /* ... */ }
}

// Scorer
#[derive(Component, Clone, Reflect)]
struct LowHealth;
impl Scorer for LowHealth {
    fn score(&self, ...) -> f32 { /* ... */ }
}
```

bigbrain 让"加 AI"变成"加组件 + 定义 action/scorer"。这是 Bevy 风格的 AI。

## 9 · AI 调试

### 9.1 调试工具

AI 调试的核心问题是"为什么 NPC 这么做?"。工业级做法:

1. **AI 日志**:每个 NPC 每 tick 输出 `state = X, decision = Y, reason = Z`。grep 日志定位。
2. **可视化**:在屏幕上画 NPC 当前状态(颜色)、目标(箭头)、感知范围(圆)。
3. **AI Inspector**:`bevy_atb` / UE 的 Behavior Tree editor——可视化 BT 节点状态(高亮当前节点)。
4. **Replay**:记录每帧 AI 状态,bug 出现时回放。

### 9.2 常见 bug

- **NPC 卡在墙边**:寻路 + steering 冲突。解法:steering 失败时停止寻路,触发 repath。
- **NPC 抖动**:行为间频繁切换。解法:hysteresis(切到 X 后保持 N 帧)。
- **NPC 不响应感知**:perception 系统频率太低。解法:perception 单独 system,跑 10Hz 而不是 60Hz。
- **NPC 群聚**:同 breed NPC 都追同一目标。解法:加 separation steering。

## 10 · 延伸阅读

- Behavior Tree 经典论文:https://www.gamedeveloper.com/programming/behavior-trees-for-ai-how-they-work
- F.E.A.R. GOAP 论文(免费 PDF):https://cdn.cloudflare.steamstatic.com/apps/valve/2015/Ors_LeClerc_FEAR_AI.pdf
- Dave Mark "Behavioral Mathematics for Game AI":Utility AI 圣经
- Reynolds 的 flocking 论文(steering behaviors):https://www.red3d.com/cwr/steer/
- A* 经典介绍:Amit Patel 的 https://www.redblobgames.com/pathfinding/a-star/introduction.html
- Recast Navigation(C++ NavMesh + A*):https://github.com/recastnavigation/recastnavigation
- bigbrain crate:https://github.com/zkat/bigbrain
- Casey HH AI 相关 day 列表:Day 130 / 135 / 140 / 145 / 150 / 155 / 160 / 165
