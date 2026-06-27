---
phase: 5
title_en: "Build a Soft Synth — Capstone"
title_zh: "造一台软合成器:T2 音频深度序列收口"
type: deep-dive
difficulty: advanced
duration: 5h
domains: [game, audio, rust, linux, system, math]
calibration: "综合 capstone:从零写一个软合成器/迷你 DAW(CCRMA 320C 风格)"
prereqs: [synthesis-and-instruments, dsp-fundamentals, fft-and-spectral-analysis, audio-effects, physical-modeling-synthesis]
---

# 造一台软合成器:T2 音频深度序列收口

> 你在 [phase-0/22-signals-foundation.md](../../phase-0/22-signals-foundation.md) 把"声音"变成了一串数。在 [dsp-fundamentals.md](dsp-fundamentals.md) 写了第一个 biquad。在 [fft-and-spectral-analysis.md](fft-and-spectral-analysis.md) 把时域拖进频域,看见锯齿波的谐波像一串排队的小峰。在 [synthesis-and-instruments.md](synthesis-and-instruments.md) 拼出 polyBLEP saw + ADSR + 滤波器的减法合成 voice。在 [audio-effects.md](audio-effects.md) 做了 reverb、compressor、delay。在 [physical-modeling-synthesis.md](physical-modeling-synthesis.md) 用一根延迟线做出 Karplus-Strong 吉他弦。在 [audio-pipeline-complete.md](audio-pipeline-complete.md) 看见 cpal callback 怎么从声卡被拉出来。**这些是音频工程的全部零件——散落的零件**。这一篇是 capstone:把所有零件**组装成一台能玩的乐器**。一台实时软件合成器(soft synthesizer),按一个键声音立刻出来,十个键一起按十根弦一起响。当你按下键的指尖到耳朵之间那段延迟小于 20 毫秒——**你拥有了音频工程**,从 sample 到 instrument 整条链路都是你造的。这是 CCRMA 320C(Stanford 计算机音乐高级项目课)的最终大作业,也是 T2 音频深度序列的终点。

## 0 · 一个夜晚,你的合成器第一次发声

凌晨两点。终端里 cargo build 一遍遍跑,屏幕上是 cpal callback、polyBLEP saw、ADSR、voice pool。你敲下 `cargo run --release`,戴上耳机,手指搭上键盘。按 `A` 键。**什么都没有**——你忘了把 gate 推到 audio thread。改一行,重跑。再按 `A`。一声"嗡——"从耳机里涌出来,锯齿的明亮,被低通滤波削去尖角,被 ADSR 描出 attack 的扬起、sustain 的稳住。按 `S`,第二根弦叠上来,两根 saw 在 stereo field 里轻轻 detune,你听见 unison 的厚度。按 `D`、`F`、`G`——五个键,五个 voice,五条信号链同时跑在 audio thread 上。你的电脑键盘变成了一台 Minimoog。

这一刻你做的不是"播放一个 wav"。**是一台乐器**:每一个 sample 都是数学函数实时算出来的,按你的指尖响应,无延迟、无卡顿。这是 T2 整个序列的目的地——把零件变成乐器。

## 1 · 软合成器的架构:一条信号链的叙述

理解一台软合成器,最好的方式是**沿着声音走的路径**讲一遍。声音不是从喇叭出来的——是从一个个 **voice** 开始的,每个 voice 是一根独立的信号链。按下键,合成器**分配一个 voice** 给这个键;voice 跑它的信号链,直到 release 完成才被回收。同时按下五个键,合成器跑五条独立信号链,把五条链的输出加在一起,送进 master effect,送进声卡。

这条路径每一块都是前几篇 deep-dive 见过的东西,只是现在要**串起来**:

**Voice management(voice 管理层)**。合成器有固定大小的 **voice pool**(典型 8-64 个 voice)。每个 voice 处于三种状态之一:空闲(Idle)、正在发音(Playing)、正在释放(Releasing)。新键按下时先找空闲 voice;都满了,就**偷**(voice stealing)——挑一个最老或最弱的 voice,粗暴 release 掉腾给新键。

**Per-voice signal chain(每条 voice 的信号链)**。这是 [synthesis-and-instruments.md](synthesis-and-instruments.md) 第 7 节那张图的实例化:**振荡器 → 滤波器 → 放大器**,沿途被 envelope 和 LFO 调制。振荡器决定"原料"(saw、square、FM、wavetable),滤波器决定"亮度",放大器决定"响度轮廓"。这条链每一级你前面都写过。

**Voice mix(voice 混合)**。所有 active voice 的输出 sample-by-sample 相加。N 个 voice 同时响,总能量 N 倍,必须**软限幅**(soft clip,通常 `tanh`)——直接 clip 会产生"咔"。这就是 [audio-pipeline-complete.md](audio-pipeline-complete.md) 第 4 节那个 mixer 干的事。

**Master effects(master 效果总线)**。混合后的信号过一串全局效果:EQ、compressor、reverb、limiter。这些是 [audio-effects.md](audio-effects.md) 里学过的。一台软合成器和一堆 voice 的区别,**就在 master bus**——master 给了它"成品感",让它听起来像一个整体而不是 N 个独立 oscillator。

**Output(输出)**。最后过 master volume、可能的 soft clip,送进 cpal 的 buffer。

整条路径**没有一处是新的**——每一块都是 T2 序列里你写过的东西。capstone 的工作是**把它们组装成一个可玩、可扩展、可维护的整体**。听起来简单,做起来极难,因为**它们必须在实时音频线程里一起跑,一毫秒都不能超时**。

## 2 · 实时约束:audio callback 是工程里最严酷的契约

理解软合成器,**第一件事不是声音,是约束**。cpal 给你的 callback 长这样:

```rust
move |out: &mut [f32], _: &cpal::OutputCallbackInfo| {
    // 你必须在这里填满 out[],然后在 deadline 前返回
}
```

