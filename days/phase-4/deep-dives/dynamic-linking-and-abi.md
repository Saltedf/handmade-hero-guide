---
phase: 4
type: deep-dive
title: "动态链接与 ABI:GOT / PLT / dlopen 到底是怎么把两个二进制接起来的"
title_en: "Dynamic Linking & ABI: GOT/PLT/dlopen Internals"
difficulty: 4
duration: "3h"
domains: [systems, rust, linux]
prereqs:
  - phase-2/deep-dives/rust-cdylib-and-ffi
  - phase-1/deep-dives/hot-reload-rust
calibration: "动态链接(GOT/PLT/dlopen)+ ABI 稳定 + 符号可见性 — 深入 hot-reload 与 cdylib 的底层"
---

# 动态链接与 ABI · GOT / PLT / dlopen 到底是怎么把两个二进制接起来的

> 你在 phase-1 写过 hot-reload,在 phase-2 用过 cdylib FFI——`dlopen` 一个 `.so`,`dlsym` 拿到函数指针,下一帧就开始调。那感觉像魔法:两个独立编译的二进制,函数地址在编译时根本不存在,凭什么运行时就能连上?这篇是 T3 系统深度序列的一站,我们钻到 ELF 文件格式、链接器、CPU 跳转指令那一层,把"魔法"拆成可以画出来的机器动作。读完这一篇,你的热重载不再黑盒,plugin 架构不再玄学,而 ABI 不匹配时的诡异崩溃也不再无从下手。

## 0 · 那一刻你觉得整个世界都是魔术

回到 phase-1 的最小 demo。你写了三行:

```rust
let lib = unsafe { Library::new("./target/debug/libgame_lib.so") }?;
let func: Symbol<unsafe extern "C" fn(*mut GameMemory)> =
    unsafe { lib.get(b"update_and_render") }?;
unsafe { func(&mut memory) };
```

保存 `game_lib/src/lib.rs`,改一行 `println` 的内容。终端里 `cargo watch` 重新编译,几秒后游戏画面里就出现新文案,但 `memory.player_x` 还是 73.5——状态没丢。

你脑子里的画面是:平台进程"知道"`update_and_render` 在哪。可它凭什么知道?`libgame_lib.so` 是另一个 cargo 进程几秒前刚生成的;主程序的 `.text` 段几小时前就定型了,里头没有一行指令跳到 `update_and_render`。地址在编译时根本不存在。

这一节就是要回答:两个独立 ELF 之间,运行时是怎么被"焊接"在一起的。答案藏在三件东西里——**重定位表(relocation)**、**过程链接表(Procedure Linkage Table, PLT)**、**全局偏移表(Global Offset Table, GOT)**。再加一个把 `.so` 整个塞进地址空间的系统调用家族 `dlopen`/`dlsym`。

理解这一整套,你就理解了 phase-2 的 `#[no_mangle] pub extern "C"` 为什么是 FFI 的"通用语",也理解了为什么 Casey 在 HH 里反复强调"接口签名绝不能在 hot-reload 中变"——那不是工程洁癖,是机器层面的硬约束。

## 1 · 静态链接 vs 动态链接 · 自包含的巨物 vs 共享的薄壳

我们先把镜头拉到 1970 年代的 Unix。那时候所有库都是静态链接的:你写 `printf("hi")`,链接器把 `printf` 的机器码从 `libc.a` 里抠出来,**复制粘贴**进你的可执行文件。结果就是每个 `/bin/ls` 都自带一份 `printf`、`malloc`、`strlen`,几百个程序跑起来,内存里就躺着几百份一模一样的字节。磁盘也膨胀——一个 100KB 的程序因为链了 libc 变成 2MB。

静态链接的好处极其朴素:一个文件,扔到任何同架构同内核的机器上就能跑,不依赖任何外部 `.so`。这就是为什么 Go 默认静态链接,为什么 Rust release build 默认静态链 glibc 之外的一切,为什么 Docker 的最小镜像里 `FROM scratch` 还能跑一个 Go binary。**自包含 = 部署的简单**。

但静态链接的两个根本缺陷——重复占用、无法升级——在大型系统上不可忍受。1980 年代 SunOS 引入了共享对象(shared object,`.so`)的概念,从此动态链接成为 Unix 的默认。Linux 上的 `.so`、Windows 上的 `.dll`、macOS 上的 `.dylib`,本质都是同一件事:库的机器码**单独**存在一个文件里,系统启动你的程序时,**多个进程可以把同一个 `.so` 的代码段映射(map)到各自的地址空间,共享同一份物理内存**。

注意是"代码段共享"——`.text` 段(机器指令)是只读的,内核用 mmap 把同一个文件的同一页映射到多个进程,物理内存只有一份。数据段(`.data`、`.bss`)每个进程各有一份,因为变量是可写的。这就是为什么你 `ldd /bin/ls` 能看到 `libc.so.6`——系统里几万个程序共享同一份 libc 代码。

动态链接带来的代价是:程序启动时多了一个**运行时链接器(runtime dynamic linker,`ld-linux-x86-64.so.2`)**的步骤。链接器要打开每个 `.so`、解析符号、把函数地址填进主程序里。这就引出了我们这一篇的核心——地址是怎么"填进去"的。

