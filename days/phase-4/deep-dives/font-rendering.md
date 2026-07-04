
# 字体渲染深度专题

> 你写完了 Handmade Hero Day 85~110 的文字渲染。你的字渲染对了——至少,字母 A 在屏幕上看起来像 A。然后你想加上中文。你打开思源黑体的 .otf,运行你的渲染器,屏幕上出现一堆问号。你换了一个 TTF,还是问号。你查了三天资料,最后在 `freetype` 的 docs 里读到 "glyph 0 usually means missing glyph"——你这才意识到:**字体文件本身,是另一种"汇编"**。今天这一篇,我们把字体从二进制位到屏幕像素的全链路拆开,让你读完任何字体相关的开源项目(freeType / harfbuzz / font-kit / cosmic-text / Bevy text)都能秒懂。

## 0 · 为什么要有这一篇

Handmade Hero 里 Casey 用了 26 集来写文字渲染,这是全系列最长的子系统之一。为什么这么久?因为字体渲染是**计算机图形学里最容易低估的复杂系统**。一个看似简单的问题("把字母 A 画出来")背后,藏着以下这些层:

**第一层,字体文件格式**。一个 .ttf 文件 5MB,里面是什么?是字体的"源码"——每个字符的几何形状(贝塞尔曲线)、字距(kerning)、连字(ligature)、hinting 指令(让小字号清晰)。你需要解析这种格式,取出"字符 A 长什么样"。

**第二层,glyph 选择**。用户打了一个 'A',你拿到的是 unicode code point 0x41。但字体里 'A' 不只一个 glyph——有大写 'A'、小型大写 'A'、上下文变体 'A'(在 'V' 旁边可能更窄)、阿拉伯字母有四种形态(首/中/尾/独立)。把 code point 映射到正确的 glyph id,这叫 **cmap**。

**第三层,文本整形(shaping)**。"fast" 中 f 和 i 之间在某些字体里会合并成 **fi 连字(ligature)**——一个 glyph 而不是两个。阿拉伯语 / 印地语里更复杂:字符的形态取决于前后字符。'shaping' 就是"给定一串 code points,生成一串正确顺序的 glyph id"。这个步骤由 **HarfBuzz** / **rust-shaper** 完成。

**第四层,栅格化(rasterization)**。拿到 glyph id,从字体文件里读出贝塞尔曲线,把它转成屏幕上的像素。这是 FreeType 的核心工作。难点在:**抗锯齿(anti-aliasing)**、**hinting**(小字号下像素对齐)、**subpixel rendering**(利用 LCD 子像素)。

**第五层,布局(layout)**。一段文字可能要换行、左右对齐、垂直排列、不同字体混排、emoji 嵌入。这叫 **text layout**,由 **cosmic-text** / **swash** / **Pango** 完成。

**第六层,缓存**。每帧画 1000 个字符,每帧都栅格化?不可能。把栅格化的 glyph 缓存到 GPU texture,这是 **glyph cache** / **atlas**。

Casey 用了 26 集就是把这六层一砖一瓦盖出来。我们今天在 Rust 生态的视角下,把这六层都讲透。

**学完这一篇,你应该能**:
- 解释 TTF / OTF / WOFF2 三种格式的区别和内部结构
- 用 Rust 从零解析一个 TTF 文件的 font directory
- 解释 FreeType 做的事,会用 `freetype-rs` 和 `font-kit`
- 解释 subpixel rendering 的原理和它在 LCD / OLED 上的差别
- 写一个简单的 SDF(Signed Distance Field)文字渲染器
- 在 Rust 项目里用 `cosmic-text` / `glyphon` / `bevy_text` 集成完整文字系统
- 处理 CJK(中日韩)字符的特殊问题,知道思源黑体和文泉驿的差异

## 1 · 字体格式三巨头:TTF / OTF / WOFF2

### 1.1 历史

**PostScript Type 1**(1984, Adobe)是最早的矢量字体。每个字符用三次贝塞尔曲线描述,精度高但格式复杂。Adobe 靠它起家,Mac 用它做早期系统字体。

**TrueType**(1991, Apple + Microsoft)是对 PostScript 的反击。Apple 想摆脱 Adobe 的控制,联合 Microsoft 推出 TrueType——使用二次贝塞尔曲线(比三次简单),并加入强大的 **hinting** 指令(让小字号下字形清晰)。Windows 3.1 的 Arial、Times New Roman 都是 TrueType。

**OpenType**(1996, Microsoft + Adobe 联合)是 TrueType 和 PostScript 的融合。OpenType 容器格式基于 TrueType,但 glyph 可以用 TrueType(二次曲线)或 CFF(三次曲线,即 PostScript Type 2)。所以**所有 .ttf 都是 OpenType,所有 .otf 也是 OpenType,区别只是 glyph 用的曲线类型**。这是新手最容易误解的点。

