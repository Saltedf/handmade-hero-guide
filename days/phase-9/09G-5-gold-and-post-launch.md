---
phase: 9
sequence: "9G"
module: 5
title_en: "Gold & Post-Launch"
title_zh: "Gold 母版与发售之后:从冻结那一刻到游戏的一生"
type: deep-dive
difficulty: 4
duration: "2.5-3 小时"
domains: [game, rust, engineering, ops, production, process]
prereqs: ["09G-4-certification-and-trc"]
calibration: "Gold 母版 + 上架 + 售后支持(live-ops)+ sunsetting/EOL"
---

# 09G-5 · Gold 母版与发售之后:从冻结那一刻到游戏的一生

## 0 · 认证通过的那一秒,你以为结束了

你在 9G-4 里熬过了 TRC / TCR / Lot Check,平台方那封"恭喜你通过认证"的邮件躺在收件箱里。你深吸一口气,把那一版构建——某个具体的 commit、某个具体的产物哈希——标记成了 **gold master**(金牌母版)。这一版不会再改了,它就是你卖给玩家的那个游戏。在 1990 年代,你会把这张母版刻进一张玻璃母盘,装进防静电袋,亲手交给压盘厂;今天,你点击"提交",几 GB 的二进制通过加密通道上传到平台方的服务器。仪式感淡了,但含义没变:**游戏定型了,它即将离开你的手。**

然后发售日(launch day)来了。商店页面从"即将推出"翻成"立即购买",玩家用你从未测过的显卡、从未想过的系统语言、从未设计过的操作习惯,同时涌入。服务器(如果游戏有联网,见 9E 与 09F-2)开始承受你压测时只敢想象的负载;Steam 评价区出现第一条差评;你的崩溃上报系统(09F-2 §4)在凌晨三点推了一条手机通知给你——某个 `particles::emitter::tick` 的崩溃,你 QA 从来没见过。前 48 小时是一场救火(firefighting),而这场火的燃料,是几千个你素未谋面的玩家。**工作没有结束,它换了一种形状。**

这一篇讲的就是那条"从 gold 到游戏一生终结"的完整生命周期:为什么 gold 是一种纪律而不是一个时刻、发售头几天会发生什么以及你拿什么去应对、发售之后游戏如何作为一项服务(game as a service)持续生长、怎么听遥测而不被遥测绑架、最后——一个游戏怎么体面地结束(sunsetting / EOL),以及为什么"结束"本身也是工程。把 9G-4 的"认证终点"接到 09F-2 的"live-ops 起点",再把这条线一直拉到一个游戏停止维护的那一天。Casey 的 Handmade Hero 从未走到这一步——它既没有 gold,也没有发售,更没有售后。**你拥有整个生命周期,这就是"专业"二字的全部重量。**

## 1 · "Going Gold":母版、签名、与"不再改"的纪律

先把 gold master 这个概念讲透,因为它常被误解成"发售日"的同义词。它不是。Gold master 是**最终构建**(final build):它是某一次具体的 CI 产出(09F-1),通过了完整认证(9G-4),被你用版本号、哈希、签名钉死,提交给平台方作为分发基准。发售日是另一件事——发售日是商店把这个 gold 母版对玩家可见的那一刻,通常比 gold 晚几天到几周(给市场预热、给平台排期、给物流铺货,在数字时代主要是给市场预热)。Gold 是工程意义上的"定型",发售是商业意义上的"开卖"。

历史上的"gold"来自压盘工业。光盘母版要用一种叫 gold master 的金属母盘压出来,这张母盘一旦开模,改一个字节就要重新开模,代价极高。所以"going gold"在心理上意味着**冻结**(freeze):你不再加功能、不再调平衡、不再修"看起来还行但其实不致命"的 bug。游戏就是它现在的样子,你接受它。这种"接受"是工程纪律,不是技术动作——任何工程师都能继续改,纪律在于你**选择不改**。

冻结的纪律具体落到几条操作上。第一,**代码冻结(code freeze)**:从 gold 那一刻起,main 分支不再接受任何新合并,除非是认证级别的 blocker。所有"我顺手再优化一下"的冲动都得按住。第二,**资产冻结(asset freeze)**:贴图、音频、关卡、本地化文本全部锁死,任何改动都要走"母版变更审批"。第三,**版本钉死**:gold 母版的版本号、commit SHA、构建产物哈希、签名证书指纹,全部记录归档。这套记录是你之后所有补丁、所有回滚、所有崩溃符号化(09F-2 §4)的基准——你三个月后回过头来修一个 gold 版本的 bug,你必须能精确还原"gold 那一天的构建环境"。这就是 09F-1 反复强调"可复现构建"的真正用意:可复现不是为发售那一天,是为了发售之后那一整年。

签名(signing)是 gold 母版在工程上最硬的一步。平台方要确认"这个二进制确实是你、而且没被篡改"。Windows 上是 Authenticode 代码签名证书(你得从 DigiCert / Sectigo 买一张,年费),签完之后 Windows SmartScreen 才不会用红色弹窗吓走玩家;macOS 上是 Apple Developer ID + notarization(公证),不公证的 app 在 Gatekeeper 面前直接拒跑;Linux 桌面对签名要求宽松,但你发布到 Flatpak / Snap 商店时同样要走签名链。主机平台更严:Sony / Microsoft / Nintendo 各有自家的签名工具链,只有用他们的 SDK 签出来的二进制才能在零售机上跑——这是 9G-4 认证流程的产物,签名的私钥由平台方托管,你没机会自己签。

一条最小化的"封金"脚本,把上面这几件事串起来,长这样:

