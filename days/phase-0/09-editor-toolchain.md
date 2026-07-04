
# 09 · 编辑器与工具链:helix/nvim + rust-analyzer + cargo-watch + tmux

> 写代码不是"打开记事本敲字"。专业开发者用一整套工具链——编辑器、语言服务器、构建系统、文件监视器、终端复用器——它们之间无缝配合,让你敲 `carago` 时编辑器立刻提示"拼错了",保存文件时立刻自动重编译,改代码时编译器错位还能看到错。这一篇把这些工具逐个讲透。

## 0 · 为什么要有这一天

你已经会写一个 `main.rs`,用 `cargo run` 跑起来。但试试做下面任何一件事,你会发现"光会 cargo 不够":

1. **你想知道 `Vec` 有什么方法**——不开浏览器查文档,光在编辑器里 hover 一下就能看签名
2. **你拼错了 `arrya`**——保存的那一刻编辑器立刻画红波浪线,而不是等到 `cargo build` 报错才知道
3. **你 import 了一个没用过的 `use std::collections::HashMap;`**——编辑器自动把它标灰,提醒你删
4. **你想看一个函数被谁调用**——右键"Find references",3 秒找到所有调用点
5. **你改了一行代码,5 秒后画面里游戏就变了**——不需要手动 `cargo run`,文件保存就触发
6. **你的 SSH 断了,后台编译全死**——你需要 `tmux` 让会话不依赖 SSH 连接
7. **你要同时看代码、看 build 输出、看游戏窗口**——开三个终端窗口?用 `tmux` 一个窗口切三块

这些工具的集合叫做 **developer toolchain**。学不会它,你后面的 667 天每天都会被低效拖累。学会它,你写代码的速度能快 10 倍。

**心理锚点**:这一篇读完,你能:
- 装好 helix(或 nvim)+ rust-analyzer,看到 Rust 代码补全、跳转、hover、诊断
- 用 cargo-watch 在文件改动时自动 build/test
- 用 tmux 在一个终端窗口里切多个面板
- 在 SSH 断线后,会话能恢复继续
- 知道 LSP(Language Server Protocol)是什么,为什么所有现代编辑器都用它

## 1 · 概念地图:编辑器、IDE、LSP、构建系统

| 词 | 是什么 | 类比 |
|---|---|---|
| **编辑器(Editor)** | 写文本的程序(helix、nvim、emacs、VS Code) | 笔和纸 |
| **IDE(Integrated Dev Env)** | 编辑器 + 编译器 + 调试器 + GUI 工具(VS Code、IntelliJ、CLion) | 一整套画室 |
| **LSP(Language Server Protocol)** | 编辑器和"语言理解服务"之间的通信协议(微软 2016 提出) | 笔和画师之间的对话规范 |
| **Language Server** | 理解某语言、提供补全/跳转/诊断的程序(rust-analyzer 是 Rust 的 LSP server) | 真正懂画的人 |
| **构建系统(Build System)** | 把源码变成可执行文件(我们的:`cargo` + `rustc`) | 印刷机 |
| **文件监视器(File Watcher)** | 文件一变就触发命令(`cargo-watch`、`entr`) | 监工 |

**关键洞察**:IDE 集成一切,但臃肿;编辑器轻量,但本身不懂语言。**LSP 是这个矛盾的解决方案**——把"语言理解"抽出来变成独立进程(language server),编辑器只负责 UI 和发请求。这样 helix、nvim、VS Code、emacs 都能用同一个 rust-analyzer。

## 2 · 心智模型

### 类比:LSP 是"前台 + 后端"的客服中心

想象一个客服中心:

- **前台**(编辑器:helix/nvim/VS Code)负责接待用户(你的键盘输入),把问题转给后端
- **后端**(language server:rust-analyzer)真正懂业务,处理问题,返回答案
- **协议**(LSP)规定前台和后端怎么通信——`textDocument/hover` 表示"用户想知道这个符号是什么",`textDocument/completion` 表示"用户想要补全建议"

