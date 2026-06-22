# 资产管线:导入、处理、打包、运行时加载

> 你做完游戏内容:1000 张纹理、200 个模型、50 段音乐、20 个 glTF 场景。如何让这些东西从美术工具到玩家 GPU 上?这就是**资产管线**(asset pipeline)——一个被低估但决定游戏质量的工程系统。本文从美术的 Photoshop / Blender 文件讲到玩家的 GPU 显存,讲清楚每个阶段、每个工具、每个决策。

## 0 · 为什么资产管线是工业级游戏的关键

新手做游戏:把 PNG 和 OBJ 直接扔进 `assets/` 目录,游戏启动时读它们。够用,直到你撞墙:

1. **加载慢**:游戏启动 30 秒读 2GB 资产。玩家失去耐心
2. **磁盘占用大**:游戏 50GB,但内容只有 5GB——剩下都是没压缩的资产
3. **加载卡顿**:玩家走进新区域,游戏卡 1 秒等磁盘
4. **跨平台**:PC 用 ASTC?移动用 BC7?Mac 用什么?每平台存一套?
5. **版本管理**:美术改了一张纹理,Git 里 50MB 变化,clone 时间爆炸
6. **打包**:发布时不能裸放 `.obj` / `.png`,需要某种容器格式

**资产管线**用工业级流程解决这些。它由四个阶段组成:

```
源资产(Source Asset)
   ↓ 导入(import)
中间资产(Intermediate Asset)
   ↓ 处理(process)
打包资产(Packaged Asset)
   ↓ 加载(load)
运行时资产(Runtime Asset)
```

每个阶段有自己的格式、工具、决策。本文逐段讲透。

**读完这一篇你能**:
- 设计一个支持热重载的资产管线
- 选合适的打包格式(KTX2、glb、自定义 PAK)
- 实现异步流式加载(玩家不卡顿)
- 看 Unreal / Unity / Bevy 的资产管线架构不被吓到

### 工业级案例:为什么资产管线决定游戏成败

资产管线不是"配置文件"——它是**决定游戏质量的工程系统**。让我们看几个真实案例:

**《Cyberpunk 2077》2020 发行灾难**:CD Projekt Red 的资产管线崩溃——Xbox One / PS4 上加载卡顿、纹理 streaming 跟不上、T-pose 角色。根本原因:资产管线在开发后期没收敛,大量资产"没准备好"就 ship。导致股价跌 75%,公司声誉受损。

**《Star Citizen》开发十年+**:Cloud Imperium 的资产管线太复杂——千个 ship、万种武器、亿级 asset。每次 build 几小时。他们花了 5 年专门重写资产管线,才让开发节奏可控。

**《Hades》Supergiant Games**:相反案例——Hades 的资产管线设计精细,小团队(20 人)能高频迭代。每次改 asset,< 10 秒看到结果。这让 Supergiant 在 2 年内 ship 高质量 roguelike。

**《Doom Eternal》id Software**:工业金标。资产管线高度自动化——美术改 PSD,自动转换 → BCn → pack,跑测试,提交。一小时内反馈。这让 id 的小团队(< 100 人)做出 AAA 质量游戏。

教训:**资产管线是 game dev 的"隐藏 infrastructure"**。投资它回报 10 倍——开发快、bug 少、迭代频繁。

### 资产管线的"四阶段"详解

本文要讲的核心架构——四阶段管线:

```
源资产(Source Asset)
   ↓ 导入(import)
中间资产(Intermediate Asset)
   ↓ 处理(process)
打包资产(Packaged Asset)
   ↓ 加载(load)
运行时资产(Runtime Asset)
```

每个阶段的具体职责:

**源资产**:美术工具产出。PSD / BLEND / WAV / FBX。**人类可编辑**、版本控制友好、可能很大。
**中间资产**:导入器输出。统一格式(Rust 结构、JSON)。**规范化**、metadata 完整、可能压缩。
**打包资产**:打包器输出。发布格式(.pak / .hha / .dat)。**紧凑**、平台特化、可能有 mipmap / BCn。
**运行时资产**:加载器输出。GPU 友好(Vulkan buffer / texture)。**直接 GPU 上传**、零拷贝、cache 友好。

