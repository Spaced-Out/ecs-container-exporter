import logging
from ecs_container_exporter.utils import create_metric, task_metric_tags, TASK_CONTAINER_NAME_TAG

log = logging.getLogger(__name__)


def calculate_cpu_metrics(docker_stats, task_cpu_limit, task_container_limits,
                          task_container_tags):
    """
    Calculate cpu metrics based on the docker container stats json.

    The precpu_stats is calculated by docker stats api at 1s interval,
    which is too small, instead we scample twice over a longer interval.
    https://github.com/moby/moby/blob/b50ba3da1239a56456634f74660f43a27df6b3f2/daemon/daemon.go#L1055

    `docker_stats` is a list with two samples over an interval. CPU usage
    is caculated by comparing the `cpu_stats` of the first and second sample.

    Task and Container Cpu usage is `scaled` against the applicable CPU
    limits. This is more accurate than using the actual values which give
    utilization against the Host CPU.

    Specifically calculate based on the following data.

    "cpu_stats": {
        "cpu_usage": {
            "percpu_usage": [
                826860687,
                830807540,
                823365887,
                844077056
            ],
            "total_usage": 3325111170,
            "usage_in_kernelmode": 1620000000,
            "usage_in_usermode": 1600000000
        },
        "online_cpus": 4,
        "system_cpu_usage": 35595977360000000,
        "throttling_data": {
            "periods": 0,
            "throttled_periods": 0,
            "throttled_time": 0
        }
    },

    """
    # Container_id to metrics mapping
    metrics_by_container = {}
    # Total task cpu usage
    task_cpu_usage_ratio = 0.0

    prev_stats = docker_stats[0]
    stats = docker_stats[1]
    online_cpus = get_online_cpus(stats)
    for container_id, container_stats in stats.items():
        metrics = []
        tags = task_container_tags[container_id]

        cpu_stats = container_stats.get('cpu_stats', {})
        prev_cpu_stats = prev_stats[container_id].get('cpu_stats', {})
        log.debug(f'CPU Stats: {container_id} - curr {cpu_stats} - prev {prev_cpu_stats}')

        # `cpu_stats` sometimes maybe empty when container is just started
        if not prev_cpu_stats:
            continue

        usage_delta = cpu_usage_diff(cpu_stats, prev_cpu_stats)
        # system_cpu_usage is sum of `all` cpu usage on the `host`:
        # https://github.com/moby/moby/blob/54d88a7cd366fd8169b8a96bec5d9f303d57c425/daemon/stats/collector_unix.go#L31
        #
        system_delta = system_cpu_usage_diff(cpu_stats, prev_cpu_stats)
        log.debug(f'usage_delta {usage_delta} system_delta {system_delta}')

        cpu_usage_ratio = calculate_cpu_usage(usage_delta, system_delta)
        log.debug(f'Usage Ratio {cpu_usage_ratio} {online_cpus}')
        # add to total task cpu usage
        task_cpu_usage_ratio += cpu_usage_ratio

        # Scale cpu usage against the Task or Container Limit
        container_cpu_limit = task_container_limits[container_id]['cpu']
        value = normalize_cpu_usage(cpu_usage_ratio, online_cpus,
                                    task_cpu_limit,
                                    container_cpu_limit)

        metric = create_metric('cpu_usage_ratio', round(value, 4), tags, 'gauge',
                               'CPU usage ratio')
        metrics.append(metric)

        # Per cpu metrics
        metrics.extend(
            percpu_metrics(cpu_stats, prev_cpu_stats, system_delta, online_cpus,
                           task_cpu_limit, container_cpu_limit, tags)
        )

        metrics.extend(
            cpu_user_kernelmode_metrics(cpu_stats, prev_cpu_stats, tags)
        )

        # CPU throttling
        # TODO: figure out how this will look at the Task level
        metrics.extend(
            cpu_throttle_metrics(cpu_stats, tags)
        )

        metrics_by_container[container_id] = metrics

    # total task cpu ratio
    if task_cpu_limit != 0:
        task_cpu_usage_ratio = scale_cpu_usage(task_cpu_usage_ratio, online_cpus, task_cpu_limit)

    tags = task_metric_tags()
    metric = create_metric('cpu_usage_ratio', round(task_cpu_usage_ratio, 4), tags, 'gauge',
                           'CPU usage ratio')

    metrics_by_container[TASK_CONTAINER_NAME_TAG] = [metric]

    return metrics_by_container


def cpu_throttle_metrics(cpu_stats, tags):
    metrics = []
    throttling_data = cpu_stats.get('throttling_data')
    for mkey, mvalue in throttling_data.items():
        metric = create_metric('cpu_throttle_' + mkey, mvalue, tags, 'gauge')
        metrics.append(metric)

    return metrics


