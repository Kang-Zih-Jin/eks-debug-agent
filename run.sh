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
# CloudShell 預設 AWS_REGION=us-east-1，會害區域型 profile invalid 且查錯區。
# 仿 EVS：查詢區與模型區拆開——模型固定 us-east-1 跑 us. profile（最穩），查詢區可指定。
export EKS_DEBUG_REGION="${EKS_DEBUG_REGION:-ap-northeast-1}"   # 你的 EKS 在哪區（要查別區就 export 這個）
export AWS_REGION="$EKS_DEBUG_REGION"                           # 讓 kubectl 用的 aws CLI 也指向查詢區
export AWS_DEFAULT_REGION="$EKS_DEBUG_REGION"
export BEDROCK_REGION="${BEDROCK_REGION:-us-east-1}"            # Bedrock 模型區（預設 us-east-1，最穩）
export EKS_DEBUG_MODEL="${EKS_DEBUG_MODEL:-us.anthropic.claude-opus-4-8}"
# 選配：查詢時 assume 一個唯讀 role 做縱深防禦（不設則用 CloudShell 當前身分）
export EKS_DEBUG_ROLE_ARN="${EKS_DEBUG_ROLE_ARN:-}"

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
