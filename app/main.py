import socket
import time
import threading
import uvicorn
import requests
import os
import json
import secrets
from datetime import datetime
from fastapi import FastAPI, Request, Response, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from collections import Counter
from dnslib import DNSRecord, QTYPE, RR, A

# --- 1. CONFIGURARE ---
# Fallback pentru folderul de date: '/data' (Docker) sau 'data' (Local Windows)
DATA_DIR = "/data" if os.path.isdir("/data") else "data"
os.makedirs(DATA_DIR, exist_ok=True)

BLOCKLIST_FILE = f"{DATA_DIR}/adlist.txt"
LOG_FILE = f"{DATA_DIR}/blocked_queries.log"
ALLOWED_IPS_FILE = f"{DATA_DIR}/allowed_ips.json"
REMOTE_LIST_URL = "https://raw.githubusercontent.com/anudeepND/blacklist/master/adservers.txt"

# Variabile de mediu pentru panoul de control
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "admin")

ALLOWED_IPS = set(["127.0.0.1"])
dns_cache = {}
log_lock = threading.Lock()

# --- 2. PERSISTENTA IP-URI ---
def load_allowed_ips():
    global ALLOWED_IPS
    # 1. Incarcam IP-urile din variabilele de mediu
    env_ips = os.environ.get("ALLOWED_IPS", "")
    for ip in env_ips.split(","):
        if ip.strip(): ALLOWED_IPS.add(ip.strip())
    
    # 2. Incarcam IP-urile din fisierul JSON (daca exista)
    if os.path.exists(ALLOWED_IPS_FILE):
        try:
            with open(ALLOWED_IPS_FILE, "r") as f:
                saved_ips = json.load(f)
                ALLOWED_IPS.update(saved_ips)
        except Exception as e:
            print(f"[ERROR] Nu am putut citi {ALLOWED_IPS_FILE}: {e}")

def save_allowed_ips():
    with log_lock:
        try:
            with open(ALLOWED_IPS_FILE, "w") as f:
                json.dump(list(ALLOWED_IPS), f)
        except Exception as e:
            print(f"[ERROR] Nu am putut salva {ALLOWED_IPS_FILE}: {e}")

# Initializare IP-uri la pornire
load_allowed_ips()

# --- 3. GESTIONARE LISTA DOMENII BLOCATE ---
def load_blocklist():
    blocklist = set()
    try:
        print(f"[INFO] Se descarca lista de la: {REMOTE_LIST_URL}")
        response = requests.get(REMOTE_LIST_URL, timeout=15)
        if response.status_code == 200:
            for line in response.text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"): continue
                domain = line.split()[-1].lower()
                blocklist.add(domain)
            
            # Salvam lista local pentru backup
            with open(BLOCKLIST_FILE, "w") as f: f.write("\n".join(blocklist))
            print(f"[SUCCESS] {len(blocklist)} domenii incarcate.")
            return blocklist
    except Exception as e:
        print(f"[WARNING] Descarcare esuata. {e}")
    
    # Incarcare din backup local in caz de eroare la descarcare
    try:
        with open(BLOCKLIST_FILE, "r") as f:
            for line in f:
                if line.strip(): blocklist.add(line.strip().lower())
    except: pass
    
    return blocklist

blocked_domains = load_blocklist()

# --- 4. LOGGING ---
def log_blocked_event(domain, qtype):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"{timestamp} - BLOCKED - {domain} (Type: {qtype})\n"
    with log_lock:
        try:
            with open(LOG_FILE, "a") as f:
                f.write(log_entry)
        except: pass

