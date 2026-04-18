"""
gui/main_window.py
------------------
AudioDesc Main Window.

ARCHITECTURE:
  HOME SCREEN (no project open)
    ├── Project list (ListCtrl, labelled)
    ├── New Project | Open | Delete | Refresh buttons
    └── Settings button (bottom-right)

  PROJECT VIEW (project open)
    ├── Project header bar (name, stage, Close Project button)
    ├── Section radio-group (wx.RadioBox — single Tab stop, arrow-key navigation)
    │     Pipeline · Descriptions · Player · Batch · Export
    └── Content panel (swaps to match selected radio)

ACCESSIBILITY COMPLIANCE:
  - RadioBox = single Tab stop; arrow keys switch sections (WCAG 2.1 §2.1.1)
  - Every interactive control paired with a visible StaticText label
  - wx.StaticBox groups logically related sections (maps to fieldset/legend)
  - All buttons have explicit Help text (F1 / tooltip)
  - Status bar announces state changes (3-field: project · stage · last action)
  - Thread-safe UI via wx.CallAfter()
  - Escape closes dialogs; Enter activates default button
  - No visual-only widgets

Keyboard shortcuts:
  Ctrl+N  New project          Ctrl+O  Open project
  Ctrl+W  Close project        Ctrl+Q  Quit
  F1      About                F5-F9   Pipeline steps 1-5
  Alt+1-5 Radio section jump   Ctrl+,  Settings
"""

import wx
from pathlib import Path

# ── Menu IDs ─────────────────────────────────────────────────────────────────
ID_NEW_PROJECT    = wx.NewIdRef()
ID_OPEN_PROJECT   = wx.NewIdRef()
ID_CLOSE_PROJECT  = wx.NewIdRef()
ID_DELETE_PROJECT = wx.NewIdRef()
ID_QUIT           = wx.NewIdRef()

ID_STEP_UPLOAD    = wx.NewIdRef()
ID_STEP_DESCRIBE  = wx.NewIdRef()
ID_STEP_AUDIO     = wx.NewIdRef()
ID_STEP_DUB       = wx.NewIdRef()
ID_STEP_EXPORT    = wx.NewIdRef()

ID_VALIDATE       = wx.NewIdRef()
ID_SMART_DUCK     = wx.NewIdRef()
ID_COST_REPORT    = wx.NewIdRef()
ID_CHECK_ENV      = wx.NewIdRef()
ID_SETTINGS       = wx.NewIdRef()
ID_ABOUT          = wx.NewIdRef()

# Section indices (matches radio button order)
SEC_PIPELINE     = 0
SEC_DESCRIPTIONS = 1
SEC_PLAYER       = 2
SEC_BATCH        = 3
SEC_EXPORT       = 4

SECTION_LABELS = ["Pipeline", "Descriptions", "Player", "Batch Queue", "Export"]


