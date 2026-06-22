---
phase: 0
title_en: "Rust Toolchain Deep Dive"
title_zh: "Rust 工具链深度专题"
type: article
domains: [rust, linux, tooling]
---

# Rust 工具链深度专题

> 你写 Rust 半年了。`cargo build` / `cargo run` / `cargo test` 这三件套用得熟练。然后你看到一个开源项目(bevy / ripgrep)的 README,里面写"run `cargo nextest run`"——你照跑,`error: no such command: nextest`。你装上它,跑一遍,发现你的 50 个测试从 5 秒变成 1 秒。你又看到 README 写"check `cargo deny check`",你装上 cargo-deny,跑一遍,它告诉你某个 dependency 有 CVE。你这才意识到:**Rust 标准工具链之外,有整整一个生态的"必装"工具**。今天这一篇把这套工具链一次说透——读完你会用 12 个 cargo 子命令,知道每个解决什么问题。

## 0 · 为什么要有这一篇

Phase 0 的 day 9 我们讲过基础工具链(rustc / cargo / rustup / rust-analyzer)。那一篇覆盖了"能写 Rust"的最小集。今天这一篇往前走一步:**工业级 Rust 开发**的工具链。

工业级和"能写"的差距:

- **能写**:`cargo build` 跑通。
- **工业级**:
  - 测试快(cargo-nextest)
  - 安全(cargo-audit / cargo-deny)
  - 体积小(cargo-bloat / twiggy)
  - 无冗余(cargo-machete / cargo-udeps)
  - 跨平台(cross)
  - 验证无 UB(miri)
  - 一致环境(rust-toolchain.toml)

每个工具解决工业开发的一个具体痛点。 Casey 在 Handmade Hero 里没用 Rust(他用 C),但你在 Rust 生态里写代码,这套工具链是必备。

**这一篇要覆盖**:

1. `sccache` — 编译缓存(跨项目重用编译结果)
2. `cargo nextest` — 下一代测试运行器(并行 / 重试 / TAP)
3. `cargo deny` / `cargo audit` — 依赖安全 / license 检查
4. `cargo bloat` / `twiggy` — 二进制体积分析
5. `cargo machete` / `cargo udeps` — 找未使用的依赖
6. `cargo doc` + `cargo docset` — 文档生成
7. `rust-objcopy` / `strip` — 二进制裁剪
8. `miri` — undefined behavior 检测器
9. `cargo profiler` — 性能 profile 入口
10. `cross` — 跨平台编译(Docker)
11. `rust-toolchain.toml` — 项目锁定 toolchain 版本
12. `components add` — 给 toolchain 加 component
13. 自定义 runner(`cargo-run-bin`)

**学完这一篇,你应该能**:
- 给团队设计一套 CI/CD,涵盖所有这些工具
- 知道每个工具适合什么场景(避免"全部用")
- 自己造一个 cargo 子命令(cargo 插件机制)

## 1 · sccache:编译缓存

### 1.1 问题

Rust 编译慢——这是 Rust 最出名的"缺点"。一个中型项目(50K 行)clean build 30 秒-1 分钟是常态。如果你同时维护 5 个 Rust 项目,每个 clean build 是浪费——尤其是这些项目共享 `serde` / `tokio` / `reqwest` 这种大依赖。

### 1.2 sccache 是什么

**sccache**(Shared Compilation Cache)是 Mozilla 开发的编译缓存。它拦截 `rustc` 调用,缓存编译结果。下次编译同一个 crate(相同源码 + 相同 flag)直接从缓存拿。

sccache 和 ccache(C/C++)的思路一样,但扩展到 Rust / C / C++ / CUDA。它支持本地缓存和**分布式缓存**(S3 / Redis)。

### 1.3 安装和启用

```bash
# 安装
sudo pacman -S sccache    # Arch
# 或
cargo install sccache

# 启用:设置 RUSTC_WRAPPER 环境变量
export RUSTC_WRAPPER=sccache
# 加到 ~/.zshrc / ~/.bashrc 让它持久

# 看缓存状态
sccache --show-stats

# 清空缓存
sccache --wipe
```

启用后,**clean build 速度提升 2-5 倍**(取决于共享依赖)。第一次编译 populate 缓存,第二次起命中。

