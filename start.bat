@echo off
rem Opens Stock Note in its own window. To get a desktop icon, run install-shortcut.ps1 once.
cd /d "%~dp0"
if not exist .venv\Scripts\pythonw.exe (
  echo Setting up for the first time...
  py -m venv .venv
  .venv\Scripts\python -m pip install -q -r requirements.txt
)
start "" .venv\Scripts\pythonw.exe launcher.pyw
