import requests
from bs4 import BeautifulSoup

r = requests.get('https://droppers.com.ar/productos/fitness.html', 
    headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
soup = BeautifulSoup(r.text, 'html.parser')

# Ver todos los links que terminen en .html
todos = [a['href'] for a in soup.find_all('a', href=True) if '.html' in a['href']]
print(f'Total links: {len(todos)}')
for l in todos[:20]:
    print(l)
