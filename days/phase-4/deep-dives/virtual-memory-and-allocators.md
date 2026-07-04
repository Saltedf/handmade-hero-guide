
# 虚拟内存与分配器

> 你在 [phase-0/24-memory-foundation.md](../../phase-0/24-memory-foundation.md) 已经看过"虚拟地址、页表、TLB、cache"的全景。你在 [arena-allocator.md](arena-allocator.md) 已经见过 bump pointer 的帧级 reset。这篇 deep-dive 把两者打通:**你在游戏里自己用 mmap 从内核拿一块虚拟地址空间,在它上面手工搭一个 pool allocator,再给主线程的 entity 换上 guard page**——把"全局 allocator 当魔法"这一层彻底掀掉。Casey 在 Handmade Hero Day 095 就开始手写 memory arena,而你看完这一篇,能理解他为什么要那么干。

## 0 · 你以为是 Vec::push,其实是 syscall

让我把镜头拉到一帧的具体场景。

你的 HH 项目跑到 Day 150。每帧 16 ms。你 profile 一下,发现 4 ms 花在 `__GI___libc_malloc` 和 `__GI___libc_free` 上——光是分配器就吃掉四分之一帧预算。你点开火焰图,每个 `entity.spawn()` 都 `Box::new` 一次,每个粒子死亡都 `free` 一次。一帧十万个粒子,就是十万对 alloc/free。

你不信。你写了个 microbench:`for _ in 0..100_000 { let _b = Box::new(Enemy::default()); }`。`cargo run --release`——50 ms。十万次 `Box::new` 要 50 ms,光这一项就三帧没了。你打开 strace,看到的是一片 `brk` 和 `mmap`/`munmap` 在疯狂跳动。`malloc` 内部维护 fastbin、tcache、arena 锁——它要兼顾"任意大小、任意生命周期、线程安全",代价就是慢。

这就是问题:**全局 allocator 是通用工具,而通用意味着对任何特定 pattern 都不是最优**。游戏的 pattern 极其典型——大量短生命周期对象、固定大小的实体、可预测的释放时机。这些 pattern 配上专门的 allocator,能从 50 ms 压到 0.5 ms,提速 100 倍。

但要写专门的 allocator,你必须先理解它底下的那层——**虚拟内存**。否则你只是把 `malloc` 换成另一个 `malloc`,看不到 syscall 那一层。这一篇的目标,是让你能**自己用 mmap 拿地址空间,自己写 pool / stack / buddy allocator,自己挂 guard page**,然后回到 [memory-layout-for-cache.md](memory-layout-for-cache.md) 的视角,确保这些分配出来的数据还落在 cache 友好的布局上。

## 1 · 虚拟内存:你看到的不是 RAM

你写 `let mut v: Vec<u8> = Vec::with_capacity(4096);`,你以为你"申请了 4 KB 的内存"。错了。你申请的是一段**虚拟地址空间**——一个 48 位的指针区间,内核把它登记到你进程的页表里,标成"这段地址合法,属性是读写匿名页"。

物理 RAM 此时根本没动。等你第一次 `v[0] = 42;`,CPU 把 `0x7f...1234` 这个虚拟地址送到 MMU,MMU 查页表——发现这一页还没有物理页帧,触发 **page fault**。内核在 page fault handler 里,从 buddy allocator(内核里的!)分一个 4 KB 物理页,填进页表,然后返回用户态重试那条 store。这时你才真正用上了一个 4 KB 的 DRAM。

这是**地址空间(address space)和内存(memory)的分离**:内核给你的是"地址的承诺",不是字节本身。字节是在你 touch 它的瞬间才物理存在的。理解这一点的直接收益是 **lazy allocation**——你可以 `mmap` 1 GB 的地址空间,只要你只 touch 其中 100 MB,只有 100 MB 占物理 RAM。

第二个收益是**隔离**。每个进程有自己独立的页表,你看到的 `0x401000` 和我看到的 `0x401000` 物理上是不同的 RAM 页。一个进程越界写,page fault handler 一看权限不对,直接 SIGSEGV,绝不会改到另一个进程的内存。

第三个收益是**保护**。页表项有 read/write/execute 三位。内核把代码段标成 r-x、栈标成 rw-、guard page 标成 `---`,任何违反权限的访问立即被硬件拦截。这是 Rust 借用检查之外的、硬件级的边界。

第四个收益——和这一篇最相关的——是**地址空间几乎免费**。48 位有效虚拟地址,Linux 用户态拿到 128 TB 的地址空间(高地址一半给内核)。你的笔记本 16 GB RAM,但你的程序能"看到"128 TB。绝大多数没映射,你只是把"将来可能要用的地址段"先 reserve 下来。**reserve 是免费的,只有 commit 才花钱(物理 RAM)**。这是 mmap 的精髓。

`pmap $(pidof your_game)` 或 `cat /proc/PID/maps` 能看到你进程当前的全部虚拟内存布局——哪些段是匿名、哪些是文件映射、哪些 huge page、哪些还没 commit(`pmap` 里 `RSS` 列就是已 commit 的量)。第一个练习就该是:`pmap -x $(pidof firefox)`,你会看到 RSS 远小于虚拟大小,那就是 lazy allocation 的证据。

## 2 · mmap:Unix 拿地址空间的 syscall

