"""Background workers for upload job maintenance."""

import logging
import threading
import time
from datetime import datetime, timedelta

from cdnmanager.common import UPLOAD_FILE_FAILED, UPLOAD_HEARTBEAT_TIMEOUT
from cdnmanager.config import ENABLE_UPLOAD_TIMEOUT_SCAN
import cdnmanager.db as db


logger = logging.getLogger(__name__)


def scan_upload_timeouts_once():
    cutoff = (datetime.now() - timedelta(seconds=UPLOAD_HEARTBEAT_TIMEOUT)).isoformat()
    stale_files = db.list_stale_uploading_files(cutoff)
    if not stale_files:
        return 0

    job_ids = set()
    for file_record in stale_files:
        db.update_upload_file(file_record['id'], {
            'status': UPLOAD_FILE_FAILED,
            'error': '上传心跳超时（>15 分钟无进度）',
            'finished_at': datetime.now().isoformat(),
        })
        job_ids.add(file_record['job_id'])

    for job_id in job_ids:
        db.recalculate_upload_job_stats(job_id)

    logger.info('上传超时扫描: 标记 %s 个文件失败', len(stale_files))
    return len(stale_files)


def start_upload_timeout_thread():
    if not ENABLE_UPLOAD_TIMEOUT_SCAN:
        return

    def worker():
        while True:
            try:
                scan_upload_timeouts_once()
            except Exception as exc:
                logger.warning('上传超时扫描异常: %s', exc)
            time.sleep(60)

    thread = threading.Thread(target=worker, daemon=True, name='upload-timeout-scanner')
    thread.start()
