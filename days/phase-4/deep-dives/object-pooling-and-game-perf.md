---
phase: 4
title_en: "Object Pooling & Game Performance Patterns"
title_zh: "对象池与游戏性能模式"
type: deep-dive
difficulty: 4
duration: "3-4h"
domains: [game, rust, memory, system, performance]
prereqs: [memory-layout-for-cache, particle-systems-cpu, virtual-memory-and-allocators]
calibration: "对象池(object pooling)+ slot map(稳定句柄)+ 游戏性能模式"
---

# 对象池与游戏性能模式

> 你跟着 Handmade Hero 走到 Phase 4,刚把怪物 AI 做出来。怪物死亡时你 spawn 2000 个粒子做爆炸特效,粒子飞溅 0.8 秒后逐个 `drop`。下个怪物死,又是 2000 个。你以为这只粒子系统的开销,但 Tracy profiler 显示——你这 5 ms 的帧时间里,有 1.8 ms 花在 `malloc`/`free` 上,真正算粒子积分的代码只占 0.4 ms。你打开 `perf stat`,cache-misses 飙到 30%,因为每次 alloc 拿到的内存都不连续,粒子数据散落在堆里。这一篇讲清楚:**为什么"每帧分配/释放"是游戏性能的隐形杀手,object pooling 如何消灭它,以及为什么 Rust 里更地道的写法是 slot map——一种"稳定句柄 + 代际检查"的池,从根上杜绝 use-after-free**。读完你应该能解释:池什么时候该用、什么时候不该用;slot map 的 generation 字段如何阻止悬空句柄;为什么现代 ECS 在存储层已经替你做了大部分池化;以及如何用 Tracy 在自己的 HH 项目里定位并消灭一个真实的分配热点。

## 0 · 一个让你 profiler 变红的爆炸

让我们先把镜头对准那个让你帧率掉到 22 的爆炸。

你写了一段看起来很合理的代码。怪物 `health <= 0` 时,触发爆炸:循环 2000 次,每次 `Vec::push(Particle::new(...))`。0.8 秒后这批粒子逐个 `age >= lifetime`,你用 `Vec::retain(|p| p.age < p.lifetime)` 把死的剔掉。下一个怪物死,再来 2000 次 push。

这段代码有三个性能炸弹,一个比一个隐蔽:

第一颗,每次 `Particle::new` 都在堆上分配。你的 `Particle` 是 112 字节(见 `particle-systems-cpu.md` 第 1.2 节),2000 次分配 = 2000 次 `malloc`。`virtual-memory-and-allocators.md` 里讲过,即便是 jemalloc 这种 thread-local cache 的分配器,一次小对象 alloc 也在 20-50 ns,2000 次 = 40-100 μs,每秒 30 次爆炸累积 1.2-3 ms/秒。

第二颗,`Vec::retain` 触发 memmove。`retain` 线性扫描把保留的元素往前挪,2000 个粒子里 600 个死了就触发大约 600 次 112 字节的 `memcpy(Particle)`,散落在 vec 各处,每次都污染一条 cache line。

第三颗,最阴险——**heap fragmentation**。每次 `malloc` 拿到的内存位置不固定,2000 个粒子可能散落在 2000 个不同的 heap chunk 里。下一帧遍历它们做积分,cache line 今天命中这个 chunk 明天命中那个,没有空间局部性。`memory-layout-for-cache.md` 第 0 节那张表——L3 miss 代价 ~12 ns,RAM miss ~100 ns。2000 个粒子如果每个都 RAM miss,光等内存就 200 μs。

把这三颗加起来,一次爆炸的"开销税"大约 0.5-1 ms——但你 profiler 显示的是 1.8 ms,因为还有 `Vec` 内部的 reallocation(满了之后 2 倍扩容 + 全量复制)。

工业界的答案叫 **object pooling**(对象池):**预分配一块固定大小的内存,所有这类对象都从这块内存里取,死了的不释放、只标记"可复用",下次 spawn 直接覆盖它**。这把三颗炸弹同时拆掉——零 alloc、零 free、零 fragmentation,数据天然连续。今天这一篇就是讲这套模式,以及它在 Rust 里的地道实现(slot map)。

## 1 · 池的核心思想:椅子、咖啡馆、与"永不买新的"

池化的核心思想一句话就能讲完,但要真懂它,得先换个比喻。

想象你开了一家咖啡馆。客人来来去去。**朴素方案**:每个客人进门你跑去家具厂买一把新椅子(`malloc`),客人走你把椅子扛到垃圾场扔掉(`free`)。家具厂被你折腾死,椅子还要等配送(`mmap` 缺页),垃圾场还堆满旧椅子(fragmentation)。

**池化方案**:你开店那天预先买 200 把椅子,整齐排成一行(`Vec::with_capacity(200)`)。客人来你指给他一把空椅子坐下;客人走了你把椅子擦一下,标记"空"。下一个客人来直接坐这把空椅子。**永远不买新椅子,永远不扔椅子**。

