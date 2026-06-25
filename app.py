import json
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash

from common import REFRESH_STATUS_REFRESHING, VALID_PROVIDERS, PROVIDER_LABELS, CREDENTIAL_FIELD_LABELS
from config import SECRET_KEY, EXTERNAL_API_SECRET, APP_PORT, PERMANENT_SESSION_LIFETIME, ENABLE_TASK_POLLING
from credentials import credential_bp
from domains import get_visible_domains, domain_bp, start_task_polling_thread
from external_api import external_bp
from models import ensure_database, load_urls, load_users, load_credentials
from users import user_bp

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
app.secret_key = SECRET_KEY
app.config['EXTERNAL_API_SECRET'] = EXTERNAL_API_SECRET
app.config['APP_PORT'] = APP_PORT
app.permanent_session_lifetime = PERMANENT_SESSION_LIFETIME

@app.template_filter('datetimeformat')
def datetimeformat(value, format='%Y-%m-%d %H:%M:%S'):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.strftime(format)

ensure_database()

app.register_blueprint(domain_bp)
app.register_blueprint(credential_bp)
app.register_blueprint(user_bp)
app.register_blueprint(external_bp)

if ENABLE_TASK_POLLING:
    start_task_polling_thread()

def get_urls_with_refreshing(urls):
    if not urls:
        return []
    n = len(urls)
    start_index = max(0, n - 20)
    current_index = start_index - 1
    while current_index >= 0:
        if urls[current_index].get('refresh_status') == REFRESH_STATUS_REFRESHING:
            current_index -= 1
        else:
            break
    final_start_index = current_index + 1
    # return list of indices to uniquely identify records in the original urls list
    return list(range(final_start_index, n))

@app.route('/')
def index():
    if 'username' not in session:
        return redirect(url_for('login'))
    users = load_users()
    user = next((u for u in users if u['username'] == session['username']), None)
    domains = get_visible_domains(user['username'], user['role'])
    credentials = load_credentials()
    all_usernames = [u['username'] for u in users]
    credential_lookup = {
        provider: {cred['id']: cred for cred in credentials.get(provider, [])}
        for provider in VALID_PROVIDERS
    }
    provider_credentials_json = json.dumps(credentials, ensure_ascii=False)
    urls = load_urls()
    indices = get_urls_with_refreshing(urls) if isinstance(urls, list) else []
    latest_urls = [dict(urls[i], _idx=urls[i]['id']) for i in reversed(indices)] if indices else []
    return render_template('index.html', user=user, domains=domains, credentials=credentials, credential_lookup=credential_lookup, provider_labels=PROVIDER_LABELS, credential_field_labels=CREDENTIAL_FIELD_LABELS, provider_credentials_json=provider_credentials_json, users=users, all_usernames=all_usernames, latest_urls=latest_urls)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        users = load_users()
        user = next((u for u in users if u['username'] == username), None)
        if user and check_password_hash(user['password'], password):
            session.permanent = True
            session['username'] = username
            return redirect(url_for('index'))
        flash('用户名或密码错误')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=app.config['APP_PORT'], debug=True)
