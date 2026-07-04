
# 12 · 开源 PR 全流程:fork → branch → commit → PR → review → merge

> "成为开源黑客"不是一句口号。它是一条非常具体的、可以照做 6 步走的流程:fork → clone → branch → commit → push → PR。这一篇手把手带你走一遍,目标是在你读完这一篇之后,真的能向一个 Rust 项目提交第一个 PR——哪怕只是改一行文档。

## 0 · 为什么要有这一天

你大概注册了 GitHub,clone 过别人的仓库,跑过 `git pull`。但下面这些问题你大概率答不上来:

1. **我想改 glam 的一个 typo,但它在我账号下没有权限,怎么提交?**
2. **fork 是什么?为什么不能直接 clone 原仓库改?**
3. **branch 干嘛用?直接在 main 上改不行吗?**
4. **commit message 怎么写?有什么约定?**
5. **PR 是 Pull Request,为什么叫 "pull"?它和 "request" 有什么关系?**
6. **maintainer 让我 "rebase 一下",rebase 是什么?**
7. **CI 显示 build failed,但本地 build 通过,怎么回事?**

这些问题背后是开源协作的核心机制。**学会这套流程,你就拿到了开源世界的钥匙**——你能改任何人的代码,只要对方接受你的 PR。Rust 生态的几乎所有 crate 都是开源的,你的每一个 PR 都在为生态做贡献。

**心理锚点**:这一篇读完,你能:
- 独立完成 fork → clone → branch → commit → push → PR 全流程
- 写一个符合规范的 commit message(`feat:` / `fix:` / `docs:` 等)
- 知道 PR review 时维护者会看什么,怎么准备
- 处理 review 反馈(改 → force push → 重新 review)
- 知道 squash / rebase / merge 三种 merge 方式的差别

## 1 · 概念地图:GitHub 协作模型

| 词 | 是什么 |
|---|---|
| **Origin / Upstream** | 你 fork 的仓库 = origin(你的);原仓库 = upstream(原作者的) |
| **Fork** | 在你的 GitHub 账号下复制一份原仓库(保留 fork 关系) |
| **Branch** | 在仓库里创建一条并行的开发线(不影响 main) |
| **Commit** | 一次原子性改动 + message,记录"做了什么" |
| **Push** | 把本地 commit 推到远端 |
| **Pull** | 从远端拉 commit 到本地 |
| **PR(Pull Request)** | 请求维护者把你的 branch 拉进 main |
| **Review** | 维护者审你的 PR,可能要求改 / 直接 merge / 拒绝 |
| **CI(Continuous Integration)** | PR 自动跑测试 + lint + 文档构建 |
| **Squash / Rebase / Merge** | 三种把 PR 合入 main 的方式 |

### 协作模型图

```
原仓库 (upstream, github.com/bitshifter/glam)
   │
   │ ① 你 fork(在你的账号下复制一份)
   ▼
你的 fork (origin, github.com/<you>/glam)
   │
   │ ② clone 到本地
   ▼
本地 git 仓库
   │
   │ ③ branch + commit + push
   ▼
你的 fork 上的一个 branch
   │
   │ ④ 在 GitHub 上发 PR 给 upstream
   ▼
upstream 的 PR 列表
   │
   │ ⑤ review → 改 → CI 通过 → merge
   ▼
upstream 的 main 上有你的改动
```

**关键洞察**:你不能直接 push 到 upstream(没有权限)。你只能 push 到自己的 fork。然后通过 PR **请求** upstream 的维护者把你的 branch **pull**(拉)过去——这就是 "Pull Request" 的来源。

## 2 · 心智模型

### 类比:开源 PR 是"投稿"流程

想象你给一家杂志投稿:

1. **fork** = 你拿一份杂志的版式样板到自己家(保持版式一致)
2. **branch** = 你单独开一张桌子改你的文章,不碰原版
3. **commit** = 你每改一段就标一下"今天改了摘要"、"今天改了结论"
4. **push** = 你把改好的稿子送到自己家邮箱(私有的)
5. **PR** = 你写信给主编:"我从我家邮箱拿了一份稿子,请审阅"
6. **review** = 主编看,提出修改意见
7. **rebase / squash** = 你按意见改,把多次小改动合并成一份完整稿子
8. **merge** = 主编接受,把你的稿子排进正式发行

每一步都有理由,不是凭空的。

### 严谨原理:为什么不能直接在 main 上改

