# Copyright 2013, Nachi Ueno, NTT I3, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
import contextlib
import copy
import mock
import socket

from neutron.openstack.common import uuidutils
from neutron.plugins.common import constants

from neutron_vpnaas.extensions import vpnaas
from neutron_vpnaas.services.vpn.device_drivers import ipsec as ipsec_driver
from neutron_vpnaas.tests import base

_uuid = uuidutils.generate_uuid
FAKE_HOST = 'fake_host'
FAKE_ROUTER_ID = _uuid()
FAKE_IKE_POLICY = {
    'ike_version': 'v1',
    'encryption_algorithm': 'aes-128',
    'auth_algorithm': 'sha1',
    'pfs': 'group5'
}

FAKE_IPSEC_POLICY = {
    'encryption_algorithm': 'aes-128',
    'auth_algorithm': 'sha1',
    'pfs': 'group5'
}

FAKE_VPN_SERVICE = {
    'id': _uuid(),
    'router_id': FAKE_ROUTER_ID,
    'admin_state_up': True,
    'status': constants.PENDING_CREATE,
    'subnet': {'cidr': '10.0.0.0/24'},
    'ipsec_site_connections': [
        {'peer_cidrs': ['20.0.0.0/24',
                        '30.0.0.0/24'],
         'id': _uuid(),
         'peer_address': '30.0.0.5',
         'initiator': 'bi-directional',
         'ikepolicy': FAKE_IKE_POLICY,
         'ipsecpolicy': FAKE_IPSEC_POLICY,
         'status': constants.PENDING_CREATE},
        {'peer_cidrs': ['40.0.0.0/24',
                        '50.0.0.0/24'],
         'peer_address': '50.0.0.5',
         'id': _uuid(),
         'initiator': 'bi-directional',
         'ikepolicy': FAKE_IKE_POLICY,
         'ipsecpolicy': FAKE_IPSEC_POLICY,
         'status': constants.PENDING_CREATE}]
}


