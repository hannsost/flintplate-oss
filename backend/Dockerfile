FROM python:3.12-slim

WORKDIR /app

# System dependencies
# - libpq-dev: asyncpg
# - tesseract-ocr + poppler-utils: OCR pipeline (Sprint 0.3)
# - libgl1 + libglib2.0: Pillow / pdf2image
# - libpango + libcairo + libgdk-pixbuf: WeasyPrint PDF export (Sprint 0.7)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    tesseract-ocr \
    tesseract-ocr-deu \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    libxml2 \
    libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade "pip>=26.2" "setuptools>=84"

# Pre-install torch CPU-only (~800 MB) before the rest of deps
# This avoids pulling the GPU variant via sentence-transformers
RUN pip install --no-cache-dir \
    torch==2.14.0+cpu \
    --index-url https://download.pytorch.org/whl/cpu

# Copy project definition and install all dependencies (non-editable for prod)
COPY pyproject.toml ./
COPY constraints-py312.txt ./
RUN pip install --no-cache-dir -c constraints-py312.txt ".[dev]"

# Copy source code (after deps for better layer caching)
COPY . .

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
