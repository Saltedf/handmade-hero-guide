
# Bridge · 从 Phase 6 到 Phase 7

> 你刚把 Phase 6 走完。200 天。这是 Handmade Hero 全程最长的一段。你的渲染器现在能跑 PBR + IBL + 阴影 + bloom + TAA + 延迟渲染。FPS 在中等场景跑 60-144。画面看起来"和商业游戏差不多"。你心想:渲染这块我已经无敌了。然后呢?——然后就是:**该把这些算法工程化**。Phase 6 你学会的是"算法",Phase 7 是 Handmade Hero 全程"工程化"最深的一段——你手写 PNG 解码器、手写资产打包格式、手写 in-game 编辑器。**从"调库的程序员"变成"理解底层的程序员"**。本文是过桥指南。

## §0 · 你已经走过的路

Phase 6 的 200 天,你完成了 GPU 渲染管线从"能跑"到"好看"的全套升级。按时间顺序复盘:

- **Day 236-260**:光照修正 + 法线贴图。线性空间、Gamma 校正、Blinn-Phong。法线贴图让低多边形看起来高多边形。

- **Day 261-310**:阴影 + IBL。Cascaded shadow maps 远距离高精度、PCF 软阴影。Image-Based Lighting 用 HDRI 环境图作光源,天空盒、环境反射。

- **Day 311-345**:PBR 完整实现。Cook-Torrance BRDF、GGX 法线分布、菲涅尔、几何遮蔽、金属度 / 粗糙度工作流。**这一段是 Phase 6 数学高峰**。

- **Day 346-410**:HDR + tone mapping + bloom + TAA。HDR framebuffer、ACES tone mapping、bloom 多次高斯模糊、TAA 用历史帧信息做抗锯齿。

- **Day 411-435**:延迟渲染 + 聚簇渲染。G-buffer、deferred vs forward 权衡、tiled / clustered light culling 多光源场景。

Phase 6 全程最值得记住的三件事:

**第一,PBR 是现代渲染的事实标准**。Phase 6 中期你写的 Cook-Torrance BRDF,Unreal / Unity / Godot 都用。学完 Phase 6,你看任何商业游戏的渲染代码都能秒懂。**`/home/sun/src/handmade-hero-guide/days/phase-6/deep-dives/pbr-complete.md`** 是 Phase 6 最值得反复读的。

**第二,渲染管线是"前向 / 延迟 → HDR FBO → 后处理链 → LDR 屏幕"**。每一步都可控,每一步都可调。Phase 6 后期你理解了这条完整管线,**你做的任何视觉效果都能放进这个管线**——这就是"工程化"的图形学。

**第三,性能 / 视觉是双线作战**。PBR 比 Phong 慢、bloom 比 no bloom 慢、TAA 比 no AA 慢。**取舍是 Phase 6 的核心**。工业级做法是 LOD + 可配置质量——低端机用低质量,高端机用高质量。

接下来 Phase 7 是 Day 436-575(140 天),主要内容:**把渲染和游戏逻辑工程化**。具体五件事:
1. **PNG 解码器**(从零手写,ZLIB + Huffman + reconstruction filters)。
2. **资产管线**(打包、热加载、in-game 编辑器)。
3. **in-game 编辑器**(在游戏运行时编辑关卡、光照、材质)。
4. **glTF 模型加载**(工业级 3D 模型格式)。
5. **导航网格 + 路径查找**(AI 移动基础)。

Phase 7 是 HH 全程"造轮子含量"最高的一段——Casey 在 Phase 6 一直用现成的 PNG 库,Phase 7 Day 436-462 他**手写完整 PNG 解码器**,从二进制位流一个 bit 一个 bit 解。这是 HH 整个系列的精神核心:**理解底层,不调库**。

## §1 · 进入 Phase 7 前的能力盘点

**A. PBR / 光照(Phase 6 核心)**
- [ ] 你能写出 Cook-Torrance BRDF 的完整公式:`f_r = KD * diffuse + KS * (D * G * F) / (4 * dot(N, L) * dot(N, V))`。
- [ ] 你理解 GGX / Trowbridge-Reitz 法线分布函数、Schlick-Smith 几何遮蔽、Fresnel-Schlick。
- [ ] 你能解释"金属度 / 粗糙度工作流"——金属度 1.0 表示纯金属(无漫反射),粗糙度 0 表示完美镜面,1 表示完全粗糙。
- [ ] 你理解 IBL(Image-Based Lighting)——用 HDRI 环境图作光源。

