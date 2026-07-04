
# Bridge · 从 Phase 3 到 Phase 4

> 你刚把 Phase 3 走完。41 天。屏幕上有一个能旋转、有纹理、有光照的 3D 立方体。你能从摄像机视角看一个 3D 世界,你能写一个完整的软件光栅化器(纯 CPU,不靠 GPU),你能用矩阵变换把任何 3D 物体放到世界任何位置。你心想:这就是 3D 游戏的核心。然后呢?——然后就是:**让它跑得快**。Phase 3 你的软件渲染器大概能跑 20-30 FPS,小场景勉强流畅。Phase 4 是 Handmade Hero 全程"工程化"最重的一段——你之前写"能跑就行"的代码,Phase 4 你要把它升级到"稳定 60 FPS、内存受控、资产有序、字体可读"。本文是过桥指南。

## §0 · 你已经走过的路

Phase 3 的 41 天,你完成了 2D → 3D 的世界观切换。按时间顺序复盘:

- **Day 71-78**:3D 数学基础。`Vec3`、`Vec4`(齐次坐标)、`Mat4`(4x4 矩阵)。变换矩阵(平移、旋转、缩放)、view 矩阵(摄像机)、投影矩阵(透视)。这是 Phase 3 全程的数学基础,**这一周你建立了 3D 直觉**。

- **Day 79-83**:软件光栅化入门。三角形从"3 个 3D 顶点"变成"屏幕上一堆像素"。扫描线填充、重心坐标插值、纹理映射。**这一段你写了第一版软光栅化器**。

- **Day 84-90**:Phong 光照模型。环境光 + 漫反射 + 镜面反射 = Blinn-Phong。法向量概念。**3D 渲染从此不是"画形状",是"画有光感的东西"**。

- **Day 91-100**:更多几何 + 优化。立方体、平面、球。视锥裁剪(摄像机看不见的东西不画)。背面剔除(背对摄像机的三角形不画)。**这是 Phase 3 第一次性能优化**,Phase 4 会大规模扩展。

- **Day 101-105**:深度处理。画家算法(按深度排序)→ z-buffer(每像素存深度)。深度冲突(z-fighting)和精度问题。**z-buffer 是 Phase 3 性能最大的"基础设施"**,所有 3D 渲染都用。

- **Day 106-111**:法线贴图 + Gamma 校正 + 反思。法线贴图让低多边形模型看起来"高多边形"。Gamma 校正确保颜色线性空间下计算。Phase 3 收官。

Phase 3 全程最值得记住的两件事:

**第一,3D 直觉的建立**。第 1-2 周(3D 数学)你被矩阵和投影折磨,但坚持下来,你建立了"看到 3D 场景能在脑子里反推变换"的能力。这是 3D 程序员的**核心能力**。**`/home/sun/src/handmade-hero-guide/days/phase-3/deep-dives/projection-matrices.md`** 这一篇把投影矩阵的每一项几何意义写清楚了,值得反复读。

**第二,软件光栅化的完整理解**。Phase 3 你写的光栅化器,是 GPU 的"软件版"。**理解了软件光栅化,你就理解了 GPU**——GPU 不过是硬件加速版的同样算法。Phase 5 你学 OpenGL 时,会发现 OpenGL 的大部分概念(顶点着色器、片段着色器、深度测试、纹理采样)你已经会了,只是接口不同。

接下来 Phase 4 是 Day 112-175(64 天),主要内容:**把"能跑"的代码升级到"工程级"**。具体六件事:
1. SIMD(单指令多数据):CPU 一条指令算 4-16 个 float。
2. 多线程:8 核 CPU 并行算。
3. lock-free 数据结构:多线程无锁通信。
4. 自定义资产格式(.hha):不再读零散 BMP/WAV。
5. 自定义内存分配器:不用 system malloc。
6. TrueType 字体渲染:游戏里能显示文字。

Phase 4 是 HH 全程"工程化密度"最大的一段。Phase 3 你的代码"能跑",Phase 4 你的代码"跑得快、跑得稳、跑得有工程美学"。

