# 深入:发布游戏的清单 — 从 polish 到 ship

> Day 667 是 HH 的最后一集——"完成"。但"游戏代码完成"和"游戏发布"不是同一件事。本文系统讲**游戏发布**需要做什么:polish、测试、打包、分发、营销。这是把"作品"变成"产品"的关键过程。

## 1 · "完成"的层次

软件 / 游戏的完成有不同层次:

| 层次 | 状态 |
|---|---|
| Code complete | 代码写完,能跑 |
| Alpha | 功能完整,有 bug,内部测试 |
| Beta | 主要 bug 修了,公开测试 |
| Gold / RC | 候选发布版,准备送厂 |
| 1.0 | 正式发布 |
| 1.x | 后续更新 / DLC |
| EOL | 不再维护 |

HH 到 Code complete(Day 667)就停了——Casey 没走完 alpha → 1.0 的商业发布路径。本文讲完整路径。

## 2 · Polish 阶段

Code complete 到 Beta 之间叫 polish——"打磨"。不是加新功能,是**让已有功能感觉对**。

### 2.1 Game feel(游戏感)

游戏感的元素:

- **响应性**:按键 → 角色动作 < 100 ms
- **动画流畅**:过渡无突兀
- **音效**:每个动作有合适声音
- **粒子 / 后处理**:视觉反馈
- **镜头**:跟随 + 阻尼,不晕

经典 polish 例子:

- 跳跃的"预备动作"(蹲下 100 ms 再起跳)
- 受伤的"屏幕震动"
- 击中敌人的"hit stop"(0.1 秒慢动作)
- 拾取金币的"粒子 + 声音 + 数字弹出"

每个加起来几十毫秒,但**手感**天差地别。

### 2.2 UX / UI

- **菜单清晰**:玩家 5 秒找到开始游戏
- **教程自然**:不强行教,在实践中教
- **设置完整**:键位 / 音量 / 难度可调
- **本地化**:至少 EN / 中文 / 日文

### 2.3 难度曲线

- 入门简单(让玩家上手)
- 中段稳步提升
- 后段挑战
- 可调难度(easy / normal / hard)

### 2.4 Polish 时间预算

经验法则:**前 80% 工作 20% 时间,后 20% polish 80% 时间**。

HH 的 Day 600-667 大部分是 polish——不是加新系统,是修边角 bug、调手感、清理代码。这就是 polish 的真实样子。

## 3 · 测试

### 3.1 单元测试 / 集成测试

```bash
cargo test
```

单元测试覆盖每个函数。集成测试覆盖完整流程(开游戏 → 玩 → 退出)。

HH 没系统测试(教学项目),但商业项目必须有。

### 3.2 Playtest(玩家测试)

找陌生人玩你的游戏,**不要给提示**。观察:

- 玩家哪里卡住?
- 哪里无聊?
- 哪里太简单 / 太难?
- 玩家想做什么但不能做?

每次 playtest 收集反馈,迭代。

### 3.3 兼容性测试

游戏要在多种硬件 / OS 跑:

- Windows 10 / 11
- macOS(Intel + ARM)
- Linux(Ubuntu LTS、Arch、SteamOS)
- 不同 GPU(NVIDIA / AMD / Intel)
- 不同分辨率(1080p / 1440p / 4K)
- 不同输入(键鼠 / 手柄)

每组合都要测。

### 3.4 性能测试

- 最低配置 vs 推荐配置
- 不同场景 benchmark
- 长时间运行(找内存泄漏)

### 3.5 自动化测试

- CI(GitHub Actions)每次 PR 跑测试
- Smoke test:启动游戏 → 进入主菜单 → 退出,确认没崩溃
- Screenshot test:固定输入 → 截图,人工 / ML 比对

## 4 · 打包

### 4.1 Windows

- **MSI installer**:用 WiX Toolset 或 Inno Setup
- **Code signing**:买证书(EV cert 几百美元),签 exe
- **SmartScreen**:Windows Defender 信任需要时间累积

### 4.2 macOS

