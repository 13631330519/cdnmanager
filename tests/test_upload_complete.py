"""Upload complete tolerance and presign batching without a live bucket."""

import unittest
from unittest.mock import MagicMock, patch

from tests.cloud_stubs import install

install()

import cdnmanager.services.upload_service as upload_service


def _file(**overrides):
    record = {
        'id': 'f1',
        'job_id': 'j1',
        'size': 12,
        'storage_key': 'a.txt',
        'upload_id': None,
        'status': 'uploading',
        'bytes_uploaded': 12,
        'mime': 'text/plain',
        'started_at': None,
    }
    record.update(overrides)
    return record


class CompleteUploadFileTest(unittest.TestCase):
    def _run(self, *, provider, proxy, verify):
        job = {'id': 'j1', 'storage_target_id': 't1'}
        file_record = _file()
        adapter = MagicMock()
        adapter.verify_object.side_effect = verify
        target = {'id': 't1', 'provider': provider, 'credential_id': 'c', 'target_config': {}}
        with patch.object(upload_service.db, 'get_storage_target', return_value=target), \
             patch.object(upload_service.db, 'get_storage_credential', return_value={'access_key': 'u', 'secret_key': 'p'}), \
             patch.object(upload_service.storage_service, 'get_adapter', return_value=adapter), \
             patch.object(upload_service.db, 'update_upload_file') as update_file, \
             patch.object(upload_service.db, 'recalculate_upload_job_stats'), \
             patch.object(upload_service, 'finalize_finished_job', return_value={'success': True, 'results': []}) as finalize:
            result = upload_service.complete_upload_file(job, file_record, etag='etag-1', proxy=proxy)
        return result, update_file, finalize, adapter

    def test_ftp_proxy_tolerates_verify_failure(self):
        result, update_file, finalize, _adapter = self._run(
            provider='ftp',
            proxy=True,
            verify=lambda *args, **kwargs: {'ok': False, 'error': 'SIZE not supported'},
        )
        self.assertTrue(result['success'])
        self.assertEqual(update_file.call_args_list[-1].args[1]['status'], 'completed')
        finalize.assert_called_once()

    def test_ftp_proxy_tolerates_verify_exception(self):
        def explode(*args, **kwargs):
            raise OSError('stat failed')

        result, update_file, _finalize, _adapter = self._run(
            provider='sftp', proxy=True, verify=explode,
        )
        self.assertTrue(result['success'])
        self.assertEqual(update_file.call_args_list[-1].args[1]['status'], 'completed')

    def test_ftp_without_proxy_is_strict(self):
        result, update_file, finalize, _adapter = self._run(
            provider='ftps',
            proxy=False,
            verify=lambda *args, **kwargs: {'ok': False, 'error': '校验失败'},
        )
        self.assertFalse(result['success'])
        self.assertEqual(result['error'], '校验失败')
        self.assertEqual(update_file.call_args_list[-1].args[1]['status'], 'failed')
        finalize.assert_called_once()

    def test_object_storage_proxy_flag_does_not_skip_verify(self):
        result, update_file, _finalize, adapter = self._run(
            provider='oss',
            proxy=True,
            verify=lambda *args, **kwargs: {'ok': False, 'error': 'HEAD 大小不一致'},
        )
        self.assertFalse(result['success'])
        adapter.verify_object.assert_called_once()
        self.assertEqual(update_file.call_args_list[-1].args[1]['status'], 'failed')

    def test_object_storage_success_keeps_etag(self):
        result, update_file, _finalize, _adapter = self._run(
            provider='cos',
            proxy=False,
            verify=lambda *args, **kwargs: {'ok': True, 'etag': 'abc', 'size': 12},
        )
        self.assertTrue(result['success'])
        self.assertEqual(result['etag'], 'abc')
        self.assertEqual(update_file.call_args_list[-1].args[1]['etag'], 'abc')


class PresignBatchTest(unittest.TestCase):
    def test_cors_and_context_once_per_target(self):
        files = [
            _file(id='a', storage_key='a.txt'),
            _file(id='b', storage_key='b.txt', status='pending', bytes_uploaded=0),
        ]
        for item in files:
            item['status'] = 'pending'
        job = {'id': 'j1', 'storage_target_id': 't1'}
        adapter = MagicMock()
        adapter.presign_put.side_effect = lambda *args, **kwargs: 'https://example/put'
        target = {'id': 't1', 'provider': 'oss', 'credential_id': 'c', 'target_config': {'bucket': 'b'}}
        with patch.object(upload_service.db, 'get_upload_files_by_ids', return_value=files) as get_files, \
             patch.object(upload_service.db, 'get_upload_jobs_by_ids', return_value=[job]) as get_jobs, \
             patch.object(upload_service.db, 'get_upload_file') as get_one, \
             patch.object(upload_service.db, 'get_upload_job') as get_job_one, \
             patch.object(upload_service.db, 'get_storage_target', return_value=target) as get_target, \
             patch.object(upload_service.db, 'get_storage_credential', return_value={'access_key': 'u', 'secret_key': 'p'}) as get_cred, \
             patch.object(upload_service.storage_service, 'get_adapter', return_value=adapter) as get_adapter, \
             patch.object(upload_service.storage_service, 'ensure_browser_cors') as cors, \
             patch.object(upload_service.db, 'update_upload_file'), \
             patch.object(upload_service.db, 'update_upload_job') as update_job:
            results, errors = upload_service.presign_put_batch(['a', 'b'], origin='https://app.example')

        self.assertEqual(errors, [])
        self.assertEqual([item['file_id'] for item in results], ['a', 'b'])
        get_files.assert_called_once()
        get_jobs.assert_called_once()
        get_one.assert_not_called()
        get_job_one.assert_not_called()
        get_target.assert_called_once()
        get_cred.assert_called_once()
        get_adapter.assert_called_once()
        cors.assert_called_once()
        update_job.assert_called_once()
        self.assertEqual(adapter.presign_put.call_count, 2)


if __name__ == '__main__':
    unittest.main()