## §1 · 进入 Phase 4 前的能力盘点

进 Phase 4 之前的能力清单。

**A. 3D 数学**
- [ ] 能从零推导透视投影矩阵的每一项。`/home/sun/src/handmade-hero-guide/days/phase-3/deep-dives/projection-matrices.md` 有完整推导,你应该能在白纸上重写。
- [ ] 能解释 view 矩阵和世界矩阵的差别:view 把世界变换到摄像机视角,world 把局部坐标变换到世界坐标。两者都是 4x4 矩阵,但**用途相反**。
- [ ] 能写出叉乘 `cross(a, b)` 的公式:`(a.y*b.z - a.z*b.y, a.z*b.x - a.x*b.z, a.x*b.y - a.y*b.x)`。叉乘在 Phase 4 大量使用(求法向量、求平面方程)。
- [ ] 能解释"齐次坐标"为什么需要——为了用矩阵乘法表示平移。Phase 3 §2 题 4 已经讲过。

**B. 软件光栅化**
- [ ] 能写出 `draw_triangle(p0, p1, p2, color)` 的最简代码:bounding box + 重心坐标判断 + 填色。大约 30 行 Rust 代码。
- [ ] 能解释"重心坐标"(barycentric coordinates)是什么——三角形内一个点 P 可以表示成 `P = a*p0 + b*p1 + c*p2`,其中 `a + b + c = 1`。a, b, c 就是重心坐标。
- [ ] 能写出"用重心坐标插值纹理坐标"的代码:对三角形内每个像素,根据重心坐标 `(a, b, c)` 插值顶点的 `(u, v)`,然后从纹理采样。
- [ ] 能解释为什么"画家算法"不够,为什么需要 z-buffer:画家算法对**互相重叠**的三角形排序错,画家算法是 O(n log n) 排序 + 画,z-buffer 是 O(像素数) 每像素比较。

**C. Phong 光照**
- [ ] 能写出 Phong 公式:`color = ambient + diffuse * max(0, dot(N, L)) + specular * pow(max(0, dot(R, V)), shininess)`。其中 N 是法向量,L 是光源方向,R 是反射方向,V 是视线方向。
- [ ] 能解释"环境光"为什么需要——没有环境光,背光面是纯黑,看不见。环境光模拟"间接光"(光在环境中弹射)的简化。
- [ ] 能解释"Gamma 校正":显示器输出是非线性的(`output = input^2.2`),所以光照计算要在**线性空间**做,最后输出前**应用 gamma**。Phase 3 Day 105+ 详细讲。

**D. 性能基础知识**
- [ ] 知道"cache miss"是什么——CPU 取内存如果不在 L1/L2/L3 cache,要从 RAM 取,慢 100 倍。Phase 4 大量讲这个。
- [ ] 知道"内存对齐"——`#[repr(align(64))]` 让 struct 起始地址是 64 的倍数,避免 cache line 跨界。
- [ ] 知道 SIMD 是什么——一条指令同时算 4 个 float(SSE)、8 个 float(AVX2)、16 个 float(AVX-512)。Phase 4 第一周深入。
- [ ] 知道多线程基本概念——thread、mutex、condition variable。Phase 4 后期深入。

**E. 资产管理**
- [ ] 知道你现在怎么加载资产——`image::open("foo.bmp")`、`std::fs::read("foo.wav")`,每个文件单独加载。Phase 4 要打包成单一 `.hha` 文件。
- [ ] 知道为什么"打包"——文件系统打开是慢操作(几十微秒),几百个文件加起来几十毫秒。打包成单文件,一次打开,顺序读取,快得多。
- [ ] 知道"WAV 格式"是什么——PCM 原始样本 + 头部。简单但占空间。
- [ ] 知道"BMP 格式"是什么——未压缩像素 + 头部。简单但占空间。

