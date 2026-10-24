# MCP 工具支持（v0.2）

> 把任意 MCP（Model Context Protocol）服务器的工具挂进 agentd：模型像用内置工具一样调用它们。

## 配置

`AGENTD_MCP_SERVERS`（JSON）：

```json
{"fetch": {"url": "https://mcp.example.com/mcp", "token": "可选 bearer"}}
```

多个服务器并列即可；`.env` 里注意单行 JSON。启动时对每个服务器做 Streamable HTTP 握手（`initialize` → 会话头 → `tools/list`），工具以 `名字原名` 注册（与内置工具同名时内置优先）。

## 行为

- **传输**：Streamable HTTP（JSON-RPC 2.0 over POST；JSON 与 SSE 帧响应都支持）
- **容错**：单个服务器不可用/握手失败 → 记日志（`mcp.unavailable`）跳过，不影响其它工具与启动
- **执行**：走统一工具管线（超时、异常转错误结果、16k 截断、审计 `tool.call`）；`isError` 结果映射为工具错误，不炸 run
- **可观测**：`mcp.initialized/loaded/unavailable` 日志；工具调用与内置一样进审计与指标

## 安全边界

MCP 工具**不受** workspace/SSRF 限制——服务器本身是你显式配置的外部依赖，调用参数由模型生成。建议：只接可信服务器；需要网络隔离时把 MCP 服务器放在内网并配 token；shell 类 MCP 工具等同于开启 shell（慎重）。

## 现状与限制（v0.2 D1）

- 仅 Streamable HTTP 传输（stdio 服务器用 `mcp-proxy` 类网关转接即可）
- 不订阅资源/提示（resources/prompts），只消费 tools
- 工具列表在启动时快照；服务器后续增删工具需重启生效（v0.2 刷新机制）
- 无逐服务器超时覆盖（统一 30s + 工具管线超时）

## 验证

- 单元测试：`tests/unit/test_mcp.py`（握手/发现/调用、SSE 帧响应、错误映射、坏服务器跳过、配置解析）
- 手工：`.env` 配一个真实 MCP 服务器 → 控制台 Playground 问一句触发它的工具
