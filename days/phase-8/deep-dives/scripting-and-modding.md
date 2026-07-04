
# 深入:脚本与 Mod 系统

> 你跟着 Handmade Hero 走到 Day 500。你的游戏好玩,核心循环打磨得不错。但你的朋友玩了一会儿,问你:"能不能加一把会发光的剑?"你说可以,我改 Rust 代码,重编译,发布 0.2 版本。朋友又问:"那能不能让 NPC 学会新台词?"你说,改代码,重编译。朋友第三次问:"我能不能自己加一把剑?"——你愣住了。
>
> 你的游戏是 50 MB 的可执行文件,朋友手里只有 Steam 装好的二进制。他没有 Rust 工具链,他不读你的源码,但他想加内容。**这就是 scripting & modding 要解决的问题**:把"游戏逻辑"从"二进制"里解放出来,变成可以被设计师 hot reload、可以被社区扩展、可以在不重编译的情况下改写规则的"文本"。
>
> 这份深入要回答三个问题。第一,为什么几乎所有 3A 游戏都内嵌一门脚本语言?第二,Lua 是怎么成为游戏脚本事实标准的?背后的历史、技术、工程原因是什么?第三,在 Rust 游戏里,怎么用 `mlua` 给 Handmade Hero 加一套完整的 mod 支持——从 capability 模型、热重载、Steam Workshop 集成,到 sandbox 安全?

## 0 · 为什么要有脚本系统

让我们把场景拉具体。你是一个 3A 工作室的技术美术。你需要做这些事:

- **任务 A**:调整 boss 战的攻击节奏——boss 在玩家近身时有 0.4 秒的前摇,你想改成 0.35 秒
- **任务 B**:给一把武器加特殊效果——击中敌人时 30% 概率点燃
- **任务 C**:做一个新 NPC,他会说三段话,每段触发一个剧情 flag
- **任务 D**:把圣诞活动的雪天效果临时打开,活动结束关掉
- **任务 E**:玩家社区想做"难度倍率 mod",让游戏可以 2 倍难度

如果游戏逻辑全写在 Rust / C++ 里,这五个任务都得**重编译发布**。每次重编译要 5-30 分钟,每次发布要过 QA,过平台认证,过 Steam 评审——一个礼拜。这意味着一个设计师每天最多能做 5-8 次改动。如果游戏有 100 个 boss、500 个武器、1000 个 NPC、每个季度 4 个活动,这种迭代速度你根本撑不住。

**脚本系统的核心价值**:把"改动 - 重编译 - 发布"压缩成"改动 - 热重载"。设计师改一行 Lua 文件,在游戏里按 F5,1 秒内看到效果。

我们来算账。假设一个 3A 项目有 200 个员工,其中 80 个是设计师 / 任务设计师 / 关卡设计师 / 美术 / 剧情策划。没有脚本系统,他们每改一个数字都要找程序员重编译,程序员变成瓶颈——200 个程序员都救不了。有脚本系统,设计师直接改 Lua 文件,程序员只写"底层 API"(动画、渲染、物理),任务逻辑、武器效果、剧情流程由设计师用脚本写。**这是脚本系统让 3A 游戏成为可能的根本原因**——它把"游戏内容生产"从"程序员"解耦到"设计师"。

第二个核心价值:**社区扩展**。Stardew Valley、Skyrim、Kerbal Space Program、Factorio、Garry's Mod、CryEngine 系列——这些游戏的"寿命"是普通游戏的 10 倍以上。原因不是核心游戏好玩 10 倍,而是 modding 社区持续生产内容。Skyrim 距离首发已经 15 年,2026 年今天 Steam 创意工坊还有新 mod 发布。**让玩家成为内容创作者**,是延长游戏生命周期的最强武器。

这条深入要讨论的核心工程问题:**怎么设计一个让设计师用得爽、让社区 mod 用得安全、让引擎代码用得快的脚本系统**。

## 1 · 历史回顾:Lua 为什么是游戏脚本之王

我们看一组事实。下面这些游戏 / 引擎都用 Lua(或 Lua 衍生):

- **魔兽世界**:整个 UI 系统是 Lua。暴雪暴露 API 给玩家,玩家写 addon 改 UI。这是 MMO 历史上最成功的 modding 案例——魔兽的 raid UI、伤害统计、副本地图,几乎都是社区 Lua addon。
- **CryEngine(Lumberyard / Amazon)**: CryEngine 的整个 entity / AI 系统用 Lua 脚本配置。设计师用 Lua Flowgraph 编排游戏逻辑。
- **Garry's Mod**:Source Engine 的 Lua mod 系统,诞生了 Trouble in Terrorist Town、Prop Hunt、DarkRP 等几十个独立游戏玩法。
- **Roblox**:Luau(Lua 衍生)是 Roblox 全平台的游戏脚本。Roblox 2025 年开发者分成超过 7 亿美元——所有内容都是 Luau 写的。
- **Love2D**:Lua 的 2D 游戏引擎,有一大批独立游戏(Celeste 经典版、Starsector 的部分逻辑)。
- **Factorio**:部分逻辑用 Lua(尤其是 mod 接口)。
- **Noita**:部分 wand 效果逻辑用 Lua。
- **Payday 系列**:任务逻辑用 Lua。

为什么是 Lua,不是 Python、不是 JavaScript、不是 Ruby?

历史回到 1993 年。巴西天主教大学(PUC-Rio)的 Roberto Ierusalimschy、Waldemar Celes、Luiz Henrique de Figueiredo 三个人在做一个石油公司的数据可视化项目。他们需要一个嵌入式的、轻量的、可以和 C 集成的脚本语言。当时他们的 SOL(Simple Object Language)和 DEL(data-entry language)合并,设计了 Lua 1.0。

Lua 的设计目标极其克制:

1. **小**。整个 Lua 5.4 的源码大概 25000 行 C,编译成 binary 大概 200 KB。Python 解释器 30 MB,JS 引擎(V8)几十 MB。
2. **可嵌入**。Lua 从第一天就是设计为"嵌入到宿主程序里"的——不是独立运行的脚本语言,而是"宿主程序的扩展语言"。API 极简:`lua_State`、`lua_pushxxx`、`lua_getglobal`、`lua_pcall` 这一套。
3. **极简语法**。Lua 只有 21 个关键字,语法和 Pascal 接近,设计师读起来不头大。
4. **表(table)是唯一数据结构**。Lua 的 table 既是数组又是字典,你可以用 table 模拟 class、record、tuple、set——一切。这种"一个结构统治一切"的设计降低了心智负担。
5. **注册表 + userdata 让 FFI 干净**。Lua 提供 `lua_pushlightuserdata` 把 C 指针塞进 Lua,反过来 Lua 可以通过 metatable 操作 C 对象。这套机制让 Lua 调 C 和 C 调 Lua 都很对称。
6. **没有 GC pause 问题(早期 Lua)**。Lua 5.1 用 incremental GC,5.4 用 generational GC,在游戏场景下 pause 都在可控范围。

游戏工业链被这些优势吸引。1996 年 LucasArts 的 Grim Fandango 是第一个大规模用 Lua 嵌入的商业游戏。之后 Bioware 的 Neverwinter Nights(2002)、Baldur's Gate Enhanced Edition 都跟进了。World of Warcraft(2004)的 UI 全 Lua 是 Lua 的"出圈"事件——一夜之间,游戏社区都在学 Lua。

到了 2026 年,Lua 仍然是游戏脚本的事实标准。但 Rust 时代有几个新候选,我们下一节讨论。

## 2 · 现代候选:Lua / Rune / Rhai / rust-script / Wasm / Python

把同一份"嵌入式脚本"需求放在 2026 年的 Rust 生态里,候选有这些:

| 候选 | 语言 | 宿主语言绑定 | 性能 | 沙箱难度 | 热重载 | 嵌入复杂度 |
|---|---|---|---|---|---|---|
| **Lua 5.4** | Lua | C ABI(rlua/mlua/hlua) | 中(快于 Python,慢于 LuaJIT) | 易(成熟沙箱) | 易(文件 watch) | 易 |
| **LuaJIT** | Lua | C ABI | 极快(JIT,接近原生 C) | 中(FFI 模块有安全风险) | 易 | 中(LuaJIT 维护停滞) |
| **Luau** | Lua 衍生 | C++ ABI | 快(AOT 编译) | 易(内置 type system 和 capability) | 易 | 中(绑定 Rust 麻烦) |
| **Rune** | Rust 风格 | Rust 原生 | 中 | 极易(纯 Rust,无 unsafe 漏洞) | 中 | 极易 |
| **Rhai** | Rust 风格 | Rust 原生 | 中慢 | 极易 | 中 | 极易 |
| **Wasm** | 任何语言 | Rust wasmtime / wasmer | 快(接近原生) | 中(线性内存,需要 capability 模型) | 中(需要 wasm 重编) | 中 |
| **Python (PyO3)** | Python | Rust PyO3 | 慢 | 难(无限 IO 能力) | 中 | 难 |
| **JavaScript (boa / deno_core)** | JS | Rust boa / V8 | 中(JIT 后) | 难(V8 漏洞历史多) | 中 | 中 |
| **rust-script / cargo-script** | Rust | Rust 编译器 | 极快(原生) | 不可能(完整 Rust) | 极慢(编译) | 极难 |

每个选型都有具体的"为什么选"和"为什么不选"。让我拆开看:

**Lua(标准 5.4)** 是"安全选择"。生态最成熟,游戏社区人都懂,Rust 的 `mlua` crate 支持完整 API。性能足够(配合 LuaJIT 接近原生 70%)。沙箱成熟——你可以禁用 `os.execute`、`io.read`、`loadfile` 等危险函数。**如果你做的是一个普通独立游戏,选 Lua**。

**LuaJIT** 是"性能选择"。Mike Pall 的 LuaJIT 是脚本语言工程的奇迹——一个 tracing JIT 把动态语言跑到接近原生速度。但 LuaJIT 5.1 卡住了,Mike Pall 半退休,5.2+ 的语法(比如 `goto`)和 bit operations 在 LuaJIT 里支持不完整。**如果你需要每帧跑几百万次脚本调用,选 LuaJIT**。Factorio 是 LuaJIT 的著名用户——他们每帧跑几万次 Lua 调用,没有 LuaJIT 根本跑不动。

**Luau** 是 Roblox 的 Lua 衍生。它做了几件事:渐进式类型系统、AOT 编译(不是 JIT,所以更可预测)、sandbox-first 设计。Luau 的沙箱是"语言级"的——默认就没有 `os.execute`、`io.read`,需要 explicit opt-in。这对 mod 系统非常友好。但 Luau 用 C++ 写的,Rust 绑定还不太成熟(`mlua` 有 Luau 后端,但维护不积极)。**如果你的游戏主要面向 Roblox 类玩家社区,选 Luau**。

**Rune** 是 Rust 写的 Rust 风格脚本语言。语法接近 Rust,所以 Rust 程序员写脚本不用换脑子。**关键优势:沙箱是默认的**——Rune 没有任何 IO 能力,所有 IO 都要宿主提供。这意味着一个 mod 作者不可能"在 Rune 里写一个删硬盘"的代码——Rune 根本不知道硬盘是什么。**如果你想要最严格的沙箱和最 Rust 友好的语法,选 Rune**。

**Rhai** 是另一个 Rust 写的脚本语言。和 Rune 类似,但更老、更稳定。语法是 JS-ish。性能比 Rune 慢一点。**如果你想要一个稳定、社区成熟的纯 Rust 脚本语言,选 Rhai**。

