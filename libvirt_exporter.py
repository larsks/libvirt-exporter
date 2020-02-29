from __future__ import print_function

import click
import libvirt
import os


def bundle_to_metrics(bundle):
    metrics = []
    labels = {'index': bundle[1]}

    if 'name' in bundle[2]:
        labels['name'] = bundle[2]['name']

    for name, value in bundle[2].items():
        if name == 'name':
            continue

        k = '{}_{}'.format(bundle[0], name)
        metrics.append((k, labels, value))
    return metrics


def parse_dom_stats(stats):
    newstats = []
    cur_bundle = (None, None, None)

    for k, v in stats.items():
        comps = k.split('.')
        if comps[1].isdigit():
            ns = comps[0]
            index = comps[1]
            if cur_bundle[:2] != (ns, index):
                if cur_bundle[0] is not None:
                    newstats.extend(bundle_to_metrics(cur_bundle))
                cur_bundle = (ns, index, {})

            k = '_'.join(comps[2:]).replace('-', '_')
            cur_bundle[2][k] = v
        else:
            k = k.replace('.', '_').replace('-', '_')
            newstats.append((k, {}, v))

    if cur_bundle[0] is not None:
        newstats.extend(bundle_to_metrics(cur_bundle))

    return newstats


@click.command()
@click.option('-c', '--connect', 'libvirt_uri')
def main(libvirt_uri):
    node = os.uname()
    host_labels = {
        'host': node[1],
    }

    c = libvirt.open(libvirt_uri)
    all_stats = c.getAllDomainStats()
    active_stats = [x for x in all_stats if x[0].isActive()]

    for dom, stats in active_stats:
        dom_labels = dict(
            domain=dom.name(),
            uuid=dom.UUIDString()
        )

        metrics = parse_dom_stats(stats)
        metrics.append(('active', {}, 1))
        for metric in metrics:
            labels = metric[1]
            labels.update(host_labels)
            labels.update(dom_labels)
            label_string = ','.join('{}="{}"'.format(k, v)
                                    for k, v in labels.items())
            print('libvirt_{} {{{}}} {}'.format(
                metric[0], label_string, metric[2]))


if __name__ == '__main__':
    main()
