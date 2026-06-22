# glTF 与模型加载:glb、网格导入、骨骼蒙皮、变形目标

> OBJ 没法存动画。FBX 是闭源混乱。COLLADA 设计冗余。直到 2017 年 Khronos 发布 **glTF**(GL Transmission Format),3D 模型领域终于有了"3D 界的 JPEG"。Web、Unreal、Unity、Blender、Godot 全部支持。本文从 glTF JSON 结构讲到 glb 二进制容器,从静态网格讲到骨骼蒙皮和 morph targets,让你能写一个能加载并渲染任何 glTF 模型的代码。

## 0 · 为什么需要 glTF

3D 模型历史上格式纷繁复杂:

| 格式 | 谁用 | 问题 |
|---|---|---|
| OBJ | 通用 | 太简单(无动画、无材质细节) |
| FBX | Autodesk 主推 | 闭源,SDK 巨大,实现不一致 |
| COLLADA | 2000s XML 标准 | 过度设计,工具支持差 |
| 3ds / max | 3ds Max | 工具特有,不可移植 |
| blend | Blender | 工作格式,不是分发格式 |

游戏行业痛点:美术用 Maya,导出 FBX;Unreal 读 FBX,但 Unreal 的 FBX 解析器和 Unity 的不一致,同一个文件表现不同。改一次模型要在多个软件重导出。

Khronos(GL / Vulkan 标准组织)2013 年开始设计 glTF,目标:**3D 界的 JPEG**——开放、高效、广泛支持。2017 年 glTF 2.0 发布,定义 PBR 材质标准。今天:

- **Web**:Three.js、Babylon.js 默认 glTF
- **引擎**:Unreal / Unity / Godot / Bevy 支持 glTF
- **工具**:Blender / Maya / 3ds Max 原生导出
- **存档**:Sketchfab、Microsoft Paint 3D 用 glTF

**glTF 的核心设计**:

1. **JSON 元数据 + 二进制资源**:JSON 描述结构,二进制存顶点 / 索引
2. **PBR 材质**:用金属度-粗糙度工作流(与 Filament / Unreal 一致)
3. **动画 + 骨骼**:完整支持角色动画
4. **可扩展**:扩展机制(KHR_* 前缀)支持新特性

**读完这一篇你能**:
- 解析 glTF 的 JSON 结构,理解每个字段
- 实现 glb 二进制容器加载
- 渲染带 PBR 材质的静态网格
- 加载骨骼蒙皮和 morph targets

## 1 · glTF 顶层结构

glTF 文件是 JSON(或 glb 包装的 JSON),顶层字段:

```json
{
  "asset": { "version": "2.0", "generator": "Blender" },
  "scene": 0,
  "scenes": [...],
  "nodes": [...],
  "meshes": [...],
  "materials": [...],
  "accessors": [...],
  "bufferViews": [...],
  "buffers": [...],
  "images": [...],
  "textures": [...],
  "samplers": [...],
  "skins": [...],
  "animations": [...],
  "cameras": [...]
}
```

每个字段是一个数组。下面逐个讲。

## 2 · 数据三件套:Buffer / BufferView / Accessor

glTF 把"二进制数据"分三层抽象:

```
Buffer(原始二进制 blob)
   ↓ 一段范围
BufferView(一段连续的字节,可能对齐)
   ↓ 类型 + 解读
Accessor(解读为特定类型的元素数组)
```

### Buffer

```json
"buffers": [
  { "byteLength": 1024, "uri": "model.bin" }
]
```

`uri` 可以是外部文件路径,或 data URI(`data:application/octet-stream;base64,...`)。

### BufferView

```json
"bufferViews": [
  { "buffer": 0, "byteOffset": 0, "byteLength": 768, "target": 34962 },
  { "buffer": 0, "byteOffset": 768, "byteLength": 256, "target": 34963 }
]
```

`target` 是 OpenGL 目标:

- 34962 = `ARRAY_BUFFER`(顶点数据)
- 34963 = `ELEMENT_ARRAY_BUFFER`(索引数据)

### Accessor

