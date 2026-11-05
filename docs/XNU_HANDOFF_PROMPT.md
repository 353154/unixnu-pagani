# XNU 移植接手须知（给新 Agent 的唯一入口）

> 你接手的是一个**正在进行的真机内核移植**，不是从零开始。
> 先读完本文件，再动手。**不要从 DEBUG_LOG 第一页顺序读**，那是 append-only 的历史，前面埋着已被推翻的结论。
>
> 项目：OnePlus 13s (`pagani` / SM8750 / Oryon 8 核) 移植 Apple XNU `xnu-8796.141.3`
> 运行环境：Gunyah Hypervisor NS-EL1
> 仓库：`~/unixnu-pagani`（GitHub `353154/unixnu-pagani`，main）
> 最后更新：2026-11-06 00:56（`0094` 实测跨过 `IOKitInitializeTime`，连过 12 个子系统后停在 `skywalk_init()`；`0095` 已下发。本轮另增 §3.0 可达性表、`tools/test_boot_gate.py`、`tools/refresh_status.py`）
>
> **交接时只需移交本文件一份**（见下方「移交清单」）。不要整份粘贴 DEBUG_LOG。
>
> **本文件末尾 §9 是「文档维护契约」。它规定你该怎么更新这套文档、以及你再次交接时该做什么。动手前请一并读完——不按契约写，等于这一轮的结论对下一任不存在。**

---

## 移交清单（用户视角：换 Agent 时该给什么）

**只给一个文件就够：本文件。** 它不是摘要，是行动依据——状态、铁律、黑名单、证据链、下一步、自检命令全在里面。多给文件反而有害：DEBUG_LOG 有 1000 行且埋着 11 条已作废结论，整份粘过去，新 Agent 大概率会先信错的。

| 层级 | 给什么 | 为什么 |
| :--- | :--- | :--- |
| **必需** | `docs/XNU_HANDOFF_PROMPT.md`（本文件；归档副本在 `~/Documents/OnePlus13s-XNU移植/`） | 唯一入口，自包含 |
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
| 当前阶段 | **M9 推进中（2026-11-06 00:48 实测）**：`bsd_init()` 越过 `IOKitInitializeTime`，一口气跑过 `vfsinit` → MAC 策略（AMFI / Sandbox / HFS）→ `mbinit` → `audit/knote/eventhandler/aio/pshm/psem` → `nwk_wq/dlil/socketinit/domaininit`，停在 `skywalk_init()` 内部。**这是 M7 之后单轮推进最远的一次，跨过 12 个子系统** |
| 最新内核提交 | `1a92e67`（`0095`：skywalk 内部 + 挂根全链路打点 `SWX1..8` / `SWY2..9` / `SWA1..2`），**构建中** |
| 最新构建 | `fcb0a59`（`0094`）/ Run `62` success，**已实测**；`1a92e67` 的 Run 待查 |
| 最新引导 | `fcb0a59` 00:48 引导（台账原记为 `boot_failed`，已按屏幕实证更正为 `booted`）；`1a92e67` 构建完将自动引导 |
| 屏幕最后一行 | `skmem_region_init  seg_size 16384, md_seg_size 16384, drv_buf_seg_size 65536 [eff 65536], usr_buf_seg_size 16384`（`bsd/skywalk/mem/skmem_region.c:374` 的 `SK_ERR`），此后只有彩条、无任何文字 |
| 死点 | `skywalk_init()` 内部、`skmem_region_init()` 的 `SK_ERR` 之后。三条候选，全都没有输出：`thread_call_allocate_with_options`（失败会 panic，但无 panic 输出）、`skmem_cache_create("sg")`、`skmem_dispatch`（排延迟 thread call，**需要定时器中断**）。`0095` 的 `SWX5..SWX8` 一次分开 |
| 已确认根因（前四关） | ① `zones` 索取 128GB VA 致 kmem claims 下溢（`0089`）；② video console 用未映射的 `vinfo.v_baseaddr` 绘制（`0090`）；③ `kperf_init_early` → `ml_wait_max_cpus()` 永久睡眠，置位者只被不存在的 IOKit CPU 驱动调用（`0092`）；④ `IOKitInitializeTime` 等不存在的 `IORTC`（`0094`，**已验证通过**：`SWT2`/`SWT4` + `calling vfsinit` 全部出现） |
| 下一步动作 | 读 `SWX1..SWX8`，**编号最大的即死点**。出现 `SWX4` = `skywalk_init` 已返回，继续看 `SWY2..`；出现 `SWA2` = 已到 `vfs_mountroot` 门口，**下一步必须准备 ramdisk，不是继续改代码** |
| 台账快照 | 自动生成 11-06 00:56 · HEAD `1a92e67` · 最新 CI Run 63 `1a92e67` in_progress · 最近引导 `fcb0a59` 00:48:05 booted |

