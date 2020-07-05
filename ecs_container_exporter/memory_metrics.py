import logging
from collections import defaultdict
from ecs_container_exporter.utils import create_metric, TASK_CONTAINER_NAME_TAG, create_task_metrics

log = logging.getLogger()
# Default value is maxed out for some cgroup metrics
CGROUP_NO_VALUE = 0x7FFFFFFFFFFFF000


def calculate_memory_metrics(stats, task_container_tags):
    metrics_by_container = {}
    # task level metrics
    task_metrics = defaultdict(int)
    metric_type = 'gauge'
    for container_id, container_stats in stats.items():
        metrics = []
        tags = task_container_tags[container_id]
        memory_stats = container_stats.get('memory_stats', {})
        log.debug(f'Memory Stats: {container_id} - {memory_stats}')

        for mkey in ['cache']:
            value = memory_stats.get('stats', {}).get(mkey)
            # some values have default garbage value
            if value < CGROUP_NO_VALUE:
                metric = create_metric('mem_' + mkey, value, tags, metric_type)
                metrics.append(metric)
                if mkey == 'cache':
                    task_metrics['mem_cache'] += value

        for mkey in ['usage']:
            value = memory_stats.get(mkey)
            # some values have default garbage value
            if value < CGROUP_NO_VALUE:
                metric = create_metric('mem_' + mkey, value, tags, metric_type)
                metrics.append(metric)
                if mkey == 'usage':
                    task_metrics['mem_usage'] += value

        metrics_by_container[container_id] = metrics

    # task level metrics
    metrics_by_container[TASK_CONTAINER_NAME_TAG] = create_task_metrics(task_metrics, metric_type)

    return metrics_by_container
