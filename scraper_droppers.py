"""
=============================================================
  MÓDULO: SCRAPER DE CATÁLOGO DE DROPPERS
  Extrae productos por categoría con precios e imágenes
=============================================================
"""

import requests
import re
from bs4 import BeautifulSoup

BASE = "https://droppers.com.ar"

# Mapa de categorías Droppers → categorías ML
CATEGORIAS_DROPPERS = {
    "Home y Deco":           {"url": "/productos/home-y-deco.html",          "ml": "Hogar y Muebles"},
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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "es-AR,es;q=0.9",
}


class ScraperDroppers:

    def __init__(self, session_cookie=None):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        if session_cookie:
            self.session.cookies.set("PHPSESSID", session_cookie)

    def login(self, email, password):
        """Inicia sesión para ver precios con login."""
        try:
            # Obtener form key
            r = self.session.get(f"{BASE}/customer/account/login/")
            soup = BeautifulSoup(r.text, "html.parser")
            form_key = ""
            fk = soup.find("input", {"name": "form_key"})
            if fk:
                form_key = fk.get("value", "")

            # Login
            self.session.post(f"{BASE}/customer/account/loginPost/", data={
                "form_key": form_key,
                "login[username]": email,
                "login[password]": password,
                "send": "",
            })
            return True
        except Exception as e:
            print(f"Error login Droppers: {e}")
            return False

    def obtener_categorias(self):
        """Devuelve la lista de categorías disponibles."""
        return [{"nombre": k, "url": v["url"], "ml": v["ml"]} for k, v in CATEGORIAS_DROPPERS.items()]

    def scrape_categoria(self, categoria_nombre, max_paginas=10):
        """
        Extrae todos los productos de una categoría.
        Retorna lista de productos con título, precio, imágenes y URL.
        """
        cat_info = CATEGORIAS_DROPPERS.get(categoria_nombre)
        if not cat_info:
            return []

        productos = []
        pagina = 1

        while pagina <= max_paginas:
            url = f"{BASE}{cat_info['url']}?p={pagina}&product_list_limit=36"
            try:
                r = self.session.get(url, timeout=15)
                soup = BeautifulSoup(r.text, "html.parser")

                # Buscar productos en la página
                items = soup.select(".product-item")
                if not items:
                    items = soup.select(".item.product")
                if not items:
                    break

                for item in items:
                    try:
                        prod = self._parsear_item(item)
                        if prod:
                            prod["categoria_ml"] = cat_info["ml"]
                            productos.append(prod)
                    except Exception:
                        pass

                # Ver si hay página siguiente
                siguiente = soup.select_one("a.next, li.next a, .pages-item-next a")
                if not siguiente:
                    break
                pagina += 1

            except Exception as e:
                print(f"Error scrapeando página {pagina}: {e}")
                break

        return productos

    def _parsear_item(self, item):
        """Extrae datos de un item de la lista."""
        # Título
        titulo_el = item.select_one(".product-item-name a, .product-item-link, h2.product-name a")
        if not titulo_el:
            return None
        titulo = titulo_el.get_text(strip=True)
        url_prod = titulo_el.get("href", "")

        # Imagen
        img_el = item.select_one("img.product-image-photo, img.photo, .product-image img")
        imagen = ""
        if img_el:
            imagen = img_el.get("src") or img_el.get("data-src") or ""
            # Convertir thumbnail a imagen más grande
            imagen = imagen.replace("/cache/180de48b51213f2b31b6fc04fceb91c7/", "/")

        # Precio — buscar en el HTML
        precio = 0
        precio_el = item.select_one(".price, .price-wrapper .price, [data-price-type='finalPrice'] .price")
        if precio_el:
            precio_txt = precio_el.get_text(strip=True)
            precio_txt = re.sub(r"[^\d,.]", "", precio_txt).replace(".", "").replace(",", ".")
            try:
                precio = float(precio_txt)
            except:
                precio = 0

        # Si no encontró precio, intentar en el link del producto
        if precio == 0 and url_prod:
            precio = self._obtener_precio_detalle(url_prod)

        if not titulo or precio == 0:
            return None

        return {
            "titulo":   titulo,
            "costo":    precio,
            "url":      url_prod,
            "imagenes": [imagen] if imagen else [],
            "stock":    10,
            "atributos": [],
        }

    def _obtener_precio_detalle(self, url_prod):
        """Obtiene el precio desde la página de detalle del producto."""
        try:
            r = self.session.get(url_prod, timeout=10)
            soup = BeautifulSoup(r.text, "html.parser")

            # Intentar varias formas de encontrar el precio
            for selector in [
                "[data-price-type='finalPrice'] .price",
                ".product-info-price .price",
                ".price-final_price .price",
                "span.price",
            ]:
                el = soup.select_one(selector)
                if el:
                    txt = re.sub(r"[^\d,.]", "", el.get_text(strip=True))
                    txt = txt.replace(".", "").replace(",", ".")
                    try:
                        return float(txt)
                    except:
                        pass

            # Buscar en JSON-LD
            scripts = soup.find_all("script", type="application/ld+json")
            for s in scripts:
                try:
                    import json
                    data = json.loads(s.string)
                    if isinstance(data, dict) and "offers" in data:
                        return float(data["offers"].get("price", 0))
                except:
                    pass

        except Exception:
            pass
        return 0

    def obtener_imagenes_producto(self, url_prod):
        """Obtiene todas las imágenes de un producto desde su página de detalle."""
        try:
            r = self.session.get(url_prod, timeout=10)
            soup = BeautifulSoup(r.text, "html.parser")
            imagenes = []

            # Galería principal
            for img in soup.select(".fotorama__img, .gallery-placeholder img, .product.media img"):
                src = img.get("src") or img.get("data-src") or ""
                if src and "placeholder" not in src and src not in imagenes:
                    # Limpiar cache path para imagen de mayor resolución
                    src = re.sub(r"/cache/[a-f0-9]+/", "/", src)
                    imagenes.append(src)

            return imagenes[:6]  # ML acepta hasta 6 imágenes
        except:
            return []
