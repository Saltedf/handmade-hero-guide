---
title: "Asset Compression"
subtitle: "LZ77/LZ4/RLE basics, when to compress, in-memory vs disk"
type: deep-dive
phase: 4
domains: [game, rust]
duration: "2-3h"
---

# Asset Compression

> Phase 4 的 .hha 文件目前是 raw 数据。如果加压缩,游戏 asset 能缩小 50-90%,下载快、磁盘省。这篇 deep-dive 讲压缩基础:LZ77 原理、LZ4 / Zstd 选型、何时压缩何时不压缩、内存 vs 磁盘压缩 trade-off。

## 0 /// 为什么压缩

游戏 asset 大小:

| Asset | Raw 大小 | 压缩后 |
|---|---|---|
| 1024x1024 RGBA8 texture | 4 MB | 1 MB(BC1) |
| 1024x1024 PNG | 4 MB raw | 500 KB |
| 3 min Ogg Vorbis 音频 | 30 MB raw PCM | 3 MB |
| 1 min MP3 | 10 MB raw | 1 MB |
| Text script | 1 MB | 100 KB(已 zip-able) |

总资产压缩后可能小 5-10 倍。玩家下载时间 / 磁盘空间大省。

## 1 /// 压缩分类

### Lossless(无损)

- 解压后 100% 还原
- 用于代码 / 数据 / 部分 asset(模型 / 文本)
- 算法:LZ77 / Huffman / Deflate / LZ4 / Zstd

### Lossy(有损)

- 解压后近似,丢弃信息换压缩率
- 用于图像(JPEG)/ 音频(MP3 / Opus)/ 视频(H.264)
- 算法:DCT(余弦变换)/ DWT(小波)

游戏 asset 两者都用:

- 纹理:lossy(BCn / ETC / ASTC 硬件格式)
- 模型:lossless(mesh 不能丢)
- 音频:lossy(Ogg / Opus)
- 文本:lossless

## 2 /// LZ77 原理

LZ77 是基础算法,几乎所有 lossless 压缩都是其变种。

### 滑动窗口

```
... [back-reference window] [look-ahead buffer] ...
... | a b r a c a d a b r | a ...
```

要压缩当前位置 "abra":

- 在 back-reference window 找 "abra" → 找到 offset 7 之前
- 输出 (offset, length, next_char) = (7, 4, ...)
- 解压时按 offset 拷贝 length 字节

### 例子

原始:`"abracadabra"`(11 字节)

LZ77 编码:

```
(0,0,'a')(0,0,'b')(0,0,'r')(0,0,'a')(0,0,'c')(0,0,'a')(0,0,'d')(7,4,'\0')
```

每 token 占 3-4 字节(假设用 1 字节 offset/length)。

总:8 token × 3 字节 = 24 字节 → 比原 11 字节大!LZ77 对小数据无效。

但长字符串效果显著:`"aaaaaaaaaa"` 编码成 `(0,0,'a')(1, 9, '\0')`,2 token × 3 字节 = 6 字节,vs 原 10 字节。

### 实际变种

- **LZSS**:LZ77 + 位图标记哪些是 literal 哪些是 reference
- **DEFLATE**(gzip):LZ77 + Huffman 编码
- **LZ4**:LZ77 + 简化 Huffman,极快
- **Zstd**:LZ77 + Finite State Entropy + 大窗口,现代

## 3 /// LZ4 vs Zstd vs gzip

| 算法 | 压缩比 | 压缩速度 | 解压速度 | 何时用 |
|---|---|---|---|---|
| LZ4 | 2-3x | 极快(500 MB/s) | 极快(2 GB/s) | 实时(streaming) |
| Zstd -1 | 2.5-3x | 快(300 MB/s) | 极快(1.5 GB/s) | 平衡 |
| Zstd -19 | 3-4x | 慢 | 极快 | 一次性 build |
| gzip | 2.5-3x | 慢 | 慢(200 MB/s) | 旧兼容 |
| bzip2 | 3-4x | 极慢 | 中 | 大文件归档 |
| LZMA / xz | 4-5x | 极慢 | 中 | 极致压缩 |

游戏开发推荐:**LZ4 实时**(asset streaming)+ **Zstd build 时**(最终打包)。

## 4 /// RLE(Run-Length Encoding)

最简单的压缩:连续相同字节合并。

```
"aaaaabbbbcccc" → (5, 'a')(4, 'b')(4, 'c')
```

13 字节 → 6 字节。

**适合**:有大段重复(像素图、mask)。**不适合**:几乎无重复的随机数据(图像 / 音频已压缩)。

RLE 极快(O(N)),但通常压缩比低。是入门压缩的好例子。

## 5 /// Huffman 编码

变长编码,频率高的字符用短码。

