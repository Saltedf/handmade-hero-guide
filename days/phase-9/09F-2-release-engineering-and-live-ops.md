---
phase: 9
sequence: "9F"
module: 2
title_en: "Release Engineering & Live-Ops"
title_zh: "发布工程与实时运营:发售那一天,工作才真正开始"
type: deep-dive
difficulty: 4
duration: "2.5-3 小时"
domains: [game, rust, engineering, ops, network]
prereqs: ["09F-1-ci-cd-and-build-engineering"]
calibration: "游戏发布工程(patching/DLC/崩溃上报/平台服务)+ live-ops/telemetry→action"
---

# 09F-2 · 发布工程与实时运营:发售那一天,工作才真正开始

## 0 · 一个你从未见过的崩溃,从地球另一端飞回来

你发布 1.0 了。这是值得停下来喝一杯的时刻——Casey 在 Day 667 没有走到这一步,你走完了。Steam 商店页面上线,第一批玩家买了游戏,论坛里出现第一批"这游戏不错"的帖子。你深呼吸,觉得最艰难的部分过去了。

凌晨三点,你的手机震了。你打开 Sentry 后台——一个崩溃报告,堆栈顶端的函数叫 `particles::emitter::tick`。你盯着这行字,心想:"这个函数我跑了几千次,从来没崩过。"报告里附带的 breadcrumb 显示,玩家崩之前正在第三关的某个特定角落,触发了某个粒子效果。你在自己的开发机上试了一整夜,无法复现。

第二天早上,后台多了 47 个同样的崩溃,来自 47 个你素未谋面的玩家。他们的共同点:都用集成显卡,显存只有 512 MB,而你的粒子系统在那种机器上一次性分配了一个 2 GB 的 buffer。你的开发机是 RTX 4080,你永远在它上面测不出这个问题。**一个 crash,从一个玩家手里是噪声;同样的 crash,从两百个玩家手里飞回来,就是一场火灾。** 而你之所以能在 24 小时之内看到这场火灾、定位到那一行代码、发布修复,完全是因为你在发售之前,把"发布工程"和"实时运营"(live-ops)这套基础设施搭好了。

这一篇讲的就是这套基础设施。它涵盖五块内容:**存档版本演化**(你的存档格式必须活过每一个 patch,这是 phase-8/savegame-and-serialization 的延续)、**补丁与差分更新**(玩家不该为一个 50 MB 的修复重新下载 20 GB 的游戏)、**DLC 与可挂载内容**(发售之后再加内容,不重编核心)、**崩溃上报**(玩家崩了,你立刻知道、立刻能定位)、**遥测到行动的闭环**(把 phase-8/telemetry-short 里那个最小系统扩成"数据驱动决策"的完整闭环)。最后是平台服务(Steam 成就 / 排行榜 / 云存档 / 匹配,跟 9E-4 接上)和**热修管线**(线上烧起来了,你多快能发一个修复出去)。

发售那天不是终点,是起跑线。从那一刻起,你的工程能力决定你的游戏能不能活下来、能不能迭代、能不能成长。这一篇就是讲怎么活下来。

## 1 · 存档的版本演化:玩家三十小时的进度,不能被你的 patch 抹掉

先把最容易被忽视、也最容易出灾难的一块讲了。存档兼容性。

你在 phase-8/savegame-and-serialization 里已经写了第一个版本化的存档系统。你知道了 schema evolution 是个真问题:你 v1.0 发售,玩家玩到 30%,然后你发了 v1.1 加了新武器和新任务,**玩家的 v1.0 存档必须能在 v1.1 加载**,新加的字段要有合理默认值,删掉的字段要被忽略。这是前向 + 后向双重兼容。这一节我要把这件事从"理论上的好习惯"讲到"实操上必须做的工程纪律",因为你发售之后,每一次 patch 都是一次 schema evolution 的考验。

考虑一个具体的场景。你 v1.0 的存档里,玩家角色长这样:

```rust
// save_schema_v1.rs
#[derive(Serialize, Deserialize)]
pub struct PlayerSaveV1 {
    pub max_hp: i32,
    pub hp: i32,
    pub x: f32,
    pub y: f32,
    pub inventory: Vec<ItemId>,
    pub gold: i32,
}
```

发售三周后,你收到反馈:"游戏后期太简单,玩家囤了一堆治疗药水,所有 boss 都没挑战。"你决定加一个**耐力系统**(stamina)——玩家释放技能消耗耐力,耐力不恢复满就不能再放。这是一个核心机制改动,意味着存档里得多一个字段 `stamina`。你的新结构是:

```rust
// save_schema_v2.rs
#[derive(Serialize, Deserialize)]
pub struct PlayerSaveV2 {
    pub max_hp: i32,
    pub hp: i32,
    pub max_stamina: i32,   // 新增
    pub stamina: i32,        // 新增
    pub x: f32,
    pub y: f32,
    pub inventory: Vec<ItemId>,
    pub gold: i32,
    pub last_rested_at: u64, // 新增:上次休息的游戏时间,用于耐力恢复
}
```

直接把 `PlayerSaveV2` 喂给反序列化器读 v1 存档,会失败——v1 的字节流里根本没有 `max_stamina` 这个字段。如果你用 JSON 或 serde 的 `#[serde(default)]` 标注,新字段会自动取默认值(0),但 0 耐力意味着玩家加载存档后一上来就不能放技能,这是不可接受的体验。你需要的是一次**显式的迁移**:把 v1 的存档,转换成 v2 等价的状态,而且要按游戏设计补一个"合理的初始耐力值"。

工业实践的做法是给存档格式加一个**版本头**,然后写一条迁移函数链。每个版本都有自己的反序列化逻辑,旧版本读完之后,经过一条 `migrate_v1_to_v2` 函数,转成新版本的内存表示。这套链条是单向的、累计的:你可以从 v1 一路迁移到 v5,但你不需要写"v1 直接到 v5"的特例,你只需要写 v1→v2、v2→v3、v3→v4、v4→v5 这四步,然后链式调用。

具体到代码,这套机制长这样:

```rust
// save_migration.rs
use serde::{Serialize, Deserialize};

// 每个版本都是一个独立的、明确的 struct。
// 永远不要"在原 struct 上加字段然后改版本号" —— 那会让你失去对历史格式的精确描述。
#[derive(Serialize, Deserialize, Clone)]
pub struct PlayerSaveV1 {
    pub max_hp: i32,
    pub hp: i32,
    pub x: f32,
    pub y: f32,
    pub inventory: Vec<ItemId>,
    pub gold: i32,
}

#[derive(Serialize, Deserialize, Clone)]
pub struct PlayerSaveV2 {
    pub max_hp: i32,
    pub hp: i32,
    pub max_stamina: i32,
    pub stamina: i32,
    pub x: f32,
    pub y: f32,
    pub inventory: Vec<ItemId>,
    pub gold: i32,
    pub last_rested_at: u64,
}

// 当前最新版本 —— 整个代码库其它地方只认这个。
pub type PlayerSaveCurrent = PlayerSaveV2;
pub const SAVE_VERSION: u32 = 2;

// 迁移函数:把 v1 升级到 v2。
// 注意两件事:(1) 新字段不是填 0,是按游戏设计填一个合理初值;
//            (2) 迁移是纯函数,没有副作用,可以反复测。
pub fn migrate_v1_to_v2(v1: PlayerSaveV1, now_game_time: u64) -> PlayerSaveV2 {
    PlayerSaveV2 {
        max_hp: v1.max_hp,
        hp: v1.hp,
        // 老玩家的耐力按等级给一个起点,不要让他们上来就废
        max_stamina: 100,
        stamina: 100,
        x: v1.x,
        y: v1.y,
        inventory: v1.inventory,
        gold: v1.gold,
        last_rested_at: now_game_time,
    }
}

// 存档文件头:魔数 + 版本号 + CRC。魔数防止把别的文件当存档读。
#[derive(Serialize, Deserialize)]
pub struct SaveHeader {
    pub magic: [u8; 4],      // b"HHSV"
    pub version: u32,
    pub crc32: u32,
}

// 反序列化 + 自动迁移的统一入口。
pub fn load_player_save(bytes: &[u8], now_game_time: u64)
    -> Result<PlayerSaveCurrent, LoadError>
{
    if bytes.len() < 12 { return Err(LoadError::TooShort); }
    let (header_bytes, body) = bytes.split_at(12);
    let header: SaveHeader = bincode::deserialize(header_bytes)?;

    if &header.magic != b"HHSV" {
        return Err(LoadError::BadMagic);
    }
    // CRC 校验 —— 检测磁盘错误 / 玩家手改 / 传输损坏
    let computed = crc32fast::hash(body);
    if computed != header.crc32 {
        return Err(LoadError::CrcMismatch);
    }

    // 按 header.version 分发到对应版本的反序列化,然后一路迁移上来
    match header.version {
        1 => {
            let v1: PlayerSaveV1 = bincode::deserialize(body)?;
            Ok(migrate_v1_to_v2(v1, now_game_time))
        }
        2 => {
            let v2: PlayerSaveV2 = bincode::deserialize(body)?;
            Ok(v2)
        }
        v => Err(LoadError::UnknownVersion(v)),
    }
}
```

这套设计有几个值得强调的细节。

第一,每个版本是一个**独立的 struct**。新手最容易犯的错是"在原 struct 上加字段、然后改 `SAVE_VERSION`"。这么做的后果是:三个月后你已经忘了 v1 长什么样,你想写迁移函数都没得写——因为你的代码里只有一个 struct,它代表的是"当前版本"。把每个版本都钉成一个独立的、永不修改的 struct,你才有了一个"存档格式的历史档案",任何时候你都能精确地描述"v1 的字节流长什么样"。

第二,迁移函数必须是**纯函数**,而且**每一个都要有单元测试**。迁移是 9A-2 里讲过的"纯函数核心"的典型例子——给定一个 v1 输入,产出确定的 v2 输出,没有副作用。这意味着它极易测,你也必须给它写 property test:随机生成合法的 v1 存档,迁移到 v2,检查所有保留字段值不变。这种 property test 是 catch "迁移函数不小心把 gold 写丢了" 这类 bug 的最锋利工具,在 9A-4 里你写过类似的回归网,这里直接复用思路。

第三,**永远不要破坏老存档**。我见过一个真实案例:某独立游戏在 v1.2 把 `inventory` 字段从 `Vec<ItemId>` 改成了 `Vec<ItemStack>`(因为要支持堆叠),开发者直接改了 struct,没写迁移,发售一周内成百上千的老玩家加载存档时 inventory 全变空。Steam 评价一夜之间从"特别好评"跌到"褒贬不一"。修复办法只能是把存档格式重新设计成"先反序列化成 v1 的 `Vec<ItemId>`,再迁移成 v2 的 `Vec<ItemStack>`(每个 ItemId 变成一个数量为 1 的 ItemStack)"。一个本该在发售前就想清楚的迁移函数,变成了一次危机公关。这个故事的教训:**存档格式是契约,不是代码**。一旦发售,你就欠所有玩家一个"他们的存档永远能读"的承诺。

最后,这套机制也可以**降级**——把 v2 存档写成 v1 格式。这听起来怪,为什么要降级?两个场景:一是云存档跨版本同步(玩家在 v1.1 机器上玩了,云同步到一台还没更新到 v1.1 的机器,后者必须能读一个"近似"的存档);二是回滚一个失败的 patch(你发了 v1.2,引入了新 bug,你想退回 v1.1,但玩家在 v1.2 已经玩了半小时,他们的存档是 v1.2 的)。降级比升级难得多,因为你得决定怎么"丢失"新字段——通常的做法是写一个 `downgrade_v2_to_v1` 函数,把新字段丢弃或合并。工业级游戏会同时维护升级和降级两条链路,这是 live-ops 的硬要求。

到这里你应该看出来了:存档版本演化不是"发布之后才操心"的事,它在发售之前就要设计好骨架。**发售的那一刻,你的存档格式就被钉死了,之后每一次改动都得照顾老存档。** 这就是为什么 phase-8/savegame-and-serialization 把它列为"五大问题"之一,这一节是把那篇的"理论"落地成发售后的"实操"。

## 2 · 补丁与差分更新:50 MB 的修复,不该让玩家重下 20 GB

存档兼容性解决了"老存档能读",补丁系统解决"老二进制能升级到新二进制"。这两件事是发售后的两条平行管线,缺一不可。

最朴素的补丁策略是**整包重下**:你发了 v1.1,玩家重新下载整个游戏。简单粗暴,在 1990 年代大家就这么干。问题是,你的游戏可能 20 GB,而 v1.1 只是修了一个粒子系统的 bug,改动总量 50 MB。让全球几万玩家每人重下 20 GB,带宽成本爆炸,玩家体验爆炸(Steam 的差分下载、Epic 的下载,玩家付费的不耐烦)。这在一周内连续发三个 hotfix 的场景下是不可持续的。

工业方案是**差分补丁**(delta patching):只发"变化的部分"。实现上有两条路线,我们分别讲。

第一条路线是**二进制差分**。你拿 v1.0 的可执行文件 `game.exe` 和 v1.1 的 `game.exe`,用一个 diff 算法算出两者的差异,产出一个小小的 patch 文件。玩家那边有一个 patcher,读这个 patch 文件,应用到本地的 v1.0 `game.exe`,产出 v1.1 的 `game.exe`。经典的算法是 bsdiff / bspatch,以及 Google 的 Courgette(Chrome 用它发更新,Courgette 特别针对可执行文件做了优化,能让"地址重定位导致的差异"大幅缩小)。Rust 生态里有 `bidiff` / `bsdiff` crate。流程在构建侧长这样:

```bash
# 在 CI 里(09F-1 讲过 CI),每次发新版本都做一次差分。
# 假设你已经构建并归档了上一版,作为基线。
mkdir -p artifacts/v1.1/patches

# 对每个文件算 diff。这里示意,实际是遍历整个安装目录的每个文件。
bidiff artifacts/v1.0/game.exe \
      artifacts/v1.1/game.exe \
      artifacts/v1.1/patches/game.exe.bsdiff

# 生成一份 manifest:列出哪些文件变了、对应哪个 patch。
cat > artifacts/v1.1/manifest.json <<'EOF'
{
  "version": "1.1",
  "baseline": "1.0",
  "files": [
    { "path": "game.exe",        "patch": "patches/game.exe.bsdiff", "size": 81234 },
    { "path": "assets/textures/particles.png", "patch": "patches/particles.png.bsdiff", "size": 4096 }
  ]
}
EOF
```

玩家这边的 patcher 收到 manifest,逐个文件应用 patch:

