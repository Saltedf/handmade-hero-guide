---
phase: 4
title_en: "Networking Syscalls: socket / epoll / io_uring and the Kernel Stack"
title_zh: "网络系统调用:socket / epoll / io_uring 与内核网络栈——你 09E 网络代码的真正底层"
type: deep-dive
difficulty: 4
duration: "3-4 小时"
domains: [system, network, rust, linux, game]
prereqs: ["09E-1-reliable-udp-transport", "phase-0/23-network-foundation"]
calibration: "网络 syscall(socket/epoll/kqueue)+ UDP/TCP 深做 + 内核网络栈 — 09E 网络的底层"
---

# 网络系统调用:socket / epoll / io_uring 与内核网络栈

## 0 · 你的 send_to 之后,那个包到底经历了什么

你在 09E-1 里写出了一个能跑的可靠 UDP 传输层。你给 `UdpSocket::send_to` 喂一段 byte 数组,对面就收到了。看起来像魔法——你写一行 Rust,数据就跨越了进程边界,甚至跨越了太平洋。但你停下来想:`send_to` 这一行,你的程序到底干了什么?它显然不是"自己"把数据送上网线的——你的用户态进程没有权限直接驱动网卡。那它做了什么?

答案是:它做了一次**系统调用**(system call,简称 syscall)。`send_to` 这一行 Rust 代码,最终被编译成一条特殊的 CPU 指令(在 x86-64 上是 `syscall`),让 CPU 从用户态(user mode)切换到内核态(kernel mode),把控制权交给 Linux 内核。内核接收你的请求——"请把这段字节,通过我那个 UDP socket,送到这个地址"——然后内核去干真正的活:构建 UDP 包头、查路由表、调网卡驱动、把字节灌到网卡的发送队列里。这一整套流程,你的代码一个字都没写,全是内核替你做的。

这一篇要讲的就是 `send_to` 这一行**底下**那一层。你会看到:socket 在内核里到底是什么(它真的"就是一个文件描述符"),UDP 和 TCP 在 syscall 层面有哪些根本不同(为什么 TCP 的可靠性你关不掉),为什么一个 blocking 的 `recv_from` 会让你的线程睡着,以及一台机器怎么扛住几万条并发连接(答案叫 epoll)。最后你会用 `strace`、`tcpdump`、`ss` 这三个工具,亲眼看到你 09E-1 写的代码在 syscall 和内核层面的真实行为——这种"看见底层"的能力,是你以后 debug "我的包为什么没到"这种玄学问题的唯一武器。

理解这一层不会让你写出更漂亮的 Rust 代码——`std::net` 和 tokio 已经把 syscall 封装得很优雅了。但它会让你**在出问题的时候知道去哪里看**。生产环境里,当你用 renet 写的联机代码出 bug,你打开 strace 看到 `recvfrom` 一直返回 `EAGAIN`,你立刻知道是 socket 被设成了 nonblocking 但你的 epoll 没注册这个 fd——这种诊断能力,纯靠读应用层代码是出不来的。这一篇就是给你装上这双"看见内核"的眼睛。

## 1 · socket 的本质:它就是一个文件描述符

要把网络的 syscall 讲透,得从 Unix 最核心的设计哲学讲起——**everything is a file**(一切皆文件)。这不是口号,是 Unix 内核 API 的设计原则:内核想让用户态进程操作的**任何东西**,都给它分配一个**文件描述符**(file descriptor,简称 fd),然后用同一套 API(`read` / `write` / `close` / `poll`)操作它。普通文件是 fd,管道(pipe)是 fd,终端(tty)是 fd——网络 socket,也是 fd。

你 `socket()` 这个 syscall 干的事,是让内核给你**创建一个网络端点**(network endpoint),在你进程的 fd 表里给它分配一个槽位,返回那个槽位的编号(非负小整数,通常 3 起步,因为 0/1/2 已被 stdin/stdout/stderr 占了)。从这一刻起你拿到的不是什么"网络对象",就是一个**数字**——但这个数字在内核里挂着的,是一整套网络栈的数据结构(发送队列、接收队列、协议状态机等等)。

你可以亲眼看到。任何进程在内核里持有的 fd,都映射到 `/proc/self/fd/` 这个目录下的符号链接:

```bash
# 一个 Rust 程序 bind 一个 UDP socket 然后睡住,看它的 fd:
ls -la /proc/$(pgrep mini-udp)/fd/
# lrwx------ ... 0 -> /dev/pts/2
# lrwx------ ... 1 -> /dev/pts/2
# lrwx------ ... 2 -> /dev/pts/2
# lrwx------ ... 3 -> socket:[1234567]   ← 这就是你的 UDP socket
```

那个 `3` 是 fd 编号,`socket:[...]` 告诉你它是 socket 类型的 fd,方括号里是内核里这个 socket 的 inode。一个 UDP socket,在内核眼里跟一个文件没本质区别——都是"一个可以 read/write 的 fd"。

这个设计的优雅在于**统一性**。你可以用 `poll()` 同时等一个 socket 可读、一个管道可读、一个普通文件可读——因为它们都是 fd。你可以把一个 socket fd 通过 `sendmsg` 的 `SCM_RIGHTS` 传给另一个进程(Android Zygote、systemd socket activation 的核心机制)——因为它就是个 fd。你能写一个泛型的 `fn handle(fd: RawFd)` 同时处理 socket 和管道——因为底层 API 是同一套。Unix 的网络 API 之所以比 Windows 的 WSA 简洁,就是因为继承了"一切皆文件"的统一性——Windows 那边 SOCKET 是独立句柄类型,跟文件 HANDLE 不兼容,要搞两套 API(虽然 Win10 后也支持了 socket-as-fd,但历史包袱还在)。

理解了"socket 就是 fd",你就能理解为什么 `recvfrom` 的签名长那样——它接收一个 fd,跟 `read` 接收一个 fd 是同一哲学。下面我们看围绕这个 fd,UDP 和 TCP 在 syscall 层面到底有什么不同。

## 2 · UDP vs TCP:在 syscall 层面它们差在哪里

[phase-0/23-network-foundation](../../phase-0/23-network-foundation.md) 讲过 UDP 和 TCP 的协议差异。这一节我们换个视角,看它们在**应用层写代码的时候**,通过 syscall 表现出来的差别。

