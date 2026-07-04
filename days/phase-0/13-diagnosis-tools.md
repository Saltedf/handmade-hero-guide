
# 13 · 诊断工具:strace / ltrace / gdb / perf / valgrind / flamegraph

> 你的程序崩溃了——segmentation fault,没说在哪。你的程序慢——比预期慢 100 倍,看不出哪段卡。你的程序内存爆了——但你看不出哪里泄漏。这些场景下,光看源码是没用的——你需要"看穿运行时"的工具。这一篇把 Linux 5 大诊断工具讲透。

## 0 · 为什么要有这一天

写代码,你 50% 时间在写,50% 时间在**搞清楚为什么不工作**。后 50% 的工具就是诊断工具:

1. **崩溃**:程序输出 `Segmentation fault (core dumped)`,哪行崩的?指针指向哪?
2. **慢**:`cargo run` 跑得动但 5 FPS,哪段最慢?CPU 卡哪?是 IO?
3. **内存涨**:跑一小时,内存从 50MB 涨到 5GB,泄漏在哪?
4. **奇怪行为**:程序说 "permission denied",但它没说在试图访问哪个文件
5. **死锁**:多线程程序卡住不动,4 个线程都在等谁?
6. **依赖黑盒**:`winit` 库内部到底调了什么系统调用?

每个问题对应一个工具:
- **strace** — 看进程发了哪些**系统调用**
- **ltrace** — 看进程调了哪些**库函数**
- **gdb** — 程序崩溃后**看现场**,设断点单步
- **perf** — 程序的**性能**采样
- **valgrind** — **内存错误**(泄漏 / 越界 / 未初始化)
- **flamegraph** — 把性能数据画成**火焰图**

学会这些,你不再"调 bug 靠猜"。

**心理锚点**:这一篇读完,你能:
- 用 strace 看 `ls` 调了什么系统调用
- 用 gdb 在 Rust 程序里设断点、看变量
- 用 perf 找到程序的 hot path
- 用 valgrind 找内存泄漏(对 C/C++ 代码尤其有用)
- 生成 flamegraph,秒看哪段函数占 CPU 最多

## 1 · 概念地图:六大诊断工具

| 工具 | 看什么 | 何时用 | 性能开销 |
|---|---|---|---|
| **strace** | 系统调用(`read`, `write`, `open` 等) | "程序在干啥",IO 卡顿 | 大(每 syscall 拦截) |
| **ltrace** | 库函数调用(libc 的 `malloc`, `printf`) | 看调用了哪些动态库函数 | 中 |
| **gdb** | 进程内部状态(寄存器、内存、栈) | 崩溃调试、断点、单步 | 几乎无(只在断点停) |
| **perf** | CPU 性能采样、cache miss、分支预测 | 找性能瓶颈 | 极小(采样率可调) |
| **valgrind** | 内存错误、泄漏、未初始化读 | C/C++ 内存 bug | 极大(10-50 倍慢) |
| **flamegraph** | 把 perf 数据可视化 | 一眼看 hot path | 离线分析 |

### 工具的关系

```
源码 ────► 编译 ────► 进程 ────► 行为
                       │           │
                  gdb attach       │
                                  │
                          strace/ltrace/perf/valgrind 观测
                                  │
                                  ▼
                            输出 → 分析 → 修复
```

`gdb` 是**侵入式**的(控制进程),其他是**观测式**的(不打断,只看)。

## 2 · 心智模型

### 类比:程序是"黑盒汽车",工具是"诊断仪"

想象你的车坏了:
- **strace** = 仪表盘的行车记录仪,记录"刹车 / 油门 / 转向"每秒的动作
- **ltrace** = 同上,但记录更细:"变速箱换挡 / ABS 启动"
- **gdb** = 修车师傅,把车拆开看每一颗螺丝
- **perf** = 油耗仪,记录哪段路最耗油
- **valgrind** = 排放检测,看哪里漏油
- **flamegraph** = 把油耗数据画成图,一眼看哪段最烧

每个工具不同维度看同一辆车。

### 系统调用 = 用户态 / 内核态边界

回顾 [08 进程与信号](08-processes-and-signals.md):程序运行在**用户态**,要读文件 / 写网络 / 创建进程时,**陷入内核**(trap),内核做完再返回。这个"陷入 + 返回"就是**系统调用(syscall)**。

