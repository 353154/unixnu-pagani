# XNU 移植接手须知（给新 Agent 的唯一入口）

> 你接手的是一个**正在进行的真机内核移植**，不是从零开始。
> 先读完本文件，再动手。**不要从 DEBUG_LOG 第一页顺序读**，那是 append-only 的历史，前面埋着已被推翻的结论。
>
> 项目：OnePlus 13s (`pagani` / SM8750 / Oryon 8 核) 移植 Apple XNU `xnu-8796.141.3`
> 运行环境：Gunyah Hypervisor NS-EL1
> 仓库：`~/unixnu-pagani`（GitHub `353154/unixnu-pagani`，main）
> 最后更新：2026-11-05 23:10
>
> **交接时只需移交本文件一份**（见下方「移交清单」）。不要整份粘贴 DEBUG_LOG。
>
> **本文件末尾 §9 是「文档维护契约」。它规定你该怎么更新这套文档、以及你再次交接时该做什么。动手前请一并读完——不按契约写，等于这一轮的结论对下一任不存在。**

---

## 移交清单（用户视角：换 Agent 时该给什么）

**只给一个文件就够：本文件。** 它不是摘要，是行动依据——状态、铁律、黑名单、证据链、下一步、自检命令全在里面。多给文件反而有害：DEBUG_LOG 有 1000 行且埋着 11 条已作废结论，整份粘过去，新 Agent 大概率会先信错的。

| 层级 | 给什么 | 为什么 |
| :--- | :--- | :--- |
| **必需** | `docs/XNU_HANDOFF_PROMPT.md`（本文件，桌面有同名副本） | 唯一入口，自包含 |
| **必需（非文件）** | 仓库路径 `~/unixnu-pagani` + 手机已连接 + 设备序列号 `3B1F67EA9BBUHK76` | 不动手就没法验证任何结论 |
| **按需** | `ONEPLUS_13S_XNU_PORTING_DEBUG_LOG.md` 的 **§14**（本轮实测）、`MILESTONE_REPORT.md` **§五** | 要追溯细节时再读，不要整份给 |
| **按需** | `hardware_baseline.md` / `hardware_specs.md` | 硬件事实，改动硬件相关代码前读 |
| **不要给** | DEBUG_LOG 全文、历史截图、聊天记录 | 含 11 条作废结论 + 大量已被推翻的推理，是最容易造成误判的输入 |

新 Agent 拿到本文件后，应能独立执行下面三条自检并复述出当前死点：

```bash
cd ~/unixnu-pagani && git log --oneline -3          # 现在到哪一版
ls xnu/patches/ | tail -5                            # 最近加了什么探针
~/.local/bin/… 2>/dev/null; adb devices; fastboot devices   # 设备在哪一侧
```

---

## 0. 三十秒状态卡

| 项 | 值 |
| :--- | :--- |
| 当前阶段 | **M7 接近完成**：`kmem_range_init` 已通过，`kernel_bootstrap` 跑到尾声（调度器/线程/IOKit 平台专家全部起来），卡在 console 接管之后 |
| 最新内核提交 | `651db40`（`0090` 跳过 video console 接管 + `SWV1/2/3` 活体探针）；`36ce59d` 是 `0089`（已验证生效） |
| 最新构建 | `36ce59d` / Run `42051760075` 已实测（23:15:39 引导）；`651db40` 构建中 |
| 屏幕最后一行 | `SWD07 gc_acquired`（console 接管分支末尾），之后无任何输出 |
| 死点 | `osfmk/console/video_console.c` 的 `initialize_screen()`，op=4 `kPEAcquireScreen`，调用点 `osfmk/kern/startup.c:709`。**它在函数内部是正常返回的**，死点在返回之后 |
| 已确认根因（上一关） | `zones` 一项索取 **128GB** VA（`ZONE_MAP_VA_SIZE` 走了 MacOSX 分支），`kernel_map` 仅 48,365MB → 减法无符号下溢。改 24GB 后已解 |
| 下一步动作 | 读 `SWV1/SWV2/SWV3`：确认跳过生效、`initialize_screen` 返回、是否进 `bsd_init` |

---

## 1. 四条铁律（前三条违反 = 设备变砖或数据全灭；第四条违反 = 下一任从零开始）

