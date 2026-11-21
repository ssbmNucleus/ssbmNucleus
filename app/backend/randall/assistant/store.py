"""Local chat history, kept separately from Tracker and credentials."""
import json
import sqlite3
import time
import uuid
from urllib.parse import quote
from core import config
from .recipes import chat_task, task_id


def _connect():
    directory = config.STORAGE_PATH / 'assistant'
    directory.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(directory / 'chats.db', timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE IF NOT EXISTS chats (id TEXT PRIMARY KEY, title TEXT, messages TEXT, updated REAL)')
    # The task a chat was started as (recipes.LAUNCHABLE), so history rows can show
    # it without parsing every transcript. Added in place: chats.db predates it,
    # and a missing column must not cost anyone their history. Read back through
    # recipes.task_id: a task that is no longer a starting point (find_mod,
    # menu_background) reads as none, so its chat opens as an ordinary chat.
    if 'task' not in {row['name'] for row in conn.execute('PRAGMA table_info(chats)')}:
        try:
            conn.execute('ALTER TABLE chats ADD COLUMN task TEXT')
        except sqlite3.OperationalError as exc:
            # Only "another connection added it between the check and the
            # ALTER" is benign. A locked or read-only database must surface
            # here, not as a missing column on the next query.
            if 'duplicate column' not in str(exc).lower():
                conn.close()
                raise
    conn.execute('CREATE TABLE IF NOT EXISTS pending_inputs (position INTEGER PRIMARY KEY AUTOINCREMENT, '
                 'id TEXT UNIQUE NOT NULL, chat_id TEXT NOT NULL, content TEXT NOT NULL, context TEXT NOT NULL, mode TEXT NOT NULL)')
    return conn


def pending_inputs(chat_id):
    conn = _connect()
    try:
        return [{**dict(row), 'context': json.loads(row['context'])} for row in conn.execute(
            'SELECT id,content,context,mode FROM pending_inputs WHERE chat_id=? '
            "ORDER BY CASE mode WHEN 'steer' THEN 0 ELSE 1 END,position", (chat_id,))]
    finally:
        conn.close()


def add_input(chat_id, input_id, content, context, mode):
    conn = _connect()
    try:
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            chat = conn.execute('SELECT messages FROM chats WHERE id=?', (chat_id,)).fetchone()
            if not chat:
                raise ValueError('Conversation not found.')
            existing = conn.execute('SELECT chat_id,content,context,mode FROM pending_inputs WHERE id=?', (input_id,)).fetchone()
            if existing:
                if (existing['chat_id'], existing['content'], json.loads(existing['context']), existing['mode']) != (chat_id, content, context, mode):
                    raise ValueError('That message ID is already in use.')
                return
            if any(m.get('id') == input_id and m['role'] == 'user' for m in json.loads(chat['messages'])):
                return  # Retrying a lost response must not send a second copy.
            if conn.execute('SELECT COUNT(*) FROM pending_inputs WHERE chat_id=?', (chat_id,)).fetchone()[0] >= 20:
                raise ValueError('The queue holds up to 20 messages. Edit or remove one first.')
            conn.execute('INSERT INTO pending_inputs (id,chat_id,content,context,mode) VALUES (?,?,?,?,?)',
                         (input_id, chat_id, content, json.dumps(context), mode))
    finally:
        conn.close()


def change_input(chat_id, input_id, *, content=None, mode=None, remove=False):
    conn = _connect()
    try:
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM pending_inputs WHERE chat_id=? AND id=?', (chat_id, input_id)).fetchone()
            if not row:
                raise RuntimeError('This message has already started or was removed. Refresh the conversation.')
            if remove:
                conn.execute('DELETE FROM pending_inputs WHERE id=?', (input_id,))
            else:
                conn.execute('UPDATE pending_inputs SET content=?,mode=? WHERE id=?',
                             (content if content is not None else row['content'], mode or row['mode'], input_id))
    finally:
        conn.close()


def deliver_inputs(chat_id, input_ids, messages, answer):
    """Move a pending input into the transcript in one durable transaction."""
    conn = _connect()
    try:
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            users = []
            for input_id in input_ids:
                row = conn.execute('SELECT * FROM pending_inputs WHERE chat_id=? AND id=?', (chat_id, input_id)).fetchone()
                if not row:
                    raise RuntimeError('This message has already started or was removed.')
                users.append({'id': row['id'], 'role': 'user', 'content': row['content'],
                              'context': json.loads(row['context']), 'input_kind': row['mode'],
                              'at': time.time()})
            conn.execute('UPDATE chats SET messages=?,updated=? WHERE id=?',
                         (json.dumps([*messages, *users, answer]), time.time(), chat_id))
            conn.executemany('DELETE FROM pending_inputs WHERE id=?', [(input_id,) for input_id in input_ids])
            return users
    finally:
        conn.close()


def change_inputs(chat_id, input_ids, *, remove=False, mode='steer'):
    """Send/Clear the visible queue as one operation, ignoring already-delivered IDs."""
    conn = _connect()
    try:
        with conn:
            if remove:
                conn.executemany('DELETE FROM pending_inputs WHERE chat_id=? AND id=?', [(chat_id, ident) for ident in input_ids])
            else:
                conn.executemany('UPDATE pending_inputs SET mode=? WHERE chat_id=? AND id=?',
                                 [(mode, chat_id, ident) for ident in input_ids])
    finally:
        conn.close()


def save(chat_id, messages):
    chat_id = chat_id or uuid.uuid4().hex
    title = next((m['content'][:64] for m in messages if m['role'] == 'user'), 'New conversation')
    conn = _connect()
    try:
        with conn:
            # The task is filled once and never changed: COALESCE keeps a stored
            # task over whatever this save would derive, so one chat stays one task.
            conn.execute('INSERT INTO chats (id,title,messages,updated,task) VALUES (?,?,?,?,?) '
                         'ON CONFLICT(id) DO UPDATE SET title=excluded.title,messages=excluded.messages,'
                         'updated=excluded.updated,task=COALESCE(chats.task,excluded.task)',
                         (chat_id, title, json.dumps(messages), time.time(), chat_task(messages)))
    finally:
        conn.close()
    return chat_id


def get(chat_id):
    conn = _connect()
    try:
        row = conn.execute('SELECT * FROM chats WHERE id=?', (chat_id,)).fetchone()
        if not row:
            return None
        messages = json.loads(row['messages'])
        # The undo receipt commits with the vault edit; refresh its state here
        # so reopening a chat and continuing it cannot report stale success.
        from core.metadata import load_metadata
        metadata = load_metadata(default={}) or {}
        actions = metadata.get('_assistant_actions', {})
        from .vault_items import _item
        skins = {(character, skin.get('id')): skin
                 for character, info in metadata.get('characters', {}).items()
                 for skin in info.get('skins', []) if skin.get('type') != 'folder'}
        for message in messages:
            for tool in message.get('tools', []):
                result = tool.get('result') or {}
                stage_results = [result, *(row.get('result') or {} for row in result.get('downloads', []))]
                for stage_result in stage_results:
                    for item in stage_result.get('imported_stages', []):
                        variant = next((v for v in metadata.get('stages', {}).get(item['folder'], {}).get('variants', [])
                                        if v.get('id') == item['id']), None)
                        item['unavailable'] = variant is None
                        if variant:
                            screenshot = variant.get('screenshot_filename')
                            item['image'] = (f"/storage/das/{quote(item['folder'], safe='')}/{quote(screenshot, safe='')}"
                                             if screenshot else item.get('fallback_image'))
                # Cards refer to live vault items. Repairs/renames should be
                # visible when reopening a receipt, without rewriting history.
                for item in [*result.get('items', []), *result.get('imported_items', [])]:
                    skin = skins.get((item.get('character'), item.get('id')))
                    if skin is None or skin.get('visible') is False:
                        item.update(unavailable=True, image=None, stock_image=None)
                        continue
                    current = _item(item['character'], skin)
                    for field in ('name', 'variant', 'image', 'stock_image', 'costume_code'):
                        item[field] = current.get(field)
                    item['unavailable'] = False
                action = actions.get(result.get('action_id'))
                if action and action.get('undone'):
                    result['undone'] = True
                    result['note'] = 'This organization was undone; original folder memberships were restored.'
        return {'id': row['id'], 'title': row['title'], 'task': task_id(row['task']), 'messages': messages}
    finally:
        conn.close()


def list_chats():
    conn = _connect()
    try:
        return [dict(row, task=task_id(row['task']))
                for row in conn.execute('SELECT id,title,updated,task FROM chats ORDER BY updated DESC LIMIT 100')]
    finally:
        conn.close()


def delete(chat_id):
    from randall.website.vault_presence import recover_history
    recover_history()
    conn = _connect()
    try:
        with conn:
            conn.execute('DELETE FROM chats WHERE id=?', (chat_id,))
            conn.execute('DELETE FROM pending_inputs WHERE chat_id=?', (chat_id,))
    finally:
        conn.close()
