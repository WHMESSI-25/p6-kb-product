# -*- coding: utf-8 -*-
"""P6 知识库 Web 服务（FastAPI）

用法：.venv/Scripts/python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
浏览器打开 http://127.0.0.1:8000
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from kb.generate import answer

app = FastAPI(title="汕大办事指南知识库")
WEB = Path(__file__).resolve().parent / "web"


class AskIn(BaseModel):
    question: str


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.post("/api/ask")
def ask(inp: AskIn):
    q = inp.question.strip()
    if not q or len(q) > 200:  # 防超长输入
        return JSONResponse({"error": "请输入 1-200 字的问题"}, status_code=400)
    try:
        return answer(q)
    except Exception as e:
        return JSONResponse({"error": f"服务内部错误：{e}"}, status_code=500)