**B. 阴影 / 后处理**
- [ ] 你能实现 shadow mapping(渲染 shadow map + fragment shader 比较)。
- [ ] 你理解 cascaded shadow maps——多个 shadow map 对应不同距离,精度高。
- [ ] 你理解 HDR + tone mapping(Reinhard / ACES / Uncharted 2)。
- [ ] 你能实现 bloom(亮处发光,多次高斯模糊)。
- [ ] 你理解 TAA 的基本思想——用历史帧 + motion vector 做抗锯齿。

**C. 渲染管线**
- [ ] 你理解前向渲染 vs 延迟渲染的权衡。
- [ ] 你能写出延迟渲染的 G-buffer(位置、法向量、颜色、材质参数多个浮点纹理)。
- [ ] 你理解 tiled / clustered light culling——把屏幕分成块,每块只算影响它的光源。

**D. OpenGL / Shader 熟练**
- [ ] 你能熟练用 OpenGL 4.x 的所有核心 API(VBO、IBO、VAO、FBO、texture、uniform、shader)。
- [ ] 你能写复杂的 GLSL shader(几百行,多个 pass)。
- [ ] 你能用 RenderDoc 调试 GPU 代码,看每个 draw call 的状态和输出。

**E. 二进制 / 文件格式基础(Phase 7 关键)**
- [ ] 你理解"位"(bit)和"字节"(byte),能算"32 位整数占 4 字节"。
- [ ] 你理解"大端"和"小端"——x86 / ARM 都是小端,网络字节序是大端。
- [ ] 你写过简单的二进制解析——比如读 BMP / WAV 文件头。Phase 4 你做过 `.hha`,这是基础。
- [ ] 你理解"压缩"的概念——DEFLATE 是最常见的(PNG、gzip、zip 都用它)。Phase 7 Day 436+ 你手写。

**F. 心理建设**
- [ ] 你接受了"PNG 解码从 bit 开始"——不是夸张,Casey 在 Day 436 真的从 bit 流开始一个 Huffman 树一个 Huffman 树解。
- [ ] 你接受了"in-game 编辑器是工程难度最高的部分之一"——它涉及 UI、热重载、序列化、状态管理。
- [ ] 你接受了"Phase 7 的产出看起来'不酷'"——不是新视觉效果,是"我能编辑资产了"。这是工程化的本质,**功能性强但视觉冲击小**。

## §2 · 自测题

下面 6 道题。

### 题 1(PBR 公式)

写出 Cook-Torrance BRDF 的完整公式,并解释每一项的物理意义。

**参考答案**:

```
f_r(l, v) = k_d * f_lambert + k_s * f_cook_torrance

其中:
f_lambert = albedo / π
f_cook_torrance = (D * G * F) / (4 * (n · l) * (n · v))

D = Normal Distribution Function(GGX / Trowbridge-Reitz):
    D(h) = α² / (π * ((n · h)² * (α² - 1) + 1)²)
    其中 α = roughness²,h = normalize(l + v) 半向量

G = Geometry Function(Smith's method with GGX):
    G(l, v) = G_SchlickGGX(l) * G_SchlickGGX(v)
    G_SchlickGGX(v) = (n · v) / ((n · v) * (1 - k) + k)
    其中 k = α / 2(直接光照)或 (α)² / 2(IBL)

F = Fresnel(Fresnel-Schlick):
    F(h, v) = F0 + (1 - F0) * pow(1 - (h · v), 5)
    F0 是 0 度角反射率,金属用 albedo,非金属用 0.04
```

物理意义:
- **D(法线分布)**:微表面中"法向量朝向 h"的比例。粗糙度低(α 小)时集中,粗糙度高(α 大)时分散。
- **G(几何遮蔽)**:微表面相互遮挡的程度。掠射角(光线擦过表面)时遮蔽多。
- **F(菲涅尔)**:反射率随入射角变化。垂直入射时反射率是 F0,掠射时接近 1(全反射)。
- **k_d 和 k_s**:漫反射和镜面反射的权重。能量守恒:`k_d + k_s <= 1`(金属的 k_d 接近 0,因为金属无漫反射)。

