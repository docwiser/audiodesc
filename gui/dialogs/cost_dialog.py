"""
gui/dialogs/cost_dialog.py
---------------------------
API cost report dialog.
"""

import wx


class CostDialog(wx.Dialog):
    def __init__(self, parent, project: dict):
        super().__init__(
            parent,
            title=f"API Cost Report — {project.get('name','')}",
            size=(680, 460),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.project = project
        self._build_ui()
        self._load_data()

    def _build_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        self.summary_lbl = wx.StaticText(self, label="")
        self.summary_lbl.SetFont(self.summary_lbl.GetFont().Bold())
        sizer.Add(self.summary_lbl, 0, wx.ALL, 10)

        self.list_ctrl = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_HRULES)
        self.list_ctrl.SetName("API usage breakdown")
        self.list_ctrl.InsertColumn(0, "Timestamp",   width=160)
        self.list_ctrl.InsertColumn(1, "Type",        width=190)
        self.list_ctrl.InsertColumn(2, "Model",       width=160)
        self.list_ctrl.InsertColumn(3, "In tokens",   width=90)
        self.list_ctrl.InsertColumn(4, "Out tokens",  width=90)
        self.list_ctrl.InsertColumn(5, "Cost (USD)",  width=90)
        sizer.Add(self.list_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        sizer.Add(wx.Button(self, wx.ID_CANCEL, label="&Close"), 0, wx.ALL | wx.ALIGN_RIGHT, 8)
        self.SetSizer(sizer)

    def _load_data(self):
        try:
            from core.cost_tracker import get_project_cost_summary
            summary = get_project_cost_summary(self.project["id"])
        except Exception as e:
            self.summary_lbl.SetLabel(f"Error loading cost data: {e}")
            return

        if not summary.get("total_calls"):
            self.summary_lbl.SetLabel("No API calls recorded yet.")
            return

        self.summary_lbl.SetLabel(
            f"Total: {summary['total_calls']} calls  |  "
            f"{summary['total_input']:,} input + {summary['total_output']:,} output tokens  |  "
            f"${summary['total_cost']:.4f} USD"
        )

        for u in summary.get("breakdown", []):
            idx = self.list_ctrl.InsertItem(self.list_ctrl.GetItemCount(), u["timestamp"][:19])
            self.list_ctrl.SetItem(idx, 1, u.get("call_type", ""))
            self.list_ctrl.SetItem(idx, 2, u.get("model", ""))
            self.list_ctrl.SetItem(idx, 3, f"{u.get('input_tokens',0):,}")
            self.list_ctrl.SetItem(idx, 4, f"{u.get('output_tokens',0):,}")
            self.list_ctrl.SetItem(idx, 5, f"${u.get('cost_usd',0):.4f}")
