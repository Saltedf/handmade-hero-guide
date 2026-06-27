---
phase: 9
sequence: "9E"
module: 2
title_en: "Authoritative Server & State Sync"
title_zh: "权威服务器与状态同步:为什么永远不能信客户端"
type: deep-dive
difficulty: 4
duration: "3-4 小时"
domains: [game, network, rust, linux, system, concurrency]
prereqs: ["09E-1-reliable-udp-transport"]
calibration: "Gaffer on Games 'Snapshot Interpolation' & 'State Synchronization' + 行业 server-authoritative 实践"
---

# 9E-2 · 权威服务器与状态同步

## 0 · 你让客户端报"我打了 100 血",一小时后游戏变成作弊地狱

你在 HH 上做完 [09E-1](09E-1-reliable-udp-transport.md) 的可靠 UDP 传输,两个客户端能互相收发输入了。你觉得"联机好像也就这样",于是做了一个看起来很自然的决定:让客户端自己计算伤害。客户端 A 的玩家挥剑砍中敌人,客户端 A 算出"造成 100 点伤害",把"我对 enemy_id=42 造成了 100 伤害"这条消息发给客户端 B。B 收到,把 enemy_42 的 hp 减 100。简单、直观、对称——P2P 架构,谁也不服谁。

发布当天晚上,你在日志里看到一个奇怪的模式:同一个 IP,在十分钟内打了 47 次 boss,每次伤害都是 9999。你打开抓包工具,看到那个玩家在 UDP 包里发的是 `DealDamage { target: boss_id, amount: 9999 }`。他甚至没改你的二进制——你的协议本身就是明文,他抓了一下包,看懂了 `DealDamage` 这个 enum 的字节布局,然后用 30 行 Python 写了个发包脚本。你给客户端加了一层"伤害上限 200"的校验——他三分钟后就发现校验在客户端本地,把它 patch 掉了。你把校验挪到对方客户端——他改成同时连两个号,自己跟自己打,两边都报 9999。

第二天你在 Reddit 看到自己的游戏被叫做"那个 9999 外挂游戏"。这就是把权威交给客户端的代价:你把"判定什么是真相"的权力,交给了你完全控制不了的一台机器。任何玩家都能 attach debugger、改内存、注入 DLL、重发任意包。这不是"如果",这是**确定会发生**——只要有足够多的玩家,其中就一定有人会这么做。

这一篇要讲的,是这一类问题的根本解:server-authoritative architecture(服务器权威架构)。**永远不要信客户端**——这不是工程偏好,这是反作弊的第一公理。客户端能做的,只有告诉服务器"我按了什么键";服务器拿到按键,自己跑一遍游戏模拟,自己算出结果,然后把结果广播给所有人。客户端改内存也好、伪造包也好,只能伪造"我按了键"——而服务器拿到按键自己算,你伪造"我按了一次开火键",服务器算出来的结果还是"你射了一发子弹",你伪造不了"这一发子弹打中了 boss"。

这个架构听起来简单,但它逼着你回答几个工程问题:服务器要跑多快(tick rate)?服务器跑出来的状态怎么高效传给客户端(snapshot compression)?客户端只听服务器的会很卡,怎么办(client prediction——这是下一篇 09E-3 的主角)?这一篇把这些一个一个讲透,并把它的客户端对偶篇 [phase-5/network-prediction-and-rollback](../phase-5/deep-dives/network-prediction-and-rollback.md) 的位置摆好——权威服务器和预测客户端是**同一套模型的两个半边**,合起来才是 2026 年所有快节奏联机游戏的工业 standard。

## 1 · 权威模型:服务器跑真实模拟,客户端只发输入

把"权威"这件事讲清楚,得从一种根深蒂固的误解开始。很多人第一次想"联机"的时候,脑子里浮现的画面是"两台机器同步状态"——A 的位置变了,A 告诉 B 新位置;B 的血量变了,B 告诉 A 新血量。这个画面是 P2P state replication,它的问题不是"做不到",而是**没有任何一方有资格说"我说了算"**。A 说"我在 (10, 20)",B 说"你在 (15, 25)",谁对?你没有一个仲裁者,就只能信任对方客户端——而对方客户端恰恰是不可信的。

权威模型反过来:不是双方互相报状态,而是**双方都报输入给一个第三方**(服务器),第三方自己跑模拟,跑出来的状态就是真相,然后告诉双方"真相是这样"。A 想动,A 不告诉 B"我现在在 (10, 20)",A 告诉服务器"我按了 W 键";服务器在自己的模拟里把 A 的角色按 W 推进一帧,得到 A 的新位置,把这个位置同时发给 A 和 B。这样无论 A 怎么撒谎——"我按了 W,而且我应该被传送到 boss 脚下"——服务器只认"我按了 W"这部分,后面的位移是服务器自己算的,A 撒不了谎。

这个架构的关键工程含义是:**服务器上跑的,就是你游戏本体的一个 headless 实例**。它不是"一个专门写的小服务",它就是你的游戏,只是没有渲染、没有窗口、没有手柄输入——把 `step` 函数原封不动搬过来,接上网线。这一点也是为什么 [09B-1](09B-1-game-loop-and-timestep.md) 那一篇的固定步长那么重要:服务器跑的 `step(state, FIXED_DT)` 必须和客户端的 `step` 完全一致(或者客户端干脆不跑 `step`,只跑渲染),否则两边对同一组输入会算出不同结果,玩家看到的画面和服务器认定的"真相"分叉,反作弊就成了笑话。

我们把它写成最朴素的代码骨架,你能看到这个架构有多干净:

