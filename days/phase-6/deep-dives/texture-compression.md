# 纹理压缩:BCn / DXT / ETC / ASTC 的块状压缩与 GPU 解码

> 一张 4K 的 RGBA 纹理,如果不压缩,占 67 MB。一个 3D 游戏几百张纹理,直接爆显存。所以工业界**所有 GPU 都内置硬件纹理压缩**——CPU 编码一次,GPU 解码每个像素,固定压缩比、固定解码延迟。本文从 BC1(DXT1)讲到 ASTC,从块状压缩原理讲到 GPU 硬件解码路径,让你看懂 GPU Spec 里的 texture format 列表。

## 0 · 为什么需要专门的纹理压缩

你大概熟悉 zip / gzip 这种通用压缩。为什么不直接用 zip 压纹理,给 GPU 解压?

四个硬约束决定了**必须用专门的纹理压缩**:

1. **随机访问**:shader 可能只采样纹理的 (123, 456) 像素。zip 解压必须从头开始,解一整张图——无法。
2. **固定压缩比**:压缩后大小必须固定(或可预测),才能计算显存布局、Mip 偏移、纹理数组偏移。zip 的压缩比随机变化,无法。
3. **极简解码**:GPU 给纹理采样只有几个时钟周期预算。zip 的解压算法复杂,GPU 不可能实时跑。
4. **硬件管线**:纹理采样器(texture sampler)是 GPU 硬件单元,压缩格式必须直接对接它。

工业界的解决方案:**块状压缩**(block-based compression)。把图像分成 4×4 的块,每块独立压缩到固定字节(通常 8 或 16 字节)。GPU 采样时,只解压当前像素所在的块——O(1) 随机访问,固定大小,解码电路极简。

**主流格式族系**:

| 家族 | 来源 | 桌面 | 移动 | 压缩比 |
|---|---|---|---|---|
| S3TC / DXT / BC1-3 | S3 Graphics 1990s | OpenGL / D3D | ✗ | 4:1 ~ 6:1 |
| RGTC / BC4-5 | ATI / D3D10 | ✓ | ✗ | 2:1 ~ 4:1 |
| BPTC / BC6-7 | D3D11 | ✓ | ✗ | 3:1 |
| ETC1 / ETC2 | Ericsson | ✗ | OpenGL ES | 4:1 ~ 6:1 |
| ASTC | ARM 2012 | ✓(新硬件) | ✓ | 4:1 ~ 12:1(可调) |

**读完这一篇你能**:
- 解释 BC1 把 16 个像素压到 8 字节的算法
- 选择合适的纹理压缩格式(每个项目都要做这个决定)
- 用 Rust + `bcndecode` / `basis-universal` crate 压缩纹理
- 知道 ASTC 为什么是移动端和未来的主流

## 1 · 块状压缩:核心思想

### 4×4 块

把图像分成 4×4 的像素块(16 个像素一块)。每块独立压缩。压缩后每块的字节数固定:

- BC1(DXT1):8 字节 / 块 = 4 个块 / 32 字节 = 0.5 字节 / 像素(bpp)
- BC3(DXT5):16 字节 / 块 = 1 bpp
- BC7:16 字节 / 块 = 1 bpp(但质量更高)
- ASTC:8 字节 / 块(可配置块大小,4×4 到 12×12)= 0.89 ~ 8 bpp

对比未压缩的 RGBA8 = 32 bit / 像素 = 4 bpp。BC1 = 8:1 压缩,BC3 = 4:1 压缩。

### 颜色端点 + 索引

BC1 的核心想法:**每块只存 2 个"端点颜色"(color endpoints),然后每个像素存一个 2-bit 索引,指向端点的插值**。

```
块(16 个像素) → 2 个端点 color0, color1 + 16 个 2-bit 索引
```

每个像素根据索引,选择 4 个值之一:

- index 0 → color0
- index 1 → color1
- index 2 → (2*color0 + color1) / 3
- index 3 → (color0 + 2*color1) / 3

(对于不透明模式)

具体字节布局:8 字节 = 2 字节 color0(RGB565)+ 2 字节 color1(RGB565)+ 4 字节 16 个 2-bit 索引。

### 解码示例

块数据(8 字节):

```
color0 = RGB565 = 0xFFFF (白)
color1 = RGB565 = 0x0000 (黑)
索引: 0 1 2 3 0 1 2 3 0 1 2 3 0 1 2 3
```

