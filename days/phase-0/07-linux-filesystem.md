---
article: 07
phase: 0
title: "Linux 文件系统:FHS / inode / proc / sys / dev / 权限"
type: setup
difficulty: 3
duration: "2-3h"
domains: [linux]
prereqs: ["00-terminal-basics", "01-arch-setup"]
---

# 07 · Linux 文件系统:FHS / inode / proc / sys / dev / 权限

> 你天天在 `/home/<你>/` 下干活,但你知道为什么 home 在 `/home/` 吗?为什么 `/proc/` 看似是文件但实际是内核状态?为什么 `chmod 755` 是这个数字?理解 Linux 文件系统让你从"会用 ls"升级到"理解系统是怎么搭起来的",这是写系统软件、读 Casey C 代码、debug 奇怪问题的根基。

## 0 · 为什么要有这一天

打开 Linux 文件管理器,你看到 `home`、`usr`、`etc`、`var` 等等。每个目录干什么?为什么这样分?

1. **FHS(Filesystem Hierarchy Standard)**:整个 Unix 世界都按这个标准分目录。`/usr/bin` 放二进制、`/etc` 放配置、`/var` 放可变数据。任何 Linux 系统你都立刻知道去哪找东西。Casey 的 C 代码会引用 `/usr/include/stdio.h`,你要知道为什么在 `/usr/include/`
2. **inode 是文件的本质**:你以为"文件 = 文件名 + 内容",Linux 视角是"文件 = inode(元数据) + 数据块",文件名只是引用 inode 的指针。这解释了硬链接、删除行为、磁盘满
3. **proc / sys 是"伪文件"**:`cat /proc/cpuinfo` 看到 CPU 信息,但你硬盘上**没有这个文件**——它是内核动态生成的视图。读懂 proc/sys 你能用纯 cat 命令查/改系统状态,这是 Linux 的精妙设计
4. **dev 是设备**:在 Linux,一切皆文件。键盘、鼠标、磁盘、显卡、声卡都是 `/dev/` 下的文件。你读 `/dev/input/event0` 就在读键盘原始事件。Handmade Hero 后面读输入设备用得到
5. **权限模型**:为什么 `chmod 755` 是这个数字?为什么 git 不能 push 到 `/var/www/`?理解 rwx + UID + GID 模型,你才能写安全的服务端代码

**心理锚点**:读完这一篇,你能:
- 解释每个顶层目录的用途(`/, /bin, /etc, /var, /usr, /home, /tmp, /proc, /sys, /dev, /opt, /mnt`)
- 用 `stat` 看 inode 信息,理解 inode vs 文件名
- 用 `cat /proc/...` 查询内核状态
- 用 `chmod / chown` 正确设置权限
- 解释权限数字(755 = rwxr-xr-x)
- 理解硬链接 vs 软链接

## 1 · 概念地图

| 词 | 是什么 | 类比 |
|---|---|---|
| **FHS** | 文件系统层次标准,规定哪个目录放什么 | 城市规划,商业区 / 住宅区 / 工业区 |
| **inode** | 文件的元数据节点(大小、权限、数据块位置) | 一本书的图书目录卡片 |
| **dentry** | 目录项,文件名 → inode 映射 | 图书馆的索引卡 |
| **block** | 磁盘数据块(通常 4KB) | 一本书的一页 |
| **硬链接(hard link)** | 多个文件名指向同一 inode | 同一本书有多张索引卡 |
| **软链接(symbolic link)** | 一个文件指向另一文件**路径** | 一张"看 X 这本书"的提示卡 |
| **挂载点(mount point)** | 把文件系统接到目录树的某点 | 在书架某层塞入一摞新书 |
| **`/proc`** | 内核和进程的伪文件视图 | 系统状态面板,只读"镜像" |
| **`/sys`** | 设备和驱动的伪文件视图 | 硬件配置面板,可读可改 |
| **`/dev`** | 设备文件 | 硬件的"遥控器" |
| **权限位** | rwx for owner / group / other | 三层门禁卡 |
| **UID / GID** | 用户 ID / 组 ID(整数) | 用户编号 |

## 2 · 心智模型

### 费曼类比:文件系统是"超大图书馆 + 索引系统"

想象一个无限大的图书馆:

- **磁盘**:物理上的书架。书架由**数据块(block)**组成,每块 4KB
- **inode**:每本书的**索引卡**,记录书的元信息(作者、大小、在哪几个书架格子上),但**不**记录书名
- **dentry(目录项)**:目录里的"书名 → 卡片号"映射,这就是文件名
- **文件名**:不属于文件本身,只是目录里的一条记录

关键点:**文件名不存储在文件里**,而是存在它所在目录的数据里。这就是为什么:
- 一个 inode(实际文件)可以有多个文件名(硬链接)
- 删一个文件名,文件实际数据**不一定删**(还有其他文件名引用)
- `mv` 改文件名只改目录里的 dentry,数据不动(超快)

**inode 怎么找到数据块**:inode 记录 12 个直接块指针 + 1 个一级间接指针 + 1 个二级 + 1 个三级。小文件直接指针够,大文件用间接指针索引更多块。

### 软链接 vs 硬链接

