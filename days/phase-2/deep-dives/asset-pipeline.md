---
phase: 2
type: deep-dive
title: "资产管线:从文件格式解析到缓存到热加载"
domains: [game, linux, rust]
duration: "2.5h"
prereqs: ["day029", "day036", "day037", "day055"]
---

# 资产管线 · 从文件格式解析到缓存到热加载

> BMP、TGA、WAV、PNG——这些是 Casey 在 HH 早期手写的资产格式。后期(Phase 7)还要写 PNG 解码器、glTF 加载器。资产管线是"游戏工程化"的最后一块拼图:把"硬盘上的文件"变成"内存里能用的数据"。本文 2.5 小时讲完:文件格式解析、内存管理、缓存策略、热加载、压缩基础。

## 0 · 这篇文章解决什么问题

你的游戏需要:

- 玩家的精灵图(BMP / TGA / PNG)
- 怪物的动画表(多帧 PNG)
- 音效(WAV / OGG)
- 地图数据(TILED / 自定义格式)
- 字体(TTF / OTF)

**问题**:硬盘上的 BMP 文件是 1.5 MB,你 `read` 进内存,需要把它变成"宽 64 高 64 的 ARGB 像素数组"才能 blit。这中间要:

1. 打开文件(`open`)
2. 读字节(`read`)
3. 解析 BMP 文件头(BMP 格式规范)
4. 解压像素(BMP 可能用 RLE 压缩)
5. 转换色彩格式(BMP 是 BGR,游戏要 ARGB)
6. 存到 GameMemory
7. **缓存**(下次再要这张图,直接返回内存版本,不重读文件)

这每一步都可能踩坑。Casey 在 HH Day 036 写第一个 BMP 加载器,Day 037 加 TGA,Day 038 加 alpha blending。Phase 7 写 PNG 解码器。本文把这些都串起来。

读完本文,你能:

- 解释 BMP / TGA / WAV 文件格式的结构
- 写一个文件加载器(读字节 + 解析 + 转换)
- 设计一个资产缓存系统(避免重复加载)
- 加资产热重载(改 BMP 自动重载)
- 知道 PNG / JPEG / OGG 等格式的取舍

## 1 · 资产管线的完整链路

```
┌────────────────────────────────────────────────────────────────┐
│  开发者侧                                                      │
│  [Photoshop / Aseprite / Audacity] → 产出 .bmp / .wav          │
│                                                                │
│  → 放进 assets/sprites/ 或 assets/sounds/                      │
└────────────────────────────────────────────────────────────────┘
                                ↓
┌────────────────────────────────────────────────────────────────┐
│  构建系统侧                                                    │
│  cargo build → 把 assets/ copy 到 target/release/assets/        │
│  (或用 include_bytes!() 编译进二进制)                          │
└────────────────────────────────────────────────────────────────┘
                                ↓
┌────────────────────────────────────────────────────────────────┐
│  运行时(平台层)                                               │
│  [1] 资产加载请求(load_bitmap("player.bmp"))                  │
│  [2] 查缓存:有?→ 返回 cached Bitmap                          │
│                        └ 没有 ↓                                │
│  [3] open + read 文件 → Vec<u8>                                │
│  [4] 解析格式(BMP / TGA / WAV)                                │
│  [5] 转换像素格式(BGR → ARGB)                                 │
│  [6] 存进 GameMemory(arena 分配)                              │
│  [7] 注册到缓存表(HashMap<Tag, Bitmap>)                       │
│  [8] 返回 Bitmap                                               │
└────────────────────────────────────────────────────────────────┘
                                ↓
┌────────────────────────────────────────────────────────────────┐
│  游戏层                                                        │
│  [9] 用 Bitmap 渲染(blit 到 framebuffer)                      │
│  [10] 文件改了 → 触发热加载 → 重新读 + 解析 + 替换缓存          │
└────────────────────────────────────────────────────────────────┘
```

