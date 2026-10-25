"""Directory-prefix collapse used by CDN refresh. Loaded from source so the
test does not import CDN provider SDKs."""

import ast
import unittest
from pathlib import Path


def _load_function(filename, name):
    path = Path(__file__).resolve().parents[1] / filename
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    if len(selected) != 1:
        raise AssertionError(f'{name} not found in {filename}')
    module = ast.Module(body=selected, type_ignores=[])
    namespace = {}
    exec(compile(module, str(path), 'exec'), namespace)
    return namespace[name]


collapse_storage_keys_to_highest_dirs = _load_function(
    'cdnmanager/services/storage_refresh_service.py',
    'collapse_storage_keys_to_highest_dirs',
)
is_ftp_family = _load_function(
    'cdnmanager/providers/storage/storage_service.py',
    'is_ftp_family',
)
build_object_key = _load_function(
    'cdnmanager/providers/storage/storage_service.py',
    'build_object_key',
)


class DirectoryCollapseTest(unittest.TestCase):
    def test_common_parent_collapses_to_one_directory(self):
        self.assertEqual(
            collapse_storage_keys_to_highest_dirs(['a/b/1.txt', 'a/c/2.txt']),
            ['a/'],
        )

    def test_sibling_directories_stay_separate(self):
        self.assertEqual(
            collapse_storage_keys_to_highest_dirs(['a/1.txt', 'b/2.txt']),
            ['a/', 'b/'],
        )

    def test_root_file_is_kept(self):
        self.assertEqual(collapse_storage_keys_to_highest_dirs(['only.txt']), ['only.txt'])

    def test_single_nested_file_keeps_its_directory(self):
        collapsed = collapse_storage_keys_to_highest_dirs(['only.txt', 'a/b/2.txt'])
        self.assertEqual(collapsed, ['a/b/', 'only.txt'])

    def test_blank_keys_are_skipped(self):
        self.assertEqual(collapse_storage_keys_to_highest_dirs(['', None]), [])


class FtpFamilyHelperTest(unittest.TestCase):
    def test_is_ftp_family(self):
        for provider in ('ftp', 'sftp', 'ftps'):
            self.assertTrue(is_ftp_family(provider))
        for provider in ('oss', 'cos', 'oos', '', None):
            self.assertFalse(is_ftp_family(provider))

    def test_object_key_segments(self):
        key = build_object_key({'base_path': 'cdn'}, '2026/09', 'assets/logo.png')
        self.assertEqual(key, 'cdn/2026/09/assets/logo.png')
        self.assertEqual(build_object_key({}, '', 'logo.png'), 'logo.png')


if __name__ == '__main__':
    unittest.main()
