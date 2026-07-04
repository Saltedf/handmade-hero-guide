
# Win32 到 winit:API 映射与抽象边界

> Casey 在 HH 用 Win32 API。你跟做用 Rust + winit。看似只是"换库",但 winit 抽象了什么、没抽象什么、Linux 和 Windows 的本质差异在哪——这些细节决定你能不能调试跨平台问题。本文列常见 Win32 API 到 winit 等价物的映射,讲 winit 的抽象边界,帮你在 KDE on Wayland 上跟做 HH 时知道问题在哪。

## 0 · 为什么需要这个映射

你跟 Casey 视频,他说:

> "Call `CreateWindowEx`, pass `WS_OVERLAPPEDWINDOW`, then `ShowWindow(hwnd, SW_SHOW)`..."

你 winit 怎么写?

```rust
let window = event_loop.create_window(
    Window::default_attributes()
        .with_title("Hello")
        .with_inner_size(LogicalSize::new(800, 600))
).unwrap();
```

看起来一一对应。但细节差异多——Casey 假设 Windows 行为,winit 假设跨平台。理解这些差异让你:

- 调试时知道问题在哪层(winit / Wayland / 内核)
- 看 Casey 代码时知道"winit 帮我做了这步"
- 必要时绕过 winit(用 `winit::platform::*` 扩展)

## 1 · 窗口创建

### Win32

```c
WNDCLASSEX wc = {0};
wc.cbSize = sizeof(wc);
wc.lpfnWndProc = MyWindowProc;  // 回调
wc.lpszClassName = "MyWindowClass";
wc.hInstance = hInstance;
RegisterClassEx(&wc);

HWND hwnd = CreateWindowEx(
    0,
    "MyWindowClass",
    "Title",
    WS_OVERLAPPEDWINDOW,  // 标题栏 + 边框 + 最大化按钮
    CW_USEDEFAULT, CW_USEDEFAULT,
    800, 600,
    NULL, NULL, hInstance, NULL
);
ShowWindow(hwnd, SW_SHOW);
```

约 30 行,涉及窗口类注册 + 创建 + 显示。

### winit

```rust
use winit::window::Window;
use winit::dpi::LogicalSize;

let window = event_loop.create_window(
    Window::default_attributes()
        .with_title("Title")
        .with_inner_size(LogicalSize::new(800, 600))
        .with_resizable(true)
).unwrap();
```

5 行。winit 帮你:

- 注册窗口类(Linux 上不需要,Wayland 没这概念)
- 创建窗口
- 显示(自动)

### 映射

| Win32 | winit |
|---|---|
| `RegisterClassEx` | (不需要,winit 内部处理) |
| `CreateWindowEx` | `event_loop.create_window(attributes)` |
| `WS_OVERLAPPEDWINDOW` | `Window::default_attributes()` 默认带装饰 |
| `WS_POPUP` | `.with_decorations(false)` |
| `ShowWindow(hwnd, SW_SHOW)` | (创建时自动 show) |
| `DestroyWindow(hwnd)` | (drop Window 自动) |

### 抽象边界

winit **抽象了**:

- 窗口类概念(Linux 没有)
- WindowProc 回调(改用 event loop)
- WS_* 标志(改用 builder 方法)
- hwnd / X11 window / Wayland surface 的具体类型

winit **没抽象**:

- 平台特定细节(DPI 处理、Wayland 协议)
- 全屏模式差异(X11 vs Wayland)
- 输入法(IME)集成

要平台特定访问,用 `winit::platform::*`:

```rust
use winit::platform::unix::*;  // Linux 特定

// 拿 X11 窗口句柄(只 X11,Wayland 不支持)
#[cfg(x11_platform)]
let x11_handle = window.xlib_window().unwrap();
```

## 2 · 消息循环(Message Loop)

### Win32

```c
MSG msg;
while (GetMessage(&msg, NULL, 0, 0)) {
    TranslateMessage(&msg);
    DispatchMessage(&msg);
}
```

主动从队列拉消息,翻译,派发给 WindowProc。

### winit

```rust
event_loop.run_app(&mut app).unwrap();

// app 实现 ApplicationHandler
impl ApplicationHandler for App {
    fn window_event(&mut self, event_loop, window_id, event) {
        // event 是 winit::event::WindowEvent
        match event {
            WindowEvent::CloseRequested => event_loop.exit(),
            WindowEvent::KeyboardInput { event, .. } => { /* 处理键盘 */ }
            WindowEvent::RedrawRequested => { /* 画 */ }
            _ => {}
        }
    }
}
```