前台和后端可以是不同公司、不同语言写的。一个 rust-analyzer 后端可以同时被 50 种编辑器使用,这就是 LSP 的威力。

### LSP 的常见请求

| 请求 | 含义 | 触发 |
|---|---|---|
| `textDocument/didOpen` | 用户打开了一个文件 | 编辑器自动发 |
| `textDocument/didChange` | 文件内容变了(每键一下) | 编辑器自动发 |
| `textDocument/hover` | 鼠标停在符号上,看类型/文档 | 鼠标 hover 或快捷键 |
| `textDocument/completion` | 给我补全建议 | 输入 `.` 或快捷键 |
| `textDocument/definition` | 跳转到定义 | Ctrl+Click 或 gd |
| `textDocument/references` | 找所有引用 | 右键 "Find references" |
| `textDocument/diagnostic` | 这段代码有什么错(编译错误、warning) | 实时(编辑器主动 publish) |
| `textDocument/formatting` | 帮我格式化代码 | 保存或快捷键 |
| `textDocument/rename` | 重命名符号(整个项目) | F2 |
| `textDocument/codeAction` | 提供修复建议(如 "import std::Vec") | 光标在错误上时 |

LSP server 收到请求后,可能跑很多工作:rust-analyzer 真的会**增量编译**你的代码,所以它能秒级给出诊断。

### 编译系统的层次

```
你的源码 main.rs
      │
      ▼
   rustc (编译器,把 .rs 变成 .rlib / 可执行文件)
      │
      ▼
   cargo (包管理 + 构建协调,调用 rustc)
      │
      ▼
   rustup (rustc / cargo 的版本管理器)
      │
      ▼
   你的 Linux 系统
```

- `rustc` 真正的编译器,几乎不直接用
- `cargo` 是 Rust 的"包管理 + 构建工具 + 测试 runner + 文档生成器",你日常 99% 时间用它
- `rustup` 管多个 Rust 工具链版本(stable、beta、nightly),你换工具链时用它

`cargo-watch` 是 cargo 的扩展(`cargo install cargo-watch`),它监视文件,一变就跑你给的 cargo 命令。

## 3 · 四域深入

### 3.1 · 🐧 Linux 系统编程视角

编辑器和 LSP server 在 Linux 上是两个进程,通过 JSON-RPC over stdio 通信。具体来说:

1. 编辑器 spawn 一个 LSP server 子进程(`rust-analyzer`)
2. 编辑器把 JSON-RPC 消息写到 server 的 stdin
3. server 把回复写到 stdout
4. server 也能主动 push 消息(diagnostic)到编辑器

回忆 [08 进程与信号](08-processes-and-signals.md):这正是 fork + exec + pipe 的组合。LSP 协议本身和系统编程无关,但**实现**完全靠 Unix IPC。

```bash
# 实际验证 LSP 是 stdio 通信
echo '{"jsonrpc":"2.0","method":"initialize","id":1,"params":{...}}' | rust-analyzer
# rust-analyzer 会从 stdin 读 JSON,处理后回 JSON 到 stdout
```

实际编辑器不会让你手动发——它内部包好了,你只看 UI。

### 3.2 · 🦀 Rust 生态视角

#### rust-analyzer

rust-analyzer(简称 rA)是 Rust 官方维护的 LSP server,GitHub: https://github.com/rust-lang/rust-analyzer

特点:
- 比 rustc 自带的 "save-analysis" 快 10 倍以上(增量编译,缓存好)
- 支持 hover、补全、跳转、重命名、提取函数、内联变量……
- 持续集成进 rustc 团队,长期和 rustc 合并

装它:
```bash
sudo pacman -S rust-analyzer
# 或用 rustup:
rustup component add rust-analyzer
```

验证:
```bash
rust-analyzer --version
# rust-analyzer 0.4.x (XXXX-XX-XX)
```

#### cargo-watch

