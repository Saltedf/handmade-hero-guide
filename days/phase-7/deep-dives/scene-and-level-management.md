
# 场景与关卡管理:加载、切换、加载界面、流式加载

> 你的 HH 项目现在能跑通一个关卡:一片地形、一个角色、几个 NPC、一阵背景音乐。`main.rs` 启动时一次性 `load_assets("world.hha")`,所有纹理、模型、音频、碰撞数据全塞进内存,然后 `game.run()` 进入主循环。在 demo 阶段这工作得很好——直到你想做一款真正的游戏。玩家从主菜单点"开始游戏"应该进入第一关;第一关打完应该进入第二关;第二关里玩家想暂停回到菜单。如果每次切换你都"清空一切,重新加载所有资产",玩家会盯着 10 秒黑屏发呆,然后退出游戏。更糟糕的是,你接下来想要一个开放世界——玩家在草原上往远处跑,远处的森林、村庄、怪物应该"长出来",而玩家身后的草原悄悄消失,内存占用却始终稳定。这两件事——多关卡切换,和开放世界无缝展开——表面上看毫无关系,实际上是同一个问题的两个尺度:**你如何把"游戏内容"作为一个可装载、可卸载、可在背景里悄悄替换的单元来管理?** 这就是**场景管理**(scene management)要回答的核心问题。这一篇从"场景到底是个什么东西"讲起,经过同步加载、异步加载、加载界面、过渡效果,一路讲到开放世界的 chunk streaming,把你 HH 项目从一个"单关卡 demo"升级成"多关卡 + 可选开放世界"的工业级骨架。读完之后,你应该能解释为什么加载界面比看上去复杂十倍、为什么 fade-to-black 不是一个纯图形特效而是一个调度手段、为什么 streaming 的难点不在 I/O 而在"什么时候把新东西整合进世界"。

## 0 · 一个让你想立刻重构的场景

把场景焊死,后面所有讨论都从这里长出来。你的 `main.rs` 大致长这样:

```rust
fn main() {
    let mut game = Game::new();
    game.world = load_world("level1.hha");   // 启动加载
    game.run();                              // 进循环,永不被打断
}
```

某个下午,你决定加一个主菜单。听起来很简单,你打算这么写——点开始按钮的时候,直接 `game.world = load_world("level1.hha")`。结果按下按钮的瞬间,屏幕冻住 8 秒,然后第一关突然蹦出来。这是**同步加载 + 无过渡**——能跑,但玩家会觉得游戏崩了。

你试第二种——按钮回调里开一个线程去加载,加载完发信号给主线程。立刻冒出一连串问题:加载期间画面应该画什么?菜单的渲染还在跑吗?如果菜单的纹理和 level1 的纹理同时驻留,内存够吗?什么时候卸载菜单的资产——加载 level1 之前还是之后?level1 加载完的瞬间,主线程要在一帧里"卸载菜单 + 安装 level1",这一帧会不会因为要做太多事而卡顿?如果玩家在加载途中按 Esc 想取消呢?

这还只是**两个关卡之间的切换**。一旦你想做开放世界——玩家在地图上自由跑动,远处的内容流式出现——问题的尺度放大十倍。一个 16 km² 的世界,如果整张图常驻内存,要 32GB;但你不可能让玩家在 32GB 的机器上玩你的游戏。你必须**只把玩家周围一小块常驻**,其余的按需加载、用完即卸。这又引出:怎么决定"周围一小块"的边界?玩家高速移动时,新的块来不及加载怎么办?新块加载好的瞬间,物理系统、AI 系统、渲染系统是不是都要看到一致的"世界"?

这一篇要把这些问题逐个拍平。核心思路是:**把"场景"作为游戏内容的可装载单元抽象出来**,围绕这个抽象建立加载、卸载、切换、流式更新的一整套机制。这条思路是 Unreal 的 `UWorld` / `ULevel`、Unity 的 `SceneManager`、Godot 的 `SceneTree`、Bevy 的 `States` 共同遵循的——名字不同,本质一致。

## 1 · "场景"到底是什么

在动手之前,我们要先把"场景"(scene)这个词的含义焊死。日常聊天里"场景"经常被混用——一会儿指一段关卡、一会儿指一帧画面的构图、一会儿指一段过场动画。这一篇里,**场景特指"游戏内容的一个可装载单元"**——它是关卡(level)、菜单(menu)、过场(cutscene)、结算屏(game over screen)这些"完整、独立、可单独打包"的内容块的统一抽象。

一个场景包含什么?至少四样东西。**第一,一组实体**(entities)——玩家、NPC、道具、触发器、相机,所有出现在场景里的"东西"。在 ECS 架构里(见 [phase-2/entity-system](../../phase-2/deep-dives/entity-system.md)),这就是一组 entity id 和它们的 component。**第二,一组资产引用**(assets)——场景里用到的纹理、模型、音频、动画的句柄,以及这些句柄的来源路径。注意:场景不直接持有资产的字节,它持有的是**资产的引用**(handle),真正的字节由 asset manager 统一管理(见 [asset-pipeline-architecture](asset-pipeline-architecture.md))。**第三,场景配置**(config)——天空盒颜色、雾参数、重力方向、玩家出生点、关卡脚本钩子、BGM 是哪一首。**第四,可选的依赖清单**——这个场景需要哪些其他场景或资产先就位(比如"Boss 房"场景依赖"通用敌人"资产包)。

