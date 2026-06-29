# Runtime image for the probes and the bind-mounted test miner: a stock python:3.14-slim plus
# msgspec, which they use for Stratum JSON (matching the erikslund-python ecosystem). The scripts
# themselves are bind-mounted at run time, so this image only rebuilds when the msgspec pin changes.
FROM python:3.14-slim
RUN pip install --no-cache-dir msgspec==0.21.1