```
原始:abracadabra
频率:a:5, b:2, r:2, c:1, d:1
Huffman codes:a=0, b=10, r=110, c=1110, d=1111

编码:0 10 110 0 1110 0 1111 0 10 110 0 = 23 bit ≈ 3 字节
原 11 字节 ASCII = 88 bit → 3.5x 压缩
```

Huffman + LZ77 = DEFLATE(gzip)。

## 6 /// 纹理压缩(硬件)

纹理压缩**特殊**:GPU 直接读压缩格式,解压在 shader 单像素。无 CPU 解压。

格式:

- **BC1-7**(DirectX / Vulkan):Windows / 跨平台
- **ETC1/2**(OpenGL ES):移动
- **ASTC**(现代):iOS / Android / 现代 GPU

| 格式 | 压缩比 | 质量 |
|---|---|---|
| BC1(RGB) | 8:1 | 中 |
| BC3(RGBA) | 4:1 | 中 |
| BC7 | 4:1 | 高 |
| ASTC | 4-12:1 可调 | 极高 |

游戏纹理**必须**用硬件压缩格式——CPU 解压 + 上传太慢。

build 时压缩(`compressonator` / `nvtt`)。

## 7 /// 音频压缩

| 格式 | 压缩比 | 质量 | 解压成本 |
|---|---|---|---|
| PCM(raw) | 1:1 | 完美 | 0 |
| FLAC | 2:1 | 无损 | 低 |
| Vorbis(Ogg) | 10:1 | 好 | 中 |
| Opus | 12:1 | 极好 | 中 |
| MP3 | 10:1 | 好 | 中 |
| ADPCM(IMA) | 4:1 | 中 | 极低 |

游戏音效用 **ADPCM**(极低解压成本,适合大量并发)。BGM 用 **Opus** / **Vorbis**。

## 8 /// 在哪里压缩

### Build 时

`.hha` 整体压缩,玩家下载受益。

```
uncompressed.hha → Zstd → game.hha
```

### 内存中

运行时解压 asset 到内存,内存占用反而**增加**(解压数据 + 压缩数据并存)。除非:

- asset 很大(纹理 4K,内存吃紧)
- 用 stream 解压(边读边解压,不全存)

### GPU 端

硬件压缩纹理上传 GPU,GPU 内存占用小。**游戏开发必做**。

## 9 /// Rust 压缩 crate

```rust
// Zstd
use zstd::stream::{Encoder, Decoder};

let compressed = {
    let mut e = Encoder::new(Vec::new(), 3)?;
    e.write_all(data)?;
    e.finish()?
};

let decompressed = {
    let mut d = Decoder::new(&compressed[..])?;
    let mut s = Vec::new();
    d.read_to_end(&mut s)?;
    s
};

// LZ4
use lz4::{EncoderBuilder, Decoder};

let mut e = EncoderBuilder::new().level(4).build(Vec::new())?;
e.write_all(data)?;
let compressed = e.finish().0;

// RLE(简单)
fn rle_encode(data: &[u8]) -> Vec<u8> {
    let mut out = Vec::new();
    let mut i = 0;
    while i < data.len() {
        let byte = data[i];
        let mut count = 1;
        while i + count < data.len() && data[i + count] == byte && count < 255 {
            count += 1;
        }
        out.push(count);
        out.push(byte);
        i += count;
    }
    out
}
```

## 10 /// 何时压缩

| 场景 | 压缩? |
|---|---|
| 大 asset(纹理 / 模型 / 音频) | 是(build 时) |
| 已压缩格式(PNG / JPEG / MP3) | 否(重复压缩反而变大) |
| 小文件(< 1 KB) | 否(overhead 大于收益) |
| 实时数据(网络流) | LZ4(快) |
| 归档 / 一次性 | Zstd max(慢但比高) |

## 11 /// 资源

- zstd crate:https://github.com/gyscos/zstd-rs
- lz4 crate:https://github.com/10XGenomics/lz4-rs
- LZ4 spec:https://github.com/lz4/lz4/blob/dev/doc/lz4_Frame_format.md
- Zstd algorithm:https://github.com/facebook/zstd/blob/dev/doc/zstd_compression_format.md
- BCn formats:https://www.reedbeta.com/blog/understanding-bcn-texture-compression-formats/

## 12 /// 练习

### Lv1

实现 RLE encode / decode。对比在 100 万字节随机数据 vs 100 万字节重复数据上的压缩比。

### Lv2

用 Zstd crate 压缩 .hha 文件。压缩前后大小对比,解压时间测量。

### Lv3

实现 streaming 解压:从磁盘读 .hha,Zstd 流式解压,边读边解。对比一次性解压的内存占用。

### Lv4

读 zstd-rs 或 lz4-rs 的 `src/lib.rs`,看它们如何包装 C 库的 unsafe FFI。提一个 doc PR。
