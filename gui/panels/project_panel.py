"""
gui/panels/project_panel.py
----------------------------
Project list panel — screen-reader accessible ListCtrl.

Controls:
  - ListCtrl (report mode) with columns: ID | Name | Stage | Descriptions | Updated
  - Buttons: New Project | Open | Delete | Refresh
  - Search field to filter projects
  - Double-click or Enter to open a project
"""

import wx
import wx.lib.mixins.listctrl as listmix
from datetime import datetime, timezone


def _time_ago(iso_str: str) -> str:
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        diff = datetime.now(timezone.utc) - dt
        s = int(diff.total_seconds())
        if s < 60:    return f"{s}s ago"
        if s < 3600:  return f"{s//60}m ago"
        if s < 86400: return f"{s//3600}h ago"
        return f"{s//86400}d ago"
    except Exception:
        return iso_str[:10]


STAGE_LABELS = {
    "created":         "Created",
    "uploaded":        "Video Uploaded",
    "described":       "Descriptions Generated",
    "audio_generated": "Audio Ready",
    "dubbed":          "Video Dubbed",
    "done":            "Done",
}


class ProjectPanel(wx.Panel):
    def __init__(self, parent, main_window):
        super().__init__(parent)
        self.main_window = main_window
        self._projects = []
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        sizer = wx.BoxSizer(wx.VERTICAL)

        # ── Header ────────────────────────────────────────────────────────────
        hdr = wx.StaticText(self, label="Projects")
        hdr.SetFont(hdr.GetFont().Bold().Scaled(1.3))
        sizer.Add(hdr, 0, wx.ALL, 8)

        # ── Search bar ────────────────────────────────────────────────────────
        search_row = wx.BoxSizer(wx.HORIZONTAL)
        lbl = wx.StaticText(self, label="&Search:")
        self.search_ctrl = wx.SearchCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.search_ctrl.SetHint("Filter projects…")
        self.search_ctrl.SetName("Project Search")
        self.search_ctrl.SetHelpText("Type to filter the project list")
        search_row.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 4)
        search_row.Add(self.search_ctrl, 1)
        sizer.Add(search_row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # ── Project list ──────────────────────────────────────────────────────
        self.list_ctrl = wx.ListCtrl(
            self,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_HRULES | wx.LC_VRULES,
        )
        self.list_ctrl.SetName("Project List")
        self.list_ctrl.SetHelpText(
            "List of all projects. Press Enter or double-click to open a project."
        )
        self.list_ctrl.InsertColumn(0, "ID",           width=80)
        self.list_ctrl.InsertColumn(1, "Name",         width=200)
        self.list_ctrl.InsertColumn(2, "Stage",        width=160)
        self.list_ctrl.InsertColumn(3, "Descriptions", width=110)
        self.list_ctrl.InsertColumn(4, "Video",        width=180)
        self.list_ctrl.InsertColumn(5, "Last Updated", width=100)
        sizer.Add(self.list_ctrl, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = wx.BoxSizer(wx.HORIZONTAL)

        self.btn_new    = wx.Button(self, label="&New Project")
        self.btn_open   = wx.Button(self, label="&Open Selected")
        self.btn_delete = wx.Button(self, label="&Delete Selected")
        self.btn_refresh = wx.Button(self, label="&Refresh List")

        self.btn_new.SetHelpText("Create a new audio description project")
        self.btn_open.SetHelpText("Open the selected project in the pipeline")
        self.btn_delete.SetHelpText("Delete the selected project from the database")
        self.btn_refresh.SetHelpText("Reload project list from database")

        btn_row.Add(self.btn_new,    0, wx.RIGHT, 4)
        btn_row.Add(self.btn_open,   0, wx.RIGHT, 4)
        btn_row.Add(self.btn_delete, 0, wx.RIGHT, 4)
        btn_row.Add(self.btn_refresh, 0)
        sizer.Add(btn_row, 0, wx.ALL, 8)

        # ── Info text ─────────────────────────────────────────────────────────
        self.info_label = wx.StaticText(self, label="")
        self.info_label.SetName("Project info")
        sizer.Add(self.info_label, 0, wx.LEFT | wx.BOTTOM, 8)

        self.SetSizer(sizer)

        # ── Events ────────────────────────────────────────────────────────────
        self.search_ctrl.Bind(wx.EVT_TEXT, self._on_search)
        self.search_ctrl.Bind(wx.EVT_SEARCHCTRL_SEARCH_BTN, self._on_search)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self._on_open)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_select)
        self.list_ctrl.Bind(wx.EVT_KEY_DOWN, self._on_list_key)
        self.btn_new.Bind(wx.EVT_BUTTON, self._on_new)
        self.btn_open.Bind(wx.EVT_BUTTON, self._on_open)
        self.btn_delete.Bind(wx.EVT_BUTTON, self._on_delete)
        self.btn_refresh.Bind(wx.EVT_BUTTON, lambda e: self.refresh())

    # ── Data ──────────────────────────────────────────────────────────────────

    def refresh(self):
        """Reload projects from DB and repopulate list."""
        try:
            from db import database as db
            self._projects = db.list_projects()
        except Exception as e:
            self._projects = []
            self.info_label.SetLabel(f"Error loading projects: {e}")
            return

        self._populate(self._projects)
        n = len(self._projects)
        self.info_label.SetLabel(f"{n} project{'s' if n != 1 else ''} in database.")

    def _populate(self, projects: list):
        self.list_ctrl.DeleteAllItems()
        for p in projects:
            desc_data = p.get("descriptions_data") or {}
            n_descs = len(desc_data.get("descriptions", []))
            video = p.get("video_path", "")
            video_name = str(video).split("/")[-1] if video else "—"

            idx = self.list_ctrl.InsertItem(self.list_ctrl.GetItemCount(), p["id"])
            self.list_ctrl.SetItem(idx, 1, p.get("name", ""))
            self.list_ctrl.SetItem(idx, 2, STAGE_LABELS.get(p.get("stage", ""), p.get("stage", "?")))
            self.list_ctrl.SetItem(idx, 3, str(n_descs) if n_descs else "—")
            self.list_ctrl.SetItem(idx, 4, video_name[:35])
            self.list_ctrl.SetItem(idx, 5, _time_ago(p.get("updated_at", "")))
            self.list_ctrl.SetItemData(idx, idx)  # used for sort later

    def _on_search(self, event):
        query = self.search_ctrl.GetValue().lower()
        filtered = [
            p for p in self._projects
            if query in p.get("name", "").lower()
            or query in p.get("id", "").lower()
        ]
        self._populate(filtered)

    def _on_select(self, event):
        idx = event.GetIndex()
        if idx >= 0:
            project = self._get_project_at(idx)
            if project:
                self.info_label.SetLabel(
                    f"Selected: {project.get('name','')}  |  "
                    f"Stage: {STAGE_LABELS.get(project.get('stage',''),'?')}"
                )

    def _on_list_key(self, event):
        if event.GetKeyCode() == wx.WXK_RETURN:
            self.open_selected_project()
        elif event.GetKeyCode() == wx.WXK_DELETE:
            self.delete_selected_project()
        else:
            event.Skip()

    def _get_project_at(self, idx: int):
        pid = self.list_ctrl.GetItemText(idx, 0)
        return next((p for p in self._projects if p["id"] == pid), None)

    def _get_selected_project(self):
        idx = self.list_ctrl.GetFirstSelected()
        if idx < 0:
            wx.MessageBox("No project selected.", "Selection Required", wx.OK | wx.ICON_INFORMATION)
            return None
        return self._get_project_at(idx)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _on_new(self, event):
        from gui.dialogs.project_dialog import ProjectDialog
        dlg = ProjectDialog(self, mode="create")
        if dlg.ShowModal() == wx.ID_OK:
            project = dlg.get_result()
            if project:
                self.refresh()
                self.main_window.load_project(project)
        dlg.Destroy()

    def _on_open(self, event=None):
        self.open_selected_project()

    def open_selected_project(self):
        project = self._get_selected_project()
        if project:
            self.main_window.load_project(project)

    def _on_delete(self, event):
        self.delete_selected_project()

    def delete_selected_project(self):
        project = self._get_selected_project()
        if not project:
            return
        ans = wx.MessageBox(
            f"Delete project '{project['name']}'?\n"
            "This removes the database entry but NOT the files on disk.",
            "Confirm Delete",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        )
        if ans == wx.YES:
            from db import database as db
            db.delete_project(project["id"])
            if self.main_window.current_project and \
               self.main_window.current_project["id"] == project["id"]:
                self.main_window.current_project = None
                self.main_window.set_project_status(None)
            self.refresh()
            self.main_window.set_status(f"Project '{project['name']}' deleted.")