声卡的 DAC 在自己的时钟上跑(那是硬件晶振,不停),每隔 `buffer_size / sample_rate` 秒就来要一批 sample。48 kHz、256 sample buffer 上,callback 每 **5.3 毫秒**被调用一次。这 5.3 毫秒里你必须:**从 message ring 拉新 note 事件**、**更新所有 active voice 的 envelope**、**每个 voice 跑完振荡器+滤波器+放大器**、**把所有 voice 混合**、**过 master effect**、**写满 buffer**。**任何一步慢了,DAC 没数据,就播零或播上一帧的尾巴——这就是 underrun,听感是"咔哒"一声**。

这个 deadline 不是"最好满足",而是"必须满足,否则就崩"。**这是整个游戏引擎里最严酷的实时约束**。渲染线程慢一帧,玩家看到 30 FPS 而不是 60 FPS,体验下降但不崩;物理线程慢一帧,碰撞检测延迟,可以补;**audio callback 慢一帧,声音直接断裂,玩家立刻听见**。

所以 audio callback 有一组铁律——这些规则在 [audio-pipeline-complete.md](audio-pipeline-complete.md) 第 2.3 节列过,这里从合成器的角度再强调一遍:

**绝对不能分配内存**。`Vec::push`、`Box::new`、`String::from`,任何 alloc 都可能触发 mmap 向 OS 要页,几十毫秒。这意味着 voice pool 必须**在启动时一次性分配好**,callback 只能复用预分配的 voice 槽位。

**绝对不能等锁**。`Mutex::lock()` 在别的线程持锁时会阻塞,futex 系统调用几毫秒。input thread 给 audio thread 送 note 事件**不能用 std Mutex**,必须用 lock-free 队列。

**绝对不能做 IO**。文件、网络、`println!`,任何系统调用都可能被调度器换出去。`println!` 在 callback 里 = 偶发 underrun,而且极难复现——典型的"恶魔 bug"。

**绝对不能复杂动态分发**。虚函数表(vtable)虽不阻塞,但 cache miss 在 N voice × M sample 的 hot loop 里是性能杀手。callback 里应该用**静态分发**(generic + monomorphization)或**直接枚举 match**。

工业级实现把 audio thread 隔离成一个**纯净的世界**:它只读两类数据——预分配好的、不可变的资源(采样表、IR、wavetable frame),和 lock-free 队列里送来的事件。这两个规则保证了 audio thread **永远不会被外部世界阻塞**。这就是 [phase-4/lock-free-programming.md](../../phase-4/deep-dives/lock-free-programming.md) 和 [phase-9/09B-1-game-loop-and-timestep.md](../../phase-9/09B-1-game-loop-and-timestep.md) 的线程模型在音频上的具体化——audio thread 是最高优先级的"实时岛",其它一切(输入、UI、磁盘)都在外面的"普通岛"上,两岛之间只通过 lock-free 队列通信。

## 3 · 锁无锁的 message ring:从 input thread 到 audio thread

你的合成器有两个线程在跑。**Input thread**(主线程)读键盘 / MIDI,产生 note_on / note_off 事件。**Audio thread**(callback)消费这些事件,触发 voice。怎么把事件从主线程送到 audio thread?

不能用 `std::sync::mpsc::channel`——`recv` 会阻塞。不能用 `Mutex<Vec<Event>>`——audio thread 等 lock 会 underrun。答案是**单生产者单消费者无锁环形队列**(lock-free SPSC ring)。`crossbeam-queue::ArrayQueue` 是生产级实现:

```rust
use crossbeam_queue::ArrayQueue;
use std::sync::Arc;

#[derive(Clone, Copy)]
pub enum VoiceEvent {
    NoteOn  { note: u8, velocity: u8 },
    NoteOff { note: u8 },
    SetCutoff { hz: f32 },
    SetReverb { amount: f32 },
}

let event_queue: Arc<ArrayQueue<VoiceEvent>> = Arc::new(ArrayQueue::new(1024));

// 主线程:按键时 push(不阻塞,满则丢)
event_queue.push(VoiceEvent::NoteOn { note: 60, velocity: 100 }).expect("queue full");

// Audio thread:每次 callback 开头 drain(不阻塞,空则 None)
while let Some(ev) = event_queue.pop() {
    synth.dispatch(ev);  // 改 voice 状态,绝不 alloc
}
```

`push` 满时返回 Err,`pop` 空时返回 None——**两者都不阻塞**。要追求极致性能(64+ voice、复杂事件流),可以手写**纯 atomic 的 SPSC ring**,每个 push/pop 只有几个 atomic 操作,没有 CAS 重试。这是 [audio-pipeline-complete.md](audio-pipeline-complete.md) 第 3.3 节那个 `SpscRing` 的思路——capacity 必须是 2^n(让 `% capacity` 变成 `& mask`),用 `Acquire/Release` 内存序保证 buffer 写入对另一线程可见。深入讨论见 [threading-journey.md](threading-journey.md) 和 [phase-4/lock-free-programming.md](../../phase-4/deep-dives/lock-free-programming.md)。

**关键认知**:message ring 不是"性能优化",是**架构必需**。它是 audio thread 和外部世界之间**唯一的桥**。所有跨线程的通信——参数变化、新 note、停止、加载新音色——都必须打包成 event,从这根管道里流过去。这条规则一旦打破(比如在 callback 里直接读主线程的某个 `Arc<Mutex<Params>>`),underrun 就会出现,而且只在系统负载高时偶发,极难调试。

## 4 · 延迟:键盘到耳朵的那 20 毫秒

软合成器和音乐播放器有一个本质区别:**它要响应玩家**。你按下一个键,期望声音立刻出来。"立刻"在人类感知里是**约 20 毫秒**以内——超过这个延迟,你会感觉"这架琴弹起来拖泥带水",节奏感丢了。专业钢琴家能感觉到 10 毫秒的延迟;20 毫秒是业余玩家的可接受上限;超过 50 毫秒,所有人都能听出来"按了之后过一会儿才响"。

这条 20 毫秒预算要分摊到整条链路:**键盘 USB 轮询(1-8 ms)+ 操作系统 input 调度(1-5 ms)+ 你的 input thread 响应(<1 ms)+ message ring 排队(<1 frame)+ audio buffer 等待(等于 buffer 大小)+ DAC/喇叭(1 ms)**。其中**最大、最可控的一块是 audio buffer 大小**。

