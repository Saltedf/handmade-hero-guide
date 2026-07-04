
# 9E-4 · 匹配、NAT 穿透、中继与大厅

## 0 · 你给游戏加完联机,然后玩家说"我朋友就在隔壁,我们就是连不上"

你走完了 [09E-1](09E-1-reliable-udp-transport.md) 的可靠 UDP 传输,[09E-2](09E-2-authoritative-server-and-state-sync.md) 的权威服务器与状态同步,[09E-3](09E-3-interest-management-and-replication.md) 的兴趣管理与复制裁剪。你的 HH 项目现在能在两台机器之间跑一个像样的 2 人联机,你的 netcode 已经是工业级水准的一半了。你把 build 发给一个朋友试玩,他住在另一个城市。你给他一个 IP 地址加端口,让他 `./hh --connect 1.2.3.4:5000`。他试了一下,告诉你"连不上,超时"。

你以为是防火墙。你让他关掉 Windows Defender 防火墙,关掉路由器上的 SPI 防火墙,甚至把他的电脑放进 DMZ(暴露在公网)。还是连不上。你 ping 他的公网 IP,通;他 ping 你的,通。但你的游戏就是连不上他的游戏。你抓包(Wireshark),看到的是:你发出去的 UDP 包到了他的公网 IP,**然后被他的家用路由器无声地吞掉了**。包没到他的电脑,路由器根本没转发进来。

这就是 **NAT**(Network Address Translation,网络地址转换)问题。它影响大约 70% 的家庭互联网用户——也就是说,如果你的游戏不做 NAT 穿透,**七成玩家根本没法 P2P 互连**。你前 3 篇 9E 文章搭起来的整套 netcode——可靠 UDP、权威服务器、兴趣管理——**全部作废**,因为玩家连对方的机器都摸不到。这一篇讲的就是:为什么 NAT 会让两个家庭网络无法直连,以及工业上是怎么解决这个问题的——从 STUN 让你"看见"自己的公网地址,到 UDP hole punching 让两端"互相打洞",到 TURN 中继作为"花点钱总能跑通"的兜底,到 ICE 把这一切串成一个框架,再到 matchmaking 让两个陌生人**找到**彼此,最后到 Steam Networking Sockets 这种把上面所有东西打包好的工业方案。这一篇是 9E 序列的收尾——走完它,你就拥有了一套完整的、可以真的让两个陌生人在公网上玩起来的游戏网络后端。

## 1 · NAT 到底是什么,以及它为什么杀死了 P2P

要理解 NAT 为什么挡你的路,得先看一眼它是怎么来的。IPv4 地址只有 32 位,全世界最多 43 亿个,早就不够分了。但全世界的联网设备有几百亿台——手机、电脑、电视、冰箱、智能音箱,每台都要 IP。怎么解决?答案是:**你家所有设备共享一个公网 IP**。你的家用路由器从 ISP 那里拿到一个公网 IP(比如 `203.0.113.42`),然后它在内部用一个**私有网段**(`192.168.1.0/24` 是最常见的)给你的每台设备分一个**私有 IP**——你的电脑是 `192.168.1.100`,你的手机是 `192.168.1.101`,电视是 `192.168.1.102`。

当你的电脑访问一个公网服务器(比如打开 `https://example.com`)时,包从你的电脑发出,源地址是 `192.168.1.100:54321`(私有 IP + 一个临时端口),目的地是 `93.184.216.34:443`。这个包到了你的路由器,路由器做了一件事:它把这个包的**源地址**从 `192.168.1.100:54321` **改写成** `203.0.113.42:12345`——用路由器的公网 IP + 一个路由器自己分配的端口。然后路由器在心里记一张表:"我把内部 `192.168.1.100:54321` 映射到了外部 `203.0.113.42:12345`,这个映射是给目的地 `93.184.216.34:443` 用的"。包以改写后的源地址发出去,到达 example.com,example.com 回包到 `203.0.113.42:12345`,路由器查表,发现这个外部端口对应内部 `192.168.1.100:54321`,把**目的地址**改写回来,转发给你的电脑。这就是 NAT——**网络地址转换**。

这套机制对你上网浏览完全够用,因为浏览是**你主动出去连别人**——你的电脑先发包出去,路由器建立映射,回来的包就能找到回家的路。但 P2P 联机游戏要的是**双向主动连接**:你的朋友想**主动**连你,他要往你的公网 IP `203.0.113.42:5000` 发包。这个包到了你的路由器,路由器查它的映射表——**没有匹配的条目**。因为没有任何内部设备先从 `192.168.1.X:5000` 主动往外发过包,这张表里根本没有 `203.0.113.42:5000` 对应谁的记录。路由器的默认行为是:**丢弃这个包**。它不知道这个包该转给谁,而且从安全角度它也不应该乱转发——不然任何公网上的攻击者都能直接打到你的内网设备。

这就是为什么你的朋友连不上你。你的 `UdpSocket::bind("0.0.0.0:5000")` 只让你的电脑在**私有网络**上监听 5000 端口,你的路由器在外部**根本不知道** `203.0.113.42:5000` 该往哪转。朋友发来的包撞到路由器这堵墙,被丢掉,你的 socket 永远收不到。

到这里你可能会想:"那我让路由器做个**端口转发**(port forwarding),把外部 5000 端口固定转发到我的 `192.168.1.100:5000` 不就行了?" 对,如果你能登录路由器后台手动配置端口转发,确实能解决。但**你不能假设玩家会做这件事**。绝大多数玩家根本不知道路由器后台是什么,你的游戏不能要求他们去配置。而且很多人的网络环境(NAT 后面再套 NAT,运营商级 NAT/CGNAT)连配置端口转发都做不到——他们的"公网 IP"其实是运营商的 NAT 后地址,根本不是真正的公网。所以端口转发是**个人开发者自测用的 hack**,不是产品方案。你必须在不要求玩家碰路由器的前提下,让两个 NAT 后面的端点能互通。

## 2 · NAT 的几种类型:为什么有的能穿透,有的不能

NAT 不是铁板一块。RFC 3489 把 NAT 按行为分成了几种类型,从"容易穿透"到"几乎不可能穿透"排成一个光谱。理解这个光谱,是理解为什么后面 STUN 和 hole punching 对一部分人管用、对另一部分人不管用的关键。

最友好的叫 **full-cone NAT**(全锥形 NAT),也叫 "endpoint-independent mapping"。它的规则是:一旦路由器为内部 `192.168.1.100:54321` 建立了外部映射 `203.0.113.42:12345`,**任何外部主机**都可以通过往 `203.0.113.42:12345` 发包来打到这台内部设备,只要这个包带着正确的目的地址。换句话说,映射一旦建立,这个外部端口就是"对全世界开放的",路由器只看目的端口转发,不关心包来自哪里。这种 NAT 穿透最简单——只要有一个 STUN 服务器告诉你"你的外部映射是 `203.0.113.42:12345`",任何人往这个地址发包都能进来。

次友好的叫 **restricted-cone NAT**(限制锥形),它分两种:address-restricted(只看源 IP)和 port-restricted(同时看源 IP 和源端口)。它们的规则是:路由器只为内部设备**主动联系过**的那个外部地址(和端口)开放映射。比如你的电脑先往 STUN 服务器 `198.51.100.1:3478` 发过包,路由器建立的映射只接受**来自 `198.51.100.1`** (port-restricted 还要匹配端口 `3478`) 的回包。其它地址往这个外部端口发包,哪怕映射存在,也会被丢。这种 NAT 穿透难一点,但 UDP hole punching 仍然能搞定——下面会讲。

