# SkillHub 与 Agent 交流平台实施进度

> 更新：2026-08-09
> 口径：只有当前工作区或真实运行证据可以证明的内容才标为完成。

本轮本地端到端验收（2026-08-09）：Docker Desktop 已运行固定版本 SkillHub `v0.2.16`、AgentTeams `v1.2.2` 与 WorkBuddy Hub；Hub smoke 返回 `skillhub=connected`、`agentteams=connected`。真实 Matrix 协作任务由 `workbuddy-leader` 回复完整任务 ID 与 `LOCAL E2E OK`，后续消息与重复取消均通过。新增轻量 Agent 任务广场：Agent 注册、公开任务检索、揭榜、提交、验收和事件链已通过真实容器 smoke，MCP `task.search` 同步通过。浏览器实测 `/skills/` 显示“SkillHub 已连接”，`/collaboration/` 显示“AgentTeams 已连接”和 `1 / 1 个 Team 可投递`，两页无控制台 warning/error。Hub 完整测试从仓库根目录执行为 **90 passed**。

本轮回归（2026-08-08）：在 `services/hub-api` 执行 `uv run pytest`，结果为 **89 passed**（1 个 Starlette/httpx 弃用警告）；`contracts/mcp/hub-tools.json`、协作事件 Schema、`contracts/openapi/hub-api.openapi.json`、供应链工作流/例外/摘要均可解析，OpenAPI 已包含 MCP、版本、报告、评分、回滚路径且不公开 `/metrics`，`git diff --check` 通过；Git 文件列表 146 个文本文件和全工作区 209 个文本文件的 Secret 扫描均为 0 个发现。

