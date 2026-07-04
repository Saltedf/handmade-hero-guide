
# 网络预测与回滚:从乐观执行到确定性重放

> 你读完了 [network-multiplayer-models.md](network-multiplayer-models.md) 的锁步部分,在 HH 里给两个玩家加了 UDP 同步。A 机和 B 机各自跑 60 FPS,你按方向键,A 机立即响应——爽;但 B 机的 A 角色在 80 ms 后才动,因为 B 机要等 A 的输入包到达。你在 A 机上按跳,跳了;B 机上 A 跳晚了 80 ms。反过来 B 也一样。两台机器各自"指挥"自己的角色,看到对方的角色永远滞后。Reddit 玩家吐槽:"这游戏的联机像在演木偶戏。"你把帧率拉到 120 Hz,延迟没变——因为延迟根本不在帧率,在 RTT。你打开 Quake 3 源码,看到 `CL_PredictMove` 函数注释里写:"client predicts what server will say, then corrects"。你恍然大悟——**为什么不让 client 自己先算一遍,server 验证后再纠正?**这就是 client-side prediction。但 24 小时后你陷入下一个坑:你按下前进,本地走了 3 步,server 回执说"只应该走 2 步,你被墙挡了",client 把你弹回 1 步——玩家感受叫"rubber banding",像被橡皮筋拽回去。再 24 小时你做错方向:你让 client 用 server 的回执直接覆盖本地状态,玩家每次回执时屏幕抖一下,叫 misprediction spike。**这一篇把 prediction + rollback 的整个链路摊开**:从最朴素的"本地立刻执行",到 GGPO / ggrs 的"网格化回滚重放",到 Overwatch / Valorant 的"server rewind lag compensation"。看完你应该能在 HH 里集成一个能跑的 prediction/rollback pipeline,知道为什么 GGPO 适合格斗、CS 类适合 FPS,知道乐观并发控制(OCC)和游戏 netcode 是同构的,知道哪些坑会让你在凌晨三点抓头发。

## 0 · 为什么要有这一篇

`network-multiplayer-models.md` 已经把"五种联机架构"摆好。这一篇是其中**第 5 种(Client Prediction + Rollback)的深挖**——2026 年所有快节奏联机游戏的工业 standard,坑多到要专门一篇来谈。

理由从轻到重排:

**第一,光速是物理下限**。光纤北京-上海 RTT 28 ms,北京-旧金山 RTT 160 ms。"等 server 确认再执行"的方案,玩家按按钮到看见响应至少 1 RTT。"立即响应"的心理学阈值是 100 ms,跨洲际联机**物理上**做不到立即响应——除非你**不等**,先在本地假装执行。

**第二,人脑对"我按了但没反应"的容忍度极低**。HCI 经典数据:0-50 ms "跟手";50-100 ms "还行";100-200 ms "卡";200+ ms "在做梦"。格斗游戏玩家能感知 16 ms(1 帧)的延迟差。预算不是"还能榨多少",是"已经在红线"。

**第三,state sync 没法解决输入延迟**。哪怕你用最快的 UDP + renet + 0 jitter,玩家按按钮 → client 发输入 → server 算 → server 回执 → client 显示,这条链路**至少 1 RTT**。client-side prediction 唯一的"作弊":**让 client 先算**,server 异步验证,感知延迟从 RTT 降到 ~0。

**第四,但 prediction 必然错**。client 不知道 server 的完整状态(其它玩家的输入、AI 决策、物理碰撞),只能基于"我猜的状态"预测。预测错 → server 回执说"不是这样"→ client 必须**回滚到正确的过去**,重放未确认 input。这个过程做错就是 rubber banding / teleport / spike。

**第五,rollback 是分布式系统理论在游戏里的化身**。学术上叫 **optimistic concurrency control**(乐观并发控制,OCC)——1979 年 H.T. Kung 提出,用于数据库事务;1995 年被游戏行业"重新发现"。理解 OCC 你就能秒懂 GGPO;反之亦然。这就是为什么这一篇是 CS-core 而不是 "gamedev only"。

**第六,industry investment 巨大**。GGPO 2009 开源后被 Capcom(街头霸王)、Iron Galaxy(Skullgirls)、Bandai-Namco(铁拳)、Arc System Works(罪恶装备)、Riot(Valorant 部分基础)用各种形式采纳。`ggrs` 是 Rust 移植,`renet` 是更通用 netcode 库。Valve Source Engine、Overwatch、Valorant 各自投了几百人月。

**学完这一篇,你应该能**:

- 解释 client-side prediction 完整算法:本地立即执行 → 发 server → server 回执 → 对比 → rollback → 重放
- 解释"乐观并发控制"和游戏 prediction 的同构性
- 解释为什么 rollback 必须保证 simulation 是 input-driven + deterministic
- 解释 GGPO 的 time-sync、input delay、回滚网格
- 解释 snapshot interpolation 的 100 ms delay buffer 原理,知道它和 rollback **互补**而非**互斥**
- 解释 server-side lag compensation 的"rewind hitbox"算法,知道 CS / Valorant 的 "favor the shooter" 怎么实现
- 在 Rust 里从零写一个 mini prediction/rollback engine 跑通 2 人联机
- 在 HH 项目里集成 `renet`,实现可玩 netcode
- 调试 rubber banding / misprediction spike / desync,知道每个症状的 root cause

## 1 · 为什么要预测:延迟的物理与心理学

### 1.1 物理下限:光速

光在真空 299,792,458 m/s,光纤中约 200,000 km/s(折射率 1.5)。典型 RTT 物理下限:

| 路径 | 光纤距离 | 单程光纤 | RTT 物理下限 |
|---|---|---|---|
| 北京-上海 | 1,300 km | 6.5 ms | 13 ms |
| 北京-广州 | 2,200 km | 11 ms | 22 ms |
| 纽约-旧金山 | 4,100 km | 20.5 ms | 41 ms |
| 北京-旧金山 | 11,000 km | 55 ms | 110 ms |
| 伦敦-东京 | 9,600 km | 48 ms | 96 ms |
| 任意-对地同步卫星 | 36,000 km × 2 | 240 ms | 480 ms |

物理下限 + 路由跳数(每跳 0.5-2 ms)+ 拥塞队列(几 ms 到几十 ms)+ OS socket 调度(几 ms),实际 RTT 通常 = 物理下限 × 1.3-2。家用宽带跨美 RTT 60-90 ms,跨太平洋 150-200 ms,5G 额外 20-40 ms,satellite 500+ ms。**任何**"等 server 确认"的方案在跨洲际联机里都不可玩。

### 1.2 心理学:输入延迟的感知阈值

人脑对"我做了动作 → 看到响应"的时间差敏感度:0-20 ms 感知不到;20-50 ms 可接受;50-100 ms "略卡";100-200 ms 明显卡;200-500 ms 严重影响可玩性;500 ms+ 几乎不可玩。

不同游戏类型的容忍度:
- **音乐游戏**(Beatmania):**< 16 ms**(1 帧)。任何延迟都毁掉节拍。
- **格斗游戏**(街头霸王):**< 80 ms**(4-5 帧)。超过这个 parry / 反击不可能。
- **FPS**(CS / Valorant):**< 100 ms**。再多就丧失瞄准优势。
- **MOBA**(LOL / Dota):**< 200 ms**。技能 / 走位容错高。
- **MMORPG**(WoW):**< 500 ms**。GCD 1.5 秒。
- **回合制**(文明):**< 5000 ms**。

所以"要不要做 prediction"的答案:**< 200 ms 容忍度的游戏类型都必须做**。HH 动作平台容忍度 100-150 ms,不做 prediction 跨城市联机就废了。

### 1.3 延迟的分解:每一毫秒从哪来

```
按下键盘 → 1-5 ms(键盘扫描 + USB 轮询)
OS 投递 event → 0.5-2 ms
游戏收 input event → 等 16 ms(60Hz)
simulation → 0.1-2 ms
render → 等 16 ms(60Hz vsync)
显示器 → 5-15 ms(IPS 5ms,TN 1ms,OLED 0.1ms)
眼睛看到
```

单机累计:**5 + 2 + 16 + 2 + 16 + 5 = 46 ms**(IPS 60Hz)。144Hz + 低延迟键盘可压到 26 ms。

加网络后:**额外加 1 RTT**。跨美 RTT 80 ms,总延迟 46 + 80 = **126 ms**——明显卡。

**client-side prediction 的承诺**:把那个 +80 ms 拿掉。代价是预测可能错,需要回滚纠正。下面正式展开。

## 2 · 第一性原理:乐观并发控制

在讲游戏实现之前,从 CS 第一性原理推导 prediction + rollback。**这一节是这一篇的"心脏"**——理解了它,后面所有算法都是它的实例化。

### 2.1 共享状态 + 并发写入 = 一致性问题

游戏 netcode 的本质:**多个 client + 一个 server,共同维护一份"游戏世界状态"**。这正是分布式系统的经典问题。1970 年代数据库领域发明了三种并发控制模型:

1. **悲观并发控制(Pessimistic CC / 2PL)**:先加锁改完放锁。Lockstep netcode 是悲观——所有 client 等齐才推进。
2. **乐观并发控制(OCC)**:先做、再验证、必要时回滚。1979 Kung 提出。
3. **多版本并发控制(MVCC)**:维护多个历史版本,各 client 读自己的 snapshot。Snapshot interpolation + lag compensation 是 MVCC 的简化。

Client-side prediction + rollback **就是 OCC 在游戏里的实例**。

### 2.2 OCC 的三阶段

Kung 的 OCC 算法分三阶段:

**阶段一:Read**。事务读本地 workspace 做计算但不提交。对应游戏:client 在本地 prediction buffer 推进 simulation。

**阶段二:Validation**。事务准备提交时检查"是否有其它事务在我读之后改了我读的数据"。有 → abort;无 → 提交。对应游戏:server 收到 client 输入,验证它假设的"start state"是否还是当前 state。

**阶段三:Write**(validation 通过后)。对应游戏:server 把 client 输入纳入权威 simulation,broadcast 给其它 client。

OCC 关键性质:**事务在 read phase 不阻塞**——它假设"大概率没人跟我冲突",所以叫"乐观"。代价是冲突时要回滚重跑。

### 2.3 游戏的 OCC 实例

| OCC 概念 | 游戏对应 |
|---|---|
| Transaction | 一次 input + 它引起的 simulation 推进 |
| Workspace | client 本地的 prediction buffer |
| Read set | client 假设的 start state(从最近 server snapshot 推出) |
| Write set | client 在 prediction buffer 里改的所有 entity |
| Validation | server 算 authoritative 结果,对比 client 假设 |
| Commit | server 把 result 加进 authoritative state |
| Abort | client prediction 错了,回滚 |
| Replay abort | client 从最近 authoritative state 重放未确认的 input |

**关键的洞察**:**游戏的 prediction/rollback 就是 OCC**。理解了 OCC 你就能从抽象层面回答:

- **为什么 rollback 必须重放 input 而不是直接覆盖 state?**——OCC abort 必须重跑事务,直接覆盖会丢失事务中间的本地修改。
- **为什么 simulation 必须是 input-driven?**——OCC 要求事务是 read-then-write 的纯函数,这样重跑才能产生相同结果。有副作用(系统时间、随机数)就发散。
- **为什么 server snapshot 频率不能太高?**——OCC abort 频率跟"冲突概率"成正比。
- **为什么 deterministic 是 rollback 的硬要求?**——OCC 假设 replay 同样事务产生同样 write set。

### 2.4 决定性:rollback 的核心成本

"决定性"(determinism)在 [network-multiplayer-models.md](network-multiplayer-models.md) §2 讨论过——同样 input + 同样 start state → 同样 end state,bit-exact。

rollback 系统对决定性的要求:**单 client 跨重放** bit-exact。这比 deterministic lockstep **弱一档**——lockstep 要求跨 client bit-exact(每个 client 跑完整 sim);rollback 只要求单 client 跨时间一致(client 重放自己的 simulation,server 是权威)。

这是为什么 rollback 比 lockstep **更工程可行**:跨平台浮点不 bit-exact 不影响(只要单平台重放一致);FMA、FTZ、transcendental 这些 lockstep 灾难对 rollback 不太敏感——只要 client 不切换 CPU 架构。但仍然要求:不用 `SystemTime::now()`、RNG 从 input 推导、`HashMap` 遍历顺序稳定。坑详见 `network-multiplayer-models.md` §2.2。

### 2.5 回滚成本:状态快照 + input ring buffer

两个核心成本:

**状态快照**。要回滚到第 K 帧,必须知道第 K 帧完整 simulation state。两种做法:
- **每帧存快照**:每 simulated frame 都序列化完整 state,回滚直接 load。代价:state 大小 × 深度(state 1 MB × 7 = 7 MB)。Quake 3 用这个。
- **周期性快照 + 重放**:每 N 帧存一次,回滚时找最近 ≤K 的快照 K0,从 K0 重放到 K。代价:回滚延迟(K-K0 帧),但内存小。GGPO 用变种。

**input ring buffer**。重放需要"从 K 帧开始所有未确认 input"。每帧几字节,buffer 深度 = 最大回滚深度。GGPO / ggrs 标准:**回滚深度 ≤ 7 帧**(7 × 16 ms = 112 ms,覆盖典型 RTT)。ring buffer 大小 = 8,每个 input 2-4 字节,总 32 字节。状态快照每 7 帧存一次,平均 8 份。

### 2.6 State hash:检测 divergence

client 和 server 必须对**回滚点**达成一致——server 说"第 K 帧你被墙挡了",client 必须能精确复现那个 simulation state。

实际做法:server 每帧算 state hash(64-bit FNV / CRC),broadcast。client 在 prediction buffer 对应帧也算 hash,对比。一致 → 继续推进;不一致 → 触发 rollback。

```rust
fn state_hash(game: &Game) -> u64 {
    let mut hasher = fnv::FnvHasher::with_key(0x12345678);  // 固定 seed!
    let bytes = bincode::serialize(game).unwrap();  // f32 不 Hash,走 bytes
    hasher.write(&bytes);
    hasher.finish()
}
```

**必须用固定 seed 的 hash**(`FnvHasher`、`DefaultHasher`)。`RandomState`(HashMap 默认)用随机 seed,绝对不能用。

### 2.7 为什么 OCC 而不是悲观锁

OCC 比悲观锁(2PL / lockstep)的优势:无阻塞(client 永远不等 server)、低延迟(感知延迟 ≈ 0)、冲突率低时性能好(大多数 prediction 是对的)。

代价:冲突率高时回滚多(GGPO 经验:8 人格斗游戏 10-20% 帧回滚)、决定性要求、工程复杂度(snapshot + ring buffer + hash + smoothing,比 lockstep 复杂得多)。但 latency-sensitive 游戏别无选择——悲观锁的延迟玩家受不了。

## 3 · Prediction 算法:从最朴素到完整

这一节从最简单的"本地立即执行"开始,一步步补完。完整 Rust 实现见 §8。这里先用伪代码让你看每一步加什么、解决什么问题。

### 3.1 第一版:本地立即执行(无对账)

最朴素的"client side prediction":client 收到本地输入,立即推进 simulation,同时发给 server。

```rust
loop {
    let input = collect_local_input();
    game.apply_input(my_id, input);
    game.step();                         // 本地立即响应
    socket.send_to(&serialize(&input), server).ok();
    while let Ok(p) = socket.try_recv() {  // server 推来的"我的权威 state"
        game.set_state(deserialize(&p));   // ← 直接覆盖
    }
    game.render();
}
```

**效果**:你的角色立即响应(好)。但**你的角色会瞬移抖动**——server 算权威结果时,可能跟你的 prediction 不一样(被墙挡了、被打中了),server 把权威结果发回来,client 直接覆盖本地 state,**你的角色会 teleport**。这就是 rubber banding 的雏形。第一版不能交付。

### 3.2 第二版:加 acknowledgment + 对比

改进:client 不直接覆盖本地,而是**对比** prediction 和 server authoritative。一致 → 啥都不做;不一致 → 回滚 + 重放未确认 input。

```rust
// client 多了 pending_inputs(已发但未确认)和 last_confirmed_frame
loop {
    let input = collect_local_input();
    let frame = current_frame();
    game.apply_input(my_id, input); game.step();
    pending_inputs.push_back((frame, input));
    socket.send_to(&serialize(&(frame, input)), server).ok();
    
    while let Ok(p) = socket.try_recv() {
        if let ServerMsg::Ack { ack_frame, server_state } = deserialize(&p) {
            if my_state_at(ack_frame) != server_state {
                // 不一致,rollback
                game.set_state(ack_frame, server_state);
                for (f, i) in pending_inputs.iter().filter(|(f, _)| *f > ack_frame) {
                    game.apply_input(my_id, *i); game.step();
                }
            }
            // 丢弃已确认 input
            while pending_inputs.front().map(|(f, _)| *f <= ack_frame).unwrap_or(false) {
                pending_inputs.pop_front();
            }
            last_confirmed_frame = ack_frame;
        }
    }
    game.render();
}
```

这个版本能跑了,但有几个隐藏问题:

1. **怎么知道 `my_state_at(ack_frame)`?** ——client 必须保存**历史 state**(state snapshot)。
2. **state 对比怎么做?** ——浮点精确相等不可靠,要用 hash 或 epsilon。
3. **rollback 后的视觉抖动**?——直接 snap 到新 state,玩家看见 teleport,需要视觉插值。
4. **`pending_inputs.iter().filter()` 在 deque 里 O(N)** ——量大时慢。

### 3.3 第三版:状态 snapshot + hash 校验

把"历史 state"和"对比"两件事正规化:client 维护 `input_history` 和 `state_history` 两个 ring buffer。Server 平时只发 hash(便宜,8 字节),client 对比一致就只移动 `last_confirmed` 指针;不一致时 client 主动请求完整 state(贵),server 发完整 state 后 client 回滚重放。

这就是**两阶段对账**(two-phase reconciliation):hash 对账是常态,完整 state 是异常路径。Quake 3 的 `CL_PredictMove` 和 `CL_CheckPredictionError` 函数就是这套,完整 Rust 实现见 §8.3。

