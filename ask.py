# -*- coding: utf-8 -*-
"""命令行问答：python ask.py "问题"（冒烟测试用）"""
import sys

from kb.generate import answer

if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else input("问题：")
    r = answer(q)
    print("\n" + r["answer"])
    print(f"\n—— 出处：{[s['title'] for s in r['sources']]}（{r['elapsed']}s，"
          f"{'拒答' if r['no_hit'] else '正常回答'}）")
