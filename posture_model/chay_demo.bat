@echo off
REM Chay demo 2 camera + server gia, xem METADATA truc tiep.
REM   chay_demo.bat 1                                   (cam hong = webcam so 1)
REM   chay_demo.bat http://192.168.1.5:8080/video       (cam hong = dien thoai, app IP Webcam)
REM Cam laptop luon la webcam 0. Phim trong cua so: q thoat, c hieu chinh lai, m an/hien METADATA.
cd /d %~dp0
if "%~1"=="" (
  echo Thieu cam hong. Vi du: chay_demo.bat 1   hoac   chay_demo.bat http://192.168.1.5:8080/video
  exit /b 1
)
python -c "import json,os;p='app_config.json';d=json.load(open(p,encoding='utf-8')) if os.path.exists(p) else {};d['api_base_url']='http://127.0.0.1:8080';d['api_token']=None;json.dump(d,open(p,'w',encoding='utf-8'),ensure_ascii=False,indent=2)"
start "SERVER GIA - du lieu backend nhan duoc" cmd /k python mock_server.py
timeout /t 2 >nul
python realtime_app.py --side %1 --front 0 --log out\log.csv
