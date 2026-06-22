---
article: 10
phase: 0
title: "包管理:pacman / cargo / rustup / AUR / asdf"
type: setup
difficulty: 2
duration: "2h"
domains: [linux, rust]
prereqs: ["00-terminal-basics", "01-arch-setup", "09-editor-toolchain"]
---

# 10 · 包管理:pacman / cargo / rustup / AUR / asdf

> 你想装一个软件——可能是个游戏引擎,一个 Rust 库,一个特定版本的 Python,或者一个 Arch 官方仓库里没有的小工具。每个来源都有自己的"包管理器":pacman 管系统,cargo 管 Rust 项目,rustup 管 Rust 工具链,AUR 管非官方,asdf 管多语言版本。这一篇把这些工具彻底梳理清楚,让你知道遇到任何软件该用哪个工具装。

## 0 · 为什么要有这一天

新手最常陷入的混乱:

1. **"装 Rust 怎么又有 pacman 又有 rustup 又有 rustc?"** —— 谁是谁,装哪个?
2. **"我想用 glam 这个 crate,但 `pacman -S glam` 找不到"** —— 因为 glam 是 Rust 项目依赖,不是系统包
3. **"我想装最新版 bun,但 pacman 的版本旧"** —— AUR 救命
4. **"项目 A 要 Python 3.10,项目 B 要 3.12,怎么并存?"** —— 多版本管理
5. **"我装了一堆东西,现在系统乱了,怎么清理?"** —— 包管理的反操作

这些问题的根源:**Linux 上有多个层级的"软件"**,每个层级有自己的包管理器。搞清楚层级,一切就清。

**心理锚点**:这一篇读完,你能:
- 看到一个软件需求,立刻知道用 pacman / cargo / rustup / AUR / asdf 哪个装
- 理解为什么 Rust 项目用 `cargo add`,不直接装系统库
- 装一个 AUR 软件并升级
- 用 asdf 在一个系统上跑多版本 Python/Node/Rust 并存
- 看懂 `Cargo.toml` / `Cargo.lock`,知道版本号怎么管

## 1 · 概念地图:四个层级的包

```
┌──────────────────────────────────────────────────┐
│ 系统级(Arch 官方 + AUR)                          │
│   pacman (官方仓库) / AUR helpers (社区仓库)     │
│   装的是 OS 级软件:浏览器、编辑器、Rust 工具链    │
└──────────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────┐
│ 语言工具链级                                      │
│   rustup (Rust), pyenv (Python), nvm (Node)     │
│   asdf 统一管理多语言多版本                       │
│   装的是某语言的"编译器/解释器本身"               │
└──────────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────┐
│ 语言生态级                                        │
│   cargo (Rust), pip (Python), npm (Node)        │
│   装的是某语言项目的依赖(库 / crate)             │
└──────────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────┐
│ 用户级 binary                                      │
│   cargo install (Rust tools), go install         │
│   装的是命令行小工具(系统包没收录的)              │
└──────────────────────────────────────────────────┘
```

**关键区分**:
- 你装 `helix`(系统级编辑器):用 pacman
- 你装 `rustc` 本身:用 rustup(pacman 也行但 rustup 更灵活)
- 你装 `glam`(Rust 项目依赖):用 `cargo add glam`(进 Cargo.toml)
- 你装 `cargo-watch`(命令行工具):用 `cargo install cargo-watch`(全局 binary)

## 2 · 心智模型

### 类比:四层仓库

想象一个城市:

- **大型超市**(pacman / 官方仓库)—— 卖生活必需品,质量保证,但品类有限
- **民间集市**(AUR)—— 啥都有,自己挑质量
- **专门超市**(rustup / asdf)—— 卖特定种类(工具链版本)
- **直供厂家**(cargo)—— 项目需要的零件,直接从 crates.io 拉

你想吃苹果,去超市;想买进口稀有奶酪,去集市;想买特定年份红酒,去专门酒行;你想给工厂配零件,直供零件厂。

每层"仓库"有自己的"账本":
- pacman:`/var/lib/pacman/local/` 记录装了什么
- rustup:`~/.rustup/` 存所有工具链
- cargo:`~/.cargo/registry/` 存下载过的 crate
- AUR:每个 PKGBUILD 文件就是一个"配方"

