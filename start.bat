@echo off
setlocal
set "ROOT=%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.11 or newer and enable PATH.
  pause
  exit /b 1
)
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
  echo Python 3.11 or newer is required.
  pause
  exit /b 1
)
where node >nul 2>nul
if errorlevel 1 (
  echo Node.js was not found. Install Node.js 20 or newer and enable PATH.
  pause
  exit /b 1
)
node -e "process.exit(Number(process.versions.node.split('.')[0]) >= 20 ? 0 : 1)"
if errorlevel 1 (
  echo Node.js 20 or newer is required.
  pause
  exit /b 1
)

if not exist "%ROOT%backend\.venv\Scripts\python.exe" (
  echo Creating backend virtual environment...
  python -m venv "%ROOT%backend\.venv"
  if errorlevel 1 exit /b 1
)
if not exist "%ROOT%backend\.venv\Lib\site-packages\fastapi" (
  echo Installing backend dependencies...
  "%ROOT%backend\.venv\Scripts\python.exe" -m pip install -r "%ROOT%backend\requirements.txt"
  if errorlevel 1 exit /b 1
)
if not exist "%ROOT%frontend\node_modules" (
  echo Installing frontend dependencies...
  pushd "%ROOT%frontend"
  call npm install
  if errorlevel 1 (
    popd
    exit /b 1
  )
  popd
)

start "EcoPulse API" /D "%ROOT%backend" cmd /k ".venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
start "EcoPulse UI" /D "%ROOT%frontend" cmd /k "npm run dev"
ping 127.0.0.1 -n 4 >nul
start "" "http://localhost:5173"
echo.
echo EcoPulse is starting:
echo   UI:  http://localhost:5173
echo   API: http://localhost:8000
echo   Docs: http://localhost:8000/docs
echo.
endlocal