---

## 1. 四条铁律（前三条违反 = 设备变砖或数据全灭；第四条违反 = 下一任从零开始）

1. **只允许 `fastboot boot`，严禁 `flash` / `erase` / `format`。** 这台机器是用户的日常主力机，全程 RAM 引导，断电即恢复。
2. **绝不自动重启回 Android；但引导测试已获授权可以自动，且必须幂等。** 帧缓冲内容重启即失（进 Android 会重绘、进 fastboot 会换 UI）。**2026-11-06 起用户明确授权：构建一结束就自动下载、合成并引导**，不必每轮等一句"开始"。边界是：
   - ✅ **自动做**：`adb reboot bootloader` + `fastboot boot`（RAM 引导，不写分区）
   - ❌ **绝不自动做**：boot 完之后重启回系统。停屏 → **请用户拍照发来** → 你读完 → 说"可以重启" → 用户自己重启
   - ⚠️ **例外**：若上一轮屏幕**还没拍照**，脚本加 `--no-boot`，只备镜像不碰设备，否则会把没读的证据冲掉
   - 🔒 **同一提交只引导一次**（2026-11-06 00:29 新增，代价是白白多引导一轮）：每次引导写一行台账到 `out/boot_history.jsonl`，同一 `sha` 已 `booted` 就直接退出，除非 `--force`。看到 CI success **不等于**需要再引导一次——先查台账。
   - ⏱ **设备不可见时立刻停**：adb 与 fastboot 都看不到设备，最常见原因是 XNU 正在跑（USB 不枚举）。此时重试引导毫无意义，脚本立即退出（返回码 4），应先拍照读屏。
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
| "屏幕上方还印着 `vnguard_policy_init` / `PE: platform expert registered`，说明本轮已跑过这些" | 23:35 读屏 | **不成立**。FB 控制台（`0003` 的 `fbcon_*`）是**环形缓冲**：写满 `fbcon_rows`（2640/32 = 82 行）后绕回顶部覆盖，且上一轮的像素不会被清干净。所以屏幕上同时存在"本轮旧位置"和"上轮残留"两种行。**判进度只认编号单调递增的新标记**（如 `SWP3`），不认行位置 |
| "`kernel_map->max_offset` 被 `0004` 压到 `0xFC0000000`，空间为 0" | §14.4 | **已推翻**。`SWK0` 实测 `max=ffffffff...`，是 64 位顶端量级。真因是 `claims ≈ 140.7GB` 撑爆可用空间后**减法下溢**（§14.6）。误判原因：只看编译期宏，没等运行时读数就写进了主叙事 |
| "claims 是某项 `kc_calculate_sz` 按物理内存算歪了" | §14.6 | **已推翻**。`zones` 的 128GB 是**编译期常量** `ZONE_MAP_VA_SIZE`（MacOSX 分支），根本没有运行时计算参与。误判原因：看到「13 项平均 10.8GB」就假设是计算错误，没先查注册点的尺寸来源 |
| "`using 462 buffer headers` 是 `mbinit` 的输出，死点在 `mbinit` 之后" | §14.10 | **顺序写反了**。该行由 `bsd_bufferinit()`（`bsd_init.c:681`）→ `bufinit()`（`vfs_bio.c:2220`）打印；`mbinit()` 在 705 行，排在 `IOKitInitializeTime`(687) 和 `vfsinit`(691) **之后**。误判原因：日志宏被关掉时用"最后一行输出"直接对到了下一个调用，没去源码核打印点 |
| "屏幕上的 `SWEET FB: ... presented as 1216x2640` 是本轮最新输出，所以卡在 FB" | 00:33 读屏 | **不成立**。它是 `AppleCLCD::start()` 的收尾日志（`0061` 补丁第 54 行，紧跟 `registerService()`），而 `start()` 只可能在 `bsd_init` **之前**的 IOKit 匹配阶段执行。出现在 `calling IOKitInitializeTime` 之后纯属环形缓冲残留。另外 OCR 把 `SWEET` 读成了 `MEET`，差点按错前缀 grep——**照片里的字符串先用产物内核 `strings` 核一遍** |
| 「`fastboot boot` 返回空输出 = 引导失败」 | 00:48 台账 | **误判**。设备刚重枚举时 fastboot 可能已经把内核交出去、随即离开 fastboot 模式，命令没有任何回显。真判据是**设备还在不在 fastboot**：走了就说明内核接手了。`fcb0a59` 因此被误记为 `boot_failed`，实际跑得好好的。修法见 `tools/auto_boot_pipeline.py` 的 `sh_all()` 与 `boot_unconfirmed` |
| 「`SWT1 t=184837626` 比 `SWT3 t=184039920` 还大，说明 `mach_absolute_time` 倒退 / 定时器异常」 | 00:48 读屏 | **OCR 误读**。`mach_absolute_time` 单调递增，不可能倒退。实际是 `184037626`，第二个 `0` 被读成 `8`。凡单个数字读数与单调性相矛盾，先怀疑读错，不要先怀疑内核 |
| 「日志停在 `skmem_region_init` 的那行 `SK_ERR`，所以死点就在打印语句里」 | 00:51 读屏 | **位置对、归因错**。那行只是该函数里最后一条**有输出**的语句，其后还有三步（`thread_call_allocate`、`skmem_cache_create`、`skmem_dispatch`）本来就不打印。死点在它们之中，`0095` 的 `SWX5..SWX8` 才能分开 |

