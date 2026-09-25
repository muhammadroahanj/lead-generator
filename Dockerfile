# Official image: Python + baseline OS packages for browsers.
# Keep the image tag and `playwright==` in requirements.txt on the same release.
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

WORKDIR /app

ENV DEBIAN_FRONTEND=noninteractive

COPY requirements.txt .
# pip: app deps. Then install Chromium build + apt packages Playwright expects for this version.
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install chromium --with-deps

COPY . .

# Default: non-interactive headless run (override in docker-compose or `docker run`).
CMD ["python", "main.py", "--headless", "-y"]