把这四样东西打包,就是一个场景的最小定义:

```rust
pub struct Scene {
    pub name:         String,                  // "level1" / "menu" / "boss_fight"
    pub entities:     Vec<EntitySpawn>,        // 待实例化的实体描述
    pub assets:       Vec<AssetRef>,           // 场景引用的所有资产
    pub sky:          SkyConfig,
    pub gravity:      Vec3,
    pub player_spawn: Vec3,
    pub bgm:          Option<AssetHandle>,
    pub dependencies: Vec<String>,             // 依赖的其他场景/资产包名
}

pub struct EntitySpawn {
    pub prefab:  AssetHandle,                  // 预制体(纹理+模型+碰撞的集合)
    pub position: Vec3,
    pub rotation: Quat,
}

pub struct AssetRef {
    pub path:   String,
    pub kind:   AssetKind,
    pub handle: Option<AssetHandle>,           // 加载完后填上
}
```

几个关键设计点要说清楚。

`entities` 里存的是**实体描述**(`EntitySpawn`),不是已经实例化的 entity。这是因为场景在被加载到内存之前,只是磁盘上一份描述(类似 glTF 场景文件、Unreal 的 `.umap`、Unity 的 `.unity`),它说"在这个位置生成一只那样的怪"。**真正生成 entity 是场景加载完毕、要"激活"那一刻做的事**——这样设计的好处是,你可以把场景加载和场景激活解耦:先在后台把所有资产读进内存(慢、可异步),激活时只是按描述把 entity 加进 ECS 世界(快、必须同步)。这两步分开是后面"加载界面"那套架构能成立的关键。

`assets` 是一个**引用列表**,场景通过它告诉 asset manager "我需要这些资产"。asset manager 自己有引用计数(见 [asset-pipeline-architecture](asset-pipeline-architecture.md) 第 4 节),场景 activate 时增加引用,deactivate 时减少引用。多个场景共享同一个资产(比如所有关卡都用同一张玩家纹理)时,asset manager 只加载一次,引用计数 > 1 就不卸载。最后强调一个观念:**场景是"加载 / 卸载"的单元,不是"渲染"的单元**。渲染系统每帧画的是当前 ECS 世界里的所有可见 entity,它根本不关心这些 entity 来自哪个场景。场景的存在是为了让人(策划、关卡设计师)和机器(I/O 系统、内存系统)有个共同的"打包 / 调度"粒度。把这个观念焊死,后面所有设计就顺了。

## 2 · 场景加载的三种策略

有了"场景"这个抽象,我们可以谈"怎么把它弄进运行时"。历史上有三种典型策略,从简单到复杂、从割裂到无缝,**每一种都用复杂度换流畅度**。

**策略一:同步加载**(synchronous load)。这是新手默认会写出来的方案——主线程 `load_scene("level2")`,函数读磁盘、解析、生成 entity、返回;调用返回前,游戏循环冻住。它就是引子里那个 8 秒冻屏的版本。优点是**简单到一目了然**:加载期间世界状态不变,没有并发问题,内存管理最朴素。缺点是**体验灾难**——任何超过 200ms 的冻屏都会让玩家以为游戏崩了。同步加载的实际应用场景只有两个:**启动时的初次加载**(玩家预期等一下),和**极小的场景切换**(< 50ms 玩家察觉不到)。除此之外,只要场景切换可能 > 200ms,就必须避开同步加载。

**策略二:异步加载 + 加载界面**(async load with loading screen)。这是 1990 年代后期到现在的工业标准。基本套路是:主线程检测到要切场景,立刻进入"加载界面模式"——后台线程加载新场景的所有资产,主线程每帧从完成队列收一点进度刷新进度条,等所有资产就绪,原子地把新场景激活、卸载旧场景、退出加载界面模式。**整个过程中,主线程一直在跑、一直在渲染,只是渲染的是 loading screen 而不是游戏世界**。玩家看到一个流畅的加载界面,不会以为游戏崩了。加载完成后,通常还配一个过渡动画(fade to black、dissolve),让"loading screen → 新场景"这一跳不那么生硬。这套方案的代价是:**你必须把"渲染 loading screen 的路径"和"渲染游戏世界的路径"分开**,因为加载期间游戏世界的一部分资产正在被替换。这个"最小渲染路径"是加载界面架构的灵魂,下一节专门讲。

**策略三:流式加载**(streaming)。这是开放世界游戏的方案——根本没有"加载"和"游戏"两个明确分开的阶段,**整个游戏过程中世界都在持续地加载一小块、卸载一小块**。玩家在地图上跑,他周围"加载半径"内的 chunk 持续保持就绪,身后的 chunk 持续被驱逐。玩家感受不到任何加载过程。流式加载是这一篇后半段的重头戏,它和 [async-io-and-streaming](../../phase-4/deep-dives/async-io-and-streaming.md) 第 7 节的 chunk streaming 直接对接——那一篇讲了底层 I/O 怎么把 chunk 异步读进来,这一篇讲 chunk 进了内存之后**怎么和场景管理系统协作、什么时候整合进 ECS 世界、什么时候驱逐**。

这三种策略不是互斥的——一个真实的游戏往往同时用三种。启动时同步加载主菜单(快、小);点开始游戏时异步加载第一关并显示 loading screen;第一关里有一个超大户外区域用流式加载。**用什么策略,取决于"切换时机对玩家有多敏感"和"切换的内容有多大"**。

