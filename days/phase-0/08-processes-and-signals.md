---
article: 08
phase: 0
title: "进程与信号:fork / exec / wait / 信号 / 作业控制"
type: setup
difficulty: 3
duration: "2-3h"
domains: [linux]
prereqs: ["00-terminal-basics", "01-arch-setup", "07-linux-filesystem"]
---

# 08 · 进程与信号:fork / exec / wait / 信号 / 作业控制

> 你在终端敲下 `cargo run` 那一刻,操作系统做了什么?为什么 Ctrl+C 能杀掉程序?为什么 `|` 能把两条命令串起来?为什么 `&` 能让程序在后台跑?这一篇把"程序怎么活、怎么死、怎么通信"一次性讲透——这是 Linux 系统编程的地基,也是你后面理解 HH 热重载、子进程、崩溃恢复的前提。

## 0 · 为什么要有这一天

写代码时,你大概率遇到过这些场景,但说不清背后发生了什么:

1. **程序卡死**,你想停掉它,Ctrl+C 一下就好了——Ctrl+C 到底传了什么给程序?
2. **编译大项目**,你想一边编译一边刷文档,于是 `cargo build &` 把编译丢后台,但怎么知道它什么时候完成?
3. **shell 用管道串命令** `cat file | grep x | sort`,这三条命令是不是三个进程?它们怎么"接力"?
4. **游戏崩溃**,日志只打了 `Segmentation fault` 然后退出——是谁让程序退出的?退出码 139 是什么意思?
5. **HH Day 1** Casey 在 Windows 上加载 DLL,热重载时卸载再加载——Linux 上对应物是什么?一个进程能不能在运行中加载新代码?

这些问题全部指向同一个底层抽象:**进程(process)和信号(signal)**。搞不懂这两件事,你写的程序永远是黑盒——你不知道它怎么启动、怎么死、怎么和别的程序配合。

**心理锚点**:这一篇读完,你能:
- 在 Rust 里用 `fork` + `exec` 启动一个子进程,知道每一步发生了什么
- 解释 Ctrl+C / Ctrl+Z / `kill -9` / `kill -15` 各自做了什么
- 在终端用 `&` / `fg` / `bg` / `jobs` 控制前后台任务
- 看 `ps aux` / `htop` 输出,找到任何程序,看它的 PID、PPID、状态、打开的文件
- 知道"僵尸进程"是什么,为什么会出现,怎么清理

## 1 · 概念地图:程序、进程、线程、PID、PPID

新手最容易混的几个词:

| 词 | 是什么 | 类比 |
|---|---|---|
| **程序(Program)** | 磁盘上的可执行文件(`hello`、`ls`) | 一份食谱(写在纸上,没动) |
| **进程(Process)** | 程序运行起来的实例,有内存、有状态、有 PID | 正在按食谱炒菜的厨师 |
| **线程(Thread)** | 一个进程里的并行执行单元,共享内存 | 厨师一只手炒菜一只手切料 |
| **PID** | 进程 ID,内核给每个进程的唯一编号 | 厨师的工号 |
| **PPID** | 父进程 ID,启动这个进程的进程的 PID | 师父(招了你的那个人) |
| **退出码(exit code)** | 进程结束时返回的 0-255 数字 | 厨师下班的交接报告 |
| **信号(signal)** | 内核或其他进程发给某进程的"小消息" | 经理拍一下厨师肩膀传话 |

**关键事实**:
- 一个程序可以同时跑多个进程(`firefox` 开三个窗口,可能是三个进程或一个进程多线程,看怎么写的)
- 每个进程有且只有一个父进程(除了 PID 1,它是孤儿院院长)
- 进程不能"凭空启动",只能**从已有进程 fork 出来**(PID 1 是内核直接启动的)
- 信号是非常原始的通信——总共 ~30 种,每种用一个数字编号,不携带数据(除少数例外)

## 2 · 心智模型

### 类比:进程是"小工位",fork 是"复制工位",exec 是"换工作内容"

