"""
共用 boto3 session：可選 assume 一個唯讀 role 做縱深防禦（仿 EVS）。
設了 EKS_DEBUG_ROLE_ARN → 查詢都走該 role 的臨時憑證（IAM 層擋寫，比 prompt 可靠）；
不設 → 用 CloudShell 當前身分。Bedrock 模型呼叫不走此 session（用預設身分）。
"""
import boto3

_state = {"session": None, "region": None, "role_arn": None}


def init_session(region: str, role_arn: str | None = None) -> None:
    if role_arn:
        sts = boto3.client("sts", region_name=region)
        cred = sts.assume_role(
            RoleArn=role_arn, RoleSessionName="eks-debug-readonly"
        )["Credentials"]
        _state["session"] = boto3.Session(
            aws_access_key_id=cred["AccessKeyId"],
            aws_secret_access_key=cred["SecretAccessKey"],
            aws_session_token=cred["SessionToken"],
            region_name=region,
        )
    else:
        _state["session"] = boto3.Session(region_name=region)
    _state["region"] = region
    _state["role_arn"] = role_arn


def get_client(service: str, region: str | None = None):
    sess = _state["session"] or boto3.Session()
    return sess.client(service, region_name=region or _state["region"])


def assumed_role_arn() -> str | None:
    return _state["role_arn"]
