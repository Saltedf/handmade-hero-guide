---
article: 01
phase: 0
title: "Arch Linux 配置:pacman / systemd / 用户权限"
type: setup
difficulty: 2
duration: "2-3h"
domains: [linux]
prereqs: ["00-terminal-basics"]
---

# 01 · Arch Linux 配置:pacman / systemd / 用户权限

> 上一篇你学会了在终端里跑命令。这一篇假设你的电脑上已经能开机进 Arch(或任何 Linux 发行版),我们要把它**从"能开机"调到"能干活"**:装软件、管服务、配用户、看日志。理解这些之后,你后面写 Rust 程序、跑 cargo build、用 strace 时才知道背后发生了什么。

## 0 · 为什么要有这一天

很多新手装完系统就以为"完事了",其实你只是装了一个空壳。开机能进桌面,但你:

1. **装不了软件**:你想装 `git`,跑 `sudo apt install git`(Ubuntu 命令)在 Arch 上会报错。每个发行版有自己的包管理器。Arch 用 `pacman`,语法不同。
2. **不懂为什么开机后某些程序自动启动了**:你的电脑开机就有图形界面、有网络、有声音。这些是谁启动的?是 `systemd`——Linux 的"大管家"。不懂它,你就不能让 cargo 写的 server 开机自启,也不能 kill 卡死的进程组。
3. **不知道为什么没声音**:Linux 的声音走 PipeWire(新一代)或 PulseAudio。如果你不知道它是个 service,你就不知道 `systemctl --user restart pipewire` 能救命。
4. **不懂"普通用户 vs root"为什么这样分**:为什么 `sudo` 比 `su` 好?为什么 `rm -rf /` 普通 user 跑不了?权限模型不是"装样子",是**安全模型的根基**。后面你跑 cargo 装的 crate 可能有恶意代码,你跑成 root 还是普通 user 决定灾难大小。
5. **看不见错误**:服务挂了你只会骂街;会用 `journalctl` 的人 10 秒找到原因。

**心理锚点**:读完这一篇,你能:
- 用 pacman 装任何软件,从官方仓库或 AUR
- 用 systemctl 启动 / 停止 / 开机自启 / 查状态 任何服务
- 用 journalctl 看任何服务的日志,过滤、追踪
- 创建新用户、给 sudo 权限、理解 root vs user
- 解释为什么"装东西要 sudo,跑东西不要 sudo"

## 1 · 概念地图:发行版、包管理器、init 系统

新手最容易混淆的几层:

| 词 | 是什么 | 类比 |
|---|---|---|
| **Linux 内核(kernel)** | 操作系统的核心,管 CPU / 内存 / 进程 / 文件 / 网络 | 大楼的钢筋骨架 |
| **发行版(distro)** | 内核 + 一套软件 + 包管理器打包成的"成品系统" | 一栋装修好的大楼(Arch / Ubuntu / Fedora 是不同装修风格) |
| **包管理器(package manager)** | 装软件 / 升级软件 / 删软件的工具 | 大楼的物业,你下单它去取货 |
| **init 系统** | 内核启动后跑的第一个用户态进程(PID 1),负责启动所有其他服务 | 大楼的总管,掌管所有服务生 |
| **服务(service / daemon)** | 后台常驻程序(网络、声音、SSH、时钟……) | 大楼的水电暖常开系统 |
| **桌面环境(DE)** | 图形界面(GNOME / KDE / XFCE) | 大楼大堂的装修 |

**关键**:Arch Linux 选了 `pacman`(包管理器) + `systemd`(init 系统)。本教程全程基于这套。Ubuntu 用 `apt`,Fedora 用 `dnf`——核心思想一样,语法不同。你跟 HH 教程必须用 Linux(不是 Windows),而 Arch 是 Casey 风格——极简、透明、文档完整——的最佳选择。

## 2 · 心智模型

### 费曼类比:Linux 是一栋大楼

把你的电脑想成一栋大楼:

- **内核(kernel)** = 大楼的钢筋结构 + 水管 + 电线。看不见,但没了就塌
- **systemd** = 物业经理。早上 7 点开灯、开电梯、开空调,晚上 11 点关。它管**所有服务**
- **服务(daemon)** = 大楼里的常驻员工:
  - `NetworkManager` 是网管(管网络)
  - `pipewire` 是音响师(管声音)
  - `sshd` 是门卫(管 SSH 远程访问)
  - `cron` / `systemd-timer` 是定时钟(到点干活)
- **pacman** = 采购员。你说"我要装 neovim",它去仓库取货、安装、登记
- **你的用户账号** = 大楼里的一户人家。你能用公共设施,但不能拆承重墙
- **root** = 大楼物业总经理。能拆承重墙,也能让大楼塌
- **/etc 配置文件** = 大楼的设备管理规定手册,改了下次开机生效
- **/var/log 日志** = 各服务每天写的工作日志,出事去翻

**核心抽象**:**Linux 把"管理"显式化了**。Windows 把"为什么有声音"藏在 5 层 GUI 后面;Linux 是"pipewire 这个 daemon 在跑,它的日志在 journalctl,它的配置在 /etc/pipewire"。一旦你接受这个心智,Linux 就不再神秘。

### 包是怎么"装上去"的

```bash
sudo pacman -S neovim
```

发生了什么:

1. pacman 读 `/etc/pacman.d/mirrorlist/`(镜像服务器列表),挑一个最快的
2. 从镜像下载仓库索引(`core.db`, `extra.db`, `multilib.db`),找到 `neovim` 的元数据(版本、依赖)
3. 解析依赖:neovim 依赖 `glibc`, `libluv`, `treesitter` …… 一并下载
4. 下载 `.pkg.tar.zst`(用 zstd 压缩的包)到 `/var/cache/pacman/pkg/`
5. 检查 `pacman-key` 签名,确认是官方包,没被篡改
6. 解压到 `/`,文件落到 `/usr/bin/nvim`, `/usr/share/nvim/`, `/usr/lib/` ……
7. 跑包里的 `.install` 钩子(可能要更新一些数据库)
8. 写入 `/var/lib/pacman/local/` 记录"我装了 neovim 0.10.2"

为什么必须 `sudo`:第 6 步要写 `/usr/bin/`,只有 root 能写。

### 服务怎么"跑起来"

```bash
sudo systemctl start sshd
```

1. systemd(PID 1)读 `/usr/lib/systemd/system/sshd.service`,知道怎么启动(`/usr/bin/sshd -D`)
2. systemd fork 一个子进程,execve 到 `/usr/bin/sshd`
3. sshd 监听 22 端口,等待连接
4. systemd 监控这个进程,挂了会自动重启(如果配置了 `Restart=always`)
5. 日志通过 `sd_notify` 发给 systemd-journald,存到 `/var/log/journal/`

**systemctl enable vs start**:
- `start` = 现在启动它
- `enable` = 让它开机时自动启动
- `enable --now` = 两件事一起做

### root vs sudo vs 普通用户

Linux 用 **UID(User ID)** 标识用户:
- UID 0 = root,能干任何事
- UID 1000+ = 普通用户,只能动自己 `~` 下的文件和**世界可写**的目录
- 中间 UID(1-999) = 系统服务账号(`http`, `postgres`, `git` 等)

`sudo`(superuser do)的本质:**临时**让一个普通用户以 root 身份跑一条命令。靠 `/etc/sudoers` 配置——只有 `wheel` 组(传统 Unix 管理员组)或被显式列出的用户能用。

为什么用 sudo 不用 su:
- `su` 直接切到 root,要知道 root 密码(共享,不安全)
- `sudo` 用自己的密码,有审计日志(谁在什么时候跑了什么)
- `sudo` 可以限制(只允许跑某些命令)

## 3 · 四域深入

### 3.1 · 🐧 Linux 系统编程视角

systemd 不只是"启动器",它暴露了 D-Bus API,你可以用代码控制服务。Rust 里:

```rust
// 用 zbus crate 和 systemd 说话(简化示例)
// Cargo.toml: zbus = "4"
use zbus::{Connection, dbus_proxy};

#[dbus_proxy(
    interface = "org.freedesktop.systemd1.Manager",
    default_service = "org.freedesktop.systemd1",
    default_path = "/org/freedesktop/systemd1"
)]
trait SystemdManager {
    fn start_unit(&self, name: &str, mode: &str) -> zbus::Result<zbus::zvariant::OwnedObjectPath>;
    fn stop_unit(&self, name: &str, mode: &str) -> zbus::Result<zbus::zvariant::OwnedObjectPath>;
}

fn main() -> zbus::Result<()> {
    let conn = Connection::system()?;   // 连到系统总线
    let manager = SystemdManagerProxyBlocking::new(&conn)?;
    // 启动 sshd(需要 polkit 授权)
    manager.start_unit("sshd.service", "replace")?;
    Ok(())
}
```

**每行解释**:
- `Connection::system()` — 连到系统总线 `/var/run/dbus/system_bus_socket`,这是 D-Bus 的入口
- `SystemdManagerProxyBlocking::new(&conn)` — 生成一个代理对象,调用它的方法就是发 D-Bus 消息给 systemd
- `start_unit("sshd.service", "replace")` — 等价于 `systemctl start sshd`,`"replace"` 是 mode(如果有同名 job 在跑,替换它)

这就是 `systemctl` 命令背后的真实机制。你能用代码做任何 systemctl 能做的事。

包管理器同理。`pacman` 是 C 写的,但你可以读 `/var/lib/pacman/local/`(已装包列表)来知道装了什么:

```rust
use std::fs;
fn installed_packages() -> Vec<String> {
    let mut pkgs = Vec::new();
    if let Ok(entries) = fs::read_dir("/var/lib/pacman/local") {
        for entry in entries.flatten() {
            let name = entry.file_name().into_string().unwrap();
            // 文件名格式 "neovim-0.10.2-1"
            if let Some(pkg) = name.split('-').next() {
                pkgs.push(pkg.to_string());
            }
        }
    }
    pkgs
}
```

### 3.2 · 🦀 Rust 生态视角

Rust 生态和 Arch 关系紧密:

- **rustup**:Rust 的多版本管理器(下一篇 Rust 文章细讲),和 pacman 配合:用 pacman 装 `rustup`,用 rustup 装 stable / nightly / 特定版本
- **cargo**:Rust 包管理器,**不**依赖系统 pacman。cargo 装的是 Rust crate(库),pacman 装的是系统二进制
- **archlinux 的 AUR** 里有大量 Rust 项目被打包:`paru -S ripgrep` 装的就是 Rust 项目
- **mold / lld**:Rust 的链接器,加快大型 cargo build

关键区分:
- 系统库(libpng, openssl)用 pacman 装(pacman 是底层)
- Rust 库(serde, tokio)用 cargo 装(cargo 在上层)
- 有时一个东西两边都有(比如 `ripgrep`):pacman 装系统级 cargo 装项目级,看场景

## 4 · 认知地图

### 4.1 上级

- **Linux 操作系统** — 内核 + 用户态工具 + 包管理 + 桌面,组成完整可用的系统
- **Unix 哲学** — 每个工具做好一件事;包管理器、init 系统、日志系统都是分离的小工具,通过文件和 D-Bus 协作
- **声明式系统管理** — `/etc/` 改一个配置文件,systemd 重启服务就生效(不用重启整台机器)

### 4.2 同级

| 工具 | 关键差别 | 何时用 |
|---|---|---|
| pacman | Arch 官方,二进制包,极简 | Arch 日常 |
| apt | Ubuntu/Debian,二进制包,数量最多 | Ubuntu 服务器 |
| dnf | Fedora/RHEL,二进制包,企业级 | Fedora 桌面 |
| AUR | Arch 用户仓库,PKGBUILD 脚本(用户自维护) | Arch 装官方仓库没有的软件 |
| paru / yay | AUR helper(自动下载 PKGBUILD + 编译 + 安装) | Arch 装 AUR 软件 |
| cargo | Rust 包管理器(只管 Rust) | Rust 项目内 |
| flatpak / snap | 跨发行版的容器化应用 | 想要沙箱隔离的应用 |