文件一变就跑命令。装:
```bash
cargo install cargo-watch
# 或 pacman:
sudo pacman -S cargo-watch
```

用:
```bash
cargo watch -x run       # 文件变 → cargo run
cargo watch -x test      # 文件变 → cargo test
cargo watch -x "build --release"   # 自定义命令
cargo watch -w src -x check        # 只监视 src/ 目录,跑 cargo check
```

#### 其他常用 cargo 扩展

```bash
cargo install cargo-edit       # cargo add / cargo rm 管理依赖
cargo install cargo-flamegraph # 生成火焰图(性能)
cargo install cargo-bench      # 跑基准
cargo install cargo-outdated   # 看哪些依赖过时了
cargo install cargo-audit      # 安全漏洞扫描
cargo install cargo-udeps      # 找未使用的依赖
cargo install cargo-nextest    # 更快的 test runner
cargo install cargo-expand     # 看宏展开后的代码
cargo install cargo-modules    # 看 crate 结构
```

每个 install 会从源码编译,第一次慢;装好后是单文件二进制,放 `~/.cargo/bin/`。

#### rustup

```bash
# 看当前工具链
rustup show
# 输出:active toolchain: stable-x86_64-unknown-linux-gnu (default)

# 装 nightly
rustup toolchain install nightly

# 给某项目指定 nightly
cd my-project
rustup override set nightly

# 装/卸 component
rustup component add rust-src       # 给 rust-analyzer 用
rustup component add clippy         # linter
rustup component add rustfmt        # formatter

# 更新所有工具链
rustup update
```

### 3.3 · 编辑器选择:helix vs nvim

教程推荐两个选项:

#### 选项 A:Helix(推荐新手)

Helix 是用 Rust 写的现代终端编辑器,内置 LSP(不用装插件),开箱即用。

```bash
sudo pacman -S helix
# 启动
hx my-file.rs
```

Helix 内置对 Rust 的支持,不需要任何配置就能:
- 补全(输 `.`,触发)
- 跳转定义(`gd`)
- hover(`Space + k`)
- 诊断(实时显示编译错误)
- 重命名(`Space + r`)
- 格式化(`Space + f`)

**Helix 选择原则(selection-first)**:先选一段(像鼠标拖),再对它做事。和你之前在 vim 里"光标移动 → 命令"不同。

基本键位(`hx` 启动后,按 `?` 看完整 cheatsheet):

```
移动:    h j k l (左下上右), w b (word 前后), gg G (首尾)
选择:    v 进入可视模式(配合移动)
搜索:    / 关键词
粘贴:    p
撤销:    u
重做:    U
命令菜单: :
文件树:   Space + f (file picker)
全局搜索: Space + /
跳转定义: gd
查找引用: Space + s (grep 当前文件), 或 g r (references)
保存:    :w
退出:    :q, :wq, :q!
分屏:    Space + w v (vertical split), Space + w s (horizontal)
切分屏:   Space + w h/j/k/l
```

第一次用建议跑 `:tutor`(Helix 自带 30 分钟交互教程)。

#### 选项 B:Neovim(想高度定制的人)

Neovim(nvim)是 vim 的现代化分支,生态更丰富但要自己配置。

```bash
sudo pacman -S neovim
```

最小配置(`~/.config/nvim/init.lua`):

```lua
-- 1. 设 leader 键为空格
vim.g.mapleader = " "

-- 2. 装 lazy.nvim(包管理器)
local lazypath = vim.fn.stdpath("data") .. "/lazy/lazy.nvim"
if not vim.loop.fs_stat(lazypath) then
  vim.fn.system({
    "git", "clone", "--filter=blob:none",
    "https://github.com/folke/lazy.nvim.git", "--branch=stable", lazypath,
  })
end
vim.opt.rtp:prepend(lazypath)

-- 3. 装 rustaceanvim(Rust 一站式插件)
require("lazy").setup({
  {
    "mrcjkb/rustaceanvim",
    version = "^4",
    lazy = false,
    init = function()
      vim.g.rustaceanvim = {
        server = {
          cmd = function()
            local mason = require("mason-registry")
            local ra = mason.get_package("rust-analyzer")
            return { ra:get_install_path() .. "/rust-analyzer" }
          end,
        },
      }
    end,
  },
  { "williamboman/mason.nvim", config = true },
  { "williamboman/mason.nvim", build = ":MasonInstall rust-analyzer" },
})
```