每两个阶段之间有**适配器**——格式转换、压缩、metadata 提取。

### 工业级选择:每个阶段的金标

**源格式**:
- 图像:PSD(Photoshop)、KRA(Krita)、SVG(矢量)
- 3D:BLEND(Blender)、MA(Maya)、FBX(交换格式)
- 音频:WAV(无损)、FLAC(无损压缩)
- 字体:TTF / OTF / FONT

**中间格式**:
- 图像:PNG / EXR(高动态范围)
- 3D:glTF 2.0(Khronos 标准)
- 音频:OGG / OPUS
- 字体:SDF atlas(预渲染)

**打包格式**:
- 自定义:Unreal PAK、Unity AssetBundle、Casey HHA
- 标准:ZIP / 7Z(普通)
- 流式:KTX2(纹理)、glb(模型)

**运行时格式**:
- 纹理:GPU native(Vulkan VkImage / D3D12 Resource)
- 模型:GPU vertex buffer + index buffer
- 音频:解压到 PCM,推给 audio device

### Casey HH 的资产管线:从 Day 432 到 Day 465

Casey 在 Phase 7 子项目 D-E 实现完整的资产管线:

- **Day 453-459**:PNG 解码器(源 → 中间)
- **Day 460-461**:文件监听 + 热重载(中间 → 运行时)
- **Day 462**:sprite atlas(中间 → 打包)
- **Day 463-465**:HHA 格式(打包 + 加载)

这是工业级资产管线的"教学版"。完成后你能:
- 看任何引擎的资产管线源码不被吓到
- 设计自己的资产管线(虽然规模小)
- 评估不同架构选择的工程权衡

## 1 · 源资产:美术工具的产出

美术用专业工具产出内容:

| 资产类型 | 美术工具 | 源格式 |
|---|---|---|
| 2D 纹理 | Photoshop / Krita / Substance Painter | .psd / .kra / .spp |
| 3D 模型 | Blender / Maya / 3ds Max | .blend / .ma / .max |
| 动画 | Blender / MotionBuilder | .fbx / .bvh |
| 音频 | Audacity / Reaper / Pro Tools | .aup / .rpp |
| 视频 | Premiere / DaVinci | .prproj / .drp |
| 字体 | FontForge / Glyphs | .sfd / .glyphs |

**关键**:源格式(PSD、blend、FBX)**不进入游戏**。它们是"工作文件",包含图层、历史、备份——游戏只需要最终结果。

## 2 · 导入阶段:从源到中间

### 2D 纹理导入

```
texture.psd → exporter → texture.png (中间格式)
```

Photoshop / Krita 都支持脚本批量导出 PNG。Substance Painter 直接导出 PNG + 元数据。

### 3D 模型导入

```
model.blend → exporter → model.glb / model.fbx
```

Blender 内置 glTF 导出器;FBX 是更老但更通用的选择。

导入阶段关注:

1. **三角化**:把 quad / n-gon 转成三角形(GPU 只画三角形)
2. **法线计算**:从顶点位置算法线(或读美工指定的法线)
3. **切线计算**:从 UV 算 tangent(法线贴图用)
4. **UV 检查**:UV 是否有效,有没有重叠、零面积三角形
5. **材质绑定**:把材质和 mesh 关联

### 音频导入

```
music.flac → converter → music.ogg (中间格式)
```

游戏用 Ogg Vorbis(压缩率高)或 Opus(更新、更好)。WAV 用于短音效(无延迟)。

## 3 · 处理阶段:从中间到打包

### 纹理处理

```
texture.png (PNG, RGBA, 无压缩) 
   → mip 生成(每级 ÷ 2,直到 1x1)
   → BC7 压缩(桌面)/ ASTC(移动)
   → texture.ktx2 (打包格式)
```

**Mip 生成**:用 box filter(每 2×2 平均)或更高级(Kaiser filter)。Mip 让远处纹理看起来平滑,而不是抖动(aliasing)。