每一步都可能踩坑:

- 文件路径错(`/` vs `\`,大小写)
- 格式解析错(BMP 有十几种变种)
- 内存泄漏(加载 1000 次没用 999 次不释放)
- 缓存失效(改了 BMP 但缓存还是旧的)
- 颜色空间错(BMP 是 sRGB,游戏光照要 linear)

本文逐个解决。

## 2 · BMP 文件格式

### 2.1 BMP 的优势

Casey 选 BMP 不是因为格式好,是因为**简单**——无压缩(BITMAPINFOHEADER 变种),字节布局直白,初学者能 1 小时写完解析器。

### 2.2 BMP 文件结构

```
┌──────────────────────────┐  ← byte 0
│ BITMAPFILEHEADER (14 字节)│
├──────────────────────────┤  ← byte 14
│ BITMAPINFOHEADER (40 字节)│
├──────────────────────────┤  ← byte 54
│ (可选)调色板             │
├──────────────────────────┤
│ 像素数据                 │
│                          │
└──────────────────────────┘
```

#### BITMAPFILEHEADER(14 字节)

```rust
#[repr(C, packed)]
struct BitmapFileHeader {
    file_type: u16,        // "BM" = 0x4D42(little endian)
    file_size: u32,        // 整个文件大小
    reserved1: u16,
    reserved2: u16,
    pixel_offset: u32,     // 像素数据起始字节偏移(通常 54)
}
```

#### BITMAPINFOHEADER(40 字节)

```rust
#[repr(C, packed)]
struct BitmapInfoHeader {
    size: u32,             // 这个 header 的大小(40)
    width: i32,            // 图像宽
    height: i32,           // 图像高(正数 = bottom-up,负数 = top-down)
    planes: u16,           // 必须是 1
    bits_per_pixel: u16,   // 通常 24(BGR)或 32(BGRA)
    compression: u32,      // 0 = 不压缩(BI_RGB)
    image_size: u32,       // 像素数据大小(0 表示不压缩时不算)
    x_ppm: i32,            // 水平分辨率(像素/米)
    y_ppm: i32,            // 垂直分辨率
    colors_used: u32,      // 调色板颜色数(0 = 全用)
    important_colors: u32, // 重要颜色数(0 = 全部)
}
```

### 2.3 像素数据

- **bottom-up**(height > 0):第一行是图像底部
- **top-down**(height < 0):第一行是图像顶部
- **每行**必须**对齐到 4 字节**——如果宽是 5 像素 × 3 字节(BGR)= 15 字节,要 pad 到 16 字节
- **像素格式**:24-bit 是 BGR(不是 RGB!),32-bit 是 BGRA

### 2.4 完整 Rust 解析器

```rust
use std::fs::File;
use std::io::Read;

pub struct Bitmap {
    pub width: i32,
    pub height: i32,
    pub pixels: Vec<u32>,  // ARGB(0xAARRGGBB)
}

pub fn load_bmp(path: &str) -> Result<Bitmap, Box<dyn std::error::Error>> {
    let mut file = File::open(path)?;
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes)?;

    // 读 BITMAPFILEHEADER
    let file_type = u16::from_le_bytes([bytes[0], bytes[1]]);
    if file_type != 0x4D42 {
        return Err("Not a BMP file".into());
    }
    let pixel_offset = u32::from_le_bytes([bytes[10], bytes[11], bytes[12], bytes[13]]) as usize;

    // 读 BITMAPINFOHEADER
    let width = i32::from_le_bytes([bytes[18], bytes[19], bytes[20], bytes[21]]);
    let height_raw = i32::from_le_bytes([bytes[22], bytes[23], bytes[24], bytes[25]]);
    let bits_per_pixel = u16::from_le_bytes([bytes[28], bytes[29]]) as usize;
    let compression = u32::from_le_bytes([bytes[30], bytes[31], bytes[32], bytes[33]]);
    if compression != 0 {
        return Err("Compressed BMP not supported".into());
    }
    if bits_per_pixel != 24 && bits_per_pixel != 32 {
        return Err("Only 24 or 32 BPP supported".into());
    }

    let top_down = height_raw < 0;
    let height = height_raw.abs();
    let bytes_per_pixel = bits_per_pixel / 8;
    let row_size_unpadded = width as usize * bytes_per_pixel;
    let row_size = (row_size_unpadded + 3) & !3;  // 对齐到 4 字节

    let mut pixels = vec![0u32; (width * height) as usize];

    for row in 0..height as usize {
        let source_row = if top_down { row } else { (height as usize - 1) - row };
        let row_start = pixel_offset + source_row * row_size;
        for col in 0..width as usize {
            let pixel_start = row_start + col * bytes_per_pixel;
            let b = bytes[pixel_start];
            let g = bytes[pixel_start + 1];
            let r = bytes[pixel_start + 2];
            let a = if bytes_per_pixel == 4 { bytes[pixel_start + 3] } else { 255 };
            // ARGB:0xAARRGGBB
            pixels[row * width as usize + col] =
                ((a as u32) << 24) | ((r as u32) << 16) | ((g as u32) << 8) | (b as u32);
        }
    }

    Ok(Bitmap { width, height, pixels })
}
```

**关键点**:
- `u16::from_le_bytes` / `u32::from_le_bytes` —— BMP 是 little endian,Rust 的整数默认 native endian,要用 le_bytes 函数显式指定。
- `#[repr(C, packed)]` —— BMP header 没有填充字节,packed 强制无 padding。
- `pixel_offset` 告诉你像素数据从哪开始(不是固定的 54 字节,因为有调色板变种)。
- 行对齐到 4 字节:`(row_size_unpadded + 3) & !3` 是"向上取整到 4 的倍数"的位运算技巧。

