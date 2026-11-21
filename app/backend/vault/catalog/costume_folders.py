"""
Folder rows in a character's vault skin list: finding a folder, the folder a
position falls in, and the skin order the Vault shows (folder members grouped
under their folder, headers dropped).
"""


def find_folder_in_skins(skins, folder_id):
    """Find a folder by ID in the skins array."""
    for i, item in enumerate(skins):
        if item.get('type') == 'folder' and item.get('id') == folder_id:
            return item, i
    return None, -1


def get_folder_id_at_position(skins, position):
    """Determine folder membership based on position."""
    for i in range(position - 1, -1, -1):
        item = skins[i]
        if item.get('type') == 'folder':
            return item['id']
        if item.get('folder_id'):
            return item['folder_id']
        return None
    return None


def order_skins_like_vault(skins):
    """Return the non-folder skins in the SAME visual order the vault shows them.

    The vault (viewer buildDisplayList) pulls every foldered skin *under* its
    folder entry -- which can sit anywhere in the array -- so grouped skins
    display together, while the raw ``skins`` list leaves those members
    scattered at their original positions. The install page's "Available to
    Import" list is flat (it shows no folders), so we flatten to a plain list
    but keep the vault's order, which is what makes the two screens agree.

    Folder headers are dropped; every real skin is returned exactly once, in
    vault order. Skins the vault never shows (hidden Nana entries, or members
    whose folder was deleted) are appended afterward in raw order so the
    returned SET is identical to a plain folder-skipping walk -- no skin is
    silently dropped (the Ice Climbers pairing lookup depends on that).
    """
    folder_members = {}  # folder_id -> [skins, in array order]
    for s in skins:
        if not isinstance(s, dict):
            continue
        if s.get('type') == 'folder':
            folder_members.setdefault(s.get('id'), [])
        elif s.get('folder_id'):
            folder_members.setdefault(s.get('folder_id'), []).append(s)

    ordered = []
    placed = set()  # id() of skins already emitted
    for s in skins:
        if not isinstance(s, dict):
            continue
        if s.get('type') == 'folder':
            for member in folder_members.get(s.get('id'), []):
                if id(member) not in placed:
                    ordered.append(member)
                    placed.add(id(member))
        elif not s.get('folder_id'):
            ordered.append(s)
            placed.add(id(s))
        # else: folder member -- emitted under its folder above

    # Hidden / orphaned skins (never shown by the vault) still have to be
    # returned; append them in raw order after the vault-ordered skins.
    for s in skins:
        if isinstance(s, dict) and s.get('type') != 'folder' and id(s) not in placed:
            ordered.append(s)
            placed.add(id(s))

    return ordered
