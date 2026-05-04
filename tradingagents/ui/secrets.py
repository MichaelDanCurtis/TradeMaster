from __future__ import annotations

import os
import subprocess
from typing import Protocol


class SecretNotFoundError(KeyError):
    """Raised when a configured secret reference cannot be resolved."""


class SecretStore(Protocol):
    def get_secret(self, secret_ref: str) -> str:
        ...

    def set_secret(self, secret_ref: str, value: str) -> None:
        ...

    def delete_secret(self, secret_ref: str) -> None:
        ...

    def describe_secret(self, secret_ref: str) -> dict[str, object]:
        ...


class EnvSecretStore:
    def get_secret(self, secret_ref: str) -> str:
        name = self._env_name(secret_ref)
        value = os.environ.get(name)
        if value is None:
            raise SecretNotFoundError(secret_ref)
        return value

    def set_secret(self, secret_ref: str, value: str) -> None:
        os.environ[self._env_name(secret_ref)] = value

    def delete_secret(self, secret_ref: str) -> None:
        os.environ.pop(self._env_name(secret_ref), None)

    def describe_secret(self, secret_ref: str) -> dict[str, object]:
        name = self._env_name(secret_ref)
        return {"backend": "env", "available": name in os.environ}

    @staticmethod
    def _env_name(secret_ref: str) -> str:
        if not secret_ref.startswith("env:"):
            raise ValueError("EnvSecretStore only supports env: references")
        name = secret_ref.removeprefix("env:").strip()
        if not name:
            raise ValueError("env secret reference must include a variable name")
        return name


class MacKeychainSecretStore:
    def get_secret(self, secret_ref: str) -> str:
        service, account = self._parts(secret_ref)
        result = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", service, "-a", account, "-w"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise SecretNotFoundError(secret_ref)
        return result.stdout.rstrip("\n")

    def set_secret(self, secret_ref: str, value: str) -> None:
        service, account = self._parts(secret_ref)
        subprocess.run(
            [
                "/usr/bin/security",
                "add-generic-password",
                "-U",
                "-s",
                service,
                "-a",
                account,
                "-w",
                value,
            ],
            check=True,
        )

    def delete_secret(self, secret_ref: str) -> None:
        service, account = self._parts(secret_ref)
        subprocess.run(
            ["/usr/bin/security", "delete-generic-password", "-s", service, "-a", account],
            check=False,
            capture_output=True,
            text=True,
        )

    def describe_secret(self, secret_ref: str) -> dict[str, object]:
        try:
            self.get_secret(secret_ref)
            available = True
        except SecretNotFoundError:
            available = False
        return {"backend": "mac-keychain", "available": available}

    @staticmethod
    def _parts(secret_ref: str) -> tuple[str, str]:
        if not secret_ref.startswith("keychain:"):
            raise ValueError("MacKeychainSecretStore only supports keychain: references")
        parts = secret_ref.split(":", 2)
        if len(parts) != 3 or not parts[1] or not parts[2]:
            raise ValueError("keychain secret reference must be keychain:<service>:<account>")
        return parts[1], parts[2]
