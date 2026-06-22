---
article: 02
phase: 0
title: "Git 和 GitHub:fork → clone → branch → commit → PR 全流程"
type: setup
difficulty: 2
duration: "2-3h"
domains: [linux, rust]
prereqs: ["00-terminal-basics", "01-arch-setup"]
---

# 02 · Git 和 GitHub:fork → clone → branch → commit → PR 全流程

> 开源极客吃饭的家伙不是某个 IDE,是 Git。整个 Rust 生态、Linux 内核、Handmade Hero 的代码、本教程本身,都是用 Git 管理的。学会 Git 你才能 fork 一个项目、改一行代码、把改动发回去(PR)。这是开源协作的基本动作。

## 0 · 为什么要有这一天

你写代码,改来改去。如果不用版本控制,你会遇到:

1. **改坏了回不去**:你删了一段代码,半小时后发现还需要。打开编辑器,翻撤销……翻不到了。
2. **不知道每个版本改了什么**:`main.c`、`main_v2.c`、`main_v2_final.c`、`main_v2_final_REALLY_FINAL.c`。哪个是哪个?
3. **没法多人协作**:两个人同时改同一个文件,谁覆盖谁?
4. **没法分享**:你的代码在本地,别人看不到。怎么发给别人?发邮件附件?
5. **没法 review**:别人给你改了一行,你要逐字对比,容易漏

Git 解决所有这些问题。它是一个**时间机器 + 协作中枢**:

- **时间机器**:每次 commit 都是一个存档点,你可以随时回到任何存档
- **协作中枢**:GitHub / GitLab 是基于 Git 的"代码云盘",你 push 上去全世界都能拉

**心理锚点**:读完这一篇,你能:
- fork 一个 GitHub 项目到自己账号下
- clone 到本地,改一行,commit,push
- 开一个 PR(Pull Request),等 review,merge
- 看懂任何开源项目的 git workflow
- 解决最常见的 merge conflict

## 1 · 概念地图:Git / GitHub / 仓库 / 分支

新手最困惑的几个词:

| 词 | 是什么 | 类比 |
|---|---|---|
| **Git** | 一个**本地**版本控制程序(装在你电脑上) | 一个会记日记的笔记本 |
| **GitHub** | 一个托管 Git 仓库的**网站**(云服务) | 笔记本的云端同步服务 |
| **仓库(repository / repo)** | 一个被 Git 管理的项目目录(有 `.git/` 子目录) | 一本完整的日记本 |
| **commit** | 一次"存档",记录所有改动的快照 | 日记的一条目 |
| **branch(分支)** | 一条平行的开发线 | 日记的另一支线(可合并回主线) |
| **HEAD** | 当前所在位置的指针(指向某 branch / commit) | 你正在写的那一页书签 |
| **remote(远端)** | 远程服务器上的副本(GitHub 上的那个) | 云端的同步副本 |
| **origin** | 默认 remote 的名字 | 默认云盘 |
| **fork** | 在 GitHub 上把别人的 repo 复制一份到自己账号 | 把别人的笔记本复印到自己家 |
| **clone** | 把 repo 从远端拉到本地 | 从云盘下载到本地 |
| **push** | 本地 commit 推到远端 | 上传到云盘 |
| **pull** | 远端新 commit 拉到本地 | 从云盘下载 |
| **PR(Pull Request)** | "请把我的改动合并到你的 repo"的请求 | 把你的日记交给原作者审阅 |

**Git 是程序,GitHub 是网站**:你可以只用 Git 不用 GitHub(把 repo 放自己硬盘或自己服务器),但几乎所有开源项目都在 GitHub。除了 GitHub 还有 GitLab、Codeberg、Gitea——协议都是 Git,网站不同。

## 2 · 心智模型

### 费曼类比:Git 是"三棵树 + 一本日记"

Git 的工作流可以理解为三个区域:

```
   工作目录(Working Directory)
   ↓ git add
   暂存区(Staging Area / Index)
   ↓ git commit
   本地仓库(Local Repository, .git/)
   ↓ git push
   远端仓库(Remote / GitHub)
```