最难的是 **symmetric NAT**(对称 NAT)。前面三种(cone 类)有个共同点:**同一个内部端点**(比如 `192.168.1.100:54321`)**不管联系谁,外部映射的端口都是同一个**——也就是 `203.0.113.42:12345`,不管你联系的是 STUN 服务器、你的朋友,还是 example.com。symmetric NAT 不一样:它对**不同的外部目的地**分配**不同的外部端口**。你联系 STUN 服务器,路由器给你分配外部端口 `12345`;你联系你的朋友,路由器给你分配外部端口 `12346`;你联系 example.com,分配 `12347`。**外部端口取决于你联系谁**。

这个区别为什么致命?因为 hole punching 的核心 trick 是"用 STUN 查到自己对外暴露的端口,告诉对方,对方往这个端口发包打洞"。但 symmetric NAT 下,你查 STUN 得到的端口(比如 `12345`)只在"跟 STUN 通信"这个上下文里有效,**你跟朋友通信时用的是一个完全不同的端口**(`12346`)——而朋友根本不知道 `12346` 是什么,他只会往 STUN 告诉他的 `12345` 发包,包撞进来路由器一看"这不是 STUN 的端口,丢掉"。hole punching 失败。Symmetric NAT 是 P2P 的死敌,大约 15-25% 的家庭网络属于这一类(企业网络和移动运营商的 CGNAT 更常见),对这部分人,唯一可靠的方案是 TURN 中继——下面会讲。

判定自己 NAT 类型的方法,用 `nmap` 自带的 `ncat` 或者 Python 的 STUN 客户端测:

```bash
# Arch Linux 装一个 STUN 客户端
sudo pacman -S nmap
# 跑 STUN 测试(需要一个公共 STUN 服务器)
ncat --proxy-type socks5 --proxy 127.0.0.1:1080 -zv stun.l.google.com 19302
# 或者用专门的 STUN 客户端
pip install stun
python -c "import stun; print(stun.get_ip_info())"
# 输出里 ExternalIP/ExternalPort 就是 NAT 给你分配的外部映射
```

这条命令在 Arch 上跑出来,你能看到你自己的 NAT 行为——如果你的外部端口每次发包都变(联系不同 STUN 服务器时端口不同),你就是 symmetric NAT。这一节讲到这里你应该明白一件事:**NAT 不是单一现象,而是一个连续光谱**。09E-1..3 的 netcode 假设两端能直接发 UDP 互连,这一篇要解决的就是"光谱上不同位置的玩家怎么互通"。

## 3 · STUN:让你看见自己在外面长什么样

既然 NAT 的核心问题是"你不知道自己的公网地址是多少",那么第一个要解决的就是**让端点发现自己的公网映射**。这就是 **STUN**(Session Traversal Utilities for NAT,NAT 会话穿透工具)的作用。

STUN 的原理简单得几乎可疑。你在公网上部署一台 STUN 服务器(它有公网 IP,没有 NAT),你的游戏客户端给 STUN 服务器发一个 UDP 包。STUN 服务器收到这个包,**它看到的源地址是经过 NAT 改写后的公网地址**(`203.0.113.42:12345`)——因为包到了 STUN 服务器之前已经穿过了一层 NAT。STUN 服务器把这个"它看到的源地址"塞进一个回包里,发回给你的客户端。你的客户端收到回包,读出来:**"哦,我在外面看起来是 `203.0.113.42:12345`。"** 这就是 STUN 的全部魔法——它只是一个"镜子",让你看到 NAT 给你画的妆。

STUN 协议本身在 RFC 5389 定义,包格式是一个简单的二进制结构:消息类型(请求/响应/错误)、消息长度、magic cookie(`0x2112A442`,用来区分 STUN 流量和其它 UDP 流量)、事务 ID(96 位随机数,用来匹配请求和响应)、然后是一串属性(TLV 格式)。最重要的属性是 `MAPPED-ADDRESS` 或 `XOR-MAPPED-ADDRESS`——后者把地址跟 magic cookie XOR 一下,目的是避免某些"聪明"的路由器识别出这是 STUN 流量然后做手脚(实际上有些 NAT 厂商确实会识别 STUN 并破坏它,XOR 是一种简单的反制)。

STUN 解决了"发现自己公网地址"的问题,但它**本身不解决 NAT 穿透**。它只告诉你"你是谁",不告诉你"怎么让别人打进来"。把"知道自己的公网地址"变成"两端真的能互通",需要的是 UDP hole punching——下一节。

工业上,Google、Mozilla、Twilio 等公司都提供免费的公共 STUN 服务器,比如 `stun.l.google.com:19302`。这些服务器你白嫖没问题,但**生产游戏不要只依赖一个**——STUN 服务器挂了你的玩家就连不上。自己部署 2-3 台 STUN 服务器(AWS / Hetzner / 阿里云,各选一个区域)是工业 standard,部署成本极低(一台 STUN 服务器是纯无状态 UDP echo,几乎不耗 CPU 和带宽,5 美元/月的 VPS 足够撑几千个并发 STUN 查询)。

## 4 · UDP hole punching:让两个 NAT 互相打洞

现在你的客户端通过 STUN 知道了自己的公网地址(假设是 A:`203.0.113.42:12345`),对方客户端也通过 STUN 知道了自己的公网地址(假设是 B:`198.51.100.7:54321`)。两人怎么连?

直觉上,问题还在:A 往 B 的 `198.51.100.7:54321` 发包,B 的路由器没映射这个端口(对 B 来说,这个端口是"跟 STUN 通信"建立的,B 的路由器可能只允许 STUN 服务器的回包进来,不允许 A 的包进来——这取决于 NAT 类型)。B 往 A 发包也是一样。两边都在尝试,两边都被对方路由器丢。

**UDP hole punching** 的核心 trick 是:**让两端同时往对方"打洞"——也就是同时主动发包出去**,这样各自的 NAT 都会为"发给对方"建立一条映射,而这条映射建立之后,对方的包就能顺着这条映射进来。

具体流程是这样的。需要一个**第三方**——一个**rendezvous 服务器**(也叫 signaling server,信令服务器),它有公网 IP,两端都能连到它。流程:

第一步,A 和 B 都通过 STUN 查到自己的公网地址,然后各自把这个地址**注册到** rendezvous 服务器上,告诉它"我是 A,我的公网地址是 `203.0.113.42:12345`,我想连 B"。

第二步,rendezvous 服务器把 B 的公网地址 `198.51.100.7:54321` **告诉** A,把 A 的公网地址 `203.0.113.42:12345` **告诉** B。现在两端都知道对方的公网地址了。

第三步,**关键一步**:A 和 B **几乎同时**往对方的公网地址发 UDP 包。A 往 `198.51.100.7:54321` 发,B 往 `203.0.113.42:12345` 发。注意这两个包**大概率会被对方的 NAT 丢掉**——因为对方的 NAT 还没建立"接受来自这个地址"的映射。但这一步**真正的目的不是把包送到对方**,而是**让自己的 NAT 建立一条"发往对方"的映射**。

