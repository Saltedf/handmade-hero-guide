---
title: "高级角色动画:重定向、Morph Target、Root Motion、Two-Bone IK"
title_en: "Advanced Character Animation: Retargeting, Morph Targets, Root Motion, Two-Bone IK"
title_zh: "高级角色动画(重定向 / morph target / blend shape / root motion / two-bone IK)"
type: deep-dive
phase: 3
difficulty: 4
duration: 90
domains: [rust, graphics, game, math]
prereqs: ["skeletal-animation-fundamentals", "animation-blending-and-state-machine"]
calibration: "高级角色动画(重定向/morph target/blend shape/root motion/two-bone IK)"
---

# 高级角色动画:重定向、Morph Target、Root Motion、Two-Bone IK

> 你的角色终于会动了。前两篇你已经啃完了 [skeletal-animation-fundamentals](./skeletal-animation-fundamentals.md)(骨架、FK、蒙皮矩阵、LBS/DQS)和 [animation-blending-and-state-machine](./animation-blending-and-state-machine.md)(cross-fade、blend tree、additive、layer、HFSM、IK 三大算法)。你按那两篇的指引,把 walk clip 喂给你的主角,角色迈步、摆臂,看起来像模像样。但还有四件事让你睡不着。第一,那个 walk clip 是美术在 Maya 里用一个 1.9 米高的男性 rig 录的,你的主角只有 1.5 米,手臂短一截——播出来胳膊在空中画圈、脚踩不到地面。第二,角色脸像一张死板的面具,不会笑不会皱眉,玩家完全感受不到情绪。第三,角色明明在播 walk,但脚在地上"滑冰"——脚掌和地面有相对位移,像在跑步机上倒腾,身体却没前进一米。第四,你想让角色的手去抓桌上的杯子,但 walk clip 里手在身体两侧晃,杯子在前方 30 厘米——手够不到。这四件事分别是**重定向(retargeting)**、**Morph Target / Blend Shape(变形目标)**、**Root Motion(根运动)**、**Two-Bone IK(双骨逆向运动学)**。它们是"播放剪辑"和"角色活起来"之间的全部距离。这一篇就把这四个技术讲透,每一个都给完整数学推导、可跑的 Rust 代码、生产坑、性能数据,最后接到你 HH 项目里——让角色真正"会动、会笑、走得稳、抓得到东西"。

## 0 · 当你的角色"看起来不对":四个让你崩溃的瞬间

你已经把前两篇啃得很熟。你的引擎能加载 glTF 骨架、采样动画剪辑、cross-fade、blend tree、additive layer、跑 Two-Bone IK 让脚贴地。你打开引擎,跑一个 demo。

第一个崩溃瞬间。你在 Sketchfab 上买了一个 walk 动画包,作者是按他自己那套 1.9 米高、肩宽 0.5 米的人形 rig 录的。你的主角是 1.5 米高、肩宽 0.35 米的精灵族角色。把那套 walk 喂给你的角色,你会看到:胳膊摆动幅度太大(因为原 rig 肩宽),手腕几乎甩到角色身体中线;胯部高度太低,角色膝盖一直是弯的;脚掌在每一帧都"穿过"地面 5 厘米(因为原 rig 腿更长,在 bind pose 时脚就在地面下)。这叫**重定向问题(retargeting problem)**——动画是按一套骨架的比例录的,你的骨架比例不一样,直接套就错位。

第二个崩溃瞬间。你的角色没有表情。眼睛瞪着前方,嘴是一条直线,无论剧情是悲伤还是愤怒,角色的脸纹丝不动。你尝试给脸上加骨骼——眉毛、嘴角、颧骨各加几根 bone,然后用 LBS 蒙皮驱动它们。结果是灾难:一个"微笑"涉及几十块面部肌肉的微小协同动作(颧大肌上提嘴角、眼轮匝肌微微收缩让眼角起皱、咬肌放松让下颌微张),用骨骼模拟这些细节是徒劳——你会得到一个看起来像中风的脸。这叫**面部动画问题**,工业界的答案叫 **Morph Target(变形目标)**,也叫 **Blend Shape(混合形状)**。

第三个崩溃瞬间。你的角色播 walk,迈腿、摆臂都对,但角色**身体不动**。原来你的游戏代码每帧根据玩家摇杆把角色平移一段距离,但 walk 动画的"前进速度"是美术录的——他可能录的是 1.5 m/s 的步速,而你的游戏代码平移速度是 3.0 m/s。结果角色脚在地面画圈(脚抬起时游戏代码已经把身体前移了 5 厘米,脚还在原地),像在跑步机上滑。玩家觉得"角色在飘"。这叫**脚滑(foot sliding)**,解决方案是 **Root Motion(根运动)**——让动画剪辑本身的"前进量"驱动角色移动,而不是让游戏代码硬平移。

第四个崩溃瞬间。你让角色去抓桌上的杯子,杯子位置是 runtime 才知道的(玩家拖动杯子)。你播一个"伸手"剪辑,但剪辑里手到达的位置是固定的——杯子挪到 5 厘米外,手就抓空了。前一篇学的 Two-Bone IK 给了"给定目标位置,反推肘腕角度"的解析解,但只是单独的 IK 求解,没告诉你**怎么把 IK 嵌入到动画管线里**,让 walk + IK + 抓取动作协同工作。这一篇会把 Two-Bone IK 接到完整的动画 pose pipeline 里——这是 [animation-blending-and-state-machine](./animation-blending-and-state-machine.md) §4.3 的延伸。

这四个技术**叠加**起来,才是工业级角色动画。一个 AAA 主角的最终 pose 是这样算出来的:

```
final_pose =
    retargeted_walk_clip                 // 1. 重定向到本角色骨架比例
    .apply_root_motion_to_character()    // 2. 根运动驱动角色位移
    .apply_two_bone_ik(foot_L, ground)   // 3. 左脚 IK 到地面
    .apply_two_bone_ik(foot_R, ground)   // 4. 右脚 IK 到地面
    .apply_two_bone_ik(hand_R, cup)      // 5. 右手 IK 到杯子
    .apply_morph_targets(face, [         // 6. 面部 morph target 混合
        ("smile", 0.8), ("blink_L", 0.2)
    ])
```

每一步都是一个独立的、可单测的算法。组合起来,角色才"活"。这一篇就讲这五个步骤的全部细节。

**学完这一篇,你应该能**:

- 解释 retargeting 为什么必须用"归一化空间",并能用 100 行 Rust 写出一个跨骨架重定向器
- 用白纸手推 morph target 的顶点 delta 公式,并能把它跟 LBS 蒙皮组合到同一个 vertex shader 里
- 解释 root motion 的两种使用模式(apply vs ignore),并知道什么时候选哪个
- 把 Two-Bone IK 嵌入到动画管线的"post-FK / pre-skinning"阶段,处理 world-space 到 local-space 的转换
- 看懂 Unreal AnimBP 的 IK 节点、Unity Animator 的 `OnAnimatorIK`、Godot 的 `SkeletonModifier3D`、OZZ 的 `IKTwoBoneJob`
- 在你 HH 项目里给主角加上完整的 retarget + root motion + IK + 表情系统

## 1 · Retargeting:让一套动画服务所有角色

### 1.1 问题到底是什么:比例错位

想象你手里有两个骨架。**骨架 A**(源,source)是美术录动画时用的 rig:1.9 米高,大腿骨 0.45 米,小腿骨 0.43 米,肩宽 0.5 米。**骨架 B**(目标,target)是你游戏的角色 rig:1.5 米高,大腿骨 0.36 米,小腿骨 0.34 米,肩宽 0.35 米。两个骨架**拓扑相同**(都是人形,joint 树结构一致),但**比例不同**。

动画师在 Maya 里给骨架 A 录了一个 walk:每一帧,每个 joint 都有一个 local transform(相对父 joint 的 TRS)。比如"大腿骨相对骨盆旋转 30 度"。这个旋转角度在骨架 A 上播放时,大腿往前摆得很自然。但把这个 local transform **原封不动**套到骨架 B 上会发生什么?

**旋转部分没问题**。30 度就是 30 度,旋转是角度量,跟 bone 长度无关。所以大腿摆动方向是对的。

**平移部分出大问题**。骨架 B 的大腿骨长度是 0.36 米,但骨架 B 的"骨盆 → 大腿 joint"的 local translation 是骨架 B 自己 bind pose 的 0.36 米。如果动画师的 walk 剪辑里"骨盆 → 大腿"的 local translation 写的是骨架 A 的 0.45 米,那你直接套用,大腿会从骨盆"伸出去"0.45 米,而骨架 B 实际只有 0.36 米的腿——结果是**大腿远端 joint 漂浮在空中**,因为它超出了 bone 的真实长度。同理,胯部高度也是按骨架 A 录的(1.9 米角色站立时胯高 0.95 米),套到骨架 B 上,胯部位置在 0.95 米,但骨架 B 的腿只能伸 0.7 米,**角色"悬空"了 25 厘米**,脚踩不到地。

这就是 retargeting 要解决的核心问题:**怎么把"按骨架 A 比例录的 local transform"重新映射到"按骨架 B 比例的 local transform",让动画的"意图"(迈步、摆臂、转身)保留,但"具体尺寸"换成骨架 B 的**。

### 1.2 归一化空间:retargeting 的核心思想

工业界的解决方案不是"逐 frame 调整 local translation",而是**在归一化空间(normalized space)里录制和回放动画**。核心思想分两步。

**第一步:录制时归一化**。动画师录动画时,所有 local transform 的**平移分量**记录成"相对单位",不是绝对米数。具体来说,一个 joint 的 local translation 不存"绝对长度 0.45 米",而是存"相对父 bone 长度的比例"——如果父 bone 长 0.45 米,这个 joint 离父 0.45 米,那归一化值就是 1.0。这样不管骨架 A 还是骨架 B,只要拓扑一致,归一化值都是同一个数(骨头的近端到远端距离永远是"父 bone 长度的 100%")。这就是为什么很多动画格式(FBX、glTF 的某些扩展、Unreal Animation、Mixamo)能在不同角色之间共享动画——它们在归一化空间里录的。

**第二步:回放时反归一化**。运行时,把归一化的 local translation 乘以**目标骨架 B 的实际 bone 长度**,得到骨架 B 的 local translation。如果归一化值是 1.0,骨架 B 的父 bone 是 0.36 米,那 joint 在骨架 B 上的 local translation 就是 0.36 米——完美贴合骨架 B 的比例。

