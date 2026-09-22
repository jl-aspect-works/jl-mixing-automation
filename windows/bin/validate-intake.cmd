@echo off
setlocal
set "_JL_MIXING_MODULE=jl_mixing.validate_intake_cli"
call "%~dp0jl-mixing-python-command.cmd" %*
exit /b %ERRORLEVEL%
