import requests
token = 'APP_USR-7554500472334410-053023-0c1a436d5bd012e271784cafac2e2edb-211711561'
h = {'Authorization': 'Bearer ' + token}
r = requests.get('https://api.mercadolibre.com/users/211711561/items/search?status=active&limit=10', headers=h)
print(r.status_code)
print(r.text[:500])
