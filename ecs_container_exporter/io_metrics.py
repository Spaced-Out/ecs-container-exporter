import logging
from collections import defaultdict
from ecs_container_exporter.utils import create_metric, create_task_metrics, TASK_CONTAINER_NAME_TAG

log = logging.getLogger()


def calculate_io_metrics(stats, task_container_tags):
    """
    Calculate IO metrics from the below data:

    "blkio_stats": {
        "io_merged_recursive": [],
        "io_queue_recursive": [],
        "io_service_bytes_recursive": [
            {
                "major": 259,
                "minor": 0,
                "op": "Read",
                "value": 10653696
            },
            {
                "major": 259,
                "minor": 0,
                "op": "Write",
                "value": 0
            },
            {
                "major": 259,
                "minor": 0,
                "op": "Sync",
                "value": 10653696
            },
            {
                "major": 259,
                "minor": 0,
                "op": "Async",
                "value": 0
            },
            {
                "major": 259,
                "minor": 0,
                "op": "Total",
                "value": 10653696
            }
        ],
        "io_service_time_recursive": [],
        "io_serviced_recursive": [
            {
                "major": 259,
                "minor": 0,
                "op": "Read",
                "value": 164
            },
            {
                "major": 259,
                "minor": 0,
                "op": "Write",
                "value": 0
            },
            {
                "major": 259,
                "minor": 0,
                "op": "Sync",
                "value": 164
            },
            {
                "major": 259,
                "minor": 0,
                "op": "Async",
                "value": 0
            },
            {
                "major": 259,
                "minor": 0,
                "op": "Total",
                "value": 164
            }
        ],
        "io_time_recursive": [],
        "io_wait_time_recursive": [],
        "sectors_recursive": []
    },
    """
    metrics_by_container = {}
    # task level metrics
    task_metrics = defaultdict(int)
    # assume these will always be gauge
    metric_type = 'gauge'
    for container_id, container_stats in stats.items():
        metrics = []
        blkio_stats = container_stats.get('blkio_stats')

        iostats = {'io_service_bytes_recursive': 'bytes', 'io_serviced_recursive': 'iops'}
        for blk_key, blk_type in iostats.items():
            tags = task_container_tags[container_id]
            read_counter = write_counter = 0
            for blk_stat in blkio_stats.get(blk_key):
                if blk_stat['op'] == 'Read' and 'value' in blk_stat:
                    read_counter += blk_stat['value']
                elif blk_stat['op'] == 'Write' and 'value' in blk_stat:
                    write_counter += blk_stat['value']

            metrics.append(
                create_metric('disk_read_' + blk_type + '_total', read_counter, tags,
                              metric_type, 'Total disk read ' + blk_type)
            )
            metrics.append(
                create_metric('disk_written_' + blk_type + '_total', write_counter, tags,
                              metric_type, 'Total disk written ' + blk_type)
            )
            task_metrics['disk_read_' + blk_type + '_total'] += read_counter
            task_metrics['disk_written_' + blk_type + '_total'] += write_counter

        metrics_by_container[container_id] = metrics

    # task level metrics
    metrics_by_container[TASK_CONTAINER_NAME_TAG] = create_task_metrics(task_metrics, metric_type)

    return metrics_by_container
