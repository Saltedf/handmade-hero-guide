
# 15 · 读 C 和汇编:读懂 Casey 的 C,用 objdump/gdb 看 x86_64 汇编

> Handmade Hero 原版是 Casey 用 C++ 写的。你要"跟 Casey 学",必须能读他的 C 代码。更深一层:有时候 C 也表达不清(尤其是优化后的机器代码),你要能读**汇编**。这一篇把 C 的基本语法、Casey 的代码风格、x86_64 汇编基础、用 objdump/gdb 看汇编,一次性讲透。

## 0 · 为什么要有这一天

Casey 的代码在 https://github.com/HandmadeHero/handmade-hero 。你打开 `handmade.cpp`,看到:

```c
internal void
GameOutputSound(game_offscreen_buffer *Buffer, int ToneHz)
{
    // ...
    int16 *SampleOut = Buffer->Samples;
    for(int SampleIndex = 0;
        SampleIndex < Buffer->SampleCount;
        ++SampleIndex)
    {
        real32 SineValue = sinf(t);
        int16 SampleValue = (int16)(SineValue * ToneVolume);
        *SampleOut++ = SampleValue;
        *SampleOut++ = SampleValue;
        t += 2.0f*Pi32*1.0f / (real32)WavePeriod;
    }
}
```

你大概率读不懂——`internal` 是什么?`int16 *SampleOut` 是什么?`*SampleOut++ = ...` 又是什么?

更难的是,Casey 后面优化代码时会**讲汇编**——"这里 rustc 编译出来的指令比 GCC 多 3 个 mov,所以慢"。如果你不读汇编,这段你也听不懂。

最后,你想真正"理解"为什么 `a + b` 比 `fma(a, b, 0)` 慢、为什么 SIMD 一次处理 4 个浮点数、为什么 cache miss 比乘法慢 100 倍——**汇编是终极答案**。

**心理锚点**:这一篇读完,你能:
- 读懂 Casey 的 C/C++ 代码(`*p`, `->`, `typedef`, `struct`, 函数指针)
- 用 `objdump -d` 反汇编一个二进制,看函数对应的汇编
- 用 `gdb` 单步执行汇编,看寄存器变化
- 看懂常见 x86_64 指令:`mov`, `add`, `mul`, `cmp`, `jmp`, `call`, `ret`
- 用 Compiler Explorer(godbolt.org)对比 C/Rust 的汇编输出
- 理解 Rust 编译器为什么比 GCC 慢 / 慢在不同地方

## 1 · 概念地图:C 代码到汇编到机器码

```
源码 (.c / .cpp)
      │
      │ 预处理(cpp:展开 #include / #define)
      ▼
预处理后源码
      │
      │ 编译(gcc / clang / rustc:生成汇编)
      ▼
汇编 (.s)
      │
      │ 汇编(as:生成机器码)
      ▼
目标文件 (.o)
      │
      │ 链接(ld:合并多个 .o + 库)
      ▼
可执行文件 (ELF)
      │
      │ 加载(execve)
      ▼
进程内存
```

每一层都是一个抽象。我们关心:
- 源码层(读懂 Casey 的 C)
- 汇编层(理解编译器做了什么)
- ELF 层(用 objdump/readelf 看)

**关键洞察**:同一份 C 代码,不同优化等级(`-O0` vs `-O3`)、不同编译器(gcc vs clang vs rustc),汇编差别巨大。**汇编是"翻译",不是"原文"**——它是编译器对源码的理解 + 优化的产物。

## 2 · 心智模型

### 类比:C 是"中级语言",汇编是"机器的语言"

- **高级语言**(Python / JS):贴近人,远离机器
- **中级语言**(C / Rust):在人和机器之间
- **汇编**:贴近机器,每个语句 ≈ 一条机器指令
- **机器码**:0/1,机器直接执行

C 被称为"中级语言",因为它**直接对应机器**——C 的指针就是内存地址,C 的 struct 就是连续字节,C 的 int 就是 32 位整数。Rust 在这之上加了所有权 / 借用 / trait 的抽象,但底层仍然是 C 那一套。

### C 代码 = 给机器写的"操作说明"

