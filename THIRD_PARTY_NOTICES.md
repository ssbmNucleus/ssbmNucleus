# Third-Party Notices

This project uses the following open source software:

## Node.js / JavaScript Dependencies

### Electron
- **License**: MIT
- **Copyright**: Copyright (c) Electron contributors
- **Repository**: https://github.com/electron/electron

### Vite
- **License**: MIT
- **Copyright**: Copyright (c) 2019-present, Yuxi (Evan) You and Vite contributors
- **Repository**: https://github.com/vitejs/vite

### React
- **License**: MIT
- **Copyright**: Copyright (c) Meta Platforms, Inc. and affiliates
- **Repository**: https://github.com/facebook/react

### Socket.IO
- **License**: MIT
- **Copyright**: Copyright (c) 2014-present Automattic, Inc.
- **Repository**: https://github.com/socketio/socket.io

### Concurrently
- **License**: MIT
- **Copyright**: Copyright (c) 2015 Kimmo Brunfeldt
- **Repository**: https://github.com/open-cli-tools/concurrently

### electron-builder
- **License**: MIT
- **Copyright**: Copyright (c) 2015 Loopline Systems
- **Repository**: https://github.com/electron-userland/electron-builder

### qrcode-generator
- **License**: MIT
- **Copyright**: Copyright (c) 2009 Kazuhiko Arase
- **Repository**: https://github.com/kazuhikoarase/qrcode-generator

### unicode-emoji-json (emoji names and groups in the Friends emoji picker)
- **License**: MIT
- **Copyright**: Copyright (c) 2019 Mu-An Chiou
- **Repository**: https://github.com/muan/unicode-emoji-json

### emojilib (emoji search keywords in the Friends emoji picker)
- **License**: MIT
- **Copyright**: Copyright (c) 2014 Mu-An Chiou
- **Repository**: https://github.com/muan/emojilib

## Python Dependencies

### Flask
- **License**: BSD-3-Clause
- **Copyright**: Copyright 2010 Pallets
- **Repository**: https://github.com/pallets/flask

### Flask-CORS
- **License**: MIT
- **Copyright**: Copyright (c) 2013 Cory Dolphin
- **Repository**: https://github.com/corydolphin/flask-cors

### Flask-SocketIO
- **License**: MIT
- **Copyright**: Copyright (c) 2014 Miguel Grinberg
- **Repository**: https://github.com/miguelgrinberg/Flask-SocketIO

### python-socketio
- **License**: MIT
- **Copyright**: Copyright (c) 2015 Miguel Grinberg
- **Repository**: https://github.com/miguelgrinberg/python-socketio

### NumPy
- **License**: BSD-3-Clause
- **Copyright**: Copyright (c) 2005-2023, NumPy Developers
- **Repository**: https://github.com/numpy/numpy

### SciPy
- **License**: BSD-3-Clause
- **Copyright**: Copyright (c) 2001-2002 Enthought, Inc. 2003, SciPy Developers
- **Repository**: https://github.com/scipy/scipy

### Pillow (PIL Fork)
- **License**: HPND (Historical Permission Notice and Disclaimer)
- **Copyright**: Copyright © 1997-2011 by Secret Labs AB, Copyright © 1995-2011 by Fredrik Lundh
- **Repository**: https://github.com/python-pillow/Pillow

### PyYAML
- **License**: MIT
- **Copyright**: Copyright (c) 2017-2021 Ingy döt Net, Copyright (c) 2006-2016 Kirill Simonov
- **Repository**: https://github.com/yaml/pyyaml

### rarfile
- **License**: ISC
- **Copyright**: Copyright (c) Marko Kreen
- **Repository**: https://github.com/markokr/rarfile
- **Note**: Pure-Python driver that invokes the bundled UnRAR binary; it contains
  no RAR decoder of its own.

### trimesh
- **License**: MIT
- **Copyright**: Copyright (c) 2023 Michael Dawson-Haggerty
- **Repository**: https://github.com/mikedh/trimesh

### pyfqmr
- **License**: MIT
- **Copyright**: Copyright (c) 2020 Kramer84
- **Repository**: https://github.com/Kramer84/pyfqmr-Fast-Quadric-Mesh-Reduction

### windows-capture
- **License**: MIT
- **Copyright**: Copyright (c) 2023 NiiightmareXD
- **Repository**: https://github.com/NiiightmareXD/windows-capture

### OpenCV (opencv-python)
- **License**: Apache-2.0 (the OpenCV library); MIT (the opencv-python packaging)
- **Copyright**: OpenCV contributors; Copyright (c) Olli-Pekka Heinisuo (packaging)
- **Repository**: https://github.com/opencv/opencv-python
- **Note**: Bundled in the Windows build because windows-capture imports it.
  The opencv-python wheel also redistributes FFmpeg (LGPL-2.1) as a separate,
  unmodified DLL (`opencv_videoio_ffmpeg*.dll`); the full license texts are
  in that project's `LICENSE-3RD-PARTY.txt`.