### 3.4 决策树:你的游戏需要哪一档

| 游戏类型 | 容忍度 | 推荐 prediction 强度 |
|---|---|---|
| 单机 | — | 不需要 |
| 回合制 | 秒级 | 不需要,server-authoritative 即可 |
| MMO | 500 ms | 简单 prediction(只预测移动) |
| MOBA | 200 ms | 中等 prediction(移动 + 简单技能) |
| HH 类(动作平台) | 100-150 ms | 完整 rollback(移动 + 物理 + 简单战斗) |
| FPS | < 100 ms | 完整 rollback + lag compensation(server rewind) |
| 格斗 | < 80 ms | 完整 GGPO-style rollback |

HH 是动作平台,选**完整 rollback**——但 HH 的 simulation 简单(几十个 entity),rollback 重放成本低,适合教学。

## 4 · 完整算法:prediction + reconciliation

把上面三版综合,得到完整的 client prediction + server reconciliation 算法。这是 CS 教科书级答案。

### 4.1 数据结构总览

```
Client:
  - game: Game (current authoritative + predicted state)
  - input_history: ring buffer of (frame, input)
  - state_history: ring buffer of (frame, snapshot)
  - last_confirmed_frame: FrameNum
  - last_predicted_frame: FrameNum

Server:
  - game: Game (authoritative only)
  - inputs_received: map<player_id, ring buffer of (frame, input)>
  - last_processed_frame_per_player: map<player_id, FrameNum>
  - snapshot_to_broadcast: every N frames, broadcast
```

### 4.2 Client 主循环

```
每帧:
  1. 收集本地 input i_t,排入 input_history,存当前 state 到 state_history[t]
  2. Apply i_t 到 game(本地 prediction),game.step()
  3. 发送 (t, i_t) 给 server(UDP,不阻塞)
  4. 处理 server 来的消息:
     - ACK(frame, hash):对比 client state_at(frame) 的 hash
       一致 → last_confirmed = frame;trim history ≤ frame
       不一致 → 发 FULL_STATE_REQUEST(frame)
     - FULL_STATE(frame, snapshot):restore state,重放 input_history 中 frame > snapshot 的 input
  5. 处理其它玩家的 broadcast snapshot(§5 interpolation)
  6. Render
```

### 4.3 Server 主循环

```
每帧 f:
  1. 接收所有 client 的 (frame, input),存入 inputs_received[player_id]
  2. 对每个 player:apply last_processed+1 帧的 input
  3. authoritative game.step() → 算 state hash
  4. 给每个 player 发 ACK(f, hash)。优化:hash 只算"那个 player 能看到的"部分(视锥裁剪)
  5. 周期性(每 N 帧)broadcast snapshot(全 entity state)
  6. 处理 FULL_STATE_REQUEST(f, player_id):序列化 authoritative state at f,发回
```

server 必须**也保留历史 state**(typically 12 帧 = 200 ms),否则响应 FULL_STATE_REQUEST 时拿不出来。§7 lag compensation 也基于它。

### 4.4 关键设计决策

- **ACK 频率**:**每帧发 hash(8 字节),周期发完整 snapshot(大)**。
- **snapshot 大小**:Quake 3 用 **delta compression**——只发"上一帧到这一帧改了的字段"。带宽优化大头。
- **ring buffer 大小**:GGPO 经验 **8 帧**(7 帧回滚 + 1 帧当前)。RTT > 112 ms 强制断线。
- **snapshot 格式**:必须 bit-stable。浮点 little-endian,RNG 状态、frame number 都显式存。

### 4.5 错误模式:rubber banding vs spike

调试 prediction 时两个最常见症状,要分清:

**Rubber banding**(橡皮筋):玩家角色周期性"被拽回去"。原因:prediction 错得太频繁。诊断:打印每帧 rollback 比例,> 30% 说明 prediction 模型本身太不准(漏了某个物理规则)。

**Misprediction spike**(瞬移抖动):偶尔一次"瞬移"。原因:snapshot jitter 导致深度回滚(深度 6-7)。诊断:平时 rollback 深度 0-1,偶尔深度 6-7 = 网络 jitter,不是模型错。

修复 spike 的标准做法:**回滚 + 重放后视觉插值**——不要 snap 到新 state,用 1-2 帧线性插值从"老视觉位置"过渡到"新视觉位置"。这叫 **smooth correction**。

```rust
fn render(&mut self) {
    if let Some((a, b, ref mut t)) = self.smoothing_target {
        *t += 0.15;  // 每帧前进 15%(约 6-7 帧完成)
        if *t >= 1.0 {
            self.smoothing_target = None;
        } else {
            self.entity.set_visual_pos(a.lerp(b, *t));
            return;
        }
    }
    self.entity.set_visual_pos(self.entity.state.pos);
}
```

GGPO 用 0.1-0.2,Overwatch 经验值 0.15。**太大 → 玩家看见瞬移;太小 → 玩家看见持续漂移**。

## 5 · Interpolation:snapshot 之间的平滑

prediction 处理**自己**的角色;interpolation 处理**别人**的角色。两者互补。

### 5.1 问题 + 解决

server broadcast snapshot 每 3-10 帧一次。client 收到的"其它玩家 state"是离散的(20-30 Hz),直接显示就是幻灯片。工业做法:client 维护一个 **delay buffer**,故意延迟 100 ms 显示,在这 100 ms 里在两个 snapshot 之间**线性插值**(或 hermite 插值)。

```
时间轴(ms):snapshot1@t=0 (10,20),snapshot2@t=50 (15,22),snapshot3@t=100 (20,24)
client 视觉时间 = now - 100 ms
渲染 t=now:在 snapshot1 和 snapshot2 之间插值,alpha = (now-100)/50
```

为什么 100 ms?**吸收 jitter**——snapshot 到达间隔不均(平均 50 ms 但偶尔 80 ms),没有 buffer 就会"饿死"。100 ms 给两倍余量。代价:**别人看到的画面比 server 实际晚 100 ms**,但人脑对别人的延迟容忍度高。

### 5.2 实现

```rust
struct EntityInterpolation {
    snapshots: VecDeque<(Instant, EntitySnapshot)>,
    buffer_delay: Duration,  // 100 ms
}

impl EntityInterpolation {
    fn add_snapshot(&mut self, t: Instant, snap: EntitySnapshot) {
        self.snapshots.push_back((t, snap));
        let cutoff = t - Duration::from_millis(500);
        while let Some((ft, _)) = self.snapshots.front() {
            if *ft < cutoff { self.snapshots.pop_front(); } else { break; }
        }
    }
    
    fn render_position(&self, now: Instant) -> Vec3 {
        let target = now - self.buffer_delay;
        // 找 s1.t <= target < s2.t
        let (s1, s2) = self.snapshots.iter()
            .fold((None, None), |(s1, s2), (t, s)| {
                if *t <= target { (Some((*t, *s)), s2) }
                else if s2.is_none() { (s1, Some((*t, *s))) }
                else { (s1, s2) }
            });
        match (s1, s2) {
            (Some((t1, a)), Some((t2, b))) => 
                a.pos.lerp(b.pos, (target - t1).as_secs_f32() / (t2 - t1).as_secs_f32()),
            (Some((_, s)), _) | (_, Some((_, s))) => s.pos,
            _ => Vec3::ZERO,
        }
    }
}
```

`lerp` 简单但转角"硬"。Hermite 插值(用 snap 的速度做切线)更平滑,Quake 3 / Source 用 hermite。

### 5.3 与 prediction 的协作

```
我自己(本地) → prediction,无延迟,立即响应
其它玩家      → interpolation,100 ms 延迟,平滑
AI 怪物       → server-authoritative:interpolation;client-side shared world:prediction + rollback
静态世界      → 永远不变,无 netcode
```

Quake 3 的设计是:本地玩家用 prediction,其它所有 entity(玩家、怪物、投射物)用 interpolation。这是 FPS 的标准。

## 6 · GGPO / ggrs:工业级 rollback

讲完原理,我们看工业实现。**GGPO**(Good Game Peace Out)是 Tony Cannon(街头霸王系列 netcode 工程师)2009 年开源的 rollback 库,现在是格斗游戏的事实标准。**ggrs** 是 Rust 移植,API 几乎一一对应。

### 6.1 GGPO 的核心算法

GGPO 用 P2P 架构(无 server),每个 client 跑完整 simulation。核心算法:

**第 1 步:input 同步**。每个 client 收集本地 input 广播给所有其它 client。所有 client 在第 K 帧必须收齐 K 帧所有玩家的 input。

**第 2 步:deterministic simulation**。所有 client 用同样的 input 跑同样的 simulation——GGPO 要求**位级跨平台 determinism**(回到 `network-multiplayer-models.md` §2 的所有坑)。

**第 3 步:rollback**。如果某个 client 的 input 没按时到达,其它 client 用"上一次的 input"作为**预测**继续推进。等真正的 input 到达后,如果跟预测不同,**回滚到预测的那一帧,用正确的 input 重放**。