读 C 时,你想的是"CPU 在干什么":
- `int x = 5;` → CPU 把 5 写到一个寄存器,然后存到栈上某地址
- `*p = 10;` → CPU 把 10 写到 p 指向的内存地址
- `if (x > 0)` → CPU 比较 x 和 0,设置标志寄存器,条件跳转

Rust 抽象掉了一些细节(比如你不需要想"这个变量在栈还是堆"),但 C 让你直接面对。

### x86_64 汇编:寄存器 + 指令

x86_64 CPU 有 16 个**通用寄存器**(每个 64 位):

| 寄存器 | 习惯用途 | 谁用 |
|---|---|---|
| `rax` | 返回值 / 算术 | 通用 |
| `rbx` | 通用(被调用方保存) | callee-saved |
| `rcx` | 第 4 个参数 / 循环计数 | 通用 |
| `rdx` | 第 3 个参数 / 除法 | 通用 |
| `rsi` | 第 2 个参数 | 通用 |
| `rdi` | 第 1 个参数 | 通用 |
| `r8-r11` | 第 5-8 参数 | 通用 |
| `r12-r15` | 通用(callee-saved) | callee-saved |
| `rbp` | 栈帧基址(老式用法) | 通用 |
| `rsp` | 栈顶 | 栈管理 |

**Calling convention**(调用约定,Linux System V AMD64):
- 参数 1-6 依次放:`rdi, rsi, rdx, rcx, r8, r9`
- 返回值放:`rax`
- 多余参数放栈上
- callee-saved 寄存器:`rbx, rbp, r12-r15` —— 调用别人时这些值不会被破坏

### 常见 x86_64 指令

| 指令 | 含义 |
|---|---|
| `mov dst, src` | 把 src 复制到 dst |
| `add dst, src` | dst += src |
| `sub dst, src` | dst -= src |
| `imul dst, src` | dst *= src(有符号) |
| `mul src` | rax *= src(无符号,结果存 rdx:rax) |
| `div src` | rdx:rax /= src |
| `inc dst` | dst += 1 |
| `dec dst` | dst -= 1 |
| `neg dst` | dst = -dst |
| `cmp a, b` | 比较(算 b - a,设标志位,不存结果) |
| `test a, b` | 测试(算 b & a,设标志位) |
| `je label` | jump if equal(等于跳,ZF=1) |
| `jne label` | jump if not equal |
| `jg label` | jump if greater(有符号) |
| `jl label` | jump if less |
| `ja label` | jump if above(无符号) |
| `jb label` | jump if below |
| `jmp label` | 无条件跳 |
| `call func` | 调用函数(压栈 + jmp) |
| `ret` | 返回(出栈 + jmp) |
| `push src` | 压栈(rsp -= 8; *rsp = src) |
| `pop dst` | 出栈(dst = *rsp; rsp += 8) |
| `lea dst, [expr]` | 加载地址(算 expr 的地址,不读内存) |

后缀:`b`(byte,8位) / `w`(word,16位) / `l`(long,32位) / `q`(quad,64位)。如 `movb`, `movl`, `movq`。

## 3 · 四域深入

### 3.1 · 读 C 的关键字

#### 类型

```c
int       x;         // 32 位整数
long      y;         // 64 位(Linux 64 位下)
short     z;         // 16 位
char      c;         // 8 位(字符或小整数)
float     f;         // 32 位浮点
double    d;         // 64 位浮点
unsigned  int u;     // 无符号 int
int32_t   i;         // 精确 32 位(需 #include <stdint.h>)
int64_t   big;       // 64 位
uint8_t   byte;      // 8 位无符号
```

Casey 用 typedef 重命名:

```c
typedef float real32;       // 32 位浮点
typedef double real64;
typedef uint32_t uint32;
typedef int32_t int32;
typedef uint16_t uint16;
typedef int16_t int16;
typedef uint8_t uint8;
typedef int8_t int8;
```

这是 HH 的风格——明确写出位数,不依赖 `int` 的平台差异。

#### 指针(`*`)

```c
int x = 5;
int *p = &x;     // p 是指向 int 的指针,& 取地址
int y = *p;      // * 解引用,读 p 指向的值
*p = 10;         // 写:p 指向的地址写入 10(即 x 变成 10)
```

