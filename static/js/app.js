const providerCredentialsEl = document.getElementById('provider-credentials');
const providerCredentials = providerCredentialsEl
    ? JSON.parse(providerCredentialsEl.textContent)
    : {};
const projectsDataEl = document.getElementById('projects-data');
const domainProjectsData = projectsDataEl ? JSON.parse(projectsDataEl.textContent) : [];

function fillProjectSelect(selectEl, selectedId) {
    if (!selectEl) return;
    const options = ['<option value="">未绑定</option>'];
    domainProjectsData.forEach((project) => {
        options.push(`<option value="${project.id}" ${project.id === selectedId ? 'selected' : ''}>${project.name}</option>`);
    });
    selectEl.innerHTML = options.join('');
}

function fillEnvironmentSelect(selectEl, projectId, selectedId) {
    if (!selectEl) return;
    const options = ['<option value="">未绑定</option>'];
    const project = domainProjectsData.find((item) => item.id === projectId);
    (project?.environments || []).forEach((env) => {
        options.push(`<option value="${env.id}" ${env.id === selectedId ? 'selected' : ''}>${env.name}</option>`);
    });
    selectEl.innerHTML = options.join('');
}

function bindProjectEnvironmentCascade(projectSelect, environmentSelect) {
    if (!projectSelect || !environmentSelect) return;
    projectSelect.addEventListener('change', () => {
        fillEnvironmentSelect(environmentSelect, projectSelect.value, '');
    });
}

window.refreshDomainProjectSelects = function refreshDomainProjectSelects(projects) {
    if (projects) {
        domainProjectsData.splice(0, domainProjectsData.length, ...projects);
    }
    if (!domainProjectsData.length) return;
    const addProject = document.getElementById('addDomainProject');
    const addEnvironment = document.getElementById('addDomainEnvironment');
    fillProjectSelect(addProject, addProject?.value || '');
    fillEnvironmentSelect(addEnvironment, addProject?.value || '', addEnvironment?.value || '');
};

if (projectsDataEl) {
    const addProject = document.getElementById('addDomainProject');
    const addEnvironment = document.getElementById('addDomainEnvironment');
    fillProjectSelect(addProject, '');
    fillEnvironmentSelect(addEnvironment, '', '');
    bindProjectEnvironmentCascade(addProject, addEnvironment);
}

