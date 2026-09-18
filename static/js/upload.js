(function () {
    const MULTIPART_THRESHOLD = 100 * 1024 * 1024;
    const PART_SIZE = 8 * 1024 * 1024;
    const BATCH_INIT_SIZE = 1000;
    const PRESIGN_BATCH_SIZE = 50;
    const VIRTUAL_LIST_THRESHOLD = 500;
    const MAX_SMALL_CONCURRENCY = 20;
    const MAX_LARGE_CONCURRENCY = 3;
    const MAX_PART_CONCURRENCY = 6;

    function initStorageAdminForms() {
        const storageTargetForm = document.getElementById('storageTargetForm');
        const storageTargetProvider = document.getElementById('storageTargetProvider');
        const storageTargetCredential = document.getElementById('storageTargetCredential');
        const storageTargetProject = document.getElementById('storageTargetProject');
        const storageTargetEnvironment = document.getElementById('storageTargetEnvironment');
        let storageCredentials = {};
        let allProjectsTree = [];
        try {
            const storageCredentialsEl = document.getElementById('storage-credentials');
            storageCredentials = storageCredentialsEl ? JSON.parse(storageCredentialsEl.textContent || '{}') : {};
        } catch (err) {
            console.warn('Failed to parse #storage-credentials', err);
        }
        try {
            const allProjectsTreeEl = document.getElementById('all-projects-tree');
            allProjectsTree = allProjectsTreeEl ? JSON.parse(allProjectsTreeEl.textContent || '[]') : [];
        } catch (err) {
            console.warn('Failed to parse #all-projects-tree', err);
        }

        function fillStorageTargetEnvironmentOptions(projectId, selectedId) {
            if (!storageTargetEnvironment) return;
            const project = allProjectsTree.find((item) => item.id === projectId);
            const options = ['<option value="">绑定环境</option>'];
            (project?.environments || []).forEach((env) => {
                options.push(`<option value="${env.id}" ${env.id === selectedId ? 'selected' : ''}>${env.name}</option>`);
            });
            storageTargetEnvironment.innerHTML = options.join('');
        }

        function updateStorageTargetCredentialOptions(selectedId) {
            if (!storageTargetProvider || !storageTargetCredential) return;
            const creds = storageCredentials[storageTargetProvider.value] || [];
            storageTargetCredential.innerHTML = '<option value="">选择凭据</option>';
            creds.forEach((cred) => {
                storageTargetCredential.insertAdjacentHTML(
                    'beforeend',
                    `<option value="${cred.id}" ${cred.id === selectedId ? 'selected' : ''}>${cred.name} (${cred.id})</option>`,
                );
            });
        }

        storageTargetProject?.addEventListener('change', () => {
            fillStorageTargetEnvironmentOptions(storageTargetProject.value, '');
        });
        storageTargetProvider?.addEventListener('change', () => updateStorageTargetCredentialOptions(''));
        updateStorageTargetCredentialOptions('');

        document.querySelectorAll('.edit-storage-target-btn').forEach((btn) => {
            btn.addEventListener('click', () => {
                const row = btn.closest('.storage-target-row');
                if (!row || !storageTargetForm) return;
                document.getElementById('storageTargetId').value = row.dataset.targetId || '';
                storageTargetForm.name.value = row.dataset.name || '';
                storageTargetProvider.value = row.dataset.provider || '';
                updateStorageTargetCredentialOptions(row.dataset.credentialId || '');
                if (storageTargetProject) {
                    storageTargetProject.value = row.dataset.projectId || '';
                    fillStorageTargetEnvironmentOptions(row.dataset.projectId || '', row.dataset.environmentId || '');
                }
                storageTargetForm.bucket.value = row.dataset.bucket || '';
                storageTargetForm.region.value = row.dataset.region || '';
                storageTargetForm.endpoint.value = row.dataset.endpoint || '';
                const allowDelete = storageTargetForm.querySelector('input[name="allow_user_delete"]');
                if (allowDelete) allowDelete.checked = row.dataset.allowUserDelete === '1';
                storageTargetForm.scrollIntoView({ behavior: 'smooth', block: 'start' });
            });
        });

        document.querySelectorAll('.delete-storage-target-btn').forEach((btn) => {
            btn.addEventListener('click', async () => {
                if (!confirm('确认删除该存储目标？')) return;
                const response = await fetch('/delete_storage_target', {
                    method: 'POST',
                    body: new URLSearchParams({ target_id: btn.dataset.targetId }),
                });
                const data = await response.json();
                if (data.success) location.reload();
                else alert(data.error || '删除失败');
            });
        });

        const storageFilterProject = document.getElementById('storageFilterProject');
        const storageFilterEnvironment = document.getElementById('storageFilterEnvironment');
        const storageTargetsTableBody = document.getElementById('storageTargetsTableBody');
        const storageListSummary = document.getElementById('storageListSummary');

        function fillStorageFilterEnvironmentOptions(projectId) {
            if (!storageFilterEnvironment) return;
            const project = allProjectsTree.find((item) => item.id === projectId);
            const options = ['<option value="">全部</option>'];
            (project?.environments || []).forEach((env) => {
                options.push(`<option value="${env.id}">${env.name}</option>`);
            });
            storageFilterEnvironment.innerHTML = options.join('');
        }

        function applyStorageTargetsFilter() {
            if (!storageTargetsTableBody) return;
            const projectFilter = storageFilterProject?.value || '';
            const environmentFilter = storageFilterEnvironment?.value || '';
            const rows = storageTargetsTableBody.querySelectorAll('.storage-target-row');
            let visible = 0;
            rows.forEach((row) => {
                const matchProject = !projectFilter || row.dataset.projectId === projectFilter;
                const matchEnvironment = !environmentFilter || row.dataset.environmentId === environmentFilter;
                const show = matchProject && matchEnvironment;
                row.classList.toggle('hidden', !show);
                if (show) visible += 1;
            });
            if (storageListSummary) {
                storageListSummary.textContent = `共 ${rows.length} 个，显示 ${visible} 个`;
            }
        }

        storageFilterProject?.addEventListener('change', () => {
            fillStorageFilterEnvironmentOptions(storageFilterProject.value);
            applyStorageTargetsFilter();
        });
        storageFilterEnvironment?.addEventListener('change', applyStorageTargetsFilter);
        fillStorageFilterEnvironmentOptions('');
        applyStorageTargetsFilter();
    }

    initStorageAdminForms();

    const appRoot = document.getElementById('storageManagerApp');
    if (!appRoot) return;

    const state = {
        remotePrefix: '',
        remoteFolders: [],
        remoteFiles: [],
        canDelete: false,
        localItems: [],
        uploading: false,
        cancelled: false,
        fileProgress: {},
        doneBytes: 0,
        totalBytes: 0,
        currentJobId: null,
        eventSource: null,
    };

    const els = {
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
        localEmpty: document.getElementById('localEmptyHint'),
        localSummary: document.getElementById('localSummary'),
        refreshAfter: document.getElementById('uploadRefreshAfter'),
        globalWrap: document.getElementById('globalProgressWrap'),
        globalText: document.getElementById('globalProgressText'),
        globalPercent: document.getElementById('globalProgressPercent'),
        globalBar: document.getElementById('globalProgressBar'),
        jobHistory: document.getElementById('uploadJobHistory'),
        jobHistoryBody: document.getElementById('uploadJobHistoryBody'),
    };

    const userRole = appRoot.dataset.userRole || 'user';
    const canDeleteDefault = appRoot.dataset.canDeleteDefault === '1';

    function formatBytes(bytes) {
        if (!bytes) return '0 B';
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
        return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
    }

    function formatFetchError(err, phase) {
        const message = err && err.message ? err.message : String(err);
        if (message === 'Failed to fetch') {
            return `${phase}失败：浏览器无法连接对象存储，请检查 Bucket CORS（PUT/GET/HEAD + 暴露 ETag）`;
        }
        return `${phase}失败：${message}`;
    }

    async function fetchJson(url, options) {
        let response;
        try {
            response = await fetch(url, options);
        } catch (err) {
            throw new Error(formatFetchError(err, '请求'));
        }
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || data.message || `HTTP ${response.status}`);
        return data;
    }

    function xhrPut(url, body, onProgress) {
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
            xhr.onerror = () => reject(new Error(formatFetchError({ message: 'Failed to fetch' }, '存储直传')));
            xhr.send(body);
        });
    }

    function updateGlobalProgress() {
        const inFlight = Object.values(state.fileProgress).reduce((sum, n) => sum + (n || 0), 0);
        const uploaded = state.doneBytes + inFlight;
        const total = state.totalBytes || 1;
        const percent = Math.min(100, Math.round((uploaded / total) * 100));
        els.globalBar.style.width = `${percent}%`;
        els.globalPercent.textContent = `${percent}%`;
    }

    function setGlobalProgressVisible(visible) {
        els.globalWrap.classList.toggle('hidden', !visible);
    }

    function canDeleteNow() {
        if (canDeleteDefault) return true;
        const opt = els.target.selectedOptions[0];
        return opt && opt.dataset.allowUserDelete === '1';
    }

    function renderBreadcrumb() {
        const parts = state.remotePrefix.replace(/\/+$/, '').split('/').filter(Boolean);
        let html = `<button type="button" class="remote-crumb hover:underline" data-prefix="">根目录</button>`;
        let acc = '';
        parts.forEach((part) => {
            acc = acc ? `${acc}/${part}` : part;
            html += `<span class="text-gray-400 mx-1">/</span><button type="button" class="remote-crumb hover:underline" data-prefix="${acc}/">${part}</button>`;
        });
        els.remoteBreadcrumb.innerHTML = html;
        els.remoteBreadcrumb.querySelectorAll('.remote-crumb').forEach((btn) => {
            btn.addEventListener('click', () => {
                state.remotePrefix = btn.dataset.prefix || '';
                els.remotePath.value = state.remotePrefix;
                loadRemoteList();
            });
        });
    }

    function renderRemoteList() {
        const hasContent = state.remoteFolders.length || state.remoteFiles.length;
        els.remoteEmpty.classList.toggle('hidden', hasContent);
        els.remoteList.innerHTML = '';

        state.remoteFolders.forEach((folder) => {
            const tr = document.createElement('tr');
            tr.className = 'hover:bg-indigo-50';
            tr.innerHTML = `
                <td class="px-3 py-2"><input type="checkbox" class="remote-check rounded" data-type="folder" data-prefix="${folder.prefix}"></td>
                <td class="px-3 py-2"><button type="button" class="remote-folder text-indigo-700 hover:underline text-left" data-prefix="${folder.prefix}"><i class="fas fa-folder text-amber-500 mr-2"></i>${folder.name}</button></td>
                <td class="px-3 py-2 text-right text-gray-400">—</td>`;
            els.remoteList.appendChild(tr);
        });

        state.remoteFiles.forEach((file) => {
            const tr = document.createElement('tr');
            tr.className = 'hover:bg-gray-50';
            tr.innerHTML = `
                <td class="px-3 py-2"><input type="checkbox" class="remote-check rounded" data-type="file" data-key="${file.key}"></td>
                <td class="px-3 py-2 truncate max-w-[240px]" title="${file.key}"><i class="fas fa-file text-gray-400 mr-2"></i>${file.name}</td>
                <td class="px-3 py-2 text-right text-gray-500">${formatBytes(file.size)}</td>`;
            els.remoteList.appendChild(tr);
        });

        els.remoteDelete.classList.toggle('hidden', !state.canDelete);
        bindRemoteEvents();
    }

    function bindRemoteEvents() {
        els.remoteList.querySelectorAll('.remote-check').forEach((cb) => {
            cb.addEventListener('change', updateRemoteActions);
        });
    }

    function applyRemoteListing(data) {
        state.canDelete = !!data.can_delete;
        state.remoteFolders = data.folders || [];
        state.remoteFiles = data.files || [];
        if (typeof data.remote_prefix === 'string') {
            state.remotePrefix = data.remote_prefix;
            els.remotePath.value = data.remote_prefix;
        }
        renderBreadcrumb();
        renderRemoteList();
        updateRemoteActions();
    }

    async function loadRemoteList() {
        const targetId = els.target.value;
        const prefix = els.remotePath.value.trim();
        const data = await fetchJson(`/api/storage/list?target_id=${encodeURIComponent(targetId)}&prefix=${encodeURIComponent(prefix)}`);
        applyRemoteListing(data);
    }

    function updateRemoteActions() {
        const checked = els.remoteList.querySelectorAll('.remote-check:checked');
        const has = checked.length > 0;
        els.remoteDownload.disabled = !has;
        els.remoteRename.disabled = !(has && checked.length === 1);
        els.remoteDelete.disabled = !has || !state.canDelete;
    }

    function rowsToRender() {
        const items = state.localItems;
        if (items.length <= VIRTUAL_LIST_THRESHOLD) {
            return items.map((item, index) => ({ item, index }));
        }
        const active = [];
        items.forEach((item, index) => {
            if (item.status === 'uploading' || item.status === 'failed' || item.selected) {
                active.push({ item, index });
            }
        });
        return (active.length ? active : items.slice(0, 120).map((item, index) => ({ item, index })));
    }

    function renderLocalList() {
        const has = state.localItems.length > 0;
        els.localEmpty.classList.toggle('hidden', has);
        els.localList.innerHTML = '';
        let total = 0;
        state.localItems.forEach((item) => { total += item.file.size; });

        const virtual = state.localItems.length > VIRTUAL_LIST_THRESHOLD;
        rowsToRender().forEach(({ item, index }) => {
            const tr = document.createElement('tr');
            tr.className = 'hover:bg-gray-50';
            tr.dataset.index = String(index);
            const statusClass = item.status === 'done' ? 'text-green-600' : item.status === 'failed' ? 'text-red-600' : 'text-gray-600';
            tr.innerHTML = `
                <td class="px-3 py-2"><input type="checkbox" class="local-check rounded" data-index="${index}" ${item.selected ? 'checked' : ''} ${state.uploading ? 'disabled' : ''}></td>
                <td class="px-3 py-2 truncate max-w-[200px]" title="${item.path}">${item.path}</td>
                <td class="px-3 py-2 text-right text-gray-500">${formatBytes(item.file.size)}</td>
                <td class="px-3 py-2">
                    <div class="w-full bg-gray-200 rounded-full h-1.5 mb-1"><div class="local-bar bg-green-500 h-1.5 rounded-full transition-all" style="width:${item.progress || 0}%"></div></div>
                    <span class="text-xs ${statusClass} local-status">${item.statusText || '待上传'}</span>
                </td>`;
            els.localList.appendChild(tr);
        });

        const selectedCount = state.localItems.filter((i) => i.selected).length;
        let summary = has
            ? `已选 ${selectedCount}/${state.localItems.length} 个，共 ${formatBytes(total)}`
            : '未选择文件';
        if (virtual) summary += ` · 虚拟列表（${state.localItems.length} 文件，显示活跃/选中行）`;
        els.localSummary.textContent = summary;
        els.localUpload.disabled = !has || state.uploading || !state.localItems.some((i) => i.selected);

        els.localList.querySelectorAll('.local-check').forEach((cb) => {
            cb.addEventListener('change', () => {
                const idx = parseInt(cb.dataset.index, 10);
                state.localItems[idx].selected = cb.checked;
                renderLocalList();
            });
        });
    }

    async function sendHeartbeat(fileId, bytesUploaded) {
        await fetchJson(`/api/upload/files/${fileId}/progress`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bytes_uploaded: bytesUploaded, status: 'uploading' }),
        }).catch(() => {});
    }

    function subscribeJobStream(jobId) {
        if (state.eventSource) state.eventSource.close();
        const es = new EventSource(`/api/upload/jobs/${jobId}/stream`);
        es.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                const pct = data.total_bytes
                    ? Math.min(100, Math.round((data.done_bytes / data.total_bytes) * 100))
                    : 0;
                els.globalText.textContent = `Job ${data.done_files}/${data.total_files} 完成 · 失败 ${data.failed_files || 0}`;
                els.globalPercent.textContent = `${pct}%`;
                els.globalBar.style.width = `${pct}%`;
            } catch (_) { /* ignore */ }
        };
        state.eventSource = es;
    }

    async function createJobInBatches(manifest) {
        let jobId = null;
        let allFiles = [];
        for (let offset = 0; offset < manifest.length; offset += BATCH_INIT_SIZE) {
            const batch = manifest.slice(offset, offset + BATCH_INIT_SIZE);
            if (offset === 0) {
                const data = await fetchJson('/api/upload/jobs', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        storage_target_id: els.target.value,
                        remote_prefix: els.remotePath.value.trim(),
                        refresh_after: els.refreshAfter.checked,
                        files: batch,
                    }),
                });
                jobId = data.job_id;
                allFiles = data.files || [];
            } else {
                const data = await fetchJson(`/api/upload/jobs/${jobId}/init-batch`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ files: batch }),
                });
                allFiles = allFiles.concat(data.files || []);
            }
        }
        return { jobId, files: allFiles };
    }

    async function loadJobHistory() {
        if (!els.jobHistoryBody) return;
        const data = await fetchJson('/api/upload/jobs?limit=15');
        els.jobHistoryBody.innerHTML = '';
        (data.jobs || []).forEach((job) => {
            const tr = document.createElement('tr');
            tr.className = 'hover:bg-gray-50';
            tr.innerHTML = `
                <td class="px-3 py-2 font-mono text-xs">${job.id}</td>
                <td class="px-3 py-2">${job.status}</td>
                <td class="px-3 py-2">${job.done_files}/${job.total_files}</td>
                <td class="px-3 py-2 text-xs text-gray-500">${job.created_at || '-'}</td>
                <td class="px-3 py-2">
                    ${job.failed_files ? `<a class="text-red-600 hover:underline text-xs" href="/api/upload/jobs/${job.id}/manifest-failures.csv">失败 CSV</a>` : '-'}
                    <button type="button" class="ml-2 text-gray-500 hover:text-red-600 text-xs job-cleanup-btn" data-job-id="${job.id}">清理</button>
                </td>`;
            els.jobHistoryBody.appendChild(tr);
        });
        els.jobHistoryBody.querySelectorAll('.job-cleanup-btn').forEach((btn) => {
            btn.addEventListener('click', async () => {
                if (!confirm('确认清理该 Job 记录？')) return;
                await fetchJson(`/api/upload/jobs/${btn.dataset.jobId}/cleanup`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ force: true }),
                });
                loadJobHistory();
            });
        });
    }

    function addLocalFiles(fileList) {
        Array.from(fileList || []).forEach((file) => {
            const path = file.webkitRelativePath || file.name;
            if (state.localItems.some((item) => item.path === path)) return;
            state.localItems.push({
                file,
                path,
                selected: true,
                status: 'pending',
                statusText: '待上传',
                progress: 0,
            });
        });
        renderLocalList();
    }

    function updateLocalItem(index, patch) {
        Object.assign(state.localItems[index], patch);
        const row = els.localList.children[index];
        if (!row) return renderLocalList();
        const bar = row.querySelector('.local-bar');
        const status = row.querySelector('.local-status');
        if (bar && patch.progress !== undefined) bar.style.width = `${patch.progress}%`;
        if (status && patch.statusText) {
            status.textContent = patch.statusText;
            status.className = `text-xs local-status ${patch.status === 'failed' ? 'text-red-600' : patch.status === 'done' ? 'text-green-600' : 'text-gray-600'}`;
        }
    }

    async function uploadPut(file, fileMeta, startData, onProgress) {
        const xhr = await xhrPut(startData.upload_url, file, (loaded, total) => {
            onProgress(loaded, total);
            if (loaded % (512 * 1024) < 65536) sendHeartbeat(fileMeta.id, loaded);
        });
        let etag = xhr.getResponseHeader('ETag') || xhr.getResponseHeader('etag') || '';
        etag = etag.replace(/"/g, '');
        if (!etag) throw new Error('未读取到 ETag，请在 CORS 中暴露 ETag');
        await fetchJson(`/api/upload/files/${fileMeta.id}/complete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ etag }),
        });
    }

    async function uploadSmallPresignBatch(entries) {
        for (let i = 0; i < entries.length; i += PRESIGN_BATCH_SIZE) {
            if (state.cancelled) return;
            const chunk = entries.slice(i, i + PRESIGN_BATCH_SIZE);
            const presign = await fetchJson('/api/upload/files/presign-batch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ file_ids: chunk.map((e) => e.meta.id) }),
            });
            const urlMap = new Map((presign.files || []).map((f) => [f.file_id, f.upload_url]));
            await runPool(chunk, MAX_SMALL_CONCURRENCY, async (entry) => {
                if (state.cancelled) return;
                try {
                    const url = urlMap.get(entry.meta.id);
                    if (!url) throw new Error('presign 缺失');
                    await uploadPut(entry.item.file, entry.meta, { upload_url: url }, (loaded, total) => {
                        state.fileProgress[entry.meta.id] = loaded;
                        const percent = total ? Math.min(100, Math.round((loaded / total) * 100)) : 0;
                        updateLocalItem(entry.index, { progress: percent, statusText: `${percent}%`, status: 'uploading' });
                        updateGlobalProgress();
                    });
                    delete state.fileProgress[entry.meta.id];
                    state.doneBytes += entry.item.file.size;
                    updateLocalItem(entry.index, { status: 'done', statusText: '完成', progress: 100 });
                    if (window.UploadIdb) {
                        await UploadIdb.saveFileState(state.currentJobId, entry.meta.id, entry.item.path, { status: 'done' });
                    }
                } catch (err) {
                    updateLocalItem(entry.index, { status: 'failed', statusText: err.message.slice(0, 80), progress: 0 });
                }
            });
        }
    }

    async function uploadMultipart(file, fileMeta, startData, fileKey, onProgress) {
        const totalParts = startData.total_parts;
        const partSize = startData.part_size || PART_SIZE;
        const pendingParts = new Map(startData.parts.map((p) => [p.part_number, p.url]));
        let partDoneBytes = 0;

        async function ensurePartUrl(partNumber) {
            if (pendingParts.has(partNumber)) return pendingParts.get(partNumber);
            const endPart = Math.min(partNumber + 19, totalParts);
            const data = await fetchJson(`/api/upload/files/${fileMeta.id}/presign-parts`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ start_part: partNumber, end_part: endPart }),
            });
            data.parts.forEach((p) => pendingParts.set(p.part_number, p.url));
            return pendingParts.get(partNumber);
        }

        async function runPart(partNumber) {
            const start = (partNumber - 1) * partSize;
            const end = Math.min(start + partSize, file.size);
            const blob = file.slice(start, end);
            const url = await ensurePartUrl(partNumber);
            const xhr = await xhrPut(url, blob, (loaded) => {
                state.fileProgress[fileKey] = partDoneBytes + loaded;
                onProgress(state.fileProgress[fileKey], file.size);
                updateGlobalProgress();
            });
            let etag = xhr.getResponseHeader('ETag') || xhr.getResponseHeader('etag') || '';
            etag = etag.replace(/"/g, '');
            if (!etag) throw new Error('分片未返回 ETag');
            await fetchJson(`/api/upload/files/${fileMeta.id}/part-done`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ part_number: partNumber, etag }),
            });
            partDoneBytes += blob.size;
            state.fileProgress[fileKey] = partDoneBytes;
            onProgress(partDoneBytes, file.size);
            updateGlobalProgress();
        }

        const partNumbers = Array.from({ length: totalParts }, (_, i) => i + 1);
        await runPool(partNumbers, MAX_PART_CONCURRENCY, runPart);
        await fetchJson(`/api/upload/files/${fileMeta.id}/complete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
        });
    }

    async function runPool(items, concurrency, worker) {
        const queue = [...items];
        await Promise.all(Array.from({ length: Math.min(concurrency, queue.length) }, async () => {
            while (queue.length) {
                if (state.cancelled) return;
                await worker(queue.shift());
            }
        }));
    }

    async function uploadSingleLocal(item, index, fileMeta) {
        const fileKey = fileMeta.id;
        state.fileProgress[fileKey] = 0;
        updateLocalItem(index, { status: 'uploading', statusText: '上传中...', progress: 0 });

        const onProgress = (loaded, total) => {
            const percent = total ? Math.min(100, Math.round((loaded / total) * 100)) : 0;
            updateLocalItem(index, { progress: percent, statusText: `${percent}%` });
        };

        const startData = await fetchJson(`/api/upload/files/${fileMeta.id}/start`, { method: 'POST' });
        if (startData.mode === 'multipart') {
            await uploadMultipart(item.file, fileMeta, startData, fileKey, onProgress);
        } else {
            await uploadPut(item.file, fileMeta, startData, (loaded, total) => {
                state.fileProgress[fileKey] = loaded;
                onProgress(loaded, total);
                updateGlobalProgress();
            });
        }
        delete state.fileProgress[fileKey];
        state.doneBytes += item.file.size;
        updateLocalItem(index, { status: 'done', statusText: '完成', progress: 100 });
        updateGlobalProgress();
    }

    async function startUpload() {
        const selected = state.localItems.map((item, index) => ({ item, index })).filter(({ item }) => item.selected);
        if (!selected.length || state.uploading) return;

        state.uploading = true;
        state.cancelled = false;
        state.doneBytes = 0;
        state.fileProgress = {};
        state.totalBytes = selected.reduce((sum, { item }) => sum + item.file.size, 0);
        setGlobalProgressVisible(true);
        els.localUpload.disabled = true;
        els.localCancel.classList.remove('hidden');
        els.globalText.textContent = `正在创建 Job（${selected.length} 文件）...`;
        updateGlobalProgress();

        const manifest = selected.map(({ item }) => ({
            relative_path: item.path,
            size: item.file.size,
            mime: item.file.type || 'application/octet-stream',
        }));

        let jobId = null;
        try {
            const jobData = await createJobInBatches(manifest);
            jobId = jobData.jobId;
            state.currentJobId = jobId;
            subscribeJobStream(jobId);

            if (window.UploadIdb) {
                await UploadIdb.saveSession({
                    jobId,
                    active: true,
                    storageTargetId: els.target.value,
                    remotePrefix: els.remotePath.value.trim(),
                    refreshAfter: els.refreshAfter.checked,
                    createdAt: new Date().toISOString(),
                    totalFiles: selected.length,
                });
            }

            const large = [];
            const small = [];
            selected.forEach(({ item, index }, i) => {
                const meta = jobData.files[i];
                const entry = { item, index, meta };
                if (item.file.size > MULTIPART_THRESHOLD) large.push(entry);
                else small.push(entry);
            });

            els.globalText.textContent = `正在上传 0/${selected.length} 个文件...`;

            let doneCount = 0;
            async function handleLargeEntry(entry) {
                if (state.cancelled) return;
                try {
                    await uploadSingleLocal(entry.item, entry.index, entry.meta);
                    if (window.UploadIdb) {
                        await UploadIdb.saveFileState(jobId, entry.meta.id, entry.item.path, { status: 'done' });
                    }
                } catch (err) {
                    updateLocalItem(entry.index, { status: 'failed', statusText: err.message.slice(0, 80), progress: 0 });
                }
                doneCount += 1;
                els.globalText.textContent = `正在上传 ${doneCount}/${selected.length} 个文件...`;
            }

            await runPool(large, MAX_LARGE_CONCURRENCY, handleLargeEntry);
            await uploadSmallPresignBatch(small);
            doneCount = selected.length;

            const failed = state.localItems.filter((i) => i.status === 'failed').length;
            els.globalText.textContent = failed
                ? `上传结束：${selected.length - failed} 成功，${failed} 失败`
                : `全部上传完成（${selected.length} 个文件）`;

            if (jobId && els.refreshAfter.checked) {
                await fetchJson(`/api/upload/jobs/${jobId}/refresh-cdn`, { method: 'POST' }).catch(() => {});
            }
            if (window.UploadIdb && jobId) {
                await UploadIdb.saveSession({ jobId, active: false });
            }
            if (state.eventSource) state.eventSource.close();
            await loadRemoteList();
            await loadJobHistory();
        } catch (err) {
            els.globalText.textContent = `上传失败: ${err.message}`;
        } finally {
            state.uploading = false;
            state.cancelled = false;
            els.localCancel.classList.add('hidden');
            renderLocalList();
        }
    }

    async function tryResumeSession() {
        if (!window.UploadIdb) return;
        const session = await UploadIdb.getActiveSession();
        if (!session || !session.active) return;
        const ok = confirm(`检测到未完成的上传 Job (${session.jobId})，是否加载待传文件列表？需重新选择相同文件夹以匹配文件。`);
        if (!ok) {
            await UploadIdb.saveSession({ jobId: session.jobId, active: false });
            return;
        }
        state.currentJobId = session.jobId;
        els.target.value = session.storageTargetId || els.target.value;
        els.remotePath.value = session.remotePrefix || '';
        subscribeJobStream(session.jobId);
        const data = await fetchJson(`/api/upload/jobs/${session.jobId}/files?status=pending&limit=1000`);
        els.globalText.textContent = `待恢复：${data.total} 个 pending 文件（请重新选择文件夹后上传）`;
        setGlobalProgressVisible(true);
    }

    async function downloadSelectedRemote() {
        const keys = [];
        els.remoteList.querySelectorAll('.remote-check:checked').forEach((cb) => {
            if (cb.dataset.type === 'file') keys.push(cb.dataset.key);
        });
        if (!keys.length) return;
        const data = await fetchJson('/api/storage/download-urls', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_id: els.target.value, keys }),
        });
        data.urls.forEach(({ url }) => {
            window.open(url, '_blank');
        });
    }

    async function deleteSelectedRemote() {
        const keys = [];
        const prefixes = [];
        els.remoteList.querySelectorAll('.remote-check:checked').forEach((cb) => {
            if (cb.dataset.type === 'file') keys.push(cb.dataset.key);
            if (cb.dataset.type === 'folder') prefixes.push(cb.dataset.prefix);
        });
        if (!keys.length && !prefixes.length) return;
        if (!confirm(`确认删除 ${keys.length} 个文件${prefixes.length ? ` 和 ${prefixes.length} 个文件夹` : ''}？`)) return;
        await fetchJson('/api/storage/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_id: els.target.value, keys, prefixes }),
        });
        await loadRemoteList();
    }

    async function mkdirSelectedRemote() {
        const folderName = window.prompt('请输入新文件夹名称：');
        if (!folderName || !folderName.trim()) return;
        const name = folderName.trim();
        await fetchJson('/api/storage/mkdir', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_id: els.target.value, directory_name: `${els.remotePath.value || ''}${name}` }),
        });
        await loadRemoteList();
    }

    async function renameSelectedRemote() {
        const checked = [...els.remoteList.querySelectorAll('.remote-check:checked')];
        const item = checked.length === 1 ? checked[0] : null;
        if (!item) return;
        const currentName = item.dataset.type === 'file' ? item.dataset.key : item.dataset.prefix;
        const nextName = window.prompt('请输入新名称：', currentName.split('/').filter(Boolean).pop() || '');
        if (!nextName || !nextName.trim()) return;
        const oldKey = item.dataset.type === 'file' ? item.dataset.key : item.dataset.prefix;
        await fetchJson('/api/storage/rename', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_id: els.target.value, old_key: oldKey, new_name: `${(els.remotePath.value || '').replace(/\/+$/, '')}/${nextName.trim()}` }),
        });
        await loadRemoteList();
    }

    els.remoteBrowse?.addEventListener('click', () => loadRemoteList());
    els.target?.addEventListener('change', () => loadRemoteList());
    els.remoteUp?.addEventListener('click', () => {
        const parts = els.remotePath.value.replace(/\/+$/, '').split('/').filter(Boolean);
        parts.pop();
        els.remotePath.value = parts.length ? `${parts.join('/')}/` : '';
        loadRemoteList();
    });
    els.remoteMkdir?.addEventListener('click', () => mkdirSelectedRemote().catch((e) => alert(e.message)));
    els.remoteRename?.addEventListener('click', () => renameSelectedRemote().catch((e) => alert(e.message)));
    els.remoteDownload?.addEventListener('click', () => downloadSelectedRemote().catch((e) => alert(e.message)));
    els.remoteDelete?.addEventListener('click', () => deleteSelectedRemote().catch((e) => alert(e.message)));
    els.remoteSelectAll?.addEventListener('change', () => {
        els.remoteList.querySelectorAll('.remote-check').forEach((cb) => { cb.checked = els.remoteSelectAll.checked; });
        updateRemoteActions();
    });

    els.localFolder?.addEventListener('change', (e) => addLocalFiles(e.target.files));
    els.localFile?.addEventListener('change', (e) => addLocalFiles(e.target.files));
    els.localClear?.addEventListener('click', () => {
        if (state.uploading) return;
        state.localItems = [];
        renderLocalList();
    });
    els.localUpload?.addEventListener('click', () => startUpload());
    els.localCancel?.addEventListener('click', () => { state.cancelled = true; });
    els.localSelectAll?.addEventListener('change', () => {
        state.localItems.forEach((item) => { item.selected = els.localSelectAll.checked; });
        renderLocalList();
    });

    // Fix folder navigation - use relative path from remotePath
    els.remoteList.addEventListener('click', (e) => {
        const btn = e.target.closest('.remote-folder');
        if (!btn) return;
        e.preventDefault();
        const folder = state.remoteFolders.find((f) => f.prefix === btn.dataset.prefix);
        if (!folder) return;
        // folder.prefix is full storage key prefix; compute relative path after base by using listing remote_prefix
        const current = (els.remotePath.value || '').replace(/\/+$/, '');
        els.remotePath.value = current ? `${current}/${folder.name}/` : `${folder.name}/`;
        loadRemoteList();
    });

    document.getElementById('uploadJobHistoryReload')?.addEventListener('click', () => loadJobHistory());

    loadRemoteList().catch(() => {});
    loadJobHistory().catch(() => {});
    tryResumeSession().catch(() => {});
})();
