# -*- coding: utf-8 -*-
"""魔搭创空间入口（Gradio 版界面）

核心逻辑与本地 FastAPI 版完全同源（kb/ 四模块一行不动），
只把界面层换成创空间要求的 Gradio。
"""
import gradio as gr

from kb.generate import answer

REFUSE_HINT = ""  # 拒答文案由 kb/generate 给出，这里不额外加工


def chat_fn(message, history):
    """Gradio 对话回调：message=用户输入，history=历史消息（本版不依赖上下文）"""
    r = answer(message)
    text = r["answer"]
    if r["sources"]:
        links = "  ".join(f"[{s['title']}]({s['url']})" for s in r["sources"])
        text += f"\n\n---\n📎 **出处**：{links}"
    return text


demo = gr.ChatInterface(
    fn=chat_fn,
    title="🏫 汕大办事指南知识库",
    description="基于学校信息公开网·办事指南语料的 RAG 问答（答案带出处，知识库没有的明说，不编造）",
    examples=["勤工助学一周最多几个小时？", "生源地贷款和校园地贷款有什么区别？", "食堂几点开门？"],
    cache_examples=False,
)

if __name__ == "__main__":
    # 创空间容器里监听 7860；0.0.0.0 必须显式指定
    demo.launch(server_name="0.0.0.0", server_port=7860)
