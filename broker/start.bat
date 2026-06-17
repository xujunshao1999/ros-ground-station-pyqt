@echo off
REM ============================================================
REM Mosquitto MQTT Broker 启动脚本 (Windows)
REM ROS 地面站项目
REM ============================================================

echo [ROS Ground Station] Starting MQTT Broker...

REM 尝试多个可能的 Mosquitto 安装路径
set MOSQUITTO_PATH=

REM 1. 检查 PATH 中是否有 mosquitto
where mosquitto >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    set MOSQUITTO_PATH=mosquitto
    goto :found
)

REM 2. 检查常见安装路径
for %%P in (
    "C:\Program Files\mosquitto\mosquitto.exe"
    "C:\mosquitto\mosquitto.exe"
    "%ProgramFiles%\mosquitto\mosquitto.exe"
    "%ProgramW6432%\mosquitto\mosquitto.exe"
) do (
    if exist %%P (
        set "MOSQUITTO_PATH=%%P"
        goto :found
    )
)

echo [ERROR] Mosquitto not found!
echo.
echo Please install Mosquitto:
echo   Option 1: winget install EclipseFoundation.Mosquitto
echo   Option 2: Download from https://mosquitto.org/download/
echo.
echo Or use the Python fallback broker:
echo   pip install amqtt
echo   python broker/start_pybroker.py
echo.
pause
exit /b 1

:found
echo [ROS Ground Station] Found Mosquitto: %MOSQUITTO_PATH%
echo [ROS Ground Station] Config: broker\mosquitto.conf
echo [ROS Ground Station] Press Ctrl+C to stop
echo.

%MOSQUITTO_PATH% -c broker\mosquitto.conf