## 2 · 重定位 · 编译时留的空,运行时填的地址

我们做一个小实验。新建一个最小项目:

```rust
// src/main.rs
extern "C" {
    fn external_function(x: i32) -> i32;
}

fn main() {
    let y = unsafe { external_function(42) };
    println!("y = {}", y);
}
```

`external_function` 来自一个 `.so`,编译时根本不知道地址。编译器生成调用 `external_function` 的指令时,它没法写 `call 0x7ffff7deadbeef`——那个地址编完才知道。那编译器怎么办?它写一个"占位符"指令,并留下一张**重定位表**,告诉链接器:"这地方地址还没定,你等 `.so` 进来之后帮我改。"

我们用 `readelf -r` 看重定位表(把上面的程序编译成依赖一个 `.so` 的 ELF 后):

```bash
$ readelf -r target/debug/myapp
Relocation section '.rela.plt' at offset 0x1234 contains 1 entry:
  Offset          Info           Type           Sym. Value    Sym. Name + Addend
0000000000003fd8  0000000100000007 R_X86_64_JUMP_SLOT 0000000000000000 external_function + 0
```

`R_X86_64_JUMP_SLOT` 是关键。它说:地址 `0x3fd8`(在 `.got.plt` 段里)这一格,运行时要被填成 `external_function` 的真实地址。`Offset` 是"留的空在哪",`Sym. Name` 是"要填的符号是谁"。

整个机制可以这么理解:编译器在 `.got.plt` 段里留了**一格槽位**(slot),记下"这格槽位对应符号 `external_function`"。链接器运行时一旦在 `.so` 里找到 `external_function` 的地址,就把那格槽位**改写成那个地址**。**间接**就在这里诞生了:程序不是直接跳到函数,而是跳到"槽位里存的地址"。

这种"留空 + 运行时填"的设计还有一个深远后果:**同一个 `.so` 加载到不同进程里,加载地址可以不一样**(ASLR、位置无关),但只要每格槽位都被正确填上,程序就跑得对。这就是位置无关代码(Position-Independent Code, PIC)的基础。

## 3 · GOT 与 PLT · 一个间接的诞生

现在我们把镜头对准槽位本身。Linux ELF 用**两张表**来组织这些槽位:**全局偏移表(GOT)** 和 **过程链接表(PLT)**。这两个词你以后看到 `.got`、`.plt` 段名就知道指的是它们。它们的关系是 PLT 用 GOT,理解了它们的协作就理解了动态链接的全部。

我们先看 GOT。GOT 是一张地址表,每一格 8 字节(x86_64)。每格槽位要么存某个外部**函数**的地址,要么存某个外部**全局变量**的地址。程序里所有"取这个变量地址"或"调用这个函数"的动作,最后都翻译成"读 GOT 第 N 格里的地址"。GOT 是可写的(因为运行时要被填),所以它和数据段在一块,但 `.got.plt` 是单独划分出来的子段。

PLT 则是一段**机器码**,位于 `.text` 旁边的 `.plt` 段。它由若干个**桩(stub)**组成,每个外部函数对应一个桩。我们用 `objdump -d` 看一个最小 Rust 程序的 PLT:

```bash
$ objdump -d -j .plt target/debug/myapp

Disassembly of section .plt:

0000000000001060 <external_function@plt>:
    1060:   ff 25 72 2f 00 00    jmpq   *0x2f72(%rip)        # 3fd8 <external_function@got.plt>
    1066:   68 00 00 00 00       pushq  $0x0
    106b:   e9 e0 ff ff ff       jmpq   1050 <_init+0x20>
```

三行指令,我们一行一行拆。

第一行 `jmpq *0x2f72(%rip)` 的意思是:**"跳到 GOT 里第 0x3fd8 那一格存的地址"**。注意是间接跳转——`*` 表示"跳到这个地址里存的地址",不是跳到 `0x3fd8` 本身。这就是"一级间接":程序的 `call external_function` 其实是 `call external_function@plt`,而 `external_function@plt` 第一件事就是去 GOT 查地址,然后跳过去。

第二、三行是给"第一次调用"准备的——稍后讲。先想清楚"槽位被填好了之后"的正常路径:

```
main 调 external_function
   ↓ call external_function@plt
PLT 桩第一行:jmpq *got[slot]
   ↓ GOT[slot] 已经存了 external_function 的真实地址
跳进 .so 里的 external_function
   ↓ 执行函数体
ret 回到 main
```

这就是后续每次调用的完整路径。**一次间接跳转,几纳秒**。这就是动态链接的运行时开销——一个内存读 + 一个间接跳转。

那"第一次"为什么不直接这样?因为程序刚启动时,GOT 里那一格还**没填**——链接器还不知道 `external_function` 在哪个 `.so` 的什么地址。这里有两种策略:**急绑定(eager binding)** 和**惰性绑定(lazy binding)**。

急绑定是程序启动时,运行时链接器立刻把所有 GOT 槽位填满。代价是启动慢(`dlopen` 一个大库可能要几百毫秒),好处是后续调用零惊喜。glibc 默认**不**用急绑定,除非你设环境变量 `LD_BIND_NOW=1`。

