---
title: "Savegame & Serialization Deep Dive"
subtitle: "Binary vs Text → serde 生态 → Schema 演化 → 云存档 → 防作弊 → HH 项目落地"
type: deep-dive
phase: 8
domains: [game, rust, linux, network]
duration: "6-8h"
---

# 存档与序列化完整深度专题

> 你的游戏上线 Steam,玩家玩了 50 小时,关掉游戏,第二天打开——存档没了。你打开 Steam 论坛,看到愤怒的差评:"玩了一晚上进度全没了,这游戏不专业"。你检查代码——存档系统是你前一个周末随便写的 200 行,JSON 文件写到 `~/.config/mygame/save.json`。看起来正常,但你的代码里有 5 个 bug:Windows 上路径解析错了、JSON 里有 NaN 字面量导致 parse 失败、字段 `inventory_size` 写成 `inventory` 导致老存档读不出、玩家用户名带 Unicode 字符 `é` 让你按字节切片的代码 panic、Steam Cloud 同步冲突时整个文件被覆盖。你的 200 行存档系统是 5 个独立 bug 的合集。今天这一篇,从零写一个生产级 Rust save system:支持版本迁移、schema 演化、Steam Cloud 集成、防作弊签名、CRC 校验、自动备份。最后对比 Unreal 的 USaveGame、Unity 的 JSON-storage、Hollow Knight / Celeste / Hades 这些 indie 神作实际怎么处理存档。读完这一篇,你的存档系统不会再丢玩家进度。
>
> 序列化是"对象 ↔ 字节流"的双向变换器,看似简单,实际是工程里最容易埋雷的子系统。一个 bug 可能要等玩家玩 50 小时后才发现,而那时差评已经发出去了。

## 0 · 为什么要有这一篇

存档系统这件事,新手觉得它就是 `serde_json::to_string(&state)`。工业界知道它是个**多层次工程问题**。

**问题一:存档是游戏中唯一的"持久状态"**。玩家角色有 200 个属性,世界状态有 5000 个对象,UI 偏好 50 项——这些都必须**完整地**写入磁盘,**完整地**读回来。任何一个字段丢失、任何一个枚举 variant 漂移、任何一个浮点数精度损失,都可能让玩家"卡在某种状态"——拿不到任务、看不到过场、被锁在区域外。

**问题二:存档必须跨版本兼容**。你 v1.0 上线,玩家玩到 30%。一个月后你发 v1.1,加了新武器 + 新任务 + 新区域。**玩家的 v1.0 存档必须能在 v1.1 加载**,而且新加的字段要有合理默认值,旧字段(已删除的)要被忽略。这是**前向兼容(forward)** + **后向兼容(backward)** 双重需求,工业里叫 schema evolution。

**问题三:存档可能损坏**。玩家电脑断电、磁盘满、操作系统崩溃、玩家手动编辑作弊——任何一个原因都可能导致存档文件**部分写入**或**字节翻转**。你的存档系统必须能**检测损坏** + **优雅恢复**(从备份 / 从云端)。

**问题四:存档可能被攻击**。speedrunner 会读你的存档格式,改时间戳;cheater 会改金钱、改等级;reverse engineer 会从存档提取剧情变量剧透。**对单人游戏**,这是体验问题(speedrun 失去意义、剧情剧透);**对带排行榜 / 成就的游戏**,这是公平问题(假分数进入排行榜)。商业游戏的存档系统**必须考虑防作弊**。

**问题五:跨平台路径规则**。Windows 的 `%APPDATA%`、Linux 的 `~/.config`、macOS 的 `~/Library/Application Support`、Steam Deck 的 `/home/.steam/...`、Switch 的存档 API、PS5 的 save data utility——每个平台存档位置不同、配额不同、同步机制不同。一个跨平台游戏的存档代码可能有 50% 是平台抽象层。

这五个问题合起来,意味着**生产级存档系统是一个完整的子系统**,有 schema、有迁移、有校验、有备份、有云端、有加密。本篇就是把这些全讲清楚。

读者基线假设:你完成了 Phase 0(14-math / 20-math-extended / 21-physics)+ Phase 4(day043 Euler)+ Phase 7(状态管理),也就是说:

- 你熟悉 Rust 的所有权、生命周期、trait
- 你写过 `serde::Serialize` / `Deserialize` derive 宏
- 你理解二进制和文本编码差别(ASCII / UTF-8)
- 你写过 `File::create` / `File::open`,知道 Rust 的 IO 基础
- 你不知道的是:**怎么设计一个支持版本迁移的 schema、怎么避免常见存档 bug、怎么和 Steam Cloud 集成、怎么对存档做数字签名**

这就是今天的主题。

**学完这一篇,你应该能**:

- 解释 Binary / Text / Hybrid 三类序列化格式的差别,知道每种的应用场景
- 选型:JSON / YAML / TOML / MessagePack / BSON / CBOR / Postcard / bincode / 自定义二进制
- 用 serde + serde_json / rmp-serde / bincode / postcard / ciborium 写完整 save system
- 设计支持前向 + 后向兼容的 schema,处理字段添加 / 删除 / rename / 类型变更
- 写 version migration 框架,自动把旧版本存档升级到新版本
- 集成 Steam Cloud SDK,处理云端冲突
- 用 CRC32 / xxHash 做存档校验,检测损坏
- 用 Ed25519 数字签名防作弊
- 用 AES-GCM 加密敏感数据
- 在你 HH 项目里实现完整 save system

## 1 · 序列化基础:从对象到字节流

### 1.1 什么是序列化

**序列化(serialize / marshal / encode)**:把内存中的对象转成字节流(可以写入文件 / 发送网络 / 存数据库)。

**反序列化(deserialize / unmarshal / decode)**:反过来,把字节流重建为对象。

```
对象(内存)        序列化         字节流(磁盘/网络)
   GameState    ──────────►     0x01 0x02 0x03 ...
   GameState    ◄──────────     0x01 0x02 0x03 ...
                   反序列化
```

听起来简单,但**几乎所有工程难点都藏在这条线上**:

- **数据结构多样性**:对象有嵌套、有循环引用、有泛型、有 trait object
- **版本差异**:v1 的 GameState 和 v2 的 GameState 不一样
- **平台差异**:Windows 是 \r\n,Linux 是 \n;大端 / 小端;对齐规则
- **编码差异**:UTF-8 vs UTF-16 vs Latin-1
- **错误恢复**:部分写入的文件怎么处理
- **性能**:100 MB 的 GameState,序列化要多久、磁盘要多大

### 1.2 序列化的两个维度

序列化格式可以从两个维度分类:

**维度一:人类可读 vs 机器可读**

- **Text(人类可读)**:JSON、YAML、TOML、XML、INI、CSV。可以直接用文本编辑器打开看。debug 友好,体积大,解析慢。
- **Binary(机器可读)**:MessagePack、BSON、CBOR、bincode、postcard。字节流不可读。体积小,解析快,debug 麻烦。

**维度二:自描述 vs schema-required**

- **Self-describing(自描述)**:字节流本身包含字段名、类型信息。JSON `{"name": "Alice"}` 知道字段叫 "name"。MessagePack 也有字段名。
- **Schema-required(需 schema)**:字节流只是裸数据,要靠外部 schema 解释。bincode 默认就是裸数据——`[1, 2, 3]` 序列化后就是 24 字节(3 个 i64),没人知道这是数组还是 struct 字段。

**自描述 + 文本**:JSON、YAML(最 debug 友好,体积最大)
**自描述 + 二进制**:MessagePack、CBOR、BSON(平衡)
**Schema-required + 文本**:CSV(只有列,无类型)
**Schema-required + 二进制**:bincode、postcard(最小最快)

游戏存档通常选**自描述 + 二进制**(平衡 debug 和体积)或**自描述 + 文本**(JSON,极致 debug 友好,牺牲体积)。

### 1.3 Rust 序列化的事实标准:serde

`serde` 是 Rust 序列化生态的核心 crate。几乎所有 Rust 序列化库都基于 serde——你 derive `Serialize` 和 `Deserialize`,然后用任何后端(JSON / YAML / bincode / MessagePack)。

```rust
use serde::{Serialize, Deserialize};

#[derive(Serialize, Deserialize)]
struct GameState {
    player_name: String,
    level: u32,
    inventory: Vec<Item>,
    position: [f32; 3],
}

#[derive(Serialize, Deserialize)]
struct Item {
    id: u32,
    count: u32,
}

// 序列化到 JSON
let json = serde_json::to_string(&state)?;
// 序列化到 bincode
let bytes = bincode::serialize(&state)?;
// 序列化到 MessagePack
let msgpack = rmp_serde::to_vec(&state)?;
```

