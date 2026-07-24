FROM public.ecr.aws/docker/library/python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN useradd -r -u 1001 appuser

COPY requirements.txt .
RUN python -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple \
    && python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 120 --retries 10

COPY . .

RUN mkdir -p /app/data /app/assets /app/output \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3000/healthz', timeout=3)"

CMD ["python", "main.py"]