### 严谨原理:什么是"包"

一个"包"(package)通常包含:
1. **元数据**:名字、版本、作者、依赖
2. **二进制 / 源码**:真正要装的东西
3. **安装脚本**:装到哪、装完做什么(update desktop database 等)
4. **依赖列表**:依赖什么其他包、版本范围

pacman 包是 `.pkg.tar.zst` 文件——一个压缩归档,里面装以上四样东西。装包就是解压 + 跑安装脚本。

AUR 包是 `PKGBUILD` 文件——一个 shell 脚本,描述"怎么从源码构建出 `.pkg.tar.zst`"。AUR 本身不存二进制,只存配方。`makepkg -si` 命令读配方,下载源码、编译、打 .pkg.tar.zst、装它。

crate 是 `*.crate` 文件——本质也是 tar.gz,里面是源码 + `Cargo.toml`。cargo 拉下来后**自己编译**(不是预编译),所以跨平台。

## 3 · 四域深入

### 3.1 · pacman:Arch 系统包管理

#### 基本命令

```bash
# 同步仓库索引 + 升级所有包(每次装新软件前必跑)
sudo pacman -Syu

# 装包
sudo pacman -S <package>
sudo pacman -S --needed helix tmux ripgrep    # --needed:已装就不重装
sudo pacman -S --noconfirm <pkg>              # 不问 yes/no(脚本里用)

# 删包(保留依赖)
sudo pacman -R <package>

# 删包 + 它独占的依赖
sudo pacman -Rs <package>     # 注意:不要删 base / base-devel

# 删包 + 依赖 + 配置文件
sudo pacman -Rns <package>

# 搜包
pacman -Ss <keyword>          # 在仓库里搜
pacman -Qs <keyword>          # 在已装里搜

# 看包信息
pacman -Si <package>          # 仓库里的信息
pacman -Qi <package>          # 已装的信息(包含安装时间、占用空间)

# 看包包含什么文件
pacman -Ql <package>          # 列出所有安装的文件路径
pacman -Qo /usr/bin/ls        # 这个文件是哪个包装的

# 看孤儿包(没被任何包依赖的、可以删的)
pacman -Qdt

# 清缓存(默认保留最近 3 个版本)
sudo pacman -Sc

# 列出最近装过的 20 个包
expac --timefmt='%Y-%m-%d %T' '%l\t%n' | sort | tail -20
```

#### 选项记忆

| 选项 | 全称 | 含义 |
|---|---|---|
| -S | sync | 从仓库装(主操作) |
| -R | remove | 删 |
| -Q | query | 查已装 |
| -y | refresh | 刷新仓库索引 |
| -u | sysupgrade | 升级所有 |
| -s | search / recursive | 搜索(配合 S/Q)/ 递归(配合 R) |
| -i | info | 看信息 |
| -l | list | 列文件 |
| -n | nosave | 不保留配置 |
| -c | cascade / clean | 级联删 / 清缓存 |

#### 配置文件 `/etc/pacman.conf`

```ini
# 启用彩色输出
Color
# 启用进度条
VerbosePkgLists
# 启用并行下载(显著加快)
ParallelDownloads = 5

# 仓库定义(默认 core / extra / multilib 已开)
[core]
Include = /etc/pacman.d/mirrorlist

[extra]
Include = /etc/pacman.d/mirrorlist

[multilib]   # 32 位库(Steam 游戏需要)
Include = /etc/pacman.d/mirrorlist
```

#### Arch 镜像源

`/etc/pacman.d/mirrorlist` 列出从哪下载。新装系统用 `reflector` 自动选最快的:

```bash
sudo pacman -S reflector
sudo reflector --latest 50 --protocol https --sort rate --save /etc/pacman.d/mirrorlist
```

#### Pacman rosetta:其他发行版对应

| 操作 | Arch (pacman) | Debian (apt) | Fedora (dnf) |
|---|---|---|---|
| 装 | pacman -S | apt install | dnf install |
| 删 | pacman -Rs | apt remove | dnf remove |
| 升级 | pacman -Syu | apt update && apt upgrade | dnf upgrade |
| 搜 | pacman -Ss | apt search | dnf search |

### 3.2 · AUR:Arch User Repository