```rust
// 服务器:headless 跑 step,只是输入来自网线
impl Server {
    fn tick(&mut self) -> io::Result<()> {
        // 1. 收所有客户端这一 tick 的输入
        let mut inputs: HashMap<ClientId, u16> = HashMap::new();
        while let Some((addr, bytes)) = self.try_recv()? {
            let input: ClientInput = bincode::deserialize(&bytes)?;
            // 只记录"按了什么键",不信客户端报的任何状态字段
            inputs.insert(self.client_id_of(addr), input.buttons);
        }
        // 2. 用 step 推进——和单机版本完全一样的 step!
        step(&mut self.state, FIXED_DT, &inputs);
        // 3. 把 step 之后的状态广播给所有人
        let snapshot = self.snapshot();
        for client in &self.clients {
            self.socket.send_to(&snapshot, client.addr)?;
        }
        Ok(())
    }
}

// 客户端:不跑 step,只发输入 + 渲染收到的状态
impl Client {
    fn frame(&mut self) -> io::Result<()> {
        // 1. 采集本地输入,只发"按了什么"
        let buttons = collect_local_input();
        let bytes = bincode::serialize(&ClientInput { buttons })?;
        self.socket.send_to(&bytes, self.server_addr)?;
        // 2. 收服务器广播的真相,直接拿来渲染
        while let Some((_, bytes)) = self.try_recv()? {
            self.received = bincode::deserialize(&bytes)?;
        }
        render(&self.received);
        Ok(())
    }
}
```

注意这个骨架里**没有任何一处**让客户端报告自己的位置、血量、伤害。客户端能报告的字段只有一个:`buttons`——这一帧按了哪些键。所有"我移动了多远、我打中了谁、我扣了多少血"全部是服务器在自己内存里算的,客户端既不能影响这个计算过程(它只提供输入),也不能篡改这个计算结果(它根本不参与)。**判定什么是真相的权力,完全在一台玩家碰不到的机器上**——这就是权威的本质。

这个架构的代价很现实:服务器要跑完整的游戏模拟,而不是当个转发节点。一个 100 人 session,服务器每帧要 update 100 个玩家的位置、AI、碰撞、伤害——CPU 占用是单机版本的 N 倍。这也是为什么严肃联机游戏都租 dedicated server,而不是用某个玩家的客户端"开 host"——host 模式下,host 这台客户端就是服务器,host 玩家能改自己机器上的模拟,等于又回到了"信任客户端"的老路。dedicated server 的成本是真金白银,但它是公平性的物理保证。

## 2 · Tick rate:服务器为什么必须用固定步长

服务器要跑模拟,就得有个节拍——多少次每秒跑一次 `step`?这个节拍叫 tick rate,它是权威服务器架构里你做的第一个关键工程决策。

最直觉的答案是"越快越好"。但快是有代价的。服务器每 tick 要做三件事:收所有客户端的输入、跑一次 `step`、序列化状态广播。tick 越快,这三件事的总开销线性上升。一个 64 tick(每秒 64 次)的服务器,如果 `step` 单次 2ms,光模拟就要 128ms/s = 12.8% CPU;128 tick 就要 256ms/s = 25.6% CPU。再叠加广播开销(每个 tick 给每个客户端发包),很快单核就吃满。所以 tick rate 不是越高越好,是一个工程权衡。

反过来,tick 太慢也有问题。tick 是服务器响应输入的粒度——你按了 W 键,要等到下一次 tick 才被服务器处理。30 tick 的服务器,你按 W 到服务器开始模拟你前进,平均延迟 1/60 秒(半个 tick 间隔),最坏 1/30 秒。在快节奏游戏里(FPS、格斗),30 tick 的输入粒度会被玩家明显感知为"按键发粘"。CS 系列长期用 64 tick,被职业玩家吐槽不够,CS:GO 后来开了 128 tick 的官方服务器;Valorant 上线直接 128 tick;格斗游戏普遍 60 tick。慢节奏的(MOBA、MMO)30 tick 够了,LoL 就是 30 tick,Fortnite 20 tick。

但 tick rate 还有一个更深层的约束,是这一篇和 [09B-1](09B-1-game-loop-and-timestep.md) 直接挂钩的:**服务器的 tick 必须是固定步长,而且每一步的 dt 必须和客户端模拟用的 dt 完全一致**。这一点听起来是工程细节,但它关系到反作弊的根本可信度。

为什么?想一个具体场景。客户端 A 和服务器都在跑 `step`。客户端的 `step` 用 `FIXED_DT = 1.0/60.0`,服务器的 `step` 用 `FIXED_DT = 1.0/30.0`(因为服务器是 30 tick)。两个 `step` 用不同的 dt 推进同一个角色,数值积分出来的位置会**不一样**——`pos += vel * dt`,dt 不同位移就不同,几秒后两个位置能差出几个像素。客户端 A 看到自己往前走了 10 米(60 tick),服务器认为 A 只走了 5 米(30 tick),服务器广播"你在 5 米处",客户端弹回去 5 米——这就是 rubber banding,但根本原因不是网络延迟,而是**两边的物理不一致**。

更糟糕的是,这种不一致会被作弊者利用。如果客户端的 dt 比服务器大,客户端每次按 W 走得更远——客户端可以用这个机制"加速移动",即便它在按真实的 W 键。这种 bug 叫 speed hack,是早期很多游戏的常见作弊方式,根因就是服务器和客户端的模拟步长不一致。

