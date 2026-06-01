import asyncio, json
from playwright.async_api import async_playwright

async def main():
    with open(r'C:\Users\Feder\Desktop\mlbot\ml_bot\productos_droppers.json', encoding='utf-8') as f:
        productos = json.load(f)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        
        # Login
        await page.goto('https://droppers.com.ar/customer/account/login/', timeout=30000)
        await page.fill('#email', 'dcsworld392@gmail.com')
        await page.fill('#pass', '220566494Fede@')
        await page.click('#send2')
        await page.wait_for_timeout(3000)
        print('Login OK')
        
        # Detectar selector de precio en primer producto
        if productos:
            await page.goto(productos[0]['url'], timeout=20000)
            await page.wait_for_timeout(2000)
            # Buscar todos los posibles selectores de precio
            for sel in ['.price', '.price-wrapper .price', '[data-price-type] .price', 
                        '.product-info-price .price', 'span.price', '.special-price .price',
                        '.regular-price .price', '[data-price-amount]']:
                el = await page.query_selector(sel)
                if el:
                    txt = await el.inner_text()
                    print(f'Selector encontrado: {sel} → {txt}')
                    break
            
            # Mostrar HTML del area de precio
            precio_area = await page.query_selector('.product-info-price, .price-box, .pricing')
            if precio_area:
                html = await precio_area.inner_html()
                print(f'HTML precio: {html[:300]}')
        
        await browser.close()

asyncio.run(main())
