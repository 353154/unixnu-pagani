#!/usr/bin/env python3
"""
patch_rootfs_bypass.py - Inject offline setup bypass into extracted iOS RootFS
Allows booting directly to SpringBoard without Apple SEP activation & Setup assistant.
"""

import os
import plistlib
import sys

def patch_preferences(rootfs_path: str):
    pref_dir = os.path.join(rootfs_path, 'private/var/mobile/Library/Preferences')
    os.makedirs(pref_dir, exist_ok=True)
    
    # 1. Bypass com.apple.purplebuddy (Setup Assistant)
    purplebuddy_path = os.path.join(pref_dir, 'com.apple.purplebuddy.plist')
    purplebuddy_data = {
        'SetupDone': True,
        'SetupFinishedAllSteps': True,
        'SetupState': 'Complete'
    }
    with open(purplebuddy_path, 'wb') as f:
        plistlib.dump(purplebuddy_data, f)
    print(f'Injected: {purplebuddy_path}')

    # 2. Bypass SpringBoard first-launch setup
    sb_path = os.path.join(pref_dir, 'com.apple.springboard.plist')
    sb_data = {
        'SBShowNonDefaultSystemApps': True,
        'SBLastKnownInterfaceOrientation': 1
    }
    with open(sb_path, 'wb') as f:
        plistlib.dump(sb_data, f)
    print(f'Injected: {sb_path}')

def patch_launchd(rootfs_path: str):
    """Disable services that crash without SEP or cellular baseband"""
    daemons_dir = os.path.join(rootfs_path, 'System/Library/LaunchDaemons')
    disabled_daemons = [
        'com.apple.sepd.plist',
        'com.apple.CommCenter.plist',
        'com.apple.mobileactivationd.plist',
    ]
    for d in disabled_daemons:
        target = os.path.join(daemons_dir, d)
        if os.path.exists(target):
            os.rename(target, target + '.bak')
            print(f'Disabled daemon: {d}')

def main():
    if len(sys.argv) < 2:
        print('Usage: python3 patch_rootfs_bypass.py <path_to_mounted_or_extracted_rootfs>')
        return
    rootfs = sys.argv[1]
    patch_preferences(rootfs)
    patch_launchd(rootfs)
    print('Offline bypass injection complete.')

if __name__ == '__main__':
    main()