**旋转和缩放分量不需要归一化**——它们本来就是无量纲的(角度、倍数),跟 bone 长度无关。所以 retargeting 只对 translation 做特殊处理。

这套思想有一个具体的工程实现,业界叫 **Motion Builder HumanIK** 或 **Unreal Retarget Manager** 的基础。核心数据结构是:每个 joint 存一个"归一化系数"(normalization factor),通常是这个 joint 到父 joint 的距离除以某个参考长度。

### 1.3 用 Rust 写一个最小 retargeter

我们来写一个 100 行的 retargeter。它接受源骨架的 bind pose、目标骨架的 bind pose、源骨架上的一个 animation clip,输出 retargeted 到目标骨架的 clip。

```rust
// src/anim/retarget.rs
use crate::anim::{clip::AnimationClip, pose::{Pose, Transform}};

/// 两个拓扑相同的骨架之间的 retarget mapping。
/// 预计算每个 joint 的"源长度 / 目标长度"比例。
pub struct RetargetMapping {
    /// scale[i] = target_bone_length[i] / source_bone_length[i]
    /// 用于 local translation 的缩放
    pub translation_scales: Vec<f32>,
}

impl RetargetMapping {
    /// 从两个骨架的 bind pose 计算 mapping。
    /// 两个骨架 joint 数必须一致,拓扑一致。
    pub fn from_bind_poses(
        source_skeleton: &Skeleton,
        source_bind_pose: &Pose,           // source 在 T-pose 下的 local pose
        target_skeleton: &Skeleton,
        target_bind_pose: &Pose,           // target 在 T-pose 下的 local pose
    ) -> Self {
        let n = source_bind_pose.joint_count();
        debug_assert_eq!(n, target_bind_pose.joint_count());

        let mut scales = vec![1.0f32; n];
        for i in 0..n {
            // local translation 的长度就是这个 joint 到父 joint 的"bone 长度"
            let src_len = vec3_length(source_bind_pose.joints[i].translation);
            let tgt_len = vec3_length(target_bind_pose.joints[i].translation);
            // 防 0(root joint 的 translation 通常是 0,没有父 bone)
            scales[i] = if src_len > 1e-6 { tgt_len / src_len } else { 1.0 };
        }
        Self { translation_scales: scales }
    }

    /// 把一个 local pose(从 source clip 采样得到)retarget 到 target。
    /// 旋转不动,translation 按比例缩放,scale 不动。
    pub fn retarget_pose(&self, out: &mut Pose, source_pose: &Pose) {
        let n = out.joint_count();
        debug_assert_eq!(source_pose.joint_count(), n);
        for i in 0..n {
            let s = self.translation_scales[i];
            let src = &source_pose.joints[i];
            out.joints[i] = Transform {
                translation: [
                    src.translation[0] * s,
                    src.translation[1] * s,
                    src.translation[2] * s,
                ],
                rotation: src.rotation,      // 旋转不归一化,直接搬
                scale: src.scale,            // scale 也不动
            };
        }
    }

    /// 把整个 clip 离线 retarget 一次,生成新 clip(运行时不再算)
    pub fn retarget_clip(&self, source_clip: &AnimationClip) -> AnimationClip {
        let mut out = source_clip.clone();
        for track in &mut out.tracks {
            for kf in &mut track.keyframes {
                let i = track.joint_index;  // 假设 track 知道自己的 joint
                let s = self.translation_scales[i];
                kf.translation[0] *= s;
                kf.translation[1] *= s;
                kf.translation[2] *= s;
            }
        }
        out
    }
}

fn vec3_length(v: [f32; 3]) -> f32 {
    (v[0]*v[0] + v[1]*v[1] + v[2]*v[2]).sqrt()
}
```

注意这里有个**关键的简化**——`translation_scales` 只是一个标量(每 joint 一个),它假设 source 和 target 的 local translation **方向一致**(只是长度不同)。这在大多数情况下成立(大腿骨都是"从骨盆向下偏前一点"),但**不总是**成立:有些角色的骨盆可能更宽(translation 的 X 分量比例不同)、肩部更窄(Z 分量比例不同)。**严格的 retargeting** 应该用 3D 向量缩放,或者更复杂的"per-axis scale":

```rust
// 严格的 per-component 缩放(如果 source 和 target 的 local translation 方向不同)
pub struct RetargetMappingPerAxis {
    pub translation_scales: Vec<[f32; 3]>,   // 每个 axis 单独缩放
}
```

但 per-axis scale 会引入 shear(剪切)问题,通常**业界不推荐**。主流做法仍然是标量缩放 + 美术在 DCC 工具里手动微调。

### 1.4 Root joint 的特殊处理

Root joint(根 joint,通常在骨盆或脚底)的 local translation 是"角色整体在世界里的位置"。如果动画师录了一个 walk 剪辑,root translation 在剪辑里是"每帧前进 5 厘米"——这是 root motion(下一节讲)。

retarget 时 root 的处理有两种选择:

**选项 A:把 root translation 也按比例缩放**。这样骨架 A 录的"前进 5 厘米",骨架 B 上变成"前进 5×(0.36/0.45)=4 厘米"。问题:这意味着骨架 B 的角色走得**慢了**——而你想让两个角色都能走 1.5 m/s。

**选项 B:root translation 不缩放,保留原始前进量**。这样骨架 B 的角色也"前进 5 厘米/帧",但骨架 B 的腿短,步幅小,可能脚跟不上身体前进——脚滑。这就是为什么 root motion 要跟 IK 配合(见 §3.4)。

工业级方案是**选项 B + 步频调整**:root 保留前进量,但角色走的快慢由"剪辑播放速度"调整。如果 walk 剪辑原速 1.5 m/s,你想让骨架 B 走 1.5 m/s,就把播放速度调到 1.0;如果你想走 3 m/s,播放速度调到 2.0(但脚步会变快)。这是 Unreal 的 `PlayRate` 和 Unity 的 `Animator.speed`。

### 1.5 验证 retarget 是否对

retarget 之后怎么知道"对了"?有三个客观验证标准。

**标准一:T-pose 对齐**。把 retargeted clip 的第 0 帧(假设是 T-pose)渲染出来,跟骨架 B 的 bind pose 对比。两者应该几乎重合——所有 joint 的世界位置误差小于 1 厘米。如果某个 joint 偏离 10 厘米,说明那个 joint 的 translation scale 算错了。

**标准二:脚着地**。跑 walk 剪辑,看角色的脚在每一帧是否"着地"(脚踝 Y 坐标 ≈ 地面 Y 坐标)。如果脚悬空 5 厘米,说明胯部太高(retarget 时胯 translation 没缩放够);如果脚穿地 5 厘米,说明胯太低。

**标准三:动作幅度一致**。骨架 A 上"挥手过头顶"的动作,retarget 到骨架 B 上,手也应该过头顶。如果骨架 B 上手只到肩膀,说明上臂 translation 缩放比例错了。

实际工程里,这三个标准都靠**肉眼 + 录屏对比**,没有自动化。大厂有 internal tool 自动比 mocap 跟 retargeted 动画的 pose 距离,但都是非公开的。

### 1.6 生产现实:Mixamo、HumanIK、Unreal IK Rig

你大概率不会自己写 retargeter。工业有几个现成方案。

**Mixamo**(Adobe,免费)是 indie 最常用的。你在 Mixamo 网站上传一个 T-pose 角色,它会自动 rigging(自动给 mesh 加骨架),然后你下载任何 Mixamo 动画,它都自动 retarget 到你的角色上。Mixamo 的 retarget 用一套固定的"标准人形骨架"(25 个 joint,固定命名)做中介——所有动画先 retarget 到标准骨架,再 retarget 到你的角色。这就是"标准化拓扑"的力量。

**Unreal Engine 5 IK Rig + IK Retargeter** 是工业级方案。UE5 引入了"IK Rig"——一个描述角色"哪些 joint 是肢体末端、哪里是 root"的 asset。两个 IK Rig 之间可以建"Retarget Chain Mapping"(joint 链对应),引擎自动算 translation scale。这套系统支持"非人形"角色(狗、龙、机甲),因为它不假设拓扑。

**Motion Builder HumanIK** 是 Autodesk 的角色动画 retarget 工具,mocap 数据处理工业标准。它的"HumanIK Definition"是一套 26-joint 的人形规范,mocap 数据全部 retarget 到这个规范,再分发到不同角色。

**OZZ** 不直接支持 retargeting——它假设动画已经跟骨架匹配。但 `ozz::animation::offline::Decimate` 工具可以做"动画压缩 + retarget 后处理"。

理解 retargeting 原理让你在使用这些工具时不糊涂——当 Mixamo 给你的角色动画"脚穿地"时,你知道是哪个 joint 的 scale 不对,可以手动调;当 Unreal IK Rig 报错"chain mapping 缺失"时,你知道它在找拓扑对应。

## 2 · Morph Target 与 Blend Shape:让脸会动

### 2.1 为什么骨骼搞不定脸

骨骼动画(LBS、DQS)对四肢很好用——大腿、小腿、上臂、前臂,每根 bone 都对应一个粗壮的肢体段,joint 旋转一下整个肢体段就跟着摆。这套抽象适合"刚性段+铰链关节"的结构。

但脸不是这种结构。脸是一个**连续的弹性表面**,表情由几十块微小肌肉协同驱动。一次"微笑"涉及:颧大肌把嘴角往斜上方拉、颧小肌加深鼻唇沟、眼轮匝肌微微收缩让眼角起皱(所谓的"Duchenne smile",真笑的标志)、咬肌放松让下颌微张、口轮匝肌调整嘴唇曲度。这些动作每个都是几十立方毫米级别的**局部表面变形**,没有"铰链",没有"骨头"。

你试图给脸加骨骼,会发现需要的 joint 数量爆炸:眉毛左右各一个、上嘴唇 6 个、下嘴唇 6 个、眼皮左右各 2 个、脸颊左右各 2 个、下巴 1 个……一套完整的脸部 rig 大概 50-100 个 joint。每个 joint 还要"加权影响"周围几十个顶点,skin weight 调起来是噩梦。而且这套 rig **跨角色完全不通用**——精灵活鼠的肌肉结构跟兽人不一样,joint 位置全得重调。

业界因此发明了一个完全不同的抽象:**Morph Target(变形目标)**,Maya 里叫 **Blend Shape(混合形状)**,3ds Max 里叫 **Morpher**。

### 2.2 Morph Target 的核心数据:顶点 delta