class TestIPsecDeviceDriver(base.BaseTestCase):
    def setUp(self, driver=ipsec_driver.OpenSwanDriver):
        super(TestIPsecDeviceDriver, self).setUp()

        for klass in [
            'os.makedirs',
            'os.path.isdir',
            'neutron.agent.linux.utils.replace_file',
            'neutron.common.rpc.create_connection',
            'neutron_vpnaas.services.vpn.device_drivers.ipsec.'
                'OpenSwanProcess._gen_config_content',
            'shutil.rmtree',
        ]:
            mock.patch(klass).start()
        self.execute = mock.patch(
            'neutron.agent.linux.utils.execute').start()
        self.agent = mock.Mock()
        self.driver = driver(
            self.agent,
            FAKE_HOST)
        self.driver.agent_rpc = mock.Mock()

    def _test_vpnservice_updated(self, expected_param, **kwargs):
        with mock.patch.object(self.driver, 'sync') as sync:
            context = mock.Mock()
            self.driver.vpnservice_updated(context, **kwargs)
            sync.assert_called_once_with(context, expected_param)

    def test_vpnservice_updated(self):
        self._test_vpnservice_updated([])

    def test_vpnservice_updated_with_router_info(self):
        router_info = {'id': FAKE_ROUTER_ID}
        kwargs = {'router': router_info}
        self._test_vpnservice_updated([router_info], **kwargs)

    def test_create_router(self):
        process_id = _uuid()
        process = mock.Mock()
        process.vpnservice = FAKE_VPN_SERVICE
        self.driver.processes = {
            process_id: process}
        self.driver.create_router(process_id)
        process.enable.assert_called_once_with()

    def test_destroy_router(self):
        process_id = _uuid()
        process = mock.Mock()
        process.vpnservice = FAKE_VPN_SERVICE
        self.driver.processes = {
            process_id: process}
        self.driver.destroy_router(process_id)
        process.disable.assert_called_once_with()
        self.assertNotIn(process_id, self.driver.processes)

    def _test_sync_check_service_helper(self, router_id):
        self.agent.assert_has_calls([
            mock.call.add_nat_rule(
                router_id,
                'POSTROUTING',
                '-s 10.0.0.0/24 -d 20.0.0.0/24 -m policy '
                '--dir out --pol ipsec -j ACCEPT ',
                top=True),
            mock.call.add_nat_rule(
                router_id,
                'POSTROUTING',
                '-s 10.0.0.0/24 -d 30.0.0.0/24 -m policy '
                '--dir out --pol ipsec -j ACCEPT ',
                top=True),
            mock.call.add_nat_rule(
                router_id,
                'POSTROUTING',
                '-s 10.0.0.0/24 -d 40.0.0.0/24 -m policy '
                '--dir out --pol ipsec -j ACCEPT ',
                top=True),
            mock.call.add_nat_rule(
                router_id,
                'POSTROUTING',
                '-s 10.0.0.0/24 -d 50.0.0.0/24 -m policy '
                '--dir out --pol ipsec -j ACCEPT ',
                top=True),
            mock.call.iptables_apply(router_id)
        ])
        self.driver.processes[router_id].update.assert_called_once_with()

    def test_sync(self):
        fake_vpn_service = FAKE_VPN_SERVICE
        self.driver.agent_rpc.get_vpn_services_on_host.return_value = [
            fake_vpn_service]
        context = mock.Mock()
        self.driver._sync_vpn_processes = mock.Mock()
        self.driver._delete_vpn_processes = mock.Mock()
        self.driver._cleanup_stale_vpn_processes = mock.Mock()
        sync_routers = [{'id': fake_vpn_service['router_id']}]
        sync_router_ids = [fake_vpn_service['router_id']]
        self.driver.sync(context, sync_routers)
        self.driver._sync_vpn_processes.assert_called_once_with(
            [fake_vpn_service], sync_router_ids)
        self.driver._delete_vpn_processes.assert_called_once_with(
            sync_router_ids, sync_router_ids)
        self.driver._cleanup_stale_vpn_processes.assert_called_once_with(
            sync_router_ids)

    def test__sync_vpn_processes_new_vpn_service(self):
        new_vpnservice = FAKE_VPN_SERVICE
        sync_router_id = new_vpnservice['router_id']
        self.driver.processes = {}
        with mock.patch.object(self.driver, 'ensure_process') as ensure_p:
            ensure_p.side_effect = self.fake_ensure_process
            self.driver._sync_vpn_processes([new_vpnservice], sync_router_id)
            self._test_sync_check_service_helper(new_vpnservice['router_id'])

    def test__sync_vpn_processes_router_with_no_vpn(self):
        """Test _sync_vpn_processes with a router not hosting vpnservice.

        This test case tests that when a router which doesn't host
        vpn services is updated, sync_vpn_processes doesn't restart/update
        the existing vpnservice processes.
        """
        process = mock.Mock()
        vpnservice = FAKE_VPN_SERVICE
        process.vpnservice = vpnservice
        process.connection_status = {}
        self.driver.processes = {
            vpnservice['router_id']: process}
        router_id_no_vpn = _uuid()
        with mock.patch.object(self.driver, 'ensure_process') as ensure_p:
            self.driver._sync_vpn_processes([vpnservice], [router_id_no_vpn])
            self.assertEqual(ensure_p.call_count, 0)

    def test__sync_vpn_processes_router_with_no_vpn_and_no_vpn_services(self):
        """No vpn services running and router not hosting vpn svc."""
        router_id_no_vpn = _uuid()
        self.driver.process_status_cache = {}
        self.driver.processes = {}
        with mock.patch.object(self.driver, 'ensure_process') as ensure_p:
            ensure_p.side_effect = self.fake_ensure_process
            self.driver._sync_vpn_processes([], [router_id_no_vpn])
            self.assertEqual(ensure_p.call_count, 0)

    def test__sync_vpn_processes_router_with_no_vpn_agent_restarted(self):
        """Test for the router not hosting vpnservice and agent restarted.

        This test case tests that when a non vpnservice hosted router
        is updated, _sync_vpn_processes restart/update the existing vpnservices
        which are not yet stored in driver.processes.
        """
        vpnservice = FAKE_VPN_SERVICE
        router_id_no_vpn = _uuid()
        self.driver.process_status_cache = {}
        self.driver.processes = {}
        with mock.patch.object(self.driver, 'ensure_process') as ensure_p:
            ensure_p.side_effect = self.fake_ensure_process
            self.driver._sync_vpn_processes([vpnservice], [router_id_no_vpn])
            self._test_sync_check_service_helper(vpnservice['router_id'])

    def test_delete_vpn_processes(self):
        router_id_no_vpn = _uuid()
        vpn_service_router_id = _uuid()
        with contextlib.nested(
            mock.patch.object(self.driver, 'ensure_process'),
            mock.patch.object(self.driver, 'destroy_router')
        ) as (fake_ensure_process, fake_destroy_router):
            self.driver._delete_vpn_processes([router_id_no_vpn],
                                              [vpn_service_router_id])
            fake_ensure_process.assert_has_calls(
                [mock.call(router_id_no_vpn)])
            fake_destroy_router.assert_has_calls(
                [mock.call(router_id_no_vpn)])

        # test that _delete_vpn_processes doesn't delete the
        # the valid vpn processes
        with contextlib.nested(
            mock.patch.object(self.driver, 'ensure_process'),
            mock.patch.object(self.driver, 'destroy_router')
        ) as (fake_ensure_process, fake_destroy_router):
            self.driver._delete_vpn_processes([vpn_service_router_id],
                                              [vpn_service_router_id])
            self.assertEqual(fake_ensure_process.call_count, 0)
            self.assertEqual(fake_destroy_router.call_count, 0)

    def test_cleanup_stale_vpn_processes(self):
        stale_vpn_service = {'router_id': _uuid()}
        active_vpn_service = {'router_id': _uuid()}
        self.driver.processes = {
            stale_vpn_service['router_id']: stale_vpn_service,
            active_vpn_service['router_id']: active_vpn_service}
        with mock.patch.object(self.driver, 'destroy_router') as destroy_r:
            self.driver._cleanup_stale_vpn_processes(
                [active_vpn_service['router_id']])
            destroy_r.assert_has_calls(
                [mock.call(stale_vpn_service['router_id'])])

    def fake_ensure_process(self, process_id, vpnservice=None):
        process = self.driver.processes.get(process_id)
        if not process:
            process = mock.Mock()
            process.vpnservice = FAKE_VPN_SERVICE
            process.connection_status = {}
            process.status = constants.ACTIVE
            process.updated_pending_status = True
            self.driver.processes[process_id] = process
        elif vpnservice:
            process.vpnservice = vpnservice
            process.update_vpnservice(vpnservice)
        return process

    def fake_destroy_router(self, process_id):
        process = self.driver.processes.get(process_id)
        if process:
            del self.driver.processes[process_id]

    def test_sync_update_vpnservice(self):
        with mock.patch.object(self.driver,
                               'ensure_process') as ensure_process:
            ensure_process.side_effect = self.fake_ensure_process
            new_vpn_service = FAKE_VPN_SERVICE
            updated_vpn_service = copy.deepcopy(new_vpn_service)
            updated_vpn_service['ipsec_site_connections'].append(
                {'peer_cidrs': ['60.0.0.0/24',
                                '70.0.0.0/24']})
            context = mock.Mock()
            self.driver.process_status_cache = {}
            self.driver.agent_rpc.get_vpn_services_on_host.return_value = [
                new_vpn_service]
            self.driver.sync(context, [{'id': FAKE_ROUTER_ID}])
            process = self.driver.processes[FAKE_ROUTER_ID]
            self.assertEqual(process.vpnservice, new_vpn_service)
            self.driver.agent_rpc.get_vpn_services_on_host.return_value = [
                updated_vpn_service]
            self.driver.sync(context, [{'id': FAKE_ROUTER_ID}])
            process = self.driver.processes[FAKE_ROUTER_ID]
            process.update_vpnservice.assert_called_once_with(
                updated_vpn_service)
            self.assertEqual(process.vpnservice, updated_vpn_service)

    def test_sync_removed(self):
        self.driver.agent_rpc.get_vpn_services_on_host.return_value = []
        context = mock.Mock()
        process_id = _uuid()
        process = mock.Mock()
        process.vpnservice = FAKE_VPN_SERVICE
        self.driver.processes = {
            process_id: process}
        self.driver.sync(context, [])
        process.disable.assert_called_once_with()
        self.assertNotIn(process_id, self.driver.processes)

    def test_sync_removed_router(self):
        self.driver.agent_rpc.get_vpn_services_on_host.return_value = []
        context = mock.Mock()
        process_id = _uuid()
        self.driver.sync(context, [{'id': process_id}])
        self.assertNotIn(process_id, self.driver.processes)

    def test_status_updated_on_connection_admin_down(self):
        self.driver.process_status_cache = {
            '1': {
                'status': constants.ACTIVE,
                'id': 123,
                'updated_pending_status': False,
                'ipsec_site_connections': {
                    '10': {
                        'status': constants.ACTIVE,
                        'updated_pending_status': False,
                    },
                    '20': {
                        'status': constants.ACTIVE,
                        'updated_pending_status': False,
                    }
                }
            }
        }
        # Simulate that there is no longer status for connection '20'
        # e.g. connection admin down
        new_status = {
            'ipsec_site_connections': {
                '10': {
                    'status': constants.ACTIVE,
                    'updated_pending_status': False
                }
            }
        }
        self.driver.update_downed_connections('1', new_status)
        existing_conn = new_status['ipsec_site_connections'].get('10')
        self.assertIsNotNone(existing_conn)
        self.assertEqual(constants.ACTIVE, existing_conn['status'])
        missing_conn = new_status['ipsec_site_connections'].get('20')
        self.assertIsNotNone(missing_conn)
        self.assertEqual(constants.DOWN, missing_conn['status'])

    def test_status_updated_on_service_admin_down(self):
        self.driver.process_status_cache = {
            '1': {
                'status': constants.ACTIVE,
                'id': 123,
                'updated_pending_status': False,
                'ipsec_site_connections': {
                    '10': {
                        'status': constants.ACTIVE,
                        'updated_pending_status': False,
                    },
                    '20': {
                        'status': constants.ACTIVE,
                        'updated_pending_status': False,
                    }
                }
            }
        }
        # Simulate that there are no connections now
        new_status = {
            'ipsec_site_connections': {}
        }
        self.driver.update_downed_connections('1', new_status)
        missing_conn = new_status['ipsec_site_connections'].get('10')
        self.assertIsNotNone(missing_conn)
        self.assertEqual(constants.DOWN, missing_conn['status'])
        missing_conn = new_status['ipsec_site_connections'].get('20')
        self.assertIsNotNone(missing_conn)
        self.assertEqual(constants.DOWN, missing_conn['status'])


