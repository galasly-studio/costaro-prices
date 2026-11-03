#!/usr/bin/env python3
"""One guarded retry for temporary labor-source transport failures only.

Never retry access denials, rate limits, DNS/TLS errors, unsafe redirects,
content validation failures or other non-transient errors.
No prices or catalog files are changed here.
"""

from __future__ import annotations

import socket
import time
import urllib.error


TRANSIENT_HTTP_CODES = frozenset({502, 503, 504})
MAX_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 0.75


def is_transient_transport_error(error: BaseException) -> bool:
    """Strictly classify only brief network/server failures."""

    if isinstance(error, urllib.error.HTTPError):
        return error.code in TRANSIENT_HTTP_CODES

    if isinstance(error, (TimeoutError, socket.timeout)):
        return True

    if isinstance(error, urllib.error.URLError):
        return isinstance(
            error.reason,
            (TimeoutError, socket.timeout),
        )

    return False


def open_with_guarded_retry(
    opener,
    request,
    *,
    timeout: float,
    pause=None,
):
    """Open the same prepared request at most twice.

    URL allowlisting and guarded redirects remain the caller's
    responsibility and must be applied before this function.
    """

    if pause is None:
        pause = time.sleep

    if not 0 < timeout <= 30:
        raise ValueError("invalid_request_timeout")

    for attempt in range(MAX_ATTEMPTS):
        try:
            return opener.open(request, timeout=timeout)

        except (OSError, ValueError) as error:
            last_attempt = attempt == MAX_ATTEMPTS - 1

            if last_attempt or not is_transient_transport_error(error):
                raise

            pause(RETRY_DELAY_SECONDS)

    raise AssertionError("Unreachable guarded retry state")