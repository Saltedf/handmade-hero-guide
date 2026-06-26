---
phase: 2
type: deep-dive
title_en: "Game Feel & Juice (Short)"
title_zh: "游戏手感与 Juice(简版)"
domains: [game, rust, graphics]
duration: "2h"
---

# 深入:游戏手感与 Juice(简版)

> 你的角色被打了一下,血条减少 30。视觉上发生了什么?**血条数字变化**。这就是全部。玩家感觉怎么样?**没感觉**。你的游戏就是死的。
>
> 同样的伤害事件,Vlambeer 的 Nuclear Throne 怎么做?**屏幕震动 0.15 秒**、**敌人喷 30 个血粒子**、**音效是 808 kick drum**、**hitstop 60ms(整个游戏冻结)**、**屏幕边缘红光闪烁**、**玩家角色 squash & stretch**。同一个"扣 30 血"事件,变成一个**让人想再被打一次**的体验。
>
> 这就是 game feel。它是商业游戏和业余游戏的分水岭。

## 0 · Game Feel 是什么

Jan Willem Nijman(Vlambeer 创始人)在 "The Art of Screenshake" 演讲里说:**game feel 是玩家在不思考时,身体对游戏的物理反应**。你打中敌人会不自觉地往前凑、你被击中会皱眉、你过关会拍桌子——这些都不是"游戏逻辑"层面的反应,是"感官"层面。

Game feel 由三个层面构成:

1. **响应性(responsiveness)**——按下按键到角色动的延迟。> 100ms 玩家就觉得"钝"。理想 < 50ms。
2. **重量感(weight)**——角色有惯性、加速度、停止有过渡。塑料感和"有重量"的差别。
3. **反馈密度(feedback density)**——每个动作都有多重反馈:视觉、音效、震动、粒子。

第三条最常被独立游戏忽略。业余游戏每个动作有 1 个反馈(按键 → 角色动)。专业游戏每个动作有 4-7 个反馈。

## 1 · Juice 元素

下面是 Vlambeer 提的"juice 元素"清单,我们对每一条给 Rust 实现思路。

| 元素 | 描述 | 实现 |
|---|---|---|
| **Screenshake** | 屏幕偏移随机量,逐渐衰减 | 振幅按指数衰减,加到相机 offset |
| **Hitstop / Freeze frame** | 命中瞬间整个游戏暂停几帧 | update 用 `dt = 0` 几帧 |
| **Particles** | 火花、血、烟雾、碎片 | 简单粒子系统,生命周期 + 速度 + 重力 |
| **Squash & stretch** | 物体撞击瞬间形变,然后回弹 | 矩阵 scale,弹簧动画 |
| **Camera lag** | 相机平滑跟随,带轻微滞后 | `lerp` 或弹簧 |
| **Time scaling** | 慢动作(bullet time)/ 加速 | 修改 dt |
| **Color flash** | 命中瞬间染白,然后恢复 | fragment shader mix |
| **Trails** | 快速移动物体留尾迹 | 历史位置画衰减 alpha |
| **Knockback** | 击中反方向推力 | 速度加临时冲量 |
| **Sound design** | 命中低频 punch,移动有脚步声 | 不只是播放,要选合适的样本 |

10 个元素。每条都对应一段 100 行的 Rust 代码。下面我们挑 4 条最有性价比的做实战:screenshake、hitstop、particles、color flash。

## 2 · Vlambeer 的 "Art of Screenshake"

Nijman 2013 年 GDC 演讲 "The Art of Screenshake" 是独立游戏必看。核心论点:**screenshake 不是"装饰",是"语言"**——玩家通过 screenshake 强度判断事件严重性。小 shake = 小事,大 shake = 大事。

他在演讲里演示了一个 Luftrausers 的 prototype。同一个攻击,没 shake 玩家觉得"软",加了 shake 玩家觉得"重"。**仅靠一个 5 行的 shake 算法,游戏感觉质变**。

经典算法:**指数衰减的随机偏移**。

```rust
struct ScreenShake {
    trauma: f32,       // 当前创伤值,0..1
    max_offset: f32,   // 最大偏移像素
    seed: u32,         // 噪声种子
}

impl ScreenShake {
    fn add_trauma(&mut self, amount: f32) {
        // trauma 累加,封顶 1
        self.trauma = (self.trauma + amount).min(1.0);
    }

    fn update(&mut self, dt: f32) -> (f32, f32) {
        // trauma 按指数衰减
        self.trauma *= (-dt / 0.2).exp();  // 200ms 时间常数
        // shake 振幅是 trauma 平方(更"暴力"的曲线)
        let shake = self.trauma * self.trauma;
        // 用 perlin / sin 噪声生成 offset
        let t = instant_now();
        let offset_x = (self.max_offset * shake) * noise(t * 30.0, self.seed);
        let offset_y = (self.max_offset * shake) * noise(t * 30.0 + 100.0, self.seed);
        (offset_x, offset_y)
    }
}

fn noise(t: f32, seed: u32) -> f32 {
    // 简单的 sin-based pseudo-noise,生产用 Perlin / Simplex
    (t.sin() * (seed as f32) * 0.1).sin()
}
```

