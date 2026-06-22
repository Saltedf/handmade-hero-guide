# PNG 文件格式全解:签名、Chunk、CRC32、过滤、隔行扫描

> 你写过 `image::open("texture.png")` 几百次,但 PNG 文件二进制长什么样?为什么前 8 字节永远是 `89 50 4E 47 0D 0A 1A 0A`?为什么 PNG 比 GIF 高效、比 JPEG 透明?这一篇从 W3C 规范逐字节解剖 PNG,让你能在 Rust 里手写一个能跑的 PNG 解码器,而不是永远依赖 `image` crate。

## 0 · 为什么 PNG 这么重要

PNG(Portable Network Graphics)诞生于 1995 年,是为了替代 GIF 的专利问题而设计的无损图像格式。今天它是:

- **Web 主流格式**(和 JPEG、WebP 并列)
- **游戏纹理的首选**(无损、有 alpha)
- **GUI 截图、图标、UI 资源**(无损 + 透明 = 完美)
- **数据交换**(科学图像、医学图像)

Casey 在 Handmade Hero Day 436 开始手写 PNG 解码器,不是为了好玩——是因为 PNG 是工业界游戏 / 网页 / UI 的基础数据格式,不懂它内部结构,你就:

1. 不知道为什么有时 PNG 加载慢(可能没解 DEFLATE 流)
2. 不知道为什么 alpha 边缘有黑边(PNG 没有 RGB + 单独 alpha,只有 RGBA 或灰度 + alpha)
3. 不知道为什么有些 PNG 在游戏里"碎掉"(可能是隔行扫描 Adam7,GPU 不支持)
4. 不知道如何优化(哪些 chunk 必须保留,哪些可以删)

**读完这一篇你能**:
- 用 hexdump 看一张 PNG,逐字节解释每段
- 在 Rust 里实现 PNG 签名校验、chunk 解析、CRC32 验证、过滤反演、Adam7 解隔行
- 解释 PNG / JPEG / WebP / AVIF 各自的取舍
- 给开源 PNG 解码器(如 `image` / `png` crate)贡献代码

## 1 · PNG 的设计哲学

PNG 解决了三个核心问题:

1. **无损**:解压后字节完全一致,适合医学图像 / 科学图像 / 纹理
2. **高压缩比**:用 DEFLATE(后面专题讲),8-30% 压缩比常见
3. **可移植**:跨平台、跨语言、跨架构

PNG 的设计选择:

- **块状结构**(chunks):每个 chunk 自描述(类型 + 长度 + 数据 + CRC),便于扩展
- **行级过滤**(filtering):每行先用 5 种过滤算法之一处理,再 DEFLATE 压缩——大幅提升压缩比
- **可选隔行扫描**(Adam7):渐进显示(网速慢时,模糊先显示,逐渐清晰)

W3C 规范文档: https://www.w3.org/TR/png/

## 2 · 文件签名:前 8 字节

PNG 文件永远以这 8 字节开始:

```
89 50 4E 47 0D 0A 1A 0A
```

十六进制 `89` 不是 ASCII 字符(故意选),避免被 7-bit 传输破坏。后面的 `50 4E 47` 是 ASCII "PNG"。最后 5 字节设计精妙:

```
0D 0A    CR LF  Windows 换行
1A       Unix 文件结束符
0A       LF  Unix 换行
```

这 5 字节组合能在所有平台"原样传输"——如果文件被错误地按文本处理,会被各种换行转换破坏,我们就能立刻发现签名错。

### Rust 校验签名

```rust
const PNG_SIGNATURE: [u8; 8] = [
    0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
];

fn check_png_signature(data: &[u8]) -> Result<(), &'static str> {
    if data.len() < 8 {
        return Err("file too short");
    }
    if data[..8] != PNG_SIGNATURE {
        return Err("not a PNG file (signature mismatch)");
    }
    Ok(())
}
```

## 3 · Chunk 结构:PNG 的"积木块"

签名之后,文件由一系列**chunk**(块)组成。每个 chunk 长这样(从字节 8 开始):

```
[长度 4 字节 BE][类型 4 字节 ASCII][数据 N 字节][CRC32 4 字节 BE]
```

