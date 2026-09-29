@echo off
rem Запуск стенда на Windows без Docker: Python 3.11+ и файл .env в корне репозитория.
cd /d "%~dp0backend"
if not exist .venv python -m venv .venv
.venv\Scripts\python -m pip install -q -r requirements.txt
set PYTHONIOENCODING=utf-8
.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 80
