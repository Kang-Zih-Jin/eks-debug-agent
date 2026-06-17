"""
EKS 唯讀除錯 agent — CloudShell 直跑版。
用 CloudShell 當前登入身分的權限直接查，不部署到 AgentCore Runtime。
方法論：.kiro/skills/read-only-debug-agent/SKILL.md
用法：
  python main.py                       # 互動問答
  python main.py "檢查我的 EKS 有沒有問題"   # 單次提問
"""
import os
import sys

# CloudShell locale 常非 UTF-8 → 中文輸入會在 input() 觸發 UnicodeDecodeError。
# 啟動就把標準串流轉 UTF-8 且容錯，徹底避免中文崩潰。
for _stream in (sys.stdin, sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

MODEL_ID = os.environ.get("EKS_DEBUG_MODEL", "jp.anthropic.claude-opus-4-8")
REGION = os.environ.get("AWS_REGION", "ap-northeast-1")            # AWS 資源查詢區域
MODEL_REGION = os.environ.get("BEDROCK_REGION", "ap-northeast-1")  # Bedrock 模型區域（須與 profile 前綴相符）


def preflight() -> tuple[bool, str]:
    """啟動前檢查：確認身分 + 模型可用，不通就回清楚訊息（不進對話才爆 traceback）。"""
    try:
        ident = boto3.client("sts", region_name=REGION).get_caller_identity()
    except (BotoCoreError, ClientError, NoCredentialsError) as e:
        return False, f"取不到 AWS 身分（憑證問題）：{e}"
    try:
        boto3.client("bedrock-runtime", region_name=MODEL_REGION).converse(
            modelId=MODEL_ID,
            messages=[{"role": "user", "content": [{"text": "ping"}]}],
            inferenceConfig={"maxTokens": 1},
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        msg = e.response.get("Error", {}).get("Message", "")
        return False, (
            f"Bedrock 模型不可用 [{code}]：{msg}\n"
            f"  模型={MODEL_ID} 區域={MODEL_REGION}\n"
            f"  解法：用 EKS_DEBUG_MODEL / BEDROCK_REGION 覆寫，或確認此帳號已在該區開通該模型。"
        )
    except (BotoCoreError, NoCredentialsError) as e:
        return False, f"Bedrock 連線問題：{e}"
    return True, f"帳號 {ident['Account']}｜模型 {MODEL_ID}@{MODEL_REGION}｜查詢區 {REGION}"


# Strands 與工具較重，preflight 過了才載入
from strands import Agent, tool  # noqa: E402
from strands.models.bedrock import BedrockModel  # noqa: E402

from tools import (  # noqa: E402
    probe_cluster as _probe,
    aws_read as _aws_read,
    setup_kubeconfig as _setup_kubeconfig,
    kubectl_read as _kubectl_read,
)


@tool
def probe_cluster(cluster_name: str, region: str = REGION) -> dict:
    """探測 EKS 叢集 endpoint 模式，判斷標準 CloudShell 能否下 kubectl。
    對某個叢集除錯前先呼叫，依 kubectl_usable 決定走純 API 或啟用 kubectl。"""
    return _probe(cluster_name, region)


@tool
def aws_read(service: str, action: str, region: str = REGION, params: dict = None) -> dict:
    """呼叫 AWS service 的唯讀 API（Describe/Get/List/Search...）。
    service 例：eks/ec2/logs/autoscaling/elbv2。action 為 boto3 snake_case method 名
    （如 list_clusters、describe_cluster、describe_nodegroup）。
    寫入動詞會被白名單擋下。回傳含真實 RequestId。"""
    return _aws_read(service, action, region, params)


@tool
def setup_kubeconfig(cluster_name: str, region: str = REGION) -> dict:
    """產生 kubeconfig。僅在 probe_cluster 判定 kubectl_usable 為 True 後才呼叫。"""
    return _setup_kubeconfig(cluster_name, region)


@tool
def kubectl_read(args: list) -> dict:
    """執行唯讀 kubectl（get/describe/logs/top/events...）。
    args 例：['get','pods','-A']、['logs','pod','--previous','-n','ns']。
    寫入動詞與 exec/port-forward/secrets 會被擋。kubeconfig 未就緒回 NO_DATA。"""
    return _kubectl_read(args)


SYSTEM_PROMPT = """你是 EKS 唯讀除錯 agent，只能查不能改。

## 紀律
1. 唯讀：只用提供的查詢工具，絕不嘗試任何寫入操作。
2. 防幻覺：每個關於叢集狀態的聲明都必須來自工具實際回傳；查不到、沒權限、
   工具回 NO_DATA → 明確說 NO_DATA，禁止用通用知識編造答案。
3. 講 AWS/EKS 服務行為或限制前，不確定就說明這是一般理解、建議查官方文件。

## 除錯流程
1. 若使用者沒給叢集名 → 先 `aws_read(service='eks', action='list_clusters')` 列出叢集。
2. 對每個要查的叢集先 `probe_cluster` 判 endpoint 模式。
3. kubectl_usable=True → setup_kubeconfig 後可用 kubectl_read。
4. kubectl_usable=False/maybe → 誠實告知限制，只用 aws_read（純 AWS API）：
   describe_cluster/describe_nodegroup 看控制面；ec2 看 node 與子網 IP 餘量；logs 看 CloudWatch。
5. 跨層關聯：Pod Pending→node 不足→ASG/子網 IP 耗盡；ImagePullBackOff→ECR/NAT；OOMKilled→limits。

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
    """問一題，AWS/執行錯誤轉成一行友善訊息，不噴 traceback。"""
    try:
        print(_agent(prompt))
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        msg = e.response.get("Error", {}).get("Message", "")
        print(f"[AWS 錯誤] {code}: {msg}")
        if code in ("AccessDeniedException", "ValidationException"):
            print(f"  提示：確認模型 {MODEL_ID}@{MODEL_REGION} 可用、帳號已開通 Bedrock；"
                  f"可用 EKS_DEBUG_MODEL/BEDROCK_REGION 覆寫。")
    except NoCredentialsError:
        print("[認證錯誤] 找不到 AWS 憑證（CloudShell 應自動帶入，請確認已登入）。")
    except (BotoCoreError, Exception) as e:  # noqa: BLE001 - CLI 不該因單題崩潰
        print(f"[執行錯誤] {type(e).__name__}: {e}")


def main() -> None:
    ok, info = preflight()
    if not ok:
        print("✗ 啟動前檢查未通過：")
        print("  " + info)
        sys.exit(1)
    print("✓ " + info)

    # 單次提問
    if len(sys.argv) > 1:
        ask(" ".join(sys.argv[1:]))
        return

    # 互動模式
    print("EKS 唯讀除錯 agent。輸入問題，exit/quit 離開。\n")
    while True:
        try:
            q = input("eks-debug> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        except UnicodeDecodeError:
            print("（輸入編碼異常，請重打一次；或改用 ./run.sh \"你的問題\" 單次提問模式）")
            continue
        if q in ("exit", "quit"):
            break
        if not q:
            continue
        ask(q)
        print()


if __name__ == "__main__":
    main()
