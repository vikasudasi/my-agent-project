"""
FastAPI Dashboard for AI Task Management System.

Human-readable web UI that reads from the same SQLite database
as the MCP server. Shows projects, task trees, progress, and docs.
"""

import hashlib
import os
import secrets
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Request, Form, HTTPException, Response, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import uvicorn

from db import (
    init_db,
    list_projects,
    get_project,
    get_project_progress,
    get_task,
    get_task_tree,
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
    add_comment,
    list_comments,
    list_agents,
    get_agent,
    reissue_api_key,
    log_audit,
    get_audit_log,
    get_audit_log_by_agent,
    onboard_agent,
    validate_api_key,
)

app = FastAPI(title="AI Task Manager Dashboard")

template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
templates = Jinja2Templates(directory=template_dir)

# ---------------------------------------------------------------------------
# Simple session auth (in-memory)
# ---------------------------------------------------------------------------

# Default admin credentials
_ADMIN_USERNAME = "admin"
_ADMIN_PASSWORD_HASH = hashlib.sha256(b"admin").hexdigest()
_SESSION_SECRET = secrets.token_hex(16)  # Random per server restart
_sessions: dict[str, str] = {}  # token -> username


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def _create_session(username: str) -> str:
    token = secrets.token_hex(32)
    _sessions[token] = username
    return token


def _get_session_user(request: Request) -> Optional[str]:
    token = request.cookies.get("session")
    if token and token in _sessions:
        return _sessions[token]
    return None


def _require_admin(request: Request):
    """Returns the username if authenticated, raises 303 redirect otherwise."""
    user = _get_session_user(request)
    if not user:
        raise HTTPException(status_code=303, detail="Not authenticated")
    return user


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
# Auth middleware — redirect to /login if not authenticated
# ---------------------------------------------------------------------------

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    # Allow login, static files, and doc pages without auth
    public_paths = {"/login", "/static/"}
    path = request.url.path
    if any(path.startswith(p) for p in public_paths) or "/doc" in path:
        return await call_next(request)

    user = _get_session_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return await call_next(request)


# ---------------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    # If already logged in, redirect to home
    if _get_session_user(request):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": error},
    )


@app.post("/login")
async def login(request: Request, response: Response,
                username: str = Form(...), password: str = Form(...)):
    if username == _ADMIN_USERNAME and _hash_password(password) == _ADMIN_PASSWORD_HASH:
        token = _create_session(username)
        redirect = RedirectResponse(url="/", status_code=303)
        redirect.set_cookie(key="session", value=token, httponly=True, max_age=86400 * 7)
        return redirect
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": "Invalid username or password"},
    )