UDP 对应的 socket 类型叫 `SOCK_DGRAM`(datagram,数据报)。它的核心特征是**面向消息**(message-oriented)。你每次调 `sendto` 发一段字节,内核就把这一段字节**原封不动**地作为一个独立的 UDP datagram 发出去——加一个 8 字节的 UDP 头(源端口、目标端口、长度、校验和),塞到 IP 包里,送上网。对面收到的时候,也是**按 datagram 边界**交付——你一次 `sendto` 100 字节,对面一次 `recvfrom` 拿到的就是这 100 字节,不会变成两次 50 字节,也不会跟下一次 `sendto` 的内容粘在一起。这种"消息边界保留"的特性,让你在 UDP 上写"一个包一个事件"的游戏协议特别自然:你发一个"玩家移动"包,对面收一个完整的"玩家移动"包,不需要自己切分包。

UDP 是**无连接**(connectionless)的。你的 socket 不需要先 `connect` 对方就能 `sendto`——每次 `sendto` 都要带一个目标地址参数,因为内核不知道你这个包要发给谁。这看起来啰嗦,但它的好处是**一个 socket 可以发给任何地址**:游戏服务器只需要一个 UDP socket,就能同时跟 1000 个玩家收发——每个进来的包带发送者地址,你 `recvfrom` 出来就知道是谁发的,回包的时候 `sendto` 那个地址就行。这就是为什么 09E-1 里那个 demo 只用一个 socket 就能跟一个远端通信,生产里的游戏服务器也只用一个 socket 处理所有玩家。

TCP 完全是另一套哲学。它对应的 socket 类型叫 `SOCK_STREAM`(stream,流)。TCP 是**面向连接**(connection-oriented)且**面向字节流**(byte stream)的。你得先 `connect` 一个特定地址,建立一条 1 对 1 的连接,然后才能 `send` / `recv`。一个 TCP socket **只对应一条连接**——你想同时跟 1000 个客户端通信,你得有 1000 个 TCP socket,每个 fd 是一条独立的连接。这就是为什么 TCP 服务器的经典模型是 `accept` 一个新连接就 `fork` / `spawn` 一个线程:每个连接独占一个 fd,各管各的。

字节流意味着 TCP **不保留消息边界**。你 `send("hello")` 再 `send("world")`,对面 `recv` 一次可能拿到 `"helloworld"`,也可能拿到 `"hel"`、`"loworl"`、`"d"`。TCP 把你写给它的字节**当成一条连续的水流**,不记录你写了"几次"——它只关心"按序把这些字节可靠地送到对面"。所以 TCP 应用层都要自己做**消息分帧**(framing):加长度前缀、用换行分隔、用特定结束符。HTTP 用 `\r\n\r\n` 分隔 header,WebSockets 用帧头里的长度字段,protobuf-over-TCP 一般前面加 varint 长度。这一层额外协议,TCP 不会替你做。

更关键的差别在于**可靠性在哪一层做**。这是 09E-1 反复强调的核心点,我们在这里从 syscall 视角再讲一遍,因为它能彻底打通你的理解。

UDP 是"我尽力发,丢就丢"——`sendto` 这个 syscall 返回成功,只意味着内核**把你的字节收下了并排进了发送队列**,完全不意味着对端收到了。UDP 包在网线上丢了、被防火墙挡了、对端接收缓冲区满了被内核静默丢了——你都不会得到任何错误反馈。你的 `sendto` 仍然开开心心地返回 Ok。所以你在 09E-1 自己写的可靠性(序列号、ACK、重传),全是因为 UDP 这个 syscall 什么都不保证,你被迫在应用层补上。

TCP 是"我保证送到"——但这个保证是**内核**做的,不是你的代码做的。你 `send` 一段字节给 TCP socket,**内核的 TCP 栈**会替你做全套:把字节切成 segment、打序列号、发出去、等对方 ACK、丢了重传、乱序了重排、对面慢了就滑动窗口减速。这一切都在**内核里**自动运转,你的应用代码完全看不见、也关不掉。这是 TCP 最大的特点,也是它对游戏最大的麻烦。

为什么"关不掉"是麻烦?因为你 09E-1 学到了游戏需要**逐消息选择**可靠性——位置包不可靠(丢了下一帧覆盖),聊天包可靠。TCP 不给你这个旋钮:它把"可靠性"焊死在**整条连接**上,这条连接上所有数据都享受同样的重传和有序保证。这意味着你哪怕只发一个不重要的位置包,只要它前面有个包丢了,它就得在内核缓冲区里排队等重传完成——这就是 [09E-1](../../phase-9/09E-1-reliable-udp-transport.md) 反复讲的**队头阻塞**(head-of-line blocking)在 syscall 层面的根源:**内核 TCP 状态机**替你做了有序交付,而它根本不知道你的某些数据其实是"过期了可以扔"的。

这就解释了为什么游戏几乎不用 TCP:TCP 在内核里替你做了**完整但僵化**的可靠性,你既享受不到它(位置包你根本不想让它重传),又被它绑架(队头阻塞),还关不掉它(没有 `SO_DONT_RETRANSMIT` 这种选项)。你唯一的出路就是用 UDP——内核给你"光秃秃的发送能力",然后你在应用层(就像 09E-1 那样)自己组装出**正好满足游戏需求**的可靠性。这就是为什么 09E-1 是这一篇的 prerequisite:你必须先理解"用户态自己造可靠性"这件事,才能理解"内核替你造的可靠性为什么不够用"。

## 3 · 阻塞的真相:你的线程为什么会睡着

到这一步,你已经知道 socket 是个 fd,知道 UDP 和 TCP 在 syscall 层面的差别。现在我们直面一个更微妙的问题:**为什么 `recvfrom` 会"卡住"**。

你写过这种代码:`let (n, addr) = socket.recv_from(&mut buf)?;`。如果此刻 socket 的接收缓冲区里没有包,这一行**不会立刻返回**——你的整个线程会**停在这里**,什么都不做,直到有一个包到达(或者对端关闭、或者出错)。这就是"blocking socket"(阻塞 socket)的默认行为。`std::net::UdpSocket` 默认就是阻塞的。