```rust
// patcher.rs(简化,真实实现要校验哈希、处理中断恢复、断点续传)
use sha2::{Sha256, Digest};

pub fn apply_patch(baseline_dir: &Path, patch_dir: &Path, manifest: &Manifest)
    -> Result<(), PatchError>
{
    for entry in &manifest.files {
        let baseline_file = baseline_dir.join(&entry.path);
        let patched_file = baseline_dir.join(&entry.path); // 原地替换
        let patch_file = patch_dir.join(&entry.patch);

        // 1. 应用 bsdiff,产出一个新文件到临时位置
        let tmp = patched_file.with_extension("patching_tmp");
        bspatch::apply(&baseline_file, &patch_file, &tmp)?;

        // 2. 校验产出文件的哈希 —— 防止 patch 损坏产出错误的二进制
        let mut hasher = Sha256::new();
        let mut f = File::open(&tmp)?;
        io::copy(&mut f, &mut hasher)?;
        let actual_hash = hasher.finalize();
        if actual_hash.as_slice() != entry.expected_sha256.as_slice() {
            std::fs::remove_file(&tmp)?;
            return Err(PatchError::HashMismatch(entry.path.clone()));
        }

        // 3. 原子替换
        atomic_rename(&tmp, &patched_file)?;
    }
    Ok(())
}
```

二进制差分的优点是实现简单、对任意文件都通用。缺点是**可执行文件的 diff 通常比"逻辑变化"大得多**——你只改了一行代码,但编译器重新分配了所有函数的地址,导致二进制层面大片字节都"变了",diff 文件还是不小。Courgette 这种工具就是治这个的,但实现复杂。

第二条路线是**分块差分**(chunk-based delta),这是 Steam、Epic、主机商店这类大规模分发系统的实际做法。核心思想:把游戏的整个安装目录切成固定大小的**块**(chunk,通常是 1 MB),给每个块算一个哈希。游戏的"清单"(manifest)就是一张"块哈希 → 块在 CDN 上的位置"的映射。发新版本时,你拿新版本算一遍块哈希,跟旧版本的清单一比——绝大部分块没变,只有少数块变了。玩家下载时只需要那些"哈希不一样的块",拼回完整的文件。

这套机制让"50 MB 的实际改动"真的就只下载 50 MB(再加上一个块边界的 round-up,可能 51 MB)。它的优雅之处在于:块的粒度独立于文件——一个大文件里改了一个字节,只重新下这一个文件对应的几个块,其它块不变。Steam 的下载系统就是这样的,这也是为什么 Steam 更新经常只有几十 MB,即使游戏本体几十 GB。

分块差分自己实现一套是相当大的工程量,推荐的做法是**直接用平台的现成服务**:Steam 的 SteamPipe、Epic 的 Build Patch Services、微软的 SmartDelivery、Sony 的 GP5。你不用自己造轮子,但你要知道它工作原理,这样才能正确地组织你的构建产物——比如,把"频繁变化的代码"和"几乎不变的资源"放在不同的目录或包里,这样代码 patch 不会牵连资源重下。

补丁管线还有两个工程细节值得强调。

第一是**前向更新**(forward update)的支持。玩家可能跳版本——他装的是 v1.0,中间没更新,现在 v1.3 出了,他想直接升到 v1.3。你不能假设"所有玩家都按顺序更新"。两种做法:要么为每对 (old, new) 版本都生成 diff(v1.0→v1.3、v1.1→v1.3、v1.2→v1.3,组合爆炸),要么用分块差分天然支持任意版本跳转(只需要新版本的清单 + 玩家本地有什么块,就能算出需要下载哪些块)。后者是工业首选。

第二是**回滚**(rollback)。一个 patch 发出去发现更糟——比如新版本在某个 GPU 上崩得更厉害。你必须能在几分钟内让所有玩家退回上一个版本。这要求你的 patcher 保留旧版本的备份(或者能逆向应用 patch),并且你的发布系统支持"将商店的 latest 指针指回旧版本"。这是 live-ops 的保险丝,没它你就是裸奔。

## 3 · DLC 与可挂载内容:发售之后往里加东西,不重编核心

补丁是"改已有的",DLC(downloadable content,可下载内容)是"加新的"。一个好的发布工程架构,应该让"加新内容"这件事的成本趋近于零——美术做完一组新武器模型、策划写完新关卡的脚本,你打包、上传、商店上架,玩家买了下载,内容就出现在游戏里。**不需要重编整个游戏,不需要发一个新版本主程序。**

要做到这一点,你的游戏必须在架构层面支持"可挂载内容"。这个思想在 phase-7 的资产管线里你已经接触过——资产是数据,代码只管"加载和解释数据"。DLC 是这个思想的延伸:它是一个**独立的资产包**,可以被游戏在运行时发现、挂载、使用,跟基础游戏的内容无缝融合。

具体到工程,DLC 通常是这样一个结构:

```
handmade_hero/
├── base_game.pak          # 基础游戏的所有资产,发售时打包好
├── dlc_skeleton_isle.pak  # "骷髅岛"DLC,后续发布
└── dlc_weapons_pack.pak   # "武器包"DLC
```

`.pak` 文件是你自定义的归档格式(也可以用 zip、tar,但自定义格式能让你做更精细的索引、压缩、加密)。游戏启动时,扫描所有 `.pak` 文件,把它们的资产清单合并成一个虚拟文件系统(virtual filesystem),游戏代码访问资产时走这个 VFS,完全不感知"这个贴图来自基础游戏还是 DLC"。

资产路径通常用一个**逻辑路径**抽象,比如 `textures/weapons/skeleton_bow.png`,这个路径在 VFS 里全局唯一。基础游戏的 pak 提供一个版本,DLC 可以"覆盖"或"新增"——比如 DLC 提供了 `textures/weapons/skeleton_bow.png` 的另一个版本,游戏代码读到的是 DLC 的版本(覆盖语义);或者 DLC 提供了 `textures/weapons/skeleton_axe.png`,基础游戏没有,这是新增。这一切对游戏代码是透明的,它只管 `vfs.open("textures/weapons/skeleton_axe.png")`。

代码层面,一个最小 VFS 长这样:

```rust
// virtual_filesystem.rs
use std::collections::HashMap;
use std::io::Read;

pub trait PakSource: Send + Sync {
    fn open(&self, logical_path: &str) -> Option<Vec<u8>>;
    fn list(&self) -> Vec<String>;
}

pub struct VirtualFilesystem {
    // 后挂载的源优先,允许 DLC 覆盖基础游戏资产
    sources: Vec<Box<dyn PakSource>>,
    index: HashMap<String, usize>, // logical_path -> source index
}

impl VirtualFilesystem {
    pub fn mount(&mut self, source: Box<dyn PakSource>, priority: MountPriority) {
        // 重新构建索引:高优先级的源覆盖低优先级的同名资产
        let idx = match priority {
            MountPriority::Base => 0,
            MountPriority::Dlc => self.sources.len(),
        };
        // ... 更新 self.index,让每个 logical_path 指向优先级最高的源
    }

    pub fn open(&self, logical_path: &str) -> Option<Vec<u8>> {
        let idx = *self.index.get(logical_path)?;
        self.sources[idx].open(logical_path)
    }
}
```