```bash
echo "hello" > original.txt

# 硬链接:两个文件名指向同一 inode
ln original.txt hard.txt

# 软链接:symlink 文件存的是路径字符串
ln -s original.txt soft.txt

ls -li
# 输出(第一列是 inode 号):
# 1234567 -rw-r--r-- 2 sun sun 6 ... original.txt
# 1234567 -rw-r--r-- 2 sun sun 6 ... hard.txt    (同 inode,链接数 2)
# 1234568 lrwxrwxrwx 1 sun sun 12 ... soft.txt -> original.txt  (不同 inode,是符号链接)
```

**关键差别**:

| | 硬链接 | 软链接 |
|---|---|---|
| 是什么 | 同一 inode 的另一文件名 | 一个特殊文件,内容是路径 |
| inode | 同 | 不同 |
| 删原文件 | 数据不丢(还有引用) | 链接"悬挂"(指向不存在的文件) |
| 跨文件系统 | 不能 | 能 |
| 链接目录 | 不能(传统) | 能 |

**`rm` 真的"删"了什么**:rm 只是减少 inode 的链接数(nlink)。nlink 到 0 时,内核回收 inode 和数据块(数据其实还在,只是被标记可重用)。这就是为什么删除后用 `extundelete` 还能恢复——只要块没被覆盖。

### 权限模型

每个文件 / 目录有 9 个权限位 + 所有者 + 所属组:

```
-rwxr-xr--
```

| 位置 | 含义 |
|---|---|
| 第 1 位 | 类型:`-` 普通文件,`d` 目录,`l` 符号链接,`c` 字符设备,`b` 块设备,`p` 管道,`s` socket |
| 2-4 (rwx) | 所有者(owner)权限 |
| 5-7 (rwx) | 组(group)权限 |
| 8-10 (rwx) | 其他人(other)权限 |

**rwx 在文件 vs 目录上含义不同**:

| 位 | 文件 | 目录 |
|---|---|---|
| r | 可读内容 | 可列出文件名(ls) |
| w | 可改内容 | 可创建/删除其中文件 |
| x | 可执行 | 可进入(cd)/访问其中文件 |

**权限数字表示**(八进制):

```
r=4, w=2, x=1,累加
rwx = 4+2+1 = 7
r-x = 4+0+1 = 5
rw- = 4+2+0 = 6
r-- = 4

755 = rwxr-xr-x    (所有者全权,组和其他只读+执行)
644 = rw-r--r--    (普通文件标准)
600 = rw-------    (私有文件)
777 = rwxrwxrwx    (所有人全权,危险)
```

`chmod 755 file` 设权限。`chmod u+x file` 给 owner 加执行。`chmod go-w file` 给 group 和 other 去掉写。

**SUID / SGID / sticky bit**:额外的特殊位:

- **SUID**(4000):执行时以文件所有者身份运行。`/usr/bin/passwd` 是 SUID(root 拥有),普通用户跑它也能改 /etc/shadow
- **SGID**(2000):目录上设置时,新建文件继承目录的组
- **sticky bit**(1000):目录上设置时,只有 owner 能删自己的文件。`/tmp` 是 sticky(1777),你不能删别人的临时文件

```bash
ls -ld /tmp
# drwxrwxrwt 20 root root ... /tmp
#                  ^  t 表示 sticky bit 设置

ls -l /usr/bin/passwd
# -rwsr-xr-x 1 root root ... /usr/bin/passwd
#     ^  s 表示 SUID 设置
```

### 文件系统层次结构(FHS)

```
/                       根目录,所有路径起点
├── bin                 基本命令(ls, cat, grep),所有用户可用
├── sbin                系统管理命令(fdisk, mount),需要 root
├── lib / lib64         基本库(glibc, libc.so)
├── usr                 "UNIX System Resources",大部分软件装这
│   ├── bin             用户命令(neovim, gcc, rustc)
│   ├── sbin            系统命令
│   ├── lib             库
│   ├── include         C 头文件(stdio.h, stdlib.h)
│   ├── share           架构无关数据(man, doc, icons)
│   └── local           本地安装的软件(不归包管理器管)
├── etc                  配置文件(文本)
│   ├── passwd          用户列表
│   ├── shadow          密码哈希(只有 root 可读)
│   ├── hostname        主机名
│   ├── fstab           文件系统挂载表
│   ├── sudoers         sudo 权限配置
│   ├── pacman.d/       pacman 配置
│   ├── systemd/        systemd 配置
│   └── ssh/            sshd 配置
├── var                 可变数据(日志、缓存、数据库)
│   ├── log             日志(/var/log/journal/, /var/log/pacman.log)
│   ├── cache           包管理器缓存(/var/cache/pacman/pkg/)
│   ├── lib             应用状态(/var/lib/pacman/local/ 等)
│   ├── spool           队列(print, mail, cron)
│   └── tmp             临时文件(重启保留)
├── home                用户家目录(/home/sun/)
├── root                root 的家目录(不在 /home 下)
├── tmp                 临时文件,重启清空
├── proc                内核 + 进程伪文件
│   ├── cpuinfo         CPU 信息
│   ├── meminfo         内存信息
│   ├── version         内核版本
│   ├── self            当前进程的"自己"链接
│   ├── 1/              PID 1(systemd)的信息
│   │   ├── status      进程状态
│   │   ├── cmdline     启动命令
│   │   ├── maps        内存映射
│   │   ├── fd/         打开的文件描述符
│   │   └── ...
│   └── sys/            内核子系统(可调参数)
├── sys                 设备和驱动伪文件(sysfs)
│   ├── class/          设备分类(net/, block/, input/)
│   ├── devices/        设备树
│   └── kernel/         内核参数
├── dev                 设备文件
│   ├── null            黑洞设备(写到这的丢掉)
│   ├── zero            读到全 0
│   ├── random          随机数
│   ├── urandom         非阻塞随机数
│   ├── sda, sdb        SCSI/SATA 磁盘
│   ├── sda1            磁盘分区
│   ├── nvme0n1         NVMe 磁盘
│   ├── input/          输入设备(event0, mice)
│   ├── snd/            声音设备
│   ├── tty             当前终端
│   ├── pts/            伪终端
│   └── shm/            共享内存(tmpfs)
├── opt                 第三方软件(可选)
├── mnt                 临时挂载点
├── media               可移动设备挂载(U盘)
├── boot                启动相关(vmlinuz 内核镜像, grub/)
├── run                 运行时数据(pid 文件,socket)
├── srv                 服务数据(HTTP 文件等,通常空)
└── lost+found          fsck 修复后的孤立文件(ext 文件系统)
```

