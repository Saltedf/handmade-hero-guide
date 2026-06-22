# Framebuffer Objects 与 Render-to-Texture

> Day 235 创建 GL context 默认渲染到屏幕。现代 OpenGL 支持渲染到**自定义 framebuffer**(texture / depth buffer)。这个 deep-dive 讲 FBO(Frame Buffer Object)和 render-to-texture,以及后处理入门。

## 1 · 为什么需要 FBO

默认 framebuffer = 屏幕窗口。FBO 允许你创建**离屏 framebuffer**——渲染到 texture 而不是屏幕。

用途:

- **后处理(post-processing)**:先渲染场景到 texture,然后用 shader 处理(bloom、色调映射、SSAO)
- **Shadow mapping**:从光源视角渲染深度到 texture
- **Mirror / portal**:把镜像场景渲染到 texture
- **Minimap**:小窗口内容是从顶视角渲染的 texture
- **MSAA resolve**:多采样 framebuffer 先渲染,再 resolve 到普通 framebuffer
- **Dynamic cube map**:反射用动态 cube texture

casey 在 HH 后期(Phase 6-7)大量用 FBO 做光照和后处理。

## 2 · FBO 概念

### 2.1 Framebuffer 组成

完整 framebuffer 需要:

- **Color attachment**:颜色 texture(可多个,MRT)
- **Depth attachment**:深度 buffer(texture 或 renderbuffer)
- **Stencil attachment**(可选)

texture 和 renderbuffer 区别:

- **Texture**:可以采样(`texture(sampler, uv)`),GPU 优化读
- **Renderbuffer**:不能直接采样,但 GPU 优化写

通常 color / depth 用 texture(便于采样),纯 depth / stencil 用 renderbuffer(快)。

### 2.2 默认 FBO

每个 GL window 有默认 framebuffer(`fbo = 0`),渲染到屏幕。

```rust
unsafe { gl.bind_framebuffer(glow::FRAMEBUFFER, None); }  // 用默认
```

### 2.3 自定义 FBO

```rust
let fbo = unsafe { gl.create_framebuffer() }.unwrap();
unsafe { gl.bind_framebuffer(glow::FRAMEBUFFER, Some(fbo)); }

// 绑 color texture
unsafe {
    gl.framebuffer_texture_2d(
        glow::FRAMEBUFFER,
        glow::COLOR_ATTACHMENT0,
        glow::TEXTURE_2D,
        Some(color_texture),
        0,  // mipmap level
    );
}

// 绑 depth texture
unsafe {
    gl.framebuffer_texture_2d(
        glow::FRAMEBUFFER,
        glow::DEPTH_ATTACHMENT,
        glow::TEXTURE_2D,
        Some(depth_texture),
        0,
    );
}

// 检查完整性
let status = unsafe { gl.check_framebuffer_status(glow::FRAMEBUFFER) };
if status != glow::FRAMEBUFFER_COMPLETE {
    panic!("FBO incomplete: {}", status);
}
```

### 2.4 渲染到 FBO

```rust
unsafe {
    gl.bind_framebuffer(glow::FRAMEBUFFER, Some(fbo));
    gl.viewport(0, 0, fb_width, fb_height);  // 必须 set viewport

    // 渲染场景
    gl.clear_color(0.0, 0.0, 0.0, 1.0);
    gl.clear(glow::COLOR_BUFFER_BIT | glow::DEPTH_BUFFER_BIT);
    draw_scene(gl);
}
```

之后 fbo 的 color_texture 就是渲染结果。

### 2.5 用 FBO 的 texture 渲染到屏幕

post-processing 的"blit"步骤:

```rust
unsafe {
    gl.bind_framebuffer(glow::FRAMEBUFFER, None);  // 切回屏幕
    gl.viewport(0, 0, screen_width, screen_height);

    // 用一个全屏 quad,texture 设为 fbo 的 color_texture
    gl.use_program(Some(postprocess_program));
    gl.active_texture(glow::TEXTURE0);
    gl.bind_texture(glow::TEXTURE_2D, Some(color_texture));
    gl.uniform_1_i32(Some(&postprocess_tex_loc), 0);

    draw_fullscreen_quad(gl);
}
```

postprocess shader 可以做任何效果:bloom、blur、tone mapping、color grading。

