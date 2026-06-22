# Shader 基础:GLSL 语法、vertex/fragment、uniform、attribute、MVP

> Day 235 创建 GL context,Day 237+ 用 GL 渲染需要 shader。这个 deep-dive 把 GLSL(OpenGL Shading Language)讲透,让你能写第一个 vertex + fragment shader,理解 uniform / attribute / MVP matrix 传递。

## 1 · Shader 是什么

**Shader**:运行在 GPU 上的一段程序。每个 vertex / pixel 各执行一次 shader 代码,数百到数千 SIMT core 并行。

渲染管线的 shader 阶段:

```
Vertex Data
   ↓
[Vertex Shader]   ← 每个 vertex 跑一次
   ↓
[Rasterization]   ← 把 triangle 拆成 pixel
   ↓
[Fragment Shader] ← 每个 pixel(实际是 fragment)跑一次
   ↓
Framebuffer (屏幕)
```

最常用的两个 shader:

- **Vertex shader**:变换 vertex 位置(模型 → 世界 → 相机 → 屏幕)
- **Fragment shader**:计算 pixel 颜色(光照、纹理采样)

现代 OpenGL 还支持:geometry / tessellation / compute shader(本文不展开)。

## 2 · GLSL 基础语法

GLSL(OpenGL Shading Language)是 C 风格语言,专为 GPU 设计。

### 2.1 类型

```glsl
// 标量
float a = 1.0;
int b = 2;
bool c = true;

// 向量
vec2 d = vec2(1.0, 2.0);
vec3 e = vec3(1.0, 2.0, 3.0);
vec4 f = vec4(1.0, 2.0, 3.0, 4.0);

// 矩阵
mat2 g = mat2(1.0);    // 单位矩阵
mat3 h = mat3(1.0);
mat4 i = mat4(1.0);

// 纹理采样器
sampler2D tex;
```

GLSL 没有指针、没有递归。简化语言,适合 GPU。

### 2.2 Swizzling

GLSL 的强大特性:`.xyz` 等取分量:

```glsl
vec4 v = vec4(1.0, 2.0, 3.0, 4.0);
vec3 a = v.xyz;      // (1, 2, 3)
vec2 b = v.zw;       // (3, 4)
vec3 c = v.xxx;      // (1, 1, 1)
vec4 d = v.xxyy;     // (1, 1, 2, 2)
```

任意组合 `.xyzw` / `.rgba` / `.stpq`,语义相同。

### 2.3 控制流

```glsl
// if
if (a > 0.5) { ... }

// for
for (int i = 0; i < 10; i++) { ... }

// while
while (i < 10) { ... }
```

GPU 上的分支**可能导致 divergence**(同一 warp 不同 lane 走不同分支,执行时间累加)。shader 应尽量无分支或用 `mix` / `step` 替代 if:

```glsl
// 避免
float result;
if (x > 0) result = a; else result = b;

// 推荐
float result = mix(b, a, step(0.0, x));
```

### 2.4 内置函数

```glsl
float c = cos(x);
float s = sin(x);
float d = dot(v1, v2);     // 点积
vec3 cr = cross(v1, v2);   // 叉积
float l = length(v);
vec3 n = normalize(v);
float dist = distance(p1, p2);
vec3 reflected = reflect(v, n);
vec3 clamped = clamp(v, 0.0, 1.0);
vec3 mixed = mix(v1, v2, 0.5);  // 线性插值
vec3 textured = texture(sampler, uv);  // 纹理采样
```

## 3 · Vertex Shader

输入 vertex 数据(位置、颜色、UV),输出变换后位置。

```glsl
#version 330 core

// 输入:每个 vertex 一份
layout (location = 0) in vec3 a_position;
layout (location = 1) in vec2 a_uv;
layout (location = 2) in vec3 a_normal;

// 输出给 fragment shader
out vec2 v_uv;
out vec3 v_normal;

// Uniform:每帧 / 每个 draw call 一份
uniform mat4 u_mvp;     // Model-View-Projection matrix
uniform mat4 u_model;

void main() {
    // 必须设置 gl_Position
    gl_Position = u_mvp * vec4(a_position, 1.0);

    // 传 uv 和 normal 给 fragment
    v_uv = a_uv;
    v_normal = mat3(u_model) * a_normal;  // 旋转法线(忽略平移)
}
```

