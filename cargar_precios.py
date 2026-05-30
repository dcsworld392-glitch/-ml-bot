import json

with open(r'C:\Users\Feder\Desktop\mlbot\ml_bot\productos_droppers.json', 'r', encoding='utf-8') as f:
    productos = json.load(f)

precios = {
    'Reloj': 4973,
    'Luz Led Bajo Alacena Placar': 3850,
    'Tender Ropa': 13490,
    'Jabonera': 5490,
    'Maquina De Tejer': 83500,
}

for p in productos:
    for nombre, precio in precios.items():
        if nombre.lower() in p['titulo'].lower():
            p['costo'] = precio
            print(f'OK: {p["titulo"][:50]} = ')

with open(r'C:\Users\Feder\Desktop\mlbot\ml_bot\productos_droppers.json', 'w', encoding='utf-8') as f:
    json.dump(productos, f, ensure_ascii=False, indent=2)
print('Guardado')
