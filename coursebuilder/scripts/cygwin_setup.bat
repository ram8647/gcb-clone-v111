@echo off

REM ----------------------------------------------------------------------------
REM Set up some convenience variables.

if "%PROCESSOR_ARCHITECTURE%" == "AMD64" (
  set SETUP_EXE=setup-x86_64.exe
) else (
  set SETUP_EXE=setup-x86.exe
)
set HOMEDRIVE=C:
set CYGWIN_ROOT=%HOMEDRIVE%\cb_cygwin
set TEMPDIR=%HOMEDRIVE%/cb_tmp
set CYGWIN_BIN=%CYGWIN_ROOT%\bin
set CYGWIN_TTY=%CYGWIN_BIN%\mintty.exe
set CYGWIN_LIB=%CYGWIN_ROOT%\lib

REM ----------------------------------------------------------------------------
REM Note that we are *not* trying to alter the %PATH% env var for the user nor
REM for the system.  Doing so would be too intrusive, especially since we are
REM installing Cygwin to a nonstandard location and the system may already have
REM a different installed version.  Instead, we set the
REM COURSE_BUILDER_CYGWIN_ROOT env var, which should not conflict with anything,
REM and use this in the bash start/deploy scripts to manipulate the path locally
REM for each invocation.

setx COURSE_BUILDER_CYGWIN_ROOT /cygdrive/%HOMEDRIVE%/cb_cygwin/bin

REM ----------------------------------------------------------------------------
REM Try to use PowerShell to download the appropriate Cygwin installer.
REM If we cannot, issue a helpful message.

set SETUP_URL=http://cygwin.com/%SETUP_EXE%
if not exist "%USERPROFILE%\Downloads\%SETUP_EXE%" (
  powershell -Command ^
    "Invoke-WebRequest %SETUP_URL% -OutFile \"%USERPROFILE%\Downloads\%SETUP_EXE%\""
)
if not %ERRORLEVEL% == 0 (
  msg %USERNAME% ^
    Download of Cygwin installer failed.  ^
    Please manually download %SETUP_URL% to ^
    "%USERPROFILE%\Downloads\%SETUP_EXE%" ^
    then re-run this command.

  echo Download of Cygwin installer failed.
  echo Please manually download %SETUP_URL% to
  echo "%USERPROFILE%\Downloads\%SETUP_EXE%"
  echo then re-run this command.
  timeout 3600
  exit 1
)

REM ----------------------------------------------------------------------------
REM Start Cygwin installer to fetch and install components needed by Course
REM Builder.

if not exist "%CYGWIN_TTY%" (
  goto install_cygwin
)
if not exist "%CYGWIN_BIN%\curl.exe" (
  goto install_cygwin
)
if not exist "%CYGWIN_BIN%\g++.exe" (
  goto install_cygwin
)
if not exist "%CYGWIN_BIN%\gcc.exe" (
  goto install_cygwin
)
if not exist "%CYGWIN_BIN%\python" (
  goto install_cygwin
)
if not exist "%CYGWIN_BIN%\python2.7.exe" (
  goto install_cygwin
)
if not exist "%CYGWIN_LIB%\python2.7\site-packages\libxml2.py" (
  goto install_cygwin
)
if not exist "%CYGWIN_LIB%\python2.7\site-packages\libxslt.py" (
  goto install_cygwin
)
if not exist "%CYGWIN_BIN%\unzip.exe" (
  goto install_cygwin
)
goto cygwin_installed
:install_cygwin
"%USERPROFILE%\Downloads\%SETUP_EXE%" ^
  --wait ^
  --quiet-mode ^
  --root=%CYGWIN_ROOT% ^
  --local-package-dir=%TEMPDIR% ^
  --site=http://cygwin.mirror.constant.com ^
  --packages=dos2unix,python,python-devel,python-lxml,python-libxslt,gcc-g++,curl,unzip
:cygwin_installed