**关键概念**:

- `in` = 输入(每个 vertex 一份)
- `out` = 输出(传给下一阶段)
- `uniform` = 全局(每次 draw call 一份)
- `gl_Position` = built-in output,必须是 clip space 的 vec4

### 3.1 MVP 矩阵

把"模型空间"坐标变换到"屏幕空间",分三步:

```
Model matrix (M): 模型空间 → 世界空间
  - 平移 / 旋转 / 缩放模型到场景中的位置

View matrix (V): 世界空间 → 相机空间
  - 把场景从"世界坐标"变到"以相机为原点"的坐标

Projection matrix (P): 相机空间 → 裁剪空间
  - 透视除法(perspective)或正交(orthographic)
```

合并:MVP = P × V × M

```rust
// Rust 端构造 MVP(用 glam crate)
use glam::{Mat4, Vec3};

let model = Mat4::from_translation(Vec3::new(0.0, 0.0, 0.0));
let view = Mat4::look_at_rh(
    Vec3::new(0.0, 0.0, 5.0),  // 相机位置
    Vec3::new(0.0, 0.0, 0.0),  // 看向
    Vec3::new(0.0, 1.0, 0.0),  // 上方向
);
let projection = Mat4::perspective_rh_gl(
    std::f32::consts::PI / 4.0,  // 45 度 FOV
    800.0 / 600.0,                // aspect
    0.1,                          // near
    100.0,                        // far
);
let mvp = projection * view * model;
```

传到 shader:

```rust
// Rust
unsafe {
    let loc = gl.get_uniform_location(program, "u_mvp").unwrap();
    gl.uniform_matrix_4_f32_slice(Some(&loc), false, &mvp.to_cols_array());
}
```

## 4 · Fragment Shader

每个 pixel 跑一次,计算颜色。

```glsl
#version 330 core

// 从 vertex shader 传过来(经过 rasterization 插值)
in vec2 v_uv;
in vec3 v_normal;

// 输出:pixel 颜色
out vec4 frag_color;

// Uniform
uniform sampler2D u_texture;
uniform vec3 u_light_dir;
uniform vec3 u_light_color;

void main() {
    // 纹理采样
    vec4 tex_color = texture(u_texture, v_uv);

    // Lambert 漫反射
    vec3 normal = normalize(v_normal);
    float diff = max(dot(normal, -u_light_dir), 0.0);
    vec3 diffuse = diff * u_light_color;

    // 环境光
    vec3 ambient = 0.2 * u_light_color;

    // 最终颜色
    vec3 result = (ambient + diffuse) * tex_color.rgb;
    frag_color = vec4(result, tex_color.a);
}
```

**关键概念**:

- `in` 从 vertex shader 接收(经过插值)
- `out` 输出到 framebuffer
- `texture(sampler, uv)` 采样纹理

## 5 · Attribute vs Uniform vs Varying

老 GLSL 术语(2.x),现代用 `in` / `out`,但概念一致:

| 修饰符 | 老 | 新 | 范围 |
|---|---|---|---|
| Per-vertex 输入 | `attribute` | `in` (vertex shader) | 每个 vertex 一份 |
| Per-frame 全局 | `uniform` | `uniform` | 每次 draw call 一份 |
| Vertex → Fragment 传递 | `varying` | `out` (vs) / `in` (fs) | 经过 rasterization 插值 |

### 5.1 Attribute

每个 vertex 一份。CPU 上传 VBO(Vertex Buffer Object),GPU 每次 vertex shader 调用取下一个。