**F. 心理建设**
- [ ] 你接受了"性能优化是迭代的"——不是一次写对,是先写对再写快,反复 profile 反复优化。
- [ ] 你接受了"多线程代码比单线程代码难写一个数量级"——bug 不复现,race condition 难定位。Phase 4 你会崩溃几次,这是正常的。
- [ ] 你接受了"自己的内存分配器是必要的"——不是矫情,是性能。Phase 4 后期 Casey 演示。

**怎么用这张清单**:逐项打勾。Phase 4 第一周(SIMD)就会用 §A、§B 全部。Phase 4 第 3-4 周(多线程)就会用 §D。Phase 4 后期(资产)就会用 §E。

## §2 · 自测题

下面 6 道题。

### 题 1(光栅化)

写一个最简的 Rust 函数 `draw_triangle(buf, p0, p1, p2, color)`,把三角形 `(p0, p1, p2)` 画成单色 `color`。`p0, p1, p2` 是 `Vec2`(屏幕坐标)。

**参考答案**:

```rust
fn draw_triangle(buf: &mut GameOffscreenBuffer, p0: Vec2, p1: Vec2, p2: Vec2, color: u32) {
    // 1. bounding box
    let min_x = p0.x.min(p1.x).min(p2.x).max(0.0) as u32;
    let max_x = p0.x.max(p1.x).max(p2.x).min(buf.width as f32 - 1.0) as u32;
    let min_y = p0.y.min(p1.y).min(p2.y).max(0.0) as u32;
    let max_y = p0.y.max(p1.y).max(p2.y).min(buf.height as f32 - 1.0) as u32;

    // 2. 三角形的两条边向量
    let v0 = p1 - p0;
    let v1 = p2 - p0;

    // 3. 逐像素扫描
    for y in min_y..=max_y {
        for x in min_x..=max_x {
            let p = Vec2 { x: x as f32 + 0.5, y: y as f32 + 0.5 };
            let v2 = p - p0;

            // 重心坐标(用叉乘计算)
            let d00 = v0.dot(v0);
            let d01 = v0.dot(v1);
            let d11 = v1.dot(v1);
            let d20 = v2.dot(v0);
            let d21 = v2.dot(v1);
            let denom = d00 * d11 - d01 * d01;
            if denom.abs() < 1e-6 { continue; }  // 退化三角形
            let b = (d11 * d20 - d01 * d21) / denom;
            let c = (d00 * d21 - d01 * d20) / denom;
            let a = 1.0 - b - c;

            // 在三角形内当且仅当 a, b, c >= 0
            if a >= 0.0 && b >= 0.0 && c >= 0.0 {
                put_pixel(buf, x, y, color);
            }
        }
    }
}
```

复杂度:O(bounding box 像素数 × 常数)。对每个像素做 10 次浮点运算 + 几次比较。

优化方向(Phase 4 会做):
- SIMD:一次算 4-16 个像素的重心坐标。
- 增量式:每行只算第一个像素,后续像素用差分。
- tile-based:把屏幕分块,块内多线程并行。

### 题 2(性能心智)

下面这段代码,两个版本的差别是什么?哪个更快?为什么?

版本 A:
```rust
struct Entity { pos: Vec3, kind: u32, hp: f32, name: String }
let entities: Vec<Entity> = ...;
for e in &entities {
    if e.kind == MONSTER {
        // AI 逻辑,用 e.pos
    }
}
```

版本 B:
```rust
struct Positions(Vec<Vec3>);
struct Kinds(Vec<u32>);
struct Hps(Vec<f32>);
let positions = ...; let kinds = ...; let hps = ...;
for i in 0..n {
    if kinds[i] == MONSTER {
        // AI 逻辑,用 positions[i]
    }
}
```

**参考答案**:

**版本 B 快得多**。

版本 A 的内存布局:每个 `Entity` 是连续的 `{ pos (12B), kind (4B), hp (4B), name (24B for String ptr+len+cap) }`,共 44 字节(还要加对齐 padding)。1000 个 entity 是 44KB,连续。

