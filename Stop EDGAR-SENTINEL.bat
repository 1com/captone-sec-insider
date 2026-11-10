@echo off
title Stop EDGAR-SENTINEL Web App
echo Stopping EDGAR-SENTINEL Stock Research App...
wsl.exe -e bash -c "cd /home/hashim/big_projects/capstone && ./scripts/stop_web.sh"
echo Done.
timeout /t 3

