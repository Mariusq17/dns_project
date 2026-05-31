import socket
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
    # Parsăm pachetul binar primit
    request = DNSRecord.parse(data)
    # Extragem numele domeniului (ex: google.com.) și scoatem punctul final
    domain = str(request.q.qname).strip(".")
    
    print(f"[QUERY] Cerere pentru: {domain}")

    # 2. Verificăm dacă domeniul este în lista neagră
    if domain.lower() in blocked_domains:
        print(f"[BLOCKED] Domeniu blocat: {domain}")
        
        # Construim răspunsul DNS cu IP-ul 0.0.0.0
        reply = request.reply()
        # RR = Resource Record, A = Adresă IPv4
        reply.add_answer(RR(rname=request.q.qname, rtype=QTYPE.A, rclass=1, ttl=60, rdata=A("0.0.0.0")))
        
        # Trimitem pachetul binar înapoi la client
        sock.sendto(reply.pack(), addr)
    else:
        # --- AICI ESTE MODIFICAREA ---
        print(f"[PASS] {domain} -> Întrebăm Google DNS...")
        
        # Facem cererea recursivă
        actual_answer = ask_upstream(data)
        
        if actual_answer:
            # Trimitem răspunsul primit de la Google direct înapoi la client
            sock.sendto(actual_answer, addr)
        # -----------------------------

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