- **工作目录**:你眼睛看到的文件夹。你改文件、删文件,改的就是这里
- **暂存区**:Git 维护的一个清单,记录"下次 commit 要带上哪些改动"。`git add` 把工作目录的改动加到这个清单
- **本地仓库**:所有 commit 的存档库,在 `.git/` 隐藏目录里
- **远端仓库**:在 GitHub 服务器上的副本

为什么要有"暂存区"这一层?**因为你可能改了 5 个文件,但只想 commit 其中 3 个**。`git add` 让你精确控制每个 commit 包含什么。

### commit 是什么:不是 diff,是快照

很多人以为 commit 存的是"和上一个 commit 的差异"(diff)。**错**。Git 的每个 commit 存的是**项目在该时刻的完整快照**——所有文件的当前状态。

为了省空间,Git 内部对没变的文件存的是引用(指针),变的文件存新内容。但**逻辑上**每个 commit = 一个完整的项目状态。

每个 commit 有:
- **SHA-1 hash**(40 字符,如 `a1b2c3d4...`):该 commit 的唯一 ID
- **parent**:上一个 commit 的 hash(形成链)
- **作者、时间、message**
- **一棵文件树(tree)**:这次快照里所有文件的内容哈希

你可以把 HEAD 想象成一个移动的指针,每 commit 一次,它往前走一格。`git checkout <hash>` 能让指针回到任何历史位置。

### branch 是什么:一个会移动的标签

branch 不是"另一份代码副本",它就是**一个指向某 commit 的指针**。`main` 是一个指针,`feature-x` 是另一个指针。它们指向同一个 commit 时就是"同一棵树"。

```
commit1 ← commit2 ← commit3  ← main (现在)
                            ← feature-x(也在 commit3)
```

你 `git checkout feature-x; git commit` 后:

```
commit1 ← commit2 ← commit3 ← main
                            ← commit4 ← feature-x
```

`main` 没动,`feature-x` 往前走了。**就这么简单**。Git 的 branch 创建/删除极快,因为只是改个指针。

### merge vs rebase

两条 branch 要合并,有两种方式:

**merge**:保留两条线,创建一个"合并 commit",有两个 parent。

```
A---B---C  main
     \
      D---E  feature
合并后:
A---B---C---F  main(F 是 merge commit,parent 是 C 和 E)
     \     /
      D---E
```

**rebase**:把 feature 的 commit "搬到" main 最新 commit 后面,变成一条直线。

```
A---B---C  main
     \
      D---E  feature
rebase 后:
A---B---C---D'---E'  main + feature 一条线
```

- merge:历史完整,但图形复杂
- rebase:历史清爽,但 commit 的 hash 变了(等于新 commit)

经验法则:**个人 branch 用 rebase,合到 main 用 merge**。但每个团队约定不同。

### fork vs clone vs branch

新手最容易混的:

- **clone**:任何人 clone 任何 repo,只要你有读权限。clone 后你**有完整本地副本**
- **fork**:在 GitHub 网站上,把别人的 repo 复制一份到**你的 GitHub 账号**下。fork 后你**对副本有写权限**
- **branch**:在你**有写权限的** repo(自己 fork 的、或团队的)里开新分支

如果你想给 `rust-lang/rust` 贡献代码,你不能直接 push(你没权限)。流程是:
1. fork `rust-lang/rust` 到 `你的名字/rust`(有写权限)
2. clone 你的 fork 到本地
3. 开 branch,改代码,commit
4. push 到你的 fork(`origin`)
5. 在 GitHub 网站点"New Pull Request",请求把你的 branch 合到 `rust-lang/rust` 的 main
6. 等 reviewer 审核,他们 merge 后你的改动就进了原 repo

这就是**开源贡献的标准流程**,必须练熟。

## 3 · 四域深入

### 3.1 · 🐧 Linux 系统编程视角

Git 底层是文件系统。`.git/` 目录的结构:

```
.git/
├── HEAD           # 当前指向哪个 ref:ref: refs/heads/main
├── config         # 本 repo 配置(用户名、remote URL)
├── refs/
│   ├── heads/     # 本地 branch:每文件一个,内容是该 branch 的 commit hash
│   │   └── main   # 例如内容:a1b2c3d4...
│   ├── remotes/   # 远端 branch
│   │   └── origin/
│   │       └── main
│   └── tags/      # 标签(release 版本)
├── objects/       # 所有 commit / tree / blob / tag 对象,用 SHA 哈希命名
│   ├── a1/
│   │   └── b2c3d4...  # 文件名是 SHA 的后 38 位
│   └── pack/      # 打包后的大文件(节省空间)
├── logs/          # reflog(HEAD 历史)
└── index          # 暂存区(二进制)
```

每个 object 是 zlib 压缩的。object 有 4 种:

- **blob**:文件内容
- **tree**:目录结构(列出文件名 + blob hash)
- **commit**:一次提交(tree hash + parent + author + message)
- **tag**:带注释的标签

Git 的所有操作本质是:读写 `.git/` 里的文件。你可以用 `git cat-file -p <hash>` 看任何 object 内容:

```bash
git cat-file -p HEAD
# 输出:
# tree 3a7b8c9...
# parent 1f2e3d4...
# author Sun <sun@example.com> 1700000000 +0800
# committer Sun <sun@example.com> 1700000000 +0800
#
#    my commit message
```

Git 的核心是一个**内容寻址存储(content-addressable storage)**:对象的"地址"就是它内容的 SHA 哈希。改一点内容,哈希完全变。

### 3.2 · 🦀 Rust 生态视角

Rust 项目就是 Git repo。每个 Rust crate 在 crates.io 上都有一个对应的 GitHub repo。`cargo` 和 Git 协作:

- `Cargo.toml` 里可以写 `version = "1.0"`(从 crates.io 拉)或 `git = "https://..."`(直接从 Git 拉)
- `Cargo.lock` 锁定每个依赖的具体版本
- `.gitignore` 里 Rust 项目一般写:
  ```
  /target       # cargo build 产物,体积巨大
  **/*.rs.bk    # rustfmt 备份
  Cargo.lock    # 如果是 library(让用户决定版本);如果是 binary,应该 commit
  ```

**Library vs Binary 的 Cargo.lock 争议**:Rust 官方建议——library 不 commit Cargo.lock(因为下游会用不同依赖版本),binary commit(确保构建可重现)。这条规则很多新手不知道,会引发 PR 被 reject。

著名的 Rust Git 工具:
- **git2-rs**(libgit2 绑定):用 Rust 操作 Git repo
- **cargo-edit** / **cargo-update**:用 Git 协作管理依赖
- **cargo-deny**:CI 里检查 license / 安全漏洞

## 4 · 认知地图

### 4.1 上级

- **版本控制(Version Control System, VCS)** — 记录文件随时间的变化,可回到任何历史点。Git 是 VCS 的一种
- **分布式版本控制** — 每个 clone 都是完整仓库,可以离线工作,无中心点单点故障。Git 是 DVCS
- **社交编程** — GitHub 在 Git 之上加了 issue / PR / wiki / Actions,把版本控制变成社交平台

### 4.2 同级

| 系统 | 关键差别 | 何时用 |
|---|---|---|
| Git | 分布式,极快,主流 | 99% 场景 |
| Mercurial (hg) | 分布式,Python 写,设计更清晰 | Python 早期项目(Mozilla, Facebook 早期) |
| Subversion (SVN) | 集中式,有"中心服务器" | 旧系统迁移、Apache 一些老项目 |
| Perforce | 集中式,商业,大文件好 | 游戏公司(因为资产大) |
| Fossil | 单个可执行文件 + 内置 web UI | SQLite 用 |

| 托管平台 | 关键差别 | 何时用 |
|---|---|---|
| GitHub | 最大,微软,生态最丰富 | Rust 主战场 |
| GitLab | 自托管友好,内置 CI/CD | 公司内部 |
| Codeberg | 非营利,开源,德国 | 想远离微软 |
| Gitea / Forgejo | 自托管,轻量 | 个人 / 小团队 |
| Sourcehut | 极简,无 JS,邮件协作 | hacker 圈 |

本教程:**Git + GitHub**(因为 Rust 生态基本都在 GitHub)。

### 4.3 下级