function initCredentialAdminForms() {
    document.querySelectorAll('.save-credential-form').forEach((form) => {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const resultDiv = form.querySelector('.credential-result');
            resultDiv.classList.add('hidden');
            resultDiv.textContent = '';

            const response = await fetch('/save_credential', {
                method: 'POST',
                body: new URLSearchParams(new FormData(form)),
            });
            const data = await response.json();
            resultDiv.textContent = data.success ? data.message : data.error;
            resultDiv.classList.remove('hidden');
            resultDiv.classList.toggle('text-green-600', !!data.success);
            resultDiv.classList.toggle('text-red-600', !data.success);
            if (data.success) {
                setTimeout(() => location.reload(), 1200);
            }
        });
    });

    document.querySelectorAll('.delete-credential-btn').forEach((btn) => {
        btn.addEventListener('click', async () => {
            const provider = btn.dataset.provider;
            const credentialId = btn.dataset.credentialId;
            const confirmed = confirm(`确认删除 ${provider} 凭据 ${credentialId}？`);
            if (!confirmed) return;

            const response = await fetch('/delete_credential', {
                method: 'POST',
                body: new URLSearchParams({ provider, credential_id: credentialId }),
            });
            const data = await response.json();
            if (data.success) {
                alert(data.message);
                location.reload();
            } else {
                alert(data.error || '删除凭据失败');
            }
        });
    });

    document.querySelectorAll('.save-dns-credential-form').forEach((form) => {
        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const resultDiv = form.querySelector('.dns-credential-result');
            resultDiv.classList.add('hidden');
            const response = await fetch('/save_dns_credential', {
                method: 'POST',
                body: new URLSearchParams(new FormData(form)),
            });
            const data = await response.json();
            resultDiv.textContent = data.success ? data.message : (data.error || data.message);
            resultDiv.classList.remove('hidden');
            resultDiv.classList.toggle('text-green-600', !!data.success);
            resultDiv.classList.toggle('text-red-600', !data.success);
            if (data.success) setTimeout(() => location.reload(), 1200);
        });
    });

    document.querySelectorAll('.delete-dns-credential-btn').forEach((btn) => {
        btn.addEventListener('click', async () => {
            if (!confirm(`确认删除 DNS 凭据 ${btn.dataset.credentialId}？`)) return;
            const response = await fetch('/delete_dns_credential', {
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
}

initCredentialAdminForms();

function buildCredentialOptions(provider, selectedId) {
    const creds = providerCredentials[provider] || [];
    let html = '<option value="">请选择凭据</option>';
    creds.forEach(cred => {
        html += `<option value="${cred.id}" ${cred.id === selectedId ? 'selected' : ''}>${cred.name}</option>`;
    });
    return html;
}

const addDomainForm = document.getElementById('addDomainForm');
if (addDomainForm) {
    addDomainForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const form = e.target;
        const formData = new FormData(form);
        const resultDiv = document.getElementById('addDomainResult');
        resultDiv.classList.add('hidden');
        resultDiv.textContent = '';

        const response = await fetch('/add_domain', {
            method: 'POST',
            body: new URLSearchParams(formData)
        });
        const data = await response.json();
        if (data.success) {
            form.reset();
            resultDiv.textContent = data.message;
            resultDiv.classList.remove('hidden');
            resultDiv.classList.add('text-green-600');
            setTimeout(() => location.reload(), 1500);
        } else {
            resultDiv.textContent = data.error;
            resultDiv.classList.remove('hidden');
            resultDiv.classList.add('text-red-600');
        }
    });
}

const addProviderSelect = document.getElementById('addProviderSelect');
const addCredentialSelect = document.getElementById('addCredentialSelect');

function updateAddCredentialOptions() {
    if (!addProviderSelect || !addCredentialSelect) return;
    addCredentialSelect.innerHTML = buildCredentialOptions(addProviderSelect.value, '');
    toggleAddCpcodeField();
}

function toggleAddCpcodeField() {
    const cpcodeInput = document.getElementById('addCpcodeInput');
    if (!cpcodeInput || !addProviderSelect) return;
    const isAkamai = addProviderSelect.value === 'akamai';
    cpcodeInput.classList.toggle('hidden', !isAkamai);
    cpcodeInput.required = isAkamai;
    if (!isAkamai) cpcodeInput.value = '';
}

function toggleEditCpcodeField(form) {
    const providerSelect = form.querySelector('[name="provider"]');
    const cpcodeField = form.querySelector('.domain-cpcode-field');
    if (!providerSelect || !cpcodeField) return;
    const isAkamai = providerSelect.value === 'akamai';
    cpcodeField.classList.toggle('hidden', !isAkamai);
    const cpcodeInput = cpcodeField.querySelector('[name="cpcode"]');
    if (cpcodeInput) {
        cpcodeInput.required = isAkamai;
        if (!isAkamai) cpcodeInput.value = '';
    }
}

if (addProviderSelect && addCredentialSelect) {
    addProviderSelect.addEventListener('change', updateAddCredentialOptions);
    updateAddCredentialOptions();
}

const DOMAINS_LAYOUT_STORAGE_KEY = 'cdnmanager.domainsLayout';
const DOMAINS_TABLE_COLSPAN = 9;
let domainBlocksMaster = null;

function parseDomainTagList(raw) {
    if (!raw) return [];
    try {
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed.filter(Boolean) : [];
    } catch (err) {
        return [];
    }
}

function escapeDomainHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function compareDomainValues(a, b, order) {
    const emptyA = !a;
    const emptyB = !b;
    if (emptyA && emptyB) return 0;
    if (emptyA) return order === 'asc' ? 1 : -1;
    if (emptyB) return order === 'asc' ? -1 : 1;
    const result = a.localeCompare(b, 'zh-CN', { numeric: true, sensitivity: 'base' });
    return order === 'desc' ? -result : result;
}

function collectDomainBlocks(tbody) {
    return Array.from(tbody.querySelectorAll('.domain-item-row')).map((row) => ({
        mainRow: row,
        provider: row.dataset.sortProvider || '',
        providerLabel: row.dataset.providerLabel || row.dataset.sortProvider || '',
        projects: parseDomainTagList(row.dataset.projects),
        environments: parseDomainTagList(row.dataset.environments),
        sortValues: {
            domain_name: row.dataset.sortDomainName || '',
            domain: row.dataset.sortDomain || '',
            provider: row.dataset.sortProvider || '',
            added_at: row.dataset.sortAddedAt || '',
            refresh_status: row.dataset.sortRefreshStatus || '',
        },
    }));
}

function sortDomainBlocks(blocks, field, order) {
    return [...blocks].sort((a, b) => compareDomainValues(
        a.sortValues[field] || '',
        b.sortValues[field] || '',
        order
    ));
}

function ensureDomainBlocksMaster() {
    const tbody = document.getElementById('domainsTableBody');
    if (!tbody) return null;
    if (!domainBlocksMaster) {
        domainBlocksMaster = collectDomainBlocks(tbody);
    }
    return domainBlocksMaster;
}

function createDomainGroupHeader(label, count) {
    const tr = document.createElement('tr');
    tr.className = 'domain-group-header bg-indigo-50 border-t-2 border-indigo-100';
    tr.innerHTML = `<td colspan="${DOMAINS_TABLE_COLSPAN}" class="px-6 py-2.5 text-sm font-semibold text-indigo-800">
        <i class="fas fa-folder-open mr-2"></i>${escapeDomainHtml(label)}
        <span class="ml-2 text-xs font-normal text-indigo-600">(${count} 个域名)</span>
    </td>`;
    return tr;
}

function appendDomainBlockDisplay(fragment, block, clone) {
    const mainRow = clone ? block.mainRow.cloneNode(true) : block.mainRow;
    if (clone) mainRow.dataset.displayClone = 'true';
    fragment.appendChild(mainRow);
}

function blockMatchesFilters(block, projectFilter, environmentFilter, providerFilter) {
    if (projectFilter && !block.projects.includes(projectFilter)) return false;
    if (environmentFilter && !block.environments.includes(environmentFilter)) return false;
    if (providerFilter && block.provider !== providerFilter) return false;
    return true;
}

function getDomainGroupTags(block, groupMode) {
    if (groupMode === 'provider') {
        return block.provider ? [block.provider] : [''];
    }
    const tags = groupMode === 'project' ? block.projects : block.environments;
    return tags.length ? tags : [''];
}

function getDomainGroupLabel(key, groupMode, sampleBlock) {
    if (groupMode === 'provider') {
        return sampleBlock?.providerLabel || key || '(未分组)';
    }
    return key ? key : '(未分组)';
}

function populateDomainFilterOptions(blocks) {
    const projectEl = document.getElementById('domainsFilterProject');
    const environmentEl = document.getElementById('domainsFilterEnvironment');
    const providerEl = document.getElementById('domainsFilterProvider');
    if (!projectEl || !environmentEl || !providerEl) return;

    const projects = new Set();
    const environments = new Set();
    const providers = new Map();
    blocks.forEach((block) => {
        block.projects.forEach((tag) => projects.add(tag));
        block.environments.forEach((tag) => environments.add(tag));
        if (block.provider) {
            providers.set(block.provider, block.providerLabel || block.provider);
        }
    });

    const savedProject = projectEl.value;
    const savedEnvironment = environmentEl.value;
    const savedProvider = providerEl.value;

    projectEl.innerHTML = '<option value="">全部</option>';
    [...projects].sort((a, b) => compareDomainValues(a, b, 'asc')).forEach((tag) => {
        projectEl.insertAdjacentHTML('beforeend', `<option value="${escapeDomainHtml(tag)}">${escapeDomainHtml(tag)}</option>`);
    });

    environmentEl.innerHTML = '<option value="">全部</option>';
    [...environments].sort((a, b) => compareDomainValues(a, b, 'asc')).forEach((tag) => {
        environmentEl.insertAdjacentHTML('beforeend', `<option value="${escapeDomainHtml(tag)}">${escapeDomainHtml(tag)}</option>`);
    });

    providerEl.innerHTML = '<option value="">全部</option>';
    [...providers.entries()]
        .sort((a, b) => compareDomainValues(a[1], b[1], 'asc'))
        .forEach(([providerId, providerLabel]) => {
            providerEl.insertAdjacentHTML(
                'beforeend',
                `<option value="${escapeDomainHtml(providerId)}">${escapeDomainHtml(providerLabel)}</option>`
            );
        });

    projectEl.value = [...projectEl.options].some((option) => option.value === savedProject) ? savedProject : '';
    environmentEl.value = [...environmentEl.options].some((option) => option.value === savedEnvironment) ? savedEnvironment : '';
    providerEl.value = [...providerEl.options].some((option) => option.value === savedProvider) ? savedProvider : '';
}

function applyDomainsTableLayout() {
    const tbody = document.getElementById('domainsTableBody');
    const sortFieldEl = document.getElementById('domainsSortField');
    const sortOrderEl = document.getElementById('domainsSortOrder');
    const projectFilterEl = document.getElementById('domainsFilterProject');
    const environmentFilterEl = document.getElementById('domainsFilterEnvironment');
    const providerFilterEl = document.getElementById('domainsFilterProvider');
    const groupModeEl = document.getElementById('domainsGroupMode');
    const summaryEl = document.getElementById('domainsListSummary');
    if (!tbody || !sortFieldEl || !sortOrderEl) return;

    const blocks = ensureDomainBlocksMaster();
    if (!blocks || !blocks.length) return;

    populateDomainFilterOptions(blocks);

    const field = sortFieldEl.value;
    const order = sortOrderEl.value;
    const projectFilter = projectFilterEl ? projectFilterEl.value : '';
    const environmentFilter = environmentFilterEl ? environmentFilterEl.value : '';
    const providerFilter = providerFilterEl ? providerFilterEl.value : '';
    const groupMode = groupModeEl ? groupModeEl.value : '';

    const filtered = blocks.filter((block) => blockMatchesFilters(
        block,
        projectFilter,
        environmentFilter,
        providerFilter
    ));
    const fragment = document.createDocumentFragment();
    let groupCount = 0;
    let visibleRows = 0;
    const displayedBlocks = new Set();

    if (groupMode) {
        const grouped = new Map();
        filtered.forEach((block) => {
            getDomainGroupTags(block, groupMode).forEach((tag) => {
                const key = tag || '';
                if (!grouped.has(key)) grouped.set(key, []);
                grouped.get(key).push(block);
            });
        });

        const groupKeys = [...grouped.keys()].sort((a, b) => {
            if (groupMode === 'provider') {
                const labelA = grouped.get(a)[0]?.providerLabel || a;
                const labelB = grouped.get(b)[0]?.providerLabel || b;
                return compareDomainValues(labelA, labelB, order);
            }
            return compareDomainValues(a, b, order);
        });
        groupCount = groupKeys.length;

        groupKeys.forEach((key) => {
            const innerField = field === 'domain_name' ? 'domain' : field;
            const groupBlocks = sortDomainBlocks(grouped.get(key), innerField, order);
            fragment.appendChild(createDomainGroupHeader(
                getDomainGroupLabel(key, groupMode, groupBlocks[0]),
                groupBlocks.length
            ));
            groupBlocks.forEach((block) => {
                const clone = displayedBlocks.has(block);
                appendDomainBlockDisplay(fragment, block, clone);
                displayedBlocks.add(block);
                visibleRows += 1;
            });
        });
    } else {
        const sorted = sortDomainBlocks(filtered, field, order);
        sorted.forEach((block) => {
            appendDomainBlockDisplay(fragment, block, false);
            visibleRows += 1;
        });
    }

    tbody.replaceChildren(fragment);

    if (summaryEl) {
        const filterActive = projectFilter || environmentFilter || providerFilter;
        let summary = `共 ${blocks.length} 个域名`;
        if (filterActive) summary += `，筛选后 ${filtered.length} 个`;
        if (groupMode && groupCount) summary += `，${groupCount} 个分组`;
        if (groupMode && visibleRows > filtered.length) summary += `，显示 ${visibleRows} 条`;
        summaryEl.textContent = summary;
    }

    localStorage.setItem(DOMAINS_LAYOUT_STORAGE_KEY, JSON.stringify({
        field,
        order,
        projectFilter,
        environmentFilter,
        providerFilter,
        groupMode,
    }));
}

function openDomainEditModal(row) {
    const modal = document.getElementById('domainEditModal');
    const form = document.getElementById('domainEditModalForm');
    if (!modal || !form || !row) return;

    document.getElementById('domainEditDomain').value = row.dataset.domain || '';
    document.getElementById('domainEditModalTitle').textContent = row.dataset.domain || '';
    const nameInput = document.getElementById('domainEditName');
    if (nameInput) nameInput.value = row.dataset.domainName || '';
    const projectSelect = document.getElementById('domainEditProject');
    const environmentSelect = document.getElementById('domainEditEnvironment');
    const projectId = row.dataset.projectId || '';
    const environmentId = row.dataset.environmentId || '';
    fillProjectSelect(projectSelect, projectId);
    fillEnvironmentSelect(environmentSelect, projectId, environmentId);
    document.getElementById('domainEditProvider').value = row.dataset.sortProvider || '';
    document.getElementById('domainEditCredential').innerHTML = buildCredentialOptions(
        row.dataset.sortProvider || '',
        row.dataset.credentialId || '',
    );
    document.getElementById('domainEditCpcode').value = row.dataset.cpcode || '';
    const allowedInput = document.getElementById('domainEditAllowedUsers');
    if (allowedInput) allowedInput.value = row.dataset.allowedUsers || '';
    toggleDomainEditCpcode();
    document.getElementById('domainEditResult').classList.add('hidden');
    modal.classList.remove('hidden');
}

function closeDomainEditModal() {
    document.getElementById('domainEditModal')?.classList.add('hidden');
}

function toggleDomainEditCpcode() {
    const provider = document.getElementById('domainEditProvider')?.value;
    const wrap = document.getElementById('domainEditCpcodeWrap');
    const input = document.getElementById('domainEditCpcode');
    if (!wrap || !input) return;
    const isAkamai = provider === 'akamai';
    wrap.classList.toggle('hidden', !isAkamai);
    input.required = isAkamai;
    if (!isAkamai) input.value = '';
}

function initDomainEditModal() {
    const modal = document.getElementById('domainEditModal');
    const form = document.getElementById('domainEditModalForm');
    if (!modal || !form || form.dataset.bound) return;
    form.dataset.bound = '1';

    modal.querySelectorAll('[data-close-domain-modal]').forEach((el) => {
        el.addEventListener('click', closeDomainEditModal);
    });

    document.getElementById('domainEditProvider')?.addEventListener('change', () => {
        const provider = document.getElementById('domainEditProvider').value;
        document.getElementById('domainEditCredential').innerHTML = buildCredentialOptions(provider, '');
        toggleDomainEditCpcode();
    });
    bindProjectEnvironmentCascade(
        document.getElementById('domainEditProject'),
        document.getElementById('domainEditEnvironment'),
    );

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const resultDiv = document.getElementById('domainEditResult');
        resultDiv.classList.add('hidden');
        const provider = document.getElementById('domainEditProvider').value;
        const params = {
            domain: document.getElementById('domainEditDomain').value,
            domain_name: document.getElementById('domainEditName')?.value || '',
            provider,
            credential_id: document.getElementById('domainEditCredential').value,
            project_id: document.getElementById('domainEditProject')?.value || '',
            environment_id: document.getElementById('domainEditEnvironment')?.value || '',
        };
        const allowedInput = document.getElementById('domainEditAllowedUsers');
        if (allowedInput) params.allowed_users = allowedInput.value;
        if (provider === 'akamai') params.cpcode = document.getElementById('domainEditCpcode').value;

        const response = await fetch('/edit_domain', {
            method: 'POST',
            body: new URLSearchParams(params),
        });
        const data = await response.json();
        resultDiv.textContent = data.success ? data.message : data.error;
        resultDiv.classList.remove('hidden');
        resultDiv.classList.toggle('text-green-600', !!data.success);
        resultDiv.classList.toggle('text-red-600', !data.success);
        if (data.success) {
            domainBlocksMaster = null;
            setTimeout(() => location.reload(), 1000);
        }
    });
}

function initDomainsTableActions() {
    const tbody = document.getElementById('domainsTableBody');
    if (!tbody || tbody.dataset.actionsBound) return;
    tbody.dataset.actionsBound = '1';
    initDomainEditModal();

    tbody.addEventListener('click', async (event) => {
        const editBtn = event.target.closest('.edit-domain-btn');
        if (editBtn) {
            openDomainEditModal(editBtn.closest('tr'));
            return;
        }

        const refreshBtn = event.target.closest('.refresh-btn');
        if (refreshBtn) {
            const domain = refreshBtn.dataset.domain;
            const row = refreshBtn.closest('tr');
            const confirmed = confirm(`确认刷新域名 ${domain} 的CDN缓存？`);
            if (!confirmed) return;

            refreshBtn.disabled = true;
            const originalText = refreshBtn.textContent;
            refreshBtn.textContent = '刷新中...';
            updateDomainRowsStatus(domain, '正在刷新', row?.querySelector('.refresh-time-cell')?.textContent || '-');

            const response = await fetch('/refresh_domain', {
                method: 'POST',
                body: new URLSearchParams({ domain }),
            });
            const data = await response.json();
            if (!data.success) {
                refreshBtn.disabled = false;
                refreshBtn.textContent = originalText;
                alert('刷新失败: ' + (data.error || data.message || JSON.stringify(data)));
                updateDomainRowsStatus(domain, data.error ? '刷新失败' : '未知状态', row?.querySelector('.refresh-time-cell')?.textContent || '-');
                return;
            }

            const finalStatus = await pollDomainRefreshStatus(domain, row, refreshBtn);
            if (finalStatus && finalStatus.success) {
                alert(`刷新完成：${finalStatus.refresh_status || '未知'}`);
            }
            return;
        }

        const deleteBtn = event.target.closest('.delete-btn');
        if (deleteBtn) {
            const domain = deleteBtn.dataset.domain;
            if (!confirm(`确认删除域名 ${domain}？此操作不可逆。`)) return;

            const response = await fetch('/delete_domain', {
                method: 'POST',
                body: new URLSearchParams({ domain }),
            });
            const data = await response.json();
            if (data.success) {
                alert('删除成功');
                location.reload();
            } else {
                alert('删除失败: ' + data.error);
            }
        }
    });
}

function initDomainsTableLayout() {
    const sortFieldEl = document.getElementById('domainsSortField');
    const sortOrderEl = document.getElementById('domainsSortOrder');
    const projectFilterEl = document.getElementById('domainsFilterProject');
    const environmentFilterEl = document.getElementById('domainsFilterEnvironment');
    const providerFilterEl = document.getElementById('domainsFilterProvider');
    const groupModeEl = document.getElementById('domainsGroupMode');
    if (!sortFieldEl || !sortOrderEl) return;

    try {
        const saved = JSON.parse(localStorage.getItem(DOMAINS_LAYOUT_STORAGE_KEY) || '{}');
        if (saved.field) sortFieldEl.value = saved.field;
        if (saved.order) sortOrderEl.value = saved.order;
        if (projectFilterEl && saved.projectFilter) projectFilterEl.value = saved.projectFilter;
        if (environmentFilterEl && saved.environmentFilter) environmentFilterEl.value = saved.environmentFilter;
        if (providerFilterEl && saved.providerFilter) providerFilterEl.value = saved.providerFilter;
        if (groupModeEl && saved.groupMode) groupModeEl.value = saved.groupMode;
    } catch (err) {
        // ignore invalid saved layout
    }

    const rerender = () => applyDomainsTableLayout();
    sortFieldEl.addEventListener('change', rerender);
    sortOrderEl.addEventListener('change', rerender);
    if (projectFilterEl) projectFilterEl.addEventListener('change', rerender);
    if (environmentFilterEl) environmentFilterEl.addEventListener('change', rerender);
    if (providerFilterEl) providerFilterEl.addEventListener('change', rerender);
    if (groupModeEl) groupModeEl.addEventListener('change', rerender);
    applyDomainsTableLayout();
}

initDomainsTableLayout();
initDomainsTableActions();

const userForm = document.getElementById('userForm');
if (userForm) {
    document.querySelectorAll('.edit-user-btn').forEach((btn) => {
        btn.addEventListener('click', () => {
            const row = btn.closest('.user-row');
            if (!row) return;
            document.getElementById('userFormUsername').value = row.dataset.username || '';
            document.getElementById('userFormRole').value = row.dataset.role || 'user';
            const projectSelect = document.getElementById('userFormProjects');
            const selected = (row.dataset.projectIds || '').split(',').filter(Boolean);
            if (projectSelect) {
                Array.from(projectSelect.options).forEach((option) => {
                    option.selected = selected.includes(option.value);
                });
            }
            document.getElementById('userFormUsername').readOnly = true;
        });
    });

    userForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const params = new URLSearchParams(new FormData(userForm));
        const projectSelect = document.getElementById('userFormProjects');
        if (projectSelect) {
            params.delete('project_ids');
            params.set(
                'project_ids',
                Array.from(projectSelect.selectedOptions).map((option) => option.value).join(','),
            );
        }
        const resultDiv = document.getElementById('userResult');
        resultDiv.classList.add('hidden');
        resultDiv.textContent = '';

        const response = await fetch('/save_user', {
            method: 'POST',
            body: params,
        });
        const data = await response.json();
        if (data.success && data.generated_password) {
            resultDiv.textContent = `${data.message}，初始密码：${data.generated_password}`;
        } else {
            resultDiv.textContent = data.success ? data.message : data.error;
        }
        resultDiv.classList.remove('hidden');
        resultDiv.classList.toggle('text-green-600', !!data.success);
        resultDiv.classList.toggle('text-red-600', !data.success);
        if (data.success) {
            setTimeout(() => location.reload(), data.generated_password ? 5000 : 1200);
        }
    });
}