```json
"accessors": [
  {
    "bufferView": 0,
    "byteOffset": 0,
    "componentType": 5126,   // FLOAT
    "count": 64,
    "type": "VEC3",          // 每个元素是 vec3
    "min": [-1, -1, -1],
    "max": [1, 1, 1]
  }
]
```

`componentType`:

- 5120 = BYTE(signed)
- 5121 = UNSIGNED_BYTE
- 5122 = SHORT
- 5123 = UNSIGNED_SHORT
- 5125 = UNSIGNED_INT
- 5126 = FLOAT

`type`:

- "SCALAR" — 1 个 component
- "VEC2" — 2 个
- "VEC3" — 3 个
- "VEC4" — 4 个
- "MAT4" — 16 个(4×4 矩阵)

每个 accessor 元素大小 = `component 大小 × type 维度`。FLOAT VEC3 = 4 × 3 = 12 字节 / 元素。

### Rust 解析

```rust
#[derive(serde::Deserialize)]
struct Gltf {
    asset: Asset,
    buffers: Vec<Buffer>,
    buffer_views: Vec<BufferView>,
    accessors: Vec<Accessor>,
    meshes: Vec<Mesh>,
    nodes: Vec<Node>,
    scenes: Vec<Scene>,
    // ...
}

#[derive(serde::Deserialize)]
struct Buffer {
    byte_length: u64,
    uri: Option<String>,
}

#[derive(serde::Deserialize)]
struct BufferView {
    buffer: usize,
    byte_offset: Option<u64>,
    byte_length: u64,
    byte_stride: Option<u64>,
    target: Option<u32>,
}

#[derive(serde::Deserialize)]
struct Accessor {
    buffer_view: usize,
    byte_offset: Option<u64>,
    component_type: u32,
    count: u64,
    #[serde(rename = "type")]
    element_type: String,
    min: Option<Vec<f32>>,
    max: Option<Vec<f32>>,
}
```

每段注释:

- `serde::Deserialize` — 用 serde 自动反序列化 JSON
- `byte_stride` — 对于交错数据(interleaved)每元素之间的步长
- `Option<...>` 因为字段可能缺失

## 3 · Mesh 结构

```json
"meshes": [
  {
    "primitives": [
      {
        "attributes": {
          "POSITION": 0,    // accessor 索引
          "NORMAL": 1,
          "TEXCOORD_0": 2,
          "TANGENT": 3
        },
        "indices": 4,
        "material": 0,
        "mode": 4
      }
    ]
  }
]
```

- `primitives` — 一个 mesh 由多个"图元"组成(每个图元可能不同材质)
- `attributes` — 顶点属性,每个值是 accessor 索引
- `POSITION` — 顶点位置(必须 VEC3 FLOAT)
- `NORMAL` — 法线(必须 VEC3 FLOAT,归一化)
- `TEXCOORD_0` — 第一组 UV(必须 VEC2)
- `TANGENT` — 切线(必须 VEC4,w 是 handedness)
- `indices` — 索引 accessor
- `material` — 材质索引
- `mode` — OpenGL 绘制模式(4 = TRIANGLES)

## 4 · 加载并渲染静态网格

```rust
fn load_mesh(
    gltf: &Gltf, mesh: &Mesh, buffers: &[Vec<u8>],
) -> Vec<Primitive> {
    let mut prims = Vec::new();
    for prim in &mesh.primitives {
        // POSITION
        let pos_accessor = &gltf.accessors[prim.attributes["POSITION"]];
        let positions = read_accessor::<[f32; 3]>(
            gltf, pos_accessor, buffers,
        );
        
        // NORMAL(可选)
        let normals = prim.attributes.get("NORMAL")
            .map(|i| read_accessor::<[f32; 3]>(
                gltf, &gltf.accessors[*i], buffers,
            ));
        
        // TEXCOORD_0(可选)
        let texcoords = prim.attributes.get("TEXCOORD_0")
            .map(|i| read_accessor::<[f32; 2]>(
                gltf, &gltf.accessors[*i], buffers,
            ));
        
        // INDICES(可选)
        let indices = prim.indices
            .map(|i| read_accessor::<u32>(
                gltf, &gltf.accessors[i], buffers,
            ));
        
        prims.push(Primitive {
            positions, normals, texcoords, indices,
            material: prim.material,
        });
    }
    prims
}

fn read_accessor<T: bytemuck::Pod>(
    gltf: &Gltf,
    accessor: &Accessor,
    buffers: &[Vec<u8>],
) -> Vec<T> {
    let view = &gltf.buffer_views[accessor.buffer_view];
    let buffer = &buffers[view.buffer];
    let view_offset = view.byte_offset.unwrap_or(0) as usize;
    let accessor_offset = accessor.byte_offset.unwrap_or(0) as usize;
    let element_size = element_size(&accessor.element_type, accessor.component_type);
    let stride = view.byte_stride.unwrap_or(element_size as u64) as usize;
    
    let mut result = Vec::with_capacity(accessor.count as usize);
    for i in 0..accessor.count as usize {
        let offset = view_offset + accessor_offset + i * stride;
        let bytes = &buffer[offset..offset + std::mem::size_of::<T>()];
        result.push(*bytemuck::from_bytes::<T>(bytes));
    }
    result
}
```

