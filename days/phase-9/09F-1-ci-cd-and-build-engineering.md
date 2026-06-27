---
phase: 9
sequence: "9F"
module: 1
title_en: "CI/CD & Build Engineering"
title_zh: "持续集成、持续交付与构建工程:从"能跑"到"能复现地交付""
type: deep-dive
difficulty: 4
duration: "3-4 小时"
domains: [rust, engineering, devops, game]
prereqs: ["09A-4-fuzz-determinism-and-regression", "phase-0/17-ci-cd"]
calibration: "工业级游戏 CI/CD + 交叉编译 + 可复现构建 + workspace 大型化 + Git LFS"
---

# 09F-1 · CI/CD 与构建工程

## 0 · "在我机器上能跑":一个让团队流血的句子

先把一个让所有职业开发者PTSD(创伤后应激障碍)的场景摆在你面前。你在你的 Arch Linux 笔记本上 `cargo build --release`,游戏跑得好好的,你顺手把构建出来的二进制塞进 release,推到 Steam。第二天早上,玩家社区炸了——Windows 用户双击你的 `.exe`,弹一个"找不到 VCRUNTIME140.dll",或者干脆闪退;macOS 用户被 Gatekeeper 拦在门外;某个 Linux 用户因为他的发行版比你老两个 glibc 版本,游戏连启动都启动不了。你的商店页被刷一星,你的退款率冲上 30%,而你还完全不知道为什么——"它明明在我机器上能跑啊"。

这个场景的变体在每一个跳过构建工程(build engineering)的团队身上重复发生。你的队友 clone 你的仓库,`cargo build` 失败,因为他缺一个系统库;你昨天构建出来的二进制,今天用同样的 commit 再 build 一遍,二进制不一样(因为时间戳、因为路径、因为并行度不同影响了 codegen 顺序);你 push 了一周的代码,某个 commit 把 Windows 编译搞坏了,你浑然不知,直到周末要发版时才发现——而你已经无法 bisect,因为中间几十个 commit 没一个在 Windows 上跑过测试。

这些都是**构建工程**的失败,而构建工程就是这一篇的主题。Phase 0 的 [17-ci-cd](../phase-0/17-ci-cd.md) 给过你 GitHub Actions 的基础——装 Rust、跑 `cargo test`、缓存、clippy。那是底座。这一篇把它从"basics"推到"industrial":为游戏设计的 build matrix、跨平台交叉编译、可复现构建(reproducible builds)、大型 workspace 的依赖治理、用 Git LFS 管理体积爆炸的二进制资产,以及怎么让所有这些在 CI 里自动跑起来,使你的项目在 push 的那一刻就被一台机器接管——它替你测、替你 build、替你产出可下载的可玩构建。

为什么这件事必须单独成篇?因为构建工程是职业游戏开发里**最被低估、又最值钱**的能力。一个能复现地、跨平台地、自动地交付二进制的团队,比一个代码写得漂亮但永远发不出能跑的二进制的团队,本质上更有价值。indie 团队之所以大量烂尾,有相当一部分不是死在游戏设计上,而是死在"我们没法让任何一台不是主程序的机器跑起我们的游戏"。这一篇就是来根治这件事的。

## 1 · 游戏项目的 CI:比普通 Rust 项目多测什么

你已经在 [17-ci-cd](../phase-0/17-ci-cd.md) 里见过一个通用的 Rust CI 模板:checkout → 装 Rust → `cargo build` → `cargo test` → clippy → fmt → audit。这套配置对,但它只回答了"这段 Rust 代码能编译、能过测试"这两个问题。一个游戏项目要回答的问题远不止这些,我们一个一个把它们加到 CI 里。

**第一个加进来的,是跨平台 build matrix。** 游戏是少有的、必须真正在三个桌面操作系统上都跑起来的 Rust 项目。普通的 CLI 工具你在 Linux 上 build,Windows 用户能凑合用 WSL;游戏不行——玩家不会为了你的游戏开 WSL。所以你的 CI 必须同时在 ubuntu-latest、windows-latest、macos-latest 上跑完整的 build + test,任何一个红了都算 CI 红。这与你 [09B-2](09B-2-subsystems-modules-plugins.md) 讲的平台抽象(platform abstraction)是一对——后者让你的**代码**能跨平台,前者让你的**CI** 真的在跨平台上验证。

**第二个加进来的,是把你 9A 序列织下的整个测试网跑起来。** 这不是一个泛泛的 `cargo test`,而是把你 [09A-1](09A-1-testable-game-architecture.md) 的纯函数单元、[09A-2](09A-2-unit-and-property-testing.md) 的 property test、[09A-3](09A-3-integration-and-snapshot-testing.md) 的集成与快照、[09A-4](09A-4-fuzz-determinism-and-regression.md) 的短时间 fuzz + 确定性回放,全部在 CI 里跑。CI 就是测试网真正生效的地方——你写在本地、不跑在 CI 的测试,等于没写。

**第三个加进来的,是游戏特有的资产验证(asset validation)。** 这是普通 Rust CI 完全不会涉及、但对游戏项目至关重要的一块。你的代码引用了 `assets/textures/hero.png`,这个文件真的存在吗?所有贴图都是支持的格式(没有混入一个老的 BMP)吗?所有 shader 在三个平台上都能编译过吗(一个 GLSL 在 NVIDIA 上能编、在 Apple Silicon 上编不过的事时有发生)?这些都可以写成自动化的检查脚本,在 CI 里每次 push 都跑,把"少提交了一个资产文件"这种低级但灾难性的错误在它进 main 之前就拦下来。

