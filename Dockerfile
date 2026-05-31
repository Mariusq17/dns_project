FROM python:3.10-slim

# Instalam utilitare de retea pentru teste
RUN apt update && apt install -y dnsutils iputils-ping

WORKDIR /app

# Instalam librarii python necesare (vom folosi dnslib pentru inceput)
RUN pip install dnslib requests fastapi uvicorn

COPY . .

# Expunem portul 53 (DNS) si 8000 (pentru DoH)
EXPOSE 53/udp
EXPOSE 8000/tcp

CMD ["python", "main.py"]