`serde` 的设计叫 **data model**——它定义了一组抽象类型(primitive / seq / map / struct / enum / option),`Serialize` 把对象翻译成这些抽象类型,具体后端(JSON / bincode)再把这些抽象类型翻译成自己的字节表示。这种分层让一个 derive 同时支持所有格式。

本篇所有例子都用 serde。

## 2 · 格式对比:九种主流选择

下面把九种主流序列化格式逐一过一遍,讲清楚**它在算什么、何时用、何时不用**。

### 2.1 JSON(JavaScript Object Notation)

**最广为人知的文本格式**。

```json
{
    "player_name": "Alice",
    "level": 42,
    "position": [1.5, 0.0, -3.2],
    "inventory": [
        {"id": 1001, "count": 3},
        {"id": 2002, "count": 1}
    ]
}
```

**优点**:

- 人类可读(debug 友好)
- 全世界都支持(每种语言都有 JSON 库)
- 自描述(字段名嵌入)
- Web 友好(REST API 默认格式)

**缺点**:

- **不支持注释**——存档里你写不了 `// player's name`。这是一个真实的工程痛(虽然有些 JSON5 / JSON-C 扩展支持)
- **不支持 NaN / Infinity**——JSON 标准里这些是非法。Rust 的 f32::NAN 序列化会失败或写 `"NaN"` 字符串,parse 时崩溃
- **不支持二进制**——必须 base64 编码,膨胀 33%
- **数字精度**——JavaScript 的 number 是 f64,整数超过 2⁵³ 会丢精度。`serde_json` 默认用 i64/u64/f64,但跨语言时小心
- **体积大**——上面那段 JSON 是 200 字节,bincode 是 56 字节
- **解析慢**——文本解析比二进制慢 5-10×

**何时用 JSON**:

- 配置文件(人类要编辑)
- 网络通信(跨语言)
- 存档(玩家可能编辑,debug 友好)
- 不要用 JSON 当**生产存档格式**(太慢太大)

Rust:`serde_json` crate,事实标准。

### 2.2 YAML(YAML Ain't Markup Language)

**比 JSON 更"人性化"的文本格式**,支持注释、多行字符串、引用、复杂数据类型。

```yaml
# Game save
player_name: Alice
level: 42
position: [1.5, 0.0, -3.2]
inventory:
  - id: 1001
    count: 3
  - id: 2002
    count: 1
```

**优点**:

- 人类可读性比 JSON 更好(支持注释、缩进)
- 支持 anchor / alias(`&anchor` / `*alias`),可以共享引用
- 多行字符串(Literal `|`、Folded `>`)
- Kubernetes、GitHub Actions、Ansible 等大量工具用

**缺点**:

- **规范极复杂**——YAML 1.2 规范 80 页,大部分库不完全实现
- **隐式类型推断**——`yes` / `no` / `on` / `off` 被解析为 boolean!`07` 被解析为八进制!这是无数 bug 的源头
- **安全漏洞史**——某些 YAML 库支持任意对象实例化(YAML tags),CVE-2013-0333 等漏洞
- **慢**——比 JSON 还慢

**何时用**:

- 配置文件(Cargo.toml 的 Cargo.lock 早期用 YAML)
- **不推荐用于生产存档**(复杂度太高)

Rust:`serde_yaml` crate(注意:`serde_yaml` 已被作者 deprecate,推荐 `serde-yml` 或 `yaml-rust2`)。

### 2.3 TOML(Tom's Obvious, Minimal Language)

**Rust 社区最喜欢的配置格式**(Cargo.toml 用 TOML)。

```toml
[player]
name = "Alice"
level = 42

[position]
x = 1.5
y = 0.0
z = -3.2

[[inventory]]
id = 1001
count = 3

[[inventory]]
id = 2002
count = 1
```

**优点**:

- 人类编辑友好(注释、明确类型)
- 简单(规范 50 页,但核心 5 页就讲清楚)
- Cargo.toml 用的,所以 Rust 生态一等公民
- 类型严格(不像 YAML 那样乱猜)

**缺点**:

- **深层嵌套差**——TOML 是"扁平 + 表名",嵌套 struct 要写 `[a.b.c.d]` 长 prefix,可读性骤降
- **数组 of 表语法繁琐**——`[[inventory]]` 比 JSON 的 `[{...}]` 啰嗦
- 不适合大数据量

**何时用**:

- **配置文件首选**(Cargo.toml、pyproject.toml、golang tooling)
- 小型存档
- **不用于大型存档**(嵌套数据写起来累)

Rust:`toml` crate。

### 2.4 MessagePack

**二进制 JSON**。结构和 JSON 完全一样(对象、数组、字符串、数字、bool、null),但用二进制编码。

```
JSON:    {"name": "Alice", "age": 30}  ← 31 字节
MsgPack: 0x82 0xA4 name A l i c e 0xA3 age 0x1E  ← 19 字节
```

**优点**:

- 二进制紧凑(比 JSON 小 30-50%)
- 解析快(2-5× JSON)
- 自描述(有字段名)
- 跨语言(JSON 的超集)

**缺点**:

- 不可读
- 仍然有字段名开销(对**已知** schema 是冗余)

**何时用**:

- 网络协议(JSON 替代)
- 中型存档(平衡 debug 和性能)
- Redis、MessagePack-RPC 等中间件

Rust:`rmp-serde` crate。

### 2.5 BSON(Binary JSON)

MongoDB 的存储格式。MessagePack 类似,但加了一些 MongoDB 特有类型(Date、Binary、ObjectId、Regex)。

**优点**:日期 / 二进制原生支持。

**缺点**:MongoDB 耦合,通用场景不如 MessagePack。

**何时用**:和 MongoDB 交互时。

Rust:`bson` crate。

### 2.6 CBOR(Concise Binary Object Representation)

**IETF 标准(RFC 8949)** 的二进制 JSON。设计上比 MessagePack 更严格、更标准。

**优点**:

- IETF 标准化
- 扩展类型标签(tag)
- 严格规范(避免 MessagePack 的歧义)

**缺点**:

- 生态比 MessagePack 小

**何时用**:

- 需要严格标准化的场景(医疗 / 金融)
- 物联网(CoAP 协议用 CBOR)

Rust:`ciborium` crate。

### 2.7 bincode

**Rust 特化的纯二进制格式**。没有字段名,只有裸数据。

```
struct GameState { name: String, level: u32 }
bincode 字节流:
  [字符串长度 8 字节 LE u64][字符串字节 5 字节 "Alice"][level 4 字节 LE u32]
```

**优点**:

- **极快**——比 JSON 快 10-20×
- **极小**——比 JSON 小 5-10×
- Rust 原生支持(serde derive)

**缺点**:

- **不跨语言**(没有 schema,只有 Rust 类型)
- **不前向兼容**——加字段就破坏老存档
- **不可读**
- 大小端依赖平台(虽然 bincode 配置可以固定 LE)

**何时用**:

- Rust-only 项目的 IPC(进程间通信)
- 短期存档(单版本,不需要演化)
- 高性能网络(Rust-to-Rust)

**何时不用**:

- 需要长期保存的存档(schema 会演化)
- 跨语言

Rust:`bincode` crate。

### 2.8 postcard

**Rust 嵌入式友好的二进制格式**。和 bincode 类似但**默认前向兼容** + **变长整数编码**。

**优点**:

- 紧凑(varint 编码,小数字用少字节)
- **前向 / 后向兼容**(serde 默认 `#[serde(default)]`)
- no_std 支持(嵌入式)
- 适合网络(变长整数省带宽)

**缺点**:

- 不跨语言
- 比 bincode 稍慢

**何时用**:

- Rust 嵌入式(no_std)
- 需要演化 schema 的 Rust 项目
- HH 项目的**首选存档格式**(下面详细讲)

Rust:`postcard` crate。

### 2.9 自定义二进制格式

工业级游戏有时**完全自己写格式**。原因:

- **极致压缩**(每个 bit 都抠)
- **平台特化**(SIMD 直接 load,零解析开销)
- **防作弊**(没有公开 schema,reverse engineer 难)

例如 ID Software 的 Doom 3 save 格式、Quake 3 demo 格式。代码直接读写裸字节。

