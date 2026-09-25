@echo off
title SyncBridge - Sincronización Segura en la Nube
color 0B
echo ========================================================
echo   SyncBridge: Sincronizando archivos del cluster local
echo ========================================================
echo.

cd /d "C:\Users\ferre\VSCode Projects\sync-bridge"
call venv\Scripts\activate

REM Ejecuta el motor de sincronización que imprime su propio estado
python -m src.sync_engine

echo.
echo ========================================================
echo   Proceso finalizado con exito. Cerrando ventana...
echo ========================================================
timeout /t 4 >nul
exit