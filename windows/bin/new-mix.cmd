@echo off
setlocal
set "_JL_MIXING_MODULE=jl_mixing.new_mix_cli"
call "%~dp0jl-mixing-python-command.cmd" %*
exit /b %ERRORLEVEL%