| init 系统 | 关键差别 | 何时用 |
|---|---|---|
| systemd | 主流,功能丰富,套件化(systemd-journald, systemd-networkd, ...) | 95% 的现代 Linux |
| OpenRC | Gentoo/Alpine 用,经典 SysV 风格,不并行 | 嵌入式 / 极简 |
| runit | Void Linux,极简 | 喜欢极简的人 |

本教程:**pacman + paru + systemd**。

### 4.3 下级

- **pacman 子命令**:`-S`(sync/install), `-R`(remove), `-Q`(query local), `-U`(upgrade from file)
- **systemctl 子命令**:`start`, `stop`, `restart`, `enable`, `disable`, `status`, `list-units`, `list-unit-files`
- **journalctl 子命令**:`-u <unit>`(某服务日志), `-f`(follow,实时), `--since`, `--until`, `-p err`(只看错误)
- **用户管理命令**:`useradd`, `usermod`, `passwd`, `groupadd`, `gpasswd`
- **配置文件**:`/etc/pacman.conf`, `/etc/sudoers`, `/etc/systemd/system/`, `/etc/os-release`

## 5 · 对照与变奏

### 同一任务的跨发行版对比:装 git

| 发行版 | 命令 |
|---|---|
| Arch | `sudo pacman -S git` |
| Ubuntu / Debian | `sudo apt install git` |
| Fedora | `sudo dnf install git` |
| openSUSE | `sudo zypper install git` |
| Gentoo | `sudo emerge dev-vcs/git` |
| NixOS | `nix-env -iA nixos.git` |

差别只在语法。思想都是:**从仓库下载包,解析依赖,装到系统**。

### 同一任务的 init 系统对比:启动 sshd

| init 系统 | 命令 |
|---|---|
| systemd | `sudo systemctl start sshd` |
| OpenRC | `sudo rc-service sshd start` |
| runit | `sudo sv up sshd` |
| SysV(老古董) | `sudo service sshd start` 或 `/etc/init.d/sshd start` |

### 二进制包 vs 源码包

- **二进制包**(pacman, apt, dnf):官方预先编译好,装得快
- **源码包**(Gentoo `emerge`, Arch 的 AUR):本机编译,可定制,慢

AUR 是 Arch 的杀手锏:如果官方没有的软件,大概率 AUR 有别人写的 PKGBUILD 脚本,你 `paru -S xxx` 等于"自动下载源码 + 编译 + 装包",整个过程透明可读。

## 6 · 关联 Day

- **铺垫**:[00-terminal-basics.md](00-terminal-basics.md) — 你需要会用终端跑命令,这一篇所有命令都假设你会
- **当天**:[01-arch-setup.md](01-arch-setup.md)(本篇)
- **后续**:
  - [02-git-and-github.md](02-git-and-github.md) — 用 pacman 装 git 后才能用
  - [03-rust-from-scratch-1.md](03-rust-from-scratch-1.md) — `sudo pacman -S rustup` 装 Rust
  - [07-linux-filesystem.md](07-linux-filesystem.md) — 理解 `/etc`, `/var`, `/usr` 的角色
  - [08-processes-and-signals.md](08-processes-and-signals.md) — systemd 启动的服务就是进程,信号控制它

## 7 · 变式训练

### Lv1 · 概念辨析

**题**:为什么 Arch 推荐用 `sudo pacman -Syu`(同步 + 升级)而不是分两步 `sudo pacman -Sy` + `sudo pacman -Su`?用 pacman 的内部状态解释。

**参考解答**:pacman 在 `/var/lib/pacman/sync/` 存仓库索引(`.db` 文件)。`-S` 操作都基于这个索引:

- `-Sy` = 同步索引(下载新 `.db`),但不升级已装的包
- `-Su` = 升级所有已装包到索引里写的版本
- `-Syu` = 两步一起

如果你只跑 `-Sy`(更新索引不升级),然后跑 `pacman -S somepkg`(装新包),pacman 会拿新索引去解析 somepkg 的依赖,但你系统里其他包还是旧版本——可能 somepkg 的新版本要求新版依赖,你系统里没有,**导致部分升级(partial upgrade)破坏依赖**。Arch 官方明确反对这样做。

