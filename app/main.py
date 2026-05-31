import socket
import time
from dnslib import DNSRecord, QTYPE, RR, A

# 1. Încărcăm lista de domenii blocate
BLOCKLIST_FILE = "/data/adlist.txt"

def load_blocklist():
    blocklist = set()
    try:
        with open(BLOCKLIST_FILE, "r") as f:
            for line in f:
                domain = line.strip().lower()
                if domain:
                    blocklist.add(domain)
        print(f"[INFO] Am încărcat {len(blocklist)} domenii pentru blocare.")
    except FileNotFoundError:
        print("[EROARE] Fișierul adlist.txt nu a fost găsit!")
    return blocklist

blocked_domains = load_blocklist()


# 1. Structura pentru Cache
# Format: { "domeniu": (pachet_binar, timestamp_expirare) }
dns_cache = {}

def get_from_cache(domain):
    """Căutăm domeniul în cache și verificăm dacă a expirat"""
    if domain in dns_cache:
        answer, expiry = dns_cache[domain]
        if time.time() < expiry:
            print(f"[CACHE] Răspuns servit din memorie pentru: {domain}")
            return answer
        else:
            print(f"[CACHE] Record expirat pentru: {domain}")
            del dns_cache[domain]
    return None

def add_to_cache(domain, data, ttl=60):
    """Salvăm răspunsul în cache pentru un număr de secunde (implicit 60)"""
    expiry = time.time() + ttl
    dns_cache[domain] = (data, expiry)
    print(f"[CACHE] Salvat în cache: {domain} (TTL: {ttl}s)")


def ask_upstream(data):
    """Trimite cererea DNS către un server extern (Google DNS)"""
    upstream_server = "8.8.8.8"
    upstream_port = 53
    
    # Cream un socket UDP nou pentru a vorbi cu Google
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(2.0) # Nu așteptăm mai mult de 2 secunde după Google
        try:
            # Trimitem exact pachetul binar primit de la clientul nostru
            sock.sendto(data, (upstream_server, upstream_port))
            # Primim răspunsul binar de la Google
            answer, _ = sock.recvfrom(1024)
            return answer
        except socket.timeout:
            print("[EROARE] Google DNS nu a răspuns la timp.")
            return None


def handle_dns_request(data, addr, sock):
    request = DNSRecord.parse(data)
    domain = str(request.q.qname).strip(".")
    
    # Pasul 1: Verificăm Blocklist
    if domain.lower() in blocked_domains:
        print(f"[BLOCKED] {domain} -> 0.0.0.0")
        reply = request.reply()
        reply.add_answer(RR(rname=request.q.qname, rtype=QTYPE.A, rclass=1, ttl=60, rdata=A("0.0.0.0")))
        sock.sendto(reply.pack(), addr)
        return

    # Pasul 2: Verificăm Cache
    cached_response = get_from_cache(domain)
    if cached_response:
        # Trebuie să modificăm ID-ul pachetului din cache pentru a se potrivi cu noua cerere
        # Altfel, clientul (Windows) va crede că e un răspuns la altă întrebare
        cached_record = DNSRecord.parse(cached_response)
        cached_record.header.id = request.header.id
        sock.sendto(cached_record.pack(), addr)
        return

    # Pasul 3: Dacă nu e în cache, întrebăm Google
    print(f"[PASS] {domain} -> Întrebăm Google DNS...")
    actual_answer = ask_upstream(data)
    
    if actual_answer:
        # Salvăm în cache pentru viitor înainte de a trimite
        add_to_cache(domain, actual_answer, ttl=60)
        sock.sendto(actual_answer, addr)

# Configurare Socket UDP
UDP_IP = "0.0.0.0"
UDP_PORT = 53

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))

print(f"[START] Serverul DNS ascultă pe portul {UDP_PORT}...")

while True:
    try:
        data, addr = sock.recvfrom(512)
        handle_dns_request(data, addr, sock)
    except Exception as e:
        print(f"[EROARE] A apărut o problemă: {e}")