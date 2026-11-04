#!/usr/bin/env python3
"""
prepare_rootfs.py - Helper script to fetch and prepare iOS 16.7.16 RootFS for XNU bringup
Target device baseline: iPhone X (iPhone10,3 - iOS 16.7.16, Build 20H392)
"""

import os
import sys
import zipfile
import argparse
import plistlib

IPSW_URL = "https://updates.cdn-apple.com/2024FallFCS/fullrestores/062-81788/F94520A8-E04E-464A-A9EC-2F38C3B4E3FA/iPhone10,3,iPhone10,6_16.7.16_20H392_Restore.ipsw"

def parse_manifest(ipsw_path: str):
    with zipfile.ZipFile(ipsw_path, 'r') as z:
        with z.open('BuildManifest.plist') as f:
            manifest = plistlib.load(f)
    
    build_identities = manifest.get('BuildIdentities', [])
    if not build_identities:
        print('No build identities found')
        return None
        
    os_comp = build_identities[0]['Manifest'].get('OS', {})
    rootfs_dmg = os_comp.get('Info', {}).get('Path')
    print(f'RootFS DMG: {rootfs_dmg}')
    return rootfs_dmg

def main():
    parser = argparse.ArgumentParser(description='Prepare iOS 16 userland rootfs for SM8750 XNU bringup')
    parser.add_argument('--ipsw', help='Local path to iPhone10,3_16.7.16_20H392_Restore.ipsw')
    parser.add_argument('--extract-dmg', action='store_true', help='Extract rootfs DMG from IPSW')
    parser.add_argument('--out-dir', default='userland', help='Output directory')
    args = parser.parse_args()

    if not args.ipsw:
        print(f'=== iOS 16.7.16 IPSW Official Download URL ===')
        print(IPSW_URL)
        print('\nDownload the IPSW and run:')
        print(f'python3 scripts/prepare_rootfs.py --ipsw <path_to_ipsw> --extract-dmg')
        return

    os.makedirs(args.out_dir, exist_ok=True)
    dmg_name = parse_manifest(args.ipsw)
    if dmg_name and args.extract_dmg:
        print(f'Extracting {dmg_name} to {args.out_dir}...')
        with zipfile.ZipFile(args.ipsw, 'r') as z:
            z.extract(dmg_name, args.out_dir)
        print(f'Extracted {dmg_name} successfully.')

if __name__ == '__main__':
    main()
