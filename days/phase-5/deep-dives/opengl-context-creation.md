# OpenGL Context Creation 深入

> Day 235 把 OpenGL 接到窗口。这个 deep-dive 把 context creation 讲透:glutin/winit 集成、context attribute、GL vs GLES、glow crate 内部原理。

## 1 · OpenGL Context 是什么

GL context 是 GPU 状态的容器。包含:

- 当前 shader 程序(`glUseProgram`)
- 当前绑定的 buffer / texture(`glBindBuffer` / `glBindTexture`)
- 当前 VAO(Vertex Array Object)
- viewport / scissor 设置
- depth / blend / stencil 状态
- error state
- 当前帧的 framebuffer

**线程局部**:每个线程一次只能有一个 current context。`make_current` 切换。

**资源持有**:texture / buffer 等 GL 资源挂在 context 上,context 销毁时资源自动释放(除非用 shared context)。

## 2 · 创建 Context 的步骤

### 2.1 平台原生 API

每个 OS 有自己的 GL binding API:

| OS | API | 函数 |
|---|---|---|
| Windows | WGL | `wglCreateContext`, `wglMakeCurrent` |
| Linux X11 | GLX | `glXCreateContext`, `glXMakeCurrent` |
| Linux Wayland | EGL | `eglCreateContext`, `eglMakeCurrent` |
| macOS | CGL | `CGLCreateContext` |
| Android / iOS | EGL | 同 Wayland |

API 名字不同,概念一致。

### 2.2 Win32 的"鸡和蛋"问题

WGL 选 pixel format 的旧 API(`ChoosePixelFormat`)只支持老格式。要现代格式(sRGB、MSAA、float)必须用扩展 API `wglChoosePixelFormatARB`。但**查扩展需要 context**。

解决:

1. 用旧 API 创建 dummy window + dummy context
2. 用 dummy 查 `wglGetExtensionsStringARB`,看是否支持 `wglChoosePixelFormatARB`
3. 如果支持,用新 API 选现代 pixel format
4. 销毁 dummy
5. 用现代 pixel format 创建真 window + 真 context

Linux 没这问题(EGL 是现代 API)。

### 2.3 glutin 抽象

glutin crate 跨平台封装:

```rust
let gl_context = ContextBuilder::new()
    .with_gl(GlRequest::Specific(Api::OpenGl, (3, 3)))
    .with_gl_profile(GlProfile::Core)
    .with_gl_debug_flag(true)
    .with_vsync(true)
    .build_windowed(window, &event_loop)?;
```

内部按平台调对应 API。`with_gl` 指定版本,`with_gl_profile` 指 core(现代)或 compatibility(老)。

## 3 · Context Attributes

### 3.1 GL 版本

```rust
.with_gl(GlRequest::Specific(Api::OpenGl, (3, 3)))  // OpenGL 3.3
.with_gl(GlRequest::Specific(Api::OpenGl, (4, 6)))  // OpenGL 4.6(最新)
.with_gl(GlRequest::Specific(Api::OpenGlEs, (3, 0)))  // OpenGL ES 3.0
```

版本选择:

- **3.3**:跨平台兼容性最好(Linux / macOS 都支持)
- **4.0+**:tessellation shader、indirect draw
- **4.6**:最新,但 macOS 不支持

Casey 选 3.3,跨平台稳。

### 3.2 Profile

```rust
.with_gl_profile(GlProfile::Core)         // 现代,无 fixed function
.with_gl_profile(GlProfile::Compatibility) // 老,支持 glBegin/glEnd
```

Core 强制现代风格(VAO + VBO + GLSL),Compatibility 容错老代码。新项目用 Core。

### 3.3 Forward compatible

```rust
.with_gl(GlProfile::Core)
// 隐含 forward compatible:删除 3.x deprecated 的 API
```

macOS 必须用 core profile + forward compatible,否则 context 创建失败。

### 3.4 Debug flag

```rust
.with_gl_debug_flag(true)
```

开启 GL debug output。驱动会发 message 告诉你:

- shader 编译错误
- 性能 warning(没用 VAO)
- error(无效枚举)

