
# 9E-1 · 可靠 UDP 传输

## 0 · 你给游戏加了 TCP,然后玩家说"卡得像放幻灯片"

你跟完了 HH 单机版,决定往上叠联机。第一直觉是:用 TCP。原因听起来天经地义——TCP 是"可靠的"传输,数据保证送到、保证按序,而且 sockets API 用起来无比友好,`TcpStream::connect`、`write`、`read`,跟读写文件一样,文档铺天盖地。你写下第一版联机代码,发出去,自己测了测,本地 loopback 一切丝滑。你 ship 了。

三天后玩家的反馈来了:"按跳之后半秒才跳起来。""游戏会突然卡住两秒然后瞬移。""别人的角色走着走着就定住,过一会儿又突然飞到新位置。"你打开自己的日志,看 RTT 曲线,发现一个奇怪的现象:大多数时候 RTT 是 30ms,但每隔十几秒会突然蹿到 800ms 甚至 1.5 秒,然后回落。你抓包,看到的是 TCP 在重传,然后拥塞控制把发送窗口砍到零。

你遇到的,是 TCP 一个被设计到骨头里的特性,叫做**队头阻塞**(head-of-line blocking)。这是 TCP 给你"可靠 + 有序"承诺的代价,而游戏恰恰是这个代价无法承受的场景。这一篇要讲的是:为什么游戏几乎不用 TCP,为什么大家改用 UDP 然后在它上面**自己**搭建刚好够用的可靠性,以及怎么从零写出这样一层可靠 UDP,在你 HH 项目里跑通,成为 09E-2 服务器权威架构的地基。

## 1 · TCP 为什么是游戏的天敌:队头阻塞,以及那该死的有序承诺

要把 TCP 为什么不行讲透,得先看一眼它内部是怎么实现"可靠有序"的。TCP 把你写给 `TcpStream` 的字节流切成一段一段的 segment,每段打上一个**序列号**(sequence number),发出去,然后等对方回 ACK。如果某一段在网络上丢了,TCP 不会假装没事——它会**停在那里**,把丢失的那段重传,等对方确认收到,**才继续往下送后面的数据**,哪怕后面的数据其实早就已经完整地躺在接收方的缓冲区里。

这就是队头阻塞的字面意思:队头那个包(最早发出去、丢了的那一段)堵住了整条队列。后面所有数据,不管自己有没有丢,都得排队等它。你可以把它想成一条单车道隧道:最前面那辆车抛锚了,后面哪怕有十辆完好无损的法拉利,也只能一起堵着,直到拖车把抛锚那辆拖走。TCP 之所以这么设计,是因为它要服务的对象是 **byte stream**——telnet、HTTP、文件下载——这些场景里,顺序就是一切,中间跳过一段,后面全部错位,毫无意义。所以 TCP 干脆把"有序"做成不可妥协的硬约束:宁可全部等,也不能乱序。

对游戏来说这个权衡是灾难性的。原因在于,游戏同时有两类数据在网上跑,它们对"可靠"和"有序"的需求是**矛盾**的。第一类是登录包、聊天消息、技能升级这种——丢了不行,顺序乱了也不行,玩家发"hello"总不能到对方那边变成"olleh",这类数据需要可靠 + 有序。第二类是每帧的玩家位置快照——这一帧玩家在 (100, 200),下一帧在 (102, 200),**最新**的那一帧才是玩家想看到的,**旧**的那一帧哪怕丢了也无所谓,反正下一帧马上来覆盖。如果你非要把这一类也搞成可靠有序,会出现什么?某帧的位置包丢了,TCP 停下来重传它,所有**更新**的位置包全卡在它后面排队等,等那个旧包重传成功送达的时候,它已经是几百年前的过期数据了,玩家屏幕上的角色在这段时间里一动不动,然后"啪"一下瞬移到旧位置,接着瞬间又被挤到新位置——这就是玩家说的"卡住、定住、瞬移"。

更糟的是 TCP 的**拥塞控制**。TCP 一旦判定丢包(它把丢包当作"网络拥塞"的信号),会激进地把自己的发送窗口减半,甚至减到 1,然后用一种叫 slow-start 的算法慢慢爬回来。这个机制是为了让互联网上的数百万条 TCP 连接公平共享带宽,设计得非常优美——但对一条游戏连接来说,窗口减半意味着你这一帧该发的输入可能根本发不出去,要等好几个 RTT 爬坡才能恢复。你看到的那个 800ms 的 RTT 蹿升,大概率就是 TCP 在做拥塞退避。

还有一个藏得比较深但同样致命的问题:Nagle 算法。TCP 默认会**攒**你的小包,攒到一定大小或等收到上一个包的 ACK 才发出去,目的是减少网络上碎小包的数量。对 HTTP 这种流式请求是好事,对游戏是地狱——你那 2 字节的玩家输入,TCP 给你压了 200 毫秒才发,玩家按跳之后 200 毫秒才跳,这游戏没法玩。你能关掉它(`TCP_NODELAY`),但关掉之后 TCP 又会因为每个小包都立刻发而频繁触发 ACK,效率反而下降。你怎么调都不对。

综合起来:**TCP 把可靠、有序、拥塞控制、攒包,全焊死在一起,你只能要么全要、要么全不要。游戏要的是"我每条消息自己决定要不要可靠、要不要有序、要不要攒",TCP 给不了。** 这就是为什么几乎所有严肃的实时游戏都不用 TCP。Glenn Fiedler 在他《Networking for Game Programmers》系列里把这一点讲得非常直接,这一篇的 calibration 就是顺着他的思路走的。

## 2 · 为什么是 UDP,以及"在 UDP 上自己造可靠性"这个反直觉的选择

UDP 的本质就一句话:你 `send_to` 一个 byte 数组,网络尽力帮你送到对方那个地址,**送到了不告诉你,没送到也不告诉你,顺序乱了不管,重复了不管,你也不需要先"连接"**。听起来像是个坑——什么保证都不给,这能用吗?

换个角度想:UDP 给你的不是"坑",而是**一块干净的地基**。TCP 之所以让你痛苦,是因为它把一堆你其实不想要的行为(强制有序、强制拥塞退避、强制攒包)焊死在了"可靠"这件事上。UDP 把所有这些行为都剥掉,只给你一个最薄的"把字节扔到网上"的能力。然后,你需要哪些行为,**你自己挑着往上加**——这条消息我要它可靠,那就给它打号、收 ACK、丢了重传;这条消息我不在乎丢不丢,那就直接发出去不管。这种**逐消息选择**的能力,是游戏对网络层最核心的需求,而 UDP 是唯一能给你这个能力的传输层。

这个选择乍听起来反直觉——TCP 都替你做好了,我为什么还要自己写?答案就在上一段:TCP 的"做好"是**一刀切**的,它没有 per-message 的旋钮。你自己写在 UDP 上的可靠性,可以精细到每一条消息:聊天消息走可靠有序通道,玩家位置走不可靠通道(只关心最新值),语音走不可靠无序通道(旧帧丢了就丢了,新帧才有价值)。TCP 给你的只有"全部可靠有序"这一个通道,而且做得还不一定符合游戏需求。

这个反直觉的选择,本质上是把"传输层"从 TCP 那种"打包好的成品",降级回 UDP 这种"原料",然后在应用层重新组装出**恰好满足游戏需求**的成品。听起来是更多工作量,确实也是——但这份工作量换来的是对网络行为的精确控制,而精确控制网络行为是低延迟联机的命门。这也是为什么 Glenn Fiedler、GGPO 的 Tony Cannon、Quake 的网络代码,无一例外都走 UDP + 自建可靠性这条路。