PBR 的核心论点:**用真实物理参数(roughness, metalness)描述材质,渲染结果在所有光照条件下都"物理正确"**。这是 Phase 6 中期的核心。

### 题 2(PNG 格式)

PNG 文件的结构是什么?为什么 PNG 能"无损压缩"?

**参考答案**:

PNG 文件结构:
```
PNG 签名(8 字节):89 50 4E 47 0D 0A 1A 0A
+
多个 Chunk(每个 Chunk):
  - Length(4 字节):data 长度
  - Type(4 字节):chunk 类型(IHDR, IDAT, IEND 等)
  - Data(Length 字节):chunk 数据
  - CRC(4 字节):循环冗余校验

关键 chunk:
- IHDR:图片基本信息(宽、高、位深、颜色类型、压缩方法等)
- IDAT:图像数据(压缩的)
- IEND:文件结束标志
```

PNG 的无损压缩由两步组成:

1. **Reconstruction filters**(重建滤波器):PNG 不是直接压缩像素,而是**先把每行像素"过滤"**(用上一行 / 左边像素 / 左上像素预测当前像素,存差值)。**这一步无损**,目的是让数据更适合压缩。
   - 5 种 filter:None(不过滤)、Sub(减左边)、Up(减上边)、Average(减左上平均)、Paeth(用 Alan Paeth 的预测器)。
   - 每行选最优 filter,编码器自己定。

2. **DEFLATE 压缩**:把过滤后的数据用 DEFLATE 算法压缩。DEFLATE 是 LZ77(滑动窗口字典压缩)+ Huffman 编码(变长编码)。**LZ77 + Huffman 都是无损的**。

所以 PNG 整体无损——过滤无损 + 压缩无损。

Phase 7 Day 436-462 你手写 PNG 解码器,需要实现:
- 文件 chunk 解析。
- IHDR 解析。
- DEFLATE 解压(LZ77 + Huffman,从 bit 流一个 bit 一个 bit 解)。
- 5 种 reconstruction filter 的逆操作。
- 颜色空间转换(可选,gamma / sRGB)。

### 题 3(LZ77)

什么是 LZ77?用一段伪代码描述。

**参考答案**:

LZ77 是 1977 年 Lempel-Ziv 提出的字典压缩算法。核心思想:**用"先前出现过的相同字节串"代替重复**。

伪代码:
```
滑动窗口大小:32KB(向后看)
前瞻缓冲区:待编码的数据

encode(input):
    output = []
    pos = 0
    while pos < len(input):
        # 在滑动窗口里找最长的"和 input[pos..] 匹配的子串"
        match = find_longest_match(input, window_start=pos-32768, current=pos)
        if match.length >= 3:
            # 输出 (距离, 长度) 对,引用先前字节
            output.push((distance=match.distance, length=match.length))
            pos += match.length
        else:
            # 输出原始字节
            output.push(literal=input[pos])
            pos += 1
    return output

decode(compressed):
    output = []
    for token in compressed:
        if token is literal:
            output.push(token.byte)
        else:  # (distance, length)
            start = len(output) - token.distance
            for i in 0..token.length:
                output.push(output[start + i])  # 复制
    return output
```

例子:input = "abcabcabc"
- pos=0,1,2:输出 literal a, b, c
- pos=3:窗口里有 "abc",匹配长度 6(剩余 "abcabc"),输出 (distance=3, length=6)
- pos=9:结束

压缩结果:literal a, literal b, literal c, (3, 6)——9 字节压成 4 token。

LZ77 的特点:
- **无损**。
- **滑动窗口大小决定压缩率**——大窗口找远距离匹配,压缩率高。DEFLATE 用 32KB。
- **解码快**(顺序读),编码慢(每个位置要搜窗口)。

DEFLATE 在 LZ77 基础上加 Huffman 编码——把"literal 字节"和"(distance, length)"编码成变长二进制。**Phase 7 Day 440+ 详细做 Huffman**。

### 题 4(in-game 编辑器)

什么是 in-game 编辑器?它和"外部编辑器"(Blender / Tiled)的差别是什么?

**参考答案**:

**in-game 编辑器**:游戏运行时,直接在游戏画面上编辑内容(关卡、光照、材质、AI 参数),修改实时生效。

**外部编辑器**:用独立的工具(Blender 建模、Tiled 画地图、Substance Painter 调材质),导出文件,游戏加载。

