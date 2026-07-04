
# Arena Allocator

> Phase 4 多处涉及 arena(Day 157 通用分配器、Day 158 asset ref count、Day 165 多线程 cache)。这篇 deep-dive 完整讲 arena allocator:bumpalo / typed-arena / generational arena,何时选 arena,何时选 general allocator。

## 0 · 什么是 arena allocator

Arena = **一次性分配、整体释放** 的内存区域。

普通分配器:

```rust
{
    let a = Box::new(1);
    let b = Box::new(2);
    let c = Box::new(3);
    // 每个 Box 单独 alloc / dealloc
}  // 3 次 free
```

Arena:

```rust
let arena = bumpalo::Bump::new();
{
    let _a = arena.alloc(1);
    let _b = arena.alloc(2);
    let _c = arena.alloc(3);
    // 都从 arena "bump pointer" 分配,极快
}  // 没有 free
drop(arena);  // 整体释放
```

arena 内部就是一个 `current_offset` 指针,alloc 时 offset += size,极快(~5 ns vs malloc ~150 ns)。代价:不 free 单个,只能整体释放。

## 1 · Arena 类型

### Bump Allocator(基础)

```rust
struct Bump {
    memory: *mut u8,
    size: usize,
    offset: usize,
}

impl Bump {
    fn alloc(&mut self, size: usize, align: usize) -> *mut u8 {
        let aligned = (self.offset + align - 1) & !(align - 1);
        if aligned + size > self.size { return null_mut(); }
        let ptr = unsafe { self.memory.add(aligned) };
        self.offset = aligned + size;
        ptr
    }

    fn reset(&mut self) {
        self.offset = 0;  // 整体重置,不 free
    }
}
```

每次 alloc 推进 offset。reset 时 offset = 0,所有之前的指针**都失效**(unsafe 借用)。

`bumpalo` crate 是工业实现。

### Typed Arena

`typed-arena` crate 限制 arena 只能放一种类型:

```rust
let arena = typed_arena::Arena::new();
let a = arena.insert(42);
let b = arena.insert(43);
// a 和 b 都是 &i32
```

类型统一让内存布局更紧凑(无 fragmentation),且 API 安全(返回 `&T` 而非裸指针)。

### Generational Arena

`generational_arena` / `slotmap` 提供"slot"分配,带 generation:

```rust
let mut arena = slotmap::SlotMap::new();
let k = arena.insert(42);
arena.remove(k);
let k2 = arena.insert(43);  // 复用 slot,generation 不同
// k 的 generation 已过期,使用 k 查不到(返回 None)
```

防 stale handle 误用。

## 2 · Arena 在游戏开发的应用

### Frame Arena

每帧分配,帧末重置:

```rust
struct Game {
    frame_arena: bumpalo::Bump,
}

impl Game {
    fn update(&mut self) {
        self.frame_arena.reset();  // 上帧数据丢弃

        // 这帧的临时分配
        let render_commands: Vec<&RenderCommand> = self.frame_arena.alloc_slice_fill(100, RenderCommand::default());
        // ...
    }
}
```

所有"这一帧需要,下一帧丢"的数据放 frame arena,无内存泄漏,极快。

### Scratch Arena

函数内临时:

```rust
fn compute_path(map: &Map, start: Vec2, end: Vec2, scratch: &Bump) -> Path {
    let visited: &mut [bool] = scratch.alloc_slice_fill_default(map.w * map.h);
    // 算法
    // 离开函数后,scratch 的这部分还在,但下次调用会复用
}
```

### Game Arena

整个游戏生命周期的 asset / entity:

```rust
struct Game {
    game_arena: bumpalo::Bump,  // 游戏结束才 drop
    // 所有 asset 指针都在 game_arena
}
```

## 3 · Arena vs General Allocator

| 维度 | Arena | General(malloc) |
|---|---|---|
| alloc 速度 | ~5 ns | ~150 ns |
| dealloc | 不做(reset) | 每次 |
| 碎片化 | 无 | 高 |
| 灵活性 | 低(必须整体释放) | 高 |
| 内存占用 | 高(reset 前全保留) | 实际用多少 |
| 适合 | 短生命周期 | 长生命周期混合 |

经验:**短生命周期用 arena,长生命周期用 general allocator**。

## 4 · bumpalo 详细用法

### 基础