```
用户态进程
   │
   │ read(fd, buf, 100)        ← 用户调 libc 的 read
   ▼
   libc 的 read wrapper
   │
   │ syscall instruction       ← 触发陷阱,CPU 切到内核态
   ▼
   内核:sys_read() 实现
   │
   │ 返回值(读了多少字节)
   ▼
   libc 把返回值传给用户
```

strace 就是在"syscall instruction"这一刻拦截,记录"什么 syscall、什么参数、什么返回值"。

### perf 的"采样"原理

perf 不拦截每个调用(那样太慢),而是**每隔 N 个 CPU 周期**采样一次"现在在跑哪个函数"。统计 10 万次采样,函数 A 占 60%,函数 B 占 30%……就是性能分布。

```
采样 #1: 正在跑 main()
采样 #2: 正在跑 parse()
采样 #3: 正在跑 parse()
采样 #4: 正在跑 parse()
采样 #5: 正在跑 render()
...
统计:parse 占 70%,render 占 20%,main 占 10%
```

这是 **statistical profiling**——牺牲一点精度换性能。10000 个样本足够准。

### valgrind 的"虚拟 CPU"

valgrind 不采样,它把你的程序**翻译成自己的中间语言**(IR),在虚拟 CPU 上跑,每条内存操作都检查。这就是为什么它慢 10-50 倍——每个指令多了几条检查。

但它能查出**所有**内存错误:越界、悬垂指针、双重释放、未初始化读、泄漏。C/C++ 程序员的救星。

Rust 的内存安全由编译器保证,理论上不需要 valgrind。但:
- Rust 的 unsafe 块可能有 bug
- Rust 调 C 库(FFI)那部分 C 代码可能有问题
- Rust 的逻辑泄漏(忘了释放资源)valgrind 也能帮看

## 3 · 四域深入

### 3.1 · strace:看系统调用

#### 装和基本用法

```bash
sudo pacman -S strace

# 跑一个命令,看它的 syscall
strace ls
# 输出(截选):
# execve("/usr/bin/ls", ["ls"], 0x7ff...) = 0
# brk(NULL)                            = 0x55a7c1234000
# mmap(NULL, 8192, PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANONYMOUS, -1, 0) = 0x7f1234567000
# openat(AT_FDCWD, ".", O_RDONLY|O_NONBLOCK|O_CLOEXEC|O_DIRECTORY) = 3
# getdents64(3, 0x55a7c1250000, 131072) = 480
# write(1, "file1.txt\nfile2.rs\n", 19)  = 19
# close(3)                              = 0
# exit_group(0)                         = ?

# 看每行格式:
# syscall_name(arg1, arg2, ...) = return_value
```

**读 strace 输出**:
- `execve` — 启动新程序(替换当前进程映像)
- `brk` / `mmap` — 分配内存
- `openat` — 打开文件,返回 fd(这里是 3)
- `getdents64` — 读目录内容
- `write(1, ...)` — 写到 fd 1(就是 stdout)
- `close` — 关闭 fd
- `exit_group` — 进程结束

#### 常用参数

```bash
# 只看特定 syscall(逗号分隔)
strace -e openat,read,write ls
# 只看文件 IO

# 看子进程(默认只看主进程)
strace -f cargo build
# -f follow fork,跟踪子进程

# 看时间(每个 syscall 耗时)
strace -T ls
# 输出:read(3, ..., 1024) = 100  <0.000123>
#                       耗时 ^^^^^^^^^

# 看时间戳
strace -tt ls
# 输出:11:22:33.123456 openat(...) = 0

# 统计:每个 syscall 调用次数 + 总耗时
strace -c ls
# 输出:
# % time     seconds  usecs/call     calls    errors syscall
# ------ ----------- ----------- --------- --------- ----------------
#   50.00    0.000100           5        20           read
#   30.00    0.000060           6        10           write
#   20.00    0.000040           4        10           openat
# ------ ----------- ----------- --------- --------- ----------------
# 100.00    0.000200                    40           total

# attach 到已经在跑的进程
sudo strace -p <PID>
```

#### 实战:程序卡 IO,看为什么

