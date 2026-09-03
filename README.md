# Logistics Cost Analyzer — Flask edition

This is the same app you had (upload → map columns → automatic KPIs,
charts, insights, exports across 10 pages), rebuilt as a normal Flask web
application instead of a Streamlit app. Same features, same look
(beige/black theme), same logic for cleaning data, computing KPIs, and
generating charts/insights/exports — just served over plain HTTP with
server-rendered HTML + Plotly.js instead of the Streamlit runtime.

## What changed vs. the Streamlit version

- **Runtime**: Flask + Jinja2 templates instead of `streamlit run`.
- **Pages**: Streamlit's automatic multi-page sidebar became normal Flask
  routes (`/cost-analysis`, `/route-analysis`, etc.), linked from a left
  nav — same 10 pages, same order.
- **Filters**: instead of `st.session_state`-backed sidebar widgets, filters
  are plain URL query parameters (e.g. `?date_start=...&route=A&route=B`).
  This means filtered views are bookmarkable/shareable, and "Reset Filters"
  is just the bare page URL. Each page keeps its own independent filters,
  exactly like the original (switching pages doesn't carry filters over).
- **Charts**: still built with Plotly (same `chart_engine.py` theme, same
  color palette) — Plotly figures are serialized to JSON and rendered
  client-side with Plotly.js instead of `st.plotly_chart`.
- **File upload / column mapping**: a normal HTML `<form enctype="multipart/form-data">`
  and `<select>` dropdowns replace `st.file_uploader` / `st.selectbox`.
- **Session state**: uploaded datasets are held in server-side memory,
  keyed by a signed session-id cookie Flask sets automatically (see
  "Scaling beyond one process" below).
- **Everything else is untouched**: `schema.py`, `data_cleaner.py`,
  `mapping.py`, `kpi_engine.py`, `insight_engine.py`, `export_engine.py`
  (CSV/Excel/PDF/PNG export), and `data_generator.py` (sample data) are the
  exact same files/logic as before — they never depended on Streamlit.

## Project layout

```
webapp/
  app.py                  # Flask routes (one per page + upload/export endpoints)
  core/                    # All the data logic (mostly unchanged from before)
  templates/               # Jinja2 HTML templates (one per page)
  static/css/style.css     # The beige/black theme, as plain CSS
  static/js/app.js         # Renders Plotly charts from embedded JSON
  requirements.txt
  Procfile                 # For Render/Railway/Heroku-style platforms
  Dockerfile                # Optional container build
```

## Run it locally

```bash
cd webapp
python -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt
python app.py
```

Visit http://localhost:8000

## Deploy it like a normal web app

**Any platform that runs a Python/WSGI app works** (this is no longer
Streamlit-specific):

- **Render / Railway / Heroku-style PaaS**: push this folder as a repo;
  the included `Procfile` (`gunicorn -w 1 -b 0.0.0.0:$PORT app:app`) is
  picked up automatically.
- **Docker / any VM / Kubernetes**: `docker build -t logistics-analyzer .`
  then `docker run -p 8000:8000 logistics-analyzer`.
- **A plain VPS**: `pip install -r requirements.txt`, then run under
  `gunicorn` (included) behind nginx/Caddy as a reverse proxy, e.g.:
  ```bash
  gunicorn -w 1 -b 0.0.0.0:8000 app:app
  ```

Before deploying for real, set a proper secret key via an environment
variable rather than the placeholder in `app.py`:
```python
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key-in-production")
```

## Scaling beyond one process

Uploaded datasets are cached in the Python process's memory per session
(see `core/data_state.py`). That's simplest and matches the original
Streamlit app's own per-session behavior, but it means:

- Keep **one worker process** (`-w 1`) unless you add sticky sessions at
  your load balancer, **or**
- Swap the in-memory `SESSION_STORE` dict in `core/data_state.py` for
  something shared (Redis, a database, or disk-backed cache) — the
  get/set/pop-style functions in that file are the only place that would
  need to change.

The sample dataset (shown before any upload) is deterministic and
generated once per process, so it's shared across all users automatically
— no scaling concern there.
