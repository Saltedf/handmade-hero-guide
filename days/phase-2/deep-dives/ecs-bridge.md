---
phase: 2
type: deep-dive
title: "ECS 渐进演化:从 HH 稀疏数组到工业 archetype"
domains: [game, rust, data-structures]
duration: "2-3h"
prereqs: ["day046", "day055", "day176"]
---

# ECS 渐进演化 · 从 HH 稀疏数组到工业 archetype

> Casey 在 Handmade Hero 里演化出了一个"稀疏数组 + generation index"的实体管理方案。这个方案很好,但工业级 ECS(Bevy、Flecs、Unity DOTS、Unreal Mass)走得更远——它们演化到了"archetype-based ECS"。这篇文章重走这条演化路径,分 7 个阶段,每个阶段:痛点 → 方案 → 新问题。读完你不仅能看懂 Casey 的稀疏数组,还能看懂 Bevy 的源码。

## 0 · 这篇文章解决什么问题

你跟着 HH 走完了 Phase 2 的 entity 系统演化(Day 046-055)。你能写出:

```rust
struct World {
    entities: Vec<Option<Entity>>,
    generations: Vec<u32>,
}

struct Handle {
    index: usize,
    generation: u32,
}
```

这是"HH 风格"的 entity 系统。它解决了 use-after-free(generation index),解决了内存复用(Option 槽位重用)。但工业 ECS 走得更远——

工业 ECS 的额外目标:

1. **cache 友好**:遍历 1000 个 entity 的 position 时,内存连续,无 cache miss。
2. **类型分组**:遍历所有"有 Position 和 Velocity 的"entity,不浪费遍历"只有 Position 没 Velocity"的。
3. **字段不浪费**:墙(只有 Position,没有 HP / Mana)不为 HP / Mana 字段付内存。
4. **并行调度**:无组件冲突的系统并行运行。
5. **codegen / 类型安全**:不要 `Box<dyn Any>` 这种动态类型,要编译时类型安全。

这 5 个目标,**HH 的稀疏数组一个都做不到**。工业 ECS 是从 HH 风格开始,**为这 5 个目标逐步演化**出来的。

本文重走演化,7 个阶段:

1. **阶段 1**:朴素 struct + Vec(HH Day 026-030)。
2. **阶段 2**:稀疏数组 + generation index(HH Day 046-055)。
3. **阶段 3**:组件分离(struct Position, struct Velocity, ...)。
4. **阶段 4**:Structure of Arrays(SoA)。
5. **阶段 5**:archetype(按组件组合分组)。
6. **阶段 6**: archetype + 系统调度(Bevy 风格)。
7. **阶段 7**:for-else / bitset / 查询编译(顶级优化)。

每个阶段:**痛点 → 方案 → 新问题**。

读完本文,你看 Bevy / Unity DOTS / Unreal Mass 的源码不再迷路——它们都在阶段 5-7。

## 阶段 1 · 朴素 struct + Vec

### 起点:最朴素的写法

你刚做完 HH Day 026,有一个能动的方块。你的 entity 是这样:

```rust
#[derive(Debug)]
struct Entity {
    pos: Vec2,
    vel: Vec2,
    kind: EntityKind,  // Player / Monster / Wall / Bullet / ...
    hp: i32,
    mana: i32,
    alive: bool,
}

struct World {
    entities: Vec<Entity>,
}

impl World {
    fn spawn(&mut self, e: Entity) -> usize {
        self.entities.push(e);
        self.entities.len() - 1
    }

    fn get(&self, idx: usize) -> &Entity {
        &self.entities[idx]
    }

    fn get_mut(&mut self, idx: usize) -> &mut Entity {
        &mut self.entities[idx]
    }
}
```

用法:
```rust
let mut world = World { entities: vec![] };
let player_id = world.spawn(Entity { pos: ..., kind: Player, hp: 100, mana: 50, ... });
let wall_id = world.spawn(Entity { pos: ..., kind: Wall, hp: 0, mana: 0, ... });
// 主循环
for e in &mut world.entities {
    if e.alive {
        e.pos += e.vel * dt;
        // AI / 物理 / 渲染
    }
}
```

这看起来很好。**简洁、直观、初学者友好**。Casey 在 Day 026-040 就是这么写的。

### 痛点(5 条)

随着游戏复杂度增长,这套方案的 5 个痛点浮现:

**痛点 1:字段浪费**。

墙(Wall)没有 hp,但每个 Wall 实例的 struct 里仍然有 `hp: i32` 字段(占 4 字节)。墙没有 mana,但仍然有 `mana: i32`(4 字节)。1000 面墙浪费 8KB 内存。

**痛点 2:遍历低效**。

你想"遍历所有怪物做 AI":
```rust
for e in &mut world.entities {
    if e.kind == EntityKind::Monster {
        // AI 逻辑
    }
}
```
每次循环要 `if` 判断,大量分支预测失败。1000 个 entity 里只有 50 个怪物,950 次判断是浪费。

**痛点 3:删除 O(n)**。

`Vec::remove(idx)` 是 O(n)——idx 后所有元素向前移动。火球发射 / 撞怪消失,每秒几十次,Vec::remove 累计成本高。

**痛点 4:use-after-free**。

