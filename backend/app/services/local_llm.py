"""Optional local language model (Ollama). Never an external API, never an API key.

ASTITVA works fully without it: every agent and the risk engine produce deterministic, template-based text. When
LLM_PROVIDER=ollama is set and LLM_BASE_URL points at a model server on this machine or the private network
(for example http://localhost:11434 or http://ollama:11434 in Docker Compose), the model may only *rephrase* text
that the deterministic code already decided. It never sees secrets, never changes a score and never approves.
Public hosts are refused, so request data cannot leave the network by configuration mistake.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

from app.core.config import get_settings

log = logging.getLogger("astitva.local_llm")
LOCAL_HOSTNAMES = {"localhost", "ollama", "host.docker.internal"}


def is_local_url(url: str | None) -> bool:
    if not url:
        return False
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if p.scheme not in ("http", "https") or not host:
        return False
    if host in LOCAL_HOSTNAMES or host.endswith(".local") or host.endswith(".internal"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        try:
            ip = ipaddress.ip_address(socket.gethostbyname(host))
        except OSError:
            return False
    return ip.is_loopback or ip.is_private


def enabled() -> bool:
    s = get_settings()
    return s.llm_provider == "ollama" and is_local_url(s.llm_base_url)


def label() -> str | None:
    return f"local:{get_settings().llm_model}" if enabled() else None


def generate(prompt: str, max_tokens: int = 160, timeout: float = 6.0) -> str | None:
    """Ask the local model to phrase something. Returns None when disabled, unreachable or slow."""
    if not enabled():
        return None
    s = get_settings()
    import httpx

    try:
        r = httpx.post(s.llm_base_url.rstrip("/") + "/api/generate", timeout=timeout,
                       json={"model": s.llm_model, "prompt": prompt, "stream": False, "think": False,
                             "options": {"temperature": 0, "num_predict": max_tokens}})
        r.raise_for_status()
        text = (r.json().get("response") or "").strip()
        return text[:800] or None
    except Exception as exc:  # the deterministic text is always the fallback
        log.warning("local model unavailable, using deterministic text: %s", exc)
        return None