class MainWindow(wx.Frame):
    """
    Top-level frame. Switches between HomeView and ProjectView
    depending on whether a project is currently open.
    """

    def __init__(self, parent):
        super().__init__(
            parent,
            title="AudioDesc — AI Audio Description Generator",
            size=(1150, 800),
            style=wx.DEFAULT_FRAME_STYLE,
        )
        self.current_project = None

        self.SetName("AudioDesc Main Window")
        self.SetHelpText(
            "AudioDesc main window. "
            "Use the project list to open or create projects. "
            "Once a project is open, use the section radio buttons to navigate."
        )

        self._build_menu()
        self._build_statusbar()
        self._build_views()
        self._bind_events()

        self.Centre(wx.BOTH)
        self._show_home()

    # ── Menu ─────────────────────────────────────────────────────────────────

    def _build_menu(self):
        mb = wx.MenuBar()

        m = wx.Menu()
        m.Append(ID_NEW_PROJECT,    "&New Project\tCtrl+N",        "Create a new audio description project")
        m.Append(ID_OPEN_PROJECT,   "&Open Selected\tCtrl+O",      "Open the selected project")
        m.Append(ID_CLOSE_PROJECT,  "&Close Project\tCtrl+W",      "Close the current project and return to home")
        m.Append(ID_DELETE_PROJECT, "&Delete Selected",             "Delete selected project from database")
        m.AppendSeparator()
        m.Append(ID_SETTINGS,       "&Settings\tCtrl+,",           "Open application settings")
        m.AppendSeparator()
        m.Append(ID_QUIT,           "E&xit\tCtrl+Q",               "Quit AudioDesc")
        mb.Append(m, "&File")

        m = wx.Menu()
        m.Append(ID_STEP_UPLOAD,   "Step &1: Upload Video\tF5",         "Upload video to Gemini Files API")
        m.Append(ID_STEP_DESCRIBE, "Step &2: Generate Descriptions\tF6","Use AI to generate audio descriptions")
        m.Append(ID_STEP_AUDIO,    "Step &3: Generate Audio\tF7",       "Synthesize TTS audio clips")
        m.Append(ID_STEP_DUB,      "Step &4: Dub Video\tF8",            "Mix descriptions into video")
        m.Append(ID_STEP_EXPORT,   "Step &5: Export\tF9",               "Export dubbed video and subtitle files")
        mb.Append(m, "&Pipeline")

        m = wx.Menu()
        m.Append(ID_VALIDATE,   "&Validate Descriptions",   "Run validation report")
        m.Append(ID_SMART_DUCK, "&Smart Volume Ducking",    "Apply audio-analysis-based volume ducking")
        m.Append(ID_COST_REPORT,"API &Cost Report",         "View Gemini API usage and costs")
        m.AppendSeparator()
        m.Append(ID_CHECK_ENV,  "Check &Environment",       "Verify dependencies are installed")
        mb.Append(m, "&Tools")

        m = wx.Menu()
        m.Append(ID_ABOUT, "&About AudioDesc\tF1", "About AudioDesc")
        mb.Append(m, "&Help")

        self.SetMenuBar(mb)

    # ── Status bar ───────────────────────────────────────────────────────────

    def _build_statusbar(self):
        sb = self.CreateStatusBar(3)
        sb.SetStatusWidths([-3, -2, -2])
        sb.SetStatusText("No project open", 0)
        sb.SetStatusText("Stage: —", 1)
        sb.SetStatusText("Ready", 2)
        sb.SetName("Application Status Bar")
        sb.SetHelpText("Shows current project, pipeline stage, and last action")
        self.statusbar = sb

    def set_status(self, msg: str, field: int = 2):
        wx.CallAfter(self.statusbar.SetStatusText, msg, field)

    def set_project_status(self, project=None):
        if not project:
            wx.CallAfter(self.statusbar.SetStatusText, "No project open", 0)
            wx.CallAfter(self.statusbar.SetStatusText, "Stage: —", 1)
        else:
            wx.CallAfter(self.statusbar.SetStatusText, f"Project: {project.get('name','?')}", 0)
            wx.CallAfter(self.statusbar.SetStatusText, f"Stage: {project.get('stage','?')}", 1)

    # ── Views ─────────────────────────────────────────────────────────────────

    def _build_views(self):
        self._main_sizer = wx.BoxSizer(wx.VERTICAL)

        self.home_panel   = HomeView(self, self)
        self.project_view = ProjectView(self, self)
        self.project_view.Hide()

        self._main_sizer.Add(self.home_panel,   1, wx.EXPAND)
        self._main_sizer.Add(self.project_view, 1, wx.EXPAND)
        self.SetSizer(self._main_sizer)

    def _show_home(self):
        self.home_panel.Show()
        self.project_view.Hide()
        self.home_panel.refresh()
        self._main_sizer.Layout()
        wx.CallAfter(self.home_panel.SetFocus)

    def _show_project(self):
        self.home_panel.Hide()
        self.project_view.Show()
        self._main_sizer.Layout()
        wx.CallAfter(self.project_view.focus_radio)

    # ── Event binding ─────────────────────────────────────────────────────────

    def _bind_events(self):
        binds = [
            (ID_NEW_PROJECT,    self._on_new_project),
            (ID_OPEN_PROJECT,   self._on_open_project),
            (ID_CLOSE_PROJECT,  self._on_close_project),
            (ID_DELETE_PROJECT, self._on_delete_project),
            (ID_QUIT,           lambda e: self.Close()),
            (ID_SETTINGS,       self._on_settings),
            (ID_STEP_UPLOAD,    lambda e: self._pipeline_step(1)),
            (ID_STEP_DESCRIBE,  lambda e: self._pipeline_step(2)),
            (ID_STEP_AUDIO,     lambda e: self._pipeline_step(3)),
            (ID_STEP_DUB,       lambda e: self._pipeline_step(4)),
            (ID_STEP_EXPORT,    lambda e: self._pipeline_step(5)),
            (ID_VALIDATE,       self._on_validate),
            (ID_SMART_DUCK,     self._on_smart_duck),
            (ID_COST_REPORT,    self._on_cost_report),
            (ID_CHECK_ENV,      self._on_check_env),
            (ID_ABOUT,          self._on_about),
        ]
        for mid, handler in binds:
            self.Bind(wx.EVT_MENU, handler, id=mid)
        self.Bind(wx.EVT_CLOSE, self._on_close)

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _require_project(self, action: str) -> bool:
        if not self.current_project:
            wx.MessageBox(
                f"Please open a project before running '{action}'.",
                "No Project Open", wx.OK | wx.ICON_INFORMATION,
            )
            return False
        return True

    def _on_new_project(self, event):
        from gui.dialogs.project_dialog import ProjectDialog
        dlg = ProjectDialog(self, mode="create")
        if dlg.ShowModal() == wx.ID_OK:
            project = dlg.get_result()
            if project:
                self.home_panel.refresh()
                self.load_project(project)
        dlg.Destroy()

    def _on_open_project(self, event):
        self.home_panel.open_selected_project()

    def _on_close_project(self, event):
        self.close_project()

    def _on_delete_project(self, event):
        self.home_panel.delete_selected_project()

    def _on_settings(self, event):
        from gui.dialogs.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self)
        dlg.ShowModal()
        dlg.Destroy()

    def _pipeline_step(self, n: int):
        if self._require_project(f"Step {n}"):
            self.project_view.show_section(SEC_PIPELINE)
            self.project_view.panel_pipeline.run_step(n)

    def _on_validate(self, event):
        if self._require_project("Validate Descriptions"):
            from gui.dialogs.validation_dialog import ValidationDialog
            dlg = ValidationDialog(self, self.current_project)
            dlg.ShowModal(); dlg.Destroy()

    def _on_smart_duck(self, event):
        if self._require_project("Smart Volume Ducking"):
            self.project_view.panel_pipeline.apply_smart_ducking()

    def _on_cost_report(self, event):
        if self._require_project("Cost Report"):
            from gui.dialogs.cost_dialog import CostDialog
            dlg = CostDialog(self, self.current_project)
            dlg.ShowModal(); dlg.Destroy()

    def _on_check_env(self, event):
        from gui.dialogs.env_check_dialog import EnvCheckDialog
        dlg = EnvCheckDialog(self)
        dlg.ShowModal(); dlg.Destroy()

    def _on_about(self, event):
        from gui.dialogs.about_dialog import AboutDialog
        dlg = AboutDialog(self)
        dlg.ShowModal(); dlg.Destroy()

    def _on_close(self, event):
        if wx.MessageBox(
            "Quit AudioDesc?", "Confirm Exit",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        ) == wx.YES:
            try: self.project_view.panel_player.stop()
            except Exception: pass
            event.Skip()

    # ── Public API ────────────────────────────────────────────────────────────

    def load_project(self, project: dict):
        """Open a project and switch to the project view."""
        self.current_project = project
        self.set_project_status(project)
        self.project_view.load_project(project)
        self._show_project()
        self.set_status(f"Opened: {project.get('name', '?')}")

    def close_project(self):
        """Return to home screen."""
        try: self.project_view.panel_player.stop()
        except Exception: pass
        self.current_project = None
        self.set_project_status(None)
        self.set_status("Project closed.")
        self._show_home()

    def refresh_current_project(self):
        if not self.current_project:
            return
        from db import database as db
        project = db.get_project(self.current_project["id"])
        if project:
            self.current_project = project
            self.set_project_status(project)
            self.project_view.load_project(project)


