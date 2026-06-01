import asyncio
import json
from playwright.async_api import async_playwright

async def main():
    with open(r"C:\Users\Feder\Desktop\mlbot\ml_bot\productos_droppers.json", encoding="utf-8") as f:
        productos = json.load(f)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        await page.goto("https://droppers.com.ar/customer/account/login/", timeout=30000)
        await page.fill("#email", "dcsworld392@gmail.com")
        await page.fill("#pass", "220566494Fede@")
        await page.click("#send2")
        await page.wait_for_timeout(3000)
        print("Login OK")

        # Probar 3 productos distintos
        for prod in productos[:3]:
            if not prod.get("url"):
                continue
            await page.goto(prod["url"], timeout=20000)
            await page.wait_for_timeout(2000)

            print(f"\n=== {prod['titulo'][:50]} ===")
            print(f"URL: {prod['url']}")

            # Buscar todos los precios en la pagina
            todos = await page.query_selector_all(".price")
            print(f"Cantidad de .price en pagina: {len(todos)}")
            for j, el in enumerate(todos[:5]):
                txt = await el.inner_text()
                print(f"  [{j}] {repr(txt)}")

            # Probar selectores mas especificos
            for sel in [
                ".product-info-price .price",
                ".price-box .price",
                "[data-price-type='finalPrice'] .price",
                "[data-price-type='minPrice'] .price",
                ".special-price .price",
                ".regular-price .price",
            ]:
                el = await page.query_selector(sel)
                if el:
                    txt = await el.inner_text()
                    print(f"  Selector '{sel}': {repr(txt)}")

        await browser.close()

asyncio.run(main())
