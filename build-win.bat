@echo off
rem ============================================================
rem  SpaceCadetPinball - native Windows build (MinGW + Ninja)
rem  Requires: MSYS2 at MSYS2_DIR (default D:\workspace\tools\msys64)
rem  Output:   bin\SpaceCadetPinball.exe
rem ============================================================
setlocal

if "%MSYS2_DIR%"=="" set MSYS2_DIR=D:\workspace\tools\msys64

set PATH=%MSYS2_DIR%\mingw64\bin;%PATH%
set SDL2DIR=%MSYS2_DIR%/mingw64

cd /d "%~dp0"

echo [1/3] Configuring...
cmake -S . -B build-native -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_POLICY_VERSION_MINIMUM=3.5
if errorlevel 1 goto fail

echo [2/3] Building...
cmake --build build-native -j 8
if errorlevel 1 goto fail

echo [3/3] Copying runtime DLLs...
for %%D in (SDL2.dll SDL2_mixer.dll libFLAC.dll libmpg123-0.dll libogg-0.dll ^
 libopus-0.dll libopusfile-0.dll libvorbis-0.dll libvorbisfile-3.dll ^
 libwavpack-1.dll libwinpthread-1.dll libxmp.dll) do (
    if exist "%MSYS2_DIR%\mingw64\bin\%%D" copy /y "%MSYS2_DIR%\mingw64\bin\%%D" bin\ >nul
)

echo.
echo Build OK -^> bin\SpaceCadetPinball.exe
exit /b 0

:fail
echo.
echo Build FAILED
exit /b 1