```bash
#!/usr/bin/env bash
# gold.sh —— 把一个 CI 产物"封金"。前提:这一版已经通过认证。
set -euo pipefail

VERSION=$1        # 比如 1.0.0
COMMIT=$2         # 通过认证的那个 commit SHA
ARTIFACT_DIR=$3   # CI 产出的目录,比如 artifacts/1.0.0-linux-x64/

echo "Sealing gold master for $VERSION (commit $COMMIT)"

# 1. 校验产物哈希 —— CI 已经算过一次,这里独立重算,防止传输/存储损坏
cd "$ARTIFACT_DIR"
sha256sum game > /tmp/gold.sha256
# 跟 CI 留存的哈希对一遍(假设 CI 把哈希写到 .ci_hash)
if ! diff -q /tmp/gold.sha256 .ci_hash; then
    echo "FATAL: artifact hash mismatch, refusing to seal"
    exit 1
fi

# 2. 代码签名(以 Linux 上的 detached GPG 签名为例;Windows 用 signtool,
#    macOS 用 codesign + xcrun notarytool,主机用平台 SDK 自带工具)
gpg --detach-sign --armor --output game.sig game
echo "Detached signature written to game.sig"

# 3. 归档调试符号 —— 没有符号就没法符号化崩溃(09F-2 §4),这是 gold 的硬要求
mkdir -p ../symbols/$VERSION
cp game.debug ../symbols/$VERSION/ 2>/dev/null || \
    objcopy --only-keep-debug game ../symbols/$VERSION/game.debug
gpg --detach-sign --armor --output ../symbols/$VERSION/game.debug.sig ../symbols/$VERSION/game.debug

# 4. 写一份 gold 记录:版本、commit、哈希、签名指纹、封金时间、封金人
cat > ../gold-records/$VERSION.json <<EOF
{
  "version": "$VERSION",
  "commit": "$COMMIT",
  "sealed_at": "$(date -u +%FT%TZ)",
  "sealed_by": "$(git config user.name)",
  "artifact_sha256": "$(sha256sum game | cut -d' ' -f1)",
  "signature": "game.sig",
  "signature_fingerprint": "$(gpg --list-packets game.sig | grep keyid | head -1)",
  "symbols": "symbols/$VERSION/game.debug"
}
EOF
gpg --clearsign ../gold-records/$VERSION.json

echo "Gold master $VERSION sealed. Record: ../gold-records/$VERSION.json.asc"
echo "From this point: NO changes to this artifact. Patches are NEW artifacts."
```

注意最后那句"patches are NEW artifacts"。这是 gold 纪律的核心:**gold 母版永远不动**。你发售之后发现的 bug,不修在 gold 上,而是产出一个**新的构建**(1.0.1),它有自己的版本号、哈希、签名、归档符号。Gold 母版作为"曾经发售的那个东西"被永久封存,用于回滚(09F-2 §2)、用于老玩家存档兼容验证(09F-2 §1)、用于历史追溯。这套"母版不可变"的纪律,跟 9A-2 里讲的"纯函数核心"是同一种思想的不同化身:**重要的东西钉死,改动只通过受控的、可追溯的新版本发生。**

心理上,gold 是一个值得停下来的时刻。很多独立开发者在这一刻会陷入两种危险情绪:一种是"再调一下平衡吧,差一点就完美了"——这叫 scope creep 的回光返照,你必须按住;另一种是"它终于走了,我可以不管它了"——这是这一篇后面要打破的幻觉。Gold 是定型的终点,却是售后的起点。**你停下了加东西的手,但接住的是一个会持续向你要修复、要内容、要回应的活产品。**

## 2 · 发售日的现实:服务器、评测、与那个你 QA 没见过的崩溃

Gold 提交之后到发售日之间,通常有几天到几周窗口。这段窗口里,玩家手里还没有游戏,但你手里**已经有了**——也就是说,你已经可能在 gold 母版上发现新 bug。这就是 **day-one patch**(首日补丁)的来源:你在发售日**之前**就准备好一个补丁,玩家第一次启动游戏时立刻下载。Day-one patch 在今天是常态,不是异常——任何稍有规模的游戏,从 gold 到发售之间的窗口几乎一定会发现至少一个值得修的问题。如果你的发售计划里没有 day-one patch 的预案,你不是没遇到问题,你是遇到了但没准备。

发售日的物理现实,可以从三条线去理解。

第一条线是**服务器负载**,这只对联网游戏成立,但一旦成立就是头号风险。09E 序列讲的是 netcode 架构,09F-2 §6 讲的是匹配作为 live-ops 的运营面;这里讲的是发售日那一刻的特殊性。压测(stress test)再充分,也压不出"发售日同时在线峰值"——因为发售日的玩家行为分布跟日常完全不同:所有人都在同一小时涌入,所有人都在创建账号、过新手引导、挤同一个匹配池。你的权威服务器(9E-2)、你的 NAT 中继(9E-4)、你的匹配服务,全部在同一时刻承受峰值。**实操上的对策是 over-provisioning(过度配额)加上 autoscale(自动扩容)**:发售头几天把服务器容量开到日常的 3-5 倍,接受单日成本飙升,因为发售口碑损失的代价远高于几天的云账单。同时配好 autoscale 规则,CPU 超过 70% 自动扩节点,等峰值过去再自动缩。这套基础设施本来就在 09F-2 的 live-ops 范畴里,发售日只是把它的"上限"测到极限。

第二条线是**评测与口碑**。Steam 的"特别好评 / 多半好评 / 褒贬不一"阈值,在发售头 48 小时基本就被钉死。Steam 算法的逻辑是:发售头几天的评价权重最高,它们决定游戏在"新品"榜单的曝光,进而决定后续自然流量的天花板。这意味着发售日的一个严重 bug(进不去游戏、存档丢失、关键 boss 卡死)不只是一个技术问题,它会通过差评→曝光下降→销量下降→补丁来得越晚差评越多的负反馈循环,变成一个商业灾难。**这就是为什么"线上烧起来了,你多快能发出去"(09F-2 §7)在发售日是最锋利的能力**——几小时发修复 vs 几天发修复,差距是几千条差评。

