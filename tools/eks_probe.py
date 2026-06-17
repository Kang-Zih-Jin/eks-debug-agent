"""
Tier 1 開場探測：讀 EKS cluster endpoint 設定，判斷標準 CloudShell 能否下 kubectl。
判斷依據（官方）：private-only 必須在 cluster VPC 內跑 kubectl；
public endpoint 若有 publicAccessCidrs 限制，CloudShell 出口 IP 不在白名單照樣連不到。
"""
import boto3


def probe_cluster(cluster_name: str, region: str = "ap-northeast-1") -> dict:
    """
    探測叢集 endpoint 模式，回傳 kubectl 可用性判斷。
    回傳 dict：含 endpoint 模式、publicAccessCidrs、kubectl_usable、reason。
    """
    eks = boto3.client("eks", region_name=region)
    resp = eks.describe_cluster(name=cluster_name)
    req_id = resp.get("ResponseMetadata", {}).get("RequestId")
    vpc = resp["cluster"]["resourcesVpcConfig"]

    public = vpc.get("endpointPublicAccess", False)
    private = vpc.get("endpointPrivateAccess", False)
    cidrs = vpc.get("publicAccessCidrs", [])

    if public and "0.0.0.0/0" in cidrs:
        usable, reason = True, "public endpoint 無 IP 限制，標準 CloudShell 可下 kubectl"
    elif public and cidrs:
        usable, reason = "maybe", (
            f"public endpoint 限制來源 CIDR {cidrs}；"
            "須確認 CloudShell 出口 IP 在白名單內，否則會被擋"
        )
    elif private and not public:
        usable, reason = False, (
            "private-only endpoint：標準 CloudShell（非 VPC）連不到，"
            "降級為純 AWS API 模式"
        )
    else:
        usable, reason = False, "endpoint 設定無法判定，保守降級純 API"

    return {
        "cluster": cluster_name,
        "region": region,
        "endpointPublicAccess": public,
        "endpointPrivateAccess": private,
        "publicAccessCidrs": cidrs,
        "kubectl_usable": usable,
        "reason": reason,
        "request_id": req_id,
    }
