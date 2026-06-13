# Retele Project: DNS Ad-Blocker over HTTPS (DoH) & Admin Shield

Un sistem complet si autonom de blocare a reclamelor (Ad-Blocker DNS) inspirat din modelul Pi-hole. Proiectul filtreaza cererile DNS folosind o lista dinamica de trackere si reclame, oferind atat suport clasic DNS (UDP port 53), cat si securitate moderna prin DNS over HTTPS (DoH). 

Proiectul include un **Dashboard de Administrare Premium** protejat prin parola, construit cu Tailwind CSS si Chart.js, care permite gestionarea adreselor IP premise si vizualizarea logurilor si a statisticilor in timp real.

---

## 🎯 Cerintele Proiectului Indeplinite

Acest proiect acopera integral cerintele temei "Ad Blocker DNS (over HTTPS)":
- [x] **Aplicatie DNS Resolver:** Dezvoltata in Python (`main.py`) capabila sa parseze si sa raspunda la cereri DNS.
- [x] **Functional (Fara a implementa tot protocolul):** Raspunde precis si eficient pentru interceptari tip A, fara bloatware.
- [x] **Mecanism de Caching:** Pachetele rezolvate cu succes sunt salvate in memorie (`dns_cache`) pentru 60 de secunde, accelerand cererile recurente la sub 1 milisecunda.
- [x] **Apeluri Recursive (Forwarding):** Daca un domeniu nu este nici blocat, nici in cache, serverul redirectioneaza cererea (forward) catre un upstream extern (`8.8.8.8`) si livreaza pachetul inapoi clientului original.
- [x] **Lista Curatoriata de Reclame:** La pornire, serverul descarca automat si parseaza o [lista recunoscuta (AnudeepND)](https://raw.githubusercontent.com/anudeepND/blacklist/master/adservers.txt).
- [x] **Blocare Efectiva:** Pentru orice domeniu blocat, serverul injecteaza raspunsul `0.0.0.0` (metoda "Sinkhole").

---

## 🚀 Functionalitati (Features)

1. **Dual Protocol (DNS & DoH):**
   - Asculta pe UDP:53 pentru cereri DNS obisnuite.
   - Asculta pe HTTP(S) prin ruta `/dns-query` pentru DNS-over-HTTPS, integrand un Reverse Proxy prin Nginx.
2. **"Admin Shield" Dashboard (Port 8000 / `/admin`):**
   - Interfata superba si responsiva (Tailwind CSS, Dark Mode).
   - Securitate Basic Auth pe toate rutele de administrare.
   - Grafice Live (Chart.js) cu topul domeniilor blocate.
3. **Sistem Persistent de Whitelist (IP-uri Permise):**
   - Protejeaza serverul de a deveni un *Open Resolver* vulnerabil atacurilor DDoS. Doar IP-urile trecute in lista permit interogari pe portul 53.
   - IP-urile adaugate in Web UI sunt salvate in `/data/allowed_ips.json` - astfel nu se pierd la un eventual restart al VPS-ului.
4. **Logare si Monitorizare Multithreaded:**
   - Fir separat de executie (Thread) pentru UDP DNS si pentru serverul HTTP FastAPI. Gestiune sigura a scrierilor in fisier (`blocked_queries.log`) folosind un `threading.Lock()`.
5. **Auto-SSL Certificate:**
   - Integreaza `acme-companion` in Docker pentru a genera complet automat si reinnoi certificate SSL Let's Encrypt pentru domeniul aplicatiei.

---

## 🛠️ Tehnologii Utilizate

### Core / Backend
- **Python 3.10**: Logica principala.
- **FastAPI & Uvicorn**: Framework web de inalta performanta folosit pentru panoul de admin si pentru endpoint-ul DoH (`/dns-query`).
- **dnslib**: Librarie pentru parsarea bi-directionala a formatului binar DNS (RFC 1035).
- **Jinja2**: Motor de randare (templating) pentru interfata HTML a panoului de admin.
- **Requests**: Pentru extragerea (fetching-ul) dinamic al listei de adservere la initializare.

### Frontend
- **Tailwind CSS (via CDN)**: Pentru o stilizare curata, design minimalist, cu suport de Dark Mode.
- **Chart.js (via CDN)**: Vizualizarea interactiva si animata a top 10 trackere blocate.
- **Vanilla JavaScript**: Fetch API asincron pentru preluarea de loguri si management IP fara a fi necesar un refresh al paginii (SPA feeling).

### Infrastructura & DevOps
- **Docker & Docker Compose**: Containerizare la cheie.
- **Nginx-Proxy (jwilder)**: Reverse proxy automat care trimite traficul porturilor 80/443 catre containerul intern de Python (port 8000).
- **acme-companion**: Solutie de automatizare Let's Encrypt.

---

## ⚙️ Arhitectura Sistemului

1. Traficul Web (`https://domeniul.tau`) loveste containerul Nginx. Nginx-ul decripteaza SSL-ul si il trimite mai departe spre containerul `dns-server` (port 8000).
2. Traficul DNS clasic loveste VPS-ul direct pe portul 53 UDP. Portul este mapat din VPS fix in containerul `dns-server` (port 53).
3. In interiorul `dns-server`, scriptul `main.py` foloseste Multithreading: 
   - *Thread 1* (FastAPI / Uvicorn): Se ocupa de rutele `/admin` si rutele DoH `/dns-query`.
   - *Thread 2* (Socket Raw UDP): Asculta continuu portul 53, parsand pachetele cu `dnslib`.

---

## 🏁 Ghid Pas cu Pas de Deploy (VPS Linux)

### 1. Pre-conditii
- Un domeniu web achizitionat (ex: `reteleproject.software`).
- Domeniul are un **record DNS "A"** creat in zona sa de administrare, care pointeaza care IP-ul public al VPS-ului tau.
- VPS cu Ubuntu/Debian pe care este instalat `docker.io` si `docker-compose`.

### 2. Configurarea
Cloneaza sau copiaza acest cod intr-un folder pe VPS (ex: `/root/dns_project`).
Deschide fisierul `docker-compose.yaml` si configureaza:
1. **`VIRTUAL_HOST` / `LETSENCRYPT_HOST`**: Pune numele domeniului tau.
2. **`DEFAULT_EMAIL`**: Pune o adresa ta de mail.
3. **`ADMIN_USER`** si **`ADMIN_PASS`**: Parola de logare in Admin Panel.
4. **`ALLOWED_IPS`**: Introdu adresa `127.0.0.1` si, esential, **Adresa IP Publica a locatiei tale de acasa** despartite prin virgula, pentru a-ti oferi permisiunea de a folosi serverul.

### 3. Lansarea Mediului Docker
Intra in folderul proiectului si ruleaza:
```bash
docker-compose up -d --build
```
*Observatie:* Containerul `acme-companion` are nevoie de 1-3 minute in fundal pentru a se autentifica la Let's Encrypt si a-ti genera certificatul HTTPS valid.

---

## 🧪 Ghid de Testare si Utilizare

### 1. Testarea Admin Panel-ului
- Acceseaza **`https://[domeniul_tau]/admin`** in browser.
- O fereastra pop-up de login Basic Auth va aparea. Introdu credentialele (ex: `admin` / `superparola123`).
- In sectiunea "IP Whitelist" testeaza adaugarea unui IP nou. In spate, acest IP este salvat direct si se aplica in timp real peste filtrul de socket UDP.
- In sectiunea "Live Logs" vei vedea ultimele 50 de atacuri sau interogari blocate.

### 2. Testarea DNS Clasic (de acasa)
Asigura-te ca IP-ul tau curent este listat in Admin Panel la sectiunea IP Whitelist. Daca e acolo, deschide un terminal (pe Windows) si ruleaza:
```bash
# Testeaza un domeniu legitim
nslookup google.com [IP_VPS_SAU_DOMENIU]

# Testeaza un domeniu blocat (din lista reclamelor)
nslookup doubleclick.net [IP_VPS_SAU_DOMENIU]
# Asteptari: Va returna adresa 0.0.0.0
```

### 3. Testarea DNS over HTTPS (DoH)
Cel mai puternic mod de a folosi serverul este DoH direct din browser (unde nu ai nevoie ca IP-ul tau sa fie in Whitelist, deoarece Nginx expune doar HTTP si tu beneficiezi de securitate prin criptare):
- Intra in **Mozilla Firefox** > **Settings** > **Privacy & Security** > **DNS over HTTPS**.
- Alege "Max Protection" si la Provider alege "Custom".
- Introdu adresa URL a serverului tau: `https://[domeniul_tau]/dns-query`
- Gata! Navigheaza pe internet in mod securizat. Reclamele, pop-up-urile invizibile si trackerele vor incepe instantaneu sa apara ca "Blocked" in Admin Panel-ul tau.