
# 音频编码与格式

> 你的游戏有 90 分钟管弦乐原声,三千个音效——脚步、枪声、UI 点击、Boss 喊话。Casey 在 day009 直接把 WAV 喂给 mixer,因为那时只有一个采样、几秒长。但你现在 ship 一个真实游戏:90 分钟立体声 48 kHz/16-bit PCM 就是约 1 GB,三千个 SFX 算下来又一个 GB。Steam 上下载 2 GB 音频,移动端装不下,内存吃光。你**必须压缩**。但音频压缩是一片格式丛林:PCM、WAV、FLAC、Vorbis、Opus、MP3、ADPCM,每一个都有自己的取舍——质量、体积、解压成本、授权。选错了,要么 ship 出去两百 MB 的膨胀包,要么玩家听见那个"嗡嗡的水声"artifact。这篇 deep-dive 是这片丛林的地图:它从最朴素的 PCM 一路讲到 Opus 为什么在 32 kbps 打败 128 kbps 的 MP3,从"为什么压缩了十倍耳朵还听不出来"的心理声学直觉,讲到游戏里"边读磁盘边解压"的双缓冲流式解码。看完你能在 HH 项目里把每一段音频素材**按用途**挑对格式——SFX 用什么、BGM 用什么、网络语音用什么——并亲手实现一条流式 Opus 解码管线。
>
> 前置:你应当读完 [信号基础](../../phase-0/22-signals-foundation.md) 知道采样率与量化,读完 [DSP 基础](dsp-fundamentals.md) 知道 LTI 与傅里叶,读完 [音频管线](audio-pipeline-complete.md) 知道 mixer 怎么吃 PCM,以及 [asset 压缩](../../phase-4/deep-dives/asset-compression.md) 里 lossless vs lossy 的基本区分。下面默认你已经会读 f32 PCM、会用 cpal callback。

## 0 · 为什么这一篇不能跳

打开你的 `game_sound.rs`,Casey 的 `LoadWAV` 把整个文件 `mmap` 进内存,pointer 直接指向 PCM 数据。三千个 SFX、每个 2 秒,总共 6 秒 × 3000 = 18000 秒音频。48 kHz 16-bit stereo:每秒 192 KB,总共 **3.4 GB**。Steam 客户端会骂你,手机直接装不下,SSD 加载的时候风扇起飞。

更糟的是质量:你录的 Boss 战音乐是从录音棚拿到的 96 kHz/24-bit master。直接 ship WAV,完美保真——但玩家根本听不出 96 kHz 和 48 kHz 的区别(Nyquist 在 48 kHz 已经 24 kHz,人耳极限就 20 kHz),也听不出 24-bit 和 16-bit 的区别(动态范围 96 dB 已经覆盖从深夜静室到飞机起飞)。你 ship 出去的 90% 字节是**耳朵收不到的信息**。

这就是音频压缩的全部起点:**用更少的字节表达同样的听感**。下面这条路从最朴素的"不压缩"开始,一级一级往压缩率走,每一步告诉你丢掉了什么、保留了什么、什么时候该选它。这是音频工程少数几个"你能从第一性原理推出来"的领域——只要你想清楚耳朵到底在听什么。

## 1 · PCM:一切的基准

**脉冲编码调制**(Pulse-Code Modulation, PCM)不是一种"压缩",它是数字音频的**本来面目**。ADC(模数转换器)每隔 T 秒采样一次,把模拟电压量化成 B 位的整数,得到一串数字 `x[0], x[1], x[2], ...`——这就是 PCM。两端点之间没有别的信息,没有冗余,没有压缩,没有 magic。

PCM 的两个参数决定了它的体积:**采样率**(samples/second)和**位深**(bits/sample)。立体声 48 kHz / 16-bit PCM 的码率是 `48000 × 16 × 2 = 1.536 Mbps`,折合每秒 192 KB。一分钟 11.5 MB,一小时 690 MB。这就是 WAV 文件动辄几百 MB 的根本原因——它就是 PCM 加了一个 44 字节的文件头。

**为什么 PCM 是基准**。你后面看到的所有有损压缩——Vorbis、Opus、MP3——它们的工作都是**把 PCM 变小**;而所有解码器的输出,**永远都是 PCM**。无论你 ship 的文件是 Opus 还是 Vorbis,送进 cpal callback 的最终都是 PCM 浮点数。你心里要把 PCM 当成"音频的真值"——一切压缩都是在它上面做文章,一切质量评价都是拿解码出来的 PCM 跟原始 PCM 比。读完这一节你在头脑里就锚定了一个**坐标系**:任何格式的码率、SNR、artifact 都和"如果直接 ship PCM 会是多少"作对比。

**Rust 里 PCM 就是 `&[f32]` 或 `&[i16]`**。Casey 的 day009 加载 WAV 后得到的就是 i16 数组,mixer 里 cast 成 f32 处理。这就是 PCM 在代码里的样子——一串连续的样本,无 metadata,无封装,没有任何"编码"。

## 2 · WAV:给 PCM 戴一顶帽子

WAV(更准确地说是 RIFF WAVE)是 1991 年 Microsoft 和 IBM 在 Windows 3.1 时代定的容器格式,它把 PCM 包了一层很薄的壳。一个典型 WAV 文件的结构是这样:开头 12 字节是 RIFF 头(签名 `RIFF` + 文件大小 + 类型 `WAVE`),然后是若干个 **chunk**(块),每个 chunk 有 4 字节的 ID、4 字节的大小、和数据。最关键的 chunk 是 `fmt `,里面装着采样率、声道数、位深;然后是 `data` chunk,里面就是**裸的 PCM 字节**,原封不动。

也就是说,WAV 文件在磁盘上和内存里**几乎一样大**——它对 PCM 不做任何压缩。这是个设计选择,也是它最大的优点和最大的缺点:优点是解压成本是**零**(memcpy 即可),你 `mmap` 之后直接拿 pointer 就能读样本;缺点是体积爆炸。

**为什么 WAV 仍然是内部工作格式**。尽管它巨大,所有专业音频软件——DAW、采样器、HH 自己的 mixer——都用 WAV(或 raw PCM)作为**内部/工作格式**。原因是:第一,零解压成本,任何实时音频路径上你都不想多一次解码;第二,无损,你可以反复处理(resample、加 effect、normalize)而不引入 artifact;第三,所有解码器都吐 PCM,你 ship 前先把所有素材转成 PCM 在内存里,这等价于"运行时全用 WAV"。

**WAV 头部解析**(你迟早要自己写一次)。下面是从 HH `LoadWAV` 出发精简的解析逻辑,展示 RIFF WAVE 的最小结构:

```rust
// 最小 RIFF WAVE 解析器(仅 16-bit PCM)
pub struct WavData {
    pub sample_rate: u32,
    pub channels: u16,
    pub samples: Vec<i16>,  // interleaved
}

pub fn parse_wav(bytes: &[u8]) -> Result<WavData, &'static str> {
    // RIFF header: "RIFF" + size(4) + "WAVE"
    if &bytes[0..4] != b"RIFF" || &bytes[8..12] != b"WAVE" {
        return Err("not a RIFF/WAVE");
    }
    let mut pos = 12;
    let mut fmt_parsed = false;
    let mut sample_rate = 0u32;
    let mut channels = 0u16;
    let mut bits_per_sample = 0u16;
    let mut samples = Vec::new();

    while pos + 8 <= bytes.len() {
        let chunk_id = &bytes[pos..pos+4];
        let chunk_size = u32::from_le_bytes(
            bytes[pos+4..pos+8].try_into().unwrap()
        ) as usize;
        let body = &bytes[pos+8 .. pos+8+chunk_size];
        match chunk_id {
            b"fmt " => {
                // format:     2 bytes (1 = PCM)
                // channels:   2 bytes
                // sample_rate: 4 bytes
                // byte_rate:  4 bytes
                // block_align:2 bytes
                // bits_per_sample: 2 bytes
                channels       = u16::from_le_bytes(body[2..4].try_into().unwrap());
                sample_rate    = u32::from_le_bytes(body[4..8].try_into().unwrap());
                bits_per_sample = u16::from_le_bytes(body[14..16].try_into().unwrap());
                fmt_parsed = true;
            }
            b"data" => {
                assert!(fmt_parsed, "data before fmt");
                assert_eq!(bits_per_sample, 16, "only 16-bit PCM supported here");
                let n = chunk_size / 2;
                samples = (0..n)
                    .map(|i| i16::from_le_bytes(
                        body[i*2..i*2+2].try_into().unwrap()
                    ))
                    .collect();
            }
            _ => {} // 忽略 LIST、fact、其他 chunk
        }
        pos += 8 + chunk_size + (chunk_size & 1); // chunk 对齐到偶数
    }
    Ok(WavData { sample_rate, channels, samples })
}
```

注意那个 `(chunk_size & 1)`——RIFF 规范要求每个 chunk 的 body 对齐到偶数字节边界,如果 chunk_size 是奇数,后面要补一个 padding byte。这是无数 WAV parser bug 的来源,Casey 在 day009 之后的某天专门修了它。

`data` chunk 之后可能还有 `LIST`(存放 cue points、loop points)、`fact`(对非 PCM 格式给出样本数),游戏里偶尔要用——比如无缝循环音乐要读 loop point,HH day209 就用到。但绝大多数情况下,WAV 就是 `fmt ` + `data` 两个 chunk。

读完这一节你心里要清楚:**WAV 是 PCM 的别名**。所有讨论"压缩"时,WAV 就是那个"没压缩"的对照组。

## 3 · FLAC:像 ZIP 一样对待音频

**Free Lossless Audio Codec**(FLAC)是 2001 年 Xiph.Org 推出的无损音频格式。它的核心承诺是:**压缩后体积变小,但解码出来的 PCM 和原始 PCM 一模一样,bit-exact,没有任何失真**。这从概念上就是把 ZIP / gzip 用在了音频上,但用了针对音频特征优化的算法(预测残差 + Rice 编码),所以压缩比远高于通用 ZIP。

压缩比典型在 **50-60%**,也就是说 100 MB 的 WAV 编成 FLAC 大约 50-60 MB。这不如有损(Vorbis / Opus 能做到 10 倍以上),但好处是"零损失"——任何你听不出来但确实存在于信号里的细节,FLAC 全保留。

FLAC 的内部算法大概是这样:对每个样本,用它前面几个样本做**线性预测**(linear prediction),预测值 `x_pred[n] = sum_i c_i · x[n-i]`,然后编码**残差**(residual)`e[n] = x[n] - x_pred[n]`。音频信号通常高度可预测(尤其纯音、谐振),残差值很小;然后用 **Rice 编码**(类似 Golomb 编码)压缩残差——小数值用短码,大数值用长码。预测器系数和残差一起存进文件。解码时反向操作:读系数,读残差,反预测还原样本。整个过程**完全可逆**,这就是"无损"的含义。

**什么时候用 FLAC**。FLAC 在游戏里有两个典型位置:**第一**,你的母带/源素材——你拿到 96 kHz/24-bit 录音棚 master,存成 FLAC 而不是 WAV,节省一半磁盘,但任何编辑都不损失质量;**第二**,玩家社区对音质极其敏感的发售——古典音乐 / 视觉小说 BGM / 音游,这些场景玩家真的能听出 128 kbps MP3 和原始的区别,你 ship FLAC 给他们"零损失"的承诺。普通商业游戏用 FLAC ship 不划算,因为 Opus / Vorbis 在透明码率(后面讲)下听感等价,而 FLAC 体积大三倍。

**Rust 用 claxon 解 FLAC**:

```toml
# Cargo.toml
[dependencies]
claxon = "0.4"
```

```rust
use claxon::FlacReader;
use std::fs::File;

let reader = FlacReader::open("bgm.flac")?;
let streaminfo = reader.streaminfo();
println!("{} Hz, {} channels, {} bps",
    streaminfo.sample_rate,
    streaminfo.channels,
    streaminfo.bits_per_sample);

// 流式读样本(不全加载)
let mut samples = reader.samples().take(48000 * 2);  // 前 1 秒 stereo
for s in samples {
    let v: i32 = s?;
    // 转 f32 处理
}
```

注意 `reader.samples()` 是个 iterator——这是 FLAC 解码器给你"流式"的最自然形式,你想读多少读多少,不需要把整个文件载入内存。这种特性对后面讲的双缓冲流式解码至关重要。

**FLAC 的工程权衡**。它的解压成本比 WAV 高(每个样本要做一次线性预测反推 + Rice 解码),但远比 Vorbis / Opus 低——FLAC 残差是固定的几字节运算,没有 transform。现代 CPU 上 FLAC 解码约 200-400 MB/s,完全够实时(60 秒音乐解压用不到 1 秒)。它**不能**做到 10 倍压缩,所以"体积 vs 解压成本"曲线上,FLAC 卡在中间:比 WAV 小一半,比 Vorbis / Opus 大十倍,质量是顶级(无损)但不够"省"。

## 4 · 有损压缩:丢掉耳朵听不见的东西

从这里开始是游戏工业真正的主力。**有损音频压缩**(lossy audio compression)的核心思想,可以用一句话概括:**用心理声学模型找出"耳朵听不见的成分",把它扔掉**。Vorbis、Opus、MP3、AAC——所有现代有损编码器,本质都是这套思路的实现,差异只在心理声学模型的精度和工程实现的取舍。

原始 PCM 里有多少信息是"耳朵听不见"的?答案是**绝大部分**。人耳能感知的声音有三个根本性的限制,每一个都是压缩的机会:

**第一,听觉阈值**。人耳对不同频率的最小可感知声压是不同的——3-4 kHz(耳道共振峰)最敏感,可以听到 0 dB SPL(参考声压 20 μPa);20 Hz 极低音和 18 kHz 极高频则要 60-80 dB 才听得见。任何低于阈值的频率成分,无论信号里有没有,**耳朵都收不到**。压缩器可以无损地把它扔掉。

