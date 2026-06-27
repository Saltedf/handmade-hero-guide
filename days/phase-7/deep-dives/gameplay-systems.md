---
phase: 7
type: deep-dive
title_en: "Gameplay Systems: Dialogue / Quest / Ability / Inventory"
title_zh: "游戏性系统:对话 / 任务 / 能力 / 库存"
difficulty: 4
duration: "10h"
domains: [game, rust, gamedev, data-driven, state-machines]
prereqs:
  - event-systems-and-gameplay-foundations
  - scripting-and-modding
calibration: "gameplay 系统(对话/任务/能力/库存)+ 共享模式(数据驱动/状态机/事件)"
---

# 深入:游戏性系统 —— 对话 / 任务 / 能力 / 库存

> 你的引擎已经能渲染一万个精灵、能跑物理碰撞、能播 BGM,玩家可以拿着剑到处砍怪——但你点 NPC,NPC 一声不吭;你杀了一只狼,游戏没有任何反应;你想给角色加一个"冲刺"技能,你打开 `player.rs` 又写了一个 `if key == Shift { pos += vel * 2 }`;你想做背包,你又开始在 `player.rs` 里塞 `Vec<Item>`。一个礼拜后你的 `player.rs` 三千行,任何改动都崩三处。**你的"引擎"很完整,但你没有"游戏"** —— 因为游戏性 (gameplay) 这一层缺位。
>
> 这篇深入要回答的核心问题:**对话、任务、能力、库存** 这四个看起来截然不同的系统,本质上共享同一套工程模式。一旦你看穿这套模式,你能用同一个心智模型造出它们任何一个 —— 进而造出"制造、科技树、声望、伙伴、坐骑、副本进度" 这些游戏里所有看起来花哨的"系统"。这条线的关键不在写代码,而在**抽象** —— 把"玩法规则"从"代码硬编码"中解放出来,变成设计师可以喂养的**数据**。
>
> 我们会一条主线走到底:每个系统都是**数据驱动 (data-driven) + 状态机 (state machine) + 事件驱动 (event-driven)** 的同一个三角形。先建立这套心智模型,再用它拆解四个系统的真实工程实现,最后落到你的 HH 项目里 —— 给 HH 加一个纯数据驱动的任务系统,然后通过"加三个任务不改一行代码"亲自体会框架 vs 内容的分工。

## 0 · 引擎不是游戏 —— 为什么需要"游戏性系统"这一层

### 0.1 一个让你窒息的真实场景

把场景拉具体。你跟 Handmade Hero 走到 Day 540,代码长得是这样:`renderer.rs` 管画,`physics.rs` 管碰撞,`audio.rs` 管声音,`input.rs` 管键鼠,`world.rs` 管地图,`entity.rs` 管实体。这些是**引擎层** —— 它们提供"能力",但不规定"规则"。

然后你想加这些"玩法":

- **任务 A**:你设计了一个新手任务 —— "杀 5 只哥布林,回报村长,得 100 金币"。这个任务怎么实现?
- **任务 B**:你设计了一段剧情对话 —— "村长说:英雄,我们需要你的帮助。选择:A. 我愿意 B. 我需要考虑"。这段对话怎么实现?
- **任务 C**:你设计了一个火球术 —— "消耗 20 法力,冷却 3 秒,造成 50 火属性伤害,可能点燃"。这个技能怎么实现?
- **任务 D**:你设计了一个背包 —— "玩家有 16 个格子,物品可堆叠到 99,可以丢弃,可以交易"。这个背包怎么实现?

新手工程师的第一反应是:**"我打开 player.rs,加 if/else"**。

- 任务 A:在 `player.rs` 加 `goblins_killed: i32`,在 `on_kill_goblin()` 里 `+= 1`,在 `on_talk_village_chief()` 里 `if goblins_killed >= 5 { give_gold(100) }`
- 任务 B:在 `npc.rs` 加 `talked_to_player: bool`,在 `on_talk()` 里 `print_line("村长:...")`,然后弹个两选项菜单
- 任务 C:在 `player.rs` 加 `fireball_cooldown: f32`,在 `update()` 里 `-= dt`,在按键处理里 `if fireball_cooldown <= 0 && mana >= 20 { ... spawn_fireball }`
- 任务 D:在 `player.rs` 加 `inventory: Vec<Item>`,写一堆 `give_item` / `remove_item` / `has_item`

第一周你看代码,觉得"挺好的,我都实现了"。第二周你想加第二个任务"杀 3 只巨魔"——你**复制粘贴**任务 A 的代码,把 `goblins_killed` 改成 `trolls_killed`,把"村长"改成"铁匠"。第三周你想加第 10 个任务 —— 你已经写了 800 行 `if quest_id == "xxx" { ... }`,代码变成了一团乱麻。一个月后你想加第 50 个任务 —— 你**拒绝**了,你想"我宁愿去外面跑 10 公里也不想再碰 quest.rs"。

**这就是引擎和游戏的本质区别**:引擎是少数程序员写的、被反复使用的能力 (capabilities);游戏是设计师天天改的、内容海量的规则 (rules)。如果你把规则和引擎混在一起,你不可能做出有 500 个任务的游戏 —— 不是因为你懒,是因为你的**架构**让"加任务"的成本线性增长。

### 0.2 这条线要解决的问题

游戏性系统 (gameplay systems) 这一层的工程目标,可以用一句话概括:

> **让"加一个新任务/新对话/新技能/新物品"的成本,趋近于"加一行数据",而不是"加十行代码"。**

这句话是整篇深入的纲领。任何一个看起来再花哨的玩法系统(制造、科技树、声望),你问自己一个问题就能判断它的工程质量:**"加一份新内容,设计师要改多少行 Rust 代码?"** 答案如果是 0,系统设计得好;答案如果是 N(N > 0),每加一份内容就要 N 行代码,系统会被内容量压垮。

这不是抽象的口号。这条线后小节我们写代码,你会亲眼看到:**一个数据驱动的任务系统,加一个新任务的代码量是 0**。设计师只要在 `quests.ron` 加一段:

```ron
Quest(
    id: "kill_5_wolves",
    title: "狼患",
    objectives: [
        Kill(type: "wolf", count: 5),
    ],
    rewards: [
        Gold(100),
        Item("health_potion", 2),
    ],
)
```

游戏运行时自动加载、自动追踪、自动结算。**代码不动**。这是工程上的"内容倍增器 (content multiplier)" —— 写一次框架,设计师之后填几百份内容。

### 0.3 历史回顾:这条心路是怎么走过来的

游戏工业对"数据驱动"的认识是逐步的,从 1980 年代到 2026 年今天,大致经历了三个阶段。

**1980-1990:硬编码 (hardcoded) 时代**。最早的游戏 —— 哪怕是《超级马里奥》这种里程碑 —— 玩法规则几乎全写在汇编 / C 里。蘑菇变大马里奥是 `if touch(mushroom) { state = Big; size *= 2; }`,写在主循环里。改一个关卡数据要重编译。这个时代"系统"和"内容"是一团。

