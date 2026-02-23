FROM python:3.12-slim

WORKDIR /app

# 安装 uv (用 pip 安装，避免从 ghcr.io 拉取镜像)
RUN pip install --no-cache-dir uv -i https://mirrors.aliyun.com/pypi/simple/

# 先复制依赖文件，利用 Docker 缓存
COPY pyproject.toml uv.lock* ./

# 安装依赖
RUN uv sync --no-dev --no-install-project

# 复制源码
COPY src/ src/

# 安装项目本身
RUN uv sync --no-dev

# 持久化目录 (由 docker-compose volume 挂载)
RUN mkdir -p db reports docs

# 环境变量
ENV TZ=Asia/Shanghai
ENV PYTHONUNBUFFERED=1

CMD ["uv", "run", "pixiu-bot"]