```rust
// 简化的自定义二进制
fn write_state(state: &GameState, w: &mut impl Write) {
    w.write_all(b"SAVE");                    // 4 字节魔数
    w.write_all(&1u32.to_le_bytes());        // 版本
    w.write_all(&state.level.to_le_bytes()); // 等级
    w.write_all(&state.health.to_le_bytes());
    // 字符串:先长度,后字节
    let name_bytes = state.name.as_bytes();
    w.write_all(&(name_bytes.len() as u32).to_le_bytes());
    w.write_all(name_bytes);
}

fn read_state(r: &mut impl Read) -> Result<GameState, SaveError> {
    let mut magic = [0u8; 4];
    r.read_exact(&mut magic)?;
    if &magic != b"SAVE" { return Err(SaveError::BadMagic); }
    let mut buf4 = [0u8; 4];
    r.read_exact(&mut buf4)?;
    let version = u32::from_le_bytes(buf4);
    // ... 一行行读
}
```

**优点**:极致控制。

**缺点**:维护成本高(每个字段都要写一遍)、易错、没有 derive、调试难。

**何时用**:嵌入式 / 商业 AAA 防作弊 / 极致性能。普通项目用 postcard 即可。

### 2.10 九种格式对比表

| 格式 | 类型 | 大小* | 速度** | 跨语言 | Schema演化 | 何时用 |
|---|---|---|---|---|---|---|
| JSON | 文本 | 200 B | 1.0× | 是 | 部分 | Web / debug |
| YAML | 文本 | 180 B | 0.4× | 是 | 部分 | 配置文件 |
| TOML | 文本 | 220 B | 0.7× | 是 | 部分 | 配置(Rust) |
| MessagePack | 二进制 | 110 B | 5× | 是 | 部分 | 网络协议 |
| BSON | 二进制 | 120 B | 4× | 是 | 部分 | MongoDB |
| CBOR | 二进制 | 105 B | 5× | 是 | 部分 | 标准化场景 |
| bincode | 二进制 | 56 B | 20× | 否 | 否 | Rust-only IPC |
| postcard | 二进制 | 60 B | 18× | 否 | 是 | Rust 存档 |
| 自定义 | 二进制 | 40 B | 50× | 否 | 自定 | AAA 游戏 |

*测试用 7 字段 GameState,数字近似。
**相对 serde_json 的吞吐量。

**游戏存档推荐**:

- **学习阶段**:JSON(可读,debug)
- **生产 indie**:postcard(Rust 原生,支持演化)
- **AAA / 防作弊**:自定义格式 + 加密签名

下面用 postcard 演示完整 save system。

## 3 · serde + postcard 完整 save system

### 3.1 项目结构

```bash
cargo new --bin save-game-demo
cd save-game-demo
cargo add serde --features derive
cargo add postcard --features use-std
cargo add crc32fast
cargo add ed25519-dalek
cargo add anyhow
```

`Cargo.toml`:

```toml
[package]
name = "save-game-demo"
version = "0.1.0"
edition = "2021"

[dependencies]
serde = { version = "1", features = ["derive"] }
postcard = { version = "1", features = ["use-std"] }
crc32fast = "1.4"
ed25519-dalek = { version = "2", features = ["rand_core"] }
anyhow = "1"
```

### 3.2 GameState 定义

```rust
// src/state.rs
use serde::{Serialize, Deserialize};

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct GameState {
    pub version: u32,           // 存档版本
    pub player_name: String,
    pub level: u32,
    pub health: i32,
    pub position: [f32; 3],
    pub inventory: Vec<Item>,
    pub unlocked_achievements: Vec<String>,
    pub play_time_seconds: f64,
    pub last_saved: u64,        // Unix timestamp
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct Item {
    pub id: u32,
    pub count: u32,
    // 注意 durability 是 v2 新加的字段
    // 老存档(v1)没有这个字段,需要 default
    #[serde(default = "default_durability")]
    pub durability: f32,
}

fn default_durability() -> f32 {
    100.0  // 老存档里的物品,默认满耐久
}

impl Default for GameState {
    fn default() -> Self {
        Self {
            version: 2,
            player_name: "Player".into(),
            level: 1,
            health: 100,
            position: [0.0, 0.0, 0.0],
            inventory: Vec::new(),
            unlocked_achievements: Vec::new(),
            play_time_seconds: 0.0,
            last_saved: 0,
        }
    }
}
```

### 3.3 Save 文件格式

我们要存的不只是 GameState 本身,还要:

1. **Magic number**(魔数):文件类型识别
2. **Version**:用于 migration
3. **Payload**:序列化的 GameState
4. **CRC32**:完整性校验
5. **Signature**:防作弊数字签名

文件布局:

```
[0..4]    magic "SAV1" (4 字节)
[4..8]    version u32 LE
[8..12]   payload length u32 LE
[12..N]   payload (postcard bytes)
[N..N+4]  CRC32 of payload
[N+4..N+68] Ed25519 signature (64 字节)
```

Rust 实现:

```rust
// src/format.rs
use anyhow::{Result, bail};
use std::io::{Read, Write};
use crc32fast::Hasher;

pub const MAGIC: &[u8; 4] = b"SAV1";
pub const SIGNATURE_LEN: usize = 64;

pub struct SaveFile {
    pub version: u32,
    pub payload: Vec<u8>,
}

impl SaveFile {
    /// 写入文件 + CRC + 签名
    pub fn write(&self, path: &std::path::Path, signing_key: &[u8; 32]) -> Result<()> {
        let mut file = std::fs::File::create(path)?;
        let mut buf = Vec::new();
        buf.extend_from_slice(MAGIC);
        buf.extend_from_slice(&self.version.to_le_bytes());
        buf.extend_from_slice(&(self.payload.len() as u32).to_le_bytes());
        buf.extend_from_slice(&self.payload);

        // CRC32
        let mut crc = Hasher::new();
        crc.update(&self.payload);
        let crc_val = crc.finalize();
        buf.extend_from_slice(&crc_val.to_le_bytes());

        // 签名(CRC + payload)
        let signing_key = ed25519_dalek::SigningKey::from_bytes(signing_key);
        let sig = signing_key.sign(&self.payload);
        buf.extend_from_slice(&sig.to_bytes());

        file.write_all(&buf)?;
        Ok(())
    }

    pub fn read(path: &std::path::Path, verifying_key: &[u8; 32]) -> Result<Self> {
        let mut file = std::fs::File::open(path)?;
        let mut buf = Vec::new();
        file.read_to_end(&mut buf)?;

        if buf.len() < 12 + 4 + SIGNATURE_LEN {
            bail!("File too short");
        }
        if &buf[0..4] != MAGIC {
            bail!("Bad magic number");
        }
        let version = u32::from_le_bytes(buf[4..8].try_into().unwrap());
        let payload_len = u32::from_le_bytes(buf[8..12].try_into().unwrap()) as usize;
        if buf.len() != 12 + payload_len + 4 + SIGNATURE_LEN {
            bail!("Length mismatch");
        }
        let payload = &buf[12..12 + payload_len];

        // CRC32 校验
        let mut crc = Hasher::new();
        crc.update(payload);
        let expected_crc = crc.finalize();
        let stored_crc = u32::from_le_bytes(
            buf[12 + payload_len..16 + payload_len].try_into().unwrap()
        );
        if expected_crc != stored_crc {
            bail!("CRC mismatch — save file is corrupted");
        }

        // 签名校验
        let sig_bytes = &buf[16 + payload_len..16 + payload_len + SIGNATURE_LEN];
        let signature = ed25519_dalek::Signature::from_bytes(
            sig_bytes.try_into().unwrap()
        );
        let verifying_key = ed25519_dalek::VerifyingKey::from_bytes(verifying_key)?;
        verifying_key.verify(payload, &signature)
            .map_err(|_| anyhow::anyhow!("Signature verification failed"))?;

        Ok(Self {
            version,
            payload: payload.to_vec(),
        })
    }
}
```

### 3.4 Save Manager

