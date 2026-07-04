
# 事件系统与游戏性根基:从硬编码调用到反射驱动的 gameplay

> 你跟完 HH Day 040,敌人终于能死。死的时候你想:得有音效、得有粒子爆炸、得分要加、任务要算"击杀数"。于是你打开 `kill_enemy` 函数,在底下塞进去四行——`audio.play(explosion_sound); particles.spawn(burst); score.add(points); quest.on_kill(unit);`。第二周你加成就系统,再回去改这个函数加一行 `achievements.on_kill(unit);`。第三周策划说"死亡有概率掉宝",你又回去改。一个月后,`kill_enemy` 这个函数要 import 八个子系统,改一处要确认不破坏另外七处。你想给它写单元测试,发现你得 mock 音频、粒子、分数、任务、成就、掉落、日志、统计——而这八件事本来跟"敌人怎么死"一点关系都没有。**这不是工程水平不够,这是缺了事件系统**。Jason Gregory 在《Game Engine Architecture》的"实时事件处理"和"游戏性基础"两章专门指出:大多数业余引擎把"事件发生 → 谁需要响应"这件事硬编码成调用链,导致游戏逻辑层和所有子系统死死焊在一起。职业引擎的做法是——**死亡这件事只发出一声"喊"(emit `EnemyDied`),谁在乎谁去听(subscribe)**。这一篇就把这条从硬编码到事件驱动、再到反射数据驱动的完整路径拆开讲清楚,顺带把 Gregory 点名的"gameplay 对象模型"和支撑它的 RTTI(运行时类型信息)一起补上。

## 0 · 你的死亡函数是一棵被疯狂嫁接的树

把上面那个场景具象一点。你打开 `handmade.rs` 第 2400 行,看到这样:

```rust
fn kill_enemy(&mut self, enemy_idx: usize) {
    let pos = self.entities[enemy_idx].pos;
    self.entities[enemy_idx].health = 0.0;
    self.entities[enemy_idx].alive = false;
    self.audio.play(SOUND_EXPLOSION);              // 第 1 周加的
    self.particles.spawn_burst(pos, 24);
    self.score.add(100);
    self.quests.notify_kill(enemy_idx);
    if rand::gen_range(0, 100) < 15 {              // 第 3 周:掉宝
        self.drop_loot(pos);
    }
    self.achievements.check_kill(enemy_idx);       // 第 5 周
    self.statistics.record_kill();                 // 第 8 周
    self.logger.info("enemy killed");
    if self.frenzy_mode.active {                   // 第 10 周:连击延长
        self.frenzy_mode.extend(2.0);
    }
    // 第 12 周,策划想加个"连击计数"……
}
```

这个函数做了它本职(把 enemy 标记为死)之后,**还有八件跟"杀死敌人"完全无关的事**。它知道音频、粒子、分数、任务、掉落、成就、统计、日志、frenzy——这九个子系统的接口。改任何一个子系统的签名,这个函数都得重编;删除任何一个子系统,这个函数得删一行;新增任何一个子系统,这个函数几乎肯定要加一行。

这件事的可怕之处不在于"代码行数多",而在于**耦合方向是反的**。"杀死敌人"本来是游戏逻辑的一个原子事件,它不应该知道下游谁在乎它。它应该只**喊一嗓子**:"敌人死了,这是谁、死在哪、被谁杀的",然后转身走人。下游那些"在乎敌人死"的系统——音频想播音效、粒子想放爆炸、任务想计数——它们**自己去订阅**这个事件,各管各的响应。死亡函数不知道、也不需要知道谁在听。这就是事件系统(event system)解决的核心问题,也是这一篇的主线。

## 1 · 事件要解决的真问题:依赖反转

在我给你写代码之前,我想先把"为什么"讲透,因为不理解这一点,你会做出一个看起来像事件总线、实际上还是耦合的东西。

直接调用(direct call)模式下,依赖关系是这样的:`kill_enemy` 依赖 `AudioSystem`、`ParticleSystem`、`ScoreSystem`、`QuestSystem`……。换句话说,**"事件源"必须认识所有"事件响应者"**。这是一个星形辐射——中心是事件源,辐射出 N 条边到 N 个响应者。每加一个响应者,就多一条边,而这条边是从事件源那边"长"出来的。

事件模式把这个星形辐射**反转**了。事件源只依赖一个东西——**事件总线**(event bus)。它对总线说一句 `bus.emit(EnemyDied { ... })`,就完事了。总线自己负责把这句话转发给所有事先登记过的订阅者。订阅者(`AudioSystem` 等)在初始化时跟总线说:"以后有 `EnemyDied` 这种事,告诉我一声,这是我的回调"。于是依赖关系变成:`kill_enemy` 依赖总线,每个响应者也依赖总线,但事件源和响应者**互相不认识**。

