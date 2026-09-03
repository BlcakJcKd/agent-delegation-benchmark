"""Tests for delegation.config: the user-owned XDG availability config."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from delegation.config import default_config, load_config, parse_config, save_config, set_enabled
from delegation.routing import EXPERIMENTAL_PAYG_NAMES, MODELS, PROVIDERS


class DefaultConfigTests(unittest.TestCase):
    def test_default_config_has_every_stable_provider_and_model_enabled(self):
        config = default_config()
        self.assertEqual(set(config["providers"]), set(PROVIDERS))
        self.assertEqual(set(config["models"]), set(MODELS))
        for name, entry in {**config["providers"], **config["models"]}.items():
            if name in EXPERIMENTAL_PAYG_NAMES:
                continue
            self.assertTrue(entry["enabled"])
            self.assertNotIn("reason", entry)

    def test_default_config_has_experimental_payg_entries_disabled_with_a_reason(self):
        config = default_config()
        for section, name in (
            ("providers", "deepseek"), ("providers", "minimax"),
            ("models", "deepseek-pro"), ("models", "deepseek-flash"), ("models", "minimax-m3"),
        ):
            entry = config[section][name]
            self.assertFalse(entry["enabled"], f"{section}.{name} must default to disabled")
            self.assertEqual(entry["reason"], "experimental PAYG; benchmark pending")


class LoadConfigTests(unittest.TestCase):
    def test_missing_file_returns_default_config_without_creating_one(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "nested" / "config.toml"
            config = load_config(path)
            self.assertEqual(config, default_config())
            self.assertFalse(path.exists())

    def test_unknown_provider_in_file_is_rejected(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "config.toml"
            path.write_text('[providers.notaprovider]\nenabled = true\n')
            with self.assertRaisesRegex(ValueError, "unknown provider"):
                load_config(path)

    def test_unknown_model_in_file_is_rejected(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "config.toml"
            path.write_text('[models.gpt5]\nenabled = true\n')
            with self.assertRaisesRegex(ValueError, "unknown model"):
                load_config(path)

    def test_non_boolean_enabled_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "must be a boolean"):
            parse_config({"providers": {"codex": {"enabled": "yes"}}})

    def test_missing_enabled_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "enabled is required"):
            parse_config({"providers": {"codex": {"reason": "x"}}})

    def test_unsupported_field_is_rejected_no_secret_fields_supported(self):
        with self.assertRaisesRegex(ValueError, "unsupported field"):
            parse_config({"providers": {"codex": {"enabled": True, "api_key": "sk-secret"}}})

    def test_entry_missing_from_file_defaults_to_enabled(self):
        config = parse_config({"providers": {"codex": {"enabled": False}}})
        self.assertFalse(config["providers"]["codex"]["enabled"])
        self.assertTrue(config["providers"]["claude"]["enabled"])
        self.assertTrue(config["providers"]["gemini"]["enabled"])

    def test_pre_existing_config_migrates_payg_entries_to_disabled_without_touching_the_rest(self):
        # A config written before deepseek/minimax existed (the real schema
        # this project's own installed config currently has): loading it
        # must not silently enable the new PAYG providers/routes, and must
        # leave every pre-existing entry exactly as recorded.
        with TemporaryDirectory() as temp:
            path = Path(temp) / "config.toml"
            path.write_text(
                "[providers.claude]\nenabled = true\n"
                "[providers.codex]\nenabled = true\n"
                "[providers.gemini]\nenabled = true\n"
                "[models.flash]\nenabled = true\n"
                "[models.haiku]\nenabled = true\n"
                "[models.luna]\nenabled = true\n"
                "[models.sonnet]\nenabled = true\n"
                "[models.terra]\nenabled = true\n"
            )
            config = load_config(path)
            for section, name in (
                ("providers", "claude"), ("providers", "codex"), ("providers", "gemini"),
                ("models", "flash"), ("models", "haiku"), ("models", "luna"),
                ("models", "sonnet"), ("models", "terra"),
            ):
                self.assertEqual(config[section][name], {"enabled": True})
            self.assertFalse(config["providers"]["deepseek"]["enabled"])
            self.assertFalse(config["providers"]["minimax"]["enabled"])
            self.assertFalse(config["models"]["deepseek-pro"]["enabled"])
            self.assertFalse(config["models"]["deepseek-flash"]["enabled"])
            self.assertFalse(config["models"]["minimax-m3"]["enabled"])
            # The migration is in-memory only; the file on disk is untouched
            # unless something explicitly calls save_config.
            self.assertNotIn("deepseek", path.read_text())


class SaveConfigTests(unittest.TestCase):
    def test_round_trips_through_save_and_load(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "config.toml"
            config = default_config()
            config = set_enabled(config, "providers", "codex", False, reason="weekly quota low")
            save_config(config, path)
            reloaded = load_config(path)
            self.assertEqual(reloaded, config)

    def test_save_creates_parent_directories(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "a" / "b" / "config.toml"
            save_config(default_config(), path)
            self.assertTrue(path.is_file())

    def test_save_keeps_user_configuration_private(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "config.toml"
            save_config(default_config(), path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)

    def test_save_is_atomic_no_leftover_temp_file(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "config.toml"
            save_config(default_config(), path)
            leftovers = [p for p in Path(temp).iterdir() if p.name != "config.toml"]
            self.assertEqual(leftovers, [])

    def test_rendered_file_never_contains_a_secret_like_field(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "config.toml"
            save_config(default_config(), path)
            data_lines = "\n".join(
                line for line in path.read_text().splitlines() if not line.strip().startswith("#")
            ).lower()
            for forbidden in ("api_key", "token", "password", "secret", "credential"):
                self.assertNotIn(forbidden, data_lines)


class SetEnabledTests(unittest.TestCase):
    def test_disable_sets_reason(self):
        config = set_enabled(default_config(), "models", "flash", False, reason="weekly quota low")
        self.assertFalse(config["models"]["flash"]["enabled"])
        self.assertEqual(config["models"]["flash"]["reason"], "weekly quota low")

    def test_enable_clears_a_stale_reason(self):
        config = set_enabled(default_config(), "models", "flash", False, reason="weekly quota low")
        config = set_enabled(config, "models", "flash", True)
        self.assertTrue(config["models"]["flash"]["enabled"])
        self.assertNotIn("reason", config["models"]["flash"])

    def test_disable_without_reason_preserves_existing_reason(self):
        config = set_enabled(default_config(), "models", "flash", False, reason="weekly quota low")
        config = set_enabled(config, "models", "flash", False)
        self.assertEqual(config["models"]["flash"]["reason"], "weekly quota low")

    def test_idempotent_disable_with_same_reason_is_a_no_op_value(self):
        config = set_enabled(default_config(), "models", "flash", False, reason="x")
        again = set_enabled(config, "models", "flash", False, reason="x")
        self.assertEqual(config, again)

    def test_unknown_route_name_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown model"):
            set_enabled(default_config(), "models", "gpt5", False)

    def test_unknown_provider_name_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown provider"):
            set_enabled(default_config(), "providers", "openai", False)

    def test_set_enabled_does_not_mutate_unrelated_entries(self):
        original = default_config()
        updated = set_enabled(original, "models", "flash", False, reason="x")
        self.assertTrue(original["models"]["flash"]["enabled"], "original must be untouched")
        for name in ("sonnet", "haiku", "terra", "luna"):
            self.assertEqual(updated["models"][name], original["models"][name])
        self.assertEqual(updated["providers"], original["providers"])

    def test_set_enabled_returns_a_new_object_not_an_alias(self):
        original = default_config()
        updated = set_enabled(original, "models", "flash", False, reason="x")
        self.assertIsNot(updated, original)
        self.assertIsNot(updated["models"], original["models"])


if __name__ == "__main__":
    unittest.main()