```bash
# 你的 cargo build 卡住了
sudo strace -p $(pgrep -f "cargo build") -e read,write,openat -tt
# 看到 read 卡在哪个 fd 上,卡了多久
```

这是定位"网络挂了 / NFS 卡了 / 磁盘慢"的金标准。

### 3.2 · ltrace:看库函数调用

```bash
sudo pacman -S ltrace

ltrace ls
# 输出:
# malloc(40)                              = 0x55a7c1250000
# strlen(".")                             = 1
# readdir64(0x55a7c1244000)              = 0x55a7c1245000
# printf("%s\n", "file1.txt")             = 11
# free(0x55a7c1250000)                    = <void>
```

ltrace 看**动态库函数**(libc、libstdc++ 等),不是 syscall。

Rust 程序默认静态链接 Rust 标准库,ltrace 看不到 Rust 内部函数。但能看到 libc 调用(malloc/free/write 等)。

### 3.3 · gdb:进程内调试

#### 装

```bash
sudo pacman -S gdb
# Rust 增强(可选,显示更好):
cargo install gdbgui    # GUI 前端(浏览器)
```

#### 基本用法

```bash
# 启动程序 + gdb
gdb ./target/debug/my-program

# 或 attach 到跑的进程
sudo gdb -p <PID>

# gdb 提示符:
(gdb)
```

#### gdb 常用命令

```
(gdb) break main              # 在 main 函数设断点
(gdb) break src/main.rs:42    # 在 main.rs 第 42 行断点
(gdb) break *0x55a7c1234567   # 在某地址断点(高级)
(gdb) info breakpoints        # 看所有断点
(gdb) delete 1                # 删除断点 1

(gdb) run                     # 跑程序(到第一个断点停)
(gdb) run arg1 arg2           # 带参数跑
(gdb) continue                # 继续到下个断点
(gdb) next                    # 下一行(不进函数)
(gdb) step                    # 下一行(进函数)
(gdb) finish                  # 跑完当前函数
(gdb) until 100               # 跑到第 100 行

(gdb) print x                 # 打印变量 x
(gdb) print *ptr              # 解引用指针
(gdb) print vec.size()        # 调用方法
(gdb) display x               # 每步都打印 x
(gdb) info locals             # 看所有局部变量
(gdb) info args               # 看函数参数

(gdb) backtrace               # 看调用栈(bt 简写)
(gdb) bt full                 # 带局部变量的调用栈
(gdb) frame 2                 # 切到第 2 帧
(gdb) up / down               # 上下移一帧

(gdb) x/10xw 0x...            # 看内存,16 进制,10 个 word
(gdb) x/10i $pc               # 看接下来的 10 条汇编指令

(gdb) watch x                 # x 变化时停
(gdb) awatch x                # x 读或写时停

(gdb) thread apply all bt     # 所有线程的栈
(gdb) info threads            # 列所有线程

(gdb) quit                    # 退出
```

#### 调试崩溃程序

```bash
# 编译时带 debug info
cargo build   # debug 模式默认有 debug info

# 让程序崩溃时产生 core dump
ulimit -c unlimited    # 当前 shell 允许 core dump

# 跑崩溃程序
./target/debug/my-program
# 输出:Segmentation fault (core dumped)
# ls 显示 core 或 core.1234 文件

# gdb 看 core dump
gdb ./target/debug/my-program core
(gdb) bt
# 看到崩溃栈:
# #0  0x... in my_crate::parse (s=...) at src/parse.rs:42
# #1  0x... in my_crate::main () at src/main.rs:10
```

#### Rust + gdb 注意

Rust 用 gdb 需要 rustc 生成的 debug info(默认开)。但 gdb 不懂 Rust 的所有权 / lifetime / trait,只看底层类型。看 `String` 会看到三个字段(ptr、len、cap),不是字符串本身。

更友好的方式:
```bash
# 装 rust-gdb 包装器(实际上是 gdb 配了 pretty-printer)
rustup component add rust-src   # 可选,看源码用
# Arch 已经包了 rust-gdb
rust-gdb ./target/debug/my-program
# 看到 String 时直接显示 "hello"
```

#### rust-lldb(Rust 替代)

