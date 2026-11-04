#!/usr/bin/env python3
"""
build_pagani_payload.py - Package XNU kernel and ADT into BootShim Android Header v4 image
Target: OnePlus 13s / 13T (SM8750 / Oryon, pagani)
"""

import argparse
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(REPO_ROOT, 'tools')
SCRIPTS_DIR = os.path.join(REPO_ROOT, 'scripts')

def run(cmd):
    print(f"[CMD] {cmd}")
    ret = subprocess.call(cmd, shell=True)
    if ret != 0:
        sys.exit(f"Command failed with exit code {ret}")

def main():
    parser = argparse.ArgumentParser(description="Package XNU for OnePlus 13s Pagani")
    parser.add_argument("--kernel", required=True, help="Path to compiled XNU kernel (kernel.development)")
    parser.add_argument("--shim", default="", help="Path to BootShim Image binary")
    parser.add_argument("--ramdisk", default="", help="Optional ramdisk image path")
    parser.add_argument("--boot-args", default="-v sweetfb_native=1 serial=3", help="XNU boot-args")
    parser.add_argument("--out-dir", default=os.path.join(REPO_ROOT, "out"), help="Output directory")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    adt_path = os.path.join(args.out_dir, "pagani.adt")
    payload_path = os.path.join(args.out_dir, "payload.bin")
    boot_img_path = os.path.join(args.out_dir, "test-boot.img")

    print(">>> 1. Generating OnePlus 13s (pagani) Apple Device Tree (ADT)...")
    mkadt_py = os.path.join(TOOLS_DIR, "mkadt.py")
    run(f'python3 "{mkadt_py}" "{adt_path}"')

    print(">>> 2. Resolving chained fixups and packing XNU payload...")
    mkpayload_py = os.path.join(TOOLS_DIR, "mkpayload.py")
    cmdline_arg = f'--cmdline "{args.boot_args}"'
    ramdisk_arg = f'--ramdisk "{args.ramdisk}"' if args.ramdisk else ""
    run(f'python3 "{mkpayload_py}" "{args.kernel}" "{adt_path}" "{payload_path}" {cmdline_arg} {ramdisk_arg}')

    if args.shim and os.path.exists(args.shim):
        print(">>> 3. Packaging into Android Header v4 boot.img...")
        mkbootimg_py = os.path.join(SCRIPTS_DIR, "mkbootimg_v4.py")
        run(f'python3 "{mkbootimg_py}" --format boot --kernel "{args.shim}" --ramdisk "{payload_path}" --output "{boot_img_path}"')
        print(f"\n[SUCCESS] Image generated at: {boot_img_path}")
        print("To test boot on device via fastboot:")
        print(f"  fastboot boot {boot_img_path}")
    else:
        print(f"\n[INFO] Payload built at: {payload_path}")
        print("Provide --shim <path_to_shim_Image> to produce final test-boot.img")

if __name__ == "__main__":
    main()
