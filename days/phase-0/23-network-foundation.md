---
article: 23
phase: 0
title: "网络基础:OSI / TCP / UDP / Socket / TLS / HTTP / WebSocket"
type: concept
difficulty: 4
duration: "6-8h"
domains: [network, game, rust, linux]
prereqs: ["08-processes-and-signals", "16-rust-toolchain-deep"]
---

# 23 · 网络基础:从一根网线到多人游戏

> 你给游戏加联机。你写代码:`socket.send("hello")`。你跑——本机两个进程能通信。你拿另一台电脑——**连接超时**。你问朋友,"你 IP 多少",他说 `192.168.1.5`,你 ping 不通。他改说 `8.8.8.8`,你 ping 通了——但你不能往 `8.8.8.8` 发"hello"。你给他装一个 server,你能连,但**发一句话要等 200ms**——分明你们都在同城。你做实时游戏,用 TCP,玩家移动**一卡一卡的**;改 UDP,玩家"瞬移"。你给 server 加 TLS,客户端报 "certificate verification failed"。这些都是网络的真实问题。这一篇讲完,你能 debug 上面所有问题,因为你会理解从你键盘的一次回车,到对方屏幕上的一行字,中间**到底发生了什么**。

## 0 · 为什么要有这一天

让我把镜头拉到一个具体场景。

你跟着 Handmade Hero 走到 Day 300(假设),Casey 开始做联机。他做了一个最简单的 echo server:客户端发什么,服务器回什么。Casey 用 C 写 `socket()`, `bind()`, `listen()`, `accept()`, `recv()`, `send()`——六七个系统调用,跑起来。

你跟 Casey 写一样的代码,本机能 echo。然后你把 server 跑在你家路由器后面的一台 Arch 上,client 跑在你的笔记本(同一 WiFi),连不上。你打开 wireshark 看,全是 ARP——你连 TCP SYN 都没发出去。**为什么**?

**真正的问题**:你有两台电脑,但你不知道它们的 IP。你 `ip addr` 看,两台都是 `192.168.1.x`。你 ping 对方的 192.168.1.5——超时。这是因为**防火墙**?是 NAT?是路由?你要懂 OSI 七层才知道去哪一层查。

第二个陷阱:**延迟的来源**。你的 server 在 AWS 东京,client 在你家北京。RTT(round-trip time,往返延迟) 80ms。你觉得"80ms 还行啊",但你做的是动作游戏,80ms 等于 5 帧(@60Hz)——玩家按下攻击,要等 5 帧才看见角色挥刀。**TCP 在丢包时会重传,延迟突然飙到 300ms**。你的玩家感受是"游戏卡了"。要做对,你得用 UDP + 自己写可靠性层,或者用现成的 KCP / ENet / QUIC。

第三个陷阱:**NAT 穿透**。两个玩家想 P2P 联机(《Minecraft》式的直接连),但两人都在 NAT 后面——彼此的"IP"是内网 IP,公网根本路由不到。你听过"打洞"(hole punching),但不知道怎么实现。你需要懂 STUN / TURN / ICE。

第四个陷阱:**TLS 证书**。你想给 server 上 HTTPS。你 `pacman -S certbot`,跑 `certbot certonly`,搞了几小时。客户端还是报证书错。你打开证书看,有一串 X.509 字段——Common Name / SAN / chain / intermediate CA——你不知道哪个不对。

第五个陷阱:**HTTP/2 / HTTP/3**。你听说"HTTP/2 多路复用"很酷,但你不知道它解决什么问题、和 HTTP/1.1 比快多少、HTTP/3 又是什么(QUIC over UDP)。

**这一篇覆盖**:
- OSI 7 层模型(每层职责、协议)
- TCP 三次握手 / 四次挥手 / 滑动窗口 / 拥塞控制
- UDP 特性、为什么游戏用 UDP
- Socket API:`socket` / `bind` / `listen` / `accept` / `connect` / `send` / `recv`
- IP 地址(IPv4 / IPv6)、子网掩码、CIDR
- NAT / STUN / TURN / ICE(P2P)
- DNS 解析
- TLS 握手 / 证书链
- HTTP/1.1 vs HTTP/2 vs HTTP/3(QUIC)
- WebSocket
- 延迟、带宽、丢包——为什么对游戏特别重要
- 实战:Rust + tokio 的 echo server + client

**每一节**:概念 → Rust 代码 → Linux 工具验证 → 游戏场景 → 跨域关联。

**心理锚点**:这一篇读完,你能:
- 解释为什么 TCP 三次握手不是两次或四次
- 解释为什么《CS:GO》用 UDP 而《文明 6》用 TCP
- 算一个 IP 包从北京到纽约的延迟下限(光纤 + 距离 / 光速)
- 用 `tcpdump` / `wireshark` 抓包读懂三次握手
- 用 `strace` 看 Rust 程序到底调了哪些 socket syscall
- 写一个能并发处理 10000 连接的 tokio echo server
- 解释 NAT 后两台机器怎么 P2P 通信(STUN + 打洞)
- 解释为什么 HTTP/3 跑在 UDP 上而不是 TCP

---

## 1 · 概念地图:网络的 7 层

很多人背 OSI 7 层只是背口诀。今天我们把它当作**debug 路线图**——你的连接出问题了,你按层从下到上检查。

| 层 | 名字 | 单位 | 代表协议 | 出问题的现象 |
|---|---|---|---|---|
| 1 | 物理(Physical) | bit | 10BASE-T, 802.11 | 网线松了 / WiFi 信号差 |
| 2 | 链路(Data Link) | frame | Ethernet, ARP | MAC 地址冲突 / ARP 欺骗 |
| 3 | 网络(Network) | packet | IP, ICMP | IP 冲突 / 路由黑洞 |
| 4 | 传输(Transport) | segment | TCP, UDP | 端口被防火墙挡 / 拥塞 |
| 5 | 会话(Session) | — | (在 TCP 里) | 长连接被中间设备断开 |
| 6 | 表示(Presentation) | — | TLS, JSON, Protobuf | 证书错 / 编码错 |
| 7 | 应用(Application) | message | HTTP, DNS, WebSocket | 404 / 协议字段错 |

**口诀**:"All People Seem To Need Data Processing"(从上到下:Application / Presentation / Session / Transport / Network / Data Link / Physical)。或者中文"物数网传会表应"。

**关键洞察**:每一层只和它的对等层"说话"。你浏览器发 HTTP 请求(HTTP 是第 7 层),对方服务器的 HTTP 服务收——但你浏览器在发之前,要先把请求**层层封装**:HTTP message → 装进 TCP segment(加端口号)→ 装进 IP packet(加 IP 地址)→ 装进 Ethernet frame(加 MAC 地址)→ 转成电信号发出去。对方收到,**层层拆开**。

```
发送方(向下封装)            接收方(向上拆封)
  HTTP message                  HTTP message
       ↓                             ↑
  +---------+                   +---------+
  | TCP hdr |                   | TCP hdr |
  +---------+                   +---------+
       ↓                             ↑
  +---------+                   +---------+
  | IP hdr  |                   | IP hdr  |
  +---------+                   +---------+
       ↓                             ↑
  +---------+                   +---------+
  | ETH hdr |                   | ETH hdr |
  +---------+                   +---------+
       ↓                             ↑
    电信号  →→→→→ 物理介质 →→→→→    电信号
```

每一层加自己的头(header),接收方一层层剥。这是**封装(encapsulation)** 的本质。

---

## 2 · 心智模型

### 2.1 类比:邮局系统

把网络想成邮局。

- **物理层**:卡车在公路上跑。卡车坏了、路塌了,信送不到。
- **链路层**:两辆卡车之间的中转站。每个中转站看信封上的"下一站地址",决定往哪转。这层用 MAC 地址标识设备(网卡的硬件编号)。
- **网络层**:信封上写的是**最终收件人地址**(IP 地址,例如 `142.250.80.46`)。中转站不看信的内容,只看"最终地址",挑一条路往那送。
- **传输层**:信封上多了一个"门牌号"(端口号,例如 `443`)。同一栋楼(同一台机器)上很多人,门牌号区分谁收。TCP 还会在信里加"这是第几封信",丢了重发;UDP 不加,丢就丢。
- **会话 / 表示层**:加密信件内容(TLS),翻译语言(UTF-8 编码)。
- **应用层**:信的实际内容,比如"GET /index.html HTTP/1.1"。

**邮局的洞察**:你写信时,你以为"直接和对方通信"。实际你的信经过了 N 个中转站,每个站只看一层信息,然后转给下一站。**没有一台机器知道整条路径**,每台只知道"下一步往哪送"——这叫**hop-by-hop 转发**。

### 2.2 第一原理:带宽、延迟、丢包

网络的三个核心指标:

**带宽(bandwidth)**:每秒能传多少字节。单位 bps(bits per second)或 Bps(bytes)。家用宽带"千兆"= 1 Gbps = 125 MB/s。注意小写 b(bit)和大写 B(byte),这是销售话术——"千兆"听起来很大,实际只有 125 MB/s。

**延迟(latency)**:一个 bit 从 A 到 B 用多久。单位 ms(毫秒)。从北京到纽约的光纤延迟下限约 70ms(光速 + 距离),实际通常 150-300ms。**本地局域网延迟 < 1ms**。

**丢包率(packet loss)**:发送的包里有多少比例没到。家用 WiFi 在干扰下能丢 5%——每 20 个包丢 1 个。有线网通常 < 0.1%。

**关键公式**:

```
RTT (round-trip time) = 单程延迟 × 2
吞吐量 (TCP 单流, 简化) ≈ 窗口大小 / RTT
```

延迟的下限由**光速**决定。光在真空里 ~3×10⁸ m/s,在光纤里 ~2×10⁸ m/s(折射率 1.5)。北京到纽约直线 ~11000 km,光纤路径绕一绕 ~15000 km,所以单程 ~75ms,RTT ~150ms。**这是物理下限,无法超越**——除非物理改了或者距离短了。

对游戏的影响:
- **回合制游戏**(《文明》):用 TCP,延迟无所谓。
- **ARPG / FPS**(《CS:GO》):用 UDP,延迟要 < 100ms 才爽。
- **格斗游戏**(《街霸》):延迟要 < 50ms,用 rollback netcode(预测 + 回滚)。

### 2.3 七层的"为什么这么多"

为啥分七层,不是一层或五十层?

**分层的好处**:每一层**独立演化**。物理层从同轴电缆 → 双绞线 → 光纤 → WiFi → 5G,上层完全不用改。应用层从 HTTP/1.1 → HTTP/2 → HTTP/3,下层不用改。这叫**解耦**。

**层数的权衡**:
- 太少(1-2 层):任何小变化都要改全部。
- 太多(50 层):每次发信都要走 50 道手续,效率低。

七层是历史折中。实际上现在互联网主流是 **TCP/IP 四层模型**(也简化的五层):Link / Internet / Transport / Application。OSI 七层的 Session / Presentation 在 TCP/IP 里合并到 Application 里(因为 TCP 自己就维持 session,TLS 在 application 里)。

```
OSI 7层        TCP/IP 4层        实际协议
─────────      ─────────         ────────
Application  ┐
Presentation ├→ Application    → HTTP, DNS, WebSocket
Session      ┘
Transport    →  Transport      → TCP, UDP
Network      →  Internet       → IP, ICMP
Data Link    ┐
Physical     ┘→ Link           → Ethernet, WiFi
```

你以后看资料,如果写 TCP/IP 模型就是四层,写 OSI 就是七层。**工程上更常用 TCP/IP 四层**,但概念上 OSI 七层更精细。

---

## 3 · 物理层和链路层(第 1-2 层)

### 3.1 物理层:bit 在导线里跑

物理层规定"0 和 1 怎么编码成电信号 / 光信号 / 无线电波"。

以太网线(双绞线):差分信号。`+1V / -1V` 编码 1,`-1V / +1V` 编码 0。差分的好处是抗干扰(两根线受同样的干扰,差值不变)。

光纤:光的有无 / 颜色 / 相位编码 bit。单模光纤(细,激光)能传几十公里;多模光纤(粗,LED)几百米。

WiFi(802.11):无线电波。2.4 GHz / 5 GHz / 6 GHz 频段。调制方式 OFDM(正交频分复用)——把数据分到几十个子载波上,并行传。

**对游戏的物理层影响**:WiFi 的物理层特性决定了**它不适合实时游戏**。WiFi 是共享介质(同一频段的路由器互相干扰),数据碰撞要重传,延迟方差大(jitter)。有线网独占介质,延迟稳定。所以电竞选手都插网线——这不是迷信,是物理。

### 3.2 链路层:Ethernet frame 和 MAC 地址

链路层规定"两个**直接相连**的设备之间怎么通信"。直接相连意味着同一局域网(同一个交换机 / 同一 WiFi)。

**MAC 地址**:网卡的硬件编号,48 bit,写成 `aa:bb:cc:dd:ee:ff`。前 24 bit 是厂商代码(OUI),后 24 bit 厂商自分配。MAC 地址"理论上唯一",实际可以软件改。

**Ethernet frame**:链路层的数据单位。结构:

```
| 目标 MAC (6B) | 源 MAC (6B) | 类型 (2B) | 数据 (46-1500B) | FCS (4B) |
```

`类型` 字段标识上层协议(`0x0800` = IPv4, `0x86DD` = IPv6, `0x0806` = ARP)。MTU(maximum transmission unit,最大传输单元)通常是 1500 字节——这是数据字段的长度上限。

**MTU 的连锁反应**:如果一个 IP 包有 4000 字节,但 Ethernet MTU 是 1500,IP 层会**分片(fragmentation)**——拆成 3 个包(1500 + 1500 + 1000)。任何一个分片丢了,整个原包都废。现代 OS 用 PMTUD(path MTU discovery)动态探测路径上最小 MTU。

**ARP(Address Resolution Protocol)**:把 IP 地址翻译成 MAC 地址。同一局域网内,A 要给 B 发包,A 必须知道 B 的 MAC。A 在 ARP 表里查(`ip neigh` 看),没有就广播问"谁有 IP X.X.X.X?把你的 MAC 告诉我"。

```bash
# 看你的 ARP 表(也叫 neighbor table)
ip neigh show
# 输出例:
# 192.168.1.1 dev eth0 lladdr 00:11:22:33:44:55 REACHABLE
# 192.168.1.5 dev eth0 lladdr aa:bb:cc:dd:ee:ff STALE
```

**ARP 欺骗**:攻击者伪造 ARP 应答,让 A 以为攻击者的 MAC 是 B 的 MAC,A 的流量都发到攻击者那里。这就是中间人攻击(MITM)的基础。家用网络不防,企业网用 DHCP snooping + ARP inspection。

### 3.3 交换机 vs 路由器

两个容易混的设备。

**交换机(switch)**:链路层设备。它有多个口,每个口接一台机器。交换机内部维护"MAC → 口"的表,收到 frame,看目标 MAC,转发到对应口。**只在同一局域网内**。

**路由器(router)**:网络层设备。它有多个口,接**不同网络**。路由器看 IP 包的目标 IP,查路由表,转发到下一个路由器。**跨网络通信**。

你家路由器其实是"路由器 + 交换机 + WiFi AP + DHCP server + NAT"五合一。WAN 口是路由器功能,LAN 口是交换机功能,天线是 AP,DHCP 自动分配 IP,NAT 让内网共用一个公网 IP。

---

## 4 · 网络层:IP 协议(第 3 层)

### 4.1 IP 地址:设备的"邮政编码"

IP 地址是网络层地址,**逻辑地址**(不像 MAC 是物理地址)。一台机器可以有多个 IP(每个网卡一个,或者一台机器多块网卡)。IP 地址可以软件改。

**IPv4**:32 bit,写成 4 个 0-255 的十进制数,`192.168.1.100`。共 ~43 亿个地址——已经用完。所以有了 IPv6。

**IPv6**:128 bit,写成 8 组 4 位十六进制,`2001:0db8:85a3:0000:0000:8a2e:0370:7334`。连续的 0 可以缩写成 `::`,`2001:db8:85a3::8a2e:370:7334`。地址空间 ~3.4×10³⁸——给地球上每粒沙子分一个都够。

**为什么 IPv6 推广慢**:2010 年说"IPv4 几年内耗尽,大家赶紧上 IPv6",实际 2024 年 IPv6 渗透率约 40%。原因是 NAT 让 IPv4 能"够用"——所有家用设备共用一个公网 IP。但 NAT 破坏了端到端(后面 ICE 一节讲)。

### 4.2 IPv4 地址分类和私有地址

IPv4 早期分五类(基于第一字节):

| 类 | 第一字节范围 | 网络位 | 默认掩码 |
|---|---|---|---|
| A | 0-127 | 8 bit | 255.0.0.0 |
| B | 128-191 | 16 bit | 255.0.0.0 |
| C | 192-223 | 24 bit | 255.255.255.0 |
| D | 224-239 | (组播) | — |
| E | 240-255 | (保留) | — |

这个分类太死板,后来用 **CIDR**(无类别域间路由)替代。

**私有地址**(RFC 1918):三段 IP 段保留给内网用,公网不路由:
- `10.0.0.0/8`(1677 万个)
- `172.16.0.0/12`(104 万个)
- `192.168.0.0/16`(65536 个)

你家 WiFi 大概用 `192.168.x.x`。公司内网用 `10.x.x.x`。

**特殊 IP**:
- `127.0.0.1`:loopback / localhost,指自己。
- `0.0.0.0`:绑定所有网卡(server 监听时用)。
- `255.255.255.255`:有限广播,本网所有机器。

### 4.3 子网掩码和 CIDR

一个 IP = 网络部分 + 主机部分。**子网掩码**告诉你在哪里切。

`192.168.1.100 / 255.255.255.0`:
- 网络部分:`192.168.1`(前 24 bit,因为掩码前 24 bit 是 1)
- 主机部分:`100`(后 8 bit)
- 这个子网能容纳 256 个 IP(实际 254 个,因为 `.0` 是网络号,`.255` 是广播)

**CIDR 表示法**:把掩码写成 `/N`,N 是网络位数。`192.168.1.100/24` 等价于掩码 `255.255.255.0`。`10.0.0.1/8` 等价于 `255.0.0.0`。

CIDR 让你切**任意位数**,不限于 8/16/24。比如 `/22` = 网络 22 bit,主机 10 bit = 1024 个 IP。这种灵活性对 ISP 有用——按用户数精确切,不浪费。

```bash
# 看你的 IP 和掩码
ip -4 addr show
# 输出例:
# inet 192.168.1.100/24 brd 192.168.1.255 scope global eth0
#                            ↑广播              ↑作用域

# 算一个 /22 子网有多少 IP
python3 -c "print(2 ** (32 - 22))"
# 输出 1024
```

### 4.4 路由:包怎么从 A 到 B

