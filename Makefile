.DEFAULT_GOAL := help

# Outside Docker the container paths do not exist, so write next to the repo.
# Anything already set in the environment wins.
DOWNLOADS_DIR ?= ./downloads
POLLER_STATE_DIR ?= ./downloads/.state
export DOWNLOADS_DIR POLLER_STATE_DIR

.PHONY: help run poll lint format up up-local down logs docker-build

help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "; print "\nUsage: make <target>\n"} \
		/^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-13s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""

run: ## Run the web UI on port 5000
	uv run python -m rai.web.app

poll: ## Run one poll cycle
	uv run python -m rai.poller

lint: ## Lint with ruff
	uvx ruff check .

format: ## Format with ruff
	uvx ruff format .

up: ## Start the stack behind the VPN
	docker compose up -d

up-local: ## Start the stack without the VPN, UI only
	docker compose up -d --build dl-local

down: ## Stop and remove both stacks
	docker compose --profile local down

logs: ## Follow container logs
	docker compose --profile local logs -f

docker-build: ## Build the image from this working tree
	docker compose --profile local build