```
GL_DEBUG_MESSAGE: Shader compile error in vertex shader:
0:5(2): error: `position' undeclared
```

开发时强烈建议开。

### 3.5 VSync

```rust
.with_vsync(true)
```

SwapBuffers 等显示器刷新。避免撕裂,限制 FPS = 显示器刷新率(60/120/144)。

## 4 · Pixel Format

Pixel format 决定 framebuffer 的:

- 颜色位深(R8G8B8 / R10G10B10 / R16G16B16)
- alpha 位深
- depth 位深(0 / 16 / 24 / 32)
- stencil 位深
- 双缓冲 / 三缓冲
- sRGB(支持 sRGB framebuffer)
- MSAA(多重采样抗锯齿:0 / 2 / 4 / 8 / 16)

### 4.1 选 format 的 tradeoff

| 需求 | 选择 |
|---|---|
| 3D 游戏 | depth 24, MSAA 4x, sRGB on |
| 2D 游戏 | depth 0, MSAA 0 |
| HDR 渲染 | R16G16B16A16 float |
| VR | 高 MSAA(8+), 高刷新率 |

### 4.2 Linux 选 format

```bash
glxinfo | grep "preferred visual"
# 输出类似: preferred visual 0x21
```

`glxinfo` 列出所有可用 visual(每个 visual 是一种 pixel format)。glutin 内部枚举选最佳。

## 5 · GL vs GLES

### 5.1 区别

**OpenGL**(桌面):full feature, 4.6
**OpenGL ES**(embedded):mobile / IoT 子集,3.2

GLES 删除了:

- fixed function pipeline(GLES 2+ 必须 shader)
- glBegin / glEnd(已经在 GL core profile 删了)
- 一些复杂 extension

GLES 增加了:

- 部分 mobile-specific extension
- 更严格的资源限制

### 5.2 选择

- **桌面 PC**:OpenGL 3.3+
- **Mobile**:OpenGL ES 3.0+
- **Web**(WebGL):GLES 2.0 / 3.0
- **Web**(WebGPU):不基于 GL,是独立 API

glutin 能创 GLES context:

```rust
.with_gl(GlRequest::Specific(Api::OpenGlEs, (3, 0)))
```

### 5.3 WebGL 注意

WebGL 1 = GLES 2.0,WebGL 2 = GLES 3.0。如果代码要编译到 Web 用 WebGL,必须用 GLES API。

glow crate 抽象 GL / GLES / WebGL 差异:

```rust
let gl = glow::Context::from_loader_function(|s| context.get_proc_address(s));
// 同一套 API,glow 内部根据 context 类型分发
```

## 6 · glow crate 内部原理

### 6.1 函数指针加载

GL API 是 runtime 查的(不是编译时链接)。glow 包装:

```rust
pub struct Context {
    // 内部存储函数指针
    gl_clear_color: Option<PFNGLCLEARCOLOR>,
    gl_draw_arrays: Option<PFNGLDRAWARRAYS>,
    // ... 几百个函数
}

impl Context {
    pub unsafe fn clear_color(&self, r: f32, g: f32, b: f32, a: f32) {
        let f = self.gl_clear_color.expect("glClearColor not loaded");
        f(r, g, b, a);
    }
}
```

### 6.2 跨后端

glow 支持:

- Desktop GL(`glow::Context::from_loader_function`)
- GLES(同上)
- WebGL(`glow::Context::from_webgl1_context` / `from_webgl2_context`)

API 一致,后端不同。这是 glow 价值:**一套代码跑所有 GL 变种**。

### 6.3 类型安全

C GL 是无类型的 `void*` + macro。glow 提供 Rust 类型:

```rust
// C
GLuint vao;
glGenVertexArrays(1, &vao);

// glow
let vao = gl.create_vertex_array().unwrap();
// vao 是 glow::VertexArray,不是 raw u32
// 销毁时 gl.delete_vertex_array(vao),防止传错类型
```

newtype 包装避免类型混淆。

## 7 · 完整 Rust 创建 context 流程

```rust
use winit::event_loop::EventLoop;
use winit::window::WindowBuilder;
use glutin::context::{ContextApi, ContextAttributes, NotCurrentGlContext, Version};
use glutin::config::ConfigTemplateBuilder;
use glutin::display::GetGlDisplay;
use glutin::prelude::*;
use glutin::surface::{Surface, SurfaceAttributesBuilder, WindowSurface};
use raw_window_handle::HasRawWindowHandle;

