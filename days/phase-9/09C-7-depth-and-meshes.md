---
phase: 9
sequence: "9C"
module: 7
title_en: "Depth Buffer & Meshes"
title_zh: "深度缓冲与真实网格:从一张贴图三角形,到一只能转的立方体"
type: deep-dive
difficulty: 4
duration: "3-4 小时"
domains: [graphics, gpu, rust]
prereqs: ["09C-6-textures-and-samplers"]
calibration: "Vulkan depth attachment + vertex/index buffers + vulkan-tutorial 'Depth Buffering' & 'Vertex/Index buffer'"
---

# 09C-7 · 深度缓冲与真实网格

## 0 · 你画得出一张贴图,但你画不出一只立方体

[09C-6](09C-6-textures-and-samplers.md) 结束时,你已经在屏幕上画出了一张贴在那个三角形上的 PNG。你很自然地想做下一步:多画几个三角形,让它们在空间里形成一个**立方体**。于是你把第二个三角形的顶点位置改成"靠后面一点",提交。屏幕上确实出现了两个三角形——可是它们谁也没挡住谁,后画的那个直接把先画的那个颜色覆盖了。你换一个角度让它们交叉,两个三角形像两张剪纸一样彼此穿过,中间那段本该"前面挡住后面"的相交部分,变成了先画或后画的纯随机胜负。

这就是没有深度缓冲的世界。一张贴图三角形不需要"谁在前",因为只有一片。一旦你画第二个、第三十六个三角形,谁来决定"这个屏幕像素最终应该看到的是哪个三角形"?OpenGL 的默认 framebuffer 里早给你预埋了一个深度缓冲,Vulkan 不给——它把这件事也交给你显式做。所以你的立方体看起来不对,根因不是你画错了三角形,而是**你从来没给 GPU 一个能记录"远近"的地方**。

这一篇要解决两件事,而且它们必须一起解决。第一件,加一个深度 attachment——一个和 swapchain image 同样大小的、专门存"每个像素当前最近的深度值"的图像,绑到 render pass 里,在 pipeline 里打开深度测试。第二件,真正的网格不再是 shader 里写死的三个顶点,而是从 CPU 上传一份**顶点缓冲(position + uv)**和**索引缓冲**——一个立方体 8 个角、36 个三角形顶点角,用索引去引用那 8 个顶点,这就是 phase-7 [gltf-and-model-loading](../phase-7/deep-dives/gltf-and-model-loading.md) 里那些 mesh 数据真正被消费的地方。两件事做完,你的屏幕上会出现一只贴了图的、绕轴旋转的、从任何角度看遮挡都正确的立方体。这是你 Vulkan 旅程里第一次真正"3D"的一刻。

## 1 · 深度缓冲:把 phase-3 的 z-buffer 搬到硬件上

要把深度缓冲讲透,得先回到 [phase-3 的 z-buffer-and-depth-testing](../phase-3/deep-dives/z-buffer-and-depth-testing.md) 里你写过的那段软件光栅化。当时你为 framebuffer 配一块同样大小的内存叫 z-buffer,每个像素一个深度值,初始填成"无穷远";每次光栅化一个三角形,对每个被覆盖的像素,算出它在三角形上的深度 z,和 z-buffer 里现存的 z 比——新的更近就同时写颜色和新的 z,否则跳过。这就是 Edwin Catmull 1974 年发明的 Z-Buffer 算法,3D 渲染里解决遮挡的标准方案,因为不需要排序、不害怕三角形相交和循环遮挡。

Vulkan 的深度 attachment 做的事**和你 phase-3 那段代码一模一样**,只不过搬到硬件上,每个像素并行做。GPU 的 ROP(Render Output Unit)在 fragment shader 输出一个颜色时,同时拿到这个 fragment 的深度(由 vertex shader 输出的位置经过光栅化插值得到),和深度 attachment 里现存的深度做比较;通过比较的才写颜色(也写新的深度),没通过的就丢弃这个 fragment。你不需要写一行这个逻辑的代码——你只需要提供一块深度图像当 attachment、告诉 render pass 它存在、在 pipeline 里把深度测试的两个开关打开。GPU 硬件替你做剩下的事。

先讲那块深度图像怎么来。它和 swapchain image 不一样:swapchain image 是 present engine 给你的、你只能用不能造,而深度图像是你**自己创建**的一块普通 image,大小和 swapchain extent 一致,format 选一个支持深度格式的。最常用的是 `VK_FORMAT_D32_SFLOAT`(32 位浮点深度);有些硬件(尤其移动端)更偏好 `D24_UNORM_S8_UINT` 这种打包了 24 位深度 + 8 位模板的格式。你要先问物理设备:"这个 format 你支持吗?有没有 `DEPTH_STENCIL_ATTACHMENT_BIT`?"养成查的习惯——验证层会在不支持的 format 上炸响。

```rust
fn find_depth_format(physical_device: vk::PhysicalDevice) -> vk::Format {
    let candidates = [
        vk::Format::D32_SFLOAT,
        vk::Format::D32_SFLOAT_S8_UINT,
        vk::Format::D24_UNORM_S8_UINT,
    ];
    for &f in &candidates {
        let props = unsafe { physical_device.format_properties(f) };
        if props.optimal_tiling_features
            .contains(vk::FormatFeatureFlags::DEPTH_STENCIL_ATTACHMENT_BIT)
        {
            return f;
        }
    }
    panic!("没有可用的深度 format");
}
```