1. **只允许 `fastboot boot`，严禁 `flash` / `erase` / `format`。** 这台机器是用户的日常主力机，全程 RAM 引导，断电即恢复。
2. **绝不自动重启设备。** 帧缓冲内容重启即失（进 Android 会重绘、进 fastboot 会换 UI）。固定协议：设备停屏 → **请用户拍照发来** → 你读完 → 说"可以重启" → 用户自己重启。
3. **一个构建只改一个变量。** 同时改两处，读到的现象就无法归因。
4. **真机跑出的每条结论必须立刻落盘。** 只写在聊天里的结论，交接时等于不存在（细则见 §9.2）。

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
| "M6 已达成（早期虚拟内存与控制台交接）" | 里程碑报告 | 曾降级为"部分达成"；**23:15 实测已真正通过**（`initialize_screen` 走到了 `gc_acquired`） |
| "`#include <kern/printf.h>`" | 0085 初版 | 该头**不存在**，`kprintf` 声明在 `pexpert/pexpert/pexpert.h:233` |
| "`SWD01`~`SWD04` 没出现，说明 FB 映射失败" | §13.3 / 本轮初判 | **错**。它们位于 `if (boot_vinfo)` 内，而 `startup.c:709` 传的是 `NULL`，整段本来就跳过。本轮 `ml_io_map_unmappable` **一次都没被调用**，"第二次映射 12.8MB"这个担心在本轮不存在 |
| "屏幕自上而下就是执行顺序" | 本轮读屏 | **不成立**。`mac_policy_initmach`（源码在 `sched_init` 之后）出现在屏幕上 `sched_init` 之前。假设（未验证）：`sweet_fbcon`（serial 路径）与 XNU video console 同时向同一块 FB 绘制、各自维护光标，两个流交错 |
| "死点在 `initialize_screen` 的 `ml_io_map_unmappable`" | §13.3 | **已推翻**。真机实测 console 接管完全通过，一路跑到 `vm_swap_init`。当初误判是因为 stage 标记缺失、屏幕没有后续输出 |
| "屏幕最后一行 = 死点" | §13 方法论 | **本环境 `panic()` 不终止系统**，打印完继续往下跑。必须找"本该出现却没出现的下一行" |
| "`SWT In 6.1 0x...` 是死循环" | 本轮读屏 | 是 `0083` 对每个 `__startup_func` 的追踪（`SWT in <subsys>.<rank> <func>` / `SWT ok <func>`），底部重复几十行是正常的逐子系统初始化 |
| "`kernel_map->max_offset` 被 `0004` 压到 `0xFC0000000`，空间为 0" | §14.4 | **已推翻**。`SWK0` 实测 `max=ffffffff...`，是 64 位顶端量级。真因是 `claims ≈ 140.7GB` 撑爆可用空间后**减法下溢**（§14.6）。误判原因：只看编译期宏，没等运行时读数就写进了主叙事 |
| "claims 是某项 `kc_calculate_sz` 按物理内存算歪了" | §14.6 | **已推翻**。`zones` 的 128GB 是**编译期常量** `ZONE_MAP_VA_SIZE`（MacOSX 分支），根本没有运行时计算参与。误判原因：看到「13 项平均 10.8GB」就假设是计算错误，没先查注册点的尺寸来源 |

另附事实约束（不是结论，是环境限制）：
- 本机 `xnu-src` 是**残缺快照**（缺 `config/MASTER.arm64.sweet` 等），只能对 `osfmk/`、`pexpert/` 做 `git apply --check` dry-run，**无法完整本地试跑补丁序列**。
- 本机**无 aarch64 交叉工具链**（只有 Apple clang，缺 `ld.lld`），不能本地编 shim。
- 本机**无 `gh` CLI**，查 CI 用 GitHub REST API（公开库，未认证也够用）。

---

## 3. 当前进度与死点（真机实测，不必重查）

### 3.1 已经跑通的链路（`cc9b9d2`，Run `42042712579` 实测）

```
arm_vm_init → serial_init → startup_initialize_upto(KPRINTF)
  → kprintf("kprintf initialized")
  → kprintf("Serial mode specified: ...")
  → PE_create_console() / initialize_screen()        ← 已通过，不是死点
  → SWEET EARLY 28..31 → machine_startup
  → SWC32/SWC33 → kernel_bootstrap
  → XNU Kernel Version 22.6.0 (root:xnu-8796.141.3)
  → vm_map_bootstrap → vm_page_bootstrap(22701 free / 9811 wired pages)
  → zone_bootstrap → vm_object_bootstrap → vm_map_init(73 maps / 153 entries)
  → kmem_init → vm_swap_init("maximum number of VM swap files: 100")
```

