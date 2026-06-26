---
phase: 5
type: bridge
title: "从 Phase 5 走到 Phase 6:渲染能跑,该让它好看"
domains: [graphics, gpu, math, rust]
prereqs: ["day176", "day235"]
---

# Bridge · 从 Phase 5 到 Phase 6

> 你刚把 Phase 5 走完。60 天。你的代码现在能在 GPU 上跑——OpenGL 上下文、shader、纹理、FBO、immediate-mode UI、ECS、网络。Phase 4 跑 60 FPS 的软件渲染器,Phase 5 变成了 GPU 渲染器,FPS 跑到 144+。你心想:渲染这块我已经会了。然后呢?——然后就是:**该让它好看**。Phase 5 你渲染出来的东西"能跑",但"扁平、塑料感、看起来像 2005 年的游戏"。Phase 6 是 Handmade Hero 全程"图形学深度"最大的一段——你之前学的 Phong 光照只是入门,Phase 6 进入**光照模型 / 阴影 / PBR / TAA** 的工业级渲染。本文是过桥指南。

## §0 · 你已经走过的路

Phase 5 的 60 天,你完成了 GPU 渲染管线 + ECS + UI + 网络四个核心组件。按时间顺序复盘:

- **Day 176-200**:OpenGL + Shader + FBO + 立即模式 UI。OpenGL 上下文、VBO/IBO、顶点 / 片段 shader、纹理、Phong 光照在 GPU 上、FBO 渲染到纹理、immediate-mode 调试 UI。**这一段你把 Phase 3+4 的 CPU 渲染器完整移植到 GPU**。

- **Day 201-210**:debug 隔离 + ECS 深化。`#[cfg(feature = "debug")]` 隔离调试代码。ECS 从 sparse array 演化到 archetype-based ECS(structure of arrays,按组件组合分组)。**这是工业级 ECS 的完整演化**,Bevy / Unity DOTS / Unreal Mass 都是这个架构。

- **Day 211-220**:ECS 系统调度 + 多线程。系统是"对一组组件的操作",系统能并行调度(无组件冲突的系统同时跑)。lock-free 任务调度器升级。**ECS + 多线程是现代游戏引擎的核心架构**。

- **Day 221-230**:网络多人游戏。client-server 模型、状态同步、client-side prediction(客户端预测 + 服务器校正)、rollback(回滚)。**这是 HH 全程唯一一段网络内容**,FORTNITE / Overwatch / Valorant 都是这套架构。

- **Day 231-235**:整理 + 反思。Phase 5 收官,你拥有"现代游戏引擎的核心"(图形 + 物理 + AI + 网络 + ECS + UI),只是每个都是简化版。

Phase 5 全程最值得记住的三件事:

**第一,GPU 编程的核心心智**——"CPU-GPU 通信最小化,GPU 并行最大化"。draw call 数、buffer 上传 / 下载字节数,都要监控。**每帧 5000 个 draw call 是性能杀手**,工业级做法是 instancing / batching。

**第二,ECS 的核心架构**——structure of arrays,按组件组合分组(archetype),系统是"对一组组件的操作"。**这是现代游戏引擎的事实标准**——Unity DOTS、Unreal Mass、Bevy、Flecs、Entitas 都是这个架构。读完 `/home/sun/src/handmade-hero-guide/days/phase-5/deep-dives/ecs-evolution.md` + `ecs-data-layout.md` + `ecs-system-scheduling.md` 你看任何 ECS 都不迷路。

**第三,立即模式 UI 的设计哲学**——每帧重新声明 UI 状态,无持久化。`if ui::button("click") { ... }` 返回是否点击,**简洁、无状态泄漏、易调试**。**这是现代游戏调试 UI 的主流**,Dear ImGui / egui / Nuklear 都是这套。读完 `/home/sun/src/handmade-hero-guide/days/phase-5/deep-dives/immediate-mode-ui.md` 你能在自己项目里写调试 UI。

