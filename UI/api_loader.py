"""Serve the protected API with standard-stub compatibility.

From the repository root:
    uvicorn UI.api_loader:app --reload --port 8000

api.py is imported read-only. Only its data-reader hook and health route are
adapted; endpoint paths, parameters and public JSON fields remain unchanged.
"""
import os
from pathlib import Path

from fastapi import HTTPException
import api as source_api

from UI.stub_repository import StubRepository

if os.environ.get('JMAP_STUBS_DIR'):
    source_api.STUBS = Path(os.environ['JMAP_STUBS_DIR']).resolve()
repository = StubRepository(source_api.STUBS)


def load_stubs():
    try:
        return repository.load()
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise HTTPException(503, f'Stub data unavailable or incomplete: {error}') from error


source_api.replay = load_stubs
app = source_api.app
app.router.routes = [route for route in app.router.routes if getattr(route, 'path', None) != '/health']


@app.get('/health')
def health():
    required = ('zones', 'edges', 'state_calm', 'state_incident', 'state_series',
                'state_series_none', 'state_series_optimiser', 'forecast_LOND',
                'compare', 'scenarios', 'incident_response', 'reference')
    missing = [name for name in required if not (source_api.STUBS / f'{name}.json').is_file()]
    return {'ok': not missing, 'missing_stubs': missing}