固定步长彻底解决这个问题。服务器和客户端用**同一个常数** dt,任何一个 dt 都不能来自墙上时钟、不能来自帧率测量、不能来自任何外部输入——必须是编译期常量。这样,服务器和客户端对"按一次 W 走多远"算出的结果数学上一致(浮点除外,但浮点是另一个话题,见 [phase-8/determinism-and-replay](../phase-8/deep-dives/determinism-and-replay.md))。客户端的预测就算和服务器有出入,也只可能来自网络延迟(输入还没到服务器),不可能来自物理不一致。

这就是为什么服务器的循环长这样——你会发现它和 09B-1 的累加器循环几乎一模一样,只是时间来源不再是 `Instant::now()`,而是"每 1/30 秒被外部触发一次":

```rust
const SERVER_TICK_HZ: u32 = 30;
const FIXED_DT: f32 = 1.0 / SERVER_TICK_HZ as f32;

impl Server {
    fn run(mut self) -> io::Result<()> {
        let tick_dur = Duration::from_micros(1_000_000 / SERVER_TICK_HZ as u64);
        let mut next_tick = Instant::now() + tick_dur;
        loop {
            self.tick()?;   // 收输入 + step + 广播,全部用 FIXED_DT
            let now = Instant::now();
            if now < next_tick {
                std::thread::sleep(next_tick - now);
            } else {
                log::warn!("server tick overrun by {:?}", now - next_tick);
            }
            next_tick += tick_dur;  // 关键:基于"理想"累加,不是 now+tick_dur
        }
    }
}
```

注意最后一行 `next_tick += tick_dur` 是个微妙但关键的细节。如果你写 `next_tick = Instant::now() + tick_dur`,每次 tick 的轻微超时会被"消化"掉,但累计起来会让服务器的"逻辑时间"和现实时间漂移——服务器以为 tick=3000 时现实过了 100 秒,实际可能过了 100.3 秒。正确的写法基于理想累加,tick 序号和时间是一一对应的稳定映射,客户端按 tick 序号估算延迟才准。这是 09B-1 那个"基于累加器而不是基于 now"的原则在服务器侧的重现。

## 3 · Snapshot 压缩:带宽是你每一帧都在打的仗

权威服务器每 tick 要把整个世界状态广播给每个客户端。"整个世界状态"听起来不大——HH 这种游戏可能就几十个 entity,每个几十字节——但你算一下,带宽就开始紧。假设 50 个 entity,每个序列化成 64 字节(位置 + 朝向 + 动画帧 + 血量),30 tick 每秒:50 × 64 × 30 = 96000 字节/秒 ≈ 94 KB/s ≈ 750 Kbps,**每个客户端的下行**。10 个客户端就是 7.5 Mbps 下行,50 个客户端(MMO 规模)就是 37 Mbps。家用宽带的上行通常只有 10-20 Mbps,服务器上行如果是 100 Mbps,几十个客户端就吃满。

这就是 snapshot compression 出现的原因。一个完整的"世界状态"每 tick 全发,是带宽不可承受的;但绝大多数 tick 里,绝大多数 entity 的状态**根本没变**——一个静止的敌人,位置不变、血量不变、动画在循环。把这些"没变"的字节全发一遍,是纯浪费。压缩的思路因此非常清楚:**只发"变化的"部分,没变的不发**。

最基础的压缩是 **quantization(量化)**,把不必要的精度砍掉。位置用 `f32` 是 4 字节,精确到小数点后 7 位——但玩家根本看不出 0.5 毫米的差别。一个游戏地图比如 2000×2000 单位,把位置量化成 `i16`(单位是 1 厘米),覆盖 ±327 米,精度 1 厘米,完全够用——4 字节压成 2 字节,带宽直接砍半。朝向角度同理,`f32` 的弧度换成 `u8`(0-255 对应 0-2π),精度 1.4 度,人眼基本看不出。这套量化把每个 entity 从 64 字节压到 16 字节左右,带宽砍 75%。

```rust
// 量化:把 f32 位置压成 i16(1 厘米精度,地图范围 ±327 米)
fn quantize_pos(x: f32) -> i16 {
    ((x * 100.0) as i32).clamp(-32767, 32767) as i16
}
fn dequantize_pos(q: i16) -> f32 { q as f32 / 100.0 }

// 朝向量化:f32 弧度 → u8(256 等分,精度 1.4 度)
fn quantize_angle(rad: f32) -> u8 {
    let n = (rad % std::f32::consts::TAU + std::f32::consts::TAU) % std::f32::consts::TAU;
    (n / std::f32::consts::TAU * 256.0) as u8
}
```

工业级的 delta encoding 比"逐字段比较"更激进。Quake 3 的网络协议做的是 bit-level diff:把整个 entity 序列化成一个 bit 数组,逐 bit 比较"上次的版本"和"这次的版本",只发"哪些 bit 翻转了"。这套机制叫 Quake 3 delta compression,是工业级 netcode 的教科书实现——你今天去看 Valorant、Apex 的协议,底层思路都是它的演化版。

还有一层是 **bitfield packing**。每个 entity 不是每个字段都发——附一个 bitfield,标记"这次发了哪些字段":第 0 位表示"是否含 position",第 1 位表示"是否含 hp"......客户端先读 bitfield,再按指示读后续字段。一个 entity 可以压到几字节。它的代码骨架长这样:

```rust
const FLAG_POS: u8 = 1 << 0;
const FLAG_HP:  u8 = 1 << 2;
const FLAG_ANIM: u8 = 1 << 3;

fn pack_entity(out: &mut Vec<u8>, prev: Option<&Entity>, cur: &Entity) {
    let mut flags = 0u8;
    if prev.map_or(true, |p| p.pos != cur.pos)  { flags |= FLAG_POS; }
    if prev.map_or(true, |p| p.hp != cur.hp)    { flags |= FLAG_HP; }
    if prev.map_or(true, |p| p.anim != cur.anim){ flags |= FLAG_ANIM; }
    out.push(flags);  // 1 字节,标记后续有哪些字段
    if flags & FLAG_POS != 0 {
        out.extend_from_slice(&quantize_pos(cur.pos.x).to_le_bytes());
        out.extend_from_slice(&quantize_pos(cur.pos.y).to_le_bytes());
    }
    if flags & FLAG_HP != 0 { out.push(cur.hp); }
    // ... 其余字段同理
}
```

把这三层叠加——量化、增量、bitfield——你能把带宽从"每 entity 64 字节 × 30 tick"砍到"平均每 entity < 2 字节 × 30 tick"。50 entity 的游戏,带宽从 750 Kbps 降到 25 Kbps 左右,家用宽带毫无压力。商业联机游戏能做到单客户端下行 100 Kbps 量级,不是因为游戏小,是压缩做得狠。

我必须强调一句:压缩不是"以后优化"。从第一行服务器代码开始,你就要把"这个字段真的需要发吗?这个字段真的需要这个精度吗?"当成架构问题。我见过太多 indie 项目,先跑通"完整状态全发",然后某天发现带宽爆了,回头改 delta encoding——结果整个序列化层和客户端反序列化层都要重写,痛苦不堪。从一开始就用 bitfield + delta,后面加 entity 是渐进的;从一开始用 bincode 全量,后面改 delta 是地狱。

## 4 · 客户端体验:纯服务器权威,延迟会让玩家想砸键盘

架构讲到这里,你应该已经感觉到一个新问题正在浮现。服务器权威解决了反作弊,但代价是:客户端按一个键,要等服务器往返才能看到响应。你按 W——客户端把 W 发给服务器——服务器收到 W、step 一次、把新位置广播回来——客户端收到新位置、渲染。这一整套往返就是你到服务器的 RTT(往返时延)。同城 RTT 5-20ms,玩家几乎无感;跨国 RTT 100-200ms,玩家按 W,100ms 后角色才动——手感像在泥里走路。这就是纯服务器权威的体验代价。

更糟的是,网络抖动(jitter)让这个延迟不稳定。你按 W,这一帧的包走了 80ms 到服务器,服务器回包走了 120ms 回来,总延迟 200ms;下一帧的包走了 50ms 到服务器,回包走了 60ms,总延迟 110ms。客户端看到的角色位置时快时慢——不是均匀地慢,是抽搐地慢。这种"卡顿感"在玩家体验里比稳定延迟更难受。

snapshot interpolation(快照插值)是缓解这个问题的第一招。客户端不直接渲染"刚收到的最新状态",而是维护一个**延迟缓冲区**——把收到的快照放进队列,但渲染时,**渲染 100ms 前的那个快照**。为什么延迟 100ms?因为这 100ms 给了客户端"等下一个快照到达"的余量。网络抖动让快照到达间隔不均匀(可能 25ms 也可能 70ms),但只要抖动不超过 100ms,客户端就总能在"该渲染下一个快照"时,已经在队列里有它——渲染就连续、平滑。代价是玩家看到的画面比服务器真实状态**晚 100ms**——但 100ms 是人类感知的临界值,大多数玩家不会注意到。

```rust
struct ClientInterpolator {
    buffer: VecDeque<(u32, GameState, Instant)>,  // (tick, 快照, 收到时刻)
    render_delay: Duration,                        // 100ms
}

impl ClientInterpolator {
    fn on_packet(&mut self, tick: u32, state: GameState) {
        self.buffer.push_back((tick, state, Instant::now()));
        while self.buffer.len() > 6 { self.buffer.pop_front(); }
    }

    fn current_render_state(&self) -> Option<GameState> {
        let target_time = Instant::now() - self.render_delay;
        let states: Vec<_> = self.buffer.iter().collect();
        for w in states.windows(2) {
            let (_, s1, recv1) = w[0];
            let (_, s2, recv2) = w[1];
            // 在两个快照的到达时刻之间,按比例插值
            if *recv1 <= target_time && target_time <= *recv2 {
                let alpha = (target_time - *recv1).as_secs_f32()
                          / (*recv2 - *recv1).as_secs_f32();
                return Some(s1.lerp(s2, alpha));
            }
        }
        states.last().map(|(_, s, _)| (*s).clone())
    }
}
```

但 snapshot interpolation 只解决了"远程玩家看起来不卡",**解决不了"本地玩家按键到响应的延迟"**。本地玩家按 W,他自己的角色也要等 100ms(服务器往返)+ 100ms(插值缓冲)= 200ms 才动——这个延迟玩家绝对感知得到,而且非常难受。

这就是这一篇和它的姊妹篇——[phase-5/network-prediction-and-rollback](../phase-5/deep-dives/network-prediction-and-rollback.md)——必须配套的原因。权威服务器和预测客户端是**同一套模型的两个半边**,缺一不可:服务器侧(本篇)跑真实模拟、广播权威状态、拒绝任何客户端的状态主张;客户端侧(下一篇)本地预测自己的输入会带来什么变化,**乐观地先在本地执行**,服务器权威状态到达后再**和解**(reconcile)。

两边的关系很像数据库里的乐观并发控制(optimistic concurrency control)。客户端假设"我的预测多半是对的",先干起来;服务器是 transaction 的最终 committer。如果客户端的乐观版本和服务器 confirm 的版本不一致,客户端回滚到服务器版本,然后基于服务器版本重放"那之后我自己又按的键"。这套机制让玩家的本地输入**立即响应**,同时保持服务器的最终权威。延迟被隐藏在"预测正确"的概率里,绝大多数 tick 预测都是对的,玩家感觉不到网络存在。

