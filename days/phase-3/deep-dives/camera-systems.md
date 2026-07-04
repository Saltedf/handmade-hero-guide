
# 摄像机系统深度专题

> 你跟着 HH Day 80 写完了基础 3D 渲染。你能在屏幕上画出一个立方体,摄像机固定在 (0, 0, 5) 看向原点。然后你想做"鼠标转视角"——按住右键拖动,镜头转。你写了 `yaw += dx * 0.01; pitch += dy * 0.01;` 然后构造 view matrix。试运行——镜头转是转了,但 pitch 转过 90° 后镜头就开始"翻转",XYZ 轴乱跳。你查文档,发现这叫 **gimbal lock**(万向节锁)。你转而学四元数(quaternion),但读了一堆公式还是不会用。今天这一篇,我们把摄像机系统的每一层从零搭起来——从 Euler 角的坑,到四元数,到第三人称跟随,到摄像机碰撞,到 cinematic。

## 0 · 为什么要有这一篇

Handmade Hero 里 Casey 用了 16 集涉及摄像机:View matrix 构造、第一人称、第三人称、镜头震屏、镜头切换。摄像机不是"一个组件"——它是**渲染、输入、物理、动画四个子系统交汇的地方**。搞错一层,玩家立刻感觉到"摄像机不舒服"——这种不舒服在工业里叫 "camera sickness",是玩家弃游戏的第一大原因(超过剧情差 / 操作难)。

**这一篇要回答**:

1. 为什么"摄像机"等于"世界逆变换"?它和 model matrix 是什么关系?
2. 透视投影 vs 正交投影,什么场景用什么?
3. 鼠标转视角的 Euler 写法为什么有 gimbal lock?四元数怎么解决?
4. 第三人称跟随相机怎么写?lerp 还是 spring?
5. 镜头穿过墙怎么处理(camera collision)?
6. cinematic(过场动画)镜头怎么切换?
7. HiDPI 屏的"逻辑像素 vs 物理像素"和摄像机有什么关系?

**学完这一篇,你应该能**:
- 从零构造 view matrix 和 projection matrix
- 在 Bevy / 自己的引擎里实现第一人称 + 第三人称
- 解释四元数的几何意义和避免 gimbal lock 的原理
- 处理摄像机碰撞(球扫式 sphere sweep)
- 实现 cinematic 镜头过渡(平滑切换)

## 1 · 摄像机的数学模型

### 1.1 摄像机是什么

3D 渲染的核心公式:

```
clip_pos = projection × view × model × local_pos
```

- `model` 矩阵:把模型的**本地坐标**转成**世界坐标**。
- `view` 矩阵:把**世界坐标**转成**摄像机坐标**(摄像机在原点,看向 -Z)。
- `projection` 矩阵:把**摄像机坐标**转成**裁剪坐标**(NDC,Normalized Device Coordinates,[-1, 1]³)。

**关键洞察**:摄像机不是一个"对象",它是**一个变换矩阵**。`view = inverse(camera_world_transform)`。也就是说:**把世界变换到摄像机本地坐标系 = 摄像机世界变换的逆**。

这是为什么 Unity / Unreal 的摄像机有 `transform`(位置 + 朝向),引擎自动算 `view = inverse(transform)`。

### 1.2 look-from / look-at / up 约定

业界构造 view matrix 的标准 API:

```rust
fn look_at(eye: Vec3, target: Vec3, up: Vec3) -> Mat4 {
    let f = (target - eye).normalize();  // forward
    let s = f.cross(&up).normalize();     // right
    let u = s.cross(&f);                  // true up(重新计算,确保正交)

    // view matrix = inverse(camera_transform)
    // camera_transform 的旋转部分是 [s, u, -f]
    // view 的旋转部分是其转置
    Mat4::new(
        s.x, u.x, -f.x, 0.0,
        s.y, u.y, -f.y, 0.0,
        s.z, u.z, -f.z, 0.0,
        -s.dot(&eye), -u.dot(&eye), f.dot(&eye), 1.0,
    )
}
```

