"""Access only the supported operating-system credential stores."""

from __future__ import annotations

import platform
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from keyring.backend import KeyringBackend


class CredentialStoreError(RuntimeError):
    """Raised when no approved secure credential store is available."""


_ALLOWED_BACKENDS: dict[str, set[str]] = {
    "Windows": {"keyring.backends.Windows.WinVaultKeyring"},
    "Darwin": {"keyring.backends.macOS.Keyring"},
    "Linux": {
        "keyring.backends.SecretService.Keyring",
        "keyring.backends.kwallet.DBusKeyring",
    },
}


def credential_backend() -> KeyringBackend:
    """Return an approved native keyring backend, failing closed otherwise."""
    system = platform.system()
    allowed = _ALLOWED_BACKENDS.get(system)
    if allowed is None:
        raise CredentialStoreError(
            "Secure OAuth storage is supported only on Windows, macOS, and Linux desktop systems."
        )

    try:
        import keyring

        backend = keyring.get_keyring()
    except Exception:
        raise CredentialStoreError(
            "The operating system's secure credential store is unavailable; no OAuth token was read or written."
        ) from None

    identity = f"{type(backend).__module__}.{type(backend).__name__}"
    if identity in allowed:
        return backend

    # keyring can combine multiple viable backends. Select one approved child
    # directly so an unapproved backend is never available as a fallback.
    if identity == "keyring.backends.chainer.ChainerBackend":
        try:
            for candidate in backend.backends:
                candidate_identity = f"{type(candidate).__module__}.{type(candidate).__name__}"
                if candidate_identity in allowed:
                    return candidate
        except Exception:
            pass

    raise CredentialStoreError(
        "No approved native credential store is active; select Windows Credential Manager, "
        "macOS Keychain, or Linux Secret Service/KWallet. No OAuth token was read or written."
    )