这个反转带来的工程价值,是随项目规模**非线性**增长的。五个响应者时,直接调用还能忍;五十个响应者时(一个商业 RPG 里"敌人死亡"能触发的事情:音效、粒子、血迹、掉落、任务、成就、统计、AI 警觉、玩家经验、声望、日志、回放、网络同步……),直接调用模式下的 `kill_enemy` 函数会变成一个 50 行的"知道所有事"的怪物,而事件模式下它仍然只有一行 `bus.emit(...)`。**新增一个响应者,事件源零改动**——这是开放-封闭原则在游戏逻辑层的兑现,和 [ecs-evolution](./ecs-evolution.md) 里讲 ECS 把 component 加法从"改 struct"变成"不改 struct"是同一个精神。

但事件模式不是银弹,它带来一个新的成本:**间接性**(indirection)。直接调用时,你想知道"敌人死了之后会发生什么",你 grep `kill_enemy` 函数体,一行行读下去就行,所有响应者都在眼前。事件模式下,你 grep `bus.emit(EnemyDied)`,只能看到一句话;想知道谁响应,你得反过来 grep "谁订阅了 `EnemyDied`"。这种间接性让事件驱动的代码更难"读一个函数就读完全部",调试时也更难追因果链(一个事件触发十个响应者,某个响应者又 emit 另一个事件,链路可能很深)。职业引擎对冲这个成本的工具是**事件查看器**(event viewer / debug overlay)——运行时把总线收发的所有事件可视化,让你能看到"这帧发出了哪些事件、谁处理了、耗时多少"。Bevy 的 `EventReader`/`EventWriter` 配合 tracy profiler([profiling-with-tracy](../../phase-4/deep-dives/profiling-with-tracy.md))就是这种工具链的工业级组合。所以记住这个权衡:**事件换来了扩展性,代价是可追踪性,你用工具补回来**。

## 2 · 第一个能跑的事件总线:类型安全的发布订阅

讲完原理,我们来在 Rust 里写一个能跑的最小事件总线。目标:类型安全(`emit(EnemyDied)` 不能往订阅 `Pickup` 的地方塞)、运行时注册订阅者、一次 emit 能通知所有人。

```rust
use std::any::{Any, TypeId};
use std::collections::HashMap;

// —— 事件本身:任何 'static + Send + Sync 的 struct 都能当事件 ——
pub struct EnemyDied { pub entity: u32, pub killer: u32, pub pos: (f32, f32) }
pub struct Pickup { pub item: u32, pub x: f32, pub y: f32 }

// —— 订阅者:一个能吃掉具体事件类型的闭包,被擦成 trait object ——
type ErasedHandler = Box<dyn FnMut(&dyn Any) + Send>;

pub struct EventBus {
    // TypeId::of::<EnemyDied>() → 一组擦掉了具体类型的 handler
    subscribers: HashMap<TypeId, Vec<ErasedHandler>>,
}

impl EventBus {
    pub fn new() -> Self { Self { subscribers: HashMap::new() } }

    /// 订阅某个事件类型,传入的 handler 在 emit 时被调用
    pub fn subscribe<E, F>(&mut self, mut handler: F)
    where
        E: Any + Send + Sync,
        F: FnMut(&E) + Send + 'static,
    {
        // 把 FnMut(&E) 包装成 FnMut(&dyn Any),内部 downcast 回 &E
        let erased: ErasedHandler = Box::new(move |any: &dyn Any| {
            if let Some(e) = any.downcast_ref::<E>() {
                handler(e);
            }
        });
        self.subscribers.entry(TypeId::of::<E>()).or_default().push(erased);
    }

    /// 发出事件,所有订阅了这个类型的 handler 按注册顺序被调用
    pub fn emit<E: Any + Send + Sync>(&mut self, event: E) {
        let key = TypeId::of::<E>();
        if let Some(handlers) = self.subscribers.get_mut(&key) {
            for h in handlers.iter_mut() { h(&event); }
        }
    }
}
```

来读一下这个实现。核心是 `subscribers: HashMap<TypeId, Vec<ErasedHandler>>`。`TypeId::of::<EnemyDied>()` 在编译期就是固定值,每个具体类型一个唯一的 `TypeId`,正好做 HashMap 的 key。值是一组 `Box<dyn FnMut(&dyn Any)>`——我们把"吃 `&EnemyDied` 的闭包"擦成"吃 `&dyn Any` 的闭包",内部在 `subscribe` 里用一个闭包包装做 downcast 回具体类型。这个技巧叫**类型擦除**(type erasure),Rust 里所有"想用容器装不同具体类型的回调"的场景都靠它。

emit 时按 `TypeId` 查到 handler 列表,挨个调用,每个 handler 自己再 downcast 回具体事件类型。**整个调用链是同步的**(immediate dispatch)——`emit` 返回时,所有订阅者都已经执行完了。这一点很重要,后面讲延迟事件时会反过来。

用起来长这样:

```rust
let mut bus = EventBus::new();

// 各个子系统在初始化时订阅
bus.subscribe::<EnemyDied, _>(|e| println!("audio: play explosion at {:?}", e.pos));
bus.subscribe::<EnemyDied, _>(|e| println!("score: +100 for killer={}", e.killer));
bus.subscribe::<Pickup, _>(|e| println!("quest: picked up item={}", e.item));

// gameplay 代码里只需要 emit
bus.emit(EnemyDied { entity: 7, killer: 0, pos: (10.0, 20.0) });
bus.emit(Pickup { item: 42, x: 5.0, y: 5.0 });
```

