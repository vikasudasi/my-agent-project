(function () {
    if (typeof marked === 'undefined' || typeof DOMPurify === 'undefined') return;

    marked.setOptions({ gfm: true, breaks: true });

    function renderPreview(textarea) {
        const preview = document.getElementById(textarea.dataset.preview);
        if (!preview) return;
        const raw = textarea.value || '';
        if (!raw.trim()) {
            preview.innerHTML = '<p class="text-gray-400 italic text-sm">Preview will appear here...</p>';
            return;
        }
        preview.innerHTML = DOMPurify.sanitize(marked.parse(raw));
    }

    document.addEventListener('DOMContentLoaded', function () {
        const textarea = document.getElementById('doc-editor');
        if (!textarea) return;
        textarea.addEventListener('input', function () { renderPreview(textarea); });
        renderPreview(textarea);
    });
})();
