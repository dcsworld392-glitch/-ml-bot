import requests, json, re, time
from bs4 import BeautifulSoup

BASE = 'https://droppers.com.ar'
session = requests.Session()
session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})

with open(r'C:\Users\Feder\Desktop\mlbot\ml_bot\productos_droppers.json', 'r', encoding='utf-8') as f:
    productos = json.load(f)

actualizados = 0
for i, p in enumerate(productos):
    if not p.get('url'):
        continue
    try:
        r = session.get(p['url'], timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')
        imagenes = []
        for img in soup.find_all('img'):
            src = img.get('src','')
            if '/media/catalog/product/' in src and 'placeholder' not in src:
                src = re.sub(r'/cache/[a-f0-9]{32}/', '/', src)
                if src.startswith('/'):
                    src = BASE + src
                if src not in imagenes:
                    imagenes.append(src)
        if imagenes:
            p['imagenes'] = imagenes[:6]
            actualizados += 1
            print(f'{i+1}. {p["titulo"][:40]} — {len(imagenes)} fotos')
        else:
            print(f'{i+1}. {p["titulo"][:40]} — sin fotos')
        time.sleep(0.3)
    except Exception as e:
        print(f'{i+1}. Error: {e}')

with open(r'C:\Users\Feder\Desktop\mlbot\ml_bot\productos_droppers.json', 'w', encoding='utf-8') as f:
    json.dump(productos, f, ensure_ascii=False, indent=2)
print(f'Fotos actualizadas: {actualizados}/{len(productos)}')