DLC 不仅是资产,还可能包含**逻辑**——新关卡有新的敌人 AI、新的脚本、新的游戏规则。这就要求你的游戏逻辑本身也是"数据驱动"的:敌人 AI 不是硬编码在 Rust 里,而是一个数据文件(行为树、脚本、或者你 phase-5 学过的 ECS 数据),DLC 提供这个数据文件,游戏引擎的解释器加载它,新的敌人行为就出现了。你的代码里没有任何"骷髅岛"这个字眼,骷髅岛完全由 DLC 的数据定义。

这一点跟 9B-4 的 CVar 系统、phase-7 的资产管线是同一条哲学的延伸:**代码是通用引擎,内容是数据**。这条哲学贯彻得越彻底,"加 DLC"就越便宜。贯彻得不好的游戏,加一个 DLC 要改十几个源文件、重编整个游戏、重新认证——成本和风险都极高,这种项目通常就放弃 DLC 战略了。

最后提一句**版本依赖**。DLC 通常依赖某个最低版本的基游戏(DLC 用了 v1.2 才有的引擎功能),你的挂载系统要检查这种依赖,版本不够时拒绝挂载并提示玩家"请先更新游戏"。这是和 §1 的存档版本演化、§2 的补丁版本管理相互呼应的一条线:**发售之后,"版本"成了你工程体系里无处不在的概念**。

## 4 · 崩溃上报:玩家崩了,你立刻知道、立刻能定位

回到这一篇开头那个故事——凌晨三点,Sentry 后台飞回来 47 个同样的崩溃。这一节讲清楚这套崩溃上报系统是怎么工作的,为什么它能在你睡觉的时候替你值夜班。

崩溃上报的客户端部分,核心是一段在"游戏要崩了"这一刻被强制执行的代码。Rust 里"崩了"主要是 panic(安全 Rust 里的 panic、或者 unsafe 里的 UB 被 sanitizer 抓到的 abort)。Windows 上还有 SEH 异常(原生异常,比如访问违例 0xC0000005)。你要做的是:**在进程真正死掉之前,尽可能多地收集信息,写到一个文件里,然后下次启动时上传到你的服务器。**

为什么不直接崩溃时联网上报?因为崩溃发生时,你的进程状态可能已经损坏——堆被踩烂了、栈溢出了、线程死锁了,这时候发起 HTTP 请求极可能失败。所以工业实践是 **"崩溃时只写本地 minidump,下次启动时上传"**。

Minidump 是 Windows 的一个二进制格式(.dmp 文件),里面包含了崩溃那一刻进程的关键状态:崩溃线程的调用栈、所有线程的寄存器、加载的模块列表(以及每个模块的版本)、部分内存。Linux 上对应的是 core dump,但 minidump 是跨平台的事实标准(Breakpad / Crashpad 都用它)。Rust 生态里,`minidump-writer` crate 能在 panic hook 里产出 minidump 文件。一套最小的实现:

```rust
// crash_handler.rs
use std::fs;
use std::path::PathBuf;

pub fn install_crash_handler() {
    std::panic::set_hook(Box::new(|panic_info| {
        // 1. 把 panic 信息写到 stderr(开发时方便)
        eprintln!("PANIC: {}", panic_info);

        // 2. 产出一个 minidump。真实实现会用 minidump_writer::minidump,
        //    这里展示概念。dump 路径用一个固定的、下次启动能找到的位置。
        let dump_path = crash_dump_path();
        let _ = write_minidump(&dump_path, panic_info);

        // 3. 顺手写一份"附加上下文"——游戏版本、平台、玩家 ID、最近的 breadcrumb。
        //    minidump 本身不带这些,你的上传逻辑会把 dump + 这个上下文打包发出去。
        let context = CrashContext {
            game_version: env!("CARGO_PKG_VERSION").to_string(),
            platform: format!("{}/{}", std::env::consts::OS, std::env::consts::ARCH),
            player_id: load_player_id().unwrap_or_default(),
            session_id: load_session_id().unwrap_or_default(),
            panic_msg: panic_info.to_string(),
            breadcrumbs: take_recent_breadcrumbs(),
            timestamp: now_unix(),
        };
        let _ = fs::write(
            dump_path.with_extension("context.json"),
            serde_json::to_vec(&context).unwrap_or_default(),
        );
    }));
}

fn crash_dump_path() -> PathBuf {
    let dir = platform_crash_dir(); // %APPDATA%/HH/crashes 或 ~/.config/hh/crashes
    let _ = fs::create_dir_all(&dir);
    dir.join(format!("crash-{}.dmp", now_unix()))
}
```

注意这套机制覆盖了 Rust 的 panic,但**不覆盖原生异常**(比如 C 绑定里的段错误)。要覆盖原生异常,你需要平台特定的处理:Windows 上注册一个 Vectored Exception Handler,Linux 上注册一个 SIGSEGV/SIGABRT 的 signal handler。这些 handler 里能做的事非常有限(不能分配内存、不能拿锁),通常只能调用一组预先写好的、async-signal-safe 的函数把 dump 写出来。`crashdump` / `minidump-writer` 这些 crate 替你封装了这些细节。完整覆盖 panic + 原生异常,你的崩溃上报才算真正落地。

服务端部分是一个**崩溃聚合系统**(crash aggregation server)。它接收 minidump + 上下文,做三件事:**符号化、聚合、triage**。

符号化(symbolication)是把 minidump 里的二进制地址(比如 `0x00007FF6A1234567`)映射回源代码的位置(比如 `particles::emitter::tick at src/particles.rs:142`)。这要求你**保留了发布版本的调试符号**(debug symbols,PDB 文件 / DWARF 信息)。这就是为什么 09F-1 里讲 CI/CD 时强调"每个发布构建都要归档它的符号文件"——没有符号,你拿到的崩溃报告就是一堆十六进制地址,毫无用处。归档的纪律是:**任何一个曾经对外发布的构建,它的符号必须能找到**。三周后玩家崩了,你还得能用三周前那个版本的符号解析。

聚合(aggregation)是把"看起来是同一个 bug 的崩溃"合并成一个问题(issue)。判断"同一个 bug"的标准通常是**崩溃栈的最上面几帧的哈希**(叫 crash signature 或 stack hash)。47 个玩家的崩溃,栈顶都是 `particles::emitter::tick` 同一行,它们的 signature 相同,聚合系统把它们归到同一个 issue,显示"这个 issue 影响了 47 个玩家,发生了 89 次"。这就是开头那句"一个 crash 是噪声,200 个同样的 crash 是火灾"的技术实现——你看到的不是 200 条孤立日志,而是一个有计数的 issue,直接告诉你"该优先修这个"。

Triage 是人工环节。你的后台每天显示一批 issue,按"受影响玩家数 × 发生频率"排序,工程师挑最上面的几个分配责任、写复现 case、修。Backtrace 和 Sentry 这两个 SaaS 服务把符号化 + 聚合 + triage 界面全包了,如果你不想自己搭,直接用它们就行。自建的好处是数据完全在手里(尤其是玩家隐私敏感的场景),但维护成本不低。

服务端的伪代码(关键逻辑,省略 HTTP 层):