拿到 format,创建 image 的过程和 09C-6 创建纹理 image 几乎一样——extent、mipLevels=1、arrayLayers=1、samples=1、tiling OPTIMAL,但 usage 必须包含 `DEPTH_STENCIL_ATTACHMENT_BIT`(没它后面绑不上 render pass),initial_layout UNDEFINED。然后 `allocate` 一块 `DEVICE_LOCAL` 内存绑给它(深度图像是 GPU 高频读写的,必须在显存)。再 `create_image_view`,view 的 aspect 不能是 COLOR,必须是 `DEPTH_BIT`。这一系列调用你在 09C-6 做过一遍,这里只是 usage 和 aspect 换成深度专用。

深度图像有一处和颜色 image 不一样的细节,值得单独点出:**它的 layout 转换走的是 `DEPTH_STENCIL_ATTACHMENT_OPTIMAL`,不是 `COLOR_ATTACHMENT_OPTIMAL`**。深度图像在 GPU 内部可能用专门的深度压缩格式、tiling 也走专门的优化,所以 Vulkan 给它一个独立的 layout 枚举值。render pass 替你管这个转换:attachment 描述里写 `initial_layout = UNDEFINED`(开始时不在乎它原来是什么,因为我们 clear)、`final_layout = DEPTH_STENCIL_ATTACHMENT_OPTIMAL`(结束时它就是深度 attachment 形态,下一帧还能接着用)。这一行 final_layout 是新手常错的地方——无脑抄颜色 attachment 的 `PRESENT_SRC_KHR` 给深度,验证层立刻报"这个 layout 对深度 image 不合法"。

## 2 · 把深度 attachment 接进 render pass 和 pipeline

image 准备好了,接下来把它接到 render pass 的"配方"里。在 [09C-4](09C-4-graphics-pipeline-first-triangle.md) 你的 render pass 只有一个颜色 attachment,现在 attachment 数组从 1 项变 2 项。注意 attachment 的**顺序**很重要——颜色 attachment 是 index 0,深度 attachment 是 index 1,subpass 的 `pColorAttachments` 指向 index 0、`pDepthStencilAttachment` 指向 index 1。`clear_values` 数组的顺序也必须和 attachment description 一致——索引 0 是颜色清屏值,索引 1 是深度清屏值。

深度 attachment 的 description 长这样:

```rust
let depth_attachment = vk::AttachmentDescription::default()
    .format(depth_format)                                   // D32_SFLOAT
    .samples(vk::SampleCountFlags::TYPE_1)                  // 暂不开 MSAA
    .load_op(vk::AttachmentLoadOp::CLEAR)                   // pass 开始时清成最远
    .store_op(vk::AttachmentStoreOp::DONT_CARE)             // 不需要把深度结果存下来
    .stencil_load_op(vk::AttachmentLoadOp::DONT_CARE)
    .stencil_store_op(vk::AttachmentStoreOp::DONT_CARE)
    .initial_layout(vk::ImageLayout::UNDEFINED)
    .final_layout(vk::ImageLayout::DEPTH_STENCIL_ATTACHMENT_OPTIMAL);
```

三处和颜色 attachment 不同的字段值得想清楚。`store_op` 是 `DONT_CARE`——深度值在 pass 结束后你不再需要(下一帧开始时会 clear 重置),GPU 可以随意丢弃它,省一次写回显存的带宽;如果某个后续 pass 要把深度图当纹理读(比如做后处理景深),那时才需要填 `STORE`。`stencil_load_op` / `stencil_store_op` 单独列出——即使你 format 选的是纯 D32(不带模板),这两个字段也必须填,填 `DONT_CARE` 即可。`final_layout` 是 `DEPTH_STENCIL_ATTACHMENT_OPTIMAL`,因为下一帧还要继续用它当深度 attachment。

clear value 那里,深度的清屏值是 **1.0**——在 Vulkan 的 [0, 1] 深度范围里,1.0 是"最远",0.0 是"最近"。这是 Vulkan 和 OpenGL 的一个重要区别,OpenGL 的 NDC Z 是 [-1, 1],Vulkan 改成了 [0, 1],你在 phase-3 [projection-matrices](../phase-3/deep-dives/projection-matrices.md) 里推导过的那个投影矩阵要相应调整才能喂给 Vulkan:

```rust
let clear_values = [
    vk::ClearValue {
        color: vk::ClearColorValue { float32: [0.0, 0.0, 0.0, 1.0] },  // 颜色清黑
    },
    vk::ClearValue {
        depth_stencil: vk::ClearDepthStencilValue { depth: 1.0, stencil: 0 },
    },
];
```

render pass 改完,还要把 pipeline 的"深度站"打开。在 [09C-4](09C-4-graphics-pipeline-first-triangle.md) §2 我讲过那十来个 create-info 里的 `depth/stencil` 那一站,当时我说"第一个三角形全部 disabled,09C-7 你加深度缓冲时,会在这里开启深度写入和深度比较"。这一刻来了:

```rust
let depth_stencil = vk::PipelineDepthStencilStateCreateInfo::default()
    .depth_test_enable(true)         // 启用深度测试:每个 fragment 都和 z-buffer 比
    .depth_write_enable(true)        // 通过测试的 fragment 写入新的深度
    .depth_compare_op(vk::CompareOp::LESS)  // 新深度小于现存深度时通过(更近)
    .depth_bounds_test_enable(false)
    .stencil_test_enable(false);
```

