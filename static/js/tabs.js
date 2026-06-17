(function () {
    const TAB_ACTIVE = 'border-indigo-600 text-indigo-600';
    const TAB_INACTIVE = 'border-transparent text-gray-600 hover:text-indigo-600 hover:border-gray-300';

    function getValidTabs() {
        return Array.from(document.querySelectorAll('.tab-btn')).map(btn => btn.dataset.tab);
    }

    function setActiveTab(tabId) {
        const validTabs = getValidTabs();
        const target = validTabs.includes(tabId) ? tabId : 'domains';

        document.querySelectorAll('.tab-btn').forEach(btn => {
            const isActive = btn.dataset.tab === target;
            btn.className = 'tab-btn px-5 py-3 text-sm font-medium border-b-2 transition whitespace-nowrap ' +
                (isActive ? TAB_ACTIVE : TAB_INACTIVE);
            btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
        });

        document.querySelectorAll('.tab-panel').forEach(panel => {
            panel.classList.toggle('hidden', panel.id !== `tab-${target}`);
        });

        history.replaceState(null, '', `#${target}`);
    }

    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => setActiveTab(btn.dataset.tab));
    });

    window.addEventListener('hashchange', () => {
        setActiveTab(location.hash.slice(1));
    });

    setActiveTab(location.hash.slice(1));
})();
