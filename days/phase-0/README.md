
# Phase 0 · 起步营

> 在你跟着 Casey 走 Day 001 之前,先把"会用终端、装好 Arch、懂 Rust 基础、会 Git、看懂编译器报错"这几件事搞定。这 16 篇手把手带你跨过门槛。

## 这一阶段在做什么

Handmade Hero 视频假设你**已经懂**:C 语言、指针、基本 Win32、Linux 命令行、版本控制。Casey 不会停下来解释这些。如果你直接跟 Phase 1,你会被两个东西反复打脸:

1. **Casey 写的是 C**。你看不懂指针、`malloc`、`#include`,就什么都看不懂。
2. **Casey 用 Windows**。他在 Win32 API 上做事,你跟 Linux 不同步。

Phase 0 解决这两件事:
- 教你 Rust(替代 C,现代、安全、Casey 精神相容)
- 教你 Linux(替代 Win32,开源、透明、命令行强大)
- 教你 Git / GitHub / PR(开源协作基本技能)
- 教你工具链(strace / gdb / perf,后面调试救命)
- 教你数学(向量、矩阵、积分,Phase 2 开始就要)
- 教你看懂 C 和汇编(Casey 原版代码 + 验证 Rust 输出)

完成 Phase 0 后,你打开 Phase 1 Day 001 时,**所有"我连这个都不懂"的拦路虎都被清掉了**,你可以专注学游戏开发本身。

## 学习目标

完成 Phase 0 后,你能:

- [ ] 在 Arch Linux 上熟练用终端工作(vim 编辑 / 管道 / 重定向 / 作业控制)
- [ ] 看懂并配置 Arch 系统(用户、权限、systemd、网络、防火墙)
- [ ] 在 GitHub 上 fork / clone / branch / commit / PR 一个真实项目
- [ ] 用 Rust 写出 50-200 行的程序(理解所有权、borrow、lifetime、enum、trait、Result)
- [ ] 看懂 Rust 编译器的 E0xxx 错误码,知道怎么修
- [ ] 解释 Linux 文件系统层次结构(FHS)、proc/sys/dev 的用途
- [ ] 用 strace 追踪系统调用、用 gdb 调试、用 perf 做性能分析
- [ ] 解释向量、点积、叉积、矩阵、积分的基本原理(不需要深推导)
- [ ] 读懂简单的 C 代码 + x86_64 汇编(用 objdump / Compiler Explorer)
- [ ] 给一个真实 Rust crate 提一个 PR(文档 / 测试 / 简单 bug)

## 16 篇文章清单

| # | 标题 | 核心内容 |
|---|---|---|
| [00](00-terminal-basics.md) | 终端基础 | shell / pwd / cd / ls / 管道 / vim 入门 |
| [01](01-arch-setup.md) | Arch Linux 配置 | pacman / systemd / journalctl / 用户权限 |
| [02](02-git-and-github.md) | Git 和 GitHub | fork → clone → branch → commit → PR 全流程 |
| [03](03-rust-from-scratch-1.md) | Rust 从零(1) | 安装 / cargo / 变量 / 类型 / 控制流(Ch.1-3) |
| [04](04-rust-from-scratch-2.md) | Rust 从零(2) | ownership / borrow / slice(Ch.4) |
| [05](05-rust-from-scratch-3.md) | Rust 从零(3) | struct / enum / pattern / error handling(Ch.5-9) |
| [06](06-rust-from-scratch-4.md) | Rust 从零(4) | trait / 泛型 / lifetime / iter / closure(Ch.10-16) |
| [07](07-linux-filesystem.md) | Linux 文件系统 | FHS / proc / sys / dev / inode / 权限位 |
| [08](08-processes-and-signals.md) | 进程与信号 | fork / exec / wait / signal / 终端控制 |
| [09](09-editor-toolchain.md) | 编辑器工具链 | helix / nvim + rust-analyzer + cargo-watch |
| [10](10-package-management.md) | 包管理 | pacman / cargo / rustup / AUR / asdf |
| [11](11-reading-rustc-errors.md) | 看 Rust 报错 | E0xxx 码 / lifetime / borrow / trait bound |
| [12](12-opensource-pr-flow.md) | 开源贡献流程 | fork → branch → commit → push → PR → review → merge 实战 |
| [13](13-diagnosis-tools.md) | 诊断工具 | strace / ltrace / gdb / perf / valgrind / flamegraph |
| [14](14-math-foundations.md) | 数学基础 | 向量 / 矩阵 / 点积 / 叉积 / 积分直觉(从零) |
| [15](15-c-and-assembly-reading.md) | 读懂 C 和汇编 | Casey 的 C / gcc / objdump / x86_64 汇编入门 |

## 学习节奏

每篇 1-3 小时(读 + 动手 + 练习)。建议:
- **00-06**(Rust + 终端):连续学,1-2 周
- **07-13**(Linux + 工具):穿插做,2 周内完成
- **14-15**(数学 + 汇编):Phase 1 开始前必看

总耗时 **2-4 周**(取决于你基础)。如果你某项已懂(比如已会 Git),可跳过对应篇,但**不要跳过 14 数学基础**——后面 Phase 2 开始数学密度陡升。

## 阶段验收

- [ ] 能在 30 分钟内:用 cargo 新建项目 → 写一个 Vec2 结构体 → 实现加法 / 点积 / 长度 → 写 main 测试 → cargo run 通过
- [ ] 能在 GitHub 上 fork 一个 Rust 项目,改一行 README,提 PR,等 review
- [ ] 能用 strace 看 cargo build 时调用了哪些系统调用
- [ ] 能用 gdb 调试 Rust 程序,打断点、看变量、单步
- [ ] 能解释下面术语:所有权、lifetime、unsafe、SIMD、cache line、进程、线程、文件描述符、inode、信号
- [ ] 能写出向量点积公式 + 几何意义,知道为什么 N·L=0 是光照边缘

## 推荐配套阅读(可选)

- The Rust Book:https://doc.rust-lang.org/book/
- Comprehensive Rust(Google):https://google.github.io/comprehensive-rust/
- Arch Wiki:https://wiki.archlinux.org/
- The Linux Command Line(免费书):https://linuxcommand.org/tlcl.php
- 3D Math Primer:https://gamemath.com/book/
- Essence of Linear Algebra(3Blue1Brown):https://www.youtube.com/playlist?list=PLZHQObOWTQDPD3MizzM2xVFitgF8hE_ab

但**所有核心内容都在本 phase 文章里**,以上只是补充。
