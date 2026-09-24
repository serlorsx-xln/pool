FROM python:3.12.7-alpine
RUN pip install --no-cache-dir psycopg2-binary
COPY main.py /app/main.py
WORKDIR /app
ENTRYPOINT ["python", "main.py"]