惰性绑定是默认行为。每个 PLT 桩一开始指向的是"回到链接器"的路径——也就是上面 `objdump` 输出的第二、三行:`pushq $0` 把"我是第 0 个槽位"压栈,然后 `jmpq 1050` 跳到一个固定入口,这个入口是运行时链接器的"解析器(resolver)"。解析器从栈上拿到槽位编号 `0`,知道"现在要解析 `external_function`",去 `.so` 的符号表里查它的地址,把地址**填进 GOT[0]**,然后跳过去执行函数。

**下一次**调用,`jmpq *got[0]` 直接命中真实地址,根本不进解析器。这就是"第一次慢、后续快"。我们用一张心理图记这个机制:

```
首次调用:
  PLT 桩 → GOT[0](指向回 PLT 桩第 6 字节)
        → pushq 槽位号
        → 跳解析器
        → 解析器查 .so,填 GOT[0]
        → 跳函数

后续调用:
  PLT 桩 → GOT[0](已是真实地址)→ 函数
```

PLT/GOT 这套设计之所以优雅,在于它把"地址解析"这件昂贵的事**推迟到第一次调用**,后续调用几乎零开销。整个机制的核心是**一级间接**:程序不去直接跳,而是先去 GOT 查表。这级间接是动态链接能成立的全部秘密。

## 4 · `dlopen` 与 `dlsym` · 运行时再加载

PLT/GOT 解决的是**编译时已知要链接哪个 `.so`** 的场景——`-lgame_lib` 在链接命令行上,程序启动时自动加载。但 hot-reload 不是这样:你要在程序**已经跑起来之后**,主动决定加载哪个 `.so`,而且要能**卸载、再加载新的版本**。这就需要 `dlopen` / `dlsym` 这套 API,POSIX 给的标准接口。

`dlopen` 做的事情,可以拆成几步理解。你调用 `dlopen("./libgame_lib.so", RTLD_NOW)`,它的工作是:

第一,**打开文件并 mmap 到进程地址空间**。内核会把 `.so` 的各段(`.text` 只读、`.data` 可写、`.bss` 清零)映射到当前进程的虚拟地址。注意位置——`dlopen` 会找一段**空闲**的虚拟地址区域(ASLR 的随机基址),所以同一个 `.so` 在不同进程、甚至同一进程的不同次加载里,加载地址都不同。

第二,**处理它依赖的其他 `.so`**(DT_NEEDED 标记)。如果 `libgame_lib.so` 依赖 `libc.so.6`、`libgcc_s.so.1`,递归 `dlopen` 它们(如果还没被加载)。

第三,**重定位**。遍历这个 `.so` 的重定位表,把所有 GOT 槽位填好。`RTLD_NOW` 是急绑定——立即填所有槽位;`RTLD_LAZY` 是惰性绑定——只填 GOT 的初始值,让 PLT 在首次调用时再解析。HH 的 hot-reload 用 `RTLD_NOW` 更稳——加载时就发现符号缺失的错误,不要等到游戏中途崩。

第四,**运行初始化代码**。每个 `.so` 可以有 `__attribute__((constructor))` 函数(C),或者 Rust 的 `#[ctor]`(用 `ctor` crate)。这些函数在 `dlopen` 返回之前自动执行。`dlopen` 返回一个不透明的 handle(`*mut c_void`),后续操作都靠它。

`dlsym(handle, "update_and_render")` 做的事情更直接:**在 handle 对应的 `.so` 的动态符号表(`.dynsym`)里按名字找符号,返回它的运行时地址**。本质就是一个哈希表查找。

我们用 `readelf` 看一个 cdylib 的动态符号表,确认我们的 `update_and_render` 真的在里面:

```bash
$ readelf --dyn-syms target/debug/libgame_lib.so | grep update_and_render
    73: 000000000000a4b0   176 FUNC    GLOBAL DEFAULT   11 update_and_render
```

`FUNC GLOBAL DEFAULT` 表示这是一个全局可见的函数符号,绑定类型是默认(全局),地址 `0xa4b0` 是它在 `.so` 内的相对偏移(加载到内存后加上基址就是真实地址)。**这一行就是 `dlsym` 能找到它的原因**。如果 `#[no_mangle]` 没加,这一行会是 mangled 名字(比如 `_ZN8game_lib18update_and_render17h12345...E`),`dlsym("update_and_render")` 就找不到。

`dlsym` 找不到符号会返回 `NULL`,所以**永远检查返回值**:

```rust
let func: Symbol<unsafe extern "C" fn(*mut GameMemory)> =
    unsafe { lib.get(b"update_and_render") }
        .map_err(|e| format!("symbol not found: {}", e))?;
```

这就是 phase-1 demo 里 `lib.get(...)?` 背后的事——它调 `dlsym`,失败返回 `LibraryError`,成功返回一个借用 `Library` 的 `Symbol`。

`dlclose(handle)` 是 `dlopen` 的反面:减少引用计数,归零时卸载 `.so`(munmap 它的内存,运行析构函数)。hot-reload 里这一步要特别小心:如果你的代码里还持有从这个 `.so` 里 `dlsym` 出来的函数指针,`dlclose` 之后那个指针就指向被释放的内存——调用它就是 use-after-free,通常立即段错误。phase-1 的解法 2(函数指针)就踩这个坑,解法 1(每帧重新 `get`)自动规避。

