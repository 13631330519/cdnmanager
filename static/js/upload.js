(function () {
    const MULTIPART_THRESHOLD = 100 * 1024 * 1024;
    const PART_SIZE = 8 * 1024 * 1024;
    const MAX_SMALL_CONCURRENCY = 20;
    const MAX_LARGE_CONCURRENCY = 3;
    const MAX_PART_CONCURRENCY = 6;

    let selectedFiles = [];
    let activeJobId = null;
    let cancelled = false;

    const folderInput = document.getElementById('uploadFolderInput');
    const fileInput = document.getElementById('uploadFileInput');
    const startBtn = document.getElementById('uploadStartBtn');
    const cancelBtn = document.getElementById('uploadCancelBtn');
    const summaryEl = document.getElementById('uploadSelectionSummary');
    const progressWrap = document.getElementById('uploadProgressWrap');
    const progressText = document.getElementById('uploadProgressText');
    const progressPercent = document.getElementById('uploadProgressPercent');
    const progressBar = document.getElementById('uploadProgressBar');
    const failedList = document.getElementById('uploadFailedList');

    if (!startBtn) return;

    function formatBytes(bytes) {
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
        if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
        return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
    }

    function setSelectedFiles(fileList) {
        selectedFiles = Array.from(fileList || []);
        const totalBytes = selectedFiles.reduce((sum, file) => sum + file.size, 0);
        summaryEl.textContent = selectedFiles.length
            ? `已选择 ${selectedFiles.length} 个文件，共 ${formatBytes(totalBytes)}`
            : '';
        startBtn.disabled = selectedFiles.length === 0 || !!activeJobId;
    }

    folderInput?.addEventListener('change', (e) => setSelectedFiles(e.target.files));
    fileInput?.addEventListener('change', (e) => setSelectedFiles(e.target.files));

    cancelBtn?.addEventListener('click', () => {
        cancelled = true;
        cancelBtn.classList.add('hidden');
    });

    async function fetchJson(url, options) {
        const response = await fetch(url, options);
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.error || data.message || `请求失败: ${response.status}`);
        }
        return data;
    }

    function updateJobProgress(doneBytes, totalBytes, doneFiles, totalFiles, failedCount) {
        const percent = totalBytes ? Math.min(100, Math.round((doneBytes / totalBytes) * 100)) : 0;
        progressBar.style.width = `${percent}%`;
        progressPercent.textContent = `${percent}%`;
        progressText.textContent = `已完成 ${doneFiles}/${totalFiles} 个文件，${formatBytes(doneBytes)}/${formatBytes(totalBytes)}${failedCount ? `，失败 ${failedCount}` : ''}`;
    }

    async function uploadPut(file, fileMeta, startData) {
        const headers = startData.headers || {};
        const response = await fetch(startData.upload_url, {
            method: startData.method || 'PUT',
            headers,
            body: file,
        });
        if (!response.ok) {
            throw new Error(`直传失败: HTTP ${response.status}`);
        }
        let etag = response.headers.get('ETag') || response.headers.get('etag') || '';
        etag = etag.replace(/"/g, '');
        await fetchJson(`/api/upload/files/${fileMeta.id}/progress`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bytes_uploaded: file.size, status: 'uploading' }),
        });
        return fetchJson(`/api/upload/files/${fileMeta.id}/complete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ etag }),
        });
    }

    async function uploadPart(url, blob) {
        const response = await fetch(url, { method: 'PUT', body: blob });
        if (!response.ok) {
            throw new Error(`分片上传失败: HTTP ${response.status}`);
        }
        let etag = response.headers.get('ETag') || response.headers.get('etag') || '';
        return etag.replace(/"/g, '');
    }

    async function uploadMultipart(file, fileMeta, startData) {
        const totalParts = startData.total_parts;
        const partSize = startData.part_size || PART_SIZE;
        const pendingParts = new Map(startData.parts.map((part) => [part.part_number, part.url]));
        let nextPresign = startData.parts.length + 1;

        async function ensurePartUrl(partNumber) {
            if (pendingParts.has(partNumber)) return pendingParts.get(partNumber);
            const endPart = Math.min(partNumber + 19, totalParts);
            const data = await fetchJson(`/api/upload/files/${fileMeta.id}/presign-parts`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ start_part: partNumber, end_part: endPart }),
            });
            data.parts.forEach((part) => pendingParts.set(part.part_number, part.url));
            nextPresign = endPart + 1;
            return pendingParts.get(partNumber);
        }

        let completedBytes = 0;
        const partNumbers = Array.from({ length: totalParts }, (_, idx) => idx + 1);

        async function runPart(partNumber) {
            const start = (partNumber - 1) * partSize;
            const end = Math.min(start + partSize, file.size);
            const blob = file.slice(start, end);
            const url = await ensurePartUrl(partNumber);
            const etag = await uploadPart(url, blob);
            await fetchJson(`/api/upload/files/${fileMeta.id}/part-done`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ part_number: partNumber, etag }),
            });
            completedBytes += blob.size;
            await fetchJson(`/api/upload/files/${fileMeta.id}/progress`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ bytes_uploaded: completedBytes, status: 'uploading' }),
            });
        }

        await runPool(partNumbers, MAX_PART_CONCURRENCY, runPart);
        return fetchJson(`/api/upload/files/${fileMeta.id}/complete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
        });
    }

    async function runPool(items, concurrency, worker) {
        const queue = [...items];
        const runners = Array.from({ length: Math.min(concurrency, queue.length) }, async () => {
            while (queue.length) {
                if (cancelled) return;
                const item = queue.shift();
                await worker(item);
            }
        });
        await Promise.all(runners);
    }

    async function uploadSingleFile(file, fileMeta) {
        const startData = await fetchJson(`/api/upload/files/${fileMeta.id}/start`, { method: 'POST' });
        if (startData.mode === 'multipart') {
            return uploadMultipart(file, fileMeta, startData);
        }
        return uploadPut(file, fileMeta, startData);
    }

    async function processFileBatch(files, metas, progressState) {
        const pairs = files.map((file, index) => ({ file, meta: metas[index] }));
        const large = pairs.filter((item) => item.file.size > MULTIPART_THRESHOLD);
        const small = pairs.filter((item) => item.file.size <= MULTIPART_THRESHOLD);

        async function handleItem(item) {
            if (cancelled) return;
            try {
                await uploadSingleFile(item.file, item.meta);
                progressState.doneFiles += 1;
                progressState.doneBytes += item.file.size;
            } catch (err) {
                progressState.failedCount += 1;
                const line = document.createElement('div');
                line.textContent = `${item.meta.relative_path}: ${err.message}`;
                failedList.appendChild(line);
            }
            updateJobProgress(
                progressState.doneBytes,
                progressState.totalBytes,
                progressState.doneFiles,
                progressState.totalFiles,
                progressState.failedCount,
            );
        }

        await runPool(large, MAX_LARGE_CONCURRENCY, handleItem);
        await runPool(small, MAX_SMALL_CONCURRENCY, handleItem);
    }

    startBtn.addEventListener('click', async () => {
        if (!selectedFiles.length) return;
        const targetId = document.getElementById('uploadTargetSelect')?.value;
        const remotePrefix = document.getElementById('uploadRemotePrefix')?.value || '';
        const refreshAfter = document.getElementById('uploadRefreshAfter')?.checked;

        cancelled = false;
        activeJobId = true;
        startBtn.disabled = true;
        cancelBtn?.classList.remove('hidden');
        progressWrap.classList.remove('hidden');
        failedList.innerHTML = '';

        const manifest = selectedFiles.map((file) => ({
            relative_path: file.webkitRelativePath || file.name,
            size: file.size,
            mime: file.type || 'application/octet-stream',
        }));

        try {
            const jobData = await fetchJson('/api/upload/jobs', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    storage_target_id: targetId,
                    remote_prefix: remotePrefix,
                    refresh_after: refreshAfter,
                    files: manifest,
                }),
            });

            activeJobId = jobData.job_id;
            const metaByPath = new Map(jobData.files.map((item) => [item.relative_path, item]));
            const orderedMetas = manifest.map((item) => metaByPath.get(item.relative_path));

            const progressState = {
                totalFiles: selectedFiles.length,
                totalBytes: selectedFiles.reduce((sum, file) => sum + file.size, 0),
                doneFiles: 0,
                doneBytes: 0,
                failedCount: 0,
            };
            updateJobProgress(0, progressState.totalBytes, 0, progressState.totalFiles, 0);

            await processFileBatch(selectedFiles, orderedMetas, progressState);

            const job = await fetchJson(`/api/upload/jobs/${jobData.job_id}`);
            progressText.textContent = `Job 完成：${job.job.status}（成功 ${job.job.done_files}，失败 ${job.job.failed_files}）`;
        } catch (err) {
            progressText.textContent = `上传失败: ${err.message}`;
        } finally {
            activeJobId = null;
            startBtn.disabled = selectedFiles.length === 0;
            cancelBtn?.classList.add('hidden');
        }
    });

    document.querySelectorAll('.save-storage-credential-form').forEach((form) => {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const resultDiv = form.querySelector('.storage-credential-result');
            resultDiv.classList.add('hidden');
            const response = await fetch('/save_storage_credential', {
                method: 'POST',
                body: new URLSearchParams(new FormData(form)),
            });
            const data = await response.json();
            resultDiv.textContent = data.success ? data.message : data.error;
            resultDiv.classList.remove('hidden');
            resultDiv.classList.toggle('text-green-600', !!data.success);
            resultDiv.classList.toggle('text-red-600', !data.success);
            if (data.success) setTimeout(() => location.reload(), 1200);
        });
    });

    document.querySelectorAll('.delete-storage-credential-btn').forEach((btn) => {
        btn.addEventListener('click', async () => {
            if (!confirm('确认删除该存储凭据？')) return;
            const response = await fetch('/delete_storage_credential', {
                method: 'POST',
                body: new URLSearchParams({
                    provider: btn.dataset.provider,
                    credential_id: btn.dataset.credentialId,
                }),
            });
            const data = await response.json();
            if (data.success) location.reload();
            else alert(data.error || '删除失败');
        });
    });

    const storageTargetForm = document.getElementById('storageTargetForm');
    const storageTargetProvider = document.getElementById('storageTargetProvider');
    const storageTargetCredential = document.getElementById('storageTargetCredential');
    const storageCredentialsEl = document.getElementById('storage-credentials');
    const storageCredentials = storageCredentialsEl
        ? JSON.parse(storageCredentialsEl.textContent)
        : {};

    function updateStorageTargetCredentialOptions() {
        if (!storageTargetProvider || !storageTargetCredential) return;
        const provider = storageTargetProvider.value;
        const creds = storageCredentials[provider] || [];
        storageTargetCredential.innerHTML = '<option value="">选择凭据</option>';
        creds.forEach((cred) => {
            storageTargetCredential.insertAdjacentHTML(
                'beforeend',
                `<option value="${cred.id}">${cred.name} (${cred.id})</option>`,
            );
        });
    }

    storageTargetProvider?.addEventListener('change', updateStorageTargetCredentialOptions);
    updateStorageTargetCredentialOptions();

    storageTargetForm?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const resultDiv = document.getElementById('storageTargetResult');
        resultDiv.classList.add('hidden');
        const response = await fetch('/save_storage_target', {
            method: 'POST',
            body: new URLSearchParams(new FormData(storageTargetForm)),
        });
        const data = await response.json();
        resultDiv.textContent = data.success ? data.message : data.error;
        resultDiv.classList.remove('hidden');
        resultDiv.classList.toggle('text-green-600', !!data.success);
        resultDiv.classList.toggle('text-red-600', !data.success);
        if (data.success) setTimeout(() => location.reload(), 1200);
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
})();
