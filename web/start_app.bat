@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在启动七天学堂查分与排名看板: http://127.0.0.1:8765
start "" "http://127.0.0.1:8765"
python app.py 8765
pause
