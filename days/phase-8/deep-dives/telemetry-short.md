---
phase: 8
type: deep-dive
title_en: "Telemetry & Crash Reporting (Short)"
title_zh: "遥测与崩溃上报(简版)"
domains: [game, rust, analytics, ops]
duration: "2h"
---

# 深入:遥测与崩溃上报(简版)

> 你发布游戏第一天,Steam 评价新增 200 条。10 条说"崩溃",5 条说"卡顿",2 条说"第二章打不过 boss"。你打开 Steam 后台看硬件调查——只知道玩家用 RTX 4060,不知道他们崩在哪个函数。
>
> 你的游戏跑到 10000 个玩家手里,运行了几亿次帧。**你的开发机器只跑了其中几千帧**。你怎么知道玩家的真实体验?**遥测**是答案——让游戏在玩家机器上自己上报"我现在怎么样",你后台聚合看趋势。

## 0 · 为什么遥测

三条核心价值:

**改进产品**。哪个 boss 玩家死最多?哪个物品 90% 玩家不用?哪个区域玩家停留 0 秒就走了?这些数据只能从真实玩家收集,内部测试样本不够。

**Detect bugs**。崩溃率 0.1% = 10000 玩家里 10 个崩,你永远收不到报告。除非游戏自己上报。

**平衡性**。多人游戏尤其。武器 X 胜率 70%、武器 Y 胜率 30%——遥测让你看到,然后 nerf X buff Y。League of Legends / Valorant / Dota 每天看遥测调平衡。

**反作弊**。玩家位置 / 速度遥测,服务器分析异常——1000 km/s 移动的玩家 = 飞行作弊。

## 1 · 自建 vs 第三方

**自建**:用 Rust 写 server,Postgres 存储,Grafana 可视化。优点:数据完全自己拥有、可定制、零月费。缺点:维护成本、需要 DevOps 经验、容易做出"难用"的 dashboard。

**GameAnalytics**:免费游戏分析 SaaS,业界最流行。免费版够独立游戏用。

**Sentry**:错误 / 崩溃追踪 SaaS。开源版可自部署。Rust 生态最成熟的 crash reporter。

**Backtrace**:专攻游戏崩溃,被 Sauce Labs 收购。Unity / Unreal 集成好。

**Datadog**:通用监控 SaaS。贵($15+/host/month),但功能强。

**Steamworks Stats**:Steam 平台自带,免费但只 Steam 渠道。

**独立游戏推荐**:GameAnalytics(免费、覆盖广)+ Sentry 崩溃追踪(免费 tier 5000 events/月)。规模大后考虑自建或付费升级。

## 2 · Rust:sentry / bugsnag / datadog

**sentry-rust**:Sentry 官方 Rust SDK。

```toml
[dependencies]
sentry = "0.34"
sentry-backtrace = "0.34"
```

```rust
use sentry::protocol::Event;

fn main() {
    let _guard = sentry::init(("https://your-dsn@sentry.io/123", sentry::ClientOptions {
        release: Some(env!("CARGO_PKG_VERSION").into()),
        attach_stacktrace: true,
        ..Default::default()
    }));
    
    // 普通日志
    sentry::capture_message("Game started", sentry::Level::Info);
    
    // 捕获 panic
    std::panic::set_hook(Box::new(|info| {
        sentry::capture_panic(&info);
        println!("Panic: {}", info);
    }));
    
    // 手动上报 error
    if let Err(e) = load_level("level3") {
        sentry::capture_error(&e);
    }
    
    // 游戏主循环
    run_game();
}
```

Sentry 接收事件后,在 Web 界面展示:

- 崩溃栈(stack trace)
- 上下文(OS 版本、游戏版本、玩家 ID)
- 频率(这个崩溃每天发生多少次)
- 受影响玩家数

**自定义 breadcrumb**:

```rust
// 记录关键事件,sentry 在崩溃时附带这些上下文
sentry::add_breadcrumb(sentry::Breadcrumb {
    ty: "debug".into(),
    message: Some(format!("Loading level {}", level_name)),
    ..Default::default()
});
```

崩溃发生时,Sentry 显示最后 N 个 breadcrumb——"啊,玩家崩溃前正在加载 level 3,然后崩了",定位问题极快。

**bugsnag-rust**:Bugsnag 的 Rust SDK。功能类似 Sentry,界面更友好,贵。

**datadog**:Datadog APIClient。可以发游戏 metric 到 Datadog,在 dashboard 看趋势。适合大型项目。

## 3 · 数据点

游戏遥测要采集什么:

**性能**
- FPS(分布,不只是平均)
- Frame time(每帧多少 ms)
- 内存占用(RAM / VRAM)
- Load time(关卡加载时间)
- Draw call 数(图形 API 调用次数)

**崩溃**
- Crash report(stack trace + 系统信息)
- GPU hang(图形驱动崩溃)
- OOM(内存不足)
- 断连(网络问题)

**进度**
- 玩家到第几关 / 第几 boss
- 完成度(支线任务、收集品)
- 玩游戏总时长
- 留存率(D1 / D7 / D30 retention)

**经济**(道具购买、金币流动)

**heatmap**(玩家死亡位置、子弹命中位置、玩家足迹)。可视化成地图叠加,看哪些区域玩家死亡多。

**行为**
- UI 点击序列(玩家怎么用菜单)
- 设置选项(玩家开 vsync 比例、UI scale 分布)
- 按键使用频率(哪个键按得最多)

**采集原则**:够用即止。不要为了"以防万一"采集所有事件——你的 server / 带宽 / 隐私成本会爆。**每个数据点都要回答一个具体问题**:"我想知道 X,所以采集 Y"。

## 4 · GDPR / COPPA / 隐私合规

**GDPR**(欧盟通用数据保护条例,2018)。要求:

- 用户**明确同意**才能采集个人数据
- 用户可以**要求数据删除**(right to be forgotten)
- 用户可以**导出**自己的数据
- 数据必须**最小化采集**(只采集必要数据)
- 数据必须**加密存储**

游戏里实现:首次启动弹窗"我们采集 X / Y / Z 数据用于改进游戏,你同意吗?"。设置菜单有"导出我的数据" / "删除我的账号"。

**COPPA**(美国儿童在线隐私保护法)。13 岁以下儿童数据采集需要父母同意。游戏面向儿童时(教育游戏、卡通画风)要特别小心。

**CCPA**(加州消费者隐私法)。类似 GDPR,加州居民享有。

**中国《个人信息保护法》(PIPL)**,2021 生效。游戏在国内运营要单独合规。

**伦理原则**:

- **匿名化**:用 player_id(随机 UUID),不要存邮箱 / IP / 真名
- **聚合**:heatmap / 性能统计用聚合数据,不存个人路径
- **本地处理**:能用客户端聚合的(比如平均 FPS),不要发原始数据
- **透明**:隐私政策清楚说明采集什么、为什么、怎么用
- **可关**:玩家可以 opt out 遥测,游戏仍然可玩

## 5 · Opt-in vs Opt-out

**Opt-in**:默认不采集,玩家明确同意才采集。GDPR 推荐。
**Opt-out**:默认采集,玩家可以关掉。美国传统做法。

游戏工业实践:

- **欧盟**:必须 opt-in(法律)
- **美国**:opt-out 仍合法,但越来越多游戏用 opt-in
- **隐私倡导者**:opt-in 是道德底线
- **商业考量**:opt-in 数据量比 opt-out 少 70%,但数据质量高(愿意分享的玩家更 engaged)

折中:**首次启动弹窗**,默认勾选 / 不勾选按地区:

```rust
fn first_run_dialog() -> TelemetryConsent {
    let region = detect_region();
    let default_consent = match region {
        Region::EU => false,  // GDPR 默认 opt-in
        Region::US => true,   // 美国默认 opt-out
        Region::CN => false,
    };
    
    let dialog = ConsentDialog {
        title: "Help us improve Handmade Hero",
        body: "We collect anonymous usage data to improve the game. \
               This includes performance metrics, bug reports, and gameplay progress. \
               No personal information is collected.",
        default_yes: default_consent,
    };
    
    dialog.show()
}
```

## 6 · 伦理考量

遥测是一把双刃剑。伦理风险:

**操纵**(dark patterns)。基于遥测数据调整游戏让玩家更上瘾——皮肤掉落概率、付费墙位置。** Loot box / gacha 系统是遥测滥用的典型**。比利时、荷兰已立法禁止部分形式。

**隐私侵蚀**。"我们只采集匿名数据"是常见辩护,但实践上"匿名"数据经常可以 re-identify(MIT 研究显示,4 个时空数据点可以唯一识别 95% 人口)。

**劳动力剥削**。玩家"免费"产生遥测数据,开发者用数据改进产品盈利。**玩家应该知道自己的数据怎么用**。

**反作弊滥用**。anti-cheat 遥测经常采集过多(全进程扫描、键盘 hook),Valve 反作弊 VAC 有争议历史。

**伦理清单**:

- [ ] 数据采集有具体目的(不是"以防万一")
- [ ] 玩家知情同意
- [ ] 数据匿名化尽力(不是字面 anonymize 就完)
- [ ] 数据保留时间有限(30 天 / 90 天)
- [ ] 玩家可以导出 / 删除自己的数据
- [ ] 不基于数据操纵玩家(没有" addicted 玩家付费墙"算法)
- [ ] 公开 privacy policy,用普通语言(不是 5000 字法律文书)

## 7 · 实战:HH 加遥测

最小可用遥测系统:

```rust
// telemetry.rs
use serde::{Serialize, Deserialize};
use std::sync::Arc;
use parking_lot::Mutex;
use std::time::{Duration, Instant};

#[derive(Serialize)]
struct TelemetryEvent {
    event_type: String,
    timestamp: u64,
    player_id: String,
    session_id: String,
    game_version: String,
    #[serde(flatten)]
    data: serde_json::Value,
}

pub struct TelemetrySystem {
    player_id: String,
    session_id: String,
    consent: bool,
    endpoint: String,
    queue: Arc<Mutex<Vec<TelemetryEvent>>>,
    flush_interval: Duration,
}

impl TelemetrySystem {
    pub fn new(consent: bool) -> Self {
        Self {
            player_id: load_or_create_player_id(),
            session_id: uuid::Uuid::new_v4().to_string(),
            consent,
            endpoint: "https://telemetry.yourgame.com/events".into(),
            queue: Arc::new(Mutex::new(vec![])),
            flush_interval: Duration::from_secs(60),
        }
    }
    
    pub fn track(&self, event_type: &str, data: serde_json::Value) {
        if !self.consent { return; }
        
        let event = TelemetryEvent {
            event_type: event_type.into(),
            timestamp: now_unix(),
            player_id: self.player_id.clone(),
            session_id: self.session_id.clone(),
            game_version: env!("CARGO_PKG_VERSION").into(),
            data,
        };
        
        self.queue.lock().push(event);
    }
    
    pub fn flush(&self) {
        if !self.consent { return; }
        
        let events: Vec<_> = {
            let mut q = self.queue.lock();
            std::mem::take(&mut *q)
        };
        
        if events.is_empty() { return; }
        
        // 异步发到 server
        let endpoint = self.endpoint.clone();
        std::thread::spawn(move || {
            let client = reqwest::blocking::Client::new();
            let _ = client.post(&endpoint)
                .json(&events)
                .send();
        });
    }
    
    pub fn track_crash(&self, panic_info: &str) {
        if !self.consent { return; }
        self.track("crash", serde_json::json!({
            "panic": panic_info,
            "os": std::env::consts::OS,
            "arch": std::env::consts::ARCH,
        }));
        self.flush();  // 崩溃立即 flush
    }
    
    pub fn track_fps(&self, fps: f32) {
        self.track("fps_sample", serde_json::json!({
            "fps": (fps * 10.0) as u32 as f32 / 10.0,  // 精度降到 0.1
        }));
    }
}
```

