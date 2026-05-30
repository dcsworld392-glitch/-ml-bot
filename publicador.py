"""
=============================================================
  MÓDULO: PUBLICADOR INTELIGENTE CON IA
  Publica productos de Droppers en ML con títulos y precios
  optimizados para el algoritmo de Mercado Libre
=============================================================
"""

import os
import json
import re
import requests
import anthropic
from costos import CalculadoraCostos, COMISIONES_ML

# =============================================================
#  CONFIGURACIÓN DE PUBLICACIÓN
# =============================================================

# Comisiones ML por categoría para el cálculo de precios
CATEGORIAS_ML = {
    "Celulares y Smartphones":         "MLA1051",
    "Computación":                     "MLA1652",
    "Electrónica":                     "MLA1004",
    "Audio":                           "MLA1003",
    "Televisores":                     "MLA1002",
    "Cámaras y Accesorios":            "MLA1039",
    "Videojuegos":                     "MLA1144",
    "Electrodomésticos":               "MLA1574",
    "Herramientas":                    "MLA1511",
    "Hogar y Muebles":                 "MLA9201",
    "Ropa y Accesorios":               "MLA1430",
    "Deportes":                        "MLA1276",
    "Juguetes":                        "MLA5726",
    "Bebés":                           "MLA5726",
    "Salud y Belleza":                 "MLA1246",
    "Mascotas":                        "MLA1612",
    "Libros":                          "MLA3025",
    "Industrias y Oficinas":           "MLA1953",
    "Construcción":                    "MLA1459",
    "Accesorios para Autos":           "MLA1747",
    "Alimentos":                       "MLA1403",
}

# Palabras clave de alto impacto en ML por categoría
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


# =============================================================
#  GENERADOR DE LISTINGS CON IA
# =============================================================

class GeneradorListings:
    def __init__(self, api_key):
        self.client = anthropic.Anthropic(api_key=api_key)

    def optimizar_para_ml(self, producto_droppers, categoria_ml, margen_pct,
                           envio_gratis=False, precio_competencia=None):
        """
        Genera un listing 100% optimizado para el algoritmo de ML.
        Retorna título, descripción y atributos listos para publicar.
        """
        keywords = KEYWORDS_CATEGORIAS.get(categoria_ml, KEYWORDS_CATEGORIAS["default"])

        prompt = f"""Sos un experto en SEO y ventas de Mercado Libre Argentina con 10 años de experiencia.
Tu objetivo es crear publicaciones que aparezcan en los primeros resultados de búsqueda.

PRODUCTO A PUBLICAR:
{json.dumps(producto_droppers, ensure_ascii=False, indent=2)}

CATEGORÍA: {categoria_ml}
ENVÍO GRATIS: {"Sí" if envio_gratis else "No"}
KEYWORDS MÁS BUSCADAS EN ESTA CATEGORÍA: {', '.join(keywords)}
{f"PRECIO PROMEDIO DE COMPETENCIA: ${precio_competencia:,.0f}" if precio_competencia else ""}

REGLAS DEL ALGORITMO DE ML (CRÍTICO - seguir al pie de la letra):
1. TÍTULO: exactamente 60 caracteres o menos. Incluir marca + modelo + característica clave + 1 keyword. NO usar signos de puntuación innecesarios. NO usar "///" ni caracteres especiales.
2. El título es el factor #1 de posicionamiento. Debe sonar natural como búsqueda real.
3. La descripción debe tener mínimo 150 palabras con keywords distribuidas naturalmente.
4. Los atributos técnicos completos mejoran el ranking hasta un 40%.
5. {"Incluir 'Envío gratis' en el título mejora CTR un 35%" if envio_gratis else ""}

Devolvé SOLO un JSON válido con este formato exacto (sin texto adicional, sin ```json):
{{
  "titulo": "título de exactamente hasta 60 caracteres",
  "descripcion": "descripción de 150-250 palabras con keywords naturales, beneficios del producto, por qué comprarlo, garantía si aplica",
  "puntos_clave": ["beneficio 1", "beneficio 2", "beneficio 3", "beneficio 4", "beneficio 5"],
  "terminos_busqueda": ["término 1", "término 2", "término 3", "término 4", "término 5"],
  "score_estimado": 85
}}"""

        msg = self.client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        texto = msg.content[0].text.strip()
        inicio = texto.find("{")
        fin = texto.rfind("}") + 1
        return json.loads(texto[inicio:fin])

    def reescribir_si_baja_efectividad(self, item_id, titulo_actual, descripcion_actual,
                                        efectividad_pct, categoria):
        """Reescribe una publicación si la efectividad baja del 66%."""
        prompt = f"""Una publicación de Mercado Libre tiene efectividad de {efectividad_pct}% (necesita >66%).

TÍTULO ACTUAL: {titulo_actual}
DESCRIPCIÓN ACTUAL: {descripcion_actual[:300]}
CATEGORÍA: {categoria}

Identificá los problemas y generá versiones mejoradas. Devolvé SOLO JSON:
{{
  "problemas": ["problema 1", "problema 2"],
  "titulo_nuevo": "título mejorado hasta 60 caracteres",
  "descripcion_nueva": "descripción mejorada de 150-200 palabras"
}}"""

        msg = self.client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}]
        )
        texto = msg.content[0].text.strip()
        inicio = texto.find("{")
        fin = texto.rfind("}") + 1
        return json.loads(texto[inicio:fin])


