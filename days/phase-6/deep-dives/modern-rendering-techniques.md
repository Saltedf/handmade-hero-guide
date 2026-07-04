
# 现代渲染技术:bindless、indirect draw 与 GPU-driven pipeline

## 0 · 你的 CPU 在画一万颗树,而 GPU 在打盹

我先把那个让你坐立不安的画面摆在你眼前。

你刚把 [deferred-and-clustered](deferred-and-clustered.md) 里那一整套 clustered forward 跑通——1080p、64 个光源、1.4 ms 一帧 GPU 时间,你截图发到 dev log 里,觉得天下太平。然后你想做一个开放世界场景:一万棵树、两千块石头、五百个 NPC、十万根草。你按朴素方式渲染:CPU 循环这一万两千五百个物体,每个物体算一次 MVP、绑定一次 descriptor set、调一次 `vkCmdDrawIndexed`。你跑起来,GPU 时间还是只有 3 ms,但帧率从 60 FPS 掉到 22 FPS。你打开 Tracy,看 CPU 时间——`vkCmdDrawIndexed` 那段累计 **18 ms**。GPU 在 3 ms 之内画完了整个场景,然后空等 15 ms 等 CPU 把下一批 draw call 灌进来。

这就是 CPU-bound(受限于 CPU)的死亡线,它和 [deferred-and-clustered](deferred-and-clustered.md) 里 GPU-bound 的死亡线是孪生兄弟——一个喂不饱 GPU,一个 GPU 喂不饱像素。今天的现代 AAA 引擎,场景几何量是百万、十亿级别(Unreal 5 Nanite 渲染数十亿三角形),它们能跑起来,不是靠把 CPU 算得更快,而是靠**把 CPU 从逐物体循环里彻底踢出去**。这一篇讲的就是把 CPU 踢出去的那套技术:bindless resources、indirect draw、GPU-driven rendering、mesh shader、Variable Rate Shading、visibility buffer。每一项都拆解它解决的具体瓶颈、它要求的 GPU/API 支持、它在生产里的代价。学完它,你能解释为什么 Nanite 能跑数十亿三角形,以及为什么这一切都离不开你在 [09C-5-descriptors-and-uniforms](../../phase-9/09C-5-descriptors-and-uniforms.md) 学的 descriptor 系统、离不开 [09B-3 frame graph](../../phase-9/09B-3-frame-graph.md) 管理的多 pass 复杂度。

这些技术不是"高级优化",它们是现代渲染的**地基**。一个 2020 年之后写的渲染器,如果还在用"CPU 逐物体循环"的朴素方式,它就还不是现代渲染器。这一篇就是从朴素到现代的那道门槛。

## 1 · 先把病名诊断清楚:你为什么 CPU-bound

要把 CPU 踢出逐物体循环,先得理解它为什么卡。这一节我把开销摊开,你才知道每一项技术砍的是哪一刀。

你每调一次 `vkCmdDrawIndexed`,发生的事情比你想象的多。第一,**命令缓冲录制开销**——Vulkan driver 要把这条 draw 命令编码进 command buffer 的内部格式,可能是 GPU 可直接执行的 PM4（AMD）/Push Buffer（NVIDIA）命令流,这部分是纯 CPU 工作。第二,**验证层（如果开着）**——验证层会检查 pipeline 是否 bound、descriptor set 是否兼容、index buffer 是否 bound,这些检查在 release build 里关掉,但开发期你不能关。第三,**state tracking**——driver 内部要维护"当前 bound 的 pipeline、descriptor set、vertex buffer"的状态,你 bind 一次它就更新一次内部表。第四,**descriptor 更新**——如果你的 descriptor set 用了 `UPDATE_AFTER_BIND` 或动态绑定,driver 要在 submit 时把 descriptor 真正写进 GPU 可见的内存。

这些开销每一项都是微秒级,看起来微不足道。但你乘以一万次 draw call,就是几十毫秒。AMD 在 GDC 2019 给过一组实测数字:在 RX Vega 64 上,朴素 `vkCmdDrawIndexed` 的 CPU 端平均开销是 **1.5 μs**（release build、无验证层、descriptor 预先更新）。一万个 draw = 15 ms。这就是你 22 FPS 的原因——CPU 还没把帧的命令录完,GPU 就没活干。D3D11 时代这个开销更高（driver 隐藏层更多）,一个 draw call 5-10 μs,一万个 draw 直接 50-100 ms,这是为什么 D3D11 的"逐物体"渲染器上限就在几千个物体。

更阴险的是,**CPU-bound 不只是总时间**。draw call 灌得慢,意味着 CPU 录制 command buffer 占着 CPU 核心,GPU 在空等——你的 i9 看起来满载,GPU 利用率却只有 30%。你以为 GPU 不够强,加了一块更猛的显卡,帧率纹丝不动。这是 CPU-bound 的典型症状:**升级 GPU 不解决问题**。

现代 GPU 的算力是如此过剩（RTX 4090 光栅化吞吐是 130 GPixel/s、三角形吞吐是 300 GTriangle/s）,以至于"GPU 画不动"的场景越来越少,瓶颈越来越频繁地落在"CPU 喂不进来"。现代渲染器的所有技术,核心目标只有一个:**减少 CPU 端的命令数,把每条命令做更多的工作**。bindless 是把 descriptor 绑定从一万次降到一次;indirect draw 是把 draw 命令从一万条降到一条;GPU-driven culling 是让 GPU 自己决定画什么;mesh shader 是把几何处理从 CPU pipeline 变成 GPU pipeline;VRS 是减少不必要的 fragment 工作;visibility buffer 是简化光栅化输出。它们从不同角度砍掉 CPU 或 GPU 的工作量。

接下来我一项一项讲。

## 2 · Bindless resources:一次 bind,shader 自己挑

整个现代 GPU-driven pipeline 的地基,是 [09C-5](../../phase-9/09C-5-descriptors-and-uniforms.md) §10 那一节末尾提过的 **bindless resources**。这里我把它从头展开,因为它太重要——没有它,后面所有的 indirect draw、GPU-driven culling 都无从谈起。