## 5 · name mangling · 为什么 C++ 的符号名像乱码

讲 `dlsym` 时我们提到一个词——name mangling。这是动态链接里绕不开的一关,直接决定你的函数能不能被按名字找到。

C 的符号名就是源码里的名字,`int foo(int)` 编出来符号就是 `foo`。这叫 C linkage,简单粗暴。但 C++ 有命名空间、有重载(`foo(int)` 和 `foo(double)` 得是不同符号),于是 C++ 编译器把类型信息编码进符号名。`void ns::foo(int, double)` 可能变成 `_ZN2ns3fooEid`。这套编码叫 Itanium ABI mangling,GCC/Clang 都用它,MSVC 用另一套。

mangled 名字对 `dlsym` 是噩梦——你不能在运行时用 `dlsym(handle, "_ZN2ns3fooEid")`,因为名字里的 hash、参数类型一旦改了,名字就变。这就是为什么**所有跨语言 FFI 入口都必须用 C linkage**,即 `extern "C"`。Rust 默认是 Rust mangling(也是 Itanium-like,带 hash),`extern "C"` 切换到 C linkage,符号名就是源码里的名字。

我们做个对照实验。同一段代码,看有/没有 `#[no_mangle]` 的差别:

```rust
// game_lib/src/lib.rs

// 不加 no_mangle,Rust ABI
pub fn internal_rust_fn(x: i32) -> i32 { x + 1 }

// 加 no_mangle + extern "C",C ABI
#[no_mangle]
pub extern "C" fn update_and_render(memory: *mut GameMemory) { /* ... */ }

// 只加 no_mangle,不加 extern "C"(仍 Rust ABI,符号名不 mangle)
#[no_mangle]
pub fn update_only_nomangle(x: i32) -> i32 { x + 2 }
```

编译后用 `nm` 看(只看 T,即代码段的全局符号):

```bash
$ nm -C --defined-only target/debug/libgame_lib.so | grep -E "update|internal"
000000000000a4b0 T update_and_render          ← 干净的名字
000000000000a520 T update_only_nomangle       ← 也是干净名字,但 ABI 是 Rust
000000000000a600 T internal_rust_fn           ← mangled,例如 _ZN8game_lib14internal_rust_fn...
```

`-C` 是 demangle,会把 `_ZN8game_lib...` 还原成可读形式。**关键洞察**:`#[no_mangle]` 只解决"名字"问题,不解决"ABI"问题。`update_only_nomangle` 名字干净,但调用约定是 Rust ABI——用 `extern "C" fn` 类型的函数指针去调它,参数怎么传可能完全错。这就是 phase-2 反复强调的:**FFI 入口必须同时 `#[no_mangle]` 和 `extern "C"`**,缺一不可。

`extern "C"` 解决的是 ABI 稳定;`#[no_mangle]` 解决的是符号可被按名字找到。两个正交问题,两道手续,合起来才能让 `dlsym` 找得到、找到后调得对。

## 6 · ABI 稳定性 · 为什么 Rust 不能直接跨 reload 边界

讲完名字,我们讲 ABI 本身。ABI 全称 Application Binary Interface,**二进制层**的接口规约。它规定的是机器层面的契约:

- 函数参数怎么传(寄存器还是栈,哪些寄存器,什么顺序)
- 返回值放哪
- 谁负责清栈(调用者 vs 被调用者)
- 结构体的内存布局(字段顺序、对齐、padding)
- 浮点/SIMD 寄存器的使用约定
- 异常怎么传播(unwind 表)

ABI 是**编译器 + 平台 + 操作系统**三方约定的,不是语言标准的一部分。Linux x86_64 用 System V AMD64 ABI(整数参数走 RDI/RSI/RDX/RCX/R8/R9,浮点走 XMM0-7),Windows x86_64 用 Microsoft x64 ABI(整数走 RCX/RDX/R8/R9,要 shadow space)。同一份 Rust 代码编译出的 `.so` 在 Linux 上能跑,搬到 Windows 上不能跑——ABI 不同。

为什么 ABI 是动态链接和 hot-reload 的命脉?因为 `dlsym` 拿到的是一个**裸地址**,你拿到这个地址之后必须告诉编译器"用哪个 ABI 调它"。这就是 `extern "C" fn` 类型签名的作用——它告诉编译器"调用这个指针时按 System V AMD64 ABI 走"。

Rust 的默认 ABI("Rust" ABI)**不稳定**——Rust 团队明确保留改动的权利。理由很硬核:Rust 想在编译器内部自由优化,比如把 `&[T]` 的 `(ptr, len)` 改成"len 用低 3 位编码对齐信息"之类的 niche optimization。这种优化在单进程内无可挑剔,但**破坏 ABI**——昨天编的 `.so` 还按 `(ptr, len)` 布局,今天的 `.so` 按 `(ptr, len_with_flags)` 布局,reload 之后读出来的 len 是垃圾。

这不是假想威胁。Rust 历史上改过 enum 的 niche layout(让 `Option<NonNull<T>>` 和 `*mut T` 一样大),改过闭包的捕获布局。每次改动对单进程 Rust 程序透明,但对 cdylib FFI 是毁灭性的。

