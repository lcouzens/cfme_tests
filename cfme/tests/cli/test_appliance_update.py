import fauxfactory
import tempfile
import pytest

from cfme.ansible.repositories import RepositoryCollection
from cfme.configure.configuration.region_settings import RedHatUpdates
from cfme.test_framework.sprout.client import SproutClient, SproutException
from cfme.utils.appliance.implementations.ui import navigate_to
from cfme.utils.version import current_version
from cfme.utils.conf import cfme_data
from cfme.utils.log import logger
from cfme.utils.update import update
from cfme.utils.version import Version
from cfme.utils.wait import wait_for
from cfme.utils import os, conf
from fixtures.pytest_store import store
from scripts.repo_gen import process_url, build_file

versions = []

REPOSITORIES = [
    "https://github.com/quarckster/ansible_playbooks",
    "https://github.com/patchkez/ansible_playbooks"
]


def pytest_generate_tests(metafunc):
    """The following lines generate appliance versions based from the current build.
    Appliance version is split and minor_build is picked out for generating each version
    and appending it to the empty versions list"""

    version = store.current_appliance.version
    split_ver = str(version).split(".")
    try:
        minor_build = split_ver[2]
    except IndexError:
        logger.exception('Caught IndexError generating for test_appliance_update, skipping')
        pytest.skip('Could not parse minor_build version from: {}'.format(version))

    for i in range(int(minor_build) - 1, -1, -1):
        versions.append("{}.{}.{}".format(split_ver[0], split_ver[1], i))


@pytest.yield_fixture(scope='module')
def ansible_repository(appliance):
    repositories = RepositoryCollection(appliance=appliance)
    repository = repositories.create(
        fauxfactory.gen_alpha(),
        REPOSITORIES[0],
        description=fauxfactory.gen_alpha())

    yield repository

    if repository.exists:
        repository.delete()


@pytest.yield_fixture(scope="function")
def appliance_preupdate(old_version, appliance):

    series = appliance.version.series()
    update_url = "update_url_{}".format(series.replace('.', ''))

    """Requests appliance from sprout based on old_versions, edits partitions and adds
    repo file for update"""

    usable = []
    sp = SproutClient.from_config()
    available_versions = set(sp.call_method('available_cfme_versions'))
    for a in available_versions:
        if a.startswith(old_version):
            usable.append(Version(a))
    usable.sort(reverse=True)
    try:
        apps, pool_id = sp.provision_appliances(count=1, preconfigured=True,
            lease_time=180, version=str(usable[0]))
    except Exception as e:
        logger.exception("Couldn't provision appliance with following error:{}".format(e))
        raise SproutException('No provision available')

    urls = process_url(conf.cfme_data['basic_info'][update_url])
    urls = process_url(cfme_data['basic_info'][update_url])
    output = build_file(urls)
    with tempfile.NamedTemporaryFile('w') as f:
        f.write(output)
        f.flush()
        os.fsync(f.fileno())
        apps[0].ssh_client.put_file(
            f.name, '/etc/yum.repos.d/update.repo')
    yield apps[0]
    apps[0].ssh_client.close()
    sp.destroy_pool(pool_id)


@pytest.mark.parametrize('old_version', versions)
@pytest.mark.uncollectif(lambda: not store.current_appliance.is_downstream)
def test_update_yum(appliance_preupdate, appliance):

    """Tests appliance update between versions"""

    appliance_preupdate.evmserverd.stop()
    with appliance_preupdate.ssh_client as ssh:
        rc, out = ssh.run_command('yum update -y', timeout=3600)


@pytest.fixture(scope='module')
def enabled_embedded_appliance(appliance_preupdate):
    """Takes a preconfigured appliance and enables the embedded ansible role"""
    appliance_preupdate.enable_embedded_ansible_role()
    assert appliance_preupdate.is_embedded_ansible_running
    return appliance_preupdate


@pytest.mark.parametrize('old_version', versions)
@pytest.mark.uncollectif(lambda: not store.current_appliance.is_downstream)
@pytest.mark.uncollectif(lambda: current_version() < "5.8")
def test_embedded_ansible_update(enabled_embedded_appliance, appliance):
    """ Tests updating an appliance which has embedded ansible role enabled, also confirms that the
        role continues to function correctly after the update has completed"""
    set_default_repo = True
    with enabled_embedded_appliance:
        red_hat_updates = RedHatUpdates(
            service='rhsm',
            url=conf.cfme_data['redhat_updates']['registration']['rhsm']['url'],
            username=conf.credentials['rhsm']['username'],
            password=conf.credentials['rhsm']['password'],
            set_default_repository=set_default_repo
        )
        red_hat_updates.update_registration(validate=False)
        red_hat_updates.check_updates()
        wait_for(
            func=red_hat_updates.checked_updates,
            func_args=[appliance.server.name],
            delay=10,
            num_sec=100,
            fail_func=red_hat_updates.refresh
        )
        if red_hat_updates.platform_updates_available():
            red_hat_updates.update_appliances()

    def is_appliance_updated(appliance):
        """Checks if cfme-appliance has updated"""
        assert appliance.version == enabled_embedded_appliance.version

    wait_for(is_appliance_updated, func_args=[enabled_embedded_appliance], num_sec=900)
    assert wait_for(func=lambda: enabled_embedded_appliance.is_embedded_ansible_running, num_sec=30)
    assert wait_for(func=lambda: enabled_embedded_appliance.is_rabbitmq_running, num_sec=30)
    assert wait_for(func=lambda: enabled_embedded_appliance.is_nginx_running, num_sec=30)
    assert enabled_embedded_appliance.ssh_client.run_command(
        'curl -kL https://localhost/ansibleapi | grep "Ansible Tower REST API"')
    updated_description = "edited_{}".format(fauxfactory.gen_alpha())
    with update(ansible_repository):
        ansible_repository.description = updated_description
    view = navigate_to(ansible_repository, "Edit")
    wait_for(lambda: view.description.value != "", delay=1, timeout=5)
    assert view.description.value == updated_description