先回到朴素模型。你在 [09C-5](../../phase-9/09C-5-descriptors-and-uniforms.md) 学到的 descriptor 系统,使用方式是"每个物体一个 descriptor set、每个 draw 之前 bind"。一万棵树意味着一万个 descriptor set,每个 set 装着"这棵树的 MVP UBO + 这棵树的漫反射贴图"。你画第 i 棵树之前,`vkCmdBindDescriptorSets` 把第 i 个 set 挂上,然后 `vkCmdDrawIndexed`。这种模型在概念上干净,但它有一个致命问题:**每帧一万次 bind,每一次 bind 都在 CPU 端产生开销**。

bindless 的核心 idea 是反过来的——**你把整个场景的所有资源（所有贴图、所有 MVP、所有 vertex buffer）,一次性绑进一个巨大的 descriptor set,然后整个 frame 不再 bind 任何新的 descriptor set**。shader 要画第 i 棵树时,它从一个数组里 `textures[i]` 取出第 i 棵树的贴图、从另一个数组里 `mvp_buffer[i]` 取出第 i 棵树的 MVP。bind 次数从一万降到一次,driver 几乎完全不参与绘制。

具体到 Vulkan,bindless 依赖两个 API 特性。第一个是 **descriptor indexing**（`VK_EXT_descriptor_indexing`,Vulkan 1.2 并入 core）。它允许 descriptor set layout 里某个 binding 声明成"不定长数组"——比如 binding 0 是 `UNIFORM_BUFFER` 数组、binding 1 是 `SAMPLED_IMAGE` 数组,数组长度可以上千。create info 里你加 `VARIABLE_DESCRIPTOR_COUNT` flag,数组长度在 allocate descriptor set 时动态指定。第二个是 **partial binding**——你不必把数组里每个元素都绑上资源,只绑你实际用的;shader 不会访问未绑的元素（你保证）,driver 也不校验未绑元素。这两个特性合在一起,你就能创建一个"装着整个场景所有资源"的 descriptor set,且创建开销可控。

shader 端语法。GLSL 要开 `#extension GL_EXT_nonuniform_qualifier : enable`,然后声明数组、用 `nonuniformEXT` 修饰索引:

```glsl
#version 450
#extension GL_EXT_nonuniform_qualifier : enable

// 场景里所有贴图,一个不定长数组
layout(binding = 0, set = 1) uniform texture2D all_textures[];
// 场景里所有 MVP,一个 SSBO
layout(binding = 0, set = 2) readonly buffer MaterialBuffer {
    MaterialData materials[];
};
// draw id 从 vertex shader 的 instance ID 推
layout(push_constant) uniform Push {
    uint material_offset;  // 这个 draw 的材质起始索引
} pc;

void main() {
    // gl_InstanceID 在每个 instance 上不同,GPU 上 divergent,必须 nonuniformEXT
    uint mat_idx = pc.material_offset + gl_InstanceID;
    MaterialData m = materials[mat_idx];
    vec4 albedo = texture(sampler2D(all_textures[nonuniformEXT(m.albedo_tex_id)],
                                    global_sampler), v_uv);
    // ...
}
```

注意那个 `nonuniformEXT(m.albedo_tex_id)`——这是 bindless 的精髓。GPU 的 warp/wavefront 里,32 或 64 个 thread 同时跑,每个 thread 的 `gl_InstanceID` 不同,因此 `all_textures[idx]` 在 warp 内 divergent（不同 thread 访问不同元素）。GPU 硬件对 divergent texture 访问有专门支持（每个 thread 独立 texture fetch）,但 driver 需要知道这是 divergent 才能生成正确代码——这就是 `nonuniformEXT` qualifier 的作用,告诉编译器"这个索引在 warp 内可能不同"。

CPU 端,你创建一次 descriptor set,把所有贴图绑进 binding 1 数组、所有 SSBO 绑进 binding 0 数组:

```rust
// 一个 binding 装所有贴图
let sampled_image_binding = vk::DescriptorSetLayoutBinding::default()
    .binding(1)
    .descriptor_type(vk::DescriptorType::SAMPLED_IMAGE)
    .descriptor_count(MAX_TEXTURES)        // 比如 4096
    .stage_flags(vk::ShaderStageFlags::FRAGMENT);

let flags = vk::DescriptorBindingFlags::PARTIALLY_BOUND    // 允许部分元素未绑
          | vk::DescriptorBindingFlags::UPDATE_AFTER_BIND;  // 允许 submit 后更新
// (Vulkan 1.2 core)
```

这一个 set 你**每帧只 bind 一次**,然后画一万次,每次通过 push constant 告诉 shader "这批物体的材质起始索引是 N"。bind 次数:从一万次降到一次。这就是为什么 bindless 是 GPU-driven pipeline 的地基——它把"逐物体绑定"这件事彻底消除。

bindless 的代价不是没有。第一,你需要 **sampler 数组** 或 **bindless sampler**——纹理多了,sampler 也要数组化,某些 GPU（主要是移动端）的 sampler 寄存器数量有限。第二,**descriptor 内存占用**——4096 个 sampled image descriptor 大约占 256 KB descriptor memory,这个不便宜,但在 desktop GPU 上完全可接受。第三,**shader 里 texture fetch 的 divergence**——warp 内每 thread 访问不同贴图,GPU texture unit 要做 coalescing 失败处理,带宽利用率下降。这是 bindless 的隐性代价,但在现代 GPU 上可控。

bindless 还有一个深远的工程意义——它让 **GPU 能自己决定访问哪个资源**。这一条是后面 indirect draw + GPU culling 的前提:GPU 跑一个 compute shader 算出"哪些物体可见",直接用算出来的索引访问对应资源,**不需要回到 CPU bind 任何东西**。这就是 GPU-driven 的字面意义——GPU 自己管自己的资源访问。