```rust
let player = world.spawn(player_entity);  // player = 5
// ... 一段时间后
world.remove(player);  // entities.remove(5) → entities[5] 现在是另一个 entity
// ... 后续代码拿着旧的 player = 5 访问
world.get(player).hp  // 拿到的不是 player 的 hp,是新进来的 entity 的 hp!bug!
```

**痛点 5:跨函数引用难**。

```rust
fn shoot_bullet(world: &mut World, shooter_idx: usize) -> usize {
    let shooter = &world.entities[shooter_idx];  // 借用 world
    let bullet = Entity { pos: shooter.pos, ... };
    world.spawn(bullet)  // 错误!world 已经被借用,不能再 mutably 借
}
```

Rust 借用检查器拒绝。你要么 `clone` shooter 的数据(浪费),要么 unsafe(危险),要么重构(痛苦)。

**这 5 个痛点加起来**,Phase 2 后期(Day 046+)Casey 决定重写 entity 系统。这就是阶段 2。

## 阶段 2 · 稀疏数组 + generation index

### 方案:Casey 在 HH Day 046-055 演化

针对阶段 1 的痛点 3、4、5,Casey 引入:

**方案 1:稀疏数组**(解决 O(n) 删除)。
```rust
struct World {
    entities: Vec<Option<Entity>>,  // 删除的 entity 设为 None,不移除
}

impl World {
    fn despawn(&mut self, idx: usize) {
        self.entities[idx] = None;  // O(1)
    }
}
```

删除是 O(1)——设为 None 即可。下次 spawn 时复用 None 槽位(线性扫描或 free list)。

**方案 2:generation index**(解决 use-after-free)。
```rust
struct World {
    entities: Vec<Option<Entity>>,
    generations: Vec<u32>,
}

#[derive(Copy, Clone, PartialEq, Eq)]
struct Handle {
    index: usize,
    generation: u32,
}

impl World {
    fn spawn(&mut self, e: Entity) -> Handle {
        // 找空槽
        for i in 0..self.entities.len() {
            if self.entities[i].is_none() {
                self.generations[i] += 1;  // 槽位复用,generation +1
                self.entities[i] = Some(e);
                return Handle { index: i, generation: self.generations[i] };
            }
        }
        self.entities.push(Some(e));
        self.generations.push(0);
        Handle { index: self.entities.len() - 1, generation: 0 }
    }

    fn get(&self, h: Handle) -> Option<&Entity> {
        if self.generations[h.index] == h.generation {
            self.entities[h.index].as_ref()
        } else {
            None  // 旧句柄,entity 已死
        }
    }
}
```

每次复用槽位,generation 加 1。旧句柄的 generation 不匹配,返回 None——**不会错误访问别的 entity**。

**方案 3:Handle 代替裸 index**(解决跨函数引用)。
```rust
fn shoot_bullet(world: &mut World, shooter: Handle) -> Handle {
    if let Some(s) = world.get(shooter) {
        let pos = s.pos;  // copy 出来
        let vel = s.vel;
        // 不再借用 world
        world.spawn(Entity { pos, vel, kind: Bullet, ... })
    } else {
        panic!("shooter dead");
    }
}
```

把需要的数据 copy 出来,避免持续借用 world。Handle 是 `Copy`,可以随便传。

### 优点

阶段 2 解决了:
- O(n) 删除 → O(1)。
- use-after-free → generation 检查。
- 跨函数引用 → Handle(Copy)。

### 新问题(阶段 2 还没解决的)

阶段 1 的痛点 1(字段浪费)、痛点 2(遍历低效)**完全没解决**。

阶段 2 的 entity 仍然是一个"fat struct",包含所有字段。墙仍然有 hp / mana 字段。遍历仍然要 `if e.kind == Monster` 分支。

而且阶段 2 引入新问题:
- **每次 spawn 扫描空槽**:O(n)。可以加 free list 优化,但要维护 free list。
- **entity 内部字段不可单独借用**:`world.get(h).pos` 拿到 `&Entity`,从 `&Entity` 借 `&pos`,整个 entity 都被借。如果你想 `world.get(h1).pos += vel` 同时 `world.get(h2).pos += vel`,Rust 借用检查拒绝——两个可变借用。

阶段 2 是 HH 终态。Casey 后续 Phase 不再大改 entity 系统。**但工业 ECS 不满足**——继续演化。

## 阶段 3 · 组件分离

### 痛点:字段浪费 + 借用冲突

阶段 2 的 entity 是 fat struct,所有字段在一起。这导致:

1. **字段浪费**:墙不需要 hp / mana,但要付内存。
2. **借用冲突**:`fn update(&mut self, h: Handle)` 内部想 `self.get_mut(h).pos.x += 1; self.get_mut(h).hp -= 1;` —— 两次可变借用,Rust 拒绝。

### 方案:把字段拆成独立 struct

把"位置"、"速度"、"hp"等拆成独立 struct:

```rust
#[derive(Copy, Clone)]
struct Position(Vec2);

#[derive(Copy, Clone)]
struct Velocity(Vec2);

#[derive(Copy, Clone)]
struct Health(i32);

#[derive(Copy, Clone)]
struct Mana(i32);

struct World {
    positions: SparseSet<Position>,
    velocities: SparseSet<Velocity>,
    healths: SparseSet<Health>,
    manas: SparseSet<Mana>,
    generations: Vec<u32>,
}

// SparseSet:稀疏集合,entity_id → 组件
struct SparseSet<T> {
    data: Vec<Option<T>>,
}

impl<T> SparseSet<T> {
    fn insert(&mut self, entity: usize, value: T) {
        if self.data.len() <= entity {
            self.data.resize_with(entity + 1, || None);
        }
        self.data[entity] = Some(value);
    }

    fn get(&self, entity: usize) -> Option<&T> {
        self.data.get(entity).and_then(|x| x.as_ref())
    }

    fn get_mut(&mut self, entity: usize) -> Option<&mut T> {
        self.data.get_mut(entity).and_then(|x| x.as_mut())
    }

    fn remove(&mut self, entity: usize) {
        if let Some(slot) = self.data.get_mut(entity) {
            *slot = None;
        }
    }
}
```

Entity 不再是 fat struct,**变成"组件的集合"**。每个组件类型用独立的 SparseSet 存储。

```rust
let mut world = World { ... };
let player = world.spawn();
world.positions.insert(player, Position(Vec2(0, 0)));
world.velocities.insert(player, Velocity(Vec2(0, 0)));
world.healths.insert(player, Health(100));
world.manas.insert(player, Mana(50));

let wall = world.spawn();
world.positions.insert(wall, Position(Vec2(10, 0)));
// wall 不插入 healths / manas —— 不浪费内存!
```

### 优点

- **无字段浪费**:墙只占 Position(8 字节),不占 Health / Mana。
- **借用友好**:`fn update(world: &mut World, e: usize) { world.positions.get_mut(e).0.x += 1; world.healths.get_mut(e).0 -= 1; }` — 两个可变借用,但是不同 SparseSet,Rust 允许。
- **类型安全**:Position 和 Velocity 是不同类型,不会搞混。

### 新问题

- **遍历仍然慢**:SparseSet 是 `Vec<Option<T>>`,遍历时要检查 None。1000 个 entity 里 100 个有 Velocity,遍历 1000 个 SparseSet 槽位,900 次浪费。
- **内存不连续**:SparseSet 用 `Vec<Option<T>>`,Option 占额外空间(8-16 字节 discriminant)。1000 个 Position 占的不是 8KB,可能是 24KB。
- **组件访问模式不清晰**:你想"遍历所有有 Position + Velocity 的 entity",要写复杂逻辑:
  ```rust
  for i in 0..world.max_entity_id() {
      if let (Some(p), Some(v)) = (world.positions.get(i), world.velocities.get(i)) {
          // ...
      }
  }
  ```
  O(n) 遍历,n 是 entity 总数,不是"有 Position + Velocity 的"数。

阶段 3 解决了字段浪费,但**遍历性能反而下降**(SparseSet 比 fat struct 慢)。**工业 ECS 不能停在这里**。

## 阶段 4 · Structure of Arrays (SoA)

### 痛点:SparseSet 浪费 + 不连续

阶段 3 的 SparseSet 是 `Vec<Option<T>>`。每个槽位是 Option,有额外开销。组件存储不连续,cache 不友好。

具体表现:1000 个 entity,你想遍历所有 Position:
```rust
for i in 0..1000 {
    if let Some(p) = world.positions.get(i) {
        // ...
    }
}
```
- 每次访问 SparseSet 的 `data[i]`,如果 `data[i]` 是 None,浪费一次访问。
- 即便都是 Some,Option<T> 仍然有 padding(对齐)。

### 方案:为每个组件类型维护一个 dense Vec

```rust
struct World {
    // 所有"曾经存在的"entity,有些可能已死
    generations: Vec<u32>,
    alive: Vec<bool>,
    // 每个组件类型一个 dense Vec
    positions: Vec<Option<Position>>,
    velocities: Vec<Option<Velocity>>,
    healths: Vec<Option<Health>>,
    manas: Vec<Option<Mana>>,
}
```

这看起来和阶段 3 没区别,但关键变化:**每个组件是独立的 Vec**,而不是 SparseSet(包装 Vec<Option<T>>)。

更重要的是:**所有 Vec 长度 = generations 长度 = 最大 entity_id + 1**。entity_id 直接是 Vec 索引,**无 hash map 查找**。

```rust
impl World {
    fn spawn(&mut self) -> usize {
        let id = self.generations.len();
        self.generations.push(0);
        self.alive.push(true);
        self.positions.push(None);
        self.velocities.push(None);
        self.healths.push(None);
        self.manas.push(None);
        id
    }

    fn position(&self, e: usize) -> Option<&Position> {
        self.positions[e].as_ref()
    }
}
```

### 优点

- **简单**:entity_id 直接索引。
- **组件独立借用**:`world.positions` 和 `world.velocities` 是不同 Vec,可同时可变借用。

### 痛点(还在)

- **遍历仍然要 Option 检查**:即便用了 Vec<Option<T>>,遍历时还要 `if let Some(p) = ...`。
- **内存浪费**:`Option<Position>` 占 16 字节(Position 8 字节 + Option 的 None 标记 + padding),Position 实际只占 8 字节,**2 倍浪费**。

