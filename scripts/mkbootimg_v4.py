#!/usr/bin/env python3
"""
mkbootimg_v4.py - Package custom kernel/BootShim into Android Boot Header v4
Target platform: Qualcomm Snapdragon 8 Elite (SM8750 / sun / pagani)
"""

import argparse
import os
import struct
import sys

PAGE_SIZE = 4096
BOOT_MAGIC = b'ANDROID!'
VENDOR_BOOT_MAGIC = b'VNDRBOOT'

def pad_to_page(data: bytes, page_size: int = PAGE_SIZE) -> bytes:
    pad = (page_size - (len(data) % page_size)) % page_size
    return data + (b'\x00' * pad)

def create_boot_v4(kernel_path: str, ramdisk_path: str, output_path: str, cmdline: str = '', os_version: int = 0):
    """
    Create a standard Android boot.img Header v4 image
    Layout:
      Page 0: boot_img_hdr_v4 (4096 bytes)
      Page 1..: kernel
      Page ..: ramdisk
    """
    with open(kernel_path, 'rb') as f:
        kernel_data = f.read()

    ramdisk_data = b''
    if ramdisk_path and os.path.exists(ramdisk_path):
        with open(ramdisk_path, 'rb') as f:
            ramdisk_data = f.read()

    kernel_size = len(kernel_data)
    ramdisk_size = len(ramdisk_data)
    header_size = 4096

    # Format:
    # 8s: magic ("ANDROID!")
    # I: kernel_size
    # I: ramdisk_size
    # I: os_version
    # I: header_size (4096)
    # 4I: reserved[4]
    # I: header_version (4)
    # 2048s: cmdline
    header_fmt = '<8sIIII4II2048s'
    cmdline_bytes = cmdline.encode('utf-8')[:2048].ljust(2048, b'\x00')

    hdr = struct.pack(
        header_fmt,
        BOOT_MAGIC,
        kernel_size,
        ramdisk_size,
        os_version,
        header_size,
        0, 0, 0, 0,       # reserved[4]
        4,                # header_version = 4
        cmdline_bytes
    )
    hdr = hdr.ljust(header_size, b'\x00')

    with open(output_path, 'wb') as out:
        out.write(pad_to_page(hdr))
        out.write(pad_to_page(kernel_data))
        if ramdisk_data:
            out.write(pad_to_page(ramdisk_data))

    print(f'Successfully built boot.img v4 image at {output_path} ({os.path.getsize(output_path)} bytes)')


def create_vendor_boot_v4(dtb_path: str, ramdisk_path: str, output_path: str, cmdline: str = ''):
    """
    Create an Android vendor_boot v4 image
    """
    with open(dtb_path, 'rb') as f:
        dtb_data = f.read()
    
    ramdisk_data = b''
    if ramdisk_path and os.path.exists(ramdisk_path):
        with open(ramdisk_path, 'rb') as f:
            ramdisk_data = f.read()
            
    dtb_size = len(dtb_data)
    ramdisk_size = len(ramdisk_data)
    
    # vendor_boot header v4 structure:
    # magic: 8 bytes ('VNDRBOOT')
    # header_version: uint32 (4)
    # page_size: uint32 (4096)
    # kernel_addr: uint32
    # ramdisk_addr: uint32
    # ramdisk_size: uint32
    # cmdline: 2048 bytes
    # tags_addr: uint32
    # name: 16 bytes
    # header_size: uint32 (2128 bytes)
    # dtb_size: uint32
    # dtb_addr: uint64
    # vendor_ramdisk_table_size: uint32
    # vendor_ramdisk_table_entry_num: uint32
    # vendor_ramdisk_table_entry_size: uint32
    # bootconfig_size: uint32
    
    header_size = 2128
    header_fmt = '<8sIIII2048sI16sIIQIIII'
    cmdline_bytes = cmdline.encode('utf-8')[:2048].ljust(2048, b'\x00')
    name_bytes = b'unixnu-pagani'.ljust(16, b'\x00')
    
    hdr = struct.pack(
        header_fmt,
        VENDOR_BOOT_MAGIC,
        4,                  # version 4
        PAGE_SIZE,          # 4096
        0x80000000,         # kernel_addr (placeholder)
        0x84000000,         # ramdisk_addr (placeholder)
        ramdisk_size,
        cmdline_bytes,
        0x80000100,         # tags_addr
        name_bytes,
        header_size,
        dtb_size,
        0x82000000,         # dtb_addr
        0,                  # vendor_ramdisk_table_size
        0,                  # vendor_ramdisk_table_entry_num
        108,                # vendor_ramdisk_table_entry_size
        0                   # bootconfig_size
    )
    
    hdr = hdr.ljust(header_size, b'\x00')
    
    with open(output_path, 'wb') as out:
        out.write(pad_to_page(hdr))
        if ramdisk_data:
            out.write(pad_to_page(ramdisk_data))
        out.write(pad_to_page(dtb_data))
        
    print(f'Successfully built vendor_boot v4 image at {output_path} ({os.path.getsize(output_path)} bytes)')

def main():
    parser = argparse.ArgumentParser(description='Build Android Boot Header v4 for SM8750')
    parser.add_argument('--kernel', default='', help='Path to kernel / BootShim Image (for boot.img)')
    parser.add_argument('--dtb', default='', help='Path to DTB/FDT blob (for vendor_boot)')
    parser.add_argument('--ramdisk', default='', help='Path to ramdisk/initrd blob')
    parser.add_argument('--cmdline', default='console=ttynull bootconfig', help='Kernel command line')
    parser.add_argument('--format', choices=['boot', 'vendor_boot'], default='boot', help='Image format to generate')
    parser.add_argument('--output', required=True, help='Output image path')
    args = parser.parse_args()

    if args.format == 'boot':
        if not args.kernel:
            sys.exit("Error: --kernel required for boot format")
        create_boot_v4(args.kernel, args.ramdisk, args.output, args.cmdline)
    else:
        if not args.dtb:
            sys.exit("Error: --dtb required for vendor_boot format")
        create_vendor_boot_v4(args.dtb, args.ramdisk, args.output, args.cmdline)

if __name__ == '__main__':
    main()