- **.app bundle**:目录结构,Info.plist
- **DMG**:磁盘镜像,拖拽安装
- **Code signing + notarization**:Apple Developer ID($99/年),`codesign` + `xcrun notarytool`
- **Universal binary**:x86_64 + aarch64

### 4.3 Linux

- **AppImage**:单文件,跨发行版
- **Flatpak**:沙箱,Flathub 分发
- **Snap**:Ubuntu 主导,Snap Store
- **Native packages**:rpm / deb / pacman
- **Steam**:把 Linux 看作一等公民

Linux 分发碎片化严重,推荐 Flatpak 或 AppImage。

### 4.4 资产打包

游戏资产(纹理 / 模型 / 音频)打包成 archive,避免散文件:

- **PAK**(id Software):简单 archive
- **ZIP**:加密 + 压缩
- **Custom format**:Casey 自己写(见 HH 早期)

打包时考虑:**压缩比 vs 加载速度**(LZ4 快但压缩比低,zstd 平衡,LZMA 压缩高但慢)。

## 5 · 分发平台

### 5.1 Steam(标杆)

- **Steamworks**:开发者平台
- **Steam Direct**:$100 一次性费用,上架游戏
- **30% 分成**:标准(年收入 $1000 万后部分降到 25% / 20%)
- **Steam Workshop**:用户生成内容
- **Achievements / Cloud / Trading Cards**:玩家粘性

### 5.2 itch.io

- **独立友好**:门槛低,无审核
- **pay-what-you-want**:玩家自定义价格
- **itch.io app**:类似 Steam 客户端
- **适合**:game jam、实验作品

### 5.3 Epic Games Store

- **88/12 分成**:对开发者友好
- **审核严**:不收所有游戏
- **免费送游戏**:吸引玩家

### 5.4 Console(Switch / PS5 / Xbox)

- **dev kit**:需申请,有门槛
- **certification**:平台严格测试,可能要反复改
- **30% 分成**:标准
- **跨平台工具**:GameMaker / Godot / Unity 帮 port

### 5.5 Mobile(iOS / Android)

- **App Store / Google Play**:30% 分成
- **F2P 主导**:免费 + 内购
- **审核**:严,规则多

## 6 · 营销

游戏发布不只是"上架",是"被人发现"。

### 6.1 Trailer(预告片)

- 30 秒到 1 分钟
- 展示**核心玩法**,不是过场动画
- 节奏快,音效到位
- YouTube / Twitter / Bilibili 发布

### 6.2 Steam page

- Capsule 图(吸引点击)
- GIF(展示游戏动)
- 详细描述
- 系统要求

Steam page 是**最重要的营销资产**——玩家决定是否买游戏,主要看这里。

### 6.3 Demo

- Steam Next Fest:每年几次,集中展示 demo
- Demo 应该展示**核心玩法**,不是"完整游戏的一小段"

### 6.4 Press / Streamer

- 邮件联系游戏记者 / 主播
- 给 early access key
- 关键媒体:Rock Paper Shotgun、Polygon、IGN 等

### 6.5 Community

- Discord server
- Reddit subreddit
- Twitter hashtag
- Bilibili / NGA(中文)

社区是长期生命力。

## 7 · 发布后的运维

### 7.1 Day-1 patch

发布后发现 critical bug,马上 patch。Console 平台 cert 慢,可能要几天。

### 7.2 Hotfix vs Update

- **Hotfix**:critical bug,小改动,快发布
- **Update**:常规更新,新内容,大改动

### 7.3 Player support

- 客服邮箱
- Steam forum
- Bug report 系统

回应玩家 = 信誉。无视 = 差评。

### 7.4 Analytics(可选)

- 收集玩家行为数据(匿名)
- 哪里玩家卡住
- 哪里玩家流失
- 难度曲线真实数据

GDPR / 个人信息保护法要注意。

## 8 · 法律 / 财务

### 8.1 公司

- 个人开发:sole proprietorship(个体)
- 工作室:LLC / Ltd(有限责任公司)
- 区别:责任、税务、可融资

### 8.2 税务

- 个人所得税
- 公司税(如果是公司)
- 国际销售:VAT / GST 复杂