- **长度**(4 字节,big-endian):Data 的字节数(0 到 2³¹-1)
- **类型**(4 字节 ASCII):chunk 的"名字",如 `IHDR`、`PLTE`、`IDAT`、`IEND`
- **数据**(N 字节):chunk 的具体内容,长度 = 长度字段
- **CRC32**(4 字节,big-endian):对 Type + Data 的 CRC32 校验

### Chunk 类型的命名约定

每个 chunk 类型是 4 个 ASCII 大写或小写字母。大小写有意义:

```
位 5(0x20)的第 1 字节(索引 0):
  大写 = 关键 chunk(必须支持)
  小写 = 辅助 chunk(可选)

位 5 的第 2 字节(索引 1):
  大写 = 公共(标准化)
  小写 = 私有(自定义)

位 5 的第 3 字节(索引 2):
  保留(必须大写)

位 5 的第 4 字节(索引 3):
  大写 = 不安全复制(编辑器不要拷贝)
  小写 = 安全复制(可拷贝)
```

例:`IHDR` 全大写 = 关键 + 公共 + 保留 + 不安全拷贝。`tEXt` = 辅助 + 公共 + 保留 + 安全拷贝。

### 关键 Chunk 列表

| Chunk | 必需 | 内容 |
|---|---|---|
| `IHDR` | 是 | 文件头:宽度、高度、位深度、颜色类型等 |
| `PLTE` | 仅调色板 | 调色板(用于 indexed color) |
| `IDAT` | 是 | 压缩的图像数据(可能多个 IDAT,逻辑上拼接) |
| `IEND` | 是 | 文件结束(空数据) |

### 辅助 Chunk(常见)

| Chunk | 用途 |
|---|---|
| `tEXt` | 文本元数据(标题、作者等) |
| `zTXt` | 压缩文本 |
| `iTXt` | 国际化文本(UTF-8) |
| `gAMA` | 图像 gamma |
| `cHRM` | 色度(色彩空间) |
| `sRGB` | sRGB 标记 |
| `iCCP` | ICC 色彩配置 |
| `tRNS` | 透明度(简单 alpha) |
| `bKGD` | 默认背景色 |
| `pHYs` | 物理像素尺寸(用于打印) |
| `tIME` | 最后修改时间 |

## 4 · IHDR:文件头详解

`IHDR` 必须是第一个 chunk(签名之后),长度固定 13 字节:

```
偏移  字段                  字节数  说明
0     Width                  4 BE   图像宽度(像素,1..2³¹)
4     Height                 4 BE   图像高度
8     Bit depth              1      每通道位数(1, 2, 4, 8, 16)
9     Color type             1      0=灰度, 2=RGB, 3=Indexed, 4=灰度+Alpha, 6=RGBA
10    Compression method     1      0(只支持 DEFLATE)
11    Filter method          1      0(只支持 5 种过滤)
12    Interlace method       1      0=不隔行, 1=Adam7
```

### Rust 解析 IHDR

```rust
#[derive(Debug)]
struct Ihdr {
    width: u32,
    height: u32,
    bit_depth: u8,
    color_type: u8,
    compression: u8,
    filter: u8,
    interlace: u8,
}

fn parse_ihdr(data: &[u8]) -> Result<Ihdr, &'static str> {
    if data.len() != 13 {
        return Err("IHDR must be 13 bytes");
    }
    Ok(Ihdr {
        width: u32::from_be_bytes([data[0], data[1], data[2], data[3]]),
        height: u32::from_be_bytes([data[4], data[5], data[6], data[7]]),
        bit_depth: data[8],
        color_type: data[9],
        compression: data[10],
        filter: data[11],
        interlace: data[12],
    })
}
```

每行注释:

- `from_be_bytes` — Rust 的标准库函数,把字节数组按 big-endian 转 u32
- Bit depth:每通道位数。对 RGBA 8-bit,bit_depth=8,每像素 4 字节
- Compression:只能是 0,DEFLATE;其他值预留但未使用
- Interlace:0 = 普通,1 = Adam7(下面讲)

## 5 · CRC32:校验每个 Chunk

CRC32(Cyclic Redundancy Check, 32-bit)是循环冗余校验,32 位校验码。PNG 规范规定每个 chunk 的 Type + Data 都要算 CRC32 并附在 chunk 末尾。