另附事实约束（不是结论，是环境限制）：
- 本机 `xnu-src` 是**残缺快照**（缺 `config/MASTER.arm64.sweet` 等），只能对 `osfmk/`、`pexpert/` 做 `git apply --check` dry-run，**无法完整本地试跑补丁序列**。
- 本机**无 aarch64 交叉工具链**（只有 Apple clang，缺 `ld.lld`），不能本地编 shim。
- 本机**无 `gh` CLI**，查 CI 用 GitHub REST API（公开库，未认证也够用）。

---

## 3. 当前进度与死点（真机实测，不必重查）

### 3.0 可达性表（回退时看这张，别凭记忆）

每一轮都在往前顶，但补丁之间会互相影响。**如果新提交反而比旧提交更早挂**，说明
这一轮引入了回归，应当按这张表回退到"最远记录"，而不是在坏版本上继续修。

| 提交 | 关键补丁 | 最远到达 | 判读依据（屏幕实证） |
| :--- | :--- | :--- | :--- |
| `36ce59d` | `0089` zones 降 24GB | `initialize_screen()` 内部 | 最后一行 `SWD07 gc_acquired` |
| `651db40` | `0090` 跳过 video console | `mac_policy_initmach()` | `SWV1` + `SWV2` 出现，`SWV3` 无 |
| `0df72ad` | `0091` SWP1..11 打点 | `kperf_init_early()` | `SWP11` 出现（尾巴全通） |
| `f2d805e` | `0092` 放开 max_cpus | `bsd_init()` 内 `bsd_bufferinit` 后 | `SWV3` + `using 462 buffer headers` |
| `231550f` | `0093` 打开 DEBUG_BSDINIT | `IOKitInitializeTime()` | `bsd_init: calling IOKitInitializeTime` |
| `fcb0a59` | `0094` 跳过 IORTC 等待 | `skywalk_init()` 内 `skmem_region_init` 之后 | `SWT1..SWT4` + `calling vfsinit` + `calling skywalk_init` |
| `1a92e67` | `0095` skywalk/挂根打点 | **待测**（`SWX1..8` / `SWY2..9` / `SWA1..2`） | — |

**当前最远记录：`fcb0a59`。** 它一次性跨过 `vfsinit` → MAC 策略 → `mbinit` → `audit`/`knote`/`aio` → `socketinit`/`domaininit` 共十二章，停在 `skywalk_init()` 内部。任何回退都以它为准。

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

