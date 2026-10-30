@echo off
chcp 65001 >nul
setlocal

echo [1/2] Проверяем зависимости...
python check_deps.py
if errorlevel 1 goto :error

echo.
echo [2/2] Собираем HoYoWorker.exe...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

pyinstaller --noconfirm --onefile --windowed --icon "icon.ico" --add-data "icon.png;." ^
    --hidden-import PyQt6.QtWebEngineWidgets ^
    --hidden-import PyQt6.QtWebEngineCore ^
    main.py
if errorlevel 1 goto :error

echo.
echo Готово: dist\HoYoWorker.exe
exit /b 0

:error
echo.
echo Сборка остановлена из-за ошибки. Смотрите сообщения выше.
exit /b 1
