"""
=============================================================
  MÓDULO: MOTOR DE COSTOS E IMPUESTOS
  Calcula la ganancia neta real por cada venta en ML
=============================================================
"""

# =============================================================
#  TABLA DE COMISIONES ML POR CATEGORÍA (actualizada 2026)
# =============================================================

COMISIONES_ML = {
    # Electrónica
    "Celulares y Teléfonos":           0.13,
    "Computación":                     0.13,
    "Electrónica, Audio y Video":      0.13,
    "Cámaras y Accesorios":            0.13,
    "Videojuegos y Consolas":          0.13,
    # Hogar
    "Electrodomésticos":               0.13,
    "Herramientas":                    0.165,
    "Hogar, Muebles y Jardín":         0.165,
    # Ropa
    "Ropa y Accesorios":               0.165,
    "Deportes y Fitness":              0.165,
    "Relojes y Joyas":                 0.165,
    # Otros
    "Juegos y Juguetes":               0.165,
    "Bebés":                           0.165,
    "Salud y Equipamiento Médico":     0.165,
    "Belleza y Cuidado Personal":      0.165,
    "Alimentos y Bebidas":             0.165,
    "Mascotas":                        0.165,
    "Libros, Revistas y Comics":       0.165,
    "Música, Películas y Series":      0.165,
    "Industrias y Oficinas":           0.165,
    "Construcción":                    0.165,
    "Accesorios para Vehículos":       0.13,
    "Autos, Motos y Otros":            0.03,   # categoría especial
    "default":                         0.145,  # categoría no mapeada
}

# Costo de cuotas ML (costo financiero que absorbe el vendedor)
CUOTAS_ML = {
    1:  {"costo_pct": 0.000, "label": "1 cuota — sin costo extra"},
    3:  {"costo_pct": 0.075, "label": "3 cuotas — 7.5% extra"},
    6:  {"costo_pct": 0.145, "label": "6 cuotas — 14.5% extra"},
    9:  {"costo_pct": 0.190, "label": "9 cuotas — 19% extra"},
    12: {"costo_pct": 0.230, "label": "12 cuotas — 23% extra"},
}
COSTO_ENVIO_PROMEDIO = {
    "pequeño":  1200,   # hasta 1kg
    "mediano":  2500,   # 1 a 5kg
    "grande":   4500,   # más de 5kg
    "default":  2000,
}

# Impuestos estimados para monotributista
IMPUESTOS = {
    "iva_sobre_comision":   0.21,    # IVA sobre la comisión de ML
    "iibb":                 0.03,    # Ingresos Brutos promedio CABA/PBA
    "percepcion_ml":        0.005,   # percepción que retiene ML
}


# =============================================================
#  CALCULADORA DE GANANCIA NETA
# =============================================================

class CalculadoraCostos:

    def calcular(self, precio_venta, costo_droppers, categoria="default",
                 envio_gratis=False, tamaño_envio="default", cuotas=1):
        """
        Calcula todos los costos y la ganancia neta real.
        Retorna un dict con el desglose completo.
        """
        # 1. Comisión ML
        tasa_comision = COMISIONES_ML.get(categoria, COMISIONES_ML["default"])
        comision_ml = precio_venta * tasa_comision

        # 2. IVA sobre comisión
        iva_comision = comision_ml * IMPUESTOS["iva_sobre_comision"]

        # 3. Percepción ML
        percepcion = precio_venta * IMPUESTOS["percepcion_ml"]

        # 4. Ingresos Brutos
        iibb = precio_venta * IMPUESTOS["iibb"]

        # 5. Costo de envío
        costo_envio = COSTO_ENVIO_PROMEDIO.get(tamaño_envio, COSTO_ENVIO_PROMEDIO["default"]) if envio_gratis else 0

        # 6. Costo de cuotas
        costo_cuotas_pct = CUOTAS_ML.get(cuotas, CUOTAS_ML[1])["costo_pct"]
        costo_cuotas = precio_venta * costo_cuotas_pct

        # 7. Total costos
        total_costos = costo_droppers + comision_ml + iva_comision + percepcion + iibb + costo_envio + costo_cuotas

        # 8. Ganancia neta
        ganancia_neta = precio_venta - total_costos

        # 9. Margen neto %
        margen_neto = (ganancia_neta / precio_venta * 100) if precio_venta > 0 else 0

        return {
            "precio_venta":      round(precio_venta, 2),
            "costo_droppers":    round(costo_droppers, 2),
            "comision_ml":       round(comision_ml, 2),
            "tasa_comision_pct": round(tasa_comision * 100, 1),
            "iva_comision":      round(iva_comision, 2),
            "percepcion_ml":     round(percepcion, 2),
            "iibb":              round(iibb, 2),
            "costo_envio":       round(costo_envio, 2),
            "costo_cuotas":      round(costo_cuotas, 2),
            "cuotas":            cuotas,
            "total_costos":      round(total_costos, 2),
            "ganancia_neta":     round(ganancia_neta, 2),
            "margen_neto_pct":   round(margen_neto, 1),
            "categoria":         categoria,
            "envio_gratis":      envio_gratis,
        }

    def calcular_precio_para_margen(self, costo_droppers, margen_deseado_pct,
                                     categoria="default", envio_gratis=False,
                                     tamaño_envio="default", cuotas=1):
        tasa_comision = COMISIONES_ML.get(categoria, COMISIONES_ML["default"])
        costo_envio = COSTO_ENVIO_PROMEDIO.get(tamaño_envio, COSTO_ENVIO_PROMEDIO["default"]) if envio_gratis else 0
        costo_cuotas_pct = CUOTAS_ML.get(cuotas, CUOTAS_ML[1])["costo_pct"]

        costos_proporcionales = (
            tasa_comision +
            tasa_comision * IMPUESTOS["iva_sobre_comision"] +
            IMPUESTOS["percepcion_ml"] +
            IMPUESTOS["iibb"] +
            costo_cuotas_pct
        )

        margen_decimal = margen_deseado_pct / 100
        denominador = 1 - costos_proporcionales - margen_decimal

        if denominador <= 0:
            return None

        precio = (costo_droppers + costo_envio) / denominador
        return round(precio, 2)

    def resumen_venta(self, orden_ml, costo_droppers, categoria="default", envio_gratis=False):
        """Calcula ganancia de una orden real de ML."""
        precio_venta = orden_ml.get("total_amount", 0)
        return self.calcular(precio_venta, costo_droppers, categoria, envio_gratis)


# =============================================================
#  REGISTRO DE COSTOS POR PRODUCTO
# =============================================================

class RegistroCostos:
    """
    Guarda el costo de cada producto para poder calcular
    la ganancia cuando se vende.
    """

    def __init__(self):
        self.costos = {}  # {item_id: {"costo": 1500, "categoria": "...", "envio_gratis": False}}

    def registrar(self, item_id, costo, categoria="default", envio_gratis=False, tamaño_envio="default"):
        self.costos[item_id] = {
            "costo":        costo,
            "categoria":    categoria,
            "envio_gratis": envio_gratis,
            "tamaño_envio": tamaño_envio,
        }

    def obtener(self, item_id):
        return self.costos.get(item_id, {
            "costo":        0,
            "categoria":    "default",
            "envio_gratis": False,
            "tamaño_envio": "default",
        })

    def listar(self):
        return self.costos


# Instancia global
calculadora = CalculadoraCostos()
registro_costos = RegistroCostos()