太复杂?**新手强烈建议先用 Helix**。nvim 的配置 rabbit hole 至少 10 小时,Helix 是 10 分钟。

#### tmux:终端里的多面板

tmux 让你在一个终端里开多个 panel,SSH 断开会话不丢。

```bash
sudo pacman -S tmux
```

基本用法:

```
开始会话:        tmux new -s work
离开(保留运行):   Ctrl+B 然后 D
回到会话:        tmux attach -t work
列会话:          tmux ls
杀死会话:        tmux kill-session -t work

会话内键位(prefix 都是 Ctrl+B):
水平分屏:        Ctrl+B 然后 "
垂直分屏:        Ctrl+B 然后 %
切 panel:        Ctrl+B 然后 hjkl(或方向键)
新窗口(类似 tab):  Ctrl+B 然后 c
切窗口:          Ctrl+B 然后 数字(0-9)
滚动模式:        Ctrl+B 然后 [ (q 退出)
```

实战推荐的工作流:左边 helix 编辑,右下 `cargo watch -x run`,右上 `htop` 看资源。

### 3.4 · 🎮 游戏编程视角

游戏开发的工具链诉求:

1. **热重载**:改代码不重启游戏,这是 Casey HH 的核心卖点。Rust 也能做:`cargo-watch` 配合 `libloading` 动态加载 .so,改代码后 watch 触发编译,游戏检测到新 .so 就 dlopen。
2. **资产监视**:改贴图立刻看效果。HH Day 500+ 实现了资产热加载,Linux 上对应 inotify + 后台线程。
3. **profiling**:运行时看性能数据。`cargo-flamegraph` + `perf`,后面 [13-diagnosis-tools.md](13-diagnosis-tools.md) 详讲。
4. **调试**:游戏卡住时 attach gdb。生产配置:`cargo build` 出 debug binary,game panic 时 gdb 自动 attach,看 backtrace。

## 4 · 认知地图

### 4.1 上级

- **Developer Experience (DX)** — 工具链、文档、社区的总和,决定你写代码多爽
- **Tooling as a Code Skill** — 熟练工具链是"程序员"和"专业开发者"的分水岭
- **LSP** — 微软 2016 年提出的协议,VS Code 用,已变成行业标准

### 4.2 同级

| 工具 | 关键差别 | 何时用 | 本项目选 |
|---|---|---|---|
| Helix | 内置 LSP,无配置 | 新手 / 想开箱即用 | ✅ 推荐 |
| Neovim | 生态丰富,可深度定制 | 想搭一套属于自己的 IDE | 备选 |
| VS Code | GUI,生态最丰富 | 不想用终端编辑器 | 不推荐(终端党) |
| Zed | Rust 写的极快 GUI 编辑器,内置 LSP | 喜欢 GUI 又快 | 可选 |
| emacs + lsp-mode | 老牌可扩展 | emacs 老用户 | 不推荐 |

| 包管理 | 关键差别 | 何时用 |
|---|---|---|
| rustup | 工具链版本管理 | 装工具链本身 |
| cargo | Rust 项目级 | 装依赖 / build / test |
| pacman | 系统级 | 装 OS 软件 |
| cargo install | 用户级 binary | 装工具(cargo-watch 等) |

### 4.3 下级

- **rust-analyzer** — Rust LSP server
- **cargo** — 构建/包管理
- **rustup** — 工具链版本管理
- **cargo-watch** — 文件监视 + 自动 build
- **tmux** — 终端复用
- **inotify** (Linux 内核) — 文件变更通知机制

## 5 · 对照与变奏

