import requests
import json

# Primero intercambiar codigo por token nuevo
r = requests.post('https://ml-bot-1c0d.onrender.com/api/intercambiar-codigo',
    json={'code': 'TG-6a1bfafc621247000105c371-211711561'},
    headers={'Content-Type': 'application/json'})
print('Intercambio:', r.text)

# Luego probar buscar publicaciones
import time; time.sleep(2)
r2 = requests.post('https://ml-bot-1c0d.onrender.com/api/mejorar-calidad')
print('Mejora:', r2.text[:300])