## 3 · Indirect draw:一条命令,画一万次

bindless 解决了"descriptor 绑定"这一刀,接下来要砍的是 draw call 本身。

朴素渲染里,你每个物体调一次 `vkCmdDrawIndexed(cmd, index_count, instance_count, first_index, vertex_offset, first_instance)`——这是 CPU 给 GPU 的一条命令,意思是"用当前 bound 的 pipeline、vertex buffer、index buffer、descriptor set,画 `index_count` 个三角形,instance `instance_count` 次"。一万个物体 = 一万条 `vkCmdDrawIndexed`,每条都是 CPU 端的录制开销。

**indirect draw** 的 idea 是把这些 draw 命令**打包成一个数组**,用一条 `vkCmdDrawIndexedIndirect` 一次性提交。CPU 端你不再逐个调 draw,你告诉 GPU"这里有个 buffer,里面装着一万个 draw 命令的参数,你按顺序全部执行"。CPU 录制从一万条命令降到一条。

```rust
// 一万个 draw 命令的参数
#[repr(C)]
#[derive(Clone, Copy)]
struct DrawIndexedIndirectCommand {
    index_count: u32,
    instance_count: u32,
    first_index: u32,
    vertex_offset: i32,
    first_instance: u32,
}

let draw_commands: Vec<DrawIndexedIndirectCommand> = scene_objects.iter().map(|obj| {
    DrawIndexedIndirectCommand {
        index_count: obj.mesh.index_count,
        instance_count: 1,
        first_index: obj.mesh.first_index,
        vertex_offset: obj.mesh.vertex_offset,
        first_instance: 0,
    }
}).collect();

// 上传到 GPU 的 indirect buffer
let indirect_buffer = create_buffer_with_data(&device, &queue, bytemuck::cast_slice(&draw_commands),
    vk::BufferUsageFlags::INDIRECT_BUFFER | vk::BufferUsageFlags::STORAGE_BUFFER);

// 一条命令画全部
unsafe {
    device.cmd_draw_indexed_indirect(
        cmd,
        indirect_buffer,
        0,                                  // offset
        draw_commands.len() as u32,         // draw count
        std::mem::size_of::<DrawIndexedIndirectCommand>() as u32,  // stride
    );
}
```

这一步的 CPU 时间已经从"一万个 draw 的录制"降到"一个 indirect draw 命令的录制"——20 μs 以内。GPU 收到这条 indirect 命令后,自己从 indirect buffer 里读出一万个 draw 参数,逐个执行。

但 indirect draw 真正的革命性不在于"CPU 少调函数",在于**这个 indirect buffer 本身可以由 GPU 写**。这就是下一节的核心。

## 4 · GPU-driven rendering:GPU 自己 cull,自己画

把 indirect draw 和 GPU write 结合起来,你就跨过了现代渲染的那道门槛。

回到那个开放世界场景。一万个物体,但相机可能只看到其中三千个——剩下七千个在视锥外、被遮挡、或者太小（远处的石头）。朴素做法是 CPU 跑一个 culling pass:遍历一万个物体的包围盒,算哪些在视锥内,只对可见的物体发 draw call。但这是**CPU 上的 culling**,你又回到了 CPU 循环——只不过循环里少了 draw call,cull 本身的 CPU 时间还在（一万个 AABB-frustum 测试大概 0.5 ms,可接受）。

GPU-driven rendering 把这个 culling 也搬到 GPU 上。具体流程:

第一步,CPU 把**整个场景的物体元数据**（每个物体的世界空间 AABB、mesh 的 index_count/first_index、material index）打包进一个 SSBO,叫 `object_buffer`。这一份数据每帧不变（场景是静态的）,只在物体动时更新。CPU 上传一次,之后整个 frame 不再碰这个 buffer。

第二步,**GPU 上的 compute culling pass**。你 dispatch 一个 compute shader,每个 thread 处理一个物体。shader 读 object_buffer[i] 的 AABB,做 frustum-AABB 测试（算法和 [spatial-acceleration](spatial-acceleration.md) §3 一样）,可能再读 depth pyramid 做 occlusion culling（参考 [hardware-ray-tracing](hardware-ray-tracing.md) §5 的 hierarchical Z）。如果物体可见,thread 把这个物体的 `DrawIndexedIndirectCommand` **写进** indirect buffer 的下一个空位（用 atomic counter 算位置）。如果物体不可见,thread 什么都不做。

第三步,**indirect draw pass**。CPU `vkCmdDrawIndexedIndirect` 用 GPU 刚刚写好的 indirect buffer,count 用同一个 atomic counter（通过 `vkCmdDrawIndirectCount` 读取 GPU 写入的 count）。GPU 执行这一帧所有可见物体的 draw call,**完全不需要 CPU 参与 culling 决策**。