第四步,A 的 NAT 看到 A 往 `198.51.100.7:54321` 发了包,就在表里建立一条映射:"内部 `192.168.1.100:5000` ↔ 外部 `203.0.113.42:12345`,允许来自 `198.51.100.7:54321` 的回包"。同理,B 的 NAT 也建立了"允许来自 `203.0.113.42:12345` 的回包"的映射。

第五步,**洞打穿了**。现在 A 再往 B 发包,这个包到达 B 的 NAT,B 的 NAT 一查表:"哦,内部 B 主动联系过 `203.0.113.42:12345`,这个地址的包放进来",转发给 B。同理 B 往 A 发包也能进了。两个端点从此能直接 P2P 通信,rendezvous 服务器可以下线不管了。

这套流程对 **full-cone、restricted-cone、port-restricted-cone** 这三类 NAT 都有效(对 restricted 类要稍微多点耐心,因为第一次对发被丢是预期的,第二次对发就能进)。工业数据(根据 Google STUN 团队的统计)是:**大约 80-85% 的 NAT 对可以 hole punch 成功**——也就是说,绝大多数玩家能直连,这是 P2P 游戏可行的根本原因。

但对 **symmetric NAT** 失败。原因上一节讲过:symmetric NAT 给"发给 B"分配的外部端口,跟 STUN 看到的端口**不一样**。A 通过 STUN 拿到的自己端口是 `12345`(跟 STUN 通信的端口),但 A 联系 B 时 NAT 给 A 分配的是 `12346`。B 拿到的"A 的地址"是从 rendezvous 来的 `203.0.113.42:12345`,但 A 实际往外发包用的是 `12346`。B 往 `12345` 发包,A 的 NAT 说"这个端口是给 STUN 的,不是给 B 的,丢"。A 往 B 发包用的源端口是 `12346`,B 的 NAT 也不知道这个端口跟 B 有什么关系(因为 B 是 port-restricted 之类),丢。两边永远打不通。这一类 NAT 占 15-25%,必须靠 TURN 中继兜底。

## 5 · TURN:花点钱总能跑通的兜底中继

Hole punching 失败时,你得接受一个事实:**这两个端点没办法直连**。唯一的办法是**让一个第三方公网服务器做中转**——A 把包发给 TURN 服务器,TURN 服务器把包转发给 B,反向同理。这就是 **TURN**(Traversal Using Relays around NAT,围绕 NAT 用中继穿透)。

TURN 的本质是一个**应用层路由器**。TURN 服务器跑在公网上,A 和 B 都能连到它(因为它是公网的,NAT 不挡)。A 通过 STUN/TURN 协议在 TURN 服务器上"分配"一个 relayed address——一个 TURN 服务器上的端口,所有发到这个端口的包都会被转发回 A。A 把这个 relayed address 告诉 B(还是通过 rendezvous 服务器),B 同样在 TURN 上分配一个 relayed address。然后双方都往对方的 relayed address 发包,TURN 服务器在中间转发。

代价显而易见:**所有流量都经过 TURN 服务器**。这意味着 TURN 服务器的带宽是直连方案的双倍(每个包要收一次、发一次),而且**延迟变高**(包要绕 TURN 服务器一圈,A→TURN→B 而不是 A→B)。带宽成本是真金白银——一个 4 人 P2P 游戏,每人 100KB/s 上行,4 人就是 400KB/s 进 TURN、400KB/s 出 TURN,TURN 服务器实际吞吐 800KB/s × 4 路 = 3.2Mbps,单台服务器撑几十个 session 就到带宽上限了。所以 TURN 是整个方案里**最贵**的部分,生产部署要算清楚成本。

但 TURN 的好处是**它永远管用**。只要 TURN 服务器在公网、A 和 B 都能上网(哪怕各自的 NAT 是 symmetric、是 CGNAT、是公司防火墙),就一定能通过 TURN 中转。它是"花点钱但保证可用"的兜底层。WebRTC 的统计是:大约 10-20% 的连接最终需要 TURN 兜底,这个比例跟你的用户群有关(企业用户、移动网络用户比例越高,TURN 比例越高)。

TURN 协议本身在 RFC 8656 定义,跟 STUN 是同一家族(它复用了 STUN 的消息格式,只是在上面加了 `ALLOCATE`、`CREATE-PERMISSION`、`CHANNELBIND`、`SEND`、`DATA` 等 TURN 特有的方法)。TURN 还有个细节叫 **relay 之上的"伪直连"**——如果 TURN 服务器在转发过程中发现 A 和 B 实际上能直连(比如 A 后来换了网络,NAT 类型变了),TURN 协议允许客户端通过 TURN 服务器**协商**一个"直连尝试",如果成功就走直连,失败再回到 relay。这是个优化,生产实现里 eNAT、coturn 都支持。

TURN 服务器的开源实现最常用的是 **coturn**(`https://github.com/coturn/coturn`),C 写的,稳定、性能好、配置灵活。Arch 上直接装:

```bash
sudo pacman -S coturn
# 配置文件在 /etc/turnserver.conf
# 最小配置(监听公网 UDP,允许所有 IP 中转):
# listening-port=3478
# listening-ip=<你的公网 IP>
# relay-ip=<你的公网 IP>
# realm=yourgame.com
# user=gameuser:gamepass   # 静态凭证(生产用 time-limited token)
# 启动
sudo systemctl start coturn
```

部署一台 coturn 的成本:VPS 5-10 美元/月 + 带宽费用。带宽是主要成本,如果你的游戏需要 TURN 兜底的玩家多,带宽账单会快速上涨——这也是为什么大型游戏公司要么自建 TURN 集群(AWS 上 coturn 跑 K8s),要么直接用 Steam Networking 这种把 TURN 成本打包进 30% 抽成的方案。

## 6 · ICE:把 STUN + hole punching + TURN 串成一个框架

到这里你可能会问:"我怎么知道该用 hole punching 还是 TURN?总不能让玩家选吧。" 答案是 **ICE**(Interactive Connectivity Establishment,交互式连接建立,RFC 8445)——一个把上面所有方法**串成一个自动化的、按优先级尝试的框架**。

ICE 的思路是:不预测哪种方法管用,**让两端各自收集所有可能的"候选地址"(candidate),然后按优先级一个一个试,谁先成功用谁**。候选地址有几类:

第一类,**host candidate**(主机候选)——端点自己的内网地址,比如 `192.168.1.100:5000`。这只在两端**在同一个局域网**时有用(比如寝室里两台笔记本),但成本是零,ICE 总会收集。

第二类,**server-reflexive candidate**(服务器反射候选,简称 srflx)——通过 STUN 查到的公网映射地址,比如 `203.0.113.42:12345`。这是 hole punching 要用的地址。

第三类,**peer-reflexive candidate**(对端反射候选,prflx)——在 hole punching 过程中,端点收到的"对方实际发包用的地址"跟 srflx 不一样时(symmetric NAT 的特征),实时记录下来的地址。这种候选是动态发现的,有时候能撞运气打通。

第四类,**relayed candidate**(中继候选,relay)——通过 TURN 在 TURN 服务器上分配的转发地址。这是兜底。

ICE 把所有这些候选地址收集起来,**按优先级排序**(通常是 host > srflx > prflx > relay,因为越靠后成本越高),然后两端做一连串的 **connectivity check**——A 往 B 的每个候选地址发一个 STUN binding request,B 收到也回一个 response。如果某个配对(A 的某候选 ↔ B 的某候选)check 通过,就把它标记为"可用",选优先级最高的可用配对作为最终的通信路径。