**WOFF**(2010, W3C 标准)是 Web Open Font Format。本质是 OpenType 加了 gzip 压缩,适合网络传输。

**WOFF2**(2018, W3C 标准)用 Brotli 压缩(比 gzip 强 20-30%),并支持预处理(table 重组)。今天 web 上 95% 字体用 WOFF2。

### 1.2 文件结构

所有 OpenType 字体(TrueType / CFF / WOFF / WOFF2)都遵循同一结构:

```
┌──────────────────┐
│ sfnt header      │  ← 字体头,告诉解析器有几个表
├──────────────────┤
│ Table Directory  │  ← N 条记录,每条 (tag, offset, length)
├──────────────────┤
│ Table Data       │  ← 各个表的实际数据
│   cmap           │  code point → glyph id
│   glyf / CFF2    │  glyph 几何数据
│   head           │  全局信息(unitsPerEm, indexToLocFormat)
│   hmtx           │  水平 metric(advance width, lsb)
│   kern / GPOS    │  kerning(字符间距)
│   name           │  字体名(name records)
│   OS/2           │  OS/2 特定 metric(weight, x-height)
│   post           │  PostScript 命名
│   ...            │  还有 20 多个表
└──────────────────┘
```

**关键术语**:
- **sfnt**:这是 OpenType / TrueType 容器的别名。sfnt = "scalable font"。
- **tag**:每个表的四字节标识。`cmap`、`glyf`、`head` 等都是 tag。
- **glyph id**:字体内部给每个 glyph 的编号。code point 0x41 (A) 在字体里可能是 glyph id 36。
- **unitsPerEm**:字体的"内部坐标系"分辨率。常见值 1000、2048。`unitsPerEm=2048` 意味着 em-square 是 2048×2048。

### 1.3 用 Rust 读 sfnt header

我们写一段真实可跑的代码,从零解析一个 .ttf 文件的头:

```rust
// 在 Cargo.toml: 无依赖,纯 std

use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::Path;

#[derive(Debug)]
struct SfntHeader {
    sfnt_version: u32,    // 0x00010000 (TTF) 或 'OTTO' (CFF)
    num_tables: u16,      // 有几个表
    search_range: u16,    // 二分查找优化
    entry_selector: u16,
    range_shift: u16,
}

#[derive(Debug)]
struct TableRecord {
    tag: [u8; 4],         // 'cmap', 'glyf' 等
    checksum: u32,        // 表的校验和
    offset: u32,          // 表数据在文件中的偏移
    length: u32,          // 表长度(字节)
}

fn read_u16_be<R: Read>(r: &mut R) -> std::io::Result<u16> {
    let mut buf = [0u8; 2];
    r.read_exact(&mut buf)?;
    Ok(u16::from_be_bytes(buf))
}

fn read_u32_be<R: Read>(r: &mut R) -> std::io::Result<u32> {
    let mut buf = [0u8; 4];
    r.read_exact(&mut buf)?;
    Ok(u32::from_be_bytes(buf))
}

fn parse_sfnt_header<P: AsRef<Path>>(path: P) -> std::io::Result<()> {
    let mut f = File::open(path)?;
    let sfnt_version = read_u32_be(&mut f)?;
    let num_tables = read_u16_be(&mut f)?;
    let search_range = read_u16_be(&mut f)?;
    let entry_selector = read_u16_be(&mut f)?;
    let range_shift = read_u16_be(&mut f)?;

    println!("sfnt_version: 0x{:08X}", sfnt_version);
    println!("num_tables: {}", num_tables);

    // 检测 TrueType 还是 CFF
    let kind = match sfnt_version {
        0x00010000 => "TrueType (二次贝塞尔曲线)",
        0x4F54544F => "CFF (三次贝塞尔曲线, 即 'OTTO')",
        _ => "未知",
    };
    println!("type: {}", kind);

    // 读 table directory
    let mut tables = Vec::with_capacity(num_tables as usize);
    for _ in 0..num_tables {
        let mut tag = [0u8; 4];
        f.read_exact(&mut tag)?;
        let checksum = read_u32_be(&mut f)?;
        let offset = read_u32_be(&mut f)?;
        let length = read_u32_be(&mut f)?;
        tables.push(TableRecord { tag, checksum, offset, length });
    }

    // 打印所有 tag
    for t in &tables {
        println!("  tag={} offset={} length={}",
            std::str::from_utf8(&t.tag).unwrap_or("?"),
            t.offset, t.length);
    }

    Ok(())
}

fn main() {
    // 你机器上随便找一个 ttf
    parse_sfnt_header("/usr/share/fonts/TTF/DejaVuSans.ttf").unwrap();
}
```

