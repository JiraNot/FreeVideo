"""Normalized, read-only capability reporting for the ComfyUI runtime."""
import json
from pathlib import Path

from .bootstrap import PACKAGE, model_target
from .comfy_bridge import installation, source_root
from .install_tuning import cache_compatible, required_models
from . import prepared_model


def _cache_ready(cache, capability):
    """Check the selected runtime cache manifest and exact group file sizes."""
    if not cache or not isinstance(capability, (list, tuple)) or len(capability) != 2:
        return False
    cache = Path(cache).expanduser().resolve()
    if not cache_compatible(cache, capability):
        return False
    manifest = json.loads((cache / 'manifest.json').read_text(encoding='utf-8'))
    groups = manifest.get('groups')
    if not isinstance(groups, list) or not groups:
        return False
    from .adaln_assets import asset_path
    for row in groups:
        target = asset_path(cache, row['file'])
        if not target.is_file() or target.stat().st_size != row['bytes']:
            return False
    return True


def _model_pack(root, machine):
    """Check the exact FreeVideo engine model selection without exposing paths."""
    run = Path(machine['setup_run']).expanduser().resolve()
    root = Path(root).expanduser().resolve()
    if run == root or root not in run.parents:
        raise ValueError('Invalid setup plan location')
    plan_path = run / 'plan.json'
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    selection = plan.get('prepared_model')
    reuse_cache = plan.get('reuse_cache')
    capability = plan.get('inventory', {}).get('hardware', {}).get('capability')
    cache = reuse_cache or (selection or {}).get('cache') or machine.get('cache')
    model_root = Path(machine['model_root']).expanduser().resolve()
    encoder_root = Path(machine['encoder_model_root']).expanduser().resolve()
    prepared_dir = Path(selection['directory']).expanduser().resolve() if selection else None
    model_source = plan.get('model_source')
    if model_source not in ('prepared', 'existing', 'source'):
        model_source = 'unknown'

    rows = json.loads((PACKAGE / 'model_files.json').read_text(encoding='utf-8'))
    rows = required_models(rows, reuse_cache or selection)
    rows += prepared_model.files(selection)
    if not rows:
        raise ValueError('No model requirements found')

    available = 0
    for row in rows:
        target = model_target(row, model_root, encoder_root, prepared_dir)
        try:
            if target.is_file() and target.stat().st_size == row['bytes']:
                available += 1
        except OSError:
            pass
    runtime_cache_ready = _cache_ready(cache, capability)
    return {
        'id': 'freevideo-h3-engine',
        'ready': available == len(rows) and runtime_cache_ready,
        'modelSource': model_source,
        'requiredFiles': len(rows),
        'availableFiles': available,
        'runtimeCacheReady': runtime_cache_ready,
    }


def discover(source=None, environ=None):
    """Report runtime and model readiness, omitting local paths and credentials."""
    root = None
    try:
        root, machine = installation(source or source_root(), environ)
        engine_ready = True
    except (OSError, ValueError, KeyError, TypeError):
        machine = None
        engine_ready = False

    try:
        model_pack = _model_pack(root, machine) if machine else {
            'id': 'freevideo-h3-engine', 'ready': False, 'modelSource': 'unknown',
            'requiredFiles': 0, 'availableFiles': 0,
        }
        model_error = False
    except (OSError, ValueError, KeyError, TypeError):
        model_pack = {
            'id': 'freevideo-h3-engine', 'ready': False, 'modelSource': 'unknown',
            'requiredFiles': 0, 'availableFiles': 0,
        }
        model_error = True

    return {
        'schemaVersion': 1,
        'engineReady': engine_ready,
        'modelPacks': [model_pack],
        'reason': ('FreeVideo engine and its selected H3 model pack are ready.'
                   if engine_ready and model_pack['ready'] else
                   'FreeVideo engine is ready, but its selected H3 model pack is incomplete.'
                   if engine_ready else
                   'FreeVideo engine installation is not ready.'),
        'modelInventoryAvailable': not model_error,
    }


def register():
    from aiohttp import web
    from server import PromptServer

    server = PromptServer.instance
    if server is None or getattr(server, '_freevideo_capabilities', None) is not None:
        return
    server._freevideo_capabilities = True

    @server.routes.get('/freevideo/capabilities')
    async def capabilities(_request):
        return web.json_response(discover())
