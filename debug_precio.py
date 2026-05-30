import requests, re
from bs4 import BeautifulSoup

session = requests.Session()
session.headers.update({'User-Agent': 'Mozilla/5.0'})
r = session.get('https://droppers.com.ar/customer/account/login/')
soup = BeautifulSoup(r.text, 'html.parser')
fk = soup.find('input', {'name': 'form_key'})
session.post('https://droppers.com.ar/customer/account/loginPost/', data={
    'form_key': fk['value'] if fk else '',
    'login[username]': 'dcsworld392@gmail.com',
    'login[password]': '220566494Fede@',
    'send': ''
})

r2 = session.get('https://droppers.com.ar/reloj-muneca-oso-panda-blanco-y-negro-ninos-negro.html')
soup2 = BeautifulSoup(r2.text, 'html.parser')

# Buscar todos los spans con clase price
for el in soup2.find_all(class_=re.compile('price')):
    txt = el.get_text(strip=True)
    if txt and len(txt) < 20:
        print(repr(txt))