这个"停在这里"不是忙等(busy-wait)——你的线程不是在 while 循环里空转烧 CPU。它真正发生的事情是:**你的线程被内核标记为"睡眠"(sleeping),从运行队列(run queue)里拿掉了**。内核调度器(scheduler)再也不会分配 CPU 时间给它,直到某个事件把它唤醒。这个唤醒事件,对于阻塞的 `recvfrom` 来说,就是"socket 的接收队列里来了新包"——内核的网络中断处理函数收到包,把包塞进 socket 的接收队列,然后顺手把在这个 socket 上等待的线程标记为"可运行"(runnable),下一次调度时它就能继续执行,`recvfrom` 返回。

这一切都是内核替你做的,你的代码看起来就是"调一行,等一会儿,返回了"。这就是阻塞的优雅之处:**代码写起来跟同步思考完全一致**——你"读"一个 socket,跟"读"一个文件一样自然。

但这个优雅有一个致命问题:**一个阻塞的线程,只能等一个 fd**。你 `recv_from` 在 socket A 上睡着,期间 socket B 来包了,你根本不知道,因为你的线程在 A 上挂着。对于单连接的客户端(比如 09E-1 的 P2P demo),这无所谓——你就一个 socket,睡着了等它就行。但对于**服务器**,这是灾难。

想象一个游戏服务器,要同时处理 1000 个玩家的连接。如果你用阻塞 socket + 一连接一线程的模型(thread-per-connection),你需要 1000 个线程,每个线程各自在一个 socket 上 `recvfrom` 睡着。每条连接占一个线程,1000 条占 1000 个线程。每个线程默认栈 8MB,1000 个线程光栈就要 8GB 内存。线程多了,调度器上下文切换(context switch)的开销也会吃掉 CPU。这个模型在小规模下(几十个连接)还行,但撑不住真正的并发。

你需要一种机制,让**一个线程同时监视多个 fd**,哪个 fd 有数据了再去处理它——而不是"一个线程傻等一个 fd"。这就是**多路复用**(I/O multiplexing)。Linux 给你提供了三代多路复用 API:`select` / `poll` / `epoll`。下一节我们从最早的 `select` 讲起,看它是怎么进化的,以及为什么今天大家用的是 `epoll`。

## 4 · 从 select 到 epoll:多路复用的三代进化

多路复用要解决的问题是:**给我一组 fd,告诉我哪些已经"准备好了"**(可读 / 可写 / 出错了),这样我只需要处理那些就绪的 fd,不用为每个 fd 配一个线程傻等。

### 4.1 select 和 poll:O(n) 扫描的老办法

最早的 API 叫 `select`,1983 年随 4.2BSD 发布。它的接口(伪签名)`select(nfds, readfds, writefds, exceptfds, timeout)`:你传一个 fd 集合(bitset),它**阻塞**直到至少一个 fd 就绪,然后返回并**修改**这个集合——把没就绪的位清掉。你扫剩下的位为 1 的就是就绪 fd。

这个模型有两个**结构性**问题。第一,`select` 用固定大小 bitset 表示 fd 集合,默认 1024(`FD_SETSIZE`)——你**最多只能监视 1024 个 fd**,扛 C10K 根本不行。第二,每次调用都要**重新传整个集合进去**,内核每次都**从头扫一遍** O(n),返回后你在用户态**还要再扫一遍**找出就绪的——又是 O(n)。fd 越多越慢,且线性恶化。

`poll`(1986 年 SysV R3)用链表代替 bitset,**没有 1024 硬上限**,但**没解决**核心问题:每次还是要传所有 fd,内核还是要全部扫一遍。在大量空闲连接场景下,跟 `select` 一样低效。

### 4.2 epoll:O(1) 的"通知"模型

Linux 2002 年(2.5.44)引入 `epoll`,核心思想是:**把"注册 fd"和"等事件"这两步分开**。

你先用 `epoll_create1` 创建 epoll 实例(它本身也是 fd)。然后对每个 socket 调一次 `epoll_ctl(epfd, EPOLL_CTL_ADD, sock_fd, &event)`——告诉内核"把这个 socket 加进监视列表,我关心它的可读事件"。这一步**只做一次**:socket 一旦注册就**一直**留在内核里,不需要每次重新注册。

主循环里你只调 `epoll_wait(epfd, &events, max_events, timeout)`,它**阻塞**直到至少一个 fd 就绪,返回**就绪 fd 列表**——不是所有 fd,只是就绪的那些。

关键差别:`epoll` 内部维护**就绪列表**(ready list)。当 socket 上有数据到达,内核**顺便**检查它是否在某个 epoll 实例里——如果是,就**插入就绪列表**,O(1) 操作。`epoll_wait` 醒来直接把这个列表给你,**O(就绪 fd 数)**而不是 O(总 fd 数)。

这意味着监视 10 个还是 10 万个 fd,**只要同时就绪的数差不多**,`epoll_wait` 开销就差不多。这就是 epoll 能扛 C10K 甚至 C10M 的根本原因——性能**不随 fd 总数恶化**,只随**活跃 fd 数**增长。对典型服务器(大量空闲连接,任意时刻少数活跃),epoll 几乎完美。

### 4.3 用 epoll 写一个多 socket UDP 服务器

下面这段 Rust 代码用 `nix` crate 直接调 epoll syscall,实现"一个线程同时处理多个 UDP socket"。教学示例——生产里你不会自己写,会用 tokio 或 mio。但亲手写一遍 epoll,你才能理解 tokio 在底下做了什么。

`Cargo.toml`:`nix = { version = "0.27", features = ["event", "fs"] }`,然后:

```rust
// src/main.rs —— 用 epoll 同时监视多个 UDP socket。
use nix::sys::event::{epoll_create1, epoll_ctl, epoll_wait, EpollEvent, EpollFlags, EpollOp};
use nix::sys::socket::{bind, recvfrom, socket, AddressFamily, SockFlag, SockType, SockAddr};
use std::os::unix::io::AsRawFd;

const PORTS: &[u16] = &[40001, 40002, 40003, 40004]; // 监听 4 个端口

fn main() -> std::io::Result<()> {
    // 1. 创建 epoll 实例(它本身也是个 fd)
    let epfd = epoll_create1(nix::sys::event::EpollCreateFlags::empty())
        .map_err(|e| std::io::Error::other(e.to_string()))?;

    // 2. 为每个端口建 UDP socket、bind、注册到 epoll
    let mut sock_fds = Vec::new();
    for &port in PORTS {
        let fd = socket(AddressFamily::Inet, SockType::Datagram, SockFlag::empty(), None)
            .map_err(|e| std::io::Error::other(e.to_string()))?;
        bind(fd, &SockAddr::new_inet(nix::sys::socket::InetAddr::from_std(
            &format!("0.0.0.0:{}", port).parse().unwrap(),
        ))).map_err(|e| std::io::Error::other(e.to_string()))?;

        // 关键:user_data 塞端口号,epoll_wait 返回时直接读出来知道是哪个端口就绪
        let mut ev = EpollEvent::new(EpollFlags::EPOLLIN, port as u64);
        epoll_ctl(epfd, EpollOp::EpollCtlAdd, fd.as_raw_fd(), &mut ev)
            .map_err(|e| std::io::Error::other(e.to_string()))?;
        sock_fds.push(fd.as_raw_fd());
        println!("[setup] listening on UDP {}", port);
    }

    // 3. 主循环:epoll_wait 等待就绪事件
    let mut events = vec![EpollEvent::empty(); 16];
    let mut buf = [0u8; 2048];
    loop {
        // 阻塞等就绪。timeout = -1 表示永远等。
        let n_ready = match epoll_wait(epfd, &mut events, -1) {
            Ok(n) => n,
            Err(nix::errno::Errno::EINTR) => continue, // 被信号打断,重试
            Err(e) => return Err(std::io::Error::other(e.to_string())),
        };
        // 关键:只遍历就绪的 fd(n_ready 个),不遍历全部注册的 fd
        for i in 0..n_ready {
            let port = events[i].data() as u16;
            let idx = (port - PORTS[0]) as usize;
            // epoll 告诉我们这个 socket 可读,recvfrom 不会阻塞
            match recvfrom::<SockAddr>(unsafe { std::mem::transmute(sock_fds[idx]) }, &mut buf) {
                Ok((n, _)) => println!("[port {}] {}B: {}",
                    port, n, String::from_utf8_lossy(&buf[..n])),
                Err(e) => eprintln!("[port {}] recv err: {}", port, e),
            }
        }
    }
}
```

注意三个关键设计点。

第一,**`EpollEvent` 的 `data` 字段是你自己的"标签"**。内核不关心它是什么,fd 就绪时原样返回。我们塞端口号,拿到 event 立刻知道是哪个端口的 socket——不反向查表。生产代码里一般塞指向"连接对象"的指针(`Box::into_raw` + `as u64`),回调里能 O(1) 拿到完整连接上下文。

第二,**`epoll_wait` 只返回就绪的 fd**。注册了 4 个 socket,但某次返回 `n_ready` 可能只有 1。我们遍历 1 次不是 4 次。注册 1 万个 socket,这个差别就是 1 次 vs 1 万次——这就是 epoll 快在哪。

第三,这段代码**只有一个线程**。它在 epoll 上阻塞,被唤醒,处理就绪 fd,继续 epoll_wait。整个生命周期里这个线程**从不为单个 socket 阻塞**,永远只在 epoll 这一个点上等,而 epoll 一旦唤醒就意味着"有事可做"。这就是事件驱动(event-driven)模型的精髓——**Nginx、Redis、Tokio 全是这个模型**,它们能单线程扛海量连接,核心就是 epoll。

### 4.4 epoll 的两种触发模式:LT vs ET

epoll 还有一个微妙旋钮——**触发模式**(trigger mode),分**水平触发**(level-triggered,LT)和**边缘触发**(edge-triggered,ET)。这一节单独拎出来讲,因为它在代码出 bug 时会变成陷阱。

水平触发(默认)的语义:**只要 fd 上还有未读数据,就一直报"就绪"**。比如接收队列有 10KB,你 `epoll_wait` 出来读 2KB 再 `epoll_wait`——这个 socket **仍然**报为就绪,因为还剩 8KB。LT 好处是**简单**,不怕"漏读",哪怕没读完下次还提醒你;坏处是高吞吐流式 fd 会反复出现在就绪列表里,略浪费。

边缘触发(注册时加 `EPOLLET`)的语义:**只在状态"变化"时通知一次**。socket 收到新数据从不就绪变成就绪,报你一次;之后哪怕没读完也**不会再报**——直到下次又有**新**数据到达。ET 的含义是"你必须一次读光,否则就错过了"。正确写法:被唤醒后在循环里调 `recvfrom` 直到返回 `EAGAIN` / `EWOULDBLOCK`(暂时没数据了),**确保队列读光**。只读一次就回去 `epoll_wait`,队列里还剩数据,下次不会再报——你**丢**了那批数据。

为什么用 ET?减少 `epoll_wait` 返回次数——fd 就绪你一口气干完,内核只通知一次。LT 模式下处理慢的 fd 会反复出现,徒增 wakeup。高吞吐服务器(libevent、Redis 的 IO 线程)倾向 ET。但 ET 写错极易丢数据,**新手用 LT 安全**。

### 4.5 kqueue 和 io_uring:兄弟和下一代

epoll 是 Linux 独有的。BSD 系(macOS、FreeBSD)对应 **kqueue**,1999 年随 4.1-RELEASE 引入,比 epoll 还早三年。kqueue 设计上比 epoll 更优雅——支持多种事件类型(信号、定时器、文件变化、进程状态等),而 epoll 只管 fd。kqueue 用一条 `kevent()` API 干 epoll_ctl 和 epoll_wait 两件事。Tokio 在 macOS 上自动用 kqueue 而不是 epoll——你的代码不用改,运行时帮你切,这就是抽象的力量。

`io_uring` 是 2019 年 Linux 5.1 引入的**真正异步** I/O 接口,syscall 演化的最新一代。epoll 仍是"就绪通知"——它告诉你"fd 可读了",但**读**这个动作你还是要自己发起 syscall 陷入内核。`io_uring` 走得更远:你**预先提交**(submit)一个"读"请求,内核帮你**完成**,完成后通过完成队列(completion queue)通知你"读完了"。整个流程你的线程**可以完全不陷入内核态**——请求和完成都通过共享内存的环形缓冲区(即"uring")传递。它的核心卖点是"省 syscall 自身开销"——一次 syscall 要切用户态↔内核态、保存寄存器、可能刷 TLB,epoll 模型每次 read 都付一次,io_uring 把这些攒一起批量提交均摊。