winit 调用你的 handler——**回调式**,你不用拉消息。

### 映射

| Win32 | winit |
|---|---|
| `GetMessage` 循环 | `event_loop.run_app(handler)` |
| `TranslateMessage` | (winit 内部) |
| `DispatchMessage` | (winit 调你的 handler) |
| WindowProc | `ApplicationHandler::window_event` |
| `WM_PAINT` | `WindowEvent::RedrawRequested` |
| `WM_KEYDOWN` | `WindowEvent::KeyboardInput` (state: Pressed) |
| `WM_KEYUP` | `WindowEvent::KeyboardInput` (state: Released) |
| `WM_CLOSE` | `WindowEvent::CloseRequested` |
| `WM_SIZE` | `WindowEvent::Resized` |
| `WM_MOUSEMOVE` | `WindowEvent::CursorMoved` |
| `WM_LBUTTONDOWN` | `WindowEvent::MouseInput` (state: Pressed, button: Left) |

### 抽象边界

winit **抽象了**:

- "拉消息" vs "推消息"——winit 用回调,跨平台一致
- 消息类型——winit event 是 enum,所有平台一致

winit **没抽象**:

- 事件时序(Wayland 的事件流和 X11 不同)
- 多窗口事件分发(winit 给你 WindowId,但不同平台可能乱序)

## 3 · 双缓冲与显示

### Win32(GDI + StretchDIBits)

```c
HDC hdc = GetDC(hwnd);

BITMAPINFO bmi = {0};
bmi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
bmi.bmiHeader.biWidth = WIDTH;
bmi.bmiHeader.biHeight = -HEIGHT;  // 负值 = top-down
bmi.bmiHeader.biPlanes = 1;
bmi.bmiHeader.biBitCount = 32;
bmi.bmiHeader.biCompression = BI_RGB;

StretchDIBits(hdc,
    0, 0, WIDTH, HEIGHT,
    0, 0, WIDTH, HEIGHT,
    back_buffer,
    &bmi,
    DIB_RGB_COLORS,
    SRCCOPY);

ReleaseDC(hwnd, hdc);
```

### winit + softbuffer

```rust
use softbuffer::Surface;

let context = softbuffer::Context::new(window.clone()).unwrap();
let mut surface = Surface::new(&context, window.clone()).unwrap();
surface.resize(NonZeroU32::new(WIDTH).unwrap(), NonZeroU32::new(HEIGHT).unwrap()).unwrap();

// 每帧
let mut buffer = surface.buffer_mut().unwrap();
for pixel in buffer.iter_mut() {
    *pixel = 0xFF_00_FF_00;  // 绿色
}
buffer.present().unwrap();
```

### 映射

| Win32 | winit + softbuffer |
|---|---|
| `GetDC(hwnd)` | (softbuffer 内部) |
| `BITMAPINFO` 设置 | (softbuffer 内部) |
| `StretchDIBits` | `surface.buffer_mut()` + `present()` |
| GDI 像素格式(ARGB) | softbuffer 像素格式(平台依赖) |
| `SwapBuffers`(OpenGL) | (softbuffer 自动) |

### 像素格式陷阱

Win32 GDI 默认 ARGB(0xAARRGGBB)。softbuffer 在 Linux 上**可能是不同顺序**——XRGB32 / XBGR8 等。

测试方法:

```rust
// 画纯红
buffer[0] = 0xFFFF0000;  // ARGB 红
// 看屏幕:红就是 ARGB,蓝就是 BGRA
```

softbuffer 文档:

```rust
// 用 Surface::buffer_mut 返回的 slice 的格式
// 通常在 Linux/Wayland 上是 XRGB32(0x00RRGGBB,alpha 被忽略)
```

跨平台写法:**用 softbuffer 提供的颜色构造 API**,不硬编码 0xAARRGGB。

## 4 · 键盘输入

### Win32

```c
// 在 WindowProc
case WM_KEYDOWN: {
    WPARAM vk = wParam;  // VK_ESCAPE / VK_SPACE / 'A'
    // 设置 keys[vk] = true
    break;
}
case WM_KEYUP: {
    keys[wParam] = false;
    break;
}

// 或者用 GetAsyncKeyState
bool is_down = GetAsyncKeyState(VK_SPACE) & 0x8000;
```

