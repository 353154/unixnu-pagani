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
RUN_ID = "41903882061"

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

log(f"\n=== 切换监控目标: Run #{RUN_ID} ===")

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
                else:
                    log(f"❌ 构建结束，结果为: {conclusion}")
                break
    except Exception as e:
        log(f"监控异常: {e}")
    time.sleep(20)
