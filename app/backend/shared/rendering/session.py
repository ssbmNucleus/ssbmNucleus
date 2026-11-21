"""
session.py -- a programmatic client for HSDRawViewer's --stream WebSocket
protocol, so an agent (or any script) can drive the same machinery the Skin
Creator UI uses: list/fetch/replace textures, reposition the camera, pose
animations, grab rendered frames, and export the edited DAT.

One ViewerSession = one HSDRawViewer process + one WebSocket connection.
The server pushes binary JPEG frames continuously (we keep only the latest)
and answers JSON commands with typed JSON replies; requests here are
serialized (one in flight) which matches how the UI uses it.

Protocol 2 (docs/dev/VIEWER_STREAMING.md): a viewer that announces protocolVersion 2
lists the messages it handles in its `capabilities` message (`supports`). Only such a
viewer is sent the in-place colour edits (`apply_colour_messages`), the texture batch
(`update_textures`) and the model swap (`load_dat`); an older viewer (the pinned
release before them, the Linux/Mac headless builds) gets what it always got, and
every caller keeps its restart path as the fallback.

Camera note: the stream protocol is DELTA-based (deltaRotX/deltaRotY are
added, deltaZoom multiplies scale, deltaX/deltaY pan). Deltas apply exactly
and in order over TCP, so we mirror the math locally -- seeded from the
server's initial `info` message -- which gives callers absolute positioning
(`set_camera(rot_y=90)`) without a server-side protocol change.
"""

import json
import math
import subprocess
import uuid

from core.child_procs import own
import threading
import time
import urllib.request
from base64 import b64decode, b64encode

try:
    import websocket  # websocket-client -- optional: only the skin lab needs it
except ImportError:
    websocket = None

REQUEST_TIMEOUT = 30.0
# One updateTextures message carries at most this much base64 (the viewer refuses a
# message over 32 MiB); a bigger batch goes as several messages.
BATCH_BYTES = 16 * 1024 * 1024
# The in-place colour edits: request type -> reply type.
COLOUR_REPLIES = {'setVertexColors': 'vertexColorsSet', 'setAnimationColors': 'animationColorsSet',
                  'setLightColors': 'lightColorsSet'}
# Between health polls while the renderer starts: a refused loopback GET costs nothing,
# and the 0.4 s it was rounded every Skin/Stage Lab open up by as much (0.2 s on average).
HEALTH_POLL_SECONDS = 0.1


class ViewerSessionError(RuntimeError):
    pass