第三条线是**那批你 QA 从未见过的崩溃**。这不是 QA 失职,这是统计必然。你的 QA 团队可能 20 个人,测了几千小时,覆盖了几十种硬件组合;发售日玩家是几万人,他们运行游戏的硬件组合数量级是几十万种,他们操作的边界情况是无穷的。你 09F-2 §4 那个故事里的 `particles::emitter::tick`——RTX 4080 上测几千次没事,集成显卡 512 MB 显存上一次性分配 2 GB buffer 就崩——这种 bug **只能在玩家的硬件上被发现**,不可能在发售前预测。所以发售日真正的工程能力,不是"确保不崩"(做不到),而是"崩了能立刻看见、立刻定位、立刻发修复"。这条能力链就是 09F-2 §4 的崩溃上报 + §5 的遥测 + §7 的热修管线。发售日是这条链第一次实战——所有在发售前演练过的环节,在这一天接受检验。

让我把发售日的工作流用伪代码画出来,你会看到它跟 09F-2 §7 那条热修管线高度重合,但节奏更紧:

```rust
// launch_day_ops.rs —— 发售日的"作战室"逻辑骨架
//
// 核心思想:发售日不是"等出事",而是"主动盯"。三个仪表盘同时开:
// (1) 崩溃聚合后台(09F-2 §4):每分钟刷一次 top crashes
// (2) 遥测 dashboard(09F-2 §5):崩溃率、退出率、负载延迟
// (3) 评测/论坛/社媒:玩家主观声音,人盯 + 关键词告警
//
// 任何一个仪表盘超阈值,触发 triage 流程。

pub struct LaunchDayMonitors {
    crash_backend: CrashBackend,         // Sentry / Backtrace / 自建
    telemetry_dash: TelemetryDashboard,  // Grafana
    review_feed: ReviewFeed,             // Steam 评价、Reddit、Discord
    // 阈值:超过就告警,进入 triage
    crash_rate_red: f64,   // 比如 5% 玩家崩过 = 红色
    crash_rate_amber: f64, // 比如 1% = 黄色,人盯但不一定发版
}

pub enum LaunchAlert {
    CrashSpike { signature: String, affected_players: u32, rate: f64 },
    ReviewBomb { negative_rate_last_hour: f64 },
    ServerOverload { p99_latency_ms: u64, queue_depth: u32 },
}

impl LaunchDayMonitors {
    pub fn tick(&self) -> Vec<LaunchAlert> {
        let mut alerts = vec![];
        // 1. 崩溃率:看最近 1 小时的崩溃玩家占比
        let crash_rate = self.crash_backend.crash_rate_last_hour();
        if crash_rate >= self.crash_rate_red {
            for issue in self.crash_backend.top_issues(5) {
                alerts.push(LaunchAlert::CrashSpike {
                    signature: issue.signature.clone(),
                    affected_players: issue.affected_players,
                    rate: crash_rate,
                });
            }
        }
        // 2. 评测:负面评测占比突然跳升 = 一定有体验问题在玩家侧发酵
        let neg = self.review_feed.negative_rate_last_hour();
        if neg > 0.30 { // 一小时内负面超 30%,基本是灾难
            alerts.push(LaunchAlert::ReviewBomb { negative_rate_last_hour: neg });
        }
        // 3. 服务器:延迟和队列深度直接反映"能不能进去玩"
        if let Some(lat) = self.telemetry_dash.server_p99_latency_ms() {
            if lat > 2000 {
                alerts.push(LaunchAlert::ServerOverload {
                    p99_latency_ms: lat,
                    queue_depth: self.telemetry_dash.queue_depth(),
                });
            }
        }
        alerts
    }
}

// 收到 alert 之后的 triage 流程:
// (a) 红色 crash spike → 立刻走 09F-2 §7 的热修管线,目标是 4 小时内 canary
// (b) 评测差评集中指向"某 boss 卡死" → 验证是 bug 还是设计,bug 走热修,
//     设计问题最快走 day-2/day-3 的平衡 hotfix(可能只是改 CVar,见 9B-4)
// (c) 服务器过载 → 立刻 autoscale 扩容,同时排查是不是某个慢查询拖垮了 DB
```

这套节奏里最反直觉的一条是:**发售日你会主动选择"不发版",除非真的是 blocker**。每发一个补丁都有引入新 bug 的风险(09F-2 §7 的 canary 就是为这个设计的),发售日的 canary 验证窗口又比平时短,所以哪怕看到十几个崩溃,只要不是"玩家进不去游戏"级别,你往往选择**先收集数据,发一个集中修复多问题的 day-2 或 day-3 patch**,而不是每小时发一次。这种"忍住不发"的判断,跟 §1 里"忍住不改 gold"是同一种纪律的延续:**克制是发售日最稀缺的工程品质**。

最后,关于 day-one patch 的发布节奏,有一条跟 9G-4 认证交叉的细节。在 PC 平台(Steam / Epic),你随时能发版,认证门槛几乎没有,day-one patch 几小时就能上线。但在主机平台,Sony / Microsoft / Nintendo 要求每一个新版本都走认证,即使是首日补丁。这意味着**主机的 day-one patch 必须在发售日之前就开始走认证流程**——通常的做法是:你提交 gold 之后,立刻开始做 day-one patch,争取在发售日之前完成主机认证,这样玩家第一次启动就能拿到。如果 day-one patch 来不及认证,主机玩家就会拿到"裸 gold",上面那个后来发现的 bug 就会真实地砸在他们头上。这是为什么主机发售的工程节奏比 PC 紧得多——gold 不是终点,是 day-one patch 起跑的发令枪。

## 3 · 售后支持:游戏作为一项服务,而不是一次性产品

发售日熬过去之后,游戏进入了一个长期阶段:**售后支持(post-launch support)**。这个阶段的长度因项目而异——独立游戏可能是几个月到一两年,大型 live service 游戏可能是五年、十年。但无论长短,现代游戏的共识是:**游戏发售之后会继续变化,它是一项服务(game as a service),不是一个一次性产品(one-shot product)**。这个观念的转变,是过去二十年游戏行业最重要的范式转移之一,而它的全部工程后果,都落在你头上。

售后支持具体做哪些事?可以分成三类,每一类对应 09F-2 里的一套基础设施。