AUR 是 Arch 社区维护的"民间仓库"。官方仓库 ~12000 包,AUR 有 ~100000 包。Steam 游戏不在官方,但 AUR 有;最新版软件 pacman 没追上,AUR 通常已收录。

**关键**:AUR 不直接提供二进制,只提供 `PKGBUILD`(配方)。用户用 `makepkg` 编译。

#### AUR helper:paru 或 yay

手动 makepkg 太慢。helper 自动化:搜、下载、编译、装、跟踪升级。

```bash
# 装 paru(推荐,Rust 写的)
sudo pacman -S --needed base-devel git
git clone https://aur.archlinux.org/paru.git ~/paru
cd ~/paru
makepkg -si

# 装 yay(更老牌,Go 写的)
git clone https://aur.archlinux.org/yay.git ~/yay
cd ~/yay
makepkg -si
```

用法(基本和 pacman 一样,小写 s 改成大写 S,或直接用):

```bash
paru <keyword>              # 搜索 + 交互式选装
paru -S <package>           # 装
paru -Syu                   # 升级所有(包括 AUR 包)
paru -R <package>           # 删

# 一些好用的命令
paru -Pstat                 # 看本地装包统计
paru -Qtdq | paru -Rns -    # 清所有孤儿包
paru -G <package>           # 看 PKGBUILD 不装
paru --gendb                # 重建 AUR 数据库
```

#### 装 AUR 包的风险

AUR 是社区维护,任何人可以提交。装前一定:
1. **看 PKGBUILD**:`paru -Gp <package>` 看构建脚本,确认没有恶意命令
2. **看 votes**:votes 多的更可信
3. **看 last updated**:太久没更新的可能不能用
4. **看 maintainer**:有 maintainer 比孤儿(orphan)好

#### 实战例子:装 blender-beta

```bash
paru -S blender-beta
# paru 会:
# 1. 下载 PKGBUILD
# 2. (你可以)审查 PKGBUILD
# 3. makepkg:下源码、编译、打 .pkg.tar.zst
# 4. 提示你密码,sudo pacman -U 装它
```

### 3.3 · cargo:Rust 包管理

#### Cargo.toml:项目元数据

```toml
[package]
name = "my-game"
version = "0.1.0"
edition = "2021"
authors = ["You <you@example.com>"]
description = "A handmade hero clone"

[dependencies]
glam = "0.29"          # 版本范围 "0.29" = "^0.29" = >=0.29.0, <0.30.0
winit = { version = "0.30", features = ["rwh_06"] }
serde = { version = "1.0", optional = true }   # 可选依赖

[dev-dependencies]
criterion = "0.5"      # 仅测试 / 基准用

[features]
default = ["serde"]
networking = []       # 编译时 feature flag

[profile.release]
opt-level = 3
lto = true            # 链接时优化
codegen-units = 1     # 单 codegen unit(更好优化,编译慢)

[[bin]]
name = "my-game"
path = "src/main.rs"
```

#### Cargo.lock:版本锁定

`Cargo.lock` 记录**实际使用的版本**(精确到 patch)。第一次 `cargo build` 时,cargo 解析 `^0.29` → 选 0.29.2,把 0.29.2 写进 lock。之后 build 用 0.29.2 不变。

**库项目**(给别人当依赖)不要 commit `Cargo.lock`——让下游选。
**应用项目**(自己跑)要 commit `Cargo.lock`——保证可重现。

#### SemVer:语义化版本

版本号 `MAJOR.MINOR.PATCH`(如 `1.4.2`):
- MAJOR 变 → 不兼容的破坏(改 API)
- MINOR 变 → 向后兼容的新功能
- PATCH 变 → 向后兼容的 bug 修复

cargo 的 `^1.4.2` 意思是 `>=1.4.2, <2.0.0`(同一 MAJOR 内自动升)。
`~1.4.2` 意思是 `>=1.4.2, <1.5.0`(同一 MINOR)。
`*` 任意版本(危险,别用)。

#### 常用命令

