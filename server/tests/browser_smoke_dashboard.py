#!/usr/bin/env python3
"""Browser smoke test for dashboard UI using Playwright."""

import sys
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8080"
PROJECT_ID = "daa1ce70-1157-483b-ab15-f21fad72611c"
PARENT_TASK_ID = "089ddfdb-5fcb-4ecc-8145-f148047ab678"
SCREENSHOT_DIR = "/opt/cursor/artifacts/screenshots"


def main():
    errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        # Login
        page.goto(f"{BASE}/login")
        if "Default: admin / admin" in page.content():
            errors.append("Login page still shows default credentials hint")
        page.fill("#login-username", "admin")
        page.fill("#login-password", "admin")
        page.click('button[type="submit"]')
        page.wait_for_url(f"{BASE}/**")

        # Home
        page.goto(f"{BASE}/")
        if page.locator('h3:has-text("UI Test Project")').count() == 0:
            errors.append("Home page missing test project card")
        if not page.locator('link[href="/static/css/app.css"]').count():
            # stylesheet linked in head
            if '/static/css/app.css' not in page.content():
                errors.append("Home page missing compiled CSS link")
        page.screenshot(path=f"{SCREENSHOT_DIR}/dashboard-home.png", full_page=True)

        # Project page
        page.goto(f"{BASE}/projects/{PROJECT_ID}")
        page.wait_for_selector("#taskSearch")
        page.fill("#taskSearch", "Child")
        page.wait_for_timeout(500)
        child_link = page.get_by_role("link", name="Child Task", exact=True)
        if child_link.count() == 0:
            errors.append("Task search filter did not show Child Task")
        page.screenshot(path=f"{SCREENSHOT_DIR}/dashboard-project.png", full_page=True)

        # Status filter chip
        page.locator('.status-filter[data-status="pending"]').click()
        page.wait_for_timeout(200)
        pressed = page.locator('.status-filter[data-status="pending"]').get_attribute("aria-pressed")
        if pressed != "true":
            errors.append(f"Status filter aria-pressed expected true, got {pressed}")

        # Task detail + sidebar tree
        page.goto(f"{BASE}/tasks/{PARENT_TASK_ID}")
        if not page.locator("text=Task Tree").is_visible():
            errors.append("Task detail missing sidebar tree")
        if 'style="margin-left: 1.5rem"' not in page.content():
            errors.append("Task tree sidebar missing inline indentation for child")
        page.screenshot(path=f"{SCREENSHOT_DIR}/dashboard-task-detail.png", full_page=True)

        # Docs hub accordion
        page.goto(f"{BASE}/projects/{PROJECT_ID}/docs?type=spec")
        toggle = page.locator(".doc-accordion-toggle").first
        if toggle.count() == 0:
            errors.append("Docs hub missing accordion toggles")
        else:
            toggle.click()
            page.wait_for_timeout(200)
            panel_id = toggle.get_attribute("aria-controls")
            panel = page.locator(f"#{panel_id}")
            if panel.is_hidden():
                errors.append("Docs accordion panel did not expand on click")
        page.screenshot(path=f"{SCREENSHOT_DIR}/dashboard-docs-hub.png", full_page=True)

        # HTMX comment
        page.goto(f"{BASE}/projects/{PROJECT_ID}")
        page.fill(f"#comment-author-project-{PROJECT_ID}", "Browser")
        page.fill(f"#comment-content-project-{PROJECT_ID}", "Playwright UI test comment")
        page.locator(f'form[action="/comments/project/{PROJECT_ID}"] button[type="submit"]').click()
        page.wait_for_selector("text=Playwright UI test comment", timeout=5000)
        if page.locator("text=Playwright UI test comment").count() == 0:
            errors.append("HTMX comment not visible after submit")

        # Mobile viewport
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(f"{BASE}/projects/{PROJECT_ID}")
        page.screenshot(path=f"{SCREENSHOT_DIR}/dashboard-project-mobile.png", full_page=True)

        # Admin table
        page.goto(f"{BASE}/admin/agents")
        if page.locator(".overflow-x-auto table").count() == 0:
            errors.append("Admin agents table missing overflow-x-auto wrapper")
        page.screenshot(path=f"{SCREENSHOT_DIR}/dashboard-admin-agents.png", full_page=True)

        browser.close()

    if errors:
        print("BROWSER TEST FAILURES:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print("Browser smoke test passed.")
    print(f"Screenshots saved to {SCREENSHOT_DIR}/")
    return 0


if __name__ == "__main__":
    import os
    os.makedirs(SCREENSHOT_DIR, exist_ok=True)
    sys.exit(main())