接下来 Phase 6 是 Day 236-435(200 天,HH 全程最长的一段),主要内容:**把 GPU 渲染从"能跑"升级到"好看"**。具体四件事:
1. **光照模型深化**:从 Phong 升级到 Blinn-Phong,再到 PBR(Physically Based Rendering,基于物理的渲染)。
2. **阴影**:shadow mapping、cascaded shadow maps、shadow filtering。
3. **后处理**:HDR + tone mapping、bloom、SSAO、TAA。
4. **GPU 并行**:多线程渲染、GPU compute、deferred vs forward 渲染路径。

Phase 6 是 HH 全程最长、最技术密集的一段。Phase 6 走完,你拥有**工业级渲染管线**——商业游戏的大部分视觉效果(金属感、玻璃、阴影、辉光)你都能做。

## §1 · 进入 Phase 6 前的能力盘点

**A. OpenGL / GPU 基础**
- [ ] 你能写完整的"渲染一个有纹理 + 光照的 3D 立方体"的 OpenGL 代码。VBO 创建、shader 编译、uniform 设置、draw call。
- [ ] 你理解 OpenGL 状态机模型——bind 之后再操作,unbind 释放。
- [ ] 你能用 RenderDoc 抓一帧,查看每个 draw call 的输入输出。
- [ ] 你理解 z-buffer、深度测试、背面剔除在 OpenGL 里怎么开(`glEnable(GL_DEPTH_TEST)`, `glEnable(GL_CULL_FACE)`)。

**B. Shader 编程**
- [ ] 你能写一个完整的 vertex + fragment shader(光照 + 纹理)。
- [ ] 你理解 uniform / attribute / varying(in / out)的区别。
- [ ] 你理解 GLSL 的数据类型:vec2/3/4, mat2/3/4, sampler2D。
- [ ] 你能在 shader 里做矩阵乘法、向量点乘 / 叉乘、纹理采样。

**C. FBO / 后处理基础**
- [ ] 你能创建 FBO,把场景渲染到纹理而不是屏幕。
- [ ] 你理解"渲染到纹理"的用途——后处理(模糊、bloom)、屏幕空间效果(SSAO、TAA)、镜子。
- [ ] 你理解"多采样抗锯齿"(MSAA)——FBO 配 multisample texture。

**D. 数学准备(Phase 6 关键)**
- [ ] 你能解释 Phong 公式:`ambient + diffuse * max(0, dot(N, L)) + specular * pow(max(0, dot(R, V)), shininess)`。
- [ ] 你能解释"线性空间"和"sRGB 空间"的区别——所有光照计算应在线性空间,最终输出转 sRGB 给显示器。
- [ ] 你理解 HDR(High Dynamic Range)——光照值允许超过 1.0,最后用 tone mapping 压缩到 [0, 1]。
- [ ] 你知道 PBR 是什么——基于物理的渲染,使用 BRDF(Bidirectional Reflectance Distribution Function),用真实的物理参数(粗糙度、金属度)而不是经验值。

**E. ECS + 系统调度**
- [ ] 你理解 archetype-based ECS——entity 按组件组合分组,同组的 entity 连续存储。
- [ ] 你能写一个"系统"(system):`fn update_positions(positions: &mut [Position], velocities: &[Velocity])`。
- [ ] 你理解系统能并行调度——无组件冲突的系统同时跑。
- [ ] 你理解"组件"(component)是纯数据,"系统"是纯逻辑,entity 是组件的集合。**这就是 ECS 的全部**。

**F. 心理建设**
- [ ] 你接受了"PBR 比 Phong 难一个数量级"——但效果震撼。
- [ ] 你接受了"图形 bug 调试特别难"——颜色不对、表面有黑斑、阴影 acne,要会看图猜原因。
- [ ] 你接受了"Phase 6 是 HH 最长的一段"——200 天,坚持下来需要耐心。

## §2 · 自测题

下面 6 道题。

### 题 1(渲染管线)

写出 OpenGL 渲染一个带纹理的 3D 立方体的完整流程(从 CPU 数据到屏幕像素)。