```python
# crash_server.py(伪代码,只展示聚合的核心逻辑)
import hashlib
from collections import defaultdict

# 存所有 issue 的内存结构(真实实现用数据库)
issues = {}              # crash_signature -> Issue
player_to_issues = defaultdict(set)  # player_id -> set of signatures

def handle_crash_upload(minidump_bytes, context_json):
    # 1. 符号化:把 minidump 里的地址,用对应版本的符号,映射回源行
    frames = symbolicate(minidump_bytes, context_json['game_version'])
    # frames = [
    #   {"module": "game.exe", "function": "particles::emitter::tick",
    #    "file": "src/particles.rs", "line": 142},
    #   ...
    # ]

    # 2. 算 crash signature:栈顶 N 帧的"函数名 + 文件 + 行"的哈希
    top = frames[:5]  # 栈顶 5 帧通常足够区分 bug
    sig_input = "|".join(f"{f['function']}@{f['file']}:{f['line']}" for f in top)
    signature = hashlib.sha256(sig_input.encode()).hexdigest()[:16]

    # 3. 聚合:第一次见到的 signature 创建 issue,否则累加计数
    if signature not in issues:
        issues[signature] = Issue(
            signature=signature,
            first_seen=context_json['timestamp'],
            last_seen=context_json['timestamp'],
            count=0,
            affected_players=set(),
            example_frames=frames,
            example_context=context_json,
        )
    issue = issues[signature]
    issue.count += 1
    issue.last_seen = context_json['timestamp']
    issue.affected_players.add(context_json['player_id'])
    player_to_issues[context_json['player_id']].add(signature)

    # 4. 排序展示:按 affected_players 数排,顶部就是"火灾"
    return signature

def top_issues_by_impact(limit=20):
    return sorted(issues.values(),
                  key=lambda i: len(i.affected_players),
                  reverse=True)[:limit]
```

这套系统跑起来之后,你的工作流是这样的:早上起来打开后台,看到 top issue 是"particles::emitter::tick,影响 312 个玩家",点进去看一个完整的栈、最近一次的 breadcrumb("玩家触发了 boss 死亡时的爆炸粒子")、一个示例 minidump,你在本机用同一版本的符号复现,五分钟定位到那个 2 GB buffer 的分配。你写修复、跑回归(9A-4 的回归网在这里保护你)、走热修管线(本篇 §7 讲)发出去。从"玩家崩"到"修复上线",几个小时。**这就是 live-ops 的速度。**

注意一个伦理细节:崩溃上报会附带玩家信息(玩家 ID、IP、硬件配置),这都属于个人数据,**必须遵守 phase-8/telemetry-short 里讲的 GDPR / COPPA / PIPL 合规要求**——首次启动的同意弹窗、可关闭、可删除。Sentry / Backtrace 的服务端会帮你做匿名化,但责任最终在你。

## 5 · 从遥测到行动:把 phase-8 的最小系统扩成闭环

崩溃上报是"被动响应"——等事情炸了才知道。遥测(telemetry)是"主动观察"——即使没崩,你也知道玩家的体验怎么样。phase-8/telemetry-short 里你已经写了一个最小的遥测系统,这一节把它扩展成一个"数据驱动决策"的完整闭环:埋点 → 聚合 → 可视化 → 行动 → 验证。

埋点(instrumentation)是在游戏代码的关键位置调用 `telemetry.track(event_type, data)`。phase-8 那篇埋了 `game_start`、`player_death`、`level_complete` 这几个事件。发售之后,你要有意识地、按问题来扩展埋点。注意,埋点的原则 phase-8 已经强调过:**每个数据点要回答一个具体问题**。下面是几个发售之后特别高价值的问题,以及对应的埋点:

**"玩家在哪里死最多?"**——这是平衡性调试的核心问题。你可能在内部测试觉得某个 boss 难度适中,结果发售发现 60% 玩家在这卡了一小时。埋点是 `player_death`,带 `level`、`x`、`y`、`death_cause`。聚合后画一张热力图(heatmap),地图上死亡密度高的地方亮红——你立刻看到"哦,第二章那个 boss 旁边的陷阱,玩家死得比 boss 还多",这可能是一个 level design 问题,不是 boss 难度问题,你光看"通关率"是看不出来的。

**"玩家在哪里退出游戏?"**——留存分析。埋点是 `session_end`,带 `last_level`、`last_event`、`session_duration`。聚合后看"玩家退出前最后在哪个关卡"的分布。如果发现 30% 玩家退出前都在第三关开头,那第三关开头就有问题(可能加载太久、可能难度陡增、可能有个 bug 让玩家以为游戏坏了)。这种洞察是评测和论坛反馈给不了的——玩家不爽了不会发帖,他们直接卸载,你只在数据里看到他们消失了。

**"加载时间在不同硬件上分布如何?"**——性能问题。埋点是 `level_loaded`,带 `level`、`load_time_ms`、`gpu_model`、`ram_gb`。聚合后画一张"load_time 分布 vs GPU 型号"的图。你可能会发现集成显卡玩家加载时间是独显玩家的 3 倍——这驱动你去优化(异步加载、流式加载),让你的游戏在低端机上也能玩。这种优化优先级,只能从遥测来。

行动(action)是遥测闭环里最容易被忽视的一环。很多团队埋了点、存了数据、画了图,然后呢?图挂在 dashboard 上没人看。数据驱动决策的"决策"那一步,需要纪律:**每周固定时间(比如周一上午),产品 + 设计 + 工程一起看 dashboard,挑出 top 3 问题,每个问题分配一个责任人 + 一个 deadline。** 没有这个纪律,遥测就是装饰品。

最后一步是**验证**。你基于遥测做了一个改动(比如把第二章 boss 的血量降低 15%),下一个 patch 发出去之后,你要看遥测数据有没有变化——"那个 boss 的 player_death 频率有没有下降?通关率有没有上升?" 如果没有,你的改动可能没生效,或者问题不在血量。这一步叫 A/B 测试的雏形:更严格的版本是 canary rollout(本篇 §7 讲),把改动先发给 5% 玩家,对比另外 95% 的遥测,确认改动有效再全量。

整个闭环可以画成一条线:**埋点 → 聚合 → 可视化 → 假设 → 改动 → 发版 → 验证 → 埋点(下一轮)**。这条线跑得越快,你的游戏迭代得越快。一个一个月才发一次版的团队,这条闭环是一个月一圈;一个每周发版的 live-ops 团队,是一周一圈。差距会以复利累积。

让我把 phase-8 那个 `TelemetrySystem` 扩一下,加几个发售之后常用的具体埋点。原系统的 `track(event_type, data)` 已经够通用,这里只是补具体的事件类型:

```rust
// gameplay_events.rs —— 在 phase-8 的 TelemetrySystem 上扩展的具体埋点
use crate::telemetry::TelemetrySystem;
use crate::state::GameState;
use serde_json::json;

// 玩家死亡 —— 平衡性和关卡设计的核心信号
pub fn track_player_death(t: &TelemetrySystem, s: &GameState) {
    t.track("player_death", json!({
        "level": s.current_level,
        "x": quantize(s.player.x, 32.0),  // 量化到 32 像素,聚合密度
        "y": quantize(s.player.y, 32.0),
        "death_cause": s.last_damage_source,
        "time_in_level_s": s.level_time,
        "deaths_in_level": s.deaths_in_level,
    }));
}

// 玩家退出 —— 留存分析的关键,要知道"他最后停在哪"
pub fn track_session_end(t: &TelemetrySystem, s: &GameState, reason: SessionEndReason) {
    t.track("session_end", json!({
        "last_level": s.current_level,
        "last_event": s.last_event_name,
        "session_duration_s": s.session_time,
        "reason": reason,  // ManualQuit / Crash / LostFocus / OOM
    }));
    // 退出时强制 flush,因为玩家可能不会很快再启动
    t.flush();
}

// 关卡加载完成 —— 性能基线
pub fn track_level_loaded(t: &TelemetrySystem, level: &str, load_ms: u64, gpu: &str) {
    t.track("level_loaded", json!({
        "level": level,
        "load_time_ms": load_ms,
        "gpu": gpu,
    }));
}

fn quantize(v: f32, step: f32) -> f32 {
    (v / step).round() * step
}
```

