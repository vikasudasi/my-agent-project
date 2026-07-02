let activeStatuses = new Set();

function taskMatchesFilter(item) {
    const query = (document.getElementById('taskSearch')?.value || '').toLowerCase().trim();
    const title = item.dataset.title || '';
    const desc = item.dataset.description || '';
    const status = item.dataset.status || '';

    const matchesSearch = !query || title.includes(query) || desc.includes(query);
    const matchesStatus = activeStatuses.size === 0 || activeStatuses.has(status);
    return matchesSearch && matchesStatus;
}

function taskSubtreeMatches(item) {
    if (taskMatchesFilter(item)) return true;
    const children = item.querySelector(':scope > .task-children');
    if (!children) return false;
    return Array.from(children.querySelectorAll('.task-item')).some(taskSubtreeMatches);
}

function updateFilterChipStates() {
    document.querySelectorAll('.status-filter').forEach(function (btn) {
        const status = btn.dataset.status;
        const active = status === 'all'
            ? activeStatuses.size === 0
            : activeStatuses.has(status);
        btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
}

function applyTaskFilters() {
    const items = document.querySelectorAll('#taskList .task-item');
    let visibleCount = 0;

    items.forEach(function (item) {
        const show = taskSubtreeMatches(item);
        item.style.display = show ? '' : 'none';
        if (show) visibleCount++;

        if (show && item.querySelector(':scope > .task-children')) {
            const query = (document.getElementById('taskSearch')?.value || '').trim();
            const selfMatch = taskMatchesFilter(item);
            if (!selfMatch && query) {
                const container = item.querySelector(':scope > .task-children');
                const chevron = document.getElementById('chevron-' + item.dataset.taskId);
                const btn = document.getElementById('toggle-' + item.dataset.taskId);
                if (container) {
                    container.classList.remove('hidden');
                    if (chevron) chevron.style.transform = 'rotate(90deg)';
                    if (btn) btn.setAttribute('aria-expanded', 'true');
                }
            }
        }
    });

    const noResults = document.getElementById('noResults');
    const filterCount = document.getElementById('filterCount');
    if (noResults) noResults.classList.toggle('hidden', visibleCount > 0);
    if (filterCount) {
        const query = document.getElementById('taskSearch')?.value?.trim();
        if (query || activeStatuses.size > 0) {
            filterCount.textContent = visibleCount + ' task(s) visible';
            filterCount.classList.remove('hidden');
        } else {
            filterCount.classList.add('hidden');
        }
    }
    updateFilterChipStates();
}

function initTaskFilters() {
    const search = document.getElementById('taskSearch');
    if (!search) return;

    search.addEventListener('input', applyTaskFilters);

    document.querySelectorAll('.status-filter').forEach(function (btn) {
        btn.addEventListener('click', function () {
            const status = btn.dataset.status;
            if (status === 'all') {
                activeStatuses.clear();
                document.querySelectorAll('.status-filter').forEach(function (b) {
                    b.classList.remove('ring-2', 'ring-blue-400', 'bg-blue-100', 'text-blue-800');
                });
                btn.classList.add('ring-2', 'ring-blue-400', 'bg-blue-100', 'text-blue-800');
            } else {
                document.querySelector('.status-filter[data-status="all"]')
                    ?.classList.remove('ring-2', 'ring-blue-400', 'bg-blue-100', 'text-blue-800');
                if (activeStatuses.has(status)) {
                    activeStatuses.delete(status);
                    btn.classList.remove('ring-2', 'ring-blue-400');
                } else {
                    activeStatuses.add(status);
                    btn.classList.add('ring-2', 'ring-blue-400');
                }
            }
            applyTaskFilters();
        });
    });

    document.addEventListener('keydown', function (e) {
        if (e.target.matches('input, textarea, select')) return;
        if (e.key === '/') {
            e.preventDefault();
            search.focus();
        }
        if (e.key === 'n' || e.key === 'N') {
            const form = document.getElementById('newTaskForm');
            if (form) {
                e.preventDefault();
                form.classList.remove('hidden');
                form.querySelector('input[name="title"]')?.focus();
            }
        }
    });

    updateFilterChipStates();
}

document.addEventListener('DOMContentLoaded', initTaskFilters);