**路由表**:每台机器有一张,告诉"目标 IP 是 X,从哪个网卡发,下一跳给谁"。

```bash
# 看路由表
ip route show
# 输出例:
# default via 192.168.1.1 dev eth0          ← 默认路由(去外网)
# 192.168.1.0/24 dev eth0 proto kernel       ← 本网段
# 10.10.0.0/16 via 192.168.1.254 dev eth0    ← 公司 VPN 网段
```

读懂路由表:
- `default via 192.168.1.1`:不知道往哪送的包,通通发给 `192.168.1.1`(你家路由器)。
- `192.168.1.0/24 dev eth0`:本网段(同交换机的机器),直接通过 eth0 发。
- `10.10.0.0/16 via 192.168.1.254`:发往 `10.10.x.x` 的包,转给 `192.168.1.254`(可能是 VPN 网关)。

**路由的"最长前缀匹配"原则**:如果多个路由都匹配目标 IP,选掩码最长的(最具体的)。比如目标 `192.168.1.5`,同时匹配 `192.168.0.0/16` 和 `192.168.1.0/24`,选 `/24` 那条。

**TTL(time to live)**:每个 IP 包有一个 TTL 字段,初始值 64 或 128。每经过一个路由器 -1。降到 0 还没到,路由器丢包并回 ICMP "Time Exceeded"。这就是 `traceroute` 的原理——故意发 TTL=1, 2, 3... 的包,记录每个路由器回的 ICMP。

```bash
# 看到-google-的路径
traceroute 8.8.8.8
# 或现代版
mtr 8.8.8.8    # 持续刷新,综合 traceroute + ping
```

### 4.5 ICMP:网络层的"信使"

ICMP(Internet Control Message Protocol)是 IP 的辅助协议,用来报告错误和状态。

- `ping`:发 ICMP Echo Request,对方回 Echo Reply。验证"对方在不在 + RTT 多少"。
- `traceroute`:用 ICMP Time Exceeded 反推路径。
- "Destination Host Unreachable":路由器不知道怎么到目标。
- "Fragmentation Needed":PMTUD 用。

```bash
ping -c 4 8.8.8.8
# 输出例:
# PING 8.8.8.8 56(84) bytes of data.
# 64 bytes from 8.8.8.8: icmp_seq=1 ttl=117 time=8.21 ms
# 64 bytes from 8.8.8.8: icmp_seq=2 ttl=117 time=8.45 ms
# ...
# rtt min/avg/max/mdev = 8.213/8.412/8.512/0.156 ms
```

`time=8.21 ms` 就是 RTT(从发出到收回)。`mdev` 是标准差,反映**抖动(jitter)**。游戏关心抖动——10ms±2ms 比 30ms±20ms 玩起来更稳。

---

## 5 · 传输层:TCP 和 UDP(第 4 层)

这是网络里最重要的一层。游戏联网、Web 浏览、视频流——所有应用层选择 TCP 还是 UDP,决定了延迟、可靠性、复杂度的根本权衡。

### 5.1 端口号:同一台机器上多个服务

IP 定位机器,端口号定位机器上的进程。端口是 16 bit,范围 0-65535。

- 0-1023:**well-known ports**(特权端口)。Unix 上要 root 才能 bind。HTTP 80, HTTPS 443, SSH 22, DNS 53, SMTP 25。
- 1024-49151:**registered ports**。数据库、游戏服务等。MySQL 3306, PostgreSQL 5432, Redis 6379, Minecraft 25565。
- 49152-65535:**ephemeral ports**。客户端临时用,系统自动分配。

```bash
# 看你的连接和端口
ss -tulnp
# t = TCP, u = UDP, l = listening, n = 不解析名字, p = 显示进程
# 输出例:
# Netid State  Local Address:Port  Peer Address:Port  Process
# tcp   LISTEN 0.0.0.0:22          0.0.0.0:*          users:(("sshd",pid=1234,fd=3))
# tcp   LISTEN 127.0.0.1:6379      0.0.0.0:*          users:(("redis-server",...))
# udp   UNCONN 0.0.0.0:68          0.0.0.0:*          users:(("NetworkManager",...))
```

### 5.2 TCP:可靠的字节流

TCP(Transmission Control Protocol)的核心特性:

1. **面向连接**:通信前先握手建立连接(SYN, SYN-ACK, ACK)。
2. **可靠**:发了的包一定到(丢了重传)。
3. **有序**:接收方按发送顺序收到。包 2 先到包 1 后到,TCP 缓存包 2,等包 1 到了再交上层。
4. **流控(flow control)**:接收方告诉发送方"我还能收多少"(滑动窗口)。
5. **拥塞控制(congestion control)**:发送方主动减速,避免网络崩溃。

TCP 把数据看作**字节流**,不是消息。你 `send("hello")` 然后 `send("world")`,对方可能 `recv` 一次收到 `"helloworld"`,也可能收到 `"hel"`、`"lowo"`、`"rld"`。**TCP 不保留消息边界**。这是新手最常踩的坑——你以为是发两条消息,对方收到一条粘在一起。要做"消息",应用层自己加长度前缀或分隔符。

#### 5.2.1 三次握手(three-way handshake)

建立 TCP 连接要三个包:

```
客户端                                  服务端
  |                                       |
  | --- SYN (seq=x) --------------->      |   客户端:"我想连,我的初始序列号是 x"
  |                                       |
  | <--- SYN+ACK (seq=y, ack=x+1) ---     |   服务端:"好的,我同意。我的初始序列号是 y,期待你下次发 x+1"
  |                                       |
  | --- ACK (seq=x+1, ack=y+1) ---->      |   客户端:"收到,我期待你下次发 y+1"
  |                                       |
  |       连接建立,可以互发数据了          |
```

**为什么是三次,不是两次**?

如果两次:服务端回 SYN+ACK,直接认为连接建立。问题:**网络延迟可能让旧的 SYN 到达**。客户端 A 几秒前发了一个 SYN(连接早已关闭),这个 SYN 因为网络堵塞延迟到几秒后才到服务端 B。B 回 SYN+ACK,B 以为连接建立了,等 A 发数据。但 A 早就忘了这件事,不会发。**B 浪费资源等待**。

三次握手让 A 第三次确认——A 收到 SYN+ACK 后,如果它没发过 SYN(这是僵尸 SYN),它发 RST(reset)而不是 ACK,B 就清掉。这叫**防止历史连接复用**。

**为什么不是四次**?三次已经够确认双向了。再加一次只是冗余。

#### 5.2.2 四次挥手(four-way handshake)

关闭 TCP 连接要四个包,因为 TCP 是**全双工**(双向都能发数据),每方都要单独关:

```
客户端                                  服务端
  |                                       |
  | --- FIN (seq=x) --------------->      |   客户端:"我没数据发了"
  |                                       |
  | <--- ACK (ack=x+1) -------------      |   服务端:"收到。等我发完我的再关"
  |                                       |
  |       (服务端可能还在发数据)            |
  |                                       |
  | <--- FIN (seq=y) ---------------      |   服务端:"我也发完了,关了"
  |                                       |
  | --- ACK (ack=y+1) -------------->     |   客户端:"好的,再见"
  |                                       |
  | (客户端等 2*MSL 才真正关闭)              |
```

中间 ACK 和 FIN 之间,服务端可以继续发数据。这叫 **half-close**——一边关了,另一边还能发。

**TIME_WAIT 状态**:主动关闭方最后发的 ACK 后,要等 2×MSL(maximum segment lifetime,默认 30s-120s)才真正释放端口。原因是怕 ACK 丢了——如果丢了,被动方会重发 FIN,主动方要还能回 ACK。但 TIME_WAIT 占着端口,server 大量短连接时端口耗尽,这是高性能 server 的痛点。

#### 5.2.3 滑动窗口:发送方 vs 接收方速度匹配

TCP 是可靠传输。你发了 1MB,要等对方 ACK 才能发下一批?那太慢了——RTT 100ms,1MB / 100ms = 10 MB/s,带宽利用率极低。

**滑动窗口**:发送方维护一个窗口,窗口内的包可以连续发,不等 ACK。接收方 ACK 时带"我还能收多少字节"(rwnd, receive window)。窗口在数据流上"滑动"——前面的 ACK 了,窗口往后挪。

```
发送窗口(假设 5 个包大小):
[1][2][3][4][5] [6][7][8]...
已确认  已发未确认   未发
       ↑ 窗口 ↑
```

收到 ACK 1,窗口右移一格,包 6 可发:
```
[1][2][3][4][5][6] [7][8]...
    已确认  已发未确认  未发
          ↑ 窗口 ↑
```

接收方处理慢,缓存快满了,就在 ACK 里把 rwnd 调小,告诉发送方"等等我"。这叫**流控**。

#### 5.2.4 拥塞控制:全局速度匹配

流控只看两台机器之间。但网络中间有几百台路由器、几万个用户共享。**所有人都按自己最大窗口发,网络会崩溃**——路由器缓存满了,丢包率飙升,所有人重传,雪崩。

**拥塞控制**是发送方主动减速,推测"网络是不是堵了",避免崩溃。算法演化:

**Reno(1988)**:加性增,乘性减(AIMD)。
- 没有 ACK 丢失时:每 RTT 窗口 +1(线性增长)。
- 检测到丢包(超时或重复 ACK):窗口 /2(乘性减半)。
- 一直在探测带宽,丢包就是信号。

**CUBIC(默认 Linux 2008-)**:Reno 改进。窗口增长用三次函数(立方),让大窗口时增长快,小窗口时增长慢。在高带宽延迟积(BDP)网络上比 Reno 好。**Linux 默认**到今天。

