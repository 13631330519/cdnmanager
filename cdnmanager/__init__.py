import os

from flask import Flask

from cdnmanager.config import (
    APP_PORT,
    ENABLE_TASK_POLLING,
    EXTERNAL_API_SECRET,
    PERMANENT_SESSION_LIFETIME,
    SECRET_KEY,
)
from cdnmanager.db.models import ensure_database
from cdnmanager.routes import register_blueprints
from cdnmanager.views import register_views

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def create_app():
    app = Flask(
        __name__,
        template_folder=os.path.join(ROOT_DIR, 'templates'),
        static_folder=os.path.join(ROOT_DIR, 'static'),
    )
    app.config['SECRET_KEY'] = SECRET_KEY
    app.secret_key = SECRET_KEY
    app.config['EXTERNAL_API_SECRET'] = EXTERNAL_API_SECRET
    app.config['APP_PORT'] = APP_PORT
    app.permanent_session_lifetime = PERMANENT_SESSION_LIFETIME

    ensure_database()
    register_blueprints(app)
    register_views(app)

    if ENABLE_TASK_POLLING:
        from cdnmanager.routes.cdn.domains import start_task_polling_thread
        start_task_polling_thread()

    return app
