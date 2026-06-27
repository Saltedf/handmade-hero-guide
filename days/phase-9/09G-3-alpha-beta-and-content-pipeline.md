---
phase: 9
sequence: "9G"
module: 3
title_en: "Alpha, Beta & the Content Pipeline"
title_zh: "Alpha、Beta 与内容量产管线:从"做好一段"到"做好整部""
type: deep-dive
difficulty: 4
duration: "3-4 小时"
domains: [rust, engineering, game, production, process]
prereqs: ["09G-2-vertical-slice"]
calibration: "制作阶段(Alpha/Beta/Gold)+ 内容量产管线 + bug triage"
---

# 09G-3 · Alpha、Beta 与内容量产管线

## 0 · 你做完了一段,现在要做一百段:大多数项目死在这里

把你拉回 [09G-2](09G-2-vertical-slice.md) 走完的那个时刻。你手里有一段垂直切片(vertical slice)——打磨过的关卡、跑通的核心循环、配齐的美术音频。三个朋友玩完说"这个挺有意思"。这段证明了**你能做出好游戏**。

然后你打开 GDD(game design document)开始数:切片 1 个关卡,GDD 是 30 个;切片 3 种敌人,游戏要 25 种;切片 1 小时,游戏要 15 小时。**你要把那个让你累趴下的切片再做大约一百次**。这"再做一百次"不是体力活,是一个完全不同的工程难题,叫 **production(量产)**。绝大多数 indie 项目不是死在原型阶段,而是死在这里——原型惊艳、demo 前途无量,进入 production 六个月后精疲力竭、资金烧光、内容只完成 20%、彼此甩锅,项目悄悄取消。这种死法常见到有名字:**production death(量产死亡)**。

量产难的本质是 **scaling(放大)**,而放大暴露原型阶段被掩盖的一切问题:资产管线(asset pipeline)做一关没问题,一百关时 `assets/` 几千文件、美术改一个模型要重新 cook、看一眼效果等 90 秒;bug tracker 原型阶段 20 个脑子能记住,production 时 800 个装不下;feature 列表本该冻结,但制作人每天有"一个好主意",三个月后多出 15 个没做完的系统。每一项单独不致命,叠在一起就是慢性毒药。

这一篇讲怎么在量产活下来。它有一条工业里叫**制作阶段(production stages)**的故事线:从切片走出来,依次穿过 **Alpha、Beta、Gold**。每个阶段不是时间点,是**纪律(discipline)的转变**——能感知这种转变、在正确时刻切换纪律的团队活下来;把 Alpha 的"做新东西"心态带进 Beta 的团队要么 ship 不了,要么 ship 出去一坨。讲完阶段,深挖贯穿量产的两条命脉——内容量产管线和 bug triage/playtesting——最后到 Gold,准备进入 [9G-4](09G-4-certification-and-trc.md) 认证(cert)和 [9G-5](09G-5-gold-and-post-launch.md) 母版制作。

## 1 · Alpha:feature complete —— "所有东西都在,但都很丑"

Alpha 的核心定义是 **feature complete(功能完成)**:游戏里**每一个设计里有的 feature 都已实现并且可达(reachable)**,玩家能从开始到结束完整玩通,不需要"占位符"跳过未实现段落。但**完整可玩不等于好看、好玩、平衡**。Alpha 可以是灰模(graybox,纯灰色方块搭的关卡占位)、临时音效(用嘴配音、桌角敲击当打击音)、严重失衡的数值、bug 满天飞。Alpha 不解决"好不好",只回答:**"这游戏在功能上'是它自己'了吗?"**

打开 Alpha build 你会看到:主菜单是程序画的占位 UI——白底黑字 Arial;点开始游戏被扔进一片灰色立方体的关卡,美术没碰过;但敌人 AI 工作(能打、能反击、能死),任务系统工作(日志更新、完成条件触发),存档工作(退出再进、进度还在)。打通第一关过场动画播放——动画是 placeholder,人物站那不动,但**剧情文本是最终的**。一路打到最终 boss——攻击模式都在,数值瞎填,你一招秒它或它卡死你,但**你能打到结局**。这就是 Alpha:功能都做了,但都没打磨。Alpha 真正的含义就是这个纪律硬转折:**从这一刻起,不再加新 feature**——Pre-alpha 是"我还在想游戏要有什么",Alpha 之后是"游戏要的东西我都知道了,现在把它们做好"。打破它的代价惨重,而打破它的诱惑又极强——这张力叫 **feature creep(功能蔓延)**,是 Alpha 的核心矛盾。

