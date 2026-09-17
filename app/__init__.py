"""Quillon Post: the parcel API the shops we sell to call from their checkouts."""

# The dated version of the API this build speaks. It goes out on every response in the
# Quillon-Version header and it is the version the public docs describe.
API_VERSION = "2026-08-01"

# The build of the service itself, which nobody outside Bristol ever sees.
SERVICE_VERSION = "2.4.0"

__all__ = ["API_VERSION", "SERVICE_VERSION"]
