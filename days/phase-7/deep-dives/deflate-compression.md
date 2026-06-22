# DEFLATE 完全解:LZ77 + Huffman,RFC 1951 逐字节走读

> PNG 用 DEFLATE 压缩。zip 用 DEFLATE。gzip 用 DEFLATE。HTTP/1.1 的 gzip 编码、SSH 协议的压缩、Java JAR、Python .pyc 缓存——背后都是同一个算法。DEFLATE 是 1990 年代设计的、至今仍是最广泛使用的通用压缩算法。本文从 RFC 1951 逐字节讲解,让你能在 Rust 里手写一个能跑的 DEFLATE 解码器。

## 0 · 为什么 DEFLATE 这么重要

1990 年代 Phil Katz 写了 PKZIP(后来变成 zip 格式),需要一个快速、免费、有效的压缩算法。他设计了 DEFLATE——结合两个经典算法:

1. **LZ77**(Lempel-Ziv 1977):找重复的字节序列,用"距离 + 长度"对表示
2. **Huffman 编码**:用变长位编码,常见符号用短码,罕见符号用长码

DEFLATE 在两者之间做了巧妙的设计:**LZ77 找重复,Huffman 把结果按统计压更紧**。结果是工业级的压缩比 + 解压速度,直到今天仍是网络和归档的主流。

为什么 30 年来没人替换 DEFLATE?

1. **公共领域**:Phil Katz 把 DEFLATE 算法放进了公共领域(不像 LZW 要收费)
2. **硬件友好**:解压只需极少 RAM,适合嵌入式
3. **简单**:RFC 1951 只有 28 页,核心算法能用 100 行代码实现
4. **可靠**:已经过几十亿文件验证,bug 早被修光

zstd / brotli 等新算法压缩比稍好(10-30%),但 DEFLATE 在"压缩够好 + 解压快 + 通用性"上的平衡仍极难超越。

**读完这一篇你能**:
- 解释 LZ77 怎么找重复,Huffman 怎么用变长码
- 在 Rust 里实现 DEFLATE 解码器(支持 fixed + dynamic Huffman)
- 看懂任何 DEFLATE 流(zlib wrapper / gzip wrapper / raw deflate)
- 给 miniz / flate2 / zune-inflate 等 Rust crate 贡献代码

## 1 · 大局:DEFLATE 的层次结构

DEFLATE 流由若干**block**(块)组成。每个 block 用以下三种模式之一:

| 模式 | 名字 | 描述 |
|---|---|---|
| 00 | Stored(未压缩) | 直接复制原始字节 |
| 01 | Fixed Huffman | 用预定义的 Huffman 码表 |
| 10 | Dynamic Huffman | 块内自带 Huffman 码表 |
| 11 | (保留) | 不允许 |

每个 block 头 3 bit:

- 1 bit `BFINAL`:1 = 最后一个 block,0 = 还有后续
- 2 bit `BTYPE`:block 类型(00, 01, 10)

模式 00 用于"数据本身不可压缩"(比如已经是 JPEG)。模式 01 用于"快速路径",跳过统计直接用固定码表。模式 10 是最常见——块内带 Huffman 表,统计当前块的最优编码。

## 2 · LZ77:基础

### 直觉

想象你在写一本英文小说,要重复"the quick brown fox"。第一次写完整,第二次写"see previous paragraph, length 19 chars"。**这就是 LZ77**:用"指针 + 长度"代替重复字符串。

具体:扫描数据时维护一个**滑动窗口**(sliding window),大小 32 KB。当前字符如果在窗口里有重复,记录"距离 distance + 长度 length",而不是直接存字节。

### 例

原始字符串:`"abc abcd abcde"`

LZ77 编码:

```
abc               字面 'a', 'b', 'c'
<dist=4, len=3>   "abc"(从 4 字节前的 "abc" 复制 3 字节)
d                 字面 'd'
<dist=6, len=4>   "abcd"(从 6 字节前的 "abcd" 复制 4 字节)
e                 字面 'e'
```

结果:`abc <4,3> d <6,4> e`——比原字符串短。

### DEFLATE 的 LZ77 变种