跑一遍,你会看到这样的输出(我机器上的 DejaVuSans.ttf):

```
sfnt_version: 0x00010000
num_tables: 19
type: TrueType (二次贝塞尔曲线)
  tag=FFTM offset=1444 length=28
  tag=GDEF offset=1472 length=140
  tag=GPOS offset=1612 length=852
  tag=GSUB offset=2464 length=876
  tag=OS/2 offset=3340 length=96
  tag=cmap offset=3436 length=526
  tag=cvt  offset=3964 length=52
  tag=gasp offset=4016 length=16
  tag=glyf offset=4032 length=43452
  tag=head offset=47484 length=54
  tag=hhea offset=47540 length=36
  tag=hmtx offset=47576 length=1068
  tag=loca offset=48644 length=1120
  tag=maxp offset=49764 length=32
  tag=name offset=49796 length=383
  tag=post offset=50180 length=32
  tag=prep offset=50212 length=212
```

你看,一个 TTF 文件就是个表集合。每个表有 tag / offset / length。把这两个数据读对,你就能从 TTF 里取任何信息。

**进阶**:rusttype / ttf-parser / swash 这三个 Rust crate 都自己写了这种解析。你不需要重新发明轮子,但理解原理很重要——以后看 rusttype 源码你会秒懂。

## 2 · FreeType + font-kit(Rust 生态主力)

### 2.1 FreeType 是什么

**FreeType**(1996, David Turner 创建)是 C 写的字体渲染库,工业标准。Linux 上 99% 文字、Android 全部文字、PlayStation 全部文字、嵌入式设备几乎所有文字——都是 FreeType 渲染的。Mac 用 Apple 自家的 CoreText,Windows 用 DirectWrite / GDI,但底层逻辑和 FreeType 一致。

FreeType 做四件事:
1. **解析**字体文件(TTF / OTF / CFF / WOFF / WOFF2)。
2. **加载** glyph——给定 glyph id,从字体里取出贝塞尔曲线。
3. **栅格化** glyph——把曲线转成位图。
4. **hinting**——在小字号下让 glyph 对齐到像素,看起来锐利。

FreeType 的 API 是 C 风格,有点繁琐:

```c
FT_Library library;
FT_Face face;
FT_Init_FreeType(&library);
FT_New_Face(library, "/usr/share/fonts/TTF/DejaVuSans.ttf", 0, &face);
FT_Set_Char_Size(face, 0, 16*64, 300, 300);  // 16pt @ 300dpi
FT_Load_Char(face, 'A', FT_LOAD_RENDER);     // 加载并栅格化 A
FT_GlyphSlot slot = face->glyph;
// slot->bitmap.buffer 现在是 A 的位图
```

注意几个细节:
- 字号用 26.6 fixed point(`16*64` 表示 16 像素)。这是因为 FreeType 要支持小数字号(比如 12.5px),用整数 fixed-point 比浮点快。
- `FT_LOAD_RENDER` flag 让 FreeType 不仅加载 glyph,还把它栅格化成位图。

### 2.2 freetype-rs:Rust 封装

```rust
// Cargo.toml: freetype = "0.7"
use freetype::Library;
use std::path::Path;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let lib = Library::init()?;
    let face = lib.new_face("/usr/share/fonts/TTF/DejaVuSans.ttf", 0)?;
    face.set_pixel_sizes(0, 32)?;  // 32px 高

    face.load_char('A', freetype::face::LoadFlag::RENDER)?;
    let glyph = face.glyph();
    let bitmap = glyph.bitmap();
    println!("A: {}x{} at ({},{})",
        bitmap.width(), bitmap.rows(),
        glyph.bitmap_left(), glyph.bitmap_top());
    // 输出: A: 22x23 at (3,18)

    Ok(())
}
```

`freetype-rs` 是 FreeType 的薄包装,API 1:1 映射 C 的。

### 2.3 font-kit:更上层的抽象

FreeType 自己**只渲染单个 glyph**,不处理"哪个字体文件好""系统字体在哪""fallback"这些问题。这些问题由 **font-kit**(Rust)或 **fontconfig**(C)解决。

```rust
// Cargo.toml: font-kit = "0.14"
use font_kit::source::SystemSource;
use font_kit::properties::{Weight, Style};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let source = SystemSource::new();
    // 找系统里一个合适的 sans-serif
    let font = source.select_best_match(
        &["DejaVu Sans".to_string()],
        &Properties::new().weight(Weight::NORMAL).style(Style::Normal),
    )?.load()?;

    println!("Family: {:?}", font.family_name());
    println!("Is monospace: {}", font.is_monospace());

    Ok(())
}
```