### 1.4 跨项目共享

sccache 的关键价值:**跨项目共享编译结果**。你在项目 A 编译过 `serde 1.0.197`,在项目 B 引入同一个版本,sccache 直接给缓存的结果——秒级。

这意味着你的**第一个项目 clean build** 后,**后续所有项目**的依赖编译都极快。

### 1.5 何时不用

- **第一次 build**:sccache 是缓存,第一次没东西可缓存。
- **修改了 build flag**:`--cfg debug` 之类的 flag 改变会导致 cache miss。
- **nightly Rust**:nightly 版本变就 invalidate 整个 cache。
- **超大型项目(单 crate 编译 30s+)**:单 crate 编译开销 vs cache lookup,cache lookup 可能不抵。

### 1.6 工业实践

- **Mozilla Firefox**:全公司用 sccache + S3 分布式缓存,CI 节省几小时。
- **Bevy 引擎**:开发者文档建议装 sccache。
- **Google / Meta**:内部有类似的分布式编译系统。

CI 集成示例(GitHub Actions):

```yaml
- name: Install sccache
  uses: mozilla-actions/sccache-action@v0.0.4

- name: Configure sccache
  run: echo "RUSTC_WRAPPER=sccache" >> $GITHUB_ENV

- name: Cache sccache
  uses: actions/cache@v4
  with:
    path: ~/.cache/sccache
    key: sccache-${{ runner.os }}-${{ hashFiles('Cargo.lock') }}
```

## 2 · cargo nextest:下一代测试运行器

### 2.1 问题

`cargo test` 是 Rust 默认测试运行器。它能跑,但有几个问题:

1. **串行执行**:测试默认在同一个进程跑,虽然 cargo 内部有并行,但每次测试启动慢。
2. **没有重试机制**:flakey 测试(网络 / 时间相关)失败就失败。
3. **没有 TAP / JUnit 输出**:CI 集成弱。
4. **报告粗糙**:测试失败显示不直观。

### 2.2 cargo nextest

`cargo nextest` 是 Mozilla 开发的下一代测试运行器。它的特点:

- **每测试一个进程**:测试隔离,一个 panic 不影响其他。
- **更激进的并行**:默认按 CPU 数并行。
- **重试机制**:`--retries 3` 自动重试 flakey 测试。
- **JUnit XML 输出**:`--junit target/test.xml`,CI 直接消费。
- **更友好的 UI**:颜色 / 进度条 / 失败高亮。

### 2.3 安装和使用

```bash
# 安装
cargo install cargo-nextest --locked

# 跑所有测试
cargo nextest run

# 跑特定测试
cargo nextest run -p my-crate --test integration

# 跑并重试 3 次 flakey
cargo nextest run --retries 3

# 生成 JUnit 报告
cargo nextest run --junit target/nextest.xml

# 只跑之前失败的测试
cargo nextest run --failed

# 看 cargo test 的输出风格(保留兼容)
cargo nextest run --no-capture
```

### 2.4 实测加速

50 个测试(包含 5 个 integration test):

```
cargo test:           8.3s
cargo nextest run:    2.1s   (4x 加速)
```

加速来自:**进程级并行** + **更少的 setup overhead**。

### 2.5 配置文件

`.config/nextest.toml`:

```toml
[profile.default]
retries = 0
failure-output = "final"
fail-fast = false

[profile.ci]
retries = 2
failure-output = "immediate"
junit = { path = "junit.xml" }

[profile.ci.junit]
path = "junit.xml"
```

```bash
cargo nextest run --profile ci
```

工业级 CI 用 nextest 配 profile,统一团队行为。

## 3 · cargo deny / cargo audit:安全检查

### 3.1 问题

Rust 项目依赖几百个 crate,任何一个有 CVE(安全漏洞)都会影响你的项目。**手动查每个依赖的 CVE 不现实**。需要自动化工具。

### 3.2 cargo audit