**M6 已完成**：console 接管、真 `kprintf` 上屏、VM 子系统五级初始化全部通过。

### 3.2 上一关已通过：`kmem_range_init` 下溢（`0089` 修好，`36ce59d` / Run `42051760075` 实测）

**根因**：`zones` 一项索取 128GB VA。尺寸来自 `osfmk/kern/zalloc.c:10148` 的 `KMEM_RANGE_REGISTER_STATIC(zones, &zone_map_range, ZONE_MAP_VA_SIZE)`，而 `ZONE_MAP_VA_SIZE` 按平台分支：MacOSX = **128GB**，其它 = **24GB**。本构建走 MacOSX 分支 → 128GB 塞不进 47GB 的 `kernel_map` → `largest_free_size -= total_claims` 无符号下溢 → 所有 claim 的 size 变成 2⁶² 量级 → `locate` 必然失败。

**修法**：`0089` 把 MacOSX 分支的 `ZONE_MAP_VA_SIZE` 降为 24GB（`#undef` + `#define`，只改这一个宏）。实测 **panic 消失**，`kmem_range_init` 通过。

**顺带破掉一个历史谜团**：panic 的 claim 名在 `vm_ptr_range` / `kmem_data_range` 之间变化，是 `kmem_shuffle_claims()` 随机打乱顺序所致，**不是硬件随机性**。

### 3.3 新停点：console 接管之后（23:15 实测）

内核已经跑完 `kernel_bootstrap` 的绝大部分：

```
kmem_range_init ✔ → vm_swap_init ✔ → machine_lockdown ✔ → PE_lockdown_iokit ✔
→ platform expert registered ✔ → AppleKeyStore / IOWatchdog / IOCoreSurfaceRoot /
  HID buttons+touch / BATTERY / AppleCLCD(FB 1216x2640 stride 4864 @0xfc800000) 全部注册
→ sched_init ✔ → thread_group / coalitions / code_signing / task / thread /
  restartable / workq / turnstiles / exception / sfi ✔
→ kernel_thread_create ✔ → idle_thread_create ✔ → sched_startup ✔ → thread_daemon_init ✔
→ kdp_init ✔ → bootprofile_init ✔ → PE_init_kprintf ✔
→ "Boot version: sweet-shim" 、kext 检查（"panic" not a kext）
→ SWD00 isc op=4 kmap=1
→ SWD05 vc_progress_set delay=0 gfx=1
→ SWD06 gc_enable in
→ SWD07 gc_acquired        ← 最后一行
```

**死点位置**：`osfmk/console/video_console.c` 的 `initialize_screen()`，`op=4`（`kPEAcquireScreen`），调用点 `osfmk/kern/startup.c:709`。

**已确证**：`vc_progress_set` 和 `gc_enable` **都正常返回**（否则 `SWD06`/`SWD07` 不会打印）。所以死点只可能在它返回之后，即 `vm_commpage_init` → `kernel_startup_initialize_upto(LAST)` → `bsd_init` 这一段。

**两个关键事实**：

1. `SWD01`~`SWD04` 没有出现，不是故障。它们在 `if (boot_vinfo)` 内，而 `startup.c:709` 传的是 `NULL`，整段本来就跳过。**本轮 `ml_io_map_unmappable` 一次都没被调用**。
2. `gc_graphics_boot = TRUE`（`SWD05` 的 `gfx=1`），所以 `gc_enable(!graphics_now)` 拿到的是 `FALSE`，video console 把文本输出关掉了。

### 3.4 正在验证：`0090`（提交 `651db40`）

`initialize_screen()` 在 `kPEAcquireScreen` 时直接跳过 video console 接管，保留 `sweet_fbcon` 这条 serial 输出路径；同时 `gc_graphics_boot = TRUE` 让 `vcattach()` 不再重放整段 msgbuf。

三个探针：`SWV1`（跳过生效）、`SWV2`（`initialize_screen` 已返回）、`SWV3`（即将进 `bsd_init`）。

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
- **当前检查点体系**：`0083` = 汇编层 `SWT`；`0084` = GIC `SWC01..SWC33`（`GICD_CTLR.RWP` 自旋已改 20 万次有界）；`0085` = console 接管 `SWD00..SWD07` / `SWE00..SWE03`；`0086` = 64×128 红色大数字阶段读数（远距离也能拍清）；`0087` = kernel_map 边界 `SWK0..SWK3`（已完成使命）；`0088` = claim 明细 `SWQ0..SWQ12` + `SWG`（已完成使命，保留在核心里用于验证 `0089`）；`0089` = zone map VA 128GB→24GB（已解决问题）；`0090` = 跳过 video console 接管 + `SWV1`/`SWV2`/`SWV3` 活体探针（**当前在役**）。
- **读屏铁律**：**大数十六进制读不准**。凡是结论依赖具体数值的探针，一律打印十进制 MB/GB（`0088` 起执行）。色带与 MB 数比长十六进制可靠得多。

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