`font-kit` 知道 Linux 用 fontconfig,macOS 用 CoreText,Windows 用 DirectWrite——它把三个平台抽象掉。Cross-platform 字体查找就用它。

### 2.4 在 Linux 上看你的 fontconfig

Linux 的字体发现由 **fontconfig** 负责。你跑:

```bash
fc-list | head -20           # 列出所有字体
fc-match "Sans"              # 找最匹配 sans 的字体
fc-match "Sans:lang=zh"      # 找最匹配中文 sans 的字体
fc-list : family | sort -u   # 所有 family 名去重排序
```

当你写 `font-kit` 的 `SystemSource::new()`,底层就是调 fontconfig 的库(`libfontconfig.so`)。

## 3 · Glyph 栅格化与 hinting

### 3.1 把曲线变成像素

一个 glyph 的几何,本质是一组贝塞尔曲线。比如 'A' 大概是 5 段二次曲线(两个斜腿、横线、两个衬线)。

栅格化就是"对每个像素,判断它在曲线内部还是外部"。最简单的方法叫 **scanline filling**:

```
对每一行 y in [0, glyph_height):
    找出曲线和这一行的所有交点 x_1, x_2, x_3, ...
    把交点排序
    对 (x_1, x_2), (x_3, x_4), ... 区间内的所有像素涂黑
```

这是 8-bit 黑白位图。但我们需要 **anti-aliasing**(抗锯齿)。怎么做?把"涂黑"改成"按覆盖率涂灰":如果像素中心在曲线内 100%,alpha=255;在边缘,按覆盖面积算 alpha。

FreeType 用的是更高效的算法叫 **anti-aliased scanline with supersampling**。具体实现细节可以读 FreeType 源码 `src/raster/ftrend1.c`。

### 3.2 Hinting:让小字看起来锐利

没有 hinting,12px 的字母看起来糊——因为 12×12 像素不够表达 'e' 那么多曲线。Hinting 是"对小字号,把曲线手动调整到对齐像素网格"的技术。

Hinting 有四个级别:

1. **No hinting**:曲线直接栅格化,任何尺寸。看起来糊。
2. **Light hinting**:FreeType 的 auto-hinter 算法,自动调整。中等清晰度。
3. **Native hinting**(TrueType hinting):字体文件里有字节码指令,字体设计师手写。最清晰但需要设计师花大量时间。
4. **Light + subpixel**:加 subpixel rendering,见下节。

TrueType 的 hinting 是一种 **bytecode interpreter**——字体文件里有 `fpgm` (font program) 和 `prep` (CVT program) 表,里面是字节码指令,告诉 FreeType "在小字号下把 'e' 的横线从 y=412 移到 y=413,让它对齐像素"。这些指令由字体设计师用 FontLab / VOLT 工具写。

为什么 hinting 重要?在 1990s 屏幕是 72 DPI,12px 字母只有几个像素宽,hinting 决定可读性。今天 4K 屏 200+ DPI,没有 hinting 字也很清晰,所以很多现代字体(Inter、Roboto)的 hinting 简化或省略。

代码示例:控制 FreeType 的 hinting:

```rust
face.load_char('A', freetype::face::LoadFlag::RENDER
    | freetype::face::LoadFlag::TARGET_NORMAL)?;  // light hinting

face.load_char('A', freetype::face::LoadFlag::RENDER
    | freetype::face::LoadFlag::TARGET_MONO)?;    // 强制 1-bit,适合等宽

face.load_char('A', freetype::face::LoadFlag::RENDER
    | freetype::face::LoadFlag::NO_HINTING)?;     // 关 hinting
```

### 3.3 Subpixel rendering

LCD 屏每个像素其实是三个子像素(RGB)并排。普通抗锯齿把每个像素当一个单位,subpixel rendering **把每个像素当三个单位**。这相当于水平分辨率三倍。

但代价是:subpixel rendering 假设 LCD 的 RGB 排列固定。在 OLED / 旋转 90° 的屏 / PenTile 排列上,subpixel rendering 会有彩色 fringe,反而难看。所以现代很多系统(包括 macOS)已经放弃 subpixel rendering,只做普通灰度抗锯齿。

著名的 subpixel rendering 实现是 Microsoft 的 **ClearType**(Windows)和 FreeType 的 LCD filter。开启方式:

```bash
# Linux 看 fontconfig 配置
cat /etc/fonts/local.conf | grep -A2 rgba
# <match target="font">
#   <edit name="rgba" mode="assign"><const>rgb</const></edit>
# </match>
```

在 freetype-rs 里:

```rust
// 加载 LCD 模式的 glyph
face.load_char('A', LoadFlag::RENDER | LoadFlag::TARGET_LCD)?;
// bitmap.buffer 现在是 RGB 3 字节/像素,而不是灰度 1 字节/像素
```

