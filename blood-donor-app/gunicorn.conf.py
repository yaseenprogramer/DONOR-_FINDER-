import os

bind = f"0.0.0.0:{os.environ.get('PORT', '10000')}"
workers = 1          # keep 1: SQLite + in-memory rate limiter
threads = 4
timeout = 120
accesslog = "-"
errorlog = "-"
loglevel = "info"
