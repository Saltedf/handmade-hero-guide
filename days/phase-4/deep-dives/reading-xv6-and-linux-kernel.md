---
title: "读内核:下钻到 xv6 与 Linux 源码"
title_en: "Reading the Kernel: Drilling into xv6 and Linux Source"
subtitle: "fork / scheduler / syscall trap / page fault — 真实内核代码精读"
type: deep-dive
phase: 4
difficulty: 4
duration: "3-4h"
domains: [rust, system, linux, c-reading, game]
prereqs:
  - "phase-0/08-processes-and-signals"
  - "phase-0/15-c-and-assembly-reading"
  - "virtual-memory-and-allocators"
calibration: "读真实内核源码(xv6 + Linux 片段)— MIT 6.S081 '下钻到底' 的精神"
---

# 读内核:下钻到 xv6 与 Linux 源码

> 你在 [phase-0/08-processes-and-signals.md](../../phase-0/08-processes-and-signals.md) 用过 `fork` / `exec` / `wait`,在 [virtual-memory-and-allocators.md](virtual-memory-and-allocators.md) 用过 `mmap` 和 page fault,在 [scheduling-and-thread-affinity.md](scheduling-and-thread-affinity.md) 读过 CFS 的概念。这一整本教程里,内核始终是那只沉默的黑盒——它给你进程、给你内存、给你文件、给你 socket,而你就这么用了。但内核也是人写的代码。它有 `.c` 文件,有 `if` 语句,有注释和 bug。这一篇不教你**写**内核,教你**读**内核——用 MIT 6.S081 的教学 OS xv6 当切入点,把 `fork()` / `scheduler()` / syscall trap / page fault 这几条你最熟的路径,一行一行翻出来。读完之后,你不会再把 `mmap` 当魔法——你会知道它进了哪个函数、改了哪个数据结构、为什么有时候慢。

## 0 · 内核就是代码,而且是你能读懂的代码

把镜头拉到你 Day 200 的 HH 项目。你刚把 entity count 推到 50 万,profile 显示一个奇怪的延迟尖峰,发生在某帧中段。你 strace 你的进程,看到一行 `mmap(NULL, 2097152, PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANONYMOUS, -1, 0) = 0x7f6c5a000000` 紧跟一个 `mprotect(...)`。你大约知道 mmap 是"申请虚拟地址空间",但你不知道:为什么是 2 MB?为什么后面立刻 mprotect?是 glibc 干的还是内核主动干的?这个 syscall 在内核里到底要走多深才返回?

要回答这种问题,文档帮不了你——man page 告诉你**怎么调**,不告诉你**内核里发生了什么**。`man 2 mmap` 写了 flags 的语义,但没写 `do_mmap` 内部如何挂 VMA、如何走 page fault 路径。唯一可靠的答案在源码里。这就是这一篇要做的事:**把内核源码当成最终文档**。

但读 Linux 内核有个根本困难:它太大了。`kernel/` 目录几千个文件,`mm/` 目录几百个,一行 `mmap` 调用牵出 `do_mmap` → `mmap_region` → `call_mmap` → 文件系统的 `ext4_file_mmap` → ... 一路下去你能读半个月还没读完一条 syscall。这不是好的入门姿势。

所以 MIT 6.S081 的 Frans Kaashoek 团队做了一个聪明决定:他们写了一个**真内核**,叫 xv6。xv6 是 Unix 接口的、能跑在 RISC-V 上的、可启动的、完整的多任务内核——但它只有大约一万行 C。整个操作系统你能在一个下午读完。它的 `fork` 是 30 行,不是 300 行;它的 `scheduler()` 是 20 行循环,不是 CFS 那 1500 行红黑树。xv6 没有 Linux 的复杂优化(没有 NUMA、没有 cgroup、没有 io_uring),但它有 Unix 的**全部核心抽象**:进程、页表、文件、pipe、syscall。这些抽象在 xv6 里和 Linux 里是同一件事——只是 Linux 把它做大了,xv6 把它做干净了。

这一篇的策略是:**先读 xv6 的核心路径,直到你看懂了"fork 内部是什么";然后跳到 Linux,看同一件事在 Linux 里多长、多复杂,但概念完全对应**。这就是 MIT 6.S081 课里反复讲的"下钻到底(drill to the metal)"——你不停在抽象层,你下到代码层。

读完之后,你不会再把任何 syscall 当黑盒。`fork` 是 `kernel/proc.c` 里的 `fork()` 函数,page fault 是 `kernel/trap.c` 里的 `usertrap()` 加一条 case,signal 是 `struct proc` 里一个字段。抽象层的东西都是真的——它们在某个 `.c` 文件里以某个函数的形式存在,而你能读懂那个函数。

## 1 · 为什么要读内核:抽象的定义在源码里

我们先问一个朴素问题:为什么要花一个下午读内核?

我在 [virtual-memory-and-allocators.md](virtual-memory-and-allocators.md) 的 §2 讲过 `mmap` 的语义——"在调用进程的虚拟地址空间里创建一段新的映射"。但这是 man page 的描述。**真实的 mmap 做的事比这多得多**:它要查 `/proc/self/maps` 的 VMA 链表确保不重叠、要决定是否预 fault、要给 file-backed 映射注册 page cache 回调、要走 security 模块检查(SELinux/AppArmor)、要在 `mm_struct` 里加一项、要返回用户态之前清掉对应的 TLB 项。man page 不告诉你这些。

当你遇到这些情况,内核源码是你唯一的答案。

第一种情况:**syscall 表现异常**。你在游戏里 `mmap` 一块 4 GB 的关卡文件,期望 lazy load,结果 RSS 一下涨到 4 GB——你以为 lazy 没生效。读源码才知道,你忘了 `MAP_PRIVATE`,默认行为可能因为某些内核版本/配置预读了一大堆页。这是 `mmap_region` 里 `MAP_POPULATE` 标志的事,文档提了一句但没强调。

第二种情况:**信号到达时机诡异**。你 [phase-0/08-processes-and-signals.md](../../phase-0/08-processes-and-signals.md) §3.1 学过 signal handler 只设 atomic flag,但你被一个 race 坑了——SIGINT 在 `epoll_wait` 中段到达,handler 跑了但 epoll 状态没清。读内核源码 `kernel/signal.c` 的 `do_signal` 路径,你会看到信号是在 syscall 返回用户态前检查的,某些可中断 sleep 会立即返回 `EINTR`,这就是 epoll 行为的根源。

第三种情况:**性能瓶颈**。你的 entity pool alloc 看似零成本,但 profile 显示大量 `__do_softirq` 和 `__handle_mm_fault`。读 `mm/memory.c` 的 `handle_mm_fault` 路径,你会发现每次跨 page boundary 触发一次 minor fault,内核要 walk 4 级页表、上锁、分配 page、改 PTE。把 pool 对齐到 page boundary 之后,fault 数归零,延迟尖峰消失。

第四种情况:**纯好奇**。`fork` 之后,父子的内存真的"复制"了吗?如果是 COW,什么时候真的发生复制?复制时谁来改 PTE?这些是 [phase-0/08-processes-and-signals.md](../../phase-0/08-processes-and-signals.md) §2 笼统说过的"复制进程",但只有源码能告诉你**精确**的步骤。

