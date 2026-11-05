#!/usr/bin/env bash
# 一条命令完成"把文档改动同步到所有副本"，让步骤级同步不因为麻烦而被跳过。
#
#   tools/sync_docs.sh "本轮一句话摘要"
#
# 做四件事：
#   1. docs/ 同步到归档目录（~/Documents/OnePlus13s-XNU移植/）
#   2. docs/ 单独提交（不碰 xnu/patches/，因此不会触发内核构建）
#   3. 推送，带重试（GitHub 出过 commit_refs_rules 瞬时故障）
#   4. 一致性自检 + 打印最新提交
#
# 铁律：文档提交绝不与 xnu/patches/ 混在一起。build-xnu.yml 的触发路径
# 只有 xnu/patches/** 和 workflow 文件本身，所以纯 docs 提交不会浪费一轮构建。

set -uo pipefail

REPO="${REPO:-$HOME/unixnu-pagani}"
ARCHIVE="${ARCHIVE:-$HOME/Documents/OnePlus13s-XNU移植}"
MSG="${1:-sync docs}"
DOCS=(XNU_HANDOFF_PROMPT.md ONEPLUS_13S_XNU_PORTING_DEBUG_LOG.md ONEPLUS_13S_XNU_PORTING_MILESTONE_REPORT.md)

cd "$REPO" || { echo "FATAL: $REPO 不存在"; exit 1; }

# 0. 防止误伤：patch 有未提交改动时提示但不阻止（文档可以单独提交）
if ! git diff --quiet -- xnu/patches 2>/dev/null; then
    echo "WARN: xnu/patches/ 有未提交改动，本次只提交 docs/，补丁请另行提交"
fi

# 0.5 刷新状态卡里的「台账快照」行（只写客观事实：HEAD / Run / 引导记录）
#     手写的「最新内核提交」「最新构建」两行不动——那里面有判断，机器写不出来。
if [ -f tools/refresh_status.py ]; then
    python3 tools/refresh_status.py || echo "WARN: 状态快照刷新失败，继续"
fi

# 1. 归档副本
mkdir -p "$ARCHIVE"
for f in "${DOCS[@]}"; do
    [ -f "docs/$f" ] && cp "docs/$f" "$ARCHIVE/"
done
echo "ARCHIVED -> $ARCHIVE"

# 2. 提交（只 add docs/）
if git diff --quiet -- docs 2>/dev/null && git diff --cached --quiet -- docs 2>/dev/null; then
    echo "NO-CHANGE: docs/ 无改动，跳过提交"
else
    git add docs
    git commit -q -m "docs: $MSG" || { echo "FATAL: commit 失败"; exit 1; }
    echo "COMMITTED: $MSG"
fi

# 3. 推送，最多 5 次退避
pushed=0
for i in 1 2 3 4 5; do
    if git push -q origin main 2>/dev/null; then
        echo "PUSHED (attempt $i)"
        pushed=1
        break
    fi
    echo "push attempt $i failed, retry in $((i*3))s"
    sleep $((i*3))
done
[ "$pushed" -eq 1 ] || echo "WARN: 推送未成功，本地提交已保全，稍后重试"

# 4. 自检
for f in "${DOCS[@]}"; do
    if [ -f "$ARCHIVE/$f" ] && diff -q "docs/$f" "$ARCHIVE/$f" >/dev/null 2>&1; then
        echo "SYNC OK   $f"
    else
        echo "SYNC FAIL $f"
    fi
done
echo "--- HEAD ---"
git log --oneline -1
