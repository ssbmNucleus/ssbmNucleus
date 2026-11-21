"""Actual auth middleware and patch-download route, without app startup."""
from tests.paths import BACKEND
import ast
import hmac
import logging
from pathlib import Path
import shutil
import tempfile
import unittest
import uuid

from flask import Blueprint, Flask, jsonify, request, send_file


def patch_app(root):
    backend = BACKEND
    app = Flask(__name__)
    scope = dict(app=app, hmac=hmac, request=request, jsonify=jsonify,
                 send_file=send_file, _backend_token='test-backend-token',
                 _PUBLIC_MEDIA_PREFIXES=(), XDELTA_PATH=root,
                 xdelta_bp=Blueprint('test_xdelta', __name__),
                 logger=logging.getLogger(__name__),
                 load_xdelta_metadata=lambda: [{'id': 'patch-1', 'name': 'My Patch'}])
    for path, names in ((backend / 'app.py', {'_valid_backend_token', 'require_backend_token'}),
                        (backend / 'vault/routes/xdelta.py', {'download_xdelta_patch'})):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
        assert len(nodes) == len(names)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), scope)
    app.register_blueprint(scope['xdelta_bp'])
    return app


class PatchDownloadAuthTests(unittest.TestCase):
    def setUp(self):
        self.root = (Path(tempfile.gettempdir()) / f'nucleus-patch-download-{uuid.uuid4().hex}').resolve()
        self.root.mkdir()
        self.patch = self.root / 'patch-1.xdelta'
        self.patch.write_bytes(b'synthetic patch bytes')
        self.app = patch_app(self.root)
        self.client = self.app.test_client()

    def tearDown(self):
        self.assertEqual(self.root.parent, Path(tempfile.gettempdir()).resolve())
        self.assertTrue(self.root.name.startswith('nucleus-patch-download-'))
        shutil.rmtree(self.root)

    def test_bare_link_fails_but_authenticated_preflight_and_download_keep_patch(self):
        self.assertFalse(self.app.testing)
        endpoint = '/api/mex/xdelta/download-patch/patch-1'
        self.assertEqual(self.client.get(endpoint).status_code, 401)
        preflight = self.client.head(endpoint, headers={'X-Nucleus-Token': 'test-backend-token'})
        try:
            self.assertEqual(preflight.status_code, 200)
        finally:
            preflight.close()
        response = self.client.get(endpoint, query_string={'_nucleus_token': 'test-backend-token'})
        try:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b'synthetic patch bytes')
            self.assertIn('My Patch.xdelta', response.headers['Content-Disposition'])
        finally:
            response.close()
        self.assertTrue(self.patch.is_file())

    def test_bad_token_and_missing_patch_fail(self):
        self.assertEqual(self.client.get('/api/mex/xdelta/download-patch/patch-1?_nucleus_token=wrong').status_code, 401)
        self.assertEqual(self.client.head('/api/mex/xdelta/download-patch/missing', headers={'X-Nucleus-Token': 'test-backend-token'}).status_code, 404)


if __name__ == '__main__':
    unittest.main()