### 7.1 当前这一轮：验证 `0095` 把死点缩到单条语句

`0094` 已实测通过，不要再回头验证 `SWT`：`SWT1..SWT4` 全部出现，其后打出 `calling vfsinit`，再连过 12 个子系统，停在 `skywalk_init()` 内部、`skmem_region_init()` 的 `SK_ERR` 之后。

`0095`（`1a92e67`）在这一段连打 18 个标记。**判读规则仍然只有一条：屏幕上编号最大的那个就是死点。**

| 标记 | 位置 | 出现即证明 |
| :--- | :--- | :--- |
| `SWX1` | `skmem_cache_pre_init()` 之后 | 第一步过 |
| `SWX2` | `skmem_region_init()` 之后 | **region_init 整个返回了** |
| `SWX3` | `skmem_cache_init()` 之后 | cache_init 过 |
| `SWX4` | `pp_init()` 之后 | `skmem_init` 全通 |
| `SWX5` | `TAILQ_INIT(&skmem_region_head)` 之后 | 进入了可疑区 |
| `SWX6` | `thread_call_allocate_with_options()` 成功之后 | 线程调用分配成功 |
| `SWX7` | `skmem_cache_create("sg", ...)` 之后 | sg cache 建成 |
| `SWX8` | `skmem_dispatch(...)` 之后 | **`skmem_region_init()` 跑到底** |
| `SWY2` | `(void) skywalk_init();` 之后 | **`skywalk_init` 返回了** |
| `SWY3`/`SWY4` | `necp_init` / `netagent_init` 之后 | NECP、netagent 过 |
| `SWY5` | `memorystatus_init()` 之后 | 内存状态机过 |
| `SWY6` | `sysctl_mib_init()` 之后 | sysctl MIB 过 |
| `SWY7` | `bsd_autoconf()` 之后 | 自动配置过 |
| `SWY8` | `net_init_run()` 之后 | 网络初始化回调跑完 |
| `SWY9` | `inittodr(0)` 之后 | 时间设定过 |
| `SWA1` | `setconf()` 之后 | **已选定根设备** |
| `SWA2` | `vfs_mountroot()` 调用前 | **已到挂根门口** |

**按结果分支（左列命中即为结论）：**

| 现象 | 结论与下一步 |
| :--- | :--- |
| `SWX5` 有、`SWX6` 无 | `thread_call_allocate_with_options()` 挂住。查 thread_call 子系统是否已初始化（`thread_call_initialize` 在 `kernel_bootstrap` 里，若有条件编译差异需核对） |
| `SWX6` 有、`SWX7` 无 | `skmem_cache_create("sg")` 挂住。查 `sg` 这个 skmem_cache 的 zone/segment 分配路径 |
| `SWX7` 有、`SWX8` 无 | `skmem_dispatch()` 挂住。它是 `thread_call_enter_delayed`，**说明延迟定时器排不进去 —— 也就是说"deadline 唤醒"确实有问题**，这会同时解释 `0094` 为什么只能靠跳过 RTC 绕开。优先级最高的一类根因 |
| `SWX8` 有、`SWX2`/`SWX3` 无 | `skmem_region_init` 返回或 `skmem_cache_init` 内部挂。二分 `skmem_cache_init` |
| `SWX4` 有、`SWY2` 无 | `skywalk_init()` 返回路径挂（`skmem_sys_region_init` 等后续步骤） |
| `SWA2` 出现 | **已到 `vfs_mountroot`。这一关的性质变了：不是 bug，是缺 ramdisk。立刻转 M9 准备根文件系统，不要再改内核代码** |
| 一个 `SWX` 都没有 | `0095` 没进内核，看流水线 `MARK SWX1` 是否为负 |
| 卡在 `SWA1` 与 `SWA2` 之间 | `setconf()` 内选根设备挂住，查 `bsd_autoconf` 注册的 `mountroot` |

`bsd_init()` 关键序列（行号对 `bsd/kern/bsd_init.c`，**状态截至 `fcb0a59` 实测**）：