### 真正的 SoA:去掉 Option

工业 ECS 的 SoA **不用 Option**,而是维护一个 dense 数组,只存"有这个组件的"entity:

```rust
struct PositionStorage {
    // dense:连续存储所有有 Position 的 entity 的 Position
    data: Vec<Position>,
    // 反向映射:entity_id → data 中的索引(如果有的话)
    sparse: Vec<Option<usize>>,
    // 正向映射:data 索引 → entity_id
    entities: Vec<usize>,
}
```

这是 **SparseSet**(真正的工业术语,不是阶段 3 的简化版)的标准实现:
- `data`:dense 数组,连续存储。
- `sparse`:反向索引,entity → dense index。
- `entities`:正向索引,dense index → entity。

遍历有 Position 的 entity:
```rust
for i in 0..storage.data.len() {
    let pos = storage.data[i];  // 直接访问,无 Option 检查
    let entity = storage.entities[i];
    // ...
}
```

O(n),n 是"有 Position 的 entity 数",不是"总 entity 数"。**这是 SparseSet 的核心优势**。

### 优点

- **遍历快**:dense 数组,cache 友好。
- **无 Option 开销**:每个组件精确占自己的大小(Position 8 字节)。
- **遍历范围精确**:只遍历有该组件的 entity。

### 新问题

- **多组件查询复杂**:你想"遍历所有有 Position + Velocity 的 entity",Position 和 Velocity 各自的 SparseSet,要做交集:
  ```rust
  for i in 0..positions.data.len() {
      let entity = positions.entities[i];
      if let Some(&v_idx) = velocities.sparse.get(entity).and_then(|x| *x) {
          let pos = positions.data[i];
          let vel = velocities.data[v_idx];
          // ...
      }
  }
  ```
  每次访问 Velocity 都要 sparse 查找,**cache 不友好**。
- **组件添加 / 删除 O(n)**:dense 数组要维护,dense 删除要 swap-remove,并更新 sparse 和 entities 索引。
- **多个 SparseSet 之间没有 locality**:Position 在一个 Vec,Velocity 在另一个,内存不在一起。

阶段 4 解决了"单组件遍历"的性能,但"多组件查询"性能仍然差。**这就是 archetype ECS 的契机**。

## 阶段 5 · Archetype(按组件组合分组)

### 痛点:多组件查询不连续

阶段 4 的 SparseSet 在多组件查询时,每个组件都要 sparse 查找,cache 不友好。

具体场景:游戏里大部分 entity 是"Player"和"Monster",它们都有 `{Position, Velocity, Health}`。**这两种 entity 占总数 80%**。每次遍历"所有有 Position + Velocity 的 entity",SparseSet 要做大量 sparse 查找。

但如果**把所有 `{Position, Velocity, Health}` 的 entity 放在连续内存里**,遍历就极快——dense Position / Velocity / Health 数组并排,完美 cache 利用。

### 方案:按组件组合(archetype)分组

**Archetype = 一组 entity 的"组件签名"**。

```rust
// 组件 ID
#[derive(Copy, Clone, PartialEq, Eq, Hash)]
struct ComponentId(u32);

// 给每个组件类型分配 ID(编译时)
impl Position { const ID: ComponentId = ComponentId(0); }
impl Velocity { const ID: ComponentId = ComponentId(1); }
impl Health { const ID: ComponentId = ComponentId(2); }
impl Mana { const ID: ComponentId = ComponentId(3); }

// Archetype = 一组组件 ID
#[derive(Clone, PartialEq, Eq, Hash)]
struct ArchetypeSignature(Vec<ComponentId>);  // 排序后的组件 ID 列表

// 一个 Archetype 内部:每个组件类型一个 dense 数组
struct Archetype {
    signature: ArchetypeSignature,
    // entity 列表(archetype 内部的 entity ID)
    entities: Vec<usize>,  // entity_id 列表
    // 每个组件类型一个 column(连续 dense 数组)
    columns: HashMap<ComponentId, Box<dyn Column>>,
}

trait Column {
    fn as_any(&self) -> &dyn Any;
    fn as_any_mut(&mut self) -> &mut dyn Any;
    fn push(&mut self, value: Box<dyn Any>);
    fn remove(&mut self, idx: usize);
}

struct TypedColumn<T> {
    data: Vec<T>,
}

impl<T: 'static> Column for TypedColumn<T> {
    fn as_any(&self) -> &dyn Any { self }
    fn as_any_mut(&mut self) -> &mut dyn Any { self }
    fn push(&mut self, value: Box<dyn Any>) {
        self.data.push(*value.downcast::<T>().unwrap());
    }
    fn remove(&mut self, idx: usize) {
        self.data.swap_remove(idx);
    }
}

struct World {
    archetypes: Vec<Archetype>,
    // entity_id → (archetype_index, row_in_archetype)
    entity_locations: Vec<Option<(usize, usize)>>,
}
```

每个 entity 属于一个 archetype。archetype 内部,所有同 archetype 的 entity 的组件**连续存储**。