Morph Target 的思想极其简单。你有一个角色的 mesh,bind pose 是"中性表情"(neutral face,嘴巴微闭、眼睛睁开、面无表情)。美术在 DCC 工具里复制一份这个 mesh,把复制版的顶点位置手动调,做成"微笑表情"——嘴角上移、眼角收窄。这就是一个 **morph target**,叫"smile"。

注意:smile mesh 跟 neutral mesh **拓扑完全相同**(同样的顶点数、三角面、顶点顺序)。它们只是顶点位置不同。

存储 morph target 时,我们不存"smile mesh 的完整顶点位置"——那是冗余的(neutral 已经有了)。我们存**每个顶点的 delta**(差值):

```
delta_smile[v] = position_smile[v] - position_neutral[v]
```

`position_smile[v]` 是 smile mesh 上顶点 v 的位置,`position_neutral[v]` 是 neutral mesh 上同一顶点的位置。delta 是个 3D 向量,表示"为了从 neutral 变成 smile,顶点 v 要移动多少"。

运行时,如果你想要"30% 的微笑",就把 neutral 顶点位置加上 0.3 × delta_smile:

```
position_final[v] = position_neutral[v] + weight_smile * delta_smile[v]
```

`weight_smile ∈ [0, 1]` 是这个 morph target 的权重——0 是不笑,1 是全笑,0.3 是微微笑。

**关键洞察**:morph target 是**线性叠加**的。一个脸可以有几十个 morph target(smile、frown、blink_L、blink_R、jaw_open、brow_raise_L、brow_raise_R、cheek_puff、mouth_open……),每个有自己的 weight,最终顶点位置是所有 delta 的加权和:

```
position_final[v] = position_neutral[v] + Σᵢ weightᵢ × deltaᵢ[v]
```

这是数学上最简单的模型——顶点空间的线性组合。但效果惊人:几十个 morph target 自由组合,能产生几乎所有人类表情。这是工业级面部动画的标准。

### 2.3 一个完整 morph target 数据结构的 Rust 实现

```rust
// src/anim/morph_target.rs

/// 一个 morph target = 一组顶点 delta(只存"被影响"的顶点,稀疏存储)
#[derive(Clone, Debug)]
pub struct MorphTarget {
    pub name: String,                       // "smile" / "blink_L" / ...
    /// 被这个 morph 影响的顶点 index + 对应的 delta
    /// 用稀疏存储——大多数 morph target 只影响脸上一小撮顶点
    pub deltas: Vec<(u32, [f32; 3])>,       // (vertex_index, delta_position)
}

/// 一个角色的所有 morph target 集合
#[derive(Clone, Debug)]
pub struct MorphTargetSet {
    pub targets: Vec<MorphTarget>,
    /// 运行时各 morph 的当前权重,长度 = targets.len()
    pub weights: Vec<f32>,
}

impl MorphTargetSet {
    /// 把所有 morph target 的 delta 加权应用到 neutral positions 上
    /// out_positions 是输出,neutral_positions 是输入(neutral 表情的 mesh)
    pub fn apply(
        &self,
        out_positions: &mut [[f32; 3]],
        neutral_positions: &[[f32; 3]],
    ) {
        // 先把 out 复制为 neutral
        out_positions.copy_from_slice(neutral_positions);
        // 对每个 morph target,把它的 delta 加权累加到 out
        for (target_idx, target) in self.targets.iter().enumerate() {
            let w = self.weights[target_idx];
            if w.abs() < 1e-6 { continue; }
            for &(vertex_idx, delta) in &target.deltas {
                let v = vertex_idx as usize;
                out_positions[v][0] += w * delta[0];
                out_positions[v][1] += w * delta[1];
                out_positions[v][2] += w * delta[2];
            }
        }
    }
}
```

注意**稀疏存储**——每个 morph target 只存它真正影响的顶点(几十到几百个),不存全部几千个顶点。一个"blink_L"(左眼眨眼)只影响左眼皮周围的 30 个顶点,其他顶点的 delta 是 0,不需要存。这让 morph target 的内存占用极小:每个 target 几 KB,几十个 target 一共几十 KB。比起存一份完整 mesh(几百 KB)省太多了。

### 2.4 Morph Target 跟骨骼蒙皮如何协同

绝大多数真实角色是"骨骼 + morph"组合:身体用骨骼(四肢、躯干、头颅),脸用 morph target。一个完整的顶点变换流程是:

```
final_vertex_position =
    skin_with_bones(morph_target_deform(neutral_vertex))
```

注意**顺序**:先 morph target(改变 neutral 顶点位置),再做骨骼蒙皮(把变形后的顶点 attach 到骨骼上)。这是因为 morph target 的 delta 是在 **neutral 表情 + bind pose** 下定义的——它假设 neutral vertex 是骨骼 bind pose 下的位置。如果你先蒙皮再做 morph,morph delta 会跟着骨骼旋转,效果就不对(嘴张的时候脸转向侧面,morph 的"嘴角上扬"会变成"嘴角朝侧面甩")。

**GLSL vertex shader 实现**:

```glsl
#version 450

// 普通蒙皮 attribute
layout(location = 0) in vec3 a_position_neutral;     // bind pose 下的 neutral 位置
layout(location = 3) in uvec4 a_joints;
layout(location = 4) in vec4  a_weights;

// morph target attribute——每个 morph target 一组 delta
// 只对"被这个 morph 影响的顶点"非零,其他顶点是 (0,0,0)
layout(location = 5) in vec3 a_delta_smile;
layout(location = 6) in vec3 a_delta_frown;
layout(location = 7) in vec3 a_delta_blink_L;
layout(location = 8) in vec3 a_delta_jaw_open;
// ... 更多 morph target

// morph 权重(uniform,所有顶点共享)
layout(set = 0, binding = 1) uniform MorphWeights {
    float w_smile;
    float w_frown;
    float w_blink_L;
    float w_jaw_open;
    // ...
} morph;

// 骨骼蒙皮 palette
const int MAX_BONES = 256;
layout(set = 0, binding = 0) uniform SkinPalette {
    mat4 bones[MAX_BONES];
} palette;

layout(set = 0, binding = 2) uniform Camera {
    mat4 view_proj;
    mat4 model;
};

void main() {
    // 1. 先做 morph target 变形(在 bind pose 空间里)
    vec3 morphed_pos = a_position_neutral
        + morph.w_smile   * a_delta_smile
        + morph.w_frown   * a_delta_frown
        + morph.w_blink_L * a_delta_blink_L
        + morph.w_jaw_open* a_delta_jaw_open;
        // ... 更多 morph target

    // 2. 再做骨骼蒙皮(把 morphed_pos 当成"neutral 位置"输入 LBS)
    vec4 skinned_pos = vec4(0.0);
    float wsum = dot(a_weights, vec4(1.0));
    for (int i = 0; i < 4; ++i) {
        float w = a_weights[i] / wsum;
        skinned_pos += w * (palette.bones[a_joints[i]] * vec4(morphed_pos, 1.0));
    }

    gl_Position = view_proj * model * skinned_pos;
}
```

这里有个**性能权衡**:每个 morph target 占一个 vertex attribute location。GLSL 3.3 / Vulkan 通常有 16 个 attribute location,扣掉 position/normal/uv/joints/weights 还剩 11 个——所以单 mesh 最多 11 个 morph target attribute。如果你的脸需要 50 个 morph target,要么把 mesh 拆成"脸"和"身体"两个 submesh(脸 50 个 morph,身体 0 个 morph),要么用 SSBO 存所有 delta(更灵活,但要 GLSL 4.3+ / Vulkan)。glTF 的扩展 `KHR_morph_targets` 用的是前者(每个 primitive 一组 morph target)。

### 2.5 Corrective Blend Shape(修正混合形状)

LBS 有个臭名昭著的 artifact:volume loss(肘弯时胳膊变细,见 [skeletal-animation-fundamentals](./skeletal-animation-fundamentals.md) §3.2)。这个 artifact 在脸上更明显——下颌张开时,脸颊两侧会"塌陷",因为下颌骨的旋转把脸颊顶点往里拽。

修正方法叫 **Corrective Blend Shape**:美术手雕一个"修正形状",专门补这个塌陷。这个修正形状**只在特定关节角度触发**——下颌张到 30 度时,corrective "jaw_open_corrective" 的权重从 0 升到 1。

```rust
// corrective morph 的权重由骨骼角度驱动
fn compute_corrective_weights(pose: &Pose, joint_index: usize) -> Vec<f32> {
    let jaw_rotation_x = pose.joints[joint_index].rotation[0];  // pitch
    // 下颌张开的程度(0 = 闭嘴,1 = 全张)
    let jaw_open_amount = (jaw_rotation_x / 0.5).clamp(0.0, 1.0);  // 0.5 rad ≈ 28 度全张
    vec![jaw_open_amount]   // corrective "jaw_open_corrective" 的权重
}
```

Unreal 的 Control Rig、Unity 的 Blend Shape 都支持这种"由骨骼驱动的 corrective"。这是 MetaHuman、Siren、Sequoia 这类高保真数字人的核心技术——脸部上千个 morph target + 几百个 corrective,组合出任意表情。重量级,但效果震撼。

### 2.6 glTF 里的 Morph Target

glTF 2.0 spec 原生支持 morph target,扩展名 `KHR_morph_targets`(实际是 core spec 的一部分,不需要扩展标记)。一个 mesh primitive 可以有 `targets` 字段,每个 target 是一组 POSITION / NORMAL / TANGENT 的 delta accessor:

```json
{
  "meshes": [{
    "primitives": [{
      "attributes": {
        "POSITION": 0,
        "NORMAL": 1,
        "JOINTS_0": 2,
        "WEIGHTS_0": 3
      },
      "targets": [
        { "POSITION": 4, "NORMAL": 5 },   // morph target 0 ("smile")
        { "POSITION": 6, "NORMAL": 7 },   // morph target 1 ("frown")
        { "POSITION": 8, "NORMAL": 9 }    // morph target 2 ("blink_L")
      ],
      "extras": {
        "targetNames": ["smile", "frown", "blink_L"]
      }
    }]
  }],
  "animations": [{
    "channels": [{
      "sampler": 0,
      "target": {
        "node": 0,
        "path": "weights"     // 动画可以驱动 morph 权重!
      }
    }]
  }]
}
```

**关键**:glTF 动画不仅能驱动 joint 的 TRS,还能驱动 morph 权重(`target.path = "weights"`)。所以你可以录一个"角色说话"的动画,joint 不动,只 morph 权重变化,运行时按 clip 采样 morph 权重就行。详细 glTF 加载流程见 [phase-7/gltf-and-model-loading](../../phase-7/deep-dives/gltf-and-model-loading.md)。

