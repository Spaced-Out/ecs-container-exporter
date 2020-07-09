From python:3-alpine
ARG WORK_DIR=/usr/src/app

WORKDIR ${WORK_DIR}

RUN pip install --upgrade pip

# TODO: find a way to do --no-cache install with setup.py
# instead of using requirements.txt
COPY . .
RUN pip install --no-cache-dir -r requirements.txt

ENV EXPORTER_PORT=9545
EXPOSE ${EXPORTER_PORT}

ENV LOG_LEVEL=info
ENV PYTHONUNBUFFERED=True
ENV EXCLUDE="ecs-container-exporter,~internal~ecs~pause"
CMD ["ecs-container-exporter"]
