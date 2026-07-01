function showToast(message, type) {
    type = type || 'success';
    const container = document.getElementById('toast-container');
    if (!container) return;

    const colors = {
        success: 'bg-green-50 border-green-200 text-green-800',
        error: 'bg-red-50 border-red-200 text-red-800',
        info: 'bg-blue-50 border-blue-200 text-blue-800',
    };

    const toast = document.createElement('div');
    toast.setAttribute('role', 'status');
    toast.className = 'flex items-center justify-between gap-3 px-4 py-3 rounded-lg border shadow-sm text-sm ' + (colors[type] || colors.success);
    toast.innerHTML = '<span>' + message + '</span><button type="button" class="text-current opacity-60 hover:opacity-100" aria-label="Dismiss">&times;</button>';
    toast.querySelector('button').addEventListener('click', function () { toast.remove(); });
    container.appendChild(toast);

    setTimeout(function () {
        toast.classList.add('opacity-0', 'transition-opacity', 'duration-300');
        setTimeout(function () { toast.remove(); }, 300);
    }, 4000);
}

document.addEventListener('DOMContentLoaded', function () {
    const flash = document.getElementById('flash-banner');
    if (flash && flash.dataset.message) {
        showToast(flash.dataset.message, flash.dataset.type || 'success');
        flash.remove();
    }
});

document.body.addEventListener('htmx:afterRequest', function (evt) {
    const trigger = evt.detail.xhr.getResponseHeader('HX-Trigger');
    if (trigger) {
        try {
            const data = JSON.parse(trigger);
            if (data.showToast) showToast(data.showToast.message, data.showToast.type);
        } catch (e) { /* ignore */ }
    }
});
