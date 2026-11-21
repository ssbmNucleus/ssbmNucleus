"""A donor's sound package read and written whole, so that a port's bank can gain sounds: the script file (one bank's
scripts) and the bank of samples. The last test reads the donor's own package and runs only with PORT_DONOR_ZIP."""
import io
import os
import struct
import zipfile
from pathlib import Path

import pytest

from fighter_port import voice


def test_a_script_file_is_read_and_written_as_it_was():
    scripts = [[(1, 3), (0x10, 100), (4, 15), (6, 255), (0xE, 0)], [(1, 0), (0xE, 0)]]
    sem = voice.sem_write(scripts)
    assert voice.sem_read(sem) == scripts and voice.sem_write(voice.sem_read(sem)) == sem
    # a script more: the ones before it keep their numbers and their commands
    more = voice.sem_read(voice.sem_write(scripts + [[(1, 7), (0xE, 0)]]))
    assert more[:2] == scripts and more[2] == [(1, 7), (0xE, 0)]


def channel(nibbles, fill):
    return {'loop_flag': 0, 'format': 0, 'loop': 0, 'nibbles': nibbles, 'rest': bytes(0x40 - 16), 'data': bytes([fill]) * ((nibbles + 1) // 2 + 1)}


def test_a_bank_is_read_and_written_as_it_was_and_can_gain_a_sound():
    bank = {'start': 0, 'sounds': [{'rate': 32000, 'channels': [channel(30, 1)]}, {'rate': 22050, 'channels': [channel(46, 2), channel(46, 3)]}]}
    ssm = voice.ssm_write(bank)
    assert len(ssm) % 0x20 == 0 and struct.unpack_from('>i', ssm, 8)[0] == 2
    back = voice.ssm_read(ssm)
    assert [(s['rate'], len(s['channels'])) for s in back['sounds']] == [(32000, 1), (22050, 2)]
    assert voice.ssm_write(back) == ssm
    back['sounds'].append({'rate': 32000, 'channels': [channel(14, 4)]})
    grown = voice.ssm_read(voice.ssm_write(back))
    # the sounds before it are untouched, sample for sample
    assert len(grown['sounds']) == 3 and grown['sounds'][2]['channels'][0]['data'][:4] == bytes([4]) * 4
    assert [c['data'][:c['nibbles'] // 2] for s in grown['sounds'][:2] for c in s['channels']] == \
           [c['data'][:c['nibbles'] // 2] for s in bank['sounds'] for c in s['channels']]


def test_a_sound_the_bank_gains_is_played_by_a_script_the_port_has_no_use_for():
    # a donor's bank has a big and a small form of each voice after the plain one: the same sample, lower and higher
    plain = lambda sample: [(1, sample), (16, 1), (4, 15), (6, 204), (14, 0)]
    bent = lambda sample, pitch: [(1, sample), (16, 1), (12, pitch), (4, 15), (6, 204), (14, 0)]
    scripts = [plain(0), plain(1), bent(1, 65186), bent(1, 450), plain(2), bent(2, 65186), bent(2, 450), plain(1)]
    assert voice.spare_scripts(scripts) == [2, 3, 5, 6]
    sound_zip = io.BytesIO()
    with zipfile.ZipFile(sound_zip, 'w') as z:
        z.writestr('scripts.sem', voice.sem_write(scripts))
        z.writestr('scripts.json', '["SFXa", "SFXv_b", "SFXv_bB", "SFXv_bS", "SFXv_c", "SFXv_cB", "SFXv_cS", "SFXb2"]')
    chosen = {'v_b': ('vc_x_attack01', b''), '+vc_x_009': ('vc_x_009', b''), '+se_x_special_h02': ('se_x_special_h02', b'')}
    calls = voice.calls(sound_zip.getvalue(), 19, chosen)
    # a swapped sample by its own script; each added one by a spare script, in the order chosen: all numbers the
    # donor's bank has, so the installer points every one of them at the port's own bank
    assert calls == {'vc_x_attack01': 190001, 'vc_x_009': 190002, 'se_x_special_h02': 190003}


DONOR = os.environ.get('PORT_DONOR_ZIP', '')


@pytest.mark.skipif(not (DONOR and Path(DONOR).exists()), reason='needs PORT_DONOR_ZIP')
def test_the_donors_own_package_comes_back_byte_for_byte():
    with zipfile.ZipFile(DONOR) as z:
        inner = next((n for n in z.namelist() if n.lower().endswith('sound.zip')), None)
        if inner is None:
            pytest.skip('the donor zip carries no sound package')
        with zipfile.ZipFile(io.BytesIO(z.read(inner))) as s:
            sem = s.read('scripts.sem')
            ssm = s.read(next(n for n in s.namelist() if n.lower().endswith('.ssm')))
    assert voice.sem_write(voice.sem_read(sem)) == sem
    assert voice.ssm_write(voice.ssm_read(ssm)) == ssm
