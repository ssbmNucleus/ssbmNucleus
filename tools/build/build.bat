@echo off
echo ========================================
echo Building MEX Manager Distribution
echo ========================================
echo.

REM Store project root directory for absolute paths
REM %~dp0 gives us the directory where this batch file is located (tools\build\)
REM The app (package.json, venv, utility, frontend) lives in app\ beside tools\.
set "REPO_ROOT=%~dp0..\.."
set "PROJECT_ROOT=%~dp0..\..\app"
pushd "%PROJECT_ROOT%"
set "PROJECT_ROOT=%cd%"
popd
cd /d "%PROJECT_ROOT%"

set DEBUG=electron-builder
set "PACKAGE_STAGE=%PROJECT_ROOT%\build-package-staging"
set "PACKAGE_OUTPUT=%PROJECT_ROOT%\dist-electron"

REM Release builds are signed by default. Refuse before the expensive build
REM stages if electron-builder has no usable identity. For a local test package,
REM explicitly opt in with: set NUCLEUS_ALLOW_UNSIGNED=1
set "SIGNING_OVERRIDE="
if /i "%NUCLEUS_ALLOW_UNSIGNED%"=="1" (
    echo WARNING: Building an unsigned LOCAL package because NUCLEUS_ALLOW_UNSIGNED=1.
    echo          Do not distribute this installer.
    set CSC_IDENTITY_AUTO_DISCOVERY=false
    set "SIGNING_OVERRIDE=--config.forceCodeSigning=false"
) else (
    REM CSC_IDENTITY_AUTO_DISCOVERY is read by app-builder-lib out/util/flags.js
    REM and consumed ONLY by macCodeSign.js -- it does nothing on the Windows
    REM path. It is set here purely so the value is explicit in the build log.
    set CSC_IDENTITY_AUTO_DISCOVERY=true
    REM Validate the identity electron-builder will ACTUALLY resolve
    REM (win.signtoolOptions.certificate* or WIN_CSC_LINK/CSC_LINK), not merely
    REM the presence of some cert in Cert:\CurrentUser\My, which Windows signing
    REM never consults. Otherwise this gate passes and winPackager.js throws
    REM only after every expensive stage has run.
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%REPO_ROOT%\tools\build\check_windows_signing.ps1"
    if errorlevel 1 exit /b 1
)

REM Secret preview update channel: NUCLEUS_PREVIEW_CHANNEL is a random token
REM that is baked into the PACKAGED package.json as previewChannel, and ONLY
REM for a preview build. electron/updates/updater.js then also polls
REM <platform>/preview/<token>/latest.json, which prerelease_to_r2.py
REM --channel <token> writes. A stable build must never carry it, so it is
REM refused without NUCLEUS_PREVIEW_FEATURES. The token must match
REM [A-Za-z0-9_-]{16,64} with at least one letter -- an all-digit value would
REM reach the manifest as a number. NUCLEUS_BUILD_VERSION must carry a
REM prerelease tag (0.9.0-preview.8): a preview packaged as plain 0.9.0 would
REM never see stable 0.9.0 as newer, so its testers could never move on.
REM Checked here, before the expensive stages. The patterns use \A...\z, not
REM ^...$: .NET's $ also matches before a trailing newline.
REM Kept flat on purpose: an exit /b inside a NESTED block reaches `cmd /c
REM build.bat` (ci.py) as exit code 0.
if defined NUCLEUS_PREVIEW_CHANNEL if not defined NUCLEUS_PREVIEW_FEATURES (
    echo ERROR: NUCLEUS_PREVIEW_CHANNEL is set but NUCLEUS_PREVIEW_FEATURES is not.
    echo        Only a preview build may carry the preview update channel.
    if not defined NUCLEUS_BUILD_NONINTERACTIVE pause
    exit /b 1
)
set "PREVIEW_CHANNEL_INVALID="
if defined NUCLEUS_PREVIEW_CHANNEL powershell.exe -NoProfile -Command "if ($env:NUCLEUS_PREVIEW_CHANNEL -cmatch '\A(?=[0-9_-]*[A-Za-z])[A-Za-z0-9_-]{16,64}\z') { exit 0 } else { exit 1 }" || set "PREVIEW_CHANNEL_INVALID=1"
if defined PREVIEW_CHANNEL_INVALID (
    echo ERROR: NUCLEUS_PREVIEW_CHANNEL must be 16-64 characters of A-Z a-z 0-9 _ -
    echo        including at least one letter, and nothing else - no spaces or newlines.
    if not defined NUCLEUS_BUILD_NONINTERACTIVE pause
    exit /b 1
)
set "PREVIEW_VERSION_INVALID="
if defined NUCLEUS_PREVIEW_CHANNEL powershell.exe -NoProfile -Command "if ($env:NUCLEUS_BUILD_VERSION -cmatch '\A(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)-(0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(\.(0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*\z') { exit 0 } else { exit 1 }" || set "PREVIEW_VERSION_INVALID=1"
if defined PREVIEW_VERSION_INVALID (
    echo ERROR: NUCLEUS_PREVIEW_CHANNEL needs NUCLEUS_BUILD_VERSION with a prerelease
    echo        tag, e.g. 0.9.0-preview.8, so testers move on to the stable release.
    if not defined NUCLEUS_BUILD_NONINTERACTIVE pause
    exit /b 1
)

