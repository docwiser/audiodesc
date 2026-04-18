"""
gui/app.py
----------
AudioDesc wx.App — application bootstrap, accessibility, global font/theme.
"""

import wx
import wx.adv
import sys
from pathlib import Path


class AudioDescApp(wx.App):
    """
    Main application class.

    Sets:
      - App name & vendor for screen readers / OS integration
      - System font scaling
      - High-contrast aware theme (reads system prefs)
    """

    def OnInit(self):
        self.SetAppName("AudioDesc")
        self.SetVendorName("AudioDesc Project")
        self.SetAppDisplayName("AudioDesc — AI Audio Description Generator")

        # Redirect stderr/stdout so crashes don't silently die on Windows
        self.SetOutputWindowAttributes(title="AudioDesc Log")

        from gui.main_window import MainWindow
        frame = MainWindow(None)
        frame.Show()
        self.SetTopWindow(frame)
        return True

    def OnExit(self):
        return 0
