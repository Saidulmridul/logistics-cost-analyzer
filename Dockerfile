FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8000
EXPOSE 8000

# -w 1: the in-memory session store (uploaded datasets) lives in process
# memory, so keep a single worker unless you swap it for a shared store
# (see README "Scaling beyond one process").
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:8000", "app:app"]
