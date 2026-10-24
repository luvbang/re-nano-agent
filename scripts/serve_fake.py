#!/usr/bin/env python
"""本地演示/联调服务（M6）：fake provider + 控制台静态资源，无需真实模型 key。

    uv run python scripts/serve_fake.py [--port 8000]
仅供开发与演示（Playground 行为是脚本化的）；生产请配 AGENTD_LLM_*。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from agentd.config import Settings
from agentd.main import create_app
from agentd.providers.fake import FakeChatProvider, demo_turn


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    dist = Path(__file__).resolve().parents[1] / "web" / "dist"
    settings = Settings(
        env="dev",
        log_level="INFO",
        log_json=False,
        admin_api_key="admin-local-demo",
        static_dir=dist if (dist / "index.html").exists() else None,
    )
    app = create_app(settings, provider=FakeChatProvider(turn_fn=demo_turn))
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