**Wasm**(WebAssembly)是"未来选项"。脚本作者用任何语言(C# / Rust / AssemblyScript / Zig)写代码,编译成 .wasm,游戏用 wasmtime 加载。优势:性能接近原生(只比原生慢 10-30%)、语言自由、内存沙箱极严(线性内存,看不到宿主进程的内存)、有完整的 capability 模型(WASI Capabilities)。劣势:工具链复杂(脚本作者要装 wasm 工具链)、调试器不成熟、热重载要重编 wasm。**如果你做的是一个有严肃 modding 社区、要求极高性能的 mod 系统(类似 Minecraft 的 Java modding),选 Wasm**。

**Python** 几乎不要选。Python 太大(嵌入 binary 30 MB)、太慢、沙箱难做(`os.system` 这种"删库"函数在 `__builtins__` 里,要靠 ` RestrictedPython` 这种半成品)。**例外**:如果你的游戏是教育向(类似 Minecraft Education Edition 教 Python),那么 Python 是必选。其他场景都不要选。

**JavaScript** 也几乎不要选,理由和 Python 类似——V8 太大、漏洞历史多。例外:如果你的游戏是 WebAssembly 跑在浏览器里,JavaScript 是唯一选择。

**rust-script** 是"非选项"。让脚本作者写 Rust 然后编译——这是把"脚本的灵活性"和"编译的速度"全都放弃了。**别选**。

**Handmade Hero 的选型建议**:Lua + mlua。理由:

1. Lua 是游戏脚本事实标准,社区文档丰富,设计师学起来快
2. mlua 是 Rust 生态最成熟的 Lua 绑定
3. 性能足够,你可以后期换 LuaJIT 后端
4. 沙箱成熟,我们可以站在巨人肩膀上
5. Steam Workshop 集成 Lua 文件就是文本文件,玩家用记事本都能改

下面我们以 Lua + mlua 为基础,讲完整套 scripting & modding 的实现。

## 3 · Rust Lua 集成:rlua / mlua / hlua 的对比

Rust 生态里有三个主流的 Lua 绑定:

**hlua**(废弃)。这是早期尝试,把 Lua API 直接暴露成 Rust trait。设计有问题——生命周期管理粗糙,容易泄漏。2018 年后基本停止维护。**不要用**。

**rlua**(维护中)。Capcom 等公司用的 Lua 绑定。安全性最好——它用 Rust 类型系统严格管理 Lua 栈,基本不可能写出"pop 多了导致段错误"的代码。但代价是 API 比较 verbose,泛型参数满天飞。如果你写的是生产级服务(金融、医疗),rlua 的安全性值得。**游戏场景用 mlua 更多**。

**mlua**(活跃维护)。当前 Rust 生态最主流的 Lua 绑定。支持多个 Lua 后端:Lua 5.4、Lua 5.3、Lua 5.2、Lua 5.1、LuaJIT、Luau。一套 API,换后端一行 Cargo.toml 改动。性能好(零成本抽象,大量 inline)、文档清晰、社区活跃。**我们用 mlua**。

mlua 的 Cargo.toml 配置:

```toml
[dependencies]
mlua = { version = "0.10", features = ["lua54", "vendored"] }
```

- `lua54` 启用 Lua 5.4 后端。换成 `luajit` 就用 LuaJIT,`luajit52` 用兼容 5.2 语法的 LuaJIT,`luau` 用 Luau。
- `vendored` 把 Lua C 源码编译进你的 binary,不依赖系统 liblua。这是 Rust 游戏发布的标配——玩家机器没有 liblua5.4.so,你必须 statically link。

mlua 的最小例子:

```rust
use mlua::{Lua, Result};

fn main() -> Result<()> {
    // 创建一个 Lua 状态机
    let lua = Lua::new();

    // 执行一段 Lua 代码
    lua.load("print('Hello from Lua!')").exec()?;

    // 从 Rust 调 Lua 函数
    let sum: i32 = lua.load("return 2 + 3").eval()?;
    println!("2 + 3 = {}", sum);

    // Rust 函数注册到 Lua
    lua.globals().set("double", |x: i32| x * 2)?;

    // Lua 调 Rust 函数
    let result: i32 = lua.load("return double(21)").eval()?;
    println!("double(21) = {}", result);

    Ok(())
}
```

第一行 `Lua::new()` 创建一个独立的 Lua state——每个 state 有自己的全局表、栈、GC。游戏里通常一个 state 跑 mod 脚本,另一个 state 跑 UI 脚本,互不干扰。

`lua.load(...).exec()` 和 `lua.load(...).eval()` 的区别:`exec` 执行但不取返回值(适合多行脚本);`eval` 取返回值(适合表达式)。底层都是 Lua 的 `lua_pcall`。

`lua.globals().set("double", ...)` 把一个 Rust 闭包注册到 Lua 的全局表 `_G`。Lua 调用 `_G.double(x)` 时,mlua 的桥接代码会把 Lua 栈里的 `x` 转成 Rust `i32`,调用闭包,把结果 `i32` 转回 Lua 值压栈。这套转换由 `mlua::IntoLua` 和 `mlua::FromLua` trait 自动派生(类似 serde)。

更复杂的例子——把 Rust struct 暴露给 Lua:

```rust
use mlua::{Lua, UserData, UserDataMethods, Result};

// 一个游戏实体
#[derive(Clone)]
struct Player {
    name: String,
    hp: i32,
    max_hp: i32,
    x: f32,
    y: f32,
}

// 实现 UserData 让 Lua 能操作这个 Rust 对象
impl UserData for Player {
    fn add_fields<F: mlua::UserDataFields<Self>>(_fields: &mut F) {
        // 暴露只读字段 name
        _fields.add_field_method_get("name", |_, this| Ok(this.name.clone()));
        // 暴露读写字段 hp
        _fields.add_field_method_get("hp", |_, this| Ok(this.hp));
        _fields.add_field_method_set("hp", |_, this, val| {
            this.hp = val.clamp(0, this.max_hp);
            Ok(())
        });
    }

    fn add_methods<M: UserDataMethods<Self>>(_methods: &mut M) {
        // 暴露方法 heal
        _methods.add_method("heal", |_, this, amount: i32| {
            this.hp = (this.hp + amount).min(this.max_hp);
            Ok(())
        });
        // 暴露方法 distance_to
        _methods.add_method("distance_to", |_, this, (ox, oy): (f32, f32)| {
            let dx = this.x - ox;
            let dy = this.y - oy;
            Ok((dx * dx + dy * dy).sqrt())
        });
    }
}

fn main() -> Result<()> {
    let lua = Lua::new();

    // 把 Player 全局对象注册到 Lua
    let player = Player {
        name: "Hero".into(),
        hp: 50,
        max_hp: 100,
        x: 10.0,
        y: 20.0,
    };
    lua.globals().set("player", player)?;

    // Lua 脚本可以用 Rust 的 Player
    lua.load(r#"
        print("Player name:", player.name)
        print("HP before:", player.hp)
        player:heal(30)
        print("HP after heal:", player.hp)
        local d = player:distance_to(0, 0)
        print("Distance to origin:", d)
    "#).exec()?;

    Ok(())
}
```

这套 `UserData` trait 是 mlua 暴露 Rust 对象给 Lua 的核心机制。Lua 看到的 `player` 是一个 userdata(原始的字节 blob),metatable 里定义了 `__index`、`__newindex` 等 metamethod,这些 metamethod 在 Lua 访问字段或调用方法时被触发,内部跳到 Rust 闭包。这是 Lua 的标准"面向对象模拟"——所有 Lua OOP 都靠 metatable。

`add_field_method_get` 接受一个闭包 `|lua, this| -> Result<T>`。`lua` 是当前 Lua state(你通常不用),`this` 是 `&Player`(可读)。`add_field_method_set` 多一个 `val: T` 参数(`&mut this, val`)。`add_method` 类似,但额外接收 Lua 调用参数 tuple。

Rust → Lua 的转换通过 `IntoLua` 实现(类似 `Serialize`),Lua → Rust 反方向通过 `FromLua`。基本类型(`i32`、`f64`、`String`、`bool`)都自动实现。自定义类型通过 `UserData`。复合类型(tuple / vec / hashmap)用 `IntoLua` derive 或手动 impl。

## 4 · API 设计:暴露游戏状态 / 函数 / 事件

设计脚本 API 是 scripting 系统最难的部分。技术上是简单的——把 Rust 函数注册到 Lua。难的是**设计选择**:暴露什么、不暴露什么、用什么名字、什么粒度。

工业里有四条 API 设计原则,我们一条条看。

### 原则一:最小接口

每个暴露给脚本的函数都是攻击面。如果 mod 作者能调 `game.set_player_hp(99999)`,他们就会(作弊)。如果他们能调 `os.remove("/etc/passwd")`,他们就会(恶意 mod)。

所以 API 设计的默认答案是"不暴露"。每一个 `register_function` 都需要辩护——"为什么这个函数必须暴露给脚本"。

Lua 默认的全局表 `_G` 包含 `print`、`pairs`、`type`、`tostring` 等纯函数(没副作用),也包括 `os`(系统调用)、`io`(文件 IO)、`loadfile`(读任意文件)、`require`(加载模块)、`debug`(反射 / 调试库,能读取栈上任何值)。后面这几个**必须**在沙箱里禁掉。我们在沙箱一节详细讨论。

最小接口的设计:把"游戏内能做的事"按"玩法"分类,每类暴露 10-20 个函数。比如:

- `player` namespace:`player.get_hp()`, `player.heal(amount)`, `player.set_pos(x, y)`, ...
- `enemy` namespace:`enemy.spawn(type, x, y)`, `enemy.kill(id)`, ...
- `world` namespace:`world.get_tile(x, y)`, `world.set_tile(x, y, tile)`, ...
- `event` namespace:`event.on("damage", callback)`, `event.emit("custom_event", data)`, ...
- `ui` namespace:`ui.show_message(text)`, `ui.add_button(text, callback)`, ...
- `audio` namespace:`audio.play_sound(name)`, `audio.set_volume(vol)`, ...

每个 namespace 10-20 个函数,总共 100-200 个函数。这是单人独立游戏的规模。3A 游戏有 1000+ 函数(Skyrim 的 Papyrus API 有 2000+ 函数,魔兽的 Lua API 有 3000+)。

### 原则二:正交命名

函数名字要 predictable——脚本作者看到 `player.get_hp()` 就知道有 `player.set_hp()`,看到 `enemy.spawn` 就知道有 `enemy.despawn`。这种"对称命名"让 API 可猜。

反例:`player.get_hp()` 和 `player.set_health()`(不一致)、`enemy.spawn` 和 `enemy.delete`(没对称)。这些都让 API 难学。

命名风格统一。要么全 `snake_case`(Lua 习惯),要么全 `camelCase`(JS 习惯),不要混。Lua 社区惯例是 `snake_case`。

### 原则三:不可变优先

API 应该尽量返回不可变视图(`&Player`),让脚本"看"游戏状态而不是"改"。`player.get_hp()` 返回 i32(值类型),脚本拿到的是副本,改它不影响游戏。`player.get_pos()` 返回 `(f32, f32)` tuple,也是值类型。

如果脚本要修改游戏状态,必须 explicit——通过 `player.set_pos(x, y)` 这种 setter,而不是 `local p = player.get_pos_mut(); p.x = 10`(返回可变引用)。Lua 的 metatable 不容易干净地表达"返回只读 view",所以最佳实践就是返回值类型 + 显式 setter。

### 原则四:事件驱动

游戏逻辑的核心是"事件"——玩家受伤、敌人死亡、子弹命中、boss 阶段切换、对话选项被选。脚本系统要 expose 这些事件,让 mod 注册 callback。

```lua
-- 在 mod 里注册一个 callback:玩家受伤时打印日志
event.on("player_damaged", function(data)
    print("Player took " .. data.amount .. " damage from " .. data.source)
end)

-- 注册一个 callback:敌人死亡时掉金币
event.on("enemy_killed", function(data)
    if data.enemy_type == "goblin" then
        world.spawn_item("gold_coin", data.x, data.y)
    end
end)
```

事件系统的 Rust 实现我们后面写。设计上几个关键决策:

- **事件名字符串**:简单,易扩展,但拼写错误只能 runtime 发现
- **事件 data 是 Lua table**:灵活,但要约定 schema
- **callback 返回值**:有的事件支持"取消"——`event.on("player_damaged", function(d) return false end)` 表示取消这次伤害。这种约定要写文档

事件系统的核心抽象是 **publisher / subscriber**。游戏内部代码是 publisher(`event.emit("player_damaged", {...})`),脚本是 subscriber(`event.on("player_damaged", callback)`)。

### 完整的 API 设计骨架

把上面四原则综合,一个典型 mod API 设计大致是:

```lua
-- 这是个示意,展示给 mod 作者的 API surface

-- 玩家相关
player.get_hp() -> integer
player.get_max_hp() -> integer
player.heal(amount: integer)
player.damage(amount: integer, source: string)
player.get_pos() -> number, number   -- x, y
player.set_pos(x: number, y: number)
player.give_item(item_id: string, count: integer)
player.remove_item(item_id: string, count: integer) -> boolean

-- 敌人相关
enemy.spawn(enemy_type: string, x: number, y: number) -> EnemyId
enemy.kill(enemy_id: EnemyId)
enemy.get_pos(enemy_id: EnemyId) -> number, number
enemy.set_target(enemy_id: EnemyId, target: "player" | EnemyId)

-- 世界相关
world.get_tile(x: integer, y: integer) -> string
world.set_tile(x: integer, y: integer, tile: string)
world.spawn_item(item_id: string, x: number, y: number)
world.time_of_day() -> number  -- 0..24
world.set_time_of_day(hours: number)

-- UI 相关
ui.show_message(text: string)
ui.show_dialogue(speaker: string, text: string, choices: table)

-- 音频相关
audio.play_sound(sound_id: string)
audio.play_music(track_id: string)

-- 事件(注册 callback)
event.on(event_name: string, callback: function) -> ListenerId
event.off(listener_id: ListenerId)
event.emit(event_name: string, data: table)

-- Mod 元数据(只读)
mod.name() -> string
mod.version() -> string
mod.data_path() -> string  -- 返回 mod 自己的数据目录
```

这是一个骨架。真实 3A 项目的 API 文档有几百页(魔兽的 Lua API 文档光目录就 30 页)。但骨架的"形状"就是这样:几个 namespace,每个 namespace 一组正交、最小、事件驱动的函数。

## 5 · 沙箱:防止 mod 干坏事

脚本系统最大的风险是**恶意 mod**。一个 mod 作者写一段 Lua 代码,你想让他能"修改 boss 战节奏",但不希望他能"读取玩家密码文件"、"上传玩家存档到他的服务器"、"植入加密货币矿工"。

沙箱是工程上最难的部分。我们一层层讨论。

### 5.1 第一层:禁用危险标准库

Lua 默认的全局环境包含这些危险库:

- `os` —— `os.execute`, `os.exit`, `os.getenv`, `os.remove`, `os.rename`。所有这些都是致命的——`os.execute("rm -rf /")` 能让玩家电脑报废。
- `io` —— `io.open`, `io.read`, `io.write`。读写任意文件。
- `loadfile` —— 加载任意 Lua 文件。
- `dofile` —— 同上。
- `require` —— 默认能 require 任何 Lua 模块,如果模块搜索路径包含系统目录,能加载恶意代码。
- `debug` —— `debug.getinfo`, `debug.getlocal`, `debug.setlocal`。反射能力,能读取栈上任何值,绕过封装。
- `package` —— Lua 的模块加载系统,可以加载 C 扩展(`.so` / `.dll`),直接 RCE。

mlua 创建 Lua state 时,**默认不加载**这些库。你必须显式开启。也就是说:

```rust
let lua = Lua::new();
// mlua 默认:os / io / loadfile / dofile / debug / package 都不加载
// 这是 mlua 的安全默认
```

如果你想给 mod 提供"只读文件访问"——比如让他们能读自己 mod 目录里的文件,你可以 expose 一个受限的 `mod.read_file(filename)`,内部检查 filename 是不是在 mod 自己的目录下,然后再调 Rust 的 `std::fs::read`。这是"capability-based security"——mod 默认没有任何 IO 能力,你显式给它"读自己目录"的能力。

```rust
lua.globals().set("read_mod_file", |path: String| -> mlua::Result<Vec<u8>> {
    let mod_dir = current_mod_dir();  // 当前 mod 的目录
    let full = mod_dir.join(&path);
    // 检查 full 还在 mod_dir 里(防止 ../../etc/passwd 攻击)
    match full.canonicalize() {
        Ok(p) if p.starts_with(&mod_dir) => {
            std::fs::read(&p).map_err(|e| mlua::Error::ExternalError(e.into()))
        }
        _ => Err(mlua::Error::RuntimeError("path traversal blocked".into())),
    }
})?;
```

这个 `read_mod_file` 实现做了三件事:第一,所有路径都 join 到 mod 自己的目录;第二,`canonicalize` 解析 symlink 和 `..`,防止 `../../../etc/passwd` 这种路径穿越攻击;第三,检查 canonicalize 之后的路径是否仍然以 mod_dir 开头,如果不是就拒绝。

### 5.2 第二层:资源限制(超时 / 内存)

恶意 mod 不一定要破坏文件——它也可以"消耗资源"。一段死循环 `while true do end` 会让游戏卡死。一段持续分配内存的代码 `local t = {}; while true do t[#t+1] = "x" end` 会让游戏 OOM。

Lua 5.4 提供 **instruction count hook**——你可以告诉 Lua "每执行 N 条指令就调用一次 hook",hook 里检查是不是超时。mlua 暴露成 `lua.set_hook`:

```rust
use mlua::{Lua, HookTriggers, DebugEvent};

let lua = Lua::new();

// 设置 instruction limit:每 1000 条指令触发一次 hook
lua.set_hook(HookTriggers::new().on_every_count(1000), |_lua, debugger| {
    // debugger 是当前调用的元信息
    // 我们用一个 thread-local counter 记录已执行指令数
    thread_local! {
        static INSTRUCTIONS: std::cell::Cell<u64> = std::cell::Cell::new(0);
    }
    INSTRUCTIONS.with(|c| {
        let n = c.get() + 1000;
        c.set(n);
        if n > 100_000_000 {  // 1 亿条指令上限
            Err(mlua::Error::RuntimeError("Script instruction limit exceeded".into()))
        } else {
            Ok(())
        }
    })
});
```

这个 hook 每 1000 条指令触发一次。我们在 hook 里累加计数,超过上限就报错中断脚本。100M 条指令在 Lua 大概对应 1-2 秒的纯 CPU 时间——足够任何合理的 mod 初始化,但不够 DoS 攻击。

内存限制 Lua 没有内置 API。你可以通过 allocator hook(Lua 的 `lua_Alloc`)统计分配的字节数,超过阈值就返回 NULL 让 Lua OOM。但这个比较复杂,大多数游戏不做——他们靠 instruction limit 兜底,因为内存爆破需要 N 条指令分配,先撞到指令限制。

### 5.3 第三层:字节码验证

Lua 有个微妙漏洞——`loadstring` 函数能加载任意 Lua 字节码(不只是源码)。Lua 字节码是低级格式,直接执行,有历史漏洞能通过精心构造的字节码实现 RCE(2008 年 CVE-2008-7321 等)。

解决方案:**禁用 `loadstring` 的字节码模式**,只接受源码。mlua 默认就是这样。`lua.load(source)` 内部用 `luaL_loadstringx`,这个函数检测 source 是源码还是字节码,如果是字节码会拒绝(除非显式启用 `load_bytecode` 模式)。

如果你给 mod 暴露 `loadstring`,务必验证:

```rust
lua.globals().set("loadstring", |src: String| -> mlua::Result<mlua::Function> {
    // 拒绝字节码(Lua 字节码以 0x1B Lua 或类似 magic 开头)
    if src.as_bytes().first().map(|&b| b < 0x20 && b != 0x09 && b != 0x0A && b != 0x0D).unwrap_or(false) {
        return Err(mlua::Error::RuntimeError("bytecode loading disabled".into()));
    }
    let lua = mlua::Lua::new();  // 用临时 state 加载(实际生产用 current lua)
    let f = lua.load(src).into_function()?;
    Ok(f)
})?;
```

### 5.4 第四层:进程隔离

最严的沙箱——**把脚本跑在子进程里**。游戏主进程 fork 一个子进程,子进程加载 mod,mod 的所有 IO / syscall 都被子进程的 seccomp / pledge / AppContainer 拦截。如果 mod 崩溃,只崩子进程,主游戏不受影响。

这种方案工业里叫 "process sandbox"。Chrome 用这个隔离每个 tab(每个 tab 一个 renderer 进程)。Office 用这个隔离宏。Visual Studio Code 用这个隔离 extension。

但**游戏几乎不用**。理由:

1. IPC 开销大——子进程之间通信用 socket / pipe,延迟比 in-process Lua 调用高 1000 倍。游戏每帧调用几千次脚本,IPC 会爆。
2. 部署复杂——子进程 sandbox 在 Windows、Linux、macOS 上完全不同的 API(AppContainer / seccomp / sandbox-exec),维护成本高。
3. 对独立游戏过度——除非你是 Roblox(每天处理几百万 mod,被攻击无数次),否则进程隔离的开销不划算。

通常的工程现实:第一层(禁用危险库) + 第二层(资源限制)就够了。第三层(字节码验证)是 mlua 默认就有的,不用你做。第四层留给 Roblox 这种场景。

## 6 · 热重载脚本

脚本系统的杀手锏是热重载。设计师改一行 Lua 文件,游戏立刻看到改动。这让迭代速度从"分钟级"(重编译)变成"秒级"(改文件 + 热重载)。

热重载的实现思路:

1. **文件监听**:用 `notify` crate 监听 scripts 目录,文件改动触发回调
2. **重新加载**:在 Lua state 里 `dofile` 改动的文件,覆盖之前的定义
3. **保留状态**:hot reload 不能丢游戏进度——玩家的位置、敌人的 HP 都不能重置

第三点是工程难点。Lua state 里有大量游戏状态——全局变量、注册的事件 callback、活动的 coroutine。如果你直接 `Lua::new()` 重建一个 state,所有这些都没了。

工业方案:**Lua state 重建 + 应用层 state 重新注入**。

具体做法:

1. 游戏状态存在 Rust 里(不在 Lua 里)。Lua 只是"消费"游戏状态,不是"持有"它。
2. Lua state 重建:`drop(old_lua); let new_lua = Lua::new();`
3. 把游戏状态重新注入:`new_lua.globals().set("player", current_player)?;`
4. 重新跑所有 mod 的 init 脚本:`new_lua.load_file("mods/foo/init.lua")?;`

这套模式叫 "stateless scripting"——脚本是无状态函数,游戏状态永远在 Rust 里,Lua 只是"读 + 触发 callback"。每次热重载,Lua 从零开始,但游戏状态在 Rust 里没动,所以游戏继续跑。

具体实现:

```rust
use notify::{Watcher, RecursiveMode, Event, EventKind};
use std::sync::mpsc;
use std::time::Duration;

struct ScriptingSystem {
    lua: Lua,
    scripts_dir: PathBuf,
    game_state: GameState,  // 游戏状态在 Rust 里
}

impl ScriptingSystem {
    fn new(scripts_dir: PathBuf, game_state: GameState) -> Self {
        let lua = Lua::new();
        let mut system = Self { lua, scripts_dir, game_state };
        system.register_api();
        system.reload_all();
        system
    }

    fn register_api(&mut self) {
        // 注册所有 API
        let gs = self.game_state.clone();
        self.lua.globals().set("player_get_hp", move || {
            gs.player_hp.get()
        }).unwrap();
        // ... 更多 API
    }

    fn reload_all(&mut self) {
        // 重新加载所有脚本
        for entry in std::fs::read_dir(&self.scripts_dir).unwrap() {
            let path = entry.unwrap().path();
            if path.extension() == Some(std::ffi::OsStr::new("lua")) {
                let _ = self.lua.load_file(&path).exec();
            }
        }
    }

    fn hot_reload(&mut self) {
        // 销毁旧 Lua state,创建新的
        let old_lua = std::mem::replace(&mut self.lua, Lua::new());
        drop(old_lua);  // 显式销毁,释放内存
        self.register_api();
        self.reload_all();
    }

    fn watch_and_reload(&mut self) {
        // 启动文件监听线程
        let (tx, rx) = mpsc::channel();
        let mut watcher = notify::raw_watcher(move |res: notify::RawResult| {
            let _ = tx.send(res);
        }).unwrap();

        watcher.watch(&self.scripts_dir, RecursiveMode::Recursive).unwrap();

        // 主循环里定期检查
        std::thread::spawn(move || {
            loop {
                if rx.recv_timeout(Duration::from_millis(100)).is_ok() {
                    // 触发重载信号
                    RELOAD_REQUESTED.store(true, std::sync::atomic::Ordering::Relaxed);
                }
            }
        });
    }
}

// 主循环里
static RELOAD_REQUESTED: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

fn game_loop(scripting: &mut ScriptingSystem) {
    loop {
        if RELOAD_REQUESTED.swap(false, std::sync::atomic::Ordering::Relaxed) {
            scripting.hot_reload();
            println!("[scripting] hot reload done");
        }
        // 帧逻辑
        // ...
    }
}
```

关键洞察:**热重载的核心是"游戏状态和脚本状态分离"**。如果你把游戏状态存在 Lua 里(很多新手都这么干),热重载会丢失状态,你就没法干净地实现 hot reload。

这套"脚本无状态"原则也是 Warcraft / Factorio / Garry's Mod 等工业级 mod 系统的核心。

## 7 · Steam Workshop 集成

让玩家在自己游戏里 mod,是 90% 场景。但让玩家**分享**自己的 mod 给其他玩家,需要平台。Steam Workshop 是 PC 游戏最大的 mod 平台。

Steamworks SDK 提供 Workshop API,核心是几个操作:

- **创建 Item**:玩家点"上传 mod",游戏调 `SteamUGC()->CreateItem(app_id, k_WorkshopItemTypeCommunity)`,Steam 返回一个 published_item_id
- **更新 Item**:玩家改了 mod,调 `SteamUGC()->StartItemUpdate(app_id, item_id)`,然后 `SetItemTitle`、`SetItemContent`(指向本地 mod 目录)、`SetItemVisibility`,最后 `SubmitItemUpdate` 上传
- **订阅 Item**:玩家在 Workshop 网页点"订阅",Steam 客户端自动下载到 `<steam_install>/steamapps/workshop/content/<app_id>/<item_id>/`
- **查询订阅**:游戏启动时调 `SteamUGC()->GetNumSubscribedItems()` + `GetSubscribedItems()`,枚举所有订阅的 mod
- **加载订阅 mod**:对每个订阅的 item,获取其本地路径,加载里面的 `init.lua`

Rust 绑定用 `steamworks` crate:

```toml
[dependencies]
steamworks = "0.11"
```

集成代码骨架:

```rust
use steamworks::Client;
use std::path::PathBuf;

struct WorkshopManager {
    client: Client,
    subscribed_paths: Vec<PathBuf>,
}

impl WorkshopManager {
    fn new() -> Self {
        let (client, single) = Client::init_app(480).unwrap();  // 480 是 Spacewar 测试 app
        std::thread::spawn(move || {
            loop {
                single.run_callbacks();
                std::thread::sleep(std::time::Duration::from_millis(16));
            }
        });
        Self { client, subscribed_paths: vec![] }
    }

    fn enumerate_subscribed(&mut self) {
        let ugc = self.client.ugc();
        let num = ugc.num_subscribed_items();
        let mut paths = vec![];
        for i in 0..num {
            if let Ok(item) = ugc.subscribed_item(i) {
                if let Ok(install_info) = ugc.item_install_info(item) {
                    paths.push(install_info.folder);
                }
            }
        }
        self.subscribed_paths = paths;
    }

    fn load_mods_into_scripting(&self, scripting: &mut ScriptingSystem) {
        for path in &self.subscribed_paths {
            let init = path.join("init.lua");
            if init.exists() {
                let _ = scripting.lua.load_file(&init).exec();
            }
        }
    }
}
```

`steamworks` crate 是 Steamworks SDK 的 Rust 封装。`Client::init_app` 初始化 SDK——注意你需要 Steam app_id,这是 Steam 上你的游戏的 ID。开发期间可以用 480(Spacewar,Valve 给开发者的测试 app)。

`run_callbacks` 必须定期调——Steamworks SDK 是事件驱动的,所有异步操作(查询、上传、下载完成)通过 callback 通知。常见做法是开一个后台线程定时调。

`num_subscribed_items` 和 `subscribed_item` 枚举玩家订阅的所有 Workshop item。`item_install_info` 拿到 item 在本地的安装路径。游戏启动时枚举一次,加载所有订阅 mod 的 `init.lua`。

Workshop 上传的 API 更复杂——你要管理 item 创建、内容更新、tag 系统、可见性。这里不展开(Steam SDK 文档 30 页)。对独立游戏,通常你做一个内置 "mod 上传器":玩家点"发布我的 mod",游戏调 CreateItem + SubmitItemUpdate,Steam 网页上做审核。

## 8 · Mod API 完整设计:capability / permission / versioning

到这一步,我们有了一个能跑 Lua 的 scripting 系统,有热重载,有 Steam Workshop。但还有一个工程问题:**版本兼容性**。

游戏 0.1 版本的 mod API 有 `player.get_hp()`,0.2 你想改成 `player.hp()`(更现代的命名)。改动合理,但所有用旧 API 的 mod 会破。怎么处理?

工业级方案有三个层次。

### 8.1 Versioning:mod 声明目标游戏版本

每个 mod 在自己的 `mod.toml` 里声明:

```toml
name = "my_cool_mod"
version = "1.0.0"
api_version = "0.2"   # 这个 mod 兼容 0.2.x 的 API
author = "John Doe"
description = "Adds a glowing sword."
```

游戏启动时,枚举所有 mod,检查 `api_version`:

```rust
#[derive(serde::Deserialize)]
struct ModManifest {
    name: String,
    version: String,
    api_version: String,  // "0.2" 或 "0.2.5"
    entry: String,        // "init.lua"
}

fn load_mod(manifest_path: &Path, lua: &Lua) -> Result<(), ModError> {
    let manifest_str = std::fs::read_to_string(manifest_path)?;
    let manifest: ModManifest = toml::from_str(&manifest_str)?;
    
    // 检查 API 版本兼容性
    let game_api_version = env!("CARGO_PKG_VERSION");  // 比如 "0.2.5"
    if !is_compatible(&manifest.api_version, game_api_version) {
        return Err(ModError::IncompatibleApi {
            mod_wants: manifest.api_version,
            game_has: game_api_version.into(),
        });
    }
    
    // 加载 mod 的入口脚本
    let entry_path = manifest_path.parent().unwrap().join(&manifest.entry);
    lua.load_file(&entry_path).exec()?;
    
    Ok(())
}

fn is_compatible(mod_api: &str, game_version: &str) -> bool {
    // 简单策略:minor 版本必须匹配
    // mod_api = "0.2",game_version = "0.2.5" → 兼容
    // mod_api = "0.2",game_version = "0.3.1" → 不兼容
    let mod_minor = mod_api.split('.').take(2).collect::<Vec<_>>().join(".");
    let game_minor = game_version.split('.').take(2).collect::<Vec<_>>().join(".");
    mod_minor == game_minor
}
```

这套语义版本规则保证:patch 升级(0.2.1 → 0.2.2)兼容现有 mod;minor 升级(0.2 → 0.3)要求 mod 更新。这是温和的兼容性策略。

更激进的策略:游戏 0.3 提供一个"兼容层",把旧的 `player.get_hp()` 调用转发到新的 `player.hp()`。这种 shim 在魔兽的 Lua API 里大量存在——暴雪每次大版本都保留旧 API 标记 deprecated,几个版本之后才真删。

### 8.2 Capability:声明 mod 需要的能力

回到沙箱那一节。我们说"默认禁用所有 IO"——但有些 mod 真的需要 IO(比如一个 mod 想读取自己的配置文件)。怎么办?

工业级答案:**capability declaration**。mod 在 `mod.toml` 里声明它需要什么能力:

```toml
name = "configurable_sword"
version = "1.0.0"
api_version = "0.2"

[capabilities]
read_self = true       # 读取自己 mod 目录的文件
read_save = false      # 不需要读取存档
network = false        # 不需要联网
audio = true           # 需要播放声音
```

游戏加载 mod 时:

1. 解析 `mod.toml`,拿到 capability 声明
2. 按 capability 注册对应的 API:
   - `read_self = true` 才注册 `mod.read_file`
   - `network = true` 才注册 `http.get` / `http.post`
   - `audio = true` 才注册 `audio.play_sound`
3. 如果 mod 调用了未声明 capability 的 API,mlua 抛错(`attempt to call a nil value`)

这套"显式声明"模型让恶意 mod 难以伪装——一个声称"加发光剑"的 mod,如果声明了 `network = true`,玩家立刻知道"这玩意要联网,我不放心"。Steam Workshop 的 mod 详情页可以高亮显示 capability,让玩家 informed consent。

### 8.3 Permission:运行时询问玩家

更严的方案:某些 capability 不仅需要声明,还需要玩家**运行时同意**。比如一个 mod 第一次调 `http.post`,游戏弹窗 "mod `foo` 试图联网,允许吗?"。玩家点"允许",记住选择,以后不再问。

这种模型类似 Android 6.0+ 的权限系统或 iOS 的隐私权限。TModLoader(Terraria 的 mod 系统)就实现了类似机制。

实现上,你给每个 capability 加一个 "asked" 状态。第一次脚本调用时,如果还没 ask,游戏暂停(其实 Lua 是同步的,你 yield),弹 UI,玩家点同意/拒绝,Lua 继续。

```rust
// 注册 http.post
lua.globals().set("http_post", |url: String, body: String| -> mlua::Result<String> {
    let mod_id = current_mod_id();
    if !PERMISSIONS.with(|p| p.borrow().is_allowed(mod_id, Capability::Network)) {
        // 触发 UI 询问玩家(这里简化,实际要 yield Lua 协程)
        return Err(mlua::Error::RuntimeError("network permission not granted".into()));
    }
    // 实际发起请求
    let response = ureq::post(&url).send_string(&body).map_err(...)?;
    Ok(response.into_string()?)
})?;
```

完整的 capability + permission 系统是 WoW / Roblox / Factorio 这种工业级 mod 平台的核心。对独立游戏,通常简化版就够——只做 capability 声明,不做运行时询问。原因:运行时询问会打断游戏体验,对单人独立游戏不值得。

## 9 · 实战:Rust + mlua 给 HH 加 mod 支持

把前面所有概念综合起来,我们给 Handmade Hero 加一个完整的最小 mod 系统。

### 9.1 项目结构

```
handmade-hero/
├── Cargo.toml
├── src/
│   ├── main.rs
│   ├── game.rs           # 游戏核心逻辑
│   ├── scripting.rs      # Lua 引擎封装
│   ├── events.rs         # 事件系统
│   └── workshop.rs       # Steam Workshop 集成(可选)
└── mods/
    ├── core/
    │   ├── mod.toml
    │   └── init.lua       # 核心 mod(默认启用)
    └── example/
        ├── mod.toml
        └── init.lua       # 示例 mod
```

### 9.2 Cargo.toml

```toml
[package]
name = "handmade-hero"
version = "0.8.0"
edition = "2021"

[dependencies]
mlua = { version = "0.10", features = ["lua54", "vendored"] }
notify = "6"
serde = { version = "1", features = ["derive"] }
toml = "0.8"
parking_lot = "0.12"
crossbeam-channel = "0.5"

# 可选:Steam Workshop
steamworks = { version = "0.11", optional = true }

[features]
default = []
workshop = ["dep:steamworks"]
```

### 9.3 mod.toml 示例

`mods/example/mod.toml`:

```toml
name = "example_mod"
version = "1.0.0"
api_version = "0.8"
author = "HH Team"
description = "An example mod that doubles player damage."
entry = "init.lua"

[capabilities]
read_self = true
audio = true
network = false
```

### 9.4 events.rs:事件系统

```rust
use mlua::{Lua, Function, Value};
use parking_lot::Mutex;
use std::sync::{Arc, atomic::{AtomicU64, Ordering}};
use std::collections::HashMap;

pub type ListenerId = u64;

static NEXT_ID: AtomicU64 = AtomicU64::new(1);

// Arc 让 Lua callback 和 Rust 主循环都能持有 EventBus
#[derive(Clone)]
pub struct EventBus {
    listeners: Arc<Mutex<HashMap<String, Vec<(ListenerId, Function)>>>>,
}

impl EventBus {
    pub fn new() -> Self {
        Self { listeners: Arc::new(Mutex::new(HashMap::new())) }
    }

    pub fn on(&self, event: String, callback: Function) -> ListenerId {
        let id = NEXT_ID.fetch_add(1, Ordering::Relaxed);
        self.listeners.lock().entry(event).or_default().push((id, callback));
        id
    }

    pub fn emit(&self, lua: &Lua, event: &str, data: Value) -> mlua::Result<()> {
        let listeners = self.listeners.lock();
        if let Some(callbacks) = listeners.get(event) {
            for (_, cb) in callbacks {
                let _ = cb.call(data.clone());
            }
        }
        Ok(())
    }
}

pub struct ScriptingSystem {
    pub lua: Lua,
    pub events: EventBus,  // 现在 EventBus 是 Clone 廉价的(Arc 包裹)
    mods_dir: PathBuf,
    loaded_mods: Vec<LoadedMod>,
}
```

注意几个细节:

- `Function` 是 mlua 的 Lua 函数句柄,内部持有 Lua 引用,可以跨 Rust 调用
- `Value` 是任意 Lua 值的类型擦除(table / number / string 都行)
- 用 `parking_lot::Mutex` 因为 std::sync::Mutex 的 poisoning 在游戏场景没用
- `next_id` 用 atomic,避免 lock 内部分配 id
- emit 时 clone data(每个 callback 拿到独立的副本)

### 9.5 scripting.rs:Lua 引擎封装

```rust
use mlua::{Lua, Result as LuaResult};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use crate::events::EventBus;

static RELOAD_REQUESTED: AtomicBool = AtomicBool::new(false);

pub struct ScriptingSystem {
    pub lua: Lua,
    pub events: EventBus,
    mods_dir: PathBuf,
    loaded_mods: Vec<LoadedMod>,
}

#[derive(Debug)]
pub struct LoadedMod {
    pub name: String,
    pub version: String,
    pub api_version: String,
    pub entry_path: PathBuf,
    pub data_path: PathBuf,
}

#[derive(serde::Deserialize)]
struct ModManifest {
    name: String,
    version: String,
    api_version: String,
    entry: String,
    #[serde(default)]
    capabilities: ModCapabilities,
}

#[derive(serde::Deserialize, Default)]
struct ModCapabilities {
    #[serde(default)]
    read_self: bool,
    #[serde(default)]
    audio: bool,
    #[serde(default)]
    network: bool,
}

impl ScriptingSystem {
    pub fn new(mods_dir: PathBuf) -> Self {
        let lua = Lua::new();
        let events = EventBus::new();

        let mut system = Self {
            lua,
            events,
            mods_dir,
            loaded_mods: vec![],
        };

        system.register_global_api();
        system.load_all_mods();

        system
    }

    fn register_global_api(&mut self) {
        let globals = self.lua.globals();

        // event.on(name, callback) -> listener_id
        // Arc 共享 EventBus,Lua callback 持有一份,Rust 主循环持有一份
        let bus_for_on = self.events.clone();
        globals.set("event_on", move |name: String, cb: Function| -> mlua::Result<ListenerId> {
            Ok(bus_for_on.on(name, cb))
        })?;

        let bus_for_emit = self.events.clone();
        globals.set("event_emit", move |name: String, data: Value| -> mlua::Result<()> {
            // emit 需要当前 Lua state,但我们用全局线程局部变量传递
            // 简化:emit 在 Rust 主循环里直接调 bus.emit(lua, ...),
            // 不暴露给 Lua。Lua 用 event_on 注册 callback,Rust 触发 emit。
            let _ = (name, data);
            bus_for_emit.listeners.lock();  // 占位,Lua 一般不直接 emit
            Ok(())
        })?;

        // 给 Lua 一个 namespace table:event = { on = ..., emit = ... }
        let event_table = self.lua.create_table()?;
        event_table.set("on", globals.get::<_, Function>("event_on")?)?;
        event_table.set("emit", globals.get::<_, Function>("event_emit")?)?;
        globals.set("event", event_table)?;

        // 注册玩家 API(player_get_hp / player_set_pos 等)
        let lua_ref = &self.lua;
        globals.set("player_get_hp", || -> mlua::Result<i32> {
            // 实际从 GameState 读
            Ok(100)
        })?;
        let _ = lua_ref;
    }

    fn load_all_mods(&mut self) {
        let game_version = env!("CARGO_PKG_VERSION");
        let entries = match std::fs::read_dir(&self.mods_dir) {
            Ok(e) => e,
            Err(_) => return,
        };

        for entry in entries.flatten() {
            let path = entry.path();
            let manifest_path = path.join("mod.toml");
            if !manifest_path.exists() {
                continue;
            }

            let manifest_str = match std::fs::read_to_string(&manifest_path) {
                Ok(s) => s,
                Err(_) => continue,
            };
            let manifest: ModManifest = match toml::from_str(&manifest_str) {
                Ok(m) => m,
                Err(e) => {
                    eprintln!("[scripting] Failed to parse {}: {}", manifest_path.display(), e);
                    continue;
                }
            };

            // 版本检查
            if !Self::is_compatible(&manifest.api_version, game_version) {
                eprintln!(
                    "[scripting] Mod {} wants API {} but game has {}",
                    manifest.name, manifest.api_version, game_version
                );
                continue;
            }

            let entry_path = path.join(&manifest.entry);
            let data_path = path.clone();

            // 加载脚本
            if let Err(e) = self.lua.load_file(&entry_path).exec() {
                eprintln!(
                    "[scripting] Failed to load {}: {}",
                    entry_path.display(),
                    e
                );
                continue;
            }

            self.loaded_mods.push(LoadedMod {
                name: manifest.name,
                version: manifest.version,
                api_version: manifest.api_version,
                entry_path,
                data_path,
            });

            println!("[scripting] Loaded mod: {}", self.loaded_mods.last().unwrap().name);
        }
    }

    fn is_compatible(mod_api: &str, game_version: &str) -> bool {
        let mod_minor: Vec<&str> = mod_api.split('.').take(2).collect();
        let game_minor: Vec<&str> = game_version.split('.').take(2).collect();
        mod_minor == game_minor
    }

    pub fn request_hot_reload() {
        RELOAD_REQUESTED.store(true, Ordering::Relaxed);
    }

    pub fn maybe_reload(&mut self) {
        if RELOAD_REQUESTED.swap(false, Ordering::Relaxed) {
            println!("[scripting] Hot reload triggered");
            // 销毁旧 Lua,创建新的
            let new_lua = Lua::new();
            let _ = std::mem::replace(&mut self.lua, new_lua);
            self.register_global_api();
            self.load_all_mods();
            println!("[scripting] Hot reload complete");
        }
    }
}
```

注意几个工程细节:

- `Lua` 不是 `Clone`,也不能 send 到其他线程。所以 ScriptingSystem 必须留在主线程上。
- `register_global_api` 把所有 Rust 函数注册到 Lua globals。每个 hot reload 都要重新注册——因为新 Lua state 什么都没有。
- `load_all_mods` 遍历 mods 目录,读每个 `mod.toml`,做版本检查,加载入口脚本。失败的 mod 不影响其他 mod。
- `maybe_reload` 在主循环里每帧调一次,检查 reload 标志。

### 9.6 文件监听

```rust
use notify::{Watcher, RecursiveMode, EventKind};

pub fn start_watcher(scripts_dir: &Path) -> notify::Result<()> {
    let (tx, rx) = std::sync::mpsc::channel();
    let mut watcher = notify::recommended_watcher(move |res: notify::Result<notify::Event>| {
        if let Ok(event) = res {
            let _ = tx.send(event);
        }
    })?;

    watcher.watch(scripts_dir, RecursiveMode::Recursive)?;

    std::thread::spawn(move || {
        while let Ok(event) = rx.recv() {
            if matches!(
                event.kind,
                EventKind::Create(_) | EventKind::Modify(_) | EventKind::Remove(_)
            ) {
                // 检查是不是 .lua 文件
                let is_lua = event.paths.iter().any(|p| {
                    p.extension() == Some(std::ffi::OsStr::new("lua"))
                });
                if is_lua {
                    ScriptingSystem::request_hot_reload();
                }
            }
        }
    });

    Ok(())
}
```

notify 是 Rust 生态最成熟的文件监听库,在 Linux 用 inotify、macOS 用 FSEvents、Windows 用 ReadDirectoryChangesW。一套 API 三个平台。

我们只关心 `.lua` 文件改动。一旦检测到,设置全局 reload 标志。主循环里 ScriptingSystem 会看到这个标志,触发 hot reload。

### 9.7 main.rs:整合

```rust
mod scripting;
mod events;

use scripting::ScriptingSystem;
use std::path::PathBuf;

fn main() {
    let mods_dir = PathBuf::from("mods");

    // 启动文件监听
    let _ = scripting::start_watcher(&mods_dir);

    // 创建脚本系统
    let mut scripting = ScriptingSystem::new(mods_dir);

    println!("Game started. Press F5 to reload mods.");

    // 主循环(简化)
    let mut frame = 0u64;
    loop {
        // 检查热重载
        scripting.maybe_reload();

        // 游戏更新 + 渲染
        game_update(&mut scripting, frame);
        game_render(frame);

        frame += 1;
        if frame > 1000 {
            break;
        }
    }
}

fn game_update(scripting: &mut ScriptingSystem, frame: u64) {
    // 模拟游戏逻辑
    if frame % 60 == 0 {
        // 每 60 帧触发一个事件
        let lua = &scripting.lua;
        let data = lua.create_table().unwrap();
        data.set("frame", frame).unwrap();
        let _ = scripting.events.emit(lua, "tick", mlua::Value::Table(data));
    }
}

fn game_render(_frame: u64) {
    // 渲染逻辑
}
```

### 9.8 示例 mod

`mods/example/init.lua`:

```lua
-- 监听 tick 事件
event.on("tick", function(data)
    if data.frame % 600 == 0 then
        print("[example_mod] 10 seconds passed")
    end
end)

-- mod 加载时
print("[example_mod] loaded!")
```

跑起来你应该看到:

```
[scripting] Loaded mod: core
[scripting] Loaded mod: example
[example_mod] loaded!
Game started. Press F5 to reload mods.
[example_mod] 10 seconds passed
[example_mod] 10 seconds passed
```

现在改 `mods/example/init.lua`,把打印内容改成 `"[example_mod] tick!"`,保存。控制台立刻看到:

```
[scripting] Hot reload triggered
[scripting] Loaded mod: core
[scripting] Loaded mod: example
[example_mod] loaded!
[example_mod] tick!
```

这就是热重载。设计师改一行,1 秒看到效果。**这就是 scripting 系统的杀手锏**。

## 10 · 检查清单

一个完整的 scripting & modding 系统需要做这些事。Checklist:

- [ ] 选定脚本语言(Lua / Rune / Wasm / ...)
- [ ] 选定 Rust 绑定(mlua / rune / wasmtime / ...)
- [ ] Cargo.toml 配置(`vendored` / 选定 Lua 后端)
- [ ] 创建 Lua state
- [ ] 设计 API(几个 namespace,每个 N 个函数)
- [ ] 注册 API 到 Lua globals
- [ ] 暴露游戏对象(UserData trait)
- [ ] 实现事件系统(`event.on` / `event.emit`)
- [ ] 沙箱化(禁用 os / io / debug / package)
- [ ] Instruction count hook(防死循环)
- [ ] Mod manifest(mod.toml + version 检查)
- [ ] Capability 系统(mod 声明需要的能力)
- [ ] 文件监听 + 热重载
- [ ] 游戏状态在 Rust 里,不在 Lua 里
- [ ] 错误处理(mod 报错不崩溃游戏)
- [ ] 日志(每个 mod 的输出标记 mod 名)
- [ ] Steam Workshop 集成(可选,通过 steamworks crate)
- [ ] Mod 加载顺序(依赖关系)
- [ ] Mod 配置保存(玩家偏好)
- [ ] 文档(API reference,新手教程)

一个 1 人独立游戏能搞定前 15 条,加上 19 条文档。Steam Workshop 集成和 mod 加载顺序是大项目才做。

## 11 · 延伸阅读

外部稳定 URL(可选):

- Lua 5.4 Reference Manual: https://www.lua.org/manual/5.4/
- mlua crate 文档: https://docs.rs/mlua/
- Programming in Lua(Roberto Ierusalimschy 的书,第四版,讲 Lua 5.3 但原理通用): https://www.lua.org/pil/
- LuaJIT 文档(Mike Pall 的工程奇迹): http://luajit.org/
- Luau(Roblox 的 Lua 衍生): https://luau.org/
- Rune crate: https://rune-rs.github.io/
- WASI Capabilities(WebAssembly 沙箱模型): https://wasi.dev/
- Steam Workshop API(Steamworks SDK): https://partner.steamgames.com/doc/features/workshop
- Casey 手写 HH 系列(脚本是从 Day 470+ 开始讨论的): https://guide.handmadehero.org/code/

真实开源参考:

- Factorio 的 Lua mod API 文档(工业级 Lua 集成的范本): https://lua-api.factorio.com/latest/
- WoW UI Lua API 文档(3000+ 函数的 API surface 案例): https://warcraft.wiki.gg/wiki/World_of_Warcraft_API
- Garry's Mod Lua Wiki(社区 modding 经典): https://wiki.facepunch.com/gmod/
- TModLoader(Terraria mod 系统的 capability / permission 设计): https://github.com/tModLoader/tModLoader
- Bevy 的 scripting 探索(bevy_mod_scripting,Rust 生态最前沿的尝试): https://github.com/makspll/bevy_mod_scripting

这份深入覆盖了从历史到工业实践、从 API 设计到沙箱、从热重载到 Steam Workshop 的全链路。把代码片段贴起来跑一遍,你就能给 Handmade Hero 加一套工作的 mod 系统。
