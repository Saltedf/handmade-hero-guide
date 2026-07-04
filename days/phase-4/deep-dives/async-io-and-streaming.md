
# 异步 I/O 与资产流式加载:epoll / io_uring / mmap vs read

> 你的 HH 项目刚做出第一座有天空盒、有地形、有 NPC 的小镇。一切看起来都对——直到你让玩家往镇外走。游戏在 `load_assets("forest.hha")` 上卡了整整 2 秒。屏幕冻结,鼠标不动,音频还在响但画面是死的。玩家以为崩了,Esc 退出。你打开 profiler,那 2 秒全是 `read()` syscall——你的主线程被磁盘堵住了,什么都没干。你试着把它挪到 worker 线程,不卡画面了,但内存峰值飙到 8GB,加载完的纹理被一次性塞进 GPU 时又卡了 200ms。**这一篇把这个链条彻底讲透**:为什么 `read()` 会堵线程,Linux 的异步 I/O 是怎么从 `select` 演化到 `epoll` 又到 `io_uring` 的,`mmap` 为什么有时候比 `read` 更聪明,以及职业引擎怎么把世界切成 chunk 在后台流式加载——让开放世界在你跑动时无缝展开,玩家根本感觉不到磁盘存在。读完这一篇,你应该能在 HH 项目里搭一条"游戏线程永不被磁盘阻塞"的加载管线,并理解 Casey 在 HH Day 270+ 把 asset loading 单独开线程这件事,本质上是在和 Linux 内核谈判。

## 0 · 一个让你膝盖中箭的场景

先把场景焊死,后面所有理论都从这个场景长出来。`main.rs` 里有一段代码,长得像新手教程:

```rust
fn load_level(path: &str) -> Level {
    let mut file = File::open(path).unwrap();
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes).unwrap();   // ← 这一行堵 2 秒
    parse_level(&bytes)
}

fn main() {
    let mut game = Game::new();
    game.level = load_level("town.hha");     // 主线程冻住
    game.run();                              // 这里才开始跑循环
}
```

启动时 2 秒黑屏,玩家勉强能忍。然后你做了世界地图,玩家走到边界要切到下一关,你又调了一次 `load_level("forest.hha")`。这次玩家是**正在玩着**的时候撞上的,2 秒冻屏直接劝退。

你查 profiler,发现两件事。第一,`read_to_end` 真的在等磁盘——你的 NVMe 标称 7 GB/s,town.hha 是 200MB,理论 30ms 该读完,实际却是 2000ms。因为 `read_to_end` 是循环调 `read()`,每次读 8KB,200MB 被切成 25000 次 syscall,固定开销加上 page cache 冷启动、内核 readahead 没跟上,墙钟时间轻松到 2 秒。第二,这 2 秒里你的 8 核 CPU 利用率只有 12.5%——一个核在 `read()`,另外 7 个闲得发慌,游戏循环、物理、AI 全停。这就是**阻塞 I/O 的暴政**:一个线程被磁盘卡住,连带它本来该服务的整帧都丢了。

这一篇的全部目标,就是**让玩家感觉不到那 2 秒存在**。几条路:把阻塞挪到别的线程(threading),或者用 OS 的就绪/完成通知(epoll / io_uring),又或者改变数据进内存的方式(`mmap`),最后把它们组合成流式加载架构。一条一条来。

## 1 · 为什么 read() 会堵住你的线程

要理解异步 I/O,必须先理解同步 I/O 到底在堵什么。

当你调 `read(fd, buf, len)`,你以为只是一条 CPU 指令,其实内核在背后做了一大堆事:它先看 page cache(kernel 维护的磁盘缓存,见 [phase-0/24-memory-foundation](../../phase-0/24-memory-foundation.md))里有没有这块数据;如果有,直接 memcpy 到你的 `buf`,这是快路径,纳秒到微秒级;如果没有,内核要发起真正的磁盘 I/O——给磁盘控制器发命令、等 DMA 把数据搬到内存、等中断回来标记完成。这一等,在 NVMe 上是几十微秒,在机械硬盘上是 10 毫秒级别(磁头要物理移动)。

关键在于:**等磁盘的这段时间里,你的线程被内核标记为 "TASK_INTERRUPTIBLE" 状态,从运行队列里摘掉了**。CPU 把它让给别人,但你的线程自己什么都做不了,直到数据就绪、内核把它唤醒。从代码视角看,就是 `read()` 这一行卡了 2 秒才返回。

这件事在你的游戏循环里是**致命的**。我们在 [09B-1 游戏循环与固定步长](../../phase-9/09B-1-game-loop-and-timestep.md)里讲过,固定步长循环靠一个累加器消费现实时间——每攒够 1/60 秒就跑一次逻辑步进。如果某次循环里 `read()` 卡住 50ms,累加器被灌满 3 个步进的量,等线程醒来一次性追三步,玩家会看到画面跳一下。**异步 I/O 的全部意义,就是让游戏线程永远不进这种"睡眠等待"状态**——它要么在跑逻辑,要么在 poll 看数据有没有好(但绝不睡死)。

打个比方:同步 `read()` 是你自己跑去仓库取货,仓库慢你就干等;异步 I/O 是你给快递员下一个订单然后继续干活,快递员把货送到门口按门铃通知你。两种模式取货总时间一样,但你"被卡住"的时间天差地别。游戏里我们最在乎的就是后者——主线程被卡住的时间必须接近零。

