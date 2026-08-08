# Hub supply-chain runbook

本目录定义 Hub API 的可复现依赖、漏洞门禁和例外流程。它扫描本机临时构建镜像，不连接现有 `8100` 服务或数据库。

## 前置条件

- Docker Engine 可用；
- Python 3.12；
- `uv 0.10.8`；
- 能访问 Python 包源、Trivy 漏洞数据库和已固定的容器镜像。

## 更新生产依赖锁

修改 `pyproject.toml` 后先更新 `uv.lock`，再从 `services/hub-api` 执行：

```powershell
uv export --frozen --no-dev --extra postgres --no-emit-project `
  --no-header --format requirements.txt --output-file requirements.lock
```

只验证签入文件是否与 `uv.lock` 一致：

```powershell
python tools/supply_chain_scan.py --lock-only
```

## 执行完整门禁

从仓库根目录运行：

```powershell
python tools/supply_chain_scan.py --output-dir artifacts/supply-chain
```

脚本执行以下动作：

1. 重新导出并比较 `requirements.lock`；
2. 在固定 Python 镜像中用 `pip-audit 2.9.0` 审计 46 个生产依赖；
3. 以唯一且预先不存在的标签构建 Hub 镜像；
4. 用固定 digest 的 Trivy 扫描 OS 和 Python 包；
5. 生成并解析 CycloneDX SBOM；
6. 写出 `summary.json`、`pip-audit.json`、`trivy-vulnerabilities.json` 和 `hub-api.cdx.json`；
7. 删除它创建的精确临时镜像标签和临时镜像归档。

默认不保留镜像。只有本地排障才可使用 `--keep-image`，并必须在排障后显式清理输出中记录的唯一标签。

## 失败与处置

- `requirements_lock_drift`：按上面的命令重新导出，审查依赖变化后再提交。
- Python 依赖漏洞：优先升级直接或传递依赖；任何未例外发现都会阻断。
- 镜像 HIGH/CRITICAL：优先更新固定基础镜像、删除非运行时包或升级依赖；不得为“让 CI 变绿”批量建例外。
- wheel 缺失：评估依赖是否支持目标平台；不要删除 `--only-binary` 来绕过审查。
- 扫描器或漏洞库不可用：属于门禁失败，不等于零漏洞。

若确实没有可用修复且业务接受剩余风险，例外必须写入 `vulnerability-exceptions.json`。每项必须包含 `id`、`package`、`expires_on`、`owner` 和 `reason`；到期日必须是未来日期。到期后门禁自动失败，续期需要重新评审。

## 发布边界

本地或 CI 扫描只证明该次构建、该漏洞库快照和该目标架构。正式发布还需记录镜像仓库 digest，对每个目标平台扫描，生成签名和来源证明，并由 Kubernetes 发布预检确保 Deployment 与迁移 Job 使用同一 digest。