`mmap` 是 Unix 那个"魔法 syscall"——它既是 `malloc` 大块分配的底层,也是文件 IO 的另一种姿势,还是 huge page、shared memory、guard page 的统一入口。它的签名在 man page 里很长,但本质就一句话:**在调用进程的虚拟地址空间里,创建一段新的映射**。

```c
void *mmap(void *addr, size_t length, int prot, int flags,
           int fd, off_t offset);
```

`addr` 通常是 `NULL`(让内核选地址),`length` 是想要的大小(会向上对齐到页),`prot` 是权限(`PROT_READ | PROT_WRITE` 等),`flags` 决定映射类型,`fd` 和 `offset` 决定是否映射文件。返回值是这段虚拟地址的起始指针。

**四种典型用法,用 flags 区分**。

第一种是匿名映射(anonymous),`flags = MAP_PRIVATE | MAP_ANONYMOUS`,`fd = -1`。这就是"我要一块内存"。glibc 的 `malloc` 对大于 128 KB 的请求就走这条路——直接 `mmap` 一个匿名段。

第二种是文件映射(file-backed),`fd` 指向一个打开的文件。访问这段虚拟地址 = 读写文件,内核的 page cache 自动做缓存。`MAP_PRIVATE` 是 COW(copy-on-write,你写的时候才复制一份私有页),`MAP_SHARED` 是把改动写回文件(或共享给其他进程)。你在 [phase-0/24-memory-foundation.md](../../phase-0/24-memory-foundation.md) 的 §7 已经见过这个用法——把 1 GB 关卡文件 mmap,玩家走过去时内核按需 page in。

第三种是 huge page。在 `flags` 里加 `MAP_HUGETLB`,或者用 `madvise(MADV_HUGEPAGE)` 提示内核 THP(transparent huge pages)。一页从 4 KB 变成 2 MB,TLB coverage 翻 512 倍。对一个遍历 100 MB 数据的热循环,TLB miss 数能从 25600 降到 50。但 huge page 有代价——内核要找连续 2 MB 物理页,可能触发 compaction,延迟尖峰。Redis、Cassandra 都建议关掉 THP。

第四种是 reserve-only。`mmap` 一个巨大区域,`prot = PROT_NONE`——内核只登记地址段,完全不 commit。后面用 `mprotect` 把需要的部分改成可读写,这才会触发 commit。Windows 上叫 `MEM_RESERVE` vs `MEM_COMMIT`,Linux 上用 `PROT_NONE` 模拟。这正是写 stack allocator、guard page、虚拟内存池的标准技巧。

### 2.1 reserve vs commit:一句话的区别

记住这两个动词的精确含义。**reserve(保留)** 是在页表里登记一段虚拟地址,告诉内核"这段地址合法,但我现在不要 RAM"。开销近乎为零——内核只是把这段加到 VMA(virtual memory area)链表里,不分配物理页。

**commit(提交)** 是真正让 RAM 可用。可以是显式的——`mprotect(PROT_READ|PROT_WRITE)`——也可以是隐式的——你往 reserve 的页里写一个字节,触发 page fault,内核被迫 commit。一旦 commit,4 KB 物理页就归你了,即使你只用其中 1 字节。

为什么这件事重要?因为**碎片化和过度 commit 的根源在这里**。如果你 reserve 1 GB 然后 commit 100 MB 散布在这 1 GB 里(每 4 KB commit 一个页,中间留空),物理页表项就散得乱七八糟——这就是内部碎片的一种。分配器的工作之一,就是把 commit 的页紧凑地组织起来,既省 TLB 又省 cache(详见 [memory-layout-for-cache.md](memory-layout-for-cache.md))。

### 2.2 overcommit:内核和你的一场赌局

Linux 默认 `vm.overcommit_memory = 0`(heuristic)或 `1`(always overcommit)。意思是:**内核允许你 reserve 远超物理 RAM 的地址空间**。

为什么?因为大量程序 reserve 了内存但没全用。Go runtime、Java JVM、PostgreSQL 都会 reserve 几 GB 的虚拟地址空间,实际 RSS 只有几百 MB。如果内核要求 reserve 必须有物理 RAM 兜底,这些程序一启动就 OOM。

代价是——如果所有进程**同时**真用了它们 reserve 的全部内存,物理 RAM 不够,内核只能 OOM killer 杀进程。Linux 的 `oom_score` 就是用来挑"谁占用最多、谁最该杀"的。

对游戏服务器,通常的做法是:**关 swap**(避免 swap 抖动延迟)+ **设 `overcommit_memory = 2` + `overcommit_ratio`** 严格模式,让 reserve 必须有物理 RAM 兜底。但单机游戏客户端,heuristic 模式足够——你 reserve 1 GB 地址空间,实际只用 500 MB,内核帮你兜着。

### 2.3 Rust 里直接调 mmap

最稳的姿势是 `libc` crate 或 `mmap` / `memmap2` crate。下面这段 Rust 代码 reserve 1 GB 虚拟地址空间,只 commit 头部一个 4 KB 页:

```rust
use libc::{mmap, mprotect, munmap, PROT_NONE, PROT_READ, PROT_WRITE,
           MAP_PRIVATE, MAP_ANONYMOUS};
use std::ptr;

const RESERVE: usize = 1 << 30; // 1 GB
const COMMIT:   usize = 1 << 12; // 4 KB

unsafe {
    let base = mmap(
        ptr::null_mut(),
        RESERVE,
        PROT_NONE,                       // 先 reserve 不可访问
        MAP_PRIVATE | MAP_ANONYMOUS,
        -1,
        0,
    );
    assert!(!base.is_null() && base as isize != -1);

    // 把头部 4 KB 改成可读写 —— 触发 commit
    let rc = mprotect(base, COMMIT, PROT_READ | PROT_WRITE);
    assert_eq!(rc, 0);

    // 现在可以写
    let p = base as *mut u8;
    *p = 42;

    // 后面的页还是 PROT_NONE,写就 SIGSEGV —— 这就是 guard page 的原理
    // *(p.add(4096)) = 99;  // ← 会崩

    munmap(base, RESERVE);
}
```

跑一下,用 `pmap -x $$` 看你的进程:`KADDR` 列整段 1 GB 都是合法地址,但 `RSS` 只有 4 KB——那 1 GB 全是 reserve。这就是虚拟内存给你"用不完的地址空间"。

## 3 · Guard page:让越界当场炸掉

你的 HH 项目里,你给某个子系统手写了一个固定大小的环形 buffer。你写 `for i in 0..1024 { buf[i] = data; }`,但 `buf` 只有 1024 字节,index 0..1024 越界一位。`buf[1024]` 写到哪儿去了?

如果 `buf` 是栈上一个数组,你写到了栈帧下面的另一个局部变量,或者 ret 地址——这叫 **stack buffer overflow**,经典 CVE 漏洞。游戏里更常见的是:你写到了隔壁 `Enemy` 的字段,程序继续跑,几十帧后才在毫不相关的地方崩。Debug 这种 bug 极其痛苦。

**Guard page(守护页)** 就是修这个的。你在 buffer 末尾紧挨着放一个 `PROT_NONE` 的页,任何越界写——CPU 立即 page fault,内核 SIGSEGV,你当场知道哪里越界。**用硬件级精度检测内存边界**,不需要 valgrind、不需要 ASAN,毫秒级。

这是 stack overflow 检测的标准机制。Linux 给每个线程的栈底放一个 guard page(默认 4 KB,可以调 `ulimit -s` 和 `kernel.guardpage_size`)。线程递归过深,栈指针走到 guard page,程序立刻死——而不是悄悄踩到隔壁线程的栈。

在游戏里,你可以给每个 entity pool、每个 per-thread scratch arena、每个环形 buffer 主动挂 guard page。具体做法:用 §2.3 那个 reserve/commit 模式,reserve 的整段尾部那一页保持 `PROT_NONE`,前面 commit。pool 写出界 → 写到 guard page → 当场 crash,backtrace 精确指向那一行。

下面是一个带 guard page 的 stack allocator 雏形:

```rust
use libc::{mmap, mprotect, munmap, PROT_NONE, PROT_READ, PROT_WRITE,
           MAP_PRIVATE, MAP_ANONYMOUS};
use std::ptr::null_mut;

pub struct GuardedStack {
    base: *mut u8,         // commit 区起点
    capacity: usize,       // commit 区大小
    offset: usize,
    raw: *mut u8,          // mmap 返回的整段(包含末尾 guard)
    raw_len: usize,        // capacity + 1 page
}

const PAGE: usize = 4096;

impl GuardedStack {
    pub fn new(capacity: usize) -> Self {
        let raw_len = capacity + PAGE;          // 多一页当 guard
        let raw = unsafe {
            mmap(null_mut(), raw_len, PROT_NONE,
                 MAP_PRIVATE | MAP_ANONYMOUS, -1, 0)
        } as *mut u8;
        assert!(!raw.is_null());
        // 只 commit 前 capacity 字节,最后一页保持 PROT_NONE
        unsafe {
            mprotect(raw as *mut _, capacity, PROT_READ | PROT_WRITE);
        }
        Self { base: raw, capacity, offset: 0, raw, raw_len }
    }

    pub fn push(&mut self, size: usize, align: usize) -> *mut u8 {
        let aligned = (self.offset + align - 1) & !(align - 1);
        if aligned + size > self.capacity {
            return std::ptr::null_mut(); // 分配失败,返回 null
        }
        let p = unsafe { self.base.add(aligned) };
        self.offset = aligned + size;
        p
    }

    pub fn pop_to(&mut self, mark: usize) { self.offset = mark; }

    pub fn mark(&self) -> usize { self.offset }
}

impl Drop for GuardedStack {
    fn drop(&mut self) {
        unsafe { munmap(self.raw as *mut _, self.raw_len); }
    }
}
```

如果某次 `push` 因为对齐偏差或者算错 size,写到 `base + capacity` 之后,**那一页就是 PROT_NONE,立即 SIGSEGV**。你的 ASAN 都没这么快。代价是多一页(4 KB)的虚拟地址空间,但因为是 reserve 而非 commit,这 4 KB 不占物理 RAM。

## 4 · 分配器三件套:stack / pool / buddy

全局 allocator 是"通用"——它要应付任意大小、任意生命周期、任意线程的混合请求。代价是慢、有碎片。游戏的请求 pattern 极其规则,可以量身定做三个分配器,分别对应三种典型场景。这一节是这篇 deep-dive 的肉。

