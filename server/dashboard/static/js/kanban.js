document.addEventListener('DOMContentLoaded', function () {
    var board = document.getElementById('kanbanBoard');
    if (!board) return;

    var draggedId = null;

    board.querySelectorAll('.kanban-card').forEach(function (card) {
        card.addEventListener('dragstart', function (e) {
            draggedId = card.dataset.taskId;
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', draggedId);
            card.classList.add('opacity-50');
        });

        card.addEventListener('dragend', function () {
            card.classList.remove('opacity-50');
            draggedId = null;
        });
    });

    board.querySelectorAll('.kanban-dropzone').forEach(function (zone) {
        zone.addEventListener('dragover', function (e) {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            zone.classList.add('ring-2', 'ring-blue-400', 'ring-inset');
        });

        zone.addEventListener('dragleave', function (e) {
            if (!zone.contains(e.relatedTarget)) {
                zone.classList.remove('ring-2', 'ring-blue-400', 'ring-inset');
            }
        });

        zone.addEventListener('drop', function (e) {
            e.preventDefault();
            zone.classList.remove('ring-2', 'ring-blue-400', 'ring-inset');
            if (!draggedId) return;

            var column = zone.closest('.kanban-column');
            if (!column) return;

            var newStatus = column.dataset.status;
            var card = board.querySelector('[data-task-id="' + draggedId + '"]');
            if (!card || card.dataset.status === newStatus) return;

            fetch('/tasks/' + draggedId + '/update', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: new URLSearchParams({ status: newStatus }),
            })
                .then(function (res) {
                    if (res.ok) {
                        window.location.href = window.location.pathname + '?view=board';
                    } else {
                        alert('Failed to update task status.');
                    }
                })
                .catch(function () {
                    alert('Failed to update task status.');
                });
        });
    });
});