主循环使用:

```rust
fn main() {
    let consent = first_run_dialog();
    let telemetry = TelemetrySystem::new(consent);
    
    // 捕获 panic
    let t = telemetry.clone_data();
    std::panic::set_hook(Box::new(move |info| {
        t.track_crash(&info.to_string());
    }));
    
    telemetry.track("game_start", json!({}));
    
    let mut last_flush = Instant::now();
    let mut frame_count = 0;
    loop {
        // 游戏帧
        let dt = frame_dt();
        
        frame_count += 1;
        if frame_count % 600 == 0 {
            // 每 10 秒采样一次 FPS
            telemetry.track_fps(1.0 / dt);
        }
        
        // 定期 flush
        if last_flush.elapsed() > Duration::from_secs(60) {
            telemetry.flush();
            last_flush = Instant::now();
        }
        
        run_frame(dt);
    }
}
```

事件埋点示例:

```rust
// 玩家死亡
fn on_player_death(state: &GameState, telemetry: &TelemetrySystem) {
    telemetry.track("player_death", json!({
        "level": state.current_level,
        "x": state.player.x,
        "y": state.player.y,
        "death_cause": state.last_damage_source,
        "time_played_s": state.session_time,
    }));
}

// 关卡完成
fn on_level_complete(state: &GameState, telemetry: &TelemetrySystem) {
    telemetry.track("level_complete", json!({
        "level": state.current_level,
        "completion_time_s": state.level_time,
        "deaths_this_level": state.deaths_in_level,
    }));
}
```

服务器端(Python / Node / Rust 都行)接收 + 存到 Postgres / ClickHouse,Grafana 画图。这是工业级 telemetry 后端的标准架构。

## 8 · 反模式

**反模式 1:每帧发遥测**。10 万玩家 × 60 FPS = 600 万 QPS。Server 立刻挂。**应该**:客户端聚合(每 10 秒发一次平均 FPS)。

**反模式 2:阻塞主线程发遥测**。HTTP 请求 100ms 延迟,游戏卡 100ms。**应该**:异步发送(background thread + queue)。

**反模式 3:同步采集玩家输入**。键盘所有按键全采集,巨量数据 + 隐私噩梦。**应该**:只采集游戏内行为(移动距离、攻击次数),不采集具体按键。

**反模式 4:遥测不可关**。即便玩家拒绝,代码还偷偷发。**法律风险 + 信任风险**。一旦被曝光,玩家口碑崩盘。

**反模式 5:遥测数据用于付费墙算法**。"this player dies a lot, offer microtransaction"。**操纵,不道德,长期看是商业自杀**。

## 9 · 延伸

- GameAnalytics 文档:https://gameanalytics.com/docs/
- Sentry Rust SDK:https://docs.sentry.io/platforms/rust/
- GDPR 官方:https://gdpr.eu/
- COPPA(FTC):https://www.ftc.gov/business-guidance/privacy-security/childrens-privacy
- "Telemetry-Driven Game Development"(GDC 2018 演讲)
- "Ethics in Game Analytics"(Eric Zimmerman 文章)
- ClickHouse(游戏遥测常用 OLAP DB):https://clickhouse.com/
- OpenTelemetry(开源遥测标准):https://opentelemetry.io/

遥测不是"加个 Google Analytics"那么简单。它是工程、隐私、伦理的交叉。**做得好,你的游戏进化速度比别人快 10 倍;做得差,你失去玩家信任**。从 day 1 把架构搭对,后期成本最低。