**第二,频率掩蔽**(simultaneous masking / 频域掩蔽)。这是心理声学最神奇的特性——一个响亮的声音会"压制"周围频率上同时刻的较弱声音,让它们变得听不见。比如你在播 1 kHz、80 dB 的纯音,旁边 1100 Hz 处有一个 30 dB 的纯音——你**完全听不见** 1100 Hz。生理学原因:basilar membrane(基底膜)在 1 kHz 位置被激活时,周围位置的阈值被推高了。这意味着压缩器可以**在 1 kHz 周围扔掉大量低能量内容**,你听不出来。

**第三,时间掩蔽**(temporal masking)。一个响亮的声音不仅掩蔽同时刻的,还掩蔽**它前面**约 5 ms(前向掩蔽)和**它后面**约 200 ms(后向掩蔽)的较弱声音。这就是为什么枪声之后的低音细节听不见——你的听觉系统还在"恢复"。压缩器据此可以丢掉 transient 前后窗口里的小信号。

把这三件事放在一起:一段 PCM 里**有效信息**只占原始字节的 5-10%。剩下 90-95% 是耳朵阈值以下的、被掩蔽的、或纯冗余的。有损压缩的目标是:**找出那 5-10% 留着,其余的扔掉或粗化**。这就是为什么 10:1 的压缩比下你听不出差别——丢掉的那 90% 你本来也听不见。

**有损编码器的通用管线**。几乎所有现代有损音频编码器都遵循同一套结构:

1. **时频变换**(time-frequency transform)。把 PCM 分成短帧(典型 2.5-60 ms),每帧做 MDCT(改进离散余弦变换,Modified Discrete Cosine Transform)或类似的滤波器组,得到频域系数。MDCT 是 overlapped 的(相邻帧 50% 重叠)和 alias-cancellation 的——这是为了时间分辨率和频率分辨率的折衷,详情参见 [DSP 基础](dsp-fundamentals.md) 里关于 windowed FFT 的讨论。
2. **心理声学模型**(psychoacoustic model)。对同一帧并行算一个 FFT,估计每个频率的掩蔽阈值——这个频率上低于多少 dB 的成分耳朵收不到。
3. **量化与编码**(quantization and coding)。把 MDCT 系数除以一个**步长**(step size)取整——这就是真正"丢信息"的步骤。步长越大,系数越粗,体积越小,误差越大。把每个系数"分到多少比特"的决策,由心理声学模型引导:听觉敏感的频率分多比特,听觉不敏感的(或被掩蔽的)频率分少比特甚至 0。
4. **熵编码**(entropy coding)。量化后的系数用 Huffman 或算术编码进一步压(类似 [asset 压缩](../../phase-4/deep-dives/asset-compression.md) 讲的 DEFLATE = LZ77 + Huffman,这里没有 LZ77 部分,只做熵编码)。

输出是连续的码流,每帧约 100-200 字节就够透明码率下的一帧立体声。解码时反向:熵解码 → 反量化 → IMDCT → overlap-add 回 PCM。

注意这套管线的**两层"压缩"**:量化(有损,信息永久丢失)+ 熵编码(无损)。有损部分决定了"听起来有多像原始",熵编码部分决定了"同样的量化结果能再省多少字节"。Opus 之所以强,主要是这两层都做得很精细,且**自适应**:信号简单(静音)时分配少比特,信号复杂(transient)时分配多。

下面四节分别讲四个主流格式——Vorbis、MP3、Opus、ADPCM——它们都是这套管线的变种。

## 5 · OGG Vorbis:游戏工业的老黄牛

**Vorbis** 是 Xiph.Org 在 2000-2002 年间推出的有损音频编码器,作为 MP3 的开源替代品。它通常封装在 **Ogg** 容器里(所以叫 "Ogg Vorbis"),Ogg 是 Xiph 自家的流式容器格式,设计上可以封装 Vorbis、Opus、FLAC、Theora 等任何 Xiph 编解码器。

Vorbis 的特性使它在游戏工业一度占据统治地位:**完全免费**,没有 MP3 那种历史上让 Valve / Id / Epic 头疼的专利授权费(Fraunhofer 在 1990s 末对 MP3 解码器索取每份 0.75-1.5 美元的版税,直接催生了 Vorbis 项目);质量在 128 kbps 以上透明(transparency,即听不出和原始 PCM 区别);解码速度足够实时;开源实现(tremor、libvorbis)成熟稳定。从 Bungie 的《Halo》到《Minecraft》到 Unity 的默认音频导入,Vorbis 是 2005-2015 年间游戏 BGM 的事实标准。

**Vorbis 的算法**。它用大窗口的 MDCT(长窗 2048 样本,或 transient 时切换到短窗 256 样本)做时频变换,后接一个**前后向预测**耦合两声道、心理声学引导的步长分配、码本(codebook)做向量量化。Vorbis 不像 MP3 直接给每个系数分配比特,而是把一组系数当作"向量"在码本里查表,这种"向量量化"在低码率下更高效。代价:码本设计复杂,编码端慢。

**质量参考**:立体声 48 kHz,**128 kbps** 已经对绝大多数素材透明;**96 kbps** 有训练耳朵能听出 artifacts(尤其 harpsichord、castanet 这种 transient + 谐波素材);**64 kbps** 开始能听出"水声"(flanging artifact);**48 kbps 以下**质量明显下降。这就是为什么游戏里 BGM 通常用 112-160 kbps Vorbis——足够小,听不出区别。

**Rust 用 lewton 解 Vorbis**:

```toml
lewton = "0.10"
```

```rust
use lewton::inside_ogg::OggStreamReader;
use std::fs::File;

let mut reader = OggStreamReader::new(File::open("bgm.ogg")?)?;
println!("{} Hz, {} ch", reader.get_sample_rate(), reader.get_channels());

// 流式读,每次给一帧(MDCT 帧的样本)
while let Some(packet) = reader.read_dec_packet()? {
    // packet.0 是样本(interleaved Vec<i16>)
    // packet.1 是样本数(每个声道)
    for &s in &packet.0 {
        let _v: f32 = s as f32 / 32768.0;
        // 喂给 mixer
    }
}
```

`read_dec_packet` 一次返回一个解码后的 MDCT 帧(典型几百到几千样本)。这是流式解码的最小单位,你不用把整个文件读进来。HH 项目里 BGM 通常用 Vorbis 就是因为这种流式友好。

**Vorbis 的坑**。它的解码 CPU 占用比 Opus 高 30-50%(虽然绝对值仍然小,1 个 100 MB 包月的手机上可能成为瓶颈);它的"pre-skip"(开头丢弃的样本数,用于 MDCT warm-up)是固定的,而 Opus 的 pre-skip 可调,这让 Opus 在低延迟语音里完胜。但 Vorbis 的最大问题是**它已经停止发展**——Xiph 团队 2012 年起全力转向 Opus,Vorbis 不再得到改进。今天开始新项目,BGM 我会直接选 Opus;Vorbis 主要是历史包袱。