`quantize` 那个小函数值得单独提一句。死亡位置如果是浮点的原始坐标,几乎每个玩家的位置都不一样,你画热力图时每个点都是孤立的,看不出密度。把坐标量化到 32 像素的格子(或者更大,64、128),同一个格子里的死亡合并成一个点,密度立刻可见。这是遥测聚合的一个常用技巧:**数据存原始值时尽量精确,但展示时按"问题需要的粒度"聚合**。

服务端的聚合逻辑跟 §4 的崩溃聚合很类似,只是事件的 schema 不同。最简的栈是:游戏 → HTTP → 一个 Rust/Python/Node 服务 → ClickHouse / Postgres → Grafana。ClickHouse 是游戏行业的事实标准 OLAP 数据库,因为它对"几亿条事件,按维度聚合"这种查询优化得极好,phase-8/telemetry-short 已经推荐过。Grafana 是可视化层,画时间序列、热力图、漏斗图都很好。这一层不需要自己造,搭起来一个最小 dashboard 大概一周的工作量。

一个伦理重申:phase-8/telemetry-short 里讲过的 dark pattern、re-identification 风险、opt-in/opt-out,在发售之后**只会被放大**——因为玩家数量从内部测试的几十个变成发售后的几万、几十万个。任何"我们只采集匿名数据"的承诺,在大规模数据面前都更容易被打破。**伦理清单要每季度 review 一次**:数据保留时间是不是还在限制内?有没有不知不觉开始采集新字段?有没有被用于付费墙算法?这是发售之后长期的责任。

## 6 · 平台服务:成就、排行榜、云存档、匹配

发售之后,除了你自己搭的基础设施,还有一组**平台 SDK** 提供的服务——Steam、Epic、PlayStation Network、Xbox Live、Nintendo Network 各有自己的一套。它们解决的是"每个游戏都要做、但每个游戏自己重新做没意义"的那一类问题:成就、排行榜、云存档、好友列表、匹配、邀请。

每家平台的 API 不一样,但它们解决的问题高度重叠,你可以抽象出一组"平台服务"的 trait,Rust 里实现一个 Steam 后端、一个 Epic 后端,游戏代码只面向 trait。这就是 9B-2 讲过的"子系统抽象"在 live-ops 这一层的应用。

```rust
// platform.rs —— 平台服务的抽象层
pub trait PlatformService {
    fn unlock_achievement(&self, id: &str) -> Result<(), PlatformError>;
    fn submit_score(&self, leaderboard_id: &str, score: i64) -> Result<(), PlatformError>;
    fn upload_cloud_save(&self, slot: u32, data: &[u8]) -> Result<(), PlatformError>;
    fn download_cloud_save(&self, slot: u32) -> Result<Option<Vec<u8>>, PlatformError>;
    fn find_match(&self, params: MatchParams) -> Result<MatchTicket, PlatformError>;
}

// Steam 实现
pub struct SteamService { /* steamworks crate 的 client */ }
impl PlatformService for SteamService {
    fn unlock_achievement(&self, id: &str) -> Result<(), PlatformError> {
        self.client.achievement(id).set()?;
        self.client.store_stats(); // 异步上传到 Steam 后台
        Ok(())
    }
    // ... 其它方法
}

// 测试用 / 无平台 fallback
pub struct NoopPlatformService;
impl PlatformService for NoopPlatformService {
    fn unlock_achievement(&self, _: &str) -> Result<(), PlatformError> { Ok(()) }
    fn submit_score(&self, _: &str, _: i64) -> Result<(), PlatformError> { Ok(()) }
    // ...
}
```

这套抽象让你能在一个 `NoopPlatformService` 上开发(没有 Steam SDK 也能跑游戏),只在发售构建时换成 `SteamService`。这跟 9A-1 讲的"依赖注入让代码可测"是同一套思想。

平台服务里跟 live-ops 最相关的两块:**云存档**和**匹配**。

云存档是 Steam / Epic / 主机会替你做的"存档云端同步"。你只要把存档写到一个"Steam 管的目录",平台 SDK 替你把它同步到云端,玩家在另一台机器上启动游戏时,SDK 把云端存档拉下来。听起来很美好,但有一个真实的工程陷阱:**冲突解决**。玩家在机器 A 玩了 1 小时,关机,Steam 同步存档到云端。然后他在机器 B 启动游戏,Steam 同步了云端版本下来——但机器 B 上有一个**更老的本地存档**(他昨天在 B 上玩过),现在 B 的本地 vs 云端,哪个新?SDK 通常用时间戳决定,但**两个机器的时钟可能不同步**,导致旧存档覆盖新存档。你的存档系统必须能处理这种情况——通常的做法是,在存档里嵌一个单调递增的 `save_counter`(每次保存自增 1),冲突时比较 counter 而不是时间戳。这就是为什么 phase-8/savegame-and-serialization 把"云存档冲突"列为五大问题之一。

匹配(matchmaking)是 9E-4 的主题,这里只讲它跟 live-ops 的交叉点。发售之后,你的匹配池子里玩家多了几个数量级,匹配参数要调;同时你要面对"匹配胜率分布"这种长期遥测——某个段位的玩家平均等多久、匹配到的对手强度差多少、有没有滥用匹配系统的行为(故意输来降段位,然后碾压新手)。这些都需要匹配系统埋点 + 你后台聚合。9E-4 讲的是匹配的技术架构,这一节讲的是"匹配上线之后怎么运营",两者是同一条线。

集成平台 SDK 还有一个工程细节:**认证(certification)**。主机平台(Sony / Microsoft / Nintendo)有一套叫 TRC / TCR / Lot Check 的认证规则,规定你的游戏在用他们的服务时必须遵守什么——比如"成就解锁必须有动画提示"、"云存档失败必须弹窗告知玩家"、"匹配中离线必须给玩家奖励补偿"。这些规则是平台方的硬要求,不通过认证你就上不了架。9G 序列会专门讲认证,这里只是预告:平台服务的集成,不只是"API 调用对了",还要满足平台方的 UX 规范,这是发布工程的一部分。

## 7 · 热修管线:线上烧起来了,你多快能发出去

前面六节都是"基础设施",这一节讲一个把这些基础设施全部串起来的实战场景:**线上烧起来了,你多快能发一个修复出去?**

考虑最糟的情况:周六早上,你打开后台,发现 v1.2 在集成显卡上启动直接崩溃(crash rate 从 0.1% 跳到 12%——10% 的玩家完全进不了游戏)。Steam 评价区开始出现"启动就崩,退款"的差评。每一个小时你不修,就多几百个差评,这些差评会跟着你的游戏一辈子。这就是 live-ops 的"火灾"场景。