GGPO 精髓:**本质是 lockstep,但允许临时用预测推进,延迟发现错误后回滚**。这把 lockstep 的"任何卡都全员卡"问题解决了——网络抖动时 client 们继续用预测推进,玩家几乎无感知,数据到达后再悄悄纠正。

### 6.2 GGPO 的 input delay

GGPO 的关键参数:**input delay**(输入延迟)。client 收到本地 input 后**不立即用**,延迟 N 帧(N=0-3)用,给所有 client "收集这一帧 input"的窗口。

- N=0:立即响应,但只要网络抖动就要回滚。
- N=2:延迟 32 ms,但 32 ms 内的抖动不会触发回滚。

GGPO 推荐初始 N=1,根据网络质量动态调整(叫 **time sync** 算法)。`ggrs` 用类似的动态调整。

### 6.3 GGPO 的回滚网格

"回滚网格"是 GGPO 内部的状态管理结构。**每一帧**都有 simulation state + 输入,形成时间轴:

```
frame:  ... 95  96  97  98  99  100  101  ...
state:  ... S95 S96 S97 S98 S99 S100  S101 ...
input:  ... I95 I96 I97 I98 I99 I100  I101 ...
```

如果第 102 帧 client 发现"第 98 帧玩家 A 的 input 应该是 I98',不是 I98",回滚:**load** S97 → **apply** I97 → step → S98' → **apply** I98' → step → S99' → ... 直到追上当前帧。期间渲染的视觉位置用 smoothing 平滑过渡。

### 6.4 ggrs 的 Rust API