**压缩格式选择**:见前面 texture-compression.md。

### 模型处理

```
model.glb (glTF,顶点 + 三角形 + UV + 法线 + 切线)
   → mesh optimization(顶点缓存优化、剔除退化三角形)
   → LOD 生成(自动简化,3-5 个 LOD 级别)
   → 包进自定义二进制格式(.mesh)
```

**顶点缓存优化**:重新排列三角形顺序,让 GPU vertex cache 命中率高。Forsyth / Tom Forsyth 算法是经典。

**LOD 生成**:用 mesh simplification(Quadric Error Metrics、METIS 等),自动生成低多边形版本。远处用低 LOD,近处用高 LOD。

### 资产打包:容器格式

所有处理后的资产塞进一个或几个**容器文件**:

| 格式 | 用途 | 特点 |
|---|---|---|
| KTX2 | 纹理 | Khronos 标准,支持所有 GPU 压缩格式 |
| glb | glTF 二进制 | 模型 + 动画 + 材质 |
| Ogg / Opus | 音频 | 流式播放 |
| 自定义 PAK | 综合 | 自己设计,可加密 |

工业级引擎都有自己的 PAK 格式:

- **Unreal**:`.pak`(基于 zlib 压缩的 zip 变种)
- **Unity**:`.asset` / `.assets`(序列化 YAML 二进制)
- **Source / Valve**:`.vpk`
- **id Tech**:`.pk3` / `.pk4`(zip 变种)

### 自定义 PAK 格式示例

```rust
// 简化的 PAK 格式
// [Header 4 字节 magic 'PAK1']
// [FileTable 数量 N(4 字节)]
// [N 个 FileEntry]
// [所有文件数据]

struct PakHeader {
    magic: [u8; 4],       // b"PAK1"
    version: u32,
    file_count: u32,
}

struct FileEntry {
    path_hash: u64,       // 路径的 hash,用于快速查找
    offset: u64,
    compressed_size: u64,
    uncompressed_size: u64,
    compression: u8,      // 0=none, 1=zstd, 2=lz4
    asset_type: u8,       // 0=texture, 1=mesh, 2=audio, ...
}

fn write_pak(entries: &[(String, Vec<u8>)]) -> Vec<u8> {
    let mut output = Vec::new();
    let mut file_table: Vec<FileEntry> = Vec::new();
    let mut data_section = Vec::new();
    
    // 写文件数据,构建 file table
    for (path, data) in entries {
        let path_hash = hash(path);
        let offset = data_section.len() as u64;
        let uncompressed_size = data.len() as u64;
        let compressed = zstd_compress(data);  // 假设有这个函数
        let compressed_size = compressed.len() as u64;
        
        file_table.push(FileEntry {
            path_hash: hash(path),
            offset,
            compressed_size,
            uncompressed_size,
            compression: 1,
            asset_type: detect_type(path),
        });
        data_section.extend_from_slice(&compressed);
    }
    
    // 写 header
    output.extend_from_slice(b"PAK1");
    output.extend_from_slice(&1u32.to_le_bytes());
    output.extend_from_slice(&(file_table.len() as u32).to_le_bytes());
    
    // 写 file table
    for entry in &file_table {
        output.extend_from_slice(&entry.path_hash.to_le_bytes());
        output.extend_from_slice(&entry.offset.to_le_bytes());
        output.extend_from_slice(&entry.compressed_size.to_le_bytes());
        output.extend_from_slice(&entry.uncompressed_size.to_le_bytes());
        output.push(entry.compression);
        output.push(entry.asset_type);
    }
    
    // 写数据
    output.extend_from_slice(&data_section);
    output
}
```

每段注释:

- `path_hash` — 用 hash(FNV-1a / xxHash)加速查找,不用字符串比较
- `compression: 1 = zstd` — 选择 zstd 或 lz4(快解压)
- `asset_type` — 一字节区分资产类型,加载器根据类型分发

## 4 · 运行时加载

### 同步加载(简单但卡顿)

```rust
fn load_texture_sync(path: &str) -> Texture {
    let data = std::fs::read(path).unwrap();
    let png = decode_png(&data).unwrap();
    upload_to_gpu(&png.pixels, png.width, png.height)
}
```