DEFLATE 的 LZ77 用:

- **距离 distance**:1 到 32768(指向滑动窗口内)
- **长度 length**:3 到 258(最小 3,因为更短用字面更便宜)

每个输出 token 是字面字节(0-255)或 (length, distance) 对。

## 3 · Huffman 编码:把符号转成位

### 直觉

ASCII 用 8 bit 表示每个字符——'e' 和 'z' 都是 8 bit,但 'e' 在英文里出现频率高 100 倍。**为什么不给高频字符短编码?**

Huffman 编码:给每个符号分配一个**变长位序列**,常见符号短,罕见符号长。

经典例子:字符集 `{a, b, c, d, e}`,频率 `{50%, 20%, 15%, 10%, 5%}`。Huffman 算法构造:

```
a: 0        (1 bit)
b: 10       (2 bit)
c: 110      (3 bit)
d: 1110     (4 bit)
e: 1111     (4 bit)
```

平均位 = 0.5×1 + 0.2×2 + 0.15×3 + 0.1×4 + 0.05×4 = 1.95 bit/符号。
对比 ASCII 8 bit,压缩比 4:1。

### 前缀码(Prefix Code)的关键性质

Huffman 码是**前缀码**:任何符号的码不是另一个符号码的前缀。这保证解码时无歧义——读到 `0` 立刻知道是 'a';读到 `10` 才可能是 'b';不会混淆。

### 构造 Huffman 树

经典算法:

1. 把所有符号按频率放进优先队列
2. 取两个最小频率的节点,合并成一个父节点(频率 = 两者和)
3. 父节点重新入队
4. 重复直到只剩一个节点(根)
5. 从根走,左 = 0,右 = 1,到叶节点路径就是该符号的码

```rust
use std::collections::BinaryHeap;
use std::cmp::Reverse;

#[derive(Debug)]
struct Node {
    freq: u32,
    symbol: Option<u8>,     // None = 内部节点
    left: Option<Box<Node>>,
    right: Option<Box<Node>>,
}

fn build_huffman(freqs: &[(u8, u32)]) -> Node {
    let mut heap = BinaryHeap::new();
    for &(sym, freq) in freqs {
        heap.push(Reverse((freq, Node {
            freq, symbol: Some(sym),
            left: None, right: None,
        })));
    }
    while heap.len() > 1 {
        let Reverse((_, a)) = heap.pop().unwrap();
        let Reverse((_, b)) = heap.pop().unwrap();
        let merged = Node {
            freq: a.freq + b.freq,
            symbol: None,
            left: Some(Box::new(a)),
            right: Some(Box::new(b)),
        };
        heap.push(Reverse((merged.freq, merged)));
    }
    let Reverse((_, root)) = heap.pop().unwrap();
    root
}
```

每行注释:

- `BinaryHeap` 是 Rust 的优先队列,默认大顶堆,用 `Reverse` 包成小顶
- `symbol: Option<u8>` — Some = 叶节点, None = 内部节点
- 每次合并两个最小频率节点,频率相加成父节点
- 直到只剩一个根

## 4 · DEFLATE 的 Huffman 限制

DEFLATE 不直接用上面的"标准 Huffman",而是用**码长限制**的 Huffman:

- 任何符号的码长 ≤ 15 bit
- 字面/长度码 ≤ 288 个符号(实际只用 286 个)
- 距离码 ≤ 32 个符号(实际只用 30 个)

为什么限制?**硬件友好**:解码器用固定大小的查找表,码长 ≤ 15 保证表大小 ≤ 32K 项。

### Canonical Huffman Codes

DEFLATE 还要求**规范 Huffman**(canonical):码长相同的符号按数值升序分配码。这样规范只存"每个符号的码长",解码器能 reconstruct 码表——节省存储。

例:三个符号码长都是 3,数值是 5, 6, 7。规范分配:

```
符号 5: 000
符号 6: 001
符号 7: 010
```

按数值升序排列分配连续码。

## 5 · DEFLATE 的 Fixed Huffman 模式

Fixed Huffman(BTYPE=01)用预定义码表:

- 字面/长度码:0-143 用 8 bit(码 00110000 到 10111111),144-255 用 9 bit(110010000 到 111111111),256-279 用 7 bit(0000000 到 0010111),280-287 用 8 bit(11000000 到 11000111)
- 距离码:0-29 用 5 bit 定长

这个表是统计大量文本得来的"经验最优"。Fixed 模式省去存动态码表的开销,适合短数据。

## 6 · DEFLATE 的 Dynamic Huffman 模式

Dynamic Huffman(BTYPE=10)在块头自带码表。结构:

```
HLIT(5 bit)         字面/长度码数 - 257(范围 257-286)
HDIST(5 bit)        距离码数 - 1(范围 1-32)
HCLEN(4 bit)        码长码数 - 4(范围 4-19)
HCLEN+4 个 3-bit 码长  按 RFC 1951 顺序给码长码的码长
(根据上面解出的码长码,解码 HLIT+HDIST+HCLEN 个码长)
```

**码长码**(code length code):对"每个符号的码长"再 Huffman 编码。码长值域 0-15(直接码长)+ 16(重复上一码长 3-6 次)+ 17(重复 0 码长 3-10 次)+ 18(重复 0 码长 11-138 次)。

为什么这么复杂?因为码长本身有大量重复(很多符号码长相同),用 RLE(run-length encoding)压缩,再 Huffman。

## 7 · 详解 RFC 1951 解码步骤

假设你拿到一段 DEFLATE 流(raw deflate,不是 zlib 包装):

```
1. 读 1 bit: BFINAL
2. 读 2 bit: BTYPE
3. 根据 BTYPE:
   - 00(Stored):跳到下一字节边界,读 LEN(2 byte LE)+ NLEN(2 byte LE)
                  LEN 是后续原始字节数,NLEN 是 LEN 的位反(校验)
                  读 LEN 个字节直接输出
   - 01(Fixed):用预定义 Huffman 表
                  进入主循环
   - 10(Dynamic):
                  读 HLIT, HDIST, HCLEN
                  读 HCLEN+4 个 3-bit 码长(按固定顺序)
                  构造码长码 Huffman 树
                  用码长码 Huffman 解码 HLIT+257+HDIST+1 个码长
                  (注意中间可能有 16/17/18 重复码)
                  把码长分成字面/长度码 + 距离码
                  构造两个 Huffman 树
                  进入主循环
   - 11:报错
   
4. 主循环:
   用字面/长度 Huffman 解码一个符号
   - 符号 < 256:字面字节,输出该字节
   - 符号 = 256:块结束
   - 符号 > 256:长度码,根据 RFC 表 1 算实际长度
                 (符号 257-285 对应长度 3-258,部分需要额外位)
                 然后用距离 Huffman 解码距离码
                 根据 RFC 表 2 算实际距离(部分需要额外位)
                 从输出 buffer 的 (current - distance) 复制 length 字节
                 (注意:可能 distance < length,字节会重叠,
                  必须按字节循环复制)
   重复直到符号 = 256
5. 如果 BFINAL = 0,回到步骤 1 处理下一个 block
```

### 长度码表

```
码   额外位  长度范围
257  0      3
258  0      4
259  0      5
260  0      6
261  0      7
262  0      8
263  0      9
264  0      10
265  1      11-12
266  1      13-14
267  1      15-16
...
285  0      258
```

### 距离码表

```
码  额外位  距离范围
0   0       1
1   0       2
2   0       3
3   0       4
4   1       5-6
5   1       7-8
6   2       9-12
...
29  13      24577-32768
```

## 8 · 位读取器(Bit Reader)

DEFLATE 是按 bit 操作,不是按 byte。但数据按 byte 存储,内部 bit 顺序重要:

- Huffman 码:高位在前(MSB first)
- 额外位(长度/距离的 extra bits):低位在前(LSB first)

这是 RFC 1951 最容易出错的地方。位读取器:

```rust
struct BitReader<'a> {
    data: &'a [u8],
    byte_pos: usize,
    bit_pos: u8,  // 0..7
}

impl<'a> BitReader<'a> {
    fn new(data: &'a [u8]) -> Self {
        Self { data, byte_pos: 0, bit_pos: 0 }
    }
    
    fn read_bits(&mut self, n: u32) -> u32 {
        // LSB first(用于 extra bits、字段如 BFINAL)
        let mut result = 0u32;
        for i in 0..n {
            if self.byte_pos >= self.data.len() {
                panic!("EOF");
            }
            let bit = (self.data[self.byte_pos] >> self.bit_pos) & 1;
            result |= (bit as u32) << i;
            self.bit_pos += 1;
            if self.bit_pos == 8 {
                self.bit_pos = 0;
                self.byte_pos += 1;
            }
        }
        result
    }
    
    fn read_huffman(&mut self, tree: &HuffmanTree) -> u16 {
        // MSB first(用于 Huffman 码)
        let mut code = 0u32;
        let mut len = 0u32;
        loop {
            // 读 1 bit,加到 code 低位
            let bit = self.read_bits(1);
            // Huffman 是 MSB first,但 bit reader 是 LSB first
            // 所以我们要"反向"加 bit
            code = (code << 1) | bit;
            len += 1;
            
            if let Some(&symbol) = tree.lookup(code, len) {
                return symbol;
            }
            if len > 15 {
                panic!("Huffman code too long");
            }
        }
    }
}
```

每行注释:

- `read_bits(n)` LSB first:第 i 个读出的 bit 放在结果的第 i 位
- `read_huffman` MSB first:每次把新 bit 加在低位,前面整体左移——结果高位是先读的 bit
- `tree.lookup(code, len)` — 在 Huffman 树里查"(code, len) 对应哪个符号"

## 9 · Huffman 解码:Fast Lookup Table

朴素 Huffman 解码:每个 bit 走树一次。慢。

快速 Huffman:**预计算 lookup table**。给定 15 位最大码长,预计算 2^15 = 32768 项表。读 15 bit,直接查表得(符号, 码长)。然后把 bit reader 退回 (15 - 码长) bit。

```rust
struct HuffmanTree {
    // 15-bit lookup table
    table: Vec<(u16, u8)>,  // (symbol, code_length)
    // 后续 fallback(码长 > 15 的极少,实际不会发生)
}

impl HuffmanTree {
    fn from_code_lengths(code_lengths: &[u8]) -> Self {
        // 1. 算每个码长的符号数
        let mut bl_count = [0u32; 16];
        for &len in code_lengths {
            if len > 0 {
                bl_count[len as usize] += 1;
            }
        }
        
        // 2. 算每个码长的第一个码
        let mut next_code = [0u32; 16];
        let mut code = 0;
        for len in 1..=15 {
            code = (code + bl_count[len - 1]) << 1;
            next_code[len] = code;
        }
        
        // 3. 给每个符号分配码
        let mut codes = vec![None; code_lengths.len()];
        for (sym, &len) in code_lengths.iter().enumerate() {
            if len > 0 {
                codes[sym] = Some((next_code[len as usize], len));
                next_code[len as usize] += 1;
            }
        }
        
        // 4. 建 lookup table(简化:实际用 15-bit 表)
        // ...
        
        Self { table: vec![(0, 0); 32768] }
    }
}
```

每行注释:

- `bl_count[len]` — 码长为 len 的符号数
- `next_code[len]` — 码长 len 的下一个可用码
- 给每个符号分配码,遵循 Canonical Huffman 规则

工业级实现(zlib、miniz)用更精细的二级表——一级 9 bit,二级补足 15 bit,节省内存。

## 10 · 完整 DEFLATE 解码器骨架