```rust
use bumpalo::Bump;
use bumpalo::collections::String;

let bump = Bump::new();

let s = bumpalo::format!(in bump, "hello {}", 42);  // &str in arena
let v = bump.alloc_vec_with_capacity(100);  // Vec in arena
v.push(1);
v.push(2);

let mut arena_string = String::new_in(&bump);
arena_string.push_str("hello");
```

### 自定义类型

```rust
#[derive(Debug)]
struct Enemy {
    hp: i32,
    name: &'static str,
}

let e = bump.alloc(Enemy { hp: 100, name: "goblin" });
println!("{:?}", e);  // e: &Enemy
```

注意:arena 分配返回 `&T`,不是 `Box<T>`。借用规则仍生效——多个 `&Enemy` 共存 OK,`&mut` 独占。

### 在 collection 里

```rust
let bump = Bump::new();
let enemies: Vec<&Enemy> = (0..10).map(|_| bump.alloc(Enemy { hp: 100, name: "x" })).collect();
// Vec 在普通 heap,内容 &Enemy 在 arena
```

### Box in arena

```rust
let boxed_in_arena: Box<i32> = Box::new_in(42, &bump);
// Box 但分配在 arena
// drop 时仍然 nothing(arena 持有)
```

## 5 · Arena 的所有权挑战

Rust 的 ownership + arena 有冲突:

```rust
fn get_or_load(cache: &mut HashMap<u32, &Asset>, arena: &Bump, id: u32) -> &Asset {
    if !cache.contains_key(&id) {
        let a = arena.alloc(load_from_disk(id));
        cache.insert(id, a);
    }
    cache.get(&id).unwrap()
    // 错误!cache 借了 arena,但函数签名没体现
}
```

`&mut cache` 和 `&arena` 都借了 Asset 的 lifetime。函数返回的 `&Asset` 同时绑两个 lifetime,Rust 编译器难表达。

解决:

- 用 `<'a>` 显式 lifetime
- 或返回 arena 的引用,cache 改成 `&'a Asset` 关联
- 或用 `Rc<RefCell<>>` 绕过(慢)

```rust
fn get_or_load<'a>(cache: &mut HashMap<u32, &'a Asset>, arena: &'a Bump, id: u32) -> &'a Asset {
    if !cache.contains_key(&id) {
        let a: &'a Asset = arena.alloc(load_from_disk(id));
        cache.insert(id, a);
    }
    cache.get(&id).copied().unwrap()
}
```

## 6 /// Generational Arena 详解

`slotmap` / `generational_arena` 解决 stale handle:

```rust
use slotmap::SlotMap;

slotmap::new_key_type! { struct EntityKey; }

let mut entities: SlotMap<EntityKey, Entity> = SlotMap::new();
let k1 = entities.insert(Entity { hp: 100 });
entities.remove(k1);

let k2 = entities.insert(Entity { hp: 50 });  // 复用 k1 的 slot,但 generation 不同
// k1 失效
assert!(entities.get(k1).is_none());
assert!(entities.get(k2).is_some());
```

### 内部结构

```
slot[0] = { generation: 1, occupied: false }
slot[1] = { generation: 5, occupied: true, data: Entity { ... } }
...
```

key = `(slot_index, generation)`。remove 时 generation += 1,occupied = false。下次 insert 复用 slot,但 key.generation 必须匹配。

## 7 /// 何时不用 Arena

- 长生命周期对象(player entity 持续整个游戏)
- 对象大小差异巨大
- 需要 per-object drop(arena 整体 drop 时 T 的 destructor 不调用——`bumpalo::Box::new_in` 会,但 `alloc` 不会)

## 8 /// 资源

- bumpalo:https://github.com/fitzgen/bumpalo
- typed-arena:https://github.com/SimonSapin/rust-typed-arena
- slotmap:https://github.com/orlp/slotmap
- generational-arena:https://github.com/fitzgen/generational-arena

## 9 /// 练习

### Lv1

用 bumpalo 实现 frame arena:游戏每帧 reset,1000 个临时分配,30 分钟稳定。

### Lv2

用 typed-arena 实现简单 AST(抽象语法树):节点都分在 arena,引用互相连接。

### Lv3

用 slotmap 实现 entity system:EntityKey 替代裸 index,add / remove / lookup,验证 stale key 检测。

### Lv4

读 bumpalo 的 `alloc` 源码。看它如何处理对齐、growth、reset。提一个 doc PR。
