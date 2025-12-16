"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                     JOBSCOUT v4.0 - PRODUCTION BACKEND                         ║
║                 Optimizado para Railway / Render / Heroku                      ║
╚═══════════════════════════════════════════════════════════════════════════════╝
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from urllib.parse import quote
from functools import wraps
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Callable
import time
import random
import hashlib
import json
import logging
import threading
import os

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════════════════

# Obtener puerto del environment (Railway/Render lo asignan automáticamente)
PORT = int(os.environ.get('PORT', 5000))
DEBUG = os.environ.get('DEBUG', 'False').lower() == 'true'
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'production')

# Logging
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
CORS(app, resources={r"/api/*": {"origins": "*"}})

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
    experience_level: str = "No especificado"
    
    def to_dict(self) -> dict:
        return asdict(self)

# ══════════════════════════════════════════════════════════════════════════════
# CACHÉ
# ══════════════════════════════════════════════════════════════════════════════

class SmartCache:
    def __init__(self, default_ttl: int = 600):  # 10 minutos en producción
        self._cache: Dict[str, tuple] = {}
        self._lock = threading.Lock()
        self.default_ttl = default_ttl
        self.hits = 0
        self.misses = 0
    
    def _generate_key(self, *args, **kwargs) -> str:
        key_data = json.dumps({'args': args, 'kwargs': kwargs}, sort_keys=True)
        return hashlib.md5(key_data.encode()).hexdigest()
    
    def get(self, key: str) -> Optional[any]:
        with self._lock:
            if key in self._cache:
                value, expiry = self._cache[key]
                if datetime.now() < expiry:
                    self.hits += 1
                    logger.info(f"💾 Cache HIT: {key[:8]}...")
                    return value
                else:
                    del self._cache[key]
            self.misses += 1
            return None
    
    def set(self, key: str, value: any, ttl: int = None) -> None:
        with self._lock:
            expiry = datetime.now() + timedelta(seconds=ttl or self.default_ttl)
            self._cache[key] = (value, expiry)
    
    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            'entries': len(self._cache),
            'hits': self.hits,
            'misses': self.misses,
            'hit_rate': f"{(self.hits / total * 100):.1f}%" if total > 0 else "0%"
        }

cache = SmartCache(default_ttl=600)

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN DE CARRERAS
# ══════════════════════════════════════════════════════════════════════════════

CAREER_CONFIG = {
    "mecatronica": {
        "keywords": ["ingeniero mecatrónico", "automatización industrial", "robótica", "PLC"],
        "icon": "🤖"
    },
    "industrial": {
        "keywords": ["ingeniero industrial", "mejora continua", "lean manufacturing", "six sigma"],
        "icon": "🏭"
    },
    "mecanica": {
        "keywords": ["ingeniero mecánico", "diseño mecánico", "CAD", "manufactura"],
        "icon": "⚙️"
    },
    "tecnologias_computacionales": {
        "keywords": ["desarrollador software", "programador", "full stack", "backend developer"],
        "icon": "💻"
    },
    "civil": {
        "keywords": ["ingeniero civil", "construcción", "estructuras", "residente de obra"],
        "icon": "🏗️"
    },
    "biotecnologia": {
        "keywords": ["biotecnólogo", "laboratorio", "microbiología", "calidad alimentos"],
        "icon": "🧬"
    },
    "finanzas": {
        "keywords": ["analista financiero", "finanzas corporativas", "tesorería", "FP&A"],
        "icon": "📊"
    },
    "administracion": {
        "keywords": ["administrador empresas", "gestión proyectos", "coordinador"],
        "icon": "📋"
    },
    "transformacion_negocios": {
        "keywords": ["business analyst", "consultor negocios", "transformación digital"],
        "icon": "🚀"
    },
    "negocios_internacionales": {
        "keywords": ["comercio exterior", "logística internacional", "aduanas"],
        "icon": "🌎"
    },
    "mercadotecnia": {
        "keywords": ["marketing digital", "community manager", "growth marketing", "SEO"],
        "icon": "📱"
    },
    "arquitectura": {
        "keywords": ["arquitecto", "diseño arquitectónico", "BIM", "Revit"],
        "icon": "🏛️"
    },
    "derecho": {
        "keywords": ["abogado", "legal", "jurídico", "corporativo"],
        "icon": "⚖️"
    }
}

EXPERIENCE_FILTERS = {
    "linkedin": {
        "practicas": "&f_E=1",
        "recien_egresado": "&f_E=2",
        "ambos": "&f_E=1%2C2"
    },
    "indeed": {
        "practicas": "&explvl=entry_level",
        "recien_egresado": "&explvl=entry_level",
        "ambos": ""
    }
}

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2.1 Safari/605.1.15',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0',
]

