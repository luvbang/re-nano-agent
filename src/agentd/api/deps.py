"""FastAPI 依赖注入：settings 与 db 挂在 app.state 上，测试可整体替换。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from agentd.config import Settings
from agentd.storage.db import Database


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_db(request: Request) -> Database:
    db: Database = request.app.state.db
    return db


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
DbDep = Annotated[Database, Depends(get_db)]
