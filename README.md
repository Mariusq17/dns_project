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

## Etapa 2: Implementarea Logicii de Blocking (Sinkhole)

### Obiectiv
Filtrarea cererilor DNS pe baza unei liste predefinite de domenii (Ad-list) și returnarea adresei `0.0.0.0` pentru acestea.

### Detalii Implementare
1. **Gestionarea Listei Negre:**
   - Lista este stocată într-un fișier extern (`/data/adlist.txt`), mapat prin Docker Volumes.
   - La pornire, serverul încarcă domeniile într-un obiect de tip `set` în Python. Am ales `set` pentru o complexitate de căutare de **O(1)**, asigurând performanță ridicată indiferent de mărimea listei.
   
2. **Procesarea Cererii:**
   - Folosim librăria `dnslib` pentru a deserializa pachetul UDP binar.
   - Comparăm domeniul extras (`QNAME`) cu elementele din `set`.
   
3. **Răspunsul DNS:**
   - Dacă domeniul este blocat, generăm un nou pachet DNS (Reply) care conține un record de tip **A** cu valoarea `0.0.0.0`.
   - Acest IP este o destinație "moartă", ceea ce face ca browserul sau aplicația client să renunțe imediat la încărcarea resursei respective.

   ## Etapa 3: Implementarea Mecanismului de Recursivitate (Forwarding)

### Obiectiv
Asigurarea funcționalității de rezoluție DNS pentru domeniile legitime (care nu se află în blocklist), prin interogarea unor servere DNS upstream (ex: Google DNS - 8.8.8.8).

### Detalii Implementare
1. **Apeluri Recursive (Recursive Queries):**
   - În momentul în care un domeniu primește "PASS" de la filtrul de blocare, serverul nostru preia rolul de client DNS.
   - Am implementat funcția `ask_upstream(data)`, care deschide un nou socket UDP temporar și trimite pachetul binar original către serverul `8.8.8.8` pe portul 53.

2. **Gestiunea Socket-urilor:**
   - Serverul principal rămâne deschis pentru a asculta noi cereri, în timp ce interogarea externă este gestionată separat.
   - Am implementat un mecanism de **Timeout** (2 secunde) pentru cererile către internet, pentru a preveni blocarea serverului nostru în cazul în care conexiunea externă este lentă sau indisponibilă.

3. **Transparent Proxying:**
   - O particularitate a acestei implementări este că serverul nostru nu mai parsează din nou răspunsul primit de la Google.
   - Deoarece răspunsul de la `8.8.8.8` este deja un pachet DNS valid și complet, serverul nostru îl retransmite (forward) direct către clientul inițial (Windows/Browser). Aceasta este o metodă eficientă și rapidă de operare.

### Verificare Proiect
- **Domeniu Blocat (facebook.com):** Serverul răspunde local cu `0.0.0.0`, blocând accesul.
- **Domeniu Legitim (youtube.com):** Serverul trimite cererea la Google, primește IP-urile reale ale YouTube și le trimite înapoi la client. Rezultatul este vizibil instant în terminal prin comanda `nslookup`.

## Etapa 4: Implementarea mecanismului de Caching

### Obiectiv
Reducerea latenței și a numărului de cereri către serverele DNS externe prin stocarea temporară a răspunsurilor valide în memoria RAM.

### Detalii Implementare
1. **Stocarea Datelor:**
   - Am utilizat un dicționar Python (`dns_cache`) pentru a mapa numele domeniilor la pachetele binare de răspuns.
   - Fiecare intrare în cache include un **Timestamp de expirare**, calculat pe baza adunării timpului curent (`time.time()`) cu un **TTL** (Time To Live).

2. **Logica de ID Matching:**
   - O provocare tehnică în implementarea cache-ului DNS este potrivirea ID-ului de tranzacție. 
   - Deoarece pachetul salvat în cache are ID-ul cererii originale, la refolosire, serverul nostru modifică header-ul pachetului binar pentru a insera ID-ul noii cereri, asigurând conformitatea cu protocolul DNS.

3. **Eficiență:**
   - Sistemul verifică mai întâi Blocklist-ul, apoi Cache-ul, și abia în ultimă instanță efectuează un apel recursiv către internet.
   - Această ierarhie minimizează traficul de rețea și oferă timpi de răspuns sub 1ms pentru cererile repetate.

Mecanismul de caching actual returnează pachetul binar stocat indiferent de tipul query-ului (A sau AAAA). Acest lucru poate duce la afișarea duplicată a IP-urilor în utilitare precum nslookup, însă nu afectează navigarea web propriu-zisă.

