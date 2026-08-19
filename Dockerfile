FROM maximhq/bifrost:latest
COPY data/config.json /app/data/config.json
RUN mkdir -p /app/data/db