`kill_enemy` 现在长这样:

```rust
fn kill_enemy(&mut self, enemy_idx: usize) {
    let pos = self.entities[enemy_idx].pos;
    self.entities[enemy_idx].health = 0.0;
    self.entities[enemy_idx].alive = false;
    // 就这一行。音效、粒子、分数、任务、成就……都不在这里。
    self.bus.emit(EnemyDied { entity: enemy_idx as u32, killer: self.player.id, pos });
}
```

对比一下 §0 那个怪物,八行 import 没了,八次方法调用变成一次 `emit`。**新增一个"敌人死亡时要做的事",你写一个新的 subscribe,不碰 kill_enemy 一行代码**。这就是依赖反转的兑现。

### 2.1 同步派发的陷阱:迭代中销毁

但你立刻会遇到一个坑,这个坑会引出"延迟事件"的必要性。设想音频系统的订阅者这么写:

```rust
bus.subscribe::<EnemyDied, _>(|e| {
    world.despawn(e.entity);   // ← 危险!在 emit 的瞬间就执行了
});
```

如果 `emit(EnemyDied)` 是在一个遍历所有敌人的循环里被调用的:

```rust
for i in 0..self.entities.len() {
    if self.entities[i].health <= 0.0 {
        self.kill_enemy(i);   // 内部 emit EnemyDied
        // ↑ emit 同步执行,handler 里 despawn 把 entities[i] 删了
        // 现在循环还在用 self.entities[i],已经无效了
    }
}
```

这就是同步事件派发的根本危险——**emit 的瞬间所有 handler 跑完,handler 可能修改 emit 调用者正在用的数据**。在 ECS 里这等价于"iterate archetype 时 insert component"那个 [ecs-evolution](./ecs-evolution.md) §6.6 讲的 UB,根因是同一个:**迭代期间结构被改了**。Bevy 的 `Commands` 延迟队列就是为解决这个而存在的——它不让你在系统内直接改 world,而是把改动排进队列,系统边界统一 flush。事件系统需要一样的机制。

## 3 · 延迟事件队列:在安全的时机再处理

为了避开"迭代中改数据"的雷区,一个好的事件系统除了同步派发,还得支持**延迟派发**(deferred / queued dispatch)。思路:emit 不立刻调用 handler,而是把事件塞进一个队列;循环跑完、到达一个安全的检查点(checkpoint)时,统一 flush 队列,这时再调用 handler。

```rust
use std::collections::VecDeque;

pub struct EventBus {
    immediate: HashMap<TypeId, Vec<ErasedHandler>>,
    pending: VecDeque<(TypeId, Box<dyn Any + Send>)>,     // 延迟队列
    deferred: HashMap<TypeId, Vec<HandlerSlot>>,          // 延迟 handler
}

pub struct HandlerSlot {
    priority: i32,         // 数字越大越先跑
    handler: ErasedHandler,
}

impl EventBus {
    /// 立刻派发(适合"读多改少"的事件,比如分数变化)
    pub fn emit_immediate<E: Any + Send + Sync>(&mut self, event: E) {
        if let Some(hs) = self.immediate.get_mut(&TypeId::of::<E>()) {
            for h in hs.iter_mut() { h(&event); }
        }
    }

    /// 入队,稍后 flush 时派发(适合"会改世界结构"的事件,比如销毁 entity)
    pub fn emit_deferred<E: Any + Send + Sync>(&mut self, event: E) {
        self.pending.push_back((TypeId::of::<E>(), Box::new(event)));
    }

    /// 在每帧的安全检查点调用:把队列里的事件全部派发出去
    pub fn flush(&mut self) {
        while let Some((type_id, event)) = self.pending.pop_front() {
            if let Some(slots) = self.deferred.get_mut(&type_id) {
                // 按优先级排序:数字大者先
                slots.sort_by(|a, b| b.priority.cmp(&a.priority));
                for slot in slots.iter_mut() {
                    (slot.handler)(event.as_ref());
                }
            }
        }
    }
}
```

游戏主循环的形态现在变成:

```rust
fn update(&mut self, dt: f32) {
    self.ai_update(dt);
    self.physics_update(dt);
    self.combat_update(dt);   // 内部 kill_enemy → emit_deferred(DestroyEntity)

    // —— 安全检查点:把延迟事件 flush 出去 ——
    // 这时所有的迭代都已经结束,handler 里做 despawn / spawn 安全
    self.bus.flush();

    self.render();
}
```

"销毁 entity"这类操作,你 emit 一个延迟的 `DestroyEntity { id }`,handler 在 flush 阶段执行,这时战斗循环已经跑完,不会撞上正在迭代的 `entities[]`。**这就是延迟事件的根本用途:把"会改结构的副作用"从迭代中挪到迭代外**。

### 3.1 优先级:ordering 的问题与陷阱

延迟事件还有个细节要解决——**handler 的执行顺序**。设想分数系统和成就系统都订阅了 `EnemyDied`:成就系统的逻辑是"分数过 1000 时解锁奖杯"。如果成就 handler 先跑,它看到的还是旧分数;分数 handler 后跑,加完分但成就已经检查过了。这个 bug 极其隐蔽,因为它不会崩溃,只是"明明该解锁的奖杯没解锁"。