**BBR(Google 2016-)**:不用丢包作信号,用 RTT 和带宽测量。BBR 测 RTT 的最小值(说明路径短)和带宽的最大值(说明管道粗),把窗口设为 bandwidth × RTT。BBR 在跨太平洋大 RTT 链路上比 CUBIC 快很多。YouTube 和 Google 全用 BBR。但 BBR 在**和 CUBIC 共存**时有公平性问题,在拥塞的网络上会"抢"带宽。

```bash
# 看你 Linux 当前用的拥塞控制
sysctl net.ipv4.tcp_congestion_control
# 输出:net.ipv4.tcp_congestion_control = bbr (或 cubic)

# 看可用算法
sysctl net.ipv4.tcp_available_congestion_control
# 输出:net.ipv4.tcp_available_congestion_control = reno cubic bbr ...

# 临时改成 cubic
sudo sysctl -w net.ipv4.tcp_congestion_control=cubic
```

#### 5.2.5 TCP 对游戏的优劣

**优点**:
- 可靠。重要的状态同步(玩家登录、聊天)用 TCP 简单。
- 有序。客户端发"先攻击再喝药",服务端按顺序处理。
- 内置流控和拥塞控制。

**缺点(对游戏致命)**:
- **head-of-line blocking**:包 1 丢了,包 2、3 即使到了也不能交上层,要等包 1 重传。**实时游戏宁可不收旧数据,要收最新数据**——玩家位置每帧更新,丢一帧没关系,但要等旧的重传就是卡顿。
- **重传延迟**:包丢了,TCP 等超时(RTT 的几倍)才重传。游戏中这等于"卡住"。
- **握手延迟**:建连要 1.5 RTT。同 RTT 50ms,连一下要 75ms 才能发数据。短连接场景贵。

### 5.3 UDP:无连接、不可靠、但快

UDP(User Datagram Protocol)极简:

```
| 源端口 (2B) | 目标端口 (2B) | 长度 (2B) | 校验和 (2B) | 数据 |
```

8 字节头(TCP 头至少 20 字节)。**无连接**(发之前不用握手)、**不可靠**(丢了不重传)、**无序**(包 2 可能比包 1 先到)、**无流控**(发多少看自己)。

UDP 就是"把数据丢出去,管它到不到"。

**为什么游戏用 UDP**:
1. **不要 head-of-line blocking**:包 1 丢了不影响包 2。游戏每帧发"当前玩家位置",旧的丢了无所谓,要新的。
2. **可控的可靠性**:游戏可以在 UDP 上**自己实现**可靠性——重要事件(开枪、命中)用 ACK 重传,不重要事件(玩家位置)直接丢就丢。
3. **低延迟**:不用等握手,直接发。
4. **组播 / 广播**:UDP 支持一对多。游戏服务器发现、局域网游戏用组播。

**主流游戏网络栈**:
- **《Quake》系列**:UDP + 自研可靠性。
- **《CS:GO》/《Valorant》**:UDP + 自研。
- **《Minecraft》**:Java 版 TCP,基岩版 UDP(RakNet)。
- **《GTA Online》**:UDP。
- **《文明 6》**:TCP(回合制,延迟无所谓)。

工业级 UDP 可靠层库:
- **ENet**:老牌,C 语言,UDP + 可靠 + 通道。
- **KCP**:中国出品,纯算法,可靠 UDP,比 TCP 快 30%-40%。
- **RakNet**:Unity 收购过,现在开源,C++。
- **QUIC**:Google 设计,HTTP/3 的传输层,UDP + TLS + 多路复用 + 0-RTT。

```rust
// UDP 发送一个 datagram
use std::net::UdpSocket;

fn main() -> std::io::Result<()> {
    let socket = UdpSocket::bind("0.0.0.0:0")?;  // 客户端,系统分配端口
    socket.send_to(b"hello game server", "127.0.0.1:3478")?;
    
    let mut buf = [0u8; 1024];
    let (n, src) = socket.recv_from(&mut buf)?;
    println!("Received {} bytes from {}", n, src);
    Ok(())
}
```

UDP 的"无连接"不代表它**没有连接概念**——你可以 `connect()` 一个 UDP socket,这只是 OS 记下"目标地址",之后 `send` 不用每次写地址。但 UDP 的 connect 不发任何包(对端根本不知道你 connect 了)。

---

## 6 · Socket API:Rust 视角

Socket 是 BSD Unix 在 1983 年引入的网络 API。Linux 继承这套 API。**所有现代语言的网络库,底层都是 socket**。

### 6.1 Socket 的六个基本操作

```
socket()   → 创建 socket 文件描述符
bind()     → 绑定到本地 IP + 端口
listen()   → 标记为被动(等待连接)
accept()   → 阻塞,等客户端连接
connect()  → 主动连接到对方
send()/recv() 或 read()/write()  → 收发数据
close()    → 关闭
```

**TCP server 流程**:
```
socket() → bind(本地端口) → listen() → 循环 {
    accept() → 得到新 socket → fork / thread 处理 → close
}
```

**TCP client 流程**:
```
socket() → connect(对方 IP + 端口) → send/recv → close
```

**UDP 流程**(server 和 client 类似):
```
socket() → bind(本地端口) → recv_from / send_to → close
```

### 6.2 Rust std::net:阻塞 socket

Rust 标准库 `std::net` 提供阻塞 socket。简单但不适合高并发。

```rust
use std::net::{TcpListener, TcpStream};
use std::io::{Read, Write};
use std::thread;

fn main() -> std::io::Result<()> {
    // 监听 127.0.0.1:7878
    let listener = TcpListener::bind("127.0.0.1:7878")?;
    println!("Server listening on 7878");
    
    for stream in listener.incoming() {
        let mut stream = stream?;
        // 每个连接开一个线程
        thread::spawn(move || {
            let mut buf = [0u8; 1024];
            loop {
                match stream.read(&mut buf) {
                    Ok(0) => return,         // 连接关闭
                    Ok(n) => {
                        if stream.write_all(&buf[..n]).is_err() {
                            return;
                        }
                    }
                    Err(_) => return,
                }
            }
        });
    }
    Ok(())
}
```

跑一下:
```bash
# Terminal 1
cargo run

# Terminal 2
nc 127.0.0.1 7878
hello        # 你输入
hello        # 回显
^C
```

用 strace 看实际系统调用:
```bash
strace -f -e trace=network,read,write ./target/debug/echo_server 2>&1 | head -50
# 输出会显示 socket(), bind(), listen(), accept4(), read(), write() 等系统调用
```

线程模型的瓶颈:10000 连接 = 10000 线程,每线程 ~8MB 栈 = 80GB 内存。不现实。

### 6.3 Tokio:异步 IO + 事件循环

异步 IO 的核心:**一个线程管理多个 socket**。线程调 `epoll_wait`(Linux)或 `kqueue`(BSD),内核告诉你"这几个 socket 有数据了",你再去 read。

**Tokio** 是 Rust 最主流的异步运行时。它内部用 epoll(Linux),通过 `async fn` 让你写"看起来像同步"的代码。

```toml
# Cargo.toml
[dependencies]
tokio = { version = "1", features = ["full"] }
```

```rust
use tokio::net::{TcpListener, TcpStream};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

#[tokio::main]
async fn main() -> tokio::io::Result<()> {
    let listener = TcpListener::bind("127.0.0.1:7878").await?;
    println!("Server listening on 7878");
    
    loop {
        let (socket, addr) = listener.accept().await?;
        println!("Connection from {}", addr);
        
        // 每个连接 spawn 一个 task(类似协程,不占线程)
        tokio::spawn(async move {
            if let Err(e) = handle_client(socket).await {
                eprintln!("Error: {}", e);
            }
        });
    }
}

async fn handle_client(mut socket: TcpStream) -> tokio::io::Result<()> {
    let mut buf = [0u8; 1024];
    loop {
        let n = socket.read(&mut buf).await?;
        if n == 0 {
            return Ok(());  // 连接关闭
        }
        socket.write_all(&buf[..n]).await?;
    }
}
```

这个 server 能轻松扛 10000 连接——因为每个 task 几 KB,Tokio worker 线程数默认等于 CPU 核数。

### 6.4 strace:看 socket syscall

```bash
# 跑 echo server,跟踪所有系统调用
strace -f ./target/debug/echo_server 2>&1 | grep -E 'socket|bind|listen|accept'

# 典型输出:
# socket(AF_INET, SOCK_STREAM, IPPROTO_TCP) = 3
# setsockopt(3, SOL_SOCKET, SO_REUSEADDR, ...) = 0
# bind(3, {sa_family=AF_INET, sin_port=htons(7878), sin_addr=inet_addr("127.0.0.1")}, 16) = 0
# listen(3, 1024) = 0
# accept4(3, ...) = 4
```

读懂:
- `socket(AF_INET, SOCK_STREAM, ...)`:AF_INET = IPv4,SOCK_STREAM = TCP(对比 SOCK_DGRAM = UDP)。
- `SO_REUSEADDR`:允许 bind 到刚关闭还 TIME_WAIT 的端口。Server 重启必备。
- `bind`:绑到 `127.0.0.1:7878`。
- `listen(3, 1024)`: backlog 1024,内核排队的"未完成握手 + 已完成握手待 accept"的连接数上限。
- `accept4`:Linux 增强版 accept,accept 的同时设 flags(如 nonblock)。

---

## 7 · NAT 穿透:P2P 联机的核心难题