正确做法:每次装新软件前先 `pacman -Syu` 全系统升级到一致状态,再装。

### Lv2 · 动手实践

**题**:完成以下任务,每步给完整命令 + 预期输出:

1. 查看你的发行版信息(确认是 Arch)
2. 看当前系统装了多少个包
3. 看 NetworkManager 服务状态(应该 active)
4. 列出所有"开机自启"的服务
5. 看 sshd 是否在跑(可能没装)
6. 装 `htop`(进程监视器)
7. 用 htop 看进程,按 `q` 退出
8. 创建用户 `dev`,密码 `dev123`,加入 `wheel` 组
9. 用 `su - dev` 切到 dev,验证能 `sudo ls /root`
10. 删除 dev 用户和它的 home 目录

完成标准:每步独立完成,记录你看到的输出。

**参考解答**(命令):

```bash
# 1. 发行版信息
cat /etc/os-release
# 预期输出包含:
# NAME="Arch Linux"
# PRETTY_NAME="Arch Linux"
# ID=arch
# VERSION_ID=rolling

# 2. 装了多少个包
pacman -Q | wc -l
# 预期输出:300-1500 之间的数字

# 3. NetworkManager 状态
systemctl status NetworkManager
# 预期:Active: active (running) since ...

# 4. 开机自启的服务
systemctl list-unit-files --state=enabled --type=service
# 输出一长串,常见:NetworkManager, gdm/sddm, bluetooth

# 5. sshd 状态
systemctl status sshd
# 可能:Unit sshd.service could not be found(没装 openssh)

# 6. 装 htop
sudo pacman -S htop
# 输出:resolving dependencies... looking for conflicting packages...
# Packages (1): htop-3.x.x-x
# Total Installed Size: 0.50 MiB
# :: Proceed with installation? [Y/n] 按 y

# 7. 跑 htop
htop
# 看进程列表,F6 排序,q 退出

# 8. 创建 dev 用户
sudo useradd -m -G wheel -s /bin/bash dev
# -m 创建 home 目录, -G wheel 加到 wheel 附加组, -s 指定 shell
echo "dev:dev123" | sudo chpasswd
# chpasswd 从 stdin 读 "用户名:密码" 设密码

# 9. 切换并验证
su - dev
# 提示密码,输 dev123
sudo ls /root
# 提示输 dev 的密码,然后列出 /root
exit  # 退回原用户

# 10. 删用户
sudo userdel -r dev
# -r 连 home 一起删
```

**关键参数解释**:
- `pacman -Q` 查本地数据库(已装的包),`-S` 是和远端仓库同步
- `systemctl list-unit-files --state=enabled` 列出开机自启(unit file 被 symlink 到 multi-user.target.wants 的)
- `useradd -m`:**没有** `-m` 不创建 home 目录,新用户登入会报错
- `chpasswd`:非交互式改密码,适合脚本
- `userdel -r`:`-r` 删 home 和 mail spool,不加只删账号记录

### Lv3 · 迁移设计

**题**:你的 Rust 项目跑成了一个 server,你想让它:
1. 开机自启
2. 挂了自动重启
3. 日志写到 `/var/log/myserver.log`(而不是 journal)

请写一个完整的 systemd unit 文件(`/etc/systemd/system/myserver.service`),并给出启动它的命令序列。

**提示**:
- `[Unit]` 段写描述和依赖
- `[Service]` 段写 `ExecStart=`(启动命令)、`Restart=always`(挂了重启)、`StandardOutput=file:/path`、`User=`
- `[Install]` 段写 `WantedBy=multi-user.target`(开机到多用户模式就启动)
- 启动序列:`systemctl daemon-reload` → `systemctl enable --now myserver`

### Lv4 · 开源贡献

**题**:Arch Linux 的官方包仓库 `core / extra / multilib` 里**所有包的 PKGBUILD 脚本**都在 GitLab:https://gitlab.archlinux.org/archlinux/packaging/packages/