feature creep 杀项目的机制具体到能看见。Alpha build 出来你自己玩,觉得"要是有个钓鱼 minigame 就好了"——想法本身好。花一周做钓鱼,然后"有钓鱼就得有鱼竿升级树"又一周,"有升级树就得有材料、采集系统"又两周。一个月后钓鱼系统做完,但你该用来 polish 战斗系统的那个月没了;新系统引入 40 个 bug,和已有系统产生没预料的交互(钓鱼时被攻击游戏卡住),再花一个月修。三个月后 release date 推迟三个月,但新加的钓鱼和核心乐趣无关——玩家为战斗来,钓鱼是 nice-to-have。**feature creep 的本质是用"做新东西"的快感逃避"打磨已有东西"的痛苦**:ship 出去的游戏质量 99% 取决于打磨,不取决于 feature 数量。

职业团队对抗它的武器:**一个被签字冻结的 feature list,以及"任何新 feature 都要走 change request 流程"的纪律。** Alpha 评审会上把"游戏将包含的功能"列成清单,团队所有人签字,清单上没有的 ship 前不准做。某人真想到必须加的走 change request(CR):写提案说明给玩家什么价值、估工时、对哪些已有系统有何影响;被接受的 CR 必须**从某已有 feature 那里挪预算**——要回答"为了加这个你打算砍什么"。这纪律听起来官僚,但就是 AAA 能按时 ship 的原因;indie 没这套纪律,所以大量 indie 的"六个月计划"变"三年烂尾"。

Alpha 还有个常被忽视的工程意义:**它是你 9A 测试网 [09A-4](09A-4-fuzz-determinism-and-regression.md) 真正发挥作用的时候**。原型阶段回归测试(regression test)网只能抓几个 bug;到 Alpha 代码几万行,任何一处改动都可能破坏十几个地方——调了角色控制器的跳跃曲线无意中破坏了 wall jump,而 wall jump 又被某关 puzzle 依赖。这种"看不见的耦合"在 Alpha 爆炸式增长,只有密集回归测试能在进 main 前拦下来。所以 Alpha 潜规则:**任何新 bug 必须配一个新测试**——修了跳跃 bug 就写一个 property test 验证边界,这样 bug 不只是被修,它被钉死了。

退出标准(exit criteria)?工业里有个朴素检验:**让你妈(或任何不玩游戏的朋友)从开始玩到结局,不需要你介入调试。** 她可能死很多次、卡关、看不懂 UI,但**不需要你按 F1 输 cheat 跳关、改配置、在控制台敲命令绕过崩溃**。她需要你介入才能玩通,说明功能没 complete。退出 Alpha 那一刻,你**向自己证明这款游戏是完整产品,只是还没打磨**。

## 2 · Beta:content complete —— "所有内容都做完了,现在的工作是把它们修好"

跨过 Alpha 进入 Beta。定义是 **content complete(内容完成)**:游戏里**所有最终内容(final content)都已放进去**——所有关卡用最终美术摆、所有敌人是最终建模、所有 UI 是最终设计、所有音乐最终录音、所有文本最终翻译、所有过场最终动画。从开头到结局**整个体验就是玩家最终会体验到的体验**,不再有任何 placeholder。

Beta 和 Alpha 的区别不在"内容多了多少",而在一个根本转变:**工作种类的转变**。Alpha 主要"做新东西",Beta 主要"修已有东西"(修 bug、调数值、磨 polish、删冗余)——Alpha 是创造者(creator),Beta 是修复者(fixer)。这身份转变对主创型开发者极痛苦,"反复磨已有东西"对他们是煎熬。所以很多 indie 卡在 Alpha→Beta 过渡:拒绝接受"创造阶段结束了、现在是修复阶段",继续偷偷加新东西,项目永远进不了真正 Beta。

Beta 的核心矛盾是:**内容做完了,但内容不对**。三大类问题。**第一类 bug**:Beta build 跑一遍几百个 bug——掉出地图、UI 错位、敌人卡住、任务无法完成、过场不同步、存档损坏。Alpha 时没法发现,内容不全测不到这些路径;Beta 内容全了玩家所有路径打开,水下 bug 全冒出来。数量会让团队恐慌("做了一年怎么还 800 个?")但这恐慌正常,Beta 就是这样:不是"bug 少"的阶段,而是"bug 多到能开始系统处理"的阶段。**第二类平衡(balance)**:Alpha 数值瞎填,Beta 所有武器、敌人、关卡难度曲线都要重调。但调平衡是**多人多次 playthrough 才能暴露的问题**——你自己测太熟什么怪都打不过你,给朋友玩第一关就被秒。balance 不是数学问题是经验问题,需大量 playtesting(§6 细讲)。**第三类节奏(pacing)**:Alpha 测单关,关和关之间过渡没测。Beta 内容齐了从头打到尾,你突然发现第二三关难度跳三级、第七关后连续五关没新机制玩家无聊、剧情高潮在游戏 40% 处后 60% 都在收尾。这些**结构性问题**只有 Beta 玩通一遍才看见,修复往往意味重做段落——这就是为什么管线迭代速度在 Beta 如此关键。

