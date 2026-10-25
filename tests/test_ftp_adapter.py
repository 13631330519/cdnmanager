"""FTP path resolution and client init branches. No live server."""

import ssl
import unittest
from unittest.mock import patch

from tests.cloud_stubs import install

install()

import cdnmanager.providers.storage.storage_ftp as storage_ftp
from tests.test_directory_collapse import build_object_key


class ResolveRemotePathTest(unittest.TestCase):
    def test_legacy_endpoint_is_root(self):
        config = {'bucket': 'ftp.example.com', 'region': '21', 'endpoint': '/www/cdn'}
        self.assertEqual(storage_ftp.resolve_remote_path(config, 'a/b.txt'), '/www/cdn/a/b.txt')
        self.assertEqual(storage_ftp.resolve_remote_path(config, ''), '/www/cdn')

    def test_root_field_wins_over_endpoint(self):
        config = {'host': 'files.example.com', 'port': 22, 'root': '/data', 'endpoint': '/old'}
        self.assertEqual(storage_ftp.resolve_remote_path(config, 'a.txt'), '/data/a.txt')

    def test_aligns_with_build_object_key(self):
        config = {'base_path': 'cdn', 'endpoint': '/www'}
        key = build_object_key(config, '2026/09', 'assets/logo.png')
        self.assertEqual(key, 'cdn/2026/09/assets/logo.png')
        self.assertEqual(
            storage_ftp.resolve_remote_path(config, key),
            '/www/cdn/2026/09/assets/logo.png',
        )

    def test_provider_config_prefers_host_port_root(self):
        host, port, root, scheme = storage_ftp._provider_config(
            {
                'host': 'files.example.com',
                'port': 2222,
                'root': '/data',
                'bucket': 'ignored',
                'region': '21',
                'endpoint': '/old',
            },
            'sftp',
        )
        self.assertEqual((host, port, root, scheme), ('files.example.com', 2222, '/data', 'sftp'))

    def test_provider_config_bucket_region_endpoint(self):
        host, port, root, scheme = storage_ftp._provider_config(
            {'bucket': 'ftp.example.com', 'region': '2121', 'endpoint': '/www'},
            'ftp',
        )
        self.assertEqual((host, port, root, scheme), ('ftp.example.com', 2121, '/www', 'ftp'))

    def test_provider_config_url_host(self):
        host, port, root, scheme = storage_ftp._provider_config(
            {'host': 'ftp://ftp.example.com:2121/cdn', 'endpoint': '/'},
            'ftp',
        )
        self.assertEqual(host, 'ftp.example.com')
        self.assertEqual(port, 2121)
        self.assertEqual(root, '/cdn')
        self.assertEqual(scheme, 'ftp')

    def test_insecure_tls_flag(self):
        self.assertFalse(storage_ftp.insecure_tls_enabled({}))
        self.assertFalse(storage_ftp.insecure_tls_enabled({'insecure_tls': '0'}))
        self.assertTrue(storage_ftp.insecure_tls_enabled({'insecure_tls': True}))
        self.assertTrue(storage_ftp.insecure_tls_enabled({'insecure_tls': 'yes'}))


class _FakeFTP:
    def __init__(self):
        self.deleted = []

    def delete(self, key):
        self.deleted.append(key)

    def quit(self):
        pass

    def close(self):
        pass


class _FakeTLS:
    def __init__(self, context=None):
        self.context = context

    def connect(self, *args, **kwargs):
        pass

    def login(self, *args, **kwargs):
        pass

    def prot_p(self):
        pass

    def set_pasv(self, *args, **kwargs):
        pass

    def cwd(self, *args, **kwargs):
        pass


class _FakeSFTP:
    def chdir(self, path):
        pass


class _FakeSSH:
    def __init__(self):
        self.policy = None

    def load_system_host_keys(self):
        pass

    def set_missing_host_key_policy(self, policy):
        self.policy = policy

    def connect(self, *args, **kwargs):
        pass

    def open_sftp(self):
        return _FakeSFTP()


