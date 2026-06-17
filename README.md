# EKS 唯讀除錯 Agent

只查不改的 EKS 除錯 agent，**在 CloudShell 直接跑**（像 evs-debug-agent 一樣），用當前登入身分的權限，不部署到 AgentCore、不建任何雲端資源。

- 方法論：`.kiro/skills/read-only-debug-agent/SKILL.md`

## 快速開始（CloudShell）
```bash
git clone https://github.com/Kang-Zih-Jin/eks-debug-agent.git
cd eks-debug-agent
chmod +x run.sh
./run.sh                          # 互動問答
# 或單次提問：
./run.sh "診斷 my-cluster 的 pod 為什麼一直 Pending"
```
`run.sh` 做的事：建 venv 於 `/tmp`（省 CloudShell 持久區）→ `pip install` strands-agents + boto3 → 跑 `python main.py`。
**不建 IAM role、不碰 AgentCore**，agent 直接用你 CloudShell 當前身分的權限呼叫 AWS / Bedrock。

> 預設模型 `jp.anthropic.claude-opus-4-8`、區域 `ap-northeast-1`。
> 可用環境變數覆寫：`EKS_DEBUG_MODEL`、`AWS_REGION`。

## 架構

| Tier | 工具 | 可用條件 | 用途 |
|------|------|---------|------|
| **Tier 1（永遠可用）** | `aws_read` | 任何 endpoint 模式 | 控制面 / node / log，走 AWS API 不依賴叢集內網 |
| **探測** | `probe_cluster` | 開場必跑 | 讀 endpoint 模式判 kubectl 能否用 |
| **Tier 2（探測通過才用）** | `setup_kubeconfig` + `kubectl_read` | endpoint 連得到 | pod/node/logs 細節 |

### 分層降級判斷（probe_cluster）
- `public` + `publicAccessCidrs` 含 `0.0.0.0/0` → kubectl 可用
- `public` + 限制 CIDR → maybe，須確認 CloudShell 出口 IP 在白名單
- `private-only` → kubectl 不可用，降級純 AWS API

## 防護骨架（read-only-debug-agent 方法論）
- 唯讀工具白名單：無 raw shell，`guards.py` 對 AWS action 與 kubectl verb 雙層動詞檢查
- 擋 secrets / exec / port-forward（防明文外洩與側信道）
- 證據帳本 + `[E#]` 引用 + 確定性 validator（`guards.validate_citations`）
- 查不到一律 `NO_DATA`，不用通用知識補洞

## 需要的權限
agent 用 CloudShell 當前身分跑，該身分需具備 `iam/readonly-permissions.json` 列的唯讀權限
（`eks:Describe*/List*`、`ec2/autoscaling/elb Describe*`、`logs/cloudwatch` 唯讀）+ `bedrock:InvokeModel*`。
PowerUser/Admin 的 CloudShell 本就涵蓋。

### kubectl 補充
kubectl 要查叢集，IAM 身分還要被綁進叢集的 **EKS Access Entry**（唯讀 access policy `AmazonEKSViewPolicy`，
或對應 RBAC view ClusterRole）。view 不含 secrets，剛好符合本 agent 禁查 secrets 的設計。

## 檔案
```
main.py                 # 互動 CLI（Strands Agent 直呼 Bedrock）
run.sh                  # CloudShell 一鍵啟動
requirements.txt        # strands-agents + boto3
tools/                  # guards / eks_probe / aws_read / kubectl_read
iam/readonly-permissions.json   # 身分需要的最小唯讀權限（參考）
```
