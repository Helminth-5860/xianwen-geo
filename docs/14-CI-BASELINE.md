# XW-0003 持续集成基线

## 目标

CI 与本地脚本执行同一组质量门禁，任何门禁失败都会阻断合并。工作流仅验证代码，
不启动 Compose 服务、不连接生产环境、不发布镜像或部署。

## 固定工具链

- Python：3.12
- Node.js：24.18.0（唯一版本来源：`frontend/.nvmrc`）
- actionlint：`rhysd/actionlint:1.7.12`
- Gitleaks CLI：`zricethezav/gitleaks:v8.30.1`

Python 开发依赖固定在 `backend/requirements-dev.txt`，不会进入运行时依赖文件。
GitHub Actions 均固定到已核验发布版本的完整提交 SHA。

## CI 触发与并发

`.github/workflows/ci.yml` 在以下情况运行：

- 创建或更新目标为 `develop` 的 Pull Request
- 推送到 `develop`
- 手工触发 `workflow_dispatch`

同一工作流、同一 Git ref 仅保留最新运行。全局权限为只读 `contents: read`。
Security Job 额外使用最小 `pull-requests: read`，仅供 Gitleaks Action 在 PR 事件中读取
提交列表；评论和结果构件均禁用，不授予任何写权限。
四个独立任务并行执行，均无 `continue-on-error`：

1. backend：Ruff、mypy、Django check、迁移漂移、Pytest、OpenAPI 3.1、pip-audit
2. frontend：ESLint、Prettier、TypeScript、Vitest、production build、npm audit
3. security：Git 清洁规则、Gitleaks Action、固定 CLI 完整历史扫描、actionlint
4. docker：Compose 配置解析，并构建 api、celery、frontend

## 本地复现

PowerShell：

```powershell
.\scripts\check.ps1 all
.\scripts\check.ps1 backend
.\scripts\check.ps1 frontend
.\scripts\check.ps1 security
.\scripts\check.ps1 docker
```

Linux/macOS：

```bash
./scripts/check.sh all
./scripts/check.sh backend
./scripts/check.sh frontend
./scripts/check.sh security
./scripts/check.sh docker
```

也可分别运行 `git`、`actionlint` 或 `gitleaks` 模式。脚本不安装依赖：

- 后端先创建 Python 3.12 虚拟环境并安装 `backend/requirements-dev.txt`
- 前端使用 `frontend/.nvmrc` 指定的 Node.js，并执行 `npm ci`
- security 与 docker 模式需要 Docker

## Docker 与敏感信息边界

Docker 门禁使用临时空 env 文件和仅供 CI 解析/构建的占位值，不读取仓库本地
`.env`，不启动服务、不连接数据库或 Redis、不推送镜像。占位值不是生产凭证。

Gitleaks 扫描完整 Git 历史并启用脱敏输出；日志和构件不得保存扫描报告或秘密值。
Git 清洁门禁拒绝跟踪 `.env`、私钥、证书、SQLite、patch 和 probe 临时文件，
但允许模板 `.env.example`。

## 缓存

GitHub Actions 仅缓存可重建的 pip 与 npm 下载内容，缓存键由对应依赖文件生成。
不缓存虚拟环境、`node_modules`、构建产物、扫描结果、环境变量或凭证。

## 远程验收

本地配置和检查完成后，仍需由 GitHub 托管 runner 实际执行一次工作流，才能确认
远程 Actions 环境、缓存与 Gitleaks Action 均正常。

## 平台迁移与 Action 升级

检查逻辑属于 `scripts/check.ps1` 和 `scripts/check.sh`。若最终改用 GitLab CI、
Gitee CI 或其他平台，只替换流水线入口，并继续调用这些脚本，不在平台配置中复制
检查逻辑。

升级 GitHub Action 时：

1. 从 Action 官方仓库选择明确的 release。
2. 核对该 release tag 对应的完整 40 字符 commit SHA。
3. 更新 workflow 中的 SHA 和旁边版本注释。
4. 运行 CI 结构回归测试与固定版本 actionlint。
5. 审查 Action 的权限、输入和供应链变更后再提交。

## 分支保护与故障复现

建立远程仓库后，应将 `Backend`、`Frontend`、`Security` 和 `Docker Compose`
四个 Job 配置为 `develop` 分支的 Required Checks，并禁止失败时合并。
当前仓库没有 remote，因此真实 Pull Request 工作流仍待验收。

门禁失败时先在本地运行对应模式，例如 `check.ps1 backend` 或
`check.sh frontend`；安全与 Docker 问题分别用 `security`、`docker` 模式复现。
脚本会保留首个失败命令的非零退出码，不会自动修复依赖或隐藏漏洞。
