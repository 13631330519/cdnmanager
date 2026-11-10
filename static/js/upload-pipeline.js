/* Local folder tree and presign / FTP-proxy upload pipeline. */
(function (app) {
    if (!app.state) return;

    app.basenameOf = function (path) {
        const parts = String(path || '').replace(/\\/g, '/').split('/').filter(Boolean);
        return parts[parts.length - 1] || path || '';
    }

    app.createFolderNode = function (name, path) {
        return {
            id: `${path}/`,
            kind: 'folder',
            name,
            path,
            selected: true,
            // 默认折叠：避免上万节点一次性挂到 DOM。
            expanded: false,
            children: [],
            sorted: false,
        };
    }

    app.createFileNode = function (file, path) {
        return {
            id: path,
            kind: 'file',
            name: app.basenameOf(path),
            path,
            file,
            selected: true,
            status: 'pending',
            statusText: '待上传',
            progress: 0,
        };
    }

    app.sortTreeChildren = function (children) {
        children.sort((a, b) => {
            if (a.kind !== b.kind) return a.kind === 'folder' ? -1 : 1;
            return app.sortNameAsc(a, b);
        });
        return children;
    }

    app.ensureChildrenSorted = function (folderNode) {
        if (!folderNode || folderNode.sorted) return;
        app.sortTreeChildren(folderNode.children || []);
        folderNode.sorted = true;
    }

    app.sortTreeRecursive = function (nodes) {
        app.sortTreeChildren(nodes);
        nodes.forEach((node) => {
            if (node.kind === 'folder') {
                node.sorted = true;
                app.sortTreeRecursive(node.children || []);
            }
        });
    }

    app.ensureFolderPath = function (rootChildren, folderPath) {
        const parts = String(folderPath || '').replace(/\\/g, '/').split('/').filter(Boolean);
        let children = rootChildren;
        let parent = null;
        let acc = '';
        parts.forEach((part) => {
            acc = acc ? `${acc}/${part}` : part;
            let folder = app.state.folderByPath.get(acc);
            if (!folder) {
                folder = app.createFolderNode(part, acc);
                children.push(folder);
                app.state.folderByPath.set(acc, folder);
                if (parent) parent.sorted = false;
            }
            parent = folder;
            children = folder.children;
        });
        return children;
    }

    app.addFileToTree = function (rootChildren, file, path) {
        const normalized = String(path || file.name || '').replace(/\\/g, '/').replace(/^\/+/, '');
        if (!normalized) return null;
        if (app.state.fileByPath.has(normalized)) return null;
        const parts = normalized.split('/');
        parts.pop();
        const parentChildren = parts.length ? app.ensureFolderPath(rootChildren, parts.join('/')) : rootChildren;
        const parentPath = parts.join('/');
        const parentFolder = parentPath ? app.state.folderByPath.get(parentPath) : null;
        const node = app.createFileNode(file, normalized);
        parentChildren.push(node);
        if (parentFolder) parentFolder.sorted = false;
        app.state.fileByPath.set(normalized, node);
        app.state.localFiles.push(node);
        app.state.localItems = app.state.localFiles;
        return node;
    }

    app.walkTree = function (nodes, visitor, depth = 0) {
        nodes.forEach((node) => {
            visitor(node, depth);
            if (node.kind === 'folder' && node.children && node.children.length) {
                app.walkTree(node.children, visitor, depth + 1);
            }
        });
    }

    app.flattenVisibleTree = function (nodes, depth = 0, out = []) {
        nodes.forEach((node) => {
            out.push({ node, depth });
            if (node.kind === 'folder' && node.expanded) {
                app.ensureChildrenSorted(node);
                app.flattenVisibleTree(node.children || [], depth + 1, out);
            }
        });
        return out;
    }

    app.setNodeSelected = function (node, selected) {
        node.selected = selected;
        if (node.kind === 'folder') {
            (node.children || []).forEach((child) => app.setNodeSelected(child, selected));
        }
    }

    app.syncFolderSelection = function (node) {
        if (node.kind !== 'folder') return;
        (node.children || []).forEach(app.syncFolderSelection);
        const children = node.children || [];
        if (!children.length) return;
        node.selected = children.every((child) => child.selected);
    }

    app.syncAllFolderSelections = function () {
        app.state.localTree.forEach(app.syncFolderSelection);
    }

    app.collectSelectedFiles = function () {
        return app.state.localFiles.filter((item) => item.selected);
    }

    app.collectSelectedDirectories = function () {
        const dirs = new Set();
        app.walkTree(app.state.localTree, (node) => {
            if (node.kind !== 'folder' || !node.selected) return;
            dirs.add(node.path);
        });
        app.collectSelectedFiles().forEach((fileNode) => {
            const parts = fileNode.path.split('/');
            parts.pop();
            let acc = '';
            parts.forEach((part) => {
                acc = acc ? `${acc}/${part}` : part;
                dirs.add(acc);
            });
        });
        return [...dirs].sort((a, b) => a.count('/') - b.count('/') || a.localeCompare(b));
    }

    app.findFileNodeByPath = function (path) {
        return app.state.fileByPath.get(path) || null;
    }

    app.findTreeNode = function (_nodes, path, kind) {
        if (kind === 'folder' || !kind) {
            const folder = app.state.folderByPath.get(path);
            if (folder) return folder;
        }
        if (kind === 'file' || !kind) {
            return app.state.fileByPath.get(path) || null;
        }
        return null;
    }

    app.updateLocalSummary = function () {
        const has = app.state.localTree.length > 0;
        let total = 0;
        app.state.localFiles.forEach((item) => { total += item.file.size || 0; });
        const selectedCount = app.collectSelectedFiles().length;
        const folderCount = app.state.folderByPath.size;
        app.els.localSummary.textContent = has
            ? `已选 ${selectedCount}/${app.state.localFiles.length} 个文件 · ${folderCount} 个目录 · ${app.formatBytes(total)}`
            : '未选择文件';
        app.els.localUpload.disabled = !has || app.state.uploading || selectedCount === 0 || app.state.localBuilding;
    }

    app.buildLocalRow = function (node, depth) {
        const tr = document.createElement('tr');
        tr.className = node.kind === 'folder' ? 'hover:bg-indigo-50' : 'hover:bg-gray-50';
        tr.dataset.path = node.path;
        tr.dataset.kind = node.kind;
        tr.style.height = `${app.LOCAL_ROW_HEIGHT}px`;
        const pad = 8 + depth * 16;
        if (node.kind === 'folder') {
            const icon = node.expanded ? 'fa-caret-down' : 'fa-caret-right';
            tr.innerHTML = `
                <td class="px-3 py-2"><input type="checkbox" class="local-check rounded" data-path="${app.escapeHtml(node.path)}" data-kind="folder" ${node.selected ? 'checked' : ''} ${app.state.uploading ? 'disabled' : ''}></td>
                <td class="px-3 py-2">
                    <button type="button" class="local-fold text-left w-full" data-path="${app.escapeHtml(node.path)}" style="padding-left:${pad}px">
                        <i class="fas ${icon} text-gray-400 mr-1 w-3 inline-block"></i>
                        <i class="fas fa-folder text-amber-500 mr-2"></i>${app.escapeHtml(node.name)}
                    </button>
                </td>
                <td class="px-3 py-2 text-right text-gray-400">—</td>
                <td class="px-3 py-2 text-xs text-gray-400">${(node.children || []).length} 项</td>`;
        } else {
            const statusClass = node.status === 'done' ? 'text-green-600' : node.status === 'failed' ? 'text-red-600' : 'text-gray-600';
            tr.innerHTML = `
                <td class="px-3 py-2"><input type="checkbox" class="local-check rounded" data-path="${app.escapeHtml(node.path)}" data-kind="file" ${node.selected ? 'checked' : ''} ${app.state.uploading ? 'disabled' : ''}></td>
                <td class="px-3 py-2 truncate max-w-[240px]" title="${app.escapeHtml(node.path)}">
                    <span style="padding-left:${pad}px"><i class="fas fa-file text-gray-400 mr-2"></i>${app.escapeHtml(node.name)}</span>
                </td>
                <td class="px-3 py-2 text-right text-gray-500">${app.formatBytes(node.file.size)}</td>
                <td class="px-3 py-2">
                    <div class="w-full bg-gray-200 rounded-full h-1.5 mb-1"><div class="local-bar bg-green-500 h-1.5 rounded-full transition-all" style="width:${node.progress || 0}%"></div></div>
                    <span class="text-xs ${statusClass} local-status">${node.statusText || '待上传'}</span>
                </td>`;
        }
        return tr;
    }

    app.renderLocalList = function () {
        const has = app.state.localTree.length > 0;
        app.els.localEmpty.classList.toggle('hidden', has);
        app.sortTreeChildren(app.state.localTree);

        const visible = app.flattenVisibleTree(app.state.localTree);
        app.state.localVisibleCache = visible;
        app.updateLocalSummary();
        if (!has) {
            app.els.localList.innerHTML = '';
            return;
        }

        const wrap = app.els.localListWrap;
        const viewH = wrap ? wrap.clientHeight || 520 : 520;
        const headerEl = wrap ? wrap.querySelector('thead') : null;
        const headerH = headerEl ? headerEl.offsetHeight : 0;
        // 滚动容器含 sticky 表头，内容总高度 = 表头 + 行高总和。
        const maxScroll = Math.max(0, headerH + visible.length * app.LOCAL_ROW_HEIGHT - viewH);
        if (wrap && wrap.scrollTop > maxScroll) {
            wrap.scrollTop = maxScroll;
        }
        const scrollTop = wrap ? wrap.scrollTop : 0;
        const bodyScroll = Math.max(0, scrollTop - headerH);
        let start = Math.max(0, Math.floor(bodyScroll / app.LOCAL_ROW_HEIGHT) - app.LOCAL_VIRTUAL_OVERSCAN);
        let end = Math.min(
            visible.length,
            Math.ceil((bodyScroll + Math.max(viewH - headerH, app.LOCAL_ROW_HEIGHT)) / app.LOCAL_ROW_HEIGHT) + app.LOCAL_VIRTUAL_OVERSCAN,
        );
        if (start > end) start = Math.max(0, end - 1);
        if (visible.length && start >= visible.length) {
            start = Math.max(0, visible.length - 1);
            end = visible.length;
        }

        const parts = [];
        if (start > 0) {
            parts.push(`<tr aria-hidden="true"><td colspan="4" style="height:${start * app.LOCAL_ROW_HEIGHT}px;padding:0;border:0;line-height:0"></td></tr>`);
        }
        const frag = document.createDocumentFragment();
        const top = document.createElement('tbody');
        top.innerHTML = parts.join('');
        while (top.firstChild) frag.appendChild(top.firstChild);

        for (let i = start; i < end; i += 1) {
            const { node, depth } = visible[i];
            frag.appendChild(app.buildLocalRow(node, depth));
        }

        if (end < visible.length) {
            const bottom = document.createElement('tr');
            bottom.setAttribute('aria-hidden', 'true');
            bottom.innerHTML = `<td colspan="4" style="height:${(visible.length - end) * app.LOCAL_ROW_HEIGHT}px;padding:0;border:0;line-height:0"></td>`;
            frag.appendChild(bottom);
        }

        app.els.localList.innerHTML = '';
        app.els.localList.appendChild(frag);
        app.ensureLocalListBindings();
    }

    app.ensureLocalListBindings = function () {
        if (app.state.localListBound) return;
        app.state.localListBound = true;
        app.els.localList.addEventListener('change', (event) => {
            const cb = event.target.closest('.local-check');
            if (!cb) return;
            const path = cb.dataset.path;
            if (cb.dataset.kind === 'folder') {
                const folder = app.findTreeNode(app.state.localTree, path, 'folder');
                if (folder) app.setNodeSelected(folder, cb.checked);
            } else {
                const fileNode = app.findFileNodeByPath(path);
                if (fileNode) fileNode.selected = cb.checked;
            }
            app.syncAllFolderSelections();
            app.renderLocalList();
        });
        app.els.localList.addEventListener('click', (event) => {
            const btn = event.target.closest('.local-fold');
            if (!btn) return;
            event.preventDefault();
            const folder = app.findTreeNode(app.state.localTree, btn.dataset.path, 'folder');
            if (!folder) return;
            folder.expanded = !folder.expanded;
            if (folder.expanded) app.ensureChildrenSorted(folder);
            app.renderLocalList();
        });
        app.els.localListWrap?.addEventListener('scroll', () => {
            if (app.state.localBuilding) return;
            window.requestAnimationFrame(() => app.renderLocalList());
        }, { passive: true });
    }

    app.yieldToMain = function () {
        return new Promise((resolve) => setTimeout(resolve, 0));
    }

    app.sendHeartbeat = async function (fileId, bytesUploaded) {
        await app.fetchJson(`/api/upload/files/${fileId}/progress`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ bytes_uploaded: bytesUploaded, status: 'uploading' }),
        }).catch(() => {});
    }

    app.subscribeJobStream = function (jobId) {
        if (app.state.eventSource) app.state.eventSource.close();
        const es = new EventSource(`/api/upload/jobs/${jobId}/stream`);
        es.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                const pct = data.total_bytes
                    ? Math.min(100, Math.round((data.done_bytes / data.total_bytes) * 100))
                    : 0;
                app.els.globalText.textContent = `Job ${data.done_files}/${data.total_files} 完成 · 失败 ${data.failed_files || 0}`;
                app.els.globalPercent.textContent = `${pct}%`;
                app.els.globalBar.style.width = `${pct}%`;
            } catch (_) { /* ignore */ }
        };
        app.state.eventSource = es;
    }

    app.createJobInBatches = async function (manifest) {
        let jobId = null;
        let allFiles = [];
        for (let offset = 0; offset < manifest.length; offset += app.BATCH_INIT_SIZE) {
            const batch = manifest.slice(offset, offset + app.BATCH_INIT_SIZE);
            if (offset === 0) {
                const data = await app.fetchJson('/api/upload/jobs', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        storage_target_id: app.els.target.value,
                        remote_prefix: app.els.remotePath.value.trim(),
                        files: batch,
                    }),
                });
                jobId = data.job_id;
                allFiles = data.files || [];
            } else {
                const data = await app.fetchJson(`/api/upload/jobs/${jobId}/init-batch`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ files: batch }),
                });
                allFiles = allFiles.concat(data.files || []);
            }
        }
        return { jobId, files: allFiles };
    }

    app.loadJobHistory = async function () {
        if (!app.els.jobHistoryBody) return;
        const data = await app.fetchJson('/api/upload/jobs?limit=15');
        app.els.jobHistoryBody.innerHTML = '';
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
            app.els.jobHistoryBody.appendChild(tr);
        });
        app.els.jobHistoryBody.querySelectorAll('.job-cleanup-btn').forEach((btn) => {
            btn.addEventListener('click', async () => {
                if (!confirm('确认清理该 Job 记录？')) return;
                await app.fetchJson(`/api/upload/jobs/${btn.dataset.jobId}/cleanup`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ force: true }),
                });
                app.loadJobHistory();
            });
        });
    }

    app.addLocalFiles = function (fileList) {
        Array.from(fileList || []).forEach((file) => {
            app.addFileToTree(app.state.localTree, file, file.webkitRelativePath || file.name);
        });
        app.syncAllFolderSelections();
        app.sortTreeRecursive(app.state.localTree);
        app.renderLocalList();
    }

    app.clearLocalSelection = function () {
        app.state.localTree = [];
        app.state.localFiles = [];
        app.state.localItems = [];
        app.state.folderByPath.clear();
        app.state.fileByPath.clear();
        app.state.localVisibleCache = [];
        if (app.els.localListWrap) app.els.localListWrap.scrollTop = 0;
        app.renderLocalList();
    }

    app.updateLocalItem = function (indexOrPath, patch) {
        let node = null;
        if (typeof indexOrPath === 'number') {
            node = app.state.localFiles[indexOrPath];
        } else if (indexOrPath && typeof indexOrPath === 'object') {
            node = indexOrPath;
        } else {
            node = app.findFileNodeByPath(indexOrPath);
        }
        if (!node) return;
        Object.assign(node, patch);
        const row = [...els.localList.querySelectorAll('tr[data-path]')].find((tr) => tr.dataset.path === node.path);
        if (!row) return;
        const bar = row.querySelector('.local-bar');
        const status = row.querySelector('.local-status');
        if (bar && patch.progress !== undefined) bar.style.width = `${patch.progress}%`;
        if (status && patch.statusText) {
            status.textContent = patch.statusText;
            status.className = `text-xs local-status ${patch.status === 'failed' ? 'text-red-600' : patch.status === 'done' ? 'text-green-600' : 'text-gray-600'}`;
        }
    }

    app.xhrProxyUpload = function (targetId, prefix, file, filename, onProgress) {
        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open('POST', '/api/storage/upload');
            const form = new FormData();
            const remoteName = filename || file.name || 'upload.bin';
            form.append('target_id', targetId);
            form.append('prefix', prefix || '');
            form.append('relative_path', remoteName);
            form.append('file', file, remoteName);
            if (onProgress) {
                xhr.upload.onprogress = (event) => {
                    if (event.lengthComputable) onProgress(event.loaded, event.total);
                };
            }
            xhr.onload = () => {
                let data = {};
                try {
                    data = JSON.parse(xhr.responseText || '{}');
                } catch (_) {
                    data = {};
                }
                if (xhr.status >= 200 && xhr.status < 300 && data.success) {
                    resolve(data);
                } else {
                    reject(new Error(data.error || data.message || `代理上传失败 HTTP ${xhr.status}`));
                }
            };
            xhr.onerror = () => reject(new Error('代理上传失败：浏览器无法连接服务器'));
            xhr.send(form);
        });
    }

    app.uploadProxyFile = async function (entry, targetId, prefix) {
        const { item, index, meta } = entry;
        if (!meta) throw new Error('任务文件缺失');
        const fileKey = meta.id;
        app.state.fileProgress[fileKey] = 0;
        app.updateLocalItem(index, { status: 'uploading', statusText: '代理上传中...', progress: 0 });
        app.sendHeartbeat(fileKey, 0);
        try {
            const data = await app.xhrProxyUpload(
                targetId,
                prefix,
                item.file,
                item.path,
                (loaded, total) => {
                    app.state.fileProgress[fileKey] = loaded;
                    const percent = total ? Math.min(100, Math.round((loaded / total) * 100)) : 0;
                    app.updateLocalItem(index, { progress: percent, statusText: `${percent}%`, status: 'uploading' });
                    app.updateGlobalProgress();
                    if (loaded % (512 * 1024) < 65536) app.sendHeartbeat(fileKey, loaded);
                },
            );
            if (!data || !data.success) throw new Error((data && data.error) || '代理上传失败');
            let statusText = '完成';
            try {
                await app.fetchJson(`/api/upload/files/${fileKey}/complete`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ proxy: true }),
                });
            } catch (err) {
                // The object is already stored. A missing ETag must not show a failed row.
                statusText = '完成（任务记录未更新）';
                console.warn('proxy upload complete skipped', err);
            }
            app.state.doneBytes += item.file.size;
            app.updateLocalItem(index, { status: 'done', statusText, progress: 100 });
            if (window.UploadIdb) {
                await UploadIdb.saveFileState(app.state.currentJobId, fileKey, item.path, { status: 'done' });
            }
        } finally {
            delete app.state.fileProgress[fileKey];
            app.updateGlobalProgress();
        }
    }

    app.uploadPut = async function (file, fileMeta, startData, onProgress) {
        const xhr = await app.xhrPut(startData.upload_url, file, (loaded, total) => {
            onProgress(loaded, total);
            if (loaded % (512 * 1024) < 65536) app.sendHeartbeat(fileMeta.id, loaded);
        });
        let etag = xhr.getResponseHeader('ETag') || xhr.getResponseHeader('etag') || '';
        etag = etag.replace(/"/g, '');
        if (!etag) throw new Error('未读取到 ETag，请在 CORS 中暴露 ETag');
        await app.fetchJson(`/api/upload/files/${fileMeta.id}/complete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ etag }),
        });
    }

    app.uploadSmallPresignBatch = async function (entries) {
        for (let i = 0; i < entries.length; i += app.PRESIGN_BATCH_SIZE) {
            if (app.state.cancelled) return;
            const chunk = entries.slice(i, i + app.PRESIGN_BATCH_SIZE);
            const presign = await app.fetchJson('/api/upload/files/presign-batch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ file_ids: chunk.map((e) => e.meta.id) }),
            });
            const urlMap = new Map((presign.files || []).map((f) => [f.file_id, f.upload_url]));
            await app.runPool(chunk, app.MAX_SMALL_CONCURRENCY, async (entry) => {
                if (app.state.cancelled) return;
                try {
                    const url = urlMap.get(entry.meta.id);
                    if (!url) throw new Error('presign 缺失');
                    await app.uploadPut(entry.item.file, entry.meta, { upload_url: url }, (loaded, total) => {
                        app.state.fileProgress[entry.meta.id] = loaded;
                        const percent = total ? Math.min(100, Math.round((loaded / total) * 100)) : 0;
                        app.updateLocalItem(entry.index, { progress: percent, statusText: `${percent}%`, status: 'uploading' });
                        app.updateGlobalProgress();
                    });
                    delete app.state.fileProgress[entry.meta.id];
                    app.state.doneBytes += entry.item.file.size;
                    app.updateLocalItem(entry.index, { status: 'done', statusText: '完成', progress: 100 });
                    if (window.UploadIdb) {
                        await UploadIdb.saveFileState(app.state.currentJobId, entry.meta.id, entry.item.path, { status: 'done' });
                    }
                } catch (err) {
                    app.updateLocalItem(entry.index, { status: 'failed', statusText: err.message.slice(0, 80), progress: 0 });
                }
            });
        }
    }

    app.uploadMultipart = async function (file, fileMeta, startData, fileKey, onProgress) {
        const totalParts = startData.total_parts;
        const partSize = startData.part_size || app.PART_SIZE;
        const pendingParts = new Map(startData.parts.map((p) => [p.part_number, p.url]));
        let partDoneBytes = 0;

        async function ensurePartUrl(partNumber) {
            if (pendingParts.has(partNumber)) return pendingParts.get(partNumber);
            const endPart = Math.min(partNumber + 19, totalParts);
            const data = await app.fetchJson(`/api/upload/files/${fileMeta.id}/presign-parts`, {
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
            const xhr = await app.xhrPut(url, blob, (loaded) => {
                app.state.fileProgress[fileKey] = partDoneBytes + loaded;
                onProgress(app.state.fileProgress[fileKey], file.size);
                app.updateGlobalProgress();
            });
            let etag = xhr.getResponseHeader('ETag') || xhr.getResponseHeader('etag') || '';
            etag = etag.replace(/"/g, '');
            if (!etag) throw new Error('分片未返回 ETag');
            await app.fetchJson(`/api/upload/files/${fileMeta.id}/part-done`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ part_number: partNumber, etag }),
            });
            partDoneBytes += blob.size;
            app.state.fileProgress[fileKey] = partDoneBytes;
            onProgress(partDoneBytes, file.size);
            app.updateGlobalProgress();
        }

        const partNumbers = Array.from({ length: totalParts }, (_, i) => i + 1);
        await app.runPool(partNumbers, app.MAX_PART_CONCURRENCY, runPart);
        await app.fetchJson(`/api/upload/files/${fileMeta.id}/complete`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
        });
    }

    app.runPool = async function (items, concurrency, worker) {
        const queue = [...items];
        await Promise.all(Array.from({ length: Math.min(concurrency, queue.length) }, async () => {
            while (queue.length) {
                if (app.state.cancelled) return;
                await worker(queue.shift());
            }
        }));
    }

    app.uploadSingleLocal = async function (item, index, fileMeta) {
        const fileKey = fileMeta.id;
        app.state.fileProgress[fileKey] = 0;
        app.updateLocalItem(index, { status: 'uploading', statusText: '上传中...', progress: 0 });

        const onProgress = (loaded, total) => {
            const percent = total ? Math.min(100, Math.round((loaded / total) * 100)) : 0;
            app.updateLocalItem(index, { progress: percent, statusText: `${percent}%` });
        };

        const startData = await app.fetchJson(`/api/upload/files/${fileMeta.id}/start`, { method: 'POST' });
        if (startData.mode === 'multipart') {
            await app.uploadMultipart(item.file, fileMeta, startData, fileKey, onProgress);
        } else {
            await app.uploadPut(item.file, fileMeta, startData, (loaded, total) => {
                app.state.fileProgress[fileKey] = loaded;
                onProgress(loaded, total);
                app.updateGlobalProgress();
            });
        }
        delete app.state.fileProgress[fileKey];
        app.state.doneBytes += item.file.size;
        app.updateLocalItem(index, { status: 'done', statusText: '完成', progress: 100 });
        app.updateGlobalProgress();
    }

    app.createLimiter = function (concurrency) {
        let active = 0;
        const queue = [];
        function pump() {
            while (active < concurrency && queue.length) {
                const job = queue.shift();
                active += 1;
                Promise.resolve()
                    .then(job.fn)
                    .then(job.resolve, job.reject)
                    .finally(() => {
                        active -= 1;
                        pump();
                    });
            }
        }
        return function limit(fn) {
            return new Promise((resolve, reject) => {
                queue.push({ fn, resolve, reject });
                pump();
            });
        };
    }

    app.walkFileList = async function (files, acceptFile, acceptFolder) {
        for (const file of files) {
            if (app.state.cancelled) return;
            const path = file.webkitRelativePath || file.name;
            const parts = String(path).replace(/\\/g, '/').split('/').filter(Boolean);
            if (acceptFolder && parts.length > 1) {
                await acceptFolder(parts.slice(0, -1).join('/'));
            }
            await acceptFile(file, path);
        }
    }

    app.walkDirectoryHandle = async function (dirHandle, prefix, acceptFile, acceptFolder) {
        if (app.state.cancelled) return;
        if (prefix && acceptFolder) await acceptFolder(prefix);
        const files = [];
        const subdirs = [];
        for await (const [name, handle] of dirHandle.entries()) {
            if (app.state.cancelled) return;
            const path = prefix ? `${prefix}/${name}` : name;
            if (handle.kind === 'directory') subdirs.push({ handle, path });
            else files.push({ handle, path });
        }
        await Promise.all([
            app.runPool(files, 8, async (entry) => {
                if (app.state.cancelled) return;
                const file = await entry.handle.getFile();
                await acceptFile(file, entry.path);
            }),
            app.runPool(subdirs, app.DIR_WALK_CONCURRENCY, async (entry) => {
                await app.walkDirectoryHandle(entry.handle, entry.path, acceptFile, acceptFolder);
            }),
        ]);
    }

    app.loadLocalFolderTree = async function (walk) {
        if (app.state.uploading || app.state.localBuilding) return;
        app.clearLocalSelection();
        app.state.localBuilding = true;
        app.els.localUpload.disabled = true;
        app.els.globalText.textContent = '正在遍历子目录（默认折叠，构建中不刷列表）...';
        app.setGlobalProgressVisible(true);
        let discovered = 0;
        let sinceYield = 0;
        let summaryTimer = null;
        const scheduleSummary = () => {
            if (summaryTimer) return;
            summaryTimer = setTimeout(() => {
                summaryTimer = null;
                app.updateLocalSummary();
                app.els.globalText.textContent = `正在构建索引：${discovered} 个文件 · ${app.state.folderByPath.size} 个目录`;
            }, 200);
        };
        try {
            await walk(
                async (file, path) => {
                    app.addFileToTree(app.state.localTree, file, path);
                    discovered += 1;
                    sinceYield += 1;
                    scheduleSummary();
                    if (sinceYield >= app.LOCAL_BUILD_YIELD_EVERY) {
                        sinceYield = 0;
                        await app.yieldToMain();
                    }
                },
                async (folderPath) => {
                    app.ensureFolderPath(app.state.localTree, folderPath);
                    scheduleSummary();
                },
            );
            app.syncAllFolderSelections();
            app.sortTreeRecursive(app.state.localTree);
            app.renderLocalList();
            app.els.globalText.textContent = discovered
                ? `已索引 ${discovered} 个文件（目录默认折叠，展开后再加载该层）。勾选后点击「上传选中」`
                : '文件夹里没有文件';
        } catch (err) {
            app.els.globalText.textContent = `读取文件夹失败: ${err.message || err}`;
        } finally {
            if (summaryTimer) clearTimeout(summaryTimer);
            app.state.localBuilding = false;
            app.updateLocalSummary();
        }
    }

    app.ensureRemoteDirectories = async function (relativeDirs) {
        if (!relativeDirs.length) return;
        const remoteBase = (app.els.remotePath.value || '').replace(/\/+$/, '');
        const directories = relativeDirs.map((dir) => (
            remoteBase ? `${remoteBase}/${dir}` : dir
        ));
        const chunkSize = 100;
        for (let i = 0; i < directories.length; i += chunkSize) {
            if (app.state.cancelled) return;
            const chunk = directories.slice(i, i + chunkSize);
            await app.fetchJson('/api/storage/mkdir', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    target_id: app.els.target.value,
                    directories: chunk,
                }),
            });
        }
    }

    app.startUpload = async function () {
        const selected = app.collectSelectedFiles().map((item) => ({
            item,
            index: app.state.localFiles.indexOf(item),
        }));
        if (!selected.length || app.state.uploading) return;
        if (!app.els.target.value) {
            alert('请先选择存储目标');
            return;
        }

        app.state.uploading = true;
        app.state.cancelled = false;
        app.state.doneBytes = 0;
        app.state.fileProgress = {};
        app.state.totalBytes = selected.reduce((sum, { item }) => sum + (item.file.size || 0), 0);
        app.setGlobalProgressVisible(true);
        app.els.localUpload.disabled = true;
        app.els.localCancel.classList.remove('hidden');
        app.els.globalText.textContent = `正在创建云端目录并分批上传（${selected.length} 文件）...`;
        app.updateGlobalProgress();
        app.renderLocalList();

        const uploadTargetId = app.els.target.value;
        const uploadPrefix = app.els.remotePath.value.trim();
        const proxyUpload = app.isProxyUploadTarget();
        const largeLimit = app.createLimiter(app.MAX_LARGE_CONCURRENCY);
        let jobId = null;
        let initChain = Promise.resolve();
        let smallChain = Promise.resolve();
        const uploads = [];
        const smallPending = [];
        let closed = false;

        async function registerBatch(entries) {
            const manifest = entries.map(({ item }) => ({
                relative_path: item.path,
                size: item.file.size,
                mime: item.file.type || 'application/octet-stream',
            }));
            if (!jobId) {
                const data = await app.fetchJson('/api/upload/jobs', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        storage_target_id: uploadTargetId,
                        remote_prefix: uploadPrefix,
                        keep_open: true,
                        files: manifest,
                    }),
                });
                jobId = data.job_id;
                app.state.currentJobId = jobId;
                app.state.openManifestJobId = jobId;
                app.subscribeJobStream(jobId);
                if (window.UploadIdb) {
                    await UploadIdb.saveSession({
                        jobId,
                        active: true,
                        storageTargetId: uploadTargetId,
                        remotePrefix: uploadPrefix,
                        createdAt: new Date().toISOString(),
                        totalFiles: selected.length,
                    });
                }
                return data.files || [];
            }
            const data = await app.fetchJson(`/api/upload/jobs/${jobId}/init-batch`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ files: manifest }),
            });
            return data.files || [];
        }

        function enqueueSmall(chunk) {
            const run = smallChain.then(() => app.uploadSmallPresignBatch(chunk));
            smallChain = run.catch(() => {});
            uploads.push(run);
        }

        function scheduleUploads(entries, metas) {
            if (proxyUpload) {
                entries.forEach((entry, i) => {
                    uploads.push(largeLimit(async () => {
                        try {
                            await app.uploadProxyFile(
                                { item: entry.item, index: entry.index, meta: metas[i] },
                                uploadTargetId,
                                uploadPrefix,
                            );
                        } catch (err) {
                            app.updateLocalItem(entry.index, {
                                status: 'failed',
                                statusText: (err.message || '代理上传失败').slice(0, 80),
                                progress: 0,
                            });
                        }
                    }));
                });
                return;
            }
            const small = [];
            entries.forEach((entry, i) => {
                const packed = { item: entry.item, index: entry.index, meta: metas[i] };
                if (entry.item.file.size > app.MULTIPART_THRESHOLD) {
                    uploads.push(largeLimit(async () => {
                        try {
                            await app.uploadSingleLocal(entry.item, entry.index, metas[i]);
                            if (window.UploadIdb) {
                                await UploadIdb.saveFileState(jobId, metas[i].id, entry.item.path, { status: 'done' });
                            }
                        } catch (err) {
                            app.updateLocalItem(entry.index, {
                                status: 'failed',
                                statusText: (err.message || '上传失败').slice(0, 80),
                                progress: 0,
                            });
                        }
                    }));
                } else {
                    small.push(packed);
                }
            });
            smallPending.push(...small);
            while (smallPending.length >= app.PRESIGN_BATCH_SIZE) {
                enqueueSmall(smallPending.splice(0, app.PRESIGN_BATCH_SIZE));
            }
        }

        async function flush(entries) {
            if (!entries.length || app.state.cancelled) return;
            const run = initChain.then(async () => {
                if (app.state.cancelled) return;
                const metas = await registerBatch(entries);
                const readyEntries = [];
                const readyMetas = [];
                entries.forEach((entry, i) => {
                    if (!metas[i]) {
                        app.updateLocalItem(entry.index, { status: 'failed', statusText: '登记失败', progress: 0 });
                        return;
                    }
                    readyEntries.push(entry);
                    readyMetas.push(metas[i]);
                });
                scheduleUploads(readyEntries, readyMetas);
                const done = selected.filter(({ item }) => item.status === 'done' || item.status === 'failed' || item.status === 'uploading').length;
                app.els.globalText.textContent = `正在分批上传 ${Math.min(done + readyEntries.length, selected.length)}/${selected.length} ...`;
            });
            initChain = run.catch((err) => {
                entries.forEach((entry) => {
                    app.updateLocalItem(entry.index, {
                        status: 'failed',
                        statusText: (err.message || '登记失败').slice(0, 80),
                        progress: 0,
                    });
                });
            });
            await run;
        }

        async function closeManifest() {
            if (!jobId || closed) return;
            closed = true;
            app.state.openManifestJobId = null;
            try {
                await app.fetchJson(`/api/upload/jobs/${jobId}/close-manifest`, { method: 'POST' });
            } catch (err) {
                // 断网时改用 keepalive，尽量让服务端收口。
                app.closeManifestKeepalive(jobId);
                throw err;
            }
            if (window.UploadIdb) await UploadIdb.saveSession({ jobId, active: false });
        }

        try {
            const dirs = app.collectSelectedDirectories();
            if (dirs.length) {
                app.els.globalText.textContent = `正在创建云端目录（${dirs.length}）...`;
                await app.ensureRemoteDirectories(dirs);
            }

            for (let offset = 0; offset < selected.length; offset += app.FOLDER_FLUSH_SIZE) {
                if (app.state.cancelled) break;
                const chunk = selected.slice(offset, offset + app.FOLDER_FLUSH_SIZE);
                await flush(chunk);
            }
            await initChain;
            if (smallPending.length) enqueueSmall(smallPending.splice(0, smallPending.length));
            await Promise.all(uploads);

            const failed = selected.filter(({ item }) => item.status === 'failed').length;
            const succeeded = selected.filter(({ item }) => item.status === 'done').length;
            if (app.state.cancelled) {
                app.els.globalText.textContent = `已取消：完成 ${succeeded}，失败 ${failed}`;
            } else if (!succeeded) {
                app.els.globalText.textContent = `上传结束：0 成功，${failed} 失败`;
            } else if (failed) {
                app.els.globalText.textContent = `上传结束：${succeeded} 成功，${failed} 失败。已提交成功文件的 CDN 刷新`;
            } else {
                app.els.globalText.textContent = `全部上传完成（${succeeded} 个文件），已提交 CDN 刷新`;
            }
            if (app.state.eventSource) app.state.eventSource.close();
            await app.loadRemoteList();
            await app.loadJobHistory();
        } catch (err) {
            app.els.globalText.textContent = `上传失败: ${err.message}`;
        } finally {
            try {
                await closeManifest();
            } catch (_) {
                /* closeManifestKeepalive already tried */
            }
            app.state.uploading = false;
            app.state.cancelled = false;
            app.els.localCancel.classList.add('hidden');
            app.renderLocalList();
        }
    }

    app.closeManifestKeepalive = function (jobId) {
        if (!jobId) return;
        const url = `/api/upload/jobs/${jobId}/close-manifest`;
        const body = '{}';
        try {
            if (navigator.sendBeacon) {
                const blob = new Blob([body], { type: 'application/json' });
                if (navigator.sendBeacon(url, blob)) return;
            }
        } catch (_) { /* fall through */ }
        fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body,
            keepalive: true,
            credentials: 'same-origin',
        }).catch(() => {});
    }

    app.bindManifestUnloadGuard = function () {
        const flushOpenManifest = () => {
            const jobId = app.state.openManifestJobId;
            if (!jobId) return;
            app.state.openManifestJobId = null;
            app.closeManifestKeepalive(jobId);
            if (window.UploadIdb) {
                try { UploadIdb.saveSession({ jobId, active: false }); } catch (_) { /* ignore */ }
            }
        };
        window.addEventListener('pagehide', flushOpenManifest);
        window.addEventListener('beforeunload', flushOpenManifest);
    }

    app.tryResumeSession = async function () {
        if (!window.UploadIdb) return;
        const session = await UploadIdb.getActiveSession();
        if (!session || !session.active) return;
        const ok = confirm(`检测到未完成的上传 Job (${session.jobId})，是否加载待传文件列表？需重新选择相同文件夹以匹配文件。`);
        if (!ok) {
            await UploadIdb.saveSession({ jobId: session.jobId, active: false });
            return;
        }
        app.state.currentJobId = session.jobId;
        app.els.target.value = session.storageTargetId || app.els.target.value;
        app.els.remotePath.value = session.remotePrefix || '';
        app.subscribeJobStream(session.jobId);
        const data = await app.fetchJson(`/api/upload/jobs/${session.jobId}/files?status=pending&limit=1000`);
        app.els.globalText.textContent = `待恢复：${data.total} 个 pending 文件（请重新选择文件夹后上传）`;
        app.setGlobalProgressVisible(true);
    }

    app.els.remoteBrowse?.addEventListener('click', () => app.loadRemoteList());
    app.els.target?.addEventListener('change', () => {
        app.state.remotePrefix = '';
        app.els.remotePath.value = '';
        app.updateTransportHint();
        app.loadRemoteList();
    });
    app.els.remoteUp?.addEventListener('click', () => {
        const parts = app.els.remotePath.value.replace(/\/+$/, '').split('/').filter(Boolean);
        parts.pop();
        app.els.remotePath.value = parts.length ? `${parts.join('/')}/` : '';
        app.loadRemoteList();
    });
    app.els.remoteMkdir?.addEventListener('click', () => app.mkdirSelectedRemote().catch((e) => alert(e.message)));
    app.els.remoteRename?.addEventListener('click', () => app.renameSelectedRemote().catch((e) => alert(e.message)));
    app.els.remoteDownload?.addEventListener('click', () => app.downloadSelectedRemote().catch((e) => alert(e.message)));
    app.els.remoteDelete?.addEventListener('click', () => app.deleteSelectedRemote().catch((e) => alert(e.message)));
    app.els.remoteSelectAll?.addEventListener('change', () => {
        app.els.remoteList.querySelectorAll('.remote-check').forEach((cb) => { cb.checked = app.els.remoteSelectAll.checked; });
        app.updateRemoteActions();
    });

    app.els.localFolder?.closest('label')?.addEventListener('click', async (event) => {
        if (typeof window.showDirectoryPicker !== 'function') return;
        event.preventDefault();
        if (app.state.uploading) return;
        try {
            const handle = await window.showDirectoryPicker({ mode: 'read' });
            await app.loadLocalFolderTree((acceptFile, acceptFolder) => (
                app.walkDirectoryHandle(handle, handle.name, acceptFile, acceptFolder)
            ));
        } catch (err) {
            if (err && err.name === 'AbortError') return;
            app.els.globalText.textContent = `读取文件夹失败: ${err.message || err}`;
            app.setGlobalProgressVisible(true);
        }
    });
    app.els.localFolder?.addEventListener('change', (e) => {
        const files = Array.from(e.target.files || []);
        e.target.value = '';
        if (!files.length || app.state.uploading) return;
        app.loadLocalFolderTree((acceptFile, acceptFolder) => app.walkFileList(files, acceptFile, acceptFolder));
    });
    app.els.localFile?.addEventListener('change', (e) => app.addLocalFiles(e.target.files));
    app.els.localClear?.addEventListener('click', () => {
        if (app.state.uploading) return;
        app.clearLocalSelection();
    });
    app.els.localUpload?.addEventListener('click', () => app.startUpload());
    app.els.localCancel?.addEventListener('click', () => { app.state.cancelled = true; });
    app.els.localSelectAll?.addEventListener('change', () => {
        const checked = !!app.els.localSelectAll.checked;
        app.state.localTree.forEach((node) => app.setNodeSelected(node, checked));
        app.renderLocalList();
    });

    // Fix folder navigation - use relative path from remotePath
    app.els.remoteList.addEventListener('click', (e) => {
        const btn = e.target.closest('.remote-folder');
        if (!btn) return;
        e.preventDefault();
        const folder = app.state.remoteFolders.find((f) => f.prefix === btn.dataset.prefix);
        if (!folder) return;
        // folder.prefix is full storage key prefix; compute relative path after base by using listing remote_prefix
        const current = (app.els.remotePath.value || '').replace(/\/+$/, '');
        app.els.remotePath.value = current ? `${current}/${folder.name}/` : `${folder.name}/`;
        app.loadRemoteList();
    });

    document.getElementById('uploadJobHistoryReload')?.addEventListener('click', () => app.loadJobHistory());

    app.bindManifestUnloadGuard();
    app.updateTransportHint();
    app.loadRemoteList().catch(() => {});
    app.loadJobHistory().catch(() => {});
    app.tryResumeSession().catch(() => {});
})(window.CdnUpload);