ICE 的精妙之处在于它**不需要预先知道 NAT 类型**。它穷举所有可能,挨个试。所以不管你的 NAT 是 full-cone、restricted、port-restricted 还是 symmetric,ICE 都会找到一条路——前三种它通过 srflx 候选的 hole punching 走通,第四种它最终 fallback 到 relay 候选走 TURN。这是为什么 WebRTC、Steam Networking、所有现代 P2P 应用都用 ICE——它把"NAT 类型判定 + 选择穿透策略"这个复杂决策**消解成暴力枚举**,工程上无比健壮。

ICE 的代价是**连接建立慢**——它要尝试多个候选配对,每个 check 有超时(通常 100-500ms),最坏情况下要等好几秒才能确定走哪条路。游戏里这个延迟通常可接受(玩家点"加入游戏"等 2 秒不算什么),但如果你做快速匹配,要优化候选收集的并行度。

## 7 · Matchmaking 与 lobby:让两个陌生人找到彼此

NAT 穿透解决的是"两个**已知地址**的端点怎么互通",但联机游戏的第一个问题其实是:**两个陌生人怎么知道对方的存在**。你不能假设玩家互相认识、互相发 IP。你需要一个**matchmaking**(匹配)服务和一个 **lobby**(大厅)系统。

最简单的形态是一个**中央 matchmaking 服务器**。它的核心数据结构是一个"待匹配队列"——每个想玩的客户端连上来,告诉服务器"我想玩",服务器按某种规则(段位、地区、ping、等待时间)把合适的几个客户端配成一组,把这一组人的公网地址互相告诉对方(这就是上面 hole punching 流程里 rendezvous 服务器的角色),然后他们尝试直连。

matchmaking 的规则设计是一门学问。最基础的是**地区匹配**——把同一个地理区域的玩家配在一起(因为他们 ping 低)。这要求 matchmaking 服务器知道每个客户端的"地区",通常通过客户端连上来时报告的 IP 地理定位库(比如 MaxMind GeoIP)推断,或者客户端自己测到几个候选 region 服务器的 ping 然后报告最低的那个。**段位匹配**(skill-based matchmaking, SBMM)是另一个维度——把水平接近的玩家配在一起,避免新手被老手碾压。SBMM 用 ELO / Glicko / TrueSkill 之类的算法给每个玩家一个数值,匹配时找数值接近的。这两个维度(地区 + 段位)经常**冲突**——你地区匹配得很好但本地没同段位的,你等 30 秒后服务器会"放宽"段位要求,这叫 **matchmaking dilation**(匹配膨胀),是工业上平衡"等待时间"和"对局质量"的标准技巧。

**lobby 系统**是 matchmaking 的友好化包装。matchmaking 是"系统自动给你配人",lobby 是"玩家自己开房间,别人能看到房间列表,选一个加入"。lobby 服务器的核心数据结构是一个**房间列表**——每个房间有一个 ID、名字、当前人数、最大人数、地图、模式、密码(可选)、host 的地址。客户端可以"创建房间"(在服务器上注册一条)、"列房间"(查询当前所有房间)、"加入房间"(给 host 发连接请求)。lobby 适合"朋友约战"——你创建一个房间,把房间 ID 发给朋友,朋友输入 ID 直接进。

**session 管理**是 lobby 之上的另一层。一个 **session**(游戏会话)有一个全局唯一 ID,玩家通过这个 ID 加入。session 有状态——"等待开始"、"进行中"、"已结束"。matchmaking 配好一组人后,会创建一个 session,把这组人的地址写进去,然后通知他们"session X 已就绪,开始连接"。游戏过程中如果有人断线重连,他通过 session ID 找回原来的对局。session 状态最终要持久化(否则 matchmaking 服务器一重启所有对局都丢了),通常写进一个 KV 存储(Redis 是工业 standard,单 session 几十字节,百万级 session 用几 GB 内存)。

**dedicated server browser**(专用服务器浏览器)是 lobby 的另一种形态,适合"任何人都能开服"的游戏(比如 Minecraft、CS 社区服、Squad)。它跟 lobby 的区别是:host 不是普通玩家,而是一台**专用服务器**(dedicated server,通常是云上租的或社区托管的)。客户端连服务器浏览器的 API,获取当前所有在线的 dedicated server 列表(每个带 IP、端口、地图、当前人数、ping),客户端选一个直连。

这里引出一个根本的架构选择:**dedicated server 还是 peer-to-peer**。

## 8 · Dedicated server vs P2P:架构选型的根本权衡

如果你用 **dedicated server**(专用服务器)架构,你的游戏服务器跑在一台**公网服务器**上——它有公网 IP,没有 NAT,任何客户端都能直接连它。客户端不需要 hole punching,不需要 STUN/TURN,直接 `UdpSocket::connect("your-game-server.com:5000")` 就行。NAT 完全不是问题——因为客户端是**主动出去连**公网服务器,NAT 不挡出站流量。

dedicated server 架构的优势是全方位的:**NAT 不存在**(上面说了),**anti-cheat 友好**(server 是权威的,见 [09E-2](09E-2-authoritative-server-and-state-sync.md)),**host migration 容易**(host 掉线换一个服务器实例就行,不像 P2P host 掉线整个对局崩),**性能可预测**(服务器硬件是你控制的,不是玩家的破笔记本)。这也是为什么所有严肃竞技游戏(CS:GO、Valorant、LOL、Dota2、Overwatch)都用 dedicated server——P2P 的"任意一个玩家卡所有人都卡"在竞技场景里完全不可接受。

dedicated server 的代价是**钱**。你要租服务器。一台能跑 100 玩家的 dedicated server 大概 50-200 美元/月(取决于 CPU、内存、地理位置),全球覆盖要至少 6-10 个 region(北美东、北美西、欧洲西、欧洲东、南美、亚太东南、亚太东北、澳洲),每个 region 几台到几十台服务器。一个中型游戏(峰值几万在线)的服务器账单轻松到每月几万到几十万美元。这就是为什么 free-to-play 游戏的"免费"是有代价的——你看到的皮肤抽屉、battle pass,**很大一部分是在补贴服务器账单**。

**P2P** 架构(host 是某个玩家,其它玩家连 host)省下了这笔钱——没有 dedicated server,玩家自己的机器跑 simulation。但 P2P 的代价是上面所有 NAT 问题(host 在 NAT 后面,其它人连不上,要 STUN/TURN/ICE),以及 anti-cheat 弱(host 可以作弊改自己机器上的状态),以及 host migration 难(host 退出整个对局要么崩,要么复杂的迁移逻辑)。

工业上的实际选择通常是:**竞技游戏用 dedicated server**(NAT 不是问题、anti-cheat 关键、性能关键),**合作游戏 / 小成本独立游戏用 P2P + ICE**(省钱,NAT 问题靠 ICE 解决,anti-cheat 不那么关键因为是合作不是对抗)。你的 HH 项目如果做联机,推荐 P2P + ICE——一台 matchmaking/STUN/TURN 服务器(可以共用一台 VPS)就够撑早期玩家,等用户量上来再考虑 dedicated server 架构。Valve 的 Left 4 Dead 系列就是 P2P + 听牌的典范(合作游戏,host 是某个玩家,Valve 提供 Steam Relay 做穿透兜底),而 CS:GO 是 dedicated server(竞技,要 anti-cheat + 性能)。两种架构的适用场景完全不同。

