from __future__ import annotations
from typing import Dict, Optional
import json
from PySide6 import QtCore, QtGui, QtWidgets
from .core.logic import Circuit, COMPONENT_REGISTRY, SwitchBinary, SwitchTernary, Probe
from .core.io import load_circuit_from_json, dump_circuit_to_json

PORT_RADIUS = 6
COMP_WIDTH = 100
COMP_HEIGHT = 50


class Canvas(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        # state
        self.circuit = Circuit()
        self.positions: Dict[str, QtCore.QPointF] = {}
        self.port_map: Dict[tuple[str, str], QtCore.QRectF] = {}
        self.dragging: Optional[str] = None
        self.drag_offset: Optional[QtCore.QPointF] = None
        self.wire_start: Optional[tuple[str, str]] = None
        self.pending_add: Optional[str] = None
        self.selected: Optional[str] = None
        self.unwired: Dict[str, list[str]] = {}

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(1200, 800)

    def add_component(self, ctype: str, pos: QtCore.QPointF):
        cid = f"{ctype}_{len(self.circuit.components)+1}"
        cls = COMPONENT_REGISTRY[ctype]
        comp = cls(cid, 0) if ctype.startswith("Switch") else cls(cid)
        self.circuit.add(comp)
        self.positions[cid] = QtCore.QPointF(pos)
        self.update()

    def set_add_mode(self, ctype: Optional[str]):
        self.pending_add = ctype
        self.setCursor(QtCore.Qt.CrossCursor if ctype else QtCore.Qt.ArrowCursor)

    def load_json(self, text: str):
        try:
            data = json.loads(text)
        except Exception:
            data = {"components": [], "wires": []}
        self.circuit = load_circuit_from_json(text)
        # place with saved positions if present
        x, y = 100, 100
        saved: Dict[str, QtCore.QPointF] = {}
        for comp in data.get("components", []):
            pos = comp.get("position") or {}
            if comp.get("id") and "x" in pos and "y" in pos:
                saved[comp["id"]] = QtCore.QPointF(float(pos["x"]), float(pos["y"]))
        self.positions.clear()
        for cid in self.circuit.components.keys():
            if cid in saved:
                self.positions[cid] = saved[cid]
            else:
                self.positions[cid] = QtCore.QPointF(x, y)
                x += 160
                if x > 1000:
                    x = 100
                    y += 120
        # validate on load
        self.validate_wiring()
        self.update()

    def auto_arrange(self):
        # Build graph
        comps = list(self.circuit.components.keys())
        out_edges: Dict[str, set[str]] = {c: set() for c in comps}
        in_deg: Dict[str, int] = {c: 0 for c in comps}
        for w in self.circuit.wires:
            if w.src_comp in out_edges and w.dst_comp in in_deg:
                if w.dst_comp not in out_edges[w.src_comp]:
                    out_edges[w.src_comp].add(w.dst_comp)
                    in_deg[w.dst_comp] += 1
        # Kahn's algorithm to assign levels
        from collections import deque, defaultdict
        q = deque([c for c, d in in_deg.items() if d == 0])
        level: Dict[str, int] = {c: 0 for c in q}
        while q:
            u = q.popleft()
            for v in out_edges[u]:
                in_deg[v] -= 1
                if in_deg[v] == 0:
                    level[v] = max(level.get(v, 0), level.get(u, 0) + 1)
                    q.append(v)
        # any remaining nodes (cycle): place after max level
        max_lvl = max(level.values(), default=0)
        for c, d in in_deg.items():
            if d > 0 and c not in level:
                max_lvl += 1
                level[c] = max_lvl
        # group by level
        by_lvl: Dict[int, list[str]] = defaultdict(list)
        for cid, lv in level.items():
            by_lvl[lv].append(cid)
        # stable order: use existing positions to keep relative nearby
        for lv in by_lvl:
            by_lvl[lv].sort()
        # assign positions
        x0, y0 = 120, 100
        xgap, ygap = 200, 120
        new_pos: Dict[str, QtCore.QPointF] = {}
        for lv in sorted(by_lvl.keys()):
            for i, cid in enumerate(by_lvl[lv]):
                new_pos[cid] = QtCore.QPointF(x0 + lv * xgap, y0 + i * ygap)
        # include any components that somehow missed (empty graph)
        for cid in comps:
            if cid not in new_pos:
                new_pos[cid] = QtCore.QPointF(x0, y0)
        self.positions = new_pos
        self.update()

    def validate_wiring(self) -> Dict[str, list[str]]:
        incoming = {}
        outgoing = {}
        for w in self.circuit.wires:
            incoming[(w.dst_comp, w.dst_port)] = True
            outgoing[(w.src_comp, w.src_port)] = True
        issues: Dict[str, list[str]] = {}
        for cid, comp in self.circuit.components.items():
            missing: list[str] = []
            for p in comp.ports.values():
                if p.direction == 'in':
                    if not incoming.get((cid, p.id)):
                        missing.append(f"in:{p.id}")
                elif p.direction == 'out':
                    if not outgoing.get((cid, p.id)):
                        missing.append(f"out:{p.id}")
            if missing:
                issues[cid] = missing
        self.unwired = issues
        self.update()
        return issues

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor("#1e1e1e"))
        p.setRenderHint(QtGui.QPainter.Antialiasing)

        # wires
        p.setPen(QtGui.QPen(QtGui.QColor("#888"), 2))
        for w in self.circuit.wires:
            a = self.port_center(w.src_comp, w.src_port, True)
            b = self.port_center(w.dst_comp, w.dst_port, False)
            p.drawLine(a, b)

        # components
        self.port_map.clear()
        for cid, comp in self.circuit.components.items():
            pos = self.positions.get(cid, QtCore.QPointF(50, 50))
            rect = QtCore.QRectF(pos.x(), pos.y(), COMP_WIDTH, COMP_HEIGHT)
            p.setBrush(QtGui.QColor("#2e2e2e"))
            # selected > unwired > normal
            if cid == self.selected:
                border_color = "#4FC3F7"  # cyan
                width = 2
            elif cid in self.unwired:
                border_color = "#FFC107"  # amber warning
                width = 2
            else:
                border_color = "#aaa"
                width = 1
            p.setPen(QtGui.QPen(QtGui.QColor(border_color), width))
            p.drawRoundedRect(rect, 6, 6)
            p.setPen(QtGui.QPen(QtGui.QColor("#fff"), 1))
            p.drawText(rect.adjusted(4, 4, -4, -4), QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop, f"{comp.type}\n{cid}")
            # ports
            in_ports = [p2 for p2 in comp.ports.values() if p2.direction == "in"]
            out_ports = [p2 for p2 in comp.ports.values() if p2.direction == "out"]
            for i, prt in enumerate(in_ports):
                cx = rect.left() - 12
                cy = rect.top() + 15 + i * 18
                self.draw_port(p, cx, cy, cid, prt.id)
            for i, prt in enumerate(out_ports):
                cx = rect.right() + 12
                cy = rect.top() + 15 + i * 18
                self.draw_port(p, cx, cy, cid, prt.id)
            # overlays
            if isinstance(comp, (SwitchBinary, SwitchTernary)):
                p.drawText(rect.adjusted(4, 24, -4, -4), QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop, f"val={comp.ports['out'].value}")
            if isinstance(comp, Probe):
                p.drawText(rect.adjusted(4, 24, -4, -4), QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop, f"in={comp.ports['in'].value}")

    def draw_port(self, p: QtGui.QPainter, cx: float, cy: float, cid: str, port: str):
        r = QtCore.QRectF(cx - PORT_RADIUS, cy - PORT_RADIUS, PORT_RADIUS * 2, PORT_RADIUS * 2)
        val = self.circuit.components[cid].ports[port].value
        p.setBrush(QtGui.QColor({1: "#00e676", 0: "#9e9e9e", -1: "#ff5252"}[val]))
        p.setPen(QtGui.QPen(QtGui.QColor("#000"), 1))
        p.drawEllipse(r)
        self.port_map[(cid, port)] = r

    def port_center(self, cid: str, port: str, output: bool) -> QtCore.QPointF:
        r = self.port_map.get((cid, port))
        if r is None:
            pos = self.positions.get(cid, QtCore.QPointF(50, 50))
            return QtCore.QPointF(pos.x() + (COMP_WIDTH + 12 if output else -12), pos.y() + COMP_HEIGHT / 2)
        return r.center()

    def mousePressEvent(self, e: QtGui.QMouseEvent):
        pos = e.position()
        # placement
        if self.pending_add:
            for _, p in self.positions.items():
                if QtCore.QRectF(p.x(), p.y(), COMP_WIDTH, COMP_HEIGHT).contains(pos):
                    break
            else:
                self.add_component(self.pending_add, pos)
                self.pending_add = None
                self.setCursor(QtCore.Qt.ArrowCursor)
                return
        # inside component rect => select/toggle/context menu
        for cid, comp in self.circuit.components.items():
            rect = QtCore.QRectF(self.positions[cid].x(), self.positions[cid].y(), COMP_WIDTH, COMP_HEIGHT)
            if rect.contains(pos):
                self.selected = cid
                if e.button() == QtCore.Qt.RightButton:
                    self._show_context_menu(e.globalPosition().toPoint())
                    return
                if isinstance(comp, (SwitchBinary, SwitchTernary)):
                    comp.toggle()
                    self.update()
                    return
        # port click => start wire
        for (cid, port), r in self.port_map.items():
            if r.contains(pos):
                self.wire_start = (cid, port)
                return
        # start drag
        for cid, p in self.positions.items():
            if QtCore.QRectF(p.x(), p.y(), COMP_WIDTH, COMP_HEIGHT).contains(pos):
                self.dragging = cid
                self.drag_offset = pos - p
                return
        # empty click clears selection
        self.selected = None
        self.update()

    def mouseMoveEvent(self, e: QtGui.QMouseEvent):
        if self.dragging:
            self.positions[self.dragging] = e.position() - (self.drag_offset or QtCore.QPointF(0, 0))
            self.update()

    def mouseReleaseEvent(self, e: QtGui.QMouseEvent):
        if self.dragging:
            self.dragging = None
            self.drag_offset = None
            return
        if self.wire_start:
            s_cid, s_port = self.wire_start
            s_is_out = self.circuit.components[s_cid].ports[s_port].direction == 'out'
            for (cid, port), r in self.port_map.items():
                if r.contains(e.position()):
                    d_is_out = self.circuit.components[cid].ports[port].direction == 'out'
                    if s_is_out != d_is_out:
                        if s_is_out:
                            self.circuit.connect(s_cid, s_port, cid, port)
                        else:
                            self.circuit.connect(cid, port, s_cid, s_port)
                        break
            self.wire_start = None
            self.update()

    def keyPressEvent(self, e: QtGui.QKeyEvent):
        if e.key() == QtCore.Qt.Key_Escape and self.pending_add:
            self.set_add_mode(None)
            e.accept(); return
        if e.key() in (QtCore.Qt.Key_Delete, QtCore.Qt.Key_Backspace):
            if self.selected:
                self.delete_selected()
                e.accept(); return
        super().keyPressEvent(e)

    def _show_context_menu(self, global_pos: QtCore.QPoint):
        menu = QtWidgets.QMenu(self)
        delete_act = menu.addAction("Delete")
        act = menu.exec(global_pos)
        if act == delete_act:
            self.delete_selected()

    def delete_selected(self):
        if not self.selected:
            return
        cid = self.selected
        self.circuit.wires = [w for w in self.circuit.wires if w.src_comp != cid and w.dst_comp != cid]
        if cid in self.circuit.components:
            del self.circuit.components[cid]
        if cid in self.positions:
            del self.positions[cid]
        self.selected = None
        self.update()


