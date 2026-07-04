
# Rust 项目持续集成与持续交付

> 你写完一个 Rust CLI 工具,推到 GitHub。你的朋友 clone 后 `cargo build`——失败。你远程 debug 半小时,发现他缺某个 system library。然后你想发预编译 binary 给 Mac 用户、Windows 用户、Linux 用户——你打开三个虚拟机,各自 build。第三周你不想维护了——已经有 5 个 release 因为没及时更新过期了。你心想:**这就是为什么大项目都有 CI/CD**。今天这一篇把 Rust 项目的 CI/CD 全套说透——从 GitHub Actions 基础,到 cargo-dist 自动发布,到 AUR / Snap / Flatpak 打包,再到 WASM + GitHub Pages 部署。

## 0 · 为什么要有这一篇

CI/CD 是工业开发的核心实践。Phase 0 的 day 12 我们讲过开源 PR flow,那一篇涉及 GitHub PR 的基本流程。今天这一篇往前一步:**自动化**——让机器替你跑测试、检查代码、发布版本。

CI(Continuous Integration,持续集成):每次 push / PR 自动跑测试、lint、build。早发现问题。

CD(Continuous Delivery / Deployment,持续交付 / 部署):自动打包、发版、部署。

**为什么 Rust 开发者必须懂 CI/CD**:

1. **跨平台验证**:Rust 跨平台,但每个平台有 quirk。CI 在 Linux / macOS / Windows 同时跑测试,确保兼容。
2. **依赖审计**:Rust 项目依赖多,CI 跑 cargo audit / deny 自动查 CVE。
3. **自动发布**:cargo-dist / cargo-release 让发版从"半天手工"变"按一下按钮"。
4. **分发**:为不同平台预编译 binary,Linux (AUR / Snap / Flatpak)、macOS (Homebrew)、Windows (Scoop)。

**这一篇要覆盖**:

1. GitHub Actions for Rust(build matrix、caching、audit、lint)
2. GitLab CI(替代方案)
3. Self-hosted runner(自建 runner,适合 ARM / GPU)
4. Release pipeline:cargo-dist / cargo-release
5. Binary distribution:GitHub Releases / AUR / Snap / Flatpak / Homebrew
6. Container builds(Docker)
7. WASM build + GitHub Pages deploy
8. Code coverage:tarpaulin / llvm-cov
9. Lint in CI:clippy + rustfmt
10. Dependabot / Renovate(依赖更新)
11. 真实开源项目 CI 配置剖析(bevy / ripgrep / nushell)

**学完这一篇,你应该能**:
- 给任何 Rust 项目设计 CI/CD pipeline
- 选择合适的工具(GitHub Actions vs GitLab CI vs 自建)
- 用 cargo-dist 自动发版到 crates.io + GitHub Releases
- 把 WASM 项目部署到 GitHub Pages
- 跑测试覆盖率并发到 coveralls / codecov

## 1 · CI 基础概念

### 1.1 CI 是什么

CI = Continuous Integration(持续集成)。核心思想:**每个开发者把代码频繁 merge 到 main 分支,每次 merge 自动跑测试**。

传统开发:开发者在自己分支工作几周,最后 merge。merge 时一堆冲突,bug 集中爆发。CI 改成:**每次 push 都跑测试**,bug 早期发现。

### 1.2 CI runner

CI 跑在 **runner**(执行机器)上。两种 runner:

- **SaaS runner**:GitHub Actions 提供 Linux / macOS / Windows 免费 runner(2-core,7 GB RAM)。够用。
- **Self-hosted runner**:你自己提供机器。适合:ARM 编译、GPU 任务、安全敏感项目、超大 build。

### 1.3 CI 的代价

CI 不是免费:

- **运行时间**:GitHub Actions 免费额度 2000 分钟/月(公开仓库无限)。超了要付费。
- **维护**:CI 配置文件复杂,bug 时调试麻烦。
- **依赖外部服务**:GitHub Actions 挂了你的 CI 也挂。