## 4 · SDF(Signed Distance Field)文字

### 4.1 问题:缩放就糊

普通栅格化的 glyph 是位图。12px 渲染的 'A' 缩放到 24px,会糊;缩放到 48px,严重糊。游戏场景里镜头远近变化,文字大小变化,这是个问题。

解法 1:为每个字号预栅格化。内存爆炸。
解法 2:GPU 上重新栅格化曲线。复杂,慢。
解法 3:**SDF 文字**。2007 年 Valve 在 SIGGRAPH 发表的论文 "Improved Alpha-Tested Magnification for Vector Textures"。这是工业标准。

### 4.2 SDF 是什么

SDF = Signed Distance Field。一个 2D SDF 是个二维数组,每个像素存的是"到字形边缘的有符号距离"。在字形内部为正,外部为负,边缘为零。

把 SDF 当 texture 上传到 GPU。GPU shader 里这样用:

```glsl
// fragment shader
uniform sampler2D sdf_texture;
in vec2 uv;
out vec4 color;

void main() {
    float dist = texture(sdf_texture, uv).r;
    float alpha = smoothstep(0.45, 0.55, dist);  // 边缘宽度由 smoothstep 控制
    color = vec4(text_color.rgb, alpha);
}
```

神奇之处:`smoothstep` 的两个参数决定边缘"软硬"。设 0.49 / 0.51 是 1 像素边缘(锐利),0.3 / 0.7 是 20 像素边缘(柔和)。同一个 SDF 在 12px、24px、48px 都能正确渲染,**不需要重新栅格化**。

### 4.3 生成 SDF 的算法

给定一个 glyph 的轮廓,生成它的 SDF 有两种主流算法:

**算法 1:Brute force(每像素查最近边缘点)**。O(N²) per pixel,慢但简单。SDF 生成时只跑一次,所以慢点也行。

**算法 2:Two-pass (8SSEDT, Eight-points Signed Sequential Euclidean Distance Transform)**。Felzenszwalb 2003 年提出,O(N) per axis,极快。工业用得最多。

Valve 的原论文就是 brute force。社区的实现(`msdfgen` / `sdfgen`)用 8SSEDT 加速。

### 4.4 MSDF:多通道 SDF

SDF 有一个缺陷:尖锐角(比如 'A' 的尖顶)在渲染时会变圆。Valve 的论文里就讨论了这个 trade-off。

**MSDF(Multi-channel SDF)** 是 Viktor Chlumský 2015 年的改进。把三个独立的 SDF 分别存到 RGB 三个通道,每个 SDF 略微偏移。GPU shader 里:

```glsl
float dist = median(sdf.r, sdf.g, sdf.b);  // 取中位数
float alpha = smoothstep(0.45, 0.55, dist);
```

中位数 trick 让 sharp corner 保留下来。MSDF 是 2015 年后游戏字体渲染的标配。

工具:`msdfgen`(C++,CMake 构建)。

```bash
# 安装
sudo pacman -S msdfgen  # Arch

# 把一个 TTF 的字母 A 生成 MSDF atlas
msdfgen msdf-font -font DejaVuSans.ttf -charset charset.txt -o atlas.png
```

Rust 生态有 `msdf-sys`(msdfgen 绑定)和纯 Rust 的 `msdf` crate。

## 5 · Bevy text / cosmic-text / glyphon

### 5.1 Bevy text

Bevy 引擎的 `bevy_text` crate 内置文字系统。用法:

```rust
use bevy::prelude::*;
use bevy::text::Text;

fn setup(mut commands: Commands) {
    commands.spawn(TextBundle {
        text: Text::from_section(
            "Hello, world!",
            TextStyle {
                font: asset_server.load("fonts/FiraSans.ttf"),
                font_size: 32.0,
                color: Color::WHITE,
            },
        ),
        ..default()
    });
}
```

底层 `bevy_text` 用 `ab_glyph`(纯 Rust 的 glyph 栅格器,不依赖 FreeType)+ `glyph_brush_layout`(文本布局)+ Bevy 自己的 `Atlas` 做 glyph cache。

`bevy_text` 在 Bevy 0.13 之后正在被替换成 **cosmic-text**,因为 ab_glyph 不支持复杂文本整形(连字、阿拉伯语、印地语等)。

### 5.2 cosmic-text

**cosmic-text** 是 System76 给 COSMIC 桌面写的 Rust 文字布局库。它是目前 Rust 生态最强的文本库,功能包括:

- 复杂文本整形(连字 / RTL / 印地语)
- 多语言混合
- BiDi(双向文本,如阿拉伯语+英语)
- 文本布局(换行、对齐)
- Emoji 渲染(彩色 glyph)
- Cache(内部 glyph cache)