### CRC32 算法

CRC32 用一个生成多项式(IEEE 802.3):`x³² + x²⁶ + x²³ + x²² + x¹⁶ + x¹² + x¹¹ + x¹⁰ + x⁸ + x⁷ + x⁵ + x⁴ + x² + x + 1`,十六进制表示为 `0x04C11DB7`(或反向 `0xEDB88320`)。

简化实现:

```rust
fn crc32(data: &[u8]) -> u32 {
    // 标准 IEEE CRC32(用于 PNG、zip、Ethernet)
    let mut crc: u32 = 0xFFFFFFFF;
    for &byte in data {
        crc ^= byte as u32;
        for _ in 0..8 {
            if crc & 1 != 0 {
                crc = (crc >> 1) ^ 0xEDB88320;
            } else {
                crc >>= 1;
            }
        }
    }
    !crc
}
```

每行注释:

- 初始 `crc = 0xFFFFFFFF`(全 1)
- 每字节先 XOR 进 crc 低位
- 8 次循环,每次根据 LSB 决定是否 XOR 多项式
- 最后取反(`!crc`)

工业级实现用**查表法**(256 项预计算表)——快 8 倍。

### 在 Rust 里用标准库

```rust
let crc = crc32::checksum_ieee(data);
// 需要 crc32 crate: cargo add crc32
```

或者用 std 的 hash:

```rust
use std::hash::Hasher;
let mut h = std::collections::hash_map::DefaultHasher::new();
h.write(data);
let hash = h.finish();  // 不是 CRC32!是 DefaultHasher 的哈希
```

注意:`DefaultHasher` **不是** CRC32。需要 CRC32,用 `crc32fast` crate。

## 6 · IDAT:压缩的图像数据

`IDAT` chunk 存 DEFLATE 压缩的图像数据。多个 `IDAT` chunk 必须连续出现(规范要求),逻辑上拼接成一个 DEFLATE 流。

### 数据布局(解压前)

```
[IDAT chunk 1][IDAT chunk 2][...][IDAT chunk N]
```

每个 chunk 的 Data 是 DEFLATE 流的一段。解码时:把所有 IDAT 的 Data 拼起来,得到完整 DEFLATE 流,然后解压。

### 数据布局(解压后)

解压后的数据是"过滤后的行扫描":

```
[过滤字节 1][像素 1, 像素 2, ..., 像素 N]
[过滤字节 2][像素 1, 像素 2, ..., 像素 N]
...
```

每行前有 1 字节"过滤类型",指示该行用了哪种过滤(下面讲)。

## 7 · 行级过滤:PNG 压缩比的关键

DEFLATE(下面专题讲)对**重复字节序列**高效。但原始图像数据每行可能差异大(尤其高频纹理),DEFLATE 直接压效率低。**行级过滤**(filtering)把每行先做一次"差分"处理,让数据更"可压缩"。

PNG 定义 5 种过滤类型:

| 类型 | 名字 | 公式 | 适合 |
|---|---|---|---|
| 0 | None | `Recon(x) = Filt(x)` | 无过滤(原值) |
| 1 | Sub | `Recon(x) = Filt(x) + Recon(a)` | 渐变图像 |
| 2 | Up | `Recon(x) = Filt(x) + Recon(b)` | 水平条纹 |
| 3 | Average | `Recon(x) = Filt(x) + floor((Recon(a)+Recon(b))/2)` | 平滑图像 |
| 4 | Paeth | `Recon(x) = Filt(x) + PaethPredictor(a, b, c)` | 复杂图像 |

其中:

- `a` = 当前像素左边的像素(同行)
- `b` = 当前像素上面的像素(上行)
- `c` = 当前像素左上的像素

### Paeth 预测器

```rust
fn paeth_predictor(a: i32, b: i32, c: i32) -> i32 {
    let p = a + b - c;
    let pa = (p - a).abs();
    let pb = (p - b).abs();
    let pc = (p - c).abs();
    if pa <= pb && pa <= pc { a }
    else if pb <= pc { b }
    else { c }
}
```

直觉:Paeth 预测"当前像素最像左、上、左上哪个"。基于一个线性预测 `p = a + b - c`,然后选最接近 p 的邻居。