```rust
let player_archetype = world.get_or_create_archetype(&[Position::ID, Velocity::ID, Health::ID, Mana::ID]);
let wall_archetype = world.get_or_create_archetype(&[Position::ID]);

let player = world.spawn_in(player_archetype, ...);  // player 在 player_archetype 内
let wall = world.spawn_in(wall_archetype, ...);  // wall 在 wall_archetype 内

// 遍历所有有 Position + Velocity 的 entity
for arch in &world.archetypes {
    if !arch.signature.contains(Position::ID) || !arch.signature.contains(Velocity::ID) {
        continue;
    }
    let positions = arch.column::<Position>();
    let velocities = arch.column::<Velocity>();
    for i in 0..positions.len() {
        positions[i].0 += velocities[i].0 * dt;
    }
}
```

### 优点

- **dense + 连续**:同 archetype 内,所有 Position 连续,所有 Velocity 连续。
- **cache 友好**:遍历 Position 数组,完美 cache 利用。
- **无 sparse 查找**:archetype 内 column 直接索引。
- **遍历精确**:只遍历"满足查询条件"的 archetype。

### 真实性能对比

1000 个 entity,其中 800 个有 `{Position, Velocity}`,200 个只有 `{Position}`:

**阶段 4(SparseSet)**:
- 遍历 Position sparse set:1000 个 entity(包括 200 个无 Velocity 的)。
- 对每个 entity 查 Velocity sparse set:800 个命中,200 个 miss。
- 总操作:1000 + 1000 = 2000,cache miss 多。

**阶段 5(archetype)**:
- 找到"有 Position + Velocity"的 archetype(800 个 entity)。
- 找到"只有 Position"的 archetype(200 个 entity)—— 查询条件不满足,跳过。
- 遍历 800 个 entity,Position 和 Velocity 都 dense,完美 cache。
- 总操作:800,cache miss 几乎为 0。

**阶段 5 比阶段 4 快 5-10 倍**(实际 benchmark)。

### 新问题

- **组件添加 / 删除需要"移动 entity 到另一个 archetype"**。给一个 entity 加 Velocity,它从 `{Position}` archetype 移动到 `{Position, Velocity}` archetype。**这要 copy 所有组件到新 archetype**。
- **archetype 数量爆炸**:N 个组件类型,理论上有 2^N 种 archetype。N=10 时 1024 种。**大部分是空的**,但查找 archetype-by-signature 仍然要 hash。
- **动态类型擦除**:column 是 `Box<dyn Column>`,内部 `Box<dyn Any>`。每次访问组件要 downcast。**有运行时开销**。

阶段 5 解决了性能,但**类型安全性**降到了运行时(动态 downcast)。**Rust 不喜欢这样**——我们要编译时类型安全。

## 阶段 6 · Archetype + 系统调度(Bevy 风格)

### 痛点:动态类型 + 系统无明确接口

阶段 5 的 archetype 用 `Box<dyn Column>` 和 `Box<dyn Any>`,每次组件访问要 downcast。不仅慢,而且**类型不安全**——downcast 失败会 panic。

而且"系统"是什么不清楚。你想写 `fn update_positions(positions: &mut [Position], velocities: &[Velocity])`,但怎么从 world 取出这些切片?怎么并行调度多个系统?

### 方案:类型擦除的边界 + 系统 trait

Bevy 的方案:在 archetype 层面用类型擦除,**但 query API 是类型安全的**。

```rust
// Query:类型安全的组件查询
struct Query<A, B> {  // A, B 是组件类型
    _a: PhantomData<A>,
    _b: PhantomData<B>,
}

impl<A: Component, B: Component> Query<A, B> {
    fn iter<'a>(&'a self, world: &'a World) -> impl Iterator<Item = (&'a A, &'a B)> + 'a {
        world.archetypes.iter()
            .filter(|arch| arch.has::<A>() && arch.has::<B>())
            .flat_map(|arch| {
                let a_col = arch.column::<A>().unwrap();
                let b_col = arch.column::<B>().unwrap();
                a_col.iter().zip(b_col.iter()).map(|(a, b)| (a, b))
            })
    }
}

// 系统 trait
trait System {
    fn run(&mut self, world: &mut World);
}

// 函数 → System 的转换
impl<Fn, Out> System for Fn where Fn: FnMut(&mut World) + 'static {
    fn run(&mut self, world: &mut World) { self(world); }
}

// 实际 Bevy 用 macro / closure 复杂,这里简化
```

具体使用:
```rust
fn update_positions(mut query: Query<&mut Position, &Velocity>) {
    for (pos, vel) in query.iter() {
        pos.0 += vel.0 * dt;
    }
}

fn update_healths(mut query: Query<&mut Health>) {
    for hp in query.iter_mut() {
        hp.0 += 1;
    }
}

let mut app = App::new();
app.add_system(update_positions);
app.add_system(update_healths);
app.run();
```

`update_positions` 和 `update_healths` **可以并行运行**(无组件冲突——Position / Velocity vs Health)。

### 优点

- **类型安全**:Query<&mut Position, &Velocity> 是编译时类型安全,运行时无 downcast。
- **并行调度**:系统间的组件访问模式分析,无冲突系统并行。
- **声明式 API**:`add_system` 注册,框架自动调度。

### Bevy 实际架构(简化版)

