"""Check deployment output and routing assets without changing API sources."""
import hashlib
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('vercel_build', ROOT/'UI/scripts/build-vercel.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attributes):
        self.urls += [value for key, value in attributes if key in ('src', 'href') and value]


class VercelBuildTests(unittest.TestCase):
    def test_public_contains_every_linked_asset_without_publishing_backend_or_recordings(self):
        before = hashlib.sha256((ROOT/'api.py').read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory(dir=ROOT/'UI/tests', prefix='vercel-build-') as temporary:
            output = Path(temporary)/'public'
            files = builder.build(output)
            for page in ('index.html', 'generation.html', 'transfers.html', 'explorer.html', 'operations.html'):
                self.assertIn(page, files)
            self.assertFalse(any(p.endswith('.py') or p.startswith(('stubs/', 'recordings/', 'tests/', 'scripts/')) for p in files))
            self.assertNotIn('assets/simulation-stubs.js', files)
            for file in output.glob('*.html'):
                references = References()
                references.feed(file.read_text(encoding='utf-8'))
                for url in references.urls:
                    parts = urlsplit(url)
                    if not parts.scheme and not parts.netloc and parts.path:
                        target = output/unquote(parts.path).lstrip('/')
                        self.assertTrue(target.is_file(), f'{file.name}: missing {url}')
            (output/'stale.js').write_text('stale', encoding='utf-8')
            builder.build(output)
            self.assertFalse((output/'stale.js').exists())
        self.assertEqual(hashlib.sha256((ROOT/'api.py').read_bytes()).hexdigest(), before)

    def test_existing_user_directory_and_source_directories_are_preserved(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'UI/tests', prefix='vercel-guard-') as temporary:
            output = Path(temporary)/'public'
            output.mkdir()
            (output/'keep.txt').write_text('existing', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'not generated'):
                builder.build(output)
            self.assertEqual((output/'keep.txt').read_text(), 'existing')
        with self.assertRaises(ValueError):
            builder.build(ROOT/'UI')

    def test_configuration_uses_the_existing_api_and_bundles_current_stubs(self):
        project = tomllib.loads((ROOT/'pyproject.toml').read_text())
        config = json.loads((ROOT/'vercel.json').read_text())
        self.assertEqual(project['tool']['vercel']['entrypoint'], 'api:app')
        self.assertEqual(config['framework'], 'fastapi')
        self.assertEqual(config['functions']['api.py']['includeFiles'], 'stubs/**')
        self.assertIn({'source':'/', 'destination':'/index.html'}, config['rewrites'])
        for filename in ('replay.json', 'compare.json', 'reference.json'):
            self.assertTrue((ROOT/'stubs'/filename).is_file())


if __name__ == '__main__':
    unittest.main(verbosity=2)