Beta 退出标准?**bug 率(bug rate)降到可接受的低水平**。没绝对数字,工业经验法则:ship 出去的游戏玩家平均每小时遇到的"明显 bug"应少于 1 个。Beta 早期可能每小时 5-10 个;后期压到 1 以下,就可以考虑进入 cert([9G-4](09G-4-certification-and-trc.md))了。

把 Alpha 和 Beta 的纪律差异再强调一遍,这是这一篇最重要的 take-away。**Alpha 纪律是"做且只做清单上的功能"**,对抗 feature creep;**Beta 纪律是"不再做新功能,只修和磨"**,对抗完美主义和倦怠。Alpha 杀手是 feature creep,Beta 杀手是"我不忍心 ship,我还能再改一版"。职业纪律告诉你是时候 ship 了——**好的 ship 永远早于完美的 ship,完美主义是另一种形式的烂尾**。

## 3 · 内容量产管线:为什么慢的工具会杀死你的 Beta

深挖贯穿量产的物理命脉——内容量产管线(content pipeline)。定义:**内容(美术资产、关卡数据、音频、文本)从创作者手里(DCC 软件:Blender、Photoshop、Audition、Tiled)到游戏里运行形式,这条完整路径上所有转换、导入、验证、cook 步骤**。垂直切片([09G-2](09G-2-vertical-slice.md))你看不见它的痛——内容少手工 export、拷进 `assets/`、加载,完事。内容一多这条路径就变成项目能不能 ship 的物理瓶颈。**慢的工具杀死 Beta,这话不是夸张。**

看具体场景。美术在 Blender 调了角色模型肩部拓扑,想看改动在游戏跑起来什么样。她操作序列:Blender export 成 `.glb`,跑一次 cook(转运行时格式、生成 mipmap、压缩贴图、build vertex buffer),拷进 `assets/`,重启游戏,加载到要看那帧。一切顺利 60 秒。糟糕的是 cook 时间 8 分钟——4K 贴图的 BC7 压缩(高质量块压缩,压一张 4K 贴图 30-60 秒),几十张串行 8 分钟。一次迭代 8 分钟一天十次 80 分钟纯等。问题不只是"等"——等待让她失去心流(flow),做完一次改动、等 8 分钟、心流断、刷手机、回来忘了之前在调什么。8 分钟迭代循环的美术产能大约是 1 分钟循环的 1/4,不是 1/8——心智切换成本比等待本身更致命。更阴险的是慢工具让团队**规避必要迭代**:美术知道改一次等 8 分钟,下意识"算了这改动不重要",大量该做的 polish 没做——肩部穿模、贴图接缝、动画抖动,每个都是"本想再调一次但 cook 太慢"的牺牲品。**慢工具不直接杀项目,它让团队有效工时腰斩,你以为只是"美术效率有点低"。content pipeline 的速度,直接决定你游戏的 polish 上限。**

职业团队把 pipeline 做快有四条核心策略。

**第一条,增量 cook(incremental cook)。** cook 不应每次重 cook 所有资产——应知道哪些改过(用 mtime 或 content hash),只 cook 改过的。Rust 里用 `cargo` 的 `rerun-if-changed`(build script 里 `println!("cargo:rerun-if-changed=assets/hero.png")`)。单独这一条把"8 分钟"压到"30 秒"。是工程纪律不是黑科技,但 indie 大量不做因为"我手动只 cook 改过的就行"——人会忘,手动 cook 容易漏。

**第二条,后台 cook + hot reload。** 美术改完不需要"重启游戏"才看效果——游戏应有 file watcher 监视 `assets/`,一旦某资产更新自动重新加载,美术**实时看到变化**。这是 [phase-7 资产管线架构](../phase-7/deep-dives/asset-pipeline-architecture.md)讲的 hot reload 的核心价值。实现它需要支持运行时重载的引擎架构——资产不能 build-time 烤死,而是运行时通过 asset handle 间接引用,handle 背后可在运行时被替换。这种架构改造最好垂直切片之前做完,Beta 再改架构是噩梦。核心模式是双层 Arc——`Arc<RwLock<Arc<T>>>`:

```rust
use std::sync::Arc;
use parking_lot::RwLock;

/// 一个可在运行时被原子替换的资产句柄
pub struct AssetHandle<T> {
    inner: Arc<RwLock<Arc<T>>>,  // 外层 RwLock 让我们换内层 Arc
}

impl<T> AssetHandle<T> {
    /// 拿当前版本(Arc 廉价 clone,持有直到用完自动释放)
    pub fn get(&self) -> Arc<T> { self.inner.read().clone() }

    /// 写锁下替换内层 Arc。**这一刻所有持有旧 Arc<T> 的代码
    /// 仍用旧版本(它们有自己的 clone),但下一次 get() 拿到新版本**。
    /// 这种"已借出的不变、新借出的更新"的语义,
    /// 是 hot reload 不破坏正在运行的帧的关键。
    pub fn swap(&self, new: Arc<T>) { *self.inner.write() = new; }
}
```

外层 `RwLock` 让我们换内层 `Arc`,内层 `Arc` 让所有持有 handle 的代码共享同一份资产。配合 `notify` crate(文件系统监听事实标准)起后台线程监视 `assets/`,任何文件改动触发一次单资产 re-cook——成功 swap handle,失败(美术正在 export、文件写一半)warn 一声等下次事件再试。

**第三条,异步并行 cook。** cook 是 CPU 密集的(贴图压缩、网格优化),应用所有核。Rust 的 `rayon` 让这事极简——cook 写成"对一个资产的函数",然后 `assets.par_iter().map(cook_one).collect()`,rayon 自动用所有核并行。16 核机器 cook 从 8 分钟压到 30 秒。但要小心:并行 cook 要求每个资产 cook **独立**,如果"角色纹理"依赖"骨骼"的 cook 它们不能并行,你要么剥依赖要么按依赖图分层 cook。

```bash
# 用 cargo 装 cook 工具,Arch 上多核 cook
sudo pacman -S --needed base-devel
cargo install --path tools/cook
cook --jobs $(nproc) --incremental assets/   # 满核 + 增量
```

**第四条,把 cook 跑进 CI。** 接上 [09F-1](09F-1-ci-cd-and-build-engineering.md)——CI 里 asset-check job 不应只检查"资产文件存不存在",还应**真的跑一次 cook**验证所有资产都能 cook 过。美术提交格式微小错误的 `.glb`,本地 cook 可能容错跑过,但某平台 cook 不过——CI 三平台都跑 cook 立刻暴露。

四条加起来,内容管线就有了职业级最小骨架:**增量 cook + hot reload + 多核 + CI 验证**。这套骨架垂直切片阶段就要建好,Beta 被真实量产压力 stress-test。有这套骨架的团队 Beta 美术一天迭代 40 次;没有的一天 5 次——后者六个月的量产计划前者两个月做完。

## 4 · 内容验证:一百个关卡意味着一千个出错的可能

讲完管线速度,讲管线的**正确性**。垂直切片做 1 关你肉眼检查;Beta 阶段 30 关你不可能肉眼检查每一个——一关里敌人 ID 写错(本该 `goblin_elite` 写成 `goblin_elite_typo`),你只有玩家走到那一关、发现没敌人(或崩了)才知道。数据驱动游戏 Beta 出错的大部分不是代码 bug,是**数据 bug**(引用断了、数值越界、枚举拼错)。

职业应对是**自动化内容验证(content validation)**:在 cook 流程或独立 `validate` 工具里对每个内容资产做静态检查(static check)——关卡 `enemy_spawn` 引用 `goblin_elite`,validate 去全局敌人表查,查不到直接 fail;武器 `damage` 是字符串而非数字,validate 检 schema 报错;NPC 对话树(dialogue tree)有死路径,validate 遍历对话图找孤立节点。骨架:

```rust
// tools/level-validate/src/main.rs(节选)
fn main() -> anyhow::Result<()> {
    let enemies: EnemyTable = ron::from_str(&std::fs::read_to_string("assets/tables/enemies.ron")?)?;
    let events:  EventTable  = ron::from_str(&std::fs::read_to_string("assets/tables/events.ron")?)?;
    let mut errors = 0;
    for entry in std::fs::read_dir("assets/levels")? {
        let path = entry?.path();
        if path.extension().map_or(true, |e| e != "ron") { continue; }
        let level: Level = ron::from_str(&std::fs::read_to_string(&path)?)?;
        for e in &level.enemies {                         // 引用必须解析
            if !enemies.enemies.contains(&e.enemy_id) {
                eprintln!("FAIL {}: unknown enemy_id '{}'", level.name, e.enemy_id); errors += 1; }
            if e.count == 0 { eprintln!("FAIL {}: spawn count 0", level.name); errors += 1; }
        }
        for t in &level.triggers {                        // 事件引用必须解析
            if !events.events.contains(&t.on_enter) {
                eprintln!("FAIL {}: trigger '{}' -> unknown event '{}'", level.name, t.id, t.on_enter); errors += 1; }
        }
    }
    if errors > 0 { eprintln!("{} validation errors, refusing to ship.", errors); std::process::exit(1); }
    eprintln!("All levels valid."); Ok(())
}
```