```rust
// Rust 端
let vertices: [f32; 6] = [
    -0.5, -0.5,
     0.5, -0.5,
     0.0,  0.5,
];
let vbo = gl.create_buffer().unwrap();
gl.bind_buffer(glow::ARRAY_BUFFER, Some(vbo));
gl.buffer_data_u8_slice(
    glow::ARRAY_BUFFER,
    bytemuck::cast_slice(&vertices),
    glow::STATIC_DRAW,
);

// VAO
let vao = gl.create_vertex_array().unwrap();
gl.bind_vertex_array(Some(vao));
gl.enable_vertex_attrib_array(0);
gl.vertex_attrib_pointer_f32(0, 2, glow::FLOAT, false, 8, 0);
```

shader 用 `layout(location = 0) in vec2 a_position;` 接收。

### 5.2 Uniform

每次 draw call 一份,所有 vertex / fragment 共享。

```glsl
uniform mat4 u_mvp;
uniform vec3 u_light_color;
uniform sampler2D u_texture;
```

CPU 设置:

```rust
let mvp_loc = gl.get_uniform_location(program, "u_mvp").unwrap();
unsafe {
    gl.uniform_matrix_4_f32_slice(Some(&mvp_loc), false, &mvp.to_cols_array());
}
```

**Uniform location**:shader 编译时,每个 uniform 分配一个 int location。CPU 用 `get_uniform_location` 查 location,然后 set。

### 5.3 Varying

vertex shader 的 `out`,fragment shader 的 `in`。GPU 在 rasterization 时**插值**:

```glsl
// vertex shader
out vec3 v_normal;
void main() {
    v_normal = a_normal;  // 每个 vertex 一个 normal
}

// fragment shader
in vec3 v_normal;  // 插值后的 normal
```

如果 triangle 三个 vertex 的 normal 不同(平滑着色),fragment shader 拿到的是 barycentric 插值后的 normal。

## 6 · 第一个 Triangle(完整 Rust 代码)

### 6.1 Shader 源码

```glsl
// vertex shader
#version 330 core
layout (location = 0) in vec2 a_pos;
void main() {
    gl_Position = vec4(a_pos, 0.0, 1.0);
}
```

```glsl
// fragment shader
#version 330 core
out vec4 frag_color;
void main() {
    frag_color = vec4(1.0, 0.5, 0.2, 1.0);  // 橙色
}
```

### 6.2 Rust 编译 + 链接 shader

```rust
fn compile_shader(gl: &glow::Context, shader_type: u32, source: &str) -> <glow::Context as glow::HasContext>::Shader {
    let shader = unsafe { gl.create_shader(shader_type) }.unwrap();
    unsafe {
        gl.shader_source(shader, source);
        gl.compile_shader(shader);
        if !gl.get_shader_compile_status(shader) {
            panic!("Shader compile error: {}", gl.get_shader_info_log(shader));
        }
    }
    shader
}

fn create_program(gl: &glow::Context, vs_src: &str, fs_src: &str) -> <glow::Context as glow::HasContext>::Program {
    let vs = compile_shader(gl, glow::VERTEX_SHADER, vs_src);
    let fs = compile_shader(gl, glow::FRAGMENT_SHADER, fs_src);
    let program = unsafe { gl.create_program() }.unwrap();
    unsafe {
        gl.attach_shader(program, vs);
        gl.attach_shader(program, fs);
        gl.link_program(program);
        if !gl.get_program_link_status(program) {
            panic!("Link error: {}", gl.get_program_info_log(program));
        }
        gl.detach_shader(program, vs);
        gl.detach_shader(program, fs);
        gl.delete_shader(vs);
        gl.delete_shader(fs);
    }
    program
}
```

### 6.3 完整 draw call

