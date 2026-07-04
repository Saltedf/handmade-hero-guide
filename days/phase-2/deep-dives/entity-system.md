
# 实体系统演化 · 从朴素 struct 到 sparse array 到 ECS

> 玩家、怪物、子弹、墙、金币——这些东西在代码里怎么表达?这是游戏开发最古老的争论。从 1970s 的"所有东西一个 struct",到 1990s 的"对象继承树",到 2010s 的"组件系统",再到 2020s 的"ECS"。Casey 在 HH 里选了"sparse array + generation index"——介于 90s 和 10s 之间的中间方案。本文 2 小时讲完这条演化路径,让你看任何引擎的实体系统都不迷路。

## 0 · 这篇文章解决什么问题

你跟着 HH 走到 Day 030,写了第一个 entity:

```rust
struct Entity {
    pos: Vec2,
    vel: Vec2,
    kind: EntityKind,
    hp: i32,
    alive: bool,
}
```

每帧 update,你写:

```rust
let mut entities: Vec<Entity> = vec![player, monster1, monster2, gold1, ...];
for e in entities.iter_mut() {
    e.pos += e.vel * dt;
    // ...
}
```

这看起来够用了。但你做下去就发现:

1. **加新字段**:加 `mana`,所有 entity 都吃一份内存——但墙不需要 mana,火球不需要 hp。**内存浪费**。
2. **创建销毁**:火球发射 / 撞怪消失,每秒几十次。Vec 删除是 O(n),性能差。**洞**(dangling index)问题:`entities[5]` 删了再访问,要么 panic 要么拿到垃圾。
3. **类型区分**:遍历所有怪做 AI,你要 `if e.kind == Monster`,大量分支预测失败。**性能差**。
4. **跨函数引用**:函数 A 创建火球,返回火球的"句柄"给函数 B。返回 `&mut Entity`?那 A 不能再修改它。返回 `usize`(index)?那 B 用 index 时 entity 可能已被销毁。**use-after-free**。
5. **不同 entity 不同行为**:玩家有"输入控制",怪有"AI 控制",墙"不动"。一个 `update` 函数装得下所有逻辑吗?**逻辑膨胀**。

这 5 个问题各自不致命,但加起来让 entity 系统的复杂度爆炸。Casey 演化了 4 个阶段解决它们,本文重走这条路:

1. **阶段 1:朴素 struct + Vec**(Day 030-040)—— 上面的写法
2. **阶段 2:稀疏数组 + generation index**(Day 051-055)—— 解决 use-after-free
3. **阶段 3:类型分组 + sparse storage**(Day 066-069)—— 解决字段浪费
4. **阶段 4:ECS(Entity-Component-System)**(Phase 5+ 转化方向)—— 解决一切

读完本文你能:

- 解释每个阶段解决什么问题
- 知道 Casey 为什么停在阶段 2-3
- 知道什么时候该升级到 ECS
- 自己实现一个最简单的 ECS

## 1 · 阶段 1:朴素 struct + Vec

### 1.1 最原始的写法

```rust
#[derive(Clone, Copy, Debug)]
enum EntityKind { Player, Monster, Wall, Projectile, Gold }

struct Entity {
    kind: EntityKind,
    pos: Vec2,
    vel: Vec2,
    half_size: f32,
    hp: i32,
    mana: i32,
    damage: i32,
    sprite: Option<BitmapId>,
    ai_state: Option<AiState>,
    alive: bool,
}

struct World {
    entities: Vec<Entity>,
}
```

### 1.2 问题逐个分析

**问题 1:内存浪费**

墙(Wall)不需要 hp / mana / damage / ai_state。但所有 entity 是同一个 struct,字段都占内存。`Option<AiState>` 至少 1 字节(标 Some/None),实际可能 16 字节(AiState struct 大小)。1000 个墙 = 16KB 浪费。

**问题 2:Vec 删除有洞**

```rust
// 删 entity index 5
entities.remove(5);
// 后面所有 entity index 减 1
// 你之前保存的 "monster1 在 index 5" 失效!
```

或者用 swap_remove:

```rust
entities.swap_remove(5);
// entities[5] 现在是原来的最后一个 entity
// 你保存的 index 失效方式不同(更糟)
```

