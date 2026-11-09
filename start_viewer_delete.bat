@echo off
chcp 65001 >nul
set "PYTHONHOME="
python "%~dp0wechat_dat_viewer.py" serve --port 56789 --allow-delete --open
pause
