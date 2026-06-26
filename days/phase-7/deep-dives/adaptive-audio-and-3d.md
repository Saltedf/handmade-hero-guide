---
phase: 7
title_en: "Adaptive Audio and 3D Positional Sound"
title_zh: "自适应音乐与 3D 空间音频全解"
type: deep-dive
domains: [game, audio, rust, linux, math, network]
bridges: ["day138", "day201", "day526", "day575"]
---

# 自适应音乐与 3D 空间音频全解

> 你跟着 HH Day 526 把 streaming audio 写完了。Day 575 你做了简单 mixer。但你的游戏里,BGM 还是**循环播放的一句 loop**——玩家走到 boss 房间,BGM 没换;玩家进入战斗,BGM 没变化;玩家从左边靠近 enemy,声音还是从中间出来。这是 1990s 的 audio 水平。现代游戏的 audio 是**活的**:音乐跟着情绪变化、声音跟着空间走。这一篇把**自适应音乐**(adaptive music)和 **3D 空间音频**(3D positional audio)两条线摊开:从 FMOD 的 vertical layering 到 Elias 的 ELIS 模型,从 stereo pan 到 HRTF 双耳线索,从距离衰减到 Doppler,从 Opus codec 到 voice chat。看完你就能给自己的游戏加上 FMOD/Wwise 级别的 audio system。

## 0 · 为什么要有这一篇

自适应音乐和 3D 音频是**游戏 audio 区别于音乐制作 audio** 的两个核心特征。看起来简单——"不就是根据 player 位置调个 pan 吗"——直到下面这些事让你陷进去:

1. **音乐切换不自然**:玩家从 explore 切到 combat,直接 crossfade 两段 BGM 听起来突兀。要做 bar-aligned transition、stinger(过渡音效)、平行 layer 增减。
2. **3D pan 听感单薄**:你用 sin/cos pan law 简单左右分配,听感是"在 headphone 里"而不是"在 3D 空间里"。要做 HRTF 才有真正的 out-of-head localization。
3. **距离衰减不对**:你用线性 1/r 衰减,近处太响,远处听不见。要做 log 衰减 + 距离归一化。
4. **遮挡不准**:墙后面声音应该闷,但你的 mixer 不知道墙存在。要做 occlusion ray cast + lowpass。
5. **Doppler 突兀**:你按公式直接 `f' = f·c/(c-v)`,运动方向反转时 frequency 跳变。要做 smoothing + speed clamp。
6. **Voice chat延迟太长**:你用 PCM 16-bit 48kHz 双工,每个 packet 50ms,echo 严重。要用 Opus 16kbps + FEC + jitter buffer。
7. **多 voice 干扰**:64 个玩家同时 voice chat,mix 后 clip + 听不清。要做 per-voice compression + spatialization 分散。

工业级 adaptive audio middleware(FMOD Studio、Wwise、Elias、CRI ADX2)解决这些问题花了**几十人年**。这一篇把这些问题逐一摊开:理论 → 算法 → Rust 实现 → 性能数据 → 真实坑。

**读完这一篇,你应该能**:
- 解释 horizontal re-sequencing 和 vertical re-orchestration 的区别,设计一个 adaptive music 系统
- 解释 ELIS(Emotion-Like Interactive Scoring)模型的工作原理
- 推导 HRTF 的物理意义,实现 stereo-to-binaural 渲染
- 实现 ITD(Inter-aural Time Difference)和 ILD(Inter-aural Level Difference)双耳线索
- 实现距离衰减(distance attenuation)、遮挡(occlusion)、房间反射(early reflections)
- 推导 Doppler effect 公式,实现 smoothed Doppler
- 解释 Opus codec 算法,Celt + SILK 混合策略
- 实现 voice chat 完整 pipeline:capture → encode → network → jitter buffer → decode → spatialize → mix → render
- 用 Rust + `rodio` / `kira` / `bevy_audio` 实现一个 game-ready 3D audio engine

假设你已掌握:**22-signals-foundation**(Nyquist、frequency、amplitude)、**dsp-fundamentals**(FIR/IIR/FFT/convolution)、**synthesis**(oscillator/envelope/LFO)、**audio-effects**(reverb/EQ/compressor,见 [audio-effects.md](../phase-5/deep-dives/audio-effects.md))。如果其中任何一项不熟,先回去补。

## 1 · Adaptive Music 概念

### 1.1 传统线性音乐 vs 自适应音乐

**线性音乐**(linear music):作曲家写一首 3 分钟的曲子,玩家触发后从头播到尾。再 loop。这就是 HH Day 526 的 streaming playback。简单,但**与游戏状态无关**——玩家在 cutscene 听这段,在 boss 战听这段,在 idle 也听这段。

**自适应音乐**(adaptive music):音乐**根据游戏状态变化**。玩家进入战斗,音乐加快;玩家接近 boss,音乐加 tension;玩家死亡,音乐切换到 mournful 版本。

自适应音乐有两大流派:

| 流派 | 英文 | 做法 | 代表 |
|---|---|---|---|
| **水平重排** | Horizontal re-sequencing | 多段独立 music segment,按游戏状态切 | FMOD / Wwise 的 Music Playlist |
| **垂直重组** | Vertical re-orchestration | 多个 layer(drum、bass、melody)按状态增减 | FMOD / Wwise 的 Multi-Instrument |

工业级 audio engine 通常**两者结合**——既有水平切换,又有垂直 layering。

### 1.2 Horizontal re-sequencing:水平重排

**结构**:作曲家写 N 段独立 music segment(exploration、combat、tension、victory、defeat)。游戏状态决定播哪一段。

**关键问题:切换怎么无缝?**

简单切换会"啪"地中断当前 segment,听感突兀。解决方案:

1. **Bar-aligned switching**:等待当前 segment 播完一个小节(bar),在下个小节开头切。这要求所有 segment 同 BPM、同 time signature。FMOD / Wwise 都这么做。

2. **Sync transition**:新旧 segment 在同一个 downbeat 切换,中间用 transition region(过渡区域)blend。

3. **Stinger**:一两拍的 transition sound effect,盖住切换的不连续。例如 combat → exploration 切换时,加一个 cymbal swell。

4. **Crossfade**:在 transition 区域里,旧 segment fade out,新 segment fade in,持续 1-2 秒。

Rust 抽象:

```rust
pub struct MusicSegment {
    pub samples: Vec<f32>,        // stereo interleaved
    pub bpm: f32,
    pub beats_per_bar: u32,       // 4 for 4/4
    pub sample_rate: f32,
    pub current_pos: usize,       // playback position
    pub name: String,
}

impl MusicSegment {
    pub fn samples_per_beat(&self) -> usize {
        (60.0 / self.bpm * self.sample_rate) as usize
    }

    pub fn samples_per_bar(&self) -> usize {
        self.samples_per_beat() * self.beats_per_bar as usize
    }

    /// Distance (in samples) to next bar boundary.
    pub fn samples_to_next_bar(&self) -> usize {
        let spb = self.samples_per_bar();
        spb - (self.current_pos % spb)
    }

    pub fn is_at_bar_boundary(&self) -> bool {
        self.current_pos % self.samples_per_bar() == 0
    }
}

pub struct HorizontalSequencer {
    segments: Vec<MusicSegment>,
    current: usize,
    queued: Option<usize>,           // next segment to switch to
    fade: f32,                       // 0..1, crossfade progress
    fade_duration_samples: usize,
    fade_pos: usize,
    in_transition: bool,
}

impl HorizontalSequencer {
    pub fn queue_segment(&mut self, idx: usize) {
        self.queued = Some(idx);
    }

    pub fn process(&mut self, output: &mut [f32]) {
        let n_frames = output.len() / 2;
        for f in 0..n_frames {
            // Check if we should switch
            if let Some(new_idx) = self.queued {
                let cur = &self.segments[self.current];
                if cur.is_at_bar_boundary() {
                    // Switch now! Trigger crossfade
                    self.current = new_idx;
                    self.queued = None;
                    self.in_transition = true;
                    self.fade_pos = 0;
                }
            }

            // Output current segment sample
            let cur = &mut self.segments[self.current];
            if cur.current_pos < cur.samples.len() {
                output[f * 2]     = cur.samples[cur.current_pos];
                output[f * 2 + 1] = cur.samples[cur.current_pos + 1];
                cur.current_pos += 2;
                if cur.current_pos >= cur.samples.len() {
                    cur.current_pos = 0;  // loop
                }
            }

            // Handle fade
            if self.in_transition {
                let fade_amt = self.fade_pos as f32 / self.fade_duration_samples as f32;
                // Apply equal-power crossfade (sin curve)
                let gain = (std::f32::consts::PI / 2.0 * fade_amt).cos();
                output[f * 2]     *= gain;
                output[f * 2 + 1] *= gain;
                self.fade_pos += 1;
                if self.fade_pos >= self.fade_duration_samples {
                    self.in_transition = false;
                }
            }
        }
    }
}
```

**性能数据**:horizontal sequencer 几乎免费(per-sample 几条 if + mul),实际 CPU 在 sample copy。10ms buffer @ 48kHz stereo ~10μs CPU。

**坑**:**所有 segment 必须 BPM 一致**。如果 exploration 是 120 BPM,combat 是 140 BPM,bar boundary 永远对不齐,切换永远突兀。作曲家要约束。

### 1.3 Vertical re-orchestration:垂直重组

**结构**:作曲家写同一个曲子,**多个 layer**:drum、bass、melody、harmony、strings。游戏状态决定哪些 layer 一起播。例如:
- **Calm**(exploration):melody + harmony,15 dB
- **Tense**(near enemy):+ drum,5 dB louder
- **Combat**(in fight):+ bass,5 dB louder
- **Climax**(boss):all layers at max

**关键问题:layer 怎么"加入"和"退出"不被察觉?**

简单 mute/unmute 会"啪"地跳变。要做 **envelope fade**(linear 或 equal-power):layer 加入时 100ms fade in,退出时 200ms fade out。

**Bar-aligned layer switching**:layer 切换最好也在 bar boundary,与 horizontal 切换同理。

Rust 实现:

```rust
pub struct MusicLayer {
    pub samples: Vec<f32>,
    pub current_pos: usize,
    pub current_gain: f32,
    pub target_gain: f32,
    pub fade_rate_per_sample: f32,
}

impl MusicLayer {
    pub fn tick(&mut self) -> (f32, f32) {
        // Advance playback
        let l = self.samples[self.current_pos];
        let r = self.samples[self.current_pos + 1];
        self.current_pos += 2;
        if self.current_pos >= self.samples.len() {
            self.current_pos = 0;  // loop
        }

        // Smooth gain toward target
        if (self.current_gain - self.target_gain).abs() < self.fade_rate_per_sample {
            self.current_gain = self.target_gain;
        } else if self.current_gain < self.target_gain {
            self.current_gain += self.fade_rate_per_sample;
        } else {
            self.current_gain -= self.fade_rate_per_sample;
        }

        (l * self.current_gain, r * self.current_gain)
    }
}

pub struct VerticalReorchestrator {
    layers: Vec<MusicLayer>,
}

impl VerticalReorchestrator {
    /// Called by game state machine
    pub fn set_layer_gain(&mut self, idx: usize, gain: f32) {
        self.layers[idx].target_gain = gain;
    }

    pub fn process(&mut self, output: &mut [f32]) {
        let n_frames = output.len() / 2;
        for f in 0..n_frames {
            let mut sum_l = 0.0;
            let mut sum_r = 0.0;
            for layer in &mut self.layers {
                let (l, r) = layer.tick();
                sum_l += l;
                sum_r += r;
            }
            output[f * 2] = sum_l;
            output[f * 2 + 1] = sum_r;
        }
    }
}
```

**性能数据**:N layer 每 sample ~N mul + N add。10 layer @ 48kHz stereo = ~10ms CPU per sec。可以同时跑多个 track。

**坑**:**所有 layer 必须 sample-aligned**。作曲家录 drum 和 bass 时,如果不小心 drum 多 50ms intro,layer 永远不对齐。FMOD 提供 sample-accurate sync,作曲家在 DAW 里要导出对齐。

### 1.4 ELIS:Emotion-Like Interactive Scoring