`HandlerSlot` 里的 `priority` 就是给这种场景的 tie-breaker——`score.on_kill` 优先级 100,`achievements.on_kill` 优先级 50,flush 时先调分数再调成就。这本质上是把 [ecs-system-scheduling](./ecs-system-scheduling.md) 里讲的系统排序问题,搬到了事件订阅者上——两者解决的是同一个"谁先谁后"的问题,因为事件 handler 和系统本质都是"对某个状态变化做出响应的函数"。

但要注意一个工程教训:**别滥用优先级**。如果某个事件被设计成"必须先 A 再 B 再 C",那说明 A/B/C 之间其实有强耦合,你的事件切分得太细了,可能合并成一个"分阶段的 handler"更清晰。优先级应该是"少数几对订阅者之间的 tie-breaker",而不是"用 priority 把一个本该一个函数的逻辑串起来"——后者是退化成"用事件总线模拟直接调用",丢掉了事件模式的解耦收益。

## 4 · Bevy 的 Events:工业级事件系统的样子

讲完手写的版本,我快速对一下 Bevy 是怎么做的,因为你迟早会用 Bevy 或者参考它的设计。Bevy 的 `Event<T>` 不是我们上面那种"全局总线"模型,而是和 ECS 紧密绑定的——它把事件当作一种特殊的 ECS 资源,通过系统参数读写。

```rust
use bevy_ecs::prelude::*;

#[derive(Event)]
struct EnemyDied { entity: Entity, killer: Entity, pos: Vec3 }

fn combat_system(mut events: EventWriter<EnemyDied>, query: Query<...>) {
    for (...) in &query {
        events.send(EnemyDied { entity, killer, pos });  // 塞进 buffer,不立刻调用
    }
}

fn score_system(mut events: EventReader<EnemyDied>, mut score: ResMut<Score>) {
    for event in events.read() { score.0 += 100; }       // 读上一帧 writer 写的
}

fn audio_system(mut events: EventReader<EnemyDied>, audio: ResMut<Audio>) {
    for event in events.read() { audio.play_at(SOUND_EXPLOSION, event.pos); }
}

app.add_event::<EnemyDied>()
   .add_systems(Update, (combat_system, score_system, audio_system));
```

Bevy 的设计有几个值得注意的取舍。

第一,它**没有"全局总线"**,而是每个事件类型对应一个独立的 `Events<T>` 资源,通过 `add_event::<T>()` 注册。这避免了我们手写版"所有事件挤在一个 HashMap 里"的内存压力,也让编译期类型检查更严——你 `EventWriter<EnemyDied>` 写错了类型,编译就报错,不会有"运行时 downcast 失败悄悄不调用"的风险。

第二,`EventReader` 默认读的是**上一帧** writer 写的事件,这天然就是延迟派发——combat 这帧 send,score/audio 下帧 read。这个设计直接吃掉了"迭代中改结构"的风险,因为读和写根本不在同一帧发生。Bevy 的 Events 资源内部维护两个 buffer(双缓冲),writer 写当前帧的,reader 读上一帧的,帧末交换。代价是事件**有一帧延迟**——对于音效、粒子这种"晚 16ms 听不出来"的没问题,但对于"立刻要看到分数变化"的 UI 可能要调整。

第三,Bevy 的 schedule([ecs-system-scheduling](./ecs-system-scheduling.md)) 通过 `before` / `after` / `in_set` 解决 handler 顺序问题,而不是 priority 数字。`score_system.after(combat_system)` 显式声明依赖,这是 Bevy 整体设计哲学——**显式优于隐式**。priority 是隐式的(你得记住"数字越大越先"),system ordering 是显式的(代码里就写着依赖关系)。

如果你在 HH 项目里手写事件系统,我建议你**先用手写版**体会一遍,再考虑要不要切到 `bevy_ecs` 的 Events。原因:手写版让你看清"事件系统到底是什么"(就是一个 HashMap + 几个 Vec),消除了神秘感;切到 Bevy 后你才能正确理解它的取舍——为什么双缓冲、为什么 Events 是资源、为什么用系统 ordering 而非 priority。直接用 Bevy 的人往往不知道这些设计点存在,只能照着文档抄。

## 5 · Gameplay 对象模型:ECS 之上的"游戏级抽象"

事件总线解决了"谁通知谁"的问题,但游戏逻辑还需要另一个东西——**对象模型**(object model)。这是 Gregory《GEA》"gameplay foundations"那一章的主题,也是 [09B-2](../../phase-9/09B-2-subsystems-modules-plugins.md) 里讲反射时埋下的伏笔。

什么是对象模型?ECS 给你的原始接口是 `world.spawn((Position, Health, AI))` 这种"裸组件元组"。但写 gameplay 的人不想每次都拼一个元组,他想写 `world.spawn_enemy(pos, kind)`、`world.spawn_player(pos)`、`world.spawn_projectile(from, to, damage)`——**这些"游戏里有名字的事物"**就是 gameplay 对象。Unity 的 `GameObject`、Unreal 的 `Actor`、早期 C++ 引擎的"Entity class",都是这种"在裸数据之上的游戏级抽象"。

