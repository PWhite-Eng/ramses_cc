"""
Test coverage for common.py.
"""

from unittest.mock import patch

from custom_components.ramses_cc import DOMAIN
from tests.tests_new.common import configuration_fixture, storage_fixture


def test_configuration_fixture_fallback() -> None:
    """
    Test that configuration_fixture falls back to default on FileNotFoundError.

    :return: None
    """
    # Using a name that definitely won't exist in your fixtures folder
    instance = "non_existent_instance_xyz"

    # We mock the loader to verify it's called with 'default' when the first attempt fails
    with patch("tests.tests_new.common.load_yaml_object_fixture") as mock_load_yaml:
        # First call raises FileNotFoundError, second call succeeds
        mock_load_yaml.side_effect = [FileNotFoundError, {"test": "default_config"}]

        result = configuration_fixture(instance)

        assert result == {"test": "default_config"}
        assert mock_load_yaml.call_count == 2
        # Verify the fallback path was used
        mock_load_yaml.assert_called_with("default/configuration.yaml", DOMAIN)


def test_storage_fixture_fallback() -> None:
    """
    Test that storage_fixture falls back to minimal on FileNotFoundError.

    :return: None
    """
    instance = "non_existent_instance_xyz"

    with patch("tests.tests_new.common.load_json_object_fixture") as mock_load_json:
        # First call raises FileNotFoundError, second call succeeds
        mock_load_json.side_effect = [FileNotFoundError, {"test": "minimal_storage"}]

        result = storage_fixture(instance)

        assert result == {"test": "minimal_storage"}
        assert mock_load_json.call_count == 2
        # Verify the fallback path was used
        mock_load_json.assert_called_with("minimal/storage.json", DOMAIN)