每段注释:

- `bytemuck::Pod` — "Plain Old Data",允许按字节解释
- `element_size` 根据 type 和 componentType 算每元素字节数
- `byte_stride` 默认 = element_size(紧凑布局);可能更大(interleaved)
- `bytemuck::from_bytes` — 安全地把字节切片转 `&T`

## 5 · Node 树:场景图

glTF 用**场景图**(scene graph)——树状节点,每个节点有变换矩阵或 TRS(Translation, Rotation, Scale)。

```json
"nodes": [
  { "name": "root", "children": [1, 2], "translation": [0, 0, 0] },
  { "name": "arm_L", "mesh": 0, "translation": [-1, 0, 0] },
  { "name": "arm_R", "mesh": 0, "translation": [1, 0, 0] }
],
"scenes": [
  { "nodes": [0] }
]
```

每个 node 的最终变换 = 父变换 × 本变换。遍历:

```rust
fn traverse_nodes(
    nodes: &[Node],
    node_idx: usize,
    parent_transform: Mat4,
    out: &mut Vec<(usize, Mat4)>,
) {
    let node = &nodes[node_idx];
    let local = node.matrix
        .unwrap_or_else(|| {
            let t = Mat4::from_translation(node.translation.into());
            let r = Mat4::from_quat(node.rotation.into());
            let s = Mat4::from_scale(node.scale.into());
            t * r * s
        });
    let world = parent_transform * local;
    out.push((node_idx, world));
    
    for &child in &node.children {
        traverse_nodes(nodes, child, world, out);
    }
}
```

每段注释:

- `TRS` — Translation + Rotation(Quat)+ Scale,可单独指定
- `matrix` — 直接给 4×4 矩阵(等价于 TRS,但更紧凑)
- 递归遍历,父变换 × 本变换得世界变换

## 6 · 材质:PBR

glTF 材质基于金属度-粗糙度工作流:

```json
"materials": [
  {
    "name": "Copper",
    "pbrMetallicRoughness": {
      "baseColorFactor": [0.95, 0.64, 0.54, 1.0],
      "metallicFactor": 1.0,
      "roughnessFactor": 0.3,
      "baseColorTexture": { "index": 0 },
      "metallicRoughnessTexture": { "index": 1 }
    },
    "normalTexture": { "index": 2 },
    "emissiveTexture": { "index": 3 },
    "emissiveFactor": [0.1, 0.05, 0.0],
    "alphaMode": "OPAQUE",
    "doubleSided": false
  }
]
```

字段:

- `baseColorFactor` — RGB 漫反射 / 金属 F0
- `metallicFactor` — 0 非金属 / 1 金属
- `roughnessFactor` — 0 光滑 / 1 粗糙
- `baseColorTexture` — 漫反射纹理
- `metallicRoughnessTexture` — 金属度(B 通道)+ 粗糙度(G 通道)合并纹理
- `normalTexture` — 法线贴图
- `emissiveTexture` / `emissiveFactor` — 自发光(发光物体)
- `alphaMode` — `OPAQUE` / `MASK` / `BLEND`
- `doubleSided` — 是否双面渲染

## 7 · 纹理

