
# Phase 4 · 性能 / 线程 / 资产(Day 112-175)

> 这是 Handmade Hero 的工程化阶段。Phase 3 你写了软光栅化器,但单核单线程、单文件资产。Phase 4 把它升级为工业级:SIMD 加速、多核并行、自定义资产格式(.hha)、自己的声音混音器、通用内存分配器、TrueType 字体渲染。

## 这一阶段在做什么

Phase 3 的最后一天,你的游戏能做这些事:渲染带纹理的 3D 立方体,有简单光照,音频是代码生成的正弦波。但帧率不稳(20-40 FPS),内存布局乱,资产是零散的 BMP/WAV 文件,每次启动都重新加载。

Phase 4 要解决的真问题:**怎么让游戏"工程化"——稳定 144 FPS,内存受控,资产有序,音频真实,字体可读**。

这个问题拆开有六个子问题,Casey 一个一个解决:

**子问题 1:CPU 性能怎么榨干?**(Day 112-121)
游戏卡顿是因为 CPU 算不过来。但 CPU 现在每秒几十亿指令,为什么不够?因为**等待内存**(cache miss),因为**没用 SIMD**,因为**只用了 1 个核**。Casey 在 Day 112 讲心智模型,Day 115 引入 SIMD,Day 121(马拉松!)把渲染拆成 tile 并行化。

**子问题 2:多核怎么用?**(Day 122-131)
现代 CPU 有 8-16 核,单核游戏浪费 87.5% 算力。Day 122 讲多线程,Day 123-124 讲原子操作和内存屏障,Day 125-126 手写 lock-free work queue,Day 127 对齐渲染内存(false sharing),Day 128-131 把多核用到渲染和地面合成。

**子问题 3:资产怎么管?**(Day 132-137)
启动加载所有资产(几百 MB)要几分钟。商业游戏用流式加载——按需加载,后台进行。Day 132 讲 streaming,Day 133-137 把资产系统演化成"类型化 + tag-based"查询。

**子问题 4:音频怎么真实?**(Day 138-146)
代码生成的 sine wave 不像游戏。真实游戏要播放 WAV 文件,多个声音混音,3D 空间音效。Day 138 写 WAV parser,Day 139-140 写混音器,Day 141 流式加载大音频,Day 142-146 优化(音量插值、变调、SIMD)。

**子问题 5:怎么打包资产?**(Day 147-154)
散装的 BMP/WAV 文件 IO 慢。Day 147-149 设计自己的 .hha 二进制格式,Day 150 加载,Day 151-154 新文件 API + 合并多文件 + 查找。

**子问题 6:字体 + 通用分配器**(Day 155-175)
游戏要显示文字,需要 TrueType 字体渲染。Day 162-175 实现。Day 157-161 写通用内存分配器(替代 malloc)。Day 155-156 粒子系统。

完成 Phase 4 后,你的游戏在 8 核机器上稳定 144 FPS,内存峰值可控,资产按需加载,有真实的音效,屏幕上有清晰文字。**架构完整工业级**——后面 Phase 5 切 OpenGL 不会推倒重来。

## 学习目标

完成 Phase 4 后,你能:

- [ ] 解释 CPU cache 层级(L1 / L2 / L3 / RAM)对性能的影响,做 cache-friendly 数据布局
- [ ] 用 SSE / AVX intrinsics 写 SIMD 代码(一次处理 4 / 8 / 16 个 float)
- [ ] 用 `compare_exchange` 写 lock-free 数据结构(ring buffer、stack)
- [ ] 解释 `Ordering::Acquire / Release / SeqCst` 的精确语义
- [ ] 用 `#[repr(align(N))]` 和 `CachePadded<T>` 避免 false sharing
- [ ] 设计并实现 lock-free work queue,把渲染拆 tile 并行化
- [ ] 实现异步资产 streaming(主线程不阻塞,工作线程后台加载)
- [ ] 设计类型化 + tag-based 资产系统(BitmapId / SoundId,newtype 防混用)
- [ ] 手写 WAV / BMP / 自定义二进制格式 parser(RIFF chunk 结构)
- [ ] 实现完整的音频混音器(multi-source mixing、stereo pan、soft clip)
- [ ] 用 cpal 接入 Linux 音频(ALSA / PulseAudio / PipeWire)
- [ ] 设计通用内存分配器(free list、coalesce)
- [ ] 用 STB TrueType 解码字体,渲染字形到屏幕
- [ ] 用 perf c2c / valgrind cachegrind 诊断性能问题
- [ ] 给真实 Rust crate(`crossbeam-queue`、`glam`、`cpal`)提 PR