glTF 的 morph target 默认是**密集存储**——每个 target 存所有顶点的 delta(包括 delta 为 0 的顶点)。这让 glTF morph 文件比较大。生产 pipeline 通常加载时转成稀疏存储(剔除 0 delta)。

### 2.7 性能预算

morph target 的运行时开销很低。一个 5000 顶点的脸 + 30 个 morph target,平均每个 morph 影响 200 个顶点:

- CPU 端 apply:30 × 200 = 6000 次加法,~50 μs
- GPU 端 shader:5000 顶点 × 30 次 multiply-add,~0.1 ms(现代 GPU)

完全在 60 FPS 预算内。Morph target 不是性能瓶颈,美术制作(雕塑每个表情的 delta)才是。一套完整的高质量脸部 morph target,美术要花 2-4 周。这就是为什么 AAA 工作室有专门的"facial rigger"职位。

## 3 · Root Motion:让脚不再滑冰

### 3.1 脚滑现象:为什么会出现

你的角色播 walk 动画,腿正常迈步,但角色身体没动——它在原地"走"。游戏代码每帧把角色平移一段距离(根据摇杆),所以角色也在前进。看起来应该没问题,对吧?

不对。问题在于**动画剪辑的"前进速度"和游戏代码的"平移速度"不匹配**。

美术录 walk 动画时,假设的是"角色以 1.5 m/s 走路"。他在剪辑里让角色的脚每帧抬起、向前、落下,一个完整步态周期 1.0 秒,角色前进 1.5 米。但他录的时候**角色的 root(根节点,通常在骨盆)是固定不动的**——他在 Maya 里把 root 锁死,只让腿和身体相对于 root 摆动。所以剪辑里 root 的 world position 永远是 (0, 0, 0)。

你的游戏代码每帧把角色平移 3 厘米(60 FPS 下 1.8 m/s)。但剪辑里腿的迈步节奏是按 1.5 m/s 设计的——脚落地的瞬间,剪辑里脚的 world position 在 root 前方 30 厘米;但游戏代码已经把整个角色(包括 root)前移了 3 厘米,脚还没抬起,就被拖动了 3 厘米。这就是**脚滑**:脚和地面有相对滑动,像在跑步机上走。

视觉上玩家看到角色"在飘"——脚和地面之间没有"咬合感",像溜冰。

### 3.2 两种使用模式:Ignore vs Apply

解决脚滑有两种思路。

**思路 A:Ignore Root Motion(忽略根运动)**。游戏代码完全控制角色位移,动画只负责"摆姿势"。这是最简单的模式,你前两篇实现的就是这种——剪辑里 root translation 全部忽略,游戏 loop 里根据摇杆平移角色。问题就是脚滑——除非你**精确匹配**剪辑的"前进速度"和游戏代码的"平移速度"。

精确匹配怎么做?美术在录剪辑时告诉你"这个 walk 剪辑的前进速度是 1.5 m/s"。你的游戏代码里:

```rust
let character_velocity = 1.5;  // m/s,跟剪辑匹配
character.position += character.forward * character_velocity * dt;
```

摇杆推 50%,你把 `character_velocity` 调到 0.75,但**同时把剪辑播放速度调到 0.5**(`clip_play_rate = 0.5`),这样剪辑的步频也减半,脚还是跟地面咬合。这是 locomotion blend tree 的标准做法——见 [animation-blending-and-state-machine](./animation-blending-and-state-machine.md) §2.5。

ignore root motion 的优点是**简单、游戏逻辑可控**——你的物理碰撞、AI 寻路、网络同步全用游戏代码的 character velocity,跟动画解耦。缺点是**美术被绑死**——所有 walk/run 剪辑必须严格按预定速度录,一旦某个剪辑速度不对(美术录快了 10%),脚就滑。

**思路 B:Apply Root Motion(应用根运动)**。让动画剪辑**驱动**角色位移。具体来说,剪辑里 root joint 的 translation 不是 (0,0,0),而是**每一帧记录"角色应该前进多少"**。比如 walk 剪辑第 0 帧到第 1 帧,root 从 (0,0,0) 移到 (0,0,0.05)——这 5 厘米就是这一帧角色应该前进的距离。游戏代码每帧从动画系统读出这个 delta,直接加到角色 world position 上:

```rust
let root_delta_this_frame = anim_system.extract_root_delta(clip_time);
character.position += character.rotation * root_delta_this_frame;
```

apply root motion 的优点是**脚永远咬合**——剪辑里 root 前进多远,脚就迈多远,完美匹配。缺点是**游戏逻辑要迁就动画**——角色的移动速度完全由剪辑决定,你不能让角色"跑得比剪辑快"(否则又滑了)。

### 3.3 提取 Root Motion Delta:工程细节

apply root motion 听起来简单——"把 root translation 加到角色上"——但工程上有几个坑。

**坑 1:剪辑是循环的,root 不能无限累加**。walk 剪辑 1.0 秒一周期,如果每一帧 root 都前进 5 厘米,1 秒后 root 累计 3 米。但你播第二个周期时,root 又从 3 米开始?不,剪辑的 root 数据是"从 0 开始的绝对位置",第二个周期开始时 root 又是 0。如果你直接用剪辑里的 root 绝对位置,角色会"跳回起点"。

正确做法是提取**每帧的 delta**——这一帧相对上一帧的位移增量。代码:

```rust
// src/anim/root_motion.rs
pub struct RootMotionExtractor {
    last_root_position: [f32; 3],
    last_root_rotation: [f32; 4],   // 四元数,root 也可以有旋转 motion(turn 动画)
    initialized: bool,
}

impl RootMotionExtractor {
    pub fn new() -> Self {
        Self {
            last_root_position: [0.0; 3],
            last_root_rotation: [0.0, 0.0, 0.0, 1.0],   // identity
            initialized: false,
        }
    }

    /// 给定当前帧 root 的世界位置和旋转,返回"相对上一帧的 delta"
    pub fn extract_delta(
        &mut self,
        current_root_position: [f32; 3],
        current_root_rotation: [f32; 4],
    ) -> ([f32; 3], [f32; 4]) {
        if !self.initialized {
            self.last_root_position = current_root_position;
            self.last_root_rotation = current_root_rotation;
            self.initialized = true;
            return ([0.0; 3], [0.0, 0.0, 0.0, 1.0]);
        }

        // 位置 delta:简单减法(在 root 的本地空间)
        let pos_delta = [
            current_root_position[0] - self.last_root_position[0],
            current_root_position[1] - self.last_root_position[1],
            current_root_position[2] - self.last_root_position[2],
        ];

        // 旋转 delta:last_rotation⁻¹ × current_rotation(SO(3) 群的"差")
        let last_inv = quat_inverse(self.last_root_rotation);
        let rot_delta = quat_mul(last_inv, current_root_rotation);

        self.last_root_position = current_root_position;
        self.last_root_rotation = current_root_rotation;
        (pos_delta, rot_delta)
    }
}

fn quat_inverse(q: [f32; 4]) -> [f32; 4] {
    // 单位四元数的逆 = 共轭
    [q[0], -q[1], -q[2], -q[3]]   // 假设 (w, x, y, z) 顺序
}

fn quat_mul(a: [f32; 4], b: [f32; 4]) -> [f32; 4] {
    // Hamilton 乘积
    [
        a[0]*b[0] - a[1]*b[1] - a[2]*b[2] - a[3]*b[3],
        a[0]*b[1] + a[1]*b[0] + a[2]*b[3] - a[3]*b[2],
        a[0]*b[2] - a[1]*b[3] + a[2]*b[0] + a[3]*b[1],
        a[0]*b[3] + a[1]*b[2] - a[2]*b[1] + a[3]*b[0],
    ]
}
```

**坑 2:cross-fade 时 root motion 怎么处理**。从 walk 切到 run,walk 的 root 速度 1.5 m/s,run 的 root 速度 4.0 m/s,cross-fade 期间角色速度应该是平滑过渡的。**正确做法**是 walk 和 run 各自提取自己的 root delta,**按 cross-fade alpha 加权混合 delta**:

```rust
let walk_delta = walk_extractor.extract_delta(walk_root_pos, walk_root_rot);
let run_delta  = run_extractor.extract_delta(run_root_pos, run_root_rot);
let blended_pos_delta = lerp_vec3(walk_delta.0, run_delta.0, cross_fade_alpha);
let blended_rot_delta = slerp_quat(walk_delta.1, run_delta.1, cross_fade_alpha);
character.position += character.rotation * blended_pos_delta;
character.rotation = quat_mul(character.rotation, blended_rot_delta);
```

**坑 3:root motion 跟物理碰撞冲突**。root motion 说"角色前进 5 厘米",但前方是墙,物理引擎说"不能动"。怎么办?工业方案是 **"动画 root motion 作为 desired velocity,物理引擎 resolve 碰撞后给 actual velocity"**:

```rust
let desired_velocity = root_delta / dt;          // 从动画算 desired
let actual_velocity = physics.resolve_collision(character, desired_velocity);
character.position += actual_velocity * dt;
```

如果撞墙了,actual_velocity < desired_velocity,角色"被卡住"——但脚还在播 walk 动画,脚又滑了!工业解决:**检测 actual/desired 比例,小于阈值时切到 idle**。或者用 IK 让脚"原地踏步"(`foot_plant IK`)。完整方案见 Naughty Dog GDC 2016 talk "Motion Matching"。

### 3.4 Root Motion 驱动相机

root motion 不仅驱动角色,还驱动**摄像机**。第三人称相机的 follow target 是角色 root——root 前进,相机跟着前进。如果用 root motion,相机的运动节奏跟角色的步伐**完全同步**——角色迈一步,相机微微前移,跟角色的"重心上下颠簸"对齐,看起来非常自然。如果用 ignore root motion(游戏代码硬平移),相机会"匀速滑动",跟角色步伐节奏脱节,玩家觉得相机"飘"。

这是 [camera-systems](./camera-systems.md) 里"相机手感"的重要一环。Casey 在 Handmade Hero 的相机系统([phase-2/game-feel-02-camera](../../phase-2/deep-dives/game-feel-02-camera.md))讨论了 camera follow,但没有 root motion(HH 是 sprite 动画,没有 root)。你的 3D HH 衍生项目如果做角色动画,root motion + camera 同步是必备。

### 3.5 何时用 ignore,何时用 apply

工业经验法则:

**用 apply root motion**:角色移动由动画完全驱动的场景——剧情脚本(角色按预设路径走)、过场动画、攻击位移(挥剑时身体前冲)、被击退(knockback)。这些场景里"角色移动多少"是动画设计师决定的,游戏逻辑只负责触发动画。

**用 ignore root motion**:角色移动由玩家输入实时控制的场景——locomotion(玩家推摇杆决定速度方向和大小)、物理平台(站在移动平台上,角色随平台移动)。这些场景里"角色移动多少"是 runtime 算的,动画只能跟(用 blend tree 适配速度)。

**混合方案**(主流):locomotion 用 ignore + blend tree,攻击 / 受击 / 过场用 apply。Unreal 的 Character Movement Component 默认 ignore,AnimMontage 可以选 apply。Unity 的 Animator `applyRootMotion` 是 per-animator 的 bool 开关。

## 4 · Two-Bone IK 接入动画管线

### 4.1 为什么"接入管线"是个独立话题

[animation-blending-and-state-machine](./animation-blending-and-state-machine.md) §4.3 已经完整推导了 Two-Bone IK 的解析解。但那只讲了"给定 root/mid/end 三个位置和 target/pole,算出 new_mid/new_end"。一个完整的角色动画系统里,IK 要**插入到 pose pipeline 的特定位置**——在 sample/blend/additive 之后,在 FK 和 skinning 之前。位置错了,效果全错。

正确的 pipeline:

```
1. sample clip -> local pose
2. blend tree (locomotion) -> local pose
3. additive layer (look / aim) -> local pose
4. FK: local pose -> global (world) pose
5. IK: 在 world space 修改 end/mid joint 的位置      <-- 这一步
6. 反 FK: 把 world 修改转回 local pose(因为 skinning 需要 local)
7. skinning: 用修改后的 local pose 算蒙皮矩阵
```

第 5 步 IK 在 **world space**(global pose)做,因为 IK 的 target(地面接触点、抓取目标)是 world space 的。但 skinning 需要 local pose(每个 joint 相对父 joint 的 TRS),所以第 6 步要把 IK 结果转回 local。这一节就讲这个"world → local"的转换。

### 4.2 Two-Bone IK 的回顾

简短回顾 [animation-blending-and-state-machine](./animation-blending-and-state-machine.md) §4.3。给一个两段骨链(joint A 是 root,固定;joint B 是 mid;joint C 是 end),已知:

- bone A→B 长度 `len_a`(常数)
- bone B→C 长度 `len_b`(常数)
- target T(joint C 想到达的位置)
- pole P(决定 joint B 在哪个方向的向量,通常是"膝盖朝前"或"肘朝后"的方向)

求 joint B 的新位置。

用余弦定理:三角形 (A, B, T) 的三边是 len_a、len_b、`|T-A|`。在 A 处的内角余弦:

```
cos(angle_at_A) = (len_a² + |T-A|² - len_b²) / (2 · len_a · |T-A|)
```

算出 angle_at_A 后,joint B 就在"从 A 朝 T 方向旋转 angle_at_A"的位置上,旋转轴是 `cross(A→T 方向, pole)`。这给出 new_mid 的位置。new_end 就是 new_mid 朝 T 方向走 len_b 的距离。

完整的 Rust 实现见前一篇 §4.3,我们这里直接调用那个函数 `solve_two_bone`。

### 4.3 把 Two-Bone IK 接到 pose pipeline

假设你有一个 64-joint 的人形骨架,joint 索引已知:`hip_L = 5`、`knee_L = 6`、`ankle_L = 7`(左腿);`shoulder_R = 22`、`elbow_R = 23`、`wrist_R = 24`(右臂)。你想给左腿加 IK(让脚踩在斜坡上),给右臂加 IK(让手抓杯子)。

```rust
// src/anim/ik_pipeline.rs
use crate::anim::{pose::Pose, ik::two_bone::{solve_two_bone, TwoBoneIkInput}};

pub struct IkChain {
    pub root_joint: usize,   // 髋 / 肩
    pub mid_joint: usize,    // 膝 / 肘
    pub end_joint: usize,    // 踝 / 腕
    pub target: [f32; 3],    // world space 目标
    pub pole: [f32; 3],      // world space pole 向量
}

/// 对一个 global pose 应用所有 IK chain。
/// 输入:globals(FK 之后的 world matrices)、skeleton(用于查父 joint)
/// 输出:修改后的 globals(IK 调整过的)
pub fn apply_ik_chains(
    globals: &mut [[f32; 4]; 4],   // 4x4 矩阵,每个 joint 一个
    skeleton: &Skeleton,
    chains: &[IkChain],
) {
    for chain in chains {
        let root_idx = chain.root_joint;
        let mid_idx = chain.mid_joint;
        let end_idx = chain.end_joint;

        // 从 global matrix 提取当前 world 位置
        let root_pos = mat4_translation(globals[root_idx]);
        let mid_pos = mat4_translation(globals[mid_idx]);
        let end_pos = mat4_translation(globals[end_idx]);

        // 跑 Two-Bone IK
        let (new_mid_pos, new_end_pos) = solve_two_bone(&TwoBoneIkInput {
            root: root_pos,
            mid: mid_pos,
            end: end_pos,
            target: chain.target,
            pole: chain.pole,
            soften: 0.1,
        });

        // 关键:把新的 world 位置写回 globals,
        // 同时调整旋转让 joint 的"朝向"对齐 bone 方向
        write_ik_result(globals, skeleton, root_idx, mid_idx, end_idx,
                        new_mid_pos, new_end_pos);
    }
}

/// 把 IK 解(world 位置)写回 globals,同时调整 mid 和 end 的旋转
fn write_ik_result(
    globals: &mut [[f32; 4]; 4],
    skeleton: &Skeleton,
    root_idx: usize, mid_idx: usize, end_idx: usize,
    new_mid: [f32; 3], new_end: [f32; 3],
) {
    let root_pos = mat4_translation(globals[root_idx]);

    // 1. 调整 root joint 的旋转:让 root → mid 方向对齐 new_mid - root_pos
    let old_root_to_mid = mat4_translation(globals[mid_idx]);
    let old_dir = vec3_normalize([
        old_root_to_mid[0] - root_pos[0],
        old_root_to_mid[1] - root_pos[1],
        old_root_to_mid[2] - root_pos[2],
    ]);
    let new_dir = vec3_normalize([
        new_mid[0] - root_pos[0],
        new_mid[1] - root_pos[1],
        new_mid[2] - root_pos[2],
    ]);
    let root_rot_delta = quat_between_vectors(old_dir, new_dir);
    let root_current_rot = mat4_rotation_quat(globals[root_idx]);
    let root_new_rot = quat_mul(root_rot_delta, root_current_rot);
    globals[root_idx] = mat4_compose(root_pos, root_new_rot, [1.0; 3]);

    // 2. 把 mid 写到新位置
    globals[mid_idx] = mat4_compose(new_mid, /* mid rot 见下 */, [1.0; 3]);

    // 3. 调整 mid 的旋转:让 mid → end 方向对齐 new_end - new_mid
    // (类似 root 的逻辑)
    // ...

    // 4. 把 end 写到新位置
    globals[end_idx] = mat4_compose(new_end, /* end rot */, [1.0; 3]);
}

/// 给定两个单位向量 from / to,返回把 from 旋转到 to 的四元数
fn quat_between_vectors(from: [f32; 3], to: [f32; 3]) -> [f32; 4] {
    let dot = from[0]*to[0] + from[1]*to[1] + from[2]*to[2];
    if dot > 0.9995 {
        // 几乎平行,返回 identity
        return [0.0, 0.0, 0.0, 1.0];
    }
    let cross = vec3_cross(from, to);
    let w = (1.0 + dot).sqrt();
    let s = 0.5 / w;
    [w * 0.5, cross[0] * s, cross[1] * s, cross[2] * s]   // (w, x, y, z)
}
```

这段代码的核心是**"调整旋转 + 平移到新位置"**。Two-Bone IK 给你的是 joint 的**位置**,但 joint 的 global matrix 是个完整的 TRS——你不仅要更新 translation,还要让 rotation 跟"bone 朝向"对齐。否则 joint 位置对了,但 rotation 还是 IK 之前的,skinning 时 mesh 会扭曲(例如脚踝位置对了但脚掌还朝原方向,IK 后脚掌朝上)。

### 4.4 从 global 反算 local:让 skinning 拿到正确数据

skin matrix 计算(`M_skin[i] = M_current_global[i] · M_bind_inv[i]`)用的是 joint 的 global matrix。所以 IK 修改完 globals 后,**直接用修改后的 globals 算 skinning 就行**——不需要反算 local。

但有一个例外:如果 IK chain 的 joint 有**子 joint**(比如手腕 IK 解决了,但手指还是子 joint),子 joint 的 global = parent global × child local。你改了 wrist 的 global 后,**finger 的 global 也会变**(因为 finger 是 wrist 的子)。这通常是想要的——手腕动了,手指跟着动。但**如果子 joint 也有 IK**(比如手指自己 IK 到抓握形状),需要按依赖顺序应用 IK:父 IK 先,parent global 更新后,子 IK 再用新的 parent global 算。

工业级方案:**拓扑排序 IK chain**,按 joint 树从根到末端顺序应用。OZZ 的 `IKTwoBoneJob` 不处理这个,它假设你单次调用解决一条链;Unreal 的 Control Rig 用"执行图(execution graph)"显式排序所有 IK 节点。

### 4.5 IK 在 world space,但 skinning 需要 model space

注意一个**坐标空间**问题。IK 的 target(地面接触点)是 **world space**——你的物理引擎算出"脚下地面 Y 高度 = 1.3 米",这是世界坐标。但 joint 的 global matrix 在 **model space**(相对角色 root)。所以应用 IK 之前,要把 target 从 world 转到 model:

```rust
let target_model = mat4_mul_vec3(
    mat4_inverse(character.world_matrix),
    target_world,
);
```

pole 也一样。这是新手 IK 写错的常见原因——target 用了 world space 但 globals 在 model space,IK 解出来 joint 跑到了世界原点附近。

### 4.6 IK 之后,角色 root 可能要调整

考虑这个场景:角色站在斜坡上,左脚下斜坡比右脚低 30 厘米。你给左脚 IK target = (左脚 X, 斜坡 Y, 左脚 Z),但角色的 root(骨盆)还在水平位置——左腿的 IK chain(髋到踝)不够长,够不到 30 厘米下的目标。Two-Bone IK 在这种情况下会"拉伸"骨头(`soften` 参数控制),但视觉上腿被拉长了,不真实。

