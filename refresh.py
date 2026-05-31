import requests, json
r = requests.post('https://api.mercadolibre.com/oauth/token', data={
    'grant_type': 'refresh_token',
    'client_id': '7554500472334410',
    'client_secret': 'QQboq4w62psB1rO3CvIhn6wUfctEzc7X',
    'refresh_token': 'TG-6a1ba52e9122240001879d15-211711561'
})
print(r.status_code)
d = r.json()
print('access_token:', d.get('access_token','ERROR'))
print('refresh_token:', d.get('refresh_token','ERROR'))
