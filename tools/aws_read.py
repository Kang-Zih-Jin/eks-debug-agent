"""
Tier 1：AWS API 唯讀查詢工具。任何 endpoint 模式都能跑（走 AWS API 不依賴叢集內網）。
透過 guards.assert_aws_readonly 雙層擋寫入。
"""
import boto3
from botocore.exceptions import ClientError

from .guards import assert_aws_readonly
from .session import get_client

def aws_read(service: str, action: str, region: str = "ap-northeast-1",
             params: dict | None = None) -> dict:
    """
    呼叫任一 AWS service 的唯讀 API。
    service: boto3 client 名（如 'eks'、'ec2'、'logs'、'autoscaling'、'elbv2'）
    action:  boto3 method 名，須為唯讀（如 'describe_cluster'）
    params:  該 API 的參數 dict
    回傳：含結果與真實 RequestId，供證據帳本引用。
    """
    # boto3 method 是 snake_case，白名單用 PascalCase 比對 → 轉換後檢查
    pascal = "".join(p.capitalize() for p in action.split("_"))
    assert_aws_readonly(pascal)

    client = get_client(service, region)
    method = getattr(client, action, None)
    if method is None:
        return {"status": "NO_DATA", "reason": f"{service} 無 method {action}"}

    try:
        resp = method(**(params or {}))
    except ClientError as e:
        return {
            "status": "NO_DATA",
            "reason": f"{e.response['Error']['Code']}: {e.response['Error']['Message']}",
            "request_id": e.response.get("ResponseMetadata", {}).get("RequestId"),
        }

    req_id = resp.pop("ResponseMetadata", {}).get("RequestId")
    return {"status": "OK", "data": resp, "request_id": req_id}
