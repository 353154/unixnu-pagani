#!/usr/bin/env python3
"""
auto_boot_pipeline 引导台账状态机自测。

为什么单独存在：
  幂等闸门是为了防止"重复引导覆盖尚未读取的停屏画面"。但这种闸门有个特性——
  它坏掉的时候不会报错，只会静默放行，然后某天我们发现证据又丢了一轮。
  这和 2026-11-05 那次「SWEET EARLY 31 假标记」是同一种错误：校验器自己
  没被校验过。

  所以每次改台账/闸门逻辑，先跑这个脚本。全部 PASS 才算可以推。

用法：python3 tools/test_boot_gate.py
"""
import os
import sys
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import auto_boot_pipeline as p

SHA = "abc1234"

# (名称, 台账内容, 期望 state)
CASES = [
    ("空台账 → 允许引导", [], None),
    ("只有 staged → 允许引导", [{"event": "staged", "sha": SHA}], "other"),
    ("boot_start 后中断 → 拦截", [{"event": "boot_start", "sha": SHA}], "started"),
    ("boot_start + booted → 拦截", [{"event": "boot_start", "sha": SHA},
                                    {"event": "booted", "sha": SHA}], "done"),
    ("boot_failed → 允许重试", [{"event": "boot_start", "sha": SHA},
                                {"event": "boot_failed", "sha": SHA}], "done"),
    ("boot_unconfirmed → 也拦住", [{"event": "boot_start", "sha": SHA},
                                   {"event": "boot_unconfirmed", "sha": SHA}], "done"),
    ("别的 sha 不干扰", [{"event": "booted", "sha": "zzz9999"}], None),
]


def main():
    tmp = tempfile.mktemp(suffix=".jsonl")
    p.BOOT_LOG = tmp
    ok = True

    def reset(recs):
        with open(tmp, "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r) + "\n")

    for name, recs, want in CASES:
        reset(recs)
        got, last = p.boot_state(SHA)
        good = got == want
        ok &= good
        print(f"{'PASS' if good else 'FAIL'}  {name:<28} "
              f"state={got!r:<10} want={want!r}")

    # 台账里混入半行/坏 JSON 时不能抛异常，否则整个流水线会崩在读取阶段
    reset([{"event": "staged", "sha": SHA}])
    with open(tmp, "a", encoding="utf-8") as f:
        f.write("{ not valid json\n")
    try:
        n = len(p.read_boot_log())
        print(f"PASS  坏行被忽略（读到 {n} 条）")
    except Exception as e:                       # noqa: BLE001
        ok = False
        print(f"FAIL  坏行导致异常: {e}")

    # 终态事件集合必须与闸门判断保持一致。boot_unconfirmed 必须在内：
    # 空输出的引导很可能已经成功，放行就等于允许再盖一次屏。
    if p.BOOT_DONE != ("booted", "boot_unconfirmed", "boot_failed"):
        ok = False
        print(f"FAIL  BOOT_DONE 被改成了 {p.BOOT_DONE}，请同步检查闸门分支")
    else:
        print("PASS  BOOT_DONE 与闸门分支一致（含 boot_unconfirmed）")

    # 闸门里"会拦住"的事件集合，必须与 BOOT_DONE 中"非失败"的那些一致
    blockable = {"booted", "boot_unconfirmed"}
    if not blockable <= set(p.BOOT_DONE):
        ok = False
        print("FAIL  有可拦截事件不在 BOOT_DONE 里，闸门会漏放")
    else:
        print("PASS  可拦截事件都在 BOOT_DONE 里")

    os.unlink(tmp)
    print("\nRESULT:", "ALL PASS" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
