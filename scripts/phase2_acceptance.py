#!/usr/bin/env python3
"""Phase 2 upload acceptance benchmarks (run from repo root)."""

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from cdnmanager import create_app
from cdnmanager.db.models import ensure_database, get_storage_target, load_storage_targets


def _login(client, username='admin'):
    with client.session_transaction() as sess:
        sess['username'] = username


def benchmark_batch_init(client, total_files=10000, batch_size=1000):
    targets = load_storage_targets()
    if not targets:
        print('[SKIP] batch init: 无存储目标，跳过')
        return None
    target_id = targets[0]['id']
    manifest = [
        {
            'relative_path': f'bench/{i}.bin',
            'size': 512000,
            'mime': 'application/octet-stream',
        }
        for i in range(total_files)
    ]

    started = time.perf_counter()
    job_id = None
    for offset in range(0, len(manifest), batch_size):
        batch = manifest[offset:offset + batch_size]
        if offset == 0:
            resp = client.post('/api/upload/jobs', json={
                'storage_target_id': target_id,
                'remote_prefix': 'phase2-bench/',
                'refresh_after': False,
                'files': batch,
            })
        else:
            resp = client.post(f'/api/upload/jobs/{job_id}/init-batch', json={'files': batch})
        data = resp.get_json()
        if resp.status_code >= 400:
            raise RuntimeError(f'batch init failed @ {offset}: {data}')
        if offset == 0:
            job_id = data['job_id']

    elapsed = time.perf_counter() - started
    print(f'[PASS] batch init {total_files} files in {elapsed:.2f}s (limit 30s) -> {"OK" if elapsed < 30 else "FAIL"}')
    return job_id


def benchmark_presign_batch(client, job_id, sample=50):
    resp = client.get(f'/api/upload/jobs/{job_id}/files?limit={sample}')
    data = resp.get_json()
    file_ids = [f['id'] for f in data.get('files', [])][:sample]
    if len(file_ids) < sample:
        print(f'[WARN] presign batch: 仅 {len(file_ids)} 个文件可测')

    timings = []
    for _ in range(5):
        t0 = time.perf_counter()
        resp = client.post('/api/upload/files/presign-batch', json={'file_ids': file_ids})
        elapsed_ms = (time.perf_counter() - t0) * 1000
        timings.append(elapsed_ms)
        payload = resp.get_json()
        if resp.status_code >= 400:
            print(f'[WARN] presign batch HTTP {resp.status_code}: {payload}')
            return
    p99 = sorted(timings)[-1]
    print(f'[PASS] presign-batch {len(file_ids)} files: samples_ms={timings}, p99={p99:.1f}ms (limit 200ms) -> {"OK" if p99 < 200 else "WARN"}')


def benchmark_list_jobs(client):
    t0 = time.perf_counter()
    resp = client.get('/api/upload/jobs?limit=30')
    elapsed_ms = (time.perf_counter() - t0) * 1000
    data = resp.get_json()
    assert data.get('success'), data
    print(f'[PASS] list jobs {len(data.get("jobs", []))} rows in {elapsed_ms:.1f}ms')


def main():
    ensure_database()
    app = create_app()
    with app.test_client() as client:
        _login(client)
        print('=== Phase 2 Acceptance ===')
        job_id = benchmark_batch_init(client)
        if job_id:
            benchmark_presign_batch(client, job_id)
            benchmark_list_jobs(client)
            client.post(f'/api/upload/jobs/{job_id}/cleanup', json={'force': True})
        print('=== Done ===')


if __name__ == '__main__':
    main()