**问题 3:跨函数引用**

```rust
fn spawn_fireball(world: &mut World, target: usize) {
    let id = world.entities.len();
    world.entities.push(Entity::new_fireball(...));
    // 我要告诉 target 怪"被火球 id 锁定"
    world.entities[target].targeted_by = Some(id);  // ← id 是 usize
}

fn later(world: &mut World, target_id: usize) {
    let target = &mut world.entities[target_id];  // ← 这个 id 还有效吗?
    // 可能在 between 火球已经撞怪消失了,targeted_by 现在指向一个新 entity
    // 或者 target_id >= world.entities.len()(越界 panic)
}
```

**这是 use-after-free 的根源**。index 没有"有效性"信息。

**问题 4:逻辑分支**

```rust
fn update(e: &mut Entity, input: &GameInput, dt: f32) {
    match e.kind {
        EntityKind::Player => {
            e.vel.x = input.controllers[0].stick_average_x * 100.0;
            e.pos += e.vel * dt;
            // 玩家专属逻辑
        },
        EntityKind::Monster => {
            let player = ...; // 找玩家
            let dir = player.pos - e.pos;
            e.vel = dir.normalized() * 50.0;
            e.pos += e.vel * dt;
            // AI 专属逻辑
            if let Some(state) = &mut e.ai_state {
                state.update(dt);
            }
        },
        EntityKind::Wall => {
            // 墙不动,什么都不做
        },
        // ... 5 个分支
    }
}
```

`match` 每个 entity 都跑一次,分支预测命中率低(因为 entity 类型分布可能均匀)。

### 1.3 何时这个阶段够用?

- 游戏 entity < 100
- 不频繁创建/销毁
- 没有"跨函数持有 entity 引用"的需求
- 简单的小游戏(贪吃蛇、俄罗斯方块、井字棋)

Casey 在 Day 030-040 用这个阶段——游戏刚开始,玩家 + 几个怪。

## 2 · 阶段 2:稀疏数组 + generation index

### 2.1 核心思路

把"index"升级成"代际 index"——`(位置, 代数)`。每次 entity 销毁,代数 +1。持有旧代数的人访问时,系统检查代数不匹配 → 返回 None。

```rust
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct EntityId {
    pub index: u32,       // 在数组里的位置
    pub generation: u32,  // 代数(这个位置第几代 entity)
}

struct Slot {
    pub generation: u32,        // 当前代数
    pub entity: Option<Entity>, // None = 空,Some = 占用
}

struct World {
    slots: Vec<Slot>,
    free_indices: Vec<u32>,     // 被释放的 slot 位置,可重用
}
```

### 2.2 创建销毁

```rust
impl World {
    pub fn spawn(&mut self, e: Entity) -> EntityId {
        if let Some(index) = self.free_indices.pop() {
            // 重用空 slot
            let slot = &mut self.slots[index as usize];
            slot.generation += 1;                    // 代数 +1
            slot.entity = Some(e);
            EntityId { index, generation: slot.generation }
        } else {
            // 没有空 slot,扩展
            let index = self.slots.len() as u32;
            self.slots.push(Slot { generation: 0, entity: Some(e) });
            EntityId { index, generation: 0 }
        }
    }

    pub fn despawn(&mut self, id: EntityId) {
        if self.is_alive(id) {
            self.slots[id.index as usize].entity = None;
            self.free_indices.push(id.index);
        }
    }

    pub fn is_alive(&self, id: EntityId) -> bool {
        let slot = &self.slots[id.index as usize];
        slot.generation == id.generation && slot.entity.is_some()
    }

    pub fn get(&self, id: EntityId) -> Option<&Entity> {
        if self.is_alive(id) {
            self.slots[id.index as usize].entity.as_ref()
        } else {
            None
        }
    }

    pub fn get_mut(&mut self, id: EntityId) -> Option<&mut Entity> {
        if self.is_alive(id) {
            self.slots[id.index as usize].entity.as_mut()
        } else {
            None
        }
    }
}
```

### 2.3 解决了什么问题

**问题 4(use-after-free)彻底解决**:

```rust
let id1 = world.spawn(monster1);
world.despawn(id1);
let id2 = world.spawn(monster2);  // 可能在同一 slot,但 generation 已经 +1

world.get(id1)  // → None,因为 id1.generation != slot.generation
world.get(id2)  // → Some(monster2)
```

旧的 EntityId 自动失效,不会拿到错误的 entity。

**问题 2(删除洞)解决**:slot 不真删,只是 mark 成 None,可重用。Vec 不需要 shift。

### 2.4 没解决的问题

**问题 1(内存浪费)** 仍然存在——每个 slot 都装整个 Entity struct,墙还是浪费 mana 字段。

**问题 3(逻辑分支)** 仍然存在——update 函数还是要 match kind。

### 2.5 Rust crate 推荐

`slotmap` crate 是这套方案的工业实现:

```toml
[dependencies]
slotmap = "1.0"
```

```rust
use slotmap::{SlotMap, dense_map::DenseSlotMap, Key};

slotmap::new_key_type! {
    pub struct EntityKey: u32;
}

let mut entities: SlotMap<EntityKey, Entity> = SlotMap::with_key();
let key = entities.insert(monster1);
// 后面 entities[key] 访问
entities.remove(key);
// entities[key] 现在会 panic(SlotMap 内部检查 generation)
```

`slotmap` 比 Vec 慢一点点(每次访问多一次 generation 检查),但 use-after-free 完全杜绝。

### 2.6 Casey 的选择

Casey 在 Day 051-055 实现了这套机制(他手写,不用 crate)。这是 HH 全程的 entity 系统。Day 066-069 加"非空间 entity"和"碰撞规则表"是在这套基础上的扩展,不是替换。

## 3 · 阶段 3:类型分组 + sparse storage

### 3.1 解决内存浪费

不同 entity 用不同 struct:

```rust
struct Player { pos: Vec2, vel: Vec2, hp: i32, mana: i32, ... }
struct Monster { pos: Vec2, vel: Vec2, hp: i32, ai_state: AiState, ... }
struct Wall { pos: Vec2, half_size: f32, sprite: BitmapId, ... }
struct Projectile { pos: Vec2, vel: Vec2, damage: i32, lifetime: f32, ... }
struct Gold { pos: Vec2, amount: i32, sprite: BitmapId, ... }

enum EntityRef {
    Player(EntityId),
    Monster(EntityId),
    Wall(EntityId),
    Projectile(EntityId),
    Gold(EntityId),
}

struct World {
    players: SlotMap<EntityId, Player>,
    monsters: SlotMap<EntityId, Monster>,
    walls: SlotMap<EntityId, Wall>,
    projectiles: SlotMap<EntityId, Projectile>,
    golds: SlotMap<EntityId, Gold>,
}
```

**好处**:
- 墙不浪费 mana / hp 字段
- 同类 entity 在内存里连续(cache 友好)
- update 只遍历自己类型的容器,不分支:

```rust
for p in self.players.values_mut() { update_player(p, input, dt); }
for m in self.monsters.values_mut() { update_monster(m, dt); }
// walls 不 update
for proj in self.projectiles.values_mut() { update_projectile(proj, dt); }
```

**坏处**:
- 碰撞检测要跨容器查(`monsters × walls`、`projectiles × monsters`)
- "找一个 entity"需要 enum dispatch
- 加新类型要改 World 结构

### 3.2 Casey 的实用版

Casey 不完全按类型分(那样太碎)。他做的是"普通 entity 共享一个 struct,墙之类的特殊 entity 用 tag":

```rust
struct Entity {
    pos: Vec2,
    vel: Vec2,
    half_size: f32,
    kind: EntityKind,
    hp: i32,            // 所有 entity 都有,墙用不到(默认 0)
    // ... 其他通用字段
}

struct World {
    entities: SlotMap<EntityId, Entity>,
}
```

墙的 hp 是 0,mana 是 0——浪费一点内存,但 update 逻辑统一。**这是工程妥协**:不在内存和复杂度之间走极端。

Casey 在 Day 066-067 加"non-spatial entity"和"conditional update",进一步优化:墙不参与 update(状态机跳过),节省 CPU。

### 3.3 业界方案

