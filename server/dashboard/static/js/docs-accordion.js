function toggleDocSection(btn) {
    const panel = document.getElementById(btn.getAttribute('aria-controls'));
    if (!panel) return;
    const expanded = panel.classList.toggle('hidden') === false;
    btn.setAttribute('aria-expanded', expanded);
}

document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.doc-accordion-toggle').forEach(function (btn) {
        btn.addEventListener('click', function () {
            toggleDocSection(btn);
        });
    });
});