buffer 大小是延迟,也是风险。`buffer_size = 64` @ 48 kHz = **1.3 毫秒**延迟,但 callback 每 1.3 ms 就要被调用一次,你的 synth 必须在 1.3 ms 内算完 64 个 sample × N voice × (振荡器 + 滤波器 + envelope)。任何一次超时就是 underrun。`buffer_size = 1024` = **21 毫秒**延迟,callback 每 21 ms 调用一次,有充分时间算,但延迟已经把 20 ms 预算全吃光了。

这是音频工程的核心**张力**:小 buffer = 低延迟但易 underrun,大 buffer = 稳但延迟感强。专业解决方案是 **PRO audio profile**——Linux 的 JACK、Windows 的 WASAPI exclusive、macOS 的 CoreAudio EX,允许 < 5 ms 的 buffer,代价是要 root/管理员权限或独占声卡。PipeWire 的 "pro" session manager 默认 quantum 是 256 sample(5.3 ms),已经能舒服地弹琴。调试方法见 [audio-pipeline-complete.md](audio-pipeline-complete.md) 第 6 节:`pw-top` 看 latency 和 xrun 列。

**实测延迟**:从按键到出声的端到端延迟很难直接测——需要回路设备(喇叭外放 + 麦克风录 + 算波形对齐)。工业做法是用 [phase-4/profiling-with-tracy.md](../../phase-4/deep-dives/profiling-with-tracy.md) 测 audio callback 的执行时间和调度抖动,间接推断。一个稳定的 synth,callback 执行时间的 **99.9 分位**必须远小于 buffer 时长(典型 < 50% buffer 时长)——剩下的是给 OS 调度抖动的余量。

## 5 · MIDI 与键盘:note 事件如何到达

合成器要"被弹",得有 note 事件来源。三种主流:

**MIDI(Musical Instrument Digital Interface)**。1983 标准化的乐器协议。一个 MIDI note-on 消息是 3 字节:`[status, note, velocity]`,status = 0x90(note-on channel 0),note 是 0-127 的音高编号(60 = 中央 C),velocity 是 0-127 的力度。note-off 是 0x80,或 0x90 + velocity=0(运行状态)。Rust 生态用 `midir` crate 接收硬件 MIDI 键盘。

**OSC(Open Sound Control)**。现代替代,基于 UDP,支持任意精度浮点和路径(`/synth/1/note_on 60 100`)。CNMAT 提出,Ableton Live、Reaktor 用。游戏里几乎不用,合成器开发偶尔用(网络化乐器)。

**电脑键盘**。最简单的开发方案——把 QWERTY 键盘当 piano,A S D F G H J 当 C D E F G A B。`winit` / `gilrs` / `crossterm` 都能读键盘事件。本篇 HH 项目就用这个,因为不依赖硬件。

无论来源,**最后都归约成同一组 event**:note_on(note, velocity)、note_off(note)、参数变化(cutoff、reverb 量)。这组 event 就是第 3 节那条 message ring 里流的东西。**输入设备和解码逻辑是 input thread 的事,audio thread 只看见统一的 event**——这是好的分层。

把 MIDI note 转成频率是**音律**(tuning)的事。最常见是 **12 平均律(12-TET)**:`f = 440 × 2^((note - 69) / 12)`,69 是 A4(440 Hz)的 MIDI 编号。这个公式你会在每一个 synth 项目里写一遍。注意 12-TET 不是唯一音律——just intonation、microtonal、印尼 gamelan 的 5-tone slendro,都用不同的 note → 频率映射。一台好的 synth 应该把 tuning 抽象出来,允许用户换。

## 6 · ADSR 与 note 生命周期

note 事件到达 voice 后,要变成**声音的形状**。这就是 ADSR envelope 的工作——你在 [synthesis-and-instruments.md](synthesis-and-instruments.md) 第 5 节写过完整实现,这里从**生命周期**的角度再看一遍。

一个 voice 的完整生命周期:note_on 到达 → **Attack**(从 0 升到 1)→ **Decay**(从 1 降到 sustain_level)→ **Sustain**(保持 sustain_level,**这是电平不是时间**)→ note_off 到达 → **Release**(从当前电平降到 0)→ **Idle**(voice 可被回收)。

**Sustain 是电平不是时间**——初学者最常踩的坑。Sustain 是"键按住时声音维持多响",不是"维持多久"。维持多久取决于**你按多久**。release 从你松手开始算。

ADSR 至少**两个**:一个 **amplitude envelope** 控制放大器(响度的时间曲线),一个 **filter envelope** 控制滤波器 cutoff(亮度的时间曲线——典型 synth lead 是 attack 时亮、decay 后变暗)。两个独立参数,再加一个 LFO 做颤音,就是减法合成器的标准三件套。

关于 exponential vs linear 段、looping envelopes 等,见 [synthesis-and-instruments.md](synthesis-and-instruments.md) 第 5 节。这里只强调一个 capstone 必须正确的细节:**note_off 在 attack 或 decay 段中间到达时,必须从当前电平 release**,不是从 peak 或 sustain——否则会有跳变。错误实现是 reset 到某个固定值再 release,听起来"咔"。

## 7 · 复音与 voice stealing:有限的 voice 池

一台真实合成器,**voice 数量是有限的**。每多一个 voice,CPU 多一份开销。Moog Minimoog 是单音(monophonic),DX7 是 16-voice polyphonic,现代 soft synth 通常 32-128 voice。**64 voice 对几乎所有 musical 场景都够**,32 已经很慷慨。

voice pool 大小是权衡:**CPU 预算** vs **使用场景**。钢琴声部可能同时按 10 个键(chord + pedal),管弦乐模拟可能 20+,合成器 lead 通常 1-8。

voice 池满了怎么办?**Voice stealing(偷 voice)**。挑一个 active voice,**强制 release**(几毫秒内衰减到 0),然后 note_on 这个 voice 给新键。挑哪个 voice 是策略问题:

**最老(oldest)**:最早 note_on 的 voice 先被偷。简单,但可能偷掉一个正在 sustain 的长音。

**最弱(quietest)**:当前 envelope 电平最低的 voice 被偷。听感最自然——偷掉一个几乎听不见的 voice,玩家察觉不到。

**同音高(same note)**:新键和某个 active voice 同音高,优先偷那个(re-trigger 同一个音)。钢琴的行为——同键反复弹,重新触发同一个 voice。

**Release 中的(releasing)**:正在 release 段的 voice 优先被偷——它们已经在淡出,偷掉听感冲击最小。

实现 voice stealing 的关键:**不要直接抢断**。直接抢断会有 click(包络从 0.5 突然跳到 0,然后又跳到 attack 的 0)。正确做法是**快速 release**——给被偷的 voice 几毫秒的"超快 release"(比如 5 ms),让它平滑淡出,然后 note_on。这叫 **fast release / voice-release tail**。具体代码见第 8 节的 `fast_release_then_trigger`:进入 `Transitioning` 状态,5 ms 内 envelope 降到 0,**然后**才真正触发新 note_on。这段时间里 voice 是"过渡中",不能被再偷。

## 8 · 把零件拼起来:一台可玩的减法合成器

把前面所有讨论落到代码。下面是一台**多音色减法合成器**的核心,基于 [synthesis-and-instruments.md](synthesis-and-instruments.md) 第 12 节那版扩展——加了 voice state machine、voice stealing、lock-free event ring、master effect 槽位。

DSP 原语(polyBLEP saw、square、ADSR、OnePoleLpf)直接复用 [synthesis-and-instruments.md](synthesis-and-instruments.md) 第 2 节和第 12 节的实现,这里不重复。我们要写的**新东西**是 voice state machine 和 voice stealing——这是 capstone 比 synthesis anchor 多出的工程层。

`Cargo.toml`:

```toml
[package]
name = "hh-soft-synth"
version = "0.1.0"
edition = "2021"

[dependencies]
cpal = "0.15"
crossbeam-queue = "0.3"
# 可选:midir = "0.9"  # 接 MIDI 键盘;rustfft = "0.6"  # convolution reverb

[profile.release]
opt-level = 3
lto = "fat"
codegen-units = 1
panic = "abort"  # audio thread panic 不能 unwind,abort 更安全
```

**ADSR 加 FastRelease 状态**——voice stealing 必需。在 synthesis anchor 的 ADSR 基础上多一个状态:

```rust
#[derive(PartialEq, Clone, Copy)]
enum EnvState { Idle, Attack, Decay, Sustain, Release, FastRelease }

pub struct Adsr {
    state: EnvState,
    pub attack: f32, pub decay: f32, pub sustain: f32, pub release: f32,
    level: f32, sample_rate: f32,
    fast_release_rate: f32,  // 5 ms 淡出,voice stealing 用
}

impl Adsr {
    // ...Attack/Decay/Sustain/Release 段同 synthesis-and-instruments.md 第 5 节...
    pub fn fast_release(&mut self) { self.state = EnvState::FastRelease; }
    pub fn level(&self) -> f32 { self.level }
    pub fn process(&mut self) -> f32 {
        match self.state {
            // ...其它段略...
            EnvState::FastRelease => {
                self.level -= self.fast_release_rate;
                if self.level <= 0.0 { self.level = 0.0; self.state = EnvState::Idle; }
            }
            _ => {}
        }
        self.level
    }
}
```

**Voice with state machine**——核心是 `Transitioning` 状态(voice stealing 的过渡):

```rust
#[derive(PartialEq)]
pub enum VoiceState { Idle, Playing, Releasing, Transitioning }  // Transitionning = fast release 中

pub struct Voice {
    osc1: Osc, osc2: Osc,             // 复用 synthesis anchor 的 polyBLEP Osc
    osc2_detune_cents: f32,
    filter: OnePoleLpf,               // 复用 synthesis anchor 的 OnePoleLpf
    amp_env: Adsr, filter_env: Adsr,
    filter_env_depth: f32, base_cutoff: f32,
    state: VoiceState,
    pending_trigger: Option<(u8, u8)>,  // fast release 完成后要触发的 note
    sample_rate: f32,
}

impl Voice {
    pub fn trigger(&mut self, note: u8, velocity: u8) {
        let freq = 440.0 * 2.0_f32.powf((note as f32 - 69.0) / 12.0);
        self.osc1.phase_inc = freq / self.sample_rate;
        self.osc2.phase_inc = freq * 2.0_f32.powf(self.osc2_detune_cents / 1200.0) / self.sample_rate;
        self.amp_env.note_on();
        self.filter_env.note_on();
        self.state = VoiceState::Playing;
    }

    /// voice stealing:5 ms 淡出后触发新 note(避免 click)
    pub fn fast_release_then_trigger(&mut self, note: u8, velocity: u8) {
        self.amp_env.fast_release();
        self.filter_env.fast_release();
        self.pending_trigger = Some((note, velocity));
        self.state = VoiceState::Transitioning;
    }

    pub fn release(&mut self) {
        self.amp_env.note_off();
        self.filter_env.note_off();
        self.state = VoiceState::Releasing;
    }

    pub fn process(&mut self) -> f32 {
        // Transitioning 期间检查 fast release 是否完成
        if self.state == VoiceState::Transitioning && self.amp_env.is_idle() {
            if let Some((note, vel)) = self.pending_trigger.take() { self.trigger(note, vel); }
        }
        if self.state == VoiceState::Idle { return 0.0; }
        // 振荡器 + filter env 调 cutoff + amp env(细节同 synthesis anchor)
        let o1 = self.osc1.process_saw();
        let o2 = self.osc2.process_saw();
        let osc_out = (o1 + o2) * 0.5;
        let f_env = self.filter_env.process();
        let cutoff = (self.base_cutoff + self.filter_env_depth * f_env).min(self.sample_rate * 0.45);
        self.filter.set_cutoff(cutoff, self.sample_rate);
        let filtered = self.filter.process(osc_out);
        let amp = self.amp_env.process();
        if self.amp_env.is_idle() && self.state != VoiceState::Transitioning {
            self.state = VoiceState::Idle;
        }
        filtered * amp
    }
}
```

