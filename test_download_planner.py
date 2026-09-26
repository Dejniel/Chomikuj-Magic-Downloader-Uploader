#!/usr/bin/env python3

import unittest
from unittest.mock import Mock

from chomikuj.common_runtime import ApiCloudflareChallengeError
from chomikuj.download_planner import DownloadPlanner


class DownloadPlannerTest(unittest.TestCase):
    def _blocked_planner(self):
        planner = DownloadPlanner("user", "password", recursive=True)
        planner._reader_mobile = Mock()
        planner._reader_mobile.split_url.side_effect = ApiCloudflareChallengeError("Cloudflare")
        return planner

    def test_recursive_folder_preserves_cloudflare_error(self):
        planner = self._blocked_planner()
        planner._soap_current = Mock(return_value={"tasks": [], "is_exact_folder": True, "folder": {}})

        with self.assertRaises(ApiCloudflareChallengeError):
            planner.collect("https://chomikuj.pl/user/folder")

    def test_recursive_file_can_still_use_soap_fallback(self):
        planner = self._blocked_planner()
        tasks = [("file.txt", Mock(), "user")]
        planner._soap_current = Mock(return_value={"tasks": tasks, "is_exact_folder": False, "folder": {}})

        self.assertEqual(planner.collect("https://chomikuj.pl/user/folder/file.txt"), tasks)


if __name__ == "__main__":
    unittest.main()