如果在 main 上改:
1. 你的 main 和 upstream 的 main 是两条线,一旦 upstream 改了你就要 merge
2. 你提交的 PR 会混入大量无关 commit
3. 别人 review 时看到一堆"merge from upstream",一团乱

**规范**:每个 PR 一个 feature branch,只包含相关的 commit。这样 review 简单,merge 干净,出问题容易 revert。

### Commit message 约定:Conventional Commits

业界主流的 commit message 格式:

```
<type>(<scope>): <subject>

<body>

<footer>
```

- `type`:feat(新功能)/ fix(bug 修复)/ docs(文档)/ refactor(重构)/ test(测试)/ chore(杂项)/ perf(性能)/ style(格式)/ ci(CI 配置)
- `scope`(可选):改动范围,如 `vec3` / `cli`
- `subject`:一句话说做了什么,祈使句("add X" 而不是 "added X")
- `body`:详细说明,为什么改、怎么改
- `footer`:breaking change / 关联 issue

例子:

```
docs(vec3): add formula derivation for reflect

The current docstring only says "computes the reflection vector"
without showing the formula v' = v - 2(v·n)n. This adds the
derivation so readers understand why.

Fixes: #123
```

这个格式被大量项目使用(glam、bevy、tokio、nushell……),自动生成 changelog、自动 bump 版本。

## 3 · 四域深入

### 3.1 · 完整 PR 流程实战:给 glam 提一个 doc PR

下面用一个**真实场景**走完全流程:发现 glam 的 doc 里有 typo / 不清楚的描述,修它,提 PR。

#### 步骤 1:fork

打开 https://github.com/bitshifter/glam ,右上角点 **Fork** 按钮。这会创建 `https://github.com/<你的用户名>/glam`。

#### 步骤 2:clone 你的 fork 到本地

```bash
# 用 gh CLI(推荐,自动配 origin / upstream)
sudo pacman -S github-cli
gh auth login   # 按提示登录

# clone 你的 fork
gh repo clone <你的用户名>/glam
cd glam

# 看 remote(应该有 origin = 你的 fork)
git remote -v
# origin  git@github.com:<你的用户名>/glam.git (fetch)
# origin  git@github.com:<你的用户名>/glam.git (push)

# 加 upstream(原仓库,为了同步上游改动)
git remote add upstream https://github.com/bitshifter/glam.git
git remote -v
# origin     ... 你的 fork
# upstream   ... 原仓库
```

**为什么需要 upstream?** 因为原仓库持续在改,你要定期同步:`git fetch upstream && git rebase upstream/main`。

#### 步骤 3:branch

```bash
# 切到最新 main
git checkout main
git pull upstream main    # 同步上游
git push origin main      # 让你的 fork 也更新(可选)

# 创建并切到新 branch
git checkout -b docs/fix-vec3-reflect-typo
# -b 表示新建,后面是 branch 名

# 看 branch(用 * 标当前)
git branch
# * docs/fix-vec3-reflect-typo
#   main
```

**branch 命名约定**:
- `feat/xxx` — 新功能
- `fix/xxx` — bug 修复
- `docs/xxx` — 文档
- `refactor/xxx` — 重构
- `test/xxx` — 测试

#### 步骤 4:改代码

```bash
# 用 helix 打开要改的文件
hx src/f32/vec3.rs

# 找到 reflect 函数(Ge: gd 跳定义,或 /fn reflect)
# 假设 docstring 写的是:
# /// Computes the reflection vector for the incident vector `v` and surface normal `n`.
# 我们改成更清楚的:
# /// Computes the reflection of vector `v` off a surface with normal `n`.
# ///
# /// Formula: `v' = v - 2 * (v · n) * n`
# ///
# /// `n` must be normalized for the result to be correct.

# 保存,看 diff
git diff
# 看到红绿对比
```

#### 步骤 5:本地验证

```bash
# 跑 build
cargo build

# 跑测试
cargo test

# 跑 clippy(很多项目 CI 跑这个)
cargo clippy -- -D warnings

# 跑 fmt check
cargo fmt -- --check

# 如果 fmt check 失败,跑 cargo fmt 修复
```

**所有 CI 检查本地先跑过**,避免 round-trip。

#### 步骤 6:commit

```bash
# 暂存改动
git add src/f32/vec3.rs

# 看 staged 状态
git status

# commit
git commit -m "docs(vec3): clarify reflect formula and normalized requirement