## 3 · TGA 文件格式

### 3.1 为什么用 TGA

TGA 也有 RLE 压缩变种,比 BMP 稍好(文件小 30-50%)。Aseprite 等像素艺术工具原生支持 TGA。

### 3.2 TGA 结构

```
┌────────────────────────────┐  ← byte 0
│ TGA Header (18 字节)       │
├────────────────────────────┤
│ (可选)Image ID             │
├────────────────────────────┤
│ (可选)Color Map            │
├────────────────────────────┤
│ Image Data                 │
└────────────────────────────┘
```

```rust
#[repr(C, packed)]
struct TgaHeader {
    id_length: u8,           // Image ID 长度(通常 0)
    color_map_type: u8,      // 0 = 无调色板
    image_type: u8,          // 2 = uncompressed true-color,10 = RLE true-color
    color_map_spec: [u8; 5], // 调色板信息(我们不用)
    x_origin: u16,
    y_origin: u16,
    width: u16,
    height: u16,
    bits_per_pixel: u8,      // 24 或 32
    image_descriptor: u8,    // bit 5:1=top-down, 0=bottom-up
}
```

### 3.3 解析(简化,只支持 uncompressed)

```rust
pub fn load_tga(path: &str) -> Result<Bitmap, Box<dyn std::error::Error>> {
    let bytes = std::fs::read(path)?;
    let header_size = 18;
    let width = u16::from_le_bytes([bytes[12], bytes[13]]) as i32;
    let height = u16::from_le_bytes([bytes[14], bytes[15]]) as i32;
    let bpp = bytes[16] as usize;
    let top_down = (bytes[17] & 0x20) != 0;

    let bytes_per_pixel = bpp / 8;
    let pixel_data_start = header_size + bytes[0] as usize;
    let mut pixels = vec![0u32; (width * height) as usize];

    for row in 0..height as usize {
        let source_row = if top_down { row } else { (height as usize - 1) - row };
        for col in 0..width as usize {
            let i = pixel_data_start + (source_row * width as usize + col) * bytes_per_pixel;
            let (b, g, r, a) = match bytes_per_pixel {
                3 => (bytes[i], bytes[i + 1], bytes[i + 2], 255u8),
                4 => (bytes[i], bytes[i + 1], bytes[i + 2], bytes[i + 3]),
                _ => return Err("Unsupported BPP".into()),
            };
            pixels[row * width as usize + col] =
                ((a as u32) << 24) | ((r as u32) << 16) | ((g as u32) << 8) | (b as u32);
        }
    }

    Ok(Bitmap { width, height, pixels })
}
```