```json
"textures": [
  { "source": 0, "sampler": 0 }
],
"images": [
  { "uri": "texture.png" }
  // 或 { "bufferView": 5, "mimeType": "image/png" }
],
"samplers": [
  {
    "magFilter": 9729,   // LINEAR
    "minFilter": 9987,   // LINEAR_MIPMAP_LINEAR
    "wrapS": 10497,      // REPEAT
    "wrapT": 10497
  }
]
```

## 8 · 骨骼蒙皮(Skinning)

骨骼蒙皮让网格跟随"骨骼"变形。流程:

1. 定义**骨骼**(joint,一组 node)
2. 每个顶点关联到几个骨骼(最多 4 个),有权重
3. 每帧根据骨骼变换,顶点 = 加权平均各骨骼变换后的位置

### glTF Skin

```json
"skins": [
  {
    "joints": [3, 4, 5, 6, 7, 8],      // 骨骼节点索引
    "inverseBindMatrices": 9,           // accessor 索引
    "skeleton": 3                       // 根骨骼(可选)
  }
]
```

每个 node 可以指定 `skin` 字段和 `JOINTS_0` / `WEIGHTS_0` 顶点属性。

### Skinning 算法

```glsl
// Vertex shader
in vec3 in_position;
in vec4 in_joints;     // 4 个骨骼索引(每顶点)
in vec4 in_weights;    // 4 个权重(每顶点)

uniform mat4 u_joint_matrices[64];  // 当前帧每个骨骼的世界变换 × inverseBind

void main() {
    vec4 posed = vec4(0.0);
    for (int i = 0; i < 4; i++) {
        int joint_idx = int(in_joints[i]);
        mat4 joint_mat = u_joint_matrices[joint_idx];
        posed += joint_mat * vec4(in_position, 1.0) * in_weights[i];
    }
    gl_Position = u_mvp * posed;
}
```

每段注释:

- `in_joints` — 顶点关联的骨骼索引(每顶点最多 4 个)
- `in_weights` — 每个骨骼的权重(加起来 = 1)
- `joint_matrices` — 当前帧每个骨骼的"最终变换"(世界变换 × inverseBindMatrices)
- 4 个骨骼加权平均得最终位置

### Rust 实现

```rust
struct SkinnedVertex {
    position: [f32; 3],
    joints: [u16; 4],     // 骨骼索引
    weights: [f32; 4],    // 权重
}

fn compute_joint_matrices(
    skin: &Skin,
    nodes: &[Node],
    node_world_transforms: &[Mat4],
    inverse_bind: &[Mat4],
) -> Vec<Mat4> {
    let mut matrices = Vec::with_capacity(skin.joints.len());
    for (i, &joint_node) in skin.joints.iter().enumerate() {
        let world = node_world_transforms[joint_node];
        let inv_bind = inverse_bind[i];
        matrices.push(world * inv_bind);
    }
    matrices
}
```

## 9 · 动画

glTF 动画 = 关键帧轨道 + 时间轴:

```json
"animations": [
  {
    "name": "Walk",
    "channels": [
      {
        "sampler": 0,
        "target": {
          "node": 3,
          "path": "translation"  // translation / rotation / scale / weights
        }
      }
    ],
    "samplers": [
      {
        "input": 10,           // 时间轴 accessor
        "output": 11,          // 关键帧值 accessor
        "interpolation": "LINEAR"  // LINEAR / STEP / CUBICSPLINE
      }
    ]
  }
]
```

每帧根据当前时间,在关键帧之间插值,更新 target node 的 translation / rotation / scale。

```rust
fn sample_animation(
    animation: &Animation,
    time: f32,
    nodes: &mut [Node],
    gltf: &Gltf,
    buffers: &[Vec<u8>],
) {
    for channel in &animation.channels {
        let sampler = &animation.samplers[channel.sampler];
        let input_times = read_accessor::<f32>(
            gltf, &gltf.accessors[sampler.input], buffers,
        );
        let output = read_accessor_values(
            gltf, &gltf.accessors[sampler.output], buffers,
            &channel.target.path,
        );
        
        // 找当前时间所在区间
        let (i, t) = find_keyframe(&input_times, time);
        
        // 插值
        let value = match sampler.interpolation.as_str() {
            "LINEAR" => lerp(&output, i, t, &channel.target.path),
            "STEP" => output[i].clone(),
            "CUBICSPLINE" => cubic_spline(&output, i, t, &channel.target.path),
            _ => panic!("unknown"),
        };
        
        // 应用到 node
        apply_animation(&mut nodes[channel.target.node], &value, &channel.target.path);
    }
}
```

