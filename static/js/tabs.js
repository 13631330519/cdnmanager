(function () {
    const SIDEBAR_KEY = 'cdnmanager.sidebarCollapsed';
    const GROUP_KEY = 'cdnmanager.sidebarGroups';

    function getValidTabs() {
        return Array.from(document.querySelectorAll('.tab-btn')).map((btn) => btn.dataset.tab);
    }

    function setActiveTab(tabId) {
        const validTabs = getValidTabs();
        const target = validTabs.includes(tabId) ? tabId : 'domains';

        document.querySelectorAll('.tab-btn').forEach((btn) => {
            btn.classList.toggle('active', btn.dataset.tab === target);
            btn.setAttribute('aria-selected', btn.dataset.tab === target ? 'true' : 'false');
        });

        document.querySelectorAll('.tab-panel').forEach((panel) => {
            panel.classList.toggle('hidden', panel.id !== `tab-${target}`);
        });

        history.replaceState(null, '', `#${target}`);
    }

    function loadGroupState() {
        try {
            return JSON.parse(localStorage.getItem(GROUP_KEY) || '{}');
        } catch {
            return {};
        }
    }

    function saveGroupState(state) {
        localStorage.setItem(GROUP_KEY, JSON.stringify(state));
    }

    function initSidebarGroups() {
        const state = loadGroupState();
        document.querySelectorAll('.sidebar-group').forEach((group) => {
            const name = group.dataset.group;
            const items = group.querySelector('.sidebar-group-items');
            const chevron = group.querySelector('.sidebar-group-chevron');
            const collapsed = state[name] === false;
            if (items) items.classList.toggle('hidden', collapsed);
            if (chevron) chevron.classList.toggle('fa-chevron-down', !collapsed);
            if (chevron) chevron.classList.toggle('fa-chevron-right', collapsed);

            group.querySelector('.sidebar-group-title')?.addEventListener('click', () => {
                const nowHidden = items?.classList.toggle('hidden');
                const isCollapsed = !!nowHidden;
                state[name] = !isCollapsed;
                saveGroupState(state);
                if (chevron) {
                    chevron.classList.toggle('fa-chevron-down', !isCollapsed);
                    chevron.classList.toggle('fa-chevron-right', isCollapsed);
                }
            });
        });
    }

    function initSidebarToggle() {
        const sidebar = document.getElementById('sidebar');
        const toggle = document.getElementById('sidebarToggle');
        if (!sidebar || !toggle) return;

        const collapsed = localStorage.getItem(SIDEBAR_KEY) === '1';
        sidebar.classList.toggle('collapsed', collapsed);
        toggle.innerHTML = collapsed
            ? '<i class="fas fa-angles-right"></i>'
            : '<i class="fas fa-angles-left"></i>';

        toggle.addEventListener('click', () => {
            const next = !sidebar.classList.contains('collapsed');
            sidebar.classList.toggle('collapsed', next);
            localStorage.setItem(SIDEBAR_KEY, next ? '1' : '0');
            toggle.innerHTML = next
                ? '<i class="fas fa-angles-right"></i>'
                : '<i class="fas fa-angles-left"></i>';
        });
    }

    document.querySelectorAll('.tab-btn').forEach((btn) => {
        btn.addEventListener('click', () => setActiveTab(btn.dataset.tab));
    });

    window.addEventListener('hashchange', () => {
        setActiveTab(location.hash.slice(1));
    });

    initSidebarGroups();
    initSidebarToggle();
    setActiveTab(location.hash.slice(1));
})();