## 2 · 第一条路:把阻塞挪到别的线程

最直觉、也最常用的解法,是承认"`read()` 会阻塞"这个事实,然后**让它阻塞别人,不要阻塞主线程**。

具体做法是开一个或多个 I/O 线程,专门跑阻塞的 `read()`。主线程把"请加载 forest.hha"这个请求塞进一个队列,I/O 线程从队列里取出请求、`read` 文件、解析、把成品 `Texture` / `Mesh` 塞进另一个完成队列,主线程每帧末尾从完成队列里取出已加载好的资产、上传到 GPU、加进场景。队列本身用 SPSC ring 或 lock-free MPSC(见 [threading-journey](../../phase-5/deep-dives/threading-journey.md) 和 [threading-models](threading-models.md))。

这套结构在 HH 里就是 Casey 的做法——Day 270+ 他开了一个 asset loading 线程,主线程通过原子指针和它通信。在工业引擎里它叫 **job-based asset loading**:每个资产一个 job,job 跑在 worker pool 上,worker 内部用 `read` 或 `pread`。

代码骨架长这样:

```rust
use std::sync::Arc;
use crossbeam_queue::ArrayQueue;
use std::path::PathBuf;

pub enum LoadRequest { Texture { path: PathBuf, tag: u64 },
                       Mesh    { path: PathBuf, tag: u64 } }
pub struct LoadResult { pub tag: u64, pub data: Vec<u8> }

pub struct IoBridge {
    requests: Arc<ArrayQueue<LoadRequest>>,
    results:  Arc<ArrayQueue<LoadResult>>,
}

impl IoBridge {
    pub fn spawn(self: &Arc<Self>) {
        let (r, d) = (self.requests.clone(), self.results.clone());
        std::thread::spawn(move || io_thread_body(r, d));
    }
    // 主线程 API:push 一行就返回,绝不阻塞
    pub fn request(&self, r: LoadRequest) { let _ = self.requests.push(r); }
    pub fn drain_results(&self, sink: &mut Vec<LoadResult>) {
        while let Some(r) = self.results.pop() { sink.push(r); }
    }
}

fn io_thread_body(reqs: Arc<ArrayQueue<LoadRequest>>,
                  res:  Arc<ArrayQueue<LoadResult>>) {
    loop {
        if let Some(req) = reqs.pop() {
            // 这里阻塞也 OK —— I/O 线程不在游戏循环里,卡多久都不影响帧率
            let bytes = std::fs::read(req.path()).unwrap_or_default();
            let _ = res.push(LoadResult { tag: req.tag(), data: bytes });
        } else {
            std::thread::sleep(std::time::Duration::from_micros(200));
        }
    }
}
```

(`LoadRequest` 上加 `path()` / `tag()` 访问器即可,真实解码见 [asset-pipeline-architecture](../../phase-7/deep-dives/asset-pipeline-architecture.md) 和 [asset-compression](asset-compression.md)。)

这套方案的好处是**简单、跨平台、够用**。Windows、macOS、Linux 都能跑,只要标准库的 `std::fs` 在,就能用。Casey 在 HH 上用的就是这个模式的 Win32 版本。90% 的中型游戏(单关卡、关卡切换不频繁)用这个就够了。

但它有几个不那么明显的代价。**第一,线程是有成本的**。每个 I/O 线程是一个完整的内核线程,有自己的内核栈(典型 8-16KB)、调度实体、要参与调度器抢占。为了"并发处理 100 个加载请求"开 100 个线程,每个都在 `read()` 上睡觉,你把成本转嫁给了内核调度器——100 个线程的元数据、上下文切换、TLB 抖动都不是免费的。线程池能缓解(pool size = 核数),但本质上**每条在飞的 I/O 都占一个内核线程**。**第二,`read()` 在内核里仍然是阻塞的**——你只是把它从游戏线程挪开了,内核还是要挂起那个 I/O 线程、等磁盘、再唤醒。如果你有一万个并发连接(MMO 后端、HTTP 服务器场景),一万个睡觉线程的内存和调度开销会拖垮机器。这就是著名的 **C10K 问题**,上世纪 90 年代困扰网络服务器界的难题,正是它推动了 Linux 异步 I/O 的演化。

**第三,完成队列是异步入队的,但"上传到 GPU"通常必须在主线程或渲染线程做**(Vulkan/OpenGL 的 command buffer 提交、context 限制)。即便数据已在完成队列里,你也要等主线程下一帧末尾才能消化——资产从"磁盘读完"到"画面里可见"还有一帧延迟。这个延迟在 open-world streaming 里其实正合适(见第 8 节),但你要知道它存在。

threading 方案是**务实派**。下面这条路是**激进派**:让一个线程同时管理几千条在飞的 I/O,谁也不阻塞。

## 3 · 第二条路:让 OS 通知你——从 select 到 epoll

要理解 epoll,先回到那个快递员比喻。线程方案是"每个订单雇一个快递员,快递员在仓库门口等";异步 I/O 是"你只雇一个快递调度员,他同时盯着几千个订单,哪个订单的货备齐了他就告诉你"。

Linux 提供这种"调度员"能力的接口,最早是 `select`(1983 年,4.2BSD)和 `poll`(1986 年,SVR3)。你给它一个文件描述符(fd)列表,调一次 syscall,**这次调用阻塞直到至少一个 fd 就绪**,返回时告诉你"这几个 fd 现在可以读了"。但 select/poll 有一个致命问题:每次返回后,你得**遍历整个 fd 列表**找出哪些就绪——盯着一万个连接,每次只有 10 个有事件,你还是要扫一遍 10000 个,复杂度 O(n)。更糟的是,下一轮你要把这一万个 fd 重新传给内核,内核又要把它们一个个注册到自己的等待队列里。连接数上到几万,这套机制就吃不动了。