## 6 · MP3:历史遗产

**MPEG-1 Audio Layer III**(MP3)是 1993 年 Fraunhofer IIS 发布的,1990s 末随 Napster 风靡全球,是"数字音乐"的同义词。它和 Vorbis / Opus 用同一套"MDCT + 心理声学"管线,只是各项参数(窗口大小、心理声学模型精度)被 1993 年的算力上限束缚,质量在同样码率下**显著差于** Vorbis 和 Opus。

那为什么还有人用 MP3?**兼容性**。地球上几乎每个能播音频的设备——从 1998 年的便携 MP3 player 到今天的车机——都支持 MP3。Unity / Unreal 默认导入 MP3 不会出错。但这些理由在原生开发的 HH 项目里都不成立,Casey 自己写解码(或者你引第三方库)能挑任何格式,所以**新游戏不要用 MP3**。

**两个具体的避雷点**。第一,MP3 的专利在 2017 年到期(美国),现在没授权费问题了,但这是历史问题遗留的"心理负担"——很多公司禁止用 MP3 的内部政策仍然没改。第二,MP3 的 frame 是固定的(每帧 1152 样本,固定码率模式),但开头有约 2400 样本的 delay,**和视频同步时**会有可察觉的偏差;游戏里你同步音乐和动画,这个 delay 可能引起"音乐比动画早 50 ms"的奇怪感觉。Opus 把这个 delay 显式声明在文件头里,你能精确补偿。

我不打算花大篇幅讲 MP3 的算法——它和 Vorbis / Opus 思路一样,只是更老更糙。读完这一节你的收获应该是:**MP3 是历史遗产,新项目不要选它**,所以下面我们专注讲真正的现代选择。

## 7 · Opus:为什么它是新王者

**Opus** 是 2012 年 IETF 标准化(RFC 6716)、由 Xiph.Org + Skype(Microsoft)+ Mozilla 联合开发的格式。它一举取代了 Vorbis 和 Skype 自家的 SILK 编码器,成为现代实时音频(语音通话、游戏网络语音、WebRTC)和音乐分发的首选。Opus 在**任何码率下**质量都不输 Vorbis / MP3,在低码率下(64 kbps 以下)**显著优于**它们,且解压延迟可低至 5 ms——这是 Vorbis / MP3 做不到的。

**Opus 的核心创新:自适应地混合两种编码器**。Opus 内部实际上是两个独立的编码器——**SILK** 和 **CELT**——加上一个智能切换层:

- **SILK** 来自 Skype,是专为**人声**优化的语音编码器。它用线性预测(Linear Predictive Coding, LPC)建模声道——把人声分解成"激励信号 + 声道滤波器"两部分。LPC 对人声极其高效(说话本质上是激励通过共振峰),64 kbps 以下甚至能压到 8 kbps 还能听懂,但音乐用 SILK 会失真(音乐不符合 LPC 模型)。
- **CELT** 来自 Xiph,是**音乐 / 通用**编码器,本质上是 MDCT + 心理声学(类似 Vorbis 但更精细)。它在 48 kbps 以上透明度极高,但低码率下不如 SILK 高效。

Opus 的魔法是:**根据内容自动决定用 SILK 还是 CELT,或者两者的混合**。说话多的内容(网络语音、对白)用 SILK;音乐用 CELT;中间过渡态(音乐里有人声)用混合模式。码率 8-64 kbps 之间 Opus 在 SILK / 混合 / CELT 之间无缝切换;64 kbps 以上纯 CELT。这一切对调用者**完全透明**——你只设一个 target bitrate,Opus 自己决定每帧用什么模式。

**Opus 的 frame size 可调**——从 2.5 ms 到 60 ms。这意味着你可以用 Opus 做**低延迟编码**:5 ms 一帧,加上网络 30 ms,玩家语音总延迟约 50 ms,完全适合 FPS / 格斗游戏这种对延迟敏感的场景。Vorbis 的最小帧约 2.5 ms 但实际工程实现只支持 ~50 ms 以上的 frame size,做不了低延迟。

**质量对比**(立体声 48 kHz,常用码率):
- 128 kbps Opus vs 128 kbps Vorbis vs 128 kbps MP3:三者对绝大多数素材透明,盲听难分。
- 96 kbps:Opus 仍然透明,Vorbis 极少数素材(弦乐、cymbal)能听出 artifact,MP3 普遍能听出。
- 64 kbps:Opus 接近透明,Vorbis 有明显"水声",MP3 严重失真。
- 32 kbps(单声道):Opus 仍然清晰可懂,Vorbis 退化为电话音质,MP3 几乎不可用。

这就是为什么我说**今天开始的项目,BGM 选 Opus,网络语音必选 Opus**。

**Rust 用 audiopus 或 opus crate**:

```toml
opus = "0.3"
```

```rust
use opus::{Encoder, Decoder, Application};

// 编码
let mut encoder = Encoder::new(48000, 2, Application::Audio)?;
let mut output_buf = vec![0u8; 4000];  // Opus 帧最大 ~4000 字节
// 一帧 20 ms @ 48 kHz stereo = 1920 samples
let encoded_bytes = encoder.encode(&pcm_interleaved, &mut output_buf)?;
// encoded_bytes 通常远小于输入的 4 倍(有损压缩)

// 解码
let mut decoder = Decoder::new(48000, 2)?;
let mut pcm_out = vec![0i16; 1920];
let n = decoder.decode(&encoded[..encoded_bytes], &mut pcm_out, false)?;
// pcm_out[..n*2] 是解码后的样本
```

注意 `Application::Audio` 这个参数——Opus 提供三种 application:`VoIP`(人声优先,启用 VBR / DTX / 不连续传输)、`Audio`(通用音乐)、`LowDelay`(极低延迟,frame size 5 ms)。**游戏 BGM 用 `Audio`,网络语音用 `VoIP`,竞技语音用 `LowDelay`**。这个选择会让编码器在内部切换不同的策略,你不能事后改。

## 8 · ADPCM:为大量 SFX 而生的轻量级

**自适应差分脉冲编码调制**(Adaptive Differential PCM, ADPCM)是一个非常不同的思路,主要用在游戏里大量短 SFX 的场景。它不基于 MDCT,也不基于心理声学——它是个**纯时域**的轻量级压缩,把每个样本和前一个样本的**差值**编成 4-bit(原始 16-bit),压缩比固定 4:1。预测器随信号自适应(对低频用大预测系数,对高频用小预测系数)。

最常见的是 **IMA ADPCM**(也写成 IMA4,Microsoft 的变种叫 ADPCM WAV)。质量在 4:1 压缩下接近"低码率 MP3",对低频素材效果不错,对高频素材(transient)有可听见的"沙沙"噪声。**最大的优点是解码成本极低**——每个样本就是两次乘加 + 一次查表,可以做到 50 ns/sample,这意味着 1000 个 SFX 同时解压用不到 1% CPU。