读法:`int *p` —— p 是 int 指针。
- `&x`:取 x 的地址(指针)
- `*p`:解引用 p(读那个地址的值)

C 指针 = Rust 的 `*mut T` / `*const T`(裸指针,unsafe)。

#### 数组 vs 指针

```c
int arr[10];        // 数组,10 个 int
int *p = arr;       // 数组名退化为指针
p[3] = 5;           // 等价于 *(p + 3) = 5
arr[3] = 5;         // 同上
```

数组本质是连续内存,下标 `a[i]` = `*(a + i)`。这就是为什么 C 数组不检查越界——编译器就是算地址,你越界它就读到下一块内存。

#### struct

```c
struct Point {
    int x;
    int y;
};

struct Point p;
p.x = 1;
p.y = 2;

struct Point *pp = &p;
pp->x = 10;        // -> 等价于 (*pp).x
```

`->` 是"通过指针访问字段"的简写。`pp->x` ≡ `(*pp).x`。

struct 在内存里是**字段连续排列**(可能有 padding):

```
struct Point 在内存里(假设 int 4 字节):
偏移 0:  int x  (4 字节)
偏移 4:  int y  (4 字节)
共 8 字节
```

#### typedef

```c
typedef struct Point Point;    // 让 Point 等价于 struct Point
Point p;                       // 不用写 struct Point 了
```

Casey 经常 typedef:

```c
typedef struct game_offscreen_buffer {
    void *Memory;
    int Width;
    int Height;
    int Pitch;
} game_offscreen_buffer;
// 之后直接用 game_offscreen_buffer(不用 struct 前缀)
```

#### 函数

```c
int add(int a, int b) {
    return a + b;
}

// 函数指针
int (*fp)(int, int) = add;
int result = fp(3, 4);     // 通过函数指针调用
```

函数指针读法复杂:`int (*fp)(int, int)` —— fp 是一个指针,指向接受 (int, int) 返回 int 的函数。

Casey 用 typedef 简化:

```c
typedef int (*add_fn)(int, int);
add_fn fp = add;
```

#### 控制流

```c
if (x > 0) { ... }
else if (x == 0) { ... }
else { ... }

while (cond) { ... }
do { ... } while (cond);

for (init; cond; step) { ... }
// 等价于:
// init;
// while (cond) { ...; step; }

switch (x) {
    case 1: ...; break;
    case 2: ...; break;
    default: ...;
}
```

#### Casey 风格:`internal` / `globalvar`

```c
#define internal static
#define global_variable static
#define local_persist static

internal void Foo() { ... }    // 文件内 static 函数
global_variable int X;          // 全局 static 变量
```

Casey 用这种"自文档化"宏,让代码意图明确。看到 `internal` 就知道这函数只在当前文件用。

### 3.2 · 把 C 翻译成汇编

让我们看几个简单的例子。用 Compiler Explorer(godbolt.org)或本地 gcc:

```bash
# 装 gcc + gdb + binutils(包含 objdump)
sudo pacman -S gcc gdb binutils
```

#### 例子 1:加法

```c
// add.c
int add(int a, int b) {
    return a + b;
}
```

编译 + 反汇编:

```bash
gcc -O2 -S add.c -o add.s     # -S 输出汇编
cat add.s
```

输出(简化,AT&T 语法):

```asm
add:
    lea    eax, [rdi + rsi]    ; eax = rdi + rsi(参数 1 + 参数 2)
    ret                         ; 返回(eax 是返回值)
```

或 Intel 语法(更易读,我们在本篇用):

```bash
gcc -O2 -S -masm=intel add.c -o add.s
cat add.s
```

```asm
add:
    lea    eax, [rdi + rsi]    ; eax = rdi + rsi
    ret
```

**逐行解释**:
- `lea eax, [rdi + rsi]` —— LEA = Load Effective Address,本来算地址,这里用来做加法(快)
- `eax` —— rax 的低 32 位(返回值是 int 32 位)
- `rdi` —— 第一个参数(a)
- `rsi` —— 第二个参数(b)
- `ret` —— 返回

#### 例子 2:循环

```c
// sum.c
int sum(int n) {
    int total = 0;
    for (int i = 0; i < n; i++) {
        total += i;
    }
    return total;
}
```