## 9 · Steam Networking Sockets:工业级打包方案

到这里你应该能感觉到:**从零搭一套完整的 NAT 穿透 + matchmaking + relay 系统,工程量巨大**。STUN 服务器、TURN 服务器、rendezvous/signaling 服务器、matchmaking 服务器、lobby 服务、session 管理、ICE 实现——每一块都不简单,合起来少说 3-6 个月专职工程。对绝大多数独立游戏开发者,这是不可承受的成本。

好消息是:**已经有打包好的工业方案**,你不需要从零搭。最知名的是 Valve 的 **Steam Networking Sockets**(以及它的身份层 **Steam Networking Identity**)。

Steam Networking Sockets 给你的是一个看起来像普通 socket 的 API:`SNP_Connect`、`SNP_Send`、`SNP_Recv`,但它在底层**自动**做了你这一篇(以及 9E 前三篇)讲过的**所有事情**:

第一,**可靠 UDP 传输**——它内部实现了类似 09E-1 讲的序列号 + ACK + 重传 + 拥塞控制(而且 Valve 的实现比我们自己写的更精细,有基于 BBR 的拥塞控制、有 MTU 探测、有 packet-level 加密)。你 `SNP_Send(message, k_Reliable)` 就走可靠通道,`k_Unreliable` 就走不可靠通道,跟 09E-1 的多通道设计是同一个思路,只是它替你做好了。

第二,**NAT 穿透**——Steam Networking 内置 STUN + TURN + ICE。你的客户端连 Steam 后台,Steam 自动给你做 NAT 类型判定、candidate 收集、connectivity check。对称 NAT 自动 fallback 到 **Steam Relay**(Valve 自己运营的全球 TURN 网络,免费,因为你付了 30% Steam 抽成)。

第三,**加密**——每个连接默认端到端加密(Curve25519 密钥交换 + AES-GCM),你不需要自己写。这解决了"netcode 上的所有包都是明文,任何路由器能读"的问题(09E-1 我们没处理加密,留到了这一篇)。

第四,**身份与 matchmaking**——Steam Networking Identity 让你用 SteamID 作为玩家身份,Steam Lobby API 给你 lobby 系统(创建房间、列房间、加入、状态同步),Steam Matchmaking 给你 SBMM 框架。这套东西跟 Steam 平台深度集成,你不需要自己搭 matchmaking 服务器。

第五,**LAN discovery**——Steam 自动帮你做局域网游戏发现(广播 + 监听)。

类似的方案还有 **Epic Online Services**(EOS,Epic 提供的跨平台网络栈,免费,Fortnite 用它,跨 PC/主机/移动),**Photon**(商业 netcode 服务,按 MAU 收费,Unity 生态用得多),**Nakama**(开源 server,Go 写的,可自托管,适合 indie)。这些方案各有定位,但**它们的底层原理都一样**——都是上面 09E-1..4 讲的这套东西(可靠 UDP + NAT 穿透 + relay + matchmaking),只是包装程度和商业模式不同。

这里有一个微妙的点要拎出来:**你之所以现在能"用"Steam Networking,是因为你"懂"它**。如果你没走完 09E-1..3,你直接看 Steam Networking 的 API 会一头雾水——"为什么有 reliable 和 unreliable 两个 send flag?什么时候用哪个?为什么 connect 之后还要等好几百毫秒才真正能发数据?为什么有时候延迟突然飙高(那是因为 ICE 在 fallback 到 relay)?" 走完这一篇,你看 Steam Networking 文档时,每一个 API、每一个现象都能对应到你已经理解的概念上。这就是 9E 这条序列的价值——它不是让你"重复造轮子",而是让你**理解轮子**,然后在你需要做架构决策时(P2P 还是 dedicated?自建 relay 还是用 Steam Relay?开几个 STUN 服务器?)有能力做判断,而不是被文档牵着走。

Rust 里集成 Steam Networking 的 crate 是 `steamworks-rs`(`https://github.com/Noxime/steamworks-rs`),它 wrap 了 Steamworks SDK。EOS 也有 Rust binding(社区维护)。如果你做一款**只在 Steam 上发布的游戏**,Steam Networking 几乎是默认选择——它免费(包含在 30% 抽成里)、稳定、覆盖所有 Steam 玩家、跨平台。

## 10 · 在你 HH 项目里动手(做中学红线)

理论讲完了。这一节的做中学红线是:**搭一个最小的 rendezvous/signaling 服务器,让两个客户端通过它交换地址,然后尝试 UDP hole punching**。我们用 localhost + 两个绑定不同端口的进程模拟"两个 NAT 后面的端点",验证整套流程能跑。这是这一篇的核心动手任务——你不亲手把 signaling 服务器跑起来、亲眼看 hole punching 的对发过程,这套概念永远停留在纸面。

### 第一步:写一个最小的 rendezvous(signaling)服务器

这个服务器跑在公网(测试时跑 localhost),客户端连上来,注册自己的"对外地址",服务器把配对的客户端地址互相告诉对方。

```rust
// rendezvous.rs —— 最小 signaling 服务器
// 协议:客户端发 Register{my_addr, want_peer},服务器回 Matched{peer_addr}
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::io::{self, ErrorKind};
use std::net::{SocketAddr, UdpSocket};

#[derive(Serialize, Deserialize, Debug, Clone)]
enum ClientMsg {
    // 客户端上线,报告自己的"对外声称的公网地址"(从 STUN 拿的)
    // 以及想配对的 peer 的 id
    Register { id: u64, public_addr: SocketAddr, want_peer: u64 },
}

#[derive(Serialize, Deserialize, Debug, Clone)]
enum ServerMsg {
    // 服务器告诉客户端:你的 peer 的地址是这个,去打洞吧
    PeerInfo { peer_addr: SocketAddr },
}

fn main() -> io::Result<()> {
    let socket = UdpSocket::bind("0.0.0.0:3478")?;
    socket.set_nonblocking(true)?;
    println!("[rendezvous] listening on :3478");

    // id -> (public_addr, 客户端实际发包来源地址)
    // 注意:public_addr 是客户端自己声称的(STUN 看到的),
    // 但实际我们要用 socket.recv_from 拿到的 addr —— 那才是真的"server-reflexive"地址
    let mut registry: HashMap<u64, SocketAddr> = HashMap::new();
    let mut pending: Vec<(u64, u64)> = Vec::new(); // (id, want_peer)

    let mut buf = [0u8; 2048];
    loop {
        match socket.recv_from(&mut buf) {
            Ok((n, src)) => {
                let msg: ClientMsg = match bincode::deserialize(&buf[..n]) {
                    Ok(m) => m,
                    Err(_) => continue,
                };
                match msg {
                    ClientMsg::Register { id, want_peer, .. } => {
                        // 关键:我们记录的地址不是客户端声称的 public_addr,
                        // 而是 server 看到的 src —— 这才是真正能打通的地址
                        // (在真实部署里 src 是 NAT 改写后的公网地址,
                        //  对 localhost 测试,src 就是客户端绑定的 127.0.0.1:port)
                        println!("[rendezvous] {} registered, src={}, want_peer={}", id, src, want_peer);
                        registry.insert(id, src);

                        // 检查 want_peer 是否已注册
                        if let Some(&peer_addr) = registry.get(&want_peer) {
                            // 双向通知
                            let to_a = ServerMsg::PeerInfo { peer_addr };
                            let to_b = ServerMsg::PeerInfo { peer_addr: src };
                            let _ = socket.send_to(&bincode::serialize(&to_a).unwrap(), src);
                            let _ = socket.send_to(&bincode::serialize(&to_b).unwrap(), peer_addr);
                            println!("[rendezvous] matched {} <-> {}, sent peer info to both", id, want_peer);
                            // 已配对,从 pending 移除
                            pending.retain(|&(a, b)| !(a == id && b == want_peer) && !(a == want_peer && b == id));
                        } else {
                            pending.push((id, want_peer));
                            // 反向检查:peer 是不是也在等 id?
                            // 简化:让客户端用对称的 want_peer 重试,或者这里做一轮扫描
                            for &(a, b) in pending.iter() {
                                if a == want_peer && b == id {
                                    if let (Some(&addr_a), Some(&addr_b)) = (registry.get(&a), registry.get(&b)) {
                                        let m1 = ServerMsg::PeerInfo { peer_addr: addr_b };
                                        let m2 = ServerMsg::PeerInfo { peer_addr: addr_a };
                                        let _ = socket.send_to(&bincode::serialize(&m1).unwrap(), addr_a);
                                        let _ = socket.send_to(&bincode::serialize(&m2).unwrap(), addr_b);
                                        println!("[rendezvous] mutual match {} <-> {}", a, b);
                                    }
                                }
                            }
                        }
                    }
                }
            }
            Err(ref e) if e.kind() == ErrorKind::WouldBlock => {
                std::thread::sleep(std::time::Duration::from_millis(10));
            }
            Err(e) => return Err(e),
        }
    }
}
```

