# -*- coding: utf-8 -*-
"""生成：检索结果拼提示词 → DeepSeek 生成答案 → 解析出处；检索为空则拒答"""
import ipaddress
import json
import os
import re
import socket
import time
import urllib.parse
import urllib.request

from . import retrieve
from .config import DEEPSEEK_MODEL, DEEPSEEK_URL, LLM_RETRIES, LLM_TIMEOUT, SYSTEM_PROMPT

REFUSE_TEXT = ("办事指南知识库中没有找到与该问题相关的资料，无法回答。"
               "建议到汕头大学信息公开网（info.stu.edu.cn）查询，"
               "或直接咨询学校相关职能部门。")

# ===== 出网守卫：https + 域名白名单 + DNS 全公网 + 禁重定向 =====
ALLOW_HOST = "api.deepseek.com"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _guard_url(url):
    p = urllib.parse.urlparse(url)
    if p.scheme != "https" or p.hostname != ALLOW_HOST or (p.port not in (None, 443)):
        raise ValueError(f"URL 未通过白名单校验: {url}")
    for info in socket.getaddrinfo(p.hostname, 443, proto=socket.IPPROTO_TCP):
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ValueError(f"DNS 解析到非公网地址 {info[4][0]}，拒绝请求")


def _call_deepseek(messages):
    """调用 DeepSeek chat 接口（Key 只从环境变量读取），带重试"""
    key = os.environ.get("LLM_API_KEY")
    if not key:
        raise RuntimeError("环境变量 LLM_API_KEY 未设置")
    body = json.dumps({
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "temperature": 0.3,       # 办事问答要稳，不要发散
        "stream": False,
    }).encode("utf-8")
    last_err = None
    for i in range(LLM_RETRIES + 1):
        try:
            _guard_url(DEEPSEEK_URL)  # 每次请求前校验（含 DNS 解析）
            req = urllib.request.Request(
                DEEPSEEK_URL, data=body,
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {key}"})
            with _OPENER.open(req, timeout=LLM_TIMEOUT) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except Exception as e:  # 网络抖动重试
            last_err = e
            if i < LLM_RETRIES:
                time.sleep(2)
    raise last_err


def _build_messages(question, hits):
    blocks = []
    for i, h in enumerate(hits, 1):
        blocks.append(f"【资料{i}】栏目：{h['category']}｜文件：{h['title']}\n{h['text']}")
    context = "\n\n".join(blocks)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"资料：\n\n{context}\n\n---\n用户问题：{question}"},
    ]


def _parse_cited(answer, hits):
    """从答案里的（资料N）提取真正被引用的资料；没标就返回全部（供界面展示）"""
    idx = {int(n) for n in re.findall(r"资料(\d+)", answer) if 1 <= int(n) <= len(hits)}
    if not idx:
        return hits
    return [h for i, h in enumerate(hits, 1) if i in idx]


def _dedupe(hits):
    """同一文档的多个块只保留得分最高的一条（hits 已按分数降序）"""
    seen, out = set(), []
    for h in hits:
        if h["doc_id"] in seen:
            continue
        seen.add(h["doc_id"])
        out.append(h)
    return out


def answer(question):
    """主入口：问题 → {answer, sources, no_hit, elapsed}
    sources: [{doc_id,title,category,url,score}]（答案实际引用的资料）
    """
    t0 = time.time()
    hits = retrieve.search(question)
    if retrieve.no_hit(hits):
        return {"answer": REFUSE_TEXT, "sources": [], "no_hit": True,
                "elapsed": round(time.time() - t0, 1)}
    text = _call_deepseek(_build_messages(question, hits))
    return {"answer": text.strip(),
            "sources": [_slim(h) for h in _dedupe(_parse_cited(text, hits))],
            "no_hit": False, "elapsed": round(time.time() - t0, 1)}


def _slim(h):
    return {k: h[k] for k in ("doc_id", "title", "category", "url", "score")}


if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else input("问题：")
    r = answer(q)
    print("\n" + r["answer"])
    print(f"\n—— 出处：{[s['title'] for s in r['sources']]}（{r['elapsed']}s，"
          f"{'拒答' if r['no_hit'] else '正常回答'}）")