`depth_test_enable` 和 `depth_write_enable` 是这一篇最关键的两行。打开 test,GPU 才会比深度;打开 write,通过测试的 fragment 才会把新的深度值写回 z-buffer。如果你只开 test 不开 write,会出现一个微妙的现象——遮挡对了,但玻璃半透明效果做不出(因为半透明物体不应该写深度);如果你只开 write 不开 test,所有 fragment 都直接覆盖,深度缓冲形同虚设。**不透明物体两个都开**,这是默认配置;透明物体才需要更细致的策略。`depth_compare_op` 用 `LESS`,意思就是 phase-3 z-buffer 那段"新的更近就保留"的硬件实现。

还有一处新手容易忽略——pipeline 创建时的 `GraphicsPipelineCreateInfo` 本身,**不需要**显式声明"这根 pipeline 用了深度"。Vulkan 从 render pass 推断:你 render pass 有深度 attachment,pipeline 的 depth/stencil state 必须配得上(开了 test 但 render pass 没深度 attachment,验证层炸响)。所以"开深度"是 render pass + pipeline depth/stencil state 两处协同的事,缺一不可。

## 3 · 顶点缓冲:让顶点数据从 CPU 走到 GPU

深度缓冲解决了"谁挡谁",但你还差另一半——真实的网格数据。

目前为止你的所有三角形,顶点位置都是**写死在 vertex shader 里的**([09C-4](09C-4-graphics-pipeline-first-triangle.md) 用 `gl_VertexIndex` 索引一个 shader 内的数组)。这种偷懒手法只能画一两个固定形状,你不能为每只模型都重新编译一遍 shader。真实项目里,顶点数据是**外部的、动态的、由 CPU 准备好后传给 GPU** 的。这就是顶点缓冲(vertex buffer)——一块装着顶点数据的、在 GPU 显存里的 buffer。

一个顶点可以包含多种**属性(attribute)**:position(vec3)、uv(vec2)、normal(vec3,留给后面打光用)、color(顶点色)、tangent(切线,做法线贴图用)。在你这第一只立方体上,先用最精简的两种:position + uv,共 5 个 float:

```rust
#[repr(C)]
#[derive(Clone, Copy)]
pub struct Vertex {
    pub pos: [f32; 3],
    pub uv:  [f32; 2],
}

impl Vertex {
    /// binding description:从哪个缓冲、按多大步幅、按顶点还是按实例推进
    fn binding_description() -> [vk::VertexInputBindingDescription; 1] {
        [vk::VertexInputBindingDescription::default()
            .binding(0)
            .stride(std::mem::size_of::<Vertex>() as u32) // 每个顶点 20 字节
            .input_rate(vk::VertexInputRate::VERTEX)]     // 按顶点推进
    }

    /// attribute description:某个属性在哪个字节偏移、shader 哪个 location 接它、什么 format
    fn attribute_descriptions() -> [vk::VertexInputAttributeDescription; 2] {
        [
            vk::VertexInputAttributeDescription::default()
                .binding(0).location(0)
                .format(vk::Format::R32G32B32_SFLOAT)     // vec3
                .offset(memoffset_of!(Vertex, pos) as u32),
            vk::VertexInputAttributeDescription::default()
                .binding(0).location(1)
                .format(vk::Format::R32G32_SFLOAT)        // vec2
                .offset(memoffset_of!(Vertex, uv) as u32),
        ]
    }
}
```

这两个 description 是 [09C-4](09C-4-graphics-pipeline-first-triangle.md) §2 里我说的"vertex input station"的真正内容——第一个三角形那里写空,现在要填进去。理解它们,要分清两个概念:**binding** 是"从哪个缓冲、按多大步幅、按顶点还是按实例推进";**attribute** 是"在这个步幅里,某个属性在哪个字节偏移、shader 哪个 location 接它、什么 format"。

`input_rate` 里另一个值 `INSTANCE` 意味着每个**实例**才推进一次,这就是 instancing 的核心——binding 0 装共用的几何顶点(VERTEX),binding 1 装每个实例独有的"实例属性"(INSTANCE,比如每个实例的世界矩阵),一次 draw 画几千个不同对象。这一篇不用 instance。

`stride` 等于 `size_of::<Vertex>()`,意思就是"相邻两个顶点在内存里隔 20 字节"。这就是 **interleaved(交错)布局**——position 和 uv 在同一个顶点结构里挨着排,顶点和顶点再挨着排。另一种布局是 **separate(分离)**——所有 position 连续放一段、所有 uv 连续放另一段,需要两个 binding、两个 buffer。哪种好?这要从 [09C-1 coalesced-access](09C-1-gpu-architecture-and-explicit-api.md) 讲起的 GPU 内存访问模式说起。对**顶点着色器**而言,interleaved 几乎总是好——因为 vertex shader 几乎一定会用 position(必须用,要算 clip space 位置),也大概率同时用 uv 和 normal。一个 cache line 拉进来,刚好覆盖整顶点,不浪费。所以 vulkan-tutorial、Sascha Willems 的 examples、Bevy 的 renderer 默认都用 interleaved。separate 布局的优势场景是"某些属性偶尔才被用"(比如 morph target 的权重),那时拆出来让常用属性的 cache density 更高。第一只立方体,**interleaved 是对的**。