### 4.1 Stack allocator:LIFO,适合 per-frame 临时

你已经在 [arena-allocator.md](arena-allocator.md) 看过 bump allocator 的核心:一个 `offset` 指针,alloc 时往前推,reset 时归零。**stack allocator** 是它的稍微灵活一点的版本——支持 **push/pop 配对**,可以中间 pop 掉一段,只要满足 LIFO(后进先出)。

为什么是 LIFO?因为只有 LIFO 才能保证 "pop 之后,剩下的内存没有 hole"。如果你 pop 掉中间一段,前后两段还在用,中间就形成一个碎片洞——这就退化成通用 allocator 的难题了。LIFO 等于"嵌套作用域":函数 A push 100 字节,调函数 B push 200 字节,B 返回时 pop 到 100,A 自己的 100 字节完全没动。

典型用法是 per-frame 临时数据。Casey 在 HH Day 095 把 transient memory 做成 stack——每帧开始 mark 一个 offset,渲染子系统 push 一堆临时 buffer,粒子系统 push,物理系统 push,帧末 pop 回 mark。**整帧零次 `free` 调用**,只是改一个 `usize`。这就是 [phase-0/24-memory-foundation.md](../../phase-0/24-memory-foundation.md) §8.4 所说的"frame arena"的精确实现。

```rust
pub struct StackAlloc {
    buf: *mut u8,
    len: usize,
    offset: usize,
}

impl StackAlloc {
    pub fn push<T>(&mut self, val: T) -> *mut T {
        let size = std::mem::size_of::<T>();
        let align = std::mem::align_of::<T>();
        let aligned = (self.offset + align - 1) & !(align - 1);
        assert!(aligned + size <= self.len, "stack overflow");
        let p = unsafe { self.buf.add(aligned) } as *mut T;
        unsafe { std::ptr::write(p, val); }
        self.offset = aligned + size;
        p
    }

    pub fn push_marker(&self) -> usize { self.offset }

    pub fn pop_to(&mut self, mark: usize) {
        // 注意:pop 之后,前面 [0, mark) 的数据是"还活着"的
        // [mark, offset) 的指针全部失效
        debug_assert!(mark <= self.offset);
        self.offset = mark;
    }
}
```

它的优势:**alloc 是 O(1),只是几次整数运算 + 一次指针写**。比 `malloc` 快 100 倍。碎片化是**零**——内存里没有任何洞。

它的劣势:**不能单独释放中间对象**。如果你 push 了 A、B、C,想释放 B,不行——只能 pop 到 A 之前,把 B 和 C 一起丢。所以 stack allocator 只适合"生命周期严格嵌套"的数据。

游戏的 per-frame 临时数据完美匹配——一帧之内分配,帧末整体 pop,生命周期就是一帧。

### 4.2 Pool allocator:固定大小,O(1),无碎片

stack 解决了"一帧之内",但有些对象的生命周期不是按帧划界的。**子弹**——开火时创建,3 秒后击中目标销毁,可能跨 180 帧。**敌人**——出生后活几十秒。**网络包缓冲**——发完就释放,时机随机。

这些对象有个共同点:**大小固定**。子弹都是 `struct Bullet { ... }` 共 64 字节,敌人都是 256 字节。固定大小是关键——它让分配器可以做到 O(1) 且零碎片。

**Pool allocator(对象池)** 的核心思路:预分配一大块 `N * sizeof(T)` 的内存,切成 N 个等大 slot。每个 slot 要么 occupied(装着一个 T),要么 free(空闲)。free 的 slot 用一个**侵入式链表**串起来——slot 自己的内存当链表节点,不额外占空间。

```rust
pub struct Pool<T> {
    storage: *mut u8,
    capacity: usize,
    free_head: *mut FreeNode,
    _marker: std::marker::PhantomData<T>,
}

// 一个 slot 闲着时,它的前 8 字节存"下一个 free slot 的指针"
// 装数据时,这 8 字节被 T 的字段覆盖
struct FreeNode {
    next: *mut FreeNode,
}

impl<T> Pool<T> {
    pub fn new(capacity: usize) -> Self {
        let size = std::mem::size_of::<T>().max(std::mem::size_of::<*mut u8>());
        let align = std::mem::align_of::<T>().max(std::mem::align_of::<*mut u8>());
        let layout = std::alloc::Layout::from_size_align(size * capacity, align).unwrap();
        let storage = unsafe { std::alloc::alloc(layout) };
        assert!(!storage.is_null());

        // 把所有 slot 串成 free list
        let mut head: *mut FreeNode = std::ptr::null_mut();
        for i in (0..capacity).rev() {
            let slot = unsafe { storage.add(i * size) } as *mut FreeNode;
            unsafe { (*slot).next = head; }
            head = slot;
        }

        Self {
            storage, capacity, free_head: head,
            _marker: std::marker::PhantomData,
        }
    }

    pub fn alloc(&mut self) -> Option<*mut T> {
        if self.free_head.is_null() {
            return None;
        }
        let slot = self.free_head as *mut u8;
        self.free_head = unsafe { (*(self.free_head)).next };
        Some(slot as *mut T)
    }

    pub fn dealloc(&mut self, ptr: *mut T) {
        let node = ptr as *mut FreeNode;
        unsafe { (*node).next = self.free_head; }
        self.free_head = node;
    }
}
```

