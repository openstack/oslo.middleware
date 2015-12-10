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

import sys
import warnings

def deprecated():
    new_name = __name__.replace('.', '_')
    warnings.warn(
        ('The oslo namespace package is deprecated. Please use %s instead.' %
         new_name),
        DeprecationWarning,
        stacklevel=3,
    )


# NOTE(dims): We cannot remove the deprecation or redirects below
# until Liberty-EOL
deprecated()

from oslo_middleware import base
from oslo_middleware import catch_errors
from oslo_middleware import correlation_id
from oslo_middleware import debug
from oslo_middleware import request_id
from oslo_middleware import sizelimit

sys.modules['oslo.middleware.base'] = base
sys.modules['oslo.middleware.catch_errors'] = catch_errors
sys.modules['oslo.middleware.correlation_id'] = correlation_id
sys.modules['oslo.middleware.debug'] = debug
sys.modules['oslo.middleware.request_id'] = request_id
sys.modules['oslo.middleware.sizelimit'] = sizelimit