# Railway 单实例部署

从 GitHub 仓库 `zimuwong-boop/Custom_APS` 的 `main` 分支部署，根目录保留 `/`。
`railway.json` 自动选择本目录 Dockerfile，前后端在同一个服务中运行；无需上传 Release 镜像。

## 服务配置

1. 创建或选用一个 Railway 项目，以 GitHub 仓库创建服务。
2. 给该服务添加一个持久化 Volume，挂载路径必须为 `/data`。保持单实例。
3. 在服务 Variables 设置：

| 变量 | 值 |
| --- | --- |
| `SECRET_KEY` | 独立随机密钥，通过 `.venv/bin/python -c "import secrets; print(secrets.token_urlsafe(48))"` 生成；不要提交到 Git |
| `RAILWAY_RUN_UID` | `0`，使应用可写入 Railway 挂载的数据卷 |
| `TRUST_PROXY_HEADERS` | `1`，识别 Railway 转发的 HTTPS 请求 |

镜像已设定 `DEBUG=0` 和 `DATABASE_PATH=/data/aps.sqlite3`。`PORT` 使用 Railway 提供的值。
`RAILWAY_VOLUME_MOUNT_PATH` 由平台自动设置，无需手动伪造该变量。

4. 在 Settings → Networking 生成 Railway 公共域名，目标端口跟随服务 `PORT`。
   应用使用 `RAILWAY_PUBLIC_DOMAIN` 配置允许的域名及 HTTPS CSRF 来源。
   使用自定义域名时，需要相应设置 `ALLOWED_HOSTS` 和 `CSRF_TRUSTED_ORIGINS`。
5. 部署后访问 `/api/v1/health/ready` 应返回正常状态，打开首页即可操作演示。

启动脚本必须在挂载数据卷后执行；不要把数据库迁移放进 Railway 的 Pre-deploy Command。
第一次启动导入 11 个物料、5 个 BOM、20 张确认销售单和待确认排产建议；后续重启或重新部署保留数据。
默认不登录即可操作，访问同一部署地址的访客使用同一份演示数据。

## 运行与恢复

迁移、系统初始化和 Gunicorn 均由镜像启动脚本完成。健康检查路径为 `/api/v1/health/ready`。
缺少真实数据卷时启动会失败，避免以临时文件系统冒充持久化部署。

备份可通过 Railway Volume 的备份功能，或在容器中运行：

```sh
python /app/scripts/backup_sqlite.py /data/aps.sqlite3 /data/aps-backup.sqlite3
```

不要在应用正在运行时覆盖 SQLite 数据库；需要恢复时，先停止应用并保留当前数据库备份，再离线恢复。
本目录不提供公开 HTTP 重置接口。原来的本地 `deploy/reset-demo.sh` 操作的是本地 Docker 项目，不会重置 Railway。

免费账户部署应以 Railway 实际可用额度和资源权限为准；本方案只需要一个应用服务和一个持久化数据卷，不需要另建数据库服务。
如果平台拒绝当前账户构建或创建 Volume，应先确认账户可用资源，不自动改为付费方案。

依据：[Railway Dockerfile](https://docs.railway.com/builds/dockerfiles)、[持久化 Volume](https://docs.railway.com/volumes)、[健康检查](https://docs.railway.com/deployments/healthchecks)、[配置文件](https://docs.railway.com/config-as-code/reference)。
