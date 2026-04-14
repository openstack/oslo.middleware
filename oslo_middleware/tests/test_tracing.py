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

from unittest import mock

from oslo_config import cfg
from oslotest import base as test_base
import webob

from oslo_middleware import tracing


class TestTracingConfig(test_base.BaseTestCase):
    def test_default_config_values(self):
        defaults = {o.name: o.default for o in tracing.TRACING_OPTS}
        self.assertFalse(defaults['enabled'])
        self.assertEqual('http://localhost:4318', defaults['otlp_endpoint'])
        self.assertEqual('http/protobuf', defaults['otlp_protocol'])
        self.assertEqual(1.0, defaults['sampling_rate'])
        self.assertFalse(defaults['insecure'])

    def test_service_name_required(self):
        sn_opt = [o for o in tracing.TRACING_OPTS if o.name == 'service_name']
        self.assertEqual(1, len(sn_opt))
        self.assertTrue(sn_opt[0].required)

    def test_set_defaults(self):
        tracing.set_defaults(service_name='nova-api')
        sn_opt = [o for o in tracing.TRACING_OPTS if o.name == 'service_name']
        self.assertEqual('nova-api', sn_opt[0].default)
        # Reset to avoid contaminating other tests in the same worker.
        sn_opt[0].default = None


class TestTracingMiddlewareDisabled(test_base.BaseTestCase):
    def setUp(self):
        super().setUp()
        tracing._INITIALIZED = False
        tracing._TRACER_PROVIDER = None
        tracing._register_opts(cfg.CONF)
        cfg.CONF.set_override(
            'enabled', False, group='oslo_middleware_tracing'
        )

        @webob.dec.wsgify
        def fake_app(req):
            return 'Hello'

        self.app = fake_app

    def test_disabled_passthrough(self):
        middleware = tracing.TracingMiddleware(self.app)
        req = webob.Request.blank('/test')
        resp = req.get_response(middleware)
        self.assertEqual(200, resp.status_int)
        self.assertEqual(b'Hello', resp.body)
        self.assertFalse(middleware._tracing_enabled)

    def test_disabled_no_otel_environ(self):
        middleware = tracing.TracingMiddleware(self.app)
        req = webob.Request.blank('/test')
        resp = req.get_response(middleware)
        self.assertEqual(200, resp.status_int)
        self.assertNotIn('otel.span', req.environ)


