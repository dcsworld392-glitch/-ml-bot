"""
=============================================================
  MÓDULO: PUBLICADOR INTELIGENTE CON IA
  Publica productos de Droppers en ML con títulos, precios
  y fichas técnicas optimizadas para Mercado Libre Argentina
=============================================================
"""

import os
import json
import re
import anthropic
from costos import CalculadoraCostos, COMISIONES_ML

# =============================================================
#  CATEGORÍAS ML
# =============================================================

CATEGORIAS_ML = {
    "Celulares y Smartphones":   "MLA1051",
    "Computación":               "MLA1652",
    "Electrónica":               "MLA1004",
    "Audio":                     "MLA1003",
    "Televisores":               "MLA1002",
    "Cámaras y Accesorios":      "MLA1039",
    "Videojuegos":               "MLA1144",
    "Electrodomésticos":         "MLA1574",
    "Herramientas":              "MLA1511",
    "Hogar y Muebles":           "MLA9201",
    "Ropa y Accesorios":         "MLA1430",
    "Deportes":                  "MLA1276",
    "Juguetes":                  "MLA5726",
    "Bebés":                     "MLA5726",
    "Salud y Belleza":           "MLA1246",
    "Mascotas":                  "MLA1612",
    "Libros":                    "MLA3025",
    "Industrias y Oficinas":     "MLA1953",
    "Construcción":              "MLA1459",
    "Accesorios para Autos":     "MLA1747",
    "Alimentos":                 "MLA1403",
}

KEYWORDS_CATEGORIAS = {
    "Celulares y Smartphones":  ["original", "sellado", "garantía", "libre", "desbloqueado"],
    "Computación":              ["original", "nuevo", "garantía", "factura", "envío gratis"],
    "Electrónica":              ["original", "garantía", "nuevo", "oficial", "envío gratis"],
    "Ropa y Accesorios":        ["original", "nuevo", "talles", "envío gratis", "liquidación"],
    "Hogar y Muebles":          ["nuevo", "envío gratis", "garantía", "calidad", "moderno"],
    "Deportes":                 ["original", "nuevo", "envío gratis", "profesional", "calidad"],
    "default":                  ["nuevo", "original", "envío gratis", "garantía", "calidad"],
}

calculadora = CalculadoraCostos()

GARANTIA_DIAS = 10
ENTREGA_DIAS  = 3   # días hábiles que tarda Droppers


# =============================================================
#  GENERADOR DE LISTINGS CON IA
# =============================================================

class GeneradorListings:
    def __init__(self, api_key):
        self.client = anthropic.Anthropic(api_key=api_key)

    def optimizar_para_ml(self, producto, categoria_ml, margen_pct,
                          envio_gratis=False, precio_competencia=None,
                          atributos_requeridos=None):
        keywords = KEYWORDS_CATEGORIAS.get(categoria_ml, KEYWORDS_CATEGORIAS["default"])
        attrs_str = ", ".join(atributos_requeridos) if atributos_requeridos else "BRAND"
        descripcion_droppers = producto.get("descripcion", "")

        prompt = f"""Sos un experto en SEO y ventas de Mercado Libre Argentina.

PRODUCTO:
- Título: {producto.get('titulo', '')}
- Descripción original de Droppers: {descripcion_droppers[:800] if descripcion_droppers else 'No disponible'}
- Categoría ML: {categoria_ml}
- Envío gratis: {"Sí" if envio_gratis else "No — entrega acordada con vendedor"}
- Keywords: {', '.join(keywords)}
{f"- Precio competencia: ${precio_competencia:,.0f}" if precio_competencia else ""}

CONDICIONES FIJAS:
- Garantía: {GARANTIA_DIAS} días del vendedor
- Entrega: 72 horas hábiles desde confirmación de pago
- Estado: nuevo

ATRIBUTOS REQUERIDOS POR ML: {attrs_str}

REGLAS:
1. TÍTULO: máximo 60 caracteres, sin puntuación innecesaria
2. DESCRIPCIÓN: 150-250 palabras. Basarte en la descripción original de Droppers si existe. Incluir garantía de {GARANTIA_DIAS} días y entrega en 72 horas hábiles
3. Para categorías de juguetes o productos infantiles, incluir información regulatoria (edad mínima, advertencias de seguridad, normas IRAM si aplica)
4. EAN: si el producto tiene código de barras conocido usarlo, sino usar "does_not_apply"
5. Completar TODOS los atributos requeridos

Devolvé SOLO JSON (sin texto adicional ni ```json):
{{
  "titulo": "título de hasta 60 caracteres",
  "descripcion": "descripción completa 150-250 palabras basada en descripción original",
  "ean": "does_not_apply",
  "informacion_regulatoria": "Completar solo si aplica para la categoría (ej juguetes: edad mínima 3 años, apto IRAM). Vacío si no aplica.",
  "atributos": [
    {{"id": "BRAND", "value_name": "Genérico"}}
  ],
  "score_estimado": 80
}}"""

        msg = self.client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}]
        )
        texto = msg.content[0].text.strip()
        inicio = texto.find("{")
        fin = texto.rfind("}") + 1
        return json.loads(texto[inicio:fin])

    def reescribir_si_baja_efectividad(self, item_id, titulo_actual,
                                        descripcion_actual, efectividad_pct, categoria):
        prompt = f"""Publicación ML con efectividad {efectividad_pct}% (necesita >66%).
TÍTULO: {titulo_actual}
DESCRIPCIÓN: {descripcion_actual[:300]}
CATEGORÍA: {categoria}
Devolvé SOLO JSON:
{{"problemas":[],"titulo_nuevo":"","descripcion_nueva":""}}"""
        msg = self.client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )
        texto = msg.content[0].text.strip()
        return json.loads(texto[texto.find("{"):texto.rfind("}")+1])


