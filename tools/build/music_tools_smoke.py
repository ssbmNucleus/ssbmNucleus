"""Exercise the exact MexCLI being packaged, using generated audio only."""
import argparse
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import wave


class MusicToolsError(RuntimeError):
    pass


def verify_music_tools(executable, scratch=None):
    executable = Path(executable).resolve()
    if not executable.is_file():
        raise MusicToolsError(f'MexCLI missing: {executable}')

    def run(command, *args, success=True):
        try:
            result = subprocess.run(
                [str(executable), command, *map(str, args)],
                capture_output=True, text=True, timeout=60,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )
            data = json.loads(result.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            raise MusicToolsError(f'{command}: MexCLI did not return JSON; rebuild the native tools') from exc
        if not isinstance(data, dict) or data.get('success') is not success or (result.returncode == 0) != success:
            raise MusicToolsError(f'{command} failed: {data}')
        return data

    def pcm(path):
        with wave.open(str(path), 'rb') as audio:
            return audio.getparams(), audio.readframes(audio.getnframes())

    with tempfile.TemporaryDirectory(prefix='music-tools-smoke-', dir=scratch) as temp:
        root = Path(temp)
        wav, hps = root / 'source.wav', root / 'source.hps'
        with wave.open(str(wav), 'wb') as audio:
            audio.setparams((2, 2, 32000, 0, 'NONE', 'not compressed'))
            audio.writeframes(b''.join(struct.pack('<hh',
                int(8000 * math.sin(i * 2 * math.pi * 440 / 32000)),
                int(6000 * math.sin(i * 2 * math.pi * 660 / 32000)),
            ) for i in range(32000)))
        run('audio-to-hps', wav, hps)
        info = run('hps-loop-info', hps)
        if info.get('frequency') != 32000 or not 990 <= info.get('duration_ms', 0) <= 1010:
            raise MusicToolsError(f'Unexpected loop metadata: {info}')
        before = root / 'before.wav'
        run('hps-to-wav', hps, before)
        original = pcm(before)
        if original[0].nchannels != 2 or original[0].nframes < 31680:
            raise MusicToolsError('Audio import lost channels or samples')
        for index, start in enumerate((345.67, 0, 712.3)):
            edited = root / f'edited-{index}.hps'
            run('hps-set-loop', hps, edited, start)
            saved = run('hps-loop-info', edited)
            if saved.get('loop_enabled') is not True or abs(saved.get('loop_start_ms', -100) - start) >= 3:
                raise MusicToolsError(f'Saved loop did not round-trip: {saved}')
            decoded = root / f'edited-{index}.wav'
            run('hps-to-wav', edited, decoded)
            if pcm(decoded) != original:
                raise MusicToolsError('Saving a loop changed the decoded audio')
            hps = edited
        rejected = root / 'invalid.hps'
        run('hps-set-loop', hps, rejected, saved['duration_ms'], success=False)
        if rejected.exists():
            raise MusicToolsError('Invalid loop wrote an output file')


def verify_stage_music_tools(stage, platform):
    relative = {
        'win': 'dist-backend/mex/mexcli.exe',
        'linux': 'dist-backend/mex-linux/mexcli',
        'mac': 'dist-backend/mex-mac/mexcli',
    }[platform]
    executable = Path(stage) / relative
    verify_music_tools(executable, scratch=stage)
    print(f'Music tools passed: {executable} (import, preview, loop save/reopen, unchanged PCM)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mexcli', type=Path)
    parser.add_argument('--scratch', type=Path)
    args = parser.parse_args()
    try:
        verify_music_tools(args.mexcli, scratch=args.scratch)
    except MusicToolsError as exc:
        parser.exit(1, f'Music tools check failed: {exc}\n')
    print('Music tools passed: import, preview, loop save/reopen, unchanged PCM')
