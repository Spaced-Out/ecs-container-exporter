# ecs-container-exporter
[AWS ECS](https://aws.amazon.com/ecs/) side car that exports container level metrics to [Prometheus](https://prometheus.io)

# Motivation
The default metrics available in ECS are at the task level, which include all the side cars associated with a task. But the container metrics are what we are interested in which is not available in ECS. In addition, more detailed cgroup metrics are also not available, such as per cpu, and memory usage breakdown into cache, rss, etc.

Luckily AWS exposes the [docker stats](https://docs.docker.com/engine/api/v1.40/#operation/ContainerInspect) data via a [Task metadata endpoint](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-metadata-endpoint.html).

The ecs-container-exporter just parses this data, and exposes it to Prometheus.

# Usage
The Docker image is available on docker hub at:

```
$ docker pull raags/ecs-container-exporter
```

On ECS, add the following json to the task definition:

```json
{
	"name": "ecs-container-exporter",
	"image": "raags/ecs-container-exporter:latest",
	"portMappings": [
	{
		"hostPort": 0,
		"protocol": "tcp",
		"containerPort": 9545
	}
	],
	"command": [],
	"cpu": 256,
	"dockerLabels": {
		"PROMETHEUS_EXPORTER_PORT": "9545"
	}
}
```
The `PROMETHEUS_EXPORTER_PORT` label is for ECS discovery via https://github.com/teralytics/prometheus-ecs-discovery

To include or exclude application containers use the `INCLUDE` or `EXCLUDE` environment variable. By default `ecs-container-exporter`
and `~internal~ecs~pause`, which is a Fargate internal sidecar, is excluded.

# Metrics

## CPU

CPU usage ratio is calculated and scaled as per the applicable container or task cpu limit:

| Task Limit | Container Limit | Task Metric | Container Metric |
| --- | --- | ---  | --- |
| 0   | 0   | no scaling   | no scaling |
| 0   | x   | no scaling   | scale cpu (can burst above 100%) |
| x   | 0   | scale as per limit | scale as per task limit  |
| x   | x   | scale as per limit | scale as per container limit (can burst above 100%) |

## Memory

Memory usage and cache is emitted separately. Memory usage include cache, so
subtract cache from it to plot application memory usage specifically.

## IO

## Network

Network metrics were recently added in Fargate 1.4.0 and ECS agent 1.41.0 onwards.