### 7.1 NAT 是什么

NAT(Network Address Translation)在家用路由器上跑。家里所有设备用 `192.168.1.x` 内网 IP,路由器对外只有一个公网 IP(比如 `1.2.3.4`)。

设备 A(`192.168.1.5`)访问 `8.8.8.8:443`:
1. A 发包:`src=192.168.1.5:50000, dst=8.8.8.8:443`。
2. 路由器拦截,改成:`src=1.2.3.4:60000, dst=8.8.8.8:443`。**源 IP 和源端口都改了**。路由器内部记下:"我用 60000 端口代表 A 的 50000 端口"。
3. 8.8.8.8 收到,看到的是 `1.2.3.4:60000`。它不知道 A 的存在。
4. 回包走相反流程。

NAT 让 IPv4"够用"——一台家庭所有设备共用一个公网 IP。

**NAT 的破坏性**:外部**主动**无法连接内部。外面某机器想连你的 A(`192.168.1.5`),它发的包只能到路由器的公网 IP(`1.2.3.4`)。路由器不知道往内网哪转——内部没人主动发起过连接,没有映射表项。**包被丢弃**。

这就是为什么你不能在家开 server 让外网直接连——你的 IP 是 `192.168.1.5`,公网根本路由不到。

### 7.2 NAT 的四种类型

RFC 3489 定义 NAT 行为类型,从易到难穿透:

**Full-cone(全锥)**:最简单。内部 A 发出去后,任何外部都能用同一个 (公网IP, 公网端口) 联系 A。极少见。

**Restricted-cone(限制锥)**:只允许 A **主动联系过**的外部 IP 回包。常见家用 NAT 的 80% 是这种。

**Port-restricted-cone(端口限制锥)**:还限制端口——A 联系过 `8.8.8.8:443`,只允许 `8.8.8.8:443` 回,`8.8.8.8:80` 不行。

**Symmetric(对称)**:最严格。A 对不同目标用**不同的公网端口**。A → B 走端口 60000,A → C 走端口 60001。**几乎无法打洞**。

打洞能否成功,取决于双方 NAT 类型的组合:
- 都是 full-cone:能。
- 一个 cone 一个 symmetric:有时能。
- 都 symmetric:不能,要 TURN 中转。

### 7.3 STUN:发现自己的公网 IP/端口

STUN(Session Traversal Utilities for NAT)服务器公网部署。客户端 A 给 STUN 发包,STUN 回"我看到你的源 IP 和端口是 X:Y"——这就是 A 的 NAT 给它分配的公网映射。

```
A (内网) → NAT (改源 IP/端口) → STUN
STUN 回:"你从 1.2.3.4:60000 来的"
A 现在知道自己的公网映射是 1.2.3.4:60000
```

### 7.4 TURN:实在不行就中转

TURN(Traversal Using Relays around NAT)。如果打洞失败(NAT 太严格),两方都连 TURN 服务器,TURN 把 A 的包转给 B,B 的包转给 A。

TURN 是退路——它要消耗服务器带宽(每个连接一对流量),所以收费(Google / Twilio 提供 STUN 免费,TURN 收费)。

Google 公共 STUN:`stun.l.google.com:19302`。

### 7.5 ICE:组合拳

ICE(Interactive Connectivity Establishment)是 WebRTC 的核心,自动尝试所有可能的连接方式:

1. 收集"候选地址":本地 IP、STUN 给的公网 IP、TURN 中继地址。
2. 两方交换候选(通过信令服务器,通常 HTTP)。
3. 两两配对尝试连,谁先成功用谁。
4. 倾向于 P2P(STUN),不行用 TURN。

工业级实现:**WebRTC** 内置 ICE,libnice(GStreamer 用),Pion(Go),aiortc(Python)。Rust 生态有 str0m 和 webrtc-rs。

**游戏场景**:两人《Minecraft》联机,hamachi、zero tier、Tailscale 这类 VPN 工具本质是 STUN/TURN 的简化版。

---

## 8 · DNS:从域名到 IP

### 8.1 为什么有 DNS

人记得住 `google.com`,记不住 `142.250.80.46`。DNS(Domain Name System)把域名翻译成 IP。

DNS 是**分布式数据库**——没有一台机器存所有域名。查询从根服务器开始,层层委托。

```
浏览器输 google.com
  ↓ 问本地 DNS resolver(你家路由器 / ISP DNS / 8.8.8.8)
本地 resolver 缓存里有?
  - 有:直接返回 IP
  - 没有:问根服务器(.)
根服务器说:"问 .com 的 TLD 服务器"
.com TLD 说:"问 google.com 的权威服务器"
google.com 权威服务器说:"IP 是 142.250.80.46"
resolver 缓存这个结果(TTL 3600 秒),返回给浏览器
```

整个查询可能要 4 步,但通常 < 50ms(因为 resolver 缓存)。第一次访问某域名慢,后面快。

### 8.2 DNS 记录类型

- **A**:域名 → IPv4 地址。`example.com. A 93.184.216.34`
- **AAAA**:域名 → IPv6 地址。
- **CNAME**:别名。`www.example.com CNAME example.com`。
- **MX**:邮件服务器。`example.com MX mail.example.com`。
- **TXT**:任意文本。常用于 SPF / DKIM / 域名验证。
- **NS**:这个域的权威服务器。
- **SOA**:Start of Authority,域名主信息。

### 8.3 dig 命令

```bash
# 查 IP
dig example.com
dig +short example.com         # 只输出 IP

# 指定记录类型
dig MX gmail.com +short
dig NS github.com +short

# 看完整解析过程
dig +trace google.com
# 输出会显示从根 → TLD → 权威的每一步

# 指定 resolver
dig @8.8.8.8 example.com       # 用 Google DNS
dig @1.1.1.1 example.com       # 用 Cloudflare DNS
```

### 8.4 /etc/resolv.conf 和 /etc/hosts

```bash
cat /etc/resolv.conf
# nameserver 192.168.1.1
# nameserver 8.8.8.8

cat /etc/hosts
# 127.0.0.1   localhost
# ::1         localhost
# 你可以加自定义条目:
# 192.168.1.10  mygame.local
```

`/etc/hosts` 优先级**最高**——查询 DNS 之前先查它。可以用来屏蔽广告(`0.0.0.0 ads.com`)或本地开发(`127.0.0.1 myapp.test`)。

### 8.5 DNS 的游戏应用

游戏 server 发现:玩家开"多人游戏",client 查 `play.example.com` 得到 server IP。如果 server 是动态 IP,用 DDNS(动态 DNS)。

工业级:Steam / Epic 不用 DNS 发现,用他们自己的"lobby 服务"。但 lobby 服务的 IP 仍走 DNS。

---

## 9 · TLS:加密 + 认证

### 9.1 为什么需要 TLS

裸 TCP 传输的所有数据,中途任何路由器 / ISP 都能看 / 改。HTTP 明文密码、cookies 全暴露。

TLS(Transport Layer Security)在 TCP 上加:
1. **加密**:中途看不到内容。
2. **完整性**:中途改一点,接收方察觉。
3. **认证**:你连的 `google.com` 真的是 Google,不是 ISP 劫持的钓鱼站。

### 9.2 TLS 握手(简化版)

```
客户端                                            服务端
  | --- ClientHello --->
  |     (支持的加密套件、TLS 版本、随机数 A)
  |
  | <--- ServerHello ---
  |     (选定套件、TLS 版本、随机数 B)
  | <--- Certificate ---
  |     (服务端的 X.509 证书,含公钥)
  | <--- ServerHelloDone ---
  |
  | --- ClientKeyExchange --->
  |     (用服务端公钥加密的 pre-master secret)
  | --- ChangeCipherSpec --->
  | --- Finished (加密) --->
  |
  | <--- ChangeCipherSpec ---
  | <--- Finished (加密) ---
  |
  |       双方用 pre-master + 随机数 A + B 派生出会话密钥
  |       之后所有数据用这个密钥对称加密
```

握手需要 2 个 RTT(TLS 1.2)。TLS 1.3 简化到 1 个 RTT,还支持 0-RTT 重连(resumption)。

**关键**:
- 非对称加密(RSA / ECDHE)只在握手用——慢但能解决"密钥交换"问题。
- 握手后双方共享一个会话密钥,用对称加密(AES-GCM / ChaCha20-Poly1305)——快。

### 9.3 证书链

服务端的证书不是凭空被信任的。证书是**证书链**:

```
根 CA(Root CA,自签名,预装在 OS / 浏览器里)
  ↓ 签发
中间 CA(Intermediate CA)
  ↓ 签发
你的网站证书(example.com)
```

客户端验证时:
1. 拿到 example.com 的证书,看它的签发者是 Intermediate CA。
2. 拿到 Intermediate CA 的证书,看它的签发者是 Root CA。
3. Root CA 在 OS 的 trust store 里(自签名,系统信任)。
4. 链条验证,所有签名都对 → 证书可信。

```bash
# 看 example.com 的证书链
openssl s_client -connect example.com:443 -showcerts < /dev/null 2>/dev/null | head -100

# 用 curl 看握手详情
curl -v https://example.com 2>&1 | head -30
# 输出例:
# * TLSv1.3 (IN), TLS handshake, Server hello (2):
# * SSL connection using TLSv1.3 / TLS_AES_256_GCM_SHA384
# * Server certificate:
# *  subject: CN=example.com
# *  start date: Jan 30 00:00:00 2024 GMT
# *  expire date: Mar  1 23:59:59 2025 GMT
# *  subjectAltName: host "example.com" matched cert's "example.com"
# *  issuer: C=US; O=Let's Encrypt; CN=R3   ← 中间 CA
```