**为什么这是 O(1)**?alloc 是"摘链表头"——一次指针赋值。dealloc 是"插链表头"——两次指针赋值。没有任何搜索、没有合并、没有 size class 查找。

**为什么零碎片**?所有 slot 等大。分配一个用掉一个,释放一个补回一个,**没有 hole**。这是"等大"这一约束带来的礼物——通用 allocator 慢,根本原因是它要应付"任意大小",大小不一就必然产生碎片。pool 把这个难题直接绕过。

**侵入式 free list 的妙处**:slot 不用时,它就是 8 字节的链表节点;使用时,这 8 字节被 T 的前 8 字节覆盖。零额外内存开销。

这就是 Casey 用的 "free list" pattern,也是 `slotmap`、`generational_arena` 的底层(它们额外加了 generation 计数防 stale handle,见 [arena-allocator.md](arena-allocator.md) §6)。游戏的 entity 系统、粒子系统、子弹系统几乎全是 pool。

但 pool 有个隐藏的好处,直接和 cache 性能挂钩——slot 地址**稳定**。一个 Bullet 的指针拿到手,它不会因为别的 Bullet 释放而 move。这对 cache 友好(详见 [memory-layout-for-cache.md](memory-layout-for-cache.md))——稳定的地址意味着你能用裸指针做 SIMD 遍历,不用担心 `Vec` grow 导致 reallocation。而且所有 slot 在内存里连续,prefetcher 帮你。

### 4.3 Buddy allocator:2 的幂,快速合并

stack 解决嵌套作用域,pool 解决固定大小。但有些场景大小不固定——比如 GPU 资源管理(texture 大小不一)、音效 buffer(时长不一)、关卡数据(struct 大小各异)。这种"任意大小但需要快速合并"的场景,**buddy allocator** 登场。

buddy 的思路:把一大块内存按 2 的幂切分。比如 1 MB,切成两个 512 KB 的"buddy"。请求 400 KB?向上取整到 512 KB,分一个 buddy。请求 100 KB?把另一个 512 KB 再切成两个 256 KB,分一个;再要 50 KB,把另一个 256 KB 切成两个 128 KB,分一个。

释放时,buddy allocator 检查被释放的块的"buddy"(它的孪生兄弟,地址 XOR 一个 size bit)是否也 free。如果 free,**合并**成一个更大的块,递归向上。这就是 **O(log N) 的快速合并**。

```
1 MB
├─ 512K A          (allocated: 400K 请求)
└─ 512K B
   ├─ 256K B1      (allocated: 100K)
   ├─ 256K B2
   │   ├─ 128K B2a (allocated: 50K)
   │   └─ 128K B2b (free)
   └─ (B 已被切,不能再算 512K)
```

为什么合并快?因为 buddy 关系是地址位运算就能算出来的——`buddy_addr = block_addr XOR size`。一次 XOR,看 buddy 在不在 free list,在就合并。通用 allocator 合并相邻空闲块要扫 descriptor 链表,buddy 不用。

代价是**内部碎片**——400 KB 请求实际占用 512 KB,浪费 28%。100 KB 占 128 KB,浪费 28%。最坏情况下,1 字节请求也占一整页。但相比"无碎片但只支持固定大小"的 pool,buddy 是"少量碎片但支持任意大小"的折中。

buddy 在游戏里典型的应用:**GPU 显存管理**(Vulkan 的 `vkAllocateMemory`、D3D12 的 heap)、**音效混音池**、**关卡 asset 加载**(每个 asset 大小不同,但希望 unload 时能合并)。Linux 内核自己用的 page allocator 就是 buddy——你 `mmap` 拿到的物理页,就是从 buddy 来的。

实现 buddy 比 stack 和 pool 都复杂,这里不贴完整代码(它会占这一篇的一半篇幅),核心数据结构是:每个 size class 一个 free list(数组,索引 0 = 最小块,索引 max = 整块),alloc 时从合适 size class 取,不够就分裂上一阶;dealloc 时递归合并。

工业实现可以看 `buddy-alloc` crate 或者读 Linux 内核 `mm/page_alloc.c`。

## 5 · 为什么这事关你的游戏帧时间

讲完了机制,让我们把镜头拉回 Day 150 那个 50 ms 的 `Box::new` 灾难。

你把十万发子弹从 `Vec<Box<Bullet>>` 改成 `Pool<Bullet>`。子弹出生时 `pool.alloc()`,击中目标时 `pool.dealloc()`。你重测 microbench——从 50 ms 降到 0.3 ms。提速 150 倍。

为什么这么夸张?三个原因叠加。

第一,**alloc 本身的成本**。`Box::new` 走 jemalloc/mimalloc(取决于你的 `#[global_allocator]`),要查 size class、要打 thread-local cache 锁、可能要 fallback 到 arena lock。Pool 是一次链表头指针赋值,5 ns 量级。十万次差距就是 50 ms vs 0.5 ms。

第二,**碎片化导致的 cache 退化**。`Box<Bullet>` 的每个 Box 是独立分配,地址在堆上随机散布,遍历所有 Bullet 时每个都 cache miss。Pool 的 Bullet 在一块连续内存里,遍历时 prefetcher 帮你拉。详见 [memory-layout-for-cache.md](memory-layout-for-cache.md) 的 §4——AoS vs SoA 那 80 倍差距,本质上也是地址连续性问题。

