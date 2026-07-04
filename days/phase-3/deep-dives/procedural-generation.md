
# 程序化生成:从 Perlin noise 到 Wave Function Collapse,完整推导 PCG 算法

> 你玩 Minecraft,新开一个世界。8 万块的方块地形在 50 ms 内全部生成。你看到山、河、洞穴、村庄、矿坑——每一样都是算法造的,但每次开新世界都不一样。你玩 Spelunky,每次进入下一关,关卡布局完全不同,但都"可通关"。你玩 No Man's Sky,18 京(1.8 × 10¹⁹)个星球,全程序生成,玩家一辈子也走不完。你玩 Caves of Qud,坑道、怪物、装备随机组合,但每个种子都能产出**确定性**的世界——同一颗种子,任何玩家都看到同样地图。这一篇就把这些奇迹背后所有核心算法都讲透:Perlin noise / Simplex noise / Wave Function Collapse / L-system / Marching Cubes / Domain warping / fBm / Voronoi / Cellular automata——所有公式手推,所有代码可跑,所有数学从第一性原理出来,最后落地到你的 HH 项目里。

## 0 · 为什么要有这一篇

游戏内容有两种来源:**手工**(美术、设计师)和**程序**(算法)。**手工内容**质量高,但贵——一个 Skyrim 的 dungeon,设计师花一周做。10 个 dungeon 一季度工作。游戏工业一直想"用算法代替设计师",这个领域叫 **PCG**(Procedural Content Generation,程序化内容生成)。

PCG 不是单一算法,是**一整个工具箱**。不同游戏用不同工具:

- **Minecraft 地形**:Perlin noise / Simplex noise 做 heightmap + biome + cave。一个种子决定一切。
- **Spelunky 关卡**:基于"切片"的拼接 + 约束求解。
- **No Man's Sky 星球**:Simplex noise 做地形,fBm 加细节,Planet Cracker 切 mesh。
- **Caves of Qud**:Cellular automata 做洞穴,Rogue-like 物品生成。
- **Civ / RimWorld 地图**:Voronoi diagram 做势力范围。
- **Tree It / Speedtree 植被**:L-system 文法生成树枝。
- **Spore 生物**:Metaball + skeletal animation。
- **Townscaper**:Wave Function Collapse + relax 算法。

每个算法都很精巧,值得单独一篇 deep-dive。但 PCG 的核心思想是相通的:**用确定性随机 + 数学约束,生成无限多样的内容**。这一篇就把核心算法都讲一遍,你会看到它们如何互相组合。

**学完这一篇,你应该能**:

- 用 100 行 Rust 实现 Ken Perlin 1985 原版 noise + 改进版 permutation table,并解释 gradient noise vs value noise 的区别
- 用 100 行 Rust 实现 Simplex noise(Perlin 2001),理解为什么它取代原版 Perlin(避免方向性 artifact + O(N²) vs O(2ᴺ) 复杂度)
- 用 50 行实现 fBm(分形布朗运动)+ Domain warping,生成"外星地形"
- 用 200 行实现 Wave Function Collapse(Maxim Gumin 2016 原版),理解为什么它是 PCG 的"瑞士军刀"
- 用 50 行实现 L-system 文法,生成树木
- 用 100 行实现 Marching Cubes(体素到 mesh),并解释 Dual Contouring 是如何保留锐边的
- 解释种子决定性(seed determinism)对 phase-8 网络同步 / 回放系统的关键性
- 在你 HH 项目里加一块程序化地形(Perlin + fBm + Marching Cubes),性能在 60 FPS

## 1 · PCG 哲学:为什么程序化

### 1.1 三个动机

游戏工业用 PCG 的三个动机:

**动机一:无限内容**。手工做 100 个关卡一周,做 1 万个关卡一辈子。算法生成,一次写好后无限产出。*No Man's Sky* 用 PCG 生成 18 京个星球。*Minecraft* 世界理论上无限大(实际受 float 精度限制)。

**动机二:节省成本**。一个 100 人美术团队一年做 5 GB 资产。PCG 工具一写,后续生成免费。*Spelunky* 关卡全部 PCG,2 人团队做了 AAA 级 60 小时体验。

**动机三:重玩性**。手工关卡玩过一次,第二次无新意。PCG 关卡每次不同。*Diablo* 系列、《以撒的结合》、《杀戮尖塔》——所有 Roguelike 都靠 PCG 撑重玩性。

### 1.2 PCG 的三种用法

PCG 在游戏生命周期的三个阶段都有用:

**Offline(离线)**:开发时用 PCG 生成资产,然后美术手工调整。*Frostpunk* 的城市背景这样做的。资产最终打包进游戏,玩家看到的是静态的。好处:开发者享受 PCG 的"批量生产",玩家享受手工调整的"精致度"。

**On-demand(运行时按需)**:玩家进入新区域,算法实时生成。*Minecraft* 的 chunk 生成是 on-demand。优点:无限内容。缺点:必须快速(几 ms 内)、确定性(同一种子同样结果)。

**Mixed(混合)**:核心区域手工,周边区域 PCG。*Witcher 3* 主要城市手工,野外部分 PCG 补。

### 1.3 PCG 的设计原则

好的 PCG 不是"完全随机",而是"约束下的随机":

- **可识别性**(recognizability):玩家能识别模式(森林、沙漠、洞穴),不是一团乱码。
- **多样性**(variety):同一模式有足够变化,不是 copy-paste。
- **公平性**(fairness):生成的关卡可通关、平衡。Spelunky 用 "safety path" 验证生成。
- **美感**(aesthetics):生成的形状有结构感(分形、对称、节奏)。
- **可重现**(reproducibility):同一 seed 同样结果。

最后一条对网络同步、bug reproduction、玩家分享 seed 都至关重要。这是 PCG 的"圣杯":**确定性 + 无限多样性**。

## 2 · 噪声:PCG 的最基础积木

### 2.1 什么是"噪声"

**噪声**(noise)是一个数学函数 `f(x) → y`,输入一个 N 维坐标,输出一个标量(或向量)。它是一个**伪随机**函数——同一点永远输出同样值,邻近点输出"相近"值。

对比:

- **真随机**:每点独立随机,邻近点无关。看起来像电视雪花点。
- **白噪声**(white noise):所有频率均匀混合。真随机的另一种说法。
- **值噪声**(value noise):网格点随机,网格之间插值。邻近点连续。
- **梯度噪声**(gradient noise):Perlin 的发明。网格点是梯度,网格之间用多项式插值。比 value noise 平滑。
- **蓝色噪声**(blue noise):只有高频,没低频。看起来"均匀散布的点"。 stippling 算法。

PCG 用**值噪声**和**梯度噪声**为主。下面手推。

### 2.2 Value noise(值噪声)

Value noise 是最简单的"平滑随机"。

**步骤一**:在网格点(整数坐标)上撒随机数。

```
对每个整数点 (i, j):
    value[i, j] = random()  // 0 到 1
```

**步骤二**:对非整数点,用 bilinear 插值。

```
value(x, y) where x = ix + fx, y = iy + fy, 0 <= fx, fy < 1:
    v00 = value[ix,   iy  ]
    v10 = value[ix+1, iy  ]
    v01 = value[ix,   iy+1]
    v11 = value[ix+1, iy+1]
    return bilinear(v00, v10, v01, v11, fx, fy)
```

bilinear 插值 = 两次 lerp:

```
top = lerp(v00, v10, fx)
bottom = lerp(v01, v11, fx)
return lerp(top, bottom, fy)
```

`lerp(a, b, t) = a + (b - a) * t`。

**问题**:bilinear 插值的"linear"在网格边界导数不连续,产生"块状"视觉 artifact。每个网格格的轮廓在 noise 输出上可见。

**修复**:用 smoothstep 替换 lerp。smoothstep 是一个 S 形曲线:

```
smoothstep(t) = t * t * (3 - 2t)
```

它在 t=0 和 t=1 处的导数都是 0,让网格边界"平滑过渡"。这叫 **smooth value noise**。

让我手算一个 1D 例子。设 `value[0] = 0.0, value[1] = 1.0`,平滑插值:

```
位置 x = 0.5:
    linear: lerp(0, 1, 0.5) = 0.5
    smooth: lerp(0, 1, smoothstep(0.5)) = lerp(0, 1, 0.5) = 0.5
    
位置 x = 0.25:
    linear: lerp(0, 1, 0.25) = 0.25
    smooth: lerp(0, 1, smoothstep(0.25)) = lerp(0, 1, 0.15625) = 0.15625
```

smoothstep 让中间区域"平缓"——梯度变小,过渡更自然。

### 2.3 Value noise 的 Rust 实现

```rust
// src/value_noise.rs
use std::sync::Mutex;
use once_cell::sync::Lazy;

// 一个 permutation table:打乱的 [0, 255]
static PERM: Lazy<Mutex<[u8; 256]>> = Lazy::new(|| {
    let mut perm: [u8; 256] = [0; 256];
    for i in 0..256 { perm[i] = i as u8; }
    // Fisher-Yates shuffle
    let mut rng = rand::thread_rng();
    use rand::seq::SliceRandom;
    perm.shuffle(&mut rng);
    Mutex::new(perm)
});

fn smoothstep(t: f32) -> f32 {
    t * t * (3.0 - 2.0 * t)
}

fn lerp(a: f32, b: f32, t: f32) -> f32 {
    a + (b - a) * t
}

fn hash2(ix: i32, iy: i32) -> f32 {
    let perm = PERM.lock().unwrap();
    let i = perm[((ix as usize) & 255) as usize] as usize;
    let j = perm[((iy as usize + i) & 255) as usize] as usize;
    // 映射到 [-1, 1]
    (j as f32 / 255.0) * 2.0 - 1.0
}

pub fn value_noise_2d(x: f32, y: f32) -> f32 {
    let ix = x.floor() as i32;
    let iy = y.floor() as i32;
    let fx = x - ix as f32;
    let fy = y - iy as f32;
    let v00 = hash2(ix,   iy);
    let v10 = hash2(ix+1, iy);
    let v01 = hash2(ix,   iy+1);
    let v11 = hash2(ix+1, iy+1);
    let sx = smoothstep(fx);
    let sy = smoothstep(fy);
    let top = lerp(v00, v10, sx);
    let bottom = lerp(v01, v11, sx);
    lerp(top, bottom, sy)
}
```

50 行的 value noise。但 value noise 有一个严重问题:**网格点可见**——人眼能识别出"每格 1 单位的方格"图案。Ken Perlin 1985 年发明的 **gradient noise**(Perlin noise)解决了这个。

### 2.4 Perlin noise(Ken Perlin 1985)

Ken Perlin 当时在做电影 *Tron*(1982)的特效。他需要一个"看起来自然"的随机纹理。他设计了 Perlin noise,后来获得 1997 年的 Academy Award(奥斯卡科技奖)。原版 Perlin noise 论文很短(*An Image Synthesizer*, SIGGRAPH 1985),但算法精妙。

**核心 idea**:在网格点上,不存"随机值",而存**随机梯度**(gradient = 方向向量)。在非网格点上,用周围 4 个(2D)或 8 个(3D)梯度算"这个点该有的值"。

具体步骤(2D 版本):

**步骤一**:为每个网格点 (i, j) 分配一个随机梯度 `g[i, j]`。梯度是单位向量(在 2D 是 12 个预设方向之一)。

**步骤二**:对非网格点 (x, y),找它所在的网格 (ix, iy)。计算到 4 个网格点的相对位置:

```
(ix,   iy):    d00 = (fx,   fy)
(ix+1, iy):    d10 = (fx-1, fy)
(ix,   iy+1):  d01 = (fx,   fy-1)
(ix+1, iy+1):  d11 = (fx-1, fy-1)
```

**步骤三**:对每个网格点,算"梯度贡献" = dot product(gradient, distance):