要回答这些,你不需要**会写**内核。你需要能**读懂**内核——知道入口在哪儿,知道顺着调用链往下走,知道哪些代码是热点、哪些是冷门边角。这是系统程序员的"读源码不读文档"——和你在 [phase-0/15-c-and-assembly-reading.md](../../phase-0/15-c-and-assembly-reading.md) 学的"读 Rust 编译器报的汇编"是同一种姿势,只是规模大。

这一篇用 xv6 当练习场,因为 xv6 是**你能完整读懂**的内核。一旦你在 xv6 上练熟了"读 syscall → 找 entry → 跟 call chain → 看数据结构"这套技能,同样的技能在 Linux、在你用的引擎源码(bevy、Unreal)、在你用的库源码(Rust 标准库、tokio)上都通用。读大代码的能力,是 systems programming 最可迁移的元能力之一。

## 2 · xv6:MIT 6.S081 的教学 OS

xv6 是 Frans Kaashoek 和 Robert Morris 在 2006 年为 MIT 6.S081 课程写的 Unix 教学内核。它的目标极其明确:**让学生在一个学期内读完整个操作系统**。它复刻了 1970 年代 Unix Sixth Edition 的接口和大部分设计,但用 ANSI C 写,跑在 RISC-V(早期版本跑 x86)上,代码风格现代。整个系统大约一万行 C,加上少量的 RISC-V 汇编启动代码。

xv6 不是"玩具"——它是**真内核**。它能 boot、能加载用户程序、能跑 shell、能多任务、有虚拟内存、有文件系统、有 pipe、能 fork/exec。MIT 6.S081 学生在这上面做的作业是真系统编程:加一个新 syscall、实现 copy-on-write fork、实现 mmap、写一个简单的调度器。xv6 的代码就是工业 Unix 的"压缩版",删掉了所有优化、所有边角情况、所有性能 hack,留下核心抽象的**最清晰**实现。

为什么用 xv6 而不是 Linux 来学读内核?核心原因是**可读性**。Linux 的 `fork` 涉及十几个文件、上千行代码、几百个边界条件;xv6 的 `fork` 在 `kernel/proc.c` 里是一个 30 行的函数,你能一目了然。Linux 的 CFS 调度器用红黑树维护虚拟运行时间、有 cgroup 调度、有 NUMA balancing、有 sched_domain 层次;xv6 的 `scheduler()` 是一个 20 行的 round-robin 循环。Linux 的 page fault handler 走 `do_page_fault` → `handle_mm_fault` → `handle_pte_fault` → 区分 anonymous / file / swap / huge / ... 几十条分支;xv6 在 `usertrap()` 里就一两行 case。在 xv6 上你看清的是**概念**,而 Linux 让你看不清的恰恰是**优化和细节**——先用 xv6 把概念钉死,再去 Linux 里认这些概念。

接下来几节我会贴 xv6 的真实 C 源码(都是 `kernel/` 目录下的文件),一段一段讲。你不必现在打开 xv6,但**强烈建议**这一节看完后做 §7 那个"在你 HH 项目里动手"——真的 clone xv6,真的 `grep fork kernel/proc.c`,亲自读一遍。这是这一篇的核心红线。

### 2.1 xv6 的代码地图

xv6 的源码目录结构:

```
kernel/
├── proc.c        // 进程:fork, exec, scheduler, sleep, wakeup
├── vm.c          // 虚拟内存:页表, mmap-like 的 uvm* 函数
├── trap.c        // 陷入:usertrap (用户态陷入), kerneltrap
├── syscall.c     // 系统调用分发:fork, read, write, ...
├── sysfile.c     // 文件相关 syscall:open, read, write, pipe
├── file.c        // 文件描述符层
├── fs.c          // 文件系统
├── buf.c         // buffer cache
├── spinlock.c    // 自旋锁
├── main.c        // 启动入口,启动后跳到 scheduler
├── riscv.h       // RISC-V 相关的位定义(PTE flags, SATP 等)
└── memlayout.h   // 地址空间布局
user/
├── sh.c          // xv6 自带的 shell,~400 行,可读
├── cat.c
├── echo.c        // ...
makecs // 编译脚本
```

整个内核你大概一个下午能过一遍核心文件:`main.c`(10 行,启动)→ `proc.c`(最长,大概 800 行)→ `vm.c`(500 行)→ `trap.c`(200 行)→ `syscall.c`(300 行)。xv6 的注释写得极其清楚——Frans 团队就是把它当教科书写的,每个函数开头都有几行说"这个函数干什么、什么时候被调用"。读 xv6 注释是金矿。

下面开始读真正的源码。我贴的 C 代码都从 xv6-riscv 仓库当前主线直接抄录,删了几行无关的注释或防御性 assert 让讲解更顺,但**逻辑**和**结构**完全保留。每个文件你都能在 https://github.com/mit-pdos/xv6-riscv 找到。

## 3 · fork:30 行看清"复制一个进程"

你在 [phase-0/08-processes-and-signals.md](../../phase-0/08-processes-and-signals.md) §2 用过 `fork`,知道它"复制当前进程,返回值在父子里不同"。现在我们看内核里这到底怎么发生的。

xv6 的 `fork` syscall 在 `kernel/proc.c` 里。入口是 `sys_fork`(在 `syscall.c` 里的一行派发),实际工作在 `fork()` 函数。我把这个函数的核心路径贴出来:

```c
// Create a new process, copying the parent.
// Sets up child kernel stack to return as if from fork() system call.
int
fork(void)
{
  struct proc *np;     // 子进程的 proc struct
  struct proc *p = myproc();

  // Allocate process.
  if((np = allocproc()) == 0){
    return -1;
  }

  // Copy user memory from parent to child.
  if(uvmcopy(p->pagetable, np->pagetable, p->sz) < 0){
    freeproc(np);
    release(&np->lock);
    return -1;
  }
  np->sz = p->sz;

  // copy saved user registers.
  *(np->trapframe) = *(p->trapframe);

  // Cause fork to return 0 in the child.
  np->trapframe->a0 = 0;

  // increment reference counts on open file descriptors.
  for(i = 0; i < NOFILE; i++)
    if(p->ofile[i])
      np->ofile[i] = filedup(p->ofile[i]);
  np->cwd = idup(p->cwd);

  safestrcpy(np->name, p->name, sizeof(p->name));

  np->parent = p;

  // ... (设置子进程状态为 RUNNABLE)
  return np->pid;
}
```

这就是一个完整的 fork。我们逐段讲。

第一段:`allocproc()`。这是 xv6 的"分配新进程"原语。它在进程表里找一个空槽,初始化一个 `struct proc`,给它分配一个 kernel stack,把状态设为 USED。注意它**没有**分配任何用户内存——此时 `np->pagetable` 还是一个空模板(只有内核映射),`np->sz`(用户内存大小)是 0。`allocproc` 做的事是"造一个空壳子"。