| 维度 | in-game 编辑器 | 外部编辑器 |
|---|---|---|
| 反馈 | 实时 | 离线(导出 → 加载) |
| 学习曲线 | 低(所见即所得) | 高(每个工具一个 UI) |
| 工程复杂度 | 高(嵌入游戏) | 低(独立工具) |
| 协作 | 难(单人编辑) | 好(每个工具自己有协作) |
| 适用 | 关卡、光照、参数 | 模型、纹理、动画 |

工业级做法:**两者结合**。Blender 建模,导出 .glb,游戏加载。游戏里 in-game 编辑器调"关卡布局 / 光照位置 / 物体摆放"。**模型细节用专业工具,布局用 in-game 编辑器**——分工明确。

Unreal / Unity 都有强大的 in-game 编辑器(实际是"editor mode")。Phase 7 后期 Casey 写自己的 in-game 编辑器,虽然简单但功能完整。

### 题 5(glTF 格式)

glTF 是什么?为什么它在 3D 游戏里取代了 OBJ / FBX?

**参考答案**:

glTF(GL Transmission Format)是 Khronos 制定的现代 3D 模型格式。**目标是"3D 的 JPEG"**——统一、高效、易加载。

glTF 的特点:
- **基于 JSON**:场景结构、节点层级、材质描述都是 JSON,人类可读。
- **二进制 buffer**:实际顶点 / 索引数据是二进制(支持嵌入或外部 .bin 文件),高效加载。
- **PBR 材质**:glTF 设计为 PBR-first,材质描述就是 metalness / roughness / base color / normal map 等。
- **动画**:支持骨骼动画、变形目标。
- **扩展性**:通过 extensions 字段支持自定义特性(KHR_extensions 是 Khronos 官方扩展)。

glTF vs OBJ:
- OBJ 是 1990s 的格式,简单(纯文本顶点 / 面),但**不支持 PBR、动画、节点层级**。
- glTF 是 2010s 的格式,完整现代特性,JSON + 二进制混合。

glTF vs FBX:
- FBX 是 Autodesk 私有格式,复杂、闭源,解析需要 SDK 或逆向工程。
- glTF 是开放标准,Khronos 维护,任何项目都能用。

现代游戏引擎(Unreal / Unity / Godot / Bevy)都默认支持 glTF。**Phase 7 后期 Casey 加 glTF 加载**,工业级资产管线的最后一块。

### 题 6(资产管线)

为什么商业游戏不用零散文件(.png / .wav / .obj),而是打包成单一格式(.pak / .assets / .vpk)?

**参考答案**:

至少 5 个理由:

1. **IO 性能**:打开一个文件是慢操作(几十微秒 syscall)。1000 个文件 = 几十毫秒。打包成一个文件,一次打开,顺序读,快得多。

2. **磁盘空间**:打包可以整体压缩(虽然纹理 / 音频通常已压缩,但元数据 / 模型可压缩)。

3. **完整性**:发布时只有一个文件,不会丢。玩家不容易误删 / 修改。

4. **加载顺序**:打包可以预排序——按"加载顺序"排,启动时顺序读,缓存友好。

5. **加密 / 混淆**:打包格式可以加密,防止玩家修改 / 解包(虽然不能完全防,但提高门槛)。

Casey 在 Phase 4 已经设计过 `.hha` 格式(简化版)。Phase 7 升级为更完整的资产管线——加 PNG 解码、glTF 加载、in-game 编辑器的"保存 / 加载"。

## §3 · 心智切换:从"算法"到"工程化"

Phase 6 的 200 天,你的心智是"**算法 + 视觉**"——PBR、阴影、TAA、延迟渲染,你追求"会算"和"好看"。

Phase 7 的 140 天,你的心智要切换到"**工程 + 工具链**"——PNG 解码、资产打包、in-game 编辑器、glTF,你追求"会做底层"和"工作流顺"。

具体 5 条切换:

**1. 从"调库"到"理解底层"**。
Phase 6 你写 PBR shader,但你读 PNG 用 `image` crate,你加载模型用 `gltf` crate。这些是"调库"。
Phase 7 你**从 bit 流手写 PNG 解码**,从字节流手写 glTF 解析。**理解了底层,你看任何库的实现都不迷路**。