这里"椅子"就是对象的内存 slot,"空"就是 dead,"坐着"就是 alive。关键洞察是:**对象的"生命周期"和它占用的"内存 slot 的生命周期"解耦了**。slot 永远存在(直到池被销毁),只是它里面装的内容会从一个对象换成另一个对象。对应到第 0 节那三颗炸弹:不买新椅子(零 alloc)、不扔椅子(零 free)、椅子永远在那 200 把的固定位置、访问模式可预测(零 fragmentation,cache 友好)。

**池的容量是你在游戏里愿意为这类对象设的"上限"**。200 把椅子满了,第 201 个客人怎么办?两种策略:要么拒绝(粒子被丢弃,玩家注意不到),要么"偷"——把最早进来还没走的客人请走(oldest-first eviction,适合"老粒子已经淡到看不见了"的场景)。游戏里多数粒子池选"拒绝",容量通常设得足够大(火焰效果 5000 把椅子,基本不会满)。这个"用固定内存上限换零分配开销"的 trade-off 就是池化的全部精髓——它不是免费的,你付出的是启动时一次性占用 N 个对象的内存,即使游戏大部分时间用不到这么多。但对短命对象来说,这个代价完全值得。

## 2 · 什么时候该池化,什么时候不该

池化是好东西,但**不是所有对象都该池化**——滥用池化是新手最常见的过度工程。判断信号要同时满足三个条件:

第一,**对象数量大**。一帧只 spawn 2 个对象,池不池化没区别(profiler 都看不见)。门槛大致是同时存活上百,或一秒 spawn/despawn 上千。

第二,**生命周期短**。对象活几帧到几秒,频繁出生死亡。活几分钟的对象(玩家角色、静态实体)一辈子只分配一次,池化省的那一次 alloc 完全可以忽略。

第三,**创建/销毁频率高**。短命但只在剧情触发时创建一次(过场动画特效),一年几回,池化不值得。必须是 hot loop 里(每帧或每几帧触发)才值得。

满足这三条的对象在游戏里有明确的几类:粒子(一团火 200 颗、爆炸 500 颗,`particle-systems-cpu.md` 整篇讲它)、投射物(机枪一秒 10 发,同屏几十到几百发)、网络包 buffer(服务器一秒收发上千个,池化的是 send/recv buffer 不是 packet 对象本身)、命令缓冲(每帧往 GPU 提交几十个 command buffer)、ECS entity 的存储 slot(Bevy 的 entity ID 本质就是 slot map key,后面会讲)。

反过来,**不该池化的对象**共同特征是生命周期长、数量少、创建频率低:玩家角色、配置文件解析结果、UI 窗口 widget。给这些对象做池化,你增加了一层"从池里取/还"的复杂度,profiler 看不到任何收益——典型的过早优化。

有一个**反直觉的情况**:有时候对象数量大、生命周期短,但你还是不该手动池化——因为框架已经替你池化了。现代 ECS(Bevy)的 component storage 内部就是一个池,你 spawn/despawn entity 实际上是在池里取/还 slot,不触发系统 `malloc`。手动再池化一层是 redundant 的。这就是为什么本文第 6 节会专门讲"pooling vs ECS"——你需要知道你站在哪一层。

判断的"启动条件"只有一条:**别凭直觉池化,凭 profiler 池化**。当你 Tracy(`phase-4/deep-dives/profiling-with-tracy.md`)看到 hot loop 里有 `malloc`/`free`/`drop` 占了 > 5% 帧时间,且这些分配是高频同类型对象,这就是池化的信号。在这之前,代码越简单越好。

## 3 · 池的设计:free-list 与双堆栈

讲完"为什么"和"什么时候",现在讲"怎么做"。我们从最朴素的 free-list 池开始,一步步推到工业级实现。

### 3.1 free-list:O(1) 取还的最朴素池

最直观的池设计是 **free-list**(空闲链表):你维护一个"哪些 slot 是空的"的链表,spawn 时从链表头取一个,kill 时把 slot 还回链表头。

```rust
struct Pool<T> {
    slots: Vec<T>,          // 预分配的所有 slot
    free_list: Vec<usize>,  // 空闲 slot 的索引(当栈用)
}

impl<T: Default + Clone> Pool<T> {
    fn new(capacity: usize) -> Self {
        Self {
            slots: vec![T::default(); capacity],
            // 初始所有 slot 都空闲,从后往前 push,这样 pop 拿到 0
            free_list: (0..capacity).rev().collect(),
        }
    }

    fn acquire(&mut self) -> Option<usize> {
        self.free_list.pop().map(|idx| idx)
    }

    fn release(&mut self, idx: usize) {
        // 调用方负责把 slots[idx] 重置成 default
        self.free_list.push(idx);
    }
}
```