**Synth**——voice pool + voice stealing + event dispatch:

```rust
use std::collections::HashMap;

pub struct Synth {
    pub voices: Vec<Voice>,
    pub note_to_voice: HashMap<u8, usize>,  // 当前按住的 note → voice 槽
    pub master_volume: f32,
    pub sample_rate: f32,
}

impl Synth {
    pub fn new(num_voices: usize, sr: f32) -> Self { /* 预分配 N 个 voice */ }

    pub fn dispatch(&mut self, ev: VoiceEvent) {
        match ev {
            VoiceEvent::NoteOn { note, velocity } => self.note_on(note, velocity),
            VoiceEvent::NoteOff { note } => self.note_off(note),
            VoiceEvent::SetCutoff { hz } => self.voices.iter_mut().for_each(|v| v.base_cutoff = hz),
            VoiceEvent::SetReverb { amount: _ } => { /* 见第 9 节 */ }
        }
    }

    fn note_on(&mut self, note: u8, velocity: u8) {
        if let Some(&idx) = self.note_to_voice.get(&note) { self.voices[idx].release(); }  // 同 note re-trigger
        // 1. 找空闲 voice
        if let Some(idx) = self.voices.iter().position(|v| v.state == VoiceState::Idle) {
            self.voices[idx].trigger(note, velocity);
            self.note_to_voice.insert(note, idx);
            return;
        }
        // 2. voice stealing:挑当前 amp_env level 最低的(最弱的)
        let idx = self.voices.iter().enumerate()
            .min_by(|(_, a), (_, b)| a.amp_env.level().partial_cmp(&b.amp_env.level()).unwrap())
            .map(|(i, _)| i).unwrap();
        self.voices[idx].fast_release_then_trigger(note, velocity);
        self.note_to_voice.insert(note, idx);
    }

    fn note_off(&mut self, note: u8) {
        if let Some(idx) = self.note_to_voice.remove(&note) { self.voices[idx].release(); }
    }

    pub fn render(&mut self, output: &mut [f32]) {
        for sample in output.iter_mut() {
            let mut sum = 0.0_f32;
            for v in &mut self.voices { sum += v.process(); }
            *sample = sum.tanh() * self.master_volume;  // 软限幅 + master volume
        }
    }
}
```

**main.rs**——cpal callback + 键盘 input thread + lock-free event ring。骨架:

```rust
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use crossbeam_queue::ArrayQueue;
use std::sync::Arc;

#[derive(Clone, Copy)]
pub enum VoiceEvent {
    NoteOn { note: u8, velocity: u8 }, NoteOff { note: u8 },
    SetCutoff { hz: f32 }, SetReverb { amount: f32 },
}

// 电脑键盘 → MIDI note:A S D F G H J K = C D E F G A B C;W E T Y U = 黑键
fn key_to_note(key: char) -> Option<u8> { /* 见 repo 完整代码 */ }

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let host = cpal::default_host();
    let device = host.default_output_device().ok_or("no output device")?;
    let config: cpal::StreamConfig = device.default_output_config()?.into();
    let sr = config.sample_rate.0 as f32;

    let synth = Arc::new(Synth::new(32, sr));  // 32-voice polyphony
    let event_queue: Arc<ArrayQueue<VoiceEvent>> = Arc::new(ArrayQueue::new(1024));

    // Audio thread:每次 callback 先 drain event queue,再 render
    let queue_audio = event_queue.clone();
    let stream = device.build_output_stream(
        &config,
        move |out: &mut [f32], _: &cpal::OutputCallbackInfo| {
            while let Some(ev) = queue_audio.pop() {
                // synth.dispatch(ev);  // 需要 &mut,见下方"共享难题"
            }
            // synth.render(out);  // 同上
        },
        |err| eprintln!("audio err: {err}"),
        None,
    )?;
    stream.play()?;

    // Input thread(主线程):读 stdin,push event
    println!("Play with A S D F G H J K. c=<hz> cutoff, r=<amt> reverb, q=quit");
    // ...读行、解析、push VoiceEvent 到 event_queue...
    Ok(())
}
```

**关于 `&mut Synth` 的共享难题**:`Arc<Synth>` 不能在 callback 里拿到 `&mut`,因为 Arc 是共享引用。生产代码几种解法:用 `Arc<parking_lot::Mutex<Synth>>`(parking_lot 无系统调用快路径,但 std Mutex 在 audio thread 是禁忌)、用 `Box::leak` 拿 `&'static mut`(unsafe)、或最常见的 `Arc<SpinLock<Synth>>`(自旋锁,audio thread 高优先级,spin 几纳秒不会 underrun)。`spinning_top::Spinlock` 是 Rust audio 社区的常见折中。深入学习见 [audio-pipeline-complete.md](audio-pipeline-complete.md) 第 8 节项目骨架。

跑:

```bash
cargo run --release
# 输入 "a" 回车 → C4 响;输入 "as" → C4 + D4 同时响(两 voice);输入 "c=500" → cutoff 调低
```

## 9 · master 效果总线:reverb 让它像一个空间

到这里你的 synth 能响了,但听起来"干"——所有声音像在消音室里发的。真实乐器在房间里,声音会反射、混响。这就是 **master reverb** 的工作。一个简单的 master reverb 立刻让整台 synth 听起来"专业"。

最便宜的可接受 reverb 是 **Schroeder reverb**(1962,4 个 comb 并联 + 2 个 allpass 串联),你在 [synthesis-and-instruments.md](synthesis-and-instruments.md) 第 10.3 节见过完整实现,直接复用。更真实的选择是 **convolution reverb**——用真实空间的 impulse response(IR)做卷积,这是 [convolution-reverb-hrtf.md](convolution-reverb-and-hrtf.md) 的主题。CPU 代价:Schroeder 轻,convolution 重(直接卷积 O(N²),partitioned FFT O(N log N))。游戏 audio 常见做法是 master bus 上挂一个短 IR(比如 200 ms "小房间"),CPU 可接受,空间感强。

