@echo off
REM Executa o Chromaqui! a partir do codigo-fonte (precisa do Python 3.10+)
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install -r requirements.txt
)
start "" .venv\Scripts\pythonw run_chromaqui.py %*