遍历时,对每个 entity 取 `kind` 字段。CPU 第一次访问 `entities[0].kind` 会把整个 entity(44B)加载到 cache line(64B)。但循环里只用了 `kind` 和 `pos`(16B),**其余 28B 浪费**了。这叫"poor cache utilization"。

版本 B 的内存布局:`Kinds` 是 `Vec<u32>`,1000 个 u32 连续 4KB。遍历时只访问 `kinds[i]`,CPU 加载一个 cache line(64B)能覆盖 16 个 u32。**cache 利用率 100%**。需要 `positions[i]` 时再独立加载,但 positions 也是连续的(12KB),cache 利用率高。

这就是 ECS 的**核心性能论点**:**Structure of Arrays(SoA)比 Array of Structures(AoS)缓存友好**。Phase 4 后期 Casey 大量用这个,Phase 5 ECS 演化彻底实现。

### 题 3(SIMD 概念)

什么是 SIMD?用一段伪代码对比"标量版"和"SIMD 版"的"4 个 float 相加"。

**参考答案**:

SIMD = Single Instruction Multiple Data。一条指令同时处理多个数据。

标量版(传统):
```
add r1, r2  ; r1 += r2
add r3, r4  ; r3 += r4
add r5, r6  ; r5 += r6
add r7, r8  ; r7 += r8
```
4 条指令,4 个 cycle。

SIMD 版(SSE,128 位寄存器装 4 个 float):
```
addps xmm0, xmm1  ; 4 个 float 同时加
```
1 条指令,1-4 个 cycle。**速度提升 4 倍**。

Rust 写法(用 `std::arch::x86_64`):
```rust
use std::arch::x86_64::*;

unsafe {
    let a = _mm_set_ps(1.0, 2.0, 3.0, 4.0);  // 4 个 float 装入 xmm
    let b = _mm_set_ps(5.0, 6.0, 7.0, 8.0);
    let c = _mm_add_ps(a, b);  // 一条指令,4 个 float 同时加
    // 提取结果
    let result: [f32; 4] = std::mem::transmute(c);
    // result = [6.0, 8.0, 10.0, 12.0]
}
```

AVX2 是 256 位,一次 8 个 float。AVX-512 是 512 位,一次 16 个 float。**SIMD 是图形、物理、音频代码的核心优化**。Phase 4 第一周深入。

### 题 4(z-buffer)

下面两段代码哪个对?为什么?

版本 A(画家算法):
```rust
let mut triangles = collect_triangles();
triangles.sort_by(|a, b| a.center_z.partial_cmp(&b.center_z).unwrap());
for t in triangles {
    draw_triangle(t);  // 后画的覆盖先画的
}
```

版本 B(z-buffer):
```rust
let mut z_buffer = vec![f32::INFINITY; screen_w * screen_h];
for t in triangles {
    for (x, y, z) in t.pixels() {
        if z < z_buffer[y * screen_w + x] {
            z_buffer[y * screen_w + x] = z;
            put_pixel(x, y, t.color);
        }
    }
}
```

**参考答案**:

**版本 B 更通用,版本 A 在某些场景出错**。

版本 A 出错的场景:**三角形互相穿插**(比如两个三角形互相切过对方的平面)。每个三角形的"中心 z"是一个数,但三角形的不同部分 z 不同。按中心 z 排序,某些像素画错了——远三角形的部分像素被画到了近三角形上面。

版本 B 出错的场景:**几乎没有**。z-buffer 是**逐像素**的,每个像素独立判断深度。三角形互相穿插也能正确处理。

性能对比:
- 画家算法:O(n log n) 排序 + O(三角形像素总数)绘制。
- z-buffer:O(三角形像素总数)绘制 + 每像素一次比较 + 一个 z 缓冲区内存(屏幕宽 × 高 × 4 字节,1080p 是 8MB)。

z-buffer 是现代 GPU 的标准方案。**所有商业 3D 游戏都用 z-buffer**(或它的变种,如 hierarchical z-buffer)。Phase 3 Casey 演化到 z-buffer,Phase 4 用它做"early-z"优化(深度测试在像素着色前,看不见的不着色)。

