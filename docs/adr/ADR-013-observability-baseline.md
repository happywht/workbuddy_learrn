# ADR-013：Hub 可观测性基线

## 状态

已采用，本地 PoC 已实现；生产采集、告警路由和 Trace 后端待环境验收。

## 决策

1. Hub API 为每个 HTTP 响应返回 `X-Request-Id`。只接受 1-128 位字母、数字、点、下划线、冒号或连字符；缺失或非法时生成 UUID。
2. 访问日志使用单行 JSON，只记录事件名、请求 ID、方法、FastAPI 路由模板、状态码和耗时。不得记录 Authorization、Cookie、请求体、原始 URL 或查询值。
3. Prometheus 指标使用 `method`、路由模板和状态码等有界标签；不得以工件 ID、任务 ID、用户、部门、查询词或异常正文作为标签。
4. `/metrics` 不进入 OpenAPI，也不由公网 Nginx 示例代理。生产由集群内 Prometheus 通过 NetworkPolicy 和采集身份访问。
5. PoC 使用固定 digest 的 Prometheus，配置 6 小时临时保留，并提供目标失联、持续 5xx 和目录 p95 三条初始规则。Trace 采样、告警阈值、通知负责人、正式保留期和容量结论必须在生产同构环境通过压测和演练后冻结。
6. Trace 使用 OpenTelemetry SDK 和 W3C `traceparent`。只有显式配置完整 OTLP/HTTP `/v1/traces` 端点时才创建导出器；访问日志关联 `trace_id`/`span_id`，默认上游 `httpx` 客户端只传播 `traceparent`，不传播 baggage。
7. Span 仅记录方法、路由模板、状态码和异常类型。原始 URL、查询值、请求体、认证头、Cookie 与异常消息不得写入 Span；OTLP URL 不允许内嵌凭据、查询参数或 fragment。

## 初始指标

- `workbuddy_hub_http_requests_total{method,route,status}`
- `workbuddy_hub_http_request_duration_seconds{method,route}`
- `workbuddy_hub_http_requests_in_progress{method}`

可用性和延迟从前两个指标计算。业务审计仍写入 Hub 审计表，不能由访问日志代替。

## 后果

路由模板避免动态 ID 造成 Prometheus 时序基数失控，请求 ID 可关联反向代理和应用日志。内存导出器、本机 OTLP 接收测试及固定 digest Collector 的隔离 Compose 已证明入站父子关系、日志关联、出站传播、protobuf 导出和 Collector 接收；但尚不能证明生产 Collector/存储可用、跨平台链路完整、告警可触达、99.5% 可用性或 p95 小于 1 秒，这些仍是 Phase 5 退出门。