**约定差异**(常见踩坑):
- **OpenGL**:摄像机看 -Z,up = +Y,右手坐标系。这是 gluLookAt 的约定。
- **DirectX**:摄像机看 +Z,up = +Y,左手坐标系。
- **Unity**:左手系,看 +Z。
- **Unreal**:左手系,看 +X(注意是 X 而非 Z)。
- **Vulkan / WebGPU / Bevy**:右手系,看 -Z。和 OpenGL 一致。

Bevy 用右手系看 -Z:

```rust
use bevy::math::Mat4;
let view = Mat4::look_at_rh(
    Vec3::new(0.0, 0.0, 5.0),  // eye
    Vec3::ZERO,                 // target
    Vec3::Y,                    // up
);
```

### 1.3 把"摄像机"想成对象

虽然数学上是"逆变换",但代码里更自然的是把摄像机当对象:

```rust
struct Camera {
    pos: Vec3,
    forward: Vec3,
    up: Vec3,
}

impl Camera {
    fn view_matrix(&self) -> Mat4 {
        look_at(self.pos, self.pos + self.forward, self.up)
    }
}
```

这样你只需要管理 `pos` 和 `forward`,view matrix 自动算。

## 2 · 透视 vs 正交投影

### 2.1 透视投影

模拟人眼——离得远的物体看起来小。

```rust
fn perspective(fovy: f32, aspect: f32, near: f32, far: f32) -> Mat4 {
    let f = 1.0 / (fovy / 2.0).tan();
    Mat4::new(
        f / aspect, 0.0, 0.0, 0.0,
        0.0, f, 0.0, 0.0,
        0.0, 0.0, (far + near) / (near - far), -1.0,
        0.0, 0.0, (2.0 * far * near) / (near - far), 0.0,
    )
}
```

**参数**:
- `fovy`:垂直视角(field of view),弧度。典型 60° (1.05 rad) 到 90° (1.57 rad)。
- `aspect`:宽高比 = width / height。1920×1080 → 16/9 ≈ 1.78。
- `near`:近平面距离。**绝不能为 0**。典型 0.1。
- `far`:远平面距离。典型 1000。

**near 平面的重要性**:near 太小(0.001)会导致深度精度问题——远处的 z-fighting(深度冲突)。经验:near 越大越好,只要不裁掉玩家。

**reverse-Z trick**(工业优化):把 near 和 far 反过来 + 用浮点深度缓冲,极大提升深度精度。Bevy / Unity / Unreal 都用这个。

```rust
// reverse-Z
fn perspective_reverse_z(fovy: f32, aspect: f32, near: f32, far: f32) -> Mat4 {
    let f = 1.0 / (fovy / 2.0).tan();
    Mat4::new(
        f / aspect, 0.0, 0.0, 0.0,
        0.0, f, 0.0, 0.0,
        0.0, 0.0, near / (near - far), -1.0,
        0.0, 0.0, (far * near) / (near - far), 0.0,
    )
}
```

### 2.2 正交投影

平行投影——远近物体大小一样。用于 2D 游戏、UI、CAD。

```rust
fn ortho(left: f32, right: f32, bottom: f32, top: f32, near: f32, far: f32) -> Mat4 {
    Mat4::new(
        2.0 / (right - left), 0.0, 0.0, 0.0,
        0.0, 2.0 / (top - bottom), 0.0, 0.0,
        0.0, 0.0, -2.0 / (far - near), 0.0,
        -(right + left) / (right - left),
        -(top + bottom) / (top - bottom),
        -(far + near) / (far - near),
        1.0,
    )
}
```

**2D 游戏用法**:摄像机 = 正交投影 + view matrix(只有平移和缩放,没有旋转或旋转固定为 0)。