工业方案是 **"root adjustment"**:在跑 IK 之前,**先把 root 下沉**(让角色微微蹲下),让 IK chain 够得到 target。具体多少?通常取"两脚 IK target 的平均 Y - 角色 stand 高度"。这是《最后生还者》foot planting 系统的核心 trick。

```rust
fn adjust_root_for_foot_ik(
    globals: &mut [[f32; 4]; 4],
    foot_l_target_y: f32,
    foot_r_target_y: f32,
    stand_height: f32,
) {
    let avg_foot_y = (foot_l_target_y + foot_r_target_y) * 0.5;
    let root_drop = (stand_height - avg_foot_y).max(0.0);  // 不上抬,只下沉
    globals[ROOT_IDX][3][1] -= root_drop;   // Y 是 [3][1] in row-major
}
```

加完 root adjustment 再跑 IK,腿就不会被拉伸到不自然。

## 5 · 五个技术的合成:完整的 advanced character animation pipeline

把前面四个技术合成,完整的角色 pose 计算 pipeline 是:

```rust
// src/anim/advanced_pipeline.rs

pub struct AdvancedAnimPipeline {
    // 输入
    pub skeleton: Skeleton,
    pub retarget_mapping: RetargetMapping,
    pub locomotion_blend_tree: BlendTree1D,    // 走 / 跑
    pub attack_clip: AnimationClip,            // 攻击
    pub morph_targets: MorphTargetSet,         // 面部
    pub ik_chains: Vec<IkChain>,               // 手脚 IK

    // 内部状态
    pub root_motion_extractor: RootMotionExtractor,
    pub current_state: AnimState,
    pub fsm: AnimFSM,
    pub scratch_pose: Pose,
    pub scratch_globals: Vec<[[f32; 4]; 4]>,
}

impl AdvancedAnimPipeline {
    pub fn evaluate(
        &mut self,
        dt: f32,
        params: &AnimParams,           // 玩家输入、地面高度、抓取目标等
        out_globals: &mut Vec<[[f32; 4]; 4]>,
        out_morph_weights: &mut Vec<f32>,
        out_root_delta: &mut ([f32; 3], [f32; 4]),
    ) {
        // === 第 1 步:FSM 求值,得到 local pose(sample + blend + additive)===
        self.fsm.update(params, dt, &mut self.scratch_pose);

        // === 第 2 步:Retarget(如果 clip 来自不同比例骨架)===
        // 注意:retarget 在 local pose 上做
        // 如果 clip 已经离线 retarget 过(self.retarget_mapping.retarget_clip),
        // 这步可以跳过
        // let mut retargeted_pose = Pose::with_joint_count(...);
        // self.retarget_mapping.retarget_pose(&mut retargeted_pose, &self.scratch_pose);
        // self.scratch_pose = retargeted_pose;

        // === 第 3 步:Forward Kinematics(local → global)===
        self.scratch_globals = self.skeleton.compute_global_poses(&self.scratch_pose);

        // === 第 4 步:Root Motion 提取 ===
        let root_idx = 0;   // root joint
        let root_pos = mat4_translation(self.scratch_globals[root_idx]);
        let root_rot = mat4_rotation_quat(self.scratch_globals[root_idx]);
        let (pos_delta, rot_delta) = self.root_motion_extractor.extract_delta(root_pos, root_rot);
        *out_root_delta = (pos_delta, rot_delta);

        // === 第 5 步:IK(在 world/model space 修改 globals)===
        // 先调整 root(让 IK chain 够得到 target)
        adjust_root_for_foot_ik(
            &mut self.scratch_globals,
            params.foot_l_target[1],
            params.foot_r_target[1],
            params.stand_height,
        );
        // 再应用 IK chains
        apply_ik_chains(&mut self.scratch_globals, &self.skeleton, &self.ik_chains);

        // === 第 6 步:输出 globals 给 skinning 系统 ===
        *out_globals = self.scratch_globals.clone();

        // === 第 7 步:输出 morph weights 给 facial 渲染 ===
        // morph weights 由 FSM 或 game logic 设置(角色情绪状态 → morph 权重)
        out_morph_weights.copy_from_slice(&self.morph_targets.weights);
    }
}
```

这个 pipeline 每一帧跑一次,产出:**关节全局矩阵**(给蒙皮 shader)、**根运动增量**(给角色位移)、**morph 权重**(给面部 shader)。三者一起送到渲染器,角色就"动起来、表情起来、抓得住东西"。

## 6 · 生产现实:工业级实现

这一节带你过一遍主流引擎和工具是怎么实现这四个技术的。理解这些让你在使用它们时心里有底。

### 6.1 Unreal Engine 5

UE5 的角色动画系统是工业标杆。

**Retargeting**:UE5 引入了 IK Rig 和 IK Retargeter 两个 asset。IK Rig 描述"角色身上哪些 joint 是 IK chain",IK Retargeter 描述"两个 IK Rig 之间的 chain 对应关系"。UE5 的 retargeting 是**自动的**——你只要打开 IK Retargeter,选源和目标,引擎自动算 translation scale,实时预览。这套系统支持非人形(四足、机甲)。

**Morph Target**:UE5 叫 Morph Target,在 Skeleton Editor 里导入。每个 Morph Target 是一组 vertex delta,运行时通过 `USkeletalMeshComponent::SetMorphTarget(FName, float)` 设置权重。UE5 还支持 **Curve-driven morph**——动画剪辑里可以录"曲线",曲线值驱动 morph 权重(比如"咬合"曲线驱动"下颌开"morph)。MetaHuman 用了上千个 morph target。

**Root Motion**:UE5 在 Animation Sequence asset 里有一个 "Root Motion" 开关。开启后,剪辑的 root joint translation 会被提取为 root motion delta,通过 `FAnimInstanceProxy::ExtractRootMotion` 返回。Character Movement Component 默认不应用 root motion(用游戏代码控制),但 AnimMontage(动画蒙太奇,用于攻击 / 受击)默认应用。`USkeletalMeshComponent::SetTickMode` 控制 root motion 是否传给 character。

**Two-Bone IK**:UE5 的 AnimBP 节点 `FAnimNode_TwoBoneIK`(`AnimGraphRuntime/Private/AnimNodes/AnimNode_TwoBoneIK.cpp`),核心调用 `AnimationCore::SolveTwoBoneIK`——就是我们 §4.2 的解析解。还有 `FAnimNode_CCDIK`、`FAnimNode_Fabrik` 处理长链 IK。Control Rig(UE5 的新一代 rig 系统)用更灵活的节点图,允许任意组合 IK + 骨骼控制。

### 6.2 Unity

Unity 的 Animator 是 C# 闭源 + C++ 后端。

**Retargeting**:Unity 通过 **Avatar** system 实现人形 retargeting。Avatar 是一个 asset,描述"这个角色的 joint 跟 Unity 标准 Humanoid 拓扑怎么对应"。所有人形动画在内部 retarget 到标准 Humanoid,再 retarget 到具体角色。这套系统对人形角色非常成熟(支持 Make Human / Mixamo 角色直接共享动画),但对非人形(狗、龙)支持有限——非人形用 Generic rig(不做 retarget)。

**Morph Target**:Unity 叫 Blend Shape,SkinnedMeshRenderer 直接暴露 `GetBlendShapeWeight(int)` / `SetBlendShapeWeight(int, float)` API。每个 Blend Shape 一个 index,美术在 Maya 里做好导入。Unity 不支持 corrective blend shape 的"骨骼驱动"自动化,要自己写脚本。

**Root Motion**:Unity Animator 有 `applyRootMotion` bool。开启后,每帧 Animator 通过 `OnAnimatorMove()` 回调把 root motion delta 给你,你自己应用到 transform。CharacterController 跟 root motion 配合需要小心(物理 resolve 后用 actual delta)。

**Two-Bone IK**:Unity Animator 暴露 `OnAnimatorIK(int layerIndex)` 回调,在里面 `Animator.SetIKPosition(AvatarIKGoal.LeftFoot, target)`。底层调 Unity 内部的 Two-Bone IK 实现。这套 API 比较老,DOTS Animation 用新的 `Unity.Animation` package,IK 是 graph node。

### 6.3 Godot 4

完全开源(关键优势,你可以读所有代码)。

**Retargeting**:Godot 4 引入了 **SkeletonProfile**——一个描述"标准人形 joint 命名和层级"的 resource。两个 Skeleton3D 通过 SkeletonProfileRetarget 映射。代码在 `scene/3d/skeleton_3d.cpp` 和 `scene/animation/skeleton_profile*.cpp`。

**Morph Target**:Godot 叫 Blend Shape,在 Importer 里设置。`MeshInstance3D.set_blend_shape_value(name, float)` 设置权重。

**Root Motion**:Godot 4.x 的 AnimationTree 支持 root motion 提取,通过 `AnimationTree.advance()` 返回 root motion delta。`Node3D` transform 应用由用户脚本控制。

**Two-Bone IK**:Godot 4 引入了 `SkeletonModifier3D`,所有骨骼修改器(IK、约束)的基类。具体实现 `LookAtModifier3D`、`TwoBoneIKModifier3D`(社区 PR 进行中,4.x 还不完全稳定)。Godot 还在快速发展这部分。

### 6.4 Bevy + OZZ

**Bevy**(0.14)的 `bevy_animation` 提供 AnimationPlayer + AnimationGraph,但 retarget / morph / root motion / IK 都还不完整。Bevy 生态的 `bevy_morph target` crate(社区)处理 morph target,`bevy_ik`(实验)处理 IK。Bevy 的目标是工业级动画系统,但目前(2026 年中)还在快速演进。

**OZZ**(Ubisoft,C++)是低层 runtime,提供 `IKTwoBoneJob`、`IKAimJob`、`LocalToModelJob`(FK)。OZZ 不做 retarget(假设动画匹配骨架)、不内置 morph target(用户自己处理)。OZZ 是工业级 IK/FK 的金标准参考实现,值得读源码。Rust binding `ozz-animation-rs` 提供基础绑定,但维护不活跃——这是社区贡献机会。

## 7 · 性能数据

把每个环节的开销列出来,你才能 budget。以下数据基于 64-joint 人形角色、Intel i7-12700H、release build、单线程。