第二段:`uvmcopy(p->pagetable, np->pagetable, p->sz)`。这是 fork 真正"复制内存"的地方。`uvmcopy` 在 `vm.c` 里,它的实现是**遍历父进程页表的所有用户页,每页分配一个新物理页,memcpy 过去**。注意这是**真复制**,不是 COW。xv6 默认不做 copy-on-write(COW 是 6.S081 的一个作业,留给学生实现)。Linux 的 `fork` 用 COW——只在写的时候才真的复制——但概念上和 xv6 这里完全一样,只是延迟了复制时机。

第三段:`*(np->trapframe) = *(p->trapframe)`。这是复制 trapframe——父进程此刻的寄存器快照。xv6 用 RISC-V,trapframe 是 32 个通用寄存器加上 PC、SP 等。父进程在调 fork 时,它的寄存器是"刚进 syscall handler 时的状态"。这一行把整个 trapframe 结构体按字节复制给子进程,所以子进程的寄存器和父进程**一模一样**——这是 fork 之后子进程"好像从 fork 调用里返回"的基础。

第四段:`np->trapframe->a0 = 0`。这是 fork 的"魔法"。RISC-V 的调用约定里,返回值放 `a0` 寄存器。父进程的 syscall 返回路径会把 trapframe 的 `a0` 当作返回值返给用户态。所以**子进程的 `a0` 设成 0**,等子进程被调度运行、`sret` 回用户态时,用户态看到的 fork 返回值就是 0。父进程那边走的是正常返回路径,`a0` 是 `np->pid`。这就是同一个 fork 调用在父子里返回值不同的实现机制——不是什么魔法,就是给两个进程的 `a0` 寄存器写不同的值。

第五段:复制文件描述符表。`for(i = 0; i < NOFILE; i++) if(p->ofile[i]) np->ofile[i] = filedup(p->ofile[i]);`。父进程打开的每个文件,子进程也"打开"——但实际是引用计数 +1,共享同一个 underlying file struct。所以父子进程的 fd 1(stdout)指向同一个 file struct,共享文件 offset——这是 shell 实现 `>` 重定向时 "fork 之后 exec 之前关 fd 1 重开" 的底层。

第六段:`np->parent = p`。子进程的 parent 指针指向父进程。这就是 [phase-0/08-processes-and-signals.md](../../phase-0/08-processes-and-signals.md) §1 那个 PPID 的来源——父进程的 PID。后面 `wait()` 用这个反向找父进程。

最后返回 `np->pid`——父进程拿到的 fork 返回值是子进程的 PID。

整段代码 30 行,但讲清了 Unix fork 的全部核心:**进程结构复制、内存复制(或 COW)、寄存器快照复制、文件描述符共享、parent 关系建立、返回值区分**。任何 Unix-like 内核的 fork 都是这六件事。Linux 的 `do_fork` → `copy_process` 做的也是这六件事,只是每件事的细节多 10 倍(COW 的 page fault handler、信号 pending 的复制、cgroup 迁移、namespace 复制、audit context 复制、io_uring ctx 共享、...)。

读完 xv6 的 fork,你以后调 `Command::spawn()` 时心里就有图了——你知道 Rust 标准库在底层调 `clone`(Linux 上 fork 的现代变体),clone 进内核走 `do_fork`,干的就是这六件事。`spawn()` 不是魔法,是六件事的封装。

### 3.1 对比 Linux:do_fork 和 copy_process

xv6 的 fork 是 30 行,Linux 的 fork 路径在 `kernel/fork.c` 里,主入口 `do_fork`(现代内核叫 `kernel_clone`),核心工作在 `copy_process`,这个函数有**约 700 行**。我列一下它做的事,你感受一下"xv6 删掉了什么":

`copy_process` 干的事:dup `mm_struct`(如果是 CLONE_VM 则共享,不复制)、复制页表(`copy_page_range`,这就是 xv6 的 `uvmcopy` 在 Linux 里的版本,但走 COW)、复制 files struct(`dup_fd`,xv6 的 `filedup` 循环)、复制 signal handler(`copy_sighand`, `copy_signal`)、复制 namespace(`copy_namespaces`,容器依赖这个)、复制 cgroup 关系、复制 audit context、复制 cred(credentials)、给子进程分配新 PID、把子进程链入 task_struct 全局链表、调用 scheduler 的 `sched_fork` 初始化调度信息。每一项在 xv6 里要么没有(cgroup / namespace / audit),要么是 3-5 行(files、parent)。

**这就是 xv6 的价值**:它保留了 fork 这件事的**骨架**,让你看清概念。Linux 让你看不清的是**优化**(COW)和**企业特性**(cgroup、namespace)。你在 Linux 上看 fork 之前,先用 xv6 把骨架钉死,就不会迷失。

## 4 · scheduler:20 行循环,内核的心跳

`fork` 创建了进程,但谁来决定哪个进程跑?调度器。xv6 的调度器在 `kernel/proc.c` 里,叫 `scheduler()`,我们贴出来:

```c
// Per-CPU process scheduler.
// Each CPU calls scheduler() after setting itself up.
// Scheduler never returns.  It loops, doing:
//  - choose a process to run.
//  - swtch to save and restore context.
//  - never return.
void
scheduler(void)
{
  struct proc *p;
  struct cpu *c = mycpu();

  c->proc = 0;
  for(;;){
    // Avoid deadlock by ensuring that devices can interrupt.
    intr_on();

    for(p = proc; p < &proc[NPROC]; p++) {
      acquire(&p->lock);
      if(p->state == RUNNABLE) {
        // Switch to chosen process.  It is the process's job
        // to release its lock and then wake up again.
        p->state = RUNNING;
        c->proc = p;
        swtch(&c->context, &p->context);

        // Process is done running for now.
        // It should have changed its p->state before coming back.
        c->proc = 0;
      }
      release(&p->lock);
    }
  }
}
```

这就是 xv6 的全部调度逻辑:**每个 CPU 一个 `scheduler()` 函数,永不返回,for 循环扫进程表,找到 RUNNABLE 的就跑**。

我们讲。

最外层 `for(;;)` 是死循环——调度器永不退出。开机后,每个 CPU(core)在 `main.c` 里被启动,最后一个动作就是跳到 `scheduler()`。从那以后这个 CPU 永远在调度循环里。

循环第一件事:`intr_on()`——开中断。这一行看着普通,但它解决一个微妙的死锁问题。下一行 `acquire(&p->lock)` 拿进程锁,如果此时中断关闭,而某个设备的中断 handler 也想拿这把锁,就死锁了。所以调度器在拿锁之前先确保中断开着——这是 [phase-0/25-concurrency-foundation.md](../../phase-0/25-concurrency-foundation.md) §3 讲的"中断关闭时不能拿会被中断 handler 用的锁"的实战。

内层循环:从 `proc[0]` 扫到 `proc[NPROC]`,这是进程表——xv6 用一个固定大小数组(典型 64 个槽)存所有进程。Linux 用链表 + RCU,xv6 用静态数组,这是教学内核的简化。