```bash
sudo pacman -S lldb
rust-lldb ./target/debug/my-program
# 命令和 gdb 类似,部分语法不同
```

macOS 上 lldb 是默认(因为 macOS gdb 不好用),Linux 上 gdb 是默认。

### 3.4 · perf:CPU 性能采样

#### 装

```bash
sudo pacman -S perf    # 在 linux-tools 包
# 或:
sudo pacman -S linux-tools-$(uname -r)  # 内核对应版本
```

需要 kernel `perf_event_paranoid` 设宽松:

```bash
# 看当前
cat /proc/sys/kernel/perf_event_paranoid
# 4 = 严格(只能看自己进程)
# 2 = 默认
# 1 = 宽松
# -1 = 完全开放

# 临时设宽松(让普通用户也能用 perf)
echo 1 | sudo tee /proc/sys/kernel/perf_event_paranoid
# 永久:加到 /etc/sysctl.d/99-perf.conf
```

#### 基本用法

```bash
# 1. 简单 stat:跑一次程序,看 CPU 周期、cache miss 等
perf stat ./target/release/my-program
# 输出:
#  1234.55 msec task-clock
#       12345 context-switches
#         234 cpu-migrations
#        1234 page-faults
#   4,567,890,123 cycles
#   2,345,678,901 instructions
#         456 cache-misses
#  1.234 seconds elapsed

# 2. record:采样程序运行
perf record --call-graph=dwarf ./target/release/my-program
# 生成 perf.data

# 3. report:看结果
perf report
# 进入交互式 UI
# 按 / 搜索,f 展开,b 看 flamegraph 数据
```

#### Flamegraph

flamegraph 把 perf 数据画成可视化图。

```bash
# 装 flamegraph 工具
cargo install flamegraph
# Arch 也提供: sudo pacman -S flamegraph

# 一行命令(自动 perf + 生成 svg)
cargo flamegraph --release --bin my-program
# 生成 flamegraph.svg,浏览器打开
```

**怎么看火焰图**:

```
▼main
▼render_frame
▼draw_mesh
▼shade_pixel
■ for loop 70% CPU    ← 横条越长 = 越占 CPU
▼shade_pixel
▼update_physics
```

- 横轴:CPU 占用百分比
- 纵轴:调用栈深度
- 找最长的横条 = hot spot

#### Brendan Gregg 的 perf cheat sheet

参考 http://www.brendangregg.com/perf.html 完整教程。常用 10 个命令:

```bash
# Top CPU consumers
perf top

# CPU cycles by function
perf record -F 99 -g --call-graph=dwarf ./my-program
perf report

# Schedule statistics
perf stat -e sched:sched_switch ./my-program

# Cache misses
perf stat -e cache-misses,cache-references ./my-program

# Branch mispredictions
perf stat -e branches,branch-misses ./my-program

# Syscall counts
perf stat -e 'syscalls:sys_enter_*' ./my-program

# Trace specific syscall
perf trace -e openat ./my-program

# Per-process
perf stat -p <PID>

# Memory
perf stat -e LLC-loads,LLC-load-misses ./my-program
```

### 3.5 · valgrind:内存检查

```bash
sudo pacman -S valgrind

# 检查 C 程序(假设你写了 hello.c)
gcc -g hello.c -o hello
valgrind --leak-check=full ./hello
# 输出:
# ==12345== Memcheck, a memory error detector
# ...
# ==12345== HEAP SUMMARY:
# ==12345==   in use at exit: 100 bytes in 1 blocks
# ==12345==   total heap usage: 5 allocs, 4 frees, 1,234 bytes allocated
# ==12345==
# ==12345== 100 bytes in 1 blocks are definitely lost in loss record 1 of 1
# ==12345==    at 0x483BE63: malloc (vg_replace_malloc.c:299)
# ==12345==    by 0x401145: main (hello.c:8)
# ==12345==
# ==12345== LEAK SUMMARY:
# ==12345==    definitely lost: 100 bytes in 1 blocks
```

**关键选项**:
- `--leak-check=full` — 详细报告泄漏
- `--show-leak-kinds=all` — 显示所有泄漏类型
- `--track-origins=yes` — 跟踪未初始化值的来源
- `--tool=callgrind` — 用 callgrind 工具(函数调用统计)
- `--tool=massif` — 堆内存使用统计