```wgsl
// gpu_cull.wgsl
struct ObjectData {
    world_aabb_min: vec4f,    // xyz + mesh_first_index
    world_aabb_max: vec4f,    // xyz + mesh_index_count
    material_offset: u32,
    vertex_offset: i32,
    _pad: vec2u,
};

struct DrawCommand {
    index_count: u32,
    instance_count: u32,
    first_index: u32,
    vertex_offset: i32,
    first_instance: u32,
    _pad: u32,
    material_offset: u32,  // 你自己加的额外字段,shader 用 push constant 接不到时
    _pad2: u32,
};

@group(0) @binding(0) var<storage, read> objects: array<ObjectData>;
@group(0) @binding(1) var<storage, read_write> draw_commands: array<DrawCommand>;
@group(0) @binding(2) var<storage, read_write> draw_count: atomic<u32>;
@group(0) @binding(3) var<uniform> frame: FrameData;

struct FrameData {
    view_proj: mat4x4f,
    frustum_planes: array<vec4f, 6>,
    num_objects: u32,
};

// 6 plane frustum-AABB 测试,经典算法
fn aabb_in_frustum(min_p: vec3f, max_p: vec3f) -> bool {
    for (var i = 0u; i < 6u; i++) {
        let p = frame.frustum_planes[i];
        // AABB 上离 plane 最近的点（"最正"的角）
        let positive_vertex = vec3f(
            select(min_p.x, max_p.x, p.x > 0.0),
            select(min_p.y, max_p.y, p.y > 0.0),
            select(min_p.z, max_p.z, p.z > 0.0),
        );
        // 如果最近的点都在 plane 外,AABB 整个在外
        if (dot(p.xyz, positive_vertex) + p.w < 0.0) {
            return false;
        }
    }
    return true;
}

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid: vec3u) {
    let obj_idx = gid.x;
    if (obj_idx >= frame.num_objects) { return; }
    
    let obj = objects[obj_idx];
    if (!aabb_in_frustum(obj.world_aabb_min.xyz, obj.world_aabb_max.xyz)) {
        return;  // 不可见,跳过
    }
    
    // 可见,把 draw 命令写进 indirect buffer
    let slot = atomicAdd(&draw_count, 1u);
    draw_commands[slot] = DrawCommand(
        u32(obj.world_aabb_max.w),  // index_count
        1u,                          // instance_count
        u32(obj.world_aabb_min.w),  // first_index
        obj.vertex_offset,
        0u,
        0u,
        obj.material_offset,
        0u,
    );
}
```

这个 compute shader 写出来的 `draw_commands` buffer,就是 indirect draw 的输入。CPU 端你这样:

```rust
// 1. dispatch cull compute shader（GPU 算可见性,写 indirect buffer + count）
device.cmd_dispatch(cmd, (num_objects + 63) / 64, 1, 1);

// 2. memory barrier:确保 cull 写完再 draw
let barrier = vk::MemoryBarrier::default()
    .src_access_mask(vk::AccessFlags::SHADER_WRITE)
    .dst_access_mask(vk::AccessFlags::INDIRECT_COMMAND_READ);
device.cmd_pipeline_barrier(cmd,
    vk::PipelineStageFlags::COMPUTE_SHADER,
    vk::PipelineStageFlags::DRAW_INDIRECT,
    &[], &[barrier], &[]);

// 3. 一条 indirect draw 命令,画所有 GPU cull 出来的可见物体
unsafe {
    device.cmd_draw_indexed_indirect_count(
        cmd,
        indirect_buffer, 0,                       // draw commands buffer
        count_buffer,    0,                       // count buffer（GPU 写的）
        MAX_OBJECTS,                               // max count
        std::mem::size_of::<DrawCommand>() as u32, // stride
    );
}
```

`cmd_draw_indexed_indirect_count` 这个 API 是关键——它的 count 本身来自一个 GPU 写的 buffer。CPU 在调用时根本不知道会画多少物体,完全由 GPU 决定。整个 CPU 端的逐物体循环消失了。

这就是 GPU-driven rendering 的本质。CPU 只发三条命令:cull dispatch、barrier、indirect draw。GPU 自己 cull 一万个物体、自己挑出三千个可见、自己画这三千个。CPU 时间从 15 ms 降到 30 μs,GPU 时间不变（还是要画三千个物体,但这部分是 GPU 强项）。这就是为什么 Nanite 能跑数十亿三角形——它把 culling、LOD 选择、draw call 生成全部搬到 GPU,CPU 几乎只是发一个"开始这一帧"的命令。

这种架构要求一个**关键的工程基础设施**——**frame graph**。你的渲染器现在有 cull pass、draw pass、shadow pass、lighting pass、post-process pass,每个 pass 之间有资源依赖（indirect buffer 是 cull 写、draw 读）,有 barrier 时机,有内存复用。手写这些状态机是噩梦,[09B-3 frame graph](../../phase-9/09B-3-frame-graph.md) 就是用来管理这种复杂度的——你声明每个 pass 的输入/输出资源,frame graph 自动算 barrier、算内存 aliasing、可视化整个 frame。现代 GPU-driven renderer 没有不用 frame graph 的。

[hardware-ray-tracing](hardware-ray-tracing.md) 那一篇里也讲了 GPU-driven 的另一面——ray tracing 本身就是 GPU 上"自己决定 trace 哪些 ray"。这两条路（raster + GPU cull / ray tracing）在现代引擎里逐渐合流——Unreal 5 的 Lumen 同时用 GPU-driven raster 和 hardware ray tracing,后者作为前者的 fallback / 高质量路径。

## 5 · Mesh shader:把几何处理也搬上 GPU

indirect draw 解决了"draw call 数量"问题,但有一个东西还在传统 pipeline 里——**几何处理**。传统的 vertex shader pipeline 是固定的:vertex shader →（可选 geometry/tessellation）→ rasterizer。每个 vertex shader invocation 处理一个顶点,每三个顶点生成一个三角形,这个过程 GPU 硬件固定。你想在几何层面做 culling（比如"这个 mesh 的这一小片整个在视锥外,跳过"）,传统 pipeline 做不到——顶点已经流过 vertex shader,三角形已经组装,rasterizer 才能丢弃。

**Mesh shader**（D3D12 Ultimate / Vulkan 的 `VK_EXT_mesh_shader`）是替代传统 vertex pipeline 的新 stage。它把几何处理单位从"顶点"换成 **meshlet**——一小块网格（典型 32-64 个顶点、最多 126 个三角形）。mesh shader pipeline 两个 stage:**task shader**（可选,做 meshlet-level culling/LOD,生成 mesh shader 工作量）和 **mesh shader**（处理一个 meshlet,输出这个 meshlet 的顶点和三角形）。

mesh shader 的核心价值:**meshlet-level culling**。task shader 在 GPU 上跑,每个 thread 处理一个 meshlet,做 frustum/occlusion 测试,只对可见的 meshlet 派发 mesh shader。这比 vertex shader pipeline 的"逐顶点"粒度粗,但比"整个物体"粒度细——适合处理那种"一个大物体部分在视锥内、部分在外"的场景（巨型地形、巨型建筑）。