### 题 5(法向量 + 叉乘)

给定一个三角形顶点 `p0 = (0,0,0)`, `p1 = (1,0,0)`, `p2 = (0,1,0)`,求它的法向量。

**参考答案**:

法向量 = 三角形所在平面的垂直方向。

步骤:
1. 算两条边向量:`e1 = p1 - p0 = (1, 0, 0)`,`e2 = p2 - p0 = (0, 1, 0)`。
2. 叉乘:`normal = e1 × e2 = (e1.y*e2.z - e1.z*e2.y, e1.z*e2.x - e1.x*e2.z, e1.x*e2.y - e1.y*e2.x)`
   - `normal.x = 0*0 - 0*1 = 0`
   - `normal.y = 0*0 - 1*0 = 0`
   - `normal.z = 1*1 - 0*0 = 1`
3. 所以 `normal = (0, 0, 1)`。
4. normalize(已经单位向量,无需 normalize)。

这个三角形的法向量是 `(0, 0, 1)`,**指向 +Z 方向**(朝向观察者)。这个三角形躺在 XY 平面上,正面朝 Z 正方向。

**叉乘的顺序很重要**:`e1 × e2` 和 `e2 × e1` 方向相反。**约定**:三角形顶点按**逆时针**(从正面看)排列时,叉乘结果指向正面。Phase 3 后期 Casey 用这个约定做"背面剔除"——背面三角形的法向量背对摄像机,dot(normal, view_dir) < 0,跳过。

### 题 6(锁 / 多线程基础)

下面这段多线程代码有什么问题?怎么修?

```rust
use std::sync::Mutex;
use std::thread;

let counter = Mutex::new(0);
let handles: Vec<_> = (0..10).map(|_| {
    let counter = &counter;  // 借用,不能跨线程
    thread::spawn(move || {
        let mut guard = counter.lock().unwrap();
        *guard += 1;
    })
}).collect();
for h in handles { h.join().unwrap(); }
println!("{}", *counter.lock().unwrap());
```

**参考答案**:

问题:`&counter` 是借用,不能 move 到 thread 里(线程生命周期可能超过借用)。

修复:用 `Arc`(Atomic Reference Counted)共享所有权。

```rust
use std::sync::{Arc, Mutex};
use std::thread;

let counter = Arc::new(Mutex::new(0));
let handles: Vec<_> = (0..10).map(|_| {
    let counter = Arc::clone(&counter);  // 引用计数 +1
    thread::spawn(move || {
        let mut guard = counter.lock().unwrap();
        *guard += 1;
    })
}).collect();
for h in handles { h.join().unwrap(); }
println!("{}", *counter.lock().unwrap());  // 10
```

`Arc` 是原子引用计数,多个线程可以同时持有。`Mutex` 保护内部值的互斥访问。

更深层的问题:**性能**。每帧 1000 个 entity,如果都从主线程加锁到共享 entity list,锁竞争会让多线程退化成单线程。**Phase 4 后期 Casey 用 lock-free work queue 解决**——主线程把"任务"塞进队列,工作线程从队列取任务执行,无锁。

```rust
// lock-free work queue 概念
struct WorkQueue {
    tasks: Mutex<Vec<Task>>,  // 简化版,生产用 lock-free ring buffer
}

impl WorkQueue {
    fn push(&self, task: Task) {
        self.tasks.lock().unwrap().push(task);
    }
    fn pop(&self) -> Option<Task> {
        self.tasks.lock().unwrap().pop()
    }
}

// 主线程:queue.push(Task::UpdateEntity(i));
// 工作线程:while let Some(task) = queue.pop() { do_work(task); }
```

Phase 4 Day 125-126 详细实现 lock-free work queue。

## §3 · 心智切换:从"能跑"到"跑得快"

Phase 3 的 41 天,你的心智是"**功能正确**"——能画三角形就行,能算光照就行,能旋转立方体就行。代码风格是"先写对再说"。

