import logging
from collections import defaultdict
from .utils import create_metric, create_task_metrics, TASK_CONTAINER_NAME_TAG

log = logging.getLogger()


def calculate_network_metrics(stats, task_container_tags):
    """
    "networks": {
        "eth1": {
            "rx_bytes": 564655295,
            "rx_packets": 384960,
            "rx_errors": 0,
            "rx_dropped": 0,
            "tx_bytes": 3043269,
            "tx_packets": 54355,
            "tx_errors": 0,
            "tx_dropped": 0
        }
    }

    """
    metrics_by_container = {}
    # task level metrics
    task_metrics = defaultdict(int)
    # assume these will always be gauge
    metric_type = 'gauge'
    for container_id, container_stats in stats.items():
        metrics = []
        tags = task_container_tags[container_id]
        network_stats = container_stats.get('networks')
        if not network_stats:
            continue

        for iface, iface_stats in network_stats.items():
            iface_tag = tags.copy()
            iface_tag['iface'] = iface

            for stat, value in iface_stats.items():
                metrics.append(
                    create_metric('network_' + stat + '_total', value, tags,
                                  metric_type, 'Network '+stat)
                )
                # assume single iface
                task_metrics['network_' + stat + '_total'] += value

        metrics_by_container[container_id] = metrics

    # Task metrics
    metrics_by_container[TASK_CONTAINER_NAME_TAG] = create_task_metrics(task_metrics, metric_type)

    return metrics_by_container
