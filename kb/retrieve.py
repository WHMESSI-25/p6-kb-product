# -*- coding: utf-8 -*-
"""检索：向量 + BM25 关键词双路召回，RRF 融合排序

轮2（2026-11-01）引入混合检索：纯向量检索够不着「专名藏在低质块」的情形
（实测代理机构名单块排第 247 名），BM25 关键词路可直接命中。
展示与拒答闸门仍用向量相似度（与轮0/轮1 口径一致）。
"""
import json
import time

import numpy as np

from .config import EMBED_MODEL, MODEL_DIR, NO_HIT_THRESHOLD, QUERY_INSTRUCTION, STORE, TOP_K

_model = None
_store = None      # (chunks, vecs)
_bm25 = None       # BM25Okapi 索引
_lcut = None       # jieba.lcut

RRF_K = 60         # RRF 常数（标准值），越大排名差异越平缓
POOL = 50          # 每路取前多少名参与融合


def _load_embedder():
    """向量模型加载：本地目录 → 魔搭源 → HF 镜像

    2026-11-02 线上教训：容器里只有 HF 一条路时，首次回答卡了 888 秒（下载超时）。
    现在三级降级，任一路径可用即可，且每级都有明确日志，便于看运行日志定位。
    """
    from sentence_transformers import SentenceTransformer

    t0 = time.time()
    # ① 仓库内置模型目录：零网络，最稳（魔搭容器外网基本封死，这条是主路径）
    weights = MODEL_DIR / "model.safetensors"
    if MODEL_DIR.exists() and (MODEL_DIR / "config.json").exists():
        # 防坑：若克隆时没拉 LFS，safetensors 会是几百字节的指针文件，硬加载会报错
        if weights.exists() and weights.stat().st_size > 1024 * 1024:
            m = SentenceTransformer(str(MODEL_DIR))
            print(f"[model] 来源=本地目录 {MODEL_DIR} 用时={time.time() - t0:.1f}s", flush=True)
            return m
        print(f"[model] 本地目录权重异常（{weights.stat().st_size if weights.exists() else '缺失'} 字节），"
              f"疑似 LFS 指针，跳过", flush=True)
    # ② 魔搭源：容器与 modelscope.cn 同网，正常几秒到几十秒
    try:
        from modelscope import snapshot_download
        path = snapshot_download(EMBED_MODEL)
        m = SentenceTransformer(path)
        print(f"[model] 来源=魔搭源 {path} 用时={time.time() - t0:.1f}s", flush=True)
        return m
    except Exception as e:
        print(f"[model] 魔搭源不可用，转 HF 镜像：{type(e).__name__}: {e}", flush=True)
    # ③ HF 镜像：超时已在 config 收紧，不可达会快速失败而不是卡死
    m = SentenceTransformer(EMBED_MODEL)
    print(f"[model] 来源=HF 镜像 用时={time.time() - t0:.1f}s", flush=True)
    return m


def _lazy_init():
    global _model, _store, _bm25, _lcut
    if _store is not None:
        return
    t0 = time.time()
    _model = _load_embedder()
    chunks = json.loads((STORE / "chunks.json").read_text(encoding="utf-8"))
    # 向量库三种存法，按优先级找：
    #   vectors.npy —— 本地/开发机（npy 格式）
    #   vectors.dat —— 魔搭仓库用：平台 .gitattributes 把 *.npy/*.npz 强制转 LFS，
    #                  而克隆时不拉 LFS 对象，拿到的是 133 字节指针，np.load 直接报错；
    #                  .dat 不在 LFS 规则里，会以普通文件形式下发
    #   vectors.npz —— 早期版本遗留（现已被 LFS 规则命中，仅作兜底）
    for name in ("vectors.npy", "vectors.dat", "vectors.npz"):
        p = STORE / name
        if not p.exists():
            continue
        if p.stat().st_size < 1024 * 1024:
            print(f"[store] {name} 只有 {p.stat().st_size} 字节，疑似 LFS 指针，跳过", flush=True)
            continue
        if name.endswith(".npz"):
            with np.load(p) as z:
                vecs = z["vectors"]
        else:
            vecs = np.load(p)
        print(f"[store] 向量来源 {name}，形状 {vecs.shape}", flush=True)
        break
    else:
        raise FileNotFoundError(f"{STORE} 下没有可用的向量文件（npy/dat/npz 都不存在或都是指针）")
    _store = (chunks, vecs)
    import jieba
    from rank_bm25 import BM25Okapi
    _lcut = jieba.lcut
    _bm25 = BM25Okapi([_lcut(c["text"]) for c in chunks])
    print(f"[store] {len(chunks)} 块向量就绪，初始化总用时={time.time() - t0:.1f}s", flush=True)


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