# =============================================================
#  MOTOR DE PUBLICACIÓN EN ML
# =============================================================

class PublicadorML:
    def __init__(self, ml_client, anthropic_key):
        self.ml = ml_client
        self.generador = GeneradorListings(anthropic_key)
        self.calculadora = CalculadoraCostos()

    def buscar_precio_competencia(self, titulo, categoria_id):
        """Busca el precio promedio de los competidores mejor posicionados."""
        try:
            r = self.ml.get("/sites/MLA/search", params={
                "q": titulo[:40],
                "category": categoria_id,
                "limit": 10,
                "sort": "relevance",
            })
            precios = [item["price"] for item in r.get("results", []) if item.get("price")]
            if precios:
                # Excluir outliers y tomar la mediana
                precios_sorted = sorted(precios)
                n = len(precios_sorted)
                return precios_sorted[n // 2]
        except:
            pass
        return None

    def calcular_precio_publicacion(self, costo_droppers, margen_pct, categoria_nombre,
                                     envio_gratis, precio_competencia=None):
        """
        Calcula el precio óptimo de publicación considerando:
        - Margen deseado
        - Precio de competencia
        - Si ofrece envío gratis
        """
        # Precio mínimo para mantener el margen
        precio_minimo = self.calculadora.calcular_precio_para_margen(
            costo_droppers, margen_pct, categoria_nombre, envio_gratis
        )

        if not precio_competencia:
            return precio_minimo

        # Estrategia: estar 3-5% por debajo del competidor mediano
        # pero nunca por debajo del precio mínimo con margen
        precio_competitivo = precio_competencia * 0.97

        precio_final = max(precio_minimo, precio_competitivo)

        # Calcular margen real con el precio final
        calculo = self.calculadora.calcular(precio_final, costo_droppers, categoria_nombre, envio_gratis)

        return {
            "precio": round(precio_final, 2),
            "margen_real_pct": calculo["margen_neto_pct"],
            "ganancia_por_venta": calculo["ganancia_neta"],
            "desglose": calculo,
        }

    def publicar_producto(self, producto_droppers, config_publicacion):
        """
        Publica un producto en ML con optimización de IA.

        config_publicacion = {
            "categoria_nombre":  "Electrónica",
            "categoria_id":      "MLA1000",
            "margen_pct":        25,        # % de ganancia deseado
            "envio_gratis":      True,
            "tamaño_envio":      "mediano",
            "costo_droppers":    5000,
        }
        """
        try:
            cat_nombre = config_publicacion["categoria_nombre"]
            cat_id     = config_publicacion["categoria_id"]
            margen_pct = config_publicacion["margen_pct"]
            envio_gratis = config_publicacion.get("envio_gratis", False)
            # Usar el costo del producto individual, no el del config global
            costo = producto_droppers.get("costo", 0) or config_publicacion.get("costo_droppers", 0)

            # Si no hay costo, no podemos calcular el precio
            if costo == 0:
                return {"ok": False, "error": "Producto sin precio de costo — cargá el precio en Droppers"}

            # Buscar categoría ML sugerida por la API según el título
            try:
                sugerencia = self.ml.get("/sites/MLA/domain_discovery/search", params={
                    "q": producto_droppers.get("titulo","")[:50],
                    "limit": 1
                })
                if sugerencia and len(sugerencia) > 0:
                    cat_id_sugerido = sugerencia[0].get("category_id", cat_id)
                    if cat_id_sugerido:
                        cat_id = cat_id_sugerido
            except:
                pass

            # 1. Buscar precio de competencia
            precio_comp = self.buscar_precio_competencia(
                producto_droppers.get("titulo", ""), cat_id
            )

            # 2. Calcular precio óptimo
            precio_info = self.calcular_precio_publicacion(
                costo, margen_pct, cat_nombre, envio_gratis, precio_comp
            )
            precio_final = precio_info["precio"] if isinstance(precio_info, dict) else precio_info

            # 3. Generar listing optimizado con IA
            listing = self.generador.optimizar_para_ml(
                producto_droppers, cat_nombre, margen_pct, envio_gratis, precio_comp
            )

            # 4. Armar el cuerpo de la publicación para ML
            condicion = "new"
            tipo_listing = "free"  # free = gratis, siempre empezar así en cuenta nueva

            cuerpo = {
                "title":            listing["titulo"],
                "category_id":      cat_id,
                "price":            precio_final,
                "currency_id":      "ARS",
                "available_quantity": producto_droppers.get("stock", 10),
                "buying_mode":      "buy_it_now",
                "condition":        condicion,
                "listing_type_id":  tipo_listing,
                "description": {
                    "plain_text": listing["descripcion"]
                },
                "pictures": [
                    {"source": url} for url in producto_droppers.get("imagenes", [])[:6]
                    if url and url.startswith("http")
                ],
                "shipping": {
                    "mode": "not_specified",
                },
                "sale_terms": [],
                "attributes":  producto_droppers.get("atributos", []),
            }

            # 5. Publicar en ML
            resultado = self.ml.post("/items", cuerpo)

            if resultado.get("id"):
                return {
                    "ok":           True,
                    "item_id":      resultado["id"],
                    "titulo":       listing["titulo"],
                    "precio":       precio_final,
                    "margen_pct":   precio_info["margen_real_pct"] if isinstance(precio_info, dict) else margen_pct,
                    "ganancia":     precio_info["ganancia_por_venta"] if isinstance(precio_info, dict) else 0,
                    "envio_gratis": envio_gratis,
                    "score_ia":     listing.get("score_estimado", 0),
                    "permalink":    resultado.get("permalink", ""),
                }
            else:
                return {"ok": False, "error": resultado.get("message", "Error desconocido"), "detalle": resultado}

        except Exception as e:
            return {"ok": False, "error": str(e)}

    def publicar_masivo(self, productos, config_publicacion, callback=None):
        """
        Publica una lista de productos.
        callback(progreso, total, resultado) se llama por cada publicación.
        """
        resultados = []
        total = len(productos)

        for i, producto in enumerate(productos):
            resultado = self.publicar_producto(producto, config_publicacion)
            resultados.append(resultado)

            if callback:
                callback(i + 1, total, resultado)

        exitosos = sum(1 for r in resultados if r.get("ok"))
        return {
            "total":     total,
            "exitosos":  exitosos,
            "fallidos":  total - exitosos,
            "resultados": resultados,
        }

    def monitorear_efectividad(self):
        """
        Revisa todas las publicaciones activas y reescribe las que
        tienen efectividad menor al 66%.
        """
        try:
            uid = self.ml.cfg["ML_USER_ID"]
            items_data = self.ml.obtener_mis_publicaciones()
            item_ids = items_data.get("results", [])
            reescritos = []

            for item_id in item_ids[:20]:  # revisar hasta 20 por ciclo
                try:
                    item = self.ml.obtener_detalle_item(item_id)
                    salud = self.ml.get(f"/items/{item_id}/health")
                    score = salud.get("overall", {}).get("points", 100)

                    if score < 66:
                        nuevo = self.generador.reescribir_si_baja_efectividad(
                            item_id, item.get("title",""), "",
                            score, item.get("category_id","")
                        )
                        # Actualizar título en ML
                        self.ml.post(f"/items/{item_id}", {
                            "title": nuevo["titulo_nuevo"],
                            "description": {"plain_text": nuevo["descripcion_nueva"]}
                        })
                        reescritos.append({"item_id": item_id, "score_anterior": score, "titulo_nuevo": nuevo["titulo_nuevo"]})
                except:
                    pass

            return reescritos
        except Exception as e:
            return []
