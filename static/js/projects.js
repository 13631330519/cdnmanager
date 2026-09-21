(function () {
    const projectsDataEl = document.getElementById('projects-data');
    const projectsData = projectsDataEl ? JSON.parse(projectsDataEl.textContent || '[]') : [];

    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function formatAllowedUsers(allowedUsers) {
        const users = Array.isArray(allowedUsers) ? allowedUsers : [];
        if (!users.length) return '所有人可见';
        return users.join(', ');
    }

    function parseAllowedUsersInput(raw) {
        if (!raw || !String(raw).trim()) return [];
        return [...new Set(String(raw).split(',').map((item) => item.trim()).filter(Boolean))];
    }

    function getEffectiveApiKey(project, environment) {
        if (environment && environment.api_key_secret) return environment.api_key_secret;
        if (project && project.api_key_secret) return project.api_key_secret;
        const defaultApiKeyEl = document.getElementById('default-api-key');
        const defaultApiKey = defaultApiKeyEl ? JSON.parse(defaultApiKeyEl.textContent || '""') : '';
        return defaultApiKey || '';
    }

    function hasAnyEnvironmentKey(project) {
        return (project.environments || []).some((env) => Boolean(env.api_key_secret));
    }

    function renderProjectsTree() {
        const container = document.getElementById('projectsTree');
        if (!container) return;

        if (!projectsData.length) {
            container.innerHTML = '<p class="text-gray-500 text-sm">暂无项目，请先创建。</p>';
            return;
        }

        container.innerHTML = projectsData.map((project) => {
            const hasProjectKey = Boolean(project.api_key_secret);
            const allEnvironmentsHaveKey = (project.environments || []).length > 0 && (project.environments || []).every((env) => Boolean(env.api_key_secret));
            const envBlocks = (project.environments || []).map((env) => {
                const effectiveKey = getEffectiveApiKey(project, env);
                const hasEnvKey = Boolean(env.api_key_secret);
                const showViewKey = Boolean(effectiveKey);
                const showGenerateKey = !hasEnvKey;

                return `
                <tr class="align-top">
                    <td class="px-3 py-2 text-sm text-gray-800">${escapeHtml(env.name)}</td>
                    <td class="px-3 py-2 text-xs text-gray-500">${escapeHtml(env.id)}</td>
                    <td class="px-3 py-2 text-xs text-gray-500">${hasEnvKey ? '环境独立 Key' : (project.api_key_secret ? '项目级 Key' : '默认公共 Key')}</td>
                    <td class="px-3 py-2 text-right">
                        <div class="flex flex-wrap justify-end gap-2">
                            ${showViewKey ? `<button type="button" class="view-api-key-btn text-xs bg-blue-500 hover:bg-blue-600 text-white px-2 py-1 rounded" data-project-id="${escapeHtml(project.id)}" data-environment-id="${escapeHtml(env.id)}">查看 API Key</button>` : ''}
                            <button type="button" class="edit-env-btn text-xs bg-indigo-500 hover:bg-indigo-600 text-white px-2 py-1 rounded" data-project-id="${escapeHtml(project.id)}" data-environment-id="${escapeHtml(env.id)}">编辑环境</button>
                            ${showGenerateKey ? `<button type="button" class="regen-env-key-btn text-xs bg-amber-500 hover:bg-amber-600 text-white px-2 py-1 rounded" data-project-id="${escapeHtml(project.id)}" data-environment-id="${escapeHtml(env.id)}">生成环境 API Key</button>` : ''}
                            <button type="button" class="delete-env-btn text-xs bg-red-500 hover:bg-red-600 text-white px-2 py-1 rounded" data-project-id="${escapeHtml(project.id)}" data-environment-id="${escapeHtml(env.id)}">删除环境</button>
                        </div>
                    </td>
                </tr>
            `;
            }).join('');

            const showProjectViewKey = !allEnvironmentsHaveKey && Boolean(getEffectiveApiKey(project, null));
            const showProjectGenerateKey = !hasProjectKey && (!project.environments || project.environments.length === 0 || !allEnvironmentsHaveKey);

            return `
                <div class="border rounded-xl p-4" data-project-id="${escapeHtml(project.id)}">
                    <div class="flex flex-wrap items-start justify-between gap-3 mb-4">
                        <div class="flex-1 min-w-[14rem]">
                            <h3 class="text-base font-semibold text-gray-800">${escapeHtml(project.name)}</h3>
                            <p class="text-sm text-gray-500">${escapeHtml(project.description || '无描述')}</p>
                            <p class="text-xs text-gray-400 mt-1">ID: ${escapeHtml(project.id)} · API Key: ${project.api_key_secret ? '已配置' : '未配置（使用环境级/公共默认 Key）'}</p>
                            <p class="text-xs text-gray-500 mt-1">授权用户: ${escapeHtml(formatAllowedUsers(project.allowed_users))}</p>
                        </div>
                        <div class="flex flex-wrap gap-2">
                            <button type="button" class="edit-project-btn text-xs bg-indigo-500 hover:bg-indigo-600 text-white px-2 py-1 rounded" data-project-id="${escapeHtml(project.id)}">编辑项目</button>
                            <button type="button" class="add-env-btn text-xs bg-green-600 hover:bg-green-700 text-white px-2 py-1 rounded" data-project-id="${escapeHtml(project.id)}">新增环境</button>
                            ${showProjectViewKey ? `<button type="button" class="view-api-key-btn text-xs bg-blue-500 hover:bg-blue-600 text-white px-2 py-1 rounded" data-project-id="${escapeHtml(project.id)}" data-scope="project">查看 API Key</button>` : ''}
                            ${showProjectGenerateKey ? `<button type="button" class="regen-project-key-btn text-xs bg-amber-500 hover:bg-amber-600 text-white px-2 py-1 rounded" data-project-id="${escapeHtml(project.id)}">生成项目 API Key</button>` : ''}
                            <button type="button" class="delete-project-btn text-xs bg-red-500 hover:bg-red-600 text-white px-2 py-1 rounded" data-project-id="${escapeHtml(project.id)}">删除项目</button>
                        </div>
                    </div>
                    <div class="space-y-2">
                        <h4 class="text-sm font-medium text-gray-700">环境列表</h4>
                        ${envBlocks ? `
                            <div class="overflow-x-auto border rounded-lg">
                                <table class="min-w-full divide-y divide-gray-200 text-sm">
                                    <thead class="bg-gray-50">
                                        <tr>
                                            <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">环境名</th>
                                            <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">ID</th>
                                            <th class="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">当前 Key</th>
                                            <th class="px-3 py-2 text-right text-xs font-medium text-gray-500 uppercase">操作</th>
                                        </tr>
                                    </thead>
                                    <tbody class="divide-y divide-gray-200 bg-white">
                                        ${envBlocks}
                                    </tbody>
                                </table>
                            </div>
                        ` : '<p class="text-xs text-gray-400">暂无环境</p>'}
                    </div>
                </div>
            `;
        }).join('');
    }

    async function reloadProjects() {
        const response = await fetch('/api/projects');
        const data = await response.json();
        if (!data.success) {
            alert(data.error || '加载项目失败');
            return;
        }
        projectsData.splice(0, projectsData.length, ...data.projects);
        renderProjectsTree();
        if (typeof window.refreshDomainProjectSelects === 'function') {
            window.refreshDomainProjectSelects(data.projects);
        }
    }

    function showApiKey(key) {
        const modal = document.getElementById('apiKeyModal');
        const valueEl = document.getElementById('apiKeyModalValue');
        if (modal && valueEl) {
            valueEl.textContent = key || '';
            modal.classList.remove('hidden');
            return;
        }
        prompt('请立即复制保存，此 Key 仅显示一次：', key);
    }

    function closeApiKeyModal() {
        const modal = document.getElementById('apiKeyModal');
        modal?.classList.add('hidden');
    }

    function showFormResult(resultDiv, message, success) {
        resultDiv.textContent = message;
        resultDiv.classList.remove('hidden');
        resultDiv.classList.toggle('text-green-600', success);
        resultDiv.classList.toggle('text-red-600', !success);
    }

    const projectModal = document.getElementById('projectEditModal');
    const projectModalTitle = document.getElementById('projectEditModalTitle');
    const createProjectForm = document.getElementById('createProjectForm');
    const environmentModal = document.getElementById('environmentEditModal');
    const environmentForm = document.getElementById('environmentEditForm');
    const environmentModalTitle = document.getElementById('environmentEditModalTitle');
    const environmentModalResult = document.getElementById('environmentEditResult');
    const environmentModalProjectId = document.getElementById('environmentModalProjectId');
    const environmentModalEnvironmentId = document.getElementById('environmentModalEnvironmentId');
    const environmentModalName = document.getElementById('environmentModalName');
    const environmentModalRegenerateBtn = document.getElementById('environmentModalRegenerateBtn');

    function openEnvironmentModal(projectId, environment) {
        if (!environmentModal || !environmentForm) return;
        const payload = environment || {};
        environmentForm.reset();
        environmentModalProjectId.value = projectId || '';
        environmentModalEnvironmentId.value = payload.id || '';
        environmentModalName.value = payload.name || '';
        environmentModalTitle.textContent = payload.id ? '编辑环境' : '新增环境';
        environmentModalRegenerateBtn.disabled = !payload.id;
        environmentModalRegenerateBtn.classList.toggle('opacity-50', !payload.id);
        environmentModalResult.classList.add('hidden');
        environmentModalResult.textContent = '';
        environmentModal.classList.remove('hidden');
    }

    function closeEnvironmentModal() {
        environmentModal?.classList.add('hidden');
    }

    function openProjectModal(project) {
        if (!projectModal || !createProjectForm) return;
        const form = createProjectForm;
        form.reset();
        form.project_id.value = project?.id || '';
        form.name.value = project?.name || '';
        form.description.value = project?.description || '';
        form.allowed_users.value = (project?.allowed_users || []).join(', ');
        projectModalTitle.textContent = project ? '编辑项目' : '新建项目';
        projectModal.classList.remove('hidden');
    }

    function closeProjectModal() {
        projectModal?.classList.add('hidden');
    }

    document.getElementById('openProjectCreateModalBtn')?.addEventListener('click', () => openProjectModal(null));
    document.querySelectorAll('[data-close-project-modal]').forEach((el) => {
        el.addEventListener('click', closeProjectModal);
    });
    document.querySelectorAll('[data-close-environment-modal]').forEach((el) => {
        el.addEventListener('click', closeEnvironmentModal);
    });
    document.querySelectorAll('[data-close-api-key-modal]').forEach((el) => {
        el.addEventListener('click', closeApiKeyModal);
    });
    document.getElementById('copyApiKeyBtn')?.addEventListener('click', async () => {
        const valueEl = document.getElementById('apiKeyModalValue');
        const value = valueEl ? valueEl.textContent : '';
        if (!value) return;
        try {
            await navigator.clipboard.writeText(value);
            alert('API Key 已复制到剪贴板');
        } catch (error) {
            const range = document.createRange();
            range.selectNodeContents(valueEl);
            const selection = window.getSelection();
            selection.removeAllRanges();
            selection.addRange(range);
            alert('复制失败，请手动选择并复制 API Key');
        }
    });

    if (createProjectForm) {
        createProjectForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            const form = event.currentTarget;
            const resultDiv = document.getElementById('createProjectResult');
            const submitBtn = form.querySelector('button[type="submit"]');
            const projectId = form.project_id.value;
            const payload = {
                name: form.name.value.trim(),
                description: form.description.value.trim(),
                allowed_users: parseAllowedUsersInput(form.allowed_users?.value),
            };
            if (!payload.name) return;

            submitBtn.disabled = true;
            try {
                const response = await fetch(projectId ? `/api/projects/${projectId}` : '/api/projects', {
                    method: projectId ? 'PUT' : 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                const data = await response.json();
                showFormResult(resultDiv, projectId ? (data.success ? '项目已更新' : (data.error || '更新失败')) : (data.success ? '项目已创建' : (data.error || '创建失败')), !!data.success);
                if (data.success) {
                    form.reset();
                    closeProjectModal();
                    await reloadProjects();
                }
            } catch (error) {
                showFormResult(resultDiv, `请求失败: ${error.message}`, false);
            } finally {
                submitBtn.disabled = false;
            }
        });
    }

    if (environmentForm) {
        environmentForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            const projectId = environmentModalProjectId.value;
            const environmentId = environmentModalEnvironmentId.value;
            const name = environmentModalName.value.trim();
            if (!projectId || !name) return;

            const body = { name };
            const url = environmentId ? `/api/projects/${projectId}/environments/${environmentId}` : `/api/projects/${projectId}/environments`;
            const method = environmentId ? 'PUT' : 'POST';
            const resultDiv = environmentModalResult;
            try {
                const response = await fetch(url, {
                    method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body),
                });
                const data = await response.json();
                showFormResult(resultDiv, data.success ? (environmentId ? '环境已更新' : '环境已创建') : (data.error || '保存失败'), !!data.success);
                if (data.success) {
                    closeEnvironmentModal();
                    await reloadProjects();
                }
            } catch (error) {
                showFormResult(resultDiv, `请求失败: ${error.message}`, false);
            }
        });
    }

    environmentModalRegenerateBtn?.addEventListener('click', async () => {
        const projectId = environmentModalProjectId.value;
        const environmentId = environmentModalEnvironmentId.value;
        if (!projectId || !environmentId) return;
        if (!confirm('重新生成将使旧的环境 API Key 失效，继续？')) return;
        const response = await fetch(`/api/projects/${projectId}/environments/${environmentId}/regenerate-key`, { method: 'POST' });
        const data = await response.json();
        if (data.success) {
            showApiKey(data.api_key);
            await reloadProjects();
        } else {
            alert(data.error || '生成失败');
        }
    });

    document.getElementById('projectsTree')?.addEventListener('submit', async (event) => {
        const form = event.target;
        if (form.classList.contains('update-project-form')) {
            event.preventDefault();
            const projectId = form.dataset.projectId;
            const response = await fetch(`/api/projects/${projectId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: form.name.value.trim(),
                    description: form.description.value.trim(),
                    allowed_users: parseAllowedUsersInput(form.allowed_users?.value),
                }),
            });
            const data = await response.json();
            if (data.success) await reloadProjects();
            else alert(data.error || '保存失败');
            return;
        }
        if (form.classList.contains('create-env-form')) {
            event.preventDefault();
            const projectId = form.dataset.projectId;
            const response = await fetch(`/api/projects/${projectId}/environments`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: form.name.value.trim() }),
            });
            const data = await response.json();
            if (data.success) {
                form.reset();
                await reloadProjects();
            } else alert(data.error || '添加环境失败');
            return;
        }
        if (form.classList.contains('update-env-form')) {
            event.preventDefault();
            const projectId = form.dataset.projectId;
            const environmentId = form.dataset.environmentId;
            const response = await fetch(`/api/projects/${projectId}/environments/${environmentId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: form.name.value.trim() }),
            });
            const data = await response.json();
            if (data.success) await reloadProjects();
            else alert(data.error || '保存环境失败');
        }
    });

    document.getElementById('projectsTree')?.addEventListener('click', async (event) => {
        const viewApiKeyBtn = event.target.closest('.view-api-key-btn');
        if (viewApiKeyBtn) {
            const project = projectsData.find((item) => item.id === viewApiKeyBtn.dataset.projectId);
            const env = project && viewApiKeyBtn.dataset.environmentId ? (project.environments || []).find((item) => item.id === viewApiKeyBtn.dataset.environmentId) : null;
            const key = getEffectiveApiKey(project, env);
            if (!key) {
                alert('当前没有可查看的 API Key，已按项目或默认密钥规则生效。');
                return;
            }
            showApiKey(key);
            return;
        }
        const projectBtn = event.target.closest('.regen-project-key-btn');
        if (projectBtn) {
            if (!confirm('重新生成将使旧的项目 API Key 失效，继续？')) return;
            const response = await fetch(`/api/projects/${projectBtn.dataset.projectId}/regenerate-key`, { method: 'POST' });
            const data = await response.json();
            if (data.success) {
                showApiKey(data.api_key);
                await reloadProjects();
            } else alert(data.error || '生成失败');
            return;
        }
        const envBtn = event.target.closest('.regen-env-key-btn');
        if (envBtn) {
            if (!confirm('重新生成将使旧的环境 API Key 失效，继续？')) return;
            const response = await fetch(`/api/projects/${envBtn.dataset.projectId}/environments/${envBtn.dataset.environmentId}/regenerate-key`, { method: 'POST' });
            const data = await response.json();
            if (data.success) {
                showApiKey(data.api_key);
                await reloadProjects();
            } else alert(data.error || '生成失败');
            return;
        }
        const addEnvBtn = event.target.closest('.add-env-btn');
        if (addEnvBtn) {
            openEnvironmentModal(addEnvBtn.dataset.projectId, null);
            return;
        }
        const editProjectBtn = event.target.closest('.edit-project-btn');
        if (editProjectBtn) {
            const project = projectsData.find((item) => item.id === editProjectBtn.dataset.projectId);
            openProjectModal(project);
            return;
        }
        const editEnvBtn = event.target.closest('.edit-env-btn');
        if (editEnvBtn) {
            const project = projectsData.find((item) => item.id === editEnvBtn.dataset.projectId);
            const env = (project?.environments || []).find((item) => item.id === editEnvBtn.dataset.environmentId);
            openEnvironmentModal(project?.id, env || null);
            return;
        }
        const deleteProjectBtn = event.target.closest('.delete-project-btn');
        if (deleteProjectBtn) {
            if (!confirm('删除项目将解除所有域名绑定，继续？')) return;
            const response = await fetch(`/api/projects/${deleteProjectBtn.dataset.projectId}`, { method: 'DELETE' });
            const data = await response.json();
            if (data.success) await reloadProjects();
            else alert(data.error || '删除失败');
            return;
        }
        const deleteEnvBtn = event.target.closest('.delete-env-btn');
        if (deleteEnvBtn) {
            if (!confirm('删除环境将解除相关域名绑定，继续？')) return;
            const response = await fetch(`/api/projects/${deleteEnvBtn.dataset.projectId}/environments/${deleteEnvBtn.dataset.environmentId}`, { method: 'DELETE' });
            const data = await response.json();
            if (data.success) await reloadProjects();
            else alert(data.error || '删除失败');
        }
    });

    renderProjectsTree();
})();