`trauma` 平方的设计是 Squirrel Eiserloh 在 GDC 2015 "Juice It or Lose It" 演讲里强调的:线性 trauma 衰减看起来"平",平方曲线让大事件看起来"猛烈",小事件"温和"——这是非线性心理感知。

## 3 · 控制曲线:指数衰减 / 弹簧

游戏手感的核心数学是**插值曲线**。三种主流:

**线性插值(lerp)**:不推荐。看起来机械。只在玩家可预测的场合用(血条数字减少)。

```rust
fn lerp(a: f32, b: f32, t: f32) -> f32 {
    a + (b - a) * t
}
```

**指数衰减(exponential)**:推荐默认。每帧朝目标移动固定比例。看起来"自然减速"。

```rust
fn exp_decay(current: f32, target: f32, decay_rate: f32, dt: f32) -> f32 {
    // decay_rate 越大衰减越快。1.0 = 100ms 衰减一半,5.0 = 20ms 衰减一半
    target + (current - target) * (-decay_rate * dt).exp()
}
```

这个公式的物理意义是"阻尼",自然出现在所有"摩擦"系统中。游戏里相机的"平滑跟随"几乎都用这个。

**弹簧(spring)**:推荐"overshoot"场合。物体冲过目标,回弹,几次振荡后稳定。

```rust
struct Spring {
    pos: f32,
    vel: f32,
    target: f32,
    stiffness: f32,   // 弹簧硬度
    damping: f32,     // 阻尼
}

impl Spring {
    fn update(&mut self, dt: f32) {
        let force = -self.stiffness * (self.pos - self.target);
        self.vel += force * dt;
        self.vel *= (-self.damping * dt).exp();  // 阻尼
        self.pos += self.vel * dt;
    }
}
```

弹簧是 squash & stretch 的核心——角色被击中,挤压瞬间形变(-0.2 scale),然后弹簧回弹到 1.0,中间可能 overshoot 到 1.05。这种"过冲"是手感来源。

stiffness = 100、damping = 10 是个好起点(临界阻尼)。stiffness 高振荡快,damping 高振荡消失快。**临界阻尼**(damping = 2 * sqrt(stiffness))是不 overshoot 的最快收敛。

## 4 · 实战:Rust 给 HH 加 screenshake + hitstop + 4 种 juice

把上面所有概念整合,我们给 Handmade Hero 加一个 JuiceSystem。代码片段:

```rust
// juice.rs

use std::time::{Duration, Instant};

pub struct JuiceSystem {
    // screenshake
    shake_trauma: f32,
    // hitstop
    freeze_until: Option<Instant>,
    // particles
    particles: Vec<Particle>,
    // color flash
    flash_alpha: f32,
}

#[derive(Clone)]
struct Particle {
    x: f32, y: f32,
    vx: f32, vy: f32,
    life: f32,         // 剩余秒数
    max_life: f32,
    color: [f32; 4],
    size: f32,
}

impl JuiceSystem {
    pub fn new() -> Self {
        Self {
            shake_trauma: 0.0,
            freeze_until: None,
            particles: vec![],
            flash_alpha: 0.0,
        }
    }

    pub fn trigger_hit(&mut self, x: f32, y: f32, severity: f32) {
        // 一次性触发 4 种 juice
        self.add_shake(0.4 * severity);
        self.add_hitstop(Duration::from_millis((60.0 * severity) as u64));
        self.spawn_blood_particles(x, y, 20 + (40.0 * severity) as usize);
        self.flash_alpha = (0.7 * severity).min(1.0);
    }

    pub fn add_shake(&mut self, trauma: f32) {
        self.shake_trauma = (self.shake_trauma + trauma).min(1.0);
    }

    pub fn add_hitstop(&mut self, duration: Duration) {
        let until = Instant::now() + duration;
        self.freeze_until = Some(until);
    }

    fn spawn_blood_particles(&mut self, x: f32, y: f32, count: usize) {
        for _ in 0..count {
            let angle = rand_0_2pi();
            let speed = 50.0 + rand_float() * 200.0;
            let vx = angle.cos() * speed;
            let vy = angle.sin() * speed;
            let life = 0.3 + rand_float() * 0.5;
            self.particles.push(Particle {
                x, y, vx, vy,
                life, max_life: life,
                color: [0.8, 0.1, 0.1, 1.0],  // 红色
                size: 2.0 + rand_float() * 3.0,
            });
        }
    }

    pub fn update(&mut self, dt: f32) -> (f32, f32) {
        // 1. hitstop 检查
        if let Some(until) = self.freeze_until {
            if Instant::now() < until {
                // 冻结期间所有 update 用 dt=0
                return (0.0, 0.0);
            } else {
                self.freeze_until = None;
            }
        }

        // 2. screenshake 衰减
        self.shake_trauma *= (-dt / 0.15).exp();
        let shake_amp = self.shake_trauma * self.shake_trauma;
        let offset_x = shake_amp * 20.0 * pseudo_noise(Instant::now(), 0);
        let offset_y = shake_amp * 20.0 * pseudo_noise(Instant::now(), 1);

        // 3. particles 更新
        for p in &mut self.particles {
            p.x += p.vx * dt;
            p.y += p.vy * dt;
            p.vy += 400.0 * dt;  // 重力
            p.vx *= (-2.0 * dt).exp();  // 空气阻力
            p.life -= dt;
        }
        self.particles.retain(|p| p.life > 0.0);

        // 4. flash 衰减
        self.flash_alpha *= (-dt / 0.08).exp();

        (offset_x, offset_y)
    }

    pub fn current_flash(&self) -> [f32; 4] {
        // 返回叠加颜色
        [1.0, 1.0, 1.0, self.flash_alpha]
    }
}

fn rand_0_2pi() -> f32 {
    use std::collections::hash_map::DefaultHasher;
    use std::hash::{Hash, Hasher};
    let mut h = DefaultHasher::new();
    Instant::now().hash(&mut h);
    ((h.finish() as f32 / u64::MAX as f32) * std::f32::consts::TAU)
}

fn rand_float() -> f32 {
    use std::collections::hash_map::DefaultHasher;
    use std::hash::{Hash, Hasher};
    let mut h = DefaultHasher::new();
    Instant::now().hash(&mut h);
    (h.finish() as f32 / u64::MAX as f32)
}

fn pseudo_noise(now: Instant, seed: u64) -> f32 {
    let t = now.elapsed().as_secs_f32();
    (t * 30.0 + seed as f32).sin() * 2.0 - 1.0
}
```