| ID | 状态 | 当前证据 | 下一退出门 |
|---|---|---|---|
| ARCH-01 | 完成 | `docs/spikes/ARCH-01-WorkBuddy可编程接入验证.md`；ADR-006 采用主动 Connector | 获取厂商 headless/API 证据时重新评审 |
| INFRA-01 | 部分 | Hub + PostgreSQL Compose、迁移、健康与烟测通过 | 部署固定版本 SkillHub，验证 namespace/search/upload/download/audit |
| INFRA-02 | 部分 | 已按固定 commit 核验 Controller/Matrix 源码并完成本地契约测试；新增 `deploy/agentteams-poc/agentteams-preflight.ps1`，可检查源码 pin、官方 Helm chart、工具链、隔离 Namespace、HTTPS 端点和密钥占位；本机实跑明确缺少 `helm`、真实端点和测试密钥，未启动完整上游栈 | 在隔离 Kubernetes/installer 目标补齐 LLM Key、Matrix Admin、Controller/Matrix URL，完成 Matrix/Worker/文件烟测 |
| IAM-01 | 部分 | Hub 已完成 OIDC Discovery/JWKS `RS256` 验签、`sub` 身份、直接部门 Claim + group 前缀映射；伪造 actor、错误 Token 和跨部门访问有拒绝测试；ADR-009 | 选定真实 IdP/Claim，验证调岗撤权时限并完成 SkillHub/AgentTeams Namespace 同步 |
| CONTRACT-01 | 完成 | `contracts/openapi/hub-api.openapi.json` | 上游接入后持续运行契约测试 |
| CONTRACT-02 | 部分 | `contracts/mcp/hub-tools.json` 已包含 `registry.*` 与 `collab.*` 工具、幂等键要求和协作事件 Schema；Hub 已提供 `POST /api/v1/mcp` 的 JSON-RPC `initialize`/`tools/list`/`tools/call`，并通过测试复用 REST 授权、审计和适配器 | 真实 Matrix/SkillHub 验证后冻结首个稳定版本，并补齐 MCP 客户端互操作测试 |
| DATA-01 | 完成 | 可重复导入 4 案例；SQLite/PostgreSQL 与 `0001 -> 0005` 迁移测试通过；预览幂等键、发布结果和扫描规则版本列可回放 | 生产迁移前做中文样例 HTTP/MIME 回归 |
| API-01 | 部分 | 案例 + Skill 搜索投影、统一详情、安装计划和案例治理 REST（版本更新/报告/评分/回滚）已实现 | 真实 OIDC/SkillHub 下验证跨部门 0 越权 |
| SEC-01 | 部分 | 发布预览已有 Secret/路径/Hash/过期/审计、预览键和发布结果幂等；新增版本化 Manifest 扫描，阻断路径/符号链接/MIME 逃逸并标记许可证、依赖、脚本、二进制、宏；协作产物已有大小、MIME、SHA-256、Zip 路径/符号链接/展开量校验 | 接入真实上传包，完成实际 Zip 内容/MIME、许可证、依赖和脚本扫描与规则签名 |
| SKILL-01 | 部分 | 已按固定 commit 核验 ClawHub 搜索/详情/resolve/download；安装计划固定真实 resolved version；当 SkillHub detail 不提供合法 SHA-256 时，Hub 通过受限流式下载计算并返回服务端包哈希（`workbuddy-smoke@0.1.0` 真实返回 `bf153cad...cbb85`，与实际下载字节一致）；Trusted Grant 仍为扩展点 | SkillHub 服务端 Grant 扩展、真实组织权限/撤权和生产包扫描烟测 |
| TEAM-01 | 部分 | 已拆分真实 Controller Team client 与 Matrix client；投递、消息、取消、等待/游标、`input_required` 人工介入、明文产物、allowlist 鉴权下载、完整性校验、写操作幂等和审计已实现；新增 [AgentTeams-PoC 前置审计](AgentTeams-PoC前置审计.md) 固化官方 Helm/installer 的部署前检查；API 回归覆盖重复消息/取消不会重复发送 Matrix 事件 | 真实 Team Admin token、房间权限和文件烟测；E2EE 另行评审与实现 |
| AGENT-01 | MVP 完成 | 轻量 Agent 注册、能力/Skill 声明、公开任务发布/检索、单 Agent 揭榜、提交、发布者验收、任务事件和 Agent Token 已实现；REST、MCP、SQLite/PostgreSQL 迁移和真实容器 smoke 通过 | 接入真实外部 Agent、任务执行 Worker 和 SkillHub Agent 发布 Grant |
| WEB-01 | PoC 完成 | `/skills/` 可查询并显示真实不可用状态、生成安装计划；新增 `auth.js`，远程页面只使用运行时 Bearer 注入，本地才允许 actor header | 组织 SSO 注入和真实 SkillHub 浏览器验收 |
| WEB-02 | PoC 完成 | `/collaboration/` 只展示当前 Matrix 身份可投递 Team，创建/刷新/请求取消走真实 Hub 契约；`input_required` 时显示最新事件提示并可发送人工回复；消息和取消请求携带幂等键；浏览器 stub 回归确认面板、回复提交和无控制台错误；新增统一登录态边界，远程无 token 时不发送伪造 actor | 组织 SSO 注入和至少两个异构 Agent 任务演练 |
| OPS-01 | 部分 | `.env` 排除、旧部署脚本已改为读取 `WORKBUDDY_DEPLOY_*` 环境变量/SSH Agent，不再硬编码服务器凭据；新增 `tools/secret_scan.py`、`ADR-011` 和 GitHub Actions secret-scan 工作流；Git 文件列表扫描 138 个文本文件、全工作区 walk 扫描 196 个文本文件均为 0 个发现，临时 API_KEY fixture 可被阻断且不泄露值 | 轮换历史凭据、接入组织 Secret Manager，完成历史文件/服务器副本审计 |
| OPS-02 | 部分 | 新增 `deploy/compose-poc/backup.py`、`restore_drill.py` 和恢复 Runbook；隔离 Compose 实测生成 PostgreSQL custom-format 备份及 SHA-256/迁移/7 表行数清单，恢复到随机临时库后用独立 Hub 容器完成 `/ready`、4 案例、兼容标题和 18 个 MCP 工具 smoke，临时库、容器、网络和 volume 已清理；篡改备份拒绝测试通过 | 在生产同构环境配置加密异地存储、保留期、定时任务和告警，并按冻结 RPO/RTO 完成季度恢复演练 |
| OPS-03 | 部分 | Hub 已增加 `X-Request-Id`、低基数 Prometheus 指标和脱敏 JSON 日志；固定 digest 的 Prometheus PoC、3 条初始规则及隔离采集通过；受控 W3C Trace 覆盖入站父子关系、`X-Trace-Id`/日志关联、默认上游 `httpx` 传播、异常消息不导出和 OTLP protobuf；固定 digest Collector 配置通过官方 `validate`，三容器 smoke 实际接收 10 个 Span；未配置 OTLP 时不导出；ADR-013 | 在生产同构环境接入 Collector 持久后端/日志/Alertmanager，验证跨 SkillHub/Matrix/IdP Trace，压测校准采样和阈值、冻结容量与 SLO并执行负责人真实触达 |
| OPS-04 | 部分 | 新增 Hub Kubernetes Kustomize 基础模板与 ADR-014：独立 Namespace/ServiceAccount、2 副本、零不可用滚动、探针/资源/PDB、TLS Ingress、默认拒绝 NetworkPolicy、外部 Secret、单独迁移 Job和 context/占位符/迁移/rollout 发布门禁；10 个资源通过 Kubernetes 1.30 schema，生产预检按预期拒绝 4 类占位符；镜像改为 UID 10001 后 Compose 完整 smoke 通过 | 替换真实 digest/域名/Grant 路径，接入组织 Secret Manager/证书/CNI，在目标集群执行迁移、双副本滚动、NetworkPolicy、节点故障和回滚验收 |
| OPS-05 | 部分 | 新增带本机/只读/并发/请求量/响应大小护栏的负载探针；隔离单副本 Hub + PostgreSQL 对统一目录执行 5,000 次查询、20 并发、100 预热，5,000 次均为 200，吞吐 290.701 req/s，p50/p95/p99 为 66.219/98.833/148.435 ms，通过 0 错误和 p95 小于 1 秒的试点阈值；证据单独留档 | 在生产同构双副本环境覆盖 Ingress/TLS/OIDC、真实上游、长轮询/文件/故障，采集峰值资源与数据库指标后冻结 SLO、requests/limits、HPA 和容量余量 |
| OPS-06 | 部分 | `uv.lock` 可重复导出带哈希的生产锁；固定 Alpine/Trivy digest 和 `pip-audit 2.9.0` 的本地门禁已实跑，46 个依赖 0 漏洞、最终镜像 0 漏洞、CycloneDX 1.6 含 100 个组件、例外 0；隔离 Compose 验证 UID 10001、无运行时 pip、迁移和完整 smoke；ADR-015 | 在 GitHub Runner 实跑工作流，推送并逐架构扫描仓库镜像，补齐签名、来源证明和生产 Kubernetes 准入策略 |

