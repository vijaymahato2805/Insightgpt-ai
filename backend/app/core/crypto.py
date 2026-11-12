import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings, get_settings


class CredentialEncryptionError(RuntimeError):
    """Raised when the application cannot safely encrypt or decrypt credentials."""


class CredentialVault:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _fernet(self) -> Fernet:
        secret = self.settings.encryption_key
        master = secret.get_secret_value() if secret else ""
        if len(master) < 32:
            raise CredentialEncryptionError(
                "ENCRYPTION_KEY must be configured with at least 32 characters"
            )
        key = base64.urlsafe_b64encode(hashlib.sha256(master.encode("utf-8")).digest())
        return Fernet(key)

    def encrypt(self, credentials: dict[str, str]) -> str:
        payload = json.dumps(credentials, separators=(",", ":")).encode("utf-8")
        return self._fernet().encrypt(payload).decode("ascii")

    def decrypt(self, ciphertext: str) -> dict[str, str]:
        try:
            value = self._fernet().decrypt(ciphertext.encode("ascii"))
            result = json.loads(value.decode("utf-8"))
        except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise CredentialEncryptionError("Stored credentials could not be decrypted") from exc
        if not isinstance(result, dict) or any(
            not isinstance(item, str) for item in result.values()
        ):
            raise CredentialEncryptionError("Stored credentials have an invalid format")
        return result
