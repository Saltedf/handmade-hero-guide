
# 9E-3 · 兴趣管理与按需复制

## 0 · 你的 09E-2 服务器在 4 玩家时跑得很美,64 玩家时直接被带宽勒死

你在 [09E-2](09E-2-authoritative-server-and-state-sync.md) 里搭好了一台权威服务器,跑 30 tick,每 tick 把整个世界状态量化、bitfield 打包,广播给所有客户端。4 个玩家连进来,延迟 100ms,带宽每客户端 30 KB/s,体验丝滑。你觉得"联机化"这件事真的过了关,准备开 64 人公共测试。

测试当晚,你拿到一份数据:你的世界现在有 5000 个 entity(怪物、道具、NPC、玩家投射物),每个 entity 在 bitfield + 量化后平均 6 字节。每 tick 你给每个客户端发一份完整的 `SnapshotPacket { tick, entities: Vec<EntitySnap> }`,5000 × 6 = 30 KB / 客户端 / tick,30 tick 就是 900 KB/s,合 7.2 Mbps **下行**,64 个客户端 × 7.2 Mbps = 460 Mbps **服务器上行**。你家服务器上行是 100 Mbps,直接打满,后连的客户端收不到完整快照,角色开始瞬移;先连的客户端虽然收得到,但客户端的 60 FPS 渲染循环被"每帧反序列化 30 KB"拖到 12 FPS。玩家在论坛上写:"这游戏进大地图就崩。"

你打开抓包,看了一秒的流量,发现一个让你睡不着觉的事实:**发给每个客户端的 30 KB 里,绝大多数字节是关于地图另一端的 entity 的**。客户端 A 站在城东,服务器给他发了城西 2000 米外一个怪物在打盹的状态;客户端 B 站在野外,服务器给他发了主城里 47 个玩家的精确朝向。这些 entity 在 A 和 B 的屏幕上**根本不存在**——它们的坐标远超摄像机的视锥,渲染管线连一个像素都不会画它们。但你把它们的字节老老实实从服务器内存搬到了客户端内存,又从客户端内存搬进了渲染管线的剔除阶段,被 frustum cull 扔掉。整条链路做了一件纯粹的废功。

这不是一个"优化"问题,这是一个**架构错误**。把整个世界状态发给一个客户端,等价于强迫每台客户端的下行带宽和 CPU 跟着"世界总规模"线性增长——世界越大,每个客户端越惨,哪怕这个客户端只看得见眼前 10 米。这种架构在大世界里必然崩溃,无论你把量化做得多狠、把 delta 压得多紧。

这一篇要讲的,是这个架构错误的根本解:**兴趣管理(interest management)**,也叫 area of interest(AoI,兴趣区域)管理。它的核心命题非常简单——**每个客户端只应该收到它当前"关心"的 entity 的状态**,服务器在每 tick 给每个客户端单独算一份"你这一 tick 该看到什么",只把这一份发出去。关心什么由游戏决定:能看到(view distance)、在同一房间、最近交互过、自己拥有(owned)、正在被某个事件影响……算出一个**兴趣集合**(interest set),只复制这个集合里的 entity。这个改动把"广播复杂度"从 `O(玩家数 × entity 总数)` 降到 `O(玩家数 × 平均邻居数)`——一个站在城东的玩家,他的兴趣集合里只有城东 50 米半径内的几十个 entity,5000 个 entity 里的其余 4950 个对他的网络包一个字节都不占。

但要让它每 tick 跑得起,你得解决两个工程子问题。第一,**怎么在每个 tick、对每个客户端,快速算出"它附近有哪些 entity"**——5000 个 entity 逐个算距离是 O(5000) × 64 客户端 = 32 万次 / tick,够呛,这正是 [phase-6/spatial-acceleration](../phase-6/deep-dives/spatial-acceleration.md) 那一篇搭好的 uniform grid / BVH / quadtree 的主场,网络层的"邻居查询"和渲染层的"frustum cull"用的是同一套空间数据结构。第二,**当客户端的带宽预算发不完兴趣集合里所有 entity 时,先发谁**——这就是 **priority accumulator**(优先级累加器)该出场的地方,服务器给每个候选 entity 打一个分数,优先发高分,低分的留到下个 tick,分数随"错过更新的时间"上升,最终每个 entity 都不会被饿死。

把这三件事——AoI 决定"发什么"、空间结构"算得快"、priority accumulator 决定"先发谁"——叠在 09E-2 的 delta + 量化之上,你的服务器就能从"4 人小屋"扩到"64 人战场",再往上还能扩到几百人。这一篇按这条主线展开,每一步都给可跑代码,最后落到你 HH 项目里——给你的 09E-2 服务器加一个 spatial grid、一个 per-client 兴趣集合、一个简单的 priority 队列,亲眼看到带宽从"跟总 entity 数走"变成"跟视距走"。

## 1 · 兴趣管理:从"广播"到"按需复制"的范式转变

要把这件事讲透,得先把"广播给所有人"这个朴素模型为什么错的根因抠干净。广播模型有一个隐含假设——**世界是小的,小到每个客户端都对整个世界感兴趣**。HH 这种几十个 entity 的横版动作,4 个玩家同屏,这个假设成立:服务器发一份完整快照给每个客户端,每个客户端都用得上几乎全部字节。但只要世界大到"客户端的摄像机看不到全部 entity",这个假设就破,广播就开始往网线上倒垃圾。

兴趣管理做的事情,是把"客户端应该收到什么"从一个**全局决策**(发所有人)变成**每个客户端的独立决策**(发你看得到的)。服务器不再维护一个 `Vec<EntitySnap>` 然后 send_to 给每个客户端,而是对每个客户端维护一个**视角上下文**(viewer context):这个客户端现在站在哪、朝哪看、属于哪个房间、跟谁在交互。基于这个上下文,服务器从全局 entity 池里**筛出一个子集**——这个子集里的 entity 才会被序列化进给这个客户端的包。其它客户端拿到的是另一份完全不同的子集。