const changePasswordBtn = document.getElementById('changePasswordBtn');
const changePasswordModal = document.getElementById('changePasswordModal');
const changePasswordForm = document.getElementById('changePasswordForm');

function closeChangePasswordModal() {
    changePasswordModal?.classList.add('hidden');
    changePasswordForm?.reset();
    document.getElementById('changePasswordResult')?.classList.add('hidden');
}

changePasswordBtn?.addEventListener('click', () => {
    changePasswordModal?.classList.remove('hidden');
});

changePasswordModal?.querySelectorAll('[data-close-password-modal]').forEach((el) => {
    el.addEventListener('click', closeChangePasswordModal);
});

changePasswordForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const resultDiv = document.getElementById('changePasswordResult');
    const response = await fetch('/change_password', {
        method: 'POST',
        body: new URLSearchParams(new FormData(changePasswordForm)),
    });
    const data = await response.json();
    resultDiv.textContent = data.success ? data.message : data.error;
    resultDiv.classList.remove('hidden');
    resultDiv.classList.toggle('text-green-600', !!data.success);
    resultDiv.classList.toggle('text-red-600', !data.success);
    if (data.success) {
        setTimeout(closeChangePasswordModal, 1200);
    }
});

document.querySelectorAll('.delete-user-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
        const username = btn.dataset.username;
        const confirmed = confirm(`确认删除用户 ${username}？`);
        if (!confirmed) return;

        const response = await fetch('/delete_user', {
            method: 'POST',
            body: new URLSearchParams({ username })
        });
        const data = await response.json();
        if (data.success) {
            alert(data.message);
            location.reload();
        } else {
            alert(data.error || '删除用户失败');
        }
    });
});

