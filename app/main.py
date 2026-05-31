import socket
import time
import threading
import uvicorn
from datetime import datetime
from fastapi import FastAPI, Request, Response
from dnslib import DNSRecord, QTYPE, RR, A
from fastapi.responses import HTMLResponse # Pentru a trimite pagina web
from collections import Counter # Pentru a număra rapid domeniile

# --- 1. CONFIGURARE ȘI VARIABILE GLOBALE ---
BLOCKLIST_FILE = "/data/adlist.txt"
LOG_FILE = "/data/blocked_queries.log"

dns_cache = {}
# Creăm "cheia" (Lock) pentru fișierul de log
# Acesta garantează că un singur thread scrie în fișier la un moment dat
log_lock = threading.Lock()

# --- 2. MODULUL DE LOGGING (THREAD-SAFE) ---

def log_blocked_event(domain, qtype):
    """Salvează domeniul blocat în fișier cu timestamp."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"{timestamp} - BLOCKED - {domain} (Type: {qtype})\n"

    # AICI este folosirea thread-lock-ului:
    # 'with log_lock' asigură că dacă un thread scrie, celelalte așteaptă la rând
    with log_lock:
        try:
            with open(LOG_FILE, "a") as f:
                f.write(log_entry)
        except Exception as e:
            print(f"[EROARE LOGARE] Nu s-a putut scrie în fișier: {e}")

# --- 3. LOGICA DE REZOLUȚIE DNS ---

def load_blocklist():
    """Încarcă domeniile din fișier într-un set pentru căutare rapidă."""
    blocklist = set()
    try:
        with open(BLOCKLIST_FILE, "r") as f:
            for line in f:
                domain = line.strip().lower()
                if domain:
                    blocklist.add(domain)
        print(f"[INFO] Blocklist încărcat cu succes ({len(blocklist)} domenii).")
    except FileNotFoundError:
        print(f"[⚠️ ATENȚIE] Fișierul {BLOCKLIST_FILE} nu a fost găsit!")
    return blocklist

blocked_domains = load_blocklist()

def ask_upstream(data):
    """Trimite cererea DNS către Google DNS (8.8.8.8) prin UDP."""
    upstream_server = "8.8.8.8"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(2.0)
        try:
            sock.sendto(data, (upstream_server, 53))
            answer, _ = sock.recvfrom(1024)
            return answer
        except socket.timeout:
            return None

def process_dns_query(data):
    """
    Creierul aplicației:
    1. Verifică Blocklist -> 2. Verifică Cache -> 3. Întreabă Internetul
    """
    try:
        request = DNSRecord.parse(data)
        domain = str(request.q.qname).strip(".")
        query_id = request.header.id
        qtype = request.q.qtype

        # PASUL 1: FILTRARE (AD-BLOCKING)
        if domain.lower() in blocked_domains:
            print(f"[BLOCK] {domain}")
            log_blocked_event(domain, qtype) # Apelăm modulul de logging
            
            reply = request.reply()
            reply.add_answer(RR(rname=request.q.qname, rtype=QTYPE.A, rclass=1, ttl=60, rdata=A("0.0.0.0")))
            return reply.pack()

        # PASUL 2: CACHE
        if domain in dns_cache:
            cached_data, expiry = dns_cache[domain]
            if time.time() < expiry:
                print(f"[CACHE] {domain}")
                cached_record = DNSRecord.parse(cached_data)
                cached_record.header.id = query_id # Adaptăm ID-ul pentru noul client
                return cached_record.pack()
            else:
                del dns_cache[domain]

        # PASUL 3: RECURSIVITATE (UPSTREAM)
        print(f"[UPSTREAM] {domain}")
        response = ask_upstream(data)
        if response:
            # Salvăm în cache pentru 60 de secunde
            dns_cache[domain] = (response, time.time() + 60)
            return response

    except Exception as e:
        print(f"[DNS ERROR] Problemă la procesarea cererii: {e}")
    return None

# --- 4. SERVER HTTP (DNS OVER HTTPS) ---

app = FastAPI()

@app.post("/dns-query")
@app.get("/dns-query")
async def doh_endpoint(request: Request):
    """Endpoint DoH conform RFC 8484."""
    body = await request.body()
    if not body:
        return Response(status_code=400, content="Cerere DNS invalidă")

    response_data = process_dns_query(body)
    if response_data:
        return Response(content=response_data, media_type="application/dns-message")
    
    return Response(status_code=500, content="Eroare internă DNS")

# --- 5. SERVER UDP (CLASIC) ---

def run_udp_server():
    """Rulează bucla infinită pentru serverul UDP pe portul 53."""
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.bind(("0.0.0.0", 53))
    print("[START] Serverul UDP pornit pe portul 53...")
    
    while True:
        try:
            data, addr = udp_sock.recvfrom(512)
            response = process_dns_query(data)
            if response:
                udp_sock.sendto(response, addr)
        except Exception as e:
            print(f"[UDP CRITICAL ERROR] {e}")

# --- MODULUL DE STATISTICI (Modular) ---

def analyze_logs():
    """Citește log-ul și returnează statistici pe companii"""
    stats = {
        "Google": 0,
        "Facebook/Meta": 0,
        "Microsoft": 0,
        "Altele": 0,
        "Total": 0
    }
    all_blocked = []

    try:
        with open(LOG_FILE, "r") as f:
            for line in f:
                # Extragem domeniul din linia de log (format: TIMESTAMP - BLOCKED - DOMAIN)
                parts = line.strip().split(" - ")
                if len(parts) < 3: continue
                
                domain = parts[2].lower()
                all_blocked.append(domain)
                stats["Total"] += 1

                # Logica de identificare a companiei (Cerința 15)
                if any(x in domain for x in ["google", "doubleclick", "youtube", "gstatic"]):
                    stats["Google"] += 1
                elif any(x in domain for x in ["facebook", "fbcd", "instagram", "fb"]):
                    stats["Facebook/Meta"] += 1
                elif any(x in domain for x in ["microsoft", "bing", "msn", "office"]):
                    stats["Microsoft"] += 1
                else:
                    stats["Altele"] += 1
        
        # Luăm top 5 cele mai blocate domenii
        top_domains = Counter(all_blocked).most_common(5)
        return stats, top_domains
    except FileNotFoundError:
        return None, None

# --- ENDPOINT-UL PENTRU PAGINA DE STATISTICI ---

@app.get("/stats", response_class=HTMLResponse)
async def get_stats_page():
    stats, top_domains = analyze_logs()
    
    if not stats:
        return "<html><body><h1>Nu există date de logare încă.</h1></body></html>"

    # Aici este partea de HTML/CSS (generată, dar integrată de tine)
    html_content = f"""
    <html>
        <head>
            <title>DNS Ad-Blocker Stats</title>
            <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
            <style>
                body {{ font-family: sans-serif; background: #f4f4f9; padding: 20px; }}
                .container {{ max-width: 800px; margin: auto; background: white; padding: 20px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
                h1 {{ color: #333; text-align: center; }}
                .stats-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 20px; }}
                .card {{ border: 1px solid #ddd; padding: 15px; border-radius: 8px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>DNS Block Analytics</h1>
                <div class="stats-grid">
                    <div class="card">
                        <h3>Sumar Companii</h3>
                        <canvas id="companyChart"></canvas>
                    </div>
                    <div class="card">
                        <h3>Top 5 Domenii Blocate</h3>
                        <ul>
                            {"".join([f"<li>{d[0]} ({d[1]} ori)</li>" for d in top_domains])}
                        </ul>
                        <p><strong>Total Cereri Blocate: {stats['Total']}</strong></p>
                    </div>
                </div>
            </div>

            <script>
                const ctx = document.getElementById('companyChart').getContext('2d');
                new Chart(ctx, {{
                    type: 'pie',
                    data: {{
                        labels: ['Google', 'Facebook/Meta', 'Microsoft', 'Altele'],
                        datasets: [{{
                            data: [{stats['Google']}, {stats['Facebook/Meta']}, {stats['Microsoft']}, {stats['Altele']}],
                            backgroundColor: ['#4285F4', '#1877F2', '#F25022', '#999']
                        }}]
                    }}
                }});
            </script>
        </body>
    </html>
    """
    return html_content

# --- 6. LANSARE ORCHESTRAȚIE ---

if __name__ == "__main__":
    # Pornim firul de execuție pentru UDP (background)
    threading.Thread(target=run_udp_server, daemon=True).start()

    # Pornim serverul web (DoH) în firul principal
    print("[START] Serverul DoH pornit pe portul 8000...")
    uvicorn.run(app, host="0.0.0.0", port=8000)