# Copyright (c) 2012 Red Hat, Inc.
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

"""
Request Body limiting middleware.
"""

from __future__ import annotations

import logging
import typing as ty

from oslo_config import cfg
import webob.dec
import webob.exc

from oslo_middleware._i18n import _
from oslo_middleware import base

if ty.TYPE_CHECKING:
    from _typeshed.wsgi import WSGIApplication

LOG = logging.getLogger(__name__)

OPTS = [
    # default request size is 112k
    cfg.IntOpt(
        'max_request_body_size',
        default=114688,
        help='The maximum body size for each request, in bytes.',
    ),
]


class LimitingReader:
    """Reader to limit the size of an incoming request."""

    def __init__(self, data: ty.IO[bytes], limit: int) -> None:
        """Initiates LimitingReader object.

        :param data: Underlying data object
        :param limit: maximum number of bytes the reader should allow
        """
        self.data = data
        self.limit = limit
        self.bytes_read = 0

    def __iter__(self) -> ty.Iterator[bytes]:
        for chunk in self.data:
            self.bytes_read += len(chunk)
            if self.bytes_read > self.limit:
                msg = _("Request is too large. Larger than %s") % self.limit
                raise webob.exc.HTTPRequestEntityTooLarge(explanation=msg)
            else:
                yield chunk

    def read(self, i: int | None = None) -> bytes:
        # NOTE(jamielennox): We can't simply provide the default to the read()
        # call as the expected default differs between mod_wsgi and eventlet
        if i is None:
            result = self.data.read()
        else:
            result = self.data.read(i)
        self.bytes_read += len(result)
        if self.bytes_read > self.limit:
            msg = _("Request is too large. Larger than %s.") % self.limit
            raise webob.exc.HTTPRequestEntityTooLarge(explanation=msg)
        return result


class RequestBodySizeLimiter(base.ConfigurableMiddleware):
    """Limit the size of incoming requests."""

    def __init__(
        self,
        application: WSGIApplication | None,
        conf: dict[str, ty.Any] | cfg.ConfigOpts | None = None,
    ) -> None:
        super().__init__(application, conf)
        self.oslo_conf.register_opts(OPTS, group='oslo_middleware')

    @webob.dec.wsgify
    def __call__(
        self,
        req: webob.request.Request,
    ) -> webob.response.Response | None:
        max_size = self._conf_get('max_request_body_size')
        if req.content_length is not None and req.content_length > max_size:
            msg = _(
                "Request is too large. Larger than max_request_body_size (%s)."
            )
            LOG.info(msg, max_size)
            raise webob.exc.HTTPRequestEntityTooLarge(explanation=msg)

        if req.content_length is None:
            # the type stub for this is incomplete: body_file is not just
            # readable - it's also iterable
            limiter = LimitingReader(req.body_file, max_size)  # type: ignore
            req.body_file = limiter

        return req.get_response(self.application)