`acquire` 和 `release` 都是 O(1)——`Vec::pop` 和 `Vec::push`(不触发扩容时)都是常数时间,这是池最关键的性能特征:**取和还都不进 allocator**。

但这个设计有个问题:`free_list` 告诉你"哪些 slot 是空的",却不告诉你"哪些是活的"。渲染时要遍历活的粒子,你没法只看 `free_list`。所以实践中,池通常还要维护一个**"alive 列表"**——所有活着 slot 的索引。这就引出了下一个设计。

### 3.2 双堆栈:把 alive 和 free 共用一个数组

`particle-systems-cpu.md` 第 2.3 节讲过一个工业级优化叫**双堆栈**(double stack),这里重新推导一遍,因为它正是 object pooling 的核心数据结构。观察一个事实:每个 slot 要么 alive 要么 free,一定是两者之一。所以 alive 集合和 free 集合互补,可以用**同一个数组**表达——前 `alive_count` 个元素是 alive 索引,后面是 free 索引。

```rust
struct Pool<T> {
    slots: Vec<T>,
    indices: Vec<usize>,   // 前 alive_count 是 alive,后面是 free
    alive_count: usize,
}

impl<T: Default + Clone> Pool<T> {
    fn new(capacity: usize) -> Self {
        Self {
            slots: vec![T::default(); capacity],
            indices: (0..capacity).collect(),  // 初始全 free
            alive_count: 0,
        }
    }

    fn acquire(&mut self) -> Option<usize> {
        if self.alive_count >= self.slots.len() {
            return None;  // 池满了
        }
        let idx = self.indices[self.alive_count];
        self.alive_count += 1;
        Some(idx)
    }

    fn release(&mut self, slot_in_alive: usize) {
        // slot_in_alive 是该 slot 在 alive 区的位置(不是 slots 数组的 idx!)
        // 把它和 alive 区最后一个交换,然后收缩 alive_count
        let last = self.alive_count - 1;
        self.indices.swap(slot_in_alive, last);
        self.alive_count -= 1;
    }

    fn alive_indices(&self) -> &[usize] {
        &self.indices[..self.alive_count]
    }
}
```

精髓在于 `release`:用 `swap` 把要释放的 slot 和 alive 区末尾交换,然后 `alive_count -= 1`。这个 swap 是 O(1)(两个 `usize` 的交换),比起"删除中间元素导致整体前移"的 O(N) memmove 快了 N 倍。代价是 alive 列表顺序会被打乱——如果你需要按 spawn 顺序或距离镜头遍历,得在遍历前单独排序。但 update 阶段(积分位置、应用力)不在乎顺序,所以这个 trade-off 在 update-heavy 场景里净赚。这个设计就是 Unreal Niagara 的 CPU 粒子池用的(见 `particle-systems-cpu.md` 第 2.5 节),10 万粒子的 update + kill 在它上面跑 < 0.3 ms。

### 3.3 满了怎么办:reject vs steal

池满了,新来的对象怎么办?两种策略:

**Reject(拒绝)**:直接返回 `None`,新对象被丢弃。粒子系统几乎都用这个——多一颗少一颗火星玩家根本看不出。但代码上要小心:`acquire` 返回 `None` 时,**不要 panic**,要静默 skip。Bevy 的 `Reserve` 模式里 spawn 失败也是这个语义。

**Steal(偷)**:把池里"最老"或"最低优先级"的对象踢出去,把它的 slot 让给新对象。这适合"必须显示这个新对象"的场景——比如 UI damage number(伤害飘字),你不可能因为池满了就丢掉玩家的暴击数字。steal 的实现就是遍历 alive 列表找 `age` 最大的,`release` 它,再 `acquire` 给新对象。

steal 是 O(N) 的——要遍历找最老的。如果池很大(10 万粒子),这个 O(N) 你承受不起。所以 steal 一般只用在**小池子**(几十到几百个 slot),比如 UI damage number 池上限 50,steal 一次扫 50 个,完全可以。工业级实现会把"年龄"维护成一个 priority queue 让 steal 变 O(log N),但 99% 的场景小池子 + 线性扫描就够了,别过度工程。

## 4 · Slot Map:Rust 地道的"稳定句柄"池

到这里你可能会想:前面的 `Pool<T>` 用 `usize` 索引 slot,这有什么问题?为什么 Rust 圈谈起池化总提 "slot map"?

问题在 `usize` 索引上——它**不稳定**。考虑这个场景:

```
1. 你 acquire 了 slot 5,拿到 idx=5
2. 你把 idx=5 存到某个"跟踪粒子"的数据结构里(比如特效系统引用这颗粒子)
3. 这颗粒子死了,你 release,slot 5 进入 free list
4. 另一个新粒子 acquire,复用了 slot 5
5. 那个"跟踪粒子"的数据结构还在用 idx=5 —— 它现在指向新粒子!
```

