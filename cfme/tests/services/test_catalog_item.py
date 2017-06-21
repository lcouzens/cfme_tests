# -*- coding: utf-8 -*-
import fauxfactory
import pytest

from selenium.common.exceptions import NoSuchElementException, TimeoutException

import cfme.tests.configure.test_access_control as tac
from cfme import test_requirements
from cfme.automate.service_dialogs import ServiceDialog
from cfme.services.catalogs.catalog_item import CatalogItem, CatalogBundle
from cfme.services.catalogs.catalog import Catalog
from cfme.web_ui import flash
from utils import error
from utils.blockers import BZ
from utils.log import logger
from utils.update import update


pytestmark = [test_requirements.service, pytest.mark.tier(3)]


@pytest.yield_fixture(scope="module")
def dialog():
    dialog_name = "dialog_" + fauxfactory.gen_alphanumeric()

    element_data = dict(
        ele_label="ele_" + fauxfactory.gen_alphanumeric(),
        ele_name=fauxfactory.gen_alphanumeric(),
        ele_desc="my ele desc",
        choose_type="Text Box",
        default_text_box="default value"
    )

    service_dialog = ServiceDialog(label=dialog_name, description="my dialog",
                                   submit=True, cancel=True,
                                   tab_label="tab_" + fauxfactory.gen_alphanumeric(),
                                   tab_desc="my tab desc",
                                   box_label="box_" + fauxfactory.gen_alphanumeric(),
                                   box_desc="my box desc", element_data=element_data)
    service_dialog.create()
    flash.assert_success_message('Dialog "{}" was added'.format(dialog_name))
    yield service_dialog

    # fixture cleanup
    try:
        service_dialog.delete()
    except NoSuchElementException or TimeoutException:
        logger.warning('test_catalog_item: dialog yield fixture cleanup, dialog "{}" not '
                       'found'.format(dialog_name))


@pytest.yield_fixture(scope="module")
def catalog():
    catalog_name = "test_cat_" + fauxfactory.gen_alphanumeric()
    cat = Catalog(name=catalog_name,
                  description="my catalog")
    cat.create()
    yield cat

    # fixture cleanup
    try:
        cat.delete()
    except NoSuchElementException:
        logger.warning('test_catalog_item: catalog yield fixture cleanup, catalog "{}" not '
                       'found'.format(catalog_name))


@pytest.yield_fixture(scope="function")
def catalog_item(dialog, catalog):
    cat_item = CatalogItem(item_type="Generic",
                           name='test_item_' + fauxfactory.gen_alphanumeric(),
                           description="my catalog item", display_in=True,
                           catalog=catalog, dialog=dialog)
    yield cat_item

    # fixture cleanup
    try:
        cat_item.delete()
    except NoSuchElementException:
        logger.warning('test_catalog_item: catalog_item yield fixture cleanup, catalog item "{}" '
                       'not found'.format(cat_item.name))


@pytest.yield_fixture(scope="function")
def catalog_bundle(catalog_item):
    catalog_item.create()
    bundle_name = "bundle" + fauxfactory.gen_alphanumeric()
    catalog_bundle = CatalogBundle(name=bundle_name, description="catalog_bundle",
                                   display_in=True, catalog=catalog_item.catalog,
                                   dialog=catalog_item.dialog,
                                   catalog_items=[catalog_item.name])
    yield catalog_bundle

    # fixture cleanup
    try:
        catalog_bundle.delete()
    except NoSuchElementException:
        logger.warning('test_catalog_item: catalog_item yield fixture cleanup, catalog item "{}" '
                       'not found'.format(catalog_bundle.name))


def test_create_catalog_item(catalog_item):
    catalog_item.create()
    flash.assert_success_message('Service Catalog Item "{}" was added'.format(catalog_item.name))


def test_update_catalog_item(catalog_item):
    catalog_item.create()
    with update(catalog_item):
        catalog_item.description = "my edited item description"


def test_add_button_group(catalog_item):
    catalog_item.create()
    catalog_item.add_button_group()


def test_add_button(catalog_item):
    catalog_item.create()
    catalog_item.add_button()


def test_edit_tags(catalog_item):
    catalog_item.create()
    catalog_item.edit_tags("Cost Center *", "Cost Center 001")


@pytest.mark.meta(blockers=[BZ(1313510, forced_streams=["5.6", "5.7", "upstream"])])
def test_catalog_item_duplicate_name(catalog_item):
    catalog_item.create()
    with error.expected("Name has already been taken"):
        catalog_item.create()


def test_permissions_catalog_item_add(catalog_item):
    """Test that a catalog can be added only with the right permissions."""
    tac.single_task_permission_test([['Everything', 'Services', 'Catalogs Explorer',
                                      'Catalog Items']],
                                    {'Add Catalog Item': catalog_item.create})


def test_tagvis_catalog_item(catalog_item, user_restricted, tag):
    """ Checks catalog item tag visibility for restricted user
    Prerequisites:
        Catalog, tag, role, group and restricted user should be created

    Steps:
        1. As admin add tag to catalog item
        2. Login as restricted user, catalog item is visible for user
        3. As admin remove tag
        4. Login as restricted user, catalog item is not visible for user
    """
    catalog_item.create()
    category_name = ' '.join((tag.category.display_name, '*'))
    catalog_item.edit_tags(category_name, tag.display_name)
    with user_restricted:
        assert catalog_item.exists

    catalog_item.remove_tag(category_name, tag.display_name)
    with user_restricted:
        assert not catalog_item.exists


def test_tagvis_catalog_bundle(user_restricted, tag, catalog_bundle):
    """ Checks catalog item tag visibility for restricted user
        Prerequisites:
            Catalog, tag, role, group, catalog item and restricted user should be created

        Steps:
            1. As admin add tag to catalog bundle
            2. Login as restricted user, catalog bundle is visible for user
            3. As admin remove tag
            4. Login as restricted user, catalog bundle is not visible for user
        """
    catalog_bundle.create()
    category_name = ' '.join((tag.category.display_name, '*'))
    catalog_bundle.edit_tags(category_name, tag.display_name)
    with user_restricted:
        assert catalog_bundle.exists

    catalog_bundle.remove_tag(category_name, tag.display_name)
    with user_restricted:
        assert not catalog_bundle.exists
