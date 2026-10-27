# The box a trial is measured in (bench/trial_collect.py builds it; docs/BENCHMARK.md says what it
# holds back). The base is held to a digest so a rebuild starts from the same system; move it on
# purpose. The wheel under test is the build context's `wheel/`, so the image id names the code.
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
ENV DEBIAN_FRONTEND=noninteractive PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends git build-essential ca-certificates libffi-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.12.15
ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python
RUN uv python install 3.9 3.10 3.11 3.12 3.13 3.14
COPY wheel/ /tmp/wheel/
RUN uv venv /opt/obelize --python 3.12 \
    && uv pip install --python /opt/obelize/bin/python /tmp/wheel/*.whl \
    && rm -r /tmp/wheel
COPY proxy.py probe.py /opt/box/
RUN useradd -m -u 10001 trial && mkdir /work && chown trial /work
USER trial
ENV PATH=/opt/obelize/bin:$PATH UV_PYTHON_DOWNLOADS=never HOME=/home/trial
RUN git config --global user.name trial \
    && git config --global user.email trial@example.invalid \
    && git config --global --add safe.directory '*'
WORKDIR /work
