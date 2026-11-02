# -*- coding: utf-8 -*-
"""P6 知识库全局配置：所有可调参数集中在这里（调优轮每轮只改一处，就改这个文件）"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# HuggingFace 缓存放 D 盘 + 大陆镜像（必须在 import transformers 前设置）
os.environ.setdefault("HF_HOME", str(ROOT / ".hf_cache"))
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
# 下载超时收紧（2026-11-02 线上踩坑）：容器里 hf 源不可达时，原默认超时会卡十几分钟，
# 收到 15 秒后快速失败，好让上层立刻切到别的加载路径
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "15")
os.environ.setdefault("HF_HUB_ETAG_TIMEOUT", "10")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

# ===== 向量模型与检索参数 =====
EMBED_MODEL = "BAAI/bge-small-zh-v1.5"          # 本地中文向量模型，约 95MB
# 可选：仓库内置的模型目录。存在则优先用（零网络，冷启动最快）；不存在则走魔搭源/HF
MODEL_DIR = ROOT / "models" / "bge-small-zh-v1.5"
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："  # bge 中文模型检索时查询侧加指令
CHUNK_SIZE = 500          # 每块字符数（调优候选变量）
CHUNK_OVERLAP = 100       # 相邻块重叠字符数（调优候选变量）
TOP_K = 8                 # 检索返回条数。轮1（2026-11-01）：5→8，针对基线 5 道检索覆盖不足丢分题
                          # 轮2（2026-11-01）：检索方式改为向量+BM25 RRF 融合（见 retrieve.py），TOP_K 保持 8
NO_HIT_THRESHOLD = 0.55   # top1 相似度低于此值视为「语料无相关内容」→ 拒答（调优候选变量）
                          # 实测：无关题 top1 约 0.44-0.49，正常题约 0.60+，0.55 居中
MIN_DOC_CHARS = 20        # 清洗后正文短于此的文档不入库（空白表格）

# ===== 存储 =====
STORE = ROOT / "kb" / "store"          # chunks.json + vectors.npy（建库产物，可重建）
EXTRACTED = ROOT / "data" / "extracted"

# ===== DeepSeek 生成端 =====
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
LLM_TIMEOUT = 60          # 单次生成超时（秒）
LLM_RETRIES = 2           # 失败重试次数

SYSTEM_PROMPT = """你是汕头大学办事指南知识库的问答助手。严格遵守：
1. 只依据【资料】中的内容回答用户问题；资料里没有的信息一律不得编造。
2. 用简体中文回答，条理清晰；涉及流程时按步骤列出。
3. 关键事实后用（资料N）标注出处编号。
4. 与问题相关的要点必须逐条列全：金额、时限、材料、审批人等细节，只要资料里有且与问题相关，都要提到。
5. 金额、数量、边界条件必须逐字照抄原文表述（例如「3000元及以上」「不超过40小时」），不得改写或自行推断边界归属。
6. 回答限定在与问题直接相关的流程上：不同流程、不同表格的资料不要互相混合，引用某流程时不要夹带其他流程的环节。
7. 如果资料不足以回答，就明确说「办事指南知识库中没有找到相关资料」，可根据资料中的线索建议咨询的部门，并提醒对方到学校信息公开网查询；绝不要靠猜。
8. 与办事咨询无关的请求（写文章、闲聊、外部资讯等），说明不在本知识库服务范围，不展开回答。"""