## 4 · WAV 文件格式

### 4.1 WAV 结构

WAV 是 RIFF 容器(Resource Interchange File Format,微软 1991):

```
┌────────────────────────────┐
│ "RIFF" (4 字节 ASCII)       │
├────────────────────────────┤
│ ChunkSize (4 字节)          │
├────────────────────────────┤
│ "WAVE" (4 字节)             │
├────────────────────────────┤
│ fmt  subchunk              │
│  ├ "fmt " (4 字节)         │
│  ├ SubchunkSize (4 字节)   │
│  ├ AudioFormat (2 字节)    │
│  ├ NumChannels (2 字节)    │
│  ├ SampleRate (4 字节)     │
│  ├ ByteRate (4 字节)       │
│  ├ BlockAlign (2 字节)     │
│  ├ BitsPerSample (2 字节)  │
├────────────────────────────┤
│ data subchunk              │
│  ├ "data" (4 字节)         │
│  ├ SubchunkSize (4 字节)   │
│  └ 音频样本数据            │
└────────────────────────────┘
```

### 4.2 Rust 解析

```rust
pub struct WavSound {
    pub channels: u16,
    pub samples_per_second: u32,
    pub bits_per_sample: u16,
    pub samples: Vec<i16>,  // 立体声:L R L R ...
}

pub fn load_wav(path: &str) -> Result<WavSound, Box<dyn std::error::Error>> {
    let bytes = std::fs::read(path)?;
    // 检查 "RIFF"
    if &bytes[0..4] != b"RIFF" { return Err("Not a WAV file".into()); }
    if &bytes[8..12] != b"WAVE" { return Err("Not a WAV file".into()); }

    // 找 fmt chunk
    let mut i = 12;
    let mut channels = 0u16;
    let mut sample_rate = 0u32;
    let mut bits_per_sample = 0u16;

    while i < bytes.len() {
        let chunk_id = &bytes[i..i+4];
        let chunk_size = u32::from_le_bytes(
            [bytes[i+4], bytes[i+5], bytes[i+6], bytes[i+7]
        ]) as usize;

        if chunk_id == b"fmt " {
            channels = u16::from_le_bytes([bytes[i+10], bytes[i+11]]);
            sample_rate = u32::from_le_bytes([bytes[i+12], bytes[i+13], bytes[i+14], bytes[i+15]]);
            bits_per_sample = u16::from_le_bytes([bytes[i+22], bytes[i+23]]);
        } else if chunk_id == b"data" {
            let data_start = i + 8;
            let data_end = data_start + chunk_size;
            let samples: Vec<i16> = bytes[data_start..data_end]
                .chunks_exact(2)
                .map(|c| i16::from_le_bytes([c[0], c[1]]))
                .collect();
            return Ok(WavSound { channels, samples_per_second: sample_rate, bits_per_sample, samples });
        }
        i += 8 + chunk_size;
    }
    Err("No data chunk".into())
}
```

## 5 · 资产缓存

### 5.1 为什么需要缓存

```rust
// 错误:每次渲染都重读文件
fn render_player() {
    let bmp = load_bmp("assets/player.bmp").unwrap();  // 每帧读 1.5MB!
    blit(bmp);
}
```

60 FPS → 每秒 90 MB 磁盘 IO。游戏卡死。

### 5.2 简单缓存