2002 年 Linux 2.6 引入了 **epoll**,这是网络服务器的"工作马"(workhorse),至今仍是 nginx、Redis、tokio 的核心。epoll 把 select/poll 的 O(n) 扫描换成了 O(1) 的就绪通知。做法是:**epoll 在内核里维护一个长期存在的 interest set(你关心的 fd 集合),用 `epoll_ctl` 增删改(每个 fd 只注册一次);然后用 `epoll_wait` 阻塞等待,内核只把"实际就绪的 fd"塞进一个小的 ready list 返回给你**。一万个连接里只有 10 个就绪,`epoll_wait` 只返回那 10 个,扫描成本是 O(就绪数)而不是 O(总数)。

最简化的 epoll 用法(用 Rust + libc 直接调 syscall):

```rust
use libc::*;
use std::os::unix::io::RawFd;

fn make_epoll() -> RawFd {
    unsafe { epoll_create1(0) }
}

fn add_fd(epfd: RawFd, fd: RawFd, events: u32) {
    let mut ev = epoll_event {
        events,
        u64: fd as u64,           // 用 data 字段塞回 fd,事件返回时能拿到
    };
    unsafe { epoll_ctl(epfd, EPOLL_CTL_ADD, fd, &mut ev); }
}

fn wait(epfd: RawFd, out: &mut [epoll_event]) -> usize {
    let n = unsafe { epoll_wait(epfd, out.as_mut_ptr(), out.len() as i32, -1) };
    if n < 0 { 0 } else { n as usize }
}
```

epoll 对**网络**简直是天作之合。一个线程能扛十万并发连接(nginx 实测),C10K 在 epoll 时代成了过去式。

但对**文件 I/O**,epoll 有一个尴尬的历史遗留问题:**普通磁盘文件总是"就绪"的**。原因是磁盘 I/O 在内核里不走和 socket 一样的等待队列机制——普通文件 `read()` 永远不返回 `EAGAIN`,它在内核里是同步完成的(数据从 page cache 拷贝过来,没拷完就一直阻塞),所以 epoll 标记它"可读"也没意义,你 `read` 它还是会堵。历史上 Linux 想过几套补丁(`O_NONBLOCK` 对普通文件无效、`aio` 系列 glibc 实现是用户态线程模拟、libaio 是原生但接口难用且有限制),没有一套让人满意。**文件 I/O 在 Linux 上长期是"难以真正异步"的**——直到 io_uring 出现。

## 4 · 第三条路:io_uring,Linux 异步 I/O 的革命

2019 年 Linux 5.1 合并了一个新接口叫 **io_uring**,作者是 Jens Axboe(Linux 块 IO 维护者)。它一出现就被称作"Linux 异步 I/O 的革命",因为它**同时**解决了三个老问题:文件 I/O 真异步、零系统调用开销、统一接口覆盖文件和 socket。

io_uring 的核心是**两个 ring buffer**(环形队列):SQ(submission queue,提交队列)和 CQ(completion queue,完成队列),都是内核和用户态**共享内存**的单生产者单消费者环形缓冲。发起一次异步读?你**不调 syscall**——直接在用户态往 SQ 里写一条 submission entry(写明"读这个 fd、读到这个 buffer、读多少字节"),写完后可选地调一次 `io_uring_enter` 通知内核。内核那边有个内核线程拿走这些 entry,执行真正的 I/O,**完成后把结果写进 CQ**。你的用户线程定期 poll CQ(也不调 syscall,直接读共享内存)拿走数据。

这两个 ring 是 mmap 出来的共享内存(见 [phase-0/24-memory-foundation](../../phase-0/24-memory-foundation.md) 关于 mmap 的概念),所以"提交一个任务"和"看到一个完成"都是**纯用户态内存读写**——没有 syscall,没有用户态/内核态切换。这就是 io_uring 文档里说的 "zero syscall per op" 的真意。

io_uring 的接口在 Rust 里通过 `io-uring` crate 或 `tokio-uring` 暴露。最小例子长这样:

```rust
use io_uring::{IoUring, opcode, types};
use std::os::unix::io::AsRawFd;

fn main() -> std::io::Result<()> {
    let mut ring = IoUring::builder()
        .setup_sqpoll(std::time::Duration::from_millis(1000))  // 内核轮询模式
        .build(64)?;

    let file = std::fs::File::open("forest.hha")?;
    let mut buf = vec![0u8; 4096];

    // 准备一条 read 提交 entry
    let read_e = opcode::Read::new(
        types::Fd(file.as_raw_fd()),
        buf.as_mut_ptr(),
        buf.len() as _,
    )
    .build()
    .user_data(0x1234);   // 完成时凭这个 token 找回这条请求

    unsafe { ring.submission().push(&read_e).expect("SQ 满"); }
    ring.submit()?;       // 这里通知内核(也可省略,SQPOLL 模式下内核自轮询)

    // 主线程现在去干别的——渲染、AI、物理都行
    // 想知道有没有完成,poll CQ:
    loop {
        if let Some(cqe) = ring.completion().next() {
            assert_eq!(cqe.user_data(), 0x1234);
            println!("读到 {} 字节", cqe.result());
            break;
        }
        // 这里可以插游戏循环逻辑
        do_some_game_work();
    }
    Ok(())
}

fn do_some_game_work() { /* ... */ }
```

