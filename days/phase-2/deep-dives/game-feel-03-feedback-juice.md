---
phase: 2
type: deep-dive
title_en: "Game Feel & Juice — Feedback Layer (Part 3 of 4)"
title_zh: "游戏手感与 Juice:反馈层(4 部之第 3 部)"
difficulty: 3
duration: "4h"
domains: [game, rust, graphics, animation]
prereqs: [particle-systems-cpu, game-feel-02]
calibration: "Steve Swink《Game Feel》+ 'Juice' (Vlambeer) — hitstop / 粒子 / 缓动 / squash-stretch"
---

# 游戏手感与 Juice:反馈层(4 部之第 3 部)

> 你刚把 HH 的剑挥出去,剑尖划过史莱姆。伤害判定触发,史莱姆 HP 从 30 减到 12。代码上**完全正确**——`hp -= 18` 那一行执行了,变量更新了。但你盯着屏幕,看着那只史莱姆纹丝不动地保持站姿,只看到血条上的数字跳了一下。说不上哪里不对,就是**什么都没发生**。你想:我写的是不是个 Excel 表格?
>
> 这就是 Vlambeer 创始人 Jan Willem Nijman 在 2013 GDC 那场 "The Art of Screenshake" 演讲里反复痛斥的现象——技术正确,但感觉为零。缺的不是逻辑,是**反馈**(feedback):那层视觉和动感的"汁水"(juice),专门告诉玩家"你这一刀**真的砍到东西了**,而且砍的是一个有重量的实体"。这一篇就是手感四部曲的第三部,讲透反馈层。

## 0 · 为什么单独把"反馈"拎出来讲

手感这个话题在 Steve Swink 那本 《Game Feel》里被拆成三大支柱:**输入**(玩家按了什么)、**预测**(游戏怎么响应)、**情境**(屏幕上发生什么)。但这三根支柱如果只各自独立做工,游戏体验依然是散的。把它们黏合在一起、让玩家**身体**而不只是**眼睛**感觉到"我刚才做了件事"的,是反馈层。一个挥剑的动作,如果没有任何反馈,玩家在心理上会觉得"我只是按了一下空格"。一旦反馈到位——屏幕震了一下、史莱姆挤扁了、火星溅出来、整个游戏暂停了 80 毫秒——玩家的身体会下意识往前凑一下。这种"凑一下"就是反馈层成功的标志。

四部曲里我们已经走完了输入(game-feel-01)和摄像机(game-feel-02),接下来还要补音频(game-feel-04)。**反馈层和这三者**是分工但不分家的关系。摄像机告诉你"hitstop 怎么和镜头搭配",输入告诉你"按下和释放的瞬间分别要触发什么反馈",音频告诉你"hitstop 期间那个 80Hz 的 kick drum 怎么配"。这篇专讲反馈层内部怎么搭——hitstop、squash-stretch、screenshake、particle burst、easing、以及"克制"这条最容易被新手忽略的纪律。

读完这一篇你应该能做到:在 HH 项目里给一次普通的命中加上 5 种反馈,调出"砍到了真的东西"的感觉;然后在你的 CVars 控制台(`09B-4`)里把所有反馈调到最大,亲眼看看为什么"juice 过载"反而让游戏看起来廉价;最后把数值压回到克制的区间,理解每一条 juice 在什么事件上才值得出现。

## 1 · 反馈层的心智模型:为什么"挨打"要冻一下

在动手写代码之前,我们要先理解一个反直觉的事实:**让玩家觉得"重"的,不是更快的运动,而是有节制的停顿**。

举一个生活化的例子。你在健身房推举,杠铃刚到顶端,教练突然帮你扶住,让杠铃"停"在那里 0.2 秒,然后才放下来。你会立刻感觉到这杠铃有多重——你的肩膀、手腕、核心都会被这一下的"停顿"调动起来。如果教练一推一拉,毫无停顿,你反而觉得轻飘飘。游戏里的打击感遵循同样的生理学。一次挥剑的命中,如果在剑尖接触敌人的那一瞬间,整个世界冻住 50 到 100 毫秒,玩家的脑会**自动把这个停顿解读成"重量的证据"**——大脑推理:既然这个世界都为这一下停下来了,那这一下一定很重。

这个机制在认知科学里有个粗糙但贴切的名字叫 **change blindness 的反向**——我们的大脑被训练成"忽略连续、关注中断"。一个一直流畅运行的画面,大脑会进入 autopilot 模式;一旦画面在某一个瞬间被"打断",注意力瞬间被拉过去。Vlambeer 在演讲里反复强调:hitstop 不是装饰,它是**告诉玩家"注意,这一刻很重要"的语言**。

理解了这一点,你就理解了为什么反馈层的所有手段——hitstop、screenshake、squash-stretch、粒子爆发——**本质上都是在制造"中断"和"对比"**。接下来我们一条一条讲。

## 2 · Hitstop:命中那 80 毫秒的世界冻结

### 2.1 它到底是什么

Hitstop(也叫 freeze frame、hit pause、impact pause)指的是:**在重击命中的那一瞬间,把整个游戏的 simulation 暂停一小段时间**(典型 50 到 100 毫秒),然后恢复正常。注意——暂停的是 simulation,不是渲染。屏幕**还在 60 FPS 刷新**,只是屏幕里的所有东西——玩家、敌人、粒子、动画状态机——都保持原样不动。这 80 毫秒在玩家脑里被读成"这一刀的冲量太大了,把时间都打停了"。

为什么是 50-100 毫秒这个区间?因为低于 40 毫秒大脑感觉不到(会被当作单帧抖动),超过 150 毫秒就开始让人觉得"游戏卡了"。80 毫秒是 Super Smash Bros、Street Fighter 系列重击的标准值,几乎是个"魔法数字"。