这套机制为什么从根本上解决带宽问题?因为绝大多数游戏里,**一个客户端在任意时刻能"感知"到的 entity 数量是有上界的**——这个上界由摄像机视距、房间布局、玩法决定,跟世界总规模无关。一个 FPS 玩家的视距是 100 米,他关心 100 米内的 entity,这个集合无论世界里有 5000 个还是 50000 个 entity,平均都是几十到一百多个;一个 MMO 玩家在一个房间内,关心这个房间内的 entity,房间的容量是有限的。所以"兴趣集合大小"基本是个常数,跟世界规模无关。这就是 AoI 把带宽从 `O(N_entities)` 降到 `O(N_nearby)` 的根本原因——`N_nearby` 是常数。

代码骨架非常干净。服务器端,你给每个客户端维护一个 `ViewerContext`,每 tick 跑一遍"为这个客户端算兴趣集合"的函数,只把集合内的 entity 序列化进去:

```rust
struct ViewerContext {
    client_id: ClientId,
    pos: Vec2,           // 这个客户端当前的位置(从最近输入推得)
    view_radius: f32,    // 视距,游戏设计参数
    recent_interactions: VecDeque<EntityId>, // 最近交互过的 entity
    owned: Vec<EntityId>, // 这个客户端拥有的 entity(自己角色、宠物)
}

impl Server {
    fn tick(&mut self) -> io::Result<()> {
        // 收输入 + step(和 09E-2 完全一样)
        self.recv_all_inputs()?;
        self.step();
        // 关键改动:不再 broadcast 一份完整快照
        // 而是给每个客户端算一份独立的、按兴趣裁剪过的快照
        for ctx in &self.viewers {
            let interest_set = self.compute_interest(ctx);
            let packet = self.serialize_for(ctx.client_id, &interest_set);
            self.socket.send_to(&packet, ctx.addr)?;
        }
        Ok(())
    }

    fn compute_interest(&self, ctx: &ViewerContext) -> Vec<EntityId> {
        let mut set: Vec<EntityId> = self.spatial
            .query_circle(ctx.pos, ctx.view_radius)  // 视距内的 entity
            .copied()
            .collect();
        // owned 永远关心(哪怕离得远——比如自己的尸体在地图另一端)
        for id in &ctx.owned {
            if !set.contains(id) { set.push(*id); }
        }
        // 最近交互过的 entity 短期关心
        for id in &ctx.recent_interactions {
            if !set.contains(id) { set.push(*id); }
        }
        set
    }
}
```

注意 `compute_interest` 里**没有一处**遍历整个 entity 池——它只查空间结构(`query_circle`),并合并几个小集合(`owned` 通常就一两个,`recent_interactions` 也是个 deque 截断过的)。整个函数的复杂度跟世界总规模无关,只跟"客户端关心的 entity 数"走。这是 AoI 架构能 scale 的核心。

还有一个工程含义容易被忽略:**客户端的快照包变小,客户端的解析也变快**。在广播模型下,客户端每帧反序列化 30 KB,即便 99% 的字节会被渲染管线 frustum cull,反序列化本身已经吃掉 CPU;在 AoI 模型下,客户端每帧反序列化几百字节,几乎免费。也就是说 AoI 不只是省服务器带宽,**它还省客户端 CPU**——这是为什么移动端游戏(AoV、原神移动版)特别依赖 AoI,手机反序列化慢,服务器发得越小越好。

最后提一句——"兴趣"不是只有"几何近"这一种判据。一套完整的 interest management 通常混合多条规则:**几何近**(视距内 / 同一房间 / 同一 region)、**关系近**(队友、敌对、同一公会)、**事件近**(刚才打过我、刚才我打过、刚才发了广播)、**owned**(自己控制的角色、自己的召唤物、自己的投射物)、**always**(时钟、计分板、世界事件)。一个 entity 满足任一条规则就进兴趣集合,集合再交给下一节讲的 priority 排序。这套混合判据是"游戏玩法"渗进"网络协议"的入口——同一台服务器、同一份代码,玩法变(比如加一个"附近有 boss 战时所有人收到 boss 状态"),interest 规则跟着变,网络层不需要重写。

## 2 · 空间加速结构:让"找附近的 entity"在每个 tick 都付得起

兴趣管理的核心算法——`compute_interest`——里最热的一行,是"找出 `ctx.pos` 周围 `view_radius` 内的所有 entity"。这看起来是个最朴素的查询,但每 tick 给每个客户端都要算一次。如果你的实现是遍历整个 entity 池算距离:

```rust
// 朴素实现:O(N_entities) per client per tick
fn query_circle_naive(all: &[Entity], center: Vec2, r: f32) -> Vec<&Entity> {
    all.iter().filter(|e| (e.pos - center).length_squared() < r*r).collect()
}
```

64 客户端 × 5000 entity = 32 万次距离计算 / tick,每次几个 cycle,合计几毫秒,30 tick 就是上百毫秒——单凭这一步你的服务器 tick 就跑不满。这是 [phase-6/spatial-acceleration](../phase-6/deep-dives/spatial-acceleration.md) §0 讲的"O(N²) 死亡"在 9E 这个新语境下的重现:渲染层和物理层都早就用空间结构逃出了 O(N²),网络层没有理由还困在里面。

解法和那一篇一模一样——**用一个空间加速结构,把 entity 按位置组织起来,查询时只访问候选区域**。对于 2D 游戏(HH 这种横版、top-down、MMORPG 平面地图),uniform grid 是最常见的选择:把世界切成固定大小的方格,每个 entity 登记到它所在的格子,查询时只查中心格 + 周围 8 格(对于视距小于 2 格半径的情况)。这种查询的复杂度从 O(N) 降到 O(邻居数),跟世界总规模脱钩。

这里要强调一个 [phase-6/spatial-acceleration](../phase-6/deep-dives/spatial-acceleration.md) 已经反复讲过的工程原则——**空间结构不是网络层独享的**,它是整个游戏**共享的基础设施**。渲染层用它做 frustum cull、物理层用它做 broadphase 碰撞、AI 层用它做"找最近的敌人"、网络层用它做 interest query。一份 grid 数据,四个子系统读。这意味着你做 9E-3 之前,如果你的 HH 项目还没有 spatial grid,你应该先回到 phase-6 把它建起来——不要在网络层再写一个,那是重复劳动,而且两份结构容易不一致(渲染层认为 entity 在格 A,网络层认为在格 B,两个客户端看到的位置不一样,debug 到死)。