## 主题索引(按 4 域分类)

### 🎮 游戏编程

- **day112-114**:CPU 性能心智模型、性能计数器、为优化准备函数
- **day115-120**:SIMD 基础、数学运算 SIMD 化、像素打包、宽位掩码、统计 intrinsic、IACA 端口分析
- **day121**:🔥🔥🔥 分块渲染马拉松(tile + SIMD + 多线程)
- **day122-126**:多线程入门、原子操作、内存屏障、work queue 抽象、循环 FIFO 实现
- **day127-131**:对齐渲染内存、push-time transforms、正交投影、无缝平铺、异步合成
- **day132-137**:资产 streaming、类型化组织、tag 映射、类型化数组、多 tag 检索、周期 tag
- **day138-146**:WAV 加载、混音入门、混音器、流式音频、音量插值、变调、SSE 优化
- **day147-154**:.hha 格式定义、写头部、写资产、加载、新文件 API、合并、查找
- **day155-156**:粒子系统、Lagrangian vs Eulerian 模拟
- **day157-161**:🔥 通用内存分配器
- **day158-159**:资产使用跟踪、清理基础设施
- **day162-175**:🔥 字体系统(TrueType、字形提取、文本渲染、对齐、kerning、Unicode)

### 🎨 图形学

- **day115-121**:SIMD 渲染优化(像素打包、掩码、tile 化)
- **day127-130**:对齐、push-time transforms、正交投影、无缝平铺
- **day131**:异步地面合成
- **day155-156**:粒子系统(Lagrangian vs Eulerian)
- **day162-175**:字体渲染(TrueType、bitmap font、kerning)

### 🐧 Linux 系统编程

- **day112-120**:`perf stat` / `perf c2c` / `cachegrind` 性能分析
- **day122-126**:pthread / futex / io_uring(Linux 并发原语)
- **day127**:`getconf LEVEL1_DCACHE_LINESIZE`、cache line 对齐、false sharing
- **day132**:`mmap` / `read` / `posix_fadvise` / `io_uring` 文件 IO
- **day138-146**:ALSA / PulseAudio / PipeWire / cpal 音频栈
- **day147-154**:二进制文件格式、Linux `open`/`read`/`stat`、`dirent` 文件查找
- **day157-161**:`malloc` / `mmap` / `sbrk` 内存分配
- **day165-166**:资产系统并发 bug 调试(gdb、ThreadSanitizer)

### 🦀 Rust 生态

- **day112-120**:SIMD(`core::arch::x86_64::__m128`)、`#[repr(align(N))]`、`MaybeUninit`
- **day122-126**:`std::sync::atomic`(`AtomicUsize`、`AtomicU64`)、`Ordering`(Acquire/Release/SeqCst)、`compare_exchange`
- **day126-127**:`UnsafeCell` + `unsafe impl Sync`、`crossbeam-utils::CachePadded`
- **day128-130**:`enum` + `match`、newtype、字段布局
- **day131**:`AtomicU32` 状态机、`Mutex<Option<Arc<T>>>`、`arc-swap`
- **day132-137**:newtype ID、`HashMap<String, T>`、`HashSet`、`string_interner`、`slotmap`
- **day138-146**:`u32::from_le_bytes`、`chunks_exact`、`std::fs::read`、cpal crate、`Arc<Mutex<T>>`
- **day147-154**:`Cursor` / `byteorder` / `binrw` / `nom` 二进制解析
- **day157-161**:`std::alloc::Layout`、`alloc` / `dealloc`、`Box::new_uninit`
- **day162-175**:STB TrueType(FFI)、`rusttype` / `ab_glyph` crate

## 关键里程碑

