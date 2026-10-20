FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# The embedding model's libraries in their own layer, before the code: they are large and
# rarely change, so a code change does not download them again. The CPU build of PyTorch:
# the GPU build is gigabytes larger. Keep the version range in sync with pyproject.toml.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch \
 && pip install --no-cache-dir "sentence-transformers>=3,<6"
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir ".[embeddings]"
COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts
COPY models ./models
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