第一类是**修复性更新**(patches / hotfixes),目标是"让游戏不崩、不卡、不坑"。这包括崩溃修复(09F-2 §4 崩溃上报驱动)、严重性能问题修复、存档相关灾难修复(09F-2 §1 的存档迁移在这里保护老玩家)、平衡性调整(09F-2 §5 遥测告诉你哪个 boss 太难)。这一类更新的频率通常是发售头几周高(每周一到两次,救火),稳定后降低(每月一次例行维护)。09F-2 §7 的热修管线是这一类的发动机,§2 的差分 patch 是这一类的分发手段。

第二类是**内容更新**(content updates / DLC),目标是"让游戏有新东西可玩"。这包括新关卡、新角色、新武器、新赛季(live service 游戏的"赛季"概念)、节日活动。这一类对应 09F-2 §3 的 DLC 与可挂载内容——你的游戏架构越彻底地"代码是通用引擎、内容是数据"(phase-7 资产管线 + 9B-4 CVar),加新内容就越便宜。一款内容更新做得轻快的游戏,可以以"两周一个新活动"的节奏持续运营;一款加内容要改十几个源文件重编核心的游戏,通常就放弃内容更新战略,变成"发售即巅峰"。架构决定商业模式,这是 phase-7 那条哲学在售后阶段的回响。

第三类是**社区管理**(community management),这一类看起来最不"工程",但它跟工程的交叉点很深。社区管理意味着你有一个论坛 / Discord / Reddit / 微博的存在,玩家在那里反馈问题、提建议、抱怨平衡、报告 bug。一个好的社区管线,会把"玩家报告的 bug"转化成"崩溃后台里的一个 issue"——比如玩家在 Discord 说"我在第三关开头必崩",社区经理(或一个集成的 bot)引导他提供崩溃 ID,然后这个 ID 跟你崩溃后台里某个 signature 关联起来,你立刻知道"哦,这不是孤例,后台里已经有 47 个同样的崩溃"。把社区声音跟遥测数据交叉验证,是售后阶段最高价值的认知活动之一——§4 会专门讲怎么做到不被任何一方绑架。

这三类工作合起来,就是"游戏作为服务"的日常。它跟"开发阶段"最大的区别是节奏和心态。开发阶段是你主动决定"今天做什么",售后阶段是**玩家决定你今天做什么**——凌晨的崩溃报告决定你今天修崩溃,周末的活动反馈决定你下周调活动。这种"被外部事件驱动"的工作模式,需要一套跟开发期完全不同的工程纪律:你的 CI/CD 必须随时能发版(09F-1)、你的补丁管线必须随时能跑(09F-2 §2)、你的回滚开关必须随时能用(09F-2 §7)。发售前这些是"基础设施",发售后这些是"生命线"。

让我用一段伪代码展示一个"售后周节奏"的工程化骨架,它把 09F-2 的几个子系统串成一个循环:

```rust
// post_launch_cycle.rs —— 售后阶段的周节奏(伪代码骨架)
//
// 这不是一个会跑的 main,而是一个"周节奏"的逻辑模板。
// 真实实现里,每一步对应 09F-2 一个子系统的具体调用。

pub struct PostLaunchContext {
    crash_backend: CrashBackend,
    telemetry: TelemetryDashboard,
    community: CommunityFeed,
    patch_pipeline: PatchPipeline,   // 09F-2 §2 + §7
    // 当前活跃版本,比如发售两周后是 1.0.3
    current_version: SemVer,
}

impl PostLaunchContext {
    // 周一:看数据,定本周优先级
    pub fn weekly_triage(&self) -> WeeklyPlan {
        // 1. 崩溃 top 5:这是"必修"
        let top_crashes = self.crash_backend.top_issues(5);
        // 2. 遥测信号:留存掉点、性能退化、平衡异常
        let signals = self.telemetry.anomalies_last_week();
        // 3. 社区高赞反馈:这是"玩家声音"
        let community_threads = self.community.top_threads(10);

        // 4. 交叉验证:社区反馈里"第三关必崩"是否对应崩溃后台某 signature?
        //    如果是,优先级提到最高;如果社区抱怨但数据没印证,降级观察。
        let mut must_fix = vec![];
        for issue in &top_crashes {
            if issue.affected_players > 50 || community_mentions(&community_threads, &issue.signature) {
                must_fix.push(issue.clone());
            }
        }

        WeeklyPlan {
            hotfix_targets: must_fix,        // 本周发版必须修的
            balancing_tweaks: from_signals(&signals), // 可能只改 CVar,见 9B-4
            community_responses: community_threads.iter()
                .filter(|t| t.needs_official_reply()).collect(),
        }
    }

    // 周四:跑回归 + 构建 + canary
    pub fn weekly_release(&mut self, plan: &WeeklyPlan) -> ReleaseResult {
        // 09A-4 的回归网保护你不引入新 bug
        run_regression_suite();
        // 09F-2 §1:如果有存档 schema 改动,跑迁移 property test
        if plan.has_save_migration() {
            run_save_migration_property_tests();
        }
        // 构建新版本,归档符号(09F-2 §4)
        let new_version = self.current_version.bump_patch();
        self.patch_pipeline.build_and_archive(new_version.clone());
        // canary 5%,盯遥测 2 小时
        self.patch_pipeline.canary_rollout(&new_version, 5)?;
        // 监控逻辑省略,真实实现会等一个 timeout 或人工确认
        Ok(ReleaseResult::Canaried(new_version))
    }

    // 周五:canary 没问题 → 全量
    pub fn weekly_promote(&mut self, new_version: SemVer) {
        if self.telemetry.canary_looks_clean(&new_version) {
            self.patch_pipeline.rollout_full(&new_version);
            self.current_version = new_version;
        } else {
            // canary 发现新问题 → 回滚(09F-2 §7)
            self.patch_pipeline.rollback(&self.current_version);
        }
    }
}
```

这个骨架的精髓不在代码,在节奏:**每周固定 triage、固定 release、固定 promote**。这种可预测的节奏,是把"售后救火"从混乱变成工程的关键。一支没有节奏的售后团队,是被崩溃报告追着跑,什么时候发版看心情,canary 多久看手感;一支有节奏的售后团队,是每周固定时间看数据、固定时间发版、固定时间验证,玩家也知道"周四是 patch 日",预期稳定。**节奏本身就是一种工程产出**,跟代码一样重要。