这个服务器的关键洞察是:**它记录的不是客户端声称的 `public_addr`,而是 `socket.recv_from` 实际看到的源地址 `src`**。在真实部署里,`src` 就是 NAT 改写后的公网地址(server-reflexive address),这是真正能打通的地址。客户端自己声称的 `public_addr` 在 localhost 测试里跟 `src` 一样,但在真实 NAT 后不一样——这就是为什么 signaling 服务器要"权威地"告诉双方对方的地址,而不是让客户端自己交换(客户端自己看到的自己地址是私网地址,没用)。

### 第二步:写客户端,实现 hole punching

客户端的工作:连 rendezvous 服务器注册自己,等服务器告诉自己 peer 的地址,然后**对发**包打洞,然后切到正常的 P2P 模式(可以复用 09E-1 的可靠 UDP 通道)。

```rust
// hole_punch_client.rs
use serde::{Deserialize, Serialize};
use std::io::{self, ErrorKind};
use std::net::{SocketAddr, UdpSocket};
use std::time::{Duration, Instant};

#[derive(Serialize, Deserialize, Debug, Clone)]
enum ClientMsg {
    Register { id: u64, public_addr: SocketAddr, want_peer: u64 },
}
#[derive(Serialize, Deserialize, Debug, Clone)]
enum ServerMsg {
    PeerInfo { peer_addr: SocketAddr },
}
// hole punching 阶段的包:就一个标识符
#[derive(Serialize, Deserialize, Debug)]
struct Punch { from: u64 }

fn main() -> io::Result<()> {
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 4 {
        eprintln!("Usage: {} <my_id> <my_local_port> <rendezvous_addr>", args[0]);
        eprintln!("  e.g. client A: {} 1 50001 127.0.0.1:3478", args[0]);
        eprintln!("  e.g. client B: {} 2 50002 127.0.0.1:3478", args[0]);
        std::process::exit(1);
    }
    let my_id: u64 = args[1].parse().unwrap();
    let my_port: u16 = args[2].parse().unwrap();
    let rendezvous: SocketAddr = args[3].parse().unwrap();

    let socket = UdpSocket::bind(("0.0.0.0", my_port))?;
    socket.set_nonblocking(true)?;

    // 1. 注册到 rendezvous。A(id=1)想连 B(id=2),B(id=2)想连 A(id=1)
    let want_peer = if my_id == 1 { 2 } else { 1 };
    let register = ClientMsg::Register {
        id: my_id,
        public_addr: format!("127.0.0.1:{}", my_port).parse().unwrap(),
        want_peer,
    };
    socket.send_to(&bincode::serialize(&register).unwrap(), rendezvous)?;
    println!("[client {}] registered at rendezvous, waiting for peer info...", my_id);

    // 2. 等 rendezvous 告诉我们 peer 的地址
    let peer_addr: SocketAddr = {
        let mut buf = [0u8; 2048];
        loop {
            match socket.recv_from(&mut buf) {
                Ok((n, _)) => {
                    if let Ok(ServerMsg::PeerInfo { peer_addr }) = bincode::deserialize(&buf[..n]) {
                        println!("[client {}] got peer addr: {}", my_id, peer_addr);
                        break peer_addr;
                    }
                }
                Err(ref e) if e.kind() == ErrorKind::WouldBlock => {
                    std::thread::sleep(Duration::from_millis(10));
                }
                Err(e) => return Err(e),
            }
        }
    };

    // 3. UDP hole punching:往 peer 狂发 punch 包,直到收到 peer 的 punch
    println!("[client {}] punching...", my_id);
    let punch = Punch { from: my_id };
    let punch_bytes = bincode::serialize(&punch).unwrap();
    let mut punched = false;
    let start = Instant::now();
    let mut last_send = Instant::now();

    while start.elapsed() < Duration::from_secs(10) {
        // 每 50ms 发一个 punch 包
        if last_send.elapsed() >= Duration::from_millis(50) {
            last_send = Instant::now();
            // 注意:这个 send 大概率前几个会被对端 NAT 丢(在真实 NAT 场景),
            // 但它的目的是在本地 NAT 建立映射,让对端的后续包能进来
            let _ = socket.send_to(&punch_bytes, peer_addr);
        }

        // 检查是否收到对端的 punch
        let mut buf = [0u8; 2048];
        match socket.recv_from(&mut buf) {
            Ok((n, src)) => {
                if src == peer_addr {
                    if let Ok(Punch { from }) = bincode::deserialize(&buf[..n]) {
                        println!("[client {}] RECEIVED punch from {}! Hole punched!", my_id, from);
                        // 回一个确认 punch,确保对端也收到
                        let _ = socket.send_to(&punch_bytes, peer_addr);
                        punched = true;
                        break;
                    }
                }
            }
            Err(ref e) if e.kind() == ErrorKind::WouldBlock => {}
            Err(_) => {}
        }
        std::thread::sleep(Duration::from_millis(5));
    }

    if !punched {
        eprintln!("[client {}] hole punching failed after 10s (this is where TURN relay would kick in)", my_id);
        return Ok(());
    }

    // 4. 打洞成功,切到正常 P2P 通信(这里复用 09E-1 的可靠 UDP 通道)
    println!("[client {}] P2P established with {}, entering normal communication", my_id, peer_addr);
    // ...这里接入 09E-1 的 ReliableSender / UnreliableSequencedSender...
    // 简化:无限循环 echo
    let mut counter = 0u64;
    loop {
        let msg = format!("hello from {} count={}", my_id, counter);
        let _ = socket.send_to(msg.as_bytes(), peer_addr);
        let mut buf = [0u8; 2048];
        if let Ok((n, _)) = socket.recv_from(&mut buf) {
            if let Ok(s) = std::str::from_utf8(&buf[..n]) {
                println!("[client {}] recv: {}", my_id, s);
            }
        }
        counter += 1;
        std::thread::sleep(Duration::from_millis(500));
    }
}
```