### 反演过滤(解码)

```rust
fn unfilter_row(
    filter_type: u8,
    filtered: &[u8],
    recon_prev: &[u8],  // 上一行(已反演)
    recon_cur: &mut [u8],
    bpp: usize,  // bytes per pixel
) {
    let len = filtered.len();
    for i in 0..len {
        let a = if i >= bpp { recon_cur[i - bpp] as i32 } else { 0 };
        let b = recon_prev.get(i).copied().unwrap_or(0) as i32;
        let c = if i >= bpp {
            recon_prev.get(i - bpp).copied().unwrap_or(0) as i32
        } else { 0 };
        
        let recon = match filter_type {
            0 => filtered[i] as i32,                                       // None
            1 => filtered[i] as i32 + a,                                   // Sub
            2 => filtered[i] as i32 + b,                                   // Up
            3 => filtered[i] as i32 + (a + b) / 2,                         // Average
            4 => filtered[i] as i32 + paeth_predictor(a, b, c),            // Paeth
            _ => panic!("unknown filter type"),
        };
        recon_cur[i] = (recon & 0xFF) as u8;
    }
}
```

每行注释:

- `bpp` — bytes per pixel,对 RGBA8 = 4
- 第一行没有上一行,`recon_prev` 全零(协议规定边界外是 0)
- 每行第一个像素没有左边和左上,`a` 和 `c` = 0
- `& 0xFF` 取低 8 位(过滤值经过 mod 256)

### 选择过滤的策略(编码端)

PNG 编码器对每行选过滤类型。简单策略:对每行试所有 5 种过滤,选**最小绝对偏差和**(MSAD)——压缩比通常最好。zopflib、libpng 都用这种策略。

## 8 · Adam7 隔行扫描

PNG 支持可选的"渐进显示"——网速慢时,先显示模糊轮廓,逐渐清晰。这叫 **Adam7 隔行扫描**(Adam M. Costello 1995 提出)。

### 7 个 Pass

Adam7 把图像分 7 个 pass,按以下模式采样:

```
1 6 4 6 2 6 4 6
7 7 7 7 7 7 7 7
5 6 5 6 5 6 5 6
7 7 7 7 7 7 7 7
3 6 4 6 3 6 4 6
7 7 7 7 7 7 7 7
5 6 5 6 5 6 5 6
7 7 7 7 7 7 7 7
```

数字 1-7 表示哪个 pass。Pass 1 是每 8 行 8 列的左上角(1/64 的像素),Pass 2 是每 8 行 8 列的中间偏左(再加 1/64),依此类推。每个 pass 内的行仍按普通方式存储(有过滤字节、有 IDAT 压缩)。

### 解码逻辑

```rust
fn deinterlace_adam7(
    width: u32, height: u32, bpp: usize,
    passes: Vec<Vec<u8>>,  // 7 个 pass 的解压后数据
) -> Vec<u8> {
    let mut output = vec![0u8; (width * height) as usize * bpp];
    
    let pass_info = [
        // (x_offset, y_offset, x_step, y_step)
        (0, 0, 8, 8),  // pass 1
        (4, 0, 8, 8),  // pass 2
        (0, 4, 4, 8),  // pass 3
        (2, 0, 4, 4),  // pass 4
        (0, 2, 2, 4),  // pass 5
        (1, 0, 2, 2),  // pass 6
        (0, 1, 1, 2),  // pass 7
    ];
    
    for (pass_idx, (x_off, y_off, x_step, y_step)) in pass_info.iter().enumerate() {
        let pass_data = &passes[pass_idx];
        let mut pass_y = 0;
        let mut data_offset = 0;
        
        let mut y = *y_off;
        while y < height {
            let mut x = *x_off;
            while x < width {
                for b in 0..bpp {
                    let src = pass_data[data_offset + b];
                    let dst_idx = ((y * width + x) as usize) * bpp + b;
                    output[dst_idx] = src;
                }
                data_offset += bpp;
                x += *x_step;
            }
            // 跳过过滤字节(每行开头 1 字节)
            data_offset += 1;
            y += *y_step;
            pass_y += 1;
        }
    }
    
    output
}
```

每段注释:

- 7 个 pass 各自有不同的起始位置和步长
- 每个 pass 内部仍按行存储(每行有过滤字节)
- 最终把 7 个 pass 的像素按位置写入输出 buffer

## 9 · 完整解码流程

```
1. 校验签名(8 字节)
2. 解析 IHDR(得到 width, height, bit_depth, color_type, interlace)
3. 循环解析 chunks:
   - PLTE:调色板(若 indexed color)
   - tRNS:透明度
   - IDAT:收集到一起(所有 IDAT)
   - 其他:辅助 chunk,可忽略
   - IEND:停止
4. 把 IDAT 数据拼起来,DEFLATE 解压
5. (若 Adam7)7 个 pass 分别处理
6. 反演每行过滤
7. (若 indexed color)查 PLTE 表得 RGB
8. 得到原始像素数据
```

## 10 · Rust 完整 PNG 解码器骨架

```rust
// Cargo.toml:
// [dependencies]
// flate2 = "1.0"  // DEFLATE 解码

use flate2::read::ZlibDecoder;
use std::io::Read;

pub struct PngImage {
    pub width: u32,
    pub height: u32,
    pub bit_depth: u8,
    pub color_type: u8,
    pub pixels: Vec<u8>,
}

pub fn decode_png(data: &[u8]) -> Result<PngImage, String> {
    // 1. 签名
    if data[..8] != PNG_SIGNATURE {
        return Err("not a PNG".into());
    }
    
    let mut offset = 8;
    let mut ihdr: Option<Ihdr> = None;
    let mut idat_data: Vec<u8> = Vec::new();
    let mut palette: Option<Vec<[u8; 3]>> = None;
    
    // 2. 循环解析 chunks
    while offset < data.len() {
        if offset + 8 > data.len() { break; }
        
        let length = u32::from_be_bytes([
            data[offset], data[offset+1], data[offset+2], data[offset+3]
        ]) as usize;
        let chunk_type = &data[offset+4..offset+8];
        let chunk_data = &data[offset+8..offset+8+length];
        // 跳过 CRC(offset+8+length 到 offset+8+length+4)
        
        match chunk_type {
            b"IHDR" => {
                ihdr = Some(parse_ihdr(chunk_data).map_err(|e| e.to_string())?);
            }
            b"PLTE" => {
                let mut pal = Vec::new();
                for chunk in chunk_data.chunks(3) {
                    pal.push([chunk[0], chunk[1], chunk[2]]);
                }
                palette = Some(pal);
            }
            b"IDAT" => {
                idat_data.extend_from_slice(chunk_data);
            }
            b"IEND" => break,
            _ => {}  // 忽略辅助 chunk
        }
        
        offset += 8 + length + 4;
    }
    
    let ihdr = ihdr.ok_or("missing IHDR")?;
    
    // 3. DEFLATE 解压
    let mut decoder = ZlibDecoder::new(&idat_data[..]);
    let mut decompressed = Vec::new();
    decoder.read_to_end(&mut decompressed).map_err(|e| e.to_string())?;
    
    // 4. 反演过滤 + (若 Adam7) 解隔行
    let pixels = if ihdr.interlace == 0 {
        unfilter_progressive(&decompressed, &ihdr)?
    } else {
        unfilter_adam7(&decompressed, &ihdr)?
    };
    
    Ok(PngImage {
        width: ihdr.width,
        height: ihdr.height,
        bit_depth: ihdr.bit_depth,
        color_type: ihdr.color_type,
        pixels,
    })
}

fn unfilter_progressive(
    data: &[u8], ihdr: &Ihdr,
) -> Result<Vec<u8>, String> {
    let bpp = bytes_per_pixel(ihdr.bit_depth, ihdr.color_type);
    let row_len = ihdr.width as usize * bpp;
    let mut output = vec![0u8; row_len * ihdr.height as usize];
    let mut prev_row = vec![0u8; row_len];
    
    let mut offset = 0;
    for y in 0..ihdr.height as usize {
        let filter_type = data[offset];
        offset += 1;
        let filtered = &data[offset..offset + row_len];
        offset += row_len;
        
        let cur_row = &mut output[y * row_len..(y + 1) * row_len];
        unfilter_row(filter_type, filtered, &prev_row, cur_row, bpp);
        
        prev_row.copy_from_slice(cur_row);
    }
    
    Ok(output)
}

fn bytes_per_pixel(bit_depth: u8, color_type: u8) -> usize {
    let channels = match color_type {
        0 => 1,  // 灰度
        2 => 3,  // RGB
        3 => 1,  // Indexed(每像素 1 字节索引)
        4 => 2,  // 灰度 + Alpha
        6 => 4,  // RGBA
        _ => panic!("unknown color type"),
    };
    // 简化:假设 bit_depth 是 8 的倍数
    channels * (bit_depth as usize / 8)
}
```