Unity / Unreal 的 GameObject / Actor + Components 是这套思想的演化:每个 entity 是基础 GameObject,加 Component(PlayerComponent, MonsterComponent, ...)。

```csharp
// Unity C#
public class Player : MonoBehaviour {
    void Update() { /* player logic */ }
}
public class Monster : MonoBehaviour {
    void Update() { /* monster logic */ }
}
// 墙不带 Player 或 Monster 组件,自然不参与对应逻辑
```

Casey 的"统一 struct + kind tag"是简化的 component——所有 component 都塞进 struct,用 kind 区分。

## 4 · 阶段 4:ECS(Entity-Component-System)

### 4.1 ECS 的核心思想

把"entity"和"数据"完全分开:

- **Entity** = 一个 ID(没有任何数据)
- **Component** = 纯数据(没有逻辑),比如 `Position`、`Velocity`、`Health`
- **System** = 处理特定 component 组合的函数,比如 "对所有有 Position 和 Velocity 的 entity,把 Position += Velocity * dt"

```rust
// ECS 风格

// Entity 只是个 ID
#[derive(Clone, Copy, PartialEq, Eq, Hash)]
struct Entity(u64);

// Component 是纯数据
#[derive(Debug)]
struct Position(Vec2);
struct Velocity(Vec2);
struct Health(i32);
struct PlayerTag;
struct MonsterTag;

// System 处理 component
fn movement_system(
    positions: &mut ComponentStorage<Position>,
    velocities: &ComponentStorage<Velocity>,
) {
    for (entity, vel) in velocities.iter() {
        if let Some(pos) = positions.get_mut(entity) {
            pos.0 += vel.0 * 0.016;
        }
    }
}

fn monster_ai_system(/* ... */) { ... }
fn render_system(/* ... */) { ... }
```

### 4.2 ECS 的优势

1. **内存完美**:只有"有 Position 的 entity"才占 Position 内存
2. **逻辑分支消失**:每个 system 只看自己关心的 component,不 `match kind`
3. **天然并行**:movement_system 改 Position,render_system 只读 Position,可以并行跑
4. **加新功能**:加"Buff" component,加"buff_system",零侵入

### 4.3 ECS 的代价

1. **学习曲线陡**:从 OOP 思维转向 data-oriented 思维
2. **抽象复杂**:ComponentStorage 内部要处理"entity 没这个 component 怎么办"
3. **查询开销**:找"有 Position 和 Velocity 的 entity"需要 join,有 hash 或排序开销
4. **debug 难**:entity 是抽象 ID,无法直接 println 看全貌

### 4.4 最简 ECS 实现

```rust
use std::collections::HashMap;

// Entity 就是个 ID
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
struct Entity(u64);

// Component trait
trait Component: 'static + Send + Sync {}

// World
struct World {
    next_id: u64,
    entities: Vec<Entity>,
    // 用 type-erased HashMap 存所有 component
    storages: HashMap<std::any::TypeId, Box<dyn std::any::Any + Send + Sync>>,
}

impl World {
    fn new() -> Self {
        Self {
            next_id: 0,
            entities: Vec::new(),
            storages: HashMap::new(),
        }
    }

    fn spawn(&mut self) -> Entity {
        let e = Entity(self.next_id);
        self.next_id += 1;
        self.entities.push(e);
        e
    }

    fn insert<C: Component>(&mut self, e: Entity, c: C) {
        let type_id = std::any::TypeId::of::<C>();
        let storage = self.storages
            .entry(type_id)
            .or_insert_with(|| Box::new(HashMap::<Entity, C>::new()));
        let map = storage.downcast_mut::<HashMap<Entity, C>>().unwrap();
        map.insert(e, c);
    }

    fn get<C: Component>(&self, e: Entity) -> Option<&C> {
        let type_id = std::any::TypeId::of::<C>();
        let storage = self.storages.get(&type_id)?;
        let map = storage.downcast_ref::<HashMap<Entity, C>>().unwrap();
        map.get(&e)
    }

    fn get_mut<C: Component>(&mut self, e: Entity) -> Option<&mut C> {
        let type_id = std::any::TypeId::of::<C>();
        let storage = self.storages.get_mut(&type_id)?;
        let map = storage.downcast_mut::<HashMap<Entity, C>>().unwrap();
        map.get_mut(&e)
    }

    fn query<C: Component>(&self) -> Vec<(Entity, &C)> {
        let type_id = std::any::TypeId::of::<C>();
        let storage = match self.storages.get(&type_id) {
            Some(s) => s,
            None => return Vec::new(),
        };
        let map = storage.downcast_ref::<HashMap<Entity, C>>().unwrap();
        map.iter().map(|(e, c)| (*e, c)).collect()
    }
}

// Component impl
impl Component for Position {}
impl Component for Velocity {}

fn main() {
    let mut world = World::new();

    let player = world.spawn();
    world.insert(player, Position(Vec2::new(0.0, 0.0)));
    world.insert(player, Velocity(Vec2::new(10.0, 0.0)));

    let monster = world.spawn();
    world.insert(monster, Position(Vec2::new(50.0, 0.0)));
    world.insert(monster, Velocity(Vec2::new(0.0, 5.0)));

    // movement system
    let mut positions = world.query::<Position>();
    let _ = positions; // 注意:Rust 借用规则会阻止同时 query Position 和 Velocity,
                       // 真实 ECS 用 unsafe 或更复杂的 API
}
```

