# No shell-built command strings: replay paths may contain spaces or metacharacters.
& node (Join-Path $PSScriptRoot 'run.mjs') @args
exit $LASTEXITCODE