这工具的精髓:**替你做脑做不了的事**——扫所有关卡、检查所有引用、找所有孤立节点,人脑查 30 关几乎一定漏,脚本绝不漏。它就是 [09F-1](09F-1-ci-cd-and-build-engineering.md) 讲 CI 时提到的 asset-check job 的具体实现,跑在 CI 里每次 push 都验证。内容验证不只关卡,还覆盖:对话树(无死路径)、本地化文本(每个 string ID 所有语言都有翻译)、平衡数据(数值在合理区间)、UI 布局(元素不重叠)。叠在一起替你拦住 Beta 阶段 80% 的"低级错误"——而低级错误是最让玩家觉得"这游戏不专业"的。

## 5 · Bug triage:八百个 bug,你修哪一百个

Beta 阶段打开 bug tracker(职业用 Jira、Linear、或开源 Mantis、Bugzilla;indie 用 GitHub Issues 凑合),里面 800 个 bug。你不可能全修——剩下工程时间能修大概 200 个,另外 600 个怎么办?这是 **bug triage(分类/甄别)** 的核心:**在有限工时里,把 bug 修在"对游戏体验影响最大"的地方**。

第一步给每个 bug 标**严重度(severity)**,工业标准三级。**A 级(crash/blocker):** 崩溃、存档损坏、玩家无法继续(卡死、关键 NPC 消失)、平台合规问题。**必须修**,不修不能 ship——A 级出现在 ship 版意味玩家可能花钱买了玩不了,是退款和差评直接来源。**B 级(major):** 严重破坏体验但能继续——某武器完全没用(数值 bug)、某 boss 可卡墙角无伤打死、某关难度明显跳级、某 UI 在 16:9 之外比例错位。**应该修**,时间紧可接受 ship 时还有少量。**C 级(minor/polish):** 不影响体验的小瑕疵——贴图 1 像素接缝、NPC 远处 LOD 切换抖一下、对话标点用了中文逗号但游戏是英文版。**可以不修**,只要数量不爆炸。完美主义者的病是想把所有 C 都修了,结果 B 没修完。

severity 是客观属性。但 triage 还需另一维度:**优先级(priority)**——多紧急。一个 A 级 crash 但只在极罕见路径触发(最终 boss 战按 esc+tab+方向键组合),severity A 但 priority 中(概率低);反之一个 B 级但每个玩家第一关就遇(新手教程 UI 错位),priority 最高——影响每个玩家第一印象。triage 实际操作就是 severity × priority 排序,从最严重最常见那批开始修:

```rust
// tools/triage/src/main.rs(节选)
#[derive(Deserialize, PartialEq, Eq, PartialOrd, Ord)]
enum Severity { C, B, A }    // derive Ord: C<B<A,排序时 A 排最前
#[derive(Deserialize, PartialEq, Eq, PartialOrd, Ord)]
enum Priority { Low, Medium, High, Critical }
#[derive(Deserialize)]
struct Bug { id: String, title: String, severity: Severity, priority: Priority, fix_cost_hours: f32 }

fn main() -> anyhow::Result<()> {
    let csv = std::fs::read_to_string("bugs.csv")?;
    let mut bugs: Vec<Bug> = csv::Reader::from_reader(csv.as_bytes()).deserialize().collect::<Result<_,_>>()?;
    // severity 降序 → priority 降序 → fix_cost 升序(便宜的先修)
    bugs.sort_by(|a, b|
        b.severity.cmp(&a.severity).then(b.priority.cmp(&a.priority))
                  .then(a.fix_cost_hours.partial_cmp(&b.fix_cost_hours).unwrap()));
    let budget_hours = 200.0;                          // ship 前还有 200 工时
    let mut spent = 0.0;
    for b in &bugs {
        if b.severity == Severity::A { println!("[MUST]    {} {:.1}h", b.id, b.fix_cost_hours); spent += b.fix_cost_hours; }
        else if spent + b.fix_cost_hours <= budget_hours { println!("[SHOULD]  {} {:.1}h", b.id, b.fix_cost_hours); spent += b.fix_cost_hours; }
        // 超预算的 fall through 到"已知不修"
    }
    Ok(())
}
```

这工具不是替代人脑——目的是**强制团队把 triage 数据化**。每个 bug 有 severity、priority、估时,团队每周过一次清单,决定哪些 must-fix、哪些 maybe-fix、哪些 punt(明确决定不修)。punt 不是"忘了",是"我们看过这 bug、决定不修"——bug 不再是"还没人处理"的混沌,而是"已过评估、接受其存在"的明确状态。**从混沌到明确**的转变才是 triage 真正的价值。