解码后(16 像素):

```
白   黑   2/3 白   1/3 白
白   黑   2/3 白   1/3 白
白   黑   2/3 白   1/3 白
白   黑   2/3 白   1/3 白
```

每块只有 4 种颜色——所以块之间可能有可见突变。这就是为什么 BC1 在渐变 / 高频纹理上有 artifacts(瑕疵)。

### 1-bit Alpha 模式

BC1 还有一种模式:color0 > color1 时(按 16-bit 无符号比较),表示 4 个索引值。当 color0 ≤ color1 时,index 3 表示"完全透明",前 3 个值表示 color0、color1、1/2*(color0+color1)——只有 3 种颜色 + 透明。这样 BC1 可以存 1-bit alpha(像素要么不透明,要么完全透明)。

## 2 · BC3 / DXT5:加完整 Alpha

BC1 不能存完整 alpha(每像素只有 1 bit)。BC3(DXT5)解决方案:**再加一个独立的 BC4 块存 alpha**。

- 前 8 字节:alpha 通道(BC4 压缩,2 个 8-bit alpha 端点 + 16 个 3-bit 索引)
- 后 8 字节:RGB 通道(BC1 压缩)

总共 16 字节 / 块 = 1 bpp。

### BC4(只存单通道)

BC4 是 BC3 的 alpha 部分,独立成格式——用来存单通道数据(高度图、阴影 mask、灰度)。算法类似 BC1,但每个端点是 8-bit,索引 3-bit(所以每像素 8 种值,而不是 BC1 的 4 种)。

## 3 · BC5:双通道(法线贴图专用)

法线贴图只需要存 (x, y) 两个通道(z 重建)。BC5 = 两个独立 BC4 块——一个存 x,一个存 y。共 16 字节 / 块。

BC5 是法线贴图的标准压缩格式(在桌面)。

## 4 · BC6H:HDR

BC1/3/5 假设像素是 8-bit LDR。HDR 渲染用 float16(每通道 16 位浮点),需要专门格式。BC6H 应运而生:16 字节 / 块,2 个 16-bit 浮点端点 + 复杂的 partition 和 index 模式。

主要用于天空盒(HDR cubemap)、光源贴图、IBL prefiltered map。

## 5 · BC7:高质量 LDR

D3D11 引入,是 BC1/3 的"高质量替代"。16 字节 / 块,但支持:

- 多达 4 个 partition(每块再细分成几个区域,每区独立端点)
- RGB + Alpha 联合压缩(不是 BC3 那样分离)
- 更复杂的端点表达(8-bit 而不是 5/6-bit)

BC7 质量接近未压缩,是桌面 LDR 纹理的最佳选择(但编码慢)。

## 6 · ETC:移动端的 BC

ETC(Ericsson Texture Compression)是 OpenGL ES 标准的纹理压缩,移动端必备。

### ETC1

4×4 块,8 字节。每块存:

- 1 个"基础颜色"(RGB444)
- 1 个"修正表索引"(每像素 2-bit,加到基础色上)
- 1 个"翻转位"(决定块是水平分还是垂直分两半,各有独立基础色)

ETC1 不支持 alpha。

### ETC2

ETC1 的扩展,向后兼容(同样的字节布局,扩展的解码规则)。新增:

- 完整 alpha(独立模式)
- 改进压缩(R / G / B 通道各自有不同模式)

ETC2 是 OpenGL ES 3.0 标准的一部分。

## 7 · ASTC:未来的王者

ASTC(Adaptive Scalable Texture Compression)是 ARM 2012 年发布的新格式,**目标:取代 BC 和 ETC**。

### ASTC 的独特之处

1. **块大小可配置**:4×4 到 12×12 都行(BC 是固定 4×4)。块越大压缩比越高,质量越低。
2. **2D 和 3D 都支持**:3D ASTC 用于体纹理。
3. **质量比 ETC2/BC7 高**:同样 bpp 下,ASTC 的 PSNR(峰值信噪比)比所有前代高。
4. **HDR / LDR 都支持**:float16 一张图也能压。
5. **慢编码**:ASTC 编码器需要搜索多种 mode 和 partition,编码时间长。但解码快。

### ASTC 块结构

固定 16 字节 / 块(128 bit),但块大小可选:

- 4×4 块:128 bit / 16 像素 = 8 bpp
- 6×6 块:128 bit / 36 像素 = 3.56 bpp
- 8×8 块:128 bit / 64 像素 = 2 bpp
- 12×12 块:128 bit / 144 像素 = 0.89 bpp

128 bit 里包含:端点、权重索引、partition 模式、双平面模式等。

### 移动 / 桌面支持

| 平台 | BC1-7 | ETC1/2 | ASTC |
|---|---|---|---|
| Desktop D3D11+ | ✓ | ✗ | ✓(部分) |
| Desktop OpenGL | ✓ | ✗ | ✓(4.6+) |
| OpenGL ES 3.0+ | ✗ | ✓ | ✓(扩展) |
| iOS | ✗ | ✓ | ✓(GPU Family 2+) |
| Android | ✗ | ✓ | ✓(几乎所有现代设备) |
| Vulkan | ✓ | ✓ | ✓ |

ASTC 是**唯一一个跨平台的现代格式**。

## 8 · 跨格式统一:Basis Universal

你做了一个游戏,想发布桌面 + 移动。桌面要 BC7,移动要 ASTC。难道要存两套纹理?

**Basis Universal** 解决方案:存一种"中间格式"(basis 编码),运行时根据设备转码到 BC7 / ASTC / ETC。这个"超集"格式已经标准化为 **KTX2** 容器。

```rust
// 用 basis-universal crate
use basis_universal::{BasisEncoder, TextureFormat};

let mut encoder = BasisEncoder::new();
encoder.add_image(&rgba_pixels, w, h);
encoder.encode();

// 写到 KTX2 文件
encoder.write_ktx2("texture.ktx2")?;

// 运行时(游戏启动):
// 1. 加载 KTX2
// 2. 根据设备能力,转码到 BC7 / ASTC / ETC2
// 3. 上传到 GPU
```

## 9 · Rust 实现:压缩一个 PNG 到 BCn

```toml
# Cargo.toml
[dependencies]
image = "0.25"
bcndecode = "0.2"  # BCn 解码(检查编码结果)
texture2dds = "0.4"  # 编码
```

```rust
// src/main.rs
use image::GenericImageView;

fn main() {
    let img = image::open("input.png").unwrap();
    let (w, h) = img.dimensions();
    let rgba = img.to_rgba8();
    
    // 转 BC7(简化,实际用 GPU 加速的库如 ispc-texcomp)
    let bc7_data = encode_bc7(&rgba, w, h);
    
    // 写到 KTX2 或 DDS 文件
    std::fs::write("output.bc7", bc7_data).unwrap();
    println!("BC7 编码完成,大小 {} 字节", std::fs::metadata("output.bc7").unwrap().len());
}

fn encode_bc7(rgba: &image::RgbaImage, w: u32, h: u32) -> Vec<u8> {
    // 实际项目用 ispc-texcomp 或 compressonator
    // 这里展示算法骨架
    let block_w = (w + 3) / 4;
    let block_h = (h + 3) / 4;
    let mut output = vec![0u8; (block_w * block_h * 16) as usize];
    
    for by in 0..block_h {
        for bx in 0..block_w {
            // 提取 4x4 像素块
            let mut block = [[0u8; 4]; 16];
            for py in 0..4 {
                for px in 0..4 {
                    let x = (bx * 4 + px).min(w - 1);
                    let y = (by * 4 + py).min(h - 1);
                    block[(py * 4 + px) as usize] = rgba.get_pixel(x, y).0;
                }
            }
            // 编码这 16 像素到 16 字节(实际 BC7 算法)
            let encoded = encode_bc7_block(&block);
            let offset = ((by * block_w + bx) * 16) as usize;
            output[offset..offset + 16].copy_from_slice(&encoded);
        }
    }
    output
}

fn encode_bc7_block(block: &[[u8; 4]; 16]) -> [u8; 16] {
    // 简化:实际 BC7 编码器搜索多种 mode 和 partition
    // 这里返回全零,真实实现见 ISPC texcomp
    [0u8; 16]
}
```

## 10 · 在 OpenGL / Vulkan 里上传压缩纹理

### OpenGL

```rust
unsafe {
    gl.compressed_tex_image_2d(
        glow::TEXTURE_2D,
        0,
        glow::COMPRESSED_RGBA_BPTC_UNORM as i32,  // BC7
        width, height, 0,
        compressed_data.len() as i32,
        Some(compressed_data),
    );
}
```

