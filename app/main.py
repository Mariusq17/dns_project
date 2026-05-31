from dnslib import DNSRecord, DNSHeader, RR, A
import socket

def handle_dns_request(data, addr, socket):
    # Parsăm datele binare primite în obiect DNS
    request = DNSRecord.parse(data)
    domain = str(request.q.qname).strip(".")
    
    print(f"Căutare pentru: {domain}")

    # AICI va veni logica de Ad-block
    # if domain in blocklist: ...

    # Exemplu de răspuns manual cu 0.0.0.0
    reply = request.reply()
    reply.add_answer(RR(domain, rdata=A("0.0.0.0"), ttl=60))
    
    socket.sendto(reply.pack(), addr)

# Configurăm serverul UDP
UDP_IP = "0.0.0.0"
UDP_PORT = 53

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP, UDP_PORT))

print("Serverul DNS pornit...")
while True:
    data, addr = sock.recvfrom(512) # Pachetele DNS au de obicei sub 512 bytes
    handle_dns_request(data, addr, sock)