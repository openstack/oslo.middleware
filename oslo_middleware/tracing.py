# Copyright 2024 OpenStack Foundation
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

"""OpenTelemetry WSGI tracing middleware.

Provides distributed tracing for OpenStack services using OpenTelemetry.
The middleware creates a span for each incoming HTTP request, propagates
W3C TraceContext headers across services, and exports traces via OTLP
to any compatible backend (Grafana Tempo, Jaeger, etc.).

Tracing is disabled by default. When disabled, the middleware is a
zero-overhead passthrough. When enabled, the OpenTelemetry packages
must be installed or the middleware will raise an error at startup.

The ``[oslo_middleware_tracing] enabled`` config flag is the primary
mechanism to control tracing, allowing services that do not use paste
(e.g. Keystone with Flask) to toggle tracing via configuration
without modifying code.

Required packages can be installed via the ``tracing-http`` extra::

    pip install oslo.middleware[tracing-http]

Configuration example::

    [oslo_middleware_tracing]
    enabled = true
    otlp_endpoint = http://tempo:4318
    service_name = glance-api
"""

from __future__ import annotations

import atexit
import logging
import typing as ty

from oslo_config import cfg

from oslo_middleware._i18n import _
from oslo_middleware import base

if ty.TYPE_CHECKING:
    from _typeshed.wsgi import WSGIApplication
    import webob.request
    import webob.response

LOG = logging.getLogger(__name__)

# OpenTelemetry imports — optional, None if not installed.
# The middleware checks these at startup and raises RuntimeError
# if tracing is enabled but packages are missing.
try:
    from opentelemetry.baggage import propagation as otel_baggage_propagation
    from opentelemetry.propagators import composite as otel_composite
    from opentelemetry.sdk import resources as otel_resources
    from opentelemetry.sdk import trace as otel_sdk_trace
    from opentelemetry.sdk.trace import export as otel_export
    from opentelemetry.sdk.trace import sampling as otel_sampling
    from opentelemetry.trace.propagation import (
        tracecontext as otel_tracecontext,
    )
    from opentelemetry import context as otel_context
    from opentelemetry import propagate as otel_propagate
    from opentelemetry import trace as otel_trace

    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False

TRACING_OPTS = [
    cfg.BoolOpt(
        'enabled',
        default=False,
        help=_(
            'Enable OpenTelemetry distributed tracing. '
            'When enabled, the service will export trace data via OTLP '
            'to a configured backend. This is the primary mechanism to '
            'control tracing for services that do not use paste deploy.'
        ),
    ),
    cfg.URIOpt(
        'otlp_endpoint',
        default='http://localhost:4318',
        schemes=['http', 'https'],
        help=_(
            'OTLP exporter endpoint URL. For HTTP/protobuf protocol, '
            'traces are sent to <endpoint>/v1/traces.'
        ),
    ),
    cfg.StrOpt(
        'otlp_protocol',
        default='http/protobuf',
        choices=[
            ('http/protobuf', 'OTLP over HTTP with Protocol Buffers'),
            ('grpc', 'OTLP over gRPC'),
        ],
        help=_('OTLP transport protocol.'),
    ),
    cfg.StrOpt(
        'service_name',
        required=True,
        help=_(
            'OpenTelemetry service name reported in trace data. '
            'This must be set when tracing is enabled, either via '
            'set_defaults() or in the configuration file.'
        ),
    ),
    cfg.FloatOpt(
        'sampling_rate',
        default=1.0,
        min=0.0,
        max=1.0,
        help=_(
            'Trace sampling rate as a float between 0.0 and 1.0. '
            'A value of 1.0 means all traces are sampled.'
        ),
    ),
    cfg.BoolOpt(
        'insecure',
        default=False,
        help=_(
            'Disable TLS verification for the OTLP endpoint. '
            'Set to True only in development environments without '
            'proper TLS certificates.'
        ),
    ),
]

_TRACER_PROVIDER = None
_INITIALIZED = False


def set_defaults(**kwargs: ty.Any) -> None:
    """Override default values for tracing configuration options.

    This is intended to be called by services during their configuration
    setup, following the same pattern as
    :func:`oslo_middleware.cors.set_defaults`.

    Example::

        from oslo_middleware import tracing

        tracing.set_defaults(service_name='glance-api')
    """
    cfg.set_defaults(TRACING_OPTS, **kwargs)