## 11 · PNG / JPEG / WebP / AVIF 对比

| 格式 | 压缩类型 | Alpha | 典型压缩比 | 用途 |
|---|---|---|---|---|
| PNG | 无损 + DEFLATE | ✓ | 30-50% | 纹理、UI、截图 |
| JPEG | 有损(DCT) | ✗ | 5-15% | 照片 |
| WebP | 无损/有损 | ✓ | 25-30% | Web(替代 PNG/JPEG) |
| AVIF | 无损/有损(AV1) | ✓ | 15-20% | 新一代 Web |
| GIF | 无损(LZW) | 1-bit | 50-70% | 动图 |
| TIFF | 多种 | ✓ | 60-80% | 专业图像 |

PNG 在"无损 + 有 alpha"场景仍然主流。WebP 和 AVIF 在 Web 上正逐渐取代 PNG,但游戏和 UI 仍大量用 PNG(因为工业工具链成熟)。

## 12 · 历史

- 1987: GIF 诞生(CompuServe),用 LZW 压缩
- 1994: Unisys 突然宣布 LZW 专利,要收费 → PNG 项目启动
- 1995: PNG 第一个规范(W3C)
- 1996: PNG 1.0 规范正式发布(W3C Recommendation)
- 2003: PNG 1.2 成为 ISO/IEC 标准
- 2010s: APNG(动画 PNG)被广泛支持
- 2020s: WebP / AVIF 挑战,但 PNG 仍是游戏 / UI 主流

## 13 · 关联 Day

- **铺垫**:Day 100+ 二进制读取;Day 200 DEFLATE 基础
- **当天**:本篇是 PNG 格式专题
- **后续**:`deflate-compression.md` 专题深入 DEFLATE;`asset-pipeline-architecture.md` 把 PNG 整合进资产管线

## 14 · 变式训练

### Lv1 · 概念辨析

**题**:为什么 PNG 用 5 种过滤而不是 1 种?每种过滤适合什么场景?

**参考解答**:DEFLATE 对"重复字节"高效,但原始图像每行差异大。过滤把"绝对值"转成"差分",让数据更可压缩。不同图像适合不同过滤:
- None:过滤引入噪声(随机图像)
- Sub:水平渐变(同色相的连续像素)
- Up:垂直渐变(条纹)
- Average:平滑过渡
- Paeth:复杂方向(几乎总是最优)

PNG 让每行独立选过滤,这样混合图像(天空 + 地面)能各选最优。编码器对每行试所有过滤,选最小绝对偏差和。

### Lv2 · 动手实践

**题**:用 `hexdump` 看一张 PNG 文件,识别每个 chunk 的类型和长度。

**提示**:`hexdump -C texture.png | head -30`

**参考解答**:

```bash
hexdump -C texture.png | head -10
# 输出示例:
# 00000000  89 50 4e 47 0d 0a 1a 0a  00 00 00 0d 49 48 44 52  |.PNG........IHDR|
# 00000010  00 00 01 00 00 00 01 00  08 06 00 00 00 5b a3 7d  |.............[.}|
# 00000020  1e 00 00 0a 49 44 41 54  78 da ...
# 
# 解析:
# 偏移 0-7:PNG 签名
# 偏移 8-11:0x0000000d = 13(IHDR Data 长度)
# 偏移 12-15:IHDR 类型(ASCII)
# 偏移 16-28:IHDR Data(13 字节:width=256, height=256, depth=8, type=6, ...)
# 偏移 29-32:CRC
# 偏移 33-:下一个 chunk(IDAT)
```

### Lv3 · 迁移设计