async function fetchDomainStatus(domain) {
    const response = await fetch(`/api/task_status?domain=${encodeURIComponent(domain)}`);
    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || data.message || `请求失败: ${response.status}`);
    }
    return response.json();
}

function updateDomainRowsStatus(domain, statusText, updatedAt) {
    document.querySelectorAll('#domainsTableBody tr.domain-item-row').forEach((row) => {
        if (row.dataset.domain !== domain) return;
        const statusCell = row.querySelector('.refresh-status-cell');
        const timeCell = row.querySelector('.refresh-time-cell');
        if (statusCell) statusCell.textContent = statusText;
        if (timeCell) timeCell.textContent = updatedAt || timeCell.textContent || '-';
        if (statusCell) row.dataset.sortRefreshStatus = (statusText || '').toLowerCase();
    });
}

async function pollDomainRefreshStatus(domain, row, btn) {
    const POLL_INTERVAL = 30000;
    const originalText = btn ? btn.textContent : '刷新';
    if (btn) {
        btn.disabled = true;
        btn.textContent = '刷新中...';
    }
    while (true) {
        try {
            const data = await fetchDomainStatus(domain);
            if (data.success) {
                updateDomainRowsStatus(domain, data.refresh_status || '-', data.last_refreshed_at || '-');
                if (data.refresh_status !== '正在刷新') {
                    if (btn) {
                        btn.disabled = false;
                        btn.textContent = originalText;
                    }
                    return data;
                }
            } else {
                throw new Error(data.error || data.message || '状态查询失败');
            }
        } catch (err) {
            if (btn) {
                btn.disabled = false;
                btn.textContent = originalText;
            }
            alert('状态查询失败: ' + err.message);
            return null;
        }
        await new Promise(resolve => setTimeout(resolve, POLL_INTERVAL));
    }
}