```rust
use std::collections::HashMap;

pub struct AssetCache {
    bitmaps: HashMap<String, Bitmap>,
    sounds: HashMap<String, WavSound>,
}

impl AssetCache {
    pub fn new() -> Self {
        Self { bitmaps: HashMap::new(), sounds: HashMap::new() }
    }

    pub fn get_bitmap(&mut self, path: &str) -> Result<&Bitmap, Box<dyn std::error::Error>> {
        if !self.bitmaps.contains_key(path) {
            let bmp = load_bmp(path)?;
            self.bitmaps.insert(path.to_string(), bmp);
        }
        Ok(self.bitmaps.get(path).unwrap())
    }

    pub fn get_sound(&mut self, path: &str) -> Result<&WavSound, Box<dyn std::error::Error>> {
        if !self.sounds.contains_key(path) {
            let s = load_wav(path)?;
            self.sounds.insert(path.to_string(), s);
        }
        Ok(self.sounds.get(path).unwrap())
    }
}
```

第一次加载从磁盘读,之后从 HashMap 取。**O(1) amortized**。

### 5.3 资产 ID(Handle)

为了避免 string 比较开销,Casey 用 hash 把 path 变成 u64 ID:

```rust
pub type AssetId = u64;

fn hash_path(path: &str) -> AssetId {
    use std::collections::hash_map::DefaultHasher;
    use std::hash::{Hash, Hasher};
    let mut hasher = DefaultHasher::new();
    path.hash(&mut hasher);
    hasher.finish()
}

pub struct AssetCache {
    bitmaps: HashMap<AssetId, Bitmap>,
}

impl AssetCache {
    pub fn get_bitmap(&mut self, path: &str) -> Result<&Bitmap, Box<dyn std::error::Error>> {
        let id = hash_path(path);
        if !self.bitmaps.contains_key(&id) {
            let bmp = load_bmp(path)?;
            self.bitmaps.insert(id, bmp);
        }
        Ok(self.bitmaps.get(&id).unwrap())
    }
}
```

游戏代码用 `let player_id = hash_path("assets/player.bmp");` 一次,后续传 id。**string 比较变成 u64 比较,快很多**。

### 5.4 内存管理

资产加载到 GameMemory(平台层分配的 1GB)。每个 Bitmap 占 `width * height * 4` 字节,1MB 的图 1000 张 = 1GB,你的内存预算就满了。

解决:

1. **LRU 缓存**:只保留最近用的 N 张,其他释放
2. **按需加载**:走到关卡才加载关卡的资产
3. **流式加载**:背景线程加载,前台不卡

Casey 在 HH Phase 4-5 才加这些。Phase 2 全装内存(小游戏够用)。

## 6 · 资产热加载

### 6.1 需求

改 `assets/player.bmp`,游戏不重启,看到的精灵图立即更新。

### 6.2 实现

类似代码热重载:监控资产文件 mtime,变了重新加载。

```rust
struct AssetEntry<T> {
    data: T,
    last_modified: std::time::SystemTime,
}

pub struct AssetCache {
    bitmaps: HashMap<AssetId, AssetEntry<Bitmap>>,
}

impl AssetCache {
    pub fn get_bitmap(&mut self, path: &str) -> Result<&Bitmap, Box<dyn std::error::Error>> {
        let id = hash_path(path);
        let current_mtime = std::fs::metadata(path)?.modified()?;

        let needs_load = match self.bitmaps.get(&id) {
            None => true,
            Some(entry) => entry.last_modified != current_mtime,
        };

        if needs_load {
            let bmp = load_bmp(path)?;
            self.bitmaps.insert(id, AssetEntry { data: bmp, last_modified: current_mtime });
        }

        Ok(&self.bitmaps.get(&id).unwrap().data)
    }
}
```

每次 `get_bitmap` 都查 mtime(1 µs),如果文件改了重载。游戏里循环 `get_bitmap("player.bmp")` 时,改 BMP → 保存 → 下一帧自动重载。

