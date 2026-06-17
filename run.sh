#!/usr/bin/env bash
# EKS 唯讀除錯 agent — CloudShell 直跑（不部署 AgentCore、不建 role）。
# 用 CloudShell 當前登入身分的權限。
# 用法：
#   ./run.sh                  # 互動問答
#   ./run.sh "診斷 my-cluster pod 為何 Pending"   # 單次提問
set -euo pipefail

export PYTHONUTF8=1 PYTHONIOENCODING=utf-8
export AWS_REGION="${AWS_REGION:-ap-northeast-1}"

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