REM Play test builds (docs/dev/PREVIEW-0.9.0.md, "Play test builds"): Play, the
REM unfinished Melee Unlocked launcher, is packaged only when asked for by name,
REM NUCLEUS_PREVIEW_FEATURES=play (comma-separate other features). It is for
REM local test builds, so it also needs a prerelease NUCLEUS_BUILD_VERSION
REM (0.9.2-play-preview.1): the release stage (ci.py) packages the tree's plain
REM version, so a stray NUCLEUS_PREVIEW_FEATURES=play fails here, not in a release.
REM Kept flat on purpose, like the checks above.
set "PLAY_PREVIEW="
if defined NUCLEUS_PREVIEW_FEATURES powershell.exe -NoProfile -Command "if (@($env:NUCLEUS_PREVIEW_FEATURES -split ',' | ForEach-Object { $_.Trim().ToLowerInvariant() }) -contains 'play') { exit 0 } else { exit 1 }" && set "PLAY_PREVIEW=1"
set "PLAY_VERSION_INVALID="
if defined PLAY_PREVIEW powershell.exe -NoProfile -Command "if ($env:NUCLEUS_BUILD_VERSION -cmatch '\A(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)-(0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)(\.(0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*\z') { exit 0 } else { exit 1 }" || set "PLAY_VERSION_INVALID=1"
if defined PLAY_VERSION_INVALID (
    echo ERROR: NUCLEUS_PREVIEW_FEATURES=play makes a Play TEST build, which needs
    echo        NUCLEUS_BUILD_VERSION with a prerelease tag, e.g. 0.9.2-play-preview.1.
    if not defined NUCLEUS_BUILD_NONINTERACTIVE pause
    exit /b 1
)
if defined PLAY_PREVIEW echo Play test build: Play ^(the Melee Unlocked launcher^) will be packaged ON, as %NUCLEUS_BUILD_VERSION%.

REM Use the project venv explicitly. The system 'python' on PATH may be a
REM different interpreter without our deps installed (Flask, etc.), which
REM produces an exe that crashes at startup with ModuleNotFoundError.
set "VENV_PYTHON=%PROJECT_ROOT%\venv\Scripts\python.exe"
if defined NUCLEUS_BUILD_PYTHON set "VENV_PYTHON=%NUCLEUS_BUILD_PYTHON%"
if not exist "%VENV_PYTHON%" (
    echo ERROR: venv not found at %VENV_PYTHON%
    echo Create it with: python -m venv venv ^&^& venv\Scripts\pip install -r requirements.txt
    if not defined NUCLEUS_BUILD_NONINTERACTIVE pause
    exit /b 1
)

REM Refuse stale interpreters and stale node_modules before freezing anything.
"%VENV_PYTHON%" "%~dp0check_build_runtimes.py" --report "%PROJECT_ROOT%\build\runtime-preflight.json"
if errorlevel 1 exit /b 1

REM Verify the venv has the runtime deps PyInstaller needs to bundle.
"%VENV_PYTHON%" -c "import flask, flask_cors, flask_socketio, PIL, numpy, yaml, psutil" 2>nul
if %errorlevel% neq 0 (
    echo ERROR: venv is missing required runtime dependencies.
    echo Run: "%VENV_PYTHON%" -m pip install -r requirements.txt
    if not defined NUCLEUS_BUILD_NONINTERACTIVE pause
    exit /b 1
)