## 3 · 后处理示例:灰度

fragment shader:

```glsl
#version 330 core
in vec2 v_uv;
out vec4 frag_color;
uniform sampler2D u_scene;

void main() {
    vec3 color = texture(u_scene, v_uv).rgb;
    float gray = dot(color, vec3(0.299, 0.587, 0.114));  // 亮度公式
    frag_color = vec4(vec3(gray), 1.0);
}
```

整个场景变成黑白。

## 4 · 后处理示例:Bloom

Bloom = 亮的部分发光。步骤:

1. 渲染场景到 HDR color_texture
2. 提取亮度 > threshold 的部分,生成 bright_texture
3. 对 bright_texture 做高斯模糊(几次 blur)
4. 把 blur 后的 bright 加到原 scene 上

需要多个 FBO 和多个 pass:

```
[scene FBO] → [threshold pass] → [bright FBO]
                                ↓
                          [horizontal blur]
                                ↓
                          [vertical blur] (重复多次)
                                ↓
                          [final composited FBO] → 屏幕
```

每个 pass 渲染到不同 FBO,前一个 FBO 的 texture 是下一个 pass 的输入。

## 5 · MSAA

Multi-Sample Anti-Aliasing(MSAA)减少边缘锯齿。每个 pixel 采样多次(2 / 4 / 8 / 16),取平均。

实现:用 multi-sample texture/renderbuffer。

```rust
// 创建 MSAA color renderbuffer
let color_rb = unsafe { gl.create_renderbuffer() }.unwrap();
unsafe {
    gl.bind_renderbuffer(glow::RENDERBUFFER, Some(color_rb));
    gl.renderbuffer_storage_multisample(glow::RENDERBUFFER, 4, glow::RGBA8, width, height);
}

// 创建 MSAA FBO
let msaa_fbo = unsafe { gl.create_framebuffer() }.unwrap();
unsafe {
    gl.bind_framebuffer(glow::FRAMEBUFFER, Some(msaa_fbo));
    gl.framebuffer_renderbuffer(glow::FRAMEBUFFER, glow::COLOR_ATTACHMENT0, glow::RENDERBUFFER, Some(color_rb));
}

// 渲染到 MSAA FBO...

// Resolve 到 non-MSAA FBO(可采样)
unsafe {
    gl.bind_framebuffer(glow::READ_FRAMEBUFFER, Some(msaa_fbo));
    gl.bind_framebuffer(glow::DRAW_FRAMEBUFFER, Some(resolve_fbo));
    gl.blit_framebuffer(0, 0, w, h, 0, 0, w, h, glow::COLOR_BUFFER_BIT, glow::NEAREST);
}
```

resolve 后的 texture 可用于 post-processing。

## 6 · Ping-Pong FBO

多次模糊需要多个中间 FBO。**Ping-pong**:两个 FBO 交替使用。

```
horizontal blur: fbo_A → fbo_B
vertical blur:   fbo_B → fbo_A
horizontal blur: fbo_A → fbo_B
...
```

避免每个 pass 都新建 FBO。

```rust
struct PingPong {
    fbos: [FrameBuffer; 2],
    current: usize,
}

impl PingPong {
    fn swap(&mut self) { self.current = 1 - self.current; }

    fn read(&self) -> &FrameBuffer { &self.fbos[self.current] }
    fn write(&mut self) -> &mut FrameBuffer { &mut self.fbos[1 - self.current] }
}
```

## 7 · 完整 FBO Wrapper