# ══════════════════════════════════════════════════════════════════════════════
#  HOME VIEW
# ══════════════════════════════════════════════════════════════════════════════

class HomeView(wx.Panel):
    """
    Home screen: project list + action buttons + settings.

    Accessibility notes:
      - SearchCtrl has an explicit StaticText label directly before it in the
        tab order and in the StaticBoxSizer label (equivalent to <label for>)
      - ListCtrl: column headers announced by NVDA/JAWS as column names
      - info_label updates on selection → equivalent to aria-live="polite"
      - btn_settings at bottom-right, also in menu as Ctrl+,
    """

    STAGE_LABELS = {
        "created":         "Created",
        "uploaded":        "Video Uploaded",
        "described":       "Descriptions Generated",
        "audio_generated": "Audio Ready",
        "dubbed":          "Video Dubbed",
        "done":            "Complete",
    }

    def __init__(self, parent, main_window):
        super().__init__(parent)
        self.main_window = main_window
        self._projects = []
        self._build_ui()

    def _build_ui(self):
        root = wx.BoxSizer(wx.VERTICAL)

        # ── Page heading ──────────────────────────────────────────────────────
        h1 = wx.StaticText(self, label="AudioDesc — Projects")
        h1.SetFont(h1.GetFont().Bold().Scaled(1.4))
        h1.SetName("Page heading: AudioDesc Projects")
        root.Add(h1, 0, wx.ALL, 12)

        # ── Search (StaticBox provides the group label; StaticText provides
        #    the per-control label immediately before the input) ───────────────
        search_box = wx.StaticBox(self, label="Filter Projects")
        search_sizer = wx.StaticBoxSizer(search_box, wx.HORIZONTAL)

        lbl_search = wx.StaticText(self, label="Search by name or ID:")
        lbl_search.SetName("Search label")
        self.search_ctrl = wx.SearchCtrl(self, style=wx.TE_PROCESS_ENTER)
        self.search_ctrl.SetHint("Type to filter…")
        self.search_ctrl.SetName("Search projects by name or ID. Results update as you type.")
        self.search_ctrl.SetHelpText(
            "Type to filter the project list below. "
            "Results update immediately. Press Escape or the X button to clear."
        )

        search_sizer.Add(lbl_search,       0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        search_sizer.Add(self.search_ctrl, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 6)
        root.Add(search_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # ── Project list ──────────────────────────────────────────────────────
        list_box = wx.StaticBox(
            self,
            label="Projects  (arrow keys to navigate · Enter or double-click to open · Delete to delete)"
        )
        list_sizer = wx.StaticBoxSizer(list_box, wx.VERTICAL)

        self.list_ctrl = wx.ListCtrl(
            self,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL | wx.LC_HRULES | wx.LC_VRULES,
        )
        self.list_ctrl.SetName(
            "Project list. "
            "Columns: ID, Name, Stage, Number of descriptions, Video file, Last updated. "
            "Press Enter or double-click to open a project. Press Delete to delete."
        )
        self.list_ctrl.SetHelpText(
            "Use Up/Down arrow keys to navigate. "
            "Press Enter or double-click to open the selected project. "
            "Press Delete to delete. "
            "Type in the search box above to filter."
        )
        cols = [
            ("ID",               70),
            ("Name",            220),
            ("Stage",           155),
            ("Descriptions",    100),
            ("Video File",      200),
            ("Last Updated",    100),
        ]
        for i, (name, w) in enumerate(cols):
            self.list_ctrl.InsertColumn(i, name, width=w)

        list_sizer.Add(self.list_ctrl, 1, wx.EXPAND | wx.ALL, 4)
        root.Add(list_sizer, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # ── Action buttons ────────────────────────────────────────────────────
        btn_box = wx.StaticBox(self, label="Project Actions")
        btn_sizer = wx.StaticBoxSizer(btn_box, wx.HORIZONTAL)

        self.btn_new     = wx.Button(self, label="&New Project")
        self.btn_open    = wx.Button(self, label="&Open Selected")
        self.btn_delete  = wx.Button(self, label="&Delete Selected")
        self.btn_refresh = wx.Button(self, label="&Refresh List")

        self.btn_new.SetHelpText(
            "Create a new audio description project. "
            "You will be asked for a project name. (Ctrl+N)"
        )
        self.btn_open.SetHelpText(
            "Open the project currently selected in the list above. "
            "You can also press Enter or double-click in the list. (Ctrl+O)"
        )
        self.btn_delete.SetHelpText(
            "Permanently delete the selected project from the database. "
            "Files on disk are NOT deleted. You will be asked to confirm."
        )
        self.btn_refresh.SetHelpText(
            "Reload the project list from the database."
        )

        for btn in [self.btn_new, self.btn_open, self.btn_delete, self.btn_refresh]:
            btn_sizer.Add(btn, 0, wx.ALL, 4)

        btn_sizer.AddStretchSpacer()

        self.btn_settings = wx.Button(self, label="⚙ &Settings")
        self.btn_settings.SetHelpText(
            "Open application settings: API keys, default model, default TTS engine, "
            "environment check. (Ctrl+,)"
        )
        btn_sizer.Add(self.btn_settings, 0, wx.ALL, 4)
        root.Add(btn_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # ── Selection info (live-region equivalent) ───────────────────────────
        self.info_label = wx.StaticText(self, label="No project selected.")
        self.info_label.SetName("Project selection info")
        self.info_label.SetHelpText(
            "Describes the currently selected project and how many are in the list."
        )
        root.Add(self.info_label, 0, wx.LEFT | wx.BOTTOM, 12)

        self.SetSizer(root)

        # ── Events ────────────────────────────────────────────────────────────
        self.search_ctrl.Bind(wx.EVT_TEXT, self._on_search)
        self.search_ctrl.Bind(wx.EVT_SEARCHCTRL_CANCEL_BTN, self._on_search_clear)
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, lambda e: self.open_selected_project())
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_SELECTED,  self._on_select)
        self.list_ctrl.Bind(wx.EVT_KEY_DOWN,             self._on_list_key)
        self.btn_new.Bind(wx.EVT_BUTTON,      self._on_new)
        self.btn_open.Bind(wx.EVT_BUTTON,     lambda e: self.open_selected_project())
        self.btn_delete.Bind(wx.EVT_BUTTON,   lambda e: self.delete_selected_project())
        self.btn_refresh.Bind(wx.EVT_BUTTON,  lambda e: self.refresh())
        self.btn_settings.Bind(wx.EVT_BUTTON, self._on_settings)

    # ── Data ──────────────────────────────────────────────────────────────────

    def refresh(self):
        try:
            from db import database as db
            self._projects = db.list_projects()
        except Exception as e:
            self._projects = []
            self.info_label.SetLabel(f"Error loading projects: {e}")
            return
        self._populate(self._projects)
        n = len(self._projects)
        self.info_label.SetLabel(
            f"{n} project{'s' if n != 1 else ''} in database. "
            "Use arrow keys to navigate the list. Press Enter to open."
        )

    def _populate(self, projects: list):
        self.list_ctrl.DeleteAllItems()
        from datetime import datetime, timezone

        def time_ago(iso):
            if not iso: return "—"
            try:
                dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
                if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
                s = int((datetime.now(timezone.utc) - dt).total_seconds())
                if s < 60:    return f"{s}s ago"
                if s < 3600:  return f"{s//60}m ago"
                if s < 86400: return f"{s//3600}h ago"
                return f"{s//86400}d ago"
            except Exception: return iso[:10]

        for p in projects:
            desc_data  = p.get("descriptions_data") or {}
            n_descs    = len(desc_data.get("descriptions", []))
            video      = p.get("video_path", "")
            video_name = Path(video).name if video else "—"
            stage_lbl  = self.STAGE_LABELS.get(p.get("stage", ""), p.get("stage", "?"))

            idx = self.list_ctrl.InsertItem(self.list_ctrl.GetItemCount(), str(p["id"]))
            self.list_ctrl.SetItem(idx, 1, p.get("name", ""))
            self.list_ctrl.SetItem(idx, 2, stage_lbl)
            self.list_ctrl.SetItem(idx, 3, str(n_descs) if n_descs else "—")
            self.list_ctrl.SetItem(idx, 4, video_name[:40])
            self.list_ctrl.SetItem(idx, 5, time_ago(p.get("updated_at", "")))

    def _on_search(self, event):
        q = self.search_ctrl.GetValue().lower().strip()
        filtered = [
            p for p in self._projects
            if q in p.get("name", "").lower() or q in str(p.get("id", "")).lower()
        ] if q else self._projects
        self._populate(filtered)
        n = len(filtered)
        self.info_label.SetLabel(
            f"{n} project{'s' if n != 1 else ''} match '{self.search_ctrl.GetValue()}'."
            if q else f"{len(self._projects)} projects total."
        )

    def _on_search_clear(self, event):
        self.search_ctrl.Clear()
        self._populate(self._projects)
        self.info_label.SetLabel(f"{len(self._projects)} projects total. Search cleared.")

    def _on_select(self, event):
        p = self._get_project_at(event.GetIndex())
        if p:
            stage = self.STAGE_LABELS.get(p.get("stage", ""), "?")
            self.info_label.SetLabel(
                f"Selected: {p.get('name', '')}  ·  Stage: {stage}  ·  "
                "Press Enter or click Open Selected to open."
            )

    def _on_list_key(self, event):
        kc = event.GetKeyCode()
        if kc == wx.WXK_RETURN:
            self.open_selected_project()
        elif kc == wx.WXK_DELETE:
            self.delete_selected_project()
        else:
            event.Skip()

    def _get_project_at(self, idx: int):
        pid = self.list_ctrl.GetItemText(idx, 0)
        return next((p for p in self._projects if str(p["id"]) == pid), None)

    def _get_selected_project(self):
        idx = self.list_ctrl.GetFirstSelected()
        if idx < 0:
            wx.MessageBox(
                "Please select a project from the list first.\n"
                "Use the arrow keys to navigate the list, then press Enter.",
                "No Project Selected", wx.OK | wx.ICON_INFORMATION,
            )
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

    def open_selected_project(self):
        p = self._get_selected_project()
        if p:
            self.main_window.load_project(p)

    def delete_selected_project(self):
        p = self._get_selected_project()
        if not p:
            return
        ans = wx.MessageBox(
            f"Delete project '{p['name']}'?\n\n"
            "This removes the database record but does NOT delete files on disk.",
            "Confirm Delete",
            wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION,
        )
        if ans == wx.YES:
            from db import database as db
            db.delete_project(p["id"])
            if (self.main_window.current_project and
                    self.main_window.current_project["id"] == p["id"]):
                self.main_window.close_project()
            self.refresh()
            self.main_window.set_status(f"Deleted project: {p['name']}")

    def _on_settings(self, event):
        from gui.dialogs.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self)
        dlg.ShowModal()
        dlg.Destroy()


# ══════════════════════════════════════════════════════════════════════════════
#  PROJECT VIEW — header + radio-group + content panels
# ══════════════════════════════════════════════════════════════════════════════

class ProjectView(wx.Panel):
    """
    Shown when a project is open.

    Layout:
      ┌─ Current Project (StaticBox) ──────────────────────────────────┐
      │  Name: Foo  ·  Stage: Video Uploaded    [← Back to Projects]   │
      └────────────────────────────────────────────────────────────────┘
      ┌─ Section (wx.RadioBox) ────────────────────────────────────────┐
      │  (•) Pipeline  ( ) Descriptions  ( ) Player  ( ) Batch  ( ) Export │
      └────────────────────────────────────────────────────────────────┘
      ┌─ [active content panel] ───────────────────────────────────────┐
      │  ...                                                            │
      └────────────────────────────────────────────────────────────────┘

    wx.RadioBox accessibility:
      - Single Tab stop — doesn't fragment the focus ring
      - Left/Right or Up/Down arrow keys move between options
      - NVDA announces: "Section, Pipeline, radio button, 1 of 5"
      - JAWS announces: "Pipeline  1 of 5  Section group"
      - Orca announces: "Pipeline radio button"
      - Alt+1-5 jump directly via EVT_CHAR_HOOK (backup shortcut)
    """

    def __init__(self, parent, main_window):
        super().__init__(parent)
        self.main_window     = main_window
        self.current_section = SEC_PIPELINE
        self._panels         = {}
        self._build_ui()

    def _build_ui(self):
        root = wx.BoxSizer(wx.VERTICAL)

        # ── Project header ────────────────────────────────────────────────────
        hdr_box    = wx.StaticBox(self, label="Current Project")
        hdr_sizer  = wx.StaticBoxSizer(hdr_box, wx.HORIZONTAL)

        lbl_name_key  = wx.StaticText(self, label="Name:")
        lbl_name_key.SetFont(lbl_name_key.GetFont().Bold())
        self.lbl_name = wx.StaticText(self, label="—")
        self.lbl_name.SetName("Project name value")

        lbl_stage_key  = wx.StaticText(self, label="Stage:")
        lbl_stage_key.SetFont(lbl_stage_key.GetFont().Bold())
        self.lbl_stage = wx.StaticText(self, label="—")
        self.lbl_stage.SetName("Project stage value")

        div = wx.StaticLine(self, style=wx.LI_VERTICAL)

        hdr_sizer.Add(lbl_name_key,  0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 8)
        hdr_sizer.Add(self.lbl_name, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 6)
        hdr_sizer.Add(div,           0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        hdr_sizer.Add(lbl_stage_key, 0, wx.ALIGN_CENTER_VERTICAL)
        hdr_sizer.Add(self.lbl_stage,0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT | wx.RIGHT, 6)
        hdr_sizer.AddStretchSpacer()

        self.btn_back = wx.Button(self, label="← &Back to Projects")
        self.btn_back.SetName("Close project and return to projects list")
        self.btn_back.SetHelpText(
            "Close this project and return to the home screen. (Ctrl+W)"
        )
        hdr_sizer.Add(self.btn_back, 0, wx.ALL, 4)
        root.Add(hdr_sizer, 0, wx.EXPAND | wx.ALL, 8)

        # ── Section radio-group ───────────────────────────────────────────────
        self.radio = wx.RadioBox(
            self,
            label="Section — use arrow keys to switch",
            choices=SECTION_LABELS,
            majorDimension=len(SECTION_LABELS),
            style=wx.RA_SPECIFY_COLS,
        )
        self.radio.SetName(
            "Section selector. "
            "Use Left and Right arrow keys to switch between sections. "
            "The content area below updates immediately."
        )
        self.radio.SetHelpText(
            "Select which section to display. "
            "Pipeline: run pipeline steps. "
            "Descriptions: review and edit descriptions. "
            "Player: play audio and video. "
            "Batch Queue: manage batch jobs. "
            "Export: export outputs. "
            "Use arrow keys or Alt+1 through Alt+5 to switch sections."
        )
        item_tips = [
            "Run pipeline steps: upload video, generate descriptions, generate audio, dub video, export",
            "Review and edit individual timestamped audio descriptions",
            "Play original or dubbed video and individual description audio clips",
            "Manage batch processing queue for multiple projects",
            "Export dubbed video, subtitle files, and audio tracks",
        ]
        for i, tip in enumerate(item_tips):
            self.radio.SetItemHelpText(i, tip)

        root.Add(self.radio, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        # ── Content area ──────────────────────────────────────────────────────
        self.content_panel = wx.Panel(self)
        self.content_panel.SetName("Section content area")
        self.content_sizer = wx.BoxSizer(wx.VERTICAL)
        self.content_panel.SetSizer(self.content_sizer)
        root.Add(self.content_panel, 1, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)

        self.SetSizer(root)

        # ── Events ────────────────────────────────────────────────────────────
        self.radio.Bind(wx.EVT_RADIOBOX, self._on_radio)
        self.btn_back.Bind(wx.EVT_BUTTON, lambda e: self.main_window.close_project())
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

    def _on_char_hook(self, event):
        kc = event.GetKeyCode()
        if event.AltDown() and ord('1') <= kc <= ord('5'):
            self.show_section(kc - ord('1'))
            return
        event.Skip()

    # ── Panel management ──────────────────────────────────────────────────────

    def _get_panel(self, section: int):
        """Lazily instantiate section panels."""
        if section in self._panels:
            return self._panels[section]

        parent = self.content_panel
        mw     = self.main_window

        if section == SEC_PIPELINE:
            from gui.panels.pipeline_panel import PipelinePanel
            panel = PipelinePanel(parent, mw)
        elif section == SEC_DESCRIPTIONS:
            from gui.panels.description_panel import DescriptionPanel
            panel = DescriptionPanel(parent, mw)
        elif section == SEC_PLAYER:
            from gui.panels.player_panel import PlayerPanel
            panel = PlayerPanel(parent, mw)
        elif section == SEC_BATCH:
            from gui.panels.batch_panel import BatchPanel
            panel = BatchPanel(parent, mw)
        elif section == SEC_EXPORT:
            from gui.panels.export_panel import ExportPanel
            panel = ExportPanel(parent, mw)
        else:
            panel = wx.Panel(parent)

        panel.Hide()
        self.content_sizer.Add(panel, 1, wx.EXPAND)
        self._panels[section] = panel

        # Load project if we already have one
        if self.main_window.current_project and hasattr(panel, "load_project"):
            try:
                panel.load_project(self.main_window.current_project)
            except Exception:
                pass

        return panel

    # Convenience properties so main_window can address panels directly
    @property
    def panel_pipeline(self):     return self._get_panel(SEC_PIPELINE)
    @property
    def panel_descriptions(self): return self._get_panel(SEC_DESCRIPTIONS)
    @property
    def panel_player(self):       return self._get_panel(SEC_PLAYER)
    @property
    def panel_batch(self):        return self._get_panel(SEC_BATCH)
    @property
    def panel_export(self):       return self._get_panel(SEC_EXPORT)

    def show_section(self, section: int):
        """Switch the visible content panel and sync the radio button."""
        if self.current_section in self._panels:
            self._panels[self.current_section].Hide()

        self.current_section = section
        self.radio.SetSelection(section)

        panel = self._get_panel(section)
        panel.Show()
        self.content_sizer.Layout()
        self.content_panel.Layout()

        self.main_window.set_status(f"Section: {SECTION_LABELS[section]}")
        wx.CallAfter(panel.SetFocus)

    def _on_radio(self, event):
        self.show_section(event.GetInt())

    def focus_radio(self):
        self.radio.SetFocus()

    # ── Project loading ────────────────────────────────────────────────────────

    STAGE_LABELS = {
        "created":         "Created",
        "uploaded":        "Video Uploaded",
        "described":       "Descriptions Generated",
        "audio_generated": "Audio Ready",
        "dubbed":          "Video Dubbed",
        "done":            "Complete",
    }

    def load_project(self, project: dict):
        self.lbl_name.SetLabel(project.get("name", "?"))
        self.lbl_stage.SetLabel(
            self.STAGE_LABELS.get(project.get("stage", ""), project.get("stage", "?"))
        )
        # Refresh already-instantiated panels
        for sec, panel in self._panels.items():
            if hasattr(panel, "load_project"):
                try:
                    panel.load_project(project)
                except Exception:
                    pass
        self.show_section(SEC_PIPELINE)
        self.Layout()