1. 选一个你用的 Rust 写的包(比如 `ripgrep`, `fd`, `bat`, `exa`, `tokei`)
2. 找到它在 GitLab 的 PKGBUILD(搜 `packages/ripgrep`)
3. 读 PKGBUILD,看 Arch 打包一个 Rust 项目要做哪些事:`cargo build --release`、`cargo install --root`、`install -D` 装到 `/usr/bin/` 等
4. 如果发现 PKGBUILD 里依赖列表过时、注释 typo、URL 过期,**这就是一个真实的 PR 机会**
5. 写下你的 PR 描述

## 8 · Rust / Arch 落地代码

### 装机必备命令

```bash
# 0. 更新整个系统(每次装新东西前必做)
sudo pacman -Syu
# 输出示例:
# :: Synchronizing package databases...
#  core                               124.0 KiB  5.23 MiB/s
#  extra                             1856.0 KiB  8.10 MiB/s
# :: Starting full system upgrade...
# resolving dependencies...
# looking for conflicting packages...
# Packages (15) ... will be upgraded

# 1. 装基础开发工具
sudo pacman -S --needed base-devel git rustup neovim \
                          ripgrep fd fzf bat tmux htop \
                          openssh openssl

# 各是什么:
# base-devel     - gcc/make/fakeroot 等(编译 AUR 需要)
# git            - 版本控制
# rustup         - Rust 版本管理器(下一篇细讲)
# neovim         - 终端编辑器
# ripgrep/fd     - grep/find 现代替代
# fzf            - 模糊查找
# bat            - cat 增强版
# tmux           - 终端多路复用器
# htop           - 进程监视
# openssh        - SSH 客户端和服务端
# openssl        - TLS 库(很多工具依赖)

# 2. 装 AUR helper(paru)
# AUR 包不能用 pacman 装,需要先 git clone 再 makepkg
# paru 自动化了这流程
sudo pacman -S --needed paru
# 如果官方源没有 paru,手动:
# git clone https://aur.archlinux.org/paru-bin.git
# cd paru-bin && makepkg -si

# 3. 配置 pacman:开启 Color 和 ILoveCandy(吃豆人进度条)
sudo sed -i 's/^#Color/Color/; s/^#ParallelDownloads = 5/ParallelDownloads = 10/' /etc/pacman.conf
# sed -i 直接编辑文件
# s/^#Color/Color/  把行首的 #Color 改成 Color(去掉注释)
# ParallelDownloads = 10  开启 10 线程并发下载

# 4. 配置 fastest mirror(用 reflector)
sudo pacman -S reflector
sudo reflector --latest 20 --protocol https --sort rate --save /etc/pacman.d/mirrorlist
# 取最近 20 个 https 镜像,按速度排序,写到 mirrorlist
```

### systemd 服务管理实战

```bash
# 看所有运行中的服务
systemctl list-units --type=service --state=running
# 输出:UNIT              LOAD   ACTIVE SUB     DESCRIPTION
# NetworkManager.service loaded active running Network Manager
# gdm.service           loaded active running GNOME Display Manager
# ...

# 看某服务详情
systemctl status NetworkManager
# 输出:
# ● NetworkManager.service - Network Manager
#      Loaded: loaded (/usr/lib/systemd/system/NetworkManager.service; enabled)
#      Active: active (running) since ... ago
#        Docs: man...
#    Main PID: 1234 (NetworkManager)
#         ...
# 最近 10 行日志

# 重启某服务
sudo systemctl restart NetworkManager

# 开机自启 / 关闭自启
sudo systemctl enable sshd       # 下次开机自启
sudo systemctl disable sshd
sudo systemctl enable --now sshd # 立即启动 + 开机自启

# 服务挂了自动重启(unit 文件里设 Restart=always)
# 看 /usr/lib/systemd/system/sshd.service 学习写法
```

### journalctl 日志查询