def init_tracing(conf: cfg.ConfigOpts | None = None) -> None:
    """Initialize the OpenTelemetry TracerProvider.

    Sets up the TracerProvider, OTLP exporter, span processor, and W3C
    propagators. This function is idempotent — calling it multiple times
    has no additional effect.

    The middleware calls this automatically in ``__init__``. Services
    that need early initialization (before paste pipeline loading) can
    call it explicitly.

    :param conf: oslo.config ConfigOpts object. Defaults to cfg.CONF.
    """
    global _TRACER_PROVIDER, _INITIALIZED

    if _INITIALIZED:
        return

    if conf is None:
        conf = cfg.CONF

    _register_opts(conf)

    if not conf.oslo_middleware_tracing.enabled:
        LOG.debug('OpenTelemetry tracing is disabled')
        _INITIALIZED = True
        return

    if not _OTEL_AVAILABLE:
        raise RuntimeError(
            'OpenTelemetry tracing is enabled but the required packages '
            'are not installed. Install them with: '
            'pip install oslo.middleware[tracing-http] or '
            'pip install oslo.middleware[tracing-grpc]'
        )

    exporter = _create_exporter(conf)

    resource = otel_resources.Resource.create(
        {
            'service.name': conf.oslo_middleware_tracing.service_name,
        }
    )

    sampler = otel_sampling.TraceIdRatioBased(
        conf.oslo_middleware_tracing.sampling_rate
    )

    _TRACER_PROVIDER = otel_sdk_trace.TracerProvider(
        resource=resource,
        sampler=sampler,
    )
    _TRACER_PROVIDER.add_span_processor(
        otel_export.BatchSpanProcessor(exporter)
    )
    otel_trace.set_tracer_provider(_TRACER_PROVIDER)

    # Set W3C TraceContext + Baggage propagators
    otel_propagate.set_global_textmap(
        otel_composite.CompositePropagator(
            [
                otel_tracecontext.TraceContextTextMapPropagator(),
                otel_baggage_propagation.W3CBaggagePropagator(),
            ]
        )
    )

    atexit.register(shutdown_tracing)
    _INITIALIZED = True

    LOG.info(
        'OpenTelemetry tracing initialized: endpoint=%s, '
        'service=%s, sampling_rate=%s',
        conf.oslo_middleware_tracing.otlp_endpoint,
        conf.oslo_middleware_tracing.service_name,
        conf.oslo_middleware_tracing.sampling_rate,
    )


def shutdown_tracing() -> None:
    """Shut down the TracerProvider, flushing any pending spans."""
    global _TRACER_PROVIDER, _INITIALIZED
    if _TRACER_PROVIDER is not None:
        _TRACER_PROVIDER.shutdown()
        _TRACER_PROVIDER = None
        _INITIALIZED = False
        LOG.info('OpenTelemetry tracing shut down')


def _register_opts(conf: cfg.ConfigOpts) -> None:
    """Register tracing config options."""
    conf.register_group(
        cfg.OptGroup('oslo_middleware_tracing', title='OpenTelemetry Tracing')
    )
    conf.register_opts(TRACING_OPTS, group='oslo_middleware_tracing')


def _create_exporter(conf: cfg.ConfigOpts) -> ty.Any:
    """Create the OTLP span exporter based on configuration.

    The protocol-specific exporter package is imported here rather
    than at module level so that ``tracing-http`` and ``tracing-grpc``
    extras are fully independent — operators install only the one
    they need.
    """
    protocol = conf.oslo_middleware_tracing.otlp_protocol
    endpoint = conf.oslo_middleware_tracing.otlp_endpoint
    insecure = conf.oslo_middleware_tracing.insecure

    if protocol == 'http/protobuf':
        try:
            from opentelemetry.exporter.otlp.proto.http import (
                trace_exporter as http_exporter,
            )
        except ImportError:
            raise RuntimeError(
                'OTLP HTTP exporter is not installed. Install it with: '
                'pip install oslo.middleware[tracing-http]'
            )

        return http_exporter.OTLPSpanExporter(
            endpoint=endpoint + '/v1/traces',
        )
    else:
        try:
            from opentelemetry.exporter.otlp.proto.grpc import (
                trace_exporter as grpc_exporter,
            )
        except ImportError:
            raise RuntimeError(
                'OTLP gRPC exporter is not installed. Install it with: '
                'pip install oslo.middleware[tracing-grpc]'
            )

        return grpc_exporter.OTLPSpanExporter(
            endpoint=endpoint,
            insecure=insecure,
        )


