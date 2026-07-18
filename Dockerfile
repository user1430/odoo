FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

# 系统库：编译型依赖（libsass 等）与运行时共享库
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libxml2-dev libxslt1-dev zlib1g-dev \
    libjpeg62-turbo-dev libpng-dev libfreetype6-dev libopenjp2-7-dev libtiff5-dev libwebp-dev \
    libpq-dev libldap2-dev libsasl2-dev libssl-dev libffi-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /odoo

# 仅复制依赖清单预装（源码在运行时通过卷挂载，不进镜像层，便于缓存与改码即时生效）
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && sed 's/^psycopg2==.*/psycopg2-binary==2.9.9/' /tmp/requirements.txt > /tmp/req.txt \
    && pip install --no-cache-dir -r /tmp/req.txt

EXPOSE 8069
# 源码通过卷挂载到 /odoo，入口直接运行仓库内的 odoo-bin
ENTRYPOINT ["python", "/odoo/odoo-bin"]
CMD ["-c", "/etc/odoo/odoo.conf"]
