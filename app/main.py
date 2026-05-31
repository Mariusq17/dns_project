import socket
import time
import threading
import uvicorn
from fastapi import FastAPI, Request, Response
from dnslib import DNSRecord, QTYPE, RR, A

# --- CONFIGURARE ȘI LOGICĂ DE BAZĂ ---

BLOCKLIST_FILE = "/data/adlist.txt"
dns_cache = {}

def load_blocklist():
    blocklist = set()
    try:
        with open(BLOCKLIST_FILE, "r") as f:
            for line in f:
                domain = line.strip().lower()
                if domain:
                    blocklist.add(domain)
        print(f"[INFO] Am încărcat {len(blocklist)} domenii în blocklist.")
    except FileNotFoundError:
        print("[EROARE] adlist.txt nu a fost găsit!")
    return blocklist

blocked_domains = load_blocklist()

def ask_upstream(data):
    upstream_server = "8.8.8.8"
    upstream_port = 53
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(2.0)
        try:
            sock.sendto(data, (upstream_server, upstream_port))
            answer, _ = sock.recvfrom(1024)
            return answer
        except socket.timeout:
            return None

# --- CREIERUL CENTRAL (Logica de Rezoluție) ---

def process_dns_query(data):
    """
    Această funcție primește pachetul binar DNS, decide ce să facă 
    și returnează pachetul binar de răspuns.
    """
    request = DNSRecord.parse(data)
    domain = str(request.q.qname).strip(".")
    query_id = request.header.id

    # 1. Verificare Blocklist
    if domain.lower() in blocked_domains:
        print(f"[BLOCK] {domain} -> 0.0.0.0")
        reply = request.reply()
        reply.add_answer(RR(rname=request.q.qname, rtype=QTYPE.A, rclass=1, ttl=60, rdata=A("0.0.0.0")))
        return reply.pack()

    # 2. Verificare Cache
    if domain in dns_cache:
        cached_data, expiry = dns_cache[domain]
        if time.time() < expiry:
            print(f"[CACHE] {domain}")
            cached_record = DNSRecord.parse(cached_data)
            cached_record.header.id = query_id # Adaptăm ID-ul
            return cached_record.pack()
        else:
            del dns_cache[domain]

    # 3. Interogare Upstream (Google)
    print(f"[UPSTREAM] {domain}")
    response = ask_upstream(data)
    if response:
        # Salvăm în cache (TTL 60 secunde implicit)
        dns_cache[domain] = (response, time.time() + 60)
        return response
    
    return None

# --- SERVERUL DNS OVER HTTPS (FastAPI) ---

app = FastAPI()

@app.post("/dns-query")
@app.get("/dns-query")
async def doh_endpoint(request: Request):
    # DoH transmite query-ul binar în body (POST) sau ca parametru (GET)
    # Standardul RFC 8484 recomandă POST pentru pachete binare
    body = await request.body()
    
    if not body:
        return Response(status_code=400, content="Cerere DNS invalida")

    response_data = process_dns_query(body)
    
    if response_data:
        return Response(
            content=response_data, 
            media_type="application/dns-message"
        )
    return Response(status_code=500, content="Eroare DNS")

# --- SERVERUL DNS CLASIC (UDP) ---

def run_udp_server():
    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.bind(("0.0.0.0", 53))
    print("[START] Serverul UDP ascultă pe portul 53...")
    
    while True:
        try:
            data, addr = udp_sock.recvfrom(512)
            response = process_dns_query(data)
            if response:
                udp_sock.sendto(response, addr)
        except Exception as e:
            print(f"[UDP ERROR] {e}")

# --- PORNIREA ORCHESTRAȚIEI ---

if __name__ == "__main__":
    # 1. Pornim serverul UDP într-un thread separat
    # daemon=True înseamnă că thread-ul moare dacă programul principal se închide
    threading.Thread(target=run_udp_server, daemon=True).start()

    # 2. Pornim serverul HTTP (DoH) în thread-ul principal
    print("[START] Serverul DoH ascultă pe portul 8000...")
    uvicorn.run(app, host="0.0.0.0", port=8000)