工业实践:**CI 是非可选的**——没有 CI 的项目等同于没测试。

## 2 · GitHub Actions for Rust

### 2.1 最小可用 workflow

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install Rust
        uses: dtolnay/rust-toolchain@stable

      - name: Build
        run: cargo build --verbose

      - name: Test
        run: cargo test --verbose
```

解释:

- `on: push / pull_request`:每次 push 到 main 或开 PR 时触发。
- `runs-on: ubuntu-latest`:在最新 Ubuntu runner 跑。
- `dtolnay/rust-toolchain@stable`:用 David Tolnay(知名 Rust 工程师)维护的 action 装 stable Rust。比手动 `rustup install` 简单。
- `cargo build`:验证能编译。
- `cargo test`:跑测试。

提交这个文件后,GitHub 自动跑。你在仓库 "Actions" tab 看输出。

### 2.2 Build matrix:跨平台

```yaml
jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
        rust: [stable, beta, nightly]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@master
        with:
          toolchain: ${{ matrix.rust }}
      - run: cargo build
      - run: cargo test
```

这会跑 9 个 job(3 OS × 3 Rust version)。每次 push 都跑 9 个 build,确保跨平台兼容 + 跨 Rust 版本兼容。

`fail-fast: false`:一个 job 失败不取消其他 job,让你一次看到所有失败。

### 2.3 缓存:加速 build

每个 job 从头装 Rust + cargo build 慢。用 `Swatinem/rust-cache` 缓存:

```yaml
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
      - uses: Swatinem/rust-cache@v2
      - run: cargo build
```

第一次 build 慢,后续命中缓存快 3-10 倍。`rust-cache` 自动判断 Cargo.lock 是否变化,变化则 invalidate。

### 2.4 Lint:rustfmt + clippy

```yaml
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
        with:
          components: rustfmt, clippy
      - name: Format check
        run: cargo fmt --all -- --check
      - name: Clippy
        run: cargo clippy --all-targets --all-features -- -D warnings
```

`--check` 让 cargo fmt 不修改文件,只检查是否格式正确。如果文件没格式化,返回非零(失败)。

`-D warnings` 让 clippy 把所有 warning 当 error。这是工业标配——零 warning tolerance。

### 2.5 Audit:安全检查

```yaml
  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: rustsec/audit-check@v2.0.0
        with:
          token: ${{ secrets.GITHUB_TOKEN }}
```

或用 cargo-deny action:

```yaml
      - uses: EmbarkStudios/cargo-deny-action@v1
        with:
          command: check advisories licenses bans sources
```

每次 push 自动检查 Cargo.lock 是否有 CVE 或 license 问题。

### 2.6 Coverage

```yaml
  coverage:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
        with:
          components: llvm-tools-preview
      - uses: taiki-e/install-action@cargo-llvm-cov
      - run: cargo llvm-cov --lcov --output-path lcov.info
      - uses: codecov/codecov-action@v4
        with:
          files: lcov.info
          token: ${{ secrets.CODECOV_TOKEN }}
```

`cargo-llvm-cov` 用 LLVM 工具生成覆盖率报告(比 tarpaulin 快)。上传到 codecov.io,在 PR 显示覆盖率变化。

### 2.7 完整 CI 模板

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

env:
  CARGO_TERM_COLOR: always
  RUST_BACKTRACE: 1

jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
        rust: [stable, beta]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@master
        with:
          toolchain: ${{ matrix.rust }}
      - uses: Swatinem/rust-cache@v2
      - run: cargo build --all-targets
      - run: cargo test --all-targets

  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
        with:
          components: rustfmt, clippy
      - run: cargo fmt --all -- --check
      - run: cargo clippy --all-targets --all-features -- -D warnings

  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: EmbarkStudios/cargo-deny-action@v1

  coverage:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
        with:
          components: llvm-tools-preview
      - uses: taiki-e/install-action@cargo-llvm-cov
      - run: cargo llvm-cov --lcov --output-path lcov.info
      - uses: codecov/codecov-action@v4
```