shader 那一侧,vertex shader 现在不能再硬编码顶点了,要从 `location = 0` 和 `location = 1` 接输入:

```glsl
// cube.vert
#version 450

layout(location = 0) in  vec3 inPos;     // 来自顶点缓冲的 position 属性
layout(location = 1) in  vec2 inUV;      // 来自顶点缓冲的 uv 属性

layout(location = 0) out vec2 fragUV;    // 传给 fragment shader

layout(set = 0, binding = 0) uniform UBO {
    mat4 mvp;                              // 09C-5 你做好的 model-view-projection 矩阵
} ubo;

void main() {
    gl_Position = ubo.mvp * vec4(inPos, 1.0);
    fragUV = inUV;
}
```

```glsl
// cube.frag
#version 450

layout(location = 0) in  vec2 fragUV;
layout(location = 0) out vec4 outColor;

layout(set = 0, binding = 1) uniform sampler2D tex;  // 09C-6 你做好的纹理

void main() {
    outColor = texture(tex, fragUV);
}
```

注意 `ubo.mvp`——这是 [09C-5 uniform-buffers-and-descriptors](09C-5-descriptors-and-uniforms.md) 里你做好的 MVP 矩阵,它每帧由 CPU 更新(让你能旋转立方体、能移动相机),通过 descriptor 喂给 shader。`tex` 是 09C-6 你做好的纹理。这两个东西在这里汇合——这一篇不是孤立的,它把 09C-5 的 uniform、09C-6 的纹理、这一篇的顶点缓冲全部接到一根 pipeline 上。

## 4 · 索引缓冲:为什么一个立方体只需要 24 个顶点而不是 36 个

你会立刻撞上一个尴尬的事实:**一个立方体,如果直接用三角形列表(每个三角形 3 个独立顶点),你需要 36 个独立顶点**(6 个面,每面 2 个三角形,每三角形 3 个顶点)。可是一个立方体**实际上只有 8 个几何角**。这意味着 36 个顶点里有大量重复——同一个角被复制了 3 到 6 次,每次重复都占内存、占带宽、还要 vertex shader 多算一次。

这就是**索引缓冲(index buffer)**解决的问题。你只存唯一的顶点,另外存一份"三角形怎么由这些顶点组成"的索引数组——每个三角形用 3 个索引指向顶点缓冲里的位置。索引不仅省内存,更重要的是**让 GPU 的顶点缓存(vertex cache,一个小的 post-transform cache)能命中**——同一个顶点被多个三角形引用时,vertex shader 只算一次,后续命中 cache 直接拿结果。

这个 vertex cache 命中率有讲究——三角形给出的顺序,直接决定了 cache 命中率。一个未优化的网格,可能有 30% 的顶点被重复计算;经过 **vertex cache optimization**(典型算法是 Tom Forsyth 的 linear-speed 算法,或 K-Cache reorder)重排三角形顺序后,能把重复算降到 5% 以下。这就是为什么 phase-7 的 [gltf-and-model-loading](../phase-7/deep-dives/gltf-and-model-loading.md) 里在导入网格时通常跑一遍 meshopt 类的优化——它在加载阶段把三角形重排,让运行时 vertex cache 命中率最大化。第一只立方体太小,优化与否无差别,但你要知道:**索引 + 顺序优化,是真实网格性能的两把钥匙**。

立方体的顶点和索引长这样(手写就行,先不接 glTF):

```rust
// 立方体的 24 个顶点(每面 4 个;不同面的同角 uv 不同,所以不复用)。
// 注意:对立方体而言,因为每个面的 uv 想各自独立映射,
// 8 个几何角会被扩展到 24 个"渲染顶点"——"几何顶点数"和"渲染顶点数"不必相等。
let vertices: Vec<Vertex> = vec![
    // 前 -Z 面
    Vertex { pos: [-1.0, -1.0, -1.0], uv: [0.0, 0.0] },
    Vertex { pos: [ 1.0, -1.0, -1.0], uv: [1.0, 0.0] },
    Vertex { pos: [ 1.0,  1.0, -1.0], uv: [1.0, 1.0] },
    Vertex { pos: [-1.0,  1.0, -1.0], uv: [0.0, 1.0] },
    // ... 后 +Z、左、右、上、下,共 6 面;每面 4 顶点,顺序按逆时针(配合 cull mode BACK)
];

let indices: Vec<u32> = vec![
     0,  1,  2,   2,  3,  0,    // 前
     // ... 其余 5 面各两个三角形,共 36 个索引
];
```

这里值得停下来澄清一个容易混淆的点。我说"立方体只有 8 个角",但上面给了 24 个顶点。这矛盾吗?不矛盾。**几何意义上的顶点**和**渲染意义上的顶点**是两个概念——前者是"空间位置",后者是"一捆 vertex attributes 的集合"。如果两个面共用一个几何角,但它们在那个角上的 uv 不同或 normal 不同,那它们就是**两个不同的渲染顶点**。phase-7 的 glTF 加载器输出的就是这种"按 attribute 是否相同决定的渲染顶点 + 索引"格式,直接喂给这里。

draw 调用也从 `vkCmdDraw` 换成了 `vkCmdDrawIndexed`:

```rust
device.cmd_bind_vertex_buffers(cmd, 0, &[vertex_buffer], &[0]);
device.cmd_bind_index_buffer(cmd, index_buffer, 0, vk::IndexType::UINT32);
// index_count=36, instance_count=1, first_index=0, vertex_offset=0, first_instance=0
device.cmd_draw_indexed(cmd, 36, 1, 0, 0, 0);
```

`index_type` 是 `U32` 还是 `U16` 也有讲究——U16 索引只能寻址 65536 个顶点以内,但占一半内存、cache 友好;U32 没限制。很多引擎导出网格时尽量用 U16,超过 65536 顶点的大网格才升级到 U32,这是顶点缓冲带宽优化的一个小细节。

## 5 · 把数据搬上 GPU:staging buffer 复用 09C-6 的套路

顶点和索引都准备好了,但它们现在还在 CPU 端的 `Vec<Vertex>` 里。你要创建两块 GPU buffer(顶点 buffer、索引 buffer),把数据搬进去。这个搬动过程,你在 09C-6 上传纹理时已经做过一遍:用一块 `HOST_VISIBLE` 的 staging buffer 作中转,CPU 把数据写进 staging,再 `cmd_copy_buffer` 从 staging 拷到 `DEVICE_LOCAL` 的目标 buffer。

```rust
fn create_vertex_buffer(
    device: &ash::Device,
    physical_device: vk::PhysicalDevice,
    cmd_pool: vk::CommandPool,
    queue: vk::Queue,
    vertices: &[Vertex],
) -> vk::Buffer {
    let size = (vertices.len() * std::mem::size_of::<Vertex>()) as vk::DeviceSize;
    let (staging_buffer, staging_memory) = create_buffer(
        device, physical_device, size,
        vk::BufferUsageFlags::TRANSFER_SRC,
        vk::MemoryPropertyFlags::HOST_VISIBLE | vk::MemoryPropertyFlags::HOST_COHERENT,
    );

    // CPU 写进 staging
    unsafe {
        let mut mapped = std::ptr::null_mut();
        device.map_memory(staging_memory, 0, size, vk::MemoryMapFlags::empty(), &mut mapped).unwrap();
        std::ptr::copy_nonoverlapping(vertices.as_ptr() as *const u8, mapped as *mut u8, size as usize);
        device.unmap_memory(staging_memory);
    }

    // GPU 本地目标 buffer
    let (gpu_buffer, _gpu_memory) = create_buffer(
        device, physical_device, size,
        vk::BufferUsageFlags::TRANSFER_DST | vk::BufferUsageFlags::VERTEX_BUFFER,
        vk::MemoryPropertyFlags::DEVICE_LOCAL,
    );

    // 提交一条 copy 命令并等它完成
    copy_buffer(device, cmd_pool, queue, staging_buffer, gpu_buffer, size);

    // staging 释放(真实工程里应留在 staging pool 复用,而非每帧 alloc/free)
    unsafe {
        device.destroy_buffer(staging_buffer, None);
        device.free_memory(staging_memory, None);
    }
    gpu_buffer
}
```

index buffer 的创建函数长得一模一样,只是 `BufferUsageFlags::VERTEX_BUFFER` 换成 `INDEX_BUFFER`。我建议你把 `create_buffer`、`copy_buffer` 抽成通用工具函数——09C-6 你写过 `create_image` / `copy_buffer_to_image`,这里只是 `create_buffer` / `copy_buffer`,把"创建 + 分配内存 + 绑定"和"录制一条 copy 命令 + 提交 + 等 fence"各自抽出来。**这种工具函数的复用,是 Vulkan 工程化最重要的一步**——你前几篇被相同模板的样板代码淹没,到这里应该沉淀出几个 helper,后续 09C-8 加更复杂的资源类型时复用它们。

`HOST_VISIBLE | HOST_COHERENT` 的 staging buffer,CPU 能写、写完不用显式 flush(COHERENT);GPU 读它走 PCIe,慢,所以只用来一次性 staging。`DEVICE_LOCAL` 的目标 buffer,GPU 直读,快,但 CPU 不能直接写——所以才需要 staging 中转。这种"两阶段上传"是 Vulkan 资源初始化的标准范式,**所有**从 CPU 来的数据(纹理、顶点、索引、uniform 初始值)都走这条路。

这一篇你的顶点缓冲和索引缓冲是**静态的**——立方体不动,数据上传一次就够了。但 uniform buffer(09C-5 的 MVP 矩阵)是**动态的**——每帧 CPU 都要更新它(因为立方体要旋转、相机要动)。所以 uniform buffer 不能走 DEVICE_LOCAL,它必须是 HOST_VISIBLE 的。这两种 buffer(静态 DEVICE_LOCAL + 动态 HOST_VISIBLE)共存于一帧,是 Vulkan 资源管理的常态。

## 6 · 让立方体转起来:MVP + 深度,汇合在一帧的录制里

数据全到位,现在把所有片段缝合成一帧的录制。这一段录制比 [09C-4](09C-4-graphics-pipeline-first-triangle.md) §7 的版本长不少,因为多了顶点/索引缓冲绑定、descriptor 绑定、draw indexed。它仍然在 [09C-3](09C-3-command-buffers-and-synchronization.md) 那套同步循环里跑——acquire、record、submit、present 不变,只是 record 的内容多了。