# =============================================================
#  MOTOR DE PUBLICACIÓN EN ML
# =============================================================

class PublicadorML:
    def __init__(self, ml_client, anthropic_key):
        self.ml         = ml_client
        self.generador  = GeneradorListings(anthropic_key)
        self.calculadora = CalculadoraCostos()

    def obtener_categoria_correcta(self, titulo):
        """Usa la API de ML para obtener la categoría hoja correcta."""
        try:
            sugerencia = self.ml.get("/sites/MLA/domain_discovery/search", params={
                "q": titulo[:50], "limit": 1
            })
            if sugerencia and len(sugerencia) > 0:
                return sugerencia[0].get("category_id", "")
        except:
            pass
        return ""

    def subir_imagen_a_ml(self, url_imagen):
        """Descarga una imagen y la sube a ML. Retorna el picture_id."""
        try:
            import requests as req
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            r = req.get(url_imagen, timeout=15, headers=headers)
            if r.status_code != 200:
                return None
            # Detectar tipo de imagen
            content_type = r.headers.get("Content-Type", "image/jpeg")
            if "png" in content_type:
                ext = "png"
            elif "webp" in content_type:
                ext = "webp"
            else:
                ext = "jpg"
            # Subir a ML Pictures API
            upload = self.ml.post_file(
                "/pictures/items/upload",
                files={"file": (f"imagen.{ext}", r.content, content_type)}
            )
            return upload.get("id")
        except Exception as e:
            return None

    def obtener_atributos_requeridos(self, categoria_id):
        """Obtiene los atributos obligatorios de una categoría."""
        try:
            attrs = self.ml.get(f"/categories/{categoria_id}/attributes")
            requeridos = []
            for a in attrs:
                tags = a.get("tags", {})
                if tags.get("required") or tags.get("catalog_required"):
                    requeridos.append(a.get("id", ""))
            return requeridos
        except:
            return ["BRAND"]

    def buscar_precio_competencia(self, titulo, categoria_id):
        """Busca el precio mediano de los competidores."""
        try:
            r = self.ml.get("/sites/MLA/search", params={
                "q": titulo[:40], "category": categoria_id,
                "limit": 10, "sort": "relevance",
            })
            precios = [i["price"] for i in r.get("results", []) if i.get("price")]
            if precios:
                precios_sorted = sorted(precios)
                return precios_sorted[len(precios_sorted) // 2]
        except:
            pass
        return None

    def calcular_precio_inteligente(self, costo, margen_min, margen_max, categoria_nombre,
                                    envio_gratis, precio_competencia, estrategia):
        """Calcula el precio óptimo según estrategia y rango de margen."""
        precio_con_margen_min = self.calculadora.calcular_precio_para_margen(
            costo, margen_min, categoria_nombre, envio_gratis
        )
        precio_con_margen_max = self.calculadora.calcular_precio_para_margen(
            costo, margen_max, categoria_nombre, envio_gratis
        )

        if not precio_competencia:
            # Sin competencia: usar margen medio
            margen_medio = (margen_min + margen_max) / 2
            precio_final = self.calculadora.calcular_precio_para_margen(
                costo, margen_medio, categoria_nombre, envio_gratis
            )
        elif estrategia == "volumen":
            # Máximo 5% bajo competencia, pero nunca bajo el margen mínimo
            precio_agresivo = precio_competencia * 0.95
            precio_final = max(precio_con_margen_min, precio_agresivo)
        elif estrategia == "margen":
            # Ignorar competencia, usar margen máximo
            precio_final = precio_con_margen_max
        else:
            # Competitivo: 3% bajo competencia, entre margen_min y margen_max
            precio_competitivo = precio_competencia * 0.97
            precio_final = max(precio_con_margen_min, min(precio_competitivo, precio_con_margen_max))

        precio_final = round(precio_final, 2)
        calculo = self.calculadora.calcular(precio_final, costo, categoria_nombre, envio_gratis)
        return {
            "precio": precio_final,
            "margen_real_pct": calculo["margen_neto_pct"],
            "ganancia_por_venta": calculo["ganancia_neta"],
            "desglose": calculo,
        }

    def publicar_producto(self, producto_droppers, config_publicacion):
        try:
            cat_nombre   = config_publicacion["categoria_nombre"]
            cat_id       = config_publicacion["categoria_id"]
            margen_min   = config_publicacion.get("margen_min", config_publicacion.get("margen_pct", 15))
            margen_max   = config_publicacion.get("margen_max", config_publicacion.get("margen_pct", 35))
            estrategia   = config_publicacion.get("estrategia", "competitivo")
            envio_gratis = config_publicacion.get("envio_gratis", False)
            costo        = producto_droppers.get("costo", 0) or config_publicacion.get("costo_droppers", 0)
            titulo_orig  = producto_droppers.get("titulo", "")

            if costo == 0:
                return {"ok": False, "error": f"Sin precio: {titulo_orig[:40]}"}

            # 1. Detectar categoría hoja correcta via API ML
            cat_id_sugerido = self.obtener_categoria_correcta(titulo_orig)
            if cat_id_sugerido:
                cat_id = cat_id_sugerido

            # 2. Obtener atributos requeridos por la categoría
            atributos_requeridos = self.obtener_atributos_requeridos(cat_id)

            # 3. Buscar precio de competencia
            precio_comp = self.buscar_precio_competencia(titulo_orig, cat_id)

            # 4. Calcular precio inteligente con rango de margen
            precio_info = self.calcular_precio_inteligente(
                costo, margen_min, margen_max, cat_nombre,
                envio_gratis, precio_comp, estrategia
            )
            precio_final = precio_info["precio"]

            # Precio mínimo de ML es $1000
            if precio_final < 1000:
                precio_final = 1000.0

            # 5. Generar listing con IA
            listing = self.generador.optimizar_para_ml(
                producto_droppers, cat_nombre, margen_min,
                envio_gratis, precio_comp, atributos_requeridos
            )

            # 6. Garantizar atributo BRAND siempre presente
            atributos_listing = listing.get("atributos", [])
            ids_presentes = [a.get("id") for a in atributos_listing]
            if "BRAND" not in ids_presentes:
                atributos_listing.insert(0, {"id": "BRAND", "value_name": "Genérico"})

            # Agregar EAN solo si es válido (numérico, 8+ dígitos)
            ean = listing.get("ean", "")
            if ean and ean.isdigit() and len(ean) >= 8:
                if "GTIN" not in ids_presentes:
                    atributos_listing.append({"id": "GTIN", "value_name": ean})

            # Agregar atributos requeridos que falten (solo BRAND y atributos simples)
            ATRIBUTOS_IGNORAR = {"VEHICLE_TYPE", "PRODUCT_TYPE", "AGE_GROUP", "MODEL"}
            for attr_id in atributos_requeridos:
                if attr_id not in [a.get("id") for a in atributos_listing]:
                    if attr_id not in ATRIBUTOS_IGNORAR:
                        atributos_listing.append({"id": attr_id, "value_name": "No especificado"})

            # 7. Condiciones de venta con garantía
            sale_terms = [
                {"id": "WARRANTY_TYPE", "value_name": "Garantía del vendedor"},
                {"id": "WARRANTY_TIME", "value_name": f"{GARANTIA_DIAS} días"},
            ]

            # 8. Descripción
            descripcion = listing.get("descripcion", "")
            if "72" not in descripcion and "hábil" not in descripcion:
                descripcion += f"\n\nENTREGA: Despachamos dentro de las 72 horas hábiles desde la confirmación del pago."
            info_reg = listing.get("informacion_regulatoria", "")
            if info_reg and len(info_reg) > 5:
                descripcion += f"\n\nINFORMACION REGULATORIA: {info_reg}"

            # 9. Subir imágenes a ML
            imagenes = []
            for url in producto_droppers.get("imagenes", [])[:6]:
                if url and url.startswith("http"):
                    picture_id = self.subir_imagen_a_ml(url)
                    if picture_id:
                        imagenes.append({"id": picture_id})
                    else:
                        imagenes.append({"source": url})

            # 10. Armar cuerpo (SIN description — se sube por endpoint separado)
            cuerpo = {
                "title":              listing["titulo"],
                "category_id":        cat_id,
                "price":              precio_final,
                "currency_id":        "ARS",
                "available_quantity": 1,
                "buying_mode":        "buy_it_now",
                "condition":          "new",
                "listing_type_id":    "bronze",
                "pictures":           imagenes,
                "shipping":           {"mode": "not_specified", "free_shipping": False},
                "sale_terms":         sale_terms,
                "attributes":         atributos_listing,
            }

            # 11. Publicar
            resultado = self.ml.post("/items", cuerpo)

            if resultado.get("id"):
                item_id = resultado["id"]

                # 12. Subir descripción por endpoint separado (requerido por ML)
                try:
                    self.ml.post(f"/items/{item_id}/description", {"plain_text": descripcion})
                except:
                    pass

                return {
                    "ok":         True,
                    "item_id":    item_id,
                    "titulo":     listing["titulo"],
                    "precio":     precio_final,
                    "margen_pct": precio_info["margen_real_pct"],
                    "ganancia":   precio_info["ganancia_por_venta"],
                    "permalink":  resultado.get("permalink", ""),
                    "score_ia":   listing.get("score_estimado", 0),
                }
            else:
                causas = resultado.get("cause", resultado.get("causes", []))
                errores = [c.get("message", c.get("code", "")) for c in causas] if causas else [resultado.get("message", "Error")]
                return {"ok": False, "error": " | ".join(errores[:2]), "detalle": resultado}

        except Exception as e:
            return {"ok": False, "error": str(e)}

    def publicar_masivo(self, productos, config_publicacion, callback=None):
        resultados = []
        total = len(productos)
        for i, producto in enumerate(productos):
            resultado = self.publicar_producto(producto, config_publicacion)
            resultados.append(resultado)
            if callback:
                callback(i + 1, total, resultado)
        exitosos = sum(1 for r in resultados if r.get("ok"))
        return {"total": total, "exitosos": exitosos,
                "fallidos": total - exitosos, "resultados": resultados}

    def monitorear_efectividad(self):
        try:
            items_data = self.ml.obtener_mis_publicaciones()
            item_ids   = items_data.get("results", [])
            reescritos = []
            for item_id in item_ids[:20]:
                try:
                    item  = self.ml.obtener_detalle_item(item_id)
                    salud = self.ml.get(f"/items/{item_id}/health")
                    score = salud.get("overall", {}).get("points", 100)
                    if score < 66:
                        nuevo = self.generador.reescribir_si_baja_efectividad(
                            item_id, item.get("title",""), "", score, item.get("category_id",""))
                        self.ml.post(f"/items/{item_id}", {
                            "title": nuevo["titulo_nuevo"],
                            "description": {"plain_text": nuevo["descripcion_nueva"]}
                        })
                        reescritos.append({"item_id": item_id, "score_anterior": score,
                                           "titulo_nuevo": nuevo["titulo_nuevo"]})
                except:
                    pass
            return reescritos
        except:
            return []