class TestTracingMiddleware(test_base.BaseTestCase):
    """Unit tests using mocked OpenTelemetry objects."""

    def setUp(self):
        super().setUp()
        tracing._INITIALIZED = False
        tracing._TRACER_PROVIDER = None
        tracing._register_opts(cfg.CONF)
        cfg.CONF.set_override(
            'enabled', False, group='oslo_middleware_tracing'
        )
        cfg.CONF.set_override(
            'service_name', 'test', group='oslo_middleware_tracing'
        )

        @webob.dec.wsgify
        def fake_app(req):
            return 'Hello'

        self.app = fake_app

    def _make_middleware(self):
        mock_span = mock.MagicMock()
        mock_span.is_recording.return_value = True
        mock_context = mock.MagicMock()
        mock_tracer = mock.MagicMock()
        mock_tracer.start_span.return_value = mock_span
        mock_propagator = mock.MagicMock()
        mock_propagator.extract.return_value = mock_context

        middleware = tracing.TracingMiddleware(self.app)
        middleware._tracing_enabled = True
        middleware._tracer = mock_tracer
        middleware._propagator = mock_propagator

        return middleware, mock_tracer, mock_span, mock_propagator

    @mock.patch('oslo_middleware.tracing.otel_context', create=True)
    def test_creates_span_on_request(self, mock_otel_ctx):
        mock_otel_ctx.attach.return_value = 'token'
        with mock.patch.dict(
            'sys.modules',
            {
                'opentelemetry': mock.MagicMock(),
                'opentelemetry.context': mock_otel_ctx,
                'opentelemetry.trace': mock.MagicMock(),
                'opentelemetry.trace.StatusCode': mock.MagicMock(),
            },
        ):
            middleware, tracer, span, propagator = self._make_middleware()
            req = webob.Request.blank('/v2/images', method='GET')
            middleware.process_request(req)

            tracer.start_span.assert_called_once()
            call_args = tracer.start_span.call_args
            self.assertEqual('HTTP GET /v2/images', call_args[0][0])

    @mock.patch('oslo_middleware.tracing.otel_context', create=True)
    def test_sets_http_attributes(self, mock_otel_ctx):
        mock_otel_ctx.attach.return_value = 'token'
        with mock.patch.dict(
            'sys.modules',
            {
                'opentelemetry': mock.MagicMock(),
                'opentelemetry.context': mock_otel_ctx,
                'opentelemetry.trace': mock.MagicMock(),
            },
        ):
            middleware, tracer, span, _ = self._make_middleware()
            req = webob.Request.blank('/v2/images', method='GET')
            req.user_agent = 'python-glanceclient'
            middleware.process_request(req)

            calls = {
                c[0][0]: c[0][1] for c in span.set_attribute.call_args_list
            }
            self.assertEqual('GET', calls['http.method'])
            self.assertEqual('/v2/images', calls['http.route'])
            self.assertEqual('python-glanceclient', calls['http.user_agent'])

    @mock.patch('oslo_middleware.tracing.otel_context', create=True)
    def test_sets_openstack_attributes(self, mock_otel_ctx):
        mock_otel_ctx.attach.return_value = 'token'
        with mock.patch.dict(
            'sys.modules',
            {
                'opentelemetry': mock.MagicMock(),
                'opentelemetry.context': mock_otel_ctx,
                'opentelemetry.trace': mock.MagicMock(),
            },
        ):
            middleware, _, span, _ = self._make_middleware()
            req = webob.Request.blank('/v2/images')
            # Simulate oslo.context set by auth middleware
            mock_ctx = mock.MagicMock()
            mock_ctx.request_id = 'req-123'
            mock_ctx.global_request_id = 'req-global-456'
            mock_ctx.project_id = 'proj-456'
            mock_ctx.user_id = 'user-789'
            mock_ctx.domain_id = 'domain-abc'
            req.environ['oslo.context'] = mock_ctx
            middleware.process_request(req)

            calls = {
                c[0][0]: c[0][1] for c in span.set_attribute.call_args_list
            }
            self.assertEqual('req-123', calls['openstack.request_id'])
            self.assertEqual(
                'req-global-456', calls['openstack.global_request_id']
            )
            self.assertEqual('proj-456', calls['openstack.project_id'])
            self.assertEqual('user-789', calls['openstack.user_id'])
            self.assertEqual('domain-abc', calls['openstack.domain_id'])

    def test_sets_status_code_on_response(self):
        with mock.patch.dict(
            'sys.modules',
            {
                'opentelemetry': mock.MagicMock(),
                'opentelemetry.context': mock.MagicMock(),
                'opentelemetry.trace': mock.MagicMock(),
                'opentelemetry.trace.StatusCode': mock.MagicMock(),
            },
        ):
            middleware, _, span, propagator = self._make_middleware()
            req = webob.Request.blank('/test')
            req.environ['otel.span'] = span
            req.environ['otel.token'] = 'token'
            resp = webob.Response(status=200)

            middleware.process_response(resp, request=req)

            span.set_attribute.assert_any_call('http.status_code', 200)
            span.end.assert_called_once()

    def test_sets_error_status_on_5xx(self):
        with mock.patch.dict(
            'sys.modules',
            {
                'opentelemetry': mock.MagicMock(),
                'opentelemetry.context': mock.MagicMock(),
                'opentelemetry.trace': mock.MagicMock(),
            },
        ):
            from unittest.mock import MagicMock

            mock_status_code = MagicMock()
            with mock.patch(
                'oslo_middleware.tracing.StatusCode',
                mock_status_code,
                create=True,
            ):
                middleware, _, span, _ = self._make_middleware()
                req = webob.Request.blank('/test')
                req.environ['otel.span'] = span
                req.environ['otel.token'] = 'token'
                resp = webob.Response(status=500)

                middleware.process_response(resp, request=req)

                span.set_status.assert_called_once()

    def test_no_error_status_on_4xx(self):
        with mock.patch.dict(
            'sys.modules',
            {
                'opentelemetry': mock.MagicMock(),
                'opentelemetry.context': mock.MagicMock(),
                'opentelemetry.trace': mock.MagicMock(),
            },
        ):
            middleware, _, span, _ = self._make_middleware()
            req = webob.Request.blank('/test')
            req.environ['otel.span'] = span
            req.environ['otel.token'] = 'token'
            resp = webob.Response(status=404)

            middleware.process_response(resp, request=req)

            span.set_status.assert_not_called()

    def test_handles_missing_span(self):
        middleware, _, _, _ = self._make_middleware()
        req = webob.Request.blank('/test')
        resp = webob.Response(status=200)

        result = middleware.process_response(resp, request=req)
        self.assertEqual(200, result.status_int)