这一篇的 scope 到服务器侧为止。但你脑子里要清楚:写一个不带 client prediction 的纯权威服务器,玩家会觉得这游戏"卡得没法玩";写一个不带 server authority 的纯 client prediction,玩家会觉得这游戏"全是外挂"。两个半边缺一不可——这就是为什么这两篇必须连着读。

## 5 · 服务器架构:单线程模拟 vs 模拟线程 + 网络线程

服务器跑权威模拟,有个架构选择:是把"收包、step、发包"全部放在一个线程里串行,还是拆成多个线程?这个选择看似是实现细节,但它影响你服务器的可扩展性和正确性。

最简单的版本是**单线程**:主循环每 tick 顺序做三件事——`recv` 收所有客户端输入、`step` 推进模拟、`send` 广播快照。这种结构的好处是**没有并发问题**:整个游戏状态只被一个线程碰,不需要锁,不需要 atomic,不需要 happens-before 推理。`step` 是纯函数式的状态机,你给它输入和新状态,它返回新状态——单线程下,这个状态机就是确定性的、可推理的。

```rust
fn run_single_thread(mut server: Server) -> io::Result<()> {
    let tick_dur = Duration::from_millis(1000 / SERVER_TICK_HZ as u64);
    let mut next = Instant::now() + tick_dur;
    loop {
        server.recv_all_inputs()?;
        server.step();           // 整个 simulation 在这一行
        server.broadcast_snapshot()?;
        sleep_until(next);
        next += tick_dur;
    }
}
```

单线程够用多久?比你想得久。一个写得紧凑的 `step`,处理 100 个 entity 大约 0.5ms;1000 个 entity(中型 MMO 一个 zone)大约 5ms;10000 个 entity(大型 battle royale)大约 50ms——已经超出 30 tick 的预算了。也就是说,单线程能撑到几百个 entity / 几十个客户端的规模,这对大多数 indie 联机游戏够用。HH 这种几十个 entity 的游戏,单线程绰绰有余。

但当你想往上扩——上千客户端,或者模拟本身很重(复杂 AI、物理)——单线程就不够了。这时常见的拆法是**模拟线程 + 网络线程**分离:一个线程专门跑 `step`(独占游戏状态,不被打扰),另一个线程专门做 socket I/O(收包放进队列、从队列拿包发出去)。两个线程通过 lock-free 队列交换数据:网络线程把"这一 tick 的输入"丢给模拟线程,模拟线程把"这一 tick 的快照"丢给网络线程。

```rust
use crossbeam_channel::unbounded;

// 两个线程通过 channel 解耦
let (input_tx, input_rx) = unbounded::<(SocketAddr, ClientInput)>();
let (snap_tx,  snap_rx)  = unbounded::<Snapshot>();

// 网络线程:只管 I/O,不碰 game state
std::thread::spawn(move || {
    let socket = UdpSocket::bind(server_addr).unwrap();
    socket.set_nonblocking(true).unwrap();
    let mut buf = [0u8; 1500];
    loop {
        while let Ok((n, addr)) = socket.recv_from(&mut buf) {
            if let Ok(input) = bincode::deserialize::<ClientInput>(&buf[..n]) {
                let _ = input_tx.send((addr, input));
            }
        }
        while let Ok(snap) = snap_rx.try_recv() {
            let bytes = bincode::serialize(&snap).unwrap();
            for c in &clients { let _ = socket.send_to(&bytes, c); }
        }
        std::thread::sleep(Duration::from_millis(1));
    }
});

// 模拟线程:独占 game state,跑固定 tick
std::thread::spawn(move || {
    let mut state = GameState::new();
    let mut next = Instant::now() + tick_dur;
    loop {
        let mut inputs = Vec::new();
        while let Ok(inp) = input_rx.try_recv() { inputs.push(inp); }
        step(&mut state, FIXED_DT, &inputs);   // state 只在这里被访问
        let _ = snap_tx.send(state.snapshot());
        sleep_until(next);
        next += tick_dur;
    }
});
```

这种拆法的好处是 `step` 拿到专属的 CPU 核心,不被 socket I/O 的 syscall 打断;网络线程跑满 I/O,不被 `step` 的 CPU 工作阻塞。syscall 和数值计算在 CPU 上的"节奏"完全不同——混在一起会互相干扰,分开就各得其所。

但拆线程的代价是**并发正确性**。channel 必须是 lock-free 的(否则网络线程阻塞会让模拟线程也卡住);队列里的输入/快照要打上 tick 序号,让模拟线程区分"这个输入属于哪个 tick"。这些并发细节在 [phase-0/25-concurrency-foundation](../phase-0/25-concurrency-foundation.md) 和 [phase-5/threading-journey](../phase-5/deep-dives/threading-journey.md) 都讲过,这一篇不展开。

还有一个更深的架构问题:**很多客户端时,广播本身就是瓶颈**。一个 zone 里有 1000 个客户端,服务器每 tick 要发 1000 个包——`send_to` 是 syscall,每个 syscall 几千 cycles,1000 个就是几百万 cycles,光发包就吃掉一个 tick 的一大部分预算。这时你需要 broadcast 优化:用 multicast(UDP multicast,一组包一次发,路由器复制),或者把多个客户端的快照打包成一个超大包再切片,或者——更激进的——**根本不全量广播**。最后这一条引出下一篇 09E-3 的主题:interest management(兴趣管理)。基本思路是,**客户端只关心他附近的 entity**,所以服务器只给他发他附近的——一个玩家根本看不到 1000 个之外的 entity,发给他就是纯浪费带宽。这套机制把"O(客户端数 × entity 数)"的广播复杂度,降到"O(客户端数 × 邻居数)",这是 MMO 能跑起来的根本原因。

