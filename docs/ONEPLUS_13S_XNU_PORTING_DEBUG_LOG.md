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
