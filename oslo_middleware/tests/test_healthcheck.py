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

import mock
from oslotest import base as test_base
import webob.dec
import webob.exc

from oslo_middleware import healthcheck


class HealthcheckTests(test_base.BaseTestCase):

    @staticmethod
    @webob.dec.wsgify
    def application(req):
        return 'Hello, World!!!'

    def _do_test_request(self, conf={}, path='/healthcheck',
                         accept='text/plain', method='GET'):
        self.app = healthcheck.Healthcheck(self.application, conf)
        req = webob.Request.blank(path, accept=accept, method=method)
        res = req.get_response(self.app)
        return res

    def _do_test(self, conf={}, path='/healthcheck',
                 expected_code=webob.exc.HTTPOk.code,
                 expected_body=b'', accept='text/plain',
                 method='GET'):
        res = self._do_test_request(conf=conf, path=path,
                                    accept=accept, method=method)
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
        conf = {'backends': 'disable_by_file',
                'disable_by_file_path': '/foobar'}
        self._do_test(conf, expected_body=b'OK')
        self.assertIn('disable_by_file', self.app._backends.names())

    def test_disablefile_enabled_head(self):
        conf = {'backends': 'disable_by_file',
                'disable_by_file_path': '/foobar'}
        self._do_test(conf, expected_body=b'', method='HEAD',
                      expected_code=webob.exc.HTTPNoContent.code)

    def test_disablefile_enabled_html_detailed(self):
        conf = {'backends': 'disable_by_file',
                'disable_by_file_path': '/foobar', 'detailed': True}
        res = self._do_test_request(conf, accept="text/html")
        self.assertIn(b'Result of 1 checks:', res.body)
        self.assertIn(b'<TD>OK</TD>', res.body)
        self.assertEqual(webob.exc.HTTPOk.code, res.status_int)

    def test_disablefile_disabled(self):
        filename = self.create_tempfiles([('test', 'foobar')])[0]
        conf = {'backends': 'disable_by_file',
                'disable_by_file_path': filename}
        self._do_test(conf,
                      expected_code=webob.exc.HTTPServiceUnavailable.code,
                      expected_body=b'DISABLED BY FILE')
        self.assertIn('disable_by_file', self.app._backends.names())

    def test_disablefile_disabled_head(self):
        filename = self.create_tempfiles([('test', 'foobar')])[0]
        conf = {'backends': 'disable_by_file',
                'disable_by_file_path': filename}
        self._do_test(conf,
                      expected_code=webob.exc.HTTPServiceUnavailable.code,
                      expected_body=b'', method='HEAD')
        self.assertIn('disable_by_file', self.app._backends.names())

    def test_disablefile_disabled_html_detailed(self):
        filename = self.create_tempfiles([('test', 'foobar')])[0]
        conf = {'backends': 'disable_by_file',
                'disable_by_file_path': filename, 'detailed': True}
        res = self._do_test_request(conf, accept="text/html")
        self.assertIn(b'<TD>DISABLED BY FILE</TD>', res.body)
        self.assertEqual(webob.exc.HTTPServiceUnavailable.code,
                         res.status_int)

    def test_two_backends(self):
        filename = self.create_tempfiles([('test', 'foobar')])[0]
        conf = {'backends': 'disable_by_file,disable_by_file',
                'disable_by_file_path': filename}
        self._do_test(conf,
                      expected_code=webob.exc.HTTPServiceUnavailable.code,
                      expected_body=b'DISABLED BY FILE\nDISABLED BY FILE')
        self.assertIn('disable_by_file', self.app._backends.names())