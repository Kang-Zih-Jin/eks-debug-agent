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

# 解析「當前呼叫者」的真實 principal，讓 trust 直接信任它
# （SSO/federated 角色沒有額外 sts:AssumeRole 權限時，root-trust 會被拒 → 必須直接信任呼叫者角色）
CALLER_ARN="$(aws sts get-caller-identity --query Arn --output text)"
PRINCIPAL=""
if [[ "$CALLER_ARN" == *":assumed-role/"* ]]; then
  _rn="$(printf '%s' "$CALLER_ARN" | sed -E 's#.*:assumed-role/([^/]+)/.*#\1#')"
  # 解析真實 IAM role ARN（含路徑，正確處理 SSO 角色）
  PRINCIPAL="$(aws iam get-role --role-name "$_rn" --query Role.Arn --output text 2>/dev/null || true)"
fi
[ -z "$PRINCIPAL" ] && PRINCIPAL="$CALLER_ARN"   # IAM user 或解析失敗 → 直接信任呼叫者 ARN
echo "==> 信任 principal：$PRINCIPAL"

# 動態產生 trust（同時信任呼叫者角色 + 帳號 root；PrincipalAccount 鎖同帳號）
cat > /tmp/eks-debug-trust.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "AllowCallerAndAccount",
    "Effect": "Allow",
    "Principal": {"AWS": ["$PRINCIPAL", "arn:aws:iam::$ACCOUNT_ID:root"]},
    "Action": "sts:AssumeRole",
    "Condition": {"StringEquals": {"aws:PrincipalAccount": "$ACCOUNT_ID"}}
  }]
}
EOF

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

echo "==> 等待 IAM 傳播（trust/policy 生效需數秒）..."
sleep 10

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
echo
echo "✅ 完成。唯讀 role ARN："
echo "   $ROLE_ARN"
echo "用法：EKS_DEBUG_ROLE_ARN=$ROLE_ARN ./run.sh \"檢查我的 EKS\""
