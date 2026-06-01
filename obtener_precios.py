import asyncio
import json
from playwright.async_api import async_playwright

def parsear_precio(txt):
    limpio = ""
    for c in txt:
        if c.isdigit() or c in ".,":
            limpio += c
    limpio = limpio.replace(".", "").replace(",", ".")
    try:
        return float(limpio)
    except:
        return 0

async def main():
    archivo = r"C:\Users\Feder\Desktop\mlbot\ml_bot\productos_droppers.json"

    with open(archivo, encoding="utf-8") as f:
        productos = json.load(f)

    print(f"Total productos: {len(productos)}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.goto("https://droppers.com.ar/customer/account/login/", timeout=30000)
        await page.fill("#email", "dcsworld392@gmail.com")
        await page.fill("#pass", "220566494Fede@")
        await page.click("#send2")
        await page.wait_for_timeout(3000)
        print("Login OK")

        actualizados = 0
        sin_precio = 0

        for i, prod in enumerate(productos):
            if not prod.get("url"):
                continue
            try:
                await page.goto(prod["url"], timeout=20000)
                await page.wait_for_timeout(1000)

                # Selector correcto - precio real del producto (no header)
                el = await page.query_selector(".product-info-price .price")
                if el:
                    txt = await el.inner_text()
                    precio = parsear_precio(txt)
                    if precio > 0:
                        prod["costo"] = precio
                        actualizados += 1
                        titulo = prod.get("titulo", "")[:40]
                        print(f"{i+1}. {titulo} -> ${precio:,.0f}")
                    else:
                        sin_precio += 1
                        print(f"{i+1}. Sin precio: {repr(txt)}")
                else:
                    sin_precio += 1
                    print(f"{i+1}. Selector no encontrado")
            except Exception as e:
                print(f"{i+1}. Error: {e}")

        await browser.close()

    with open(archivo, "w", encoding="utf-8") as f:
        json.dump(productos, f, ensure_ascii=False, indent=2)

    print(f"\nActualizados: {actualizados}/{len(productos)}")
    print(f"Sin precio: {sin_precio}")

asyncio.run(main())