每次扫到一个进程,先 `acquire(&p->lock)`。这把锁保护 `p->state` 字段——你不能在另一个 CPU 同时改它。然后 `if(p->state == RUNNABLE)`——只挑就绪的进程。RUNNABLE 表示"想跑但没在跑",对应 [phase-0/08-processes-and-signals.md](../../phase-0/08-processes-and-signals.md) §2 里的 `R` 状态。

找到就 `p->state = RUNNING; c->proc = p;`——状态改成 RUNNING,记下当前 CPU 在跑谁。然后**核心那一行**:`swtch(&c->context, &p->context)`。

`swtch` 是 RISC-V 汇编写的(在 `kernel/swtch.S`),它做的事是**寄存器上下文切换**:保存当前 CPU 的 callee-saved 寄存器到 `c->context`,从 `p->context` 恢复 callee-saved 寄存器。然后 `ret`——这一跳就跳到了进程 `p` 上次被换出时执行到的位置。

这就是"上下文切换(context switch)"的全部:存一组寄存器,加载另一组寄存器,跳过去。**没有魔法,就是寄存器搬动**。xv6 的 swtch 大概 20 行汇编,Linux 的 `__switch_to` 在 x86 上也是类似规模,只是多了 FPU / vector / TLS 状态切换。

`swtch` 返回时,执行流已经回到了 `p` 上次停下的地方——通常是 `p` 之前调用 `swtch` 切换出去的位置(`yield` / `sleep` / `sched`)。从 `p` 的视角看,它从来没"睡过",只是它的 `swtch` 调用终于返回了。这就是协作式时间片切换的实现本质:**每个进程都以为自己在连续运行,实际是被无数次 swtch 切来切去**。

`swtch` 返回到调度器时,意味着刚才那个进程主动让出了 CPU(调了 `yield` 或 `sleep` 或时间片到了被中断 handler 调 `yield`)。`c->proc = 0` 清标记,`release(&p->lock)`,继续扫下一个进程。

整段 20 行,但讲清了 Unix 调度的全部核心:**进程表扫描、状态机、锁保护、寄存器上下文切换、进程从 swtch 返回的视角**。所有 Unix-like 内核的调度器都是这个骨架。

### 4.1 对比 Linux:CFS 不是另一个东西,是同一个东西的优化版

xv6 是 round-robin——轮询,谁 RUNNABLE 就跑谁,不区分优先级、不区分"已经跑了多久"。简单粗暴。

Linux 的 CFS(Completely Fair Scheduler)你已经在 [scheduling-and-thread-affinity.md](scheduling-and-thread-affinity.md) 见过。它做的事**概念上和 xv6 一样**——选下一个 RUNNABLE 进程,swtch 过去——但它用红黑树按"虚拟运行时间(vruntime)"排序,选 vruntime 最小的进程,这样每个进程"公平"地拿到 CPU 时间。xv6 是"绝对公平的轮流",CFS 是"按权重比例公平的轮流",但**选进程 → swtch** 的骨架完全一致。

Linux 的调度器主入口在 `kernel/sched/core.c`,函数 `__schedule`(以及 `pick_next_task`),它做的事:扫每个 scheduling class(`stop_sched_class` → `dl_sched_class` → `rt_sched_class` → `fair_sched_class` → `idle_sched_class`),每个 class 用自己的策略挑进程。`fair_sched_class` 就是 CFS,内部调 `pick_next_entity` 走红黑树。

读 Linux 调度器时,如果你先在 xv6 上把 `scheduler()` 那个 20 行骨架钉死,你就不会被 Linux 那 1500 行吓到——你心里清楚骨架就是"扫 RUNNABLE,选一个,swtch 过去",Linux 加的全部是"怎么挑得更聪明"。vruntime、cgroup 调度、sched_domain(NUMA)、sched_rt(SCHED_FIFO / SCHED_RR)、sched_dl(deadline scheduling)全是"挑得更聪明"的工具。

## 5 · syscall 怎么进内核:从 user 到 kernel 的那条 trap

`fork` 是 syscall 之一。现在我们看更通用的事:**一个 syscall 怎么从用户态进入内核**。这是 [phase-0/15-c-and-assembly-reading.md](../../phase-0/15-c-and-assembly-reading.md) §3 讲的 "user space 和 kernel space 的边界" 的实现层。

在 RISC-V 上,用户程序调 `ecall` 指令触发一个 environment call 陷入。xv6 的 `uservec`(在 `kernel/trampoline.S`)接过控制,保存用户态寄存器到 trapframe,切换到内核页表,跳到 `usertrap`(在 `kernel/trap.c`)。`usertrap` 根据 trap 的原因(system call / timer interrupt / device interrupt / fault)派发。

我们看 `usertrap` 里 syscall 那一支(简化版,删了 device/timer 分支):

```c
void
usertrap(void)
{
  int which_dev = 0;

  // ... (修改 SSTATUS 等,确保再次陷入时进入 kernel mode)

  if(r_scause() == 8){
    // system call
    if(killed(p))
      exit(-1);

    // sepc points to the ecall instruction,
    // but we want to return to the next instruction.
    p->trapframe->epc += 4;

    // an interrupt will change sepc, sstatus, and scause,
    // so we need to save them here.
    intr_on();

    syscall();
  } else {
    // ... 其他 trap 原因:page fault, illegal instruction, ...
  }

  // ... 准备返回用户态:usertrapret()
}
```

我们讲。

`r_scause() == 8`——RISC-V 的 scause 寄存器读出来是 8,意思是"environment call from U-mode",也就是用户态的 ecall 指令触发的陷入。这就是 syscall 的硬件信号。

`p->trapframe->epc += 4`——这一行是关键。`epc` 是触发 trap 的指令地址,也就是那条 `ecall` 的地址。返回用户态时 PC 要从哪里开始?xv6 的选择是"ecall 的下一条指令"——也就是 syscall 调用点之后的代码。`ecall` 是 4 字节指令(RISC-V 所有指令 4 字节),所以 `epc += 4` 跳过它。这就是"syscall 返回到调用点的下一条"的实现——硬件只记 ecall 的地址,跳过它由软件做。

`intr_on()`——开中断。xv6 在 syscall 执行期间允许中断(timer 中断可以打断 syscall,这是为了时间片调度——如果一个 syscall 跑太久,定时器中断进来,handler 调 `yield`,CPU 切到别的进程)。Linux 不允许所有 syscall 被中断,有些 critical section 关中断,但概念上一样:syscall 期间也可能被换出 CPU。

`syscall()`——这一行是真正的派发。它在 `kernel/syscall.c` 里:

```c
void
syscall(void)
{
  int num;
  struct proc *p = myproc();

  num = p->trapframe->a7;     // syscall number in a7
  if(num > 0 && num < NELEM(syscalls) && syscalls[num]) {
    p->trapframe->a0 = syscalls[num]();   // 返回值放 a0
  } else {
    num = p->trapframe->a7;
    p->trapframe->a0 = -1;    // unknown syscall
  }
}
```

