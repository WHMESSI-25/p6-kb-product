# -*- coding: utf-8 -*-
"""检索：向量 + BM25 关键词双路召回，RRF 融合排序

轮2（2026-11-01）引入混合检索：纯向量检索够不着「专名藏在低质块」的情形
（实测代理机构名单块排第 247 名），BM25 关键词路可直接命中。
展示与拒答闸门仍用向量相似度（与轮0/轮1 口径一致）。
"""
import json

import numpy as np

from .config import EMBED_MODEL, NO_HIT_THRESHOLD, QUERY_INSTRUCTION, STORE, TOP_K

_model = None
_store = None      # (chunks, vecs)
_bm25 = None       # BM25Okapi 索引
_lcut = None       # jieba.lcut

RRF_K = 60         # RRF 常数（标准值），越大排名差异越平缓
POOL = 50          # 每路取前多少名参与融合


def _lazy_init():
    global _model, _store, _bm25, _lcut
    if _store is not None:
        return
    from sentence_transformers import SentenceTransformer
    _model = SentenceTransformer(EMBED_MODEL)
    chunks = json.loads((STORE / "chunks.json").read_text(encoding="utf-8"))
    vecs = np.load(STORE / "vectors.npy")
    _store = (chunks, vecs)
    import jieba
    from rank_bm25 import BM25Okapi
    _lcut = jieba.lcut
    _bm25 = BM25Okapi([_lcut(c["text"]) for c in chunks])


def search(query, k=TOP_K):
    """混合检索，返回 [{doc_id,title,category,url,chunk_no,text,score,fused}]
    score=向量相似度（展示/闸门用），fused=RRF 融合分（排序用）"""
    _lazy_init()
    chunks, vecs = _store
    qv = _model.encode([QUERY_INSTRUCTION + query], normalize_embeddings=True)[0]
    dense = vecs @ np.asarray(qv, dtype=np.float32)
    kw = _bm25.get_scores(_lcut(query))

    fused = {}
    for rank, i in enumerate(np.argsort(-dense)[:POOL]):
        fused[int(i)] = fused.get(int(i), 0.0) + 1 / (RRF_K + rank + 1)
    for rank, i in enumerate(np.argsort(-kw)[:POOL]):
        fused[int(i)] = fused.get(int(i), 0.0) + 1 / (RRF_K + rank + 1)

    hits = []
    for i in sorted(fused, key=lambda j: -fused[j])[:k]:
        c = dict(chunks[i])
        c["score"] = float(dense[i])
        c["fused"] = round(fused[i], 4)
        hits.append(c)
    return hits


def no_hit(hits):
    """闸门：融合结果中最高的向量相似度仍低于阈值 → 视为语料无相关内容
    （取 max 是为了不误杀「BM25 捞到但向量分低」的关键词命中）"""
    return not hits or max(h["score"] for h in hits) < NO_HIT_THRESHOLD
