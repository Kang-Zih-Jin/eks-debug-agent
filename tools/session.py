"""
共用 boto3 session：可選 assume 一個唯讀 role 做縱深防禦（仿 EVS）。

保證性（回應「操作時是否都用 role」）：
- 設了 EKS_DEBUG_ROLE_ARN → 所有資源查詢都走該 role 的 **自動續期** 臨時憑證；
  憑證到期會自動 refresh，整個 session 期間永遠帶 role，不會中途過期或降級。
- get_client 嚴格模式：session 未初始化直接 raise，**絕不 silent fallback 到預設身分**。
- 不設 role → 明確用 CloudShell 當前身分（仍是顯式 Session，非隱性）。
- Bedrock 模型呼叫不走此 session（用預設身分，因唯讀 role 通常無 bedrock 權限）。
"""
import boto3
from botocore.credentials import RefreshableCredentials
from botocore.session import get_session as _botocore_session

_state = {"session": None, "region": None, "role_arn": None}


def _refreshable_assume_role_session(region: str, role_arn: str) -> boto3.Session:
    """建立會自動續期的 assumed-role session：憑證到期前自動重新 assume。"""
    sts = boto3.client("sts", region_name=region)

    def _refresh() -> dict:
        c = sts.assume_role(
            RoleArn=role_arn,
            RoleSessionName="eks-debug-readonly",
            DurationSeconds=3600,
        )["Credentials"]
        return {
            "access_key": c["AccessKeyId"],
            "secret_key": c["SecretAccessKey"],
            "token": c["SessionToken"],
            "expiry_time": c["Expiration"].isoformat(),
        }

    creds = RefreshableCredentials.create_from_metadata(
        metadata=_refresh(),
        refresh_using=_refresh,
        method="sts-assume-role",
    )
    bc = _botocore_session()
    bc._credentials = creds
    bc.set_config_variable("region", region)
    return boto3.Session(botocore_session=bc)


def init_session(region: str, role_arn: str | None = None) -> None:
    if role_arn:
        _state["session"] = _refreshable_assume_role_session(region, role_arn)
    else:
        _state["session"] = boto3.Session(region_name=region)
    _state["region"] = region
    _state["role_arn"] = role_arn


def get_client(service: str, region: str | None = None):
    # 嚴格：未初始化就 raise，不准 silent fallback 到預設身分（避免誤用 CloudShell 身分）
    if _state["session"] is None:
        raise RuntimeError("session 未初始化；請先呼叫 init_session（拒絕用預設身分）")
    return _state["session"].client(service, region_name=region or _state["region"])


def assumed_role_arn() -> str | None:
    return _state["role_arn"]