### 2.3 何时用什么

| 场景 | 投影 | 理由 |
|---|---|---|
| 3D 第一人称 | 透视 | 沉浸感 |
| 3D 第三人称 | 透视 | 沉浸感 |
| 2D 横版 | 正交 | 没有透视畸变 |
| UI / HUD | 正交 | 不受摄像机影响 |
| 小地图 | 正交 | 俯视,等大 |
| 战略游戏 | 透视(广 FOV) | 略带立体感 |

工业级做法:**渲染两遍**——3D 物体用透视,UI 用正交。这是 Bevy 的 Camera 实现。

## 3 · 鼠标转视角:Euler vs 四元数

### 3.1 Euler 角的写法

最直觉的"鼠标转视角":

```rust
struct Camera {
    pos: Vec3,
    yaw: f32,    // 水平转(绕 Y 轴)
    pitch: f32,  // 垂直转(绕 X 轴)
}

impl Camera {
    fn forward(&self) -> Vec3 {
        let cos_p = self.pitch.cos();
        Vec3::new(
            self.yaw.sin() * cos_p,
            self.pitch.sin(),
            -self.yaw.cos() * cos_p,
            // 注意:看向 -Z 时 yaw=0,pitch=0
        )
    }
}

fn handle_mouse(cam: &mut Camera, dx: f32, dy: f32) {
    cam.yaw += dx * 0.005;
    cam.pitch += dy * 0.005;
    // 限制 pitch 不能 ±90°
    cam.pitch = cam.pitch.clamp(-1.55, 1.55);  // ≈ ±89°
}
```

**关键细节**:
- `pitch` 必须 clamp 到 ±89°,不能到 90°。**为什么**?90° 时 forward 完全沿 Y 方向,look_at 的 `up` 和 `forward` 平行,cross product 为零,矩阵退化。
- `dx * 0.005` 的 0.005 是鼠标 sensitivity,可调。

这种写法**对 FPS 游戏够用**——pitch 永远不到 90°。但如果做飞行模拟器(pitch 可任意),Euler 会爆。

### 3.2 Gimbal lock

Euler 角的根本问题:**当两个轴重合时,失去一个自由度**。

经典场景:pitch 到 90°(看正上方)时,继续移动鼠标,你期望 yaw 移动(左右转头)。但实际世界看起来在"滚"——因为 pitch=90 时 yaw 和 roll 重合,无法区分。

这是为什么飞行模拟器(可以任意 360° 转)不能用 Euler。**解决方案**:四元数。

### 3.3 四元数入门

四元数是 Hamilton 1843 年发明的扩展复数:`q = w + xi + yj + zk`,4 个分量。

四元数表示旋转的方式:
- `(w, x, y, z)`,其中 `w² + x² + y² + z² = 1`(单位四元数)
- 等价于绕轴 `(x, y, z)` 旋转 `2·acos(w)` 弧度

四元数的优势:
- **无 gimbal lock**(任何旋转序列都能表示)
- **组合简单**:`q1 * q2`(四元数乘法)就是旋转复合
- **插值平滑**:`slerp(q1, q2, t)` 球面线性插值,旋转动画用
- **省空间**:4 个 float vs 旋转矩阵 9 个

Rust 的 `glam` / `cgmath` / `nalgebra` 都有 Quat:

```rust
use glam::Quat;

// 绕 Y 轴转 90°
let q = Quat::from_rotation_y(std::f32::consts::FRAC_PI_2);

// 组合两个旋转(先 q1 后 q2)
let combined = q2 * q1;

// 把向量旋转
let v = q * Vec3::X;

// slerp
let t = 0.5;
let interpolated = Quat::slerp(q1, q2, t);
```

### 3.4 用四元数的鼠标转视角

