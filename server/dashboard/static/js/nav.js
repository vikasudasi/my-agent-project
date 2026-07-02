function toggleNavMenu(btn) {
    const menu = document.getElementById(btn.getAttribute('aria-controls'));
    if (!menu) return;
    const expanded = menu.classList.toggle('hidden') === false;
    btn.setAttribute('aria-expanded', expanded);
}

document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.nav-menu-toggle').forEach(function (btn) {
        btn.addEventListener('click', function () { toggleNavMenu(btn); });
    });
});
