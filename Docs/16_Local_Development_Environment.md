# 本地开发环境与依赖基线

准备日期：2026-10-10。用户已要求准备本地venv及开发依赖；本地环境准备的原始记录保留如下；业务功能已实现，最新验证见 [17](17_Implementation_Acceptance.md)，演示初始数据已按 [18](18_Demo_BOM.md) 另行授权建立。

## 安装位置

| 内容 | 位置 | 说明 |
|---|---|---|
| Python虚拟环境 | 项目根目录/.venv | 使用本机Python3.13，不向系统Python安装项目包 |
| Node/npm | 项目根目录/.tools/node | 官方Node24 LTS压缩包，校验官方SHA-256 |
| Python/npm缓存 | .tools/pip-cache、.tools/npm-cache | 本项目隔离，不写全局缓存 |
| Chromium | .tools/playwright | 开发浏览器测试，不是部署服务 |
| 前端依赖 | frontend/node_modules | 对应package-lock.json |
| Docker入口 | .tools/bin/docker | 指向已有Docker Desktop，不重新安装引擎 |
| CA证书 | .tools/cacert.pem | pip随附可信CA包，修复本机Python默认CA缺失，保持HTTPS校验 |

虚拟环境、下载工具、node_modules、报告和构建产物被.gitignore排除。锁文件、依赖清单、配置及验证测试保留在源码中。

## 依赖职责

| 类别 | 库/工具 | 用途 |
|---|---|---|
| 后端 | Django5.2 | Web框架、ORM、SQLite事务 |
| API | Django REST Framework、django-filter | 请求响应校验、REST接口及过滤 |
| 部署 | Gunicorn、WhiteNoise | 单同步worker服务和Vue静态资源 |
| 图快照 | jsonschema | 建议JSON图结构校验，业务数量/状态仍由领域服务验证 |
| Python测试 | pytest、pytest-django、pytest-cov、Hypothesis | 单元/数据库/覆盖率/随机图不变量 |
| Python质量 | Ruff、pip-tools | 规范、格式和带哈希依赖锁 |
| 前端 | Vue3、Vue Router、Pinia | 页面、路由和状态 |
| UI | Element Plus及图标库 | 表格、表单、弹窗和状态组件 |
| 依赖图 | Vue Flow及background/controls | 多父多子的图展示，不负责业务算法 |
| 前端构建 | Vite、TypeScript、vue-tsc | 开发服务器、编译、Vue类型检查 |
| 前端测试 | Vitest、Vue Test Utils、jsdom、Playwright | 组件测试和真实Chromium冒烟 |
| 前端质量 | ESLint、Vue/TypeScript规则、Prettier | 静态检查与格式 |

图遍历、精确数量及Fraction计算使用Python标准库，不添加优化求解器、NumPy、Redis或Celery。Python自带SQLite，无需额外数据库服务。

## 实际版本与验证

已核对：Python3.13.1、SQLite3.45.3、Node24.21.0、npm11.19.0；Docker客户端/引擎29.8.2、Desktop4.94.0。

| 依赖 | 锁定版本 |
|---|---|
| Django / DRF / django-filter | 5.2.18 / 3.18.3 / 26.2 |
| Gunicorn / WhiteNoise / jsonschema | 25.3.0 / 6.12.0 / 4.26.0 |
| pytest / pytest-django / pytest-cov | 9.1.1 / 4.14.0 / 7.1.0 |
| Hypothesis / Ruff / pip-tools | 6.168.5 / 0.17.0 / 7.6.2 |
| Vue / Vue Router / Pinia | 3.5.43 / 4.6.4 / 3.0.4 |
| Element Plus / Vue Flow core | 2.14.7 / 1.48.2 |
| Vite / TypeScript / vue-tsc | 8.3.4 / 5.9.3 / 3.3.13 |
| Vitest / Vue Test Utils / jsdom | 4.1.11 / 2.5.1 / 27.4.0 |
| Playwright / ESLint / Prettier | 1.64.0 / 10.12.0 / 3.9.10 |

完整间接依赖以requirements/base.txt、requirements/dev.txt和frontend/package-lock.json为准。Python版本由pip-tools解析，发行包哈希从PyPI官方版本JSON获取；安装时使用--require-hashes逐包验证。前端npm安装报告0个已知漏洞。

本次实际验证结果：

| 检查 | 结果 |
|---|---|
| Python锁与实际安装 | 30个包全部一致，运行锁与开发锁一致；pip check无冲突 |
| Python规范与格式 | Ruff检查和格式检查通过 |
| Python环境冒烟 | 4项通过，包括SQLite回滚和Django IMMEDIATE事务 |
| 前端规范、格式和类型 | ESLint、Prettier、vue-tsc通过 |
| 前端组件环境 | 2项Vitest测试通过，UI挂载和依赖图组件可加载 |
| 前端生产构建 | Vite成功，无超大分块提示；当前入口JS约64kB |
| 锁文件重建 | npm ci --offline成功，286个包安装；0个已知漏洞 |
| 真实浏览器 | Chromium156.0.8078.4，1项Playwright测试通过，无页面脚本错误 |
| 一次激活 | Python、Node、npm、Docker命令均可用 |
| Docker | 客户端和Desktop引擎版本检查通过，未运行业务容器 |
| 文档 | 462项结构、引用及数学检查通过 |

Element Plus按需引入组件，环境占位入口不全量加载UI库。npm的vue-demi安装脚本已检查并仅允许已安装版本0.14.10；可选fsevents原生安装脚本不执行，开发服务器使用可用的文件监听实现。此策略记录在package.json，重建环境保持一致。

## 使用与重建

在项目根目录：

```sh
source scripts/activate.sh
make check
make e2e
make frontend-dev
```

激活脚本启用venv、项目Node、Docker入口、CA和浏览器路径。仅激活`.venv/bin/activate`时Node/npm可能不在PATH；也可直接使用`./scripts/npm`包装命令。

重建：`./scripts/setup.sh`。Python安装requirements/dev.txt的哈希锁，前端用npm ci。运行时最小集在requirements/base.txt；开发集在requirements/dev.txt。更新输入范围后用make lock重新解析并复核，不用范围清单替代锁文件安装。

IDE设置已配置项目Python解释器、pytest、前端ESLint目录和格式化器；推荐扩展在.vscode/extensions.json。未修改个人IDE全局设置。

## 验证边界

环境测试只检查依赖导入、SQLite事务、Django的IMMEDIATE配置、UI组件挂载、图组件加载、前端构建和浏览器加载；不是09文档中的业务验收结果。

2026-10-11 更新：前端已为完整工作空间，后端有实际应用、模型、迁移及 API。Vite 的 /api 代理连接本机8000；make backend-dev 与 make frontend-dev 分别启动。表格中的4项/2项/1项是环境准备时记录，最新业务测试数量见17，不作为当前总数。

依据：[Django安装兼容性](https://docs.djangoproject.com/en/5.2/faq/install/)、[Node LTS](https://nodejs.org/en/about/previous-releases)、[Vite环境要求](https://vite.dev/guide/)。实际版本以锁文件和本节验证记录为准。

## 当前测试端口与数据隔离

普通开发：Django8000、Vite5173；Docker演示：默认8000。浏览器回归：临时后端18081、前端15173，Vite代理使用APS_API_PROXY_TARGET连接临时后端，对应CSRF来源也隔离。make e2e不复用正在运行的演示服务，不需要停掉Docker容器。场景导入和备份恢复按18文档显式执行。
