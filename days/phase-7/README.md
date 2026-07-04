
# Phase 7 · PNG / 资产管线 / 编辑器(Day 436–575)

> 前 435 集 Casey 一直用 BMP 和现成的 .hha。Day 436 起,他开始**手写 PNG 解码器**:ZLIB、Huffman、reconstruction filters,从二进制位流开始一个 bit 一个 bit 解。这是 HH 全剧"造轮子含量"最高的 30 集。之后 Casey 给游戏加 in-game 编辑器、热加载资产、自定义资产打包格式。Phase 7 把你从"调库的程序员"变成"理解底层的程序员"。

## 这一阶段在做什么

### 把镜头拉近:Phase 7 开始时 Casey 的处境

假设你就是 Casey,坐到 2017 年某天的直播台前。过去三年(对观众来说是 Day 1-435)你一步步搭起了 Handmade Hero:从空窗口开始,做出了软件渲染器、Windows 平台层、音频系统、ECS 风格的实体管理、动态内存分配器、第一人称控制器、纹理映射、3D 几何管线、Blinn-Phong 光照、视锥裁剪、法线贴图、Gamma 校正、HDR + tone mapping、阴影贴图、延迟 vs 前向的权衡讨论、ImGui 风格的 debug overlay、性能 profiler、变量编辑器。这一切都是从零写的——`malloc` 不用,STL 不用,CRT 不用,Win32 API 手敲。

但有一处 Casey 心里始终不踏实:**资产加载**。游戏用的 PNG 纹理,他是用 `image` 这个外部库解的。游戏用的 .hha 资产包,是预先打包好、观众从网站下载的。**这两件事构成了"调库的黑盒"**——Casey 整个 Handmade Hero 哲学最大的例外。

调库本身不是罪——很多优秀的开源项目都用库。但对 Casey 来说,这意味着**他没法回答观众的灵魂提问**:"诶,那个 .hha 文件里到底装了什么?" "为什么我改了 PNG 重新打包就出错?" "DEFLATE 算法到底怎么把 100 KB 压成 30 KB?"

Phase 7 就是 Casey 把这块黑盒**也拆开**的阶段。他从 Day 436 开始,做了一系列"造轮子"专题:先升级光照采样到工业级(子项目 A),然后函数逼近(子项目 B),然后 3D 迷宫生成(子项目 C),然后**完整手写 PNG 解码器**(子项目 D,7 集),然后资产热重载(子项目 E),最终 Phase 7 收尾于 in-game editor(子项目 F-J,横跨 110 天)。

### 三个工程短板的根源

Phase 6 收官时,你的游戏已经有了完整 3D 渲染、光照、纹理压缩。但还有几个工程短板:

**第一,资产管线依赖外部库**。你之前用 `image` crate 解 PNG,但不知道里面发生了什么——DEFLATE、Huffman、Paeth 滤镜全是黑盒。这让"调试花屏"或"支持新格式"变得困难。具体说,你修不了三类 bug:(a) 某些 PNG 解出花屏——可能是 interlacing 没处理,但你看不懂 `image` 的源码;(b) 某些大 PNG(8K)解到一半崩溃——内存布局问题,但你不知道内部用了什么 buffer;(c) 想加一个自定义格式(比如 16-bit 高动态范围 PNG),`image` 不支持,你只能等上游。这些都是黑盒之痛。

**第二,资产热重载不完整**。改 PNG 后要重启游戏才能看到效果,迭代慢。具体场景:你调一个 sprite,改了 50 像素,要保存——切到游戏窗口——重启——再走 30 秒到那个 sprite 所在地——看效果——不行——切回编辑器再改——重启……这一个循环 2 分钟,改 10 次 = 20 分钟,改 100 次 = 半天。工业级游戏(Unreal、Unity)都支持热重载——改完立刻看见。Phase 7 要把这个能力加上。