**为什么它曾经统治游戏**。PlayStation 1 / 2 时代的游戏机内存只有几 MB,无法容纳大量 PCM SFX,而当时 MP3 解码对 1994 年的 R3000A CPU 来说太重。ADPCM 提供了"4 倍压缩 + 几乎零解压成本"的完美平衡,PS1 的 SPU 硬件直接支持 ADPCM 解码。所有 PS1 / PS2 游戏的音效都是 ADPCM。

**今天还用 ADPCM 吗?** 仍然是 indie 游戏和移动游戏大量 SFX 的选项,特别是当 SFX 非常多(比如 procedurally generated 的脚步声、不同地形音)且每个 SFX 又很短(几秒)的情况——这种场景 Vorbis / Opus 的解压成本可能成为瓶颈(同时解 200 个 Vorbis 流 = 10-15% CPU,解 200 个 ADPCM 几乎不可察觉)。但 ADPCM 的质量明显差于 Vorbis / Opus,所以**只在"质量可以容忍,数量极大"的场景选它**。HH 项目里我建议:音效用 Vorbis(质量优先),除非你真的 SFX 数量破万,再考虑 ADPCM。

## 9 · 流式解码:游戏 BGM 的真正需求

到这里你已经知道每种格式本身。但游戏里有个**工程问题**比格式选择还重要:**BGM 一小时,你不能把它整个解码进内存**。1 小时 Opus 大约 60 MB(64 kbps),但解码成 PCM 是约 700 MB stereo——内存爆。你必须**边读磁盘边解码边播,只在内存里保留一小段 PCM**。这就是流式解码。

**双缓冲流式解码**(double-buffered streaming)是游戏音频流式播放的标准模式。基本思路:在内存里维持**两个 PCM 缓冲区**,每个 buffer 装一"chunk"(典型 1-2 秒 PCM)。当 mixer 在播 buffer A 时,后台线程在解码 buffer B;当 A 播完,swap,A 变成下一轮的"在解码",B 变成"在播"。如此往复,内存里永远只有约 2-4 秒 PCM。

下面是这个模式的 Rust 实现(简化,省略线程同步):

```rust
use std::sync::mpsc;
use std::thread;

pub struct StreamingDecoder {
    sample_rate: u32,
    channels: u16,
    // 后台线程通过这个 channel 把解码好的 chunk 送过来
    chunk_rx: mpsc::Receiver<Vec<f32>>,
}

impl StreamingDecoder {
    pub fn open(path: &str, chunk_samples: usize) -> std::io::Result<Self> {
        // 用 lewton / claxon / opus 打开文件,获取 sample_rate / channels
        // 然后启动后台解码线程
        let (tx, rx) = mpsc::channel::<Vec<f32>>();
        let path = path.to_string();
        thread::spawn(move || {
            // 伪代码:具体看用的库
            let mut reader = open_format_specific_reader(&path).unwrap();
            loop {
                let mut buf = vec![0f32; chunk_samples];
                let n = reader.read_samples_f32(&mut buf);  // 一次读 chunk_samples
                if n == 0 { break; }  // EOF
                buf.truncate(n);
                if tx.send(buf).is_err() { break; }  // 主线程 drop 了 rx
            }
        });
        // 先送一个 chunk,让 mixer 启动时就有数据
        let _first_chunk = rx.recv().unwrap();
        Ok(Self {
            sample_rate: 48000,
            channels: 2,
            chunk_rx: rx,
        })
    }

    /// mixer 调用:取下一个 chunk。如果后台还没解完,会阻塞。
    /// 生产代码应该用 ring buffer + try_recv 做无锁版本。
    pub fn next_chunk(&mut self) -> Option<Vec<f32>> {
        self.chunk_rx.recv().ok()
    }
}
```

**实际的两个关键细节**:

**第一,chunk 大小的选择**。chunk 太小(比如 10 ms),后台线程被唤醒太频繁,上下文切换浪费 CPU;chunk 太大(比如 30 秒),内存占用大且启动延迟长(开始播之前要先解 30 秒)。游戏 BGM 经验值是 **500 ms 到 2 秒**——足够大避免频繁唤醒,足够小让启动时延可接受。

**第二,预读(prefetch)和 backpressure**。当 mixer 在播当前 chunk 时,后台线程应该**已经在解下一个 chunk**——否则一旦 mixer 用完当前 chunk,就要等后台现解,产生卡顿。所以 channel 容量应该 ≥ 2(两个 buffer 都允许预解好,等 mixer 来取)。如果后台跟不上(mixer 消耗速度 > 解码速度),你要么降低质量(更小 chunk),要么显示式 drop frames(对音乐不可接受,对网络语音可接受)。Opus 的解码速度通常远快于实时(单核 200x 实时),所以本地 BGM 流式不会卡。

**第三,无缝循环**。游戏 BGM 通常要循环——menu 音乐循环、battle 音乐循环。如果你用文件级别的"播完从头",loop 边界会有"咔嗒"(两个 chunk 衔接处 PCM 不连续)。正确做法:在 loop 边界做 **crossfade**(前后各 50 ms 淡入淡出叠加)或者读取文件里嵌入的 loop point cue(某些 WAV / OGG 支持),在循环点精确地接上。Opus 因为 frame-based,loop 边界天然对齐到 frame 边界(通常 20 ms),所以artifact 比 Vorbis / WAV 小。

读完这一节你应当能在 HH 项目里实现一个 `StreamingMusicSource` trait,让 mixer 把它当作普通 voice(每帧调 `read_samples(&mut out)`),但内部跑双缓冲流式解码,内存占用恒定在几 MB。

## 10 · 怎么给游戏选格式

到此你有了所有材料,现在讲选择。我不用表格——因为格式选择不是查表,是**从用途反推**。每一种声音资产在游戏里都有它的"职责",职责决定了对**质量**、**体积**、**解压成本**、**延迟**四件事的优先级,优先级决定了格式。

**音效(SFX)** 是数量大、单次短的素材。脚步、枪声、UI 点击、爆炸——单个一两秒,但游戏里有几千个。这里**解压成本**比体积更重要:你可能在某一帧同时触发 50 个音效(爆炸 + 碎片 + 火焰 + 喊声 + UI 反馈),每个都要解码,瞬间 CPU 峰值。Vorbis 解压速度足够(每秒约 200-400 MB/s),50 个并发解码也就是 10-20% 一个核心,可承受;Opus 类似。但如果你有 1000 个并发(超出实际),就该考虑 ADPCM。**音效不用流式**——它们太短,直接整个解码进内存,可能用 Vorbis 解一次转 PCM 缓存起来,后续播放零成本。这是 HH 项目里 SFX 的最常见做法:在 load 时把 OGG 解成 PCM 存内存,play 时 mixer 直接读 PCM。这样体积(ship 的是压缩的)和解压成本(只解一次)都最优。

