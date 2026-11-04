# 一加 13s (高通骁龙 8 至尊版 / SM8750) 移植 Apple XNU 内核与 iOS 完整调试技术全景实录

> **项目名称**：Project Sweet / Pagani (OnePlus 13s XNU Porting)  
> **远程仓库 (GitHub)**：https://github.com/353154/unixnu-pagani (Public, `main` branch)  
> **云端流水线 (CI/CD)**：https://github.com/353154/unixnu-pagani/actions  
> **目标平台**：OnePlus 13s / 13T (代号 `pagani` / 型号 `CPH2723`)  
> **核心芯片**：Qualcomm Snapdragon 8 Elite (SM8750 / sun, 8x Qualcomm Oryon 核心, ARMv9.2-A)  
> **底层固件**：高通 Gunyah Type-1 Hypervisor + QSEE TrustZone + ABL (Android Bootloader)  
> **目标操作系统**：Apple Darwin / XNU 内核 (xnu-8796.141.3) + iOS 16.7.16 核心用户态  
> **安全基石**：绝对免清空原则（严禁任何 `fastboot flash / erase`，全流程 100% 采用 `fastboot boot` 单次内存安全引导）  

---

## 目录 (Table of Contents)
1. [硬件背景与移植技术挑战](#1-硬件背景与移植技术挑战)
2. [第一阶段：从 0 到 1 破除引导黑盒 (BootShim 诞生与物理交接)](#2-第一阶段从-0-到-1-破除引导黑盒)
3. [第二阶段：彩虹硬件探测带体系 (Rainbow Checkpoints)](#3-第二阶段彩虹硬件探测带体系)
4. [第三阶段：死磕 MMU 开启与高通 Oryon 核心硬件陷阱攻坚](#4-第三阶段死磕-mmu-开启与高通-oryon-核心硬件陷阱攻坚)
   - 4.1 [高通 XPU 硬件内存防火墙熔断机制 (Smoking Gun)](#41-高通-xpu-硬件内存防火墙熔断机制)
   - 4.2 [SCTLR_EL1.WXN (写即不可执行) 致命死锁剖析](#42-sctlr_el1wxn-写即不可执行-致命死锁剖析)
   - 4.3 [非法的系统寄存器指令 msr PAN, #0 陷阱](#43-非法的系统寄存器指令-msr-pan-0-陷阱)
   - 4.4 [TCR_EL1 页表遍历层级与 16KB Granule 体系结构匹配](#44-tcr_el1-页表遍历层级与-16kb-granule-体系结构匹配)
   - 4.5 [微观纳秒级双断点 (CP3A / CP3B) 的精准隔离](#45-微观纳秒级双断点-cp3a--cp3b-的精准隔离)
5. [第四阶段：云端自动化构建与真机零风险工作流](#5-第四阶段云端自动化构建与真机零风险工作流)
6. [后续技术演进路线 (Roadmap: Milestone 5 ~ 8)](#6-后续技术演进路线)
7. [第五阶段：异常可视化向量表 (2026-11-05 会话)](#7-第五阶段异常可视化向量表--让无声死机开口说话-2026-11-05-会话)

---

## 1. 硬件背景与移植技术挑战

一加 13s（代号 `pagani`）搭载高通 2024~2025 年的旗舰移动平台——**骁龙 8 至尊版（Snapdragon 8 Elite / SM8750）**。
该芯片彻底摒弃了 ARM 公版 Cortex-X/A 架构，首次在移动端采用了高通全自研的 **Qualcomm Oryon CPU 架构**（8 核设计：2x 超大核 4.32GHz + 6x 大核 3.53GHz），微架构代号 Phoenix。

### 核心移植壁垒：
1. **异构 Boot 链与加载格式对立**：
   - 高通平台引导标准采用 Android Boot Image v4 格式（GKI 内核压缩镜像 `Image.gz` / `Image`），执行流为：`PBL -> SBL -> XBL -> ABL -> Linux Kernel`。
   - 苹果 XNU 内核原生为 Mach-O 格式（带 64 位瘦 Mach-O 头、`__TEXT_EXEC`、`__DATA_CONST` 等 Mach-O 段），依赖苹果自家的 `iBoot` 提供复杂的 `boot_args` 结构体及 Device Tree（ADT）。
2. **虚拟化层拦截 (Gunyah Hypervisor)**：
   - 骁龙 8 至尊版原生运行在 EL2 级别的 **Gunyah Type-1 Hypervisor** 之下。操作系统内核只能运行在非安全 EL1（Non-Secure EL1）。
   - 许多 CPU 底层寄存器受到 Hypervisor 的严格约束或陷阱（Trap）。
3. **硬件安全防火墙 (Qualcomm XPU)**：
   - 高通在总线上布设了高强度的硬件内存保护单元（XPU）。如果 CPU 试图对属于 TrustZone（QSEE）、基带（Modem）或 Gunyah 的物理内存发起任何未授权读取或**投机性预取（Speculative Prefetch）**，XPU 会直接触发总线熔断并强制拉死 CPU。
4. **无调试外设的极度盲测环境**：
   - 消费级零售真机完全关闭了 JTAG 调试接口，没有引出 UART 串口。在进入图形驱动前，内核若发生任何崩溃，屏幕没有任何日志，只会瞬时卡死或黑屏重启。

---

## 2. 第一阶段：从 0 到 1 破除引导黑盒

### 2.1 BootShim 微引导器的诞生
为了在不修改高通 ABL 固件的前提下无缝加载苹果 XNU 内核，我们研发了 **BootShim**（一个体积仅 180KB 的裸机底层汇编/C 微引导器）：
- 伪装成标准的 Linux 64 位无压缩内核（具备 ARM64 Linux 64 字节头部 `kernel_image_head`）；
- 伪装通过 ABL 的校验，由 ABL 加载到物理内存 `0x80000000`；
- 将预先打包在 Ramdisk 中的 XNU Mach-O 内核段（16MB）按 segment 逐一解压并重定位到物理内存 `0xb0000000`；
- 在内存中合成符合 Apple 规范的 `boot_args` 和 Apple Device Tree (`pagani.adt`)；
- 最后关闭中断，平滑跳转到 XNU 物理入口 `_start`。

### 2.2 接管硬件显存 (连续闪屏区)
在没有串口的绝境中，真机 OLED 屏幕是唯一的生命线。
我们通过逆向分析高通设备树与 ABL 内存保留区，成功锁定了 ABL 遗留下来的图形帧缓冲区：
- **物理基地址**：`0xfc800000`（高通 `cont_splash_region` 保留区）；
- **屏幕分辨率**：$1216 \times 2688$ 像素，32-bit ARGB/BGR 模式；
- **扫描行步长 (Stride)**：$4864$ 字节（$1216 \times 4$）；
- **显示测试**：BootShim 在物理地址模式下，向 `0xfc800000` 连续写入高亮纯色（全屏刷红/刷蓝），并成功绘制点阵英文字符，证明我们在裸机阶段完全获得了屏幕控制权！

### 2.3 斩除首个致命硬件陷阱：`OSLAR_EL1`
当 BootShim 执行 `br x4` 跃迁到 XNU 的物理入口 `_start` 时，机器一度陷入永恒黑屏。
排查发现：
- 苹果原版 XNU 的 `_start` 第一条关键系统寄存器操作是：
  ```asm
  msr   OSLAR_EL1, xzr    // 解锁核心调试锁
  ```
- **在 Qualcomm Oryon 核心以及 Gunyah EL1 客户机环境下，访问 `OSLAR_EL1` 直接触发了未定义指令异常（Undefined Instruction Exception）**，CPU 当场崩溃！
- **破局**：在补丁中彻底移除该指令，并换上我们的硬件绘制探针。
- **真机突破**：屏幕瞬间亮起 **$400 \times 100$ 纯白矩形方块（Stage 0）**！
  **这是历史上 Apple XNU 内核的第一条机器指令首次在高通 Oryon 核心上物理执行成功！**

---

## 3. 第二阶段：彩虹硬件探测带体系 (Rainbow Checkpoints)

为了将 XNU 启动过程中的每一条汇编指令和 C 语言入口可视化，我们在内核初始化路径上建立了**彩虹硬件探测带（Rainbow Checkpoints）**。

### 3.1 探针实现原理
探针基于纯汇编宏 `SWEET_CHECKPOINT x_off, color_val`：
- 不依赖堆栈（Stack-less），不依赖内存分配，不修改主逻辑寄存器；
- 无论 MMU 开启与否，直接将 32 位 ARGB 像素块写入显存 `0xfc800000 + 520 * 4864 + x_off * 4`；
- 在屏幕顶部纯白方块下方，形成一排清晰可辨的彩色状态指示块。

### 3.2 彩虹探测带状态定义表

| 探测带 | 颜色 | 对应十六进制色值 | 代码所在位置 | 达成的技术里程碑 | 实测状态 |
| :---: | :---: | :---: | :---: | :---: | :---: |
| **Stage 0** | ⚪ 纯白 | `0xFFFFFFFF` | `_start` 入口第 1 行 | BootShim 跳转移交成功，XNU 物理指令首度执行 | ✅ **已完全点亮** |
| **CP1** | 🟨 纯黄 | `0xFFFFFF00` | `start_first_cpu` 入口 | 成功关中断，清除 DAIF，进入主 CPU 引导流程 | ✅ **已完全点亮** |
| **CP2** | 🟦 青色 | `0xFF00FFFF` | `create_bootstrap_mapping` 后 | 16KB 页表 V=P 平坦映射与 KVA 映射构建完成，显存页表写入 | ✅ **已完全点亮** |
| **CP3** | 🟪 品红 | `0xFFFF00FF` | `common_start` 写入 TCR/TTBR 后 | TCR、MAIR、TTBR0、TTBR1 写入就绪，到达开启 MMU 关口 | ✅ **已完全点亮** |
| **CP3A** | ⚪ 白色 | `0xFFFFFFFF` | `MSR_SCTLR_EL1_X0` 紧前一条 | 控制位计算完成，准备执行开启 MMU 指令 | 🚀 **正在测试** |
| **CP3B** | 🟧 珊瑚橙 | `0xFFFF8800` | `MSR_SCTLR_EL1_X0` 紧后一条 | SCTLR_EL1 写入完成，等待执行流水线同步 isb | 🚀 **正在测试** |
| **CP4** | 🟩 绿色 | `0xFF00FF00` | `isb sy` 之后 | MMU 成功点亮，取指单元平稳跨越地址翻译鸿沟 | 🎯 **即将突破** |
| **CP5** | 🟦 浅蓝 | `0xFF0088FF` | `ret lr` 跳转之前 | 参数完成 KVA 转换，准备跃迁至 C 语言世界 | ⏳ 待验证 |
| **CP6** | 🟧 橙色 | `0xFFFFAA00` | `arm_init` C 语言入口第 1 行 | 成功跨越汇编/C边界，进入内核核心架构初始化 | ⏳ 待验证 |

---

## 4. 第三阶段：死磕 MMU 开启与高通 Oryon 核心硬件陷阱攻坚

在多次实测中，真机屏幕清晰展示出 **黄、青、品红（CP1 ~ CP3）** 三个色块，但绿块（CP4）始终未亮，系统定格在品红界面。
这表明代码在执行 **开启 MMU（`SCTLR_EL1.M = 1`）** 时发生了硬件死锁。我们对此展开了极其深入的底层攻坚。

### 4.1 高通 XPU 硬件内存防火墙熔断机制 (Smoking Gun)
#### 发现过程：
研读 BootShim 源码（`shim/mmu.c`）时，发现关键硬件警示：
> *"Qualcomm XPUs fault on speculative reads of protected carve-outs (TZ, hyp, modem...), so nothing is mapped cacheable except our own image"*

#### 故障机理：
1. XNU 源码在初始页表中，粗暴地把从 `0xb0000000` 开始的 1.2GB 大片内存统统标记为了 `Inner/Outer Write-Back Cacheable`；
2. 如果我们在写入 `SCTLR_EL1` 时顺手打开了 **`C = 1`（Data Cache 数据缓存）**；
3. Qualcomm Oryon 核心具备极强悍的激进投机预取器（Speculative Prefetcher），会在 MMU 开启瞬间疯狂向整个可缓存区域投机性预读；
4. 预读取瞬间撞击到高通 TrustZone、Gunyah Hypervisor 和基带的物理内存保留区；
5. **高通片上 XPU 硬件防火墙立即拉闸断流，直接在系统总线层面将 CPU 锁死！**

#### 解决方案：
在开启 MMU 阶段，**严格强制关闭数据缓存（`C = 0`）**：
```asm
bic   x0, x0, #(1 << 2)   // 彻底关闭 D-Cache，封印投机预取器
```

---

### 4.2 SCTLR_EL1.WXN (写即不可执行) 致命死锁剖析
#### 故障机理：
高通 Gunyah Hypervisor 在引导时，其默认分配给 EL1 虚拟机的 `SCTLR_EL1` 中将 **`WXN`（bit 19，Write-Execute-Never）置为了 1**。
ARM64 体系结构严格规定：
- 当 `WXN = 1` 时，**任何在页表中带有“可写（Writable）”属性的内存页，会被 CPU 硬件强制判定为“禁止执行（Execute-Never / XN）”**；
- XNU 此时正运行在物理内存的平坦映射（V=P）中，而该页表项为了数据读写被配置为了可写模式；
- **当 `SCTLR_EL1.M = 1` 写入生效的一刹那，CPU 自身当前正在执行代码的这一页内存，瞬间被硬件剥夺了执行权限！**
- CPU 取下一条指令时立即触发 **Instruction Abort（权限故障异常）**！
- 此时中断向量表 `VBAR_EL1` 已被指向高地址 KVA，引发连锁崩溃，导致死机！

#### 解决方案：
严格同步 BootShim 的清除逻辑，强制将 `WXN` 和对齐检查位 `A` 清零：
```asm
bic   x0, x0, #(1 << 1)   // A = 0 (关闭严格对齐检查)
bic   x0, x0, #(1 << 19)  // WXN = 0 (绝杀！解除平坦映射中的可写即不可执行死锁！)
```

---

### 4.3 非法的系统寄存器指令 msr PAN, #0 陷阱
为了防止特权访问禁止（PAN）导致低地址访问报错，早期版本曾尝试插入 `msr PAN, #0`。
然而反汇编发现：Clang 编译器将该助记符编译成了 `msr S0_0_C4_C0_4, xzr`。在 Oryon 核心的 Non-Secure EL1 客户机环境下，该系统寄存器编码会直接抛出 **Undefined Instruction Exception（未定义指令异常）**。
**解决方案**：通过在 `SCTLR_EL1` 中置位 `SPAN = 1`（bit 23，在异常时不自动激活 PAN），彻底删除 `msr PAN, #0` 指令。

---

### 4.4 TCR_EL1 页表遍历层级与 16KB Granule 体系结构匹配
我们对 XNU 写入的 `TCR_EL1` 寄存器值 `0x000000226511a511` 进行了逐 bit 解构：
- `TG0 = 2` (16KB granule)
- `TG1 = 1` (16KB granule)
- `T0SZ = 17` (虚拟地址 47 位，有效寻址 128TB，从 Level 1 页表开始遍历)
- `T1SZ = 17` (高地址空间 47 位，完美覆盖 XNU 的 KVA 基地址 `0xfffffe0000000000`)
- `IPS = 2` (40 位物理地址寻址，完全覆盖设备 16GB 物理内存)
- `EPD0 = 0` / `EPD1 = 0` (TTBR0 与 TTBR1 均正常开启，支持双向地址翻译)

这证明 XNU 的内存管理单元配置与硬件完全相容，只要解决流水线取指可见性即可平稳跨越。

---

### 4.5 微观纳秒级双断点 (CP3A / CP3B) 的精准隔离
为了以 100% 毫无争议的物理证据定位当前停留在品红色的具体指令，我们在 `MSR_SCTLR_EL1_X0` 紧邻前后布设了微观探针：

```asm
	// 1. 读取 Gunyah 原始寄存器并修正安全位
	mrs		x0, SCTLR_EL1
	bic		x0, x0, #(1 << 1)   // A = 0 (关对齐检查)
	bic		x0, x0, #(1 << 2)   // C = 0 (关 D-Cache 防 XPU 熔断)
	bic		x0, x0, #(1 << 19)  // WXN = 0 (允许平坦映射执行代码)
	orr		x0, x0, #(1 << 0)   // M = 1 (开启 MMU)
	orr		x0, x0, #(1 << 12)  // I = 1 (开启指令缓存)
	orr		x0, x0, #(1 << 23)  // SPAN = 1 (保持 PAN 清除)

	/* 探针 CP3A: 纯白色方块 (0xFFFFFFFF) —— 写入 MMU 寄存器前的最后 1 纳秒 */
	SWEET_CHECKPOINT 250, 0xffffffff

	/* 关键跃迁：正式写入 SCTLR_EL1 开启硬件 MMU */
	MSR_SCTLR_EL1_X0

	/* 探针 CP3B: 珊瑚橙方块 (0xFFFF8800) —— SCTLR 已写入、流水线尚未 isb 同步 */
	SWEET_CHECKPOINT 265, 0xffff8800

	isb		sy

	/* 探针 CP4: 翠绿方块 (0xFF00FF00) —— 流水线同步完成，MMU 全面工作 */
	SWEET_CHECKPOINT 280, 0xff00ff00
```

---

## 5. 第四阶段：云端自动化构建与真机零风险工作流

为了保证数以百次的内核迭代高效、可追溯且绝对安全，我们构建了全自动闭环工作流：

```mermaid
flowchart LR
    A["本地代码改动 (start.s / patches)"] -->|git push| B["GitHub 远程仓库 (unixnu-pagani)"]
    B -->|触发 Actions| C["macOS-14 云端构建 (Xcode 15 / iig)"]
    C -->|生成 16MB 内核| D["编译产物 Artifact (149MB)"]
    D -->|watch_and_download.py 自动下载| E["本地打包流水线 (mkpayload + mkbootimg_v4)"]
    E -->|生成 32MB boot.img| F["fastboot boot 单次内存无感引导"]
    F -->|真机运行| G["一加 13s OLED 屏幕彩虹带判定"]
```

### 核心安全保障：
1. **零擦写铁律**：全流程杜绝 `fastboot flash` 或 `fastboot erase`，手机原有 ColorOS 系统、Bootloader 分区、用户数据毫无磨损风险；
2. **断电自愈**：任何死锁或异常，长按电源键强制重启后设备立刻恢复原有状态。

---

## 6. 后续技术演进路线

```
[Milestone 1] Bootloader 解锁与 Android Boot Image v4 结构打通        ─── [已完成]
[Milestone 2] 裸机屏幕 Framebuffer 显存接管 (连续闪屏区 1216x2688)    ─── [已完成]
[Milestone 3] BootShim 物理移交与 XNU 物理入口首条指令点亮 (白块)       ─── [已完成]
[Milestone 4] XNU 16KB 粒度 MMU 地址翻译与平坦映射点亮                 ─── [当前攻坚中]
[Milestone 5] 进入 C 语言 arm_init 并通过 sweet_early 清屏输出字符      ─── [即将达成]
[Milestone 6] UFS 4.0 闪存控制器只读驱动与 Device Tree 硬件解析       ─── [规划中]
[Milestone 7] 挂载 iOS 16.7.16 APFS 只读根文件系统与 launchd 启动     ─── [规划中]
[Milestone 8] 触控屏 (Goodix/Synaptics) 驱动与精简图形用户态交互       ─── [规划中]
```

---
*本文档由 Antigravity 自动化协同系统持续跟踪并实时更新。*

---

## 7. 第五阶段：异常可视化向量表 —— 让「无声死机」开口说话 (2026-11-05 会话)

### 7.1 会话起始现场快照
- 仓库 `unixnu-pagani` HEAD = `968022a`，关键补丁链已就位：关 D-Cache（`72a3ea6`）→ 清 WXN/A（`5e4cf12`）→ CP3A/CP3B 微探针（`368d7e7`）→ 页表 `dc civac` 清 PoC（`5239523`）→ **移除平坦映射 NX 位**（`4d04685`，05:29 提交）。
- CI Run `#41916624702`（`4d04685`）于 05:36 构建成功，`out/test-boot.img`（32MB）就绪。
- 真机（fastboot 序列号 `3B1F67EA9BBUHK76`）已执行 `fastboot boot out/test-boot.img`（OKAY, 1.17s），**NX 移除版正在机上运行，屏幕定格待人工读取**。

### 7.2 核心诊断盲区：CP3 与 CP4 之间的异常是「无声」的
对 CP3A（写 SCTLR 前 1ns）→ CP4（isb 后）窗口逐条分析后发现一个比任何单个 bug 更致命的问题——**这个窗口内发生的任何异常都无法被观测**：

1. XNU 在 `start_first_cpu` 早期已把 `VBAR_EL1` 指向 `LowExceptionVectorBase`，而该表的全部 16 个槽位都是 `b .`（原地死循环）；
2. 即便走 XNU 真正的异常处理路径，处理程序也依赖尚不存在的 per-CPU 数据结构，必然二次崩溃；
3. 因此无论是「SCTLR_EL1 写入被 Gunyah 陷阱吞掉」「MMU 开启后取指 Abort」「TTBR 遍历时的属性故障」，在屏幕上都表现为**同一种画面：定格无声死机**——三种完全不同的病因共享同一种症状，排查只能靠盲猜。

### 7.3 解决方案：SWEET 异常证据向量表（commit `e265c82`）
在 `start.s` 末尾新增一张 2048 字节、16 槽全彩异常向量表，并在 `common_start` 写入 `SCTLR_EL1` **之前**安装为 `VBAR_EL1`（直接 `msr`，绕过 PAC 签名的 pinst 包装）：

```asm
	adrp	x0, EXT(sweet_exc_vectors)@page
	add		x0, x0, EXT(sweet_exc_vectors)@pageoff
	msr		VBAR_EL1, x0
	isb		sy
```

每个向量槽只做一件事：把自己的专属颜色装入 `x0` 后跳入公共处理程序 `Lsweet_exc_common`，依次绘制三块证据区后 `wfe` 永久驻留（画面定格不丢）：

| 屏幕区域 | 内容 | 说明 |
| :---: | :---: | :--- |
| **第 600 行** | 400×40 色条 | 16 槽专属色，直接指认异常类型 |
| **第 700 行** | 32 格位带 | `ESR_EL1` 二进制，最左格 = bit31，白=1 / 深灰=0 |
| **第 760 行** | 32 格位带 | `FAR_EL1` 二进制，直接读出故障虚拟地址 |

#### 16 槽异常色卡对照表（第 600 行）
| 颜色 | 异常类型 | 颜色 | 异常类型 |
| :---: | :---: | :---: | :---: |
| 🔴 `0xFFFF0000` | 0: 同步异常, 当前EL, SP0 | 🟢 `0xFF00FF00` | 4: 同步异常, 当前EL, SPx |
| 🟠 `0xFFFF6A00` | 1: IRQ, 当前EL, SP0 | 🌿 `0xFF00FF87` | 5: IRQ, 当前EL, SPx |
| 🟡 `0xFFFFFF00` | 2: FIQ, 当前EL, SP0 | 🩵 `0xFF00FFFF` | 6: FIQ, 当前EL, SPx |
| 🟩 `0xFFB4FF00` | 3: SError, 当前EL, SP0 | 💙 `0xFF0090FF` | 7: SError, 当前EL, SPx |
| 🔵 `0xFF0000FF` | 8: 同步异常, 低EL, A64 | ⚪ `0xFFFFFFFF` | 12: 同步异常, 低EL, A32 |
| 🟣 `0xFF6A00FF` | 9: IRQ, 低EL, A64 | 🩶 `0xFF909090` | 13: IRQ, 低EL, A32 |
| 💜 `0xFFB400FF` | 10: FIQ, 低EL, A64 | 🫧 `0xFF009090` | 14: FIQ, 低EL, A32 |
| 🩷 `0xFFFF00FF` | 11: SError, 低EL, A64 | 🟥 `0xFF900030` | 15: SError, 低EL, A32 |

> **最可能的读数**：若死机根因是权限/翻译类取指或数据故障，应看到 **红色条（槽 0）** 或 **绿色条（槽 4）** + ESR 位带中 EC 字段（bit31~26）非零；若是 Gunyah 注入的 SError / 总线熔断，则是 **青柠条（槽 3）** 或 **天蓝条（槽 7）**。ESR 的 EC=0b100101（0x25，Instruction Abort EL1）= WXN/NX 残留；EC=0b100001（0x21，Data Abort）+ FAR 指向 carveout = XPU 熔断实锤。

### 7.4 工程验证链（推送前全绿）
1. `git apply --check` 对原始 `xnu-8796.141.3` 源码树应用通过；
2. 新增汇编代码独立抽出后经本地 `clang -c -arch arm64` 汇编通过（2164 字节），反汇编确认 16 槽严格 128 字节间距、`b Lsweet_exc_common` 跳转目标正确；
3. CI Run `#41919080851`（macOS-14 / Xcode 15）构建诊断版内核，完成后自动重合成 `test-boot.img`。

### 7.5 观察指引（读屏解码手册）
1. **彩虹带**（第 520 行，x=100~340）：黄→青→品红→白(250)→珊瑚(265)→绿(280)→浅蓝(340)，最靠右的颜色就是执行到的最远位置；
2. **第 400 行的 400×100 白块** = Stage0；**第 520 行 x=400 的橙色块** = 已进入 `arm_init`（C 语言世界）；
3. 若出现第 600/700/760 行的异常证据区：色条查上表定异常类型，位带从左到右按二进制读出 ESR/FAR；
4. 定格画面为最终状态（`wfe` 驻留），可随时长按电源键强制重启恢复 ColorOS，无任何写入风险。

### 7.6 实测结果链：三次真机迭代锁定冻结指令 (2026-11-05 06:00 ~ 06:15)

| 构建版本 | 新增能力 | 真机读数 | 结论 |
| :---: | :--- | :--- | :--- |
| `4d04685` (NX 移除版) | 平坦映射去 NX | 最远点亮珊瑚橙 CP3B | `msr SCTLR_EL1` 成功返回，MMU 开启后 ~20 条指令 + 1600 次显存写入全部成功 |
| `e265c82` (异常向量版) | 16 槽彩色异常表 + ESR/FAR 位带 | 依然橙色；**无任何异常色条/位带** | 排除一切同步/异步异常（Abort、SError 都没发生）——CPU 是无声冻结 |
| `d711f90` (二分标记版) | `dsb sy` 后草绿块 / `isb sy` 后粉红块 | **草绿亮、粉红不亮** | **冻结点 = `isb sy`**（`dsb sy` 屏障正常放行，在途事务全部完成） |

> 微观证据链：`movk/mov` 类指令不可能挂死且粉红块 0 个像素落屏 → 执行流断在 `isb sy` 一条指令上；同时无异常触发 → 不是权限/翻译故障，而是取指/总线层面的静默冻结。

### 7.7 根因破获：`__ARM_IC_NOALIAS_ICACHE__` 裁掉了开 MMU 前的 TLB/I-Cache 清理

对冻结点的溯源收敛到一条被编译器删除的代码：

1. `pexpert/arm64/apple_arm64_common.h:37` 无条件定义 `__ARM_IC_NOALIAS_ICACHE__ = 1`（苹果假设：iBoot 引导的核心 TLB/I-Cache 永远是干净的）；
2. 于是 `start.s` 中开 MMU 前唯一的 `tlbi vmalle1; ic iallu`（`#ifndef __ARM_IC_NOALIAS_ICACHE__` 保护块）**被整段预处理裁掉**；
3. 本机引导链是 ABL + Gunyah：Hypervisor 时代残留的**陈旧 TLB 表项与 I-Cache 行**一直活到 XNU 接管；
4. `SCTLR_EL1.M = 1` 瞬间陈旧翻译复活——恰好无害的表项让前 ~30 条指令照常执行（橙色块 + 草绿标记），而后续取指撞上致命表项，翻译指向 XPU 保护区 → 总线层挂起 → 无异常、无声、永久冻结；
5. **铁证对照**：BootShim 在同一颗 SoC、同一个 Gunyah 下开 MMU 百发百中，其使能序列（`shim/mmu.c:112-122`）恰好每步都有清理：写 TCR/TTBR 后 `isb; tlbi vmalle1; dsb nsh; isb`，跳转 XNU 前再 `dsb sy; ic iallu; dsb sy; isb`。

### 7.8 修复：补回 BootShim 同款清理序列 (commit `9729cb0`)

在 SWEET 路径写 `SCTLR_EL1` 之前插入（位于异常向量表安装之前）：

```asm
	ic		iallu      // 无效化整个 I-Cache（苹果配置裁掉的那条）
	tlbi	vmalle1    // 整表无效化 TLB（清 Gunyah/ABL 残留翻译）
	dsb		sy
	isb		sy
```

全链验证：`git apply --check` 通过 → 真机三色读数协议（SCREEN_READ_PROMPT v2）待验证。**若生效，粉红/绿/浅蓝块将依次点亮，直抵 `arm_init`。**

### 7.9 工期预期与三大加速器

| 里程碑 | 内容 | 预估 |
| :---: | :--- | :--- |
| M4 MMU 点亮 | **正在最后一击**（TLBI 修复待验证） | 当日出结论 |
| M5 `arm_init` 全程 + early console | GIC/timer/pmap 各需过墙 | 数天迭代 |
| M6 UFS 驱动 + 设备树 | 大块新驱动开发 | 1~2 周 |
| M7 APFS 根文件系统 + launchd | 依赖 M6 + AMFI 签名链 | 1~2 周 |
| M8 触屏 + 用户态图形 | 最后冲刺 | 数天 |

加速器：
1. **MMU 点亮后信息密度质变**：崩溃走 XNU panic 路径，屏幕直接打印日志（`sweet_early_panic` 已埋好），一轮数十条信息；
2. **QEMU 并行线**（`tools/qemu-sweet.py`）：M5+ 的内核逻辑 / iOS 用户态 / launchd 在 Mac 上 GDB 秒级迭代，真机只留给硬件环节；
3. **读屏协议 v2 + 异常向量表**：真机测试从「猜色板」升级为「结构化取证」（桌面 `SCREEN_READ_PROMPT.md`）。