triage 还有个反直觉但极重要的纪律:**允许"已知 bug ship"**。indie 常见灾难是"我不能 ship,还有 bug!"——这心态导致永远 ship 不出去,bug 数量永远不归零。职业纪律是:你**明确地**列出 ship 时会带着的已知 bug 清单(叫 **known shippables**),和 release notes 一起签字——每个都经过评估(B/C 级、概率低、修复成本高、修复风险大),所以接受它进 ship。**好的 ship 永远带着 known shippables;不 ship 的项目永远"我要再修一个 bug"。**

## 6 · Playtesting at scale:用数据告诉你哪里不对

讲完内部 triage,讲外部反馈。Beta 阶段你需要**外部 playtester**——不是团队里的人,是没参与过项目、对游戏一无所知的真实玩家。团队内部测试有不可消除的偏差:你太熟了,知道哪条路是"对的",不会卡在你设计时没意识到的死胡同。只有陌生玩家能暴露这种"设计者盲区"。

playtesting at scale 分两类。**定性 playtest** 是经典形式:招募 3-10 个目标玩家,给 Beta build 让他们在你面前玩,你不说话、不提示,只记录:卡在哪?什么时候露出困惑表情?什么时候说"我觉得该往左但其实该往右"?这些定性信号极宝贵——它们告诉你**为什么**玩家在某处体验不好。三条铁律:**不解释**(玩家卡住时你不能说"点右上角",让他卡,记录卡多久——这"卡多久"就是 ship 后是否加引导的依据)、**记录原始反应**(录屏+录音+观察笔记,事后回放)、**多样化样本**(别只招硬核玩家——一个休闲玩家在你"明显很简单"的关卡卡 20 分钟,这数据比 100 个硬核玩家通关时间更有价值)。

**定量 telemetry** 是另一条腿。telemetry 是**游戏内置的、自动上报的、玩家行为数据**——玩家在哪死(位置+死因)、哪卡了超 30 秒没移动(可能迷路或困惑)、哪个对话选项犹豫超 5 秒、哪一关退出游戏(潜在"挫败退出点")。本地 playtest 存本地文件,远程上报到简单 HTTP endpoint:

```rust
// 玩家死亡时埋点(异步 flush——永远不能阻塞游戏循环,60FPS 是硬指标)
pub fn on_player_death(state: &GameState, cause: &str, pos: [f32;3], level_id: &str, t: &mut TelemetryBuffer) {
    t.push(TelemetryEvent {
        kind: "player_death", level: level_id.into(),
        pos_x: pos[0], pos_y: pos[1], pos_z: pos[2],
        cause: cause.into(), play_time_sec: state.play_time.as_secs(),
        timestamp: chrono::Utc::now(),
    });
}
impl TelemetryBuffer {
    pub fn flush(&mut self) {
        if self.events.is_empty() { return; }
        let body = serde_json::to_string(&std::mem::take(&mut self.events)).unwrap();
        let endpoint = self.endpoint.clone();
        std::thread::spawn(move || { let _ = ureq::post(&endpoint).send_string(&body); });
    }
}
```

telemetry 工业级实现见 [phase-8 telemetry](../phase-8/deep-dives/telemetry-short.md)。telemetry 给你**聚合数据**——"玩家在第三关某走廊死 47 次"。3 个 playtester 已能看趋势,100 个能看统计显著模式。但 telemetry 只告诉你**哪里**,不告诉你**为什么**——为什么在那死 47 次?敌人太难?地形视线遮挡?控制方案不灵敏?telemetry 不能回答,定性 playtest 能。所以**定性+定量必须结合**:telemetry 定位,playtest 解释。把数据落到 triage——"走廊死 47 次"在 bug tracker 开一个 B 级,从此这 bug 不基于直觉,基于数据。**数据驱动的设计调整(data-driven design)** 是职业和业余的分水岭:业余凭感觉调,职业凭数据调。

## 7 · 从 Beta 到 Gold:bug 率、内容冻结、准备 cert

讲完 Alpha、Beta、管线、triage、playtest,到了量产最后一段——**从 Beta 走向 Gold**。Gold 是 production 终点:游戏母版(gold master)制作完成,准备交付平台方([9G-5](09G-5-gold-and-post-launch.md) 细讲)。Beta 到 Gold 不是某个时间点,是一段持续纪律:**bug 率持续下降、内容持续冻结、风险持续收敛**,路上你追踪三个数。

**第一个,Bug 收敛率(bug burn-down)。** 每周新发现 bug 数 vs 修复 bug 数,差是净减少率。Beta 早期新发现 > 修复(净增——越测越发现)、中期持平、后期修复 > 新发现(净减)。当总数降到阈值(工业经验:A 级=0、B 级<20、C 级不限),就准备好进入 cert 了。

