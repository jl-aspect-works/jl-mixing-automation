@echo off
rem Internal Windows launcher for the authoritative JL Mixing Python runtime.
setlocal

if not defined _JL_MIXING_MODULE (
    >&2 echo Error: internal JL Mixing launcher requires a Python module name.
    exit /b 2
)

if defined JL_MIXING_HOME (
    set "_JL_APP_ROOT=%JL_MIXING_HOME%"
) else (
    set "_JL_APP_ROOT=%~dp0..\.."
)
for %%I in ("%_JL_APP_ROOT%") do set "_JL_APP_ROOT=%%~fI"

if defined JL_MIXING_PYTHON (
    set "_JL_PYTHON=%JL_MIXING_PYTHON%"
) else if exist "%_JL_APP_ROOT%\runtime\python.exe" (
    set "_JL_PYTHON=%_JL_APP_ROOT%\runtime\python.exe"
) else (
    where python.exe >nul 2>&1
    if errorlevel 1 (
        >&2 echo Error: JL Mixing Python runtime was not found.
        exit /b 3
    )
    set "_JL_PYTHON=python.exe"
)

if not exist "%_JL_PYTHON%" (
    where "%_JL_PYTHON%" >nul 2>&1
    if errorlevel 1 (
        >&2 echo Error: JL Mixing Python runtime was not found.
        exit /b 3
    )
)

if defined PYTHONPATH (
    set "PYTHONPATH=%_JL_APP_ROOT%\src;%PYTHONPATH%"
) else (
    set "PYTHONPATH=%_JL_APP_ROOT%\src"
)

"%_JL_PYTHON%" -m "%_JL_MIXING_MODULE%" %*
set "_JL_STATUS=%ERRORLEVEL%"
exit /b %_JL_STATUS%