## 4 · 听遥测,但不被遥测绑架:data-informed, not data-ruled

售后阶段最微妙的工程判断,不在"怎么发版",在"听谁的"。这一节专门讲这个判断,因为它是新手最容易翻车的地方,翻车的后果是把游戏改坏。

你已经有了 09F-2 §4 的崩溃上报和 §5 的遥测闭环,你也有了一个活跃的社区(Discord / Reddit / 论坛)。这两个信息源都在向你说话,但它们说的话**不是同一回事,也都不等于"玩家想要什么"**。

遥测告诉你的是**玩家做了什么**(what players do):他们在哪里死最多、在哪里退出游戏、平均玩多久、哪些 boss 通关率多少。这是行为数据,客观、大规模、可量化。但行为数据不告诉你**为什么**——你看到 30% 玩家在第三关开头退出,你不知道是因为难度陡增,还是因为有 bug,还是因为那段音乐让玩家头疼。行为数据是症状,不是病因。

社区告诉你的是**玩家说他们想要什么**(what players say they want):论坛高赞帖"这 boss 太难了,削一下"——这是显性需求。但社区声音有两个特征:第一,**发声的是少数**——一个 10 万玩家的游戏,Discord 活跃用户可能只有 2000,论坛发帖的可能只有几百,他们不代表沉默的大多数;第二,**玩家说的不一定是玩家真的要的**——经典的例子是某 MMO 玩家集体请愿"加强 X 职业",开发组真的加强了,结果那个职业变成必选,游戏平衡崩了,所有人都不开心,包括当初请愿的人。**说出来的需求,跟真正的需求,经常是两回事。**

所以工业实践总结出一条原则:**data-informed, not data-ruled**(被数据启发,不被数据统治)。这句话的含义是,数据(遥测 + 社区)是你的输入之一,但**决策是你做的**,而且你必须把数据放在"游戏设计的长期目标"这个更大的框架里去解读。具体落到几条操作纪律上。

第一条,**永远看比例,不看绝对数**。论坛上有 100 个帖子骂某个 boss,听起来很多;但如果你有 5 万活跃玩家,100 个帖子是 0.2% 的声音。同时遥测告诉你,这个 boss 的通关率是 60%,跟其他 boss 持平。这时候那 100 个帖子反映的不是"boss 设计坏了",而是"这个 boss 难住了 100 个特别爱发帖的人"。正确的反应不是削 boss,而是可能加一个难度选项,让爱发帖的硬核玩家有挑战、让沉默的休闲玩家有出口。

第二条,**区分"行为异常"和"行为异常是问题"**。遥测告诉你"30% 玩家在第三关退出",这是异常(跟其他关相比)。但这个异常是不是问题?可能第三关本来就是一个自然的"试玩结束点"——很多玩家试玩两小时就够决定买不买了,他们在第三关退出不是游戏坏了,是他们做完了购买决策。这时候你应该看的不是"怎么让第三关留存变高",而是"这些退出的玩家最后转化成购买了多少"。**数据告诉你 what,设计目标告诉你哪个 what 是问题。**

第三条,**做 A/B 验证,而不是直接全量**。你判断"第三关退出是因为难度陡增",你把难度降了 15%。这是你的假设,不一定是真相。正确做法是 canary(09F-2 §7)发到 5% 玩家,看这 5% 的第三关退出率有没有变化。如果没变化,你的假设错了,问题不在难度,撤回改动。这一步把"我觉得"变成"数据证明",是 data-informed 的核心操作。canary 不只是"防止新 bug",更是"验证设计假设"——这是它在售后阶段的第二个、往往更高价值的用途。

第四条,**警惕"被论坛绑架"的政治压力**。社区声音大,容易被团队内部当成"民意的代表"。一个没有纪律的团队,会陷入"论坛喊什么就改什么"的循环,最后游戏被改得四不像,因为它不再服务于一个连贯的设计愿景,而是服务于"最近谁喊得最响"。这条纪律的具体形态是:**任何平衡性改动,必须先在遥测里找到证据,再考虑社区声音**。论坛说 boss 难,先看遥测——通关率 60%?那不是 boss 难,是论坛声学特性。通关率 15%?那确实是难,改。**社区提供假设,遥测提供裁决,设计目标提供框架——三者缺一不可。**

这套纪律听起来抽象,但它就是售后阶段最值钱的经验。新手团队最容易犯的错,是把遥测或社区任何一个当成"圣旨",然后被它牵着改坏游戏;成熟团队的做法是把两者都当输入,由一个理解设计目标的人(或团队)做最终判断,而且这个判断是**可以被推翻的**(通过 canary 验证)。**数据是工具,不是主人。** 这一句话,是售后阶段最重要的一句工程哲学。

## 5 · Sunsetting / EOL:一个游戏怎么体面地结束

售后阶段不会无限持续。无论游戏多成功,总有一天你会**停止支持它**——不再发补丁、不再加内容、不再做社区运营。这一步叫 **sunsetting**(日落)或 **end-of-life**(EOL,生命周期终结)。这是游戏生命周期里最少被讨论的一段,因为它不像发售那样有商业庆典、不像补丁那样有技术挑战,它是"一件事情的结束",听起来不性感。但一个专业的工程师知道:**结束一件事的过程,跟开始一件事的过程一样需要工程纪律**,而且结束做得好不好,直接关系到玩家的信任、团队的声誉、以及你自己作为工程师的完整度。

Sunsetting 的具体动作,因游戏类型差异很大,但可以分成几条共同的工程线。

第一条线是**服务器关闭**(server shutdown),这只对联网游戏成立,但一旦成立就是最敏感的一步。一个网游关闭服务器,意味着玩家花了几百小时的角色、装备、社交关系,在那一刻全部失去意义——他们的"游戏"消失了。这是一个伦理敏感的动作,工业实践里有一套基本规范。第一,**提前告知**:服务器关闭日期必须提前公布,通常至少 6 个月,给玩家时间消化、告别、完成他们想完成的事。第二,**停止商业化**:公布关服之后,立刻关闭所有付费入口(不能让玩家在关服前一周还充值,那是欺骗)。第三,**提供出口**:如果技术上可能,提供一个**离线模式**(offline mode)或**私服客户端**(private server client),让玩家在官方服务器关闭后还能以某种形式继续玩。第四,**退款政策**:对刚充值未消耗的虚拟货币,按比例退款,具体规则因平台和地区而异(这部分也跟 GDPR / 各国消费者保护法交叉,见 phase-8/telemetry-short 的合规框架)。