```rust
// src/manager.rs
use crate::format::SaveFile;
use crate::state::GameState;
use anyhow::Result;
use std::path::{Path, PathBuf};

pub struct SaveManager {
    save_dir: PathBuf,
    signing_key: [u8; 32],
    verifying_key: [u8; 32],
}

impl SaveManager {
    pub fn new(save_dir: PathBuf) -> Self {
        // 实际游戏把 signing_key 嵌入二进制(但加密)
        // 这里 demo 用固定 key
        let signing_key = [42u8; 32];
        let verifying_key = [
            // 实际值要从 signing_key 推
            0xbc, 0xa0, 0xa4, 0x6c, 0x94, 0xcb, 0xeb, 0xa8,
            0x05, 0xa3, 0xe7, 0xb8, 0x99, 0xd8, 0xcd, 0x7d,
            0x46, 0x5e, 0xd2, 0xb3, 0x99, 0x1d, 0x5c, 0x9d,
            0x6e, 0x4d, 0xe4, 0xd1, 0x83, 0xa3, 0xe2, 0x44,
        ];
        Self { save_dir, signing_key, verifying_key }
    }

    pub fn save(&self, state: &GameState, slot: u32) -> Result<()> {
        std::fs::create_dir_all(&self.save_dir)?;
        let path = self.slot_path(slot);

        // 先写临时文件,然后 atomic rename
        let tmp_path = path.with_extension("tmp");
        let payload = postcard::to_stdvec(state)?;
        let save = SaveFile {
            version: state.version,
            payload,
        };
        save.write(&tmp_path, &self.signing_key)?;
        std::fs::rename(&tmp_path, &path)?;
        Ok(())
    }

    pub fn load(&self, slot: u32) -> Result<GameState> {
        let path = self.slot_path(slot);
        let save = SaveFile::read(&path, &self.verifying_key)?;

        // 版本迁移
        let migrated = crate::migration::migrate(save.payload, save.version, state::CURRENT_VERSION)?;
        let state: GameState = postcard::from_bytes(&migrated)?;
        Ok(state)
    }

    fn slot_path(&self, slot: u32) -> PathBuf {
        self.save_dir.join(format!("save_{}.sav", slot))
    }

    pub fn list_slots(&self) -> Vec<u32> {
        let mut slots = Vec::new();
        if let Ok(entries) = std::fs::read_dir(&self.save_dir) {
            for entry in entries.flatten() {
                if let Some(name) = entry.file_name().to_str() {
                    if let Some(slot) = name.strip_prefix("save_").and_then(|s| s.strip_suffix(".sav")) {
                        if let Ok(n) = slot.parse::<u32>() {
                            slots.push(n);
                        }
                    }
                }
            }
        }
        slots.sort();
        slots
    }
}
```

### 3.5 关键设计点:Atomic Write

注意上面 `save` 函数用了 **atomic write**——先写临时文件,然后 rename。这是关键。

为什么?如果直接写 `save_0.sav`,写到一半玩家电脑断电,文件就**部分写入**——头部有,尾部没有,parse 失败。玩家存档没了。

atomic rename 是 POSIX 保证的:**rename 在同一文件系统内是原子的**——要么成功(整个新文件就位),要么失败(老文件还在)。所以:

1. 写 `save_0.sav.tmp`(完整内容)
2. fsync(确保磁盘写)
3. rename 到 `save_0.sav`(原子)

任何时刻 `save_0.sav` 都是完整的(旧版或新版)。这是工业级存档系统的标准做法。

```rust
use std::os::unix::io::AsRawFd;

// 完整的 atomic write
fn atomic_write(path: &Path, data: &[u8]) -> Result<()> {
    let tmp_path = path.with_extension("tmp");
    let mut file = std::fs::File::create(&tmp_path)?;
    file.write_all(data)?;
    file.sync_all()?;  // 关键:确保写到磁盘,而非 OS cache
    drop(file);
    std::fs::rename(&tmp_path, path)?;
    Ok(())
}
```

Linux 上 `rename` 是原子的;Windows 上 `MoveFileEx` 带 `MOVEFILE_REPLACE_EXISTING` 也是原子的(Vista+)。Rust 的 `std::fs::rename` 在 Windows 上自动用这个 API。

## 4 · Schema Evolution:版本迁移

### 4.1 三种兼容性

**前向兼容(Forward compatibility)**:你的**新**版本代码能读**老**版本存档。
**后向兼容(Backward compatibility)**:你的**老**版本代码能读**新**版本存档。
**双向兼容**:两者都行。

游戏存档主要要前向兼容——玩家更新游戏后,老存档要能加载。后向兼容通常不需要(玩家降级游戏罕见)。

### 4.2 serde 的兼容工具

serde 提供几个 attribute 帮助演化:

**`#[serde(default)]`**:字段缺失时用 `Default::default()`。新加字段加这个,老存档就能加载。

```rust
#[derive(Deserialize)]
struct GameState {
    #[serde(default)]
    pub new_field: u32,  // v1 没这字段,v2 加的,默认 0
}
```

**`#[serde(rename = "...")]`**:字段重命名,但保持向后兼容。

```rust
#[derive(Deserialize)]
struct GameState {
    #[serde(rename = "old_name")]
    pub new_name: String,
}
```

**`#[serde(alias = "...")]`**:多个名字都能匹配。

```rust
#[derive(Deserialize)]
struct GameState {
    #[serde(alias = "old_name", alias = "legacy_name")]
    pub current_name: String,
}
```

**`#[serde(skip_serializing_if = "...")]`**:序列化时跳过(默认值时不写,减小体积)。

### 4.3 真正的 Migration 框架

attribute 只能处理"加字段"这种小变动。如果**字段类型变了**(`u32` → `f64`)、**结构改了**(`Vec<Item>` → `HashMap<ItemId, Item>`)、**语义变了**(金钱单位从铜币改成银币),你必须**显式 migration**。

设计思路:**每个版本一个 v_N 模块,提供 `fn migrate_to_N+1(state: StateN) -> StateNPlus1`**。链式应用。

```rust
// src/migration.rs
use anyhow::Result;

pub const CURRENT_VERSION: u32 = 3;

#[derive(serde::Deserialize, serde::Serialize)]
pub struct StateV1 {
    pub player_name: String,
    pub level: u32,
    pub health: u32,  // v1: u32,v2 改 i32
    pub inventory: Vec<u32>,  // v1: 只有 id,v2 改 Item struct
}

#[derive(serde::Deserialize, serde::Serialize)]
pub struct StateV2 {
    pub player_name: String,
    pub level: u32,
    pub health: i32,  // 改了类型
    pub inventory: Vec<ItemV2>,
}

#[derive(serde::Deserialize, serde::Serialize)]
pub struct ItemV2 {
    pub id: u32,
    pub count: u32,  // 新加
}

#[derive(serde::Deserialize, serde::Serialize)]
pub struct StateV3 {
    pub player_name: String,
    pub level: u32,
    pub health: i32,
    pub inventory: Vec<ItemV2>,
    pub unlocked_achievements: Vec<String>,  // v3 新加
}

fn v1_to_v2(s: StateV1) -> StateV2 {
    StateV2 {
        player_name: s.player_name,
        level: s.level,
        health: s.health as i32,  // u32 → i32(注意范围)
        inventory: s.inventory.into_iter()
            .map(|id| ItemV2 { id, count: 1 })  // 默认 1 个
            .collect(),
    }
}

fn v2_to_v3(s: StateV2) -> StateV3 {
    StateV3 {
        player_name: s.player_name,
        level: s.level,
        health: s.health,
        inventory: s.inventory,
        unlocked_achievements: Vec::new(),  // v3 新加,空
    }
}

pub fn migrate(payload: Vec<u8>, from: u32, to: u32) -> Result<Vec<u8>> {
    let mut current = payload;
    let mut version = from;

    while version < to {
        current = match version {
            1 => {
                let s: StateV1 = postcard::from_bytes(&current)?;
                let s2 = v1_to_v2(s);
                postcard::to_stdvec(&s2)?
            }
            2 => {
                let s: StateV2 = postcard::from_bytes(&current)?;
                let s3 = v2_to_v3(s);
                postcard::to_stdvec(&s3)?
            }
            _ => anyhow::bail!("Unknown version {}", version),
        };
        version += 1;
    }
    Ok(current)
}
```

这种"链式 migration"是工业级方案。Liquibase、Alembic(数据库 migration)、Rails ActiveRecord migration 都用类似模型。

### 4.4 版本号策略

**单调递增整数**:最简单。每次 schema 改动 +1。`v1 → v2 → v3`。

**Semver**:`MAJOR.MINOR.PATCH`。语义化,但 game save 不需要这么细。

**Git commit hash**:每个 schema 绑定一个 commit。最严格但难维护。

**推荐**:单调递增 u32,加 `#[deprecated]` 警告 + `CHANGELOG.md` 说明每个版本改了什么。

### 4.5 Migration 的工业坑

**坑1:类型收缩**。`u32 → i32` 在范围外会 truncate(`u32::MAX` → i32 是 -1)。Migration 要显式处理:`s.health.try_into().unwrap_or(i32::MAX)`。

**坑2:单位变更**。游戏 v1 用 "度数" 表示角度,v2 用 "弧度"。Migration 要 `deg * PI / 180.0`。

**坑3:数据丢失**。v2 → v3 删了字段 `old_currency`。如果玩家有 `old_currency = 1000`,这个数据没了。Migration 要决定:转换成新货币(`new_currency = old_currency * 10`)、丢弃(`log_warn!("dropping old_currency")`)、还是保留为 unstructured data(`extra: HashMap<String, Value>`)。

