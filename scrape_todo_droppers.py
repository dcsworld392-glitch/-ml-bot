"""
scrape_todo_droppers.py
Scrapeá TODAS las categorías de Droppers automáticamente con Playwright.
Al terminar sube el JSON al bot de Simple's.

Uso:
  python scrape_todo_droppers.py
"""
import asyncio, json, requests, re, time
from playwright.async_api import async_playwright

BASE = "https://droppers.com.ar"
BOT_URL = "https://ml-bot-1c0d.onrender.com"
ARCHIVO = r"C:\Users\Feder\Desktop\mlbot\ml_bot\productos_droppers.json"

CATEGORIAS = {
    "Home y Deco":          "/productos/home-y-deco.html",
    "Bazar y Cocina":       "/productos/bazar-y-cocina.html",
    "Bano y Limpieza":      "/productos/ba-o-y-limpieza.html",
    "Electronica":          "/productos/electronica.html",
    "Accesorios Mascotas":  "/productos/accesorios-de-mascotas.html",
    "Estetica y Belleza":   "/productos/estetica-y-belleza.html",
    "Fitness":              "/productos/fitness.html",
    "Indumentaria y Moda":  "/productos/accesorios-de-moda.html",
    "Articulos Infantiles": "/productos/articulos-infantiles.html",
    "Nuevos Ingresos":      "/productos/nuevos-ingresos.html",
}

async def obtener_links_categoria(page, url_path):
    """Obtiene todos los links de productos de una categoría."""
    await page.goto(BASE + url_path, timeout=30000)
    await page.wait_for_timeout(4000)

    # Scroll para cargar todos los productos
    for _ in range(3):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1000)

    links = set()
    for a in await page.query_selector_all("a"):
        href = await a.get_attribute("href") or ""
        if (href.startswith("http") and href.endswith(".html")
                and "droppers.com.ar" in href
                and "/productos/" not in href.replace(BASE, "")
                and "/como-funciona" not in href
                and "/customer" not in href
                and "/checkout" not in href
                and "/dropper/" not in href
                and href != BASE + "/"
                and "login" not in href):
            links.add(href)
    return links


async def scrape_producto(page, href, categoria):
    """Scrapeá los datos de un producto individual."""
    try:
        await page.goto(href, timeout=20000)
        await page.wait_for_timeout(1500)

        # Título
        titulo = (await page.title()).replace(" - Droppers", "").strip()
        if not titulo or titulo == "Droppers":
            h1 = await page.query_selector("h1")
            titulo = (await h1.inner_text()).strip() if h1 else href.split("/")[-1].replace(".html", "")

        # Fotos
        imgs = []
        for i in await page.query_selector_all("img"):
            src = await i.get_attribute("src") or ""
            if "/media/catalog/product/" in src and "placeholder" not in src.lower():
                src = re.sub(r"/cache/[a-f0-9]{32}/", "/", src)
                if src not in imgs:
                    imgs.append(src)
        fotos = imgs[:6]

        # Descripción
        desc = ""
        for sel in [
            ".product.attribute.description .value",
            "#description .value",
            ".product-description",
            ".description .value",
        ]:
            el = await page.query_selector(sel)
            if el:
                desc = (await el.inner_text()).strip()[:800]
                break

        return {
            "titulo": titulo,
            "costo": 0,
            "url": href,
            "imagenes": fotos,
            "stock": 10,
            "atributos": {},
            "descripcion": desc,
            "categoria": categoria,
        }
    except Exception as e:
        print(f"    ❌ Error en {href}: {e}")
        return None


async def main():
    print("=" * 60)
    print("  Simple's — Scraper completo de Droppers")
    print("=" * 60)
    print()

    todos_productos = []
    inicio = time.time()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        for nombre, url_path in CATEGORIAS.items():
            print(f"\n📦 Categoría: {nombre}")
            print("-" * 40)

            try:
                links = await obtener_links_categoria(page, url_path)
                print(f"  🔍 {len(links)} productos encontrados")

                cat_productos = []
                for i, href in enumerate(list(links)[:60], 1):
                    prod = await scrape_producto(page, href, nombre)
                    if prod:
                        cat_productos.append(prod)
                        print(f"  ✅ {i}/{len(links)}: {prod['titulo'][:50]}")
                    await asyncio.sleep(0.3)

                todos_productos.extend(cat_productos)
                print(f"  ✅ {len(cat_productos)} productos de {nombre} listos")

            except Exception as e:
                print(f"  ❌ Error en categoría {nombre}: {e}")

        await browser.close()

    # Guardar JSON
    print(f"\n💾 Guardando {len(todos_productos)} productos en JSON...")
    with open(ARCHIVO, "w", encoding="utf-8") as f:
        json.dump(todos_productos, f, ensure_ascii=False, indent=2)

    # Resumen por categoría
    print("\n📊 Resumen:")
    from collections import Counter
    conteo = Counter(p["categoria"] for p in todos_productos)
    for cat, n in sorted(conteo.items()):
        print(f"  {cat}: {n} productos")
    print(f"\n  TOTAL: {len(todos_productos)} productos")

    # Subir al bot automáticamente
    print(f"\n🚀 Subiendo productos al bot...")
    try:
        r = requests.post(
            f"{BOT_URL}/api/cargar-productos",
            json={"productos": todos_productos},
            timeout=60
        )
        resultado = r.json()
        if resultado.get("ok"):
            print(f"  ✅ {resultado['productos']} productos cargados en el bot")
        else:
            print(f"  ⚠️ Respuesta: {r.text[:200]}")
    except Exception as e:
        print(f"  ❌ Error al subir: {e}")
        print(f"  Cargá el JSON manualmente con:")
        print(f"  python -c \"import requests,json; p=json.load(open(r'{ARCHIVO}',encoding='utf-8')); r=requests.post('{BOT_URL}/api/cargar-productos',json={{'productos':p}},timeout=60); print(r.text)\"")

    elapsed = int(time.time() - inicio)
    print(f"\n⏱️ Tiempo total: {elapsed // 60}m {elapsed % 60}s")
    print("\n✅ ¡Listo! Ahora podés elegir cualquier categoría en el dashboard.")


asyncio.run(main())