这就是经典的 **use-after-free / aliasing bug**。在 C 里它是 segfault 的温床;在 Rust 里 borrow checker 通常能挡住"持有 `&mut T` 的同时 release"这种直接错误,但挡不住"持有 `usize` 索引的语义错误"——`usize` 只是数字,borrow checker 不知道它代表"曾经有效的 slot"。

slot map 解决的就是这个问题。它给你的不是裸 `usize` 索引,而是一个 **Key**,Key 里有两部分:`index`(slot 在数组里的位置)+ `generation`(这个 slot 当前是"第几代"内容)。

```rust
#[derive(Clone, Copy, PartialEq, Eq, Hash)]
struct SlotKey {
    index: u32,       // slot 在 slots 数组里的位置
    generation: u32,  // 这个 slot 的"版本号"
}
```

每次 release 一个 slot,它的 `generation` 加 1。下次 acquire 复用这个 slot 时,新拿到的 Key 是 `{index, generation+1}`。如果你手里有个老 Key `{index, generation}`,你去查 slot map——它发现 slot 当前 generation 是 `generation+1`,**不匹配**,返回 `None`。这就安全地报告了"你拿的是过期句柄"。

来看核心实现(`get_mut` 是 `get` 的镜像,省略):

```rust
struct Slot<T> {
    value: Option<T>,     // None 表示空闲
    generation: u32,
}

pub struct SlotMap<T> {
    slots: Vec<Slot<T>>,
    free_list: Vec<u32>,  // 空闲 slot 的 index
}

impl<T> SlotMap<T> {
    pub fn with_capacity(capacity: usize) -> Self {
        Self {
            slots: (0..capacity).map(|_| Slot { value: None, generation: 0 }).collect(),
            free_list: (0..capacity as u32).rev().collect(),
        }
    }

    pub fn insert(&mut self, value: T) -> Option<SlotKey> {
        let idx = self.free_list.pop()?;
        let slot = &mut self.slots[idx as usize];
        slot.value = Some(value);
        Some(SlotKey { index: idx, generation: slot.generation })
    }

    pub fn get(&self, key: SlotKey) -> Option<&T> {
        let slot = self.slots.get(key.index as usize)?;
        if slot.generation != key.generation { return None; }  // 关键:代际检查
        slot.value.as_ref()
    }

    pub fn remove(&mut self, key: SlotKey) -> Option<T> {
        let slot = self.slots.get_mut(key.index as usize)?;
        if slot.generation != key.generation { return None; }
        let value = slot.value.take()?;
        slot.generation = slot.generation.wrapping_add(1);  // 灵魂:代际 +1
        self.free_list.push(key.index);
        Some(value)
    }
}
```

注意 `remove` 里这一行:`slot.generation = slot.generation.wrapping_add(1)`。这是 slot map 的灵魂——**每次回收 slot,generation 加 1**。这意味着即使 slot 被复用了 40 亿次(`u32::MAX`),也只是 wrapping 回到 0,不会有内存不安全(虽然理论上可能 generation 撞回原值导致 stale key 误判,但 `u32` 范围下需要这个 slot 被复用 40 亿次,实际游戏跑一千年也跑不到)。

这个设计的妙处在于:**它把"句柄是否有效"的检查从"调用方纪律"变成了"数据结构的内置保证"**。你不可能 use-after-free,因为 stale key 永远返回 `None`。你不可能 aliasing,因为同一个 slot 同时只能有一个有效的 generation。这是 Rust 哲学的体现——把不变量(invariant)编码进类型系统,让错误在编译期或运行时被早期检测,而不是在生产环境里 segfault。

### 4.1 SlotMap 在游戏里的应用:ECS entity ID

slot map 不只是粒子池的工具——它就是 **ECS entity ID 的实现方式**。Bevy 的 `Entity` 类型定义大致是:

```rust
// bevy_ecs/src/entity.rs(简化)
#[derive(Clone, Copy, PartialEq, Eq, Hash)]
pub struct Entity {
    index: u32,        // slot 位置
    generation: u32,   // 代际
}
```

这就是 `SlotKey`。Bevy 的 `Entities` 结构内部就是一个 slot map:`world.spawn(...)` 拿到 `Entity`(slot map key),`world.despawn(entity)` 是 `slot_map.remove(key)`,`world.get::<Position>(entity)` 内部就是代际检查挡住"访问已销毁实体"。这就是为什么 ECS 的 entity 句柄是"稳定的"——你可以把 `Entity` 存在任意地方(父实体的 children 列表、AI 的 target 引用、网络的 entity map),即使实体后来被销毁、slot 被复用,老句柄也不会误指向新实体,而是被代际检查挡住返回空。这是 ECS 设计的核心 safety 保证,也是为什么 ECS 不直接用 `usize` 索引而是用包装类型。`phase-2/deep-dives/entity-system.md` 讲了 entity 的语义,但"为什么 entity ID 长这样"的答案是 slot map——entity 的"分配/回收/引用"本质上就是 object pooling + generational index,没有别的魔法。

### 4.2 性能与生态

