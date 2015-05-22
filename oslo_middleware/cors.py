# Copyright (c) 2015 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied. See the License for the specific language governing permissions and
# limitations under the License.

# Default allowed headers
import copy
import logging
from oslo_config import cfg
from oslo_middleware import base
import webob.dec
import webob.exc
import webob.response


LOG = logging.getLogger(__name__)

CORS_OPTS = [
    cfg.StrOpt('allowed_origin',
               default=None,
               help='Indicate whether this resource may be shared with the '
                    'domain received in the requests "origin" header.'),
    cfg.BoolOpt('allow_credentials',
                default=True,
                help='Indicate that the actual request can include user '
                     'credentials'),
    cfg.ListOpt('expose_headers',
                default=['Content-Type', 'Cache-Control', 'Content-Language',
                         'Expires', 'Last-Modified', 'Pragma'],
                help='Indicate which headers are safe to expose to the API. '
                     'Defaults to HTTP Simple Headers.'),
    cfg.IntOpt('max_age',
               default=3600,
               help='Maximum cache age of CORS preflight requests.'),
    cfg.ListOpt('allow_methods',
                default=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
                help='Indicate which methods can be used during the actual '
                     'request.'),
    cfg.ListOpt('allow_headers',
                default=['Content-Type', 'Cache-Control', 'Content-Language',
                         'Expires', 'Last-Modified', 'Pragma'],
                help='Indicate which header field names may be used during '
                     'the actual request.')
]


