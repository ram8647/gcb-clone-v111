@echo off
chdir %~dp0
call .\cygwin_setup.bat
chdir ..
set /P APPLICATION="What is the name of the App Engine instance to deploy to?"
%CYGWIN_TTY% --hold always /usr/bin/bash ^
  ./scripts/deploy.sh --noauth_local_webserver %APPLICATION%