### GUI 编辑器 vs 终端编辑器

| | GUI(VS Code、Zed、CLion) | 终端(helix、nvim) |
|---|---|---|
| 启动 | 慢(几百 ms - 几秒) | 快(< 50ms) |
| 远程 SSH | 难(需要 X forwarding 或浏览器版) | 原生 |
| 鼠标依赖 | 高 | 低(几乎纯键盘) |
| 学习曲线 | 平(所见即所得) | 陡(键位多) |
| 内存占用 | 大(几百 MB - GB) | 小(几十 MB) |
| 自动化 / 脚本 | 难(各编辑器私有 API) | 易(脚本友好) |

**推荐**:学习阶段用终端(helix)——磨炼键盘肌肉记忆,远程开发零摩擦。后期大型项目可以用 GUI(IDE 自动化强)。

### LSP 之前的世界

- **1990s-2010s**:每个 IDE 自己解析每种语言。IntelliJ 写一份 Java 解析器,Eclipse 写一份,VS Code 写一份。每加一种语言 × 每个编辑器 = N × M 工作。
- **2016 LSP 出现**:每语言写 1 个 LSP server,所有支持 LSP 的编辑器都能用。变成 N + M 工作。
- **2020s**:LSP 几乎变成事实标准。新版 IDE 都支持。LSP 之外还有 DAP(Debug Adapter Protocol)、Tree-sitter(语法解析),思想类似。

### 文件监视:inotify vs FSEvents vs ReadDirectoryChangesW

| OS | 内核 API |
|---|---|
| Linux | inotify(每目录一个 fd,触发事件) |
| macOS | FSEvents(系统级流,延迟到 1s) |
| Windows | ReadDirectoryChangesW(每目录 IOCP) |

Rust 跨平台库:`notify` crate 统一三套 API。`cargo-watch` 用 notify 实现。

## 6 · 关联 Day

- **铺垫**:[00-terminal-basics.md](00-terminal-basics.md)(vim 基础)、[01-arch-setup.md](01-arch-setup.md)(pacman)
- **当天**:本篇
- **后续**:
  - [10-package-management.md](10-package-management.md)(深入 pacman / cargo / rustup / AUR)
  - [11-reading-rustc-errors.md](11-reading-rustc-errors.md)(看 rustc 报错)
  - Phase 1 Day 001(项目初始化,你会在 helix 里写第一行 Rust)
  - Phase 4 Day 112+(热重载,用 cargo-watch + libloading)

## 7 · 变式训练

### Lv1 · 概念辨析

**题**:为什么 LSP 不让编辑器自己实现语言理解?换句话说,把"理解 Rust"内置到 helix 里,有什么坏处?

**参考解答**:
1. **N × M 问题**:M 个语言 × N 个编辑器 = MN 套实现。LSP 拆开:每语言 1 套 server,每编辑器 1 套 client,共 M+N 套。语言越多越值。
2. **重复工作**:rust-analyzer 是几百人年的工程(rustc 团队自己维护),不可能 helix、nvim、VS Code 各自实现一遍。
3. **解耦**:语言和编辑器可以独立演化。rust-analyzer 升级,所有编辑器受益,不用等编辑器发版。
4. **进程隔离**:language server 崩了不会拖死编辑器——可以重启它。

### Lv2 · 动手实践

**题**:完成以下任务,每步截图/记录命令:

1. 装 helix、rust-analyzer、tmux、cargo-watch
2. 用 `cargo new editor-test` 创建一个新项目
3. 进项目目录,用 helix 打开 `src/main.rs`
4. 在 helix 里输入 `let v = Vec::<i32>::new(); v.push(1); v.push("str");`
5. **验证**:helix 应该立刻在 `v.push("str");` 上画红线(hover 看错误)
6. 改成 `v.push(2);`,保存,红线消失
7. 在另一终端 `cd` 到项目,跑 `cargo watch -x check`
8. 故意改错(加个错语法),cargo-watch 应该立刻报错
9. 开 tmux,在一个 window 里分 3 个 panel:helix / cargo-watch / htop
10. 离开 tmux(Ctrl+B D),再 attach 回去,所有还在