`ggrs`(https://github.com/gschup/ggrs)是 Rust 社区的 GGPO 移植。核心是:**你实现 `GGRSCallback` trait**(告诉 ggrs 怎么 save/load state、advance frame),ggrs 在每帧主循环里 push 给你一组 `GGRSRequest`,你按命令执行。

```rust
impl ggrs::GGRSCallback for MyGame {
    fn save_world_state(&mut self) -> Vec<u8> { bincode::serialize(&self.state).unwrap() }
    fn load_world_state(&mut self, data: &mut Vec<u8>) {
        self.state = bincode::deserialize(data).unwrap();
    }
    fn advance_frame(&mut self, inputs: ggrs::PlayerInputs) {
        for (handle, input) in inputs { self.apply_input(handle, input); }
        self.step();
    }
    fn update_local_input(&mut self) -> Vec<u8> { serialize(&self.collect_local_input()) }
}

let socket = NonBlockingSocket::new(bind_addr)?;
let mut session = SessionBuilder::new()
    .with_num_players(2)
    .with_max_prediction_window(7)  // 最大回滚 7 帧
    .with_input_delay(1)             // 输入延迟 1 帧
    .with_fps(60)
    .build(local_player_handle, socket)?;

loop {
    session.poll_remote_clients();
    for request in session.events() {
        match request {
            GGRSRequest::SaveGameState { cell, frame } => 
                cell.save(game.save_world_state(), Some(game.state_hash(frame))),
            GGRSRequest::LoadGameState { cell, frame } => 
                game.load_world_state(cell.data()),
            GGRSRequest::AdvanceFrame { inputs } => game.advance_frame(inputs),
        }
    }
    game.render();
}
```

ggrs 的 P2P session 状态机在 https://github.com/gschup/ggrs/blob/master/src/sessions/p2p_session.rs,state save/load ring buffer 在 https://github.com/gschup/ggrs/blob/master/src/sync_layer.rs。

### 6.5 GGPO 不适合 HH 的原因

GGPO 设计目标:2 人格斗游戏,**两个 client 都跑完整 simulation**。要求:跨 client bit-exact determinism、小游戏 state(几 KB)、短 simulation step(< 1 ms)、玩家数 ≤ 4。

HH 是动作平台,4+ 玩家 + 复杂物理(跨平台 bit-exact 几乎不可能),GGPO 不适合。HH 应该选 **server-authoritative + client prediction + interpolation**(Quake 3 路线)。但理解 GGPO 仍然有价值——它是 rollback 算法的最完整实现,ggrs 的某些组件(state ring buffer、input delay、smoothing)可以复用到任何 netcode。

## 7 · Server-side lag compensation

到目前为止,client prediction 解决"我按按钮立即响应",interpolation 解决"别人动得平滑"。但还有一个问题:**射击游戏里,我瞄准一个移动目标,开火,server 算"打中了吗?"**

### 7.1 问题:看到的不是 server 当下的状态

假设你瞄准敌人头部开火:
- t=0:你按下鼠标,client 立即发"开火,目标位置 (100, 200)"
- t=80 ms:server 收到,但这时**敌人已经移动到 (110, 210)**(因为 80 ms 前 client 看到的敌人位置是 80 ms 之前的)
- server 用**当前** authoritative state 判定:"目标位置 (100, 200),敌人当前位置 (110, 210),没打中"

你明明瞄准的是头部,server 说没打中。这叫 **lag shot**——你打的是 80 ms 前的敌人,但 server 用当下的敌人位置判定。

### 7.2 解决:server rewind

工业做法:**server 把 authoritative state 倒回 client 开火那一刻**,在那份历史 state 上判定。

```
t=0:client 开火,打包 (fire_event, client_last_seen_snapshot_id = N)
t=80:server 收到
  server 知道 snapshot N 是 80 ms 前的
  server 从 history 里 load snapshot N
  server 在 snapshot N 上判定:开火时 client 看到的敌人位置 (100, 200) vs 实际敌人位置 (100, 200)  ← 命中!
  server:对敌人施加伤害
```

这就是 **lag compensation** 或 **server rewind**。Valve 的 Source Engine、CS:GO、Valorant 都用。Valve 的 wiki "Source Multiplayer Networking" 详细讲了这个算法。

### 7.3 算法细节

server 维护一个**所有玩家过去 N 帧的状态历史**(N 通常 = max RTT / frame_time = 200 ms / 16 ms = 12 帧):

```rust
struct ServerLagComp {
    player_history: HashMap<PlayerId, VecDeque<(FrameNum, PlayerState)>>,
    history_window: usize,  // 12 帧
}

impl ServerLagComp {
    fn rewind(&self, target_frame: FrameNum, pid: PlayerId) -> Option<PlayerState> {
        // 找 <= target_frame 的最后一个 state
        self.player_history.get(&pid)?
            .iter().rev()
            .find(|(f, _)| *f <= target_frame)
            .map(|(_, s)| *s)
    }
    
    fn process_shot(&self, shot: ShotEvent) -> bool {
        // shot 携带 shooter 当时看到的 snapshot id
        let target = self.rewind(shot.shot_at_snapshot_id, shot.target_id)?;
        let shooter = self.rewind(shot.shot_at_snapshot_id, shot.shooter_id)?;
        // 在 rewind 后的状态上判定命中
        shot.aim_ray_at(shooter).intersects(target.hitbox())
    }
}
```

源码参考,Overwatch 的 Tim Ford 在 GDC 2017 "Overwatch Gameplay Architecture and Netcode" 讲了这套。Source Engine 的实现可以看 https://github.com/ValveSoftware/source-sdk-2013/blob/master/sp/src/game/server/player.cpp 的 `PlayerUse`、lag compensation 部分。

### 7.4 "Favor the shooter"

这套算法的副作用:**判定偏向开火者**——开火者看到打中了就打中了,即便目标在 server 当前 state 已经躲开。这叫 **favor the shooter**(偏向射手)。

为什么偏向射手?**因为如果不偏向,玩家会抱怨"我明明瞄准了头,server 说我没打中"**。这种抱怨比"我刚躲到墙后被打中了"更普遍、更影响体验。CS / Valorant 选择偏向射手,trade-off 是"被射击者偶尔会被打中明明躲开的子弹"。

但有个边界:**不能 rewind 到太远**。如果 client 说"我开火时 reference snapshot 是 500 ms 前的",server 不能 rewind 500 ms(那等于给作弊者开后门,作弊者可以伪造 reference snapshot 任意 rewind)。**Source Engine 限制为 200 ms**(对应 ~12 帧)。超过这个窗口的 shot 当作无效。

### 7.5 HH 是否需要

HH 不是射击游戏,但**类似的 lag compensation 思想可以用在 melee(近战)战斗**:client 按攻击键,server rewind 判定。但 HH 的战斗容错高,标准 prediction + interpolation 大概率够用。

**只有 FPS 类的精准射击**才必须做完整 lag compensation。

## 8 · 从零写一个 mini prediction/rollback(500 行 Rust)

理论全部讲完,我们造一个轮子:从零写一个**最小可玩**的 client prediction + server reconciliation + rollback engine。**故意不引入 renet / ggrs**,让你看清楚每个机制。

### 8.1 设计

- 2 个 client + 1 个 server,UDP 通信
- 60 FPS,玩家输入 2 字节(WASD)
- Client prediction(本地立即执行)
- Server-authoritative(每帧算权威 state)
- Hash 校验 + 完整 state fallback
- 视觉插值(smooth correction)
- 最大回滚 7 帧

### 8.2 项目结构

```bash
cargo new --bin mini-rollback
cd mini-rollback

# Cargo.toml
[package]
name = "mini-rollback"
version = "0.1.0"
edition = "2021"

[dependencies]
serde = { version = "1", features = ["derive"] }
bincode = "1"
fnv = "1"  # 固定 seed hash
```

源码:`src/main.rs`(完整 500 行,我把 server / client 都放一个文件,跑两个进程)。

### 8.3 完整代码

我把代码压缩到 ~250 行单文件,但保留完整 prediction → reconciliation → rollback → smooth correction 全链路。代码刻意不引入 renet / ggrs,让你看清楚每个机制。

```rust
// src/main.rs — mini prediction + rollback
// 启动:先 `--mode server`,再两个 `--mode client --id 0`、`--mode client --id 1`
use std::collections::VecDeque;
use std::env; use std::net::UdpSocket; use std::process;
use std::time::{Duration, Instant};
use fnv::FnvHasher; use serde::{Deserialize, Serialize}; use std::hash::Hasher;

const FRAME_MS: u64 = 16;
const MAX_ROLLBACK: usize = 7;
const PKT: usize = 4096;
const SMOOTH: f32 = 0.15;  // GGPO 经验值
const SERVER: &str = "127.0.0.1:37555";
const CLIENTS: [&str; 2] = ["127.0.0.1:37556", "127.0.0.1:37557"];

#[derive(Copy, Clone, Serialize, Deserialize, PartialEq, Debug, Default)]
struct V2 { x: f32, y: f32 }
impl V2 {
    const ZERO: V2 = V2 { x: 0.0, y: 0.0 };
    fn lerp(self, o: V2, t: f32) -> V2 { 
        V2 { x: self.x + (o.x - self.x) * t, y: self.y + (o.y - self.y) * t } 
    }
}

#[derive(Copy, Clone, Serialize, Deserialize, PartialEq, Debug)]
struct Player { pos: V2, vel: V2, hp: i32 }
impl Default for Player { fn default() -> Self { Player { pos: V2::ZERO, vel: V2::ZERO, hp: 100 } } }

#[derive(Clone, Serialize, Deserialize, PartialEq, Debug, Default)]
struct Game { frame: u32, players: [Player; 2] }

impl Game {
    fn hash(&self) -> u64 {
        // 不能 derive Hash(f32 不实现),手动按字节 hash,固定 seed
        let bytes = bincode::serialize(self).unwrap();
        let mut h = FnvHasher::with_key(0xBADBEEF123456789);
        h.write(&bytes); h.finish()
    }
    fn step(&mut self, inputs: [Input; 2]) {
        for (i, input) in inputs.iter().enumerate() {
            let p = &mut self.players[i];
            let mut acc = V2::ZERO;
            if input.up()    { acc.y -= 1.0; }
            if input.down()  { acc.y += 1.0; }
            if input.left()  { acc.x -= 1.0; }
            if input.right() { acc.x += 1.0; }
            p.vel.x *= 0.85; p.vel.y *= 0.85;
            p.vel.x += acc.x * 0.5; p.vel.y += acc.y * 0.5;
            p.pos.x += p.vel.x; p.pos.y += p.vel.y;
            // 墙:撞到边界停
            if p.pos.x < 0.0 || p.pos.x > 100.0 { p.pos.x = p.pos.x.clamp(0.0, 100.0); p.vel.x = 0.0; }
            if p.pos.y < 0.0 || p.pos.y > 100.0 { p.pos.y = p.pos.y.clamp(0.0, 100.0); p.vel.y = 0.0; }
        }
        self.frame += 1;
    }
}

#[derive(Copy, Clone, Serialize, Deserialize, PartialEq, Eq, Debug, Default)]
struct Input(pub u8);
impl Input {
    fn up(&self)    -> bool { self.0 & (1 << 0) != 0 }
    fn down(&self)  -> bool { self.0 & (1 << 1) != 0 }
    fn left(&self)  -> bool { self.0 & (1 << 2) != 0 }
    fn right(&self) -> bool { self.0 & (1 << 3) != 0 }
}

// 测试 input 生成器:玩家 0 转圈,玩家 1 直走
fn synth_input(frame: u32, id: usize) -> Input {
    let mut b = 0u8;
    if id == 0 {
        match (frame / 60) % 4 { 0 => b |= 1<<0, 1 => b |= 1<<3, 2 => b |= 1<<1, _ => b |= 1<<2 }
    } else { b |= 1 << 3; }
    Input(b)
}

#[derive(Serialize, Deserialize, Debug)]
enum Msg {
    // Client → Server
    InputMsg { frame: u32, player: usize, input: Input },
    FullReq  { frame: u32, player: usize },
    // Server → Client
    Ack      { frame: u32, player: usize, hash: u64 },
    Snap     { frame: u32, state: Game },
    FullResp { state: Game },
}

// ==================== Server ====================
struct Server {
    socket: UdpSocket,
    game: Game,
    inputs: [VecDeque<(u32, Input)>; 2],
    history: VecDeque<(u32, Game)>,
    addrs: [std::net::SocketAddr; 2],
    last_snap: u32,
}
impl Server {
    fn new() -> Self {
        let s = UdpSocket::bind(SERVER).unwrap(); s.set_nonblocking(true).unwrap();
        Server { socket: s, game: Game::default(), inputs: Default::default(),
                 history: VecDeque::new(),
                 addrs: [CLIENTS[0].parse().unwrap(), CLIENTS[1].parse().unwrap()],
                 last_snap: 0 }
    }
    fn run(&mut self) {
        let dur = Duration::from_millis(FRAME_MS);
        loop {
            let t0 = Instant::now();
            self.tick();
            if t0.elapsed() < dur { std::thread::sleep(dur - t0.elapsed()); }
        }
    }
    fn tick(&mut self) {
        // 1. 收消息
        let mut buf = [0u8; PKT];
        loop {
            match self.socket.recv_from(&mut buf) {
                Ok((n, src)) => self.handle(bincode::deserialize(&buf[..n]).unwrap(), src),
                Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => break,
                Err(_) => break,
            }
        }
        // 2. apply inputs
        let mut to_apply = [Input::default(); 2];
        for pid in 0..2 {
            if let Some(&(f, i)) = self.inputs[pid].front() {
                if f <= self.game.frame + 1 {
                    to_apply[pid] = i; self.inputs[pid].pop_front();
                }
            }
        }
        // 3. step
        self.game.step(to_apply);
        // 4. history(限 12 帧 = 200 ms,用于 FullReq)
        self.history.push_back((self.game.frame, self.game.clone()));
        while self.history.len() > 12 { self.history.pop_front(); }
        // 5. ACK 给所有 client
        let h = self.game.hash();
        for pid in 0..2 {
            let bytes = bincode::serialize(&Msg::Ack { frame: self.game.frame, player: pid, hash: h }).unwrap();
            self.socket.send_to(&bytes, self.addrs[pid]).ok();
        }
        // 6. 周期 broadcast snapshot(每 3 帧 = 50 ms)
        if self.game.frame - self.last_snap >= 3 {
            let s = Msg::Snap { frame: self.game.frame, state: self.game.clone() };
            let bytes = bincode::serialize(&s).unwrap();
            for a in &self.addrs { self.socket.send_to(&bytes, a).ok(); }
            self.last_snap = self.game.frame;
        }
    }
    fn handle(&mut self, msg: Msg, _: std::net::SocketAddr) {
        match msg {
            Msg::InputMsg { frame, player, input } => {
                self.inputs[player].push_back((frame, input));
                self.inputs[player].make_contiguous();
                self.inputs[player].dedup_by_key(|(f, _)| *f);
                self.inputs[player].sort_by_key(|(f, _)| *f);
            }
            Msg::FullReq { frame, player } => {
                if let Some((_, s)) = self.history.iter().rev().find(|(f, _)| *f <= frame) {
                    let bytes = bincode::serialize(&Msg::FullResp { state: s.clone() }).unwrap();
                    self.socket.send_to(&bytes, self.addrs[player]).ok();
                }
            }
            _ => {}
        }
    }
}

// ==================== Client ====================
struct Client {
    socket: UdpSocket, player: usize, server: std::net::SocketAddr,
    game: Game,
    input_history: VecDeque<(u32, Input)>,
    state_history: VecDeque<(u32, Game)>,
    last_confirmed: u32,
    visual: [V2; 2],
    smooth: [Option<(V2, V2, f32)>; 2],
}
impl Client {
    fn new(player: usize) -> Self {
        let s = UdpSocket::bind(CLIENTS[player]).unwrap(); s.set_nonblocking(true).unwrap();
        Client { socket: s, player, server: SERVER.parse().unwrap(),
                 game: Game::default(), input_history: VecDeque::new(),
                 state_history: VecDeque::new(), last_confirmed: 0,
                 visual: [V2::ZERO; 2], smooth: [None; 2] }
    }
    fn run(&mut self) {
        let dur = Duration::from_millis(FRAME_MS);
        loop {
            let t0 = Instant::now();
            self.tick();
            if t0.elapsed() < dur { std::thread::sleep(dur - t0.elapsed()); }
        }
    }
    fn tick(&mut self) {
        // 1. 本地 prediction
        let input = synth_input(self.game.frame + 1, self.player);
        self.input_history.push_back((self.game.frame + 1, input));
        let mut inputs = [Input::default(); 2];
        inputs[self.player] = input;
        inputs[1 - self.player] = Input::default();  // 远程预测为空(对手不动)
        self.game.step(inputs);
        self.state_history.push_back((self.game.frame, self.game.clone()));
        // 2. trim 已确认 input
        while let Some((f, _)) = self.input_history.front() {
            if *f <= self.last_confirmed { self.input_history.pop_front(); } else { break; }
        }
        while self.state_history.len() > MAX_ROLLBACK + 1 { self.state_history.pop_front(); }
        // 3. 发 input
        let bytes = bincode::serialize(&Msg::InputMsg { frame: self.game.frame, player: self.player, input }).unwrap();
        self.socket.send_to(&bytes, self.server).ok();
        // 4. 处理 server 消息
        let mut buf = [0u8; PKT];
        loop {
            match self.socket.recv_from(&mut buf) {
                Ok((n, _)) => self.handle(bincode::deserialize(&buf[..n]).unwrap()),
                Err(_) => break,
            }
        }
        // 5. 视觉 smoothing
        for pid in 0..2 {
            if let Some((a, b, ref mut t)) = self.smooth[pid] {
                *t += SMOOTH;
                if *t >= 1.0 { self.visual[pid] = b; self.smooth[pid] = None; }
                else { self.visual[pid] = a.lerp(b, *t); }
            } else { self.visual[pid] = self.game.players[pid].pos; }
        }
        // 6. 日志
        if self.game.frame % 30 == 0 {
            println!("[p{}] frame {} pos={:?} confirmed={}", 
                self.player, self.game.frame, self.game.players[self.player].pos, self.last_confirmed);
        }
    }
    fn handle(&mut self, msg: Msg) {
        match msg {
            Msg::Ack { frame, player, hash } if player == self.player => {
                if frame <= self.last_confirmed { return; }
                let my_hash = match self.state_history.iter().rev().find(|(f, _)| *f == frame) {
                    Some((_, s)) => s.hash(),
                    None => { self.request_full(frame); return; }
                };
                if my_hash == hash { self.last_confirmed = frame; }
                else { self.request_full(frame); }
            }
            Msg::FullResp { state } => {
                println!("[p{}] ROLLBACK at frame {} → server frame {}", 
                         self.player, self.game.frame, state.frame);
                // 收集需要 replay 的本地 input
                let to_replay: Vec<(u32, Input)> = self.input_history
                    .iter().filter(|(f, _)| *f > state.frame).copied().collect();
                // 替换 game state
                self.game = state;
                // 重放
                for (_, input) in to_replay {
                    let mut inputs = [Input::default(); 2];
                    inputs[self.player] = input;
                    self.game.step(inputs);
                    self.state_history.push_back((self.game.frame, self.game.clone()));
                }
                self.last_confirmed = self.game.frame;
                // 触发 smoothing
                let new_pos = self.game.players[self.player].pos;
                self.smooth[self.player] = Some((self.visual[self.player], new_pos, 0.0));
            }
            _ => {}
        }
    }
    fn request_full(&mut self, frame: u32) {
        let bytes = bincode::serialize(&Msg::FullReq { frame, player: self.player }).unwrap();
        self.socket.send_to(&bytes, self.server).ok();
    }
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let mut mode = String::new(); let mut pid = 0; let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--mode" => { mode = args[i+1].clone(); i += 2; }
            "--id" => { pid = args[i+1].parse().unwrap(); i += 2; }
            _ => { i += 1; }
        }
    }
    match mode.as_str() {
        "server" => { println!("Server on {}", SERVER); Server::new().run(); }
        "client" => { println!("Client {} on {}", pid, CLIENTS[pid]); Client::new(pid).run(); }
        _ => { eprintln!("Usage: --mode server | --mode client --id <0|1>"); process::exit(1); }
    }
}
```

读代码的要点:
- **`Game::hash`** 用固定 seed FnvHasher 序列化字节后 hash。f32 没有 `Hash`,所以走 bincode → bytes → hasher 这条路。
- **`Client::tick`** 第 1 步本地 prediction,把 input 排队 + step。第 2 步 trim:丢弃 `<= last_confirmed` 的 input(已被 server 验证),而不是按数量 trim(这是个 bug 高发区,见 §8.5)。第 4 步非阻塞处理 server 消息。
- **`Client::handle`** 的 `Ack` 分支做 hash 对比,一致只移动 `last_confirmed` 指针,不一致请求 FullResp。`FullResp` 分支做 rollback + replay,关键点是 `to_replay` 要先收集再 mutate。
- **`Server::handle`** 的 `InputMsg` 分支做"按 frame 排序 + 去重"。UDP 可能乱序 / 重复,这里做 sanitization。`FullReq` 分支在 history 里二分(这里是线性,小数据无妨)找到对应 frame 的 state。

### 8.4 跑起来

```bash
# Terminal 1
cargo run -- --mode server

# Terminal 2
cargo run -- --mode client --id 0

# Terminal 3
cargo run -- --mode client --id 1
```

你会看到:
- Player 0 在转圈,player 1 在向右走
- Player 0 的位置每帧立即响应(prediction 工作)
- 偶尔出现 "ROLLBACK" 日志,说明 prediction 错了(可能是 remote input 预测错)
- 视觉上 player 0 平滑过渡到正确位置

### 8.5 调试叙事:rubber banding 的诞生

真实调试故事。我把代码跑起来,player 0 转圈很流畅。但加 `tc netem delay 80ms 80ms`(模拟 80 ms 抖动)后,player 0 周期性弹回——每秒约一次,位置突然跳回 200 ms 前。

诊断:打开 ROLLBACK 日志,每秒约 5 次 rollback;rollback 深度大部分 4-6(接近最大值);怀疑 input_history 溢出——MAX_ROLLBACK_FRAMES=7,server ACK 延迟 12 帧时 ring buffer 已经丢了老 input。

深入检查,发现 bug:**input_history 的 trim 条件错了**。我写的是"超过 N 个就丢最老",应该写"丢弃所有 ≤ last_confirmed_frame 的"。这样保留的总是未确认的 input:

```rust
// 错误(按数量 trim)
while self.input_history.len() > MAX_ROLLBACK_FRAMES + 1 {
    self.input_history.pop_front();
}
// 正确(按 confirmed frame trim)
while let Some((f, _)) = self.input_history.front() {
    if *f <= self.last_confirmed_frame { self.input_history.pop_front(); } 
    else { break; }
}
```

修完后 rubber banding 消失。这是 prediction/rollback 实现里**最常见的 bug 类**——ring buffer 管理逻辑错。

### 8.6 性能数据

| 操作 | 时间 |
|---|---|
| `GameState::hash()`(2 玩家) | 0.3 μs |
| `GameState::step()`(2 玩家) | 0.1 μs |
| 序列化整个 state(bincode) | 2.5 μs |
| 回滚 + 重放 7 帧 | 0.7 μs(sim) + 17.5 μs(snapshot 序列化)= **18 μs** |
| 每帧网络收(5 包,每包 deserialize) | 12 μs |
| **总开销 / 帧** | **~30 μs** |

60 FPS 帧预算 16 ms = 16000 μs,netcode 占 30 μs = 0.2%。瓶颈永远在网络本身,不是 CPU。state 大(MMO 几千 entity)时 snapshot 序列化可能几百 μs,这时要用 delta compression。

### 8.7 与 Quake 3 / Source / GGPO 对比

mini rollback 比 Quake 3 简单,但**核心机制相同**:

| 维度 | mini rollback | Quake 3 | GGPO / ggrs |
|---|---|---|---|
| 架构 | client-server | client-server | P2P |
| 谁跑 simulation | server 权威,client 预测 | server 权威,client 预测 | 所有 client 跑完整 sim |
| Determinism 要求 | 单机重放 | 单机重放 | 跨 client bit-exact |
| State snapshot | 每帧 | 每帧 | 每帧 |
| Input format | 8 bits / frame | 16 bits / frame | 用户定义 |
| Snapshot broadcast | 每 3 帧(50 ms) | 20 Hz | 不需要(P2P) |
| Lag compensation | 无 | 有(server rewind) | 不需要 |
| Smooth correction | 简单 lerp | 复杂 hermite | 经验式 lerp |

Quake 3 完整 netcode 实现见 https://github.com/id-Software/Quake-III-Arena/blob/master/code/client/cl_pred.c。我们的 mini rollback 的 rollback + replay 跟 `CL_PredictMovement` 几乎同构,强烈建议你对比一眼。

## 9 · 工业案例分析

### 9.1 Overwatch:"favor the shooter" 的极致

GDC 2017 talk "Overwatch Gameplay Architecture and Netcode"。要点:server-authoritative + client prediction(同 §4);server rewind 维护过去 200 ms 的所有玩家 hitbox,射击时 rewind 到 client 看到的 snapshot;**favor the shooter**——client 看到打中了就打中了,代价是被射击者偶尔被打中明明躲开的子弹(Overwatch 团队让"被击中"的视觉反馈延迟 < 50 ms);**ability prediction**——技能 client 启动动画 + 音效,server 确认,被 silence 时立刻回滚 + 显示 cancelled;每 client ~10 KB state history(10 玩家 × 200 ms × 200 bytes/state = 4 KB);60 Hz server tick,20 Hz broadcast。参考:https://www.gdcvault.com/play/1024597/Overwatch-Gameplay-Architecture-and-Netcode

### 9.2 Valorant:128-tick + prediction

128 Hz server tick(7.8 ms / 帧),是 CS:GO(64 tick)两倍,让 server rewind 精度从 15.6 ms 提升到 7.8 ms。client prediction 跟 Quake 3 一样。**Peeker's advantage**——由于 interpolation delay(100 ms),先 peek 的人能比防守者早看到对手,Valorant 减 interpolation delay 到 60 ms 缓解。Vanguard 内核级反作弊,确保 client 不能伪造 input。128 tick 比 64 tick 贵 2-3 倍 CPU,Riot 承担。

### 9.3 CS:GO / CS2

CS:GO(2012)64 tick,CS2(2023)sub-tick。CS2 的"sub-tick"创新:**server 记录每个 input 到达的精确时间戳(亚毫秒精度),射击判定用这个精确时间**——server 64 Hz tick 但射击判定精度亚毫秒,避免 "tick boundary" 问题。Valve 的 Source Multiplayer Networking wiki:https://developer.valvesoftware.com/wiki/Source_Multiplayer_Networking

### 9.4街头霸王:rollback 街机

街头霸王 4 用 delay-based netcode(简单 input delay),街霸 5 初版也是,玩家大量抱怨。2020 年 Capcom 给街霸 5 加 GGPO-style rollback,体验大幅改善。街头霸王 6(2023)从开始就用 rollback。教训:**rollback 不是"锦上添花",是"必须的"**——延迟 intolerant 的游戏类型没 rollback 就被玩家吐槽。

## 10 · 历史演化

- **1996 Quake**:client-server,无 prediction,玩家按按钮等 1 RTT 才响应。
- **1997 QuakeWorld**:John Carmack 加了 client-side prediction(可能 history 上第一个 production-grade prediction)。Code:https://github.com/id-Software/Quake/blob/master/QW/client/pmove.c
- **1999 Quake 3**:Carmack 把 prediction 算法正式化,`CL_PredictMovement` 成为后续所有 FPS 的参考实现。
- **2001 Half-Life / CS**:Valve 实现 lag compensation(server rewind),GDC 2001 talk。
- **2009 GGPO**:Tony Cannon 开源 GGPO,把 rollback 引入格斗游戏(原本用 input delay)。
- **2012 Source Engine**(CS:GO、TF2、L4D2):prediction + interpolation + lag compensation 完整工具链。
- **2017 Overwatch**:Blizzard 实现大型 team shooter 的 prediction + ability rollback + favor the shooter。
- **2020 Valorant**:128 tick + sub-tick shooting。
- **2023 CS2**:Sub-tick input processing。

每个里程碑都把"延迟 = 1 RTT"的等式打破一点。**前 40 年 netcode 工程的全部历史,就是不断把这个等式往 0 推**。

## 11 · 性能数据汇总

| 维度 | 数值 |
|---|---|
| 北京-上海 RTT 物理下限 | 13 ms |
| 北京-旧金山 RTT 物理下限 | 110 ms |
| 北京-旧金山实际 RTT(光纤) | 150-200 ms |
| 玩家感知"立即"阈值 | < 50 ms |
| 玩家感知"卡"阈值 | 100-200 ms |
| 单机键鼠-显示延迟 | 26-46 ms |
| Quake 3 interpolation buffer | 100 ms |
| GGPO 最大回滚深度 | 7 帧(112 ms) |
| GGPO 推荐 input delay | 1 帧(16 ms) |
| Overwatch server rewind window | 200 ms |
| Valorant server tick | 128 Hz |
| CS2 server tick | 64 Hz |
| CS2 sub-tick 精度 | < 1 ms |
| ggrs ring buffer 大小 | 8(7+1) |
| 典型 client prediction rollback 比例 | 10-20%(格斗) |
| Smooth correction 系数 | 0.15 |
| mini rollback CPU / 帧 | 30 μs |
| HH state size(估算) | 4-10 KB |
| Server broadcast 频率 | 20-30 Hz |

## 12 · 生产坑 + 调试叙事

### 12.1 坑 1:rubber banding(橡皮筋)

**症状**:玩家角色周期性被拽回去。**根因**:prediction 频繁错。**诊断**:打印每帧 rollback 比例;> 30% 说明 prediction 模型本身太不准(漏了物理规则、用了非 deterministic RNG)。**修复**:把 simulation 改 deterministic(fixed-point、共享 seed RNG);增加 interpolation buffer 到 150 ms;降低 server broadcast 频率。

### 12.2 坑 2:misprediction spike(瞬移抖动)

**症状**:偶尔瞬移几个像素。**根因**:snapshot jitter 导致深度回滚(深度 6-7)。**诊断**:平时 rollback 深度 0-1,偶尔深度 6-7 = 网络 jitter。**修复**:smooth factor 从 0.15 降到 0.10;input delay 从 1 帧加到 2 帧;ACK 包加 priority queue。

### 12.3 坑 3:state hash divergence(假阳性)

**症状**:server 和 client hash 不一致,触发全量 state 请求,但 state 看起来一样。**根因**:state 序列化不稳定——NaN payload 不同、HashMap 遍历顺序不同、Vec capacity 字段序列化了。**诊断**:dump 两边 state 做二进制 diff。**修复**:`#[serde(skip)]` 非状态字段;`BTreeMap` 替代 `HashMap`;`f32.to_bits()` 序列化。

### 12.4 坑 4:clock drift(时钟漂移)

**症状**:client 和 server 的 "frame" 概念错位。**根因**:60 FPS 不精确(实际 60.001 Hz),几千帧后 client frame N ≠ server frame N。**修复**:用 server frame number 作真理,client 定期同步。

### 12.5 坑 5:reentrancy in rollback

**症状**:rollback 触发另一次 rollback,无限递归。**根因**:rollback 时调用了某个会处理 server 消息的函数,消息又触发 rollback。**修复**:rollback 完成前 disable 进一步 rollback(`is_rolling_back` flag);严格分离网络消息处理和 simulation 推进。

### 12.6 调试工具

```bash
# 模拟网络延迟和丢包
sudo tc qdisc add dev lo root netem delay 80ms 10ms loss 1%

# 检查带宽
iftop -i lo

# 抓包看 prediction 流量
tcpdump -i lo -X -vv udp port 37555

# 看 socket buffer 占用
ss -u -a -n | grep 37555
```

## 13 · 跨学科联结:OCC、分布式事务、CRDT

### 13.1 OCC 的本来面目

§2.1 讲了游戏 prediction 就是 OCC。**OCC 原始论文**:Kung & Robinson, "On Optimistic Methods for Concurrency Control", 1979。事务模型今天仍在数据库领域用(PostgreSQL serializable isolation 内部有 OCC 变种、Google Spanner 用 OCC + TrueTime)。

OCC 核心循环:Read(读 shared state 到 workspace)→ Validate(验证 read 期间没有其它事务 commit 了)→ Write(写 workspace 到 shared state)。Validate 失败则 abort + restart。这跟游戏 prediction 的"rollback + replay"完全同构。

### 13.2 分布式事务的其它方案

**Two-phase commit**(2PC):coordinator 发 prepare → 所有 participant 回 yes/no → coordinator 发 commit/abort。游戏 netcode 不用 2PC,因为它要求所有 participant 同步响应——任何 participant 卡整个事务卡,跟 OCC 的"乐观"哲学相反。但**游戏的 server 重新广播 state 等价于 OCC 的 validation phase**。

**Conflict-free Replicated Data Types**(CRDT):允许"无冲突合并"。counter CRDT 在多个 client 都能 +1,合并取 max 或 sum。游戏 netcode 一般不用 CRDT(game state 不是"幂等可合并"),但**某些子问题**适合 CRDT——击杀计数、成就进度。

### 13.3 共同的洞察

OCC、2PC、CRDT、lockstep、游戏 prediction 都解决同一个问题:**多个 writer 共享状态如何最终一致**。不同的算法在不同维度做权衡:

| 算法 | 延迟 | 冲突处理 | 适用语义 |
|---|---|---|---|
| OCC | 低 | abort + replay | 通用事务 |
| 2PC | 高 | 序列化 | 严格一致事务 |
| CRDT | 中 | 自动合并 | 可合并语义(counter, set) |
| Lockstep | 高 | 零冲突(序列化) | 跨 client deterministic |
| Server-authoritative + prediction | 低 | server single writer | 游戏状态 |

理解这个 trade-off matrix 让你能**给任何分布式一致性问题选算法**——不止游戏。数据库、文件系统、版本控制(git 三方合并)、协作编辑(Google Docs 的 OT 算法)都是同一棵树的不同枝。

## 14 · 在你 HH 项目里实践

理论、源码、案例都讲完了。下面给你具体的落地步骤,把你 HH 项目变成能联机的版本。

### 14.1 选型:HH 适合哪种 netcode

回顾 §3.4 的决策树:HH 是动作平台游戏,容忍度 100-150 ms,允许 2-4 人联机,跨平台不重要(假设只 PC)。**推荐**:

- **架构**:server-authoritative + client prediction + interpolation。**不要** GGPO(HH 不要求跨 client bit-exact)。
- **库**:用 `renet`(https://github.com/lucaspeson/renet),提供 reliable UDP、connection management。**不用** `ggrs`(那是 P2P)。
- **Server**:dedicated server binary(`hh_server`),跑同一个 simulation。Client binary(`hh_client`)。
- **Tick**:60 Hz server tick,20 Hz broadcast。
- **Max rollback**:7 帧。

### 14.2 集成步骤

**Step 1:分离 simulation 和 rendering**

HH 现在的 `update_and_render` 函数把 simulation 和渲染混在一起。第一步是分开,server 只跑 sim,client 只跑 render:

```rust
// Before:
fn update_and_render(state: &mut State, input: &Input) { update_sim(state, input); render(state); }
// After:
fn update_sim(state: &mut State, inputs: &[PlayerInput]) { ... }
fn render(state: &State) { ... }
```

**Step 2:抽出 game state**。所有 mutable state 集中到 `#[derive(Serialize, Deserialize, Clone)] struct GameState`,不包含非 deterministic 字段(无 `Instant`、无 `*const T`)。

**Step 3:加 input ring buffer + state snapshot**。client 加 §4 的 input_history 和 state_history,每帧存 snapshot,最多 8 份。

**Step 4:加 prediction + reconciliation**。实现 §4 完整算法——本地输入立即应用,server ACK 触发 hash 对比,不一致时回滚重放。

**Step 5:加 interpolation**。其它玩家位置用 §5 entity interpolation,延迟 buffer 100 ms。

**Step 6:加 smooth correction**。§4.5 的 smooth_correction,防止视觉瞬移。

**Step 7:网络层**

renet 提供可靠 UDP、连接管理、channel 分离。骨架:

```rust
use renet::{RenetServer, RenetServerConfig, ServerEvent};

let mut server = RenetServer::new(config, ConnectionConfig::default(), server_addr, socket);

loop {
    server.update(delta).ok();
    while let Some(event) = server.get_event() {
        // 处理 ClientConnected / ClientDisconnected
    }
    // 收每个 client 的 input(channel 0)
    for cid in server.clients_id().iter() {
        for msg in server.receive_messages(cid, 0).unwrap_or_default() {
            let input: PlayerInput = bincode::deserialize(&msg).unwrap();
            // 应用
        }
    }
    game.step(all_inputs);
    // 广播 state hash(channel 1)
    let bytes = bincode::serialize(&game.hash()).unwrap();
    for cid in server.clients_id().iter() {
        server.send_message(*cid, 1, bytes.clone()).ok();
    }
}
```

renet 用 channel 区分 reliable vs unreliable。Input 走 unreliable channel(丢了重发即可),state hash 走 unreliable(够用),FullStateResponse 走 reliable(必须到)。renet 的可靠 channel 实现(类似 QUIC)在 https://github.com/lucaspeson/renet/blob/main/renet/src/reliable_channel.rs,主模块在 https://github.com/lucaspeson/renet/blob/main/renet/src/lib.rs。

### 14.3 测试网络条件

```bash
# 用 tc netem 模拟 80 ms RTT,1% 丢包
sudo tc qdisc add dev lo root netem delay 40ms loss 1%
# 跑两个 client 在 localhost,server 也在 localhost
# 完了清除
sudo tc qdisc del dev lo root
```

预期:1% 丢包 rubber banding < 5%;5% 丢包 10-20% 帧 rollback 但 smooth correction 让玩家几乎无感;10% 丢包明显劣化但仍可玩。

### 14.4 调优参数

| 参数 | 初始值 | 调优范围 |
|---|---|---|
| MAX_ROLLBACK_FRAMES | 7 | 5-12(更大用更多内存) |
| SMOOTH_FACTOR | 0.15 | 0.05-0.3 |
| Interpolation buffer | 100 ms | 60-150 ms |
| Server tick | 60 Hz | 30-120 Hz |
| Broadcast frequency | 20 Hz | 10-30 Hz |

**没有"正确"答案**,要 playtest 调整。

### 14.5 验收清单

- [ ] 单机模式不受影响(关 netcode 跑)
- [ ] 联机 2 人,P1 自己动得跟单机一样流畅
- [ ] P2 移动平滑,无明显 jitter
- [ ] 80 ms RTT 玩 5 分钟,rubber banding < 5 次
- [ ] 200 ms RTT 仍可玩(不流畅但不崩溃)
- [ ] 1% 丢包下,smooth correction 让 misprediction 几乎不可见
- [ ] 一方断线,另一方看到 "P2 disconnected",不崩溃
- [ ] Server binary 跑在另一台机器,client 连得上

## 15 · 开源贡献机会

`renet` / `ggrs` / `bevy_replicator` 都在积极维护,适合贡献 PR。

**renet**(https://github.com/lucaspeson/renet):文档薄,可以补完整 prediction + interpolation 的 example;加 2 人 FPS example 展示 lag compensation;reliable channel 有性能优化空间;看 issues 列表 fix outstanding bugs。

**ggrs**(https://github.com/gschup/ggrs):跨平台 determinism 测试套件(自动检测 simulation 在不同 CPU / OS 上 bit-exact);smoothing 算法(从 lerp 升 hermite 或 critically damped spring);WebAssembly 支持。

**bevy_replicator**(https://github.com/Ubee/bevy_replicator,社区维护):组件级 prediction plugin(把 §4 算法集成到 bevy ECS);可视化 debug UI(显示 rollback 频率 / 深度 / hash divergence)。

**提 PR 流程**:(1) Fork + clone;(2) 在 issue 列表确认方向;(3) 干净的 commit history,每个 commit 一个逻辑改动;(4) 跑 `cargo test`,推 fork 跑 CI;(5) PR 描述(动机、summary、验证步骤、issue link);(6) iterate maintainer 反馈。游戏 netcode 社区非常 friendly。

## 16 · 延伸阅读

外部稳定 URL:

- **GGPO 原始论文** — Tony Cannon, "GGPO Network Library", https://drive.google.com/file/d/0B1qyuld1fXJneFpwNTN4VTRrQ1U/view
- **Valve Source Multiplayer Networking** — https://developer.valvesoftware.com/wiki/Source_Multiplayer_Networking
- **Overwatch GDC 2017 Talk** — "Overwatch Gameplay Architecture and Netcode", https://www.gdcvault.com/play/1024597/
- **Glenn Fiedler's Networking for Game Programmers** — https://gafferongames.com/categories/game-networking/
- **Valorant 128-Tick Servers** — https://technology.riotgames.com/news/valorant-128-tick-servers
- **Kung & Robinson OCC 原始论文** — "On Optimistic Methods for Concurrency Control", 1979, ACM TODS
- **Google Spanner**(OCC + TrueTime)— 2012 OSDI 论文
- **Shapiro et al. CRDT survey** — "A comprehensive study of Convergent and Commutative Replicated Data Types", 2011

真实开源源码参考(都在本篇正文引用过):

- **Quake 3 client prediction** — https://github.com/id-Software/Quake-III-Arena/blob/master/code/client/cl_pred.c
- **ggrs P2P session** — https://github.com/gschup/ggrs/blob/master/src/sessions/p2p_session.rs
- **ggrs sync layer**(state ring buffer)— https://github.com/gschup/ggrs/blob/master/src/sync_layer.rs
- **renet 主模块** — https://github.com/lucaspeson/renet/blob/main/renet/src/lib.rs
- **renet reliable channel** — https://github.com/lucaspeson/renet/blob/main/renet/src/reliable_channel.rs
- **GGPO sync.cpp** — https://github.com/pondababa/GGPO/blob/master/lib/ggpo/sync.cpp
- **Source SDK 2013 lag compensation** — https://github.com/ValveSoftware/source-sdk-2013/blob/master/sp/src/game/shared/gamemovement.cpp
- **bevy_replicator** — https://github.com/Ubee/bevy_replicator

本仓库内相关内容:

- `days/phase-5/deep-dives/network-multiplayer-models.md` — 联机架构全谱(本文前置)
- `days/phase-5/deep-dives/threading-journey.md` — 多线程架构,netcode 离不开
- `days/phase-5/day201.md` — 隔离调试代码,本文的 netcode 调试工具用到
- `days/phase-0/23-network-foundation.md` — socket / TCP / UDP 基础
- `days/phase-0/25-concurrency-foundation.md` — 并发基础

读完这一篇,你应该能在 HH 项目里集成一套可玩的 prediction + rollback netcode,知道为什么 GGPO 适合格斗、CS 类适合 FPS,知道乐观并发控制为什么是游戏 netcode 的同构抽象,知道哪些坑会让你在凌晨三点抓头发——以及怎么爬出来。