function startExistingRefreshPolling() {
    document.querySelectorAll('tr').forEach(row => {
        const statusCell = row.querySelector('.refresh-status-cell');
        const btn = row.querySelector('.refresh-btn');
        if (!statusCell || !btn) return;
        const domain = btn.dataset.domain;
        if (statusCell.textContent.trim() === '正在刷新') {
            pollDomainRefreshStatus(domain, row, btn);
        }
    });
}

async function fetchUrlStatus(url, idx) {
    const q = (typeof idx !== 'undefined' && idx !== null) ? `url_idx=${encodeURIComponent(idx)}` : `url=${encodeURIComponent(url)}`;
    const response = await fetch(`/api/task_status?${q}`);
    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || data.message || `请求失败: ${response.status}`);
    }
    return response.json();
}

function updateUrlRowStatus(row, statusText, updatedAt) {
    const statusCell = row.querySelector('.url-refresh-status-cell');
    const timeCell = row.querySelector('.url-time-cell');
    if (statusCell) statusCell.textContent = statusText;
    if (timeCell) timeCell.textContent = updatedAt || timeCell.textContent || '-';
}

async function pollUrlRefreshStatus(url, row, idx) {
    const POLL_INTERVAL = 30000;
    while (true) {
        try {
            const data = await fetchUrlStatus(url, idx);
            if (data.success) {
                updateUrlRowStatus(row, data.refresh_status || '-', data.completed_at || data.submitted_at || '-');
                if (data.refresh_status !== '正在刷新') {
                    return data;
                }
            } else {
                throw new Error(data.error || data.message || '状态查询失败');
            }
        } catch (err) {
            console.error('URL 状态查询失败:', err);
            return null;
        }
        await new Promise(resolve => setTimeout(resolve, POLL_INTERVAL));
    }
}