### 6.3 监控多个文件

如果资产多(1000+),每帧查 1000 次 mtime 太慢。用 inotify / notify crate 异步通知。

## 7 · 跨平台路径

### 7.1 路径分隔符

- Linux:`/`
- Windows:`\`(但也接受 `/`)
- macOS:`/`

Rust 的 `Path` / `PathBuf` 自动处理跨平台。**永远用 `PathBuf::join`,不要字符串拼接**。

```rust
// 好
let path = PathBuf::from("assets").join("sprites").join("player.bmp");

// 坏(Linux 上能跑,Windows 不行)
let path = "assets/sprites/player.bmp";
```

### 7.2 大小写

Windows / macOS 文件系统**不区分大小写**(`Player.bmp` == `player.bmp`)。Linux **区分**。如果你的代码在 Windows 开发,导出到 Linux 服务器可能 "file not found"。

解决:强制 lowercase 命名约定。

### 7.3 工作目录

游戏在哪找 `assets/`?

- **相对路径**:`./assets/`,依赖当前工作目录(cwd)。如果用户从 file manager 双击启动,cwd 可能是 home,不是游戏目录。
- **可执行文件同目录**:`current_exe().parent()` 找到自己,在它旁边找 assets。最可靠。
- **绝对路径**:开发期硬编码 `/home/user/mygame/assets/`,发布不能这样。

```rust
fn assets_dir() -> PathBuf {
    let exe = std::env::current_exe().unwrap();
    exe.parent().unwrap().join("assets")
}
```

## 8 · 编译进二进制(include_bytes!)

小资产(字体、图标)可以编译进二进制,避免运行时 IO:

```rust
const FONT_BYTES: &[u8] = include_bytes!("../assets/font.ttf");
```

`include_bytes!` 在编译期读文件,变成 `&'static [u8]`。

**优势**:发布单文件,没 assets 目录。
**劣势**:二进制大,改资产要重 build。

适合小资产(几 KB),大资产(几 MB)不要。

## 9 · 资产压缩

### 9.1 为什么要压缩

- BMP:64×64 像素 = 16KB
- 同样 PNG(无损压缩):3-5 KB
- 同样 WebP:1-2 KB

10000 个精灵图,BMP 总 160MB,PNG 50MB,WebP 20MB。压缩能省 70-90% 磁盘。

### 9.2 压缩格式对比

| 格式 | 压缩率 | 解码速度 | 适合 |
|---|---|---|---|
| BMP | 1:1(不压缩) | 极快 | Casey HH 教学用 |
| TGA(RLE) | 2:1 | 快 | 像素艺术 |
| PNG | 3:1 | 中等(几 ms) | 通用 |
| WebP | 5:1 | 中等 | 现代 Web |
| JPEG | 10:1(有损) | 快 | 照片(不适合像素艺术) |
| BCn(DXT) | 4:1(硬件解码) | 极快 | GPU 纹理 |
| ASTC / ETC | 6:1(硬件) | 极快 | 移动 GPU 纹理 |

### 9.3 PNG 简介(Phase 7 详细讲)

PNG 用 DEFLATE 压缩(LZ77 + Huffman)。解码步骤:

1. 读 PNG 文件 signature(8 字节)
2. 读 IHDR chunk(width, height, bit depth, color type)
3. 读 IDAT chunk(像素数据,DEFLATE 压缩)
4. 用 zlib 解压
5. 反 filter(unfilter,每行的 1 字节 filter type + 数据)
6. 反 interlace(Adam7 pass 重组,可选)
7. 转 ARGB

每步都有坑。Casey 在 Phase 7 Day 436+ 完整写一遍 PNG 解码器。

### 9.4 Casey 的选择

- **Phase 1-2**:BMP / TGA(简单,教学清晰)
- **Phase 4+**:RLE 自定义压缩(快速版)
- **Phase 7**:PNG
- **Phase 8**:BCn 纹理压缩(GPU 友好)

