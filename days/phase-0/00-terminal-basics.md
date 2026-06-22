---
article: 00
phase: 0
title: "终端基础:shell 是怎么工作的"
type: setup
difficulty: 1
duration: "1-2h"
domains: [linux]
prereqs: []
---

# 00 · 终端基础:shell 是怎么工作的

> 这份教程假设你会用鼠标点击图标打开程序。从这一篇开始,我们要让你**用键盘告诉电脑做事**——这就是终端 / shell。它是开源极客吃饭的家伙,学不会它,后面 666 天都走不动。

## 0 · 为什么要有这一天

你装好了 Arch Linux(下一篇讲怎么装),登录桌面,看到一个图形界面。你点击文件夹图标打开文件管理器,看到 `home` 文件夹,双击进入,再双击 `Documents`,找到你想看的文件,双击打开。

这一串操作没问题,但有几个硬伤:

1. **慢**:每次"打开文件夹 → 找文件 → 双击"至少 3 次点击,键盘一次回车就行
2. **无法自动化**:你想把 100 张图片从 `Downloads/` 移到 `Pictures/vacation/`,GUI 要点 100 次;终端一行命令搞定
3. **无法远程**:你 SSH 到服务器,没有 GUI,只有终端。不会终端就不会用服务器
4. **看不见过程**:GUI 把命令藏起来,你不知道"双击"背后调了什么;终端完全透明,你能学到底层
5. **开源协作靠它**:所有开源项目的 README 都假设你会在终端跑命令(`cargo build`, `git clone`, `make install`)。不会终端,你连文档都读不懂

终端不是"老古董用的",它是**和电脑说话最精确、最快、最透明的方式**。一旦你熟练了,你会发现 GUI 是给"不想懂电脑的人"用的。

**心理锚点**:这一篇读完,你能:
- 在终端里去任何文件夹(目录)
- 创建 / 删除 / 复制 / 移动文件
- 用管道把几个命令串起来做事
- 用 vim 在终端里改文件(必学,后面改配置文件全靠它)
- 看懂别人 README 里的命令在做什么

## 1 · 概念地图:终端、Shell、控制台、TTY 是什么

新手最容易混的几个词:

| 词 | 是什么 | 类比 |
|---|---|---|
| **终端(Terminal)** | 一个程序,提供"输入字符 + 显示字符"的窗口 | 一个屏幕 + 键盘的模拟器 |
| **Shell** | 真正理解你输入的命令的程序(bash / zsh / fish) | 一个翻译官,把你说的"翻译"给内核 |
| **控制台(Console)** | 整个屏幕全屏的终端(Linux 有 6 个虚拟控制台,Ctrl+Alt+F1~F6 切换) | 物理意义上"接在电脑上的"终端 |
| **TTY** | 终端的设备文件(`/dev/tty1` 等) | 内核给每个终端的一个"门牌号" |

**关键**:你打开的"Terminal" 应用,实际上是一个**终端模拟器**(GNOME Terminal / Konsole / Alacritty / Kitty),它模拟物理终端的行为,在里面跑一个 shell(bash / zsh)。

Arch Linux 默认 shell 是 **bash**(Bourne Again Shell,大部分 Linux 默认)。你可能听过 zsh(macOS 默认)或 fish。本教程用 bash,但 zsh 命令 95% 一样。

## 2 · 心智模型

### 类比:shell 是"管道工"

想象你站在一栋大楼的控制室。墙上有 100 个按钮(命令),每个按钮管一件具体的事:
- 按下"开灯"按钮 → 灯亮
- 按下"调温到 22°C"按钮 → 空调动作
- 按下"关窗帘"按钮 → 窗帘关

但有些按钮可以**串起来**:按"读温度"按钮出来的数字,可以接到"调温"按钮上,让目标温度自动等于当前温度 + 2 度。这就是**管道(pipe)**——把一个命令的输出接到另一个命令的输入。

shell 就是这个控制室的操作员。你输入命令,它执行。每个命令都是一个**独立的小程序**(`ls` 是一个程序,`cd` 是 shell 内置命令,`cp` 又是一个程序),shell 帮你调度。

### 命令的本质:程序 + 参数

```bash
ls -l /home/sun
```

- `ls` — 程序名(在 `/usr/bin/ls`)
- `-l` — 选项(option),告诉 ls 用"long format"输出
- `/home/sun` — 参数(argument),告诉 ls 列哪个目录

通用模板:`命令 [选项] [参数]`。选项一般以 `-` 开头(短选项单字母,如 `-l`)或 `--` 开头(长选项,如 `--all`)。

`ls --help` 几乎所有命令都支持,打印简短帮助。`man ls` 打印完整手册(q 退出)。

## 3 · 四域深入

