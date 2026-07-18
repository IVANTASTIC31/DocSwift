@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_CMD="

if exist ".venv\Scripts\python.exe" set "PYTHON_CMD=.venv\Scripts\python.exe"

if not defined PYTHON_CMD (
  where py >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=py -3"
)

if not defined PYTHON_CMD (
  where python >nul 2>nul
  if not errorlevel 1 set "PYTHON_CMD=python"
)

if not defined PYTHON_CMD (
  echo [错误] 未找到 Python 3。
  echo 请安装 Python 3.10 或更高版本，并在安装时勾选 Add Python to PATH。
  echo 安装完成后，在本目录运行：python -m pip install -r requirements.txt
  pause
  exit /b 1
)

%PYTHON_CMD% -c "import docx, openpyxl" >nul 2>nul
if errorlevel 1 (
  echo [错误] 缺少项目依赖。
  echo 请在本目录运行：%PYTHON_CMD% -m pip install -r requirements.txt
  pause
  exit /b 1
)

%PYTHON_CMD% app.py
if errorlevel 1 (
  echo.
  echo [错误] 程序运行失败，请查看上方错误信息。
  pause
  exit /b 1
)

endlocal