```rust
pub fn inflate(data: &[u8]) -> Result<Vec<u8>, String> {
    let mut reader = BitReader::new(data);
    let mut output: Vec<u8> = Vec::new();
    
    loop {
        let bfinal = reader.read_bits(1);
        let btype = reader.read_bits(2);
        
        match btype {
            0 => {
                // Stored
                reader.align_to_byte();
                let len = reader.read_u16_le();
                let nlen = reader.read_u16_le();
                if len != !nlen {
                    return Err("stored block length mismatch".into());
                }
                for _ in 0..len {
                    let byte = reader.read_byte();
                    output.push(byte);
                }
            }
            1 => {
                // Fixed Huffman
                let lit_tree = build_fixed_lit_tree();
                let dist_tree = build_fixed_dist_tree();
                decode_block(&mut reader, &lit_tree, &dist_tree, &mut output)?;
            }
            2 => {
                // Dynamic Huffman
                let (lit_tree, dist_tree) = read_dynamic_trees(&mut reader)?;
                decode_block(&mut reader, &lit_tree, &dist_tree, &mut output)?;
            }
            _ => return Err("invalid btype".into()),
        }
        
        if bfinal == 1 { break; }
    }
    
    Ok(output)
}

fn decode_block(
    reader: &mut BitReader,
    lit_tree: &HuffmanTree,
    dist_tree: &HuffmanTree,
    output: &mut Vec<u8>,
) -> Result<(), String> {
    loop {
        let symbol = reader.read_huffman(lit_tree);
        if symbol < 256 {
            // 字面字节
            output.push(symbol as u8);
        } else if symbol == 256 {
            // 块结束
            break;
        } else {
            // 长度码
            let (length, extra_bits) = decode_length(symbol);
            let extra = reader.read_bits(extra_bits);
            let length = length + extra;
            
            // 距离码
            let dist_symbol = reader.read_huffman(dist_tree);
            let (base_dist, extra_bits) = decode_distance(dist_symbol);
            let extra = reader.read_bits(extra_bits);
            let distance = base_dist + extra;
            
            // 复制(注意可能重叠)
            let start = output.len() - distance as usize;
            for i in 0..length as usize {
                let byte = output[start + i];
                output.push(byte);
            }
        }
    }
    Ok(())
}
```

每行注释:

- `align_to_byte` — 跳到下一个字节边界(stored 模式按字节)
- `read_u16_le` — 16 位 little-endian(DEFLATE stored 块用 LE)
- `length != !nlen` — NLEN 是 LEN 的位反,校验数据完整
- 字面 < 256:直接输出
- 长度码 257-285:解码长度(查表 + extra bits)
- 距离码 0-29:解码距离(查表 + extra bits)
- **复制时按字节循环**——可能 distance < length,即"自重叠复制"(常见于 RLE)

## 11 · 完整例子:解码 "deflate"

我们看一段真实的 DEFLATE 流(简化例子):

```
原始数据:Hello Hello
LZ77 后:Hello <dist=5, len=5>
Huffman 后(假设 Fixed):
  H = 01001000 (8-bit 字面)
  e = 01100101
  l = 01101100
  o = 01101111
  ' ' = 00100000
  <len=5> = symbol 261(对应长度 5,无 extra bits)= 码 00100011(假设)
  <dist=5> = symbol 4(对应距离 5,无 extra bits)= 码 00000010(5-bit 假设)
```

最终位流(简化):拼接所有码,在前面加 `BFINAL=1, BTYPE=01` 3 bit。

## 12 · ZLIB 和 GZIP 包装

DEFLATE 是"原始流",实际文件格式常包装:

- **zlib**(RFC 1950):2 字节头(`78 9C` 最常见,deflate default compression)+ DEFLATE + 4 字节 Adler-32 校验
- **gzip**(RFC 1952):10 字节头(`1F 8B` magic)+ 元信息 + DEFLATE + 4 字节 CRC32 + 4 字节原始大小
- **zip**:每个文件单独 DEFLATE,前后加 zip 容器元信息

PNG 用 zlib 包装(因为 PNG 规范需要校验),zip / gzip 各自的包装用于不同场景。

## 13 · Rust 实现:用 flate2

```toml
# Cargo.toml
[dependencies]
flate2 = "1.0"
```

