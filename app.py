"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                     JOBSCOUT v5.0 - OPTIMIZED ENGINE                          ║
║         HTTP Directo + Caché SQLite + Proxies Rotativos + Paralelo            ║
╚═══════════════════════════════════════════════════════════════════════════════╝
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote, urljoin
from bs4 import BeautifulSoup
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import requests
import random
import sqlite3
import hashlib
import json
import time
import logging
import os
import re

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════════════════

PORT = int(os.environ.get('PORT', 5000))
DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'
CACHE_TTL_MINUTES = 60  # Caché por 1 hora
MAX_WORKERS = 4  # Búsquedas en paralelo
REQUEST_TIMEOUT = 15

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s │ %(levelname)-8s │ %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger('JobScout')

# ══════════════════════════════════════════════════════════════════════════════
# FLASK APP
# ══════════════════════════════════════════════════════════════════════════════

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

# ══════════════════════════════════════════════════════════════════════════════
# USER AGENTS REALISTAS
# ══════════════════════════════════════════════════════════════════════════════

USER_AGENTS = [
    # Chrome Windows
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    # Chrome Mac
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    # Firefox Windows
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
    # Safari Mac
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
    # Edge
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
]

# ══════════════════════════════════════════════════════════════════════════════
# PROXY MANAGER - Proxies gratuitos rotativos
# ══════════════════════════════════════════════════════════════════════════════

class ProxyManager:
    def __init__(self):
        self.proxies = []
        self.last_fetch = None
        self.fetch_interval = 300  # Refrescar cada 5 minutos
    
    def fetch_proxies(self):
        """Obtiene proxies gratuitos de múltiples fuentes"""
        proxy_sources = [
            'https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=5000&country=all&ssl=yes&anonymity=all',
            'https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt',
            'https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt',
        ]
        
        new_proxies = []
        for url in proxy_sources:
            try:
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    lines = resp.text.strip().split('\n')
                    for line in lines[:50]:  # Max 50 por fuente
                        proxy = line.strip()
                        if proxy and ':' in proxy:
                            new_proxies.append(f'http://{proxy}')
            except:
                continue
        
        if new_proxies:
            self.proxies = list(set(new_proxies))[:100]  # Max 100 proxies
            self.last_fetch = datetime.now()
            logger.info(f"🔄 {len(self.proxies)} proxies cargados")
        
        return self.proxies
    
    def get_proxy(self) -> Optional[Dict]:
        """Retorna un proxy aleatorio o None para usar conexión directa"""
        # 50% de probabilidad de usar proxy, 50% directo
        if random.random() > 0.5:
            return None
        
        # Refrescar si es necesario
        if not self.proxies or not self.last_fetch or \
           (datetime.now() - self.last_fetch).seconds > self.fetch_interval:
            self.fetch_proxies()
        
        if self.proxies:
            proxy = random.choice(self.proxies)
            return {'http': proxy, 'https': proxy}
        return None

proxy_manager = ProxyManager()

# ══════════════════════════════════════════════════════════════════════════════
# CACHÉ SQLite
# ══════════════════════════════════════════════════════════════════════════════

class CacheDB:
    def __init__(self, db_path='jobscout_cache.db'):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_created ON cache(created_at)')
            conn.commit()
    
    def _generate_key(self, *args) -> str:
        key_data = json.dumps(args, sort_keys=True)
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def get(self, *args) -> Optional[List]:
        key = self._generate_key(*args)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                'SELECT data, created_at FROM cache WHERE key = ?', (key,)
            )
            row = cursor.fetchone()
            
            if row:
                data, created_at = row
                created = datetime.fromisoformat(created_at)
                if datetime.now() - created < timedelta(minutes=CACHE_TTL_MINUTES):
                    logger.info(f"💾 Cache HIT: {key[:8]}...")
                    return json.loads(data)
                else:
                    # Expirado, eliminar
                    conn.execute('DELETE FROM cache WHERE key = ?', (key,))
                    conn.commit()
        return None
    
    def set(self, data: List, *args):
        key = self._generate_key(*args)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                'INSERT OR REPLACE INTO cache (key, data, created_at) VALUES (?, ?, ?)',
                (key, json.dumps(data), datetime.now().isoformat())
            )
            conn.commit()
        logger.info(f"💾 Cache SET: {key[:8]}...")
    
    def cleanup(self):
        """Elimina entradas expiradas"""
        with sqlite3.connect(self.db_path) as conn:
            cutoff = (datetime.now() - timedelta(minutes=CACHE_TTL_MINUTES)).isoformat()
            conn.execute('DELETE FROM cache WHERE created_at < ?', (cutoff,))
            conn.commit()
    
    def stats(self) -> Dict:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('SELECT COUNT(*) FROM cache')
            count = cursor.fetchone()[0]
            return {'entries': count, 'ttl_minutes': CACHE_TTL_MINUTES}