Phase 4 的 64 天,你的心智要切换到"**性能 + 工程**"——同样画 1000 个三角形,你要问"为什么是 30 FPS 不是 60 FPS",要问"内存占用是多少,为什么",要问"能多核并行吗"。

具体 5 条切换:

**1. 从"指令"思维到"内存层次"思维**。
Phase 3 你写代码,假设"读一个变量是 O(1)"。Phase 4 你要建立"内存层次"心智——L1 cache 1ns,L2 cache 4ns,L3 cache 12ns,RAM 100ns,**差距 100 倍**。一个看起来普通的"读字段"操作,可能是 cache miss,**慢 100 倍**。

具体表现:你写 `for e in &entities { sum += e.hp; }`,你以为是 O(n),实际可能是 O(10n),因为每个 entity 的 `hp` 字段都可能 cache miss。

心智切换:**写代码时,不只看指令数,看"内存访问模式"**。连续访问(Vec 索引)cache 友好,跳跃访问(链表 / hash map)cache 不友好。

**2. 从"单核"到"多核"**。
Phase 3 你写代码,假设"只有一个 CPU"。Phase 4 你的 CPU 有 8-16 核,**单核只用了 1/8 算力**。Phase 4 第二周开始你大量写多线程代码。

心智切换的最大陷阱:**多线程不是"加个 thread 就行"**。共享数据要同步,同步有锁,锁有竞争,竞争让多线程退化成单线程。**好的多线程代码不是"用了很多锁",是"几乎不用锁"**——通过数据分块(每个线程独立处理一块数据,无共享)、lock-free 数据结构(原子操作)实现。

**3. 从"标量"到"SIMD"**。
Phase 3 你写 `for i in 0..n { c[i] = a[i] + b[i]; }`,一条指令一次加。Phase 4 你写 SIMD,一条指令同时加 4-16 个数。**速度提升 4-16 倍**。

心智切换:**写循环时,问自己"这个循环能用 SIMD 吗"**。如果是简单的"对每个元素做同样的运算",答案通常是"能"。Rust 有 `wide` crate 包装 SIMD,或者用 `std::arch::x86_64` 直接调 intrinsic。

**4. 从"system malloc"到"自定义分配器"**。
Phase 3 你写 `Box::new`, `Vec::push`,`String::from`,内部都调 system malloc。malloc 是通用的,**对游戏不够好**——游戏每帧分配释放几千次小对象,malloc 内部锁和元数据开销大。

Phase 4 你写**arena allocator**——一次性分配一大块内存,所有对象从 arena 分配,arena 一次性释放(整帧级别)。**这是工业级游戏引擎的标配**(Unreal 用 FMalloc,Unity 用 NativeArray)。

**5. 从"零散文件"到"打包资产"**。
Phase 3 你加载资产是 `image::open("textures/player.bmp")`——打开文件,读字节,解析 BMP。每个文件一次 IO,几百个资产几百次 IO。

Phase 4 你把所有资产**打包成一个 `.hha` 文件**(Casey 自己设计的格式),一次 IO 加载所有,内存映射访问。**这是商业游戏的标准做法**(.pak in Unreal, .assets in Unity, .vpk in Source)。

心智切换:**资产加载从"代码操作"变成"管线操作"**——你写一个 `asset_packer.exe` 把源资产(.bmp / .wav)打包成 `.hha`,游戏只读 `.hha`。这是"工具链"概念的雏形,Phase 7 大规模扩展。

切换的最大陷阱:**过早优化**。Phase 4 你学到 SIMD、多线程、arena,可能想"所有代码都 SIMD 化,所有循环都并行化,所有内存都 arena 化"。**这是错的**。

正确策略(Casey 在 HH 里反复说):
1. 先写对的代码(功能正确)。
2. 测量哪里慢(`cargo flamegraph`,Tracy profiler)。
3. 只优化最慢的 20%(80/20 法则)。
4. 再测量,迭代。