```bash
# 看所有日志(按时间倒序)
journalctl
# 按 End 跳到最新, q 退出

# 实时追踪(像 tail -f)
journalctl -f

# 看某服务的日志
journalctl -u sshd
journalctl -u NetworkManager --since "1 hour ago"

# 只看错误
journalctl -p err
# 优先级:emerg(0) alert(1) crit(2) err(3) warning(4) notice(5) info(6) debug(7)

# 看本次启动以来的日志
journalctl -b

# 看上次启动的日志(系统挂了重启后排查)
journalctl -b -1

# 输出 JSON(适合脚本处理)
journalctl -u sshd -o json

# 找包含关键词的日志
journalctl | grep "Failed password"
```

### 用户和权限

```bash
# 看当前用户
whoami           # 你的用户名
id               # 你的 uid, gid, 组列表
# 输出示例:uid=1000(sun) gid=1000(sun) groups=1000(sun),998(wheel)

# 看所有用户
cat /etc/passwd | cut -d: -f1,3,7
# 格式:用户名:UID:shell
# root 一般是 0,普通用户 1000+

# 创建新用户
sudo useradd -m -G wheel -s /bin/bash alice
# -m 创建 /home/alice
# -G wheel 把 alice 加入 wheel 附加组(可 sudo)
# -s 指定登录 shell

# 设密码
sudo passwd alice
# 提示输入两次密码

# 改密码(自己改,不要 sudo)
passwd

# 把用户加到某组(附加)
sudo gpasswd -a alice video   # 让 alice 能访问 /dev/video*

# 删用户
sudo userdel -r alice

# 看 sudo 权限配置
sudo cat /etc/sudoers
# 关键行:%wheel ALL=(ALL:ALL) ALL
# 意思:wheel 组成员能在任何主机以任何用户跑任何命令

# 推荐:用 visudo 编辑 sudoers(它有语法检查)
sudo visudo
```

### 排错实战

```bash
# 故障 1: pacman 报 "failed to commit transaction (conflicting files)"
# 原因:某文件被多个包要求,或上次装包没装完
# 解决:看具体冲突文件,大概率是 /usr/lib/xxx 被旧文件占了
sudo pacman -Syu --overwrite '*'  # 强制覆盖(谨慎)

# 故障 2: systemctl start xxx 报 "Failed to start xxx.service: Unit xxx.service not loaded"
# 原因:unit 文件不在 systemd 搜索路径
# 解决:确认文件在 /etc/systemd/system/ 或 /usr/lib/systemd/system/
# 然后跑 daemon-reload:
sudo systemctl daemon-reload

# 故障 3: journalctl 里看到服务挂了反复重启
# 原因:Restart=always + 启动命令本身报错
# 解决:看完整日志定位
journalctl -u xxx -n 100 --no-pager

# 故障 4: "error: keyring is not writable"
# 原因: pacman-key 状态坏了
sudo pacman-key --init
sudo pacman-key --populate archlinux

# 故障 5: 没声音
# 看 pipewire 状态
systemctl --user status pipewire pipewire-pulse wireplumber
# 如果 inactive,启动它们:
systemctl --user enable --now pipewire pipewire-pulse wireplumber
```

## 9 · 延伸阅读(可选补充,非必需)

本仓库本地:
- [00-terminal-basics.md](00-terminal-basics.md) — 终端基础(前置)
- [07-linux-filesystem.md](07-linux-filesystem.md) — 文件系统(`/etc`, `/var` 的角色)
- [08-processes-and-signals.md](08-processes-and-signals.md) — systemd 起的 service 就是进程

外部稳定 URL:
- Arch Wiki Installation guide:https://wiki.archlinux.org/title/Installation_guide
- Arch Wiki pacman:https://wiki.archlinux.org/title/Pacman
- Arch Wiki systemd:https://wiki.archlinux.org/title/Systemd
- Arch Wiki Users and groups:https://wiki.archlinux.org/title/Users_and_groups
- systemd 官方手册:https://www.freedesktop.org/wiki/Software/systemd/
- man pages(本地可跑):`man pacman`, `man systemctl`, `man journalctl`, `man useradd`

真实开源源码:
- pacman 源码(GitLab):https://gitlab.archlinux.org/pacman/pacman
- systemd 源码(GitHub):https://github.com/systemd/systemd
- AUR PKGBUILD 仓库:https://aur.archlinux.org/
