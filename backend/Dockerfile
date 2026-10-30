FROM python:3.13-slim AS deps

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-install-project


# De browser hangt alleen aan de playwright-versie in uv.lock, niet aan de
# applicatiecode. Stond de download onderaan, onder de COPY van /app, dan
# maakte elke commit hem opnieuw: een nieuwe digest van 106 MiB die het
# register apart opslaat. Vanuit `deps` erft deze stage dezelfde versie als
# de runtime, dus er kan geen versienummer uit de pas lopen.
FROM deps AS playwright
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN /app/.venv/bin/playwright install chromium-headless-shell


# Het sprekermodel waarmee de debat-tijdlijn stemmen uit elkaar houdt
# (WeSpeaker ResNet34-LM, CC BY 4.0). 26 MB aan binair bestand hoort niet
# in git, dus het wordt hier opgehaald: vastgepind op een revisie en op de
# SHA-256 van het bestand, beide in het script. Een eigen stage, zodat de
# laag alleen opnieuw wordt gemaakt als het script verandert.
#
# Lukt de download niet, dan slaagt de build toch en is de map leeg: de
# tijdlijn zet een regel dan op tijd bij een spreker, zoals voorheen. Klopt
# de checksum niet, dan faalt de build.
FROM python:3.13-slim AS stemmodel
COPY scripts/fetch_stem_model.py /tmp/fetch_stem_model.py
RUN python /tmp/fetch_stem_model.py /models/voxceleb_resnet34_LM.onnx


FROM deps AS builder

COPY . .
RUN uv sync --frozen


FROM python:3.13-slim

# Playwright runtime deps voor headless chromium (ABD-scrape). De browser
# zelf komt uit de playwright-stage hierboven en staat in /ms-playwright.
RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-client \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libdrm2 libdbus-1-3 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxext6 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI: de enige route waarlangs een abonnementstoken
# (CLAUDE_CODE_OAUTH_TOKEN uit `claude setup-token`) werkt. De Anthropic SDK
# accepteert dat token niet, dus zonder deze binary valt de LLM-laag terug
# op een API-sleutel die per token afrekent. De install faalt zacht: een
# image zonder CLI werkt gewoon, alleen die ene route niet.
#
# npm gaat er na de install weer uit (de CLI draait op node, niet op npm),
# en de apt-lists worden binnen dezelfde laag opgeruimd — ook op het
# faalpad, anders houdt een mislukte install de cache in de image.
RUN set -eux; \
    { apt-get update \
      && apt-get install -y --no-install-recommends nodejs npm \
      && npm install -g @anthropic-ai/claude-code \
      && apt-get purge -y npm \
      && apt-get autoremove -y; } \
    || echo "Claude CLI install gefaald; abonnementsroute niet beschikbaar"; \
    rm -rf /var/lib/apt/lists/* /root/.npm /tmp/*

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
COPY --from=playwright /ms-playwright /ms-playwright

# Leesbaar voor elke UID: ZAD/OpenShift draait de container vaak onder een
# willekeurige gebruiker.
COPY --from=stemmodel /models /models
ENV DEBAT_STEM_MODEL_PATH=/models/voxceleb_resnet34_LM.onnx

RUN useradd --create-home --uid 1001 appuser && \
    mkdir -p /data/bijlagen/chat /data/bijlagen/leads /data/bijlagen/taken && \
    chgrp -R 0 /data && \
    chmod -R g=u /data

# De Claude CLI schrijft zijn configuratie in $HOME. ZAD/OpenShift draait
# de container vaak onder een willekeurige UID uit groep 0, en dan is $HOME
# `/` en niet schrijfbaar — de CLI faalt dan op elke call. Deze map is
# groepschrijfbaar volgens hetzelfde patroon als /data, en `entrypoint.sh`
# wijst HOME hierheen als het bestaande HOME niet schrijfbaar is.
RUN mkdir -p /home/claude && \
    chgrp -R 0 /home/claude && \
    chmod -R g=u /home/claude

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY --from=builder --chown=appuser:appuser /app /app
# age-recipients.txt is copied into the build context by CI; wildcard
# makes it optional for local builds where encryption is not needed.
COPY --chown=appuser:appuser age-recipients.tx[t] /app/

USER 1001

# Activate venv via PATH — entrypoint uses python/alembic/uvicorn directly
ENV PATH="/app/.venv/bin:$PATH"

# Force unbuffered stdout/stderr — without this Python buffers when stdout
# is not a TTY, so the worker's log lines (and crash tracebacks) sit in the
# buffer until the process exits, making operational issues invisible.
ENV PYTHONUNBUFFERED=1

ARG GIT_SHA=""
ARG BUILD_TIME=""
ENV GIT_SHA=$GIT_SHA
ENV BUILD_TIME=$BUILD_TIME

EXPOSE 8080

ENTRYPOINT ["sh", "/app/entrypoint.sh"]
