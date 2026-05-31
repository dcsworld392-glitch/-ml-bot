import asyncio
from playwright.async_api import async_playwright
import json, re

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto('https://droppers.com.ar/reloj-muneca-oso-panda-blanco-y-negro-ninos-negro.html', timeout=30000)
        await page.wait_for_timeout(3000)
        
        # Buscar todas las imagenes del producto
        imgs = await page.eval_on_selector_all('img', 'imgs => imgs.map(i => i.src)')
        fotos = [i for i in imgs if '/media/catalog/product/' in i and 'placeholder' not in i]
        fotos = list(dict.fromkeys(fotos))
        
        print(f'Fotos encontradas: {len(fotos)}')
        for f in fotos:
            print(f)
        
        await browser.close()

asyncio.run(main())