- **Git 命令**:`init`, `clone`, `add`, `commit`, `push`, `pull`, `fetch`, `merge`, `rebase`, `checkout`, `switch`, `branch`, `tag`, `log`, `diff`, `stash`, `cherry-pick`, `reset`, `revert`, `reflog`
- **GitHub 功能**:Issues, Pull Requests, Actions(CI/CD), Projects, Releases, Wiki, Gist
- **协作模式**:Trunk-based(都 commit 到 main), GitFlow(release/develop/feature 多分支), GitHub Flow(main + feature branch + PR)
- **配置文件**:`.git/config`(repo 级), `~/.gitconfig`(全局), `.gitignore`(忽略文件)

## 5 · 对照与变奏

### commit 信息风格对比

不同社区有不同的 commit message 规范:

**Conventional Commits**(Angular / Vue / 很多 JS 项目):
```
feat(auth): add OAuth2 login
fix(ui): prevent double-click on submit button
docs(readme): update installation steps
chore(deps): bump serde to 1.0.150
```
格式:`type(scope): description`。type 限定为 feat / fix / docs / refactor / test / chore。

**Linux kernel 风格**:
```
net: tcp: fix spurious retransmissions on high-RTT links

Detailed description...
```
格式:`subsystem: summary`。

**Rust 风格**(rust-lang/rust):
```
Fix ICE in borrow checker when...
```
自由格式,但 message 体里要详细说明 motivation + change + tests。

**Handmade Hero / Casey 风格**:
Casey 用自己的版本控制(他视频里有提到),不用 Git。他的精神是"每行改动有清晰动机"。

**经验**:看一个项目的 CONTRIBUTING.md,跟着他们的风格走。

### GitHub Flow vs GitFlow

**GitFlow**(老派,复杂):
```
main (生产)
  ↑
release (准备发版)
  ↑
develop (开发主线)
  ↑
feature/* (具体功能)
```
4 层 branch,严格流程。

**GitHub Flow**(现代,简单):
```
main (生产,永远可部署)
  ↑
feature/xxx (一个 PR 一个 branch)
```
2 层,够用。Rust 生态、Handmade Hero、大多数现代开源项目用 GitHub Flow。

本教程推荐:**GitHub Flow**。

### squash merge vs merge commit vs rebase merge

GitHub PR 合并时三种选项:

- **Create a merge commit**(默认):保留所有 commit + 一个 merge commit。历史完整
- **Squash and merge**:把 PR 里所有 commit 压成一个,合到 main。历史干净,适合"小改动"PR
- **Rebase and merge**:把 PR 里每个 commit 逐一 rebase 到 main,无 merge commit。保留每个 commit,但 hash 变

经验:**PR 有多个语义 commit 用 rebase;PR 只是一个改动集合用 squash**。

## 6 · 关联 Day

- **铺垫**:
  - [00-terminal-basics.md](00-terminal-basics.md) — 命令行操作
  - [01-arch-setup.md](01-arch-setup.md) — `sudo pacman -S git` 装 git
- **当天**:[02-git-and-github.md](02-git-and-github.md)(本篇)
- **后续**:
  - [03-rust-from-scratch-1.md](03-rust-from-scratch-1.md) — Rust 项目用 git 管理
  - [12-opensource-pr-flow.md](12-opensource-pr-flow.md) — 进阶 PR 流程(本篇是基础)
  - 所有 HH 的 dayNNN.md 都假设你会 git clone 本仓库代码

## 7 · 变式训练

### Lv1 · 概念辨析

**题**:`git fetch` 和 `git pull` 有什么区别?为什么推荐先 `fetch` 再决定要不要 `merge`?

**参考解答**:
- `git fetch`:从远端下载新 commit 到本地,但**不**修改工作目录或当前 branch。fetch 后你可以 `git log origin/main` 看远端有什么新东西
- `git pull` = `git fetch` + `git merge`(默认)。它不仅下载,还立即把远端改动合到你当前 branch

为什么推荐先 fetch:`pull` 直接 merge 可能引发冲突或意料之外的改动。先 fetch 看 diff(`git diff main origin/main`),再决定是 merge、rebase 还是先在本地测试。这避免了"一 pull 把代码搞坏"的灾难。

### Lv2 · 动手实践

**题**:完整跑一遍开源贡献流程。准备:注册一个 GitHub 账号。