## 6 · 生产现实:这是每一款竞技联机游戏都在跑的架构

讲到这里,我想花一节让你感受这个架构有多"工业 standard"。你今天打开 CS2、Valorant、Apex、Overwatch、《街头霸王 6》《罪恶装备奋战》、Rocket League——它们的服务器架构核心,就是这一篇讲的那套:服务器跑权威模拟,客户端发输入,服务器广播状态,客户端预测+和解。区别只在细节——tick rate 多少、压缩多狠、prediction 多深、lag compensation 怎么做。但"权威在服务器"这一条,**无一例外**。

为什么这么统一?因为这个架构是几十年来"反作弊 vs 体验"博弈的均衡点。把权威放服务器,反作弊最强但体验最差(延迟);把权威放客户端,体验最好但反作弊最弱(随便作弊)。客户端预测+和解是走出这个两难的关键技术——它让"权威在服务器"也能有"本地立即响应"的体验,从而把权威架构从"理论可行"推到"生产可用"。从 Quake 1996 第一次实现 client-side prediction 开始,这套架构被反复打磨了 30 年,到 2026 年已经是默认选项。

这个架构的成本主要在工程复杂度:tick 调度、状态序列化、增量压缩、广播、断线处理、reconnect 状态恢复、anti-tamper 校验、speed hack 检测......每一个都是独立的子系统。一个 indie 想从零写一个能跑的权威服务器,工作量在月级——这也是为什么 renet / Nakama / EOS / Photon 这些 netcode 中间件有市场。但对学习而言,**从零写一遍**是值得的。你不写一遍,根本不知道"reconnect 时怎么把客户端对齐到正确的 tick""断线检测的超时设多久才不会误伤抖动玩家"。这些经验值,只有自己踩过坑才内化。这就是下一节"在你 HH 项目里动手"要你做的事。

## 7 · 在你 HH 项目里动手(做中学红线)

理论讲完,做中学开始。这一节的目标是:把你的 HH 游戏改造成一个最小可跑的"权威服务器 + 哑客户端"系统。两个客户端通过一台服务器看到同一个世界;其中一个客户端哪怕改内存、伪造包,也无法影响服务器认定的真相。然后你给本机加模拟延迟,**亲手感受**纯服务器权威的延迟——这种感受会驱动你去看下一篇 client prediction。

**第一步:把 HH 改成 headless 可构建**。

你的 HH 游戏目前是一个单进程:主循环里 update + render。第一步是把"模拟"和"渲染"在代码上彻底分离——这一步其实 [09A-1](09A-1-testable-game-architecture.md) 和 [09B-1](09B-1-game-loop-and-timestep.md) 都让你做过了,这里只是确认。你的 `step(state: &mut State, dt: f32, inputs: &Inputs)` 必须是**纯函数式的**,不碰渲染、不碰窗口、不碰手柄——它只读 state、读 inputs、写 state。然后你的 `Cargo.toml` 加一个 feature flag:

```toml
[features]
default = ["render"]
render = ["dep:winit", "dep:wgpu"]
headless = []
```

`src/main.rs` 顶层根据 feature 选 server 或 client 入口:

```rust
#[cfg(feature = "headless")]
fn main() -> io::Result<()> { server::run() }

#[cfg(not(feature = "headless"))]
fn main() -> io::Result<()> { client::run() }
```

构建两份二进制:`cargo build --features headless --bin hh_server`、`cargo build --bin hh_client`。这一步的本质是:你的游戏逻辑是 headless 可跑的——这是从 09A-1 的可测架构一路下来的回报。

**第二步:写一个最小的 UDP 服务器**。

复用 [09E-1](09E-1-reliable-udp-transport.md) 的可靠 UDP 通道,但这里为了教学清晰用裸 UDP,生产环境换成 09E-1 的 reliable channel。

```rust
// hh_server/src/main.rs —— 关键骨架
const SERVER_TICK_HZ: u32 = 30;
const FIXED_DT: f32 = 1.0 / SERVER_TICK_HZ as f32;
const PROTO_VERSION: u32 = 1;

#[derive(serde::Serialize, serde::Deserialize)]
struct InputPacket { proto: u32, client_id: u64, tick: u32, buttons: u16 }
// buttons: bit 0=W, 1=A, 2=S, 3=D, 4=Jump, 5=Attack

#[derive(serde::Serialize, serde::Deserialize)]
struct SnapshotPacket { tick: u32, entities: Vec<EntitySnap> }

#[derive(Copy, Clone, serde::Serialize, serde::Deserialize)]
struct EntitySnap { id: u32, x: i16, y: i16, hp: u8, facing: u8, anim: u8 }
// 位置量化到 1 厘米,朝向量化到 256 等分

fn main() -> io::Result<()> {
    let socket = UdpSocket::bind("0.0.0.0:5000")?;
    socket.set_nonblocking(true)?;
    let mut state = hh_core::GameState::new();  // 复用你的 step
    let mut inputs: HashMap<u64, u16> = HashMap::new();
    let mut addrs: HashMap<u64, SocketAddr> = HashMap::new();
    let mut buf = [0u8; 1500];
    let tick_dur = Duration::from_millis(1000 / SERVER_TICK_HZ as u64);
    let mut next = Instant::now() + tick_dur;

    loop {
        // 1. 收所有 pending 输入
        loop {
            match socket.recv_from(&mut buf) {
                Ok((n, addr)) => {
                    if let Ok(pkt) = bincode::deserialize::<InputPacket>(&buf[..n]) {
                        if pkt.proto != PROTO_VERSION { continue; }
                        inputs.insert(pkt.client_id, pkt.buttons);
                        addrs.entry(pkt.client_id).or_insert(addr);
                    }
                }
                Err(ref e) if e.kind() == io::ErrorKind::WouldBlock => break,
                Err(_) => break,
            }
        }
        // 2. step——和客户端完全一样的函数!
        hh_core::step(&mut state, FIXED_DT, &inputs);
        // 3. 序列化 + 广播
        let snap = SnapshotPacket {
            tick: state.tick,
            entities: state.entities.values().map(|e| EntitySnap {
                id: e.id,
                x: (e.pos.x * 100.0) as i16,
                y: (e.pos.y * 100.0) as i16,
                hp: e.hp.min(255) as u8,
                facing: ((e.facing.rem_euclid(std::f32::consts::TAU)
                          / std::f32::consts::TAU) * 256.0) as u8,
                anim: e.anim_frame as u8,
            }).collect(),
        };
        let bytes = bincode::serialize(&snap).unwrap();
        for (_id, addr) in &addrs { let _ = socket.send_to(&bytes, addr); }
        // 4. 固定节拍
        let now = Instant::now();
        if now < next { std::thread::sleep(next - now); }
        next += tick_dur;
    }
}
```

