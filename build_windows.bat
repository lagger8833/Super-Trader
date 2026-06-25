@echo off
REM ============================================================
REM  mStock Trader -- Windows Build Script
REM  Automatically installs Python if missing, then installs
REM  all dependencies and builds a standalone EXE.
REM  Run as Administrator for best results.
REM ============================================================

REM Always run from the folder where this bat file lives
cd /d "%~dp0"

echo.
echo ============================================================
echo   mStock Trader -- Build Setup
echo   Working directory: %~dp0
echo ============================================================
echo.

REM Verify requirements.txt is present
if not exist "requirements.txt" (
    echo ERROR: requirements.txt not found in %~dp0
    echo Make sure you extracted the full zip and are running
    echo build_windows.bat from inside the mstock_trader folder.
    pause
    exit /b 1
)

REM -- STEP 1: Check for Python ----------------------------------
echo [1/6] Checking for Python...
python --version >nul 2>&1
if errorlevel 1 goto :install_python

REM Python found -- verify it is 3.10+
for /f "tokens=2 delims= " %%V in ('python --version 2^>^&1') do set PY_VER=%%V
for /f "tokens=1,2 delims=." %%A in ("%PY_VER%") do (
    set PY_MAJOR=%%A
    set PY_MINOR=%%B
)
if %PY_MAJOR% LSS 3 goto :install_python
if %PY_MAJOR% EQU 3 if %PY_MINOR% LSS 10 goto :install_python

echo [OK] Python %PY_VER% found
goto :after_python_install

REM -- Python not found or too old -- download and install ------
:install_python
echo.
echo [!] Python 3.10+ not found. Downloading Python 3.12.4 installer...
echo     This requires an internet connection.
echo.

REM Detect architecture
reg Query "HKLM\Hardware\Description\System\CentralProcessor\0" /v "Identifier" | find /i "x86" >nul 2>&1
if errorlevel 1 (
    set PY_INSTALLER=python-3.12.4-amd64.exe
    set PY_URL=https://www.python.org/ftp/python/3.12.4/python-3.12.4-amd64.exe
) else (
    set PY_INSTALLER=python-3.12.4.exe
    set PY_URL=https://www.python.org/ftp/python/3.12.4/python-3.12.4.exe
)

echo     Downloading %PY_INSTALLER%...
powershell -Command "& { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%PY_URL%' -OutFile '%TEMP%\%PY_INSTALLER%' -UseBasicParsing }"

if not exist "%TEMP%\%PY_INSTALLER%" (
    echo.
    echo ERROR: Download failed. Please install Python 3.10+ manually from:
    echo        https://www.python.org/downloads/
    echo        Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)

echo.
echo [!] Running Python installer...
echo     ** IMPORTANT: The installer will open. **
echo     ** Check "Add Python to PATH" then click Install Now. **
echo.
start /wait "" "%TEMP%\%PY_INSTALLER%" /passive InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_launcher=1

python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo [!] Python installed but not yet on PATH for this session.
    echo     Please close this window and run build_windows.bat again.
    pause
    exit /b 1
)

echo [OK] Python installed successfully
del "%TEMP%\%PY_INSTALLER%" >nul 2>&1

:after_python_install

REM -- STEP 2: Upgrade pip ---------------------------------------
echo.
echo [2/6] Upgrading pip and setuptools...
python -m pip install --upgrade pip setuptools wheel
if errorlevel 1 (
    echo [WARN] pip upgrade had issues, continuing...
)

REM -- STEP 3: Install project requirements ---------------------
echo.
echo [3/6] Installing mStock Trading API dependencies...
python -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo ERROR: Failed to install requirements. Check your internet connection.
    pause
    exit /b 1
)

REM -- STEP 4: Install mStock Trading API package ---------------
echo.
echo [4/6] Installing mStock-TradingApi-A...
python -m pip install --upgrade mStock-TradingApi-A
if errorlevel 1 (
    echo ERROR: Failed to install mStock-TradingApi-A.
    pause
    exit /b 1
)

REM -- STEP 5: Install GUI + security + build tools -------------
echo.
echo [5/6] Installing PyQt5, cryptography, and PyInstaller...
python -m pip install PyQt5 cryptography pyinstaller
if errorlevel 1 (
    echo ERROR: Failed to install GUI/security packages.
    pause
    exit /b 1
)

REM -- STEP 6: Build the EXE ------------------------------------
echo.
echo [6/6] Building standalone EXE with PyInstaller...
pyinstaller "%~dp0mstock_trader.spec" --clean
if errorlevel 1 (
    echo.
    echo ERROR: PyInstaller build failed. See output above.
    pause
    exit /b 1
)

REM -- Result ---------------------------------------------------
echo.
if exist "%~dp0dist\mStockTrader.exe" (
    REM FIX #1: copy EXE to project root for easy access
    copy /Y "%~dp0dist\mStockTrader.exe" "%~dp0mStockTrader.exe" >nul
    echo ============================================================
    echo   SUCCESS!
    echo.
    echo   EXE (dist folder) : %~dp0dist\mStockTrader.exe
    echo   EXE (project root): %~dp0mStockTrader.exe  ^<-- easy access
    echo.
    echo   IMPORTANT: place your .env file next to mStockTrader.exe
    echo   before running it.  Copy .env.example ^-^> .env and fill in
    echo   your API_KEY.
    echo ============================================================
    echo.
    set /p OPEN_DIST="Open folder now? (Y/N): "
    if /i "%OPEN_DIST%"=="Y" explorer "%~dp0"
) else (
    echo ============================================================
    echo   Build may have encountered issues.
    echo   Check the output above for errors.
    echo ============================================================
)
echo.
pause
