@echo off
setlocal
pushd "%~dp0"
python -c "import PIL, pillow_heif" >nul 2>&1
if errorlevel 1 (
  echo Thieu dependency. Chay: python -m pip install -r requirements.txt
  pause
  exit /b 1
)
where ffmpeg >nul 2>&1
if errorlevel 1 (
  echo Khong tim thay ffmpeg trong PATH.
  pause
  exit /b 1
)
python timelapse.py
if errorlevel 1 pause
popd