这是工业级 Rust CI 模板。提交到任何 Rust 项目,通用。

## 3 · GitLab CI

### 3.1 差异

GitLab CI 类似 GitHub Actions,但语法和概念略不同:

- **GitHub Actions**:workflow 文件在 `.github/workflows/`,用 YAML。
- **GitLab CI**:配置文件 `.gitlab-ci.yml`,用 YAML。

GitLab CI 自带 Docker runner——每个 job 在独立 Docker 容器跑。

### 3.2 示例

```yaml
# .gitlab-ci.yml
stages:
  - test
  - build
  - deploy

variables:
  CARGO_HOME: $CI_PROJECT_DIR/.cargo

test:
  stage: test
  image: rust:latest
  cache:
    paths:
      - .cargo
      - target/
  script:
    - cargo test --all-targets

lint:
  stage: test
  image: rust:latest
  script:
    - rustup component add rustfmt clippy
    - cargo fmt --all -- --check
    - cargo clippy -- -D warnings

build:linux:
  stage: build
  image: rust:latest
  script:
    - cargo build --release
    - cp target/release/my_app my_app-linux
  artifacts:
    paths:
      - my_app-linux
```

### 3.3 GitLab vs GitHub Actions

| 特性 | GitHub Actions | GitLab CI |
|---|---|---|
| 集成 | GitHub 仓库原生 | GitLab 仓库原生 |
| 免费 runner | 有(Linux / macOS / Windows) | 有(限制更多) |
| 私有仓库 | 公开无限,私有有限 | 私有也有限 |
| 内置 Docker | 不内置 | 内置 |
| Marketplace | 大量第三方 action | 较少 |
| 注册门槛 | 低 | 中(企业多用) |

工业选型:开源项目选 GitHub,企业内部选 GitLab(因为 GitLab 自托管友好)。

## 4 · Self-hosted Runner

### 4.1 何时需要

SaaS runner 不能满足时:

- **ARM 编译**:GitHub 没 ARM Linux runner(有 ARM macOS)。要测 ARM Linux 用自建。
- **GPU 任务**:训练 / 推理 ML 模型,要 GPU。
- **超大 build**:Rust 编译需要 32 GB+ 内存,免费 runner 只有 7 GB。
- **安全**:代码不能出公司网络。
- **私有依赖**:依赖私有 crate registry,自建网络配置方便。

### 4.2 GitHub self-hosted runner

```bash
# GitHub repo → Settings → Actions → Runners → New self-hosted runner
# 按提示:

mkdir actions-runner && cd actions-runner
curl -o actions-runner-linux-x64-2.315.0.tar.gz -L \
    https://github.com/actions/runner/releases/download/v2.315.0/actions-runner-linux-x64-2.315.0.tar.gz
tar xzf actions-runner-linux-x64-2.315.0.tar.gz
./config.sh --url https://github.com/owner/repo --token TOKEN
./run.sh

# 注册成 systemd 服务
sudo ./svc.sh install
sudo ./svc.sh start
```

然后 workflow 里:

```yaml
jobs:
  build:
    runs-on: self-hosted
    steps:
      # ...
```

### 4.3 注意事项

- **安全**:self-hosted runner 不要执行 PR(可能跑恶意代码)。GitHub 默认 self-hosted runner 不跑公开仓库的 PR——别改这个设置。
- **资源隔离**:每个 job 在 `~/actions-runner/_work/` 下,完成后清理。但缓存会留——小心磁盘满。
- **多 runner**:大项目有多个 self-hosted runner,GitHub 自动负载均衡。

## 5 · Release Pipeline:cargo-dist / cargo-release

### 5.1 问题

发版涉及多步:

1. 更新 `Cargo.toml` 的 version
2. 更新 CHANGELOG
3. commit + tag + push
4. cargo publish(发 crates.io)
5. 构建 release binary
6. 上传到 GitHub Releases
7. 更新 Homebrew / AUR / Scoop 等