REM Check if PyInstaller is installed in the venv (not globally).
"%VENV_PYTHON%" -c "import PyInstaller" 2>nul
if %errorlevel% neq 0 (
    echo PyInstaller not found in venv. Installing...
    "%VENV_PYTHON%" -m pip install pyinstaller
    REM Verify by re-importing rather than trusting pip's exit code (pip can
    REM exit non-zero on harmless notices like "a new release of pip is available").
    "%VENV_PYTHON%" -c "import PyInstaller" 2>nul
    REM `if errorlevel 1`, NOT `if %errorlevel%` -- inside a parenthesized
    REM block cmd expands %errorlevel% when it PARSES the block, so it would
    REM still hold the failing value that got us in here and a fresh install
    REM could never pass.
    if errorlevel 1 (
        echo ERROR: PyInstaller install failed - cannot import after pip install.
        if not defined NUCLEUS_BUILD_NONINTERACTIVE pause
        exit /b 1
    )
)

REM Force delete old build artifacts to prevent caching issues
echo Cleaning old build artifacts...
if exist "%PROJECT_ROOT%\dist" (
    rmdir /s /q "%PROJECT_ROOT%\dist"
)
if exist "%PROJECT_ROOT%\build\mex_backend" (
    rmdir /s /q "%PROJECT_ROOT%\build\mex_backend"
)
if exist "%~dp0__pycache__" (
    rmdir /s /q "%~dp0__pycache__"
)

echo.
echo [1/5] Building Python Backend...
echo ----------------------------------------
"%VENV_PYTHON%" -m PyInstaller "%~dp0mex_backend.spec" --clean --noconfirm --distpath "%PROJECT_ROOT%\dist" --workpath "%PROJECT_ROOT%\build"
if %errorlevel% neq 0 (
    echo ERROR: Python backend build failed
    if not defined NUCLEUS_BUILD_NONINTERACTIVE pause
    exit /b 1
)
"%VENV_PYTHON%" "%~dp0check_pyinstaller_warnings.py" "%PROJECT_ROOT%\build\mex_backend\warn-mex_backend.txt"
if %errorlevel% neq 0 (
    echo ERROR: PyInstaller warning inventory contains a new project-level missing import
    if not defined NUCLEUS_BUILD_NONINTERACTIVE pause
    exit /b 1
)

REM Exercise the frozen executable and its deliberately loose processor/service
REM modules without touching the developer's real LocalAppData state.
set "BUILD_SMOKE_ROOT=%PROJECT_ROOT%\build\smoke-runtime"
if exist "%BUILD_SMOKE_ROOT%" rmdir /s /q "%BUILD_SMOKE_ROOT%"
mkdir "%BUILD_SMOKE_ROOT%"
if errorlevel 1 (
    echo ERROR: Could not create isolated backend smoke-test directory
    exit /b 1
)
set "NUCLEUS_BUILD_SMOKE_ROOT=%BUILD_SMOKE_ROOT%"
REM Do not let the frozen backend borrow DLLs or Python packages from the
REM developer's tools on PATH. Its own bundle must supply those dependencies.
setlocal
set "PATH=%SystemRoot%\System32;%SystemRoot%"
set "PYTHONHOME="
set "PYTHONPATH="
set "VIRTUAL_ENV="
set "CONDA_PREFIX="
pushd "%BUILD_SMOKE_ROOT%"
"%PROJECT_ROOT%\dist\mex_backend.exe" --build-smoke-test
set "BUILD_SMOKE_EXIT=%ERRORLEVEL%"
popd
endlocal & set "BUILD_SMOKE_EXIT=%BUILD_SMOKE_EXIT%"
set "NUCLEUS_BUILD_SMOKE_ROOT="
if exist "%BUILD_SMOKE_ROOT%" rmdir /s /q "%BUILD_SMOKE_ROOT%"
set "BUILD_SMOKE_ROOT="
if not "%BUILD_SMOKE_EXIT%"=="0" (
    echo ERROR: Frozen backend smoke test failed
    exit /b %BUILD_SMOKE_EXIT%
)
set "BUILD_SMOKE_EXIT="

