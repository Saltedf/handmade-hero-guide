# 参考资料(只读,subagent 撰写时按需查)

本目录是 subagent 撰写 dayNNN.md 时按需读取的参考材料索引。
所有外部资料只取 **合法可再分发** 版本;具体章节由 subagent 用 WebFetch 按需抓取。

## 已落库的本地资料

### `hh-slices/` — Handmade Hero 路线图 JSON 切片

每个 phase 一个文件,内含:
- `phase_meta`:阶段标题、范围、目标、Rust 主题、CS 补充、推荐资源
- `episodes`:Casey 官方 episode 列表(标题、URL、难度、时长)
- `lessons`:每天已有的 lesson 数据(why / model / map / exercises / supplements)

补充文件:
- `_mental_models.json` — 10 个核心心智模型(4 层深度)
- `_concepts.json` — 37 张概念卡
- `_theory.json` — 6 个理论板块
- `_intro_to_c.json` — Intro to C 系列(10 集)
- `_handmade_ray.json` — Handmade Ray 系列(5 集)
- `_handmade_chat.json` — Handmade Chat 深度话题(17 集)

## 外部参考(subagent 按需 WebFetch)

### 🦀 Rust

| 资料 | URL | 许可证 | 覆盖什么 |
|---|---|---|---|
| The Rust Book | https://doc.rust-lang.org/book/ | MIT/Apache 2.0 | 从零到中级,所有权/borrow/trait/lifetime/error/iter/closure/smart ptr/concurrency |
| The Rust Reference | https://doc.rust-lang.org/reference/ | MIT/Apache 2.0 | 语法语义权威,查具体语法 |
| Rustonomicon | https://doc.rust-lang.org/nomicon/ | MIT/Apache 2.0 | unsafe / FFI / 内部细节 |
| Rust Atomics and Locks | https://marabos.nl/atomics/ | 公开章节 | atomic / Ordering / Mutex / RwLock 深入 |
| Comprehensive Rust (Google) | https://google.github.io/comprehensive-rust/ | Apache 2.0 | Rust 速通 + 异步 + 安全 |
| Cargo Book | https://doc.rust-lang.org/cargo/ | MIT/Apache 2.0 | workspace / features / build.rs / cdylib |
| std lib docs | https://doc.rust-lang.org/std/ | MIT/Apache 2.0 | 按模块查(`std::sync`, `std::arch`, `std::ffi`) |
| Rust By Example | https://doc.rust-lang.org/rust-by-example/ | MIT/Apache 2.0 | 代码示例查 |
| Rust FFI Omnibus | http://jakegoulding.com/rust-ffi-omnibus/ | 公开 | C-Rust FFI 实例 |
| This Week in Rust 周刊 | https://this-week-in-rust.org/ | CC BY-NC-SA | 生态动态 |

### 🎨 图形学

| 资料 | URL | 许可证 | 覆盖什么 |
|---|---|---|---|
| 3D Math Primer | https://gamemath.com/book/ | 免费在线 | 向量、矩阵、四元数、坐标变换、欧拉角/四元数 |
| LearnOpenGL | https://learnopengl.com/ | CC BY-NC 4.0 | 现代 OpenGL 全套:管线、shader、光照、模型加载、PBR |
| The Book of Shaders | https://thebookofshaders.com/ | CC BY-NC-SA 4.0 | GLSL fragment shader 入门到精深 |
| Physically Based Rendering | https://pbr-book.org/ | CC BY-NC-ND 4.0(可引用不可改) | 路径追踪、PBR 理论,完整书 + 源码 |
| Scratchapixel | https://www.scratchapixel.com/ | 免费在线 | 软光栅化 / 软光线追踪 / 光照模型教程 |
| GAMES101 (闫令琪) | https://www.bilibili.com/video/BV1X7411F744 | 免费 | 现代图形学概论(线性代数、光栅化、几何、光线追踪、PBR) |
| GAMES202 | https://www.bilibili.com/video/BV1YK4y1M7zV | 免费 | 实时高质量渲染 |
| OpenGL Wiki | https://www.khronos.org/opengl/wiki/ | CC BY-SA 3.0 | OpenGL 上下文 / 扩展 / FBO / VAO |
| Khronos glTF Spec | https://registry.khronos.org/glTF/ | 免费规范 | 3D 模型文件格式 |
| Real-Time Rendering | https://www.realtimerendering.com/ | 书,引用参考文献 | 实时渲染权威综述(网站有附录和参考) |

