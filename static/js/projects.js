(function () {
    const projectsDataEl = document.getElementById('projects-data');
    if (!projectsDataEl) return;

    const projectsData = JSON.parse(projectsDataEl.textContent || '[]');

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

    function renderProjectsTree() {
        const container = document.getElementById('projectsTree');
        if (!container) return;

        if (!projectsData.length) {
            container.innerHTML = '<p class="text-gray-500 text-sm">暂无项目，请先创建。</p>';
            return;
        }

        container.innerHTML = projectsData.map((project) => {
            const envBlocks = (project.environments || []).map((env) => `
                <div class="border rounded-lg p-4 bg-gray-50" data-environment-id="${escapeHtml(env.id)}">
                    <div class="flex flex-wrap items-center justify-between gap-2 mb-3">
                        <div>
                            <span class="font-medium text-gray-800">${escapeHtml(env.name)}</span>
                            <span class="text-xs text-gray-400 ml-2">${escapeHtml(env.id)}</span>
                        </div>
                        <div class="flex flex-wrap gap-2">
                            <button type="button" class="regen-env-key-btn text-xs bg-amber-500 hover:bg-amber-600 text-white px-2 py-1 rounded" data-project-id="${escapeHtml(project.id)}" data-environment-id="${escapeHtml(env.id)}">生成环境 API Key</button>
                            <button type="button" class="delete-env-btn text-xs bg-red-500 hover:bg-red-600 text-white px-2 py-1 rounded" data-project-id="${escapeHtml(project.id)}" data-environment-id="${escapeHtml(env.id)}">删除环境</button>
                        </div>
                    </div>
                    <form class="update-env-form flex flex-wrap items-end gap-3" data-project-id="${escapeHtml(project.id)}" data-environment-id="${escapeHtml(env.id)}">
                        <div class="flex-1 min-w-[12rem]">
                            <label class="block text-xs text-gray-500 mb-1">环境名称</label>
                            <input type="text" name="name" value="${escapeHtml(env.name)}" class="w-full px-3 py-2 border rounded-lg text-sm" required>
                        </div>
                        <button type="submit" class="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg text-sm">保存环境</button>
                    </form>
                </div>
            `).join('');

            return `
                <div class="border rounded-xl p-4" data-project-id="${escapeHtml(project.id)}">
                    <div class="flex flex-wrap items-start justify-between gap-3 mb-4">
                        <div>
                            <h3 class="text-base font-semibold text-gray-800">${escapeHtml(project.name)}</h3>
                            <p class="text-sm text-gray-500">${escapeHtml(project.description || '无描述')}</p>
                            <p class="text-xs text-gray-400 mt-1">ID: ${escapeHtml(project.id)} · API Key: ${project.api_key_secret ? '已配置' : '未配置（使用公共默认 Key）'}</p>
                            <p class="text-xs text-gray-500 mt-1">授权用户: ${escapeHtml(formatAllowedUsers(project.allowed_users))}</p>
                        </div>
                        <div class="flex flex-wrap gap-2">
                            <button type="button" class="regen-project-key-btn text-xs bg-amber-500 hover:bg-amber-600 text-white px-2 py-1 rounded" data-project-id="${escapeHtml(project.id)}">生成项目 API Key</button>
                            <button type="button" class="delete-project-btn text-xs bg-red-500 hover:bg-red-600 text-white px-2 py-1 rounded" data-project-id="${escapeHtml(project.id)}">删除项目</button>
                        </div>
                    </div>
                    <form class="update-project-form grid gap-3 md:grid-cols-3 mb-4" data-project-id="${escapeHtml(project.id)}">
                        <input type="text" name="name" value="${escapeHtml(project.name)}" class="px-3 py-2 border rounded-lg text-sm" required>
                        <input type="text" name="description" value="${escapeHtml(project.description || '')}" placeholder="描述" class="px-3 py-2 border rounded-lg text-sm">
                        <input type="text" name="allowed_users" value="${escapeHtml((project.allowed_users || []).join(', '))}" placeholder="授权用户，逗号分隔；留空=所有人可见" class="px-3 py-2 border rounded-lg text-sm">
                        <button type="submit" class="bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg text-sm md:col-span-3 w-fit">保存项目</button>
                    </form>
                    <div class="space-y-3">
                        <h4 class="text-sm font-medium text-gray-700">环境</h4>
                        ${envBlocks || '<p class="text-xs text-gray-400">暂无环境</p>'}
                        <form class="create-env-form flex flex-wrap items-end gap-3 border-t pt-3" data-project-id="${escapeHtml(project.id)}">
                            <div class="flex-1 min-w-[12rem]">
                                <label class="block text-xs text-gray-500 mb-1">新环境名称</label>
                                <input type="text" name="name" placeholder="如 prod / staging" class="w-full px-3 py-2 border rounded-lg text-sm" required>
                            </div>
                            <button type="submit" class="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded-lg text-sm">添加环境</button>
                        </form>
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
        prompt('请立即复制保存，此 Key 仅显示一次：', key);
    }

    function showFormResult(resultDiv, message, success) {
        resultDiv.textContent = message;
        resultDiv.classList.remove('hidden');
        resultDiv.classList.toggle('text-green-600', success);
        resultDiv.classList.toggle('text-red-600', !success);
    }

    const createProjectForm = document.getElementById('createProjectForm');
    if (createProjectForm) {
        createProjectForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            const form = event.currentTarget;
            const resultDiv = document.getElementById('createProjectResult');
            const submitBtn = form.querySelector('button[type="submit"]');
            const payload = {
                name: form.name.value.trim(),
                description: form.description.value.trim(),
                allowed_users: parseAllowedUsersInput(form.allowed_users?.value),
            };
            if (!payload.name) return;

            submitBtn.disabled = true;
            try {
                const response = await fetch('/api/projects', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                const data = await response.json();
                showFormResult(resultDiv, data.success ? '项目已创建' : (data.error || '创建失败'), !!data.success);
                if (data.success) {
                    form.reset();
                    await reloadProjects();
                }
            } catch (error) {
                showFormResult(resultDiv, `请求失败: ${error.message}`, false);
            } finally {
                submitBtn.disabled = false;
            }
        });
    }

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
