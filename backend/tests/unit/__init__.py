"""True unit tests for backend/app/utils modules.

Unlike backend/tests/test_*.py (which exercise full HTTP routes against the
FakeDatabase integration double), the tests under this package import
individual functions from app/utils directly and mock every external
dependency (MongoDB calls, transformer model loads, S3/SMTP clients, network
sockets) so each function is verified in isolation.
"""