心智切换:**调库不是错,但理解底层是程序员的尊严**。Casey 在 HH 里反复说"我用过 image crate,但现在我想真的懂"。Phase 7 是这个"想真的懂"的实现。

**2. 从"功能正确"到"工程化"**。
Phase 6 你写 shader,只要 shader 跑对就行。
Phase 7 你写 in-game 编辑器,你要考虑:
- 数据怎么持久化(修改了关卡,怎么保存到文件)?
- 怎么撤销 / 重做(按 Ctrl+Z 撤销刚才的操作)?
- 怎么多选(框选多个物体一起移动)?
- 怎么复制 / 粘贴?

这些不是"算法",是"工程"。**工业级编辑器的代码量通常是游戏代码本身的 2-3 倍**——Unreal Editor 比 Unreal Engine 大,Unity Editor 也是。

心智切换:**写"工具"比写"游戏"更难**——因为工具要让用户(开发者)用得舒服,而游戏让玩家用得舒服。开发者比玩家更挑剔。

**3. 从"硬编码"到"数据驱动"**。
Phase 6 你写 `let light = Light { pos: Vec3(1, 2, 3), color: ... };`,数据在代码里。
Phase 7 你写 `let lights = load_lights_from_asset("level1.lights.json");`,数据在资产里。

心智切换:**游戏逻辑尽量"通用",具体内容放资产**。这是"游戏引擎"和"游戏"的分界——引擎是通用代码,游戏是资产 + 少量胶水代码。**Casey 在 Phase 7 大量做这个分离**。

**4. 从"启动加载"到"按需加载"**。
Phase 6 你启动时加载所有资产。
Phase 7 你实现 streaming——玩家走到某区域才加载该区域的资产,离开时卸载。**这是开放世界游戏的标配**(GTA、Elden Ring 都是)。

心智切换:**资产不是"准备好的",是"动态流的"**。这要求资产格式支持部分加载、依赖管理、卸载回滚。**Phase 7 后期 Casey 实现这套**。

**5. 从"代码即真理"到"数据即真理"**。
Phase 6 你改关卡,改代码,重新编译。
Phase 7 你改关卡,在 in-game 编辑器里改,**不重新编译**。

心智切换:**编辑器和游戏分离,编辑器是工具,游戏是产品**。**这是工业级游戏开发的核心工作流**——策划 / 美术在编辑器里工作,程序员维护编辑器和引擎。Unreal、Unity 都是这套。

切换的最大陷阱:**过度工程**。Phase 7 你学了资产管线、in-game 编辑器,可能想"什么都自己写一套"。**这是错的**。

正确策略:
- **核心资产格式**:自己写(理解底层)。
- **复杂工具**:用现成的(Substance Painter 调材质,Blender 建模)。
- **游戏特定工具**:自己写(每个游戏有特殊需求)。

Casey 在 HH 里写 PNG 解码器是"理解底层"——他不是说"以后所有 PNG 解码都自己写"。**理解之后用库更熟练**,这才是 Phase 7 的真意。

## §4 · 进 Phase 7 第一周学习路径

**Day 436-442(对应 HH day436-442)**:**PNG 文件格式 + 签名 + IHDR**。
重点:PNG 文件结构、chunk 解析、IHDR(基本图片信息)。
产出:能解析 PNG 头,知道图片是 1920x1080 还是 256x256。

**Day 443-452(对应 HH day443-452)**:**DEFLATE + Huffman**。
重点:从 bit 流一个 bit 一个 bit 解。LZ77 解码、Huffman 树构造、fixed / dynamic Huffman codes。**这是 Phase 7 最难的一周**——你处理 bit 级操作,容错率极低。
产出:能解压 IDAT chunk 拿到过滤后的像素数据。
建议:读 `/home/sun/src/handmade-hero-guide/days/phase-7/deep-dives/deflate-compression.md` 和 `/home/sun/src/handmade-hero-guide/days/phase-7/deep-dives/png-format-complete.md`。

**Day 453-462(对应 HH day453-462)**:**Reconstruction filters + 完整 PNG 解码**。
重点:5 种 filter 的逆操作(None、Sub、Up、Average、Paeth)。把过滤后的数据转成原始像素。最终完成 PNG 解码器。
产出:不依赖 `image` crate,自己从 .png 字节流解码出 RGBA 像素。

