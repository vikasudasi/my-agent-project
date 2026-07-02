function toggleSubtasks(taskId) {
    const container = document.getElementById('subtasks-' + taskId);
    const chevron = document.getElementById('chevron-' + taskId);
    const btn = document.getElementById('toggle-' + taskId);
    if (!container) return;
    const expanded = container.classList.toggle('hidden') === false;
    if (chevron) chevron.style.transform = expanded ? 'rotate(90deg)' : '';
    if (btn) btn.setAttribute('aria-expanded', expanded);
}

function confirmStatusChange(select) {
    const previous = select.dataset.previous || select.value;
    if (select.value === previous) return;
    if (confirm('Change task status to "' + select.value.replace('_', ' ') + '"?')) {
        select.form.submit();
    } else {
        select.value = previous;
    }
}

document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('select[name="status"][data-confirm]').forEach(function (select) {
        select.dataset.previous = select.value;
        select.addEventListener('change', function () {
            confirmStatusChange(select);
        });
    });
});