@app.get("/logout")
async def logout(response: Response):
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("session")
    return response


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
        request,
        "index.html",
        {"projects": enriched, "status_color": _status_color},
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
    doc_spec = get_project_doc(project_id, doc_type="spec")
    doc_progress = get_project_doc(project_id, doc_type="progress")
    doc_closure = get_project_doc(project_id, doc_type="closure")
    comments = list_comments("project", project_id)

    return templates.TemplateResponse(
        request,
        "project.html",
        {
            "project": project,
            "task_tree": task_tree,
            "doc_spec": doc_spec,
            "doc_progress": doc_progress,
            "doc_closure": doc_closure,
            "comments": comments,
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


# ---------------------------------------------------------------------------
# Task Detail Page
# ---------------------------------------------------------------------------

@app.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_detail(request: Request, task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    project = get_project_progress(task["project_id"])
    full_tree = get_task_subtree(task["project_id"])
    doc_spec = get_task_doc(task_id, doc_type="spec")
    doc_progress = get_task_doc(task_id, doc_type="progress")
    doc_closure = get_task_doc(task_id, doc_type="closure")
    comments = list_comments("task", task_id)

    # Build breadcrumb: walk up parent chain
    breadcrumb = []
    current = task
    while current and current.get("parent_id"):
        parent = get_task(current["parent_id"])
        if parent:
            breadcrumb.insert(0, parent)
            current = parent
        else:
            break

    return templates.TemplateResponse(
        request,
        "task_detail.html",
        {
            "task": task,
            "project": project,
            "full_tree": full_tree,
            "doc_spec": doc_spec,
            "doc_progress": doc_progress,
            "doc_closure": doc_closure,
            "comments": comments,
            "breadcrumb": breadcrumb,
            "status_color": _status_color,
            "statuses": ["pending", "in_progress", "completed", "blocked", "failed", "cancelled"],
        },
    )


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------

@app.post("/comments/{entity_type}/{entity_id}")
async def comment_add_route(entity_type: str, entity_id: str,
                             content: str = Form(...),
                             author: str = Form("")):
    add_comment(entity_type, entity_id, content, author=author)
    if entity_type == "project":
        return RedirectResponse(f"/projects/{entity_id}", status_code=303)
    return RedirectResponse(f"/tasks/{entity_id}", status_code=303)


# ---------------------------------------------------------------------------
# Doc pages (updated with doc_type support)
# ---------------------------------------------------------------------------

@app.get("/tasks/{task_id}/doc", response_class=HTMLResponse)
async def task_doc_page(request: Request, task_id: str,
                         type: str = Query("spec")):
    doc_type = type
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    doc = get_task_doc(task_id, doc_type=doc_type)
    project = get_project(task["project_id"])
    comments = list_comments("task", task_id)
    return templates.TemplateResponse(
        request,
        "doc.html",
        {
            "entity_type": "task",
            "entity_id": task_id,
            "title": task["title"],
            "project_id": task["project_id"],
            "content": doc,
            "doc_type": doc_type,
            "comments": comments,
        },
    )


@app.post("/tasks/{task_id}/doc")
async def task_doc_update(task_id: str, content: str = Form(...),
                           doc_type: str = Form("spec")):
    task = get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    upsert_task_doc(task_id, content, doc_type=doc_type)
    return RedirectResponse(f"/tasks/{task_id}/doc?type={doc_type}", status_code=303)


@app.get("/projects/{project_id}/doc", response_class=HTMLResponse)
async def project_doc_page(request: Request, project_id: str,
                            type: str = Query("spec")):
    doc_type = type
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    doc = get_project_doc(project_id, doc_type=doc_type)
    comments = list_comments("project", project_id)
    return templates.TemplateResponse(
        request,
        "doc.html",
        {
            "entity_type": "project",
            "entity_id": project_id,
            "title": project["name"],
            "project_id": project_id,
            "content": doc,
            "doc_type": doc_type,
            "comments": comments,
        },
    )


@app.post("/projects/{project_id}/doc")
async def project_doc_update(project_id: str, content: str = Form(...),
                              doc_type: str = Form("spec")):
    project = get_project(project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    upsert_project_doc(project_id, content, doc_type=doc_type)
    return RedirectResponse(f"/projects/{project_id}/doc?type={doc_type}", status_code=303)


# ---------------------------------------------------------------------------
# Admin: Agent Management
# ---------------------------------------------------------------------------

@app.get("/admin/agents", response_class=HTMLResponse)
async def admin_agents(request: Request):
    _require_admin(request)
    agents = list_agents()
    return templates.TemplateResponse(
        request,
        "admin_agents.html",
        {"agents": agents},
    )


@app.get("/admin/agents/{agent_id}", response_class=HTMLResponse)
async def admin_agent_detail(request: Request, agent_id: str):
    _require_admin(request)
    agent = get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    audit = get_audit_log_by_agent(agent["name"])
    return templates.TemplateResponse(
        request,
        "admin_agent_detail.html",
        {"agent": agent, "audit": audit, "new_key": None},
    )


@app.post("/admin/agents/{agent_id}/reissue")
async def admin_agent_reissue(request: Request, agent_id: str):
    _require_admin(request)
    result = reissue_api_key(agent_id)
    if not result:
        raise HTTPException(404, "Agent not found")
    log_audit("admin", "admin", "agent", agent_id, "key_reissued")
    return templates.TemplateResponse(
        request,
        "admin_agent_detail.html",
        {
            "agent": result,
            "new_key": result["api_key"],
            "audit": get_audit_log_by_agent(result["name"]),
        },
    )


@app.get("/admin/settings", response_class=HTMLResponse)
async def admin_settings(request: Request, message: str = "", error: str = ""):
    _require_admin(request)
    return templates.TemplateResponse(
        request,
        "admin_settings.html",
        {"message": message, "error": error},
    )


@app.post("/admin/settings/password")
async def admin_change_password(request: Request,
                                 current_password: str = Form(...),
                                 new_password: str = Form(...),
                                 confirm_password: str = Form(...)):
    _require_admin(request)
    global _ADMIN_PASSWORD_HASH
    if _hash_password(current_password) != _ADMIN_PASSWORD_HASH:
        return templates.TemplateResponse(
            request,
            "admin_settings.html",
            {"error": "Current password is incorrect"},
        )
    if new_password != confirm_password:
        return templates.TemplateResponse(
            request,
            "admin_settings.html",
            {"error": "New passwords do not match"},
        )
    if len(new_password) < 4:
        return templates.TemplateResponse(
            request,
            "admin_settings.html",
            {"error": "New password must be at least 4 characters"},
        )
    _ADMIN_PASSWORD_HASH = _hash_password(new_password)
    return templates.TemplateResponse(
        request,
        "admin_settings.html",
        {"message": "Password changed successfully"},
    )


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    uvicorn.run(app, host="0.0.0.0", port=8000)