**Day 463-475(对应 HH day463-475)**:**资产热重载 + 资产管线**。
重点:文件 watcher 检测资产变化,游戏实时看到。资产打包格式升级(扩展 Phase 4 的 `.hha`)。
产出:改一张 PNG,游戏里实时更新。
建议:读 `/home/sun/src/handmade-hero-guide/days/phase-7/deep-dives/asset-pipeline-architecture.md`。

**Day 476-510(对应 HH day476-510)**:**in-game 编辑器基础**。
重点:in-game 编辑器的 UI、选中、移动、复制、保存 / 加载。state management(撤销 / 重做)。
产出:在游戏里点物体,移动,保存到文件,下次启动加载。
建议:读 `/home/sun/src/handmade-hero-guide/days/phase-7/deep-dives/immediate-mode-editor.md`。

**Day 511-530(对应 HH day511-530)**:**glTF 加载**。
重点:glTF 格式规范(JSON + binary buffer)。PBR 材质映射到 Phase 6 的 shader。骨骼动画(可选)。
产出:加载一个 .glb 模型,带 PBR 材质。
建议:读 `/home/sun/src/handmade-hero-guide/days/phase-7/deep-dives/gltf-and-model-loading.md`。

**Day 531-560(对应 HH day531-560)**:**导航网格 + 路径查找**。
重点:把可走区域生成 navmesh(A* 寻路用)。A* 算法。AI 移动。
产出:怪物能从 A 点走到 B 点,绕开障碍。
建议:读 `/home/sun/src/handmade-hero-guide/days/phase-7/deep-dives/navmesh-and-pathfinding.md`。

**Day 561-575(对应 HH day561-575)**:**整理 + 反思**。
重点:Phase 7 收官,你拥有完整资产管线 + in-game 编辑器 + glTF 加载 + 导航网格。Phase 8 在此基础上做最后优化。

第一周结束你应该有:能解析 PNG 文件头,开始理解 DEFLATE。**这是 Phase 7 最难的开端**——bit 级操作和工业级文件格式解析是新挑战。

## §5 · 实战项目建议

### 项目 A:完整 PNG 解码器

从零写一个 PNG 解码器。技术栈:纯 Rust,不用任何压缩库。

需求:
- 解析 PNG 签名、IHDR、IDAT、IEND chunks。
- 实现 DEFLATE 解压(LZ77 + Huffman)。
- 实现 5 种 reconstruction filters 的逆操作。
- 支持 8 位 RGBA / RGB / grayscale。
- 至少能解码一张真实的 .png 截图,输出和 `image::open` 一致。

时间预算:2-4 周。

为什么推荐:**这是 HH 全程"造轮子含量"最高的项目**。PNG 是日常使用的格式,理解它从 bit 流到像素的完整链路,**你对所有压缩格式都建立直觉**——gzip、zip、JPEG 都用类似技术。

参考资源:`/home/sun/src/handmade-hero-guide/days/phase-7/deep-dives/png-format-complete.md` 和 `/home/sun/src/handmade-hero-guide/days/phase-7/deep-dives/deflate-compression.md`。

### 项目 B:简单 in-game 编辑器

写一个 in-game 关卡编辑器。技术栈:Rust + 你 Phase 5-6 的渲染器。

需求:
- 鼠标点击选中物体。
- WASD + 鼠标 移动相机。
- 拖动物体改变位置。
- 旋转、缩放物体。
- 保存 / 加载关卡到文件。
- 撤销 / 重做(Ctrl+Z / Ctrl+Y)。

时间预算:1-2 个月。

为什么推荐:in-game 编辑器是工业级游戏开发的核心工具。**做完这个项目,你理解 Unreal / Unity 编辑器在做什么**——它们就是更复杂的版本。

参考资源:`/home/sun/src/handmade-hero-guide/days/phase-7/deep-dives/immediate-mode-editor.md`。

### 项目 C:A* 寻路

写一个 A* 寻路器。技术栈:Rust。

需求:
- 输入:网格地图(2D 数组,0 是空,1 是墙)。
- 输出:从 start 到 goal 的路径。
- 支持 4 邻接(上下左右)和 8 邻接(加对角线)。
- 支持不同 heuristic(Manhattan、Euclidean、Chebyshev)。
- 可视化(可选,用你的渲染器画出来)。

时间预算:1 周。

为什么推荐:A* 是游戏 AI 的基础。**做完这个项目,你理解所有 RTS / MOBA 的"右键移动"在做什么**。