```bash
cargo new my-project         # 新建二进制项目
cargo new --lib my-lib       # 新建库项目
cargo build                  # 编译(debug 模式)
cargo build --release        # 编译(release 模式,优化)
cargo run                    # 编译 + 跑
cargo run -- --flag value    # 给程序传参数(注意 --)
cargo test                   # 跑所有测试
cargo test -- --nocapture    # 测试时显示 println! 输出
cargo check                  # 只检查不生成 binary(快,IDE 用)
cargo clippy                 # 跑 linter
cargo fmt                    # 格式化代码
cargo fmt -- --check         # CI 用:检查是否已格式化
cargo doc --open             # 生成文档并打开浏览器
cargo add glam               # 加依赖(自动找最新版本,写进 Cargo.toml)
cargo add glam --features "bytemuck"
cargo remove glam            # 删依赖
cargo update                 # 升级所有依赖(在 SemVer 范围内)
cargo update -p glam         # 只升 glam
cargo tree                   # 看依赖树
cargo tree -d                # 看重复依赖(同一 crate 多版本)
cargo bench                  # 跑基准(需要 criterion 等)
cargo install cargo-watch    # 装命令行工具到 ~/.cargo/bin
cargo install --path .       # 把当前项目装成 binary
cargo uninstall cargo-watch  # 卸载
```

#### crates.io:Rust 包仓库

https://crates.io 是 Rust 的官方包仓库,目前 ~15 万 crate。`cargo add` / `cargo build` 默认从这里拉。

每个 crate 有:
- README
- 文档(自动从 doc comment 生成,docs.rs 自动构建)
- 版本历史
- 下载统计
- 依赖关系

#### Cargo 的隐藏能力

```bash
# 用特定工具链
cargo +nightly build          # 用 nightly
cargo +stable run

# 跨编译
rustup target add wasm32-unknown-unknown
cargo build --target wasm32-unknown-unknown

# 工作空间(workspace):多个 crate 一起管理
# Cargo.toml 顶层:
# [workspace]
# members = ["crates/*"]

# 覆盖依赖(用本地版本调试)
# Cargo.toml:
# [patch.crates-io]
# glam = { path = "../glam" }
```

### 3.4 · rustup:Rust 工具链版本管理

```bash
# 装工具链
rustup toolchain install stable
rustup toolchain install beta
rustup toolchain install nightly

# 看已装
rustup toolchain list

# 默认
rustup default stable

# 给某项目指定(在该项目目录下)
rustup override set nightly

# 看 override
rustup override list

# 加 / 删 component
rustup component add rust-src clippy rustfmt rust-analyzer
rustup component remove clippy

# 加 target(跨编译)
rustup target add wasm32-unknown-unknown

# 更新所有工具链到最新
rustup update

# 卸载整个 Rust
rustup self uninstall
```

**Arch 的特殊性**:`/usr/bin/rustc` 是 pacman 装的。但如果你 `rustup default stable`,rustup 装的 stable 会**优先于** pacman 的——因为 rustup shim 在 PATH 前面。验证:

```bash
which rustc
# /home/sun/.cargo/bin/rustc  ← rustup 的
# /usr/bin/rustc               ← pacman 的

rustc --print sysroot
# 看实际用的 sysroot 路径
```

### 3.5 · asdf:多语言版本统一管理

asdf 是一个统一插件,管 Python / Node / Ruby / Go / Elixir…… 几十种语言。每语言一个插件,每个项目可以 `.tool-versions` 文件指定版本。

#### 装 asdf

```bash
# 依赖
sudo pacman -S --needed git curl

# 装 asdf 本体(git clone 法,官方推荐)
git clone https://github.com/asdf-vm/asdf.git ~/.asdf --branch v0.14.0

# 加到 shell(~/.bashrc 末尾)
echo '. "$HOME/.asdf/asdf.sh"' >> ~/.bashrc
source ~/.bashrc

# 验证
asdf --version
```

#### 装插件 + 用

```bash
# 装 Python 插件
asdf plugin add python
asdf plugin add nodejs
asdf plugin add golang

# 列所有可装版本
asdf list all python

# 装某版本
asdf install python 3.12.0
asdf install python 3.10.13

# 设全局默认
asdf global python 3.12.0

# 给某项目设(在该目录下创建 .tool-versions)
asdf local python 3.10.13
cat .tool-versions
# 输出:python 3.10.13

# 看当前用什么
asdf current
# 输出:
# python   3.10.13  (set by /path/to/.tool-versions)
# nodejs   20.0.0   (set by /home/user/.tool-versions)
```

#### 为什么不用各语言原生的(pyenv、nvm)?

