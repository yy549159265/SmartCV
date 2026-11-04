# SmartCV 后端 API 镜像
# 构建上下文 = smartcv-api/（docker build -f smartcv-api/Dockerfile smartcv-api）
#
# 分两层：
#   Dockerfile.base  基础镜像：系统依赖 + requirements.txt + Playwright Chromium
#                    这些很少变，只有 requirements.txt 改了才需要重建
#   Dockerfile       本文件：只 COPY 业务代码，几十秒就能构建完
#
# 首次使用前先构建一次基础镜像（在仓库根目录执行）：
#   docker build -f smartcv-api/Dockerfile.base -t smartcv-backend-base:py312 smartcv-api/
# 不传 BASE_IMAGE 就用本地这个名字；换成自己仓库的镜像也行：
#   docker build -f smartcv-api/Dockerfile \
#       --build-arg BASE_IMAGE=<你的仓库地址>/smartcv-backend-base:py312 smartcv-api/

ARG BASE_IMAGE=smartcv-backend-base:py312
FROM ${BASE_IMAGE}

WORKDIR /app

# 只拷贝业务代码；依赖和浏览器都在基础镜像里
COPY . /app/

EXPOSE 8600

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8600"]