注意:在现代 Linux,**`/bin`、`/sbin`、`/lib` 通常是符号链接到 `/usr/bin`、`/usr/sbin`、`/usr/lib`**(叫 "merged /usr")。Arch 默认就这么做。这是为了简化,但概念上仍按 FHS 区分。

### /proc 深入

`/proc` 是内核暴露的"伪文件系统"。读它就是查内核状态,写它就是改内核参数。

```bash
# CPU 信息
cat /proc/cpuinfo | head -20
# 输出:processor, vendor_id, cpu family, model, model name, ...

# 内存
cat /proc/meminfo | head -5
# MemTotal, MemFree, MemAvailable, Buffers, Cached

# 内核版本
cat /proc/version
# Linux version 6.x.x-arch1-1 ...

# 命令行参数(内核启动时)
cat /proc/cmdline
# BOOT_IMAGE=/boot/vmlinuz-linux root=UUID=... rw quiet

# 当前进程信息
ls /proc/self
# /proc/self 是当前进程的"自己"链接
# 包含:cmdline, cwd, environ, exe, fd/, maps, status, ...

# 当前进程的命令行
cat /proc/self/cmdline | tr '\0' ' '
# 输出:cat /proc/self/cmdline
```

`/proc/<pid>/` 是每个进程的"信息门户":
- `status`:进程状态(R/S/Z 等)、UID、内存
- `cmdline`:启动命令(参数以 `\0` 分隔)
- `cwd`:当前工作目录的符号链接
- `exe`:可执行文件的符号链接
- `fd/`:打开的文件描述符(每个 fd 一个符号链接)
- `maps`:虚拟内存映射
- `environ`:环境变量

这就是为什么 `ps`、`top`、`htop` 能列出所有进程——它们读 `/proc/`。

`/proc/sys/` 可调参数:

```bash
# 端口范围
cat /proc/sys/net/ipv4/ip_local_port_range
# 32768   60999

# 临时改(重启失效)
echo 1 > /proc/sys/net/ipv4/ip_forward

# 永久改:写 /etc/sysctl.d/*.conf
echo "net.ipv4.ip_forward = 1" | sudo tee /etc/sysctl.d/99-custom.conf
sudo sysctl -p /etc/sysctl.d/99-custom.conf
```

`sysctl` 命令是 `/proc/sys/` 的封装:`sysctl net.ipv4.ip_forward` 等价 `cat /proc/sys/net/ipv4/ip_forward`。

### /sys 深入

`/sys`(sysfs)是设备模型视图。它显示硬件 + 驱动状态,可读可写:

```bash
# 电池信息
ls /sys/class/power_supply/BAT0/
# capacity, status, charge_full, ...

cat /sys/class/power_supply/BAT0/capacity
# 75

# 亮度(笔记本屏幕)
cat /sys/class/backlight/intel_backlight/brightness
# 500
echo 800 | sudo tee /sys/class/backlight/intel_backlight/brightness
# 立刻变亮

# 网卡
ls /sys/class/net/
# enp3s0 lo wlp2s0
cat /sys/class/net/enp3s0/address
# MAC 地址

# LED 灯
echo 1 | sudo tee /sys/class/leds/inputXX::capslock/brightness
# Caps Lock 灯亮
```

/sys 让你**用文件读写控制硬件**。Handmade Hero 的输入处理会用 `/dev/input/event*`(evdev),设备路径在 `/sys/class/input/`。

### /dev 深入

