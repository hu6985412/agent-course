@echo off
REM ============================================================================
REM  start-env-windows.bat  --  one-click LLM env loader (Windows ONLY)
REM
REM  WHAT IT DOES
REM    Sets API_KEY / BASE_URL / MODEL for THIS window only, fixes the console
REM    to real UTF-8, then opens a shell. Nothing is written to the registry
REM    and nothing is written to disk. Close the window and it is all gone.
REM
REM  HOW TO USE
REM    1. COPY THIS FILE OUT OF THE REPO FIRST (e.g. to C:\Users\you\llm-env\)
REM       -- never fill in your real key inside a git working copy.
REM    2. Right-click the copy -> Edit, change the 3 lines marked  >>> EDIT
REM    3. Save (keep CRLF line endings -- see tools/README.md)
REM    4. Double-click it, then cd to the week folder you are working on
REM
REM  WHY THE VALUES STAY LOCAL
REM    cmd sets them -> powershell.exe is started as a CHILD process ->
REM    child inherits parent env -> bash/python inherit again. Environment
REM    blocks are inherited, never shared upwards, so only this window sees
REM    them. No setx, no .env file, no restart of VS Code needed.
REM
REM  WHY NOT PASS THE KEY ON THE COMMAND LINE
REM    Anything typed on a command line lands in shell history
REM    (~/.bash_history, PSReadLine history) and in the process list.
REM    Environment variables do neither.
REM
REM  WHY THE UTF-8 BLOCK EXISTS  (this is not cosmetic -- see week-01)
REM    Windows PowerShell 5.1 decodes output from native EXEs using the legacy
REM    OEM code page (936 = GBK on a zh-CN machine), NOT UTF-8. An API replies
REM    in UTF-8, so every Chinese char gets decoded as GBK:
REM        归 = E5 BD 92  --GBK-->  three mojibake chars
REM    Worse: the mangled text eats the closing quote of the JSON string, so
REM      curl ... | ConvertFrom-Json
REM    dies with "invalid object, expected ':' or '}'". You blame the parser;
REM    the parser is innocent -- the bytes were already destroyed upstream.
REM    Setting [Console]::OutputEncoding to UTF-8 removes the whole class of
REM    bug. PowerShell 7 (pwsh) defaults to UTF-8 and does not need this.
REM
REM  NOTE: prompts are in English on purpose -- GBK/UTF-8 mismatch in cmd
REM        turns Chinese comments into mojibake and can break parsing.
REM ============================================================================

REM ---------- >>> EDIT THESE 3 LINES <<< ----------
set "API_KEY=PASTE_YOUR_KEY_HERE"
set "BASE_URL=https://your-relay.com/v1"
set "MODEL=your-model-name"
REM ---------- >>> END OF EDITABLE BLOCK <<< ----------

REM ---------- >>> OPTIONAL: point at a newer Python <<< ----------
REM Leave this EMPTY to keep your system python. Fill it in ONLY if your
REM system python is older than 3.9 -- from week-05 on, packages such as
REM pgvector and langgraph refuse to install on 3.8 (end of life Oct 2024).
REM The value is the FOLDER that holds python.exe, not python.exe itself.
REM Example (yours will differ):
REM   C:\Users\you\AppData\Local\Programs\Python\Python313
set "PYTHON_HOME="
if defined PYTHON_HOME set "PATH=%PYTHON_HOME%;%PATH%"
REM ---------- >>> END OF OPTIONAL BLOCK <<< ----------

REM --- UTF-8, part 1/3: switch cmd's own code page -------------------------
REM Only affects this window. If you are on Windows 7/8 or see weird output,
REM put REM in front of the next line -- the PowerShell settings below alone
REM are enough for curl.exe output.
chcp 65001 >nul

REM --- UTF-8, part 2/3: tell Python to stop guessing -----------------------
REM Without this, Python writes to a console or pipe using cp936 and can raise
REM UnicodeEncodeError on Chinese replies. PEP 540 flag, needs Python 3.7+.
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

REM BASE_URL rule: stop at /v1 -- do NOT append /chat/completions.
REM If you do, every request hits /v1/chat/completions/chat/completions and 400s.
echo %BASE_URL% | findstr /i /c:"/chat/completions" >nul
if %errorlevel%==0 (
  echo   [!] BASE_URL looks like a full endpoint. It must end with /v1 only.
)

echo.
echo   [env] loaded into THIS window only
echo     BASE_URL    = %BASE_URL%
echo     MODEL       = %MODEL%
echo     API_KEY     = %API_KEY:~0,6%......
for /f "tokens=*" %%p in ('python --version 2^>^&1') do echo     python      = %%p
echo.

if "%API_KEY%"=="PASTE_YOUR_KEY_HERE" (
  echo   [!] API_KEY is still the placeholder - edit this .bat first.
  echo.
)

if "%BASE_URL%"=="https://your-relay.com/v1" (
  echo   [!] BASE_URL is still the placeholder - edit this .bat first.
  echo.
)

if "%MODEL%"=="your-model-name" (
  echo   [!] MODEL is still the placeholder - edit this .bat first.
  echo.
)

if defined PYTHON_HOME (
  if not exist "%PYTHON_HOME%\python.exe" (
    echo   [!] PYTHON_HOME is set but python.exe was not found in it.
    echo       Check the folder, or clear the value to use system python.
    echo.
  )
)

echo   Next: cd to the week folder, e.g.
echo     cd D:\your\repo\week-01\code
echo.

REM --- UTF-8, part 3/3: fix PowerShell's decoder for native EXE output -----
REM   OutputEncoding : how PowerShell DECODES bytes coming from curl.exe etc.
REM   InputEncoding  : how it DECODES what you type / paste
REM   $OutputEncoding: how it ENCODES text it PIPES INTO a native command
REM All three default to the legacy code page on 5.1. All three are process
REM local, so nothing outside this window is touched.
powershell.exe -NoExit -Command "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; [Console]::InputEncoding=[System.Text.Encoding]::UTF8; $OutputEncoding=[System.Text.Encoding]::UTF8; Write-Host ('  console encoding = ' + [Console]::OutputEncoding.WebName) -ForegroundColor Cyan; Write-Host '  Ready. Variables live only in this window.' -ForegroundColor Green"
