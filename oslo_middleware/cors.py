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

from __future__ import annotations

import copy
import logging
import typing as ty

import debtcollector
from oslo_config import cfg
from oslo_middleware import base
import webob.exc

if ty.TYPE_CHECKING:
    from _typeshed.wsgi import WSGIApplication
    import webob.request
    import webob.response


class AllowedOrigin(ty.TypedDict):
    allow_credentials: bool
    expose_headers: list[str]
    max_age: int | None
    allow_methods: list[str]
    allow_headers: list[str]


LOG = logging.getLogger(__name__)

OPTS = [
    cfg.ListOpt(
        'allowed_origin',
        help='Indicate whether this resource may be shared with the '
        'domain received in the requests "origin" header. '
        'Format: "<protocol>://<host>[:<port>]", no trailing '
        'slash. Example: https://horizon.example.com',
    ),
    cfg.BoolOpt(
        'allow_credentials',
        default=True,
        help='Indicate that the actual request can include user credentials',
    ),
    cfg.ListOpt(
        'expose_headers',
        default=[],
        help='Indicate which headers are safe to expose to the API. '
        'Defaults to HTTP Simple Headers.',
    ),
    cfg.IntOpt(
        'max_age',
        default=3600,
        help='Maximum cache age of CORS preflight requests.',
    ),
    cfg.ListOpt(
        'allow_methods',
        default=[
            'OPTIONS',
            'GET',
            'HEAD',
            'POST',
            'PUT',
            'DELETE',
            'TRACE',
            'PATCH',
        ],  # RFC 2616, RFC 5789
        help='Indicate which methods can be used during the actual request.',
    ),
    cfg.ListOpt(
        'allow_headers',
        default=[],
        help='Indicate which header field names may be used during '
        'the actual request.',
    ),
]

# legacy alias, since many projects reference this directly
CORS_OPTS = OPTS


def set_defaults(**kwargs: cfg.Opt) -> None:
    """Override the default values for configuration options.

    This method permits a project to override the default CORS option values.
    For example, it may wish to offer a set of sane default headers which
    allow it to function with only minimal additional configuration.

    :param allow_credentials: Whether to permit credentials.
    :type allow_credentials: bool
    :param expose_headers: A list of headers to expose.
    :type expose_headers: List of Strings
    :param max_age: Maximum cache duration in seconds.
    :type max_age: Int
    :param allow_methods: List of HTTP methods to permit.
    :type allow_methods: List of Strings
    :param allow_headers: List of HTTP headers to permit from the client.
    :type allow_headers: List of Strings
    """
    # Since 'None' is a valid config override, we have to use kwargs. Else
    # there's no good way for a user to override only one option, because all
    # the others would be overridden to 'None'.

    valid_params = {k.name for k in OPTS if k.name != 'allowed_origin'}
    passed_params = {k for k in kwargs}

    wrong_params = passed_params - valid_params
    if wrong_params:
        raise AttributeError(
            f'Parameter(s) [{wrong_params}] invalid, please only use '
            f'[{valid_params}]'
        )

    # Set global defaults.
    cfg.set_defaults(OPTS, **kwargs)


class InvalidOriginError(Exception):
    """Exception raised when Origin is invalid."""

    def __init__(self, origin: str):
        self.origin = origin
        super().__init__(f"CORS request from origin '{origin}' not permitted.")