class JsonEditor(QtWidgets.QWidget):
    textChanged = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # toolbar
        self.toolbar = QtWidgets.QToolBar()
        self.actionLoad = QtGui.QAction("Load", self)
        self.actionSave = QtGui.QAction("Save", self)
        self.actionSaveAs = QtGui.QAction("Save As", self)
        self.actionApply = QtGui.QAction("Apply", self)
        self.toolbar.addAction(self.actionLoad)
        self.toolbar.addAction(self.actionSave)
        self.toolbar.addAction(self.actionSaveAs)
        self.toolbar.addSeparator()
        self.toolbar.addAction(self.actionApply)
        layout.addWidget(self.toolbar)
        # editor
        self.edit = QtWidgets.QPlainTextEdit()
        font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        self.edit.setFont(font)
        self.edit.textChanged.connect(self.textChanged.emit)
        layout.addWidget(self.edit)
        # status
        self.status = QtWidgets.QLabel("")
        self.status.setStyleSheet("color: #bbb")
        layout.addWidget(self.status)
        self.current_path: Optional[str] = None

    def set_text(self, text: str, path: Optional[str] = None):
        self.edit.setPlainText(text)
        self.current_path = path
        self.status.setText(path or "(unsaved)")

    def get_text(self) -> str:
        return self.edit.toPlainText()

    def set_status(self, msg: str, ok: bool = True):
        color = "#8bc34a" if ok else "#ff5252"
        self.status.setStyleSheet(f"color: {color}")
        self.status.setText(msg)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ternuino CPU Designer")
        self.canvas = Canvas()
        # splitter
        splitter = QtWidgets.QSplitter()
        splitter.setOrientation(QtCore.Qt.Horizontal)
        self.editor = JsonEditor()
        splitter.addWidget(self.editor)
        splitter.addWidget(self.canvas)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([450, 850])
        self.setCentralWidget(splitter)
        # toolbar
        tb = self.addToolBar("Tools")
        for name in ["SwitchBinary", "SwitchTernary", "TAND", "TNOR", "TNOT", "Transistor", "TLatch", "Probe"]:
            act = QtGui.QAction(name, self)
            act.setToolTip(f"Click, then click on canvas to place a {name}")
            act.triggered.connect(lambda _, n=name: self.on_select_component(n))
            tb.addAction(act)
        tb.addSeparator()
        step_act = QtGui.QAction("Step", self)
        step_act.triggered.connect(self.on_step)
        tb.addAction(step_act)
        load_act = QtGui.QAction("Load JSON", self)
        load_act.triggered.connect(self.on_load)
        tb.addAction(load_act)
        save_act = QtGui.QAction("Save JSON", self)
        save_act.triggered.connect(self.on_save)
        tb.addAction(save_act)
        apply_act = QtGui.QAction("Apply From Editor", self)
        apply_act.triggered.connect(self.on_apply_editor)
        tb.addAction(apply_act)
        export_act = QtGui.QAction("Export From Canvas", self)
        export_act.triggered.connect(self.on_export_canvas)
        tb.addAction(export_act)
        del_act = QtGui.QAction("Delete Selected", self)
        del_act.setShortcut(QtGui.QKeySequence.Delete)
        del_act.triggered.connect(self.on_delete)
        tb.addAction(del_act)
        tb.addSeparator()
        auto_act = QtGui.QAction("Auto Arrange", self)
        auto_act.setToolTip("Automatically arrange components by data flow")
        auto_act.triggered.connect(self.on_auto_arrange)
        tb.addAction(auto_act)
        validate_act = QtGui.QAction("Validate Wiring", self)
        validate_act.setToolTip("Highlight components with missing connections")
        validate_act.triggered.connect(self.on_validate)
        tb.addAction(validate_act)
        # editor toolbar wiring
        self.editor.actionLoad.triggered.connect(self.on_load)
        self.editor.actionSave.triggered.connect(self.on_save)
        self.editor.actionSaveAs.triggered.connect(self.on_save_as)
        self.editor.actionApply.triggered.connect(self.on_apply_editor)
        exp_btn = QtGui.QAction("Export", self)
        exp_btn.triggered.connect(self.on_export_canvas)
        self.editor.toolbar.addAction(exp_btn)
        # status
        self.statusBar().showMessage("Tip: Select a component and click the canvas to place it. Drag to move.")

    def on_select_component(self, ctype: str):
        self.canvas.set_add_mode(ctype)
        self.statusBar().showMessage(f"Placing {ctype}: click on canvas to place. Press Esc to cancel.")

    def on_step(self):
        self.canvas.circuit.step()
        self.canvas.update()

    def on_load(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Open design", filter="JSON (*.json)")
        if path:
            with open(path, 'r', encoding='utf-8') as f:
                text = f.read()
            self.editor.set_text(text, path)
            self._apply_text_to_canvas(text)

    def on_save(self):
        if not self.editor.current_path:
            return self.on_save_as()
        text = self.editor.get_text()
        try:
            json.loads(text)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Invalid JSON", str(e))
            self.editor.set_status("Invalid JSON - not saved", ok=False)
            return
        with open(self.editor.current_path, 'w', encoding='utf-8') as f:
            f.write(text)
        self.editor.set_status(f"Saved: {self.editor.current_path}")
        self._apply_text_to_canvas(text)

    def on_save_as(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save design as", filter="JSON (*.json)")
        if not path:
            return
        self.editor.current_path = path
        self.on_save()

    def on_apply_editor(self):
        text = self.editor.get_text()
        self._apply_text_to_canvas(text)

    def _apply_text_to_canvas(self, text: str):
        try:
            self.canvas.load_json(text)
            self.editor.set_status("Applied to canvas", ok=True)
            issues = self.canvas.validate_wiring()
            if issues:
                self.statusBar().showMessage(f"Validation: {len(issues)} component(s) with missing connections")
            else:
                self.statusBar().showMessage("Validation: all components wired")
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Load error", str(e))
            self.editor.set_status("Apply failed", ok=False)

    def on_export_canvas(self):
        try:
            base = json.loads(dump_circuit_to_json(self.canvas.circuit))
            for comp in base.get('components', []):
                cid = comp.get('id')
                if cid and cid in self.canvas.positions:
                    p = self.canvas.positions[cid]
                    comp['position'] = {'x': int(p.x()), 'y': int(p.y())}
            text = json.dumps(base, indent=2)
            self.editor.set_text(text, self.editor.current_path)
            self.editor.set_status("Exported from canvas", ok=True)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Export error", str(e))
            self.editor.set_status("Export failed", ok=False)

    def on_delete(self):
        self.canvas.delete_selected()

    def on_auto_arrange(self):
        self.canvas.auto_arrange()

    def on_validate(self):
        issues = self.canvas.validate_wiring()
        if issues:
            summary = []
            max_items = 8
            for i, (cid, ports) in enumerate(issues.items()):
                if i >= max_items:
                    summary.append("...")
                    break
                summary.append(f"{cid}: {', '.join(ports)}")
            QtWidgets.QMessageBox.information(self, "Wiring issues", "\n".join(summary))
        else:
            QtWidgets.QMessageBox.information(self, "Wiring", "All components have connections")


def run():
    app = QtWidgets.QApplication([])
    w = MainWindow()
    w.resize(1200, 800)
    w.show()
    app.exec()