这是教学版,生产版用 `bevy_ecs` 或 `hecs` 或 `legion`。

### 4.5 业界 ECS

| 引擎 / crate | ECS 风格 | 特点 |
|---|---|---|
| Bevy | archetype-based | 性能最好,query 并行 |
| Unity DOTS | archetype-based | Unity 官方 ECS |
| hecs | sparse | 简单,API 友好 |
| legion | archetype | 已停止维护 |
| specs | shred-based | 老牌,文档全 |
| Casey HH | sparse array + kind tag | 不是 ECS,但思路类似 |

### 4.6 Casey 为什么不上 ECS?

1. **教学复杂度**:ECS 抽象层多,HH 是教学项目,要简单
2. **Phase 5+ 才需要**:Phase 2-4 entity 数 < 1000,sparse array 够
3. **HH 录制年代(2014-2018)**:那时 ECS 还不普及
4. **Casey 的 OOP 倾向**:他的代码风格偏 90s id Software,不是 DOD(data-oriented design)

但 HH 学完后,你能轻松切换到 ECS——所有概念(Entity / Component / System / Storage)你都懂底层。

## 5 · 演化决策树

### 5.1 什么时候升级?

| 阶段 | entity 数 | 字段复杂度 | 触发升级信号 |
|---|---|---|---|
| 1: Vec<Entity> | < 100 | 简单 | 出现 use-after-free |
| 2: sparse + gen | < 1000 | 中等 | 出现字段浪费 / 分支预测失败 |
| 3: 类型分组 | < 10000 | 多类型 | 加新类型累,容器爆炸 |
| 4: ECS | 任意 | 任意 | 想自动并行 / 跨系统组合 |

### 5.2 升级时的迁移成本

- 阶段 1 → 2:**重写 World**。Entity 数据结构不动,API 换成 EntityId。
- 阶段 2 → 3:**拆 World 为多容器**。update 函数加 dispatch。
- 阶段 3 → 4:**完全重写**。所有 component 拆开,所有 system 重写。

Casey 故意停在阶段 2-3——避免阶段 4 的大重构。Phase 5+ 你想升级 ECS 时,从头开始(用 bevy_ecs),而不是渐进迁移。

## 6 · 性能对比

### 6.1 内存占用

1000 个 entity,每个有 10 个字段,平均字段大小 8 字节:

| 方案 | 内存 | 注释 |
|---|---|---|
| Vec<Entity> | 80 KB | 所有 entity 都有所有字段 |
| Sparse + gen | 80 KB + 8 KB(slot metadata) | 加 generation 开销 |
| 类型分组 | ~50 KB(假设 30% 字段共享) | 不同类型不同 struct |
| ECS | ~50 KB(同上)+ archetype metadata | 同分量,但查询更慢 |

差别不大。**1MB 内存 1000 个 entity,任何方案都够用**。

### 6.2 CPU 时间

1000 个 entity,每帧 update(纯算 pos += vel * dt):

