FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TRICLOUD_DATA=/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# glibc 默认每线程一个 malloc arena，线程池多时内存碎片大；限制为 2 个（放在 pip 之后，不破坏依赖层缓存）
ENV MALLOC_ARENA_MAX=2
COPY app ./app
COPY web ./web
COPY entrypoint.sh /entrypoint.sh
RUN useradd -u 10001 -m tricloud && chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