## Etapa 5: Integrarea DNS over HTTPS (DoH) și Multithreading

### Obiectiv
Extinderea funcționalității serverului pentru a suporta cereri prin protocolul modern DoH (RFC 8484) și rularea simultană a serviciilor UDP și HTTP.

### Detalii Implementare
1. **Arhitectura Multithreading:**
   - Deoarece Python execută codul secvențial, am utilizat modulul `threading` pentru a porni serverul UDP într-un fir de execuție secundar.
   - Serverul web (FastAPI) rulează în firul principal, gestionând conexiunile DoH pe portul 8000.

2. **Endpoint DoH (DNS over HTTPS):**
   - Am creat ruta `/dns-query` care acceptă cereri de tip `POST`.
   - Conform standardului, cererea conține pachetul DNS binar în corpul mesajului HTTP, iar răspunsul este trimis cu header-ul `Content-Type: application/dns-message`.

3. **Refactorizarea Logicii Centralizate:**
   - Pentru a evita duplicarea codului, am extras logica de procesare (Blocklist -> Cache -> Upstream) într-o funcție unică `process_dns_query`. Aceasta asigură că politicile de filtrare și caching sunt aplicate identic, indiferent de modul în care a fost primită cererea (UDP sau HTTPS).

### Cum se testează:
- **UDP:** `nslookup google.com 127.0.0.1`
- **DoH:** `curl -X POST http://localhost:8000/dns-query --data-binary @pachet_dns_exemplu` (Sau configurarea unui browser precum Firefox să folosească acest URL ca Provider DoH).

## Etapa 6: Persistența Datelor și Logging-ul Modular

### Obiectiv
Monitorizarea și salvarea activității de filtrare prin jurnalizarea cererilor blocate într-un fișier persistent pentru analize statistice ulterioare.

### Detalii Implementare
1. **Arhitectură Modulară de Logging:**
   - Am implementat funcția `log_blocked_event(domain)`, separată de logica principală de rezoluție DNS. Aceasta permite modificarea formatului de logare (ex: trecerea de la fișier text la bază de date) fără a afecta funcționarea serverului DNS.
   
2. **Thread-Safety (Gestiunea concurenței):**
   - Deoarece avem două servere (UDP și HTTP) care rulează simultan, există riscul ca ambele să încerce să scrie în fișierul de log în aceeași milisecundă.
   - Am utilizat `threading.Lock()` pentru a crea o "secțiune critică". Doar un singur thread poate deține "cheia" fișierului de log la un moment dat, prevenind coruperea datelor (race conditions).

3. **Formatul Jurnalului:**
   - Fiecare intrare conține un timestamp precis, statusul (`BLOCKED`) și numele domeniului. Acest format facilitează parsarea ulterioară pentru generarea de statistici.

### Persistența în Docker:
Fișierul de log este salvat în volumul `/data`. Astfel, chiar dacă containerul este șters și recreat, istoricul domeniilor blocate rămâne salvat pe mașina gazdă (Windows), permițând acumularea celor 100 de intrări cerute.

## Etapa 7: Analytics și Raportare (Dashboard)

### Obiectiv
Analizarea datelor colectate și generarea de statistici în timp real despre activitatea de blocking, cu identificarea marilor furnizori de tracking (Google, Facebook, Microsoft).

### Detalii Implementare
1. **Endpoint-ul `/stats`:**
   - Am adăugat o rută specială în serverul FastAPI care servește un dashboard HTML.
   - Aceasta funcționează ca un motor de analiză: deschide fișierul de log, parsează fiecare intrare și clasifică domeniile în categorii.

2. **Identificarea Companiilor (Cerința 15):**
   - Am implementat o logică de tip "Substring Matching" pentru a identifica apartenența domeniilor.
   - Exemple: `doubleclick.net` -> Google, `fbcdn.net` -> Facebook, etc.
   - Această metodă acoperă o gamă largă de subdomenii folosite pentru tracking și reclame.

3. **Vizualizarea Datelor:**
   - Pentru un aspect profesional, dashboard-ul utilizează librăria **Chart.js** (via CDN) pentru a genera un grafic de tip "Pie Chart" (plăcintă).
   - Top-ul celor mai blocate domenii este calculat folosind `collections.Counter`, oferind o perspectivă rapidă asupra celor mai agresivi trackeri din rețea.

### Rezultat:
Accesând `http://localhost:8000/stats`, utilizatorul poate vedea exact ce companii sunt blocate cel mai frecvent, îndeplinind cerința de obținere a statisticilor pentru minim 100 de intrări.