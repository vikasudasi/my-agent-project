"""
FastAPI Dashboard for AI Task Management System.

Human-readable web UI that reads from the same SQLite database
as the MCP server. Shows projects, task trees, progress, and docs.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

from db import (
    init_db,
    list_projects,
    get_project,
    get_project_progress,
    get_task,
    list_tasks,
    get_task_subtree,
    update_task,
    delete_task,
    get_project_doc,
    upsert_project_doc,
    get_task_doc,
    upsert_task_doc,
    create_project,
    create_task,
)

app = FastAPI(title="AI Task Manager Dashboard")

template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
templates = Jinja2Templates(directory=template_dir)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _status_color(status: str) -> str:
    colors = {
        "pending": "#6b7280",
        "in_progress": "#3b82f6",
        "completed": "#22c55e",
        "blocked": "#ef4444",
        "failed": "#f97316",
        "cancelled": "#9ca3af",
        "active": "#3b82f6",
        "archived": "#6b7280",
    }
    return colors.get(status, "#6b7280")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    projects = list_projects()
    enriched = []
    for p in projects:
        progress = get_project_progress(p["id"])
        enriched.append(progress if progress else p)

    return templates.TemplateResponse(
        "index.html",
        {"request": request, "projects": enriched, "status_color": _status_color},
    )


@app.post("/projects/create")
async def project_create(name: str = Form(...), description: str = Form("")):
    create_project(name, description)
    return RedirectResponse("/", status_code=303)


@app.post("/projects/{project_id}/delete")
async def project_delete(project_id: str):
    from db import delete_project as dp
    dp(project_id)
    return RedirectResponse("/", status_code=303)


@app.get("/projects/{project_id}", response_class=HTMLResponse)
async def project_detail(request: Request, project_id: str):
    project = get_project_progress(project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    task_tree = get_task_subtree(project_id)
    doc = get_project_doc(project_id)

    return templates.TemplateResponse(
        "project.html",
        {
            "request": request,
            "project": project,
            "task_tree": task_tree,
            "doc": doc,
            "status_color": _status_color,
            "statuses": ["pending", "in_progress", "completed", "blocked", "failed", "cancelled"],
        },
    )


@app.post("/projects/{project_id}/tasks/create")
async def task_create(
    project_id: str,
    title: str = Form(...),
    description: str = Form(""),
    parent_id: str = Form(""),
):
    create_task(
        project_id,
        title,
        description,
        parent_id=parent_id if parent_id else None,
    )
    return RedirectResponse(f"/projects/{project_id}", status_code=303)


@app.post("/tasks/{task_id}/update")
async def task_update_route(task_id: str, status: str = Form(...)):
    update_task(task_id, status=status)
    # Redirect back to the project page
    task = get_task(task_id)
    if task:
        return RedirectResponse(f"/projects/{task['project_id']}", status_code=303)
    return RedirectResponse("/", status_code=303)


@app.get("/tasks/{task_id}/doc", response_class=HTMLResponse)
async def task_doc_page(request: Request, task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    doc = get_task_doc(task_id)
    project = get_project(task["project_id"])
    return templates.TemplateResponse(
        "doc.html",
        {
            "request": request,
            "entity_type": "task",
            "entity_id": task_id,
            "title": task["title"],
            "project_id": task["project_id"],
            "content": doc,
        },
    )


@app.post("/tasks/{task_id}/doc")
async def task_doc_update(task_id: str, content: str = Form(...)):
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    upsert_task_doc(task_id, content)
    return RedirectResponse(f"/tasks/{task_id}/doc", status_code=303)


@app.get("/projects/{project_id}/doc", response_class=HTMLResponse)
async def project_doc_page(request: Request, project_id: str):
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    doc = get_project_doc(project_id)
    return templates.TemplateResponse(
        "doc.html",
        {
            "request": request,
            "entity_type": "project",
            "entity_id": project_id,
            "title": project["name"],
            "project_id": project_id,
            "content": doc,
        },
    )


@app.post("/projects/{project_id}/doc")
async def project_doc_update(project_id: str, content: str = Form(...)):
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    upsert_project_doc(project_id, content)
    return RedirectResponse(f"/projects/{project_id}/doc", status_code=303)


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    uvicorn.run(app, host="0.0.0.0", port=8000)