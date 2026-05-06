# 用 Python 3.12 官方镜像
FROM python:3.12-slim

WORKDIR /app

# 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 代码和后台页面
COPY gateway.py .
COPY shenyu_gateway ./shenyu_gateway
COPY debug.html .

# 端口
EXPOSE 8000

# 启动（不用 reload，生产环境）
CMD ["uvicorn", "gateway:app", "--host", "0.0.0.0", "--port", "8000"]