完成标准:每步都能复述你看到了什么。

**参考解答**:命令清单(每条都跑了再看效果):

```bash
# 1. 装工具
sudo pacman -S helix rust-analyzer tmux
cargo install cargo-watch   # 或 sudo pacman -S cargo-watch

# 2. 创建项目
cargo new editor-test
cd editor-test

# 3. 用 helix 打开
hx src/main.rs

# 4-6. 在 helix 里改代码,看红线变化

# 7. cargo watch
cargo watch -x check

# 9. tmux 工作流
tmux new -s dev
# 在里面分屏(Ctrl+B "),开 helix
# 切另一个 panel(Ctrl+B 方向键),跑 cargo watch
# 再开一个 panel,跑 htop

# 10. 离开
# Ctrl+B 然后 D
tmux ls
tmux attach -t dev
```

### Lv3 · 迁移设计

**题**:你被分配到一个**Python 项目**,想用 helix 看 Python 代码补全。你需要装什么?helix 怎么知道用哪个 language server?

**提示**:
- helix 内置一份"language ID → 默认 language server"映射
- Python 默认 LSP 是 `pylsp`(社区)或 `pyright`(微软)
- 装:`sudo pacman -S python-pylsp` 或 `pip install python-lsp-server`
- 在 helix 里看 `:config` 打开 `languages.toml`,看 Python 怎么配置

写出完整步骤,从 `sudo pacman` 开始。

### Lv4 · 开源贡献

**题**:helix 是 Rust 写的现代编辑器,GitHub: https://github.com/helix-editor/helix

1. clone 它,看 `languages.toml` 里 Rust 的配置(注释 / LSP 选项)
2. 找一个 helix 还**没**内置 language server 配置的小众语言(比如 COBOL、Fortran 之类)
3. **可能的贡献**:给它加一份 language 配置(`languages.toml` 加 entry + `runtime/queries/<lang>/` 加 tree-sitter 语法文件)
4. 或者更小:helix 的 doc 里某个 keybinding 没说清,你补一句
5. 写 PR 描述

**示例**:`languages.toml` 加一种新语言,基本结构:

```toml
[[language]]
name = "my-lang"
scope = "source.my"
file-types = ["my"]
comment-token = "#"
indent = { tab-width = 4, unit = "    " }
```

## 8 · Rust / Arch 落地代码

### 完整配置文件

#### ~/.config/helix/config.toml(helix 主配置)

```toml
# 主题(可选:helix 内置很多)
theme = "gruvbox"

# 编辑器选项
[editor]
line-number = "relative"      # 相对行号(方便 hjkl 移动)
mouse = false                 # 关鼠标,纯键盘
idle-timeout = 50             # 50ms 不动就触发 completion
auto-completion = true
auto-format = true
true-color = true

[editor.statusline]
left = ["mode", "spinner", "file-name", "file-modification-indicator"]
right = ["diagnostics", "selections", "position", "file-encoding", "file-type"]

[editor.lsp]
display-messages = true       # 显示 LSP 启动消息
display-inlay-hints = true    # 显示类型提示(inlay hints)

# 按键映射(可选,改默认快捷键)
[keys.normal]
"C-s" = ":w"                  # Ctrl+S 保存
```

#### ~/.config/helix/languages.toml(Rust 专属配置)

```toml
[[language]]
name = "rust"

[language-server.rust-analyzer]
config = {
    checkOnSave = { command = "clippy", extraArgs = ["--", "-W", "clippy::pedantic"] },
    cargo = { features = "all" },
    procMacro = { enable = true },
    diagnostics = { enable = true, experimental = { enable = true } },
}
```

**配置解释**:
- `checkOnSave.command = "clippy"` — 保存时用 clippy 跑检查(比 cargo check 更严)
- `cargo.features = "all"` — 启用所有 cargo feature
- `procMacro.enable = true` — 启用过程宏(很多 crate 依赖,如 serde)
- `diagnostics.experimental.enable = true` — 启用实验性诊断(更细致)

