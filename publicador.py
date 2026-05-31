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

        prompt = f"""Sos un experto certificado en el algoritmo de Mercado Libre Argentina. Tu misión es crear publicaciones que alcancen el 80%+ de calidad según el sistema de puntuación de ML.

ALGORITMO DE PUNTUACIÓN DE ML (conocelo de memoria):
- Fotos: 25 pts → necesita mínimo 4 fotos
- Descripción: 20 pts → mínimo 150 palabras, keywords naturales, sin mayúsculas excesivas
- Características principales: 20 pts → mínimo 4 atributos técnicos completos y precisos
- Título: 15 pts → 60 chars exactos, keyword principal al inicio, sin puntuación
- Código universal: 10 pts → GTIN/EAN válido
- Garantía: 5 pts → ya configurada
- Tiempo disponibilidad: 5 pts → ya configurado

PRODUCTO A OPTIMIZAR:
- Título original: {producto.get('titulo', '')}
- Descripción de Droppers: {descripcion_droppers[:1000] if descripcion_droppers else 'No disponible'}
- Categoría ML: {categoria_ml}
- Atributos requeridos por ML: {attrs_str}
- Keywords más buscadas: {', '.join(keywords)}
- Envío gratis: {"Sí" if envio_gratis else "No — acordado con vendedor"}
{f"- Precio competencia referencia: ${precio_competencia:,.0f}" if precio_competencia else ""}

CONDICIONES FIJAS DE LA TIENDA:
- Garantía del vendedor: {GARANTIA_DIAS} días
- Entrega: 72 horas hábiles desde confirmación de pago (3 días hábiles)
- Condición: Nuevo
- Dropshipping: el producto se envía directo desde el proveedor

INSTRUCCIONES CRÍTICAS PARA MÁXIMA CALIDAD:
1. TÍTULO: exactamente 55-60 caracteres. Formato: [Producto] [Característica principal] [Material/Color] [Uso]. Keyword más buscada al inicio. Sin signos de puntuación. Sin palabras en mayúsculas innecesarias.
2. DESCRIPCIÓN: mínimo 200 palabras. Estructura: párrafo de beneficios (50 palabras) + características técnicas detalladas (80 palabras) + instrucciones de uso (40 palabras) + garantía y entrega (30 palabras). Usar saltos de línea. Incluir keywords de forma natural.
3. ATRIBUTOS: completar MÍNIMO 6 atributos con valores reales y precisos. Para cada atributo requerido en {attrs_str} dar un valor específico, no genérico. Si no sabés el valor exacto, estimá uno razonable basándote en el producto.
4. CARACTERÍSTICAS: incluir material, dimensiones aproximadas, color, peso estimado, uso principal, compatibilidad si aplica.

Devolvé SOLO JSON válido (sin markdown, sin texto extra):
{{
  "titulo": "título de 55-60 caracteres exactos con keyword al inicio",
  "descripcion": "descripción de mínimo 200 palabras con estructura y keywords",
  "atributos": [
    {{"id": "BRAND", "value_name": "Genérico"}},
    {{"id": "MODEL", "value_name": "modelo o referencia del producto"}},
    {{"id": "COLOR", "value_name": "color principal"}},
    {{"id": "MATERIAL", "value_name": "material principal"}},
    {{"id": "WITH_WARRANTY", "value_name": "Sí"}},
    {{"id": "PACKAGE_LENGTH", "value_name": "estimado en cm"}},
    {{"id": "PACKAGE_HEIGHT", "value_name": "estimado en cm"}},
    {{"id": "PACKAGE_WIDTH", "value_name": "estimado en cm"}},
    {{"id": "PACKAGE_WEIGHT", "value_name": "estimado en gramos"}}
  ],
  "informacion_regulatoria": "solo si aplica (juguetes: edad mínima X años, norma IRAM XXXX)",
  "score_estimado": 85
}}"""

        msg = self.client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1500,
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

    def buscar_competidores(self, titulo, categoria_id):
        """Busca competidores en ML y retorna datos completos."""
        try:
            r = self.ml.get("/sites/MLA/search", params={
                "q": titulo[:40], "category": categoria_id,
                "limit": 10, "sort": "relevance",
            })
            resultados = r.get("results", [])
            if not resultados:
                return {"precio_mediano": None, "competidores": [], "cantidad": 0}

            competidores = []
            precios = []
            for item in resultados:
                precio = item.get("price", 0)
                if precio > 0:
                    precios.append(precio)
                    competidores.append({
                        "titulo":    item.get("title", "")[:60],
                        "precio":    precio,
                        "vendedor":  item.get("seller", {}).get("nickname", ""),
                        "imagen":    item.get("thumbnail", ""),
                        "item_id":   item.get("id", ""),
                        "permalink": item.get("permalink", ""),
                        "condicion": item.get("condition", "new"),
                        "envio_gratis": item.get("shipping", {}).get("free_shipping", False),
                    })

            precio_mediano = None
            if precios:
                precios_sorted = sorted(precios)
                precio_mediano = precios_sorted[len(precios_sorted) // 2]

            return {
                "precio_mediano": precio_mediano,
                "precio_minimo":  min(precios) if precios else None,
                "precio_maximo":  max(precios) if precios else None,
                "competidores":   competidores[:5],
                "cantidad":       len(precios),
            }
        except:
            return {"precio_mediano": None, "competidores": [], "cantidad": 0}

    def buscar_precio_competencia(self, titulo, categoria_id):
        """Busca el precio mediano de los competidores (wrapper simple)."""
        return self.buscar_competidores(titulo, categoria_id).get("precio_mediano")

    def decidir_estrategia_marketing(self, precio_comp, cantidad_competidores,
                                      margen_disponible_pct, estrategia):
        """
        Decide qué herramienta de marketing usar según el contexto.
        Retorna la herramienta elegida y su costo estimado como % del precio.
        """
        # Reglas de decisión basadas en competencia y margen
        if margen_disponible_pct >= 25 and cantidad_competidores >= 10:
            # Mucha competencia y buen margen → publicidad para destacar
            return {"herramienta": "product_ads", "costo_pct": 0.07,
                    "label": "Product Ads (7% reservado para publicidad)"}
        elif margen_disponible_pct >= 20 and cantidad_competidores >= 5:
            # Competencia moderada → oferta relámpago ocasional
            return {"herramienta": "oferta_relampago", "costo_pct": 0.05,
                    "label": "Oferta relámpago (5% descuento estratégico)"}
        elif margen_disponible_pct >= 15 and estrategia == "volumen":
            # Estrategia volumen → precio agresivo sin marketing extra
            return {"herramienta": "precio_agresivo", "costo_pct": 0.03,
                    "label": "Precio agresivo (3% adicional para competir)"}
        else:
            # Margen justo → sin herramienta extra, precio competitivo básico
            return {"herramienta": "ninguna", "costo_pct": 0.0,
                    "label": "Sin herramienta extra — precio optimizado"}

    def calcular_precio_inteligente(self, costo, margen_min, margen_max, categoria_nombre,
                                    envio_gratis, precio_competencia, estrategia, cuotas=1):
        """
        Motor de decisión inteligente de precios.
        Analiza la competencia, elige herramienta de marketing si conviene,
        y calcula el precio óptimo dentro del rango mínimo-máximo.
        """
        # Buscar más datos de competencia para tomar decisión
        cantidad_competidores = 0
        try:
            r = self.ml.get("/sites/MLA/search", params={
                "q": "", "category": "", "limit": 20
            })
            # Aproximación — si hay precio de competencia, hay competidores
            cantidad_competidores = 8 if precio_competencia else 0
        except:
            cantidad_competidores = 5 if precio_competencia else 0

        # Calcular precio base con margen mínimo (incluyendo cuotas)
        precio_minimo = self.calculadora.calcular_precio_para_margen(
            costo, margen_min, categoria_nombre, envio_gratis, cuotas=cuotas
        )
        # Calcular precio con margen máximo
        precio_maximo = self.calculadora.calcular_precio_para_margen(
            costo, margen_max, categoria_nombre, envio_gratis, cuotas=cuotas
        )

        if not precio_minimo or not precio_maximo:
            precio_minimo = costo * 1.3
            precio_maximo = costo * 1.5

        # Decidir herramienta de marketing
        margen_medio = (margen_min + margen_max) / 2
        marketing = self.decidir_estrategia_marketing(
            precio_competencia, cantidad_competidores, margen_medio, estrategia
        )
        costo_marketing_pct = marketing["costo_pct"]

        # Calcular precio objetivo según estrategia
        if estrategia == "volumen":
            # Precio más agresivo posible — mínimo margen pero máxima competitividad
            if precio_competencia:
                precio_objetivo = precio_competencia * 0.93  # 7% bajo competencia
            else:
                precio_objetivo = precio_minimo
        elif estrategia == "margen":
            # Maximizar ganancia — usar margen máximo
            precio_objetivo = precio_maximo
        else:
            # Competitivo — 3-5% bajo mediana, ajustado por herramienta
            if precio_competencia:
                descuento = 0.03 + costo_marketing_pct
                precio_objetivo = precio_competencia * (1 - descuento)
            else:
                precio_objetivo = (precio_minimo + precio_maximo) / 2

        # Ajustar precio para cubrir el costo de marketing
        precio_con_marketing = precio_objetivo * (1 + costo_marketing_pct)

        # Respetar el rango mínimo-máximo
        precio_final = max(precio_minimo, min(precio_con_marketing, precio_maximo))
        precio_final = round(precio_final, 2)

        # Calcular métricas finales
        calculo = self.calculadora.calcular(
            precio_final, costo, categoria_nombre, envio_gratis, cuotas=cuotas
        )

        return {
            "precio":               precio_final,
            "margen_real_pct":      calculo["margen_neto_pct"],
            "ganancia_por_venta":   calculo["ganancia_neta"],
            "desglose":             calculo,
            "marketing":            marketing,
            "precio_competencia":   precio_competencia,
            "precio_minimo":        precio_minimo,
            "precio_maximo":        precio_maximo,
        }

    def publicar_producto(self, producto_droppers, config_publicacion):
        try:
            cat_nombre   = config_publicacion["categoria_nombre"]
            cat_id       = config_publicacion["categoria_id"]
            margen_min   = config_publicacion.get("margen_min", config_publicacion.get("margen_pct", 15))
            margen_max   = config_publicacion.get("margen_max", config_publicacion.get("margen_pct", 35))
            estrategia   = config_publicacion.get("estrategia", "competitivo")
            envio_gratis = config_publicacion.get("envio_gratis", False)
            cuotas       = config_publicacion.get("cuotas", 1)
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

            # 3. Buscar competidores completos
            datos_competencia = self.buscar_competidores(titulo_orig, cat_id)
            precio_comp = datos_competencia["precio_mediano"]

            # 4. Calcular precio inteligente con rango de margen y cuotas
            precio_info = self.calcular_precio_inteligente(
                costo, margen_min, margen_max, cat_nombre,
                envio_gratis, precio_comp, estrategia, cuotas
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

            # 7. SKU inteligente
            import re as _re
            palabras = _re.sub(r'[^a-zA-Z0-9\s]', '', titulo_orig).split()
            sku = "-".join(p[:4].upper() for p in palabras[:4]) + f"-{str(int(costo))[:4]}"
            if "SELLER_SKU" not in ids_presentes:
                atributos_listing.append({"id": "SELLER_SKU", "value_name": sku})

            # 8. Agregar atributos requeridos que falten
            ATRIBUTOS_IGNORAR = {"VEHICLE_TYPE", "PRODUCT_TYPE", "AGE_GROUP", "MODEL"}
            for attr_id in atributos_requeridos:
                if attr_id not in [a.get("id") for a in atributos_listing]:
                    if attr_id not in ATRIBUTOS_IGNORAR:
                        atributos_listing.append({"id": attr_id, "value_name": "No especificado"})

            # 9. Condiciones de venta con garantía
            sale_terms = [
                {"id": "WARRANTY_TYPE", "value_name": "Garantía del vendedor"},
                {"id": "WARRANTY_TIME", "value_name": f"{GARANTIA_DIAS} días"},
            ]

            # 10. Descripción
            descripcion = listing.get("descripcion", "")
            if "72" not in descripcion and "hábil" not in descripcion:
                descripcion += f"\n\nENTREGA: Despachamos dentro de las 72 horas hábiles desde la confirmación del pago."
            info_reg = listing.get("informacion_regulatoria", "")
            if info_reg and len(info_reg) > 5:
                descripcion += f"\n\nINFORMACION REGULATORIA: {info_reg}"

            # 11. Subir imágenes a ML
            imagenes = []
            for url in producto_droppers.get("imagenes", [])[:6]:
                if url and url.startswith("http"):
                    picture_id = self.subir_imagen_a_ml(url)
                    if picture_id:
                        imagenes.append({"id": picture_id})
                    else:
                        imagenes.append({"source": url})

            # 12. Configurar envío — fix para que envío gratis funcione
            if envio_gratis:
                shipping_config = {
                    "mode": "me2",
                    "free_shipping": True,
                }
            else:
                shipping_config = {
                    "mode": "not_specified",
                    "free_shipping": False,
                }

            # 13. Armar cuerpo
            cuerpo = {
                "title":              listing["titulo"],
                "category_id":        cat_id,
                "price":              precio_final,
                "currency_id":        "ARS",
                "available_quantity": 10,
                "buying_mode":        "buy_it_now",
                "condition":          "new",
                "listing_type_id":    "bronze",
                "pictures":           imagenes,
                "shipping":           shipping_config,
                "sale_terms":         sale_terms,
                "attributes":         atributos_listing,
            }

            # 14. Publicar
            resultado = self.ml.post("/items", cuerpo)

            if resultado.get("id"):
                item_id = resultado["id"]

                # 15. Subir descripción por endpoint separado
                try:
                    self.ml.post(f"/items/{item_id}/description", {"plain_text": descripcion})
                except:
                    pass

                return {
                    "ok":               True,
                    "item_id":          item_id,
                    "titulo":           listing["titulo"],
                    "precio":           precio_final,
                    "margen_pct":       precio_info["margen_real_pct"],
                    "ganancia":         precio_info["ganancia_por_venta"],
                    "permalink":        resultado.get("permalink", ""),
                    "score_ia":         listing.get("score_estimado", 0),
                    "marketing":        precio_info.get("marketing", {}).get("label", ""),
                    "precio_comp":      precio_comp,
                    "competidores":     datos_competencia.get("competidores", []),
                    "cant_competidores": datos_competencia.get("cantidad", 0),
                    "desglose": {
                        "costo_droppers":    costo,
                        "comision_ml":       precio_info["desglose"].get("comision_ml", 0),
                        "iva_iibb":          precio_info["desglose"].get("iva_comision", 0) + precio_info["desglose"].get("iibb", 0),
                        "cuotas":            precio_info["desglose"].get("costo_cuotas", 0),
                        "marketing_costo":   precio_final * precio_info.get("marketing", {}).get("costo_pct", 0),
                        "ganancia_neta":     precio_info["ganancia_por_venta"],
                        "margen_pct":        precio_info["margen_real_pct"],
                        "razon_margen":      f"Competencia ${precio_comp:,.0f}" if precio_comp else "Sin competencia — margen medio",
                    }
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