#### valgrind 工具集

| 工具 | 干啥 |
|---|---|
| memcheck(默认) | 内存错误(泄漏、越界、未初始化) |
| callgrind | 函数调用次数 + cache 命中 |
| cachegrind | cache 仿真 |
| helgrind | 多线程 race condition |
| drd | 多线程 race |
| massif | 堆内存 profile |

### 3.6 · Rust 特有:dhat / cargo Instruments

Rust 项目优先用:
- **cargo flamegraph** — 看 hot path(本篇已讲)
- **dhat-rs** — Rust 内存 profile crate
- **cargo-bench + criterion** — 微基准
- **tui-prof** — terminal UI 的 perf viewer

```bash
# 装 dhat
cargo add dhat
# 在 main.rs:
# use dhat::Dhat;
# let _dhat = Dhat::new_heap();
# 程序结束时打印堆 profile
```

## 4 · 认知地图

### 4.1 上级

- **Observability(可观测性)** — 系统/程序的状态可被外部观测的程度
- **Profiling** — 测量程序某方面(性能 / 内存 / IO)的技术
- **Tracing** — 记录程序执行轨迹

### 4.2 同级

| 工具 | 看什么 | 开销 | 项目用 |
|---|---|---|---|
| strace | syscall | 1-10 倍慢 | 临时调试 |
| ltrace | 库函数 | 中 | 临时调试 |
| gdb | 进程状态 | 几乎无(只在断点) | 开发期 |
| perf | CPU/Cache | <1% | 生产可接受 |
| valgrind | 内存 | 10-50 倍慢 | 测试期 |
| flamegraph | 视觉化 | <1%(perf 采样) | 性能分析 |
| eBPF / bpftrace | 内核事件 | 极低 | 生产(进阶) |

### 4.3 下级

- **ptrace(系统调用)** — strace/gdb 实现的基础
- **perf_event_open(系统调用)** — perf 实现的基础
- **uprobes / kprobes** — 用户态 / 内核态探针
- **DWARF debug info** — 让工具把机器地址映射回源码
- **eBPF** — 现代 Linux tracing 终极武器

## 5 · 对照与变奏

### 不同语言的诊断工具

| 语言 | 主力工具 |
|---|---|
| C / C++ | gdb + valgrind + perf |
| Rust | gdb/lldb + perf + flamegraph + cargo-instruments |
| Go | pprof(内置)+ delve |
| Python | cProfile + pdb |
| Java | JFR / VisualVM / async-profiler |

Rust 因为编译成原生 binary,所以和 C 工具链相同。这是 Rust 比 Java/Python 优势之一(更接近底层)。

### 静态 vs 动态分析

| | 静态 | 动态 |
|---|---|---|
| 何时 | 编译期 | 运行期 |
| 工具 | clippy / rustc / sonar | strace / gdb / perf |
| 找什么 | 代码模式问题(可能 bug) | 实际发生的 bug |

Rust 的 clippy 是强力静态分析,能预防很多 bug。但运行时的诊断工具仍然不可或缺。

### 历史

- **1970s ptrace** — Unix V7 引入,debugger 基础
- **1980s gdb** — Richard Stallman 写
- **1990s strace** — Linux 出现
- **2000s valgrind** — Julian Seward 写
- **2010s perf** — Linux 内核自带,eBPF 兴起
- **2020s eBPF** — 现代 observability 革命(Cilium / Pixie / Parca)

eBPF 是下一代 tracing,允许在内核跑小程序观测事件。本篇不讲,但你应该知道名字。

## 6 · 关联 Day

- **铺垫**:[08-processes-and-signals.md](08-processes-and-signals.md)(系统调用 / 进程)、[09-editor-toolchain.md](09-editor-toolchain.md)(cargo)
- **当天**:本篇
- **后续**:
  - [15-c-and-assembly-reading.md](15-c-and-assembly-reading.md)(用 objdump 看汇编)
  - Phase 1 Day 001-005(平台层出 bug 时用 gdb)
  - Phase 4 Day 112+(性能优化,perf + flamegraph 主力)
  - Phase 5(Debug 系统,用 perf 数据驱动优化)

## 7 · 变式训练

### Lv1 · 概念辨析