fn main() {
    let event_loop = EventLoop::new();

    // 1. 创建窗口(不显示)
    let window = WindowBuilder::new()
        .with_title("GL Window")
        .with_transparent(true)
        .build(&event_loop)
        .unwrap();

    // 2. 创建 GL display
    let template = ConfigTemplateBuilder::default()
        .with_alpha_size(8)
        .with_transparency(true)
        .build();
    let display = unsafe {
        glutin::display::Display::new(window.raw_display_handle().unwrap(), template)
    }.unwrap();

    // 3. 选 config(枚举所有,选最佳)
    let config = display.find_configs()
        .unwrap()
        .next()
        .unwrap();

    // 4. 创建 context
    let context_attributes = ContextAttributes::builder()
        .with_context_api(ContextApi::OpenGl(Some(Version::new(3, 3))))
        .build(Some(window.raw_window_handle().unwrap()));
    let not_current = unsafe {
        display.create_context(&config, &context_attributes).unwrap()
    };

    // 5. 创建 surface
    let attrs = SurfaceAttributesBuilder::<WindowSurface>::new()
        .with_srgb(Some(true))
        .build(window.raw_window_handle().unwrap(), 800, 600);
    let surface = unsafe { config.display().create_window_surface(&config, &attrs) }.unwrap();

    // 6. Make current
    let current = not_current.make_current(&surface).unwrap();

    // 7. 加载 GL 函数
    let gl = glow::Context::from_loader_function(|s| {
        display.get_proc_address(s) as *const _
    });

    // 8. 设置 VSync
    surface.set_swap_interval(&current, glutin::surface::SwapInterval::Wait(1)).ok();

    // 9. 测试渲染
    unsafe {
        gl.clear_color(0.2, 0.3, 0.3, 1.0);
        gl.clear(glow::COLOR_BUFFER_BIT);
    }
    surface.swap_buffers(&current).unwrap();

    println!("OpenGL context created successfully");
}
```

注:glutin 0.31+ API 较繁琐,生产代码推荐参考 `glutin_examples` 官方仓库。

## 8 · 常见问题

### 8.1 创建失败:GLX_BAD_SCREEN

```
Error: GLX_BAD_SCREEN
```

原因:无 GPU 驱动,或驱动配置错。Linux 检查:

```bash
glxinfo | grep "OpenGL renderer"
# 如果显示 llvmpipe,是软件渲染
# 装厂商驱动:
# AMD: sudo pacman -S mesa vulkan-radeon
# NVIDIA: sudo pacman -S nvidia
# Intel: sudo pacman -S mesa
```

### 8.2 SwapBuffers 卡顿

VSync 开了 + 帧时间 < 16ms,SwapBuffers 等到 16ms 才返回。如果想跑更高 FPS:

```rust
surface.set_swap_interval(&current, SwapInterval::DontWait).ok();
```

但可能撕裂。

### 8.3 Function pointer null

```
panic: glClearColor not loaded
```

原因:context 没 make_current,或函数名错(glow 内部用字符串查)。检查:

```rust
// 必须先 make_current 再创建 glow::Context
let current = not_current.make_current(&surface).unwrap();
let gl = glow::Context::from_loader_function(|s| {
    current.get_proc_address(s) as *const _
});
```

### 8.4 macOS black screen

macOS 默认 layer 不显示 GL。需要:

```rust
#[cfg(target_os = "macos")]
{
    use raw_window_handle::HasRawWindowHandle;
    // ... 设置 NSOpenGLView layer
}
```

或用 `winit` + `glutin` 的 macOS 适配。

## 9 · 关联 Day

- [day235](../day235.md) OpenGL 初始化(主日)
- [day242](../day242.md) context escalation
- [day245](../day245.md) pixel format

## 10 · 延伸阅读

- LearnOpenGL Context Creation:https://learnopengl.com/Getting-started/Creating-a-window
- glutin docs:https://docs.rs/glutin
- glow docs:https://docs.rs/glow
- WGL pixel format:https://www.khronos.org/registry/OpenGL/extensions/ARB/WGL_ARB_pixel_format.txt
