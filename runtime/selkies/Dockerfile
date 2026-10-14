FROM python@sha256:9bed8554e926c07c6f908841d5ee88c33e8df9236b191526bbce81a9062ab43a
RUN apt-get update && apt-get install --no-install-recommends -y \
    xvfb xclip xdotool libgbm1 libegl1 libxkbcommon0 libxkbcommon-x11-0 \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libatspi2.0-0 libxcomposite1 \
    libxdamage1 libxrandr2 libasound2 libcups2 libdrm2 libpulse0 \
    libwayland-server0 libwayland-client0 libva2 libva-drm2 libva-x11-2 \
    libxcursor1 libxi6 libxfixes3 libxtst6 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*
COPY selkies-src /build/src
COPY pyproject.toml README.md LICENSE /build/
COPY requirements.txt /build/requirements.txt
RUN python -m pip install --no-cache-dir -r /build/requirements.txt && python -m pip install --no-cache-dir --no-deps /build && python -m pip check && python -m pip freeze > /opt/python-dependencies.txt
COPY selkies-web /opt/selkies-web
COPY browser /opt/browser
COPY candidate /opt/candidate
COPY build-inputs.json /opt/build-inputs.json
COPY client-source /opt/selkies-client-source
RUN useradd --uid 1000 --create-home radhouse && mkdir /state && chown radhouse /state
USER radhouse
ENV RADHOUSE_BROWSER_MODE=fixture HOME=/home/radhouse LANG=C.UTF-8
WORKDIR /opt/candidate
EXPOSE 8080
ENTRYPOINT ["python", "runtime/selkies/qualification.py"]
