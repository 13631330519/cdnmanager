"""FTP/SFTP/FTPS server-proxy adapter with low-overhead streaming.

Design goals:
- Keep the application server as a control-plane proxy, not a data relay.
- Stream uploads/downloads directly from the remote endpoint whenever possible.
- Avoid creating large temporary files unless the protocol requires buffering.
- Use one connection per request. Multi-key delete and recursive delete reuse it.
- FTPS uses explicit TLS (ftplib.FTP_TLS / AUTH TLS) on port 21.
  Implicit FTPS on port 990 is not implemented.

TLS / host keys default to verified. Set target_config['insecure_tls'] to
restore the previous unverified FTPS context and SFTP AutoAddPolicy. That flag
is for existing deployments that cannot present a certificate or known_hosts.
"""

import os
import posixpath
import stat
import tempfile
import ssl
from contextlib import contextmanager
from ftplib import FTP, FTP_TLS
from urllib.parse import urlsplit

from flask import Response
import paramiko


def _default_port(provider):
    # FTP_TLS is explicit FTPS: connect in the clear, then AUTH TLS.
    # That handshake uses the FTP control port (21), not implicit FTPS (990).
    return {'ftp': 21, 'ftps': 21, 'sftp': 22}.get(provider, 21)


def insecure_tls_enabled(config):
    """True only when the target explicitly opts out of TLS/host-key checks."""
    value = (config or {}).get('insecure_tls')
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return bool(value)


def _as_port(value, default):
    if value is None or value == '':
        return default
    try:
        port = int(value)
    except (TypeError, ValueError):
        return default
    if not 1 <= port <= 65535:
        return default
    return port


def _ftp_root(config):
    """Remote root directory.

    Prefer host/port/root fields. ``endpoint`` (and ``path``) remain the legacy
    form-field mapping used by existing storage targets.
    """
    config = config or {}
    for field in ('root', 'path', 'endpoint'):
        raw = config.get(field)
        if raw is None:
            continue
        text = str(raw).strip().replace('\\', '/')
        if text == '':
            continue
        if text == '/':
            return '/'
        return '/' + text.strip('/')
    return '/'


def _provider_config(config, provider):
    """Return ``(host, port, root, scheme)``.

    Preferred fields are host, port, and root. Bucket, region, and endpoint
    stay accepted so rows saved by the admin form keep working. A host value
    may also be an ftp://, ftps://, or sftp:// URL.
    """
    config = config or {}
    host = (config.get('host') or config.get('bucket') or '').strip()
    if not host:
        raise ValueError('FTP/SFTP/FTPS 目标需要配置 Host / Bucket')

    if host.startswith(('ftp://', 'ftps://', 'sftp://')):
        parsed = urlsplit(host)
        scheme = (parsed.scheme or provider or 'ftp').lower()
        host_name = parsed.hostname or host
        port = parsed.port or _default_port(scheme)
        url_root = (parsed.path or '').strip()
        if url_root in ('', '/'):
            root = _ftp_root(config)
        else:
            root = '/' + url_root.strip('/')
        return host_name, port, root, scheme

    port = _as_port(config.get('port'), None)
    if port is None:
        port = _as_port(config.get('region'), None)
    if port is None:
        port = _as_port(config.get('ftp_port'), _default_port(provider))
    return host, port, _ftp_root(config), provider


def resolve_remote_path(config, key):
    """Absolute remote path for one object key.

    ``key`` matches ``storage_service.build_object_key`` (base_path + prefix +
    relative path, no leading slash) or a browser key relative to the FTP root.
    The root is applied exactly once.
    """
    root = _ftp_root(config)
    normalized = (key or '').replace('\\', '/').strip('/')
    if not normalized:
        return root
    if root == '/':
        return '/' + normalized
    return root.rstrip('/') + '/' + normalized


def _relative_key(config, absolute_path):
    """Strip the FTP root so listing keys stay aligned with object keys."""
    root = _ftp_root(config).rstrip('/')
    path = '/' + (absolute_path or '').replace('\\', '/').lstrip('/')
    if root and root != '/' and (path == root or path.startswith(root + '/')):
        path = path[len(root):]
    return path.lstrip('/')


def _safe_join(base, *parts):
    cleaned = [part for part in parts if part]
    if not cleaned:
        return base or '/'
    path = posixpath.join(base, *[p.strip('/') for p in cleaned])
    return '/' + path.lstrip('/') if not path.startswith('/') else path


def _object_key(config, remote_prefix, relative_path):
    # Lazy import: storage_service imports this module at load time.
    from cdnmanager.providers.storage.storage_service import build_object_key
    return build_object_key(config, remote_prefix, relative_path)


