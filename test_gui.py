#!/usr/bin/env python3

import os
import unittest
from unittest.mock import Mock, patch

from chomikuj import gui


if gui.tk is not None:
    class GuiTest(unittest.TestCase):
        @patch.object(gui.dialog_folder_language, "register")
        @patch.object(gui.dialog_folder, "askpath", return_value=("/tmp/first", "/tmp/second"))
        def test_upload_folder_dialog_adds_all_selected_folders(self, askpath, register):
            window = Mock()
            window.i18n.language = "pl"
            window.i18n.return_value = "Wybierz foldery do wysłania"

            gui.ChomikujGui._add_folders(window)

            register.assert_called_once_with("pl", gui.DIALOG_FOLDER_TRANSLATIONS_PL, window)
            window.tk.call.assert_called_once_with("msgcat::mclocale", "pl")
            askpath.assert_called_once_with(
                parent=window,
                select="dir",
                multiple=True,
                initialdir=os.getcwd(),
                title="Wybierz foldery do wysłania",
            )
            window._append_lines.assert_called_once_with(
                window.upload_text, ("/tmp/first", "/tmp/second")
            )


if __name__ == "__main__":
    unittest.main()