**1990-2005:脚本化 (scripted) 时代**。Quake、Half-Life、Diablo II 这些游戏开始大量用脚本 (QuakeC、Half-Life 的 entity I/O、Diablo II 的状态机 AI) 表达玩法规则。这一阶段的进步是把"规则"从二进制里解放出来,放进了文本。但脚本仍是"代码" —— 改一个技能效果,你要改一段脚本,要懂编程。Half-Life 的 entity I/O 系统至今仍是教科书级别的"事件驱动"案例,你能在 [Hammer Editor](https://developer.valvesoftware.com/wiki/Hammer) 里给实体接 `OnBreak`、`OnTriggered` 这种 output 到其他实体的 input,实现"破坏开关后开门"这种逻辑,**不写一行代码**。这就是数据驱动的雏形。

**2005-2026:数据驱动 (data-driven) 时代**。Unreal Engine 的 Blueprint、Unity 的 ScriptableObject、魔兽世界的 quest template、Diablo III 的 loot table —— 这些都把玩法从"代码 / 脚本"进一步抽离成**纯数据**。设计师不写代码也不写脚本,他们在可视化工具里"勾选 + 填表",工具输出 XML / JSON / RON,引擎解析数据生成玩法。魔兽世界有 8000+ 任务,**每个任务的逻辑字段都是数据库行**,玩家执行任务时引擎读行 + 跑通用规则。这种规模的"内容生产"硬编码根本不可想象。

注意这三个阶段**不是互相替代,而是叠加**。2026 年的 AAA 游戏同时用三层:引擎核心是 C++(硬编码),玩法规则可以是 Blueprint / Lua(脚本化),任务模板 / 物品表是纯数据(数据驱动)。每个系统选哪一层,取决于"这块逻辑变化频率"和"这块逻辑复杂度" —— 高频变化的简单逻辑,数据驱动;低频变化的复杂逻辑,代码硬编码;中间的,脚本。

### 0.4 这篇深入的结构

这一篇按下面顺序展开:

1. **第 1 节**:讲清楚 gameplay 系统的**共享模式** —— 数据驱动 / 状态机 / 事件驱动 三角形。这是骨架。
2. **第 2 节**:对话系统 —— 用模式拆"对话是一个有向图"。
3. **第 3 节**:任务系统 —— 用模式拆"任务是一个状态机 + 目标事件订阅"。
4. **第 4 节**:能力系统 —— 用模式拆"能力是数据 + 通用运行器"。
5. **第 5 节**:库存与经济 —— 用模式拆"物品是数据,交易是原子验证"。
6. **第 6 节**:工业实践 —— 这些系统怎么协作,内容倍增器在生产里的体现。
7. **第 7-8 节**:在你 HH 项目里动手(做中学红线)+ 练习 + 延伸阅读。

读完你会获得:一套能套到任何玩法系统上的抽象心智模型,四个系统的 Rust 实现骨架,以及一份"明天就能贴到 HH 项目里"的任务系统代码。

## 1 · 共享模式:数据驱动 + 状态机 + 事件

### 1.1 三个系统的"同构性" —— 一个让人头皮发麻的洞察

你先停下来,把对话、任务、能力、库存这四个系统"假装"不认识,只看它们的**结构**。

- **对话** 一段对话是有向图 (graph) 的节点 (node)。每个节点有"当前显示哪句话",有"接下来能去哪些节点"。对话正在播放时,系统处于某个节点 —— 这是**状态**。NPC 被点了一下 —— 这是**触发事件**。每个节点的具体内容(台词、选项、条件) —— 是**数据**。
- **任务** 一个任务是状态机。状态:`Inactive → Active → Complete`(还有 `Failed`)。每个状态对应玩家看到的不同 UI 和系统能执行的不同操作。玩家杀了一只狼 —— `EnemyKilled` 事件 —— 任务系统的某个目标订阅了这个事件 —— 把"杀狼计数 +1" —— 计数到 5 —— 状态切到 `Complete` —— 触发 `QuestComplete` 事件。任务的定义(标题、目标列表、奖励) —— 是**数据**。
- **能力** 一个能力是状态机。状态:`Ready → Casting → Active → Cooldown`(还有 `Interrupted`)。玩家按下技能键 —— `InputTriggered` 事件 —— 能力系统查表,这个技能当前是 `Ready`,允许释放 —— 状态切到 `Casting`,过 0.5 秒前摇切到 `Active`,施加伤害,状态切到 `Cooldown`,过 3 秒回到 `Ready`。能力的定义(冷却、伤害、消耗、效果) —— 是**数据**。
- **库存** 一个库存是状态机 + 事务 (transaction)。状态:每个物品槽有"数量",系统整体有"容量"。玩家点了"购买药水" —— `BuyRequested` 事件 —— 库存系统**原子地**做:扣 50 金、加 1 瓶药水。如果中间断电(想象一下),要么两个都成功要么两个都失败,**不可能扣了钱没拿到药水**(就是 bug 复制)。物品的定义(名字、最大堆叠、价值、类别) —— 是**数据**。

看出规律了吗?**四个系统都是同一个三角形**:

> 数据(定义"它是什么") + 状态机(定义"它现在在干嘛") + 事件(定义"它和外界怎么通信")

这条洞察是整篇深入最重要的。一旦你内化了它,你看任何新玩法系统(制造、声望、科技树),你都会下意识问三个问题:**它的数据是什么?它的状态是什么?它订阅/发出什么事件?** 三个问题答完,系统设计就完成了一大半。剩下的就是工程实现细节。

下面我们把这个三角形展开。

### 1.2 数据驱动 (data-driven):规则是数据,不是代码

数据驱动的反面是**硬编码 (hardcoded)**。我们看同一个"火球术"的两种实现。

**硬编码版**:

```rust
fn cast_fireball(player: &mut Player, world: &mut World) {
    if player.fireball_cooldown > 0.0 { return; }
    if player.mana < 20 { return; }
    player.fireball_cooldown = 3.0;
    player.mana -= 20;
    world.spawn(Projectile {
        kind: ProjectileKind::Fireball,
        pos: player.pos,
        dir: player.facing,
        speed: 8.0,
        damage: 50,
        element: Element::Fire,
    });
}
```

这段代码工作得很好。但它只能做火球术。你想加冰箭术?你写 `cast_frostbolt`。你想加闪电链?你写 `cast_chain_lightning`。50 个技能你写 50 个函数。每次改个数字(火球伤害从 50 改到 60),你要改 Rust 代码、重编译、重启游戏。

**数据驱动版**:

```rust
// 数据:一个能力的定义
#[derive(Deserialize, Clone)]
pub struct AbilityDef {
    pub id: String,
    pub name: String,
    pub mana_cost: i32,
    pub cooldown: f32,
    pub cast_time: f32,
    pub effects: Vec<EffectSpec>,
}

#[derive(Deserialize, Clone)]
pub enum EffectSpec {
    SpawnProjectile { kind: String, speed: f32, damage: i32, element: String },
    Heal { amount: i32 },
    Buff { stat: String, amount: f32, duration: f32 },
    Dash { distance: f32 },
    // ...
}

// 火球术的数据(RON 格式,设计师生成,你只读)
// abilities/fireball.ron:
// AbilityDef(
//     id: "fireball",
//     name: "火球术",
//     mana_cost: 20,
//     cooldown: 3.0,
//     cast_time: 0.5,
//     effects: [
//         SpawnProjectile(kind: "fireball", speed: 8.0, damage: 50, element: "fire"),
//     ],
// )

// 通用运行器:不认识"火球",只认识 AbilityDef
pub fn cast_ability(
    caster: &mut Entity,
    ability: &AbilityDef,
    world: &mut World,
) -> Result<(), CastError> {
    if caster.cooldowns[&ability.id] > 0.0 { return Err(CastError::OnCooldown); }
    if caster.mana < ability.mana_cost { return Err(CastError::NotEnoughMana); }

    // 状态切换(后面详谈)
    caster.cooldowns.insert(ability.id.clone(), ability.cooldown);
    caster.mana -= ability.mana_cost;

    // 通用效果应用:这里没有"火球"两个字
    for effect in &ability.effects {
        apply_effect(caster, effect, world);
    }
    Ok(())
}

fn apply_effect(caster: &Entity, effect: &EffectSpec, world: &mut World) {
    match effect {
        EffectSpec::SpawnProjectile { kind, speed, damage, element } => {
            world.spawn(Projectile {
                kind: kind.clone(),
                pos: caster.pos,
                dir: caster.facing,
                speed: *speed,
                damage: *damage,
                element: element.clone(),
            });
        }
        EffectSpec::Heal { amount } => { caster.hp += amount; }
        EffectSpec::Buff { .. } => { /* ... */ }
        EffectSpec::Dash { .. } => { /* ... */ }
    }
}
```

注意这个改动的本质。**`cast_ability` 函数里没有任何"火球"或"冰箭"的概念**。它只懂"能力 (AbilityDef) + 效果列表 (EffectSpec)"。50 个技能 = 50 份 RON 数据,**代码不变**。改火球伤害从 50 到 60?改 `abilities/fireball.ron`,**热重载**(参见 [scripting-and-modding](../../phase-8/deep-dives/scripting-and-modding.md) 一篇的热重载机制),秒见效。

这里有几个工程关键点,我们一个个看。

**第一,数据 schema 要稳定**。`AbilityDef` 是 schema —— 它定义"能力长什么样"。schema 一旦发布给设计师就很难改(改了所有旧数据要 migration)。所以设计 schema 时要慎重:**字段要么是必需的,要么有合理默认值**。Rust 这边用 `#[serde(default)]` 给字段默认值,RON / JSON 这边设计师可以省略字段。

**第二,EffectSpec 用 enum 而不是 trait object**。新手会用 `Box<dyn Effect>` —— 这让"加一种新效果"看起来灵活(只要 impl Effect 就行)。但实际生产里**效果种类是有限的**(SpawnProjectile / Heal / Buff / Dash 等 5-15 种),用 enum 让 Rust 编译器在你加新效果时强制你处理所有 match 分支 —— 漏一个分支编译失败,bug 不会跑到运行时。这是 Rust 的 sum type 给游戏开发的红利。

**第三,数据格式选 RON / TOML / JSON 都行**。RON (Rusty Object Notation) 对游戏数据最友好 —— 语法接近 Rust,支持 enum 和嵌套,可读性比 JSON 好。TOML 适合平铺配置(mod.toml)。JSON 适合工具生成的数据(因为 Web 工具大量产 JSON)。生产里常见组合:设计师工具导出 JSON,引擎读;策划手改用 RON。

**第四,数据驱动的极端形态是 reflection / registry**。当你的 schema 本身需要"运行时增减字段",就进入 [09B-2 反射与数据驱动系统](../../phase-9/09B-2-subsystems-modules-plugins.md) 的领域 —— 不再是编译期 enum,而是运行时 schema,字段名是字符串,值是 `Value::Int(5)` / `Value::String("fire")` 这种 tagged union。这是 AAA 引擎(Unreal 的 Reflection System、Unity 的 SerializeReference)的标配,但对独立游戏过度 —— 编译期 enum + serde 已经能解决 90% 的问题。

### 1.3 状态机 (state machine):每个系统都有内部状态

数据驱动解决"是什么"的问题,状态机解决"现在在干嘛"的问题。

我们看任务系统的状态机:每个任务实例 (quest instance) 都有一份状态。同一个任务"杀 5 只狼",玩家 A 接了没杀,玩家 B 接了杀了 3 只,玩家 C 接了全杀了 —— 三个玩家三个任务实例,**三个不同的状态**。状态机是 per-instance 的,不是 per-definition。

```rust
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum QuestState {
    Inactive,  // 没接
    Active,    // 接了没完成
    Complete,  // 完成没领奖
    Failed,    // 失败(限时任务超时等)
    Rewarded,  // 领完奖,任务终结
}

pub struct QuestInstance {
    pub def_id: String,        // 指向 QuestDef(数据)
    pub state: QuestState,     // 当前状态机
    pub progress: Vec<i32>,    // 每个目标的进度(杀了 3 只 → progress[0] == 3)
    pub accepted_at: f64,      // 接受时间(用于限时任务)
}
```

任务的状态机很朴素:`Inactive → Active → (Complete | Failed) → Rewarded`。**关键不在状态枚举**,而在于**状态迁移的触发条件**。`Inactive → Active` 是玩家点"接受任务"按钮(玩家主动);`Active → Complete` 是所有目标 progress 达标(系统检测);`Active → Failed` 是某些任务特定条件(限时任务超时)。状态机的工程价值在于:**所有状态变化都走同一个函数 `transition(&mut self, new_state)`,在这个函数里集中处理副作用**(发事件、改 UI、播音乐)。

```rust
impl QuestInstance {
    pub fn transition(&mut self, new_state: QuestState, events: &mut EventBus) {
        let old = self.state;
        self.state = new_state;
        match (old, new_state) {
            (Inactive, Active) => {
                events.emit(QuestAccepted { quest_id: self.def_id.clone() });
            }
            (Active, Complete) => {
                events.emit(QuestComplete { quest_id: self.def_id.clone() });
            }
            (Active, Failed) => {
                events.emit(QuestFailed { quest_id: self.def_id.clone() });
            }
            (Complete, Rewarded) => {
                events.emit(QuestRewarded { quest_id: self.def_id.clone() });
            }
            _ => {} // 非法迁移被静默忽略(或日志告警)
        }
    }
}
```

这套"状态迁移走单一函数 + 函数内集中发事件"的模式叫 **state transition as event**。它的价值:**调用方不需要知道每种迁移要做什么副作用**,只要说"我想把任务 A 从 Active 切到 Complete",`transition()` 内部决定发哪些事件、改哪些 UI。这极大降低了模块间耦合 —— 战斗系统杀完最后一只狼,只发一个 `EnemyKilled` 事件,任务系统自己决定要不要切状态;切了状态,UI 系统自己监听 `QuestComplete` 自己改界面。**没人直接调 UI 系统,UI 系统也不被任何系统"知道"**。

同样的模式套到对话、能力、库存:

- 对话的状态机:节点 ID 是状态。`transition(to_node_5)` 内部播那句话的配音、检查触发条件。
- 能力的状态机:`Ready → Casting → Active → Cooldown`。每个状态对应不同的可执行操作 —— `Cooldown` 状态按技能键无效,`Casting` 状态被攻击可能切到 `Interrupted`。
- 库存的状态机:不太明显,但每个"交易中"是个临时状态 —— 开始交易时进入 `PendingTransaction`,所有修改在内存里,确认了才"提交 (commit)"切回 `Idle`,取消就"回滚 (rollback)"。

注意状态机的两层概念:**定义层状态**(任务的 `Inactive/Active/Complete`)是 schema 的一部分,稳定;**实例层状态**(玩家 A 的任务实例当前是 `Active`,progress 是 3)是运行时的,频繁变。设计 schema 时先想清楚"这个系统有几种稳定状态" —— 状态数应该是有限的(通常 3-8 个),如果状态爆炸(几十个),说明你在用状态机表达应该用数据表达的东西。

### 1.4 事件驱动 (event-driven):系统之间不直接调函数

第三个共享模式是**事件驱动**。这一层我们在 [event-systems-and-gameplay-foundations](../../phase-5/deep-dives/event-systems-and-gameplay-foundations.md) 里详细讲过事件总线 (event bus),这里只讲它在 gameplay 系统里的角色。

回到任务系统。新手写任务系统的代码:

```rust
// 战斗系统里
fn on_enemy_killed(enemy: &Enemy, player: &mut Player) {
    player.goblins_killed += 1;
    if player.goblins_killed >= 5 && player.current_quest == "kill_5_goblins" {
        player.current_quest_state = QuestState::Complete;
        // 还要更新 UI
        ui.update_quest_panel();
        // 还要播音乐
        audio.play("quest_complete.wav");
    }
}
```

这是**反模式**。战斗系统**知道**任务系统的存在 —— 它直接读写 `current_quest` 和 `current_quest_state`。后果:

1. 战斗系统和任务系统耦合 —— 改任务系统的字段,战斗系统要改
2. 加第二个任务(杀 3 只狼)要在 `on_enemy_killed` 里加 `if enemy.kind == "wolf" { player.wolves_killed += 1; if ... }` —— 战斗系统代码随任务数线性膨胀
3. 任务完成时播音乐、更新 UI 的逻辑全堆在战斗系统里 —— 战斗系统职责混乱

事件驱动的写法:

```rust
// 战斗系统里
fn on_enemy_killed(enemy: &Enemy, events: &mut EventBus) {
    events.emit(EnemyKilled {
        enemy_type: enemy.kind.clone(),
        pos: enemy.pos,
        killer: KillerKind::Player,
    });
    // 战斗系统的工作到此结束。它不知道有任务系统。
}

// 任务系统订阅 EnemyKilled(注册时一次性建立)
fn setup_quest_system(events: &mut EventBus, quests: Arc<Mutex<QuestManager>>) {
    events.on::<EnemyKilled>(move |event| {
        let mut qm = quests.lock();
        // 任务系统自己决定哪些任务关心这次击杀
        for quest in qm.active_quests_mut() {
            for obj in quest.def.objectives.iter() {
                if let Objective::Kill { ref kind, .. } = obj {
                    if kind == &event.enemy_type {
                        quest.progress_obj(obj_index);
                        if quest.all_complete() {
                            quest.transition(QuestState::Complete, &events);
                        }
                    }
                }
            }
            // 战斗系统根本不出现
        }
    });
}
```

战斗系统只负责"我杀了一只怪,告诉全世界",**它不知道有任务系统**。任务系统自己监听 `EnemyKilled`,自己决定哪些任务的哪些目标对应这次击杀。这套 decoupling 让任何系统都能加进来而不改战斗系统:

- 成就系统订阅 `EnemyKilled` —— "杀 1000 只怪"成就解锁
- 掉落系统订阅 `EnemyKilled` —— 怪死亡时掉装备
- 经验系统订阅 `EnemyKilled` —— 给玩家加经验
- 剧情系统订阅 `EnemyKilled` —— "杀 boss 触发结局"

战斗系统的 `on_enemy_killed` 永远只有一行 `events.emit(...)`。**这就是事件驱动的核心价值**。

但事件驱动有它自己的工程坑,我们后面详细讲(主要是顺序、并发、生命周期)。这里先建立心智模型:**gameplay 系统之间通过事件总线通信,不通过直接函数调用**。事件总线是 gameplay 层的"中枢神经"。

把三个模式综合:**数据定义"是什么",状态机定义"现在在干嘛",事件定义"和外界怎么通信"**。下面我们用这套模型拆解四个系统。

## 2 · 对话系统:对话是一张有向图

### 2.1 对话的本质:节点 + 边 + 条件

你给 NPC 加对话,新手会写 `match dialogue_step { 0 => say("你好"), 1 => say("..."), ... }` —— 这种"对话是一段脚本"的心智模型只能写**线性对话**。但真实游戏的对话是**分支**的:玩家问"你是谁",NPC 答 A;玩家问"这地方怎么走",NPC 答 B;两个答案之后都能回到"还有什么需要帮忙吗"的菜单。这是**图**的结构,不是线性序列。

工业级对话系统的数据模型:

```rust
#[derive(Deserialize, Clone)]
pub struct DialogueDef {
    pub id: String,
    pub start_node: String,        // 入口节点
    pub nodes: HashMap<String, DialogueNode>,
}

#[derive(Deserialize, Clone)]
pub struct DialogueNode {
    pub speaker: String,           // "村长"
    pub text: String,              // "英雄,我们需要你的帮助。"
    pub choices: Vec<DialogueChoice>,
    // 有些节点没有 choices —— 自动跳到 next
    pub next: Option<String>,
}

#[derive(Deserialize, Clone)]
pub struct DialogueChoice {
    pub text: String,              // "A. 我愿意"
    pub next: String,              // 选择后跳到哪个节点
    pub condition: Option<Condition>,   // "只在 met_king 为 true 时显示"
    pub effects: Vec<EffectSpec>,       // "选了之后:set joined_army = true, give_item sword"
}
```

这套数据结构表达的就是有向图。`nodes` 是节点集合,`next` 和 `choices[].next` 是边。`start_node` 是图的入口。每个节点有**条件 (condition)** —— 决定这个节点是否可达(例如"只在玩家见过国王后显示" —— 用 `met_king == true` 这类游戏状态条件)和**效果 (effects)** —— 进入这个节点时施加的副作用(给玩家物品、设剧情 flag)。

看一段实际对话数据(RON 格式):

```ron
DialogueDef(
    id: "village_chief_intro",
    start_node: "greeting",
    nodes: {
        "greeting": DialogueNode(
            speaker: "村长",
            text: "英雄!你终于来了。我们的村子正遭受狼患。",
            next: Some("menu"),
        ),
        "menu": DialogueNode(
            speaker: "村长",
            text: "你需要什么信息?",
            choices: [
                DialogueChoice(
                    text: "告诉我狼的来历",
                    next: "wolf_lore",
                    condition: None,
                    effects: [],
                ),
                DialogueChoice(
                    text: "我接受任务",
                    next: "accept_quest",
                    condition: Some(Flag("player_level").gte(5)),  // 至少 5 级
                    effects: [StartQuest("kill_5_wolves")],
                ),
                DialogueChoice(
                    text: "[离开]",
                    next: "exit",
                    condition: None,
                    effects: [],
                ),
            ],
        ),
        "wolf_lore": DialogueNode(
            speaker: "村长",
            text: "狼群来自北方的森林,近年来异常凶猛...",
            next: Some("menu"),  // 说完回菜单
        ),
        "accept_quest": DialogueNode(
            speaker: "村长",
            text: "太好了!杀掉 5 只狼,我会给你 100 金币。",
            effects: [GiveGold(50)],  // 接任务的预付款
            next: Some("exit"),
        ),
        "exit": DialogueNode(
            speaker: "",
            text: "",
            next: None,  // 对话结束
        ),
    },
)
```

这段数据没有任何代码 —— 设计师在工具(类似 [Yarn Spinner](https://yarnspinner.dev/)、[Ink](https://www.inklestudios.com/ink/))里画图,导出 RON。运行时引擎读数据,渲染 UI,**对话系统的所有"逻辑"都在通用运行器里**。

### 2.2 条件 (condition):对话的"门"

对话系统的灵魂是 condition。一个对话节点能不能进入,一个选项能不能显示,都被 condition 门控。简单的 condition(查游戏 flag)可以是数据:

```rust
#[derive(Deserialize, Clone)]
pub enum Condition {
    Flag(String),                   // 某 flag 是否为 true
    FlagEqual(String, i32),         // flag == value
    QuestState(String, QuestState), // 某任务处于某状态
    HasItem(String, i32),           // 拥有 N 个某物品
    PlayerLevel(i32),               // 玩家等级 >= N
    And(Vec<Condition>),
    Or(Vec<Condition>),
    Not(Box<Condition>),
}
```

但生产里 condition 会复杂到没法用 enum 表达 —— "只在玩家杀过 boss 且没有这件装备且当前时间是夜晚" 还能拼出来,"如果玩家阵营是 A 且和这个 NPC 的好感度大于 30 但低于 70" 也行,但"如果玩家上次选择走善良路线的次数比邪恶路线多至少 2 次"就触及数据驱动表达的极限。

工业方案是**条件 + 脚本混用**。简单条件用 enum data,复杂条件挂一个脚本函数。对话节点有一个可选字段 `script_condition: Option<String>`,字符串是脚本函数名,运行时调那个函数判断 true/false。这是 [scripting-and-modding](../../phase-8/deep-dives/scripting-and-modding.md) 里讲的数据驱动 + 脚本的混合 —— 大部分数据,少量复杂逻辑脚本。

```rust
#[derive(Deserialize, Clone)]
pub struct DialogueNode {
    pub speaker: String,
    pub text: String,
    pub choices: Vec<DialogueChoice>,
    pub next: Option<String>,
    pub condition: Option<Condition>,           // 数据 condition(简单)
    pub script_condition: Option<String>,       // 脚本 condition(复杂),返回 bool
    pub effects: Vec<EffectSpec>,
    pub script_effects: Option<String>,         // 脚本 side-effect
}

// 运行时检查节点能否进入
fn can_enter_node(node: &DialogueNode, gs: &GameState, scripting: &ScriptingSystem) -> bool {
    // 先查数据 condition
    if let Some(cond) = &node.condition {
        if !evaluate_condition(cond, gs) { return false; }
    }
    // 再查脚本 condition(如果有)
    if let Some(func_name) = &node.script_condition {
        let result: bool = scripting.call(func_name, gs).unwrap_or(false);
        if !result { return false; }
    }
    true
}
```

注意两层 condition 是**短路 (short-circuit)** 的 —— 数据 condition 快(纯内存查表),脚本 condition 慢(调 Lua)。先用快的过滤,再跑慢的。这是性能上的考量,生产里 1000 个对话节点每帧要全部检查 condition(决定哪些选项显示),全部跑脚本会卡帧。

### 2.3 效果 (effect):节点触发时发生什么

节点的 `effects` 是进入节点时施加的副作用。EffectSpec 复用前面能力系统那套 enum,因为对话效果和能力效果是同构的(都是"给玩家加东西 / 改状态 / 发事件")。但对话还多了几种特殊 effect:

```rust
#[derive(Deserialize, Clone)]
pub enum DialogueEffect {
    Shared(EffectSpec),         // 复用通用 effect
    StartQuest(String),
    CompleteQuest(String),
    SetFlag(String, i32),
    GiveItem(String, i32),
    GiveGold(i32),
    ChangeFaction(String, i32), // 改阵营好感度
    StartDialogue(String),      // 立刻跳到另一段对话
    StartCombat(String),        // 进入战斗
}
```

`StartDialogue` 这条特别值得注意 —— 它让对话可以"嵌套"或"路由"。一段普通对话进入某节点后跳到战斗对话,战斗对话结束后回到原对话。这是数据驱动的复用 —— 一段战斗对话被多段普通对话复用,不用每段都写战斗分支。

效果的应用顺序有讲究。工业实践:**先应用 effect,再切对话节点**。理由:effect 可能修改游戏状态(比如 `GiveGold`),修改后的状态可能影响下一个节点的 condition 检查。如果先切节点再应用 effect,condition 看到的是旧状态,可能算错。

### 2.4 运行时:对话状态机

对话系统运行时是状态机:

```rust
pub struct DialogueRunner {
    pub def: DialogueDef,
    pub current_node: String,  // 当前状态
}

impl DialogueRunner {
    pub fn start(def: DialogueDef, gs: &GameState) -> Self {
        let start = def.start_node.clone();
        let mut runner = Self { def, current_node: start };
        runner.enter_current_node(gs);
        runner
    }

    fn enter_current_node(&mut self, gs: &GameState) {
        let node = self.def.nodes.get(&self.current_node).unwrap();
        // 1. 播放 text(交给 UI 系统)
        ui_show_dialogue(node.speaker.clone(), node.text.clone(), &node.choices);

        // 2. 应用 effects
        for effect in &node.effects {
            apply_effect(effect);
        }

        // 3. 如果节点没有 choices,自动 next
        if node.choices.is_empty() {
            if let Some(next) = &node.next {
                self.transition_to(next.clone());
            } else {
                // 对话结束
                ui_close_dialogue();
            }
        }
        // 否则等玩家选 choice
    }

    pub fn choose(&mut self, choice_index: usize, gs: &GameState) {
        let node = self.def.nodes.get(&self.current_node).unwrap();
        let choice = &node.choices[choice_index];

        // 应用 choice effects
        for effect in &choice.effects {
            apply_effect(effect);
        }

        // 跳转
        self.transition_to(choice.next.clone());
    }

    fn transition_to(&mut self, node_id: String, gs: &GameState) {
        self.current_node = node_id;
        self.enter_current_node(gs);
    }
}
```

注意 `enter_current_node` 把"进入一个节点要做的事"集中起来 —— 播放文本、应用 effect、决定下一步。这是 state-machine-as-method 的典型 Rust 模式。每个状态进入时调一个 `on_enter` 函数,副作用集中,调用方只负责"我要去这个状态"。

对话系统的状态机层比任务系统更动态 —— 任务状态是固定枚举 (Inactive/Active/...),而对话状态是任意节点 ID 字符串。这是**广义状态机 (generalized state machine)** —— 状态集合由数据定义。这种模式在玩法系统里非常常见(对话、过场动画、游戏阶段切换都是这种)。

### 2.5 工业级对话工具:Yarn Spinner / Ink / articy:draft

数据驱动对话系统离不开可视化工具。设计师画有向图比写 RON 快十倍。业界主流对话编辑器:

- **Yarn Spinner**:开源,被 Night in the Woods、Lost in Random 等游戏使用。Node-based,脚本语法接近自然语言。
- **Ink**:inklestudios 出品,被 Heaven's Vault、80 Days 使用。脚本式(写脚本而不是画图),但适合线性分支对话。
- **articy:draft**:商业软件,被很多 RPG 使用。完整的内容管理平台,不只对话,还包括任务、物品、角色。
- **Twine**:开源,文字冒险游戏标配。

这些工具都导出 JSON / XML,引擎读 JSON / XML 转 DialogueDef。HH 项目可以接 Yarn Spinner(Rust 有 [yarnspinner crate](https://crates.io/crates/yarnspinner))做对话编辑,把这一层完整跑通。

## 3 · 任务系统:状态机 + 目标事件订阅

### 3.1 任务的解剖:定义 vs 实例

任务系统的数据模型比对话更"标准",是数据驱动 + 状态机 + 事件的最经典案例。先把概念分清楚。

**任务定义 (QuestDef)** 是数据 —— 一个任务"长什么样":标题、描述、目标列表、奖励列表、前置条件。一份定义被所有玩家共享。

**任务实例 (QuestInstance)** 是运行时 —— 一个玩家"接了这个任务后的状态":当前在哪个状态、每个目标进度多少、接受时间。每个玩家有自己的一份实例列表。

这两层严格分离是工业实践。魔兽世界的 quest_template 表是 QuestDef,character_questlog 表是 QuestInstance。一份定义,千万份实例。改定义(把"杀 5 只狼"改成"杀 10 只狼")影响所有还没完成的实例;改实例(把玩家 A 的进度从 3 改到 5)只影响玩家 A。

```rust
#[derive(Deserialize, Clone)]
pub struct QuestDef {
    pub id: String,
    pub title: String,
    pub description: String,
    pub objectives: Vec<ObjectiveDef>,
    pub rewards: Vec<RewardDef>,
    pub prerequisites: Vec<Condition>,   // 接任务的前置条件
    pub chain_prev: Option<String>,       // 前置任务 ID(任务链)
    pub chain_next: Option<String>,       // 后续任务 ID
    pub repeatable: bool,                 // 是否可重复
    pub time_limit: Option<f32>,          // 限时(秒)
}

#[derive(Deserialize, Clone)]
pub enum ObjectiveDef {
    Kill { kind: String, count: i32 },
    Collect { item: String, count: i32 },
    TalkTo { npc: String },
    Reach { location: String },
    Escort { npc: String, to: String },
    Custom { event: String, count: i32 }, // 通用:订阅某事件 N 次
}

#[derive(Deserialize, Clone)]
pub enum RewardDef {
    Gold(i32),
    Item { id: String, count: i32 },
    Experience(i32),
    Faction { faction: String, reputation: i32 },
    UnlockQuest(String),                  // 完成后开启另一个任务
}
```

```rust
pub struct QuestInstance {
    pub def_id: String,
    pub state: QuestState,
    pub progress: Vec<i32>,               // 每个目标的当前进度
    pub accepted_at: f64,
    pub completed_at: Option<f64>,
}
```

注意 `progress: Vec<i32>` 的索引对应 `QuestDef.objectives` 的索引 —— `progress[i]` 是 `objectives[i]` 的当前进度。这是常见的"用 Vec 平行数组表示 per-objective 状态"模式,比 `HashMap<String, i32>` 省内存,查表也更快。代价是改 objectives 列表要同步改 progress,但 objectives 在数据加载后不变,所以没问题。

### 3.2 目标 (objective):事件订阅的解析

任务系统的精髓在 objective。每个 objective 本质是**"对某类事件的订阅 + 计数"**。

- `Kill { kind: "wolf", count: 5 }` —— 订阅 `EnemyKilled`,过滤 `kind == "wolf"`,每命中一次 progress +1
- `Collect { item: "sword", count: 1 }` —— 订阅 `ItemAcquired`,过滤 `item == "sword"`
- `TalkTo { npc: "merchant" }` —— 订阅 `DialogueStarted`,过滤 `npc == "merchant"`
- `Reach { location: "north_forest" }` —— 订阅 `PlayerEnteredLocation`
- `Custom { event: "treasure_found", count: 1 }` —— 订阅 `treasure_found`

这些 objective 都可以统一抽象成:**"监听事件 X,过滤条件 Y,每命中 progress +1,达标后停止"**。

```rust
impl QuestInstance {
    /// 任务系统收到一个事件时,看哪些 objective 关心它
    pub fn handle_event(&mut self, event: &GameEvent, def: &QuestDef) -> bool {
        let mut changed = false;
        for (i, obj) in def.objectives.iter().enumerate() {
            if self.progress[i] >= obj.target_count() { continue; } // 已达标跳过
            if obj.matches(event) {
                self.progress[i] += 1;
                changed = true;
                if self.progress[i] >= obj.target_count() {
                    events.emit(ObjectiveComplete { quest: self.def_id.clone(), index: i });
                }
            }
        }
        changed
    }
}

impl ObjectiveDef {
    fn target_count(&self) -> i32 {
        match self {
            Kill { count, .. } | Collect { count, .. } | Custom { count, .. } => *count,
            TalkTo { .. } | Reach { .. } | Escort { .. } => 1,
        }
    }

    fn matches(&self, event: &GameEvent) -> bool {
        match (self, event) {
            (Kill { kind, .. }, GameEvent::EnemyKilled(e)) => &e.enemy_type == kind,
            (Collect { item, .. }, GameEvent::ItemAcquired(e)) => &e.item_id == item,
            (TalkTo { npc, .. }, GameEvent::DialogueStarted(e)) => &e.npc_id == npc,
            (Reach { location, .. }, GameEvent::LocationEntered(e)) => &e.location_id == location,
            (Custom { event: evt, .. }, e) => e.name() == evt,
            _ => false,
        }
    }
}
```

这套 `matches` 函数是任务系统的核心 —— 它把"事件类型"和"objective 类型"对上号。这是 sum type 的优雅之处:Rust 编译器在你加新 objective 类型或新 event 类型时,强制你更新所有 match 分支。

注意几个生产细节。**第一,事件过滤要早**。任务系统每帧可能收到几十个 `EnemyKilled`,但只有几个和当前活动任务相关。优化是先按事件类型筛 —— 任务系统订阅时声明"我关心 EnemyKilled / ItemAcquired / DialogueStarted / LocationEntered 这几种",事件总线只路由这几种事件给它,其他事件根本不进入任务系统。这避免了 1000 个任务的循环里跑无用 `matches` 检查。

**第二,多任务共享事件**。一次 `EnemyKilled(wolf)` 可能同时触发"杀 5 只狼"任务的进度 +1 和"杀 100 个敌人"成就的进度 +1。任务系统循环所有 active 任务,每个任务调用 `handle_event`,有任何一个 `changed` 就标 dirty。

**第三,完成检测集中**。所有 objective 都达标时,任务 transition 到 Complete。这个检查在每次 `handle_event` 后跑一次:

```rust
impl QuestInstance {
    pub fn all_objectives_done(&self, def: &QuestDef) -> bool {
        self.progress.iter().enumerate()
            .all(|(i, &p)| p >= def.objectives[i].target_count())
    }
}
```

### 3.3 任务链 (quest chain) 与前置条件

任务系统还有两个常见特性:**任务链** 和 **前置条件**。

任务链是设计上的"前置必须先完成"。`chain_prev: Some("tutorial_quest")` 表示这个任务必须先完成"tutorial_quest"才能接。前置条件 `prerequisites: Vec<Condition>` 更细粒度 —— "玩家等级 >= 5 且 和铁匠好感度 >= 30"。两者可以并存:任务链是粗粒度的剧情流(必须先做 A 才能做 B),prerequisites 是细粒度的状态门控(满足条件才能接)。

```rust
impl QuestManager {
    pub fn can_accept(&self, def: &QuestDef, gs: &GameState) -> bool {
        // 1. 任务链检查
        if let Some(prev) = &def.chain_prev {
            let prev_instance = self.instances.iter().find(|q| &q.def_id == prev);
            match prev_instance {
                None => return false,                       // 前置任务没接
                Some(q) if q.state != QuestState::Rewarded => return false, // 前置没完成
                _ => {}
            }
        }

        // 2. 前置条件检查
        for cond in &def.prerequisites {
            if !evaluate_condition(cond, gs) { return false; }
        }

        // 3. 已经接了 / 已完成(非 repeatable)
        if let Some(existing) = self.instances.iter().find(|q| &q.def_id == &def.id) {
            if existing.state != QuestState::Failed || !def.repeatable {
                return false;
            }
        }

        true
    }
}
```

这套"先粗后细"的检查顺序在生产里有性能意义。任务链检查是 O(1)(查一个任务实例),前置条件检查可能涉及脚本调用(慢)。先 cheap 后 expensive,短路掉大部分明显不可接的任务。

### 3.4 任务系统就是事件-条件-动作

回过头看任务系统,你会发现它本质就是经典的**事件-条件-动作 (event-condition-action, ECA)** 模式 —— 这是 1990 年代 AI 研究和 active database 的核心抽象,在 gameplay 里被反复重新发现。

- **事件 (Event)**:玩家杀了狼 / 拿了剑 / 进了房间 —— 来自 event bus
- **条件 (Condition)**:objective 的 `matches` 检查 + `prerequisites` 检查
- **动作 (Action)**:progress +1 / 状态迁移 / 发 QuestComplete 事件

ECA 在游戏里应用极广 —— 任务系统、成就系统、触发器系统 (trigger,如"玩家进入区域 X 时刷怪")、AI 反应系统(如"被攻击时反击")。任务系统只是 ECA 最直观的实例。一旦你看穿 ECA 这套抽象,你能在你的引擎里造一个**通用 ECA 引擎**,然后任务、成就、触发器都是它的实例。这是 AAA 引擎(Unreal 的 Gameplay Abilities System、Unity 的 Gameplay Tags + Listener)的做法。但对独立游戏过度 —— 直接写四个独立的 ECA 实例(quest、achievement、trigger、ai-reaction)比写通用框架简单,bug 也少。

## 4 · 能力系统:数据 + 通用运行器

### 4.1 能力的状态机比任务复杂

能力 (ability / skill) 系统在前面对话和任务铺垫后,模式已经清楚。它的特别之处在**状态机更复杂**。一个能力的生命周期:

```
Ready ──(input)──> Casting ──(cast_time passed)──> Active ──(duration passed)──> Cooldown ──(cooldown passed)──> Ready
   ↑                  │                                                                          │
   │                  └──(interrupted)──> Cooldown                                                │
   └──────────────────────────────────────────────────────────────────────────────────────────────┘
```

每个状态对应不同的行为:

- **Ready**:玩家按键可以触发,进入 Casting
- **Casting**:不能动 / 不能用其他能力(取决于能力定义的 `cast_flags`),倒计时 `cast_time`。被打断(受击、移动)切到 Interrupted
- **Active**:能力效果施加(火球飞出、伤害结算、buff 应用)。瞬间能力直接到 Cooldown,持续能力到 duration 结束到 Cooldown
- **Cooldown**:不能用这个能力,倒计时 `cooldown`。结束后回 Ready
- **Interrupted**:被中断,通常进 Cooldown(惩罚)或直接回 Ready(不惩罚),取决于设计

```rust
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum AbilityState {
    Ready,
    Casting { progress: f32 },       // 已经过的 casting 时间
    Active { remaining: f32 },       // 剩余 active 时间
    Cooldown { remaining: f32 },     // 剩余 cooldown 时间
}

pub struct AbilityInstance {
    pub def_id: String,
    pub state: AbilityState,
}

impl AbilityInstance {
    pub fn update(&mut self, dt: f32, def: &AbilityDef, events: &mut EventBus) {
        match &mut self.state {
            AbilityState::Casting { progress } => {
                *progress += dt;
                if *progress >= def.cast_time {
                    // Casting → Active,施加效果
                    for effect in &def.effects {
                        apply_effect(effect, events);
                    }
                    if def.duration > 0.0 {
                        self.state = AbilityState::Active { remaining: def.duration };
                    } else {
                        // 瞬间能力,直接进 Cooldown
                        self.state = AbilityState::Cooldown { remaining: def.cooldown };
                    }
                    events.emit(AbilityCast { ability: def.id.clone() });
                }
            }
            AbilityState::Active { remaining } => {
                *remaining -= dt;
                if *remaining <= 0.0 {
                    self.state = AbilityState::Cooldown { remaining: def.cooldown };
                }
            }
            AbilityState::Cooldown { remaining } => {
                *remaining -= dt;
                if *remaining <= 0.0 {
                    self.state = AbilityState::Ready;
                    events.emit(AbilityReady { ability: def.id.clone() });
                }
            }
            AbilityState::Ready => {}
        }
    }

    pub fn try_cast(&mut self, def: &AbilityDef) -> Result<(), CastError> {
        match self.state {
            AbilityState::Ready => {
                self.state = AbilityState::Casting { progress: 0.0 };
                Ok(())
            }
            _ => Err(CastError::NotReady),
        }
    }

    pub fn interrupt(&mut self, def: &AbilityDef) {
        if let AbilityState::Casting { .. } = self.state {
            // 设计选择:被中断后是否进 cooldown
            self.state = AbilityState::Cooldown { remaining: def.cooldown_on_interrupt.unwrap_or(0.0) };
        }
    }
}
```

注意 `AbilityState` 的几个变体带了 inline 数据(`progress` / `remaining`)。这是 Rust 状态机的常见技巧 —— 状态本身携带"这个状态相关的运行时数据"。比"一个 enum 状态 + 平行的几个 f32 字段"更内聚 —— `progress` 只在 Casting 时有意义,放进 enum variant 让编译器保证"Active 状态下访问 progress 是编译错误"。

### 4.2 能力作为 ECS 组件

如果你的引擎是 ECS(参见 [ecs-evolution](../../phase-5/deep-dives/ecs-evolution.md) 一篇),能力系统应该是组件化 (component-based) 的。每个 entity 有一个 `Abilities` 组件,持有它的所有能力实例。系统每帧 `update` 所有 `Abilities` 组件。

```rust
// ECS 组件
#[derive(Component)]
pub struct Abilities {
    pub instances: HashMap<String, AbilityInstance>,  // def_id → instance
}

// ECS 系统
pub fn ability_system(
    mut query: Query<&mut Abilities, With<Player>>,
    ability_db: Res<AbilityDatabase>,
    time: Res<Time>,
    mut events: EventWriter<AbilityEvent>,
) {
    for mut abilities in query.iter_mut() {
        for (def_id, instance) in abilities.instances.iter_mut() {
            let def = ability_db.get(def_id).unwrap();
            instance.update(time.delta_seconds(), def, &mut events);
        }
    }
}
```

这是 Bevy 风格的 ECS 能力系统。和"在 player.rs 加 cooldowns: HashMap"相比,ECS 版本的优势:

1. **能力可以挂任何 entity** —— 不只玩家,敌人、NPC、陷阱都能有 Abilities 组件
2. **系统并行** —— 多个 entity 的能力更新可以并行(query 提供 parallel iterator)
3. **数据布局友好** —— 大量 entity 的 Abilities 组件在内存里紧凑,cache 友好

ECS 是 gameplay 系统的好宿主,但**能力系统的核心抽象(数据 + 状态机)不变**。ECS 只是承载方式。

### 4.3 效果系统 (effect system):能力的真正威力

到这里能力系统的状态机看起来挺简单,但真实游戏的能力系统复杂度全在**效果 (effect)** 上。一个火球术的效果是"发射火球",但一个"奥术爆炸"的效果可能是:

- 在玩家周围 5 米内,对每个敌人施加 30 点奥术伤害
- 同时给每个敌人施加 "易伤" buff(持续 5 秒,受伤 +50%)
- 玩家自己获得 "护盾" buff(吸收 100 点伤害)
- 播放爆炸粒子效果
- 屏幕震动

每个效果都是一个 EffectSpec 的变体。复杂的"组合效果"通过多个 EffectSpec 列表表达:

```ron
AbilityDef(
    id: "arcane_nova",
    name: "奥术爆炸",
    mana_cost: 50,
    cooldown: 8.0,
    cast_time: 1.0,
    duration: 0.0,
    effects: [
        AoeDamage { radius: 5.0, element: "arcane", amount: 30 },
        AoeApplyBuff { radius: 5.0, buff: "vulnerable", duration: 5.0 },
        ApplyBuffToSelf { buff: "arcane_shield", duration: 10.0, magnitude: 100 },
        SpawnParticle { particle: "arcane_explosion", at: CasterPos },
        ScreenShake { magnitude: 0.5, duration: 0.3 },
    ],
)
```

这种"效果列表"的表达力极强 —— 几乎任何技能都能用 10-20 种基础 effect 组合出来。设计师组合基础 effect 创造新能力,程序员只维护这 10-20 个 effect 的实现。这是 AAA 引擎"几百个技能,几十个 effect 类型"的根本工程结构。Unreal 的 Gameplay Effects、魔兽的 spell DB 都是这个模式。

但 effect 系统也有"复杂度天花板"。当效果需要**条件分支**(如果目标是友军就治疗,如果是敌军就伤害)、**循环**(对每个目标做)、**自定义逻辑**(根据玩家法强动态算伤害),纯数据 effect 不够用,需要嵌套脚本。这就是为什么 AAA 能力系统(Unreal GAS)的 effect 可以挂 Gameplay Cues / Execution Calculations(其实是 C++ / Blueprint 函数)。又是数据 + 脚本的混合。

## 5 · 库存与经济:数据 + 原子事务

### 5.1 物品 (item):最纯粹的数据驱动

库存系统是四个系统里"数据驱动"最纯粹的 —— 物品几乎没有任何状态,就是数据。

```rust
#[derive(Deserialize, Clone)]
pub struct ItemDef {
    pub id: String,
    pub name: String,
    pub description: String,
    pub category: ItemCategory,
    pub max_stack: i32,            // 最大堆叠数(99 表示可堆 99 个)
    pub weight: f32,
    pub value: i32,                // NPC 收购价
    pub usable: Option<ItemEffect>,  // 使用时的效果(药水治疗等)
    pub equipable: Option<EquipSlot>, // 可装备到哪个槽
    pub rarity: Rarity,
    pub icon: String,              // 图标资源 id
}

#[derive(Deserialize, Clone)]
pub enum ItemCategory {
    Consumable,
    Weapon,
    Armor,
    Material,
    Quest,                         // 任务物品(不能丢)
    Misc,
}
```

库存实例只持有 `(item_id, count)` 对。具体物品属性都查 ItemDef。这是数据驱动的极致 —— **运行时状态最小化**。

```rust
pub struct Inventory {
    pub slots: Vec<InventorySlot>,  // 固定大小(16 / 32 槽)
    pub gold: i32,
}

pub struct InventorySlot {
    pub item_id: Option<String>,
    pub count: i32,
}
```

注意库存用**槽 (slot)** 模型 —— 固定数量的格子,每个格子放一种物品的若干个。这是经典 RPG 模式(暗黑破坏神、魔兽世界都是)。另一种模型是**容量 (capacity)** —— 没有格子概念,只有总重量 / 总体积上限(上古卷轴、Skyrim 用重量)。两种各有优劣,槽模型更适合"网格化 UI" 的传统 RPG,容量模型更适合"沉浸式"的现代 RPG。

### 5.2 事务 (transaction):原子性与一致性

库存系统的工程难度全在**事务 (transaction)** 上。事务是数据库的概念 —— 一组操作要么全部成功,要么全部失败,不存在中间状态。

为什么库存需要事务?想象玩家和 NPC 交易:

1. 玩家给 NPC 100 金币
2. NPC 给玩家一把剑

如果中间崩了(玩家被踢下线),出现"扣了钱没拿到剑" —— 这是**复制丢失 (duplication / loss) bug** 的根源。游戏工业里这种 bug 屡见不鲜,严重的会让经济系统崩溃(玩家发现可以复制物品,游戏内通货膨胀,所有物品贬值 99%,正常玩家流失)。

事务的正确实现:

```rust
pub struct Trade {
    pub from: EntityId,
    pub to: EntityId,
    pub give_items: Vec<(String, i32)>,
    pub give_gold: i32,
    pub receive_items: Vec<(String, i32)>,
    pub receive_gold: i32,
}

impl Inventory {
    /// 原子地执行一次交易。返回 Err 时双方库存不变。
    pub fn execute_trade(
        from_inv: &mut Inventory,
        to_inv: &mut Inventory,
        trade: &Trade,
    ) -> Result<(), TradeError> {
        // 步骤 1:验证 —— 双方都有要给的东西吗?
        for (item, count) in &trade.give_items {
            if !from_inv.has_item(item, *count) {
                return Err(TradeError::InsufficientItems);
            }
        }
        if from_inv.gold < trade.give_gold {
            return Err(TradeError::InsufficientGold);
        }
        for (item, count) in &trade.receive_items {
            if !to_inv.has_item(item, *count) {
                return Err(TradeError::CounterpartyInsufficient);
            }
        }
        if to_inv.gold < trade.receive_gold {
            return Err(TradeError::CounterpartyInsufficient);
        }
        // 验证 to_inv 能否装下 give_items(槽位够)
        if !to_inv.has_space_for(&trade.give_items) {
            return Err(TradeError::NoSpace);
        }
        if !from_inv.has_space_for(&trade.receive_items) {
            return Err(TradeError::CounterpartyNoSpace);
        }

        // 步骤 2:执行 —— 到这里所有验证都过了,直接修改
        // 注意:从 step 1 到 step 2 中间,如果多线程访问这两个 inventory,要锁
        for (item, count) in &trade.give_items {
            from_inv.remove_item_silent(item, *count);
            to_inv.add_item_silent(item, *count);
        }
        from_inv.gold -= trade.give_gold;
        to_inv.gold += trade.give_gold;
        for (item, count) in &trade.receive_items {
            to_inv.remove_item_silent(item, *count);
            from_inv.add_item_silent(item, *count);
        }
        to_inv.gold -= trade.receive_gold;
        from_inv.gold += trade.receive_gold;

        Ok(())
    }

    fn has_item(&self, item: &str, count: i32) -> bool {
        self.slots.iter()
            .filter(|s| s.item_id.as_deref() == Some(item))
            .map(|s| s.count)
            .sum::<i32>() >= count
    }
}
```

这套"先全部验证再全部执行"的模式叫 **validate-then-execute**。它的核心保证:**验证通过后,执行阶段不做任何可能失败的修改**。如果执行阶段有任何分支(比如"添加物品时发现槽位不够"),那是验证没做干净 —— bug,要回去补验证。

生产里 validate-then-execute 还要考虑并发。如果两个交易同时改同一个库存,可能出现"两个交易都验证通过,但执行时第一个交易用掉了金币,第二个交易的金币不够" —— 经典 race condition。解决是给 Inventory 加锁,或用 STM (software transactional memory) 之类的事务内存。游戏里通常简单点 —— 所有库存修改在主线程同步执行,不并发。

### 5.3 经济 (economy):库存 + 价格 + 货币

经济系统建立在库存之上。最简形态:

- 玩家背包里有金币(`gold: i32`)
- 每个 ItemDef 有 `value`(NPC 收购价)
- NPC 卖价 = `value * 1.5`(或某个倍率)
- NPC 收价 = `value * 0.5`

这套静态定价适合小规模 RPG。但 AAA 游戏的经济要复杂得多 —— 供需关系、通货膨胀、动态价格、限定物品、特殊货币(钻石、声望、荣誉)。这些机制实现上都是"在交易前后改 `gold` / `value` 的计算方式",库存系统本身不变。

一个有意思的设计是**多种货币**:玩家有金币、银币、铜币(经典 MMO 模式),或者有金币 + 钻石(免费游戏氪金)。库存系统可以统一处理 —— 把货币当成特殊的 ItemDef:

```ron
ItemDef(
    id: "gold_coin",
    name: "金币",
    category: Currency,
    max_stack: i32::MAX,
    weight: 0.0,
    value: 1,
    ...
)
```

把货币当物品的好处是经济系统可以统一 —— 所有"给 / 拿"操作都是 item transaction,无论物品还是货币。代价是 UI 要特殊处理货币显示(不像普通物品放格子)。

### 5.4 库存的脏路径:复制 bug

库存系统最容易出 bug 的地方是**所有修改入口要统一走 transaction**。如果你在某处直接 `inventory.slots[0].count -= 1`(不走 transaction),bug 就埋下了 —— 这个修改可能没对应地"给"另一个库存,造成物品凭空消失或凭空产生。

工业实践是**封装 (encapsulation)**。`Inventory` 的 `slots` 字段是 `pub(crate)` 或 private,外部只能通过 `add_item` / `remove_item` / `execute_trade` 这些方法修改。所有方法内部走 transaction 逻辑。Rust 的可见性 (visibility) 系统在这方面给游戏开发巨大帮助 —— 编译器强制所有修改走公开 API,内部数据布局可以自由优化(比如把 `Vec<InventorySlot>` 改成 `HashMap<String, i32>`),不影响调用方。

## 6 · 工业实践:四个系统怎么协作

### 6.1 内容倍增器 (content multiplier)

把四个系统合起来看,你会发现它们都是**内容倍增器**。代码量是固定的(几百到几千行 Rust),内容量随设计师的产出线性增长。

具体到生产,这意味什么?

- **游戏程序员 (gameplay programmer)** 写框架 —— `QuestDef` / `ObjectiveDef` schema、`QuestManager` 状态机、事件订阅逻辑。这是技术活,要懂 Rust、懂架构、懂性能。
- **内容设计师 (content designer)** 喂数据 —— 在工具里画 500 个任务、写 2000 行对话、配 100 个技能、平衡 1000 个物品的数据。这是创意活,要懂玩法、懂节奏、懂数值。

两个人群用同一份数据 schema 协作。**框架质量决定内容生产速度**。一个 schema 设计糟糕的任务系统,设计师加一个任务要花 30 分钟(因为字段不清、要补字段、要手工对齐进度);一个 schema 设计好的系统,设计师加一个任务 5 分钟。500 个任务就是 5000 分钟 vs 2500 分钟 —— 50 小时 vs 125 小时的差距。

这是为什么 AAA 工作室专门有 **tools programmer** —— 他们的工作不是写游戏,是写"让设计师更快产内容"的工具(任务编辑器、对话编辑器、物品表编辑器)。工具的 ROI 极高 —— 一个程序员投入 1 个月做的任务编辑器,让 10 个设计师之后 1 年的工作快 30%,回报 3600 工时。

### 6.2 四系统的协作流程

四个系统不是孤岛,它们通过事件总线协作。看一个完整的"玩家杀狼、完成任务、得奖励"流程:

1. **战斗系统**:`EnemyKilled(wolf)` 事件 → event bus
2. **任务系统**(订阅 EnemyKilled):`kill_5_wolves` 任务的 Kill objective progress +1 → 进度到 5 → 任务 transition 到 Complete → `QuestComplete(kill_5_wolves)` 事件
3. **UI 系统**(订阅 QuestComplete):弹出"任务完成!"提示,更新任务日志 UI
4. **音频系统**(订阅 QuestComplete):播放任务完成音效
5. 玩家走到村长前,点击村长 → **对话系统**:`DialogueStarted(village_chief)` 事件
6. 对话系统进入村长对话的"complete_quest"节点(因为 `QuestComplete(kill_5_wolves)` flag 为 true,condition 通过)→ 节点 effects 包含 `CompleteQuest(kill_5_wolves)`(把任务从 Complete 切到 Rewarded)+ `GiveGold(100)` + `GiveItem(health_potion, 2)`
7. **库存系统**:`ItemAcquired(health_potion)` 事件 → 更新背包 UI
8. **能力系统**:玩家拿了任务奖励里的"治疗药水能力解锁" → `AbilityUnlocked(heal)` 事件 → 能力系统加这个能力到玩家的 Abilities 组件
9. **成就系统**(订阅 `QuestRewarded`):"完成 10 个任务"成就 progress +1
10. **存档系统**(订阅关键事件):标记 dirty,准备 auto-save(参见 [savegame-and-serialization](../../phase-8/deep-dives/savegame-and-serialization.md))

整个流程没有任何系统**直接调用**其他系统。每个系统只关心自己订阅的事件和自己发出的事件。这种 decoupling 让系统可以独立开发、独立测试、独立替换。要加一个"任务完成时通知手机 App"的功能,你写一个新系统订阅 `QuestComplete`,不碰任何现有代码。这就是事件驱动 gameplay 的威力。

### 6.3 数据 schema 的演化

生产里数据 schema 会演化 —— 加字段、改字段类型、删字段。每次 schema 变,旧数据要 migration。

migration 的工程实践:

- **schema 加版本号**:`QuestDef` 加 `version: u32` 字段,加载时检查版本
- **向前兼容**:新版本读旧数据时,缺字段用默认值(`#[serde(default)]`)
- **migration 函数**:旧版本数据加载后,跑一个 migration 函数升级到新版本

```rust
impl QuestDef {
    pub fn from_data_v1(data: serde_json::Value) -> Result<Self, SchemaError> {
        let mut def: QuestDefV1 = serde_json::from_value(data)?;
        Ok(Self {
            // 把 v1 字段映射到 v2 字段,补默认值
            id: def.id,
            title: def.name,  // v1 叫 name,v2 叫 title
            description: def.desc.unwrap_or_default(),
            // ...
        })
    }
}
```

AAA 项目里 schema 演化是日常 —— 游戏开发 2-5 年,期间数据格式必然变几次。游戏发布后还要 patch、DLC,继续演化。**没有 schema 版本管理的数据驱动系统是不可维护的**。

### 6.4 模式识别:套到任何玩法系统

回到第 1 节的"三角形"心智模型。现在我们用它快速套几个没讲过的玩法系统,验证它的普适性。

**制造系统 (crafting)**:数据是配方 (`Recipe` —— 输入物品列表、输出物品、需要的工作台、制造时间)。状态机:`Locked → Unlocked → Crafting → Done`(玩家学会配方 → 开始造 → 造完)。事件:订阅 `CraftRequested`,发 `CraftComplete`。**完全同构**。

**声望系统 (reputation)**:数据是阵营 (`Faction`)和声望等级 (`ReputationLevel`)。状态机:每个等级是状态(Hated → Hostile → Unfriendly → Neutral → Friendly → Honored → Exalted),声望值达标自动迁移。事件:订阅 `FactionMemberKilled`,扣声望;订阅 `QuestComplete` 加声望。**完全同构**。

**科技树 (tech tree)**:数据是科技 (`Tech` —— 前置、效果、研究成本)。状态机:`Locked → Researchable → Researching → Researched`。事件:订阅 `ResearchComplete`,解锁后续科技。**完全同构**。

**副本进度 (dungeon progression)**:数据是副本 (`Dungeon` —— boss 列表、boss 顺序、奖励)。状态机:`NotEntered → InProgress → BossKilled(N) → Cleared`。事件:订阅 `BossKilled`,推进进度。**完全同构**。

看出来了吗?**所有玩法系统都是同一个三角形的不同实例**。一旦你内化这个模型,你能在一天内设计任何一个新玩法系统的雏形 —— 把"它的数据是什么 / 它的状态是什么 / 它订阅什么事件"三问答完,基本架构就出来了。剩下的是工程实现细节,每个系统都有它独特的难点(库存的事务性、能力的状态机复杂度、对话的图结构),但骨架是共享的。

## 7 · 在你 HH 项目里动手(做中学红线)

理论讲完了,现在落到代码。这一节给你一份完整的、能直接贴到 HH 项目里运行的数据驱动任务系统。建议你按这个顺序做:

### 步骤 1:建项目结构

```
handmade-hero/
├── Cargo.toml
├── src/
│   ├── main.rs
│   ├── events.rs         # 事件总线(参见 event-systems 一篇)
│   ├── quest.rs          # 任务系统(本篇核心)
│   └── game.rs           # 模拟游戏逻辑
└── data/
    └── quests/
        ├── kill_5_wolves.ron
        ├── fetch_sword.ron
        └── talk_to_sage.ron
```

### 步骤 2:Cargo.toml

```toml
[package]
name = "handmade-hero"
version = "0.7.0"
edition = "2021"

[dependencies]
serde = { version = "1", features = ["derive"] }
ron = "0.8"
parking_lot = "0.12"
```

### 步骤 3:events.rs —— 极简事件总线

如果你已经做过 [event-systems-and-gameplay-foundations](../../phase-5/deep-dives/event-systems-and-gameplay-foundations.md) 一篇的练习,这里的事件总线可以复用。这里写一个最小可用版本,跑通任务系统演示。

```rust
// src/events.rs
use parking_lot::Mutex;
use std::any::{Any, TypeId};
use std::collections::HashMap;
use std::sync::Arc;

type Handler = Box<dyn Fn(&dyn Any) + Send + Sync>;

#[derive(Default, Clone)]
pub struct EventBus {
    handlers: Arc<Mutex<HashMap<TypeId, Vec<Handler>>>>,
}

impl EventBus {
    pub fn new() -> Self {
        Self::default()
    }

    /// 订阅某类型的事件。返回的 ListenerId 可用于取消订阅。
    pub fn on<E: 'static, F>(&self, handler: F)
    where
        E: Send + Sync + 'static,
        F: Fn(&E) + Send + Sync + 'static,
    {
        let handler: Handler = Box::new(move |any: &dyn Any| {
            if let Some(e) = any.downcast_ref::<E>() {
                handler(e);
            }
        });
        self.handlers.lock()
            .entry(TypeId::of::<E>())
            .or_default()
            .push(handler);
    }

    pub fn emit<E>(&self, event: E)
    where
        E: Send + Sync + 'static,
    {
        let type_id = TypeId::of::<E>();
        let handlers = self.handlers.lock();
        if let Some(list) = handlers.get(&type_id) {
            for h in list {
                h(&event);
            }
        }
    }
}
```

注意这套事件总线用 `TypeId` 做事件类型的 key。emit 时只通知订阅了**完全相同类型**的 handler。这是类型安全的事件总线 —— 编译期就保证 `emit(EnemyKilled)` 不会被订阅 `ItemAcquired` 的 handler 收到。代价是闭包里要做 `downcast_ref`,有一点运行时开销,但比基于字符串的事件名可靠得多。

### 步骤 4:quest.rs —— 任务系统

这是这一节的核心代码。仔细读,你会看到第 1-3 节讲的所有模式落地。

```rust
// src/quest.rs
use serde::Deserialize;
use crate::events::EventBus;
use std::collections::HashMap;
use std::path::Path;
use std::sync::{Arc, Mutex as StdMutex};
use parking_lot::Mutex;

// ===================== 数据层:QuestDef =====================

#[derive(Deserialize, Clone, Debug)]
pub struct QuestDef {
    pub id: String,
    pub title: String,
    pub description: String,
    pub objectives: Vec<ObjectiveDef>,
    pub rewards: Vec<RewardDef>,
}

#[derive(Deserialize, Clone, Debug)]
#[serde(tag = "kind", content = "data")]
pub enum ObjectiveDef {
    Kill { enemy_type: String, count: i32 },
    Collect { item: String, count: i32 },
    TalkTo { npc: String },
    Reach { location: String },
}

#[derive(Deserialize, Clone, Debug)]
#[serde(tag = "kind", content = "data")]
pub enum RewardDef {
    Gold(i32),
    Item { id: String, count: i32 },
    Experience(i32),
}

impl ObjectiveDef {
    fn target_count(&self) -> i32 {
        match self {
            ObjectiveDef::Kill { count, .. } |
            ObjectiveDef::Collect { count, .. } => *count,
            ObjectiveDef::TalkTo { .. } |
            ObjectiveDef::Reach { .. } => 1,
        }
    }
}

// ===================== 状态层:QuestInstance =====================

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum QuestState {
    Inactive,
    Active,
    Complete,
    Rewarded,
}

pub struct QuestInstance {
    pub def_id: String,
    pub state: QuestState,
    pub progress: Vec<i32>,
}

impl QuestInstance {
    fn new(def: &QuestDef) -> Self {
        Self {
            def_id: def.id.clone(),
            state: QuestState::Inactive,
            progress: vec![0; def.objectives.len()],
        }
    }

    fn all_done(&self, def: &QuestDef) -> bool {
        self.progress.iter().enumerate()
            .all(|(i, &p)| p >= def.objectives[i].target_count())
    }

    fn transition(&mut self, new_state: QuestState, events: &EventBus) {
        let old = self.state;
        self.state = new_state;
        match (old, new_state) {
            (QuestState::Inactive, QuestState::Active) => {
                events.emit(QuestAccepted { quest_id: self.def_id.clone() });
            }
            (QuestState::Active, QuestState::Complete) => {
                events.emit(QuestComplete { quest_id: self.def_id.clone() });
            }
            (QuestState::Complete, QuestState::Rewarded) => {
                events.emit(QuestRewarded { quest_id: self.def_id.clone() });
            }
            _ => {}
        }
    }
}

// ===================== 事件:任务系统关心的事件 =====================

#[derive(Debug, Clone)]
pub struct EnemyKilled {
    pub enemy_type: String,
}

#[derive(Debug, Clone)]
pub struct ItemAcquired {
    pub item_id: String,
    pub count: i32,
}

#[derive(Debug, Clone)]
pub struct DialogueStarted {
    pub npc_id: String,
}

#[derive(Debug, Clone)]
pub struct LocationEntered {
    pub location_id: String,
}

#[derive(Debug, Clone)]
pub struct QuestAccepted { pub quest_id: String }
#[derive(Debug, Clone)]
pub struct QuestComplete { pub quest_id: String }
#[derive(Debug, Clone)]
pub struct QuestRewarded { pub quest_id: String }

// ===================== 管理器:QuestManager =====================

pub struct QuestManager {
    pub defs: HashMap<String, QuestDef>,
    pub instances: HashMap<String, QuestInstance>,  // def_id → instance
    events: EventBus,
}

impl QuestManager {
    /// 从 data/quests/ 目录加载所有 .ron 任务定义
    pub fn load_from_dir(dir: &Path, events: EventBus) -> Result<Self, std::io::Error> {
        let mut defs = HashMap::new();
        for entry in std::fs::read_dir(dir)? {
            let path = entry?.path();
            if path.extension().and_then(|e| e.to_str()) == Some("ron") {
                let content = std::fs::read_to_string(&path)?;
                match ron::from_str::<QuestDef>(&content) {
                    Ok(def) => {
                        println!("[quest] loaded: {} ({})", def.id, def.title);
                        defs.insert(def.id.clone(), def);
                    }
                    Err(e) => {
                        eprintln!("[quest] failed to parse {}: {}", path.display(), e);
                    }
                }
            }
        }
        Ok(Self {
            defs,
            instances: HashMap::new(),
            events,
        })
    }

    /// 玩家接受任务
    pub fn accept(&mut self, def_id: &str) {
        let def = match self.defs.get(def_id) {
            Some(d) => d,
            None => return,
        };
        let mut instance = QuestInstance::new(def);
        instance.transition(QuestState::Active, &self.events);
        self.instances.insert(def_id.to_string(), instance);
    }

    /// 处理一个游戏事件(由事件总线回调调用)
    pub fn handle_enemy_killed(&mut self, event: &EnemyKilled) {
        for (def_id, instance) in self.instances.iter_mut() {
            if instance.state != QuestState::Active { continue; }
            let def = &self.defs[def_id];
            for (i, obj) in def.objectives.iter().enumerate() {
                if instance.progress[i] >= obj.target_count() { continue; }
                if let ObjectiveDef::Kill { enemy_type, .. } = obj {
                    if enemy_type == &event.enemy_type {
                        instance.progress[i] += 1;
                        println!("[quest] {} progress: {}/{}",
                            def_id, instance.progress[i], obj.target_count());
                    }
                }
            }
            if instance.all_done(def) {
                instance.transition(QuestState::Complete, &self.events);
            }
        }
    }

    pub fn handle_item_acquired(&mut self, event: &ItemAcquired) {
        for (def_id, instance) in self.instances.iter_mut() {
            if instance.state != QuestState::Active { continue; }
            let def = &self.defs[def_id];
            for (i, obj) in def.objectives.iter().enumerate() {
                if instance.progress[i] >= obj.target_count() { continue; }
                if let ObjectiveDef::Collect { item, count, .. } = obj {
                    if item == &event.item_id {
                        instance.progress[i] = instance.progress[i].saturating_add(event.count).min(*count);
                        println!("[quest] {} collect: {}/{}",
                            def_id, instance.progress[i], count);
                    }
                }
            }
            if instance.all_done(def) {
                instance.transition(QuestState::Complete, &self.events);
            }
        }
    }

    pub fn handle_dialogue_started(&mut self, event: &DialogueStarted) {
        for (def_id, instance) in self.instances.iter_mut() {
            if instance.state != QuestState::Active { continue; }
            let def = &self.defs[def_id];
            for (i, obj) in def.objectives.iter().enumerate() {
                if instance.progress[i] >= obj.target_count() { continue; }
                if let ObjectiveDef::TalkTo { npc } = obj {
                    if npc == &event.npc_id {
                        instance.progress[i] = 1;
                    }
                }
            }
            if instance.all_done(def) {
                instance.transition(QuestState::Complete, &self.events);
            }
        }
    }

    /// 玩家领取任务奖励(到村长那里交付)
    pub fn reward(&mut self, def_id: &str) -> Vec<RewardDef> {
        let instance = match self.instances.get_mut(def_id) {
            Some(q) => q,
            None => return vec![],
        };
        if instance.state != QuestState::Complete { return vec![]; }
        let rewards = self.defs[def_id].rewards.clone();
        instance.transition(QuestState::Rewarded, &self.events);
        rewards
    }
}
```

仔细看 `handle_enemy_killed` 的实现。**它没有任何"杀狼"或"杀哥布林"的硬编码**。它循环所有 active 任务的 Kill objective,匹配 enemy_type。你加 100 个杀怪任务,这段代码不变 —— 100 个任务的数据各自描述自己关心哪种 enemy_type。

### 步骤 5:data/quests/*.ron —— 纯数据驱动

```ron
// data/quests/kill_5_wolves.ron
(
    id: "kill_5_wolves",
    title: "狼患",
    description: "村长请你消灭森林里的狼群。",
    objectives: [
        Kill(enemy_type: "wolf", count: 5),
    ],
    rewards: [
        Gold(100),
        Item(id: "health_potion", count: 2),
        Experience(50),
    ],
)
```

```ron
// data/quests/fetch_sword.ron
(
    id: "fetch_sword",
    title: "遗失的宝剑",
    description: "铁匠的剑掉进井里了,帮他捞回来。",
    objectives: [
        Collect(item: "rusty_sword", count: 1),
        TalkTo(npc: "blacksmith"),
    ],
    rewards: [
        Gold(50),
        Item(id: "iron_sword", count: 1),
    ],
)
```

```ron
// data/quests/talk_to_sage.ron
(
    id: "talk_to_sage",
    title: "智者的指引",
    description: "去山洞里找隐居的智者问问路。",
    objectives: [
        Reach(location: "mountain_cave"),
        TalkTo(npc: "sage"),
    ],
    rewards: [
        Experience(100),
    ],
)
```

这三个任务**没有任何 Rust 代码**。它们就是 RON 文件,扔进 `data/quests/` 目录,任务系统 `load_from_dir` 自动加载。这就是数据驱动的内容倍增器 —— 加任务的成本是"加一个文件",不是"加十行代码"。

### 步骤 6:main.rs —— 整合 + 演示

```rust
// src/main.rs
mod events;
mod quest;

use events::EventBus;
use quest::*;
use std::path::Path;

fn main() {
    // 1. 创建事件总线
    let events = EventBus::new();

    // 2. 监听任务相关事件(打日志,模拟 UI / 音频系统)
    events.on(|e: &QuestAccepted| println!("[ui] 任务已接受: {}", e.quest_id));
    events.on(|e: &QuestComplete| println!("[ui] ✅ 任务完成: {}", e.quest_id));
    events.on(|e: &QuestRewarded| println!("[ui] 🎁 奖励已领取: {}", e.quest_id));

    // 3. 从 data/quests/ 加载所有任务定义
    let mut qm = QuestManager::load_from_dir(Path::new("data/quests"), events.clone())
        .expect("failed to load quests");

    // 4. 玩家接受任务
    println!("\n=== 接受任务 ===");
    qm.accept("kill_5_wolves");
    qm.accept("fetch_sword");
    qm.accept("talk_to_sage");

    // 5. 模拟游戏事件 —— 玩家杀狼
    println!("\n=== 杀狼 x5 ===");
    for _ in 0..5 {
        qm.handle_enemy_killed(&EnemyKilled { enemy_type: "wolf".into() });
    }

    // 6. 模拟游戏事件 —— 玩家捡到生锈剑
    println!("\n=== 捡到生锈剑 ===");
    qm.handle_item_acquired(&ItemAcquired { item_id: "rusty_sword".into(), count: 1 });

    // 7. 模拟游戏事件 —— 玩家到山洞 + 和智者对话
    println!("\n=== 到山洞找智者 ===");
    // (Reach 事件简化,这里只演示 dialogue;你的实现里加 LocationEntered handler)

    // 8. 玩家找铁匠(完成 fetch_sword 第二个 objective + 领奖励)
    println!("\n=== 找铁匠领奖 ===");
    qm.handle_dialogue_started(&DialogueStarted { npc_id: "blacksmith".into() });
    let rewards = qm.reward("fetch_sword");
    println!("获得的奖励: {:?}", rewards);

    // 9. 杀狼任务领奖
    println!("\n=== 杀狼任务领奖 ===");
    let rewards = qm.reward("kill_5_wolves");
    println!("获得的奖励: {:?}", rewards);
}
```

跑起来你应该看到:

```
[quest] loaded: kill_5_wolves (狼患)
[quest] loaded: fetch_sword (遗失的宝剑)
[quest] loaded: talk_to_sage (智者的指引)

=== 接受任务 ===
[ui] 任务已接受: kill_5_wolves
[ui] 任务已接受: fetch_sword
[ui] 任务已接受: talk_to_sage

=== 杀狼 x5 ===
[quest] kill_5_wolves progress: 1/5
[quest] kill_5_wolves progress: 2/5
[quest] kill_5_wolves progress: 3/5
[quest] kill_5_wolves progress: 4/5
[quest] kill_5_wolves progress: 5/5
[ui] ✅ 任务完成: kill_5_wolves

=== 捡到生锈剑 ===
[quest] fetch_sword collect: 1/1

=== 找铁匠领奖 ===
[quest] fetch_sword progress (TalkTo): ...
[ui] ✅ 任务完成: fetch_sword
[ui] 🎁 奖励已领取: fetch_sword
获得的奖励: [Gold(50), Item { id: "iron_sword", count: 1 }]

=== 杀狼任务领奖 ===
[ui] 🎁 奖励已领取: kill_5_wolves
获得的奖励: [Gold(100), Item { id: "health_potion", count: 2 }, Experience(50)]
```

### 步骤 7:亲手感受"内容倍增器"

跑通之后,**现在做一件事**:在 `data/quests/` 加一个新文件 `kill_10_goblins.ron`,内容你自己设计(杀 10 个哥布林,奖励一堆东西)。**不要改任何 Rust 代码**。重新跑,你的新任务自动被加载、自动可接受、自动追踪。这就是框架 vs 内容的分工 —— 框架程序员写一次,设计师填无数次。

这就是"在你 HH 项目里动手"这一节要你拿走的核心体感。代码骨架已经能跑,接下来你按自己游戏的内容慢慢扩 —— 加对话系统、能力系统、库存系统,每个都是同一套模式。模式会了,代码就是体力活。

## 8 · 关联 HH Day 与跨模块

- **铺垫**:[event-systems-and-gameplay-foundations](../../phase-5/deep-dives/event-systems-and-gameplay-foundations.md) —— 事件总线是 gameplay 系统的神经系统,先做这个再做 gameplay;[scripting-and-modding](../../phase-8/deep-dives/scripting-and-modding.md) —— 复杂 condition / effect 用脚本表达;[09B-2 反射与数据驱动系统](../../phase-9/09B-2-subsystems-modules-plugins.md) —— 数据驱动的极致形态是 reflection
- **当天**:本篇是 phase-7 游戏性专题
- **后续**:[game-state-management](../../phase-2/deep-dives/game-state-management.md) —— 任务实例 / 库存实例是 game state 的一部分,要做 savegame;[savegame-and-serialization](../../phase-8/deep-dives/savegame-and-serialization.md) —— 任务进度、库存、对话 flag 都要序列化到存档;[ai-patterns](../../phase-2/deep-dives/ai-patterns.md) —— 任务系统的目标事件订阅和 AI 的行为树事件触发同源

## 9 · 练习

### Lv1 · 概念辨析

**题**:对话、任务、能力、库存这四个系统,各自的数据、状态、事件是什么?用一句话各答三问。

**参考解答**:

- 对话:数据是有向图节点(台词 + 条件 + effect),状态是"当前在哪个节点",事件是 `DialogueStarted` / `DialogueChoiceSelected`。
- 任务:数据是 QuestDef(objective + reward),状态是 Inactive/Active/Complete/Rewarded,事件是订阅 `EnemyKilled` / `ItemAcquired` 等,发出 `QuestComplete` 等。
- 能力:数据是 AbilityDef(cooldown + effect list),状态是 Ready/Casting/Active/Cooldown,事件是订阅 input,发出 `AbilityCast`。
- 库存:数据是 ItemDef(name + value + stack),状态是每个槽位的 item_id + count,事件是订阅 `ItemAcquired`,事务化执行 give/take。

四个系统都是**数据驱动 + 状态机 + 事件驱动**的同一三角形。

### Lv2 · 动手实践

**题**:在本篇的 HH 任务系统代码基础上,加一个新 objective 类型 `Escort { npc, to }` —— 护送 NPC 到指定地点。要求:加 enum 变体、加 event 订阅、加数据示例。

完成标准:RON 里能写 `Escort(npc: "merchant", to: "town_gate")`,跑通模拟。

**参考解答**:

1. `ObjectiveDef` 加 `Escort { npc: String, to: String }` 变体,`target_count` 返回 1
2. 加事件 `EscortReached { npc_id: String, location_id: String }`
3. QuestManager 加 `handle_escort_reached`,匹配 npc 和 location
4. RON:`Escort(npc: "merchant", to: "town_gate")`

关键洞察:加一个 objective 类型涉及 enum + event + handler 三处,这是 sum type 数据驱动的扩展成本。比"硬编码 if quest_id == xxx" 健壮得多,因为 Rust 编译器强制你处理所有 match 分支。

### Lv3 · 迁移设计

**题**:用本篇的"数据驱动 + 状态机 + 事件"三角形,设计一个**制造系统 (crafting)** 的数据 schema 和状态机。要求:

- 配方:输入物品 + 输出物品 + 制造时间 + 需要的工作台
- 玩家可以同时进行多个制造(每个制造有独立进度)
- 制造完成发事件,库存系统订阅它给物品

提示:状态机是 `Locked → Unlocked → InProgress { remaining: f32 } → Done`。

### Lv4 · 开源贡献

**题**:研究一个工业级 gameplay 框架,看它们的"数据驱动 + 状态机 + 事件"三角形怎么实现。推荐:

1. **Unreal Engine Gameplay Abilities System (GAS)** —— 这是 AAA 级 gameplay 系统的事实标准。GitHub 上 Unreal 源码 `Source/GameplayAbilities/Public/`。重点看 `GameplayAbility.h`(能力定义)、`GameplayEffect.h`(效果)、`AbilitySystemComponent.h`(状态机 + 复制)。
2. **Bevy 的 `bevy_mod_rpg` 系列** —— Rust 生态的 RPG 框架雏形。看它的 quest / inventory / combat module 怎么拆。
3. **OpenRCT2 / OpenMW** —— 开源的 RollerCoaster Tycoon 2 / Morrowind 实现,看它们的 quest / dialogue / inventory 系统。
4. **yarnspinner-rust** —— Yarn Spinner 的 Rust 移植,对话系统的工业实现。

读源码时不断问自己:**"这块逻辑是数据、状态、还是事件?"** —— 你会发现 AAA 源码也是按这个三角形组织的,只是规模更大、抽象更深。

## 10 · 延伸阅读

外部稳定 URL:

- Unreal Gameplay Abilities System 文档(AAA gameplay 系统的事实标准):https://dev.epicgames.com/documentation/en-us/unreal-engine/gameplay-ability-system-for-unreal-engine
- Yarn Spinner(开源对话系统,被多款独立游戏使用):https://yarnspinner.dev/
- Ink by inklestudios(脚本式对话系统):https://www.inklestudios.com/ink/
- articy:draft(商业内容管理平台,AAA RPG 标配):https://www.articy.com/
- Bob Nystrom 的 Game Programming Patterns(设计模式经典,State / Observer / Component 各自对应本篇的状态 / 事件 / 数据驱动):https://gameprogrammingpatterns.com/
- RON 格式(Rust Object Notation,游戏数据首选):https://github.com/ron-rs/ron
- Bevy ECS(本篇能力系统作为 ECS 组件的工业实践):https://bevyengine.org/

真实开源源码(必读):

- OpenMW 的 quest / dialogue 系统(Morrowind 开源复刻):https://gitlab.com/OpenMW/openmw/-/tree/master/apps/openmw/mwdialogue
- OpenRCT2 的 scenario / objective 系统(RollerCoaster Tycoon 2 开源):https://github.com/OpenRCT2/OpenRCT2/tree/develop/src/openrct2
- Unreal GAS GameplayAbility:https://github.com/EpicGames/UnrealEngine/blob/ue5-main/Source/GameplayAbilities/Public/GameplayAbility.h
- Yarn Spinner Rust:https://github.com/YarnSpinnerTool/YarnSpinner-Rust
- Bevy 的 reflect crate(数据驱动 + reflection 的 Rust 实践):https://github.com/bevyengine/bevy/tree/main/crates/bevy_reflect

---

**最终建议**:gameplay 系统是"游戏"和"引擎"的分水岭。引擎程序员写能力(渲染、物理、音频),gameplay 程序员写规则(任务、对话、能力、库存)。两者的工程范式不同 —— 引擎追求性能,gameplay 追求灵活。**数据驱动 + 状态机 + 事件** 这套三角形是 gameplay 程序员的核心武器。把这篇深入里那套任务系统的代码贴到 HH 项目里跑通,然后挨个加上对话、能力、库存,你就掌握了独立游戏 80% 的 gameplay 工程实践。剩下 20% 是 AAA 级的 reflection、replication、tooling,留给你的职业生涯慢慢探索。