## 3 · 同步加载:把它写对,然后只在启动用

同步加载看起来不需要教——不就是 `load_scene()` 阻塞返回嘛。但**写对一个不卡的同步加载**,有几个细节比直觉微妙。

第一,**先卸载再加载,还是先加载再卸载**?直觉是先卸载旧的(释放内存),再加载新的。但这意味着**内存峰值是旧场景 + 新场景同时存在那一瞬间**——如果旧场景 1GB、新场景 1GB、机器只有 1.5GB,你的进程会被 OOM kill。**职业做法是流水线化**:在主线程逐项卸载旧场景的同时,**I/O 线程已经开始预读新场景的资产**(因为 I/O 是异步的,卸载期间磁盘在动)。等卸载完,I/O 大概也读了一半,剩下的加载时间减半。

第二,**卸载顺序很重要**。一个 entity 引用着纹理、模型、动画、脚本;你不能先 free 纹理再删 entity,那 entity 在删除过程中可能访问已释放纹理。**正确的顺序是:先停所有引用资产的系统,再删 entity,最后才 free 资产**。这看起来像废话,但它是导致"加载关卡时随机 crash"的常见根因——尤其在 ECS 里,某个 system 还在遍历 component,你突然把 component 删了,iterator 失效。

第三,**激活时机**。新场景的 entity 全部生成之后,还不能立刻让玩家操作——物理系统要做一次 broadphase rebuild、AI 系统要做一次 navmesh 查询、动画系统要从第 0 帧开始播放。**职业做法是分阶段激活**:先激活渲染(玩家看到画面)、再激活物理、最后激活 AI。中间的几十 ms 玩家会看到一个"静止的世界",但只要 < 100ms 通常感知不到。

```rust
pub fn load_scene_sync(world: &mut World, assets: &mut AssetManager, path: &str) {
    // 0. 停所有引用资产的系统(避免 iterator 失效)
    world.suspend_systems(&[SystemKind::Ai, SystemKind::Physics, SystemKind::Animation]);
    // 1. 卸载当前场景的 entity(资产引用计数 -1)
    world.clear_entities();
    // 2. asset manager 把引用计数归零的资产真正 free
    assets.gc_unused();
    // 3. 解析新场景描述
    let desc: SceneDesc = assets.read_scene(path);
    // 4. 同步加载所有资产(I/O 线程可提前 prefetch)
    for asset_ref in &desc.assets {
        let handle = assets.load_sync(&asset_ref.path, asset_ref.kind);
        asset_ref.handle.set(handle);
    }
    // 5. 激活场景 —— 生成 entity
    for spawn in &desc.entities { world.spawn_entity(spawn); }
    // 6. 分阶段恢复系统
    world.resume_system(SystemKind::Physics);
    world.physics.rebuild_broadphase();
    world.resume_system(SystemKind::Ai);
    world.resume_system(SystemKind::Animation);
}
```

每段注释对应前面讲的细节:`suspend_systems` 保证卸载期间不会被系统访问、`clear_entities` + `gc_unused` 是先删 entity 后 free 资产的顺序、`rebuild_broadphase` 是激活时的启动开销。**这套同步加载的代码你只应该在两个地方用:启动时的初始场景、以及加载界面背后的"实际加载动作"**。后一种情况——loading screen 模式下,主线程冻结游戏世界的更新,但仍在渲染 loading 界面;真正的场景加载是用同步代码跑的,只不过跑这段代码时玩家看到的是 loading 界面而不是冻屏。**这就是为什么同步加载的"对版本"依然重要——它是异步加载的内部实现**。

## 4 · 异步加载 + 加载界面:最小渲染路径

现在到了真正有意思的部分。我们要做的是:**主线程在加载期间持续渲染 loading screen,后台线程把新场景的资产慢慢读进内存**。听起来简单,做对有几个反直觉的点。

**第一个反直觉点:加载期间你仍然要渲染,但你渲染的不是游戏世界**。游戏世界的渲染需要所有纹理、模型、shader 就位,而这些正在被替换。所以你要有一条**完全独立的、最小化的渲染路径**,专门画 loading screen——它需要的资产(loading 背景图、进度条贴图、字体、可能的 BGM)在游戏启动时就预加载,永远常驻,不被场景切换触及。这条最小渲染路径不依赖 ECS 世界、不依赖当前场景、不依赖任何会被卸载的资产。

```rust
pub struct LoadingScreenRenderer {
    bg_texture:  AssetHandle,        // 启动时加载,永不卸载
    bar_texture: AssetHandle,
    font:        AssetHandle,
    progress:    f32,                 // 0.0 .. 1.0
    tip_text:    String,
}

impl LoadingScreenRenderer {
    pub fn render(&self, renderer: &mut Renderer) {
        renderer.draw_fullscreen_quad(self.bg_texture);
        renderer.draw_progress_bar(self.bar_texture, self.progress);
        renderer.draw_text(&self.tip_text, self.font, (100, 700));
    }
}
```

这套渲染路径**轻量到极致**——一次 fullscreen quad、一个进度条、几行字,十几微秒搞定一帧。它给主线程留出大量时间去做"收加载完成事件、刷新进度条、整合 ready 的资产"。