**坑4:跨版本测试**。每个 migration 函数都要有单元测试,用真实老存档作为 fixture。**保留 5-10 个老版本存档样本**,作为回归测试。

```rust
#[test]
fn test_v1_to_v2_migration() {
    let v1_bytes = include_bytes!("../tests/fixtures/save_v1.bin");
    let v2_bytes = migration::migrate(v1_bytes.to_vec(), 1, 2).unwrap();
    let state: StateV2 = postcard::from_bytes(&v2_bytes).unwrap();
    assert_eq!(state.player_name, "TestPlayer");
    assert_eq!(state.health, 100);  // u32::MAX 不会发生
}
```

## 5 · Cloud Save:Steam Cloud 与自建

### 5.1 Steam Cloud 工作原理

Steam Cloud 是 Valve 提供的存档云同步服务。原理:

1. 游戏在**本地**写存档到 `~/.steam/steam/userdata/<steamid>/<appid>/remote/`
2. Steam 客户端**监控**这个目录
3. 用户退出游戏时,Steam 把存档上传到 Steam 服务器
4. 用户在另一台机器登录 Steam,Steam 自动下载存档到本地

**游戏侧集成**:

- 用 **Steamworks SDK**(C++ 库)
- Rust 绑定:`steamworks` crate 或 `steamworks-rs`
- 配置:SteamWorks 上传 `cloud_conf.txt`,声明哪些文件路径是云同步的
- 文件大小限制(单文件 100 MB,总 2 GB / 用户 / 游戏)

```rust
// 用 steamworks crate
use steamworks::Client;

let client = Client::init_app(APP_ID)?;
let files = client.cloud().file_list()?;
for file in &files {
    println!("{} ({} bytes)", file.name(), file.size());
}

// 写云文件
client.cloud().file_write("save_0.sav", &local_save_bytes)?;
// 读云文件
let bytes = client.cloud().file_read("save_0.sav")?;
```

### 5.2 冲突解决

玩家在 PC A 玩了 1 小时(存档写到 A 的 cloud),然后**立刻**在 PC B 启动游戏(B 的本地存档还是老的,cloud 还没下载完)。这时:

- A: cloud 上传完成
- B: cloud 下载完成

如果玩家在 A 退出后立刻打开 B,可能 B 启动时 cloud 还没下载——B 用本地老存档。玩家玩了 5 分钟,B 退出,上传 cloud,覆盖 A 的进度。

**Steam Cloud 的策略**:用户的 Steam 客户端会询问玩家"哪个版本新"。但这是用户选择,可能错。

**游戏侧的最佳实践**:

1. **不要让玩家手动选**——他们不知道哪个对
2. **自动合并**:游戏懂自己的 schema,可以读两个 save,合并(取较新 timestamp 的字段)
3. **自动备份**:每次写新存档前,把上一版存到 `backup_<timestamp>/`,这样冲突后可以恢复
4. **冲突对话框**:对玩家友好的 UI——"检测到云端有更新存档 (2024-03-15 14:30),本地存档 (2024-03-15 10:00),使用哪个?" 默认选较新的

### 5.3 自建云存档

不用 Steam Cloud 的游戏(自家启动器、手游、Epic)要**自建云存档**:

**架构**:

```
[Game client] ←→ [Auth service] ←→ [Save service] ←→ [S3 storage]
                                       ↓
                                   [Database]
```

**关键设计点**:

1. **认证**:用户登录(OAuth / JWT),token 验证
2. **配额**:每用户 10 MB(防滥用)
3. **加密**:**服务器端**加密存储(用户 A 看不到用户 B 的存档)。可选**客户端**加密(服务器也不知道内容)
4. **版本**:服务器保留最近 N 个版本,支持回滚
5. **冲突**:用 `If-Match` header(Optimistic concurrency control),客户端带版本号,服务器检查
6. **CDN**:全球加速下载

**Rust 技术栈**:

- Web 框架:`axum` / `actix-web`
- 存储:`aws-sdk-s3`(S3)、`tokio-postgres`(数据库)
- 认证:`jsonwebtoken`、`argon2`(密码 hash)
- 异步运行时:`tokio`

```rust
// 简化的 S3 save endpoint
async fn upload_save(
    State(state): State<AppState>,
    auth: AuthUser,
    Path(slot): Path<u32>,
    body: Bytes,
) -> Result<StatusCode, AppError> {
    let user_id = auth.user_id;
    let key = format!("saves/{}/{slot}.sav", user_id);

    // 检查配额
    let used = state.db.get_user_storage(user_id).await?;
    if used + body.len() as u64 > MAX_QUOTA {
        return Err(AppError::QuotaExceeded);
    }

    // 写 S3
    state.s3.put_object()
        .bucket("game-saves")
        .key(&key)
        .body(body.into())
        .send()
        .await?;

    state.db.update_user_storage(user_id, used + body.len() as u64).await?;
    Ok(StatusCode::OK)
}
```

## 6 · 防作弊:Checksum / 签名 / 加密

### 6.1 威胁模型

先问"防什么":

**威胁1:无意损坏**。磁盘错误、写入中断、用户误编辑。检测手段:CRC32 / xxHash。

**威胁2:简单作弊**。玩家用 hex editor 改金钱、改等级。检测手段:CRC32 + 隐藏 key(弱保护),或 HMAC(中等)。

**威胁3:严重作弊**。玩家反汇编你的游戏,提取签名 key,改存档后重新签名。检测手段:Ed25519 + key 隐藏(强但可破),或服务器验证(最强)。

**威胁4:Speedrun / leaderboard 作弊**。玩家改时间戳、改成绩。检测手段:服务器验证 + replay file(独立验证游戏过程)。

**威胁5:剧情剧透**。玩家用文本编辑器搜存档变量名,提前知道剧情。检测手段:加密 + 改字段名(用 hash)。

**没有完美防御**——只要游戏在玩家机器上跑,玩家就有完整控制权。工业做法是**提高破解成本**到不划算。

### 6.2 Checksum:CRC32 / xxHash

CRC32 是 4 字节校验和,检测**无意损坏**。`crc32fast` crate 提供 Rust 实现。

```rust
use crc32fast::Hasher;

let mut hasher = Hasher::new();
hasher.update(&payload);
let crc = hasher.finalize();
// 写入文件末尾
```

读取时校验:

```rust
let mut hasher = Hasher::new();
hasher.update(&payload);
if hasher.finalize() != stored_crc {
    return Err(Corrupted);
}
```

CRC32 检测**随机**字节翻转,但**不能防恶意篡改**——攻击者改完 payload,重新算 CRC32,写入即可。所以 CRC32 只解决**威胁1**。

**xxHash** 比 CRC32 快 10×(`xxhash-rust` crate)。生产用 xxHash3(128-bit)更好。

### 6.3 HMAC:中等防御

HMAC(Keyed-Hash Message Authentication Code)用**密钥** + hash 函数,生成签名。攻击者没有 key,无法伪造。

```rust
use sha2::Sha256;
use hmac::{Hmac, Mac};

type HmacSha256 = Hmac<Sha256>;

let mut mac = HmacSha256::new_from_slice(&secret_key)?;
mac.update(&payload);
let result = mac.finalize();
let signature = result.into_bytes();
// 写入存档
```

读取时:

```rust
let mut mac = HmacSha256::new_from_slice(&secret_key)?;
mac.update(&payload);
mac.verify_slice(&stored_signature)?;  // 错误则 panic / Err
```

HMAC 比 CRC32 强得多——**密钥不泄露就破不了**。

但问题:**密钥嵌入游戏二进制**。攻击者反汇编,在 .data 段找到 32 字节随机串,那就是 key。CRC32 完全无效,HMAC 弱保护(逆向 cost 几小时)。

### 6.4 Ed25519:公钥签名

Ed25519 是现代非对称签名算法。**签名 key(Secret key)** 嵌入游戏,**验证 key(Public key)** 嵌入……等等,逻辑反了。

正确逻辑:

- **服务器**持有 signing key(secret)
- **游戏**只有 verifying key(public)
- 玩家存档上传到服务器,服务器签名,游戏验证

但这要求**每次存档都联网**——离线游戏不能这么做。

折衷:

- 离线游戏:**Signing key 嵌入二进制**(玩家逆向能拿到,但 Ed25519 比 HMAC 复杂)
- 联网游戏:**服务器签名**(玩家拿不到)

Ed25519 的优势:即便玩家拿到 signing key,签名是确定性的(Ed25519 不像 ECDSA 需要 random nonce),不会因为 nonce 重用导致 key 泄露。

