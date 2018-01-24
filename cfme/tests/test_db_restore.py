import fauxfactory
import pytest

from cfme.cloud import provider as cloud_provider
from cfme.cloud.provider.ec2 import EC2Provider
from cfme.common.vm import VM
from cfme.infrastructure.provider import wait_for_a_provider
from cfme.infrastructure.provider.virtualcenter import VMwareProvider
from fixtures.pytest_store import store
from cfme.utils.log import logger
from cfme.utils.providers import list_providers_by_class


def provider_app_crud(provider_class, appliance):
    try:
        prov = list_providers_by_class(provider_class)[0]
        prov.appliance = appliance
        return prov
    except IndexError:
        pytest.skip("No {} providers available (required)".format(provider_class.type))


def provision_vm(request, provider):
    """Function to provision appliance to the provider being tested"""
    vm_name = "test_rest_db_" + fauxfactory.gen_alphanumeric()
    vm = VM.factory(vm_name, provider)

    request.addfinalizer(vm.delete_from_provider)

    if not provider.mgmt.does_vm_exist(vm_name):
        logger.info("deploying %s on provider %s", vm_name, provider.key)
        vm.create_on_provider(allow_skip="default")
    else:
        logger.info("recycling deployed vm %s on provider %s", vm_name, provider.key)
    vm.provider.refresh_provider_relationships()
    vm.wait_to_appear()
    return vm


@pytest.fixture(scope="module")
def get_appliances(temp_appliances_unconfig_modscope):
    """Returns two database-owning appliances

    """
    appl1 = temp_appliances_unconfig_modscope[0]
    appl2 = temp_appliances_unconfig_modscope[1]
    appl1.configure(region=0)
    appl1.wait_for_web_ui()
    appl2.configure(region=0)
    appl2.wait_for_web_ui()
    return temp_appliances_unconfig_modscope


#TODO Refactore test in to fixtures
@pytest.mark.tier(2)
@pytest.mark.uncollectif(
    lambda: not store.current_appliance.is_downstream)
def test_db_restore(request, soft_assert, get_appliances):

    appl1, appl2 = get_appliances

    def finalize():
        appl1.destroy()
        appl2.destroy()
    request.addfinalizer(finalize)

    # Manage infra,cloud providers and set some roles before taking a DB backup
    server_info = appl1.server.settings
    server_info.enable_server_roles('automate')
    roles = server_info.server_roles_db
    virtual_crud = provider_app_crud(VMwareProvider, appl1).setup()
    provider_app_crud(EC2Provider, appl1).setup()

    providers_appl1 = appl1.managed_known_providers
    appl1.db.backup()

    # Fetch v2_key and DB backup from the first appliance
    rand_filename = "/tmp/v2_key_{}".format(fauxfactory.gen_alphanumeric())
    appl1.ssh_client.get_file("/var/www/miq/vmdb/certs/v2_key", rand_filename)
    dump_filename = "/tmp/db_dump_{}".format(fauxfactory.gen_alphanumeric())
    appl1.ssh_client.get_file("/tmp/evm_db.backup", dump_filename)
    # Push v2_key and DB backup to second appliance
    appl2.ssh_client.put_file(rand_filename, "/var/www/miq/vmdb/certs/v2_key")
    appl2.ssh_client.put_file(dump_filename, "/tmp/evm_db.backup")


    # Restore DB on the second appliance
    appl2.evmserverd.stop()
    appl2.db.drop()
    appl2.db.restore()
    appl2.start_evm_service()
    appl2.wait_for_web_ui()
    with appl2:
        wait_for_a_provider()
        cloud_provider.wait_for_a_provider()

    # Assert providers on the second appliance
    providers_appl2 = appl2.managed_known_providers
    assert set(providers_appl2).issubset(providers_appl1), (
        'Restored DB is missing some providers'
    )

    # Verify that existing provider can detect new VMs on the second appliance
    vm = provision_vm(request, virtual_crud)
    soft_assert(vm.find_quadicon().data['state'] == 'currentstate-on')
    soft_assert(vm.provider.mgmt.is_vm_running(vm.name), "vm running")

    # Assert server roles on the second appliance
    for role, is_enabled in server_info.server_roles_ui.iteritems():
        if is_enabled:
            assert roles[role], "Role '{}' is selected but should not be".format(role)
        else:
            assert not roles[role], "Role '{}' is not selected but should be".format(role)
