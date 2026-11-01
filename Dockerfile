FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=UTC
WORKDIR /app
COPY requirements-ctrader.txt requirements-research.txt ./
RUN pip install --no-cache-dir -r requirements-ctrader.txt
COPY . .
RUN mkdir -p /app/runtime /app/data/ctrader_live
CMD ["python","-m","scripts.run_demo","--poll-seconds","30"]
