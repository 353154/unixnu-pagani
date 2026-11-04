# 一加 13s / 13T (pagani / SM8750) 硬件底包解析报告

数据来源：`/Volumes/T7/一加13t/Super Flasher 13T IN 17.0.0.101/OOS_FILES_HERE`

## 1. 引导与内核参数 (vendor_boot v4)
- **Magic**: `VNDRBOOT` (Header Version: 4, Page size: 4096)
- **内核启动参数 (Cmdline)**:
  ```text
  video=vfb:640x400,bpp=32,memsize=3072000 log_buf_len=2M nosoftlockup console=ttynull qcom_geni_serial.con_enabled=0 nohugevmalloc bootconfig buildvariant=user
  ```
- **Ramdisk 大小**: 19,526,116 字节 (~18.6 MB)
- **DTB 镜像大小**: 6,821,771 字节 (~6.5 MB)

## 2. 设备树 (DTB & DTBO) 提取结果
已从 `vendor_boot.img` 和 `dtbo.img` 中解出全套硬件描述：
- **SoC 芯片平台**：Qualcomm `sun` (SM8750 / Snapdragon 8 Elite / Oryon 架构)
- **主板型号识别**：`Qualcomm Technologies, Inc. Sun MTP,pagani`
- **设备树总览**：
  - `dtb_04.dtb`: Qualcomm Technologies, Inc. Sun v2 SoC
  - `dtb_05.dtb`: Qualcomm Technologies, Inc. Sun SoC
  - `dtbos/dtbo_*.dtbo`: 包含 OPPO/OnePlus 专有 PMIC (`oplus,pmicwd_qpnp-power-on`, `oplus-ocp-dev@8200`)、屏幕面板驱动及触控引脚定义。

## 3. 内存与启动分级
- `xbl_config.img`: 包含 DDR 早期初始化时序参数 (`pakala-1`, `pakala-R2-2`) 及内存保留区映射。
