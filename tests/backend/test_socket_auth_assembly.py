"""Exercise actual socket construction/registrations without app startup IO."""
from tests.paths import BACKEND
import ast
import hmac
from pathlib import Path
import unittest

from flask import Flask
from flask_socketio import SocketIO


def socket_app():
    source = BACKEND / 'app.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    selected = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == 'socketio' for t in node.targets):
            selected.append(node)
        elif isinstance(node, ast.FunctionDef):
            if node.name == '_valid_backend_token' or any(
                    isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and isinstance(d.func.value, ast.Name) and d.func.value.id == 'socketio'
                    and d.func.attr == 'on' and d.args
                    and isinstance(d.args[0], ast.Constant) and d.args[0].value == 'connect'
                    for d in node.decorator_list):
                selected.append(node)
    app = Flask('socket-auth-test')
    app.secret_key = 'synthetic-secret'
    scope = dict(app=app, SocketIO=SocketIO, hmac=hmac,
                 _backend_token='synthetic-backend-token',
                 _allowed_origin=lambda origin: True)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), 'exec'), scope)
    return app, scope['socketio']


class SocketAuthAssemblyTests(unittest.TestCase):
    def test_valid_client_receives_progress_and_reconnects(self):
        app, socket = socket_app()
        client = socket.test_client(app, auth={'token': 'synthetic-backend-token'})
        try:
            self.assertTrue(client.is_connected())
            socket.emit('setup_progress', {'percentage': 42})
            self.assertEqual(client.get_received()[0]['args'], [{'percentage': 42}])
            client.disconnect()
            client.connect(auth={'token': 'synthetic-backend-token'})
            self.assertTrue(client.is_connected())
        finally:
            if client.is_connected():
                client.disconnect()

    def test_missing_invalid_and_non_string_tokens_are_rejected(self):
        app, socket = socket_app()
        self.assertFalse(app.testing)  # exercise real enforcement, not its testing bypass
        for auth in (None, {}, {'token': 'wrong'}, {'token': 42}):
            with self.subTest(auth=auth):
                client = socket.test_client(app, auth=auth)
                try:
                    self.assertFalse(client.is_connected())
                finally:
                    if client.is_connected():
                        client.disconnect()


if __name__ == '__main__':
    unittest.main()
