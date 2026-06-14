FROM python:3.11-slim

# Create a non-root user for security
RUN useradd -m -u 1000 prism

WORKDIR /app

# Install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the source tree into /app/prism/ so the package import works:
#   from prism import prism as T   (used by dashboard/api/main.py)
#   from prism.prism import get_db  (used by dashboard/api/deps.py)
# /app is on sys.path → /app/prism/ is the 'prism' package.
COPY . /app/prism/

# State directory (overridden by the volume mount in docker-compose)
RUN mkdir -p /app/state && chown -R prism:prism /app

USER prism

# Expose the dashboard API port
EXPOSE 3002

# TRACKER_STATE_DIR and TRACKER_DB control where SQLite lives.
# docker-compose mounts ./state → /app/state and sets TRACKER_STATE_DIR=/app/state.
ENV TRACKER_STATE_DIR=/app/state
ENV TRACKER_DB=/app/state/runloq.db
ENV PYTHONPATH=/app

CMD ["uvicorn", "prism.dashboard.api.main:app", "--host", "0.0.0.0", "--port", "3002"]
