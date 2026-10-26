# The MCP server (HTTP on port 8000 inside the Docker network; Caddy in docker-compose.yml is the only thing facing the internet).
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 TZ=Asia/Jerusalem
WORKDIR /app

# pytest is a development tool; playwright here is only the client that talks to the Chrome container (no browser is installed in this image)
COPY requirements.txt .
RUN grep -v '^pytest' requirements.txt > requirements.runtime.txt && pip install -r requirements.runtime.txt

COPY server.py .
COPY myt_mcp ./myt_mcp
# myt_mcp/guide.py serves quote_guide from instructions/claude_project.md
COPY instructions ./instructions

RUN useradd --create-home --uid 1000 app && mkdir -p /data && chown app:app /data
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
CMD ["python", "server.py"]