The current docstring only says 'computes the reflection vector'
without showing the formula. This adds the explicit formula
v' = v - 2 * (v · n) * n and notes that n must be normalized."
```

或用 `git commit`(不带 -m)打开编辑器写多行 message——这是大改动推荐做法。

#### 步骤 7:push 到你的 fork

```bash
git push origin docs/fix-vec3-reflect-typo
# 第一次 push 这个 branch,加 -u 设置 upstream tracking
git push -u origin docs/fix-vec3-reflect-typo
```

#### 步骤 8:发 PR

两种方式:

**方式 A:用 gh CLI(最快)**

```bash
gh pr create \
    --repo bitshifter/glam \
    --base main \
    --head <你的用户名>:docs/fix-vec3-reflect-typo \
    --title "docs(vec3): clarify reflect formula and normalized requirement" \
    --body "## What does this PR do?

Clarifies the docstring for \`Vec3::reflect\` by adding:
- The explicit formula: \`v' = v - 2 * (v · n) * n\`
- A note that \`n\` must be normalized for correct results

## Why?

The current docstring only says 'computes the reflection vector'
without explaining the math, making it hard for new users to
understand what the function actually does.

## Checklist
- [x] Documentation updated
- [x] \`cargo test\` passes
- [x] \`cargo clippy -- -D warnings\` passes
- [x] \`cargo fmt -- --check\` passes
"
```

**方式 B:用 GitHub 网页**

push 后,GitHub 会显示一个黄色按钮 "Compare & pull request"。点它,填 title + body,提交。

#### 步骤 9:等 review

PR 提交后:
1. CI(GitHub Actions)自动跑,显示绿勾或红叉
2. 维护者收到通知,有时间会看
3. 反馈三种:
   - **直接 merge**(小改动,typo 这种)
   - **request changes**(要求改)
   - **close**(拒绝)

如果 CI 红,看日志修。常见:
- 格式不对 → `cargo fmt`
- clippy 失败 → 看 warning 修
- test 失败 → 是不是你的改动破坏了某 test

#### 步骤 10:处理 review 反馈

维护者说:"Please add an example to the docstring."

```bash
# 继续在同一 branch 改
hx src/f32/vec3.rs
# 加 example

# 再 commit
git add src/f32/vec3.rs
git commit -m "docs(vec3): add usage example to reflect"

# push(不是新 PR,直接 push 到同 branch)
git push origin docs/fix-vec3-reflect-typo

# PR 自动更新(因为是同 branch)
```

#### 步骤 11:rebase(可选,清理历史)

如果你的 branch 有 5 个 commit,维护者可能要求 squash 成一个。或 rebase 到最新 main。

```bash
# 同步最新 main
git fetch upstream
git rebase upstream/main
# 这把你的 commit 重新放到 upstream/main 最新之上

# 如果有冲突,git 会停,告诉你解决
# 解决后:git add <文件> && git rebase --continue

# force push(因为 rebase 重写了历史)
git push --force-with-lease origin docs/fix-vec3-reflect-typo
```

`--force-with-lease` 比 `--force` 安全:如果别人也 push 了,会拒绝(避免覆盖)。

#### 步骤 12:merge

维护者点 "Merge pull request" 按钮。三种 merge 方式:

| 方式 | 行为 | 何时用 |
|---|---|---|
| **Merge commit**(默认) | 保留所有 commit + 加一个 merge commit | 一般项目 |
| **Squash and merge** | 把所有 commit 合成一个,加到 main | commit 历史脏时 |
| **Rebase and merge** | 把每个 commit 直接加到 main(无 merge commit) | commit 已干净时 |

merge 后你的 branch 可以删:

```bash
git checkout main
git pull upstream main
git branch -d docs/fix-vec3-reflect-typo   # 删本地
git push origin --delete docs/fix-vec3-reflect-typo   # 删远端
```

### 3.2 · GitHub 工具:gh CLI

`gh` 是 GitHub 官方 CLI,比网页快 10 倍。

```bash
# 装
sudo pacman -S github-cli
gh auth login

# 常用命令
gh repo clone <owner>/<repo>     # clone
gh repo fork <owner>/<repo> --clone   # fork + clone 一步到位
gh pr create                     # 发 PR
gh pr list                       # 列出 PR
gh pr view <number>              # 看 PR 详情
gh pr checkout <number>          # 切到 PR 的 branch(方便 review 别人的)
gh pr checks                     # 看 CI 状态
gh pr merge <number> --squash    # merge(需要权限)
gh issue list                    # 列 issue
gh issue create                  # 创建 issue
```

