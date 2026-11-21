"""The fighter table the model import reads: the app's fighter names and their Pl codes.

Randall's model import (``randall/model_import/chat``: the fighters rigswap targets, the names a user picks) and
its vault save (``randall/model_import/studio/finish.py``: the costume code) both read it.
"""

# keys = the vault/vanilla-assets folder names (what the UI sends);
# long-name aliases map onto the same canonical entries.
_CHAR_TO_CODE = {
    'Fox': 'Fx', 'Falco': 'Fc', 'C. Falcon': 'Ca', 'DK': 'Dk',
    'Dr. Mario': 'Dr', 'Ganondorf': 'Gn', 'Kirby': 'Kb', 'Bowser': 'Kp',
    'Link': 'Lk', 'Luigi': 'Lg', 'Mario': 'Mr', 'Marth': 'Ms',
    'Mewtwo': 'Mt', 'Ness': 'Ns', 'Peach': 'Pe', 'Pichu': 'Pc',
    'Pikachu': 'Pk', 'Jigglypuff': 'Pr', 'Roy': 'Fe', 'Samus': 'Ss',
    'Yoshi': 'Ys', 'Zelda': 'Zd', 'Young Link': 'Cl',
    'Mr. Game & Watch': 'Gw', 'Ice Climbers': 'Pp', 'Sheik': 'Sk',
}
_CHAR_ALIASES = {'Captain Falcon': 'C. Falcon', 'Donkey Kong': 'DK'}


def _canonical(character):
    """Vault/assets folder name for whatever name variant came in."""
    return _CHAR_ALIASES.get(character, character)
