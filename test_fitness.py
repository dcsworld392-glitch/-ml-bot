import requests
from bs4 import BeautifulSoup

r = requests.get('https://droppers.com.ar/productos/fitness.html', 
    headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
soup = BeautifulSoup(r.text, 'html.parser')
links = [a['href'] for a in soup.find_all('a', href=True) 
         if a['href'].endswith('.html') and 'droppers.com.ar' in a['href']
         and '/productos/' not in a['href']]
print(f'Productos encontrados: {len(links)}')
for l in links[:5]:
    print(l)
