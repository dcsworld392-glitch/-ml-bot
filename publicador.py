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

    def decidir_precio_con_ia(self, producto, costo, margen_min, margen_max,
                               categoria_nombre, envio_gratis, datos_competencia,
                               estrategia, cuotas):
        """Usa Claude para decidir el precio óptimo y herramienta de marketing."""
        try:
            competidores_txt = ""
            if datos_competencia.get("competidores"):
                competidores_txt = "\n".join([
                    f"- {c['titulo'][:50]}: ${c['precio']:,.0f} ({'envío gratis' if c['envio_gratis'] else 'sin envío gratis'})"
                    for c in datos_competencia["competidores"][:5]
                ])

            precio_min_calc = self.calculadora.calcular_precio_para_margen(
                costo, margen_min, categoria_nombre, envio_gratis, cuotas=cuotas
            ) or costo * 1.2
            precio_max_calc = self.calculadora.calcular_precio_para_margen(
                costo, margen_max, categoria_nombre, envio_gratis, cuotas=cuotas
            ) or costo * 1.5

            prompt = f"""Sos un experto en pricing para Mercado Libre Argentina. Analizá esta situación y decidí el precio óptimo.

PRODUCTO: {producto.get('titulo', '')}
COSTO (Droppers): ${costo:,.0f}
CATEGORÍA: {categoria_nombre}
ESTRATEGIA ELEGIDA: {estrategia}
CUOTAS: {cuotas} cuotas sin interés
ENVÍO GRATIS: {'Sí' if envio_gratis else 'No'}

RANGO DE PRECIO PERMITIDO:
- Precio mínimo (margen {margen_min}%): ${precio_min_calc:,.0f}
- Precio máximo (margen {margen_max}%): ${precio_max_calc:,.0f}

COMPETENCIA EN ML:
- Precio mediano: ${datos_competencia.get('precio_mediano') or 'Sin datos'}
- Precio mínimo competencia: ${datos_competencia.get('precio_minimo') or 'Sin datos'}
- Cantidad de vendedores: {datos_competencia.get('cantidad', 0)}
- Top competidores:
{competidores_txt or 'Sin competidores encontrados'}

HERRAMIENTAS DE MARKETING DISPONIBLES:
1. Product Ads (publicidad paga por clic) — reservar 7% del precio para publicidad → mayor visibilidad
2. Oferta relámpago (descuento temporal) — reducir precio 5% por tiempo limitado → más ventas rápidas
3. Sin herramienta — precio competitivo directo

Decidí:
1. El precio exacto dentro del rango permitido
2. La herramienta de marketing más conveniente
3. La razón de tu decisión en una línea

Devolvé SOLO JSON:
{{"precio": 12500, "herramienta": "product_ads", "costo_marketing_pct": 0.07, "razon": "Precio 5% bajo mediana para entrar al mercado con publicidad"}}"""

            import anthropic as _ant
            client = _ant.Anthropic(api_key=self.generador.client.api_key)
            msg = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}]
            )
            texto = msg.content[0].text.strip()
            resultado = json.loads(texto[texto.find("{"):texto.rfind("}")+1])

            precio_final = float(resultado.get("precio", precio_min_calc))
            # Respetar el rango
            precio_final = max(precio_min_calc, min(precio_final, precio_max_calc))
            precio_final = round(precio_final, 2)

            calculo = self.calculadora.calcular(
                precio_final, costo, categoria_nombre, envio_gratis, cuotas=cuotas
            )
            return {
                "precio":             precio_final,
                "margen_real_pct":    calculo["margen_neto_pct"],
                "ganancia_por_venta": calculo["ganancia_neta"],
                "desglose":           calculo,
                "marketing": {
                    "herramienta": resultado.get("herramienta", "ninguna"),
                    "costo_pct":   resultado.get("costo_marketing_pct", 0),
                    "label":       resultado.get("razon", ""),
                },
            }
        except Exception as e:
            # Fallback al motor clásico si la IA falla
            return self.calcular_precio_inteligente(
                costo, margen_min, margen_max, categoria_nombre,
                envio_gratis, datos_competencia.get("precio_mediano"),
                estrategia, cuotas
            )
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

            # 4. Calcular precio con IA
            precio_info = self.decidir_precio_con_ia(
                producto_droppers, costo, margen_min, margen_max,
                cat_nombre, envio_gratis, datos_competencia,
                estrategia, cuotas
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
                "listing_type_id":    "gold_special",
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

    def mejorar_calidad_publicacion(self, item_id, item_data, health_data):
        """
        Motor inteligente de mejora de calidad.
        Usa incomplete_technical_specs para saber exactamente qué falta,
        igual que el editor manual de ML.
        """
        try:
            score = health_data.get("overall", {}).get("points", 0)
            if score >= 75:
                return {"ok": True, "item_id": item_id, "score": score, "accion": "ya_ok"}

            titulo_actual = item_data.get("title", "")
            categoria_id = item_data.get("category_id", "")
            attrs_actuales = item_data.get("attributes", [])

            # 1. Obtener specs técnicas incompletas — igual que el editor de ML
            specs_incompletas = []
            try:
                r = self.ml.get(f"/items/{item_id}/technical_specs/input")
                groups = r.get("groups", [])
                for group in groups:
                    for comp in group.get("components", []):
                        for attr in comp.get("attributes", []):
                            if attr.get("tag") in ["required", "conditional_required"] or \
                               not attr.get("value_id") and not attr.get("value_name"):
                                specs_incompletas.append({
                                    "id": attr.get("id"),
                                    "name": attr.get("name", ""),
                                    "hint": attr.get("hint", ""),
                                    "values": [v.get("name") for v in attr.get("allowed_values", [])[:5]],
                                })
            except:
                pass

            # 2. Obtener atributos requeridos por categoría
            atributos_requeridos = []
            try:
                r = self.ml.get(f"/categories/{categoria_id}/attributes")
                for a in r:
                    tags = a.get("tags", {})
                    if tags.get("required") or tags.get("catalog_required"):
                        atributos_requeridos.append({
                            "id": a["id"],
                            "name": a.get("name", ""),
                            "values": [v.get("name") for v in a.get("allowed_values", [])[:5]],
                        })
            except:
                pass

            # 3. Obtener descripción actual
            desc_actual = ""
            try:
                desc_data = self.ml.get(f"/items/{item_id}/description")
                desc_actual = desc_data.get("plain_text", "") or desc_data.get("text", "")
            except:
                pass

            # 4. Analizar buckets del performance
            buckets = health_data.get("sections", [])
            problemas = []
            mejoras = {}
            for b in buckets:
                pts = b.get("points", 0)
                total = b.get("total_points", 100)
                key = b.get("section_id", "")
                if pts < total * 0.7:
                    tips = [v.get("title", "") for v in b.get("tips", []) if v.get("status") == "PENDING"]
                    problemas.append(f"{key} ({pts}/{total}): {', '.join(tips[:2])}")
                    if key == "DESCRIPTION": mejoras["descripcion"] = True
                    if key == "MAIN_FEATURES": mejoras["atributos"] = True

            # 5. Prompt muy específico con datos reales de ML
            specs_txt = "\n".join([
                f"- {s['id']} ({s['name']}): opciones posibles: {', '.join(s['values']) if s['values'] else 'valor libre'}"
                for s in specs_incompletas[:15]
            ]) or "No se pudieron obtener specs"

            reqs_txt = "\n".join([
                f"- {a['id']} ({a['name']}): {', '.join(a['values']) if a['values'] else 'valor libre'}"
                for a in atributos_requeridos[:10]
            ]) or "Sin atributos requeridos"

            attrs_txt = "\n".join([
                f"- {a.get('id')}: {a.get('value_name','')}"
                for a in attrs_actuales[:10]
            ]) or "Ninguno"

            prompt = f"""Sos un experto en el algoritmo de calidad de Mercado Libre Argentina.
Mejorá esta publicación para que llegue al 80%+ de calidad.

PUBLICACIÓN:
- Título: {titulo_actual}
- Categoría: {categoria_id}
- Score actual: {score}%

ATRIBUTOS ACTUALES:
{attrs_txt}

DESCRIPCIÓN ACTUAL:
{desc_actual[:400] if desc_actual else "SIN DESCRIPCIÓN"}

SPECS TÉCNICAS INCOMPLETAS (las que pide ML en su editor):
{specs_txt}

ATRIBUTOS REQUERIDOS POR CATEGORÍA:
{reqs_txt}

PROBLEMAS DETECTADOS:
{chr(10).join(problemas) if problemas else "Sin datos"}

INSTRUCCIONES:
1. Completar TODOS los atributos de las specs incompletas con valores REALES inferidos del título
2. Usar EXACTAMENTE los valores permitidos cuando se listen opciones (ej: si dice "Negro, Blanco, Azul", usar uno de esos)
3. Título: 55-60 chars, keyword al inicio
4. Descripción: 200+ palabras, características técnicas, garantía 10 días, entrega 72hs hábiles

Devolvé SOLO JSON válido:
{{
  "titulo_nuevo": "título 55-60 chars",
  "descripcion_nueva": "descripción 200+ palabras",
  "atributos_nuevos": [
    {{"id": "BRAND", "value_name": "Generico"}},
    {{"id": "COLOR", "value_name": "valor real del título"}},
    {{"id": "MATERIAL", "value_name": "valor real inferido"}},
    {{"id": "WITH_WARRANTY", "value_name": "Si"}},
    {{"id": "SELLER_SKU", "value_name": "SKU-AUTO"}}
  ],
  "razon": "qué se mejoró en una línea",
  "score_estimado": 82
}}"""

            import anthropic as _ant
            client = _ant.Anthropic(api_key=self.generador.client.api_key)
            msg = client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )
            texto = msg.content[0].text.strip()
            mejora = json.loads(texto[texto.find("{"):texto.rfind("}")+1])

            # 6. Aplicar mejoras
            updates = {}
            titulo_nuevo = mejora.get("titulo_nuevo", "")
            if titulo_nuevo and titulo_nuevo != titulo_actual:
                updates["title"] = titulo_nuevo[:60]

            atributos_nuevos = mejora.get("atributos_nuevos", [])
            if atributos_nuevos:
                attrs_map = {a.get("id"): a for a in attrs_actuales}
                for a in atributos_nuevos:
                    v = a.get("value_name", "")
                    if v and v not in ["No especificado", "valor real del título", "valor real inferido", "SKU-AUTO"]:
                        attrs_map[a["id"]] = a
                    elif a["id"] == "SELLER_SKU":
                        # Generar SKU real
                        import re as _re
                        palabras = _re.sub(r'[^a-zA-Z0-9\s]', '', titulo_actual).split()
                        sku = "-".join(p[:4].upper() for p in palabras[:3]) + f"-{item_id[-4:]}"
                        attrs_map["SELLER_SKU"] = {"id": "SELLER_SKU", "value_name": sku}
                updates["attributes"] = list(attrs_map.values())

            if updates:
                try:
                    resp_put = self.ml.put(f"/items/{item_id}", updates)
                    if isinstance(resp_put, dict) and resp_put.get("error"):
                        return {"ok": False, "item_id": item_id, "error": f"ML rechazó PUT: {resp_put.get('message','')}", "resp": str(resp_put)[:300]}
                except Exception as e_put:
                    return {"ok": False, "item_id": item_id, "error": f"Error PUT items: {str(e_put)}"}

            # 7. Actualizar descripción
            desc_nueva = mejora.get("descripcion_nueva", "")
            if desc_nueva and mejoras.get("descripcion"):
                try:
                    if desc_actual:
                        self.ml.put(f"/items/{item_id}/description", {"plain_text": desc_nueva})
                    else:
                        self.ml.post(f"/items/{item_id}/description", {"plain_text": desc_nueva})
                except:
                    try:
                        self.ml.post(f"/items/{item_id}/description", {"plain_text": desc_nueva})
                    except:
                        pass

            return {
                "ok": True,
                "item_id": item_id,
                "score_anterior": score,
                "score_estimado": mejora.get("score_estimado", 82),
                "titulo_nuevo": titulo_nuevo,
                "mejoras_aplicadas": list(mejoras.keys()),
                "razon": mejora.get("razon", ""),
            }

        except Exception as e:
            return {"ok": False, "item_id": item_id, "error": str(e)}

    def ciclo_mejora_calidad(self, meta_score=75):
        """
        Revisa todas las publicaciones activas y mejora las que están bajo la meta.
        Corre automáticamente cada hora.
        """
        try:
            # Obtener mis publicaciones activas
            items_data = self.ml.get(f"/users/{self.ml.cfg.get('ML_USER_ID', '')}/items/search",
                                     params={"status": "active", "limit": 50})
            item_ids = items_data.get("results", [])
            if not item_ids:
                return []

            mejorados = []
            for item_id in item_ids:
                try:
                    # Obtener health score
                    health = self.ml.get(f"/items/{item_id}/health")
                    score = health.get("overall", {}).get("points", 100)

                    if score < meta_score:
                        # Obtener datos del item
                        item_data = self.ml.get(f"/items/{item_id}")
                        resultado = self.mejorar_calidad_publicacion(item_id, item_data, health)
                        if resultado.get("ok"):
                            mejorados.append(resultado)
                except:
                    pass

            return mejorados
        except Exception as e:
            return []

    def monitorear_efectividad(self):
        """Wrapper para compatibilidad — usa el nuevo ciclo de mejora."""
        return self.ciclo_mejora_calidad(meta_score=75)