class CORS(base.ConfigurableMiddleware):
    """CORS Middleware.

    This middleware allows a WSGI app to serve CORS headers for multiple
    configured domains.

    For more information, see http://www.w3.org/TR/cors/
    """

    simple_headers = [
        'Accept',
        'Accept-Language',
        'Content-Type',
        'Cache-Control',
        'Content-Language',
        'Expires',
        'Last-Modified',
        'Pragma',
    ]

    def __init__(
        self,
        application: WSGIApplication | None,
        conf: dict[str, ty.Any] | cfg.ConfigOpts | None = None,
    ) -> None:
        super().__init__(application, conf)
        # Begin constructing our configuration hash.
        self.allowed_origins: dict[str, AllowedOrigin] = {}
        self._init_conf()

    @classmethod
    def factory(
        cls: type[base.MiddlewareType],
        global_conf: dict[str, ty.Any] | None,
        **local_conf: ty.Any,
    ) -> ty.Callable[[WSGIApplication], base.MiddlewareType]:
        """factory method for paste.deploy

        allowed_origin: Protocol, host, and port for the allowed origin.
        allow_credentials: Whether to permit credentials.
        expose_headers: A list of headers to expose.
        max_age: Maximum cache duration.
        allow_methods: List of HTTP methods to permit.
        allow_headers: List of HTTP headers to permit from the client.
        """
        if (
            'allowed_origin' not in local_conf
            and 'oslo_config_project' not in local_conf
        ):
            raise TypeError(
                "allowed_origin or oslo_config_project is required"
            )
        return super().factory(global_conf, **local_conf)

    def _init_conf(self) -> None:
        """Initialize this middleware from an oslo.config instance."""

        # First, check the configuration and register global options.
        self.oslo_conf.register_opts(OPTS, 'cors')

        allowed_origin = self._conf_get('allowed_origin', 'cors')
        allow_credentials = self._conf_get('allow_credentials', 'cors')
        expose_headers = self._conf_get('expose_headers', 'cors')
        max_age = self._conf_get('max_age', 'cors')
        allow_methods = self._conf_get('allow_methods', 'cors')
        allow_headers = self._conf_get('allow_headers', 'cors')

        # Clone our original OPTS, and set the defaults to whatever is
        # set in the global conf instance. This is done explicitly (instead
        # of **kwargs), since we don't accidentally want to catch
        # allowed_origin.
        subgroup_opts = copy.deepcopy(OPTS)
        cfg.set_defaults(
            subgroup_opts,
            allow_credentials=allow_credentials,
            expose_headers=expose_headers,
            max_age=max_age,
            allow_methods=allow_methods,
            allow_headers=allow_headers,
        )

        # If the default configuration contains an allowed_origin, don't
        # forget to register that.
        self.add_origin(
            allowed_origin=allowed_origin,
            allow_credentials=allow_credentials,
            expose_headers=expose_headers,
            max_age=max_age,
            allow_methods=allow_methods,
            allow_headers=allow_headers,
        )

        # Iterate through all the loaded config sections, looking for ones
        # prefixed with 'cors.'
        for section in self.oslo_conf.list_all_sections():
            if section.startswith('cors.'):
                debtcollector.deprecate(
                    'Multiple configuration blocks are '
                    'deprecated and will be removed in '
                    'future versions. Please consolidate '
                    'your configuration in the [cors] '
                    'configuration block.'
                )
                # Register with the preconstructed defaults
                self.oslo_conf.register_opts(subgroup_opts, section)
                self.add_origin(**self.oslo_conf[section])

    def add_origin(
        self,
        allowed_origin: str | list[str],
        allow_credentials: bool = True,
        expose_headers: list[str] | None = None,
        max_age: int | None = None,
        allow_methods: list[str] | None = None,
        allow_headers: list[str] | None = None,
    ) -> None:
        """Add another origin to this filter.

        :param allowed_origin: Protocol, host, and port for the allowed origin.
        :param allow_credentials: Whether to permit credentials.
        :param expose_headers: A list of headers to expose.
        :param max_age: Maximum cache duration.
        :param allow_methods: List of HTTP methods to permit.
        :param allow_headers: List of HTTP headers to permit from the client.
        :return:
        """

        # NOTE(dims): Support older code that still passes in
        # a string for allowed_origin instead of a list
        if isinstance(allowed_origin, str):
            # TODO(krotscheck): https://review.opendev.org/#/c/312687/
            LOG.warning(
                'DEPRECATED: The `allowed_origin` keyword argument in '
                '`add_origin()` should be a list, found String.'
            )
            allowed_origin = [allowed_origin]

        if allowed_origin:
            for origin in allowed_origin:
                if origin in self.allowed_origins:
                    LOG.warning(
                        'Allowed origin [%s] already exists, skipping',
                        allowed_origin,
                    )
                    continue

                self.allowed_origins[origin] = {
                    'allow_credentials': allow_credentials,
                    'expose_headers': expose_headers or [],
                    'max_age': max_age,
                    'allow_methods': allow_methods or [],
                    'allow_headers': allow_headers or [],
                }

    def process_response(
        self,
        response: webob.response.Response,
        request: webob.request.Request | None = None,
    ) -> webob.response.Response:
        """Check for CORS headers, and decorate if necessary.

        Perform two checks. First, if an OPTIONS request was issued, let the
        application handle it, and (if necessary) decorate the response with
        preflight headers. In this case, if a 404 is thrown by the underlying
        application (i.e. if the underlying application does not handle
        OPTIONS requests, the response code is overridden.

        In the case of all other requests, regular request headers are applied.
        """

        # Sanity precheck: If we detect CORS headers provided by something in
        # in the middleware chain, assume that it knows better.
        if 'Access-Control-Allow-Origin' in response.headers:
            return response

        # We need the request object
        if not request:
            return response

        # Doublecheck for an OPTIONS request.
        # TODO(stephenfin): typeshed typing is incomplete and doesn't include
        # OPTIONS
        if request.method == 'OPTIONS':  # type: ignore
            return self._apply_cors_preflight_headers(
                request=request, response=response
            )

        # Apply regular CORS headers.
        self._apply_cors_request_headers(request=request, response=response)

        # Finally, return the response.
        return response

    @staticmethod
    def _split_header_values(
        request: webob.request.Request,
        header_name: str,
    ) -> list[str]:
        """Convert a comma-separated header value into a list of values."""
        values = []
        if header_name in request.headers:
            for value in request.headers[header_name].rsplit(','):
                value = value.strip()
                if value:
                    values.append(value)
        return values

    def _apply_cors_preflight_headers(
        self,
        request: webob.request.Request,
        response: webob.response.Response,
    ) -> webob.response.Response:
        """Handle CORS Preflight (Section 6.2)

        Given a request and a response, apply the CORS preflight headers
        appropriate for the request.
        """

        # If the response contains a 2XX code, we have to assume that the
        # underlying middleware's response content needs to be persisted.
        # Otherwise, create a new response.
        if 200 > response.status_code or response.status_code >= 300:
            response = base.NoContentTypeResponse(
                status=str(webob.exc.HTTPOk.code)
            )

        # Does the request have an origin header? (Section 6.2.1)
        if 'Origin' not in request.headers:
            return response

        # Is this origin registered? (Section 6.2.2)
        try:
            origin, cors_config = self._get_cors_config_by_origin(
                request.headers['Origin']
            )
        except InvalidOriginError:
            return response

        # If there's no request method, exit. (Section 6.2.3)
        if 'Access-Control-Request-Method' not in request.headers:
            LOG.debug(
                'CORS request does not contain '
                'Access-Control-Request-Method header.'
            )
            return response
        request_method = request.headers['Access-Control-Request-Method']

        # Extract Request headers. If parsing fails, exit. (Section 6.2.4)
        try:
            request_headers = self._split_header_values(
                request, 'Access-Control-Request-Headers'
            )
        except Exception:
            LOG.debug('Cannot parse request headers.')
            return response

        # Compare request method to permitted methods (Section 6.2.5)
        permitted_methods = cors_config['allow_methods']
        if request_method not in permitted_methods:
            LOG.debug(
                'Request method \'%s\' not in permitted list: %s',
                request_method,
                permitted_methods,
            )
            return response

        # Compare request headers to permitted headers, case-insensitively.
        # (Section 6.2.6)
        permitted_headers = [
            header.upper()
            for header in (cors_config['allow_headers'] + self.simple_headers)
        ]
        for requested_header in request_headers:
            upper_header = requested_header.upper()
            if upper_header not in permitted_headers:
                LOG.debug(
                    'Request header \'%s\' not in permitted list: %s',
                    requested_header,
                    permitted_headers,
                )
                return response

        # Set the default origin permission headers. (Sections 6.2.7, 6.4)
        response.headers['Vary'] = 'Origin'
        response.headers['Access-Control-Allow-Origin'] = origin

        # Does this CORS configuration permit credentials? (Section 6.2.7)
        if cors_config['allow_credentials']:
            response.headers['Access-Control-Allow-Credentials'] = 'true'

        # Attach Access-Control-Max-Age if appropriate. (Section 6.2.8)
        if 'max_age' in cors_config and cors_config['max_age']:
            response.headers['Access-Control-Max-Age'] = str(
                cors_config['max_age']
            )

        # Attach Access-Control-Allow-Methods. (Section 6.2.9)
        response.headers['Access-Control-Allow-Methods'] = request_method

        # Attach  Access-Control-Allow-Headers. (Section 6.2.10)
        if request_headers:
            response.headers['Access-Control-Allow-Headers'] = ','.join(
                request_headers
            )

        return response

    def _get_cors_config_by_origin(
        self,
        origin: str,
    ) -> tuple[str, AllowedOrigin]:
        if origin not in self.allowed_origins:
            if '*' in self.allowed_origins:
                origin = '*'
            else:
                LOG.debug(
                    'CORS request from origin \'%s\' not permitted.', origin
                )
                raise InvalidOriginError(origin)
        return origin, self.allowed_origins[origin]

    def _apply_cors_request_headers(
        self,
        request: webob.request.Request,
        response: webob.response.Response,
    ) -> None:
        """Handle Basic CORS Request (Section 6.1)

        Given a request and a response, apply the CORS headers appropriate
        for the request to the response.
        """

        # Does the request have an origin header? (Section 6.1.1)
        if 'Origin' not in request.headers:
            return

        # Is this origin registered? (Section 6.1.2)
        try:
            origin, cors_config = self._get_cors_config_by_origin(
                request.headers['Origin']
            )
        except InvalidOriginError:
            return

        # Set the default origin permission headers. (Sections 6.1.3 & 6.4)
        if 'Vary' in response.headers:
            response.headers['Vary'] += ',Origin'
        else:
            response.headers['Vary'] = 'Origin'
        response.headers['Access-Control-Allow-Origin'] = origin

        # Does this CORS configuration permit credentials? (Section 6.1.3)
        if cors_config['allow_credentials']:
            response.headers['Access-Control-Allow-Credentials'] = 'true'

        # Attach the exposed headers and exit. (Section 6.1.4)
        if cors_config['expose_headers']:
            response.headers['Access-Control-Expose-Headers'] = ','.join(
                cors_config['expose_headers']
            )


# NOTE(sileht): Shortcut for backwards compatibility
filter_factory = CORS.factory
