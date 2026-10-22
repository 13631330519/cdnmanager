(function () {
    const MULTIPART_THRESHOLD = 100 * 1024 * 1024;
    const PART_SIZE = 8 * 1024 * 1024;
    const BATCH_INIT_SIZE = 1000;
    const PRESIGN_BATCH_SIZE = 50;
    const MAX_SMALL_CONCURRENCY = 20;
    const MAX_LARGE_CONCURRENCY = 3;
    const MAX_PART_CONCURRENCY = 6;
    const FOLDER_FLUSH_SIZE = 200;
    const DIR_WALK_CONCURRENCY = 6;
    const PROXY_PROVIDERS = new Set(['ftp', 'sftp', 'ftps']);
    const OSS_TARGET_PLACEHOLDERS = {
        bucket: 'Bucket 名称',
        region: 'Region（如 oss-cn-hangzhou / ap-guangzhou）',
        endpoint: '自定义 Endpoint（可选）',
    };
    const FTP_TARGET_PLACEHOLDERS = {
        bucket: 'Host（如 ftp.example.com）',
        region: '端口（数字，FTP/FTPS 通常 21，SFTP 通常 22）',
        endpoint: '根路径（如 /www/cdn，可选）',
    };

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

        function updateStorageTargetFieldHints() {
            if (!storageTargetForm) return;
            const ftp = PROXY_PROVIDERS.has(storageTargetProvider?.value || '');
            const hints = ftp ? FTP_TARGET_PLACEHOLDERS : OSS_TARGET_PLACEHOLDERS;
            const bucket = storageTargetForm.querySelector('input[name="bucket"]');
            const region = storageTargetForm.querySelector('input[name="region"]');
            const endpoint = storageTargetForm.querySelector('input[name="endpoint"]');
            if (bucket) {
                bucket.placeholder = hints.bucket;
                bucket.title = ftp ? '远程主机名或 IP' : 'Bucket 名称';
            }
            if (region) {
                region.placeholder = hints.region;
                region.title = ftp ? '端口，1-65535' : 'Region';
                region.inputMode = ftp ? 'numeric' : 'text';
            }
            if (endpoint) {
                endpoint.placeholder = hints.endpoint;
                endpoint.title = ftp ? '远程根路径，可选' : '自定义 Endpoint，可选';
            }
            const hint = document.getElementById('storageTargetFieldHint');
            if (hint) {
                hint.textContent = ftp
                    ? 'FTP / SFTP / FTPS：三个输入框依次为 Host、端口、根路径。显式 FTPS（AUTH TLS）默认端口为 21。'
                    : '对象存储：填写 Bucket、Region，Endpoint 可选。';
            }
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

        const storageTargetModal = document.getElementById('storageTargetModal');
        const modalTitle = document.getElementById('storageTargetModalTitle');
        const openStorageTargetModalBtn = document.getElementById('openStorageTargetModalBtn');

        function resetStorageTargetForm(mode = 'create') {
            if (!storageTargetForm) return;
            storageTargetForm.reset();
            storageTargetForm.target_id.value = '';
            if (storageTargetProject) storageTargetProject.value = '';
            fillStorageTargetEnvironmentOptions('', '');
            updateStorageTargetCredentialOptions('');
            updateStorageTargetFieldHints();
            modalTitle.textContent = mode === 'edit' ? '编辑存储目标' : '新建存储目标';
        }

        function openStorageTargetModal(mode = 'create', row = null) {
            if (!storageTargetModal || !storageTargetForm) return;
            resetStorageTargetForm(mode);
            if (row) {
                storageTargetForm.target_id.value = row.dataset.targetId || '';
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
            }
            updateStorageTargetFieldHints();
            storageTargetModal.classList.remove('hidden');
        }

        function closeStorageTargetModal() {
            storageTargetModal?.classList.add('hidden');
        }

        openStorageTargetModalBtn?.addEventListener('click', () => openStorageTargetModal('create'));
        document.querySelectorAll('[data-close-storage-target-modal]').forEach((el) => {
            el.addEventListener('click', closeStorageTargetModal);
        });

        storageTargetProject?.addEventListener('change', () => {
            fillStorageTargetEnvironmentOptions(storageTargetProject.value, '');
        });
        storageTargetProvider?.addEventListener('change', () => {
            updateStorageTargetCredentialOptions('');
            updateStorageTargetFieldHints();
        });
        updateStorageTargetCredentialOptions('');
        updateStorageTargetFieldHints();

        document.querySelectorAll('.edit-storage-target-btn').forEach((btn) => {
            btn.addEventListener('click', () => {
                const row = btn.closest('.storage-target-row');
                if (!row || !storageTargetForm) return;
                openStorageTargetModal('edit', row);
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
        localTree: [],
        localFiles: [],
        localItems: [],
        uploading: false,
        cancelled: false,
        fileProgress: {},
        doneBytes: 0,
        totalBytes: 0,
        currentJobId: null,
        eventSource: null,
        localRenderOffset: 0,
        openManifestJobId: null,
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

    function formatDateTime(value) {
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

    function sortNameAsc(a, b) {
        return String(a.name || '').localeCompare(String(b.name || ''), 'zh-CN', { sensitivity: 'base' });
    }

    function renderRemoteList() {
        const folders = [...state.remoteFolders].sort(sortNameAsc);
        const files = [...state.remoteFiles].sort(sortNameAsc);
        const hasContent = folders.length || files.length;
        els.remoteEmpty.classList.toggle('hidden', hasContent);
        els.remoteList.innerHTML = '';

        folders.forEach((folder) => {
            const tr = document.createElement('tr');
            tr.className = 'hover:bg-indigo-50';
            tr.innerHTML = `
                <td class="px-3 py-2"><input type="checkbox" class="remote-check rounded" data-type="folder" data-prefix="${folder.prefix}"></td>
                <td class="px-3 py-2"><button type="button" class="remote-folder text-indigo-700 hover:underline text-left" data-prefix="${folder.prefix}"><i class="fas fa-folder text-amber-500 mr-2"></i>${escapeHtml(folder.name)}</button></td>
                <td class="px-3 py-2 text-right text-gray-400">—</td>
                <td class="px-3 py-2 text-right text-gray-400">—</td>`;
            els.remoteList.appendChild(tr);
        });

        files.forEach((file) => {
            const tr = document.createElement('tr');
            tr.className = 'hover:bg-gray-50';
            tr.innerHTML = `
                <td class="px-3 py-2"><input type="checkbox" class="remote-check rounded" data-type="file" data-key="${file.key}"></td>
                <td class="px-3 py-2 truncate max-w-[240px]" title="${escapeHtml(file.key)}"><i class="fas fa-file text-gray-400 mr-2"></i>${escapeHtml(file.name)}</td>
                <td class="px-3 py-2 text-right text-gray-500">${formatBytes(file.size)}</td>
                <td class="px-3 py-2 text-right text-gray-500 whitespace-nowrap">${formatDateTime(file.last_modified)}</td>`;
            els.remoteList.appendChild(tr);
        });

        els.remoteDelete.classList.toggle('hidden', !state.canDelete);
        bindRemoteEvents();
    }

    function escapeHtml(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
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

    function basenameOf(path) {
        const parts = String(path || '').replace(/\\/g, '/').split('/').filter(Boolean);
        return parts[parts.length - 1] || path || '';
    }

    function createFolderNode(name, path) {
        return {
            id: `${path}/`,
            kind: 'folder',
            name,
            path,
            selected: true,
            expanded: true,
            children: [],
        };
    }

    function createFileNode(file, path) {
        return {
            id: path,
            kind: 'file',
            name: basenameOf(path),
            path,
            file,
            selected: true,
            status: 'pending',
            statusText: '待上传',
            progress: 0,
        };
    }

    function sortTreeChildren(children) {
        children.sort((a, b) => {
            if (a.kind !== b.kind) return a.kind === 'folder' ? -1 : 1;
            return sortNameAsc(a, b);
        });
        return children;
    }

    function ensureFolderPath(rootChildren, folderPath) {
        const parts = String(folderPath || '').replace(/\\/g, '/').split('/').filter(Boolean);
        let children = rootChildren;
        let acc = '';
        parts.forEach((part) => {
            acc = acc ? `${acc}/${part}` : part;
            let folder = children.find((node) => node.kind === 'folder' && node.name === part);
            if (!folder) {
                folder = createFolderNode(part, acc);
                children.push(folder);
                sortTreeChildren(children);
            }
            children = folder.children;
        });
        return children;
    }

    function addFileToTree(rootChildren, file, path) {
        const normalized = String(path || file.name || '').replace(/\\/g, '/').replace(/^\/+/, '');
        if (!normalized) return null;
        if (rootChildren === state.localTree && state.localFiles.some((item) => item.path === normalized)) {
            return null;
        }
        const parts = normalized.split('/');
        const fileName = parts.pop();
        const parentChildren = parts.length ? ensureFolderPath(rootChildren, parts.join('/')) : rootChildren;
        if (parentChildren.some((node) => node.kind === 'file' && node.name === fileName)) return null;
        const node = createFileNode(file, normalized);
        parentChildren.push(node);
        sortTreeChildren(parentChildren);
        state.localFiles.push(node);
        state.localItems = state.localFiles;
        return node;
    }

    function walkTree(nodes, visitor, depth = 0) {
        nodes.forEach((node) => {
            visitor(node, depth);
            if (node.kind === 'folder' && node.children && node.children.length) {
                walkTree(node.children, visitor, depth + 1);
            }
        });
    }

    function flattenVisibleTree(nodes, depth = 0, out = []) {
        nodes.forEach((node) => {
            out.push({ node, depth });
            if (node.kind === 'folder' && node.expanded) {
                flattenVisibleTree(node.children || [], depth + 1, out);
            }
        });
        return out;
    }

    function setNodeSelected(node, selected) {
        node.selected = selected;
        if (node.kind === 'folder') {
            (node.children || []).forEach((child) => setNodeSelected(child, selected));
        }
    }

    function syncFolderSelection(node) {
        if (node.kind !== 'folder') return;
        (node.children || []).forEach(syncFolderSelection);
        const children = node.children || [];
        if (!children.length) return;
        node.selected = children.every((child) => child.selected);
    }

    function syncAllFolderSelections() {
        state.localTree.forEach(syncFolderSelection);
    }

    function collectSelectedFiles() {
        return state.localFiles.filter((item) => item.selected);
    }

    function collectSelectedDirectories() {
        const dirs = new Set();
        walkTree(state.localTree, (node) => {
            if (node.kind !== 'folder' || !node.selected) return;
            dirs.add(node.path);
        });
        collectSelectedFiles().forEach((fileNode) => {
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

    function findFileNodeByPath(path) {
        return state.localFiles.find((item) => item.path === path);
    }

    function renderLocalList() {
        const has = state.localTree.length > 0;
        els.localEmpty.classList.toggle('hidden', has);
        els.localList.innerHTML = '';

        const visible = flattenVisibleTree(state.localTree);
        visible.forEach(({ node, depth }) => {
            const tr = document.createElement('tr');
            tr.className = node.kind === 'folder' ? 'hover:bg-indigo-50' : 'hover:bg-gray-50';
            tr.dataset.path = node.path;
            tr.dataset.kind = node.kind;
            const pad = 8 + depth * 16;
            if (node.kind === 'folder') {
                const icon = node.expanded ? 'fa-caret-down' : 'fa-caret-right';
                tr.innerHTML = `
                    <td class="px-3 py-2"><input type="checkbox" class="local-check rounded" data-path="${escapeHtml(node.path)}" data-kind="folder" ${node.selected ? 'checked' : ''} ${state.uploading ? 'disabled' : ''}></td>
                    <td class="px-3 py-2">
                        <button type="button" class="local-fold text-left w-full" data-path="${escapeHtml(node.path)}" style="padding-left:${pad}px">
                            <i class="fas ${icon} text-gray-400 mr-1 w-3 inline-block"></i>
                            <i class="fas fa-folder text-amber-500 mr-2"></i>${escapeHtml(node.name)}
                        </button>
                    </td>
                    <td class="px-3 py-2 text-right text-gray-400">—</td>
                    <td class="px-3 py-2 text-xs text-gray-400">${(node.children || []).length} 项</td>`;
            } else {
                const statusClass = node.status === 'done' ? 'text-green-600' : node.status === 'failed' ? 'text-red-600' : 'text-gray-600';
                tr.innerHTML = `
                    <td class="px-3 py-2"><input type="checkbox" class="local-check rounded" data-path="${escapeHtml(node.path)}" data-kind="file" ${node.selected ? 'checked' : ''} ${state.uploading ? 'disabled' : ''}></td>
                    <td class="px-3 py-2 truncate max-w-[240px]" title="${escapeHtml(node.path)}">
                        <span style="padding-left:${pad}px"><i class="fas fa-file text-gray-400 mr-2"></i>${escapeHtml(node.name)}</span>
                    </td>
                    <td class="px-3 py-2 text-right text-gray-500">${formatBytes(node.file.size)}</td>
                    <td class="px-3 py-2">
                        <div class="w-full bg-gray-200 rounded-full h-1.5 mb-1"><div class="local-bar bg-green-500 h-1.5 rounded-full transition-all" style="width:${node.progress || 0}%"></div></div>
                        <span class="text-xs ${statusClass} local-status">${node.statusText || '待上传'}</span>
                    </td>`;
            }
            els.localList.appendChild(tr);
        });

        let total = 0;
        state.localFiles.forEach((item) => { total += item.file.size || 0; });
        const selectedCount = collectSelectedFiles().length;
        els.localSummary.textContent = has
            ? `已选 ${selectedCount}/${state.localFiles.length} 个文件，共 ${formatBytes(total)}`
            : '未选择文件';
        els.localUpload.disabled = !has || state.uploading || selectedCount === 0;

        els.localList.querySelectorAll('.local-check').forEach((cb) => {
            cb.addEventListener('change', () => {
                const path = cb.dataset.path;
                if (cb.dataset.kind === 'folder') {
                    const folder = findTreeNode(state.localTree, path, 'folder');
                    if (folder) setNodeSelected(folder, cb.checked);
                } else {
                    const fileNode = findFileNodeByPath(path);
                    if (fileNode) fileNode.selected = cb.checked;
                }
                syncAllFolderSelections();
                renderLocalList();
            });
        });
        els.localList.querySelectorAll('.local-fold').forEach((btn) => {
            btn.addEventListener('click', () => {
                const folder = findTreeNode(state.localTree, btn.dataset.path, 'folder');
                if (!folder) return;
                folder.expanded = !folder.expanded;
                renderLocalList();
            });
        });
    }

    function findTreeNode(nodes, path, kind) {
        for (const node of nodes) {
            if (node.path === path && (!kind || node.kind === kind)) return node;
            if (node.kind === 'folder') {
                const found = findTreeNode(node.children || [], path, kind);
                if (found) return found;
            }
        }
        return null;
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
            addFileToTree(state.localTree, file, file.webkitRelativePath || file.name);
        });
        syncAllFolderSelections();
        renderLocalList();
    }

    function clearLocalSelection() {
        state.localTree = [];
        state.localFiles = [];
        state.localItems = [];
        renderLocalList();
    }

    function updateLocalItem(indexOrPath, patch) {
        let node = null;
        if (typeof indexOrPath === 'number') {
            node = state.localFiles[indexOrPath];
        } else if (indexOrPath && typeof indexOrPath === 'object') {
            node = indexOrPath;
        } else {
            node = findFileNodeByPath(indexOrPath);
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

    function selectedStorageProvider() {
        const opt = els.target && els.target.selectedOptions && els.target.selectedOptions[0];
        return ((opt && opt.dataset.provider) || '').toLowerCase();
    }

    function isProxyUploadTarget() {
        return PROXY_PROVIDERS.has(selectedStorageProvider());
    }

    function updateTransportHint() {
        const proxy = isProxyUploadTarget();
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

    function xhrProxyUpload(targetId, prefix, file, filename, onProgress) {
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

    async function uploadProxyFile(entry, targetId, prefix) {
        const { item, index, meta } = entry;
        if (!meta) throw new Error('任务文件缺失');
        const fileKey = meta.id;
        state.fileProgress[fileKey] = 0;
        updateLocalItem(index, { status: 'uploading', statusText: '代理上传中...', progress: 0 });
        sendHeartbeat(fileKey, 0);
        try {
            const data = await xhrProxyUpload(
                targetId,
                prefix,
                item.file,
                item.path,
                (loaded, total) => {
                    state.fileProgress[fileKey] = loaded;
                    const percent = total ? Math.min(100, Math.round((loaded / total) * 100)) : 0;
                    updateLocalItem(index, { progress: percent, statusText: `${percent}%`, status: 'uploading' });
                    updateGlobalProgress();
                    if (loaded % (512 * 1024) < 65536) sendHeartbeat(fileKey, loaded);
                },
            );
            if (!data || !data.success) throw new Error((data && data.error) || '代理上传失败');
            let statusText = '完成';
            try {
                await fetchJson(`/api/upload/files/${fileKey}/complete`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ proxy: true }),
                });
            } catch (err) {
                // The object is already stored. A missing ETag must not show a failed row.
                statusText = '完成（任务记录未更新）';
                console.warn('proxy upload complete skipped', err);
            }
            state.doneBytes += item.file.size;
            updateLocalItem(index, { status: 'done', statusText, progress: 100 });
            if (window.UploadIdb) {
                await UploadIdb.saveFileState(state.currentJobId, fileKey, item.path, { status: 'done' });
            }
        } finally {
            delete state.fileProgress[fileKey];
            updateGlobalProgress();
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

    function createLimiter(concurrency) {
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

    async function walkFileList(files, acceptFile, acceptFolder) {
        for (const file of files) {
            if (state.cancelled) return;
            const path = file.webkitRelativePath || file.name;
            const parts = String(path).replace(/\\/g, '/').split('/').filter(Boolean);
            if (acceptFolder && parts.length > 1) {
                await acceptFolder(parts.slice(0, -1).join('/'));
            }
            await acceptFile(file, path);
        }
    }

    async function walkDirectoryHandle(dirHandle, prefix, acceptFile, acceptFolder) {
        if (state.cancelled) return;
        if (prefix && acceptFolder) await acceptFolder(prefix);
        const files = [];
        const subdirs = [];
        for await (const [name, handle] of dirHandle.entries()) {
            if (state.cancelled) return;
            const path = prefix ? `${prefix}/${name}` : name;
            if (handle.kind === 'directory') subdirs.push({ handle, path });
            else files.push({ handle, path });
        }
        await Promise.all([
            runPool(files, 8, async (entry) => {
                if (state.cancelled) return;
                const file = await entry.handle.getFile();
                await acceptFile(file, entry.path);
            }),
            runPool(subdirs, DIR_WALK_CONCURRENCY, async (entry) => {
                await walkDirectoryHandle(entry.handle, entry.path, acceptFile, acceptFolder);
            }),
        ]);
    }

    async function loadLocalFolderTree(walk) {
        if (state.uploading) return;
        clearLocalSelection();
        els.globalText.textContent = '正在遍历子目录...';
        setGlobalProgressVisible(true);
        let discovered = 0;
        let renderTimer = null;
        const scheduleRender = () => {
            if (renderTimer) return;
            renderTimer = setTimeout(() => {
                renderTimer = null;
                renderLocalList();
                els.globalText.textContent = `已列出 ${discovered} 个文件，勾选后点击「上传选中」`;
            }, 120);
        };
        try {
            await walk(
                async (file, path) => {
                    addFileToTree(state.localTree, file, path);
                    discovered += 1;
                    scheduleRender();
                },
                async (folderPath) => {
                    ensureFolderPath(state.localTree, folderPath);
                    scheduleRender();
                },
            );
            syncAllFolderSelections();
            renderLocalList();
            els.globalText.textContent = discovered
                ? `已列出 ${discovered} 个文件，勾选后点击「上传选中」`
                : '文件夹里没有文件';
        } catch (err) {
            els.globalText.textContent = `读取文件夹失败: ${err.message || err}`;
        } finally {
            if (renderTimer) clearTimeout(renderTimer);
        }
    }

    async function ensureRemoteDirectories(relativeDirs) {
        if (!relativeDirs.length) return;
        const remoteBase = (els.remotePath.value || '').replace(/\/+$/, '');
        const directories = relativeDirs.map((dir) => (
            remoteBase ? `${remoteBase}/${dir}` : dir
        ));
        const chunkSize = 100;
        for (let i = 0; i < directories.length; i += chunkSize) {
            if (state.cancelled) return;
            const chunk = directories.slice(i, i + chunkSize);
            await fetchJson('/api/storage/mkdir', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    target_id: els.target.value,
                    directories: chunk,
                }),
            });
        }
    }

    async function startUpload() {
        const selected = collectSelectedFiles().map((item) => ({
            item,
            index: state.localFiles.indexOf(item),
        }));
        if (!selected.length || state.uploading) return;
        if (!els.target.value) {
            alert('请先选择存储目标');
            return;
        }

        state.uploading = true;
        state.cancelled = false;
        state.doneBytes = 0;
        state.fileProgress = {};
        state.totalBytes = selected.reduce((sum, { item }) => sum + (item.file.size || 0), 0);
        setGlobalProgressVisible(true);
        els.localUpload.disabled = true;
        els.localCancel.classList.remove('hidden');
        els.globalText.textContent = `正在创建云端目录并分批上传（${selected.length} 文件）...`;
        updateGlobalProgress();
        renderLocalList();

        const uploadTargetId = els.target.value;
        const uploadPrefix = els.remotePath.value.trim();
        const proxyUpload = isProxyUploadTarget();
        const largeLimit = createLimiter(MAX_LARGE_CONCURRENCY);
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
                const data = await fetchJson('/api/upload/jobs', {
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
                state.currentJobId = jobId;
                state.openManifestJobId = jobId;
                subscribeJobStream(jobId);
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
            const data = await fetchJson(`/api/upload/jobs/${jobId}/init-batch`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ files: manifest }),
            });
            return data.files || [];
        }

        function enqueueSmall(chunk) {
            const run = smallChain.then(() => uploadSmallPresignBatch(chunk));
            smallChain = run.catch(() => {});
            uploads.push(run);
        }

        function scheduleUploads(entries, metas) {
            if (proxyUpload) {
                entries.forEach((entry, i) => {
                    uploads.push(largeLimit(async () => {
                        try {
                            await uploadProxyFile(
                                { item: entry.item, index: entry.index, meta: metas[i] },
                                uploadTargetId,
                                uploadPrefix,
                            );
                        } catch (err) {
                            updateLocalItem(entry.index, {
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
                if (entry.item.file.size > MULTIPART_THRESHOLD) {
                    uploads.push(largeLimit(async () => {
                        try {
                            await uploadSingleLocal(entry.item, entry.index, metas[i]);
                            if (window.UploadIdb) {
                                await UploadIdb.saveFileState(jobId, metas[i].id, entry.item.path, { status: 'done' });
                            }
                        } catch (err) {
                            updateLocalItem(entry.index, {
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
            while (smallPending.length >= PRESIGN_BATCH_SIZE) {
                enqueueSmall(smallPending.splice(0, PRESIGN_BATCH_SIZE));
            }
        }

        async function flush(entries) {
            if (!entries.length || state.cancelled) return;
            const run = initChain.then(async () => {
                if (state.cancelled) return;
                const metas = await registerBatch(entries);
                const readyEntries = [];
                const readyMetas = [];
                entries.forEach((entry, i) => {
                    if (!metas[i]) {
                        updateLocalItem(entry.index, { status: 'failed', statusText: '登记失败', progress: 0 });
                        return;
                    }
                    readyEntries.push(entry);
                    readyMetas.push(metas[i]);
                });
                scheduleUploads(readyEntries, readyMetas);
                const done = selected.filter(({ item }) => item.status === 'done' || item.status === 'failed' || item.status === 'uploading').length;
                els.globalText.textContent = `正在分批上传 ${Math.min(done + readyEntries.length, selected.length)}/${selected.length} ...`;
            });
            initChain = run.catch((err) => {
                entries.forEach((entry) => {
                    updateLocalItem(entry.index, {
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
            state.openManifestJobId = null;
            try {
                await fetchJson(`/api/upload/jobs/${jobId}/close-manifest`, { method: 'POST' });
            } catch (err) {
                // 断网时改用 keepalive，尽量让服务端收口。
                closeManifestKeepalive(jobId);
                throw err;
            }
            if (window.UploadIdb) await UploadIdb.saveSession({ jobId, active: false });
        }

        try {
            const dirs = collectSelectedDirectories();
            if (dirs.length) {
                els.globalText.textContent = `正在创建云端目录（${dirs.length}）...`;
                await ensureRemoteDirectories(dirs);
            }

            for (let offset = 0; offset < selected.length; offset += FOLDER_FLUSH_SIZE) {
                if (state.cancelled) break;
                const chunk = selected.slice(offset, offset + FOLDER_FLUSH_SIZE);
                await flush(chunk);
            }
            await initChain;
            if (smallPending.length) enqueueSmall(smallPending.splice(0, smallPending.length));
            await Promise.all(uploads);

            const failed = selected.filter(({ item }) => item.status === 'failed').length;
            const succeeded = selected.filter(({ item }) => item.status === 'done').length;
            if (state.cancelled) {
                els.globalText.textContent = `已取消：完成 ${succeeded}，失败 ${failed}`;
            } else if (!succeeded) {
                els.globalText.textContent = `上传结束：0 成功，${failed} 失败`;
            } else if (failed) {
                els.globalText.textContent = `上传结束：${succeeded} 成功，${failed} 失败。已提交成功文件的 CDN 刷新`;
            } else {
                els.globalText.textContent = `全部上传完成（${succeeded} 个文件），已提交 CDN 刷新`;
            }
            if (state.eventSource) state.eventSource.close();
            await loadRemoteList();
            await loadJobHistory();
        } catch (err) {
            els.globalText.textContent = `上传失败: ${err.message}`;
        } finally {
            try {
                await closeManifest();
            } catch (_) {
                /* closeManifestKeepalive already tried */
            }
            state.uploading = false;
            state.cancelled = false;
            els.localCancel.classList.add('hidden');
            renderLocalList();
        }
    }

    function closeManifestKeepalive(jobId) {
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

    function bindManifestUnloadGuard() {
        const flushOpenManifest = () => {
            const jobId = state.openManifestJobId;
            if (!jobId) return;
            state.openManifestJobId = null;
            closeManifestKeepalive(jobId);
            if (window.UploadIdb) {
                try { UploadIdb.saveSession({ jobId, active: false }); } catch (_) { /* ignore */ }
            }
        };
        window.addEventListener('pagehide', flushOpenManifest);
        window.addEventListener('beforeunload', flushOpenManifest);
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
    els.target?.addEventListener('change', () => {
        state.remotePrefix = '';
        els.remotePath.value = '';
        updateTransportHint();
        loadRemoteList();
    });
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

    els.localFolder?.closest('label')?.addEventListener('click', async (event) => {
        if (typeof window.showDirectoryPicker !== 'function') return;
        event.preventDefault();
        if (state.uploading) return;
        try {
            const handle = await window.showDirectoryPicker({ mode: 'read' });
            await loadLocalFolderTree((acceptFile, acceptFolder) => (
                walkDirectoryHandle(handle, handle.name, acceptFile, acceptFolder)
            ));
        } catch (err) {
            if (err && err.name === 'AbortError') return;
            els.globalText.textContent = `读取文件夹失败: ${err.message || err}`;
            setGlobalProgressVisible(true);
        }
    });
    els.localFolder?.addEventListener('change', (e) => {
        const files = Array.from(e.target.files || []);
        e.target.value = '';
        if (!files.length || state.uploading) return;
        loadLocalFolderTree((acceptFile, acceptFolder) => walkFileList(files, acceptFile, acceptFolder));
    });
    els.localFile?.addEventListener('change', (e) => addLocalFiles(e.target.files));
    els.localClear?.addEventListener('click', () => {
        if (state.uploading) return;
        clearLocalSelection();
    });
    els.localUpload?.addEventListener('click', () => startUpload());
    els.localCancel?.addEventListener('click', () => { state.cancelled = true; });
    els.localSelectAll?.addEventListener('change', () => {
        const checked = !!els.localSelectAll.checked;
        state.localTree.forEach((node) => setNodeSelected(node, checked));
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

    bindManifestUnloadGuard();
    updateTransportHint();
    loadRemoteList().catch(() => {});
    loadJobHistory().catch(() => {});
    tryResumeSession().catch(() => {});
})();
