"""
Tier 2：kubectl 唯讀工具。僅在 probe_cluster 判定 kubectl_usable 後才有意義。
工具自身會：①確認 kubeconfig 已產生 ②動詞白名單檢查 ③連不到回 NO_DATA（不瞎試）。
"""
import shutil
import subprocess

from .guards import assert_kubectl_readonly
from .session import assumed_role_arn

_KUBECONFIG_READY = {"ok": False, "cluster": None}


def setup_kubeconfig(cluster_name: str, region: str = "ap-northeast-1") -> dict:
    """產生 kubeconfig（aws eks update-kubeconfig）。探測判定可用後才呼叫。
    若有設唯讀 role（EKS_DEBUG_ROLE_ARN），kubeconfig 也綁該 role 取 token。"""
    if shutil.which("kubectl") is None:
        return {"status": "NO_DATA", "reason": "環境未安裝 kubectl"}
    cmd = ["aws", "eks", "update-kubeconfig",
           "--name", cluster_name, "--region", region]
    role = assumed_role_arn()
    if role:
        cmd += ["--role-arn", role]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=60)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        return {"status": "NO_DATA", "reason": f"update-kubeconfig 失敗: {e}"}
    _KUBECONFIG_READY.update(ok=True, cluster=cluster_name)
    return {"status": "OK", "cluster": cluster_name}


def kubectl_read(args: list[str]) -> dict:
    """
    執行唯讀 kubectl 指令。args 例：['get','pods','-n','default']、
    ['logs','my-pod','--previous','-n','default']、['describe','node','ip-x']。
    """
    if not _KUBECONFIG_READY["ok"]:
        return {"status": "NO_DATA",
                "reason": "kubeconfig 未就緒；請先確認探測判定 kubectl_usable 並 setup_kubeconfig"}
    try:
        assert_kubectl_readonly(args)
    except PermissionError as e:
        return {"status": "REJECTED", "reason": str(e)}

    try:
        proc = subprocess.run(
            ["kubectl", *args],
            capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        return {"status": "NO_DATA", "reason": "kubectl 逾時（endpoint 可能連不到）"}

    if proc.returncode != 0:
        return {"status": "NO_DATA", "reason": proc.stderr.strip() or "kubectl 非零退出"}
    return {"status": "OK", "stdout": proc.stdout}