### 3.1 · 🐧 Linux 系统编程视角

shell 不是魔法,它就是一个**读命令、找程序、运行程序**的程序。简化版的 shell 用 Rust 写出来大概这样:

```rust
use std::io::{self, BufRead, Write};
use std::process::Command;

fn main() {
    let stdin = io::stdin();
    let mut stdout = io::stdout();
    loop {
        // 1. 显示提示符
        print!("$ ");
        stdout.flush().unwrap();
        // 2. 读一行
        let mut line = String::new();
        if stdin.lock().read_line(&mut line).unwrap() == 0 { break; }
        let line = line.trim();
        if line.is_empty() { continue; }
        // 3. 解析(简化版:用空格分)
        let mut parts = line.split_whitespace();
        let cmd = parts.next().unwrap();
        let args: Vec<&str> = parts.collect();
        // 4. 内置命令:cd
        if cmd == "cd" {
            let dir = args.first().copied().unwrap_or("/");
            std::env::set_current_dir(dir).ok();
            continue;
        }
        // 5. 外部命令:fork+exec
        let status = Command::new(cmd).args(&args).status();
        match status {
            Ok(s) if !s.success() => eprintln!("exit code: {:?}", s.code()),
            Err(e) => eprintln!("error: {}", e),
            _ => {}
        }
    }
}
```

**每行解释**:
- `stdin.lock().read_line(&mut line)` — 从标准输入读一行,存到 `line`。返回读取的字节数,0 表示 EOF(用户按 Ctrl+D)
- `std::env::set_current_dir(dir)` — 改变当前进程的工作目录,这就是 `cd` 在做的事
- `Command::new(cmd).args(&args).status()` — fork 一个子进程,执行 `cmd`,等它结束
- `cd` 是**内置**的——因为它要改变的是 shell 自己的工作目录,而外部程序无法改 shell 的目录(子进程改不了父进程的)

真正的 bash 比这复杂 100 倍(管道、重定向、变量、if/for/while、函数、通配符、job control……),但**核心就是这个 loop**:提示符 → 读 → 解析 → 执行 → 循环。

这就是为什么 shell 能存在 50 年——它抓住了一个根本抽象:**用文本和程序交互**。

### 3.2 · 🦀 Rust 生态视角

Rust 标准库提供了所有写 shell 需要的原语:
- `std::process::Command` — fork+exec 的封装
- `std::os::unix::process::CommandExt` — Unix 特定扩展(setsid, uid, env clear)
- `std::io` — stdin/stdout/stderr

著名的 Rust shell 实现:
- **nushell** — 数据感知 shell,命令输出结构化数据(不是文本)
- **ion** — Redox OS 的 shell,纯 Rust
- **elfshell** — 极简教学用

如果你以后想给开源 shell 项目贡献代码,读 nushell 源码是绝佳起点:https://github.com/nushell/nushell

## 4 · 认知地图

### 4.1 上级

- **Unix 哲学** — "每个程序做好一件事;用文本流连接程序"(Ken Thompson, 1970s)
- **REPL** — Read-Eval-Print Loop,交互式语言环境。shell 是 REPL 的一种
- **作业控制(Job Control)** — 后台 / 前台进程、信号、终端会话

### 4.2 同级

| 工具 | 关键差别 | 何时用 |
|---|---|---|
| bash | POSIX 标准,Linux 默认 | 通用脚本、所有 Linux 都有 |
| zsh | 更智能的自动补全、globbing | 交互式用(macOS 默认) |
| fish | 开箱即用,不兼容 POSIX | 新手友好(但脚本不通用) |
| nushell | 数据感知,结构化输出 | 数据处理 |
| PowerShell | 微软出品,对象管道 | Windows |

本教程用 bash,但你装 zsh 也行(本篇结尾会讲怎么装)。

### 4.3 下级

- **核心命令**:`cd`, `ls`, `pwd`, `mkdir`, `rm`, `cp`, `mv`, `cat`, `less`, `grep`, `find`
- **管道与重定向**:`|`, `>`, `<`, `>>`, `2>`, `2>&1`
- **变量**:`export`, `$VAR`, `${VAR:-default}`
- **作业控制**:`&`, `jobs`, `fg`, `Ctrl+Z`, `Ctrl+C`
- **shell 配置**:`~/.bashrc`, `~/.zshrc`
- **终端模拟器**:GNOME Terminal, Alacritty, Kitty, WezTerm

## 5 · 对照与变奏

### 同一任务的不同做法:找文件

