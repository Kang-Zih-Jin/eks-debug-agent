#!/usr/bin/env bash
# 建立 EksDebugReadOnlyRole（防 agent 的唯讀角色，縱深防禦）。
# 由有 IAM 權限者執行一次即可，之後 ./run.sh 用 EKS_DEBUG_ROLE_ARN assume 它。
# 用法：bash setup-role.sh
# 印出的 ARN 可直接餵給 run.sh（互動引導也會自動帶入）。
set -euo pipefail

ROLE_NAME="${EKS_DEBUG_ROLE_NAME:-EksDebugReadOnlyRole}"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"

echo "==> 帳號：$ACCOUNT_ID  角色：$ROLE_NAME"

# 把 ACCOUNT_ID 套進 trust 範本（輸出 /tmp 不污染 repo）
sed "s/ACCOUNT_ID/$ACCOUNT_ID/g" "$APP_DIR/iam/trust-policy.json" > /tmp/eks-debug-trust.json

if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  echo "==> 角色已存在，更新信任政策"
  aws iam update-assume-role-policy --role-name "$ROLE_NAME" \
    --policy-document file:///tmp/eks-debug-trust.json
else
  echo "==> 建立角色"
  aws iam create-role --role-name "$ROLE_NAME" \
    --description "Read-only role for EKS debug agent (defense against agent writes)" \
    --max-session-duration 3600 \
    --assume-role-policy-document file:///tmp/eks-debug-trust.json
fi

echo "==> 掛 AWS 託管 ViewOnlyAccess（基礎唯讀）"
aws iam attach-role-policy --role-name "$ROLE_NAME" \
  --policy-arn arn:aws:iam::aws:policy/job-function/ViewOnlyAccess

echo "==> 掛補充唯讀政策（EKS/EC2/ASG/ELB/Logs/CloudWatch）"
aws iam put-role-policy --role-name "$ROLE_NAME" \
  --policy-name eks-debug-readonly-extra \
  --policy-document file://"$APP_DIR/iam/readonly-permissions.json"

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
echo
echo "✅ 完成。唯讀 role ARN："
echo "   $ROLE_ARN"
echo "用法：EKS_DEBUG_ROLE_ARN=$ROLE_ARN ./run.sh \"檢查我的 EKS\""