class TestInitTracing(test_base.BaseTestCase):
    def setUp(self):
        super().setUp()
        tracing._INITIALIZED = False
        tracing._TRACER_PROVIDER = None

    def test_init_disabled(self):
        tracing._register_opts(cfg.CONF)
        tracing.init_tracing(cfg.CONF)
        self.assertTrue(tracing._INITIALIZED)
        self.assertIsNone(tracing._TRACER_PROVIDER)

    def test_init_idempotent(self):
        tracing._register_opts(cfg.CONF)
        cfg.CONF.set_override('enabled', True, group='oslo_middleware_tracing')
        cfg.CONF.set_override(
            'service_name', 'test', group='oslo_middleware_tracing'
        )
        with mock.patch.object(
            tracing, '_create_exporter', return_value=mock.MagicMock()
        ):
            tracing.init_tracing(cfg.CONF)
            tracing.init_tracing(cfg.CONF)
        self.assertTrue(tracing._INITIALIZED)


class TestShutdownTracing(test_base.BaseTestCase):
    def test_shutdown_with_provider(self):
        mock_provider = mock.MagicMock()
        tracing._TRACER_PROVIDER = mock_provider
        tracing._INITIALIZED = True

        tracing.shutdown_tracing()

        mock_provider.shutdown.assert_called_once()
        self.assertIsNone(tracing._TRACER_PROVIDER)

    def test_shutdown_without_provider(self):
        tracing._TRACER_PROVIDER = None
        tracing.shutdown_tracing()


class TestPasteFactory(test_base.BaseTestCase):
    def test_factory_creates_middleware(self):
        @webob.dec.wsgify
        def fake_app(req):
            return 'Hello'

        factory = tracing.TracingMiddleware.factory({})
        middleware = factory(fake_app)
        self.assertIsInstance(middleware, tracing.TracingMiddleware)


class _InMemoryExporter:
    """Simple in-memory span exporter for tests.

    Replaces opentelemetry.sdk.trace.export.in_memory.InMemorySpanExporter
    which was removed in opentelemetry-sdk 1.40.
    """

    def __init__(self):
        self._spans: list = []

    def export(self, spans, **kwargs):
        self._spans.extend(spans)
        from opentelemetry.sdk.trace.export import SpanExportResult

        return SpanExportResult.SUCCESS

    def shutdown(self, **kwargs):
        pass

    def force_flush(self, timeout_millis=None, **kwargs):
        return True

    def get_finished_spans(self):
        return list(self._spans)


