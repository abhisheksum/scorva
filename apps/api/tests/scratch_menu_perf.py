import os
import signal
import subprocess
import time
import urllib.request
from playwright.sync_api import sync_playwright

def wait_for_url(url, timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status in (200, 307, 308):
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"Timeout waiting for {url}")

def safe_kill(proc):
    if not proc:
        return
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGTERM)
        proc.wait(timeout=3)
    except Exception:
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGKILL)
        except Exception:
            pass

def main():
    backend_proc = None
    frontend_proc = None
    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = "."
        backend_proc = subprocess.Popen(
            [".venv/bin/uvicorn", "apps.api.main:create_app", "--factory", "--host", "127.0.0.1", "--port", "8000"],
            env=env,
            cwd="/home/shubh/scorva",
            preexec_fn=os.setsid,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        frontend_env = os.environ.copy()
        frontend_env["NODE_OPTIONS"] = "--max-old-space-size=512"
        frontend_proc = subprocess.Popen(
            ["npx", "next", "start", "-p", "3000"],
            env=frontend_env,
            cwd="/home/shubh/scorva/apps/web",
            preexec_fn=os.setsid,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        wait_for_url("http://127.0.0.1:8000/api/v1/health", timeout=20)
        wait_for_url("http://127.0.0.1:3000/login", timeout=25)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            page.on("console", lambda msg: print(f"  [BROWSER CONSOLE {msg.type}]: {msg.text[:120]}"))

            print("\n=== STEP 1: LOGIN AS SUPER ADMIN ===")
            t0 = time.time()
            page.goto("http://localhost:3000/login")
            page.wait_for_selector('input[type="email"]')
            page.fill('input[type="email"]', "admin@scorva.io")
            page.fill('input[type="password"]', "Password123!")
            page.click('button[type="submit"]')
            page.wait_for_function("() => window.location.pathname.startsWith('/admin')", timeout=15000)
            print(f"Login as admin took {(time.time() - t0)*1000:.1f} ms. Current URL: {page.url}")

            menus = [
                ("Overview", "/admin"),
                ("Organizations", "/admin/organizations"),
                ("Users & Access", "/admin/users"),
                ("Hackathons", "/admin/hackathons"),
                ("Settings", "/admin/settings"),
            ]

            print("\n=== STEP 2: SWITCHING ADMIN MENUS ===")
            for name, path in menus:
                t0 = time.time()
                print(f"Clicking menu '{name}' ({path})...")
                # Navigate via clicking sidebar link or goto
                link_selector = f'a[href="{path}"]'
                page.wait_for_selector(link_selector, timeout=5000)
                page.click(link_selector)
                page.wait_for_function(f"() => window.location.pathname === '{path}'", timeout=15000)
                # Wait for any spinner or table to load
                page.wait_for_timeout(500)
                t1 = time.time()
                print(f"  -> Menu '{name}' rendered in {(t1 - t0)*1000:.1f} ms. URL: {page.url}")

            print("\n=== STEP 3: SWITCHING USER FROM ADMIN TO ORGANIZER ===")
            t0 = time.time()
            page.goto("http://localhost:3000/login")
            page.wait_for_selector('input[type="email"]')
            page.fill('input[type="email"]', "organizer@scorva.io")
            page.fill('input[type="password"]', "Password123!")
            page.click('button[type="submit"]')
            page.wait_for_function("() => window.location.pathname.startsWith('/organizations')", timeout=15000)
            print(f"Switch user to organizer took {(time.time() - t0)*1000:.1f} ms. Current URL: {page.url}")

            print("\n=== STEP 4: SWITCHING TENANT MENUS ===")
            org_url = page.url
            t0 = time.time()
            page.click('a:has-text("Hackathons")')
            page.wait_for_function("() => window.location.pathname.includes('/hackathons')", timeout=15000)
            page.wait_for_timeout(500)
            print(f"  -> Tenant Hackathons rendered in {(time.time() - t0)*1000:.1f} ms. URL: {page.url}")

            t0 = time.time()
            page.click('a:has-text("Organization Profile")')
            page.wait_for_function("() => !window.location.pathname.includes('/hackathons')", timeout=15000)
            page.wait_for_timeout(500)
            print(f"  -> Tenant Profile rendered in {(time.time() - t0)*1000:.1f} ms. URL: {page.url}")

            browser.close()
    finally:
        safe_kill(backend_proc)
        safe_kill(frontend_proc)

if __name__ == "__main__":
    main()