想象一栋写字楼,每间办公室是一个进程。每间办公室有:
- 一个工位号(PID)
- 一个师父(PPID)
- 一份正在做的工作(代码 + 内存里的数据)
- 一张办公桌(内存)
- 一些打开的文件夹(文件描述符)
- 一个状态牌:"工作中"、"等外卖"、"已下班"

**fork**:某间办公室的员工说"我复制一间完全一样的办公室给自己"。新办公室里所有东西(代码、内存、打开的文件)都和原来一模一样,但工位号不同。两间办公室从此独立工作。

**exec**:某间办公室的员工说"我放下手头工作,换一份新工作"。原来的代码、内存全部被新程序替换,但工位号不变、打开的文件不变(默认)。所以"启动一个新程序"实际上是 fork 出一个新办公室,然后这个新办公室立刻 exec 自己——把自己换成新程序。

**wait**:师父说"我等徒弟完成,把他的交接报告收下"。如果师父不等,徒弟死掉后它的交接报告就没人收,变成僵尸(zombie)。

**signal**:经理发个"小纸条"给某间办公室,内容只有一个词("终止"、"暂停"、"继续")。员工收到时可能正在工作,会**中断当前工作**先处理纸条(默认行为),或自定义处理方式(注册 handler)。

### 严谨原理:进程的生命周期

一个 Linux 进程从生到死的完整链路:

```
                  fork()
[父进程] ──────────────────────► [子进程(父进程的副本)]
                                      │
                                      │ exec(新程序)
                                      ▼
                                  [子进程(运行新程序)]
                                      │
                                      │ 运行 / 等待 / 阻塞
                                      │
                                      ▼
                                  [子进程 exit(退出码)]
                                      │
                                      ▼
                                  [僵尸进程(Z 状态)]
                                      │
                  wait()/waitpid()   │
[父进程] ◄─────────────────────────────┘
                                      │
                                      ▼
                                  [被回收,完全消失]
```

每一步对应一个系统调用(system call,用户态进程请求内核做事的接口):

- `fork()` — 创建子进程(复制当前进程)
- `execve(path, argv, envp)` — 用 `path` 指定的程序替换当前进程的代码和数据
- `waitpid(pid, &status, options)` — 等待子进程结束,取回退出码
- `exit(status)` — 当前进程结束,返回 `status & 0xFF` 给父进程
- `kill(pid, signo)` — 给某 PID 发信号

### 进程状态(`ps` 看到的字母)

```
R (Running)         在 CPU 上跑,或在就绪队列等 CPU
S (Sleeping)        可中断睡眠,等事件(读文件、睡 1 秒……)
D (Disk sleep)      不可中断睡眠,通常在等磁盘 IO(不能被 SIGKILL 外信号打断)
Z (Zombie)          已 exit 但父进程还没 wait,留着一个"空壳"
T (Stopped)         被 SIGSTOP 暂停(如 Ctrl+Z),等 SIGCONT 才继续
```

`ps -el` 第二列就是状态。看到 `Z` 就该处理了(让父进程 wait,或杀掉父进程)。

### 信号:用数字传达一个词

Linux 内核定义的信号(常用部分):

| 编号 | 名字 | 默认行为 | 谁发 | 用途 |
|---|---|---|---|---|
| 1 | SIGHUP | 终止 | 终端关闭 / 手动 | "你的终端没了",守护进程常用它来"重新加载配置" |
| 2 | SIGINT | 终止 | Ctrl+C | "请结束",程序可以拦截做清理 |
| 3 | SIGQUIT | 终止 + core dump | Ctrl+\ | "请结束,且带上现场" |
| 9 | SIGKILL | 终止(不可拦截) | kill -9 | "立刻死,没有商量" |
| 15 | SIGTERM | 终止 | kill 默认 | "请你优雅退出" |
| 18 | SIGCONT | 继续 | kill -18 | 让暂停的进程恢复 |
| 19 | SIGSTOP | 暂停 | Ctrl+Z / kill -19 | 立刻暂停(不可拦截) |
| 11 | SIGSEGV | 终止 + core dump | 内核 | "你访问了非法内存"(野指针、空指针解引用) |
| 6 | SIGABRT | 终止 + core dump | abort() | "assert 失败 / 主动崩溃" |