**参考答案**:

```
1. CPU:定义 24 个顶点(6 面 × 4 顶点)和 36 个索引(6 面 × 2 三角形 × 3 顶点)
2. CPU:创建 VBO,上传顶点数据(位置 + 法向量 + 纹理坐标)
3. CPU:创建 IBO(Index Buffer Object),上传索引
4. CPU:创建纹理(gl::GenTextures),上传像素数据(gl::TexImage2D)
5. CPU:编译 vertex shader 和 fragment shader,链接成 program
6. CPU:设置 attribute 指针(位置、法向量、纹理坐标各自的偏移和步长)
7. 每帧:
   a. CPU:更新 uniforms(MVP 矩阵、光源位置、相机位置)
   b. CPU:bind program, bind VBO, bind IBO, bind texture
   c. CPU:gl::DrawElements(TRIANGLES, 36, UNSIGNED_INT, ...)
   d. GPU 顶点着色器:对每个顶点,MVP 变换位置到 clip space
   e. GPU:光栅化(把三角形变成像素)
   f. GPU 片段着色器:对每个像素,采样纹理,计算 Phong 光照,输出颜色
   g. GPU:深度测试、模板测试、混合
   h. GPU:写 framebuffer(屏幕)
8. swap buffers
```

每一步都要会。Phase 6 后期(延迟渲染)这个流程会有大改——先把这版"前向渲染"(forward rendering)搞透。

### 题 2(Blinn-Phong)

写出 Blinn-Phong 的 specular 公式。它和 Phong 的差别是什么?为什么 Blinn-Phong 更"对"?

**参考答案**:

Phong specular:
```
R = reflect(-L, N)  // 反射方向
specular = pow(max(0, dot(R, V)), shininess)
```

Blinn-Phong specular:
```
H = normalize(L + V)  // 半向量
specular = pow(max(0, dot(N, H)), shininess)
```

差别:Phong 用"反射方向和视线方向的夹角",Blinn-Phong 用"法向量和半向量的夹角"。**两者数学不等价**,但 Blinn-Phong 更接近真实物理。

为什么 Blinn-Phong 更"对":
1. **更接近真实 BRDF**:真实表面的高光分布更符合"半向量"模型。
2. **计算更便宜**:`H = (L + V) / |L + V|` 比 `R = 2 * dot(L, N) * N - L` 简单。
3. **shininess 参数不同**:Blinn-Phong 的 shininess 大约是 Phong 的 4 倍,但视觉效果一致。

Phase 6 早期(光照深化)从 Phong 切换到 Blinn-Phong。Phase 6 中期(从 Blinn-Phong 切换到 PBR)是更大的跳跃。

### 题 3(线性空间 vs sRGB)

为什么光照计算要在"线性空间"做?如果你在 sRGB 空间做光照,会出什么问题?

**参考答案**:

显示器的输出是非线性的:`output = input^2.2`(近似)。这就是 sRGB 空间——为了让人眼感觉"亮度均匀",sRGB 编码后,数字 0.5 大约是物理亮度的 0.21(0.5^2.2)。

**光照计算**应该反映物理光的行为:**两束光叠加,亮度直接相加**。这是线性空间的性质——`L1 + L2` 在线性空间是"两束光的物理亮度叠加"。

如果在 sRGB 空间做光照(直接相加两个 sRGB 值),**结果不正确**。两束 sRGB 0.5 的光相加,sRGB 1.0,但物理亮度是 1.0,不是 0.21 + 0.21 = 0.42。

具体表现:
- **光照过曝**:暗部变亮,亮部更亮,对比度看起来不对。
- **颜色失真**:某些颜色组合在 sRGB 空间相加得到"脏"颜色。

正确流程:
1. 读纹理:sRGB → 线性(纹理硬件通常自动做,`gl::SRGB8_ALPHA8` 内部格式)。
2. 光照计算:线性空间。
3. 后处理:bloom、tone mapping,全在线性空间。
4. 最终输出:线性 → sRGB(着色器里 `pow(color, 1/2.2)`,或硬件 sRGB framebuffer)。