slot map 比 free-list 多的开销是:每次 `get`/`remove` 多一次 `u32` 比较(几个纳秒,可忽略),每个 slot 多 4 字节存 generation(10 万粒子 = 多 400 KB)。对极致 cache-sensitive 的代码,这 400 KB 可以用 hot/cold split 隔离——把 generation 放到 cold 数组,不污染 update 循环的 cache(同 `particle-systems-cpu.md` 第 9 节的思路)。

实践中 slot map 的开销对 99% 的池化场景都不是瓶颈,它的 safety 收益远超性能成本。Rust 圈有成熟的 `slotmap` crate(作者 Yessin Jajati),就是这一节的实现加一些优化(把 generation 和 value pack 在一起,用 `NonNull` 避免 `Option<T>` 的标签开销)。生产代码应该直接用它:

```rust
use slotmap::{SlotMap, new_key_type};

new_key_type! { struct ParticleKey; }  // 类型安全的 key

let mut particles: SlotMap<ParticleKey, Particle> = SlotMap::with_capacity(10_000);
let k1: ParticleKey = particles.insert(Particle::new(...));
particles.remove(k1);          // 现在 k1 过期
particles.get(k1);             // 返回 None —— 安全!
```

`new_key_type!` 宏生成一个全新的 key 类型,这样你不会把 `ParticleKey` 误用到 `ProjectileKey` 的池上——又是 Rust 类型系统替你挡一类 bug。

## 5 · Cache-Friendly 池:把池子和 SoA 接起来

到这里你有一个池,但池里的对象布局可能还是 AoS(Array of Structs)——`Vec<Particle>`,每个 `Particle` 112 字节紧挨着下一个。`memory-layout-for-cache.md` 第 3 节已经详细讲了 AoS vs SoA 的对比,这里我们只讲"池化和 SoA 怎么结合"。

问题在于:前面写的 `Pool<T>` 用 `Vec<T>` 存 slot,这是天生的 AoS。如果你的 update 循环只访问 `position` 和 `velocity`(24 字节),但每个 `Particle` 是 112 字节,那你每读一条 cache line(64 字节)只用了不到一半——剩下的是 color、size、rotation 等"渲染才用"的字段,update 时是纯浪费。

把池改成 SoA 的核心思路:**slot 不再是单个 `T`,而是把 `T` 的每个字段拆成独立的数组**。slot 的"索引"指向所有数组的同一个下标。

```rust
struct ParticlePoolSoA {
    // Hot(update 频繁访问,紧密相邻)
    positions: Vec<[f32; 3]>,
    velocities: Vec<[f32; 3]>,
    ages: Vec<f32>,
    lifetimes: Vec<f32>,
    // Cold(只渲染时访问)
    colors: Vec<[f32; 4]>,
    sizes: Vec<f32>,
    rotations: Vec<f32>,
    // 索引管理(双堆栈)
    indices: Vec<u32>,       // 前 alive_count 个是 alive
    alive_count: usize,
}
```

`spawn` 从 `indices[alive_count]` 取一个 slot,往 7 个数组各自的对应下标写值;`update` 遍历 `indices[0..alive_count]`,对每个 idx 做积分,死的 swap 到末尾、`alive_count -= 1`。完整实现见 `particle-systems-cpu.md` 第 10 节的 mini system——那里的 `ParticleSystem` 就是本节这个 SoA 池。把 `Vec<Particle>` 拆成 7 个独立数组后,update 循环只访问 `positions` 和 `velocities` 这两个连续数组,prefetcher 友好,在 10 万粒子上从 1.2 ms 降到 0.28 ms(快 4 倍,数据见该篇第 9.2 节)。

这里要指出一个 `particle-systems-cpu.md` 没强调的细节:**indirect addressing 的代价**。即使 alive 列表 `indices[0..alive_count]` 是连续的,`indices[i]` 指向的 `positions[indices[i]]` 可能跳——这是双堆栈设计的代价。极致 cache-friendly 的设计是完全避免 indirect addressing,让 alive 粒子的数据物理上紧挨着。两种做法:**compact-on-update**(update 时把活的"压"到数组前部,代价是 O(N) memmove,但 memmove 是连续大块拷贝、SIMD 友好,比随机访问快);**bitmask + branchless skip**(用 `alive_mask: Vec<bool>`,数据物理位置不变但要扫整个数组包括死的 slot,分支预测失败时反而是 trap)。`particle-systems-cpu.md` 第 2.4 节的 `FixedPool` 是 bitmask 思路的极端版,Niagara 的 swap-remove 是 compact 思路的轻量版。

工业引擎多数用 **compact-on-update** 的变种。`particle-systems-cpu.md` 第 2.4 节那个"FixedPool"是 bitmask 思路的极端版,适合"slot 死亡率低"的场景;Niagara 的 swap-remove 是 compact 思路的轻量版(只 swap 不全 compact)。