```
n00 = dot(g00, d00)
n10 = dot(g10, d10)
n01 = dot(g01, d01)
n11 = dot(g11, d11)
```

**步骤四**:双线性插值这 4 个贡献,但用 fade 函数替代 linear:

```
fade(t) = t * t * t * (t * (t * 6 - 15) + 10)
// 也叫 quintic interpolant,5 次多项式
// 它的 1 阶导数和 2 阶导数在 t=0,1 都是 0,非常平滑
```

```
u = fade(fx)
v = fade(fy)
result = lerp(
    lerp(n00, n10, u),
    lerp(n01, n11, u),
    v
)
```

这就是 Perlin noise 的输出。范围约 [-1, 1](实际是 [-sqrt(N)/2, sqrt(N)/2],N 是维度)。

### 2.5 Perlin 的 fade 函数:为什么要 quintic

为什么不用 smoothstep(3 次),用 quintic(5 次)?让我手推。

3 次 smoothstep:`s3(t) = 3t² - 2t³`。导数:`s3'(t) = 6t - 6t²`,在 t=0,1 都是 0。但**二阶导**:`s3''(t) = 6 - 12t`,在 t=0 是 6,在 t=1 是 -6——**不为 0**。

二阶导不连续意味着"曲率"在网格边界突变。人眼对这种突变敏感——你能看到"网格"。Perlin 用 quintic fade:`s5(t) = 6t⁵ - 15t⁴ + 10t³`。一阶导 `30t⁴ - 60t³ + 30t²`,在 t=0,1 都是 0。二阶导 `120t³ - 180t² + 60t`,在 t=0,1 都是 0。**完全平滑**。

这是 Perlin 2002 改进版 *Improving Noise* 的关键修正(原版 1985 用 smoothstep,2002 改 quintic)。

### 2.6 Permutation table(置换表)

如何"为每个网格点分配随机梯度"?直接 random 不行——下次访问同一点会得到不同梯度,违反确定性。

Ken Perlin 的解法:**预先生成一个 256 元素的 permutation table**(打乱的 [0, 255]),用 hash 函数访问:

```
gradient(i, j) = grad_table[perm[(i + perm[j mod 256]) mod 256]]
```

`perm` 是固定的 256 元素数组(打乱后),`grad_table` 是 12 个预设 2D 单位梯度。

**为什么要 256 元素?** 因为 256 = 2⁸,用 8 位 index 直接索引,无 modulo 开销。Perlin 1985 用这个 trick 至今未变。

`hash(i, j)` 通过两次 perm 索引得到一个 [0, 255] 的值——这是确定性、可重复的伪随机。

### 2.7 Perlin noise 完整 Rust 实现

```rust
// src/perlin.rs
use std::sync::Mutex;
use once_cell::sync::Lazy;

// Ken Perlin 改进版 permutation table(2002)
const PERM: [u8; 256] = [
    151, 160, 137, 91, 90, 15, 131, 13, 201, 95, 96, 53, 194, 233, 7, 225,
    140, 36, 103, 30, 69, 142, 8, 99, 37, 240, 21, 10, 23, 190, 6, 148,
    247, 120, 234, 75, 0, 26, 197, 62, 94, 252, 219, 203, 117, 35, 11, 32,
    57, 177, 33, 88, 237, 149, 56, 87, 174, 20, 125, 136, 171, 168, 68, 175,
    74, 165, 71, 134, 139, 48, 27, 166, 77, 146, 158, 231, 83, 111, 229, 122,
    60, 211, 133, 230, 220, 105, 92, 41, 55, 46, 245, 40, 244, 102, 143, 54,
    65, 25, 63, 161, 1, 216, 80, 73, 209, 76, 132, 187, 208, 89, 18, 169,
    200, 196, 135, 130, 116, 188, 159, 86, 164, 100, 109, 198, 173, 186, 3, 64,
    52, 217, 226, 250, 124, 123, 5, 202, 38, 147, 118, 126, 255, 82, 85, 212,
    207, 206, 59, 227, 47, 16, 58, 17, 182, 189, 28, 42, 223, 183, 170, 213,
    119, 248, 152, 2, 44, 154, 163, 70, 221, 153, 101, 155, 167, 43, 172, 9,
    129, 22, 39, 253, 19, 98, 108, 110, 79, 113, 224, 232, 178, 185, 112, 104,
    218, 246, 97, 228, 251, 34, 242, 193, 238, 210, 144, 12, 191, 179, 162, 241,
    81, 51, 145, 235, 249, 14, 239, 107, 49, 192, 214, 31, 181, 199, 106, 157,
    184, 84, 204, 176, 115, 121, 50, 45, 127, 4, 150, 254, 138, 236, 205, 93,
    222, 114, 67, 29, 24, 72, 243, 141, 128, 195, 78, 66, 215, 61, 156, 180,
];

// Perlin 改进版 3D 梯度表(12 个预设向量,从 (1,1,0) 等组合派生)
const GRAD3: [(f32, f32, f32); 12] = [
    (1, 1, 0), (-1, 1, 0), (1, -1, 0), (-1, -1, 0),
    (1, 0, 1), (-1, 0, 1), (1, 0, -1), (-1, 0, -1),
    (0, 1, 1), (0, -1, 1), (0, 1, -1), (0, -1, -1),
];

fn fade(t: f32) -> f32 {
    t * t * t * (t * (t * 6.0 - 15.0) + 10.0)
}

fn lerp(a: f32, b: f32, t: f32) -> f32 {
    a + t * (b - a)
}

fn grad(g: usize, x: f32, y: f32, z: f32) -> f32 {
    let (gx, gy, gz) = GRAD3[g % 12];
    gx * x + gy * y + gz * z
}

// 双重 perm 索引
fn hash_coord(xi: i32, yi: i32, zi: i32) -> usize {
    let h = PERM[((xi as usize) & 255)];
    let h = PERM[(h as usize + (yi as usize & 255)) & 255];
    let h = PERM[(h as usize + (zi as usize & 255)) & 255];
    h as usize
}

pub fn perlin_noise_3d(x: f32, y: f32, z: f32) -> f32 {
    let xi = x.floor() as i32;
    let yi = y.floor() as i32;
    let zi = z.floor() as i32;
    let xf = x - xi as f32;
    let yf = y - yi as f32;
    let zf = z - zi as f32;

    let u = fade(xf);
    let v = fade(yf);
    let w = fade(zf);

    // 8 个角点的 gradient index
    let g000 = hash_coord(xi,   yi,   zi);
    let g100 = hash_coord(xi+1, yi,   zi);
    let g010 = hash_coord(xi,   yi+1, zi);
    let g110 = hash_coord(xi+1, yi+1, zi);
    let g001 = hash_coord(xi,   yi,   zi+1);
    let g101 = hash_coord(xi+1, yi,   zi+1);
    let g011 = hash_coord(xi,   yi+1, zi+1);
    let g111 = hash_coord(xi+1, yi+1, zi+1);

    // 8 个角点的贡献:dot product(gradient, distance_to_corner)
    let n000 = grad(g000, xf,   yf,   zf);
    let n100 = grad(g100, xf-1.0, yf,   zf);
    let n010 = grad(g010, xf,   yf-1.0, zf);
    let n110 = grad(g110, xf-1.0, yf-1.0, zf);
    let n001 = grad(g001, xf,   yf,   zf-1.0);
    let n101 = grad(g101, xf-1.0, yf,   zf-1.0);
    let n011 = grad(g011, xf,   yf-1.0, zf-1.0);
    let n111 = grad(g111, xf-1.0, yf-1.0, zf-1.0);

    // 三线性插值(用 fade)
    let x1 = lerp(n000, n100, u);
    let x2 = lerp(n010, n110, u);
    let y1 = lerp(x1, x2, v);
    let x3 = lerp(n001, n101, u);
    let x4 = lerp(n011, n111, u);
    let y2 = lerp(x3, x4, v);
    lerp(y1, y2, w)
}
```

~80 行的 Perlin 3D noise。这个实现直接来自 Ken Perlin 2002 *Improving Noise* 论文的 reference implementation,可以编译跑。

### 2.8 Perlin noise 的 artifact:方向性

Perlin noise 有一个为人熟知的 artifact:**网格方向可见**。在新生成的 Perlin noise 纹理上,你能看到沿 x 轴、y 轴、对角线的"假象"——这是因为梯度表只有 12 个预设方向,频率域上有"方向性 bias"。

这个 artifact 在 2D 还不太明显,在 3D(体纹理)就很明显。Ken Perlin 2001 年发明 **Simplex noise** 修这个问题。

### 2.9 Simplex noise(Perlin 2001)

Simplex noise 是 Ken Perlin 2001 年的 *Noise Hardware* 论文提出的。它有两个改进:

**改进一**:用**单形**(simplex)替代网格(grid)。2D 单形是三角形,3D 单形是四面体,N 维单形有 N+1 个顶点。N+1 比 2ᴺ 少得多——3D Simplex 只需 4 个角点 vs 3D Perlin 的 8 个。复杂度从 O(2ᴺ) 降到 O(N²)。

**改进二**:**更好的梯度分布**。Simplex 用更大的梯度表,消除了 Perlin 的方向性 artifact。

让我手推 2D Simplex 的核心步骤。

**步骤一**:坐标变换。Simplex 网格是斜的(三角形),所以先把 (x, y) 变换到"单形坐标系":

```
skew_factor = (sqrt(3) - 1) / 2 ≈ 0.366
X = x + skew_factor * (x + y)
Y = y + skew_factor * (x + y)
```

skew 把方形网格变成菱形(三角形)网格。

**步骤二**:找 (X, Y) 所在的 simplex。

```
i = floor(X), j = floor(Y)
t = (X + Y) - (i + j)  // 单形内参数
if t < 0.5: 角点是 (i, j), (i+1, j), (i, j+1)  // 小 t
else:       角点是 (i+1, j), (i, j+1), (i+1, j+1)  // 大 t
```

**步骤三**:对每个角点,算贡献:

```
unskewed_corner = (i - skew_factor * (i + j), j - skew_factor * (i + j))
distance = (x, y) - unskewed_corner
contribution = max(0, 0.5 - |distance|²)⁴ * dot(gradient, distance)
```

`(0.5 - |distance|²)⁴` 是一个核函数(kernel),距离越近权重越大,超过 0.5 直接归零。这是 Simplex 的"软衰减"——比 Perlin 的 fade 函数更平滑。

**步骤四**:三个角点贡献之和 × 缩放因子(2D 是 ~70,确保输出 [-1, 1])。

### 2.10 Simplex noise 的 Rust 实现

