#!/usr/bin/env python3
"""Opt-in Qdrant sidecar lifecycle; never configures a site or creates a collection."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
PROJECT = 'cipher-semantic-integration'
NETWORK = 'cipher-integration_default'
ALIAS = 'cipher-semantic-qdrant'
VOLUME = 'cipher-semantic-integration-qdrant-v1155'
IMAGE = 'qdrant/qdrant@sha256:53d8c371bc3ae99e4353897ee594bfcfab7f72c4925f74471ebb34d9f6103a3e'
IMAGE_ID = 'sha256:0ad2e23181e5646b286253c04cea23f07040ca313cc377d9fa7b21db184b6406'


class AdmissionError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise AdmissionError(message)


def docker(*arguments):
    return subprocess.run(['docker', *arguments], cwd=HERE, check=True, text=True,
                          stdout=subprocess.PIPE).stdout.strip()


def compose(*arguments):
    return docker('compose', '--project-name', PROJECT, '-f', str(HERE / 'compose.semantic.yml'),
                  '--profile', 'semantic', *arguments)


def admit_image(image):
    require(image.get('Id') == IMAGE_ID and image.get('Os') == 'linux' and image.get('Architecture') == 'amd64',
            'The locally cached image does not match the pinned Linux AMD64 Qdrant identity.')
    require(IMAGE in image.get('RepoDigests', []), 'The expected immutable Qdrant manifest is not present locally.')


def admit_network(network):
    labels = network.get('Labels') or {}
    require(network.get('Name') == NETWORK and network.get('Driver') == 'bridge' and
            labels.get('com.docker.compose.project') == 'cipher-integration' and
            labels.get('com.docker.compose.network') == 'default',
            'Start the existing integration profile first; its expected Compose bridge is required.')


def admit_container(container):
    config, host = container.get('Config', {}), container.get('HostConfig', {})
    labels = config.get('Labels') or {}
    require(labels.get('com.docker.compose.project') == PROJECT and labels.get('com.docker.compose.service') == 'qdrant',
            'Unexpected sidecar ownership labels.')
    require(config.get('Image') == IMAGE and container.get('Image') == IMAGE_ID,
            'The sidecar is running a different image identity.')
    require(not host.get('PortBindings') and not host.get('PublishAllPorts') and not host.get('Privileged'),
            'The sidecar must have no published ports or privileged mode.')
    require(host.get('Memory') == 512 * 1024 ** 2 and host.get('MemorySwap') == 512 * 1024 ** 2 and
            host.get('NanoCpus') == 1000000000 and host.get('PidsLimit') == 128,
            'The sidecar does not have the declared CPU, memory and process bounds.')
    networks = container.get('NetworkSettings', {}).get('Networks', {})
    running = container.get('State', {}).get('Running') is True
    require(set(networks) == {NETWORK} and
            (not running or ALIAS in (networks[NETWORK].get('Aliases') or [])),
            'The sidecar must use only the integration bridge and its unique alias.')
    stores = [mount for mount in container.get('Mounts', []) if mount.get('Destination') == '/qdrant/storage']
    require(len(stores) == 1 and stores[0].get('Type') == 'volume' and stores[0].get('Name') == VOLUME,
            'The sidecar is not using its distinct persistent storage volume.')


def selected_container():
    identifiers = compose('ps', '--all', '--quiet', 'qdrant').splitlines()
    require(len(identifiers) <= 1, 'More than one sidecar container exists; reconcile ownership first.')
    if not identifiers:
        return None
    container = json.loads(docker('inspect', identifiers[0]))[0]
    admit_container(container)
    return container


def admit_alias_owners(peers, selected):
    owners = {peer.get('Id') for peer in peers
              if ALIAS in (peer.get('NetworkSettings', {}).get('Networks', {}).get(NETWORK, {}).get('Aliases') or [])}
    expected = {selected['Id']} if selected else set()
    running = selected is not None and selected.get('State', {}).get('Running') is True
    require(not (owners - expected) and (not running or owners == expected),
            'The semantic DNS alias must belong only to the selected sidecar on the integration bridge.')


def probe_version():
    identifiers = docker('ps', '--quiet', '--filter', 'label=com.docker.compose.project=cipher-integration',
                         '--filter', 'label=com.docker.compose.service=runtime').splitlines()
    require(len(identifiers) == 1, 'Exactly one running integration runtime is needed for the bridge-only read probe.')
    runtime = json.loads(docker('inspect', identifiers[0]))[0]
    require(NETWORK in runtime.get('NetworkSettings', {}).get('Networks', {}),
            'The integration runtime is not attached to its expected bridge.')
    script = """import json
from urllib.request import ProxyHandler,build_opener
with build_opener(ProxyHandler({})).open('http://cipher-semantic-qdrant:6333/',timeout=5) as response:
 data=response.read(8193)
 if len(data)>8192: raise SystemExit('Oversized identity response')
 result=json.loads(data)
 if result.get('version')!='1.15.5': raise SystemExit('Unexpected Qdrant server version')
 print(json.dumps({'version':result['version'],'protocol':'qdrant-rest-v1'}))
"""
    return json.loads(docker('exec', identifiers[0], 'python', '-c', script))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check', 'start', 'stop', 'status'))
    args = parser.parse_args(argv)
    network = json.loads(docker('network', 'inspect', NETWORK))[0]
    admit_network(network)
    admit_image(json.loads(docker('image', 'inspect', IMAGE))[0])
    container = selected_container()
    connected = list(network.get('Containers') or {})
    peers = json.loads(docker('inspect', *connected)) if connected else []
    admit_alias_owners(peers, container)
    if args.action == 'start':
        print(compose('up', '--detach', '--no-build', '--pull', 'never', 'qdrant'))
        print('Sidecar start requested. Run status after startup to verify its actual server version.')
    elif args.action == 'stop':
        print(compose('stop', '--timeout', '30', 'qdrant'))
        print('Sidecar stopped; its storage volume is retained. Base profile lifecycle is separate.')
    elif args.action == 'status':
        require(container is not None and container.get('State', {}).get('Running') is True,
                'The optional sidecar is not running.')
        print(json.dumps({'image': IMAGE, 'image_id': IMAGE_ID, 'network': NETWORK, 'volume': VOLUME,
                          **probe_version(), 'collection_qualified': False, 'site_configuration_changed': False}, indent=2))
    else:
        print('Pinned image and existing integration bridge admitted; no service was started or site configured.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (AdmissionError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print('Semantic sidecar command refused: ' + str(error), file=sys.stderr)
        raise SystemExit(1)