**第二个反直觉点:加载期间主线程不是"无所事事地等"**,它每帧都在干活。每帧主线程做四件事:一,从 I/O 完成队列 drain 一批完成事件(见 [async-io-and-streaming](../../phase-4/deep-dives/async-io-and-streaming.md) 第 2 节的 `IoBridge`);二,把已就绪的资产上传 GPU(这一步必须在主线程或渲染线程做);三,更新 progress;四,渲染 loading screen。**这四件事的总耗时必须 < 一帧的预算**,否则 loading 期间会掉帧、loading 动画会卡。

**第三个反直觉点:资产在后台线程读,GPU 上传在主线程**。这是因为 OpenGL / Vulkan / D3D 的 command buffer 提交有 context 限制。后台线程把磁盘字节读进内存、解码成像素数组,然后通过完成队列把"已解码像素"塞回主线程;主线程拿到像素后调 `renderer.upload_texture()` 推到 GPU。这个"读在 worker、上传在主"的分工是 [async-io-and-streaming](../../phase-4/deep-dives/async-io-and-streaming.md) 第 2 节强调过的关键约束。

```rust
pub enum GameMode {
    Playing { current: SceneHandle },
    LoadingScreen {
        target:    SceneHandle,
        pending:   HashMap<u64, AssetRef>,     // tag -> 待加载资产
        loaded:    u32,
        total:     u32,
        renderer:  LoadingScreenRenderer,
    },
}

pub fn frame(game: &mut Game, dt: f32) {
    match &mut game.mode {
        GameMode::Playing { current } => {
            game.world.update(dt);
            game.renderer.render_world(&game.world, current);
        }
        GameMode::LoadingScreen { target, pending, loaded, total, renderer } => {
            // 1. 收完成事件
            let mut done = Vec::new();
            game.io.drain_results(&mut done);
            for r in done {
                if let Some(asset_ref) = pending.remove(&r.tag) {
                    let handle = game.renderer.upload(&r.bytes, asset_ref.kind);  // 主线程上传
                    asset_ref.handle.set(handle);
                    *loaded += 1;
                }
            }
            // 2. 更新进度(可加平滑)
            renderer.progress = *loaded as f32 / *total as f32;
            // 3. 渲染 loading screen(始终渲染)
            renderer.render(&mut game.renderer);
            // 4. 全部加载完 → 进入过渡(见下一节)
            if pending.is_empty() { /* 启动 fade-to-black */ }
        }
    }
}
```

**进度反馈**(progress feedback)是 loading screen 一个被低估的细节。一个粗暴的进度条(0% 直接跳到 100%)会让玩家觉得游戏卡了。职业做法是:进度按"字节数"加权、加上轻微的平滑(`progress = lerp(progress, raw, 0.1)`),并在最后 5% 故意停一下(等真正激活场景)。**这套方案不卡帧的核心,是主循环依然是单线程**(game thread),它每帧根据当前 mode 分支处理;**I/O 线程在另一个核上跑**,通过队列和它通信。

最后讲讲**线程拓扑**。最简单的拓扑是两个线程:主线程(game + 渲染 loading screen)+ 一个 I/O 线程。职业引擎会用 worker pool(N 个 I/O 线程并行加载多个资产),但**主线程仍然只有一个**——它负责 drain、上传、渲染。如果你把渲染单独放一个线程(render thread),拓扑变成三个:game thread、render thread、I/O worker pool。这种三线程拓扑是 console 引擎的标配,见 [threading-journey](../../phase-5/deep-dives/threading-journey.md)。

## 5 · 过渡效果:为什么 fade-to-black 是调度手段

到这里,你的 loading screen 已经能用了。但还有一个细节——**loading screen 怎么"消失",新场景怎么"出现"**?最粗暴的做法是瞬间切换——loading screen 消失,第一关蹦出来。这个"瞬间"对玩家的视觉冲击其实很大,因为 loading screen 的色彩、明度和第一关完全不同,人眼会感到一闪。**这就是过渡效果(transitions)存在的理由**:用一段短暂的视觉过渡(fade、dissolve、wipe)掩盖场景切换的生硬。

最常见的过渡是**淡入淡出**(fade to black / fade from black):loading 完成后,先在 loading screen 上叠一层渐渐变黑的全屏 quad(alpha 从 0 到 1,几百 ms),完全黑屏的那一刻**原子地切换底层场景**,然后从黑屏渐渐淡出。整个过程中,玩家看到的只是"画面慢慢变黑,再慢慢亮起来,亮起来时已经是新场景"——切换被黑屏完美掩盖。

这里有一个**关键的调度意义被忽视**:fade-to-black 不只是视觉效果,它给引擎**争取了几百 ms 的"无视觉监督"时间窗**——在这段时间里,画面是完全黑的,玩家什么也看不见。引擎可以**在这段时间窗里做那些"耗时但不能让玩家看见"的事**:卸载旧场景的所有资产(GPU 资源销毁,某些驱动会同步等 GPU idle,几十 ms)、激活新场景的所有 entity(rebuild broadphase、查询 navmesh、初始化脚本,几十到几百 ms)、预编译 shader。**这些事如果在 loading screen 完成后立刻做,玩家会看到"loading 100% → 卡 500ms → 新场景蹦出"**;放在 fade-to-black 的黑屏时间里做,玩家看到的是"loading 100% → 渐渐变黑 → 渐渐变亮(已经是新场景)",**完全无感**。

