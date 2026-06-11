import os
import json
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import check_password_hash

from common import ensure_data_files, VALID_PROVIDERS, PROVIDER_LABELS
from credentials import load_credentials, credential_bp
from domains import get_visible_domains, load_domains, domain_bp, start_task_polling_thread
from users import load_users, user_bp
from external_api import external_bp

app = Flask(__name__)
app.secret_key = "cdn_manager_2026_secret_key_789"
app.config['EXTERNAL_API_SECRET'] = os.environ.get('EXTERNAL_API_SECRET', 'cdn_manager_external_secret')

@app.template_filter('datetimeformat')
def datetimeformat(value, format='%Y-%m-%d %H:%M:%S'):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.strftime(format)

ensure_data_files()

app.register_blueprint(domain_bp)
app.register_blueprint(credential_bp)
app.register_blueprint(user_bp)
app.register_blueprint(external_bp)

task_polling_started = False

@app.before_request
def ensure_task_polling_started():
    global task_polling_started
    if not task_polling_started:
        start_task_polling_thread()
        task_polling_started = True

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
    return render_template('index.html', user=user, domains=domains, credentials=credentials, credential_lookup=credential_lookup, provider_labels=PROVIDER_LABELS, provider_credentials_json=provider_credentials_json, users=users, all_usernames=all_usernames)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        users = load_users()
        user = next((u for u in users if u['username'] == username), None)
        if user and check_password_hash(user['password'], password):
            session['username'] = username
            return redirect(url_for('index'))
        flash('用户名或密码错误')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=80, debug=True)
