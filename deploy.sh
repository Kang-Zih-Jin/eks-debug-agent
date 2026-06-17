#!/usr/bin/env bash
# EKS 唯讀除錯 agent 一鍵部署（標準 CloudShell，連網非 VPC）
# 含 Execution Role 自動偵測/建立：role 已存在則沿用，不存在才建。
# 用法：./deploy.sh [REGION] [AGENT_NAME] [ROLE_NAME]
#   預設 REGION=ap-northeast-1  AGENT_NAME=eks-debug  ROLE_NAME=eks-debug-exec-role
# 細節/踩雷見 .kiro/skills/agentcore-deploy 與 read-only-debug-agent skill
set -euo pipefail

REGION="${1:-ap-northeast-1}"
AGENT_NAME="${2:-eks-debug}"
ROLE_NAME="${3:-eks-debug-exec-role}"

# [踩雷] agentcore 輸出含 emoji，pipe 時 stdout 退回 Big5 會 UnicodeEncodeError → 強制 UTF-8
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8 AGENTCORE_SUPPRESS_RECOMMENDATION=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "==> 站對帳號確認"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
echo "    Account=$ACCOUNT_ID  Region=$REGION"

# ---------- Execution Role：先偵測，沒有才建 ----------
if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  echo "==> Execution Role '$ROLE_NAME' 已存在，沿用"
  ROLE_ARN="$(aws iam get-role --role-name "$ROLE_NAME" --query Role.Arn --output text)"
else
  echo "==> Execution Role '$ROLE_NAME' 不存在，建立中"
  # 信任政策：principal bedrock-agentcore + SourceAccount/SourceArn 雙條件防混淆代理人
  cat > /tmp/${ROLE_NAME}-trust.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
    "Action": "sts:AssumeRole",
    "Condition": {
      "StringEquals": {"aws:SourceAccount": "$ACCOUNT_ID"},
      "ArnLike": {"aws:SourceArn": "arn:aws:bedrock-agentcore:$REGION:$ACCOUNT_ID:*"}
    }
  }]
}
EOF
  ROLE_ARN="$(aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document file:///tmp/${ROLE_NAME}-trust.json \
    --query Role.Arn --output text)"
  # 業務唯讀 + runtime 營運權限兩件套
  aws iam put-role-policy --role-name "$ROLE_NAME" \
    --policy-name eks-debug-readonly \
    --policy-document file://iam/execution-role-policy.json
  aws iam put-role-policy --role-name "$ROLE_NAME" \
    --policy-name eks-debug-runtime \
    --policy-document file://iam/runtime-operational-policy.json
  echo "    建立完成，等待 IAM 傳播..."
  sleep 10
fi
echo "    ROLE_ARN=$ROLE_ARN"

# ---------- venv（CloudShell 持久區只有 1GB → 裝 /tmp） ----------
VENV=/tmp/eks-debug-venv
echo "==> 建立 venv（$VENV）"
python3 -m venv "$VENV"
# shellcheck source=/dev/null
source "$VENV/bin/activate"
pip -q install --upgrade pip
pip -q install bedrock-agentcore-starter-toolkit

# ---------- configure → deploy → 冒煙測試 ----------
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