cache = CacheDB()

# ══════════════════════════════════════════════════════════════════════════════
# HTTP CLIENT MEJORADO
# ══════════════════════════════════════════════════════════════════════════════

class SmartHTTPClient:
    def __init__(self):
        self.session = requests.Session()
    
    def get_headers(self) -> Dict:
        ua = random.choice(USER_AGENTS)
        return {
            'User-Agent': ua,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'es-MX,es;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        }
    
    def get(self, url: str, retries: int = 3) -> Optional[str]:
        for attempt in range(retries):
            try:
                proxy = proxy_manager.get_proxy()
                response = self.session.get(
                    url,
                    headers=self.get_headers(),
                    proxies=proxy,
                    timeout=REQUEST_TIMEOUT,
                    allow_redirects=True
                )
                
                if response.status_code == 200:
                    return response.text
                elif response.status_code == 429:
                    # Rate limited, esperar
                    time.sleep(2 ** attempt)
                    continue
                    
            except requests.exceptions.Timeout:
                logger.warning(f"⏱️ Timeout intento {attempt + 1}")
            except requests.exceptions.ProxyError:
                logger.warning(f"🔄 Proxy error, reintentando...")
            except Exception as e:
                logger.warning(f"⚠️ Error: {str(e)[:50]}")
            
            time.sleep(random.uniform(0.5, 1.5))
        
        return None

http_client = SmartHTTPClient()

# ══════════════════════════════════════════════════════════════════════════════
# MODELOS
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class JobListing:
    title: str
    company: str
    location: str
    link: str
    source: str
    
    def to_dict(self) -> dict:
        return asdict(self)

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE CARRERAS
# ══════════════════════════════════════════════════════════════════════════════

CAREER_CONFIG = {
    "mecatronica": {"keywords": ["ingeniero mecatrónico", "mecatrónica", "automatización", "PLC", "robótica"], "icon": "🤖"},
    "industrial": {"keywords": ["ingeniero industrial", "mejora continua", "lean manufacturing", "producción"], "icon": "🏭"},
    "mecanica": {"keywords": ["ingeniero mecánico", "diseño mecánico", "CAD", "manufactura"], "icon": "⚙️"},
    "tecnologias_computacionales": {"keywords": ["desarrollador", "software", "programador", "full stack", "backend", "frontend"], "icon": "💻"},
    "civil": {"keywords": ["ingeniero civil", "construcción", "estructuras", "obra"], "icon": "🏗️"},
    "biotecnologia": {"keywords": ["biotecnología", "laboratorio", "microbiología", "calidad"], "icon": "🧬"},
    "finanzas": {"keywords": ["analista financiero", "finanzas", "contabilidad", "tesorería"], "icon": "📊"},
    "administracion": {"keywords": ["administrador", "gestión", "coordinador", "gerente"], "icon": "📋"},
    "transformacion_negocios": {"keywords": ["business analyst", "consultor", "transformación digital"], "icon": "🚀"},
    "negocios_internacionales": {"keywords": ["comercio exterior", "importación", "exportación", "logística"], "icon": "🌎"},
    "mercadotecnia": {"keywords": ["marketing", "community manager", "redes sociales", "publicidad"], "icon": "📱"},
    "arquitectura": {"keywords": ["arquitecto", "diseño arquitectónico", "BIM", "Revit"], "icon": "🏛️"},
    "derecho": {"keywords": ["abogado", "legal", "jurídico", "licenciado en derecho"], "icon": "⚖️"}
}

# ══════════════════════════════════════════════════════════════════════════════
# SCRAPERS HTTP DIRECTOS
# ══════════════════════════════════════════════════════════════════════════════

class LinkedInScraper:
    """Scraper para LinkedIn Jobs (versión pública sin login)"""
    
    @staticmethod
    def scrape(keyword: str, location: str) -> List[JobListing]:
        logger.info(f"🔵 LinkedIn: '{keyword}' en {location}")
        jobs = []
        
        # LinkedIn jobs públicos
        url = f"https://www.linkedin.com/jobs/search?keywords={quote(keyword)}&location={quote(location)}&f_TPR=r86400&position=1&pageNum=0"
        
        html = http_client.get(url)
        if not html:
            logger.warning("   ❌ No se pudo obtener LinkedIn")
            return jobs
        
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # LinkedIn usa diferentes selectores
            cards = soup.select('div.base-card, div.job-search-card, li.jobs-search-results__list-item')
            
            for card in cards[:10]:
                try:
                    # Título
                    title_elem = card.select_one('h3.base-search-card__title, h3.job-search-card__title, a.job-card-list__title')
                    title = title_elem.get_text(strip=True) if title_elem else None
                    
                    # Empresa
                    company_elem = card.select_one('h4.base-search-card__subtitle, h4.job-search-card__subtitle, a.job-card-container__company-name')
                    company = company_elem.get_text(strip=True) if company_elem else "Empresa confidencial"
                    
                    # Ubicación
                    location_elem = card.select_one('span.job-search-card__location, span.job-result-card__location')
                    job_location = location_elem.get_text(strip=True) if location_elem else location
                    
                    # Link
                    link_elem = card.select_one('a.base-card__full-link, a.job-search-card__link-wrapper, a[href*="/jobs/view/"]')
                    link = link_elem.get('href', '') if link_elem else ''
                    
                    if title and link:
                        # Limpiar link
                        if link.startswith('/'):
                            link = 'https://www.linkedin.com' + link
                        link = link.split('?')[0]
                        
                        jobs.append(JobListing(
                            title=title,
                            company=company,
                            location=job_location,
                            link=link,
                            source="LinkedIn"
                        ))
                except Exception as e:
                    continue
                    
        except Exception as e:
            logger.error(f"   ❌ Error parsing LinkedIn: {str(e)[:50]}")
        
        logger.info(f"   ✅ {len(jobs)} vacantes")
        return jobs


class IndeedScraper:
    """Scraper para Indeed México"""
    
    @staticmethod
    def scrape(keyword: str, location: str) -> List[JobListing]:
        logger.info(f"🟣 Indeed: '{keyword}' en {location}")
        jobs = []
        
        url = f"https://mx.indeed.com/jobs?q={quote(keyword)}&l={quote(location)}&sort=date&fromage=7"
        
        html = http_client.get(url)
        if not html:
            logger.warning("   ❌ No se pudo obtener Indeed")
            return jobs
        
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Indeed cards
            cards = soup.select('div.job_seen_beacon, div.jobsearch-ResultsList > div, td.resultContent')
            
            for card in cards[:10]:
                try:
                    # Título
                    title_elem = card.select_one('h2.jobTitle span[title], h2.jobTitle a, a.jcs-JobTitle')
                    title = title_elem.get_text(strip=True) if title_elem else None
                    
                    # Empresa
                    company_elem = card.select_one('span.companyName, span[data-testid="company-name"]')
                    company = company_elem.get_text(strip=True) if company_elem else "Empresa confidencial"
                    
                    # Ubicación
                    location_elem = card.select_one('div.companyLocation, div[data-testid="text-location"]')
                    job_location = location_elem.get_text(strip=True) if location_elem else location
                    
                    # Link
                    link_elem = card.select_one('a[id^="job_"], a.jcs-JobTitle, h2.jobTitle a')
                    link = link_elem.get('href', '') if link_elem else ''
                    
                    if title and link:
                        if link.startswith('/'):
                            link = 'https://mx.indeed.com' + link
                        
                        jobs.append(JobListing(
                            title=title,
                            company=company,
                            location=job_location,
                            link=link,
                            source="Indeed"
                        ))
                except:
                    continue
                    
        except Exception as e:
            logger.error(f"   ❌ Error parsing Indeed: {str(e)[:50]}")
        
        logger.info(f"   ✅ {len(jobs)} vacantes")
        return jobs


class ComputrabajoScraper:
    """Scraper para Computrabajo México"""
    
    @staticmethod
    def scrape(keyword: str, location: str) -> List[JobListing]:
        logger.info(f"🟢 Computrabajo: '{keyword}' en {location}")
        jobs = []
        
        # Normalizar ubicación para Computrabajo
        location_slug = location.lower().replace(' ', '-').replace('á', 'a').replace('é', 'e').replace('í', 'i').replace('ó', 'o').replace('ú', 'u')
        
        url = f"https://www.computrabajo.com.mx/trabajo-de-{quote(keyword.replace(' ', '-'))}"
        
        html = http_client.get(url)
        if not html:
            logger.warning("   ❌ No se pudo obtener Computrabajo")
            return jobs
        
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            cards = soup.select('article.box_offer, div.job_item, article[data-id]')
            
            for card in cards[:10]:
                try:
                    title_elem = card.select_one('h2 a, a.js-o-link, h1.fwB')
                    title = title_elem.get_text(strip=True) if title_elem else None
                    
                    company_elem = card.select_one('p.fs16.fc_base, span.enterprise, a.fc_aux')
                    company = company_elem.get_text(strip=True) if company_elem else "Empresa confidencial"
                    
                    location_elem = card.select_one('span.location, p.fs13 span')
                    job_location = location_elem.get_text(strip=True) if location_elem else location
                    
                    link_elem = card.select_one('a[href*="/ofertas-de-trabajo/"], h2 a')
                    link = link_elem.get('href', '') if link_elem else ''
                    
                    if title and link:
                        if link.startswith('/'):
                            link = 'https://www.computrabajo.com.mx' + link
                        
                        jobs.append(JobListing(
                            title=title,
                            company=company,
                            location=job_location,
                            link=link,
                            source="Computrabajo"
                        ))
                except:
                    continue
                    
        except Exception as e:
            logger.error(f"   ❌ Error parsing Computrabajo: {str(e)[:50]}")
        
        logger.info(f"   ✅ {len(jobs)} vacantes")
        return jobs


class OCCMundialScraper:
    """Scraper para OCC Mundial"""
    
    @staticmethod
    def scrape(keyword: str, location: str) -> List[JobListing]:
        logger.info(f"🟠 OCC Mundial: '{keyword}' en {location}")
        jobs = []
        
        url = f"https://www.occ.com.mx/empleos/de-{quote(keyword.replace(' ', '-'))}/"
        
        html = http_client.get(url)
        if not html:
            logger.warning("   ❌ No se pudo obtener OCC")
            return jobs
        
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            cards = soup.select('div.job-card, article.job, div[class*="jobCard"]')
            
            for card in cards[:10]:
                try:
                    title_elem = card.select_one('h2 a, a.job-title, h3.title')
                    title = title_elem.get_text(strip=True) if title_elem else None
                    
                    company_elem = card.select_one('span.company, div.company-name, p.company')
                    company = company_elem.get_text(strip=True) if company_elem else "Empresa confidencial"
                    
                    location_elem = card.select_one('span.location, div.location')
                    job_location = location_elem.get_text(strip=True) if location_elem else location
                    
                    link_elem = card.select_one('a[href*="/empleo/"]')
                    link = link_elem.get('href', '') if link_elem else ''
                    
                    if title and link:
                        if link.startswith('/'):
                            link = 'https://www.occ.com.mx' + link
                        
                        jobs.append(JobListing(
                            title=title,
                            company=company,
                            location=job_location,
                            link=link,
                            source="OCC Mundial"
                        ))
                except:
                    continue
                    
        except Exception as e:
            logger.error(f"   ❌ Error parsing OCC: {str(e)[:50]}")
        
        logger.info(f"   ✅ {len(jobs)} vacantes")
        return jobs

# ══════════════════════════════════════════════════════════════════════════════
# MOTOR DE BÚSQUEDA PARALELO
# ══════════════════════════════════════════════════════════════════════════════

class SearchEngine:
    def __init__(self):
        self.scrapers = [
            LinkedInScraper.scrape,
            IndeedScraper.scrape,
            ComputrabajoScraper.scrape,
            OCCMundialScraper.scrape,
        ]
    
    def search(self, career: str, location: str) -> List[dict]:
        if career not in CAREER_CONFIG:
            raise ValueError(f"Carrera no válida: {career}")
        
        # Revisar caché
        cached = cache.get(career, location)
        if cached:
            return cached
        
        config = CAREER_CONFIG[career]
        keyword = config["keywords"][0]
        all_jobs: List[JobListing] = []
        
        logger.info("═" * 50)
        logger.info(f"🔍 BÚSQUEDA: {config['icon']} {career}")
        logger.info(f"   Keyword: {keyword} | Ubicación: {location}")
        logger.info("═" * 50)
        
        # Búsqueda paralela
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(scraper, keyword, location): scraper.__qualname__
                for scraper in self.scrapers
            }
            
            for future in as_completed(futures, timeout=30):
                try:
                    jobs = future.result()
                    all_jobs.extend(jobs)
                except Exception as e:
                    logger.error(f"❌ Error en scraper: {e}")
        
        # Eliminar duplicados
        seen = set()
        unique_jobs = []
        for job in all_jobs:
            key = (job.title.lower()[:50], job.company.lower()[:30])
            if key not in seen:
                seen.add(key)
                unique_jobs.append(job)
        
        random.shuffle(unique_jobs)
        
        logger.info(f"✅ Total: {len(unique_jobs)} vacantes únicas")
        
        result = [job.to_dict() for job in unique_jobs]
        
        # Guardar en caché
        if result:
            cache.set(result, career, location)
        
        return result