`-O2` 后 gcc 可能用数学公式优化(高斯求和 `n*(n+1)/2`)。我们关掉优化看原始汇编:

```bash
gcc -O0 -S -masm=intel sum.c -o sum.s
cat sum.s
```

简化后:

```asm
sum:
    push   rbp                  ; 保存调用者的 rbp
    mov    rbp, rsp             ; 设置栈帧
    mov    DWORD PTR [rbp-20], rdi  ; n 存到 [rbp-20]
    DWORD PTR [rbp-4], 0        ; total = 0
    DWORD PTR [rbp-8], 0        ; i = 0
.L2:
    mov    eax, DWORD PTR [rbp-8]   ; eax = i
    cmp    eax, DWORD PTR [rbp-20]  ; cmp i, n
    jge    .L5                       ; if i >= n,跳出
    mov    eax, DWORD PTR [rbp-4]   ; eax = total
    add    eax, DWORD PTR [rbp-8]   ; eax += i
    mov    DWORD PTR [rbp-4], eax   ; total = eax
    add    DWORD PTR [rbp-8], 1     ; i++
    jmp    .L2                       ; 回到循环开头
.L5:
    mov    eax, DWORD PTR [rbp-4]   ; eax = total
    pop    rbp                       ; 恢复 rbp
    ret
```

每条指令都对应 C 的一小段。开 `-O2`:

```asm
sum:
    test   edi, edi              ; n == 0?
    jle    .L8
    lea    eax, [rdi - 1]        ; eax = n - 1
    imul   eax, edi              ; eax = (n-1)*n
    shr    eax                   ; eax /= 2
    add    eax, edi              ; 不对...gcc 实际公式略不同
    ret
.L8:
    xor    eax, eax              ; return 0
    ret
```

gcc 识别出求和模式,用乘法代替循环——O(N) 变 O(1)。这就是优化的威力。

#### 例子 3:指针

```c
void fill(int *arr, int n, int val) {
    for (int i = 0; i < n; i++) {
        arr[i] = val;
    }
}
```

`-O2` 后(可能 SIMD 化):

```asm
fill:
    test   esi, esi              ; n == 0?
    jle    .L4
    mov    eax, esi
    shr    eax, 2                ; eax = n / 4(SIMD 4 个一组)
    test   eax, eax
    je     .L5
    ; SIMD 循环:
    vxorps xmm0, xmm0, xmm0
.L3:
    vmovdqu YMMWORD PTR [rdi], ymm1   ; 一次写 32 字节(8 个 int)
    add    rdi, 32
    add    r8, 1
    cmp    r8, r9
    jb     .L3
    ...
```

gcc 用 AVX2 `vmovdqu` 一次写 32 字节(8 个 int),比标量循环快 8 倍。这就是 SIMD 的力量。

### 3.3 · 工具:objdump 反汇编可执行文件

```bash
# 编译
gcc -O2 add.c -o add

# 反汇编
objdump -d -M intel add | grep -A 20 "<add>"
# -d 反汇编
# -M intel 用 Intel 语法(默认 AT&T)
# grep 找 add 函数,显示后 20 行

# 输出:
# 0000000000001129 <add>:
#     1129:   01 f7                   add    edi, esi
#     112b:   89 f8                   mov    eax, edi
#     112d:   c3                      ret
```

实际可执行文件里 add 函数只有 3 条指令!

`objdump` 其他有用的:

```bash
# 看所有 section
objdump -h add

# 看 .data / .rodata
objdump -s -j .rodata add

# 反汇编 + 源码(需要 -g 编译)
gcc -g -O2 add.c -o add
objdump -d -M intel -S add | less
# 看到 C 源码和汇编交错
```

### 3.4 · 工具:readelf 看 ELF 结构

```bash
readelf -h add       # 看 ELF 头
readelf -S add       # 看 section headers
readelf -l add       # 看 program headers(运行时 segments)
readelf -s add       # 看 symbol table
readelf -d add       # 看 dynamic 段(依赖的 .so)
```

### 3.5 · 工具:gdb 单步汇编