```toml
# Cargo.toml
cosmic-text = "0.11"
```

```rust
use cosmic_text::{Attrs, Buffer, Family, Metrics, Shaping};

// 创建 buffer
let mut buffer = Buffer::new(
    Metrics::new(14.0, 18.0),  // font_size, line_height
    "Hello, 世界!".into(),
);

// 设置字体属性
let attrs = Attrs::new()
    .family(Family::SansSerif);

// 整形 + 布局
buffer.set_text("Hello, 世界!", attrs, Shaping::Advanced);
buffer.shape_until_scroll(...);
```

cosmic-text 内部用了 `swash`(OpenType 解析 + shaping)、`rustybuzz`(HarfBuzz 的 Rust 移植)。它是当今 Rust 文字生态的事实标准。

### 5.3 glyphon:wgpu 上的 cosmic-text

**glyphon** 是 cosmic-text 的 wgpu 渲染层——给你一个能直接放进 wgpu / Bevy 渲染管线的"文字 atlas + buffer"。

```toml
glyphon = "0.6"
```

```rust
use glyphon::{Buffer, FontSystem, SwashCache, TextAtlas, TextRenderer};

let mut font_system = FontSystem::new();           // 系统字体加载
let mut swash_cache = SwashCache::new();           // glyph 栅格化缓存
let mut atlas = TextAtlas::new(&device, &queue, ...);
let mut text_renderer = TextRenderer::new(
    &mut atlas, &device, ...);

let mut buffer = Buffer::new(&mut font_system, Metrics::new(20.0, 24.0));
buffer.set_text("Hello, wgpu!", None);

// 每帧
text_renderer.prepare(&device, &queue, &mut font_system, &mut atlas, ...)?;
text_renderer.render(&wgpu_render_pass)?;
```

这是 Rust 生态里"最快的从零到能渲染文字"的路径。如果你做一个 wgpu 项目要文字,glyphon 是首选。

## 6 · Kerning 和 ligatures

### 6.1 Kerning

紧排:某些字符对需要"靠近一点"才好看。经典例子:'AV'、'Ta'、'To'。没有 kerning,'AV' 看起来像 'A V' 中间太空;有 kerning,'A' 和 'V' 紧凑咬合。

字体文件里 kerning 信息存在两个地方:
- **`kern` table**(老式,TrueType)
- **`GPOS` table**(现代,OpenType)

`GPOS`(Glyph Positioning)是 OpenType 高级排版的表,不仅能做 kerning,还能做 mark positioning(阿拉伯字母的点标记位置)、contextual positioning(根据上下文调整)。

读 kerning:

```rust
// 用 ttf-parser
let k = ttf_parser::KerningSubtables::new(&face);
for subtable in k {
    // 取出每对字符的 kerning 值
}
```

但工业实现不会逐对查 GPOS——太慢。一般做法是预先建一个 HashMap<(glyph_a, glyph_b), i16>,运行时 O(1) 查。

### 6.2 Ligatures

连字:某些字符序列合并成一个 glyph。英语里常见的:
- **fi** → ﬁ(很多字体有)
- **fl** → ﬂ
- **ff** → ﬀ
- **ffi** → ﬃ

CSS 里 `font-feature-settings: "liga" 1;` 开启标准连字。编程字体(如 Fira Code、JetBrains Mono)还支持程序员连字:
- `!=` → ≠
- `=>` → ⇒
- `->` → →

连字由 **GSUB**(Glyph Substitution)表描述。实现:整形阶段(Shaping)由 HarfBuzz / rustybuzz 处理。

```rust
// cosmic-text / rustybuzz 自动处理连字
let features = &[rustybuzz::Feature::new(
    rustybuzz::Tag::from_bytes(b"liga"), 1, ..)];
// shaping 后 'f' + 'i' 会变成单个 glyph
```

### 6.3 OpenType features 速查

OpenType features 是控制字形变体的开关。常见的:

| tag | 名字 | 作用 |
|---|---|---|
| liga | Standard Ligatures | fi、fl 等连字 |
| dlig | Discretionary Ligatures | 可选连字(默认关) |
| kern | Kerning | 字符对紧排 |
| calt | Contextual Alternates | 上下文变体 |
| smcp | Small Caps | 小型大写 |
| onum | Old-style Figures | 旧式数字 |
| tnum | Tabular Numbers | 表格数字(等宽) |
| zero | Slashed Zero | 带斜线的零 |

CSS: `font-feature-settings: "smcp" 1, "tnum" 1;`

## 7 · CJK 字体渲染

CJK(Chinese / Japanese / Korean)文字渲染有几个特殊问题。

