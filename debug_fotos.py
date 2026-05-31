import requests, re
from bs4 import BeautifulSoup

BASE = 'https://droppers.com.ar'
session = requests.Session()
session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})

r = session.get('https://droppers.com.ar/reloj-muneca-oso-panda-blanco-y-negro-ninos-negro.html', timeout=15)
soup = BeautifulSoup(r.text, 'html.parser')

# Buscar todas las URLs de imagenes en el HTML
urls = re.findall(r'https?://droppers\.com\.ar/media/catalog/product[^\s"\']+', r.text)
urls = list(dict.fromkeys(urls))
print(f'URLs encontradas: {len(urls)}')
for u in urls[:10]:
    print(u)

# Buscar en scripts
scripts = soup.find_all('script')
for s in scripts:
    if 'media/catalog' in (s.string or ''):
        matches = re.findall(r'media/catalog/product[^\s"\'\\]+', s.string)
        if matches:
            print(f'En script: {matches[:5]}')
            break
