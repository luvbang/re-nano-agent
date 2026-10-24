"""SDK 快速上手（M4 DoD：外部人员 30 分钟接入的第一站）。

前置：agentd 服务已启动，且设置了管理员 key：

    export AGENTD_ADMIN_API_KEY=agd_xxx
    uv run agentd serve --port 8000

运行本示例：

    uv run python examples/quickstart.py <base_url> <agd_xxx>

无参数时打本地默认地址，未配置服务会以 ConnectionError 退出（也是演示的一部分）。
"""

from __future__ import annotations

import sys

from agentd import Client


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    api_key = sys.argv[2] if len(sys.argv) > 2 else ""
    if not api_key:
        print("用法：python examples/quickstart.py <base_url> <agd_xxx>")
        print("（key 在服务端用 AGENTD_ADMIN_API_KEY 配置；也可在控制台 Keys 页创建）")
        return 2

    with Client(base_url=base_url, api_key=api_key) as client:
        session = client.sessions.create(title="quickstart")
        print(f"[1] 会话已创建：{session.id}")

        print("[2] 流式对话（输入触发工具：'现在几点了？'）：")
        with client.runs.stream(session.id, input="现在几点了？") as stream:
            for event in stream:
                if event.type == "message.delta":
                    print(event.delta, end="", flush=True)
                elif event.type == "tool.started":
                    print(f"\n[tool] {event.name} {event.args}")
                elif event.type == "tool.completed":
                    print(f"[tool] {event.name} {event.status} {event.duration_ms}ms")
        assert stream.result is not None
        print(
            f"\n[3] 完成 status={stream.result.status} "
            f"usage in={stream.result.input_tokens} out={stream.result.output_tokens}"
        )

        print(f"[4] 历史消息 {len(client.sessions.messages(session.id))} 条")
        usage = client.usage.get(from_="2000-01-01", to="2999-01-01", group_by="model")
        print(f"[5] 用量聚合：{[(i.group, i.runs) for i in usage.items]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