对象模型要回答的问题是:一个"敌人"由哪些 component 组成?这些 component 的初始值由什么决定?"敌人"有哪些行为(巡逻、追击、攻击、死亡)?这些行为本质就是订阅了一堆事件的 handler。不同类型的敌人怎么区分?

职业引擎的做法是把"敌人"这种概念做成一个 **prefab**(预制件)——一个数据文件,描述"敌人"这种对象需要哪些 component、初始值是什么。运行时 `world.spawn_from_prefab("goblin")` 读这个文件,组装出正确的 component。这把"造一个敌人"的逻辑从代码里搬到了数据里——加一种新敌人,只需要写一个新的 prefab 数据文件,不改任何代码。这就是 [09B-2](../../phase-9/09B-2-subsystems-modules-plugins.md) §6 讲的"数据驱动"在 gameplay 层的兑现。

事件系统、ECS、对象模型三者的关系:**ECS** 是**数据层**(entity 是 ID、component 是数据、system 是处理函数);**事件总线** 是**通信层**(让 system / gameplay 代码之间不直接调用);**对象模型** 是**抽象层**(在裸 ECS 上提供"敌人、玩家、子弹"这种游戏级概念,让 gameplay 代码可读、可配置)。一个完整的 gameplay 系统三层都用:某个 system 检测到敌人血量 ≤ 0,emit `EnemyDied` 事件;事件总线的订阅者(可能也是 system,也可能是 gameplay-level 的 handler)各自响应——audio system 播音效、score system 加分、quest system 更新任务。对象模型的"敌人"概念,体现在"所有有 `Health + AI + Render` 的 entity 都被视为敌人"。HH 项目里你可能还停在"player 是个 struct、entity 是个数组"的 Stage 0([ecs-evolution](./ecs-evolution.md) §2),没有 prefab、没有 event、没有 gameplay-level 抽象。这一篇的"在 HH 项目里动手"那一节,会带你把事件总线这一层先加进去——这是从 Stage 0 走向"真正能扩展的 gameplay"的性价比最高的一步。

## 6 · 反射:让事件、脚本、编辑器变得通用

讲到这里,你可能会想:我的事件总线好像还行,但每加一种新事件,我都得定义一个 `struct`、写 `bus.subscribe::<MyEvent>`、各处 emit。这本身还算可接受。但设想一个场景——**编辑器**。

你想做一个可视化编辑器,让策划能在不写代码的情况下定义新事件、给事件挂新的响应。策划点开"事件"面板,看到 `EnemyDied`,想给它加一个新的响应:"播放某段动画"。这个响应的数据(动画名、播放速度、循环与否)是策划在 UI 里填的,然后存成一个数据文件。运行时,引擎读这个数据文件,根据"动画名 = 'death_1'"这种字段,**自动**调用 `play_animation("death_1")`。

这里有个根本问题:**策划填的数据是字符串和数字,引擎代码里没有对应的 `struct`**。引擎怎么知道 "animation_name" 这个字段对应 `AnimationPlayer` 系统的哪个参数?怎么把它从 JSON 字符串转成函数调用?

答案是**反射**(reflection),也叫 **RTTI**(Run-Time Type Information,运行时类型信息)。Gregory 在《GEA》专门用一章讲它,因为它是数据驱动 gameplay 的**承重墙**。这一点 [09B-2](../../phase-9/09B-2-subsystems-modules-plugins.md) §6 从架构角度讲过,这里我从事件和 gameplay 的角度再讲一遍,把它和这一篇的主题钉死。

反射的核心是:**让运行时的程序知道"自己定义的类型长什么样"**。Rust 编译后,`struct EnemyDied { entity: u32, killer: u32, pos: (f32, f32) }` 这条信息**没了**——运行时只剩一块 16 字节的内存,程序不知道里面有什么字段、字段叫什么、什么类型。这对于"想写出通用工具"的场景是致命的:

- 序列化([savegame-and-serialization](../../phase-8/deep-dives/savegame-and-serialization.md)):你想写一个"把任意 struct 存成 JSON"的函数,但运行时你不知道 struct 有哪些字段。
- 编辑器:你想在 UI 里显示任意 component 的字段供策划修改,但运行时你不知道 component 有什么字段。
- 脚本([scripting-and-modding](../../phase-8/deep-dives/scripting-and-modding.md)):你想让 Lua 脚本通过字段名访问 `enemy.health`,但运行时 Rust 不知道 `Enemy` 有个 `health` 字段。
- 数据驱动事件:策划用 JSON 描述一个新事件,引擎需要把 JSON 转成具体事件 struct,但运行时 Rust 不知道有哪些事件 struct、它们长什么样。

**所有这些"想泛型地操作任意类型"的能力,底座都是反射**。没有反射,每个新类型你都得手写一份序列化、一份编辑器面板、一份脚本绑定——加一个 `struct` 就得改四个地方,这就是 Stage 0 的"上帝对象"反模式在数据层的复现。