def _ftp_client(credential, config, provider):
    host, port, root, _scheme = _provider_config(config, provider)
    if provider == 'ftps':
        context = ssl._create_unverified_context() if insecure_tls_enabled(config) else ssl.create_default_context()
        ftp = FTP_TLS(context=context)
        ftp.connect(host, port, timeout=15)
        ftp.login(credential['access_key'], credential['secret_key'])
        ftp.prot_p()
        ftp.set_pasv(True)
        if root and root != '/':
            try:
                ftp.cwd(root)
            except Exception:
                pass
        return ftp, root
    ftp = FTP()
    ftp.connect(host, port, timeout=15)
    ftp.login(credential['access_key'], credential['secret_key'])
    ftp.set_pasv(True)
    if root and root != '/':
        try:
            ftp.cwd(root)
        except Exception:
            pass
    return ftp, root


def _sftp_client(credential, config, provider):
    host, port, root, _scheme = _provider_config(config, provider)
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    if insecure_tls_enabled(config):
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    else:
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(
        host,
        port=port,
        username=credential['access_key'],
        password=credential['secret_key'],
        timeout=15,
        banner_timeout=15,
    )
    sftp = client.open_sftp()
    if root and root != '/':
        try:
            sftp.chdir(root)
        except IOError:
            pass
    return client, sftp, root


@contextmanager
def _connection(credential, config, provider):
    """One FTP or SFTP session for every key touched by this request."""
    if provider == 'sftp':
        client, sftp, _root = _sftp_client(credential, config, provider)
        try:
            yield sftp
        finally:
            try:
                sftp.close()
            finally:
                client.close()
        return
    ftp, _root = _ftp_client(credential, config, provider)
    try:
        yield ftp
    finally:
        try:
            ftp.quit()
        except Exception:
            try:
                ftp.close()
            except Exception:
                pass


def _is_dir_mode(mode):
    return bool(mode) and stat.S_ISDIR(mode)


def _list_sftp_dir(sftp, config, prefix):
    dir_path = resolve_remote_path(config, (prefix or '').strip('/'))
    folders = []
    files = []
    for entry in sftp.listdir_attr(dir_path):
        name = entry.filename
        if name in ('.', '..'):
            continue
        full = _safe_join(dir_path, name)
        if _is_dir_mode(entry.st_mode):
            rel = _relative_key(config, full)
            folders.append({'prefix': rel.rstrip('/') + '/', 'name': name})
        else:
            files.append({
                'key': _relative_key(config, full),
                'name': name,
                'size': entry.st_size,
                'last_modified': None,
            })
    return folders, files


def _list_ftp_dir(ftp, config, prefix):
    dir_path = resolve_remote_path(config, (prefix or '').strip('/'))
    folders = []
    files = []
    current = None
    try:
        current = ftp.pwd()
    except Exception:
        current = None
    try:
        # Do not fall back to the root listing. A missing directory must not
        # be reported as the root, or a later delete could target the wrong keys.
        ftp.cwd(dir_path)
        entries = ftp.mlsd() if hasattr(ftp, 'mlsd') else ftp.nlst()
        for item in entries:
            if isinstance(item, tuple):
                name, facts = item
            else:
                name = item
                facts = {}
            if name in ('.', '..'):
                continue
            full = _safe_join(dir_path, name)
            if facts.get('type') == 'dir':
                rel = _relative_key(config, full)
                folders.append({'prefix': rel.rstrip('/') + '/', 'name': name})
            else:
                files.append({
                    'key': _relative_key(config, full),
                    'name': name,
                    'size': int(facts.get('size', 0) or 0),
                    'last_modified': facts.get('modify'),
                })
    finally:
        if current:
            try:
                ftp.cwd(current)
            except Exception:
                pass
    return folders, files


def _sorted_listing(prefix, folders, files):
    folders.sort(key=lambda item: item['name'].lower())
    files.sort(key=lambda item: item['name'].lower())
    return {'prefix': prefix, 'folders': folders, 'files': files}


def list_objects(credential, config, prefix='', delimiter='/', max_keys=500):
    provider = credential.get('provider') or 'ftp'
    prefix = (prefix or '').replace('\\', '/')
    try:
        with _connection(credential, config, provider) as conn:
            if provider == 'sftp':
                folders, files = _list_sftp_dir(conn, config, prefix)
            else:
                folders, files = _list_ftp_dir(conn, config, prefix)
        return _sorted_listing(prefix, folders, files)
    except Exception as exc:
        return {'prefix': prefix, 'folders': [], 'files': [], 'error': str(exc)}


