/* Remote browser plus shared state for the upload page. */
(function (app) {
    app.MULTIPART_THRESHOLD = 100 * 1024 * 1024;
    app.PART_SIZE = 8 * 1024 * 1024;
    app.BATCH_INIT_SIZE = 1000;
    app.PRESIGN_BATCH_SIZE = 50;
    app.MAX_SMALL_CONCURRENCY = 20;
    app.MAX_LARGE_CONCURRENCY = 3;
    app.MAX_PART_CONCURRENCY = 6;
    app.FOLDER_FLUSH_SIZE = 200;
    app.DIR_WALK_CONCURRENCY = 6;
    app.LOCAL_ROW_HEIGHT = 40;
    app.LOCAL_VIRTUAL_OVERSCAN = 10;
    app.LOCAL_BUILD_YIELD_EVERY = 250;
    app.PROXY_PROVIDERS = new Set(['ftp', 'sftp', 'ftps']);

    const appRoot = document.getElementById('storageManagerApp');
    if (!appRoot) return;

    app.state = {
        remotePrefix: '',
        remoteFolders: [],
        remoteFiles: [],
        canDelete: false,
        localTree: [],
        localFiles: [],
        localItems: [],
        folderByPath: new Map(),
        fileByPath: new Map(),
        uploading: false,
        cancelled: false,
        fileProgress: {},
        doneBytes: 0,
        totalBytes: 0,
        currentJobId: null,
        eventSource: null,
        localRenderOffset: 0,
        openManifestJobId: null,
        localVisibleCache: [],
        localListBound: false,
        localBuilding: false,
    };

    app.els = {
        target: document.getElementById('storageTargetSelect'),
        remotePath: document.getElementById('remotePathInput'),
        remoteBrowse: document.getElementById('remoteBrowseBtn'),
        remoteUp: document.getElementById('remoteUpBtn'),
        remoteMkdir: document.getElementById('remoteMkdirBtn'),
        remoteRename: document.getElementById('remoteRenameBtn'),
        remoteDownload: document.getElementById('remoteDownloadBtn'),
        remoteDelete: document.getElementById('remoteDeleteBtn'),
        remoteSelectAll: document.getElementById('remoteSelectAll'),
        remoteList: document.getElementById('remoteFileList'),
        remoteEmpty: document.getElementById('remoteEmptyHint'),
        remoteBreadcrumb: document.getElementById('remoteBreadcrumb'),
        localFolder: document.getElementById('localFolderInput'),
        localFile: document.getElementById('localFileInput'),
        localClear: document.getElementById('localClearBtn'),
        localUpload: document.getElementById('localUploadBtn'),
        localCancel: document.getElementById('localCancelBtn'),
        localSelectAll: document.getElementById('localSelectAll'),
        localList: document.getElementById('localFileList'),
        localListWrap: document.getElementById('localListWrap'),
        localEmpty: document.getElementById('localEmptyHint'),
        localSummary: document.getElementById('localSummary'),
        globalWrap: document.getElementById('globalProgressWrap'),
        globalText: document.getElementById('globalProgressText'),
        globalPercent: document.getElementById('globalProgressPercent'),
        globalBar: document.getElementById('globalProgressBar'),
        jobHistory: document.getElementById('uploadJobHistory'),
        jobHistoryBody: document.getElementById('uploadJobHistoryBody'),
    };

    app.userRole = appRoot.dataset.userRole || 'user';
    app.canDeleteDefault = appRoot.dataset.canDeleteDefault === '1';

    app.formatBytes = function (bytes) {
        if (!bytes) return '0 B';
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
        return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
    }

    app.formatDateTime = function (value) {
        if (!value) return '—';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return String(value);
        return date.toLocaleString('zh-CN', {
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
            hour: '2-digit',
            minute: '2-digit',
        });
    }

    app.formatFetchError = function (err, phase) {
        const message = err && err.message ? err.message : String(err);
        if (message === 'Failed to fetch') {
            return `${phase}失败：浏览器无法连接对象存储，请检查 Bucket CORS（PUT/GET/HEAD + 暴露 ETag）`;
        }
        return `${phase}失败：${message}`;
    }

    app.fetchJson = async function (url, options) {
        let response;
        try {
            response = await fetch(url, options);
        } catch (err) {
            throw new Error(app.formatFetchError(err, '请求'));
        }
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || data.message || `HTTP ${response.status}`);
        return data;
    }

    app.xhrPut = function (url, body, onProgress) {
        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open('PUT', url);
            xhr.responseType = 'text';
            if (onProgress) {
                xhr.upload.onprogress = (event) => {
                    if (event.lengthComputable) onProgress(event.loaded, event.total);
                };
            }
            xhr.onload = () => {
                if (xhr.status >= 200 && xhr.status < 300) {
                    resolve(xhr);
                } else {
                    reject(new Error(`直传失败 HTTP ${xhr.status}: ${(xhr.responseText || '').slice(0, 120)}`));
                }
            };
            xhr.onerror = () => reject(new Error(app.formatFetchError({ message: 'Failed to fetch' }, '存储直传')));
            xhr.send(body);
        });
    }

    app.updateGlobalProgress = function () {
        const inFlight = Object.values(app.state.fileProgress).reduce((sum, n) => sum + (n || 0), 0);
        const uploaded = app.state.doneBytes + inFlight;
        const total = app.state.totalBytes || 1;
        const percent = Math.min(100, Math.round((uploaded / total) * 100));
        app.els.globalBar.style.width = `${percent}%`;
        app.els.globalPercent.textContent = `${percent}%`;
    }

    app.setGlobalProgressVisible = function (visible) {
        app.els.globalWrap.classList.toggle('hidden', !visible);
    }

    app.canDeleteNow = function () {
        if (app.canDeleteDefault) return true;
        const opt = app.els.target.selectedOptions[0];
        return opt && opt.dataset.allowUserDelete === '1';
    }

    app.renderBreadcrumb = function () {
        const parts = app.state.remotePrefix.replace(/\/+$/, '').split('/').filter(Boolean);
        let html = `<button type="button" class="remote-crumb hover:underline" data-prefix="">根目录</button>`;
        let acc = '';
        parts.forEach((part) => {
            acc = acc ? `${acc}/${part}` : part;
            html += `<span class="text-gray-400 mx-1">/</span><button type="button" class="remote-crumb hover:underline" data-prefix="${acc}/">${part}</button>`;
        });
        app.els.remoteBreadcrumb.innerHTML = html;
        app.els.remoteBreadcrumb.querySelectorAll('.remote-crumb').forEach((btn) => {
            btn.addEventListener('click', () => {
                app.state.remotePrefix = btn.dataset.prefix || '';
                app.els.remotePath.value = app.state.remotePrefix;
                app.loadRemoteList();
            });
        });
    }

    app.sortNameAsc = function (a, b) {
        return String(a.name || '').localeCompare(String(b.name || ''), 'zh-CN', { sensitivity: 'base' });
    }

    app.renderRemoteList = function () {
        const folders = [...app.state.remoteFolders].sort(app.sortNameAsc);
        const files = [...app.state.remoteFiles].sort(app.sortNameAsc);
        const hasContent = folders.length || files.length;
        app.els.remoteEmpty.classList.toggle('hidden', hasContent);
        app.els.remoteList.innerHTML = '';

        folders.forEach((folder) => {
            const tr = document.createElement('tr');
            tr.className = 'hover:bg-indigo-50';
            tr.innerHTML = `
                <td class="px-3 py-2"><input type="checkbox" class="remote-check rounded" data-type="folder" data-prefix="${folder.prefix}"></td>
                <td class="px-3 py-2"><button type="button" class="remote-folder text-indigo-700 hover:underline text-left" data-prefix="${folder.prefix}"><i class="fas fa-folder text-amber-500 mr-2"></i>${app.escapeHtml(folder.name)}</button></td>
                <td class="px-3 py-2 text-right text-gray-400">—</td>
                <td class="px-3 py-2 text-right text-gray-400">—</td>`;
            app.els.remoteList.appendChild(tr);
        });

        files.forEach((file) => {
            const tr = document.createElement('tr');
            tr.className = 'hover:bg-gray-50';
            tr.innerHTML = `
                <td class="px-3 py-2"><input type="checkbox" class="remote-check rounded" data-type="file" data-key="${file.key}"></td>
                <td class="px-3 py-2 truncate max-w-[240px]" title="${app.escapeHtml(file.key)}"><i class="fas fa-file text-gray-400 mr-2"></i>${app.escapeHtml(file.name)}</td>
                <td class="px-3 py-2 text-right text-gray-500">${app.formatBytes(file.size)}</td>
                <td class="px-3 py-2 text-right text-gray-500 whitespace-nowrap">${app.formatDateTime(file.last_modified)}</td>`;
            app.els.remoteList.appendChild(tr);
        });

        app.els.remoteDelete.classList.toggle('hidden', !app.state.canDelete);
        app.bindRemoteEvents();
    }

    app.escapeHtml = function (value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    app.bindRemoteEvents = function () {
        app.els.remoteList.querySelectorAll('.remote-check').forEach((cb) => {
            cb.addEventListener('change', app.updateRemoteActions);
        });
    }

    app.applyRemoteListing = function (data) {
        app.state.canDelete = !!data.can_delete;
        app.state.remoteFolders = data.folders || [];
        app.state.remoteFiles = data.files || [];
        if (typeof data.remote_prefix === 'string') {
            app.state.remotePrefix = data.remote_prefix;
            app.els.remotePath.value = data.remote_prefix;
        }
        app.renderBreadcrumb();
        app.renderRemoteList();
        app.updateRemoteActions();
    }

    app.loadRemoteList = async function () {
        const targetId = app.els.target.value;
        const prefix = app.els.remotePath.value.trim();
        const data = await app.fetchJson(`/api/storage/list?target_id=${encodeURIComponent(targetId)}&prefix=${encodeURIComponent(prefix)}`);
        app.applyRemoteListing(data);
    }

    app.updateRemoteActions = function () {
        const checked = app.els.remoteList.querySelectorAll('.remote-check:checked');
        const has = checked.length > 0;
        app.els.remoteDownload.disabled = !has;
        app.els.remoteRename.disabled = !(has && checked.length === 1);
        app.els.remoteDelete.disabled = !has || !app.state.canDelete;
    }

    app.selectedStorageProvider = function () {
        const opt = app.els.target && app.els.target.selectedOptions && app.els.target.selectedOptions[0];
        return ((opt && opt.dataset.provider) || '').toLowerCase();
    }

    app.isProxyUploadTarget = function () {
        return app.PROXY_PROVIDERS.has(app.selectedStorageProvider());
    }

    app.updateTransportHint = function () {
        const proxy = app.isProxyUploadTarget();
        const mode = document.getElementById('localTransferMode');
        if (mode) {
            mode.textContent = proxy
                ? '经服务器代理上传（FTP / SFTP / FTPS）'
                : '直传不经服务器 · 大文件自动分片';
        }
        const hint = document.getElementById('uploadTransportHint');
        if (!hint) return;
        hint.className = proxy
            ? 'text-xs text-sky-800 bg-sky-50 border border-sky-200 rounded-lg p-3'
            : 'text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-3';
        hint.innerHTML = proxy
            ? '当前目标为 FTP / SFTP / FTPS：文件通过服务器 <code>POST /api/storage/upload</code> 代理写入，不使用预签名直传，也不依赖对象存储 ETag。'
            : '传输均走客户端 ↔ 对象存储直链，服务器仅签发凭证与列举目录。Job 记录保留至手动清理，支持失败 manifest CSV 导出。若直传失败，请确认 Bucket CORS 已允许 PUT/GET/HEAD 并暴露 <code>ETag</code>。';
    }

    app.downloadSelectedRemote = async function () {
        const keys = [];
        app.els.remoteList.querySelectorAll('.remote-check:checked').forEach((cb) => {
            if (cb.dataset.type === 'file') keys.push(cb.dataset.key);
        });
        if (!keys.length) return;
        const data = await app.fetchJson('/api/storage/download-urls', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_id: app.els.target.value, keys }),
        });
        data.urls.forEach(({ url }) => {
            window.open(url, '_blank');
        });
    }

    app.deleteSelectedRemote = async function () {
        const keys = [];
        const prefixes = [];
        app.els.remoteList.querySelectorAll('.remote-check:checked').forEach((cb) => {
            if (cb.dataset.type === 'file') keys.push(cb.dataset.key);
            if (cb.dataset.type === 'folder') prefixes.push(cb.dataset.prefix);
        });
        if (!keys.length && !prefixes.length) return;
        if (!confirm(`确认删除 ${keys.length} 个文件${prefixes.length ? ` 和 ${prefixes.length} 个文件夹` : ''}？`)) return;
        await app.fetchJson('/api/storage/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_id: app.els.target.value, keys, prefixes }),
        });
        await app.loadRemoteList();
    }

    app.mkdirSelectedRemote = async function () {
        const folderName = window.prompt('请输入新文件夹名称：');
        if (!folderName || !folderName.trim()) return;
        const name = folderName.trim();
        await app.fetchJson('/api/storage/mkdir', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_id: app.els.target.value, directory_name: `${app.els.remotePath.value || ''}${name}` }),
        });
        await app.loadRemoteList();
    }

    app.renameSelectedRemote = async function () {
        const checked = [...els.remoteList.querySelectorAll('.remote-check:checked')];
        const item = checked.length === 1 ? checked[0] : null;
        if (!item) return;
        const currentName = item.dataset.type === 'file' ? item.dataset.key : item.dataset.prefix;
        const nextName = window.prompt('请输入新名称：', currentName.split('/').filter(Boolean).pop() || '');
        if (!nextName || !nextName.trim()) return;
        const oldKey = item.dataset.type === 'file' ? item.dataset.key : item.dataset.prefix;
        await app.fetchJson('/api/storage/rename', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_id: app.els.target.value, old_key: oldKey, new_name: `${(app.els.remotePath.value || '').replace(/\/+$/, '')}/${nextName.trim()}` }),
        });
        await app.loadRemoteList();
    }

})(window.CdnUpload = window.CdnUpload || {});