**测量优先于优化**——这是 Phase 4 全程的核心纪律。

## §4 · 进 Phase 4 第一周学习路径

**Day 112-115(对应 HH day112-115)**:**性能心智 + 测量工具**。
重点:Tracy profiler 的安装和使用。`cargo flamegraph` 的使用。心智模型——内存层次、cache line、cache miss。**Phase 4 全程建立在测量基础上,这一周是测量工具入门**。
产出:你能 profile 自己 Phase 3 写的渲染器,看到哪里慢。
建议:读 `/home/sun/src/handmade-hero-guide/days/phase-4/deep-dives/profiling-with-tracy.md`。

**Day 116-121(对应 HH day116-121)**:**SIMD 入门**。
重点:`std::arch::x86_64` 的 intrinsic 函数。`_mm_add_ps`、`_mm_mul_ps`、`_mm_set_ps` 等。把 Phase 3 的 `Vec3` 操作改成 SIMD 版。**这是 Phase 4 第一次性能优化**,把"3 个 float"操作从"3 条指令"变成"1 条指令"(或 4 个 Vec3 同时算)。
产出:渲染器内循环 SIMD 化,FPS 提升 2-4 倍。
建议:读 `/home/sun/src/handmade-hero-guide/days/phase-4/deep-dives/simd-in-rust.md`。

**Day 122-127(对应 HH day122-127)**:**多线程基础 + atomics**。
重点:`std::thread::spawn`、`Arc`、`Mutex`。原子操作(`AtomicU32` 等)、内存顺序(`Ordering::Relaxed` / `Acquire` / `Release`)。**这一段是 HH 全程"难"密度最大的一周**,内存顺序的概念不直觉。
产出:你能写出一个生产者-消费者队列,主线程生产任务,工作线程消费。
建议:读 `/home/sun/src/handmade-hero-guide/days/phase-4/deep-dives/lock-free-programming.md` 和 `/home/sun/src/handmade-hero-guide/days/phase-4/deep-dives/threading-models.md`。

**Day 128(对应 HH day128)**:**反思 + 整理**。
重点:Phase 4 前 2 周代码量极大,做架构整理。把 SIMD 代码独立成 `simd.rs`,把多线程代码独立成 `threading.rs`。

第一周结束你应该有:能用 Tracy profile 自己的代码,能用 SIMD 加速内循环,能写多线程代码(尽管还有 bug)。

## §5 · 实战项目建议

### 项目 A:SIMD 矩阵乘法器

从零写一个 SIMD 加速的 4x4 矩阵乘法。技术栈:Rust + `std::arch::x86_64`。

需求:
- 标量版的 `mat4_mul(a, b) -> Mat4`。
- SIMD 版的 `mat4_mul_simd(a, b) -> Mat4`。
- benchmark 对比,目标 SIMD 版比标量版快 2-4 倍。
- 写测试验证两个版本结果一致。

时间预算:1 周。

为什么推荐:矩阵乘法是图形学最频繁的操作,SIMD 加速它有立竿见影的效果。**而且范围小,容易完成**——4x4 矩阵就 16 个数,手动展开 / SIMD 都好写。

### 项目 B:多线程图像处理器

写一个多线程图像模糊器。技术栈:Rust + `std::thread` + `image` crate。

需求:
- 读一张 PNG 图。
- 用 box blur(3x3 平均)模糊。
- 单线程版作为 baseline。
- 多线程版:把图按行分给 N 个线程并行处理。
- benchmark:多线程版在 8 核 CPU 上要比单线程版快 ~6 倍(为什么不是 8 倍?线程启动 / 同步开销)。

时间预算:1-2 周。

为什么推荐:图像处理是天然可并行的——每个像素独立。**而且实际有用**——做完你能模糊任何图。

### 项目 C:arena allocator

从零写一个 arena allocator。技术栈:纯 Rust。