def cpu_user_kernelmode_metrics(cpu_stats, prev_cpu_stats, tags):
    # user and kernel mode split
    curr_stats = cpu_stats['cpu_usage']
    prev_stats = prev_cpu_stats['cpu_usage']
    kernelmode_delta = curr_prev_diff(curr_stats, prev_stats, 'usage_in_kernelmode')
    kernelmode_metric = create_metric('cpu_kernelmode', kernelmode_delta, tags, 'gauge',
                                      'cpu usage in kernel mode')

    usermode_delta = curr_prev_diff(curr_stats, prev_stats, 'usage_in_usermode')
    usermode_metric = create_metric('cpu_usermode', usermode_delta, tags, 'gauge',
                                    'cpu usage in user mode')

    return (kernelmode_metric, usermode_metric)


def percpu_metrics(cpu_stats, prev_cpu_stats, system_delta, online_cpus,
                   task_cpu_limit, container_cpu_limit, tags):
    metrics = []
    percpu_usage = cpu_stats.get('cpu_usage', {}).get('percpu_usage', [])
    prev_percpu_usage = prev_cpu_stats.get('cpu_usage', {}).get('percpu_usage', [])

    if percpu_usage and prev_percpu_usage:
        for i, value in enumerate(percpu_usage):
            # skip inactive Cpus - https://github.com/torvalds/linux/commit/5ca3726
            if value != 0:
                cpu_tags = tags.copy()
                cpu_tags['cpu'] = str(i)
                if prev_percpu_usage[i] and system_delta:
                    usage_delta = float(value) - float(prev_percpu_usage[i])
                    usage_ratio = usage_delta / system_delta
                else:
                    usage_ratio = 0.0

                value = normalize_cpu_usage(usage_ratio, online_cpus,
                                            task_cpu_limit,
                                            container_cpu_limit)

                metric = create_metric('percpu_usage_ratio', round(usage_ratio, 4), cpu_tags, 'gauge',
                                       'Per CPU usage ratio')
                metrics.append(metric)

    return metrics


def calculate_cpu_usage(usage_delta, system_delta):
    if usage_delta and system_delta:
        # Keep it to 100% instead of scaling by number of cpus :
        # https://github.com/moby/moby/issues/29306#issuecomment-405198198
        #
        cpu_usage_ratio = usage_delta / system_delta
    else:
        cpu_usage_ratio = 0.0

    return cpu_usage_ratio


def system_cpu_usage_diff(cpu_stats, prev_cpu_stats):
    return curr_prev_diff(cpu_stats, prev_cpu_stats, 'system_cpu_usage')


def cpu_usage_diff(cpu_stats, prev_cpu_stats):
    return curr_prev_diff(cpu_stats['cpu_usage'], prev_cpu_stats['cpu_usage'],
                          'total_usage')


def curr_prev_diff(curr_stats, prev_stats, metric_key):
    curr = curr_stats[metric_key]
    prev = prev_stats[metric_key]
    if curr and prev:
        return curr - prev
    else:
        return 0.0


def scale_cpu_usage(cpu_usage_ratio, host_cpu_count, cpu_share_limit):
    """
    Scales cpu ratio originally calculated against total host cpu capacity,
    with the corresponding cpu shares limit (at task or container level)

    host_cpu_count is multiplied by 1024 to get the total available cpu shares

    """
    scaled_cpu_usage_ratio = (cpu_usage_ratio * host_cpu_count * 1024) / cpu_share_limit
    return scaled_cpu_usage_ratio


def normalize_cpu_usage(cpu_usage_ratio, host_cpu_count,
                        task_cpu_limit, container_cpu_limit):
    """
    Task Limit - Container Limit - Cpu metric
        0  -  0  -  no scaling
        0  -  x  -  scale against container limit
        x  -  x  -  scale against container limit
        x  -  0  -  scale against task limit

    """
    log.debug(f'Normalize CPU: {cpu_usage_ratio} - {host_cpu_count} - {task_cpu_limit} - {container_cpu_limit}')
    if task_cpu_limit == 0 and container_cpu_limit == 0:
        # no scaling, task can use all of host CPU
        return cpu_usage_ratio

    if container_cpu_limit != 0:
        # case 2 and 3 above
        # this can go above 100% when task_cpu_limit is 0
        #
        return scale_cpu_usage(cpu_usage_ratio, host_cpu_count, container_cpu_limit)

    if task_cpu_limit != 0:
        # case 4, should not go above 100% as cpu usage
        # is limited by task_cpu_limit
        #
        return scale_cpu_usage(cpu_usage_ratio, host_cpu_count, task_cpu_limit)


def get_online_cpus(stats):
    """
    Assume this number is same for all containers

    """
    for container_id, container_stats in stats.items():
        return container_stats['cpu_stats']['online_cpus']