### 2.2 在游戏循环里实现

把 hitstop 接到你的主循环(见 `09B-1` 的 game loop)里只需要一个"模拟暂停计时器"。每一帧 tick 开始时检查这个计时器,如果还没归零,就**跳过 simulation 的 update**,但仍然渲染:

```rust
use std::time::{Duration, Instant};

/// 全局的 hitstop 状态。挂在 game state 上,所有 system 都能读
pub struct Hitstop {
    /// 还要冻结多久。None 表示没在冻结
    remaining: Option<Duration>,
}

impl Hitstop {
    pub fn new() -> Self {
        Self { remaining: None }
    }

    /// 在重击事件里调用。传入要冻结的时长
    /// 注意:取 max 而不是累加,避免连续命中把冻结时间叠到天荒地老
    pub fn trigger(&mut self, duration: Duration) {
        self.remaining = Some(match self.remaining {
            Some(prev) if prev > duration => prev,
            _ => duration,
        });
    }

    /// 每帧开始时调用。返回 true 表示当前帧 simulation 应该跳过
    pub fn tick(&mut self, dt: Duration) -> bool {
        match &mut self.remaining {
            None => false,
            Some(r) => {
                if *r >= dt {
                    *r -= dt;
                    true   // 还在冻结,跳过 simulation
                } else {
                    self.remaining = None;
                    true   // 这一帧的剩余冻结时间内仍然跳过
                }
            }
        }
    }

    pub fn is_active(&self) -> bool {
        self.remaining.is_some()
    }
}
```

主循环里这样接:

```rust
loop {
    let dt = stopwatch.delta();
    let frozen = hitstop.tick(dt);

    // 输入永远要读——不然玩家在 hitstop 期间按了闪避会丢失
    input.collect();

    if !frozen {
        // simulation 更新:玩家移动、敌人 AI、动画、粒子物理...
        world.update(dt);
    }
    // 不管冻不冻,都渲染。让玩家看到"画面停在那"
    renderer.draw(&world, &camera);
    window.swap();
}
```

这里有一个**新手最容易踩的坑**:把 hitstop 写成"全主循环 `sleep`"。这种写法在某些早期教程里能看到,但完全错误。`sleep` 会冻结输入采集,导致玩家在 hitstop 期间按下的闪避键直接丢失。正确做法是**只跳过 simulation 的 update,渲染和输入仍然每帧进行**。这样玩家在 80 毫秒冻结期间按闪避,游戏会在冻结结束的下一帧立即响应,完全没有"输入被吞"的感觉。

另一个坑是**音效**。hitstop 期间,大部分音效(尤其命中的低频打击音)应该**照常播放**——音效不依赖 simulation 帧。这正是为什么 hitstop 配合 80Hz kick drum 这么爽:画面冻了,鼓点响了,大脑把两者合成一个"重击"体验。这层跨感官的合成,我们留到 game-feel-04 详细讲。

### 2.3 调参:轻重和事件类型

Hitstop 不是所有命中都一样长。工业实践的调参经验:轻击 0-30 毫秒(几乎没有,只在有击退时给一点点)、普通攻击 50-80 毫秒、重击 100-150 毫秒、必杀/处决 200-400 毫秒(已经在"小段慢动作"的边缘,要谨慎)。**轻击不要给 hitstop**——如果每一刀都冻 80 毫秒,玩家会觉得游戏卡顿。Hitstop 是"重事件"的语言,用多了就贬值。

把每个事件类型的 hitstop 时长做成 CVar(见 `09B-4`),在游戏运行时实时调,是工业化标配。比如:

```rust
// 在 dev_console 里注册
cvars.register_f32("hitstop_light", 0.0);     // 轻击不冻
cvars.register_f32("hitstop_normal", 0.06);   // 60ms
cvars.register_f32("hitstop_heavy", 0.10);    // 100ms
cvars.register_f32("hitstart_finisher", 0.20); // 处决 200ms
```

调出"打中 Boss 的最后一下"那种命中时,你会发现 hitstop 加到 150ms 配合一个白色全屏 flash,玩家下意识会喊一声"漂亮"——这就是反馈层的甜区。

## 3 · Squash and Stretch:把动画原理借给游戏

### 3.1 从迪士尼十二条到游戏

Squash and stretch(挤压与拉伸)是迪士尼动画师 1930 年代总结的"动画十二原则"第一条。讲的是一个有弹性的物体在受力时**沿受力方向被压扁**(squash),**垂直受力方向被拉长**(stretch),然后弹回原状。一颗皮球落到地面那一瞬间是扁的(垂直方向被压),弹起来上升的过程中是长的(垂直方向被拉)。这个形变传达两个信息:**有质量**(否则不会形变),**有弹性**(形变能恢复)。

游戏继承了这个原则,但用法不太一样。电影里 squash-stretch 是逐帧画出来的,游戏里我们要**用程序实时计算 scale**,然后让动画系统应用。好处是:它能对任意事件做出反应——这次落地和下次落地高度不同,scale 形变也跟着不同,这种"实时响应"是预录动画做不到的。

### 3.2 实现:沿主轴的弹簧动画

最干净的实现是把 squash-stretch 想成**一根弹簧**:`scale_x` 和 `scale_y` 是两个独立的 spring,平时 target = 1.0,事件触发时把 target 推到一个偏离值,然后让 spring 自然回弹。Spring 的物理我们在 game-feel-short 里讲过,这里直接用:

```rust
use glam::Vec2;

/// 一个 axis-aligned 的 squash-stretch 形变。
/// scale_x 是水平缩放,scale_y 是垂直缩放,默认 (1, 1)
pub struct SquashStretch {
    pub scale: Vec2,
    pub vel: Vec2,           // 每个轴的弹簧速度
    pub stiffness: f32,      // 典型 150-300
    pub damping: f32,        // 典型 8-15
}

impl SquashStretch {
    pub fn new() -> Self {
        Self {
            scale: Vec2::new(1.0, 1.0),
            vel: Vec2::ZERO,
            stiffness: 200.0,
            damping: 12.0,
        }
    }

    /// 触发一次形变。amount 是形变量,主轴指受力方向(单位向量)
    /// amount = 0.2 表示主轴压缩到 0.8、垂直轴拉伸到 1.2(体积近似守恒)
    pub fn trigger(&mut self, amount: f32, main_axis: Vec2) {
        let area_preserve = (1.0 - amount).sqrt();
        // 主轴 = main_axis 方向;垂直 = (-main_axis.y, main_axis.x)
        // 为简化我们假设 main_axis 已经是 (1,0) 或 (0,1) 这种 axis-aligned
        // 通用情况要存一个完整的 transform,这里留给读者扩展
        let (mx, my) = (main_axis.x.abs(), main_axis.y.abs());
        // 主轴方向 scale 减小,垂直方向 scale 增大(近似面积守恒)
        self.scale.x = 1.0 - amount * mx + (area_preserve - 1.0) * my;
        self.scale.y = 1.0 - amount * my + (area_preserve - 1.0) * mx;
        // vel 归零,让 spring 从这个形变开始回弹
        self.vel = Vec2::ZERO;
    }

    /// 每帧调用。target 永远是 (1, 1),spring 把 scale 拉回去
    pub fn update(&mut self, dt: f32) {
        let target = Vec2::new(1.0, 1.0);
        let force = (target - self.scale) * self.stiffness;
        self.vel += force * dt;
        // 指数阻尼
        let damp = (-self.damping * dt).exp();
        self.vel *= damp;
        self.scale += self.vel * dt;
    }
}
```

落地场景怎么用:

```rust
fn on_player_land(player: &mut Player, land_speed: f32) {
    // 着地速度越快,挤压越厉害。clamp 到 0.3 防止夸张
    let amount = (land_speed / 800.0).clamp(0.0, 0.3);
    // 着地是垂直方向受力,主轴 = (0, 1)
    player.squash_stretch.trigger(amount, Vec2::new(0.0, 1.0));
}
```

挥剑命中场景:

```rust
fn on_sword_hit(slime: &mut Slime, hit_normal: Vec2) {
    // 命中的"挤压方向"是冲击力的法线。比如剑从上往下砍,hit_normal = (0, 1)
    let amount = 0.18;
    slime.squash_stretch.trigger(amount, hit_normal);
}
```

### 3.3 调参的甜区

Squash-stretch 的调参比 hitstop 更微妙。`stiffness` 决定回弹速度—— stiffness = 100 回弹慢(粘腻),stiffness = 400 回弹快(利落)。`damping` 决定要不要 overshoot—— damping 大不 overshoot,critical damping(`damping = 2 * sqrt(stiffness)`)是最快但不超调;damping 小会有 1-2 次小振荡,看起来更"有弹性"。敌人这类有"血肉感"的对象推荐稍低 damping(允许轻微 overshoot),玩家角色推荐 critical damping(避免镜头晃)。

`amount` 一般在 0.1 到 0.3 之间。0.1 几乎看不出来,适合"小动作"(走路的脚步);0.2 是常规命中;0.3 已经有点夸张了,适合处决。**永远不要超过 0.4**——超过这个值,物体会被压成 pancake 或拉成面条,反而失去重量感(因为大脑识别出"这不是真的物体")。

### 3.4 体积守恒的数学

为什么 squash-stretch 要"近似体积守恒"?因为大脑对物体的"身份"判断依赖体积。如果一个角色被压扁后体积明显缩小,大脑会觉得"它消失了";如果体积明显变大,大脑会觉得"它变胖了"。我们要传达的是**形变但身份不变**,所以体积要近似守恒。在 2D 里,"体积"= 面积 = `scale_x * scale_y`,所以如果 `scale_x = 1 - k`,正确的 `scale_y` 应该是 `1 / (1 - k)`,而不是 `1 + k`。但是 `1/(1-k)` 在 k > 0.3 时会爆炸式增长,所以实践中用 `1 + k` 这种"近似"已经够好——只要 k 不大,误差在视觉上看不出来。

代码里我用 `area_preserve = sqrt(1 - amount)` 是一个折中:它在 amount 较小时近似 `(1-amount, 1+amount)`,在 amount 较大时不会让 scale_y 爆炸。**记住:工业级 squash-stretch 库(比如 Unity 的 DOTween 的 `PunchScale`)用的也是这种近似,因为视觉差异肉眼不可分**。

## 4 · Screenshake:从摄像机借来的振幅

Screenshake 的算法和实现我们已经在 game-feel-02 里详细讲过(指数衰减的 trauma 模型 + 平方振幅曲线)。这里我们只讲它在反馈层里的**用法**——具体地说,screenshake 是反馈层里**最便宜也最容易过量**的一种。

便宜指的是:实现成本极低(一个 trauma 变量加两个 sin 函数),收益极高(瞬间传达"严重性")。容易过量指的是:screenshake 直接动整个摄像机,影响**所有**画面元素,稍微一过就让玩家前庭不适。Squirrel Eiseroh 在 GDC 2015 演讲里反复强调:screenshake 的 trauma 平方曲线(`amp = trauma * trauma`)是为了**让小事件几乎不震,大事件才震得猛**。如果你把所有命中都给 `trauma = 0.3`,玩家 5 分钟就头晕。