```rust
struct World {
    archetypes: Vec<Archetype>,
    components: ComponentRegistry,
    systems: Vec<Box<dyn System>>,
    schedule: Schedule,
}

struct App {
    world: World,
}

impl App {
    fn add_system<F, Args>(&mut self, system: F)
    where F: IntoSystem<Args>,
    {
        // 把函数转成 System
        let system = system.into_system();
        self.world.systems.push(Box::new(system));
    }

    fn run(&mut self) {
        // 调度:分析每个系统的组件访问模式,分组并行
        let schedule = Schedule::build(&self.world.systems);
        schedule.run(&mut self.world);
    }
}

// IntoSystem trait:把闭包转成 System
trait IntoSystem<Args> {
    type System: System;
    fn into_system(self) -> Self::System;
}

// 为各种函数签名实现 IntoSystem
impl<A: Component, B: Component> IntoSystem<(Query<A, B>,)> for fn(Query<A, B>) {
    type System = ...;
    fn into_system(self) -> Self::System { ... }
}
```

实际 Bevy 用了 `SystemParam` trait 和大量 macro,把"任意函数签名"自动转 System。**这是 Bevy API 优雅的核心**。

### 调度细节

调度器分析每个系统的组件访问:
- `Query<&mut Position, &Velocity>`:可变访问 Position,不可变访问 Velocity。
- `Query<&mut Health>`:可变访问 Health。

冲突规则:
- 两个系统都**可变**访问同一组件 → 必须串行。
- 一个**可变**一个**不可变** → 必须串行。
- 两个都**不可变** → 可并行。
- 访问不同组件 → 可并行。

`update_positions` 和 `update_healths` 访问不同组件(Position/Velocity vs Health),**可并行**。

调度器构建 DAG(有向无环图),节点是系统,边是依赖。然后拓扑排序,无依赖的并行执行。

### 优点

- **多核自动利用**:调度器自动并行。
- **声明式**:你只声明每个系统的访问,框架自动调度。
- **类型安全**:编译时检查组件访问模式。

### 真实性能

Bevy benchmark(100K entity):
- 单线程:30 FPS。
- 多线程(8 核):180 FPS。

**6 倍提升**(不是 8 倍,因为有调度开销和共享数据)。

### 新问题

- **调度开销**:小系统(< 100μs)调度开销大于执行。**Bevy 用 "system batching" 缓解**。
- **冷启动慢**:第一次构建 schedule 要分析所有系统,O(N²)(N 是系统数)。
- **资源访问冲突**:全局资源(World、Asset Server)容易冲突,要小心设计。

阶段 6 是 Bevy 0.10+ 的核心架构。Unity DOTS、Unreal Mass 也是这个架构的变种。

## 阶段 7 · 顶级优化(bitset、查询编译、cache 局部性)

### 痛点:archetype 查询仍有开销

阶段 6 的 archetype 查询:
```rust
world.archetypes.iter()
    .filter(|arch| arch.has::<A>() && arch.has::<B>())
```

每次 filter 是 hash 查找 `has<A>()`。100 个 archetype,100 次 hash。**这是开销**。

而且 archetype 内部:`columns: HashMap<ComponentId, Box<dyn Column>>`,每次 column 访问是 hash 查找。**热路径上的 hash 查找,慢**。

### 方案 1:Bitset 签名

每个 archetype 的签名用一个 bitset 表示,而不是 `Vec<ComponentId>`:

```rust
const MAX_COMPONENTS: usize = 128;

#[derive(Copy, Clone, PartialEq, Eq, Hash)]
struct ArchetypeId(u32);

struct ArchetypeSignature(u128);  // 128 bit,支持 128 种组件

impl ArchetypeSignature {
    fn has(&self, component: ComponentId) -> bool {
        (self.0 & (1 << component.0)) != 0
    }

    fn contains(&self, other: &Self) -> bool {
        (self.0 & other.0) == other.0  // self 包含 other 的所有 bit
    }
}
```

查询"有 A + B 的 archetype":
```rust
let query_mask = ArchetypeSignature(A::BIT | B::BIT);
for arch in &world.archetypes {
    if arch.signature.contains(&query_mask) {
        // 匹配
    }
}
```

bitset 操作是 AND + 比较,**几纳秒**。比 hash 查找快 10 倍。

### 方案 2:查询编译(jit)

对于"反复运行的 query",Bevy / Flecs 会**缓存查询结果**:第一次运行 query,扫描所有 archetype,缓存匹配的 archetype ID 列表。后续运行直接用缓存。

```rust
struct QueryCache {
    signature: ArchetypeSignature,
    matched_archetypes: Vec<usize>,  // 匹配的 archetype 索引
}

impl QueryCache {
    fn iter<'a>(&'a mut self, world: &'a World) -> ... {
        // 增量更新:只检查新创建的 archetype
        let last_checked = self.last_checked;
        for i in last_checked..world.archetypes.len() {
            if world.archetypes[i].signature.contains(&self.signature) {
                self.matched_archetypes.push(i);
            }
        }
        self.last_checked = world.archetypes.len();
        // ...
    }
}
```

### 方案 3:Column 数组而非 HashMap

archetype 内部 column 用 `Vec<Box<dyn Column>>` 而不是 HashMap,**按 component_id 索引**(假设每个 archetype 内只有少量组件,直接数组):