注意上面那段 `loop` ——**这就是异步 I/O 的精髓**:主线程在等数据的同时**一直在干活**,它从来没有"阻塞睡眠",只是时不时瞄一眼 CQ 看有没有完成。读磁盘的那几百微秒到几毫秒,主线程用在了渲染和 AI 上,完全没浪费。

为什么说 io_uring 是革命,可以列三件事。**第一,它统一了文件和 socket**——同一套 SQ/CQ 接口既能 `read` / `write` / `fsync` 文件,也能 `accept` / `recv` / `send` socket,再也不用文件用 libaio、网络用 epoll 这两套互不相干的 API。**第二,它真的零拷贝、真异步**——`IORING_OP_READ` 提交后,内核直接 DMA 到你给的 buffer,中途你的线程完全自由,这是 Linux 历史上第一次让普通文件 I/O 真的"提交即返回、完成再通知"。**第三,它支持 polling 模式**(`IORING_SETUP_SQPOLL`),内核开一个专属线程轮询 SQ,你连 `io_uring_enter` 都不用调——提交一个任务就是写共享内存。代价是占一个核,但换来**最低延迟**的 I/O 路径,数据库和高频交易在用。

当然,io_uring 不是没代价。它需要 Linux 5.1+(许多特性要 5.6+,`SQPOLL` 要 5.11+),跨平台游戏要 fallback;API 学习曲线陡(SQE 链式、buffer ring、registered buffers 都有讲究);它历史上出过几轮安全漏洞(2022 年一系列 wday 漏洞导致 Google 把 Chrome/Android 上的 io_uring 关了),服务器侧用得多,桌面应用要注意权限模型。但对游戏这种受信进程,io_uring 是 2026 年 Linux 上最锋利的 I/O 武器。

**tokio 和 async Rust 是用户态的一层包装**。tokio 的 runtime 在 Linux 上默认用 epoll(reactor 模式)调度所有 `async fn`;当你 `tokio::fs::read` 时,tokio 把它扔到自己的 blocking thread pool(本质上是第 2 节的 threading 方案)。tokio-uring 是另一个 crate,它真的用 io_uring 来跑 `async fn`,但 API 范式要求专属 buffer类型和 `tokio_uring::main`。**如果你写一个全新的 Linux-only 游戏 I/O 层,直接用 io_uring 是最高性能的;如果想跨平台和生态成熟,tokio + blocking pool 是务实之选**。

到这里,三条异步 I/O 的路讲完了:threading(简单、跨平台、有线程开销)、epoll(网络神、文件废)、io_uring(全能王、Linux only)。下面换一个角度——不是"用什么 API",而是"数据怎么进内存"。

## 5 · mmap vs read:数据进内存的两条路

不论你用 threading 还是 io_uring,你最终都要把磁盘上的字节弄到你的进程地址空间里。Linux 提供两种本质不同的机制:`read()` 和 `mmap()`。理解它们的差别,是选择加载策略的前提。

**`read()` 的数据流**:磁盘 → 内核 page cache(一份拷贝)→ 你的用户 buffer(第二份拷贝)。注意中间多了一次 memcpy——内核不会让你直接看 page cache 的内存,它会把数据从 page cache 拷一份到你 `read()` 时传进来的指针。这两份拷贝在某些场景是浪费,但也是安全隔离的代价。

**`mmap()` 的数据流**:磁盘 → 内核 page cache(就这一份)。`mmap` 把文件"映射"到你的进程地址空间——它在你虚拟地址空间里**预留一段地址**,告诉页表"这段地址对应这个文件的某些偏移"。**第一次访问这段地址时,CPU 触发缺页异常(page fault),内核才知道你要这页数据,才把它从磁盘读进 page cache**,然后让你的虚拟地址指向 page cache 里的那一页。**没有任何额外的 memcpy**——你的进程和内核共用同一份物理内存。

这就是 mmap 的核心魔法:**数据按需加载,只读你摸到的页**。

```rust
use std::fs::File;
use memmap2::Mmap;

let file = File::open("forest.hha")?;
let mmap = unsafe { Mmap::map(&file)? };

// 到这一行,数据其实还没从磁盘读!mmap 只是建好了映射。
// 第一次访问时才触发 page fault:
let first_byte = mmap[0];   // ← page fault,内核去读磁盘的第一页
let last_byte  = mmap[mmap.len() - 1];  // ← 另一次 page fault
```

mmap 在以下场景**显著优于** read:

第一,**大资产稀疏访问**。一个 4GB 的 glTF 场景文件,你只需要它的 vertex table(在文件中部),其他部分用不到。read 要把 4GB 全读进内存;mmap 只在你访问 vertex table 那几页时才从磁盘读那几页,其他页从来不进内存——**这就把"读 4GB"变成了"读 50MB"**。

第二,**多进程共享同一文件**。两个游戏实例(开发时的编辑器 + 运行时)映射同一个 4GB 资产包,内核里只有一份 page cache,两个进程通过页表共享同一份物理内存。read 做不到——每个进程都拷一份。