function startExistingUrlRefreshPolling() {
    document.querySelectorAll('tr[data-url]').forEach(row => {
        const statusCell = row.querySelector('.url-refresh-status-cell');
        if (!statusCell) return;
        const url = row.dataset.url;
        const idx = row.dataset.urlIdx ? parseInt(row.dataset.urlIdx, 10) : null;
        if (url && statusCell.textContent.trim() === '正在刷新') {
            pollUrlRefreshStatus(url, row, idx);
        }
    });
}

function renderRefreshRecords(records) {
    const tbody = document.getElementById('refreshRecordsBody');
    const empty = document.getElementById('refreshRecordsEmpty');
    const summary = document.getElementById('refreshRecordsSummary');
    if (!tbody) return;
    tbody.innerHTML = '';
    if (!records.length) {
        empty?.classList.remove('hidden');
        if (summary) summary.textContent = '暂无记录';
        return;
    }
    empty?.classList.add('hidden');
    records.forEach((item) => {
        const tr = document.createElement('tr');
        tr.className = 'hover:bg-gray-50 transition';
        tr.dataset.url = item.url || '';
        tr.dataset.urlIdx = item.id;
        tr.dataset.domain = item.domain || '';
        tr.innerHTML = `
            <td class="px-4 py-3 whitespace-nowrap text-gray-700">${item.domain || '-'}</td>
            <td class="px-4 py-3 max-w-md truncate" title="${item.url || ''}">${item.url || '-'}</td>
            <td class="px-4 py-3 whitespace-nowrap text-gray-500">${item.provider_label || item.provider || '-'}</td>
            <td class="px-4 py-3 whitespace-nowrap url-refresh-status-cell">${item.refresh_status || '-'}</td>
            <td class="px-4 py-3 whitespace-nowrap url-time-cell">${item.completed_at || item.submitted_at || '-'}</td>`;
        tbody.appendChild(tr);
    });
    if (summary) summary.textContent = `共 ${records.length} 条记录`;
    startExistingUrlRefreshPolling();
}

