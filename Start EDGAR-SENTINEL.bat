@echo off
title EDGAR-SENTINEL Stock Research App
echo ========================================================
echo Starting EDGAR-SENTINEL Stock Research App...
echo ========================================================
echo.
wsl.exe -e bash -c "cd /home/hashim/big_projects/capstone && ./scripts/start_web.sh"
pause