最简单的实现是一个 `HashMap<GridCell, Vec<EntityId>>`,每帧 clear 再 rebuild——clear + rebuild 比增量维护更便宜,因为 entity 数远小于格子数,而增量更新要处理"上一帧在格 A、这一帧在格 B"的迁出/迁入逻辑。代码骨架:

```rust
#[derive(Hash, Eq, PartialEq, Copy, Clone)]
struct GridCell { x: i32, y: i32 }

struct SpatialGrid {
    cell_size: f32,
    cells: HashMap<GridCell, Vec<EntityId>>,
}

impl SpatialGrid {
    fn new(cell_size: f32) -> Self {
        assert!(cell_size > 0.0);
        SpatialGrid { cell_size, cells: HashMap::new() }
    }

    fn rebuild(&mut self, entities: &BTreeMap<EntityId, Entity>) {
        self.cells.clear();
        for (id, e) in entities {
            let cell = self.cell_of(e.pos);
            self.cells.entry(cell).or_default().push(*id);
        }
    }

    fn cell_of(&self, pos: Vec2) -> GridCell {
        GridCell {
            x: (pos.x / self.cell_size).floor() as i32,
            y: (pos.y / self.cell_size).floor() as i32,
        }
    }

    // 查询圆内的 entity。视距 r ≤ cell_size 时只需要查 3x3;
    // r 更大时按 ceil(r/cell_size) 扩张查询窗口
    fn query_circle<'a>(
        &'a self,
        entities: &'a BTreeMap<EntityId, Entity>,
        center: Vec2,
        r: f32,
    ) -> impl Iterator<Item = EntityId> + 'a {
        let r_cells = (r / self.cell_size).ceil() as i32;
        let center_cell = self.cell_of(center);
        let r2 = r * r;
        (center_cell.x - r_cells ..= center_cell.x + r_cells)
            .flat_map(move |cx| {
                (center_cell.y - r_cells ..= center_cell.y + r_cells)
                    .flat_map(move |cy| {
                        self.cells.get(&GridCell { x: cx, y: cy })
                            .into_iter().flatten().copied()
                    })
            })
            // 网格查询会"过取"——把矩形窗口里的 entity 都返回了,
            // 还得做一次精确距离筛,把圆外的剔掉
            .filter(move |id| {
                let e = &entities[id];
                (e.pos - center).length_squared() <= r2
            })
    }
}
```

注意最后一行的精确距离筛——grid 查询给的是"包围圆的方格窗口"里的所有 entity,这一步会把矩形四个角上、其实不在圆内的 entity 也带回来,所以必须在最后用 `length_squared() <= r2` 再过一遍。这是一个"广撒网再精确筛"的经典 pattern,phase-6 那篇在讲 broadphase 时反复提过。

cell_size 怎么选?经验法则:**等于或略大于视距**。这样查询窗口恰好是 3×3 格,九个格子的 entity 总数跟"视距内 entity 数"几乎相等,过取最小。如果 cell_size 远小于视距,查询窗口要扩成 5×5 或 7×7,过取严重;如果 cell_size 远大于视距,每个格子里塞了一堆视距外的 entity,过取也严重。HH 这种视距 50 米的游戏,cell_size = 50 米很合适。

3D 游戏或世界尺度更大的(MMO),uniform grid 不一定够,会换成 quadtree(2D 动态分裂)、BVH(任意维度)、octree(3D)。这些 phase-6 都讲过,这里不重复,只点一句——**选哪种结构取决于"查询 pattern"**:网络层的查询几乎总是"以某个客户端位置为圆心的圆查询",uniform grid / quadtree 对圆查询最快;BVH 对 ray / box 查询最快,更适合渲染层。所以渲染层和网络层**可能用不同的结构**,但 entity 的 ground truth 必须只有一个,任何结构的更新都从这个 ground truth 派生。

最后一句关于"为什么每帧 rebuild 而不是增量更新"。看上去 rebuild 是 O(N_entities) 的,而增量更新摊到每个移动的 entity 是 O(1) 的——理论上增量更快。但 rebuild 是**线性扫描 + 单次哈希插入**,缓存友好,branch predictor 满意;增量更新要处理"格子之间的迁移",每次迁移是两个 HashMap 的删除+插入,hash + 比对的开销远高于线性扫描的均摊成本。5000 entity 全量 rebuild 大约 50 μs,30 tick 才 1.5 ms,完全在预算内。这就是为什么 phase-6 那篇推荐"每帧 rebuild"——简洁、缓存友好、够快。增量更新是 10000 entity 起步、且 entity 位置稀疏迁移时才需要的优化,过早优化是万恶之源。

## 3 · Priority Accumulator:带宽不够时,先发谁

到这里,你能给每个客户端算出一份"它该看到的 entity 列表"了。但很快你会撞到第二个工程问题:**兴趣集合有时比客户端的带宽预算还大**。一个具体场景:你的 MMO 里,64 个玩家挤在一个 boss 房间里,boss 召唤了 200 个小怪,房间内 entity 总数 264+。一个客户端的下行带宽预算假设是 100 KB/s,30 tick 就是 3.3 KB / tick,量化后平均每个 entity 4 字节,3.3 KB 只够发 800 字节 ≈ 200 个 entity。264 > 200,有 64 个 entity 这一 tick 发不出去。

朴素的解法是"按距离排序,近的先发"。但这个解法有个隐蔽的失败模式——**远处的 entity 永远发不出去,直到客户端走近才一次性"瞬移"出现**。一个玩家站在原地,他 80 米外有个巡逻的怪,按距离排序这个怪永远排在自己脚下 5 米内那几个怪后面,从来不发;客户端走近怪到 50 米,怪突然"刷"出来——这种 popping 在 MMO 里非常常见,玩家一眼就看穿。更糟的是,某些重要的远距离事件(一个 boss 在远处吼了一嗓子、广播了全图)也会因为距离远被无限延后。