## .NET / C# Dependencies

### HSDLib / HSDRaw / HSDRawViewer
- **License**: MIT
- **Copyright**: Copyright (c) 2021 Ploaj
- **Repository**: https://github.com/Ploaj/HSDLib
- **Description**: Library for working with HAL DAT files
- **Note**: Used for CSP generation and model/texture work via HSDRawViewer.
  We distribute a prebuilt, modified build of our fork, https://github.com/sc00ppp/ssbmNucleus-hsdlib
  (release tag pinned in `utility/hsdlib.manifest.json`; the complete source is in that repository).

### Avalonia UI (MexManager GUI)
- **License**: MIT
- **Copyright**: Copyright (c) The Avalonia Project
- **Repository**: https://github.com/AvaloniaUI/Avalonia

### SixLabors.ImageSharp (+ Drawing, Fonts)
- **License**: Six Labors Split License, Version 1.0
- **Copyright**: Copyright (c) Six Labors
- **Repository**: https://github.com/SixLabors/ImageSharp
- **Note**: Used under the Apache-2.0 terms of the split license. Distributed as a dependency of MexCLI.

### IONET
- **License**: GPL-3.0
- **Copyright**: Copyright (c) Ploaj
- **Repository**: https://github.com/Ploaj/IONET
- **Description**: 3D model import/export (DAE, OBJ, SMD, FBX, MayaAnim)
- **Note**: Linked into HSDRawViewer and HSDRawHeadless. See "Licensing status" at the end of this file.

### OpenTK
- **License**: MIT
- **Copyright**: Copyright (c) 2006-2019 Stefanos Apostolopoulos for the Open Toolkit project
- **Repository**: https://github.com/opentk/opentk

### CSCore
- **License**: Ms-PL (Microsoft Public License)
- **Copyright**: Copyright (c) 2017 Florian R.
- **Repository**: https://github.com/filoe/cscore
- **Note**: The `CSCore.Ffmpeg` subproject is excluded from this license grant and is **not** distributed with this software.

### NVorbis
- **Version**: 0.10.5
- **License**: MIT
- **Copyright**: Copyright (c) 2020 Andrew Ward
- **Repository**: https://github.com/NVorbis/NVorbis
- **Description**: Managed streaming decoder for Ogg Vorbis audio imports

### NLayer
- **Version**: 2.0.1
- **License**: MIT
- **Copyright**: Copyright (c) NLayer contributors
- **Repository**: https://github.com/naudio/NLayer
- **Description**: Cross-platform managed MP3 decoder

### SharpJaad
- **Version**: 0.1.1
- **License**: MIT
- **Copyright**: Copyright (c) SharpJaad contributors
- **Repository**: https://github.com/jimm98y/SharpJaad
- **Description**: Cross-platform managed MP4 demultiplexer and AAC decoder for M4A imports (`SharpJaad` and `SharpJaad.AAC` packages)

### VGAudio
- **License**: MIT
- **Copyright**: Copyright (c) 2016 Alex Barney
- **Repository**: https://github.com/Thealexbarney/VGAudio

### Be.Windows.Forms.HexBox.Net8
- **License**: MIT
- **Copyright**: Copyright (c) 2011-2025 Bernhard Elbl
- **Authors**: The Melding Wars, harborsiem
- **Repository**: https://github.com/harborsiem/Be.HexEditor
- **Note**: .NET 8 repackaging of Be.Windows.Forms.HexBox (`Be.Windows.Forms.HexBox.Net8` 2.1.0), used by HSDRawViewer's property inspector.

### DockPanel Suite (WeifenLuo.WinFormsUI.Docking)
- **License**: MIT
- **Copyright**: Copyright (c) Weifen Luo and contributors
- **Repository**: https://github.com/dockpanelsuite/dockpanelsuite

### YamlDotNet
- **License**: MIT
- **Copyright**: Copyright (c) Antoine Aubry and contributors
- **Repository**: https://github.com/aaubry/YamlDotNet

### PropertyModels / Avalonia.PropertyGrid
- **License**: MIT
- **Copyright**: Copyright (c) bodong
- **Repository**: https://github.com/bodong1987/Avalonia.PropertyGrid

### GLFW
- **License**: Zlib
- **Copyright**: Copyright (c) Marcus Geelnard and Camilla Löwy
- **Repository**: https://github.com/glfw/glfw
- **Note**: Distributed as `glfw3.dll` via OpenTK.

## Bundled Executables (invoked as separate processes)

These are shipped alongside the application and run as subprocesses. They are not
linked into the application.

