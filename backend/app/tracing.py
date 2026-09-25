"""One OpenTelemetry span per chat call, exported to local Phoenix.

Phoenix is optional. If it is not running, the API still returns a trace id.
Start the UI with: phoenix serve
Then open http://localhost:6006
"""

from opentelemetry import trace

try:
    from phoenix.otel import register

    register(
        project_name="nimbus-brain",
        endpoint="http://127.0.0.1:6006/v1/traces",
        batch=False,
        auto_instrument=False,
        verbose=False,
    )
except Exception:
    # Missing package or Phoenix is down. Chat still works.
    pass

tracer = trace.get_tracer("nimbus-brain")


def trace_id(span) -> str:
    return format(span.get_span_context().trace_id, "032x")
