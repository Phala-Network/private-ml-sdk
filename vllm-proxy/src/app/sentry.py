import os
import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration


def init_sentry():
    """
    Initialize Sentry for error monitoring and performance tracking.
    """
    dsn = os.getenv("SENTRY_DSN")
    if not dsn:
        return    
    sentry_sdk.init(
        dsn=dsn,
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        send_default_pii=bool(os.getenv("SENTRY_SEND_PII", "false").lower() == "true"),
    )