**第三,资产打包格式是黑盒**。Casey 此前用预制 .hha,观众依赖下载。源码可读但生成工具未公开。这意味着:(a) Casey 不能轻易加新资产类型(动画、音频 metadata);(b) 观众不能自己打包自己的资产;(c) 格式版本控制不清晰——V0 升 V1 怎么迁移?Phase 7 把 .hha 格式完全开放。

### 五个子项目的串接逻辑

Phase 7 解决这三个问题。Casey 用 140 天分多个子项目。让我把每个子项目的**内在动机**讲清楚,而不是简单列表:

**子项目 A:光照采样分布(Day 436-439)**。把光照计算从朴素半球网格升级到工业级"螺旋 + 余弦加权 + Poisson"分布。涉及信息论(熵)、概率分布、PRNG 算法。**动机**:Phase 6 末的光照有噪声——像素闪烁,像没去噪的 ray tracing 图。Casey 知道问题在采样分布,于是花 4 天彻底搞清楚"为什么均匀采样不好,余弦加权怎么解决问题"。这是图形学的硬核数学。

**子项目 B:工具链稳定 + 调试器(Day 440-442)**。Andrew Bromage 来宾讲函数逼近(sin/cos/exp 的多项式拟合)。Casey 讨论工具链冻结的工程纪律。NSight GPU profiler 集成。**动机**:Phase 7 之后要进入"造轮子"期,代码会很难调。Casey 先把工具链钉死(compiler 版本、flags、debugger),避免后面被工具问题分心。这是工业级开发纪律——"先磨刀,再砍柴"。

**子项目 C:3D 迷宫生成器(Day 443-450)**。8 集手把手实现程序化房间生成——房间体积、邻接放置、凿门、防重叠、所有方向连接。是 HH 的程序化生成实战。**动机**:子项目 D 写 PNG 解码器之前,Casey 需要一个"用得上 PNG 纹理"的游戏场景。3D 迷宫正好——要 procedural 生成房间、放装饰物、贴墙纹理。这一阶段把光照采样(子项目 A)和工程纪律(子项目 B)都用上了。

**子项目 D:PNG 解码器(Day 453-459)**。7 集完整手写 PNG 解码——PNG 头部、ZLIB、DEFLATE、Huffman、LZ77、5 种重建滤镜。这是 HH 全剧"造轮子含量"最高的部分。**动机**:这是 Phase 7 的核心黑盒拆除。Casey 不仅要"用 PNG",更要"理解 PNG 到字节级"。完成后,他自己实现的解码器取代了 `image` crate。

**子项目 E:资产热重载 + 导入器(Day 460-465)**。6 集实现完整资产管线——文件监听、热重载、精灵表提取、HHA V0 → V1 格式升级。**动机**:有了自己的 PNG 解码器,接下来是"运行时资产管线"——监听文件变化、自动重载、版本控制。这是把子项目 D 的能力"产品化"。

### Phase 7 后半:Editor 的马拉松

完成子项目 A-E 后,Phase 7 还剩 100 多天(day466-575)。这些天数几乎全部围绕一个主题:**in-game editor**。

Casey 在直播里反复强调:商业游戏引擎(Unreal、Unity、Godot)的核心竞争力不是渲染器,而是**编辑器**。一个 artist 或 designer 打开引擎,不写代码就能放房间、调光照、试玩。这种"非程序员可迭代"的能力,是工业级游戏开发的命脉。

Casey 决定也给 Handmade Hero 加 in-game editor。这件事横跨 100 天不是因为它"难",而是因为它**包罗万象**——immediate-mode UI 框架、选择系统、变换 gizmo、属性面板、undo/redo、序列化、关卡保存/加载、层级视图、快捷键系统。每一项都是子项目。

这一段对应本仓库 day 文件的:**day466-575**(约 110 集)。本教程的金标文件覆盖了其中的代表性天数,但并非逐日详尽。本 README 主要覆盖**子项目 A-E(day436-465)**——这是 Casey 公认的"造轮子教学精华"。