#### ~/.tmux.conf(tmux 配置)

```bash
# 用 Ctrl+A 替代 Ctrl+B(Ctrl+B 太远)
unbind C-b
set -g prefix C-a
bind C-a send-prefix

# 256 色 + true color
set -g default-terminal "tmux-256color"
set -ag terminal-overrides ",xterm-256color:RGB"

# 鼠标支持(滚轮滚 panel)
set -g mouse on

# 分屏键位更直觉(| 垂直,- 水平)
bind | split-window -h -c "#{pane_current_path}"
bind - split-window -v -c "#{pane_current_path}"

# 切 panel 用 hjkl
bind h select-pane -L
bind j select-pane -D
bind k select-pane -U
bind l select-pane -R

# 新窗口保持当前路径
bind c new-window -c "#{pane_current_path}"

# 从 1 开始编号(0 太远)
set -g base-index 1
setw -g pane-base-index 1

# 重载配置快捷键
bind r source-file ~/.tmux.conf \; display "Config reloaded"
```

改完跑 `tmux source ~/.tmux.conf`。

### 一键脚本:全新 Arch 装好整套

```bash
#!/bin/bash
# setup-dev-env.sh

set -e

# 1. 系统 Rust 工具链
sudo pacman -S --needed rustup base-devel

# 2. 装 stable + nightly
rustup default stable
rustup toolchain install nightly
rustup component add rust-src clippy rustfmt rust-analyzer

# 3. 装 cargo 扩展(从源码编译,可能要几分钟)
cargo install cargo-watch cargo-edit cargo-flamegraph cargo-nextest cargo-outdated

# 4. 编辑器 + 终端工具
sudo pacman -S --needed helix tmux ripgrep fd fzf bat

# 5. 创建配置目录
mkdir -p ~/.config/helix ~/.config/nvim

# 6. 验证
echo "--- Versions ---"
rustc --version
cargo --version
rust-analyzer --version
hx --version
tmux -V
cargo watch --version
echo "--- All good ---"
```

跑法:
```bash
chmod +x setup-dev-env.sh
./setup-dev-env.sh
```

### Troubleshooting

- **helix 不显示补全**:检查 `rust-analyzer --version` 是否能跑;helix 默认 PATH 找不到 rust-analyzer 时,用绝对路径在 `languages.toml` 配 `language-server.rust-analyzer.command`
- **rust-analyzer 卡在 "Indexing..."**:大项目首次索引慢(几分钟),耐心等。第二次启动会快(有缓存)
- **cargo-watch 不触发**:可能文件在 docker volume / NFS,inotify 不工作。tmux 网络文件系统挂载时 inotify 默认不工作
- **tmux 鼠标滚屏选中文本复制不到系统剪贴板**:tmux 接管了鼠标。按住 Shift 再选,会用终端原生选择;或在 `~/.tmux.conf` 加 `set -g mouse off`

## 9 · 延伸阅读(可选补充,非必需)

本仓库本地:
- [00-terminal-basics.md](00-terminal-basics.md) — vim 基础(本篇 helix 部分需要那些基础)
- [10-package-management.md](10-package-management.md) — 包管理深入
- [13-diagnosis-tools.md](13-diagnosis-tools.md) — perf / valgrind / flamegraph

外部稳定 URL:
- Helix 官方文档:https://docs.helix-editor.com/
- rust-analyzer 手册:https://rust-analyzer.github.io/manual.html
- LSP 规范:https://microsoft.github.io/language-server-protocol/
- tmux 入门(Tao of tmux):https://leanpub.com/the-tao-of-tmux/read

真实开源源码:
- rust-analyzer:https://github.com/rust-lang/rust-analyzer
- helix:https://github.com/helix-editor/helix
- cargo-watch:https://github.com/watchexec/cargo-watch