class FtpInitBranchTest(unittest.TestCase):
    def test_ftps_verifies_tls_unless_insecure(self):
        credential = {'access_key': 'u', 'secret_key': 'p', 'provider': 'ftps'}
        config = {'host': 'ftp.example.com', 'port': 21, 'root': '/'}
        with patch.object(storage_ftp, 'FTP_TLS', _FakeTLS):
            ftp, _root = storage_ftp._ftp_client(credential, config, 'ftps')
        self.assertEqual(ftp.context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ftp.context.check_hostname)

        config['insecure_tls'] = True
        with patch.object(storage_ftp, 'FTP_TLS', _FakeTLS):
            ftp, _root = storage_ftp._ftp_client(credential, config, 'ftps')
        self.assertEqual(ftp.context.verify_mode, ssl.CERT_NONE)

    def test_sftp_rejects_unknown_host_keys_unless_insecure(self):
        import paramiko

        credential = {'access_key': 'u', 'secret_key': 'p', 'provider': 'sftp'}
        config = {'host': 'files.example.com', 'port': 22, 'root': '/data'}
        with patch.object(storage_ftp.paramiko, 'SSHClient', _FakeSSH):
            _client, _sftp, _root = storage_ftp._sftp_client(credential, config, 'sftp')
        # _sftp_client does not return the SSH client. Re-run capturing it.
        created = {}

        class CapturingSSH(_FakeSSH):
            def __init__(self):
                super().__init__()
                created['client'] = self

        with patch.object(storage_ftp.paramiko, 'SSHClient', CapturingSSH):
            storage_ftp._sftp_client(credential, config, 'sftp')
        self.assertIsInstance(created['client'].policy, paramiko.RejectPolicy)

        config['insecure_tls'] = '1'
        with patch.object(storage_ftp.paramiko, 'SSHClient', CapturingSSH):
            storage_ftp._sftp_client(credential, config, 'sftp')
        self.assertIsInstance(created['client'].policy, paramiko.AutoAddPolicy)

    def test_plain_ftp_does_not_use_tls(self):
        credential = {'access_key': 'u', 'secret_key': 'p', 'provider': 'ftp'}
        config = {'bucket': 'ftp.example.com', 'region': '21', 'endpoint': '/'}
        tls_calls = []

        class BoomTLS:
            def __init__(self, *args, **kwargs):
                tls_calls.append(1)

        class Plain:
            def connect(self, *args, **kwargs):
                pass

            def login(self, *args, **kwargs):
                pass

            def set_pasv(self, *args, **kwargs):
                pass

            def cwd(self, *args, **kwargs):
                pass

        with patch.object(storage_ftp, 'FTP', Plain), patch.object(storage_ftp, 'FTP_TLS', BoomTLS):
            storage_ftp._ftp_client(credential, config, 'ftp')
        self.assertEqual(tls_calls, [])

    def test_delete_reuses_one_connection(self):
        calls = {'n': 0}
        ftp = _FakeFTP()

        def fake_client(credential, config, provider):
            calls['n'] += 1
            return ftp, '/'

        with patch.object(storage_ftp, '_ftp_client', fake_client):
            deleted = storage_ftp.delete_objects(
                {'provider': 'ftp', 'access_key': 'u', 'secret_key': 'p'},
                {'endpoint': '/data'},
                ['a.txt', 'b.txt'],
            )
        self.assertEqual(calls['n'], 1)
        self.assertEqual(deleted, 2)
        self.assertEqual(ftp.deleted, ['/data/a.txt', '/data/b.txt'])

    def test_delete_prefix_lists_and_deletes_on_one_connection(self):
        calls = {'n': 0}

        class ListingFTP:
            def __init__(self):
                self.deleted = []
                self.cwd_path = '/'

            def pwd(self):
                return self.cwd_path

            def cwd(self, path):
                self.cwd_path = path

            def mlsd(self):
                return [('a.txt', {'type': 'file', 'size': '3'})]

            def delete(self, key):
                self.deleted.append(key)

            def quit(self):
                pass

            def close(self):
                pass

        ftp = ListingFTP()

        def fake_client(credential, config, provider):
            calls['n'] += 1
            return ftp, '/data'

        with patch.object(storage_ftp, '_ftp_client', fake_client):
            deleted = storage_ftp.delete_prefix(
                {'provider': 'ftp', 'access_key': 'u', 'secret_key': 'p'},
                {'endpoint': '/data'},
                'incoming',
            )
        self.assertEqual(calls['n'], 1)
        self.assertEqual(deleted, 1)
        self.assertEqual(ftp.deleted, ['/data/incoming/a.txt'])


if __name__ == '__main__':
    unittest.main()