class TracingMiddleware(base.ConfigurableMiddleware):
    """WSGI middleware for OpenTelemetry distributed tracing.

    Creates a span for each incoming HTTP request with W3C TraceContext
    propagation.

    Usage in ``api-paste.ini``::

        [filter:tracing]
        paste.filter_factory = oslo_middleware:TracingMiddleware.factory
        oslo_config_project = glance
        oslo_config_program = glance-api

    Or via entry point::

        [filter:tracing]
        paste.filter_factory = oslo_middleware#tracing
    """

    def __init__(
        self,
        application: WSGIApplication | None,
        conf: dict[str, ty.Any] | cfg.ConfigOpts | None = None,
    ) -> None:
        super().__init__(application, conf)
        self._tracing_enabled = False
        self._tracer: ty.Any = None
        self._propagator: ty.Any = None

        _register_opts(self.oslo_conf)

        if not self.oslo_conf.oslo_middleware_tracing.enabled:
            return

        init_tracing(self.oslo_conf)

        self._tracer = otel_trace.get_tracer('oslo_middleware.tracing')
        self._propagator = otel_propagate.get_global_textmap()
        self._tracing_enabled = True

    def process_request(
        self,
        req: webob.request.Request,
    ) -> webob.response.Response | None:
        if not self._tracing_enabled:
            return None

        # Extract trace context from incoming request headers
        carrier: dict[str, str] = {}
        for key in ('traceparent', 'tracestate'):
            value = req.headers.get(key)
            if value:
                carrier[key] = value

        ctx = self._propagator.extract(carrier=carrier)

        # Start a new span
        method = req.method
        path = req.path_info or '/'
        span = self._tracer.start_span(
            f'HTTP {method} {path}',
            context=ctx,
            kind=otel_trace.SpanKind.SERVER,
        )

        # Set HTTP span attributes
        span.set_attribute('http.method', method)
        span.set_attribute('http.url', req.url)
        span.set_attribute('http.route', path)
        user_agent = req.user_agent
        if user_agent:
            span.set_attribute('http.user_agent', user_agent)

        # OpenStack-specific attributes from oslo.context.
        # The request context is populated by the auth middleware which
        # must run before this middleware in the pipeline.
        ctx_obj = req.environ.get('oslo.context')
        if ctx_obj is not None:
            if getattr(ctx_obj, 'global_request_id', None):
                span.set_attribute(
                    'openstack.global_request_id',
                    ctx_obj.global_request_id,
                )
            if getattr(ctx_obj, 'request_id', None):
                span.set_attribute('openstack.request_id', ctx_obj.request_id)
            if getattr(ctx_obj, 'project_id', None):
                span.set_attribute('openstack.project_id', ctx_obj.project_id)
            if getattr(ctx_obj, 'user_id', None):
                span.set_attribute('openstack.user_id', ctx_obj.user_id)
            if getattr(ctx_obj, 'domain_id', None):
                span.set_attribute('openstack.domain_id', ctx_obj.domain_id)

        # Attach span to context
        new_ctx = otel_trace.set_span_in_context(span, ctx)
        token = otel_context.attach(new_ctx)

        req.environ['otel.span'] = span
        req.environ['otel.token'] = token

        return None

    def process_response(
        self,
        response: webob.response.Response,
        request: webob.request.Request | None = None,
    ) -> webob.response.Response:
        if not self._tracing_enabled:
            return response

        # Get the request from the parameter or from response.request
        req = request or getattr(response, 'request', None)
        if req is None:
            return response

        span = req.environ.get('otel.span')
        token = req.environ.get('otel.token')

        if span is None:
            return response

        try:
            status_code = response.status_int
            span.set_attribute('http.status_code', status_code)

            if status_code >= 500:
                span.set_status(
                    otel_trace.StatusCode.ERROR, f'HTTP {status_code}'
                )

            # Inject trace context into response headers
            response_carrier: dict[str, str] = {}
            self._propagator.inject(carrier=response_carrier)
            for key, value in response_carrier.items():
                response.headers[key] = value
        finally:
            span.end()
            if token is not None:
                otel_context.detach(token)

        return response
