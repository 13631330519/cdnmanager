"""Flask blueprints grouped by feature module."""


def register_blueprints(app):
    from cdnmanager.routes.cdn.credentials import credential_bp
    from cdnmanager.routes.cdn.domains import domain_bp
    from cdnmanager.routes.cdn.external_api import external_bp
    from cdnmanager.routes.cdn.refresh_records import refresh_records_bp
    from cdnmanager.routes.dns.credentials import dns_credential_bp
    from cdnmanager.routes.dns.root_domains import root_domain_bp
    from cdnmanager.routes.storage.browser import storage_browser_bp
    from cdnmanager.routes.storage.credentials import storage_credential_bp
    from cdnmanager.routes.storage.targets import storage_target_bp
    from cdnmanager.routes.storage.uploads import upload_bp
    from cdnmanager.routes.users import user_bp

    app.register_blueprint(domain_bp)
    app.register_blueprint(credential_bp)
    app.register_blueprint(dns_credential_bp)
    app.register_blueprint(root_domain_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(external_bp)
    app.register_blueprint(refresh_records_bp)
    app.register_blueprint(storage_credential_bp)
    app.register_blueprint(storage_target_bp)
    app.register_blueprint(storage_browser_bp)
    app.register_blueprint(upload_bp)
