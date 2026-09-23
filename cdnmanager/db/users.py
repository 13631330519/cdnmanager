import json

from cdnmanager.db.connection import query_all, query_one, run_write


def load_users():
    return query_all('SELECT username, password, role, created_at, updated_at FROM users ORDER BY username')


def get_user(username):
    return query_one(
        'SELECT username, password, role, created_at, updated_at FROM users WHERE username = ?',
        (username,),
    )


def remove_user_from_domains(username):
    def work(conn):
        rows = conn.execute('SELECT domain, allowed_users FROM domains').fetchall()
        for row in rows:
            allowed_users = row.get('allowed_users') or '[]'
            try:
                allowed_users_list = json.loads(allowed_users)
            except Exception:
                allowed_users_list = []
            if username in allowed_users_list:
                updated_users = [u for u in allowed_users_list if u != username]
                conn.execute(
                    'UPDATE domains SET allowed_users = ? WHERE domain = ?',
                    (json.dumps(updated_users, ensure_ascii=False), row['domain']),
                )

    run_write(work)


def upsert_user(user):
    def work(conn):
        conn.execute(
            '''
            INSERT INTO users (username, password, role, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                password = excluded.password,
                role = excluded.role,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            ''',
            (
                user.get('username'),
                user.get('password'),
                user.get('role', 'user'),
                user.get('created_at'),
                user.get('updated_at'),
            ),
        )

    run_write(work)


def delete_user(username):
    def work(conn):
        conn.execute('DELETE FROM users WHERE username = ?', (username,))

    run_write(work)