把 reverb 接到 master bus 的关键设计:**send/return 模型**而不是 insert。每个 voice 不直接进 reverb,而是有一个 "send amount" 推到一条平行的 reverb bus,reverb bus 输出再和 dry 混合。这模拟了真实混音台——每条 channel 推一点到 reverb bus,主信号保持 dry:

```rust
pub struct MasterBus {
    dry_gain: f32,
    reverb: SchroederReverb,        // 或 ConvolutionReverb
    reverb_send: f32,               // 0-1,多少比例送进 reverb
}

impl MasterBus {
    pub fn process(&mut self, x: f32) -> f32 {
        let wet = self.reverb.process(x * self.reverb_send);
        x * self.dry_gain + wet
    }
}
```

master bus 上还可以挂 **compressor**(整体动态控制)、**limiter**(最后保险,防止 clip)、**EQ**(频段平衡,削去 30 Hz 以下 rumble)。这就是 [audio-effects.md](audio-effects.md) 学过的东西在 synth 上的实例化。一台 soft synth 的"成品感",**90% 来自 master bus**——同样的 voice,master bus 上有 reverb 和 limiter 的版本,听起来像唱片;没有的版本,听起来像 demo。

## 10 · 迷你 DAW:从乐器到工作站

合成器是一台乐器。**DAW(Digital Audio Workstation)** 是一座工作站——多台乐器、序列器、录音、混音。Ableton Live、Logic、FL Studio、Reaper 都是 DAW。把你的 synth 扩展成迷你 DAW,是理解的下一步。

DAW 比 synth 多三层:

**Sequencer(序列器)**。一段音乐由"什么时间触发什么 note"组成。Sequencer 存一个 **timeline**——一串 `(sample_index, event)` 对。Audio callback 跑的时候,检查 timeline 里下一个待触发的事件是不是该在当前 buffer 内触发,是就 dispatch。这是"程序化音乐"的核心——你写的不是实时输入,而是预编排的序列。

```rust
pub struct Sequencer {
    events: Vec<(u64, VoiceEvent)>,  // 按 sample_index 排序
    cursor: usize,
    current_sample: u64,
}

impl Sequencer {
    pub fn advance(&mut self, samples: u64, sink: &mut impl FnMut(VoiceEvent)) {
        let target = self.current_sample + samples;
        while self.cursor < self.events.len() && self.events[self.cursor].0 < target {
            sink(self.events[self.cursor].1);
            self.cursor += 1;
        }
        self.current_sample = target;
        if self.cursor >= self.events.len() { self.cursor = 0; self.current_sample = 0; }  // loop
    }
}
```

**多 instrument(多乐器实例)**。DAW 不只一台 synth——它有 N 个 "track",每个 track 一台 instrument。Audio callback 调用每个 instrument 的 render,把所有 track 的输出混合。这就是 [audio-pipeline-complete.md](audio-pipeline-complete.md) 第 4 节那个 mixer 的工作,只不过 voice 换成了 instrument。

**Recording(录音)**。把 audio callback 的最终输出同时写到磁盘(WAV)。这是反向 IO——audio callback 不能直接写文件,要把 sample 推到另一条 lock-free ring,由独立的 **writer thread** 消费并写盘。Writer thread 是普通线程,可以 alloc、可以 syscall,不影响 audio thread。

这三个扩展把"乐器"变成"音乐工作站"。Handmade Hero 没走这一步——Casey 的目标是游戏,不是 DAW。但**理解 DAW 的架构,是理解游戏 audio middleware(FMOD、Wwise)的关键**——FMOD 的 Event 系统、Wwise 的 Interactive Music Hierarchy,本质上都是序列器 + 多 instrument + 录音的变体。游戏里"动态 BGM"(玩家战斗时切入战斗主题、解谜时切入安静主题)就是 sequencer 在实时切换 timeline。

## 11 · 在你 HH 项目里动手(做中学红线)

这是 T2 序列最后一个练习,**也是最大、最综合的一个**——给你一台真正能在自己电脑上弹奏的多音色软合成器。建议 8-15 小时分多次完成。

**目标**:Rust + cpal 项目,电脑键盘当琴键,实时多音色发声,master bus 有 reverb。弹起来延迟低、和弦饱满、空间自然。

**步骤 1(地基)**:把 [audio-pipeline-complete.md](audio-pipeline-complete.md) 第 2.2 节那个 sine callback 跑起来,确认 ALSA/PipeWire 工作。`pw-top` 看 Latency。

**步骤 2(振荡器)**:把 `phase.sin()` 换成本篇第 8 节的 `Osc::process_saw()`。听出锯齿("亮、rich")和正弦("空洞")的区别——这是 [synthesis-and-instruments.md](synthesis-and-instruments.md) 第 2 节的核心听感训练。

**步骤 3(滤波器 + envelope)**:静态发 A4,过 OnePoleLpf,cutoff 由 ADSR 循环调制。听见"嗡——亮起来——暗下去——"。听出 filter envelope 对音色的影响。

**步骤 4(message ring)**:实现第 3 节的 `ArrayQueue<VoiceEvent>`,主线程读键盘 push,audio callback drain。按 `a` 触发 note_on(C4)。**这是真正的工程**——两线程无锁通信,audio thread 永不阻塞。如果你用了 `Mutex`,改成 `ArrayQueue`,看 underrun 是否消失。

**步骤 5(单 voice + ADSR)**:一个 Voice,note_on/off 走 ADSR。按下响,松开淡出。听出 attack/release 时间的不同感觉。

**步骤 6(voice pool + 多音)**:实现第 8 节的 Synth 结构,32 voice。同时按多键,`pw-top` 看 CPU 不暴涨,不 underrun。

**步骤 7(voice stealing)**:按 33 个键(超过 voice pool),确认 fast release 工作——**没有 click 杂音**。这一步的成败是工程功力的证明。