Phase 5 你可能没完全做对(因为 Casey 也是逐步演化),Phase 6 早期 Casey 修正这点。

### 题 4(Shadow Mapping 原理)

什么是 shadow mapping?写下它的基本算法。

**参考答案**:

Shadow mapping 是最常用的实时阴影算法。基本思想:**如果一个像素从光源看不见,那它就在阴影里**。

算法:
1. **渲染 shadow map**:把摄像机放在光源位置,渲染场景,**只存深度**(不存颜色)。这个深度图叫 shadow map。
2. **渲染场景**:把摄像机放回正常位置,渲染场景。在 fragment shader 里,对每个像素:
   a. 把它的世界坐标变换到"光源视角"的 clip space。
   b. 采样 shadow map 在这个位置的深度。
   c. 比较这个像素的深度和 shadow map 的深度。
   d. 如果像素深度 > shadow map 深度,说明有更近的物体挡住了光,**这个像素在阴影里**。
   e. 阴影里的像素,光照贡献 = 0(只算环境光)。

伪 shader:
```glsl
// fragment shader
vec3 light_pos = ...;  // 光源位置
vec3 frag_to_light = ...;
float frag_depth_in_light_space = ...;  // 变换到光源空间后的深度
float shadow_map_depth = texture(shadow_map, light_uv).r;
float shadow = (frag_depth_in_light_space > shadow_map_depth + bias) ? 0.0 : 1.0;
// shadow = 0 表示在阴影里,1 表示被光照
color = ambient + shadow * (diffuse + specular);
```

shadow mapping 的问题:
- **shadow acne**(阴影条纹):精度问题导致部分像素"自阴影"。用 bias 偏移解决。
- **peter panning**(阴影脱离物体):bias 太大导致阴影和物体分离。
- **锯齿**(hard edges):shadow map 分辨率不够。用 PCF(Percentage Closer Filtering)多次采样平滑。
- **远距离阴影精度差**:用 cascaded shadow maps(CSM),多张 shadow map 不同距离。

Phase 6 中期(阴影深化)详细做这些。

### 题 5(ECS archetype)

下面是 archetype-based ECS 的简化代码。补全 `query` 函数。

```rust
struct World {
    // 按"组件组合"分组,每组连续存储同组合的 entity
    archetypes: Vec<Archetype>,
}

struct Archetype {
    // 这个 archetype 的组件类型签名
    signature: Signature,
    // 每个组件的连续数组
    storages: HashMap<ComponentId, Box<dyn ComponentStorage>>,
}

trait ComponentStorage {
    fn as_any(&self) -> &dyn Any;
    fn as_any_mut(&mut self) -> &mut dyn Any;
}

// 实现:每个组件类型一个 storage
struct TypedStorage<T> { data: Vec<T> }

impl<T: 'static> ComponentStorage for TypedStorage<T> {
    fn as_any(&self) -> &dyn Any { self }
    fn as_any_mut(&mut self) -> &mut dyn Any { self }
}

impl World {
    // 查询:返回所有 archetype 里"同时拥有 A 和 B"的 (A, B) 元组迭代器
    fn query<A: 'static, B: 'static>(&self) -> Vec<(&[A], &[B])> {
        ???
    }
}
```

**参考答案**:

```rust
impl World {
    fn query<A: 'static, B: 'static>(&self) -> Vec<(&[A], &[B])> {
        let a_id = ComponentId::of::<A>();
        let b_id = ComponentId::of::<B>();
        let required = Signature::from(&[a_id, b_id]);

        let mut result = vec![];
        for arch in &self.archetypes {
            // archetype 的 signature 必须包含所有需要的组件
            if !arch.signature.contains(&required) { continue; }

            // 从 storage 取出强类型数组
            let a_storage = arch.storages.get(&a_id).unwrap()
                .as_any().downcast_ref::<TypedStorage<A>>().unwrap();
            let b_storage = arch.storages.get(&b_id).unwrap()
                .as_any().downcast_ref::<TypedStorage<B>>().unwrap();

            result.push((&a_storage.data, &b_storage.data));
        }
        result
    }
}

// 用法
for (positions, velocities) in world.query::<Position, Velocity>() {
    for i in 0..positions.len() {
        // 两个数组并行索引
        positions[i] += velocities[i] * dt;
    }
}
```

