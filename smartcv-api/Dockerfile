# SmartCV 后端 API 镜像
# ============================================================================
# 构建上下文 = smartcv-api/（docker build -f smartcv-api/Dockerfile smartcv-api）
#
# 注意：
#   - docling 会拉 torch/transformers/opencv 等大依赖，镜像很大、构建/首次运行都慢。
#   - 模型（docling 版面/表格/OCR 全在 docling-models/，含 EasyOcr/ 中文）构建时
#     COPY 进镜像，运行时完全离线，不再联网下载。
#   - 本机已用 Python 3.14 跑通；镜像改用 3.12-slim 以保证 ML 轮子可用，需按实际微调版本。
# ============================================================================

FROM python:3.12-slim

# OpenCV 运行库 + curl（docling 用）；不装 gcc（大部分包已有轮子）。
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-liberation curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 后端依赖（用清华 PYPI 镜像，国内拉包快）
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

# Playwright 无头 Chromium（导出 PDF 用）
RUN playwright install --with-deps chromium

#ENV HF_ENDPOINT=https://hf-mirror.com \
#    HF_HUB_DISABLE_XET=1 \
#    HF_HUB_OFFLINE=1 \
#    TQDM_DISABLE=1 \
#    DOCLING_ARTIFACTS_PATH=/app/docling-models

COPY . /app/


EXPOSE 8600

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8600"]