主循环里:

```rust
let mut juice = JuiceSystem::new();
let mut dt = 1.0 / 60.0;

loop {
    let (shake_x, shake_y) = juice.update(dt);
    let flash = juice.current_flash();

    // 渲染时把 (shake_x, shake_y) 加到相机 offset
    // 渲染时把 flash 颜色叠到屏幕最顶层

    if player_takes_damage() {
        juice.trigger_hit(player.x, player.y, 1.0);
    }
}
```

这套实现的核心:**所有 juice 效果共享一个 `JuiceSystem`**,游戏代码只需要在关键事件里调 `trigger_hit` / `add_shake` / `add_hitstop`。Juice 系统负责衰减、生命周期、清理。

**实际效果对比**:

- 没 juice:玩家被打 → 血条减少。视觉无变化。
- 有 juice:玩家被打 → 屏幕震一下、整个游戏冻结 60ms、30 个红粒子向四周喷射、屏幕全屏闪白 80ms。**玩家立刻感受到"被打了一下"**。

这个差别是商业产品 vs 业余作品的本质差别。Vlambeer、Derek Yu(Spelunky)、Edmund McMillen(Super Meat Boy)的早期演讲都在反复强调这一点。

## 5 · Juice 设计的反模式

新手做 juice 容易陷入的几个坑:

**坑 1:Juice 过多**。屏幕每秒震 5 次,玩家头晕。Juice 要"少而精"——关键事件给足,小事件不给。普通走路不要 shake,boss 大招才 shake。

**坑 2:Juice 不分严重性**。小伤害和大伤害都震 100ms。玩家失去对"严重性"的感知。应该按 severity 缩放:`shake_amp = severity * severity`。

**坑 3:Juice 不可配置**。**永远给玩家"减少 shake"选项**。前庭功能敏感的玩家会因 shake 恶心。`accessibility-short.md` 专门讨论这个。把 shake / flash / particles 都做成可关闭的 accessibility 选项。

**坑 4:Sound 设计被忽略**。Nijman 反复强调:有 sound 的 juice 比没 sound 的 juice 强 10 倍。一个 hitstop 配合 80Hz kick drum,玩家"身体"反应;没 sound 的 hitstop 玩家"理性"反应。两者差别巨大。

**坑 5:测试只在 60Hz**。在 60Hz 调好的 juice,144Hz 屏幕上 shake 可能太短、particle 太少。**Juice 要按时间(秒)而不是帧数定义**。`life = 0.3` 而不是 `life = 18 frames`。否则高刷新率屏幕上效果稀释。

## 6 · 关联与延伸

- 这份简版聚焦"实战",完整版理论见 Vlambeer "Art of Screenshake" GDC 2013 演讲(YouTube)
- Squirrel Eiserloh "Juice It or Lose It" GDC Europe 2013 — 数学推导的源头
- accessibility-short.md(shake / flash 的可访问性开关)
- immediate-mode-editor.md(给 juice 加实时调试 UI)
- `days/phase-2/day041.md`(教学风格金标)
- Bevy 的 bevy_hanabi(粒子系统工业级实现)
- "Game Feel" by Steve Swink(书,完整理论框架)

Juice 不是"装饰"。Juice 是游戏体验的物理载体。一个"血条减少 30"的事件,通过 juice 设计,可以是无聊的数字游戏,也可以是让玩家心跳加速的瞬间。**写完 juice 系统后,你的游戏感觉像换了 5 倍预算**。
