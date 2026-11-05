#!/usr/bin/env python3
import urllib.request
import json
import time
import sys
import subprocess
import os
import zipfile
import io

LOG_FILE = "/Users/damon/unixnu-pagani/build_status.log"

def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def get_token():
    try:
        return subprocess.check_output("security find-internet-password -s github.com -w 2>/dev/null", shell=True).decode().strip()
    except Exception:
        return ""

def push_wechat(msg):
    try:
        py_path = "/Users/damon/.hermes/installs/8c379330277d6bde/environments/a5231383ca1545bd8892d6f2844e56e5/venv/bin/python"
        script = "/Users/damon/unixnu-pagani/scripts/wxpush.py"
        if os.path.exists(py_path) and os.path.exists(script):
            subprocess.run([py_path, script, msg], timeout=10)
    except Exception as e:
        log(f"微信通知失败: {e}")

token = get_token()
headers = {"Authorization": f"token {token}", "User-Agent": "Python"} if token else {"User-Agent": "Python"}

if len(sys.argv) > 1:
    RUN_ID = sys.argv[1]
else:
    req = urllib.request.Request("https://api.github.com/repos/353154/unixnu-pagani/actions/runs?per_page=1", headers=headers)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
        RUN_ID = str(data["workflow_runs"][0]["id"])

log(f"\n=== 启动自动心跳监控: Run #{RUN_ID} ===")

while True:
    try:
        token = get_token()
        headers = {"Authorization": f"token {token}", "User-Agent": "Python"} if token else {"User-Agent": "Python"}
        req = urllib.request.Request(
            f"https://api.github.com/repos/353154/unixnu-pagani/actions/runs/{RUN_ID}/jobs",
            headers=headers
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            job = data["jobs"][0]
            status = job["status"]
            conclusion = job["conclusion"]
            
            steps_info = []
            for s in job["steps"]:
                if s["status"] == "in_progress":
                    steps_info.append(f"{s['name']} (进行中...)")
                elif s["conclusion"] == "failure":
                    steps_info.append(f"{s['name']} (失败!)")
            
            active = ", ".join(steps_info) if steps_info else status
            log(f"当前构建状态: {status} | 活跃步骤: {active}")
            
            if status == "completed":
                if conclusion == "success":
                    log("🎉 XNU 内核编译成功！正在自动下载内核产物...")
                    token = get_token()
                    art_req = urllib.request.Request(
                        f"https://api.github.com/repos/353154/unixnu-pagani/actions/runs/{RUN_ID}/artifacts",
                        headers={"Authorization": f"token {token}", "User-Agent": "Python"} if token else {"User-Agent": "Python"}
                    )
                    with urllib.request.urlopen(art_req) as art_resp:
                        art_data = json.loads(art_resp.read().decode())
                        artifacts = art_data.get("artifacts", [])
                        if artifacts:
                            download_url = artifacts[0]["archive_download_url"]
                            log(f"找到内核产物: {artifacts[0]['name']} ({artifacts[0]['size_in_bytes']} bytes)")
                            
                            dl_req = urllib.request.Request(
                                download_url,
                                headers={"Authorization": f"token {token}", "User-Agent": "Python"}
                            )
                            class SafeRedirect(urllib.request.HTTPRedirectHandler):
                                def http_error_302(self, req, fp, code, msg, headers):
                                    new_url = headers.get("Location")
                                    return urllib.request.urlopen(urllib.request.Request(new_url, headers={"User-Agent": "Python"}))
                            opener = urllib.request.build_opener(SafeRedirect)
                            with opener.open(dl_req) as dl_resp:
                                z = zipfile.ZipFile(io.BytesIO(dl_resp.read()))
                                os.makedirs("/Users/damon/unixnu-pagani/out", exist_ok=True)
                                z.extractall("/Users/damon/unixnu-pagani/out")
                                log(f"✅ 内核产物已成功解压到 /Users/damon/unixnu-pagani/out")
                                log(">>> 正在自动重新合体生成 32MB test-boot.img...")
                                subprocess.run([
                                    "python3", "/Users/damon/unixnu-pagani/scripts/build_pagani_payload.py",
                                    "--kernel", "/Users/damon/unixnu-pagani/out/kernel.development.sweet",
                                    "--shim", "/Users/damon/unixnu-pagani/shim/out/Image",
                                    "--out-dir", "/Users/damon/unixnu-pagani/out"
                                ], check=True)
                                log("✅ test-boot.img 重新合成成功！")
                                push_wechat("✅ OnePlus 13s XNU v14 镜像已自动下载并打包完毕 (out/test-boot.img)，准备自动引导！")
                                log(">>> 正在自动重启手机至 Bootloader 准备引导...")
                                subprocess.run(["adb", "reboot", "bootloader"], check=False)
                                for _ in range(40):
                                    time.sleep(1)
                                    res = subprocess.run(["fastboot", "devices"], stdout=subprocess.PIPE, text=True)
                                    if "3B1F67EA9BBUHK76" in res.stdout or "fastboot" in res.stdout:
                                        log(">>> 探测到 fastboot 设备，正在自动执行 fastboot boot out/test-boot.img...")
                                        boot_res = subprocess.run(["fastboot", "boot", "/Users/damon/unixnu-pagani/out/test-boot.img"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                                        log(f"fastboot boot 输出:\n{boot_res.stdout}\n{boot_res.stderr}")
                                        push_wechat("🚀 OnePlus 13s XNU v14 已成功自动引导到真机！请查看屏幕！")
                                        break
                else:
                    log(f"❌ 构建结束，结果为: {conclusion}")
                    push_wechat(f"❌ XNU 构建结束，结果为: {conclusion}")
                break
    except Exception as e:
        log(f"监控异常: {e}")
    time.sleep(20)
