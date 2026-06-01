import asyncio, json, re
from playwright.async_api import async_playwright

async def main():
    with open(r'C:\Users\Feder\Desktop\mlbot\ml_bot\productos_droppers.json', encoding='utf-8') as f:
        productos = json.load(f)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        
        await page.goto('https://droppers.com.ar/customer/account/login/', timeout=30000)
        await page.fill('#email', 'dcsworld392@gmail.com')
        await page.fill('#pass', '220566494Fede@')
        await page.click('#send2')
        await page.wait_for_timeout(3000)
        
        await page.goto(productos[0]['url'], timeout=20000)
        await page.wait_for_timeout(2000)
        
        precio_el = await page.query_selector('.price')
        if precio_el:
            txt = await precio_el.inner_text()
            print(f'Texto raw: [{repr(txt)}]')
            print(f'Largo: {len(txt)}')
            for c in txt:
                print(f'  char: [{repr(c)}] = {ord(c)}')
        
        await browser.close()

asyncio.run(main())