1. 装 git 并配置用户名 / 邮箱
2. 生成 SSH key 并加到 GitHub(避免每次输密码)
3. fork 一个 Rust 项目(比如 `rust-lang/rustlings`)
4. clone 你的 fork 到本地
5. 配置 upstream(指向原 repo)
6. 创建 branch `fix-typo`
7. 改一行 README(挑个真的 typo,或加一句有用注释)
8. commit,message 用 Conventional Commits 格式
9. push 到你的 fork 的 `fix-typo` branch
10. 在 GitHub 网站开 PR,标题 + 描述
11. 等待 review(自己 review 也行,跑通流程)

完成标准:能看到自己的 PR 出现在 GitHub 网页上,即便没被 merge。

**参考解答**(命令序列):

```bash
# 1. 装 git + 配置
sudo pacman -S git openssh
git config --global user.name "你的真名或昵称"
git config --global user.email "你的邮箱@example.com"
git config --global init.defaultBranch main
git config --global pull.rebase false  # 默认 merge,不 rebase
# 验证:
git config --global --list

# 2. SSH key
ssh-keygen -t ed25519 -C "你的邮箱@example.com"
# 一路回车(默认路径 ~/.ssh/id_ed25519,空密码也行)
cat ~/.ssh/id_ed25519.pub
# 复制输出的整行(以 ssh-ed25519 AAAA... 开头)
# 到 GitHub → Settings → SSH and GPG keys → New SSH key → 粘贴

# 测试连接:
ssh -T git@github.com
# 首次会问 yes/no,选 yes
# 成功输出:Hi 你的名字! You've successfully authenticated...

# 3. fork:在 GitHub 网页上点 Fork 按钮
# 假设你 fork 了 rust-lang/rustlings 到 你的名字/rustlings

# 4. clone 你的 fork(注意用 SSH URL,不是 HTTPS)
cd ~
git clone git@github.com:你的名字/rustlings.git
cd rustlings

# 5. 配置 upstream
git remote add upstream https://github.com/rust-lang/rustlings.git
git remote -v
# 应该看到:
# origin    git@github.com:你的名字/rustlings.git (fetch)
# origin    git@github.com:你的名字/rustlings.git (push)
# upstream  https://github.com/rust-lang/rustlings.git (fetch)
# upstream  https://github.com/rust-lang/rustlings.git (push)

# 6. 新 branch
git switch -c fix-typo
# -c 创建并切换到新 branch

# 7. 改一行(用 nvim 或任何编辑器)
nvim README.md
# 找一个 typo 或加一句注释

# 8. commit
git status         # 看哪些文件改了
git diff           # 看具体改动
git add README.md  # 加到暂存区
git commit -m "docs(readme): fix typo in installation section"
# message 格式:Conventional Commits

# 9. push
git push -u origin fix-typo
# -u 设置 upstream tracking,下次 git push 直接成功

# 10. 开 PR:
# 打开 https://github.com/你的名字/rustlings
# GitHub 会自动提示 "Compare & pull request"
# 点进去,写标题和描述,点 Create pull request
```

### Lv3 · 迁移设计

**题**:你在 `feature-a` branch 上开发了 3 天,期间 main 上有人 push 了新 commit。你想让 `feature-a` 基于最新 main,有两种做法:`git merge main` 和 `git rebase main`。讨论每种做法的结果、对 commit 历史的影响、以及在团队协作中应该选哪个。

**提示**:
- merge 会产生一个 merge commit,有 2 个 parent
- rebase 会重写 feature-a 上的每个 commit,hash 变化
- "不要 rebase 已经 push 给别人的 branch"是黄金法则
- 如果 feature-a 是你私有的(没 push 或只有你用),rebase 更干净

### Lv4 · 开源贡献

**题**:这是真实练习,完成一个 Rust 开源项目的 PR:

1. 在 GitHub 上搜索 `is:issue is:open label:"good first issue" language:Rust` 找一个简单 issue
2. 选一个你看得懂的(比如 "fix doc typo", "add a test case", "improve error message")
3. fork、clone、改、test、PR
4. PR 描述必须包括:
   - 问题(issue 链接)
   - 解决方案(改了什么)
   - 测试(怎么验证)