```glsl
#version 450
#extension GL_EXT_mesh_shader : enable

layout(local_size_x = 32) in;       // 一个 task shader workgroup
layout(set = 0, binding = 0) readonly buffer MeshletBuffer {
    Meshlet meshlets[];
};
taskPayloadSharedEXT MeshletPayload payload;

struct Meshlet {
    center: vec4f,           // xyz + radius
    vertex_offset: u32,
    index_offset: u32,
    vertex_count: u32,
    triangle_count: u32,
};

void main() {
    let meshlet_idx = gl_GlobalInvocationID.x;
    if (meshlet_idx >= num_meshlets) { return; }
    
    let m = meshlets[meshlet_idx];
    // meshlet-level frustum cull
    if (!sphere_in_frustum(m.center.xyz, m.center.w)) {
        return;
    }
    
    // 可见 meshlet,派发 1 个 mesh shader workgroup
    payload.visible[meshlet_idx % 32] = meshlet_idx;
    EmitMeshTasksEXT(1, 1, 1);
}
```

mesh shader stage 接收 task shader 派发,处理一个 meshlet,输出顶点和三角形:

```glsl
#version 450
#extension GL_EXT_mesh_shader : enable

layout(local_size_x = 32) in;            // 一个 mesh shader workgroup 32 thread
layout(triangles, vertices = 3, max_vertices = 64, max_primitives = 126) out;
layout(location = 0) out VertexData {
    vec3 world_pos;
    vec3 normal;
    vec2 uv;
} v_out[];

void main() {
    let meshlet_idx = payload.visible[gl_WorkGroupID.x];
    let m = meshlets[meshlet_idx];
    
    // 每 thread 处理 meshlet 的几个顶点
    uint vid = gl_LocalInvocationID.x;
    if (vid < m.vertex_count) {
        uint global_vid = m.vertex_offset + vid;
        vec3 pos = vertex_buffer[global_vid].pos;
        v_out[vid].world_pos = (model_matrix * vec4(pos, 1.0)).xyz;
        v_out[vid].normal = vertex_buffer[global_vid].normal;
        v_out[vid].uv = vertex_buffer[global_vid].uv;
        SetMeshOutputsEXT(m.vertex_count, m.triangle_count);
    }
    
    // 输出三角形 index
    uint tid = gl_LocalInvocationID.x;
    if (tid < m.triangle_count) {
        uint i0 = index_buffer[m.index_offset + tid * 3 + 0];
        uint i1 = index_buffer[m.index_offset + tid * 3 + 1];
        uint i2 = index_buffer[m.index_offset + tid * 3 + 2];
        gl_PrimitiveTriangleIndicesEXT[tid] = uvec3(i0, i1, i2);
    }
}
```

mesh shader 的支持情况:RTX 20+（2018）原生支持 RDNA 2+（2020,PS5/Xbox Series）原生支持 Intel Arc（2022）支持。Vulkan 上目前还是 extension（`VK_EXT_mesh_shader`）,不是 core,但 desktop 主流 GPU 都支持。移动端目前几乎不支持,这是为什么 mesh shader 还只在 desktop/console 引擎里用。

mesh shader 是 [gpu-compute-fundamentals](gpu-compute-fundamentals.md) 那一篇讲的 compute shader 模型的延伸——mesh shader 本质上是"输出顶点和三角形的 compute shader"。理解了 [gpu-compute-fundamentals](gpu-compute-fundamentals.md) 的 workgroup、shared memory、barrier,mesh shader 的写法对你不陌生。

Nanite 用 mesh shader 做到了"GPU 上自己选 LOD、自己 cull meshlet、自己 rasterize"。Nanite 的细节是专利级的,但公开的部分（Unreal 5 docs + GDC 2021 talk）清楚显示:它的核心是把传统 vertex pipeline 完全替换成 mesh shader + 软件光栅化（cluster 太小时用 compute shader 自己光栅化,跳过固定硬件 rasterizer）。

## 6 · Variable Rate Shading:不是每个像素都需要全力

前面几节都在砍 CPU 工作,这一节砍 GPU 工作——具体地,砍 fragment shader 的工作量。

朴素渲染里,每个像素的 fragment shader 跑同样多次采样、同样多次光照计算。但这其实没必要——你的眼睛对屏幕不同区域的细节敏感度差别巨大。**中心凹**（fovea,视网膜中心）分辨率高,你看得清;**周边视觉**（peripheral）模糊,你看不清细节。运动模糊区域（motion-blurred）你本来就看不清。UI 后面的区域（被 HUD 覆盖）,你根本看不到。

**Variable Rate Shading**（VRS,D3D12 Ultimate / Vulkan 的 `VK_EXT_fragment_shading_rate`）允许你**指定屏幕上不同区域用不同的 fragment shader 采样率**。最低可以到 1/16（每 4x4 像素跑一次 fragment shader,结果覆盖整个 4x4 块）。你把屏幕中心设成 1x1（全分辨率）,周边设成 2x2,极周边设成 4x4——画面几乎无差别,GPU 节省 30-50% 的 fragment 工作量。

VRS 有三种使用模式。第一,**per-draw VRS**——draw call 时指定一个固定 shading rate,整个 draw 用这个 rate。适合"远处的物体用 2x2、近处的物体用 1x1"。第二,**per-primitive VRS**——vertex/geometry shader 输出一个 shading rate,每个三角形用不同 rate。适合"快速运动的物体（高 velocity）用低 rate"。第三,**screen-space image VRS**——你提供一张和屏幕一样大的 shading rate image,每个 tile（典型 16x16 像素）一个 rate。适合"UI 区域用最低 rate、中心区域用最高 rate、运动区域根据 motion vector 决定 rate"。

```rust
// 设置 screen-space VRS
let shading_rate_image = create_shading_rate_image(&device, screen_size / 16);
// 每帧 CPU 或 GPU 更新这张图,每个 tile 一个 u8 表示 rate

unsafe {
    device.cmd_set_fragment_shading_rate(
        cmd,
        &vk::FragmentShadingRateCombinerOpKHR::MAX,  // 怎么合并 pipeline、primitive、image rate
        // ...
    );
}
```