### Blender
- **License**: GPL-2.0-or-later (Blender's own code; the distributed binary as a
  whole is under GPL-3.0-or-later terms, because it includes libraries licensed
  GPL-3.0-compatible-only — see Blender's `copyright.txt` and `license/license.md`)
- **Copyright**: Copyright (c) Blender Foundation and the Blender Developers
- **Repository**: https://projects.blender.org/blender/blender
- **Source**: https://download.blender.org/source/ — the corresponding source for
  this exact release is `blender-4.2.23.tar.xz` in that directory.
- **Note**: Version 4.2.23 LTS, the official portable Windows x64 build
  (`blender-4.2.23-windows-x64.zip`, sha256
  `82e791475779a7342424a480bdde9a20b43710da9264c60346125aa16cd910cb`),
  distributed unmodified and invoked as a separate process with
  `--background --factory-startup --disable-autoexec`. It is never linked into
  the application. Ships at `utility/blender/` and is used by the model-import
  pipeline for bone-heat skin weighting, Collada normalization and the shaded
  fit-review renders. Debug symbols, UI translations and the Cycles renderer's
  script tree are deleted from the shipped copy; no file is patched. Full
  license texts ship beside the binary: `utility/blender/copyright.txt`,
  `utility/blender/license/spdx/GPL-2.0-or-later.txt`,
  `utility/blender/license/spdx/GPL-3.0-or-later.txt`, and
  `utility/blender/license/license.md` for Blender's own bundled dependencies.

### FFmpeg
- **License**: GPL-3.0-or-later. FFmpeg is configured with `--enable-gpl
  --enable-version3` and statically linked with GPL libraries — x264, x265,
  Xvid, davs2, xavs2, vid.stab, Rubber Band, libdvdread, libdvdnav, libdvdcss
  and FFTW (all GPL-2.0-or-later) — and with libraries that require the
  version 3 terms: GMP and aribb24 (LGPL-3.0-or-later) and OpenCORE AMR
  (Apache-2.0). It is also compiled against the AviSynth+ and frei0r plugin
  headers; those two are loaded at run time only if the user has installed
  them, and neither ships with this application.
- **Copyright**: Copyright (c) the FFmpeg developers and the authors of the
  libraries above; Windows build by BtbN's FFmpeg-Builds
- **Repository**: https://github.com/FFmpeg/FFmpeg
- **Build recipe**: https://github.com/BtbN/FFmpeg-Builds at commit
  `6c9aec5fc9a72ec3abedd1fa84db141fa18cf52b` (release
  `autobuild-2026-09-30-13-08`), built with `./build.sh win64 gpl 9.0` from
  FFmpeg commit `2a571b606854520cf89804d8030c8b328e621689` (branch
  `release/9.0`).
- **Source**: https://github.com/FFmpeg/FFmpeg/commit/2a571b606854520cf89804d8030c8b328e621689
  for FFmpeg itself. The source of every library linked into the binary is
  pinned, by upstream URL and commit, in the build recipe above
  (`scripts.d/` at that commit), which rebuilds this exact binary.
- **Note**: Version 9.0.2 (`ffmpeg version n9.0.2-17-g2a571b6068-20260930`),
  the static Windows x64 GPL build
  (`ffmpeg-n9.0.2-17-g2a571b6068-win64-gpl-9.0.zip`, sha256
  `a0e45723c72141975f51d8666302e614711745f3102b704ca3f82c897a58d278`),
  distributed unmodified and invoked as a separate process to encode game
  recordings. It is never linked into the application. Ships at
  `utility/ffmpeg/bin/ffmpeg.exe`; ffplay, ffprobe, the docs and presets are
  deleted from the shipped copy and no file is patched. The GPL-3.0 license
  text ships beside the binary: `utility/ffmpeg/LICENSE.txt`.

### xdelta3
- **License**: Apache-2.0
- **Copyright**: Copyright (c) Joshua MacDonald
- **Repository**: https://github.com/jmacd/xdelta
- **Note**: Version 3.1.0, distributed as unmodified binaries and invoked as a
  separate process. The Windows build ships at `utility/xdelta/xdelta3.exe`;
  the Linux build at `utility/xdelta-linux/xdelta3` is compiled without source
  modification from the upstream v3.1.0 release and statically linked.

### UnRAR
- **License**: UnRAR freeware license (see `utility/unrar*/license.txt`)
- **Copyright**: Copyright (c) 1993-2025 Alexander Roshal
- **Source**: https://www.rarlab.com/rar_add.htm
- **Note**: Version 7.12, distributed as unmodified official binaries and invoked
  as a separate process to read `.rar` mod archives. Ships at
  `utility/unrar/UnRAR.exe` (Windows), `utility/unrar-linux/unrar` and
  `utility/unrar-mac/unrar`, each alongside the license text the author requires
  to accompany it. The license permits free distribution of UnRAR inside other
  software packages, and forbids using RAR/UnRAR code to re-create the RAR
  compression algorithm — Nucleus only decompresses, and does not create RAR
  archives.

## Slippi Ecosystem

### slippilab
- **License**: MIT
- **Copyright**: Copyright (c) Frank Borden
- **Repository**: https://github.com/frankborden/slippilab
- **Note**: Per-character animation data is bundled with this application and
  supplies the 2D character geometry for the in-app clip viewer.

### slippi-js
- **License**: LGPL-3.0
- **Copyright**: Copyright (c) Project Slippi
- **Repository**: https://github.com/project-slippi/slippi-js
- **Note**: The combo-detection state machine in this application is a port of
  slippi-js's, including its reset-window timing and action-state ranges.

### peppi / peppi-py
- **License**: MIT (peppi). No license is published for the peppi-py bindings.
- **Repository**: https://github.com/hohav/peppi
- **Note**: Used to parse `.slp` replay files.

### Slippi playback Dolphin (Ishiiruka)
- **License**: GPL-2.0
- **Repository**: https://github.com/project-slippi/Ishiiruka
- **Note**: **Not distributed with this application.** Replay playback launches
  the copy installed by the user's own Slippi Launcher.

### Dolphin Emulator
- **License**: GPL-2.0
- **Repository**: https://github.com/dolphin-emu/dolphin
- **Note**: Not distributed with this application. Slippi's playback build is
  derived from Dolphin.

## Melee Modding Community Projects

### Changing Color Effects in Melee
- **Source**: https://smashboards.com/threads/changing-color-effects-in-melee.313177/
- **Note**: Source for the effect-color offsets used by Nucleus.

### m-ex
- **Author**: Akaneia / UnclePunch
- **Repository**: https://github.com/akaneia/m-ex
- **Note**: Community Melee extension framework. No license is published by the
  upstream project.

### MexManager / MexCLI
- **Author**: Ploaj
- **Repository**: https://github.com/Ploaj/MexManager
- **Note**: No license is published by the upstream project. We distribute a prebuilt build of our
  fork, https://github.com/sc00ppp/ssbmNucleus-mex (release tag pinned in `utility/mex.manifest.json`;
  the source is in that repository).

