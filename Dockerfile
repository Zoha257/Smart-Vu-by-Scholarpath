# Optional containerized deployment of the Admin App on the Oracle Cloud
# Always Free VM. Even inside a container, the port mapping on the HOST
# must stay bound to 127.0.0.1 (Section 18.5) — see README "Private network
# binding" for the exact `docker run -p 127.0.0.1:8001:8001 ...` command.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recursive \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8001

# NEVER change this to 0.0.0.0 in a way that gets published on a public
# interface at the docker run/compose level — see README Section 18.5 notes.
CMD ["python", "admin_main.py"]
