#!/usr/bin/env bash
# EKS 唯讀除錯 agent — CloudShell 直跑（不部署 AgentCore、不建 role）。
# 用 CloudShell 當前登入身分的權限。
# 用法：
#   ./run.sh                          # 互動問答
#   ./run.sh "檢查我的 EKS 有沒有問題"    # 單次提問（推薦，避開互動輸入編碼問題）
set -euo pipefail

# --- 環境硬化（CloudShell 已知地雷一次設好）---
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8
# locale 非 UTF-8 會害中文輸入崩
export LC_ALL="${LC_ALL:-C.UTF-8}"
export LANG="${LANG:-C.UTF-8}"
# CloudShell 預設 AWS_REGION=us-east-1 → 區域型 profile(jp.*) 會 invalid 且查錯區，強制覆蓋
export AWS_REGION="${EKS_DEBUG_REGION:-ap-northeast-1}"
export AWS_DEFAULT_REGION="$AWS_REGION"
export BEDROCK_REGION="${BEDROCK_REGION:-ap-northeast-1}"

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- venv（持久區只有 1GB → 裝 /tmp），requirements 沒變就跳過安裝 ---
VENV=/tmp/eks-debug-venv
if [ ! -d "$VENV" ]; then
  echo "==> 首次建立 venv（$VENV）"
  python3 -m venv "$VENV"
fi
# shellcheck source=/dev/null
source "$VENV/bin/activate"

STAMP="$VENV/.req.md5"
NEW_HASH="$(md5sum requirements.txt | awk '{print $1}')"
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$NEW_HASH" ]; then
  echo "==> 安裝相依套件"
  pip -q install --upgrade pip >/dev/null
  pip -q install -r requirements.txt
  echo "$NEW_HASH" > "$STAMP"
fi

python main.py "$@"
