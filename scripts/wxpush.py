#!/usr/bin/env python3
"""Push a message to the user's WeChat via the Hermes weixin (iLink) channel.

Usage: wxpush.py "message text"
Reads WEIXIN_TOKEN / WEIXIN_ACCOUNT_ID / WEIXIN_HOME_CHANNEL / WEIXIN_BASE_URL
from ~/.hermes/.env. Runs on the gateway's venv python.
"""
import asyncio
import os
import sys
from pathlib import Path

HERMES_HOME = Path.home() / ".hermes"
ENV_FILE = HERMES_HOME / ".env"
REPO = HERMES_HOME / "hermes-agent"

def load_env():
    vals = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals

async def main(message: str):
    env = load_env()
    token = env.get("WEIXIN_TOKEN")
    account_id = env.get("WEIXIN_ACCOUNT_ID")
    chat_id = env.get("WEIXIN_HOME_CHANNEL")
    base_url = env.get("WEIXIN_BASE_URL", "https://ilinkai.weixin.qq.com")
    cdn = env.get("WEIXIN_CDN_BASE_URL", "https://novac2c.cdn.weixin.qq.com/c2c")
    if not (token and account_id and chat_id):
        print("missing WEIXIN_* config", file=sys.stderr)
        return 2
    sys.path.insert(0, str(REPO))
    from plugins.platforms.weixin.adapter import send_weixin_direct
    result = await send_weixin_direct(
        extra={"account_id": account_id, "base_url": base_url, "cdn_base_url": cdn},
        token=token,
        chat_id=chat_id,
        message=message,
    )
    print(result)
    return 0 if not result.get("error") else 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "（空消息测试）")))