工业级的解法叫 **priority accumulator**(优先级累加器)。它给每个候选 entity 维护一个**累积优先级**(accumulated priority),这个分数由几个因子合成:距离(近的高分)、拥有的 entity(永远最高分)、最近交互(短期高分)、**错过更新的时长**(越久没发,分数随时间累积越高)。服务器每 tick 给每个客户端,从兴趣集合里选**优先级最高的若干个** entity 发出去,发出去的就把它的累积优先级**清零**(或者扣掉一个"刚发了一次"的固定值),没发出去的继续累积。这样,即便某个远距离 entity 距离分很低,它"好几个 tick 没发"的累积分会逐渐追上近距离的高分 entity,最终被发出去——这叫**反饥饿(anti-starvation)**,保证每个 entity 在合理时间内都至少被同步一次。

代码骨架——priority accumulator 是 per-client 的状态,因为它要为每个客户端独立追踪"这个 entity 给这个客户端多久没发了":

```rust
struct PriorityEntry {
    entity: EntityId,
    accum: f32,         // 累积优先级
    last_sent_tick: u32,// 上次发给这个客户端的 tick
}

struct ClientPriority {
    entries: HashMap<EntityId, PriorityEntry>,
    per_tick_budget_bytes: usize,
}

impl ClientPriority {
    // 每 tick 调用一次,更新候选 entity 的累积分,并选出本次要发的
    fn select_for_send(
        &mut self,
        interest: &[EntityId],
        viewer_pos: Vec2,
        entities: &BTreeMap<EntityId, Entity>,
        cur_tick: u32,
    ) -> Vec<EntityId> {
        // 1. 把 interest 集合里没有的 entry 清掉(它离开了兴趣区)
        self.entries.retain(|id, _| interest.contains(id));
        // 2. 给 interest 集合里的 entity 累加优先级
        for &id in interest {
            let e = &entities[&id];
            let dist = (e.pos - viewer_pos).length();
            // 距离分:近的高,远的低,view_radius 处归零
            let dist_score = (1.0 - dist / 50.0).max(0.0) * 10.0;
            // 饥饿分:每错过一个 tick 累加 1.0,保证最终被发
            let ticks_since = (cur_tick.saturating_sub(
                self.entries.get(&id).map(|p| p.last_sent_tick).unwrap_or(0)
            )) as f32;
            let starve_score = ticks_since * 1.0;
            let score = dist_score + starve_score;
            self.entries.entry(id).and_modify(|p| p.accum = score)
                .or_insert(PriorityEntry {
                    entity: id, accum: score, last_sent_tick: 0,
                });
        }
        // 3. 按累积优先级降序排序
        let mut sorted: Vec<&mut PriorityEntry> = self.entries.values_mut().collect();
        sorted.sort_by(|a, b| b.accum.partial_cmp(&a.accum).unwrap());
        // 4. 按字节预算贪心选取
        let mut to_send = Vec::new();
        let mut bytes_used = 0;
        for entry in sorted {
            if bytes_used + 4 > self.per_tick_budget_bytes && !to_send.is_empty() {
                break; // 预算用完,剩下的留到下一 tick 继续累积
            }
            to_send.push(entry.entity);
            entry.accum = 0.0;              // 发了就清零
            entry.last_sent_tick = cur_tick; // 记下时间,用于下次饥饿分计算
            bytes_used += 4;
        }
        to_send
    }
}
```

读这段代码时,关键看 `starve_score` 这一项——它是 priority accumulator 的灵魂。距离分让"近的优先"符合直觉,但单独的距离分会饿死远处的 entity;`ticks_since * 1.0` 这一项保证每个 tick 不被发的 entity,它的分数都+1,几秒后(30 tick × 几秒)累积分就会超过任何距离分,被强制发一次。这种"距离定基调、饥饿保公平"的组合,是工业级 interest scheduler 的标准做法。

`per_tick_budget_bytes` 这个字段是 per-client 的,因为不同客户端带宽不同——移动端客户端预算 30 KB/s,PC 端 100 KB/s,服务器按客户端的 budget 上报来分配。商业 netcode(renet / Nakama)都有这套机制,通常叫 "send rate" 或 "bandwidth limit" 配置。

还有一个细节值得展开:**owned entity 永远在 to_send 里**。玩家自己的角色、自己的宠物、自己的投射物,无论距离多远,都要每 tick 同步——因为玩家需要看到自己的操作立即响应(client prediction 的前提)。所以 `select_for_send` 通常会在贪心选取之前,先把 `owned` 集合全部 push 进 `to_send`,然后再用 budget 选其它 entity。这是 9E-3 和下一篇 [09E-4](09E-4-matchmaking-nat-relay-lobby.md) 涉及的 client prediction 的衔接点——prediction 要工作,服务器必须保证 owned entity 的状态每 tick 都到客户端。

priority accumulator 还有一个常被忽略的进阶用法——**event-driven priority spike**。当一个 entity 触发了一个重要事件(开了火、被打到、爆炸),它在这一 tick 给所有客户端的 priority 立刻 spike 到最高(比如 +1000),保证"看到这一枪被打出去"在所有相关客户端是同步的。这种"事件驱动加急"是 FPS netcode 的必备——你按下开火,服务器在所有客户端那里都把"你的角色 + 你的子弹"的 priority 顶到最高,确保几十毫秒内大家都看到这一枪。代码上加一行:

```rust
// 在 step 之后、select_for_send 之前,把本 tick 触发事件的 entity 标记
for (client_id, ctx) in &self.viewers {
    for &event_entity in &self.this_tick_event_entities {
        if let Some(p) = self.prio.get_mut(client_id).and_then(|m| m.get_mut(&event_entity)) {
            p.accum += 1000.0;  // 立刻顶到队首
        }
    }
}
```

总结一下三件事的分工:**AoI 决定"发什么"(what)、空间结构决定"算得快"(fast)、priority accumulator 决定"先发谁"(order)**。这三件事一起,把 09E-2 的"无脑广播"升级成"工业级按需复制"。下一节我们把它们和 09E-2 的 delta + 量化接起来,看完整链路。