**音乐(BGM)** 是数量少、单次长的素材。一首 5 分钟,总共可能就 20-50 首音乐,但每首巨大。这里**体积**比解压成本更重要,且**必须流式**(不能整个解码进内存)。Opus 64-96 kbps 几乎透明,5 分钟音乐只占 2.5-4 MB。Opus 是首选;Vorbis 是次选(已经 ship 的项目);FLAC 是"零损失信仰"项目选(体积大 10 倍但绝对无损)。

**网络语音** 是实时、双向、对延迟敏感的场景。玩家麦克风录入,编码,网络发送,对方解码播放。这里**延迟**最重要,然后是低码率(节省带宽)。**Opus 是唯一合理的选择**:5 ms frame size,8-32 kbps 码率,VoIP 模式启用 VBR / DTX(没说话时不传)。Vorbis / MP3 在这个场景下完全不行,frame size 太大、低码率质量差。

**母带 / 工作格式** 是你拿到录音棚 master 后内部存什么。**WAV 或 FLAC**,永远不要用有损——任何中间步骤都加损失,反复编辑会累积 artifact。FLAC 节省一半磁盘但需要解码,WAV 占空间但 memcpy 即可,看你磁盘 vs CPU 的 trade-off。专业流程通常 master 存 FLAC,ship 前用一次转码到 Opus / Vorbis。

**一个具体的 HH 决策树**:看 `game_sound.rs` 里要播放的素材,问三个问题——**多长?多少个同时播?对延迟敏感吗?** 1-2 秒的 SFX,无论多少,Vorbis(ship)+ 解到 PCM(运行时);5 分钟以上的音乐,无论多少,Opus + 流式;玩家麦克风输入,Opus + 低延迟模式;录音棚 master,FLAC。这三个问题问完,99% 的资产答案就清楚了。

## 11 · 解码成本和实时性能

上面说了"解压成本"很重要,但具体数字是多少?这节给一个直觉性的尺度感,让你心里有个 baseline。所有数字都是约值,具体看你 CPU 和编译参数。

**WAV / PCM**:解压成本是**零**。memcpy 16-bit 样本到 f32 数组,基本是内存带宽限制(几个 GB/s),60 秒 stereo PCM 复制用不到 1 ms。这就是为什么 SFX 解一次到内存后续播放完全免费。

**FLAC**:解压成本约 200-400 MB PCM/s。一个核心上跑实时 48 kHz stereo(0.19 MB/s)用不到 0.1% CPU。FLAC 解码非常快,因为它只是反预测 + Rice 解码,无 transform。

**Vorbis**:解码速度约 100-300 MB PCM/s。实时 48 kHz stereo 占 0.1-0.3% CPU 一个核心。同时解 100 个 Vorbis 流 = 10-30% 一个核心,开始有点压力但还能扛。Opus 比 Vorbis 快 30-50%,且低码率下质量更好。

**Opus**:解码速度约 200-500 MB PCM/s,且支持 SIMD 优化(Opus 库内部有 SSE / NEON 实现)。一个核心实时解码几十路 Opus 流毫无压力。

**ADPCM**:解码速度极快,基本是内存带宽限制。1 个 sample = 2 次乘加 + 1 次表查找,约 50 ns/sample,折合 80 MB PCM/s——慢的看上去比 FLAC 还低,但 ADPCM 是 4-bit 输入,所以**单位输入字节的解码速度**远高于 FLAC。1000 个 ADPCM SFX 并发占用可忽略。

**实时音频的预算**。在 48 kHz、buffer size 480 sample(10 ms)的设定下,你有 10 ms 处理一帧。一个 4 核 CPU 跑 4 GHz,10 ms 是 4 千万周期。一个 biquad(见 [DSP 基础](dsp-fundamentals.md))约 6 ns/sample,480 sample = 3 μs,可以同时跑**数千个** biquad。一个 Opus 解码 480 sample(20 ms frame)约 5 μs,可以同时解**上百路** Opus。所以 CPU 通常**不是瓶颈**,真正限制并发的是**内存带宽**(同时混 256 个 voice 时,每个 voice 一帧读 480 sample × 4 byte = 1.9 KB,256 路 = 0.5 MB / 帧 = 50 MB/s,完全可承受)。

**所以什么时候解码成本真的成为问题**?三种情况:第一,移动端 / 老硬件(CPU 慢 5-10 倍),且 SFX 数量极大(>500 同时),此时考虑 ADPCM;第二,网络语音大量并发(MMO 100 人同房间说话),Opus 解码 100 路约 0.5 ms 一个核心,仍可承受,主要瓶颈是上行带宽而非解码;第三,你写了自己的 SIMD 不友好的解码器,这种情况下用社区优化过的库(lewton、opus、claxon)会立刻解决。

## 12 · 生产现实:你不写编解码器,但你要会选

游戏开发里你几乎不会自己写 Opus / Vorbis / FLAC 编解码器——这些是十年以上工程师打磨的复杂代码(Opus 的 reference 实现有 5 万行 C,涉及大量 SIMD 优化、心理声学精细调参)。你用现成库,但你**必须懂格式之间的取舍**,才能正确选型和调参。这节列出 Rust 生态里每个格式对应的库,以及实际项目里你要做哪些"参数调优"决策。

