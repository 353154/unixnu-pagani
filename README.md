# unixnu-pagani

Experimental bring-up of Apple XNU kernel and iOS 16 userland on OnePlus 13s (CPH2723 / pagani / SM8750 "sun").

## Target Hardware Specs (Dumped)
- **Model**: OnePlus 13s (`CPH2723` / `OP612BL1`)
- **Platform**: Qualcomm Snapdragon 8 Elite (`sun` / SM8750)
- **CPU**: 8x Qualcomm Oryon Cores (`implementer 0x51, part 0x001`)
- **Screen**: 1216x2640 @ 560 dpi
- **Kernel Baseline**: Linux 6.6.118-android15

## Project Stages
1. **Hardware Recon & Baseline Dumps**: FDT/DTB extraction, memory mapping (xbl_config), touch/display controller probing.
2. **UEFI BootShim**: EDK2-based boot payload conforming to Android Boot Header v4 for `fastboot boot`.
3. **XNU Kernel Bringup**: Porting Apple `xnu-8796` to Qualcomm Oryon + GICv4.1 + PSCI + MiniIOMobileFramebuffer.
4. **iOS Userland Extraction**: iPhone X iOS 16.7.16 (20H392) rootfs preparation with offline setup bypass.