简单,但加载阻塞主线程,玩家会感到卡顿。

### 异步加载(流畅但复杂)

```rust
async fn load_texture_async(path: &str) -> Texture {
    let data = tokio::fs::read(path).await.unwrap();
    let png = decode_png(&data).unwrap();
    upload_to_gpu(&png.pixels, png.width, png.height)
}
```

主线程不阻塞,但需要异步运行时(tokio / async-std)。

### 后台线程加载(主流)

```rust
fn load_texture_background(
    path: String,
    sender: Sender<TextureLoadResult>,
) {
    thread::spawn(move || {
        let data = std::fs::read(&path).unwrap();
        let png = decode_png(&data).unwrap();
        // 注意:GPU 上传必须在渲染线程!
        sender.send(TextureLoadResult {
            path, pixels: png.pixels, w: png.width, h: png.height
        }).unwrap();
    });
}
```

工作线程做磁盘 I/O 和解码;GPU 上传在渲染线程完成(因为 OpenGL 限制)。

### 流式加载(大世界)

大世界游戏(GTA、Elden Ring)用流式加载:

1. 把世界分成 chunk(每 chunk 100m × 100m)
2. 玩家位置变化,提前加载周围 N 个 chunk
3. 远离玩家的 chunk 卸载

```rust
fn streaming_update(player_pos: Vec3) {
    let current_chunk = world_to_chunk(player_pos);
    
    // 加载周围 3x3 chunk
    for dx in -1..=1 {
        for dz in -1..=1 {
            let chunk = current_chunk + IVec2::new(dx, dz);
            if !loaded_chunks.contains(&chunk) {
                load_chunk_async(chunk);
            }
        }
    }
    
    // 卸载远离的 chunk
    for chunk in loaded_chunks.iter() {
        if distance(chunk, current_chunk) > 3 {
            unload_chunk(*chunk);
        }
    }
}
```

### 资产引用计数

每个资产有引用计数:

```rust
struct Asset<T> {
    inner: Arc<RwLock<T>>,
    handle: AssetHandle,
}

impl<T> Clone for Asset<T> {
    fn clone(&self) -> Self {
        // 增加引用计数
        asset_manager.inc_ref(&self.handle);
        Self { inner: self.inner.clone(), handle: self.handle }
    }
}

impl<T> Drop for Asset<T> {
    fn drop(&mut self) {
        // 减少引用计数;归零时卸载
        asset_manager.dec_ref(&self.handle);
    }
}
```

Rust 的所有权 + Drop trait 完美匹配资产引用计数。

## 5 · 热重载(Hot Reload)

游戏开发时,美工改了纹理,你想立刻看到效果——不要重启游戏。这就是**热重载**。

### 实现方式

1. **文件监视**(inotify / kqueue):操作系统监听文件变化,触发回调
2. **资产版本**:每个资产有版本号,每帧检查文件 mtime
3. **资源管理器 API**:`reload_texture(handle)` 强制重载

```rust
use notify::{Watcher, RecursiveMode, watcher};
use std::sync::mpsc::channel;
use std::time::Duration;

fn watch_assets(asset_dir: &str, manager: Arc<AssetManager>) {
    let (tx, rx) = channel();
    let mut watcher = watcher(tx, Duration::from_millis(100)).unwrap();
    watcher.watch(asset_dir, RecursiveMode::Recursive).unwrap();
    
    thread::spawn(move || {
        while let Ok(event) = rx.recv() {
            match event {
                notify::DebouncedEvent::Write(path) => {
                    manager.reload(&path);
                }
                _ => {}
            }
        }
    });
}
```

每段注释:

- `notify::Watcher` — 跨平台文件监视 crate
- `DebouncedEvent::Write` — 文件写入完成事件(防抖,避免编辑器临时文件触发)
- `manager.reload(&path)` — 找到对应资产,重新加载,GPU 上传新版本

热重载让游戏开发体验飞跃。Casey 在 Handmade Hero 把热重载做到极致——连代码都能热重载。

