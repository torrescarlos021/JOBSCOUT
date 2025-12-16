# 🚀 Guía de Deploy - JobScout v4.0

## Opción 1: Railway (Recomendada)

### Paso 1: Crear cuenta
1. Ve a [railway.app](https://railway.app)
2. Regístrate con GitHub (gratis)

### Paso 2: Subir a GitHub
```bash
# En tu terminal local
cd jobscout-prod
git init
git add .
git commit -m "Initial commit - JobScout v4.0"

# Crear repo en GitHub y conectar
git remote add origin https://github.com/TU_USUARIO/jobscout.git
git push -u origin main
```

### Paso 3: Deploy en Railway
1. En Railway, click "New Project"
2. Selecciona "Deploy from GitHub repo"
3. Elige tu repositorio `jobscout`
4. Railway detectará automáticamente la configuración
5. Espera ~5 minutos al primer deploy

### Paso 4: Obtener URL
- Railway te asignará una URL tipo: `jobscout-production.up.railway.app`
- ¡Listo! Tu app está en internet

### Variables de Entorno (opcional)
En Railway > Settings > Variables:
```
ENVIRONMENT=production
DEBUG=False
```

---

## Opción 2: Render

### Paso 1: Cuenta
1. Ve a [render.com](https://render.com)
2. Regístrate con GitHub

### Paso 2: Nuevo Web Service
1. New > Web Service
2. Conecta tu repo de GitHub
3. Configuración:
   - Name: `jobscout`
   - Runtime: `Docker`
   - Instance Type: `Free` o `Starter`

### Paso 3: Variables
```
PORT=10000
ENVIRONMENT=production
```

---

## Opción 3: VPS (DigitalOcean/Linode)

### Paso 1: Crear Droplet
- Ubuntu 22.04
- $6/mes mínimo

### Paso 2: Setup
```bash
# SSH al servidor
ssh root@TU_IP

# Instalar dependencias
apt update && apt install -y python3-pip python3-venv nginx

# Clonar repo
git clone https://github.com/TU_USUARIO/jobscout.git
cd jobscout

# Setup Python
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
playwright install-deps

# Probar
gunicorn app:app --bind 0.0.0.0:5000
```

### Paso 3: Systemd Service
```bash
# /etc/systemd/system/jobscout.service
[Unit]
Description=JobScout
After=network.target

[Service]
User=root
WorkingDirectory=/root/jobscout
ExecStart=/root/jobscout/venv/bin/gunicorn app:app --bind 127.0.0.1:5000 --timeout 120
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
systemctl enable jobscout
systemctl start jobscout
```

### Paso 4: Nginx
```nginx
# /etc/nginx/sites-available/jobscout
server {
    listen 80;
    server_name tu-dominio.com;
    
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 120s;
    }
}
```

---

## 🔧 Troubleshooting

### Error: Playwright no encuentra Chromium
```bash
playwright install chromium
playwright install-deps chromium
```

### Error: Timeout en scraping
- Aumenta el timeout en gunicorn: `--timeout 180`
- Reduce workers: `--workers 1`

### Error: Memory limit
- El tier gratuito tiene ~512MB
- Usa `--workers 1` para reducir memoria

---

## 📊 Costos Estimados

| Plataforma | Tier Gratuito | Tier Pago |
|------------|---------------|-----------|
| Railway    | 500hrs/mes    | $5/mes    |
| Render     | 750hrs/mes    | $7/mes    |
| DigitalOcean | No         | $6/mes    |

---

¡Éxito con tu deploy! 🎉