**第二个,内容冻结(content freeze)的级别。** 你不是一次性冻结所有内容,而是分阶段:先冻**美术**(不再改模型贴图——美术团队解散或转做 trailer)、再冻**数据**(不再调数值,freeze 后任何调整走 CR)、再冻**代码**(code freeze,只允许修 bug 不允许重构)、最后冻**文本**(localization freeze,翻译团队拿最终文本做本地化,之后再改意味所有语言重译)。每次冻结让团队从"创造模式"切到"修复模式",这是 Beta 后期标志心态。

**第三个,playtest 满意度趋势。** 每次 playtest 后让玩家填简短问卷(推荐净推荐值 net promoter score,NPS——"你会向朋友推荐这游戏吗,0-10 分")。Beta 早期 NPS 可能 3,中期升 5,后期 7+。NPS 不是绝对科学的,但**趋势**有意义:连续三次在涨 polish 在生效;卡住不动甚至下降,polish 方向不对,要停下来反思。

到这三个数都达标,你进入 **release candidate(RC)** 阶段——build"准备 ship"的版本,跑全套 cert 检查([9G-4](09G-4-certification-and-trc.md)),过了就 Gold。RC 不是一次过的:通常 build RC1,cert 发现 5 个 TRC 违规,修了 build RC2 再过一遍发现 2 个,再修 RC3 过了。这个"RC→cert→修→RC"循环留到 [9G-5](09G-5-gold-and-post-launch.md) 详讲;这一篇只需知道:从 Beta 走出来,目标是**让这三个数收敛到可以开始 RC 循环的水平**。

## 8 · 在你 HH 项目里动手(做中学红线)

核心动作是**把你的垂直切片([09G-2](09G-2-vertical-slice.md))放大成一款游戏**,在放大中亲身经历 Alpha、Beta、triage、playtest。做完这些,你对"production 是什么感觉"就有了肌肉记忆。

**第一步,内容量产 5×。** 拿切片内容(假设 1 关卡、3 种敌人、2 件武器),用内容管线**复制扩展**到 5 关卡、15 种敌人、10 件武器——5 关卡是切片关卡当模板变体出 5 个布局,15 种敌人是 3 种基础的数值/外观变体,10 件武器是 2 种基础的数值变体。意义不在内容质量,在**让你感受内容量产的物理量**——5× 已能让你体会"一关时手工管,五关时手工管开始出错"。过程记录每次"内容错误"(某关引用不存在的敌人 ID、某武器填错字段、某关没 exit),这些就是 §4 内容验证要拦的对象。

**第二步,做最小化的内容管线改造。** 给 HH 项目加 `tools/cook` 子 crate(在 [09F-1](09F-1-ci-cd-and-build-engineering.md) 讲的 workspace 里),实现**增量 cook+多核**——增量用 mtime 判断哪些要重 cook,多核用 `rayon` 并行。产出 `cook` 命令跑 `cook --jobs $(nproc) --incremental assets/` 几秒 cook 完 5×。然后**再扩到 20×**,感受增量多核 cook 在更大规模的表现。

**第三步,加 hot reload。** 用 §3 示例思路给 asset 系统加文件 watcher+asset handle swap——美术(或你自己扮演)改贴图游戏不重启实时看到。做完回头再做第一步的内容量产,你会立刻感受效率差:**没 hot reload 改一次等几十秒,有 hot reload 立刻看到**。

**第四步,跑一次 bug triage。** 5× 或 20× 内容之后自己 playtest 几小时,记录每个 bug(GitHub Issues 或 CSV)。目标不是修,是**收集一批 bug 然后 triage**——给每个 bug 标 severity(A/B/C)和 priority(Low/Medium/High/Critical),用 §5 triage 工具思路(哪怕只 shell 排序)标 must-fix / maybe-fix / punt。产出是**数据化的 bug 清单**——bug 不再是一团混沌"还有好多事要做",而是明确"先做这 10 个 A 级、再做这 30 个高优先 B 级、剩下 50 个 C 级 punt"。

**第五步,招 3 个外部 playtester+收 telemetry。** 找三个不参与你项目的朋友(理想情况有一个完全不爱玩游戏的),给 Beta build 让他们玩,你只观察记录(定性)。同时游戏里埋最简 telemetry——玩家在哪死(pos+level),用 `serde_json` 序列化到本地文件即可。玩完把 telemetry 可视化(把死亡位置画在关卡俯视图上),你会看到某些点死亡密度明显高于其他。产出是**一次完整 playtest 循环:埋点→测试→数据→调整**。

做完五步,你的 HH 项目从"一段切片"长成"有量产压力的小游戏",你也亲身走过 Alpha(冻 feature)、Beta(量产内容+triage bug)、playtest(收数据)三个阶段的纪律转变。**这一篇的核心 take-away 不是某个具体技术,而是"在正确时刻切换纪律"的感觉**——这种感知能力就是职业制作人和 indie 烂尾者的本质差距。

