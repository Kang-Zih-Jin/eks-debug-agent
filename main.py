"""
EKS 唯讀除錯 AgentCore agent（Strands）。
方法論：.kiro/skills/read-only-debug-agent/SKILL.md
部署：.kiro/skills/agentcore-deploy/SKILL.md
"""
from strands import Agent, tool
from strands.models.bedrock import BedrockModel
from bedrock_agentcore import BedrockAgentCoreApp

from tools import (
    probe_cluster as _probe,
    aws_read as _aws_read,
    setup_kubeconfig as _setup_kubeconfig,
    kubectl_read as _kubectl_read,
)

# Opus 4.8 inference profile（ap-northeast-1 區域內，資料留日本區）。
# 存在性已用 list-inference-profiles 確認 ACTIVE；若帳號未通過 Bedrock 驗證 converse 會 403。
# 全球路由可改用 global.anthropic.claude-opus-4-8。Opus 4.7+ 只支援 adaptive thinking。
MODEL_ID = "jp.anthropic.claude-opus-4-8"
REGION = "ap-northeast-1"


# ---------- Tier 1：環境探測（開場必跑） ----------
@tool
def probe_cluster(cluster_name: str, region: str = REGION) -> dict:
    """探測 EKS 叢集 endpoint 模式，判斷標準 CloudShell 能否下 kubectl。
    除錯開場第一步必呼叫此工具，依 kubectl_usable 決定走 Tier 1 純 API 或啟用 kubectl。"""
    return _probe(cluster_name, region)


# ---------- Tier 1：AWS API 唯讀查詢（任何 endpoint 都能跑） ----------
@tool
def aws_read(service: str, action: str, region: str = REGION, params: dict = None) -> dict:
    """呼叫 AWS service 的唯讀 API（Describe/Get/List/Search...）。
    service 例：eks/ec2/logs/autoscaling/elbv2。action 為 boto3 snake_case method 名。
    寫入動詞會被白名單擋下。回傳含真實 RequestId 供證據引用。"""
    return _aws_read(service, action, region, params)


# ---------- Tier 2：kubectl 唯讀（探測通過才用） ----------
@tool
def setup_kubeconfig(cluster_name: str, region: str = REGION) -> dict:
    """產生 kubeconfig。僅在 probe_cluster 判定 kubectl_usable 為 True 後才呼叫。"""
    return _setup_kubeconfig(cluster_name, region)


@tool
def kubectl_read(args: list) -> dict:
    """執行唯讀 kubectl（get/describe/logs/top/events...）。
    args 例：['get','pods','-n','ns']、['logs','pod','--previous','-n','ns']。
    寫入動詞與 exec/port-forward/secrets 會被擋。kubeconfig 未就緒回 NO_DATA。"""
    return _kubectl_read(args)


SYSTEM_PROMPT = """你是 EKS 唯讀除錯 agent，只能查不能改。

## 紀律
1. 唯讀：只用提供的查詢工具，絕不嘗試任何寫入操作。
2. 防幻覺：每個關於叢集狀態的聲明都必須來自工具實際回傳，引用證據；
   查不到、沒權限、工具回 NO_DATA → 明確說 NO_DATA，禁止用通用知識編造答案。
3. 講 AWS/EKS 服務行為或限制前，若不確定先說明這是一般理解、建議查官方文件。

## 除錯流程（分層降級）
1. 開場必先呼叫 probe_cluster 判斷 endpoint 模式。
2. kubectl_usable=True → setup_kubeconfig 後可用 kubectl_read（Tier 2）。
3. kubectl_usable=False/maybe → 誠實告知限制，只用 aws_read（Tier 1，純 AWS API）：
   - describe-cluster / describe-nodegroup 看控制面
   - ec2 describe-instances / describe-subnets 看 node 與 IP 餘量
   - logs（CloudWatch）看 Container Insights 與 control plane log
4. 跨層關聯：Pod Pending→node 不足→ASG/子網 IP 耗盡；ImagePullBackOff→ECR/NAT；OOMKilled→limits。

## log 三層來源
- kubectl logs（含 --previous 抓 CrashLoop 前一個容器）
- CloudWatch Container Insights / Fluent Bit（pod 已死看歷史）
- EKS control plane log（api/audit/authenticator/controllerManager/scheduler）
"""

app = BedrockAgentCoreApp()
agent = Agent(
    model=BedrockModel(model_id=MODEL_ID, region_name=REGION),
    tools=[probe_cluster, aws_read, setup_kubeconfig, kubectl_read],
    system_prompt=SYSTEM_PROMPT,
)


@app.entrypoint
async def invoke(payload):
    async for event in agent.stream_async(payload.get("prompt", "")):
        yield event


if __name__ == "__main__":
    app.run()
