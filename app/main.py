import socket
import time
import threading
import uvicorn
import requests  # NECESAR: Adaugă în Dockerfile
from datetime import datetime
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse
from collections import Counter
from dnslib import DNSRecord, QTYPE, RR, A

# --- 1. CONFIGURARE ---
BLOCKLIST_FILE = "/data/adlist.txt"
LOG_FILE = "/data/blocked_queries.log"
# URL-ul către lista RAW (format hosts)
REMOTE_LIST_URL = "https://raw.githubusercontent.com/anudeepND/blacklist/master/adservers.txt"

dns_cache = {}
log_lock = threading.Lock()

# --- 2. MODUL DESCĂRCARE ȘI ÎNCĂRCARE LISTĂ ---

def load_blocklist():
    """Descarcă lista de pe GitHub, o curăță și o încarcă în memorie."""
    blocklist = set()
    
    # Pasul A: Încercăm descărcarea de pe internet
    try:
        print(f"[INFO] Se descarcă lista actualizată de la: {REMOTE_LIST_URL}")
        response = requests.get(REMOTE_LIST_URL, timeout=15)
        if response.status_code == 200:
            lines = response.text.splitlines()
            for line in lines:
                line = line.strip()
                # Ignorăm comentariile și liniile goale
                if not line or line.startswith("#"):
                    continue
                
                # Curățăm formatul "0.0.0.0 domain.com" sau "127.0.0.1 domain.com"
                parts = line.split()
                # Luăm ultimul element din linie (care este domeniul)
                domain = parts[-1].lower()
                blocklist.add(domain)
            
            # Salvăm local pentru backup
            with open(BLOCKLIST_FILE, "w") as f:
                f.write("\n".join(blocklist))
            print(f"[SUCCESS] Am descărcat și curățat {len(blocklist)} domenii.")
            return blocklist
    except Exception as e:
        print(f"[⚠️ WARNING] Descărcarea a eșuat ({e}). Folosim backup-ul local.")

    # Pasul B: Dacă internetul pică, citim fișierul local
    try:
        with open(BLOCKLIST_FILE, "r") as f:
            for line in f:
                domain = line.strip().lower()
                if domain: blocklist.add(domain)
        print(f"[INFO] Backup local încărcat: {len(blocklist)} domenii.")
    except FileNotFoundError:
        print("[EROARE] Nicio listă de domenii nu a putut fi încărcată!")
    
    return blocklist

blocked_domains = load_blocklist()

# --- 3. MODUL LOGGING ---

def log_blocked_event(domain, qtype):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"{timestamp} - BLOCKED - {domain} (Type: {qtype})\n"
    with log_lock:
        try:
            with open(LOG_FILE, "a") as f:
                f.write(log_entry)
        except: pass

# --- 4. LOGICĂ DNS ȘI RECURSIVITATE ---

def ask_upstream(data):
    upstream_server = "8.8.8.8"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(2.0)
        try:
            sock.sendto(data, (upstream_server, 53))
            answer, _ = sock.recvfrom(1024)
            return answer
        except: return None

def process_dns_query(data):
    try:
        request = DNSRecord.parse(data)
        domain = str(request.q.qname).strip(".")
        query_id = request.header.id
        qtype = request.q.qtype

        # 1. Blocklist
        if domain.lower() in blocked_domains:
            print(f"[BLOCK] {domain}")
            log_blocked_event(domain, qtype)
            reply = request.reply()
            reply.add_answer(RR(rname=request.q.qname, rtype=QTYPE.A, rclass=1, ttl=60, rdata=A("0.0.0.0")))
            return reply.pack()

        # 2. Cache
        if domain in dns_cache:
            cached_data, expiry = dns_cache[domain]
            if time.time() < expiry:
                res = DNSRecord.parse(cached_data)
                res.header.id = query_id
                return res.pack()

        # 3. Upstream
        response = ask_upstream(data)
        if response:
            dns_cache[domain] = (response, time.time() + 60)
            return response
    except: return None

# --- 5. SERVERE (UDP & DoH) ---

app = FastAPI()

@app.post("/dns-query")
@app.get("/dns-query")
async def doh_endpoint(request: Request):
    body = await request.body()
    if not body: return Response(status_code=400)
    res = process_dns_query(body)
    return Response(content=res, media_type="application/dns-message") if res else Response(status_code=500)

def run_udp_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 53))
    while True:
        data, addr = sock.recvfrom(512)
        res = process_dns_query(data)
        if res: sock.sendto(res, addr)

# --- 6. STATISTICI ---

def analyze_logs():
    stats = {"Google": 0, "Facebook/Meta": 0, "Microsoft": 0, "Altele": 0, "Total": 0}
    all_blocked = []
    try:
        with open(LOG_FILE, "r") as f:
            for line in f:
                parts = line.strip().split(" - ")
                if len(parts) < 3: continue
                domain = parts[2].split(" (")[0].lower()
                all_blocked.append(domain)
                stats["Total"] += 1
                if any(x in domain for x in ["google", "doubleclick", "youtube"]): stats["Google"] += 1
                elif any(x in domain for x in ["facebook", "fbcd", "instagram"]): stats["Facebook/Meta"] += 1
                elif any(x in domain for x in ["microsoft", "bing", "msn"]): stats["Microsoft"] += 1
                else: stats["Altele"] += 1
        return stats, Counter(all_blocked).most_common(5)
    except: return None, None

@app.get("/stats", response_class=HTMLResponse)
async def get_stats_page():
    stats, top = analyze_logs()
    if not stats: return "<h1>Nu există date încă.</h1>"
    return f"""
    <html>
        <head><script src="https://cdn.jsdelivr.net/npm/chart.js"></script></head>
        <body style="font-family:sans-serif; padding:20px;">
            <h1>DNS Analytics Dashboard</h1>
            <div style="display:flex; gap:40px;">
                <div style="width:300px;"><canvas id="myChart"></canvas></div>
                <div>
                    <h3>Top 5 Blocate:</h3>
                    <ul>{"".join([f"<li>{d[0]}: {d[1]}</li>" for d in top])}</ul>
                    <p>Total: {stats['Total']}</p>
                </div>
            </div>
            <script>
                new Chart(document.getElementById('myChart'), {{
                    type: 'pie',
                    data: {{
                        labels: ['Google', 'Facebook', 'Microsoft', 'Altele'],
                        datasets: [{{ data: [{stats['Google']}, {stats['Facebook/Meta']}, {stats['Microsoft']}, {stats['Altele']}], backgroundColor: ['blue', 'navy', 'orange', 'grey'] }}]
                    }}
                }});
            </script>
        </body>
    </html>
    """

if __name__ == "__main__":
    threading.Thread(target=run_udp_server, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=8000)