### MeleeMedia
- **Author**: Ploaj
- **Repository**: https://github.com/Ploaj/MeleeMedia
- **Note**: Audio/media conversion for Melee formats. No license is published by
  the upstream project. Its own dependencies CSCore and VGAudio are listed above;
  the GPL-licensed AForge.NET listed in MeleeMedia's README is **not** distributed
  with this software.

### GCILib
- **Author**: Ploaj (attributed)
- **Note**: GameCube file-format library, distributed as a prebuilt DLL and
  referenced by mexLib/MexManager. No published repository or license was found.
  The bundled DLL carries a reproducible local IL patch that opens source ISOs
  read-only with shared-read access; the developer tool and instructions live in
  `tools/GCILibPatcher` in the ssbmNucleus-mex fork repository.

## Licensing status

Two notes recorded honestly rather than glossed:

1. **IONET is GPL-3.0 and is linked into HSDRawViewer/HSDRawHeadless** (compile-time
   reference, not a subprocess). Resolving what that requires for the distributed
   HSDRawViewer binary is tracked and unresolved. It does not affect the separately
   licensed components of this application, which invoke HSDRawViewer as an external
   process.
2. **Several Melee community upstreams publish no license at all** (m-ex,
   MexManager/MexCLI, MeleeMedia, GCILib, and the peppi-py bindings). They are used
   and redistributed here by community convention, not by an express grant.
3. **slippi-js is LGPL-3.0 and the combo-detection code here is a port of it.** A
   translation is a derivative work, so that portion carries slippi-js's terms.
   This is tracked and unresolved.

## Game Assets

### Super Smash Bros. Melee Assets
- **Copyright**: © Nintendo / HAL Laboratory, Inc.
- **Note**: Vanilla character portraits, stock icons, and other game assets are property of Nintendo. This software is designed for use with legally obtained copies of Super Smash Bros. Melee.
- **Distribution**: No Nintendo game data is distributed with this software. Vanilla assets are extracted at first run from the user's own ISO, on the user's machine.

## Additional Tools

### DAT Processing Tools
- **Origin**: Adapted from the author's own [meleeWebsite](https://github.com/davidfeira/meleeWebsite) project
- **Description**: Character detection and DAT file processing utilities

---

## License Texts

### MIT License

```
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### BSD-3-Clause License

```
Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice,
   this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its contributors
   may be used to endorse or promote products derived from this software
   without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

---

*This file was last updated: November 2024*