接下来这一篇,就是带你一步步把这份"自建"做出来。我们会从一个光秃秃的 UDP socket 开始,依次往上加四块东西:**序列号**(让接收方知道缺了什么)、**ACK 机制**(让发送方知道什么到了)、**重传**(让发送方补上丢失的)、**滑动窗口**(让发送方别发太快淹死接收方)。每一块都是被迫加的——上一块不够用,所以加下一块,你会清楚地看到每一块在解决什么具体问题。

## 3 · 序列号:让接收方知道缺了哪一帧

先回到那个光秃秃的 UDP socket。假设你已经能 `send_to` 和 `recv_from` 了(具体代码下一节给,这里先建概念)。你每帧把玩家的位置打成一个 byte 数组发出去。问题来了:接收方收到一个包,它**完全不知道**这是哪一帧的——UDP 包头里没有"这是第几个包"的信息,UDP 把它当成一段无意义的字节。

你需要给每个包打一个号。最简单的做法,是在每个包的最前面加一个 `u16` 或 `u32` 整数,叫**序列号**(sequence number)。第一个包序列号是 0,第二个是 1,以此类推,发送方每发一个包就 +1。这个号每发一个包就涨,永远不回退(或者回绕到 0,这是另一个话题,先不管)。

加了序列号之后,接收方就能做一件之前做不了的事:**检测丢包**。假设接收方刚收到序列号 100 的包,下一个收到的是 103——那 101 和 102 这两个包要么还在路上,要么已经丢了。注意,这时候**还不能**判定它们一定丢了——可能只是乱序,103 比 101 先到(UDP 不保证顺序,这种事经常发生)。所以序列号本身只是"让我看见缺口"的能力,看见缺口之后判定"丢了"还要更复杂(下一节讲)。但至少,你有了**感知**丢失的能力。

序列号还有第二个用途:**去重**。UDP 在极端情况下会重复投递同一个包(比如应用层重传 + 原包都到了),接收方拿到两个序列号 100 的包,得知道这是同一个包出现了两次,而不是两个不同的包。靠序列号一比就知道了。

第三个用途:**拒绝过期数据**。如果你做的是位置快照(每帧发一次玩家位置),接收方维护一个"我见过的最大序列号",任何一个序列号小于等于这个最大值的包,直接扔掉——因为它是过期的,我手里已经有更新的了。这就是不可靠通道的核心机制:**只关心最新值,旧的来了就丢**。

序列号用 `u16` 还是 `u32`?`u16` 最多 65535,60 帧每秒的话大约 18 分钟回绕一次,处理回绕的代码不复杂(只要确认窗口小于 65535/2 就行),省 2 字节。`u32` 大约两年才回绕一次,实际不用操心回绕,多花 2 字节带宽。对每帧的位置包,2 字节累加起来不可忽略(60Hz × 2 字节 = 120 字节/秒 × N 玩家),所以**不可靠通道**常用 `u16`;**可靠通道**因为要长期跟踪 ACK 状态,常用 `u32` 省心。renet、ENet 这些库都是这么折中的。

序列号讲到这里,你应该感觉到 UDP 上可靠性最早的一块砖已经铺好——**接收方现在能看见自己缺了什么**。但光看见不够,接收方还得把这个"我缺什么 / 我收到了什么"的信息**告诉发送方**,这就是 ACK。

## 4 · ACK:让发送方知道什么到了、什么没到

发送方要把丢失的包重传,前提是它得**知道**哪个包丢了。但 UDP 不告诉它。唯一的办法是让接收方主动汇报"我都收到了哪些序列号",这个汇报本身就是一个新的包,叫 **ACK**(acknowledgment)。

最朴素的 ACK 设计,是接收方每收到一个序列号 N 的包,就发回一个 ACK 包,里面写着"我收到了 N"。发送方收到这个 ACK,就把 N 从自己的"待确认"列表里划掉。这听起来已经够用了,但有几个工程细节让这件事比想象的微妙。

第一个细节,**别为每个包单独 ACK**。如果你 60Hz 发包,接收方也 60Hz 回 ACK,网络上的包数量翻倍,而且每个 ACK 自己也可能丢——ACK 丢了你就误以为数据包丢了,触发不必要的重传。工业做法是 **piggyback**(捎带)和 **批量 ACK**:接收方维护一个"最近收到的最大连续序列号",把这个号塞进自己**本来就要发回去的**数据包的包头里(因为游戏连接是双向的,双方都在互发包,所以一定有"本来就要发的包"可以搭车)。如果暂时没有要发的包,就**定时**(比如每 30ms)专门发一个纯 ACK 包。这样一个 ACK 包能确认一大批序列号,效率高得多。

第二个细节更巧妙,叫 **ack bitfield**(ACK 位图)。你不仅要告诉对方"我收到了序列号 100",你还得告诉他"序列号 101 我没收到、102 收到了、103 收到了、104 没收到……"——因为你收到的包可能是不连续的。把每个序列号对应到一个 bit,1 表示收到、0 表示没收到,这样一个 32 位的 bitfield 就能紧凑地描述"以最大序列号 N 为基准,往前 32 个包里哪些收到了、哪些没收到"。Quake 3 的网络协议就是用这种 bitfield 的,renet 也用。下面我们写代码的时候会照这个思路实现。

第三个细节是关于"何时判定一个包真的丢了"。光看 ACK 位图上某个 bit 是 0,你**不能**立刻判定那个包丢了——它可能只是延迟了,晚点会到。判丢的依据是**时间**:发送方记录每个发出去的包的时间戳,如果一个包在某个**超时阈值**(比如 RTT 的 2-3 倍)内还没被 ACK,就**判定**它丢了,触发重传。这个阈值的选择是个权衡:太短,容易把"还在路上"的包误判为丢了,造成无谓重传,加重网络负担;太长,真正的丢包要等很久才补,玩家感知到卡顿。生产代码通常用**动态 RTT 估算**(类似 TCP 的 SRTT/RTTVAR 算法)来设这个阈值,而不是写死的常量。我们这一篇先写一个写死的简版,留个 TODO 提示动态化。

第四个细节是 **ACK 自己不需要可靠**。这是个反直觉但非常重要的点。如果某个 ACK 包丢了,会怎么样?发送方就不知道那个序列号被收到了,会一直把它留在"待确认"列表里,直到超时,然后重传那个数据包。重传之后,接收方会再次收到,然后会再发一个 ACK——这次 ACK 大概率会到。所以 ACK 丢失**会被下一个 ACK 自动修复**,你不需要给 ACK 自己再加一层可靠性,那只会陷入"给可靠通道做可靠通道"的无穷递归。这是可靠 UDP 设计的核心直觉之一,Glenn Fiedler 反复强调。

到这里,接收方有了序列号能感知缺口,接收方有了 ACK 能告诉发送方收到了什么,发送方有了超时能判丢。下一块拼图就是补上丢失——**重传**。

## 5 · 重传与超时:补上那条丢在风里的包

判丢之后,动作就一句话:**把这个包再发一次**。但"再发一次"听起来简单,工程上有几个坑。

第一个坑,**重传的负载不是从原始字节现找的,得缓存着**。你 `send_to` 一个包之后,那段 byte 数组就交给了操作系统,你应用层如果没留底,丢了就找不回来了。所以发送方必须维护一个 **pending packets** 队列:每个发出去的可靠包,在收到 ACK 之前,**它原始的字节内容**得在内存里留着,直到 ACK 来了才能丢掉。这个队列里的每个条目至少要存:序列号、字节内容、第一次发送时间、最后一次重传时间。这是个 O(未确认包数) 的内存占用,生产上要给它一个上限(超过就说明网络实在差,要么降速、要么报错),不能让它无脑涨。