### 🔥 Day 112-121 · 性能优化阶段(SIMD + 多核)

整个 Phase 4 最经典的部分。Casey 在 Day 121 单集几小时,把整个软渲染器拆成 tile 并行化。完成这一阶段你的渲染器从 30 FPS 提升到 144 FPS(8 核机器)。

### 🔥 Day 122-131 · 多线程 + work queue

实现 lock-free work queue,主线程产生 task,工作线程消费。这是 Casey 在 C 里靠纪律解决的事,Rust 里你要么 unsafe 要么重新设计避免 unsafe。

### 🔥 Day 138-146 · 手写音频系统

从 WAV 文件到混音器,完整自实现。结束后你完全理解音频管线,不再害怕任何音频 API。

### 🔥 Day 147-154 · 自定义 .hha 二进制格式

设计自己的资产打包格式(类似商业游戏的 .pak / .dat)。理解二进制格式设计原则。

### 🔥 Day 157-161 · 通用内存分配器

实现自己的 malloc / free。理解 free list、coalesce、对齐分配。是 Day 1-156 都用 push buffer / arena,这一阶段开始有真正的"通用"分配。

### 🔥 Day 162-175 · TrueType 字体渲染

字体渲染是图形学里最复杂的主题之一。Day 162-175 完整覆盖:解析 TTF、提取字形、Kerning、Unicode 支持。完成后能在游戏里显示任意文字。

## 阶段项目验收

完成这一阶段后,你的 Rust 项目应该能:

- [ ] 渲染稳定 144 FPS(8 核机器,1280×720)
- [ ] tile-based 并行渲染,8 核 CPU 利用率 > 80%
- [ ] SIMD 优化的光栅化器(每像素 < 10 个 intrinsic)
- [ ] lock-free work queue,主线程零阻塞
- [ ] 异步 chunk streaming,玩家移动无卡顿
- [ ] 类型化资产系统(BitmapId / SoundId 编译期防混用)
- [ ] tag-based 资产查询(find_all / find_matching)
- [ ] 手写 WAV parser,支持 8/16/24/32-bit
- [ ] 完整混音器(多声源、stereo pan、soft clip)
- [ ] cpal 接入声卡,实际播放声音
- [ ] .hha 资产打包格式
- [ ] 通用内存分配器(替代 malloc)
- [ ] TrueType 字体渲染,屏幕显示文字
- [ ] Unicode 支持(至少 BMP,emoji 可选)
- [ ] `cargo run --release` 跑 30 分钟不崩溃,内存稳定

## 开源贡献实践(本阶段)

Phase 4 涉及大量工业级 Rust crate,提 PR 机会多。推荐目标(按难度递增):