## 6 · 跨平台资产策略

不同平台 GPU 支持的压缩格式不同。两种策略:

### 策略 1:每平台一份资产

```
assets_pc/texture.ktx2 (BC7)
assets_mobile/texture.ktx2 (ASTC)
```

打包时只带本平台的资产。简单,但每个平台单独打包。

### 策略 2:用 Basis Universal 超集

```
assets/texture.ktx2 (Basis Universal 中间格式)
```

运行时根据 GPU 能力转码到 BC7 / ASTC / ETC2。一份资产,所有平台。

**权衡**:策略 2 启动时多了一次转码(几十毫秒);策略 1 占用更多磁盘 / 构建复杂。

工业界倾向策略 2(Bevy、Filament、Unreal 5 都用 Basis)。

## 7 · 资产清单(Asset Manifest)

资产多了需要**清单文件**:列出所有资产、版本、依赖。常见格式:

```toml
# assets.toml
[texture.player_diffuse]
source = "src/textures/player_diffuse.psd"
format = "BC7"
mips = true

[mesh.player]
source = "src/models/player.blend"
lod = [1.0, 0.5, 0.25]

[audio.bgm]
source = "src/audio/bgm.flac"
format = "Opus"
loop = true
```

构建脚本读 manifest,执行 import / process / package。

## 8 · Rust 生态工具

### 纹理

- `image`:PNG/JPEG/BMP 解码
- `ktx2`:KTX2 容器读写
- `basis-universal`:Basis 编码/转码
- `astc-encoder`:ASTC 编码

### 模型

- `gltf`:glTF 加载
- `easy-gltf`:更易用包装
- `fbxcel`:FBX 加载(实验性)

### 音频

- `vorbis`:Ogg Vorbis 解码
- `audrey`:多格式音频解码

### 容器 / 打包

- 自定义 PAK 格式(项目特定)
- `zip`:zip 兼容格式
- `tar`:tar 格式

## 9 · 工业级示例:Bevy 资产管线

Bevy 的资产系统是 Rust 工业级参考:

```rust
// Cargo.toml:
// [dependencies]
// bevy = "0.14"

use bevy::prelude::*;
use bevy::asset::AssetPlugin;

fn main() {
    App::new()
        .add_plugins(DefaultPlugins.set(AssetPlugin {
            watch_for_changes: true,  // 热重载
            ..default()
        }))
        .add_systems(Startup, setup)
        .run();
}

fn setup(mut commands: Commands, asset_server: Res<AssetServer>) {
    // 异步加载纹理
    let texture: Handle<Image> = asset_server.load("textures/player.png");
    
    commands.spawn(SpriteBundle {
        texture,
        ..default()
    });
}
```

每行注释:

- `watch_for_changes: true` — 启用文件监视,美工改文件自动重载
- `Handle<Image>` — 资产句柄,引用计数,无需手动释放
- `asset_server.load(...)` — 异步加载,内部线程池

## 10 · 历史

