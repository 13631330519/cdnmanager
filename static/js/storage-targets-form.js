/* Storage-target admin form: provider hints, credential options, filters. */
(function () {
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
                    ? 'FTP / SFTP / FTPS：三个输入框依次为 Host、端口、根路径。显式 FTPS（AUTH TLS）默认端口为 21。默认校验证书和主机密钥，旧环境可勾选「允许不安全连接」。'
                    : '对象存储：填写 Bucket、Region，Endpoint 可选。';
            }
            const insecureRow = document.getElementById('storageTargetInsecureTlsRow');
            const insecureInput = document.getElementById('storageTargetInsecureTls');
            if (insecureRow) insecureRow.classList.toggle('hidden', !ftp);
            if (!ftp && insecureInput) insecureInput.checked = false;
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
                const insecureInput = document.getElementById('storageTargetInsecureTls');
                if (insecureInput) insecureInput.checked = row.dataset.insecureTls === '1';
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

})();