| 方案 | 时间 | 注释 |
|---|---|---|
| Vec<Entity> | ~10 µs | cache 完美 |
| Sparse + gen | ~12 µs | 多一次 generation 检查 |
| 类型分组 | ~10 µs | 同类连续 |
| ECS | ~30 µs | 查询开销 |

ECS 慢一点,但**仅限小规模**。entity 数 10000+,ECS 因为并行化反超。

### 6.3 加新功能

加一个"Buff"系统(有些 entity 有 buff,会扣血):

| 方案 | 改动 |
|---|---|
| Vec<Entity> | 加 `buff: Option<Buff>` 字段 + if 分支 |
| Sparse + gen | 同上 |
| 类型分组 | 加新 container + 新 update 分支 |
| ECS | 加 BuffComponent + buff_system,**零侵入** |

ECS 在扩展性上碾压。

## 7 · Rust 实战推荐

### 7.1 学习用

阶段 1:手写(Phase 2 你已经做了)
阶段 2:手写 + 看 `slotmap` 源码
阶段 3:手写
阶段 4:用 `hecs`(比 bevy_ecs 简单,适合学习)

```toml
[dependencies]
hecs = "0.10"
```

```rust
use hecs::World;

let mut world = World::new();
let player = world.spawn((Position::default(), Velocity::default(), PlayerTag));
let monster = world.spawn((Position::new(50.0, 0.0), Velocity::default(), MonsterTag));

// System
for (id, (pos, vel)) in &mut world.query::<(&mut Position, &Velocity)>() {
    pos.0 += vel.0 * 0.016;
}
```

### 7.2 生产用

`bevy_ecs` 是 Bevy 引擎的 ECS 子 crate,可以独立用:

```toml
[dependencies]
bevy_ecs = "0.14"
```

```rust
use bevy_ecs::prelude::*;

#[derive(Component)]
struct Position(Vec2);

#[derive(Component)]
struct Velocity(Vec2);

fn movement_system(mut query: Query<(&mut Position, &Velocity)>) {
    for (mut pos, vel) in &mut query {
        pos.0 += vel.0 * 0.016;
    }
}

fn main() {
    let mut world = World::new();
    let mut schedule = Schedule::default();
    schedule.add_systems(movement_system);

    world.spawn(Position(Vec2::new(0.0, 0.0)));
    // ...

    schedule.run(&mut world);
}
```

## 8 · 关键概念对照表

| HH(Day 030-069) | slotmap crate | hecs | bevy_ecs | Unity |
|---|---|---|---|---|
| `struct Entity { ... }` | `T`(value) | `(Components)` tuple | `Entity` (id only) | GameObject |
| `EntityId` | `EntityKey` | `Entity` | `Entity` | instance ID |
| `World.entities` | `SlotMap<K, V>` | `World` | `World` | Scene |
| `kind: EntityKind` | 字段 | `Tag` component | `Tag` component | Component |
| `fn update(e: &mut Entity)` | 外部 fn | System | System | Component.Update() |
| generation | 内部 | 内部 | 内部 | instance ID version |

## 9 · 延伸阅读

本仓库:
- [day030.md](../day030.md) —— 第一个 entity
- [day050.md](../day050.md) —— entity 间碰撞
- [day051.md](../day051.md) —— 频率分层(条件 update 的雏形)
- [day055.md](../day055.md) —— hash 世界存储
- [day066.md](../day066.md) —— 非空间 entity
- [day069.md](../day069.md) —— 碰撞规则(类型对派发)

外部:
- ECS Back and Forth — Sander Mertens: https://skypjack.github.io/2019-02-14-ecs-baf-part-1/
- Data-Oriented Design — Richard Fabian: https://www.dataorienteddesign.com/dodbook/
- Bevy Book: https://bevyengine.org/learn/book/

开源源码:
- `slotmap`: https://github.com/orlp/slotmap
- `hecs`: https://github.com/Ralith/hecs
- `bevy_ecs`: https://github.com/bevyengine/bevy/tree/main/crates/bevy_ecs
- Unity Entities(DOTS ECS)源码: https://github.com/Unity-Technologies/EntityComponentSystemSamples