第二个坑,**重传的时机**。最朴素的策略是"超时了立刻重传",但更精细的做法是**指数退避**(exponential backoff)——第一次重传等 RTT,第二次等 2×RTT,第三次 4×RTT……这能避免在网络已经拥塞的时候反复重传把网络彻底搞死。TCP 就这么做。游戏里我们一般折中——重传间隔不指数,但每次重传前先检查"距离上次发送过了多久",不要在 RTT 还没到的时候频繁重传。

第三个坑,**别重传过期数据**。如果你发的是位置快照(每帧一发的玩家位置),那个包到了"该重传"的时候,它其实**早就过期了**——你已经又发了 N 个更新的位置包,这个旧包重传过去对玩家毫无价值。所以**不可靠通道的包根本不应该重传**——它丢了就让它丢。重传只用在**可靠通道**的包上,比如聊天、登录、技能升级这种"内容不会过期"的消息。这就是为什么我们在 §2 强调 per-message 选择的重要性:不可靠的快照压根不进 pending 队列,省 CPU 省内存省带宽。

第四个坑,**重传要带原来的序列号**。听起来废话,但写代码的时候容易漏:重传不是"发一个新包",而是"把原来的那个序列号的包**再发一次**"。接收方收到重传包时,序列号跟之前某个包一样,它要能识别出"这是重传,我已经处理过这个序列号了,直接扔掉(或者更新一下 ACK 状态)",**不能**当成新包再次 apply 到游戏状态上,否则游戏状态会乱。

第五个坑,也是最反直觉的一个:**重传应该用比原始发送更激进的策略吗?不**。重传包用的是跟原始包一样的网络路径、一样的带宽,它并不"优先"。如果你给重传包加优先级,网络拥塞时重传会挤占新包的带宽,陷入恶性循环。重传就是个普通包,该排队排队,该被丢被丢。能丢到让重传也丢的网络,本来就不行了,该考虑的是降级(降发送频率)而不是堆重传。

总结:重传这一层的关键,是它有清晰的边界——**只重传可靠通道的包,只重传没过期的包,只重传到 ACK 来为止,且重传不享受任何特权**。它的代价是发送方内存和带宽,所以可靠通道的消息要慎用,不可靠能搞定的事情别用可靠。这就是为什么 renet、ENet 这些库都让你**显式声明 channel 类型**——它在强迫你想清楚每条消息到底需不需要可靠。

## 6 · 滑动窗口:别让发送方淹死接收方

到这一步,你已经有了序列号、ACK、重传。听起来可靠通道能跑了。但你跑起来会发现一个新问题:**发送方发太快**。

想象发送方有一个 100MB 的关卡数据要推给客户端(玩家加入游戏时同步初始状态)。发送方按可靠通道的逻辑,把这 100MB 全切成包,疯狂 `send_to` 出去。接收方处理不过来——它的 `recv` 缓冲区被塞满,操作系统开始**静默丢弃**新来的包(UDP 在缓冲区满时是直接丢的,不报错)。结果:大量包被丢,触发海量重传,雪崩。

你需要**流量控制**(flow control)——发送方得控制自己,别发得比接收方能消化的还快。最经典的机制叫**滑动窗口**(sliding window)。它的思路是:发送方维护一个**窗口大小** N,意思是"在没收到 ACK 之前,我最多同时让 N 个包在路上"。发够 N 个就停,等 ACK 来了,窗口往前滑一格,再发一个。

窗口大小决定吞吐:窗口太小,带宽利用率低(发送方老在等 ACK,网络空跑);窗口太大,容易淹死接收方。理想窗口 ≈ 带宽 × RTT(经典的 BDP,bandwidth-delay product),但这俩值你都不知道,所以工业代码会做**动态估算**:基于 ACK 到达的速率调整窗口。我们这一篇先写一个固定窗口的简版,生产里要动态化。

滑动窗口在游戏里的实际场景比"推关卡数据"更常见——它其实就是任何**可靠通道**都需要的东西。即便你只是发聊天消息,如果网络突然变差,你也得能"暂停"发送别让 backlog 堆爆。所以滑动窗口是可靠通道的标配组件。

注意滑动窗口和 TCP 的拥塞窗口(congestion window)是两回事,虽然名字像。**滑动窗口**关注的是"接收方处理得了吗",解决的是两端处理能力的对称问题。**拥塞窗口**关注的是"中间链路扛得住吗",解决的是网络中间设备的拥塞问题。TCP 把这俩窗口取 min,综合控制。我们在 UDP 上自建可靠性时,通常会简化——只做滑动窗口(因为是 P2P 或点到点的 server 连接,中间链路一般没问题),不做完整的拥塞控制。renet 这种库默认就是这么折中的。如果你做的游戏要跑在非常糟糕的网络(跨境、卫星),你才需要考虑加拥塞控制。

至此,四块砖全部到位:**序列号**让接收方看见缺口,**ACK** 让发送方知道什么到了,**重传**补上丢失,**滑动窗口**控制发送速率。这四块加在一起,就构成了一个最小的可靠 UDP 通道。下一节我们把这些概念全部落成 Rust 代码,你能跑、能改、能用 `tc netem` 在本机模拟丢包来验证它的行为。

## 7 · 三种通道:可靠有序、不可靠有序、不可靠无序

在写代码之前,我们必须把这一篇的**核心洞察**单独拎出来强调,因为它是你设计网络 API 的根本。这个洞察是:**reliable、ordered、unreliable 不是同一种东西,它们是三种不同的通道,你的网络层应该同时提供这三种,让每条消息自己选**。

第一种,**可靠有序通道**(reliable ordered)。消息保证送到、保证按发送顺序被对方处理。代价是它要承担全套:序列号、ACK、重传、pending 队列、滑动窗口,以及——队头阻塞(在这个通道内部,跟 TCP 一样会阻塞)。所以这个通道只用在**真正需要**的地方:聊天消息(乱序没法读)、登录握手(必须按顺序)、技能升级事件(乱序触发会导致逻辑错乱)、状态变更的"权威通知"。**它的本质是"在这条通道内部,复制了 TCP 的语义"**。但你只对你**需要**这种语义的消息用它,而不是把整条连接搞成可靠有序——这就是它和 TCP 的根本区别。

第二种,**不可靠有序通道**(unreliable sequenced / unreliable ordered)。消息不保证送到,但如果送到了,保证按顺序处理(在接收方看到乱序时,丢弃所有"比已见过的最大序列号更老"的包,只保留最新的)。这就是位置快照该用的通道:每帧的玩家位置,丢了无所谓,反正下一帧还有;但旧的快照**不能覆盖**新的——我玩家明明已经在 (200, 200),你不能因为一个延迟到达的旧包把我拉回 (100, 200)。这个通道**没有重传、没有 pending 队列、没有滑动窗口**(发出去就忘),只有序列号和"丢弃过期"的逻辑。它**完全不阻塞**——这是它和可靠有序的根本区别。游戏里 80% 的实时数据都用这个通道。

第三种,**不可靠无序通道**(unreliable unordered)。消息不保证送到,也不保证顺序,来一个处理一个。用在**每个包独立、新旧无所谓**的场景:语音通话(VoIP,最新一帧音频才有意义,顺序乱了就乱了,人类听不出来)、分散的事件通知(同一事件可能多次触发,任意一个到达即可)。这个通道连序列号都不一定需要(取决于你要不要去重),是最轻量的。

你看得出来,这三种通道是 reliable 和 ordered 两个独立维度的组合,枚举了几乎所有可能性。唯一没列的是"可靠无序",它在游戏里几乎不用——如果你要可靠又不在乎顺序,通常意味着你的应用层逻辑可以容忍乱序,那其实可以用可靠有序然后应用层做幂等,没必要专门开一个通道。