```rust
use glam::{Quat, Vec3};

struct Camera {
    pos: Vec3,
    rotation: Quat,  // 摄像机朝向(四元数)
}

impl Camera {
    fn forward(&self) -> Vec3 {
        self.rotation * Vec3::NEG_Z  // Bevy 约定看 -Z
    }

    fn view_matrix(&self) -> Mat4 {
        Mat4::look_at_rh(self.pos, self.pos + self.forward(), Vec3::Y)
    }
}

fn handle_mouse(cam: &mut Camera, dx: f32, dy: f32) {
    // 绕世界 Y 轴 yaw(水平)
    let yaw_q = Quat::from_rotation_y(-dx * 0.005);
    // 绕摄像机本地 X 轴 pitch(垂直)
    let pitch_q = Quat::from_rotation_x(-dy * 0.005);

    // 先 yaw 再 pitch(顺序很重要)
    cam.rotation = yaw_q * cam.rotation * pitch_q;
    // 重新归一化(防止 float 误差累积)
    cam.rotation = cam.rotation.normalize();
}
```

注意 `yaw_q * cam.rotation * pitch_q` 的顺序——四元数乘法**不交换**。这个顺序保证 yaw 绕世界轴(不受当前 pitch 影响),pitch 绕摄像机本地轴(不影响 yaw 方向)。

**额外好处**:这种写法支持任意 360° 旋转——飞行模拟器 / 太空游戏标配。

### 3.5 为什么归一化

四元数必须是**单位四元数**(模长 1)才能表示纯旋转。浮点运算有误差,反复乘法后模长会偏离 1。每帧 `normalize` 是必需的。否则摄像机会"逐渐变形"。

## 4 · 第三人称跟随相机

### 4.1 基本结构

第三人称相机跟随玩家,位置和朝向都"指向"玩家。

```rust
struct ThirdPersonCamera {
    target: Entity,           // 跟随谁
    distance: f32,            // 距离
    height: f32,              // 高度
    look_at_offset: Vec3,     // 看向玩家的偏移(比如头部)
}

fn update_camera(
    cam: &mut ThirdPersonCamera,
    transforms: &Query<&Transform>,
    cam_transform: &mut Transform,
) {
    let target_tf = transforms.get(cam.target).unwrap();
    let target_pos = target_tf.translation + cam.look_at_offset;

    // 摄像机位置 = target - forward * distance + up * height
    let forward = target_tf.forward();
    let cam_pos = target_pos - forward * cam.distance + Vec3::Y * cam.height;

    cam_transform.translation = cam_pos;
    cam_transform.look_at(target_pos, Vec3::Y);
}
```

这种"硬绑"摄像机**非常僵硬**——玩家急停时摄像机瞬间跟随,玩家头晕。

### 4.2 Lerp 平滑

工业实践:摄像机位置和朝向用 lerp(线性插值)平滑过渡。

```rust
// 每帧:
let desired_pos = compute_desired_pos(...);
let actual_pos = cam_transform.translation;
cam_transform.translation = actual_pos.lerp(desired_pos, 0.1);
```

`0.1` 是 lerp 因子。0 = 不动,1 = 瞬移。`0.1` 意味着"每帧追 10% 差距"。

**lerp 的物理学**:这种写法等价于**指数衰减**——距离以 10% / 帧的速度衰减。如果游戏 60 FPS,5 帧后距离变成 0.9^5 = 0.59,即 1 秒衰减到 30%。

**lerp 的帧率独立性坑**:lerp 因子 0.1 在 60 FPS 等价于 0.18 在 30 FPS——帧率影响感觉。工业做法:

```rust
// 帧率独立的指数平滑
let alpha = 1.0 - (-delta_time * speed).exp();
cam_transform.translation = actual_pos.lerp(desired_pos, alpha);
```

`speed` 是"每秒衰减速率",`speed = 5` 意味着距离每秒衰减到 e^-5 ≈ 0.7%。

### 4.3 Spring(弹簧)相机