### winit

```rust
fn window_event(&mut self, _, _, event: WindowEvent) {
    match event {
        WindowEvent::KeyboardInput { event: KeyEvent {
            physical_key: PhysicalKey::Code(code),
            state,
            ..
        }, .. } => {
            match state {
                ElementState::Pressed => self.keys.insert(code),
                ElementState::Released => self.keys.remove(&code),
            };
        }
        _ => {}
    }
}
```

### 映射

| Win32 | winit |
|---|---|
| `WM_KEYDOWN` | `KeyboardInput` state: Pressed |
| `WM_KEYUP` | `KeyboardInput` state: Released |
| `WPARAM` VK_xxx | `KeyCode` enum |
| `GetAsyncKeyState` | 查自己的 `HashSet<KeyCode>` |
| VK_SHIFT / VK_CONTROL | `KeyCode::ShiftLeft` / `ControlLeft` |
| 字符输入(WM_CHAR) | `WindowEvent::Ime` 或 `KeyEvent::text` |

### 物理键 vs 逻辑键

**重要差别**:

- **物理键(scancode)**:键盘上的物理位置,布局无关。QWERTY 上的 'Q' 在 Dvorak 上也是同一物理键
- **逻辑键(virtual key)**:经过布局转换的字符。QWERTY 'Q' 在 Dvorak 上可能变成 ' character

游戏**必须用物理键**——WASD 在所有布局下位置一样。

Win32:`wParam` 是 virtual key,要拿 scancode 用 `MapVirtualKey` 或读 `LPARAM` 的 bits 16-23。

winit:

```rust
KeyEvent {
    physical_key: PhysicalKey::Code(KeyCode::KeyQ),  // ← 物理键(用这个)
    logical_key: Key::Character("q"),                 // ← 逻辑(布局相关)
    ..
}
```

## 5 · 手柄输入

### Win32(XInput)

```c
#include <xinput.h>

DWORD result;
XINPUT_STATE state;
ZeroMemory(&state, sizeof(state));
result = XInputGetState(0, &state);  // controller 0

if (result == ERROR_SUCCESS) {
    bool a_pressed = state.Gamepad.wButtons & XINPUT_GAMEPAD_A;
    SHORT left_x = state.Gamepad.sThumbLX;  // -32768 to 32767
    BYTE left_trigger = state.Gamepad.bLeftTrigger;  // 0-255
}
```

### winit + gilrs

```rust
let mut gilrs = gilrs::Gilrs::new().unwrap();

while let Some(_event) = gilrs.next_event() {}

for (id, gamepad) in gilrs.gamepads() {
    let a_pressed = gamepad.is_pressed(gilrs::Button::South);
    let left_stick = gamepad.state().left_stick();  // Vec2, -1 to 1
    let left_trigger = gamepad.value(gilrs::Axis::LeftZ);  // 0 to 1
}
```

### 映射

| Win32 (XInput) | gilrs |
|---|---|
| `XInputGetState` | `gilrs.gamepads()` 迭代 |
| `wButtons & XINPUT_GAMEPAD_A` | `is_pressed(Button::South)` |
| `sThumbLX` (-32k..32k) | `left_stick().x` (-1..1) |
| `bLeftTrigger` (0..255) | `value(Axis::LeftZ)` (0..1) |
| 仅 Xbox 兼容 | 所有(SDL 标准)手柄 |

### 按钮命名差异

Win32 / Xbox:A / B / X / Y。PlayStation:Cross / Circle / Square / Triangle。Switch:A / B / X / Y(但布局不同——Switch A 在右,Xbox A 在下)。

**SDL 标准**(gilrs 用):

| SDL | Xbox | PS | Switch |
|---|---|---|---|
| South | A | Cross | B |
| East | B | Circle | A |
| West | X | Square | Y |
| North | Y | Triangle | X |

游戏代码用 SDL 标准(gilrs 默认),自动适配所有手柄。

## 6 · 音频

### Win32(DirectSound)

