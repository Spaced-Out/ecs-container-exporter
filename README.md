# ecs-container-exporter
[AWS ECS](https://aws.amazon.com/ecs/) side car that exports ECS container level docker stats metrics to [Prometheus](https://prometheus.io) as well as publish it via Statsd.

# Motivation
The default metrics available in AWS ECS are limited, mostly at the task level, across all containers in a task; the container level metrics are not available. In addition, more detailed cgroup metrics are also not available, such as per cpu, and memory usage breakdown into cache, rss, etc.

Luckily AWS exposes the [docker stats](https://docs.docker.com/engine/api/v1.40/#operation/ContainerInspect) data via a [Task metadata endpoint](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task-metadata-endpoint.html).

The ecs-container-exporter parses this data, and can expose it to Prometheus or push them via StatsD.

# Usage
Install via Pip:

```
$ pip3 install ecs-container-exporter
```

or via docker:

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
and `~internal~ecs~pause` (a Fargate internal sidecar) is excluded.

## Statsd

Version `2.0.0` add Statsd support with `--use-statsd` flag or env `USE_STATSD`. Metrics are emitted with DogStatsd Tag format.


# Metrics

The metrics are sampled twice as per the configured `interval` (default 60s), and than aggregated in this interval. This should be set to the Prometheus scrape interval.


## CPU

CPU usage ratio is calculated and scaled as per the applicable container or task cpu limit:

| Task Limit | Container Limit | Task Metric | Container Metric |
| --- | --- | ---  | --- |
| 0   | 0   | no scaling   | no scaling |
| 0   | x   | no scaling   | scale cpu (can burst above 100%) |
| x   | 0   | scale as per limit | scale as per task limit  |
| x   | x   | scale as per limit | scale as per container limit (can burst above 100%) |

Note that unlike `docker stats` command and others, CPU usage is not scaled to
the number of CPUs. This means a task with 4 CPUs with all 4 having full
utilization will show up as 400% in `docker stats`, but 100% here.

## Memory

Memory usage and cache is emitted separately, but the memory usage also includes cache, so
subtract cache from it to plot application memory usage specifically.

## IO

## Network

Network metrics were recently added in Fargate 1.4.0 and ECS agent 1.41.0 onwards.

# TODO
[] - Support Non ECS docker host containers