function fillRefreshRecordsEnvironmentOptions(projectId, selectedId) {
    const environmentFilter = document.getElementById('refreshRecordsEnvironmentFilter');
    if (!environmentFilter) return;
    const options = ['<option value="">全部</option>'];
    const project = domainProjectsData.find((item) => item.id === projectId);
    (project?.environments || []).forEach((env) => {
        options.push(`<option value="${env.id}" ${env.id === selectedId ? 'selected' : ''}>${env.name}</option>`);
    });
    environmentFilter.innerHTML = options.join('');
}

async function loadRefreshRecords() {
    const domainFilter = document.getElementById('refreshRecordsDomainFilter');
    const projectFilter = document.getElementById('refreshRecordsProjectFilter');
    const environmentFilter = document.getElementById('refreshRecordsEnvironmentFilter');
    const params = new URLSearchParams();
    if (domainFilter?.value) params.set('domain', domainFilter.value);
    if (projectFilter?.value) params.set('project_id', projectFilter.value);
    if (environmentFilter?.value) params.set('environment_id', environmentFilter.value);
    const query = params.toString();
    const response = await fetch(`/api/refresh_records${query ? `?${query}` : ''}`);
    const data = await response.json();
    if (!data.success) {
        alert(data.error || '加载刷新记录失败');
        return;
    }
    renderRefreshRecords(data.records || []);
}

const refreshRecordsFilter = document.getElementById('refreshRecordsDomainFilter');
const refreshRecordsProjectFilter = document.getElementById('refreshRecordsProjectFilter');
const refreshRecordsEnvironmentFilter = document.getElementById('refreshRecordsEnvironmentFilter');
const refreshRecordsReloadBtn = document.getElementById('refreshRecordsReloadBtn');
refreshRecordsFilter?.addEventListener('change', () => loadRefreshRecords());
refreshRecordsProjectFilter?.addEventListener('change', () => {
    fillRefreshRecordsEnvironmentOptions(refreshRecordsProjectFilter.value, '');
    loadRefreshRecords();
});
refreshRecordsEnvironmentFilter?.addEventListener('change', () => loadRefreshRecords());
refreshRecordsReloadBtn?.addEventListener('click', () => loadRefreshRecords());
if (refreshRecordsProjectFilter && domainProjectsData.length) {
    fillRefreshRecordsEnvironmentOptions('', '');
}

startExistingRefreshPolling();
startExistingUrlRefreshPolling();

const dnsCredentialsEl = document.getElementById('dns-credentials');
const dnsCredentials = dnsCredentialsEl ? JSON.parse(dnsCredentialsEl.textContent) : {};

function buildDnsCredentialOptions(provider, selectedId) {
    const creds = dnsCredentials[provider] || [];
    let html = '<option value="">请选择 DNS 凭据</option>';
    creds.forEach(cred => {
        html += `<option value="${cred.id}" ${cred.id === selectedId ? 'selected' : ''}>${cred.name}</option>`;
    });
    return html;
}

const addDnsProviderSelect = document.getElementById('addDnsProviderSelect');
const addDnsCredentialSelect = document.getElementById('addDnsCredentialSelect');

function updateAddDnsCredentialOptions() {
    if (!addDnsProviderSelect || !addDnsCredentialSelect) return;
    addDnsCredentialSelect.innerHTML = buildDnsCredentialOptions(addDnsProviderSelect.value, '');
}

if (addDnsProviderSelect && addDnsCredentialSelect) {
    addDnsProviderSelect.addEventListener('change', updateAddDnsCredentialOptions);
    updateAddDnsCredentialOptions();
}

const addRootDomainForm = document.getElementById('addRootDomainForm');
if (addRootDomainForm) {
    addRootDomainForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const resultDiv = document.getElementById('addRootDomainResult');
        resultDiv.classList.add('hidden');
        const response = await fetch('/add_root_domain', {
            method: 'POST',
            body: new URLSearchParams(new FormData(addRootDomainForm))
        });
        const data = await response.json();
        resultDiv.textContent = data.success ? data.message : (data.error || data.message);
        resultDiv.classList.remove('hidden');
        resultDiv.classList.toggle('text-green-600', !!data.success);
        resultDiv.classList.toggle('text-red-600', !data.success);
        if (data.success) setTimeout(() => location.reload(), 1200);
    });
}

document.querySelectorAll('.edit-root-domain-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const editRow = document.querySelector(`.root-edit-row[data-domain="${btn.dataset.domain}"]`);
        if (editRow) editRow.classList.toggle('hidden');
    });
});

document.querySelectorAll('.cancel-root-edit-btn').forEach(btn => {
    btn.addEventListener('click', () => btn.closest('.root-edit-row')?.classList.add('hidden'));
});

document.querySelectorAll('.root-domain-edit-form').forEach(form => {
    const providerSelect = form.querySelector('.root-dns-provider-select');
    const credentialSelect = form.querySelector('.root-dns-credential-select');
    providerSelect?.addEventListener('change', () => {
        credentialSelect.innerHTML = buildDnsCredentialOptions(providerSelect.value, '');
    });

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const params = new URLSearchParams(new FormData(form));
        params.set('domain', form.dataset.domain);
        const response = await fetch('/edit_root_domain', { method: 'POST', body: params });
        const data = await response.json();
        if (data.success) location.reload();
        else alert(data.error || data.message || '保存失败');
    });
});

