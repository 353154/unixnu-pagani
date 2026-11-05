# XNU 移植接手须知（给新 Agent 的唯一入口）

> 你接手的是一个**正在进行的真机内核移植**，不是从零开始。
> 先读完本文件（约 120 行），再动手。**不要从 DEBUG_LOG 第一页顺序读**，那是 append-only 的历史，前面埋着已被推翻的结论。
>
> 项目：OnePlus 13s (`pagani` / SM8750 / Oryon 8 核) 移植 Apple XNU `xnu-8796.141.3`
> 运行环境：Gunyah Hypervisor NS-EL1
> 仓库：`~/unixnu-pagani`（GitHub `353154/unixnu-pagani`，main）
> 最后更新：2026-11-05 22:20

---

## 0. 三十秒状态卡

| 项 | 值 |
| :--- | :--- |
| 当前阶段 | M6 收尾：早期 VM 已全通，**卡在 console 接管** |
| 最新内核提交 | `cc9b9d2`（`0012` 真生效 + `0083`~`0086` 首次同时在场）；之后 `c376116` 仅改文档 |
| 最新构建 | Run `42042712579` |
| 屏幕最后一行 | `initialize_screen: b=FC800000, w=000004C0, h=00000A50, r=00001300, d=00000002` |
| 死点 | `osfmk/console/video_console.c:2792+` → `ml_io_map_unmappable(0xfc800000, 12.8MB, VM_WIMG_IO)` |
| 下一步动作 | 在该调用**前后各插一个 SWE 标记**，二分出到底是它本身死还是 `gc_initialize` 之后死 |

---

## 1. 三条铁律（违反任意一条 = 设备变砖或数据全灭）

1. **只允许 `fastboot boot`，严禁 `flash` / `erase` / `format`。** 这台机器是用户的日常主力机，全程 RAM 引导，断电即恢复。
2. **绝不自动重启设备。** 帧缓冲内容重启即失（进 Android 会重绘、进 fastboot 会换 UI）。固定协议：设备停屏 → **请用户拍照发来** → 你读完 → 说"可以重启" → 用户自己重启。
3. **一个构建只改一个变量。** 同时改两处，读到的现象就无法归因。

另：`fastboot` 序列号固定为 `3B1F67EA9BBUHK76`；挂死时长按电源重启（不是看门狗，历史上曾误判过一次）。

---

## 2. 已作废结论黑名单（**不要复活这些**）

以下每条都曾是"已锁定根因"，后来被真机实验推翻。文档里仍留着原文，遇到请直接跳过。

| 作废结论 | 出处 | 真相 |
| :--- | :--- | :--- |
| "KVA L2 块描述符内容错误（实读 `0xA30` ≠ 期望 `0xB00`）" | §7.16 | **假象**。v17/v18 实测 L2 条目为 `0xb0000701`，完全正确。真因是页粒度 + 后续 4KB 重构 |
| "16KB 页粒度可修（补丁 0083 修 TG1 私有编码）" | §7.15 | **硬件不支持**。`ID_AA64MMFR0_EL1 = 0x00001024`，`TGran16 == 0`，Oryon 只认 4KB（及 64KB） |
| "124 秒看门狗自动复位" | §7.x | 用户**手动重启**。系统不会自己回来 |
| "停点位置漂移 = 硬件随机性" | 多处 | `0012` 补丁因 `corrupt patch` 被 CI 整份跳过，stage 10~31 标记**从未编进内核** |
| "M6 已达成（早期虚拟内存与控制台交接）" | 里程碑报告 | 只达成 VM 侧；**console 接管未通**，已降级为"部分达成" |
| "`#include <kern/printf.h>`" | 0085 初版 | 该头**不存在**，`kprintf` 声明在 `pexpert/pexpert/pexpert.h:233` |

另附事实约束（不是结论，是环境限制）：
- 本机 `xnu-src` 是**残缺快照**（缺 `config/MASTER.arm64.sweet` 等），只能对 `osfmk/`、`pexpert/` 做 `git apply --check` dry-run，**无法完整本地试跑补丁序列**。
- 本机**无 aarch64 交叉工具链**（只有 Apple clang，缺 `ld.lld`），不能本地编 shim。
- 本机**无 `gh` CLI**，查 CI 用 GitHub REST API（公开库，未认证也够用）。

---

## 3. 当前死点的完整证据链（已交叉确证，不必重查）

`osfmk/arm/arm_init.c:516-571` 的真实调用顺序：

```
arm_vm_init()
  → serial_init()
  → startup_initialize_upto(STARTUP_SUB_KPRINTF)
  → kprintf("kprintf initialized")
  → kprintf("Serial mode specified: ...")
  → PE_create_console()          ← 内部调用 initialize_screen()
```

**重要**：屏幕停在第 3 行不是"很早死机"，而是 `arm_vm_init` + `serial_init` 都已成功，恰好死在 console 接管那一步。

`osfmk/console/video_console.c:2792+` 的 `initialize_screen()`，打印完 `b=FC800000 ...` 后立即执行：

```c
newMapSize   = round_page(2640 * 4864);                    // ≈ 12.8MB
newVideoVirt = ml_io_map_unmappable(0xfc800000, newMapSize, VM_WIMG_IO);
gc_initialize(&vinfo);
vc_progress_set();
gc_enable();
```