class TestOpenSwanProcess(base.BaseTestCase):
    def setUp(self):
        super(TestOpenSwanProcess, self).setUp()
        self.driver = ipsec_driver.OpenSwanProcess(mock.ANY, 'foo-process-id',
                                                   FAKE_VPN_SERVICE, mock.ANY)

    def test__resolve_fqdn(self):
        with mock.patch.object(socket, 'getaddrinfo') as mock_getaddr_info:
            mock_getaddr_info.return_value = [(2, 1, 6, '',
                                              ('172.168.1.2', 0))]
            resolved_ip_addr = self.driver._resolve_fqdn('fqdn.foo.addr')
            self.assertEqual('172.168.1.2', resolved_ip_addr)

    def _test_get_nexthop_helper(self, address, _resolve_fqdn_side_effect,
                                 _execute_ret_val, expected_ip_cmd,
                                 expected_nexthop):
        with contextlib.nested(
            mock.patch.object(self.driver, '_execute'),
            mock.patch.object(self.driver, '_resolve_fqdn')
        ) as (fake_execute, fake_resolve_fqdn):
            fake_resolve_fqdn.side_effect = _resolve_fqdn_side_effect
            fake_execute.return_value = _execute_ret_val

            returned_next_hop = self.driver._get_nexthop(address)
            _resolve_fqdn_expected_call_count = (
                1 if _resolve_fqdn_side_effect else 0)

            self.assertEqual(_resolve_fqdn_expected_call_count,
                             fake_resolve_fqdn.call_count)
            fake_execute.assert_called_once_with(expected_ip_cmd)
            self.assertEqual(expected_nexthop, returned_next_hop)

    def test__get_nexthop_peer_addr_is_ipaddr(self):
        gw_addr = '10.0.0.1'
        _fake_execute_ret_val = '172.168.1.2 via %s' % gw_addr
        peer_address = '172.168.1.2'
        expected_ip_cmd = ['ip', 'route', 'get', peer_address]
        self._test_get_nexthop_helper(peer_address, None,
                                      _fake_execute_ret_val, expected_ip_cmd,
                                      gw_addr)

    def test__get_nexthop_peer_addr_is_valid_fqdn(self):
        peer_address = 'foo.peer.addr'
        expected_ip_cmd = ['ip', 'route', 'get', '172.168.1.2']
        gw_addr = '10.0.0.1'
        _fake_execute_ret_val = '172.168.1.2 via %s' % gw_addr

        def _fake_resolve_fqdn(address):
            return '172.168.1.2'

        self._test_get_nexthop_helper(peer_address, _fake_resolve_fqdn,
                                      _fake_execute_ret_val, expected_ip_cmd,
                                      gw_addr)

    def test__get_nexthop_gw_not_present(self):
        peer_address = '172.168.1.2'
        expected_ip_cmd = ['ip', 'route', 'get', '172.168.1.2']
        _fake_execute_ret_val = ' '

        self._test_get_nexthop_helper(peer_address, None,
                                      _fake_execute_ret_val, expected_ip_cmd,
                                      peer_address)

    def test__get_nexthop_fqdn_peer_addr_is_not_resolved(self):
        self.assertRaises(vpnaas.VPNPeerAddressNotResolved,
                          self.driver._get_nexthop, 'foo.peer.addr')
