:: License
:: This script is given as is, without any warranties or guarantees.
:: Use this script at your own risk.
:: You must have read and understood the entire script before running it.
:: By using this script, you acknowledge that you have read and understood the above warnings.


@echo off
setlocal

:: START OF WARNING SECTION
:: CHANGE THIS TO "ALLOWED_TO_RUN" IF YOU WANT TO ALLOW DIRECT RUNNING OF THE SCRIPT
:: YOU NEED TO FULLY AGREE TO THE RISKS OF RUNNING THIS SCRIPT DIRECTLY
:: YOU ARE FULLY RESPONSIBLE FOR ANY CONSEQUENCES OF RUNNING THIS SCRIPT DIRECTLY
:: YOU MUST FULLY UNDERSTAND THE RISKS BEFORE PROCEEDING
:: SET THIS TO "ALLOWED_TO_RUN" ONLY IF YOU FULLY UNDERSTAND AND ACCEPT THE RISKS
:: YOU MUST SET ALLOWED_TO_RUN TO "ALLOWED_TO_RUN" IF YOU UNDERSTAND AND ACCEPT THE RISKS
:: THIS SCRIPT WILL EXIT IF ALLOWED_TO_RUN IS NOT SET TO "ALLOWED_TO_RUN"
:: THIS SCRIPT IS INTENDED TO BE RUN ONLY IF ALLOWED_TO_RUN IS SET TO "ALLOWED_TO_RUN"
:: IF YOU WANT TO RUN THIS SCRIPT DIRECTLY, SET ALLOWED_TO_RUN TO "ALLOWED_TO_RUN"
:: MAKE SURE YOU UNDERSTAND THE RISKS BEFORE SETTING ALLOWED_TO_RUN TO "ALLOWED_TO_RUN"
set ALLOWED_TO_RUN="ALLOWED_TO_RUN"
:: YOU HAVE BEEN WARNED ABOUT THE RISKS OF RUNNING THIS SCRIPT DIRECTLY
:: PROCEED ONLY IF YOU FULLY UNDERSTAND AND ACCEPT THE RISKS
:: RUNNING THIS SCRIPT WITHOUT FULLY UNDERSTANDING AND ACCEPTING THE RISKS IS NOT ADVISED
:: IF YOU ARE NOT SURE ABOUT THE RISKS, DO NOT RUN THIS SCRIPT DIRECTLY
:: END OF WARNING SECTION

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

:: INSTALLATION OF DEPENDENCIES SECTION


goto :skip_installation_of_dependencies

:: Installing Python dependencies SECTION
echo Installing Python dependencies...
pip install sqlalchemy

:: END OF INSTALLATION OF PYTHON DEPENDENCIES SECTION
:skip_installation_of_python_dependencies



:: Installing PostgreSQL docker image
echo Installing PostgreSQL docker image...
docker run --name umm-postgre ^
    -e POSTGRES_PASSWORD="%SQL_PASSWORD%" ^
    -d postgres

:skip_installation_of_postgresql_docker_image
:: END OF INSTALLATION OF POSTGRESQL DOCKER IMAGE SECTION

:: END OF DEPENDENCIES INSTALLATION SECTION

:skip_installation_of_dependencies

:: TERMINATION OF SCRIPT
:: RESET THE ALLOWED_TO_RUN FLAG
echo Resetting ALLOWED_TO_RUN flag...
powershell -NoProfile -Command "(Get-Content -Raw '%~f0') -replace 'set ALLOWED_TO_RUN=\"ALLOWED_TO_RUN\"', 'set ALLOWED_TO_RUN=\"NOT_ALLOWED_TO_RUN\"' | Set-Content '%~f0'"
echo Termination of script.
:: END OF SCRIPT
goto :eof

:not_direct
if "%ALLOWED_TO_RUN%==ALLOWED_TO_RUN" goto :main

echo ERROR: Direct execution is not allowed.
echo DO NOT RUN THIS SCRIPT DIRECTLY
echo After pause will exit the script.
echo Open the script and inspect its contents before running it.
pause
exit /b 1