```rust
pub struct Transition {
    pub phase:     TransitionPhase,
    pub elapsed:   f32,
    pub duration:  f32,                 // 单向 fade 的时长,典型 0.4s
    pub swap_done: bool,
}

pub enum TransitionPhase { FadeOut, Black, FadeIn }

impl Transition {
    pub fn update(&mut self, dt: f32, swap_fn: &mut dyn FnMut()) -> f32 {
        self.elapsed += dt;
        match self.phase {
            TransitionPhase::FadeOut => {
                let t = (self.elapsed / self.duration).min(1.0);
                if t >= 1.0 { self.phase = TransitionPhase::Black; self.elapsed = 0.0; }
                t
            }
            TransitionPhase::Black => {
                if !self.swap_done {
                    swap_fn();              // 在玩家完全看不见时执行重活
                    self.swap_done = true;
                }
                if self.elapsed > 0.2 { self.phase = TransitionPhase::FadeIn; self.elapsed = 0.0; }
                1.0
            }
            TransitionPhase::FadeIn => {
                let t = (self.elapsed / self.duration).min(1.0);
                1.0 - t
            }
        }
    }
}
```

注意 `Black` 阶段里的 `swap_fn()`——这是真正的场景切换动作(卸载旧场景 + 激活新场景),它在玩家**完全看不见**的时候执行。这段代码也是为什么过渡效果应该和 cutscene / timeline 系统**共享同一套机制**(见 [cutscene-and-timeline](cutscene-and-timeline.md))——本质上 fade-to-black 就是一段 1.0 秒的 scripted sequence。

dissolve(溶解)过渡比 fade 复杂——它需要两幅画面同时叠加渲染,这意味着**新场景和旧场景的资产要同时驻留一会儿**,内存峰值更高。fade-to-black 不需要这种同时驻留(因为中间有黑屏分隔),所以**对内存压力更友好**——这也是为什么大多数游戏用 fade 而不是 dissolve。

## 6 · 流式加载:把世界切成 chunk

现在进入重头戏——开放世界的场景管理。前面五种场景处理的是"离散的、玩家触发的"切换,流式加载处理的是"连续的、玩家移动驱动的"切换。本质区别在于:**离散切换有明确的"加载阶段"和"游戏阶段"分离,流式加载则永远没有"加载阶段",加载和游戏交织在一起**。

流式加载的核心架构在 [async-io-and-streaming](../../phase-4/deep-dives/async-io-and-streaming.md) 第 7 节已经讲了底层——把世界切成 chunk、根据玩家位置预测要哪些 chunk、用 `Streamer` 控制器请求和驱逐。这一节聚焦在**场景管理层**——chunk 进了内存之后怎么和 ECS 世界协作。

第一个问题:**chunk 在场景管理里是什么角色**?最直接的答案是,**每个 chunk 就是一个"迷你场景"**(mini-scene)——它有自己的 entity 描述(这块地形上的树、石头、NPC)、自己的资产引用、自己的配置。整个开放世界是几千个 chunk 场景的集合,玩家周围常驻 100 多个,其余的在磁盘上。**所以 streaming 本质上是"同时管理几百个迷你场景的并发加载 / 卸载"**——这就是为什么它的复杂度远超单关卡切换。

第二个问题:**新 chunk 加载好了,什么时候整合进 ECS 世界**?直觉是"加载好就立刻整合",但这是**灾难性的错误**。假设物理系统这帧的 step 已经跑了一半,你突然塞进一群新 entity,物理系统 iterator 失效、碰撞结果错误,可能直接 crash。**职业做法是 frame boundary integration**:所有"加载好的 chunk"先暂存在一个 staging buffer,每帧末尾(所有 system 都跑完之后、渲染之前)的某个固定时机,**原子地**把 staging buffer 里所有 chunk 整合进 ECS。这一帧的所有 system 看到的世界状态是一致的。这和 [09B-1 游戏循环与固定步长](../../phase-9/09B-1-game-loop-and-timestep.md) 里讲的"frame boundary 是状态变更的安全点"同源,也和 event-systems 里"event 在帧末尾统一 dispatch"的思路一致。

第三个问题:**整合的"原子性"具体怎么做**?最务实的方案是:**streaming 整合就在主线程做,作为帧末尾的一个固定 step**。这一步的工作量被严格控制——一帧最多整合 N 个 chunk(N 是预算,典型 2-4)。如果 staging buffer 里有 50 个待整合 chunk(玩家刚传送),分 25 帧慢慢整合,每帧整合 2 个。**这就是为什么 streaming 的 pop-in 是分帧"长出来"的**——50 个 chunk 不会同时蹦出来,而是一帧长 2 个,25 帧长完。pop-in 的视觉效果可以靠 LOD 和距离遮挡缓解,但"分帧预算化整合"是底线,不能破。