注意几个工程细节。第一,`proto: u32` 字段是 protocol versioning——以后协议改了,旧客户端发的包不会让服务器崩。第二,客户端的 `client_id` 在生产环境一定要是**服务器签发的 token**——客户端不能自己声明 ID,否则它声称自己是别人就能伪造别人的输入。这里教学简化,直接信任 client_id 字段,生产环境必须加 [09E-1](09E-1-reliable-udp-transport.md) 讲的鉴权。第三,`tick` 字段让客户端知道"这是服务器第几个 tick 的状态",client prediction 的和解逻辑(下一篇)要靠这个 tick 序号对齐。

**第三步:写一个最小客户端**。

客户端的工作就两件:采集本地输入发给服务器、把收到的快照拿来渲染。客户端**完全不跑 simulation**——它甚至不知道"按 W 角色怎么移动",它只知道"按 W 我把 W 这一位塞进 buttons 发给服务器,然后等服务器告诉我角色在哪"。

```rust
// hh_client/src/main.rs —— 关键骨架
const MY_CLIENT_ID: u64 = 0xC0FFEE;  // 生产:从 auth server 拿

fn main() -> io::Result<()> {
    let socket = UdpSocket::bind("0.0.0.0:0")?;
    socket.set_nonblocking(true)?;
    let server_addr: SocketAddr = "127.0.0.1:5000".parse().unwrap();
    let mut interp = InterpBuffer::new(Duration::from_millis(100));
    let mut local_tick: u32 = 0;
    let mut buf = [0u8; 2048];
    let frame_dur = Duration::from_millis(16); // 60 FPS 渲染
    let mut next_frame = Instant::now() + frame_dur;

    loop {
        local_tick += 1;
        // 1. 采集本地输入,发给服务器
        let buttons = read_keyboard();
        let pkt = InputPacket { proto: 1, client_id: MY_CLIENT_ID, tick: local_tick, buttons };
        let _ = socket.send_to(&bincode::serialize(&pkt).unwrap(), server_addr);
        // 2. 收服务器快照,塞进插值 buffer
        loop {
            match socket.recv_from(&mut buf) {
                Ok((n, _)) => {
                    if let Ok(snap) = bincode::deserialize::<SnapshotPacket>(&buf[..n]) {
                        interp.on_packet(snap.tick, snap, Instant::now());
                    }
                }
                Err(ref e) if e.kind() == io::ErrorKind::WouldBlock => break,
                Err(_) => break,
            }
        }
        // 3. 插值拿渲染状态,画
        if let Some(render_state) = interp.current_render_state() {
            render(&render_state);
        }
        let now = Instant::now();
        if now < next_frame { std::thread::sleep(next_frame - now); }
        next_frame += frame_dur;
    }
}
```

`InterpBuffer` 就是 §4 那个 `ClientInterpolator`,这里不重复贴。`render` 把快照里的 entity 画到屏幕,动画帧根据 `anim` 字段查 spritesheet。

**第四步:跑两个客户端 + 一个服务器,验证三件事**。

```bash
# 终端 1:服务器
cargo run --features headless --bin hh_server

# 终端 2:客户端 A
cargo run --bin hh_client

# 终端 3:客户端 B
cargo run --bin hh_client
```

你要看到三件事:

第一,**两个客户端看到同一个世界**。客户端 A 按住 W,他的角色往前走;客户端 B 的屏幕上,A 的角色也在往前走(可能有 100ms 滞后,这是 snapshot interpolation 的延迟)。两个客户端对"角色现在在哪"达成一致——这是权威广播的直接结果。

第二,**客户端撒谎被无视**。开第三个终端,用 Python 伪造一个客户端,发`InputPacket { client_id: <假装是 A 的 ID>, buttons: 0 }` 想覆盖 A 的输入——服务器确实会把它当作 A 这一帧的输入(假设没加签名校验)。这是为什么生产环境一定要有 [09E-1](09E-1-reliable-udp-transport.md) 讲的加密 token——你不能让别人假冒你的 client_id。但即便如此,这个伪造的客户端**无法做**一件事:它无法让 A 的角色瞬移到 boss 脚下。它只能发"按了什么键",移动多远是服务器算的,它影响不了。客户端能撒谎的范围被严格限制在"输入"层,影响不了"状态"层。

