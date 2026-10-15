"""Clean The CAM - window."""

import os
import sys
import traceback

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import core, dnc, settings

APP = "Clean The CAM"

BG = "#1e1e1e"
PANEL = "#141414"
FIELD = "#2b2b2b"
FG = "#e6e6e6"
DIM = "#9a9a9a"
OK = "#4ec26a"
BAD = "#e05a5a"
WARN = "#e0a83a"
ACCENT = "#4a9eda"

SEG_STYLE = {   # preview: colour, width, dash
    'rapid_off': ("#4a4a4a", 1, (2, 3)),
    'rapid_on': ("#c08a2a", 1, ()),
    'rapid_on_new': ("#ff5fd2", 1, (4, 2)),
    'etch': ("#4a9eda", 1, ()),
    'cut': ("#e05a5a", 2, ()),
}
LEGEND = [('etch', "engrave"), ('cut', "through-cut"),
          ('rapid_on', "beam-on rapid (cncKad)"), ('rapid_on_new', "beam-on rapid (joined)"),
          ('rapid_off', "beam-off rapid")]


class App:
    def __init__(self, root):
        self.root = root
        self.cfg = settings.load()
        root.title(f"{APP} {core.VERSION}")
        root.geometry("980x760")
        root.minsize(820, 600)
        root.configure(bg=BG)
        self._style()

        self.paths = []
        self.results = []          # (src, dst, Result, report)

        v = self.cfg
        self.target = tk.StringVar(value=v['target'])
        self.force_a0 = tk.BooleanVar(value=v['force_a0'])
        self.save_report = tk.BooleanVar(value=v['save_report'])
        self.stamp = tk.BooleanVar(value=v['stamp'])
        self.home = tk.StringVar(value=v['home'])
        self.home_x = tk.StringVar(value=v['home_x'])
        self.home_y = tk.StringVar(value=v['home_y'])
        self.end = tk.StringVar(value=v['end'])
        self.end_x = tk.StringVar(value=v['end_x'])
        self.end_y = tk.StringVar(value=v['end_y'])

        # --- file row
        bar = tk.Frame(root, bg=BG)
        bar.pack(fill="x", padx=14, pady=(14, 6))
        self._button(bar, "Select .ENC file(s)...", self.pick, accent=True).pack(side="left")
        self.lbl = tk.Label(bar, text="no file selected", bg=BG, fg=DIM,
                            font=("Segoe UI", 9), anchor="w")
        self.lbl.pack(side="left", padx=12, fill="x", expand=True)
        self._button(bar, "Settings", self.open_settings).pack(side="right")

        # --- options
        opts = tk.Frame(root, bg=BG)
        opts.pack(fill="x", padx=14, pady=(0, 4))
        r0 = tk.Frame(opts, bg=BG)
        r0.pack(fill="x", pady=2)
        self._label(r0, "Engrave condition:").pack(side="left")
        self._entry(r0, self.target, 7).pack(side="left", padx=(6, 18), ipady=3)
        for text, var in (("force pierce to A0", self.force_a0),
                          ("stamp header", self.stamp),
                          ("save report .txt", self.save_report)):
            self._check(r0, text, var).pack(side="left", padx=(0, 14))

        self._radio_row(opts, "Home (G92):", self.home,
                        [("keep", "Keep original"), ("bottom_left", "Bottom left (X10 Y10)"),
                         ("custom", "Custom")], self.home_x, self.home_y)
        self._radio_row(opts, "End position:", self.end,
                        [("home", "Return home (G50)"), ("start", "Back to start (G92 point)"),
                         ("custom", "Custom")], self.end_x, self.end_y)

        run_row = tk.Frame(root, bg=BG)
        run_row.pack(fill="x", padx=14, pady=(2, 2))
        self.run_btn = self._button(run_row, "Run", self.run, accent=True, state="disabled")
        self.run_btn.pack(side="right")
        self.banner = tk.Label(run_row, text="", bg=BG, fg=FG, anchor="w",
                               font=("Segoe UI", 11, "bold"))
        self.banner.pack(side="left", fill="x", expand=True)

        # --- report / preview
        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=14, pady=(4, 8))
        self.nb = nb
        rep = tk.Frame(nb, bg=PANEL)
        self.txt = tk.Text(rep, bg=PANEL, fg=FG, relief="flat", wrap="none",
                           font=("Consolas", 9), padx=12, pady=10, insertbackground=FG)
        sb = ttk.Scrollbar(rep, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.txt.pack(side="left", fill="both", expand=True)
        for tag, col in (("ok", OK), ("bad", BAD), ("warn", WARN), ("dim", DIM)):
            self.txt.tag_config(tag, foreground=col)
        nb.add(rep, text="  Report  ")

        pv = tk.Frame(nb, bg=PANEL)
        top = tk.Frame(pv, bg=PANEL)
        top.pack(fill="x", padx=8, pady=(6, 2))
        self.pick_preview = ttk.Combobox(top, state="readonly", width=48)
        self.pick_preview.bind("<<ComboboxSelected>>", lambda e: self.draw_preview())
        self.pick_preview.pack(side="left")
        leg = tk.Frame(pv, bg=PANEL)
        leg.pack(fill="x", padx=8, pady=(0, 4))
        self.layers = {}
        for key, text in LEGEND:
            col, wd, dash = SEG_STYLE[key]
            var = tk.BooleanVar(value=True)
            self.layers[key] = var
            tk.Checkbutton(leg, variable=var, command=self.draw_preview, bg=PANEL,
                           activebackground=PANEL, selectcolor=FIELD,
                           highlightthickness=0).pack(side="left", padx=(6, 0))
            c = tk.Canvas(leg, width=26, height=10, bg=PANEL, highlightthickness=0)
            c.create_line(2, 5, 24, 5, fill=col, width=max(wd, 2), dash=dash)
            c.pack(side="left", padx=(0, 2))
            tk.Label(leg, text=text, bg=PANEL, fg=DIM, font=("Segoe UI", 8)).pack(side="left")
        self.canvas = tk.Canvas(pv, bg=PANEL, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.draw_preview())
        nb.add(pv, text="  Preview  ")

        # --- footer
        foot = tk.Frame(root, bg=BG)
        foot.pack(fill="x", padx=14, pady=(0, 12))
        self.dnc_btn = self._button(foot, "Send to DNC", self.send_dnc, accent=True,
                                    state="disabled")
        self.dnc_btn.pack(side="left")
        self.copy_btn = self._button(foot, "Copy report", self.copy, state="disabled")
        self.copy_btn.pack(side="right")
        self.open_btn = self._button(foot, "Open output folder", self.reveal, state="disabled")
        self.open_btn.pack(side="right", padx=(0, 8))

        self.say("Select one or more cncKad .ENC files.\n\n"
                 "Fly-cut hatches are rewritten to the engrave condition, stroke-by-stroke\n"
                 "engraving is joined into one fly cut, and through-cuts are left alone.\n"
                 "Every output is replayed and checked against the original before it is\n"
                 "written. Nothing is written on FAIL.\n", "dim")
        root.protocol("WM_DELETE_WINDOW", self.close)

    # ---------- widgets ----------
    def _style(self):
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("TNotebook", background=BG, borderwidth=0)
        st.configure("TNotebook.Tab", background=FIELD, foreground=FG, padding=(10, 4))
        st.map("TNotebook.Tab", background=[("selected", PANEL)])

    def _button(self, parent, text, cmd, accent=False, state="normal"):
        b = tk.Button(parent, text=text, command=cmd, relief="flat", padx=14, pady=5,
                      font=("Segoe UI", 9, "bold" if accent else "normal"), cursor="hand2",
                      bg=ACCENT if accent else FIELD, fg="white" if accent else FG,
                      activebackground="#3a8ec8" if accent else "#3a3a3a",
                      activeforeground="white", disabledforeground="#6a6a6a", state=state)
        b._accent = accent
        if accent and state == "disabled":
            b.configure(bg=FIELD)
        return b

    def _label(self, parent, text):
        return tk.Label(parent, text=text, bg=BG, fg=FG, font=("Segoe UI", 9))

    def _entry(self, parent, var, width):
        return tk.Entry(parent, textvariable=var, width=width, bg=FIELD, fg=FG,
                        insertbackground=FG, relief="flat", justify="center",
                        font=("Consolas", 10), disabledbackground="#242424",
                        disabledforeground="#6a6a6a")

    def _check(self, parent, text, var):
        return tk.Checkbutton(parent, text=text, variable=var, bg=BG, fg=FG,
                              selectcolor=FIELD, activebackground=BG, activeforeground=FG,
                              font=("Segoe UI", 9), relief="flat", highlightthickness=0)

    def _radio_row(self, parent, title, var, choices, xvar, yvar):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=2)
        lab = self._label(row, title)
        lab.configure(width=13, anchor="w")
        lab.pack(side="left")
        for value, text in choices:
            tk.Radiobutton(row, text=text, value=value, variable=var, bg=BG, fg=FG,
                           selectcolor=FIELD, activebackground=BG, activeforeground=FG,
                           font=("Segoe UI", 9), highlightthickness=0,
                           command=lambda: self._sync_custom()).pack(side="left", padx=(0, 12))
        ex = self._entry(row, xvar, 8)
        ey = self._entry(row, yvar, 8)
        tk.Label(row, text="X", bg=BG, fg=DIM).pack(side="left")
        ex.pack(side="left", padx=(2, 8), ipady=2)
        tk.Label(row, text="Y", bg=BG, fg=DIM).pack(side="left")
        ey.pack(side="left", padx=2, ipady=2)
        if not hasattr(self, '_customs'):
            self._customs = []
        self._customs.append((var, ex, ey))
        self._sync_custom()

    def _sync_custom(self):
        for var, ex, ey in getattr(self, '_customs', []):
            st = "normal" if var.get() == "custom" else "disabled"
            ex.configure(state=st)
            ey.configure(state=st)

    def _enable(self, btn, on):
        if btn._accent:
            btn.configure(bg=ACCENT if on else FIELD, fg="white" if on else "#6a6a6a")
        btn.configure(state="normal" if on else "disabled")

    def say(self, text, tag=None):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", text, tag or ())
        self.txt.configure(state="disabled")

    # ---------- actions ----------
    def pick(self):
        ps = filedialog.askopenfilenames(
            title="Select cncKad .ENC file(s)", initialdir=self.cfg.get('last_dir') or None,
            filetypes=[("Amada NC files", "*.ENC *.enc"), ("All files", "*.*")])
        if not ps:
            return
        self.set_paths(list(ps))

    def set_paths(self, ps):
        self.paths = ps
        self.cfg['last_dir'] = os.path.dirname(ps[0])
        self.lbl.configure(text=os.path.basename(ps[0]) if len(ps) == 1
                           else f"{len(ps)} files selected", fg=FG)
        self._enable(self.run_btn, True)
        self.banner.configure(text="")
        self.say("Ready. Press Run.\n", "dim")

    def options(self, cleanup=None):
        return core.Options(
            target=self.target.get(), force_a0=self.force_a0.get(),
            home=self.home.get(), home_xy=(self.home_x.get(), self.home_y.get()),
            end=self.end.get(), end_xy=(self.end_x.get(), self.end_y.get()),
            stamp=self.stamp.get(), cleanup=cleanup)

    def ask_cleanup(self, src, r):
        """True = clean, False = leave as posted, None = skip this file."""
        msg = (f"{os.path.basename(src)}\n\n{core.describe_cleanup(r)}\n\n"
               f"Clean these up?\n\nYes = clean up    No = leave as posted    "
               f"Cancel = skip this file")
        return messagebox.askyesnocancel(f"{APP} - cleanup", msg, parent=self.root)

    def run(self):
        if not self.paths:
            return
        self.results = []
        for src in self.paths:
            self.results.append(self.run_one(src))
        self.show_results()

    def run_one(self, src):
        dst, rep_path = core.output_paths(src)
        try:
            r = core.process(src, self.options())
            if r.needs_decision:
                choice = self.ask_cleanup(src, r)
                if choice is None:
                    r.status = 'FAIL'
                    r.errors.append("Skipped - cleanup question cancelled.")
                else:
                    r = core.process(src, self.options(cleanup=choice))
            if r.ok:
                try:
                    core.write_output(dst, r.text)
                except OSError as ex:
                    r.status = 'FAIL'
                    r.errors.append(f"Could not write output: {ex}")
            report = core.format_report(src, dst, r)
        except Exception:
            r = core.Result(status='FAIL', errors=["Unexpected error - see below."])
            report = core.format_report(src, dst, r) + "\n" + traceback.format_exc()
        if self.save_report.get():
            try:
                with open(rep_path, "w", encoding="utf-8") as f:
                    f.write(report)
            except OSError:
                pass
        return (src, dst, r, report)

    def show_results(self):
        n_ok = sum(1 for *_, r, _ in self.results if r.status == 'PASS')
        n_warn = sum(1 for *_, r, _ in self.results if r.status == 'WARN')
        n_fail = len(self.results) - n_ok - n_warn
        if n_fail:
            text, col = f"  FAIL - {n_fail} of {len(self.results)} not written", BAD
        elif n_warn:
            text, col = "  PASS with warnings - review before running", WARN
        else:
            text, col = "  PASS - output written", OK
        if len(self.results) == 1 and not n_fail:
            text += f"  ->  {os.path.basename(self.results[0][1])}"
        self.banner.configure(text=text, fg=col)

        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        if len(self.results) > 1:
            self.txt.insert("end", "SUMMARY\n", ())
            for src, dst, r, _ in self.results:
                tag = {'PASS': 'ok', 'WARN': 'warn'}.get(r.status, 'bad')
                self.txt.insert("end", f"  {r.status:<5} {os.path.basename(src)}\n", (tag,))
            self.txt.insert("end", "\n")
        for src, dst, r, report in self.results:
            tag = {'PASS': 'ok', 'WARN': 'warn'}.get(r.status, 'bad')
            for line in report.splitlines():
                t = ()
                if line.strip().startswith("RESULT:"):
                    t = (tag,)
                elif "[ERROR]" in line:
                    t = ("bad",)
                elif "[WARNING]" in line:
                    t = ("warn",)
                elif "[NOTE]" in line:
                    t = ("dim",)
                self.txt.insert("end", line + "\n", t)
        self.txt.configure(state="disabled")

        names = [os.path.basename(s) for s, _, r, _ in self.results]
        self.pick_preview.configure(values=names)
        if names:
            self.pick_preview.current(0)
        self.draw_preview()
        self._enable(self.copy_btn, True)
        self._enable(self.open_btn, True)
        self._enable(self.dnc_btn, len(self.results) == 1 and self.results[0][2].ok)
        settings.save(self.current_cfg())

    def draw_preview(self):
        c = self.canvas
        c.delete("all")
        if not self.results:
            return
        i = max(self.pick_preview.current(), 0)
        r = self.results[i][2]
        pv = r.preview
        if not pv or not pv.get('segs'):
            c.create_text(20, 20, anchor="nw", fill=DIM, font=("Segoe UI", 10),
                          text="No preview - the file did not pass.")
            return
        ox, oy = pv.get('offset') or (0.0, 0.0)
        pts = [(x + ox, y + oy) for _, ps in pv['segs'] for x, y in ps]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        if pv.get('sheet'):
            w, h = pv['sheet']
            x0, y0, x1, y1 = min(x0, 0), min(y0, 0), max(x1, w), max(y1, h)
        W, H = max(c.winfo_width(), 50), max(c.winfo_height(), 50)
        pad = 24
        k = min((W - 2 * pad) / max(x1 - x0, 1e-6), (H - 2 * pad) / max(y1 - y0, 1e-6))
        tx = lambda x: pad + (x - x0) * k + ((W - 2 * pad) - (x1 - x0) * k) / 2
        ty = lambda y: H - pad - (y - y0) * k - ((H - 2 * pad) - (y1 - y0) * k) / 2
        if pv.get('sheet'):
            w, h = pv['sheet']
            c.create_rectangle(tx(0), ty(0), tx(w), ty(h), outline="#3a3a3a", dash=(3, 3))
            c.create_text(tx(0) + 4, ty(h) + 4, anchor="nw", fill="#5a5a5a",
                          font=("Segoe UI", 8), text=f"sheet {w:g} x {h:g}")
        order = ['rapid_off', 'rapid_on', 'etch', 'cut', 'rapid_on_new']
        for kind in order:
            if not self.layers[kind].get():
                continue
            col, wd, dash = SEG_STYLE[kind]
            for kk, ps in pv['segs']:
                if kk != kind:
                    continue
                flat = [v for x, y in ps for v in (tx(x + ox), ty(y + oy))]
                c.create_line(*flat, fill=col, width=wd, dash=dash)

    def send_dnc(self):
        if len(self.results) != 1:
            return
        src, dst, r, _ = self.results[0]
        if not r.ok:
            return
        if r.status == 'WARN' and not messagebox.askokcancel(
                f"{APP} - warnings",
                "This output passed WITH WARNINGS.\n\nHave you read them in the report?\n\n"
                "OK = load it into DNC", parent=self.root):
            return
        try:
            msg = dnc.load_into_dnc(dst, self.cfg)
            if not (self.cfg.get('dnc_progid') and self.cfg.get('dnc_method')):
                self.root.clipboard_clear()
                self.root.clipboard_append(os.path.abspath(dst))
            messagebox.showinfo(f"{APP} - DNC", msg, parent=self.root)
        except dnc.DncError as ex:
            messagebox.showerror(f"{APP} - DNC", str(ex), parent=self.root)

    def copy(self):
        text = "\n\n".join(rep for *_, rep in self.results)
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)

    def reveal(self):
        if not self.results:
            return
        d = os.path.dirname(os.path.abspath(self.results[0][1]))
        try:
            if sys.platform.startswith("win"):
                os.startfile(d)
            elif sys.platform == "darwin":
                os.system(f'open "{d}"')
            else:
                os.system(f'xdg-open "{d}"')
        except Exception:
            pass

    def open_settings(self):
        SettingsDialog(self)

    def current_cfg(self):
        c = self.cfg
        c.update(target=self.target.get(), force_a0=self.force_a0.get(),
                 save_report=self.save_report.get(), stamp=self.stamp.get(),
                 home=self.home.get(), home_x=self.home_x.get(), home_y=self.home_y.get(),
                 end=self.end.get(), end_x=self.end_x.get(), end_y=self.end_y.get())
        return c

    def close(self):
        settings.save(self.current_cfg())
        self.root.destroy()