### 9.4 自己签证书:本地开发

```bash
# 生成本地自签证书
openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout key.pem -out cert.pem -days 365 \
    -subj "/CN=localhost" \
    -addext "subjectAltName=DNS:localhost"

# 跑 HTTPS server
python3 -m http.server 443 --cert cert.pem --key key.pem
# 或者用 Rust 的 axum / hyper

# 浏览器会警告"自签证书不可信",你点"高级 → 继续"。
```

生产环境用 **Let's Encrypt**:免费、自动续期。`sudo pacman -S certbot`,`sudo certbot certonly --standalone -d yourdomain.com`。

---

## 10 · HTTP:应用层最常用协议

### 10.1 HTTP/1.1:文本协议

HTTP/1.1 是文本协议——你能用 `telnet` 直接手写 HTTP 请求:

```
GET /index.html HTTP/1.1
Host: www.example.com
User-Agent: my-telnet-client
[空行]
```

服务端回:

```
HTTP/1.1 200 OK
Content-Type: text/html
Content-Length: 1256

<html>...</html>
```

请求行 + 头部 + 空行 + body。每个请求一个 TCP 连接(慢)。HTTP/1.1 加了 `Connection: keep-alive`,一个 TCP 连接发多个请求。

**HTTP/1.1 的问题**:
- **队头阻塞(HoL)**:同连接上的请求必须按顺序响应。请求 1 慢,请求 2 即使处理好了也要等。
- **多连接**:浏览器绕过 HoL,对同一域名开 6 个并发 TCP 连接。每个连接握手慢。
- **头大**:每次请求都带完整 header,几百字节起。Cookie 一多就上 KB。

### 10.2 HTTP/2:二进制分帧 + 多路复用

2015 年标准化。HTTP/2 把请求/响应**分帧**,每个帧带 stream ID。一个 TCP 连接上多个 stream 并发收发——**多路复用**。

```
TCP 连接
├── Stream 1: 请求 A
├── Stream 3: 请求 B
├── Stream 5: 请求 C
└── ...
帧交错传输,接收方按 stream ID 重组
```

加上头压缩(HPACK),头重复字段只传一次。服务器 push(已废弃)。

**HTTP/2 的问题**:还在 TCP 上。TCP 不知道多 stream,**整个 TCP 连接**有 HoL——一个 stream 的包丢了,所有 stream 都等。

### 10.3 HTTP/3:QUIC over UDP

2022 年标准化。HTTP/3 跑在 **QUIC** 上,QUIC 跑在 **UDP** 上。

QUIC(Quick UDP Internet Connections)是 Google 设计的"现代 TCP",但跑在 UDP 上。原因:
1. **流级别独立**:QUIC 内置多 stream,一个 stream 丢包不影响其他 stream——解决了 TCP HoL。
2. **0-RTT 握手**:第二次连接同一 server,第一个包就能带数据(对比 TCP + TLS 1.3 至少 1 RTT)。
3. **连接迁移**:手机从 WiFi 切 4G,IP 变了,TCP 连接断了。QUIC 用 Connection ID 标识连接,IP 变了连接不断。
4. **用户态实现**:内核 TCP 慢演化(要内核升级),QUIC 在用户态,迭代快。

代价:UDP 在某些网络(企业防火墙)被限速;CPU 比内核 TCP 高(在用户态做);防火墙不熟悉 UDP 流量。

```bash
# 看 Google 是不是支持 HTTP/3
curl -I --http3 https://www.google.com
# 或
curl -sI https://www.cloudflare.com | grep -i alt-svc
# 输出: alt-svc: h3=":443"; ma=86400
# 表示"我也支持 HTTP/3 over UDP 443"
```

### 10.4 WebSocket:在 HTTP 之上做双向

HTTP 是请求-响应(单向)。WebSocket 协议:HTTP 升级握手 → 成功后变成全双工长连接。

```
客户端 → 服务端:
GET /chat HTTP/1.1
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Key: ...

服务端 → 客户端:
HTTP/1.1 101 Switching Protocols
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Accept: ...

(之后这条 TCP 连接就是 WebSocket 了,双方随时互发 frame)
```

WebSocket 用于聊天、实时通知、多人游戏(网页游戏)。但**对游戏不是最优**——它跑在 TCP 上,有 HoL 问题。

**WebSocket vs WebRTC**:WebRTC 跑 UDP,适合实时游戏。WebSocket 跑 TCP,适合聊天 / 回合制。

```rust
// Rust WebSocket 例子(用 tungstenite crate)
// Cargo.toml: tungstenite = "0.21"
use tungstenite::{accept, Message};
use std::net::TcpListener;

fn main() -> std::io::Result<()> {
    let server = TcpListener::bind("127.0.0.1:9001")?;
    for stream in server.incoming() {
        let mut ws = accept(stream?).unwrap();
        loop {
            let msg = ws.read().unwrap();
            if msg.is_text() {
                ws.send(Message::text(format!("echo: {}", msg))).unwrap();
            }
        }
    }
    Ok(())
}
```

---

## 11 · 实战:Rust + tokio 的网络栈

把所学拼起来。我们做一个**多人游戏的最小骨架**——位置同步 server + client。

### 11.1 server 端

```toml
[package]
name = "mini-game-server"
version = "0.1.0"
edition = "2021"

[dependencies]
tokio = { version = "1", features = ["full"] }
serde = { version = "1", features = ["derive"] }
bincode = "1"
```

```rust
// src/main.rs
use tokio::net::UdpSocket;
use std::collections::HashMap;
use std::net::SocketAddr;
use serde::{Serialize, Deserialize};

#[derive(Serialize, Deserialize, Debug, Clone)]
struct PlayerState {
    player_id: u32,
    x: f32,
    y: f32,
}

#[derive(Serialize, Deserialize, Debug)]
enum Packet {
    Join { name: String },
    State { you: PlayerState, others: Vec<PlayerState> },
    Input { dx: f32, dy: f32 },
}

#[tokio::main]
async fn main() -> tokio::io::Result<()> {
    let socket = UdpSocket::bind("0.0.0.0:3478").await?;
    println!("Game server on UDP 3478");
    
    let mut players: HashMap<SocketAddr, PlayerState> = HashMap::new();
    let mut next_id: u32 = 1;
    let mut buf = [0u8; 1024];
    
    loop {
        let (n, src) = socket.recv_from(&mut buf).await?;
        let Ok(pkt) = bincode::deserialize::<Packet>(&buf[..n]) else { continue };
        
        match pkt {
            Packet::Join { name } => {
                let id = next_id;
                next_id += 1;
                let state = PlayerState { player_id: id, x: 0.0, y: 0.0 };
                println!("Player '{}' joined from {} as id {}", name, src, id);
                players.insert(src, state);
            }
            Packet::Input { dx, dy } => {
                if let Some(p) = players.get_mut(&src) {
                    p.x += dx;
                    p.y += dy;
                }
            }
            Packet::State { .. } => {} // client 不应该发这个
        }
        
        // 广播所有人状态给所有人
        let all_states: Vec<PlayerState> = players.values().cloned().collect();
        for (addr, my_state) in &players {
            let others: Vec<PlayerState> = all_states.iter()
                .filter(|p| p.player_id != my_state.player_id)
                .cloned()
                .collect();
            let response = Packet::State { you: my_state.clone(), others };
            let bytes = bincode::serialize(&response).unwrap();
            let _ = socket.send_to(&bytes, addr).await;
        }
    }
}
```

### 11.2 client 端

```rust
// src/client.rs
use tokio::net::UdpSocket;
use serde::{Serialize, Deserialize};

#[derive(Serialize, Deserialize, Debug, Clone)]
struct PlayerState { player_id: u32, x: f32, y: f32 }

#[derive(Serialize, Deserialize, Debug)]
enum Packet {
    Join { name: String },
    State { you: PlayerState, others: Vec<PlayerState> },
    Input { dx: f32, dy: f32 },
}

#[tokio::main]
async fn main() -> tokio::io::Result<()> {
    let socket = UdpSocket::bind("0.0.0.0:0").await?;
    socket.connect("127.0.0.1:3478").await?;
    
    // 加入
    let join = bincode::serialize(&Packet::Join { name: "Alice".into() }).unwrap();
    socket.send(&join).await?;
    
    let mut buf = [0u8; 1024];
    loop {
        let n = socket.recv(&mut buf).await?;
        if let Ok(Packet::State { you, others }) = bincode::deserialize::<Packet>(&buf[..n]) {
            println!("Me: ({:.1}, {:.1})  Others: {}", you.x, you.y, others.len());
        }
        
        // 模拟一个移动输入
        let input = bincode::serialize(&Packet::Input { dx: 0.1, dy: 0.0 }).unwrap();
        socket.send(&input).await?;
    }
}
```

跑:
```bash
# Terminal 1
cargo run --bin mini-game-server

# Terminal 2
cargo run --bin client

# Terminal 3(再开一个 client)
cargo run --bin client
```

你会看到 client 的位置在动,两边互相看见。

### 11.3 用 tcpdump 抓包验证

```bash
# 抓 UDP 3478 的包
sudo tcpdump -i lo -n udp port 3478 -X

# -i lo: 回环接口(本机)
# -n: 不解析 DNS
# -X: 打印 hex 内容
# 你会看到客户端发的包和服务端回的包,二进制内容
```