所以 FFI 边界**必须用 `extern "C"`**。`extern "C"` 告诉 Rust 编译器:"这个函数的调用约定、参数布局,按平台的 C ABI 走,不要做 Rust 特有的优化。"System V AMD64 ABI 是几十年不变的工业标准,glibc、GCC、Clang、Rust、Zig 全都遵守它,跨编译器、跨语言、跨 rustc 版本都兼容。

这就是 phase-2 的 `#[repr(C)]` + `#[no_mangle] pub extern "C" fn` 的根本原因——不是风格偏好,是**ABI 稳定性的硬要求**。

我们看一个 ABI 不匹配导致静默腐败的例子。你写了:

```rust
// game_lib V1
#[repr(C)]
pub struct GameMemory {
    pub is_initialized: bool,
    pub player_hp: i32,
}
// sizeof = 8 (bool 1 + padding 3 + i32 4)

#[no_mangle]
pub extern "C" fn update(memory: *mut GameMemory) {
    let memory = unsafe { &mut *memory };
    memory.player_hp -= 1;
}
```

某天你想"优化"布局,把 `player_hp` 提到前面(以为这样更紧凑,或者只是手贱):

```rust
// game_lib V2(改了布局)
#[repr(C)]
pub struct GameMemory {
    pub player_hp: i32,    // ← 现在在前面
    pub is_initialized: bool,
}
// sizeof = 8 (i32 4 + bool 1 + padding 3)
```

`sizeof` 还是 8,但**字段偏移变了**。platform 进程里的 `GameMemory` 还是按 V1 布局分配的(`player_hp` 在 offset 4),`update` 按新代码读 `player_hp` 当成 offset 0——读出来其实是 `is_initialized` 的字节 + 3 字节垃圾,然后 `-= 1`,把那个垃圾当 hp 减,写回 offset 0,覆盖了 `is_initialized`。

游戏表现:`player_hp` 看起来随机变化,`is_initialized` 可能突然变 false 触发重新初始化,玩家进度丢失。**没有任何报错,没有 crash,就是数据默默变烂**。这是 ABI mismatch 最阴险的形态——不是 segfault,是逻辑错误。

phase-1 教你的防御:`#[repr(C)]` 是必要但不充分,你还得**保证字段顺序稳定**。加字段只加末尾,不改现有字段顺序。重大改动重启 platform。这些工程纪律的底层就是这一节讲的事。

## 7 · 符号可见性 · 别让你的内部函数污染动态符号表

讲完 ABI,我们讲一个常被忽略但影响"加载速度"和"封装性"的话题——符号可见性(symbol visibility)。

默认情况下,GCC 编译 C 代码时所有非 static 函数都是全局可见的(导出到 `.dynsym`)。Rust cdylib 也类似——`pub fn` 默认会被考虑导出(虽然 Rust 编译器对 cdylib 做了过滤,只导出真正跨 crate 用的)。导出多了有两个坏处:

第一,**动态符号表膨胀**。`.dynsym` 是 `dlopen` 时必须扫描的表,符号越多,`dlsym` 越慢(虽然现代 glibc 用 hash 加速,但仍有常数开销),链接器初始化越慢。大型 C++ 库的 `.dynsym` 可以有几万个符号。

第二,**封装泄漏**。你导出了 `internal_helper`,外部代码就能 `dlsym` 拿到它调用,你就背上了"不能改这个函数签名"的 ABI 包袱,即使你本不想公开它。

Linux ELF 的符号可见性有几个级别,从最公开到最私有:`DEFAULT` > `PROTECTED` > `HIDDEN`。`PROTECTED` 表示符号在本 `.so` 内可见、外部 `.so` 看不到;`HIDDEN` 表示完全内部,不出现在 `.dynsym` 里。

C 里控制可见性用 `__attribute__((visibility("hidden")))`,或者编译时 `-fvisibility=hidden` 全局默认隐藏、对要导出的加 `__attribute__((visibility("default")))`。Rust cdylib 自动做了大量过滤——只有标了 `#[no_mangle] pub extern "C"` 的函数才进 `.dynsym`,内部 `pub fn` 不会导出。这是 Rust 比 C 友好的地方。

但 Rust 仍然可能多导出。你的 cdylib 链了一个依赖 `some_lib`,如果 `some_lib` 的符号默认可见,链接器**可能**把它们也加进 cdylib 的 `.dynsym`。结果就是你的 cdylib 的动态符号表里有大量 `some_lib::xxx` 符号,既慢又暴露内部依赖。

控制办法:Cargo.toml 里加:

```toml
[profile.release]
# 让 Rust 编译时把非 #[no_mangle] 函数都设为 hidden
# (Rust 默认就这么做,但显式确认无害)
codegen-units = 1
lto = true

# 更激进:全局强制 hidden,只 #[no_mangle] 的才出来
# 通过 RUSTFLAGS:
#   -C default-hidden-visibility=yes
```

或者直接在 build.rs 里给链接器传参数,或者在源码里用 nightly 的 `#[link_name]` 配合 visibility 控制(目前 stable Rust 没有直接的 visibility 属性,主要靠 cdylib 的默认行为)。

我们用 `nm -D`(等价于 `--dynamic`)看一个 cdylib 实际导出了哪些符号:

```bash
$ nm -D target/release/libgame_lib.so
0000000000000000 A __bss_start
000000000000a4b0 T update_and_render
000000000000a520 T get_api_version
0000000000000000 A _edata
0000000000000000 A _end
0000000000000000 T _init
0000000000000000 T _fini
```

`T` 是代码段(Text)的全局符号——除了系统自动生成的 `_init`/`_fini`,你应该只看到你**有意**公开的 `update_and_render` 和 `get_api_version`。如果这里冒出来一堆 `some_internal_function`、`alloc::raw_vec::...`,说明可见性控制失效了,需要排查。

良好实践:**cdylib 的导出表应该极小**——只放 FFI 入口函数,内部实现全部通过模块系统封在 crate 内部。phase-2 的 `api.rs`(FFI wrapper)+ `internal.rs`(safe Rust 实现)分层就是这个原则的体现。`internal.rs` 的所有函数都不会出现在 `.dynsym` 里,因为它们没有 `#[no_mangle]`,Rust 编译器自动隐藏。

## 8 · hot-reload 完整链路 · 现在你懂每一行了

把前面 7 节攒起来,我们重新看 phase-1 的 hot-reload 链路,这次每一行都知道在做什么。

**编译期**:你写 `game_lib` 这个 crate,`Cargo.toml` 里 `crate-type = ["cdylib"]`。rustc 把它编成 `libgame_lib.so`——一个 ELF 共享对象,带 `.dynsym` 动态符号表,里面有 `update_and_render`(因为你加了 `#[no_mangle]`)。函数代码本身用 System V AMD64 ABI(`extern "C"`)。

**platform 启动**:platform 是个普通 ELF 可执行文件,不依赖 `libgame_lib.so`(它没有 `DT_NEEDED` 指向 game_lib,因为我们想运行时决定加载哪个)。它链了 `libloading`,libloading 内部调用 `libc` 的 `dlopen`/`dlsym`。

**`Library::new(path)`**:这步调 `dlopen(path, RTLD_NOW)`。运行时链接器打开 `libgame_lib.so`,mmap 到地址空间(基址随机),处理它依赖的其他 `.so`,把所有 GOT 槽位按 `RTLD_NOW` 急绑定填好,跑构造函数。返回一个 handle。

**`lib.get(b"update_and_render")`**:这步调 `dlsym(handle, "update_and_render")`。链接器在 handle 对应的 `.so` 的 `.dynsym` 里查 `update_and_render`,找到地址(基址 + `0xa4b0`),返回这个裸地址。libloading 把它包成 `Symbol<unsafe extern "C" fn(*mut GameMemory)>`,生命周期绑定到 `Library`。

**调用 `func(&mut memory)`**:CPU 执行一条 `call` 指令,目标地址是上一步 `dlsym` 返回的地址。`extern "C" fn` 类型告诉编译器:这次调用按 System V AMD64 ABI——`memory` 指针走 RDI 寄存器,栈 16 字节对齐。CPU 跳进 `libgame_lib.so` 的 `.text` 段,执行 `update_and_render` 函数体。函数体内部 `unsafe { &mut *memory }` 把裸指针 cast 成 `&mut GameMemory`,布局按 `#[repr(C)]` 解析——platform 那边的 `memory` 字段顺序和 game_lib 这边的 `GameMemory` 字段顺序一致(因为两边都引同一个 `shared` crate,定义带 `#[repr(C)]`)。

**reload 触发**:`cargo watch` 重新编译 `game_lib`,生成新的 `libgame_lib.so`(覆盖旧文件)。platform 检测到 mtime 变化,等 50ms(防读到半成品),调 `Library::new` 重新 `dlopen`——这次加载的是新版本的 `.so`,基址可能不同(ASLR),符号地址不同。然后重新 `lib.get(b"update_and_render")` 拿新的函数指针。

**`memory` 不动**:这是关键。`memory` 是 platform 进程的栈/堆变量,reload 不影响它。新版本的 `update_and_render` 接收同一个指针,看到的是同一块内存,但代码是新版本——这就是"代码可换、状态保留"的全部魔法。能做到这一点,是因为 `GameMemory` 的内存布局(`#[repr(C)]`)在新旧版本间一致——这是 ABI 稳定性的直接回报。

理解了这条链路,你就理解了所有 plugin 系统。phase-0 的 09B-2 讲的插件架构本质就是:主程序定义一个 ABI 接口(一组函数签名),插件实现这个接口并编成 cdylib,主程序 `dlopen` + `dlsym` 拿到函数指针调用。HH 自己就是一个超大 plugin 系统——平台层是宿主,游戏层是插件,只是"插件"恰好可以热替换。

## 9 · 在你 HH 项目里动手(做中学红线)

理论读完,我们把手指放到键盘上。下面这套练习让你亲眼看见 PLT/GOT,亲手操作符号表,亲手制造一次 ABI 崩坏。这是把"魔法"变成"机制"的最后一步。

**第一步:在你的 HH 项目里编出 cdylib,用 readelf 看 PLT/GOT。**

确保 `game_lib` 能 `cargo build`(产出 `target/debug/libgame_lib.so`)。然后:

```bash
# 看动态段(确认它是个 .so,有哪些 DT_NEEDED 依赖)
$ readelf -d target/debug/libgame_lib.so

# 看 PLT 重定位(每一项是一个"运行时要填地址的函数槽位")
$ readelf -r target/debug/libgame_lib.so | head -40

# 反汇编 PLT 段(看每个桩的 jmpq *got[...] 模式)
$ objdump -d -j .plt target/debug/libgame_lib.so
$ objdump -d -j .plt.got target/debug/libgame_lib.so
```

你应该能看到一堆 PLT 桩,每个对应一个 game_lib 调用的外部函数(比如 `libc` 的 `printf`、`memcpy`)。桩的第一行都是 `jmpq *某地址(%rip)`,那个地址就是 GOT 里对应的槽位。把 PLT 桩的地址、GOT 槽位的地址一一对照,在纸上画一张表——这就是你那个 cdylib 的"动态链接地图"。

**第二步:用 nm / objdump -T 看导出的符号,验证 #[no_mangle] 的效果。**

```bash
# nm -D 看动态符号表
$ nm -D target/debug/libgame_lib.so | grep -E "update|render|get_api"

# objdump -T 是另一种看动态符号的方式
$ objdump -T target/debug/libgame_lib.so | grep update_and_render
```

你应该看到 `update_and_render` 是干净名字(没有 `_ZN...` mangle 前缀),类型是 `T`(Text 段全局符号)。然后**故意去掉** `#[no_mangle]` 重新编译,再看:

```bash
$ nm -D target/debug/libgame_lib.so | grep update
000000000000a4b0 T _ZN8game_lib18update_and_render17h1a2b3c4d5e6f7a8bE
```

现在名字变成 mangled 形式。`dlsym("update_and_render")` 会失败。这印证了 phase-2 的铁律:`#[no_mangle]` 是符号可被按名字找到的前提。

**第三步:用 ldd 看依赖,验证 cdylib 链了什么。**

```bash
$ ldd target/debug/libgame_lib.so
        linux-vdso.so.1 (0x00007fff...)
        libgcc_s.so.1 => /lib/x86_64-linux-gnu/libgcc_s.so.1 (0x...)
        libc.so.6 => /lib/x86_64-linux-gnu/libc.so.6 (0x...)
        ld-linux-x86-64.so.2 => /lib64/ld-linux-x86-64.so.2 (0x...)
```

`ldd` 显示这个 `.so` 启动时会被 `dlopen` 自动加载哪些依赖。这是 `readelf -d` 里 `DT_NEEDED` 条目的运行时视图。`linux-vdso` 是内核虚拟出的so(提供 `gettimeofday` 等快速系统调用),`ld-linux-x86-64.so.2` 是运行时链接器本身。

**第四步:制造一次 ABI 不匹配,观察腐败。**

这是最有冲击力的一步。你已经在 phase-1 写过 `GameMemory`。现在做这个实验:

```rust
// game_lib V1(当前版本)
#[repr(C)]
pub struct GameMemory {
    pub is_initialized: bool,
    pub player_hp: i32,
    pub player_x: f32,
}

#[no_mangle]
pub extern "C" fn update(memory: *mut GameMemory) {
    let m = unsafe { &mut *memory };
    if !m.is_initialized {
        m.player_hp = 100;
        m.player_x = 0.0;
        m.is_initialized = true;
    }
    m.player_hp -= 1;
    m.player_x += 1.0;
    println!("hp={} x={}", m.player_hp, m.player_x);
}
```

跑一会,看到 hp 在减、x 在增。然后**改字段顺序但保持 #[repr(C)]**(假装是"优化"):

```rust
// game_lib V2(字段顺序变了,#[repr(C)] 还在)
#[repr(C)]
pub struct GameMemory {
    pub player_hp: i32,       // ← 现在在 offset 0
    pub is_initialized: bool, // ← 现在 offset 4
    pub player_x: f32,        // ← 现在 offset 8
}
```

注意 `shared` crate(平台和 game_lib 都引的那个)**别改**,只改 game_lib 里的副本。`cargo watch` 自动重编,platform hot-reload 拿到新 `.so`。

下一帧,新代码读 `memory.player_hp`(按新布局,offset 0),但 platform 写入的内存按旧布局,offset 0 是 `is_initialized` 字节。你看到的现象:`player_hp` 输出值怪异(可能是 0 或 1,因为读的是 bool 字节),`is_initialized` 被 `player_hp -= 1` 写坏(可能变 0 触发重新初始化,玩家 hp 突然重置成 100)。

**这就是 ABI mismatch 的现场**。`#[repr(C)]` 没救你,因为 `#[repr(C)]` 只保证"按声明顺序布局",但你的声明顺序变了。这个实验做完,你会对"接口签名绝不在 hot-reload 中改"这条铁律有身体记忆。

**第五步:把隐藏的函数暴露出来,看符号表变化。**

在 game_lib 里加一个普通 `pub fn`:

```rust
// game_lib/src/lib.rs
pub fn internal_helper(x: i32) -> i32 {
    x * 2
}
```

重新编译,`nm -D target/debug/libgame_lib.so | grep internal_helper`。**应该找不到**——Rust cdylib 默认不导出非 `#[no_mangle]` 函数。这印证了上一节讲的可见性控制。

现在给它加 `#[no_mangle]`:

```rust
#[no_mangle]
pub fn internal_helper(x: i32) -> i32 {
    x * 2
}
```