这套"多通道"设计是 renet、ENet、Steam Networking Sockets、Quake 3 网络协议共有的核心思想。**TCP 给你的,只有第一种,而且是焊死在整条连接上的。这就是为什么 TCP 不行,而你自己在 UDP 上要这么做。** 等会儿写代码时,我们会把这三个通道都实现出来,你能直观地看到它们用同样的 UDP socket,但行为完全不同。

## 8 · 把概念落成代码:一个能跑的最小可靠 UDP 库

理论铺垫够了,现在我们把这些概念全部写成 Rust 代码。这个实现的目标是:**教学清晰,功能完整,能跑能改**。它不是生产级(没有加密、没有 RTT 动态估算、没有完整的拥塞控制),但它实现了序列号、ACK 位图、重传、滑动窗口、三种通道,你能在它上面跑通一个 2 人 demo,能用 `tc netem` 模拟丢包来观察可靠消息和不可靠消息的不同表现。

为了依赖最小,我们用 `std::net::UdpSocket` 配 `serde` + `bincode` 做序列化。不引入任何专门的网络 crate——这一篇的目的是让你**理解原理**,不是让你集成现成库(集成 renet 是 09E-2 的事)。

`Cargo.toml`:

```toml
[package]
name = "mini-reliable-udp"
version = "0.1.0"
edition = "2021"

[dependencies]
serde = { version = "1", features = ["derive"] }
bincode = "1"
```

代码分三个文件:`protocol.rs`(协议数据结构)、`reliable_channel.rs`(可靠有序通道的实现)、`main.rs`(demo,跑两个端互通)。下面一个一个来。

### 8.1 `src/protocol.rs`:包格式与通道 ID

```rust
// src/protocol.rs
// 包格式与通道定义。这是收发双方共享的"协议"。

use serde::{Deserialize, Serialize};

// 三种通道,每条消息在发送前要先选一个
#[derive(Copy, Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum ChannelId {
    // 可靠有序:聊天 / 登录 / 重要事件
    ReliableOrdered,
    // 不可靠有序:每帧的位置快照(本篇主用的"实时"通道)
    UnreliableSequenced,
    // 不可靠无序:语音 / 独立事件
    UnreliableUnordered,
}

// 包头:每个 UDP 包都带这个头
#[derive(Copy, Clone, Debug, Serialize, Deserialize)]
pub struct PacketHeader {
    // 这条消息属于哪个通道
    pub channel: ChannelId,
    // 序列号(在对应通道内单调递增)
    pub sequence: u16,
    // ACK:本端"最近收到的"该通道最大连续序列号
    pub ack_seq: u16,
    // ACK 位图:以 ack_seq 为基准,往前 32 个包里哪些收到了
    // bit i = 1 表示 ack_seq - 1 - i 这个序列号收到了
    pub ack_bits: u32,
}

// 一个完整的数据包:包头 + 负载
#[derive(Debug, Serialize, Deserialize)]
pub struct Packet {
    pub header: PacketHeader,
    pub payload: Vec<u8>,
}
```

注意几个设计选择。第一,**通道 ID 写在每个包的头部**——这样接收方收到包时一眼就能看出它属于哪个通道、走哪条处理逻辑。这是"多通道共享一条 UDP socket"的关键,renet 和 ENet 都这么做。第二,**序列号是 u16 而不是 u32**——这一篇先用 u16 让代码简单,但留个 TODO:生产代码要处理 u16 回绕(只要确认窗口 < 32768,回绕判定就是简单的"无符号减法",不复杂)。第三,**ACK 字段也写在每个包头里**——这实现了 §4 讲的 piggyback:每个数据包都顺便捎带本端最新的 ACK 状态,不单独发纯 ACK 包(纯 ACK 包作为兜底,见 §8.4 的定时器)。

### 8.2 `src/reliable_channel.rs`:可靠有序通道的核心

这是这一篇最重的代码。我们专注实现**可靠有序**通道,因为它的逻辑包含了所有难点(序列号、ACK 位图、重传、滑动窗口)。不可靠通道在它基础上做减法,§8.3 会给。