1. **`crossbeam-queue`**(https://github.com/crossbeam-rs/crossbeam)—— lock-free 队列。读 `ArrayQueue` 源码,理解 CAS loop 和 sequence number
2. **`crossbeam-utils`** —— `CachePadded<T>`。补 doc / 测试 false sharing 场景
3. **`glam`**(https://github.com/bitshifter/glam)—— 数学库。补 SIMD 优化的 doc,加 perspective / orthographic 矩阵的 LH/RH 解释
4. **`hound`**(https://github.com/paden/hound)—— WAV 库。补 24-bit 解码的 doc
5. **`cpal`**(https://github.com/RustAudio/cpal)—— 音频。读 ALSA 后端,补 callback 实时性约束的 doc
6. **`slotmap`**(https://github.com/orlp/slotmap)—— 代际索引。补 new_key_type! 宏的例子
7. **`bevy_asset`**(https://github.com/bevyengine/bevy)—— Bevy 资产系统。补 Handle strong/weak 差别
8. **`rusttype` / `ab_glyph`**—— 字体库。补 TrueType 解析的 doc

PR 类型建议(从易到难):
- 文档(补 doc、公式、例子)
- 测试(补 edge case)
- 示例(加 runnable example)
- bug(找小 bug 修)
- 重构(只在完全理解时)

## 本阶段用到的 reference/ 资料

主要依据的本地 HH slice:[days/reference/hh-slices/phase-4.json](../reference/hh-slices/phase-4.json)(64 集 lesson 数据)

外部资料(按需 WebFetch):
- Mara Bos *Rust Atomics and Locks*:https://marabos.nl/atomics/ —— Rust 并发的圣经
- 3D Math Primer ch.10 "Texturing":https://gamemath.com/book/texturing.html
- Intel Optimization Manual:https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html
- Mike Acton GDC 2014 "Data-Oriented Design":https://www.youtube.com/watch?v=rX0ItVEVjA4
- Wang tiles:https://en.wikipedia.org/wiki/Wang_tile
- WAV spec:https://www.loc.gov/preservation/digital/formats/fdd/fdd000001.shtml
- TrueType spec:https://developer.apple.com/fonts/TrueType-Reference-Manual/
- Linux ALSA:https://www.alsa-project.org/wiki/Documentation
- io_uring:https://unixism.net/loti/

## Phase 4 内容索引(目录)

按主题分组,数字是天数(dayNNN):

### 性能 + SIMD(day112-121)

- [day112](day112.md) · CPU 性能心智模型
- [day113](day113.md) · 简单性能计数器
- [day114](day114.md) · 为优化准备函数
- [day115](day115.md) · 🔥 SIMD 基础
- [day116](day116.md) · 数学运算 SIMD 化
- [day117](day117.md) · 像素打包
- [day118](day118.md) · 宽位解包与掩码
- [day119](day119.md) · 统计 intrinsic
- [day120](day120.md) · IACA 端口分析
- [day121](day121.md) · 🔥🔥🔥 分块渲染马拉松

### 多线程 + work queue(day122-131)

- [day122](day122.md) · 多线程入门
- [day123](day123.md) · 原子操作
- [day124](day124.md) · 🔥🔥 内存屏障与序
- [day125](day125.md) · 抽象 work queue
- [day126](day126.md) · 循环 FIFO work queue
- [day127](day127.md) · 对齐渲染内存
- [day128](day128.md) · 推送时变换
- [day129](day129.md) · 正交投影
- [day130](day130.md) · 无缝双线性平铺
- [day131](day131.md) · 异步地面区块合成

### 资产系统(day132-137)

- [day132](day132.md) · 资产流式加载
- [day133](day133.md) · 资产初步组织(类型化)
- [day134](day134.md) · 资产映射到位图(string-to-id)
- [day135](day135.md) · 类型化资产数组(generic AssetPool<T>)
- [day136](day136.md) · 基于 tag 的多对多检索
- [day137](day137.md) · 匹配周期性标签

### 音频系统(day138-146)

- [day138](day138.md) · 🔥 加载 WAV 文件
- [day139](day139.md) · 🔥 声音混音入门
- [day140](day140.md) · 实现声音混音器
- [day141](day141.md) · 流式加载大音频
- [day142](day142.md) · 逐样本音量插值
- [day143](day143.md) · 混音器中的变调
- [day144](day144.md) · SSE 混音器前后循环
- [day145](day145.md) · SSE 混音器主循环
- [day146](day146.md) · 累加 vs 显式计算

### .hha 资产打包格式(day147-154)

- [day147](day147.md) · 定义资产文件格式
- [day148](day148.md) · 写资产文件头部
- [day149](day149.md) · 把资产写入资产文件
- [day150](day150.md) · 从资产文件加载
- [day151](day151.md) · 新平台文件 API
- [day152](day152.md) · 新 Win32 文件 API 实现
- [day153](day153.md) · 合并多资产文件
- [day154](day154.md) · 查找资产文件

### 粒子 + 通用分配器(day155-161)

- [day155](day155.md) · 粒子系统入门
- [day156](day156.md) · Lagrangian vs Eulerian 模拟
- [day157](day157.md) · 🔥 通用内存分配入门
- [day158](day158.md) · 跟踪资产使用
- [day159](day159.md) · 清理资产基础设施
- [day160](day160.md) · 基础通用分配
- [day161](day161.md) · 完成通用分配器

### 字体系统(day162-175)

- [day162](day162.md) · 🔥 TrueType 字体入门
- [day163](day163.md) · STB TrueType 处理
- [day164](day164.md) · Windows 字体处理
- [day165](day165.md) · 🔥 修复资产系统线程 bug(debug)
- [day166](day166.md) · 给资产操作加锁
- [day167](day167.md) · 完成 Win32 字体字形提取
- [day168](day168.md) · 渲染文本行
- [day169](day169.md) · 文本对齐到基线
- [day170](day170.md) · 定义字体元数据
- [day171](day171.md) · 资产构建器加字体元数据
- [day172](day172.md) · 提取 kerning 表
- [day173](day173.md) · 精确字体对齐
- [day174](day174.md) · 加稀疏 Unicode 支持
- [day175](day175.md) · 🎉 M4 完成:稀疏 Unicode 支持

## Phase 4 的核心抽象

### 1. Lock-free work queue(Day 122-126)

主线程产生 task,工作线程消费。lock-free 用 `AtomicUsize` head/tail + `compare_exchange` + `Ordering::Acquire/Release`。Rust 实现:`UnsafeCell` + `unsafe impl Sync`,工业级用 `crossbeam-queue::ArrayQueue`。

### 2. SIMD 渲染(Day 115-121)

`__m128` 一次处理 4 个 float。关键 intrinsics:`_mm_load_ps`、`_mm_mul_ps`、`_mm_add_ps`、`_mm_cmpgt_ps`(mask)。`#[repr(align(16))]` 满足 `movaps` 对齐。Day 121 马拉松:tile 化 + SIMD + 多核结合。

### 3. Asset streaming(Day 131-137)

资产状态机:Empty → Composing → Ready。主线程 push 任务到 work queue,工作线程异步加载。`AtomicU32` 状态切换,CAS loop 避免竞争。fallback 渲染未合成 chunk。LRU 淘汰远离玩家的资产。

### 4. 类型化 + tag-based 资产系统(Day 133-137)

newtype ID(`BitmapId(u32)`、`SoundId(u32)`)编译期防混用。`AssetPool<T>` 泛型容器。多 tag 系统(forward + reverse index),`find_matching(&["weapon", "sharp"])` 集合交集查询。周期 tag(`walk_0` / `walk_1` / ...)支持 sprite 动画。

### 5. 手写音频系统(Day 138-146)

WAV parser(RIFF chunk)+ Mixer(多声源相加 + soft clip)+ cpal 集成。每秒 44100 样本 × N 声源 × mix = 几百万操作,CPU 占用 < 1%。SIMD 优化(Day 144-145)4× 加速。

### 6. .hha 二进制打包(Day 147-154)

自定义格式:文件头(magic + version + asset_count)+ 资产索引数组 + 资产数据。一次 IO 读多个资产,降低 syscall。Day 152-154 跨平台文件 API。

### 7. 通用内存分配器(Day 157-161)

替代 `malloc` 的通用分配:free list、coalesce、对齐分配。Day 157 入门,Day 160-161 完整实现。理解系统 malloc 怎么工作,以及为什么游戏开发要自写分配器。

### 8. TrueType 字体(Day 162-175)

TTF 解析 + 字形提取 + kerning + 渲染。Casey 用 STB TrueType(library),也可以直接读 TTF spec。Day 174-175 加 Unicode 支持(UTF-8 解码 + 字形查找)。

## Phase 4 结束后你能做什么

完成 Phase 4,你具备:

- **性能工程**:理解 cache、SIMD、多核,能把任何 hot path 优化到极限
- **并发编程**:会用原子操作、内存屏障、lock-free 数据结构
- **资产管线**:能设计自己的二进制格式,实现 streaming、tag 系统
- **音频引擎**:完整自实现混音器,理解从 WAV 到声卡的整个链路
- **字体渲染**:理解 TrueType,能显示任意文字
- **Linux 系统编程**:深入 ALSA / mmap / io_uring / perf

更重要的是:**你不再害怕"底层"**。当你看到 Casey 在 C 里写 lock-free queue、手写 SIMD、读二进制格式——这些技能你都在 Rust 里实践过。你具备了一个**游戏引擎程序员**的核心能力。

下一步:Phase 5(Debug 系统 + OpenGL 迁移)。把 Phase 4 的多核 / SIMD 软渲染器搬到 GPU,游戏性能再上一个数量级。