```bash
gcc -g add.c -o add
gdb add

(gdb) break add
(gdb) run 3 4
(gdb) disas                     ; 反汇编当前函数
(gdb) info registers            ; 看寄存器
(gdb) stepi                     ; 单步汇编(一条指令)
(gdb) nexti                     ; 单步(不进 call)
(gdb) print $rdi                ; 打印 rdi
(gdb) x/4xb $rdi                ; 看 rdi 指向的 4 字节,16 进制
```

### 3.6 · 工具:Compiler Explorer(godbolt.org)

https://godbolt.org 是在线工具,左边写 C/Rust/Go 代码,右边实时显示汇编。无比适合学习。

选编译器:`x86-64 gcc 13.2`,加 `-O2 -masm=intel`,写代码,实时看。

### 3.7 · Rust vs C 汇编对比

Rust 同样的 add:

```rust
pub fn add(a: i32, b: i32) -> i32 {
    a + b
}
```

```bash
rustc -O --emit asm --crate-type lib add.rs -o /dev/stdout 2>/dev/null | grep -A 5 "add:"
# 输出(简化):
# add:
#     lea eax, [rdi + rsi]
#     ret
```

完全一样!**优化后的 Rust 和 C 编译出同样的汇编**——它们底层是同一套机器。

Rust 比 C 慢的地方:
- 编译时间长(Rust 类型检查 + 借用检查 + monomorphization)
- debug 模式 Rust 慢(默认不做优化,加上 panic / array bound check)
- release 模式 Rust 和 C 几乎一样

### 3.8 · 读 Casey 的 C:实战

打开 https://github.com/HandmadeHero/handmade-hero/blob/main/code/day024/handmade.cpp 的一段:

```c
internal void
RenderWeirdGradient(game_offscreen_buffer *Buffer, int BlueOffset, int GreenOffset)
{
    uint8 *Row = (uint8 *)Buffer->Memory;
    for(int Y = 0; Y < Buffer->Height; ++Y)
    {
        uint32 *Pixel = (uint32 *)Row;
        for(int X = 0; X < Buffer->Width; ++X)
        {
            uint8 Blue = (uint8)(X + BlueOffset);
            uint8 Green = (uint8)(Y + GreenOffset);
            *Pixel++ = ((Green << 8) | Blue);
        }
        Row += Buffer->Pitch;
    }
}
```

逐段翻译:

```c
internal void                  // "internal" = static,文件内私有
RenderWeirdGradient(           // 函数名
    game_offscreen_buffer *Buffer,  // 参数:指向 game_offscreen_buffer 的指针
    int BlueOffset,
    int GreenOffset)
{
    // Buffer->Memory 是 void*;强制转成 uint8*(字节指针)
    uint8 *Row = (uint8 *)Buffer->Memory;

    for(int Y = 0; Y < Buffer->Height; ++Y)
    {
        // 把 Row 当 uint32*(4 字节指针)用——4 字节表示一个像素
        uint32 *Pixel = (uint32 *)Row;
        for(int X = 0; X < Buffer->Width; ++X)
        {
            // 强转截断:取低 8 位
            uint8 Blue = (uint8)(X + BlueOffset);
            uint8 Green = (uint8)(Y + GreenOffset);
            // 0x00GG_BBBB:绿在 bits 8-15,蓝在 bits 0-7
            // Green << 8 把 Green 移到 bits 8-15
            // | Blue 合并
            // *Pixel++ = ...:写入 Pixel 指向的地址,然后 Pixel++
            *Pixel++ = ((Green << 8) | Blue);
        }
        // Pitch 是"一行字节数"——可能有 padding
        Row += Buffer->Pitch;
    }
}
```

**用 Rust 重写**:

```rust
fn render_weird_gradient(buffer: &mut GameOffscreenBuffer, blue_offset: i32, green_offset: i32) {
    // buffer.memory 是 &mut [u8]
    let pitch = buffer.pitch as usize;
    let width = buffer.width as usize;
    let height = buffer.height as usize;

    for y in 0..height {
        // 一行的起点
        let row_start = y * pitch;
        // 按 4 字节(一个像素)切
        for x in 0..width {
            let pixel_offset = row_start + x * 4;
            let blue = (x as u8).wrapping_add(blue_offset as u8);
            let green = (y as u8).wrapping_add(green_offset as u8);
            // 0x00RRGGBB(本例 R=0)
            let pixel = (green as u32) << 8 | blue as u32;
            // 写到 4 字节(Little-Endian)
            buffer.memory[pixel_offset..pixel_offset + 4].copy_from_slice(&pixel.to_le_bytes());
        }
    }
}
```