## 当前验证

- Hub API：`pytest` 90 项通过；覆盖迁移、OIDC RSA/JWKS 验签与权限隔离、预览/发布幂等、Manifest 安全扫描、版本/报告/评分/回滚治理、固定上游 SkillHub 路由、AgentTeams Controller/Matrix 路由、轻量 Agent 注册和任务广场闭环、状态边界、有界等待、`input_required` 消息介入、消息/取消幂等、MCP JSON-RPC 工具调用、恢复清单篡改检测、产物下载和完整性校验，以及请求 ID、低基数指标、日志脱敏、监控配置、受控 Trace、Kubernetes 发布约束、容量探针、生产锁漂移、供应链策略和容器浅路径配置。
- Compose：PostgreSQL 和 Hub API 健康；旧 volume 收编为 `0001_initial`；7 张业务/版本表存在。重启后的本地 `127.0.0.1:8100` 部署 smoke 通过：`/health` 为 200，4 个案例可读，`case-capacity` 标题为 `项目资料交付检查`，未配置 SkillHub/AgentTeams 时 Skill 查询和协作 Team 查询分别返回预期 503。
- MCP 运行态：重启后的本地 `127.0.0.1:8100` 通过 `deploy/compose-poc/smoke.py` 验证 `POST /api/v1/mcp` 的 `tools/list`，当前返回 27 个契约工具；新增 `agent.*` 和 `task.*` 工具使用 `X-Agent-Token`，未认证调用返回结构化错误。
- 容器化回归：使用独立 Compose 项目 `workbuddy-hub-poc-ci`、端口 `18100/55433` 和临时 volume 完成镜像构建、Alembic 启动迁移、PostgreSQL/Hub healthcheck 与同一 smoke；验证完成后已删除临时容器、网络和 volume，未触碰现有 8100 服务或业务库。
- 可观测性容器回归：使用独立 Compose 项目 `workbuddy-hub-observability-ci`、端口 `18120/55450` 构建新镜像；运行态 smoke 验证 4 案例、兼容标题、18 个 MCP 工具、`X-Request-Id` 透传、三类 Prometheus 指标及模板路由标签，随后删除临时容器、网络、volume 和镜像；原 8100 服务仍返回 health ok 和 4 个案例。
- 监控栈回归：`prom/prometheus:v3.5.0` 固定多架构 digest，`promtool` 验证 1 个配置和 3 条规则；隔离 Compose 项目 `workbuddy-hub-monitoring-ci` 在 `18130/55460/19091` 启动 PostgreSQL、Hub 和 Prometheus，运行态确认 Hub target 为 `up` 且 3 条告警规则加载。首次运行暴露只读容器 tmpfs 权限问题，修正为 `nobody` 的 `uid/gid 65534` 后通过；临时容器、网络、volume 和 Hub 镜像已清理。
- Trace 回归：内存导出器验证外部 `traceparent` 父子关系、模板路由和日志 `trace_id/span_id` 一致；默认 `httpx` hook 只传播 `traceparent`；异常仅记录类型且不导出消息；本机临时 OTLP/HTTP 接收端收到 `/v1/traces` protobuf。隔离 Compose 项目 `workbuddy-hub-tracing-ci` 在 `18140/55470` 构建含 OTel 依赖的新镜像并完成完整 smoke，随后清理；该证据不等同真实 Collector 或跨平台链路已验收。
- Collector 回归：固定 `otel/opentelemetry-collector-contrib:0.130.1` 多架构 digest，官方 `validate` 通过新版 pull-reader 配置；隔离 Compose 项目 `workbuddy-hub-otel-ci` 在 `18150/55480/18890/13135` 启动 PostgreSQL、Hub 与 Collector，完整 Hub smoke 后以固定 W3C trace ID 请求，Hub 回传同一 `X-Trace-Id`，Collector 指标记录 10 个 OTLP/HTTP Span；临时容器、网络、volume 和 Hub 镜像已清理。PoC debug exporter 无长期存储，不等同生产 Trace 后端验收。
- Kubernetes 模板回归：`kubectl v1.34.1` 内置 Kustomize 可渲染 10 个资源；固定 digest 的 `kubeconform v0.7.0` 按 Kubernetes 1.30 strict schema 验证 10/10 有效；3 项语义测试通过，仓库模式允许 4 类占位标记而生产模式明确拒绝。独立 `workbuddy-hub-nonroot-ci` Compose 在 `18160/55490` 验证容器 UID 10001、迁移、健康和完整 smoke，临时资源已清理。该证据不等同目标 Kubernetes 集群准入、网络和滚动发布已验收。
- 供应链回归：生产依赖锁 SHA-256 为 `a325dfd2...094d0a`；固定 `pip-audit 2.9.0` 审计 46 个依赖为 0 漏洞；固定 digest 的 Trivy 0.66.0 扫描最终镜像为 0 漏洞；CycloneDX 1.6 包含 100 个组件，例外表为空。初始 Debian slim 固定镜像曾因 4 CRITICAL、19 HIGH 正确阻断，改用固定 Alpine 并删除运行时 pip 后归零。独立 `workbuddy-hub-supply-chain-ci` Compose 在 `18180/55510` 验证 UID 10001、无 pip、迁移和完整 smoke，临时资源已清理；详见 [Hub 供应链基线](evidence/2026-08-08-Hub供应链基线.md)。该证据不等同 GitHub Runner、镜像签名/来源证明、多架构或生产准入已验收。
- 本地容量回归：只读探针先通过 6 项护栏/统计/阈值测试；独立 `workbuddy-hub-load-ci` Compose 在 `18170/55500` 完成 5,000 请求、20 并发目录基线，错误率 0、p95 98.833 ms，测试后临时资源已清理。负载结束后的单次资源快照不代表峰值，未用于定容；详见 [Hub 本地容量基线](evidence/2026-08-08-Hub本地容量基线.md)。
- 恢复演练：使用独立项目 `workbuddy-hub-restore-ci`、端口 `18110/55440` 创建 28,842 字节备份（SHA-256 `3ce4709a...47ad`，迁移 `0005_publication_scan_rules`），恢复到 `workbuddy_hub_restore_2a25c809` 后在 18111 端口完成端到端 smoke；演练临时 API、临时数据库、Compose 容器/网络/volume 和本机临时备份均已清理。该证据验证本地 PoC 工具链，不等同生产 RPO/RTO 验收。
- 兼容性：4 个案例保持，`case-capacity` 标题为 `项目资料交付检查`。
- 前端：Skill 中心和协作室桌面与移动端浏览器布局、交互错误状态和控制台通过；静态 URL 返回 200。
- 运行边界：未配置 SkillHub、AgentTeams Controller 或 Matrix 时返回明确错误；没有模拟成功。已删除对不存在的 AgentTeams `/api/v1/tasks` 路径的依赖。
- 断线边界：真实本地进程烟测中，Matrix 未配置时 `wait/events/artifacts` 均返回 `sync=degraded`；临时烟测任务随后已删除。
- 文件边界：真实本地进程烟测中，MXC allowlist 未配置时校验返回 503、持久化失败状态并写入审计；临时任务、事件、验证和审计记录随后已删除。
- 身份边界：代码级 OIDC 与可见范围测试已通过；真实 IdP、Claim、Subject 生命周期和 Namespace 同步仍是外部验收项，当前不能宣称组织 SSO 已上线。
- SkillHub 哈希边界：真实 `v0.2.16` 的 resolve/detail 不提供包哈希，Hub 已增加 25 MiB 默认上限的流式 SHA-256 回退；实际包若超过上限或下载响应异常则安装计划明确失败，不返回不可校验计划。
- AgentTeams 前置边界：`agentteams-preflight.ps1` 实跑生成 17 项检查；当前源码 HEAD `90f861c` 不等于稳定 `v1.2.1` 的 `552d0fb`，且本机没有 `helm`、真实 Controller/Matrix URL 和测试凭据，因此退出码为 2，未尝试部署。
- Secret 边界：`python tools/secret_scan.py --json` 扫描 Git 文件列表中的 146 个文本文件、`--walk` 扫描全工作区 209 个可读文本文件，均为 0 个发现；临时 API_KEY fixture 被识别且不输出值。该结果不覆盖服务器历史副本或 Git 历史，生产前仍必须人工轮换和审计。