echo.
echo [2/5] Fetching the pinned MexCLI + HSDRawViewer (prebuilt, win-x64)...
echo ----------------------------------------
REM The m-ex / HSDLib forks publish self-contained builds as GitHub Releases;
REM app\utility\mex.manifest.json and hsdlib.manifest.json pin the tag + sha256.
REM mexcli.exe, codes.gct and seed_codes.ini arrive together in the mex zip.
"%VENV_PYTHON%" "%REPO_ROOT%\tools\build\fetch_native.py" all --platform win-x64
if %errorlevel% neq 0 (
    echo ERROR: could not fetch the native toolchain ^(see tools\build\fetch_native.py --help^)
    if not defined NUCLEUS_BUILD_NONINTERACTIVE pause
    exit /b 1
)
if exist "%PROJECT_ROOT%\dist-backend\mex" rmdir /s /q "%PROJECT_ROOT%\dist-backend\mex"
if exist "%PROJECT_ROOT%\dist-backend\hsdraw" rmdir /s /q "%PROJECT_ROOT%\dist-backend\hsdraw"
echo Staging dist-backend\mex and dist-backend\hsdraw...
xcopy /E /I /Y /Q "%PROJECT_ROOT%\utility\mex\win-x64" "%PROJECT_ROOT%\dist-backend\mex" >nul
if %errorlevel% neq 0 (
    echo ERROR: could not stage MexCLI
    exit /b 1
)
xcopy /E /I /Y /Q "%PROJECT_ROOT%\utility\hsdraw\win-x64" "%PROJECT_ROOT%\dist-backend\hsdraw" >nul
if %errorlevel% neq 0 (
    echo ERROR: could not stage HSDRawViewer
    exit /b 1
)
REM seed_codes.ini (NOT codes.ini) is the community code library that seeds the
REM vault Codes section: a codes.ini beside mexcli.exe would make `mexcli create`
REM enable all 49 codes on every new project. The release zip already names it so.
if not exist "%PROJECT_ROOT%\dist-backend\mex\codes.gct" (
    echo ERROR: codes.gct missing from the fetched MexCLI -- mexcli cannot create projects without it
    exit /b 1
)

echo Copying Sheik vanilla CSP assets (PNGs only - never the ISO-derived DATs)...
xcopy /E /I /Y "%PROJECT_ROOT%\utility\assets\vanilla\Sheik\*.png" "%PROJECT_ROOT%\dist-backend\mex\utility\assets\vanilla\Sheik"
cd /d "%PROJECT_ROOT%"

echo.
echo [3/5] Checking the bundled stage model parser...
echo ----------------------------------------
dotnet build "%REPO_ROOT%\tools\ingame\stage-groups-smoke\StageGroupsSmoke.csproj" -c Release --artifacts-path "%PROJECT_ROOT%\scratch\stage-group-smoke" -p:HsdRawAssembly="%PROJECT_ROOT%\utility\hsdraw\win-x64\HSDRaw.dll" -p:NuGetAudit=false --verbosity quiet
if %errorlevel% neq 0 (
    echo ERROR: Stage parser smoke test build failed ^(needs the .NET 8 SDK on the build machine^)
    exit /b 1
)
dotnet "%PROJECT_ROOT%\scratch\stage-group-smoke\bin\StageGroupsSmoke\release\StageGroupsSmoke.dll"
if %errorlevel% neq 0 (
    echo ERROR: Bundled stage parser failed the split-table regression
    exit /b 1
)

