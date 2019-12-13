From python:3
WORKDIR /usr/src/app

COPY requirements.txt ./
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 9545

ENV PYTHONUNBUFFERED=True
ENTRYPOINT [ "./ecs-container-exporter.py" ]
CMD ["--exclude", "ecs-container-exporter,~internal~ecs~pause"]
