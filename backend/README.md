# 后端开发

技术栈：Python 3.12、Django 5.2 LTS、Django REST Framework、Celery。

本机运行（无需 Docker，仅用于快速测试）：

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py runserver
```

质量检查：

```powershell
python -m ruff check .
python -m ruff format --check .
python -m pytest
```

未设置 `DATABASE_URL` 和 `REDIS_URL` 时，只有 `local`/`test` 环境允许使用
SQLite 与进程内缓存，便于测试。Docker Compose 始终使用 PostgreSQL 和 Redis；
非本地环境缺少数据库或密钥配置会立即启动失败。
