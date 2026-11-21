"""Compile a generated C text with the host's compiler and run it (the tests of the generated specials code)."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest


def compile_and_run(tmp_path,source):
    (tmp_path/'special.c').write_text(source)
    vc=Path('C:/Program Files/Microsoft Visual Studio/2022/Community/VC/Auxiliary/Build/vcvars64.bat')
    cc=shutil.which('cc') or shutil.which('gcc')
    if vc.is_file():
        batch=tmp_path/'run.cmd'
        batch.write_text('@echo off\ncall "'+str(vc)+'" >nul\nif errorlevel 1 exit /b 1\n'
                         'cl /nologo /TC /std:c11 special.c /Fe:special.exe\nif errorlevel 1 exit /b 1\nspecial.exe\nexit /b %errorlevel%\n')
        result=subprocess.run([os.environ['COMSPEC'],'/d','/c',str(batch)],cwd=tmp_path,capture_output=True,text=True,timeout=45)
    elif cc:
        binary=tmp_path/'special'
        result=subprocess.run([cc,'-std=c11','special.c','-o',str(binary),'-lm'],cwd=tmp_path,capture_output=True,text=True,timeout=30)
        assert result.returncode==0,result.stdout+result.stderr
        result=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10)
    else:pytest.skip('requires host C compiler')
    assert result.returncode==0,result.stdout+result.stderr
