.PHONY: up down config config-gpu logs ps

up:
	@if command -v nvidia-smi >/dev/null 2>&1; then \
		echo "NVIDIA GPU detected; starting with compose.gpu.yaml"; \
		docker compose -f compose.yaml -f compose.gpu.yaml up --build; \
	else \
		echo "No NVIDIA GPU detected; starting with compose.yaml"; \
		docker compose -f compose.yaml up --build; \
	fi

down:
	docker compose -f compose.yaml down

config:
	docker compose -f compose.yaml config

config-gpu:
	docker compose -f compose.yaml -f compose.gpu.yaml config

logs:
	docker compose -f compose.yaml logs -f

ps:
	docker compose -f compose.yaml ps