参考资源:`/home/sun/src/handmade-hero-guide/days/phase-7/deep-dives/navmesh-and-pathfinding.md`。

## §6 · 推荐配合的 deep-dive

`/home/sun/src/handmade-hero-guide/days/phase-6/deep-dives/` 里进 Phase 7 前值得读的:

### `pbr-complete.md`(强推荐)

PBR 完整推导。Phase 7 你加载 glTF 模型,glTF 用 PBR 材质,你要彻底懂 PBR。

### `deferred-and-clustered.md`(推荐)

延迟渲染。Phase 7 in-game 编辑器需要看场景,延迟渲染对多光源场景友好。

### `texture-compression.md`(推荐)

纹理压缩格式(BCn / ASTC / ETC2)。Phase 7 资产管线会用,先把基础打牢。

---

`/home/sun/src/handmade-hero-guide/days/phase-7/deep-dives/` 里的推荐:

### `png-format-complete.md`(强推荐,Day 436+ 读)

PNG 格式的完整规范。所有 chunk、所有 reconstruction filter、所有颜色类型。**Phase 7 第一天开始读**。

### `deflate-compression.md`(强推荐,Day 443+ 读)

DEFLATE 算法的完整实现。LZ77 + Huffman,从 bit 流解码。**Phase 7 中期核心**。

### `asset-pipeline-architecture.md`(强推荐,Day 463+ 读)

资产管线架构。打包 / 解包、热重载、依赖管理。**Phase 7 中后期核心**。

### `immediate-mode-editor.md`(强推荐,Day 476+ 读)

in-game 编辑器的完整设计。选中、移动、撤销 / 重做、序列化。**Phase 7 后期核心**。

### `gltf-and-model-loading.md`(强推荐,Day 511+ 读)

glTF 格式 + 模型加载。骨骼动画、PBR 材质映射。

### `texture-pipeline.md`(推荐)

纹理管线:从 PNG 到 GPU texture 的完整链路。压缩、mipmap、各向异性过滤。

### `material-and-shader-authoring.md`(推荐)

材质编辑:从 PBR 参数到 shader 实现的完整映射。

### `navmesh-and-pathfinding.md`(强推荐,Day 531+ 读)

导航网格 + A* 寻路。AI 移动的基础设施。

### `localization-short.md`(可选,后期读)

游戏本地化。多语言、字体回退、文本布局。

### `accessibility-short.md`(可选)

游戏无障碍。色盲模式、字幕、键位自定义。

### `ui-data-binding-short.md`(可选)

UI 数据绑定。immediate-mode UI + ECS 数据的桥接。

### `adaptive-audio-and-3d.md`(可选)

自适应音频 + 3D 音频。Phase 4 音频系统的延伸。

---

## 结语

Phase 6 是"渲染算法深化",Phase 7 是"工程化 + 工具链"。Phase 6 完成时你能渲染好看的东西,Phase 7 完成时你能**编辑资产、热重载、加载工业级模型格式**。

Phase 7 第一周(PNG 解码)你会觉得"为什么这么痛苦,bit 流这么烦"。**坚持下来**,你会发现 PNG 解码是一次"程序员尊严之旅"——做完之后你看任何压缩格式都不迷路,因为你知道从 bit 到像素的完整链路。

Phase 7 中期(资产管线)你会觉得"这种'打包 + 解包'的事为什么要做"。**坚持下来**,你会发现这是工业级游戏开发的核心工作流——Unreal、Unity、所有商业游戏都有这个,只是名字不同(.pak / .assets / .vpk)。

Phase 7 后期(in-game 编辑器)你会觉得"工程难度真大"。**坚持下来**,你会发现 in-game 编辑器是"程序员 + 策划 + 美术"协作的桥梁。**没有 in-game 编辑器,你做的不是游戏,是技术 demo**。

Phase 7 全程的核心心智是:**理解底层,用工具顺手**。Casey 在 HH 里手写 PNG 不是因为他反对用库,是因为**理解底层之后用库更熟练**。Phase 7 完成时,你既能"从 bit 流手写 PNG",也能"熟练调 image crate"——前者让你理解,后者让你高效。**两者兼备,才是真正的工程师**。

下一站:Day 436。打开你的十六进制编辑器(或 `xxd`),准备看 PNG 文件的字节流。