```rust
pub struct ChunkStreamer {
    staging:          Vec<ChunkIntegrate>,          // 已就绪、待整合(来自 I/O 线程)
    loaded:           HashMap<ChunkId, ChunkEntity>, // 当前 ECS 里的 chunk
    integrate_budget: usize,                         // 每帧最多整合几个
    io:               Arc<IoBridge>,
    load_radius:      f32,                           // 典型 200m
    keep_radius:      f32,                           // 典型 500m
}

pub struct ChunkIntegrate {
    pub id:      ChunkId,
    pub spawns:  Vec<EntitySpawn>,
    pub handles: Vec<AssetHandle>,
}

impl ChunkStreamer {
    pub fn update(&mut self, world: &mut World, assets: &mut AssetManager,
                  player_pos: Vec3, player_vel: Vec3) {
        // 1. drain I/O 完成事件 → staging
        let mut done = Vec::new();
        self.io.drain_results(&mut done);
        for r in done { self.staging.push(decode_chunk(&r.bytes)); }

        // 2. 预测玩家位置、请求新 chunk(详见 async-io-and-streaming 第 7 节)
        let future = player_pos + player_vel * 1.0;
        for chunk in chunks_in_radius(future, self.load_radius) {
            if !self.loaded.contains_key(&chunk) && !self.is_pending(chunk) {
                let tag = self.io.request(Kind::Chunk, chunk_path(&chunk));
                self.mark_pending(tag, chunk);
            }
        }

        // 3. 帧边界整合,遵守预算
        let mut integrated = 0;
        self.staging.retain(|ci| {
            if integrated >= self.integrate_budget { return true; }
            let mut ents = Vec::new();
            for spawn in &ci.spawns { ents.push(world.spawn_entity(spawn)); }
            self.loaded.insert(ci.id, ChunkEntity { entities: ents, handles: ci.handles.clone() });
            integrated += 1;
            false
        });

        // 4. 驱逐 keep 半径外的 chunk(顺序:先删 entity,后 dec-ref 资产)
        let keep: HashSet<ChunkId> = chunks_in_radius(player_pos, self.keep_radius).into_iter().collect();
        let to_unload: Vec<ChunkId> = self.loaded.keys()
            .filter(|id| !keep.contains(id)).copied().collect();
        for id in to_unload {
            if let Some(ce) = self.loaded.remove(&id) {
                for eid in ce.entities { world.despawn_entity(eid); }
                for h in ce.handles    { assets.dec_ref(h); }
            }
        }
    }
}
```

注意第 3 步的 `integrate_budget`——它是这一架构的"防卡顿保险丝"。即便玩家传送到一个全新区域、瞬间有 200 个 chunk 要加载,主线程每帧只整合 2-4 个,200 / 3 ≈ 67 帧 ≈ 1.1 秒长完。**这一秒里玩家看到世界慢慢"长出来",而不是卡死一秒后整个蹦出**——这就是 streaming 体验的全部精髓。驱逐(第 4 步)也要注意顺序——**先删 entity 后 dec-ref 资产**,和同步加载的卸载顺序一致。

## 7 · 流式加载的内存预算

streaming 有一个常被新手忽视、实际上是架构灵魂的约束:**内存预算**(memory budget)。你不能把整个开放世界塞进内存——一个 16 km² 的世界,完整内容可能 32GB;玩家的机器只有 16GB。**所以 streaming 的本质是"用一个滑动窗口在巨大内容上滑动",窗口的大小由内存预算决定**。

具体怎么算?假设 chunk 是 64m × 64m,每 chunk 完整资产 8MB。加载半径 200m → loaded chunk 数 ≈ π × 200² / 64² ≈ 30 个,占内存 240MB——可接受。加载半径 500m → 192 个,1.5GB——还能接受。调到 1km → 770 个,6GB——开始紧张。调到 2km,3TB——爆炸。**所以加载半径不是"想看多远就能看多远",而是被内存预算反向决定的**。给定预算(比如 2GB 给 streaming),你能支持的加载半径是 sqrt(2GB / 8MB × 64² / π) ≈ 360m。再要让玩家看得更远,只能靠减小 chunk 的内存占用(更激进的压缩、LOD)、或者让远处的 chunk 用更低的精度(mip streaming,远处只加载低 mip,内存占用 1/16)。

预算化还有一个**不那么明显的运用**:I/O 带宽也是预算。NVMe 标称 7 GB/s,实际游戏场景下能稳定拿到 2 GB/s 就不错了。每秒能加载的 chunk 数 = 2 GB/s / 8MB = 250 个。玩家骑马以 30 m/s 飞奔,每秒新进入加载半径的 chunk 数 ≈ 9 个,毫无压力。问题出在**传送**(fast travel)——玩家瞬间从地图一端到另一端,可能瞬间需要 200 个新 chunk,2 GB/s 加载完要 800ms,这段时间玩家站在一片"空地"上,看远处慢慢长出来。这就是为什么传送通常配一个 loading screen,本质上是用第 4 节的 loading screen 架构来掩盖 streaming 跟不上的瞬间。

内存预算化在代码层面的实现,是把 chunk 的内存池化——所有 chunk 共用一个 arena 或 pool,驱逐时整体回收。这避免了"频繁 alloc/free chunk 让 arena 出洞"的碎片化问题(见 [phase-0/24-memory-foundation](../../phase-0/24-memory-foundation.md) 的 pool 章节,以及 [memory-layout-for-cache](../../phase-4/deep-dives/memory-layout-for-cache.md))。最简单的做法是**固定容量的 LRU**:loaded chunk 数不超过 N(由预算算出),要加载新 chunk 时如果已满,先驱逐最久未访问的一个再加载。这个结构保证了内存占用恒定,非常适合 console 这种内存固定的平台。