Rust 版本:
- 不用裸指针,用切片(自动边界检查)
- 没有 `*Pixel++` 这种"写完顺便自增"——Rust 拆开
- `wrapping_add` 显式说明溢出语义(C 是隐式)

性能上,`-O3` 编译后 Rust 版本和 Casey 版本汇编几乎一样。

## 4 · 认知地图

### 4.1 上级

- **ABI(Application Binary Interface)** — 二进制层接口,规定函数参数怎么传、返回值怎么传、寄存器谁保存
- **Instruction Set Architecture(ISA)** — x86_64 / ARM64 / RISC-V 等,每套 ISA 的汇编不同
- **Calling Convention** — 调用约定,Linux System V AMD64 是主流

### 4.2 同级

| 工具 | 干啥 |
|---|---|
| gcc / clang | C/C++ 编译器 |
| rustc | Rust 编译器 |
| objdump | 反汇编 + 看 sections |
| readelf | 看 ELF 结构 |
| gdb / lldb | 调试器(看寄存器、单步) |
| strace | 看 syscall |
| Compiler Explorer | 在线实时汇编对比 |
| radare2 / Ghidra | 逆向工程(高级) |

### 4.3 下级

- **寄存器** — CPU 内部的存储单元
- **指令** — CPU 能执行的最小操作
- **栈(stack)** — 后进先出内存区,存局部变量 + 返回地址
- **堆(heap)** — 动态分配内存区
- **ELF 文件格式** — Linux 可执行文件格式

## 5 · 对照与变奏

### AT&T vs Intel 汇编语法

| | AT&T(gcc 默认) | Intel |
|---|---|---|
| 顺序 | `mov src, dst` | `mov dst, src` |
| 寄存器前缀 | `%eax` | `eax` |
| 立即数前缀 | `$5` | `5` |
| 内存 | `(%rax)` | `[rax]` |

Intel 更易读,本篇用 Intel。gdb 默认 AT&T,改:`set disassembly-flavor intel`。

### x86_64 vs ARM64

| | x86_64 | ARM64 |
|---|---|---|
| 寄存器数 | 16 通用 | 31 通用 |
| 指令长度 | 变长(1-15 字节) | 定长 4 字节 |
| 风格 | CISC(复杂指令) | RISC(简单指令) |
| 用在 | PC / 服务器 | 手机 / 苹果 M 系列 / 嵌入式 |

M1/M2 Mac 是 ARM64,Raspberry Pi 4 是 ARM64。游戏开发大部分还在 x86_64,但 ARM64 在崛起。

### Casey C 风格 vs 现代 C++

| | Casey(Handmade Hero) | Modern C++ |
|---|---|---|
| 内存管理 | 手动 malloc/free | smart pointers / RAII |
| 字符串 | char* / 自定义 | std::string |
| 模板 | 不用 | 大量 |
| STL | 不用 | 大量 |
| 异常 | 不用 | 用 |

Casey 是"C with classes"风格——他刻意避开 C++ 的高级特性,认为它们引入不可控的复杂度。这种风格在游戏行业很流行(data-oriented design)。

## 6 · 关联 Day

- **铺垫**:[13-diagnosis-tools.md](13-diagnosis-tools.md)(gdb / objdump 基础)
- **当天**:本篇
- **后续**:
  - Phase 1 Day 001(读 Casey 平台层 C 代码)
  - Phase 4 Day 112+(SIMD,需要读汇编)
  - Phase 5(看 Casey 的内联汇编 / 优化技巧)

## 7 · 变式训练

### Lv1 · 概念辨析

**题**:`*p++ = x` 这个表达式做了什么?为什么 `*p++ = x` 和 `(*p)++ = x` 完全不同?

**参考解答**:`*p++ = x`:
1. `p++` 是后置自增,表达式值是 p 自增**前**的值
2. `*` 解引用那个值(原 p)
3. `= x` 把 x 写到那个地址
4. **之后** p 增加 1(其实增加 `sizeof(*p)` 字节)

