#!/usr/bin/env python3
"""
刷新交接文档状态卡里的「台账快照」行。

为什么需要：
  状态卡的「最新内核提交 / 最新构建」两行是手写的。写的时候构建往往还没
  结束，写完那一刻就已经脱节——这在本项目里至少发生过三次，每次代价都是
  "下一个读文档的人（包括三天后的自己）按错误前提开工"。

  但这两行同时含有人工判断（"0093 打开 DEBUG_BSDINIT"），没法整行自动生成。
  所以拆开：人工描述保持不动，另加一行只含**客观事实**的快照，由脚本刷新。
  自动生成的永远只写可机读的东西：sha、Run 号、结论、时刻。

用法：
  python3 tools/refresh_status.py          # 就地改写 docs/XNU_HANDOFF_PROMPT.md
  python3 tools/refresh_status.py --print  # 只打印，不改文件
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOC = os.path.join(ROOT, "docs/XNU_HANDOFF_PROMPT.md")
BOOT_LOG = os.path.join(ROOT, "out/boot_history.jsonl")
REPO = "353154/unixnu-pagani"
MARK = "| 台账快照 |"


def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True,
                              text=True, cwd=ROOT).stdout.strip()
    except Exception:
        return ""


def head_sha():
    return sh("git rev-parse --short=7 HEAD") or "unknown"


def latest_run():
    """返回 (run_number, sha7, conclusion) 或 None。网络/鉴权失败一律返回 None，
    绝不让文档刷新因为 CI 查不到而失败——那会把"同步文档"变成一件有风险的事。"""
    try:
        tok = sh("security find-internet-password -s github.com -w 2>/dev/null")
        hdr = {"User-Agent": "Python"}
        if tok:
            hdr["Authorization"] = f"token {tok}"
        url = f"https://api.github.com/repos/{REPO}/actions/runs?per_page=1"
        req = urllib.request.Request(url, headers=hdr)
        d = json.loads(urllib.request.urlopen(req, timeout=15).read())
        r = d["workflow_runs"][0]
        return r["run_number"], r["head_sha"][:7], r["conclusion"] or r["status"]
    except Exception:
        return None


def last_boot():
    """台账里最后一条引导记录（只认 booted / boot_failed，staged 不算）。"""
    if not os.path.exists(BOOT_LOG):
        return None
    last = None
    for ln in open(BOOT_LOG, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            r = json.loads(ln)
        except Exception:
            continue
        if r.get("event") in ("booted", "boot_failed"):
            last = r
    return last


def build_line():
    parts = [f"自动生成 {time.strftime('%m-%d %H:%M')}", f"HEAD `{head_sha()}`"]

    run = latest_run()
    if run:
        num, sha, concl = run
        parts.append(f"最新 CI Run {num} `{sha}` {concl}")
    else:
        parts.append("最新 CI 查询失败")

    b = last_boot()
    if b:
        parts.append(f"最近引导 `{b['sha']}` {b['at'][-8:]} {b['event']}")
    else:
        parts.append("台账无引导记录")

    return MARK + " " + " · ".join(parts) + " |"


def main():
    dry = "--print" in sys.argv
    if not os.path.exists(DOC):
        print("FATAL: 找不到", DOC)
        return 1

    src = open(DOC, encoding="utf-8").read()
    line = build_line()

    if MARK in src:
        # 就地替换已有快照行。用 lambda 而非字符串做替换，避免内容里的
        # 反斜杠被 re 当成转义序列。
        new = re.sub(r"^\| 台账快照 \|.*$", lambda _m: line, src,
                     count=1, flags=re.M)
    else:
        # 插在状态卡表格的最后一行（「下一步动作」）之后
        anchor = re.search(r"^\| 下一步动作 \|.*$", src, flags=re.M)
        if not anchor:
            print("WARN: 找不到状态卡锚点，改为不插入")
            return 0
        new = src[:anchor.end()] + "\n" + line + src[anchor.end():]

    if dry:
        print(line)
        return 0

    if new == src:
        print("NO-CHANGE:", line)
        return 0

    open(DOC, "w", encoding="utf-8").write(new)
    print("UPDATED:", line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
