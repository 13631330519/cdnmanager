"""FTP/SFTP/FTPS server-proxy adapter with low-overhead streaming.

Design goals:
- Keep the application server as a control-plane proxy, not a data relay.
- Stream uploads/downloads directly from the remote endpoint whenever possible.
- Avoid creating large temporary files unless the protocol requires buffering.
- Use a single lightweight connection per request; do not persist long-lived sessions.
- FTPS uses explicit TLS (ftplib.FTP_TLS / AUTH TLS) on port 21.
  Implicit FTPS on port 990 is not implemented.
"""

import os
import posixpath
import tempfile
import ssl
from ftplib import FTP, FTP_TLS
from urllib.parse import urlsplit

from flask import Response, stream_with_context
import paramiko


def _default_port(provider):
    # FTP_TLS is explicit FTPS: connect in the clear, then AUTH TLS.
    # That handshake uses the FTP control port (21), not implicit FTPS (990).
    return {'ftp': 21, 'ftps': 21, 'sftp': 22}.get(provider, 21)


def _provider_config(config, provider):
    host = (config.get('host') or config.get('bucket') or '').strip()
    if not host:
        raise ValueError('FTP/SFTP/FTPS 目标需要配置 Host / Bucket')

    if host.startswith('ftp://') or host.startswith('ftps://') or host.startswith('sftp://'):
        parsed = urlsplit(host)
        scheme = parsed.scheme.lower()
        host_name = parsed.hostname or host
        port = parsed.port or _default_port(scheme)
        root = parsed.path or '/'
        if root in ('', '/'):  # allow user to pass just host with optional path
            root = (config.get('endpoint') or config.get('root') or config.get('path') or '/').strip() or '/'
        return host_name, port, root, scheme

    host_name = host
    port = int(config.get('port') or config.get('region') or config.get('ftp_port') or _default_port(provider))
    root = (config.get('endpoint') or config.get('root') or config.get('path') or '/').strip() or '/'
    return host_name, port, root, provider


def _safe_join(base, *parts):
    cleaned = [part for part in parts if part]
    if not cleaned:
        return base or '/'
    path = posixpath.join(base, *[p.strip('/') for p in cleaned])
    return '/' + path.lstrip('/') if not path.startswith('/') else path

def _normalize_dir(path):
    if not path or path == '.':
        return '/'
    return '/' + path.strip('/').replace('\\', '/') if not path.startswith('/') else path


def _ftp_client(credential, config, provider):
    host, port, root, scheme = _provider_config(config, provider)
    if provider == 'ftps':
        ftp = FTP_TLS(context=ssl._create_unverified_context())
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
    host, port, root, _ = _provider_config(config, provider)
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=credential['access_key'], password=credential['secret_key'], timeout=15, banner_timeout=15)
    sftp = client.open_sftp()
    if root and root != '/':
        try:
            sftp.chdir(root)
        except IOError:
            pass
    return client, sftp, root


def list_objects(credential, config, prefix='', delimiter='/', max_keys=500):
    provider = credential.get('provider') or 'ftp'
    prefix = (prefix or '').replace('\\', '/')
    root = _normalize_dir(config.get('endpoint') or config.get('root') or config.get('path') or '/')
    dir_path = _normalize_dir(prefix)
    if dir_path == '/':
        dir_path = root
    elif root not in ('/', ''):
        dir_path = _safe_join(root, prefix)

    folders = []
    files = []

    try:
        if provider == 'sftp':
            client, sftp, _ = _sftp_client(credential, config, provider)
            try:
                names = sftp.listdir_attr(dir_path)
                for entry in names[:max_keys]:
                    name = entry.filename
                    full = _safe_join(dir_path, name)
                    if entry.st_mode and (entry.st_mode & 0o170000) == 0o040000:
                        folders.append({'prefix': full.rstrip('/') + '/', 'name': name})
                    else:
                        files.append({'key': full.lstrip('/'), 'name': name, 'size': entry.st_size, 'last_modified': None})
            finally:
                sftp.close(); client.close()
            return {'prefix': prefix, 'folders': folders, 'files': files}

        ftp, _ = _ftp_client(credential, config, provider)
        try:
            current = ftp.pwd()
            try:
                ftp.cwd(dir_path)
            except Exception:
                ftp.cwd(root)
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
                    folders.append({'prefix': full.rstrip('/') + '/', 'name': name})
                else:
                    files.append({'key': full.lstrip('/'), 'name': name, 'size': int(facts.get('size', 0) or 0), 'last_modified': facts.get('modify')})
            try:
                ftp.cwd(current)
            except Exception:
                pass
        finally:
            ftp.quit()
        return {'prefix': prefix, 'folders': folders[:max_keys], 'files': files[:max_keys]}
    except Exception as exc:
        return {'prefix': prefix, 'folders': [], 'files': [], 'error': str(exc)}


def _path_for_upload(config, key):
    root = (config.get('endpoint') or config.get('root') or config.get('path') or '/').strip('/')
    key = (key or '').replace('\\', '/').strip('/')
    if root:
        return '/' + '/'.join([p for p in [root, key] if p]) if key else '/' + root
    return '/' + key if key else '/'


