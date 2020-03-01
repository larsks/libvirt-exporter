import click
import logging
import time
import yaml

from pathlib import Path

from prometheus_client.core import REGISTRY
from prometheus_client import start_http_server

from libvirt_exporter.collector import LibvirtCollector

LOG = logging.getLogger(__name__)


@click.command()
@click.option('-u', '--uri')
@click.option('-l', '--listen', default='0.0.0.0')
@click.option('-p', '--port', default=5111)
@click.option('-x', '--labels-from-xml', type=Path)
@click.option('-v', '--verbose', count=True, default=0,
              type=click.IntRange(0, 2))
def main(verbose, uri, listen, port, labels_from_xml):
    loglevel = ['WARNING', 'INFO', 'DEBUG'][verbose]
    logging.basicConfig(level=loglevel)

    if labels_from_xml:
        with labels_from_xml.open('r') as fd:
            dom_label_map = yaml.safe_load(fd)
    else:
        dom_label_map = None

    REGISTRY.register(LibvirtCollector(
        uri=uri,
        dom_label_map=dom_label_map,
    ))

    LOG.info('starting server on %s port %d', listen, port)
    start_http_server(port, addr=listen)
    while True:
        time.sleep(3600)