但 mmap 不是银弹。**第一,page fault 是同步的**——你访问 mmap 的某页触发 fault,内核在这一刻才去读磁盘,你的线程**仍然阻塞**等数据。所以 mmap 本身不解决"不阻塞主线程",它只是把阻塞推迟到你访问内存的那一刻。**主线程访问 mmap 的内存依然会卡**。要把 mmap 变成真正的异步,得用 `madvise(MADV_WILLNEED)` 或 `readahead()` 提前告诉内核"我马上要这段,你后台预读",或用 `io_uring` 的 `IORING_OP_MADVISE`。

**第二,小文件 mmap 反而更慢**。mmap 要建 VMA(virtual memory area)、改页表、handle fault,固定开销比 read 大。经验值是 64KB 以下别 mmap。**第三,顺序全读时 read 通常更快**——你把整个文件从头读到尾(加载完整纹理的典型场景),read 的 readahead 机制能让磁盘顺序读满带宽,而 mmap 的 page fault 路径反而慢(每个 fault 都要陷入内核)。**第四,信号处理的复杂性**:mmap 的文件被别人截短了,你访问被截掉的页会收到 SIGBUS,默认动作是杀进程。**第五,TLB 压力**:mmap 一段很大的地址范围会占用很多 TLB entry,ARM 上尤其明显。

**总结**:对于"完整顺序读一个资产"的 streaming 场景,`read`(配合 io_uring 或 worker thread)通常和 mmap 持平甚至更优,而且更可预测;对于"稀疏访问大文件"(大型世界数据库、PVR 虚拟纹理、glTF 场景),`mmap` 显著省内存省 I/O。**职业引擎两者都用,按资产类型分发**——纹理/模型走 read streaming(因为通常要全部上传 GPU),虚拟纹理 page cache、场景图节点走 mmap。

这一节的精神和 [asset-compression](asset-compression.md) 是连着的:压缩格式决定了你能不能稀疏解压(LZ4 stream 可以、Zstd 大窗口可以、PNG/JPEG 单文件不行),而稀疏解压配合 mmap 是 open-world 虚拟纹理的基石。

## 6 · 拼起来:异步 I/O + mmap 的工程组合

讲完三个零件,我们看怎么把它们组合成真正可用的 I/O 层。下面是三种务实组合:

**策略 A(默认,简单):threading + read**。开 N 个 I/O 线程(N = 物理核数的一半),每个线程从请求队列拿任务、用大 buf(`read_to_end` 容量设 1MB,避免 syscall 碎片化)读完整个文件、解码、塞回完成队列。主线程每帧末尾 drain 完成队列。这是 90% 游戏的方案,跨平台,简单。**第 2 节那段 `IoBridge` 就是这个策略的最小实现**,把它扩成带优先级和取消的版本就是生产骨架。

**策略 B(Linux 高性能):io_uring + read + buffer ring**。一个 io_uring 实例,注册一组 registered buffers(避免每次 SQE 重复注册 buffer),提交所有 read 操作;主线程每帧 `io_uring_enter` 一次收割完成事件。这是 Linux 平台的最佳实践,但要 Linux 5.6+ 和 io-uring crate。

**策略 C(大文件稀疏):mmap + madvise + 异步预读**。把大资产(>100MB 的虚拟纹理、巨型场景)用 mmap 映射,主线程**不直接访问**它;而是由 I/O 线程或 io_uring 提前 `madvise(MADV_WILLNEED)` 推动内核后台预读(或发 `readahead()` syscall)。主线程访问的时候,数据已经在 page cache 里了,fault 几乎不阻塞。这是 PS5 的 Kraken / 虚拟纹理流式加载的内核侧思路。

主循环这边每帧做两件事:发请求(检测到玩家接近 forest 边界)、收结果(每帧末尾 drain)。**主线程一行阻塞 syscall 都不调**。这是 streaming 的最低骨架,下一节我们把它扩成完整的开放世界流式加载。

## 7 · 开放世界的流式加载:把世界切成 chunk

现在我们终于回到开场那个场景——玩家在镇外跑,forest 慢慢"长"出来。职业引擎怎么做到玩家感觉不到加载?

答案是**流式加载**(streaming),核心是四步循环:**切块 → 预测 → 请求 → 整合 + 驱逐**。

**第一步:把世界切成 chunk**。整个开放世界不是一整个 4GB 的 .hha,而是被切成几百个小包——每个 chunk 是 64m × 64m 的地形 + 它上面的纹理 + 模型 + 碰撞,单独打包成一个几 MB 的小文件(或者一个大文件里的几 MB 一段)。这是 [asset-pipeline-architecture](../../phase-7/deep-dives/asset-pipeline-architecture.md) 在打包阶段要做的事——build 时按空间坐标切块,运行时按需加载。

**第二步:预测玩家马上要什么**。每帧主线程算玩家当前位置 + 速度向量,外推未来 1-2 秒的位置,看哪些 chunk 在玩家的"加载半径"(典型 200m)内、目前还没加载。这些就是要请求的 chunk。也可以分级:近的 chunk 用高 mipmap,远的用低 mipmap,先加载低精度版占位,高精度版后台慢慢替上来(这就是 mip streaming / clipmap 的思路)。

**第三步:发请求**。把"要加载的 chunk"丢给第 6 节的 `StreamingIo`。**关键细节:请求要带优先级**。玩家正前方的 chunk 优先级最高(马上要踩进去),背后的最低。I/O 队列要是 FIFO,会让"身后远处一个不重要的 chunk"占着带宽,挡住"面前一个马上要的 chunk"。职业引擎用一个优先级队列,优先级根据"到玩家的距离 + 玩家视线方向夹角"算。

