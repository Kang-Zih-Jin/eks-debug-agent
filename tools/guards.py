"""
防護骨架：唯讀動詞白名單 + 證據帳本 + 確定性 validator。
方法論見 .kiro/skills/read-only-debug-agent/SKILL.md
"""
import re

# ---- AWS API 唯讀動詞白名單 ----
AWS_READ_PREFIXES = (
    "Describe", "Get", "List", "Search", "BatchGet", "Lookup", "Scan",
)
# 明確擋下的寫入動詞（雙保險，命中即拒）
AWS_WRITE_MARKERS = (
    "Create", "Put", "Update", "Delete", "Modify", "Attach", "Detach",
    "Run", "Start", "Stop", "Terminate", "Reboot", "Associate",
    "Authorize", "Revoke", "Remove", "Add", "Set", "Enable", "Disable",
)

# ---- kubectl 唯讀動詞白名單 ----
KUBECTL_READ_VERBS = {
    "get", "describe", "logs", "top", "events",
    "explain", "api-resources", "version", "cluster-info",
}
KUBECTL_BLOCKED_VERBS = {
    "apply", "delete", "edit", "patch", "scale", "rollout",
    "cordon", "drain", "label", "annotate", "create", "replace",
    "exec", "port-forward", "cp", "attach", "run", "expose", "set",
}
# secrets 直接禁查（避免明文外洩）
KUBECTL_BLOCKED_RESOURCES = {"secret", "secrets"}


def assert_aws_readonly(action: str) -> None:
    """AWS API action 唯讀檢查；不合白名單直接 raise，呼叫端不會送出 API。"""
    if not action:
        raise PermissionError("REJECTED: 空的 action")
    # 先擋明確寫入字樣
    for w in AWS_WRITE_MARKERS:
        if action.startswith(w):
            raise PermissionError(f"REJECTED: 寫入動詞 '{action}' 被唯讀白名單擋下")
    # 再要求必須命中唯讀前綴
    if not action.startswith(AWS_READ_PREFIXES):
        raise PermissionError(f"REJECTED: '{action}' 不在唯讀動詞白名單")


def assert_kubectl_readonly(args: list[str]) -> None:
    """kubectl 參數唯讀檢查。"""
    if not args:
        raise PermissionError("REJECTED: 空的 kubectl 參數")
    verb = args[0].lower()
    if verb in KUBECTL_BLOCKED_VERBS:
        raise PermissionError(f"REJECTED: kubectl '{verb}' 為寫入/側信道動詞，禁止")
    if verb not in KUBECTL_READ_VERBS:
        raise PermissionError(f"REJECTED: kubectl '{verb}' 不在唯讀白名單")
    # 擋 secrets
    for a in args:
        if a.lower().split("/")[0] in KUBECTL_BLOCKED_RESOURCES:
            raise PermissionError("REJECTED: 禁止讀取 secrets（防明文外洩）")


class EvidenceLedger:
    """證據帳本：累積帶真實 RequestId 的查詢結果，回答引用 [E#]。"""

    def __init__(self):
        self._entries: list[dict] = []

    def record(self, source: str, request_id: str | None, summary: str) -> str:
        idx = len(self._entries) + 1
        tag = f"E{idx}"
        self._entries.append({
            "tag": tag,
            "source": source,
            "request_id": request_id or "N/A",
            "summary": summary,
        })
        return tag

    def keys(self) -> set[str]:
        return {e["tag"] for e in self._entries}

    def dump(self) -> list[dict]:
        return list(self._entries)


def validate_citations(answer: str, ledger: EvidenceLedger) -> list[str]:
    """確定性 validator：抽出答案裡的 [E#]，回傳帳本中不存在的（幻覺）引用。"""
    cited = set(re.findall(r"\[(E\d+)\]", answer))
    return sorted(cited - ledger.keys())