`gh repo fork --clone` 是神器:

```bash
gh repo fork bitshifter/glam --clone
# 自动:fork → 加 origin → 加 upstream → clone 到本地
```

一步做完步骤 1-2。

### 3.3 · 协作礼仪:维护者怎么看 PR

维护者一次收到几十个 PR,他要快速判断。会优先看:

1. **PR description 清楚** —— 一句话说做了什么 + why
2. **CI 全绿** —— 不会浪费时间看 CI 红的
3. **改动小** —— 100 行的 PR 比一千行容易 review
4. **scope 单一** —— 一个 PR 只做一件事,不要顺带改无关代码
5. **有测试** —— 新功能 / bug 修复必有 test
6. **符合代码风格** —— fmt + clippy 通过

**不礼貌的行为**(会被 close):
- 改一堆无关的代码"顺手清理"
- PR description 只写 "fix"(写清楚啊)
- 改别人代码风格(用你的偏好)
- 没有 test
- 一个 PR 解决多个不相关问题(拆开)
- 不回 review 评论(消失一周)

### 3.4 · 看真实 PR 学习

去 GitHub 看 glam 或 nushell 的已 merge PR,选 labeled "good first issue" 的:

```
https://github.com/bitshifter/glam/pulls?q=is:pr+label:"good-first-issue"
```

看每个 PR 的:
- description 怎么写
- review 评论怎么交互
- 改了多少文件、多少行
- CI 跑了什么

这是免费的"开源协作课"。

## 4 · 认知地图

### 4.1 上级

- **开源协作模型** — 分布式开发 + 中心化代码托管 + PR 审查
- **Distributed Version Control** — Git 设计的核心:每个人有完整副本
- **Code Review 文化** — 所有改动经他人 review,代码质量+ 知识传播

### 4.2 同级

| 平台 | 关键差别 | 何时用 |
|---|---|---|
| GitHub | 最大,微软,主流开源 | 绝大多数项目 |
| GitLab | 自托管选项,CI/CD 强 | 企业内部项目 |
| Gitea / Forgejo | 自托管,轻量 | 私有 / 离线 |
| Sourcehut | 极简,无 JS,邮件式 PR | 极客项目 |
| Codeberg | 非营利,Gitea fork | 价值观驱动 |

Git 操作都一样,只是托管界面不同。

### 4.3 下级

- **git rebase** — 把 commit 重放到另一 base
- **git cherry-pick** — 把单个 commit 摘过来
- **git bisect** — 二分查找引入 bug 的 commit
- **CONTRIBUTING.md** — 项目自己的贡献指南(必读!)
- **CODEOWNERS** — 自动指定 reviewer
- **DCO(Developer Certificate of Origin)** — 一些项目要求签名

## 5 · 对照与变奏

### PR vs 直接 push(集中式 vs 分布式)

| | 集中式(老 SVN 模型) | 分布式(Git + PR) |
|---|---|---|
| 谁能改 | 有 commit 权限的人 | 任何人 |
| 怎么改 | 直接 commit 到 main | fork → branch → PR |
| Review | 事后(或没有) | 事前(merge 前) |
| 适合 | 小团队 | 开源项目 |

Git 设计哲学就是"分布式"——Linux 内核有几千贡献者,没 PR 模型不可行。

### 三种 merge 方式对比

```
原始:
main:      A---B---C
                  \
feature:           D---E---F

Merge commit:
main:      A---B---C-----------M
                  \         /
feature:           D---E---F
(M 是 merge commit,保留 D E F)

Squash and merge:
main:      A---B---C---DEF
(把 D E F 合成一个 DEF)

Rebase and merge:
main:      A---B---C---D'--E'--F'
(D E F 重放到 main 后,无 merge commit)
```

不同项目偏好不同。看 `CONTRIBUTING.md`。

### 历史演化

- **2005 Git 诞生** — Linus Torvalds 写,内核用
- **2008 GitHub 上线** — 让 Git 协作变得可视化
- **2010s PR 成主流** — 业界共识
- **2020s** — Conventional Commits / 机器人自动化 / 自动 changelog

## 6 · 关联 Day

