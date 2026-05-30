import requests, json, re
from bs4 import BeautifulSoup

BASE = 'https://droppers.com.ar'
session = requests.Session()
session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})

r = session.get(f'{BASE}/customer/account/login/')
soup = BeautifulSoup(r.text, 'html.parser')
fk = soup.find('input', {'name': 'form_key'})
form_key = fk['value'] if fk else ''

session.post(f'{BASE}/customer/account/loginPost/', data={
    'form_key': form_key,
    'login[username]': 'dcsworld392@gmail.com',
    'login[password]': '220566494Fede@',
    'send': ''
})

with open(r'C:\Users\Feder\Desktop\mlbot\ml_bot\productos_droppers.json', 'r', encoding='utf-8') as f:
    productos = json.load(f)

r2 = session.get(productos[0]['url'], timeout=15)
print('URL:', productos[0]['url'])
print('Precio en HTML:', 'price' in r2.text.lower())
precios = re.findall(r'\$\s*[\d\.]+', r2.text)
print('Precios encontrados:', precios[:10])
print('HTML snippet:', r2.text[r2.text.find('price'):r2.text.find('price')+200] if 'price' in r2.text.lower() else 'NO HAY PRECIO')
