@echo off
setlocal

:: ============================================================
:: WARNING SECTION
:: ============================================================

:: CHANGE THIS TO "ALLOWED_TO_RUN" ONLY AFTER READING THIS FILE

set "ALLOWED_TO_RUN=NOT_ALLOWED_TO_RUN"

:: ============================================================
:: END WARNING SECTION
:: ============================================================

goto :not_direct


:main

if "%SQL_PASSWORD%"=="" (
    echo ERROR: SQL_PASSWORD is not set.
    echo Set it before running this script:
    echo.
    echo     set SQL_PASSWORD=your_secure_password
    echo.
    exit /b 1
)

:: ============================================================
:: INSTALLATION OF DEPENDENCIES
:: ============================================================

goto :test_skip

echo Installing Python dependencies...

pip install sqlalchemy

echo Installing PostgreSQL Docker image...

docker run --name umm-postgre ^
    -e POSTGRES_PASSWORD="%SQL_PASSWORD%" ^
    -d postgres

:test_skip

:: ============================================================
:: RESET EXECUTION PERMISSION
:: ============================================================

echo.
echo Resetting ALLOWED_TO_RUN flag...

powershell -NoProfile -Command "(Get-Content -Raw '%~f0') -replace 'set ""ALLOWED_TO_RUN=ALLOWED_TO_RUN""', 'set ""ALLOWED_TO_RUN=NOT_ALLOWED_TO_RUN""' | Set-Content '%~f0'"

echo.
echo Termination of script.

goto :eof


:not_direct

if "%ALLOWED_TO_RUN%"=="ALLOWED_TO_RUN" goto :main

echo ERROR: Direct execution is not allowed.
echo DO NOT RUN THIS SCRIPT DIRECTLY
echo After pause will exit the script.
echo Open the script and inspect its contents before running it.

pause
exit /b 1