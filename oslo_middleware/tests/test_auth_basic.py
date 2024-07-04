# Copyright 2012 OpenStack Foundation
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

import base64
import os
import tempfile

from oslo_config import cfg
import webob

from oslo_middleware import basic_auth as auth
from oslo_middleware import exceptions as exc
from oslotest import base as test_base


class TestAuthBasic(test_base.BaseTestCase):
    def setUp(self):
        super().setUp()

        @webob.dec.wsgify
        def fake_app(req):
            return webob.Response()
        self.fake_app = fake_app
        self.request = webob.Request.blank('/')

    def write_auth_file(self, data=None):
        if not data:
            data = '\n'
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write(data)
            self.addCleanup(os.remove, f.name)
            return f.name

    def test_middleware_authenticate(self):
        auth_file = self.write_auth_file(
            'myName:$2y$05$lE3eGtyj41jZwrzS87KTqe6.'
            'JETVCWBkc32C63UP2aYrGoYOEpbJm\n\n\n')
        cfg.CONF.set_override('http_basic_auth_user_file',
                              auth_file, group='oslo_middleware')
        self.middleware = auth.BasicAuthMiddleware(self.fake_app)
        self.request.environ[
            'HTTP_AUTHORIZATION'] = 'Basic bXlOYW1lOm15UGFzc3dvcmQ='
        response = self.request.get_response(self.middleware)
        self.assertEqual('200 OK', response.status)

    def test_middleware_unauthenticated(self):
        auth_file = self.write_auth_file(
            'myName:$2y$05$lE3eGtyj41jZwrzS87KTqe6.'
            'JETVCWBkc32C63UP2aYrGoYOEpbJm\n\n\n')
        cfg.CONF.set_override('http_basic_auth_user_file',
                              auth_file, group='oslo_middleware')

        self.middleware = auth.BasicAuthMiddleware(self.fake_app)
        response = self.request.get_response(self.middleware)
        self.assertEqual('401 Unauthorized', response.status)

    def test_authenticate(self):
        auth_file = self.write_auth_file(
            'foo:bar\nmyName:$2y$05$lE3eGtyj41jZwrzS87KTqe6.'
            'JETVCWBkc32C63UP2aYrGoYOEpbJm\n\n\n')
        # test basic auth
        self.assertEqual(
            {'HTTP_X_USER': 'myName', 'HTTP_X_USER_NAME': 'myName'},
            auth.authenticate(
                auth_file, 'myName', b'myPassword')
        )
        # test failed auth
        e = self.assertRaises(webob.exc.HTTPBadRequest,
                              auth.authenticate,
                              auth_file, 'foo', b'bar')
        self.assertEqual('Only bcrypt digested '
                         'passwords are supported for foo', str(e))
        # test problem reading user data file
        auth_file = auth_file + '.missing'
        e = self.assertRaises(webob.exc.HTTPBadRequest,
                              auth.authenticate,
                              auth_file, 'myName',
                              b'myPassword')
        self.assertEqual(
            'Problem reading auth file', str(e))

    def test_auth_entry(self):
        entry_pass = ('myName:$2y$05$lE3eGtyj41jZwrzS87KTqe6.'
                      'JETVCWBkc32C63UP2aYrGoYOEpbJm')
        entry_fail = 'foo:bar'
        # success
        self.assertEqual(
            {'HTTP_X_USER': 'myName', 'HTTP_X_USER_NAME': 'myName'},
            auth.auth_entry(entry_pass, b'myPassword')
        )
        # failed, unknown digest format
        ex = self.assertRaises(webob.exc.HTTPBadRequest,
                               auth.auth_entry, entry_fail, b'bar')
        self.assertEqual('Only bcrypt digested '
                         'passwords are supported for foo', str(ex))
        # failed, incorrect password
        self.assertRaises(webob.exc.HTTPUnauthorized,
                          auth.auth_entry, entry_pass, b'bar')

    def test_validate_auth_file(self):
        auth_file = self.write_auth_file(
            'myName:$2y$05$lE3eGtyj41jZwrzS87KTqe6.'
            'JETVCWBkc32C63UP2aYrGoYOEpbJm\n\n\n')
        # success, valid config
        auth.validate_auth_file(auth_file)
        # failed, missing auth file
        auth_file = auth_file + '.missing'
        self.assertRaises(exc.ConfigInvalid,
                          auth.validate_auth_file, auth_file)
        # failed, invalid entry
        auth_file = self.write_auth_file(
            'foo:bar\nmyName:$2y$05$lE3eGtyj41jZwrzS87KTqe6.'
            'JETVCWBkc32C63UP2aYrGoYOEpbJm\n\n\n')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          auth.validate_auth_file, auth_file)

    def test_parse_token(self):
        # success with bytes
        token = base64.b64encode(b'myName:myPassword')
        self.assertEqual(
            ('myName', b'myPassword'),
            auth.parse_token(token)
        )
        # success with string
        token = str(token, encoding='utf-8')
        self.assertEqual(
            ('myName', b'myPassword'),
            auth.parse_token(token)
        )
        # failed, invalid base64
        e = self.assertRaises(webob.exc.HTTPBadRequest,
                              auth.parse_token, token[:-1])
        self.assertEqual('Could not decode authorization token', str(e))
        # failed, no colon in token
        token = str(base64.b64encode(b'myNamemyPassword'), encoding='utf-8')
        e = self.assertRaises(webob.exc.HTTPBadRequest,
                              auth.parse_token, token[:-1])
        self.assertEqual('Could not decode authorization token', str(e))

    def test_parse_header(self):
        auth_value = 'Basic bXlOYW1lOm15UGFzc3dvcmQ='
        # success
        self.assertEqual(
            'bXlOYW1lOm15UGFzc3dvcmQ=',
            auth.parse_header({
                'HTTP_AUTHORIZATION': auth_value
            })
        )
        # failed, missing Authorization header
        e = self.assertRaises(webob.exc.HTTPUnauthorized,
                              auth.parse_header,
                              {})
        # failed missing token
        e = self.assertRaises(webob.exc.HTTPBadRequest,
                              auth.parse_header,
                              {'HTTP_AUTHORIZATION': 'Basic'})
        self.assertEqual('Could not parse Authorization header', str(e))
        # failed, type other than Basic
        digest_value = 'Digest username="myName" nonce="foobar"'
        e = self.assertRaises(webob.exc.HTTPBadRequest,
                              auth.parse_header,
                              {'HTTP_AUTHORIZATION': digest_value})
        self.assertEqual('Unsupported authorization type "Digest"', str(e))
