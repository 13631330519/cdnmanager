from datetime import datetime

from cdnmanager.db.connection import query_all, query_one, run_write


def insert_upload_job(job):
    def work(conn):
        conn.execute(
            '''
            INSERT INTO upload_jobs
            (id, username, storage_target_id, remote_prefix, status, total_files, total_bytes,
             done_files, done_bytes, failed_files, refresh_after, created_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                job.get('id'),
                job.get('username'),
                job.get('storage_target_id'),
                job.get('remote_prefix'),
                job.get('status'),
                job.get('total_files', 0),
                job.get('total_bytes', 0),
                job.get('done_files', 0),
                job.get('done_bytes', 0),
                job.get('failed_files', 0),
                job.get('refresh_after', 0),
                job.get('created_at'),
                job.get('finished_at'),
            ),
        )

    run_write(work)


def get_upload_job(job_id):
    return query_one(
        '''
        SELECT id, username, storage_target_id, remote_prefix, status, total_files, total_bytes,
               done_files, done_bytes, failed_files, refresh_after, created_at, finished_at
        FROM upload_jobs WHERE id = ?
        ''',
        (job_id,),
    )


def update_upload_job(job_id, updates):
    if not updates:
        return False
    set_clauses = []
    params = []
    for key, value in updates.items():
        set_clauses.append(f'{key} = ?')
        params.append(value)
    params.append(job_id)
    sql = f"UPDATE upload_jobs SET {', '.join(set_clauses)} WHERE id = ?"

    def work(conn):
        conn.execute(sql, params)

    run_write(work)
    return True


def _upload_file_row_values(item):
    return (
        item.get('id'),
        item.get('job_id'),
        item.get('relative_path'),
        item.get('size'),
        item.get('mime'),
        item.get('status'),
        item.get('bytes_uploaded', 0),
        item.get('storage_key'),
        item.get('upload_id'),
        item.get('etag'),
        item.get('error'),
        item.get('retry_count', 0),
        item.get('started_at'),
        item.get('finished_at'),
        item.get('last_heartbeat_at'),
    )


def insert_upload_files(files):
    if not files:
        return

    def work(conn):
        conn.executemany(
            '''
            INSERT INTO upload_files
            (id, job_id, relative_path, size, mime, status, bytes_uploaded, storage_key,
             upload_id, etag, error, retry_count, started_at, finished_at, last_heartbeat_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            [_upload_file_row_values(item) for item in files],
        )

    run_write(work)


def get_upload_file(file_id):
    return query_one(
        '''
        SELECT id, job_id, relative_path, size, mime, status, bytes_uploaded, storage_key,
               upload_id, etag, error, retry_count, started_at, finished_at, last_heartbeat_at
        FROM upload_files WHERE id = ?
        ''',
        (file_id,),
    )


def update_upload_file(file_id, updates):
    if not updates:
        return False
    set_clauses = []
    params = []
    for key, value in updates.items():
        set_clauses.append(f'{key} = ?')
        params.append(value)
    params.append(file_id)
    sql = f"UPDATE upload_files SET {', '.join(set_clauses)} WHERE id = ?"

    def work(conn):
        conn.execute(sql, params)

    run_write(work)
    return True


_UPLOAD_FILE_COLUMNS = '''
    id, job_id, relative_path, size, mime, status, bytes_uploaded, storage_key,
    upload_id, etag, error, retry_count, started_at, finished_at, last_heartbeat_at
'''


def list_upload_files(job_id, status=None, limit=500, offset=0):
    if status:
        return query_all(
            f'''
            SELECT {_UPLOAD_FILE_COLUMNS}
            FROM upload_files WHERE job_id = ? AND status = ?
            ORDER BY relative_path LIMIT ? OFFSET ?
            ''',
            (job_id, status, limit, offset),
        )
    return query_all(
        f'''
        SELECT {_UPLOAD_FILE_COLUMNS}
        FROM upload_files WHERE job_id = ?
        ORDER BY relative_path LIMIT ? OFFSET ?
        ''',
        (job_id, limit, offset),
    )


def list_upload_jobs(username=None, limit=50, offset=0):
    if username:
        return query_all(
            '''
            SELECT id, username, storage_target_id, remote_prefix, status, total_files, total_bytes,
                   done_files, done_bytes, failed_files, refresh_after, created_at, finished_at
            FROM upload_jobs WHERE username = ?
            ORDER BY created_at DESC LIMIT ? OFFSET ?
            ''',
            (username, limit, offset),
        )
    return query_all(
        '''
        SELECT id, username, storage_target_id, remote_prefix, status, total_files, total_bytes,
               done_files, done_bytes, failed_files, refresh_after, created_at, finished_at
        FROM upload_jobs
        ORDER BY created_at DESC LIMIT ? OFFSET ?
        ''',
        (limit, offset),
    )


def count_upload_jobs(username=None):
    if username:
        row = query_one('SELECT COUNT(*) AS cnt FROM upload_jobs WHERE username = ?', (username,))
    else:
        row = query_one('SELECT COUNT(*) AS cnt FROM upload_jobs')
    return row['cnt'] if row else 0


def list_failed_upload_files(job_id):
    return query_all(
        f'''
        SELECT {_UPLOAD_FILE_COLUMNS}
        FROM upload_files WHERE job_id = ? AND status = 'failed'
        ORDER BY relative_path
        ''',
        (job_id,),
    )


def list_stale_uploading_files(cutoff_iso):
    return query_all(
        f'''
        SELECT {_UPLOAD_FILE_COLUMNS}
        FROM upload_files
        WHERE status IN ('uploading', 'verifying')
          AND last_heartbeat_at IS NOT NULL
          AND last_heartbeat_at < ?
        ''',
        (cutoff_iso,),
    )


def increment_upload_job_totals(job_id, add_files, add_bytes):
    def work(conn):
        conn.execute(
            '''
            UPDATE upload_jobs
            SET total_files = total_files + ?, total_bytes = total_bytes + ?
            WHERE id = ?
            ''',
            (add_files, add_bytes, job_id),
        )

    run_write(work)


def count_upload_files(job_id, status=None):
    if status:
        row = query_one(
            'SELECT COUNT(*) AS cnt FROM upload_files WHERE job_id = ? AND status = ?',
            (job_id, status),
        )
    else:
        row = query_one('SELECT COUNT(*) AS cnt FROM upload_files WHERE job_id = ?', (job_id,))
    return row['cnt'] if row else 0


def insert_upload_parts(parts):
    def work(conn):
        for item in parts:
            conn.execute(
                '''
                INSERT INTO upload_parts
                (file_id, part_number, size, etag, status)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(file_id, part_number) DO UPDATE SET
                    size = excluded.size,
                    etag = excluded.etag,
                    status = excluded.status
                ''',
                (
                    item.get('file_id'),
                    item.get('part_number'),
                    item.get('size'),
                    item.get('etag'),
                    item.get('status'),
                ),
            )

    run_write(work)


def list_upload_parts(file_id):
    return query_all(
        '''
        SELECT id, file_id, part_number, size, etag, status
        FROM upload_parts WHERE file_id = ? ORDER BY part_number
        ''',
        (file_id,),
    )


def update_upload_part(file_id, part_number, updates):
    if not updates:
        return False
    set_clauses = []
    params = []
    for key, value in updates.items():
        set_clauses.append(f'{key} = ?')
        params.append(value)
    params.extend([file_id, part_number])
    sql = f"UPDATE upload_parts SET {', '.join(set_clauses)} WHERE file_id = ? AND part_number = ?"

    def work(conn):
        conn.execute(sql, params)

    run_write(work)
    return True


def recalculate_upload_job_stats(job_id):
    def work(conn):
        rows = conn.execute(
            'SELECT status, size, bytes_uploaded FROM upload_files WHERE job_id = ?',
            (job_id,),
        ).fetchall()
        done_files = failed_files = 0
        done_bytes = 0
        for row in rows:
            status = row['status']
            if status == 'completed':
                done_files += 1
                done_bytes += row['size'] or 0
            elif status == 'failed':
                failed_files += 1
        total = len(rows)
        pending = total - done_files - failed_files
        if pending > 0 and done_files + failed_files > 0:
            job_status = 'running'
        elif done_files == total:
            job_status = 'completed'
        elif failed_files == total:
            job_status = 'failed'
        elif done_files > 0 and failed_files > 0 and pending == 0:
            job_status = 'partial'
        elif done_files == 0 and failed_files == 0:
            job_status = 'pending'
        else:
            job_status = 'running'
        finished_at = datetime.now().isoformat() if pending == 0 and total > 0 else None
        conn.execute(
            '''
            UPDATE upload_jobs
            SET done_files = ?, done_bytes = ?, failed_files = ?, status = ?,
                finished_at = COALESCE(?, finished_at)
            WHERE id = ?
            ''',
            (done_files, done_bytes, failed_files, job_status, finished_at, job_id),
        )

    run_write(work)


def delete_upload_job_cascade(job_id):
    def work(conn):
        file_rows = conn.execute(
            'SELECT id FROM upload_files WHERE job_id = ?',
            (job_id,),
        ).fetchall()
        for row in file_rows:
            conn.execute('DELETE FROM upload_parts WHERE file_id = ?', (row['id'],))
        conn.execute('DELETE FROM upload_files WHERE job_id = ?', (job_id,))
        conn.execute('DELETE FROM upload_jobs WHERE id = ?', (job_id,))

    run_write(work)


def cleanup_finished_upload_job(job_id):
    job = get_upload_job(job_id)
    if not job:
        return False
    if job.get('status') not in {'completed', 'partial', 'failed', 'cancelled'}:
        return False
    active = count_upload_files(job_id, status='uploading')
    active += count_upload_files(job_id, status='verifying')
    active += count_upload_files(job_id, status='pending')
    if active > 0:
        return False
    delete_upload_job_cascade(job_id)
    return True