**关键区分**:
- **SIGKILL(9)** 和 **SIGSTOP(19)** 不能被程序拦截——内核直接处理。这是"无条件终止/暂停"。
- 其他信号默认会终止进程,但程序可以注册 handler 改变行为——比如注册 SIGINT handler 做优雅退出(保存文件、关连接)。

### 退出码

进程 exit 时传一个 8 位无符号整数(0-255)给内核,父进程 wait 时拿到。约定:

- `0` — 成功
- `1-125` — 失败(具体含义看程序自己定义)
- `126` — 没执行权限
- `127` — 命令找不到
- `128 + N` — 被信号 N 杀死(SIGSEGV=11 → 128+11 = 139;SIGKILL=9 → 128+9 = 137)

shell 里 `$?` 是上一条命令的退出码:
```bash
false; echo $?     # 1(false 总返回 1)
true; echo $?      # 0
ls /nonexistent; echo $?  # 2(ls 自己定义:目录不存在)
```

## 3 · 四域深入

### 3.1 · 🐧 Linux 系统编程视角

#### fork/exec/wait 是"三件套"

POSIX 定义的进程 API。Rust 标准库的 `std::process::Command` 把 fork+exec+wait 封装好了,但你要懂底层。

**为什么 fork 和 exec 分开?** 这是 Unix 1970 年代的设计决策,叫 **fork-exec separation**。中间留了窗口,让父进程在 fork 之后、exec 之前**改子进程的环境**:关掉一些文件描述符、重定向 stdin/stdout、改工作目录、设环境变量。这正是 shell 做的——`>` 重定向、`|` 管道,都是 fork 之后 exec 之前做的。

```rust
// 等价的 Rust 底层调用(伪代码,真实 API 用 nix crate 更顺手)
use std::os::unix::process::CommandExt;

let mut cmd = std::process::Command::new("ls");
cmd.arg("-l");
// 在 fork 之后、exec 之前,关掉 stdout,重新打开到 /tmp/out.txt
unsafe {
    cmd.pre_exec(|| {
        // 这里在子进程里,exec 之前
        // 任何 libc::xxx 调用,出错返回 Err
        // 示例:重新设 umask
        libc::umask(0o022);
        Ok(())
    });
}
let status = cmd.status().unwrap();
```

`pre_exec` 是 unsafe 的——因为在多线程程序里 fork 之后只能调"async-signal-safe"的函数,违反就死锁或更糟。Rust 标准库用 unsafe 让你对这个负责。

#### 管道是怎么连起来的

`cat file | grep x` 的实现:
1. shell 创建一个**管道(pipe)**——一对文件描述符 `{read_fd, write_fd}`
2. shell fork 出 cat,在 cat 里把 stdout 重定向到 `write_fd`(关掉 read_fd)
3. shell fork 出 grep,在 grep 里把 stdin 重定向到 `read_fd`(关掉 write_fd)
4. cat 写到 stdout → 管道 → grep 从 stdin 读

```rust
use std::process::{Command, Stdio};

// 用 Rust 实现等价 cat file | grep x
let file = std::fs::File::open("file.txt").unwrap();
let cat = Command::new("cat")
    .stdin(Stdio::from(file))
    .stdout(Stdio::piped())  // stdout 用管道
    .spawn()                 // 注意是 spawn 不是 status,因为要拿 stdout
    .unwrap();
let grep = Command::new("grep")
    .arg("x")
    .stdin(Stdio::from(cat.stdout.unwrap()))  // grep 的 stdin = cat 的 stdout
    .stdout(Stdio::inherit())                 // 直接打印到本进程的 stdout
    .status()
    .unwrap();
```

每个 `Stdio::piped()` 创建一对 pipe fd,`Stdio::from(other.stdout)` 把它接上去。这就是所有 shell 管道的本质。

#### 信号 handler

Rust 注册信号 handler 要用 `signal-hook` crate(因为 signal handler 的限制极严,Rust 标准库不敢给安全封装):