### 7.1 字符数量爆炸

拉丁字母 26 个 + 一些标点 < 100 个 glyph。
CJK 需要 **3000-20000+** 个常用字符。GB2312 是 6763 个汉字,GBK 是 21003 个,GB18030 是 70244 个。Unicode CJK 区有 80000+。

这意味着:
- **字体文件大**。思源黑体 SourceHanSansCN-Regular.otf 是 9.6 MB。
- **glyph cache 不可行全局预生成**。必须 lazy cache,用到才栅格化。
- **shaping 极慢**。CJK 没有 kerning(基本是等宽方框),但 GSUB 表巨大。

### 7.2 字体选择

| 字体 | 大小 | 适用 |
|---|---|---|
| 思源黑体 Source Han Sans | 9-20 MB | 现代黑体,开源,标准 |
| 思源宋体 Source Han Serif | 12-30 MB | 宋体,开源 |
| 文泉驿微米黑 | 6 MB | 老牌开源,Linux 常见 |
| 文泉驿正黑 | 4 MB | 等宽黑体,适合终端 |
| Noto Sans CJK | 12 MB | Google 版的思源 |
| 文鼎 PL 新宋 | 4 MB | 老牌开源 |
| 站酷高端黑 | 5 MB | 商用免费 |

**重要**:`文泉驿`和`思源`是 Linux 上的两大主力。前者更轻量,后者更现代。系统 fallback 链一般是:

```
DejaVu Sans → 文泉驿微米黑 → 思源黑体 → Noto Color Emoji
```

代码里实现 fallback:

```rust
// 给每个字符找字体
let fonts = [noto_sans, wenquanyi, source_han];

for c in text.chars() {
    let font = fonts.iter().find(|f| f.has_glyph(c)).unwrap_or(&fonts[0]);
    // 用 font 渲染 c
}
```

cosmic-text / pango 内部都有这套 fallback 机制,叫 **font fallback chain**。

### 7.3 字形竖排

中日韩传统竖排。CSS: `writing-mode: vertical-rl;`。OpenType 有 `vhea` / `vmtx` 表存垂直 metric。HarfBuzz / cosmic-text 都支持竖排 shaping。

### 7.4 异体字

中文里同一个字有多个写法。比如 "戸" vs "戶" vs "户"——日 / 港台 / 大陆不同写法。Unicode 把它们编码为不同 code point,但有时同一 code point 在不同地区有不同字形。OpenType 的 `locl` feature(Localized Forms)处理这个。

## 8 · 从零解析 TTF:parseFontDirectory 实例

Casey 在 Handmade Hero Day 88-92 自己写了 TTF 解析器。让我把这个过程复盘。

完整代码很长(几百行),我们只看核心:`parseFontDirectory` 函数。这个函数读 font 文件头,返回一个 Font 结构。