但对游戏来说 io_uring 还不是主流——epoll + nonblocking read 对游戏网络已经够用,游戏瓶颈在 RTT 和带宽,不在 syscall 次数。tokio 还没把 io_uring 作默认后端(虽然 tokio-uring 独立 crate 存在)。这一节只是让你**知道** io_uring 的存在和它解决什么问题,你日常游戏网络代码大概率还是 epoll。但趋势往 io_uring 走——尤其高性能服务(QUIC、CDN、数据库)已是标配。

[async-io-and-streaming](async-io-and-streaming.md) 是这一节的兄弟篇,它讲 epoll 的另一面——把它用在文件 I/O 和管道 I/O 上,以及它怎么演变成 tokio 那套 async/await 语法。读完你会看到 epoll 是比"网络"更通用的机制:它能监视任何 fd,所以也监视管道、eventfd、timerfd、signalfd。这一篇只聚焦 socket 上讲透,你掌握的 epoll 知识可以直接迁移。

## 5 · 内核网络栈:你的包从 send_to 到网线的旅程

到这里你已经掌握了 socket 和 epoll 这两层。最后这一节我们退一步,看一个更宏大的图景:**你的 `send_to` 调用之后,数据是怎么真的跑到网线上的**。这一节不教你写代码,它教你**理解全貌**——这样你以后用 tcpdump、ss、ethtool 这些工具诊断问题时,知道它们看到的"是协议栈的哪一层"。

### 5.1 发送方向:从应用层到网卡

当你在用户态调 `sendto(fd, buf, ..., dst_addr)`,执行流是这样的:

首先,libc 包装把 syscall 号和参数塞进寄存器,执行 `syscall` 指令,CPU 切换到内核态,跳到内核里 `sys_sendto` 这个处理函数。内核拿到 fd,在当前进程的 fd 表里找到对应的 socket 对象。fd 只是个数字,真正干活的是这个 socket 结构体(里面藏着协议类型、绑定地址、发送/接收队列等等)。

然后内核进入 **UDP 协议层**。它检查你传的目标地址,如果目标在本地路由表里查得到(内核查 `route` 表),就构造一个 **UDP datagram**:加一个 8 字节的 UDP 头(源端口、目标端口、长度、校验和)。UDP 头本身只有这 8 个字节,所以 UDP 是个极其薄的协议——内核几乎没有"状态",发完就忘。

接下来是 **IP 层**。UDP datagram 被塞进一个 IP 包,加 20 字节(或 40 字节,IPv6)的 IP 头。IP 头里有源 IP、目标 IP、TTL(每过一个路由器 -1,防止包永久游荡)、协议号(17 = UDP,6 = TCP)等。如果目标 IP 是本机(127.x 或同子网),走 loopback 路径(直接塞到对端 socket 的接收队列,不真上网卡);如果目标在远端,IP 层通过 ARP 找到下一跳的 MAC 地址(IP → MAC 的翻译,详见 [phase-0/23-network-foundation](../../phase-0/23-network-foundation.md))。

然后是**链路层**。IP 包被塞进一个 Ethernet frame(或者 WiFi 帧),加上目标 MAC、源 MAC、类型字段。这个 frame 被内核**通过网卡驱动**(NIC driver)交给网卡。网卡硬件负责把数字信号编码成电信号(有线)或无线电波(WiFi)发出去。

到这里你的 `sendto` 才真正返回——它实际上比"内核把字节排进发送队列"还要再深一层。但对你应用层代码来说,看到的就是"调一行,过一会儿对面收到了"。这中间几十微秒(本机)到几十毫秒(跨洋)的工作,**全是内核 + 网卡硬件 + 中间无数路由器**替你做的。

### 5.2 接收方向:从网卡到你的 recv_from

反过来,当一个 UDP 包到达你的网卡,流程是这样的:

网卡硬件收到帧,通过 **DMA**(直接内存访问,Direct Memory Access)把帧数据写进内核预分配的环形缓冲区(ring buffer,网卡和内核之间的"信箱")。然后网卡向 CPU 发一个**硬件中断**(interrupt)。CPU 收到中断,暂停当前正在跑的任何代码,跳到内核的**中断处理函数**(interrupt handler)——这是网络栈的"门口"。

中断处理函数做最少的事(因为中断里不能干重活,要尽快返回让 CPU 干别的):把数据包从网卡的 ring buffer 拷出来,塞进内核网络栈的接收队列,然后**软中断**(softirq,也叫"下半部",bottom half)异步处理。软中断里,内核把 frame 一层层剥:链路层剥 Ethernet 头看类型(0x0800 = IPv4)→ 交给 IP 层;IP 层剥 IP 头看协议号(17 = UDP)→ 交给 UDP 层;UDP 层剥 UDP 头,看目标端口,找到绑定在这个端口上的那个 socket(内核里有个哈希表,以端口号为 key),把 datagram 塞进这个 socket 的**接收队列**(receive buffer)。

塞进接收队列之后,关键一步:**如果这个 socket 上有正在 `recvfrom` 阻塞的线程,或者注册在 epoll 里,epoll 会把它加进就绪列表**——这一步触发了第 3、4 节讲的"唤醒"。被唤醒的线程(或者下次 epoll_wait 的线程)继续执行,内核把 datagram 拷到用户态传进来的 `buf` 里,syscall 返回。这就是你 `recv_from(&mut buf)` 拿到数据的全过程。

### 5.3 这个全貌对 debug 的意义

为什么这一节重要?因为它告诉你**每个诊断工具看到的是哪一层**,从而让你出 bug 时知道去哪里看。

**tcpdump / wireshark** 抓的是**链路层或 IP 层**的包——也就是说,它在内核协议栈**进 socket 接收队列之前**拦截。所以 tcpdump 看到一个包,意味着这个包**已经到了你的机器**;但它能不能被你的应用 `recvfrom` 读到,取决于 socket 的接收队列有没有满、有没有别的进程先读了等等。这是一个非常重要的诊断原则:**tcpdump 看到包但应用没收到 = 不是网络问题,是应用或内核 socket 缓冲的问题**(应用读太慢,缓冲区满了,内核开始静默丢包)。