## 10 · 业界对比

### 10.1 Casey HH

手写 BMP / TGA / WAV 解析。简单,教学清晰。

### 10.2 Bevy(asset crate)

```rust
use bevy::asset::AssetServer;

fn setup(assets: Res<AssetServer>) {
    let texture: Handle<Image> = assets.load("player.png");
    // 自动异步加载、缓存、热重载
}
```

Bevy 把所有资产抽象成 `Asset`,自动处理缓存、热重载、跨线程加载。

### 10.3 Unity

```csharp
// Resources.Load(同步)
Texture2D tex = Resources.Load<Texture2D>("player");

// Addressables(异步,2020+)
Addressables.LoadAssetAsync<Texture2D>("player").Completed += handle => {
    Texture2D tex = handle.Result;
};
```

Unity 早期(Resources)路径耦合,新版(Addressables)解耦。

### 10.4 Unreal

```cpp
// 同步
UTexture2D* Tex = LoadObject<UTexture2D>(nullptr, TEXT("/Game/Assets/Player"));

// 异步
FStreamableManager Streamable;
Streamable.RequestAsyncLoad("/Game/Assets/Player");
```

## 11 · 完整最小示例

下面是一个完整的 BMP 加载 + 缓存 + 热重载的 Rust 实现。

```rust
use std::collections::HashMap;
use std::path::Path;
use std::time::SystemTime;

pub struct Bitmap {
    pub width: i32,
    pub height: i32,
    pub pixels: Vec<u32>,
}

struct CacheEntry<T> {
    data: T,
    last_modified: SystemTime,
}

pub struct AssetCache {
    bitmaps: HashMap<String, CacheEntry<Bitmap>>,
}

impl AssetCache {
    pub fn new() -> Self {
        Self { bitmaps: HashMap::new() }
    }

    pub fn get_bitmap(&mut self, path: &str) -> Result<&Bitmap, Box<dyn std::error::Error>> {
        let mtime = std::fs::metadata(path)?.modified()?;
        let needs_load = match self.bitmaps.get(path) {
            None => true,
            Some(e) => e.last_modified != mtime,
        };
        if needs_load {
            let bmp = load_bmp(path)?;
            self.bitmaps.insert(path.to_string(), CacheEntry { data: bmp, last_modified: mtime });
        }
        Ok(&self.bitmaps.get(path).unwrap().data)
    }
}

// load_bmp 函数见 §2.4

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut cache = AssetCache::new();

    loop {
        let bmp = cache.get_bitmap("assets/test.bmp")?;
        // 渲染 bmp
        println!("Loaded: {}x{}", bmp.width, bmp.height);

        std::thread::sleep(std::time::Duration::from_millis(16));
    }
}
```

跑这个,然后改 `assets/test.bmp`(用 Photoshop 编辑),游戏立即看到新图。

## 12 · 延伸阅读

本仓库:
- [day029.md](../day029.md) —— 第一段代码读 BMP
- [day036.md](../day036.md) —— 完整 BMP 加载器
- [day037.md](../day037.md) —— TGA / alpha blending
- [day055.md](../day055.md) —— hash 表(资产缓存的底层数据结构)
- [deep-dives/platform-game-separation.md](platform-game-separation.md) —— GameMemory

外部:
- BMP format spec: https://en.wikipedia.org/wiki/BMP_file_format
- WAV format: http://soundfile.sapp.org/doc/WaveFormat/
- PNG spec: https://www.w3.org/TR/png/
- Bevy Asset 系统: https://bevyengine.org/news/bevy-0-12/#asset-system-rewrite

开源源码:
- image crate(Rust 图像解码库): https://github.com/image-rs/image
- bevy_asset: https://github.com/bevyengine/bevy/tree/main/crates/bevy_asset
- Casey HH Day 036: https://github.com/HandmadeHero/handmade-hero/tree/main/code/day036