```rust
pub struct ChunkPool {
    capacity: usize,                                  // 同时常驻上限(由预算算)
    loaded:   LinkedHashMap<ChunkId, ChunkEntity>,    // LRU 顺序
}

impl ChunkPool {
    pub fn try_reserve(&mut self, id: ChunkId) -> bool {
        if self.loaded.len() < self.capacity { return true; }
        if let Some((evict_id, _)) = self.loaded.pop_back() {  // 驱逐最久未访问
            self.evict(evict_id);
            return true;
        }
        false
    }
    pub fn touch(&mut self, id: ChunkId) {
        // 玩家进入这个 chunk,移到 LRU 前端,避免被驱逐
        if let Some(ce) = self.loaded.remove(&id) { self.loaded.push_front(id, ce); }
    }
}
```

`capacity` 是 streaming 系统的"内存阀门"。开机时根据机器内存动态算出(给总内存的 25% 给 streaming),让游戏在不同硬件上都跑得动——这是 Indie 游戏适配从 8GB 笔记本到 64GB 工作站的标准做法。

## 8 · 整合时序:streaming 不能让固定步长掉帧

把 `ChunkStreamer::update` 放到主循环里,正确的位置是**所有 step 跑完之后、渲染之前**:

```rust
pub fn game_loop(game: &mut Game) {
    let mut acc = 0.0;
    let fixed = 1.0 / 60.0;
    loop {
        let frame_start = instant::now();
        let dt = (frame_start - game.last_frame).min(0.25);
        game.last_frame = frame_start;
        acc += dt;

        // 跑所有固定步长 step(物理、AI、动画 —— 它们看不到 staging 里的 chunk)
        while acc >= fixed {
            game.world.step(fixed);
            acc -= fixed;
        }

        // ============ 帧 边 界 ============
        // 在这里整合 streaming,所有 step 已经跑完,世界状态稳定
        game.streamer.update(&mut game.world, &mut game.assets,
                             game.player.pos, game.player.vel);
        // ============ 帧 边 界 ============

        game.renderer.render(&game.world);   // 渲染看到的是整合后的世界
        sleep_until_next_frame(instant::now());
    }
}
```

注意 `world.step` 循环里**完全没有 streaming 相关的代码**——step 内的世界状态是冻结的,streamer 在所有 step 跑完之后才动世界。这就是"帧边界整合"的精确含义:**streaming 是帧级粒度的事件,不是 step 级粒度的**。

但还有一个更细的陷阱:**整合本身可能耗时长**。一帧整合 4 个 chunk,每个 chunk 平均 50 个 entity,生成 200 个 entity 加进 ECS 可能要 5-10ms。再加上驱逐若干个 chunk,可能再花 5ms。这两项加起来 10-15ms,**已经接近一帧的全部预算**。所以 `integrate_budget` 要谨慎调——在 [profiling-with-tracy](../../phase-4/deep-dives/profiling-with-tracy.md) 里量"整合 + 驱逐"的耗时,反算出每帧安全整合几个。**宁可让玩家多看几帧 pop-in,也不能让帧时间超过 17ms**——这是 [09B-1 游戏循环与固定步长](../../phase-9/09B-1-game-loop-and-timestep.md) 的合约,streaming 必须遵守。

最后强调一个和 audio 的交互:**audio 资产的 streaming 要提前 N 秒**。如果一个 chunk 里有 BGM 或环境音效,等到 chunk 整合进 ECS 才开始加载音频,玩家会先看到画面、几秒后才听到声音——这是非常糟糕的体验(见 [threading-journey](../../phase-5/deep-dives/threading-journey.md) 关于 audio 线程不能阻塞的讨论)。职业做法是**音频资产有更大的"预加载半径"**(比如 2 倍于普通 chunk 的加载半径),让 BGM 提前好几秒就开始流式准备。

## 9 · 在你 HH 项目里动手(做中学红线)

理论够了,落到你的 HH 项目。下面这一系列操作是这一篇**真正变成肌肉记忆**的最低红线。

**第 1 步:把单关卡抽象成 Scene**。看你 `main.rs` 启动时 `load_world` 那段代码——拆出来,封装成一个 `Scene` 结构和 `fn load_scene(path: &str) -> Scene`。这一步不改变行为,只改变组织。

**第 2 步:加一个第二场景**。做最简单的主菜单场景(一个 fullscreen quad + 一个"开始游戏"按钮),作为 `Scene::new("menu")`。让游戏启动时加载 menu 而不是 level1。

**第 3 步:实现同步切换 + 加载界面**。点"开始游戏",先实现最简单的同步切换,用 [profiling-with-tracy](../../phase-4/deep-dives/profiling-with-tracy.md) 量切换那一帧的 frame time——**它大概率会爆表**。然后实现真正的异步版本:进 loading screen 模式,后台 I/O 线程加载,主线程每帧 drain + 上传 + 刷新进度 + 渲染 loading 界面。再量一次——**loading 期间每帧稳定在 16ms 附近,完全无卡顿**。

**第 4 步:加 fade 过渡**。loading 完成后,做一段 fade-to-black + 切换 + fade-from-black。把切换动作放在黑屏阶段执行。

**第 5 步:实验 2D streaming grid**。如果你的 HH 有一个能走动的 2D 世界,切成 8×8 或 16×16 的 chunk。实现第 6 节那段 `ChunkStreamer`。把加载半径调小到能看见 pop-in(50m),再调大到完全感觉不到(200m+)。**亲眼看 pop-in 消失的过程,是这一节最有价值的体感**。

**第 6 步:加内存预算**。给 chunk pool 设容量(比如 50 个),让 LRU 自动驱逐。把容量调到极小(10 个)看世界多快消失;调到极大(500 个)看内存占用。