反过来,**应用收不到包 + tcpdump 也看不到 = 真的是网络问题**(防火墙、路由、对端没发)。这两个状态用 tcpdump 一抓就能区分,这是它最核心的价值。

**ss / netstat** 看的是 **socket 层**——它读 `/proc/net/udp`、`/proc/net/tcp` 这些内核导出的伪文件,告诉你当前有哪些 socket、各自的状态(LISTEN / ESTABLISHED / TIME_WAIT)、各自的接收/发送队列里有多少字节未读。`ss -una` 列所有 UDP socket,你能看到你那个 socket 在不在、绑了哪个端口、队列里堆了多少数据。如果队列满了(`Recv-q` 接近 `net.core.rmem_max`),说明你的应用读得太慢——内核开始丢包了,你的 `recvfrom` 速度跟不上入包速度。

**strace** 看的是**应用和内核的边界**——它用 `ptrace` 系统调用拦截你程序里每一次 syscall,打印出来。`strace -e network ./your_game` 会打印所有的 socket / sendto / recvfrom / epoll_wait 调用,包括参数和返回值。如果应用层"看起来"发包了但实际没出去,你看 strace 里 `sendto` 到底返回了什么——返回 -1 是错误,返回的字节数应该等于你传进去的长度。**strace 是把你"以为在干的事"和"实际在干的事"对齐的工具**。

**ethtool / ip -s link** 看的是**网卡硬件层**——丢包统计、ring buffer 大小、链路速度。如果网卡硬件在物理层就丢包(比如 WiFi 信号差导致 CRC 错误),它在 ethtool 的统计里有反映,这种丢包应用层根本看不到。

理解这四层工具各自看哪一层,你就拥有了从硬件到应用的全栈诊断能力。这也是这一篇的最终目的——不是让你手写 syscall,是让你在出问题的时候**知道去看哪一层**。

## 6 · 在你 HH 项目里动手(做中学红线)

理论讲透了,现在轮到你自己上手,在你 09E-1 写的可靠 UDP 代码上做这些事。这一节的每一步都极其值得做——它会让你亲眼看到你写的 Rust 代码和内核网络栈的接口,这种"打通抽象层"的体验,纯读代码出不来。

### 第一步:用 strace 看 09E-1 的实际 syscall

把你 09E-1 那个 mini-reliable-udp 项目 build 好,跑起来一个端点(那个 `./target/release/mini-reliable-udp 40001 127.0.0.1 40002`)。然后在另一个终端,用 strace 跟踪它所有的网络相关 syscall:

```bash
# 找到你的进程 pid
pgrep -f mini-reliable-udp

# 用 strace 跟踪它的网络 syscall
# -p <pid>:attach 到一个已经在跑的进程
# -e trace=network:只看网络相关调用(socket / bind / sendto / recvfrom / setsockopt ...)
sudo strace -p $(pgrep -f "40001") -e trace=network -yy -tt 2>&1 | head -40
```

你应该看到类似这样的输出:

```
12:34:56.789012 socket(AF_INET, SOCK_DGRAM|SOCK_CLOEXEC, IPPROTO_UDP) = 3
12:34:56.789045 bind(3<UDP:[12345]>, {sa_family=AF_INET, sin_port=htons(40001), sin_addr=inet_addr("0.0.0.0")}, 16) = 0
12:34:56.789123 setsockopt(3<UDP:[12345]>, SOL_SOCKET, SO_REUSEADDR, [1], 4) = 0
12:34:56.789456 setsockopt(3<UDP:[12345]>, SOL_SOCKET, SO_RCVBUF, [212992], 4) = 0
12:34:56.790111 sendto(3<UDP:[12345]>, 0x7ffe... , 56, 0, {sa_family=AF_INET, sin_port=htons(40002), ...}, 16) = 56
12:34:56.790234 recvfrom(3<UDP:[12345]>, 0x7ffe..., 2048, 0, NULL, NULL) = 48
12:34:56.791002 sendto(3<UDP:[12345]>, ..., 56, 0, ..., 16) = 56
...
```

逐行解读。

第一行 `socket(AF_INET, SOCK_DGRAM|SOCK_CLOEXEC, IPPROTO_UDP) = 3`。`AF_INET` 是 IPv4 协议族,`SOCK_DGRAM` 是 UDP(datagram),`SOCK_CLOEXEC` 表示"进程 exec 时自动关 fd"(防 fd 泄露给子进程的安全习惯)。返回 3 是分配的 fd 编号——这就是 §1 讲的"socket 就是个 fd"。`-yy` flag 让 strace 把 fd 翻译成可读形式(`<UDP:[12345]>`),能看到类型和 inode。

第二行 `bind(3, ..., htons(40001), ..., inet_addr("0.0.0.0"))`。fd 3 绑到 `0.0.0.0:40001`——`0.0.0.0` 是所有网卡(INADDR_ANY),`htons` 是 host-to-network-short 字节序转换(网络字节序大端,x86 小端,要翻一下)。

接下来 `setsockopt` 设 socket 选项:`SO_REUSEADDR` 让你 bind 到刚关闭还 TIME_WAIT 的端口(server 重启必备),`SO_RCVBUF` 设接收缓冲区大小(Linux 默认 212992 字节 ≈ 208KB)。

后面就是数据收发:`sendto(fd, buf, len, flags, dst_addr, ...) = len` 发出 len 字节;`recvfrom(fd, buf, len, ..., src_addr, ...) = n` 收到 n 字节。这就是你 09E-1 写的可靠 UDP 在 syscall 层面的真实样子——一个 `sendto`、一个 `recvfrom`,中间是内核替你干的活。**自己跑一次,把这 40 行 strace 截下来标注每个 syscall 语义**——你对"send_to 真的只是个 syscall"就从抽象变具象了。

### 第二步:用 tcpdump 抓你 09E-1 的实际包

strace 看 syscall 边界。tcpdump 看协议栈内部——链路层往上一层。开一个终端跑 tcpdump,另一个跑你的 09E-1:

```bash
# 抓 loopback 上 UDP 40001/40002 的包
sudo tcpdump -i lo -n udp port 40001 or udp port 40002 -X -tttt
```