lerp 平滑但**永远滞后**——快速移动时摄像机一直追在后面。工业游戏(God of War / The Last of Us)用**弹簧物理**:

```rust
struct SpringCamera {
    pos: Vec3,
    vel: Vec3,           // 摄像机当前速度
    stiffness: f32,      // 弹簧硬度(典型 50-200)
    damping: f32,        // 阻尼(典型 5-20)
}

fn update(cam: &mut SpringCamera, target_pos: Vec3, dt: f32) {
    // 弹簧力:F = -k(x - target) - c·v
    let force = (target_pos - cam.pos) * cam.stiffness
              - cam.vel * cam.damping;
    // 加速度 = F / mass(mass=1)
    let accel = force;
    cam.vel += accel * dt;
    cam.pos += cam.vel * dt;
}
```

**好处**:
- 摄像机有"惯性感"。
- 可以略微超越目标(spring overshoot),看起来有"弹性"。
- 调 stiffness / damping 控制感觉。

**典型调参**:stiffness=150, damping=10。可以查 spring physics 文档获得更多。

## 5 · 摄像机碰撞

### 5.1 问题

第三人称相机在墙边时,摄像机会穿墙——玩家看不到自己角色,只看到墙内部。

### 5.2 Sphere sweep(球扫式)

工业做法:从玩家位置出发,沿摄像机方向做"球扫式"射线检测。如果碰到墙,把摄像机位置缩短到碰撞点 + 球半径。

```rust
fn update_camera_with_collision(
    player_pos: Vec3,
    desired_cam_pos: Vec3,
    physics: &PhysicsWorld,
) -> Vec3 {
    let direction = desired_cam_pos - player_pos;
    let distance = direction.length();
    let direction = direction.normalize();

    // 球扫式射线
    let sphere_radius = 0.3;
    if let Some(hit) = physics.sphere_cast(
        player_pos,
        direction,
        distance,
        sphere_radius,
    ) {
        // 碰到了,把摄像机放碰撞点稍前
        let safe_distance = (hit.distance - sphere_radius).max(0.1);
        player_pos + direction * safe_distance
    } else {
        desired_cam_pos
    }
}
```

### 5.3 退路

如果碰撞让摄像机太近(< 0.5m),工业实践:
- **隐藏玩家角色**(避免遮挡)
- **淡化墙**(透明化)
- **切到第一人称**

God of War 用前两者,The Last of Us 用第三者。

## 6 · Cinematic(过场)

### 6.1 镜头切换

剧情过场需要多镜头切换。设计:

```rust
struct CinematicShot {
    duration: f32,
    pos: Vec3,
    target: Vec3,
    fov: f32,
}

struct CinematicSequence {
    shots: Vec<CinematicShot>,
    current_shot: usize,
    time_in_shot: f32,
}

fn update(seq: &mut CinematicSequence, cam: &mut Camera, dt: f32) {
    if seq.current_shot >= seq.shots.len() { return; }
    let shot = &seq.shots[seq.current_shot];

    // 平滑过渡(用 slerp + lerp)
    let alpha = (seq.time_in_shot / 0.5).min(1.0);  // 0.5s 过渡
    cam.pos = cam.pos.lerp(shot.pos, alpha);
    cam.fov = cam.fov.lerp(shot.fov, alpha);

    seq.time_in_shot += dt;
    if seq.time_in_shot > shot.duration {
        seq.current_shot += 1;
        seq.time_in_shot = 0.0;
    }
}
```

工业库:Unreal 的 Sequencer、Unity 的 Cinemachine。Rust 的 `bevy_cinematic`。

### 6.2 Bevy 的 Camera 系统

Bevy 把摄像机做成 entity:

```rust
commands.spawn(Camera3dBundle {
    transform: Transform::from_xyz(0.0, 5.0, 10.0).looking_at(Vec3::ZERO, Vec3::Y),
    projection: Projection::Perspective(PerspectiveProjection {
        fov: 60.0_f32.to_radians(),
        ..default()
    }),
    ..default()
});
```