**第四步:整合 + 驱逐**。完成的 chunk 数据从完成队列出来,主线程把它解码、上传 GPU(或加进 GPU 流式纹理池)、塞进场景图。**同时要驱逐远处的 chunk**——玩家已经走过了的 chunk,如果不在某个更大的"保留半径"内(典型 500m),就卸载它的 GPU 资源、释放内存。否则内存会被几小时的游戏过程慢慢灌满。

整合这一步有个**关键时序约束**:你不能在帧中间突然把一个 chunk 加进场景——那会让物理 / AI / 渲染在一帧里看到不一致的状态(一半有碰撞、一半没有)。**职业做法是双缓冲**:本帧正在用的世界状态是 A,后台加载好的 chunk 暂存在 B;每帧末尾的某个固定时机,原子地把 B 换成 A、A 释放。这就是 streaming 的 "frame boundary integration",和 [threading-journey](../../phase-5/deep-dives/threading-journey.md) 里讲的双缓冲 render resource 同源。

下面是一段极简的 chunk streaming 控制器,演示预测 + 请求 + 整合 + 驱逐的完整循环:

```rust
use std::collections::{HashMap, HashSet};
#[derive(Hash, Eq, PartialEq)] pub struct ChunkId(pub i32, pub i32);

pub enum ChunkState { Loading, Ready { gpu: u64 } }   // gpu = 已上传 GPU 的 handle

pub struct Streamer {
    io: StreamingIo,                                  // 第 2 节那座桥
    loaded: HashMap<ChunkId, ChunkState>,
    pending: HashMap<u64, ChunkId>,                   // tag -> 请求的 chunk
    load_radius: f32,                                 // 加载半径(典型 200m)
    keep_radius: f32,                                 // 保留半径(典型 500m)
}

impl Streamer {
    pub fn update(&mut self, player_pos: (f32, f32), player_vel: (f32, f32)) {
        // 1. 外推 1 秒后的位置
        let future = (player_pos.0 + player_vel.0, player_pos.1 + player_vel.1);

        // 2. 找出"加载半径内还没加载"的 chunk,按距离排序后请求
        let mut want: Vec<(ChunkId, f32)> = chunks_in_radius(future, self.load_radius)
            .into_iter().filter(|c| !self.loaded.contains_key(&c.0)).collect();
        want.sort_by(|a, b| a.1.partial_cmp(&b.1).unwrap());
        for (chunk, _) in want {
            let tag = self.io.request(Kind::Mesh, chunk_path(&chunk));  // 非阻塞
            self.loaded.insert(chunk, ChunkState::Loading);
            self.pending.insert(tag, chunk);
        }

        // 3. 收完成、上传 GPU
        let mut done = Vec::new();
        self.io.poll(&mut done);
        for d in done {
            if let Some(chunk) = self.pending.remove(&d.tag) {
                let gpu = upload_to_gpu(&d.bytes);
                self.loaded.insert(chunk, ChunkState::Ready { gpu });
            }
        }

        // 4. 驱逐"keep 半径外"的 chunk
        let keep: HashSet<ChunkId> =
            chunks_in_radius(player_pos, self.keep_radius).into_iter().collect();
        self.loaded.retain(|id, st| {
            if keep.contains(id) { return true; }
            if let ChunkState::Ready { gpu } = st { free_gpu(*gpu); }
            false
        });
    }
}
// chunks_in_radius / chunk_path / upload_to_gpu / free_gpu 是与引擎耦合的占位
```

跑起来,你会看到玩家跑动时前方 chunk 一个个静悄悄地长出来,背后的悄悄消失,内存占用稳定在一个常数(loaded 的 chunk 数 ≈ π × keep_radius² / chunk_size²),帧时间平稳。**这就是开放世界"感觉不到加载"的全部秘密**。

这套架构在 [asset-pipeline-architecture](../../phase-7/deep-dives/asset-pipeline-architecture.md) 那篇里有更完整的打包侧描述——build 时怎么按 chunk 切、运行时怎么管理 chunk 间依赖。在 [asset-compression](asset-compression.md) 里讲了 chunk 内部用什么压缩(LZ4 实时解压)。内存侧所有 chunk 共用一个 arena 或 pool,驱逐时整体回收——见 [phase-0/24-memory-foundation](../../phase-0/24-memory-foundation.md) 的 arena / pool 章节。

## 8 · 一个常见的坑:streaming 不能让固定步长循环掉帧

streaming 整合进场景时,会不会破坏固定步长循环?这正是和 [09B-1 游戏循环与固定步长](../../phase-9/09B-1-game-loop-and-timestep.md) 紧密相关的一个点。固定步长循环的合约是每个 step 必须在固定预算内完成(典型 1/60 = 16.6ms);如果某个 step 因"刚整合了一个大 chunk,物理要重新计算 broadphase"超了 30ms,累加器就吃了两步的现实时间,掉帧。