```rust
struct Archetype {
    signature: ArchetypeSignature,
    // 用稀疏数组:component_id → 索引到 columns(只在 signature 中有的)
    component_to_column: Vec<Option<usize>>,  // 索引 0..MAX_COMPONENTS
    columns: Vec<Box<dyn Column>>,
    entity_ids: Vec<usize>,
}
```

`component_to_column[component_id]` 给出 column 索引,**O(1) 数组访问**,无 hash。

### 方案 4:SIMD 批量化

某些系统(物理、AI)可以 SIMD 批量处理 archetype 内的多个 entity:

```rust
// 标量版
for i in 0..positions.len() {
    positions[i].0 += velocities[i].0 * dt;
}

// SIMD 版(用 wide crate)
use wide::f32x4;
let dt_simd = f32x4::splat(dt);
for chunk in positions.chunks_exact_mut(4).zip(velocities.chunks_exact(4)) {
    let (p_chunk, v_chunk) = chunk;
    let p = f32x4::from_slice(p_chunk);  // 假设 Position 是 Vec2 简化为 f32
    let v = f32x4::from_slice(v_chunk);
    let new_p = p + v * dt_simd;
    new_p.copy_to_slice(p_chunk);
}
```

archetype 内的连续数组**完美 SIMD 友好**——对齐好、stride 已知。

### 方案 5:Batch 系统

小系统的调度开销占比大。Bevy 把多个小系统"batch"成一个大系统:

```rust
// 原本:调度 N 次系统,每次 O(scheduling) + O(work)
// batch:调度 1 次,内部顺序运行 N 个系统,O(scheduling) + N*O(work)
```

### 顶级 ECS 的性能数字

Flecs(C 语言 ECS)的 benchmark:
- 1M entity,简单 query:10ms。
- 1M entity,5 个系统并行:30ms。
- 1M entity,5 个系统 SIMD:15ms。

Bevy 0.13 类似数量级。

对比 HH 风格(阶段 2):
- 1M entity,简单遍历(稀疏数组 + Option):500ms。

**顶级 ECS 比 HH 风格快 30-50 倍**。

## 跨阶段对比

把 7 个阶段放在一张表上:

| 阶段 | 数据结构 | 删除 | use-after-free | 字段浪费 | 遍历性能 | 类型安全 |
|---|---|---|---|---|---|---|
| 1 朴素 struct + Vec | Vec<FatEntity> | O(n) | 有 bug | 严重 | 慢(if 分支) | 编译时 |
| 2 稀疏数组 + gen(HH) | Vec<Option<Entity>> | O(1) | 解决 | 严重 | 慢 | 编译时 |
| 3 组件分离(SparseSet) | 多个 SparseSet | O(1) | 解决 | 解决 | 中等 | 编译时 |
| 4 SoA | 多个 Vec | O(1) | 解决 | 解决 | 中等 | 编译时 |
| 5 Archetype | archetype + dense column | O(1) | 解决 | 解决 | 快 | 运行时(downcast) |
| 6 Archetype + 系统 | + 系统调度 | O(1) | 解决 | 解决 | 快 + 并行 | 编译时(Query) |
| 7 + bitset / cache / SIMD | + bitset 签名 / cache | O(1) | 解决 | 解决 | 极快 + 并行 | 编译时 |

演化路径:**先解决正确性(阶段 1-2),再解决性能(阶段 3-5),再解决易用性(阶段 6),最后极致优化(阶段 7)**。**这是所有复杂软件系统的演化规律**。

## Rust 生态的 ECS 比对