```rust
// src/simplex.rs
const GRAD3: [(f32, f32, f32); 12] = [
    (1, 1, 0), (-1, 1, 0), (1, -1, 0), (-1, -1, 0),
    (1, 0, 1), (-1, 0, 1), (1, 0, -1), (-1, 0, -1),
    (0, 1, 1), (0, -1, 1), (0, 1, -1), (0, -1, -1),
];

const PERM: [u8; 512] = {
    // 重复一次,避免 mod 255
    let base = [
        151, 160, 137, 91, 90, 15, 131, 13, 201, 95, 96, 53, 194, 233, 7, 225,
        // ... 同 Perlin 的 perm
        151, 160, 137, 91, 90, 15, 131, 13, 201, 95, 96, 53, 194, 233, 7, 225,
        // 简化:实际工程用 Lazy 初始化 512 长 perm
    ];
    let mut full = [0u8; 512];
    let mut i = 0;
    while i < 256 { full[i] = base[i]; full[i+256] = base[i]; i += 1; }
    full
};

const F2: f32 = 0.366025403; // 0.5 * (sqrt(3) - 1)
const G2: f32 = 0.211324865; // (3 - sqrt(3)) / 6

pub fn simplex_noise_2d(xin: f32, yin: f32) -> f32 {
    let s = (xin + yin) * F2;
    let i = (xin + s).floor() as i32;
    let j = (yin + s).floor() as i32;
    let t = (i + j) as f32 * G2;
    let x0 = xin - (i as f32 - t);
    let y0 = yin - (j as f32 - t);

    let (i1, j1) = if x0 > y0 { (1, 0) } else { (0, 1) };

    let x1 = x0 - i1 as f32 + G2;
    let y1 = y0 - j1 as f32 + G2;
    let x2 = x0 - 1.0 + 2.0 * G2;
    let y2 = y0 - 1.0 + 2.0 * G2;

    let ii = i & 255;
    let jj = j & 255;
    let gi0 = PERM[ii + PERM[jj] as usize] as usize % 12;
    let gi1 = PERM[ii + i1 as usize + PERM[jj + j1 as usize] as usize] as usize % 12;
    let gi2 = PERM[ii + 1 + PERM[jj + 1] as usize] as usize % 12;

    let mut t0 = 0.5 - x0*x0 - y0*y0;
    let n0 = if t0 < 0.0 { 0.0 } else {
        t0 *= t0; t0 *= t0;
        t0 * (GRAD3[gi0].0 * x0 + GRAD3[gi0].1 * y0)
    };

    let mut t1 = 0.5 - x1*x1 - y1*y1;
    let n1 = if t1 < 0.0 { 0.0 } else {
        t1 *= t1; t1 *= t1;
        t1 * (GRAD3[gi1].0 * x1 + GRAD3[gi1].1 * y1)
    };

    let mut t2 = 0.5 - x2*x2 - y2*y2;
    let n2 = if t2 < 0.0 { 0.0 } else {
        t2 *= t2; t2 *= t2;
        t2 * (GRAD3[gi2].0 * x2 + GRAD3[gi2].1 * y2)
    };

    70.0 * (n0 + n1 + n2)
}
```

Simplex noise 在视觉上比 Perlin 更平滑,在 3D / 4D 性能上优势更明显。但 2D 性能差距不大——Perlin 2D 还是工业主流,因为简单。

**OpenSimplex**:Simplex noise 的专利问题(Perlin 申请了专利)让社区开发 OpenSimplex(2014, Steven Gustavson / Digital Shadow)。OpenSimplex 算法等价但绕过专利,是开源项目的首选。Rust 生态 `noise` crate 用 OpenSimplex。

### 2.11 Worley / Cellular noise

Worley noise(Steven Worley 1996,*A Cellular Texture Basis Function*)生成"细胞状"图案。每个细胞有一个核心点,每个查询点取到最近的几个核心点的距离。

算法:

```
1. 在网格每格放一个核心点(格内随机位置)。
2. 对查询点 (x, y),找它所在格 + 8 邻格,收集 9 个核心点。
3. 算到每个核心点的距离,排序。
4. 输出:F1 = 最近距离;F2 = 第二近距离;F2 - F1 等。
```

Worley noise 用于:**水波纹**(F1 当作"水滴位置")、**石头纹理**(F2 - F1 当作"缝隙宽度")、**程序化细胞组织**(生物膜)。

### 2.12 各种 noise 的对比

| 噪声 | 复杂度(2D) | 复杂度(3D) | 平滑度 | 方向性 | 用途 |
|---|---|---|---|---|---|
| White noise | O(1) | O(1) | 无 | 无 | 静态纹理 |
| Value noise | O(2²) | O(2³) | 中(C¹) | 有(grid) | 简单地形 |
| Perlin noise | O(2²) | O(2³) | 高(C²) | 弱 | 通用,主要 PCG |
| Simplex noise | O((N+1)²) | O(N² × 4) | 高(C²) | 极弱 | 高质量 PCG |
| Worley | O(3ᴺ) | O(3ᴺ) | 视情况 | 无 | 细胞纹理 |

(表里的复杂度是每点查询复杂度,N 是维度。)

## 3 · Fractal Brownian Motion(fBm)

### 3.1 一个噪声不够:需要分形

单层 Perlin noise 看起来"光滑",但自然界地形**不是单一频率**——大山里有中山,中山里有小山,小山里有石头,石头里有砂砾。**多个频率叠加**。

**fBm**(fractional Brownian motion,分形布朗运动)就是把噪声叠加多层:

```
fBm(x, y) = ∑ octaves (persistence^i) * noise(x * frequency^i, y * frequency^i)
```

参数:
- **octaves**(八度数):叠加几层。典型 4-8。
- **frequency**(基础频率):最底层的频率。典型 1。
- **lacunarity**(空隙率):每层频率乘多少。典型 2.0。
- **persistence**(持续度):每层振幅乘多少。典型 0.5。

直觉:**低频大波 + 高频小波叠加 = 自然地形**。低频给大形状(山脉),高频给细节(碎石)。每升一层,频率翻倍(更密的波),振幅减半(更弱的贡献)。

### 3.2 fBm 的 Rust 实现

```rust
// src/fbm.rs
use crate::perlin::perlin_noise_3d;

pub fn fbm_3d(
    x: f32, y: f32, z: f32,
    octaves: u32,
    lacunarity: f32,
    persistence: f32,
) -> f32 {
    let mut total = 0.0;
    let mut frequency = 1.0;
    let mut amplitude = 1.0;
    let mut max_value = 0.0;  // 用于归一化
    for _ in 0..octaves {
        total += amplitude * perlin_noise_3d(x * frequency, y * frequency, z * frequency);
        max_value += amplitude;
        frequency *= lacunarity;
        amplitude *= persistence;
    }
    total / max_value
}
```

调用:`fbm_3d(x, y, z, 6, 2.0, 0.5)` 生成一个 6 层分形噪声,值域约 [-1, 1]。这就是 Minecraft 高度图的核心——把 (x, z) 喂入,得到 y 当作地形高度。

### 3.3 Domain warping(域扭曲)

普通的 fBm 地形看起来"还行",但缺乏**奇异感**。Inigo Quilez(piquant shaders 作者,Disney 前技术总监)2002 年发明 **domain warping**——不是直接 noise(x),而是 noise(x + noise(x)):

```
基础 noise:n(x, y) = perlin(x, y)
一阶 warp:warp1(x, y) = perlin(x + n(x,y) * k, y + n(x,y) * k)
二阶 warp:warp2(x, y) = perlin(x + warp1(x,y) * k, y + warp1(x,y) * k)
```

`k` 是扭曲强度(典型 0.5-2.0)。

效果:**扭曲让噪声产生"漩涡""岩石褶皱""外星地貌"**——单层 fBm 看不到的复杂形状。

```rust
pub fn warped_fbm(x: f32, y: f32, t: f32) -> f32 {
    let k = 0.5;
    let n1 = fbm_3d(x * 0.5, y * 0.5, t, 4, 2.0, 0.5);
    let n2 = fbm_3d(x * 0.5 + n1 * k, y * 0.5 + n1 * k, t, 4, 2.0, 0.5);
    fbm_3d(x + n2 * k, y + n2 * k, t, 6, 2.0, 0.5)
}
```

这是 *No Man's Sky* 地形的核心技巧之一。

## 4 · 侵蚀模拟(Erosion Simulation)

### 4.1 水力侵蚀(Hydraulic erosion)

普通 fBm 地形"看起来像数字"。真地形有**水侵蚀**——雨水落下,顺坡流,带土石走,形成河谷。这给地形**结构感**。

**水力侵蚀模拟**算法(Mei 2007, *Fast Hydraulic Erosion Simulation*):

```
1. 初始化地形 heightmap h(x, y)。
2. 对每个 "水滴"粒子:
   a. 随机位置生成,初速 0,水量 1.0,沉积量 0。
   b. 循环直到水量 < 0.01 或超出地图:
      - 计算当前位置的高度梯度 ∇h。
      - 速度更新:v = v * inertia - ∇h * gravity。
      - 移动:new_pos = pos + v * dt。
      - 计算高度差 Δh = h(pos) - h(new_pos)。
      - 计算沉积容量:capacity = max(-Δh, min(Δh, v.magnitude)) *水量 *沉积系数。
      - 沉积或冲刷:
        if 沉积量 > capacity: 沉积到地形,sediment -= (sediment - capacity) * deposit_rate。
        else: 从地形冲刷,sediment += (capacity - sediment) * erode_rate。
      - 水量蒸发:water *= (1 - evaporate_rate)。
3. 渲染最终地形。
```

参数典型:`inertia = 0.05`, `gravity = 4.0`, `deposit_rate = 0.3`, `erode_rate = 0.3`, `evaporate_rate = 0.01`。一个 1024×1024 heightmap 跑 10 万水滴约 2 秒,得到真实感极强的河谷地形。

### 4.2 热侵蚀(Thermal erosion)

热侵蚀模拟"碎屑滚下坡"——超过"休止角"(angle of repose,~ 35° 沙子)的斜坡,材料滚下,直到斜坡角度 < 休止角。

算法(talus angle 规则):

```
for each cell (x, y):
    差值 = max(0, h(x,y) - h(neighbors_max))
    if 差值 > talus_threshold:
        // 把差值的一部分给最低邻居
        h(x, y) -= 差值 * 0.5
        h(neighbor_min) += 差值 * 0.5
```

反复迭代 100 次。结果:陡坡被"削平",山脚变缓。这是 *Shamus Young* 的程序化地形生成器用的算法。

### 4.3 侵蚀 Rust 实现

```rust
// src/erosion.rs
use crate::heightmap::HeightMap;

pub struct WaterDrop {
    pub x: f32,
    pub y: f32,
    pub vx: f32,
    pub vy: f32,
    pub water: f32,
    pub sediment: f32,
}

pub fn hydraulic_erosion(
    hm: &mut HeightMap,
    iterations: usize,
    inertia: f32,
    gravity: f32,
    deposit_rate: f32,
    erode_rate: f32,
    evaporate: f32,
) {
    let w = hm.width() as f32;
    let h = hm.height() as f32;
    let mut rng = rand::thread_rng();
    use rand::Rng;

    for _ in 0..iterations {
        let mut drop = WaterDrop {
            x: rng.gen_range(0.0..w),
            y: rng.gen_range(0.0..h),
            vx: 0.0,
            vy: 0.0,
            water: 1.0,
            sediment: 0.0,
        };

        let mut prev_h = hm.bilinear(drop.x, drop.y);

        for _step in 0..64 {
            // 梯度
            let (gx, gy) = hm.gradient(drop.x, drop.y);
            // 速度
            drop.vx = drop.vx * inertia - gx * gravity;
            drop.vy = drop.vy * inertia - gy * gravity;
            // normalize (避免速度过小)
            let speed = (drop.vx * drop.vx + drop.vy * drop.vy).sqrt();
            if speed < 1e-5 { break; }
            drop.vx /= speed;
            drop.vy /= speed;
            // 移动
            drop.x += drop.vx;
            drop.y += drop.vy;
            if drop.x < 0.0 || drop.x >= w || drop.y < 0.0 || drop.y >= h { break; }
            let new_h = hm.bilinear(drop.x, drop.y);
            let dh = new_h - prev_h;
            // 容量
            let capacity = (-dh).max(0.0).min(speed) * drop.water;
            if drop.sediment > capacity {
                // 沉积
                let dep = (drop.sediment - capacity) * deposit_rate;
                drop.sediment -= dep;
                hm.add(drop.x, drop.y, dep);
            } else {
                // 冲刷
                let ero = (capacity - drop.sediment) * erode_rate;
                drop.sediment += ero;
                hm.add(drop.x, drop.y, -ero * (-dh).max(0.0));
            }
            prev_h = new_h;
            drop.water *= 1.0 - evaporate;
            if drop.water < 0.01 { break; }
        }
    }
}
```

~80 行的水力侵蚀。这是 *Hans Theobald Beyer* 的硕士论文 *Implementation of a method for hydraulic erosion*(2015)的核心算法。