echo [4/5] Building React Frontend...
echo ----------------------------------------
REM The assistant (Randall's chat + the app MCP) is in the frontend bundle exactly
REM when its release gate ships in this build: by default since 0.9.0
REM (backend/core/gates.py, packaged_off=False), or when a preview asks for it with
REM NUCLEUS_PREVIEW_FEATURES=assistant while it is held back. ship_guard.py gate is
REM the one rule -- mex_backend.spec, the stage and the frozen smoke apply it too.
REM VITE_ASSISTANT_PREVIEW builds the tab and panel into the bundle
REM (frontend/src/shared/config/features.js; the name is from the 0.9.0 previews).
REM The ship guard refuses a stage whose bundle and gate disagree either way.
REM Kept flat on purpose (see the preview-channel checks above).
set "VITE_ASSISTANT_PREVIEW="
"%VENV_PYTHON%" "%~dp0ship_guard.py" gate assistant
if not errorlevel 1 set "VITE_ASSISTANT_PREVIEW=1"
if defined VITE_ASSISTANT_PREVIEW echo The assistant chat and the app MCP are ENABLED in the frontend bundle ^(the Tracker coach stays off^).
if defined VITE_ASSISTANT_PREVIEW echo   Packaged backend policy ^(electron/main.js, backend/core/gates.py, docs/dev/PREVIEW-0.9.0.md^):
if defined VITE_ASSISTANT_PREVIEW echo     NUCLEUS_RANDALL=0   NUCLEUS_BUILD_COMMIT=0   NUCLEUS_DELIVERY=0   NUCLEUS_WISH_SUBMIT=0
if defined VITE_ASSISTANT_PREVIEW echo   The backend logs the same switches at startup ^("Feature switches: ..."^).
if not defined VITE_ASSISTANT_PREVIEW echo The assistant is LEFT OUT of this build ^(its release gate is closed^).
REM Randall's model import runs rigswap's package (utility/rigswap/app), which ships
REM with the assistant on every platform; its Python and Blender are a download the
REM user starts in Settings (utility/model_import_tools.json). fetch_rigswap.py does
REM nothing when the tree already holds the pinned commit; it needs a rigswap clone
REM (RIGSWAP_REPO, else %USERPROFILE%\projects\rigswap) only to build it.
if not defined VITE_ASSISTANT_PREVIEW goto :rigswap_done
"%VENV_PYTHON%" "%REPO_ROOT%\tools\build\fetch_rigswap.py"
if errorlevel 1 (
    echo ERROR: could not build utility\rigswap\app ^(see tools\build\fetch_rigswap.py --help^)
    if not defined NUCLEUS_BUILD_NONINTERACTIVE pause
    exit /b 1
)
:rigswap_done
REM Play (the Nucleus game client's launcher) follows its gate the same way. It is
REM packaged_off, so `ship_guard.py gate play` passes only for a Play test build
REM (NUCLEUS_PREVIEW_FEATURES=play, version checked at the top) or once
REM backend/core/gates.py PLAY_IN_STABLE is True; then
REM VITE_PLAY_PREVIEW builds Play mode (the wordmark's third mode) and the PlayApp chunk into the bundle
REM (frontend/src/shared/config/features.js), mex_backend.spec freezes the play
REM package, and main.js sets NUCLEUS_PLAY=1 for this package. In every other
REM build it is cleared here and the ship guard refuses a PlayApp chunk.
set "VITE_PLAY_PREVIEW="
"%VENV_PYTHON%" "%~dp0ship_guard.py" gate play
if not errorlevel 1 set "VITE_PLAY_PREVIEW=1"
REM Play in a stable build (`gate play --stable`: PLAY_IN_STABLE is True): the
REM packaged manifest gets releaseFeatures=play (stage 5), which main.js reads.
set "PLAY_STABLE="
"%VENV_PYTHON%" "%~dp0ship_guard.py" gate play --stable
if not errorlevel 1 set "PLAY_STABLE=1"
if defined VITE_PLAY_PREVIEW echo Play is ENABLED in this build ^(frontend bundle, backend package, NUCLEUS_PLAY=1^).
if not defined VITE_PLAY_PREVIEW echo Play is LEFT OUT of this build ^(its release gate is closed^).
if not exist "%PROJECT_ROOT%\frontend" (
    echo ERROR: Cannot find frontend directory at %PROJECT_ROOT%\frontend
    if not defined NUCLEUS_BUILD_NONINTERACTIVE pause
    exit /b 1
)
cd /d "%PROJECT_ROOT%\frontend"
call npm run build
if %errorlevel% neq 0 (
    echo ERROR: Frontend build failed
    cd /d "%PROJECT_ROOT%"
    if not defined NUCLEUS_BUILD_NONINTERACTIVE pause
    exit /b 1
)
cd /d "%PROJECT_ROOT%"

echo.
echo [5/5] Creating Electron Installer...
echo ----------------------------------------
set "ELECTRON_VERSION="
for /f %%I in ('node -p "require(\"./node_modules/electron/package.json\").version"') do set "ELECTRON_VERSION=%%I"
if not defined ELECTRON_VERSION (
    echo ERROR: Unable to determine installed Electron version
    if not defined NUCLEUS_BUILD_NONINTERACTIVE pause
    exit /b 1
)

REM Note: previously wiped %LOCALAPPDATA%\electron-builder\Cache\winCodeSign here
REM "to avoid symlink issues" - that actually CAUSED the problem by forcing
REM re-extraction every build. winCodeSign contains macOS symlinks that need
REM SeCreateSymbolicLinkPrivilege to extract. Real fix: enable Windows
REM Developer Mode (Settings -> Privacy & security -> For developers).
REM The cache is keyed by winCodeSign version, which only changes when
REM electron-builder is upgraded, so it's safe to reuse.

echo Preparing clean packaging stage...
REM Staging, scrubbing and the leak scan all live in tools/build/ship_guard.py,
REM driven by tools/build/ship_rules.json. build-linux.sh and build-macos.sh call
REM the exact same two commands, so the three platforms cannot drift apart again --
REM which is precisely how the 0.7.0 AppImage shipped retail costume DATs that this
REM script had been stripping for months. Do NOT re-inline copy/delete steps here;
REM add them to ship_rules.json.
"%VENV_PYTHON%" "%~dp0ship_guard.py" stage --platform win --stage "%PACKAGE_STAGE%"
if %errorlevel% neq 0 (
    echo.
    echo ERROR: staging failed - refusing to package. See output above.
    if not defined NUCLEUS_BUILD_NONINTERACTIVE pause
    exit /b 1
)

echo Testing ISO selection and drag-and-drop with the staged desktop bridge...
set "NUCLEUS_ISO_IMPORT_PRELOAD_PATH=%PACKAGE_STAGE%\electron\preload.js"
node "%REPO_ROOT%\tools\ingame\iso-import-smoke.cjs"
set "ISO_IMPORT_CHECK_EXIT=%ERRORLEVEL%"
set "NUCLEUS_ISO_IMPORT_PRELOAD_PATH="
if not "%ISO_IMPORT_CHECK_EXIT%"=="0" (
    echo ERROR: ISO import check failed - refusing to package.
    if not defined NUCLEUS_BUILD_NONINTERACTIVE pause
    exit /b 1
)

if exist "%PACKAGE_OUTPUT%" (
    rmdir /s /q "%PACKAGE_OUTPUT%"
)

echo.
echo Scanning the build for bundled Nintendo/ISO-derived game data...
"%VENV_PYTHON%" "%~dp0ship_guard.py" scan --stage "%PACKAGE_STAGE%" --backend "%PROJECT_ROOT%\dist\mex_backend.exe" --report "%PROJECT_ROOT%\ship-report.txt"
if %errorlevel% neq 0 (
    echo.
    echo ERROR: ship guard failed - refusing to package. See output above.
    if not defined NUCLEUS_BUILD_NONINTERACTIVE pause
    exit /b 1
)
echo.

REM Preview builds: set NUCLEUS_BUILD_VERSION (e.g. 0.8.4-preview.20260910.6)
REM to stamp the packaged app -- which also names the installer and drives the
REM in-app version via app.getVersion() -- WITHOUT editing any package.json in
REM the tree, so a shared working copy never holds a throwaway version.
set "VERSION_OVERRIDE="
if defined NUCLEUS_BUILD_VERSION set "VERSION_OVERRIDE=--config.extraMetadata.version=%NUCLEUS_BUILD_VERSION%"
if defined NUCLEUS_BUILD_VERSION echo Packaging as version %NUCLEUS_BUILD_VERSION%

REM The electron half of NUCLEUS_PREVIEW_FEATURES (see stage 4). Written into
REM the PACKAGED package.json only, so the tree's manifests stay release-clean;
REM main.js reads the feature names in previewFeatures and opens NUCLEUS_ASSISTANT
REM ('assistant') or NUCLEUS_PLAY ('play') for that package alone (the Tracker
REM coach and the write paths stay off).
set "PREVIEW_FEATURES_OVERRIDE="
if defined NUCLEUS_PREVIEW_FEATURES set "PREVIEW_FEATURES_OVERRIDE=--config.extraMetadata.previewFeatures=%NUCLEUS_PREVIEW_FEATURES%"
if defined NUCLEUS_PREVIEW_FEATURES echo Packaging with preview features: %NUCLEUS_PREVIEW_FEATURES%

REM The packaged_off gates a stable build opens all the same (gates.py
REM release_features, asked in stage 4): Play once PLAY_IN_STABLE is True.
set "RELEASE_FEATURES_OVERRIDE="
if defined PLAY_STABLE set "RELEASE_FEATURES_OVERRIDE=--config.extraMetadata.releaseFeatures=play"
if defined PLAY_STABLE echo Packaging with release features: play

REM The secret preview update channel (validated at the top). Never echoed.
set "PREVIEW_CHANNEL_OVERRIDE="
if defined NUCLEUS_PREVIEW_CHANNEL set "PREVIEW_CHANNEL_OVERRIDE=--config.extraMetadata.previewChannel=%NUCLEUS_PREVIEW_CHANNEL%"
if defined NUCLEUS_PREVIEW_CHANNEL echo Packaging with the secret preview update channel.

call "%PROJECT_ROOT%\node_modules\.bin\electron-builder.cmd" --win --projectDir "%PACKAGE_STAGE%" "--config.directories.output=%PACKAGE_OUTPUT%" "--config.electronVersion=%ELECTRON_VERSION%" %SIGNING_OVERRIDE% %VERSION_OVERRIDE% %PREVIEW_FEATURES_OVERRIDE% %RELEASE_FEATURES_OVERRIDE% %PREVIEW_CHANNEL_OVERRIDE%
if %errorlevel% neq 0 (
    echo ERROR: Electron packaging failed
    if not defined NUCLEUS_BUILD_NONINTERACTIVE pause
    exit /b 1
)

REM Verify the executable that actually goes into the installer, not just its lockfile.
"%VENV_PYTHON%" "%~dp0check_build_runtimes.py" --electron-exe "%PACKAGE_OUTPUT%\win-unpacked\SSBM Nucleus.exe" --report "%PROJECT_ROOT%\build\runtime-packaged.json"
if errorlevel 1 exit /b 1

REM Preview builds: prove the packaged manifest carries exactly the requested
REM preview channel (the token as a string, or none). A token the CLI coerced
REM would otherwise ship a test build that silently never updates.
if defined NUCLEUS_PREVIEW_FEATURES node "%REPO_ROOT%\tools\build\check_preview_channel.js" "%PACKAGE_OUTPUT%\win-unpacked\resources"
if errorlevel 1 (
    if not defined NUCLEUS_BUILD_NONINTERACTIVE pause
    exit /b 1
)

echo.
echo Copying installer to project root...
REM Record exactly what THIS run produced. The root wrapper reads this file
REM instead of listing every *.exe in the project root, so a stale installer
REM from an older version can never be reported as build output.
if not exist "%PROJECT_ROOT%\build" mkdir "%PROJECT_ROOT%\build"
set "INSTALLER_MANIFEST=%PROJECT_ROOT%\build\last_installers.txt"
del /q "%INSTALLER_MANIFEST%" 2>nul
set "FOUND_PACKAGED_INSTALLER="
for %%F in ("%PACKAGE_OUTPUT%\*.exe") do (
    if exist "%%~fF" (
        copy /Y "%%~fF" "%PROJECT_ROOT%\"
        if errorlevel 1 (
            echo ERROR: Failed to copy newly built installer %%~nxF
            if not defined NUCLEUS_BUILD_NONINTERACTIVE pause
            exit /b 1
        )
        >>"%INSTALLER_MANIFEST%" echo %PROJECT_ROOT%\%%~nxF
        set "FOUND_PACKAGED_INSTALLER=1"
    )
)
if not defined FOUND_PACKAGED_INSTALLER (
    echo ERROR: Electron packaging returned success but produced no new installer.
    echo Existing project-root .exe files do not count as build output.
    if not defined NUCLEUS_BUILD_NONINTERACTIVE pause
    exit /b 1
)

echo.
if /i "%NUCLEUS_KEEP_BUILD_ARTIFACTS%"=="1" goto :build_complete
echo Cleaning up build artifacts...
rmdir /s /q "%PROJECT_ROOT%\dist"
rmdir /s /q "%PROJECT_ROOT%\dist-backend"
rmdir /s /q "%PROJECT_ROOT%\dist-electron"
if exist "%PACKAGE_STAGE%" (
    rmdir /s /q "%PACKAGE_STAGE%"
)

:build_complete
echo.
echo ========================================
echo Build Complete!
echo ========================================
echo.
type "%INSTALLER_MANIFEST%" 2>nul
echo.
if not defined NUCLEUS_BUILD_NONINTERACTIVE pause
goto :eof