```rust
// Cargo.toml: signal-hook = "0.3"
use signal_hook::consts::SIGINT;
use signal_hook::low_level::{register, emit};
use std::sync::atomic::{AtomicBool, Ordering};

static QUIT: AtomicBool = AtomicBool::new(false);

fn main() {
    // 注册:收到 SIGINT 时,把 QUIT 设为 true
    unsafe {
        register(SIGINT, || QUIT.store(true, Ordering::SeqCst)).unwrap();
    }
    while !QUIT.load(Ordering::SeqCst) {
        std::thread::sleep(std::time::Duration::from_millis(100));
        println!("working...");
    }
    println!("graceful shutdown");
}
```

**为什么不直接在 handler 里做事?** 因为 signal handler 是"随时被中断"的——它可能在主线程正在持有锁时打断,如果你在 handler 里也去抢锁,就死锁。所以工程实践:**handler 只做一件事——设一个 atomic flag**,主循环看 flag 做清理。

HH 后面会用到这个模式:游戏主循环每帧检查 `should_quit`,有就 break。

### 3.2 · 🦀 Rust 生态视角

Rust 标准库的进程 API:

```rust
use std::process::{Command, Stdio, Child};

// 1. 简单运行,等它结束
let status = Command::new("ls").arg("-l").status()?;
// status.code() 是 Option<i32>,被信号杀死时是 None

// 2. 异步运行,拿 Child 句柄
let mut child: Child = Command::new("long_task")
    .stdout(Stdio::piped())
    .spawn()?;
// 干别的事
let status = child.wait()?;  // 等子进程结束

// 3. 杀掉子进程
let mut child = Command::new("loop").spawn()?;
child.kill()?;     // 发 SIGKILL
child.wait()?;     // 必须 wait,否则变僵尸

// 4. 拿子进程的输出
let output = Command::new("echo").arg("hi").output()?;
// output.stdout: Vec<u8>,包含 "hi\n"
// output.status.code() 是退出码
```

**坑**:spawn 之后必须 wait,否则子进程死后变成僵尸——内核保留它的退出信息,等父进程收。父进程不收,僵尸就一直在。`ps` 看到 `Z` 状态就是僵尸。

如果你写长期运行的服务(守护进程),用 `tokio::process::Command` 或 `async-process` crate——异步版本的 Command,集成进异步运行时。

**著名 crate**:
- `nix` — Rust 对 POSIX 的薄封装,直接调 `fork` / `execve` / `kill` / `sigaction`,带类型安全
- `signal-hook` — 信号处理的事实标准
- `tokio::signal` — 异步信号(配合 tokio 运行时)
- `daemonize` — 把自己变成守护进程(setsid + fork + chdir /)

### 3.3 · 🎮 游戏编程视角

HH 里进程相关的几个场景:

1. **Day 1 平台层**:Windows 用 `LoadLibrary` 加载游戏代码 .dll,改了重载;Linux 对应物是 `dlopen` + `dlclose`(在同一进程内,不是子进程)
2. **Day 50+ 音频**:开启音频线程(同进程的多线程,不是多进程)
3. **Day 60+ 日志**:把日志写到文件,或 spawn 一个 `tail -f` 子进程实时看
4. **资产预处理**:启动 `ffmpeg` / `pngquant` 子进程压缩资产,等它结束
5. **崩溃恢复**:主进程崩溃,daemon 监控重启

游戏行业最经典的进程模式是**主进程 + 资源/网络子进程**——比如 MMORPG 把网络放在独立进程,游戏逻辑放在另一进程,共享内存通信。这样网络崩溃不会拖死游戏逻辑。HH 是单进程多线程,这是 Casey 的选择(简单优先)。

### 3.4 · Linux 工具实战

