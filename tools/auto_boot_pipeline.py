#!/usr/bin/env python3
"""
OnePlus 13s (pagani) XNU 移植 —— 全自动引导流水线

用途：一条命令完成「等 CI → 抓失败日志 → 下载产物 → 校验补丁是否真进内核
→ 合成 boot.img → 进 bootloader → fastboot boot」。

为什么需要它：
  0012 补丁曾因 `corrupt patch` 被 CI 跳过数轮而无人察觉（构建仍 success）。
  因此本脚本在拿到 kernel 后会**搜索标记字符串**（SWD00 / SWE00 / SWC01 等），
  任何标记缺失即视为「补丁没进去」并直接报错，不再让假象进入真机实验。

安全约束：只执行 `fastboot boot`，绝不 flash / erase。
用法：python3 tools/auto_boot_pipeline.py [--sha <commit>]
"""
import urllib.request, json, time, subprocess, zipfile, io, sys, os

REPO = "353154/unixnu-pagani"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERIAL = os.environ.get("PAGANI_SERIAL", "3B1F67EA9BBUHK76")

# 必须存在于产物内核中的标记串（缺失 => 对应补丁没生效）
REQUIRED_MARKS = [b"SWD00", b"SWE00", b"SWC01",
                  b"kernel framebuffer VA live", b"early I/O page tables ready",
                  # 0087 kmem 空间探针：比上面几条更关键——它决定本轮能否读出 kernel_map 边界
                  b"SWK0", b"SWK1", b"SWK2", b"SWK3",
                  # 0012：补丁被静默跳过数轮才导致的长期误判，必须每次校验
                  b"SWEET EARLY 31"]


def token():
    try:
        return subprocess.check_output(
            "security find-internet-password -s github.com -w 2>/dev/null",
            shell=True).decode().strip()
    except Exception:
        return ""


TOK = token()
H = {"User-Agent": "Python"}
if TOK:
    H["Authorization"] = f"token {TOK}"


def _raw(u, headers=None, tries=5):
    """带指数退避的 GET。GitHub 的 TLS 偶发被中断（SSL: UNEXPECTED_EOF），必须重试。"""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(u, headers=headers or H)
            return urllib.request.urlopen(req, timeout=60).read()
        except Exception as e:                      # URLError / SSLEOFError / 超时
            last = e
            wait = 2 ** i
            print(f"  retry {i + 1}/{tries} after {wait}s: {type(e).__name__}", flush=True)
            time.sleep(wait)
    raise last


def get(u):
    return json.loads(_raw(u).decode())


def sh(c):
    return subprocess.run(c, shell=True, capture_output=True, text=True).stdout.strip()


def main():
    sha = sys.argv[sys.argv.index("--sha") + 1] if "--sha" in sys.argv else \
        sh(f"git -C {ROOT} rev-parse HEAD")
    print("HEAD", sha[:7], flush=True)

    # 本轮新增的探针不必改代码：--require "SWK0,SWK1"
    if "--require" in sys.argv:
        for m in sys.argv[sys.argv.index("--require") + 1].split(","):
            if m.strip():
                REQUIRED_MARKS.append(m.strip().encode())
        print("EXTRA MARKS", [m.decode() for m in REQUIRED_MARKS[-3:]], flush=True)

    run = None
    for _ in range(30):
        # 允许传短 sha：用 startswith 前缀匹配，且放宽到 30 条（shim/xnu 两条工作流都会产生 run）
        for r in get(f"https://api.github.com/repos/{REPO}/actions/runs?per_page=30")["workflow_runs"]:
            if r["head_sha"].startswith(sha):
                run = r
                break
        if run:
            break
        time.sleep(5)
    if not run:
        print("NO RUN for", sha[:7], flush=True)
        return 1

    rid = run["id"]
    print("RUN", rid, run["status"], flush=True)

    r = run
    for _ in range(90):
        r = get(f"https://api.github.com/repos/{REPO}/actions/runs/{rid}")
        if r["status"] == "completed":
            break
        print(f"[{time.strftime('%H:%M:%S')}] {r['status']}", flush=True)
        time.sleep(20)
    print("CONCL", r["conclusion"], flush=True)

    if r["conclusion"] != "success":
        jobs = get(f"https://api.github.com/repos/{REPO}/actions/runs/{rid}/jobs")["jobs"]
        try:
            jid = jobs[0]["id"]
            log = urllib.request.urlopen(urllib.request.Request(
                f"https://api.github.com/repos/{REPO}/actions/jobs/{jid}/logs",
                headers=H)).read().decode("utf-8", "replace")
            bad = [l.split("Z ", 1)[-1] for l in log.splitlines()
                   if ": error:" in l or "FAILED" in l or "Skipping patch" in l]
            for l in bad[:25]:
                print("ERR:", l[:220], flush=True)
        except Exception as e:
            print("log fetch failed", e, flush=True)
        return 1

    art = get(f"https://api.github.com/repos/{REPO}/actions/runs/{rid}/artifacts")["artifacts"][0]
    print("ART", art["name"], art["size_in_bytes"], flush=True)

    class Redirect(urllib.request.HTTPRedirectHandler):
        # 302 会跳到 objects.githubusercontent.com 的预签名地址，不能带 token
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return urllib.request.Request(newurl, headers={"User-Agent": "Python"})

    opener = urllib.request.build_opener(Redirect)
    url = f"https://api.github.com/repos/{REPO}/actions/artifacts/{art['id']}/zip"

    data = None
    for i in range(5):
        try:
            data = opener.open(urllib.request.Request(url, headers=H), timeout=300).read()
            break
        except Exception as e:
            print(f"  zip retry {i + 1}/5: {type(e).__name__}", flush=True)
            time.sleep(2 ** i)
    if data is None:
        print("ZIP DOWNLOAD FAILED", flush=True)
        return 1

    zipfile.ZipFile(io.BytesIO(data)).extractall(os.path.join(ROOT, "out"))
    print("EXTRACT", len(data), flush=True)

    kern = os.path.join(ROOT, "out/kernel.development.sweet")
    blob = open(kern, "rb").read()
    print("KERNEL", len(blob), flush=True)

    missing = []
    for m in REQUIRED_MARKS:
        off = blob.find(m)
        print("MARK", m.decode(), off, flush=True)
        if off < 0:
            missing.append(m.decode())
    if missing:
        print("!! 缺失标记，说明相关补丁未生效:", ", ".join(missing), flush=True)
        return 2

    subprocess.run(["python3", os.path.join(ROOT, "scripts/build_pagani_payload.py"),
                    "--kernel", kern,
                    "--shim", os.path.join(ROOT, "shim/out/Image"),
                    "--out-dir", os.path.join(ROOT, "out")],
                   check=True, stdout=subprocess.DEVNULL)
    print("IMAGE READY", flush=True)

    if sh(f"adb -s {SERIAL} get-state 2>/dev/null") == "device":
        sh(f"adb -s {SERIAL} reboot bootloader")
        print("reboot bootloader issued", flush=True)

    for _ in range(200):
        dev = sh("fastboot devices")
        if dev:
            print("FASTBOOT", dev, flush=True)
            print(sh(f"fastboot boot {os.path.join(ROOT, 'out/test-boot.img')}"), flush=True)
            print("BOOTED", time.strftime("%H:%M:%S"), flush=True)
            return 0
        time.sleep(3)
    print("fastboot device never appeared", flush=True)
    return 3


if __name__ == "__main__":
    sys.exit(main())