**第四个加进来的,是产出可下载的可玩构建(playable build per commit)。** 这是游戏 CI 区别于普通项目 CI 最显著的特征。普通 CLI 工具的 release 是周期性的——一个月发一次。游戏的 playable build 是**每个 commit 都要有**的——美术想看今天的改动长什么样、设计想测一下刚调的数值、QA 想验一下昨晚修的 bug,他们都需要"今天的构建"。你的 CI 应该在每次 push 后,自动 build 出一个 release,上传到一个可下载的地方(GitHub Artifacts、Steam beta branch、或一个内部 download page),让团队里任何角色一键拿到今天的游戏。这一条做好了,团队的迭代速度会肉眼可见地提升。

把这些加在一起,CI 不再是"跑测试"那么简单,而是一个完整的、自动化的、每次 commit 都触发的"构建 + 验证 + 交付"管线。接下来我们用 GitHub Actions 的 YAML 把这条管线写出来,讲清楚每一行在干什么——我不会把 YAML 往那一摆让你自己读,我会像写散文一样逐段 narrate。

## 2 · 一份工业级游戏 CI 的 YAML,逐段 narrate

我们从一个完整的游戏 CI workflow 开始,然后我一段一段讲。文件放在你 HH 仓库的 `.github/workflows/ci.yml`。

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
  workflow_dispatch:   # 允许手动触发,排错时极其有用

env:
  CARGO_TERM_COLOR: always
  RUST_BACKTRACE: 1
  RUSTFLAGS: "-D warnings"   # warning 就是 error,零容忍
```

顶部这一段定义触发条件。`on: push` 到 main、任何 `pull_request`,以及一个 `workflow_dispatch`——这个手动触发入口平时用不上,但当你 CI 莫名其妙红了、想反复触发同一个 commit 调试时,它救命。`env` 块设了几个全局环境变量,其中 `RUSTFLAGS: "-D warnings"` 这一句把"零 warning 容忍"焊死在 CI 层面——本地你可以留 warning 慢慢修,但只要它进了 CI,任何一个 warning 都让整个 build 失败。这是职业工程纪律。

接下来是测试 job,这是 CI 的核心。

```yaml
jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]
        rust: [stable]
        include:
          - os: ubuntu-latest
            rust: beta
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
        with:
          lfs: true              # 拉取 Git LFS 资产,后面 §6 细讲
      - uses: dtolnay/rust-toolchain@master
        with:
          toolchain: ${{ matrix.rust }}
          components: clippy, rustfmt
      - uses: Swatinem/rust-cache@v2
      - name: Format check
        run: cargo fmt --all -- --check
      - name: Clippy
        run: cargo clippy --all-targets --all-features -- -D warnings
      - name: Install nextest
        run: cargo install cargo-nextest --locked || true
      - name: Test (nextest)
        run: cargo nextest run --all-targets
      - name: Doc tests
        run: cargo test --doc
```

`strategy.matrix` 这一段是这份 CI 的灵魂之一。它声明:这个 test job 会在 ubuntu + windows + macos 上各跑一次,`fail-fast: false` 保证一个平台红了不会取消另外两个——你想一次看到所有平台的失败,而不是修一个、push、等十分钟、再发现下一个。`include` 又额外加了一个 ubuntu + beta Rust 的组合,让你持续知道"下一个 Rust 版本会不会破坏你的构建",这种"未来兼容性"的早期预警在工业里非常值钱。

`actions/checkout@v4` 后面那个 `lfs: true` 是游戏项目特有的细节。普通项目 checkout 默认拉所有文件就够了,但你的仓库里如果有用 Git LFS 存的大资产(贴图、模型、音频),不打开 `lfs: true` 的话 LFS 文件会变成一个 100 字节的指针文件——你的 CI 跑起来就发现"贴图加载失败",但你完全不知道为什么。这是个新手坑,记住:游戏 CI 的 checkout 永远要带 `lfs: true`。

`Swatinem/rust-cache@v2` 这一行是性能优化的大头。它缓存 `~/.cargo/registry` 和 `target/`,基于 Cargo.lock 的 hash 判断要不要 invalidate。第一次 build 仍然慢(可能十几分钟),但后续命中缓存能快 3-10 倍。对一个有几十个依赖的中型游戏项目,这一条把你的 CI 反馈时间从"等一杯咖啡"压到"喝一口水"。

测试这里我用了 `cargo-nextest` 而不是裸 `cargo test`。nextest 是一个 Rust 测试运行器,比 `cargo test` 快很多(并行更激进、隔离更好),输出更友好,失败重跑更智能。它是当下 Rust 社区的事实标准——bevy、ripgrep、nushell 这些大项目都换了。`cargo install cargo-nextest --locked || true` 里的 `|| true` 是个防御:如果 nextest 因为某个原因装不上(比如刚发布的版本有 bug),fallback 到下面的 doc tests 还能跑,不至于整个 CI 因为工具安装失败而红。

接下来是资产验证 job。这是个**完全为游戏项目设计**的 job,普通 Rust CI 里你看不到。

```yaml
  asset-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          lfs: true
      - name: Verify referenced assets exist
        run: cargo run --bin asset-check --locked
      - name: Validate texture formats
        run: |
          find assets/textures -type f \( -name '*.bmp' -o -name '*.tga' \) \
            | tee /dev/stderr \
            | (! read line || (echo "Unsupported texture format: $line" && exit 1))
      - name: Shader cross-compile check
        run: cargo run --bin shader-check --locked -- --backends glsl,hlsl,msl,spirv
