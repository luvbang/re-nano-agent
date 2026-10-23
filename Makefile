# Makefile 只是薄壳：所有任务在 scripts/tasks.py 里实现，Windows 直接
#   uv run python scripts/tasks.py <task>
# 效果与 `make <task>` 完全一致。

.DEFAULT_GOAL := help
PY := uv run python

.PHONY: help install migrate dev serve test lint type check up down logs deploy tag

help: ## 列出可用任务
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "};{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## 创建 venv 并安装依赖（uv sync --all-groups）
	$(PY) scripts/tasks.py install

migrate: ## 应用数据库迁移（幂等）
	$(PY) scripts/tasks.py migrate

dev: ## 本地开发服务（热重载）
	$(PY) scripts/tasks.py dev

serve: ## 本地服务（无热重载）
	$(PY) scripts/tasks.py serve

test: ## 运行测试
	$(PY) scripts/tasks.py test

lint: ## ruff check
	$(PY) scripts/tasks.py lint

type: ## mypy 类型检查
	$(PY) scripts/tasks.py type

check: ## lint + type + test（提交前必跑）
	$(PY) scripts/tasks.py check

up: ## 构建并后台启动 app + caddy（docker compose）
	$(PY) scripts/tasks.py up

down: ## 停止容器
	$(PY) scripts/tasks.py down

logs: ## 跟踪 app 日志
	docker compose logs -f app

deploy: ## 部署机上更新到当前代码（迁移由容器启动时的 auto_migrate 完成）
	docker compose up -d --build
	docker compose ps

tag: ## 打里程碑 tag：make tag VERSION=v0.1.0-m1
	$(PY) scripts/tasks.py tag $(VERSION)