### 🎮 游戏编程

| 资料 | URL | 许可证 | 覆盖什么 |
|---|---|---|---|
| Game Programming Patterns | https://gameprogrammingpatterns.com/ | CC BY-NC 3.0 | Nystrom 全本免费,设计模式在游戏里 |
| Handmade Hero Wiki | https://handmade.wiki/HandmadeHero | CC BY-SA | HH 系列笔记/术语/索引 |
| Handmade Network | https://handmade.network/ | 公开 | 社区文章 / 论坛 |
| Casey's GitHub | https://github.com/HandmadeHero/ | 公开源码 | HH 原版 C 源码 |
| Milton (Casey 的画图工具) | https://github.com/serge-rgb/milton | MIT | 真实项目参考 |

### 🐧 Linux 系统编程

| 资料 | URL | 许可证 | 覆盖什么 |
|---|---|---|---|
| The Linux Programming Interface | https://man7.org/tlpi/ | 书(有样章) | 系统编程圣经(64 章 + 1500 页)|
| APUE 3rd ed | https://www.apuebook.com/ | 书(有样章) | Stevens 的 UNIX 编程,样章公开 |
| CS:APP 3rd ed | http://csapp.cs.cmu.edu/ | 书(有样章) | Bryant/O'Hallaron,程序员的计算机系统 |
| Linux man pages | https://man7.org/linux/man-pages/ | GPL-2.0+ | 系统调用/库函数权威(在线) |
| Arch Wiki | https://wiki.archlinux.org/ | GNU FDL 1.3 | Linux 工具、配置、内核、systemd |
| kernel.org docs | https://www.kernel.org/doc/html/latest/ | GPL | 内核子系统文档 |
| lwn.net | https://lwn.net/ | 公开(部分订阅) | 内核深度文章 |
| Brendan Gregg perf | http://www.brendangregg.com/perf.html | 公开 | perf / flamegraph / eBPF 工具链 |
| perf examples | https://www.brendangregg.com/perf.html#examples | 公开 | 具体命令模板 |

### 🔢 数学

| 资料 | URL | 许可证 | 覆盖什么 |
|---|---|---|---|
| 3D Math Primer | https://gamemath.com/book/ | 免费在线 | 游戏数学(同上图形学条目) |
| Immersive Linear Algebra | http://immersivemath.com/ila/ | 免费在线 | 互动式线性代数 |
| Immersive Math | http://immersivemath.com/ | 免费在线 | 全套高等数学互动 |
| Khan Academy Linear Algebra | https://www.khanacademy.org/math/linear-algebra | CC BY-NC-SA 3.0 | 视频教程 |
| Essence of Linear Algebra (3Blue1Brown) | https://www.youtube.com/playlist?list=PLZHQObOWTQDPD3MizzM2xVFitgF8hE_ab | 免费 | 直觉式线代 |

### 🔧 工具链 / Arch

