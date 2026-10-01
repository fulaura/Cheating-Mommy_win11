@echo off

g++ -std=c++17 -O2 -static -static-libgcc -static-libstdc++ -o update_credentials.exe update_credentials.cpp
g++ -std=c++17 -O2 -static -static-libgcc -static-libstdc++ -o crop_region.exe crop_region.cpp
g++ -std=c++17 -O2 -static -static-libgcc -static-libstdc++ -o hotkey_configuration.exe hotkey_configuration.cpp -luser32

set "APP_NAME=Cheating Mommy"
set "APP_VERSION=1.3.1"
for /f "usebackq tokens=1,* delims==" %%A in ("app.txt") do (
    if /i "%%A"=="APP_NAME" set "APP_NAME=%%B"
    if /i "%%A"=="APP_VERSION" set "APP_VERSION=%%B"
)
(
    echo #define AppName "%APP_NAME%"
    echo #define AppVersion "%APP_VERSION%"
) > app_meta.iss
call "%~dp0.venv\Scripts\activate.bat"
call "%~dp0.venv\Scripts\python.exe" -m PyInstaller --onefile --noconsole --icon icon.ico --name "%APP_NAME%" --clean main.py
call "%~dp0.venv\Scripts\python.exe" -m PyInstaller --onefile --console  --icon icon.ico --name "%APP_NAME%_console" --clean main.py
call "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" "installer.iss"