```bash
# /dev/null:写入丢弃
echo "trash" > /dev/null    # 啥都不发生

# /dev/zero:读到全 0
dd if=/dev/zero of=zeros.bin bs=1M count=10    # 创建 10MB 全 0 文件

# /dev/random:真随机(阻塞,熵不够时等)
# /dev/urandom:伪随机(不阻塞)
head -c 16 /dev/urandom | xxd    # 16 字节随机数

# /dev/null 用法:丢弃 stderr
some_command 2> /dev/null    # 把 stderr 丢黑洞

# 磁盘设备
ls /dev/nvme* /dev/sd*
# /dev/nvme0n1     NVMe 磁盘
# /dev/nvme0n1p1   分区 1
# /dev/sda         SATA 磁盘

# 终端
tty    # 你当前终端的路径,如 /dev/pts/0

# 输入设备
ls /dev/input/
# event0 event1 ... mice ...

# 音频
ls /dev/snd/
# controlC0 pcmC0D0c pcmC0D0p ...
```

`/dev/` 下的设备有两类:

- **字符设备**(c):按字节读写。键盘、串口、`/dev/null`
- **块设备**(b):按块读写。磁盘、SSD

```bash
ls -l /dev/null /dev/nvme0n1
# crw-rw-rw- 1 root root 1, 3 ... /dev/null        c 表示字符设备
# brw-r----- 1 root disk 259, 0 ... /dev/nvme0n1   b 表示块设备
#                                ^^^^^^^^
#                       主设备号,次设备号(内核用)
```

### 文件系统挂载

```bash
# 看挂载情况
mount
# 输出多行,每行:设备 on 挂载点 type 文件系统 (选项)
# /dev/nvme0n1p2 on / type ext4 (rw,relatime)
# tmpfs on /tmp type tmpfs (rw,...)
# ...

# 现代写法
findmnt
# 树形显示,更易读

# 挂载 U 盘
sudo mount /dev/sdb1 /mnt/usb

# 卸载
sudo umount /mnt/usb

# 启动时挂载(/etc/fab)
cat /etc/fstab
# UUID=xxx  /     ext4   defaults  0 1
# UUID=xxx  /home ext4   defaults  0 2
# tmpfs     /tmp  tmpfs  defaults  0 0
```

文件系统类型:

| 文件系统 | 用途 |
|---|---|
| ext4 | Linux 默认,日志,稳定 |
| btrfs | 现代文件系统,快照,压缩 |
| xfs | 大文件好,RHEL 默认 |
| f2fs | Flash 友好,手机用 |
| tmpfs | 内存盘,重启清空 |
| procfs | `/proc`,伪 |
| sysfs | `/sys`,伪 |
| vfat / ntfs | Windows 兼容 |
| iso9660 | 光盘镜像 |
| nfs | 网络文件系统 |
| fuse | 用户态文件系统(sshfs 等) |

## 3 · 四域深入

### 3.1 · 🐧 Linux 系统编程视角

文件系统是 Linux 系统编程的根基。**一切皆文件**的哲学:open / read / write / close 这四个系统调用,**对一切**——普通文件、设备、网络 socket、管道——都适用。

```rust
use std::fs::File;
use std::io::{Read, Write};

// 读 CPU 信息
let mut f = File::open("/proc/cpuinfo")?;
let mut s = String::new();
f.read_to_string(&mut s)?;
println!("{}", s);

// 写 brightness
let mut f = File::create("/sys/class/backlight/intel_backlight/brightness")?;
f.write_all(b"800")?;
```

读 `/proc/cpuinfo` 和读普通文件没区别——内核自动把 read 系统调用重定向到内核函数。

**系统调用层级**:

```
应用代码 (Rust)
    ↓
libc (glibc) - read/write 包装
    ↓
syscall 指令(x86_64: syscall 指令)
    ↓
内核:sys_read / sys_write 函数
    ↓
虚拟文件系统(VFS)
    ↓
具体文件系统(ext4 / proc / sysfs / devtmpfs)
    ↓
块设备驱动 / 内核数据结构
```

VFS(Virtual File System)是关键抽象:它定义统一的 `inode_operation` / `file_operation` 接口,各种文件系统(ext4 / proc / sysfs)实现自己的版本。读 `/proc/cpuinfo` 时,VFS 调用 procfs 的 read 实现;读 `/home/x.txt` 时,调用 ext4 的 read 实现。应用代码不区分。

Casey 在 HH 里讲的 `CreateFileA` / `ReadFile`(Win32)对应 Linux 的 `open` / `read`,内核设计哲学不同但抽象层相似。

### 3.2 · 🦀 Rust 生态视角

Rust 标准库 `std::fs` 是文件操作的封装:

```rust
use std::fs;
use std::os::unix::fs::PermissionsExt;       // Unix 特定扩展

// 读
let content = fs::read_to_string("/etc/hostname")?;

// 写
fs::write("/tmp/test.txt", "hello")?;

// 元数据(对应 stat 系统调用)
let meta = fs::metadata("/etc/passwd")?;
println!("size: {}", meta.len());
println!("is_file: {}", meta.is_file());
println!("perm: {:o}", meta.permissions().mode());

// 改权限
let mut perm = meta.permissions();
perm.set_mode(0o644);
fs::set_permissions("/tmp/test.txt", perm)?;

// 创建目录
fs::create_dir("/tmp/foo")?;
fs::create_dir_all("/tmp/a/b/c")?;  // 递归创建

// 删除
fs::remove_file("/tmp/test.txt")?;
fs::remove_dir_all("/tmp/foo")?;

// 软链接 / 硬链接
std::os::unix::fs::symlink("target", "link")?;
fs::hard_link("source", "hardlink")?;

// 遍历目录
for entry in fs::read_dir("/etc")? {
    let entry = entry?;
    println!("{}", entry.path().display());
}

// 文件存在
if Path::new("/etc/passwd").exists() { ... }
```