**题**:你用 perf record 跑程序,生成 perf.data,然后 perf report 看到 `Unknown Symbol` 或地址而不是函数名。为什么?怎么修?

**参考解答**:perf 需要**调试符号**把地址映射到函数名。如果你跑的是 `--release` 编译的二进制,Rust 默认 strip debug info(为了二进制小)。

修法:
- 跑 debug build:`cargo build`(默认有 debug info)
- 或 release 保留 debug:`Cargo.toml` 加 `[profile.release] debug = true`
- 或用 `dwarf` 调用图:`perf record --call-graph=dwarf` 而不是默认的 `fp`

### Lv2 · 动手实践

**题**:用 strace 跑下面命令,记录输出 + 解释每个 syscall:

```bash
strace -e trace=openat,read,write,close echo "hello"
```

完成标准:能说清每个 syscall 干了什么。

**参考解答**:

```
openat(AT_FDCWD, "/etc/ld.so.cache", O_RDONLY|O_CLOEXEC) = 3
# 打开 ld.so.cache(动态链接器缓存,加速找 .so)
# 返回 fd 3

# ... 一堆加载 libc.so.6 等共享库的 syscall ...

read(3, ..., 8192) = 8192
# 读 ld.so.cache 内容
close(3) = 0
# 关闭 cache

write(1, "hello\n", 6) = 6
# echo 把 "hello\n" 写到 fd 1(stdout),返回写了 6 字节

exit_group(0) = ?
# 进程退出
```

每个 syscall 模式:`name(arg1, arg2, ...) = return_value`。

### Lv3 · 迁移设计

**题**:你的 Rust 程序 `cargo build` 卡住 30 秒不动,你想知道为什么。设计一个诊断流程,用本篇工具排查。

**提示**:
- 第一步:strace 看 cargo 进程在等什么(哪个 fd / 哪个 syscall 卡住)
- 第二步:如果是网络 fd,可能是 crates.io 慢 → 配镜像
- 第三步:如果是磁盘 fd,可能是磁盘满 / IO 慢 → 看 `iostat`
- 第四步:如果是 cpu 100%,perf 看哪个函数占 CPU
- 第五步:多线程死锁 → gdb attach 看 `info threads`

写出每步的具体命令 + 你期望看到的输出特征。

### Lv4 · 开源贡献

**题**:flamegraph 工具本身是开源的 Rust crate,GitHub: https://github.com/flamegraph-rs/flamegraph

1. clone 它,读源码,看它怎么调 perf / dtrace
2. **可能的贡献**:
   - README 里某个 flag 没解释清楚,补一段
   - 某个 error message 模糊(比如 perf not found),改成更友好的提示
   - 加 unit test 覆盖某个未测的函数
3. fork → branch → 改 → PR

写下你打算提的 PR 描述。

## 8 · Rust / Arch 落地代码

### 完整示例:用 perf + flamegraph 找性能瓶颈

```rust
// src/main.rs —— 故意写一个有 hot spot 的程序
fn main() {
    let n: u64 = 1_000_000;
    let mut sum = 0u64;
    for i in 0..n {
        sum = sum.wrapping_add(slow_function(i));
    }
    println!("sum = {}", sum);
}

fn slow_function(x: u64) -> u64 {
    // 故意低效:多次 mod
    let mut result = 0;
    for j in 0..100 {
        result += x % (j + 1);
    }
    result
}
```

跑 + 分析:

```bash
# 1. 编译 release(否则 debug 优化会扭曲结果)
cargo build --release

# 2. 用 cargo-flamegraph 一键生成
cargo flamegraph --release --bin my-program
# 自动:perf record → 生成 flamegraph.svg → 浏览器打开

# 3. 手动 perf
perf record --call-graph=dwarf ./target/release/my-program
# 完成后看 perf.data

# 4. 看 report
perf report
# 交互式 UI,看到 slow_function 占 95% CPU

# 5. 优化:slow_function 的内层 mod 可以缓存或并行
# 改完重新跑 flamegraph,确认 hot spot 消失
```

### Rust 程序的 gdb 调试