参考项目(都有 good first issue):
- https://github.com/rust-lang/cargo
- https://github.com/rust-lang/rustlings
- https://github.com/BurntSushi/ripgrep
- https://github.com/sharkdp/bat
- https://github.com/starship/starship

写下你的 PR URL。

## 8 · Rust / Arch 落地代码

### Git 装机配置

```bash
# 装 git
sudo pacman -S git openssh github-cli

# github-cli (gh):GitHub 官方 CLI,可以开 PR / 看 issue 不开浏览器
# 后面有用

# 全局配置
git config --global user.name "你的名字"
git config --global user.email "你的邮箱"

# 让 git 输出带颜色
git config --global color.ui auto

# 默认 branch 名用 main(不用 master)
git config --global init.defaultBranch main

# pull 默认行为:rebase 而不是 merge(可选)
git config --global pull.rebase false

# 设置默认编辑器为 nvim(写 commit message 时用)
git config --global core.editor nvim

# 让 git 记住密码(用 SSH 不需要,HTTPS 需要)
git config --global credential.helper store

# 验证
git config --global --list
```

### SSH 密钥设置

```bash
# 生成 ed25519 key(现代推荐,比 RSA 短而安全)
ssh-keygen -t ed25519 -C "你的邮箱"
# 提示:
# Enter file in which to save the key (~/.ssh/id_ed25519):  回车
# Enter passphrase (empty for no passphrase):  可以空,或设密码更安全
# Enter same passphrase again:

# 生成两个文件:
# ~/.ssh/id_ed25519      私钥(绝对不能泄露)
# ~/.ssh/id_ed25519.pub  公钥(可以给别人看)

# 把公钥加到 GitHub:
cat ~/.ssh/id_ed25519.pub
# 复制整行,在 GitHub → Settings → SSH and GPG keys → New SSH key

# 测试
ssh -T git@github.com
# 输出:Hi 你的名字! You've successfully authenticated, but GitHub does not provide shell access.
```

### 日常 Git 工作流

```bash
# 看状态(最常用)
git status
# 输出示例:
# On branch main
# Your branch is up to date with 'origin/main'.
# Changes not staged for commit:
#   (use "git add <file>..." to update what will be committed)
#         modified:   src/main.rs

# 看改动
git diff                 # 工作目录 vs 暂存区
git diff --staged        # 暂存区 vs HEAD
git diff HEAD            # 工作目录 vs HEAD
git diff main feature-x # 两个 branch 的差别

# 加到暂存区
git add src/main.rs      # 加一个文件
git add .                # 加所有改动(包括新文件、删除)
git add -p               # 交互式加(patch mode,推荐)— 一个 hunk 一个 hunk 选
# -p 会逐块问你 y/n/s/e(yes/no/split/edit)

# commit
git commit -m "feat(auth): add OAuth2 login"
git commit               # 不加 -m 会打开编辑器写多行 message

# 看历史
git log                       # 全部
git log --oneline             # 紧凑(每行一个 commit)
git log --oneline --graph --all  # 图形化看所有 branch
git log -p path/to/file       # 看某文件的完整改动历史
git log --author="你的名字"   # 只看你写的

# 撤销
git restore src/main.rs      # 丢弃工作目录的改动(还没 add)
git restore --staged src/main.rs  # 把暂存区的改动退回到工作目录
git reset HEAD~1             # 撤销最新 commit,改动保留在工作目录
git reset --hard HEAD~1      # 撤销最新 commit,改动丢弃(危险!)

# 暂存当前改动(切到别的 branch 处理事)
git stash                    # 暂存所有未 commit 改动
git stash list               # 看暂存了什么
git stash pop                # 取回最新 stash
git stash drop               # 丢弃最新 stash

# 同步远端
git fetch                    # 下载新 commit,不改工作目录
git pull                     # fetch + merge(默认)
git push                     # 推送本地 commit 到远端
git push -u origin new-branch # 第一次 push 新 branch,加 -u
```

### GitHub CLI (gh)

