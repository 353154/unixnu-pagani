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

用法：
  python3 tools/auto_boot_pipeline.py [--sha <commit>] [--require "SWK0,SWP1"]
                                      [--no-boot] [--force]

  --no-boot  只备镜像、不碰设备（上一轮屏幕还没拍时用）
  --force    跳过幂等闸门，允许对已引导过的提交再引导一次

幂等：每次引导都会写一行台账到 out/boot_history.jsonl。同一 sha 已 boot 过
就直接退出，避免"看到 CI success 就再跑一遍"覆盖掉尚未读取的停屏画面。
设备在 adb/fastboot 两侧都不可见时立即退出（最常见原因是 XNU 正在跑，USB
不枚举），不再空等 12 分钟。
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
                  # 0088 claim 明细
                  b"SWQ%u", b"SWG free=",
                  # 0090 console 接管旁路 + 活体探针
                  b"SWV1", b"SWV2", b"SWV3"]


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


# ── 引导台账 ────────────────────────────────────────────────────────────────
# 2026-11-06 00:29 教训：同一提交 231550f 被引导了两次。原因是脚本既不记录
# "这个 sha 已经 boot 过"，也没有任何可查痕迹，于是"看到 CI success 就再跑一次"
# 成了默认动作。第二次引导会把第一次停屏的画面覆盖掉——证据白丢一轮。
# 从这版起：每次引导写一行 JSONL；同一 sha 已引导过就直接退出，除非 --force。
BOOT_LOG = os.path.join(ROOT, "out/boot_history.jsonl")


def read_boot_log():
    recs = []
    if not os.path.exists(BOOT_LOG):
        return recs
    for ln in open(BOOT_LOG, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            recs.append(json.loads(ln))
        except Exception:
            pass
    return recs


def log_boot(event, sha, **extra):
    rec = {"event": event, "sha": sha[:7],
           "at": time.strftime("%Y-%m-%d %H:%M:%S"), **extra}
    os.makedirs(os.path.dirname(BOOT_LOG), exist_ok=True)
    with open(BOOT_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("LEDGER", json.dumps(rec, ensure_ascii=False), flush=True)
    return rec


def device_visible():
    """adb 或 fastboot 任一侧能看到本机即为可见。"""
    st = sh(f"adb -s {SERIAL} get-state 2>/dev/null")
    if st in ("device", "recovery", "sideload"):
        return True
    return bool(sh("fastboot devices"))



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

    # 默认行为：产物校验通过后直接 reboot bootloader + fastboot boot。
    # 2026-11-06 用户明确授权「构建一结束就自动下载、合成并引导」，所以不再
    # 每次停下来等一句"开始"。
    #
    # 铁律 2 真正要守的是「不自动重启回 Android」——那会冲掉停屏画面。进
    # fastboot 做 RAM 引导不写任何分区，且此时上一轮的屏幕早已拍完，不构成
    # 证据丢失。
    #
    # 唯一例外：上一轮屏幕还没拍照时，加 --no-boot 只备镜像、不碰设备。
    if "--no-boot" in sys.argv:
        print("NO-BOOT mode: image staged, device untouched", flush=True)
        log_boot("staged", sha, mode="no-boot")
        return 0

    # ── 幂等闸门（2026-11-06 00:29 新增）────────────────────────────────
    # 同一提交已引导过就不再碰设备。这是为了防止"看到构建成功就再跑一遍"，
    # 把上一次还没读的停屏画面覆盖掉。
    done = [r for r in read_boot_log()
            if r.get("sha") == sha[:7] and r.get("event") == "booted"]
    if done and "--force" not in sys.argv:
        last = done[-1]
        print(f"ALREADY BOOTED {last['sha']} at {last['at']} —— 跳过", flush=True)
        print("同一提交已引导过，不重复引导。确认要重跑请加 --force。", flush=True)
        return 0

    # ── 设备可见性预检（2026-11-06 00:29 新增）──────────────────────────
    # 旧版在设备两边都不可见时会干等 20×3s + 240×3s ≈ 12 分钟才报错，期间
    # 完全没有输出。实测最常见的"不可见"是设备正在跑 XNU（USB 不枚举），
    # 这种情况重试引导毫无意义，应当立刻停下让用户拍照。
    seen = False
    for i in range(4):
        if device_visible():
            seen = True
            break
        if i == 0:
            sh("adb start-server")
        time.sleep(3)
    if not seen:
        print("DEVICE NOT VISIBLE —— adb 和 fastboot 都看不到设备", flush=True)
        print("最常见原因：设备正在跑 XNU 内核（USB 不枚举）。", flush=True)
        print("此刻不要重试引导，先拍照读屏，再重启回 Android。", flush=True)
        log_boot("skipped_invisible", sha, reason="adb+fastboot both empty")
        return 4


    # 只要 adb 侧能看到本机序列号就重启（get-state 在设备刚重枚举时会返回 offline/空，
    # 曾因此跳过 reboot 然后干等 fastboot 十分钟）
    def adb_ready():
        out = sh(f"adb -s {SERIAL} get-state 2>/dev/null")
        return out in ("device", "recovery", "sideload")

    sent = False
    for attempt in range(20):
        if adb_ready():
            sh(f"adb -s {SERIAL} reboot bootloader")
            print(f"reboot bootloader issued (attempt {attempt + 1})", flush=True)
            sent = True
            break
        if attempt == 0:
            sh("adb start-server")
        time.sleep(3)
    if not sent:
        print("adb not ready, assuming device may already be in fastboot", flush=True)

    for i in range(240):
        dev = sh("fastboot devices")
        if dev:
            print("FASTBOOT", dev, flush=True)
            out = sh(f"fastboot boot {os.path.join(ROOT, 'out/test-boot.img')}")
            print(out, flush=True)
            ok = "OKAY" in out or "Booting" in out
            print("BOOTED" if ok else "BOOT FAILED", time.strftime("%H:%M:%S"), flush=True)
            log_boot("booted" if ok else "boot_failed", sha,
                     serial=SERIAL,
                     image_mtime=time.strftime(
                         "%H:%M:%S", time.localtime(
                             os.path.getmtime(os.path.join(ROOT, "out/test-boot.img")))),
                     out=out.replace("\n", " | ")[:200])
            return 0 if ok else 5
        # 60 秒还没出现：可能 reboot 没生效，或手机停在 Android，重发一次
        if i and i % 20 == 0:
            if adb_ready():
                sh(f"adb -s {SERIAL} reboot bootloader")
                print(f"  re-issued reboot bootloader @ {i * 3}s", flush=True)
        time.sleep(3)
    print("fastboot device never appeared", flush=True)
    log_boot("boot_failed", sha, reason="fastboot never appeared")
    return 3


if __name__ == "__main__":
    sys.exit(main())
