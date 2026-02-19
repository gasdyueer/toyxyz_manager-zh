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

        # 正面提示词
        pos_header = QHBoxLayout()
        pos_header.addWidget(QLabel("正面提示词:"))
        btn_copy_pos = QPushButton("📋")
        btn_copy_pos.setFixedWidth(30)
        btn_copy_pos.setToolTip("复制正面提示词")
        btn_copy_pos.clicked.connect(lambda: self._copy_to_clipboard(self.txt_pos.toPlainText(), "正面提示词"))
        pos_header.addWidget(btn_copy_pos)
        pos_header.addStretch()
        layout.addLayout(pos_header)
        
        self.txt_pos = QTextEdit()
        self.txt_pos.setPlaceholderText("正面提示词")
        layout.addWidget(self.txt_pos, 1)
        
        # 负面提示词
        neg_header = QHBoxLayout()
        neg_header.addWidget(QLabel("负面提示词:"))
        btn_copy_neg = QPushButton("📋")
        btn_copy_neg.setFixedWidth(30)
        btn_copy_neg.setToolTip("复制负面提示词")
        btn_copy_neg.clicked.connect(lambda: self._copy_to_clipboard(self.txt_neg.toPlainText(), "负面提示词"))
        neg_header.addWidget(btn_copy_neg)
        neg_header.addStretch()
        layout.addLayout(neg_header)
        
        self.txt_neg = QTextEdit()
        self.txt_neg.setPlaceholderText("负面提示词")
        self.txt_neg.setObjectName("ExampleNegativePrompt")
        layout.addWidget(self.txt_neg, 1)
        
        # Generation 设置
        self.param_widgets = {}
        grid_group = QGroupBox("Generation 设置")
        grid_layout = QGridLayout(grid_group)
        params = ["步数", "采样器", "CFG", "种子", "调度器"]
        for i, p in enumerate(params):
            grid_layout.addWidget(QLabel(p), 0, i)
            le = QLineEdit()
            self.param_widgets[p] = le
            grid_layout.addWidget(le, 1, i)
            
        layout.addWidget(grid_group)
        
        # Metadata Tabs (模型 / 其他)
        self.meta_tabs = QTabWidget()
        
        # Tab 1: 模型 / 资源
        self.tab_model = QWidget()
        tab_model_layout = QVBoxLayout(self.tab_model)
        tab_model_layout.setContentsMargins(5,5,5,5)
        self.txt_resources = QTextEdit()
        self.txt_resources.setPlaceholderText("Civitai resources / 模型 info...")
        self.txt_resources.setMaximumHeight(100)
        tab_model_layout.addWidget(self.txt_resources)
        self.meta_tabs.addTab(self.tab_model, "资源")
        
        # Tab 2: 其他
        self.tab_etc = QWidget()
        tab_etc_layout = QVBoxLayout(self.tab_etc)
        tab_etc_layout.setContentsMargins(5,5,5,5)
        self.txt_etc = QTextEdit()
        self.txt_etc.setPlaceholderText("额外参数 (NovelAI, 笔记等)...")
        self.txt_etc.setReadOnly(True)
        self.txt_etc.setMaximumHeight(100)
        tab_etc_layout.addWidget(self.txt_etc)
        self.meta_tabs.addTab(self.tab_etc, "其他")
        
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
            if meta.get("raw_text", "") and ("步数:" in meta["raw_text"] or "采样器:" in meta["raw_text"]):
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
            self.txt_etc.setText(f"错误 parsing metadata: {e}")

    def _display_from_raw_text(self, text):
        data = parse_generation_parameters(text)
        
        self.txt_pos.setText(data["positive"])
        self.txt_neg.setText(data["negative"])
        
        p_map = data["parameters"]
        
        # Map to widgets
        key_map = {
            "steps": "步数", "sampler": "采样器", "cfg scale": "CFG", 
            "seed": "种子", "schedule type": "调度器"
        }
        
        for k_src, k_ui in key_map.items():
            if k_src in p_map:
                self.param_widgets[k_ui].setText(p_map[k_src])
                
        # 资源
        lines = []
        
        # Checkpoint from parameters?
        if "model" in p_map: lines.append(f"[checkpoint] {p_map['model']}")
        elif "model hash" in p_map: lines.append(f"[checkpoint] {p_map['model hash']}")
        
        # Civitai 资源
        if data["raw_resources"]:
            try:
                res_list = json.loads(data["raw_resources"])
                if isinstance(res_list, list):
                    for item in res_list:
                        itype = item.get("type", "unknown")
                        iname = item.get("model名称", "Unknown")
                        iver = item.get("modelVersion名称", "")
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
        
        # 其他
        used_keys = set(key_map.keys()) | {"model", "model hash", "civitai resources", "resources"}
        etc_lines = []
        for k, v in p_map.items():
            if k not in used_keys:
                etc_lines.append(f"{k}: {v}")
        self.txt_etc.setText("\n".join(etc_lines))

    def _display_novelai(self, meta):
        p = meta.get("main", {})
        key_map = {"steps": "步数", "sampler": "采样器", "cfg": "CFG", "seed": "种子", "schedule": "调度器"}
        for k_src, k_ui in key_map.items():
            if p.get(k_src): self.param_widgets[k_ui].setText(str(p[k_src]))
            
        self.txt_pos.setText(meta.get("prompts", {}).get("positive", ""))
        self.txt_neg.setText(meta.get("prompts", {}).get("negative", ""))
        
        etc_lines = [f"{k}: {v}" for k, v in meta.get("etc", {}).items()]
        self.txt_etc.setText("\n".join(etc_lines))

    def _display_comfy(self, meta):
        p = meta.get("main", {})
        key_map = {"steps": "步数", "sampler": "采样器", "cfg": "CFG", "seed": "种子", "schedule": "调度器"}
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
        key_map = {"steps": "步数", "sampler": "采样器", "cfg": "CFG", "seed": "种子", "schedule": "调度器"}
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
            "步数": "步数", 
            "采样器": "采样器", 
            "种子": "种子", 
            "调度器": "调度器 type"
        }
        
        for k, w in self.param_widgets.items():
            v = w.text().strip()
            if v:
                pk = rev_map.get(k, k)
                param_parts.append(f"{pk}: {v}")
                
        # Extract 模型 from 资源
        res_content = self.txt_resources.toPlainText().strip()
        model_found = False
        
        # Simple parsing to find [checkpoint] and add it as "模型: 名称"
        for line in res_content.split('\n'):
            line = line.strip()
            if line.lower().startswith("[checkpoint]"):
                model_val = line[len("[checkpoint]"):].strip()
                if model_val:
                    # Remove version info in parens if we want just name? 
                    # Usually A1111 puts hash or name.
                    # Let's just use the full string found there.
                    param_parts.append(f"模型: {model_val}")
                    model_found = True
                break
                
        full_text = pos
        if neg: full_text += f"\nNegative prompt: {neg}"
        if param_parts: full_text += "\n" + ", ".join(param_parts)
        
        # 资源 handling
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
                 # But excluding the [checkpoint] line might be safer if we added 模型 param?
                 # No, let's keep it simple: just append what's in text.
                 filtered_lines = [l for l in res_content.split('\n') if not l.strip().lower().startswith("[checkpoint]")]
                 cleaned_res = "\n".join(filtered_lines).strip()
                 if cleaned_res:
                     full_text += f"\n资源:\n{cleaned_res}"
                     
        return full_text
