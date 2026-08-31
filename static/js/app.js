const providerCredentialsEl = document.getElementById('provider-credentials');
const providerCredentials = providerCredentialsEl
    ? JSON.parse(providerCredentialsEl.textContent)
    : {};

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

document.querySelectorAll('.save-credential-form').forEach(form => {
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const resultDiv = form.querySelector('.credential-result');
        resultDiv.classList.add('hidden');
        resultDiv.textContent = '';

        const response = await fetch('/save_credential', {
            method: 'POST',
            body: new URLSearchParams(new FormData(form))
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

document.querySelectorAll('.delete-credential-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
        const provider = btn.dataset.provider;
        const credentialId = btn.dataset.credentialId;
        const confirmed = confirm(`确认删除 ${provider} 凭据 ${credentialId}？`);
        if (!confirmed) return;

        const response = await fetch('/delete_credential', {
            method: 'POST',
            body: new URLSearchParams({ provider, credential_id: credentialId })
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

const userForm = document.getElementById('userForm');
if (userForm) {
    userForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const formData = new FormData(userForm);
        const resultDiv = document.getElementById('userResult');
        resultDiv.classList.add('hidden');
        resultDiv.textContent = '';

        const response = await fetch('/save_user', {
            method: 'POST',
            body: new URLSearchParams(formData)
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
}

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

document.querySelectorAll('.edit-domain-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const row = btn.closest('tr');
        const editRow = row.nextElementSibling;
        if (editRow && editRow.classList.contains('edit-row')) {
            editRow.classList.toggle('hidden');
        }
    });
});

document.querySelectorAll('.cancel-edit-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const editRow = btn.closest('.edit-row');
        if (editRow) {
            editRow.classList.add('hidden');
        }
    });
});

document.querySelectorAll('.domain-edit-form').forEach(form => {
    const providerSelect = form.querySelector('[name="provider"]');
    const credentialSelect = form.querySelector('[name="credential_id"]');

    function updateDomainCredentialOptions(selectedId) {
        credentialSelect.innerHTML = buildCredentialOptions(providerSelect.value, selectedId);
    }

    providerSelect.addEventListener('change', () => {
        updateDomainCredentialOptions('');
        toggleEditCpcodeField(form);
    });
    updateDomainCredentialOptions(credentialSelect.value);
    toggleEditCpcodeField(form);

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const domain = form.dataset.domain;
        const provider = providerSelect.value;
        const credentialId = credentialSelect.value;
        const resultDiv = form.querySelector('.edit-result');
        resultDiv.classList.add('hidden');
        resultDiv.textContent = '';

        const domainNameInput = form.querySelector('[name="domain_name"]');
        const allowedUsersInput = form.querySelector('[name="allowed_users"]');
        const params = {
            domain,
            domain_name: domainNameInput ? domainNameInput.value : '',
            provider,
            credential_id: credentialId,
        };
        if (allowedUsersInput) {
            params.allowed_users = allowedUsersInput.value;
        }
        const cpcodeInput = form.querySelector('[name="cpcode"]');
        if (cpcodeInput && provider === 'akamai') {
            params.cpcode = cpcodeInput.value;
        }

        const response = await fetch('/edit_domain', {
            method: 'POST',
            body: new URLSearchParams(params)
        });
        const data = await response.json();
        if (data.success) {
            resultDiv.textContent = data.message;
            resultDiv.classList.remove('hidden');
            resultDiv.classList.remove('text-red-600');
            resultDiv.classList.add('text-green-600');
            setTimeout(() => location.reload(), 1200);
        } else {
            resultDiv.textContent = data.error;
            resultDiv.classList.remove('hidden');
            resultDiv.classList.remove('text-green-600');
            resultDiv.classList.add('text-red-600');
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

function updateDomainRowStatus(row, statusText, updatedAt) {
    const statusCell = row.querySelector('.refresh-status-cell');
    const timeCell = row.querySelector('.refresh-time-cell');
    if (statusCell) statusCell.textContent = statusText;
    if (timeCell) timeCell.textContent = updatedAt || timeCell.textContent || '-';
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
                updateDomainRowStatus(row, data.refresh_status || '-', data.last_refreshed_at || '-');
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

startExistingRefreshPolling();
startExistingUrlRefreshPolling();

document.querySelectorAll('.refresh-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
        const domain = btn.dataset.domain;
        const row = btn.closest('tr');
        const confirmed = confirm(`确认刷新域名 ${domain} 的CDN缓存？`);
        if (!confirmed) return;

        btn.disabled = true;
        const originalText = btn.textContent;
        btn.textContent = '刷新中...';
        if (row) {
            updateDomainRowStatus(row, '正在刷新', row.querySelector('.refresh-time-cell')?.textContent || '-');
        }

        const response = await fetch('/refresh_domain', {
            method: 'POST',
            body: new URLSearchParams({ domain })
        });
        const data = await response.json();
        if (!data.success) {
            btn.disabled = false;
            btn.textContent = originalText;
            const errText = data.error || data.message || JSON.stringify(data);
            alert('刷新失败: ' + errText);
            if (row) {
                updateDomainRowStatus(row, data.error ? '刷新失败' : '未知状态', row.querySelector('.refresh-time-cell')?.textContent || '-');
            }
            return;
        }

        const finalStatus = await pollDomainRefreshStatus(domain, row, btn);
        if (finalStatus && finalStatus.success) {
            alert(`刷新完成：${finalStatus.refresh_status || '未知'}`);
        }
    });
});

document.querySelectorAll('.delete-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
        const domain = btn.dataset.domain;
        const result = confirm(`确认删除域名 ${domain}？此操作不可逆。`);
        if (!result) return;

        const response = await fetch('/delete_domain', {
            method: 'POST',
            body: new URLSearchParams({ domain })
        });
        const data = await response.json();
        if (data.success) {
            alert('删除成功');
            location.reload();
        } else {
            alert('删除失败: ' + data.error);
        }
    });
});

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

document.querySelectorAll('.save-dns-credential-form').forEach(form => {
    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const resultDiv = form.querySelector('.dns-credential-result');
        resultDiv.classList.add('hidden');
        const response = await fetch('/save_dns_credential', {
            method: 'POST',
            body: new URLSearchParams(new FormData(form))
        });
        const data = await response.json();
        resultDiv.textContent = data.success ? data.message : (data.error || data.message);
        resultDiv.classList.remove('hidden');
        resultDiv.classList.toggle('text-green-600', !!data.success);
        resultDiv.classList.toggle('text-red-600', !data.success);
        if (data.success) setTimeout(() => location.reload(), 1200);
    });
});

document.querySelectorAll('.delete-dns-credential-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
        if (!confirm(`确认删除 DNS 凭据 ${btn.dataset.credentialId}？`)) return;
        const response = await fetch('/delete_dns_credential', {
            method: 'POST',
            body: new URLSearchParams({
                provider: btn.dataset.provider,
                credential_id: btn.dataset.credentialId
            })
        });
        const data = await response.json();
        if (data.success) location.reload();
        else alert(data.error || '删除失败');
    });
});

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