```c
LPDIRECTSOUND direct_sound;
DirectSoundCreate(0, &direct_sound, 0);
direct_sound->SetCooperativeLevel(hwnd, DSSCL_PRIORITY);

WAVEFORMATEX format = {0};
format.wFormatTag = WAVE_FORMAT_PCM;
format.nChannels = 2;
format.nSamplesPerSec = 44100;
format.wBitsPerSample = 16;
format.nBlockAlign = format.nChannels * format.wBitsPerSample / 8;
format.nAvgBytesPerSec = format.nSamplesPerSec * format.nBlockAlign;

DSBUFFERDESC desc = {0};
desc.dwSize = sizeof(desc);
desc.dwFlags = DSBCAPS_PRIMARYBUFFER;
desc.lpwfxFormat = &format;

LPDIRECTSOUNDBUFFER buffer;
direct_sound->CreateSoundBuffer(&desc, &buffer, 0);
buffer->Play(0, 0, DSBPLAY_LOOPING);

// 每帧:获取 play cursor,写样本
DWORD play_cursor, write_cursor;
buffer->GetCurrentPosition(&play_cursor, &write_cursor);
// ... 算样本数,写入 ...
```

### winit + cpal

```rust
let host = cpal::default_host();
let device = host.default_output_device().unwrap();
let config = device.default_output_config().unwrap();
let sample_rate = config.sample_rate().0;
let channels = config.channels();

let stream = device.build_output_stream(
    &config.into(),
    move |data: &mut [f32], _: &_| {
        // 声卡需要 data.len() 个样本,你填
        for sample in data.iter_mut() {
            *sample = generate_next_sample();
        }
    },
    |err| eprintln!("{}", err),
    None,
).unwrap();
stream.play().unwrap();
```

### 映射

| Win32 (DirectSound) | cpal |
|---|---|
| `DirectSoundCreate` | `default_host().default_output_device()` |
| `SetCooperativeLevel` | (不需要) |
| `WAVEFORMATEX` | `default_output_config()` |
| 创建 secondary buffer | (cpal 内部) |
| `GetCurrentPosition` | (cpal 回调自动) |
| 你 push 数据 | 声卡 pull 回调 |
| 16-bit i16 样本 | 默认 32-bit f32(可配置) |

### 抽象边界

cpal 抽象了:

- DirectSound / ALSA / CoreAudio 的差异
- ring buffer 管理
- play cursor 同步

cpal 没抽象:

- 设备热插拔(插拔耳机/USB 声卡)
- 高级特性(空间音频、效果链)
- 真正低延迟(JACK 才能做到几 ms,cpal 默认 20+ ms)

## 7 · 时间

### Win32

```c
LARGE_INTEGER freq, start;
QueryPerformanceFrequency(&freq);
QueryPerformanceCounter(&start);

// 测时间
LARGE_INTEGER now;
QueryPerformanceCounter(&now);
double elapsed = (now.QuadPart - start.QuadPart) / (double)freq.QuadPart;
```

或 RDTSC(直接读 CPU 时间戳计数器):

```c
uint64_t tsc = __rdtsc();
```

### winit + std::time

```rust
use std::time::Instant;

let start = Instant::now();
// ...
let elapsed = start.elapsed().as_secs_f64();
```

### 映射

| Win32 | Rust std |
|---|---|
| `QueryPerformanceCounter` | `Instant::now()` |
| `QueryPerformanceFrequency` | (内部处理) |
| `RDTSC` | (Rust 没直接 API,可用 asm) |
| `GetTickCount` (毫秒精度) | `Instant::elapsed().as_millis()` |

### 实现细节

`Instant::now()` 在 Linux 上调用 `clock_gettime(CLOCK_MONOTONIC)`,纳秒精度,几十纳秒开销。

Casey 在 HH 用 `QueryPerformanceCounter`(主)+ `RDTSC`(微基准)。Rust `Instant` 等价 QPC,够用。

## 8 · 文件 I/O

### Win32

```c
HANDLE file = CreateFileA("data.bin", GENERIC_READ, FILE_SHARE_READ, 
                          NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
LARGE_INTEGER size;
GetFileSizeEx(file, &size);
char *buffer = malloc(size.QuadPart);
DWORD read;
ReadFile(file, buffer, size.QuadPart, &read, NULL);
CloseHandle(file);
```

### winit + std::fs

```rust
use std::fs;

let data = fs::read("data.bin").unwrap();
let bytes_written = fs::write("out.bin", &data).unwrap();
```