需求:
- `Arena::new(capacity: usize)`,一次性分配 capacity 字节。
- `Arena::alloc<T>(&self) -> *mut T`,从 arena 分配 sizeof(T) 字节,返回指针。
- `Arena::reset(&self)`,一次性释放所有(把 offset 归零)。
- 不需要 individual free——arena 设计哲学是"分配快,释放一次性"。
- benchmark:对比 system malloc,arena 快 10-100 倍(小对象)。

时间预算:4-7 天。

为什么推荐:arena 是工业级游戏引擎的标配。**理解了 arena,你看 Unreal 的 FMalloc、Bevy 的 Resources 都不迷路**。而且代码量小(50 行 Rust),容易完成。

## §6 · 推荐配合的 deep-dive

`/home/sun/src/handmade-hero-guide/days/phase-3/deep-dives/` 里有几篇进 Phase 4 前值得读的:

### `rasterization-from-scratch.md`(强推荐)

光栅化的完整推导。Phase 4 你要 SIMD 化光栅化器,这篇让你**清楚知道光栅化每一步在做什么**,才能 SIMD 化。

### `simd-progression.md`(强推荐)

SIMD 的渐进式演化,从标量到 AVX2。Phase 4 第一周必读。

### `z-buffer-and-depth-testing.md`(推荐)

z-buffer 的完整讨论。Phase 4 后期用 z-buffer 做"early-z"优化,这篇是基础。

---

`/home/sun/src/handmade-hero-guide/days/phase-4/deep-dives/` 里的推荐:

### `profiling-with-tracy.md`(强推荐,Phase 4 第一天读)

Tracy profiler 的安装、集成、使用。**Phase 4 全程用 Tracy**,这篇让你一次配好。

### `simd-in-rust.md`(强推荐,Day 116 读)

Rust SIMD 的完整指南。`std::arch::x86_64` intrinsic、`wide` crate、auto-vectorization。Phase 4 第一周核心读物。

### `memory-layout-for-cache.md`(强推荐,Day 122+ 读)

cache 友好的内存布局。AoS vs SoA、cache line、false sharing。**Phase 4 中后期必读**。

### `arena-allocator.md`(强推荐,Day 138+ 读)

arena allocator 的完整实现。Phase 4 后期 Casey 大量用 arena,这篇是参考。

### `lock-free-programming.md`(强推荐,Day 124-127 读)

lock-free 数据结构。原子操作、内存顺序、ABA 问题。**Phase 4 难度最大的一周,这篇是救命草**。

### `threading-models.md`(推荐,Day 122 读)

游戏引擎的线程模型——主线程、渲染线程、工作线程、IO 线程。Phase 4 后期参考。

---

## 结语

Phase 3 是"做出 3D 游戏的核心",Phase 4 是"让核心跑得快、跑得稳、跑得有工程美学"。Phase 3 完成时你的代码"能跑",Phase 4 完成时你的代码"能跑 + 能优化 + 能维护"。

Phase 4 第一周你会觉得"SIMD 好难,intrinsic 名字好长"。坚持一周,你会发现 SIMD 的核心就是"一次算多个数",intrinsic 名字虽然长但有规律(`_mm_add_ps` = "multimedia add packed single-precision")。

Phase 4 第二周你会觉得"多线程好难,race condition 找不到 bug"。坚持两周,你会建立"共享状态 = bug 源"的直觉,以后写代码自动避免共享。

Phase 4 后期你会觉得"为什么要写自己的内存分配器,malloc 不够用吗"。读完 `arena-allocator.md`,你会理解 system malloc 的"通用"代价——它要支持任何 size 的分配释放,所以内部数据结构复杂、有锁。**游戏每帧几千次小对象分配,malloc 是瓶颈**。arena 砍掉所有这些复杂度,把游戏场景下分配速度提到 O(1)。

Phase 4 全程的核心纪律是:**测量优先于优化**。任何优化前先 profile,优化后再 profile,确认有效。不测量就优化,90% 是浪费时间。

下一站:Day 112。装好 Tracy,准备 profile 自己的 Phase 3 代码。