`p->trapframe->a7`——syscall number。RISC-V 的 syscall 调用约定是:a7 放 syscall 编号,a0-a6 放参数,返回值放 a0。xv6 的用户库 `usys.pl` 自动生成的汇编桩,比如 `fork()` 的桩就是 `li a7, SYS_fork; ecall; ret`,把 SYS_fork 编号放 a7,然后 ecall 陷入。

`syscalls[num]()`——`syscalls` 是一个函数指针数组,索引是 syscall 编号,值是对应的内核实现函数。比如 `syscalls[SYS_fork] = sys_fork`。这就是 syscall 的派发表。Linux 的派发表叫 `sys_call_table`,概念一模一样,只是条目多(Linux 有几百个 syscall,xv6 大约 20 个)。

`p->trapframe->a0 = syscalls[num]()`——调用真正的实现(`sys_fork` / `sys_read` / ...),返回值写进 trapframe 的 a0。返回用户态时用户程序看到的 `fork()` 返回值,就是这个 a0。

整条 syscall 路径就是:**用户 ecall → uservec 保存现场 → usertrap 判断是 syscall → syscall() 查表调 sys_xxx → 返回值写 a0 → usertrapret 恢复现场 sret 回用户态**。

这一切在你写的 `Command::new(...).spawn()` 那一行 Rust 背后默默发生。Rust 标准库调 libc 的 `fork()` → libc 的 `fork` 是个薄桩,设 a7 = SYS_clone,ecall → 进内核走上面那条路径 → 返回 PID。你看不到任何一行汇编,但底下就是这么一层一层的"陷阱+派发+返回"。

### 5.1 对比 Linux:同一条路径,只是更深

xv6 的 syscall 入口是 `uservec` → `usertrap` → `syscall()`,全部在 `kernel/` 目录里,几百行搞定。

Linux 的 syscall 入口在 x86_64 上叫 `entry_SYSCALL_64`(在 `arch/x86/entry/entry_64.S`),它做的事:uservec 等价——保存用户态寄存器、切内核栈、切页表(MIT 6.S081 的 xv6 是 RISC-V,所以页表切换细节略有不同,但都是"从用户 CR3 切到内核 CR3"或等价动作)。然后跳到 `do_syscall_64`(在 `arch/x86/entry/common.c`),它做安全检查(seccomp、ptrace)、查 `sys_call_table`、调真正的 `__x64_sys_xxx` 实现。Linux 加的复杂度全是**安全检查**(seccomp 沙箱、capability、audit log、strace 的 ptrace hook),骨架和 xv6 完全一致。

读 Linux syscall 路径时,记住 xv6 那条 `usertrap → syscall() → syscalls[num]()` 骨架,你会认出 Linux 的 `entry_SYSCALL_64 → do_syscall_64 → sys_call_table[nr]()` 是同一件事。

## 6 · page fault:虚拟内存的"出错"是它的核心机制

最后一条路径——page fault。你在 [virtual-memory-and-allocators.md](virtual-memory-and-allocators.md) §1 学过 page fault:CPU 访问的虚拟地址在页表里没映射(或权限不对),触发陷入,内核的 page fault handler 处理。

xv6 的 page fault 处理在 `usertrap` 里——同一个函数,只是 scause 不是 8(syscall),而是 13/15(load page fault)或 12/14/15(store page fault / instruction page fault)。xv6 默认的 page fault 行为是简单粗暴的:**杀掉进程**。`usertrap` 里 page fault 那一支就是:

```c
} else if((which_dev = devintr()) != 0){
  // ok
} else {
  printf("usertrap(): unexpected scause %p pid=%d\n", r_scause(), p->pid);
  printf("            sepc=%p stval=%p\n", r_sepc(), r_stval());
  p->killed = 1;
}
```

任何不是 syscall、不是设备中断、不是 timer 中断的 trap,xv6 直接 `p->killed = 1`,然后进程会被杀。这就是 [phase-0/08-processes-and-signals.md](../../phase-0/08-processes-and-signals.md) §3 里的 SIGSEGV 的等价物——你访问非法地址,xv6 直接终结进程。

xv6 这么做是因为它没实现 lazy allocation、没实现 COW、没实现 demand paging——这些都是 6.S081 的作业。但 **Linux 都实现了**。这就是为什么这一节主要讲 Linux 而不是 xv6——page fault 这个特性,xv6 把它"删了"留给学生,所以 xv6 源码你看不到完整的 page fault 处理。Linux 是看 page fault 的正确地点。

Linux 的 page fault 主入口在 `arch/x86/mm/fault.c`(其他架构在 `arch/<arch>/mm/fault.c`),叫 `do_page_fault`(在 x86_64 上有时是 `__do_page_fault` 或 `exc_page_fault`,版本不同名字略变)。它做的事是:

第一步:读 fault 地址(CR2 寄存器)和错误码。错误码告诉你是 read fault 还是 write fault、是 user 触发还是 kernel 触发、是 protection 违反还是 page 不存在。

第二步:`find_vma(mm, address)`——在进程的 VMA 链表里找包含这个地址的 VMA。如果没找到(地址在任何 VMA 之外),说明进程访问了未分配的地址,这是 SIGSEGV 的标准原因。

第三步:走 `handle_mm_fault`(`mm/memory.c`),这是 Linux page fault handler 的核心。它做的事:

- 如果 VMA 是匿名页(`!vma->vm_ops` 或没有 `fault` 回调)且页表项不存在,**分配一个新零页**(zeroed page),填进页表。这就是 lazy allocation——`mmap` 时只挂 VMA,真正访问时才分配物理页。你在 [virtual-memory-and-allocators.md](virtual-memory-and-allocators.md) §1 那段"你 touch 它的瞬间内核才分物理页"的实现就在这里。

- 如果 VMA 是文件映射(`vma->vm_ops->fault` 存在),调 `fault` 回调——通常是 `filemap_fault`,它从 page cache 找页,没有就发 IO 从磁盘读。这就是 mmap 一个文件之后"按需从磁盘读页"的机制。

- 如果页表项存在但权限不对(比如 COW:父子的页都映射到同一物理页,标 read-only,一方写时触发 write fault),Linux 走 `do_wp_page`——分配一个新物理页,memcpy 旧的过去,改 PTE 指向新页,改权限为 writable。这就是 COW fork 的"在写的时候才真复制"的实现。

第四步:返回用户态,这次同样的访问指令重试,这次成功了。

整条路径大约 `do_page_fault`(架构相关,~200 行)→ `handle_mm_fault`(架构无关,~300 行)→ `handle_pte_fault`(分支,~100 行)→ 具体 `do_anonymous_page` / `do_wp_page` / `do_read_fault` / `do_numa_page`。每一支处理一类 page fault。总代码量几千行,但**概念**只有四类:lazy alloc、file demand-paging、COW、NUMA migration。

读这一段时,你的核心收益是:**page fault 不是 bug,是机制**。它是虚拟内存"按需分配"的实现入口。你 mmap 1 GB,内核一个 RAM 都没给你,你访问第一页的时候,page fault 才让内核真的给你 RAM。这是 mmap 的精髓,你只有读源码才能**亲眼**看到——man page 只告诉你"按需分配",不告诉你这在 `handle_mm_fault` 的哪个分支。