效果:把 x 写到 *p,然后 p 移到下一个元素。C 程序员喜欢这种"一行做两件事"的写法。

`(*p)++ = x` 是**非法的**——`(*p)++` 是 `*p` 的旧值,然后 `*p += 1`,这是个右值,不能被赋值。如果写成 `(*p) = x; p++;`,效果和 `*p++ = x` 一样,但啰嗦。

Rust 里没有这种歧义——Rust 的 `*p = x; p = p.add(1);` 两步明确分开。

### Lv2 · 动手实践

**题**:在 godbolt.org 上对比下面 3 个版本的汇编:

C 版本:
```c
int sum(int *arr, int n) {
    int total = 0;
    for (int i = 0; i < n; i++) total += arr[i];
    return total;
}
```

Rust 版本:
```rust
pub fn sum(arr: &[i32]) -> i32 {
    arr.iter().sum()
}
```

Rust unsafe 版本:
```rust
pub fn sum(arr: *const i32, n: usize) -> i32 {
    unsafe {
        let mut total = 0;
        for i in 0..n { total += *arr.add(i); }
        total
    }
}
```

完成标准:
1. 都用 `-O2`,看汇编有什么相同 / 不同
2. Rust 版本是不是有边界检查?
3. 哪个版本最短?

**参考解答**(总结):
- 三个版本核心循环几乎一样(`add eax, DWORD PTR [...]`)
- Rust 安全版本:每条 array 访问前可能有边界检查(`cmp, ja`)——但 `iter().sum()` 用迭代器,LLVM 通常能消除边界检查
- Rust unsafe 版本:和 C 完全一样(没有边界检查)
- 最短:三者优化后差不多(10-15 条指令)

### Lv3 · 迁移设计

**题**:Casey 的 `RenderWeirdGradient` 函数里有个 `*Pixel++ = ...`。改成 Rust 时,有几种等效写法?各自性能如何?

写出 3 种 Rust 写法,分析:
1. 用 `chunks_exact_mut(4)` + 写 `u32::to_le_bytes()`
2. 用 `bytemuck::cast_slice_mut::<u8, u32>` 直接得到 `&mut [u32]`
3. 用 unsafe 裸指针(完全模拟 Casey)

哪种最像 Casey?哪种最 Rust 风格?性能差异?

**提示**:`-O3` 下三者可能汇编完全一样。这是 Rust 零成本抽象的体现。

### Lv4 · 开源贡献

**题**:godbolt 是开源项目,GitHub: https://github.com/compiler-explorer/compiler-explorer

1. clone,看 README,看它的源码结构
2. **可能的贡献**:
   - 某个编译器选项的描述不清楚,改进 UI 提示
   - 添加一个 Rust nightly feature 的默认支持
   - README 里有过时信息(typo / 链接失效)
3. fork → branch → PR

写下 PR 描述。

## 8 · Rust / Arch 落地代码

### 完整示例:C → 汇编 → 验证

#### 1. C 代码

```c
// vec_dot.c
#include <stdint.h>

float dot(float *a, float *b, int n) {
    float total = 0.0f;
    for (int i = 0; i < n; i++) {
        total += a[i] * b[i];
    }
    return total;
}
```

#### 2. 编译 + 反汇编

```bash
# -O3 -mavx2 -mfma 开 SIMD + 融合乘加
gcc -O3 -mavx2 -mfma -S -masm=intel vec_dot.c -o vec_dot.s
cat vec_dot.s

# 输出(简化):
# dot:
#     xor    eax, eax                  ; i = 0
#     vxorps ymm0, ymm0, ymm0          ; acc = [0, 0, 0, 0, 0, 0, 0, 0]
#     mov    edx, edi
#     and    edx, -8                    ; edx = n & ~7(8 个一组)
#     test   edx, edx
#     je     .L5
# .L4:
#     vmovups ymm1, YMMWORD PTR [rsi + rax*4]   ; 加载 8 个 a
#     vfmadd231ps ymm0, ymm1, YMMWORD PTR [rdx + rax*4]  ; acc += a * b(融合乘加!)
#     add    rax, 8
#     cmp    rax, rdx
#     jb     .L4
#     ...
```