```

这个 job 做三件事,每一件都对应一类真实的灾难。第一件,`asset-check` 是你自己写的一个小工具,扫遍游戏代码里所有形如 `load("assets/textures/hero.png")` 的引用,检查那个文件在仓库里真的存在。少了资产文件是新手最常见的低级错误——你在本地忘了 `git add`,CI 不检查,玩家运行时游戏崩,你查半天才发现是一个 `:` 写成了 `;` 的路径错。让一个脚本替你查。

第二件,贴图格式检查。你的管线规定只接受 PNG / KTX2,但有人手贱提交了一个 BMP——本地能跑(因为你的加载器宽容),但跑到某些 Windows 机器上颜色错乱(BMP 的通道顺序坑死人)。用一行 `find` 把仓库里所有 `.bmp` 和 `.tga` 找出来,如果有一个就直接 fail。这种"格式 gate"在资产驱动的项目里极其有效。

第三件,shader 跨后端编译。你 [09C-1](09C-1-gpu-architecture-and-explicit-api.md) 会讲现代 GPU API 的 shader 是统一用 WGSL/SPIR-V 写、再 transpile 到 GLSL/HLSL/MSSL 各个后端。这个 transpile 不是 Rust 编译器替你做的——一个 shader 在 GLSL 后端能编、在 HLSL 后端可能因为某个语义(semantic)绑定的差异编不过。CI 里每次 push 都跑一次"所有 shader 在所有后端上能不能编译",能在它 ship 到玩家显卡上之前,把这种后端兼容性问题在 CI 里抓出来。

最后是构建和发布 job。

```yaml
  build-artifact:
    needs: [test, asset-check]
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    strategy:
      matrix:
        include:
          - os: ubuntu-latest
            target: x86_64-unknown-linux-gnu
            artifact: hh-linux
          - os: windows-latest
            target: x86_64-pc-windows-msvc
            artifact: hh-windows.exe
          - os: macos-latest
            target: aarch64-apple-darwin
            artifact: hh-macos
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
        with:
          lfs: true
      - uses: dtolnay/rust-toolchain@stable
        with:
          targets: ${{ matrix.target }}
      - uses: Swatinem/rust-cache@v2
      - name: Build release
        run: cargo build --release --target ${{ matrix.target }}
      - name: Package with assets
        run: |
          mkdir -p staging/assets
          cp target/${{ matrix.target }}/release/${{ matrix.artifact }} staging/
          cp -r assets/* staging/assets/
      - uses: actions/upload-artifact@v4
        with:
          name: hh-${{ matrix.target }}-${{ github.sha }}
          path: staging/
          retention-days: 30
```

注意几件事。`needs: [test, asset-check]` 让 build job 等到测试和资产验证都通过才跑——坏代码不会被发出去。`if: github.event_name == 'push' && github.ref == 'refs/heads/main'` 让 build 只在 push 到 main 时跑,不在 PR 上跑(省 CI 时间,因为 build 是慢的部分)。`actions/upload-artifact@v4` 把构建产物上传到 GitHub,团队任何人在 Actions 页面点一下就能下载今天的可玩构建。`retention-days: 30` 控制保留时间——构建产物很占空间,GitHub 给免费用户的 artifact 存储是有限的,30 天一般够 QA 用,超过自动删。

这就是一份工业级游戏 CI 的雏形。它做的四件事——跨平台 build matrix、跑完整测试网、资产验证、产出可下载构建——是任何职业游戏团队的最小 CI 配置。你提交它进仓库,从此每次 push 都被一台机器接管,你团队里的美术、设计、QA 都能从今天的构建里拿到"今天游戏长什么样",这是没 CI 的团队完全享受不到的迭代速度。

## 3 · 交叉编译:在 Linux 上 build 出 Windows 二进制

接下来这块是构建工程里最让人头疼、但也是回报最大的能力——交叉编译(cross-compilation)。情景很具体:你是 Linux 主力开发者,你想 CI 的 ubuntu runner 上直接 build 出一个 Windows `.exe`,而不是非得开一个 windows-latest runner(Windows runner 慢、贵、配额紧)。或者反过来,你想从 Windows build 出 Linux 二进制(虽然这个方向少见,因为 Linux 开发者多)。这就需要交叉编译。

Rust 的交叉编译在"纯 Rust"的部分非常简单——你 `rustup target add x86_64-pc-windows-gnu`,然后 `cargo build --target x86_64-pc-windows-gnu`,理论上有二进制产出。问题在于,Rust 不只是 Rust。你的游戏几乎肯定会用到 C 依赖:你 [09C](09C-1-gpu-architecture-and-explicit-api.md) 要链 Vulkan / DX12 / Metal 的 loader,你用 SDL / winit 做窗口,你用 stb_image 或 libpng 做图像解码,你可能用 miniaudio 做音频。这些 C 依赖在交叉编译时,需要的是**目标平台(target)的 C 工具链和系统库**——你 Linux 上有 Linux 版的 libpng,但没有 Windows 版的。这就是 C 依赖交叉编译的痛点。

解决方案有两条主流路径,我们分别看。

**第一条路径,用 mingw-w64 toolchain 手工配。** 这是经典做法,适合 Linux → Windows GNU target。在 Arch 上:

```bash
sudo pacman -S mingw-w64-gcc
rustup target add x86_64-pc-windows-gnu
```

然后告诉 cargo 用 mingw 的 linker。在 `.cargo/config.toml` 里:

```toml
[target.x86_64-pc-windows-gnu]
linker = "x86_64-w64-mingw32-gcc"
ar = "x86_64-w64-mingw32-ar"
```

然后 `cargo build --target x86_64-pc-windows-gnu`,只要你的 C 依赖能从 mingw 找到(纯 Rust 的 crate 自动 buildscript 处理),你就能拿到 `.exe`。这条路的问题是:任何有 C 依赖的 crate,它的 buildscript 也得在交叉环境里能编 C 代码,这经常卡在各种 system header 找不到上。对一个游戏项目,这通常很快就崩。

**第二条路径,用 cargo-xwin。** 这是一个更现代、更省心的方案,它的思路是:不在 Linux 上配 mingw,而是用 Microsoft 官方的 Windows SDK headers + CRT,通过 wine + xwin 模拟出"一个 Windows 的 build 环境"。装它:

```bash
cargo install cargo-xwin
rustup target add x86_64-pc-windows-msvc
cargo xwin build --release --target x86_64-pc-windows-msvc
```

`cargo xwin` 自动下载 Windows SDK、配好环境,然后调用 cargo 用 MSVC target build。这条路的好处是:你拿到的 `.exe` 和在真 Windows 上用 MSVC build 出来的二进制 ABI 兼容(因为用的是真 MSVC CRT),不是 mingw 那套略有差异的 ABI。对游戏这种重度依赖 Windows 原生 API 的项目,这个差异重要——很多 Windows 游戏用的库只发 MSVC ABI 的 `.lib`,mingw 链不上。

无论选哪条路,有几条工程纪律能让你的生活好过很多。**第一,从一开始就跨平台,不要等到要发版了才试。** 你在第一天就 `cargo build --target x86_64-pc-windows-msvc`,出问题立刻知道是哪一行代码、哪个依赖不兼容;你要等到三个月后才试,问题已经埋在几百个 commit 里,根本定位不到。这条纪律的更深层版本是:你的代码结构本身要为跨平台而生,平台相关代码隔离到一个个明确的"平台层(platform layer)"后面——这正是 [09B-2](09B-2-subsystems-modules-plugins.md) 讲子系统分层时的核心思想。平台抽象不只是"代码好看",它是"让交叉编译能工作"的前提。

**第二,把交叉编译跑进 CI,每天验证。** 你 CI 里加一个 `cross-build` job,跑 `cargo xwin build --target x86_64-pc-windows-msvc`。这个 job 不出二进制可下载(那个还是用 windows runner 出,质量更可靠),它的唯一目的是**验证你的代码确实能交叉编译过**。一旦某天某个新依赖破坏了交叉编译,这个 job 立刻红,你当天就知道,而不是等到发版时才发现。

```yaml
  cross-build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
        with:
          targets: x86_64-pc-windows-msvc
      - uses: Swatinem/rust-cache@v2
      - name: Install cargo-xwin
        run: cargo install cargo-xwin --locked
      - name: Cross-build for Windows
        run: cargo xwin build --release --target x86_64-pc-windows-msvc
```

这就是一个" Canary(金丝雀)"job——它的存在不是为了产出,是为了**持续证明交叉编译没坏**。职业 CI 里这种"持续验证某件事没崩"的 canary job 非常常见。

## 4 · 可复现构建:同一个 commit + 同一个工具链 = 位级相同的二进制

现在我们到了构建工程里最玄、但工业价值最高的概念——可复现构建(reproducible builds)。它的定义听起来简单:**给定同一个 commit、同一个工具链版本、同一套构建参数,你 build 出来的二进制应该是位级(bit-identical)相同的。** 任何两次 build,二进制逐字节一致。

这件事听起来像废话——"同样的输入当然同样的输出"。但在实践中它非常难做到,因为现代构建系统里有大量"隐式输入",它们悄悄影响二进制但不被你记录。理解这些敌人,是做到可复现的前提。

**第一个敌人是时间戳。** 默认情况下,Rust 编译器会把 build 时间嵌进二进制的某些 metadata;很多 C 库的 buildscript 也会。你昨天 build 的二进制里有一个 `Build date: 2026-06-26 14:32`,今天 build 出来是 `Build date: 2026-06-27 09:11`——两个二进制不一样,哪怕源代码完全相同。Rust 的对策是用 `--remap-path-prefix` 配合 `SOURCE_DATE_EPOCH`(一个被 [reproducible-builds.org](https://reproducible-builds.org) 标准化的环境变量)把时间戳固定到一个确定的值。

**第二个敌人是 build 路径。** 你的代码里有 `file!()` 宏,它把 `src/main.rs` 这样的相对路径嵌进 panic 信息。但 `file!()` 嵌的不是相对项目根的路径,而是 build 时的工作目录绝对路径——你 Linux 上是 `/home/sun/src/hh/src/main.rs`,CI 上是 `/home/runner/work/hh/hh/src/main.rs`,二进制不同。Rust 的对策是用 `--remap-path-prefix` 把绝对路径 rewrite 成相对路径。

```bash
export SOURCE_DATE_EPOCH=1700000000   # 一个固定的 epoch 值
RUSTFLAGS="--remap-path-prefix=$(pwd)=/src" cargo build --release
```

这两行加上之后,你本地 build、CI build、队友 build,嵌进二进制的路径都是 `/src/main.rs`,时间戳都是同一个 epoch,这一类差异就消除了。

**第三个敌人是并行度。** 这是 Rust 可复现构建里最阴险的一个。Rust 编译器在并行 codegen 时,不同线程的完成顺序会影响某些 codegen 决策(比如 monomorphization cache 的填充顺序),进而影响最终二进制的字节布局。Rust 团队这些年一直在修这类问题,但仍有边角情况——要做到严格的位级复现,有时候你需要固定 codegen units 为 1(`-C codegen-units=1`)和禁用 incremental(`CARGO_INCREMENTAL=0`)。这些会让 build 变慢,所以只在"我要产出一个可验证的 release"时打开,日常开发不开。

```toml
# Cargo.toml 的 [profile.release],只在严格复现时调
[profile.release]
codegen-units = 1
incremental = false
```

**第四个敌人是构建依赖里的随机性或时间相关代码。** 偶尔某个 buildscript 用了 `SystemTime::now()` 来生成某个版本号、用 UUID 生成某个标识符,这些都会破坏复现。排查方法是把同一个 commit build 两次,diff 二进制,定位差异区域,顺藤摸瓜找到那个不规矩的 buildscript。

那么,为什么你要花精力做可复现构建?它值钱在哪?

第一个价值是**信任**。当一个二进制是从公开源码 build 出来、并且社区里任何人都能用同样的 commit + 同样的工具链 build 出位级相同的二进制时,这个二进制是可审计的——安全研究员可以反汇编你 ship 的二进制,和源码对照,确认没有后门。这是 Debian、NixOS 这类发行版的核心质量保证,也是为什么 Linux 发行版的官方包都是可复现 build 的。

第二个价值是**bisecting**。你 [09A-4](09A-4-fuzz-determinism-and-regression.md) 讲过 git bisect——但 bisect 只对源码有效,对二进制无效。如果你 ship 的二进制不可复现,你无法回答"这个二进制对应哪个 commit"——因为它不是任何一次 build 的产物,它是"某次 build 的产物"。可复现构建让你能从二进制反推到精确的源码状态,这对线上事故排查极其有用。

第三个价值是**缓存效率**。如果你的 build 不可复现,你的 CI cache 命中率永远不够好,因为相同的输入产生了不同的输出,缓存没法信任。可复现 build 让"输入相同 → 输出相同"严格成立,缓存可以放心用。

职业工程实践是:你的 CI 里专门跑一个"复现验证"job,build 同一个 commit 两次,diff 两个二进制,如果有任何字节差异就 fail。这个 job 平时不需要每次 push 都跑(慢),但发版前一定跑——它给你"这个 release 二进制是可复现的"这个保证。

```yaml
  reproducibility-check:
    if: startsWith(github.ref, 'refs/tags/v')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
      - name: Build #1
        env:
          SOURCE_DATE_EPOCH: "1700000000"
          RUSTFLAGS: "--remap-path-prefix=$PWD=/src"
        run: cargo build --release
      - run: cp target/release/hh /tmp/hh-1
      - name: Clean
        run: cargo clean
      - name: Build #2
        env:
          SOURCE_DATE_EPOCH: "1700000000"
          RUSTFLAGS: "--remap-path-prefix=$PWD=/src"
        run: cargo build --release
      - name: Compare
        run: cmp /tmp/hh-1 target/release/hh && echo "REPRODUCIBLE"
```

`cmp` 两个二进制,相同就 echo "REPRODUCIBLE",不同就非零退出、CI 红。发版前必须绿。这是 Debian / NixOS / Firefox / Tor Browser 这些工业级项目都在做的实践,你给 HH 也加上,就是和它们站在同一个工程高度上。

## 5 · Workspace:把你的引擎拆成 crate,crate 就是层边界

到这里我们一直假设你的游戏是一个 crate——单个 Cargo.toml,单个 `src/`。这在 phase 0~8 学习阶段没问题,但你的引擎一旦长到几千行、几万行,单 crate 就开始折磨你了。`cargo build` 慢得吓人,任何一处改动触发整个 crate 重编;`cargo test` 一次性跑所有测试,反馈慢;你的依赖关系是一团乱麻,因为 Rust 的可见性在单 crate 内默认很松,谁都能 import 谁,自然就长出意大利面。这时候你要做的是把你的引擎拆成一个 **Cargo workspace**。

Workspace 的核心思想是:你有多个 crate(比如 `hh-core`、`hh-render`、`hh-physics`、`hh-audio`、`hh-game`),它们共享同一个 `Cargo.lock` 和同一个 `target/` 目录,但每个 crate 有自己的 `Cargo.toml` 和 `src/`。顶层是一个**虚拟 manifest**(virtual manifest):

```toml
# Cargo.toml(根,虚拟 manifest)
[workspace]
members = ["crates/core", "crates/render", "crates/physics", "crates/audio", "crates/game"]
resolver = "2"

[workspace.package]
version = "0.1.0"
edition = "2021"
license = "MIT"

[workspace.dependencies]
# 在这里统一声明依赖版本,子 crate 用 version = "x" 引用
anyhow = "1.0"
bytemuck = "1.14"
glam = "0.27"
log = "0.4"
```

这个虚拟 manifest 本身**不是一个 crate**——它没有 `[package]` 段,只有 `[workspace]`。它把所有子 crate 当作 members,并且用 `[workspace.dependencies]` 这个机制**集中管理依赖版本**。子 crate 引用依赖时这样写:

```toml
# crates/render/Cargo.toml
[package]
name = "hh-render"
version.workspace = true
edition.workspace = true

[dependencies]
hh-core = { path = "../core" }
anyhow.workspace = true
bytemuck.workspace = true
glam.workspace = true
```

`anyhow.workspace = true` 这一行意味着"用 workspace 根里声明的 anyhow 版本"。这个机制解决了大型项目的一个老大难问题:**依赖版本漂移**。没有 workspace 时,你 5 个 crate 各自声明 `glam = "0.27"`,半年后某个 crate 升到 `"0.28"`,你又忘了同步其他 crate,bug 就来了——某段代码用了 0.28 的 API,链接时才发现两个 crate 之间 glam 版本不兼容。workspace 强制所有子 crate 用同一个版本,从根上消除这个 bug。

workspace 的更大价值是它强制你思考**层边界(layer boundary)**。这正好接上 [09B-2](09B-2-subsystems-modules-plugins.md) 讲的子系统分层——那一篇讲的"core 不依赖 render、render 不依赖 game"这些规则,在单 crate 里靠人自觉,在 workspace 里**靠 Cargo.toml 的 `[dependencies]` 段强制**。`hh-core` 的 Cargo.toml 不写 `hh-render`,那 core 里就不可能 `use hh_render::*`——编译器直接拒绝。Cargo 的依赖图就是你引擎架构的物理体现,crate 就是层边界。这是 workspace 比"单 crate + module"显著强的地方。

```
┌────────────────────────────────────┐
│           hh-game (顶层)            │  游戏逻辑、状态机、内容
├────────────────────────────────────┤
│ hh-render │ hh-physics │ hh-audio  │  各功能子系统
├────────────────────────────────────┤
│            hh-core (地基)            │  数学、容器、平台抽象
└────────────────────────────────────┘
```

这个金字塔是依赖图——上层依赖下层,下层不知道上层存在。你的 core crate 完全不知道有个 render crate 在用它;render 不知道有个 game crate 在用它。这个"反向无知"正是好分层的关键——下层稳定,上层可以随便改,改 game 不影响 core。

workspace 还带给你 CI 加速。因为 `target/` 是共享的,你改了 `hh-audio` 的代码,CI 只需要重新 build `hh-audio` 和依赖它的 `hh-game`,不用重新 build `hh-render`、`hh-physics`。Cargo 自动判断哪些 crate 受影响(基于依赖图),只 build 这些。一个长到 5 万行的游戏,如果结构良好,改一处音频代码可能 CI 只需要 30 秒,而不是从头 build 的 5 分钟。这种"局部重编"是大型项目 CI 反馈快慢的决定性因素。

最后一条 workspace 实践:**每个 crate 都有独立的 `cargo test`**。`cargo test --workspace` 跑所有 crate 的所有测试,但 `cargo test -p hh-physics` 只跑 physics crate 的测试。在 CI 里,你可以为每个 crate 起一个独立的 job,并行跑——这把测试时间从串行的 N 分钟压到并行的 max(N)。这是 workspace 给 CI 的另一个提速杠杆。

```yaml
  test-per-crate:
    strategy:
      matrix:
        crate: [core, render, physics, audio, game]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
      - uses: Swatinem/rust-cache@v2
      - run: cargo nextest run -p hh-${{ matrix.crate }}
```

5 个 crate 5 个并行 job,总时间约等于最慢那个 crate 的测试时间,而不是 5 个加起来。这种"按 crate 切分 CI"是大型 Rust 项目(bevy、rustc 自己)的标准做法。

## 6 · Git LFS:当你的仓库被贴图和模型塞爆

讲完代码组织,我们聊资产组织——这是游戏项目独有的存储压力。你的仓库一开始很小,几十 KB 的 Rust 源码。然后你开始加资产:一张 4K 贴图 8MB,一个角色模型 20MB,一段音效 2MB,一首 BGM 10MB。等你做完一个 demo,仓库里塞了几百个 MB 的二进制文件。然后灾难开始:**Git 在大文件上极其难用**。

Git 是为文本文件设计的——它存的是 diff,文本 diff 很小、很快。但二进制文件几乎无法 diff,Git 只能存整个文件的完整副本。你改一张贴图的一个像素,commit 一次,Git 把整张贴图(8MB)再存一份。改十次,80MB 的历史。clone 仓库时,所有历史版本的所有贴图都要下载——一个 500MB 的 working tree,clone 下来可能要拉 5GB。新人 clone 一次等半小时。CI runner 每次跑都要拉一遍,慢得要死。`git status` 检查几百 MB 的二进制文件 hash,卡顿明显。仓库到了某个体量,基本就废了——所有人都害怕 clone。

Git LFS(Large File Storage)就是治这个的。它的核心思想:**二进制大文件不存到 Git 仓库本身,而是存到一个外部的 LFS server,Git 仓库里只保留一个几百字节的指针文件**。clone 时默认只拉当前版本的指针指向的真实文件,旧版本不拉,除非你显式要。这样 working tree 仍然有几个 MB 的贴图(对应你当前用的版本),但 `.git` 历史只有几百字节的指针,clone 飞快。

启用 LFS 在 Arch 上:

```bash
sudo pacman -S git-lfs
git lfs install   # 一次性,在你的 ~/.gitconfig 里注册 LFS 的 filter
```

在你的 HH 仓库里告诉 LFS 哪些文件用 LFS 存:

```bash
cd ~/src/handmade-hero
git lfs track "*.png" "*.jpg" "*.ktx2" "*.glb" "*.gltf" "*.ogg" "*.wav" "*.mp3"
git add .gitattributes
git commit -m "Track large assets with Git LFS"
```

`git lfs track "*.png"` 这条命令在 `.gitattributes` 文件里加了一行 `*.png filter=lfs diff=lfs merge=lfs -text`——这是 Git 的 filter 机制,告诉 Git "凡是 `.png` 文件,在 commit 时走 LFS filter"。从此你 `git add hero.png`,存进 LFS server;仓库里只有一个指针文件。注意:**`git lfs track` 之后,之前已经 commit 进仓库的 PNG 不会自动迁移**——只对之后新加的 PNG 生效。要迁移历史,得用 `git lfs migrate import`,这是个改写历史的操作,谨慎使用。

LFS 不是免费的,你需要知道它的代价。**第一,你需要一个 LFS server。** GitHub 提供免费的 LFS 存储,但额度有限(免费用户 1GB 存储 + 1GB/月带宽),超了要付费。Bitbucket、GitLab 也有自己的 LFS 配额。对一个游戏项目,几 GB 的资产很常见,LFS 带宽很容易超——尤其是你的仓库被频繁 clone 时(每次 clone 拉一份 LFS 内容,吃带宽)。**第二,LFS 增加了一层复杂度。** 你的 CI 必须记得 `actions/checkout` 带 `lfs: true`(我们前面 §2 的 YAML 里就有);新人 clone 仓库前要确保装了 `git-lfs`,否则拉下来全是 100 字节的指针文件,游戏跑起来一片空白。**第三,LFS 是 vendor lock-in。** 你的资产存在 GitHub 的 LFS server 上,如果你想迁到 GitLab,迁移 LFS 是个麻烦事——资产和源码不在同一个地方了。

**当资产真的体量爆炸时,LFS 也撑不住。** 一个有几十 GB 贴图、上千个 3D 模型的真实商业游戏,LFS 的带宽账单会让你破产。这时候职业团队转向**专门的资产数据库(asset database / asset pipeline)**——资产存到一个外部的存储(可能是 SVN、Perforce 的 Helix Core——这俩对大文件支持远好于 Git,所以 AAA 工作室至今还在用 Perforce 管资产),或者用更现代的方案,如 Plastic SCM、git-annex、或自建的资产管线。Git 只管源码,资产由另一套系统管。

但对 HH 这种独立游戏规模,LFS 是最务实的中间方案——比把贴图硬塞进 Git 仓库强一万倍,又比上 Perforce 简单一万倍。**用 LFS 把资产和源码分离,这是 indie 游戏项目的标配。**

## 7 · 在你 HH 项目里动手(做中学红线)

这一篇的动手部分,是把上面所有概念落到你的 HH 项目里。做完这些,你的 HH 项目就拥有了职业级的构建工程基础设施。

**第一步,建立 GitHub Actions CI workflow。** 在你的 HH 仓库创建 `.github/workflows/ci.yml`,内容基于 §2 那份模板,根据你的项目实际调整。最小化的目标是:`push` 到 main 或开 PR 时,自动在 ubuntu / windows / macos 三个平台上跑 `cargo build` + `cargo nextest run` + `cargo clippy -D warnings` + `cargo fmt --check`。第一次跑可能很慢(几台机器各自冷启动 build 十几分钟),但跑通之后,从你 `git push` 那一刻起,你就知道:你的代码在三平台上都编译过、测试过。这一刻开始,你不再"在盲发"。

**第二步,加一个 `build-artifact` job。** 在 CI 通过后,build 一个 release,打包 `assets/` 目录,用 `actions/upload-artifact@v4` 上传。这样每次 push 到 main,都产生一个 30 天有效期的可下载构建。把下载链接发给你的朋友(他没有 Rust 环境,但有 Windows/Mac),让他双击 `hh-windows.exe` 看能不能跑起来。这一步会立刻暴露你之前没意识到的跨平台问题——缺 DLL、字体找不到、贴图路径大小写不对(Linux 文件系统大小写敏感、Windows 不敏感,这是跨平台经典的坑)。每个暴露出来的问题都修掉,你的下一份构建就更稳。

**第三步,加 cross-build canary。** 装上 `cargo-xwin`,在 ubuntu CI runner 上加一个 job,跑 `cargo xwin build --target x86_64-pc-windows-msvc`,只验证能编译过,不出 artifact。这个 job 平时没什么用,但某天你引入一个新的 C 依赖、它破坏了交叉编译,这个 job 立刻红——你的"未来 self"会感谢现在的你。

**第四步,资产上 LFS。** 把你 HH 仓库里现有的 `.png` / `.png` / `.wav` / `.ogg` 这些大资产用 `git lfs track` 接管。提交 `.gitattributes`,从下一个 commit 起,新加的资产进 LFS。你不需要立刻迁移历史,先让"未来的资产"自动走 LFS,这是零代价的第一步。等仓库 size 真的成问题时,再考虑 `git lfs migrate import`。

**第五步,验证"一个命令构建"。** 拉一个朋友(或者你自己换一台干净的机器/VM),clone 你的仓库,跑**一条**命令——理想情况下是 `cargo run --release`——游戏应该完整 build + run 起来。如果失败了,记录失败原因:缺 LFS?那你的 README 要写明 clone 前装 git-lfs。缺系统库?那你要么把它改成纯 Rust 依赖,要么在 README 写清楚依赖。缺字体?你要把字体打进 assets。这个"一个命令构建"的属性,职业上叫 **build from clean**(冷构建),是任何交付级项目的基本要求——别人不能在你的机器上跑你的游戏,他必须能在他自己的机器上跑。

做完这五步,你的 HH 项目就有了:三平台自动 CI、可下载的可玩构建、交叉编译 canary、LFS 管理的资产、以及"clone 后一条命令跑起来"的可复现性。这五件事加起来,就是 indie 游戏项目从"个人玩具"到"可交付产品"的分水岭。Casey 在 HH 里完全没有这一层——他不在乎,因为 HH 不发版;但你要发版,你必须有这一层。

## 8 · 练习

**练习一(难度 1),概念题。** 回答这三个问题,并把答案写在你的笔记里:(a) 为什么"零 warning 容忍"是职业 CI 的标配?它和"warning 不就是 warning 嘛,跑得动就行"的差距在哪?(b) workspace 的 `[workspace.dependencies]` 解决了什么具体问题?(c) Git LFS 的"指针文件"长什么样?找一个启用 LFS 的 GitHub 仓库,clone 时不装 git-lfs,看看那个指针文件的内容。

**练习二(难度 2),动手实践。** 完成上面 §7 的第一步和第二步——给你的 HH 项目建一个三平台 CI,产出可下载构建。把构建链接发给一个用 Windows 的朋友,让他试运行,把任何运行失败都修掉。这一步的产出(一个能在 Windows 上双击运行的 `hh.exe`)是你 HH 项目从"我能跑"到"别人能跑"的实质跃迁。

**练习三(难度 3),进阶工程。** 给你的 HH 项目做可复现构建验证。设好 `SOURCE_DATE_EPOCH` 和 `RUSTFLAGS=--remap-path-prefix`,在 CI 里加一个 `reproducibility-check` job,build 同一个 commit 两次,`cmp` 两个二进制。如果第一次跑发现不可复现,diff 二进制(`xxd target/release/hh > a.hex; xxd /tmp/hh-1 > b.hex; diff a.hex b.hex`),定位差异区域,追到具体是哪个 buildscript 引入了随机性。这个练习会让你第一次直面"现代构建系统里有多少隐式输入",理解为什么可复现构建是个工程难题。

**练习四(难度 4),设计题。** 假设你的 HH 项目要在六个月内长到一个 AAA-scale 团队(20 人,代码 50 万行,资产 200GB)。设计一个完整的构建工程方案:用什么管源码(Git + workspace,假设)、什么管资产(Perforce? Plastic? 自建管线?给出选择理由)、CI 怎么横向扩展(单 runner 跑不下了,要不要 self-hosted runner pool?)、release 怎么 ship(Steam? 自有 launcher?)、可复现构建要不要严格做(为什么或为什么不)。把方案写下来,不写代码——这一题考的是你能不能把这一篇的概念综合成一个真实场景下的工程决策。

## 9 · 延伸阅读与下一篇

构建工程是一个相对小众但极其值钱的领域,值得读的资料集中在几个地方。**Reproducible Builds 项目**(reproducible-builds.org)是这方面的全球协作组织,它的文档把可复现构建的所有敌人、所有对策都讲透了,Firefox / Tor / Debian / NixOS 都遵循它的标准。**The Cargo Book** 关于 workspace、profiles、build script 的章节,是你做 Rust 项目构建工程的权威参考,特别是 `[profile.*]` 那一段——你今天只学了 `codegen-units` 和 `incremental`,还有 `lto`、`panic`、`strip` 等十几个旋钮,每一个都影响二进制的体积、性能、可调试性。**Matklad 的博客**(matklad.github.io)有大量关于 Rust 工程实践的文章,他是 rust-analyzer 的作者,文章质量极高,尤其推荐"Why Your Builds Are Slow"和"Building Rust Apps for Multiple Platforms"。**Casey Muratori 自己的 HH 后期 day**(day 500+ 里他确实尝试过做 release build)里有一些关于"为什么 HH 这种单文件 build 模式无法 scale"的反面教材——你看他痛苦地手动拷贝 DLL、手动 build,就更能体会 CI 的价值。

Git LFS 的官方文档和 GitHub 的 LFS 计费文档都值得过一遍,因为 LFS 的带宽和存储额度是真实工程约束,你需要心里有数。如果将来你要上 Perforce / Plastic SCM,它们的官方文档各自有完整教程——这两个系统是 AAA 工业级资产管线的标准,你以后做大项目大概率会遇到。

写到这里,9F 序列的第一篇就收口了。这一篇把 [phase-0/17](../phase-0/17-ci-cd.md) 的 CI/CD 基础,推到了**游戏项目特有**的工程高度:跨平台 build matrix 让你不再"在我机器上能跑"地盲发、9A 测试网在 CI 里持续运行、资产验证把低级错误拦在 main 之外、可下载构建让团队所有人都能拿到"今天的游戏";交叉编译让你从 Linux 主力开发也能 ship 出 Windows 二进制;可复现构建让你 ship 的二进制是可审计、可追溯、可信任的;workspace 把你的引擎从单 crate 拆成有清晰层边界的多 crate 结构,既加速 CI 又强制好架构;Git LFS 让你的仓库不被资产撑爆。这些能力的共同名字,叫**构建工程**——一个被低估、却决定 indie 项目能不能发版的工程领域。

下一篇 [09F-2](09F-2-release-engineering-and-live-ops.md) 离开"构建",进入"发布(release)"——讲怎么把一个可复现 build 出的二进制,真正送到玩家手上:版本管理(semantic versioning、CHANGELOG、release notes)、自动发版管线(cargo-dist、GitHub Releases)、平台特定的 packaging(Steam、itch.io、Homebrew、AUR)、签名与公证(Windows 的 code signing、macOS 的 notarization——这是 Mac 发版的硬门槛)、以及一些独立的现实:当你有玩家付费,你必须严肃对待"发出去的二进制能跑、能装、不会被杀毒误报"。这一篇是你"能 build 出二进制",下一篇是你"能让玩家拿到并跑起这个二进制"——前者是技术,后者是工程交付,缺一不可。