### 6.1 用 /proc 看 page fault 发生

光读不够,看现场。Linux 把每进程的 page fault 计数暴露在 `/proc/PID/stat` 里。第 10 个字段是 minor fault 次数(没 IO 的 page fault,比如 lazy alloc / COW),第 12 个字段是 major fault 次数(需要磁盘 IO 的 page fault,比如 file demand-paging)。

```bash
# 跑你的 HH 项目,在另一个终端
PID=$(pidof your_game)

# minor / major fault 次数
cat /proc/$PID/stat | awk '{print "minor:", $10, "major:", $12}'
```

minor fault 高,说明你的程序在大量触发 lazy allocation / COW——可能是 entity pool 跨 page boundary 频繁,或者大量 `fork`(每个 fork 都复制页表项,触发 minor)。major fault 高,说明你的 mmap 文件正在从磁盘按需读——这是 [virtual-memory-and-allocators.md](virtual-memory-and-allocators.md) §7 那个"关卡文件 lazy load"在做的事,在玩家走到新区块时你能看到 major fault 计数跳。

## 7 · 读大代码的元技能:不读懂每一行也能理解

这一篇开头说,读大代码是 systems programming 最可迁移的元能力之一。我用了一整篇讲怎么读 xv6 的几个核心函数,但 xv6 一万行,真正的大代码——Linux、Unreal、Rust 编译器——是几百万行。你不能用读 xv6 的方式一行一行读 Linux,你会读 5 年。

读大代码的正确姿势,核心是**别读懂每一行**。这不是懒,这是策略。具体来说有几条原则。

**第一条:从一个 syscall 或一个 entry point 进去,跟一条 call chain,不要试图理解整个文件**。你不知道 Linux 内核某个文件整体在干什么没关系,你知道"fork 这条路径走 `do_fork → copy_process → copy_mm → dup_mmap → ...`",顺着这条链读就行。读完这一条,你对 fork 的理解比 99% 的程序员深。其他路径(read、mmap、signal、page fault)等需要时再读——读大代码是**问题驱动**的,不是**系统通读**的。xv6 你可以系统通读,因为它小;Linux 你只能问题驱动。

**第二条:注释和文档比代码本身重要**。Linux 内核的注释是金矿——很多函数开头一大段注释解释"这个函数干什么、为什么这么实现、有哪些 corner case"。读代码前先读注释,注释告诉你作者意图,代码告诉你实现。xv6 的注释尤其清楚,因为 Frans 团队就是把它当教科书写的。Linux 的注释良莠不齐,但核心函数(`__schedule`、`do_page_fault`、`copy_process`)的注释都很到位。

**第三条:用 grep / cscope / ripgrep 找符号,不要肉眼翻**。你看到一个函数被调用但不知道在哪定义,`grep -rn "函数名" kernel/` 一秒找到。Linux 源码太大,你不能靠"打开文件翻"找到任何东西。xv6 你可以,因为整个内核就几十个文件。

```bash
# 在 xv6 仓库里
grep -n "allocproc" kernel/proc.c          # 找定义
grep -rn "allocproc" kernel/                # 找所有调用点

# 在 Linux 源码里(先装 cscope)
cd linux-source
cscope -R                                   # 交互式查符号定义/调用
rg "copy_process" kernel/                   # ripgrep, 比 grep 快
```

`cscope` 比 grep 强的地方在于它知道 C 语义——它能区分"这个符号是函数定义"、"这个符号是函数调用"、"这个符号是字符串里的文本"。Linux 源码不装 cscope 你会读得很痛苦。

**第四条:先读数据结构,再读函数**。Linux 内核的设计哲学是"数据结构决定一切"——你不懂 `task_struct` 长什么样,就读不懂任何进程相关函数;不懂 `mm_struct` 和 `vm_area_struct` 的关系,就读不懂任何 mm 函数;不懂 `struct file` 和 `struct inode`,就读不懂 fs。读一个子系统前,先打开它的核心 struct 定义,看每个字段是干什么的——注释会说。然后看函数时,你脑子里有这个 struct 的图,函数就是在改这些 struct 的字段。

xv6 也是一样。读 `proc.c` 之前,先读 `struct proc` 的定义(在 `kernel/proc.h`):

```c
// Per-process state
struct proc {
  struct spinlock lock;

  // p->lock must be held when using these:
  enum procstate state;        // Process state
  void *chan;                  // If non-zero, sleeping on chan
  int killed;                  // If non-zero, have been killed
  int xstate;                  // Exit status to be returned to parent's wait
  int pid;                     // Process ID

  // wait_lock must be held when using this:
  // proc_lock must be held when using this:
  struct proc *parent;         // Parent process

  // these are private to the process, so p->lock need not be held.
  uint64 kstack;               // Virtual address of kernel stack
  uint64 sz;                   // Size of process memory (bytes)
  pagetable_t pagetable;       // User page table
  struct trapframe *trapframe; // data page for trampoline.S
  struct context context;      // swtch() here to run process
  struct file *ofile[NOFILE];  // Open files
  struct inode *cwd;           // Current directory
  char name[16];               // Process name (debugging)
};
```

你看完这个 struct,你心里就有了进程的"骨架":状态、PID、parent、内核栈、用户页表、用户内存大小、trapframe(寄存器快照)、context(swtch 上下文)、文件描述符表、cwd。后面读 `fork`、`scheduler`、`exec`、`wait` 时,这些函数全是在改这个 struct 的字段——分配 proc 改 state,复制页表改 pagetable 和 sz,复制 fd 改 ofile 数组,等等。**数据结构是地图,函数是行动**。这条原则在 Linux、Unreal、bevy 任何大代码上都通用。

**第五条:读测试和注释里的"不变量"**。xv6 的 `proc.c` 开头有大段注释说"this file has the routines for process management; the proc table is `proc[]`, NPROC entries; ...",这种总览注释极其有用。Linux 的子系统开头也有类似的 `Documentation/<subsystem>/` 目录。Rust 标准库每个模块的 `mod.rs` 注释也讲不变量。这些是作者给你的"导览地图",别跳过。

**第六条:别追求读懂每一行边角代码**。Linux 里大量代码是处理罕见 corner case、特定架构 quirks、性能优化。这些你第一次读完全可以跳过——`#ifdef CONFIG_NUMA` 那一大段、`if (unlikely(...))` 的罕见分支、各种 `goto out_unlock` 的清理路径,这些是给资深维护者看的。你第一次读时,抓主干:`fork` 怎么复制 mm、怎么复制 files、怎么挂进程链表,主干读懂就是 80% 的理解。边角以后慢慢补。

把这六条用上,你在 Linux 这种千万行代码里就能"读得动"——你不会读完整个内核,但你能读懂你需要的那条路径。这就是 systems programmer 的"读源码"能力。

## 8 · 这一切怎么改变你的游戏编程

你可能会问:我一个写游戏的,为什么要花一个下午读 xv6 和 Linux?

我给你三个具体的改变。

