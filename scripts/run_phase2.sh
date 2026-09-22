#!/usr/bin/env bash
# ============================================================
# 阶段 2 一键采集（桌面桥 / 本地终端通用）
# 用法：bash scripts/run_phase2.sh              # 推荐顺序全跑
#       bash scripts/run_phase2.sh papers      # 只跑指定模块（可多个）
# 前置：照 .keys.env.example 建好 .keys.env（钥匙只存在本机）
# 每个模块跑完自动执行 manifest verify——红了立即停（set -e）。
# ============================================================
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .keys.env ]; then
  set -a; . ./.keys.env; set +a
  echo "[OK] 已载入 .keys.env（执行人：${COLLECTOR_NAME:-未填}）"
else
  echo "[提示] 未找到 .keys.env——只有免钥匙模块（institutions/clinicaltrials）能正常跑"
fi

MODULES=("$@")
if [ ${#MODULES[@]} -eq 0 ]; then
  MODULES=(institutions clinicaltrials papers shares github patentsview orcid)
fi

python3 scripts/collect_all.py plan
echo "==== 预算核对完毕，开始执行：${MODULES[*]} ===="
for m in "${MODULES[@]}"; do
  echo ""
  echo "======== 模块 $m ========"
  python3 scripts/collect_all.py "$m"
  python3 scripts/manifest.py verify
done
echo ""
echo "[完成] 阶段2 模块：${MODULES[*]}"
echo "收尾：git add -A && git commit -m \"阶段2采集：${MODULES[*]} 执行人\${COLLECTOR_NAME:-?}\"，然后把仓库发回对话"