手动做容易出错——忘记某步,版本号错乱。

### 5.2 cargo-release

`cargo-release` 自动化前几步:

```bash
cargo install cargo-release

# 发版 0.2.0
cargo release 0.2.0

# 它会:
# 1. 检查 working tree 干净
# 2. cargo update
# 3. 改 Cargo.toml version 到 0.2.0
# 4. cargo publish --dry-run 验证
# 5. git commit "Release 0.2.0"
# 6. git tag 0.2.0
# 7. 实际发布(需要 --execute)
```

配置 `release.toml`:

```toml
[[pre-release-replacements]]
file = "CHANGELOG.md"
search = "Unreleased"
replace = "0.2.0 - {{date}}"

[sign-commit]
sign-tag = true
```

### 5.3 cargo-dist

`cargo-dist` 是 Axel Riese / Mistydewo 维护的更高级工具——**自动跨平台 build + 发布**。

```bash
cargo install cargo-dist --locked
cargo dist init    # 生成 config

# 配置 dist.toml
```

`dist.toml` 示例:

```toml
[dist]
cargo-dist-version = "0.13.0"
ci = ["github"]
installers = ["shell", "powershell", "homebrew"]
targets = [
    "x86_64-unknown-linux-gnu",
    "x86_64-apple-darwin",
    "aarch64-apple-darwin",
    "x86_64-pc-windows-msvc",
]
```

跑 `cargo dist plan`,它告诉你将 build 什么。跑 `cargo dist build`,实际构建。跑 `cargo dist publish`,发到 GitHub Releases + crates.io。

cargo-dist **自动生成 GitHub Actions workflow**:

```bash
cargo dist init
# 会创建 .github/workflows/dist.yml
```

提交后,**每次 push tag `v0.2.0`** 自动:

1. 在 4 个 OS build。
2. 打包 binary。
3. 创建 GitHub Release。
4. 生成 install.sh / install.ps1 / homebrew formula。

### 5.4 实例:ripgrep 发版

BurntSushi 维护 ripgrep。每次发版:

1. 改 Cargo.toml version。
2. 改 CHANGELOG。
3. commit + tag。
4. push tag。
5. cargo-dist workflow 自动 build + upload。

整个流程从几小时降到几分钟。工业级开源项目都用这套。

## 6 · Binary Distribution

发版后,要把 binary 送到用户手上。多平台分发:

### 6.1 GitHub Releases

最简单的分发。cargo-dist 自动建 GitHub Release,把每个 platform 的 binary 上传。

用户去 release 页下载对应平台的 tar.gz / zip。

### 6.2 Homebrew(macOS)

```bash
# 创建 homebrew tap 仓库:github.com/yourname/homebrew-tap

# Formula: my_app.rb
class MyApp < Formula
  desc "Your awesome app"
  homepage "https://github.com/yourname/my_app"
  url "https://github.com/yourname/my_app/archive/refs/tags/v0.2.0.tar.gz"
  sha256 "..."
  head "https://github.com/yourname/my_app.git", branch: "main"

  depends_on "rust" => :build

  def install
    system "cargo", "install", *std_cargo_args
  end

  test do
    assert_match "0.2.0", shell_output("#{bin}/my_app --version")
  end
end
```

用户安装:

```bash
brew tap yourname/tap
brew install my_app
```

cargo-dist 可以**自动生成并更新** formula。每次发版,它把 formula 推到 homebrew-tap 仓库。

### 6.3 AUR(Arch User Repository)

Arch Linux 用户用 AUR 装:

```bash
# PKGBUILD
pkgname=my-app
pkgver=0.2.0
pkgrel=1
pkgdesc="Your awesome app"
arch=('x86_64')
url="https://github.com/yourname/my_app"
license=('MIT')
depends=('gcc-libs')
makedepends=('cargo')
source=("$url/archive/v$pkgver.tar.gz")
sha256sums=('...')

build() {
    cd "$pkgname-$pkgver"
    cargo build --release --locked
}

package() {
    cd "$pkgname-$pkgver"
    install -Dm755 target/release/my_app "$pkgdir/usr/bin/my_app"
    install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
```