重新编译,`nm -D` 现在能看到 `internal_helper` 了——但它是 Rust ABI(`extern "Rust"`)。从 platform 里 `dlsym` 拿到地址,用 `extern "C" fn` 类型调用,大概率参数读取错误(Rust ABI 不一定把第一个参数放 RDI)。这印证了 phase-2 的另一条铁律:**符号可见 ≠ ABI 兼容**,两个正交问题必须分别解决。

做完这五步,你不再把 hot-reload 当魔法。你看到的是 `.so` 文件、ELF 段、符号表、寄存器约定——一堆可以测量、可以操控的物理对象。

## 10 · 练习

**Lv1 · 看懂基础。** 用 `readelf -d target/debug/libgame_lib.so` 列出所有 `DT_NEEDED` 条目,说明每一条的含义。用 `objdump -d -j .plt` 找到一个具体的 PLT 桩,把它画在纸上,标注"第一行 jmpq 跳到 GOT 哪一格"。

**Lv2 · 改一改。** 在你的 game_lib 里加一个新 `#[no_mangle] pub extern "C" fn get_api_version() -> u32`,返回 `1`。platform 在 `dlopen` 之后调 `dlsym` 拿到它,打印版本号。然后用 `nm -D` 确认它在动态符号表里。下次 reload 改返回值为 `2`,看 platform 打印更新——这是版本化 ABI 的最简实现。

**Lv3 · 跟踪一次 dlopen。** 用 `strace -f -e trace=openat,mmap,target/debug/platform`(或用 `ltrace -e dlopen+dlsym`)跟踪 platform 进程的一次 hot-reload。你能看到一组 `openat("./target/debug/libgame_lib.so", ...)` + 一串 `mmap` 调用——这就是 `dlopen` 在内核层面的动作。把这些 syscall 排成时间线,理解"运行时链接器把 `.so` 塞进进程地址空间"是怎么由 mmap 拼出来的。

**Lv4 · 写一个最小 plugin 系统。** 不用 libloading,直接 `extern "C"` 声明 libc 的 `dlopen`/`dlsym`/`dlclose`(在 `libc` crate 或手写 extern block),实现一个能加载任意 cdylib、调用 `init()`/`update()`/`shutdown()` 三个 `extern "C"` 函数的 plugin manager。每个 plugin 是独立的 cdylib。这是 HH 之外、phase-3 / phase-5 ECS plugin 架构的雏形——你接下来会反复用到这个模式。

## 11 · 延伸阅读

本仓库内交叉引用,强烈建议按顺序读:

- [phase-1/deep-dives/hot-reload-rust.md](../../phase-1/deep-dives/hot-reload-rust.md)——hot-reload 的工程实现,本篇是它的底层"为什么"
- [phase-2/deep-dives/rust-cdylib-and-ffi.md](../../phase-2/deep-dives/rust-cdylib-and-ffi.md)——cdylib + FFI 完整指南,本篇的 ABI 一节是它的深化
- [phase-1/deep-dives/hot-reload.md](../../phase-2/deep-dives/hot-reload.md)——Casey HH 原版 hot-reload 思路(C++ DLL)
- [phase-2/deep-dives/platform-game-separation.md](../../phase-2/deep-dives/platform-game-separation.md)——平台/游戏分离,plugin 模式的源头
- [phase-0/16-rust-toolchain-deep.md](../../phase-0/16-rust-toolchain-deep.md)——rustc/cargo 工具链深入,理解 cdylib 是怎么被产出的
- phase-3 / phase-5 的 ECS plugin 架构(09B-2 系列)——本篇 ABI/dlopen 知识的实战应用

外部资料,补全细节:

- ELF 格式规范(System V ABI):https://refspecs.linuxbase.org/elf/gabi4+/contents.html
- Linux dynamic linker 文档(`ld.so` man page):`man 8 ld.so` / `man 3 dlopen`
- How to Write Shared Libraries(Ulrich Drepper 经典论文):https://www.akkadia.org/drepper/dsohowto.pdf
- MaskRay 的博客(深入 PLT/GOT/重定位的中文/英文资料):https://maskray.me/
- Rust FFI 与 ABI 稳定性讨论:https://github.com/rust-lang/rfcs/issues/2579
- Eli Bendersky 的 "Load-time relocation of shared libraries":https://eli.thegreenplace.net/2011/08/25/load-time-relocation-of-shared-libraries

工具速查(都是本篇用到的):

- `readelf -d <elf>` 看动态段(`DT_NEEDED` 依赖等)
- `readelf -r <elf>` 看重定位表(GOT/PLT 槽位)
- `readelf --dyn-syms <elf>` 看动态符号表(`.dynsym`)
- `objdump -d -j .plt <elf>` 反汇编 PLT
- `objdump -T <elf>` 看动态符号(类似 `readelf --dyn-syms`)
- `nm -D <elf>` / `nm --dynamic <elf>` 看动态符号
- `nm -C <elf>` demangle 显示
- `ldd <elf>` 看 `.so` 依赖
- `strace -e openat,mmap <prog>` 跟踪 `dlopen` 的系统调用
- `ltrace -e dlopen+dlsym <prog>` 跟踪 `dlopen`/`dlsym` 库调用