class CORS(base.Middleware):
    """CORS Middleware.

    This middleware allows a WSGI app to serve CORS headers for multiple
    configured domains.

    For more information, see http://www.w3.org/TR/cors/
    """

    simple_headers = [
        'Content-Type',
        'Cache-Control',
        'Content-Language',
        'Expires',
        'Last-Modified',
        'Pragma'
    ]

    def __init__(self, application, conf):
        super(CORS, self).__init__(application)

        # First, check the configuration and register global options.
        if not conf or not isinstance(conf, cfg.ConfigOpts):
            raise ValueError("This middleware requires a configuration of"
                             " type oslo_config.ConfigOpts.")
        conf.register_opts(CORS_OPTS, 'cors')

        # Clone our original CORS_OPTS, and set the defaults to whatever is
        # set in the global conf instance. This is done explicitly (instead
        # of **kwargs), since we don't accidentally want to catch
        # allowed_origin.
        subgroup_opts = copy.deepcopy(CORS_OPTS)
        cfg.set_defaults(subgroup_opts,
                         allow_credentials=conf.cors.allow_credentials,
                         expose_headers=conf.cors.expose_headers,
                         max_age=conf.cors.max_age,
                         allow_methods=conf.cors.allow_methods,
                         allow_headers=conf.cors.allow_headers)

        # Begin constructing our configuration hash.
        self.allowed_origins = {}

        # If the default configuration contains an allowed_origin, don't
        # forget to register that.
        if conf.cors.allowed_origin:
            self.allowed_origins[conf.cors.allowed_origin] = conf.cors

        # Iterate through all the loaded config sections, looking for ones
        # prefixed with 'cors.'
        for section in conf.list_all_sections():
            if section.startswith('cors.'):
                # Register with the preconstructed defaults
                conf.register_opts(subgroup_opts, section)

                # Make sure that allowed_origin is available. Otherwise skip.
                allowed_origin = conf[section].allowed_origin
                if not allowed_origin:
                    LOG.warn('Config section [%s] does not contain'
                             ' \'allowed_origin\', skipping.' % (section,))
                    continue

                self.allowed_origins[allowed_origin] = conf[section]

    @webob.dec.wsgify
    def __call__(self, req):
        # If it's an OPTIONS request, handle it immediately. Otherwise,
        # pass it through to the application.
        if req.method == 'OPTIONS':
            resp = webob.response.Response(status=webob.exc.HTTPOk.code)
            self._apply_cors_preflight_headers(request=req, response=resp)
        else:
            resp = req.get_response(self.application)
            self._apply_cors_request_headers(request=req, response=resp)

        # Finally, return the response.
        return resp

    def _split_header_values(self, request, header_name):
        """Convert a comma-separated header value into a list of values."""
        values = []
        if header_name in request.headers:
            for value in request.headers[header_name].rsplit(','):
                value = value.strip()
                if value:
                    values.append(value)
        return values

    def _apply_cors_preflight_headers(self, request, response):
        """Handle CORS Preflight (Section 6.2)

        Given a request and a response, apply the CORS preflight headers
        appropriate for the request.
        """

        # Does the request have an origin header? (Section 6.2.1)
        if 'Origin' not in request.headers:
            return

        # Is this origin registered? (Section 6.2.2)
        origin = request.headers['Origin']
        if origin not in self.allowed_origins:
            if '*' in self.allowed_origins:
                origin = '*'
            else:
                LOG.debug('CORS request from origin \'%s\' not permitted.'
                          % (origin,))
                return
        cors_config = self.allowed_origins[origin]

        # If there's no request method, exit. (Section 6.2.3)
        if 'Access-Control-Request-Method' not in request.headers:
            return
        request_method = request.headers['Access-Control-Request-Method']

        # Extract Request headers. If parsing fails, exit. (Section 6.2.4)
        try:
            request_headers = \
                self._split_header_values(request,
                                          'Access-Control-Request-Headers')
        except Exception:
            LOG.debug('Cannot parse request headers.')
            return

        # Compare request method to permitted methods (Section 6.2.5)
        if request_method not in cors_config.allow_methods:
            return

        # Compare request headers to permitted headers, case-insensitively.
        # (Section 6.2.6)
        for requested_header in request_headers:
            upper_header = requested_header.upper()
            permitted_headers = cors_config.allow_headers + self.simple_headers
            if upper_header not in (header.upper() for header in
                                    permitted_headers):
                return

        # Set the default origin permission headers. (Sections 6.2.7, 6.4)
        response.headers['Vary'] = 'Origin'
        response.headers['Access-Control-Allow-Origin'] = origin

        # Does this CORS configuration permit credentials? (Section 6.2.7)
        if cors_config.allow_credentials:
            response.headers['Access-Control-Allow-Credentials'] = 'true'

        # Attach Access-Control-Max-Age if appropriate. (Section 6.2.8)
        if 'max_age' in cors_config and cors_config.max_age:
            response.headers['Access-Control-Max-Age'] = \
                str(cors_config.max_age)

        # Attach Access-Control-Allow-Methods. (Section 6.2.9)
        response.headers['Access-Control-Allow-Methods'] = request_method

        # Attach  Access-Control-Allow-Headers. (Section 6.2.10)
        if request_headers:
            response.headers['Access-Control-Allow-Headers'] = \
                ','.join(request_headers)

    def _apply_cors_request_headers(self, request, response):
        """Handle Basic CORS Request (Section 6.1)

        Given a request and a response, apply the CORS headers appropriate
        for the request to the response.
        """

        # Does the request have an origin header? (Section 6.1.1)
        if 'Origin' not in request.headers:
            return

        # Is this origin registered? (Section 6.1.2)
        origin = request.headers['Origin']
        if origin not in self.allowed_origins:
            LOG.debug('CORS request from origin \'%s\' not permitted.'
                      % (origin,))
            return
        cors_config = self.allowed_origins[origin]

        # Set the default origin permission headers. (Sections 6.1.3 & 6.4)
        response.headers['Vary'] = 'Origin'
        response.headers['Access-Control-Allow-Origin'] = origin

        # Does this CORS configuration permit credentials? (Section 6.1.3)
        if cors_config.allow_credentials:
            response.headers['Access-Control-Allow-Credentials'] = 'true'

        # Attach the exposed headers and exit. (Section 6.1.4)
        if cors_config.expose_headers:
            response.headers['Access-Control-Expose-Headers'] = \
                ','.join(cors_config.expose_headers)
