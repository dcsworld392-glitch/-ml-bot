import requests, json, time
from bs4 import BeautifulSoup

BASE = 'https://droppers.com.ar'
session = requests.Session()
session.headers.update({'User-Agent': 'Mozilla/5.0'})
r = session.get(f'{BASE}/customer/account/login/')
soup = BeautifulSoup(r.text, 'html.parser')
fk = soup.find('input', {'name': 'form_key'})
session.post(f'{BASE}/customer/account/loginPost/', data={
    'form_key': fk['value'] if fk else '',
    'login[username]': 'dcsworld392@gmail.com',
    'login[password]': '220566494Fede@', 'send': ''
})
print('Login OK')

with open(r'C:\Users\Feder\Desktop\mlbot\ml_bot\productos_droppers.json', 'r', encoding='utf-8') as f:
    productos = json.load(f)

actualizados = 0
for i, p in enumerate(productos):
    try:
        r = session.get(p['url'], timeout=15)
        soup2 = BeautifulSoup(r.text, 'html.parser')
        precio = 0
        for el in soup2.find_all(class_=lambda x: x and 'price' in x):
            txt = el.get_text(strip=True)
            txt = txt.replace('\xa0','').replace('$','').replace('.','').replace(',','.').strip()
            try:
                val = float(txt)
                if val > 100:
                    precio = val
                    break
            except: pass
        if precio > 0:
            p['costo'] = precio
            actualizados += 1
            print(f'{i+1}. {p["titulo"][:40]} = ')
        else:
            print(f'{i+1}. SIN PRECIO')
        time.sleep(0.2)
    except Exception as e:
        print(f'Error {i+1}: {e}')

with open(r'C:\Users\Feder\Desktop\mlbot\ml_bot\productos_droppers.json', 'w', encoding='utf-8') as f:
    json.dump(productos, f, ensure_ascii=False, indent=2)
print(f'Listos: {actualizados}/{len(productos)}')