Rust 没有内建反射(这是 Rust 有意的设计选择——反射有性能和编译时间成本,Rust 倾向 opt-in)。最主流的方案是 `bevy_reflect`:

```rust
use bevy_reflect::Reflect;

#[derive(Reflect, Debug)]
pub struct EnemyDied {
    pub entity: u32,
    pub killer: u32,
    pub pos: (f32, f32),
}

let event = EnemyDied { entity: 7, killer: 0, pos: (10.0, 20.0) };
let reflected: &dyn Reflect = &event;

// 运行时遍历字段
for field in reflected.iter_fields() {
    println!("field: {:?}", field);
}

// 按名字访问
let pos = reflected.field("pos").unwrap();
println!("pos = {:?}", pos);
```

`#[derive(Reflect)]` 在编译时由派生宏生成一份"字段表"(每个字段的名字、类型、访问方法),这份表在运行时可查。`bevy_reflect::Reflect` trait 的核心方法就是 `field(name)`、`iter_fields()`、`as_any()` 这些——让运行时能把任意 struct 当成"名值对集合"操作。

回到策划那个场景。有了反射,数据驱动的事件可以这样设计:

```rust
// 引擎内置的几种"响应 action",都 derive Reflect
#[derive(Reflect)]
struct PlayAnimation { animation_name: String, speed: f32, loop_: bool }

#[derive(Reflect)]
struct AddScore { points: i32 }

// 策划在编辑器里给 EnemyDied 配置响应:存成 JSON
// [
//   { "type": "PlayAnimation", "animation_name": "death_1", "speed": 1.0 },
//   { "type": "AddScore", "points": 100 }
// ]

// 运行时:读 JSON → 反射 + type registry → 调对应 handler
fn run_response(action: &dyn Reflect, ctx: &EventContext) {
    match action.type_path() {
        "PlayAnimation" => {
            let a = action.downcast_ref::<PlayAnimation>().unwrap();
            ctx.anim.play(&a.animation_name, a.speed, a.loop_);
        }
        "AddScore" => {
            let a = action.downcast_ref::<AddScore>().unwrap();
            ctx.score.0 += a.points;
        }
        _ => {}
    }
}
```

这个模式叫**数据驱动的事件响应**——策划加一种新响应,只需要在 JSON 里加一条;加一种新 action 类型,才需要程序员写一个新 `#[derive(Reflect)] struct` 和对应的 dispatch 分支。这是职业引擎的"事件系统"为什么能扩展到几百种事件、几千种响应的根本——**它们大多数不是手写代码,是数据**。Unity 的 `UnityEvent`、Unreal 的 `Blueprint` 事件图,都是这个模式的成熟实现,底层都有完整的反射系统支撑。

把这个反射注册表接到 §2 的事件总线上,你就有了**完整的事件 + 反射系统**:Rust 代码 emit 事件用编译期类型(`bus.emit(EnemyDied { ... })`),策划的 JSON / 脚本 emit 事件用运行时字符串(`registry.dispatch_json(...)`)。两边最终都走到同一个 handler,代码逻辑只有一份。这是职业引擎的"事件系统"和"脚本系统"为什么能无缝协作的底层原因——**它们共享同一份反射注册表**。

### 6.1 反射的成本与边界

反射不是免费的,你得清楚它的成本,不然会滥用。性能上,反射调用比直接调用慢——一次 `field("pos")` 涉及字符串比较、HashMap 查表、动态类型检查,比 `event.pos` 这种编译期字段访问慢几十倍。反射还有**内存开销**——每个 derive 出的 Reflect 实现,要存一份字段元数据。编译时间上,`#[derive(Reflect)]` 让 proc macro 多跑一轮,大型项目里这部分非平凡。

职业引擎的做法是**只在"需要通用性"的地方用反射**,内部热路径用普通 struct。具体来说:Component、Event、Action 这些"策划 / 脚本 / 编辑器要操作的数据"**用反射**,它们不是每帧跑的热路径;数学库(Vec3、Mat4)、物理 state、渲染 buffer 这些"引擎内部、不暴露给数据驱动"的**不用反射**,它们性能关键;系统调度里的 ComponentId、Event 类型注册用一次反射(注册时),之后用整数 ID 索引,**避免运行时反复反射**。Bevy 的设计就严格遵循这个边界:`bevy_reflect` 是 opt-in 的 crate,普通 component 不 derive Reflect 也能跑;只有你明确需要反射的(序列化、编辑器、脚本)才 derive。

## 7 · 在你 HH 项目里动手(做中学红线)

理论讲够了,我们把这一篇落到你的 HH 项目上。这是一次中等规模的重构,影响深远——做完之后你的 gameplay 代码风格会从根本上改变。

### 7.1 第一步:引入 EventBus

在你的 `Cargo.toml` 加 nothing——这个版本我们手写,不依赖外部 crate,这样你能完全看清它是什么。把 §2 的 `EventBus` 代码贴进 `src/event_bus.rs`。然后在 `GameState` 里加一个字段:`pub bus: EventBus`。`GameState::new()` 里初始化 `bus: EventBus::new()`。

