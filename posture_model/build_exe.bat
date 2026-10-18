@echo off
setlocal
cd /d "%~dp0"
REM Use the project venv. Build dependency: pyinstaller==6.22.3
python -m PyInstaller --noconfirm --windowed --name PostureMonitor ^
  --exclude-module torch --exclude-module tensorflow ^
  --exclude-module PyQt5 --exclude-module PyQt6 ^
  --collect-all mediapipe --collect-binaries onnxruntime ^
  --hidden-import plyer.platforms.win.notification ^
  --hidden-import keyring.backends.Windows ^
  --add-data "posture_transformer.onnx;." ^
  --add-data "pose_landmarker_full.task;." ^
  --add-data "face_landmarker.task;." ^
  --add-data "posture_config.json;." ^
  --add-data "schemas;schemas" ^
  --add-data "ui;ui" app.py
if errorlevel 1 exit /b 1
echo Open dist\PostureMonitor\PostureMonitor.exe (keep the whole folder).
REM Never copy app_config.json, outbox, credentials or runtime logs into a release.