```bash
# 看当前所有进程
ps aux | head
# 输出列:USER PID %CPU %MEM VSZ RSS TTY STAT START TIME COMMAND

# 看进程树(谁是谁的父进程)
pstree -p
# 看到类似:init(1)───systemd-journal(342)
#                ───sshd(1024)───sshd(2048)───bash(2050)───pstree(2099)

# 交互式看进程(更直观)
htop
# F5 显示树形;F6 排序;F9 发信号;F4 过滤

# 看某进程打开的文件
lsof -p <PID>
# 输出:COMMAND PID USER FD TYPE DEVICE SIZE NODE NAME
# ls       1234 sun  3r  REG  8,1   1024 5678 /etc/passwd

# 看某进程的内存映射
cat /proc/<PID>/maps
# 看 /proc/<PID>/status:更易读的进程状态
cat /proc/<PID>/status | head
```

## 4 · 认知地图

### 4.1 上级

- **操作系统抽象** — 进程是 OS 提供的"虚拟机"幻象,让每个程序以为自己独占内存和 CPU
- **并发单元** — 进程 / 线程 / 协程是不同粒度的并发单元
- **IPC (Inter-Process Communication)** — 进程间通信,管道 / 共享内存 / 信号 / socket / 消息队列

### 4.2 同级

| 方案 | 关键差别 | 何时用 | 本项目选了哪个 |
|---|---|---|---|
| 多进程(fork+exec) | 独立内存,容错好,通信贵 | 服务隔离、shell 命令 | HH 平台层用 dlopen,但子进程用于资产管线 |
| 多线程(pthread) | 共享内存,容错差,通信快 | 游戏逻辑 + 渲染 + 音频 | ✅ HH 主线 |
| 协程(async) | 用户态调度,单线程 | IO 密集,高并发 | 网络层可能用 tokio |
| Actor(Erlang/Akka) | 进程级隔离 + 消息 | 高容错分布式 | 不用 |

### 4.3 下级

- **fork** — 复制当前进程
- **execve** — 替换进程映像
- **wait / waitpid** — 等子进程
- **kill** — 发信号
- **sigaction** — 注册 handler
- **pipe / socketpair** — 进程间通信
- **/proc 文件系统** — 内核暴露的进程信息

## 5 · 对照与变奏

### Linux vs Windows 进程 API

| 概念 | Linux | Windows |
|---|---|---|
| 创建进程 | `fork() + execve()` | `CreateProcess()`(一步到位) |
| 复制进程(共享内存) | 不支持(fork 是复制) | `CreateProcess` 不复制 |
| 发信号 | `kill(pid, signo)` | `TerminateProcess`(粗暴) |
| 等子进程 | `waitpid(pid)` | `WaitForSingleObject(handle)` |
| 信号 handler | `sigaction` | `SetConsoleCtrlHandler`(只支持 Ctrl+C 等) |
| 加载动态库 | `dlopen` + `dlsym` | `LoadLibrary` + `GetProcAddress` |

Windows 没有"信号"概念——这是个 Unix 历史包袱。Casey 的 HH 在 Windows 写,所以你看不到 SIGTERM 的处理;后面 Linux 移植版会加上。

### 历史演化

- **1969 Unix**:fork/exec/kill 设计成型,Dennis Ritchie / Ken Thompson
- **1980s POSIX**:标准化信号和 wait
- **2000s Linux 2.6**:引入 NPTL(新 POSIX 线程库),线程终于和进程一样轻
- **2010s**:cgroups / namespaces → 容器(Docker 把进程隔离推到极致)
- **2020s**:io_uring 把 IO 又革命一遍(异步系统调用,绕过 fork/exec 模型)

容器(Docker)本质上就是:**fork + exec + 一堆 namespace 隔离 + cgroup 资源限制**。你学会本篇,以后看 Docker 源码不会陌生。

## 6 · 关联 Day

- **铺垫**:[07-linux-filesystem.md](07-linux-filesystem.md)(文件描述符的概念)、[00-terminal-basics.md](00-terminal-basics.md)(shell 是怎么 fork+exec 的)
- **当天**:本篇
- **后续**:
  - [13-diagnosis-tools.md](13-diagnosis-tools.md)(用 strace 看进程发的系统调用)
  - Phase 1 Day 001-005(平台层,Linux 上 dlopen 加载游戏代码)
  - Phase 4(多线程,JIT,asset 子进程)
  - HH Day 519(Casey 处理 DLL 加载/卸载,Linux 对应 dlopen)