## 4 · 把 AoI、Priority、Delta 串起来:WHAT × ORDER × HOW SMALL

很多人学 9E-3 会卡在一个困惑——"我已经做了 delta compression(09E-2 §3),为什么还要 AoI?两个不都是省带宽的吗?"这个困惑的根因,是把"省带宽"当成一件事,而实际上**省带宽分三个独立的维度,各管一件事,不能互相替代**。

第一个维度是 **WHAT**——发哪些 entity。这是 AoI 管的。即便你 delta 做得再狠,只要你把一个客户端永远看不见的 entity 也序列化进去,字节就是浪费——哪怕每个 entity 只剩 1 字节,5000 个看不见的 entity 也是 5 KB/tick。AoI 在"选哪些 entity 进包"这一层就把它们排除了。这是最大的省——从"5000 个 entity 的字节"砍到"100 个 entity 的字节",一个数量级。

第二个维度是 **ORDER**——当 WHAT 选出来的集合仍然超出预算,先发谁。这是 priority accumulator 管的。它决定的是"哪些 entity 这 tick 同步、哪些留到下 tick",目标是保证重要的、饥饿的被先发,而不是均匀随机地丢一些。ORDER 不直接省字节,它省的是"字节的有效性"——同样的字节预算,priority 让你优先同步玩家最关心的 entity,体验质量天差地别。

第三个维度是 **HOW SMALL**——每个被选中的 entity,用多少字节发。这是 09E-2 §3 的 delta + 量化管的。量化把 f32 压成 i16,delta 只发变化字段,bitfield 标记哪些字段存在。HOW SMALL 决定的是"单个 entity 的字节成本",从 64 字节砍到 4 字节,一个数量级。

三个维度相乘:从"5000 entity × 64 字节 = 320 KB/tick"(朴素广播),降到"100 entity × 4 字节 = 400 字节/tick"(AoI + delta),**省 800 倍**。其中 AoI 贡献了 50 倍(5000→100),量化+delta 贡献了 16 倍(64→4),两者独立、可叠加。priority 不省字节,但保证这 400 字节花在玩家最关心的 entity 上,避免"近处的怪没同步、远处的怪同步了三遍"这种荒唐分配。

下面是完整的服务器 tick 伪代码,把三件事串起来。这段代码就是你给 09E-2 服务器加 9E-3 之后的最终形态:

```rust
impl Server {
    fn tick(&mut self) -> io::Result<()> {
        // ---- 09E-2 不变 ----
        self.recv_all_inputs()?;
        self.step();
        self.spatial.rebuild(&self.state.entities); // 重建空间结构
        self.this_tick_event_entities.clear();
        // step 内部会把触发事件的 entity 推进 this_tick_event_entities

        let cur_tick = self.state.tick;

        // ---- 9E-3 新增 ----
        for ctx_idx in 0..self.viewers.len() {
            let (ctx, prio, state, spatial) = self.split_borrow(ctx_idx);
            // WHAT: 算兴趣集合
            let interest = compute_interest(ctx, spatial, state);
            // ORDER: 选本 tick 发哪些(budget 内)
            let to_send = prio.select_for_send(
                &interest, ctx.pos, &state.entities, cur_tick,
            );
            // 把本 tick 事件 entity 的 priority 顶高
            for &eid in &self.this_tick_event_entities {
                if interest.contains(&eid) {
                    if let Some(p) = prio.entries.get_mut(&eid) {
                        p.accum += 1000.0;
                    }
                }
            }
            // HOW SMALL: 序列化成 delta + 量化
            let bytes = self.delta_serializer.serialize_for(
                ctx.client_id, &to_send, &state.entities, cur_tick,
            );
            self.socket.send_to(&bytes, ctx.addr)?;
        }
        Ok(())
    }
}
```

`split_borrow` 是一个借用切片的小技巧——Rust 不允许在循环里同时 `&mut self.viewers[i]` 和 `&self.state`,需要把 self 拆开借。生产代码可以用 index 或者把 viewers / state / spatial 拆成独立字段分别借。`delta_serializer` 是 09E-2 §4 那个 delta encoder,这里复用,只是它现在收到的不是"全部 entity",而是"本客户端本 tick 选出的 entity 子集"。

还有一个工程细节值得点——**rebuild 空间结构的位置**。每 tick 的开头 rebuild 一次,因为 step 之后 entity 位置变了,空间结构必须反映新位置。这一步是 9E-3 新增的固定开销,5000 entity 大约 50-100 μs,可以接受。

## 5 · Per-client 通道 vs Broadcast 通道:两种 entity,两种发送策略

讲到这里,容易给人一个错觉——"所有 entity 都是 per-client 的,每个客户端拿到的快照都完全不同"。实际情况是,**绝大多数游戏有一小撮 entity 是真·全局的,所有客户端收到的内容完全一样**,这部分用 broadcast 通道发,跟 per-client 通道并行。把这两类 entity 区分开,既省 CPU(全局的只序列化一次),也省带宽(全局的走 multicast 或单次大包),还让协议更清晰。

哪些是全局 entity?典型有几类:**世界时钟**(所有客户端需要一个单调递增的服务器时间,用于延迟估算、动画同步)、**全局计分板**(MOBA 的双方击杀数、battle royale 的存活人数)、**世界事件**(boss 何时刷新、空投何时落地、昼夜更替)、**全局聊天**(广播给同一 zone 的所有客户端)、**规则状态**(比赛阶段:准备 / 进行 / 结算)。这些 entity 的特点是**所有客户端都关心同样的内容**,没有 per-client 差异。

把这些和 per-entity state 混在一个 `SnapshotPacket` 里发,是一种"看似省事实则乱"的设计——你得在每个客户端的包里都序列化一份时钟、一份计分板,64 个客户端就序列化 64 次同样的内容。更干净的做法是把它们拆到**两个通道**:

```rust
// 通道 1:全局广播,每 tick 序列化一次,发给所有客户端
struct GlobalPacket {
    tick: u32,
    server_time_ms: u64,
    scoreboard: ScoreboardSnap,    // 小,几十字节
    world_events: Vec<EventSnap>,  // 本 tick 触发的世界事件
    chat: Vec<ChatLine>,           // 这 tick 的广播聊天
}

// 通道 2:per-client,每个客户端独立的内容
struct ClientPacket {
    tick: u32,
    entities: Vec<EntitySnap>,     // AoI + priority 选出的 entity 子集
    // 注意:这里没有时钟,没有计分板——那些在 GlobalPacket
}
```

服务器每 tick 先序列化一份 `GlobalPacket`(代价低,因为全局状态小),发 N 次(N = 客户端数);然后给每个客户端独立序列化一份 `ClientPacket`,各自发。客户端两个通道都收,合并渲染。

broadcast 通道还能进一步优化成"真·multicast"——如果服务器和客户端之间的网络支持 UDP multicast(局域网或经过特殊配置的广域网),一份 `GlobalPacket` 由路由器复制给所有订阅者,服务器只发一次 syscall。这对超大规模 zone(EVE 1000 人同场)是关键省法。但公网 multicast 路由通常不支持,生产环境更常见的做法是让服务器把同一份 `GlobalPacket` 用一个循环 send_to 给每个客户端——这是一次序列化 + N 次发送,序列化开销摊薄到 N 上,依然比"每客户端独立序列化"省。renet 这类库通常提供 "broadcast message" 接口,就是干这件事。

per-client 通道不能 broadcast,这是显然的——每个客户端的 `ClientPacket` 内容都不同。但 per-client 的序列化有共享的中间结果可以缓存:比如 delta 计算需要"上次发给这个客户端的版本",这是 per-client 状态;但"这个 entity 这一 tick 的当前快照"对所有客户端都一样,可以预先算好,所有客户端共享。一个常见优化是**两阶段序列化**:第一阶段,把每个 entity 序列化成"绝对字节流"(per-entity 一次);第二阶段,per-client,根据"上次发的内容"算 delta。第一阶段的结果是共享的,缓存起来,N 个客户端只算一次。

## 6 · 生产现实:EVE 和 Planetside 是怎么撑起 1000 人同场的

讲到这里,我想让你感受一下这套架构在工业级生产里有多关键。MMO 和大规模 live game **不存在不靠 interest management 活着的**——EVE Online 单场战斗 1000+ 玩家同场,Planetside 2 单地图 600+ 玩家同场,Fortnite battle royale 100 玩家、Apex 60 玩家,这些游戏的服务器如果不做 AoI,带宽和 CPU 会在前 50 个玩家连进来时就死。

EVE 是一个特别的案例研究。它的"大战役"(fleet battle)动辄 1000+ 玩家挤在一个 solar system 里。每个玩家的飞船是一个 entity,加上无人机、导弹、空间站,entity 总数轻松破万。如果服务器把每个 entity 发给每个玩家,1000 玩家 × 10000 entity × 1Hz × 几十字节 = 几百 Gbps 上行,不可能。EVE 的解法是**激进的 time dilation + AoI**:战斗激烈时,服务器把这个 solar system 的 tick rate 从 1Hz 降到 0.1Hz(time dilation,玩家感知为"子弹时间",所有动作都变慢但保持一致),同时 AoI 严格按"视距 + 雷达范围"筛,一个玩家只收得到 100-200 个 entity 的状态。这样即便 1000 玩家同场,服务器总流量是 1000 × 200 × 1 字节/秒级别 = 几 MB/s,可控。EVE 团队在 GDC 上多次讲过这套架构,是 MMO interest management 的教科书案例。

Planetside 2 是另一个经典。它是一个 FPS,但单地图 600 玩家同场,这在 FPS 里几乎独一无二。它的服务器把地图切成 region,每个 region 内的 entity 互相可见(走 AoI),region 之间的 entity 默认不可见——只有当玩家走到 region 边界,新 region 的 entity 才进入兴趣集合。这套"region 边界 + 内部 AoI"的两层结构,让 600 玩家分散在几十个 region 里时,每个玩家只关心自己所在 region 的几十个 entity,FPS 的实时性需求(30-60 Hz 同步)依然能满足。Planetside 的工程师在 GDC 2014 讲过他们的 netcode,其中 priority accumulator 部分讲得非常详细——"近处的玩家比远处的优先,开火的玩家比没开的优先,受伤的玩家比没受伤的优先",每一条都是一个 priority 因子。

这两款游戏说明一个事实——**大规模 live game 的生死,90% 取决于 interest management 做得好不好**。游戏机制再好、画面再美,服务器撑不起规模,玩家进不去、进去就卡,游戏直接死。反之,EVE 这种画面"简陋"到 2026 年看像 2005 年的游戏,因为 1000 人同场能跑,二十年活下来还有稳定玩家群体。这就是为什么这一篇值得花一节专门讲生产案例——它不是"以后优化",是架构级的生死问题。

## 7 · 在你 HH 项目里动手(做中学红线)

理论讲完,做中学开始。这一节的目标是:在你 [09E-2](09E-2-authoritative-server-and-state-sync.md) 已经搭好的权威服务器上加三件东西——一个 uniform grid、一个 per-client 兴趣集合、一个简单的 priority 选择器。然后用大量 entity 做负载测试,亲眼看到"带宽跟视距走,不跟总 entity 数走"。

**第一步:给 09E-2 的 GameState 加一个 spatial grid**。

复用 §2 那个 `SpatialGrid`。把它放到 `hh_core` 里(它和渲染层共享),每 tick step 之后调用 `rebuild`。这一步的 commit message 写 "add spatial grid to server, query_circle for interest"。

