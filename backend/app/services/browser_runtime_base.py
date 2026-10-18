from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from app.config import get_settings
from app.services.ats_base import page_fingerprint
from app.services.browser_handoff import current_browser_node_id


CDP_STARTUP_TIMEOUT_SECONDS = 120
PLAYWRIGHT_ATTACH_TIMEOUT_SECONDS = 120
EXTERNAL_CDP_CONNECT_TIMEOUT_SECONDS = 20
CHROMIUM_TRANSIENT_SINGLETON_NAMES = (
    "SingletonLock",
    "SingletonSocket",
    "SingletonCookie",
)


class BrowserRuntimeError(RuntimeError):
    pass