**步骤 8(master reverb)**:实现第 9 节的 SchroederReverb(或从 [synthesis-and-instruments.md](synthesis-and-instruments.md) 第 10.3 节 copy),接 send/return。开启后声音立刻有"在房间里"的感觉。

**步骤 9(可选,加分):convolution reverb**。从 [convolution-reverb-hrtf.md](convolution-reverb-and-hrtf.md) 的方法实现 partitioned FFT convolution,接 master bus。对比 Schroeder("通用")和 convolution("具体空间",教堂/小木屋/录音棚各异)的听感和 CPU。

**步骤 10(可选,DAW 扩展)**:实现第 10 节的 Sequencer,存一段简单旋律 loop 播放。加 recording,把 audio 输出写到 WAV(`hound` crate)。你现在有了一台迷你 DAW。

**完成标志**:能弹一首简单曲子(《小星星》),听感流畅、无杂音、有 reverb 空间感,延迟低到不察觉。**录音导出一个 WAV,放给朋友听,他们不觉得是"代码生成的"**——这是 T2 序列的毕业证书。

## 12 · 练习

**Lv1 · 单音色减法 synth**。完成步骤 1-5。一台 monophonic 减法合成器,一个键,ADSR + filter envelope。**通过标准**:能听见 attack、sustain、release 的形状,能调 cutoff 改亮度。

**Lv2 · 多音色 + voice stealing**。完成步骤 6-7。32 voice polyphony,voice stealing 无 click。**通过标准**:同时按 10 键不卡,按 33 键无杂音。**测量**:`pw-top` 在 32 voice 全 active 时 CPU 占用 < 5%。

**Lv3 · 加 master reverb 和 soft clip limiter**。完成步骤 8 + master bus 上加一个 limiter(防止和弦过响 clip)。**通过标准**:reverb send 在 0.3 时有清晰空间感;limiter 在和弦全满时不 clip。

**Lv4 · 迷你 DAW / 物理建模扩展**。两个二选一:
- **路线 A(工程)**:完成步骤 9-10。Convolution reverb + sequencer + 录音。导出 30 秒 WAV。
- **路线 B(声音)**:在 voice 里**额外加一个 Karplus-Strong 弦合成 voice 类型**(从 [physical-modeling-synthesis.md](physical-modeling-synthesis.md) 复用代码),让它和 saw voice 共存于同一个 voice pool。按某个键(比如 `z`)触发 string voice,其它键触发 saw voice。**通过标准**:两种音色自然共存,string voice 听起来像吉他拨弦。

## 13 · T2 音频深度序列收口

走完这一篇,你完成了 T2 音频深度序列的全部内容。沿你走过的路径**回望一遍**,看这条弧线的形状。

**起点:信号**。在 [phase-0/22-signals-foundation.md](../../phase-0/22-signals-foundation.md) 你把声音变成了一串数——Nyquist 采样、量化。这是音频工程的**本体论**:sample 是一个 f32,一切后续讨论都建立在这上面。

**DSP 基础**。在 [dsp-fundamentals.md](dsp-fundamentals.md) 你写了第一个 biquad,学了 z 变换、频率响应、相位。你理解了"滤波器是一组系数,信号流过系数被塑形"——reverb、EQ、envelope follower 本质上都是某种滤波。

**频域**。在 [fft-and-spectral-analysis.md](fft-and-spectral-analysis.md) 你把时域拖进频域,看见声音的"另一种形状"——频谱。这给了你**两种视角**:时域看波形,频域看谐波。polyBLEP 抗 aliasing 是频域视角的胜利——你在频域看见 alias 的谐波折叠,在时域加修正项消除它。

**合成**。在 [synthesis-and-instruments.md](synthesis-and-instruments.md) 你学了**生成**声音——振荡器、ADSR、FM、Karplus-Strong、wavetable。理解了"声音不必来自录音,可以是数学函数实时生成的"。这是从"播放"到"创造"的跃迁。

**效果**。在 [audio-effects.md](audio-effects.md) 你学了**塑造**声音——reverb、delay、compressor、distortion。理解了"干声经过一串效果,变成有空间、有动态、有色彩的成品"。

**物理建模**。在 [physical-modeling-synthesis.md](physical-modeling-synthesis.md) 你学了**模拟**声音——微分方程描述乐器物理,数值积分得到声音。Karplus-Strong 的延迟线、waveguide 的双向传播。声音可以来自物理,不必是 oscillator。

**空间音频与编解码**。在 [convolution-reverb-hrtf.md](convolution-reverb-and-hrtf.md) 学了 HRTF 与卷积,理解"声音从哪里来"。在 [audio-codecs-formats.md](audio-codecs-and-formats.md) 学了 MP3、Opus,理解"声音怎么压缩存储"。在 [adaptive-audio-and-3d.md](../../phase-7/deep-dives/adaptive-audio-and-3d.md) 学了游戏音频 middleware,理解"声音怎么响应玩家"。

**音频流水线**。在 [audio-pipeline-complete.md](audio-pipeline-complete.md) 学了**音频在系统里怎么流**——cpal callback、lock-free ring、SIMD mixer。音频工程不只是 DSP,还是系统编程。

**Capstone(这一篇)**。你把上述一切**组装成一台乐器**。从 sample 到 instrument,每一层都是你写的。

这条弧线正是 **CCRMA 320A/B/C** 的形状——Stanford 计算机音乐系列三个学期:**320A 信号与系统**(dsp + fft)、**320B 音频处理与合成**(synthesis + effects + physical modeling)、**320C 音频软件工程**(pipeline + 这一篇 capstone)。你用 Rust + cpal 走完了它,CCRMA 用 C++ + JUCE 走。**工具不同,工程思维一致**。

你现在**理解了音频工程从 sample 到 instrument 的完整链路**。这不是"我会用 FMOD"——这是"我理解 FMOD 内部在做什么"。当你以后用任何 audio middleware,都能透视它的内部:voice pool(你知道 voice stealing 怎么工作)、mixer(你知道 SIMD 怎么加速)、reverb(你知道 Schroeder 和 convolution 的区别)、codec(你知道 Opus 为什么比 MP3 好)。这种**透视能力**是 T2 序列给你的最大礼物。

