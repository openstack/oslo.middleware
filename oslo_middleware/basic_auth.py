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
import binascii
import logging

import bcrypt
import webob

from oslo_config import cfg
from oslo_middleware import base
from oslo_middleware import exceptions

LOG = logging.getLogger(__name__)

OPTS = [
    cfg.StrOpt('http_basic_auth_user_file',
               default='/etc/htpasswd',
               help="HTTP basic auth password file.")
]

cfg.CONF.register_opts(OPTS, group='oslo_middleware')


class BasicAuthMiddleware(base.ConfigurableMiddleware):
    """Middleware which performs HTTP basic authentication on requests"""

    def __init__(self, application, conf=None):
        super().__init__(application, conf)
        self.auth_file = cfg.CONF.oslo_middleware.http_basic_auth_user_file
        validate_auth_file(self.auth_file)

    def format_exception(self, e):
        result = {'error': {'message': str(e), 'code': 401}}
        headers = [('Content-Type', 'application/json')]
        return webob.Response(content_type='application/json',
                              status_code=401,
                              json_body=result,
                              headerlist=headers)

    @webob.dec.wsgify
    def __call__(self, req):
        try:
            token = parse_header(req.environ)
            username, password = parse_token(token)
            req.environ.update(authenticate(
                self.auth_file, username, password))
            return self.application
        except Exception as e:
            response = self.format_exception(e)
            return self.process_response(response)


def authenticate(auth_file, username, password):
    """Finds username and password match in Apache style user auth file

    The user auth file format is expected to comply with Apache
    documentation[1] however the bcrypt password digest is the *only*
    digest format supported.

    [1] https://httpd.apache.org/docs/current/misc/password_encryptions.html

    :param: auth_file: Path to user auth file
    :param: username: Username to authenticate
    :param: password: Password encoded as bytes
    :returns: A dictionary of WSGI environment values to append to the request
    :raises: HTTPUnauthorized, if no file entries match username/password
    """

    line_prefix = username + ':'
    try:
        with open(auth_file) as f:
            for line in f:
                entry = line.strip()
                if entry and entry.startswith(line_prefix):
                    return auth_entry(entry, password)
    except OSError as exc:
        LOG.error('Problem reading auth file: %s', exc)
        raise webob.exc.HTTPBadRequest(
            detail='Problem reading auth file')
    # reached end of file with no matches
    LOG.info('User %s not found', username)
    raise webob.exc.HTTPUnauthorized()


def auth_entry(entry, password):
    """Compare a password with a single user auth file entry

    :param: entry: Line from auth user file to use for authentication
    :param: password: Password encoded as bytes
    :returns: A dictionary of WSGI environment values to append to the request
    :raises: HTTPUnauthorized, if the entry doesn't match supplied password or
        if the entry is crypted with a method other than bcrypt
    """

    username, crypted = parse_entry(entry)
    if not bcrypt.checkpw(password, crypted):
        LOG.info('Password for %s does not match', username)
        raise webob.exc.HTTPUnauthorized()
    return {
        'HTTP_X_USER': username,
        'HTTP_X_USER_NAME': username
    }


def validate_auth_file(auth_file):
    """Read the auth user file and validate its correctness

    :param: auth_file: Path to user auth file
    :raises: ConfigInvalid on validation error
    """

    try:
        with open(auth_file) as f:
            for line in f:
                entry = line.strip()
                if entry and ':' in entry:
                    parse_entry(entry)
    except OSError:
        raise exceptions.ConfigInvalid(
            error_msg='Problem reading auth user file')


def parse_entry(entry):
    """Extrace the username and crypted password from a user auth file entry

    :param: entry: Line from auth user file to use for authentication
    :returns: a tuple of username and crypted password
    :raises: ConfigInvalid if the password is not in the supported bcrypt
    format
    """

    username, crypted_str = entry.split(':', maxsplit=1)
    crypted = crypted_str.encode('utf-8')
    if crypted[:4] not in (b'$2y$', b'$2a$', b'$2b$'):
        error_msg = ('Only bcrypt digested passwords are supported for '
                     '%(username)s') % {'username': username}
        raise webob.exc.HTTPBadRequest(detail=error_msg)
    return username, crypted


def parse_token(token):
    """Parse the token portion of the Authentication header value

    :param: token: Token value from basic authorization header
    :returns: tuple of username, password
    :raises: BadRequest, if username and password could not be parsed for any
        reason
    """

    try:
        if isinstance(token, str):
            token = token.encode('utf-8')
        auth_pair = base64.b64decode(token, validate=True)
        (username, password) = auth_pair.split(b':', maxsplit=1)
        return (username.decode('utf-8'), password)
    except (TypeError, binascii.Error, ValueError) as exc:
        LOG.info('Could not decode authorization token: %s', exc)
        raise webob.exc.HTTPBadRequest(detail=(
            'Could not decode authorization token'))


def parse_header(env):
    """Parse WSGI environment for Authorization header of type Basic

    :param: env: WSGI environment to get header from
    :returns: Token portion of the header value
    :raises: HTTPUnauthorized, if header is missing or if the type is not Basic
    """

    try:
        auth_header = env.pop('HTTP_AUTHORIZATION')
    except KeyError:
        LOG.info('No authorization token received')
        raise webob.exc.HTTPUnauthorized()
    try:
        auth_type, token = auth_header.strip().split(maxsplit=1)
    except (ValueError, AttributeError) as exc:
        LOG.info('Could not parse Authorization header: %s', exc)
        raise webob.exc.HTTPBadRequest(detail=(
            'Could not parse Authorization header'))
    if auth_type.lower() != 'basic':
        error_msg = ('Unsupported authorization type "%s"') % auth_type
        LOG.info(error_msg)
        raise webob.exc.HTTPBadRequest(detail=error_msg)
    return token