著名 Rust 文件系统 crate:

- **walkdir**:跨平台目录递归遍历
- **notify**:文件变更监听(inotify 封装)
- **tempfile**:安全创建临时文件
- **tokio::fs**:异步文件 I/O

### 3.3 · 🎮 游戏编程视角

游戏里文件系统用于:

- **资产加载**:贴图、模型、音频从磁盘读
- **配置 / 存档**:JSON / TOML 文件
- **日志**:写到 `/var/log/` 或 `~/.local/share/game/`
- **mod 系统**:玩家自定义内容,扫目录加载

Handmade Hero 的资产系统(Phase 7)会读 `/assets/sprites/*.png`、`/assets/audio/*.wav`。理解文件系统让你正确处理路径、权限、跨平台目录(Windows 是 `C:\Users\`,Linux 是 `/home/`)。

跨平台目录获取:

```rust
// Cargo.toml: dirs = "5"
use dirs;

let home = dirs::home_dir();           // /home/sun
let data_dir = dirs::data_dir();        // ~/.local/share
let config_dir = dirs::config_dir();    // ~/.config
let cache_dir = dirs::cache_dir();      // ~/.cache
```

这些自动处理 Linux / macOS / Windows 差异。

## 4 · 认知地图

### 4.1 上级

- **VFS(Virtual File System)** — Linux 内核的抽象层,统一所有文件系统接口
- **Plan 9 哲学** — "一切皆文件"的极致,由 Bell Labs 设计,Linux 部分继承(/proc /sys 由此而来)
- **POSIX** — 可移植操作系统接口,规定文件 I/O API 的标准

### 4.2 同级

| 系统 | 文件系统层次 | 特点 |
|---|---|---|
| Linux (FHS) | / /usr /etc /var /proc /sys | 完整,文档化 |
| macOS | 类 FHS,但用 /Applications | FreeBSD 基础 |
| Windows | C:\Users, C:\Program Files | 盘符 + 反斜杠 |
| BSD | 类 FHS,但 /usr/local 更常用 | 历史 |

| 伪文件系统 | 用途 |
|---|---|
| procfs | 进程 + 内核状态 |
| sysfs | 设备 + 驱动状态 |
| devtmpfs | /dev 自动管理 |
| tmpfs | 内存盘 |
| debugfs | 内核 debug 信息 |
| tracefs | ftrace |

### 4.3 下级

- **inode 字段**:权限、所有者、大小、时间戳(atime/mtime/ctime)、数据块指针
- **dentry**:目录项缓存,加速路径查找
- **mount 系统调用**:挂载文件系统
- **open / read / write / close**:基本系统调用
- **stat / fstat / lstat**:查 inode 元数据
- **mmap**:把文件映射到内存(大文件高效)
- **flock / fcntl**:文件锁
- **inotify**:文件事件通知

## 5 · 对照与变奏

### 文件路径分隔符

- Linux / macOS:`/`(正斜杠)
- Windows:`\`(反斜杠)
- URL:`/`

Rust 的 `Path` / `PathBuf` 自动跨平台:

```rust
use std::path::PathBuf;
let p = PathBuf::from("/home").join("sun").join("file.txt");
// Linux: /home/sun/file.txt
// Windows: \home\sun\file.txt
```

### 硬链接 vs 软链接 vs copy

| | hard link | soft link | copy |
|---|---|---|---|
| 占用磁盘 | 不增加(共享) | 微小(路径字符串) | 全量 |
| 删原文件 | 数据还在 | 链接悬挂 | 无影响 |
| 改文件 | 同步看到 | 同步看到 | 独立 |

为什么 git 不用硬链接:跨文件系统不安全。git 用 pack 文件 + 引用。

### inode 满了 vs 磁盘满了

```bash
df -h        # 看磁盘空间
df -i        # 看 inode 使用率!

# 极端情况:磁盘有空间但 inode 满了
# 症状:No space left on device(但 df -h 显示有空间)
# 原因:文件系统有 inode 限制(ext4 默认每 16KB 一个 inode)
# 解决:找小文件多的目录:`for d in /*; do echo $(find $d | wc -l) $d; done | sort -n`
```

某些场景(邮件服务器,每封邮件是小文件)会碰到 inode 满。

## 6 · 关联 Day

- **铺垫**:
  - [00-terminal-basics.md](00-terminal-basics.md) — `ls`、`cd`、`pwd` 命令
  - [01-arch-setup.md](01-arch-setup.md) — `/etc`、`/var`、`pacman` 数据库
- **当天**:[07-linux-filesystem.md](07-linux-filesystem.md)(本篇)
- **后续**:
  - [08-processes-and-signals.md](08-processes-and-signals.md) — `/proc/<pid>/` 是进程信息的来源
  - [13-diagnosis-tools.md](13-diagnosis-tools.md) — strace / ltrace 看系统调用
  - Phase 1 Day 005:从 `/dev/input/event*` 读输入
  - Phase 7:资产加载,扫目录

## 7 · 变式训练

### Lv1 · 概念辨析

**题**:你 `rm` 删了一个文件,然后立刻 `df -h` 发现磁盘空间没释放。两种可能原因,各是什么?

**参考解答**:

1. **有进程还持有该文件的文件描述符**。Linux 规则:inode 的链接数到 0 **且**没有打开的 fd 时,才回收数据块。如果某进程 open 了这文件没 close,删了文件名后 fd 还指向 inode,数据块不释放。解决:用 `lsof | grep deleted` 找出进程,kill 它或让它 close fd

2. **文件被硬链接引用**。rm 只是减少链接数,如果还有其他硬链接指向同一 inode,数据不释放。解决:用 `find / -inum <inode号> 2>/dev/null` 找所有指向同一 inode 的文件

### Lv2 · 动手实践

**题**:探索你的系统的文件系统,完成下列任务:

1. 找出 `/usr/bin/python` 实际指向哪(`/usr/bin/python` 一般是 symlink)
2. 看 `/etc/passwd` 的权限位,解释每段含义
3. 看 `/tmp` 的权限位,解释为什么是 `1777`(`t` 是什么)
4. 看 `/usr/bin/passwd` 的权限位,解释 `s`
5. 用 `stat` 看 `/etc/hostname` 的 inode 号、块数、atime/mtime/ctime
6. 看 `/proc/self/status` 的内容,解释 VmRSS 是什么
7. 列出 `/sys/class/backlight/` 下的目录(笔记本),或 `/sys/class/net/` 下的网卡
8. 用 `dd` 从 `/dev/zero` 创建 1MB 全 0 文件,验证大小

**参考解答**(命令):

```bash
# 1.
ls -l /usr/bin/python
# 输出:lrwxrwxrwx ... /usr/bin/python -> python3
ls -l /usr/bin/python3
# 可能再是 symlink 到 python3.12

# 2.
ls -l /etc/passwd
# -rw-r--r-- 1 root root ...
# 解释:- 普通文件 / rw- root 可读写 / r-- 组只读 / r-- 其他只读

# 3.
ls -ld /tmp
# drwxrwxrwt ... /tmp
# 1777: rwxrwxrwt
# t 是 sticky bit,只有 owner 能删自己创建的文件

# 4.
ls -l /usr/bin/passwd
# -rwsr-xr-x ... 
# s 是 SUID,执行时以 root(文件 owner)身份跑
# 因为 passwd 要写 /etc/shadow,只有 root 能写

# 5.
stat /etc/hostname
# File: /etc/hostname
# Size: 11          Blocks: 8          IO Block: 4096   regular file
# Device: ...
# Inode: 1234567    Links: 1
# Access: (0644/-rw-r--r--)  Uid: (...)  Gid: (...)
# Access: 2024-XX-XX ...    atime(读时间)
# Modify: 2024-XX-XX ...    mtime(内容修改时间)
# Change: 2024-XX-XX ...    ctime(inode 修改时间,如改权限)
# Birth: ...(某些文件系统支持)

# 6.
cat /proc/self/status | grep VmRSS
# VmRSS:      1234 kB
# VmRSS = Virtual Memory Resident Set Size,实际在物理内存的 KB

# 7.
ls /sys/class/backlight/
# 可能输出:intel_backlight / acpi_video0

# 8.
dd if=/dev/zero of=/tmp/zeros.bin bs=1M count=1
# 输出:1+0 records in / 1+0 records out / 1048576 bytes (1.0 MB) copied
ls -l /tmp/zeros.bin
# -rw-r--r-- 1 sun sun 1048576 ...
rm /tmp/zeros.bin
```

### Lv3 · 迁移设计

**题**:你要写一个监控程序,定期扫描 `/var/log/` 找超过 10MB 的日志文件并报告。要求:

1. 递归遍历 `/var/log/`(用 `walkdir` 或 std::fs)
2. 对每个文件,用 `metadata()` 查大小
3. 超 10MB 的输出路径 + 大小
4. 注意权限:可能需要 sudo(因为某些日志只有 root 可读)
5. 跨文件系统边界:跳过 `/var/log/journal/`(单独文件系统)

写出完整 Rust 程序,跑 `sudo cargo run`,看输出。

**提示**:
- `walkdir::WalkDir::new("/var/log").into_iter().filter_map(|e| e.ok())` 容错遍历
- `entry.metadata()?.len()` 拿大小
- `entry.path()` 拿路径

### Lv4 · 开源贡献

**题**:很多 Rust 系统工具就是基于 /proc /sys /dev 的。选一个深入:

1. **procs**(https://github.com/dalance/procs):Rust 写的 ps 替代,读 /proc
2. **bottom**(https://github.com/ClementTsang/bottom):top 替代
3. **bandwhich**(https://github.com/imsnif/bandwhich):网络流量分析

clone 一个,看它怎么读 `/proc/<pid>/stat`、`/proc/net/tcp` 等。找一个 `good first issue` 提 PR。

或者更轻:写一个简单的 `myps` 程序,扫 `/proc/*/status` 列出所有进程,模仿 `ps aux` 的输出。这就是 `procs` 的核心。

## 8 · Rust / Arch 落地代码

### 文件系统巡检脚本

```rust
// src/main.rs
// 综合演示文件系统操作
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

fn main() -> std::io::Result<()> {
    println!("=== 文件系统巡检 ===\n");

    // 1. 当前目录
    let cwd = std::env::current_dir()?;
    println!("当前目录: {}", cwd.display());

    // 2. 家目录
    let home = std::env::var("HOME").unwrap_or_else(|_| "/".to_string());
    println!("家目录: {}", home);

    // 3. 看 /etc 下哪些是目录
    println!("\n/etc 下的目录(前 10):");
    for entry in fs::read_dir("/etc")?.take(10) {
        let entry = entry?;
        if entry.file_type()?.is_dir() {
            println!("  [dir] {}", entry.path().display());
        }
    }

    // 4. 看 /proc/self 的几个关键文件
    println!("\n当前进程(/proc/self):");
    let cmdline = fs::read_to_string("/proc/self/cmdline")?;
    let cmdline = cmdline.replace('\0', " ");
    println!("  cmdline: {}", cmdline);

    let status = fs::read_to_string("/proc/self/status")?;
    for line in status.lines() {
        if line.starts_with("Pid") || line.starts_with("VmRSS") || line.starts_with("Uid") {
            println!("  {}", line);
        }
    }

    // 5. 看 CPU 信息(前 5 行)
    println!("\n/proc/cpuinfo 前 5 行:");
    let cpuinfo = fs::read_to_string("/proc/cpuinfo")?;
    for line in cpuinfo.lines().take(5) {
        println!("  {}", line);
    }

    // 6. 内存使用
    println!("\n/proc/meminfo:");
    let meminfo = fs::read_to_string("/proc/meminfo")?;
    for line in meminfo.lines().take(5) {
        println!("  {}", line);
    }

    // 7. 创建文件 + 改权限
    let test_file = "/tmp/fs_demo.txt";
    fs::write(test_file, "hello\n")?;
    let meta = fs::metadata(test_file)?;
    println!("\n创建 {},权限: {:o}", test_file, meta.permissions().mode());

    // 改权限 600
    let mut perm = meta.permissions();
    perm.set_mode(0o600);
    fs::set_permissions(test_file, perm.clone())?;
    println!("改为权限: {:o}", perm.mode());

    fs::remove_file(test_file)?;

    // 8. 硬链接演示
    let original = "/tmp/hard_link_demo.txt";
    let hardlink = "/tmp/hard_link_demo_2.txt";
    fs::write(original, "data")?;
    fs::hard_link(original, hardlink)?;

    let stat_original = fs::metadata(original)?;
    let stat_hardlink = fs::metadata(hardlink)?;
    println!("\n硬链接演示:");
    println!("  original inode(用 stat 看)");
    println!("  original nlink = (用 stat)");
    // 这里 std::fs 不能直接拿 inode,要用 std::os::unix::fs::MetadataExt
    use std::os::unix::fs::MetadataExt;
    println!("  original inode: {}, nlink: {}", 
             stat_original.ino(), stat_original.nlink());
    println!("  hardlink inode: {}, nlink: {}", 
             stat_hardlink.ino(), stat_hardlink.nlink());

    fs::remove_file(original)?;
    println!("删 original 后,hardlink 还能读:");
    println!("  {}", fs::read_to_string(hardlink)?);
    fs::remove_file(hardlink)?;

    // 9. 软链接演示
    let target = "/tmp/symlink_target.txt";
    let symlink = "/tmp/symlink_demo.txt";
    fs::write(target, "symlink data")?;
    std::os::unix::fs::symlink(target, symlink)?;
    
    let link_meta = fs::symlink_metadata(symlink)?;
    println!("\n软链接 {}:", symlink);
    println!("  类型: symlink? {}", link_meta.file_type().is_symlink());
    println!("  指向: {:?}", fs::read_link(symlink)?);
    
    fs::remove_file(target)?;
    println!("删 target 后,read_link 还行,但 read 会失败:");
    println!("  read_link: {:?}", fs::read_link(symlink));
    match fs::read_to_string(symlink) {
        Ok(s) => println!("  read: {}", s),
        Err(e) => println!("  read error: {}", e),    // 悬挂 symlink
    }
    fs::remove_file(symlink)?;

    Ok(())
}
```

跑:

```bash
cargo run
# 输出:当前目录 / 家目录 / /etc 下的目录 / 当前进程信息 / CPU / 内存 / 硬链接演示 / 软链接演示
```

### 常用命令速查

```bash
# === 磁盘 / 空间 ===
df -h                  # 文件系统使用率(h: human-readable)
df -i                  # inode 使用率
du -sh /path           # 某目录总大小
du -sh /* | sort -h    # 根目录下每项大小,排序
ncdu /                 # 交互式磁盘使用分析(需装 ncdu)

# === 文件信息 ===
ls -l file             # 详细信息(权限、所有者、大小)
ls -li file            # 加 inode 号
stat file              # 完整 inode 信息
file file              # 文件类型(ELF / text / image / ...)
xxd file | head        # 十六进制看头部

# === 权限 ===
chmod 755 file         # 数字设
chmod u+x file         # 符号设(给 owner 加执行)
chmod -R 644 dir/      # 递归
chown user:group file  # 改所有者
chgrp group file       # 改组
umask                  # 看默认权限掩码

# === 链接 ===
ln source hardlink     # 硬链接
ln -s target symlink   # 软链接
readlink symlink       # 读 symlink 指向

# === 挂载 ===
mount                  # 列出所有挂载
findmnt                # 树形
sudo mount /dev/sdb1 /mnt/usb
sudo umount /mnt/usb

# === 查找 ===
find / -name "*.rs" 2>/dev/null    # 全盘找
fd "\.rs$"            # 现代版(更快)
locate somefile       # 用数据库(需先 updatedb)

# === /proc /sys ===
cat /proc/cpuinfo
cat /proc/meminfo
cat /proc/loadavg
cat /proc/uptime
cat /sys/class/power_supply/BAT0/capacity
sysctl -a | grep net.ipv4.ip_local_port_range
```

### 排错

```bash
# 故障 1: "No space left on device" 但 df -h 显示有空间
df -i          # 看 inode 使用率,可能满了
# 解决:删大量小文件

# 故障 2: rm 删了大文件但空间没释放
lsof | grep deleted     # 看哪个进程持有
sudo systemctl restart <那个服务>  # 让它释放

# 故障 3: 权限不够
ls -l file               # 看当前权限
id                       # 看你的 UID/GID/组
sudo                     # 临时 root

# 故障 4: "Permission denied" 但你是 root
# 可能文件有 immutable 属性(ext 特有)
lsattr file              # 看属性
sudo chattr -i file      # 去掉 immutable

# 故障 5: symlink 悬挂
find / -xtype l          # 找所有悬挂 symlink

# 故障 6: /tmp 满了
# /tmp 通常是 tmpfs(内存盘),清空:
sudo rm -rf /tmp/*
# 或重启(自动清)

# 故障 7: 文件名乱码
ls -i                    # 拿 inode
find . -inum <inode> -delete    # 按 inode 删
```

### 进阶:挂载 / 卸载 / 创建文件系统

```bash
# 格式化 U 盘为 ext4(危险!会清空数据)
sudo mkfs.ext4 /dev/sdb1

# 创建 ext4 + label
sudo mkfs.ext4 -L MYUSB /dev/sdb1

# 挂载
sudo mount /dev/sdb1 /mnt/usb

# 卸载(注意:不能在挂载点目录里跑 umount)
cd /
sudo umount /mnt/usb

# 强制卸载(有进程占用时)
sudo umount -l /mnt/usb    # lazy unmount
sudo fuser -km /mnt/usb    # kill 占用进程

# 看文件系统类型
lsblk -f

# 检查文件系统(需先 unmount)
sudo fsck.ext4 /dev/sdb1

# 调整 ext4 大小(增大)
sudo resize2fs /dev/sdb1
```

### 高级:bind mount 和 namespaces

```bash
# bind mount:把一个目录"挂到"另一个位置(共享 inode)
sudo mount --bind /home/sun/project /var/www/project

# 用于容器:docker 用 bind mount + namespace 实现"目录隔离"
# 这是 Docker、systemd-nspawn 的底层技术之一

# 查看某进程的 mount namespace
readlink /proc/<pid>/ns/mnt
```

### mount namespacing(进阶)

Linux 容器(Docker、Podman)的根基是 namespace——让进程"看不见"系统的其他部分。文件系统层面是 mount namespace:

```bash
# 用 unshare 创建新的 mount namespace
sudo unshare -m bash
# 现在你 mount/umount 不影响外部

# systemd-nspawn 是更完整的容器
sudo pacman -S systemd-container
sudo systemd-nspawn -D /path/to/rootfs
```

理解文件系统 + namespace + cgroup,你就理解了容器技术的 80%。这是 Linux 系统编程的高级话题,Phase 4 之后我们会回头讨论。

## 9 · 延伸阅读(可选补充,非必需)

本仓库本地:
- [00-terminal-basics.md](00-terminal-basics.md) — `ls`/`cd`/`pwd`
- [01-arch-setup.md](01-arch-setup.md) — `/etc`、`/var` 配置文件
- [08-processes-and-signals.md](08-processes-and-signals.md) — `/proc/<pid>/`
- [13-diagnosis-tools.md](13-diagnosis-tools.md) — strace 看文件系统调用

外部稳定 URL:
- Arch Wiki File permissions:https://wiki.archlinux.org/title/File_permissions
- Arch Wiki File systems:https://wiki.archlinux.org/title/File_systems
- Filesystem Hierarchy Standard:https://refspecs.linuxfoundation.org/FHS_3.0/fhs-3.0.pdf
- man pages:`man hier`(目录层次)、`man inode`、`man proc`、`man mount`
- The Linux Programming Interface(书,系统编程圣经),Ch.14-15 文件系统

真实开源源码:
- Linux VFS 实现:https://github.com/torvalds/linux/tree/master/fs
- procfs 实现:https://github.com/torvalds/linux/tree/master/fs/proc
- Rust std::fs:https://github.com/rust-lang/rust/tree/master/library/std/src/fs
