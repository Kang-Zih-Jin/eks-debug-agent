#!/usr/bin/env bash
# =============================================================
#  READ-ONLY EKS worker node 診斷腳本  (node-diag.sh)
#  目標：定位「節點 runtime 退化」造成 pod 失敗
#        (Error / ContainerStatusUnknown / 無 log)
#  保證純唯讀：無 restart / rm / stop / drain / cordon / 寫入
#  適用：Amazon Linux 2023, containerd, kubelet
#  用法：bash node-diag.sh   或   POD_KEYWORD=xxx bash node-diag.sh
# =============================================================
set -uo pipefail

# --- 自動偵測 sudo（非 root 就加 sudo）---
if [ "$(id -u)" -ne 0 ]; then SUDO="sudo"; else SUDO=""; fi

# --- 要鑽取的故障 pod 關鍵字（可用環境變數覆蓋）---
POD_KEYWORD="${POD_KEYWORD:-chtappservice}"

# --- containerd socket / crictl endpoint ---
CRI_SOCK="unix:///run/containerd/containerd.sock"
CRICTL="$SUDO crictl --runtime-endpoint $CRI_SOCK"

sec() { echo; echo "===== $1 ====="; }

echo "################################################################"
echo "#  EKS Node 唯讀診斷報告  $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "################################################################"

# ------------------------------------------------------------
sec "1. 基本資訊 (主機 / 開機時長 / 負載)"
echo "# 看：節點開機多久、平均負載是否飆高"
hostname
uptime
echo "kernel: $(uname -r)"

# ------------------------------------------------------------
sec "2. 磁碟使用率 df -h (看 DiskPressure)"
echo "# 看：/ 與 /var/lib/containerd /var/lib/kubelet 是否接近 100%"
df -h
echo "--- 重點掛載點 ---"
df -h / /var /var/lib/containerd /var/lib/kubelet 2>/dev/null

sec "3. inode 使用率 df -i (小檔太多會耗盡 inode)"
echo "# 看：IUse% 是否接近 100%（容器層/log 太多）"
df -i

# ------------------------------------------------------------
sec "4. 記憶體 free -m / available"
echo "# 看：available 是否過低 → 記憶體壓力會驅逐/OOM"
free -m
echo "--- /proc/meminfo MemAvailable ---"
grep -E "MemTotal|MemAvailable|SwapTotal" /proc/meminfo

# ------------------------------------------------------------
sec "5. 吃資源的 process Top 10 (by %MEM)"
ps aux --sort=-%mem | head -n 11
sec "5b. 吃資源的 process Top 10 (by %CPU)"
ps aux --sort=-%cpu | head -n 11

# ------------------------------------------------------------
sec "6. kubelet 服務狀態"
echo "# 看：active(running)? 重啟次數多不多？"
$SUDO systemctl status kubelet --no-pager 2>/dev/null | head -n 20
echo "--- kubelet 近 1 小時 error/warn (PLEG/evict/unhealthy) ---"
$SUDO journalctl -u kubelet --since "1 hour ago" --no-pager 2>/dev/null \
  | grep -iE "error|fail|PLEG|unhealthy|evict|OutOfmemory" | tail -n 40

# ------------------------------------------------------------
sec "7. containerd 服務狀態"
echo "# 看：runtime 是否卡死/重啟/報錯"
$SUDO systemctl status containerd --no-pager 2>/dev/null | head -n 20
echo "--- containerd 近 1 小時 error (oom/kill/fail) ---"
$SUDO journalctl -u containerd --since "1 hour ago" --no-pager 2>/dev/null \
  | grep -iE "error|fail|oom|kill|panic" | tail -n 40

# ------------------------------------------------------------
sec "8. dmesg — OOM killer"
echo "# 看：是否有行程被 OOM 殺掉（記憶體不足）"
$SUDO dmesg -T 2>/dev/null | grep -iE "out of memory|oom-kill|killed process" | tail -n 20
echo "(以上為空 = 近期無 OOM)"

sec "8b. dmesg — 硬體 / IO / 檔案系統錯誤"
echo "# 看：hardware error/MCE/I/O error/EXT4 error → 實體機或磁碟退化"
$SUDO dmesg -T 2>/dev/null | grep -iE "hardware error|mce:|machine check|i/o error|EXT4-fs error|blk_update_request" | tail -n 20
echo "(以上為空 = 近期無硬體/IO 錯誤)"

