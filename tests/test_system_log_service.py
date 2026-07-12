import unittest
from unittest.mock import MagicMock, patch

from app.services.system_log_service import _json_safe, db_log


class SystemLogServiceTests(unittest.TestCase):
    @patch("app.core.database.public_db")
    def test_db_log_inserts_with_source_core(self, mock_public_db):
        mock_table = MagicMock()
        mock_public_db.return_value.table.return_value = mock_table
        mock_table.insert.return_value.execute.return_value = None

        db_log("backup", "info", "백업 완료", {"s3_key": "backups/test.json.gz"})

        mock_public_db.return_value.table.assert_called_once_with("system_logs")
        payload = mock_table.insert.call_args[0][0]
        self.assertEqual(payload["source"], "core")
        self.assertEqual(payload["category"], "backup")
        self.assertEqual(payload["level"], "info")
        self.assertEqual(payload["message"], "백업 완료")
        self.assertEqual(payload["context"]["s3_key"], "backups/test.json.gz")

    @patch("app.core.database.public_db")
    def test_db_log_swallows_insert_errors(self, mock_public_db):
        mock_public_db.return_value.table.side_effect = RuntimeError("db down")
        db_log("scheduler", "error", "실패")  # must not raise

    def test_json_safe_serializes_non_json_types(self):
        class Dummy:
            def __str__(self):
                return "dummy"

        result = _json_safe({"x": Dummy()})
        self.assertEqual(result["x"], "dummy")


if __name__ == "__main__":
    unittest.main()