### 7.2 第二步:定义你的第一批事件

从最容易的事件开始——`EnemyDied`。**事件的设计有讲究**:一个事件应该表达"发生了什么",而不是"该做什么"。`EnemyDied` 是好的——它说"敌人死了",至于死之后要播音效还是加分,事件本身不关心,订阅者决定。如果你定义一个 `PlayExplosionSoundOnEnemyDeath` 这种"指令式"事件,你又在把调用链硬编码进事件名了。

### 7.3 第三步:把死亡响应迁移到订阅者(红线)

这一步是红线。找到你 HH 项目里的 `kill_enemy`(或者类似的函数),把它当前的死亡响应逻辑——所有"音频、粒子、分数、任务"调用——**全部删掉**,只留 `bus.emit(EnemyDied { ... })`。然后在游戏初始化的地方,给每个被删掉的子系统注册一个订阅者:

```rust
// 游戏启动时
state.bus.subscribe::<EnemyDied, _>(move |e| {
    audio.play_explosion_at(e.pos);
});
state.bus.subscribe::<EnemyDied, _>(|e| {
    state.score += 100;   // 这里有借用问题,见下面注意
});
state.bus.subscribe::<EnemyDied, _>(|e| {
    state.quests.notify_kill(e.entity);
});
```

**注意 Rust 的借用坑**:我们的 `subscribe` 接受 `FnMut(&E)`,闭包捕获外部状态。但 `state.bus.subscribe` 时 `state` 已经被借用,handler 闭包里又想用 `state.score`,这就形成了 `state` 同时被借用两次的冲突。职业做法是**把订阅者拆到各子系统的模块**,每个子系统 own 自己的状态:

```rust
// in audio/mod.rs
impl AudioSystem {
    pub fn register(&mut self, bus: &mut EventBus) {
        let audio = self.handle.clone();  // AudioHandle 是 Send 的
        bus.subscribe::<EnemyDied, _>(move |e| {
            audio.play_explosion_at(e.pos);
        });
    }
}
```

这样每个子系统 own 自己的数据,bus own 它的订阅者列表,gameplay 代码 own 它的 emit,三方互不借用。如果用 Bevy,这个借用问题不存在——ECS 的 `Query` / `ResMut` 通过系统参数自动借用检查,你不用手管闭包捕获。

### 7.4 第四步:加延迟事件,解决"销毁 entity"

把 `EnemyDied` 里"销毁 entity"这一步单独拆出来,做成一个延迟事件 `DestroyEntity { id: u32 }`。`kill_enemy` emit 两个事件:同步的 `EnemyDied`(让音效、分数立刻响应),延迟的 `DestroyEntity`(让销毁延后到 flush):

```rust
fn kill_enemy(&mut self, idx: usize) {
    let pos = self.entities[idx].pos;
    let id = idx as u32;
    self.entities[idx].health = 0.0;
    self.bus.emit_immediate(EnemyDied { entity: id, killer: self.player.id, pos });
    self.bus.emit_deferred(DestroyEntity { id });   // 等到迭代结束
}

fn update(&mut self, dt: f32) {
    self.combat_update(dt);   // 这里可能 emit_deferred(DestroyEntity)
    self.bus.flush();         // ← 安全检查点,DestroyEntity 在这里执行 despawn
    self.render();
}
```

做完这一步,**故意制造一个 bug 验证它真的在工作**:把 `emit_deferred` 改成 `emit_immediate`,然后让你 HH 里有"一个敌人死亡引发另一个敌人死亡"的链(比如爆炸带连锁伤害)。你会看到程序在迭代中 panic / 数据错乱(因为前一个敌人 despawn 改了 entities 数组,后面的迭代用了错误索引)。改回 `emit_deferred`,bug 消失。这是把"延迟事件为什么必要"焊进你肌肉记忆的最快方式。

### 7.5 第五步(可选):加反射,体验数据驱动

如果你想更进一步,引入 `bevy_reflect`(独立 crate,不需要整个 bevy):

```toml
[dependencies]
bevy_reflect = "0.15"
```

给你的事件加 `#[derive(Reflect)]`,然后在 main 里 print 出它的字段:

```rust
use bevy_reflect::Reflect;

#[derive(Reflect)]
struct EnemyDied { entity: u32, killer: u32, pos: (f32, f32) }

let e = EnemyDied { entity: 7, killer: 0, pos: (10.0, 20.0) };
let r: &dyn Reflect = &e;
for field in r.iter_fields() { println!("{:?}", field); }
```

这一步不会立刻产出功能,但它让你看清"反射在 Rust 里到底长什么样"。当你后续要做存档([savegame-and-serialization](../../phase-8/deep-dives/savegame-and-serialization.md))或者编辑器的时候,你会用上这个底座。

做完以上五步,你的 HH 项目就从"硬编码调用链"演进到了"事件驱动 + 部分数据驱动"。再加一种新事件(比如 `Pickup`、`LevelUp`),你的 workflow 是:定义 `#[derive(Reflect)] struct`,写几个 `subscribe` 注册响应,在合适的位置 `emit`。**不需要改任何现有的死亡 / 拾取 / 升级代码**。这种扩展性的差异,等你做了几十种事件之后会非常明显——你的同行还在硬编码,代码已经是一团乱麻,你的代码每个文件依然清爽。