反馈层里 screenshake 的正确用法是**和事件严重性挂钩**:

```rust
fn on_hit_event(shake: &mut ScreenShake, event: &HitEvent) {
    // event.damage 已经是事件本身的"严重性"指标
    // 用 sqrt 让小伤害也震一点点,但大伤害震得猛
    let trauma = (event.damage as f32 / 50.0).sqrt().clamp(0.0, 1.0);
    shake.add_trauma(trauma);
}
```

注意 `sqrt` 这个选择——和 trauma 平方衰减组合起来,整条响应曲线是 `amp = (sqrt(damage/50))^2 = damage/50`,**线性**。这意味着玩家感受到的 shake 振幅和伤害成正比,直觉上对得上"打多重的一击,震得多厉害"。如果你用线性 trauma 加平方 amp,小伤害几乎不震,大伤害震爆——这适合 boss 战的极端对比,但日常战斗会感觉"轻击没反应"。

调参的建议:把 shake 的 `max_offset` 和 trauma 系数都做成 CVar,在游戏里实时拉到几个不同事件上试,看哪种曲线和你游戏的伤害数字配比最舒服。**永远在 accessibility 菜单里提供"完全关闭 shake"的选项**——前庭功能敏感的玩家(约占人群 10-15%)会因 shake 恶心。这条我们在 phase-7 的 `accessibility-short` 里详细讲。

## 5 · 粒子爆发:反馈层的劳模

如果说 hitstop 是反馈层里的"高光时刻",粒子(particle)爆发就是反馈层里的"劳模"——它出现在几乎每一个反馈事件里:剑命中的火花、人物落地的尘土、爆炸的碎片、技能释放的魔法光点。粒子系统的底层实现我们在 `particle-systems-cpu` 里花了一整篇讲(SoA 池、emitter 几何、billboard 渲染),这里只讲反馈层视角:**怎么为单个事件"调出"一个对的粒子爆发**。

### 5.1 为事件选 emitter

反馈层里的粒子几乎都是 **burst emitter**(突发式喷射),不是 continuous。burst 的意思是"事件触发那一刻 spawn 一批粒子,之后就不再 spawn"。这一批粒子的数量、初速、寿命、颜色,完全由事件决定。

不同的反馈事件用不同的 emitter 几何(几何的数学推导见 particle-systems-cpu 第 3 节):

剑命中的火花用 **cone emitter**,锥轴沿命中点的法线方向(垂直于被砍表面),半角 30-45 度。这样火花会"从被砍点向外溅",符合物理直觉。粒子寿命短(0.2-0.4 秒),颜色从亮黄到暗红再消失,大小 3-8 像素,初速度高(5-10 米/秒)。

```rust
fn spawn_sword_hit_sparks(pool: &mut ParticleSystem, pos: Vec3, normal: Vec3, severity: f32) {
    let count = (15 + 25.0 * severity) as usize;
    for _ in 0..count {
        // cone emitter:沿 normal 方向,半角 0.6 弧度
        let (p, v) = emit_cone(&mut rng, pos, normal, 0.6, 4.0, 9.0);
        pool.spawn(p, v, rng.range(0.2, 0.4), rng.range(0.03, 0.08));
    }
}
```

人物落地的尘土用 **half-sphere emitter**(球 emitter 的上半球),粒子从落地点向四周水平散开,寿命稍长(0.4-0.8 秒),颜色是灰土色,初速度低(2-4 米/秒),重力是负的(尘土往上飘一会儿)。这看起来反直觉,但尘土之所以"飘"是因为空气阻力远大于重力,粒子在阻力下慢慢减速然后才下沉——所以前 0.3 秒粒子**应该看起来像在浮**,后期才开始落。

爆炸的碎片用 **full-sphere emitter**(全向),粒子寿命分散(0.5-2.0 秒,有的飞得远)、初速度高(8-15 米/秒)、重力正常(下沉)、颜色按"刚爆炸的橙红 → 冷却的黑灰"渐变。重要细节:**爆炸应该混合两类粒子**——快、亮、短命的火星(易燃物)+ 慢、暗、长命的烟雾(残留物)。两类粒子的物理参数完全不同,这是为什么工业引擎(Unreal Niagara、Unity VFX Graph)允许一个 emitter 配多个 spawn 模块。

### 5.2 数量和严重性挂钩

跟 hitstop、screenshake 一样,粒子数量也必须按事件严重性缩放。一把小刀砍一刀给 10-15 个火星,大剑重斩给 30-50 个,技能大招给 100-200 个。**永远不要给每个普通事件都 spawn 200 个粒子**——除了性能问题,更严重的是**严重性贬值**:如果每刀都是 200 粒子,玩家看不出哪一刀"更重"。

数量缩放推荐用 sqrt:

```rust
let particle_count = (base_count as f32 * severity.sqrt()) as usize;
```

`severity.sqrt()` 让小事件的粒子数被压低,大事件的粒子数被抬高,响应曲线和大脑的"严重性感知"对得上。

### 5.3 颜色和 alpha 曲线

反馈粒子的颜色曲线有几个工业惯例:**命中火花**是"亮黄(0.0) → 橙红(0.4) → 暗红(0.7) → 透明(1.0)",模拟金属摩擦产生的火星冷却过程。**爆炸**是"白热(0.0) → 橙(0.2) → 暗红(0.5) → 黑烟(0.8) → 透明(1.0)",模拟火球膨胀冷却。**血**是"鲜红 → 暗红 → 透明",**魔法**是"亮蓝/紫 → 暗 → 透明"。

