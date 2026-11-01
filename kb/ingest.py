# -*- coding: utf-8 -*-
"""建库：153 篇语料 → 去重 → 清洗 → 切块 → 向量化 → 本地存储

用法：python -m kb.ingest    （一条命令重建整个向量库）
产出：kb/store/chunks.json + kb/store/vectors.npy
"""
import json
import re
import time
import numpy as np

from .config import (CHUNK_OVERLAP, CHUNK_SIZE, EMBED_MODEL, EXTRACTED, MIN_DOC_CHARS,
                     STORE)

# PDF 提示语（HTML 正文里的下载阅读器段落，全是噪音）
BOILER = re.compile(r"如果您无法在线浏览此\s*PDF[\s\S]*?PDF\s*文件")


def load_docs():
    """读取 manifest + pdf_manifest，按 PDF 内容指纹去重，返回保留文档列表"""
    manifest = json.loads((EXTRACTED.parent / "manifest.json").read_text(encoding="utf-8"))
    pdf_manifest = json.loads((EXTRACTED.parent / "pdf_manifest.json").read_text(encoding="utf-8"))
    pdfmap = {a["id"]: a for a in pdf_manifest["articles"]}
    seen_fp, kept = set(), []
    for a in sorted(manifest["articles"], key=lambda x: x["id"]):
        pa = pdfmap.get(a["id"])
        fp = None
        if pa and pa.get("pdfs"):
            m = re.search(r"__local/[^?]+", pa["pdfs"][0]["pdfUrl"])  # URL 内含内容指纹
            fp = m.group(0) if m else None
        if fp and fp in seen_fp:
            continue  # 同一 PDF 挂多个页面，只保留一篇
        if fp:
            seen_fp.add(fp)
        kept.append(a)
    return kept, manifest


def clean_body(raw):
    """去掉「来源/标题」头和 PDF 提示语，返回正文"""
    parts = raw.split("\n\n", 1)
    body = parts[1] if len(parts) == 2 else raw
    body = BOILER.sub(" ", body)
    body = re.sub(r"[ \t\u3000]+", " ", body)
    body = re.sub(r"\n{2,}", "\n", body)
    return body.strip()


def chunk_text(text):
    """滑动窗口切块；过小的尾块并入前块"""
    if len(text) <= CHUNK_SIZE:
        return [text]
    step = CHUNK_SIZE - CHUNK_OVERLAP
    pieces = [text[i:i + CHUNK_SIZE] for i in range(0, len(text), step)]
    if len(pieces[-1]) < 50:
        pieces[-2] += pieces[-1]
        pieces.pop()
    return pieces


def build():
    t0 = time.time()
    docs, manifest = load_docs()
    chunks, skipped, dup = [], 0, len(manifest["articles"]) - len(docs)
    for a in docs:
        raw = (EXTRACTED / f"{a['id']}.txt").read_text(encoding="utf-8")
        body = clean_body(raw)
        if len(body.replace(" ", "").replace("\n", "")) < MIN_DOC_CHARS:
            skipped += 1
            continue
        for i, piece in enumerate(chunk_text(body)):
            chunks.append({
                "doc_id": a["id"], "title": a["title"], "category": a["category"],
                "url": a["url"], "chunk_no": i, "text": piece,
            })

    print(f"语料：{len(manifest['articles'])} 篇 → 去重 {dup} 篇、空壳跳过 {skipped} 篇、入库 {len(docs) - skipped} 篇")

    from sentence_transformers import SentenceTransformer
    print(f"加载向量模型 {EMBED_MODEL} ……")
    # 与 retrieve.py 同策略：魔搭容器走 ModelScope 源，本地走 HF 镜像源
    try:
        from modelscope import snapshot_download
        model = SentenceTransformer(snapshot_download(EMBED_MODEL))
    except Exception:
        model = SentenceTransformer(EMBED_MODEL)
    print(f"向量化 {len(chunks)} 块 ……")
    vecs = model.encode([c["text"] for c in chunks], batch_size=64,
                        normalize_embeddings=True, show_progress_bar=False)
    vecs = np.asarray(vecs, dtype=np.float32)

    STORE.mkdir(parents=True, exist_ok=True)
    (STORE / "chunks.json").write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    np.save(STORE / "vectors.npy", vecs)
    print(f"建库完成：{len(chunks)} 块 × {vecs.shape[1]} 维，耗时 {time.time() - t0:.0f} 秒 → {STORE}")


if __name__ == "__main__":
    build()
