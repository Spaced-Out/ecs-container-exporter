.PHONY: build test

TAG ?= latest
LOG_LEVEL ?= DEBUG

build:
	docker build . -t raags/ecs-container-exporter:${TAG}

package:
	pip install --upgrade build
	python3 -m build

pypi:
	python3 -m twine upload

run:
	docker run --rm --name ecs-container-exporter -p 9545:9545 -e ECS_CONTAINER_METADATA_URI=http://10.200.10.1:8080 raags/ecs-container-exporter:${TAG}
	# --log-level debug