# ══════════════════════════════════════════════════════════════════════════════
# UTILIDADES
# ══════════════════════════════════════════════════════════════════════════════

def retry_with_backoff(max_retries: int = 2, base_delay: float = 1.0):
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(f"⚠️ Intento {attempt + 1}/{max_retries} fallido. Reintentando en {delay:.1f}s")
                    time.sleep(delay)
            raise last_exception
        return wrapper
    return decorator

def create_stealth_browser(playwright):
    """Crea navegador para producción (headless optimizado)"""
    browser = playwright.chromium.launch(
        headless=True,
        args=[
            '--disable-blink-features=AutomationControlled',
            '--disable-dev-shm-usage',
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-gpu',
            '--single-process',  # Importante para Railway/containers
            '--no-zygote'
        ]
    )
    
    context = browser.new_context(
        user_agent=random.choice(USER_AGENTS),
        viewport={'width': 1920, 'height': 1080},
        locale='es-MX',
        timezone_id='America/Mexico_City'
    )
    
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['es-MX', 'es', 'en'] });
        window.chrome = { runtime: {} };
    """)
    
    return browser, context

def human_like_delay(min_sec: float = 0.3, max_sec: float = 1.0):
    time.sleep(random.uniform(min_sec, max_sec))

def clean_text(text: str) -> str:
    if not text:
        return ""
    return ' '.join(text.strip().split())

def clean_url(url: str, base: str = "") -> str:
    if not url:
        return ""
    if url.startswith('/'):
        url = base + url
    return url.split('?')[0].split('#')[0]

# ══════════════════════════════════════════════════════════════════════════════
# SCRAPERS
# ══════════════════════════════════════════════════════════════════════════════

class LinkedInScraper:
    @staticmethod
    @retry_with_backoff(max_retries=2)
    def scrape(page, keyword: str, location: str, experience: str) -> List[JobListing]:
        logger.info(f"🔵 LinkedIn: '{keyword}' en {location}")
        jobs = []
        
        exp_filter = EXPERIENCE_FILTERS["linkedin"].get(experience, "")
        url = f"https://www.linkedin.com/jobs/search/?keywords={quote(keyword)}&location={quote(location)}{exp_filter}&sortBy=DD"
        
        try:
            page.goto(url, timeout=25000, wait_until='domcontentloaded')
            human_like_delay(1, 2)
            
            for _ in range(2):
                page.mouse.wheel(0, random.randint(500, 800))
                human_like_delay(0.3, 0.6)
            
            page.wait_for_selector("div.base-card, div.job-search-card", timeout=8000)
            cards = page.locator("div.base-card, div.job-search-card").all()
            
            for card in cards[:8]:
                try:
                    title = clean_text(card.locator("h3").inner_text())
                    company = clean_text(card.locator("h4").inner_text())
                    job_location = clean_text(card.locator("span.job-search-card__location").inner_text()) or location
                    link = card.locator("a").first.get_attribute("href") or ""
                    
                    if title and company:
                        jobs.append(JobListing(
                            title=title, company=company, location=job_location,
                            link=clean_url(link), source="LinkedIn",
                            experience_level="Prácticas" if experience == "practicas" else "Entry Level"
                        ))
                except:
                    continue
                    
        except PlaywrightTimeout:
            logger.warning("   ⏱️ Timeout LinkedIn")
        except Exception as e:
            logger.error(f"   ❌ Error LinkedIn: {str(e)[:50]}")
        
        logger.info(f"   ✅ {len(jobs)} vacantes")
        return jobs


class IndeedScraper:
    @staticmethod
    @retry_with_backoff(max_retries=2)
    def scrape(page, keyword: str, location: str, experience: str) -> List[JobListing]:
        logger.info(f"🟣 Indeed: '{keyword}' en {location}")
        jobs = []
        
        exp_filter = EXPERIENCE_FILTERS["indeed"].get(experience, "")
        url = f"https://mx.indeed.com/jobs?q={quote(keyword)}&l={quote(location)}{exp_filter}&sort=date"
        
        try:
            page.goto(url, timeout=25000, wait_until='domcontentloaded')
            human_like_delay(1, 2)
            
            try:
                page.locator("button[aria-label='close']").click(timeout=2000)
            except:
                pass
            
            page.wait_for_selector("div.job_seen_beacon, td.resultContent", timeout=8000)
            cards = page.locator("div.job_seen_beacon, td.resultContent").all()
            
            for card in cards[:8]:
                try:
                    title_elem = card.locator("h2.jobTitle span[title], h2.jobTitle a")
                    title = clean_text(title_elem.inner_text())
                    company = clean_text(card.locator("[data-testid='company-name'], span.companyName").inner_text())
                    job_location = clean_text(card.locator("[data-testid='text-location'], div.companyLocation").inner_text()) or location
                    link_elem = card.locator("a[id^='job_'], a.jcs-JobTitle").first
                    link = link_elem.get_attribute("href") or ""
                    
                    if title and company:
                        jobs.append(JobListing(
                            title=title, company=company, location=job_location,
                            link=clean_url(link, "https://mx.indeed.com"), source="Indeed"
                        ))
                except:
                    continue
                    
        except PlaywrightTimeout:
            logger.warning("   ⏱️ Timeout Indeed")
        except Exception as e:
            logger.error(f"   ❌ Error Indeed: {str(e)[:50]}")
        
        logger.info(f"   ✅ {len(jobs)} vacantes")
        return jobs

# ══════════════════════════════════════════════════════════════════════════════
# MOTOR DE SCRAPING
# ══════════════════════════════════════════════════════════════════════════════

class ScrapingEngine:
    def __init__(self):
        self.scrapers = {
            'linkedin': LinkedInScraper.scrape,
            'indeed': IndeedScraper.scrape,
        }
    
    def search(self, career: str, location: str, experience: str) -> List[dict]:
        if career not in CAREER_CONFIG:
            raise ValueError(f"Carrera no válida: {career}")
        
        cache_key = cache._generate_key(career, location, experience)
        cached_result = cache.get(cache_key)
        if cached_result:
            return cached_result
        
        config = CAREER_CONFIG[career]
        keyword = config["keywords"][0]
        all_jobs: List[JobListing] = []
        
        logger.info("═" * 50)
        logger.info(f"🔍 BÚSQUEDA: {config['icon']} {career}")
        logger.info(f"   Keyword: {keyword} | Loc: {location} | Exp: {experience}")
        logger.info("═" * 50)
        
        with sync_playwright() as playwright:
            browser, context = create_stealth_browser(playwright)
            page = context.new_page()
            
            for source, scraper in self.scrapers.items():
                try:
                    jobs = scraper(page, keyword, location, experience)
                    all_jobs.extend(jobs)
                    human_like_delay(0.5, 1)
                except Exception as e:
                    logger.error(f"❌ Error en {source}: {e}")
            
            browser.close()
        
        # Eliminar duplicados
        seen = set()
        unique_jobs = []
        for job in all_jobs:
            key = (job.title.lower(), job.company.lower())
            if key not in seen:
                seen.add(key)
                unique_jobs.append(job)
        
        random.shuffle(unique_jobs)
        
        logger.info(f"✅ Total: {len(unique_jobs)} vacantes únicas")
        
        result = [job.to_dict() for job in unique_jobs]
        cache.set(cache_key, result)
        
        return result

engine = ScrapingEngine()

# ══════════════════════════════════════════════════════════════════════════════
# RUTAS API
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/')
def serve_frontend():
    """Sirve el frontend"""
    return send_from_directory('static', 'index.html')

@app.route('/api')
def api_info():
    return jsonify({
        "name": "JobScout API",
        "version": "4.0",
        "status": "online",
        "environment": ENVIRONMENT
    })

@app.route('/api/scrape', methods=['GET'])
def scrape_jobs():
    career = request.args.get('career')
    location = request.args.get('location', 'México')
    experience = request.args.get('experience', 'ambos')
    
    if not career:
        return jsonify({"error": "El parámetro 'career' es requerido"}), 400
    
    if career not in CAREER_CONFIG:
        return jsonify({"error": f"Carrera '{career}' no válida", "available": list(CAREER_CONFIG.keys())}), 400
    
    try:
        jobs = engine.search(career, location, experience)
        return jsonify({
            "success": True,
            "query": {"career": career, "location": location, "experience": experience},
            "total": len(jobs),
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
    return jsonify({"cache": cache.stats(), "sources": list(engine.scrapers.keys())})

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print(f"""
    ╔═══════════════════════════════════════════════════════════════╗
    ║           🔍 JOBSCOUT v4.0 - {ENVIRONMENT.upper():^15}              ║
    ╠═══════════════════════════════════════════════════════════════╣
    ║  🌐 URL: http://0.0.0.0:{PORT:<5}                                ║
    ║  📡 API: http://0.0.0.0:{PORT}/api                              ║
    ╚═══════════════════════════════════════════════════════════════╝
    """)
    app.run(host='0.0.0.0', port=PORT, debug=DEBUG)