# --- 5. LOGICA DNS ---
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

        # Verificam daca domeniul este in lista de blocare
        if domain.lower() in blocked_domains:
            log_blocked_event(domain, qtype)
            reply = request.reply()
            reply.add_answer(RR(rname=request.q.qname, rtype=QTYPE.A, rclass=1, ttl=60, rdata=A("0.0.0.0")))
            return reply.pack()

        # Verificam daca raspunsul este deja in cache
        if domain in dns_cache:
            cached_data, expiry = dns_cache[domain]
            if time.time() < expiry:
                res = DNSRecord.parse(cached_data)
                res.header.id = query_id
                return res.pack()

        # Intrebam serverul extern (upstream) daca nu gasim in cache
        response = ask_upstream(data)
        if response:
            dns_cache[domain] = (response, time.time() + 60)
            return response
    except: return None

# --- 6. SERVERE API / HTTP ---
app = FastAPI()
security = HTTPBasic()
templates = Jinja2Templates(directory="app/templates")

def get_current_username(credentials: HTTPBasicCredentials = Depends(security)):
    correct_username = secrets.compare_digest(credentials.username, ADMIN_USER)
    correct_password = secrets.compare_digest(credentials.password, ADMIN_PASS)
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

@app.post("/dns-query")
@app.get("/dns-query")
async def doh_endpoint(request: Request):
    body = await request.body()
    if not body: return Response(status_code=400)
    res = process_dns_query(body)
    return Response(content=res, media_type="application/dns-message") if res else Response(status_code=500)

# Serverul UDP standard pentru DNS (port 53)
def run_udp_server():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 53))
    print("[INFO] Server UDP pornit.")
    while True:
        data, addr = sock.recvfrom(512)
        # Filtram cererile DNS folosind Whitelist-ul
        if addr[0] not in ALLOWED_IPS and "*" not in ALLOWED_IPS:
            continue
        res = process_dns_query(data)
        if res: sock.sendto(res, addr)

# --- 7. ADMIN DASHBOARD ---

@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request, username: str = Depends(get_current_username)):
    return templates.TemplateResponse(request=request, name="admin.html")

@app.get("/admin/api/stats")
async def api_stats(username: str = Depends(get_current_username)):
    all_blocked = []
    total = 0
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r") as f:
                for line in f:
                    parts = line.strip().split(" - ")
                    if len(parts) >= 3:
                        domain = parts[2].split(" (")[0].lower()
                        all_blocked.append(domain)
                        total += 1
    except: pass
    
    # Generam top 10 domenii blocate
    top_10 = [{"domain": k, "count": v} for k, v in Counter(all_blocked).most_common(10)]
    return {"total": total, "top": top_10}

@app.get("/admin/api/ips")
async def api_get_ips(username: str = Depends(get_current_username)):
    return list(ALLOWED_IPS)

@app.post("/admin/api/ips")
async def api_add_ip(request: Request, username: str = Depends(get_current_username)):
    data = await request.json()
    ip = data.get("ip")
    if ip:
        ALLOWED_IPS.add(ip.strip())
        save_allowed_ips()
        return {"status": "success"}
    raise HTTPException(status_code=400, detail="Invalid IP")

@app.delete("/admin/api/ips/{ip}")
async def api_delete_ip(ip: str, username: str = Depends(get_current_username)):
    if ip in ALLOWED_IPS:
        ALLOWED_IPS.remove(ip)
        save_allowed_ips()
        return {"status": "success"}
    raise HTTPException(status_code=404, detail="IP not found")

@app.get("/admin/api/logs")
async def api_get_logs(username: str = Depends(get_current_username)):
    logs = []
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r") as f:
                # Citim doar ultimele 50 de cereri pentru performanta
                lines = f.readlines()[-50:]
                for line in reversed(lines):
                    parts = line.strip().split(" - ")
                    if len(parts) >= 3:
                        domain_part = parts[2].split(" (Type: ")
                        if len(domain_part) == 2:
                            logs.append({
                                "timestamp": parts[0],
                                "domain": domain_part[0].replace("BLOCKED - ", "").strip(),
                                "type": domain_part[1].replace(")", "")
                            })
    except: pass
    return logs

if __name__ == "__main__":
    threading.Thread(target=run_udp_server, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=8000)