import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from freevideo_engine import comfy_capabilities


class ComfyCapabilitiesTests(unittest.TestCase):
    def test_model_readiness_uses_exact_required_files_and_byte_sizes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = root / '.freevideo' / 'run-1'
            run.mkdir(parents=True)
            model_root = root / 'models'
            encoder_root = root / 'encoders'
            cache = root / 'cache'
            model_root.mkdir()
            encoder_root.mkdir()
            cache.mkdir()
            (model_root / 'present.safetensors').write_bytes(b'1234')
            (cache / 'weights.safetensors').write_bytes(b'cache')
            (cache / 'manifest.json').write_text(json.dumps({
                'groups': [{'file': 'weights.safetensors', 'bytes': 5}],
            }), encoding='utf-8')

            plan = {
                'model_source': 'source', 'prepared_model': None, 'reuse_cache': None,
                'inventory': {'hardware': {'capability': [8, 9]}},
            }
            (run / 'plan.json').write_text(json.dumps(plan), encoding='utf-8')
            machine = {
                'setup_run': str(run),
                'model_root': str(model_root),
                'encoder_model_root': str(encoder_root),
                'cache': str(cache),
            }
            manifest = [
                {'repo': 'OpenVDN/model', 'file': 'present.safetensors', 'bytes': 4},
                {'repo': 'OpenVDN/model', 'file': 'missing.safetensors', 'bytes': 7},
            ]

            with patch.object(comfy_capabilities, 'PACKAGE', root), \
                    patch.object(comfy_capabilities.prepared_model, 'files', return_value=[]), \
                    patch.object(comfy_capabilities, 'cache_compatible', return_value=True):
                (root / 'model_files.json').write_text(json.dumps(manifest), encoding='utf-8')
                status = comfy_capabilities._model_pack(root, machine)

            self.assertEqual(status['id'], 'freevideo-h3-engine')
            self.assertFalse(status['ready'])
            self.assertEqual(status['requiredFiles'], 2)
            self.assertEqual(status['availableFiles'], 1)
            self.assertTrue(status['runtimeCacheReady'])

    def test_discovery_never_returns_installation_paths_or_setup_credentials(self):
        machine = {
            'root': 'C:/private/runtime',
            'setup_run': 'C:/private/runtime/.freevideo/run',
            'python': 'C:/private/runtime/python.exe',
        }
        with patch.object(comfy_capabilities, 'installation', return_value=(Path('C:/private/runtime'), machine)), \
                patch.object(comfy_capabilities, '_model_pack', return_value={
                    'id': 'freevideo-h3-engine', 'ready': True, 'modelSource': 'prepared',
                    'requiredFiles': 12, 'availableFiles': 12,
                }):
            result = comfy_capabilities.discover()

        serialized = json.dumps(result)
        self.assertTrue(result['engineReady'])
        self.assertTrue(result['modelPacks'][0]['ready'])
        self.assertNotIn('C:/private/runtime', serialized)
        self.assertNotIn('python.exe', serialized)

    def test_model_plan_must_be_inside_the_installation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            elsewhere = root.parent / (root.name + '-outside')
            elsewhere.mkdir()
            machine = {
                'setup_run': str(elsewhere),
                'model_root': str(root / 'models'),
                'encoder_model_root': str(root / 'encoders'),
            }
            with self.assertRaises(ValueError):
                comfy_capabilities._model_pack(root, machine)
            elsewhere.rmdir()

    def test_runtime_cache_requires_every_manifest_group_at_the_expected_size(self):
        with tempfile.TemporaryDirectory() as temporary:
            cache = Path(temporary)
            (cache / 'manifest.json').write_text(json.dumps({
                'groups': [{'file': 'weights.safetensors', 'bytes': 5}],
            }), encoding='utf-8')
            (cache / 'weights.safetensors').write_bytes(b'12345')
            with patch.object(comfy_capabilities, 'cache_compatible', return_value=True):
                self.assertTrue(comfy_capabilities._cache_ready(cache, [8, 9]))
                (cache / 'weights.safetensors').write_bytes(b'1234')
                self.assertFalse(comfy_capabilities._cache_ready(cache, [8, 9]))


if __name__ == '__main__':
    unittest.main()