def upload_file(credential, config, remote_prefix, uploaded_file, resume_from=0):
    provider = credential.get('provider') or 'ftp'
    remote_prefix = (remote_prefix or '').replace('\\', '/').strip('/')
    remote_name = (uploaded_file.filename or 'upload.bin').replace('\\', '/')
    remote_key = resolve_remote_path(config, _object_key(config, remote_prefix, remote_name))

    if provider == 'sftp':
        client, sftp, _ = _sftp_client(credential, config, provider)
        try:
            uploaded_file.stream.seek(0, os.SEEK_END)
            size = uploaded_file.stream.tell()
            uploaded_file.stream.seek(0)
            if resume_from > 0:
                remote_exists = False
                try:
                    sftp.stat(remote_key)
                    remote_exists = True
                except IOError:
                    pass
                if not remote_exists:
                    resume_from = 0
            if resume_from > 0:
                uploaded_file.stream.seek(resume_from)
                with sftp.open(remote_key, 'ab') as handle:
                    while True:
                        chunk = uploaded_file.stream.read(65536)
                        if not chunk:
                            break
                        handle.write(chunk)
                return {'path': remote_key, 'size': size, 'resumed': True}
            sftp.putfo(uploaded_file.stream, remote_key)
            return {'path': remote_key, 'size': size}
        finally:
            sftp.close()
            client.close()

    ftp, _ = _ftp_client(credential, config, provider)
    try:
        uploaded_file.stream.seek(0, os.SEEK_END)
        size = uploaded_file.stream.tell()
        uploaded_file.stream.seek(0)
        if resume_from > 0:
            try:
                ftp.size(remote_key)
                ftp.sendcmd(f'REST {resume_from}')
                uploaded_file.stream.seek(resume_from)
                ftp.storbinary(f'STOR {remote_key}', uploaded_file.stream, blocksize=65536)
                return {'path': remote_key, 'size': size, 'resumed': True}
            except Exception:
                uploaded_file.stream.seek(0)
        ftp.storbinary(f'STOR {remote_key}', uploaded_file.stream, blocksize=65536)
        return {'path': remote_key, 'size': size}
    finally:
        ftp.quit()


def _ensure_remote_dir_sftp(sftp, remote_dir):
    parts = [part for part in remote_dir.strip('/').split('/') if part]
    current = ''
    for part in parts:
        current = f'{current}/{part}'
        try:
            sftp.stat(current)
        except IOError:
            sftp.mkdir(current)


def _ensure_remote_dir_ftp(ftp, remote_dir):
    parts = [part for part in remote_dir.strip('/').split('/') if part]
    current = ''
    for part in parts:
        current = f'{current}/{part}'
        try:
            ftp.mkd(current)
        except Exception:
            pass


def mkdir(credential, config, directory_name):
    provider = credential.get('provider') or 'ftp'
    remote_dir = resolve_remote_path(config, directory_name)
    if provider == 'sftp':
        client, sftp, _ = _sftp_client(credential, config, provider)
        try:
            _ensure_remote_dir_sftp(sftp, remote_dir)
            return {'path': remote_dir, 'ok': True}
        finally:
            sftp.close()
            client.close()
    ftp, _ = _ftp_client(credential, config, provider)
    try:
        _ensure_remote_dir_ftp(ftp, remote_dir)
        return {'path': remote_dir, 'ok': True}
    finally:
        ftp.quit()


def rename(credential, config, old_key, new_name):
    provider = credential.get('provider') or 'ftp'
    old_path = resolve_remote_path(config, old_key)
    new_path = resolve_remote_path(config, new_name)
    if provider == 'sftp':
        client, sftp, _ = _sftp_client(credential, config, provider)
        try:
            sftp.rename(old_path, new_path)
            return {'ok': True, 'old': old_path, 'new': new_path}
        finally:
            sftp.close()
            client.close()
    ftp, _ = _ftp_client(credential, config, provider)
    try:
        ftp.rename(old_path, new_path)
        return {'ok': True, 'old': old_path, 'new': new_path}
    finally:
        ftp.quit()


def _delete_sftp_key(sftp, remote_key):
    try:
        info = sftp.stat(remote_key)
        if _is_dir_mode(info.st_mode):
            sftp.rmdir(remote_key)
            return 0
        sftp.remove(remote_key)
        return 1
    except Exception:
        return 0


def _delete_ftp_key(ftp, remote_key):
    try:
        ftp.delete(remote_key)
        return 1
    except Exception:
        try:
            ftp.rmd(remote_key)
        except Exception:
            pass
        return 0


