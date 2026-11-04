# OnePlus 13s (pagani / SM8750) 核心硬件规格与拓扑汇总

该文档由从官方固件 `vendor_boot.img`、`dtbo.img` 以及实机基线解析生成，供 UEFI BootShim 及 XNU 内核驱动移植使用。

---

## 1. 核心处理器 (CPU) 与电源接口 (PSCI)
- **架构**: ARMv8.7-A / ARMv9 兼容，8x Qualcomm Oryon 核心
- **CPU MIDR**: Implementer `0x51` (Qualcomm), Part `0x001` (Oryon)
- **多核唤醒机制 (PSCI)**: `arm,psci-1.0` (标准 SMC/HVC 接口，遵循标准 ARM PSCI 规范唤醒从核)

## 2. 中断控制器 (Interrupt Controller - GIC)
- **架构**: ARM GICv3 / GICv4.1
- **物理寄存器映射**:
  - **GICD (Distributor)**: `0x16000000` (大小: `0x10000` / 64 KB)
  - **GICR (Redistributor)**: `0x16080000` (大小: `0x200000` / 2 MB)
- **XNU 适配关键点**: 苹果 XNU 原生适配的是 Apple AIC (Apple Interrupt Controller)。移植到高通需要替换为 ARM GICv3 驱动（已在 `UniXNU-houji` 和 `ios-sweet` 中具备通用参考驱动）。

## 3. 安全内存与保留区 (Reserved Memory / Exclusion Map)
在 XNU 内核初始化物理页帧分配器（`pmap`）时，**绝对不能**将以下高通固件专用的物理地址段映射为可用内存，否则将立即导致 Hypervisor (Gunyah) 或 TrustZone (QTEE) 拦截并强制宕机：
- `0x80000000 - 0x81200000` (18 MB): `gunyah_hyp_region` (高通虚拟机监视器固件)
- `0x81c00000 - 0x81d00000`: `aop_image_region` / `aop_cmd_db` (Always-On Processor 电源管理)
- `0x81d00000 - 0x81f00000` (2 MB): `smem_region` (高通子系统共享内存)
- `0x8ba00000 - 0x9b000000` (246 MB): `mpss_region` (基带调制解调器固件保留区)
- `0xd8000000 - 0xd8600000` (6 MB): `tz_merged_region` (TrustZone 安全区)
- `0xf3800000 - 0xf7c00000` (68 MB): `trust_ui_vm_region` (安全 UI 显示缓冲区)

## 4. 显示与图形输出 (Display & Framebuffer)
- **物理分辨率**: `1216 x 2640` @ 560 DPI
- **原生屏幕面板**: `mdss_dsi_panel_AA594_P_7_A0020_dsc_cmd` (支持 DSC 压缩显示的 DSI 模组)
- **DPU 硬件基址**: `0x0af54000`
- **XNU 适配策略**: 采用 **UEFI GOP 传递内存帧缓冲区** 方式，由 EDK2/UEFI 初始化屏幕，并将 Framebuffer 物理地址和步长传给 XNU 的 `MiniIOMobileFramebuffer`，实现 iOS UI 画面软解输出。

## 5. 触摸屏控制器 (Touch Controller)
- **触控 IC**: `Synaptics S3910` (`synaptics_tcm@0`，运行于 SPI 模式) / 备选兼容 `Goodix Berlin`
- **接口**: SPI Bus + 专用中断 GPIO (`synaptics,irq-gpio`)
- **XNU 适配策略**: 参考 `SweetHID` 框架，在 XNU 内注册 `IOHIDDevice` 驱动，解析触控协议上报的 X/Y 原始坐标。
