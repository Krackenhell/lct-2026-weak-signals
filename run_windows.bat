@echo off
rem Запуск стенда на Windows без Docker: Python 3.11+, Git и файл .env в корне репозитория.
rem Сторож (deploy\supervisor.py) сам обновляет стенд из GitHub (ветка main) и перезапускает сервер при сбое.
cd /d "%~dp0"
if not exist backend\.venv python -m venv backend\.venv
set PYTHONIOENCODING=utf-8
if "%PORT%"=="" set PORT=80
backend\.venv\Scripts\python deploy\supervisor.py
