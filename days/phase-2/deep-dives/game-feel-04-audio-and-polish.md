
# 深入:游戏手感序列(四)—— 音频手感与综合打磨

> 你写完了 part 3 的 juice 系统。屏幕会震、命中会 hitstop、粒子会喷、屏幕会闪白——你已经把 [game-feel-short](./game-feel-short.md) 里那 4 种 juice 跑通了。然后你打开游戏玩了一局。**奇怪,还是不够"爽"**。哪里出了问题?
>
> 你做的第一件事应该是:**把游戏静音,再玩一遍**。
>
> 同样的画面、同样的 shake、同样的 hitstop、同样的粒子——但这一次,**什么都没有感觉**。剑挥出去没有 whoosh、跳起来没有落地声、击中没有 crunch、爆击没有低频 punch。屏幕在震,可你的身体没反应。你的 juice 系统还在跑,但它的威力凭空蒸发了 70%。
>
> 这就是 part 4 要讲的事:**音频是游戏手感的另一半,而综合打磨(the polish pass)是把前三个 part 缝合成一个整体的那道工序**。这一篇是游戏手感序列的最后一篇,讲完它,你手里就有了一整套从输入(part 1)、相机(part 2)、视觉反馈(part 3)、音频与综合打磨(part 4)的工程化手感工具链。

## 0 · 把游戏静音,你就懂了

Swinx 在《Game Feel》里有一句话被反复引用:**音频不是游戏手感的"装饰",它是游戏手感的"另一半"**。这不是夸张。任何做过 A/B 测试的人都会告诉你:同一个动画、同一个粒子系统,有音频和无音频的体感差距,远大于"粒子从 20 个加到 50 个"。

原因在大脑,不在代码。视觉系统告诉我们"有东西发生了",但**听觉系统告诉我们"这件事有多重、有多近、有多真"**。一个无声的拳头打在木板上,大脑会怀疑它是不是真的打中了;同一个拳头配上一个 200 Hz 的低频 crunch + 一声木裂,大脑立刻接受"这是一记重击"。这是 multimodal perception(多模态感知)的基本事实:大脑**交叉验证**视觉和听觉,**任何一方缺失,另一方的可信度都会下降**。

所以 part 4 的工程目标只有一句话:**每一个视觉反馈事件,都必须有一个音频伙伴**。剑挥过去 = whoosh;剑砍中 = crunch + shake + particles + hitstop(四个 part 一起触发);敌人死亡 = death cry + death animation + death particle burst;UI 按钮按下 = click + scale pulse。没有例外的"无声动作"。

这一篇把这条规则拆成五件事讲透:**音频作为反馈**(the multiplier)、**变奏**(the anti-repetition rule)、**自适应音乐**(macro feel)、**空间音频作为信息**(spatial audio for feel)、**综合打磨**(the holistic polish pass)。最后是游戏手感序列的四篇收口反思,以及一组在你 HH 项目里立刻能做的"做中学"红线任务。

## 1 · 音频作为反馈:那个看不见的乘数

回到 part 3 的 `JuiceSystem::trigger_hit`。你给它加了 shake、hitstop、particles、flash 四种视觉 juice。现在我们再给它加一个维度:**一个 hit sound**。

```rust
impl JuiceSystem {
    pub fn trigger_hit(&mut self, x: f32, y: f32, severity: f32, audio: &mut AudioEngine) {
        // 视觉 juice(part 3)
        self.add_shake(0.4 * severity);
        self.add_hitstop(Duration::from_millis((60.0 * severity) as u64));
        self.spawn_blood_particles(x, y, 20 + (40.0 * severity) as usize);
        self.flash_alpha = (0.7 * severity).min(1.0);

        // 音频 juice(part 4,这是关键的新增)
        audio.play_one_shot(OneShot {
            buffer: self.hit_sound_for(severity),
            pitch: 1.0 - 0.05 * severity,      // 越重越低沉
            volume: 0.6 + 0.4 * severity,
            position: Some(Vec3::new(x, y, 0.0)), // 空间化(见 §4)
            lowpass_cutoff: 8000.0 - 6000.0 * severity, // 越重越闷
        });
    }

    fn hit_sound_for(&self, severity: f32) -> &SoundBuffer {
        // 轻击用 punch,重击用 crunch(变奏 bank,见 §2)
        if severity < 0.5 { &self.bank.light_hit } else { &self.bank.heavy_hit }
    }
}
```