完成 Phase 7 后,你的游戏资产管线**完全自主可控**:从 PNG 文件到 GPU 纹理,每一步你都理解。这是一个开源黑客的核心能力。

## 学习目标

完成 Phase 7 的前 30 天(day436-465,本教程覆盖范围)后,你能:

- [ ] 解释 Shannon 熵、Monte Carlo 积分、重要性采样三个图形学概念
- [ ] 实现 PCG32 PRNG 并验证其统计质量
- [ ] 用 4 阶 Remez 多项式逼近 sin,达到 libm 5 倍速度
- [ ] 用四元数表达 3D 旋转,避免 Gimbal lock
- [ ] 实现自顶向下 + stub 的大功能开发流程
- [ ] 写出 3D 迷宫生成器:房间生成、邻接放置、防重叠、连接方向
- [ ] 手写完整 PNG 解码器(8 字节 magic → 像素数据)
- [ ] 解释 DEFLATE 算法:LZ77 + Huffman 的组合
- [ ] 实现 5 个 PNG 重建滤镜(None/Sub/Up/Average/Paeth)
- [ ] 实现资产热重载(文件监听 → 自动重载)
- [ ] 设计 HHA 二进制资产格式并实现 V0 → V1 迁移

## 主题索引(按 4 域分类,本教程覆盖 day436-465)

### 🎮 游戏编程

- **day436-439**:光照采样分布(螺旋 / Poisson / 余弦加权 / 熵)
- **day443**:四元数 mouse look
- **day444-450**:3D 迷宫生成器(8 集)
  - 房间体积生成、邻接放置、凿门、防重叠、所有方向
- **day460-461**:资产热重载
- **day462**:精灵表 atlas
- **day463-465**:HHA 资产格式 V0 → V1

### 🎨 图形学

- **day436-440**:Monte Carlo 积分、重要性采样
- **day440**:函数逼近(Andrew Bromage)
- **day442**:GPU profiler(NSight / RenderDoc)
- **day451**:反投影(unproject)
- **day452**:第三人称相机 + 碰撞
- **day453-459**:PNG 解码全链路
  - PNG chunk / ZLIB / DEFLATE / Huffman / LZ77 / 5 滤镜

### 🐧 Linux 系统编程

- **day439**:PRNG(/dev/urandom / RDRAND / PCG)
- **day441**:工具链冻结(pacman IgnorePkg / rust-toolchain.toml)
- **day442**:GPU 工具链(nvidia-smi / glxinfo / apitrace)
- **day453**:二进制解析工具(file / xxd / pngcheck)
- **day458**:调试工具(gdb / rr / valgrind / ASAN)
- **day460-461**:文件监听(stat / inotify / notify crate)

### 🦀 Rust 生态

- **day436**:const fn / 数组初始化 / SIMD 友好布局
- **day437**:const fn vs Lazy vs 显式 GameState
- **day438**:Iterator 链 / 拒绝采样 / Bridson 算法
- **day439**:rand / rand_pcg / nanorand / getrandom
- **day440**:mul_add / Horner 形式 / fast-math crate
- **day441**:rust-toolchain.toml / Cargo.lock / cargo vendor
- **day443**:四元数 / SLERP / glam
- **day445**:工厂模式 / enum + match
- **day448**:Wall piece / 凿墙几何
- **day453-459**:BitReader / Huffman 树 / canonical code
- **day459**:模块化 crate 设计 / pub(crate) / DecodeError enum
- **day464**:约定优于配置 / 文件名解析

## 跨日专题(本教程未来补充)

Phase 7 的剩余 110 天(day466-575)包括:

- **In-game editor**:immediate-mode UI,undo/redo,关卡编辑器
- **Memory profiling**:可视化内存使用,leak 检测
- **Light probes**:光探针系统(体素化光照,现代引擎标配)
- **Asset cooker**:从源 PNG → GPU 友好格式(BCn / ASTC)

这些将在后续子项目中补充。

## 阶段项目验收(本教程 day436-465 范围)