```rust
// src/reliable_channel.rs
// 可靠有序通道(ReliableOrdered)的发送与接收端实现。

use crate::protocol::{ChannelId, Packet, PacketHeader};
use std::collections::{HashMap, VecDeque};
use std::io;
use std::net::{SocketAddr, UdpSocket};
use std::time::{Duration, Instant};

// === 常量 ===

// 滑动窗口大小:在收到 ACK 之前,最多同时"在路上"的包数。
// 这是个写死的简版。生产代码会基于 RTT 估算动态调整。
const WINDOW_SIZE: u16 = 64;

// 重传超时。距离一个包上次发送超过这个时间还没被 ACK,就重传。
// 简版用写死值;生产用 SRTT * 2 之类。
const RTO: Duration = Duration::from_millis(150);

// pending 队列上限。超过说明网络极差,避免内存爆。
const MAX_PENDING: usize = 1024;

// === 发送端 ===

// 一个待确认的包
struct PendingPacket {
    sequence: u16,
    bytes: Vec<u8>,           // 完整序列化好的字节,重传时直接复用
    last_sent: Instant,       // 上次发送时间(用于判断 RTO)
    send_count: u32,          // 发送次数(用于诊断)
}

pub struct ReliableSender {
    // 下一个要分配的序列号
    next_seq: u16,
    // 已经发出、还没被 ACK 的包(按序列号索引)
    pending: HashMap<u16, PendingPacket>,
    // 滑动窗口下界:这个序列号(含)之前的都已 ACK,可发的是 [next_ack, next_ack + WINDOW_SIZE)
    // 实际上 next_seq 已经隐含了"发到哪",window 约束体现在 can_send() 上
    window_base: u16, // 最早未 ACK 的序列号
    // 收到对方的 ACK 后,记录对方"最近收到的最大连续序列号"
    remote_max_recv: Option<u16>,
}

impl ReliableSender {
    pub fn new() -> Self {
        ReliableSender {
            next_seq: 0,
            pending: HashMap::new(),
            window_base: 0,
            remote_max_recv: None,
        }
    }

    // 滑动窗口是否还有空位可以发新包
    pub fn can_send(&self) -> bool {
        let inflight = self.next_seq.wrapping_sub(self.window_base);
        inflight < WINDOW_SIZE
    }

    // 发送一个可靠有序消息
    // 返回分配的序列号
    pub fn send(
        &mut self,
        socket: &UdpSocket,
        remote: SocketAddr,
        payload: &[u8],
        ack_for_remote: (u16, u32), // (ack_seq, ack_bits) 本端对对方的 ACK
    ) -> io::Result<u16> {
        if !self.can_send() {
            // 窗口满了。生产代码这里应该把消息排队等窗口滑,
            // 简版直接报错让上层处理。
            return Err(io::Error::new(
                io::ErrorKind::WouldBlock,
                "reliable send window full",
            ));
        }

        if self.pending.len() >= MAX_PENDING {
            return Err(io::Error::other("pending queue overflow"));
        }

        let seq = self.next_seq;
        self.next_seq = self.next_seq.wrapping_add(1);

        let header = PacketHeader {
            channel: ChannelId::ReliableOrdered,
            sequence: seq,
            ack_seq: ack_for_remote.0,
            ack_bits: ack_for_remote.1,
        };
        let packet = Packet { header, payload: payload.to_vec() };
        let bytes = bincode::serialize(&packet)
            .map_err(|e| io::Error::other(e.to_string()))?;

        socket.send_to(&bytes, remote)?;

        self.pending.insert(
            seq,
            PendingPacket {
                sequence: seq,
                bytes,
                last_sent: Instant::now(),
                send_count: 1,
            },
        );
        Ok(seq)
    }

    // 处理收到的 ACK(从对方的包头解析出来)
    // ack_seq = 对方"最近收到的最大连续序列号"
    // ack_bits = 对该 ack_seq 往前 32 个包的到位情况
    pub fn process_ack(&mut self, ack_seq: u16, ack_bits: u32) {
        // 把所有"被这个 ACK 确认了"的包从 pending 移除
        // ack_bits 的第 i 位 = 1 表示 ack_seq - i 收到了
        for i in 0..32u32 {
            if ack_bits & (1 << i) != 0 {
                let seq = ack_seq.wrapping_sub(i);
                self.pending.remove(&seq);
            }
        }
        // ack_seq 本身也算收到(约定:ack_bits 不包含 ack_seq 自己)
        self.pending.remove(&ack_seq);

        // 推进 window_base:它应该等于 pending 里最小的序列号,
        // 简化做法是循环检查 window_base 是否还在 pending 里
        while !self.pending.contains_key(&self.window_base) && !self.pending.is_empty() {
            // 这里要小心:如果 pending 里所有序列号都比 window_base "新",
            // 推进会过头。简版只在 pending 非空时推进。
            // 真正的工业实现会用一个 seq -> PendingPacket 的有序结构。
            // 这里我们简单推进一格然后退出循环,留给练习改进。
            let next = self.window_base.wrapping_add(1);
            // 检查 next 是否还在 pending 的范围内,避免无穷推进
            if self.pending.values().any(|p| p.sequence == next) || next == self.next_seq {
                break;
            }
            self.window_base = next;
        }
        if self.pending.is_empty() {
            self.window_base = self.next_seq;
        }
    }

    // 在主循环里定期调用:检查 RTO,重传超时的包
    pub fn update_retransmits(&mut self, socket: &UdpSocket, remote: SocketAddr) -> io::Result<usize> {
        let now = Instant::now();
        let mut resent = 0;
        // 克隆 pending 的 key 列表避免 borrow 问题
        let seqs: Vec<u16> = self.pending.keys().copied().collect();
        for seq in seqs {
            let should_resend = {
                if let Some(p) = self.pending.get(&seq) {
                    now.duration_since(p.last_sent) >= RTO
                } else {
                    false
                }
            };
            if should_resend {
                if let Some(p) = self.pending.get_mut(&seq) {
                    socket.send_to(&p.bytes, remote)?;
                    p.last_sent = now;
                    p.send_count += 1;
                    resent += 1;
                }
            }
        }
        Ok(resent)
    }

    // 诊断:目前 inflight 包数
    pub fn inflight(&self) -> usize {
        self.pending.len()
    }
}

// === 接收端 ===

pub struct ReliableReceiver {
    // 下一个期望收到的序列号(可靠有序要求按序交付)
    next_expected: u16,
    // 收到但还不能交付的包(序列号 > next_expected),按序列号索引
    // 用于处理乱序到达
    pending: HashMap<u16, Vec<u8>>,
    // 用于构造 ACK 位图:记录"最近 32 个序列号里哪些收到了"
    // 用一个环形 buffer,简版用一个 set
    received_recently: VecDeque<u16>,
}

impl ReliableReceiver {
    pub fn new() -> Self {
        ReliableReceiver {
            next_expected: 0,
            pending: HashMap::new(),
            received_recently: VecDeque::with_capacity(33),
        }
    }

    // 处理收到的可靠包
    // 返回按序交付给应用层的消息列表(可能为空、可能多条)
    pub fn receive(&mut self, seq: u16, payload: Vec<u8>) -> Vec<Vec<u8>> {
        // 记录这个序列号"收到了",用于构造 ACK 位图
        self.record_received(seq);

        // 如果序列号 < next_expected,这是重复或过期包,直接扔
        // (next_expected 之前的都已经被交付过了)
        let already_delivered = seq.wrapping_sub(self.next_expected) > u16::MAX / 2;
        if already_delivered {
            return Vec::new();
        }

        // 如果正是期望的下一个,交付它,然后看 pending 里有没有"接得上"的
        if seq == self.next_expected {
            let mut out = vec![payload];
            self.next_expected = self.next_expected.wrapping_add(1);

            // 尝试连续交付 pending 里"接得上"的包
            loop {
                if let Some(p) = self.pending.remove(&self.next_expected) {
                    out.push(p);
                    self.next_expected = self.next_expected.wrapping_add(1);
                } else {
                    break;
                }
            }
            return out;
        }

        // 否则(seq > next_expected),先存着等中间的包到
        self.pending.insert(seq, payload);
        Vec::new()
    }

    // 构造给对方发送用的 ACK 状态
    // 返回 (ack_seq, ack_bits):
    //   ack_seq = next_expected - 1(最近连续收到的最大序列号)
    //   ack_bits = 以 ack_seq 为基准,前 32 个包的到位情况
    pub fn ack_state(&self) -> (u16, u32) {
        if self.next_expected == 0 {
            // 还没收到任何包(或刚好收到 0 后回绕到 0,简版忽略)
            return (0, 0);
        }
        let ack_seq = self.next_expected.wrapping_sub(1);
        let mut bits = 0u32;
        for (i, &s) in self.received_recently.iter().enumerate() {
            if i >= 32 {
                break;
            }
            // s 是 ack_seq 的前 i+1 个吗?
            let expected_s = ack_seq.wrapping_sub(i as u16 + 1);
            if s == expected_s {
                bits |= 1 << i;
            }
        }
        (ack_seq, bits)
    }

    fn record_received(&mut self, seq: u16) {
        // 去重
        if self.received_recently.iter().any(|&s| s == seq) {
            return;
        }
        self.received_recently.push_back(seq);
        while self.received_recently.len() > 32 {
            self.received_recently.pop_front();
        }
    }
}
```

这段代码有几个地方值得停下来想一想,因为它们对应着前面几节的概念。

`can_send()` 检查的是滑动窗口还有没有空位。`inflight` 包数(`next_seq - window_base`)< WINDOW_SIZE 时还能发,满了就 `WouldBlock`。这就是 §6 讲的滑动窗口,代码里的实现就是这么朴素——它就是用一个数字上限卡住"同时未确认的包数"。

`process_ack` 把对方确认了的包从 `pending` 移除。这里的位图解码就是把 `ack_bits` 这个 32 位整数,**每一位**对应一个序列号(ack_seq 是第 0 位,ack_seq - 1 是第 1 位……),位是 1 就表示那个序列号被确认了。一个 ACK 包能一次性确认最多 33 个包(ack_seq 自己 + 前 32 个),这是 §4 讲的"批量 ACK"。

`update_retransmits` 是 §5 讲的重传。它扫一遍 `pending`,凡是 `last_sent` 距离现在超过 RTO 的,就重发。注意重发用的是**原始字节**(缓存在 `PendingPacket.bytes` 里),不是重新序列化——这是个微优化,也是为了避免"重发的包内容跟原始包不一样"的诡异 bug。

接收端的 `receive` 体现了"可靠有序"的核心:**严格按序交付**。如果收到的不是期望的下一个序列号,就先攒着(`pending` 这个 HashMap),等到中间缺的包到齐了再一次性交付一串。这就是为什么这个通道内部会有队头阻塞——序列号 100 没到,101、102、103 都到了也得在 `pending` 里干等。这是为了"有序"必须付出的代价。

`ack_state` 是构造 ACK 位图的反向操作,把接收方最近收到的序列号列表压缩成 `(ack_seq, ack_bits)` 塞进下一个发出去的包的包头。这就实现了 §4 讲的 piggyback——我们从不主动发纯 ACK 包,而是搭车在每个数据包上。

### 8.3 不可靠通道:做减法,而不是另起炉灶

