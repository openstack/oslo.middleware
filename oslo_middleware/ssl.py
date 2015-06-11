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

from oslo.config import cfg
from oslo_middleware import base


OPTS = [
    cfg.StrOpt('secure_proxy_ssl_header',
               default='X-Forwarded-Proto',
               help="The HTTP Header that will be used to determine what "
                    "the original request protocol scheme was, even if it was "
                    "hidden by an SSL termination proxy.")
]
cfg.CONF.register_opts(OPTS, group='oslo_middleware')


class SSLMiddleware(base.Middleware):
    """SSL termination proxies middleware.

    This middleware overloads wsgi.url_scheme with the one provided in
    secure_proxy_ssl_header header. This is useful when behind a SSL
    termination proxy.
    """

    def __init__(self, application):
        super(SSLMiddleware, self).__init__(application)
        self.header_name = 'HTTP_{0}'.format(
            cfg.CONF.oslo_middleware.secure_proxy_ssl_header.upper()
            .replace('-', '_'))

    def process_request(self, req):
        req.environ['wsgi.url_scheme'] = req.environ.get(
            self.header_name, req.environ['wsgi.url_scheme'])