提交到 AUR 后,用户 `yay -S my-app-bin` 安装。

### 6.4 Snap(Ubuntu)

```yaml
# snapcraft.yaml
name: my-app
version: '0.2.0'
summary: Your awesome app
description: |
  Longer description.

grade: stable
confinement: strict

base: core22

apps:
  my-app:
    command: bin/my_app

parts:
  my-app:
    plugin: rust
    source: .
```

```bash
snapcraft          # 构建 .snap
snapcraft push my-app_0.2.0_amd64.snap
```

用户 `snap install my-app`。

### 6.5 Flatpak

```xml
<!-- org.example.MyApp.json -->
{
    "app-id": "org.example.MyApp",
    "runtime": "org.freedesktop.Platform",
    "runtime-version": "23.08",
    "sdk": "org.freedesktop.Sdk",
    "command": "my_app",
    "modules": [
        {
            "name": "my_app",
            "buildsystem": "simple",
            "build-commands": [
                "cargo build --release",
                "install -D target/release/my_app /app/bin/my_app"
            ],
            "sources": [
                {
                    "type": "archive",
                    "url": "https://github.com/yourname/my_app/archive/v0.2.0.tar.gz",
                    "sha256": "..."
                }
            ]
        }
    ]
}
```

```bash
flatpak-builder build-dir org.example.MyApp.json
flatpak build-bundle build-dir my-app.flatpak org.example.MyApp
```

用户 `flatpak install my-app.flatpak`。

### 6.6 决策:打哪些包

工业实践:

- **必打**:GitHub Releases(原始 binary)。
- **macOS**:Homebrew(主流)。
- **Linux**:
  - AUR(Arch 用户,程序员社区)
  - Ubuntu PPA / Snap(Ubuntu 用户)
  - Flatpak(跨发行版,GUI 应用)
- **Windows**:Scoop / Chocolatey / winget。
- **Docker**:容器化部署。

不是每个项目都打全部。CLI 工具:GitHub Releases + Homebrew + AUR 够。GUI:加 Snap / Flatpak。

## 7 · Container Builds

### 7.1 Dockerfile

```dockerfile
FROM rust:1.75-slim as builder

WORKDIR /app
COPY Cargo.toml Cargo.lock ./
COPY src/ ./src/
RUN cargo build --release

FROM debian:bookworm-slim
COPY --from=builder /app/target/release/my_app /usr/local/bin/
ENTRYPOINT ["my_app"]
```

构建:

```bash
docker build -t my-app:0.2.0 .
docker push my-app:0.2.0
```

### 7.2 多阶段构建的关键

- **stage 1(build)**:rust:1.75-slim,完整 Rust toolchain。编译 release binary。
- **stage 2(runtime)**:debian:bookworm-slim,只有 runtime lib。COPY binary 进来。

最终镜像只有几十 MB(没有 Rust 编译器)。

### 7.3 Scratch 镜像(最小)

```dockerfile
FROM rust:1.75 as builder
WORKDIR /app
COPY . .
RUN apt-get update && apt-get install -y musl-tools
RUN rustup target add x86_64-unknown-linux-musl
RUN cargo build --release --target x86_64-unknown-linux-musl

FROM scratch
COPY --from=builder /app/target/x86_64-unknown-linux-musl/release/my_app /my_app
ENTRYPOINT ["/my_app"]
```

最终镜像 < 10 MB。完全静态链接(musl libc),无任何依赖。生产 server 部署理想。

### 7.4 CI 里 build Docker

```yaml
  docker:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKER_USERNAME }}
          password: ${{ secrets.DOCKER_TOKEN }}
      - uses: docker/build-push-action@v5
        with:
          push: true
          tags: myorg/my-app:${{ github.ref_name }}
```

