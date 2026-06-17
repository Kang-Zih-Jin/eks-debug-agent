#!/usr/bin/env bash
# EKS 唯讀除錯 agent — CloudShell 直跑（不部署 AgentCore、不建 role）。
# 用 CloudShell 當前登入身分的權限。
# 用法：
#   ./run.sh                  # 互動問答
#   ./run.sh "診斷 my-cluster pod 為何 Pending"   # 單次提問
set -euo pipefail

export PYTHONUTF8=1 PYTHONIOENCODING=utf-8
# CloudShell locale 常非 UTF-8，會害中文輸入在 input() 崩（UnicodeDecodeError）→ 強制 UTF-8 locale
export LC_ALL="${LC_ALL:-C.UTF-8}"
export LANG="${LANG:-C.UTF-8}"
# CloudShell 預設 AWS_REGION=us-east-1，這裡強制覆蓋成目標區（預設東京），
# 否則區域型 inference profile(jp.*) 會在 us-east-1 報 invalid，且 EKS 查詢跑錯區。
export AWS_REGION="${EKS_DEBUG_REGION:-ap-northeast-1}"
export AWS_DEFAULT_REGION="$AWS_REGION"
export BEDROCK_REGION="${BEDROCK_REGION:-ap-northeast-1}"

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# CloudShell 持久區只有 1GB → venv 裝 /tmp
VENV=/tmp/eks-debug-venv
if [ ! -d "$VENV" ]; then
  echo "==> 首次建立 venv（$VENV）"
  python3 -m venv "$VENV"
fi
# shellcheck source=/dev/null
source "$VENV/bin/activate"
pip -q install --upgrade pip >/dev/null
pip -q install -r requirements.txt

echo "==> 啟動 EKS 唯讀除錯 agent"
python main.py "$@"
