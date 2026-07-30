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
## 分环境配置

| APP_ENV | 设置模块 | 说明 |
|---|---|---|
| local | `config.django_settings.local` | 允许安全开发默认值 |
| test | `config.django_settings.test` | SQLite 内存库、LocMem、日志降噪 |
| production | `config.django_settings.production` | 严格校验并 fail-fast |

公共设置集中在 `config/django_settings/base.py`，`config.settings` 根据 `APP_ENV`
加载对应环境，不复制整份配置。

production 必须提供：

- `DJANGO_SECRET_KEY`
- `DATABASE_URL`
- `REDIS_URL`
- `ALLOWED_HOSTS`
- `CSRF_TRUSTED_ORIGINS`
- `CORS_ALLOWED_ORIGINS`