engine = SearchEngine()

# ══════════════════════════════════════════════════════════════════════════════
# RUTAS API
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/')
def serve_frontend():
    return send_from_directory('static', 'index.html')

@app.route('/api')
def api_info():
    return jsonify({
        "name": "JobScout API",
        "version": "5.0",
        "engine": "HTTP Directo + Caché + Paralelo",
        "status": "online"
    })

@app.route('/api/scrape', methods=['GET'])
def scrape_jobs():
    career = request.args.get('career')
    location = request.args.get('location', 'México')
    
    if not career:
        return jsonify({"error": "El parámetro 'career' es requerido"}), 400
    
    if career not in CAREER_CONFIG:
        return jsonify({"error": f"Carrera '{career}' no válida"}), 400
    
    try:
        start = time.time()
        jobs = engine.search(career, location)
        elapsed = round(time.time() - start, 2)
        
        return jsonify({
            "success": True,
            "query": {"career": career, "location": location},
            "total": len(jobs),
            "time_seconds": elapsed,
            "jobs": jobs
        })
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/careers', methods=['GET'])
def list_careers():
    return jsonify({k: {"keywords": v["keywords"], "icon": v["icon"]} for k, v in CAREER_CONFIG.items()})

@app.route('/api/stats', methods=['GET'])
def get_stats():
    return jsonify({
        "cache": cache.stats(),
        "sources": ["LinkedIn", "Indeed", "Computrabajo", "OCC Mundial"],
        "version": "5.0"
    })

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    # Limpiar caché viejo al iniciar
    cache.cleanup()
    
    # Cargar proxies al iniciar
    proxy_manager.fetch_proxies()
    
    print(f"""
    ╔═══════════════════════════════════════════════════════════════╗
    ║           🔍 JOBSCOUT v5.0 - OPTIMIZED ENGINE                 ║
    ╠═══════════════════════════════════════════════════════════════╣
    ║  ⚡ HTTP Directo (sin Playwright)                             ║
    ║  💾 Caché SQLite ({CACHE_TTL_MINUTES} min TTL)                             ║
    ║  🔄 Proxies Rotativos                                         ║
    ║  🚀 Scraping Paralelo ({MAX_WORKERS} workers)                          ║
    ╠═══════════════════════════════════════════════════════════════╣
    ║  🌐 URL: http://localhost:{PORT}                               ║
    ╚═══════════════════════════════════════════════════════════════╝
    """)
    app.run(host='0.0.0.0', port=PORT, debug=DEBUG)
