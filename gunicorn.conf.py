import multiprocessing
import os

bind = os.environ.get('GUNICORN_BIND', '0.0.0.0:80')
workers = int(os.environ.get('GUNICORN_WORKERS', max(2, multiprocessing.cpu_count())))
threads = int(os.environ.get('GUNICORN_THREADS', '2'))
timeout = int(os.environ.get('GUNICORN_TIMEOUT', '120'))
worker_class = 'gthread'
preload_app = False
accesslog = '-'
errorlog = '-'