| 资料 | URL | 许可证 | 覆盖什么 |
|---|---|---|---|
| Arch Wiki: Rust | https://wiki.archlinux.org/title/Rust | GNU FDL 1.3 | Arch 上 Rust 工具链 |
| Arch Wiki: mold | https://wiki.archlinux.org/title/Mold | GNU FDL 1.3 | mold 链接器 |
| Arch Wiki: perf | https://wiki.archlinux.org/title/Perf | GNU FDL 1.3 | perf profiling |
| Arch Wiki: GDB | https://wiki.archlinux.org/title/GDB | GNU FDL 1.3 | gdb |
| Arch Wiki: systemd | https://wiki.archlinux.org/title/Systemd | GNU FDL 1.3 | systemd |
| Arch Wiki: pacman | https://wiki.archlinux.org/title/Pacman | GNU FDL 1.3 | 包管理 |
| rustup docs | https://rust-lang.github.io/rustup/ | MIT/Apache 2.0 | 工具链管理 |
| cargo docs | https://doc.rust-lang.org/cargo/ | MIT/Apache 2.0 | 包/workspace |

## 常用 Rust crate 速查(subagent 可按需查 docs.rs)

- **窗口/显示**:`winit`(窗口),`softbuffer`(framebuffer 上屏),`glutin`(OpenGL 上下文),`glfw`,`sdl2`
- **OpenGL**:`glow`(多后端 binding),`glium`,`ash`(Vulkan),`wgpu`(WebGPU)
- **音频**:`cpal`(底层),`rodio`(高层),`kira`(游戏音频)
- **输入**:`gilrs`(手柄),`device-query`,`rdev`
- **动态加载**:`libloading`(dlopen 封装)
- **数学**:`nalgebra`(线性代数),`glam`(游戏优化),`cgmath`,`nalgebra-glm`
- **图像**:`image`(decoders),`lodepng`(纯 Rust PNG)
- **SIMD**:`std::arch::x86_64`,`wide`,`packed_simd`,`portable-simd`(nightly)
- **并发**:`rayon`(并行迭代),`crossbeam`,`parking_lot`
- **错误处理**:`anyhow`,`thiserror`,`eyre`
- **序列化**:`serde`,`serde_json`,`bincode`,`rmp-serde`
- **内存**:`bumpalo`(arena),`typed-arena`,`slotmap`(代际索引)
- **构建脚本**:`cc`(编译 C 依赖),`bindgen`(从 C 头生成 binding),`cmake`
- **热重载**:`hot-lib-reloader`,`cargo-watch`
- **诊断**:`tracing`,`env_logger`,`slog`

┌───────────┬──────────────────────────────────────────────────────────┬────────────────────────────────────────────────────────────────────────────────────────────┐
  │   领域    │                    黄金标准课程/教材                     │                                     “一学期”的真正含义                                     │
  ├───────────┼──────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────┤
  │ 图形      │ CMU 15-462 + Berkeley CS184 + pbrt + Real-Time Rendering │ 约20次讲座 + 10次递进作业，构建一个真实的代码库 (Scotty3D:                                 │
  │           │                                                          │ Rasterizer→MeshEdit→PathTracer→Animation)                                                  │
  ├───────────┼──────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────┤
  │ GPU/实时  │ CMU 15-469 (Visual Computing Systems)                    │ 对 GPU 架构 + 显式 API 的深入探讨                                                          │
  ├───────────┼──────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────┤
  │ 音频/DSP  │ Stanford CCRMA Music 320A→320B→320C                      │ 一个三门课程的序列 (信号→DSP→实时插件)                                                     │
  ├───────────┼──────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────┤
  │ 系统      │ MIT 6.S081 (xv6)                                         │ 11个实验，构建一个真实的内核                                                               │
  ├───────────┼──────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────┤
  │ 物理/动画 │ CMU 15-464 + 15-763                                      │ 基于论文的实现序列                                                                         │
  ├───────────┼──────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────┤
  │ 游戏特有  │ CMU 15-466 + Swink Game Feel + Nystrom Game Programming  │ 基于代码库的游戏开发                                                                       │
  │           │ Patterns                                                 │                                                                                            │
  ├───────────┼──────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────────────────────────────────────┤
  │ 网络      │ Gaffer on Games (Glenn Fiedler)                          │ 多篇文章的 netcode 课程                                                                    │
  └───────────┴──────────────────────────────────────────────────────────┴────────────────────────────────────────────────────────────────────────────────────────────┘