**题**:PNG 是图像格式,但 chunk 结构本质是"自描述的块状容器"。设计一个游戏存档文件格式,借鉴 PNG 的 chunk 结构。需要哪些 chunk 类型?如何处理版本升级?

**提示**:每个游戏对象(玩家、敌人、地图)一个 chunk。版本兼容性靠 chunk 类型大小写或专门的 version chunk。

### Lv4 · 开源贡献

**题**:`image` 是 Rust 主流图像库,GitHub: https://github.com/image-rs/image

1. clone 它
2. 看 `src/codecs/png.rs`(PNG 编解码)
3. 看 PngDecoder / PngEncoder
4. 可能的贡献:加单元测试 / 优化某个 chunk 的解析 / 加新 chunk 类型支持

## 15 · Rust / Arch 落地代码

完整可跑的 PNG 解码器(简化版,只支持 RGBA8 非隔行):

```rust
// src/main.rs
use std::fs::File;
use std::io::Read;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    // 读 PNG 文件
    let mut file = File::open("input.png")?;
    let mut data = Vec::new();
    file.read_to_end(&mut data)?;
    
    // 解码
    let image = decode_png(&data).map_err(|e| format!("decode failed: {}", e))?;
    
    println!("PNG: {}x{}, depth={}, color_type={}",
             image.width, image.height, image.bit_depth, image.color_type);
    println!("Pixels: {} bytes", image.pixels.len());
    Ok(())
}
```

Arch 工具链:

```bash
# 看 PNG 文件
sudo pacman -S xxd      # hex viewer
sudo pacman -S pngcheck  # PNG 验证
sudo pacman -S optipng   # PNG 优化
sudo pacman -S pngquant  # PNG 调色板压缩(有损降色)

# 看文件结构
xxd texture.png | head -5
# 输出:
# 00000000: 8950 4e47 0d0a 1a0a 0000 000d 4948 4452  .PNG........IHDR
# 00000010: 0000 0100 0000 0100 0806 0000 005b a37d  ............[.}
# 00000020: 1e00 0006 4944 4154 789c ...

# 验证
pngcheck -v texture.png
# 输出:
#   OK: texture.png (256x256, 32-bit, RGBA, non-interlaced, 93.0%)

# 优化压缩
optipng -o7 texture.png
# -o7 最高压缩级别(慢)
# 输出示例:
#   ** Processing: texture.png
#   256x256 pixels, 4x8 bits/pixel, RGBA
#   Input file size = 51234 bytes
#   Output file size = 38912 bytes (decrease = 24.0%)
```

排错:

```bash
# 1. "invalid signature"
#    原因:文件不是 PNG(可能是 JPEG),或传输破坏
#    排查:看前 8 字节是否 `89 50 4E 47 0D 0A 1A 0A`

# 2. "CRC mismatch"
#    原因:文件被错误编辑(可能有工具改了 chunk 数据没更新 CRC)
#    排查:用 pngcheck 找具体哪个 chunk 坏

# 3. 颜色错乱
#    原因:bit_depth 或 color_type 解析错
#    排查:打印 IHDR,确认 bpp 计算对

# 4. alpha 通道错乱
#    原因:tRNS chunk 没处理(对 indexed color 透明)
```

## 16 · 延伸阅读

本仓库本地:

- `days/phase-7/deep-dives/deflate-compression.md` — DEFLATE 算法
- `days/phase-7/deep-dives/asset-pipeline-architecture.md` — PNG 在资产管线中的角色

外部稳定 URL:

- W3C PNG 规范: https://www.w3.org/TR/png/
- libpng 文档: http://www.libpng.org/pub/png/libpng.html
- RFC 1950(ZLIB): https://datatracker.ietf.org/doc/html/rfc1950
- RFC 1951(DEFLATE): https://datatracker.ietf.org/doc/html/rfc1951
- Wikipedia PNG: https://en.wikipedia.org/wiki/Portable_Network_Graphics

真实开源源码:

- Rust png crate: https://github.com/image-rs/image-png
- libpng(C 标准): https://github.com/glennrp/libpng
- stb_image.h(单文件): https://github.com/nothings/stb/blob/master/stb_image.h
- spng(纯 C,快速): https://github.com/randy408/libspng