**校验标记自身也必须验证**（2026-11-05 实例）：曾把 `b"SWEET EARLY 31"` 写进 `REQUIRED_MARKS`，而内核里根本没有这个字面量——阶段号是 framebuffer 直绘，不走 `kprintf`。结果构建成功、`0088` 探针也确实在核心里，却被自己的校验器判红。**加标记前先 `blob.find()` 确认它存在**，否则校验器会变成新的误报源。

推荐用仓库内脚本跑全链路（自动校验标记串是否真在内核里）：

```bash
python3 ~/unixnu-pagani/tools/auto_boot_pipeline.py --sha <commit>
```

它会拒绝引导"标记缺失"的构建，避免假象上真机。

### 6.5 改一轮的完整闭环（照这个顺序，不要跳步）

```bash
# 1. 写补丁：放进 xnu/patches/，编号递增，前缀 sweet，文件名决定应用顺序
#    （CI 把 xnu/patches/*.patch 全部拷进 dxb/patches/，由 build.sh 按序应用）
~/unixnu-pagani/xnu/patches/0090-sweet-<一句话描述>.patch

# 2. 本机先验证能应用（xnu-src 是残缺快照，只对 osfmk/pexpert 有效）
cd ~/unixnu-pagani/xnu-src && git apply --check ../xnu/patches/0090-*.patch

# 3. 提交推送 —— 只有 xnu/patches/** 和 workflow 文件的改动才会触发 CI
cd ~/unixnu-pagani && git add xnu/patches/0090-*.patch && git commit -m "..." && git push

# 4. 挂全自动流水线（约 15 分钟构建，之后自动下载→校验标记→合成→引导）
python3 ~/unixnu-pagani/tools/auto_boot_pipeline.py --sha $(git rev-parse --short HEAD)

# 5. 设备停屏 → 请用户拍照 → 读屏 → 结论落盘（§9.2）
```

两条关键事实：

- **CI 只监听 `xnu/patches/**` 与 workflow 文件。** 改 `docs/` 不会触发构建，所以文档可以随时提交；反过来，如果推了补丁却十分钟没动静，先看改动路径对不对。
- **`xnu-src` 是残缺快照**（缺 `config/MASTER.arm64.sweet` 等），本地无法完整编译，只能做 `git apply --check`。真正的编译只在 CI 的 `macos-14` 上发生，本地没有可用交叉工具链。

---

## 7. 下一步该做什么（精确到文件）

### 7.1 当前这一轮：验证 `0090` 是否把死点推过 `bsd_init`

`0090-sweet-skip-video-console.patch`（提交 `651db40`）在 `initialize_screen()` 的 `kPEAcquireScreen` 分支开头直接返回，跳过整个 video console 接管；并在两个位置加了活体探针。

看三行，按出现与否分支：

| 标记 | 出现说明 | 不出现说明 |
| :--- | :--- | :--- |
| `SWV1 video console skipped serial=..` | 跳过生效 | `0090` 没应用，或 op 不是 4 |
| `SWV2 initialize_screen returned` | 接管**不是**死点 | 死点就在 `initialize_screen` 内部（与我们前面的推断矛盾，需重查） |
| `SWV3 entering bsd_init` | `kernel_bootstrap` 跑完，**M7 达成** | 死点在 `vm_commpage_init` → `kernel_startup_initialize_upto(LAST)` 之间 |

`SWV1` 里的 `vbase=` 还顺带给出 `vinfo.v_baseaddr`——若它与 `0xfc800000` 同级，说明 XNU 拿到的是物理地址当虚拟地址用，这正是之后要做真图形控制台时必须先解决的问题。

### 7.2 按结果分支