讲完可靠有序通道,不可靠通道就简单了——它就是在可靠通道上**砍掉**三样东西:重传、pending 队列、滑动窗口。剩下的序列号 + "丢弃过期"逻辑就够了。

```rust
// src/unreliable_channel.rs
// 不可靠有序通道:用于每帧的实时数据(位置快照)。

use crate::protocol::{ChannelId, Packet, PacketHeader};
use std::io;
use std::net::{SocketAddr, UdpSocket};

pub struct UnreliableSequencedSender {
    next_seq: u16,
}

impl UnreliableSequencedSender {
    pub fn new() -> Self {
        UnreliableSequencedSender { next_seq: 0 }
    }

    // 发出去就忘。没有 pending,没有重传,没有窗口。
    pub fn send(
        &mut self,
        socket: &UdpSocket,
        remote: SocketAddr,
        payload: &[u8],
        ack_for_remote: (u16, u32),
    ) -> io::Result<u16> {
        let seq = self.next_seq;
        self.next_seq = self.next_seq.wrapping_add(1);

        let header = PacketHeader {
            channel: ChannelId::UnreliableSequenced,
            sequence: seq,
            ack_seq: ack_for_remote.0,
            ack_bits: ack_for_remote.1,
        };
        let packet = Packet { header, payload: payload.to_vec() };
        let bytes = bincode::serialize(&packet)
            .map_err(|e| io::Error::other(e.to_string()))?;
        socket.send_to(&bytes, remote)?;
        Ok(seq)
    }
}

pub struct UnreliableSequencedReceiver {
    max_seen: Option<u16>,
}

impl UnreliableSequencedReceiver {
    pub fn new() -> Self {
        UnreliableSequencedReceiver { max_seen: None }
    }

    // 返回 Some(payload) 表示这是"比之前都新"的包,应该处理;
    // 返回 None 表示这是过期或重复包,直接扔。
    pub fn receive(&mut self, seq: u16, payload: Vec<u8>) -> Option<Vec<u8>> {
        let is_new = match self.max_seen {
            None => true,
            Some(max) => {
                // seq > max(考虑回绕)
                let diff = seq.wrapping_sub(max);
                diff != 0 && diff < u16::MAX / 2
            }
        };
        if is_new {
            self.max_seen = Some(seq);
            Some(payload)
        } else {
            None
        }
    }
}
```

对比一下你能看出**不可靠通道**和**可靠通道**的本质区别:

可靠通道的接收端,要维护 `pending` 缓存乱序到达的包、按序交付,缺一个就全部卡住。不可靠通道的接收端,只维护一个 `max_seen`,任何比这个值更老的包**直接扔掉**——它**没有 pending,不会卡**。这就是为什么位置快照必须用不可靠通道:它永远不会被旧包堵住,旧包来了就丢,玩家永远看到最新的位置。

可靠通道的发送端,要维护 `pending` 等待 ACK、定期重传。不可靠通道的发送端,`send_to` 一发就忘,**完全不保留状态**。这就是为什么不可靠通道不会爆内存、不会触发重传洪水。

可靠通道有滑动窗口卡着别发太快。不可靠通道没这个约束——你**就是要**尽快把最新状态推出去,丢就丢。

这三种通道共用一条 UDP socket(通过包头里的 `ChannelId` 区分),但行为完全不同。这就是 §7 讲的"per-message 选择"在代码里的体现。

### 8.4 `src/main.rs`:跑一个 2 人 demo,把所有东西串起来

最后,我们写一个 main,跑两个进程互发可靠消息(模拟聊天)+ 不可靠消息(模拟位置)。这个 demo 同时验证两件事:可靠消息一定送到(即使你用 `tc netem` 把丢包拉到 20%),不可靠消息不阻塞可靠消息。