你的热修管线(hotfix pipeline)决定了你能不能在几小时之内发出去。一条成熟的热修管线,从"工程师开始修"到"玩家拿到修复",要走过这些步骤:**修代码 → 跑回归测试 → 构建发布版本(归档符号!)→ 算差分 patch → 内部验证 → canary 灰度发布 → 监控遥测 → 全量发布**。

这里的几个环节,前面几节都讲过基础设施:§2 的差分 patch、§4 的崩溃上报、§5 的遥测。这里要把它们串起来,并且强调两个新东西:**快速认证**(cert-quick)和 **canary 灰度**。

快速认证在 PC 平台(Steam / Epic)几乎不存在——你构建好、上传、点发布,几分钟到几小时就上线了。但主机平台(Sony / Microsoft / Nintendo)每次发版都要走认证流程,完整认证可能要几天。这就是为什么主机的热修成本极高——你最好不发,发了就一次修干净。平台方为此提供了"快速认证"通道,要求更严(改动量必须小、不能加新功能、只修关键 bug),但能在一天内通过。这条通道的使用频率是有限的(你不能每周都用),所以要省着用,只在线上火灾时走。

Canary 灰度发布(canary rollout)是 web 工程的标准实践,在游戏行业也越来越普及。它的核心思想:**别一次性发给所有人,先发给一小撮人,看遥测,没问题再扩大**。具体到 Steam,Steam 的"branches"功能支持你把新版本先发到一个分支,玩家可以选择加入这个分支(canary 队列)。或者更自动化的做法是,Steamworks 后台支持"staged rollout",你点发布时可以指定"先发给 5% 玩家",后台自动按比例分发。

Canary 的工作流长这样:你发 5%,盯着遥测 30 分钟到几小时——崩溃率有没有跳?玩家退出率有没有变?论坛 / 评价区有没有新问题?如果一切正常,你把比例调到 25%,再盯,再调到 100%。如果中间发现新问题,你**回滚**(rollback)——把商店的 latest 指针指回旧版本,canary 队列里的 5% 玩家自动回退,其他 95% 玩家根本没收到这次更新,完全无感知。

这套机制看起来繁琐,但它救命的次数远超你预期。**任何一次"全量发布"都是一次赌博**——你的测试再充分,也无法覆盖几万个玩家的硬件组合。Canary 让你把赌博的赌注从"所有玩家"降到"5% 玩家",出问题的爆炸半径缩小 20 倍。一次失败的 canary 是经验教训,一次失败的全量发布是公关灾难。

让我把整条热修管线用一个伪 shell 流程串起来(对应 09F-1 的 CI/CD 管线的延续):

```bash
#!/usr/bin/env bash
# hotfix.sh —— 线上火灾时的标准发布流程
set -euo pipefail

VERSION=$1           # 比如 1.2.1
BASELINE=$2          # 上一个稳定版,比如 1.2
CANARY_PCT=${3:-5}   # 默认 5% 灰度

# 1. 跑回归测试 —— 9A-4 的回归网在这里保护你,防止 hotfix 引入新 bug
cargo test --release
cargo fuzz run load_save -- -runs=100000   # 短 fuzz 冒烟

# 2. 构建发布版本(每个平台)
#    --remap-path-prefix 让 panic 信息里的路径是相对的,不泄露构建机路径
cargo build --release
# (省略:跨平台构建在 09F-1 里讲过)

# 3. 归档调试符号 —— 没有符号就没法符号化崩溃,绝对不能漏
mkdir -p symbols/$VERSION
cp target/release/*.pdb symbols/$VERSION/ 2>/dev/null || \
cp target/release/*.dwarf symbols/$VERSION/ 2>/dev/null || true

# 4. 算差分 patch(§2)
mkdir -p artifacts/$VERSION/patches
for f in game.exe assets/*.pak; do
    bidiff artifacts/$BASELINE/$f \
          artifacts/$VERSION/$f \
          artifacts/$VERSION/patches/$(basename $f).bsdiff
done

# 5. 上传符号到崩溃服务器(§4),上传 patch 到 CDN(§2)
upload_symbols symbols/$VERSION/
upload_patches artifacts/$VERSION/

# 6. 内部验证 —— 内部 canary 队列先跑几小时
echo "Internal QA branch updated. Manual smoke test before staging."
prompt_smoke_test_confirmation

# 7. Canary 灰度发布 —— Steamworks API 设置 staged rollout 比例
steamworks_set_staged_rollout $VERSION $CANARY_PCT
echo "Canary rollout at $CANARY_PCT%. Watch dashboards for 1-4 hours."

# 8. (人工)盯遥测 + 崩溃率,确认无 regression
#    如果 OK,手动调到 100%:
#      steamworks_set_staged_rollout $VERSION 100
#    如果不 OK,回滚:
#      steamworks_rollback_to $BASELINE
```

这一整套流程的纪律,就是 live-ops 的核心。它不是"出事了再说",而是在发售之前就把每一步都排练过——你的 CI 已经在每天构建、归档符号,你的 patcher 已经测过,你的 canary 流程在内部 QA 队列里跑过几次 dry-run。火灾来的时候,你不慌,因为流程是肌肉记忆。这是 09F-1 讲的"可重复构建"的真正用意:不是为了发售那一天,而是为了发售之后的每一天。

## 8 · 在你 HH 项目里动手(做中学红线)

这一篇的做中学有四件事,每一件都对应一个 live-ops 的核心子系统。做完这四件事,你的 HH 游戏就有了 live-ops 的脊柱——它能在玩家崩了的时候告诉你、能在你改了存档格式之后照顾老玩家、能在发售之后基于数据持续改进。

第一,**给 HH 加一个崩溃处理器,panic 时写 minidump**。这一件事的目标是让你亲自动手写一次 panic hook,亲手产出一份 dump 文件,亲眼看到"哦,这个文件就是崩溃那一刻的状态快照"。用 `std::panic::set_hook` 装上你的处理器,在里面调 `minidump_writer`(或者退一步,先用 Rust 的 `std::backtrace` 写一个简化版的"panic 时把栈写到文件"的版本)。然后**故意触发一个 panic**(在一个测试里调一个会 unwrap None 的函数),看 dump 文件有没有产出。再写一个简单的上传器:游戏下次启动时检查 crash 目录,有 dump 就 POST 到你的服务器。这一步做完,你就有了一个端到端的崩溃上报闭环。

第二,**写一个最小的崩溃收集服务器**。它不需要做完整的符号化——你可以从"接收 POST,存到文件,按 panic_msg 字段聚合计数"开始。用 Rust 的 `axum` 或者 Python 的 Flask 都行,目标是一个能在本机跑、能接收客户端发来的 dump + context 的 HTTP 服务。它每次收到 dump,按 panic 消息的前 100 字符算一个 signature,聚合到 `HashMap<String, u32>`(signature → count)。提供一个 GET 端点列出 top crashes。这一步做完,你就理解了"为什么一个 crash 是噪声、200 个同样的 crash 是火灾"——你能从服务端的计数里直接看到。

第三,**给 HH 的存档加版本化,实现一次 v1 → v2 的迁移**。如果你 HH 项目还没有存档系统,先按 phase-8/savegame-and-serialization 写一个最简的(把 `PlayerState` 序列化到 JSON 文件)。然后给它加 §1 那套:加 `SaveHeader`(魔数 + 版本号 + CRC),把当前的存档格式定义为 v1。然后**故意改一下存档结构**——比如给 player 加一个 `stamina` 字段,这就是 v2。写 `migrate_v1_to_v2`,写一个 v1 的存档文件,验证你能在 v2 的代码里读它。**再写一个 property test**:随机生成合法的 v1 存档,迁移到 v2,检查保留字段值不变。这一步做完,你就内化了"存档是契约"这条工程纪律,你发售之后再也不敢随手改存档 struct 了。

