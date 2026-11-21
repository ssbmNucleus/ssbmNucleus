"""Stable identities shared by the Rivals reader and native branch bindings."""
import hashlib
import re


def branch_stem(attack, window):
    """Stable clip name for a conditional path, independent of character or window ordering."""
    label = re.sub(r'[^a-z0-9]+', '_', f'{attack}_{window}'.lower()).strip('_')
    digest = hashlib.sha256(f'{attack}\0{window}'.encode()).hexdigest()[:8]
    return f'd04branch_{label}_{digest}'


