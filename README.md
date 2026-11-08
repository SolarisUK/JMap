# JMap

A UK energy dashboard with generation sites, live interconnector flows, annual local-authority statistics and historical real-data grid simulations.

- `UI/generation.html`: generating-site map and capacity explorer.
- `UI/transfers.html`: observed GB electricity imports and exports.
- `UI/explorer.html`: local energy statistics and area heatmap.
- `UI/operations.html`: No response (network-blind dispatch) versus Optimiser, with forecasts and API-driven results.

## Host on Vercel

Import this repository and set **Root Directory to the repository root (`.`), not `UI`**. Select **FastAPI** if framework detection does not select it. Leave Install Command and Output Directory overrides disabled; `vercel.json` supplies the build command.

`UI/index.html` opens the generation map. The build copies public UI assets into generated `public/`, which Vercel serves through its CDN. `pyproject.toml` points Vercel directly to the existing `api:app`; `api.py` and its loader are unchanged. The root `stubs/` folder stays beside the API and supplies the same endpoint payloads.

See [UI/VERCEL.md](UI/VERCEL.md) for settings, deployment smoke checks and future data updates. This prepares the repository for Vercel; it does not create a Vercel project or claim a cloud deployment has passed.

## Run locally

With the Python dependencies in `pyproject.toml` installed, run `uvicorn api:app --port 8000` from the repository root. Open `UI/index.html` directly, or run `python -m http.server 8080 --directory UI` and visit `http://localhost:8080/`.

To preview the deployment assets, run `python -B UI/scripts/build-vercel.py`, then `python -m http.server 8080 --directory public`, alongside the API.

## Validate

```powershell
node --test UI/tests/*.test.cjs
python -B UI/tests/api-replay.test.py
python -B UI/tests/vercel-build.test.py
python -B UI/tests/vercel-browser.py
```

The API must be running for the replay and deployment-browser checks. Deployment browser checks simulate the CDN and same-origin API routing locally; they do not replace a Vercel cloud smoke test.

Detailed behavior, source provenance and other regression checks are documented in [UI/README.md](UI/README.md).