切换摄像机:把一个 Camera 的 `is_active` 设为 false,另一个设为 true。

## 7 · 帧率、Vsync、HiDPI

### 7.1 Vsync

Vsync(垂直同步):GPU 等到显示器垂直回扫期间才 swap buffer。开启时帧率上限 = 显示器刷新率(60 / 120 / 144 Hz)。

**作用**:防止 tearing(画面上下半刷新不同步)。
**副作用**:增加 input latency(输入延迟 1 帧)。

工业游戏提供选项:
- Off(最高帧率,可能 tearing)
- On(无 tearing,有延迟)
- Adaptive(低于刷新率关 vsync,高于开)

Bevy / wgpu 默认开 vsync:

```rust
Window {
    present_mode: bevy::window::PresentMode::AutoVsync,
    ..default()
}
```

### 7.2 HiDPI

HiDPI(高 DPI):苹果 Retina、4K 屏。一个逻辑像素对应 2×2 物理像素。

```rust
// Bevy
fn log_dpi(windows: Query<&Window>) {
    for w in windows.iter() {
        println!("Logical: {}x{}", w.width(), w.height());
        println!("Physical: {}x{}", w.physical_width(), w.physical_height());
        println!("Scale factor: {}", w.scale_factor());
    }
}
```

**关键**:摄像机投影矩阵用 **logical 或 physical 都可以**,但要一致。Bevy 内部用 logical(屏幕坐标 = logical)。如果你的 UI 算 pixel,要乘 scale_factor。

### 7.3 帧率独立的运动

游戏逻辑必须 **frame-rate independent**——60 FPS 和 144 FPS 表现一致。

```rust
// 错(帧率依赖)
pos += vel;

// 对(帧率独立)
pos += vel * dt;
```

`dt` 是上一帧时间,从 `Time` 资源拿:

```rust
fn move_player(mut q: Query<&mut Transform, With<Player>>, time: Res<Time>) {
    for mut tf in q.iter_mut() {
        tf.translation.x += 5.0 * time.delta_seconds();
    }
}
```

## 8 · Rust 生态速查

### 8.1 数学库

| crate | 用途 |
|---|---|
| `glam` | Bevy 默认,游戏数学 |
| `cgmath` | 老牌,纯 Rust |
| `nalgebra` | 科学计算,游戏可 |
| `mint` | 通用接口 |

### 8.2 Bevy 摄像机相关

| crate | 用途 |
|---|---|
| `bevy::render::camera` | 标准 |
| `bevy_cinematic` | 过场 |
| `bevy_dolly` | 摄像机 rigs |
| `bevy_screen_dirt` | 屏幕特效 |

### 8.3 推荐顺序

1. 先用 Bevy 的 Camera3dBundle 做第一人称。
2. 加 quaternion 鼠标控制。
3. 改成第三人称(lerp)。
4. 加 spring physics。
5. 加碰撞。
6. 加 cinematic sequence。

## 9 · 延伸阅读

- LearnOpenGL 摄像机章节:https://learnopengl.com/Getting-started/Camera
- gluLookAt 文档(经典):https://www.khronos.org/registry/OpenGL-Refpages/gl2.1/xhtml/gluLookAt.xml
- Reverse-Z 技巧:https://developer.nvidia.com/content/depth-precision-visualized
- 四元数可视化:https://eater.net/quaternions
- Smooth and Spring Camera:https://www.gamedeveloper.com/programming/introduction-to-centered-camera-math
- Bevy 摄像机源码:https://github.com/bevyengine/bevy/tree/main/crates/bevy_render/src/camera
- Cinemachine 文档:https://docs.unity3d.com/Packages/com.unity.cinemachine@2.9/manual/index.html
- Casey HH 摄像机相关 day:Day 80 / 82 / 85 / 90 / 110 / 115 / 125 / 130