- **铺垫**:[02-git-and-github.md](02-git-and-github.md)(git 基础)、[10-package-management.md](10-package-management.md)(cargo)
- **当天**:本篇
- **后续**:
  - 每个 Phase 末尾,Lv4 开源贡献题(都用本篇流程)
  - Phase 2 Day 050+(可能给 glam 提数学函数 PR)
  - Phase 5(给 wgpu / bevy 提 PR)

## 7 · 变式训练

### Lv1 · 概念辨析

**题**:origin 和 upstream 各指什么?为什么不直接 git pull origin?

**参考解答**:
- **origin** = 你的 fork 的远端(在你账号下)
- **upstream** = 原项目仓库(在原 maintainer 账号下)

如果你只 `git pull origin main`,你拿到的是**你的 fork 的状态**——可能是几天前 fork 时的快照,可能 maintainer 已经改了很多。所以你**必须** `git pull upstream main` 同步上游。

典型工作流:`git fetch upstream && git rebase upstream/main`(把你的 branch 基于 upstream 最新改)。

### Lv2 · 动手实践

**题**:完成一个**真实的**小 PR。建议目标:
- 在 https://github.com/bitshifter/glam 找一个 doc comment 的小问题(typo / 表达不清 / 缺 example)
- 或者:在 https://github.com/rust-lang/rust 找错误码 md 里的过时例子
- 或者:任何你用过的 Rust crate 的 README

完整步骤:
1. fork → clone(用 `gh repo fork --clone`)
2. 同步 upstream
3. branch
4. 改一行 / 加一行 example
5. 本地 cargo test + clippy + fmt
6. commit(conventional commits 格式)
7. push
8. `gh pr create`
9. 等 review

完成标准:**PR 真的提交了**,PR URL 是你能贴出来的。

**参考解答**(命令清单,你跑了再看效果):

```bash
# 1. fork + clone
gh repo fork bitshifter/glam --clone
cd glam

# 2. 同步
git fetch upstream
git checkout main
git rebase upstream/main
git push origin main

# 3. branch
git checkout -b docs/vec3-reflect-example

# 4. 改
hx src/f32/vec3.rs
# 找 reflect,加 example

# 5. 验证
cargo test
cargo clippy -- -D warnings
cargo fmt -- --check

# 6. commit
git add src/f32/vec3.rs
git commit -m "docs(vec3): add usage example for reflect

Adds a doctest example showing how to use Vec3::reflect
to compute the reflection of an incident velocity vector
off a surface normal."

# 7. push
git push -u origin docs/vec3-reflect-example

# 8. PR
gh pr create --repo bitshifter/glam \
    --base main \
    --title "docs(vec3): add usage example for reflect" \
    --body "Adds a doctest example for \`Vec3::reflect\`.

## Why
The current docstring has no example, making it harder for
new users to understand the function's behavior.

## Checklist
- [x] \`cargo test\` passes
- [x] \`cargo clippy\` clean
- [x] \`cargo fmt\` clean"

# 9. 等
gh pr view --web   # 在浏览器打开 PR
```

### Lv3 · 迁移设计

**题**:你给一个项目提 PR,维护者说 "Can you rebase onto main and squash your commits?"。完整步骤是什么?每步做什么?如果有 conflict 怎么办?

**提示**:
- `git fetch upstream` 拿上游最新
- `git rebase -i HEAD~3` 交互式 rebase,把最近 3 个 commit 合并
- `git rebase upstream/main` 把你的 branch 重放到上游最新之上
- 有 conflict:fix → `git add` → `git rebase --continue`
- force push:`git push --force-with-lease`

写出完整命令序列,描述每步会发生什么。

### Lv4 · 开源贡献(进阶)

**题**:本篇的 Lv2 就是真实的开源贡献。再做一个不同类型:

1. **找 good first issue**:在 https://github.com/bitshifter/glam/issues?q=is:open+label:"good-first-issue" 认领一个
2. **加测试**:找个 glam 里没测试覆盖的函数,补 test
3. **加 example**:glam 的 examples 目录加一个新 demo
4. **修 typo**:看 glam 的 README,有没有过时的版本号 / 链接

