import asyncio, json, re, time
from playwright.async_api import async_playwright

BASE = 'https://droppers.com.ar'

async def obtener_fotos(page, url):
    try:
        await page.goto(url, timeout=30000)
        await page.wait_for_timeout(2000)
        imgs = await page.eval_on_selector_all('img', 'imgs => imgs.map(i => i.src)')
        fotos = [i for i in imgs if '/media/catalog/product/' in i and 'placeholder' not in i.lower()]
        fotos = list(dict.fromkeys(fotos))
        # Limpiar cache de las URLs
        fotos_limpias = []
        for f in fotos:
            f_limpia = re.sub(r'/cache/[a-f0-9]{32}/', '/', f)
            if f_limpia not in fotos_limpias:
                fotos_limpias.append(f_limpia)
        return fotos_limpias[:6]
    except:
        return []

async def main():
    with open(r'C:\Users\Feder\Desktop\mlbot\ml_bot\productos_droppers.json', 'r', encoding='utf-8') as f:
        productos = json.load(f)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        actualizados = 0
        for i, prod in enumerate(productos):
            if not prod.get('url'):
                continue
            fotos = await obtener_fotos(page, prod['url'])
            if fotos:
                prod['imagenes'] = fotos
                actualizados += 1
                print(f'{i+1}. {prod["titulo"][:40]} — {len(fotos)} fotos')
            else:
                print(f'{i+1}. {prod["titulo"][:40]} — sin fotos')
        
        await browser.close()

    with open(r'C:\Users\Feder\Desktop\mlbot\ml_bot\productos_droppers.json', 'w', encoding='utf-8') as f:
        json.dump(productos, f, ensure_ascii=False, indent=2)
    
    print(f'\nActualizados: {actualizados}/{len(productos)} productos')

asyncio.run(main())