| 操作 | 单次开销 | 60 FPS 占比 |
|---|---|---|
| Retarget(在线,per pose) | 0.008 ms | 0.05% |
| Retarget(离线,per clip) | 一次性,运行时 0 | 0% |
| Morph target apply(50 targets, 5000 verts) | 0.05 ms(CPU) / 0.1 ms(GPU) | 0.3% / 0.6% |
| Root motion extract | 0.0005 ms | 0.003% |
| Two-Bone IK(单 chain) | 0.0008 ms | 0.005% |
| Two-Bone IK(4 chain:双臂双腿) | 0.003 ms | 0.018% |
| FK(64 joint) | 0.003 ms | 0.018% |
| Skin matrix palette(64 joint) | 0.030 ms | 0.18% |

**一个完整的 advanced character animation pipeline(单角色,每帧)**:

```
Locomotion blend tree:   0.020 ms   (前一篇的数据)
Retarget(在线):         0.008 ms
FK:                      0.003 ms
Root motion extract:     0.001 ms
4 个 Two-Bone IK:        0.003 ms
Skin palette:            0.030 ms
Morph target(GPU):       0.100 ms
─────────────────────────────────
总计:                    0.165 ms
```

**100 个角色并行**:16.5 ms,刚好在 60 FPS 预算(16.6 ms)内。**500 个角色**( Horde 游戏,如《全面战争》)就需要 LOD—— 远处的角色关闭 morph / IK / retarget,只播简化动画。

## 8 · 生产坑 + 调试叙事

### 8.1 坑一:Retarget 之后角色"悬空"

**现象**:从 Mixamo 导入的 walk 剪辑,retarget 到你的角色,角色脚悬空 8 厘米。

**调试**:把 walk 剪辑第 0 帧(假设是 T-pose 或 stand)渲染出来,看角色脚 Y 坐标。结果脚在 Y=0.08,地面在 Y=0。

**根因**:Mixamo 的标准 rig 站立时脚踝在 Y=0,但你的角色 bind pose 设计时脚踝在 Y=-0.08(建模师没对齐)。Retarget 用 bind pose 算 translation scale,bind pose 错了 scale 就错了。

**修复**:在 DCC 工具里调整角色 bind pose,让脚踝在 Y=0(跟 Mixamo 对齐)。或者在 retarget 之后加一个 "vertical offset" CVar 手动调。**生产 tip**:bind pose 设计时,角色脚底永远在 Y=0,这是工业规范。

### 8.2 坑二:Morph Target 让脸"塌"

**现象**:你给脸加了 5 个 morph target(smile、frown、blink_L、blink_R、jaw_open),同时全开,脸"塌成一团"——所有顶点跑到中心。

**调试**:逐个 morph 开,看是哪个 morph 有问题。开到 jaw_open 时脸塌。

**根因**:jaw_open 这个 morph target 的 delta 数据错了——美术在 DCC 工具里导出时,把 jaw_open mesh 的某些顶点 delta 算反了(delta 应该是 `smile_pos - neutral_pos`,他算成了 `neutral_pos - smile_pos`,符号反)。所有 delta 朝中心收缩,叠加起来脸塌陷。

**修复**:在 DCC 工具里检查 jaw_open 的 delta 方向(嘴角应该往下,不是往上)。或者在 loader 里加 sanity check:每个 morph target 的 delta 平均长度应该在合理范围(0.5-5 厘米),超出范围警告。

### 8.3 坑三:Root Motion 在 cross-fade 时"跳"

**现象**:从 walk 切到 run,cross-fade 进行到一半时角色"瞬移"了一段距离。

**调试**:打印 walk 和 run 各自的 root delta。walk 前进 0.025 m/frame,run 前进 0.066 m/frame。cross-fade alpha=0.5 时,blended delta = lerp(0.025, 0.066, 0.5) = 0.046,看起来正常。

**真正根因**:`RootMotionExtractor::extract_delta` 每帧**只调一次**,但 cross-fade 期间你在 walk 和 run 上**各自**调了一次——每次都更新 `last_root_position`。第二次调用时 `last_root_position` 已经被第一次更新过,delta 算错了。

**修复**:`RootMotionExtractor` 的 state 跟踪应该是**每剪辑一个独立实例**。walk 有自己的 extractor,run 有自己的 extractor,两者互不干扰。blended delta 由两个 extractor 各自的输出加权得到。见 §3.3 坑 2 的代码。

### 8.4 坑四:IK 让肘"反弯"

**现象**:你给右臂加 Two-Bone IK 抓杯子,但肘朝身体外侧弯(像鸡腿),而不是朝后弯(人正常)。

**调试**:检查 pole 向量。代码里 `pole = shoulder_pos + [0, 0, 1]`(Z+ 是前方),应该让肘朝前。但你的世界坐标系 Z+ 是后方(右手坐标系 + Y up + Z toward camera),所以 pole 实际指向相机,肘朝相机方向弯。

**根因**:pole 向量的坐标空间混了。pole 应该在 model space(角色本地坐标系),你给了 world space。

**修复**:pole 在 model space 设为 `[0, 0, 1]`(角色本地 Z+ 是前方),或者明确地用"角色 forward × up"算 pole 方向。Two-Bone IK 的 pole 决定 IK 解在"哪一侧",空间错了视觉就错。

### 8.5 坑五:Corrective Blend Shape 不触发

**现象**:你给下颌加了 corrective blend shape(下颌张开时脸颊补 volume),但跑动画时 corrective 没生效——下颌张到 30 度,脸颊还是塌。

**调试**:打印 corrective 的权重驱动函数。发现 `jaw_rotation_x` 一直是 0。

**根因**:`jaw_rotation_x` 取的是 `pose.joints[jaw_idx].rotation[0]`,这是 local rotation quaternion 的 x 分量,不是 pitch 角度。quaternion 的 x 分量跟 pitch 不是线性关系。

**修复**:从 quaternion 提取 pitch:

```rust
fn quat_to_euler_pitch(q: [f32; 4]) -> f32 {
    // (w, x, y, z) 顺序
    let sin_p = 2.0 * (q[0] * q[1] + q[2] * q[3]);
    let cos_p = 1.0 - 2.0 * (q[1] * q[1] + q[2] * q[2]);
    sin_p.atan2(cos_p)
}
```

corrective 的驱动应该用 pitch 弧度,不是 quaternion 分量。

## 9 · 在你 HH 项目里动手(做中学红线)

具体到你的 Handmade Hero Rust 项目,把这一篇的四个技术全部落地。这是"做中学"红线——你必须真的跑通这四个,不然没学到。

### 9.1 准备工作

你需要一个 rigged 角色 mesh(带骨架)。两个选项:

**选项 A**:用你 HH 项目已有的角色(如果它有骨骼)。理想情况。

**选项 B**:去 Mixamo 下载一个免费角色 + 几个动画(walk / run / idle)。Mixamo 会自动 rigging,导出 FBX 或 glTF。然后用 `gltf` crate 加载。这是最快路径。

还需要一个**不同比例的骨架**——选项 B 里,你下载 Mixamo 的"标准 rig"动画,然后**自己改一版角色**(在 Blender 里缩放 armature,让角色矮 20%),用 retarget 把 Mixamo 动画映射过来。

### 9.2 实战一:Retarget 验证

把 §1.3 的 `RetargetMapping` 接到你项目里。

1. 加载两个骨架:source(Mixamo 标准 rig)、target(你的角色)。两者的 joint 数和拓扑应该一致(Mixamo 用固定 25-joint 人形)。
2. 加载 source 的 bind pose(`source_bind_pose`)、target 的 bind pose(`target_bind_pose`)。
3. 构造 mapping:`let mapping = RetargetMapping::from_bind_poses(&source_skel, &source_bind, &target_skel, &target_bind)`。
4. 加载一个 walk 剪辑(从 Mixamo,在 source 骨架上录的)。
5. 每帧采样剪辑,retarget,FK,蒙皮:`mapping.retarget_pose(&mut retargeted, &source_pose); skeleton.compute_global_poses(&retargeted); ...`
6. **验证**:渲染角色,跑 walk。角色的脚应该踩在地面上(不悬空、不穿地),胳膊摆动幅度跟 Mixamo 预览一致。如果脚穿地,调 bind pose;如果胳膊过宽,检查 shoulder joint 的 scale。

记录一个 CVar `g_retarget_enabled`,设 0 时跳过 retarget(用原始 source pose),设 1 时做 retarget。这样你能 toggle 看差异。

### 9.3 实战二:Morph Target 面部

给你的角色加 morph target。如果你的角色 mesh 没有内置 morph target,你有两个选择:

**简易路径**:在 Blender 里复制角色 mesh 一份,手动调嘴角几个顶点往上 0.5 厘米,做成"smile"morph target。导出 glTF(勾选 Morph Targets),glTF 会包含 smile 的 delta。

**懒人路径**:在 Rust 里**程序化生成**一个 morph target——找角色嘴角附近的几个顶点(通过 vertex index,你自己查),手动写 delta 数组:

```rust
let smile_target = MorphTarget {
    name: "smile".to_string(),
    deltas: vec![
        (1234, [0.02, 0.03, 0.0]),    // 嘴角左
        (1235, [-0.02, 0.03, 0.0]),   // 嘴角右
        // ... 更多顶点
    ],
};
```

加一个 CVar `g_smile_weight ∈ [0, 1]`,每帧把它设到 morph target 的权重上:

```rust
let smile_weight = cvars.g_smile_weight;
morph_set.weights[smile_idx] = smile_weight;
morph_set.apply(&mut deformed_positions, &neutral_positions);
// 然后用 deformed_positions 做蒙皮
```

**验证**:跑游戏,在 console 改 `g_smile_weight 0.5`,角色嘴角应该上扬。改 `g_smile_weight 1.0`,完全微笑。改 `0.0`,恢复中性。

### 9.4 实战三:Root Motion 应用

把 §3.3 的 `RootMotionExtractor` 接上。

1. 找到你 walk 剪辑的 root joint(通常是 joint 0,叫 "root" 或 "Hips")。
2. 每帧采样剪辑后,FK 之前,从 local pose 里读出 root joint 的 translation 和 rotation。
3. 用 `RootMotionExtractor::extract_delta` 算出这一帧的 root delta。
4. 把 delta 应用到角色 world position:

```rust
let (pos_delta, rot_delta) = root_motion_extractor.extract_delta(root_pos, root_rot);
character.position[0] += character_rotation[0] * pos_delta[0] + ...;
// 旋转应用到角色 facing
character_rotation = quat_mul(character_rotation, rot_delta);
```

5. **关掉之前的"游戏代码硬平移"**(那种 `character.position += forward * speed * dt`)——现在角色移动完全由 root motion 驱动。