```rust
// src/main.rs

mod protocol;
mod reliable_channel;
mod unreliable_channel;

use protocol::{ChannelId, Packet};
use reliable_channel::{ReliableReceiver, ReliableSender};
use unreliable_channel::{UnreliableSequencedReceiver, UnreliableSequencedSender};

use std::io::{self, ErrorKind};
use std::net::{SocketAddr, UdpSocket};
use std::time::{Duration, Instant};

// 心跳:哪怕没数据要发,也得定期发个包把 ACK 捎回去
// 否则可靠通道的 ACK 永远没机会搭车
const HEARTBEAT_INTERVAL: Duration = Duration::from_millis(50);
// 10 秒没收到对方任何包,判定断线
const TIMEOUT: Duration = Duration::from_secs(10);

struct Endpoint {
    socket: UdpSocket,
    remote: SocketAddr,
    // 可靠通道
    rs_tx: ReliableSender,
    rs_rx: ReliableReceiver,
    // 不可靠通道
    us_tx: UnreliableSequencedSender,
    us_rx: UnreliableSequencedReceiver,
    // 统计
    last_seen: Instant,
    last_heartbeat: Instant,
    // 已收到但还没交付给"应用层"的可靠消息
    pending_reliable_out: Vec<Vec<u8>>,
    // 简单的统计计数
    reliable_received: u64,
    unreliable_received: u64,
}

impl Endpoint {
    fn new(socket: UdpSocket, remote: SocketAddr) -> Self {
        socket.set_nonblocking(true).unwrap();
        Endpoint {
            socket,
            remote,
            rs_tx: ReliableSender::new(),
            rs_rx: ReliableReceiver::new(),
            us_tx: UnreliableSequencedSender::new(),
            us_rx: UnreliableSequencedReceiver::new(),
            last_seen: Instant::now(),
            last_heartbeat: Instant::now(),
            pending_reliable_out: Vec::new(),
            reliable_received: 0,
            unreliable_received: 0,
        }
    }

    // 收所有 pending 的 UDP 包
    fn poll_incoming(&mut self) -> io::Result<()> {
        let mut buf = [0u8; 2048];
        loop {
            match self.socket.recv_from(&mut buf) {
                Ok((n, _addr)) => {
                    self.last_seen = Instant::now();
                    let packet: Packet = match bincode::deserialize(&buf[..n]) {
                        Ok(p) => p,
                        Err(_) => continue, // 坏包,扔
                    };
                    let header = packet.header;
                    let payload = packet.payload;

                    // 不管是哪个通道的包,头部里都带了对方的 ACK
                    // 用它推进可靠发送端的 pending
                    self.rs_tx.process_ack(header.ack_seq, header.ack_bits);

                    // 构造本端对对方的 ACK 状态(供下次发包时塞进头部)
                    // 注意:可靠 ACK 状态只跟"可靠通道收到的"有关,
                    // 所以只用 rs_rx 来算
                    let _ = self.rs_rx.ack_state(); // 留给下次 send 时用

                    match header.channel {
                        ChannelId::ReliableOrdered => {
                            let delivered = self.rs_rx.receive(header.sequence, payload);
                            for msg in delivered {
                                self.reliable_received += 1;
                                self.pending_reliable_out.push(msg);
                            }
                        }
                        ChannelId::UnreliableSequenced => {
                            if let Some(msg) = self.us_rx.receive(header.sequence, payload) {
                                self.unreliable_received += 1;
                                self.pending_reliable_out.push(msg);
                            }
                        }
                        ChannelId::UnreliableUnordered => {
                            // 本 demo 不用这个通道,直接收
                            self.unreliable_received += 1;
                            self.pending_reliable_out.push(payload);
                        }
                    }
                }
                Err(ref e) if e.kind() == ErrorKind::WouldBlock => break,
                Err(e) => return Err(e),
            }
        }
        Ok(())
    }

    // 发一个可靠消息
    fn send_reliable(&mut self, payload: &[u8]) -> io::Result<()> {
        let ack = self.rs_rx.ack_state();
        self.rs_tx.send(&self.socket, self.remote, payload, ack)?;
        Ok(())
    }

    // 发一个不可靠消息
    fn send_unreliable(&mut self, payload: &[u8]) -> io::Result<()> {
        let ack = self.rs_rx.ack_state();
        self.us_tx.send(&self.socket, self.remote, payload, ack)?;
        Ok(())
    }

    // 主循环每帧调一次:处理重传、心跳、超时检测
    fn update(&mut self) -> io::Result<()> {
        // 1. 重传超时的可靠包
        self.rs_tx.update_retransmits(&self.socket, self.remote)?;

        // 2. 心跳:把积压的 ACK 状态用一个空包搭出去
        //    (空负载的可靠包其实不空——头部带着 ACK)
        let now = Instant::now();
        if now.duration_since(self.last_heartbeat) >= HEARTBEAT_INTERVAL {
            self.last_heartbeat = now;
            // 用不可靠通道发个心跳,纯粹是为了把 ACK 捎出去
            self.send_unreliable(&[])?;
        }

        // 3. 超时检测
        if now.duration_since(self.last_seen) > TIMEOUT {
            return Err(io::Error::other("peer timed out"));
        }
        Ok(())
    }

    // 取走所有已交付但应用层还没读走的可靠消息
    fn drain_delivered(&mut self) -> Vec<Vec<u8>> {
        std::mem::take(&mut self.pending_reliable_out)
    }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 4 {
        eprintln!("Usage: {} <local_port> <remote_ip> <remote_port>", args[0]);
        eprintln!("  Endpoint A: {} 40001 127.0.0.1 40002", args[0]);
        eprintln!("  Endpoint B: {} 40002 127.0.0.1 40001", args[0]);
        std::process::exit(1);
    }
    let local_port: u16 = args[1].parse().unwrap();
    let remote_ip = &args[2];
    let remote_port: u16 = args[3].parse().unwrap();

    let socket = UdpSocket::bind(("0.0.0.0", local_port)).unwrap();
    let remote: SocketAddr = format!("{}:{}", remote_ip, remote_port).parse().unwrap();
    let mut ep = Endpoint::new(socket, remote);

    // Demo 行为:每秒发一条可靠消息(假装是聊天),每 33ms 发一条不可靠消息(假装是位置)
    let mut last_reliable = Instant::now();
    let mut last_unreliable = Instant::now();
    let mut frame_no: u32 = 0;
    let frame_dur = Duration::from_millis(16);

    loop {
        let frame_start = Instant::now();

        // 1. 收包
        if let Err(e) = ep.poll_incoming() {
            eprintln!("recv error: {}", e);
        }

        // 2. 处理已交付的可靠消息
        for msg in ep.drain_delivered() {
            if !msg.is_empty() {
                println!("[port {}] RECV ({}B): {}",
                    local_port, msg.len(), String::from_utf8_lossy(&msg));
            }
        }

        // 3. 每秒发一条可靠消息
        if frame_start.duration_since(last_reliable) >= Duration::from_secs(1) {
            last_reliable = frame_start;
            let chat = format!("chat from {} frame={}", local_port, frame_no);
            match ep.send_reliable(chat.as_bytes()) {
                Ok(_) => {}
                Err(e) => eprintln!("[port {}] reliable send failed: {}", local_port, e),
            }
        }

        // 4. 每 33ms 发一条不可靠消息(位置快照)
        if frame_start.duration_since(last_unreliable) >= Duration::from_millis(33) {
            last_unreliable = frame_start;
            let pos = format!("pos {},{} frame={}", frame_no, frame_no, frame_no);
            let _ = ep.send_unreliable(pos.as_bytes());
        }

        // 5. update:重传 / 心跳 / 超时
        if let Err(e) = ep.update() {
            eprintln!("[port {}] endpoint error: {}", local_port, e);
            break;
        }

        frame_no += 1;

        // 6. 帧节流
        let elapsed = frame_start.elapsed();
        if elapsed < frame_dur {
            std::thread::sleep(frame_dur - elapsed);
        }
    }
}
```

跑这个 demo 的方法,以及怎么用 `tc netem` 模拟丢包来验证它,是下一节"在你 HH 项目里动手"的核心内容。

## 9 · 在你 HH 项目里动手(做中学红线)

理论讲完了,代码也给了,现在轮到你自己跑一遍,在真实的(模拟的)丢包链路上观察可靠 UDP 的行为。这是这一篇的做中学红线——你不亲手跑一遍 `tc netem` + 自己的代码,这些概念永远停留在"我懂了"的层面,不会变成肌肉记忆。

### 第一步:把代码跑起来,验证 localhost 上的基本互通

把上面的 `Cargo.toml` 和三个源文件铺到一个新目录,`cargo build --release`。然后开两个终端:

```bash
# 终端 1
cd /path/to/mini-reliable-udp
./target/release/mini-reliable-udp 40001 127.0.0.1 40002

# 终端 2
cd /path/to/mini-reliable-udp
./target/release/mini-reliable-udp 40002 127.0.0.1 40001
```

你应该看到两边每秒互收一条 `chat from ...` 的可靠消息(模拟聊天),还有大量"位置"消息在静默收发(它们的负载只在打印里被忽略,你可以改 main 加个 `--verbose` 让它打)。这时候一切顺畅,因为 loopback 不丢包。

### 第二步:用 `tc netem` 给 loopback 加丢包,观察可靠消息和不可靠消息的分化行为

这一步是关键。Linux 的 `tc`(traffic control)命令可以在网络接口上做流量整形,`netem` 是其中一个 module,专门用来模拟延迟、丢包、抖动、重复、乱序。我们用它给 `lo`(loopback 接口)加 5% 丢包,然后看你的可靠 UDP 怎么反应。

```bash
# 给 loopback 加 5% 丢包(需要 sudo,因为改内核网络栈)
sudo tc qdisc add dev lo root netem loss 5%

# 验证规则生效
tc qdisc show dev lo
# 应该看到一行 qdisc netem ... loss 5%

# 现在重新跑两个端点
./target/release/mini-reliable-udp 40001 127.0.0.1 40002 &
./target/release/mini-reliable-udp 40002 127.0.0.1 40001 &
```

观察日志。你应该看到:**可靠消息(chat)依然每秒稳定到达,尽管偶有延迟**——这就是重传在工作,丢的那 5% 被 RTO 之后补回来了。**不可靠消息(位置)的某些帧会丢**,但因为它们每 33ms 发一次,丢一两个玩家完全感觉不到,下一帧就覆盖了。两边都不会"卡住"。

把丢包率拉到极端,看边界:

```bash
# 删掉旧规则再加新的
sudo tc qdisc del dev lo root
sudo tc qdisc add dev lo root netem loss 20%

# 重跑
./target/release/mini-reliable-udp 40001 127.0.0.1 40002 &
./target/release/mini-reliable-udp 40002 127.0.0.1 40001 &
```

现在你应该看到可靠消息**仍然**能送到(只是延迟变大,因为重传次数变多),不可靠消息**丢得更多**(但依然不阻塞)。这就是可靠 UDP 设计的胜利:在 20% 丢包的烂链路上,你的聊天还能用,你的位置还在更新,而 TCP 在这种链路上早就因为队头阻塞 + 拥塞退避而假死了。

再加延迟,看 RTT 的影响:

```bash
sudo tc qdisc del dev lo root
sudo tc qdisc add dev lo root netem delay 100ms loss 5%

# 重跑,观察可靠消息的延迟。你应该感觉到 chat 之间间隔变大
# (因为 RTO 是 150ms,RTT 翻倍到 200ms 后重传更慢)
```