| 库 | 阶段 | 特点 |
|---|---|---|
| HH 风格(自己写) | 阶段 2 | 简单,适合小项目 |
| specs | 阶段 4-5 | Rust 早期 ECS,Amethyst 引擎用 |
| legion | 阶段 5-6 | archetype-based,后来合并到 Bevy |
| **bevy_ecs** | 阶段 6-7 | 工业级,Bevy 引擎核心 |
| **flecs** | 阶段 7(C 语言) | 最快,跨语言绑定 |
| **entitas**(C#) | 阶段 5-6 | Unity 早期 ECS |
| **Unity DOTS** | 阶段 6-7 | Unity 官方 ECS |
| **Unreal Mass** | 阶段 6-7 | Unreal 5 官方 ECS |

如果你做 Rust 游戏开发,**用 bevy_ecs 或 hecs**。不要自己写 ECS——除非为了学习。

## 实操:从 HH 风格迁移到 bevy_ecs

下面是把 HH 风格代码迁移到 bevy_ecs 的例子。

### HH 风格(阶段 2)

```rust
struct World {
    entities: Vec<Option<Entity>>,
    generations: Vec<u32>,
}

let mut world = World::new();
let player = world.spawn(Entity {
    pos: Vec2(0, 0),
    vel: Vec2(0, 0),
    hp: 100,
    kind: Player,
});
// 主循环
for e in &mut world.entities {
    if let Some(e) = e {
        if e.kind == Player || e.kind == Monster {
            e.pos += e.vel * dt;
        }
    }
}
```

### bevy_ecs 风格(阶段 6-7)

```rust
use bevy_ecs::prelude::*;

#[derive(Component)]
struct Position(Vec2);

#[derive(Component)]
struct Velocity(Vec2);

#[derive(Component)]
struct Health(i32);

#[derive(Component)]
struct Player;

#[derive(Component)]
struct Monster;

let mut world = World::new();
world.spawn((Position(Vec2(0, 0)), Velocity(Vec2(0, 0)), Health(100), Player));

// 系统:遍历所有有 Position + Velocity 的 entity(无论 Player 还是 Monster)
fn update_positions(mut query: Query<(&mut Position, &Velocity)>) {
    for (mut pos, vel) in &mut query {
        pos.0 += vel.0 * dt;
    }
}

// 调度
let mut schedule = Schedule::default();
schedule.add_systems(update_positions);
schedule.run(&mut world);
```

迁移要点:
1. Entity struct → 多个 Component(`#[derive(Component)]`)。
2. 全局 World → bevy_ecs 的 World(底层是 archetype)。
3. for 循环 → 系统(`fn` + `Query`)。
4. 主循环 → Schedule。

### 性能对比

100K entity:
- HH 风格(阶段 2):500ms 遍历。
- bevy_ecs(阶段 6-7):5ms 遍历,**100 倍**。

而且 bevy_ecs 自动并行(多核),HH 风格单线程。

## 什么时候用哪个阶段?

不是所有项目都需要顶级 ECS。**按项目规模选**:

- **小项目(< 1K entity,简单逻辑)**:阶段 1-2(HH 风格)够用。代码简单,易维护。
- **中等项目(1K-10K entity,中等复杂度)**:阶段 3-4(组件分离 + SoA)。性能足够,代码不复杂。
- **大项目(10K+ entity,复杂逻辑)**:阶段 5-6(archetype + 系统)。性能必要。
- **工业级项目(100K+ entity,极致优化)**:阶段 7(顶级优化)。或者直接用 Bevy / Flecs。

**不要过度工程**。Casey 在 HH 里用阶段 2 的方案,因为 HH 是教学项目,简单优先。**你的小项目可能用阶段 2 也够**。

## 学完之后

读完这篇文章,你应该能:

1. **看懂 HH Phase 2 的 entity 演化**(阶段 1-2)。
2. **看懂 Bevy / Unity DOTS / Unreal Mass 的源码**(阶段 5-7)。
3. **选择合适的 ECS 阶段**——不过度工程,不性能不足。
4. **手写阶段 1-4 的 ECS**——理解底层。
5. **使用 bevy_ecs / flecs / hecs**——工业级实现。

### 推荐延伸阅读

- **Bevy 源码**(github.com/bevyengine/bevy/crates/bevy_ecs):阶段 6-7 的完整工业级实现。
- **Flecs 源码**(github.com/SanderMertens/flecs):阶段 7 的 C 语言实现,极快。
- **Unity DOTS 文档**(docs.unity3d.com/Packages/com.unity.entities):阶段 6-7 的 C# 实现。
- **ECS FAQ**(github.com/SanderMertens/ecs_faq):Sander Mertens 写的 ECS 设计常见问题,**所有想做 ECS 的人都该读**。
- **ECS Back and Forth**(ajmmertens.medium.com):Sander Mertens 的 ECS 设计系列文章,深度极高。

### 实战项目建议

#### 项目 A:从零写阶段 1-5 ECS

从零实现 5 个阶段的 ECS,每个阶段做一个 benchmark。**这是巩固理解的最佳方式**。

时间预算:2-4 周。

#### 项目 B:把 HH 风格 ECS 升级到 archetype

把你 HH 项目里的 entity 系统(阶段 2)升级到 archetype(阶段 5-6)。**这是 HH 毕业后的"下一个项目"**。

时间预算:1-2 个月。

#### 项目 C:用 bevy_ecs 做一个小游戏

直接用 bevy_ecs 做一个简单游戏(俄罗斯方块 / 小行星)。**对比 HH 风格 vs Bevy 风格的开发体验**。

时间预算:2-4 周。

## 结语

ECS 演化的 7 个阶段,**不是"每个阶段都比上个阶段好",是"每个阶段解决特定问题"**。

- 阶段 1 解决"起步"——能用就行。
- 阶段 2 解决"正确性"——use-after-free。
- 阶段 3 解决"内存"——字段浪费。
- 阶段 4 解决"单组件遍历性能"——dense 数组。
- 阶段 5 解决"多组件查询性能"——archetype 分组。
- 阶段 6 解决"易用性 + 并行"——系统调度。
- 阶段 7 解决"极致性能"——bitset / cache / SIMD。

Casey 在 HH 里停在阶段 2,因为 HH 是教学项目——**简单优先,够用即可**。但工业级游戏不能停在阶段 2,**因为性能 + 工程化是商业需求**。

读完本文,你看任何 ECS 实现都能秒懂它在哪个阶段、为什么这样设计。**这是 ECS 世界的"上帝视角"**。

带着这个视角,去看 Bevy 源码、Unity DOTS 文档、Unreal Mass 教程。**你会发现它们都在这张地图上**。

下一站:打开 bevy 源码,从 `crates/bevy_ecs/src/archetype.rs` 开始读。