**关键观察**:
- 用了 `ymm` 寄存器(32 字节,8 个 float)
- `vfmadd231ps`:FMA 指令,一次做 8 个 `a*b+c`(融合乘加,更快更准)
- 一次循环处理 8 个 float,比标量快 8 倍

#### 3. Rust 等价

```rust
pub fn dot(a: &[f32], b: &[f32]) -> f32 {
    a.iter().zip(b).map(|(x, y)| x * y).sum()
}
```

```bash
rustc -O --emit asm --crate-type lib -C target-cpu=native vec_dot.rs -o /dev/stdout 2>/dev/null | grep -A 20 "dot:"
```

输出和 C 几乎一样——SIMD + FMA。Rust 的"高级"迭代器被 LLVM 优化成同样的 SIMD 循环。**这就是零成本抽象**。

### gdb 实战:看 dot 函数执行

```bash
gcc -g -O0 vec_dot.c -o vec_dot_test
cat > main.c << 'EOF'
#include <stdio.h>
float dot(float *a, float *b, int n);
int main() {
    float a[] = {1.0, 2.0, 3.0};
    float b[] = {4.0, 5.0, 6.0};
    printf("%f\n", dot(a, b, 3));  // 1*4 + 2*5 + 3*6 = 32
    return 0;
}
EOF
gcc -g -O0 vec_dot.c main.c -o vec_dot_test

gdb vec_dot_test
(gdb) break dot
(gdb) run
(gdb) disas
# 看 dot 的汇编
(gdb) info registers rdi rsi rdx
# rdi = a 的地址
# rsi = b 的地址
# rdx = n = 3
(gdb) x/3fw $rdi
# 看 a 指向的 3 个 float
# 1.0  2.0  3.0
(gdb) stepi          # 单步汇编
(gdb) stepi
(gdb) info registers
# 看寄存器变化
```

### Arch 上的 binutils 命令

```bash
# 1. objdump:反汇编
objdump -d -M intel /usr/bin/ls | head -50

# 2. readelf:看 ELF 头
readelf -h /usr/bin/ls

# 3. nm:看符号表
nm /usr/bin/ls 2>/dev/null | head

# 4. file:看文件类型
file /usr/bin/ls
# 输出:ELF 64-bit LSB pie executable, x86-64, version 1 (SYSV), dynamically linked

# 5. size:看段大小
size /usr/bin/ls

# 6. ldd:看依赖
ldd /usr/bin/ls
# 输出:libcap.so.2 => /usr/lib/libcap.so.2
#       libc.so.6 => /usr/lib/libc.so.6
#       /lib64/ld-linux-x86-64.so.2 => /usr/lib64/ld-linux-x86-64.so.2

# 7. readelf 看 dynamic section
readelf -d /usr/bin/ls

# 8. addr2line:地址转源码行
addr2line -e /usr/bin/ls 0x12345

# 9. strings:看二进制里的字符串
strings /usr/bin/ls | grep -i version
```

### Troubleshooting

- **objdump 显示 AT&T 语法**:加 `-M intel`
- **gcc 报 "target attribute" 错**:`-mavx2 -mfma` 要 CPU 支持。或用 `-march=native`
- **gdb 看不到源码**:编译时加 `-g`
- **Rust 编译的 binary 看不到符号**:release 默认 strip。`Cargo.toml` 加 `[profile.release] debug = true`

## 9 · 延伸阅读(可选补充,非必需)

本仓库本地:
- [13-diagnosis-tools.md](13-diagnosis-tools.md) — gdb / perf / objdump
- [phase-0/README.md](README.md)

外部稳定 URL:
- Compiler Explorer:https://godbolt.org/
- x86_64 指令参考:https://www.felixcloutier.com/x86/
- Agner Fog 优化手册(指令延迟 / 吞吐):https://www.agner.org/optimize/
- Intel SDM(Intel Software Developer's Manual,巨厚但权威)
- Brendan Gregg 性能页:http://www.brendangregg.com/
- Casey 的"Performance-Aware Programming":https://www.computerenhance.com/

真实开源源码:
- Handmade Hero C 代码:https://github.com/HandmadeHero/handmade-hero
- GCC 源码:https://gcc.gnu.org/git.html
- Rust 编译器:https://github.com/rust-lang/rust
- LLVM(底层编译框架):https://github.com/llvm/llvm-project