这就是为什么 `ecs-data-layout.md` 那一篇要单独讨论 archetype 内部的存储——ECS 的 component storage 本质就是 "slot map 的 key + SoA + compact" 三件套。Bevy 的 `BlobVec` 在 archetype 内部就是这么干的。读完这一节再看 ECS 的存储代码,你会发现它没有发明新东西,只是把这一节的模式推广到"任意 component 集合"。

## 6 · Pooling vs ECS:你到底站在哪一层

这一节解答一个常见困惑:既然 ECS 已经替我做池化了,我还需要自己写池吗?

答案是**分情况**。我们要分清两个层次:

**存储层(storage layer)**。ECS 的 component storage,内部就是池——`phase-5/deep-dives/ecs-data-layout.md` 详细讲了 bevy 的 `Table` / `SparseSet` 内部怎么用 contiguous 数组 + slot 索引 + 代际 entity ID。**如果你的对象是 ECS entity,池化在存储层已经做了,你不要手动再池化一层**。你 `world.spawn(...)` 拿到的 `Entity` 就是 slot map key,`world.despawn(...)` 就是把 slot 还回池——没有系统 `malloc`/`free` 发生(除非 archetype table 第一次扩容,那是 amortized 的)。

**逻辑层(logic layer)**。有些对象不是 ECS entity——它们是引擎内部的"资源"或"缓冲区":GPU command buffer 池(Vulkan 的 `VkCommandBuffer` 显式池化,从 `CommandPool` acquire 用完 recycle)、网络包 buffer 池(服务器收到 UDP packet,处理完 buffer 还回池)、资产引用池(Texture/Mesh 加载卸载频繁)、线程池(`rayon` 内部的 worker 池不是每来任务就 `thread::spawn`)。这些都不是 ECS entity,池化你得自己做,`slotmap` crate 是标准工具。

更微妙的情形:**ECS entity 是池化的,但你 spawn/despawn 的频率太高,ECS 的 entity 分配/回收开销仍然显著**。`particle-systems-cpu.md` 第 0 节讲过这个——Bevy 给每个粒子挂 entity + 5 个 component,一秒 spawn/despawn 15 万次,光 archetype table 维护就 30-75 ms。这就是为什么**粒子系统通常绕过 ECS,自己写一套池**。粒子是"数量极大、单体极简、生命周期极短"的特殊对象,ECS 的通用开销对它太重。

判断流程:

1. 你的对象是 ECS entity 吗?是 → ECS 已经池化,你别手动池化。
2. 你的对象是引擎内部资源/缓冲区吗?是 → 用 `slotmap` crate 自己池化。
3. 你的对象是大批量短命的"批次"对象(粒子、顶点、像素)?是 → 绕过通用池,写专用的 SoA 池(像 `particle-systems-cpu.md` 那样)。

这就是为什么本篇和 `particle-systems-cpu.md` 是互补的:`particle-systems-cpu.md` 讲的是"专用 SoA 粒子池"的极致优化,本篇讲的是"通用 slot map 池"的 pattern。两者解决不同层次的问题,游戏引擎两者都用。

## 7 · 生产现实:测了再池化

读完前面六节你可能跃跃欲试,想把项目里所有 `Vec::push` 都换成池。**慢着**——过早池化是真实存在的陷阱,有三个面:

第一,**代码复杂度**。一段简单的 `Vec::push` / `Vec::retain` 变成 `pool.acquire` / `pool.release` + alive 列表管理 + 满了的处理策略,代码量翻倍,bug 面积也翻倍(常见的池化 bug:release 之后还访问 slot、忘记 reset slot 内容导致新对象看到老对象的脏数据、alive 列表和 free list 不一致导致 slot 凭空消失)。

第二,**可能反而变慢**。如果对象数量不大(同时只活 20 个),`Vec::push` 比手写池更快——Rust 标准库的 `Vec::push` 在不扩容时是 5-10 ns 的指令,你的 `pool.acquire` 走 free-list pop 至少也是这个量级,但多了一层间接。对小规模对象,简单 `Vec` 经常赢。

第三,**内存常驻**。10 万粒子的池子 = 11.2 MB 始终占用,即使这帧一个粒子都没 spawn。对内存紧张的设备(Switch 4 GB、手机 2-3 GB 可用),这是真实成本——`Vec` 可以 `shrink_to_fit` 释放空闲内存,池子不能。

那么到底什么时候池化?**让 profiler 决定,不要让直觉决定**。流程是:用 Tracy(`phase-4/deep-dives/profiling-with-tracy.md`)标记 hot loop,看 `malloc`/`free`/`drop` 占了多少帧时间——如果 < 2%,别池化,代码保持简单;如果 > 5%,在 Tracy 的 memory profiler 里定位是哪类对象在高频分配,把**那一类**对象池化(profiler 点名的才池化,不要"顺手"池化别的),然后重新 profile 确认那 5% 真的消失且 cache-miss 率下降,最后写测试验证 slot 复用后新对象看不到老对象的脏数据。

