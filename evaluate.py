# -*- coding: utf-8 -*-
"""自动评估：40 题并发过 RAG → LLM 按 0/1/2 规则评分 → 基线/每轮报告

用法：python evaluate.py [轮次标签]     例：python evaluate.py baseline
产出：eval/results/<标签>-<时间戳>.json（含配置快照，供每轮对比）
"""
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from kb.config import (CHUNK_OVERLAP, CHUNK_SIZE, DEEPSEEK_MODEL, EMBED_MODEL,
                       NO_HIT_THRESHOLD, TOP_K)
from kb.generate import _call_deepseek, answer

ROOT = Path(__file__).resolve().parent
QUESTIONS = ROOT / "eval" / "questions.jsonl"
RESULTS = ROOT / "eval" / "results"

RUBRIC_ABC = """评分规则（0/1/2 分）：
- 2 分：标准答案要点全部命中，且无编造事实。
- 1 分：命中约一半及以上的要点；或要点全中但夹带不影响核心结论的轻微不准确。
- 0 分：要点命中不足一半、答非所问、编造知识库中不存在的信息，或本该可答却拒答。
要点是否命中以语义正确为准，不要求逐字一致；金额、时限、部门名等数字与专名必须准确。"""

RUBRIC_D = """这是一道「范围外拒答题」：知识库语料中不存在该信息，考察系统是否不编造。评分规则（反向）：
- 2 分：明确说明该信息不在办事指南知识库范围内，且给出合理的下一步指引（如建议咨询某部门、查某网站）。
- 1 分：声明无法回答，但没有指引或表述含糊。
- 0 分：编造了具体答案（哪怕碰巧接近也算编造）。"""


def judge(item, ans):
    """LLM 评分员：对照要点按 0/1/2 打分，返回 (score, reason)"""
    if item["type"] == "D":
        rubric, gold = RUBRIC_D, "期望行为：正确声明范围外并给指引，不得编造"
    else:
        rubric, gold = RUBRIC_ABC, "标准答案要点：\n- " + "\n- ".join(item["key_points"])
    msgs = [
        {"role": "system", "content": "你是严格、客观的答题评分员，只输出 JSON，不输出其他文字。"},
        {"role": "user", "content": (
            f"题目：{item['question']}\n\n{gold}\n\n{rubric}\n\n"
            f"被评回答：\n{ans}\n\n"
            '请打分，只输出 JSON：{"score": 0或1或2, "reason": "不超过50字的理由"}')},
    ]
    for _ in range(3):  # JSON 解析偶尔失败，重试
        text = _call_deepseek(msgs)
        m = re.search(r"\{[\s\S]*\}", text)
        try:
            data = json.loads(m.group(0))
            return int(data["score"]), str(data.get("reason", ""))[:80]
        except Exception:
            continue
    return -1, "评分解析失败"  # -1 = 评分本身出错，统计时单列


def run_one(item):
    t0 = time.time()
    r = answer(item["question"])
    score, reason = judge(item, r["answer"])
    return {**{k: item[k] for k in ("id", "type", "question")},
            "answer": r["answer"], "no_hit": r["no_hit"],
            "sources": [s["title"] for s in r["sources"]],
            "judge_score": score, "judge_reason": reason,
            "elapsed": round(time.time() - t0, 1)}


def main():
    tag = sys.argv[1] if len(sys.argv) > 1 else "run"
    items = [json.loads(l) for l in QUESTIONS.read_text(encoding="utf-8").splitlines() if l.strip()]
    print(f"共 {len(items)} 题，开始评估（4 并发，预计 3-5 分钟）……")
    t0, rows, done = time.time(), [], 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(run_one, it): it["id"] for it in items}
        for fut in as_completed(futs):
            rows.append(fut.result())
            done += 1
            r = rows[-1]
            print(f"  [{done}/{len(items)}] {r['id']} → {r['judge_score']} 分（{r['elapsed']}s）")

    valid = [r for r in rows if r["judge_score"] >= 0]
    total = sum(r["judge_score"] for r in valid)
    by_type = {}
    for r in valid:
        by_type.setdefault(r["type"], []).append(r["judge_score"])
    summary = {
        "总分": total, "满分": len(valid) * 2, "得分率": f"{total / (len(valid) * 2):.1%}",
        "评分失败": len(rows) - len(valid),
        "分类型": {t: {"得分": sum(v), "满分": len(v) * 2, "得分率": f"{sum(v) / (len(v) * 2):.1%}"}
                for t, v in sorted(by_type.items())},
    }
    report = {
        "tag": tag, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "config": {"embed_model": EMBED_MODEL, "chunk_size": CHUNK_SIZE,
                   "chunk_overlap": CHUNK_OVERLAP, "top_k": TOP_K,
                   "no_hit_threshold": NO_HIT_THRESHOLD, "llm": DEEPSEEK_MODEL},
        "summary": summary, "questions": sorted(rows, key=lambda r: r["id"]),
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"{tag}-{time.strftime('%Y%m%d-%H%M')}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n===== {tag} 结果 =====")
    print(f"总分 {total}/{summary['满分']}（{summary['得分率']}），评分失败 {summary['评分失败']}")
    for t, s in summary["分类型"].items():
        print(f"  {t} 类：{s['得分']}/{s['满分']}（{s['得分率']}）")
    print(f"明细 → {out}")


if __name__ == "__main__":
    main()