```rust
use flate2::read::{GzDecoder, ZlibDecoder, DeflateDecoder};
use std::io::Read;

// 解 gzip 文件
fn decompress_gzip(data: &[u8]) -> std::io::Result<Vec<u8>> {
    let mut d = GzDecoder::new(data);
    let mut result = Vec::new();
    d.read_to_end(&mut result)?;
    Ok(result)
}

// 解 zlib 流(PNG 用)
fn decompress_zlib(data: &[u8]) -> std::io::Result<Vec<u8>> {
    let mut d = ZlibDecoder::new(data);
    let mut result = Vec::new();
    d.read_to_end(&mut result)?;
    Ok(result)
}

// 解 raw DEFLATE(无包装)
fn decompress_deflate(data: &[u8]) -> std::io::Result<Vec<u8>> {
    let mut d = DeflateDecoder::new(data);
    let mut result = Vec::new();
    d.read_to_end(&mut result)?;
    Ok(result)
}
```

## 14 · 历史

- 1952: David Huffman 发表 Huffman 编码论文
- 1977: Abraham Lempel 和 Jacob Ziv 发表 LZ77
- 1980s: ARC、LZW、PKZIP 等压缩工具兴起
- 1990s: Phil Katz 设计 DEFLATE(放进 zip),公开到公共领域
- 1996: RFC 1950(zlib)、1951(DEFLATE)、1952(gzip)发布
- 2000s: DEFLATE 成 Web 标准(HTTP gzip)、PNG 标准
- 2010s: zstd、brotli 在压缩比上略胜,但 DEFLATE 仍主流
- 2020s: DEFLATE 仍是绝大多数场景的默认压缩

## 15 · 关联 Day

- **铺垫**:Day 100+ 二进制读取;Day 200 二叉树;Day 436 PNG 引入 DEFLATE
- **当天**:本篇是 DEFLATE 专题
- **后续**:`asset-pipeline-architecture.md` 用 DEFLATE 压资产

## 16 · 变式训练

### Lv1 · 概念辨析

**题**:DEFLATE 用"LSB first"读 extra bits 但"MSB first"读 Huffman 码。为什么两种顺序?

**参考解答**:这是历史包袱。Phil Katz 设计 DEFLATE 时,Intel CPU 是 LSB-first(小端),他按 CPU 习惯让 extra bits 也是 LSB first(把字节当作 LSB 在前的位流)。但 Huffman 码按"码字"概念是 MSB first(从树根走,左 = 0 = 第一个读出的位)。两种顺序并存是当时硬件 + 算法概念混合的产物。RFC 1951 第 5 节明确说明两种顺序。

### Lv2 · 动手实践

**题**:用 Rust 实现一个 LZ77 编码器(简化版:距离 ≤ 256,长度 3-16)。编码 `"abc abc def def"`。

**参考解答**:

```rust
fn lz77_encode(data: &[u8]) -> Vec<Token> {
    enum Token { Lit(u8), Match { dist: u16, len: u16 } }
    let mut result = Vec::new();
    let mut i = 0;
    
    while i < data.len() {
        // 在 [max(0, i-256)..i] 范围找最长匹配
        let window_start = i.saturating_sub(256);
        let mut best_len = 0;
        let mut best_dist = 0;
        
        for start in window_start..i {
            let mut len = 0;
            while i + len < data.len() &&
                  len < 16 &&
                  data[start + len] == data[i + len] {
                len += 1;
            }
            if len >= 3 && len > best_len {
                best_len = len;
                best_dist = i - start;
            }
        }
        
        if best_len >= 3 {
            result.push(Token::Match {
                dist: best_dist as u16,
                len: best_len as u16,
            });
            i += best_len;
        } else {
            result.push(Token::Lit(data[i]));
            i += 1;
        }
    }
    result
}
```

### Lv3 · 迁移设计

**题**:DEFLATE 的 LZ77 滑动窗口 32KB。设计一个适合"超长重复序列"(比如 DNA 序列,几兆字节的 ACGT 重复)的压缩算法,要怎么调整窗口?LZ77 还适用吗?

**提示**:32KB 窗口适合一般文本。DNA 重复可能跨兆字节,LZ77 滑窗太小。考虑 LZ77 的变种(LZMA 大窗口、LZ4 长距离匹配)。

### Lv4 · 开源贡献

**题**:`zune-inflate` 是 Rust 最快的 DEFLATE 解码器之一,GitHub: https://github.com/etemesi254/zune-inflate

