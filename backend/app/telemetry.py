"""OpenTelemetry setup (architecture §2: observability).

No-op unless OTEL_EXPORTER_OTLP_ENDPOINT is set, so the default boot stays
dependency-light. When enabled, auto-instruments FastAPI + httpx and exports
traces over OTLP/HTTP to a collector (Tempo/Grafana or hosted).
"""
from __future__ import annotations

import logging

from .config import settings

log = logging.getLogger("weave.telemetry")


def setup_telemetry(app) -> None:  # noqa: ANN001
    if not settings.otel_enabled:
        return
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create({"service.name": settings.otel_service_name}))
        provider.add_span_processor(BatchSpanProcessor(
            OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)))
        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app)
        try:
            from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
            HTTPXClientInstrumentor().instrument()
        except Exception:  # noqa: BLE001
            pass
        log.info("OpenTelemetry enabled -> %s", settings.otel_exporter_otlp_endpoint)
    except Exception as exc:  # noqa: BLE001
        log.warning("OpenTelemetry setup skipped: %s", exc)
