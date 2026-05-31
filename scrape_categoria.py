import asyncio, json, sys
from playwright.async_api import async_playwright

BASE = "https://droppers.com.ar"
CATEGORIAS = {
    "Home y Deco": "/productos/home-y-deco.html",
    "Bazar y Cocina": "/productos/bazar-y-cocina.html",
    "Fitness": "/productos/fitness.html",
    "Electronica": "/productos/electronica.html",
    "Accesorios Mascotas": "/productos/accesorios-de-mascotas.html",
    "Estetica y Belleza": "/productos/estetica-y-belleza.html",
    "Indumentaria y Moda": "/productos/accesorios-de-moda.html",
    "Articulos Infantiles": "/productos/articulos-infantiles.html",
    "Nuevos Ingresos": "/productos/nuevos-ingresos.html",
    "Bano y Limpieza": "/productos/ba-o-y-limpieza.html",
}

async def scrape_cat(page, nombre, url_path):
    print(f"Scrapeando {nombre}...")
    await page.goto(BASE + url_path, timeout=30000)
    await page.wait_for_timeout(4000)

    links = set()
    for a in await page.query_selector_all("a"):
        href = await a.get_attribute("href") or ""
        if (href.startswith("http") and href.endswith(".html")
                and "droppers.com.ar" in href
                and "/productos/" not in href.replace(BASE, "")
                and "/como-funciona" not in href
                and "/customer" not in href
                and "/checkout" not in href
                and href != BASE + "/"):
            links.add(href)

    print(f"  {len(links)} productos encontrados")
    productos = []

    for href in list(links)[:60]:
        try:
            await page.goto(href, timeout=20000)
            await page.wait_for_timeout(1500)

            titulo = (await page.title()).replace(" - Droppers", "").strip()

            imgs = []
            for i in await page.query_selector_all("img"):
                src = await i.get_attribute("src") or ""
                if "/media/catalog/product/" in src and "placeholder" not in src:
                    imgs.append(src)
            fotos = list(dict.fromkeys(imgs))[:6]

            desc = ""
            for sel in [".product.attribute.description .value", "#description .value", ".product-description"]:
                el = await page.query_selector(sel)
                if el:
                    desc = (await el.inner_text())[:600]
                    break

            productos.append({
                "titulo": titulo,
                "costo": 0,
                "url": href,
                "imagenes": fotos,
                "stock": 10,
                "atributos": {},
                "descripcion": desc,
                "categoria": nombre,
            })
            print(f"  OK: {titulo[:50]}")
        except Exception as e:
            print(f"  Error en {href}: {e}")

    return productos


async def main():
    cat = sys.argv[1] if len(sys.argv) > 1 else "Home y Deco"
    url = CATEGORIAS.get(cat, "/productos/home-y-deco.html")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        prods = await scrape_cat(page, cat, url)
        await browser.close()

    archivo = r"C:/Users/Feder/Desktop/mlbot/ml_bot/productos_droppers.json"

    # Mergear con JSON existente
    try:
        existentes = json.load(open(archivo, encoding="utf-8"))
        existentes = [p for p in existentes if p.get("categoria") != cat]
        existentes.extend(prods)
        prods = existentes
    except:
        pass

    json.dump(prods, open(archivo, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"\nTotal guardado: {len(prods)} productos ({[p for p in prods if p.get('categoria') == cat].__len__()} de {cat})")


asyncio.run(main())