用 wireshark 更直观:`sudo wireshark`,选 lo 接口,filter `udp.port == 3478`,看见每个包的 hex dump,以及 bincode 序列化的字节。

### 11.4 用 ss 看连接

```bash
ss -u -a -n | grep 3478
# u = UDP, a = 所有, n = 不解析
# 输出例:
# UNCONN  0  0  0.0.0.0:3478  0.0.0.0:*
```

---

## 12 · 四域深入

### 12.1 游戏编程视角

游戏网络的工业级方案:

**Lockstep(锁步)**:所有客户端按相同 tick 推进,每个 tick 互相发"我这一帧的输入"。优点: deterministic,服务器只转发,负载低。缺点:任何一人慢,所有人等。**RTS 用**(《星际争霸》《帝国时代》)——单位多,只发输入省带宽。

**State synchronization(状态同步)**:server 维护权威状态,定期广播给所有人。**FPS 用**(《CS:GO》《守望先锋》)——动作多,玩家位置实时变。

**Rollback netcode(回滚)**:格斗游戏(《街霸》《罪恶装备》)、《Mortal Kombat》。本地预测:你按键立刻在本地生效,同时把输入发对方。等对方输入回来,如果和你预测的一致,无事;不一致,回滚到过去状态,用正确输入重新模拟。看起来"先斩后奏"——延迟极低,但回滚时画面会闪一下。

工业级库:
- **Photon**(Unity / 自研引擎商用)
- **Mirror**(Unity 开源)
- **Nakama**(开源,跨引擎)
- **Steam Networking**(Steam 内置,免费,Lobby + relay + ICE)

Rust 生态:
- **renet**(Rust 网络库,server-authoritative)
- **bevy_renet**(bevy 集成)
- **naia**(Rust + 多语言客户端)

### 12.2 图形学视角

图形程序员很少直接碰网络。但有几处交集:
- **纹理 / 资源流送**:开放世界游戏边玩边下资产,需要稳定带宽 + 优先级队列。
- **云渲染**(NVIDIA GeForce Now / Xbox Cloud Gaming):视频流到客户端,延迟 < 50ms 才能玩。用 WebRTC(基于 UDP)。
- **多人协作白板**(Figma / Miro):WebSocket + CRDT。
- **远程 GPU 渲染**(Blender / Unreal Remote):同样基于 WebRTC。

### 12.3 Linux 系统编程视角

Linux 内核网络栈是性能优化的战场。关键调优点:

```bash
# 看 socket buffer 大小
sysctl net.core.rmem_max        # 接收 buffer 最大(字节)
sysctl net.core.wmem_max        # 发送 buffer 最大
# 默认 212992,高吞吐 server 设到 16MB:
sudo sysctl -w net.core.rmem_max=16777216
sudo sysctl -w net.core.wmem_max=16777216

# TCP 缓冲(每个 socket)
sysctl net.ipv4.tcp_rmem        # min default max
sysctl net.ipv4.tcp_wmem

# 启用 BBR
sudo sysctl -w net.ipv4.tcp_congestion_control=bbr

# 永久生效,写 /etc/sysctl.d/99-network.conf:
# net.core.rmem_max=16777216
# net.ipv4.tcp_congestion_control=bbr
# 然后 sudo sysctl --system
```

工具:
- **iperf3**:测带宽。`iperf3 -s`(server), `iperf3 -c server_ip`(client)。
- **mtr**:持续 traceroute。
- **tcpdump**:命令行抓包。
- **wireshark**:GUI 抓包分析。
- **ngrep**:在包里 grep 字符串。
- **ss / netstat**:看连接状态。
- **nmap**:端口扫描。
- **curl**:HTTP 测试。

### 12.4 Rust 生态视角

Rust 网络库分层:

**底层**:
- `std::net`:阻塞 socket,标准库。
- `tokio::net`:异步 socket,Tokio 运行时。
- `mio`:Tokio 底层的事件循环,直接用 epoll。
- `socket2`:更底层的 socket API,可以设 SO_REUSEPORT 等高级选项。

**应用层 HTTP**:
- `hyper`:HTTP/1.1 + HTTP/2,client + server。Tokio 生态基石。
- `reqwest`:基于 hyper 的"易用 HTTP client"(类似 Python requests)。
- `axum`:基于 hyper 的 web 框架,Tokio 团队出品。
- `actix-web`:actor 模型的 web 框架,性能强。

**WebSocket**: `tungstenite`(同步)、`tokio-tungstenite`(异步)。

**TLS**:`rustls`(纯 Rust 实现,默认安全)、`native-tls`(用 OpenSSL,兼容性好)。

**QUIC / HTTP/3**:`quinn`(主流 QUIC 实现)、`h3`(HTTP/3)。

**游戏网络**:`renet`(state sync)、`naia`、`ggrs`(rollback)、`message-io`(轻量)。

---

## 13 · 认知地图

### 13.1 上级

- **分布式系统**:网络是分布式系统的"传输介质"。CAP 定理、共识算法(Raft / Paxos)都假设有网络。
- **网络安全**:TLS / mTLS / OAuth / JWT,都建立在今天讲的基础之上。
- **云计算**:AWS / GCP / Azure 提供 VPC(虚拟私有云) = OSI 第 3 层。Load Balancer = 第 4 层(L4)或第 7 层(L7)。

### 13.2 同级

| 主题 | 关系 |
|---|---|
| 进程间通信(IPC) | 单机 vs 网络。socket 既算 IPC(localhost)也算网络。 |
| 并发(本系列 25-concurrency) | 网络高并发 = 大量并发连接,要异步 IO。 |
| 性能(本系列 24-memory) | 网络栈性能受 CPU cache、内存带宽影响。 |

### 13.3 下级

- socket syscall:`socket` / `bind` / `listen` / `accept` / `connect` / `send` / `recv` / `sendto` / `recvfrom` / `close`
- epoll / kqueue / IOCP:OS 提供的多路复用 API
- TCP 状态机:11 个状态(LISTEN / SYN_SENT / ESTABLISHED / ... / TIME_WAIT)
- IP header 字段:version / IHL / TTL / protocol / src / dst / ...
- IPv6 扩展头:Hop-by-Hop / Routing / Fragment / ...

---

## 14 · 对照与变奏

### 14.1 跨语言网络 API

**C / POSIX**:`socket()`, `bind()`, `listen()`, `accept()` —— 原始 syscall,所有语言底层。

**Python**:`socket` 标准库(几乎 1:1 对应 C API);`asyncio` 异步(类似 Tokio)。

**Go**:`net` 标准库内置 goroutine-friendly socket,自动非阻塞。**Go 的网络是工业级标杆**。

**Node.js**:libuv 提供异步 IO,事件驱动。

**Rust**:`std::net`(阻塞)+ `tokio::net`(异步)+ `mio`(底层)。Rust 的"零成本抽象"在这里特别明显——异步代码看起来像同步,性能和手写 epoll 一样。

### 14.2 网络协议演化史

- 1969:ARPANET,第一个包交换网络。
- 1974:TCP/IP 论文(Vint Cerf / Bob Kahn)。
- 1983:TCP/IP 成为主流(被称为"Internet 的生日")。
- 1989:Tim Berners-Lee 提出 WWW。HTTP/0.9。
- 1995:HTTP/1.0。
- 1997:HTTP/1.1(keep-alive,主流 20 年)。
- 2009:Google 提出 SPDY(HTTP/2 雏形)。
- 2013:Google 提出 QUIC。
- 2015:HTTP/2 标准化。
- 2021:QUIC 标准(RFC 9000)。
- 2022:HTTP/3 标准化。

每一步都在解决前一代的瓶颈。HTTP/4 会是什么?可能内置 WebTransport / WebCodecs,游戏 / 视频会议全面 web 化。

### 14.3 互联网的中立性争议

网络不是单纯技术——它嵌入政治经济。"网络中立性"(net neutrality):ISP 应平等对待所有流量,不能为某些服务加速 / 减速。美国 2015 通过、2017 废除、可能再通过。游戏延迟对这个特别敏感——如果 Comcast 和 Netflix 合作减速 Amazon Prime Video 流量,顺便可能也影响你跑在 AWS 上的游戏 server。

---

## 15 · 关联 Day

- **铺垫**:[day020-network-socket.md](../phase-1/day020-network-socket.md)(假设,未来加)—— Rust socket 实操
- **当天**:[23-network-foundation.md](23-network-foundation.md)(本篇)
- **后续**:[24-memory-foundation.md](24-memory-foundation.md)—— 网络性能受 cache 影响;[25-concurrency-foundation.md](25-concurrency-foundation.md)—— 高并发 = 异步 IO + 协程;[day150-networked-game.md](../phase-6/day150-networked-game.md)(假设)—— 第一个真正的多人游戏

---

## 16 · 变式训练

### Lv1 · 概念辨析

**题**:为什么 TCP 三次握手不能两次?为什么挥手要四次?

**参考答案**:

两次握手的问题:**历史僵尸 SYN**。如果 A 之前发的 SYN 因为网络延迟几秒后才到 B,B 回 SYN+ACK 就以为连接建立了,占着资源等 A 发数据,但 A 早就忘了。第三次握手让 A 验证"我确实现在想连",僵尸 SYN 时 A 会回 RST 而不是 ACK,B 清理资源。

四次挥手是因为 TCP 全双工——两个方向独立关。A 发 FIN 表示"我没数据了",但 B 可能还有数据要发,所以先回 ACK,等 B 也发完了再发 FIN,A 最后回 ACK。中间 ACK 和 FIN 之间 B 还能发,叫 half-close。