| 工具 | 优点 | 缺点 |
|---|---|---|
| pyenv + nvm + rbenv | 各自最成熟 | 多套工具,配置各不同 |
| asdf | 一套管所有 | 部分插件比原生慢更新 |

简单项目用 asdf,深度用某语言用原生。Rust 用 rustup(asdf 也有 rust 插件,但 rustup 更主流)。

## 4 · 认知地图

### 4.1 上级

- **依赖管理(Dependency Management)** — 软件工程的核心问题之一,管"我的代码依赖什么"
- **版本控制(Versioning)** — SemVer / lock file / reproducible build
- **包分发(Package Distribution)** — 仓库架构、镜像、签名

### 4.2 同级(各层级包管理器)

| 工具 | 层级 | 何时用 |
|---|---|---|
| pacman | 系统 | 装 OS 软件 |
| paru / yay | 系统 + AUR | 装 AUR 包 |
| rustup | Rust 工具链 | 切 stable/beta/nightly |
| cargo | Rust 项目 | 装项目依赖 |
| cargo install | 用户 binary | 装命令行工具 |
| asdf | 多语言版本 | Python/Node 多版本 |
| pip / npm | 各语言项目 | 对应语言的 cargo |
| flatpak / snap | 沙箱应用 | GUI 应用,跨发行版 |

### 4.3 下级

- **PKGBUILD** — AUR 的"配方"文件
- **Cargo.toml / Cargo.lock** — Rust 项目的"清单"
- **mirrorlist** — pacman 下载源列表
- **GPG 签名** — pacman 验证包来源
- **rolling release** — Arch 滚动更新模型

## 5 · 对照与变奏

### Arch 滚动发布 vs Debian/Ubuntu 大版本发布

| | Arch (rolling) | Ubuntu (LTS) |
|---|---|---|
| 模型 | 滚动,一直最新 | 两年一个大版本 |
| 优势 | 永远最新,没有"升级发行版"麻烦 | 稳定,适合服务器 |
| 劣势 | 偶尔 break(自行修复) | 包版本陈旧 |
| 适合 | 桌面 / 开发机 | 生产服务器 |

HH 教程用 Arch,因为你需要最新 Rust / 图形驱动 / 工具链。服务器用 Debian 没问题,但本教程的"开发机"假设 Arch。

### cargo vs 其他语言的包管理

| 语言 | 工具 | 装在哪儿 |
|---|---|---|
| Rust | cargo | 项目(依赖)或 ~/.cargo/bin(工具) |
| Python | pip + venv | 项目虚拟环境 |
| Node | npm / yarn / pnpm | 项目 node_modules |
| Go | go mod | 项目 + 全局缓存 |
| C++ | conan / vcpkg | 项目 + 系统混合 |

Rust 的 cargo 是这些里**最干净**的——单一官方工具,无分裂。这是 Casey 没用 Rust 但我会推荐你用 Rust 写 HH 的原因之一。

### 历史演化

- **1990s**:Linux 各发行版各自做包管理(RPM、DEB)
- **2000s**:apt / yum 成熟;Python 出 pip;Ruby 出 gem
- **2010s**:npm 横空出世;cargo 横空出世(2014);snap / flatpak 出现
- **2020s**:cargo 成为新一代包管理的"金标准",很多新语言(zig、deno)都借鉴

## 6 · 关联 Day

- **铺垫**:[00-terminal-basics.md](00-terminal-basics.md)(命令行基础)、[09-editor-toolchain.md](09-editor-toolchain.md)(编辑器和工具链)
- **当天**:本篇
- **后续**:
  - [12-opensource-pr-flow.md](12-opensource-pr-flow.md)(开源贡献,你会 fork 一个 crate 改它)
  - Phase 1 Day 001(`cargo new` 第一个项目)
  - Phase 2(加 glam / winit 依赖)

## 7 · 变式训练

### Lv1 · 概念辨析

**题**:你想用一个 Rust 库 `rand`(随机数生成),下面哪种做法对?
A. `sudo pacman -S rand`
B. `cargo install rand`
C. `cargo add rand`
D. `paru -S rust-rand`