def upload_file(credential, config, remote_prefix, uploaded_file, resume_from=0):
    provider = credential.get('provider') or 'ftp'
    remote_prefix = (remote_prefix or '').replace('\\', '/').strip('/')
    remote_name = (uploaded_file.filename or 'upload.bin').replace('\\', '/')
    remote_key = _path_for_upload(config, posixpath.join(remote_prefix, remote_name) if remote_prefix else remote_name)

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
            sftp.close(); client.close()

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


def mkdir(credential, config, directory_name):
    provider = credential.get('provider') or 'ftp'
    remote_dir = _path_for_upload(config, directory_name)
    if provider == 'sftp':
        client, sftp, _ = _sftp_client(credential, config, provider)
        try:
            sftp.mkdir(remote_dir)
            return {'path': remote_dir, 'ok': True}
        finally:
            sftp.close(); client.close()
    ftp, _ = _ftp_client(credential, config, provider)
    try:
        ftp.mkd(remote_dir)
        return {'path': remote_dir, 'ok': True}
    finally:
        ftp.quit()


def rename(credential, config, old_key, new_name):
    provider = credential.get('provider') or 'ftp'
    old_path = _path_for_upload(config, old_key)
    new_path = _path_for_upload(config, new_name)
    if provider == 'sftp':
        client, sftp, _ = _sftp_client(credential, config, provider)
        try:
            sftp.rename(old_path, new_path)
            return {'ok': True, 'old': old_path, 'new': new_path}
        finally:
            sftp.close(); client.close()
    ftp, _ = _ftp_client(credential, config, provider)
    try:
        ftp.rename(old_path, new_path)
        return {'ok': True, 'old': old_path, 'new': new_path}
    finally:
        ftp.quit()


def delete_objects(credential, config, keys):
    provider = credential.get('provider') or 'ftp'
    root = _normalize_dir(config.get('endpoint') or config.get('root') or config.get('path') or '/')
    count = 0
    for key in keys:
        remote_key = _path_for_upload(config, key)
        if provider == 'sftp':
            client, sftp, _ = _sftp_client(credential, config, provider)
            try:
                if sftp.stat(remote_key).st_mode and (sftp.stat(remote_key).st_mode & 0o170000) == 0o040000:
                    sftp.rmdir(remote_key)
                else:
                    sftp.remove(remote_key)
                    count += 1
            except Exception:
                pass
            finally:
                sftp.close(); client.close()
            continue

        ftp, _ = _ftp_client(credential, config, provider)
        try:
            try:
                ftp.delete(remote_key)
                count += 1
            except Exception:
                try:
                    ftp.rmd(remote_key)
                except Exception:
                    pass
        finally:
            ftp.quit()
    return count


def delete_prefix(credential, config, prefix):
    listing = list_objects(credential, config, prefix=prefix)
    entries = (listing.get('files') or []) + (listing.get('folders') or [])
    total = 0
    for item in entries:
        if item.get('prefix'):
            total += delete_prefix(credential, config, item['prefix'])
        else:
            total += delete_objects(credential, config, [item.get('key')])
    return total


def _stream_file_from_sftp(sftp, remote_key):
    size = sftp.stat(remote_key).st_size

    def generate():
        with sftp.open(remote_key, 'rb') as file_obj:
            while True:
                chunk = file_obj.read(65536)
                if not chunk:
                    break
                yield chunk

    return Response(stream_with_context(generate()), mimetype='application/octet-stream', headers={
        'Content-Length': str(size),
        'Content-Disposition': f'attachment; filename="{os.path.basename(remote_key)}"',
    })


def _stream_file_from_ftp(ftp, remote_key):
    spool = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)

    def generate():
        try:
            def _write(data):
                spool.write(data)
            ftp.retrbinary(f'RETR {remote_key}', _write, blocksize=65536)
            spool.seek(0)
            while True:
                chunk = spool.read(65536)
                if not chunk:
                    break
                yield chunk
        finally:
            spool.close()

    return Response(stream_with_context(generate()), mimetype='application/octet-stream', headers={
        'Content-Disposition': f'attachment; filename="{os.path.basename(remote_key)}"',
    })


def stream_download(credential, config, key, range_header=None):
    provider = credential.get('provider') or 'ftp'
    remote_key = _path_for_upload(config, key)
    if provider == 'sftp':
        client, sftp, _ = _sftp_client(credential, config, provider)
        try:
            stat = sftp.stat(remote_key)
            start = 0
            end = max(0, stat.st_size - 1)
            if range_header:
                try:
                    unit, value = range_header.split('=', 1)
                    if unit.lower() == 'bytes':
                        start_text, end_text = value.split('-', 1)
                        start = int(start_text) if start_text else max(0, end - int(end_text or 0))
                        end = int(end_text) if end_text else end
                except Exception:
                    start, end = 0, max(0, stat.st_size - 1)
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
                response.headers['Content-Range'] = f'bytes {start}-{end}/{stat.st_size}'
            return response
        finally:
            sftp.close(); client.close()

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
    remote_key = _path_for_upload(config, object_key)
    try:
        if provider == 'sftp':
            client, sftp, _ = _sftp_client(credential, config, provider)
            try:
                stat = sftp.stat(remote_key)
                return {'ok': True, 'size': stat.st_size, 'etag': None}
            finally:
                sftp.close(); client.close()
        ftp, _ = _ftp_client(credential, config, provider)
        try:
            size = ftp.size(remote_key)
            return {'ok': True, 'size': size, 'etag': None}
        finally:
            ftp.quit()
    except Exception as exc:
        return {'ok': False, 'error': str(exc)}