**这不是终点**。T2 之后还有更深的领域:**DSP 算法的硬件实现**(FPGA、DSP 芯片)、**机器学习合成**(Meta AudioCraft、Google MusicLM,用 transformer 直接生成音频波形)、**空间音频研究前沿**(Ambisonics 高阶、个人化 HRTF 测量)、**音乐信息检索**(自动转录、节拍检测、和弦识别)。这些是研究生的课题,你已有了读懂它们的基础。如果对其中任何一个感兴趣,**T2 是你的入场券**。

最后一句:HH 的 Casey 没走完整条 T2,因为他的目标是游戏不是合成器。但**他做 HH 的精神——从零写、不抄、理解每一行——和 T2 完全一致**。你写的这台软合成器,从 polyBLEP 的多项式到 voice stealing 的策略,每一行都是你**理解的、能解释的、能改的**代码。这是 handmade 精神在音频上的实践。下一阶段你会把这种精神带到 GPU、光栅化、延迟渲染——另一条弧线,但工程思维完全一样。

## 14 · 延伸阅读

本仓库本地资料(按学习顺序):
- [phase-0/22-signals-foundation.md](../../phase-0/22-signals-foundation.md) — T2 起点:信号与系统基础
- [phase-5/deep-dives/dsp-fundamentals.md](dsp-fundamentals.md) — DSP 基础:biquad、z 变换
- [phase-5/deep-dives/fft-and-spectral-analysis.md](fft-and-spectral-analysis.md) — FFT 与频域分析
- [phase-5/deep-dives/synthesis-and-instruments.md](synthesis-and-instruments.md) — 声音合成与乐器(polyBLEP、ADSR、FM、Karplus-Strong)
- [phase-5/deep-dives/audio-effects.md](audio-effects.md) — 音频效果(reverb、compressor、delay)
- [phase-5/deep-dives/physical-modeling-synthesis.md](physical-modeling-synthesis.md) — 物理建模合成
- [phase-5/deep-dives/convolution-reverb-hrtf.md](convolution-reverb-and-hrtf.md) — 卷积 reverb 与 HRTF(空间音频)
- [phase-5/deep-dives/audio-codecs-formats.md](audio-codecs-and-formats.md) — 音频编解码(MP3、Opus、Vorbis)
- [phase-5/deep-dives/adaptive-audio-and-3d.md](../../phase-7/deep-dives/adaptive-audio-and-3d.md) — 自适应音频中间件
- [phase-5/deep-dives/audio-pipeline-complete.md](audio-pipeline-complete.md) — 音频流水线全解(cpal、ring buffer、SIMD)
- [phase-4/deep-dives/lock-free-programming.md](../../phase-4/deep-dives/lock-free-programming.md) — 无锁编程(message ring 的底)
- [phase-4/deep-dives/threading-models.md](../../phase-4/deep-dives/threading-models.md) — 线程模型(audio thread 是其中一种实时岛)
- [phase-4/deep-dives/profiling-with-tracy.md](../../phase-4/deep-dives/profiling-with-tracy.md) — 性能分析(测 callback 抖动)
- [phase-9/09B-1-game-loop-and-timestep.md](../../phase-9/09B-1-game-loop-and-timestep.md) — 09B 游戏循环与时间步(audio thread 是另一种"实时岛"模型)

外部稳定 URL:
- CCRMA 课程列表(Stanford 计算机音乐中心,320A/B/C 的源头):https://ccrma.stanford.edu/courses
- Pirkle "Designing Software Synthesizer Plug-Ins in C++"(with JUCE,工业级 synth 实现教科书):https://www.routledge.com/Designing-Software-Synthesizer-Plug-Ins-in-C-with-Audio-DSP/Pirkle/p/book/9781138583931
- The Audio Programming Book(Boulanger & Lazzarini,经典教科书):https://mitpress.mit.edu/9780262680820/the-audio-programming-book/
- Curtis Roads "The Computer Music Tutorial"(1996 圣经级):https://mitpress.mit.edu/9780262680820/the-computer-music-tutorial/
- Zölzer "DAFX: Digital Audio Effects"(效果算法权威):https://www.wiley.com/en-us/DAFX%3A+Digital+Audio+Effects%2C+2nd+Edition-p-9780470665992
- Smith "Physical Audio Signal Processing"(在线免费,waveguide 圣经):https://ccrma.stanford.edu/~jos/pasp/
- JUCE 框架文档(工业级 synth 开发框架,C++,参考架构):https://docs.juce.com/
- cpal 文档(Rust 跨平台 audio):https://docs.rs/cpal/
- crossbeam-queue 文档(ArrayQueue / SegQueue):https://docs.rs/crossbeam-queue/
- Sound on Sound "Synth Secrets" 系列(Gordon Reid,63 篇经典):https://www.soundonsound.com/series/synth-secrets

真实开源源码(强烈推荐读):
- Vital(Matt Tytel,开源 wavetable synth,C++,大型工业参考):https://github.com/mtytel/vital
- Helm(Matt Tytel 较早的 subtractive synth,代码更易读):https://github.com/mtytel/helm
- Surge(开源 hybrid synth,polyphonic + voice stealing 实现参考):https://github.com/surge-synthesizer/surge
- fundsp(Rust 函数式 DSP 框架,节点连接式架构):https://github.com/SamiPerttu/fundsp
- oxc-synth(Rust synth 参考):https://github.com/oxc/oxc-synth
- Cardinal(开源 Reaktor-like modular):https://github.com/DISTRHO/Cardinal

历史演化的完整时间线见 [synthesis-and-instruments.md](synthesis-and-instruments.md) 第 14 节。软件工程视角的关键节点:**1967 Max Mathews MUSIC V**(第一个软件 synth)→ **1996 Steinberg VST**(synth 从硬件搬到 PC)→ **2014 Serum**(polyBLEP + spectral morphing 行业标准)→ **2020 Vital**(免费开源 wavetable,democratizing)→ **2020s Neural synthesis**(RAVE、AudioCraft,ML 直接生成音色)。
