"""
gui/dialogs/project_dialog.py
------------------------------
Create project dialog — accessible wx.Dialog.
"""

import wx


class ProjectDialog(wx.Dialog):
    def __init__(self, parent, mode="create"):
        title = "Create New Project" if mode == "create" else "Edit Project"
        super().__init__(
            parent,
            title=title,
            size=(440, 250),
            style=wx.DEFAULT_DIALOG_STYLE,
        )
        self.mode    = mode
        self._result = None
        self._build_ui()

    def _build_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        g = wx.FlexGridSizer(rows=2, cols=2, vgap=10, hgap=8)
        g.AddGrowableCol(1)

        lbl_name = wx.StaticText(self, label="&Project Name:")
        self.name_ctrl = wx.TextCtrl(self)
        self.name_ctrl.SetName("Project name")
        self.name_ctrl.SetHelpText("Enter a descriptive name for this audio description project")

        lbl_desc = wx.StaticText(self, label="&Description (optional):")
        self.desc_ctrl = wx.TextCtrl(self, style=wx.TE_MULTILINE, size=(-1, 70))
        self.desc_ctrl.SetName("Project description")

        g.Add(lbl_name, 0, wx.ALIGN_CENTER_VERTICAL)
        g.Add(self.name_ctrl, 1, wx.EXPAND)
        g.Add(lbl_desc, 0, wx.ALIGN_TOP | wx.TOP, 4)
        g.Add(self.desc_ctrl, 1, wx.EXPAND)

        sizer.Add(g, 0, wx.EXPAND | wx.ALL, 12)

        btn_sizer = wx.StdDialogButtonSizer()
        self.btn_ok     = wx.Button(self, wx.ID_OK, "&Create Project" if self.mode == "create" else "&Save")
        self.btn_cancel = wx.Button(self, wx.ID_CANCEL, "&Cancel")
        self.btn_ok.SetDefault()
        btn_sizer.AddButton(self.btn_ok)
        btn_sizer.AddButton(self.btn_cancel)
        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.EXPAND | wx.ALL, 8)

        self.SetSizer(sizer)
        self.name_ctrl.SetFocus()

        self.btn_ok.Bind(wx.EVT_BUTTON, self._on_ok)

    def _on_ok(self, event):
        name = self.name_ctrl.GetValue().strip()
        if not name:
            wx.MessageBox("Project name cannot be empty.", "Validation Error", wx.OK | wx.ICON_WARNING)
            self.name_ctrl.SetFocus()
            return

        try:
            from db import database as db
            project = db.create_project(name, self.desc_ctrl.GetValue().strip())
            self._result = project
            self.EndModal(wx.ID_OK)
        except Exception as e:
            wx.MessageBox(f"Failed to create project:\n{e}", "Error", wx.OK | wx.ICON_ERROR)

    def get_result(self):
        return self._result
