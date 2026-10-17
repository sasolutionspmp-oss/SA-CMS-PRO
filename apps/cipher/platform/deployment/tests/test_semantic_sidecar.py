"""Reject wrong-image, cross-profile and publicly exposed sidecar admission."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('cipher_semantic_local', Path(__file__).resolve().parents[1] / 'cipher-semantic.py')
semantic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(semantic)


class SemanticAdmission(unittest.TestCase):
    def container(self):
        return {'State': {'Running': True}, 'Config': {'Image': semantic.IMAGE, 'Labels': {'com.docker.compose.project': semantic.PROJECT,
                'com.docker.compose.service': 'qdrant'}}, 'Image': semantic.IMAGE_ID,
                'HostConfig': {'Memory': 512 * 1024 ** 2, 'MemorySwap': 512 * 1024 ** 2,
                               'NanoCpus': 1000000000, 'PidsLimit': 128},
                'NetworkSettings': {'Networks': {semantic.NETWORK: {'Aliases': [semantic.ALIAS]}}},
                'Mounts': [{'Type': 'volume', 'Name': semantic.VOLUME, 'Destination': '/qdrant/storage'}]}

    def test_exact_registry_image_identity_is_required(self):
        image = {'Id': semantic.IMAGE_ID, 'Os': 'linux', 'Architecture': 'amd64', 'RepoDigests': [semantic.IMAGE]}
        semantic.admit_image(image)
        for key, value in (('Id', 'sha256:' + '0' * 64), ('Architecture', 'arm64'), ('RepoDigests', ['qdrant/qdrant:latest'])):
            with self.subTest(field=key), self.assertRaises(semantic.AdmissionError):
                semantic.admit_image({**image, key: value})

    def test_trial_network_or_wrong_external_network_owner_is_refused(self):
        network = {'Name': semantic.NETWORK, 'Driver': 'bridge', 'Labels': {
            'com.docker.compose.project': 'cipher-integration', 'com.docker.compose.network': 'default'}}
        semantic.admit_network(network)
        for key, value in (('Name', 'cipher-trial_default'), ('Driver', 'host'), ('Labels', {})):
            with self.subTest(field=key), self.assertRaises(semantic.AdmissionError):
                semantic.admit_network({**network, key: value})

    def test_exposure_wrong_storage_or_missing_bounds_are_refused(self):
        semantic.admit_container(self.container())
        for key, value in (('PortBindings', {'6333/tcp': [{'HostPort': '6333'}]}),
                           ('Privileged', True), ('Memory', 0), ('NanoCpus', 0), ('PidsLimit', 0)):
            container = self.container()
            container['HostConfig'][key] = value
            with self.subTest(field=key), self.assertRaises(semantic.AdmissionError):
                semantic.admit_container(container)
        for changed in ('network', 'volume', 'image'):
            container = deepcopy(self.container())
            if changed == 'network':
                container['NetworkSettings']['Networks']['cipher-trial_default'] = {}
            elif changed == 'volume':
                container['Mounts'][0]['Name'] = 'cipher-trial_sites'
            else:
                container['Image'] = 'sha256:' + '0' * 64
            with self.subTest(field=changed), self.assertRaises(semantic.AdmissionError):
                semantic.admit_container(container)

    def test_shared_alias_cannot_redirect_the_version_probe(self):
        owned = {**self.container(), 'Id': 'owned-sidecar', 'State': {'Running': True}}
        other = {**self.container(), 'Id': 'different-sidecar', 'State': {'Running': True}}
        semantic.admit_alias_owners([owned], owned)
        semantic.admit_alias_owners([], None)
        with self.assertRaises(semantic.AdmissionError):
            semantic.admit_alias_owners([owned, other], owned)
        with self.assertRaises(semantic.AdmissionError):
            semantic.admit_alias_owners([other], None)

    def test_stopped_container_can_restart_before_live_alias_readback(self):
        stopped = self.container()
        stopped['State']['Running'] = False
        stopped['NetworkSettings']['Networks'][semantic.NETWORK]['Aliases'] = None
        semantic.admit_container(stopped)
        stopped['State']['Running'] = True
        with self.assertRaises(semantic.AdmissionError):
            semantic.admit_container(stopped)


if __name__ == '__main__':
    unittest.main()