## 8 · WASM + GitHub Pages

### 8.1 构建 WASM

```toml
# Cargo.toml
[lib]
crate-type = ["cdylib"]

[dependencies]
wasm-bindgen = "0.2"
```

```bash
rustup target add wasm32-unknown-unknown
cargo build --release --target wasm32-unknown-unknown

# 转 .wasm + .js(让浏览器能加载)
cargo install wasm-bindgen-cli
wasm-bindgen --out-dir target/wasm --target web \
    target/wasm32-unknown-unknown/release/my_app.wasm
```

### 8.2 部署到 GitHub Pages

`index.html`:

```html
<!DOCTYPE html>
<html>
<head><title>My WASM App</title></head>
<body>
<script type="module">
import init from './my_app.js';
async function run() {
    await init();
}
run();
</script>
</body>
</html>
```

`.github/workflows/pages.yml`:

```yaml
name: Deploy to Pages

on:
  push:
    branches: [main]

permissions:
  contents: read
  pages: write
  id-token: write

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: dtolnay/rust-toolchain@stable
        with:
          targets: wasm32-unknown-unknown
      - run: cargo install wasm-bindgen-cli
      - run: cargo build --release --target wasm32-unknown-unknown
      - run: wasm-bindgen --out-dir dist --target web target/wasm32-unknown-unknown/release/my_app.wasm
      - run: cp index.html dist/
      - uses: actions/upload-pages-artifact@v3
        with:
          path: dist

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - uses: actions/deploy-pages@v4
        id: deployment
```

push 到 main 自动 build + deploy。访问 `https://yourname.github.io/your-repo/` 看 WASM 应用。

### 8.3 trunk(更易用的工具)

`trunk` 是 WASM web 项目的 build tool,封装 wasm-bindgen + bundler。

```bash
cargo install trunk
trunk serve   # 开发服务器
trunk build   # 生成 dist/
```

`index.html` 用 trunk 语法:

```html
<!DOCTYPE html>
<html>
<head><title>My App</title></head>
<body>
<link data-trunk rel="rust" data-bin="my_app">
</body>
</html>
```

trunk 自动 build Rust + 生成 JS glue + 引入。

## 9 · Code Coverage

### 9.1 tarpaulin

`cargo-tarpaulin` 是 Rust 老牌覆盖率工具。仅 Linux。

```bash
cargo install cargo-tarpaulin
cargo tarpaulin --out Html --output-dir coverage/
# 或 LCOV 格式
cargo tarpaulin --out Lcov --output-dir coverage/
```

### 9.2 llvm-cov

`cargo-llvm-cov` 更快、更准。基于 LLVM 工具。

```bash
cargo install cargo-llvm-cov
rustup component add llvm-tools-preview

cargo llvm-cov               # 跑测试 + 报告
cargo llvm-cov --lcov --output-path lcov.info   # LCOV 格式
cargo llvm-cov --html        # HTML 报告
```

### 9.3 上传

```yaml
- uses: codecov/codecov-action@v4
  with:
    files: lcov.info
```

或 Coveralls:

```yaml
- uses: coverallsapp/github-action@v2
  with:
    path-to-lcov: lcov.info
```

PR 显示覆盖率变化,工业标配。

## 10 · Dependabot / Renovate

### 10.1 问题

依赖每月更新——CVE 修复、新功能、bug 修复。手动跟踪不现实。

### 10.2 Dependabot

GitHub 内置。`.github/dependabot.yml`:

```yaml
version: 2
updates:
  - package-ecosystem: "cargo"
    directory: "/"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 10

  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "monthly"
```

Dependabot 每周扫描 Cargo.toml,自动开 PR 更新。

### 10.3 Renovate

Renovate 是更强大的替代(Mend 维护,开源):

```json
// renovate.json
{
  "extends": ["config:recommended", ":semanticCommits"],
  "schedule": ["before 6am on Monday"],
  "rust": { "enabled": true }
}
```