**第一,你不会再误用 syscall**。读完这一篇,你知道 `fork` 复制页表(即使 COW 也要复制 PTE,大进程 fork 慢)、`mmap` 在你访问时才真分 RAM(lazy 是默认)、`epoll_wait` 在 syscall 返回前可能被信号打断返回 `EINTR`(你的代码要处理这个 errno)。这些细节在 man page 里都有,但只有读源码你才会**记住**——因为你看过 `do_page_fault` 怎么走、看过 `usertrap` 怎么检查 signal。下次你 `mmap` 一块大内存然后奇怪 RSS 没涨,你立刻知道是 lazy allocation,不是 bug。下次你 fork 一个 8 GB 的进程然后发现 fork 慢得离谱,你知道是 COW 复制页表,得想别的姿势(`vfork` / `posix_spawn` / `clone` + `CLONE_VM`)。

**第二,你能 debug syscall 级的问题**。游戏上线后某个玩家报"游戏偶发卡 200ms",profile 没发现热点,火焰图看是 `__do_page_fault` 占了一大块。你不会一脸懵——你知道这是 major page fault,要么是 mmap 文件在按需读盘,要么是 swap 在读回页。你 `cat /proc/PID/stat` 看 major fault 次数,看是不是高峰;你 `vmstat 1` 看是不是 swap 在抖动。这些都是你读了 `handle_mm_fault` 之后才会**自然想到**的诊断方向。

**第三,你写引擎时的设计更扎实**。你在 [async-io-and-streaming.md](async-io-and-streaming.md) 学 io_uring,在 [scheduling-and-thread-affinity.md](scheduling-and-thread-affinity.md) 学线程亲和性,这些设计选择都依赖你对内核的理解。读完这一篇,你知道 io_uring 的"submission queue"在内核里其实是和 user 共享的内存页,你知道线程亲和性的 `sched_setaffinity` 最终改的是 `task_struct->cpus_allowed`,你知道 CFS 的 vruntime 在 `task_struct->se.vruntime`。这些知识让你的设计有**根据**,不是抄博客。

更哲学地说:**把内核当黑盒的程序员和把内核当透明盒的程序员,写出代码的质量差一个数量级**。前者写出的代码经常"莫名其妙慢"或"莫名其妙崩",后者写出的代码每一个 syscall 都用得对、用得少、用得恰到好处。Casey 在 HH 里反复强调"理解每一层",他连 Windows 的 PE 加载器细节都讲给你听——同样的精神,在 Linux 上对应的就是读内核。

## 9 · 在你 HH 项目里动手(做中学红线)

这一节是这一篇的核心红线。**强烈建议完整做完**——光读文字理解不深,亲自把 xv6 clone 下来、grep 几个函数、写一段笔记,你才真正"下钻到底"。

**步骤 1**:clone xv6-riscv。在你的 HH 项目之外建一个 `study/` 目录:

```bash
mkdir -p ~/study && cd ~/study
git clone https://github.com/mit-pdos/xv6-riscv
cd xv6-riscv

# 看 kernel 目录,先扫一眼
ls kernel/
wc -l kernel/proc.c kernel/vm.c kernel/trap.c kernel/syscall.c
```

你应该看到 proc.c 大约 800 行,vm.c 大约 500 行,trap.c 大约 200 行,syscall.c 大约 300 行。这就是整个 xv6 的核心。

**步骤 2**:装一个能 grep 的工具,熟悉 cscope。Arch 上:

```bash
sudo pacman -S cscope ripgrep
```

在 xv6 目录里建 cscope 索引:

```bash
cd ~/study/xv6-riscv
cscope -R
# 在 cscope 界面里查 Find functions calling this function: allocproc
# 看谁调了 allocproc —— fork、exec、userinit 都调
```

**步骤 3**:按下面四个目标,每个写一段(150-300 字)用自己的话解释这段代码做什么。这是把读到的内化为"我能复述"的关键。

目标 1:读 `kernel/proc.c` 的 `fork()`(就是这一篇 §3 贴的那段),用你的话写:"fork 在内核里具体做了哪几步?为什么要复制 trapframe?为什么把子进程 trapframe 的 a0 设 0?"

目标 2:读 `kernel/proc.c` 的 `scheduler()`,用你的话写:"scheduler 怎么挑下一个进程?swtch 之后控制流到哪儿去了?从被换出进程的视角看,它的 swtch 调用什么时候返回?"

目标 3:读 `kernel/vm.c` 的 `uvmcopy`(fork 调的那个)。它的循环是什么?它在做什么?xv6 的 fork 是 eager copy 还是 COW?(用 200 字解释。提示:它 `kalloc` + `memmove` 每页,所以是 eager。)

目标 4:读 `kernel/syscall.c` 的 `syscall()` 函数 + `syscall.h` 的 syscall 编号定义。回答:"xv6 一共多少个 syscall?fork 的编号是多少?`syscalls[SYS_fork]` 指向哪个函数?追踪 `sys_fork` 到 `fork()`,中间有几层?"(答案:sys_fork 在 `sysproc.c`,它薄薄一层调 `fork()`,两层。)

**步骤 4**:从下面挑**一个** Linux 内核函数,locate 它,读它。这步把你 xv6 上练的"读内核"技能迁移到 Linux。

候选 A:`__schedule`(在 `kernel/sched/core.c`)。它是 Linux 调度器主入口。读它前 50 行,看它怎么 disable preemption、调 `pick_next_task`、`context_switch`。这就是 xv6 `scheduler()` 的 Linux 版。

候选 B:`do_page_fault` / `exc_page_fault`(在 `arch/x86/mm/fault.c`)。它是 x86_64 的 page fault 入口。读前 80 行,看它怎么读 CR2、`find_vma`、`handle_mm_fault`。这就是 §6 讲的那条路径的源码。

候选 C:`copy_process`(在 `kernel/fork.c`)。它是 `do_fork` 的核心,负责真正"复制"一个 task_struct。这个函数很长(700 行),但你只读它的主干:复制 mm_struct(`copy_mm`)、复制 files(`copy_files`)、复制 signal(`copy_signals`)、复制 namespace(`copy_namespaces`)。每一项对应 xv6 `fork()` 里的一两行,在 Linux 里是一大段。读完你会**切身**体会"xv6 删掉了什么"。

定位方法:

```bash
# 装 Linux 源码(Arch)
sudo pacman -S linux-headers   # 装的是当前内核对应的头
# 或者直接 clone(慢但完整)
git clone --depth 1 https://github.com/torvalds/linux
cd linux

# 找函数
rg "^void __schedule" kernel/sched/core.c
rg "^(void|asmlinkage).*do_page_fault" arch/x86/mm/fault.c
rg "^static.*copy_process" kernel/fork.c
```

挑一个,读 50-100 行(不需要读完整个函数),写一段 300 字笔记:这个函数做什么?它和你读过的 xv6 对应函数概念上一致吗?Linux 多出来的复杂度是为了什么?(COW?NUMA?cgroup?security hook?)

**步骤 5**:把你的 xv6 笔记 + Linux 笔记 commit 到你 HH 项目的 `notes/` 或 `docs/` 目录(纯 markdown,几个 KB)。以后你调 syscall 时翻这个笔记,会迅速回忆起"那东西底下是什么"。

