@echo off
title DMM Scanner
cd /d "%~dp0"
start http://localhost:5000
python dmm_scanner.py
pause