Renovate 支持 Cargo / npm / Docker / GitHub Actions 等几十种包管理器。一个 PR 可以更新多个依赖("batch")。比 Dependabot 灵活。

## 11 · 真实项目 CI 剖析

### 11.1 ripgrep

ripgrep 是 Andrew Gallant(BurntSushi)维护。CI 配置在 `.github/workflows/ci.yml`:

```bash
gh repo clone BurntSushi/ripgrep
cd ripgrep
cat .github/workflows/ci.yml | head -100
```

观察:

- **Build matrix**:跨 OS、跨 Rust 版本(stable + beta + nightly + MSRV)。
- **MSRV**(Minimum Supported Rust Version)测试:ripgrep 的 Cargo.toml 有 `rust-version = "1.65"`,CI 测 1.65 能 build。
- **测试 nextest**:大量 integration test。
- **Doc 测试**:cargo test --doc。
- **Cross compile**:测 WASM、ARM。

### 11.2 nushell

nushell 是 Sophia Turner 团队维护。

```bash
gh repo clone nushell/nushell
cd nushell
cat .github/workflows/ci.yml
```

观察:

- **Plugin 测试**:nushell 有 plugin 生态,每个 plugin 单独 CI。
- **Stress test**:大文件 / 长字符串 stress。
- **Standard rejection**:某些 OS 不支持,CI 标记 ignore。

### 11.3 bevy

```bash
gh repo clone bevyengine/bevy
cd bevy
cat .github/workflows/ci.yml
cat .github/workflows/validation.yml
```

观察:

- **Examples build**:几百个 examples,每个都要 build。
- **Multiple feature flags**:matrix 测各种 feature 组合。
- **Validation**:separate workflow 跑 miri / clippy extra pedantic。

## 12 · CI/CD 设计 checklist

设计一个 Rust 项目 CI/CD 时,按这个清单:

**基础**:
- [ ] build matrix(Linux / macOS / Windows)
- [ ] Rust 版本(stable + beta)
- [ ] cargo cache
- [ ] cargo build
- [ ] cargo test

**质量**:
- [ ] rustfmt --check
- [ ] clippy -D warnings
- [ ] cargo deny(安全 / license)
- [ ] coverage(llvm-cov + codecov)

**发布**:
- [ ] cargo-release 或 cargo-dist
- [ ] GitHub Releases(auto)
- [ ] Homebrew(可选)
- [ ] AUR(可选)
- [ ] Docker(可选)

**自动化**:
- [ ] Dependabot / Renovate
- [ ] 自动部署(WASM / Pages / Docker Hub)

不是所有项目都要全部。**按规模和重要性选**——但 build + test + lint 是底座,必须有。

## 13 · 延伸阅读

- GitHub Actions 文档:https://docs.github.com/en/actions
- dtolnay/rust-toolchain action:https://github.com/dtolnay/rust-toolchain
- Swatinem/rust-cache:https://github.com/Swatinem/rust-cache
- cargo-dist:https://github.com/axodotdev/cargo-dist
- cargo-release:https://github.com/crate-ci/cargo-release
- cargo-llvm-cov:https://github.com/taiki-e/cargo-llvm-cov
- tarpaulin:https://github.com/xd009642/tarpaulin
- trunk(WASM):https://trunkrs.dev/
- Renovate:https://docs.renovatebot.com/
- ripgrep CI:https://github.com/BurntSushi/ripgrep/blob/master/.github/workflows/ci.yml
- nushell CI:https://github.com/nushell/nushell/tree/main/.github/workflows
- Bevy CI:https://github.com/bevyengine/bevy/tree/main/.github/workflows
- Axo.dev(cargo-dist 作者,有大量发版工具):https://axodotdev.github.io/
- "Building Rust Apps for Multiple Platforms":https://matklad.github.io/2024/03/23/the-correct-way-to-ship-rust-binaries.html
