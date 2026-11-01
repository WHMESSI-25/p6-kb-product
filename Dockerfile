# P6 知识库产品容器镜像（Hugging Face Spaces / 本地 Docker 均可用）
# Space 要求应用监听 7860 端口
FROM python:3.12-slim

WORKDIR /app
ENV HF_ENDPOINT=https://hf-mirror.com \
    HF_HOME=/app/.hf_cache \
    PYTHONIOENCODING=utf-8

# CPU 版 torch：Linux 默认 PyPI 源会拉 CUDA 版（2GB+），必须指定 CPU 源
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 代码与语料（向量库不入 git，容器内按管线重建，保证与语料同源）
COPY kb/ kb/
COPY web/ web/
COPY app.py ./
COPY data/extracted/ data/extracted/
COPY data/manifest.json data/pdf_manifest.json data/

# 构建期：预下载 95MB 向量模型 + 建库（415 块），启动零等待
RUN python -m kb.ingest

EXPOSE 7860
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