1. clone 它
2. 看它的 lookup table 实现(`src/decoder.rs`)
3. 看它的 SIMD 优化(如果有)
4. 可能的贡献:加 fuzzing 测试 / 改进文档 / 加 Brotli 解码

## 17 · Rust / Arch 落地代码

完整的 DEFLATE 解码器骨架(可跑,简化版):

```rust
// src/main.rs
use std::fs::File;
use std::io::Read;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<String> = std::env::args().collect();
    let path = &args[1];
    
    let mut file = File::open(path)?;
    let mut data = Vec::new();
    file.read_to_end(&mut data)?;
    
    // 自动检测格式
    if data.starts_with(&[0x1F, 0x8B]) {
        // gzip
        let result = decompress_gzip(&data)?;
        println!("gzip: 解压 {} → {} 字节", data.len(), result.len());
    } else if data.starts_with(&[0x78, 0x9C]) || data.starts_with(&[0x78, 0xDA]) {
        // zlib
        let result = decompress_zlib(&data)?;
        println!("zlib: 解压 {} → {} 字节", data.len(), result.len());
    } else {
        // 假定 raw DEFLATE
        let result = decompress_deflate(&data)?;
        println!("raw deflate: 解压 {} → {} 字节", data.len(), result.len());
    }
    
    Ok(())
}
```

Arch 工具链:

```bash
# 装工具
sudo pacman -S zlib      # C 库
sudo pacman -S gzip      # gzip 命令
sudo pacman -S p7zip     # 7z(支持 zip)

# 看压缩比
gzip -k large_file.txt
ls -lh large_file.txt*
# 输出:
#   -rw-r--r-- 1 sun sun 10M large_file.txt
#   -rw-r--r-- 1 sun sun 3.5M large_file.txt.gz

# 不同压缩级别
gzip -1 file.txt  # 最快(压缩比低)
gzip -9 file.txt  # 最慢(压缩比高,默认 6)

# 看文件 hex
xxd file.txt.gz | head -3
# 输出:
# 00000000: 1f8b 0808 ...                  .Г......
# Magic 1F 8B,然后 08(deflate),...

# 测试解压
gunzip file.txt.gz
# 等价:gzip -d file.txt.gz

# Profiling
sudo pacman -S perf valgrind
valgrind --tool=callgrind ./my_deflate_decoder
kcachegrind callgrind.out.*
```

排错:

```bash
# 1. "invalid code lengths set"
#    原因:动态 Huffman 的码长无效(可能某个码长组合不可能存在)
#    排查:检查 HLIT/HDIST/HCLEN 解析,码长码解码

# 2. "distance too far back"
#    原因:distance > output.len()(试图复制不存在的数据)
#    排查:距离解码 + extra bits 算法

# 3. 解压结果是垃圾
#    原因:LSB vs MSB 顺序搞反(最常见 bug)
#    排查:仔细看 RFC 1951 第 5 节,区分 Huffman(MSB)和 extra bits(LSB)
```

## 18 · 延伸阅读

本仓库本地:

- `days/phase-7/deep-dives/png-format-complete.md` — PNG 用 DEFLATE
- `days/phase-7/deep-dives/asset-pipeline-architecture.md` — 资产用 DEFLATE 压

外部稳定 URL:

- RFC 1951(DEFLATE 规范): https://datatracker.ietf.org/doc/html/rfc1951
- RFC 1950(zlib 规范): https://datatracker.ietf.org/doc/html/rfc1950
- RFC 1952(gzip 规范): https://datatracker.ietf.org/doc/html/rfc1952
- zlib 由来: https://www.zlib.net/zlib_tech.html
- "How to be a DEFLATOR"教程: https://github.com/dbohdan/deflate101

真实开源源码:

- zlib(原版 C): https://github.com/madler/zlib
- miniz(C 单文件): https://github.com/richgel999/miniz
- flate2(Rust,包装 miniz): https://github.com/rust-lang/flate2
- zune-inflate(Rust 快): https://github.com/etemesi254/zune-inflate
- miniz_oxide(Rust pure): https://github.com/Frommi/miniz_oxide