ELIS 是 Elias Software 提出的 adaptive music **模型**(Elias 是专业 adaptive music middleware,http://eliasaudio.com/ )。核心思路:**作曲家给每个 musical "theme" + 每种 "emotion" 录一段 music**,游戏运行时 engine 根据当前 emotion 选择 music segment。

例如:
- Theme "Forest",emotion "Calm":录一段 peaceful strings
- Theme "Forest",emotion "Tense":录一段 tense strings + light percussion
- Theme "Forest",emotion "Combat":录一段 aggressive orchestral

游戏状态机决定 (theme, emotion),engine 在两者之间 transition。

ELIS 的关键创新是 **"seamless musical transition"**:engine 实时分析当前 segment 的 key、chord、rhythm,生成一段 1-2 秒的 musical bridge 到目标 segment,让 transition 听起来像作曲家手写的——不像传统 crossfade 的"两段重叠"。

实现 ELIS 完整需要 music analysis + procedural composition,超出这一篇范围。但简化版可以:
1. 每个 (theme, emotion) 一段预录 music
2. Transition 时:用 stinger + bar-aligned crossfade

```rust
pub struct ElisSystem {
    themes: HashMap<String, HashMap<String, MusicSegment>>,
    current_theme: String,
    current_emotion: String,
    current_segment: MusicSegment,
    transition_pending: Option<(String, String, f32)>, // (theme, emotion, transition time)
}

impl ElisSystem {
    pub fn request_state(&mut self, theme: &str, emotion: &str) {
        if theme == self.current_theme && emotion == self.current_emotion {
            return;
        }
        // Queue transition
        self.transition_pending = Some((theme.to_string(), emotion.to_string(), 2.0));
    }

    pub fn process(&mut self, output: &mut [f32]) {
        // Simplified — no real procedural bridge, just bar-aligned switch
        if let Some((theme, emotion, _)) = &self.transition_pending {
            if self.current_segment.is_at_bar_boundary() {
                let new_seg = self.themes.get(theme).unwrap().get(emotion).unwrap().clone();
                self.current_segment = new_seg;
                self.current_theme = theme.clone();
                self.current_emotion = emotion.clone();
                self.transition_pending = None;
            }
        }
        // Output current segment
        // ...
    }
}
```

Elias 真实引擎远比这个复杂(分析 chord / key / rhythm 然后生成 transition),但简化版足以体现 concept。

### 1.5 Adaptive music 参数

游戏传给 adaptive music engine 的参数:

- **Emotion**(calm / tense / combat / victory / defeat)— 主导 music 选择
- **Intensity**(0-1)— 调节 layer 数量 / volume
- **Health**(0-1)— 影响 music tension(low health 加急促感)
- **Proximity to boss**(0-1)— 接近时音乐变化
- **Time of day**(day / night)— music 切换
- **Player count**(singleplayer / multiplayer)— 不同 mix

这些参数通过 **parameter smoothing** 应用,不要让任何参数"跳变"。比如 health 从 1.0 跌到 0.2,music 应在 0.5-1 秒内慢慢变化,不能瞬间切换。

```rust
pub struct SmoothedParam {
    current: f32,
    target: f32,
    rate_per_sample: f32,  // e.g. 1.0 / (0.5 * sample_rate)
}

impl SmoothedParam {
    pub fn tick(&mut self) -> f32 {
        if (self.current - self.target).abs() < self.rate_per_sample {
            self.current = self.target;
        } else if self.current < self.target {
            self.current += self.rate_per_sample;
        } else {
            self.current -= self.rate_per_sample;
        }
        self.current
    }
}
```

**坑**:game state 突变时(player instant-kill),不要让 music 瞬间切——按 200-500ms 平滑过渡。

## 2 · 工业级 Interactive Music Systems

### 2.1 FMOD Studio 完整工作流

FMOD(Firelight Technologies)是 game audio middleware 的事实标准之一。Minecraft、Hades、Celeste、Hollow Knight 都用 FMOD。完整工作流:

1. **Composer 在 DAW**(Logic / Ableton / Cubase)里写 music,导出 multi-track stems。
2. **Sound designer 在 FMOD Studio**(GUI app)里:
   - 创建 **Events**:每个 game-triggered sound 是一个 event("footstep"、"gunshot"、"combat_music")
   - 创建 **Parameters**:game state 变量("intensity"、"health"、"distance_to_boss")
   - 在 Event 里拖入 stems,用 parameter 控制 layer 切换 / pitch / volume
   - 创建 **Music Tracks**:horizontal sequencer + vertical layering,bar-aligned transition
   - 设置 **Snapshots**:全局 effect state("low_health_snapshot" 让所有 sound 加 lowpass + slow tremolo)
3. **Programmer** 在 C++ / Rust 代码里调用 FMOD API:
   - `EventInstance_Start(event)`
   - `EventInstance_SetParameterByName(event, "intensity", 0.7)`
   - `StudioSystem_Update()` 每帧调用,同步 state

FMOD 关键概念:
- **Bank**:打包的 audio + metadata 文件(.bank),game runtime 加载
- **Event**:game-facing audio object,有 parameter
- **Snapshot**:全局 DSP state 变更
- **VCAs**(Voltage Control Amplifiers):group volume 控制,类似 bus

FMOD 的 adaptive music 系统:
- **Music Track** = multi-sequence + multi-layer
- **Music Loop Region**:loop a segment
- **Music Transition Region**:bar-aligned switch
- **Destination Fed**:parameter-driven segment selection

**FMOD 源码**:[闭源] 但 API 文档完整 https://fmod.com/docs 。FMOD Studio(编辑器)的 SDK 跨平台,运行时是 .so/.dll/.a 静态/动态库。

**FMOD 与 Rust 集成**:`fmod-rs` crate(社区)或者直接 FFI bind:

```rust
// Via FFI bindings (simplified)
extern "C" {
    fn FMOD_Studio_System_Create(system: *mut *mut System, headerversion: u32) -> i32;
    fn FMOD_Studio_System_Initialize(system: *mut System, maxchannels: i32, studioflags: u32, flags: u32, extradriverdata: *mut c_void) -> i32;
    fn FMOD_Studio_System_LoadBankFile(system: *mut System, path: *const c_char, flags: u32, bank: *mut *mut Bank) -> i32;
    fn FMOD_Studio_System_GetEvent(system: *mut System, path: *const c_char, event: *mut *mut EventDescription) -> i32;
    fn FMOD_Studio_EventDescription_CreateInstance(description: *mut EventDescription, instance: *mut *mut EventInstance) -> i32;
    fn FMOD_Studio_EventInstance_Start(instance: *mut EventInstance) -> i32;
    fn FMOD_Studio_EventInstance_SetParameterValue(instance: *mut EventInstance, name: *const c_char, value: f32) -> i32;
    fn FMOD_Studio_System_Update(system: *mut System) -> i32;
}
```

Rust 包装:

```rust
pub struct FmodSystem(*mut std::ffi::c_void);
pub struct FmodEvent(*mut std::ffi::c_void);

impl FmodSystem {
    pub fn new() -> Self {
        unsafe {
            let mut sys: *mut std::ffi::c_void = std::ptr::null_mut();
            let hdr = 0x00020000;  // header version
            FMOD_Studio_System_Create(&mut sys, hdr);
            FMOD_Studio_System_Initialize(sys, 1024, 1, 1, std::ptr::null_mut());
            FmodSystem(sys)
        }
    }

    pub fn load_bank(&self, path: &str) {
        unsafe {
            let c_path = std::ffi::CString::new(path).unwrap();
            let mut bank: *mut std::ffi::c_void = std::ptr::null_mut();
            FMOD_Studio_System_LoadBankFile(self.0, c_path.as_ptr(), 1, &mut bank);
        }
    }

    pub fn create_event(&self, event_path: &str) -> FmodEvent {
        unsafe {
            let c_path = std::ffi::CString::new(event_path).unwrap();
            let mut desc: *mut std::ffi::c_void = std::ptr::null_mut();
            FMOD_Studio_System_GetEvent(self.0, c_path.as_ptr(), &mut desc);
            let mut instance: *mut std::ffi::c_void = std::ptr::null_mut();
            FMOD_Studio_EventDescription_CreateInstance(desc, &mut instance);
            FmodEvent(instance)
        }
    }

    pub fn update(&self) {
        unsafe { FMOD_Studio_System_Update(self.0); }
    }
}

impl FmodEvent {
    pub fn start(&self) {
        unsafe { FMOD_Studio_EventInstance_Start(self.0); }
    }

    pub fn set_parameter(&self, name: &str, value: f32) {
        unsafe {
            let c_name = std::ffi::CString::new(name).unwrap();
            FMOD_Studio_EventInstance_SetParameterValue(self.0, c_name.as_ptr(), value);
        }
    }
}
```

(实际 code 用 `libfmod` / `fmod-rs` crate,已经包好了。)

### 2.2 Wwise 完整工作流

Wwise(Audiokinetic)是 FMOD 的主要竞争对手。FromSoftware(Elden Ring)、Insomniac(Spider-Man)、Bungie(Destiny)用 Wwise。

Wwise 概念与 FMOD 类似,但术语不同:
- **SoundBanks**:对应 FMOD Banks
- **Events**:同 FMOD
- **Game Syncs**(Switch / RTPC / State):对应 FMOD Parameter
- **Music Segment / Music Playlist Container**:adaptive music 容器

Wwise 的优势是**更深的 source control 集成**(Wwise Project 文件可 git diff),以及**音频扩散**(spatial audio spread)做得更细致。

**Wwise 源码**:[闭源] https://www.audiokinetic.com/ 。

### 2.3 Elias

Elias(Elias Software,瑞典)专做 adaptive music。The Division、Cyberpunk 2077(部分 track)用 Elias。

Elias 的核心卖点是 **music transition 真的 seamless**——它分析 chord / rhythm,生成 musical bridge。这需要音乐家提供"音乐模板"而不只是录音。

**Elias 源码**:[闭源] http://eliasaudio.com/

### 2.4 Pure Data / Max/MSP:Visual Programming

Pure Data(Pd)和 Max/MSP 是 visual programming 语言,用 patcher(线连 box)做 audio synthesis 和 processing。

- **Pure Data**:开源,Miller Puckette 创作,http://msp.ucsd.edu/software.html
- **Max/MSP**:商业(Cycling 74),Ableton Live 集成

游戏里嵌入 Pd 可以做"运行时 music engine":composer 用 pd patch 设计 music 生成规则,game 触发控制信号。

```
[receive combat_intensity]
|
[* 0.01]
|
[metro]  <- tempo
|
[drum_trigger] -> [play_sample~ kick.wav]
[drum_trigger] -> [play_sample~ snare.wav]
```

(示意 patch;实际 pd 用 GUI 拖拽 box,不是文本。)

**libpd** 是 Pd 的 C 库,可以嵌入 Rust:

```rust
// Via libpd-sys crate
use libpd_sys::*;

pub struct PdEngine {
    // ...
}

impl PdEngine {
    pub fn new(patch_path: &str) -> Self {
        unsafe {
            libpd_init();
            libpd_open_audio(2, 2, 48000);  // in, out, sample rate
            let c_path = std::ffi::CString::new(patch_path).unwrap();
            let dir = std::ffi::CString::new(".").unwrap();
            libpd_open_patch(c_path.as_ptr(), dir.as_ptr());
        }
        Self {}
    }

    pub fn send_float(&self, receiver: &str, value: f32) {
        unsafe {
            let c_recv = std::ffi::CString::new(receiver).unwrap();
            libpd_float(c_recv.as_ptr(), value);
        }
    }
}
```

**用 Pd 做游戏 music 的优势**:composer 不依赖程序员,可以独立修改 music 逻辑。劣势:performance 不如 hand-coded engine,patch 难以调试。

## 3 · 3D 空间音频基础

### 3.1 Panning laws

最简单的"3D audio"是 **stereo panning**:把 mono signal 按 listener 左右分布到 L/R channel。

**Linear pan law**:
```
g_L = (1 - pan) / 2
g_R = (1 + pan) / 2
```
pan = 0(中间)→ g_L = g_R = 0.5。问题:**听感上中间比两边响**(因为两个耳朵同时听见)。

**Constant power pan law**(equal power):
```
g_L = cos(π/2 · (pan + 1) / 2)
g_R = sin(π/2 · (pan + 1) / 2)
```
pan = 0(中间)→ g_L = g_R = sqrt(2)/2 ≈ 0.707。总 power = g_L² + g_R² = 1,与 mono 等价。这是工业 standard。

```rust
pub fn pan_stereo(sample: f32, pan: f32) -> (f32, f32) {
    // pan in [-1, 1]
    let angle = std::f32::consts::PI / 4.0 * (pan + 1.0);
    (sample * angle.cos(), sample * angle.sin())
}
```

**-4.5 dB pan law**:一些 DAW 用 -4.5 dB center attenuation(对应 pan=0 时 g=0.595),比 -3 dB(equal power)更平。

### 3.2 Surround:5.1 / 7.1

**5.1 surround**:Left、Center、Right、Left Surround、Right Surround、LFE(Low Frequency Effects,subwoofer)。位置约定:
```
       Center
   L             R
       (listener)
   LS            RS
```

L、R 在 ±30°,LS、RS 在 ±110°。

**7.1** 加 Left Back、Right Back(±135°)。

Panning 到 surround:用 Vector Base Amplitude Panning(VBAP)或 ambisonics。

**VBAP 简化**:source 在角度 θ,找最近的两个 speaker,用 constant power 在两者间 pan。

```rust
// Simplified 5.1 pan: angle in [-180, 180], 0 = center front
pub fn pan_5_1(sample: f32, angle: f32) -> [f32; 6] {
    // Speakers: L=-30, C=0, R=30, LS=-110, RS=110 (degrees)
    // Output order: L, R, C, LFE, LS, RS
    let mut out = [0.0; 6];

    // Find two nearest speakers
    let speakers = [-110.0, -30.0, 0.0, 30.0, 110.0];
    let speaker_idx = [4, 0, 2, 1, 5]; // map to output index (L=0, R=1, C=2, LFE=3, LS=4, RS=5)
    // Simplified: assume angle in [-180, 180]
    let mut best = (0, 1);
    let mut best_dist = f32::MAX;
    for i in 0..5 {
        for j in (i+1)..5 {
            let d = ((speakers[i] + speakers[j]) / 2.0 - angle).abs();
            if d < best_dist {
                best_dist = d;
                best = (i, j);
            }
        }
    }

    let s1 = speakers[best.0];
    let s2 = speakers[best.1];
    let span = (s2 - s1).abs();
    let t = ((angle - s1) / span).clamp(0.0, 1.0);
    let g1 = (std::f32::consts::PI / 2.0 * t).cos();
    let g2 = (std::f32::consts::PI / 2.0 * t).sin();
    out[speaker_idx[best.0]] = sample * g1;
    out[speaker_idx[best.1]] = sample * g2;

    out
}
```

(这是简化版。完整 VBAP 处理 3D 三角化speaker triangle。)

### 3.3 HRTF:Head-Related Transfer Function

**HRTF**(Head-Related Transfer Function)是 **从 3D 空间某点到人耳鼓膜的频率响应**。它编码了 head、torso、pinna(耳廓)对声波的衍射 / 反射效应。HRTF 是 **真正能让 headphone 听起来 out-of-head** 的核心技术。

**物理直觉**:声波从某个方向到达人耳,过程中:
- 被 head 阻挡(head shadow):对侧耳朵高频衰减
- 被 pinna 反射:产生 direction-dependent spectral notches
- 经过 torso 反射:增加 complexity
- 到达两侧耳朵的时间不同:ITD

这些效应综合起来,**人脑根据两个耳朵的 signal 差异** 反推 source 方向。HRTF 就是这些差异的 frequency-domain 表征。

**HRTF 测量**:在消声室,把小 probe mic 放到 test subject 的 ear canal 入口,从各个方向用 speaker 播 impulse(sine sweep),录 mic response,deconvolution 得到 HRTF。每个 (azimuth, elevation) 一对 HRTF(L 和 R)。

**HRTF 数据集**:
- MIT KEMAR(1994,Gardner & Martin):经典 measurement,710 directions
- CIPIC(HOR Clifton Park):45 subjects,1250 directions
- IRCAM Listen:50 subjects
- ARI HRTF(OpenMHA):modern high-resolution

工业 standard 是 SOFA(Spatially Oriented Format for Acoustics)文件格式。

**Binaural rendering**:用 HRTF 做 convolution:

```
y_L[n] = sum_k HRTF_L[θ, φ][k] · x[n-k]
y_R[n] = sum_k HRTF_R[θ, φ][k] · x[n-k]
```

(θ, φ) 是 source 相对 listener 的方向。

完整 pipeline:

```
mono source x[n]
   │
   │ (assume at azimuth θ, elevation φ)
   ▼
   convolve with HRTF_L(θ, φ) → y_L[n]
   convolve with HRTF_R(θ, φ) → y_R[n]
   │
   ▼
   stereo headphone output
```

简化 Rust 实现:

```rust
pub struct HrtfChannel {
    filter: Vec<f32>,        // HRIR (impulse response) for this ear/dir
    history: Vec<f32>,       // input history
    pos: usize,
}

pub struct HrtfRenderer {
    left: HrtfChannel,
    right: HrtfChannel,
    ir_length: usize,
}

impl HrtfRenderer {
    pub fn new(ir_length: usize) -> Self {
        Self {
            left: HrtfChannel {
                filter: vec![0.0; ir_length],
                history: vec![0.0; ir_length],
                pos: 0,
            },
            right: HrtfChannel {
                filter: vec![0.0; ir_length],
                history: vec![0.0; ir_length],
                pos: 0,
            },
            ir_length,
        }
    }

    pub fn set_direction(&mut self, azimuth: f32, elevation: f32, dataset: &HrtfDataset) {
        // Look up nearest HRIR pair from dataset
        let (hrir_l, hrir_r) = dataset.lookup(azimuth, elevation);
        self.left.filter[..hrir_l.len()].copy_from_slice(hrir_l);
        self.right.filter[..hrir_r.len()].copy_from_slice(hrir_r);
    }

    pub fn process(&mut self, input: &[f32], output_l: &mut [f32], output_r: &mut [f32]) {
        let ir_len = self.ir_length;
        for (i, &x) in input.iter().enumerate() {
            // Write to history
            self.left.history[self.left.pos] = x;
            self.right.history[self.right.pos] = x;

            // Convolve (FIR filter)
            let mut sum_l = 0.0f32;
            let mut sum_r = 0.0f32;
            for k in 0..ir_len {
                let idx = (self.left.pos + ir_len - k) % ir_len;
                sum_l += self.left.filter[k] * self.left.history[idx];
                sum_r += self.right.filter[k] * self.right.history[idx];
            }
            output_l[i] = sum_l;
            output_r[i] = sum_r;

            self.left.pos = (self.left.pos + 1) % ir_len;
            self.right.pos = (self.right.pos + 1) % ir_len;
        }
    }
}
```

**性能数据**:HRIR 典型 128 或 256 taps(时域 IR)。每个 sample 做 2 × 128 = 256 multiply-accumulate。48kHz stereo = 48000 × 256 = 12.3M MAC/sec per source。占 modern CPU ~0.5%。

可以用 **partitioned convolution FFT**(像 convolution reverb 那样)加速长 HRIR,但 128 taps 直接时域更快。

### 3.4 ITD 和 ILD:双耳线索的物理

HRTF 编码了 ITD 和 ILD(以及其他更复杂 effect)。理解 ITD / ILD 的物理是设计 spatializer 的基础。

**ITD**(Inter-aural Time Difference):声波到达左右耳的时间差。

简化物理(平面声波,head 看作球):
```
ITD ≈ (head_radius / speed_of_sound) · sin(azimuth)
```

典型 head radius r = 8.75 cm,声速 c = 343 m/s。最大 ITD(azimuth = ±90°)≈ 0.0875 / 343 ≈ 0.255 ms。对应 sample @ 48kHz = 12 sample。

更精确公式:Woodworth formula:
```
ITD = (r/c) · (θ + sin θ)   for azimuth θ in front
```
最大 ITD ≈ 0.6 ms,约 30 sample @ 48kHz。

**ILD**(Inter-aural Level Difference):声波到达左右耳的强度差。

主要由 head shadow effect 引起。Head 对高频(> 1 kHz)是 obstacle,对侧耳朵高频显著衰减。低频(< 500 Hz)波长大于 head,基本无 ILD。

简化模型:
```
ILD(f, θ) ≈ 1.5 · (f/1000) · sin(θ)   (in dB, for f < 4 kHz, capped at ~20 dB)
```

**应用到 spatializer**:HRTF 完整表征了 ITD + ILD + pinna effect。但**简化版** spatializer 可以只做 ITD(delay) + ILD(gain):

```rust
pub struct SimpleBinaural {
    itd_samples_l: f32,
    itd_samples_r: f32,
    ild_db_l: f32,
    ild_db_r: f32,
    // fractional delay buffers
    buf_l: Vec<f32>,
    buf_r: Vec<f32>,
    pos_l: usize,
    pos_r: usize,
}

impl SimpleBinaural {
    pub fn set_direction(&mut self, azimuth: f32, sample_rate: f32) {
        // azimuth in [-π, π], 0 = front
        let r = 0.0875;  // head radius (m)
        let c = 343.0;
        let max_itd_sec = r / c * (1.0 + std::f32::consts::PI / 2.0);  // ~0.6 ms
        let itd_sec = max_itd_sec * azimuth.sin() / std::f32::consts::FRAC_PI_2.sin();
        let itd_samples = itd_sec * sample_rate;
        self.itd_samples_l = itd_samples.max(0.0);
        self.itd_samples_r = (-itd_samples).max(0.0);

        // ILD: simple low-freq approximation
        // At high freq, opposite ear gets -6 dB head shadow at azimuth 90°
        let ild_db = -6.0 * azimuth.sin().abs();
        if azimuth > 0.0 {
            // source on right: right ear louder
            self.ild_db_l = ild_db;
            self.ild_db_r = 0.0;
        } else {
            self.ild_db_l = 0.0;
            self.ild_db_r = ild_db;
        }
    }
}
```

**听感**:simple ITD+ILD spatializer 比 HRTF 弱(没有 pinna spectral cue,前/后 confused),但实现简单,CPU 极低。**Web Audio API 的 PannerNode 默认就是 HRTF 或 equal-power 之一**。

### 3.5 距离衰减

声波在自由场衰减 6 dB per doubling distance(反平方律)。

```
amplitude = source_amplitude / max(distance, ref_distance)
```

但**线性反距离太陡**——近处听力被摧残,远处快速消失。游戏 audio 用更可控的 curve:

**Logarithmic attenuation**:
```
gain = ref_distance / (ref_distance + ref_distance * log10(distance / ref_distance))
```

或简化:

```rust
pub fn distance_attenuation(distance: f32, ref_distance: f32, max_distance: f32, rolloff: f32) -> f32 {
    if distance >= max_distance { return 0.0; }
    if distance <= ref_distance { return 1.0; }
    let ratio = (distance - ref_distance) / (max_distance - ref_distance);
    (1.0 - ratio).powf(rolloff)
}
```

`rolloff = 1.0` 是线性,`rolloff = 2.0` 是反平方(陡),`rolloff = 0.5` 是平缓(听到更远)。

**典型游戏值**:ref_distance = 1m,max_distance = 50m,rolloff = 1.5。

### 3.6 Occlusion:遮挡

墙后面的声音应该被 lowpass filter(高频被墙吸收)并 attenuate。

实现:
1. **Ray cast** from source to listener(在 game physics world)
2. 检查 ray 是否穿过 occluder
3. 如果穿,lowpass cutoff 取决于 material(混凝土 200 Hz,木墙 1000 Hz,玻璃 5000 Hz)
4. Optional:额外 attenuation(每堵墙 -3 dB)

```rust
pub fn compute_occlusion(source_pos: Vec3, listener_pos: Vec3, world: &World) -> (f32, f32) {
    // Returns (lowpass_cutoff_hz, extra_attenuation_db)
    let ray_direction = listener_pos - source_pos;
    let ray_distance = ray_direction.length();
    let ray_dir = ray_direction / ray_distance;

    let mut cutoff = 20000.0;
    let mut atten = 0.0;

    // Cast ray,find intersections
    if let Some(hit) = world.raycast(source_pos, ray_dir, ray_distance) {
        match hit.material {
            Material::Concrete => { cutoff = 200.0;  atten = -12.0; }
            Material::Wood     => { cutoff = 1000.0; atten = -6.0; }
            Material::Glass    => { cutoff = 5000.0; atten = -3.0; }
            Material::Fabric   => { cutoff = 2000.0; atten = -2.0; }
        }
    }
    (cutoff, atten)
}
```

应用到 audio:source 的 signal 经一个 lowpass(根据 occlusion 设 cutoff)再 attenuation。

```rust
pub struct OccludedSource {
    source: AudioSource,
    lowpass: Biquad,  // from audio-effects
    current_cutoff: f32,
}

impl OccludedSource {
    pub fn update_occlusion(&mut self, source_pos: Vec3, listener_pos: Vec3, world: &World) {
        let (cutoff, atten_db) = compute_occlusion(source_pos, listener_pos, world);
        // Smoothly update lowpass (avoid zipper noise)
        self.current_cutoff = self.current_cutoff * 0.95 + cutoff * 0.05;
        self.lowpass.set_lowpass(self.current_cutoff, 0.707, 48000.0);
        // Apply attenuation in gain
        self.source.gain = db_to_linear(atten_db);
    }
}
```

### 3.7 房间反射:Early reflections + Late reverb

HRTF 处理 direct path,但房间里的 sound 还包括**早期反射**(early reflections,前 80ms)和**晚期混响**(late reverb,80ms 之后)。

**Early reflections**:用 **image source method** 算。把房间看作 mirror room,source 的虚像(image source)在 mirror 位置。listener 听到的 first-order reflection = listener 听 image source 的 direct sound。

简化:image source 列表(简化 1st-order,6 个 wall):

```rust
pub fn image_sources(source: Vec3, room_min: Vec3, room_max: Vec3) -> Vec<Vec3> {
    vec![
        Vec3::new(2.0 * room_min.x - source.x, source.y, source.z),  // left wall
        Vec3::new(2.0 * room_max.x - source.x, source.y, source.z),  // right wall
        Vec3::new(source.x, 2.0 * room_min.y - source.y, source.z),  // floor
        Vec3::new(source.x, 2.0 * room_max.y - source.y, source.z),  // ceiling
        Vec3::new(source.x, source.y, 2.0 * room_min.z - source.z),  // back wall
        Vec3::new(source.x, source.y, 2.0 * room_max.z - source.z),  // front wall
    ]
}

pub fn render_early_reflections(source: Vec3, listener: Vec3, room: (Vec3, Vec3), hrtf: &mut HrtfRenderer) -> (Vec<f32>, Vec<f32>) {
    let images = image_sources(source, room.0, room.1);
    let mut l = vec![0.0; 1024];
    let mut r = vec![0.0; 1024];
    let mut l_temp = vec![0.0; 1024];
    let mut r_temp = vec![0.0; 1024];
    for img in images {
        // Direction from listener to image source
        let dir = img - listener;
        let dist = dir.length();
        let azimuth = dir.y.atan2(dir.x);
        let elevation = dir.z.atan2(dir.xy().length());
        hrtf.set_direction(azimuth, elevation, &dataset);
        // Apply attenuation for distance
        let atten = distance_attenuation(dist, 1.0, 50.0, 1.5);
        // Render
        hrtf.process(&source_buffer, &mut l_temp, &mut r_temp);
        for i in 0..l.len() {
            l[i] += l_temp[i] * atten;
            r[i] += r_temp[i] * atten;
        }
    }
    (l, r)
}
```

完整 image source 算 2nd / 3rd order,reflection 越多越密。

**Late reverb**:房间残响,用 FDN 或 convolution reverb(见 [audio-effects.md](../phase-5/deep-dives/audio-effects.md) §3)。

**Spatialized reverb**:把 late reverb 也通过 HRTF 渲染。Reverb 来自"四面八方",所以用 diffuse field HRTF(平均 all directions)。

### 3.8 Doppler effect

声源相对 listener 运动时,听到的 frequency 变化。

**物理公式**(source 朝 listener 运动,径向速度 v_r,正方向为接近):
```
f_heard = f_emitted · c / (c - v_r)
```

c = 343 m/s。v_r = 34.3 m/s(高速接近,~10% c)→ frequency 升 10%。

**Doppler 实现**:不用 resample input signal(贵),而是调 playback rate:

```rust
pub struct DopplerSource {
    base_pitch: f32,         // playback rate multiplier,1.0 = normal
    last_pitch: f32,
    smoothing: f32,
}

impl DopplerSource {
    pub fn update(&mut self, source_vel: Vec3, listener_vel: Vec3, source_to_listener_dir: Vec3) {
        let c = 343.0;
        // Radial velocity (positive = approaching)
        let v_r = (source_vel - listener_vel).dot(-source_to_listener_dir);
        let pitch = c / (c - v_r);
        // Smooth to avoid clicks on direction changes
        self.last_pitch = self.last_pitch * 0.95 + pitch * 0.05;
    }
}
```

**坑**:
- v_r 突变(source 在 listener 周围转)→ pitch 突变 → click。Smoothing 必需。
- v_r > c(supersonic):formula 除 0。Clamp v_r 到 c - 1。
- 实际玩家移动速度有限,小 Doppler 调整(±10%)够。

## 4 · Voice Chat:实时多人语音

### 4.1 网络语音的挑战

Real-time voice over IP(VoIP)有几条硬约束:
- **延迟 < 150 ms 单程**(玩家说话到对方听到)。超过就"对讲机感"
- **带宽** < 50 kbps/voice(64 player × 64 kbps = 4 Mbps 上行,太多)
- **packet loss 容忍**(5% UDP loss 不应让 voice 听不懂)
- **jitter**(packet 到达间隔不稳)

### 4.2 Opus codec

Opus(http://opus-codec.org/)是 IETF 标准(RFC 6716),Xiph/Skype 联合开发。**游戏 voice chat 的事实标准**(Discord、Zoom、Fortnite、Valorant 都用)。

Opus 的核心:** CELT + SILK 混合**。
- **SILK**:Skype 开发的语音 codec,8-24 kHz,speech-optimized。Skype 用了 10 年。
- **CELT**:Xiph 开发的通用 codec,8-48 kHz,music-optimized。
- Opus 在 low bitrate(< 24 kbps)用 SILK(对 voice 更高效),high bitrate 用 CELT(对 music 更好)。中间过渡。

**Opus bitrate 范围**:6 kbps(极限低)到 510 kbps(高质量)。游戏 voice 通常 16-32 kbps。

**Opus frame size**:2.5, 5, 10, 20, 40, 60 ms。游戏 voice 用 20 ms(50 packets/sec,平衡 latency 和 overhead)。

**Opus latency**:algorithmic delay = frame size + lookahead。20 ms frame + 5 ms lookahead = 25 ms codec delay。

**Opus features**:
- **DTX**(Discontinuous Transmission):静音时不发包(节省 bandwidth)
- **VAD**(Voice Activity Detection):自动检测 speech
- **FEC**(Forward Error Correction):把"上一帧低质量版本"嵌入"当前帧",packet loss 可重建
- **In-band FEC**:explicit redundancy
- **LBRR**(Low Bitrate Redundancy):low bitrate version of previous frame piggybacked

**Opus 在 Rust**:`audiopus` 或 `opus-sys` crate,FFI 调 libopus。

```rust
use audiopus::{Application, Bitrate, Channels, Encoder, Decoder, SampleRate};

pub struct OpusVoiceChat {
    encoder: Encoder,
    decoder: Decoder,
    frame_size_samples: usize,  // 20 ms @ 48kHz = 960
}

impl OpusVoiceChat {
    pub fn new() -> Self {
        let encoder = Encoder::new(SampleRate::Hz48000, Channels::Mono, Application::Voip).unwrap();
        encoder.set_bitrate(Bitrate::Bits(24000)).unwrap();
        let decoder = Decoder::new(SampleRate::Hz48000, Channels::Mono).unwrap();
        Self {
            encoder,
            decoder,
            frame_size_samples: 960,
        }
    }

    pub fn encode(&mut self, pcm: &[i16]) -> Vec<u8> {
        let mut output = vec![0u8; 4000];
        let len = self.encoder.encode(pcm, &mut output).unwrap();
        output.truncate(len);
        output
    }

    pub fn decode(&mut self, packet: &[u8]) -> Vec<i16> {
        let mut output = vec![0i16; self.frame_size_samples];
        self.decoder.decode(Some(packet), &mut output, false).unwrap();
        output
    }

    pub fn decode_fec(&mut self, packet: &[u8], prev_lost: bool) -> Vec<i16> {
        let mut output = vec![0i16; self.frame_size_samples];
        // decode_next decodes previous frame from in-band FEC in this packet
        self.decoder.decode(Some(packet), &mut output, prev_lost).unwrap();
        output
    }
}
```

### 4.3 Jitter buffer

Network packet 到达间隔不稳。如果 audio callback 每帧(20ms)需要 decode 一个 packet,但 packet 因 network delay 在 25ms 后才到,就直接 underrun(没数据可播)。

**Jitter buffer**:接收端缓存 N 个 packet(典型 3-5 帧 = 60-100ms),再以稳定速率给 audio callback。

```rust
pub struct JitterBuffer {
    packets: Vec<Option<Vec<u8>>>,
    write_seq: u16,
    read_seq: u16,
    capacity: usize,
}

impl JitterBuffer {
    pub fn new(capacity: usize) -> Self {
        Self {
            packets: (0..capacity).map(|_| None).collect(),
            write_seq: 0,
            read_seq: 0,
            capacity,
        }
    }

    pub fn push(&mut self, seq: u16, packet: Vec<u8>) {
        let idx = (seq as usize) % self.capacity;
        self.packets[idx] = Some(packet);
        self.write_seq = seq.wrapping_add(1);
    }

    pub fn pop(&mut self) -> Option<Vec<u8>> {
        let idx = (self.read_seq as usize) % self.capacity;
        let packet = self.packets[idx].take();
        if packet.is_some() {
            self.read_seq = self.read_seq.wrapping_add(1);
        }
        packet
    }
}
```

**坑**:
- Jitter buffer 太小(2 frames = 40ms)→ underrun 频繁
- Jitter buffer 太大(10 frames = 200ms)→ 总 latency 增加
- Adaptive jitter buffer:根据 network condition 动态调整大小

### 4.4 Forward Error Correction

Opus 内置 FEC:encode 时 set `encoder.set_inband_fec(1)`,encoder 把"上一帧 CELT redundancy"嵌入当前帧。如果上一帧 packet 丢了,decoder 收到当前帧时可以从 redundancy 恢复上一帧。

```rust
pub fn encode_with_fec(encoder: &mut Encoder, current: &[i16], prev: Option<&[i16]>) -> Vec<u8> {
    encoder.set_inband_fec(1).unwrap();
    encoder.set_packet_loss_perc(5).unwrap();  // hint to encoder
    // Encode current frame,FEC redundancy contains prev frame info
    let mut output = vec![0u8; 4000];
    let len = encoder.encode(current, &mut output).unwrap();
    output.truncate(len);
    output
}

pub fn decode_with_fec(decoder: &mut Decoder, packet: &[u8], prev_lost: bool) -> Vec<i16> {
    let mut output = vec![0i16; 960];
    // forward_decode: get this frame normally
    decoder.decode(Some(packet), &mut output, false).unwrap();
    output
}

pub fn recover_lost_frame(decoder: &mut Decoder, next_packet: &[u8]) -> Vec<i16> {
    // When previous frame was lost, decode it from next packet's FEC
    let mut output = vec![0i16; 960];
    decoder.decode(Some(next_packet), &mut output, true).unwrap();
    output
}
```

**Packet loss concealment (PLC)**:即使没 FEC,Opus decoder 也能用 `decode(None, ...)` "猜"一帧(用上一帧的 spectral envelope),音质明显比静音好。

### 4.5 Speex codec

Speex(Opus 前身,Xiph)现在很少用,但 AEC / denoiser 算法仍在用。新项目不要用 Speex codec——Opus 全面超越。

### 4.6 完整 voice chat pipeline

整合所有零件:

```
[Capture] 16kHz/48kHz PCM
   ↓
[Pre-processing]
   - Noise suppression (RNNoise, Speex DSP)
   - Echo cancellation (WebRTC AEC)
   - AGC (automatic gain control)
   ↓
[Opus encode] 24 kbps, 20ms frame
   ↓
[Network send] UDP, sequence numbering
   ↓
... network ...
   ↓
[Network receive] jitter buffer
   ↓
[Opus decode] (with FEC recovery if lost)
   ↓
[Per-voice processing]
   - Spatialize (HRTF for positional voice)
   - Compressor
   - Limiter
   ↓
[Mix all voices + game audio]
   ↓
[Master bus]
   - Multiband compressor
   - Limiter
   ↓
[Render to output device]
```

Rust 伪代码:

```rust
pub struct VoiceChatReceiver {
    jitter: JitterBuffer,
    decoder: OpusVoiceChat,
    hrtf: HrtfRenderer,
    compressor: Compressor,
    voice_position: Vec3,
    listener_position: Vec3,
}

impl VoiceChatReceiver {
    pub fn on_packet(&mut self, seq: u16, data: Vec<u8>) {
        self.jitter.push(seq, data);
    }

    pub fn render(&mut self, output_l: &mut [f32], output_r: &mut [f32]) {
        // Pop one frame from jitter buffer
        if let Some(packet) = self.jitter.pop() {
            let pcm = self.decoder.decode(&packet);
            // Convert to f32
            let f32_pcm: Vec<f32> = pcm.iter().map(|&s| s as f32 / 32768.0).collect();
            // Spatialize
            let dir = (self.voice_position - self.listener_position).normalize();
            let azimuth = dir.y.atan2(dir.x);
            let elevation = dir.z.atan2(dir.xy().length());
            self.hrtf.set_direction(azimuth, elevation, &dataset);
            self.hrtf.process(&f32_pcm, output_l, output_r);
            // Compress
            let mut mono = vec![0.0; output_l.len()];
            for i in 0..output_l.len() {
                mono[i] = (output_l[i] + output_r[i]) * 0.5;
            }
            let mut comp_out = vec![0.0; mono.len()];
            self.compressor.process(&mono, &mut comp_out);
            for i in 0..output_l.len() {
                output_l[i] = comp_out[i];
                output_r[i] = comp_out[i];
            }
        } else {
            // Underrun:output silence or PLC
            for x in output_l.iter_mut() { *x = 0.0; }
            for x in output_r.iter_mut() { *x = 0.0; }
        }
    }
}
```

## 5 · Rust 生态

### 5.1 rodio spatial

`rodio` 是 Rust 简单 audio playback crate。Source API,可以叠效果:

```rust
use rodio::Source;

pub struct SpatialSource<S: Source<Item = f32>> {
    source: S,
    listener_pos: Vec3,
    listener_orient: Quat,
    source_pos: Vec3,
    lowpass: Biquad,
}

impl<S: Source<Item = f32>> Iterator for SpatialSource<S> {
    type Item = f32;
    fn next(&mut self) -> Option<f32> {
        let sample = self.source.next()?;
        // Distance attenuation
        let dist = (self.source_pos - self.listener_pos).length();
        let atten = distance_attenuation(dist, 1.0, 50.0, 1.5);
        // Apply
        Some(sample * atten)
    }
}
```

`rodio::spatial::SpatialSink` 是 builtin 实现,见 https://github.com/RustAudio/rodio/blob/master/src/spatial.rs 。它做基本 3D pan + distance attenuation,不做 HRTF。

### 5.2 kira

`kira` 是 game-focused audio engine。设计上有"track"(类似于 FMOD event)、"instance"、parameter。

```rust
use kira::{
    AudioManager, AudioManagerSettings, DefaultBackend,
    sound::static_sound::StaticSoundSettings,
    track::TrackBuilder,
};

let mut manager = AudioManager::<DefaultBackend>::new(AudioManagerSettings::default())?;
let sound = manager.load_sound("path/to/sound.ogg", StaticSoundSettings::default())?;
let mut instance = sound.play()?;
instance.set_volume(0.5)?;
```

`kira` 支持 adaptive music 通过 parameter modulation,但不直接支持 3D audio。

### 5.3 bevy_audio

`bevy_audio` 是 Bevy 引擎的 audio crate,与 ECS 集成:

```rust
// Bevy ECS setup
fn setup(mut commands: Commands, asset_server: Res<AssetServer>) {
    commands.spawn(AudioBundle {
        source: asset_server.load("sounds/gunshot.ogg"),
        settings: PlaybackSettings::DESPAWN,
    });
}
```

3D positional audio 在 Bevy 通过 plugin(`bevy_audio` 或第三方 `bevy_kira_audio`、`bevy_fmod`)。

### 5.4 bevy_fmod / fmod-rs

社区 binding。`bevy_fmod` 把 FMOD 集成到 Bevy ECS:

```rust
fn play_footstep(
    mut commands: Commands,
    fmod: Res<FmodPlugin>,
    query: Query<&Transform, With<Player>>,
) {
    for transform in query.iter() {
        let event = fmod.create_event("event:/footstep");
        event.set_3d_attributes(transform.translation);
        event.start();
    }
}
```

## 6 · 实战:Rust 完整 3D positional + adaptive music

整合所有零件,写一个 Rust 项目:

```rust
// Cargo.toml:
// [dependencies]
// audiopus = "0.3"
// rodio = "0.17"

use std::f32::consts::PI;
use std::sync::Arc;

// === Math helpers ===
#[derive(Clone, Copy, Debug)]
pub struct Vec3 { pub x: f32, pub y: f32, pub z: f32 }

impl Vec3 {
    pub fn new(x: f32, y: f32, z: f32) -> Self { Self { x, y, z } }
    pub fn length(self) -> f32 { (self.x * self.x + self.y * self.y + self.z * self.z).sqrt() }
    pub fn normalize(self) -> Self {
        let l = self.length();
        if l > 0.0 { Self { x: self.x / l, y: self.y / l, z: self.z / l } }
        else { Self { x: 0.0, y: 0.0, z: 0.0 } }
    }
    pub fn dot(self, other: Self) -> f32 {
        self.x * other.x + self.y * other.y + self.z * other.z
    }
}

impl std::ops::Sub for Vec3 {
    type Output = Self;
    fn sub(self, other: Self) -> Self {
        Self { x: self.x - other.x, y: self.y - other.y, z: self.z - other.z }
    }
}

// === Listener (player) ===
pub struct Listener {
    pub position: Vec3,
    pub velocity: Vec3,
    pub facing: Vec3,
    pub up: Vec3,
}

// === 3D Audio Source ===
pub struct SpatialSource {
    pub buffer: Vec<f32>,           // mono PCM
    pub position: Vec3,
    pub velocity: Vec3,
    pub playback_pos: f32,          // fractional position in buffer
    pub base_pitch: f32,            // 1.0 = normal
    pub ref_distance: f32,
    pub max_distance: f32,
    pub rolloff: f32,
    // Per-source HRTF state
    hrtf_history_l: Vec<f32>,
    hrtf_history_r: Vec<f32>,
    hrtf_pos_l: usize,
    hrtf_pos_r: usize,
    // Cached current direction / attenuation
    azimuth: f32,
    elevation: f32,
    distance_gain: f32,
    doppler_pitch: f32,
    // HRIR (impulse response) for current direction
    hrir_l: Vec<f32>,
    hrir_r: Vec<f32>,
    // Occlusion lowpass
    occlusion_filter: OnePoleLP,
}

impl SpatialSource {
    pub fn new(buffer: Vec<f32>, position: Vec3) -> Self {
        Self {
            buffer,
            position,
            velocity: Vec3::new(0.0, 0.0, 0.0),
            playback_pos: 0.0,
            base_pitch: 1.0,
            ref_distance: 1.0,
            max_distance: 50.0,
            rolloff: 1.5,
            hrtf_history_l: vec![0.0; 128],
            hrtf_history_r: vec![0.0; 128],
            hrtf_pos_l: 0,
            hrtf_pos_r: 0,
            azimuth: 0.0,
            elevation: 0.0,
            distance_gain: 1.0,
            doppler_pitch: 1.0,
            hrir_l: vec![0.0; 128],
            hrir_r: vec![0.0; 128],
            occlusion_filter: OnePoleLP::new(20000.0, 48000.0),
        }
    }

    pub fn update_listener(&mut self, listener: &Listener, hrtf_dataset: &HrtfDataset) {
        // Compute relative direction
        let to_source = self.position - listener.position;
        let distance = to_source.length();
        let dir = to_source.normalize();

        // Transform to listener-local coordinates
        // Right vector = forward × up
        let forward = listener.facing.normalize();
        let right = Vec3::new(
            forward.z * listener.up.y - forward.y * listener.up.z,
            forward.x * listener.up.z - forward.z * listener.up.x,
            forward.y * listener.up.x - forward.x * listener.up.y,
        ).normalize();
        let up = Vec3::new(
            right.y * forward.z - right.z * forward.y,
            right.z * forward.x - right.x * forward.z,
            right.x * forward.y - right.y * forward.x,
        );
        // Project dir onto listener axes
        let x_local = right.dot(dir);   // right
        let y_local = forward.dot(dir); // forward
        let z_local = up.dot(dir);      // up

        // Compute azimuth (-π to π, 0 = front)
        self.azimuth = x_local.atan2(y_local);
        // Elevation (-π/2 to π/2, 0 = horizontal)
        self.elevation = z_local.asin();

        // Update HRIR from dataset
        let (hrir_l, hrir_r) = hrtf_dataset.lookup(self.azimuth, self.elevation);
        self.hrir_l[..hrir_l.len()].copy_from_slice(hrir_l);
        self.hrir_r[..hrir_r.len()].copy_from_slice(hrir_r);

        // Distance attenuation
        self.distance_gain = distance_attenuation(distance, self.ref_distance, self.max_distance, self.rolloff);

        // Doppler
        let c = 343.0;
        let radial_vel = (self.velocity - listener.velocity).dot(dir);
        let v_r = radial_vel.max(-c + 1.0);  // clamp to avoid div by zero
        let new_pitch = self.base_pitch * c / (c - v_r);
        // Smooth pitch
        self.doppler_pitch = self.doppler_pitch * 0.99 + new_pitch * 0.01;
    }

    pub fn render(&mut self, output_l: &mut [f32], output_r: &mut [f32]) {
        let n = output_l.len();
        let pitch = self.doppler_pitch;
        for i in 0..n {
            // Resample from buffer using linear interpolation
            let pos = self.playback_pos as usize;
            let frac = self.playback_pos - pos as f32;
            let s0 = self.buffer.get(pos).copied().unwrap_or(0.0);
            let s1 = self.buffer.get(pos + 1).copied().unwrap_or(s0);
            let mut sample = s0 * (1.0 - frac) + s1 * frac;
            self.playback_pos += pitch;
            if self.playback_pos as usize >= self.buffer.len() {
                self.playback_pos = 0.0;  // loop
            }

            // Occlusion lowpass
            sample = self.occlusion_filter.process(sample);

            // Apply distance gain
            sample *= self.distance_gain;

            // HRTF convolution
            self.hrtf_history_l[self.hrtf_pos_l] = sample;
            self.hrtf_history_r[self.hrtf_pos_r] = sample;
            let mut sum_l = 0.0f32;
            let mut sum_r = 0.0f32;
            for k in 0..128 {
                let idx_l = (self.hrtf_pos_l + 128 - k) % 128;
                let idx_r = (self.hrtf_pos_r + 128 - k) % 128;
                sum_l += self.hrir_l[k] * self.hrtf_history_l[idx_l];
                sum_r += self.hrir_r[k] * self.hrtf_history_r[idx_r];
            }
            output_l[i] = sum_l;
            output_r[i] = sum_r;

            self.hrtf_pos_l = (self.hrtf_pos_l + 1) % 128;
            self.hrtf_pos_r = (self.hrtf_pos_r + 1) % 128;
        }
    }
}

// === One-pole lowpass (for occlusion) ===
pub struct OnePoleLP {
    a: f32,
    state: f32,
}

impl OnePoleLP {
    pub fn new(cutoff_hz: f32, sample_rate: f32) -> Self {
        let dt = 1.0 / sample_rate;
        let rc = 1.0 / (2.0 * PI * cutoff_hz);
        let a = dt / (rc + dt);
        Self { a, state: 0.0 }
    }

    #[inline]
    pub fn process(&mut self, input: f32) -> f32 {
        self.state = self.state + self.a * (input - self.state);
        self.state
    }

    pub fn set_cutoff(&mut self, cutoff_hz: f32, sample_rate: f32) {
        let dt = 1.0 / sample_rate;
        let rc = 1.0 / (2.0 * PI * cutoff_hz);
        self.a = dt / (rc + dt);
    }
}

// === Distance attenuation ===
pub fn distance_attenuation(distance: f32, ref_distance: f32, max_distance: f32, rolloff: f32) -> f32 {
    if distance >= max_distance { return 0.0; }
    if distance <= ref_distance { return 1.0; }
    let ratio = (distance - ref_distance) / (max_distance - ref_distance);
    (1.0 - ratio).powf(rolloff)
}

// === HRTF Dataset (placeholder, real impl loads SOFA) ===
pub struct HrtfDataset {
    // Simplified: store azimuth/elevation buckets
    // Real impl: SOFA file via SOFA-rs or hrtf-rs
    pub hrirs_l: Vec<Vec<f32>>,  // index by direction bucket
    pub hrirs_r: Vec<Vec<f32>>,
    pub azimuths: Vec<f32>,
    pub elevations: Vec<f32>,
}

impl HrtfDataset {
    pub fn lookup(&self, azimuth: f32, elevation: f32) -> (&[f32], &[f32]) {
        // Find nearest pre-computed
        let az_idx = self.azimuths.iter()
            .enumerate()
            .min_by_key(|(_, &a)| ((a - azimuth) * 1000.0) as i64)
            .map(|(i, _)| i)
            .unwrap_or(0);
        let el_idx = self.elevations.iter()
            .enumerate()
            .min_by_key(|(_, &e)| ((e - elevation) * 1000.0) as i64)
            .map(|(i, _)| i)
            .unwrap_or(0);
        let idx = el_idx * self.azimuths.len() + az_idx;
        (&self.hrirs_l[idx], &self.hrirs_r[idx])
    }
}

// === Adaptive music layer ===
pub struct AdaptiveMusicLayer {
    pub buffer: Vec<f32>,
    pub position: usize,
    pub current_gain: f32,
    pub target_gain: f32,
    pub fade_rate: f32,
}

impl AdaptiveMusicLayer {
    pub fn render(&mut self, output: &mut [f32]) {
        for x in output.iter_mut() {
            // Loop playback
            let sample = self.buffer.get(self.position).copied().unwrap_or(0.0);
            self.position = (self.position + 1) % self.buffer.len();

            // Smooth gain
            if (self.current_gain - self.target_gain).abs() < self.fade_rate {
                self.current_gain = self.target_gain;
            } else if self.current_gain < self.target_gain {
                self.current_gain += self.fade_rate;
            } else {
                self.current_gain -= self.fade_rate;
            }

            *x = sample * self.current_gain;
        }
    }
}

pub struct AdaptiveMusicSystem {
    layers: Vec<AdaptiveMusicLayer>,
    /// 0 = calm, 1 = tense, 2 = combat
    pub intensity: f32,
    pub intensity_target: f32,
}

impl AdaptiveMusicSystem {
    pub fn new() -> Self {
        Self { layers: vec![], intensity: 0.0, intensity_target: 0.0 }
    }

    pub fn add_layer(&mut self, buffer: Vec<f32>) {
        self.layers.push(AdaptiveMusicLayer {
            buffer,
            position: 0,
            current_gain: 0.0,
            target_gain: 0.0,
            fade_rate: 1.0 / (48000.0 * 0.5),  // 500ms fade
        });
    }

    pub fn set_intensity(&mut self, intensity: f32) {
        self.intensity_target = intensity.clamp(0.0, 1.0);
        // Smooth intensity
        let smooth_rate = 1.0 / (48000.0 * 2.0);  // 2s smooth
        // (applied in render)
    }

    pub fn render(&mut self, output: &mut [f32]) {
        // Smooth intensity
        if (self.intensity - self.intensity_target).abs() < 1.0 / (48000.0 * 2.0) {
            self.intensity = self.intensity_target;
        } else if self.intensity < self.intensity_target {
            self.intensity += 1.0 / (48000.0 * 2.0);
        } else {
            self.intensity -= 1.0 / (48000.0 * 2.0);
        }

        // Set layer gains based on intensity
        // 0 = drums (only combat), 1 = bass (tense +), 2 = melody (always), 3 = harmony (always)
        let n = self.layers.len();
        for (i, layer) in self.layers.iter_mut().enumerate() {
            let layer_norm = i as f32 / (n - 1).max(1) as f32;
            // Each layer fades in when intensity exceeds its threshold
            let threshold = layer_norm;
            if self.intensity > threshold {
                layer.target_gain = 1.0;
            } else {
                layer.target_gain = 0.0;
            }
        }

        // Render and sum
        let mut layer_out = vec![0.0f32; output.len()];
        for x in output.iter_mut() { *x = 0.0; }
        for layer in &mut self.layers {
            layer.render(&mut layer_out);
            for i in 0..output.len() {
                output[i] += layer_out[i];
            }
        }
    }
}

// === Complete 3D audio engine ===
pub struct AudioEngine {
    pub listener: Listener,
    pub sources: Vec<SpatialSource>,
    pub music: AdaptiveMusicSystem,
    pub hrtf_dataset: HrtfDataset,
    pub master_volume: f32,
}

impl AudioEngine {
    pub fn render(&mut self, output_l: &mut [f32], output_r: &mut [f32]) {
        let n = output_l.len();
        // Clear
        for i in 0..n {
            output_l[i] = 0.0;
            output_r[i] = 0.0;
        }

        // Render each spatial source
        let mut source_l = vec![0.0f32; n];
        let mut source_r = vec![0.0f32; n];
        for source in &mut self.sources {
            source.update_listener(&self.listener, &self.hrtf_dataset);
            source.render(&mut source_l, &mut source_r);
            for i in 0..n {
                output_l[i] += source_l[i];
                output_r[i] += source_r[i];
            }
        }

        // Render adaptive music (mono for now, can extend to stereo)
        let mut music_mono = vec![0.0f32; n];
        self.music.render(&mut music_mono);
        // Apply simple pan (center) for music
        for i in 0..n {
            output_l[i] += music_mono[i] * 0.5;
            output_r[i] += music_mono[i] * 0.5;
        }

        // Master volume
        for i in 0..n {
            output_l[i] *= self.master_volume;
            output_r[i] *= self.master_volume;
            // Soft clip to prevent clip
            output_l[i] = output_l[i].tanh();
            output_r[i] = output_r[i].tanh();
        }
    }
}

// === Game integration ===
pub struct GameWorld {
    pub audio: AudioEngine,
    pub player_health: f32,
    pub enemies_near: usize,
}

impl GameWorld {
    pub fn update_adaptive_music(&mut self) {
        // Health low -> tense
        let health_intensity = 1.0 - self.player_health;
        // Enemies near -> combat
        let enemy_intensity = (self.enemies_near as f32 / 10.0).min(1.0);
        // Combine
        let intensity = (health_intensity * 0.5 + enemy_intensity * 0.5).clamp(0.0, 1.0);
        self.audio.music.set_intensity(intensity);
    }
}
```

**性能数据**:这个完整 engine 处理 16 个 spatial source + 4 music layer,每秒 48000 sample:
- 每 source:resample + occlusion + HRTF = ~150 ns/sample = 7.2 ms CPU/sec
- 16 source = 115 ms/sec,**11.5% single core**
- Music:10 ms/sec
- Total:~12.5% single core

一台 8-core CPU 可以同时跑 ~60 source + music + voice chat,绰绰有余。

## 7 · 性能数据汇总

### 7.1 各组件 CPU 数据

| 组件 | CPU per sec @ 48kHz | 备注 |
|---|---|---|
| Horizontal sequencer | <1 ms | 几乎免费 |
| Vertical layering 5 layer | 5 ms | 每 layer ~1 ms |
| ELIS simplified | 2 ms | |
| Biquad lowpass (per source) | 0.5 ms | TDF2 |
| Distance attenuation | <0.1 ms | 一条 mul |
| Doppler + resample | 1.5 ms | linear interp |
| Occlusion (1 ray cast per source) | 0.5 ms | 取决于 physics engine |
| HRTF 128-tap per source | 7 ms | 时域 convolution |
| HRTF 128-tap with SIMD | 2 ms | SSE/AVX2 |
| Image source 6 reflections | 42 ms | 6 × HRTF |
| Convolution reverb 2s IR | 50 ms | partitioned FFT |
| Freeverb | 24 ms | 8 comb + 4 allpass |
| Opus encode 24kbps mono | 8 ms | i7-12700H |
| Opus decode | 3 ms | |
| Jitter buffer | <1 ms | 只是 buffer |
| WebRTC AEC3 | 30 ms | echo cancel |
| RNNoise denoiser | 12 ms | neural network |

### 7.2 Latency 数据

| Stage | Typical latency |
|---|---|
| Mic capture → PCM | 5-20 ms(driver) |
| AEC / denoise | 5-10 ms |
| Opus encode | 5 ms(20ms frame + lookahead) |
| Network transit | 20-100 ms(WAN) |
| Jitter buffer | 60-100 ms |
| Opus decode | 1 ms |
| Audio output | 5-20 ms(driver) |
| **Total voice chat** | **100-250 ms** |

| Stage | Typical latency |
|---|---|
| Game 3D spatial render | 0 ms(in-line) |
| Audio callback → speaker | 10-20 ms |
| **Total game sound** | **10-30 ms** |

### 7.3 Bandwidth 数据

| Codec | Bitrate | Quality |
|---|---|---|
| PCM 16-bit 48kHz mono | 768 kbps | Lossless |
| PCM 16-bit 16kHz mono | 256 kbps | Phone quality |
| G.711 (8kHz) | 64 kbps | Old phone |
| G.722 | 48-64 kbps | Better phone |
| Speex 16kHz | 28 kbps | OK |
| Opus 16kHz voice | 8 kbps | Good |
| Opus 48kHz voice | 24 kbps | Excellent |
| Opus 48kHz music | 64 kbps | High quality |
| Opus 48kHz stereo music | 128 kbps | Near-CD |

### 7.4 HRTF dataset 大小

| Dataset | Subjects | Directions | Total IR |
|---|---|---|---|
| MIT KEMAR | 1 (mannequin) | 710 | 710 |
| CIPIC | 45 | 1250 | 56,250 |
| IRCAM Listen | 50 | 187 | 9,350 |
| ARI HRTF (SADIE) | 20 | 2113 | 42,260 |

每个 IR 128 sample × 4 bytes = 512 bytes。CIPIC total = 28 MB(合理大小,可以打包到 game)。

## 8 · 在你 HH 项目里实践

### 8.1 落地 1:footstep 3D positional

你的 player 走,footstep 触发 sound。把 footstep source 放在 player position:

```rust
fn play_footstep(audio: &mut AudioEngine, player_pos: Vec3) {
    let mut source = SpatialSource::new(footstep_buffer.clone(), player_pos);
    source.ref_distance = 0.5;
    source.max_distance = 10.0;  // footstep doesn't carry far
    source.rolloff = 2.0;
    audio.sources.push(source);
}
```

玩家自己的 footstep 离 listener 太近(distance ≈ 0),直接 use ref_distance gain。

### 8.2 落地 2:enemy AI 的位置感

敌人巡逻,你听 enemy voice chat。把 enemy source 在 enemy 位置:

```rust
fn spawn_enemy(audio: &mut AudioEngine, enemy_pos: Vec3) {
    let mut source = SpatialSource::new(enemy_voice_buffer.clone(), enemy_pos);
    source.ref_distance = 1.0;
    source.max_distance = 30.0;
    audio.sources.push(source);
}
```

每帧 update source position(enemy 移动):

```rust
fn update_enemy(audio: &mut AudioEngine, enemy_idx: usize, new_pos: Vec3) {
    audio.sources[enemy_idx].position = new_pos;
}
```

听感:enemy 在你后面,声音从后面来(HRTF)。Enemy 跑过你,声音从左移到右。

### 8.3 落地 3:adaptive music

游戏状态 explore / combat 切换:

```rust
fn update_music(world: &mut GameWorld) {
    let in_combat = world.enemies_in_combat > 0;
    if in_combat {
        world.audio.music.set_intensity(1.0);  // combat music
    } else if world.enemies_near > 0 {
        world.audio.music.set_intensity(0.5);  // tense
    } else {
        world.audio.music.set_intensity(0.0);  // calm
    }
}
```

### 8.4 落地 4:room reverb

进入大教堂,所有声音"watery"。在 source pipeline 加 room reverb send:

```rust
// In render loop, also feed source to a shared room reverb
let reverb_send = source_l.clone();
room_reverb.process(&reverb_send, &mut reverb_out_l);
output_l[i] += reverb_out_l[i] * room_reverb_amount;
```

room_reverb_amount 由 room type 决定(cathedral = 0.4,small room = 0.1)。

### 8.5 落地 5:low-health filter

玩家 health < 30%,所有声音加 lowpass + slow tremolo(模拟"接近死亡"听感):

```rust
fn apply_low_health_filter(world: &mut GameWorld, dt: f32) {
    let health_factor = if world.player_health < 0.3 {
        1.0 - world.player_health / 0.3  // 0..1
    } else { 0.0 };
    // Set global lowpass cutoff
    let cutoff = 20000.0 - 18000.0 * health_factor;  // 20000 -> 2000 Hz
    world.audio.master_lowpass.set_cutoff(cutoff, 48000.0);
}
```

### 8.6 落地 6:voice chat(简单版)

64 player server,每个 player 一路 voice。简化为单 player voice receive:

```rust
pub struct VoiceChatSystem {
    receivers: Vec<VoiceChatReceiver>,
    opus_encoder: OpusVoiceChat,
    capture_buf: Vec<i16>,
}

impl VoiceChatSystem {
    pub fn on_local_voice(&mut self, pcm: &[i16]) -> Vec<u8> {
        // Encode local voice
        self.opus_encoder.encode(pcm)
    }

    pub fn on_remote_packet(&mut self, voice_id: u32, packet: Vec<u8>) {
        if let Some(receiver) = self.receivers.get_mut(voice_id as usize) {
            receiver.on_packet(/* seq */, packet);
        }
    }
}
```

每 frame render 所有 receiver:

```rust
fn render_voice_chat(voice: &mut VoiceChatSystem, output_l: &mut [f32], output_r: &mut [f32]) {
    let mut l = vec![0.0f32; output_l.len()];
    let mut r = vec![0.0f32; output_r.len()];
    let mut temp_l = vec![0.0f32; output_l.len()];
    let mut temp_r = vec![0.0f32; output_r.len()];
    for receiver in &mut voice.receivers {
        receiver.render(&mut temp_l, &mut temp_r);
        for i in 0..l.len() {
            l[i] += temp_l[i];
            r[i] += temp_r[i];
        }
    }
    for i in 0..output_l.len() {
        output_l[i] += l[i];
        output_r[i] += r[i];
    }
}
```

## 9 · 历史演化与开源贡献

### 9.1 Adaptive music 时间线

| 年 | 引擎 | 创新 |
|---|---|---|
| 1993 | iMUSE(LucasArts) | 早期 adaptive MIDI system,Monkey Island / DOOM 用 |
| 1998 | DirectMusic | Microsoft 的 segment-based adaptive |
| 2002 | FMOD | Sample-accurate music transition |
| 2003 | Wwise | 类似 FMOD,更深 source control |
| 2008 | Elias | 真正 seamless ELIS transition |
| 2010s | CRI ADX2 | 日本,Sega / Capcom 用 |
| 2015+ | Adaptive music in middleware | FMOD/Wwise 标配 |

### 9.2 3D audio 时间线

| 年 | 技术 | 创新 |
|---|---|---|
| 1970s | Quadraphonic | 4-speaker surround |
| 1980s | Dolby Pro Logic | 5.1 from stereo |
| 1990s | Aureal A3D | First commercial HRTF gaming |
| 1998 | DirectSound3D | Microsoft HW-accelerated 3D |
| 2000s | OpenAL | Cross-platform 3D |
| 2010s | Steam Audio, Oculus Audio | Modern HRTF + reflection |
| 2020s | Sony Tempest 3D Audio | PS5 hardware 3D audio |

### 9.3 Opus codec 时间线

| 年 | 事件 |
|---|---|
| 2009 | Skype SILK 公开 |
| 2007 | Xiph CELT 开发 |
| 2010 | Opus 标准化开始(IETF codec WG) |
| 2012 | RFC 6716 发布(Opus 1.0) |
| 2013 | Opus 1.1(CELT 模式改进) |
| 2016 | Opus 1.1.3(广泛部署) |
| 2019 | Opus 1.3(DTX 改进, surround support) |
| 2022+ | Opus 1.5(ML-based loss concealment) |

### 9.4 开源贡献机会

适合贡献的开源项目:

1. **`rust-opus`** / **`audiopus`**:Rust Opus binding。可贡献:
   - 更好的错误类型
   - Async API
   - SIMD optimization for wrapper

2. **`rodio` spatial module**:https://github.com/RustAudio/rodio/blob/master/src/spatial.rs 。可以贡献 HRTF 渲染、occlusion。

3. **`kira`**:https://github.com/tesselode/kira 。可以贡献 3D positional 支持。

4. **`bevy_audio`**:https://github.com/bevyengine/bevy/tree/main/crates/bevy_audio 。可以贡献 spatial audio system。

5. **`Steam Audio Rust binding`**:社区需要 Rust binding 到 Steam Audio(Phonon)。https://github.com/ValveSoftware/steam-audio

6. **`Resonance Audio Rust binding`**:Google 的 3D audio library,需要 Rust binding。

7. **`HRTF dataset tooling`**:SOFA file 加载、interpolation 的 Rust crate(目前几乎没有 mature 的)。

### 9.5 论文与参考资料

- Gardner & Martin 1994 "HRTF Measurements of a KEMAR Dummy-Head Microphone"(MIT KEMAR 经典 paper)
- Blauert "Spatial Hearing"(心理学+物理,revised edition)
- Begault "3-D Sound for Virtual Reality and Multimedia"
- Vorlander "Auralization: Fundamentals of Acoustics, Modelling, Simulation, Algorithms and Acoustic Virtual Reality"
- Opus RFC 6716:https://datatracker.ietf.org/doc/html/rfc6716
- WebRTC AEC3 paper
- RNNoise paper:https://arxiv.org/abs/1709.08243
- Elias model paper(白皮书)

## 10 · 检查清单

读完这一篇,你应该能:

- [ ] 解释 horizontal re-sequencing vs vertical re-orchestration
- [ ] 实现 bar-aligned segment switching + crossfade
- [ ] 实现 vertical layering with smoothed gain
- [ ] 解释 ELIS 模型的核心 idea
- [ ] 解释 HRTF 的物理意义,知道 SOFA 文件格式
- [ ] 实现 128-tap HRTF convolution
- [ ] 推导 ITD 公式(Woodworth formula)
- [ ] 解释 ILD 在高频 vs 低频的差异
- [ ] 实现 distance attenuation with configurable rolloff
- [ ] 实现 occlusion with material-dependent lowpass
- [ ] 实现 image source early reflections(至少 1st-order)
- [ ] 实现 Doppler effect with smoothing
- [ ] 解释 Opus codec 的 CELT + SILK 混合策略
- [ ] 实现完整 voice chat pipeline:capture → encode → network → jitter → decode → spatialize → mix
- [ ] 在 HH 项目里落地 footstep 3D、enemy positional、adaptive music

## 11 · 延伸阅读

本仓库相关:
- [audio-effects.md](../phase-5/deep-dives/audio-effects.md) — 效果器全解(reverb、EQ、compressor),这一篇直接依赖
- [audio-pipeline-complete.md](../phase-5/deep-dives/audio-pipeline-complete.md) — WAV/ALSA 流水线
- [network-multiplayer-models.md](../phase-5/deep-dives/network-multiplayer-models.md) — 网络模型,voice chat 底层
- [threading-journey.md](../phase-5/deep-dives/threading-journey.md) — audio thread 实时性

外部稳定 URL:
- FMOD Docs:https://fmod.com/docs
- Wwise Docs:https://www.audiokinetic.com/library/
- Opus Codec:https://opus-codec.org/
- SOFA format:https://www.sofaconventions.org/
- MIT KEMAR HRTF:https://sound.media.mit.edu/resources/KEMAR.html
- CIPIC HRTF:https://www.ece.ucdavis.edu/cipic/spatial-sound/hrtf-data/
- Steam Audio:https://valvesoftware.github.io/steam-audio/
- Resonance Audio:https://resonance-audio.github.io/resonance-audio/
- WebRTC:https://webrtc.org/

开源源码:
- `rodio` spatial:https://github.com/RustAudio/rodio/blob/master/src/spatial.rs
- `kira`:https://github.com/tesselode/kira
- `bevy_audio`:https://github.com/bevyengine/bevy/tree/main/crates/bevy_audio
- `audiopus`:https://github.com/Thinker-Machine / audiopus-rs
- `libpd`(Pure Data C library):https://github.com/libpd/libpd
- OpenMHA(ARI HRTF tools):https://www.openmha.org/

写到这里,你的工具箱里有:

- **Adaptive music**:horizontal sequencer + vertical layering + ELIS 概念
- **3D positional audio**:HRTF、ITD/ILD、distance attenuation、occlusion、early reflections、Doppler
- **Voice chat**:Opus encode/decode、jitter buffer、FEC、PLC
- **Rust 实现**:完整 AudioEngine,16 source + music + voice chat
- **性能数据**:每组件 CPU、latency、bandwidth 数据
- **HH 项目落地**:6 个具体场景

接下来:**关掉 IDE 旁边的 Spotify,打开你的 HH 项目,加一个 spatial enemy source,用 headphone 听 enemy 在你后面走**。第一次听到 enemy 真的"在后面"的声音,你就懂 HRTF 的魔法。

然后给 BGM 加 vertical layering —— 调 health 滑块,听 melody + bass + drum 一层层加进来。这就是 adaptive music 的核心:**音乐是活的,响应玩家**。

最后做 voice chat —— 找个朋友,WebRTC 或自建 UDP server,跑 Opus 24kbps,听延迟 < 150ms 的真实对话。**每一毫秒你减掉的 latency,都是你今天学到的全部。**
