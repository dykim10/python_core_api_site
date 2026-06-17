import os
import unittest
from unittest.mock import MagicMock, patch

from app.core import secrets_loader


class LoadSecretsTests(unittest.TestCase):
    def setUp(self):
        self._env_backup = dict(os.environ)
        os.environ.pop("APP_ENV", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env_backup)

    @patch("app.core.secrets_loader.load_dotenv")
    @patch("boto3.client")
    def test_skips_when_not_production(self, mock_client, mock_load_dotenv):
        os.environ["APP_ENV"] = "local"
        secrets_loader.load_secrets()
        mock_client.assert_not_called()

    @patch("app.core.secrets_loader.load_dotenv")
    @patch("boto3.client")
    def test_detects_production_from_dotenv_when_no_os_env_var(self, mock_client, mock_load_dotenv):
        # APP_ENV가 OS 환경변수로는 없고 .env 파일에만 있는 경우를 시뮬레이션한다.
        def fake_load_dotenv(*args, **kwargs):
            os.environ["APP_ENV"] = "production"
        mock_load_dotenv.side_effect = fake_load_dotenv
        mock_ssm = MagicMock()
        mock_client.return_value = mock_ssm
        mock_ssm.get_paginator.return_value.paginate.return_value = []
        secrets_loader.load_secrets()
        mock_client.assert_called_once_with("ssm", region_name="ap-northeast-2")

    @patch("app.core.secrets_loader.load_dotenv")
    @patch("boto3.client")
    def test_loads_and_paginates_across_pages(self, mock_client, mock_load_dotenv):
        os.environ["APP_ENV"] = "production"
        mock_ssm = MagicMock()
        mock_client.return_value = mock_ssm
        mock_paginator = MagicMock()
        mock_ssm.get_paginator.return_value = mock_paginator
        mock_paginator.paginate.return_value = [
            {"Parameters": [
                {"Name": "/pac-run/prod/supabase/db-password", "Value": "pw-123"},
                {"Name": "/pac-run/prod/anthropic/api-key", "Value": "sk-ant-abc"},
            ]},
            {"Parameters": [
                {"Name": "/pac-run/prod/kma/api-key", "Value": "kma-xyz"},
            ]},
        ]
        secrets_loader.load_secrets()
        mock_ssm.get_paginator.assert_called_once_with("get_parameters_by_path")
        mock_paginator.paginate.assert_called_once_with(
            Path="/pac-run/prod/",
            Recursive=True,
            WithDecryption=True,
        )
        self.assertEqual(os.environ["DB_PASSWORD"], "pw-123")
        self.assertEqual(os.environ["ANTHROPIC_API_KEY"], "sk-ant-abc")
        self.assertEqual(os.environ["KMA_API_KEY"], "kma-xyz")

    @patch("app.core.secrets_loader.load_dotenv")
    @patch("boto3.client")
    def test_ignores_unmapped_parameter_names(self, mock_client, mock_load_dotenv):
        os.environ["APP_ENV"] = "production"
        mock_ssm = MagicMock()
        mock_client.return_value = mock_ssm
        mock_ssm.get_paginator.return_value.paginate.return_value = [
            {"Parameters": [
                {"Name": "/pac-run/prod/unknown/thing", "Value": "should-not-load"},
            ]}
        ]
        secrets_loader.load_secrets()
        self.assertNotIn("should-not-load", os.environ.values())


if __name__ == "__main__":
    unittest.main()
