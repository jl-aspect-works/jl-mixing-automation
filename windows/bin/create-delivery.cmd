@echo off
setlocal
set "_JL_MIXING_MODULE=jl_mixing.create_delivery_cli"
call "%~dp0jl-mixing-python-command.cmd" %*
exit /b %ERRORLEVEL%
