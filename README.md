# EKS 唯讀除錯 Agent

只查不改的 EKS 除錯 AgentCore agent。沿用 evs-debug-agent 的防護骨架，新增「AWS API + kubectl 雙軸 + 分層降級」。

- 方法論：`.kiro/skills/read-only-debug-agent/SKILL.md`
- 部署機制：`.kiro/skills/agentcore-deploy/SKILL.md`

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

> 連線環境定調為**標準 CloudShell（連網、非 VPC）**：換來零網路設定，代價是 private-only 叢集放棄 kubectl。

## 防護骨架（read-only-debug-agent 方法論）
- 唯讀工具白名單：無 raw shell，`guards.py` 對 AWS action 與 kubectl verb 雙層動詞檢查
- 擋 secrets / exec / port-forward（防明文外洩與側信道）
- 證據帳本 + `[E#]` 引用 + 確定性 validator（`guards.validate_citations`）
- 查不到一律 `NO_DATA`，不用通用知識補洞

## 部署（摘要，細節見 agentcore-deploy skill）
1. 建 Execution Role：附 `iam/execution-role-policy.json`（業務唯讀）+ 官方 runtime 營運權限（ECR/logs/X-Ray/InvokeModel/GetWorkloadAccessToken）。
2. **kubectl 要能查叢集**：把 Execution Role 用 **EKS Access Entry** 綁定唯讀 access policy `AmazonEKSViewPolicy`（或對應 RBAC view ClusterRole）。注意 view 不含 secrets，剛好符合本 agent 禁查 secrets 的設計。
3. 模型：部署前用 `aws bedrock-runtime converse --model-id <id>` 驗證 `MODEL_ID`（main.py 內為待驗證值）。
4. `agentcore configure --entrypoint main.py --name eks-debug --execution-role <arn> --requirements-file requirements.txt --region ap-northeast-1 --non-interactive`
5. `agentcore deploy` → `agentcore invoke '{"prompt":"診斷 my-cluster 的 pod 為什麼 Pending"}'`

## 待辦
- [ ] 驗證並填入確切 Opus inference profile model id
- [ ] 接證據帳本到 entrypoint（目前 guards 已備，main.py 尚未串入回答後 validate）
- [ ] 選配：agent assume 獨立唯讀 role 再查（帳號層唯讀保險）