## 7 · 变式训练

### Lv1 · 概念辨析

**题**:为什么 Ctrl+C 杀不死一个 `D` 状态的进程?为什么 `kill -9` 也杀不死?用什么方法能"杀"它?

**参考解答**:`D`(Disk sleep,不可中断睡眠)是内核里的状态——进程在执行某个**不可中断的系统调用**(通常是磁盘 IO,也可能是某些 NFS 操作)。这个状态下,进程**不响应任何信号**,包括 SIGKILL。SIGKILL 的"不可拦截"指的是用户程序不能注册 handler 拦截它,但内核仍要等进程返回到可中断状态才生效。

杀它的方法:等系统调用自己返回(可能几秒到几分钟,或者永远不返回如果是 NFS 挂了)。如果卡死了,只能**重启系统**(因为内核里这个进程持有锁,杀不掉)。

`D` 状态长期出现通常是磁盘/NFS/驱动 bug——开发时遇到要先看是不是 IO 卡住。

### Lv2 · 动手实践

**题**:在 Rust 里实现一个迷你 shell,能跑 `ls`、`pwd`、`echo` 三条命令,支持管道 `|`(至少两段)。要求:
- 读一行,按 `|` 分段
- 对每段,`Command::new(段 0).args(段 1..)` 启动
- 用 `Stdio::piped()` 把上一段的 stdout 接到下一段的 stdin
- 最后一段的 stdout 接到当前进程的 stdout

完成标准:`echo hello | cat` 输出 `hello`;`ls | head -3` 输出当前目录前 3 项。

**参考解答**:

```rust
use std::io::{self, BufRead};
use std::process::{Command, Stdio};

fn main() {
    let stdin = io::stdin();
    loop {
        print!("$ ");
        io::Write::flush(&mut io::stdout()).unwrap();
        let mut line = String::new();
        if stdin.lock().read_line(&mut line).unwrap() == 0 { break; }
        let line = line.trim();
        if line.is_empty() { continue; }

        // 按 | 分段
        let segments: Vec<&str> = line.split('|').map(str::trim).collect();
        // segments = ["echo hello", "cat"]

        let mut prev_stdout: Option<std::process::ChildStdout> = None;
        let mut children: Vec<std::process::Child> = vec![];

        for (i, seg) in segments.iter().enumerate() {
            let parts: Vec<&str> = seg.split_whitespace().collect();
            if parts.is_empty() { continue; }
            let mut cmd = Command::new(parts[0]);
            cmd.args(&parts[1..]);

            // stdin:第一段继承当前进程 stdin;后续段接上一段 stdout
            if let Some(out) = prev_stdout.take() {
                cmd.stdin(Stdio::from(out));
            } else {
                cmd.stdin(Stdio::inherit());
            }

            // stdout:最后一段继承当前进程 stdout;其他段用 piped
            let is_last = i == segments.len() - 1;
            if is_last {
                cmd.stdout(Stdio::inherit());
            } else {
                cmd.stdout(Stdio::piped());
            }

            let mut child = cmd.spawn().expect("spawn failed");
            if !is_last {
                prev_stdout = child.stdout.take();
            }
            children.push(child);
        }

        // 等所有子进程结束
        for mut c in children {
            c.wait().expect("wait failed");
        }
    }
}
```

**每行解释**:
- `io::Write::flush(&mut io::stdout())` — 强制刷新 stdout,让 `$ ` 立刻显示(否则会卡到下个换行才输出)
- `child.stdout.take()` — 把 Child 里的 stdout Option 取出来(变成 owned),这样能传给下一段。`take` 让原 Child.stdout 变 None,但子进程还在跑
- `Stdio::from(out)` — 把一个已存在的 fd 当作子进程的 stdin
- 最后才 wait——避免死锁(如果先 wait 第一段,管道缓冲区满,它会阻塞,但消费者还没启动)