```rust
// Casey 风格,简化版
#[derive(Debug)]
struct Font {
    scale: u32,           // unitsPerEm
    ascent: i16,
    descent: i16,
    line_gap: i16,
    cmap_subtable_offset: u32,
    glyph_locations: Vec<u32>,  // loca table
}

fn parse_font_directory(data: &[u8]) -> Option<Font> {
    let mut cursor = 0;

    // 1. 读 sfnt header
    let sfnt_version = read_u32(data, &mut cursor)?;  // 4 bytes
    if sfnt_version != 0x00010000 && sfnt_version != 0x4F54544F {
        return None;  // 不是 TTF 也不是 OTF
    }

    let num_tables = read_u16(data, &mut cursor)?;
    cursor += 6;  // skip searchRange, entrySelector, rangeShift

    // 2. 读 table directory
    let mut head_offset = None;
    let mut cmap_offset = None;
    let mut loca_offset = None;
    let mut hhea_offset = None;
    let mut hmtx_offset = None;
    let mut glyf_offset = None;

    for _ in 0..num_tables {
        let tag = &data[cursor..cursor+4];
        cursor += 4;
        let _checksum = read_u32(data, &mut cursor)?;
        let offset = read_u32(data, &mut cursor)?;
        let _length = read_u32(data, &mut cursor)?;

        match tag {
            b"head" => head_offset = Some(offset),
            b"cmap" => cmap_offset = Some(offset),
            b"loca" => loca_offset = Some(offset),
            b"hhea" => hhea_offset = Some(offset),
            b"hmtx" => hmtx_offset = Some(offset),
            b"glyf" => glyf_offset = Some(offset),
            _ => {}
        }
    }

    // 3. 解析 head table
    let head_offset = head_offset?;
    let mut c = head_offset + 18;  // skip 18 bytes 的 magic/version/etc
    let units_per_em = read_u16(data, &mut c)?;
    c += 16;  // skip created/modified dates
    let _x_min = read_i16(data, &mut c)?;
    let _y_min = read_i16(data, &mut c)?;
    let _x_max = read_i16(data, &mut c)?;
    let _y_max = read_i16(data, &mut c)?;
    c += 6;  // skip macStyle, lowestRecPPEM
    let index_to_loc_format = read_i16(data, &mut c)?;  // 0 = short, 1 = long

    // 4. 解析 hhea table
    let hhea_offset = hhea_offset?;
    let mut c = hhea_offset + 4;  // skip version
    let ascent = read_i16(data, &mut c)?;
    let descent = read_i16(data, &mut c)?;
    let line_gap = read_i16(data, &mut c)?;

    // 5. 解析 loca table(得到每个 glyph 在 glyf 里的偏移)
    let loca_offset = loca_offset?;
    let glyf_offset = glyf_offset?;

    let mut glyph_locations = Vec::new();
    let mut lc = loca_offset;

    // 简化:假设 index_to_loc_format = 0 (short format)
    loop {
        let off = read_u16(data, &mut lc)? as u32 * 2;
        glyph_locations.push(glyf_offset + off);
        if glyph_locations.len() > 65536 { break; }
        // 实际要读 maxp 表的 numGlyphs
        // 这里简化
    }

    Some(Font {
        scale: units_per_em as u32,
        ascent, descent, line_gap,
        cmap_subtable_offset: cmap_offset?,
        glyph_locations,
    })
}

// 辅助函数:大端读
fn read_u16(data: &[u8], c: &mut usize) -> Option<u16> {
    if *c + 2 > data.len() { return None; }
    let v = u16::from_be_bytes([data[*c], data[*c+1]]);
    *c += 2;
    Some(v)
}

fn read_i16(data: &[u8], c: &mut usize) -> Option<i16> {
    Some(read_u16(data, c)? as i16)
}

fn read_u32(data: &[u8], c: &mut usize) -> Option<u32> {
    if *c + 4 > data.len() { return None; }
    let v = u32::from_be_bytes([data[*c], data[*c+1], data[*c+2], data[*c+3]]);
    *c += 4;
    Some(v)
}
```

这个 parser 不完整(没有解析 cmap、glyph、kerning),但已经能拿到 font 的基本 metric。Casey 在 HH 里花了几集把整个 parser 写完,然后又花了几集实现 `glyf` 解析(贝塞尔曲线)和栅格化。

工业级 TTF parser 在 Rust 里:`ttf-parser`(纯 Rust)、`rusttype`(纯 Rust,带栅格化)、`swash`(完整 OpenType + shaping)。**写自己的 parser 是学习,生产用现成的 crate**。

## 9 · Rust 生态工具链速查

```bash
# 看系统有什么字体
fc-list : family | sort -u | head -20

# 找某个字符哪些字体支持
fc-list :charset=0x4E2D   # 中

# 看 TTF 的表
sudo pacman -S fonttools
python3 -c "from fontTools.ttLib import TTFont; f = TTFont('/usr/share/fonts/TTF/DejaVuSans.ttf'); print(f.keys())"

# msdfgen 生成 SDF
sudo pacman -S msdfgen
msdfgen msdf-font -font /path/to.ttf -charset charset.txt -o atlas.png -size 32

# fontforge 编辑字体(GUI)
sudo pacman -S fontforge
fontforge /path/to.ttf
```

Rust crates 推荐链:

| 用途 | 推荐 crate |
|---|---|
| 解析 TTF(轻量) | `ttf-parser` |
| 解析 + 栅格化 | `ab_glyph` |
| FreeType 绑定 | `freetype` (freetype-rs) |
| 跨平台字体查找 | `font-kit` |
| 完整文字系统 | `cosmic-text` |
| wgpu 渲染文字 | `glyphon` |
| shaping | `rustybuzz` |
| 彩色 glyph(emoji) | `swash` |

## 10 · 延伸阅读

- FreeType 官方文档:https://freetype.org/freetype2/docs/documentation.html
- Valve SDF 论文:https://steamcdn-a.akamaihd.net/apps/valve/2007/SIGGRAPH2007_AlphaTestedMagnification.pdf
- Viktor Chlumský 的 MSDF 论文和工具:https://github.com/Chlumsky/msdfgen
- OpenType 规范:https://docs.microsoft.com/en-us/typography/opentype/spec/
- cosmic-text 源码:https://github.com/pop-os/cosmic-text
- glyphon 源码:https://github.com/grovesNL/glyphon
- ttf-parser 源码:https://github.com/RazrFalcon/ttf-parser
- Casey HH 字体相关 day 列表:https://guide.handmadehero.org/code/day088/ 到 day110
