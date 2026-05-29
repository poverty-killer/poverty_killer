"""Local operator credential storage.

The package stores local runtime secrets only under a gitignored operator
secret directory. Public APIs must use the redacted summaries, not raw values.
"""

from app.operator_credentials.store import LocalCredentialStore, default_credential_store_path

__all__ = ["LocalCredentialStore", "default_credential_store_path"]
