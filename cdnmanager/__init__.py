import os

from flask import Flask

from cdnmanager.config import (
    APP_PORT,
    ENABLE_TASK_POLLING,
    EXTERNAL_API_SECRET,
    PERMANENT_SESSION_LIFETIME,
    SECRET_KEY,
)
import cdnmanager.db as db
import cdnmanager.services.refresh_service as refresh_service
import cdnmanager.services.upload_workers as upload_workers

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

    db.ensure_database()
    register_blueprints(app)
    register_views(app)

    @app.context_processor
    def inject_asset_version():
        static_root = app.static_folder or ''
        versions = []
        for rel_path in ('js/app.js', 'js/upload.js', 'css/layout.css'):
            try:
                versions.append(int(os.path.getmtime(os.path.join(static_root, *rel_path.split('/')))))
            except OSError:
                continue
        return {'asset_version': max(versions) if versions else 1}

    if ENABLE_TASK_POLLING:
        refresh_service.start_task_polling_thread()

    from cdnmanager.config import ENABLE_UPLOAD_TIMEOUT_SCAN
    if ENABLE_UPLOAD_TIMEOUT_SCAN:
        upload_workers.start_upload_timeout_thread()

    return app
