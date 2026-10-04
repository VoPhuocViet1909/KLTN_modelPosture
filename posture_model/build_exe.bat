@echo off
REM Dong goi Desktop App thanh thu muc chay duoc khong can cai Python: dist\PostureMonitor\PostureMonitor.exe
REM Chay 1 lan realtime_app.py truoc de tai face_landmarker.task, roi moi chay file nay.
cd /d %~dp0
pip install pyinstaller plyer
pyinstaller --noconfirm --name PostureMonitor ^
  --collect-all mediapipe --collect-binaries onnxruntime ^
  --hidden-import plyer.platforms.win.notification ^
  --add-data "posture_transformer.onnx;." ^
  --add-data "pose_landmarker_full.task;." ^
  --add-data "posture_config.json;." ^
  --add-data "schemas;schemas" ^
  realtime_app.py
if exist face_landmarker.task copy /y face_landmarker.task dist\PostureMonitor\_internal\ >nul
if exist app_config.json copy /y app_config.json dist\PostureMonitor\ >nul
echo.
echo Xong: dist\PostureMonitor\PostureMonitor.exe --side 1 --front 0
pause