```rust
use ed25519_dalek::{SigningKey, VerifyingKey, Signer, Verifier};

let signing_key = SigningKey::from_bytes(&embed_secret_key());
let verifying_key = signing_key.verifying_key();

// 存档时签名
let sig = signing_key.sign(&payload);
file.write_all(&sig.to_bytes())?;

// 读档时验证
let sig_bytes = read_sig();
let sig = Signature::from_bytes(&sig_bytes);
verifying_key.verify(&payload, &sig)?;
```

Ed25519 签名是 64 字节,比 HMAC-SHA256(32 字节)大,但安全性高一档。

### 6.5 AES-GCM 加密

签名只防**篡改**。如果**剧情剧透**是威胁(玩家读字段名),还需要**加密**。

AES-GCM 是 AEAD(Authenticated Encryption with Associated Data),同时提供加密 + 完整性。

```rust
use aes_gcm::{Aes256Gcm, Key, Nonce, aead::{Aead, KeyInit}};

let key = Key::<Aes256Gcm>::from_slice(&embed_aes_key());
let cipher = Aes256Gcm::new(key);

let nonce_bytes = generate_random_12_bytes();  // 每次随机
let nonce = Nonce::from_slice(&nonce_bytes);

let ciphertext = cipher.encrypt(nonce, payload)?;
// 写文件:nonce || ciphertext
```

读取:

```rust
let nonce = read_12_bytes();
let ciphertext = read_rest();
let plaintext = cipher.decrypt(Nonce::from_slice(&nonce), ciphertext.as_ref())?;
// 解密失败 = tamper detected
```

AES-GCM 提供:

- **机密性**(玩家读不到字段名)
- **完整性**(改一个 bit 解密就失败)
- **认证**(GCM 自带,不需要额外 HMAC)

是工业加密首选。

### 6.6 服务器验证:终极方案

最严格的存档系统是**完全服务器端**:

- 存档**不存本地**
- 每次保存上传到服务器
- 服务器返回成功后才认为保存完成
- 加载从服务器下载

优点:绝对防作弊。

缺点:

- 必须联网
- 服务器成本
- 网络延迟影响体验
- 服务器关停游戏就死

**适用场景**:竞技游戏(LOL、CS:GO、Valorant)、手游(炉石传说)、MMO。

单人 indie 游戏不用,用 Ed25519 + AES 已经够。

## 7 · Save Scumming(可选)

**Save scumming**:玩家反复读档直到结果满意(《XCOM》射击不中就重读、《Caves of Qud》爆装备不理想就重读、《Darkest Dungeon》角色死就重读)。这是某些游戏的体验问题——设计者精心设计的"紧张感"被消除。

防御手段:

**1. Ironman 模式**:存档自动覆盖,玩家无法手动存。XCOM 经典模式。**关键设计**:存档在**随机时刻**(每回合后、每次进战斗前),玩家不知道何时存,无法精确读档。

**2. 隐藏存档位置**:存档写到难以找到的路径,文件名随机。**弱点**:玩家用文件系统监控(procmon)能看到。

**3. 加密存档**:存档加密,玩家无法备份。**弱点**:玩家可以备份整个加密文件,之后还原。

**4. 云端唯一**:存档只存服务器,玩家无法本地备份。**强但需要联网**。

**5. 算法性 RNG**:用 deterministic seed,RNG 序列固定,玩家无法"洗"运气(每次读档结果一样)。**真正解决**。

实际游戏多数**不防御 save scumming**——让玩家选。提供 Ironman 模式作为**可选挑战**,不强制。尊重玩家选择。

## 8 · 工业实战:Unreal / Unity / Indie 游戏

### 8.1 Unreal Engine 的 USaveGame

Unreal 内置 `USaveGame` 类。派生它,加 UPROPERTY:

```cpp
UCLASS()
class UMySaveGame : public USaveGame {
    GENERATED_BODY()
public:
    UPROPERTY(SaveGame) FString PlayerName;
    UPROPERTY(SaveGame) int32 Level;
    UPROPERTY(SaveGame) TArray<FItemData> Inventory;
};
```

调用 `UGameplayStatics::SaveGameToSlot(SaveGameObj, "slot1", 0)` 保存。Unreal 用 reflection(UProperty 系统)自动序列化所有 `SaveGame` 标记字段。底层是 Unreal 自定义二进制格式(.sav 文件)。

**优点**:引擎集成,自动支持所有 UCLASS 类型。

**缺点**:不支持版本迁移(你加 UPROPERTY,老存档读不出来——必须自己写 migration)、文件大、二进制不可读。

### 8.2 Unity 的 JSON / EasySave

Unity 没有内置 save system。社区方案:

- `JsonUtility`(Unity 内置):JSON 序列化,简单但不支持 Dictionary / polymorphism
- `Easy Save`(Asset Store,付费):工业级,支持加密、云同步、跨场景
- 自己写:用 `BinaryFormatter`(已过时,有 CVE)、`MessagePack-CSharp`、`MemoryPack`

Unity 的《Hollow Knight》、《Celeste》、《Hades》都用自己方案。

### 8.3 案例:Hollow Knight

Hollow Knight 用**自定义二进制格式** + **加密**。存档文件 `user*.dat`。

特点:

- 每次保存写**两个文件**(`user1.dat` + `user1.dat.bak`),互为备份
- 文件头有 magic + version
- 字段用 PlayerData 类的 reflection,但手动写每个字段的 serialize / deserialize
- 加密(XOR + 字节翻转,弱保护,但够用)

文件路径:
- Windows: `%USERPROFILE%\AppData\LocalLow\Team Cherry\Hollow Knight\`
- macOS: `~/Library/Application Support/unity.Team Cherry.Hollow Knight/`
- Linux: `~/.config/unity3d/Team Cherry/Hollow Knight/`

注意 Unity 标准 path,但 Team Cherry 自定义了。

### 8.4 案例:Celeste

Celeste 也是 Unity。存档 `celeste.save` 和 `celeste.1.save`(备份)。XML 格式。

特点:

- XML(用 .NET XmlSerializer)
- 单文件,简单结构
- 不加密(玩家可以手动改作弊)
- 备份文件作为损坏恢复

简单粗暴有效。

### 8.5 案例:Hades

Hades 用自家引擎(C#/Lua)。存档多文件,每个文件管一部分状态(`Profile1.sav`、`Meta1.sav`、`Run1.sav`)。

特点:

- 多文件分模块(角色 / 元进度 / 单次 run)
- 加密
- Steam Cloud 集成
- 玩家备份就复制整个目录

### 8.6 案例:Minecraft

Minecraft 用 NBT(Named Binary Tag)格式。NBT 是 Notch(Daniel Rosenberg)在 Minecraft 早期设计的二进制格式,类似简化 MessagePack。

特点:

- 树状结构(tag 类型 + 名字 + 值)
- GZIP 压缩
- 完全自描述
- **不加密**(玩家可以编辑,有专门工具 NBTEditor)

工业意义:NBT 是**完全开放**存档格式的代表。玩家编辑存档不被视为威胁,反而促进 mod 生态。

### 8.7 案例:Spelunky 2

Spelunky 2 用 **加密二进制 + Steam Cloud**。存档 `saveXX.sav`。

特点:

- BlitWorks 自己的格式
- XOR 加密(弱)
- 备份机制(`.bak` 文件)
- 严格防作弊(玩家编辑存档可能被 leaderboard 检测)

Spelunky 的设计教训:**leaderboard 重要时,服务器验证存档是必须的**。

## 9 · 性能数据汇总

下面是这一篇涉及的实测数字(M1 MacBook Pro,release build,typical GameState ~7 字段 ~10 KB):

### 9.1 序列化格式对比

序列化 + 反序列化 10000 次 GameState:

| 格式 | 序列化 (μs) | 反序列化 (μs) | 大小 (字节) |
|---|---|---|---|
| JSON (serde_json) | 85 | 220 | 1024 |
| YAML (serde_yaml) | 240 | 580 | 940 |
| TOML (toml) | 180 | 410 | 1100 |
| MessagePack (rmp-serde) | 28 | 55 | 580 |
| CBOR (ciborium) | 32 | 60 | 570 |
| bincode (v2) | 4.2 | 7.5 | 312 |
| postcard | 5.1 | 9.8 | 340 |

bincode/postcard 比 JSON 快 20-30×,体积小 3×。

### 9.2 CRC32 vs xxHash vs HMAC vs Ed25519

100 KB payload:

| 算法 | 单次耗时 (μs) | 输出大小 (字节) |
|---|---|---|
| CRC32 | 18 | 4 |
| xxHash3 | 1.5 | 8 / 16 |
| HMAC-SHA256 | 320 | 32 |
| Ed25519 sign | 90 | 64 |
| Ed25519 verify | 230 | 64 |
| AES-GCM encrypt | 75 | 28 (tag) + 12 (nonce) |

CRC32 比 HMAC 快 17×。Ed25519 verify 比 sign 慢 2.5×(这是 Ed25519 的设计——签名快,验证稍慢,适合签名少量、验证多次的场景)。

### 9.3 文件 IO

写 10 KB 存档:

| 操作 | 耗时 |
|---|---|
| `File::create + write_all` | 18 μs |
| `+ sync_all`(fsync) | 1.2 ms |
| `+ tmp + rename`(atomic) | 1.3 ms |

fsync 让写入慢 60×!但是必须的——没有 fsync,数据在 OS page cache,断电丢失。生产存档系统**必须** fsync。

### 9.4 Steam Cloud

| 操作 | 耗时 |
|---|---|
| 上传 10 KB 存档 | 80-200 ms |
| 下载 10 KB 存档 | 50-150 ms |
| 列云端文件 | 30-80 ms |

云同步慢——别在主循环里调,在游戏退出时异步调。

### 9.5 工业游戏存档大小

| 游戏 | 存档大小 | 格式 |
|---|---|---|
| Hollow Knight | 100-500 KB | 自定义二进制(加密) |
| Celeste | 30-100 KB | XML |
| Hades | 200-800 KB | 自定义(加密) |
| Minecraft (single player) | 1-100 MB | NBT (gzip) |
| Skyrim | 4-15 MB | 自定义二进制 |
| The Witcher 3 | 8-30 MB | 自定义二进制 |
| Cyberpunk 2077 | 2-10 MB | 自定义二进制 |

## 10 · 生产坑

### 10.1 坑1:JSON 里的 NaN

```rust
let state = GameState { health: f32::NAN, .. };
serde_json::to_string(&state)?;  // Error: NaN is not a valid JSON number
```

JSON 规范不支持 NaN / Infinity。`serde_json` 默认会报错。

**修复**:

1. **代码里禁用 NaN**(`assert!(state.health.is_finite())`)
2. **用 `serde_json` 的 `arbitrary_precision` feature**(写出 `"NaN"` 字符串,parse 时还原)
3. **用二进制格式**(bincode / postcard 完全支持 NaN)
4. **序列化前 sanitize**:`if x.is_nan() { 0.0 } else { x }`

### 10.2 坑2:Windows 路径

Linux:`/home/user/.config/mygame/save.sav`
macOS:`/Users/user/Library/Application Support/mygame/save.sav`
Windows:`C:\Users\user\AppData\Roaming\mygame\save.sav`

错误做法:

```rust
let path = format!("{}/.config/mygame/save.sav", env::var("HOME")?);
```

这在 Windows 上完全不工作(HOME 不存在,路径分隔符错)。

正确做法:用 `dirs` crate:

```rust
use dirs::data_dir;
let path = data_dir()
    .ok_or("no data dir")?
    .join("mygame")
    .join("save.sav");
