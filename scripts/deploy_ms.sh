#!/usr/bin/env bash
# 魔搭创空间部署脚本：克隆 → 组装 → 提交 → 推送
# 用法：MS_TOKEN=<访问令牌> bash scripts/deploy_ms.sh
# 令牌只从环境变量读，不写入本文件（用完可吊销）
set -e

MS_TOKEN="${MS_TOKEN:?请通过环境变量 MS_TOKEN 传入访问令牌}"
USER="WHMESSI"
SPACE="p6-kb-product"
SRC="/d/projects/p6-kb-product"
DEPLOY="/d/projects/.deploy-tmp/ms-space"

rm -rf "$DEPLOY"
mkdir -p "$(dirname "$DEPLOY")"

echo "== 1/4 克隆空间仓库 =="
git clone -q "https://${USER}:${MS_TOKEN}@www.modelscope.cn/studios/${USER}/${SPACE}.git" "$DEPLOY"
cd "$DEPLOY"

echo "== 2/4 装入部署文件 =="
# 创空间入口约定文件名 app.py（Gradio 应用）
cp "$SRC/app_gradio.py" app.py
cp -r "$SRC/kb" kb
rm -rf kb/__pycache__

# requirements：创空间是 Gradio 运行环境（自带 gradio），不装 fastapi/uvicorn
cat > requirements.txt <<'EOF'
sentence-transformers>=3.0
jieba>=0.42
rank_bm25>=0.2.2
numpy
EOF

# 空间首页说明（不带 HF 式 frontmatter，部署类型由创空间配置决定）
cat > README.md <<'EOF'
# 批六 · 汕大办事指南知识库

基于汕头大学信息公开网「办事指南」153 篇语料的 RAG 问答应用。
答案带原文出处，知识库没有的内容明确拒答不编造。

- 核心架构：bge-small-zh 向量 + BM25 关键词双路检索（RRF 融合）→ DeepSeek 生成
- 评估：40 题评估集，三轮调优 86.2% → 91.2%（明细在 GitHub 仓库 p6-kb-product）
EOF

echo "== 3/4 提交 =="
git add -A
git commit -q -m "部署：汕大办事指南知识库（Gradio 界面 + 向量/BM25 混合检索 + DeepSeek 生成）"

echo "== 4/4 推送（master 分支）=="
git branch -M master 2>/dev/null || true
git push origin master 2>&1 | tail -3

echo "== 完成。仓库内容： =="
ls