streaming 要尊重这个合约,有几条原则。**第一,整合时不要做重活**——chunk 上传 GPU 是 cheap 的(command buffer submit,几十微秒),但"把新 chunk 加进物理 broadphase 加速结构"可能是重活,职业做法是**懒整合**:chunk 标记为 ready,物理系统分摊到后续几帧慢慢纳入。**第二,整合只在帧末尾做**——绝对不要在 step 中间修改场景图(那会让一个 step 的物理看到半个 chunk),固定在每一帧"渲染之前、所有 step 之后"那一刻原子地 swap streaming buffer。**第三,工作量要预算化**——一帧要整合 50 个 chunk(玩家快速传送)就每帧只整合 4 个,分 13 帧慢慢长出来。pop-in 是审美问题,卡顿是体验问题,前者可以忍,后者不能。**第四,完全不要在 audio 线程做 streaming**——audio 线程是 [threading-journey](../../phase-5/deep-dives/threading-journey.md) 强调过的"绝对 lock-free"线程,它要等磁盘就会断音(XRUN),audio sample 数据要预流式进 ring buffer,在游戏线程提前 N 秒填充。

这些约束让 streaming 看起来"啰嗦",但它们都是为了让玩家**感受不到 streaming 存在**——游戏世界仿佛一开始就在那里,只是慢慢向你展开。

## 9 · 生产现实:工业级 streaming 是什么样的

讲到这里,把工业现实摆出来,让你知道这套东西在天花板上是什么样。

**PS5 的 I/O 系统**是当下 console streaming 的标杆。它有一条专用 I/O 通道(SSD → I/O complex → RAM → GPU),硬件压缩(Kraken / zlib 解压芯片),硬件解密,和一组叫 "I/O engines" 的 io_uring 风格 submission/completion 队列。Mark Cerny 在 GDC 2020 road to PS5 演讲里讲过:加载 2 秒 vs 0.2 秒的差别,不只是快慢,而是**整个游戏设计**的不同——加载 2 秒你只能做关卡切换(loading screen),加载 0.2 秒你可以让玩家跑步时无缝飞过 chunk 边界。PS5 还有一个 "Geometry Engine" 能直接给 GPU 喂压缩 mesh,GPU 端解压。这套东西的内核侧 API 在概念上就是 io_uring + 硬件加速版。

**DirectStorage(Xbox Series + Windows)** 是微软对应的方案——游戏调 `Fence` 提交一批 read 请求,GPU 直接从 SSD 拿压缩数据解压,绕过 CPU。**Unreal Engine 5 的 Nanite** 把虚拟几何 streaming 推到极致,整个世界几何按像素级精度 streaming,它本质上是一个 GPU-side chunk streaming + cluster culling 系统,I/O 部分依然跑在第 6 节那套 threading/io_uring 之上。**Bevy 0.13+ 的 `bevy_asset`** 提供了 `AssetLoader` trait,内置异步加载 + 跨平台 abstraction,Linux 上目前主要用 blocking thread pool(策略 A)。

**Mip streaming / clipmap / virtual texture** 是图形端的 streaming。一张 16K × 16K 的纹理(1GB)不可能常驻显存,但 GPU 可以按需 page in 不同 mip level——离玩家近的用高 mip,远的用低 mip。这套系统的内核侧正是第 5 节讲的 mmap + 异步预读:CPU 端维护 "page table",GPU 缺页时反馈给 CPU,CPU 用 io_uring 异步读那一页,完成后更新 page table。这是 John Carmack 在 id Tech 5(MegaTexture)首创、到现在所有 AAA 引擎标配的技术。

**复杂度现实**:streaming 系统是引擎里最容易出隐蔽 bug 的子系统之一——优先级反转(低优先级请求占着带宽)、依赖死锁(chunk A 要 chunk B 的纹理,B 还没加载)、内存碎片(频繁 alloc/free chunk 让 arena 出洞)、取消竞态(玩家转身,刚请求的 chunk 还没回来要不要取消)、GPU 同步(uploaded chunk 的 command buffer 还没执行完就被驱逐,引发 use-after-free)。每一项都是真实的生产事故,有专门的 GDC talk 讲它们。但**这套复杂性换来的,是让玩家感觉世界是无限的**——这种无缝感是开放世界游戏的灵魂。

## 10 · 在你 HH 项目里动手(做中学红线)

理论够了,现在落到你的 HH 项目里。下面这一系列操作,是你把这一篇**真正变成肌肉记忆**的最低红线。

**第 1 步:搭一个后台 I/O 线程**。把第 6 节那段 `StreamingIo` 代码搬进你的项目,接进你现有的 asset 系统。把 HH Day 270+ 那个简陋的 worker 线程升级成有请求队列、完成队列、可取消的 streaming 桥。

**第 2 步:挑一个最大的资产做实验品**。找一个你项目里几十 MB 的纹理或 mesh(没有就生成一个 8K × 8K 的程序纹理,或者重复拼一个 200MB 的 dummy mesh)。先用同步 `read_to_end` 在主线程加载,用 [profiling-with-tracy](profiling-with-tracy.md) 量出阻塞时间(典型几百 ms 到几秒)。

**第 3 步:迁到后台线程**。改成 `io.request(...)`,主线程下一帧 `io.poll(...)` 收结果。在 Tracy 里看主线程的 frame time——**阻塞应该完全消失,稳定在 16ms 附近**(假设你跑 60 FPS)。这一步本身就完成了"主线程不被磁盘卡"的目标。

**第 4 步:实验 mmap vs read**。把 I/O 线程的实现换成 mmap 版(用 `memmap2` crate),配合 `madvise(MADV_WILLNEED)` 做预读。量两种方案的:加载总时间、page fault 次数(用 `perf stat -e page-faults`)、内存峰值(用 `/proc/self/status` 的 VmRSS)。你会看到 mmap 在大资产稀疏访问下确实省内存,但全顺序读时和 read 差不多。**这一步的目标不是用 mmap 换 read,而是理解两者各赢在哪**。