```rust
// hh_core/src/spatial.rs(新增文件,或加到现有 spatial 模块)
use std::collections::HashMap;

#[derive(Hash, Eq, PartialEq, Copy, Clone, Debug)]
pub struct GridCell { pub x: i32, pub y: i32 }

pub struct SpatialGrid {
    cell_size: f32,
    cells: HashMap<GridCell, Vec<u32>>, // Vec<EntityId>
}

impl SpatialGrid {
    pub fn new(cell_size: f32) -> Self {
        SpatialGrid { cell_size, cells: HashMap::new() }
    }
    pub fn rebuild(&mut self, entities: &hh_core::Entities) {
        self.cells.clear();
        for (id, e) in entities.iter() {
            let cell = self.cell_of(e.pos);
            self.cells.entry(cell).or_default().push(*id);
        }
    }
    fn cell_of(&self, pos: hh_core::Vec2) -> GridCell {
        GridCell {
            x: (pos.x / self.cell_size).floor() as i32,
            y: (pos.y / self.cell_size).floor() as i32,
        }
    }
    pub fn query_circle(&self, center: hh_core::Vec2, r: f32)
        -> Vec<u32>
    {
        let r_cells = (r / self.cell_size).ceil() as i32;
        let cc = self.cell_of(center);
        let r2 = r * r;
        let mut out = Vec::new();
        for cx in cc.x - r_cells ..= cc.x + r_cells {
            for cy in cc.y - r_cells ..= cc.y + r_cells {
                if let Some(ids) = self.cells.get(&GridCell { x: cx, y: cy }) {
                    for &id in ids { out.push(id); }
                }
            }
        }
        out // 注意:这是矩形窗口,调用方要再做精确圆筛
    }
}
```

注意 cell_size 怎么选——你 HH 的视距如果是 50 米,cell_size = 50;3×3 查询窗口正好覆盖视距。

**第二步:给 Server 加 per-client 的 ViewerContext**。

每个连进来的客户端有一个 `ViewerContext`,记录它的位置、视距、owned entity。位置每 tick 从客户端最近输入推得(或者用上一 tick step 之后的位置,简化教学):

```rust
struct ViewerContext {
    client_id: u64,
    addr: SocketAddr,
    pos: hh_core::Vec2,
    view_radius: f32,
    owned: Vec<u32>,
}

struct Server {
    state: hh_core::GameState,
    spatial: SpatialGrid,
    viewers: Vec<ViewerContext>,
    socket: UdpSocket,
    // ... 09E-2 已有的字段
}
```

`view_radius` 设成 50 米(或者你游戏摄像机看得到的距离)。`owned` 通常是这个客户端控制的角色 ID 列表——单角色游戏就一个元素。

**第三步:把 09E-2 的 broadcast 改成 per-client AoI 发送**。

这是核心改动。原来的:

```rust
// 09E-2 旧代码——broadcast 全量
let snap = self.snapshot();  // 全部 entity
let bytes = bincode::serialize(&snap).unwrap();
for (_id, addr) in &self.addrs { let _ = self.socket.send_to(&bytes, addr); }
```

改成:

```rust
// 9E-3 新代码——per-client 兴趣裁剪
self.spatial.rebuild(&self.state.entities);
for viewer in &self.viewers {
    let candidate_ids = self.spatial.query_circle(viewer.pos, viewer.view_radius);
    // 精确圆筛 + 合并 owned
    let mut interest: Vec<u32> = candidate_ids.into_iter()
        .filter(|id| {
            let e = &self.state.entities[id];
            (e.pos - viewer.pos).length_squared() <= viewer.view_radius.powi(2)
        })
        .collect();
    for &owned_id in &viewer.owned {
        if !interest.contains(&owned_id) { interest.push(owned_id); }
    }
    // 序列化兴趣集合(复用 09E-2 的 EntitySnap 量化)
    let entities: Vec<EntitySnap> = interest.iter()
        .map(|id| entity_to_snap(&self.state.entities[id]))
        .collect();
    let snap = SnapshotPacket { tick: self.state.tick, entities };
    let bytes = bincode::serialize(&snap).unwrap();
    let _ = self.socket.send_to(&bytes, viewer.addr);
}
```

这一步的 commit message 写 "replace broadcast with per-client AoI culling"。

跑两个客户端测试,你应该看到——**两个客户端在不同位置,收到的快照内容不同**。客户端 A 站在城东,他的快照里只有城东的 entity;客户端 B 站在野外,他的快照里只有野外的 entity。这是 AoI 第一次显现威力的瞬间。

**第四步:加一个简单的 priority 选择器 + per-client 预算**。

`ClientPriority` 用 §3 的实现。给每个 `ViewerContext` 配一个 `budget_bytes_per_tick`,设成 1500(一个 MTU,避免 IP 分片)。当兴趣集合序列化后超过 1500 字节,priority 队列选 top-K 发出去:

```rust
let mut prio = self.client_prio.get_mut(&viewer.client_id).unwrap();
let to_send = prio.select_for_send(
    &interest, viewer.pos, &self.state.entities, self.state.tick,
);
let entities: Vec<EntitySnap> = to_send.iter()
    .map(|id| entity_to_snap(&self.state.entities[id]))
    .collect();
```

这一步的 commit message 写 "add priority accumulator with anti-starvation"。

**第五步:负载测试,验证带宽跟视距走,不跟总 entity 数走**。

这是这一节最重要的实验,亲眼看到 AoI 的效果。写一个测试脚本,在地图上随机生成 N 个 entity(N 从 100 到 5000),让一个客户端站在地图中央。然后跑服务器,用 `tcpdump` 抓服务器发给这个客户端的流量:

```bash
# 终端 1:启动服务器
cargo run --features headless --bin hh_server -- --entities 100

# 终端 2:抓包,统计每秒发到客户端 5001 的字节数
sudo tcpdump -i lo -nn 'udp and dst port 5001' -c 10000 \
  | awk '{sum += length} END {print "bytes/pkt avg:", sum/NR}'

# 客户端连进来后,跑 30 秒,看每秒字节数
# 然后改 --entities 5000,再跑一遍,客户端站在同一位置
```

你应该看到的对比:

- N=100,view_radius=50:客户端收到 ~100 entity 的字节(全部)
- N=5000,view_radius=50:客户端收到 ~30-50 entity 的字节(只有附近的)
- **N 从 100 涨到 5000,客户端收到的字节数基本不变**——这是 AoI 的根本胜利

再做一组实验——**固定 N=5000,改 view_radius**:

- view_radius=30:收 ~20 entity
- view_radius=50:收 ~50 entity
- view_radius=100:收 ~150 entity
- view_radius=500:收 ~5000 entity(几乎全部,视距超过地图)