class ViewerSession:
    def __init__(self, exe, port, dat_file, logs_path=None, scene_file=None,
                 aj_file=None, data_file=None, subprocess_kwargs=None, frame_fps=10,
                 startup_timeout=40.0):
        if websocket is None:
            raise ViewerSessionError(
                "The 'websocket-client' package is not installed in the backend's "
                "Python environment (pip install websocket-client).")
        self.port = port
        self.closed = False
        # The socket reader ended (socket closed or failed) while the child may
        # still run: no frame or reply will ever arrive again.
        self.disconnected = False
        # What a reopen in place (`reopen`) passes again: the start-up's companion files.
        self.dat_file, self.scene_file, self.aj_file, self.data_file = dat_file, scene_file, aj_file, data_file
        self._send_lock = threading.Lock()      # websocket-client send isn't thread-safe
        self._request_lock = threading.Lock()   # one command in flight at a time
        self._replies = {}                      # msg type -> (threading.Event, payload)
        self._replies_lock = threading.Lock()
        self._frame = None                      # latest binary JPEG frame
        self._frame_seq = 0
        self._frame_cond = threading.Condition()
        self.info = None
        self.capabilities = None                # the viewer's `capabilities` message (None: a pre-protocol viewer)
        self.camera = None                     # tracked absolute state (degrees for rot)
        self.textures = []                      # cached list (no thumbnails)
        # getFullTexture replies, by index. The renderer builds its texture list once
        # at start-up and a texture's readback changes only when that texture is
        # written through updateTexture (which drops it here), so a second read of
        # an unwritten texture returns exactly what the first did -- without the
        # renderer PNG-encoding it again (10-20 ms a texture; a whole stage reads 60).
        self._readback = {}

        cmd = [str(exe), '--stream', str(port), str(dat_file)]
        # positional args: logs path must be present to pass scene/aj after it
        cmd.append(str(logs_path) if logs_path else '')
        cmd.append(str(scene_file) if scene_file else '')
        if aj_file:
            cmd.append(str(aj_file))
            # fighter-data dat (ftData: model-part lookup table + subaction
            # scripts) -> per-animation mesh-part visibility. Positional, so it
            # only follows a present aj_file (and is useless without one).
            if data_file:
                cmd.append(str(data_file))
        self.process = own(subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **(subprocess_kwargs or {})))

        try:
            self._wait_http_ready(startup_timeout)
            self.ws = websocket.create_connection(
                f'ws://localhost:{port}/', timeout=10)
            self.ws.settimeout(5)
            self._reader = threading.Thread(target=self._read_loop, daemon=True)
            self._reader.start()
            self._wait_info(timeout=15.0)
            # throttle the frame stream; we only ever read the latest frame
            self._send({'type': 'fps', 'value': int(frame_fps)})
            self._load_texture_list()
        except Exception:
            self.close()
            raise

    # ------------------------------------------------------------------ #
    # process / connection plumbing                                       #
    # ------------------------------------------------------------------ #
    def _wait_http_ready(self, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise ViewerSessionError(
                    f'viewer process exited during startup (code {self.process.returncode})')
            try:
                req = urllib.request.urlopen(f'http://localhost:{self.port}/', timeout=1)
                if req.status == 200:
                    return
            except Exception:
                pass
            time.sleep(HEALTH_POLL_SECONDS)
        raise ViewerSessionError('viewer did not become ready in time')

    def _read_loop(self):
        while not self.closed:
            try:
                opcode, data = self.ws.recv_data()
            except websocket.WebSocketTimeoutException:
                continue
            except Exception:
                break
            if opcode == websocket.ABNF.OPCODE_BINARY:
                with self._frame_cond:
                    self._frame = data
                    self._frame_seq += 1
                    self._frame_cond.notify_all()
            elif opcode == websocket.ABNF.OPCODE_TEXT:
                try:
                    msg = json.loads(data)
                except Exception:
                    continue
                mtype = msg.get('type')
                if not mtype:
                    continue
                with self._replies_lock:
                    waiter = self._replies.get(mtype)
                if waiter:
                    waiter[1] = msg
                    waiter[0].set()
                elif mtype == 'info':
                    self.info = msg
                elif mtype == 'capabilities':
                    self.capabilities = msg
            elif opcode == websocket.ABNF.OPCODE_CLOSE:
                break
        # Nothing reads the socket from here on: wake everyone waiting on it.
        self.disconnected = True
        with self._frame_cond:
            self._frame_cond.notify_all()
        with self._replies_lock:
            for waiter in self._replies.values():
                waiter[0].set()

    def _wait_info(self, timeout):
        # `info` arrives unsolicited right after connect
        deadline = time.time() + timeout
        while self.info is None and time.time() < deadline:
            time.sleep(0.05)
        if self.info is None:
            raise ViewerSessionError('no info message from viewer')
        cam = self.info.get('camera') or {}
        self.camera = {
            'rotX': float(cam.get('rotX', 0.0)),
            'rotY': float(cam.get('rotY', 0.0)),
            'scale': float(cam.get('scale', 1.0)),
            'x': float(cam.get('x', 0.0)),
            'y': float(cam.get('y', 0.0)),
        }

    def _send(self, msg):
        with self._send_lock:
            self.ws.send(json.dumps(msg))

    def _request(self, msg, reply_type, timeout=REQUEST_TIMEOUT):
        """Send a command and wait for its typed reply."""
        with self._request_lock:
            event = threading.Event()
            waiter = [event, None]
            with self._replies_lock:
                self._replies[reply_type] = waiter
            try:
                self._send(msg)
                if not event.wait(timeout):
                    raise ViewerSessionError(f'timed out waiting for {reply_type}')
                if waiter[1] is None and self.disconnected:
                    raise ViewerSessionError('the viewer connection closed')
                return waiter[1]
            finally:
                with self._replies_lock:
                    self._replies.pop(reply_type, None)

    def supports(self, message):
        """True when the running viewer announced protocol 2 or later and lists `message`."""
        caps = self.capabilities or {}
        version = caps.get('protocolVersion')
        return type(version) is int and version >= 2 and message in (caps.get('messages') or ())

    def _checked(self, msg, reply_type, timeout=REQUEST_TIMEOUT):
        """A protocol-2 request (it carries a request id) whose reply must report success."""
        msg = {**msg, 'requestId': uuid.uuid4().hex}
        reply = self._request(msg, reply_type, timeout)
        if reply.get('requestId') not in (None, msg['requestId']):
            raise ViewerSessionError(f'{reply_type} answered another request')
        if not reply.get('success'):
            raise ViewerSessionError(reply.get('error') or f'{msg["type"]} failed')
        return reply

    def alive(self):
        return not self.closed and not self.disconnected and self.process.poll() is None

    def close(self):
        self.closed = True
        try:
            if getattr(self, 'ws', None):
                self.ws.close()
        except Exception:
            pass
        try:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # textures                                                            #
    # ------------------------------------------------------------------ #
    def _load_texture_list(self):
        reply = self._request({'type': 'getTextures'}, 'textureList')
        # matAnim/animates: MatAnim swap frames (blink textures etc.) the
        # viewer appends after the material textures; `animates` is the
        # material texture index the swap bank animates (-1 if unlinked).
        # extra: textures from non-rendered extra JOBJ roots (e.g.
        # Jigglypuff's alt-costume hats), appended after the matanim entries.
        self.textures = [
            {'index': t.get('index'), 'name': t.get('name'),
             'width': t.get('width'), 'height': t.get('height'),
             'matAnim': bool(t.get('matAnim')),
             'animates': t.get('animates', -1),
             'extra': bool(t.get('extra'))}
            for t in (reply.get('textures') or [])
        ]

    def get_full_texture(self, index):
        """Full-resolution texture as PNG bytes (read once until the texture is written)."""
        index = int(index)
        cached = self._readback.get(index)
        if cached is not None:
            return cached
        reply = self._request({'type': 'getFullTexture', 'index': index},
                              'fullTexture')
        if reply.get('error') or not reply.get('data'):
            raise ViewerSessionError(reply.get('error') or 'no texture data')
        data = b64decode(reply['data'])
        self._readback[index] = data
        return data

    def remember_textures(self, written):
        """Readback for textures just written with exactly these PNG bytes ({index: bytes}): the renderer
        shows their pixels, so the next read returns these bytes without asking it (a look that puts the
        textures back, randall/recolor/texture_inspection.identify)."""
        for index, data in written.items():
            self._readback[int(index)] = data

    def material_command(self, command):
        reply = self._request(command, 'materials')
        if not reply.get('success'):
            raise ViewerSessionError(reply.get('error') or 'The viewer could not update materials')
        return reply

    def get_uv_layout(self):
        """Per-texture UV layout: for every texture that geometry samples,
        the triangles as [u0,v0,u1,v1,u2,v2, x0,y0,z0, x1,y1,z1, x2,y2,z2]
        (UVs in wrap units, positions posed world space) plus wrapS/wrapT.
        Used by projection-mode composites (compose.composite_project)."""
        reply = self._request({'type': 'getUVLayout'}, 'uvLayout', timeout=60.0)
        if reply.get('error'):
            raise ViewerSessionError(reply['error'])
        return reply.get('textures') or []

    def update_texture(self, index, png_bytes):
        """Replace a texture (PNG bytes; caller is responsible for sizing)."""
        # Dropped before sending: whatever the reply, the next read asks the renderer.
        self._readback.pop(int(index), None)
        reply = self._request(
            {'type': 'updateTexture', 'index': int(index),
             'data': b64encode(png_bytes).decode('ascii')},
            'textureUpdated')
        if not reply.get('success'):
            raise ViewerSessionError(reply.get('error') or 'texture update failed')
        # Material compositing can enlarge tiny canvases. Keep inspection data
        # consistent with the pixels actually submitted to the renderer.
        from PIL import Image
        from io import BytesIO
        with Image.open(BytesIO(png_bytes)) as image:
            for texture in self.textures:
                if texture['index'] == int(index):
                    texture.update(width=image.width, height=image.height)

    def update_textures(self, updated):
        """Replace several textures ({index: PNG bytes}, applied in order). A protocol-2 viewer takes
        them as updateTextures batches (decoded and encoded in parallel, applied in one render-thread
        pass, one reply); an older one one updateTexture at a time, as before."""
        if not self.supports('updateTextures'):
            for index, png in updated.items():
                self.update_texture(index, png)
            return
        batch, size = [], 0
        for index, png in updated.items():
            data = b64encode(png).decode('ascii')
            if batch and size + len(data) > BATCH_BYTES:
                self._texture_batch(batch)
                batch, size = [], 0
            batch.append((int(index), png, data))
            size += len(data)
        if batch:
            self._texture_batch(batch)

    def _texture_batch(self, batch):
        for index, _, _ in batch:
            self._readback.pop(index, None)
        self._checked({'type': 'updateTextures',
                       'textures': [{'index': index, 'data': data} for index, _, data in batch]},
                      'texturesUpdated', timeout=60.0)
        from PIL import Image
        from io import BytesIO
        sizes = {}
        for index, png, _ in batch:
            with Image.open(BytesIO(png)) as image:
                sizes[index] = (image.width, image.height)
        for texture in self.textures:
            if texture['index'] in sizes:
                texture.update(width=sizes[texture['index']][0], height=sizes[texture['index']][1])

    # ------------------------------------------------------------------ #
    # in-place colour edits and model swap (protocol 2)                   #
    # ------------------------------------------------------------------ #

    def apply_colour_messages(self, messages):
        """setVertexColors / setAnimationColors / setLightColors messages (dat_colours.colour_messages),
        each applied and acknowledged in order. Raises ViewerSessionError on the first failure: the
        caller then shows the edited file another way (model_colours.reload)."""
        for message in messages:
            reply_type = COLOUR_REPLIES.get(message.get('type'))
            if reply_type is None or not self.supports(message['type']):
                raise ViewerSessionError(f'The viewer cannot take {message.get("type")} in place')
            self._checked(message, reply_type, timeout=60.0)

    def load_dat(self, dat_file, scene_file=None, aj_file=None, data_file=None, reframe=None):
        """Replace the model in the running viewer (loadDat): window, GL context and camera stay
        (unless `reframe`), the animation being watched stays when the new file has it. Raises
        ViewerSessionError when it fails; the viewer may then show nothing, so restart it."""
        msg = {'type': 'loadDat', 'datFile': str(dat_file), 'sceneFile': str(scene_file or ''),
               'ajFile': str(aj_file or ''), 'dataFile': str(data_file or '')}
        if reframe is not None:
            msg['reframe'] = bool(reframe)
        reply = self._checked(msg, 'datLoaded', timeout=60.0)
        self.dat_file, self.scene_file, self.aj_file, self.data_file = dat_file, scene_file, aj_file, data_file
        self._readback = {}
        self.textures = [
            {'index': t.get('index'), 'name': t.get('name'), 'width': t.get('width'), 'height': t.get('height'),
             'matAnim': bool(t.get('matAnim')), 'animates': t.get('animates', -1), 'extra': bool(t.get('extra'))}
            for t in (reply.get('textures') or [])]
        if reply.get('reframed'):
            cam = reply.get('camera') or {}
            self.camera = {'rotX': float(cam.get('rotX', 0.0)), 'rotY': float(cam.get('rotY', 0.0)),
                           'scale': float(cam.get('scale', 1.0)), 'x': float(cam.get('x', 0.0)),
                           'y': float(cam.get('y', 0.0))}
        return reply

    def reopen(self, dat_file):
        """load_dat with the companion files this renderer was started (or last reopened) with."""
        return self.load_dat(dat_file, self.scene_file, self.aj_file, self.data_file)

    # ------------------------------------------------------------------ #
    # camera (absolute via tracked deltas)                                #
    # ------------------------------------------------------------------ #
    def set_camera(self, rot_x=None, rot_y=None, scale=None, x=None, y=None):
        """Absolute camera positioning. Rotations in degrees, scale ~ zoom
        (bigger = closer), x/y pan in world units."""
        msg = {'type': 'camera'}
        if rot_x is not None:
            msg['deltaRotX'] = float(rot_x) - self.camera['rotX']
            self.camera['rotX'] = float(rot_x)
        if rot_y is not None:
            msg['deltaRotY'] = float(rot_y) - self.camera['rotY']
            self.camera['rotY'] = float(rot_y)
        if scale is not None:
            target = max(0.1, min(1000.0, float(scale)))
            if self.camera['scale'] > 0:
                msg['deltaZoom'] = target / self.camera['scale'] - 1.0
            self.camera['scale'] = target
        if x is not None:
            msg['deltaX'] = float(x) - self.camera['x']
            self.camera['x'] = float(x)
        if y is not None:
            msg['deltaY'] = float(y) - self.camera['y']
            self.camera['y'] = float(y)
        if len(msg) > 1:
            self._send(msg)
        return dict(self.camera)

    # ------------------------------------------------------------------ #
    # frames                                                              #
    # ------------------------------------------------------------------ #
    def grab_frame(self, fresh=2, timeout=5.0):
        """The current rendered view as JPEG bytes. Waits for `fresh` NEW
        frames so recent camera/texture changes are actually in the shot."""
        with self._frame_cond:
            target = self._frame_seq + max(0, int(fresh))
            deadline = time.time() + timeout
            while self._frame_seq < target:
                if self.disconnected:
                    raise ViewerSessionError('the viewer connection closed')
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                self._frame_cond.wait(remaining)
            if self._frame is None:
                raise ViewerSessionError('no frame received from viewer yet')
            return self._frame

    def resize(self, width, height):
        self._send({'type': 'resize',
                    'width': int(width), 'height': int(height)})

    # ------------------------------------------------------------------ #
    # animation                                                           #
    # ------------------------------------------------------------------ #

    def set_anim_frame(self, frame):
        self._send({'type': 'animSetFrame', 'frame': float(frame)})

    def set_anim_playing(self, playing):
        self._send({'type': 'animPlay' if playing else 'animPause'})

    def playing_frame(self, timeout=5.0):
        """Where a playing animation is: animPlay (nothing changes while it plays) answers with the
        animation's state -> {'frame', 'frameCount', 'playing', 'speed'}. A paused one would start."""
        return self._request({'type': 'animPlay'}, 'animFrame', timeout)

    # ------------------------------------------------------------------ #
    # export                                                              #
    # ------------------------------------------------------------------ #
    def export_dat(self):
        """The current DAT -- including every updateTexture applied -- as bytes."""
        reply = self._request({'type': 'exportDat'}, 'exportDat', timeout=60.0)
        if not reply.get('success') or not reply.get('data'):
            raise ViewerSessionError(reply.get('error') or 'export failed')
        return b64decode(reply['data'])
