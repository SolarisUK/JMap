# Deploy JMap on Vercel

Import the repository into Vercel and use these settings:

| Setting | Value |
|---|---|
| Root Directory | Repository root (`.`), **not** `UI` |
| Framework Preset | FastAPI (normally detected automatically) |
| Build Command | `python -B UI/scripts/build-vercel.py` (configured in `vercel.json`) |
| Output Directory | Leave the override disabled; FastAPI serves root `public/` through Vercel's CDN |
| Install Command | Leave the override disabled; dependencies come from `pyproject.toml` |
| Python | 3.13, selected by `pyproject.toml` |

The configuration points directly to the existing `api:app` application. `api.py`, its loader and the JSON shapes are unchanged. `stubs/` stays beside `api.py` and is included in the function bundle. There is no separate API domain or production localhost setting.

The build copies HTML, CSS, JavaScript, map assets and published source datasets from `UI/` into generated `public/`. Tests, Python helpers, recordings and the unused numerical replay JavaScript archive are excluded from the public site. The homepage uses `UI/index.html` and opens the existing generation map; navigation retains `generation.html`, `transfers.html`, `explorer.html` and `operations.html`.

Verify the deployment:

1. `/` opens the generation map and its assets load.
2. `/health` returns `"ok": true`.
3. `/operations.html` loads both strategies from same-origin `/state`, `/state/series` and `/compare` requests.
4. `/explorer.html` loads the local-authority map, including Highland selection.

For a local static preview, run `python -B UI/scripts/build-vercel.py`, then `python -m http.server 8080 --directory public`. Keep `uvicorn api:app --port 8000` running separately for the local simulation. Production uses the Vercel function instead of a persistent Uvicorn process.

Future replay updates still use `python -B UI/scripts/export-api-stubs.py --backend-root dhruv_latest`. Commit the generated data and redeploy so Vercel bundles the new stubs. Updating local files does not modify an existing deployment.

This repository setup is tested locally. A successful Vercel cloud build and live smoke check are still required after importing the project.

References: [FastAPI on Vercel](https://vercel.com/docs/frameworks/backend/fastapi), [Python runtime](https://vercel.com/docs/functions/runtimes/python).
