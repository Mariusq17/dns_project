# DNS Ad-Blocker Project (Custom Implementation)

## Etapa 1: Configurarea mediului de dezvoltare și a infrastructurii Docker

### Obiectiv
Crearea unui mediu izolat și reproductibil folosind Docker pentru a rula un server DNS personalizat scris în Python.

### Arhitectura Sistemului
1. **Host (Windows/macOS):** Trimite cereri DNS pe portul 53.
2. **Docker Compose:** Redirecționează traficul de pe portul 53 (Host) către containerul nostru.
3. **Container (Ubuntu/Python):** Rulează scriptul `main.py` care procesează pachetele DNS.

### Tehnologii utilizate
- **Docker & Docker Compose:** Pentru containerizare și orchestrare.
- **Python 3.10:** Limbajul de programare pentru logica serverului.
- **dnslib:** O librărie Python folosită pentru a parsa (interpreta) pachetele binare DNS.

### Fișiere de configurare
- `Dockerfile`: Definește imaginea de bază (Python slim) și instalează dependențele.
- `docker-compose.yml`: Configurează maparea porturilor și volumele de date.
- `app/main.py`: Punctul de intrare al aplicației care deschide un socket UDP pe portul 53.

### Cum funcționează (Pas cu Pas)
1. Pornim serviciul cu `docker-compose up --build`.
2. Scriptul Python deschide un **Socket UDP** (un canal de comunicare) pe portul 53.
3. Când executăm `nslookup` pe host, Windows trimite un pachet binar către container.
4. Serverul Python primește pachetul, îl decodifică și afișează domeniul cerut în consolă.