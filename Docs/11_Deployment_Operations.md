# 部署与运行手册

版本：2.1 · 原始基线：2026-10-10 · 修订：2026-10-11 · 状态：当前需求与实现基线。

## 运行形态

- Node 24.21.0 多阶段构建 Vue；最终镜像使用 Python 3.13.1、Django、WhiteNoise 和 SQLite。
- 唯一运行服务 `aps`，镜像 `custom-aps:local`，Gunicorn 一个 worker、4 个线程，容器端口 8000。
- 默认仅绑定 `127.0.0.1:8000`。演示时需要局域网访问可显式修改 compose 的绑定、ALLOWED_HOSTS 和 CSRF_TRUSTED_ORIGINS。
- `/data/aps.sqlite3` 位于 `custom_aps_data` named volume；运行 UID/GID 10001。没有 Node、Redis、Celery、Nginx 或其他运行容器。
- 所有前端资源打包在镜像中，构建完成后无 CDN、外部账号或网络运行依赖。

## 配置项

以下是实现中的实际名称，替代设计阶段的占位名称。

| 名称 | 默认 / 用途 |
|---|---|
| SECRET_KEY | 必须在容器环境中提供；启动脚本拒绝空值，建议首次生成并保存在本地 `.env` |
| APS_PORT | compose 宿主端口，8000 |
| DATABASE_PATH | 容器 `/data/aps.sqlite3`；本机 `data.sqlite3` |
| DEBUG | 容器 0；本机开发 1 |
| ALLOWED_HOSTS | localhost,127.0.0.1 |
| CSRF_TRUSTED_ORIGINS | compose 默认两种本机 8000 来源；开发允许本机 5173 |
| GRAPH_NODE_BUDGET / GRAPH_EDGE_BUDGET | 20000 / 50000，资源保护，不是 BOM 层级限制 |
| 时区与锁等待 | 固定 Asia/Shanghai，UTC 存储，SQLite timeout=10 秒、IMMEDIATE 事务 |

默认只初始化 PCS（整数）、KG/L（6 位小数）及 SystemState，不初始化业务物料、BOM、销售单或场景。已有单位和数据不会被启动过程覆盖。

## 启动与停止

```sh
source scripts/activate.sh
cp .env.example .env
python -c "import secrets; from pathlib import Path; p=Path('.env'); p.write_text(p.read_text().replace('replace-with-a-generated-local-secret', secrets.token_urlsafe(48)))"
docker compose up -d --build
curl --fail http://127.0.0.1:8000/api/v1/health/ready
docker compose logs --tail 100
```

已有 `.env` 时不覆盖，后续直接运行 compose。秘密配置不进入镜像或源码。停止保留数据：

```sh
docker compose stop
docker compose start
```

入口顺序为：检查 SECRET_KEY → migrate → init_system → Gunicorn。数据库不可写或迁移失败则不启动业务服务，不自动删除文件修复。

`health/live` 测应用进程；`health/ready` 检查迁移文件与已应用记录一致、SystemState 结构版本、数据库 quick_check 和实际写权限（不改变业务值）。API 返回 request_id，响应头有 X-Request-ID；请求路径、状态和耗时写标准输出，业务日志存 AuditEvent，无操作人。

## 备份

SQLite online backup API 会取得一致性快照，包含编号序列和业务状态，不直接复制正在写入的数据库文件。

```sh
docker compose exec aps python scripts/backup_sqlite.py /data/aps.sqlite3 /data/backup-20261011.sqlite3
mkdir -p backups
docker compose cp aps:/data/backup-20261011.sqlite3 backups/backup-20261011.sqlite3
```

备份目标必须尚不存在。另行保留 `.env` 和匹配的镜像版本；SECRET_KEY 不存数据库。

## 恢复

先停止服务，再用同版本镜像运行恢复工具。原数据以 `.before-restore` 保留；该安全副本已存在时不会覆盖，须先归档。

```sh
docker compose stop aps
docker run --rm -v custom_aps_data:/data --entrypoint python custom-aps:local \
  scripts/restore_sqlite.py /data/backup-20261011.sqlite3 /data/aps.sqlite3 --service-stopped
docker compose start aps
docker compose exec aps python manage.py check_demo_integrity
```

恢复工具在覆盖前验证完整性、schema_version 和完整迁移清单；使用 UID10001 的镜像进程创建文件，清除目标旧 journal/WAL/SHM，再原子替换。恢复后：

- epoch、data_revision 取旧库与备份中的较大值再加 1；旧页面需重新加载。
- 各编号序列取较大值，避免批次号倒退复用。
- 清除幂等缓存，草稿建议标为 SUPERSEDED，需重新生成建议；正式批次与实际进度按备份恢复。
- 新增 RESTORE 审计事件，保留备份原有业务历史。
- 验证失败不覆盖当前数据库，已保存的安全副本也保留。

`check_demo_integrity` 为只读检查：DAG 无环、生产数量守恒、BOM 制造组件覆盖、开工依赖、精确进度缓存、销售覆盖与完成状态。

## 升级与故障处理

升级前保存备份和旧镜像，再构建、迁移并验证。回退需要旧镜像与匹配备份，不假定迁移可以任意逆转。不要执行 `docker compose down -v`，除非明确需要永久删除数据卷。

| 现象 | 检查 / 处理 |
|---|---|
| 数据重启丢失 | 检查是否挂载 custom_aps_data、是否误重置或删除卷 |
| SQLite 繁忙 | 保持一个 worker，排查外部写入和长事务；API 超时返回 503 |
| 写入冲突 | 刷新当前版本；同一幂等键用于同一请求，不覆盖他人更新 |
| ready 失败 | 查看权限、结构版本、库完整性和空间；禁止自动删除库 |
| API 路径错误 | 返回 JSON 404，不能回退到前端 index.html |
| 重置或恢复后旧页报错 | 刷新获取新的 epoch，不能重放旧请求 |

复验命令：`.venv/bin/python scripts/verify_container.py`。它创建并清理自己的容器和数据卷，不触碰 compose 演示数据；验证并发、首次启动、重启、镜像替换、备份恢复和无网络运行。

## 当前演示初始状态与结构升级

根目录Compose不在启动或迁移中自动加载业务种子。已授权蒜蓉酱初始导入命令为 `python manage.py load_demo_bom`，仅允许空业务库；初始化及移机复演按 [18](18_Demo_BOM.md)。当前初始备份为demo-initial-20261011-v3.sqlite3，包含0001～0005迁移结构。原始v1备份仍保留，使用旧版本代码恢复或先在副本迁移，不向当前恢复工具提交旧迁移清单。

0003/0004为取消完成量及依赖有效性迁移，不修改已有进度。升级前可先运行在线备份；已有正式计划的取消缩量只经业务动作执行，不在迁移时自动取消销售。

## 当前部署与初始化口径

根目录Compose空库仅初始化单位和系统配置；快速部署包与Railway首次空库加载v3初始演示种子，之后重启或升级保留已有数据，绝不自动重置。当前基线包含0001～0005迁移、20张确认销售和41条明细，不含中间料直销。

本地快速部署与恢复见 [deploy](../deploy/README.md)，Railway单实例与/data持久化卷见 [Railway](../deploy/railway/README.md)。升级只迁移结构和销售资格，不取消历史订单、不改现有生产进度。