**库选型**。Vorbis 解码用 [`lewton`](https://crates.io/crates/lewton)(纯 Rust,安全)或 [`vorbis`](https://crates.io/crates/vorbis)(libvorbis FFI,更快);Opus 编解码用 [`opus`](https://crates.io/crates/opus) 或 [`audiopus`](https://crates.io/crates/audiopus);FLAC 解码用 [`claxon`](https://crates.io/crates/claxon)(纯 Rust);想要一个"什么都解"的统一接口,用 [`symphonia`](https://crates.io/crates/symphonia)——它支持 WAV、Vorbis、FLAC、MP3、Opus 等,API 统一,适合做 asset pipeline。HH 项目里我推荐 symphonia 作为运行时音频库,单一依赖管理所有格式。

**参数调优的几个常见决策**:

**Vorbis quality vs bitrate**。`oggenc` 有 `-q` 参数(-1 到 10)和 `-b` 参数(目标 bitrate kbps)。`-q 5` 对应约 160 kbps(默认),`-q 3` 约 112 kbps,`-q 6` 约 192 kbps。游戏 BGM 通常 `-q 4`(约 128 kbps)足够透明。**永远用 VBR**(variable bitrate),不要用 CBR——VBR 在简单段落(静音、单一乐器)省字节,复杂段落给多字节,同等平均码率下质量远高于 CBR。

**Opus 的 bitrate 选择**。Opus 的 `Encoder::set_bitrate` 接受 6-510 kbps。游戏音乐 64-96 kbps 立体声足够透明;网络语音 24-32 kbps 单声道清晰可懂;高保真音乐 128-192 kbps。**永远启用 VBR**(`Encoder::set_vbr(true)`),和 DTX(仅 VoIP 模式,没说话时不传字节)。Opus 的 `set_complexity`(0-10)调编码 CPU,默认 10(最慢但质量最好),实时编码降到 5 也基本无质量损失。

**FLAC 的 compression level**。`flac` 命令行有 `-0` 到 `-8` 八级。level 越高编码越慢,压缩比越好,但**解码速度不变**(解码只读必要信息)。level 5(默认)是 sweet spot。level 8 比 5 多花 3 倍编码时间,体积只小 1-2%。**build 时用 8,运行时编解码根本不发生**(ship 出去的 FLAC 是预先编好的)。所以你 ship 前跑一次 `flac -8` 就行。

**采样率选择**。游戏音频几乎都是 **48 kHz**——这是视频和游戏的标准,任何高于此的(96 / 192 kHz)对游戏体验无意义,只会增加体积。Opus / Vorbis 在 48 kHz 上调优最好。如果你拿到的素材是 96 kHz,build 时用 ffmpeg / sox 降采样到 48 kHz(ship),不要 ship 96 kHz。

**声道选择**。音乐几乎总是 stereo(2 声道)。SFX 经常是 mono(单声道,游戏中可以 pan 到任意位置——这比 stereo SFX 灵活,因为立体声 SFX 的左右平衡是固定的)。Mono SFX 体积只有 stereo 的一半,且 mixer 可以 spatial 化。Opus / Vorbis 都支持 mono 和 stereo,选 mono 对 SFX 是好选择。

读完这一节,你的工具链应该清晰:**asset pipeline 用 ffmpeg / sox 把 master 转成 ship 格式**(BGM 转 Opus 96 kbps VBR,SFX 转 Vorbis `-q 4`),**运行时用 symphonia 或专用库解码**。编解码细节交给库,你做的是**选格式和调参数**。

## 13 · 在你 HH 项目里动手(做中学红线)

这一节把前面的概念落地到 HH 代码里。你需要做四件事:A/B 测试、CPU 测量、流式解码、按用途分格式。每一件都给你具体的入口和验证标准。

**第一步:A/B 听感测试**。拿一个 5 秒的素材(最好是包含 transient 的素材,比如军鼓、castanet、harpsichord——这些是 lossy 最容易暴露 artifact 的),转成 5 个版本:WAV 原始、Vorbis `-q 5`(~160 kbps)、Vorbis `-q 3`(~112 kbps)、Opus 96 kbps、Opus 48 kbps。然后写一个 HH 测试模式,按 1-5 键切换播放哪个版本,盲测自己能不能听出区别。

```bash
# 准备 5 个版本
ffmpeg -i master.wav -c:a copy sfx_test.wav
ffmpeg -i master.wav -c:a libvorbis -q:a 5 sfx_vorbis_q5.ogg
ffmpeg -i master.wav -c:a libvorbis -q:a 3 sfx_vorbis_q3.ogg
ffmpeg -i master.wav -c:a libopus -b:a 96k sfx_opus_96.opus
ffmpeg -i master.wav -c:a libopus -b:a 48k sfx_opus_48.opus
ls -lh sfx_*  # 看体积对比
```

经验:大多数素材 Opus 96 kbps 和 WAV 区分不出来;Vorbis `-q 3` 在 castanet / harpsichord 上能听出"沙沙";Opus 48 kbps 在素材简单(单一乐器)时仍然清晰,素材复杂(密集和声)时开始有 artifact。这一步建立你对"透明码率"的第一手感觉。

**第二步:解码 CPU 测量**。写一个 micro-benchmark,把每个格式解 100 次同一个素材,测平均时间。用 Rust 的 `std::time::Instant`:

```rust
use std::time::Instant;
use std::fs::File;

fn bench_vorbis(path: &str, iters: u32) -> f64 {
    let start = Instant::now();
    for _ in 0..iters {
        let mut reader = lewton::inside_ogg::OggStreamReader::new(
            File::open(path).unwrap()
        ).unwrap();
        while reader.read_dec_packet().unwrap().is_some() {}
    }
    start.elapsed().as_secs_f64() / iters as f64
}

fn bench_opus(path: &str, iters: u32) -> f64 {
    // 用 opus crate 解 .opus 文件(.opus 是 Ogg 容器 + Opus payload)
    // 需要先剥离 Ogg 容器,然后用 opus::Decoder 解每帧
    // 实现略,API 见 opus crate 文档
    0.0
}

fn main() {
    let wav_time = bench_wav("sfx_test.wav", 100);
    let vorbis_time = bench_vorbis("sfx_vorbis_q5.ogg", 100);
    let opus_time = bench_opus("sfx_opus_96.opus", 100);
    println!("WAV:    {:.2} ms", wav_time * 1000.0);
    println!("Vorbis: {:.2} ms", vorbis_time * 1000.0);
    println!("Opus:   {:.2} ms", opus_time * 1000.0);
}
```

我预期:WAV 几乎测不出来(<0.1 ms);Vorbis / Opus 解 5 秒素材约 5-15 ms(实时倍数 300-1000x)。这个数字让你心里有底——BGM 实时解码用 0.3% CPU,可以放心流式。

**第三步:实现流式 BGM 解码**。这是 HH 项目里最重要的工程练习。在 `game_sound.rs` 里加一个 `StreamingMusicSource`:

```rust
use std::sync::mpsc;
use std::thread;
use std::time::Duration;

pub struct StreamingMusic {
    chunk_rx: mpsc::Receiver<Vec<f32>>,
    current_chunk: Vec<f32>,
    cursor: usize,
    sample_rate: u32,
}

impl StreamingMusic {
    pub fn open(path: &str) -> Self {
        let (tx, rx) = mpsc::sync_channel(2);  // 预读 2 个 chunk
        let path_owned = path.to_string();
        thread::Builder::new()
            .name("bgm_decoder".into())
            .spawn(move || {
                // 用 lewton / opus / claxon 打开,具体看格式
                let mut reader = open_decoder(&path_owned);
                let chunk_samples = 48000 * 2;  // 1 秒 stereo PCM
                loop {
                    let mut buf = vec![0f32; chunk_samples];
                    let n = reader.read_decoded(&mut buf);
                    if n == 0 { break; }
                    buf.truncate(n);
                    // 阻塞直到 mixer 取走一个 chunk,实现 backpressure
                    if tx.send(buf).is_err() { break; }
                }
            })
            .unwrap();

        StreamingMusic {
            chunk_rx: rx,
            current_chunk: Vec::new(),
            cursor: 0,
            sample_rate: 48000,
        }
    }

    /// mixer 调用:填 `out` 下一段样本。如果当前 chunk 用完,取下一个。
    pub fn read_samples(&mut self, out: &mut [f32]) -> bool {
        for slot in out.iter_mut() {
            loop {
                if self.cursor < self.current_chunk.len() {
                    *slot = self.current_chunk[self.cursor];
                    self.cursor += 1;
                    break;
                }
                // 当前 chunk 用完,取下一个(可能阻塞)
                match self.chunk_rx.recv_timeout(Duration::from_millis(100)) {
                    Ok(next) => {
                        self.current_chunk = next;
                        self.cursor = 0;
                    }
                    Err(_) => return false,  // EOF 或解码超时
                }
            }
        }
        true
    }
}
```

然后在 mixer 主循环里,把 `StreamingMusic` 当作一个永远在播的 voice,每帧调 `read_samples` 填 mixer buffer。验证标准:90 分钟 Opus BGM 在 HH 里播放,**内存占用恒定在 ~5 MB**(只有 2 个 chunk + reader state),不随音乐时长增长。这就是流式解码的胜利。

**第四步:给资产按用途选格式**。盘点 HH 项目里的所有音频资产,给每个分配格式:

- 玩家脚步 / 武器 / UI 这些短 SFX → Vorbis `-q 4`,load 时解成 PCM 缓存
- 主菜单 / 战斗 / 区域 BGM → Opus 96 kbps VBR,流式解码
- (如果 HH 有网络模式)玩家语音 → Opus 24 kbps VoIP 模式,5 ms frame
- 录音棚拿到的 master → FLAC,build 时转成 ship 格式

写一个简单的 `audio_pipeline.toml` 描述每类资产的转码规则,build 时用 ffmpeg / symphonia 批量转换。这就把今天讲的"格式选择"工程化了——你不再手动决定每个 wav 转 opus 还是 vorbis,而是按类别批量处理。

完成这四步,你 HH 项目里的音频管线就从 day009 的"裸 WAV"进化到真实游戏的"分类型压缩 + 流式解码"水平。

## 14 · 练习

### Lv1 · 转码体验

用 ffmpeg 把同一个 30 秒素材转成:WAV(原始 PCM)、FLAC、Vorbis `-q 5`、Vorbis `-q 3`、Opus 96k、Opus 48k、Opus 24k(mono)。`ls -lh` 看体积,从大到小排序。盲听一遍,记下你能听出差别的最低码率。把体积和听感结果写进 HH 项目 `notes/audio-codec-test.md`。

### Lv2 · WAV parser 手写

不看任何参考实现,从 RIFF spec(链接见延伸阅读)出发,自己写一个 WAV parser,支持 8 / 16 / 24 / 32-bit PCM 和 IEEE float 格式。测试它能在 HH 的 day009 音频文件上正确工作。**坑点**:8-bit PCM 是 unsigned,16-bit 是 little-endian signed,24-bit 是 3 字节 little-endian signed(需要手动组装),32-bit float 是 IEEE 754。

### Lv3 · 流式 Opus 解码器

在 HH 项目里实现一个 `OpusStreamer`,用 opus crate + 手写 Ogg 容器解析,实现双缓冲流式播放 90 分钟 Opus BGM,内存峰值不超过 8 MB。要求:支持无缝循环(loop point 处用 50 ms crossfade),支持运行时切换 BGM(淡出当前 + 淡入新的,各 200 ms)。验证:profiler 下内存恒定,CPU 在 4 核机器上单核占用 < 1%。

### Lv4 · 心理声学实验

写一个 Rust 程序演示**同时掩蔽**:生成两个正弦波叠加的信号——1 kHz、80 dB 的"掩蔽音" + 1.1 kHz、可调强度的"被掩蔽音"。让用户在 HH 里调被掩蔽音的强度,记录"刚好听不见"的阈值。验证该阈值是否与文献中的同时掩蔽数据(典型约 30-40 dB 差)一致。这个练习让你**亲耳听见**有损压缩为什么能扔掉 90% 数据——你的耳朵本身就是那个"心理声学模型"。

## 15 · 延伸阅读

本仓库本地资料(必读):
- [phase-0/22-signals-foundation.md](../../phase-0/22-signals-foundation.md) — 信号基础:采样定理、量化、Nyquist,音频压缩的物理前提
- [phase-5/deep-dives/dsp-fundamentals.md](dsp-fundamentals.md) — DSP 基础:MDCT、傅里叶变换,有损编码的数学地基
- [phase-5/deep-dives/audio-pipeline-complete.md](audio-pipeline-complete.md) — HH 完整音频管线,mixer 怎么吃 PCM
- [phase-5/deep-dives/fft-and-spectral-analysis.md](fft-and-spectral-analysis.md) — FFT 和频谱分析,MDCT 的"近亲"
- [phase-4/deep-dives/asset-compression.md](../../phase-4/deep-dives/asset-compression.md) — 通用 asset 压缩,LZ77 / Zstd 的另一面(lossless 通用)
- [phase-7/deep-dives/png-format-complete.md](../../phase-7/deep-dives/png-format-complete.md) — PNG 格式深度,图像端的"无损 + DEFLATE"对应音频的 FLAC + Rice

外部稳定 URL(可选):
- Opus 官方网站与 RFC 6716(权威规范):https://opus-codec.org/ 和 https://datatracker.ietf.org/doc/html/rfc6716
- Xiph.Org 的 "Monty" Montgomery 演讲 "Digital Audio Compression"(心理声学入门必看):https://www.xiph.org/video/vid2.shtml
- Vorbis 规范文档(I 格式 + 配置):https://xiph.org/vorbis/doc/
- FLAC 格式规范:https://xiph.org/flac/format.html
- RIFF WAVE 规范(MSDN,可读性最好的参考):https://learn.microsoft.com/en-us/windows/win32/xaudio2/resource-interchange-file-format--riff-
- Listening tests 网站(听感对比质量数据):https://listening-tests.hydrogenaud.io/
- ffmpeg 音频编码文档(转码工具链):https://trac.ffmpeg.org/wiki/Encode/Audio

真实开源源码:
- libopus(C reference 实现,IETF 标准参考):https://github.com/xiph/opus
- libvorbis(Vorbis reference):https://github.com/xiph/vorbis
- lewton(纯 Rust Vorbis 解码器,可读性极佳):https://github.com/RustAudio/lewton
- claxon(纯 Rust FLAC 解码器):https://github.com/ruuda/claxon
- symphonia(纯 Rust 多格式音频解码框架,推荐做 HH asset pipeline):https://github.com/pdeljanov/Symphonia
- Casey HH day009 的 WAV 加载代码(对照参考):https://github.com/HandmadeHero/handmade-hero/tree/main/code/day009

历史演化(可选):
- 1991 RIFF WAVE(Microsoft / IBM,Windows 3.1 时代)
- 1993 MP3(Fraunhofer IIS,专利锁死催生开源替代)
- 2000-2002 Vorbis(Xiph.Org,作为 MP3 的开源替代)
- 2001 FLAC(Xiph.Org,无损音频标准)
- 2012 Opus(Xiph + Skype + Mozilla,IETF 标准,RFC 6716)
- 2017 MP3 专利到期(美国),但生态已转向 Opus
- 2015-至今 WebRTC / Discord / Zoom 都用 Opus,游戏(Bungie、Id、Epic)也从 Vorbis 迁向 Opus
