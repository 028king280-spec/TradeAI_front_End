from playwright.sync_api import sync_playwright

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto("http://localhost:3000/paper-trading", wait_until="networkidle")
        page.wait_for_timeout(2000)
        panel = page.locator("#research-paper")
        panel.screenshot(path=r"C:\Users\Sourav Verma\.gemini\antigravity\brain\a47b88ae-3d04-471a-a671-adebd0b6ad2f\research_paper_account_with_5_trades.png")
        print("Captured research panel screenshot successfully!")
        browser.close()

if __name__ == "__main__":
    main()
