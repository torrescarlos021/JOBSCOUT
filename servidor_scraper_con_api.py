from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote

app = Flask(__name__)
CORS(app)

SCRAPINGBEE_API_KEY = 'N442FF79HZWBD2HQMS4369K1CSS9T9FW0MUIDMNKVJY7IRDB0DOBH25U8LLTHN8LUOYEMCGFQ3BFYGK6'

SEARCH_QUERIES = {
    "mecatronica": ["ingeniero mecatronico", "automatizacion", "robotica", "control"],
    "industrial": ["ingeniero industrial", "procesos", "calidad", "supply chain", "logistica"],
    "tecnologias_computacionales": ["desarrollador de software", "ingeniero de software", "programador", "devops"],
    "civil": ["ingeniero civil", "construccion", "estructuras", "obra civil"],
    "finanzas": ["analista financiero", "finanzas", "contador", "tesoreria", "inversiones"],
    "administracion": ["administrador de empresas", "gerente", "coordinador", "gestion de proyectos"],
    "transformacion_negocios": ["consultor de negocios", "business transformation", "mejora continua"],
    "negocios_internacionales": ["comercio exterior", "international business", "import export"],
    "mecanica": ["ingeniero mecanico", "diseño mecanico", "mantenimiento mecanico"],
    "mercadotecnia": ["marketing digital", "gerente de marca", "publicidad", "SEO", "SEM"],
    "arquitectura": ["arquitecto", "diseño arquitectonico", "urbanismo", "autocad", "revit"],
    "derecho": ["abogado", "legal", "corporativo", "litigio"],
    "biotecnologia": ["ingeniero en biotecnologia", "biotecnologo", "investigacion y desarrollo", "laboratorio"]
}

@app.route('/scrape', methods=['GET'])
def scrape_jobs():
    career = request.args.get('career')
    location = request.args.get('location', 'Mexico')

    print(f"\n>>> Petición recibida: Carrera='{career}', Lugar='{location}'")

    if not career or career not in SEARCH_QUERIES:
        return jsonify({"error": "Carrera no válida."}), 400

    try:
        search_term = " OR ".join(SEARCH_QUERIES[career])
        encoded_search_term = quote(search_term)
        encoded_location = quote(location)
        
        linkedin_url = f"https://www.linkedin.com/jobs/search/?keywords={encoded_search_term}&location={encoded_location}"
        
        # Parámetros para la API 
        payload = {
            'api_key': SCRAPINGBEE_API_KEY, 
            'url': linkedin_url
        }
        
        print(f">>> Buscando en LinkedIn a través de ScrapingBee...")
        
        #ENDPOINT
        response = requests.get('https://app.scrapingbee.com/api/v1/', params=payload, timeout=90) # Aumentamos el timeout a 90s
        
        response.raise_for_status()

        soup = BeautifulSoup(response.text, 'html.parser')
        job_listings = soup.find_all('div', class_='base-card')

        jobs_data = []
        for job in job_listings:
            title_element = job.find('h3', class_='base-search-card__title')
            company_element = job.find('h4', class_='base-search-card__subtitle')
            location_element = job.find('span', class_='job-search-card__location')
            link_element = job.find('a', class_='base-card__full-link')

            if all([title_element, company_element, location_element, link_element]):
                jobs_data.append({
                    "title": title_element.text.strip(),
                    "company": company_element.text.strip(),
                    "location": location_element.text.strip(),
                    "link": link_element['href']
                })
        
        print(f">>> Búsqueda completa. Enviando {len(jobs_data)} vacantes al cliente.")
        return jsonify(jobs_data)

    except requests.exceptions.RequestException as e:
        error_message = f"Error de red o timeout al contactar ScrapingBee. Detalles: {e}"
        print(f"!!! {error_message}")
        return jsonify({"error": error_message}), 500

    except Exception as e:
        error_message = f"Ocurrió un error inesperado en el servidor. Detalles: {e}"
        print(f"!!! {error_message}")
        return jsonify({"error": error_message}), 500

# INICIO SERV
if __name__ == '__main__':
    print("===================================================")
    print(">>> Servidor de Scraping LOCAL (con ScrapingBee) iniciado.")
    print(">>> Escuchando en: http://127.0.0.1:5000")
    print(">>> Presiona CTRL+C para detener el servidor.")
    print("===================================================")

    app.run(port=5000)