符号反查（`out/kernel.development.sweet.unstripped.yml`，73,277 个符号）得到 `initialize_screen+0xdc` 落在此处，与源码一致。

**这与 §11 修过的 "no PTE" panic 是同一族根因**：`sweet_fbcon` 已占 16MB，这里再要 12.8MB，早期 I/O 的 L3 页表池可能耗尽——区别在于这次没有 panic 出口，表现为静默冻结。

---

## 4. 已排除嫌疑（**不要重复怀疑**）

boot-args 随机性（`startup_debug=0x1` 反而更早停，已回退基线）· framebuffer 踩内核内存（ADT 中 fb 与 RAM 不重叠）· ADT 里 GIC 地址错（已用上游 `sm8750.dtsi` 核对：GICD `0x16000000`、GICR `0x16080000`、size `0x200000`、stride `0x40000`）· KASLR（未启用）· `+64MB` 导致内存饥饿（RAM 尚余 127MB）· `find_gicr_pe_base()` 死循环（上界 `gicr_size`，最多 16 次）· BSS 未清零（`shim/loader.c` 会清）

---

## 5. 观测链路（设备没有外部调试口）

- **无 UART、无 JTAG**；pstore/ramoops 需 root（BootShim 阶段拿不到）；Gunyah 下 EL2 日志不可达。
- **唯一通道**：framebuffer 物理 `0xfc800000`，1216×2640，stride 4864。
- **三种读取手段**：
  1. 用户整屏照片 → 多模态直接 OCR（能读 `SWDxx`/`SWExx` 与 `kprintf` 文本行）；
  2. 裁剪放大局部（小号 `iso_font` 8×16）；
  3. Pixel-level 读色带（自己写 PNG 解码，逐像素采样某格是红/绿/亮/灭）——抗模糊、抗反光，**比 OCR 可靠**。
- **当前检查点体系**：`0083` = 汇编层 `SWT`；`0084` = GIC `SWC01..SWC33`（`GICD_CTLR.RWP` 自旋已改 20 万次有界）；`0085` = console 接管 `SWD00..SWD07` / `SWE00..SWE03`；`0086` = 64×128 红色大数字阶段读数（远距离也能拍清）。

---

## 6. 开工自检（先跑这五条，再谈别的）

```bash
git -C ~/unixnu-pagani log --oneline -3              # 确认 HEAD 与状态卡一致
git -C ~/unixnu-pagani status --short                # 有无未提交改动
fastboot devices; adb devices                        # 设备在哪一侧
curl -s "https://api.github.com/repos/353154/unixnu-pagani/actions/runs?per_page=2" | grep -E '"(status|conclusion|head_sha)"' | head -8
cd ~/unixnu-pagani/xnu-src && git apply --check ../xnu/patches/0012-*.patch   # 补丁完整性
```

**每次改补丁后，必须验证它真的被应用了**：CI 日志里 grep `Skipping patch`。`0012` 曾因 hunk 计数错被静默跳过数轮，而构建一直 success —— 这是本项目最贵的一次教训。

推荐用仓库内脚本跑全链路（自动校验标记串是否真在内核里）：

```bash
python3 ~/unixnu-pagani/tools/auto_boot_pipeline.py --sha <commit>
```

它会拒绝引导"标记缺失"的构建，避免假象上真机。

---

## 7. 下一步该做什么（精确到文件）

1. 在 `osfmk/console/video_console.c` 的 `ml_io_map_unmappable` **调用前**插 `SWE04`、**返回后**插 `SWE05`。
2. 单变量构建 → 真机 → 读屏：
   - 停在 `SWE04`：死在这条映射调用内部；
   - 过了 `SWE05` 才停：死在 `gc_initialize` / `vc_progress_set` / `gc_enable`。
3. 若确认死在映射本身，两条修复路线（**优先 B**）：
   - **A 扩容**：`osfmk/arm64/arm_vm_init.c` 继续放大早期 I/O L3 池（现为 `va_l1_end += (64 << 20)`），覆盖 16MB + 12.8MB 叠加；
   - **B 复用**：让 `initialize_screen` 直接复用 `sweet_fbcon` 已建立的 16MB 映射（`v_info` 指向既有 VA），从根上消除第二次映射。
4. console 接管成功后：`arm_init()` 返回 → `machine_startup(&BootCpuData)` → Thread 0 接管 → 冲 M7 `kernel_bootstrap`。

---

## 8. 文档索引（按需读，别全读）

| 文件 | 用途 |
| :--- | :--- |
| 本文件 | **入口**，状态 + 铁律 + 黑名单 + 下一步 |
| `ONEPLUS_13S_XNU_PORTING_MILESTONE_REPORT.md` §五 | 里程碑总览、本轮关键修正、交接须知表 |
| `ONEPLUS_13S_XNU_PORTING_DEBUG_LOG.md` §8 | 交接手册（旧版快照已重写，§8.1 为权威状态） |
| 同上 §12-13 | 本轮：观测链路、`0012` 根因、死点确证 |
| 同上 §7.x | 历史攻坚全过程（**含大量已作废结论，慎读**） |
| `hardware_baseline.md` / `hardware_specs.md` | 硬件事实基线 |
