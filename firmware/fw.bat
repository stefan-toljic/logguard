@echo off
rem LogGuard firmware profiles: one code base, one build folder per profile.
rem   fw a build                  build profile A into build_a
rem   fw b build                  build profile B into build_b
rem   fw b -p COM7 flash monitor  flash profile B and open the monitor
rem Profile settings: profiles\<name>.defaults. They are applied when build_<name>
rem is created; after changing a profile file, delete build_<name> and build again.
setlocal
set "P=%~1"
if "%P%"=="" goto usage
if not exist "%~dp0profiles\%P%.defaults" goto usage
set "DEF=%~dp0sdkconfig.defaults;%~dp0profiles\%P%.defaults"
if exist "%~dp0profiles\local.defaults" set "DEF=%DEF%;%~dp0profiles\local.defaults"
set ARGS=
:next
shift
if "%~1"=="" goto run
set ARGS=%ARGS% %1
goto next
:run
echo LogGuard profile %P%: build_%P%
idf.py -C "%~dp0." -B "%~dp0build_%P%" -D "SDKCONFIG=%~dp0build_%P%\sdkconfig" -D "SDKCONFIG_DEFAULTS=%DEF%"%ARGS%
exit /b %ERRORLEVEL%
:usage
echo Usage: fw a build ^| fw b build ^| fw b -p COM7 flash monitor
echo Profiles:
dir /b "%~dp0profiles\*.defaults"
exit /b 1
