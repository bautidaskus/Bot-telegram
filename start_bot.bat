@echo off
rem Arranque del Personal Tracker Bot en Windows.
rem Copialo o crea un acceso directo en shell:startup para que arranque con la sesion.
cd /d "%~dp0"
call .venv\Scripts\activate.bat
python -m src.main