```rust
fn record_frame(
    device: &ash::Device,
    cmd: vk::CommandBuffer,
    pipeline: vk::Pipeline,
    pipeline_layout: vk::PipelineLayout,
    framebuffer: vk::Framebuffer,
    render_pass: vk::RenderPass,
    extent: vk::Extent2D,
    descriptor_set: vk::DescriptorSet,
    vertex_buffer: vk::Buffer,
    index_buffer: vk::Buffer,
) {
    unsafe {
        device.begin_command_buffer(cmd, &vk::CommandBeginInfo::default()).unwrap();

        let clear_values = [
            vk::ClearValue {
                color: vk::ClearColorValue { float32: [0.02, 0.02, 0.05, 1.0] },
            },
            vk::ClearValue {
                depth_stencil: vk::ClearDepthStencilValue { depth: 1.0, stencil: 0 },
            },
        ];
        let render_pass_info = vk::RenderPassBeginInfo::default()
            .render_pass(render_pass)
            .framebuffer(framebuffer)
            .render_area(vk::Rect2D { offset: vk::Offset2D::default(), extent })
            .clear_values(&clear_values);

        device.cmd_begin_render_pass(cmd, &render_pass_info, vk::SubpassContents::INLINE);
        device.cmd_bind_pipeline(cmd, vk::PipelineBindPoint::GRAPHICS, pipeline);

        let viewport = vk::Viewport {
            x: 0.0, y: 0.0,
            width: extent.width as f32, height: extent.height as f32,
            min_depth: 0.0, max_depth: 1.0,
        };
        device.cmd_set_viewport(cmd, 0, std::slice::from_ref(&viewport));
        device.cmd_set_scissor(cmd, 0, std::slice::from_ref(
            &vk::Rect2D { offset: vk::Offset2D::default(), extent }));

        device.cmd_bind_descriptor_sets(
            cmd, vk::PipelineBindPoint::GRAPHICS,
            pipeline_layout, 0, &[descriptor_set], &[],
        );
        device.cmd_bind_vertex_buffers(cmd, 0, &[vertex_buffer], &[0]);
        device.cmd_bind_index_buffer(cmd, index_buffer, 0, vk::IndexType::UINT32);
        device.cmd_draw_indexed(cmd, 36, 1, 0, 0, 0);

        device.cmd_end_render_pass(cmd);
        device.end_command_buffer(cmd).unwrap();
    }
}
```

每帧 CPU 端,你更新 uniform buffer 里的 MVP 矩阵。模型矩阵用一个绕 Y 轴随时间旋转的矩阵(`angle = start.elapsed().as_secs_f32()`),view 矩阵把相机后撤到 `(0, 0, -4)` 看向原点,projection 矩阵用 [phase-3 projection-matrices](../phase-3/deep-dives/projection-matrices.md) 里推导的透视投影(注意 Vulkan 的 NDC Z 是 [0, 1]、y 轴朝下,投影矩阵和 OpenGL 的版本不一样——大多数数学库都提供 Vulkan 风格的版本,比如 `cgmath::Perspective::new_vulkan`、`glam::Mat4::perspective_lh`,直接用)。三者相乘 `mvp = proj * view * model`(列主序,应用顺序是 model 在最右),写进 uniform buffer。提交后,vertex shader 用这个矩阵把每个顶点变到 clip space,光栅化插值出每个 fragment 的深度,深度 attachment 逐像素比较,通过的颜色写进 framebuffer。一帧结束,present。

你应该看到一只立方体在屏幕中央慢慢旋转,六个面各贴了一张图(用同一张纹理,因为 uv 在每个面上独立铺了一遍),旋转时面的遮挡完全正确——你永远只看到朝向你的三个面,背面的面被深度测试剔除。换成多只立方体重叠,也不会再出现"先画的覆盖后画的"那种 09C-4 时代的问题。这就是深度缓冲的意义。

## 7 · Z-Fighting 与半透明:深度缓冲的两个老朋友

深度缓冲不是银弹,它有一个老问题——**Z-fighting(深度冲突)**。当两个面几乎共面时(比如你画一个贴在墙上的标志,标志和墙的 z 太接近),深度 attachment 的精度不足以分辨它们的微小深度差,光栅化时两个面的深度值**量化到同一个值**,于是这两个面在屏幕上**随机交替地通过深度测试**,出现一种闪烁的、像百叶窗一样的纹理。这是 [phase-3 z-buffer-and-depth-testing](../phase-3/deep-dives/z-buffer-and-depth-testing.md) 里你也见过的同一头怪兽。

Z-fighting 的根因是深度值在 framebuffer 里的**精度有限**——D32_SFLOAT 看似精度很高,但浮点数在 0 附近精度高、在 1 附近精度低,而透视投影把远处的深度压缩得很厉害(非线性的 1/z 分布),所以远处物体的有效深度精度其实很差。三种缓解手段:**第一**,共面的几何明确共面——给墙上的标志写位置时,**手动让标志的 z 比墙小一点点**(所谓 polygon offset 的手工版);**第二**,把 near plane 推远、far plane 拉近——缩小 [near, far] 范围,深度精度分布更密;**第三**,深度范围用 reversed-Z(把 near 写成 1、far 写成 0、`depth_compare_op` 改成 GREATER),这是现代引擎的标配——reversed-Z 让 1/z 分布的反向正好和浮点精度分布互补,远处也能保持好精度。第一只立方体你不会遇到 Z-fighting,但你画到第二只、和地面重叠时,它会回来。提前知道这个名字,你看到闪烁时不会茫然。