## 8 · 练习

**Lv1(概念辨析)**:用一句话解释"事件系统解决了直接调用模式的什么根本问题",以及它引入了什么新成本。

参考答案:直接调用模式下,事件源必须认识所有响应者(依赖辐射);事件模式反转为"事件源只依赖总线,响应者只依赖总线,彼此不认识",带来扩展性,代价是间接性(读一个函数读不到完整因果链,需要工具辅助追踪)。

**Lv2(动手实践)**:完成 §7 的前三步。把你的 HH 项目里 `kill_enemy`(或类似函数)的死亡响应,从直接调用音频 / 粒子 / 分数,重构成 emit `EnemyDied`,各子系统 subscribe。提交一个 commit,在 commit message 里记录重构前后这个函数的行数差异(应该明显变短)。

**Lv3(设计思辨)**:你的策划提出一个新需求:"敌人死亡时,如果玩家在 frenzy 模式,要额外播放一段特殊音效"。在硬编码模式下,你会去改 `kill_enemy`。在事件模式下,你应该怎么做?给出方案,并说明这种做法相对于硬编码的优势。

参考答案:写一个新的 `subscribe::<EnemyDied>`,在 handler 里查 `frenzy_mode.is_active()` 决定播哪段音效。`kill_enemy` 完全不动。优势:frenzy 这个功能可以由 frenzy 模块自己负责,它和战斗系统完全解耦——以后 frenzy 模式要移除 / 改实现,战斗系统一行不改。

**Lv4(进阶)**:给你的 EventBus 加一个"事件历史"功能——保留最近 100 个 emit 的事件(类型名 + 时间戳 + 简要内容),通过一个 debug 命令打印出来。然后用它调试一个真实 bug(比如某个 EnemyDied 没被处理),体会"事件查看器"这种工具为什么是事件驱动代码的可追踪性补丁。把这个 debug 视图和 [game-state-management](../../phase-2/deep-dives/game-state-management.md) 里讲的游戏状态查看器关联起来——它们本质都是"把内存里的抽象状态可视化给人看"。

## 9 · 延伸阅读

外部稳定参考:

- Jason Gregory, *Game Engine Architecture* 3rd ed., 第 6 章 "Gameplay Foundations" 和第 7 章 "Real-Time Event Processing"。这两章是这一篇的"母题",Gregory 在 Naughty Dog 的实战经验都在里面,值得反复读。特别是他对事件队列 vs 立即派发的取舍、gameplay 对象模型如何和引擎解耦的论述,是教科书级的。
- Bevy 的 `Event` / `EventReader` / `EventWriter` 文档:https://bevyengine.org/learn/book/events/ 。读完你会发现 Bevy 的 Events 是这一篇讲的"延迟双缓冲"的工业实现。
- `bevy_reflect` 文档与源码:https://github.com/bevyengine/bevy/tree/main/crates/bevy_reflect 。看它怎么用派生宏生成字段元数据、怎么用 TypeRegistry 做运行时分发。
- Unity 的 `UnityEvent` 和 `ScriptableObject` 事件系统:https://docs.unity3d.com/ScriptReference/Events.UnityEvent.html 。这是商业引擎里"数据驱动事件响应"的成熟实现,值得对比 Bevy 的设计。
- Unreal Engine 的 `Blueprint` 事件和 `UFunction` 反射:https://docs.unrealengine.com/5.0/en-US/unreal-engine-reflection-system-in-unreal-engine/ 。Unreal 用 `UCLASS` / `UPROPERTY` 宏做反射,是 C++ 引擎里 RTTI 的经典方案。

关联模块:

- [ecs-evolution](./ecs-evolution.md) — 这一篇假设你已经理解 ECS 的 Stage 0-6,特别是 archetype move 和 iterate 期间不能改结构的约束。
- [ecs-system-scheduling](./ecs-system-scheduling.md) — 系统排序和事件 handler 排序是同一个问题,优先级 vs 显式 ordering 的取舍两边都讲。
- [09B-2](../../phase-9/09B-2-subsystems-modules-plugins.md) §6 — 反射那一节是这一篇 §6 的姐妹篇,从架构角度展开讲为什么反射是数据驱动的承重墙。
- [scripting-and-modding](../../phase-8/deep-dives/scripting-and-modding.md) — 脚本系统直接消费反射注册表,这一篇的事件 + 反射是它的底座。
- [game-state-management](../../phase-2/deep-dives/game-state-management.md) — 事件驱动和状态机经常配合使用:状态转换 emit 事件,事件触发新的状态查询。
- [gameplay-systems](../../phase-7/deep-dives/gameplay-systems.md) — 这一篇的"gameplay 对象模型"那节是 gameplay 系统的入口,后续那篇会更具体讲怎么建模职业、技能、buff。
- [savegame-and-serialization](../../phase-8/deep-dives/savegame-and-serialization.md) — 序列化是反射的最大消费方之一,这一篇 §6 的反射底座在那里直接兑现。