**验证**:跑 walk,角色前进速度应该跟剪辑里 root translation 累积速度一致(约 1.5 m/s)。脚不应该再"滑"——脚掌每次落地都在地面咬合。在 console 改 `g_walk_playback_speed 2.0`,角色跑起来,脚依然咬合(因为 root motion 跟着 play rate 缩放)。

### 9.5 实战四:Two-Bone IK

把 §4.3 的 IK 接到 pose pipeline。

**场景 A:脚 IK 到不平地面**。你的场景里放几个 box(高度不一),让角色站上去。每帧用 raycast 算左右脚下方的地面高度,设为 IK target:

```rust
let foot_l_target = [foot_l_current_x, ground_height_l + 0.05, foot_l_current_z];
let foot_r_target = [foot_r_current_x, ground_height_r + 0.05, foot_r_current_z];
// +0.05 是"脚踝离地 5 厘米"
ik_chains[0].target = foot_l_target;
ik_chains[1].target = foot_r_target;
// pole:膝盖朝前(角色本地 +Z)
ik_chains[0].pole = [hip_l_x, hip_l_y + 0.5, hip_l_z + 1.0];
ik_chains[1].pole = [hip_r_x, hip_r_y + 0.5, hip_r_z + 1.0];
```

**场景 B:手 IK 到一个物体**。放一个 movable 的杯子(玩家可以拖动),让角色右手去抓:

```rust
let cup_pos = cup_entity.position;
let wrist_target = [cup_pos[0], cup_pos[1], cup_pos[2]];
ik_chains[2].target = wrist_target;
// pole:肘朝后(角色本地 -Z)
ik_chains[2].pole = [shoulder_r_x, shoulder_r_y + 0.3, shoulder_r_z - 0.5];
```

跑 IK,FK 之后,蒙皮之前。

**验证**:角色站在 box 上,脚踝贴着 box 表面(不穿 box,不悬空)。拖动杯子,角色右手始终"指向"杯子(可能差几厘米,因为 IK chain 有限长度——杯子太远时手伸不到,这是正常的)。

### 9.6 完整集成测试清单

按这个顺序验证全部四个技术:

- [ ] cargo build,无 warning
- [ ] 实战一:retarget 后角色脚踩地,动作幅度跟 Mixamo 预览一致
- [ ] 实战二:CVar 改 morph 权重,角色脸变化正确
- [ ] 实战三:root motion 驱动角色前进,脚不滑
- [ ] 实战四 A:角色站在 box 上,脚踝贴 box 表面
- [ ] 实战四 B:角色右手跟随杯子位置(IK)
- [ ] 全部一起开:retarget + root motion + 双脚 IK + 右手 IK + 面部 morph,角色"看起来活了"
- [ ] 帧时间稳定在 16.6 ms 以下(60 FPS),profile 显示动画 pipeline 占 < 1 ms

### 9.7 调试工具

加这些 debug 可视化:

```rust
// 渲染 IK target 为小球
debug_draw::sphere(ik_chain.target, 0.05, Color::RED);
// 渲染 IK pole 为线
debug_draw::line(ik_chain.root_pos, ik_chain.pole, Color::GREEN);
// 渲染 root motion delta 为箭头
debug_draw::arrow(character.position, character.position + pos_delta * 30.0, Color::BLUE);
// 渲染 morph target 当前权重(屏幕 HUD)
debug_draw::text(&format!("smile: {:.2}", morph_weights[smile_idx]), 10, 10);
```

这些可视化是排错利器——你能"看见"target 在哪、pole 朝哪、root 动了多少。Casey 在 HH 经常说"可视化你的数据",动画系统尤其重要。

## 10 · 练习

### Lv1 · 概念辨析

**题**:retargeting 为什么只对 translation 做特殊处理,rotation 和 scale 不动?morph target 跟 corrective blend shape 的区别是什么?root motion 的 ignore 和 apply 模式各适合什么场景?Two-Bone IK 的 pole 向量为什么必须存在?

**参考答案要点**:

- rotation 是角度量(无量纲),30 度在哪个骨架上都是 30 度,跟 bone 长度无关;scale 是比例,也无量纲;只有 translation 是长度量,跟骨架比例有关。所以只有 translation 需要"按比例缩放"。
- morph target 是"主动变形"(smile、blink),由 game logic 或动画驱动,代表"角色想做的表情";corrective blend shape 是"被动修正"(jaw_open_corrective 补下颌张时的脸颊塌陷),由骨骼角度驱动,代表"修 LBS 的 artifact"。一个表达情感,一个修 bug。
- ignore 适合玩家实时控制移动(locomotion、平台跳跃);apply 适合脚本驱动 / 攻击 / 过场。前者移动速度 runtime 决定,后者移动由动画预录决定。
- 没有 pole,3D 的 triangle (root, mid, target) 有无穷多个解——mid 可以绕 root-target 轴任意旋转。pole 决定 mid 在哪一侧(膝盖朝前 / 后,肘朝前 / 后),让 IK 解唯一。

### Lv2 · 动手实践

**题**:写一个 `RetargetMapping`,接受任意两个拓扑相同的骨架 bind pose,构造 translation scale 数组。然后写一个 unit test 验证:对 source bind pose 做 retarget,得到的 translation 跟 target bind pose 的 translation 一致(误差 < 1e-5)。

**完成标准**:
1. 实现构造和 retarget_pose
2. 写 3-joint 链的 test:source bone 长度 (1, 1, 1),target bone 长度 (2, 0.5, 1.5)。验证 retargeted translation 是 (2, 0.5, 1.5)。
3. 写 10-joint 树形骨架的 test,随机生成 source / target 比例,验证。

### Lv3 · 调试场景

**题**:你的角色 retarget 后,左臂摆动幅度太小(几乎不动),右臂正常。写一份 5 步调试流程,从现象到根因。

**提示**:
- 先验证 source 上左臂动作是否正常(可能 source clip 本身就有问题)
- 检查 left shoulder joint 的 translation scale 是否异常(可能 source / target bind pose 里 left shoulder 的 translation 方向不同,标量 scale 不够)
- 检查 left shoulder 的 rotation 在 retarget 后是否被错误处理(应该原样保留)
- 检查 left arm 的 skin weight 是否正确(可能 mesh 上左臂顶点的 joint index 写错,绑到了 neck 而不是 shoulder)
- 跟 right arm 对比数据,找出差异

### Lv4 · 系统设计

**题**:设计一个"foot planting"系统——角色在不平地面上行走时,根据预测的落脚点,自动调整步态。需要:1) 步幅预测(根据当前速度和方向预测下一步落在哪);2) 落脚点 IK(用 Two-Bone IK 把脚踝放到预测点);3) hip adjustment(如果两脚高度差太大,调整骨盆高度和倾斜)。写出数据结构、主循环伪代码、跟 locomotion blend tree 的接口。

**完成标准**:
1. 写出 FootPlantSystem struct
2. 写出预测算法(可以用简单的"前向投影"——从当前脚位置向前 0.3 米 raycast 找地面)
3. 写出 hip adjustment 算法
4. 解释这个系统跟 Motion Matching([animation-blending-and-state-machine](./animation-blending-and-state-machine.md) §9)的关系——Motion Matching 是更高级的解决方案,不需要手动 foot plant

## 11 · 延伸阅读

本仓库本地资料:
- [skeletal-animation-fundamentals](./skeletal-animation-fundamentals.md) — 骨架、FK、LBS、DQS 的基础(本篇前置)
- [animation-blending-and-state-machine](./animation-blending-and-state-machine.md) — blend tree、HFSM、IK 三大算法(本篇前置)
- [camera-systems](./camera-systems.md) — 相机系统,root motion 驱动相机的部分
- [phase-2/game-feel-02-camera](../../phase-2/deep-dives/game-feel-02-camera.md) — 相机手感,角色移动节奏跟相机的同步
- [phase-9/09B-1-game-loop-and-timestep](../../phase-9/09B-1-game-loop-and-timestep.md) — delta-time 和动画 tick 的关系
- [phase-7/gltf-and-model-loading](../../phase-7/deep-dives/gltf-and-model-loading.md) — glTF morph target 加载的完整流程

外部稳定 URL:
- Lewis et al. 2000, "Pose Space Deformation":https://www.disneyanimation.com/publications/pose-space-deformation/ — corrective blend shape 的奠基论文
- Autodesk HumanIK 文档:https://help.autodesk.com/view/MOBPRO/2022/ENU/?guid=GUID-... — Motion Builder 的 retarget 系统
- Unreal Engine 5 IK Rig 文档:https://docs.unrealengine.com/5.0/en-US/ik-rig-in-unreal-engine/ — IK Rig 和 IK Retargeter
- Unity Avatar and Retargeting:https://docs.unity3d.com/Manual/AvatarCreationandConfiguration.html
- Mixamo:https://www.mixamo.com/ — 免费 auto-rigging 和动画库
- glTF 2.0 Morph Targets spec:https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#morph-targets
- OZZ IKTwoBoneJob 源码:https://github.com/ozz-animation/ozz-animation/blob/main/src/animation/runtime/ik_two_bone_job.cc
- Bevy bevy_animation:https://github.com/bevyengine/bevy/tree/main/crates/bevy_animation

真实开源源码:
- OZZ `ik_two_bone_job.cc`:Two-Bone IK 的工业级参考实现,SIMD 优化
- OZZ `ik_aim_job.cc`:Aim IK(单 joint 朝 target)
- Unreal `AnimNode_TwoBoneIK.cpp`:UE5 的 Two-Bone IK 节点
- Godot `skeleton_3d.cpp` + `skeleton_profile_humanoid.cpp`:Godot 4 retarget
- Bevy `bevy_animation` graph.rs:AnimationGraph(blend tree)

---

**结语**:retargeting、morph target、root motion、two-bone IK——这四个技术单独看都不复杂,每个几百行代码就能写。但组合起来,它们让角色从"播放剪辑"升级到"在游戏世界里真实地活着"。retargeting 让动画资产跨角色复用,morph target 让脸会笑会哭,root motion 让脚咬住地面,two-bone IK 让手脚跟环境互动。这四个加上前两篇的骨骼动画 + blend tree + HFSM,就是工业级角色动画的全部基础。再往上就是 Motion Matching / 神经动画的研究领域,但那是建立在这四个技术都扎实的前提上的。

下一篇建议学 **physics-driven animation**(物理驱动动画)——布料、头发、绳索、肌肉,它们在骨骼动画之上又加一层物理仿真,让角色在跑动时衣服飘、头发甩、肌肉晃。