每段注释:

- `input` — 关键帧时间(秒)
- `output` — 关键帧值(translation: VEC3,rotation: VEC4 quaternion,...)
- `interpolation` — 插值方式(LINEAR / STEP / Hermite spline)
- 四元数旋转用 slerp(球面插值),不是 lerp

## 10 · Morph Targets(变形目标)

另一种动画方式:**morph targets**(也叫 blend shapes)。预定义几个目标形变,运行时混合。

```json
{
  "primitives": [{
    "targets": [
      { "POSITION": 12 },  // target 0 的位置偏移
      { "POSITION": 13 }   // target 1 的位置偏移
    ],
    "attributes": { ... }
  }],
  "weights": [0.0, 0.5]   // 初始权重
}
```

每个 mesh node 可以指定 `weights`,控制每个 target 的影响。

顶点最终位置 = 原始 + sum(weights[i] × target_offset[i])。

适合**面部表情**(笑脸、皱眉)等不需要骨骼动画的形变。

## 11 · glb:二进制容器

glTF 的 JSON 模式适合开发(易读、易编辑)。生产用 **glb**:把 JSON + 所有二进制资源打包成一个文件。

### glb 结构

```
[12 字节 header]
[JSON chunk][Binary chunk]
```

Header:

```
magic         4 字节 = b"glTF"
version       4 字节 = 2(LE)
length        4 字节 = 整个文件字节数
```

每个 chunk:

```
chunk_length  4 字节
chunk_type    4 字节 = b"JSON" 或 b"BIN\0"
chunk_data    chunk_length 字节
```

### Rust 解析 glb

```rust
fn parse_glb(data: &[u8]) -> Result<(String, Vec<u8>), String> {
    if data.len() < 12 { return Err("too short".into()); }
    if &data[..4] != b"glTF" { return Err("bad magic".into()); }
    let version = u32::from_le_bytes(data[4..8].try_into().unwrap());
    if version != 2 { return Err("only glTF 2.0 supported".into()); }
    let _length = u32::from_le_bytes(data[8..12].try_into().unwrap());
    
    let mut offset = 12;
    let mut json_str: Option<String> = None;
    let mut binary: Option<Vec<u8>> = None;
    
    while offset < data.len() {
        let chunk_len = u32::from_le_bytes(
            data[offset..offset+4].try_into().unwrap()
        ) as usize;
        let chunk_type = &data[offset+4..offset+8];
        let chunk_data = &data[offset+8..offset+8+chunk_len];
        
        if chunk_type == b"JSON" {
            json_str = Some(String::from_utf8_lossy(chunk_data).into_owned());
        } else if chunk_type.starts_with(b"BIN") {
            binary = Some(chunk_data.to_vec());
        }
        
        offset += 8 + chunk_len;
        // 4 字节对齐填充
        while offset % 4 != 0 && offset < data.len() {
            offset += 1;
        }
    }
    
    Ok((json_str.ok_or("no JSON chunk")?, binary.unwrap_or_default()))
}
```

每段注释:

- Header 12 字节固定
- 两个 chunk:JSON + BIN
- chunk 之间可能有 4 字节对齐填充(spaces 0x20)

## 12 · 完整加载流程

```
1. 读 .gltf(JSON) 或 .glb(二进制)
2. 如果 glb:拆出 JSON + binary
3. 解析 JSON,加载所有外部 buffer(.bin 文件 / data URI)
4. 构建 buffer / bufferView / accessor 缓存
5. 遍历 scene → nodes → 递归计算世界变换
6. 对每个 mesh node,加载 mesh primitives → GPU 顶点缓冲
7. 加载材质 → 创建 GPU shader pipeline
8. 加载 images / textures → GPU 纹理
9. 加载 skins → 预计算 joint matrices
10. 加载 animations → 启动动画播放器
11. 渲染循环:更新动画时间 → 重算 joint matrices → 渲染
```

