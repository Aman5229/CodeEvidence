FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# The embedding model's libraries in their own layer, before the code: they are large and
# rarely change, so a code change does not download them again. The CPU build of PyTorch:
# the GPU build is gigabytes larger. Keep the version range in sync with pyproject.toml.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch \
 && pip install --no-cache-dir "sentence-transformers>=3,<6"
# Static analysis that reviews run on the changed files. ruff and semgrep get their own
# virtualenv, so their dependencies never clash with the app's. gitleaks is a release binary,
# checked against the SHA-256 its release publishes (update both when changing the version).
RUN python -m venv /opt/tools \
 && /opt/tools/bin/pip install --no-cache-dir "ruff>=0.8,<1" "semgrep>=1.80,<2" \
 && ln -s /opt/tools/bin/ruff /opt/tools/bin/semgrep /usr/local/bin/ \
 && case "$(uname -m)" in \
      x86_64) arch=x64; sha=ba6dbb656933921c775ee5a2d1c13a91046e7952e9d919f9bac4cec61d628e7d ;; \
      aarch64) arch=arm64; sha=bf5f7f466ebfade1296c8bd32cf7d3f592c2aa78836aa9980ffbe2cadca7a861 ;; \
      *) echo "No gitleaks build for $(uname -m)"; exit 1 ;; \
    esac \
 && python -c "import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], '/tmp/gitleaks.tgz')" \
      "https://github.com/gitleaks/gitleaks/releases/download/v8.18.4/gitleaks_8.18.4_linux_${arch}.tar.gz" \
 && echo "$sha  /tmp/gitleaks.tgz" | sha256sum -c - \
 && tar -xzf /tmp/gitleaks.tgz -C /usr/local/bin gitleaks \
 && rm /tmp/gitleaks.tgz
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir ".[embeddings]"
COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts
COPY models ./models
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