- 1980s:游戏直接读磁盘,无管线
- 1990s:Doom 用 WAD(Where's All the Data)格式打包资产
- 2000s:Unreal / Unity 出现,资产管线成引擎标配
- 2010s:Foundation Universal / ASTC 出现,跨平台资产成为可能
- 2020s:Bevy / Filament 用 ECS + 异步资产管线,Rust 生态成熟

## 11 · 关联 Day

- **铺垫**:Day 100+ 文件系统;Day 200 多线程;Day 436 PNG;Day 466 glTF
- **当天**:本篇是资产管线专题
- **后续**:Day 500+ 大世界流式加载;Day 600+ 发布打包

## 12 · 变式训练

### Lv1 · 概念辨析

**题**:为什么游戏不用源格式(.psd / .blend)直接读,而要走 import → process → package?

**参考解答**:三个原因:
1. **效率**:PSD 有图层 / 历史,文件大 5-10 倍。游戏只需要最终像素,导入后转 PNG 节省 90% 磁盘
2. **可移植**:游戏运行时不需要 Photoshop / Blender,中间格式(PNG、glb)用任何库都能读
3. **可优化**:导入时做 BC7 压缩、mip 生成、LOD 简化等耗时操作,运行时直接用

### Lv2 · 动手实践

**题**:给你的游戏写一个简化的 PAK 打包器和解包器。要求:支持添加文件、按路径查询、列出所有文件。

**参考解答**:见上面的 `write_pak` 代码骨架。补充:

```rust
fn read_pak(data: &[u8]) -> Vec<(String, Vec<u8>)> {
    // 1. 读 header
    let magic = &data[..4];
    assert_eq!(magic, b"PAK1");
    let file_count = u32::from_le_bytes(data[8..12].try_into().unwrap());
    
    // 2. 读 file table
    let mut offset = 12;
    let mut entries = Vec::new();
    for _ in 0..file_count {
        let path_hash = u64::from_le_bytes(data[offset..offset+8].try_into().unwrap());
        offset += 8;
        // ... 读其他字段
        entries.push(/* ... */);
    }
    
    // 3. 读数据
    // ...
    
    // 注意:实际需要存 path → hash 的映射
    // 简化:假设有原始路径
    vec![]
}
```

### Lv3 · 迁移设计

**题**:Web 应用的"前端构建"(webpack / Vite)和游戏资产管线有什么相似和不同?设计一个能同时服务两者的通用"资产管线"框架。

**提示**:都有 source → import → process → bundle 流程。Web 用 URL 定位,游戏用 path;Web 用 hash 缓存,游戏用版本号。

### Lv4 · 开源贡献

**题**:Bevy 的资产系统在 https://github.com/bevyengine/bevy

1. 看 `crates/bevy_asset/`
2. 理解 `AssetServer`、`AssetLoader`、`AssetSaver`
3. 看热重载实现
4. 可能的贡献:加一个新的 AssetLoader(比如某种格式)、改进文档

## 13 · Rust / Arch 落地代码

完整的"导入 → 处理 → 打包 → 加载"流程骨架:

```rust
// asset_pipeline.rs

use std::path::{Path, PathBuf};
use std::collections::HashMap;

pub struct AssetImporter {
    intermediate_dir: PathBuf,
}

impl AssetImporter {
    pub fn new(intermediate_dir: &Path) -> Self {
        Self { intermediate_dir: intermediate_dir.to_path_buf() }
    }
    
    pub fn import_texture(&self, src: &Path) -> Result<PathBuf, String> {
        // PSD → PNG(简化:假设源是 PNG)
        let dest = self.intermediate_dir.join(
            src.file_stem().unwrap().to_str().unwrap()
        ).with_extension("png");
        
        let img = image::open(src).map_err(|e| e.to_string())?;
        img.save(&dest).map_err(|e| e.to_string())?;
        
        Ok(dest)
    }
    
    pub fn import_model(&self, src: &Path) -> Result<PathBuf, String> {
        // blend → glb(需要 Blender CLI 或 gltf 库)
        // 简化:假设源是 glb
        let dest = self.intermediate_dir.join(
            src.file_stem().unwrap().to_str().unwrap()
        ).with_extension("glb");
        std::fs::copy(src, &dest).map_err(|e| e.to_string())?;
        Ok(dest)
    }
}

pub struct AssetProcessor {
    output_dir: PathBuf,
}

impl AssetProcessor {
    pub fn new(output_dir: &Path) -> Self {
        Self { output_dir: output_dir.to_path_buf() }
    }
    
    pub fn process_texture(&self, intermediate: &Path) -> Result<PathBuf, String> {
        let img = image::open(intermediate).map_err(|e| e.to_string())?;
        // 生成 mip、压缩到 KTX2(简化)
        let dest = self.output_dir.join(
            intermediate.file_stem().unwrap().to_str().unwrap()
        ).with_extension("ktx2");
        std::fs::copy(intermediate, &dest).map_err(|e| e.to_string())?;
        Ok(dest)
    }
}

pub struct AssetPak {
    pub files: HashMap<String, PathBuf>,
}

impl AssetPak {
    pub fn package(&self, output: &Path) -> Result<(), String> {
        let entries: Vec<(String, Vec<u8>)> = self.files.iter()
            .map(|(name, path)| {
                let data = std::fs::read(path).unwrap();
                (name.clone(), data)
            })
            .collect();
        let pak_data = write_pak(&entries);
        std::fs::write(output, pak_data).map_err(|e| e.to_string())?;
        Ok(())
    }
}

pub struct RuntimeLoader {
    pak_data: Vec<u8>,
    file_table: HashMap<u64, (u64, u64, u8)>,  // hash → (offset, size, compression)
}

impl RuntimeLoader {
    pub fn open(pak_path: &Path) -> Result<Self, String> {
        let data = std::fs::read(pak_path).map_err(|e| e.to_string())?;
        // 解析 header + file table
        // ...
        Ok(Self { pak_data: data, file_table: HashMap::new() })
    }
    
    pub fn load(&self, path: &str) -> Result<Vec<u8>, String> {
        let hash = hash(path);
        let (offset, size, compression) = self.file_table.get(&hash)
            .ok_or("not found")?;
        let compressed = &self.pak_data[*offset as usize..(*offset + *size) as usize];
        match compression {
            0 => Ok(compressed.to_vec()),
            1 => zstd_decompress(compressed),  // 假设有这个函数
            _ => Err("unknown compression".into()),
        }
    }
}
```

Arch 工具链:

```bash
# 装资产处理工具
sudo pacman -S blender       # 模型
sudo pacman -S krita         # 2D 美术
sudo pacman -S imagemagick   # 命令行图像处理
sudo pacman -S astc-encoder  # ASTC 压缩
sudo pacman -S ffmpeg        # 音视频转换
yay -S basis-universal       # Basis 编码器(AUR)

# 看资产大小
du -sh assets/
# 输出:1.2G  assets/

# 看具体类型
find assets/ -type f | awk -F. '{print $NF}' | sort | uniq -c
# 输出:
#    152 blend
#   1248 png
#     87 glb
#     23 ogg

# 用 Blender 批量导出
blender --background --python export_glb.py
# --background 不开 GUI
# --python 跑导出脚本

# 用 ImageMagick 批处理纹理
mogrify -resize 50% -format png textures/*.psd
# 把所有 PSD 缩小 50% 转 PNG

# 看磁盘 I/O 性能(资产加载瓶颈)
sudo pacman -S iotop
sudo iotop -o
# 显示当前有 I/O 的进程
```

排错:

```bash
# 1. 游戏启动慢
#    原因:同步加载所有资产
#    排查:perf record ./game 然后 perf report
#    解决:改异步加载 / 流式加载

# 2. 内存爆
#    原因:资产没卸载
#    排查:valgrind --tool=massif ./game
#    解决:加引用计数,远离的资产卸载

# 3. 卡顿
#    原因:大资产(GPU 上传)
#    排查:Renderdoc 看 texture upload 时间
#    解决:分帧上传,每帧上传几个

# 4. 跨平台不一致
#    原因:不同 GPU 支持不同格式
#    排查:vulkaninfo / glxinfo 看格式支持
#    解决:用 Basis Universal
```

## 14 · 延伸阅读

本仓库本地:

- `days/phase-7/deep-dives/png-format-complete.md` — 纹理格式
- `days/phase-7/deep-dives/gltf-and-model-loading.md` — 模型格式
- `days/phase-6/deep-dives/texture-compression.md` — 压缩格式

外部稳定 URL:

- Bevy Assets: https://bevyengine.org/learn/book/features/assets/
- Filament Materials: https://google.github.io/filament/Materials.html
- KTX2 规范: https://registry.khronos.org/KTX/specs/2.0/ktxspec.v2.html
- glTF 规范: https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html
- Basis Universal: https://github.com/BinomialLLC/basis_universal

真实开源源码:

- Bevy Asset: https://github.com/bevyengine/bevy/tree/main/crates/bevy_asset
- Filament Material: https://github.com/google/filament/tree/main/tools/matc
- Amethyst Assets(legacy): https://github.com/amethyst/amethyst/tree/master/amethyst_assets