| 工具 | 命令 | 优点 |
|---|---|---|
| `find` | `find . -name "*.rs"` | POSIX 标准,所有 Unix 都有 |
| `fd` (modern) | `fd -e rs` | 快(并行)、默认忽略 .gitignore、彩色输出 |
| `ripgrep` (内容搜索) | `rg "fn main"` | 极快,默认递归,默认忽略 .gitignore |
| `fzf` | `fzf` | 交互式模糊查找 |

老一代用 find / grep,新一代用 fd / ripgrep。Casey 视频里用 find / grep(时代限制),你跟做时建议装 fd / ripgrep,效率高 10 倍。

### GUI vs CLI:复制 100 张图片

GUI:
1. 打开 Downloads
2. 框选 100 张图(可能漏选)
3. Ctrl+C
4. 切换到 Pictures/vacation
5. Ctrl+V
6. 等进度条
共:~30 秒 + 易错

CLI:
```bash
mv ~/Downloads/*.jpg ~/Pictures/vacation/
```
共:3 秒 + 不会漏

这就是为什么"会用终端的人比不会用的人效率高 10 倍"。

## 6 · 关联 Day

- **铺垫**(本篇是 phase-0 第一篇,没有前置)
- **当天**:[00-terminal-basics.md](00-terminal-basics.md)(本篇)
- **后续**:
  - [01-arch-setup.md](01-arch-setup.md) — Arch 配置(假设你会终端基础)
  - [02-git-and-github.md](02-git-and-github.md) — git 命令行
  - [03-rust-from-scratch-1.md](03-rust-from-scratch-1.md) — `cargo` 命令行
  - [07-linux-filesystem.md](07-linux-filesystem.md) — 文件系统深入

## 7 · 变式训练

### Lv1 · 概念辨析

**题**:shell、terminal、shell script 三个概念有什么区别?用一个生活类比说清。

**参考解答**:
- **terminal**(终端)= 钢琴。是个硬件 / 软件壳子,提供"输入 + 输出"接口
- **shell** = 一种钢琴谱的演奏法(bash / zsh 是不同的演奏家)。是 terminal 里跑着的、真正理解你输入的程序
- **shell script** = 一份乐谱(`.sh` 文件)。是预先写好的命令序列,给 shell 一次性演奏

你可以换个 shell(从 bash 换 zsh),terminal 不变;你也可以换个 terminal(从 GNOME Terminal 换 Alacritty),shell 不变;同一个 shell 能跑成千上万不同的 script。

### Lv2 · 动手实践

**题**:在你的 Arch Linux 上完成下列任务,每步用一条命令:

1. 打开 terminal(任何终端模拟器都行)
2. 看你现在在哪个目录(应该输出 `/home/<你的用户名>`)
3. 列出当前目录所有文件(包括隐藏文件,文件名以 `.` 开头的)
4. 创建一个目录叫 `playground`
5. 进入 `playground`,创建一个空文件 `hello.txt`
6. 用 `echo` 把字符串 `Hello, terminal!` 写到 `hello.txt` 里
7. 用 `cat` 读 `hello.txt`,确认内容正确
8. 把 `hello.txt` 复制成 `hello.bak.txt`
9. 列出当前目录,应该有两个文件
10. 删除 `hello.txt`,只剩 `hello.bak.txt`
11. 回到上一级目录(用 `cd ..`)
12. 删除整个 `playground` 目录(用 `rm -r playground`)
13. 用 `ls playground` 确认它不存在了(应该报错)

完成标准:每步独立完成,不抄答案。

**参考解答**(命令清单,你自己先试):

```bash
pwd
ls -la
mkdir playground
cd playground
touch hello.txt
echo "Hello, terminal!" > hello.txt
cat hello.txt
cp hello.txt hello.bak.txt
ls
rm hello.txt
cd ..
rm -r playground
ls playground  # 应该报 No such file or directory
```

**关键参数解释**:
- `ls -la`:`-l` 是 long format(详细),`-a` 是 all(包括隐藏)
- `>` 是**重定向**:把命令的标准输出写到文件里(覆盖)
- `>>` 也是重定向,但是追加
- `rm -r`:`-r` 是 recursive(递归),删目录必须用,否则报错
- `cd ..`:`..` 是父目录,`.` 是当前目录

### Lv3 · 迁移设计

**题**:你要把一个项目里所有 `.rs` 文件里包含 `TODO` 的行提取出来,按文件名分组,存到一个文件 `todos.txt`。你怎么用一行命令(可以用管道 `|`)做?

**提示**:
- `grep -rn` 递归搜索并打印文件名 + 行号
- `sort` 排序
- `>` 重定向到文件

写出完整命令,然后想:这命令的每一段在做什么?

### Lv4 · 开源贡献

**题**:`ripgrep` 是 Rust 写的极快 grep 替代品,GitHub: https://github.com/BurntSushi/ripgrep