- **`SWV3` 出现** → M7 完成。下一步是 `bsd_init`：要准备 root ramdisk，否则会在 `bsd_init` 里因为找不到根设备而 panic 或卡住。这是 M9 的入口，提前把 ramdisk 方案想好。
- **`SWV2` 出现、`SWV3` 不出现** → 死点在 `vm_commpage_init` / `mac_policy_initmach` / `dtrace` / `trust_cache` / `OSKextRemoveKextBootstrap` / `kernel_startup_initialize_upto(LAST)` 这几步之间。这六步已有 `kernel_bootstrap_log`，屏幕上一比就能定位。
- **只有 `SWV1`、没有 `SWV2`** → 说明 `initialize_screen` 里还有别的路径会挂（例如 `pmap_remove` 或 `kmem_free` 分支），回到函数体内二分。
- **一个 `SWV` 都没有** → 补丁没进内核。先看流水线的 `MARK SWV1` 是否为负。

### 7.3 通过之后

`bsd_init`（M9，需要 ramdisk/UFS）→ 8 核 PSCI（M8）→ launchd（M10）。

**同时值得评估**：本构建为什么走 `XNU_PLATFORM_MacOSX` 分支。`0089` 只打了一个宏补丁，没改平台判定；若后续再遇到「Mac 有、iOS 没有」的常量差异（zalloc / IOKit / 驱动加载路径上还有若干处），应整体切到 iOS 平台配置。**但那是一次大改，必须单独一轮、单独归因。**

### 7.4 顺手该修的（不阻塞主线）

1. `SWT in X.2147483647` 说明某条 `__startup_func` 描述的 `rank` 未初始化（`INT_MAX` 哨兵）。
2. `SWT` 输出淹了半屏，建议进入 `kernel_bootstrap` 后关掉，恢复读屏信噪比。
3. **屏幕行的顺序与执行顺序不一致**（见黑名单最后一条），在真正实现图形控制台之前，读屏时要按"内容"而不是按"位置"判断进度。

---

## 8. 文档索引（按需读，别全读）

| 文件 | 用途 |
| :--- | :--- |
| 本文件 | **入口**，状态 + 铁律 + 黑名单 + 下一步 |
| `ONEPLUS_13S_XNU_PORTING_MILESTONE_REPORT.md` §五 | 里程碑总览、本轮关键修正、交接须知表 |
| `ONEPLUS_13S_XNU_PORTING_DEBUG_LOG.md` §8 | 交接手册（旧版快照已重写，§8.1 为权威状态） |
| 同上 §12-13 | 本轮：观测链路、`0012` 根因、死点确证 |
| 同上 §7.x | 历史攻坚全过程（**含大量已作废结论，慎读**） |
| 本文件 §9 | **文档维护契约**：写入权限、强制落盘时机、证据要求、推翻旧结论的三步、交接自检 |
| `hardware_baseline.md` / `hardware_specs.md` | 硬件事实基线 |

---

## 9. 文档维护契约（接手后必须遵守）

这一节是**自指**的：它规定你怎么写文档，也规定你再次交接时该做什么。

本项目最贵的两次事故都不是技术问题——一次是补丁被 CI 静默跳过、连续多轮被当成硬件现象；一次是把"最后一行的 `kprintf`"当成死点。两次的共性都是**文档没跟上实测**，而下一个读文档的人只能相信文档。

### 9.1 三份文件，三种写入权限

| 文件 | 权限 | 规则 |
| :--- | :--- | :--- |
| `DEBUG_LOG.md` | **只追加** + 允许插勘误块 | 绝不改写已有正文；章节号递增（当前到 §14）；推翻旧结论时在**原处**插入 `> ⚠️ 勘误（YYYY-MM-DD）：本条已作废，见 §N。真相：…`，原文保留 |
| `XNU_HANDOFF_PROMPT.md`（本文件） | **原地重写** | 状态卡 / 黑名单 / 死点 / 下一步必须永远是"此刻最新"，不留历史——历史归 DEBUG_LOG |
| `MILESTONE_REPORT.md` | 原地重写 | 只放里程碑级状态，不放过程；只有 M 编号的状态变化才动它 |

分界线：**"发生了什么"写 DEBUG_LOG，"现在在哪、下一步做什么"写本文件。**

### 9.2 什么时候必须写（四个强制触发点）

不是"有空再写"，任意一条命中就得落盘，写完再继续下一个动作：

1. **真机跑出结论后**（无论证实还是推翻）→ DEBUG_LOG 新章节 + 本文件状态卡/黑名单
2. **死点发生变化后** → 本文件 §0 状态卡 + §3 立即改
3. **每轮构建推送前** → 核对文档里的"最新提交/最新 Run"是不是真的
4. **交给用户或下一个 agent 之前** → 跑 §9.5 自检

