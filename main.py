"""
EKS 唯讀除錯 agent — CloudShell 直跑版（互動 CLI）。
用 CloudShell 當前登入身分的權限直接查，不部署到 AgentCore Runtime。
方法論：.kiro/skills/read-only-debug-agent/SKILL.md
用法：
  python main.py                 # 互動問答模式
  python main.py "診斷 my-cluster pod 為何 Pending"   # 單次提問
"""
import os
import sys

# CloudShell locale 常非 UTF-8，導致中文輸入在 input() 觸發 UnicodeDecodeError。
# 強制把標準串流轉 UTF-8 並容錯，確保中文輸入不崩。
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from strands import Agent, tool
from strands.models.bedrock import BedrockModel

from tools import (
    probe_cluster as _probe,
    aws_read as _aws_read,
    setup_kubeconfig as _setup_kubeconfig,
    kubectl_read as _kubectl_read,
)

# Opus 4.8 inference profile（ap-northeast-1 區內）。list-inference-profiles 確認 ACTIVE。
# 全球路由可改 global.anthropic.claude-opus-4-8。Opus 4.7+ 只支援 adaptive thinking。
MODEL_ID = os.environ.get("EKS_DEBUG_MODEL", "jp.anthropic.claude-opus-4-8")
REGION = os.environ.get("AWS_REGION", "ap-northeast-1")            # AWS 資源查詢區域
MODEL_REGION = os.environ.get("BEDROCK_REGION", "ap-northeast-1")  # Bedrock 模型區域（須與 profile 前綴相符）


@tool
def probe_cluster(cluster_name: str, region: str = REGION) -> dict:
    """探測 EKS 叢集 endpoint 模式，判斷標準 CloudShell 能否下 kubectl。
    除錯開場第一步必呼叫，依 kubectl_usable 決定走純 API 或啟用 kubectl。"""
    return _probe(cluster_name, region)


@tool
def aws_read(service: str, action: str, region: str = REGION, params: dict = None) -> dict:
    """呼叫 AWS service 的唯讀 API（Describe/Get/List/Search...）。
    service 例：eks/ec2/logs/autoscaling/elbv2。action 為 boto3 snake_case method 名。
    寫入動詞會被白名單擋下。回傳含真實 RequestId 供證據引用。"""
    return _aws_read(service, action, region, params)


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
2. 防幻覺：每個關於叢集狀態的聲明都必須來自工具實際回傳；查不到、沒權限、
   工具回 NO_DATA → 明確說 NO_DATA，禁止用通用知識編造答案。
3. 講 AWS/EKS 服務行為或限制前，若不確定先說明這是一般理解、建議查官方文件。

## 除錯流程（分層降級）
1. 開場必先呼叫 probe_cluster 判斷 endpoint 模式。
2. kubectl_usable=True → setup_kubeconfig 後可用 kubectl_read。
3. kubectl_usable=False/maybe → 誠實告知限制，只用 aws_read（純 AWS API）：
   describe-cluster/nodegroup 看控制面；ec2 看 node 與子網 IP 餘量；logs 看 CloudWatch。
4. 跨層關聯：Pod Pending→node 不足→ASG/子網 IP 耗盡；ImagePullBackOff→ECR/NAT；OOMKilled→limits。

## log 三層
kubectl logs(--previous) / CloudWatch Container Insights / EKS control plane log
(api/audit/authenticator/controllerManager/scheduler)
"""

_agent = Agent(
    model=BedrockModel(model_id=MODEL_ID, region_name=MODEL_REGION),
    tools=[probe_cluster, aws_read, setup_kubeconfig, kubectl_read],
    system_prompt=SYSTEM_PROMPT,
)


def ask(prompt: str) -> None:
    result = _agent(prompt)
    print(result)


def main() -> None:
    # 單次提問模式
    if len(sys.argv) > 1:
        ask(" ".join(sys.argv[1:]))
        return
    # 互動模式
    print("EKS 唯讀除錯 agent（CloudShell）。輸入問題，exit/quit 離開。")
    print(f"模型 {MODEL_ID} @ {MODEL_REGION}；查詢區域 {REGION}；使用當前 CloudShell 身分的權限。\n")
    while True:
        try:
            q = input("eks-debug> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        except UnicodeDecodeError:
            print("（輸入編碼異常，請重打一次；確認 LC_ALL=C.UTF-8）")
            continue
        if q in ("exit", "quit"):
            break
        if not q:
            continue
        ask(q)
        print()


if __name__ == "__main__":
    main()