第二条线是**最终补丁**(final patch)。服务器关闭之前,通常要发一个最终版本,它的目标是"让游戏在没有官方维护的状态下,尽可能自洽地活下去"。这个最终补丁可能做几件事:把所有依赖官方服务器的功能,优雅地降级到本地(比如排行榜变成"你自己的最高分",云存档变成"导出到本地文件");移除所有"需要服务器才能工作"的入口,避免玩家点了之后看到无意义的错误;解锁所有原本需要付费或服务器验证的内容,作为对老玩家的告别礼物。这个最终补丁的工程量不小,因为它要把"联网架构"反向改造成"单机可玩",而你的架构在 9E-2(权威服务器)和 9E-4(匹配/中继)里是围绕"有服务器"设计的——把它倒回去,本身就是一次严肃的工程任务。

第三条线是**归档**(archival)。游戏停止维护之后,它的二进制、源代码、资产、文档、调试符号、构建脚本,都应该被归档保存。这不是怀旧,是工程责任。原因有几个:第一,法律上你可能需要在多年后证明"这个版本的版权属于你",你需要能还原当时发售的那个二进制(这就是 §1 那份 gold 记录的长期价值);第二,如果有玩家社区想做 mod、做私服、做考古,你保留源代码意味着这件事在未来有可能合法地发生(很多经典游戏在 EOL 多年后由社区复活,前提是源代码还在);第三,你自己多年后可能想做续作或重制,有原始资产和源代码能省下天文数字的恢复成本。归档的纪律是:**任何曾经对外发布的版本,它的二进制 + 符号 + 源代码 snapshot + 构建环境描述,必须能找到**。这跟 §1 的 gold 记录、09F-2 §4 的符号归档,是同一条线拉到 EOL 的延伸。

第四条线是**沟通**(communication)。Sunsetting 是一个情感事件——对玩家是告别,对团队也是。一封写得好的"关服公告",会诚实地解释为什么结束(商业上不持续、技术债太重、团队要去做新东西),感谢玩家的陪伴,清晰地列出时间线和玩家接下来能做什么、不能做什么。一封写得差的公告(冷漠的法律式声明,或者过度煽情),会伤害团队声誉,影响你下一款游戏的发售。**沟通是工程的一部分**,因为它跟你的社区管线(§3)直接相关——你建立的那个社区,在这一刻是接收你说再见的对象。

让我把一个最小化的"EOL 时刻"工程动作列出来,作为骨架:

```bash
#!/usr/bin/env bash
# eol.sh —— 游戏 EOL 时刻的工程动作骨架
# 假设:已经提前 6 个月公布关服日期,今天是关服日。
set -euo pipefail

GAME=$1           # 游戏标识
FINAL_VERSION=$2  # 最终补丁版本,比如 5.4.7-eol

echo "Executing EOL for $GAME"

# 1. 发布最终补丁(已经在过去几周 canary 过):
#    - 离线模式启用
#    - 服务器依赖功能优雅降级
#    - 解锁所有付费内容作为告别
#    这一步在关服日之前完成,确保所有玩家在关服那一刻手里是 final 版本。
echo "Final patch $FINAL_VERSION already rolled out (verified 100%)."

# 2. 服务器关闭:按预定时刻关闭各个服务,顺序很重要
#    (a) 先停匹配/登录,拒绝新玩家进入
#    (b) 给在线玩家 30 分钟"告别时间"窗口,广播告别消息
#    (c) 关闭游戏服务器实例
#    (d) 关闭匹配服务、中继服务
#    (e) 最后关闭数据库,做最终备份
echo "Shutting down servers in sequence..."
# ssh deploy@matchmaker "systemctl stop hh-matchmaker"
# ... (省略具体服务名)

# 3. 最终数据库备份 + 加密归档
BACKUP_PATH="archive/$GAME/$(date -u +%F)-final-db.sql.gz"
pg_dump hh_game | gzip > "$BACKUP_PATH"
gpg --encrypt --recipient archive@$GAME-studio "$BACKUP_PATH"
echo "Final DB backup encrypted at $BACKUP_PATH.gpg"

# 4. 源代码 + 资产 + 符号归档(冷存储)
#    把整个 git 仓库、所有 release 符号、所有 .pak 资产、所有构建脚本
#    打包,上传到冷存储(S3 Glacier / 类似),打标签 "EOL archive"
tar czf archive/$GAME-eol-source.tar.gz -C .. src assets build-tools ci
gpg --encrypt --recipient archive@$GAME-studio archive/$GAME-eol-source.tar.gz
echo "Source + assets + symbols archived to cold storage."

# 5. 商店页面更新:把游戏标记为"不再更新",商店描述里加 EOL 说明
#    (在 Steamworks 后台 / 各平台开发者门户手动操作)

# 6. 社区公告:发布最终的"谢谢"公告,关闭新帖功能(保留只读)
echo "Publishing farewell announcement. Community goes read-only."

echo "EOL complete. $GAME is now in archival state."
```

这套动作的精神是:**结束一件事情,跟开始一件事情,需要同等的工程严肃性**。一个游戏从原型(9G-1)走到垂直切片(9G-2)、走到 alpha/beta(9G-3)、走过认证(9G-4)、走过 gold(§1)、走过发售(§2)、走过售后(§3)、最终走到 EOL——这是一条完整的工程生命周期。能从头到尾走完这条线的工程师,跟只能做其中某一段的工程师,差距是数量级的。**EOL 不是失败的标志,是成熟的标志**——一个游戏活到自然 EOL,意味着它有过完整的生命,你把它带到了一个负责任的终点。这本身,就是专业。

## 6 · 在你 HH 项目里动手(做中学红线)