### Lv3 · 迁移设计

**题**:你要写一个**子进程崩溃自动重启**的 wrapper,要求:
- 启动子进程(`target/release/game`),传给它所有命令行参数
- 等它结束
- 如果退出码 != 0,**最多重启 5 次**,每次之间等 1 秒
- 收到 SIGINT(Ctrl+C)时,把信号转发给子进程(让它优雅退出),不再重启

写出关键代码骨架(不用全跑通,关键是逻辑正确)。提示:
- 用 `Command::spawn` 拿到 `Child`
- 用 `signal-hook` 注册 SIGINT,设 atomic flag
- 子进程的 PID 怎么发 SIGINT?用 `nix::sys::signal::kill(Pid::from_raw(child.id() as i32), Signal::SIGINT)`

**提示**:`child.id()` 返回子进程 PID,但 Rust 标准库没提供"给 Child 发信号"的 API,要用 libc 或 nix crate 直接 `kill`。

### Lv4 · 开源贡献

**题**:`nix` crate 是 Rust 对 POSIX 的薄封装,GitHub: https://github.com/nix-rust/nix

1. clone 它,看 `src/sys/signal.rs` 里 signal handler 的封装
2. **可能的贡献**:
   - `nix` 的 doc 里某些函数(如 `SigSet::add`)没给完整例子,你补一个 doctest
   - 找 issue 标签 `good first issue` 的,认领一个
   - `src/unistd/fork.rs` 的 Pid::from_raw 文档可以更清楚
3. 写 PR 描述(repo / 文件 / 动机 / 验证)

**示例**:在 `src/sys/signal.rs` 的 `signal` 函数文档下面加一个 doctest,演示怎么注册 SIGINT handler。

## 8 · Rust / Arch 落地代码

### 完整可跑示例:子进程 + 信号

```rust
// Cargo.toml:
// [dependencies]
// signal-hook = "0.3"
// nix = { version = "0.29", features = ["signal"] }

use signal_hook::consts::{SIGINT, SIGTERM};
use signal_hook::low_level::register;
use std::process::Command;
use std::sync::atomic::{AtomicBool, Ordering};

static SHOULD_QUIT: AtomicBool = AtomicBool::new(false);

fn main() {
    // 1. 注册信号 handler——只设 flag
    unsafe {
        register(SIGINT, || SHOULD_QUIT.store(true, Ordering::SeqCst))
            .expect("register SIGINT");
        register(SIGTERM, || SHOULD_QUIT.store(true, Ordering::SeqCst))
            .expect("register SIGTERM");
    }
    println!("parent pid = {}", std::process::id());

    // 2. fork 一个子进程跑 cargo --version
    let mut child = Command::new("sleep")
        .arg("10")
        .spawn()
        .expect("spawn failed");
    println!("child pid = {}", child.id());

    // 3. 等 3 秒,然后发 SIGTERM 给子进程
    for i in 1..=3 {
        if SHOULD_QUIT.load(Ordering::SeqCst) {
            println!("parent got quit signal, killing child");
            let _ = nix::sys::signal::kill(
                nix::unistd::Pid::from_raw(child.id() as i32),
                nix::sys::signal::Signal::SIGTERM,
            );
            break;
        }
        std::thread::sleep(std::time::Duration::from_secs(1));
        println!("parent: {i}s elapsed");
    }

    // 4. wait 子进程,拿到退出信息
    let status = child.wait().unwrap();
    println!("child exit: {status:?}");
    // 如果是被信号杀死的,status.signal() 会是 Some(SIGTERM)
}
```

**关键 Rust 特性**:
- `AtomicBool` — 多线程安全的 bool,不用 Mutex。`Ordering::SeqCst` 是最强的内存序,保证所有线程看到一致顺序
- `unsafe { register(...) }` — signal-hook 的 register 是 unsafe,因为 handler 在 restricted environment 跑
- `child.id()` 返回 u32,但 nix 要 i32 PID,所以 cast `as i32`
- `child.wait()` 是阻塞的——它会一直等到子进程结束