def delete_objects(credential, config, keys):
    provider = credential.get('provider') or 'ftp'
    if not keys:
        return 0
    count = 0
    with _connection(credential, config, provider) as conn:
        for key in keys:
            remote_key = resolve_remote_path(config, key)
            if provider == 'sftp':
                count += _delete_sftp_key(conn, remote_key)
            else:
                count += _delete_ftp_key(conn, remote_key)
    return count


def _delete_prefix_on(conn, provider, config, prefix):
    try:
        if provider == 'sftp':
            folders, files = _list_sftp_dir(conn, config, prefix)
        else:
            folders, files = _list_ftp_dir(conn, config, prefix)
    except Exception:
        return 0
    total = 0
    for folder in folders:
        total += _delete_prefix_on(conn, provider, config, folder.get('prefix') or '')
    for item in files:
        remote_key = resolve_remote_path(config, item.get('key'))
        if provider == 'sftp':
            total += _delete_sftp_key(conn, remote_key)
        else:
            total += _delete_ftp_key(conn, remote_key)
    return total


def delete_prefix(credential, config, prefix):
    provider = credential.get('provider') or 'ftp'
    try:
        with _connection(credential, config, provider) as conn:
            return _delete_prefix_on(conn, provider, config, prefix)
    except Exception:
        return 0


def stream_download(credential, config, key, range_header=None):
    provider = credential.get('provider') or 'ftp'
    remote_key = resolve_remote_path(config, key)
    if provider == 'sftp':
        client, sftp, _ = _sftp_client(credential, config, provider)
        try:
            stat_result = sftp.stat(remote_key)
            start = 0
            end = max(0, stat_result.st_size - 1)
            if range_header:
                try:
                    unit, value = range_header.split('=', 1)
                    if unit.lower() == 'bytes':
                        start_text, end_text = value.split('-', 1)
                        start = int(start_text) if start_text else max(0, end - int(end_text or 0))
                        end = int(end_text) if end_text else end
                except Exception:
                    start, end = 0, max(0, stat_result.st_size - 1)
            payload = sftp.open(remote_key, 'rb')
            payload.seek(start)
            data = payload.read(end - start + 1)
            payload.close()
            response = Response(data, mimetype='application/octet-stream', headers={
                'Content-Length': str(len(data)),
                'Content-Disposition': f'attachment; filename="{os.path.basename(remote_key)}"',
                'Accept-Ranges': 'bytes',
            })
            if range_header:
                response.status_code = 206
                response.headers['Content-Range'] = f'bytes {start}-{end}/{stat_result.st_size}'
            return response
        finally:
            sftp.close()
            client.close()

    ftp, _ = _ftp_client(credential, config, provider)
    try:
        total = ftp.size(remote_key)
        start = 0
        end = max(0, total - 1)
        if range_header:
            try:
                unit, value = range_header.split('=', 1)
                if unit.lower() == 'bytes':
                    start_text, end_text = value.split('-', 1)
                    start = int(start_text) if start_text else max(0, end - int(end_text or 0))
                    end = int(end_text) if end_text else end
            except Exception:
                start, end = 0, max(0, total - 1)
        spool = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
        ftp.retrbinary(f'RETR {remote_key}', spool.write, rest=start if start else None)
        spool.seek(0)
        chunk = spool.read(end - start + 1) if start or end < total - 1 else spool.read()
        response = Response(chunk, mimetype='application/octet-stream', headers={
            'Content-Length': str(len(chunk)),
            'Content-Disposition': f'attachment; filename="{os.path.basename(remote_key)}"',
            'Accept-Ranges': 'bytes',
        })
        if range_header:
            response.status_code = 206
            response.headers['Content-Range'] = f'bytes {start}-{end}/{total}'
        return response
    finally:
        ftp.quit()


def presign_get(credential, config, object_key):
    raise NotImplementedError('FTP/SFTP/FTPS 目标需要走代理下载，不能直接返回预签名 URL')


def verify_object(credential, config, object_key, expected_size):
    provider = credential.get('provider') or 'ftp'
    remote_key = resolve_remote_path(config, object_key)
    try:
        if provider == 'sftp':
            client, sftp, _ = _sftp_client(credential, config, provider)
            try:
                stat_result = sftp.stat(remote_key)
                return {'ok': True, 'size': stat_result.st_size, 'etag': None}
            finally:
                sftp.close()
                client.close()
        ftp, _ = _ftp_client(credential, config, provider)
        try:
            size = ftp.size(remote_key)
            return {'ok': True, 'size': size, 'etag': None}
        finally:
            ftp.quit()
    except Exception as exc:
        return {'ok': False, 'error': str(exc)}