建议:赚够一定数额后找会计师。

### 8.3 IP / 版权

- 你的代码:自动 copyright(你拥有)
- 商标:游戏名注册,防别人用
- 专利:很少用,但核心机制可考虑

### 8.4 License

- 第三方资产:有 license(付费 / CC0 / CC-BY)
- 开源库:MIT / Apache / GPL 等不同要求
- 音乐:特别小心,严 license

## 9 · 发布清单

发布前 checklist(完整):

### 技术
- [ ] 所有平台 build 通过(Windows / Mac / Linux)
- [ ] Code signed + notarized
- [ ] Crash reporter 工作
- [ ] Save / load 测试通过
- [ ] Performance 达标(60 FPS 最低配置)
- [ ] 兼容性测试(多种硬件 / OS)

### 内容
- [ ] 主线 / 副线完整
- [ ] 难度曲线调好
- [ ] 所有 art / music / SFX placeholder 替换
- [ ] 本地化(至少 EN)
- [ ] Credits 写完

### 营销
- [ ] Trailer 制作
- [ ] Steam page 上线(至少 2 周前)
- [ ] Press kit 准备
- [ ] 社交媒体账号
- [ ] Demo(可选)

### 平台
- [ ] Steam build 上传 + 审核
- [ ] itch.io page
- [ ] (如果 console)platform cert

### 法律
- [ ] 公司注册(如果适用)
- [ ] 商标
- [ ] 第三方 license 全部清楚
- [ ] 隐私政策 / 服务条款

### 运维
- [ ] Customer support email
- [ ] Bug report 渠道
- [ ] Day-1 patch 预备

完成清单后,按下"发布"按钮。

## 10 · HH 的"完成"

Casey 的 HH 不走完整发布路径——它是**教育项目**,不是商业产品。但 Casey 留下的代码 + 视频是**完整的教育资产**:

- 视频在 YouTube 永久免费
- 代码在 GitHub 公开
- 社区仍然讨论
- 教学价值持续

这是另一种"完成"——不是商业发布,是**遗产**。

## 11 · 给你的建议

### 11.1 你的第一个游戏

- **目标**:完成 > 完美
- **平台**:itch.io(免费,门槛低)
- **价格**:pay-what-you-want($0 起)
- **时长**:2-5 小时游戏内容

### 11.2 你的"严肃"游戏

如果想要商业化:

- **预算**:至少 6 个月储蓄
- **平台**:Steam(必须)
- **价格**:$5-20(独立游戏 sweet spot)
- **营销**:至少发布前 6 个月开始

### 11.3 不要等"完美"

很多独立开发者陷入"再加一个功能就发布"循环,永远发不了。

**法则**:发布时游戏应该让你"羞愧"(因为有 bug),但已经"可玩有趣"。完美主义是发布的敌人。

## 12 · 总结

游戏发布是**工程 + 营销 + 法律 + 心理**的综合。技术好不等于能赚钱——还要让人发现你的游戏、买你的游戏、喜欢你的游戏。

Casey 的 HH 教你**技术**,本文帮你看到**完整画面**。如果你想做"能赚钱的游戏",这些都要学。

如果你只是**学技术 + 做开源**,HH 的"完成态"也是好目标。开源项目不需要商业化,但仍要 polish、文档、社区。

无论你走哪条路,**完成项目**是最重要的能力。开始做,做完它,发布它,然后做下一个。

## 13 · 延伸阅读

本仓库本地:
- [day667.md](../day667.md) - HH 完成
- [phase-0/12-opensource-pr-flow.md](../../phase-0/12-opensource-pr-flow.md) - 开源 PR 流程

外部稳定 URL:
- Steamworks documentation: https://partner.steamgames.com/doc/
- Indie game postmortems(GDC): https://www.gdcvault.com/
- Itch.io help: https://itch.io/docs/

真实开源 / 工具:
- Godot(开源引擎): https://godotengine.org/
- Inno Setup(Windows installer): https://jrsoftware.org/isinfo.php
- WiX Toolset: https://wixtoolset.org/