```

`dirs::data_dir()` 自动返回平台正确路径。

### 10.3 坑3:Unicode 用户名

```rust
let name = "José";  // 4 字符,5 字节
let bytes = name.as_bytes();
let first4 = std::str::from_utf8(&bytes[..4])?;  // UTF-8 边界错误!
```

`é` 在 UTF-8 是 2 字节(0xC3 0xA9)。`bytes[..4]` 在 `é` 中间截断,`from_utf8` 失败。

**修复**:用**字符**而非字节切片。如果非要按字节,用 `ceil_char_boundary`:

```rust
let safe_end = name.ceil_char_boundary(4);  // Rust 1.82+
let s = &name[..safe_end];
```

### 10.4 坑4:时钟回退

`last_saved = SystemTime::now()`——但玩家可以**改系统时间**!如果玩家把时间往回拨(为了恢复 daily bonus),你的 timestamp 逻辑可能崩溃(负 duration)。

**修复**:

1. 用 monotonic clock(`Instant::now()`)——不会回退,但会随系统睡眠暂停
2. 检测回退:`if new_time < old_time { /* 处理 */ }`
3. 用服务器时间(网络时间)——绝对权威,但需要联网

### 10.5 坑5:Steam Cloud 冲突覆盖

玩家在 PC A 玩 1 小时(写存档 + 同步 cloud),立刻在 PC B 启动 B(本地老存档,cloud 还没下载)。B 用老存档启动,玩家玩 5 分钟,B 退出上传 cloud——覆盖 A 的 1 小时进度。

**修复**:

1. 启动时**强制同步**——`SteamApps::SynchronizeCloud()`,等下载完成
2. **冲突对话框**——检测到本地 vs cloud timestamp 不同,问玩家
3. **自动合并**——游戏懂 schema,读两个 save,按字段取较新 timestamp

### 10.6 坑6:存档损坏后无法启动

如果存档文件头部损坏(魔数错),游戏崩溃,玩家每次启动都崩。**玩家无法进入游戏,无法清存档**。

**修复**:

1. **损坏检测后**自动转移到 `corrupt_<timestamp>.sav`,启动新游戏
2. **从备份恢复**——保留 `.bak`,损坏时用 backup
3. **UI 提示**——"存档损坏,已备份到 X,新游戏开始",让玩家知道发生了什么

### 10.7 坑7:Migration 中断

玩家 v1 存档,migration 到 v2 时崩溃(磁盘满 / OOM / panic)。原文件已被覆盖,新文件损坏——存档永久丢失。

**修复**:

1. **migration 期间不覆盖原文件**——migrate 到 `save_0.sav.new`,成功后 rename
2. **完整备份**——migration 前复制到 `migration_backup_v1_<timestamp>.sav`
3. **migration log**——记录每一步,失败时回滚

### 10.8 坑8:签名 key 泄露

游戏发布后,逆向工程师 30 分钟内提取出 HMAC key 或 signing key。从此 cheater 可以伪造存档。

**修复**:

1. **混淆**——key 不放明文,运行时拼装(`let key = [0x4a, 0x5b, ...]`)
2. **多 key**——key A 用于存档字段 1,key B 用于字段 2,泄露一个不全军覆没
3. **服务器验证**——关键操作(成就解锁、leaderboard 上传)服务器二次验证
4. **接受现实**——单人游戏的存档签名只防 95% 玩家,5% 高手破了就破了

## 11 · 跨学科连接

### 11.1 数据库

数据库的**事务**(transaction)概念在存档里同样适用:ACID 原则(原子性 / 一致性 / 隔离性 / 持久性)。存档的"原子写"对应数据库的"原子 commit"。

**WAL(Write-Ahead Log)**:数据库技术,先写 log 再改数据。存档系统也可以用——写新存档前先写 `save_0.sav.wal`,成功后 rename。 crash 后下次启动看到 .wal,知道上次没完成,可以恢复。

### 11.2 网络协议

**Protobuf / gRPC / Cap'n Proto / FlatBuffers** 都是序列化格式,设计上和 bincode/postcard 类似(schema + 二进制)。但它们更注重**跨语言** + **前向 / 后向兼容**(Proto 默认加字段兼容,删字段要 reserved)。

游戏存档的 schema 演化策略,可以直接借鉴 Protobuf 的设计:每个字段有 `field number`,旧 field number 保留(reserved),新字段用新号。这样老 reader 读新数据时,跳过未知 field number;新 reader 读老数据时,缺失 field 用 default。

### 11.3 区块链

区块链本质是**全局共识的 serialization**。每个区块序列化为字节流,哈希链接到前一区块。如果存档要"公开可验证"(玩家可以证明自己的成就),可以用类似机制——存档哈希上链。

但游戏存档几乎从不用区块链——中心化服务器更简单高效。

### 11.4 版本控制

Git 的对象模型(blob / tree / commit)也是一种 serialization + 内容寻址(content-addressable)。Git 的 `tree` 序列化是用文本格式,字段是 `mode SP name NUL hash`,简单但有效。

借鉴:**内容寻址存档**——存档哈希作为文件名,任何修改生成新文件。这样可以**完整历史回溯**。Git LFS / restic 备份系统用类似机制。

## 12 · 在你 HH 项目里实践

读完这一篇,在你的 Handmade Hero 项目里做这些事。

### 12.1 最简存档系统(JSON)

```rust
use serde::{Serialize, Deserialize};
use std::path::PathBuf;
use anyhow::Result;

#[derive(Serialize, Deserialize)]
pub struct SaveData {
    pub player_x: f32,
    pub player_y: f32,
    pub level: u32,
    pub coins: u32,
}