class SettingsDialog:
    def __init__(self, app):
        self.app = app
        top = self.top = tk.Toplevel(app.root)
        top.title(f"{APP} - settings")
        top.configure(bg=BG)
        top.transient(app.root)
        cfg = app.cfg
        self.exe = tk.StringVar(value=cfg['dnc_exe'])
        self.progid = tk.StringVar(value=cfg['dnc_progid'])
        self.method = tk.StringVar(value=cfg['dnc_method'])

        frm = tk.Frame(top, bg=BG)
        frm.pack(fill="both", expand=True, padx=16, pady=14)
        tk.Label(frm, text="DNC program", bg=BG, fg=FG, font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, sticky="w")
        e = app._entry(frm, self.exe, 52)
        e.configure(justify="left")
        e.grid(row=1, column=0, sticky="we", ipady=3)
        app._button(frm, "Browse...", self.browse).grid(row=1, column=1, padx=(8, 0))
        tk.Label(frm, text="DNC automation (leave empty until known)", bg=BG, fg=FG,
                 font=("Segoe UI", 9, "bold")).grid(row=2, column=0, sticky="w", pady=(14, 0))
        for n, (text, var) in enumerate((("ProgID", self.progid),
                                         ("load method", self.method))):
            row = tk.Frame(frm, bg=BG)
            row.grid(row=3 + n, column=0, sticky="w", pady=2)
            tk.Label(row, text=text, bg=BG, fg=DIM, width=12, anchor="w").pack(side="left")
            en = app._entry(row, var, 30)
            en.configure(justify="left")
            en.pack(side="left", ipady=2)
        tk.Label(frm, text=("Without automation, Send to DNC opens DNC and copies the output\n"
                            "path to the clipboard. Nothing is ever sent to the machine\n"
                            "without you pressing send in DNC."),
                 bg=BG, fg=DIM, justify="left", font=("Segoe UI", 8)).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(12, 0))
        btns = tk.Frame(frm, bg=BG)
        btns.grid(row=6, column=0, columnspan=2, sticky="e", pady=(14, 0))
        app._button(btns, "Cancel", top.destroy).pack(side="right")
        app._button(btns, "Save", self.save, accent=True).pack(side="right", padx=(0, 8))

    def browse(self):
        p = filedialog.askopenfilename(parent=self.top, title="Locate DNC",
                                       filetypes=[("Programs", "*.exe"), ("All files", "*.*")])
        if p:
            self.exe.set(os.path.normpath(p))

    def save(self):
        self.app.cfg.update(dnc_exe=self.exe.get().strip(),
                            dnc_progid=self.progid.get().strip(),
                            dnc_method=self.method.get().strip())
        settings.save(self.app.cfg)
        self.top.destroy()


def main(paths=None):
    root = tk.Tk()
    app = App(root)
    if paths:
        app.set_paths(paths)
    root.mainloop()