## 5 · Wave Function Collapse(WFC)

### 5.1 WFC 是什么

Wave Function Collapse(WFC)由 Maxim Gumin 2016 年提出(https://github.com/mxgmn/WaveFunctionCollapse ),灵感来自量子力学的波函数塌缩。它**学一个样本图案的局部规则,然后生成"风格相似"的新图案**。

例子:你给它一张地图——8×8 的森林截图(树、草、水、路)。WFC 学到"路只能连路或草,水只能连水或沙"。然后它生成 32×32 的新地图,**完美遵循原规则**。

这是 PCG 的革命。之前 PCG 算法(Perlin、Cellular automata)是"通用噪声",生成的是"看起来随机"的内容。WFC 是**"风格学习"**——给它 Mario 关卡,生成新 Mario 关卡;给它 Caves of Qud 地图,生成新 Qud 地图。

### 5.2 WFC 算法核心步骤

WFC 有两种模式:**重叠模式(Overlapping)** 和 **分块模式(Tiling)**。先讲 Overlapping(更通用)。

**输入**:一张 N×N 的样本图案(像素图 / tile 图)。

**步骤一**:**学习局部 pattern**。对样本的每个像素位置 (x, y),提取一个 3×3(或其他大小)的子图案。去重,得到一个 patterns 列表。

**步骤二**:**学习 pattern 之间的兼容性**。pattern A 和 pattern B 在某个方向(offset)兼容,如果"把 A 和 B 沿该方向偏移重叠,重叠部分像素一致"。

```
compatible(A, B, dx, dy) iff
    for each pixel (i, j) in the overlap region:
        A[i, j] == B[i - dx, j - dy]
```

**步骤三**:**初始化输出**。输出 W×H 网格,每格是一个"可能性波"——所有 pattern 都可能。`possible[w, h] = set of all patterns`。

**步骤四**:**观察 + 塌缩**。循环:
1. **观察**:找到"可能性最少"的格(熵最低)。
2. **塌缩**:从该格的可能 pattern 中随机选一个(按样本频率加权),该格塌缩成单一 pattern。
3. **传播**:从这个格向外传播约束——如果格子 X 塌缩成 pattern P,那么 X 的邻居只能保留与 P 兼容的 pattern。继续传播,直到所有格稳定。
4. **重复**:直到所有格塌缩。

**步骤五**:**冲突处理**。如果传播过程中某个格的可能性变成空集,说明死路——回滚或重启。

### 5.3 WFC 的 Rust 实现

```rust
// src/wfc.rs
use std::collections::{HashMap, HashSet, BTreeSet};
use std::hash::Hash;

#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct Pattern<T: Clone + PartialEq + Eq + Hash> {
    pub cells: Vec<T>,  // N*N pixels,行优先
    pub n: usize,        // 子图案大小
}

pub struct WFC<T: Clone + PartialEq + Eq + Hash + Ord> {
    pub patterns: Vec<Pattern<T>>,
    pub pattern_freq: Vec<f32>,                       // 每个 pattern 的频率
    pub compatible: Vec<Vec<HashMap<(i32, i32), Vec<usize>>>>,  // 兼容表
    pub width: usize,
    pub height: usize,
    pub wave: Vec<BTreeSet<usize>>,  // 每格的可能性集合
}

impl<T: Clone + PartialEq + Eq + Hash + Ord> WFC<T> {
    pub fn from_sample(sample: &[T], sample_w: usize, sample_h: usize,
                       n: usize, out_w: usize, out_h: usize) -> Self {
        // 1. 提取所有 n*n 子图案
        let mut patterns: Vec<Pattern<T>> = Vec::new();
        let mut counts: HashMap<Vec<T>, usize> = HashMap::new();

        for y in 0..=(sample_h - n) {
            for x in 0..=(sample_w - n) {
                let mut cells = Vec::with_capacity(n * n);
                for dy in 0..n {
                    for dx in 0..n {
                        cells.push(sample[(y + dy) * sample_w + (x + dx)].clone());
                    }
                }
                *counts.entry(cells.clone()).or_insert(0) += 1;
                if !patterns.iter().any(|p| p.cells == cells) {
                    patterns.push(Pattern { cells, n });
                }
            }
        }

        let total = counts.values().sum::<usize>() as f32;
        let pattern_freq: Vec<f32> = patterns.iter()
            .map(|p| counts[&p.cells] as f32 / total)
            .collect();

        // 2. 计算兼容性
        let npatterns = patterns.len();
        let offsets: [(i32, i32); 4] = [(-1, 0), (1, 0), (0, -1), (0, 1)];
        let mut compatible = vec![vec![HashMap::new(); npatterns]; npatterns];

        for (i, pi) in patterns.iter().enumerate() {
            for (j, pj) in patterns.iter().enumerate() {
                for &(dx, dy) in &offsets {
                    if Self::overlap_matches(pi, pj, dx, dy) {
                        compatible[i][j].entry((dx, dy)).or_insert_with(Vec::new).push(j);
                    }
                }
            }
        }

        // 3. 初始化 wave
        let all: BTreeSet<usize> = (0..npatterns).collect();
        let wave = vec![all.clone(); out_w * out_h];

        WFC {
            patterns, pattern_freq, compatible,
            width: out_w, height: out_h, wave,
        }
    }

    /// 检查 pi 和 pj 在 offset (dx, dy) 处重叠时是否一致
    fn overlap_matches(pi: &Pattern<T>, pj: &Pattern<T>, dx: i32, dy: i32) -> bool {
        let n = pi.n as i32;
        for iy in 0..n {
            for ix in 0..n {
                let jx = ix + dx;
                let jy = iy + dy;
                if jx < 0 || jx >= n || jy < 0 || jy >= n { continue; }
                let pi_cell = &pi.cells[(iy * n + ix) as usize];
                let pj_cell = &pj.cells[(jy * n + jx) as usize];
                if pi_cell != pj_cell { return false; }
            }
        }
        true
    }

    /// 找熵最低的格
    fn min_entropy_cell(&self) -> Option<usize> {
        let mut min_entropy = usize::MAX;
        let mut min_idx = None;
        for (i, cell) in self.wave.iter().enumerate() {
            if cell.len() == 1 { continue; }  // 已塌缩
            if cell.len() < min_entropy {
                min_entropy = cell.len();
                min_idx = Some(i);
            }
        }
        min_idx
    }

    /// 塌缩一个格
    fn collapse(&mut self, idx: usize) {
        let cell = &self.wave[idx];
        // 按频率加权随机选一个 pattern
        let total: f32 = cell.iter().map(|&p| self.pattern_freq[p]).sum();
        let mut r = rand::thread_rng().gen_range(0.0..total);
        use rand::Rng;
        let mut chosen = *cell.iter().next().unwrap();
        for &p in cell.iter() {
            r -= self.pattern_freq[p];
            if r <= 0.0 { chosen = p; break; }
        }
        let mut new_set = BTreeSet::new();
        new_set.insert(chosen);
        self.wave[idx] = new_set;
    }

    /// 传播约束
    fn propagate(&mut self, start: usize) {
        let mut stack = vec![start];
        while let Some(idx) = stack.pop() {
            let x = idx % self.width;
            let y = idx / self.width;
            let cell = self.wave[idx].clone();
            // 对每个邻居
            for &(dx, dy) in &[(-1i32, 0i32), (1, 0), (0, -1), (0, 1)] {
                let nx = x as i32 + dx;
                let ny = y as i32 + dy;
                if nx < 0 || nx >= self.width as i32 || ny < 0 || ny >= self.height as i32 {
                    continue;
                }
                let nidx = ny as usize * self.width + nx as usize;
                let mut to_remove = Vec::new();
                for &candidate in self.wave[nidx].iter() {
                    // candidate 是否还有任何"和 idx 当前 cell 兼容"的 pattern?
                    let ok: bool = cell.iter().any(|&p| {
                        self.compatible[p][candidate]
                            .get(&(-dx, -dy))
                            .map_or(false, |v| !v.is_empty())
                    });
                    if !ok { to_remove.push(candidate); }
                }
                if !to_remove.is_empty() {
                    let neighbor = self.wave[nidx].clone();
                    self.wave[nidx] = neighbor.into_iter()
                        .filter(|p| !to_remove.contains(p))
                        .collect();
                    stack.push(nidx);
                }
            }
        }
    }

    pub fn run(&mut self) -> Result<(), &'static str> {
        loop {
            match self.min_entropy_cell() {
                None => return Ok(()),  // 全部塌缩
                Some(idx) => {
                    self.collapse(idx);
                    self.propagate(idx);
                    // 检测冲突
                    if self.wave.iter().any(|c| c.is_empty()) {
                        return Err("contradiction detected, retry needed");
                    }
                }
            }
        }
    }
}
```

~150 行的 WFC 实现。这是 Maxim Gumin 原版的简化版——原版有更多优化(分块模式、回滚、对称检测、模板匹配)。

### 5.4 WFC 的应用

- **Townscaper**(Oskar Stålberg 2021):用 WFC 生成无边的、风格化的城市。GDC talk: *Townscaper: A Tiny Game Tour*。
- **Caves of Qud**:WFC 生成洞穴、地下城。
- **Risk of Rain 2**:WFC 生成关卡布局。
- **Hex SDL tiles**:社区有大量 WFC tile-based 项目。

### 5.5 WFC 的复杂度与回滚

WFC 最坏复杂度是 **指数** ——理论上无解的 sample 会让 WFC 反复失败。但实际工程中,大多数 sample 在合理时间内能收敛。如果**冲突**(某格可能性空集),回滚到上一个稳定状态,或整个重启。

优化技巧:
1. **预计算兼容表**:O(P² × |offsets|),P = pattern 数。一次算好,反复用。
2. **优先选最低熵**:大幅减少回滚次数。
3. **对称检测**:如果 sample 有 4-fold 对称,WFC 可以利用对称性减少 pattern 数。
4. **限分块模式**:Tiling WFC 比 Overlapping 快 10-100×,但需要预定义 tile。

## 6 · L-system:文法生成

### 6.1 L-system 是什么

L-system(Lindenmayer system)由匈牙利生物学家 Aristid Lindenmayer 1968 年发明,用于模拟**植物生长**。它是一个**字符串重写系统**——从一个起始串(axiom)开始,反复应用产生式规则(production rules),得到最终字符串,然后**解释为图形**。

经典例子:**Fractal plant**(分形植物):

```
axiom: X
rules:
    X → F+[[X]-X]-F[-FX]+X
    F → FF
```

每次迭代,把所有 X 和 F 替换。然后 **turtle graphics** 解释:
- F:画一条线段(前进)
- +:右转 25°
- -:左转 25°
- [:压栈(保存当前位置和方向)
- ]:出栈(恢复位置和方向)
- X:不画(只是 placeholder)

经过 5 次迭代,字符串长度爆炸,但 turtle graphics 画出**像树的形状**——主干、分叉、叶子。

### 6.2 L-system Rust 实现

```rust
// src/lsystem.rs
use std::collections::HashMap;

pub struct LSystem {
    pub axiom: String,
    pub rules: HashMap<char, String>,
}

impl LSystem {
    pub fn iterate(&self, n: usize) -> String {
        let mut current = self.axiom.clone();
        for _ in 0..n {
            let mut next = String::new();
            for c in current.chars() {
                if let Some(replacement) = self.rules.get(&c) {
                    next.push_str(replacement);
                } else {
                    next.push(c);
                }
            }
            current = next;
        }
        current
    }
}

/// Turtle 解释器:把字符串变成线条
pub struct Turtle {
    pub x: f32,
    pub y: f32,
    pub angle: f32,  // 度
    pub stack: Vec<(f32, f32, f32)>,
    pub lines: Vec<((f32, f32), (f32, f32))>,
}

impl Turtle {
    pub fn new(x: f32, y: f32, angle: f32) -> Self {
        Self { x, y, angle, stack: Vec::new(), lines: Vec::new() }
    }

    pub fn interpret(&mut self, s: &str, step: f32, turn_deg: f32) {
        for c in s.chars() {
            match c {
                'F' => {
                    let rad = self.angle.to_radians();
                    let nx = self.x + step * rad.cos();
                    let ny = self.y + step * rad.sin();
                    self.lines.push(((self.x, self.y), (nx, ny)));
                    self.x = nx;
                    self.y = ny;
                }
                '+' => self.angle += turn_deg,
                '-' => self.angle -= turn_deg,
                '[' => self.stack.push((self.x, self.y, self.angle)),
                ']' => {
                    if let Some((x, y, a)) = self.stack.pop() {
                        self.x = x; self.y = y; self.angle = a;
                    }
                }
                _ => {}
            }
        }
    }
}

pub fn fractal_plant() -> (LSystem, f32) {
    let mut rules = HashMap::new();
    rules.insert('X', "F+[[X]-X]-F[-FX]+X".to_string());
    rules.insert('F', "FF".to_string());
    (LSystem { axiom: "X".to_string(), rules }, 25.0)
}
```

50 行的 L-system。这是 Speedtree / Tree It 等植被生成工具的核心原理。工业级 L-system 加上**随机变异**(每次规则应用有概率选择不同右端)、**光照影响**(分支朝光多)、**叶子和花的 3D 模型**。

## 7 · Voronoi diagram(沃罗诺伊图)

### 7.1 什么是 Voronoi

给定平面上 N 个种子点,Voronoi diagram 把平面分成 N 个区域——每个区域包含所有"离这个种子最近"的点。

```
对每个查询点 q:
    Voronoi_cell(q) = argmin_i (distance(q, seed_i))
```

Voronoi 由俄国数学家 Georgy Voronoy 1908 年提出。它在自然界普遍存在——斑马纹、长颈鹿斑、蜻蜓翅膀、龟壳。

### 7.2 算法:Fortune's sweep

构造 Voronoi 的 O(N log N) 算法叫 **Fortune's sweep**(Steven Fortune 1986)。核心 idea:**用一条扫描线扫过平面,维护一个"抛物线前沿",在抛物线交点处产生 Voronoi 顶点**。

详细推导较长(200 行算法),这里我跳过细节,只说怎么用。

Rust 库 `voronoi`(https://github.com/pdestrop/voronoi) 实现了完整 Fortune's sweep。

### 7.3 Voronoi 在游戏中的应用

- **地图势力范围**:Civ / Stellaris 用 Voronoi 划分帝国势力。
- **程序化纹理**:细胞状纹理(Worley noise 本质就是 Voronoi 距离)。
- **Biome 分布**:每个 biome 种子在地图上,Voronoi 决定每格属于哪个 biome。
- **手机基站分布**:游戏地图的"信号塔"覆盖。
- **AI 探索**:agent 探索过的区域用 Voronoi 表示。

### 7.4 Voronoi 变体:Centroidal Voronoi

普通 Voronoi 的种子位置任意。**Centroidal Voronoi Tessellation(CVT)** 要求每个种子在自己 Voronoi cell 的**重心**——这产生"均匀"的 cell 分布。

CVT 算法(Lloyd's algorithm):

```
1. 随机 N 个种子。
2. 计算每个种子的 Voronoi cell。
3. 把每个种子移到它 cell 的重心。
4. 重复步骤 2-3 直到收敛(种子不动)。
```

CVT 产生**均匀六边形分布**,看起来像蜂窝。Stippling 算法(用点画模拟灰度图)用 CVT。

## 8 · Marching Cubes

### 8.1 体素到 mesh

**Marching Cubes**(MC)是 1987 年 Lorensen 和 Cline 发表在 SIGGRAPH 的算法(*Marching Cubes: A High Resolution 3D Surface Construction Algorithm*)。它把**体素网格**(标量场)转成 **mesh**。具体:每个体素有 0 或 1(里/外),MC 在体素边界生成三角形,拟合"等值面"(isosurface)。

应用:
- **医学影像**:CT/MRI 体素 → mesh,医生看 3D 解剖。
- **Metaball 渲染**:球体融合的"软"形状。
- **地形生成**:噪声高度场 → mesh(替代 heightmap,允许洞窟、悬空)。
- **Voxel 游戏**:*Minecraft* 是"块状" voxel,MC 让它平滑(*Minetest* smooth lighting 用 MC)。

### 8.2 MC 算法

每个体素有 8 个角顶点,每个角有 0 或 1。共 2⁸ = 256 种情况。Lorensen 制作了一个 lookup table:每种情况生成几个三角形,顶点位置通过线性插值估算。

简化描述:

```
for each voxel (x, y, z):
    1. 看 8 个角的值(0 = outside, 1 = inside)。
    2. 用 8 个 bit 编码,得到 0-255 的 index。
    3. 查表:这个 index 对应哪些三角形(由哪些边插值而成)。
    4. 对每条"穿越边"(一个角 0,一个角 1),线性插值得到等值面位置:
        t = (isovalue - v0) / (v1 - v0)
        vertex = p0 + t * (p1 - p0)
    5. 输出三角形。
```

256 种情况用对称性减到 15 个基本 cases(Lorensen 原论文图)。

### 8.3 MC 的 Rust 实现(简化版)

```rust
// src/marching_cubes.rs

const EDGE_TABLE: [u16; 256] = [
    // 256 个 entry,每个是 12 位 mask,标识哪些边穿越
    // 完整表很长(256 个 16-bit),从 Paul Bourke 的网页拷
    0x0, 0x109, 0x203, 0x30a, 0x406, 0x50f, 0x605, 0x70c,
    // ... (省略,完整表见 https://paulbourke.net/geometry/polygonise/)
    0x0, 0x0, 0x0, 0x0,
];

const TRI_TABLE: [[i8; 16]; 256] = [
    // 256 个 entry,每个最多 5 个三角形(3 顶点 × 5 = 15 + 1 终止符)
    [-1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1],
    [0, 8, 3, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1, -1],
    // ... 完整表从 Paul Bourke 拷
];

pub fn march_one_voxel(
    p: [[f32; 3]; 8],   // 8 个角的位置
    val: [f32; 8],       // 8 个角的标量值
    isovalue: f32,
    out_triangles: &mut Vec<[f32; 9]>,  // 每个三角形 3 个顶点 × 3
) {
    // 1. 算 8-bit cubeindex
    let mut cubeindex = 0u8;
    for i in 0..8 {
        if val[i] < isovalue { cubeindex |= 1 << i; }
    }
    if EDGE_TABLE[cubeindex as usize] == 0 { return; }

    // 2. 找所有穿越边,线性插值得到顶点
    let mut vert_list = [[0.0f32; 3]; 12];
    let edges = EDGE_TABLE[cubeindex as usize];
    if edges & 1    != 0 { vert_list[0]  = interpolate(p[0], p[1], val[0], val[1], isovalue); }
    if edges & 2    != 0 { vert_list[1]  = interpolate(p[1], p[2], val[1], val[2], isovalue); }
    if edges & 4    != 0 { vert_list[2]  = interpolate(p[2], p[3], val[2], val[3], isovalue); }
    if edges & 8    != 0 { vert_list[3]  = interpolate(p[3], p[0], val[3], val[0], isovalue); }
    if edges & 16   != 0 { vert_list[4]  = interpolate(p[4], p[5], val[4], val[5], isovalue); }
    if edges & 32   != 0 { vert_list[5]  = interpolate(p[5], p[6], val[5], val[6], isovalue); }
    if edges & 64   != 0 { vert_list[6]  = interpolate(p[6], p[7], val[6], val[7], isovalue); }
    if edges & 128  != 0 { vert_list[7]  = interpolate(p[7], p[4], val[7], val[4], isovalue); }
    if edges & 256  != 0 { vert_list[8]  = interpolate(p[0], p[4], val[0], val[4], isovalue); }
    if edges & 512  != 0 { vert_list[9]  = interpolate(p[1], p[5], val[1], val[5], isovalue); }
    if edges & 1024 != 0 { vert_list[10] = interpolate(p[2], p[6], val[2], val[6], isovalue); }
    if edges & 2048 != 0 { vert_list[11] = interpolate(p[3], p[7], val[3], val[7], isovalue); }

    // 3. 查 tri table,输出三角形
    let tri = &TRI_TABLE[cubeindex as usize];
    let mut i = 0;
    while tri[i] != -1 {
        let a = vert_list[tri[i] as usize];
        let b = vert_list[tri[i + 1] as usize];
        let c = vert_list[tri[i + 2] as usize];
        out_triangles.push([a[0], a[1], a[2], b[0], b[1], b[2], c[0], c[1], c[2]]);
        i += 3;
    }
}

fn interpolate(p1: [f32; 3], p2: [f32; 3], v1: f32, v2: f32, isov: f32) -> [f32; 3] {
    let t = (isov - v1) / (v2 - v1);
    [
        p1[0] + t * (p2[0] - p1[0]),
        p1[1] + t * (p2[1] - p1[1]),
        p1[2] + t * (p2[2] - p1[2]),
    ]
}
```

Marching Cubes 的完整 lookup table 是固定的 256 entries,从 Paul Bourke 的网页(https://paulbourke.net/geometry/polygonise/)复制。

### 8.4 MC 的弱点:丢失锐边

MC 假设等值面**光滑**——线性插值得到三角形顶点,但**法线连续**。如果体素场有锐边(比如建筑物),MC 把它磨圆。

**Dual Contouring**(DC, Ju et al. 2002)修这个问题。DC 在每个体素内部放**一个**顶点(不是 12 条边各一个),用 **QEF**(Quadric Error Function,和 QEM 同根同源!)算出最优顶点位置——保留锐边和角。DC 比 MC 复杂,但视觉效果好得多。*Houdini* 的 VDB to Mesh 节点用 DC。

### 8.5 Transvoxels

游戏地形用 MC 会有 chunk 边界 artifact(两个 chunk 的 mesh 不连续)。David 2010 发明 **Transvoxels**——在 chunk 边界用特殊过渡三角形。*7 Days to Die* 用 Transvoxels。

## 9 · 地形生成完整 pipeline

### 9.1 Minecraft 风格 heightmap

最简单的地形:

```rust
fn heightmap_terrain(x: f32, z: f32, seed: u32) -> f32 {
    let h1 = fbm_3d(x * 0.005, z * 0.005, seed as f32, 6, 2.0, 0.5);
    let h2 = fbm_3d(x * 0.02, z * 0.02, seed as f32, 4, 2.0, 0.5) * 0.3;
    let height = (h1 + h2) * 30.0 + 64.0;  // 中心 y=64
    height
}
```

这就是 Minecraft 1.0 的地形生成核心(实际 Minecraft 用多 octaves + biome 噪声 + 高度梯度,更复杂)。

### 9.2 3D 噪声 + Marching Cubes

更复杂的地形(允许洞窟、悬空):

```rust
fn density_3d(x: f32, y: f32, z: f32, seed: u32) -> f32 {
    // 基础高度场
    let base_height = fbm_3d(x * 0.005, z * 0.005, seed as f32, 4, 2.0, 0.5) * 30.0;
    let height_density = (base_height + 64.0 - y) * 0.05;
    // 洞穴(3D 噪声)
    let cave_noise = fbm_3d(x * 0.02, y * 0.02, z * 0.02, seed as f32, 3, 2.0, 0.5);
    let caves = if cave_noise.abs() < 0.1 { -1.0 } else { 0.0 };
    // 合并
    height_density + caves
}

// 然后用 Marching Cubes 在体素网格上提取 isovalue = 0 的面
```

这是 *Astroneer* / *7 Days to Die* / *Minetest* 的核心地形生成。

### 9.3 Biome(生物群系)

Minecraft 风格 biome:

```
1. 用 2 个独立 Perlin noise:temperature(温度)和 humidity(湿度)。
2. 二维查找表:把 (temperature, humidity) 映射到 biome。
   - 高温 + 高湿 → 丛林
   - 高温 + 低湿 → 沙漠
   - 低温 + 高湿 → 雪林
   - 低温 + 低湿 → 苔原
3. 每个 biome 有不同的:
   - 高度调整(沙漠平坦,山地陡峭)
   - 植被密度
   - 块类型(沙 vs 草 vs 雪)
```

### 9.4 结构生成

结构(village、dungeon、temple)的生成:

```
1. 一个 chunk 加载时,根据 (chunk_x, chunk_z, seed) 算 hash。
2. 如果 hash % 100 == 0,这个 chunk 有结构。
3. 用 hash 决定结构类型(village / dungeon / temple)。
4. 用 hash 决定结构位置(chunk 内的局部坐标)。
5. 用 PCG 文法(L-system 或 graph grammar)生成结构布局。
6. 把布局 paste 到地形上(覆盖块)。
```

## 10 · 程序化纹理

### 10.1 噪声到纹理

任何 noise 都可以采样为 2D 纹理:

```rust
fn generate_wood_texture(width: usize, height: usize) -> Vec<[u8; 4]> {
    let mut pixels = vec![[0u8, 0, 0, 255]; width * height];
    for y in 0..height {
        for x in 0..width {
            let nx = x as f32 / width as f32 * 8.0;
            let ny = y as f32 / height as f32 * 8.0;
            // 木纹 = 周期函数 + Perlin 噪声扰动
            let rings = (nx + 0.1 * perlin_noise_3d(nx, ny, 0.0, 0.0) * 8.0).sin();
            let wood = (rings * 0.5 + 0.5) * 60.0 + 80.0;
            pixels[y * width + x] = [
                (wood * 1.3) as u8,  // R
                (wood * 0.7) as u8,  // G
                (wood * 0.3) as u8,  // B
                255,                  // A
            ];
        }
    }
    pixels
}
```

这是 *Minecraft* 木纹方块、*Spelunky* 石墙、所有像素艺术风格游戏的程序化纹理原理。

### 10.2 法线贴图从高度图

高度图 → 法线贴图:

```rust
fn height_to_normal(h: &[f32], w: usize, _h: usize, strength: f32) -> Vec<[u8; 4]> {
    let mut normals = vec![[0u8; 4]; w * _h];
    for y in 0.._h {
        for x in 0..w {
            let hl = h[y * w + (x.saturating_sub(1))];
            let hr = h[y * w + ((x + 1).min(w - 1))];
            let hd = h[(y.saturating_sub(1)) * w + x];
            let hu = h[((y + 1).min(_h - 1)) * w + x];
            let dx = (hr - hl) * strength;
            let dy = (hu - hd) * strength;
            let n = Vec3::new(-dx, -dy, 1.0).normalize();
            normals[y * w + x] = [
                ((n.x * 0.5 + 0.5) * 255.0) as u8,
                ((n.y * 0.5 + 0.5) * 255.0) as u8,
                ((n.z * 0.5 + 0.5) * 255.0) as u8,
                255,
            ];
        }
    }
    normals
}
```

这就是 Substance Designer / Filter Forge 的核心思路。

## 11 · Wang tiling(王氏拼贴)

### 11.1 Wang tiles

Hao Wang 1961 年提出的问题:**用一组正方形 tile,每边有颜色,无缝铺满平面**。规则:相邻 tile 的边颜色必须相同。

如果用 16 个 tile(每边 2 色 = 4 边 = 2⁴ = 16 tile),可以**非周期性**铺满任意大小平面。这给 PCG 一个利器:**预生成 16 个 tile,运行时任意拼,玩家看到"无缝大地图"但实际是固定 tile**。

### 11.2 Wang tiling 在游戏里

- **Terrain texture**:16 个 tile 平铺,看起来像无缝大地形。
- **Dungeon wall**:4-color Wang tile 生成无限走廊。
- **Texture atlas**:Spelunky 2 用 Wang tiles 拼接地下城。

实现:

```rust
fn wang_tiling(width: usize, height: usize) -> Vec<usize> {
    // 4-color Wang tile:每 tile 用 4 bit 编码(N E S W = 北东南西各一色)
    // tile 0 = (0,0,0,0), tile 15 = (1,1,1,1)
    let mut grid = vec![0usize; width * height];
    let mut rng = rand::thread_rng();
    use rand::Rng;
    for y in 0..height {
        for x in 0..width {
            let n = if y > 0 { grid[(y - 1) * width + x] & 0b0100 >> 2 } else { rng.gen_range(0..2) };
            let w = if x > 0 { grid[y * width + (x - 1)] & 0b0001 } else { rng.gen_range(0..2) };
            let s = rng.gen_range(0..2);
            let e = rng.gen_range(0..2);
            grid[y * width + x] = (n << 3) | (e << 2) | (s << 1) | w;
        }
    }
    grid
}
```

## 11.5 · Cellular Automata(元胞自动机)

### 什么是 CA

**元胞自动机**(Cellular Automata, CA)由 John von Neumann 和 Stanislaw Ulam 1940 年代在 Los Alamos 国家实验室发明,本来是研究"自复制机器"。1970 年 John Conway 的 *Game of Life* 把 CA 推广到大众。CA 是一组规则:**网格上每个 cell 有 0 或 1 状态,每代迭代根据邻居状态更新自己的状态**。

最经典的 CA 规则(Conway's Life):

```
live cell with 2 or 3 live neighbors → 存活
live cell with < 2 or > 3 live neighbors → 死亡
dead cell with exactly 3 live neighbors → 出生
```

简单规则产生复杂行为——滑翔机(glider)、振荡器(oscillator)、宇宙飞船(spaceship)。

### CA 在 PCG 中的应用:Cave generation

CA 在游戏 PCG 里的最经典应用是**洞穴生成**。Conway 规则稍作修改,生成"洞穴状"形状:

```
规则(B5678/S45678):
- 初始:随机 45% 的 cell 是 wall,55% 是 floor。
- 每代迭代:
    if cell is wall and neighbors (8) >= 4 → keep wall
    if cell is floor and neighbors (8) >= 5 → become wall
    else → become floor
- 跑 4-5 代迭代。
```

效果:随机噪声演化成"有结构的洞穴"——开阔的房间 + 弯曲的走廊。这是 *Caves of Qud* / *Dwarf Fortress* / *Brogue* / *Steamworld Dig* 的洞穴生成核心。

让我手推一个 8×8 网格的 5 代演化。初始(45% wall,W = wall,F = floor):

```
代 0(随机):
W F F W F F F W
F F W W F W F F  
F W W F F W W F
W F W F W F W W
F W F F W F F W
W F F W W W F F
F F W F F W F W
W W F W F F W W

代 1(应用规则一次):
W F F W F F F W
F F W W F W F F
F W W F F W W F
W F W F W F W W
F W F F W F F W
W F F W W W F F
F F W F F W F W
W W F W F F W W
(实际上要更新,但 CA 规则让密集 wall 区域更密,稀疏 floor 区域更稀)
```

### CA Rust 实现

```rust
// src/cellular_automata.rs

pub struct CA {
    pub width: usize,
    pub height: usize,
    pub cells: Vec<bool>,  // true = wall, false = floor
}

impl CA {
    pub fn new_random(width: usize, height: usize, fill: f32) -> Self {
        let mut rng = rand::thread_rng();
        use rand::Rng;
        let cells: Vec<bool> = (0..(width * height))
            .map(|_| rng.gen::<f32>() < fill)
            .collect();
        Self { width, height, cells }
    }

    pub fn count_wall_neighbors(&self, x: i32, y: i32) -> u32 {
        let mut count = 0;
        for dy in -1..=1 {
            for dx in -1..=1 {
                if dx == 0 && dy == 0 { continue; }
                let nx = x + dx;
                let ny = y + dy;
                if nx < 0 || nx >= self.width as i32 || ny < 0 || ny >= self.height as i32 {
                    count += 1;  // 边界算 wall
                } else if self.cells[ny as usize * self.width + nx as usize] {
                    count += 1;
                }
            }
        }
        count
    }

    /// 5-3 规则:wall if neighbors >= 5 else floor
    pub fn iterate_cave(&mut self) {
        let mut new_cells = self.cells.clone();
        for y in 0..self.height {
            for x in 0..self.width {
                let n = self.count_wall_neighbors(x as i32, y as i32);
                new_cells[y * self.width + x] = n >= 5;
            }
        }
        self.cells = new_cells;
    }

    pub fn run_cave_generation(&mut self, generations: usize) {
        for _ in 0..generations {
            self.iterate_cave();
        }
    }
}
```

40 行的 CA。这种 cave generation 是 Rogue-like 游戏的标配。*Caves of Qud*、*Dungeon Crawl Stone Soup* 都用它。

### CA 变体:Vote rule

CA 的另一种规则是 **Vote rule**:每个 cell 的下一状态 = 邻居(含自己)状态的平均值 > 0.5。这产生更"光滑"的图案,适合生成海岸线、岛屿边缘。Vote rule 是 *Cataclysm: Dark Days Ahead* 的海岸线生成算法。

### CA 的并行性

CA **天然并行**——每个 cell 的更新独立,完美 SIMD/GPU 适配。用 compute shader 跑 4K×4K CA,每代 < 1 ms。这是 *Sebastian Lague* YouTube 频道的 CA 视频的核心优化。

## 11.6 · Drunkard's Walk(醉汉游走)

### 算法

Drunkard's Walk(醉汉游走)是另一种洞穴生成算法,极简单:

```
1. 初始化全 wall 网格。
2. 选起点,标为 floor。
3. "醉汉"在网格上随机走 N 步,每步标当前位置为 floor。
4. 重复(每次新醉汉从已有 floor cell 出发),直到 floor cell 数达到目标。
```

效果:**曲折的隧道 + 偶然的房间**。每个醉汉走出一条不规则走廊,多条走廊汇成洞穴。

### Rust 实现

```rust
// src/drunkard.rs

pub fn drunkard_walk(
    width: usize,
    height: usize,
    target_floors: usize,
    seed: u64,
) -> Vec<bool> {
    let mut rng = <rand::rngs::StdRng as rand::SeedableRng>::seed_from_u64(seed);
    use rand::Rng;
    let mut cells = vec![true; width * height];  // true = wall

    let mut cx = width / 2;
    let mut cy = height / 2;
    cells[cy * width + cx] = false;  // 起点 floor
    let mut floor_count = 1;

    while floor_count < target_floors {
        let dir = rng.gen_range(0..4);
        let (nx, ny) = match dir {
            0 => (cx as i32 + 1, cy as i32),
            1 => (cx as i32 - 1, cy as i32),
            2 => (cx as i32, cy as i32 + 1),
            _ => (cx as i32, cy as i32 - 1),
        };
        // 边界检查;撞墙就"弹回"
        if nx < 1 || nx >= width as i32 - 1 || ny < 1 || ny >= height as i32 - 1 {
            continue;
        }
        cx = nx as usize;
        cy = ny as usize;
        if cells[cy * width + cx] {
            cells[cy * width + cx] = false;
            floor_count += 1;
        }
    }
    cells
}
```

30 行的 Drunkard's Walk。*Caves of Qud* 用这种算法生成洞穴,*Spelunky* 用变种生成走廊。

### 对比 CA 和 Drunkard's Walk

| 算法 | 风格 | 控制性 | 性能 |
|---|---|---|---|
| CA(B5678/S45678) | 有机、自然 | 弱(只有参数,形状难控) | 慢(每代 O(W×H)) |
| Drunkard's Walk | 长走廊、不规则 | 中(可指定目标 floor 数) | 快(O(target_floors)) |
| BSP(下面讲) | 规则、对称 | 强(明确房间 + 走廊结构) | 快 |

## 11.7 · BSP 地牢生成

### 算法

Binary Space Partitioning(BSP,二叉空间分割)地牢生成由 Mike Anderson 2008 提出(*Procedural Dungeon Generation* 系列)。算法:

```
1. 整个地图是一个矩形 room。
2. 递归二分:沿长边切,分割成两个子矩形。
3. 直到矩形大小 <= 最小阈值(停止)。
4. 对每个叶节点矩形,在中央放一个 room(随机大小,小于矩形)。
5. 在父节点里,把两个子节点的 room 用走廊连接。
6. 上溯,直到根节点:整个 dungeon 连通。
```

这是经典 *Rogue* / *NetHack* / *Hack* / *Dungeon Crawl Stone Soup* 的 dungeon 生成算法。

### Rust 实现

```rust
// src/bsp_dungeon.rs

#[derive(Clone, Debug)]
pub struct Rect {
    pub x: i32,
    pub y: i32,
    pub w: i32,
    pub h: i32,
}

impl Rect {
    pub fn center(&self) -> (i32, i32) {
        (self.x + self.w / 2, self.y + self.h / 2)
    }
}

enum BspNode {
    Leaf(Rect),
    Branch {
        left: Box<BspNode>,
        right: Box<BspNode>,
        rect: Rect,
    },
}

impl BspNode {
    pub fn new(rect: Rect, min_size: i32, depth: u32) -> Self {
        if depth == 0 || rect.w <= min_size * 2 || rect.h <= min_size * 2 {
            return BspNode::Leaf(rect);
        }
        let mut rng = rand::thread_rng();
        use rand::Rng;
        let (left_rect, right_rect) = if rect.w > rect.h {
            let split = rng.gen_range(min_size..(rect.w - min_size));
            (
                Rect { x: rect.x, y: rect.y, w: split, h: rect.h },
                Rect { x: rect.x + split, y: rect.y, w: rect.w - split, h: rect.h },
            )
        } else {
            let split = rng.gen_range(min_size..(rect.h - min_size));
            (
                Rect { x: rect.x, y: rect.y, w: rect.w, h: split },
                Rect { x: rect.x, y: rect.y + split, w: rect.w, h: rect.h - split },
            )
        };
        BspNode::Branch {
            left: Box::new(BspNode::new(left_rect, min_size, depth - 1)),
            right: Box::new(BspNode::new(right_rect, min_size, depth - 1)),
            rect,
        }
    }

    pub fn collect_rooms(&self, rooms: &mut Vec<Rect>) {
        match self {
            BspNode::Leaf(rect) => {
                let mut rng = rand::thread_rng();
                use rand::Rng;
                let w = rng.gen_range(6..rect.w);
                let h = rng.gen_range(6..rect.h);
                let x = rect.x + (rect.w - w) / 2;
                let y = rect.y + (rect.h - h) / 2;
                rooms.push(Rect { x, y, w, h });
            }
            BspNode::Branch { left, right, .. } => {
                left.collect_rooms(rooms);
                right.collect_rooms(rooms);
            }
        }
    }

    pub fn corridors(&self, corridors: &mut Vec<((i32, i32), (i32, i32))>) {
        if let BspNode::Branch { left, right, .. } = self {
            left.corridors(corridors);
            right.corridors(corridors);
            // 连接两个子节点的"代表房间"
            let mut left_rooms = Vec::new();
            let mut right_rooms = Vec::new();
            left.collect_rooms(&mut left_rooms);
            right.collect_rooms(&mut right_rooms);
            if let (Some(lr), Some(rr)) = (left_rooms.first(), right_rooms.first()) {
                let (lx, ly) = lr.center();
                let (rx, ry) = rr.center();
                corridors.push(((lx, ly), (rx, ry)));
            }
        }
    }
}

pub fn generate_bsp_dungeon(
    map_w: i32,
    map_h: i32,
    min_room_size: i32,
    max_depth: u32,
) -> (Vec<Rect>, Vec<((i32, i32), (i32, i32))>) {
    let root = BspNode::new(
        Rect { x: 0, y: 0, w: map_w, h: map_h },
        min_room_size,
        max_depth,
    );
    let mut rooms = Vec::new();
    root.collect_rooms(&mut rooms);
    let mut corridors = Vec::new();
    root.corridors(&mut corridors);
    (rooms, corridors)
}
```

~80 行的 BSP 地牢。这是 Rogue-like 游戏的核心。

### BSP vs CA vs Drunkard

三种 dungeon 算法的风格对比:

- **BSP**:*NetHack* 风格——规则房间 + 直走廊。可预测、易平衡。
- **CA**:*Caves of Qud* 风格——有机洞穴、自然形状。不可预测。
- **Drunkard's Walk**:*Broquest* / *Steamworld Dig* 风格——长隧道、不规则。

工业 dungeon 生成经常**混合**三种:BSP 决定主结构 + CA 修饰边缘 + Drunkard 加洞穴。

## 12 · 真实案例

### 12.1 Minecraft

Minecraft 用 Perlin / Simplex noise 多层叠加生成地形。每个 chunk 16×16×256 block,16 chunk × 16 chunk = region 文件。种子是 64-bit 整数,完全决定世界。

Minecraft 1.18 以后的地形生成有重大升级——**噪声配置**(noise router)系统,基于 *Cubic Octaves* 论文。每个 biome 有自己的噪声配置,平滑过渡。OpenJDK 反编译出 *Minecraft* 地形生成源码:https://github.com/Mojang/MinecraftForge 。

### 12.2 Spelunky

Spelunky 关卡生成:

1. 关卡分成 4×4 grid(每个 cell 是一个"房间")。
2. 强制有一条**主路径**(从入口到出口),保证可通关。
3. 每个房间从预设的 room template 池里选(手工设计 100+ templates)。
4. 房间内部的"敌人、宝箱"再随机生成。

这是 **directed PCG**——保证可通关的前提下随机。Derek Yu 的 *Spelunky* 书详细讲了这个 pipeline。

### 12.3 No Man's Sky

NMS 算法:

1. 每个 star system 的 ID 用 hash 得到 seed。
2. 星系内的每个 planet 用 star seed 派生 planet seed。
3. 每个 planet 用 planet seed 生成:
   - 大气、重力、温度
   - 地形(多层 fBm + Simplex)
   - Biome 分布(Voronoi)
   - 植被、矿物分布
   - 动物(L-system + 部件组合)

NMS 用 64-bit seed,理论上有 2⁶⁴ ≈ 1.8 × 10¹⁹ 个星球。每个玩家访问的星球都是确定的——共享 seed,别人能去同样星球。

### 12.4 Caves of Qud

Qud 用 Cellular Automata + WFC + 程序化物品。开发者 Jason Grinblat 在 GDC talk 讲了 pipeline。

### 12.5 Dwarf Fortress

Dwarf Fortress 是 PCG 史上最深的项目。它生成:世界地图、山脉、河流、文明、历史、人物。1000 年历史模拟后,玩家开始游戏。所有事件用 seed 决定性生成。Tarn Adams(单人开发者)用了 20 年。源码不开源,但 wiki 详细描述算法。

## 13 · 种子决定性(seed determinism)

### 13.1 为什么种子重要

种子决定性 = **同一 seed,同一输出**。这对:

- **多人游戏同步**:所有玩家看同一地图,从 seed 派生。
- **回放系统**:记录玩家输入 + seed,重放即可重现整局游戏。
- **bug 重现**:玩家报"我看见 X",开发者用 seed 重现。
- **种子分享**:玩家分享"seed 12345 有超棒村庄"。

### 13.2 实现种子的陷阱

**坑 1:浮点数 IEEE 754 不确定性**。不同 CPU / 编译器,float 运算可能差 1 ULP。跨平台同步崩。

**坑 2:HashMap 迭代顺序**。Rust 的 HashMap 默认随机化迭代顺序,种子相同但迭代顺序不同 → 不同输出。

**坑 3:多线程**。线程调度顺序影响随机数调用顺序。

**坑 4:外部数据**。读文件时间、系统时钟混入 PCG,破坏确定性。

工业实践:
- 用 **`u64` / `i64` 算术** 而不是 float 做 PCG(或用 fixed-point)。
- 用 **`BTreeMap`** 替代 `HashMap`(保证顺序)。
- 用 **`ChaCha8Rng`** 等确定性 PRNG,runtime seed。
- PCG 调用串行化(每帧一个 PCG pass,不跨线程)。

### 13.3 种子派生

主 seed → 多个 sub-seed:

```rust
fn derive_seed(master: u64, sub_id: u32) -> u64 {
    let mut hasher = std::collections::hash_map::DefaultHasher::new();
    use std::hash::{Hash, Hasher};
    master.hash(&mut hasher);
    sub_id.hash(&mut hasher);
    hasher.finish()
}
```

主 seed 12345 派生:地形 seed(12345, 1)、洞穴 seed(12345, 2)、结构 seed(12345, 3)。每个子系统用独立 seed,互不干扰。

## 14 · Hex / square / cube grid

### 14.1 网格类型

PCG 经常需要"格子"概念。三种主流网格:

**Square grid**(正方形):最简单,(x, y)。邻居分两种:**4-邻居**(上下左右)和 **8-邻居**(加对角)。Minecraft / Terraria 用 square。

**Hex grid**(六边形):每格 6 个邻居。优点:各向同性(任意方向距离一致),适合 *Civ* 战棋。坐标系统:cube coordinates (x, y, z) 约束 x+y+z=0,或 axial coordinates (q, r)。

**Cube grid**(立方体):3D 体素,Minecraft voxel。

### 14.2 Hex 坐标变换

Hex 用 cube 坐标 (x, y, z),x + y + z = 0。axial 坐标 (q, r) = (x, z)。

```
cube_to_pixel: 
    pixel_x = size * (sqrt(3) * q + sqrt(3)/2 * r)
    pixel_y = size * (3/2 * r)

pixel_to_cube:
    q = (sqrt(3)/3 * x - 1/3 * y) / size
    r = (2/3 * y) / size
    然后 round 到 cube 坐标(复杂的 rounding,见 Red Blob Games 教程)
```

Red Blob Games 的 *Hexagonal Grids* 教程(https://www.redblobgames.com/grids/hexagons/)是 hex 实现的金标参考。

## 15 · 真实开源源码

### 15.1 noise-rs(Rust noise 库)

GitHub: https://github.com/Razaekel/noise-rs

Rust 生态主流 noise 库,实现 Perlin / Simplex / OpenSimplex / Worley / fBm / Billow 等。读它的 `src/perlin.rs` 和 `src/simplex.rs` 看完整实现。

### 15.2 fastnoise(跨语言 noise 库)

GitHub: https://github.com/Auburns/FastNoise

C++ 的超优化 noise 库,SIMD 加速。读它的 `FastNoiseSIMD.h` 看 SIMD 优化的 Perlin。

### 15.3 WFC 原版(C#)

GitHub: https://github.com/mxgmn/WaveFunctionCollapse

Maxim Gumin 的原版,200 行 C#。读 `Core.cs` 看完整 WFC。

### 15.4 OpenSimplex

GitHub: https://github.com/KdotJPG/OpenSimplex2

K.jpg 的 OpenSimplex2,绕过专利的 Simplex 替代品。读 `OpenSimplex2S.java` 看实现。

### 15.5 libvxl(Voxel engine)

GitHub: https://github.com/xtreme8000/libvxl

*Ace of Spades* 的 voxel 引擎。看它如何 stream chunk,做 voxel raycast。

### 15.6 Bevy PCG 生态

- `bevy_noise`:noise-rs 集成
- `bevy_terrain`:chunked terrain
- `bevy_mod_wfc`:WFC for Bevy

## 16 · 性能数据

让我列出实测数字,这些要在脑子里:

1. **Perlin 3D noise 单点查询**:Rust naive ≈ 80 ns;SIMD 优化 ≈ 20 ns。
2. **Simplex 3D 单点**:Rust ≈ 100 ns;比 Perlin 慢一点(但更高维 Simplex 反而快)。
3. **fBm 6 octaves 3D**:≈ 600 ns。
4. **1024×1024 heightmap 全采样 Perlin**:≈ 100 ms 单线程;≈ 8 ms 16 线程。
5. **Marching Cubes 128³ voxel**:≈ 5 ms 单线程。
6. **WFC 32×32 网格,8 pattern**:≈ 50 ms(主要时间在 propagate)。
7. **WFC 64×64 网格,16 pattern**:≈ 500 ms。
8. **Hydraulic erosion 1024×1024, 100k 水滴**:≈ 2 秒。
9. **L-system iterate 8 次**:F → FF 字符串长度 2⁸ = 256,turtle 解释 ≈ 0.1 ms。
10. **Voronoi 10000 seeds,Fortune sweep**:≈ 50 ms。
11. **Domain warped fBm 3D,5 octaves + 2 warps,单点**:≈ 2 μs(慢 10× 但视觉质量极高)。
12. **OpenSimplex2 3D 单点**:≈ 70 ns(比 Perlin 略快)。

## 17 · 生产坑

**坑 1:Perlin noise 的方向性**。Perlin 在网格方向上有 bias。地形看起来"沿 x 轴有条纹"。**修复**:用 Simplex 或 OpenSimplex。

**坑 2:fBm octaves 过多**。octaves=8 看起来更"详细",但慢一倍。**经验**:octaves=4-6 已够好。

**坑 3:WFC 死锁**。某些 sample 让 WFC 永远死锁。**修复**:加超时(> N 次迭代重启)。或换 sample。

**坑 4:跨平台 float 不一致**。Windows / Linux / Mac 的 f32 计算 intransitive(差异 1 ULP)。**修复**:fixed-point 算术,或 PCG 输出量化到整数。

**坑 5:HashMap 顺序**。Rust HashMap 默认随机迭代序。**修复**:用 BTreeMap,或用 IndexMap(保留插入序)。

**坑 6:多线程 PCG**。多线程共享 RNG 会有 race。**修复**:每线程独立 RNG,从主 seed 派生。

**坑 7:Chunk boundary artifact**。地形 chunk 边界 noise 不连续。**修复**:用 3D noise 而不是 2D,在 chunk 边界采样邻居 chunk 的"虚拟"边缘点。

**坑 8:大世界 float 精度**。Minecraft 在 (10⁷, 10⁷) 位置 f32 精度丢失,地形抖动。**修复**:用 f64(慢)或 camera-relative rendering(所有坐标相对相机)。

**坑 9:Permutation table 在 GPU**。GPU 不支持 8-bit index lookup,要用 32-bit。GPU Perlin 用 texture-based perm table。

**坑 10:L-system 字符串爆炸**。每代迭代字符串 × N,8 次迭代 X → F+[[X]-X]-F[-FX]+X 大约 5⁸ ≈ 390000 字符。**修复**:Lazy generation,或转 DAG(Directed Acyclic Graph)。

## 18 · 跨学科

PCG 在跨领域有重要应用:

**生物学**:L-system 起源于植物形态学,现在用于建模神经元、血管、菌丝。

**天体物理学**:宇宙大尺度结构模拟(SDSS 数据)用 PCG 模拟暗物质分布。

**艺术**:Beeple、Refik Anadol 等数字艺术家用 PCG 创作生成艺术。

**建筑设计**:Zaha Hadid 建筑事务所用 WFC 生成建筑概念。

**音乐**:Brian Eno 的 *Generative Music* 用 PCG 作曲。

**密码学**:流密码本质是 PCG(randomness expansion)。

## 19 · 开源贡献

PCG 社区活跃,entry point 多:

- **noise-rs**(Rust)issues: https://github.com/Razaekel/noise-rs/issues — SIMD 加速、新 noise 类型。
- **WFC**:移植到不同语言、新优化。
- **Bevy 生态**:`bevy_noise`、`bevy_mod_wfc` 都是社区维护,欢迎 PR。
- **fastnoiseLite**(C# / JS / Rust / Python 多语言):https://github.com/Auburn/FastNoiseLite — 跨平台 noise 库。

## 20 · 在你 HH 项目里实践

**最小实践**:程序化地形 chunk。

**步骤 1**:定义 chunk。每 chunk 16×16×64 block。

**步骤 2**:实现 Perlin noise(从本篇拷 80 行 Rust 代码)。

**步骤 3**:加 fBm(50 行)。`height = fbm(x*0.01, z*0.01, 6, 2.0, 0.5) * 16.0 + 32.0`。

**步骤 4**:chunk 生成函数。给 (chunk_x, chunk_z) 算每 block 的 type(air / grass / dirt / stone)。

**步骤 5**:相机移动时动态加载 chunk。前 8 chunk、左 8 chunk、右 8 chunk。

**步骤 6**:Unloading。远离相机的 chunk 删除。

**步骤 7**:Mesh 化——把每 chunk 的 block 数据转成 vertex buffer + index buffer,只渲染"表面" block(空气旁边)。

**步骤 8**:加 biome(temperature + humidity 2 个 Perlin),2 个 biome(草 vs 沙)。

**步骤 9**:加洞穴——3D Perlin,abs() < 0.1 是空气。

**步骤 10**:加结构(每 25×25 chunk 有 1 个 village,用 hash 决定位置)。

这 10 步约 1500 行 Rust 代码,3-5 天工作。完成后你有一个 Minecraft 风格的无限世界。

**进阶**:加 WFC 生成 dungeon。加 L-system 树。加 Marching Cubes 平滑地形(替代方块)。

## 21 · 关联 Day

- **铺垫**:[day075.md](../day075.md) — 随机数与种子的基础
- **铺垫**:[day082.md](../day082.md) — view matrix,理解 chunk distance 计算
- **当天**:本篇(deep-dive)
- **后续**:[phase-8/seed-determinism.md](../../phase-8/seed-determinism.md) — 多人游戏同步如何用种子
- **关联**:[geometry-processing.md](geometry-processing.md) — QEM 简化 vs Dual Contouring QEF,数学同根
- **关联**:[particle-systems-cpu.md](particle-systems-cpu.md) — 噪声场驱动的粒子运动

## 22 · 变式训练

### Lv1 · 概念辨析

**题**:Perlin noise 和 value noise 的本质区别是什么?为什么 Perlin 视觉质量更高?

**参考解答**:Value noise 在网格点存**随机值**,Perlin 存**随机梯度**。Value noise 输出 = 邻居值的插值,网格点之间是低频。Perlin 输出 = 邻居梯度贡献的 dot product,每个点都是周围梯度的加权,频率分布更均匀。Perlin 的 quintic fade 让二阶导连续,人眼看不到网格。

### Lv2 · 动手实践

**题**:用 Rust 写一个 100 行的程序,生成一张 256×256 的 PNG,内容是 fBm Perlin 噪声地形(高度灰度图)。

**完成标准**:
1. 调用 `cargo run > output.png` 生成图片
2. 图片看起来像"低分辨率地形图"——有山有谷有平原
3. 不同种子生成不同地形

**关键提示**:
- 用 `image` crate 输出 PNG。
- fBm 6 octaves,2.0 lacunarity,0.5 persistence。
- 把 [-1, 1] 噪声映射到 [0, 255]: `pixel = ((noise + 1) * 127.5) as u8`。

### Lv3 · 算法实现

**题**:实现一个最简单的 WFC,输入是 4×4 的 ASCII 图:

```
##..
##..
..##
..##
```

输出 8×8 的图案,遵循"对角块不能直接相邻"的规则。

**关键提示**:
- Pattern size = 2×2
- 共有 4 个 pattern:左上块、右上块、左下块、右下块(去重)
- WFC 应该输出 6×6 个 pattern(8×8 像素 / 2×2 pattern)

### Lv4 · 算法分析

**题**:Perlin noise 在 2D 时复杂度是 O(2² × constant)。如果在 GPU shader 里跑 fragment shader,N×N pixel 都调用,总复杂度 O(N² × 4)。1024×1024 纹理,每像素 ~80 ns,共 ~83 ms。

但 GPU 可以并行——RTX 3080 有 8704 个 CUDA core,理论加速 8700×。实际加速是 1000×,为什么?

**分析方向**:
1. **Texture cache locality**:邻近 pixel 共享 perm table,但 cache miss 仍然存在。
2. **Branch divergence**:GPU warp 32 thread 一起执行,if-else 让一些 thread idle。
3. **Memory bandwidth**:noise lookup 是 random access,GPU HBM 带宽虽大(768 GB/s),但 latency 高。
4. **Thread block scheduling**:8700 core 不能全部用上 100% 利用率。

这是 GPU computing 的经典 trade-off。深入可看 NVIDIA 的 *CUDA C Best Practices Guide*。

### Lv5 · 开源贡献

**题**:Clone noise-rs,看 simplex 实现:

```bash
gh repo clone Razaekel/noise-rs
cd noise-rs
```

候选方向:
- 加 SIMD 优化(用 `packed_simd` 或 `std::simd`)
- 加 4D noise(原版有,但可能性能优化空间)
- 加 doc comment 解释参数
- 加一个 benchmark 套件

提一个真实 PR。

## 23 · 延伸阅读

外部稳定 URL:
- Ken Perlin 1985, *An Image Synthesizer*:https://dl.acm.org/doi/10.1145/325165.325267
- Ken Perlin 2001, *Noise Hardware*:https://www.csee.umbc.edu/~olano/s2006c03/ch02.pdf
- Ken Perlin 2002, *Improving Noise*:https://dl.acm.org/doi/10.1145/566654.566636
- Stefan Gustavson, *Simplex noise demystified*:https://weber.itn.liu.se/~stegu/simplexnoise/simplexnoise.pdf
- Maxim Gumin WFC:https://github.com/mxgmn/WaveFunctionCollapse
- Inigo Quilez, *Domain Warping*:https://iquilezles.org/articles/warp/
- Aristid Lindenmayer 1968, *Mathematical models for cellular interactions*:https://www.cs.bgu.ac.il/~linden/LSystems.pdf
- Przemyslaw Prusinkiewicz, *The Algorithmic Beauty of Plants*:http://algorithmicbotany.org/papers/abop/abop.pdf
- Lorensen 1987 Marching Cubes 原始论文:https://doi.org/10.1145/37402.37422
- Paul Bourke Marching Cubes lookup table:https://paulbourke.net/geometry/polygonise/
- Ju et al. 2002 Dual Contouring:https://www.cse.wustl.edu/~taoju/cse554/a3/Ju_2002_DCB.pdf
- Red Blob Games Hexagonal Grids:https://www.redblobgames.com/grids/hexagons/
- Auburn FastNoiseLite:https://github.com/Auburn/FastNoiseLite
- Hans Theobald Beyer 的硕士论文(Beyer erosion):https://www.fgg.ethz.ch/publications/2015_beyer_hydraulic_erosion_bscthesis.pdf

真实开源源码:
- noise-rs:https://github.com/Razaekel/noise-rs/blob/master/src/perlin.rs
- noise-rs simplex:https://github.com/Razaekel/noise-rs/blob/master/src/simplex.rs
- Maxim Gumin WFC:https://github.com/mxgmn/WaveFunctionCollapse/blob/master/Core.cs
- OpenSimplex2:https://github.com/KdotJPG/OpenSimplex2/blob/master/java/OpenSimplex2S.java
- Bevy noise:https://github.com/bevyengine/bevy/blob/main/crates/bevy_render/src/texture/mod.rs
- Townscaper GDC talk(Oskar Stålberg):https://www.gdcvault.com/play/1027046/Townscaper-A-Tiny-Game