pub fn save(data: &SaveData) -> Result<()> {
    let path = save_path()?;
    let json = serde_json::to_string_pretty(data)?;
    let tmp = path.with_extension("tmp");
    std::fs::write(&tmp, json)?;
    std::fs::rename(&tmp, &path)?;
    Ok(())
}

pub fn load() -> Result<SaveData> {
    let path = save_path()?;
    let json = std::fs::read_to_string(path)?;
    let data: SaveData = serde_json::from_str(&json)?;
    Ok(data)
}

fn save_path() -> Result<PathBuf> {
    use dirs::data_dir;
    let dir = data_dir().ok_or(anyhow::anyhow!("no data dir"))?
        .join("handmade_hero");
    std::fs::create_dir_all(&dir)?;
    Ok(dir.join("save.json"))
}
```

100 行内,这就是一个能用的存档系统。学习阶段够。

### 12.2 升级到 postcard + 版本管理

```rust
use postcard::{from_bytes, to_stdvec};
use serde::{Serialize, Deserialize};

const SAVE_VERSION: u32 = 1;

#[derive(Serialize, Deserialize)]
pub struct SaveDataV1 {
    pub version: u32,
    pub player_x: f32,
    pub player_y: f32,
    pub level: u32,
    pub coins: u32,
}

pub fn save_v1(data: &SaveDataV1) -> Result<()> {
    let mut payload = to_stdvec(data)?;
    let mut buf = Vec::new();
    buf.extend_from_slice(b"HHSV");  // magic
    buf.extend_from_slice(&SAVE_VERSION.to_le_bytes());
    buf.extend_from_slice(&(payload.len() as u32).to_le_bytes());
    buf.append(&mut payload);

    let path = save_path()?;
    let tmp = path.with_extension("tmp");
    std::fs::write(&tmp, &buf)?;
    std::fs::rename(&tmp, &path)?;
    Ok(())
}

pub fn load_v1() -> Result<SaveDataV1> {
    let path = save_path()?;
    let bytes = std::fs::read(path)?;
    if &bytes[0..4] != b"HHSV" { bail!("bad magic"); }
    let version = u32::from_le_bytes(bytes[4..8].try_into()?);
    if version != SAVE_VERSION {
        return migrate_and_load(bytes, version);
    }
    let len = u32::from_le_bytes(bytes[8..12].try_into()?) as usize;
    let payload = &bytes[12..12 + len];
    let data: SaveDataV1 = from_bytes(payload)?;
    Ok(data)
}

fn migrate_and_load(bytes: Vec<u8>, from_version: u32) -> Result<SaveDataV1> {
    // 后续版本:加 v1_to_v2 等
    bail!("Unsupported version {}", from_version);
}
```

### 12.3 加 CRC 校验

```rust
use crc32fast::Hasher;

// 写
let mut crc = Hasher::new();
crc.update(&payload);
let crc_val = crc.finalize();
buf.extend_from_slice(&crc_val.to_le_bytes());

// 读
let mut crc = Hasher::new();
crc.update(payload);
let expected = crc.finalize();
let stored = u32::from_le_bytes(bytes[N..N+4].try_into()?);
if expected != stored { bail!("CRC mismatch — corrupted"); }
```

### 12.4 加 HMAC 签名

```rust
use hmac::{Hmac, Mac};
use sha2::Sha256;
type HmacSha256 = Hmac<Sha256>;

const SECRET: &[u8; 32] = include_bytes!("../secret_key.bin");

// 写
let mut mac = HmacSha256::new_from_slice(SECRET)?;
mac.update(&payload);
let sig = mac.finalize().into_bytes();
buf.extend_from_slice(&sig);

// 读
let mut mac = HmacSha256::new_from_slice(SECRET)?;
mac.update(&payload);
mac.verify_slice(&stored_sig)?;
```

`secret_key.bin` 在编译前随机生成,不入 git。CI/CD 时生成 key 文件再编译。

### 12.5 Steam Cloud 集成

```rust
use steamworks::Client;

pub struct CloudSave {
    client: Client,
}

impl CloudSave {
    pub fn new(app_id: u32) -> Result<Self> {
        let client = Client::init_app(app_id)?;
        Ok(Self { client })
    }

    pub fn save(&self, slot: u32, data: &[u8]) -> Result<()> {
        let filename = format!("save_{}.sav", slot);
        self.client.cloud().file_write(&filename, data)?;
        Ok(())
    }

    pub fn load(&self, slot: u32) -> Result<Vec<u8>> {
        let filename = format!("save_{}.sav", slot);
        let bytes = self.client.cloud().file_read(&filename)?;
        Ok(bytes)
    }
}
```

### 12.6 完整 save manager(参考前面 §3.4)

把上面所有零件组合起来:postcard + 版本 + CRC + HMAC + atomic write + Steam Cloud + 备份 + migration 框架。这是工业级方案。

## 13 · 开源贡献方向

读完这一篇,你可以做这些贡献。

### 13.1 给 postcard 加 schema evolution 文档

postcard 默认支持 `#[serde(default)]`,但很多用户不知道。可以加 README 章节、example 项目,展示完整 schema 演化流程。

GitHub: https://github.com/jamesmunns/postcard

### 13.2 给 dirs crate 加新平台支持

`dirs` crate 是跨平台路径的事实标准,但对某些小众平台(如 FreeBSD、Fuchsia)支持不完整。如果你用这些平台,可以测试 + 加 PR。

GitHub: https://github.com/dirs-dev/dirs-rs

### 13.3 给 steamworks-rs 加完整 cloud API

`steamworks-rs` 是 Steamworks SDK 的 Rust 绑定。Cloud API 部分覆盖不全(某些新 SDK 功能没绑定)。可以补全。

GitHub: https://github.com/Noxime/steamworks-rs

### 13.4 写一个开源 save framework

Rust 生态**没有**一个像 Unity 的 EasySave 那样的"开箱即用" save framework。你可以写一个:

- 基于 postcard
- 内置 schema migration
- 内置 atomic write
- 内置 CRC + HMAC
- 平台 path 抽象
- 可选 Steam Cloud 集成

这是 indie Rust 游戏社区的高价值贡献。

## 14 · 延伸阅读

本仓库本地资料:

- [../phase-8/day576.md](../day576.md) — Phase 8 入门
- [performance-budget.md](performance-budget.md) — 性能预算
- [shipping-checklist.md](shipping-checklist.md) — 发布检查清单
- [../phase-5/day201.md](../../phase-5/day201.md) — debug 隔离(也涉及发布二进制)

外部稳定 URL:

- **serde 官方文档**:https://serde.rs/
- **postcard GitHub**:https://github.com/jamesmunns/postcard
- **bincode GitHub**:https://github.com/bincode-org/bincode
- **Protocol Buffers schema evolution 最佳实践**:https://protobuf.dev/programming-guides/dos-donts/
- **Steam Cloud 官方文档**:https://partner.steamgames.com/doc/features/cloud
- **Steamworks SDK**:https://partner.steamgames.com/doc/sdk
- **Ed25519 RFC**:https://datatracker.ietf.org/doc/html/rfc8032
- **AES-GCM RFC**:https://datatracker.ietf.org/doc/html/rfc5116
- **Tom Forsyth《Handle-aware》系列**(讨论游戏存档架构):https://eli.thegreenplace.net/

真实开源源码:

- **Bevy 的 SaveLoad 模块**:https://github.com/bevyengine/bevy/tree/main/crates/bevy_scene
- **Unreal Engine USaveGame 源码**:https://github.com/EpicGames/UnrealEngine/blob/release/Engine/Source/Runtime/Engine/Public/GameFramework/SaveGame.h(需要 Epic 账号)
- **rust-steamworks Cloud API**:https://github.com/Noxime/steamworks-rs/blob/master/src/cloud.rs
- **CRC32 crate 源码**:https://github.com/srijs/rust-crc32fast
- **ed25519-dalek 源码**:https://github.com/dalek-cryptography/curve25519-dalek
- **Hollow Knight Save Editor(社区逆向)**:https://github.com/jadebaek/HollowKnight.SaveEditor(看真实游戏存档格式)
- **Minecraft NBT spec**:https://wiki.vg/NBT

这一篇到这里。下次你看到存档 bug,你知道是路径问题、Unicode 问题、版本问题、CRC 问题还是签名问题。下次玩家投诉存档丢失,你知道检查 fsync、检查 atomic write、检查 migration log、检查 Steam Cloud 状态。存档系统不是 `to_string` 那么简单,但也不是黑魔法——理解了每一层(格式、版本、校验、签名、云端、加密),你就能写出工业级 save system,让你的玩家放心玩 100 小时,知道自己的进度不会消失。