## 9 · 练习

**练习一(难度 1),概念题。** 用你自己的话回答:(a) Alpha 和 Beta 的核心区别?为什么 Alpha 纪律是"不加新 feature"、Beta 是"不再做新功能"?各自对抗什么?(b) 为什么 feature creep 是 Alpha 杀手、完美主义/不忍 ship 是 Beta 杀手?给一个(假设的)项目失败案例,说明它死于哪一个。(c) 解释 severity 和 priority 的差别。给一个"severity 高 priority 低"和一个"severity 低 priority 高"的 bug 例子。

**练习二(难度 2),动手实践。** 完成 §8 第二步——给 HH 项目做 `tools/cook` 子 crate,支持 `--jobs` 和 `--incremental`。然后在 CI([09F-1](09F-1-ci-cd-and-build-engineering.md))里加 cook job 验证所有资产都能 cook 过。产出是被 CI 持续验证的内容管线——美术提交坏资产,CI 当天就红。

**练习三(难度 3),进阶工程。** 完成 §8 第三步的 hot reload。用 `notify` crate 监视 `assets/`,实现 §3 那段 asset handle swap。然后**实测迭代效率**:打开游戏改一个贴图,记录从改动到看到效果的时间;对比不开 hot reload 时。把两个数字写进开发笔记——它们会让你切身体会"为什么慢工具杀死 Beta"。想做更深版本,加"cook 失败时不替换旧资产"的容错机制——模拟美术正在 export、文件写一半的场景。

**练习四(难度 4),设计题。** 假设 HH 项目从你一人扩展成 8 人小工作室(2 程序、2 美术、1 设计、1 制作、1 QA、1 音频),进入 Beta,bug 数 400,内容已全部做完但 bug 满天飞。设计完整 production 流程:(a) triage 流程具体怎么跑?谁参与?多久一次会?(b) 内容管线怎么分配职责——美术怎么提交、cook 怎么跑、谁验证?(c) playtest 计划——多久一次?每次多少人?telemetry 埋哪些点?(d) 怎么决定什么时候从 Beta 进入 RC——具体到三个数字标准。写成两页文档,不需要代码。考你能不能把这一篇的概念综合成真实团队场景下的可执行流程。

## 10 · 延伸阅读与下一篇

production 阶段工程实践中文资料稀缺,值得读的主要是英文。**Tim Cain 的 GDC 演讲和 YouTube 系列**(Fallout 主创)对 production stages 有接地气的讲解,带着做 Fallout、Temple of Elemental Evil、The Outer Worlds 的血泪故事——尤其推荐他讲 feature creep 和 ship discipline 的几期。**Jason Schreier 的《Blood, Sweat, and Pixels》** 讲十个 indie/AAA 项目开发故事,每个都是 production death 案例研究——Stardew Valley 一人 4.5 年量产怎么活下来、又怎么差点没活;Uncharted 4 在 Beta 重做了大半游戏。**Game Developer(gamedeveloper.com,原 Gamasutra)的 postmortem 栏目** 是工业最有价值的反思资料库。

工程层面,**《Game Engine Architecture》by Jason Gregory**(Naughty Dog 主程)关于 asset pipeline 和 content tools 的章节是 AAA 工业级管线的圣经。**Bevy 引擎的 asset system 源码**(github.com/bevyengine/bevy 的 `crates/bevy_asset`)是 Rust 生态里 asset handle + hot reload 的事实参考实现,你 §3 写的 `AssetHandle<T>` 是它极简版,值得对照读 Bevy 完整实现。triage 方面 **Linear 和 Jira 的官方文档**关于 severity vs priority 的区分都讲得很清楚。

写到这里,9G 序列从"预制作"([9G-1](09G-1-preproduction-and-prototype.md),假设)、"垂直切片"([09G-2](09G-2-vertical-slice.md))走到了"量产"(这一篇)。你已经知道一个游戏从"一段切片"长成"一款完整游戏"要穿过 Alpha、Beta 两个纪律阶段,要靠一条能跑得动的内容管线,要靠数据化的 bug triage,要靠外部 playtest 和 telemetry 提供反馈。下一篇 [9G-4](09G-4-certification-and-trc.md) 离开"制作",进入"上架前最后一道闸"——**certification(认证)和 TRC/TCR**。平台方(Sony、Microsoft、Nintendo、Steam)有一份几百页的清单告诉你"做完"的标准:手柄必须能调到主菜单、存档满了必须给玩家警告、网络断了不能崩、待机恢复不能丢进度。下一篇就是这份清单怎么读、怎么过、怎么把 TRC 检查提前到 production 阶段就持续验证。