### 第三步:在 localhost 上跑通整个流程

开三个终端:

```bash
# 编译(假设你把上面两个文件放进一个 cargo 项目)
cd /path/to/hole-punch-demo
cargo build --release

# 终端 1:启动 rendezvous 服务器
./target/release/rendezvous

# 终端 2:客户端 A(id=1, 绑定端口 50001)
./target/release/hole_punch_client 1 50001 127.0.0.1:3478

# 终端 3:客户端 B(id=2, 绑定端口 50002)
./target/release/hole_punch_client 2 50002 127.0.0.1:3478
```

你应该看到的流程:A 先注册,服务器说"等 B";B 注册,服务器发现 B 想 A 而 A 在等 B,**双向通知**;A 和 B 几乎同时拿到对方的地址,开始对发 punch 包,几百毫秒内互相收到对方的 punch,打洞成功,切到正常 P2P 通信,两个终端开始互收 "hello from ..."。

在 localhost 上这个流程丝滑,因为 localhost 没有 NAT——`recv_from` 看到的 `src` 就是客户端的真实地址。**真实的 hole punching 测试需要部署到公网**,你需要一台公网 VPS 跑 rendezvous,然后两台各自在家庭 NAT 后的机器跑客户端。这一步超出"做中学红线"的范围(需要你额外准备公网 VPS),但如果你做到了,你会**第一次**亲眼看到你的游戏在两个陌生家庭网络之间真正互通——这是 9E 这条序列的"毕业时刻"。

### 第四步:用 netem 模拟"差网络"下的行为

在 localhost 跑通之后,加 `tc netem` 模拟延迟和丢包,看 hole punching 在恶劣网络下的鲁棒性:

```bash
# 给 loopback 加 100ms 延迟 + 5% 丢包
sudo tc qdisc add dev lo root netem delay 100ms loss 5%

# 重跑三个进程,看 hole punching 是否还能成功(应该能,只是慢一点)
# punch 间隔 50ms,如果丢 5%,平均 20 个 punch(1 秒)内能收到一个

# 清理
sudo tc qdisc del dev lo root
```

### 第五步:集成进 HH 项目,完成"真在线"游戏

把上面的 rendezvous 服务器和 hole punching 客户端集成进 HH 项目,作为联机的"连接建立阶段"。流程是:HH 启动 → 连 rendezvous → 拿到 peer 地址 → hole punch → 切到 09E-1 的可靠 UDP 通道 → 跑 09E-2 的权威服务器逻辑(注意 P2P 下谁是 host 谁是 server) → 跑 09E-3 的兴趣管理(2 人场景下兴趣管理退化为"全发")。

集成完成后,你就拥有了一款**真正能跨家庭网络在线对战的 HH**。它不是 demo,不是 localhost 测试——它是真实的、可以发给陌生人玩的联机游戏。如果你愿意更进一步,把 hole punching 失败的兜底接到 coturn(自建 TURN)或 Steam Relay(集成 steamworks-rs),那它就拥有了 Steam Networking 同级的连通性——这是这一篇做中学红线的终极目标。

可选的进阶:集成 **Steam Networking Sockets** 作为生产级对比。Steamworks SDK 给你一个 `ISteamNetworkingSockets` 接口,你调用 `ConnectP2P(steamID)` 就行,它内部自动跑 ICE + Steam Relay。你可以在 HH 项目里加一个 `--steam` flag,开了就用 Steam Networking,不开就用你自己写的 hole punching。然后对比两者:Steam Networking 几乎一定更稳(因为它的 ICE 实现更成熟 + Steam Relay 全球覆盖),但你的自研版本能让你**理解** Steam Networking 在干什么——这是这一篇,也是 9E 整条序列的核心价值。

## 11 · 练习

练习一,Lv1,概念辨析。你的朋友跟你说:"我配了路由器端口转发,5000 端口转到我这台机器,所以我的游戏不需要 NAT 穿透。" 想清楚为什么这个说法在**产品**层面是错的——你不能假设玩家会配端口转发,而且很多玩家的网络(CGNAT、公司网)连配置入口都没有。正确的工程姿态是什么?(不依赖玩家手动配置,默认走 ICE,把端口转发当作"高级玩家自测加速"的可选项,而不是依赖项)。能把这条说清楚,你就懂这一篇为什么存在了。

练习二,Lv2,动手实践。完成 §10 的全部五步——写 rendezvous 服务器、写 hole punching 客户端、localhost 三终端跑通、netem 加延迟丢包测试、集成进 HH 项目。提交 commit,信息可以写 `feat(net): add NAT traversal with rendezvous signaling + UDP hole punching`。如果你能额外部署一台公网 VPS 跑 rendezvous,然后两台家庭网络机器真的连通,这是 Lv3 级别的成果,值得一个独立 commit `feat(net): validate cross-NAT P2P on public VPS`。

练习三,Lv3,NAT 类型判定。给客户端加一个"STUN 探测"模式:启动时连两个不同的公共 STUN 服务器(比如 `stun.l.google.com:19302` 和 `stun1.l.google.com:19302`),分别报告自己的外部端口。如果两个端口**一样**,你是 cone NAT(可 hole punch);如果**不一样**,你是 symmetric NAT(必须 TURN)。把这个判定结果打印出来,然后让客户端在 hole punching 阶段据此决定策略——cone NAT 直接 punch,symmetric NAT 跳过 punch 直接走 relay(你可以模拟 relay,就是让 rendezvous 服务器转发流量)。这是 ICE 框架的简化版,做完你能理解 ICE 为什么用"暴力枚举候选"而不是"先判定 NAT 类型再选策略"。

练习四,Lv4,Steam Networking 集成与对比。在 HH 项目里加一个 `--steam` flag,集成 `steamworks-rs` 的 `ISteamNetworkingSockets`,实现同样的"两个客户端连接"功能,但是走 Steam Networking。然后写一个对比文档:同样两台家庭网络机器,你的自研 hole punching 能连通的比例 vs Steam Networking 能连通的比例(Steam 应该接近 100%,因为它有 Steam Relay 兜底);两者的连接建立时间(STeam 可能慢一点,因为它要跑完整 ICE);两者的延迟(STeam 在需要 relay 时延迟更高)。这个对比能让你深刻理解"工业方案为什么是工业方案"——以及你自己的实现在哪些地方可以改进。

## 12 · 9E 序列收口:四篇文章构成了一整套游戏网络后端

这是 9E 序列的最后一篇。让我把四篇文章的脉络串起来,让你看到它们如何构成一个**完整的、可以真的让陌生人在公网上对战**的游戏网络后端基础设施。

[09E-1](09E-1-reliable-udp-transport.md) 解决的是"两台能互通的机器之间,怎么传游戏数据"。它从"为什么 TCP 是游戏的天敌"开始,讲透队头阻塞,然后在裸 UDP 上自建了一套序列号 + ACK + 重传 + 滑动窗口的可靠性层,以及"可靠有序 / 不可靠有序 / 不可靠无序"三种通道的 per-message 选择。它是这一整套的地基——**没有可靠的传输管道,上面的一切都无从谈起**。