## 13 · 历史

- 2013: Khronos 启动 glTF 项目
- 2015: glTF 1.0 发布(有局限)
- 2017: glTF 2.0 发布(引入 PBR,事实标准)
- 2019: KHR 扩展体系成熟(materials_volume、materials_transmission 等)
- 2020s: glTF 成 Web 3D 标准格式,所有主流工具支持

## 14 · 关联 Day

- **铺垫**:Day 100+ JSON 解析;Day 200 二进制;Day 466 glTF 引入
- **当天**:本篇是 glTF 专题
- **后续**:Day 500+ 模型动画实战;Day 600+ 优化加载

## 15 · 变式训练

### Lv1 · 概念辨析

**题**:glTF 为什么要分 Buffer / BufferView / Accessor 三层,而不是直接存"顶点数组"?

**参考解答**:三个原因:
1. **共享 buffer**:多个 accessor 可以共用一段二进制(同一个 .bin 文件),节省内存
2. **交错数据**:GPU 偏好交错布局(position + normal + uv 紧凑放)。BufferView 用 `byte_stride` 表达这种布局
3. **类型无关**:Buffer 是"原始字节",Accessor 是"解读方式"。同一个 buffer 可以用不同 accessor 解读(比如 position 也能当 colors)

这种分层让 glTF 既能表达紧凑布局,又能灵活解读。

### Lv2 · 动手实践

**题**:用 Rust 写一个程序,加载 glb 文件,打印所有 mesh 的顶点数和三角形数。

**参考解答**:

```rust
use gltf::Gltf;
use std::fs;

fn main() {
    let data = fs::read("model.glb").unwrap();
    let (document, _buffers, _images) = gltf::Gltf::from_slice(&data).unwrap();
    
    for mesh in document.meshes() {
        println!("Mesh: {}", mesh.name().unwrap_or("(unnamed)"));
        for prim in mesh.primitives() {
            let pos = prim.get(&gltf::Semantic::Positions).unwrap();
            let n_verts = pos.count();
            let n_indices = prim.indices().map(|a| a.count()).unwrap_or(n_verts);
            println!("  Primitive: {} verts, {} indices",
                     n_verts, n_indices);
        }
    }
}
```

### Lv3 · 迁移设计

**题**:glTF 用来描述 3D 模型。设计一个 "2D 模型格式"(类似 Spine / DragonBones),借鉴 glTF 的设计理念。需要支持哪些扩展?如何表达 2D 骨骼动画?

**提示**:2D 没有 tangent,但需要 2D 骨骼 + 网格变形 + 多层 sprite。

### Lv4 · 开源贡献

**题**:`gltf` 是 Rust 主流 glTF 加载库,GitHub: https://github.com/gltf-rs/gltf

1. clone 它
2. 看 `src/`:`gltf.rs`、`buffer.rs`、`mesh.rs`
3. 看它怎么用 serde
4. 可能的贡献:加一个 KHR 扩展支持(如 KHR_materials_volume)、改进文档

## 16 · Rust / Arch 落地代码

完整的 glTF 模型查看器骨架:

```toml
# Cargo.toml
[dependencies]
gltf = "1.4"
glam = "0.29"
bytemuck = "1.14"
image = "0.25"
```