PR description 要包括:
- 改了什么
- 为什么
- 怎么验证(cargo test 输出截图)
- 关联 issue(Fixes #N)

写完后回头看:你的 PR 哪些地方符合本篇讲的规范?哪些可以改进?

## 8 · Rust / Arch 落地代码

### 完整脚本:一键发 PR

```bash
#!/bin/bash
# submit-pr.sh —— 一键 fork → branch → commit → push → PR
# 用法:submit-pr.sh <upstream-repo> <branch-name> <commit-message> <pr-title> <pr-body-file>

set -e

UPSTREAM="$1"           # 如 bitshifter/glam
BRANCH="$2"              # 如 docs/vec3-example
COMMIT_MSG="$3"
PR_TITLE="$4"
PR_BODY_FILE="$5"

REPO_NAME=$(basename "$UPSTREAM")

# 1. fork + clone
gh repo fork "$UPSTREAM" --clone
cd "$REPO_NAME"

# 2. 同步上游
git fetch upstream
git checkout main
git rebase upstream/main
git push origin main

# 3. 新 branch
git checkout -b "$BRANCH"

echo ">>> 现在改代码,改完按 Enter"
read

# 4. 验证
cargo test
cargo clippy -- -D warnings
cargo fmt -- --check

# 5. commit
git add -A
git commit -m "$COMMIT_MSG"

# 6. push
git push -u origin "$BRANCH"

# 7. PR
gh pr create \
    --repo "$UPSTREAM" \
    --base main \
    --head "$(gh api user --jq .login):$BRANCH" \
    --title "$PR_TITLE" \
    --body "$(cat $PR_BODY_FILE)"

echo ">>> PR 已创建。"
gh pr view --web
```

### git 配置优化

```bash
# ~/.gitconfig
[user]
    name = Your Name
    email = your@email.com

[init]
    defaultBranch = main       # 新仓库默认 main(不是 master)

[pull]
    rebase = true              # pull 时 rebase 而不是 merge

[push]
    autoSetupRemote = true     # 第一次 push 自动 -u

[alias]
    co = checkout
    br = branch
    ci = commit
    st = status
    df = diff
    lg = log --oneline --graph --decorate --all
    amend = commit --amend --no-edit
    # 用法:git lg 看漂亮历史图

[core]
    editor = hx                # 默认编辑器用 helix

[rerere]
    enabled = true             # 记住 rebase 冲突的解决方法

[color]
    ui = auto
```

加完后 `git lg` 给你这种输出:

```
* 4b8c3a4 (HEAD -> main, origin/main) docs: add reflect example
* 7f9d0e1 feat: add glam support
* a2c1b9d initial commit
```

### 处理 CI 失败的常见情况

```bash
# 1. fmt 失败
cargo fmt
git add -A
git commit --amend --no-edit    # 改进上一个 commit
git push --force-with-lease

# 2. clippy 失败
cargo clippy --fix              # 自动修
cargo clippy -- -D warnings     # 验证
git add -A && git commit --amend --noedit
git push --force-with-lease

# 3. test 失败
# 看是哪个 test 失败
cargo test -- --nocapture
# 修后 amend + force-push

# 4. 跨平台失败(windows CI 红)
# 可能是路径分隔符 / 行尾 / 大小写敏感问题
# 用 cargo check --target x86_64-pc-windows-gnu 试试(需要装 target)
```

### Troubleshooting

- **`git push` 报 "Permission denied"** —— SSH key 没配。`gh auth setup-git` 自动配,或手动加 SSH key 到 GitHub
- **`gh pr create` 报 "no commits between"** —— 你忘了 push branch
- **CI 红但本地绿** —— 看 CI 日志。常见:Rust 版本不同(本地 stable,CI 用 MSRV)、平台不同(本地 Linux,CI 也跑 Windows)、feature flag 不同
- **维护者 request changes 但你没通知** —— GitHub 不自动通知。改完 push 后,在 PR 评论 "@maintainer updated"

## 9 · 延伸阅读(可选补充,非必需)

本仓库本地:
- [02-git-and-github.md](02-git-and-github.md) — git 基础
- [10-package-management.md](10-package-management.md) — cargo / rustup
- [phase-0/README.md](README.md)

外部稳定 URL:
- GitHub Docs PR 流程:https://docs.github.com/en/pull-requests
- Conventional Commits 规范:https://www.conventionalcommits.org/
- First Contributions 教程:https://github.com/firstcontributions/first-contributions
- How to Contribute to Open Source:https://opensource.guide/how-to-contribute/

真实开源源码:
- glam CONTRIBUTING.md:https://github.com/bitshifter/glam/blob/main/CONTRIBUTING.md
- rust CONTRIBUTING.md:https://github.com/rust-lang/rust/blob/master/CONTRIBUTING.md
- 看真实 PR:https://github.com/bitshifter/glam/pulls?q=is:pr+is:merged