## 已确认的上游限制

- AgentTeams Controller 不提供任务、消息、事件或取消 API；这些动作必须走 Matrix/Manager 工作流。
- 当前 Team 响应不提供 coordinator 投递所需的 Leader Matrix ID，因此一期自动投递严格限定为 Team Admin 的 `leaderDMRoomID`。
- 取消是 Matrix 中的协作停止请求；在 Agent 回传确认前，Hub 状态只能是 `cancel_requested`。
- SkillHub ClawHub `latestVersion` 是嵌套对象，固定版本必须通过 `/api/v1/resolve` 获取；下载 302 可能返回相对地址。

## 当前阻塞与个人开发边界

**本地开发当前无阻塞，也不需要用户再提供 OIDC、Kubernetes、生产告警负责人或正式 SLO/RPO/RTO。** 模型配置已填写，固定版本上游、Hub 连接、Skill 安装计划和真实 Agent 回复均已验证。

迁移到 16H16G Linux 服务器时，才需要确定服务器公网 IP/域名、防火墙和 HTTPS。个人试用可以继续使用本地身份；OIDC、多人权限、告警值班和正式灾备指标在出现真实多人/生产需求后再启用。具体步骤见 [16H16G 单机服务器迁移指南](16H16G单机服务器迁移指南.md)。