第三,**地址稳定性**。Pool 释放一个 Bullet 不影响其他 Bullet 的地址。`Vec<Bullet>` grow 时会 reallocate,所有 `&Bullet` 指针全失效——Rust 编译器会拦住你 borrow checker 错误,但运行时如果用裸指针就崩。Pool 不 grow,指针稳定,你可以在系统之间共享 `*const Bullet`。

把 stack allocator 用于 per-frame 临时数据,把 pool 用于 entity / 粒子 / 子弹,把 buddy(或者大块 mmap)用于 asset / GPU 资源——这就是工业级游戏的内存架构。Casey 在 HH 里手写的 `MemoryArena` 就是 stack + 大块 reserve 的组合。Unreal 的 `FMemory` 有 `FMallocBinned`(buddy)、`FMallocTLS`(thread-local pool)。Unity 的 DOTS 用 chunk-based ECS,本质上是一种 pool。

**选择正确的 allocator 是最大的帧时间杠杆之一**,仅次于算法复杂度和 cache 友好布局。

## 6 · Rust:替换全局 allocator,接入 allocator_api

讲完了底层机制,这一节讲 Rust 给你的上层旋钮。

### 6.1 GlobalAlloc trait:替换全局 allocator

Rust 的 `Box::new` / `Vec::push` / `String::from` 全部走 `std::alloc::GlobalAlloc`。这个 trait 有两个核心方法:`alloc` 和 `dealloc`。你可以实现自己的 allocator,挂到 `#[global_allocator]`,从此所有默认分配走你的代码。

最常见的两个用途:**换一个更快的实现**(jemalloc、mimalloc),或者**包一层 instrumentation**(计数、追踪、日志)。

```rust
use std::alloc::{GlobalAlloc, Layout, System};

struct CountingAllocator {
    inner: System,
    allocs: std::sync::atomic::AtomicU64,
    bytes:  std::sync::atomic::AtomicU64,
}

unsafe impl GlobalAlloc for CountingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        self.allocs.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        self.bytes.fetch_add(layout.size() as u64,
                             std::sync::atomic::Ordering::Relaxed);
        self.inner.alloc(layout)
    }
    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        self.inner.dealloc(ptr, layout);
    }
}

#[global_allocator]
static GLOBAL: CountingAllocator = CountingAllocator {
    inner: System,
    allocs: std::sync::atomic::AtomicU64::new(0),
    bytes:  std::sync::atomic::AtomicU64::new(0),
};
```

挂上之后,在游戏循环每帧打印 `GLOBAL.allocs.load(...)`,你能看到一帧做了多少次分配。如果数字大得吓人(几万次),你就知道该上 arena / pool 了。这是定位"哪段代码在分配"的第一步——`heaptrack` / `dhat` 给更细粒度,但全局计数是免费的哨兵。

### 6.2 allocator_api:每个容器选自己的分配器

`#[global_allocator]` 有个根本限制——它是**全局**的。一旦挂上,整个进程的所有 `Box` / `Vec` 都走它。但你想让某些 `Vec` 走 arena,某些走 pool,某些走 system,怎么办?

Rust nightly 的 `allocator_api` feature 就是干这个的。它让 `Box`、`Vec`、`VecDeque` 等容器接受一个类型参数 `A: Allocator`,每个容器实例可以用不同的 allocator。

```rust
#![feature(allocator_api)]
use std::alloc::Allocator;

fn frame_work<S: Allocator>(scratch: &S) {
    // 这个 Vec 临时分配走 scratch allocator(比如 bump arena)
    let mut tmp: Vec<u32, &S> = Vec::new_in(scratch);
    for i in 0..1024 { tmp.push(i); }
    // tmp 离开作用域时,调 scratch.dealloc —— 对 bump allocator 就是 no-op
    // 数据在 scratch 的内存里,帧末 reset 统一回收
}
```

这个 API 在 stable Rust 还没全量稳定,但 `bumpalo::collections::Vec` 提供等价功能稳定可用——一个 `Vec` 但分配在 `bumpalo::Bump` 里。`bumpalo::boxed::Box` 同理。

工业级 Rust 游戏引擎(bevy、Fyrox)大量用 allocator_api 让"热路径的容器走 arena,冷路径走 system"。这是把"不要在 hot loop 分配"从口号变成可执行规则的姿势。

### 6.3 hot-loop 不分配:纪律

不管你的 allocator 多快,**不分配永远是最快的**。`alloc` 再快也要一次 atomic 或一次指针写,而编译器优化掉一个寄存器赋值是免费的。游戏的"hot loop"——每帧跑几百万次的循环——里**任何 alloc 都是 bug**。

怎么落实这个纪律?三件事。

第一,**profiler 找出 hot loop 里的 alloc**。挂一个 counting allocator,profile 看哪一帧 alloc 数最多、哪个调用栈。heaptrack 的 flamegraph 一眼能看出来。

第二,**把 alloc 移到循环外**。`for x in &data { let mut buf = Vec::new(); ... }` 改成 `let mut buf = Vec::with_capacity(N); for x in &data { buf.clear(); ... }`。`clear()` 不释放内存,只重置 len。