关键点:

- 第 3 参数 `internalformat` 必须是压缩格式常量(`COMPRESSED_RGBA_BPTC_UNORM` = BC7)
- 最后一个参数是压缩后的字节数(不是 width * height * 4)

### Vulkan

```rust
let format = vk::Format::BC7_UNORM_BLOCK;  // 或 ASTC_6X6_UNORM_BLOCK 等

let create_info = vk::ImageCreateInfo::builder()
    .format(format)
    .extent(vk::Extent3D { width, height, depth: 1 })
    .build();
```

Vulkan 的格式名直接说明一切:`BC7_UNORM_BLOCK`、`ASTC_6X6_SRGB_BLOCK`、`ETC2_R8G8B8_UNORM_BLOCK`。

## 11 · 在 GPU 内部:解码电路

GPU 的纹理采样器硬件单元长这样(简化):

```
sample(uv) →
  1. 算 uv 落在哪个 4x4 块(block_idx)
  2. 从显存读这个块(8 或 16 字节,固定大小)
  3. 解压块:解析端点、索引
  4. 根据块内 uv(0..3),查索引得颜色
  5. (可选)mip、各向异性过滤、双线性插值
  6. 返回颜色给 shader
```

整个过程在 GPU 硬件里 1-2 个时钟周期。这就是为什么 GPU 能"实时"解压——它不是软件解压,是定制硬件。

## 12 · 关联 Day

- **铺垫**:Day 290 纹理基础;Day 295 mipmap
- **当天**:本篇是 Phase 6 纹理压缩专题
- **后续**:Day 415 法线贴图压缩(BC5);Day 480 资产打包(KTX2 容器)

## 13 · 变式训练

### Lv1 · 概念辨析

**题**:为什么 GPU 纹理压缩不能像 zip 那样"流式"解压(只读一段就能解)?

**参考解答**:两个原因:
1. **随机访问**:shader 采样 `(123, 456)` 像素,zip 要从头读才能到这位置——每像素采样都从头解,完全无法用。块压缩每个块独立,任何像素都能 O(1) 定位
2. **可预测大小**:GPU 显存布局、mip 链、纹理数组都依赖"块大小固定"——压缩后字节数必须能从 (width, height) 算出。zip 压缩比变化,无法预算

### Lv2 · 动手实践

**题**:用 `compressonator` 或 `ispc-texcomp` 把一张 1024×1024 PNG 压成 BC1、BC3、BC7,比较文件大小和视觉质量。

**参考解答**:

```bash
# 装 compressonator
sudo pacman -S compressonator  # 或 AUR

# 压缩(命令行)
compressonator -m BC1 input.png output_bc1.dds
compressonator -m BC7 input.png output_bc7.dds

# 看大小
ls -lh output_*.dds
# 输出示例:
#   output_bc1.dds  533K   (8 bpp,原 1024*1024*4 = 4MB,压缩 8:1)
#   output_bc3.dds  1.1M   (16 bpp,压缩 4:1)
#   output_bc7.dds  1.1M   (16 bpp,质量更高)

# 看视觉质量
compressonator output_bc1.png reference.png diff.png
# diff.png 显示差异,几乎黑表示低差异(好)
```

### Lv3 · 迁移设计

**题**:设计一种"专为深色背景下的亮色 UI 设计"的压缩格式。考虑:UI 的边缘锐利、纯色块多、透明边缘硬。你会怎么做?

**提示**:BC1 在锐利边缘有 artifact,因为每块只有 4 个颜色。考虑增加一个"alpha mask"模式或专门的边缘编码。

### Lv4 · 开源贡献

**题**:Basis Universal 是开源的纹理压缩超集,GitHub: https://github.com/BinomialLLC/basis_universal

1. clone 它
2. 看它的 transcoder(transcoder_basisu.cpp)
3. 理解它怎么从 basis 中间格式转到 BC7 / ASTC
4. 可能的贡献:加一个新的 target format(如新的 AV1 图像编码 AVM),或改进文档

## 14 · Rust / Arch 落地代码

完整的"PNG → KTX2(BC7) → 上传到 GPU"管线:

```rust
// Cargo.toml:
// [dependencies]
// image = "0.25"
// basis_universal = "0.3"
// glow = "0.14"

use image::GenericImageView;
use glow::*;

fn main() {
    let img = image::open("texture.png").unwrap();
    let (w, h) = img.dimensions();
    let rgba: Vec<u8> = img.to_rgba8().into_raw();

    // 1. 用 basis-universal 编码到超集格式
    let basis_data = encode_to_basis(&rgba, w, h);
    std::fs::write("texture.basis", &basis_data).unwrap();
    println!("basis 编码完成:{} 字节", basis_data.len());

    // 2. 运行时转码到 BC7(假设已经知道设备支持 BC7)
    let bc7_data = transcode_basis_to_bc7(&basis_data);
    println!("BC7 转码:{} 字节", bc7_data.len());

    // 3. 上传到 GPU(简化)
    let gl = unsafe { Context::from_loader_function(|s| /* get_proc_address */) };
    unsafe {
        let tex = gl.create_texture().unwrap();
        gl.bind_texture(TEXTURE_2D, Some(tex));
        gl.compressed_tex_image_2d(
            TEXTURE_2D, 0,
            COMPRESSED_RGBA_BPTC_UNORM as i32,  // BC7
            w as i32, h as i32, 0,
            bc7_data.len() as i32,
            Some(&bc7_data),
        );
    }
}

fn encode_to_basis(rgba: &[u8], w: u32, h: u32) -> Vec<u8> {
    // 简化:实际用 basis_universal::BasisEncoder
    rgba.to_vec()  // 占位
}

fn transcode_basis_to_bc7(basis: &[u8]) -> Vec<u8> {
    // 简化:实际用 basis_universal::Transcoder
    basis.to_vec()
}
```

Arch 工具链:

```bash
# 装纹理工具
sudo pacman -S compressonator       # GUI/CLI BCn 编码
sudo pacman -S astc-encoder         # ASTC 编码
yay -S ispc-texcomp                 # Intel 的快速 BC 编码(AUR)

# 看 GPU 支持哪些压缩格式
sudo pacman -S mesa-utils
glxinfo | grep -i texture
# 输出示例:
#   GL_COMPRESSED_RGBA_BPTC_UNORM: yes (BC7)
#   GL_COMPRESSED_RGB8_ETC2: yes
#   GL_COMPRESSED_RGBA_ASTC_4x4_KHR: yes

# Vulkan 支持查询
sudo pacman -S vulkan-tools
vulkaninfo | grep -i format | head -50

# 编码一个纹理
compressonator -m BC7 -q 0.95 input.png output.dds
# -m 模式, -q 质量(0..1,BC7 用 0.95 起步)

# ASTC
astcenc -cl input.png output.astc 6x6 -medium
# 6x6 = 块大小, -medium = 编码质量档
```

排错:

```bash
# 1. 纹理在 GPU 里看起来怪怪的(块状 artifact)
#    可能:压缩比设太低(块太大)
#    解决:换更小块(ASTC 4x4 而不是 12x12),或用 BC7

# 2. 纹理完全黑
#    可能:internalformat 错了,把 BC1 用成 BC7 的常量
#    排查:用 renderdoc 抓帧,看 Texture Inspector 显示的格式

# 3. 纹理在某些设备上跑不起来
#    可能:设备不支持这个格式(比如移动端没 BC7)
#    解决:用 Basis Universal 转码到该设备支持的格式
```

## 15 · 延伸阅读

本仓库本地:

- `days/phase-6/deep-dives/normal-mapping.md` — BC5 是法线贴图的标准
- `days/phase-7/deep-dives/asset-pipeline-architecture.md` — 纹理打包到 KTX2

外部稳定 URL:

- Khronos 纹理压缩格式参考: https://www.khronos.org/opengl/wiki/Texture_Compression
- Microsoft BCn 格式: https://learn.microsoft.com/en-us/windows/win32/direct3d11/texture-block-compression-in-direct3d-11
- ASTC 格式规范: https://developer.arm.com/documentation/101137/latest
- Basis Universal: https://github.com/BinomialLLC/basis_universal
- KTX2 规范: https://registry.khronos.org/KTX/specs/2.0/ktxspec.v2.html

真实开源源码:

- ISPC texcomp(BCn 快速编码): https://github.com/GameTechDev/ISPC-TexComp
- ARM ASTC 编码器: https://github.com/ARM-software/astc-encoder
- Basis Universal: https://github.com/BinomialLLC/basis_universal