Alpha 曲线(透明度)有个坑:不要用线性 alpha 衰减(`alpha = 1 - t`)。线性衰减在中段(t=0.5)粒子还有 50% alpha,看起来仍然很显眼,然后到 0.9 突然消失,观感是"粒子突然没了"。正确做法是用 ease-in 衰减——前 70% 寿命 alpha 几乎不变,后 30% 快速淡出:

```rust
fn alpha_curve(t: f32) -> f32 {
    // t 是 [0, 1] 的归一化寿命
    // 前 0.7 保持 alpha 1.0,后 0.3 用 ease-in 快速衰减
    if t < 0.7 {
        1.0
    } else {
        let local_t = (t - 0.7) / 0.3;
        1.0 - local_t * local_t   // ease-in 曲线
    }
}
```

这种"前段保持后段淡出"的曲线让粒子看起来"活够本了再消失",而不是"慢慢淡到你以为还在但其实已经没了"。

### 5.4 性能预算

反馈层的粒子是临时爆发的,不是持续喷射。所以总粒子数(同时活跃)一般很低——一次战斗场景同时 200-500 个粒子,CPU 粒子系统完全 hold 得住。**不要因为"反正粒子系统跑得动"就给每次命中都 spawn 500 个粒子**——再便宜的 spawn 调用,在每帧几百次的情况下也会累积。

如果某个反馈事件需要持续几百粒子的复杂效果(比如 boss 大招),考虑预生成一个"effect asset",触发时直接 playback,而不是每次重新 spawn。Unity VFX Graph 的 Point Cache 就是这个思路。

## 6 · Easing 和 Tweening:为什么线性的东西都该改

到这里我们已经讲了 hitstop、squash-stretch、screenshake、粒子。你可能注意到这些反馈都有一个共同模式:**它们都是一个"事件触发 → 状态偏离 → 回到原状"的过程**。Squash-stretch 触发后回到 scale 1,screenshake 触发后回到 trauma 0,粒子 spawn 后寿命归零,scale 动画播放后回到 idle。

这些"回到原状"的过程,**绝不能用线性插值**。线性插值(`lerp(a, b, t)` with `t = elapsed / duration`)看起来机械、呆板,像 Excel 表格里渐变的颜色。游戏手感的核心数学技巧是 **easing curve**(缓动曲线):让 `t` 经过一个非线性变换,让"过渡"看起来像有意图的运动。

### 6.1 三种最基本的缓动

工业级 tweening 库(Rust 生态的 `leafface`、`bevy_tweening`,JS 的 `gsap`)都提供几十种缓动函数。但你只需要记住三种:

**Ease-out**(快进慢出):开始快,后面慢。适合"到达"——一个 UI 元素从屏幕外飞入,一把剑挥到目标位置,一个粒子减速到停止。视觉上像"有目的地接近"。

```rust
fn ease_out_cubic(t: f32) -> f32 {
    1.0 - (1.0 - t).powi(3)
}
```

**Ease-in**(慢进快出):开始慢,后面快。适合"出发"——一个物体被推出、一个坠落的石头、一个加速冲向玩家的敌人。视觉上像"积攒能量"。

```rust
fn ease_in_cubic(t: f32) -> f32 {
    t * t * t
}
```

**Ease-in-out**(慢-快-慢):两端慢,中间快。适合"位移"——角色从 A 走到 B,相机从镜头 A 切到镜头 B。视觉上像"自然运动"(有加速有减速)。

```rust
fn ease_in_out_cubic(t: f32) -> f32 {
    if t < 0.5 {
        4.0 * t * t * t
    } else {
        1.0 - (-2.0 * t + 2.0).powi(3) / 2.0
    }
}
```

记住一条规则:**线性是 fallback,任何反馈都该用 ease**。哪怕只是"血条数字从 30 滚到 12",也应该用 ease-out 让数字快速掉到 14 然后慢慢减速到 12,而不是匀速滚动。

### 6.2 把 easing 接到反馈系统

我们写一个最朴素的 tween 系统:

```rust
/// 一个 tween:把一个 f32 从 from 缓动到 to,经过 duration 秒
pub struct Tween {
    from: f32,
    to: f32,
    elapsed: f32,
    duration: f32,
    easing: Easing,
}

enum Easing {
    Linear,
    EaseOutCubic,
    EaseInOutCubic,
    EaseOutBack,  // 带 overshoot 的 ease-out,适合"弹一下停住"
}

impl Tween {
    pub fn new(from: f32, to: f32, duration: f32, easing: Easing) -> Self {
        Self { from, to, elapsed: 0.0, duration, easing }
    }

    /// 返回 (current_value, finished)
    pub fn update(&mut self, dt: f32) -> (f32, bool) {
        self.elapsed += dt;
        let raw_t = (self.elapsed / self.duration).clamp(0.0, 1.0);
        let eased_t = match self.easing {
            Easing::Linear => raw_t,
            Easing::EaseOutCubic => 1.0 - (1.0 - raw_t).powi(3),
            Easing::EaseInOutCubic => {
                if raw_t < 0.5 { 4.0 * raw_t.powi(3) }
                else { 1.0 - (-2.0 * raw_t + 2.0).powi(3) / 2.0 }
            }
            Easing::EaseOutBack => {
                let c1 = 1.70158;
                let c3 = c1 + 1.0;
                1.0 + c3 * (raw_t - 1.0).powi(3) + c1 * (raw_t - 1.0).powi(2)
            }
        };
        let value = self.from + (self.to - self.from) * eased_t;
        (value, self.elapsed >= self.duration)
    }
}
```

**EaseOutBack** 是反馈层的明星——它在结尾会**略微超过目标再回来**(overshoot)。一个 UI 按钮被点击时,用 ease-out-back 让它先缩到 0.9 再"弹回" 1.05 再到 1.0,这一个 overshoot 让按钮看起来"被按了真的有反应"。同样的曲线用在血条、伤害数字、菜单弹出上,瞬间提升手感。