**参考解答**:**C**。
- A 错:rand 是 Rust crate,不是系统包,pacman 没有(就算有 `rust-rand` 也是给系统 Rust 用的,会和你项目的版本冲突)
- B 错:`cargo install` 是装**命令行 binary**,不是项目依赖
- C 对:加到当前项目的 `Cargo.toml` 里,版本管理由 cargo 管
- D 错:同 A 的理由

记住口诀:**项目依赖用 cargo add,系统软件用 pacman,CLI 工具用 cargo install,AUR 是 pacman 没有的补充**。

### Lv2 · 动手实践

**题**:完成以下任务,记录每步输出:

1. 看 pacman 配置文件,确认 ParallelDownloads 已开
2. `pacman -Qi rustup` 看版本、安装时间、占用空间
3. 找出系统里所有"孤儿包"
4. 装 `btop`(更现代的 htop 替代),用 pacman
5. 装一个 AUR 软件包(推荐:`paru` 自己,或 `visual-studio-code-bin`),用 paru
6. 在一个新 Rust 项目里 `cargo add rand`,看 Cargo.toml 改动
7. 用 `cargo tree` 看依赖树
8. 装 asdf,用 asdf 装 Python 3.12,在某目录设为 local 版本

完成标准:每步实际跑命令,把关键输出截图/粘贴到你的笔记。

**参考解答**(命令清单):

```bash
# 1.
grep -E "^ParallelDownloads|^Color" /etc/pacman.conf

# 2.
pacman -Qi rustup

# 3.
pacman -Qdt
# 或删它们:
# paru -Qtdq | paru -Rns -

# 4.
sudo pacman -S btop
btop    # 启动,按 q 退

# 5.
paru -S visual-studio-code-bin
# 审查 PKGBUILD,确认 ok,继续装

# 6.
cargo new pkgs-test
cd pkgs-test
cargo add rand
cat Cargo.toml    # 应该看到 rand = "0.8.x" 加进了 [dependencies]

# 7.
cargo tree
# 看到 pkgs-test -> rand -> rand_core -> ...

# 8.
git clone https://github.com/asdf-vm/asdf.git ~/.asdf --branch v0.14.0
echo '. "$HOME/.asdf/asdf.sh"' >> ~/.bashrc
source ~/.bashrc
asdf plugin add python
asdf install python 3.12.0
asdf global python 3.12.0
python --version    # Python 3.12.0
mkdir test-python && cd test-python
asdf local python 3.10.13
python --version    # Python 3.10.13(切到这个目录)
```

### Lv3 · 迁移设计

**题**:你在一个团队项目里,某个依赖 `crate_a` 用了 `glam 0.27`,另一个 `crate_b` 用了 `glam 0.29`。cargo 怎么处理?会有什么问题?怎么修?

**提示**:
- `cargo tree -d` 看重复依赖
- Rust 允许同一 crate 多版本共存(因为每个版本是独立 type)
- 但**问题**:两个版本的类型不能互转(glam 0.27 Vec3 和 0.29 Vec3 是不同类型),如果你的代码要传递 Vec3 给两个 crate 的 API,会编译失败
- 修复:用 `[patch.crates-io]` 或 `cargo update -p` 强制统一版本(如果 API 兼容)

### Lv4 · 开源贡献

**题**:`rustup` 是 Rust 工具链管理器,GitHub: https://github.com/rust-lang/rustup

1. clone 它,读 README
2. 找 doc 里的小问题(typo / 链接失效 / 命令过时)
3. **可能的贡献**:
   - README 里的某段命令示例没解释参数,补一行说明
   - `src/cli/` 某个命令的 help 文本可以更清楚
   - 找 issue 标签 `good first issue`
4. fork → branch → commit → PR(完整流程在 [12-opensource-pr-flow.md](12-opensource-pr-flow.md))

写下你打算提交的 PR 描述(repo / 文件 / 动机 / 验证)。

## 8 · Rust / Arch 落地代码

### 完整项目:用 cargo + pacman 协同

#### 项目结构

```
my-game/
├── Cargo.toml         ← 项目元数据
├── Cargo.lock         ← 版本锁定(应用项目 commit 它)
├── src/
│   ├── main.rs
│   └── lib.rs
├── tests/
│   └── integration.rs
├── benches/
│   └── parse_bench.rs
└── .tool-versions     ← asdf 配置(可选)
```

#### 完整 Cargo.toml

