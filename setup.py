import re
import ast
from setuptools import setup


_version_re = re.compile(r'__version__\s+=\s+(.*)')

with open('ecs_container_exporter/__init__.py', 'rb') as f:
    version = str(ast.literal_eval(_version_re.search(f.read().decode('utf-8')).group(1)))

with open('./README.md') as f:
    long_desc = f.read()


setup(
    name='ecs-container-exporter',
    version=version,
    author='Raghu Udiyar',
    author_email='raghusiddarth@gmail.com',
    url='https://github.com/Spaced-Out/ecs-container-exporter',
    license='MIT License',
    description='Prometheus exporter for AWS ECS Task and Container Metrics',
    long_description=long_desc,
    long_description_content_type="text/markdown",
    install_requires=['setuptools>=36.0.0',
                      'Click==7.0',
                      'prometheus-client==0.7.1',
                      'requests==2.22.0',
                      'datadog==0.39.0'],
    packages=['ecs_container_exporter'],
    entry_points={
        'console_scripts': [
            'ecs-container-exporter = ecs_container_exporter.main:main'
        ]
    },
    classifiers=[
        'Environment :: Console',
        'Intended Audience :: Developers',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
    ]
)