VR 渲染特别受益于 VRS——人眼在 VR 头盔里能精确知道"用户在看哪"（eye tracking）,foveated rendering（注视点渲染）用 VRS 把注视点外的区域降到 1/4 甚至 1/16 分辨率,用户感知不到,GPU 节省 60-70% 工作量。这是为什么 Quest Pro、PSVR2 都内置 eye tracking + VRS。

VRS 的代价是边缘可能出现 artifact——shading rate 低的区域,边缘锯齿更明显,因为 fragment shader 只跑一次、覆盖整块。修复方法是 TAA（temporal anti-aliasing,参考 [taa-and-upscaling](taa-and-upscaling.md)）+ 在 rate 边界做插值。但绝大多数情况下,VRS 的代价远小于收益。

## 7 · Visibility buffer:把光栅化和着色彻底解耦

最后一项技术,是 [deferred-and-clustered](deferred-and-clustered.md) §4 提过的 visibility buffer 的延续。那里我讲过它的概念——存几何 ID 而不是材质属性。这里我把它放到"现代渲染技术"的语境里讲,因为它和前面所有技术（bindless、indirect draw、mesh shader）形成闭环。

朴素 raster 管线里,光栅化和着色是**耦合**的——三角形被光栅化时,fragment shader 同时跑,采样纹理、算光照、输出颜色。这有一个工程问题:**复杂材质**。一个场景里有水面 shader、皮肤 SSS shader、布料 shader、PBR shader,它们共享同一个 G-Buffer（deferred）或同一个 fragment shader（forward）的格式。但如果你想在 fragment 阶段做"per-material code path",要么用 shader branch（慢）、要么用 stencil routing（多 pass）。

**Visibility buffer** 把这两阶段完全解耦。第一阶段（**visibility pass**）只光栅化,每个像素只写**几何 ID**——`triangle_id`（这个像素被哪个三角形覆盖）+ `instance_id`（哪个物体）+ barycentric（重心坐标,用于重建顶点属性）+ depth。每像素 8-16 字节,远小于 G-Buffer 的 56 字节。

```glsl
// visibility.frag —— 只写几何 ID,不做任何着色
layout(location = 0) out vec4 o_visibility;  // RG = triangle_id+instance_id,B = bary.x,A = bary.y
flat in uint v_triangle_id;
flat in uint v_instance_id;
in vec3 v_barycentric;

void main() {
    // 编码 triangle_id + instance_id + bary
    o_visibility = vec4(
        uintBitsToFloat(v_triangle_id),
        uintBitsToFloat(v_instance_id),
        v_barycentric.x,
        v_barycentric.y
    );
    // depth 由光栅化硬件写
}
```

第二阶段（**shade pass**）是一个 fullscreen compute pass,每像素读 visibility buffer,根据 triangle_id + instance_id **从 bindless vertex buffer 重建几何属性**,然后根据 material_id 走对应 material shader。

```glsl
// shade.comp —— 读 visibility,重建属性,着色
layout(set = 0, binding = 0) readonly buffer VertexBuffer { Vertex vertices[]; }[];
layout(set = 0, binding = 1) readonly buffer IndexBuffer { uint indices[]; };
layout(set = 0, binding = 2) uniform sampler2D visibility_tex;

void main() {
    ivec2 pixel = ivec2(gl_GlobalInvocationID.xy);
    vec4 vis = texelFetch(visibility_tex, pixel, 0);
    uint tri_id = floatBitsToUint(vis.x);
    uint inst_id = floatBitsToUint(vis.y);
    vec2 bary = vis.zw;
    vec3 bary3 = vec3(bary.x, bary.y, 1.0 - bary.x - bary.y);
    
    // 从 bindless vertex buffer 重建顶点属性
    uint i0 = indices[tri_id * 3 + 0];
    uint i1 = indices[tri_id * 3 + 1];
    uint i2 = indices[tri_id * 3 + 2];
    Vertex v0 = vertices[inst_id][i0];
    Vertex v1 = vertices[inst_id][i1];
    Vertex v2 = vertices[inst_id][i2];
    
    vec3 world_pos = bary_interp(v0.pos, v1.pos, v2.pos, bary3);
    vec3 normal = normalize(bary_interp(v0.normal, v1.normal, v2.normal, bary3));
    vec2 uv = bary_interp(v0.uv, v1.uv, v2.uv, bary3);
    
    uint material_id = vertices[inst_id][i0].material_id;
    // 根据 material_id 走对应 material shader
    out_color = shade_material(material_id, world_pos, normal, uv, ...);
}
```

visibility buffer 的优势非常突出。第一,**VRAM 占用极低**——16 字节/像素 vs G-Buffer 的 56 字节,4K 下从 224 MB 降到 64 MB。第二,**多材质友好**——shade pass 是 compute shader,每个 thread 可以根据 material_id 走完全不同的 code path,没有 stencil routing、没有多 pass。第三,**MSAA 友好**——per-sample 存 visibility（4x MSAA 只增加 4x visibility buffer,小）,shade pass 在 sample 上跑,完美抗锯齿。第四,**和 ray tracing 集成自然**——ray tracing 的 hit 信息本质上就是"visibility",visibility buffer 的 shade pass 可以无缝地把 raster 的 visibility 和 ray tracing 的 visibility 合并处理。

代价是 shade pass 要**重建顶点属性**,这意味着 bindless vertex buffer 是硬性要求（没有 [09C-5](../../phase-9/09C-5-descriptors-and-uniforms.md) §10 那套 bindless,visibility buffer 实现不了）。重建顶点属性还要查 index buffer + 三次 vertex fetch,可能有 cache miss。但这些在现代 GPU 上可控——尤其是 mesh shader pipeline（§5）输出 visibility 时,顶点属性已经在 on-chip memory 里。