[09E-2](09E-2-authoritative-server-and-state-sync.md) 解决的是"两台机器之间,谁来算游戏状态"。它从"为什么不能信客户端"开始,讲透 anti-cheat,然后搭建了服务器权威架构——server 跑完整 simulation,client 发输入、收快照、做插值和预测。它把 09E-1 的管道变成了一个**不能被作弊的联机系统**。

[09E-3](09E-3-interest-management-and-replication.md) 解决的是"server 怎么高效地把状态发给几十上百个玩家"。它从"全量 broadcast 带宽爆炸"开始,讲透兴趣管理(谁关心什么)、区域划分、delta 压缩、视锥裁剪、优先级调度。它把 09E-2 的"一个 server 对一个 client"扩展到了"一个 server 对 N 个 client",让游戏**能 scale**。

[09E-4](09E-4-matchmaking-nat-relay-lobby.md)(这一篇)解决的是"两个陌生玩家在公网上怎么找到彼此并连上"。它从"NAT 杀死 P2P"开始,讲透 STUN、UDP hole punching、TURN relay、ICE 框架,然后讲了 matchmaking / lobby / session 管理,以及 dedicated server vs P2P 的架构选型,最后落到了 Steam Networking 这种工业打包方案。它把前三篇搭好的 netcode **真正接入了公网**——前三篇假设"两端能互通",这一篇把假设变成现实。

这四篇合起来,覆盖了一个游戏网络后端基础设施的**全栈**:传输层(09E-1)→ 应用层架构(09E-2)→ 规模化(09E-3)→ 接入层(09E-4)。它们和 phase-5 的 [network-multiplayer-models](../phase-5/deep-dives/network-multiplayer-models.md) 互补——phase-5 讲的是"用什么**模型**做联机"(lockstep / state sync / rollback),9E 讲的是"这些模型**跑在什么基础设施上**"。两者结合,你就拥有了从"高层模型选择"到"底层传输实现"的完整网络知识图谱。

走完 9E 之后你能做什么?你能:(1) 在自己的 Rust 游戏里从零实现一个可靠 UDP 传输层(09E-1);(2) 在它之上搭一个不可作弊的权威服务器(09E-2);(3) 让这个服务器支持几十人同服,带宽可控(09E-3);(4) 让陌生玩家在公网找到彼此并连上,NAT 不再是障碍(09E-4);(5) 理解 Steam Networking / EOS / Photon 这些工业方案在底层做什么,有能力做架构决策(选 P2P 还是 dedicated?自建 relay 还是用 Steam Relay?)。**这些能力合起来,就是"我能独立交付一款带专业级联机的游戏"的含义。** 这是 9E 序列的毕业证书。

## 13 · 延伸阅读与下一篇

外部稳定 URL:

- **RFC 8445 ICE** — `https://datatracker.ietf.org/doc/html/rfc8445`,ICE 的权威规范,枯燥但完整,你想理解 candidate 优先级和 connectivity check 的精确语义就读它。
- **RFC 8656 TURN** — `https://datatracker.ietf.org/doc/html/rfc8656`,TURN 中继协议规范。
- **RFC 5389 STUN** — `https://datatracker.ietf.org/doc/html/rfc5389`,STUN 协议规范(包括 XOR-MAPPED-ADDRESS 的位运算细节)。
- **RFC 3489(旧 STUN,NAT 类型判定)** — `https://datatracker.ietf.org/doc/html/rfc3489`,虽然已被 5389 取代,但这篇定义了 full-cone / restricted / symmetric 的分类,理解 NAT 光谱的最佳读物。
- **Glenn Fiedler "Building a Game Network Protocol" 系列** — `https://gafferongames.com/categories/game-networking/`,跟 9E 整条序列同源,其中有几篇专门讲 NAT 穿透的工程实践。
- **WebRTC 的 NAT 穿透文档** — `https://developer.mozilla.org/en-US/docs/Web/API/WebRTC_API/Protocols`,虽然是浏览器 API 文档,但它的 STUN/TURN/ICE 解释是全网最清晰的一份。
- **coturn 项目** — `https://github.com/coturn/coturn`,工业级 TURN 服务器实现,部署生产 TURN 必备。
- **Steam Networking Sockets 文档** — `https://partner.steamgames.com/doc/features/multiplayer/networking`,Valve 官方文档,讲 Steam Networking 的 NAT 穿透 + relay + 加密全栈。
- **Valve 的 Steamworks SDK** — `https://partner.steamgames.com/doc/sdk`,steamworks-rs 就是 wrap 这个 SDK。
- **Epic Online Services** — `https://dev.epicgames.com/docs/services/en-US/EpicAccountServices/index.html`,跨平台网络 + matchmaking 服务,Fortnite 用它。
- **Brynat 等人的 NAT 穿透实证研究** — "NAT Traversal in the Wild" 等论文,有 Google STUN 团队的大规模统计,告诉你 hole punching 成功率的真实分布。

真实开源源码参考:

- **coturn 的 TURN 实现** — `https://github.com/coturn/coturn/blob/master/src/server/ns_turn_server.c`,TURN server 的核心,看 ALLOCATE / CHANNELBIND 怎么实现。
- **pion/ice(Go 的 ICE 实现)** — `https://github.com/pion/ice`,WebRTC 的 Go 实现,ICE 的 agent 逻辑清晰,适合通读理解 candidate gathering。
- **aiortc(Python 的 WebRTC)** — `https://github.com/aiortc/aiortc/blob/main/src/aiortc/rtcicetransport.py`,Python 的 ICE transport,代码量小,适合学习。
- **steamworks-rs** — `https://github.com/Noxime/steamworks-rs`,Rust binding,看 `src/networking.rs` 怎么 wrap Steam Networking Sockets。

本仓库内相关内容:

- [phase-9/09E-1-reliable-udp-transport](09E-1-reliable-udp-transport.md) 是 9E 序列的起点,讲可靠 UDP 传输层——这一篇的 hole punching 打通后,跑的就是 09E-1 的可靠通道。
- [phase-9/09E-2-authoritative-server-and-state-sync](09E-2-authoritative-server-and-state-sync.md) 讲权威服务器与状态同步——这一篇的 P2P 架构里,谁是 host 谁就是 09E-2 的 server。
- [phase-9/09E-3-interest-management-and-replication](09E-3-interest-management-and-replication.md) 讲兴趣管理与复制——2 人 P2P 场景下兴趣管理退化为"全发",但多人场景下这一篇是 09E-3 的延伸。
- [phase-5/deep-dives/network-multiplayer-models](../phase-5/deep-dives/network-multiplayer-models.md) 是 9E 整条序列的上游——它讲"用什么模型做联机"(lockstep/state sync/rollback),9E 讲"这些模型跑在什么基础设施上"。两者互补,先读 phase-5 知道"为什么需要 netcode",再读 9E 知道"netcode 怎么造"。
- [phase-0/23-network-foundation](../phase-0/23-network-foundation.md) 是 socket / TCP / UDP 的基础,如果你对 `UdpSocket`、`send_to`、`recv_from` 这些底层 API 还不熟,先回去补这一篇。

下一篇 [09F-1](09F-1-ci-cd-and-build-engineering.md) 会从网络后端切换到**构建与发布工程**——讲可复现构建、交叉编译、资产校验、CI 守护、跨平台打包。如果说 9E 让你的游戏"能在公网上跑起来",9F 就是让你的游戏"能被任何人一键安装到任何平台"。9E 解决的是"运行时可达性",9F 解决的是"交付时可达性"——两者合起来,才是一款真正能上架的游戏。