实验完一定要清掉规则,不然你的整个 loopback 都受影响(后面跑别的测试会莫名其妙):

```bash
sudo tc qdisc del dev lo root
tc qdisc show dev lo  # 确认回到默认 qdisc(通常是 noqueue)
```

### 第三步:把这层可靠 UDP 集成进 HH 项目

跑通了 demo 之后,把它接到 HH 上。HH 还没有联机,你要做的是给它加一个最小的"双人位置同步"模式:一端是 player 0,另一端是 player 1,双方的玩家位置通过不可靠通道每帧互发(每帧 60Hz,丢一两个无所谓),重要的游戏事件(玩家死亡、关卡完成)通过可靠通道发。

具体步骤:

1. 把 `mini-reliable-udp` 这个 crate 作为 HH 的一个依赖,或者直接把它的源码拷到 HH 项目里(`src/net/`)。
2. 在 HH 的主循环里(就是你按 9B-1 改造出来的那个固定步长 loop),加一个 `network_update` 调用,每帧:`endpoint.poll_incoming()`、`endpoint.update()`、然后 `endpoint.send_unreliable(&serialize_local_player_pos())`。
3. 在游戏逻辑 `step` 里,把收到的对方玩家位置应用到 remote player entity 上(用一个独立的 entity,跟 local player 区分)。
4. 关键事件(玩家被击杀、捡到道具、过关)走 `endpoint.send_reliable(&event)`,在另一边的 `drain_delivered` 里取出并应用。
5. 跑两个 HH 实例,本地 loopback,你应该能看到两个玩家在同一个屏幕里走来走去。

6. 用 `tc netem loss 5%` 重复上面的实验,确认 remote player 偶尔"卡一下然后跳位置"(因为位置包丢了,等下一帧),但游戏**完全不阻塞**——你的 local player 移动如丝,你的关键事件(死亡、过关)一定触发。

这就是你 HH 项目第一次有"能用的联机"。它还不是服务器权威的(那是 09E-2),它只是 P2P 互发状态,但它已经能让你直观地感受到"per-message 选择可靠性的力量"。

## 10 · 练习

练习一,Lv1,概念辨析。有人问你:"既然可靠 UDP 这么好,我干嘛不把所有消息都设成 reliable ordered?反正有重传,稳得很。"想清楚为什么这是错的——会重新引入队头阻塞(位置快照里有一个包丢了,后续位置全卡在 pending 里等),会浪费带宽(位置过期了还在重传),会让 pending 队列爆掉。正确做法是只对**真正需要**可靠有序的消息(聊天、登录、关键事件)开 reliable,实时数据走 unreliable sequenced。能把这条说清楚,你就懂这一篇了。

练习二,Lv2,动手实践。完成 §9 的全部三步——跑通 demo,用 `tc netem` 在 5%、20% 丢包 + 100ms 延迟下分别观察行为,然后集成到 HH 项目跑通双人位置同步。提交 commit,信息可以写 `feat(net): add minimal reliable-UDP transport with tc netem validation`。

练习三,Lv3,改进实现。我们 §8.2 的 `ReliableSender::process_ack` 里的 window_base 推进逻辑是简化的,在边界 case 下可能"卡住"——比如 pending 里同时存在序列号 100 和 200(中间全 ACK 了),window_base 应该跳到 200,但简版代码可能推不动。改用一个 `BTreeMap<u16, PendingPacket>` 让 pending 按序列号有序,然后 `window_base = pending.first_key().unwrap_or(next_seq)`,修掉这个 bug。同时,把 RTO 从写死的 150ms 改成基于实际 RTT 的动态估算(SRTT/RTTVAR,参考 RFC 6298),验证在 5ms loopback 和 100ms netem 延迟下重传时机都合理。

练习四,Lv4,开源贡献。去 renet 的 GitHub 仓库(`https://github.com/lucaspeson/renet`),读它 `reliable_channel.rs` 的实现,跟我们这一篇的版本做对比。挑一个我们的简版做得粗糙的地方(piggyback 策略、ack bitfield 编码、window 推进、RTT 估算),写一个 issue 或 PR,把 renet 的做法和我们教学版的差异梳理清楚——这种"读工业代码 + 写对比"的练习,是把原理知识转化为工程直觉最快的方式。如果你能提一个具体的改进 PR(比如补一个 doc comment 说明 ack bitfield 的位序约定),那是更好的贡献。

## 11 · 延伸阅读与下一篇

Glenn Fiedler 的《Gaffer on Games》网络系列(`https://gafferongames.com/categories/game-networking/`)是这一篇的祖师爷,尤其《Reliable Ordered Messages》那一篇,几乎就是这一篇的蓝本,必读。如果你想看一个完整工业级的可靠 UDP 实现,renet(`https://github.com/lucaspeson/renet`)和 ENet(`http://enet.bespin.org/`)都是开源的,代码量适中,适合通读。Valve 的 Steam Networking Sockets 文档(`https://partner.steamgames.com/doc/features/multiplayer/networking`)展示了在可靠 UDP 之上再叠加密、NAT 穿透、relay 的完整工业栈,值得读了解"生产级"是什么样的。Quake 3 的 `sv_net_chan.c`(`https://github.com/id-Software/Quake-III-Arena/blob/master/code/server/sv_net_chan.c`)是可靠 UDP 的祖师爷级实现,虽然年代久远但思路历久弥新,Glenn Fiedler 的文章里很多内容都能在它里面找到原型。

本仓库内的相关内容:

- [phase-5/deep-dives/network-multiplayer-models](../phase-5/deep-dives/network-multiplayer-models.md) 是这一篇的上游——它讲了 lockstep / state sync / rollback 这些**用**可靠 UDP 的更高层模型,这一篇讲的是**可靠 UDP 本身**怎么造。先读那篇知道"为什么要可靠 UDP",再读这一篇知道"可靠 UDP 怎么做"。
- [phase-5/deep-dives/network-prediction-and-rollback](../phase-5/deep-dives/network-prediction-and-rollback.md) 讲 rollback netcode,它跑在可靠 UDP 之上(因为输入包需要可靠传输才能保证 rollback 的正确性),读完这一篇你能更好地理解 rollback 那边为什么需要 reliable 输入通道。
- [phase-8/deep-dives/determinism-and-replay](../phase-8/deep-dives/determinism-and-replay.md) 讲确定性 + 回放,跟可靠 UDP 配合最深的是"输入录制"——把每帧输入通过可靠通道发到对方,在确定性保证下 replay,这是 lockstep netcode 的根基。
- [phase-0/23-network-foundation](../phase-0/23-network-foundation.md) 是 socket / TCP / UDP 的基础,如果你对 `UdpSocket`、`send_to`、`recv_from` 这些底层 API 还不熟,先回去补这一篇。
- [09B-1-game-loop-and-timestep](09B-1-game-loop-and-timestep.md) 讲的固定步长 loop,是这一篇 `network_update` 调用所嵌入的骨架——你的网络更新必须挂在固定步长的 loop 里,才能保证发送频率稳定(60Hz 位置包、1Hz 心跳),否则帧率波动会让网络行为也跟着波动。

下一篇 [09E-2](09E-2-authoritative-server-and-state-sync.md) 会从这一篇搭好的可靠 UDP 通道之上,继续往上叠——讲**服务器权威架构**(server-authoritative):为什么 client 不能被信任、server 怎么跑完整 simulation、client 怎么做预测和插值、怎么用这一篇的可靠通道发"重要事件"而用不可靠通道发"状态快照"。如果说这一篇讲的是"造一根能用的管子",下一篇讲的就是"怎么用这根管子搭出一个不能被作弊、对延迟友好的联机架构"。管子造好了,该往上盖楼了。
