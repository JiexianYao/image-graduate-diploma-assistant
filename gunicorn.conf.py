import os

bind            = f"0.0.0.0:{os.environ.get('PORT', '9001')}"
workers         = 2
worker_class    = "uvicorn.workers.UvicornWorker"
timeout         = 120
keepalive       = 5
accesslog       = "-"
errorlog        = "-"
loglevel        = "info"