**第 5 步:加 chunk streaming(可选,如果项目已经支持玩家走动)**。如果你的 HH 已经有了一个能跑动的世界,把它切成 8×8 或 16×16 的 chunk,每个 chunk 单独一个文件。实现第 7 节那段 `Streamer` 的预测 + 请求 + 整合 + 驱逐。把加载半径调到能看见 chunk pop-in(故意小到 50m),再调到玩家完全感觉不到(200m+)。**亲眼看 pop-in 消失的过程,是这一节最有价值的体感**。

**第 6 步(进阶,Linux only):试试 io_uring**。把 `StreamingIo` 的 worker 换成一个 io_uring 实例(用 `io-uring` 或 `tokio-uring` crate),提交所有 read SQE,主线程每帧 `io_uring_enter` 收割。量线程数(I/O 线程从 N 降到 1)、CPU 利用率、p99 frame time。**这一步让你亲手摸到 io_uring 的零 syscall 路径**。

完成这六步,你的 HH 项目就具备了职业引擎 I/O 层的雏形——一个游戏线程永远不被磁盘阻塞、能流式加载资产、可选异步 I/O 加速的现代化管线。这是你做开放世界游戏、做大型 indie、做引擎工具的底层能力。

## 11 · 练习

### Lv1

写一个小程序,主线程打印当前毫秒时间戳,然后用 `std::fs::read` 读一个 100MB 的文件,再打印时间戳,看阻塞了多久。然后改成调一个 worker 线程去读、主线程同时跑一个 `loop { print!("."); sleep(10ms) }`——观察主线程是否还在持续打印。**这一步让你亲眼看到"阻塞"和"不阻塞"的差别**。

### Lv2

用 `strace` 跟踪 `std::fs::read_to_end` 在你的 HH 项目加载一个 50MB 文件时发出的所有 `read` syscall。数 syscall 的数量、看每次的 size。然后用 `BufReader::with_capacity(1 << 20, file)`(1MB buf)重写,再 strace 一次,对比 syscall 数量。**这一步让你理解为什么默认 read_to_end 慢、为什么 buf size 重要**。

### Lv3

把第 6 节的 `StreamingIo` 接进你的 HH 项目。把一个原本同步加载的资产(纹理或 mesh)改成异步加载。在 [profiling-with-tracy](profiling-with-tracy.md) 里量主线程 frame time 的 p99,确认异步加载之后不再有 frame 超过 17ms。**这一步是把这一篇理论变成你项目里真实代码的关键**。

### Lv4

把 `StreamingIo` 的 worker 换成 io_uring 后端(用 `tokio-uring` 或裸 `io-uring` crate)。对比 threading 版和 io_uring 版的:CPU 占用、p99 frame time、并发请求数上限。把发现写进你的项目 notes。这一步是 Linux 平台极致优化的入门券。

## 12 · 延伸阅读

本仓库内关联资料:

- [threading-models](threading-models.md) —— 游戏开发的线程模型,worker pool / work stealing 的基础
- [threading-journey](../../phase-5/deep-dives/threading-journey.md) —— 从 Mutex 到 lock-free 的完整演化,SPSC ring 在 audio streaming 里的角色
- [asset-compression](asset-compression.md) —— LZ4 / Zstd 选型,实时解压如何配合 streaming
- [asset-pipeline-architecture](../../phase-7/deep-dives/asset-pipeline-architecture.md) —— build 时如何按 chunk 切分资产,运行时如何管理 chunk 间依赖
- [phase-0/24-memory-foundation](../../phase-0/24-memory-foundation.md) —— page cache、虚拟内存、mmap 的内核侧基础
- [09B-1 游戏循环与固定步长](../../phase-9/09B-1-game-loop-and-timestep.md) —— 固定步长循环为什么不能容忍 I/O 阻塞
- [profiling-with-tracy](profiling-with-tracy.md) —— 量 streaming 对 frame time 影响的工具

外部稳定 URL:

- io_uring 入门(Lord of the io_uring,网络服务器演化史的浓缩):https://unixism.net/loti/
- Efficient IO with io_uring(Kernel Recipes 2019,Jens Axboe):https://www.youtube.com/watch?v=-5T4Cjw46ys
- Linux `epoll` man page:`man 7 epoll`,或 https://man7.org/linux/man-pages/man7/epoll.7.html
- The C10K problem(Dan Kegel 经典):http://www.kegel.com/c10k.html
- `mmap` man page:`man 2 mmap`,看 `MAP_POPULATE`、`MADV_WILLNEED`、`MADV_RANDOM` 的差别
- `memmap2` crate(Rust mmap):https://docs.rs/memmap2/
- `io-uring` crate:https://github.com/tokio-rs/io-uring
- `tokio-uring`:https://github.com/tokio-rs/tokio-uring
- tokio blocking pool 设计:https://docs.rs/tokio/latest/tokio/task/index.html#blocking-io
- Mark Cerny "Road to PS5" GDC 2020(PS5 I/O 系统):https://www.youtube.com/watch?v=Phw0K2Dq6RQ
- Nanite(SIGGRAPH 2021,虚拟几何 streaming 工业实现):https://advances.realtimerendering.com/s2021/
- id Tech 5 MegaTexture(Carmack,早期 virtual texturing):https://www.slideshare.net/IdSoftwareLtd/megatexture-in-rage-7250207
