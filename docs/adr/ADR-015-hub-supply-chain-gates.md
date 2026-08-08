# ADR-015：Hub 可复现构建与供应链门禁

- 状态：Accepted（本地门禁已验证，制品仓库与生产发布未验收）
- 日期：2026-08-08

## 背景

原 Hub 镜像使用浮动的 `python:3.12-slim`，只复制 `pyproject.toml` 后执行 `pip install ".[postgres]"`。即使 `uv.lock` 未变化，后续构建仍可能解析出不同依赖；镜像也没有依赖审计、OS/语言包漏洞门禁或 SBOM。

首次用固定 Debian slim digest 扫描时，Python 依赖没有发现漏洞，但基础层有 4 个 CRITICAL 和 19 个 HIGH，且当时没有修复版本。将这些项目批量加入例外无法降低风险，因此改用经过同一规则验证的 Alpine 基础层。

## 决策

1. `uv.lock` 是 Python 依赖解析的唯一权威源。生产依赖导出到 `requirements.lock`，必须是精确版本和哈希；CI 重新导出并执行字节级漂移检查。
2. Dockerfile 使用 `python:3.12-alpine` 的明确多架构 digest，只允许 `--require-hashes --only-binary=:all:` 安装。缺少受支持 wheel 时构建失败，不在生产镜像构建中隐式编译源码。
3. 安装完成后从最终镜像移除 `pip`，运行时继续使用 UID/GID 10001。应用源码通过只读的 `/app/src` 加载，不依赖把项目再次构建为未锁定 wheel。
4. 依赖审计固定使用 `pip-audit 2.9.0`；镜像扫描和 CycloneDX SBOM 固定使用 Trivy 0.66.0 的 digest。Python 依赖任一未例外漏洞阻断；镜像任一未例外 HIGH/CRITICAL 阻断。
5. 例外只允许写入 `deploy/supply-chain/vulnerability-exceptions.json`，且必须精确到漏洞 ID 和包名，并包含负责人、理由和到期日。空字段、重复项和过期项在扫描前阻断；初始例外表为空。
6. GitHub Actions 每次 push/PR 执行同一脚本，并保留机器可读的依赖报告、Trivy 报告、CycloneDX SBOM 和摘要 30 天。报告是构建产物，不提交仓库。

## 后果与边界

Alpine 的 musl ABI 需要容器 smoke，不能只以镜像构建成功作为兼容性证据。基础镜像、`uv`、`pip-audit` 或 Trivy 升级都必须作为显式变更重新扫描。

当前本地 amd64 镜像门禁和隔离 Compose 已通过，但 GitHub 托管 Runner 尚未实跑；也未完成制品仓库推送、签名、构建来源证明、各目标架构逐一扫描或 Kubernetes 准入校验。这些仍是生产发布前的退出门。