第三,**模拟延迟,亲身感受纯权威的卡顿**——这是这一节最重要的体验。用 Linux 的 `tc netem` 给本机 loopback 加 100ms 单程延迟(200ms RTT):

```bash
# 给 lo 加 100ms 单程延迟(双程 200ms RTT)
sudo tc qdisc add dev lo root netem delay 100ms
cargo run --bin hh_client     # 感受按 W 角色多晚才动
sudo tc qdisc del dev lo root # 测完移除

# 还能模拟丢包(必须测):
sudo tc qdisc add dev lo root netem delay 100ms loss 5%
```

你按 W,你会看到角色**约 200ms 后才动**(200ms RTT + 100ms 插值缓冲)。在 FPS 或格斗游戏里,这个延迟会让游戏完全没法玩——这种切身体验会驱动你去看下一篇 [phase-5/network-prediction-and-rollback](../phase-5/deep-dives/network-prediction-and-rollback.md):"为什么不让客户端在本地先把这一步算了?"就是 client-side prediction 的全部动机。模拟丢包时,单个包丢了,客户端插值 buffer 少一个快照,渲染会"停"在那个位置一帧;连续丢好几个,角色会"瞬移"到最新位置——这就是 jitter spike,下一篇 prediction 也会缓解它。

**做完这一节,你应该 commit**。提交信息可以写 "implement authoritative server with snapshot interpolation, validate anti-cheat and feel lag"。这是你 HH 项目里"联机化"的第一个真实里程碑——你已经有了一个能跑、能反作弊、能感受到延迟的服务器,下一篇就是把延迟藏起来。

## 8 · 练习

练习一(Lv1,概念辨析)。有人问:"既然服务器权威这么好,为什么不直接让服务器连渲染都包了,客户端就是个瘦终端,只显示视频流?"想清楚这个方案的可行性边界——它的延迟模型(服务器渲染 + 视频编码 + 网络传输 + 客户端解码)和服务器状态广播有什么本质区别。提示:想想 OnLive 和 Stadia 为什么死了,而 GeForce Now 活着;再想想"网络传输 60 FPS 视频流"和"网络传输 30 Hz 状态快照"的带宽量级差异。

练习二(Lv2,动手实践)。完成 §7 的全套改造——headless 服务器、客户端、两个客户端联机、netem 模拟延迟。提交 commit。这是后续 09E-3 兴趣管理的前置基础,不做完没法继续。

练习三(Lv3,深入量化)。给你 HH 的 entity 加一套完整的量化方案——位置 `i16`(1cm 精度)、速度 `i8`(0.1 单位/帧精度)、朝向 `u8`、动画帧 `u8`。对比量化前后的带宽,写在 commit message 里。然后做一个边界测试:让角色快速移动到地图边缘(量化溢出),确认 `clamp` 兜底正确,没有 panic。最后,加一个"量化往返误差"的单元测试——给定一个浮点位置,量化再反量化,误差不能超过 1cm。

练习四(Lv4,系统设计)。给你的服务器加 **delta encoding**——记住每个客户端上次收到的 entity 版本,每 tick 只发变化的字段。用 bitfield packing 表示"哪些字段变了"。测试:让一个 entity 静止 10 秒,确认 10 秒内它**不发任何字节**(除了"没变"的标记 bit)。再测试:让一个 entity 不停移动,确认它的每 tick 字节数和"只发 position 字段"一致。这个练习做完,你的带宽应该比"全量广播"低一个数量级。

## 9 · 延伸阅读与下一篇

Glenn Fiedler 的 Gaffer on Games 系列里,《Snapshot Interpolation》和《State Synchronization》两篇是这一篇的直接祖师爷,网上直接搜得到,讲得比我更朴素更直接——如果你觉得我哪里绕,强烈建议读原文,它们更短。Valve 的 Source Multiplayer Networking wiki 是工业级实现的第一手资料,讲 snapshot interpolation + lag compensation,Quake 3 的源码(`code/server/sv_net_chan.c`)是 delta compression 的教科书实现,值得逐行读。Jason Gregory 的《Game Engine Architecture》第三版有专门的网络章节,讲 server-authoritative 架构的系统化设计。

本仓库内的相关内容:[09E-1](09E-1-reliable-udp-transport.md) 是这一篇的传输层前置,本篇的 UDP 都假设走它给的可靠通道;[09B-1](09B-1-game-loop-and-timestep.md) 的固定步长是服务器侧 `step` 的正确性基石,服务器的 tick 必须用固定 dt;[phase-8/determinism-and-replay](../phase-8/deep-dives/determinism-and-replay.md) 把"为什么浮点会让 step 不一致"讲透,本篇假设你已经在那篇里驯服了浮点;[phase-5/network-multiplayer-models](../phase-5/deep-dives/network-multiplayer-models.md) 是这一篇所在大厦的鸟瞰图,本篇是其"state sync / snapshot interpolation"分支的深挖;[phase-5/network-prediction-and-rollback](../phase-5/deep-dives/network-prediction-and-rollback.md) 是这一篇的客户端对偶——权威服务器和预测客户端是同一套模型的两个半边,两篇必须连着读才能看到完整图景。

下一篇 [09E-3](09E-3-interest-management-and-replication.md) 会从这一篇的"广播给所有客户端"出发,讲为什么这个朴素广播在大规模(MMO、battle royale)下不可持续,以及工业级的解法——interest management(兴趣管理,只发客户端附近的 entity)、空间划分(grid / quadtree / AoI)、relevance filtering、host migration、server clustering。如果说这一篇讲的是"权威服务器怎么跑得对",下一篇讲的就是"权威服务器怎么跑得起规模"。