关键点:
- **archetype 是"组件组合"的分组**。所有有 `{Position, Velocity}` 组件的 entity 在同一个 archetype 里。
- **每个组件连续存储**(`Vec<Position>`, `Vec<Velocity>`),**cache 友好**。
- **查询返回元组切片**,系统可以直接 `for i in 0..n` 遍历,无虚函数调用。
- **多个 archetype 可能都满足查询**——查询返回多个切片对,系统逐个处理。

这是工业级 ECS 的核心架构。Bevy / Flecs / Unity DOTS / Unreal Mass 都是这个架构的变种。

### 题 6(立即模式 UI)

immediate-mode UI 和 retained-mode UI 的核心差别是什么?各有什么优缺点?

**参考答案**:

**immediate-mode UI**(立即模式):每帧重新声明 UI 状态。
```rust
fn draw_ui(ui: &mut Ui) {
    if ui.button("click me") {  // 每帧都调用
        println!("clicked");
    }
}
```

**retained-mode UI**(保留模式):UI 是一棵持久化的树。
```rust
let button = Button::new("click me");
button.on_click(|| println!("clicked"));
window.add_child(button);
// 后续每帧 UI 框架自己绘制 button,无需手动调用
```

| 维度 | Immediate-mode | Retained-mode |
|---|---|---|
| 状态 | 无(每帧重新声明) | 有(UI 树持久化) |
| 调试 | 易(每帧从头) | 难(状态分散) |
| 性能 | 中(每帧重画) | 好(只画变化的) |
| 数据绑定 | 直接(`if ui.slider("x", &mut x)`) | 复杂(observer / MVVM) |
| 代码量 | 少 | 多(每个控件要写类) |
| 适用 | 游戏调试 UI、工具 UI | 应用 UI(VSCode、Photoshop) |

immediate-mode 优点:
- **代码简洁**:没有类层次,直接函数调用。
- **无状态**:每帧从头,bug 不积累。
- **数据绑定天然**:`&mut x` 直接传地址,UI 修改即数据修改。

immediate-mode 缺点:
- **性能**:每帧重画所有控件(但调试 UI 量小,影响小)。
- **复杂布局难**:动画、过渡、嵌套滚动需要"记忆"上帧状态,immediate-mode 不擅长。

retained-mode 优点:
- **性能好**:只重画变化的控件。
- **复杂布局**:CSS-like 布局、动画、过渡。

retained-mode 缺点:
- **代码冗长**:每个控件一个类。
- **数据绑定复杂**:observer 模式、signal / slot、双向同步。

游戏调试 UI 几乎都用 immediate-mode(Dear ImGui / egui)。应用 UI 几乎都用 retained-mode(Qt / GTK / WinUI)。

## §3 · 心智切换:从"渲染能跑"到"渲染好看"

Phase 5 的 60 天,你的心智是"**功能完整**"——画三角形、有纹理、有光照、有 UI。代码风格是"先把功能跑通"。

Phase 6 的 200 天,你的心智要切换到"**视觉效果**"——同样的渲染管线,你要问"为什么我渲染的金属看起来像塑料?为什么我的阴影有锯齿?为什么我的玻璃看起来不像玻璃?"。代码风格是"调参 + 数学"。

具体 5 条切换:

**1. 从"经验光照"到"基于物理的光照"**。
Phase 5 你写 Phong:`specular = pow(dot(R, V), shininess)`。`shininess` 是经验值,你试 8、32、128 看哪个好看。
Phase 6 你写 PBR:`specular = D * G * F / (4 * dot(N, L) * dot(N, V))`。D 是法线分布函数(GGX),G 是几何遮蔽(Schlick-Smith),F 是菲涅尔效应。**每个公式有物理意义**,参数(粗糙度 roughness、金属度 metalness)对应真实物理量。