**字节数跟 view_radius 的平方走**(因为圆面积 ∝ r²),这是 AoI 的可预测性——你能从设计参数直接算出带宽预算,不用"调一调看"。

**第六步(可选进阶):加 netem,在差网络上验证 priority 的反饥饿**。

```bash
# 给 lo 加 200ms RTT + 5% 丢包
sudo tc qdisc add dev lo root netem delay 100ms loss 5%
cargo run --bin hh_client
# 观察:某些 entity 因为丢包错过更新,几个 tick 后 priority 累积,
# 被强制重发——客户端看到的远处怪不会永远卡在旧位置
sudo tc qdisc del dev lo root
```

**做完这一节,你应该 commit**。提交信息可以写 "implement AoI replication with spatial grid and priority accumulator, validate bandwidth scaling"。这是你 HH 项目里"网络化"的第二个里程碑——你的服务器现在能 scale 到几十人,带宽只跟视距走,这是 MMO 和大规模 live game 的工程门票。

## 8 · 练习

练习一(Lv1,概念辨析)。你的同事说:"我们游戏只有 4 人联机,entity 也就几十个,AoI 是过度工程,直接 broadcast 就行。" 写 200 字以内,讲清楚他在什么前提下的对的、什么前提下错的。提示:如果未来加 8 人模式?如果游戏改成开放世界?如果移植到移动端?broadcast 的"省事"在什么规模下会变成"卡到没法玩"?

练习二(Lv2,动手实践)。完成 §7 的前三步——spatial grid、ViewerContext、把 broadcast 改成 per-client AoI。两个客户端连进来,各自站在地图不同区域,`tcpdump` 抓两个客户端各自收到的字节数,确认两个数字**不同**,且都远小于"全部 entity 序列化的字节数"。提交 commit,把抓包数据贴在 PR 描述里。

练习三(Lv3,负载测试 + 可视化)。完成 §7 第四、五步——加 priority accumulator + 负载测试。写一个 Rust 测试,跑 N=100/500/1000/2000/5000 五档 entity 数,记录每客户端每秒收到的字节数,把数据 dump 成 CSV。用 `gnuplot` 或 `python -m matplotlib` 画一张图:x 轴是 entity 总数,y 轴是每客户端每秒字节。你应该看到一条**水平线**——这是 AoI 的视觉证据。然后画第二张图:固定 N=5000,改 view_radius,x 轴 view_radius,y 轴字节数,你应该看到一条**抛物线**(r² 关系)。把两张图放进 commit message。

练习四(Lv4,系统设计)。给你 HH 的服务器加 **per-client bandwidth budget 配置**——客户端连进来时,在握手包里报告自己的带宽(模拟值,比如 mobile=30KB/s,pc=100KB/s),服务器把这个值存进 ViewerContext,priority accumulator 用它当 `per_tick_budget_bytes`。测试:同一个服务器,两个客户端一个"假装 mobile"、一个"假装 pc",验证 mobile 客户端收到的字节数确实更少,但 priority 保证它**至少**每秒能收到每个 owned entity 一次(owned 反饥饿)。这个练习做完,你的服务器就有了"自适应带宽"的雏形——这是商业 netcode 库(renet / Nakama)的核心 feature 之一。

## 9 · 延伸阅读与下一篇

Glenn Fiedler 的 Gaffer on Games 系列里,《State Synchronization》和《Snapshot Interpolation》两篇是这一篇的直接基础(也是 09E-2 的祖师爷),网上直接搜得到。讲 interest management 最系统的工业资料是 Planetside 2 工程师在 GDC 2014 的 talk "Planetside 2 Network Architecture",里面详细讲了 region 划分、priority 因子、bandwidth shaping——读完你会对"大规模 FPS 怎么做 AoI"有第一手直觉。EVE Online 团队多次在 GDC / EVE Fanfest 上讲他们的 time dilation + AoI 架构,搜 "EVE Online server architecture GDC" 能找到 talk 视频,是 MMO interest management 的最佳案例研究。Jason Gregory 的《Game Engine Architecture》第三版网络章节里有一节专门讲 "Relevance / Priority",把这一篇 §3 的 priority accumulator 数学模型化,值得精读。

本仓库内的相关内容:[09E-1](09E-1-reliable-udp-transport.md) 是这一篇的传输层前置,本篇所有 UDP 假设走它给的可靠通道;[09E-2](09E-2-authoritative-server-and-state-sync.md) 是这一篇的直接前置,本篇的所有改动都是"在 09E-2 的服务器上加东西"——量化、delta、bitfield 都来自那里;[09B-1](09B-1-game-loop-and-timestep.md) 的固定步长是服务器侧 `step` 的正确性基石,AoI 不改变这一点;[phase-5/network-multiplayer-models](../phase-5/deep-dives/network-multiplayer-models.md) 是这一篇所在大厦的鸟瞰图,本篇是其 "state sync / AoI" 分支的深挖;[phase-6/spatial-acceleration](../phase-6/deep-dives/spatial-acceleration.md) 是 §2 那个 `SpatialGrid` 的完整推导,uniform grid / BVH / quadtree 的选型和性能数据都在那里;[phase-7/navmesh-and-pathfinding](../phase-7/deep-dives/navmesh-and-pathfinding.md) 里的 region / zone 概念,是 §5 / §6 那种"region 边界 AoI"的设计灵感来源,大规模 MMO 的多层 interest 结构都借鉴自 zone 划分。

下一篇 [09E-4](09E-4-matchmaking-nat-relay-lobby.md) 会从这一篇的"服务器已经能跑规模"出发,讲客户端怎么**找到**这台服务器——matchmaking(匹配)、NAT traversal(NAT 穿透,家用路由器后面的客户端怎么互相连上)、relay server(中继服务器,当 P2P 不通时fallback)、lobby system(房间系统)。如果说 09E-2 讲的是"权威服务器怎么跑得对"、9E-3 讲的是"权威服务器怎么跑得起规模",09E-4 讲的就是"玩家怎么找到并连上这台权威服务器"——这是把前面三篇的"已经能跑的服务器"变成"玩家点一下匹配就能玩的产品"的最后一公里。
