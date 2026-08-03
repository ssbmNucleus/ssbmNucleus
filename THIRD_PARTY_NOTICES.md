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

### Pillow (PIL Fork)
- **License**: HPND (Historical Permission Notice and Disclaimer)
- **Copyright**: Copyright © 1997-2011 by Secret Labs AB, Copyright © 1995-2011 by Fredrik Lundh
- **Repository**: https://github.com/python-pillow/Pillow

### PyYAML
- **License**: MIT
- **Copyright**: Copyright (c) 2017-2021 Ingy döt Net, Copyright (c) 2006-2016 Kirill Simonov
- **Repository**: https://github.com/yaml/pyyaml

## .NET / C# Dependencies

### HSDLib / HSDRaw / HSDRawViewer
- **License**: MIT
- **Copyright**: Copyright (c) 2021 Ploaj
- **Repository**: https://github.com/Ploaj/HSDLib
- **Description**: Library for working with HAL DAT files
- **Note**: Used for CSP generation and model/texture work via HSDRawViewer

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

### DotNetZip (Ionic.Zip.Reduced)
- **License**: Ms-PL (Microsoft Public License)
- **Copyright**: Copyright (c) 2006-2011 Dino Chiesa
- **Repository**: https://github.com/DinoChiesa/DotNetZip
- **Note**: Contains managed ZLIB code derived from jzlib, under a BSD-3-Clause license.

### Be.Windows.Forms.HexBox
- **License**: MIT
- **Copyright**: Copyright (c) 2011 Bernhard Elbl
- **Repository**: https://github.com/Pkcs11Admin/Be.HexEditor

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

### wit (Wiimms ISO Tools)
- **License**: GPL-2.0
- **Copyright**: Copyright (c) Dirk Clemens (Wiimm)
- **Source**: https://wit.wiimm.de/
- **Note**: Distributed as an unmodified binary and invoked as a separate process.
  Full license text: `tools/gpl-2.0.txt`. Source is available from the URL above.

### xdelta3
- **License**: Apache-2.0
- **Copyright**: Copyright (c) Joshua MacDonald
- **Repository**: https://github.com/jmacd/xdelta
- **Note**: Version 3.1.0, distributed as an unmodified binary.

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
- **Note**: No license is published by the upstream project.

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
  `utility/MexManager/tools/GCILibPatcher`.

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