心智切换:**从"调出好看"到"算出正确"**。PBR 渲染的物体在不同光照下表现一致,因为它是物理正确的。Phong 物体换个光照就"破功",因为经验值只对一种场景好看。

**2. 从"无阴影"到"动态阴影"**。
Phase 5 你没有阴影——物体看起来"飘着",没有空间感。
Phase 6 你写 shadow mapping,物体在阴影里、在光下,**立体感立刻出现**。

心智切换:**阴影是空间感的核心**。一个物体没有阴影,看不出它在地面上 1 米还是 0.5 米。**视觉真实感 60% 来自阴影**。

**3. 从"LDR(Low Dynamic Range)"到"HDR + tone mapping"**。
Phase 5 你渲染的颜色在 [0, 1],超过就 clamp 到 1。结果:"太阳直接照到的地方"和"普通亮的地方"看起来一样亮——都是 1.0。
Phase 6 你用 HDR,光照值允许超过 1.0(太阳是 10.0,普通光是 0.5)。最后用 tone mapping 把 [0, +∞] 压缩到 [0, 1] 给显示器。**亮的地方真的"亮",有"过曝感"**。

心智切换:**真实世界光是 HDR 的,显示器是 LDR 的。中间用 tone mapping 桥接**。这一步让画面"有电影感"。

**4. 从"无后处理"到"全套后处理"**。
Phase 5 你渲染直接到屏幕。
Phase 6 你渲染到 HDR 浮点 FBO,然后做后处理:bloom(亮处发光)、SSAO(屏幕空间环境光遮蔽,角落变暗)、TAA(时间抗锯齿,用历史帧信息)、color grading(调色)、tone mapping。**最后才到屏幕**。

心智切换:**渲染管线变成"前向 / 延迟渲染 → HDR FBO → 后处理链 → LDR 屏幕"**。每一步都是可控的视觉风格调整。

**5. 从"前向渲染"到"前向 vs 延迟权衡"**。
Phase 5 你的渲染流程:每个三角形,在 fragment shader 里算光照。如果有 100 个三角形覆盖同一像素,fragment shader 跑 100 次,**光只算一次就够**(因为像素只显示一个颜色)。
Phase 6 你写"延迟渲染"(deferred rendering):先渲染几何到 G-buffer(存位置、法向量、颜色等),后处理一遍算光照。**每像素只算一次光照**,适合多光源场景。

心智切换:**不同渲染路径适合不同场景**。前向渲染简单、适合少光源、支持 MSAA。延迟渲染复杂、适合多光源、不支持 MSAA。**没有银弹**,看场景选。

切换的最大陷阱:**性能审美双线作战**。Phase 6 你既追求"好看"(PBR、HDR、阴影、bloom),又追求"快"(60+ FPS)。两者常常冲突——PBR 比 Phong 慢、bloom 比 no bloom 慢、TAA 比 no AA 慢。**取舍是 Phase 6 的核心**。

工业级做法:** LOD(Level of Detail) + 可配置质量**。低端机用低质量渲染(无 TAA,简化 PBR),高端机用高质量。Phase 6 收尾时你会理解为什么 AAA 游戏有"画质设置"。

## §4 · 进 Phase 6 第一周学习路径

**Day 236-245(对应 HH day236-245)**:**OpenGL 集成完成 + 光照修正**。
重点:Phase 5 末尾 OpenGL 集成完成,Phase 6 早期 Casey 修正光照——线性空间、Gamma 校正、Blinn-Phong。这是 Phase 5 → Phase 6 的过渡。
产出:渲染的画面颜色"对了",不像 Phase 5 时"扁平"。