第三,**用 arena / pool 预分配**。per-frame 数据走 stack allocator,entity 走 pool。这两件事这一篇都讲过了。

Casey 在 HH 里反复强调 "no allocations in the inner loop",这不是口号,是写在他自己 memory arena 设计里的硬约束——`PushSize` / `PushStruct` 之外的分配,他都在调试 build 加 assert 拦截。Rust 让这件事更容易:你可以用 type system 标记一个"no-alloc context",任何 `Box::new` 在里面都是编译错误。

## 7 · 跨域关联:这一篇和其他 deep-dive 怎么咬在一起

讲完了虚拟内存和分配器,回头看看它在你的知识网里的位置。

**和 [memory-layout-for-cache.md](memory-layout-for-cache.md) 的关系**:分配器决定数据**在哪个地址**,地址决定数据**进哪个 cache line**。Pool allocator 让 entity 在内存里连续,直接喂给 prefetcher。stack allocator 让一帧的临时数据紧凑堆叠,不浪费 cache line。这俩是同一件事的两面——分配是"位置",cache 是"位置带来的延迟"。学完这篇,你应该能解释为什么 `Vec<Entity>` 比链表快、为什么 pool 比 `Box` 快——底层都是地址连续性。

**和 [arena-allocator.md](arena-allocator.md) 的关系**:那一篇讲了 arena 的 API 层(bumpalo、typed-arena、slotmap),这一篇讲了 arena 底下那层(mmap、reserve/commit、guard page)。两者合起来才是完整的"游戏内存架构"。Casey 的 HH arena 就是这两篇内容的总和。

**和 [phase-0/24-memory-foundation.md](../../phase-0/24-memory-foundation.md) 的关系**:那篇是地基——虚拟地址、页表、TLB、cache、NUMA。这一篇是地基之上专门讲"分配器"那一节(原篇 §8)的深度展开。

**和 [phase-0/25-concurrency-foundation.md](../../phase-0/25-concurrency-foundation.md) 的关系**:多线程下,allocator 是竞争热点。`malloc` 内核里的 arena lock、jemalloc 的 thread cache、lock-free pool 的设计——都依赖那一篇讲的内存序、原子操作、MESI 协议。如果你写一个多线程的 entity pool,要么 thread-local pool(每线程一个,无竞争),要么 lock-free free list(`AtomicPtr` CAS)。前者用 `crossbeam::CachePadded` 避免 false sharing,后者用 hazard pointer 或 epoch reclamation 防 use-after-free。这两个话题在 [lock-free-programming.md](lock-free-programming.md) 里有详细展开。

**和 [09B-2-subsystems-modules-plugins.md](../../phase-9/09B-2-subsystems-modules-plugins.md) 的关系**:游戏引擎的子系统划分,本质上也是内存所有权划分——render 模块用自己的 arena,audio 用自己的 pool,physics 用自己的 scratch。模块边界 = allocator 边界。读那一篇时,你会发现"每个子系统自管内存"是工业引擎的标准设计。

## 8 · 在你 HH 项目里动手(做中学红线)

讲完了理论,这一节给你一条具体的落地路径。**强烈建议完整做完——这是把这篇内容内化的唯一方式**。

**步骤 1**:在你的 HH 项目里加一个 `mem` 模块,用 `libc::mmap` reserve 64 MB 虚拟地址空间(匿名、`PROT_NONE`)。用 `mprotect` commit 前 32 MB 作为 pool 区,中间留一页 `PROT_NONE` 当 guard page,后 32 MB 当 stack 区。`pmap -x $(pidof your_game)` 验证 RSS 远小于 64 MB——这是 reserve/commit 的物理证据。

**步骤 2**:实现 §4.2 的 `Pool<Bullet>`(假设你的 Bullet 是 64 字节),capacity = 50000,放在 pool 区。把现有的 `Vec<Box<Bullet>>` 全部替换成 `Pool<Bullet>` + `pool.alloc()` / `pool.dealloc()`。运行游戏,确认功能不变。

**步骤 3**:在 pool 区末尾的 guard page 上,故意写一个 bug——在 `alloc()` 里把 size 算大一位。运行游戏,确认 SIGSEGV 触发,`backtrace` 精确指向那一行。修回 bug,验证 guard page 在正常情况下不会误触发。

**步骤 4**:在 stack 区实现 §4.1 的 `StackAlloc`,作为 per-frame scratch。把你渲染子系统里所有"每帧临时分配的 Vec"改成 `Vec::new_in(&scratch_bump)`(用 bumpalo)或自定义 `StackVec`。每帧开始 `scratch.reset()`。

**步骤 5**:挂一个 §6.1 的 `CountingAllocator` 当 `#[global_allocator]`,每秒打印一次 alloc 计数。目标是 hot loop 里**零增长**——任何增长都说明你漏了某个 alloc。修到零为止。

**步骤 6**:用 `cargo flamegraph` profile。对比改造前后的帧时间。你应该看到 30-50% 的帧时间下降(具体数字取决于你原来 alloc 多狠)。

**步骤 7**:用 `perf stat -e page-faults,LLC-load-misses` 看 page fault 和 cache miss。改造后 page fault 应该接近零(都在 reserve 区里),LLC-load-misses 显著降低(entity 在连续内存里)。

