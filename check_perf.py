import requests
token = 'APP_USR-7554500472334410-053105-d732c76d496f511cb0be176c088dc861-211711561'
h = {'Authorization': 'Bearer ' + token}
r = requests.get('https://api.mercadolibre.com/items/MLA1810729125/performance', headers=h)
print(r.status_code)
print(r.text[:1000])