这个流程的本质是:**池化是优化,优化必须有可测量的收益才做**。现代 CPU 和 allocator 比你想象的聪明得多,jemalloc 的 thread-local cache 让小对象 alloc 几乎免费,直到你 alloc 的频率高到打穿 cache。在 Tracy 里用 `ZoneScopedN("spawn_particle")` 标记 spawn 函数,如果这个 zone 一帧内被调用 5000 次且累积时间 > 1 ms,这才是池化的明确信号。Tracy 的 memory tracking (`TracyAlloc`/`TracyFree`) 还能可视化 heap 增长曲线——健康的项目曲线应该是"启动后平台不动",如果每次战斗曲线锯齿状波动,那就是 alloc/free churn,池化的目标靶子。

## 8 · 在你 HH 项目里动手(做中学红线)

这一节给你一个"动手"清单,把本篇所有概念落到 Handmade Hero 项目里,这是 Phase 4 的红线任务。流程是:**profile 找热点 → 用 slot map 池替换 → re-profile 验证收益 → 写测试验证 correctness**。

**步骤 1-3:profile,建立 baseline**。先接 Tracy(`phase-4/deep-dives/profiling-with-tracy.md` 有完整指南,最低限度是 main loop 加 `frame_mark`、每个 system 加 `ZoneScoped`)。在怪物死亡时触发一次大爆炸——循环 spawn 1500 个粒子(用 Phase 3 的简单粒子系统,如果还没有,先用 `Vec<Particle>` 的朴素版本)。在 spawn 加 `ZoneScopedN("particle_spawn")`,update 加 `ZoneScopedN("particle_update")`。打开 Tracy 跑几次爆炸,记下:`particle_spawn` 一帧调用次数和累积时间、memory view 的 heap 曲线是否锯齿状、`Vec::retain` 占多少。这是 baseline。

**步骤 4:实现一个 slot map 池**。推荐用 `slotmap` crate(生产代码就该用现成库),接到你的粒子系统:

```rust
use slotmap::{SlotMap, new_key_type};

new_key_type! { pub struct ParticleKey; }

pub struct ParticleSystem {
    slots: SlotMap<ParticleKey, Particle>,
    alive: Vec<ParticleKey>,  // 句柄列表,不是数据本身
}

impl ParticleSystem {
    pub fn with_capacity(cap: usize) -> Self {
        Self { slots: SlotMap::with_capacity(cap), alive: Vec::with_capacity(cap) }
    }

    pub fn spawn(&mut self, p: Particle) -> Option<ParticleKey> {
        let key = self.slots.insert(p)?;
        self.alive.push(key);
        Some(key)
    }

    pub fn update(&mut self, dt: f32, gravity: [f32; 3]) {
        let mut write = 0;
        for read in 0..self.alive.len() {
            let key = self.alive[read];
            // 代际检查:get_mut 返回 None 说明 key 过期 —— slot map 让我们安全
            let p = match self.slots.get_mut(key) { Some(p) => p, None => continue };
            p.velocity[0] += gravity[0] * dt;
            p.velocity[1] += gravity[1] * dt;
            p.velocity[2] += gravity[2] * dt;
            p.position[0] += p.velocity[0] * dt;
            p.position[1] += p.velocity[1] * dt;
            p.position[2] += p.velocity[2] * dt;
            p.age += dt;
            if p.age < p.lifetime {
                self.alive[write] = key;
                write += 1;
            } else {
                self.slots.remove(key);  // 回收到 slot map 的 free list
            }
        }
        self.alive.truncate(write);
    }
}
```

`alive: Vec<ParticleKey>` 是句柄列表不是数据本身,update 时数据不被反复移动。死的 key 调 `slots.remove(key)` 把 slot 还回 free list。需要遍历活粒子做渲染时,用 `alive.iter().filter_map(|&k| slots.get(k))`——代际检查替你挡住任何外部 remove 造成的 stale key。

**步骤 5:re-profile,对比 baseline**。让游戏跑和前面完全相同的场景。你应该看到:`particle_spawn` zone 基本消失(spawn 现在是 `slot_map.insert`,不走系统 malloc);memory view 的 heap 曲线变平(池子启动时一次分配,之后不再 grow);`perf stat -e cache-misses` 的 cache-miss 率下降(slot map 内部是 contiguous `Vec<Slot<T>>`,比散落的 heap chunk 友好)。spawn 时间应该从毫秒级降到微秒级。

**步骤 6:验证 correctness**。slot map 的卖点是"代际检查挡住 stale key",写一个测试:

```rust
#[test]
fn stale_key_returns_none() {
    let mut pool = ParticleSystem::with_capacity(100);
    let k1 = pool.spawn(Particle::default()).unwrap();
    // 模拟 k1 死亡
    pool.slots.remove(k1);
    // 现在 k1 应该 get 不到
    assert!(pool.slots.get(k1).is_none());
    // spawn 一个新粒子,可能复用 k1 的 slot
    let k2 = pool.spawn(Particle::default()).unwrap();
    // k1 仍然无效(k1 的 generation 老于当前 slot 的 generation)
    assert!(pool.slots.get(k1).is_none());
    // k2 有效
    assert!(pool.slots.get(k2).is_some());
}
```