| 行 | 调用 | 状态 |
| :--- | :--- | :--- |
| 570 | `mac_policy_initbsd()` | ✅ `MAC Framework successfully initialized` |
| 681 | `bsd_bufferinit()` | ✅ `using 462 buffer headers` |
| 687 | `IOKitInitializeTime()` | ✅ `SWT1..SWT4`（`0094` 已解） |
| 691 | `vfsinit()` | ✅ AMFI / Sandbox / HFS 全注册 |
| 705 | `mbinit()` | ✅ `mbinit: done [64 MB total pool size]` |
| 713–745 | `audit_init` → `knote_init` → `eventhandler_init` → `aio_init` → `pshm/psem` → `nwk_wq` → `dlil_init` | ✅ 全部出现 |
| 749–752 | `socketinit()` / `domaininit()` | ✅ 全部出现 |
| 760 | `skywalk_init()` | 🔴 **当前死点**：`skmem_region_init()` 的 `SK_ERR` 之后 |
| 765–789 | `necp_init` / `netagent_init` / `memorystatus*` / `sysctl_mib_init` / `bsd_autoconf` | ❓ `0095` 的 `SWY*` 覆盖 |
| 856 | `inittodr(0)` | ❓ `SWY9` |
| 868 | `setconf()` | ❓ `SWA1` 选根设备 |
| 870 | `vfs_mountroot()` | ❓ `SWA2`，失败进 `while (TRUE)` 无限重试 |

> ⚠️ 唯一容易搞错的地方：`using 462 buffer headers`（`bsd_bufferinit`）在 `IOKitInitializeTime` **之前**，真正的 `mbinit: done` 在其**之后**。§14.12 曾把两者弄反，§14.13 已用实测纠正。

### 7.2 通过之后：先备 ramdisk，再谈 8 核

`0095` 一旦打出 `SWA2`，主线就从「修内核」切换到「备根文件系统」。这两件事的
排查方式完全不同：前者读源码定位语句，后者是准备一个交付物。

**M9 的第一件事不是写代码，是准备 root ramdisk**：`vfs_mountroot()` 失败会清空
`rootdevice` 后 `while (TRUE)` 重试，屏幕上会不断刷 `cannot mount root, errno = N`。
看起来像新死点，其实是没有可挂的东西。要么用 boot_args 的 `-md` 注入内存根盘，
要么从 UFS 切一个最小分区。**这一步必须在撞上之前就开始准备，不能等它挂住再救。**

后续里程碑：8 核 PSCI（M8）→ launchd 及 libSystem（M10）。

**M8 的入手点已经测出来了**：`SWP12` 打出 `wait_max_cpus n=1`，说明 `machine_info.max_cpus` 现在是 **1**——PE 只枚举了一个 CPU。这不是配置问题，是没有 `AppleARMSMP` 平台驱动来上报 CPU topology。做 M8 时从这里开始，而不是从 PSCI 汇编开始。

**同时值得评估**：本构建为什么走 `XNU_PLATFORM_MacOSX` 分支。`0089` 只打了一个宏补丁，没改平台判定；若后续再遇到「Mac 有、iOS 没有」的常量差异（zalloc / IOKit / 驱动加载路径上还有若干处），应整体切到 iOS 平台配置。**但那是一次大改，必须单独一轮、单独归因。**

### 7.3 顺手该修的（不阻塞主线）

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

### 9.2 什么时候必须写（步骤级同步，不是每轮同步）

**粒度是"一步"，不是"一轮"。** 用户 2026-11-06 00:18 明确要求：**每做一步就同步文档，不许攒到一轮结束再回填。**

"一步"的定义是**对外可见状态发生变化的最小动作**，不是每敲一条命令：

| 你刚做完的动作 | 立刻要写什么 | 写到哪 |
| :--- | :--- | :--- |
| 写完一个补丁 | 补丁名 + 它要验证什么 + 怎么判读（出现哪个标记代表什么） | 本文件 §7 |
| 提交并推送 | 状态卡「最新内核提交」 | 本文件 §0 |
| 下发构建 | 状态卡「最新构建」+ Run 号 | 本文件 §0 |
| 构建完成、标记校验 | `MARK xxx <offset>` 读数（负数 = 没编进内核） | DEBUG_LOG 本轮小节 |
| 真机引导 | 引导时刻（精确到秒）+ 台账行 | DEBUG_LOG 本轮小节；`out/boot_history.jsonl` 自动记录 |
| 读到屏幕结论 | 屏幕原文 + 结论 + 证据类型 | DEBUG_LOG 新章节；同时改 §0 / §2 / §3 |
| 用户提出新规则/新协议 | 用户原话的意思 + 生效时间 | 本文件对应章节（如 §1） |
| 交接前 | 跑 §9.5 五条自检 | — |