判断标准只有一句：**如果这一轮的结论只存在于聊天记录里，那它在交接时就等于不存在。**

### 9.3 每条结论必须带证据

不接受"应该是 / 可能是 / 大概率"。写进文档的结论必须附至少一项可复核物证：

| 证据类型 | 写法示例 |
| :--- | :--- |
| 屏幕原文 | `initialize_screen: b=FC800000, w=000004C0 …`（用户照片 2026-11-05 22:14） |
| 内核中字符串存在 | `b"SWE00" @ offset 513629`（`auto_boot_pipeline.py` 校验输出） |
| 提交 / Run | `d3c06d7` / Run `42045809346` |
| 源码行号 | `osfmk/vm/vm_kern.c:3645` |
| 硬件寄存器读数 | `ID_AA64MMFR0_EL1 = 0x00001024`，`TGran16 == 0` |
| 上游对照 | 高通 `sm8750.dtsi`：GICD `0x16000000`、GICR `0x16080000` |

**未经验证的假设必须显式标注**：写成 `假设（未验证）：… 验证手段：…`，不许写成"根因"。验证完成后要么升级为结论并附证据，要么原样挪进黑名单。

### 9.4 推翻旧结论的固定动作（三步，缺一不可）

1. **DEBUG_LOG 原处插勘误块**，不改原文——保留错误结论是为了让后人看见"当时是怎么想错的"
2. **本文件 §2 黑名单加一行**：作废结论 / 出处 / 真相 / **当时为什么会误判**
3. 若该误判有方法论价值，DEBUG_LOG 里单独写一段"教训"

第 2 步最后那一列最容易漏，也最值钱。例如"死点在 `ml_io_map_unmappable`"这条，误判原因是**补丁静默未生效 → stage 标记缺失 → 屏幕没有后续输出**。不写这个原因，下一个人换个死点还会犯同样的错。

### 9.5 交接前自检（五条，全过才算交接完成）

```bash
# 1 状态卡里的提交与 Run 是真的
git -C ~/unixnu-pagani log --oneline -3
curl -s "https://api.github.com/repos/353154/unixnu-pagani/actions/runs?per_page=2" \
  | grep -E '"(status|conclusion|head_sha)"' | head -6

# 2 本轮结论已落盘（不是只在上面的聊天里）
grep -n "2026-11-05" ~/unixnu-pagani/docs/ONEPLUS_13S_XNU_PORTING_DEBUG_LOG.md | tail -5

# 3 桌面副本与仓库一致（用户的视口是桌面）
diff -q ~/unixnu-pagani/docs/XNU_HANDOFF_PROMPT.md ~/Desktop/XNU_HANDOFF_PROMPT.md

# 4 补丁完整性没被本轮改动破坏
cd ~/unixnu-pagani/xnu-src && git apply --check ../xnu/patches/00*.patch 2>&1 | head
```

第 5 条是人工判断，两个问题：

- **本轮推翻过什么？** → §2 黑名单里必须有对应行，没有就是漏了。
- **§7 的"下一步"是具体动作吗？** → 若还写着"继续分析""进一步排查"，说明文档没写完，下一个 agent 会从这里开始迷路。

### 9.6 你再次交接时必须做的事（只需三件）

不必重写文档，只做：

1. 更新本文件 **§0 状态卡 + §2 黑名单 + §3 死点 + §7 下一步**——这四节就是交接的全部有效内容
2. 同步桌面副本（用户视口）：
   ```bash
   cp ~/unixnu-pagani/docs/XNU_HANDOFF_PROMPT.md \
      ~/unixnu-pagani/docs/ONEPLUS_13S_XNU_PORTING_DEBUG_LOG.md ~/Desktop/
   ```
3. 把 `~/Desktop/粘贴给新Agent.txt` 里"当前节点"那段同步成本轮结论

然后把 §0 状态卡第一行改成新时间，并确认 `git log -1` 与状态卡一致。

### 9.7 禁止事项

- ❌ 只在聊天里说、不写进文档
- ❌ 把假设写成根因（这是黑名单里一半条目的来源）
- ❌ 删除或改写 DEBUG_LOG 旧正文（只能追加 + 插勘误块）
- ❌ 状态卡留旧提交号（新 agent 踩的第一个坑，也是最容易发现的坑）
- ❌ 写"待补充 / TODO"却不写"谁在什么条件下补"
- ❌ 把文档改动和补丁改动放进同一个提交——文档必须提交在 `docs/` 下，不混入 `xnu/patches/`，否则会触发一轮不必要的构建