1. 装它:`sudo pacman -S ripgrep`(Arch)
2. 读它的 README,知道它和 grep 的差别
3. 用 `rg "TODO" --vimgrep` 找当前目录所有 TODO,看看输出格式
4. **可能的贡献方向**:
   - ripgrep 的 `--help` 长但晦涩,找一个你觉得没解释清楚的选项,在 doc 里补一段说明
   - ripgrep 的 issues 列表找 `good first issue` 标签的 issue,认领一个
   - 翻 `crates/regex-syntax/` 的源码,看正则引擎是怎么实现的,如果你发现某个公开 API 的 doc comment 有 typo,提 PR 修
5. 写下你的 PR 描述(repo URL / 改动文件 / 动机 / 验证)

## 8 · Rust / Arch 落地代码

### 安装和配置

```bash
# 1. 更新系统(每次装新软件前都先做这个)
sudo pacman -Syu
# 输出:starting full system upgrade... 
# resolving dependencies... looking for conflicting packages...
# Packages (X) xxx will be installed, Y will be upgraded
# Total download size: XXX MiB

# 2. 装必备终端工具
sudo pacman -S --needed bash bash-completion coreutils findutils grep sed \
                          less vim neovim git ripgrep fd fzf bat tmux

# 各是什么:
# bash              - shell 本体
# bash-completion   - bash 自动补全(Tab 键触发)
# coreutils         - ls/cp/mv/rm/cat/mkdir 等基础命令
# findutils         - find/xargs
# grep              - 文本搜索
# sed               - 流编辑器(批量替换)
# less              - 分页查看长文件
# vim / neovim      - 终端编辑器(必学)
# git               - 版本控制(下一篇讲)
# ripgrep / fd      - 现代版 grep / find(快 10 倍)
# fzf               - 模糊查找 Ctrl+R 历史命令
# bat               - cat 的彩色增强版
# tmux              - 终端多路复用器

# 3. 看看你的 shell 是什么
echo $SHELL
# 输出:/bin/bash(默认)

# 4. 看当前用户、主机、目录
whoami    # 你的用户名
hostname  # 你的电脑名
pwd       # 当前目录

# 5. 配置 bash 让它更顺手
# 编辑 ~/.bashrc,加几行 alias(简写):
cat >> ~/.bashrc << 'EOF'

# 我的 alias
alias ll='ls -lah'
alias ..='cd ..'
alias ...='cd ../..'
alias gs='git status'
alias gd='git diff'
alias cat=bat
alias vim=nvim
EOF

# 6. 让配置生效
source ~/.bashrc

# 7. 测试
ll    # 应该列出当前目录详细信息
```

### vim / neovim 基础(必学,5 分钟入门)

后面改配置文件、写代码、看代码都用 vim。最少要会:

```
打开文件:    nvim 文件名
退出:        :q (无修改) / :q! (强制退出) / :wq (保存退出)
进入插入模式: i (光标前插入) / a (光标后插入)
退出插入模式: Esc
保存:        :w
移动:        h j k l (左 下 上 右)
删除:        dd (删整行) / x (删一个字符)
撤销:        u
重做:        Ctrl+r
搜索:        /关键词 然后 Enter,n 下一个,N 上一个
跳到行首:    0
跳到行尾:    $
跳到文件头:  gg
跳到文件尾:   G
```

这 12 个动作够你做 80% 的事。后面想深入,跑 `vimtutor` 命令(自带教程,30 分钟)。

### Arch 特殊:Tmux / Screen

如果远程 SSH 工作,网络一断你的命令就死了。`tmux` 让你的会话不依赖 SSH:

```bash
sudo pacman -S tmux

# 开始一个命名会话
tmux new -s work

# 在里面跑命令...
# 按 Ctrl+B 然后 D,离开会话(它继续跑)

# 列出会话
tmux ls

# 回到会话
tmux attach -t work
```

这套技能在后面跑长时间构建、远程开发时救命。

## 9 · 延伸阅读(可选补充,非必需)

本仓库本地:
- [01-arch-setup.md](01-arch-setup.md) — Arch 配置(下一篇)
- [phase-0/README.md](README.md) — 起步营总览

外部稳定 URL:
- The Linux Command Line (William Shotts)免费书:https://linuxcommand.org/tlcl.php
- Arch Wiki Bash:https://wiki.archlinux.org/title/Bash
- Learn Vim Progressively:https://yannesposito.com/Scratch/en/blog/Learn-Vim-Progressively/
- Vim Adventures(游戏化学 vim):https://vim-adventures.com/

真实开源源码:
- bash 源码(GNU):https://git.savannah.gnu.org/cgit/bash.git
- nushell 源码:https://github.com/nushell/nushell(用 Rust 写的现代化 shell)