**Day 246-260(对应 HH day246-260)**:**法线贴图 + 视差贴图**。
重点:法线贴图让低多边形看起来高多边形(每个像素有"细节法向量")。视差贴图更进一步,模拟"位移"。
产出:一面墙的法线贴图打开,立刻有"砖缝"细节。

**Day 261-280(对应 HH day261-280)**:**阴影**。
重点:shadow mapping 基础、bias、PCF 软阴影、cascaded shadow maps(远距离高精度)。
产出:物体在地面上有正确的软阴影。
建议:读 `/home/sun/src/handmade-hero-guide/days/phase-6/deep-dives/shadow-mapping.md`。

**Day 281-310(对应 HH day281-310)**:**环境光照 + IBL**。
重点:Image-Based Lighting(基于图像的光照)——用 HDRI 环境图作为光源。天空盒。环境反射。
产出:金属物体反射环境,玻璃透明。
建议:读 `/home/sun/src/handmade-hero-guide/days/phase-6/deep-dives/lighting-models.md`。

**Day 311-345(对应 HH day311-345)**:**PBR 完整实现**。
重点:PBR 理论(Cook-Torrance BRDF)、GGX 法线分布、菲涅尔、几何遮蔽、金属度 / 粗糙度工作流。PBR 材质编辑。
产出:你写的渲染器能渲染和商业游戏媲美的金属 / 塑料 / 玻璃。
建议:读 `/home/sun/src/handmade-hero-guide/days/phase-6/deep-dives/pbr-complete.md`。

**Day 346-380(对应 HH day346-380)**:**HDR + tone mapping + bloom**。
重点:HDR framebuffer(浮点格式)、tone mapping(Reinhard、ACES、Uncharted 2)、bloom(亮处发光)。
产出:画面有"电影感"。
建议:读 `/home/sun/src/handmade-hero-guide/days/phase-6/deep-dives/post-processing.md`。

**Day 381-410(对应 HH day381-410)**:**TAA + 抗锯齿**。
重点:MSAA、FXAA、TAA(Temporal Anti-Aliasing)。TAA 用上一帧信息做抗锯齿,需要 motion vector。
产出:画面无锯齿,运动流畅。
建议:读 `/home/sun/src/handmade-hero-guide/days/phase-6/deep-dives/taa-and-upscaling.md`。

**Day 411-435(对应 HH day411-435)**:**延迟渲染 + 收尾**。
重点:G-buffer、deferred vs forward 的权衡、light culling(tiled / clustered)。
产出:延迟渲染器跑起来,多光源场景性能比前向好。
建议:读 `/home/sun/src/handmade-hero-guide/days/phase-6/deep-dives/deferred-and-clustered.md`。

第一周结束你应该有:光照修正后的渲染器,看起来"颜色对了"。**这是 Phase 6 的开端**——后面 195 天持续打磨。

## §5 · 实战项目建议

### 项目 A:PBR 渲染器

写一个完整的 PBR 渲染器。技术栈:Rust + OpenGL + GLSL。

需求:
- Cook-Torrance BRDF(GGX + Schlick-Smith + Fresnel-Schlick)。
- 金属度 / 粗糙度工作流。
- IBL(Image-Based Lighting)环境光。
- 至少一个方向光 + 一个点光源。
- HDR + tone mapping。

时间预算:1-2 个月。

为什么推荐:PBR 是现代渲染的事实标准。Unreal / Unity / Godot 默认 PBR。**做完这个项目,你看任何 PBR 实现都不迷路**。

参考资源:learnopengl.com 的 PBR 章节(Boboola 翻译的中文版),和 `/home/sun/src/handmade-hero-guide/days/phase-6/deep-dives/pbr-complete.md`。

### 项目 B:阴影 demo

写一个阴影演示。技术栈同上。

需求:
- 一个方向光,cascaded shadow maps。
- 一个点光源,cube shadow map(omnidirectional shadow)。
- PCF 软阴影。
- 一个交互的物体(鼠标拖动),阴影实时更新。

时间预算:2-3 周。

为什么推荐:阴影是 3D 渲染最难做好的部分之一。**做完这个项目,你对实时阴影的所有 trick 都心里有数**。