**唯一允许延后的情形**：连续动作尚未产生读数（例如补丁刚推、构建还没完）。此时只更新 §0 的「最新提交 / 最新构建」两行，结论等读数到手再一次性写全。除此以外不许压着。

**为什么定这么细**：本项目最贵的两次事故形态完全一样——聊天里已经报了新结论，文档里还停在上一轮，下一个读文档的人（包括三天后的你自己）直接踩空。压着不写的成本不在写的时候显现，在交接的时候一次性爆发。

**长命令必须可观测**（2026-11-06 00:29 教训）：任何可能跑过 60 秒的命令，**一律后台执行 + 分阶段各打一行**（轮询中 → 下载完 → 校验完 → 已引导）。不要用前台 + `tail`：前台无输出时用户看到的就是"你卡死了"，而且被管道吞掉的中间行事后也查不到。同一提交被重复引导那次，就是"看不到进度、也不知道引导过没有"两个问题叠出来的。

配套命令见 §9.6：`tools/sync_docs.sh` 一条命令完成「同步归档 + 提交 + 推送 + 一致性自检」，让"及时同步"不因为麻烦而被跳过。

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

# 3 归档副本与仓库一致（2026-11-05 起桌面已清空，改放文稿）
diff -q ~/unixnu-pagani/docs/XNU_HANDOFF_PROMPT.md \
        ~/Documents/OnePlus13s-XNU移植/XNU_HANDOFF_PROMPT.md

# 4 补丁完整性没被本轮改动破坏
cd ~/unixnu-pagani/xnu-src && git apply --check ../xnu/patches/00*.patch 2>&1 | head
```

第 5 条是人工判断，两个问题：

- **本轮推翻过什么？** → §2 黑名单里必须有对应行，没有就是漏了。
- **§7 的"下一步"是具体动作吗？** → 若还写着"继续分析""进一步排查"，说明文档没写完，下一个 agent 会从这里开始迷路。

### 9.6 你再次交接时必须做的事（只需三件）

不必重写文档，只做：

1. 更新本文件 **§0 状态卡 + §2 黑名单 + §3 死点 + §7 下一步**——这四节就是交接的全部有效内容
2. 一条命令同步全部副本（`tools/sync_docs.sh`：归档 + 提交 + 推送重试 + 一致性自检）：
   ```bash
   ~/unixnu-pagani/tools/sync_docs.sh "交接前同步：<本轮一句话结论>"
   ```
   它只 `git add docs/`，不碰 `xnu/patches/`，所以不会触发内核构建。若脚本不可用，退回手工：
   ```bash
   cp ~/unixnu-pagani/docs/XNU_HANDOFF_PROMPT.md \
      ~/unixnu-pagani/docs/ONEPLUS_13S_XNU_PORTING_DEBUG_LOG.md \
      ~/Documents/OnePlus13s-XNU移植/
   ```
3. 把 `~/Documents/OnePlus13s-XNU移植/粘贴给新Agent.txt` 里"当前节点"那段同步成本轮结论

然后把 §0 状态卡第一行改成新时间，并确认 `git log -1` 与状态卡一致。

### 9.7 禁止事项

- ❌ 只在聊天里说、不写进文档
- ❌ **攒够一轮再一次性回填**（用户 2026-11-06 明令禁止；按 §9.2 的表格逐步写）
- ❌ 把假设写成根因（这是黑名单里一半条目的来源）
- ❌ 删除或改写 DEBUG_LOG 旧正文（只能追加 + 插勘误块）
- ❌ 状态卡留旧提交号（新 agent 踩的第一个坑，也是最容易发现的坑）
- ❌ 写"待补充 / TODO"却不写"谁在什么条件下补"
- ❌ 把文档改动和补丁改动放进同一个提交——文档必须提交在 `docs/` 下，不混入 `xnu/patches/`，否则会触发一轮不必要的构建