### 映射

| Win32 | std::fs |
|---|---|
| `CreateFileA` | `fs::File::open` / `fs::OpenOptions` |
| `ReadFile` | `file.read` / `fs::read` |
| `WriteFile` | `file.write` / `fs::write` |
| `CloseHandle` | (drop 自动) |
| `GetFileSizeEx` | `file.metadata().len()` |

`std::fs` 跨平台(POSIX + Win32 都封装)。

### 路径差异

Windows:反斜杠 `C:\Users\sun\file.txt`
Linux:正斜杠 `/home/sun/file.txt`

Rust `PathBuf` 自动处理:

```rust
use std::path::PathBuf;
let p = PathBuf::from("data").join("level1.bin");
// Windows: "data\level1.bin"
// Linux: "data/level1.bin"
```

### XDG 路径

Linux 用户期望配置在 `~/.config/`,数据在 `~/.local/share/`,缓存在 `~/.cache/`。Windows 习惯是当前目录。

Rust 用 `dirs` crate:

```rust
use dirs;

let config = dirs::config_dir().unwrap();  // ~/.config(Linux) / AppData/Roaming(Win)
let data = dirs::data_dir().unwrap();      // ~/.local/share / AppData/Local
let cache = dirs::cache_dir().unwrap();    // ~/.cache / AppData/Local/Temp
```

不要硬编码路径。Casey 用当前目录(Windows 习惯),Linux 应该用 XDG。

## 9 · 动态加载

### Win32

```c
HMODULE lib = LoadLibraryA("handmade.dll");
if (!lib) { /* error */ }

typedef void Fn(Memory*, Input*);
Fn *update_and_render = (Fn*)GetProcAddress(lib, "update_and_render");
if (!update_and_render) { /* error */ }

update_and_render(memory, input);

FreeLibrary(lib);
```

### winit + libloading

```rust
use libloading::Library;

let lib = unsafe { Library::new("./libhandmade.so") }?;
let func: libloading::Symbol<unsafe extern "C" fn(*mut Memory, *const Input)> = 
    unsafe { lib.get(b"update_and_render") }?;
unsafe { func(memory, input) };
drop(lib);
```

### 映射

| Win32 | libloading |
|---|---|
| `LoadLibraryA` | `Library::new` |
| `GetProcAddress` | `lib.get(b"name")` |
| `FreeLibrary` | `drop(lib)` |
| 引用计数(多次 Load) | (libloading 同样) |
| `.dll` | `.so` (Linux) / `.dylib` (macOS) |

### 文件格式

| 平台 | 库扩展 | 格式 |
|---|---|---|
| Windows | .dll | PE / COFF |
| Linux | .so | ELF |
| macOS | .dylib | Mach-O |

Casey 假设 .dll。你的 Rust 代码要跨平台,用 `std::env::consts`:

```rust
let ext = if cfg!(windows) { "dll" } 
         else if cfg!(target_os = "macos") { "dylib" }
         else { "so" };
let path = format!("./libhandmade.{}", ext);
```

或更优雅:

```rust
let path = std::env::current_exe().unwrap()
    .with_file_name("libhandmade")
    .with_extension(std::env::consts::DLL_EXTENSION);
```

## 10 · Linux 特定陷阱

跟 Casey 跟做时,你 Linux 会遇到这些 Casey 没提的问题:

### Wayland vs X11

KDE Plasma 5.21+ 默认 Wayland。Wayland 和 X11 在很多方面行为不同:

- **窗口位置**:Wayland 不让客户端决定窗口位置(KWin 决定)。X11 让。
- **全局热键**:Wayland 不让客户端监听全局键盘(安全模型)。X11 让。
- **屏幕坐标**:Wayland 客户端不知道自己在屏幕哪里。X11 知道。
- **窗口装饰**:Wayland 由合成器画(SSD),X11 客户端画(CSD)。

winit 在两个后端都工作,但某些 API 在 Wayland 下无效(`with_position`)。

### DPI 缩放

4K 屏 + KDE 通常开 1.5× 或 2× 缩放。

```rust
let window = event_loop.create_window(
    Window::default_attributes()
        .with_inner_size(LogicalSize::new(800, 600))  // 逻辑像素
)?;
// 实际物理像素可能是 1200×900(1.5×)或 1600×1200(2×)

let physical = window.inner_size();  // PhysicalSize
let scale = window.scale_factor();   // 1.5 / 2.0
```