```toml
[package]
name = "my-game"
version = "0.1.0"
edition = "2021"
rust-version = "1.75"   # 最低支持的 Rust 版本
description = "Handmade Hero in Rust"
license = "MIT"
repository = "https://github.com/you/my-game"

[dependencies]
glam = "0.29"
winit = { version = "0.30", features = ["rwh_06"] }
rand = "0.8"

[dev-dependencies]
criterion = "0.5"

[features]
default = []
debug_render = []      # 调试渲染模式
profile = []           # 性能 profiling

[profile.dev]
opt-level = 1          # debug 模式下也开一点优化,跑得动游戏

[profile.release]
opt-level = 3
lto = "fat"            # 链接时优化,激进
codegen-units = 1      # 单 codegen unit,优化更好
panic = "abort"        # panic 直接 abort,不要 unwind(更快、二进制更小)

[[bench]]
name = "parse_bench"
harness = false        # 用 criterion 自己的 harness
```

#### 系统包管理的最佳实践脚本

```bash
#!/bin/bash
# maintenance.sh —— Arch 系统维护

set -e

# 1. 全系统升级
sudo pacman -Syu

# 2. 升级 AUR 包
paru -Syu

# 3. 清孤儿包
orphans=$(paru -Qtdq || true)
if [ -n "$orphans" ]; then
    echo "Removing orphans: $orphans"
    paru -Rns $orphans
fi

# 4. 清 pacman 缓存(保留最近 2 个版本)
sudo paccache -r -k 2
# 或全部清:
# sudo paccache -ruk0   # 清未安装的包

# 5. 清 cargo 缓存(可选,只清 registry)
# cargo cache --autoclean  # 需要 cargo install cargo-cache

# 6. 升级 rustup 工具链
rustup update

# 7. 升级 cargo install 装的工具
cargo install --list | awk '/^[a-z]/{print $1}' | xargs -I{} cargo install {} --force

# 8. 升级 asdf 工具
# asdf plugin update --all

# 9. 看磁盘占用
df -h /
du -sh ~/.cache ~/.cargo ~/.rustup 2>/dev/null

# 10. 看已装包统计
echo "Total packages: $(paru -Q | wc -l)"
echo "AUR packages: $(paru -Qm | wc -l)"
echo "Explicitly installed: $(paru -Qe | wc -l)"
```

跑法:
```bash
chmod +x maintenance.sh
./maintenance.sh
```

每周跑一次,系统保持健康。

### Troubleshooting

- **`pacman -S xxx` 报 "target not found"**:可能名字错。`pacman -Ss xxx` 搜索;或 AUR 有,用 paru
- **`pacman -Syu` 报 "conflicting files"**:通常是手工装了文件(没通过 pacman)。删冲突文件,或 `--overwrite` 强制
- **`cargo build` 报 "failed to download"**:网络问题。设镜像:`~/.cargo/config.toml` 加 `[source.crates-io]` + `replace-with = "ustc"`
- **rustup 切 nightly 但 cargo 还用 stable**:在项目目录看 `rustup override list`,可能没设
- **AUR 包编译失败**:看 PKGBUILD 的依赖(`depends=`),可能缺;或源 URL 失效(改镜像)

中国镜像配置(可选,网络环境需要):

```toml
# ~/.cargo/config.toml
[source.crates-io]
replace-with = "ustc"

[source.ustc]
registry = "sparse+https://mirrors.ustc.edu.cn/crates.io-index/"
```

## 9 · 延伸阅读(可选补充,非必需)

本仓库本地:
- [09-editor-toolchain.md](09-editor-toolchain.md) — 工具链
- [12-opensource-pr-flow.md](12-opensource-pr-flow.md) — 开源贡献
- [phase-0/README.md](README.md)

外部稳定 URL:
- Arch Wiki pacman:https://wiki.archlinux.org/title/Pacman
- Arch Wiki AUR:https://wiki.archlinux.org/title/Arch_User_Repository
- Cargo Book:https://doc.rust-lang.org/cargo/
- SemVer 规范:https://semver.org/
- asdf 文档:https://asdf-vm.com/

真实开源源码:
- pacman 源码:https://gitlab.archlinux.org/pacman/pacman
- paru 源码:https://github.com/Morganamilo/paru
- rustup 源码:https://github.com/rust-lang/rustup