### Arch 命令实战

```bash
# 1. 装必备工具
sudo pacman -S --needed procps-ng psmisc htop lsof strace

# procps-ng 提供 ps / top / free / sysctl
# psmisc 提供 killall / pstree / fuser
# htop 交互式进程查看
# lsof 看 fd / 网络连接 / 文件
# strace 追踪系统调用(下一篇章详细讲)

# 2. 看当前 shell 的 PID
echo $$
# 输出如:12345 —— 这是你当前 bash 的 PID

# 3. 看 shell 的父进程
ps -o pid,ppid,cmd -p $$
# 输出:
#   PID  PPID CMD
# 12345 12340 bash
# PPID 12340 是 bash 的父(可能是 tmux 或 terminal)

# 4. 递归看进程树到 PID 1
pstree -aps $$
# 输出:systemd,1───...───tmux,12340───bash,12345───pstree,12399

# 5. 后台运行
sleep 100 &
# 输出:[1] 12350 —— 12350 是 PID,[1] 是 job id

jobs
# 输出:[1]+  Running                 sleep 100 &

fg %1   # 把 job 1 拉回前台
# 现在前台是 sleep,Ctrl+C 能杀它

# 6. 发信号
kill -SIGTERM 12350   # 等价于 kill 12350(默认 SIGTERM)
kill -SIGKILL 12350   # 强制杀,等价于 kill -9 12350
kill -SIGSTOP 12350   # 暂停(等价于 Ctrl+Z)
kill -SIGCONT 12350   # 继续

# 7. 看僵尸进程
ps -el | grep 'Z'
# 输出:F S   UID   PID  PPID  ...  Z  ...  cmd
# 看到 Z 状态的进程,看它 PPID,kill 那个 PPID 让它 reap

# 8. 看某进程的系统调用(下一篇详讲)
sudo strace -p 12350
# 实时看它调用什么系统调用

# 9. 看某进程打开的文件
lsof -p 12350
# 输出列:COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME
# FD 列:0r=stdin 读,1w=stdout 写,2w=stderr 写,3r=第 3 个 fd 读...

# 10. 看进程的内存映射
cat /proc/12350/maps
# 输出形如:
# 55a7c1234000-55a7c1235000 r--p 00000000 08:01 1234 /usr/bin/sleep
# 这是 ELF 文件加载后的段映射
```

### Troubleshooting

- **"defunct" / "Z" 进程一堆**:父进程没 wait。看 PPID,kill 父进程或重启它
- **`kill 1234` 杀不掉**:进程可能在 D 状态(看 `ps -o stat -p 1234`),或权限不够(用 `sudo kill`)
- **后台进程在 SSH 断开后死了**:你退出 SSH 时,SIGHUP 发给所有子进程。用 `nohup cmd &` 或 `tmux`/`screen` 隔离
- **子进程 print 没显示**:可能 stdout 没 flush,Rust 默认行缓冲但管道是块缓冲——加 `io::Write::flush()`

## 9 · 延伸阅读(可选补充,非必需)

本仓库本地:
- [00-terminal-basics.md](00-terminal-basics.md) — shell 的 fork+exec 循环
- [13-diagnosis-tools.md](13-diagnosis-tools.md) — 用 strace 看进程发的系统调用
- [phase-0/README.md](README.md) — 起步营总览

外部稳定 URL:
- Arch Wiki Process(信号 / job control 详解):https://wiki.archlinux.org/title/Process
- man 7 signal(信号完整列表):`man 7 signal`
- man 2 fork / man 2 execve / man 2 waitpid(系统调用详情)
- The Linux Programming Interface(Michael Kerrisk,圣经级)

真实开源源码:
- `nix` crate signal.rs:https://github.com/nix-rust/nix/blob/master/src/sys/signal.rs
- bash 源码 jobs.c(作业控制实现):https://git.savannah.gnu.org/cgit/bash.git/tree/jobs.c
- util-linux 的 kill.c(看看 kill 命令自己怎么写):https://github.com/util-linux/util-linux/blob/master/kill.c