visibility buffer 是 Nanite 的渲染基础。Nanite 在 mesh shader 里输出 visibility buffer,跳过传统的"fragment shader + G-Buffer"组合,在 visibility buffer 之上做 software rasterization（cluster 太小时,直接 compute shader 写 visibility）。这就是为什么 Nanite 能渲染数十亿三角形——传统 raster + G-Buffer 在这个规模下带宽爆炸,visibility buffer 让每像素的成本降到 16 字节。

## 8 · 这些技术为什么"必须"组合:生产现实

到这里我把每一项技术都讲完了。但它们的真正威力在于**组合**。让我用一个具体的渲染管线把它们串起来,你就看到为什么"现代渲染"是一个整体工程,不是孤立的小技巧。

一个现代 GPU-driven renderer 的单帧 pipeline（参考 Unreal 5 Nanite + Lumen 的公开架构）:

第一步,**CPU 端只做最少的事**。CPU 把场景的 object buffer（一帧不变的部分）上传一次,然后发几条命令:cull dispatch、barrier、visibility render dispatch、barrier、shade compute dispatch、barrier、post-process dispatch。CPU 端总开销 50 μs 以内。

第二步,**GPU cull pass**（§4）。compute shader 遍历所有 meshlet（mesh shader 的 §5 概念）,frustum + occlusion cull,可见的 meshlet 写进一个 indirect mesh shader dispatch buffer。

第三步,**visibility render pass**（§7）。mesh shader 处理可见 meshlet,光栅化,输出 visibility buffer（每像素 16 字节几何 ID）。这一步用 bindless（§2）访问所有 vertex/index buffer,用 indirect dispatch（§4）由 GPU 自己决定工作量。

第四步,**shade pass**（§7）。fullscreen compute shader 读 visibility buffer,重建属性,根据 material_id 走对应 material shader。这一步可以用 VRS（§6）——如果某些区域是 motion blur 或 UI 后面,shade 在低 rate 跑。

第五步,**lighting / GI pass**。clustered forward（参考 [deferred-and-clustered](deferred-and-clustered.md)）的 light culling + 累加,Lumen 风格的 GI（可能用 [hardware-ray-tracing](hardware-ray-tracing.md)）。

第六步,**post-process**。tone mapping、TAA（[taa-and-upscaling](taa-and-upscaling.md)）、bloom,这些是经典 pass。

注意这个 pipeline 的几个特征。第一,**CPU 几乎不参与绘制决策**——所有 culling、LOD、draw 生成都在 GPU。第二,**资源全部 bindless**——没有 CPU bind。第三,**pass 数量多**——cull、visibility、shade、lighting、GI、post-process,加上 shadow map、reflection probe 等,轻松 20+ pass。第四,**pass 之间有严格的资源依赖和 barrier**。这四点中,后两点直接决定了你需要 [09B-3 frame graph](../../phase-9/09B-3-frame-graph.md)——手写这种复杂度的 pipeline 是噩梦。frame graph 让你声明每个 pass 的输入输出,它自动算 barrier、自动复用内存、自动可视化整个 frame。没有 frame graph,你写不到 Nanite 这个复杂度。

这些技术的另一个共同要求是**显式 API**——Vulkan、D3D12、Metal。OpenGL / WebGL 没有 bindless（确切说有 `NV_bindless_texture` 扩展但不是 core）、没有 indirect draw count（有 `GL_ARB_indirect_parameter` 但碎片化）、没有 mesh shader（`GL_NV_mesh_shader` extension）、没有 VRS（`GL_NV_shading_rate_image` extension）。这就是为什么 [09C-5](../../phase-9/09C-5-descriptors-and-uniforms.md) 那一篇讲的 Vulkan descriptor 系统、[multithreaded-rendering](multithreaded-rendering.md) 讲的多线程 command buffer 录制,是这一篇的前提——你在 explicit API 里学的每一个概念,都是为了在这里能跑起来。

## 9 · 在你 HH 项目里动手（做中学红线）

这一篇的做中学,我给你**一个最高杠杆的单步**——把你 HH 渲染器里现有的某个 CPU draw loop,改造成 bindless + indirect draw。这一步走完,你就跨过了从"朴素渲染器"到"现代渲染器"的那道门槛。

第一步,**挑一个循环**。你 HH 项目里应该已经有一个"画一批 instanced 物体"的循环——草地、粒子、或者一堆 box。如果没有,先做一个:画 1000 个 box,每个不同的位置、不同的 MVP。朴素方式:CPU 循环 1000 次,每次 push constants 一个 MVP、调 `vkCmdDraw`。先跑这个朴素版,**用 Tracy 量 CPU 时间**——你应该看到大约 1-5 ms（1000 个 draw 的录制开销）。

第二步,**改成 instanced draw**。把 1000 个 MVP 打包进一个 SSBO,shader 里用 `gl_InstanceID` 索引,一条 `vkCmdDraw(vertex_count, 1000, 0, 0)` 画完。CPU 时间应该降到 5 μs 以内。这一步不是本节目标,但它是 prerequisite——你要先理解 instancing。

第三步,**改成 indirect draw**。把 instanced draw 的参数写进一个 indirect buffer（一个 `DrawIndirectCommand`）,用 `vkCmdDrawIndirect` 提交。CPU 时间不变,但你拿到了"GPU 写 buffer 控制绘制"的能力。

第四步,**改成 indirect draw count**。建两个 buffer:一个装 draw commands（每条对应一个物体）,一个装 count（GPU atomic 写）。CPU 调 `vkCmdDrawIndirectCount`,count 来自 GPU buffer。先用 CPU 把 count 写死成 1000,验证通路。

第五步,**加 compute cull pass**。dispatch 一个 compute shader,每 thread 处理一个物体,frustum 测试,可见的写进 draw commands buffer + atomic++ count。CPU 不再写 count——它由 GPU 决定。

第六步,**量 CPU 时间**。Tracy 看 cull dispatch + indirect draw 的 CPU 累计时间,应该比朴素版本的 1000 个 draw call 快几十倍。这一步验证了你跨过了 CPU-bound 门槛。