```rust
let vertices: [f32; 6] = [-0.5, -0.5, 0.5, -0.5, 0.0, 0.5];

let vao = unsafe { gl.create_vertex_array() }.unwrap();
let vbo = unsafe { gl.create_buffer() }.unwrap();

unsafe {
    gl.bind_vertex_array(Some(vao));
    gl.bind_buffer(glow::ARRAY_BUFFER, Some(vbo));
    gl.buffer_data_u8_slice(glow::ARRAY_BUFFER, bytemuck::cast_slice(&vertices), glow::STATIC_DRAW);
    gl.enable_vertex_attrib_array(0);
    gl.vertex_attrib_pointer_f32(0, 2, glow::FLOAT, false, 8, 0);
    gl.bind_vertex_array(None);
}

// 渲染
unsafe {
    gl.use_program(Some(program));
    gl.bind_vertex_array(Some(vao));
    gl.draw_arrays(glow::TRIANGLES, 0, 3);
}
```

## 7 · 调试 Shader

### 7.1 编译错误

GL 编译 shader 失败时,`glGetShaderInfoLog` 返回错误信息:

```
ERROR: 0:5: 'a_position' : undeclared identifier
```

`0:5` = 第 0 行第 5 字符(行号是 shader 内的,不是 include header 后的)。

### 7.2 RenderDoc

`renderdoc` 工具:

- 截取一帧
- 查看每个 draw call
- 看 shader source
- 看 uniform 值
- 看 vertex 数据
- 看每个阶段(顶点变换后 / 光栅化后 / 着色后)的中间结果

```bash
sudo pacman -S renderdoc
renderdoc &  # 启动
# File → Launch Application → 选你的程序
# F11 / 点击 capture frame
```

### 7.3 Shader 输出调试

没有 printf,但可以把调试值作为颜色:

```glsl
// 检查 normal 是否正确
frag_color = vec4(v_normal * 0.5 + 0.5, 1.0);
// 把 normal 从 [-1, 1] 映射到 [0, 1] 显示
```

不同 normal 显示不同颜色,直观检查。

### 7.4 GL debug output

```rust
unsafe {
    gl.enable(glow::DEBUG_OUTPUT);
    gl.debug_message_callback(|_src, _ty, _id, sev, msg| {
        if sev != glow::DEBUG_SEVERITY_NOTIFICATION {
            eprintln!("GL: {}", msg);
        }
    });
}
```

驱动发 message 告诉你 shader 错误、性能 warning 等。

## 8 · 常见错误

### 8.1 Black screen

最常见。可能原因:

1. Shader 编译失败 → 看 info log
2. VAO 没 bind → draw 0 vertex
3. Vertex 数据错 → 看 RenderDoc
4. Uniform 没 set → 用默认 0
5. Backface culling → 试试 `gl.disable(glow::CULL_FACE)`
6. Depth test 错 → 试试 `gl.disable(glow::DEPTH_TEST)`

### 8.2 Vertex 数据混乱

```rust
gl.vertex_attrib_pointer_f32(0, 2, glow::FLOAT, false, 8, 0);
//                                              ^ stride ^ offset
```

stride = 一个 vertex 的字节数。如果 vertex 是 `(x, y)`,stride = 8。如果是 `(x, y, u, v)`,stride = 16。

offset = 这个 attribute 在 vertex 内的偏移。`(x, y, u, v)` 中 uv 的 offset = 8。

### 8.3 矩阵转置

OpenGL 期望 column-major matrix。Rust 的 `glam::Mat4::to_cols_array()` 返回 column-major。如果用 `to_cols_array_2d()` 或行主序,结果错。

```rust
// 正确
gl.uniform_matrix_4_f32_slice(Some(&loc), false, &mvp.to_cols_array());
//                                              ^ transpose=false,已经是 column-major
```

## 9 · 关联 Day

- [day235](../day235.md) OpenGL context 创建
- [day237](../day237.md) 用 GL 显示图像
- [day238](../day238.md) 屏幕坐标
- [day239](../day239.md) 通过 GL 渲染游戏

## 10 · 延伸阅读

- LearnOpenGL Shaders:https://learnopengl.com/Getting-started/Shaders
- GLSL 规范:https://www.khronos.org/opengl/wiki/OpenGL_Shading_Language
- The Book of Shaders:https://thebookofshaders.com/
- glam crate:https://docs.rs/glam