这一篇的做中学,是一次**完整的发售模拟**——从切一个"gold"构建开始,到把游戏发出去让真人玩家玩、收崩溃、做 triage、发 day-one patch,完整地走一遍 gold → launch → patch 的循环。你做完这件事,会第一次"亲身感受到一个游戏从离开你的手到被玩家玩、再回到你手里变成修复"的完整生命周期。Casey 的 HH 没有这一段,这就是你超越他的地方。

第一,**给你的 HH 游戏切一个"gold"构建**。这件事的目标是让你亲手执行一次 §1 那套"封金"纪律。具体步骤:先在你的 HH 项目仓库里,确定一个"发售候选" commit——它通过了你所有的测试(9A 序列)、你不再打算加任何东西。给这个 commit 打 tag,比如 `v1.0.0-gold`。然后用 09F-1 的 CI 流程(或本地 cargo build --release)产出 release 二进制。算它的 SHA256,归档它的调试符号(09F-2 §4 反复强调过),写一份 gold 记录 JSON(版本、commit、哈希、封金时间、封金人,可以参考 §1 那个 gold.sh 的格式)。最后,把这一刻当成"不再改"——你之后所有的修复,都在新 commit 上做,产出 v1.0.1,而不是回头改 v1.0.0。**这一步做完,你内化了"gold 母版不可变"的纪律。**

```bash
# 在你 HH 项目里,封金 v1.0.0
cd ~/src/handmade-hero
git tag -a v1.0.0-gold -m "Gold master for HH 1.0.0"
cargo build --release
sha256sum target/release/handmade_hero > artifacts/v1.0.0/hh.sha256
# 归档符号(Linux)
objcopy --only-keep-debug target/release/handmade_hero \
        artifacts/v1.0.0/handmade_hero.debug
# 写 gold 记录(参考 §1 的 gold.sh 模板,可以简化但要有版本+commit+哈希)
```