第七步,**加 bindless（可选,但推荐）**。如果你的 1000 个物体有不同贴图,把贴图绑成一个 bindless 数组,shader 里用 `nonuniformEXT` 索引。这一步彻底消除"逐物体 bind"。

验收标准:**CPU 时间从几毫秒降到几十微秒,帧率从受限于 draw call 变成受限于 GPU 实际工作量**。把这个对比数据写进 commit message——这是你 HH 项目里最有说服力的一次性能测量。

如果你野心更大,可以在 §5 加 mesh shader 的实验——但 mesh shader 要求 GPU 支持 + extension enable,且改 pipeline 改动大,建议作为后续独立的实验。VRS（§6）也类似——单独实验,不在"红线"路径上。

## 10 · 练习

练习一,Lv1 概念辨析。CPU-bound 和 GPU-bound 的区别是什么?为什么升级 GPU 解决不了 CPU-bound?朴素 `vkCmdDrawIndexed` 的 CPU 端开销大致来自哪四个来源?请用一句话概括 indirect draw 如何砍掉其中哪一刀。

练习二,Lv1 概念辨析。bindless resources 和"每个物体一个 descriptor set"的区别,在于 bind 次数。但 bindless 不是没有代价——shader 端 `nonuniformEXT` 起什么作用?如果忘了加这个 qualifier,会发生什么（提示:想想 warp divergence 和 driver 编译）?请在你的 dev log 里写下你对这个 qualifier 的解释。

练习三,Lv2 动手实践。完成前面 §9 的第一到第五步。要求:用 Tracy 测出朴素版本和 GPU-driven 版本的 CPU 时间对比,数据写进 commit message。验证层零报错。如果实现了 compute cull,记录下"cull pass 自己的 GPU 时间"——这个数字应该远小于它砍掉的 CPU 时间。

练习四,Lv3 迁移设计。不写代码,在你 HH 项目的渲染器设计文档里画一个"现代 GPU-driven frame"的 pipeline 图。要求:cull pass → visibility render → shade pass → lighting → post-process,每个 pass 标出输入/输出资源、barrier 时机、bindless descriptor set 怎么组织。讨论:[09B-3 frame graph](../../phase-9/09B-3-frame-graph.md) 在这个管线里帮你做了什么?

练习五,Lv4 开源探索。在 Sascha Willems 的 Vulkan examples 仓库里找 `indirectdraw` 和 `descriptorindexing` 两个 example。**不要运行**,只读代码:它的 indirect buffer 是 CPU 写还是 GPU 写?它的 bindless 数组用了 `PARTIALLY_BOUND` flag 吗?把这两个 example 的核心思路和你这一篇的讲解对照,写下三个你之前没注意到的细节。

## 11 · 延伸阅读

外部稳定 URL:
- **Vulkan spec descriptor indexing**（Vulkan 1.2 core）:https://www.khronos.org/registry/vulkan/specs/1.2-extensions/html/vkspec.html#VK_EXT_descriptor_indexing
- **VK_EXT_mesh_shader** spec:https://registry.khronos.org/vulkan/specs/1.3-extensions/man/html/VK_EXT_mesh_shader.html
- **VK_EXT_fragment_shading_rate** spec:https://registry.khronos.org/vulkan/specs/1.3-extensions/man/html/VK_EXT_fragment_shading_rate.html
- **Unreal 5 Nanite** GDC 2021 talk（"A Deep Dive into Nanite"）:https://advances.realtimerendering.com/s2021/Karis_Nanite_SIGGRAPH_Advances_2021_final.pdf
- **GPU-Driven Rendering Pipelines**（Willems / gl_Helper）综述:https://vkguide.dev/docs/gpu_driven/gpu_driven_overview/
- **Visibility Buffer**（Burns 2013,改良版 Unreal 用）:http://www.jordanstevenstechart.com/visibility-buffer
- **D3D12 Mesh Shaders**（Microsoft docs）:https://learn.microsoft.com/en-us/windows/win32/direct3d12/mesh-shader
- **Variable Rate Shading** intro（Intel）:https://www.intel.com/content/www/us/en/developer/articles/technical/adaptive-shading-intel-integrated-graphics.html
- **Sascha Willems Vulkan examples**（`indirectdraw`、`descriptorindexing`、`meshshader`）:https://github.com/SaschaWillems/Vulkan
- **GDC 2015 "Driven to Destruction"**（DICE GPU-driven rendering talk）:https://www.ea.com/frostbite/news/gpu-driven-rendering

真实开源源码:
- wgpu examples（`boids`、`storage-buffers` 是 GPU-driven 的雏形）:https://github.com/gfx-rs/wgpu/tree/trunk/examples
- bevy_render `gpu_preprocess` 和 `batching`:https://github.com/bevyengine/bevy/tree/main/crates/bevy_render
- Unreal Nanite（部分）:https://github.com/EpicGames/UnrealEngine/blob/release/Engine/Source/Runtime/Renderer/Private/Nanite
- Granite engine GPU-driven（themaister）:https://github.com/Themaister/Granite

---

这一篇是 phase-6 渲染顶端的核心。在你 HH 项目里,你之前学过的——[09C-5](../../phase-9/09C-5-descriptors-and-uniforms.md) 的 descriptor、[deferred-and-clustered](deferred-and-clustered.md) 的多光源、[gpu-compute-fundamentals](gpu-compute-fundamentals.md) 的 compute、[spatial-acceleration](spatial-acceleration.md) 的 culling、[multithreaded-rendering](multithreaded-rendering.md) 的多线程录制——都在这里汇流成一条现代渲染管线。完成 §9 的红线动手,你就完成了从"会画三角形"到"会画一百万个三角形"的跃迁。后面 [hardware-ray-tracing](hardware-ray-tracing.md) 把 ray tracing 接到这条管线上,[post-processing](post-processing.md) 在管线末端加最后一道美化——它们都建立在这一篇的地基上。
