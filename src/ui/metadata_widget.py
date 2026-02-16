from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit, 
    QGridLayout, QGroupBox, QLineEdit, QTabWidget, QApplication
)
from PySide6.QtCore import Qt, Signal
import json
import logging

from ..utils.metadata_utils import parse_generation_parameters

class MetadataViewerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)

        # Positive Prompt
        pos_header = QHBoxLayout()
        pos_header.addWidget(QLabel("Positive:"))
        btn_copy_pos = QPushButton("📋")
        btn_copy_pos.setFixedWidth(30)
        btn_copy_pos.setToolTip("Copy Positive Prompt")
        btn_copy_pos.clicked.connect(lambda: self._copy_to_clipboard(self.txt_pos.toPlainText(), "Positive Prompt"))
        pos_header.addWidget(btn_copy_pos)
        pos_header.addStretch()
        layout.addLayout(pos_header)
        
        self.txt_pos = QTextEdit()
        self.txt_pos.setPlaceholderText("Positive Prompt")
        layout.addWidget(self.txt_pos, 1)
        
        # Negative Prompt
        neg_header = QHBoxLayout()
        neg_header.addWidget(QLabel("Negative:"))
        btn_copy_neg = QPushButton("📋")
        btn_copy_neg.setFixedWidth(30)
        btn_copy_neg.setToolTip("Copy Negative Prompt")
        btn_copy_neg.clicked.connect(lambda: self._copy_to_clipboard(self.txt_neg.toPlainText(), "Negative Prompt"))
        neg_header.addWidget(btn_copy_neg)
        neg_header.addStretch()
        layout.addLayout(neg_header)
        
        self.txt_neg = QTextEdit()
        self.txt_neg.setPlaceholderText("Negative Prompt")
        self.txt_neg.setObjectName("ExampleNegativePrompt")
        layout.addWidget(self.txt_neg, 1)
        
        # Generation Settings
        self.param_widgets = {}
        grid_group = QGroupBox("Generation Settings")
        grid_layout = QGridLayout(grid_group)
        params = ["Steps", "Sampler", "CFG", "Seed", "Schedule"]
        for i, p in enumerate(params):
            grid_layout.addWidget(QLabel(p), 0, i)
            le = QLineEdit()
            self.param_widgets[p] = le
            grid_layout.addWidget(le, 1, i)
            
        layout.addWidget(grid_group)
        
        # Metadata Tabs (Model / Etc)
        self.meta_tabs = QTabWidget()
        
        # Tab 1: Model / Resources
        self.tab_model = QWidget()
        tab_model_layout = QVBoxLayout(self.tab_model)
        tab_model_layout.setContentsMargins(5,5,5,5)
        self.txt_resources = QTextEdit()
        self.txt_resources.setPlaceholderText("Civitai resources / Model info...")
        self.txt_resources.setMaximumHeight(100)
        tab_model_layout.addWidget(self.txt_resources)
        self.meta_tabs.addTab(self.tab_model, "Resources")
        
        # Tab 2: Etc
        self.tab_etc = QWidget()
        tab_etc_layout = QVBoxLayout(self.tab_etc)
        tab_etc_layout.setContentsMargins(5,5,5,5)
        self.txt_etc = QTextEdit()
        self.txt_etc.setPlaceholderText("Extra parameters (NovelAI, Notes, etc)...")
        self.txt_etc.setReadOnly(True)
        self.txt_etc.setMaximumHeight(100)
        tab_etc_layout.addWidget(self.txt_etc)
        self.meta_tabs.addTab(self.tab_etc, "Etc")
        
        layout.addWidget(self.meta_tabs)

    def clear(self):
        self.txt_pos.clear()
        self.txt_neg.clear()
        self.txt_resources.clear()
        self.txt_etc.clear()
        for w in self.param_widgets.values():
            w.clear()

    def set_metadata(self, meta):
        self.clear()
        if not meta: return

        try:
            # 1. Parsing logic based on 'type'
            
            # Legacy/Raw Text Support
            if meta.get("raw_text", "") and ("Steps:" in meta["raw_text"] or "Sampler:" in meta["raw_text"]):
                 self._display_from_raw_text(meta["raw_text"])
                 return

            mtype = meta.get("type", "unknown")
            
            if mtype == "novelai":
                self._display_novelai(meta)
            elif mtype == "comfy":
                self._display_comfy(meta)
            elif mtype == "simpai":
                 self._display_simpai(meta)
            else:
                 # Fallback
                 if meta.get("raw_text", ""):
                     self._display_from_raw_text(meta["raw_text"])

        except Exception as e:
            logging.warning(f"MetadataViewerWidget error: {e}")
            self.txt_etc.setText(f"Error parsing metadata: {e}")

    def _display_from_raw_text(self, text):
        data = parse_generation_parameters(text)
        
        self.txt_pos.setText(data["positive"])
        self.txt_neg.setText(data["negative"])
        
        p_map = data["parameters"]
        
        # Map to widgets
        key_map = {
            "steps": "Steps", "sampler": "Sampler", "cfg scale": "CFG", 
            "seed": "Seed", "schedule type": "Schedule"
        }
        
        for k_src, k_ui in key_map.items():
            if k_src in p_map:
                self.param_widgets[k_ui].setText(p_map[k_src])
                
        # Resources
        lines = []
        
        # Checkpoint from parameters?
        if "model" in p_map: lines.append(f"[checkpoint] {p_map['model']}")
        elif "model hash" in p_map: lines.append(f"[checkpoint] {p_map['model hash']}")
        
        # Civitai Resources
        if data["raw_resources"]:
            try:
                res_list = json.loads(data["raw_resources"])
                if isinstance(res_list, list):
                    for item in res_list:
                        itype = item.get("type", "unknown")
                        iname = item.get("modelName", "Unknown")
                        iver = item.get("modelVersionName", "")
                        line = f"[{itype}] {iname}"
                        if iver: line += f" ({iver})"
                        if itype != "checkpoint":
                             line += f" : {item.get('weight', 1.0)}"
                        lines.append(line)
            except:
                lines.append(data["raw_resources"])
        elif "resources" in p_map:
            lines.append(p_map["resources"])
            
        self.txt_resources.setText("\n".join(lines))
        
        # Etc
        used_keys = set(key_map.keys()) | {"model", "model hash", "civitai resources", "resources"}
        etc_lines = []
        for k, v in p_map.items():
            if k not in used_keys:
                etc_lines.append(f"{k}: {v}")
        self.txt_etc.setText("\n".join(etc_lines))

    def _display_novelai(self, meta):
        p = meta.get("main", {})
        key_map = {"steps": "Steps", "sampler": "Sampler", "cfg": "CFG", "seed": "Seed", "schedule": "Schedule"}
        for k_src, k_ui in key_map.items():
            if p.get(k_src): self.param_widgets[k_ui].setText(str(p[k_src]))
            
        self.txt_pos.setText(meta.get("prompts", {}).get("positive", ""))
        self.txt_neg.setText(meta.get("prompts", {}).get("negative", ""))
        
        etc_lines = [f"{k}: {v}" for k, v in meta.get("etc", {}).items()]
        self.txt_etc.setText("\n".join(etc_lines))

    def _display_comfy(self, meta):
        p = meta.get("main", {})
        key_map = {"steps": "Steps", "sampler": "Sampler", "cfg": "CFG", "seed": "Seed", "schedule": "Schedule"}
        for k_src, k_ui in key_map.items():
             if p.get(k_src): self.param_widgets[k_ui].setText(str(p[k_src]))
             
        self.txt_pos.setText(meta.get("prompts", {}).get("positive", ""))
        self.txt_neg.setText(meta.get("prompts", {}).get("negative", ""))
        
        m = meta.get("model", {})
        lines = []
        if m.get("checkpoint"): lines.append(f"[checkpoint] {m['checkpoint']}")
        for l in m.get("loras", []): lines.append(f"[lora] {l}")
        self.txt_resources.setText("\n".join(lines))

    def _display_simpai(self, meta):
        # Similar to comfy/novelai structure
        p = meta.get("main", {})
        key_map = {"steps": "Steps", "sampler": "Sampler", "cfg": "CFG", "seed": "Seed", "schedule": "Schedule"}
        for k_src, k_ui in key_map.items():
             if p.get(k_src): self.param_widgets[k_ui].setText(str(p[k_src]))
        
        self.txt_pos.setText(meta.get("prompts", {}).get("positive", ""))
        self.txt_neg.setText(meta.get("prompts", {}).get("negative", ""))
        
        if meta.get("model", {}).get("checkpoint"):
             self.txt_resources.setText(f"[checkpoint] {meta['model']['checkpoint']}")
             
        etc_lines = [f"{k}: {v}" for k, v in meta.get("etc", {}).items()]
        self.txt_etc.setText("\n".join(etc_lines))

    def _copy_to_clipboard(self, text, label):
        cb = QApplication.clipboard()
        cb.setText(text)

    def get_formatted_parameters(self):
        """
        Reconstructs the parameters string from the current UI state.
        Returns: (full_text, resources_text)
        """
        pos = self.txt_pos.toPlainText()
        neg = self.txt_neg.toPlainText()
        
        param_parts = []
        # Mapping from UI Widget keys to Standard A1111 keys
        rev_map = {
            "CFG": "CFG scale", 
            "Steps": "Steps", 
            "Sampler": "Sampler", 
            "Seed": "Seed", 
            "Schedule": "Schedule type"
        }
        
        for k, w in self.param_widgets.items():
            v = w.text().strip()
            if v:
                pk = rev_map.get(k, k)
                param_parts.append(f"{pk}: {v}")
                
        # Extract Model from Resources
        res_content = self.txt_resources.toPlainText().strip()
        model_found = False
        
        # Simple parsing to find [checkpoint] and add it as "Model: Name"
        for line in res_content.split('\n'):
            line = line.strip()
            if line.lower().startswith("[checkpoint]"):
                model_val = line[len("[checkpoint]"):].strip()
                if model_val:
                    # Remove version info in parens if we want just name? 
                    # Usually A1111 puts hash or name.
                    # Let's just use the full string found there.
                    param_parts.append(f"Model: {model_val}")
                    model_found = True
                break
                
        full_text = pos
        if neg: full_text += f"\nNegative prompt: {neg}"
        if param_parts: full_text += "\n" + ", ".join(param_parts)
        
        # Resources handling
        cleaned_res = ""
        if res_content:
             if res_content.startswith('[{"') or "Civitai resources:" in res_content:
                 full_text += f", {res_content}" # Raw JSON append
             else:
                 # Standard text format
                 # Filter out [checkpoint] lines if we already added them to params?
                 # Actually, A1111 puts them in separate blocks sometimes.
                 # But we want to preserve them.
                 # Let's just append the resources block if it's not empty
                 # But excluding the [checkpoint] line might be safer if we added Model param?
                 # No, let's keep it simple: just append what's in text.
                 filtered_lines = [l for l in res_content.split('\n') if not l.strip().lower().startswith("[checkpoint]")]
                 cleaned_res = "\n".join(filtered_lines).strip()
                 if cleaned_res:
                     full_text += f"\nResources:\n{cleaned_res}"
                     
        return full_text