```bash
# 编译(默认 debug 模式,带 debug info)
cargo build

# gdb 启动
rust-gdb ./target/debug/my-program

# 在 gdb 内
(gdb) break my_program::main
(gdb) break my_program::slow_function
(gdb) run
# 停在 main
(gdb) next
(gdb) print n
# $1 = 1000000
(gdb) continue
# 停在 slow_function
(gdb) print x
# $2 = 0
(gdb) bt
# #0  my_program::slow_function (x=0) at src/main.rs:11
# #1  0x... in my_program::main () at src/main.rs:6
(gdb) finish  # 跑完这个函数
(gdb) continue
```

### 系统调用追踪

```bash
# 1. 简单追踪
strace -e trace=write,openat ./target/release/my-program

# 2. 看时间分布
strace -c ./target/release/my-program
# 输出每个 syscall 的次数 / 总耗时

# 3. 看 malloc / free(C 层)
ltrace -e malloc+free ./target/release/my-program

# 4. 看子进程
strace -f cargo build
# 看到 cargo fork 出 rustc,rustc 调 gcc 等
```

### 内存检查(对 unsafe Rust 或 FFI)

```rust
// 故意写一个 unsafe 越界
fn main() {
    let v = vec![1, 2, 3];
    unsafe {
        let ptr = v.as_ptr();
        // 故意越界读
        let x = *ptr.add(100);
        println!("{}", x);
    }
}
```

```bash
# Rust 程序,先编译
cargo build

# valgrind 跑
valgrind --leak-check=full --show-error-context=yes ./target/debug/my-program
# 输出:Invalid read of size 4
#    at 0x...: my_program::main (src/main.rs:5)
#  Address 0x... is 388 bytes after a block of size 12 alloc'd
```

Rust 程序用 valgrind 一般不出错(因为安全 Rust 编译期检查),但 unsafe / FFI 部分 valgrind 能抓。

### 一键分析脚本

```bash
#!/bin/bash
# analyze.sh <binary>
BIN="$1"

echo "=== 1. Strace summary ==="
strace -c "$BIN" 2>&1 | tail -25

echo ""
echo "=== 2. Perf stat ==="
perf stat "$BIN" 2>&1 | tail -25

echo ""
echo "=== 3. Flamegraph ==="
perf record -F 99 --call-graph=dwarf -o /tmp/perf.data "$BIN"
perf script -i /tmp/perf.data | flamegraph-script > /tmp/flamegraph.svg
echo "Flamegraph saved to /tmp/flamegraph.svg"

echo ""
echo "=== 4. Valgrind memcheck ==="
valgrind --leak-check=full --error-exitcode=1 "$BIN" 2>&1 | tail -30
```

### Troubleshooting

- **`perf record` 报 "Permission denied"**:perf_event_paranoid 太严,`echo 1 | sudo tee /proc/sys/kernel/perf_event_paranoid`
- **flamegraph 没函数名,只有地址**:debug info 丢了。`Cargo.toml` 加 `[profile.release] debug = true`
- **valgrind 不工作**:Rust 程序默认 stack-protector-strong 会让 valgrind 误报。用 `RUSTFLAGS="-C stack-protector=none"` 重编
- **gdb 看不到 Rust 类型**:`rust-gdb` 而不是 `gdb`,前者带 pretty-printer
- **strace 输出爆炸**:用 `-e trace=` 过滤,或 `-c` 只看统计

## 9 · 延伸阅读(可选补充,非必需)

本仓库本地:
- [08-processes-and-signals.md](08-processes-and-signals.md) — 系统调用基础
- [15-c-and-assembly-reading.md](15-c-and-assembly-reading.md) — objdump 看汇编
- [phase-0/README.md](README.md)

外部稳定 URL:
- Brendan Gregg perf 页(圣经):http://www.brendangregg.com/perf.html
- Arch Wiki Debugging:https://wiki.archlinux.org/title/Debugging
- Rust performance book:https://nnmm.se/?id=2020-04-rustperf
- Flamegraph rust crate:https://github.com/flamegraph-rs/flamegraph

真实开源源码:
- strace:https://github.com/strace/strace
- perf(在内核):https://github.com/torvalds/linux/tree/master/tools/perf
- valgrind:https://sourceware.org/git/?p=valgrind.git
- flamegraph(Brendan Gregg Perl 原版):https://github.com/brendangregg/FlameGraph
