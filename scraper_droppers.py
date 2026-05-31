"""
=============================================================
  MÓDULO: SCRAPER DE CATÁLOGO DE DROPPERS
  Extrae productos por categoría con precios e imágenes
=============================================================
"""

import requests
import re
import json
from bs4 import BeautifulSoup

BASE = "https://droppers.com.ar"

CATEGORIAS_DROPPERS = {
    "Home y Deco":           {"url": "/productos/home-y-deco.html",           "ml": "Hogar y Muebles"},
    "Bazar y Cocina":        {"url": "/productos/bazar-y-cocina.html",        "ml": "Hogar y Muebles"},
    "Baño y Limpieza":       {"url": "/productos/ba-o-y-limpieza.html",       "ml": "Hogar y Muebles"},
    "Electrónica":           {"url": "/productos/electronica.html",           "ml": "Electrónica"},
    "Accesorios Mascotas":   {"url": "/productos/accesorios-de-mascotas.html","ml": "Mascotas"},
    "Estética y Belleza":    {"url": "/productos/estetica-y-belleza.html",    "ml": "Salud y Belleza"},
    "Fitness":               {"url": "/productos/fitness.html",               "ml": "Deportes"},
    "Verano":                {"url": "/productos/verano.html",                "ml": "Deportes"},
    "Indumentaria y Moda":   {"url": "/productos/accesorios-de-moda.html",    "ml": "Ropa y Accesorios"},
    "Artículos Infantiles":  {"url": "/productos/articulos-infantiles.html",  "ml": "Juguetes"},
    "Nuevos Ingresos":       {"url": "/productos/nuevos-ingresos.html",       "ml": "Hogar y Muebles"},
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-AR,es;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


class ScraperDroppers:

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def obtener_categorias(self):
        return [{"nombre": k, "url": v["url"], "ml": v["ml"]} for k, v in CATEGORIAS_DROPPERS.items()]

    def scrape_categoria(self, categoria_nombre, max_paginas=5):
        """Extrae productos de una categoría usando requests + BeautifulSoup."""
        cat_info = CATEGORIAS_DROPPERS.get(categoria_nombre)
        if not cat_info:
            return []

        productos = []
        pagina = 1

        while pagina <= max_paginas:
            url = f"{BASE}{cat_info['url']}?p={pagina}&product_list_limit=36"
            try:
                r = self.session.get(url, timeout=20)
                soup = BeautifulSoup(r.text, "html.parser")

                # Droppers usa una lista ordenada con items de productos
                # Cada item tiene: img con link + negrita con link al producto
                items_encontrados = 0

                # Buscar todos los links a productos (.html que no sean categorías)
                links_productos = set()
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if (href.endswith(".html") and
                        BASE in href and
                        "/productos/" not in href and
                        "/como-funciona" not in href and
                        "/customer/" not in href and
                        "/checkout/" not in href and
                        "/dropper/" not in href and
                        href != f"{BASE}/" and
                        "login" not in href and
                        "create" not in href):
                        links_productos.add(href)

                # Buscar imágenes de productos con sus nombres
                for img in soup.find_all("img", alt=True):
                    alt = img.get("alt", "").strip()
                    src = img.get("src", "")
                    if (alt and len(alt) > 5 and
                        "logo" not in alt.lower() and
                        "banner" not in alt.lower() and
                        "placeholder" not in src.lower() and
                        "/media/catalog/product/" in src):

                        # Encontrar el link asociado a esta imagen
                        parent = img.find_parent("a")
                        url_prod = ""
                        if parent and parent.get("href", "").endswith(".html"):
                            url_prod = parent["href"]

                        # Mejorar resolución de imagen
                        img_url = re.sub(r"/cache/[a-f0-9]{32}/", "/", src)
                        if img_url.startswith("/"):
                            img_url = BASE + img_url

                        if url_prod and alt not in [p["titulo"] for p in productos]:
                            productos.append({
                                "titulo":    alt,
                                "costo":     0,  # se obtiene del detalle
                                "url":       url_prod,
                                "imagenes":  [img_url],
                                "stock":     10,
                                "atributos": [],
                                "categoria_ml": cat_info["ml"],
                            })
                            items_encontrados += 1

                if items_encontrados == 0:
                    break

                # Ver si hay página siguiente
                siguiente = soup.find("a", string=re.compile("Siguiente|Next", re.I))
                if not siguiente:
                    siguiente = soup.select_one(".pages-item-next a, .next a")
                if not siguiente:
                    break
                pagina += 1

            except Exception as e:
                print(f"Error página {pagina}: {e}")
                break

        # Obtener precios Y descripciones de las páginas de detalle (primeros 20)
        for prod in productos[:20]:
            if (prod["costo"] == 0 or not prod.get("descripcion")) and prod["url"]:
                try:
                    detalle = self._scrape_detalle(prod["url"])
                    if detalle:
                        if prod["costo"] == 0:
                            prod["costo"] = detalle.get("costo", 0)
                        if not prod.get("descripcion") and detalle.get("descripcion"):
                            prod["descripcion"] = detalle["descripcion"]
                        if detalle.get("imagenes") and len(detalle["imagenes"]) > len(prod.get("imagenes",[])):
                            prod["imagenes"] = detalle["imagenes"]
                except:
                    pass

        return [p for p in productos if p["titulo"]]

    def _parsear_item_lista(self, item):
        """Extrae datos básicos de un item en la lista."""
        # Título y URL
        link = (item.select_one(".product-item-name a") or
                item.select_one(".product-item-link") or
                item.select_one("h2 a") or
                item.select_one("a.product-item-link"))

        if not link:
            return None

        titulo = link.get_text(strip=True)
        url_prod = link.get("href", "")
        if not url_prod.startswith("http"):
            url_prod = BASE + url_prod

        # Imagen
        img = (item.select_one("img.product-image-photo") or
               item.select_one(".product-image-wrapper img") or
               item.select_one("img"))
        imagen = ""
        if img:
            imagen = (img.get("src") or img.get("data-src") or
                      img.get("data-original") or "")
            # Mejorar resolución quitando cache
            imagen = re.sub(r"/cache/[a-f0-9]{32}/", "/", imagen)

        # Precio — buscar en el item
        precio = self._extraer_precio_html(str(item))

        if not titulo:
            return None

        # Si no hay precio, marcar como 0 (se completará con detalle)
        return {
            "titulo":    titulo,
            "costo":     precio,
            "url":       url_prod,
            "imagenes":  [imagen] if imagen else [],
            "stock":     10,
            "atributos": [],
        }

    def _extraer_precio_html(self, html):
        """Extrae precio de un fragmento HTML."""
        # Buscar patrones de precio argentino: $12.100,00 o $ 12.100
        patrones = [
            r'\$\s*([\d\.]+(?:,\d{2})?)',
            r'"price":\s*"?([\d\.]+)"?',
            r'data-price-amount="([\d\.]+)"',
        ]
        for patron in patrones:
            match = re.search(patron, html)
            if match:
                txt = match.group(1).replace(".", "").replace(",", ".")
                try:
                    val = float(txt)
                    if val > 100:  # filtrar valores muy chicos
                        return val
                except:
                    pass
        return 0

    def _scrape_via_links(self, cat_url, cat_ml):
        """Método alternativo: extrae links de productos y visita cada uno."""
        productos = []
        try:
            url = f"{BASE}{cat_url}"
            r = self.session.get(url, timeout=20)
            soup = BeautifulSoup(r.text, "html.parser")

            # Buscar todos los links a productos
            links = []
            for a in soup.select("a[href]"):
                href = a.get("href", "")
                # Los productos de Droppers tienen URLs como /nombre-producto.html
                if href.endswith(".html") and "/productos/" not in href and href != cat_url:
                    if BASE in href or href.startswith("/"):
                        full = href if href.startswith("http") else BASE + href
                        if full not in links:
                            links.append(full)

            links = links[:20]  # máximo 20 para no tardar mucho

            for link in links:
                try:
                    prod = self._scrape_detalle(link)
                    if prod:
                        prod["categoria_ml"] = cat_ml
                        productos.append(prod)
                except:
                    pass

        except Exception as e:
            print(f"Error scrape via links: {e}")

        return productos

    def _scrape_detalle(self, url_prod):
        """Extrae datos completos desde la página de detalle de un producto."""
        try:
            r = self.session.get(url_prod, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")

            # Título
            titulo = ""
            for sel in ["h1.page-title span", "h1.product-name", "h1", ".page-title"]:
                el = soup.select_one(sel)
                if el:
                    titulo = el.get_text(strip=True)
                    break
            if not titulo or len(titulo) < 3:
                return None

            # Precio
            precio = 0
            for sel in ["[data-price-type='finalPrice'] .price",
                        ".product-info-price .price",
                        ".price-final_price .price",
                        "span.price"]:
                el = soup.select_one(sel)
                if el:
                    precio = self._extraer_precio_html(el.get_text())
                    if precio > 0:
                        break

            # Si aún no hay precio, buscar en JSON-LD
            if precio == 0:
                for script in soup.find_all("script", type="application/ld+json"):
                    try:
                        data = json.loads(script.string or "")
                        if isinstance(data, dict) and "offers" in data:
                            precio = float(data["offers"].get("price", 0))
                            break
                    except:
                        pass

            # Imágenes — múltiples selectores para capturar toda la galería
            imagenes = []
            selectores_img = [
                ".fotorama__img",
                ".gallery-placeholder img",
                ".product.media img",
                "img.product-image-photo",
                ".MagicSlideshow img",
                "[data-gallery] img",
                ".owl-item img",
            ]
            for selector in selectores_img:
                for img in soup.select(selector):
                    src = (img.get("src") or img.get("data-src") or
                           img.get("data-lazy") or img.get("data-original") or "")
                    if (src and "placeholder" not in src.lower() and
                            "logo" not in src.lower() and
                            "/media/catalog/product/" in src and
                            src not in imagenes):
                        src = re.sub(r"/cache/[a-f0-9]{32}/", "/", src)
                        if src.startswith("/"):
                            src = BASE + src
                        imagenes.append(src)

            # Si no encontró imágenes con selectores, buscar todas las imágenes del catálogo
            if not imagenes:
                for img in soup.find_all("img"):
                    src = img.get("src", "")
                    if "/media/catalog/product/" in src and "placeholder" not in src:
                        src = re.sub(r"/cache/[a-f0-9]{32}/", "/", src)
                        if src.startswith("/"):
                            src = BASE + src
                        if src not in imagenes:
                            imagenes.append(src)

            imagenes = list(dict.fromkeys(imagenes))[:6]

            # Descripción
            descripcion = ""
            for sel in [".product.attribute.description .value",
                        ".product-info-main .product.attribute",
                        "#description .value"]:
                el = soup.select_one(sel)
                if el:
                    descripcion = el.get_text(strip=True)[:500]
                    break

            return {
                "titulo":      titulo,
                "costo":       precio,
                "url":         url_prod,
                "imagenes":    imagenes,
                "descripcion": descripcion,
                "stock":       10,
                "atributos":   [],
            }

        except Exception as e:
            return None

