PYTHON ?= python3
VENV ?= .venv
AWS_ENDPOINT_URL ?= http://127.0.0.1:4566

.PHONY: up down test lint

up:
	docker compose up -d --wait --wait-timeout 90

down:
	docker compose down

$(VENV)/.ready: requirements-dev.txt
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/python -m pip install -r requirements-dev.txt
	touch $@

test: $(VENV)/.ready
	# The target name provides dummy values through process environment only.
	env -u AWS_SESSION_TOKEN -u AWS_SECURITY_TOKEN -u AWS_PROFILE -u AWS_DEFAULT_PROFILE \
	  AWS_ACCESS_KEY_ID=$@ AWS_SECRET_ACCESS_KEY=$@ AWS_DEFAULT_REGION=us-east-1 \
	  AWS_EC2_METADATA_DISABLED=true AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null \
	  AWS_ENDPOINT_URL=$(AWS_ENDPOINT_URL) $(VENV)/bin/python -m pytest -q

lint: $(VENV)/.ready
	$(VENV)/bin/ruff check src tests
	$(VENV)/bin/ruff format --check src tests