这个测试通过,你就证明了自己的实现没有 use-after-free bug。如果失败,说明你忘了在 remove 时 increment generation——回去检查第 4 节的代码。

**步骤 7(进阶):SoA 化**。如果 profile 显示 update 还是慢(10 万级粒子),把 `SlotMap<ParticleKey, Particle>` 改成第 5 节的 `ParticlePoolSoA`,trade-off 是丢掉"任意 key 类型"的通用性,换来 cache 友好。`particle-systems-cpu.md` 第 9 节有完整代码。

完成这 7 步,你就把本篇所有概念实战了一遍:从 profiler 定位、到 slot map 实现、到代际 safety 验证、到 SoA 进阶——**用工具定位性能问题,用数据结构解决它,用测试保证正确性**,这是 Phase 4 结业时你应该具备的能力。

## 9 · 练习

### Lv1

写一个 `Pool<T>` 用 free-list(本篇第 3.1 节),T 是 `String`。capacity 1000。循环 100 万次:`acquire` 一个 String、修改它、`release`。对比同样循环用 `String::new()` + 立即 `drop` 的时间。期望看到池化版本快 2-5 倍。

### Lv2

把 Lv1 的 `Pool<T>` 改成 slot map(加 generation)。写一个测试:acquire 一个 key,release 它,再 acquire 一个新 key(可能复用同一个 slot)。验证旧 key `get` 返回 `None`,新 key 返回 `Some`。这是 correctness 测试,不是 perf 测试。

### Lv3

在你 HH 项目里完成第 8 节的 7 步。提交一个 Tracy 截图,展示池化前后 spawn zone 的对比(池化前 zone 一片红,池化后基本消失)。再提交 `perf stat` 的 cache-misses 对比。

### Lv4

(进阶,选做)实现一个**多线程友好的池**:用 `Mutex<SlotMap<Key, T>>` 包一层,允许多个线程同时 acquire/release。benchmark 4 线程并发 acquire 100 万次,看锁竞争多大。然后改用 shard 池(每个线程一个独立 SlotMap,避免锁),benchmark 提速多少。思考:这种 shard 设计牺牲了什么?(提示:全局 key 不再是单个 slot map 的 key,需要带上 shard id)

## 10 · 延伸阅读

外部稳定 URL:

- slotmap crate 文档(本篇第 4 节实现来源):https://docs.rs/slotmap
- Sean Middleditch "Generational Indices"(slot map 思想):https://medium.com/@seanchen_/generational-indices-8a3d04e1e3a6
- Andre Weissflog "Handle-based resource management"(floooh 博客,游戏资源池化):https://floooh.github.io/2018/06/17/handles.html
- Niklas Frykholm "Managing Decoupling Part 4 — The ID Lookup Table"(BitSquid):http://t-machine.org/index.php/2014/02/24/decoupling-objects-with-an-id-lookup-table/
- Mike Acton "Data-Oriented Design"(CppCon 2014):https://www.youtube.com/watch?v=rX0ItVEVjA4
- Tracy profiler 官方 manual:https://github.com/wolfpld/tracy/blob/master/manual/tracy.pdf

真实开源源码:

- bevy_ecs 的 `Entities`(slot map 实现):https://github.com/bevyengine/bevy/blob/main/crates/bevy_ecs/src/entity.rs
- bevy_ecs 的 `BlobVec`(archetype 内部 SoA 池):https://github.com/bevyengine/bevy/blob/main/crates/bevy_ecs/src/storage/blob_vec.rs
- `slotmap` crate 源码:https://github.com/slotmap/slotmap
- Unreal Niagara CPU 粒子池(简化版见 `particle-systems-cpu.md` 第 2.5 节):https://github.com/EpicGames/UnrealEngine/blob/ue5-main/Engine/Source/Runtime/Niagara/Private/NiagaraParticleData.h
- EnTT(C++ ECS,generational handle):https://github.com/skypjack/entt/wiki/Crash-Course:-entity-component-system

本系列内交叉引用:铺垫 `phase-4/deep-dives/memory-layout-for-cache.md`(cache 原理)、`phase-3/deep-dives/particle-systems-cpu.md`(专用 SoA 粒子池,本文的对照)、`phase-4/deep-dives/virtual-memory-and-allocators.md`(分配器原理,本文消灭的对象);当天本篇;后续 `phase-5/deep-dives/ecs-data-layout.md`(ECS 存储 = slot map + SoA + compact 三件套)、`phase-2/deep-dives/entity-system.md`(entity 概念,本篇第 4.1 节解释 entity ID 为什么是 generational)。
