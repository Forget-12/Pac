# ==========================================
# TAHAP 1: BUILDER CFSOLVE (Rust) — dari cfsolve.zip bundled
# ==========================================
FROM rust:bookworm AS cfsolve-builder

# Dependensi compile BoringSSL & cfsolve
RUN apt-get update && apt-get install -y \
    cmake clang libclang-dev pkg-config libssl-dev build-essential \
    golang-go git unzip \
    && rm -rf /var/lib/apt/lists/*

# Build dari arsip yang dibawa repo (self-contained, versi terpin)
COPY cfsolve.zip /tmp/cfsolve.zip
RUN unzip -q /tmp/cfsolve.zip -d /src

WORKDIR /src/cfsolve
# rust-toolchain.toml di dalam zip memilih channel terpin; rustup memasangnya.
RUN cargo build --release --bin challenge

# ==========================================
# TAHAP 2: IMAGE UTAMA (Node.js + Python)
# ==========================================
FROM node:20-slim

RUN apt-get update && apt-get install -y \
    chromium python3 python3-pip python3-venv unzip \
    fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 libc6 \
    libcairo2 libcups2 libdbus-1-3 libexpat1 libfontconfig1 libgbm1 \
    libgcc1 libglib2.0-0 libgtk-3-0 libnspr4 libnss3 libpango-1.0-0 \
    libpangocairo-1.0-0 libstdc++6 libx11-6 libx11-xcb1 libxcb1 \
    libxcomposite1 libxcursor1 libxdamage1 libxext6 libxfixes3 libxi6 \
    libxrandr2 libxrender1 libxss1 libxtst6 lsb-release wget xdg-utils \
    && rm -rf /var/lib/apt/lists/*

ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium
ENV CHROME_PATH=/usr/bin/chromium
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app
COPY package*.json ./
RUN npm install

# Virtual Environment Python
RUN python3 -m venv $VIRTUAL_ENV

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .

# --- BINARY CFSOLVE HASIL BUILD DARI ZIP ---
COPY --from=cfsolve-builder /src/cfsolve/target/release/challenge /app/cfsolve
RUN chmod +x /app/cfsolve

# Ekstrak profil perangkat (iphone-*) untuk rotasi --fingerprint
RUN unzip -o profiles.zip -d profiles || true

CMD ["node", "app.js"]
