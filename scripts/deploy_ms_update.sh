#!/usr/bin/env bash
# 魔搭空间增量更新：不重新克隆（远端大文件走 LFS，本机克隆易卡），
# 直接在首次部署的本地工作目录里同步改动文件 → 提交 → 推送
# 用法：bash scripts/deploy_ms_update.sh "提交说明"
set -e

SRC="/d/projects/p6-kb-product"
DEPLOY="/d/projects/.deploy-tmp/ms-space"
MSG="${1:-部署更新}"

[ -d "$DEPLOY/.git" ] || { echo "部署目录不存在，请先运行 deploy_ms.sh 完成首次部署"; exit 1; }

echo "== 同步代码 =="
for f in config.py retrieve.py generate.py ingest.py __init__.py; do
  cp "$SRC/kb/$f" "$DEPLOY/kb/$f"
done
# 入口：本地叫 app_gradio.py，创空间约定入口文件名是 app.py
cp "$SRC/app_gradio.py" "$DEPLOY/app.py"
cp "$SRC/requirements-deploy.txt" "$DEPLOY/requirements.txt"

echo "== 同步向量库（npz 走普通存储，避免平台把 npy 强制转 LFS 后克隆拿不到）=="
mkdir -p "$DEPLOY/kb/store"
cp "$SRC/kb/store/chunks.json" "$DEPLOY/kb/store/chunks.json"
cp "$SRC/kb/store/vectors.npz" "$DEPLOY/kb/store/vectors.npz"
rm -f "$DEPLOY/kb/store/vectors.npy"

echo "== 同步内置向量模型（容器外网被封，随仓库带上最稳）=="
if [ -d "$SRC/models/bge-small-zh-v1.5" ]; then
  mkdir -p "$DEPLOY/models"
  cp -r "$SRC/models/bge-small-zh-v1.5" "$DEPLOY/models/"
else
  echo "本地无 models/ 目录，跳过（线上会退回魔搭源下载）"
fi

cd "$DEPLOY"
echo "== 提交并推送 =="
git add -A
git diff --cached --quiet && { echo "无改动"; exit 0; }
git commit -q -m "$MSG"
git push origin master 2>&1 | tail -3
echo "== 已推送，等魔搭重新构建 =="
git log --oneline -1