document.querySelectorAll('.delete-root-domain-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
        if (!confirm(`确认删除主域名 ${btn.dataset.domain}？`)) return;
        const response = await fetch('/delete_root_domain', {
            method: 'POST',
            body: new URLSearchParams({ domain: btn.dataset.domain })
        });
        const data = await response.json();
        if (data.success) location.reload();
        else alert(data.error || '删除失败');
    });
});

function renderDnsRecords(container, records) {
    if (!records.length) {
        container.innerHTML = '<p class="text-gray-500">暂无解析记录</p>';
        return;
    }
    let html = '<div class="overflow-x-auto"><table class="min-w-full text-sm"><thead><tr>';
    html += '<th class="px-2 py-1 text-left">主机记录</th><th class="px-2 py-1 text-left">类型</th><th class="px-2 py-1 text-left">记录值</th><th class="px-2 py-1 text-left">TTL</th><th class="px-2 py-1 text-left">操作</th></tr></thead><tbody>';
    records.forEach(record => {
        html += `<tr class="border-t"><td class="px-2 py-2">${record.sub_domain || '@'}</td>`;
        html += `<td class="px-2 py-2">${record.record_type}</td>`;
        html += `<td class="px-2 py-2 break-all">${record.value}</td>`;
        html += `<td class="px-2 py-2">${record.ttl ?? '-'}</td>`;
        html += `<td class="px-2 py-2 whitespace-nowrap">`;
        html += `<button type="button" class="fill-dns-record-btn text-indigo-600 hover:underline mr-2" data-record='${JSON.stringify(record).replace(/'/g, '&#39;')}'>编辑</button>`;
        html += `<button type="button" class="delete-dns-record-btn text-red-600 hover:underline" data-record-id="${record.record_id}">删除</button>`;
        html += `</td></tr>`;
    });
    html += '</tbody></table></div>';
    container.innerHTML = html;

    container.querySelectorAll('.fill-dns-record-btn').forEach(button => {
        button.addEventListener('click', () => {
            const record = JSON.parse(button.dataset.record);
            const panel = container.closest('.dns-records-panel');
            const form = panel.querySelector('.dns-record-form');
            form.querySelector('[name="record_id"]').value = record.record_id;
            form.querySelector('[name="sub_domain"]').value = record.sub_domain || '';
            form.querySelector('[name="record_type"]').value = record.record_type || 'A';
            form.querySelector('[name="value"]').value = record.value || '';
            form.querySelector('[name="ttl"]').value = record.ttl ?? '';
            form.querySelector('[name="line"]').value = record.line && record.line !== 'default' ? record.line : '';
        });
    });

    container.querySelectorAll('.delete-dns-record-btn').forEach(button => {
        button.addEventListener('click', async () => {
            const panel = container.closest('.dns-records-panel');
            const rootDomain = panel.dataset.domain;
            if (!confirm('确认删除该解析记录？')) return;
            const response = await fetch('/internal/dns/record/delete', {
                method: 'POST',
                body: new URLSearchParams({ root_domain: rootDomain, record_id: button.dataset.recordId })
            });
            const data = await response.json();
            if (data.success) panel.querySelector('.load-dns-records-btn').click();
            else alert(data.message || data.error || '删除失败');
        });
    });
}

document.querySelectorAll('.view-dns-records-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const row = document.querySelector(`.dns-records-row[data-domain="${btn.dataset.domain}"]`);
        if (row) row.classList.toggle('hidden');
    });
});

document.querySelectorAll('.dns-records-panel').forEach(panel => {
    const loadBtn = panel.querySelector('.load-dns-records-btn');
    const resultDiv = panel.querySelector('.dns-records-result');
    const form = panel.querySelector('.dns-record-form');
    const formResult = panel.querySelector('.dns-record-form-result');

    loadBtn?.addEventListener('click', async () => {
        resultDiv.textContent = '加载中...';
        const params = new URLSearchParams({ root_domain: panel.dataset.domain });
        const sub = panel.querySelector('.dns-filter-sub')?.value.trim();
        const type = panel.querySelector('.dns-filter-type')?.value.trim();
        if (sub) params.set('sub_domain', sub);
        if (type) params.set('record_type', type);
        const response = await fetch(`/internal/dns/records?${params.toString()}`);
        const data = await response.json();
        if (!data.success) {
            resultDiv.textContent = data.message || data.error || '查询失败';
            return;
        }
        renderDnsRecords(resultDiv, data.records || []);
    });

    panel.querySelector('.reset-dns-record-form-btn')?.addEventListener('click', () => {
        form.reset();
        form.querySelector('[name="record_id"]').value = '';
        formResult.classList.add('hidden');
    });

    form?.addEventListener('submit', async (e) => {
        e.preventDefault();
        const formData = new FormData(form);
        const recordId = formData.get('record_id');
        const params = new URLSearchParams(formData);
        params.set('root_domain', panel.dataset.domain);
        const endpoint = recordId ? '/internal/dns/record/update' : '/internal/dns/record/create';
        const response = await fetch(endpoint, { method: 'POST', body: params });
        const data = await response.json();
        formResult.textContent = data.success ? data.message : (data.message || data.error || '保存失败');
        formResult.classList.remove('hidden');
        formResult.classList.toggle('text-green-600', !!data.success);
        formResult.classList.toggle('text-red-600', !data.success);
        if (data.success) {
            loadBtn.click();
            if (!recordId) {
                form.reset();
                form.querySelector('[name="record_id"]').value = '';
            }
        }
    });
});