完成这一阶段后,你的 Rust 项目应该能:

- [ ] 加载任何 PNG 文件(用你自己写的解码器),不依赖 `image` crate
- [ ] 自动监听 PNG 文件变化,改了立刻看到(不用重启游戏)
- [ ] 从一张精灵表 PNG 切出 N 个 sprite,渲染到屏幕
- [ ] 生成 3D 迷宫:5-20 个房间,每个房间有门连接,玩家可走通
- [ ] 玩家相机第三人称跟随,贴墙时不穿墙
- [ ] 鼠标点击地面,在 3D 世界画出 marker(用 unproject)
- [ ] 程序化光照用 64 个余弦加权半球方向(不依赖 RNG)
- [ ] HHA 资产从 V0 迁移到 V1,CRC 验证通过

## 开源贡献实践(本阶段)

推荐 1-2 个开源贡献:

1. **`glam`**(https://github.com/bitshifter/glam)— Rust 数学库
   - 看 Vec3A / Quat 的 SIMD 实现
   - 补 SLERP / from_axis_angle 的 doc 或 test

2. **`png` crate**(https://github.com/image-rs/image-png)
   - 看滤镜实现
   - 补损坏 PNG 输入测试

3. **`miniz_oxide`**(https://github.com/Frommi/miniz_oxide)
   - 看 DEFLATE 实现
   - 补 fuzzing 输入

4. **`flate2`**(https://github.com/rust-lang/flate2-rs)
   - zlib/gzip/zip 文档
   - 补极端 size 测试

5. **`notify`**(https://github.com/notify-rs/notify)
   - 文件监听库
   - 补 NFS / 网络盘边界测试

PR 类型建议:
- 文档:补算法推导、公式说明
- 测试:补边界情况(NaN、空输入、极端 size)
- 示例:加 runnable example
- 实现:加 SIMD 优化(谨慎,需先理解原代码)

## 本阶段用到的 reference/ 资料

主要依据的本地 HH slice:[days/reference/hh-slices/phase-7.json](../reference/hh-slices/phase-7.json)(140 集 lesson 数据)

外部资料(按需 WebFetch):
- W3C PNG spec:https://www.w3.org/TR/png/
- RFC 1950 (zlib):https://datatracker.ietf.org/doc/html/rfc1950
- RFC 1951 (DEFLATE):https://datatracker.ietf.org/doc/html/rfc1951
- PCG paper:https://www.pcg-random.org/paper.html
- "Understanding Quaternions":https://www.3dgep.com/understanding-quaternions/
- RenderDoc:https://renderdoc.org/
- rr debugger:https://rr-project.org/
- LearnOpenGL PBR IBL:https://learnopengl.com/PBR/IBL

## 风格金标

本阶段 day 文件的金标:
- [day436.md](day436.md) — 球面螺旋分布(本阶段第一天,概念密度高)
- [day453.md](day453.md) — PNG 头部解析(造轮子系列开篇)
- [day455.md](day455.md) — Huffman 表(DEFLATE 难点)
- [day459.md](day459.md) — 模块化重构(工程化)

## 阶段总结:从"调库"到"造轮子"

Phase 7 的核心张力是**抽象 vs 理解**。

调库(用 `image::open`)让你快速做事,但你不理解里面发生了什么——遇到 bug、性能问题、新格式,你束手无策。

造轮子(自己写 PNG 解码器)让你深度理解,但慢——你花 7 集才能加载一张 PNG。

Casey HH 选造轮子,因为目标是培养"开源黑客"——能从字节到 GPU 完整理解、能为开源项目贡献代码的程序员。商业游戏开发反过来,优先调库(快)。

完成 Phase 7 后,你两种都能做:
- **快**:用 `image` / `png` / `flate2` 加载资产(知道原理)
- **深**:自己实现 PNG 解码、Huffman 编码、文件监听(理解每行)

这种"两栖能力"是开源黑客的核心。Phase 8 会带这种能力做最终游戏收官——光照优化、3D 碰撞重构、发布。

### 一个常见误解:"造轮子"=不调库

很多人看完 Handmade Hero 哲学,误以为 Casey 反对所有库。**这是误解**。Casey 自己反复强调:他造轮子的目的不是"反对调库",而是"先理解,再决定调不调"。

具体说,Casey 在 HH 里也调了不少库:
- **freetype**:字体光栅化,Casey 直接用 freetype 库,不自己实现。理由:FreeType 是 30 年沉淀的复杂代码,自己写一遍收益极低。
- **OpenGL / Direct3D**:GPU API,Casey 用现成的。理由:GPU driver 本身是闭源黑盒,你重写 API 也调不到 driver 之下。
- **Windows API**:平台层。Casey 用 Win32,不自己写 syscall。理由:Win32 已经是 Microsoft 维护的"准系统调用"。

但 Casey **不**调这些:
- **CRT(C runtime)**:malloc、printf、memcpy。Casey 全部自己实现。理由:CRT 是历史包袱(线程安全、locale、错误处理)太多,自己写一遍能控制行为。
- **stb_image / lodepng**:PNG 解码。Casey 自己写。理由:PNG 解码是单文件级复杂度,自己写一遍收益高。
- **cute_headers / indie headers**:轻量库。Casey 看情况。

判断"调不调库"的标准:
1. **复杂度收益比**:库复杂度高、你重写收益高 → 重写。库复杂度极高、重写收益低 → 调用。
2. **可理解性**:库源码你看得懂 → 调用(必要时候能 debug)。库源码看不懂(如 OpenSSL)→ 找替代或慎用。
3. **依赖稳定性**:库活跃维护、API 稳定 → 调用。库弃坑、API 漂移 → 慎用或自己实现核心。
4. **抽象代价**:库引入抽象层(虚函数、运行时反射)影响性能 → 慎用。

PNG 解码对 Casey 是"刚好值得重写"的——它复杂但不是太复杂,理解它对你处理其他二进制格式(ZIP / GLB / ASTC)有正迁移。所以 Casey 选了重写。

### Phase 7 的"涟漪效应"

Phase 7 学完,你获得的能力不只是"会写 PNG 解码器"。它会**改变你看所有二进制文件的方式**。具体说:

- **看 ZIP 文件**:ZIP 内部也是 DEFLATE 压缩,Phase 7 学的 Huffman/LZ77 直接适用。你以后看 `unzip -l archive.zip` 不再是黑盒。
- **看 GLB / glTF**:3D 模型格式。GLB 有 JSON header + 二进制 buffer,Phase 7 学的"二进制解析纪律"直接适用。
- **看 WASM 字节码**:WebAssembly 是一种二进制指令格式。Phase 7 学的 LEB128 编码、section 解析、模块结构,都是同套思路。
- **看 ELF / PE**:可执行文件格式。ELF header、section table、relocation table——同套二进制解析思路。
- **看 BCn / ASTC 纹理**:GPU 压缩格式。Phase 7 学的"位级操作"直接适用——BCn 把 4×4 像素块压到 64 bit / 128 bit,你要一位一位读。

这就是 Casey 哲学的真正威力:**学一个具体格式(PNG),迁移到一类问题(二进制解析)**。Phase 7 学的不是 PNG,是"如何阅读规范文档并实现它"。

工业界招聘要求里常写"熟悉二进制格式解析",这其实就是 Phase 7 教的能力。Casey 给你的不是"PNG 知识",是"读规范能力"。

### 与本仓库其他 Phase 的衔接

- **Phase 1-2(day001-040)**:软件光栅化基础——你学会了如何"画一个像素"。Phase 7 是"如何读一个像素(从 PNG 文件)"。
- **Phase 3(day041-110)**:内存管理、动态加载。Phase 7 的资产管线建立在这之上——你要分配 buffer、读取文件、释放。
- **Phase 4-5(day111-210)**:3D 渲染、调试工具。Phase 7 的 PNG 解码器需要 debug overlay 显示状态,Phase 5 的工具用得上。
- **Phase 6(day261-435)**:高级渲染(光照、纹理压缩)。Phase 7 的光照采样分布(子项目 A)是 Phase 6 光照的延续。
- **Phase 8(day616+)**:游戏发布。Phase 7 的资产管线 + 编辑器是发布前的"最后一里"。

整个 800 多天的 Handmade Hero 之旅是一棵树,Phase 7 是其中一根大树枝——它把"游戏功能"和"工具链/资产"两条线交汇起来。

## 下一步

完成本教程覆盖的 day436-465 后,你可以:

1. **继续 Phase 7 余下天数(day466-575)**:
   - In-game editor(立即模式 UI)
   - Light probes(现代光照)
   - Asset cooker(BCn / ASTC)
   
   本教程未来补充这些 day 文件

2. **回顾 Phase 6**(如果还没完成):
   - 深度缓冲 / 光照 / 压缩
   - [Phase 6 README](../phase-6/README.md)

3. **做 Phase 7 阶段项目**:
   - 写自己的 PNG 解码器
   - 实现资产热重载
   - 给一个 Rust crate 提 PR

## 一份"读完 Phase 7 后的世界观"

### 对一张 PNG 图片的新认知

读 Phase 7 之前,你看一张 PNG 图片,看到的是"一张图"。读完之后,你看 PNG 文件,看到的是**一个有结构的字节序列**:

```
[0x89 P N G \r \n 0x1A \n]   ← 8 字节 magic
[IHDR chunk]                   ← 13 字节头(width/height/depth/colorType/...)
[IDAT chunk]                   ← 压缩的像素数据(DEFLATE)
[IDAT chunk]                   ← 可能多个,串起来是完整数据流
[IEND chunk]                   ← 结束标记
```

IDAT 内部又是:
```
[ZLIB header: 2 字节(CMF + FLG)]
[DEFLATE data: compressed blocks]
  每个 block:
    [header: 1 bit final + 2 bit type]
    [LZ77 + Huffman 编码的数据]
[Adler-32 checksum: 4 字节]
```

DEFLATE 解出来是**filtered scanline**:
```
[filter type: 1 字节]
[scanline data: width × bytesPerPixel 字节]
[filter type: 1 字节]
[scanline data: ...]
...
```

每个 scanline 经过 5 种 filter 之一(None/Sub/Up/Average/Paeth)反向操作,才是**原始像素**。

你以后再看一张 PNG,看到的是一个**多层嵌套的二进制结构**,你能立刻说出每一字节是什么。这是"读规范能力"的具体体现。

### 对"压缩"的新认知

很多人对"压缩"的理解停留在"用 zip 压一下"。读完 Phase 7,你理解压缩是两层:

**第一层:LZ77 滑动窗口**。找重复字符串,用 `(distance, length)` 引用替换。这一层**消除冗余**——同一段数据出现两次,只存一次 + 指针。

**第二层:Huffman 编码**。统计字符频率,高频字符短编码,低频字符长编码。这一层**消除信息熵冗余**——用变长编码逼近香农极限。

DEFLATE 是 LZ77 + Huffman 的串联。ZIP、gzip、zlib 都是 DEFLATE 的容器。理解了 DEFLATE,你就理解了 90% 的无损压缩格式。

工业界应用:
- **HTTP gzip**:浏览器和服务器之间的数据压缩。理解 DEFLATE 你就能解释为什么 gzip 对图片几乎无效(图片已经是高熵数据,无可压缩冗余)。
- **Brotli / Zstandard**:DEFLATE 的进化版,但思路一样——LZ77 + 熵编码。
- **JPEG / BCn / ASTC**:有损压缩,但同样有"找冗余 + 熵编码"的两层结构。

### 对"二进制解析"的新认知

读 Phase 7 之前,你看到"big-endian u32"会愣一下。读完之后,你一眼看出文件格式的字节序问题。

Phase 7 教给你的二进制解析纪律:
1. **明确字节序**:大端(网络序)还是小端(x86)?PNG 全大端。ELF 头有标志位。PE 是小端。
2. **对齐**:数据是否对齐?C struct 有 padding,Rust 的 `#[repr(C)]` 也有。手工解析要跳过 padding。
3. **变长整数**:LEB128(用于 Protobuf / WASM)、varint(用于 GLB extensions)、SLEB128(用于 DWARF)。这些是"用 1-5 字节表示任意大小整数"的编码。
4. **位级操作**:bit field、bit mask。PNG 的 Huffman 编码要按 bit 读,不按 byte。
5. **错误处理**:碰到非法数据怎么办?严格报错(安全)还是 best-effort(兼容)?PNG 解码器两者都常见。

这些纪律**跨格式通用**。读完 Phase 7,你看任何二进制格式,都能用这套思路分解。

### 对"实时系统"的新认知

Phase 7 教的不只是 PNG。子项目 E(资产热重载)教的是**实时系统的文件监听**——这是工业级开发工具的核心。

具体说,你看 Visual Studio Code:你改一个文件,VSCode 立刻显示。这是文件监听 + 增量解析。
你看 `cargo check`:你改 Rust 代码,cargo 自动重新编译。这是文件监听 + 增量构建。
你看 Unreal Engine:你改材质,游戏立刻应用。这是文件监听 + 资产热重载。

这些都是 Phase 7 子项目 E 教的能力。Linux 用 `inotify`,macOS 用 `FSEvents`,Windows 用 `ReadDirectoryChangesW`。Rust 的 `notify` crate 抽象了这三个。

读完 Phase 7,你能自己写一个"watch 目录 + 自动响应"的工具。这是**DevOps 工具链的核心**——CI/CD、热重载、文件同步,本质都是文件监听。

### 一个具体的"读完 Phase 7 后能做什么"清单

假设你刚读完 Phase 7。一周内你能做出这些:

**Day 1-2**:用纯 Rust(无依赖)写一个 `cat` 替代品,显示任意二进制文件的 hex dump + ASCII。
**Day 3**:用 `notify` crate 监听一个目录,文件变化时执行命令。本质是简化版 `entr` 工具。
**Day 4-5**:扩展你的 PNG 解码器,支持 JPEG 解码(另一套算法:离散余弦变换 + 量化 + Huffman)。这是 Phase 7 能力的**正迁移**。
**Day 6**:写一个 ZIP 文件浏览器——列出 ZIP 内容、解压单文件。ZIP 内部是 DEFLATE,你已经会。
**Day 7**:写一个 .hha 文件查看器,显示资产包里的所有 sprite + metadata。

这一周内,你**完全脱离 `image` / `zip` / `flate2` 库**,自己实现核心逻辑。这是开源黑客的标志性能力。

工业界真实场景:
- **Mozilla Firefox 工程师**:浏览器要解 WebP / AVIF / JPEG XL 新格式。`image` 库还没支持。你要自己写或贡献给上游。
- **Telegram 客户端**:Telegram 用了自定义的 sticker 格式(.tgs,本质是 LZ4 压缩的 Lottie JSON)。客户端要解。库支持不全。你要自己写。
- **游戏 modding 社区**:你拿到一个商业游戏的资产包,格式自定义。想提取里面的贴图。你要自己写解码器。

这些都是 Phase 7 教你的能力。**你不只学会了 PNG,你学会了"读规范 + 实现规范"的通用工程方法**。

## 结语

Phase 7 是 Handmade Hero 的"成人礼"。它要求你抛弃"调库就完事"的舒适区,把抽象层一层一层剥开,直到看见字节。这个过程痛苦——一个 Huffman 树写错,整张图就花屏;一个 reconstruction filter 反向算错,像素偏移成鬼影。但你完成后,看任何文件格式都"透明"。

Casey 在 Day 459(子项目 D 收官)说:**"这 7 集可能是整个 Handmade Hero 最值得的 7 集。其他集教你'怎么做事',这 7 集教你'怎么理解'。"** 这句话不是夸张——Phase 7 的回报是终身的。

祝你在这 140 天里,看见字节的形状。

## 附录:Phase 7 学习路径建议

### 路径 A:严格按 Casey 节奏(适合深度学习者)

按 day 编号顺序读 day436 → day465。每天配 Handmade Hero 视频(每集约 1.5-2 小时)。这一路径估计 60-90 天完成子项目 A-E。再花 3-6 个月做子项目 F-J 的代表性天数。

**优点**:深度。
**缺点**:慢。可能拖到 Phase 8 都没开始。

### 路径 B:跳到 PNG 解码器(适合实用主义者)

直接从 day453 开始,跳过子项目 A-C。学完 day453-459 后,自己写一个 mini PNG 解码器(目标:能解任一 RGB PNG)。再回头补子项目 A-C 的光照采样。

**优点**:快速看到成果。
**缺点**:跳过基础可能后期回填代价大。

### 路径 C:从工程视角切入(适合想做编辑器的人)

直接跳到子项目 E(day460-465)看资产热重载,然后跳到 Phase 7 后半(day500+)看 in-game editor。回头再补 PNG。

**优点**:贴近工业开发。
**缺点**:PNG 部分要补,否则资产管线不完整。

### 路径 D:做项目驱动学习

挑一个具体项目(如:写一个 Rust 版的 `feh` 图片查看器),按需读 Phase 7 相应天数。需要解 PNG 就读 day453-459;需要文件监听就读 day460-461;需要 GUI 就读子项目 F。

**优点**:动力足。
**缺点**:覆盖不全,可能错过关键概念。

### 共同建议(无论选哪条路径)

1. **配代码**:每篇 day 文件配一段可运行的 Rust 代码,自己跑一遍。
2. **写笔记**:每篇 day 文件读完,写 200 字总结——你学到了什么?还有什么不懂?
3. **改一改**:每篇 day 文件读完后,改一个东西——比如换参数、加边界 case、改算法实现。看结果是否符合预期。
4. **配视频**:Handmade Hero 视频是付费的($15),但 Casey 偶尔在 YouTube 发免费片段。即便没付费,本仓库的 day 文件应该足够自学。

### 推荐配套工具

- **`xxd`** / **`hexdump`**:Linux 二进制查看。每篇 PNG 相关 day 都要配 hex dump。
- **`pngcheck`**:PNG 验证工具。能告诉你 chunk 结构。
- **`python3 -c 'import struct; ...'`**:快速解析二进制。
- **`binwalk`**:对未知文件做"逆向工程扫描"。
- **`Ida Pro` / `Ghidra`**:高级反汇编(Phase 7 之后的进阶)。

Arch Linux 上安装:
```bash
sudo pacman -S xxd pngcheck python binwalk
# Ghidra 在 AUR
yay -S ghidra
```

### 推荐书单(可选)

- **"Real-Time Rendering", Akenine-Möller et al.**:图形学圣经。Phase 7 子项目 A 光照采样对应第 14 章。
- **"Computer Graphics: Principles and Practice", Hughes et al.**:基础教材。
- **"PNG: The Definitive Guide", Greg Roelofs**:PNG 权威书(免费在线)。
- **RFC 1950 / 1951 / 2083**:zlib / DEFLATE / PNG 的官方规范。Phase 7 子项目 D 的圣经。

在线资源:
- W3C PNG spec: https://www.w3.org/TR/png/
- RFC 1950 (zlib): https://datatracker.ietf.org/doc/html/rfc1950
- RFC 1951 (DEFLATE): https://datatracker.ietf.org/doc/html/rfc1951
- "A primer on DEFLATE": https://github.com/madler/zlib/blob/master/doc/algorithm.txt

读完这些,你写自己的 PNG 解码器 / ZLIB 库 / DEFLATE 实现都没问题。
