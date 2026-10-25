"""Static layering smoke test described in docs/architecture-layering.md.

A module may import the same rank or a lower rank. It must not import a higher
rank (db must not import services, providers must not import routes, and so on).
Same-layer imports such as routes.common stay allowed here; the doc treats those
as a review guideline rather than this smoke check.
"""

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'cdnmanager'

RANKS = {
    'common': 0,
    'config': 0,
    'db': 1,
    'providers': 2,
    'services': 3,
    'routes': 4,
    'views': 4,
}


def _module_name(path):
    parts = list(path.relative_to(ROOT).with_suffix('').parts)
    if parts[-1] == '__init__':
        parts = parts[:-1]
    return '.'.join(parts)


def _rank(module_name):
    parts = module_name.split('.')
    if not parts or parts[0] != 'cdnmanager':
        return None
    if len(parts) == 1:
        return 5
    return RANKS.get(parts[1])


def _imported_modules(path):
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.append(node.module)
    return found


class ProjectLayeringTest(unittest.TestCase):
    def test_modules_do_not_import_higher_layers(self):
        violations = []
        for path in sorted(PACKAGE.rglob('*.py')):
            source = _module_name(path)
            source_rank = _rank(source)
            if source_rank is None:
                continue
            for imported in _imported_modules(path):
                target_rank = _rank(imported)
                if target_rank is None:
                    continue
                if target_rank > source_rank:
                    violations.append(f'{source} (rank {source_rank}) imports {imported} (rank {target_rank})')
        self.assertEqual(violations, [])


if __name__ == '__main__':
    unittest.main()