做完这五步,你就完成了这一篇的"做中学"。**从这一刻起,你写的每个 syscall 都不再是无意识的——你知道它进了 `kernel/` 的哪个文件、改了哪个 struct、走完了哪条 call chain**。这就是"下钻到底"。

## 10 · 练习

### Lv1 · 概念辨析

**题**:用你自己的话(不超过 250 字)解释 xv6 的 `fork` 为什么要把子进程的 `trapframe->a0` 设成 0。如果忘了这一步,父子里看到的 fork 返回值会怎样?(提示:RISC-V 的 syscall 返回值放 a0 寄存器。)

**完成标准**:能说清"返回值通过寄存器传递,父子的寄存器在 swtch 后是各自独立的,所以设不同的 a0 就实现了不同的返回值"。

### Lv2 · 动手实践

**题**:clone xv6-riscv,跑起来。然后做 6.S081 的 lazy allocation lab(在 https://pdos.csail.mit.edu/6.S081/2020/labs/ 上的 "lazy" lab)。具体:修改 `kernel/trap.c` 的 `usertrap`,加一段处理 page fault(scause == 13 或 15)的代码,从进程的 VMA 表里找到对应地址,分配一页,挂上。然后让 sbrk 不真的分配物理页,只增大 `p->sz`。

提示:xv6 的 `sbrk` 在 `kernel/sysproc.c` 的 `sys_sbrk`,它调 `growproc` → `uvmalloc`,你要把这一段改成只改 `p->sz` 不真 alloc,真正的 alloc 放到 `usertrap` 的 page fault handler 里。

**完成标准**:`echo hi` 跑通(它需要 sbrk 来给参数分配),且 `lazytests` 通过。这一步让你**亲手**实现 page fault handler,把这一篇 §6 讲的机制变成你写的代码。

### Lv3 · 迁移设计

**题**:你的 HH 项目有一个 asset streaming 子系统,用 `mmap` 把关卡文件按需加载。Profile 显示玩家走到新区块时有一个 200ms 的尖峰,根因是大量 major page fault 同时发生。读 `mm/memory.c` 的 `do_read_fault` / `filemap_fault`(在 `mm/filemap.c`),理解 file-backed page fault 怎么从磁盘读页。然后写一个 300 字的设计:怎么消除这个尖峰?

提示方向:`madvise(MADV_WILLNEED)` 让内核预读;`readahead` syscall 主动触发预读;在另一线程用 `mincore` 检测哪些页没在 RAM,提前 `readahead` 它们。`filemap_fault` 的源码会告诉你"为什么单页单页读慢"——它每次只读一页,触发一次 IO,你可以批量预读减少 IO 次数。

**完成标准**:给出可行的预读策略,并在你的 HH 项目里实验验证尖峰从 200ms 降到 < 50ms。

### Lv4 · 开源贡献

**题**:Linux kernel 的 bugzilla 和 mailing list 上经常有"可读性"改进的 patch——重写注释、修复 typo、补充文档。在 https://elixir.bootlin.com/linux 上读 `kernel/sched/core.c` 的 `__schedule` 函数,看它的注释是否清楚。如果你觉得某段可以改清楚(比如某个参数没解释、某个分支没说为什么),写一个 patch 发到 LKML。

或者更入门的:在 https://github.com/mit-pdos/xv6-riscv 上提一个 issue 或 PR,改进某个函数的注释或修复一个 typo。xv6 团队非常欢迎教学性改进——更好的注释让下一代学生少走弯路。

**完成标准**:有一个发出去的 patch / PR,不论是否 merge。

## 11 · 延伸阅读

本仓库本地资料:
- [phase-0/08-processes-and-signals.md](../../phase-0/08-processes-and-signals.md) — 进程、信号、fork/exec/wait 的 API 层(这一篇是它的"下钻"版)
- [phase-0/15-c-and-assembly-reading.md](../../phase-0/15-c-and-assembly-reading.md) — 读 C 和汇编的姿势,这一篇把它用在内核上
- [phase-0/07-linux-filesystem.md](../../phase-0/07-linux-filesystem.md) — VFS、inode、文件描述符,内核 fs 子系统的用户视角
- [virtual-memory-and-allocators.md](virtual-memory-and-allocators.md) — mmap、page fault、分配器(这一篇讲了 page fault handler 的实现)
- [scheduling-and-thread-affinity.md](scheduling-and-thread-affinity.md) — CFS、线程亲和性、sched_setaffinity(这一篇讲了 CFS 的源头 `__schedule`)
- [async-io-and-streaming.md](async-io-and-streaming.md) — io_uring、epoll、异步 IO 的 syscall(这一篇讲了 syscall trap 的实现)

外部稳定 URL:
- MIT 6.S081 Operating Systems(xv6 配套课程,视频 + lab):https://pdos.csail.mit.edu/6.S081/2020/
- xv6-riscv 源码仓库:https://github.com/mit-pdos/xv6-riscv
- xv6 book(Frans Kaashoek 等写的 xv6 注释书):https://pdos.csail.mit.edu/6.828/2020/xv6/book-riscv-rev1.pdf
- Linux 内核源码在线浏览(带交叉引用):https://elixir.bootlin.com/linux
- Linux Kernel Newbies(每个版本的新特性导读):https://kernelnewbies.org/
- Robert Love, Linux Kernel Development(第三版)—— Linux 内核概念入门最清楚的英文书之一
- Bovet & Cesati, Understanding the Linux Kernel(老但概念讲解扎实)
- LWN.net:深入内核子系统的英文长文,例如 https://lwn.net/Articles/822834/(CFS 详解)

真实开源源码:
- xv6 `kernel/proc.c`(fork / scheduler / sleep / wakeup):https://github.com/mit-pdos/xv6-riscv/blob/master/kernel/proc.c
- xv6 `kernel/vm.c`(页表 / uvmcopy / uvmunmap):https://github.com/mit-pdos/xv6-riscv/blob/master/kernel/vm.c
- xv6 `kernel/trap.c`(usertrap / usertrapret):https://github.com/mit-pdos/xv6-riscv/blob/master/kernel/trap.c
- xv6 `kernel/syscall.c`(syscall 派发表):https://github.com/mit-pdos/xv6-riscv/blob/master/kernel/syscall.c
- Linux `kernel/fork.c`(`copy_process`,700 行的 fork 核心):https://github.com/torvalds/linux/blob/master/kernel/fork.c
- Linux `kernel/sched/core.c`(`__schedule` / `pick_next_task`):https://github.com/torvalds/linux/blob/master/kernel/sched/core.c
- Linux `mm/memory.c`(`handle_mm_fault`,page fault handler):https://github.com/torvalds/linux/blob/master/mm/memory.c
- Linux `arch/x86/mm/fault.c`(`exc_page_fault`,架构相关入口):https://github.com/torvalds/linux/blob/master/arch/x86/mm/fault.c
- Linux `arch/x86/entry/entry_64.S`(`entry_SYSCALL_64`,syscall 汇编入口):https://github.com/torvalds/linux/blob/master/arch/x86/entry/entry_64.S