还有一类相关的现象——**深度缓冲不能直接做半透明**。半透明(alpha blend)需要按从远到近排序绘制,而且半透明物体**不应该写深度**(否则后面更近的半透明被剔除,blend 不出来)。这就是为什么真实渲染器里不透明 pass 写深度、半透明 pass 不写深度,两个 pass 分开。这正是 [09B-3 frame-graph](09B-3-frame-graph.md) 在更高抽象上自动管的事——你声明两个 pass、各自的依赖,frame graph 自动把"不透明先写深度,半透明后读深度做 blend"的同步插好。第一只立方体是不透明的,所以两个开关都开,放心。

## 8 · 在你 HH 项目里动手(做中学红线)

这一篇的动手,是把你 09C-6 的"一张贴图三角形"升级成"一只贴图旋转立方体"。结束时,你的屏幕上出现立方体,验证层完全干净,深度正确。

第一步,**加深度 attachment**。在你 09C-6 已有的 Vulkan 后端里,新增 `find_depth_format`(查 D32_SFLOAT 支持),创建深度 image(extent = swapchain extent、usage 含 `DEPTH_STENCIL_ATTACHMENT_BIT`、DEVICE_LOCAL 内存)、创建对应的 image view(aspect = DEPTH_BIT)。把 view 加进每个 framebuffer 的 attachments 数组(原来是 `[color_view]`,现在是 `[color_view, depth_view]`)。

第二步,**改 render pass**。attachment description 数组从 1 项变 2 项,第二项是 §2 那段 depth_attachment。subpass 的 `pDepthStencilAttachment` 指向新 attachment reference(index 1,layout `DEPTH_STENCIL_ATTACHMENT_OPTIMAL`)。subpass dependency 这一项——如果你之前 09C-4 没写(用了默认),加深度 attachment 后可能需要补一条,告诉 GPU"深度 attachment 在 pass 早期就能用";vulkan-tutorial 的 Depth Buffering 章节里给的 dependency 可以直接抄。

第三步,**改 pipeline 的 depth/stencil state**(§2 那段),`depth_test_enable(true)`、`depth_write_enable(true)`、`depth_compare_op(LESS)`,链接到 pipeline。

第四步,**定义 Vertex 结构体**,填好 binding description 和 attribute description(§3),把它们喂进 pipeline 的 vertex input state(原来是空,现在填上)。

第五步,**手写立方体顶点和索引**(§4 那份 24 顶点 + 36 索引),通过 §5 的 staging buffer 流程上传,创建 vertex buffer 和 index buffer。

第六步,**改 vertex/fragment shader**(§3 的 GLSL),用 `glslangValidator -V` 编成 SPIR-V,在 pipeline 里换上新的 shader module。Arch 上工具链 `sudo pacman -S shaderc glslang`。

第七步,**改录制函数**(§6 的 `record_frame`),加上 descriptor 绑定、vertex/index 绑定、`cmd_draw_indexed`。每帧 CPU 端更新 uniform 里的 MVP(让立方体旋转、相机后撤、用透视投影)。

第八步,**跑,看屏幕,看验证层**。立方体应该出现、旋转、深度正确、纹理在每个面上正确铺开。验证层一声不响。从多个角度看(改相机位置),确认面遮挡正确——朝你的三个面可见,背面被剔除。

验收标准:**屏幕出现贴图旋转立方体,深度正确无 Z-fighting,验证层零报错,持续运行稳定**。截一段小视频或几张图存到你的 dev log 里——这是你 Vulkan 旅程从"2D 演示"跨入"真 3D"的时刻。提交 commit 时,记录踩过的坑:深度 attachment 的 final_layout 抄错成 PRESENT_SRC_KHR?vertex input 的 attribute offset 算错?顶点绕向和 cull mode 不匹配导致整个面被剔除?

## 9 · 生产现实:你不会手写每只网格的 pipeline

真实的游戏引擎里,**没人手写每个 mesh 的 pipeline 和顶点输入布局**。原因有两个。第一,一个商业引擎有几百上千种渲染状态组合(不同材质、不同 pass、不同 LOD),手写每个不现实。第二,这些状态本来就被 [09B-3 frame-graph](09B-3-frame-graph.md) 和材质系统(material system)在更高的抽象层管着——材质定义了"用什么 shader、blend 怎么开、cull mode",frame graph 定义了"render pass 长什么样、attachment 几个",mesh 定义了"顶点属性是 position+uv 还是 pos+uv+normal+tangent",它们**自动合成**出 pipeline create-info 和 vertex input layout。

所以这一篇学的东西,在生产里的实际形态是:**你的 mesh 数据是数据驱动(data-driven)的——加载器声明它的 vertex layout,材质系统声明它的 shader 和状态,frame graph 声明它要写深度,引擎把它们组装成 pipeline**。你以后在 HH 项目里也会走向这条路:09C-8 之后的某个 phase,你会写一个最小的 material system 和 mesh format,从此不再为每只 mesh 手写一遍 `Vertex` 结构体和 pipeline create-info。

