# Picked up automatically by `gunicorn app:app`. One worker with threads keeps live (SSE) connections in one process.
worker_class = "gthread"
workers = 1
threads = 32
timeout = 120
