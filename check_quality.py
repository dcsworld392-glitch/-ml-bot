import requests, json
token = 'APP_USR-7554500472334410-053023-0c1a436d5bd012e271784cafac2e2edb-211711561'
h = {'Authorization': 'Bearer ' + token}

r = requests.get('https://api.mercadolibre.com/users/211711561/items/search?limit=5', headers=h)
items = r.json().get('results', [])
print('Publicaciones:', len(items))

for item_id in items[:2]:
    health = requests.get('https://api.mercadolibre.com/items/' + item_id + '/health', headers=h)
    data = health.json()
    overall = data.get('overall', {})
    print('\n=== ' + item_id + ' === Puntaje: ' + str(overall.get('points', 0)))
    for section in data.get('sections', []):
        print('  ' + section.get('section_id','') + ': ' + str(section.get('points',0)) + '/' + str(section.get('total_points',0)))
        for tip in section.get('tips', []):
            print('    - ' + str(tip.get('tip','')))
