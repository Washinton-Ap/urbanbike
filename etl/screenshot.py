from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 800})

    # Login directo en el browser
    page.goto("http://127.0.0.1:8002/auth/login", wait_until="commit", timeout=15000)
    page.wait_for_selector("input[name='email']", timeout=5000)
    page.fill("input[name='email']", "admin@urbanbike.com")
    page.fill("input[name='password']", "Urbanbike123!")
    page.click("button[type='submit']")

    # Esperar que llegue al dashboard
    page.wait_for_url("**/dashboard**", timeout=15000)
    page.wait_for_timeout(2000)

    page.screenshot(path="dashboard_admin.png", full_page=False)
    print("OK - URL:", page.url)
    browser.close()
