@echo off
echo Simple's - Actualizador de precios %date% %time%
cd /d "C:\Users\Feder\Desktop\mlbot\ml_bot"
echo Obteniendo precios de Droppers...
python obtener_precios.py
git add productos_droppers.json
git commit -m "precios droppers auto %date%"
git push --force origin main
python -c "import requests,json,time; p=json.load(open('productos_droppers.json',encoding='utf-8')); time.sleep(5); r=requests.post('https://ml-bot-1c0d.onrender.com/api/cargar-productos',json={'productos':p},timeout=120); print(r.text[:200])"
echo Listo!