### Lv2 · 动手实践

**题**:用 Rust + tokio 写一个 UDP echo server 和 client。要求:
1. server 监听 `0.0.0.0:9999`
2. client 从命令行读字符串,发给 server
3. server 把字符串改成大写,回
4. client 收到后打印

**完成标准**:
- 两个终端能通信
- 用 `tcpdump -i lo udp port 9999 -X` 抓到包

**参考解答**:

server:
```rust
use tokio::net::UdpSocket;

#[tokio::main]
async fn main() -> tokio::io::Result<()> {
    let socket = UdpSocket::bind("0.0.0.0:9999").await?;
    println!("UDP echo server on 9999");
    let mut buf = [0u8; 1024];
    loop {
        let (n, src) = socket.recv_from(&mut buf).await?;
        let upper: Vec<u8> = buf[..n].iter().map(|b| b.to_ascii_uppercase()).collect();
        socket.send_to(&upper, src).await?;
    }
}
```

client:
```rust
use tokio::net::UdpSocket;
use std::io::{self, BufRead};

#[tokio::main]
async fn main() -> tokio::io::Result<()> {
    let socket = UdpSocket::bind("0.0.0.0:0").await?;
    socket.connect("127.0.0.1:9999").await?;
    
    let stdin = io::stdin();
    for line in stdin.lock().lines() {
        let line = line?;
        socket.send(line.as_bytes()).await?;
        let mut buf = [0u8; 1024];
        let n = socket.recv(&mut buf).await?;
        println!("{}", String::from_utf8_lossy(&buf[..n]));
    }
    Ok(())
}
```

### Lv3 · 迁移设计

**题**:你接手一个多人 Rust 游戏,用 TCP。玩家抱怨"卡"。你打开 wireshark,看到 RTT 80ms 但偶尔出现 500ms 的尖峰。设计一个改造计划,把 TCP 改 UDP + 自定义可靠层,要求:
- 重要事件(开枪、命中)可靠
- 不重要事件(玩家位置)不可靠,丢了就丢了
- 不引入第三方库(自研)

提示:
- 用 sequence number 标识每个包
- 重要包要 ACK + 重传(超时设多少?)
- 不重要包不带 ACK,接收方按 seq 排序去重
- 思考"如何处理重要包的 ACK 超时"
- 写一份 200 字的 RFC(给你的团队)

### Lv4 · 开源贡献

**题**:Tokio 是 Rust 异步生态的基石。`gh repo clone tokio-rs/tokio`,看 `tokio/src/net/mod.rs`,理解 TcpListener / UdpSocket 的实现。

1. 看 `TcpListener::accept` 怎么实现。它返回 `impl Future`,这个 Future 内部 poll 什么?
2. 看 tokio 怎么把 epoll 事件接到 async fn(找 `mio` 调用)。
3. 提一个 issue 或 PR:文档改进(比如某个例子缺失 / 错误)。

---

## 17 · Rust / Arch 落地清单

### 17.1 装工具

```bash
# 网络诊断
sudo pacman -S iproute2          # ip / ss
sudo pacman -S iputils           # ping / traceroute
sudo pacman -S mtr               # 综合 ping + traceroute
sudo pacman -S dnsutils          # dig / nslookup
sudo pacman -S tcpdump           # 命令行抓包
sudo pacman -S wireshark-qt      # GUI 抓包
sudo pacman -S ngrep             # 包内容 grep
sudo pacman -S nmap              # 端口扫描
sudo pacman -S socat             # "网络瑞士军刀"
sudo pacman -S iperf3            # 带宽测试

# Rust 网络栈
cargo install cargo-edit         # cargo add
# 在项目里:
# cargo add tokio --features full
# cargo add serde --features derive
# cargo add bincode
# cargo add rustls
# cargo add tokio-tungstenite
```

### 17.2 日常诊断

```bash
# 看本机 IP 和 MAC
ip -br addr                  # 简洁模式
ip -4 addr show eth0         # 详细

# 看 ARP / neighbor
ip neigh show

# 看路由
ip route
ip -6 route

# 看连接
ss -t                        # TCP 连接
ss -tlnp                     # listening + process
ss -u                        # UDP

# 看路由器路径
mtr 8.8.8.8

# 看端口被谁占
sudo ss -tlnp | grep 8080
sudo lsof -i :8080

# 测带宽
iperf3 -s                    # 服务端
iperf3 -c server_ip          # 客户端

# 测 HTTP
curl -w "@curl-format" -o /dev/null -s https://example.com
# curl-format 文件:
#     time_namelookup:  %{time_namelookup}\n
#        time_connect:  %{time_connect}\n
#     time_appconnect:  %{time_appconnect}\n
#    time_pretransfer:  %{time_pretransfer}\n
#       time_starttransfer:  %{time_starttransfer}\n
#                     ----------\n
#          time_total:  %{time_total}\n
```

### 17.3 抓包实战

```bash
# 抓 HTTP (lo)
sudo tcpdump -i lo -A -s0 'tcp port 80 and (((ip[2:2] - ((ip[0]&0xf)<<2)) - ((tcp[12]&0xf0)>>2)) != 0)'

# 抓 DNS
sudo tcpdump -i any -n port 53

# 抓 ICMP (ping)
sudo tcpdump -i any icmp

# 用 wireshark
sudo wireshark
# 选接口(lo / eth0 / wlan0),写 filter,点 start
# Filter 例:tcp.port == 443, http, dns, ip.addr == 8.8.8.8
```

### 17.4 性能调优

```bash
# 看当前 TCP 参数
sysctl net.ipv4.tcp_congestion_control
sysctl net.ipv4.tcp_rmem
sysctl net.ipv4.tcp_wmem
sysctl net.core.rmem_max
sysctl net.core.wmem_max
sysctl net.core.netdev_max_backlog

# 高性能 server 调优(写 /etc/sysctl.d/99-net-tune.conf)
cat <<'EOF' | sudo tee /etc/sysctl.d/99-net-tune.conf
net.core.rmem_max = 16777216
net.core.wmem_max = 16777216
net.ipv4.tcp_rmem = 4096 87380 16777216
net.ipv4.tcp_wmem = 4096 65536 16777216
net.ipv4.tcp_congestion_control = bbr
net.core.somaxconn = 4096
net.ipv4.tcp_max_syn_backlog = 4096
EOF
sudo sysctl --system

# 验证
sysctl net.ipv4.tcp_congestion_control
```

---

## 18 · Troubleshooting

**问题1**:两台机器同 WiFi,连不上。
诊断:`ping` 对方 IP。如果超时,看防火墙。Arch 默认没装防火墙,但若装了 `ufw`,`sudo ufw status`。或 `sudo iptables -L`。临时关:`sudo iptables -F`。server 程序 bind `0.0.0.0`,不要 `127.0.0.1`(后者只本机)。

**问题2**:server 能在本机用 `127.0.0.1` 连,但用本机内网 IP `192.168.1.5` 连不上。
原因:bind 到 `127.0.0.1` 而非 `0.0.0.0`。`127.0.0.1` 只监听 loopback,不接受其他网卡来的连接。
修复:bind `0.0.0.0`(IPv4 所有网卡)或 `::`(IPv6 + IPv4 dual-stack)。

**问题3**:跨 NAT 连不上(在家开 server 外网连)。
原因:NAT 后的 IP 公网无法直接路由。
解决:端口转发(路由器后台设置)、或用 ngrok / cloudflared tunnel、或用 Tailscale / ZeroTier 组虚拟内网。

**问题4**:WebSocket 老断。
原因:中间设备(企业防火墙、移动代理)超时杀空闲 TCP。
解决:应用层心跳(每 30 秒发个 ping)。

**问题5**:TLS 握手失败 "certificate verification failed"。
原因:证书过期、CN/SAN 不匹配、自签证书未在 trust store。
诊断:`openssl s_client -connect host:443 -servername host`,看错误。生产环境用 Let's Encrypt 续期。开发环境把 `cert.pem` 加到 client 的 trust store。

---

## 19 · 延伸阅读

本仓库本地资料:
- [day008.md](../phase-1/day008.md) — 早年的网络话题铺垫
- [22-signals-foundation.md](22-signals-foundation.md) — 信号基础,音频流同样考虑延迟
- [24-memory-foundation.md](24-memory-foundation.md) — 内存对网络性能的影响
- [25-concurrency-foundation.md](25-concurrency-foundation.md) — 异步 IO 的并发基础

外部稳定 URL:
- Beej's Guide to Network Programming:https://beej.us/guide/bgnet/
- The TCP/IP Guide:http://www.tcpipguide.com/
- RFC 791 (IPv4):https://www.rfc-editor.org/rfc/rfc791
- RFC 793 (TCP):https://www.rfc-editor.org/rfc/rfc793
- RFC 768 (UDP):https://www.rfc-editor.org/rfc/rfc768
- RFC 9000 (QUIC):https://www.rfc-editor.org/rfc/rfc9000
- Tokio Tutorial:https://tokio.rs/tokio/tutorial
- Rust Atomics and Locks(Mara Bos):https://marabos.nl/atomics/
- Glenn Fiedler's "Gaffer on Games" — 游戏网络系列:https://gafferongames.com/

真实开源源码:
- Tokio source:https://github.com/tokio-rs/tokio
- QUIC Quinn:https://github.com/quinn-rs/quinn
- WebRTC Rust:https://github.com/webrtc-rs/webrtc
- ENet:https://github.com/lsalzman/enet
- KCP:https://github.com/skywind3000/kcp
