"""OpenHarnX: verifies work done by coding agents."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("openharnx")
except PackageNotFoundError:  # running from a source tree without an install
    __version__ = "0.0.0+unknown"
