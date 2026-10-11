# Custom APS 快速部署

单 Docker 容器运行 Django + Vue + SQLite。内含 ARM64 和 AMD64 镜像、初始演示数据库及恢复脚本，无需安装 Python、Node.js 或下载依赖。

## 启动

安装并启动 Docker（含 Docker Compose v2），从 [GitHub Releases](https://github.com/zimuwong-boop/Custom_APS/releases/latest) 下载 `custom-aps-demo-deploy.tar.gz` 并解压。在 macOS / Linux 终端执行：

```sh
cd deploy
./start.sh
```

打开 http://127.0.0.1:8000 。脚本自动选择处理器架构、导入镜像并生成本机独立密钥。

如果 8000 端口已被占用：

```sh
APS_PORT=18082 ./start.sh
```

端口会保存到本目录的 `.env`，以后启动和恢复沿用该设置。默认仅供本机访问。

## 初始状态

- 11 个物料：3 个成品、2 个半成品、6 个原料。
- 5 个有效 BOM，包含共享蒜蓉酱半成品和不同包装规格。
- 20 张已确认销售单、41 条销售明细，已生成待确认排产建议。
- 没有正式生产单，可以从调整建议、拆单合并和确认排产开始演示。

只有首次启动时导入初始数据；重启保留操作结果。默认使用独立项目 `custom-aps-demo` 和数据卷 `custom-aps-demo_demo_data`，不会覆盖原项目 `custom_aps` 的数据库。

## 停止与恢复

```sh
./stop.sh
./start.sh
# 清除本部署的演示操作，恢复初始数据：
./reset-demo.sh --yes
```

恢复前自动停止容器，并在数据卷 `/data/backups/` 留存带时间戳的旧数据库；恢复后重新生成排产建议、校验数据并启动服务。数据版本和编号序列继续递增，避免旧请求或批次编号冲突，因此恢复后的建议编号可能与首次启动不同。

查看运行日志：

```sh
docker compose --project-name custom-aps-demo logs --tail 100 aps
```

## 文件说明

| 文件 | 用途 |
| --- | --- |
| `compose.yaml` | 单实例部署和独立数据卷 |
| `images/*.tar.gz` | 两种架构的可直接导入镜像 |
| `demo-initial.sqlite3` | 初始演示数据库 |
| `start.sh` / `stop.sh` | 启动与停止 |
| `reset-demo.sh` | 恢复初始演示状态 |
| `source.tar.gz` / `build-image.sh` | 构建源码备用包；重新构建需要联网 |
| `SHA256SUMS` | 文件完整性校验 |
| `verification.json` | 实际部署验证结果 |

源码仓库包含部署脚本和初始数据库；镜像及完整部署包通过 GitHub Releases 提供下载。若直接克隆仓库，先执行 `./build-image.sh` 联网构建镜像，再执行 `./start.sh`。克隆源码时缺少镜像属于正常情况，`SHA256SUMS` 的完整校验适用于下载后的部署包。

本目录应整体复制，不要只复制镜像。也可解压 `custom-aps-demo-deploy.tar.gz` 后进入其中的 `deploy` 目录启动。镜像和源码不包含原项目 `.env` 或当前操作数据。

校验文件：Linux 使用 `sha256sum -c SHA256SUMS`；macOS 使用 `shasum -a 256 -c SHA256SUMS`。

多套演示可在不同目录部署，并在每次操作时设置不同的 `APS_PROJECT_NAME` 与端口；项目名必须一致，才能操作对应实例。

验证情况：ARM64 已通过首次启动、进度保留和恢复测试。AMD64 已构建并验证镜像导入；本机跨架构运行检查未完成，详见 `verification.json`。