第四,**给 HH 埋三个游戏事件,服务端聚合并可视化**。在本篇 §5 的扩展埋点里挑三个:`player_death`、`session_end`、`level_loaded`。在游戏代码里 hook 这三个事件,通过 phase-8/telemetry-short 的 `TelemetrySystem` 发到你 §2 写的服务端(把它扩展成接收所有事件,不只是 crash)。服务端用一个简单的聚合:`SELECT level, COUNT(*) FROM events WHERE type='player_death' GROUP BY level`。再用 Grafana(或者一个手写的 HTML 页面,显示 JSON 数据)画一张"每关死亡次数"的柱状图。**这一步做完,你第一次有了"数据告诉我玩家在哪卡住"的能力——这是猜测变成数据驱动决策的转折点。**

做完这四件事,你的 HH 游戏就有了 live-ops 的脊柱。你可以发售、可以收到玩家的崩溃、可以基于数据迭代、可以在不破坏老玩家存档的前提下持续更新。这就是发售之后"活下来"的工程能力。Casey 在 Day 667 没有走到这一步——你走完了。

## 9 · 练习

练习一(Lv1,概念)。这一篇的核心论点是"发售那天,工作才真正开始"。请用一段话解释:为什么"游戏代码完成"(code complete)和"游戏发布且能持续运营"不是同一件事,中间隔了哪些工程基础设施?用本篇讲过的至少三个子系统(存档版本化、补丁、DLC、崩溃上报、遥测、平台服务、热修)来支撑你的论述。

练习二(Lv2,动手)。完成 §8 的第二件事——写一个最小的崩溃收集服务器。用 `curl` 模拟客户端,POST 一份假的 crash context JSON 到你的服务器,验证聚合计数能正常累加。再 POST 50 个 signature 相同的 crash,看 top crashes 列表里它的计数是不是 50。这一步让你直观看到"火灾"是怎么在数据里浮现的。

练习三(Lv3,设计)。给你 HH 项目的存档,设计一份 v1 → v2 → v3 的迁移链。每一步选一个**真实可能的变更**:v1→v2 加一个字段(比如 stamina),v2→v3 改一个字段的类型(比如 inventory 从 `Vec<ItemId>` 变成 `Vec<ItemStack>` 支持堆叠)。给每一步写迁移函数,并思考:**从 v1 直接升到 v3 的玩家,跟先升到 v2 再升到 v3 的玩家,他们的存档最终状态一样吗?** 写 property test 验证。这个练习会让你体会到"迁移链是单向累计的、可以链式应用"的工程含义。

练习四(Lv4,系统)。实现一个最小 canary 灰度发布的模拟。修改你的 HH 游戏,让它启动时读一个本地的 `config.json`,里面有个 `feature_flags` 字段。让一个新的游戏功能(比如一个新粒子效果)只在 `feature_flags.new_particles == true` 时启用。再写一个伪"发布脚本",它"把 5% 玩家的 config 设为 true"——你可以模拟成"生成 100 个假玩家配置文件,5 个开新粒子"。观察"开新粒子的玩家"和"没开的玩家"在遥测数据(崩溃率、帧率分布)上的差异。这个练习让你亲手走一遍 canary 的逻辑,理解为什么"先 5%,再 100%"是降低发布风险的工程纪律。

## 10 · 延伸阅读与下一篇

崩溃上报的工业标准是 Google Breakpad 和它的继任者 Crashpad(Chromium 项目用,文档详尽),它们跨平台、生产级,源代码值得一读。Backtrace(现属 Sauce Labs)是游戏行业最专业的崩溃 SaaS,Unity 和 Epic 都集成了它,它的白皮书讲聚合和 triage 讲得特别清楚。Sentry 的 Rust SDK 文档是上手最快的,免费 tier 适合独立项目。

差分更新方面,bsdiff / bspatch 的论文是经典,Google Courgette 的博客文章("Smaller is Better")专门讲为什么针对可执行文件做差分要特殊处理。Steam 的 SteamPipe 文档和 Epic 的 Build Patch Services 文档,是分块差分在游戏行业的实际工程参考。如果你想自己实现 chunk-based diff,Google 的 zsync 和 rsync 的算法是基础。

遥测到行动的闭环,GDC 演讲 "Telemetry-Driven Game Development"(各年都有变体)是行业经验的金矿。ClickHouse 的官方文档对"为什么 OLAP 适合遥测聚合"讲得很透彻。OpenTelemetry 是开源遥测的标准,值得了解它的数据模型,即使你不直接用。伦理方面,Eric Zimmerman 的 "Ethics in Game Analytics" 和 phase-8/telemetry-short 引用过的 GDPR 官方站点,要每季度复习一次。

平台服务的官方文档:Steamworks SDK、Epic Online Services(跨平台,免费)、各主机的开发者门户(Nintendo Dev Portal / PlayStation Partners / ID@Xbox)。9E-4 是匹配的技术架构延伸,9G 序列会专门讲 TRC/TCR 认证,跟本篇 §6 的平台服务集成接上。

存档版本演化的工业参考,phase-8/savegame-and-serialization 已经给了完整的体系,本篇 §1 是它的发售延续。phase-8/shipping-checklist 里那张"完成的层次"清单(Code complete → Alpha → Beta → Gold → 1.0 → 1.x → EOL)是本篇的入场券——本篇所有内容都发生在 1.0 之后那一段,即 1.x → EOL 的整个生命周期;你发售之后做的每一次 patch、每一次 DLC、每一次热修,都是那张清单上"1.x"那一栏的具体内容。9A-4 的 fuzz 和回归网,是本篇 §1 存档迁移函数的测试基础设施,9A-2 的 property test 是迁移正确性的核心验证手段——你 §8 的第三件事和练习三会直接用到。9B-4 的 CVar 系统是本篇热修管线的一个延伸:某些数值平衡 hotfix 甚至不需要发版,改 CVar 配置推到客户端就行(尤其配合 live-ops 的实时下发),这是"hot-tuning in live"的实践,你在 9B-4 已经埋下了种子。

最后一句总结。发售那天,你完成了 Casey 没完成的——你上架了。但发售之后的每一天,才是游戏作为"活的产品"真正生长的阶段。能不能持续不崩、能不能基于数据改、能不能让玩家三十小时的存档永远能读、能不能在火灾发生时几小时内发修复——这些能力,全部来自你在发售之前搭好的发布工程和 live-ops 基础设施。**发售是工程的开始,不是结束。**

下一篇 [09F-3](09F-3-cross-platform-and-portability.md) 离开"运营"主题,讲游戏的**分发与商店**:从构建产物到玩家手里那条最后的路——商店页面、定价、地区、退款、跨平台发布、开源发布。把 9F 这条"构建 → 发布 → 运营 → 分发"的链条收口。如果说 09F-1 解决"怎么可靠地构建",本篇解决"怎么在发售之后持续运营",那么 09F-3 解决"怎么把游戏送到玩家手里并维持一个健康的商店存在"。三篇合起来,就是你作为"能独立交付一款游戏的开源工程师"的发布工程全景。