`cargo audit` 检查 `Cargo.lock` 里的每个 crate 是否在 [RustSec Advisory Database](https://github.com/rustsec/advisory-db) 有记录。

```bash
cargo install cargo-audit

cargo audit
# 输出类似:
# Crate:    openssl
# Version:  0.10.40
# Title:    openssl XXE vulnerability
# Date:     2024-01-15
# ID:       RUSTSEC-2024-0001
# Solution: upgrade to >= 0.10.41
```

### 3.3 cargo deny

`cargo deny` 是更全面的检查器——除了 CVE 还检查:

- **License**:确保所有依赖的 license 兼容(比如不混 GPL 和 proprietary)。
- **Banned crates**:你 black list 某些 crate(比如禁止 `time` 老 version)。
- **Duplicate dependencies**:同 crate 多版本(版本碎片化)。
- **Source**:依赖来自 crates.io 还是 git。

```bash
cargo install cargo-deny
cargo deny init    # 生成 deny.toml
cargo deny check
```

`deny.toml` 示例:

```toml
[advisories]
db-urls = ["https://github.com/rustsec/advisory-db"]
vulnerability = "deny"
unmaintained = "warn"
yanked = "deny"

[licenses]
allow = ["MIT", "Apache-2.0", "BSD-3-Clause", "ISC"]
deny = ["GPL-3.0", "AGPL-3.0"]

[bans]
multiple-versions = "warn"
deny = [
    { name = "time", version = "<0.3" },
]

[sources]
unknown-registry = "deny"
unknown-git = "deny"
```

### 3.4 工业集成

CI 每次提交跑 `cargo deny check`。如果有 CVE / license 问题,build fail。这是工业级 Rust CI 的标配。

```yaml
# GitHub Actions
- name: cargo deny
  uses: EmbarkStudios/cargo-deny-action@v1
  with:
    command: check all
```

## 4 · cargo bloat / twiggy:体积分析

### 4.1 问题

Rust 默认 release binary 不算特别小。一个简单的 web server 可能 5-10 MB。要找到"什么占了体积",需要工具。

### 4.2 cargo bloat

```bash
cargo install cargo-bloat

# 看每个函数占多少
cargo bloat --release -n 20

# 看每个 crate 占多少
cargo bloat --release --crates -n 20

# 看每个函数 + 反汇编
cargo bloat --release --time -n 20
```

输出:

```
File  .text    Size         Crate
8.4%  17.8%  33.8KiB        serde
6.0%  12.8%  24.2KiB        ???
4.2%   8.9%  16.8KiB        std
3.8%   8.1%  15.3KiB        tokio
...
```

`???` 表示函数来自 std / 编译器生成的代码。

### 4.3 twiggy

`twiggy` 是 RustWASM 团队的体积分析工具,支持 wasm / ELF / Mach-O。

```bash
cargo install twiggy

# 看一个 wasm 的 top 函数
twiggy top target/wasm32-unknown-unknown/release/my_game.wasm -n 20

# 看 dead code
twiggy dead_code target/release/my_game

# 看 dominator tree(谁占了最大代码段)
twiggy dominators target/release/my_game
```

### 4.4 工业用法

- **嵌入系统**:把 binary 砍到 < 1 MB。
- **WebAssembly**:wasm 越小加载越快。
- **Server**:不太关心体积,但 bloat 报告能发现"为什么我引入了 X crate"。

## 5 · cargo machete / cargo udeps:未使用依赖

### 5.1 问题

项目演化几个月后,`Cargo.toml` 里堆积一堆 deps,有些已经不用了。手动检查要打开每个 .rs 文件搜 `use`,不现实。

### 5.2 cargo machete

最快的 unused dep 检查器。它不解析 Rust 语法,只搜文本——快但偶尔误报。

```bash
cargo install cargo-machete
cargo machete
# 输出:
# Unused dependencies:
#   my-crate: chrono, regex
```

### 5.3 cargo udeps

更准确的工具,基于 rust-analyzer 的语法分析。但需要 nightly。

```bash
cargo +nightly install cargo-udeps
cargo +nightly udeps
```

### 5.4 工业实践

CI 偶尔(每周)跑一次 `cargo machete`,把报告发到团队聊天。开发者主动清理。这避免"Cargo.toml 无限膨胀"。

## 6 · cargo doc / cargo docset:文档

### 6.1 cargo doc

```bash
cargo doc              # 生成项目文档
cargo doc --open       # 生成并打开浏览器
cargo doc --no-deps    # 不生成依赖文档(快)
cargo doc --document-private-items  # 包括私有
```

文档输出到 `target/doc/`,入口 `target/doc/<crate_name>/index.html`。

### 6.2 写好 doc comment

```rust
/// Adds two numbers.
///
/// # Examples
///
/// ```
/// let result = my_crate::add(2, 3);
/// assert_eq!(result, 5);
/// ```
pub fn add(a: i32, b: i32) -> i32 {
    a + b
}
```

`///` 是 doc comment。cargo doc 会渲染成 HTML,**包括代码示例**(代码示例会被 cargo test 跑——叫 "doctest")。

### 6.3 cargo docset

`cargo docset` 把 cargo doc 输出转成 **Dash / Zeal 兼容的 docset**——离线文档浏览器。

```bash
cargo install cargo-docset
cargo docset
# 生成 my_crate.docset,可以用 Zeal / Dash 浏览
```

Zeal 是开源跨平台的离线文档浏览器,Linux 友好。

```bash
sudo pacman -S zeal
```

## 7 · rust-objcopy / strip:二进制裁剪

### 7.1 问题

Release binary 含**符号表**(symbol table)和**调试信息**(DWARF)——这些占了 binary 50-90% 的体积!发行版不需要这些。

### 7.2 strip

```bash
strip target/release/my_app
# 移除所有 symbol 和 debug info
# binary 可能从 10MB 变成 1MB

strip -d target/release/my_app
# 只移除 debug info(保留 symbol)

strip -s target/release/my_app
# 同上(显式)
```

### 7.3 Rust 内置 strip

`Cargo.toml`:

```toml
[profile.release]
strip = true          # 等价 strip
strip = "symbols"     # 只 strip symbols
strip = "debuginfo"   # 只 strip debug info
```

启用后 cargo build --release 自动 strip。

### 7.4 objcopy

`objcopy` 可以做更细的 binary 操作:改架构、改格式、提取 section。

```bash
# 提取 binary 的某个 section
objcopy --dump-section .rodata=my_data.bin target/release/my_app

# 转 ELF 到 raw binary(无 ELF header,直接是机器码)
objcopy -O binary target/release/my_app my_app.bin

# 嵌入式系统常用
```

Rust 嵌入式开发(STM32 / ESP32)用 objcopy 把 ELF 转 .bin / .hex 烧录。

## 8 · miri:UB 检测

### 8.1 问题

Rust 标榜"memory safe",但 `unsafe` 代码可能引入 undefined behavior(UB)。UB 极难调试——它可能在你不知情下损坏内存,bug 表现和 root cause 完全无关。

### 8.2 miri

`miri` 是 Rust 的 MIR 解释器,检测 UB。它**不生成机器码**——直接解释 MIR,运行时检查每种 UB。

```bash
# 安装 nightly 和 miri component
rustup toolchain install nightly
rustup +nightly component add miri

# 设置(第一次跑会装一些依赖)
cargo +nightly miri setup

# 跑测试
cargo +nightly miri test
```

miri 能检测:
- **未初始化内存读取**
- **数据竞争**(data race)
- **越界访问**(array out of bounds,在 unsafe 里)
- **无效指针**(dangling pointer dereference)
- **违反 aliasing 规则**(&mut 真的独占)
- **integer overflow**(signed)
- **无效 uninitialized bytes**

### 8.3 用例

```rust
#[cfg(test)]
mod tests {
    #[test]
    fn test_unsafe() {
        let mut x = 0u32;
        let p = &mut x as *mut u32;
        unsafe {
            *p = 42;
        }
        assert_eq!(x, 42);
    }
}
```

跑 `cargo +nightly miri test`,miri 解释执行,如果有 UB 会立即报错并指出位置。

### 8.4 miri 的局限

- **慢**:10-100x 慢于 native。不能跑大型测试。
- **不支持 FFI**:不能跑调用 C 的代码。
- **不支持某些 std feature**(线程池 / async 复杂场景有限)。

工业用法:**单独 CI job** 跑 miri on 一部分核心 unsafe 测试。

## 9 · cargo profiler:性能入口

### 9.1 是什么

`cargo profiler` 是个 wrapper,把 `perf` / `valgrind` / `gprof` 等工具包装成 cargo 子命令。

```bash
cargo install cargo-profiler

# 用 perf 跑
cargo profiler perf --bin my_app

# 用 callgrind(valgrind)
cargo profiler callgrind --bin my_app

# 输出 hot path 报告
```

### 9.2 Linux 用 perf

更直接:

```bash
# Arch
sudo pacman -S perf

# 跑
perf record -- ./target/release/my_app
perf report
```

perf 是 Linux 内核级 profiler,采样 CPU 性能计数器。比 valgrind 快(开销小)。

### 9.3 工业级:Tracy / Superluminal

游戏 / 图形用专门的 profiler:

- **Tracy**:开源,GPU + CPU,实时 flamegraph。
- **Superluminal**:商业,Windows 强。
- **puffin**:Rust 嵌入式 profiler。

```toml
# Cargo.toml
[dependencies]
puffin = "0.19"
puffin_egui = "0.29"
```

```rust
fn frame() {
    puffin::profile_function!();
    // ...
}
```

## 10 · cross:跨平台编译

### 10.1 问题

要在 ARM Linux(x86_64 → aarch64)上跑你的 Rust binary,需要交叉编译。手动配置交叉编译链很痛苦——要装 cross-binutils、cross-gcc、target sysroot。

### 10.2 cross

`cross` 用 Docker 容器封装所有 cross 工具链。你装 Docker,然后 `cross build`——它自动拉镜像、配置环境、跑 cargo。

```bash
cargo install cross --git https://github.com/cross-rs/cross

# 装 Docker
sudo pacman -S docker
sudo systemctl start docker
sudo usermod -aG docker $USER
# 重新登录让组生效

# 交叉编译到 ARM 64
cross build --target aarch64-unknown-linux-gnu

# 跑 ARM 测试(用 qemu)
cross test --target aarch64-unknown-linux-gnu

# 交叉编译到 Android
cross build --target aarch64-linux-android

# 编译到 MIPS(路由器)
cross build --target mips-unknown-linux-gnu
```

`cross` 支持 50+ target,每个都有预建 Docker 镜像。

### 10.3 自己的镜像

如果你的 target 不在 cross 默认支持列表,可以提供自己的 `Cross.toml`:

```toml
[target.my-custom-target]
image = "my-registry/my-custom-image:latest"
```

## 11 · rust-toolchain.toml:锁定 toolchain

### 11.1 问题

每个 Rust 项目可能要求不同的 toolchain——稳定项目用 stable,实验性用 nightly,生产用 1.75。团队成员不同 toolchain 会导致 build 不一致。

### 11.2 rust-toolchain.toml

项目根目录放 `rust-toolchain.toml`:

```toml
[toolchain]
channel = "1.75.0"
components = ["rustfmt", "clippy", "rust-src"]
targets = ["wasm32-unknown-unknown"]
profile = "default"
```

任何人进入这个目录跑 `cargo build`,rustup 自动切到 1.75.0,装上 rustfmt / clippy / wasm32 target。

### 11.3 用法

- `channel = "stable"` / `"nightly"` / `"1.75.0"` / `"beta"`
- `components`:额外 component(clippy / rustfmt / miri / rust-src)
- `targets`:cross compile 目标
- `profile = "minimal"` 只装 rustc + cargo;`"default"` 加 rustfmt + clippy;`"complete"` 全部(不推荐)

### 11.4 文件名约定

- `rust-toolchain`(无扩展名,纯文本,只含 channel 名)——老式
- `rust-toolchain.toml`(TOML 格式)——推荐

工业项目必备。**任何严肃的 Rust 项目根目录都该有这个文件**。

## 12 · components add:扩展 toolchain

### 12.1 是什么

rustup 装 Rust 时默认装 rustc + cargo。但还有更多 component 可以加:

```bash
# 列出所有可用 component
rustup component list

# 装 clippy
rustup component add clippy

# 装 rustfmt
rustup component add rustfmt

# 装 rust-src(Rust source code,rust-analyzer 需要)
rustup component add rust-src

# 装 miri(UB 检测)
rustup component add miri

# 装 rust-analyzer(LSP)
rustup component add rust-analyzer

# 装 analysis(Rust compiler 内部数据)
rustup component add rustc-codegen-cranelift  # 实验,CRanelift backend

# 装 llvm-tools(objdump 等 LLVM 工具)
rustup component add llvm-tools-preview
```

### 12.2 给特定 toolchain 加

```bash
rustup component add --toolchain nightly clippy
rustup component add --toolchain 1.75.0 rustfmt
```

## 13 · 自定义 runner:cargo-run-bin

### 13.1 问题

CI 里要跑某个 binary,但本地有不同 binary 版本。需要版本锁定。

### 13.2 cargo-run-bin

```bash
cargo install cargo-run-bin

# 在项目里跑某个工具
cargo bin --version=1.0.0 -- some-tool arg1 arg2
```

`cargo bin` 会从 crates.io 拉指定版本的工具,缓存,然后跑。这相当于 Python 的 `pipx run`、Node 的 `npx`。

工业用法:CI 里 `cargo bin mdbook build` 而不要求预装 mdbook。

### 13.3 自定义 cargo 子命令

cargo 自动识别 `cargo-XXX` 的可执行文件为子命令 `cargo XXX`。你可以自己写:

```bash
mkdir -p ~/.cargo/bin
cat > ~/.cargo/bin/cargo-hello <<'EOF'
#!/bin/sh
echo "Hello from custom cargo command!"
EOF
chmod +x ~/.cargo/bin/cargo-hello
cargo hello
# 输出: Hello from custom cargo command!
```

这就是 cargo 插件机制。`cargo-nextest` / `cargo-deny` / `cargo-bloat` 都是这种——可执行文件名前缀 `cargo-` 即被 cargo 识别。

## 14 · 全套工具的 CI 整合

```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
        with:
          components: clippy, rustfmt
      - uses: mozilla-actions/sccache-action@v0.0.4
      - run: echo "RUSTC_WRAPPER=sccache" >> $GITHUB_ENV

      # 格式
      - run: cargo fmt --all -- --check

      # Clippy
      - run: cargo clippy -- -D warnings

      # 测试(nextest)
      - uses: taiki-e/install-action@nextest
      - run: cargo nextest run --profile ci

      # 安全检查
      - uses: EmbarkStudios/cargo-deny-action@v1
        with:
          command: check advisories licenses

      # 体积
      - uses: taiki-e/install-action@cargo-bloat
      - run: cargo bloat --release --crates -n 20

      # 未使用依赖
      - uses: taiki-e/install-action@cargo-machete
      - run: cargo machete
```

这就是工业级 Rust CI 模板。每个 step 防一类问题。

## 15 · 工具选择决策树

```
项目刚开始:
  → rustup + cargo + rust-analyzer + rustfmt + clippy

项目稳定:
  → + sccache(加速编译)
  → + cargo nextest(测试)
  → + cargo deny(安全)

发布前:
  → + cargo bloat(体积)
  → + cargo machete(冗余)
  → + strip(裁剪)

需要 unsafe:
  → + miri(UB 检测)

跨平台:
  → + cross
  → + rust-toolchain.toml(锁版本)
```

不是每个项目都要用全部工具。**按需选用**——这就是工程师的判断。

## 16 · 延伸阅读

- Rust 工具链总览:https://rust-lang.org/tools
- cargo book:https://doc.rust-lang.org/cargo/
- sccache:https://github.com/mozilla/sccache
- cargo-nextest:https://nexte.st/
- cargo-deny:https://github.com/EmbarkStudios/cargo-deny
- cargo-bloat:https://github.com/RazrFalcon/cargo-bloat
- twiggy:https://github.com/rustwasm/twiggy
- cargo-machete:https://github.com/bnjbvr/cargo-machete
- cargo-udeps:https://github.com/est31/cargo-udeps
- miri:https://github.com/rust-lang/miri
- cross:https://github.com/cross-rs/cross
- rust-toolchain 文档:https://rust-lang.github.io/rustup/overrides.html#the-toolchain-file
- ripgrep 的 CI(参考):https://github.com/BurntSushi/ripgrep/blob/master/.github/workflows/ci.yml
- nushell 的 CI:https://github.com/nushell/nushell/blob/main/.github/workflows/ci.yml
- Bevy 贡献指南(讲 toolchain):https://github.com/bevyengine/bevy/blob/main/CONTRIBUTING.md