**唯一一行新代码**——`audio.play_one_shot`——把 part 3 的 juice 从"看起来很重"变成"身体感觉很重"。这就是为什么 Nijman 在 [The Art of Screenshake](https://www.youtube.com/results?search_query=art+of+screenshake) 演讲里反复强调"**有 sound 的 juice 比没 sound 的 juice 强 10 倍**":没有 sound 的 hitstop 玩家用"理性"接受("哦,游戏停了一下"),有 80 Hz kick drum 的 hitstop 玩家用"身体"接受("啊,我打中了")。

这件事的心理物理学背景值得讲清楚。人对"冲击"事件的感知是多模态的:**视觉告诉你方向和形状,听觉告诉你能量和质量**。一个无声的撞击,大脑会**下意识降低它的重要性评级**——因为它"听起来不像是真的打中了"。这就是为什么你 part 3 写完 juice 还是觉得"不够爽":你的大脑一直在等那个本该出现的"砰",但它没来。

更微妙的一点:**音频还能补偿视觉的延迟**。视觉系统的处理延迟大约 50-100ms,听觉只有 20-40ms。当一个 hit 发生时,玩家先听到 crunch(快),才看到粒子(慢)。**音频在视觉到达前就锁定了"事件已发生"这个判断**——这就是为什么配上 sound 的 hitstop 感觉"瞬间即沉",而不配 sound 的 hitstop 感觉"卡了一下"。

落地原则:**每一个 part 3 触发的视觉事件,都要在 part 4 触发对应的音频事件**。把它们绑成一对,放进同一个函数(`trigger_hit` / `trigger_jump` / `trigger_pickup`),永远不要让其中一方单独出现。下面是一个最小的反馈绑定表(在心里记,不写文件):

- 受伤 = shake + particles + flash + **crunch sound**(低频,severity 越大 cutoff 越低)
- 跳跃 = squash + camera bob + **whoosh sound**(高频短促上扬)
- 落地 = stretch + dust particles + camera dip + **thud sound**(中低频,落地速度越快越响)
- 拾取 = scale pulse + sparkle particles + **chime sound**(高频,音高随物品稀有度上升)
- UI 悬停 = cursor scale + **tick sound**(极轻,几乎潜意识)
- UI 确认 = button scale + **click sound**(干脆)
- 击杀敌人 = death animation + blood burst + slowmo + **death cry + impact**(复合,长尾)

这张清单的本质是:**动作 → 多通道反馈**。每一个动作至少 1 个视觉 + 1 个音频,关键动作 4-7 个反馈通道。这是 part 3 已经立的原则,part 4 把"音频通道"这条补齐。

## 2 · 变奏:那条把"业余"和"专业"分开的线

现在你的 hit 已经有 sound 了。你打第 1 个敌人,crunch 响起,爽。打第 2 个,crunch,爽。打第 10 个,crunch——**你已经听不见了**。打第 50 个,crunch——**你开始烦了**。

这是音频手感里最容易被新手忽略、又被老手视为底线的一条规则:**重复的声音会被大脑过滤,然后变成噪音**。大脑是高效的重复检测器:同一个刺激出现 3-5 次,它就把它归类为"背景",不再分配注意力。这就是为什么业余游戏的脚步声、刀剑声、枪声听了 10 分钟就累——它们从头到尾是**同一个样本**。

专业游戏的做法叫 **variation**(变奏)。规则极简:**任何会被触发的声音,每一次播放都要和上一次不一样**。实现起来有四把刀,你都应该装上:

**第一把:随机 pitch**。最简单也最有效。每次播放时,pitch 在 ±5% 范围内随机偏移。±5% 是黄金区间:小到不破坏"这是同一个声音"的认知,大到大脑检测不到完全重复。超过 ±8% 会让人听出"调变了",低于 ±3% 又起不到变奏作用。

```rust
pub struct OneShot {
    pub buffer: SoundBuffer,
    pub base_pitch: f32,
    pub pitch_jitter: f32,   // 0.05 = ±5%
    pub volume_jitter: f32,  // 0.1 = ±10%
    // ...
}

impl OneShot {
    pub fn sample_pitch(&self, rng: &mut impl Rng) -> f32 {
        let jitter = (rng.gen::<f32>() * 2.0 - 1.0) * self.pitch_jitter;
        self.base_pitch * (1.0 + jitter)
    }

    pub fn sample_volume(&self, rng: &mut impl Rng) -> f32 {
        let jitter = (rng.gen::<f32>() * 2.0 - 1.0) * self.volume_jitter;
        self.base_volume * (1.0 + jitter).max(0.0)
    }
}
```

**第二把:随机 volume**。±10% 的音量抖动,搭配 pitch jitter,让"完全相同"变成"统计相似"。注意 volume jitter 不要太大(>20%),否则同一动作听起来一会儿响一会儿弱,玩家会觉得"hit detection 有问题"。

**第三把:小变奏 bank**。同一种事件准备 3-5 个**略有不同**的录音(或同一录音的不同 EQ 处理)。每次播放随机选一个。这是最贵也最有效的变奏——因为样本本身就是不同的波形,pitch/volume jitter 叠加上去,几乎不可能出现两次完全相同的播放。3 个变奏足够,5 个就奢侈了。Hades、Celeste 的脚步声都用 3-5 个变奏的 bank。

```rust
pub struct SoundBank {
    pub variants: Vec<SoundBuffer>,
    pub last_index: usize,
}

impl SoundBank {
    pub fn pick(&mut self, rng: &mut impl Rng) -> &SoundBuffer {
        // 避免"立即重复同一个"——这是变奏 bank 的小技巧
        let mut idx;
        loop {
            idx = rng.gen_range(0..self.variants.len());
            if self.variants.len() == 1 || idx != self.last_index { break; }
        }
        self.last_index = idx;
        &self.variants[idx]
    }
}
```

**第四把:循环声的随机起点**。脚步声、引擎声、心跳声这类需要 loop 的声音,**不要每次都从 sample 0 开始播**。否则前几个 sample 的 transient 永远是同一个,大脑立刻识别"它在循环"。每次进入 loop 时随机跳到一个非零起点(或者干脆从 1/4 周期、3/4 周期这些位置开始)。

```rust
impl LoopSound {
    pub fn start_at_random(&mut self, rng: &mut impl Rng) {
        let total = self.buffer.len();
        self.play_pos = rng.gen_range(total / 4..total * 3 / 4);
    }
}
```

**这一条单独的纪律,就能把音频从"stock"提升到"alive"**。我把它叫做反重复律(the anti-repetition rule)。它是区分"声音设计师做的游戏"和"程序员随便贴了几个 wav 的游戏"最清晰的分界线。前者的脚步声你听 8 小时都不烦,后者的脚步声你 10 分钟就想关音量。

落地到 HH 项目:把 part 3 里所有 `play_one_shot(buffer)` 改成 `play_one_shot_from_bank(bank, rng)`。给每一种事件准备 3 个变奏(可以是同一录音的 EQ 变体),叠 ±5% pitch jitter 和 ±10% volume jitter。**这一项改动可能比你 part 3 加的所有粒子加起来都更值钱**。

## 3 · 自适应音乐:宏观尺度的手感

到目前为止我们都在讲"事件级"的音频反馈——一次 hit、一次 jump、一次 pickup。但游戏手感还有一个**宏观尺度**:情绪节奏(emotional pacing)。

想象玩家在 HH 项目里进入 boss 房间。如果 BGM 还是之前 explore 时的轻柔钢琴 loop,**整个 boss 战的紧张感就泄掉了**——视觉上 boss 在咆哮、粒子在炸、屏幕在震,可音乐还在跟你轻声细语。玩家身体的肾上腺素上不来。反过来,玩家在森林里散步,BGM 是 boss 战的狂暴交响乐,**玩家的探索节奏就被打乱了**——他无法放松地找路。

这就是 adaptive music(自适应音乐)解决的问题:**让音乐跟着游戏状态变,而不是无视游戏状态**。这一节我们直接对接 [adaptive-audio-and-3d.md](../../phase-7/deep-dives/adaptive-audio-and-3d.md) 那一篇的完整理论(水平重排、垂直重组、ELIS 模型),这里只讲**它和游戏手感的关系**。

Adaptive music 是**游戏节奏(player state)和音乐节奏(music energy)的同步**。它本质上是一种"长时间尺度的 juice"——part 3 的 hitstop 是 60ms 的体感冲击,adaptive music 是 60 秒的情绪铺陈。两者用的是同一套原理:**让游戏的输出通道(视觉/音频/触觉)和玩家当前的状态相匹配**。

落地到 HH 项目,你只需要做最简单的 vertical layering(垂直重组):

```rust
pub struct MusicDirector {
    pub intensity: SmoothedParam,  // 0 = calm, 1 = combat
    pub layers: Vec<MusicLayer>,   // melody / harmony / bass / drums
}

impl MusicDirector {
    pub fn on_game_state(&mut self, state: &GameState) {
        // 把游戏状态映射到音乐强度
        let target = match state {
            GameState::Combat(n) if *n > 0  => 1.0,
            GameState::NearEnemy            => 0.5,
            GameState::LowHealth            => 0.7,  // 低血量单独加紧张
            GameState::Exploration          => 0.0,
            GameState::Victory              => 0.0,  // 胜利时换段,这里简化
        };
        self.intensity.set_target(target, smoothing_2s);
    }

    pub fn render(&mut self, output: &mut [f32]) {
        let intensity = self.intensity.tick();
        // 每个 layer 有一个"出现阈值"
        // drums 只在 intensity > 0.6 才显著
        // bass 在 intensity > 0.3 才显著
        // melody / harmony 始终在,但 combat 时 melody 让位给 drums
        for layer in &mut self.layers {
            let target_gain = self.gain_for_layer(layer.role, intensity);
            layer.target_gain = target_gain;
            layer.render_into(output);
        }
    }

    fn gain_for_layer(&self, role: LayerRole, intensity: f32) -> f32 {
        use LayerRole::*;
        match role {
            Melody  => (1.0 - intensity * 0.5).max(0.3), // combat 时让位
            Harmony => 0.7,
            Bass    => (intensity * 1.2).min(1.0),       // combat 时加厚
            Drums   => ((intensity - 0.4) * 2.5).clamp(0.0, 1.0),
        }
    }
}
```

关键点:**`intensity` 是 smoothed 的,任何变化都在 1-2 秒内过渡,绝不让音乐"啪"地切换**。这个 smoothing 是 part 2 相机 damping 在音频领域的同构——把"突变"变成"流畅过渡"。同样的工程思路,不同的输出通道。

**这件事为什么和"游戏手感"有关,而不是单纯的"音乐设计"?** 因为 adaptive music 改变的是**玩家的生理状态**——快节奏、低音、高密度的音乐会拉高心率、压紧呼吸,玩家在 boss 战时会真的更紧张、反应更快、犯错更频繁。慢节奏音乐会反过来。所以 adaptive music 不是"让音乐更好听",是**通过音乐调控玩家的体感节奏**——这是宏观尺度的 game feel。Swinx 把它叫做 "the game's emotional pace matching the player's state"。

深入做下去你会遇到 bar-aligned transition(等小节切换)、stinger(过渡音效)、ELIS(实时生成 bridge)等等复杂工艺。这些都超出了 part 4 的范围,完整理论见 [adaptive-audio-and-3d.md](../../phase-7/deep-dives/adaptive-audio-and-3d.md)。part 4 只要求你做到一件事:**BGM 不再是无视游戏状态的死循环**。

## 4 · 空间音频作为信息:不仅是氛围

[game-feel-short](./game-feel-short.md) 里讲的都是发生在屏幕上的事件。但很多游戏手感来源**不在屏幕上**——敌人在你身后、宝箱在你右边、爆炸在你左后方。这些信息,**视觉帮不了你**(你看不到屏幕外),只有**音频**能告诉你。

这就是 spatial audio(空间音频)的第二种用法:不是氛围(让声音"听起来在那个房间"),而是**信息**(告诉玩家"那个东西在你哪个方向")。这一节我们对接 [adaptive-audio-and-3d.md](../../phase-7/deep-dives/adaptive-audio-and-3d.md) 里的 HRTF、panning law、距离衰减、occlusion,但只关心一件事:**空间音频怎么把游戏手感从"屏幕内"扩展到"360 度"**。

举个具体场景。你的 HH 是俯视角动作游戏,但 enemy 会从任何方向扑过来。屏幕只能显示前方一窄条视野。**如果 enemy 从屏幕外接近你,玩家唯一的预警就是音频**——脚步声从右后方渐渐变响。一个有 spatial audio 的游戏,玩家会在 enemy 进入视野前 0.5 秒就转头;一个没有 spatial audio 的游戏,玩家会被"突然出现在屏幕边缘的 enemy"惊吓,反应慢半拍,体验明显劣化。

实现上,这件事的关键不在于 HRTF 用得多精确(那是 [adaptive-audio-and-3d.md](../../phase-7/deep-dives/adaptive-audio-and-3d.md) §3 的工程话题),而在于**你愿不愿意把每一条"会移动的 source"放进 spatializer**。最低限度也要做立体声 pan + 距离衰减:

```rust
pub fn render_spatial_source(
    source: &SoundBuffer,
    src_pos: Vec3,
    listener_pos: Vec3,
    listener_facing: Vec3,
    output_l: &mut [f32], output_r: &mut [f32],
) {
    let delta = src_pos - listener_pos;
    let dist = delta.length();
    let dir = delta.normalize();

    // 距离衰减(part 4 简化版,完整见 adaptive-audio-and-3d §3.5)
    let atten = (1.0 / (1.0 + dist * 0.1)).min(1.0);

    // 立体声 pan:把 listener 朝向投影到 source 方向
    // 用 constant-power pan law(adaptive-audio-and-3d §3.1)
    let pan = dir.dot(&listener_facing_right(listener_facing)); // -1 = 左, 0 = 前, +1 = 右
    let angle = std::f32::consts::FRAC_PI_4 * (pan.clamp(-1.0, 1.0) + 1.0);
    let g_l = angle.cos();
    let g_r = angle.sin();

    for (i, &s) in source.samples().iter().enumerate() {
        let attenuated = s * atten;
        output_l[i] += attenuated * g_l;
        output_r[i] += attenuated * g_r;
    }
}
```

这一段代码的效果:**玩家戴上耳机,enemy 从右边跑过来,脚步声真的从右耳进**。仅此一项,game feel 就会从"屏幕内的游戏"变成"围绕你的世界"。如果你的 HH 用了 headphone playback,再进一步上 HRTF(见 [adaptive-audio-and-3d.md](../../phase-7/deep-dives/adaptive-audio-and-3d.md) §3.3 的 128-tap FIR 实现),效果会从"右边"变成"右后方 2 米"——玩家能闭着眼睛指出 enemy 在哪。

空间音频作为信息,还有一个常被忽略的子方向:**reverb 作为空间地图**。在大教堂里 footstep 有 3 秒尾响,在小屋里 footstep 几乎没尾响。玩家**通过 reverb 长度无意识地判断房间大小**——这是一种几乎免费的"游戏感"。在 [audio-effects.md](../../phase-5/deep-dives/audio-effects.md) 的 convolution reverb 章节里有完整实现,这里只提醒:**给每个 room 一个 reverb preset,player 进入时 swap**——一行代码,效果惊人。

把这一节总结成一条工程命令:**任何不在屏幕正中央的 source,都必须经过 spatializer**。Footstep、gunshot、ambient drone、voice chat——无一例外。这是把 game feel 从 2D 屏幕扩展到 3D 空间的关键。

## 5 · 综合打磨:那个"最后 10% 占 50% 时间"的工序

到这里,你已经有了 part 1(input)、part 2(camera)、part 3(visual feedback)、part 4(audio feedback + adaptive music + spatial audio)。**四个 part 的零件都齐了**。但你的游戏可能还是不够好。为什么?

因为**零件齐全不等于产品成熟**。零件之间有缝隙:某个动作的 juice 强度比另一个高 30%,某个相机过渡没有 damping,某段 BGM 的 layer 切换比预期慢 200ms,某个 enemy 的 footstep 还在用同一个样本(没有变奏),某个 UI 按钮没有 click sound。这些"缝隙"单独看每一个都很小,**叠在一起就是业余和专业的差距**。

**Polish pass(综合打磨)**就是去把所有这些缝隙填上的工序。它不是新功能,不是新系统——它是**用一套统一的标准走查整个游戏**,确保每一个动作、每一个过渡、每一个重复的声音、每一个相机时刻都符合手感序列四篇定下的所有规则。

Polish pass 的标准走查清单(在心里默念,不写文件):

- **每个动作都有反馈吗?**(part 3 + part 4 §1)—— 走、跑、跳、攻击、受击、死亡、拾取、对话、开门、装备、卸下。每一个动作,你能在代码里找到它对应的 `trigger_xxx(audio)` 调用吗?找不到?那就是个无声动作,补上。
- **每个反馈都有变奏吗?**(part 4 §2)—— grep 一下你的 `play_one_shot` 调用,有几个是直接传 `buffer`,有几个是传 `bank`?直接传 `buffer` 的,改成 `bank`。
- **每个过渡都有 easing 吗?**(part 2 + part 3)—— 血条减少是线性还是指数衰减?相机切换是瞬切还是 lerp?UI 元素出场是 instant 还是 spring?
- **每个重复声音都有 jitter 吗?**(part 4 §2)—— 你的 hit sound 每次 pitch 都一样吗?加上 ±5%。
- **每个相机时刻都有 damping 吗?**(part 2)—— 相机跟随是 `pos = target` 还是 `pos = exp_decay(pos, target, ...)`?几乎永远应该是后者。
- **音乐自适应了吗?**(part 4 §3)—— 进入 combat 音乐变了吗?低血量音乐变了吗?
- **空间音频用了吗?**(part 4 §4)—— enemy 在你身后能听出来吗?
- **每个 part 3 的 juice 都可关闭吗?**(accessibility)—— shake / flash / particles 有 accessibility 开关吗?

把这张清单变成一个 checklist,然后**系统地走一遍整个游戏**。这是 polish pass。

这里要讲清楚一个工业界的事实,因为这个事实是新游戏开发者最难接受的一条:**polish 不是免费的,它是项目预算里最被低估的一项,资深制作人都心知肚明地给它留 30-50% 的时间**。

原因有两个。第一,**polish 没有可见的产出**。你花两周把每个 hit sound 加上变奏,代码量比两周前还少(因为重构了)。老板/合作者看 diff,觉得你没干活。但玩家上手就感觉到差别。这就是为什么 Vlambeer、Nintendo、Polyphony 这些"手感神话"的工作室,**polish 阶段不写新功能,只改现有功能**。

第二,**polish 是无法精确估时的**。你说"我下周做完 hit feel",做完以后玩一遍,觉得还差点,再改一周;再玩一遍,觉得 camera 跟着 hit 抖了一下不舒服,改一周;再玩一遍,觉得 enemy 死亡 cry 的尾响和下一个 hit sound 撞了,改一周。polish 是**通过"玩"驱动"改"**的循环,这个循环的长度由"什么时候觉得对了"决定,而不是"什么时候 feature complete"决定。这就是为什么资深 producer 给 polish 留的比例比新手想象的**高得多**——通常占整个开发周期的 30-50%。

具体怎么"通过玩驱动改"?**用 CVars(console variables)做实时调参,不要重新编译**。这是工业级 polish 的核心工作流。把所有手感参数 exposed 成 CVar:pitch jitter、volume jitter、shake max offset、hitstop duration、camera damping rate、layer gain curve——全部能从 console 实时改。然后**一直玩,一直改,直到舒服**。

```rust
// 一个最小的 CVar 系统(完整版见 immediate-mode-editor.md)
pub struct CVars {
    map: HashMap<String, f32>,
}

impl CVars {
    pub fn get(&self, name: &str, default: f32) -> f32 {
        self.map.get(name).copied().unwrap_or(default)
    }
    pub fn set(&mut self, name: &str, value: f32) {
        self.map.insert(name.to_string(), value);
    }
}

// 在 trigger_hit 里读 CVar,而不是 hardcode
impl JuiceSystem {
    pub fn trigger_hit(&mut self, sev: f32, cvars: &CVars, audio: &mut AudioEngine) {
        let shake = cvars.get("juice.hit.shake", 0.4) * sev;
        let hitstop_ms = cvars.get("juice.hit.hitstop_ms", 60.0) * sev;
        let pitch_jit = cvars.get("audio.hit.pitch_jitter", 0.05);
        // ...
    }
}
```

游戏运行时打开 console,`juice.hit.shake = 0.6`,立刻看到效果。玩 10 分钟,反复改,直到"对了"。**这个过程比读 100 篇手感文章都有用**。Swink 在《Game Feel》里说,**游戏手感是"玩出来"的,不是"算出来"的**——polish pass 就是把这句话工程化的那段工序。

最后讲一个反模式,这是新手最容易踩的坑:**把 polish 当成"上线前最后一周做的事"**。如果 feature 都做完了才开始 polish,你已经来不及了。正确的做法是**从第一个 prototype 就开始 polish**——Vlambeer 的每一个 prototype 第一周就有 shake、有 particles、有 sound、有 hitstop。他们不是"先做完再 polish",他们是"**polish 就是 feature 的一部分,从 day 1 就做**"。这是为什么他们的 prototype 玩起来就比你的成品好玩。

## 6 · 游戏手感序列收口:四篇的合奏

这是游戏手感序列的第四篇,也是最后一篇。退一步看四篇的合奏:

- **Part 1 — Input(输入手感)**:按下到反应的延迟、输入缓冲、输入预测。它回答"为什么我的角色不听话"。
- **Part 2 — Camera(相机手感)**:平滑跟随、超前预测、阻尼、shake。它回答"为什么我看不清发生了什么"。
- **Part 3 — Feedback(视觉反馈,juice)**:粒子、shake、hitstop、squash & stretch、flash。它回答"为什么打中了没感觉"。
- **Part 4 — Audio & Polish(音频反馈与综合打磨)**:音频作为反馈、变奏、自适应音乐、空间音频、综合打磨。它回答"为什么整个游戏不够爽"。

**这四篇没有任何一篇能单独让游戏"手感好"**。只做 input 不做 camera,角色反应快但镜头跟不上;只做 camera 不做 juice,镜头顺但事件没冲击;只做 juice 不做 audio,粒子在飞但身体没反应;只做 audio 不做 polish,某些事件有声有色,某些事件没反馈,整体不统一。

**手感是四者合奏的结果**。它要求你把四条线**一致地、统一地**应用到游戏的每一个动作、每一个过渡、每一个重复事件、每一个相机时刻上——然后用 CVars 反复调,反复玩,直到舒服。这个"一致地应用 + 反复调"的过程,就是 part 4 §5 讲的 polish pass。

这件事为什么是"工程"而不是"玄学"?因为它**可以被分解、被实现、被测试**。Swink 在《Game Feel》里把"手感"这个词去神秘化的核心论点就是:**game feel 是可度量的工程产物**。延迟 < 50ms 是可度量的。每个动作有 ≥ 2 个反馈通道是可度量的。每个 hit sound 有 ±5% pitch jitter 是可度量的。BGM 在 combat 时 intensity > 0.6 是可度量的。当所有这些可度量的指标都达标,游戏就**不可避免地**有手感。业余游戏和专业游戏的差距,不是"天赋",是**有没有把这些可度量的事做到位**。

你现在已经有了这一整套可度量指标的工程化实现:part 1 的输入缓冲、part 2 的 exp_decay 相机、part 3 的 JuiceSystem、part 4 的 AudioEngine + SmoothedParam + SoundBank。剩下的工作不在"学新东西",而在**把这些零件装到你 HH 项目的每一个角落,然后一直玩一直改**。这就是从"demo"到"game"之间,你需要亲手走完的那段路。

Vlambeer 在《The Art of Screenshake》的最后说:"**Juice 不是装饰,juice 是游戏体验的物理载体。**" 这句话换个说法就是:**game feel 是 engineered 的,而你现在已经有了 engineering**。

## 7 · 在你 HH 项目里动手(做中学红线)

这一节是 part 4 的"做中学"红线。**做完这 6 个任务,你的 HH 就从"有 juice 的 demo"升级成"sound + juice 都到位的小作品"**。每一个任务都能在 1-2 小时内完成,但合起来是质变。

**任务 1:静音测试(诊断)**。在你 HH 项目里,把 audio output mute 掉(`master_volume = 0`),玩 5 分钟。**记下你"感觉不对劲"的所有瞬间**——大概率是:hit 不够重、jump 不够脆、落地没重量感、UI 按钮按下没反馈。这些就是你 part 4 要补的洞。这个"静音测试"是手感诊断的金标准——它把音频的贡献隔离出来,让你看清 part 3 的视觉 juice 单独能撑多少。

**任务 2:静态测试(诊断)**。反过来——**不要按任何键,让游戏自己跑 30 秒**(或者如果游戏需要输入才前进,只做最小移动)。看屏幕、听声音。**每一个 30 秒里出现的"无声动作"都是个 bug**——某只鸟飞过去没声音、某个火把没噼啪声、某个 enemy 没呼吸声、某个 UI 元素自动出场没 tick。把这些全部记下来,这就是你 ambient / system-level audio 的待办清单。

**任务 3:把每个 hit 绑定 sound(实施)**。找到 part 3 的 `JuiceSystem::trigger_hit`,在它里面加一个 `audio.play_one_shot_from_bank(...)`。准备一个 3 个变奏的 hit sound bank(可以是同一个录音的 3 种 EQ 处理),加 ±5% pitch jitter、±10% volume jitter。**用 CVars 把 jitter 暴露出来**,玩的时候实时调到舒服。

```rust
// 你 HH 项目里要补的代码骨架
impl JuiceSystem {
    pub fn trigger_hit(&mut self, x: f32, y: f32, sev: f32, ctx: &mut Context) {
        // part 3 的视觉 juice 不变
        self.add_shake(ctx.cvars.get("juice.hit.shake", 0.4) * sev);
        self.add_hitstop(Duration::from_millis(
            ctx.cvars.get("juice.hit.hitstop_ms", 60.0) as u64 * sev as u64
        ));
        self.spawn_particles(x, y, sev);

        // part 4 新增:音频 juice
        let bank = if sev < 0.5 { &ctx.audio.banks.light_hit } else { &ctx.audio.banks.heavy_hit };
        let pitch = 1.0 + (ctx.rng.gen::<f32>() * 2.0 - 1.0) * ctx.cvars.get("audio.hit.pitch_jitter", 0.05);
        let volume = 0.7 * (1.0 + (ctx.rng.gen::<f32>() * 2.0 - 1.0) * ctx.cvars.get("audio.hit.volume_jitter", 0.1));
        ctx.audio.play_one_shot(OneShot {
            buffer: bank.pick(&mut ctx.rng).clone(),
            pitch,
            volume,
            position: Some(Vec3::new(x, y, 0.0)),
            lowpass_cutoff: 8000.0 - 6000.0 * sev,
        });
    }
}
```

**任务 4:把每一个动作的反馈绑定查一遍(实施)**。grep 你 HH 项目里的所有"动作触发点"——`player.jump()`、`player.land()`、`player.attack()`、`enemy.die()`、`pickup.collect()`、`ui.button_pressed()`。**每一个都必须同时调用 `juice.trigger_xxx(...)` 和 `audio.play_one_shot_from_bank(...)`**。少一个就补上。这一步就是把 part 3 和 part 4 的规则"系统化"地走查整个游戏——本质上是 mini polish pass。

**任务 5:adaptive music 的最小实现(实施)**。给你的 HH 项目加 vertical layering:一段 BGM 拆成 melody + harmony + bass + drums 四个 layer(如果你不会分轨,临时用 4 个不同的 loop 也行)。在游戏状态机里加 `MusicDirector::on_game_state(state)`,把 combat / exploration / low-health 映射到 intensity。**用 1-2 秒的 SmoothedParam 过渡,绝不让音乐瞬间切换**。玩 boss 战,听音乐跟着加 drums;脱离战斗,听 drums 慢慢淡出。**第一次听到 BGM 真的"响应"你的状态,你会理解为什么 adaptive music 是宏观 game feel**。

**任务 6:综合 polish pass(收尾)**。这是 part 4 的最后一道工序,也是整个手感序列的收尾。打开你 HH 项目的所有 CVar,准备一张 checklist(就是 §5 那张),系统走一遍:

```rust
// 在你 game loop 顶部,每帧 reapply 所有 CVar(实时调参的基础)
fn apply_cvars(world: &mut World, cvars: &CVars) {
    world.audio.master_volume = cvars.get("audio.master", 0.8);
    world.audio.music.target_intensity_smoothing = cvars.get("music.smoothing_sec", 2.0);
    world.camera.damping_rate = cvars.get("camera.damping", 5.0);
    world.camera.look_ahead = cvars.get("camera.lookahead", 80.0);
    world.juice.default_shake = cvars.get("juice.default.shake", 0.4);
    world.juice.default_hitstop_ms = cvars.get("juice.default.hitstop_ms", 60.0);
    // ...
}
```

然后**打开游戏,打开 console,一直玩一直改**。改 shake、改 hitstop、改 pitch jitter、改 camera damping、改 layer gain 阈值。**目标是:连续玩 10 分钟,任何一个瞬间都不会觉得"这里差点意思"**。这个目标通常要 4-8 小时的迭代才能达到。这就是"最后 10% 占 50% 时间"那段工序的真实形态。

**做完这 6 个任务,做最后一次静音测试和静态测试**。静音时游戏的视觉 juice 应该还能撑住基本体验(因为 part 3 的视觉部分已经够强);开声音时整个体验应该明显比静音时更"重"、更"爽"。静态时屏幕上应该没有无声动作、没有突兀过渡。**到这一步,你的 HH 项目就走完了从 demo 到 game 的那段路**。

## 8 · 练习

**Lv1(基础,30 分钟)**。给你 HH 项目的 hit sound 加 ±5% pitch jitter 和 ±10% volume jitter。准备 3 个 hit sound 变奏放进 bank。打 50 次 enemy,对比"有变奏"和"无变奏"的体感差距。

**Lv2(进阶,1-2 小时)**。实现任务 5 的 vertical layering adaptive music。把一段 30 秒的 loop 拆成 melody / bass / drums 三轨(可以用 Audacity 手动分,或者用现成的 stem)。映射 `player_health < 0.3` 到 drums layer fade in。**注意:layer 切换必须在 bar boundary + 用 SmoothedParam 过渡**,否则突兀。

**Lv3(挑战,2-4 小时)**。给你 HH 项目加一个最小的 HRTF 空间音频路径:enemy 的 footstep 用 [adaptive-audio-and-3d.md](../../phase-7/deep-dives/adaptive-audio-and-3d.md) §3.3 的 128-tap HRTF convolution 渲染。戴上耳机,让一个 enemy 绕你转一圈,听声音跟着转。**这一步如果你 HH 是俯视角游戏,体感提升会非常显著**。

**Lv4(深度,半天到一天)**。完整 polish pass。打开你 HH 的所有手感 CVar,准备一张 §5 的 checklist,系统走一遍每一个动作和过渡。目标:连续玩 10 分钟没有"差点意思"的瞬间。**做完后找一个朋友玩 5 分钟,观察他/她的表情**——这就是 polish 的最终验收标准。

## 9 · 延伸阅读

本仓库内相关:

- [adaptive-audio-and-3d.md](../../phase-7/deep-dives/adaptive-audio-and-3d.md) — 自适应音乐和 3D 空间音频的完整理论,HRTF、ELIS、Opus voice chat 的母篇。part 4 §3 和 §4 直接依赖这一篇。
- [audio-effects.md](../../phase-5/deep-dives/audio-effects.md) — EQ / compressor / reverb / convolution 全解。part 4 §1 的 lowpass per severity、§4 的 reverb-as-space-map 都依赖这一篇。
- [game-feel-short.md](./game-feel-short.md) — 游戏手感简版(原始篇)。part 4 是这条线的延续。
- [game-feel-01.md](game-feel-01-input-and-timing-feel.md) — 游戏手感序列 part 1(input)。
- [game-feel-02.md](game-feel-02-camera.md) — 游戏手感序列 part 2(camera)。
- [game-feel-03.md](game-feel-03-feedback-juice.md) — 游戏手感序列 part 3(visual feedback / juice)。part 4 是它的直接续篇,必须先读。
- [accessibility-short.md](../../phase-7/deep-dives/accessibility-short.md) — shake / flash / sound 的可访问性开关。part 4 §5 的 polish checklist 里"可关闭"一项的依据。
- phase-2 day041.md — 教学风格金标,本篇写作风格的参照。

外部稳定 URL:

- Steve Swink《Game Feel》(Morgan Kaufmann, 2009)— 本篇 calibration 的母书。完整理论框架,part 4 主要对应 "Audio" 和 "Polish" 两章。
- Jan Willem Nijman "The Art of Screenshake" GDC 2013 — https://www.youtube.com/results?search_query=art+of+screenshake 。juice 的源头演讲,反复强调"sound 让 juice 强 10 倍"。
- Squirrel Eiserloh "Juice It or Lose It" GDC Europe 2013 — 数学推导(trauma 平方曲线、弹簧)的源头。
- Vlambeer 工作室档案 — https://vlambeer.com/ (站点已停止更新,但作品 Nuclear Throne / Luftrausers / Ridiculous Fishing 仍是手感标杆)。
- GDC "Game Audio Boot Camp" 系列演讲 — 工业级 audio polish 的工作流。
- kira crate(Rust game audio)— https://github.com/tesselode/kira
- rodio spatial(Rust 3D audio)— https://github.com/RustAudio/rodio/blob/master/src/spatial.rs

---

写到这里,游戏手感序列四篇就结束了。你手里现在有:

- **Input(part 1)**:输入缓冲、预测、延迟控制
- **Camera(part 2)**:exp_decay 跟随、look-ahead、阻尼、shake
- **Feedback(part 3)**:JuiceSystem,粒子 / hitstop / squash & stretch / flash
- **Audio & Polish(part 4)**:音频作为反馈、变奏、adaptive music、spatial audio、综合打磨

四者合奏,一致应用,反复调参——这就是 game feel 的全部工程。**接下来该做的事不是再读文章,是打开你 HH 项目,静音玩一遍,把每一个"不对劲"的瞬间改到"对了"**。这条路走完,你的游戏就从"能跑的 demo"变成"想一直玩的游戏"。