```bash
# 装
sudo pacman -S github-cli
gh auth login                # 浏览器认证

# 用 gh 开 PR(不开浏览器)
gh pr create --title "feat: add OAuth2" --body "Closes #123"
gh pr list                   # 列出 PR
gh pr view 123               # 看某个 PR 详情
gh pr checkout 123           # 切到 PR 123 的 branch 本地测试
gh pr merge 123              # merge(需要权限)

# 看 issue
gh issue list
gh issue view 45

# 看 PR review 评论
gh pr view 123 --comments
```

### 排错实战

```bash
# 故障 1: "fatal: refusing to merge unrelated histories"
# 原因:两个 repo 的 commit 历史完全不重合(比如 fork 后原 repo force-push 过)
# 解决:确认你想合并,加 --allow-unrelated-histories
git pull origin main --allow-unrelated-histories

# 故障 2: merge conflict
# 症状:git status 显示 "both modified: src/main.rs"
# 打开 src/main.rs,看到:
# <<<<<<< HEAD
# 我的改动
# =======
# 别人的改动
# >>>>>>> origin/main
# 解决:
# 1. 手动决定保留哪个,或合并两边,删除 <<<<<<< ======= >>>>>>> 标记
# 2. git add src/main.rs
# 3. git commit(merge 模式下不加 -m 也行,会自动生成 merge message)

# 故障 3: 误删了 commit
git reflog
# reflog 记录 HEAD 的所有移动,即使 commit 看似丢了,这里也能找到
# 找到误删前的 commit hash,然后:
git reset --hard <hash>

# 故障 4: 想撤销一个已经 push 的 commit
# 不要 reset --hard 然后 force-push(危险!影响别人)
# 用 revert,创建一个反向 commit:
git revert <commit-hash>
git push

# 故障 5: force push 后队友的本地坏了
# 教训:永远不要 force push 到公共 branch(main / develop)
# 只对自己的 feature branch force push

# 故障 6: git push 报权限错误
# 检查 remote:
git remote -v
# 如果 origin 是 HTTPS URL,push 要输密码(GitHub 已不支持密码,要用 PAT)
# 改成 SSH:
git remote set-url origin git@github.com:你的名字/repo.git
```

### 一个完整的 PR 示例(ripgrep)

```bash
# 假设你想给 ripgrep 加一个测试

# 1. fork & clone
gh repo fork BurntSushi/ripgrep --clone
cd ripgrep

# 2. 看 CONTRIBUTING.md
cat CONTRIBUTING.md
# ripgrep 要求:跑 cargo test 通过,代码用 rustfmt 格式化

# 3. 装 pre-commit hook(如果有)
ls .github/hooks/
# 看 CI 配置:
cat .github/workflows/ci.yml

# 4. 新 branch
git switch -c add-new-test

# 5. 写代码 + 测试
nvim crates/regex/src/main.rs   # 加个 #[test]
cargo test                       # 跑测试,确认通过
cargo fmt                        # 格式化
cargo clippy                     # lint

# 6. commit
git add crates/regex/src/main.rs
git commit -m "test(regex): add test for empty alternation"

# 7. push
git push -u origin add-new-test

# 8. 开 PR
gh pr create --title "test(regex): add test for empty alternation" \
             --body "Adds a regression test for empty alternation parsing."
```

## 9 · 延伸阅读(可选补充,非必需)

本仓库本地:
- [01-arch-setup.md](01-arch-setup.md) — `pacman -S git` 安装
- [12-opensource-pr-flow.md](12-opensource-pr-flow.md) — 进阶 PR 实战
- [phase-0/README.md](README.md) — 起步营总览

外部稳定 URL:
- Pro Git Book(免费,完整):https://git-scm.com/book/zh/v2(中文版)
- GitHub Docs:https://docs.github.com/
- Conventional Commits:https://www.conventionalcommits.org/
- Learn Git Branching(交互式游戏):https://learngitbranching.js.org/?locale=zh_CN
- Oh Shit, Git!?!:https://ohshitgit.com/(救急手册)
- man pages:`man git`, `man gittutorial`, `man git-push`

真实开源源码:
- Git 源码(C 写):https://github.com/git/git
- git2-rs(libgit2 的 Rust 绑定):https://github.com/rust-lang/git2-rs
- GitHub CLI(Go 写):https://github.com/cli/cli