### 6.3 缓动曲线和样条的关系

缓动函数本质上是一个从 `[0,1] → [0,1]` 的标量曲线。这条曲线可以理解为**贝塞尔曲线(bezier curve)**在 x = y = 0 到 x = y = 1 区间的一个特殊解——CSS 的 `cubic-bezier(0.25, 0.1, 0.25, 1.0)` 就是直接定义两个控制点构造一条三次贝塞尔作为缓动曲线。

这个连接点很重要,因为它意味着缓动不是孤立的"魔法函数",而是样条数学(spline math)的一个实例。我们在 phase-2 的 spline-math(easing curves)里详细讲了贝塞尔曲线的数学,这里的缓动只是它在"输入输出都是 [0,1]"上的一个特例。如果你想自定义一条缓动曲线,只要在 editor 里画一条从 (0,0) 单调递增到 (1,1) 的贝塞尔,就可以作为新的缓动函数。**Unity 的 Animation Curve、Unreal 的 CurveFloat、CSS 的 cubic-bezier 全是这个思路**。

理解了这一点,你就可以做"非对称缓动"——比如一个 UI 弹窗用 ease-out-back 进入(快、带 overshoot),用 ease-in-cubic 退出(慢进、果断出),两种缓动不对称,符合"进入要活泼、退出要干脆"的心理预期。

### 6.4 实战:用 tween 替换所有线性动画

把你的 HH 项目里所有"线性渐变"过一遍,问自己:这个能不能用 ease?答案几乎永远是"能"。最常见的几处:

- **HP 条**:从 30 到 12,用 ease-out,300ms。先快后慢,玩家看到血"哗"地掉一大截再慢慢停。
- **伤害数字浮字**:数字从命中点上浮 50 像素然后消失,移动用 ease-out,透明度用 ease-in(后半段才淡出)。
- **UI 菜单弹出**:缩放从 0.8 到 1.0,用 ease-out-back,200ms,让菜单"弹进来"。
- **摄像机切换**(见 game-feel-02):用 ease-in-out 切换镜头位置,200-400ms。
- **拾取物 magnet**(吸附效果):物品飞向玩家,初速度用 ease-in(慢慢加速),接近玩家时切换到 ease-out-back(冲过来撞一下停住)。

这一节的产出:**写一个 50 行的 Tween 系统,然后扫一遍你的 HH 代码,把所有 `from + (to - from) * (elapsed/duration)` 替换成 `Tween::new(from, to, dur, Easing::EaseOutCubic).update(dt)`**。这一改游戏手感立刻质变,而代码量几乎不变。

## 7 · 节制的纪律:为什么"juicy"的反义词是"messy"

讲到这里你可能已经摩拳擦掌,准备把所有反馈都开到最大。**先停一下**。这是反馈层最容易翻车的地方。

### 7.1 Juice 是调味料,不是主菜

Vlambeer 演讲的标题是 "The Art of **Screenshake**",不是 "The Art of **More Screenshake**"。Juice 是盐,不是肉。一道好菜需要盐,但你不会把整袋盐倒进锅里。同样的,反馈层需要 juice,但**不是每个瞬间都需要 juice**。

新手做 juice 最常见的失误:**给所有事件都加全套反馈**。挥剑砍空气也给 shake、给粒子、给 squash-stretch、给 hitstop。结果就是:屏幕每秒震 3 次,粒子漫天飞舞,所有物体都在不停挤压拉伸。玩 5 分钟,玩家前庭系统过载,要么关游戏,要么把 shake 在选项里关了(然后失去反馈层一半的价值)。

工业实践里,反馈层是**分层级**的:

**第一层是常驻反馈**——走路时脚部的小尘土、攻击时角色轻微的前倾、UI hover 时按钮的小放大。这些反馈**不需要** shake、不需要 hitstop、不需要 200 粒子。它们的存在是为了让世界"活着",不是为了传达"重大事件"。

**第二层是常规反馈**——普通攻击命中、被普通攻击命中、跳跃落地、拾取物品。这些事件配 1-2 种 juice:粒子爆发 + 一点 squash-stretch;或者一个短 shake + 小 hitstop(30ms)。**不要把所有 4 种都堆上去**。

**第三层是高潮反馈**——boss 倒下、必杀技释放、关卡通关。这种事件才配全套:大 shake(trauma 0.8)、长 hitstop(150ms+)、大量粒子(200+)、强力 squash-stretch(amount 0.3)、全屏白闪。**这些反馈之所以震撼,正是因为它们平时不出现**。

### 7.2 失真和贬值

反馈层的核心货币是**对比度**。一次重击之所以震撼,是因为平时不重击。如果整个游戏都在重击,就没有"重击"这个概念了。这就像交响乐——如果整场演出都是 fortissimo(最强音),听众 5 分钟就耳鸣;正是因为大部分时间是 piano(弱),fortissimo 出现时才有冲击力。

把这个原则翻译到反馈层:

- Hitstop 的"重"建立在平时"不冻"的对比上。给所有事件都加 hitstop,hitstop 就贬值了。
- Screenshake 的"震"建立在平时画面稳定的对比上。给走路都加 shake,玩家就分辨不出 boss 大招的震了。
- 粒子的"多"建立在平时粒子稀疏的对比上。每次命中都 200 粒子,真正爆炸的 500 粒子看起来也没差别。
- Squash-stretch 的"夸张"建立在平时姿态自然的对比上。每个动作都形变,玩家看不出哪个动作"特别"。