### 项目 C:Post-processing pipeline

写一个后处理管线。技术栈同上。

需求:
- HDR framebuffer。
- bloom(亮处发光,多次高斯模糊)。
- tone mapping(可选 ACES / Reinhard / Uncharted 2)。
- color grading(LUT 颜色查找表)。
- TAA(可选)。

时间预算:2-3 周。

为什么推荐:后处理是"画面感"的最后一步。**没有后处理的 PBR 看起来"差一口气"**——加了 bloom 和 tone mapping,立刻"电影感"。

## §6 · 推荐配合的 deep-dive

`/home/sun/src/handmade-hero-guide/days/phase-5/deep-dives/` 里进 Phase 6 前值得读的:

### `shader-basics.md`(强推荐)

shader 编程基础。Phase 6 你会大量写 shader,这篇是基础。

### `fbo-and-render-to-texture.md`(强推荐)

FBO 完整讨论。Phase 6 全程用 FBO(渲染到 HDR 浮点纹理)。

### `opengl-context-creation.md`(可选,Phase 5 已读则跳)

---

`/home/sun/src/handmade-hero-guide/days/phase-6/deep-dives/` 里的推荐:

### `lighting-models.md`(强推荐,Phase 6 早期读)

光照模型完整演化:Phong → Blinn-Phong → PBR。Phase 6 早期核心。

### `pbr-complete.md`(强推荐,Day 311+ 读)

PBR 的完整实现。Cook-Torrance BRDF 的所有公式 + 代码。**Phase 6 中期核心**。

### `shadow-mapping.md`(强推荐,Day 261+ 读)

阴影映射的完整讨论。基础 shadow map、PCF、CSM。

### `deferred-and-clustered.md`(推荐,Day 411+ 读)

延迟渲染 + 聚簇渲染。Phase 6 后期。

### `post-processing.md`(推荐,Day 346+ 读)

后处理完整管线:bloom、SSAO、color grading、tone mapping。

### `taa-and-upscaling.md`(推荐,Day 381+ 读)

TAA + 升采样(DLSS / FSR 原理)。

### `depth-buffer-precision.md`(可选)

深度缓冲精度问题。Phase 6 后期遇到 z-fighting 时参考。

### `light-attenuation.md`(可选)

光照衰减的物理模型。点光源、聚光灯。

### `normal-mapping.md`(强推荐,Day 246+ 读)

法线贴图的完整推导。

### `color-science-deep.md`(可选)

色彩科学:色彩空间、色温、色域。深入理解 sRGB / Rec.709 / Rec.2020。

---

## 结语

Phase 5 是"用 GPU 渲染",Phase 6 是"让 GPU 渲染好看"。Phase 5 完成时你能渲染带光照的 3D 场景,Phase 6 完成时你的场景看起来"和商业游戏差不多"。

Phase 6 第一周你会觉得"光照修正是小事"。**坚持下来**,你会发现"线性空间"和"sRGB 空间"的差别贯穿整个图形学,做不对的代码处处出 bug。

Phase 6 中期(PBR)你会觉得"Cook-Torrance 公式好长"。**坚持下来**,你会发现每个公式项有明确的物理意义——D 是"微表面法向量分布",G 是"微表面相互遮蔽",F 是"菲涅尔反射率"。**理解了每一项,PBR 就是几个公式的乘法**。

Phase 6 后期(TAA、延迟渲染)你会觉得"为什么这么复杂"。**坚持下来**,你会发现这些技术是工业级渲染管线的标配,**做完这个项目,你的渲染器接近 AAA 级别**。

Phase 6 全程 200 天,是 HH 最长的一段。**耐心** 是这一段最重要的品质。每一段深挖的 deep-dive 都值得反复读——`/home/sun/src/handmade-hero-guide/days/phase-6/deep-dives/` 有 15 篇文章,几乎覆盖工业级渲染的所有主题。

下一站:Day 236。修正光照,开始追求"好看"。
