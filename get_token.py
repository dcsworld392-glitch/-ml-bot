import requests, json
r = requests.post('https://api.mercadolibre.com/oauth/token', data={
    'grant_type': 'authorization_code',
    'client_id': '7554500472334410',
    'client_secret': 'QQboq4w62psB1rO3CvIhn6wUfctEzc7X',
    'code': 'TG-6a1bfbfa640408000173efb0-211711561',
    'redirect_uri': 'https://httpbin.org/get'
})
print(r.status_code)
print(r.text)