游戏代码用**物理像素**画(softbuffer 给的 buffer 是物理像素)。

### 输入法(IME)

中文输入法激活时,键盘事件被 IME 截获。winit 给你 `WindowEvent::Ime` 而非 `KeyboardInput`。

游戏一般忽略 IME,但要处理"玩家输入法激活时游戏收不到键盘"——告诉用户打字时关 IME。

### libinput

Wayland 下键盘 / 鼠标 / 触摸板通过 libinput(用户态库)→ 内核 evdev。winit 用 libinput。

某些旧游戏手柄 libinput 支持差——这就是 gilrs 直接走 evdev 的原因(绕过 libinput)。

### PipeWire vs PulseAudio

KDE Plasma 5.21+ 默认 PipeWire。老系统是 PulseAudio。cpal 都支持,自动选。

### 内核 HZ

```bash
zcat /proc/config.gz | grep CONFIG_HZ
# CONFIG_HZ_1000=y  ← 桌面内核默认 1000 Hz
# CONFIG_HZ=1000
```

1000 Hz 意味着 timer 精度 1ms。`sleep(4)` 可能睡 4-5ms。Windows 默认 15.6ms 精度(要 `timeBeginPeriod(1)`)。

Linux 这个对游戏友好,不需要全局副作用。

## 11 · 总结:抽象层级

```
┌────────────────────────────────────┐
│ 你的游戏代码                        │  ← 业务逻辑
├────────────────────────────────────┤
│ winit / softbuffer / cpal / gilrs │  ← 跨平台抽象
├────────────────────────────────────┤
│ libloading                         │  ← 动态加载
├────────────────────────────────────┤
│ Wayland / X11 / ALSA / evdev       │  ← Linux 用户态 API
├────────────────────────────────────┤
│ Linux 内核(syscall / driver)      │  ← 内核
├────────────────────────────────────┤
│ 硬件                                │
└────────────────────────────────────┘
```

Casey 的 Win32 代码在 Windows 上类似的层级,只是中间层是 Win32 API。

## 12 · 调试跨平台问题

跟做 HH 时遇到问题,排查流程:

1. **winit 文档**:这个 API 在 Linux 下行为是否不同?
2. **Arch Wiki**:Wayland / PipeWire / evdev 的预期行为
3. **winit / softbuffer / cpal / gilrs 的 issue tracker**:别人遇到过吗?
4. **KDE bug tracker**:Wayland 特定问题
5. **最小复现**:写最小 demo,排除游戏代码

实战工具:

```bash
# Wayland 调试
WAYLAND_DEBUG=1 ./your-app  # 打印 Wayland 协议消息

# PipeWire 调试
PIPEWIRE_DEBUG=2 ./your-app
pw-top  # 实时看状态

# 输入调试
sudo evtest /dev/input/event15  # 看手柄事件

# 字体 / DPI
xrdb -query | grep dpi  # X11
kcminput diag  # KDE 输入诊断
```

## 13 · Casey 哲学 vs 现代跨平台

Casey 在 HH 用 Win32,理由:

- 透明(每行代码看得懂)
- 教学(让你理解底层)
- 性能(无抽象开销)

你用 winit,理由:

- 跨平台(一份代码 Linux / Windows / macOS)
- 现代(社区维护,bug 修复)
- 体验(IDE 集成、文档好)

两种哲学各有道理。Casey 选纯 Win32 因为他在做教学视频;你选 winit 因为你在跟做 + 学习 Rust。

**理解 Casey 的选择 + 用现代工具**——这是 HH 跟做者的最佳路径。

## 延伸阅读

本仓库:
- [day002](../day002.md)——窗口
- [day003](../day003.md)——后缓冲
- [day006](../day006.md)——输入
- [day007](../day007.md)——音频
- [day021](../day021.md)——动态加载

外部:
- winit 文档:https://docs.rs/winit/
- softbuffer:https://docs.rs/softbuffer/
- Wayland 协议:https://wayland.app/protocols/
- Arch Wiki Wayland:https://wiki.archlinux.org/title/Wayland
- Arch Wiki PipeWire:https://wiki.archlinux.org/title/PipeWire
- Casey HH Day 2(Win32 窗口):https://guide.handmadehero.org/code/day002/