调参的经验法则是:**事件越普通,反馈越朴素;事件越罕见,反馈越夸张**。普通小怪的命中给 5 个火星 + 0.05 squash + 0 shake;精英怪的命中给 20 火星 + 0.15 squash + 0.2 trauma;boss 大招给 200 粒子 + 0.3 squash + 0.8 trauma + 100ms hitstop + 全屏闪。**这条单调递增的曲线就是反馈层的灵魂**。

### 7.3 测试方法:把所有反馈关到 0,再开到最大

工业化调试反馈层有一个非常有用的技巧:**先把所有 juice 的强度参数关到 0,玩 5 分钟,然后再开到最大,再玩 5 分钟,最后回到"中间值"再玩 5 分钟**。

第一步(全关)让你看到"裸游戏"是什么样——你会震惊地发现,没有 juice 的 HH 简直像 1990 年代的 shareware game,完全无法玩。这一步让你理解 juice 的**必要性**。

第二步(全开)让你看到"juice 过载"是什么样——你会震惊地发现,所有 juice 拉满的游戏像 2010 年代的免费手游广告,廉价、吵闹、令人疲惫。这一步让你理解 juice 的**危险性**。

第三步(回到中间)让你看到"克制 juice"是什么样——这是你的目标。这一步让你理解为什么"少即是多":一次普通的命中给一点点反馈,足以让玩家感受到"砍到了",但不至于让他每次都受惊。

把这三个状态录下来对比,你会对"反馈层的甜区在哪"有非常直观的理解。这个甜区不是某个具体数值,而是**事件之间反馈强度的比例关系**。

## 8 · 整体视角:反馈层不是孤岛

我们花了七节专讲反馈层内部。现在要回退一步,看反馈层在四部曲整体里的位置。

游戏手感是**整体涌现**的——输入、摄像机、反馈、音频四个部分各自都很简单,但组合在一起,**它们之间的协同效应**才是把技术 demo 变成"玩家热爱的游戏"的关键。一个 hitstop 单独做出来,玩家感受到的是"卡了一下";hitstop + screenshake + 粒子爆发 + 80Hz kick drum 同时触发,玩家感受到的是"妈的这一刀真重"。后者的总效应**远大于**部分之和。

四部曲的协同点:

**输入 → 反馈**:玩家按下攻击键的瞬间(< 50ms 内),剑应该开始挥动(animation 启动),刀光 trail 开始生成。这个"按下到看到动作"的延迟如果超过 100ms,玩家就觉得"卡"。反馈层的所有 juice 都建立在"输入已经响应"的基础上——如果输入响应本身慢,juice 也救不了。

**摄像机 → 反馈**:Hitstop 期间,摄像机如果**继续按惯性移动**会破坏冻结感——正确做法是 hitstop 期间摄像机也停。但 hitstop 结束的瞬间,摄像机应该有一个微小的"反弹"(spring overshoot),模拟"被冲击力推了一下"。这个细节是 The Last of Us、God of War 这些 TPS 的标准做法,看起来无关紧要,但少了它玩家会下意识觉得"hitstop 不对劲"。摄像机的 screenshake 接入我们在第 4 节讲过。

**反馈 → 音频**:这一层协同是 Vlambeer 演讲的核心。**没有音频的反馈,效果减半**。一个 hitstop + 粒子 + shake,如果配上合适的低频打击音,玩家的反应强度会是没音效时的 3-5 倍(神经科学上叫 multisensory integration——多个感官的信号在脑内被加权合成)。这部分我们留到 game-feel-04 详细讲,但你现在就要意识到:**反馈层的代码完成后,游戏还是"哑巴",真正的爽感必须等音频进来**。

理解了整体视角,你就明白为什么这一篇不写"完整的 juice 系统"——完整系统需要四个部分都到位。这一篇只负责反馈层的数据结构和算法,完整的"手感"是四部曲的总和。

## 9 · 在你 HH 项目里动手(做中学红线)

把这一篇落到代码,分四个步骤。每一步做完都先**自己玩 5 分钟感受**,再进下一步。

**步骤 1:加 Hitstop**。在你的 game state 里加一个 `Hitstop` 结构(第 2 节代码),主循环里 `tick` 它。在 `player_attack_hits_enemy` 那个事件里,调用 `hitstop.trigger(Duration::from_millis(80))`。运行游戏,砍一个史莱姆。你应该立刻感觉到"砍到了"。如果没感觉,把时长拉到 150ms 再试——这一下你应该明显感觉到了。然后把时长压回 60ms,这是甜区。

**步骤 2:加 Squash-Stretch**。给你的 `Player` 和 `Slime` 都加一个 `SquashStretch` 字段。在动画 update 里把它的 `scale` 应用到 transform。在落地事件里 `trigger(0.15, Vec2::new(0.0, 1.0))`,在命中事件里 `trigger(0.18, hit_normal)`。运行游戏,跳一次,你应该看到角色落地被压扁再弹回来。砍史莱姆,你应该看到史莱姆被推扁。stiffness 调到 200、damping 调到 12,这是好起点。

**步骤 3:加 Particle Burst**。复用你在 `particle-systems-cpu` 那一篇做的 `ParticleSystem`(没有的话先回去做)。在命中事件里 `spawn_sword_hit_sparks(...)`(第 5.1 节代码),数量 15-30。运行游戏,砍史莱姆。火星应该从命中点向法线方向溅出来,寿命 0.3 秒,颜色亮黄到暗红。这一步完成后,你的"砍史莱姆"已经有了 3 种 juice:hitstop、squash-stretch、粒子——这一刀已经感觉像真的砍到了。

**步骤 4:把所有参数做成 CVar**。在 `09B-4` 的 dev console 里注册以下 CVars:

```rust
cvars.register_f32("juice_hitstop_ms", 80.0);
cvars.register_f32("juice_squash_amount", 0.18);
cvars.register_f32("juice_squash_stiffness", 200.0);
cvars.register_f32("juice_squash_damping", 12.0);
cvars.register_f32("juice_shake_trauma", 0.3);
cvars.register_f32("juice_particle_count_mult", 1.0);
```

运行游戏,砍几次史莱姆建立基线感觉。然后**把所有参数拉到最大**——hitstop 500ms、squash amount 0.5、trauma 1.0、particle count mult 5。玩 1 分钟。你应该立刻感到"这游戏很烦,我想关 shake"。这就是 juice 过载的感觉,记住它。

然后**把所有参数压回 0**——hitstop 0、squash 0、trauma 0、particle count 0。玩 1 分钟。你应该感到"这游戏像 1995 年的 shareware,什么都没发生"。这就是 juice 缺失的感觉,也记住它。

最后**把参数调回中间值**——hitstop 80、squash 0.18、trauma 0.25、particle count mult 1.0。玩 5 分钟。这就是反馈层的甜区。把这几个数值 commit 到你的 CVar 默认值里。

**这一步完成后,你的 HH 项目里"砍史莱姆"已经从 Excel 表格变成了真正的游戏动作**。这个差别,就是 Vlambeer 反复强调的"商业游戏和业余游戏的分水岭"。

## 10 · 练习

**Lv 1**:把第 2 节的 `Hitstop` 接到主循环,触发时长改成 200ms,玩 30 秒。然后把时长改成 0,玩 30 秒。在 commit message 里写下你两种情况下"砍到史莱姆"的主观感受差别。

**Lv 2**:给 `SquashStretch` 加一个"面积严格守恒"模式——`scale_y = 1 / scale_x`(主轴)。把它和现有的"近似守恒"模式 `1 + amount` 对比,在 amount = 0.3 时观察两者视觉差异。哪种更对?为什么?

**Lv 3**:写一个 `ComboManager`,跟踪玩家连续命中的次数。每次连续命中,hitstop 时长 +5ms(封顶 150ms),粒子数 +5(封顶 80),screenshake trauma +0.05(封顶 0.8)。如果 1 秒内没有新命中,combo 重置。这是反馈层和"游戏逻辑"耦合的标准做法——combo 越高,反馈越强,玩家越爽。在 game-feel-04 里我们会继续讨论 combo 和音效音调的协同。

**Lv 4**(进阶):研究 Super Smash Bros 的 hitstop 机制(它在命中双方都冻结,但冻结时长不同——攻击者短、被攻击者长)。在你的 HH 里实现这个非对称 hitstop,讨论它和对称 hitstop 的手感差异。提示:这种非对称设计的目的是让"攻击者立刻能继续操作,被攻击者感受到停留",符合"主动方应该觉得利落,被动方应该觉得被命中"的心理预期。

## 11 · 延伸阅读与下一篇

外部稳定 URL:

- Vlambeer / Jan Willem Nijman, "The Art of Screenshake" (GDC 2013) — 反馈层的奠基演讲。YouTube 上有官方存档,搜 "The Art of Screenshake GDC" 即可。
- Squirrel Eiseroh, "Juice It or Lose It" (GDC Europe 2013) — screenshake trauma 平方曲线的源头,数学推导详细。
- Steve Swink, *Game Feel* (2009) — 反馈层的理论基础,从认知科学角度解释"为什么 juice 有效"。
- Disney, *The Illusion of Life* (1981) — 动画十二原则的原典,squash-stretch 是第一条。任何动画相关的工作者必读。
- Robert Penner, "Motion, Tweening, and Easing" (2001) — 缓动函数的工业标准,所有 easing 库(包括 CSS)都基于 Penner 的公式。 https://www.robertpenner.com/easing/
- easings.net — 缓动函数可视化速查,所有常见缓动的曲线和代码。 https://easings.net/

本仓库内交叉链接:

- `days/phase-3/deep-dives/particle-systems-cpu.md` — 本篇粒子爆发的底层系统,SoA 池、emitter 几何、billboard 渲染的完整实现。
- `days/phase-3/deep-dives/camera-systems.md` — screenshake 的宿主,spring 相机的物理。
- `days/phase-2/deep-dives/game-feel-short.md` — game feel 系列的简版总览,包含 spring 物理的入门。
- `game-feel-01`(输入响应) — 反馈层建立在输入响应之上,先读它。
- `game-feel-02`(摄像机) — screenshake 的算法和实现细节,本篇第 4 节基于它。
- `game-feel-04-audio-and-polish`(音频与收尾) — **下一篇**。反馈层完成后,音频是让它真正"爽"起来的最后一公里。我们会讲 hitstop 期间那个 80Hz kick drum 怎么合成、UI 点击音怎么和 squash-stretch 对齐、boss BGM 怎么随 combo 升调。完成 game-feel-04,你的 HH 项目就完成了完整的手感四部曲。
- `spline-math`(easing curves) — 第 6 节缓动函数背后的贝塞尔数学,自定义缓动从这里开始。
- `09B-4`(CVars 与开发控制台) — 第 9 步所有 juice 参数的实时调节都依赖它。
- `09B-1`(game loop) — 第 2 节 hitstop 接入主循环的位置。

反馈层不是"做完一关就完事"的功能,它是**贯穿整个开发周期需要反复打磨**的部分。每加一个新敌人、新武器、新场景,你都要回来问:这个事件的反馈强度在层级曲线上对吗?是不是又该重新跑一次"全关-全开-中间"的对比测试?这种持续打磨的态度,是把"能跑的 demo"打磨成"玩家会推荐给朋友的游戏"的真正工作。
