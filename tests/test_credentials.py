import json

import pytest
from keyring.errors import PasswordDeleteError

from vision_mcp.config import default_config
from vision_mcp.credentials import (
    LEGACY_BACKUP_MAGIC,
    delete_key,
    get_provider_key,
    migrate_legacy,
    purge_all,
    purge_legacy_data,
)


def test_legacy_named_keys_are_migrated_and_backed_up(app_env, monkeypatch):
    legacy = app_env["roaming"] / "vision-mcp" / "keys.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(json.dumps({"主-智谱免费": "legacy-secret"}), encoding="utf-8")
    vault = {}
    monkeypatch.setattr("vision_mcp.credentials.get_key", lambda provider_id: vault.get(provider_id, ""))
    monkeypatch.setattr("vision_mcp.credentials.set_key", lambda provider_id, value: vault.__setitem__(provider_id, value))
    monkeypatch.setattr("vision_mcp.credentials._protect_bytes", lambda raw: LEGACY_BACKUP_MAGIC + raw[::-1])
    cfg = default_config()
    assert migrate_legacy(cfg) == 1
    assert all(vault[provider["id"]] == "legacy-secret" for provider in cfg["providers"])
    assert not legacy.exists()
    backup = legacy.with_suffix(".json.migrated.bak")
    assert backup.exists()
    assert b"legacy-secret" not in backup.read_bytes()
    assert backup.read_bytes().startswith(LEGACY_BACKUP_MAGIC)


def test_legacy_plaintext_is_backed_up_when_credential_already_exists(app_env, monkeypatch):
    legacy = app_env["roaming"] / "vision-mcp" / "keys.json"
    legacy.parent.mkdir(parents=True)
    cfg = default_config()
    legacy.write_text(json.dumps({cfg["providers"][0]["name"]: "older-secret"}), encoding="utf-8")
    monkeypatch.setattr("vision_mcp.credentials.get_key", lambda _provider_id: "newer-secret")
    monkeypatch.setattr("vision_mcp.credentials.set_key", lambda *_args: pytest.fail("must not overwrite credential"))
    monkeypatch.setattr("vision_mcp.credentials._protect_bytes", lambda raw: LEGACY_BACKUP_MAGIC + raw[::-1])

    assert migrate_legacy(cfg) == 0
    assert not legacy.exists()
    backup = legacy.with_suffix(".json.migrated.bak")
    assert backup.exists()
    assert b"older-secret" not in backup.read_bytes()


def test_existing_plaintext_backup_is_upgraded(app_env, monkeypatch):
    folder = app_env["roaming"] / "vision-mcp"
    folder.mkdir(parents=True)
    backup = folder / "keys.json.migrated.bak"
    backup.write_bytes(b'\x7b"provider":"old-secret"\x7d')
    monkeypatch.setattr("vision_mcp.credentials._protect_bytes", lambda raw: LEGACY_BACKUP_MAGIC + raw[::-1])

    assert migrate_legacy(default_config()) == 0
    assert backup.read_bytes().startswith(LEGACY_BACKUP_MAGIC)
    assert b"old-secret" not in backup.read_bytes()


def test_purge_legacy_data_removes_plaintext_files(app_env):
    folder = app_env["roaming"] / "vision-mcp"
    folder.mkdir(parents=True)
    (folder / "keys.json").write_text("secret", encoding="utf-8")
    (folder / "keys.json.migrated.bak").write_text("secret", encoding="utf-8")
    assert purge_legacy_data() == 2
    assert not folder.exists()


def test_deleting_missing_credential_is_idempotent(monkeypatch):
    class MissingBackend:
        class errors:
            PasswordDeleteError = PasswordDeleteError

        @staticmethod
        def delete_password(_service, _provider_id):
            raise PasswordDeleteError("VisionMCP")

    monkeypatch.setattr("vision_mcp.credentials._backend", lambda: MissingBackend)
    delete_key("missing-provider")


def test_provider_key_falls_back_to_migration_alias(monkeypatch):
    vault = {"old-id": "legacy-secret"}
    monkeypatch.setattr("vision_mcp.credentials.get_key", lambda provider_id: vault.get(provider_id, ""))
    assert get_provider_key({"id": "new-id", "credential_aliases": ["old-id"]}) == "legacy-secret"


def test_purge_all_removes_orphaned_windows_credentials(monkeypatch):
    vault = {"current": "secret", "orphaned": "secret"}
    deleted = []
    monkeypatch.setattr("vision_mcp.credentials._windows_provider_ids", lambda: {"orphaned"})
    monkeypatch.setattr("vision_mcp.credentials.get_key", lambda provider_id: vault.get(provider_id, ""))
    monkeypatch.setattr("vision_mcp.credentials.delete_key", lambda provider_id: deleted.append(provider_id))

    count = purge_all({"providers": [{"id": "current"}]})

    assert count == 2
    assert set(deleted) == {"current", "orphaned"}
