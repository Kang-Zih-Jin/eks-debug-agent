#!/usr/bin/env bash
# EKS 唯讀除錯 agent 一鍵部署（標準 CloudShell，連網非 VPC）
# 用法：./deploy.sh <EXECUTION_ROLE_ARN> [REGION] [AGENT_NAME]
# 細節/踩雷見 .kiro/skills/agentcore-deploy/SKILL.md
set -euo pipefail

ROLE_ARN="${1:?需傳入 Execution Role ARN：./deploy.sh <arn> [region] [name]}"
REGION="${2:-ap-northeast-1}"
AGENT_NAME="${3:-eks-debug}"

# [踩雷] agentcore 輸出含 emoji，pipe 時 stdout 退回 Big5 會 UnicodeEncodeError → 強制 UTF-8
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8 AGENTCORE_SUPPRESS_RECOMMENDATION=1

echo "==> 站對帳號確認"
aws sts get-caller-identity --query Account --output text

# CloudShell 持久區只有 1GB → venv 裝 /tmp 省空間
VENV=/tmp/eks-debug-venv
echo "==> 建立 venv（$VENV）"
python3 -m venv "$VENV"
# shellcheck source=/dev/null
source "$VENV/bin/activate"
pip -q install --upgrade pip
pip -q install bedrock-agentcore-starter-toolkit

echo "==> configure"
agentcore configure \
  --entrypoint main.py \
  --name "$AGENT_NAME" \
  --execution-role "$ROLE_ARN" \
  --requirements-file requirements.txt \
  --region "$REGION" \
  --non-interactive

echo "==> deploy（CodeBuild 遠端建 ARM64，本機免 Docker）"
agentcore deploy

echo "==> 冒煙測試"
agentcore invoke '{"prompt":"先 probe_cluster 探測叢集 endpoint 模式，告訴我 kubectl 能不能用"}'

echo "==> 完成。觀察 log：aws logs tail /aws/bedrock-agentcore/runtimes/$AGENT_NAME --follow --region $REGION"