做完这七步,你会**亲手感受到**"系统层"——下面是 mmap 和页表,中间是你写的 pool / stack,上面是 Rust 的 ownership。这一层穿透,是 game engine programmer 和 application programmer 的分水岭。

## 9 · 练习

### Lv1 · 概念辨析

**题**:解释为什么 reserve 1 GB 虚拟地址空间,进程的 RSS 几乎不增长,但物理 RAM "理论上"已经"承诺"给这个进程。在你的 Linux 上跑一段 reserve 1 GB 但只 commit 4 KB 的代码,用 `pmap -x` 和 `/proc/PID/status` 的 `VmRSS` / `VmSize` 验证。提交:代码 + 两张截图 + 200 字解释 reserve/commit 的区别。

**完成标准**:能清晰区分 VmSize(虚拟空间)和 VmRSS(物理占用),解释为什么差异大。

### Lv2 · 动手实践

**题**:用 Rust 实现 §4.2 的 `Pool<T>`,加上 `slotmap` 风格的 generation 计数(每个 slot 一个 u32 generation,dealloc 时 +1)。Key 类型是 `(index: u32, generation: u32)`。验证:alloc 一个 key,dealloc,再 alloc 复用同一 slot 但 generation 不同,旧 key 查不到。这是 entity handle 的标准实现。

**完成标准**:单元测试覆盖 stale key 检测、池满回退、并发场景下单线程正确性。

### Lv3 · 迁移设计

**题**:你的 HH 项目里挑一个子系统(粒子、AI、物理),profile 它当前每帧的 alloc 数(用 counting allocator)。写一份 300 字设计文档:这个子系统的对象生命周期属于哪种 pattern(短命 per-frame / 中等生命周期 entity / 长生命周期 asset)?应该用 stack / pool / 哪种?给迁移计划,执行,对比前后帧时间。

**完成标准**:有 before/after 的 flamegraph 和帧时间数字,帧时间至少降 15%。

### Lv4 · 开源贡献

**题**:读 Linux 内核 `mm/mmap.c` 的 `do_mmap` 函数,跟踪一次 `mmap(NULL, len, PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANONYMOUS, -1, 0)` 从 syscall 入口到 VMA 挂载的完整路径。然后读 `mm/page_alloc.c` 的 buddy allocator(`__alloc_pages_nodemask`),理解 page fault 时如何从 buddy 拿一个物理页。在 2000 字以内的笔记里画出从 `mmap` 到 page commit 的完整调用栈。

**完成标准**:能解释 `vm_area_struct`、`page`、`mm_struct` 三个数据结构的关系,能指出 `MAP_POPULATE` 标志如何改变 lazy allocation 行为。

## 10 · 延伸阅读

本仓库本地资料:
- [phase-0/24-memory-foundation.md](../../phase-0/24-memory-foundation.md) — 虚拟内存、cache、分配器全景
- [phase-0/25-concurrency-foundation.md](../../phase-0/25-concurrency-foundation.md) — 多线程下的原子操作和内存序
- [arena-allocator.md](arena-allocator.md) — arena allocator 的 API 层(bumpalo、typed-arena、slotmap)
- [memory-layout-for-cache.md](memory-layout-for-cache.md) — 分配器决定地址,地址决定 cache 性能
- [lock-free-programming.md](lock-free-programming.md) — 多线程分配器的底层(lock-free free list、hazard pointer)
- [09B-2-subsystems-modules-plugins.md](../../phase-9/09B-2-subsystems-modules-plugins.md) — 模块边界 = 内存边界

外部稳定 URL:
- MIT 6.S081 Operating Systems(Lecture on virtual memory):https://pdos.csail.mit.edu/6.S081/2020/lecture/l5-pg.txt
- CSAPP Chapter 9(Virtual Memory):https://csapp.cs.cmu.edu/
- Drepper, What Every Programmer Should Know About Memory:https://people.freebsd.org/~lstewart/articles/cpumemory.pdf
- Linux mm subsystem source:https://github.com/torvalds/linux/tree/master/mm
- Linux man page mmap(2):https://man7.org/linux/man-pages/man2/mmap.2.html
- Linux man page overcommit:https://www.kernel.org/doc/Documentation/vm/overcommit-accounting
- Rust Allocator API RFC:https://rust-lang.github.io/rfcs/1398-kinds-of-allocators.html
- Knuth, The Art of Computer Programming Vol 1 §2.5(Dynamic storage allocation):经典 buddy / pool 论述
- Bonwick, The Slab Allocator(UMA——Solaris 内核的对象池):http://www.groklaw.net/pdf/OSSPatentCitations/SunMicrosystems/SlabAllocator.pdf

真实开源源码:
- Linux `mm/page_alloc.c`(buddy allocator):https://github.com/torvalds/linux/blob/master/mm/page_alloc.c
- Linux `mm/mmap.c`(mmap 实现):https://github.com/torvalds/linux/blob/master/mm/mmap.c
- `bumpalo` Rust arena:https://github.com/fitzgen/bumpalo
- `buddy-alloc` Rust crate:https://github.com/jjyr/buddy-alloc
- `slotmap` generational pool:https://github.com/orlp/slotmap
- Casey Muratori, Handmade Hero Day 095(Transient memory / arena):https://guide.handmadehero.org/code/day095/
