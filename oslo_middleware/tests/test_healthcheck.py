# Copyright (c) 2013 NEC Corporation
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

import threading
import time
from unittest import mock

from oslo_config import fixture as config
from oslo_serialization import jsonutils
from oslotest import base as test_base
import requests
import webob.dec
import webob.exc

from oslo_middleware.exceptions import ConfigInvalid
from oslo_middleware import healthcheck
from oslo_middleware.healthcheck import __main__


class HealthcheckMainTests(test_base.BaseTestCase):
    def test_startup_response(self):
        server = __main__.create_server(0)
        th = threading.Thread(target=server.serve_forever)
        th.start()
        self.addCleanup(server.shutdown)
        while True:
            try:
                # Connecting on 0.0.0.0 is not allowed on windows
                # The operating system will return WSAEADDRNOTAVAIL which
                # in turn will throw a requests.ConnectionError
                r = requests.get(
                    f"http://127.0.0.1:{server.server_address[1]}",
                    timeout=10,
                )
            except requests.ConnectionError:
                # Server hasn't started up yet, try again in a few.
                time.sleep(1)
            else:
                self.assertEqual(200, r.status_code)
                break


class HealthcheckTests(test_base.BaseTestCase):
    def setUp(self):
        super().setUp()
        self.useFixture(config.Config())

    @staticmethod
    @webob.dec.wsgify
    def application(req):
        return 'Hello, World!!!'

    def _do_test_request(
        self,
        conf={},
        path='/healthcheck',
        accept='text/plain',
        method='GET',
        server_port=80,
        headers=None,
        remote_addr='127.0.0.1',
    ):
        self.app = healthcheck.Healthcheck(self.application, conf)
        req = webob.Request.blank(path, accept=accept, method=method)
        req.server_port = server_port
        if headers:
            req.headers = headers
        req.remote_addr = remote_addr
        res = req.get_response(self.app)
        return res

    def _do_test(
        self,
        conf={},
        path='/healthcheck',
        expected_code=webob.exc.HTTPOk.code,
        expected_body=b'',
        accept='text/plain',
        method='GET',
        server_port=80,
        headers=None,
        remote_addr='127.0.0.1',
    ):
        res = self._do_test_request(
            conf=conf,
            path=path,
            accept=accept,
            method=method,
            server_port=server_port,
            headers=headers,
            remote_addr=remote_addr,
        )
        self.assertEqual(expected_code, res.status_int)
        self.assertEqual(expected_body, res.body)

    def test_default_path_match(self):
        self._do_test()

    def test_default_path_not_match(self):
        self._do_test(path='/toto', expected_body=b'Hello, World!!!')

    def test_configured_path_match(self):
        conf = {'path': '/hidden_healthcheck'}
        self._do_test(conf, path='/hidden_healthcheck')

    def test_configured_path_not_match(self):
        conf = {'path': '/hidden_healthcheck'}
        self._do_test(conf, path='/toto', expected_body=b'Hello, World!!!')

    @mock.patch('oslo_middleware.healthcheck.disable_by_file.LOG')
    def test_disablefile_unconfigured(self, fake_log):
        fake_warn = fake_log.warning
        conf = {'backends': 'disable_by_file'}
        self._do_test(conf, expected_body=b'OK')
        self.assertIn('disable_by_file', self.app._backends.names())
        fake_warn.assert_called_once_with(
            'DisableByFile healthcheck middleware '
            'enabled without disable_by_file_path '
            'set'
        )

    def test_disablefile_enabled(self):
        conf = {
            'backends': 'disable_by_file',
            'disable_by_file_path': '/foobar',
        }
        self._do_test(conf, expected_body=b'OK')
        self.assertIn('disable_by_file', self.app._backends.names())

    def test_disablefile_enabled_head(self):
        conf = {
            'backends': 'disable_by_file',
            'disable_by_file_path': '/foobar',
        }
        self._do_test(
            conf,
            expected_body=b'',
            method='HEAD',
            expected_code=webob.exc.HTTPNoContent.code,
        )

    def test_disablefile_enabled_html_detailed(self):
        conf = {
            'backends': 'disable_by_file',
            'disable_by_file_path': '/foobar',
            'detailed': True,
        }
        res = self._do_test_request(conf, accept="text/html")
        self.assertIn(b'Result of 1 checks:', res.body)
        self.assertIn(b'<TD>OK</TD>', res.body)
        self.assertEqual(webob.exc.HTTPOk.code, res.status_int)

    def test_disablefile_disabled(self):
        filename = self.create_tempfiles([('test', 'foobar')])[0]
        conf = {
            'backends': 'disable_by_file',
            'disable_by_file_path': filename,
        }
        self._do_test(
            conf,
            expected_code=webob.exc.HTTPServiceUnavailable.code,
            expected_body=b'DISABLED BY FILE',
        )
        self.assertIn('disable_by_file', self.app._backends.names())

    def test_disablefile_disabled_head(self):
        filename = self.create_tempfiles([('test', 'foobar')])[0]
        conf = {
            'backends': 'disable_by_file',
            'disable_by_file_path': filename,
        }
        self._do_test(
            conf,
            expected_code=webob.exc.HTTPServiceUnavailable.code,
            expected_body=b'',
            method='HEAD',
        )
        self.assertIn('disable_by_file', self.app._backends.names())

    def test_disablefile_disabled_html_detailed(self):
        filename = self.create_tempfiles([('test', 'foobar')])[0]
        conf = {
            'backends': 'disable_by_file',
            'disable_by_file_path': filename,
            'detailed': True,
        }
        res = self._do_test_request(conf, accept="text/html")
        self.assertIn(b'<TD>DISABLED BY FILE</TD>', res.body)
        self.assertEqual(webob.exc.HTTPServiceUnavailable.code, res.status_int)

    def test_two_backends(self):
        filename = self.create_tempfiles([('test', 'foobar')])[0]
        conf = {
            'backends': 'disable_by_file,disable_by_file',
            'disable_by_file_path': filename,
        }
        self._do_test(
            conf,
            expected_code=webob.exc.HTTPServiceUnavailable.code,
            expected_body=b'DISABLED BY FILE\nDISABLED BY FILE',
        )
        self.assertIn('disable_by_file', self.app._backends.names())

    def test_disable_by_port_file(self):
        filename = self.create_tempfiles([('test', 'foobar')])[0]
        conf = {
            'backends': 'disable_by_files_ports',
            'disable_by_file_paths': f"80:{filename}",
        }
        self._do_test(
            conf,
            expected_code=webob.exc.HTTPServiceUnavailable.code,
            expected_body=b'DISABLED BY FILE',
        )
        self.assertIn('disable_by_files_ports', self.app._backends.names())

    def test_no_disable_by_port_file(self):
        filename = self.create_tempfiles([('test', 'foobar')])[0]
        conf = {
            'backends': 'disable_by_files_ports',
            'disable_by_file_paths': f"8000:{filename}",
        }
        self._do_test(
            conf, expected_code=webob.exc.HTTPOk.code, expected_body=b'OK'
        )
        self.assertIn('disable_by_files_ports', self.app._backends.names())

    def test_disable_by_port_many_files(self):
        filename = self.create_tempfiles([('test', 'foobar')])[0]
        filename2 = self.create_tempfiles([('test2', 'foobar2')])[0]
        conf = {
            'backends': 'disable_by_files_ports',
            'disable_by_file_paths': f"80:{filename},81:{filename2}",
        }
        self._do_test(
            conf,
            expected_code=webob.exc.HTTPServiceUnavailable.code,
            expected_body=b'DISABLED BY FILE',
        )
        self._do_test(
            conf,
            expected_code=webob.exc.HTTPServiceUnavailable.code,
            expected_body=b'DISABLED BY FILE',
            server_port=81,
        )
        self.assertIn('disable_by_files_ports', self.app._backends.names())

    def test_enablefile_disablefile_configured(self):
        conf = {'backends': 'disable_by_file,enable_by_files'}
        self.assertRaises(
            ConfigInvalid, healthcheck.Healthcheck, self.application, conf
        )

    def test_enablefile_unconfigured(self):
        conf = {'backends': 'enable_by_files'}
        self._do_test(conf, expected_body=b'OK')
        self.assertIn('enable_by_files', self.app._backends.names())

    def test_enablefile_enabled(self):
        filename = self.create_tempfiles([('.test', '.foobar')])[0]
        conf = {
            'backends': 'enable_by_files',
            'enable_by_file_paths': filename,
        }
        self._do_test(conf, expected_body=b'OK')
        self.assertIn('enable_by_files', self.app._backends.names())

    def test_enablefile_enabled_head(self):
        filename = self.create_tempfiles([('.test', '.foobar')])[0]
        conf = {
            'backends': 'enable_by_files',
            'enable_by_file_paths': filename,
        }
        self._do_test(
            conf,
            expected_body=b'',
            method='HEAD',
            expected_code=webob.exc.HTTPNoContent.code,
        )

    def test_enablefile_enabled_html_detailed(self):
        filename = self.create_tempfiles([('.test', '.foobar')])[0]
        conf = {
            'backends': 'enable_by_files',
            'enable_by_file_paths': filename,
            'detailed': True,
        }
        res = self._do_test_request(conf, accept="text/html")
        self.assertIn(b'Result of 1 checks:', res.body)
        self.assertIn(b'<TD>OK</TD>', res.body)
        self.assertEqual(webob.exc.HTTPOk.code, res.status_int)

    def test_enablefile_disabled(self):
        conf = {
            'backends': 'enable_by_files',
            'enable_by_file_paths': '.foobar',
        }
        self._do_test(
            conf,
            expected_code=webob.exc.HTTPServiceUnavailable.code,
            expected_body=b'FILE PATH MISSING',
        )
        self.assertIn('enable_by_files', self.app._backends.names())

    def test_enablefile_disabled_head(self):
        conf = {
            'backends': 'enable_by_files',
            'enable_by_file_paths': '.foobar',
        }
        self._do_test(
            conf,
            expected_code=webob.exc.HTTPServiceUnavailable.code,
            expected_body=b'',
            method='HEAD',
        )
        self.assertIn('enable_by_files', self.app._backends.names())

    def test_enablefile_disabled_html_detailed(self):
        conf = {
            'backends': 'enable_by_files',
            'enable_by_file_paths': '.foobar',
            'detailed': True,
        }
        res = self._do_test_request(conf, accept="text/html")
        self.assertIn(b'<TD>FILE PATH MISSING</TD>', res.body)
        self.assertEqual(webob.exc.HTTPServiceUnavailable.code, res.status_int)

    def test_json_response(self):
        expected_body = jsonutils.dumps(
            {'detailed': False, 'reasons': []}, indent=4, sort_keys=True
        ).encode('utf-8')
        self._do_test(expected_body=expected_body, accept='application/json')

    def test_source_within_allowed_ranges(self):
        conf = {'allowed_source_ranges': ['192.168.0.0/24', '192.168.1.0/24']}
        self._do_test(
            conf,
            expected_code=webob.exc.HTTPOk.code,
            remote_addr='192.168.0.1',
        )

    def test_source_out_of_allowed_ranges(self):
        conf = {'allowed_source_ranges': ['192.168.0.0/24', '192.168.1.0/24']}
        self._do_test(
            conf,
            expected_code=webob.exc.HTTPOk.code,
            expected_body=b'Hello, World!!!',
            remote_addr='192.168.3.1',
        )

    def test_proxied_not_ignored(self):
        self._do_test(
            {},
            expected_code=webob.exc.HTTPOk.code,
            headers={'Forwarded-For': 'http://localhost'},
        )

    def test_proxied_ignored(self):
        conf = {'ignore_proxied_requests': True}
        modern_headers = {'x-forwarded': 'https://localhost'}
        self._do_test(
            conf,
            expected_code=webob.exc.HTTPOk.code,
            expected_body=b'Hello, World!!!',
            headers=modern_headers,
        )
        legacy_headers = {
            'x-forwarded-proto': 'https',
            'x-forwarded-host': 'localhost',
            'x-forwarded-for': '192.0.2.11',
        }
        self._do_test(
            conf,
            expected_code=webob.exc.HTTPOk.code,
            expected_body=b'Hello, World!!!',
            headers=legacy_headers,
        )