参数:`-i lo` 监听 loopback 接口(本机两进程通信走的虚拟网卡,IP 127.0.0.1);`-n` 不解析 DNS;`udp port 40001 or udp port 40002` 是 BPF(Berkeley Packet Filter)表达式;`-X` 打印 hex dump;`-tttt` 完整时间戳。

跑起来你会看到一连串的包滚过:

```
12:34:56.789012 IP 127.0.0.1.40001 > 127.0.0.1.40002: UDP, length 56
    0x0000:  4500 0050 0001 4000 4011 0000 7f00 0001  E..P..@.@.......
    0x0010:  7f00 0001 9c41 9c42 003c fe30 .........A.B.<.0
    0x0020:  <你 bincode 序列化的包头 + payload>
```

第一行是人类可读摘要。下面 hex dump 是这个包的逐字节——**你能读出 IP 头和 UDP 头**:`4500` 是 IP 头(version=4, IHL=5, TOS=0),`0050` 是 IP 总长度,`4011` 是 TTL=64 + 协议号=17(UDP),源/目标 IP `7f00 0001` = 127.0.0.1,`9c41` = 40001 源端口,`9c42` = 40002 目标端口,`003c` = 60 是 UDP 长度(含 8 字节头),`fe30` 是校验和。**你 09E-1 写的 bincode 序列化内容,紧跟在这 28 字节 IP+UDP 头后面**——你能在 tcpdump 输出里**直接看到**应用层代码生成的字节。

一个有意思的现象:**`tc netem` 开丢包之后,tcpdump 里看不到"丢包"这件事**——丢包是内核模拟的,模拟发生在哪层你看不出来,但从 tcpdump 视角你 sendto 的包都"正常"出现在 lo 接口上,只是对端 recvfrom 没收到。这种"发出去了对面没收到"的差异化视角,正是 tcpdump 帮你看清内核哪一层在干什么。wireshark(`sudo wireshark` 选 lo 接口)UI 上字段解析更直观,生产环境 debug 协议是利器。

### 第三步:用 ss 看你的 socket

ss(socket statistics)是 iproute2 套件一员,新版 netstat(老 netstat 已 deprecated)。它读 `/proc/net/udp` / `/proc/net/tcp` 内核导出文件,告诉你当前所有 socket 状态。

```bash
# 看所有 UDP socket(-u UDP, -n 不解析端口名, -a 所有含 UNCONN)
ss -una
# State   Recv-Q Send-Q Local Address:Port  Peer Address:Port  Process
# UNCONN  0      0      0.0.0.0:40001       0.0.0.0:*          users:(("mini-reliable-udp",pid=12345,fd=3))
```

UDP socket 的 State 永远 `UNCONN`(无连接)。`Recv-Q` 是接收队列未读字节数——**这个值 > 0 且持续增长,说明应用读太慢**,内核在 socket 层排队。如果 Recv-Q 涨到 `rmem_max`(默认 ~208KB),内核就**静默丢弃**新到包(UDP 没流控,缓冲满直接扔)——这种丢包 tcpdump 都看不到(包到内核了,但没排进队列)。

试个实验:在你 09E-1 程序里临时改成"收到包先 sleep 1 秒"(模拟处理慢),另一端疯狂发包。`watch -n 0.5 'ss -una | grep 40001'` 持续刷新,看 Recv-Q 涨到某值不再涨(开始丢包)。这就是"应用层慢导致内核丢包"——你 09E-1 的 `poll_incoming` 必须**循环**读光所有 pending 包再返回,就是为避免这种情况。加 `-e` flag(`ss -una -e`)看 inode、内存、UID 等更多细节。

### 第四步:写一个 epoll 多 socket UDP 监听器

不依赖 tokio,直接用 epoll syscall 写一个能同时监听 4 个 UDP socket 的程序。基于 §4.3 给的代码骨架跑起来,用 `nc -u 127.0.0.1 40001` 等 4 个终端分别往 4 个端口发数据,看 epoll 怎么被唤醒、怎么知道是哪个端口收到包。

如果 §4.3 代码因 nix 版本差异编译不过,装老版本:`cargo add nix@0.27 --features event,fs`。或用 libc crate 手写 syscall:

```rust
use libc::{epoll_create1, epoll_ctl, epoll_event, EPOLLIN, O_CLOEXEC};
let epfd = unsafe { epoll_create1(O_CLOEXEC) };
let mut ev = epoll_event { events: EPOLLIN as u32, u64: port as u64 };
unsafe { epoll_ctl(epfd, 1 /*EPOLL_CTL_ADD*/, sock_fd, &mut ev); }
```

跑通后挂 strace:`sudo strace -p $(pgrep epoll-udp) -e trace=epoll_wait,epoll_ctl,recvfrom -tt`。你会看到 epoll 的真实节奏——程序大部分时间在 `epoll_wait` 阻塞,某 socket 收到包立刻唤醒,处理完再回 epoll_wait。这个"睡眠-唤醒-处理"循环就是所有事件驱动服务器的脉搏。把这一步做出来,你就**亲手用过了 epoll syscall**——以后写 `tokio::net::UdpSocket::recv_from().await` 时,你心里知道底层在干什么,你的"async"其实是 epoll 上的一次 wait。

### 第五步:把这层理解用在 HH 项目上

把这些工具内化进 HH 工作流。当你 09E-1 集成进 HH 后(09E-1 §9 第三步的"双人位置同步"),开一个常驻 strace 窗口:`sudo strace -p $(pgrep handmade_hero) -e trace=network -tt -s 256 > ~/hh-net.log 2>&1`,出问题时 grep 它。`ss -una | grep <端口>` 做成 dev 脚本。如果出"对面没收到我的包"的 bug,**先 tcpdump,再 strace,再 ss**——tcpdump 看不到包 = 网络层问题;tcpdump 看到包但应用没 recvfrom = socket 层问题;recvfrom 了但应用没处理 = 应用层 bug。这三步定位 99% 网络问题。

这就是做中学红线——不亲手跑一遍 strace / tcpdump / ss + epoll,这些工具对你永远是"听过名字"。跑一遍后变成肌肉记忆,你以后看任何网络代码都能立刻知道"问题在哪一层"。

## 7 · 练习

