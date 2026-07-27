@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE="
set "PYTHONW_EXE="
set "PYTHON_ARGS="
set "CODEX_PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "CODEX_PYW=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\pythonw.exe"

if exist ".venv\Scripts\python.exe" (
  set "PYTHON_EXE=.venv\Scripts\python.exe"
  if exist ".venv\Scripts\pythonw.exe" set "PYTHONW_EXE=.venv\Scripts\pythonw.exe"
)

if not defined PYTHON_EXE (
  where py >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_EXE=py"
    set "PYTHON_ARGS=-3"
    where pyw >nul 2>nul
    if not errorlevel 1 set "PYTHONW_EXE=pyw"
  )
)

if not defined PYTHON_EXE (
  for /f "delims=" %%I in ('where python 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%I"
  for /f "delims=" %%I in ('where pythonw 2^>nul') do if not defined PYTHONW_EXE set "PYTHONW_EXE=%%I"
)

if not defined PYTHON_EXE (
  if exist "%CODEX_PY%" (
    set "PYTHON_EXE=%CODEX_PY%"
    if exist "%CODEX_PYW%" set "PYTHONW_EXE=%CODEX_PYW%"
  )
)

if not defined PYTHON_EXE (
  echo [ERROR] Python 3 was not found.
  echo Install Python 3.10 or newer and enable "Add Python to PATH".
  echo Then run: python -m pip install -r requirements.txt
  if not defined DOCSWIFT_NO_PAUSE pause
  exit /b 1
)

"%PYTHON_EXE%" %PYTHON_ARGS% -c "import docx, openpyxl, PySide6, pypdf" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Required packages are missing.
  echo Run: "%PYTHON_EXE%" %PYTHON_ARGS% -m pip install -r requirements.txt
  if not defined DOCSWIFT_NO_PAUSE pause
  exit /b 1
)

if /I not "%~1"=="--console" (
  if defined PYTHONW_EXE (
    start "" "%PYTHONW_EXE%" %PYTHON_ARGS% app.py
    exit /b 0
  )
)

"%PYTHON_EXE%" %PYTHON_ARGS% app.py
if errorlevel 1 (
  echo.
  echo [ERROR] DocSwift failed. Review the error message above.
  if not defined DOCSWIFT_NO_PAUSE pause
  exit /b 1
)

endlocal