完成这六步,你的 HH 项目就具备了职业引擎场景管理层的雏形。

## 10 · 练习

### Lv1 · 概念辨析

题:为什么"loading screen 期间仍然渲染"是一个反直觉但必须的设计?如果 loading 期间完全不渲染(主线程 join I/O 线程后一起等加载完),会有什么问题?

参考解答:三个原因。第一,玩家会以为游戏崩了——任何超过 200ms 的画面冻结都会让玩家怀疑游戏卡死,loading screen 至少告诉玩家"在加载"。第二,主线程没在干活就是浪费 CPU——它能 drain I/O 完成事件、上传 GPU、刷新进度。第三,操作系统 / 桌面环境会认为"无响应"应用——Windows 的"程序无响应"提示、X11 / Wayland 的窗口变灰,都是因为主线程长时间不处理事件。

### Lv2 · 动手实践

题:在你的 HH 项目里实现第 4 节那段 `LoadingScreenRenderer` + `GameMode::LoadingScreen` 状态机。要求:点按钮触发 loading,loading 期间显示进度条(按"已加载资产数 / 总资产数"算),loading 完成自动切到目标场景。用 Tracy 量 loading 期间每帧 frame time,确认稳定在 16ms 附近。

提示:`GameMode` 的 enum 分支让主循环天然按状态分支处理——这是状态机模式在游戏主循环里的标准运用(见 [game-state-management](../../phase-2/deep-dives/game-state-management.md))。

### Lv3 · 迁移设计

题:Unreal 的 `OpenLevel` 和 Unity 的 `SceneManager.LoadScene` 都做了"异步加载 + loading screen"流程,但它们的 API 长得像"一行就切场景"。设计一个 Rust API,让用户写 `scenes.open("level2").with_loading_screen().with_fade(0.4).await` 就能完成所有事。它内部要做什么?

提示:builder pattern + async/await。`open()` 返回一个 `SceneLoadBuilder`,builder 方法配置选项,`.await` 真正触发。内部把状态推进到 `GameMode::LoadingScreen`,await 在一个 future 上,future 在 loading 完成时 resolve。注意游戏主循环不能 `await`(它会阻塞循环),所以这个 API 更适合编辑器 / 工具模式,运行时游戏要用回调或状态机驱动。

### Lv4 · 开放世界流式

题:在你的 HH 项目里实现第 6 节的 `ChunkStreamer` + 第 7 节的 `ChunkPool`。要求:玩家用 WASD 走动,chunk 按预测加载、按帧边界整合、按 LRU 驱逐。**做到玩家走动时没有任何 frame 超过 17ms**。把加载半径、整合预算、chunk pool 容量都做成可调参数,在游戏里实时调。

进阶:加一个"传送"功能(按 T 键瞬移到地图随机位置)。观察传送瞬间的 staging buffer 堆积,以及分帧整合让世界慢慢"长出来"的过程。**这一步是 streaming 体验最有教育意义的实验**——你会亲眼看到"瞬间需要 200 个 chunk"和"I/O 带宽有限"之间的张力。

## 11 · 延伸阅读

本仓库内关联资料:

- [asset-pipeline-architecture](asset-pipeline-architecture.md) —— 资产管线总览,场景里的资产引用最终都走这套管线
- [async-io-and-streaming](../../phase-4/deep-dives/async-io-and-streaming.md) —— chunk streaming 的底层 I/O,这一篇的场景管理层直接建立在它之上
- [game-state-management](../../phase-2/deep-dives/game-state-management.md) —— 游戏状态机,`GameMode::Playing` / `LoadingScreen` 是状态机的典型运用
- [phase-2/entity-system](../../phase-2/deep-dives/entity-system.md) —— ECS 基础,场景里的 entity 都活在 ECS 世界里
- [memory-layout-for-cache](../../phase-4/deep-dives/memory-layout-for-cache.md) —— chunk pool 的内存布局,streaming 的内存预算化基础
- [phase-0/24-memory-foundation](../../phase-0/24-memory-foundation.md) —— arena / pool 的内存模型
- [09B-1 游戏循环与固定步长](../../phase-9/09B-1-game-loop-and-timestep.md) —— 固定步长循环,streaming 整合必须遵守它的合约
- [threading-journey](../../phase-5/deep-dives/threading-journey.md) —— render thread / audio thread 拓扑,加载期间多线程协作的基础
- [cutscene-and-timeline](cutscene-and-timeline.md) —— 过渡效果本质上是一段 scripted sequence,和 cutscene 共享机制
- [savegame-and-serialization](../../phase-8/deep-dives/savegame-and-serialization.md) —— 存档系统,场景的"已激活状态"序列化存盘的入口
- [profiling-with-tracy](../../phase-4/deep-dives/profiling-with-tracy.md) —— 量 loading 期间 frame time、streaming 整合耗时的工具

外部稳定 URL:

- Unreal Engine `OpenLevel` 文档:https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/Engine/UGameplayStatics/OpenLevel
- Unity `SceneManager.LoadScene` 文档:https://docs.unity3d.com/ScriptReference/SceneManagement.SceneManager.LoadScene.html
- Godot SceneTree 文档:https://docs.godotengine.org/en/stable/classes/class_scenetree.html
- Bevy `States` 文档:https://docs.rs/bevy/latest/bevy/prelude/struct.States.html
- "Fix Your Timestep!"(固定步长循环详解):https://gafferongames.com/post/fix_your_timestep/