# ------------------------------------------------------------
sec "9. crictl — 容器 / image / stats"
if command -v crictl >/dev/null 2>&1; then
  echo "--- crictl ps -a (所有容器含已退出，看 STATE/ATTEMPT) ---"
  $CRICTL ps -a 2>/dev/null | head -n 40
  echo "--- crictl images (image 是否齊全) ---"
  $CRICTL images 2>/dev/null | head -n 30
  echo "--- crictl stats (現存容器資源用量) ---"
  $CRICTL stats 2>/dev/null | head -n 30
else
  echo "crictl 未安裝，略過此段"
fi

# ------------------------------------------------------------
sec "10. 鑽取故障 pod：關鍵字 = $POD_KEYWORD"
if command -v crictl >/dev/null 2>&1; then
  echo "--- 找出該 pod 的容器 ---"
  MATCH=$($CRICTL ps -a 2>/dev/null | grep -i "$POD_KEYWORD")
  echo "${MATCH:-（找不到符合 $POD_KEYWORD 的容器，可能已被 runtime 清掉=正是 ContainerStatusUnknown 成因）}"
  echo "--- 逐個 inspect 看 exitCode / reason ---"
  CIDS=$($CRICTL ps -a 2>/dev/null | grep -i "$POD_KEYWORD" | awk '{print $1}')
  if [ -n "${CIDS:-}" ]; then
    for cid in $CIDS; do
      echo ">> container $cid"
      $CRICTL inspect "$cid" 2>/dev/null \
        | grep -iE "\"exitCode\"|\"reason\"|\"message\"|\"startedAt\"|\"finishedAt\"" | head -n 8
    done
  else
    echo "（無對應 containerID。手動備案：$CRICTL ps -a | grep <關鍵字> 取得 ID 後 $CRICTL inspect <ID>）"
  fi
else
  echo "crictl 未安裝，略過此段"
fi

# ------------------------------------------------------------
sec "11. PLEG 健康檢查"
echo "# 看：PLEG is not healthy = kubelet 與 runtime 失聯（典型 ContainerStatusUnknown 前兆）"
$SUDO journalctl -u kubelet --since "1 day ago" --no-pager 2>/dev/null \
  | grep -iE "PLEG is not healthy|skipping pod synchronization" | tail -n 15
echo "(以上為空 = 近一天 PLEG 正常)"

# ------------------------------------------------------------
sec "12. 4 天前時間關聯 (故障 pod 誕生前後的節點事件)"
FOUR_DAYS_AGO=$(date -d "4 days ago" '+%Y-%m-%d' 2>/dev/null || echo "4天前")
echo "# 鎖定 $FOUR_DAYS_AGO 附近 kubelet/containerd 的關鍵事件"
$SUDO journalctl -u kubelet -u containerd --since "${FOUR_DAYS_AGO} 00:00:00" --until "${FOUR_DAYS_AGO} 23:59:59" --no-pager 2>/dev/null \
  | grep -iE "error|shutdown|evict|restart|PLEG|oom|kill" | tail -n 40
echo "(若為空，可改用 journalctl --since '${FOUR_DAYS_AGO}' 全量查看)"

# ============================================================
sec "判讀提示"
cat <<'EOF'
┌─ 發現 ──────────────────────┬─ 對應根因 / 處置 ──────────────────────────┐
│ 磁碟 / inode 接近 100%       │ DiskPressure → kubelet 驅逐 pod。清理或擴容  │
│ free available 過低 / dmesg  │ 記憶體壓力 / OOM。看 ps top mem，調 limit    │
│   有 oom-kill               │                                              │
│ containerd journal 大量 error│ runtime 卡死/異常 → 重建節點最乾淨            │
│ kubelet PLEG is not healthy  │ kubelet↔containerd 失聯 → 正是              │
│                             │   ContainerStatusUnknown 成因。重建節點      │
│ dmesg hardware error / MCE   │ 底層實體機退化 → 對 EC2 做 stop/start        │
│   / I/O error               │   (非 reboot) 遷移到健康宿主機               │
│ crictl 找不到故障容器        │ container 已被清掉 → 真死因已遺失，靠上面     │
│                             │   時間關聯與 journal 反推                     │
└─────────────────────────────┴──────────────────────────────────────────┘

注意：ContainerStatusUnknown 報的 exit 137 是 kubelet 合成的「假值」，
      不代表 OOM。真正死因要靠 dmesg / journal / crictl inspect 佐證。
下一步：止血用 (在你的 kubectl 端) kubectl cordon <node>，
        定根因後 kubectl drain --ignore-daemonsets --delete-emptydir-data，
        讓 ASG 自動補一台乾淨節點，或 terminate 該 instance。
EOF
echo
echo "=== 診斷完成 ==="