```rust
pub struct Framebuffer {
    pub id: <glow::Context as glow::HasContext>::Framebuffer,
    pub color_texture: <glow::Context as glow::HasContext>::Texture,
    pub depth_texture: <glow::Context as glow::HasContext>::Texture,
    pub width: i32,
    pub height: i32,
}

impl Framebuffer {
    pub fn new(gl: &glow::Context, width: i32, height: i32) -> Self {
        let id = unsafe { gl.create_framebuffer() }.unwrap();
        unsafe { gl.bind_framebuffer(glow::FRAMEBUFFER, Some(id)); }

        // Color texture
        let color_texture = unsafe { gl.create_texture() }.unwrap();
        unsafe {
            gl.bind_texture(glow::TEXTURE_2D, Some(color_texture));
            gl.tex_image_2d(
                glow::TEXTURE_2D, 0, glow::RGBA8 as i32,
                width, height, 0,
                glow::RGBA, glow::UNSIGNED_BYTE, None,
            );
            gl.tex_parameter_i32(glow::TEXTURE_2D, glow::TEXTURE_MIN_FILTER, glow::LINEAR as i32);
            gl.tex_parameter_i32(glow::TEXTURE_2D, glow::TEXTURE_MAG_FILTER, glow::LINEAR as i32);
            gl.framebuffer_texture_2d(
                glow::FRAMEBUFFER, glow::COLOR_ATTACHMENT0,
                glow::TEXTURE_2D, Some(color_texture), 0,
            );
        }

        // Depth texture
        let depth_texture = unsafe { gl.create_texture() }.unwrap();
        unsafe {
            gl.bind_texture(glow::TEXTURE_2D, Some(depth_texture));
            gl.tex_image_2d(
                glow::TEXTURE_2D, 0, glow::DEPTH_COMPONENT24 as i32,
                width, height, 0,
                glow::DEPTH_COMPONENT, glow::FLOAT, None,
            );
            gl.framebuffer_texture_2d(
                glow::FRAMEBUFFER, glow::DEPTH_ATTACHMENT,
                glow::TEXTURE_2D, Some(depth_texture), 0,
            );
        }

        let status = unsafe { gl.check_framebuffer_status(glow::FRAMEBUFFER) };
        assert_eq!(status, glow::FRAMEBUFFER_COMPLETE, "FBO incomplete");

        unsafe { gl.bind_framebuffer(glow::FRAMEBUFFER, None); }

        Self { id, color_texture, depth_texture, width, height }
    }

    pub fn bind(&self, gl: &glow::Context) {
        unsafe {
            gl.bind_framebuffer(glow::FRAMEBUFFER, Some(self.id));
            gl.viewport(0, 0, self.width, self.height);
        }
    }

    pub fn unbind(gl: &glow::Context) {
        unsafe { gl.bind_framebuffer(glow::FRAMEBUFFER, None); }
    }

    pub fn delete(self, gl: &glow::Context) {
        unsafe {
            gl.delete_framebuffer(self.id);
            gl.delete_texture(self.color_texture);
            gl.delete_texture(self.depth_texture);
        }
    }
}
```

## 8 · 常见错误

### 8.1 Black texture

- FBO incomplete:check `glCheckFramebufferStatus`
- Viewport 没 set 到 FBO 大小
- Shader 没 bind texture
- Texture 单元错(active texture + uniform sampler 必须 match)

### 8.2 撕裂 / 错位

- Viewport 不匹配 FBO 大小
- Texture wrap mode 错(CLAMP vs REPEAT)
- UV 坐标系错(OpenGL 左下原点 vs 屏幕左上原点)

### 8.3 Depth test 失效

- FBO 没 depth attachment
- Depth test 没 enable
- Depth func 错(`gl.LEQUAL` 而非 `gl.LESS`)

### 8.4 性能问题

- FBO 大小过大(4K FBO + bloom 多 pass,慢)
- 不必要的 resolve(MSAA resolve 慢)
- Format 错(float texture 比 8-bit 慢 4 倍)

## 9 · Rust 生态

- `glow`:原始 GL wrapper,自己管 FBO
- `wgpu`:更高级,`TextureView` + `RenderPass` 抽象 FBO
- `rend3` / `bevy_render`:引擎级别

参考 crate:`glium`(deprecated 但参考好)、`glfw`(window + GL)。

## 10 · 关联 Day

- [day235](../day235.md) OpenGL context 创建
- [day239](../day239.md) 通过 GL 渲染游戏
- [day241](../day241.md) VSync + sRGB(渲染管线用 sRGB FBO)
- [day243](../day243.md) 异步纹理下载(从 FBO 读回 CPU)

## 11 · 延伸阅读

- LearnOpenGL Framebuffers:https://learnopengl.com/Advanced-OpenGL/Framebuffers
- OpenGL Wiki FBO:https://www.khronos.org/opengl/wiki/Framebuffer_Object
- Bloom tutorial:https://learnopengl.com/Advanced-Lighting/Bloom
