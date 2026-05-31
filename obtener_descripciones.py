import requests, json, re, time
from bs4 import BeautifulSoup

session = requests.Session()
session.headers.update({'User-Agent': 'Mozilla/5.0'})

with open(r'C:\Users\Feder\Desktop\mlbot\ml_bot\productos_droppers.json', 'r', encoding='utf-8') as f:
    productos = json.load(f)

actualizados = 0
for i, p in enumerate(productos):
    if p.get('url') and not p.get('descripcion'):
        try:
            r = session.get(p['url'], timeout=15)
            soup = BeautifulSoup(r.text, 'html.parser')
            desc = ''
            for sel in ['.product-info-main .product.attribute.description .value',
                        '.product.attribute.description .value',
                        '#description .value', '.product-description']:
                el = soup.select_one(sel)
                if el:
                    desc = el.get_text(strip=True)[:600]
                    break
            if desc:
                p['descripcion'] = desc
                actualizados += 1
                print(f'{i+1}. OK: {p["titulo"][:40]}')
            else:
                print(f'{i+1}. Sin desc: {p["titulo"][:40]}')
            time.sleep(0.3)
        except Exception as e:
            print(f'{i+1}. Error: {e}')

with open(r'C:\Users\Feder\Desktop\mlbot\ml_bot\productos_droppers.json', 'w', encoding='utf-8') as f:
    json.dump(productos, f, ensure_ascii=False, indent=2)
print(f'Descripciones agregadas: {actualizados}/{len(productos)}')