class TestTracingIntegration(test_base.BaseTestCase):
    """Integration tests using the real OpenTelemetry SDK.

    These tests verify that the middleware works correctly with
    the actual opentelemetry-sdk packages, catching API changes
    or incompatibilities early.

    All tests use a locally-scoped TracerProvider assigned directly
    to the middleware instance, avoiding mutation of the global otel
    provider which causes flaky failures in parallel test workers.
    """

    def setUp(self):
        super().setUp()
        tracing._INITIALIZED = False
        tracing._TRACER_PROVIDER = None
        tracing._register_opts(cfg.CONF)
        cfg.CONF.set_override(
            'enabled', False, group='oslo_middleware_tracing'
        )

        @webob.dec.wsgify
        def fake_app(req):
            return 'Hello'

        self.app = fake_app

    def _make_traced_middleware(self, app=None, sampling_rate=1.0):
        """Create a middleware with a local TracerProvider.

        Does not touch the global otel provider, so it is safe
        for parallel test execution.
        """
        from opentelemetry.propagators.composite import CompositePropagator
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.trace.propagation.tracecontext import (
            TraceContextTextMapPropagator,
        )

        resource = Resource.create({'service.name': 'test-service'})
        sampler = TraceIdRatioBased(sampling_rate)
        provider = TracerProvider(resource=resource, sampler=sampler)

        exporter = _InMemoryExporter()
        provider.add_span_processor(
            SimpleSpanProcessor(exporter)  # type: ignore[arg-type]
        )

        propagator = CompositePropagator(
            [
                TraceContextTextMapPropagator(),
            ]
        )

        middleware = tracing.TracingMiddleware(app or self.app)
        middleware._tracing_enabled = True
        middleware._tracer = provider.get_tracer('oslo_middleware.tracing')
        middleware._propagator = propagator

        return middleware, exporter, provider

    def test_init_creates_tracer_provider(self):
        from opentelemetry.sdk.trace import TracerProvider

        _, _, provider = self._make_traced_middleware()
        self.assertIsInstance(provider, TracerProvider)

    def test_init_sets_service_name(self):
        _, _, provider = self._make_traced_middleware()
        attrs = dict(provider.resource.attributes)
        self.assertEqual('test-service', attrs['service.name'])

    def test_middleware_creates_real_spans(self):
        from opentelemetry.sdk.trace import ReadableSpan

        middleware, exporter, _ = self._make_traced_middleware()

        req = webob.Request.blank('/v2/images', method='GET')
        mock_ctx = mock.MagicMock()
        mock_ctx.request_id = 'req-test-123'
        mock_ctx.global_request_id = None
        mock_ctx.project_id = 'proj-test-456'
        mock_ctx.user_id = 'user-test-789'
        mock_ctx.domain_id = None
        req.environ['oslo.context'] = mock_ctx
        resp = req.get_response(middleware)

        self.assertEqual(200, resp.status_int)

        spans = exporter.get_finished_spans()
        self.assertGreaterEqual(len(spans), 1)

        span = spans[-1]
        self.assertIsInstance(span, ReadableSpan)
        self.assertEqual('HTTP GET /v2/images', span.name)

        attrs = dict(span.attributes)
        self.assertEqual('GET', attrs['http.method'])
        self.assertEqual('/v2/images', attrs['http.route'])
        self.assertEqual(200, attrs['http.status_code'])
        self.assertEqual('req-test-123', attrs['openstack.request_id'])
        self.assertEqual('proj-test-456', attrs['openstack.project_id'])
        self.assertEqual('user-test-789', attrs['openstack.user_id'])

    def test_middleware_sets_error_on_5xx(self):
        from opentelemetry.trace import StatusCode

        @webob.dec.wsgify
        def error_app(req):
            resp = webob.Response(status=503)
            resp.text = 'Service Unavailable'
            return resp

        middleware, exporter, _ = self._make_traced_middleware(app=error_app)
        req = webob.Request.blank('/fail')
        resp = req.get_response(middleware)

        self.assertEqual(503, resp.status_int)

        spans = exporter.get_finished_spans()
        span = spans[-1]
        self.assertEqual(StatusCode.ERROR, span.status.status_code)
        self.assertEqual(503, dict(span.attributes)['http.status_code'])

    def test_middleware_propagates_traceparent(self):
        middleware, exporter, _ = self._make_traced_middleware()

        traceparent = '00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01'
        req = webob.Request.blank('/test')
        req.headers['traceparent'] = traceparent
        resp = req.get_response(middleware)

        self.assertEqual(200, resp.status_int)

        spans = exporter.get_finished_spans()
        span = spans[-1]
        trace_id = format(span.context.trace_id, '032x')
        self.assertEqual('0af7651916cd43dd8448eb211c80319c', trace_id)

        self.assertIn('traceparent', resp.headers)

    def test_middleware_injects_traceparent_in_response(self):
        middleware, _, _ = self._make_traced_middleware()
        req = webob.Request.blank('/test')
        resp = req.get_response(middleware)

        self.assertIn('traceparent', resp.headers)
        parts = resp.headers['traceparent'].split('-')
        self.assertEqual(4, len(parts))
        self.assertEqual('00', parts[0])

    def test_shutdown_flushes_spans(self):
        middleware, exporter, _ = self._make_traced_middleware()
        req = webob.Request.blank('/test')
        req.get_response(middleware)

        self.assertGreaterEqual(len(exporter.get_finished_spans()), 1)

    def test_sampling_rate(self):
        middleware, exporter, _ = self._make_traced_middleware(
            sampling_rate=0.0
        )

        for _ in range(10):
            req = webob.Request.blank('/test')
            req.get_response(middleware)

        spans = exporter.get_finished_spans()
        self.assertEqual(0, len(spans))
