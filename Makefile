SHELL := /bin/bash
PROJECT_DIR := /home/casperhood/.codex/NexDownSave
VENV := $(PROJECT_DIR)/venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
SERVICE := nexdownsave

.PHONY: help venv install env run compile test check health backup brand-assets service-install service-restart service-status logs clean

help:
	@echo "NexDownSave commands:"
	@echo "  make venv             - create virtual environment"
	@echo "  make install          - install Python dependencies"
	@echo "  make env              - create .env from template if missing"
	@echo "  make run              - run bot locally"
	@echo "  make compile          - syntax check project"
	@echo "  make test             - run unit tests"
	@echo "  make check            - run compile and unit tests"
	@echo "  make health           - run healthcheck"
	@echo "  make backup           - create SQLite backup"
	@echo "  make brand-assets     - generate local brand PNG assets"
	@echo "  make service-install  - install/update systemd service"
	@echo "  make service-restart  - restart systemd service"
	@echo "  make service-status   - show systemd status"
	@echo "  make logs             - tail journald logs"
	@echo "  make clean            - remove __pycache__ directories"

venv:
	python3 -m venv $(VENV)

install: venv
	$(PIP) install -U pip
	$(PIP) install -r $(PROJECT_DIR)/requirements.txt

env:
	@if [ ! -f $(PROJECT_DIR)/.env ]; then cp $(PROJECT_DIR)/.env.example $(PROJECT_DIR)/.env; echo ".env created from template"; else echo ".env already exists"; fi

run:
	cd $(PROJECT_DIR) && $(PYTHON) bot.py

compile:
	$(PYTHON) -m compileall $(PROJECT_DIR)

test:
	cd $(PROJECT_DIR) && $(PYTHON) -m unittest discover -s tests -p 'test_*.py'

check: compile test

health:
	cd $(PROJECT_DIR) && $(PYTHON) healthcheck.py

backup:
	cd $(PROJECT_DIR) && ./backup_db.sh

brand-assets:
	cd $(PROJECT_DIR) && $(PYTHON) scripts/generate_brand_assets.py

service-install:
	sudo cp $(PROJECT_DIR)/deploy/nexdownsave.service /etc/systemd/system/$(SERVICE).service
	sudo systemctl daemon-reload
	sudo systemctl enable --now $(SERVICE)

service-restart:
	sudo systemctl restart $(SERVICE)

service-status:
	sudo systemctl status $(SERVICE)

logs:
	journalctl -u $(SERVICE) -f

clean:
	find $(PROJECT_DIR) -type d -name '__pycache__' -prune -exec rm -rf {} +
