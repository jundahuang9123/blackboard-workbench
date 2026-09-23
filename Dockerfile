# Keep the semantic-typing implementation external and versioned.
FROM python:3.11-slim

ARG SAST_REPO=https://github.com/U0iS112/654321.git
ARG SAST_REF=074ddfc409bdd120c93a0b68773bafa464e56504

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib \
    XDG_CACHE_HOME=/tmp/.cache

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --no-checkout "${SAST_REPO}" /opt/sast \
    && git -C /opt/sast checkout --detach "${SAST_REF}" \
    && test "$(git -C /opt/sast rev-parse HEAD)" = "${SAST_REF}" \
    && test -f /opt/sast/blackboard/codebase/core/blackboard_semantic_mapping.py \
    && test -f /opt/sast/requirements.txt

# Install only packages imported by the pipeline path used here. Sebastian's
# full requirements also include unrelated local-model libraries.
COPY requirements-upstream-runtime.txt /tmp/requirements-upstream-runtime.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements-upstream-runtime.txt

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY blackboard_workbench ./blackboard_workbench
RUN python -m pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 workbench \
    && mkdir -p /var/lib/blackboard-workbench \
    && chown workbench:workbench /var/lib/blackboard-workbench \
    && chown -R workbench:workbench /opt/sast \
    && python -c "import sys; sys.path.insert(0, '/opt/sast'); from blackboard.codebase.core import blackboard_semantic_mapping"

USER workbench
EXPOSE 8031
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8031/api/config', timeout=3).read()"
CMD ["python", "-m", "blackboard_workbench.server", "--host", "0.0.0.0", "--port", "8031", "--data-dir", "/var/lib/blackboard-workbench", "--upstream", "/opt/sast", "--upstream-python", "/usr/local/bin/python"]