第二,**把你的 gold 构建发布到一个公开渠道**。如果你有 Steamworks 帐号,可以走 Steam 上架流程,但对 HH 这个规模的游戏,推荐用更轻量的渠道:[itch.io](https://itch.io) 是独立游戏最常用的发布平台,上传一个 zip,设置价格(或免费),生成一个商店页面。把你的 gold 构建传上去,让它是"可下载、可运行"的状态。这一步做完,你的 HH 游戏第一次"离开了你的手"——任何人都可以下载它,在你不知道的硬件上运行它。**这一刻就是发售。**

第三,**让至少三个朋友下载并玩你的游戏,触发崩溃**。这一步的精髓是"陌生硬件 + 陌生操作"——你 QA 自己测,永远是同一台机器、同一种玩法;朋友会做出你意想不到的操作,跑在你没测过的系统上。给他们一个反馈渠道(itch.io 自带的反馈、Discord、邮件)。当他们报告崩溃时,你的崩溃处理器(09F-2 §8 的第一件事,你应该已经装了 panic hook 写 minidump)应该产出 dump,你的上传器(09F-2 §8 的延伸)应该把 dump 发到你的崩溃后台(09F-2 §8 的第二件事)。**这一步让你亲眼看到:"哦,我测不出来的崩溃,真的会在真玩家那里发生。"**

第四,**做一次 triage,发一个"day-one patch"**。从你朋友报告的崩溃里,挑一个最严重的(最好是"所有人都遇到"的),走 09F-2 §7 的热修管线:跑回归(9A-4)、修代码、构建 v1.0.1、归档符号、上传新版本到 itch.io。然后通知你的朋友更新到 v1.0.1,验证崩溃消失。**这一步做完,你完整地走了一遍 launch → crash report → triage → patch → verify 的循环**,这是售后阶段最核心的一个工作单元,你亲手做了一次。

第五,**写一份"发售复盘"文档**(只在你的项目里,不需要给别人看)。回答几个问题:你的 gold 构建里,有没有已知但你选择不修的 bug(因为你判断它不致命)?发售(让朋友玩)之后,你发现了几个你之前不知道的 bug?它们的根因是什么(硬件差异?边界条件?你没想到的玩家行为?)?你的 day-one patch 修复了它们之后,有没有引入新问题?你的 triage 过程,是凭直觉还是有数据驱动?**这一步是这一篇最重要的"做中学"——它强迫你把"发售体验"转成可反思的知识**,下次你做真正的商业游戏发售时,这套反思就是你的经验基础。

做完这五件事,你完成了一个微缩版的"gold → launch → post-launch → EOL"循环(虽然 EOL 你不会真的做,但你会理解它意味着什么)。你的 HH 游戏从"我手里在做的项目"变成了"曾经发布过、有玩家玩过、被修补过的产品"。这是 Casey 在 Day 667 没有走到的那一步——**你走完了。**

## 7 · 练习

练习一(Lv1,概念)。这一篇的核心论点是"gold 不是终点,是售后的起点"。请用一段话论述:为什么"gold 母版定型"(§1)和"游戏进入售后"(§3)不是两件独立的事,而是同一条工程生命线的两个阶段?用本篇讲过的至少三个具体环节(冻结纪律、day-one patch、热修管线、社区管理、sunsetting)来支撑你的论述。

练习二(Lv2,动手)。完成 §6 的第二和第三件事——把你的 HH gold 构建发布到 itch.io,让至少三个朋友玩并报告崩溃。把至少一个真实的崩溃,从"朋友报告"到"你在崩溃后台里找到对应 signature"再到"你定位到源代码行",完整走一遍。写一份 triage 记录:这个崩溃的 signature 是什么?根因是什么?你为什么在发售前没测出来?这一步让你直观感受"陌生玩家和陌生硬件能暴露你测不出来的 bug"。

练习三(Lv3,设计)。为你的 HH 游戏设计一份 **sunsetting 计划**,即使你不真的执行它。假设你的 HH 是一个有 5000 活跃玩家的联网游戏,你要在 6 个月后关服。回答:你要提前多久公布?公布之后,你的商店页面、付费入口、社区论坛分别要做什么改动?你的"最终补丁"要做哪些技术改造(把哪些服务器依赖功能降级到本地)?你的归档策略是什么——哪些东西必须保存、保存多久、保存在哪里?这个练习让你体会到"结束一个游戏"是一件需要工程规划的严肃事情,不是"拍拍屁股走人"。

练习四(Lv4,系统)。实现一个**最简 canary 灰度发布的模拟**,并把 §4 的"data-informed, not data-ruled"原则做成一个可验证的练习。具体:在你 HH 游戏里加一个新功能(比如一个新的粒子效果或一个新的敌人行为),用 9B-4 的 CVar 系统控制它默认关闭。然后写一个"伪发布"脚本,把 5% 玩家(模拟成 100 个假玩家配置文件,5 个开 CVar)设为开启。让你的 HH 游戏在跑这 100 个假玩家 session 时,分别记录开 CVar 和没开 CVar 的崩溃率、帧率分布。判断:这个新功能 canary 之后,遥测是"clean"还是"有 regression"?如果 clean,你才会"全量发布"(把 CVar 默认开)。这个练习让你亲手走一遍"假设 → canary → 遥测裁决 → 决策"的循环,理解为什么"先 5% 再 100%"是降低发布风险的工程纪律。

## 8 · 延伸阅读与下一篇

发售与售后的工程实践,业界最系统的参考是 Jason Schreier 的《Blood, Sweat, and Pixels》和《Press Reset》——前者讲游戏开发后期的混乱(包括 gold 阶段的现实),后者专门讲工作室关闭和项目终止,是 sunsetting 这一节 (§5) 最真实的行业注脚。GDC 演讲 "Post-Launch Live Ops"(各年都有变体,Ubisoft / Epic / Digital Extremes 都讲过)是 live service 运营的实战经验来源。"Day-One Patch: Why It Exists and Why It's Normal" 这类行业博客文章(多个独立开发者写过)从独立游戏视角讲发售日工程节奏。

服务器关闭的伦理与实操,经典案例是 City of Heroes(2012 关服,社区抗议与多年后的私服复活)、Marvel Heroes(2017 突然关服,作为反例)、以及 recent 的 Concord 案例——这些案例的公开复盘文章值得一读,它们会让你理解 §5 里"提前 6 个月公布、提供出口、退款"这些规范是怎么从行业痛苦里长出来的。GDPR 官方站点和各国消费者保护法(中国的《网络游戏管理暂行办法》、欧盟的 Consumer Rights Directive)是退款和告知义务的法律基线。

Data-informed 决策的哲学,经典文献是 Eric Ries 的《The Lean Startup》(虽然写的是创业,但"build-measure-learn 循环"和"看比例不看绝对数"完全适用于游戏售后)。GDC 演讲 "Telemetry-Driven Game Development" 跟 09F-2 §5 的遥测闭环直接呼应,这一篇 §4 是那个闭环在"判断"环节的延伸。关于"玩家说的不等于玩家要的"的经典案例,Valve 在 TF2 上的多次平衡改动复盘(以及玩家社区的"reddit 跟数据打架"传统)是绝佳教材。

跟本系列其它篇的交叉。**9G-4**(certification and TRC)是这一篇的直接前驱——gold 母版就是 9G-4 认证流程的产物,认证通过的那一刻你才能 §1 "封金",所以本篇从 9G-4 结束的地方接上。**09F-2**(release engineering and live-ops)是这一篇的工程基础设施底座——本篇 §2 的发售日救火、§3 的售后周节奏、§4 的遥测判断、§6 的 day-one patch,全部跑在 09F-2 那套崩溃上报、遥测、热修、canary、差分 patch 的管线上;本篇是"何时何地使用那套管线"的运营叙事,09F-2 是"那套管线怎么造"的工程叙事,两者是同一件事的两面。**phase-8/shipping-checklist** 那张"完成的层次"清单(Code complete → Alpha → Beta → Gold → 1.0 → 1.x → EOL)是这一篇的入场券——本篇覆盖的就是从 Gold 到 EOL 的整段生命周期,你发售之后做的每一次 day-one patch、每一次平衡 hotfix、每一次 DLC、最终的那次关服,都是那张清单上"1.x → EOL"那一段的具体内容。**phase-8/telemetry-short** 是这一篇 §2 和 §4 的遥测数据来源——发售日你盯的那个 dashboard、售后你做 triage 依据的那些信号,数据都从 phase-8 那套最小遥测系统里来;本篇是"怎么用那些数据做判断",phase-8 是"怎么把那些数据采上来"。**9B-4** 的 CVar 系统是这一篇 §3 平衡 hotfix 的"不发版修复"手段——某些平衡调整甚至不需要发版,改 CVar 配置实时下发到客户端就行,这是 live-ops 里"hot-tuning"的实践,你 §6 的做中学和练习四都会用到。

最后一句总结。一个游戏从 gold 到 EOL 的整条路,跟从原型到 gold 的那条路一样长、一样难、一样值得被认真地走完。**发售不是工程的结束,EOL 才是。** Casey 的 Handmade Hero 停在了"未完成"的状态,它没有 gold、没有发售、没有售后、没有 EOL——它从未拥有完整的生命。你做完这一篇的做中学,你拥有了一个完整生命周期的微缩版本:你封过金、发过售、收过真玩家的崩溃、发过 patch、最后你也会在某个时刻负责任地结束它。**这就是"专业"二字的全部含义:你负责一件事的整个生命周期,包括它的结束。**

下一篇 [09G-6](09G-6-professional-readiness-checklist.md) 是 9G 序列的收束,也是整个 Phase 9 的 capstone——把你从 9A 到 9G 这七条序列里学到的全部能力(测试、架构、Vulkan、GPU 调试、网络后端、构建发布、制作交付),整合进一个完整的 capstone 项目里,做成你作为"能独立交付一款专业水准游戏的开源工程师"的作品集(portfolio)。如果说 9G-1 到 9G-5 教你"每一块怎么造",9G-6 教你"怎么把它们整合成一个能拿出去给人看的完整作品"。本篇是这条线里"产品生命周期"的那一段,下一篇是"你作为工程师的整个能力地图"的那一段。