```rust
// src/main.rs
use gltf::Gltf;
use std::fs;

struct LoadedModel {
    primitives: Vec<Primitive>,
    materials: Vec<Material>,
    textures: Vec<u32>,  // GPU texture IDs
    nodes: Vec<NodeTransform>,
    skins: Vec<Skin>,
}

struct Primitive {
    positions: Vec<[f32; 3]>,
    normals: Vec<[f32; 3]>,
    texcoords: Vec<[f32; 2]>,
    indices: Vec<u32>,
    material_idx: usize,
}

fn load_gltf(path: &str) -> LoadedModel {
    let data = fs::read(path).unwrap();
    let (document, buffers, images) = Gltf::from_slice(&data).unwrap();
    
    let mut primitives = Vec::new();
    for mesh in document.meshes() {
        for prim in mesh.primitives() {
            let reader = prim.reader(|buffer| buffers.get(buffer.index()).map(|b| b.as_slice()));
            
            let positions: Vec<_> = reader.read_positions().unwrap().collect();
            let normals: Vec<_> = reader.read_normals().unwrap_or_default().collect();
            let texcoords: Vec<_> = reader.read_tex_coords(0).unwrap_or_default()
                .into_f32().collect();
            let indices: Vec<_> = reader.read_indices().unwrap_or_default()
                .into_u32().collect();
            
            primitives.push(Primitive {
                positions, normals, texcoords, indices,
                material_idx: prim.material().index().unwrap_or(0),
            });
        }
    }
    
    // ... 加载材质、纹理、骨骼
    
    LoadedModel {
        primitives, materials: vec![], textures: vec![],
        nodes: vec![], skins: vec![],
    }
}

fn main() {
    let model = load_gltf("model.glb");
    println!("Loaded {} primitives", model.primitives.len());
    
    // 渲染循环:遍历 primitives,绑定材质,调用 glDrawElements
}
```

每行注释:

- `Gltf::from_slice(&data)` — 解析 glb 或 gltf 二进制
- `prim.reader(|b| ...)` — 创建 reader,提供 buffer 数据
- `read_positions()` / `read_normals()` — 强类型读取器
- `read_tex_coords(0)` — 第一组 UV,可能有多组
- `read_indices().into_u32()` — 索引可能是 u16/u32,统一转 u32

Arch 工具链:

```bash
# 装工具
sudo pacman -S blender    # 编辑器
sudo pacman -S gltf-viewer  # 简单查看器(AUR)
yay -S gltf-shell-extension  # 文件管理器缩略图

# 用 Blender 导出 glb
blender model.blend --background --python-expr "
import bpy
bpy.ops.export_scene.gltf(filepath='model.glb', export_format='GLB')
"

# 在线验证 glTF
# 用 https://github.com/donmccurdy/glTF-Validator
sudo pacman -S nodejs npm
npm install -g gltf-validator
gltf-validator model.glb

# 看模型结构
sudo pacman -S jq
# 解开 glb 看 JSON chunk
head -c 100 model.glb | xxd
# 输出:
# 00000000: 676c 5446 0200 0000 ...    glTF....

# Profile 模型加载
sudo pacman -S perf
perf record ./my_viewer
perf report
```

排错:

```bash
# 1. "Buffer access out of bounds"
#    原因:accessor 的 byteOffset + count 超过 buffer
#    排查:用 gltf-validator 验证文件

# 2. 模型看起来是黑
#    原因:法线没加载,或材质没正确绑定
#    排查:打印材质的 baseColorFactor,确认是 [1,1,1,1] 而不是 [0,0,0,0]

# 3. 动画不动
#    原因:没启动动画播放器,或时间没更新
#    排查:每帧打印当前动画时间

# 4. 骨骼蒙皮抖动
#    原因:joint_matrices 算错(没乘 inverseBindMatrices)
#    排查:打印一个 joint 的世界变换,确认动画时在变
```

## 17 · 延伸阅读

本仓库本地:

- `days/phase-7/deep-dives/png-format-complete.md` — glTF 引用的纹理
- `days/phase-7/deep-dives/asset-pipeline-architecture.md` — 资产管线整合
- `days/phase-6/deep-dives/lighting-models.md` — PBR 材质的光照

外部稳定 URL:

- glTF 2.0 规范: https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html
- glTF Tutorial: https://github.com/KhronosGroup/glTF-Tutorials
- glTF Validator: https://github.com/KhronosGroup/glTF-Validator
- glTF Sample Models: https://github.com/KhronosGroup/glTF-Sample-Models
- Khronos glTF 投影教程: https://www.khronos.org/blog/art-pipelines-for-glTF

真实开源源码:

- Rust gltf crate: https://github.com/gltf-rs/gltf
- Bevy gltf loader: https://github.com/bevyengine/bevy/blob/main/crates/bevy_gltf/src/lib.rs
- Filament gltfio: https://github.com/google/filament/tree/main/gltfio/src
- Three.js GLTFLoader: https://github.com/mrdoob/three.js/blob/master/examples/jsm/loaders/GLTFLoader.js