那为什么你还要手写一遍?因为**你只有亲手做过一遍,才能理解材质系统和 frame graph 在自动生成什么**。否则,材质系统对你就是黑盒——它出一个 pipeline 你就用,你不知道那个 pipeline 长什么样、为什么长那样、出 bug 了怎么 debug。这一篇手写 pipeline + 顶点输入,是让你**理解 vertex 数据怎么流过 pipeline**,以便日后你能信任并控制那些自动生成它的系统。这正是这个序列反复强调的:**学底层是为了在更高抽象上自由**。

## 10 · 练习

练习一,Lv1 概念辨析。深度 attachment 的 `store_op` 为什么通常填 `DONT_CARE`?因为深度值在 pass 结束后你不再消费它(下一帧开始时会 clear 重置),GPU 可以随意丢弃这块数据,省一次写回显存的带宽开销。如果某个后续 pass 要把深度图当纹理读(比如做后处理景深),那时候才需要填 `STORE`。用一句话复述这个权衡。

练习二,Lv1 概念辨析。interleaved 和 separate 两种顶点属性布局,分别在什么场景下占优?interleaved 在 vertex shader 同时使用多数属性的常见情况下 cache density 好、布局简单,是默认选择;separate 在"某些属性偶尔用"的场景下(如 morph target 权重),拆出来让常用属性的 cache 更密。第一只立方体为什么选 interleaved?

练习三,Lv2 动手实践。完成前面 §8 的全部八步,在你的 HH 项目里画出贴图旋转立方体。把验证层日志、屏幕截图、踩坑记录写进 commit message。这是这一篇的核心交付物。

练习四,Lv3 迁移设计。在不实际写代码的前提下,回答:如果你要把 phase-7 [gltf-and-model-loading](../phase-7/deep-dives/gltf-and-model-loading.md) 加载的一个 glTF 模型渲染出来,你需要从那个加载器拿什么数据?(顶点数组,每个含 pos+uv+normal;索引数组;材质定义——shader、纹理句柄、blend 模式;)这些数据怎么映射到这一篇的 vertex buffer、index buffer、descriptor set?把这个设计写在 dev log 里。

练习五,Lv4 性能与稳健性。用 `vkCmdDrawIndexed` 画两只立方体重叠,故意让它们的部分面共面,观察 Z-fighting。然后实验三种缓解:把共面物体的 z 手动错开 0.001;把投影矩阵的 near plane 从 0.001 推到 0.1;把深度范围反向(reversed-Z)。记录每种缓解的效果,在 dev log 里写一份"Z-fighting 缓解手段对比"。这个练习把你从"会画立方体"推到"理解深度精度并能诊断相关问题"。

## 11 · 延伸阅读与下一篇

这一篇最权威的参考是 Vulkan spec 的 *Resource Creation* 章节(关于 image 和 buffer 创建)和 *Fixed-Function Vertex Processing* 章节(关于 vertex input state);最有实践价值的资源仍然是 vulkan-tutorial.com 的 "Vertex buffer description"、"Loading models"、"Generating Mipmaps"(纹理部分,但顶点缓冲范式相同)、以及专门的 "Depth buffering" 那一章——它和你这一篇走的是同一条路,可以对照读。Sascha Willems 的 examples 仓库里 `triangle`、`cube`、`gltfloading` 几个例子尤其值得对照,你能看到从最小立方体到加载真实 glTF 的渐进路径。关于 vertex cache 优化的算法细节,Tom Forsyth 的 "Linear-Speed Vertex Cache Optimisation" 是经典原文,phase-7 [gltf-and-model-loading](../phase-7/deep-dives/gltf-and-model-loading.md) 里提到的 meshopt 库就是它的工业级实现。关于 reversed-Z 的数学直觉,Upchurch & Catmull 的 "A Fresh Look at Generalized Perspective" 之类讨论可作延伸。

深度缓冲和 phase-3 的 z-buffer 概念同源——这一篇是它在 Vulkan API 上的具象;而 MVP 矩阵和投影矩阵的细节,phase-3 的 [z-buffer-and-depth-testing](../phase-3/deep-dives/z-buffer-and-depth-testing.md) 和 [projection-matrices](../phase-3/deep-dives/projection-matrices.md) 已经铺好了基础,你在这里第一次把它们和 GPU 硬件管线接通。这是"软件光栅化的知识"迁移到"GPU 上的硬件光栅化"的关键一跳。

下一篇 [09C-8](09C-8-migrate-hh-pass-to-vulkan.md),你这一只立方体的渲染已经很完整了——有同步、有 pipeline、有 shader、有纹理、有 uniform、有深度、有顶点/索引。但还有一件事没做:**当窗口大小变化(用户拖拽窗口边框)时,你的 swapchain 失效了,你必须重建它**。下一篇讲 swapchain recreation——这看起来是个边缘话题,但它是把 Vulkan 程序从"演示级"推向"产品级"的最后一块拼图:一个最小可用、能正确响应窗口变化、不会因尺寸变化而崩溃或撕裂的 Vulkan 后端。同时它还会讲到 pipeline cache,把"创建时昂贵"那个我在 09C-4 反复提的代价,做一次系统的工程优化。这一篇之后的 9C 序列就告一段落,你已经有了一只能跑、能转、深度正确的 3D 立方体——这是接下来一切更复杂渲染(光照、阴影、后处理)的起点。