练习一,Lv1,概念辨析。有人问你:"既然 epoll 比 select 强这么多,为什么 select 还存在,而且 std 库的 `std::net::TcpListener::accept` 默认是阻塞的?"想清楚两个点。第一,select 存在是因为**兼容性**——它在所有 Unix 系统上都有,而 epoll 是 Linux 独有的(虽然 BSD 有 kqueue),写跨平台代码的库(如旧版 libevent)会优先用最通用的 API。第二,`std::net` 默认阻塞是因为它**故意简单**——教学场景和简单场景下阻塞 API 最直观。生产环境要并发,你应该用 tokio(它在 Linux 上自动用 epoll)。能把这两点说清楚,你就理解了 API 演化背后的兼容性和易用性权衡。

练习二,Lv2,动手实践。完成 §6 的全部五步——strace 看 09E-1、tcpdump 抓 09E-1 的包、ss 看 socket 状态、跑通 epoll 多 socket demo、把工具链集成进 HH。把你 strace 输出的前 40 行截图、tcpdump 抓到的某个完整 UDP 包的 hex dump 标注(IP 头每个字段、UDP 头每个字段)、ss 输出的 Recv-Q 解读,整理成一份简短的实验报告(可以是个 commit message 或 PR 描述)。这种"动手并记录"的习惯,是工程师区别于"只看书的人"的核心素质。

练习三,Lv3,理解 epoll 的边缘触发陷阱。把 §4.3 的 epoll demo 改成边缘触发模式(注册时加 `EPOLLET` flag),然后故意在收到事件后**只读一次**(不循环读到 EAGAIN)。用 `nc -u 127.0.0.1 <port>` 一次发多个包(比如用 `printf` 拼一段长字符串 + 多次发送),观察你的程序**漏掉**了哪些包。然后改成正确写法——`loop { recvfrom -> 如果返回 EAGAIN 就 break }`——验证不再丢包。把"为什么边缘触发必须读到 EAGAIN"这个原则用自己的话写下来。这个练习让你亲身体验 §4.4 讲的 LT vs ET 差别,这一差别写成 bug 极其隐蔽,亲手踩一次就长记性了。

练习四,Lv4,源码深读。tokio 是 Rust 异步生态的核心,它底层的 mio crate 直接封装 epoll。`gh repo clone tokio-rs/mio`,找到 `mio/src/sys/unix/selector/epoll.rs`(路径可能因版本略有不同)。读 `epoll_create`、`epoll_register`、`epoll_wait` 三个函数的实现——它们就是 nix / libc 调用的薄包装。然后看 mio 怎么把 epoll 事件接到 tokio 的 `Future` 上(找 `Waker`、`Registration` 这些类型)。把这个链条——`tokio::net::UdpSocket::recv_from().await` → tokio runtime → mio → epoll_wait → 内核——画一张图,标注每一步的代码位置和职责。这种"从抽象到底层的全链路追踪",是成为高级系统工程师的必备能力。如果你能找到 mio 里处理 ET / LT 模式的代码并解释它的选择,那是 bonus。

## 8 · 延伸阅读

这一篇讲的是 syscall 层细节。man page 是你最好的朋友——`man 2 socket`、`man 2 sendto`、`man 2 recvfrom`、`man 2 epoll_create`、`man 2 epoll_wait`、`man 7 udp`、`man 7 tcp`。第 2 节是 syscall,第 7 节是协议总览,这两个 section 是查网络 syscall 细节的首选。

书方面,W. Richard Stevens 的《UNIX Network Programming》(UNP,卷一)是 socket 编程的圣经,年代久远但讲的是 API 语义,历久弥新。同一作者的《Advanced Programming in the UNIX Environment》(APUE)对"fd 是什么"有更深展开。Brendan Gregg 的《BPF Performance Tools》讲怎么用 eBPF 在内核里 trace 网络栈——你 tcpdump 看不到的层(软中断处理),eBPF 能看到,这是 §5 的"更深处"。

线上,Julia Evans 的博客(`https://jvns.ca/`)有大量 epoll、networking 的图解博文,擅长把复杂的内核机制画成直观的卡通图。Linux 内核源码里 `net/ipv4/udp.c` 是 UDP 协议层实现——你 §5 读到的"sendto 怎么走完内核网络栈",对应的代码就在 `udp_sendmsg` 函数里,你能看到 09E-1 调的那个 syscall 在内核里到底干了什么。`Documentation/networking/` 对每个子系统有总览。io_uring 方面,Jens Axboe(io_uring 作者)的官网 `https://unixism.net/loti/` 是最权威教程,先读 `what_is_io_uring.html` 弄清 io_uring 跟 epoll 设计哲学的根本差别;`tokio-uring`、`quinn` 这些用 io_uring / QUIC 的开源项目代码值得读。

本仓库内的相关内容:

- [09E-1-reliable-udp-transport](../../phase-9/09E-1-reliable-udp-transport.md) 是这一篇的直接上游——它讲你在**用户态**怎么用 `std::net::UdpSocket` 自建可靠性,这一篇讲那个 `UdpSocket` **底下**是什么。读完 09E-1 再读这一篇,你就从应用层一路打通到内核。
- [phase-0/23-network-foundation](../../phase-0/23-network-foundation.md) 是网络基础——OSI 七层、TCP 三次握手、UDP 协议格式、NAT 穿透这些"宏观"知识。这一篇假设你已懂那一篇,往下钻到 syscall 层。对 `AF_INET` / `SOCK_DGRAM` / `127.0.0.1` 这些词还不熟,先回去补那一篇。
- [09E-2-authoritative-server-and-state-sync](../../phase-9/09E-2-authoritative-server-and-state-sync.md) 讲服务器权威架构,它跑在 09E-1 的可靠 UDP 之上,而 09E-1 跑在这一篇讲的 syscall 之上。
- [network-multiplayer-models](../../phase-5/deep-dives/network-multiplayer-models.md) 讲 lockstep / state sync / rollback 这些用可靠 UDP 的更高层模型,跟这一篇形成"高层模型 → 用户态可靠性 → syscall 底层"的完整垂直切片。
- [async-io-and-streaming](async-io-and-streaming.md) 是这一篇的兄弟——讲 epoll 的**另一面**,即把 epoll 用在文件 I/O、管道、eventfd 等非 socket fd 上,以及 epoll 怎么演变成 tokio 的 async/await。两篇合起来,你对 epoll 这个 Linux 异步 I/O 的基石就有完整理解。
