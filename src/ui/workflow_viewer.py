import json
import logging
from typing import Dict, Any, List

from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsItem, QGraphicsPathItem, QPushButton
from PySide6.QtCore import Qt, QRectF, QPointF, QRect
from PySide6.QtGui import QPen, QBrush, QPainterPath, QColor, QPainter, QFont, QFontMetrics

class WorkflowGroupItem(QGraphicsItem):
    def __init__(self, group_data, parent=None):
        super().__init__(parent)
        self.group_data = group_data
        self.title = group_data.get("title", "Group")
        self.color = group_data.get("color", "#3f4142") 
        if not self.color: self.color = "#3f4142"
        
        # Geometry
        bounding = group_data.get("bounding", [])
        if len(bounding) >= 4:
            self.rect = QRectF(bounding[0], bounding[1], bounding[2], bounding[3])
        else:
            self.rect = QRectF(0, 0, 100, 100)
            
        self.setZValue(-2) # Behind links and nodes
        
    def boundingRect(self):
        return self.rect
        
    def paint(self, painter, option, widget=None):
        # Draw Background
        c = QColor(self.color)
        c.setAlpha(150) # Semi-transparent
        painter.setBrush(c)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(self.rect, 8, 8)
        
        # Draw Title Block (Bottom)
        title_height = 30
        title_rect = QRectF(self.rect.x(), self.rect.bottom() - title_height, self.rect.width(), title_height)
        
        painter.setBrush(c.darker(120))
        painter.drawRoundedRect(title_rect, 8, 8) # Rounded corners will look slightly off at top connection but okay
        
        # Title Text
        painter.setPen(Qt.white)
        font = painter.font()
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(title_rect, Qt.AlignCenter, self.title)

class WorkflowNodeItem(QGraphicsItem):
    def __init__(self, node_id, node_data, parent=None):
        super().__init__(parent)
        self.node_id = str(node_id)
        self.node_data = node_data
        
        # Extract basic info
        self.title = self._get_title(node_data)
        self.inputs = self._get_inputs(node_data)
        self.outputs = self._get_outputs(node_data)
        self.widgets = self._get_widgets(node_data) 
        
        # Dimensions
        self.width = 200 
        self.header_height = 24
        self.base_slot_height = 20
        self.value_height = 15 # Extra height for value line
        self.spacing = 10
        self.padding = 10
        
        # Cache socket positions per slot index/name
        self.input_sockets = {} 
        self.output_sockets = {} 
        
        # Track connected links
        self.links = []
        
        # Layout variables
        self.input_y_offsets = [] # Top-relative y for each input
        self.output_y_offsets = []
        self.widget_blocks = []
        self.widget_start_y = 0
        
        # Calculate Layout & Height
        self._calculate_layout()
        
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True) 

    def _calculate_layout(self):
        # 1. Height Calculation
        # Left side inputs have variable height now
        
        current_y = self.header_height + self.padding
        self.input_y_offsets = []
        
        for inp in self.inputs:
            h = self.base_slot_height
            if "widget_value" in inp:
                h += self.value_height
            self.input_y_offsets.append((current_y, h))
            current_y += h
            
        left_h = current_y - (self.header_height + self.padding)
        
        # Add remaining widgets height
        total_widget_h = 0
        self.widget_blocks = []
        if self.widgets:
            f = QFont()
            f.setPointSize(8)
            fm = QFontMetrics(f)
            text_width = self.width - 16
            
            for w_text in self.widgets:
                rect = fm.boundingRect(QRect(0, 0, int(text_width), 1000), Qt.TextWordWrap, w_text)
                h = rect.height() + 5 
                self.widget_blocks.append((w_text, h))
                total_widget_h += h
        
        left_h += total_widget_h
        
        # Right Side: Outputs (Uniform height usually, but let's just stack them)
        right_current_y = self.header_height + self.padding
        self.output_y_offsets = []
        for out in self.outputs:
            h = self.base_slot_height
            self.output_y_offsets.append((right_current_y, h))
            right_current_y += h
            
        right_h = right_current_y - (self.header_height + self.padding)
        
        # Total Height
        content_h = max(left_h, right_h)
        self.height = self.header_height + content_h + (self.padding * 2)
        
        # 2. Socket Positions
        # Inputs
        for i, (y, h) in enumerate(self.input_y_offsets):
            inp = self.inputs[i]
            name = inp.get("name", f"In {i}")
            # Socket at middle of the *top part* (slot name)
            socket_y = y + (self.base_slot_height / 2)
            
            pos = QPointF(0, socket_y)
            self.input_sockets[i] = pos
            self.input_sockets[name] = pos
            
        # Widget Start Y (after all inputs)
        if self.input_y_offsets:
            last_y, last_h = self.input_y_offsets[-1]
            self.widget_start_y = last_y + last_h + 5
        else:
            self.widget_start_y = self.header_height + self.padding
            
        # Outputs
        for i, (y, h) in enumerate(self.output_y_offsets):
            out = self.outputs[i]
            name = out.get("name", f"Out {i}")
            socket_y = y + (h / 2)
            pos = QPointF(self.width, socket_y)
            self.output_sockets[i] = pos
            
    def add_link(self, link):
        self.links.append(link)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            for link in self.links:
                link.track_nodes()
        return super().itemChange(change, value)
        
    def _get_title(self, data):
        # 1. User-defined Title (Highest Priority)
        if "title" in data: return data["title"]
        
        # 2. Meta Title
        if "_meta" in data and "title" in data["_meta"]: return data["_meta"]["title"]
        
        # 3. Properties (Node name for S&R)
        props = data.get("properties", {})
        if "Node name for S&R" in props: return props["Node name for S&R"]
        
        # 4. 类型 / Class 类型
        # These might be human readable OR UUIDs (for Group Nodes)
        candidate = data.get("type") or data.get("class_type")
        
        if candidate:
            # Check if it looks like a UUID or is too long/technical
            if len(candidate) > 25 and "-" in candidate and " " not in candidate:
                return f"Group/Node {candidate[:8]}..."
            return candidate
            
        return f"Node {self.node_id}"

    def _get_inputs(self, data):
        if "inputs" in data and isinstance(data["inputs"], list):
            return data["inputs"] 
        if "inputs" in data and isinstance(data["inputs"], dict):
            # API Format
            res = []
            for k, v in data["inputs"].items():
                item = {"name": k}
                # If not a link (list len 2), it's a value
                if not (isinstance(v, list) and len(v) == 2):
                     item["widget_value"] = str(v)
                res.append(item)
            return res
        return []

    def _get_outputs(self, data):
        if "outputs" in data and isinstance(data["outputs"], list):
            return data["outputs"]
        return []
        
    def _get_widgets(self, data):
        vals = []
        if "widgets_values" in data and isinstance(data["widgets_values"], list):
            for v in data["widgets_values"]:
                if isinstance(v, str):
                    vals.append(v)
                elif isinstance(v, (int, float)):
                    vals.append(str(v))
        
        # API Check handled in _get_inputs.
        if "inputs" in data and isinstance(data["inputs"], dict):
            return []
            
        return vals

    def boundingRect(self):
        return QRectF(0, 0, self.width, self.height)

    def paint(self, painter, option, widget=None):
        # Draw Box
        rect = self.boundingRect()
        
        painter.setPen(QPen(Qt.black, 1))
        painter.setBrush(Qt.white)
        painter.drawRoundedRect(rect, 4, 4)
        
        # Header
        header_rect = QRectF(0, 0, self.width, self.header_height)
        painter.setBrush(QColor("#eaeaea"))
        painter.drawRoundedRect(header_rect, 4, 4) 
        painter.drawRect(QRectF(0, self.header_height-5, self.width, 5)) 
        painter.drawLine(0, self.header_height, self.width, self.header_height)
        
        # Title
        painter.setPen(Qt.black)
        font = painter.font()
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRectF(5, 0, self.width - 10, self.header_height), Qt.AlignVCenter | Qt.AlignLeft, self.title)
        
        # Content Font
        font.setBold(False)
        font.setPointSize(8)
        painter.setFont(font)
        
        # Draw Inputs
        for i, (y, h) in enumerate(self.input_y_offsets):
            inp = self.inputs[i]
            name = inp.get("name", f"In {i}")
            
            # Socket
            socket_y = y + (self.base_slot_height / 2)
            painter.setBrush(Qt.black)
            painter.drawEllipse(QPointF(0, socket_y), 3, 3)
            
            # 名称
            painter.setPen(Qt.black)
            name_rect = QRectF(8, y, self.width/2, self.base_slot_height)
            painter.drawText(name_rect, Qt.AlignVCenter | Qt.AlignLeft, name)
            
            # Value (if exists)
            val = inp.get("widget_value")
            if val is not None:
                val_rect = QRectF(12, y + self.base_slot_height - 5, self.width - 20, self.value_height)
                painter.setPen(QColor("#666666"))
                # Elide text if too long?
                elided_val = painter.fontMetrics().elidedText(val, Qt.ElideRight, val_rect.width())
                painter.drawText(val_rect, Qt.AlignVCenter | Qt.AlignLeft, elided_val)
            
        # Draw Widgets (Leftovers)
        if self.widget_blocks:
            y_text = self.widget_start_y
            painter.setPen(QColor("#333333"))
            
            for w_text, h in self.widget_blocks:
                text_rect = QRectF(8, y_text, self.width - 16, h) 
                painter.drawText(text_rect, Qt.TextWordWrap, w_text)
                y_text += h

        # Draw Outputs
        for i, (y, h) in enumerate(self.output_y_offsets):
            out = self.outputs[i]
            name = out.get("name", f"Out {i}")
            
            socket_y = y + (h / 2)
            painter.setBrush(Qt.black)
            painter.drawEllipse(QPointF(self.width, socket_y), 3, 3)
            
            painter.setPen(Qt.black)
            name_rect = QRectF(self.width/2, y, self.width/2 - 8, h)
            painter.drawText(name_rect, Qt.AlignVCenter | Qt.AlignRight, name)

    def get_input_pos(self, ident):
        local_pos = self.input_sockets.get(ident)
        if not local_pos:
             # Fallback
             local_pos = QPointF(0, self.header_height)
        return self.mapToScene(local_pos)

    def get_output_pos(self, ident):
        local_pos = self.output_sockets.get(ident)
        if not local_pos:
             local_pos = QPointF(self.width, self.header_height)
        return self.mapToScene(local_pos)


class WorkflowLinkItem(QGraphicsPathItem):
    def __init__(self, start_node, start_slot, end_node, end_slot):
        super().__init__()
        self.start_node = start_node
        self.start_slot = start_slot
        self.end_node = end_node
        self.end_slot = end_slot
        
        self.setPen(QPen(Qt.black, 1.5))
        self.setZValue(-1) # Behind nodes
        self.track_nodes()
        
    def track_nodes(self):
        start_pos = self.start_node.get_output_pos(self.start_slot)
        end_pos = self.end_node.get_input_pos(self.end_slot)
        self.update_path(start_pos, end_pos)
        
    def update_path(self, start_pos, end_pos):
        path = QPainterPath()
        path.moveTo(start_pos)
        
        # Cubic Bezier
        dx = end_pos.x() - start_pos.x()
        dy = end_pos.y() - start_pos.y()
        
        ctrl1_x = start_pos.x() + max(dx * 0.5, 50)
        ctrl1_y = start_pos.y()
        
        ctrl2_x = end_pos.x() - max(dx * 0.5, 50)
        ctrl2_y = end_pos.y()
        
        path.cubicTo(ctrl1_x, ctrl1_y, ctrl2_x, ctrl2_y, end_pos.x(), end_pos.y())
        self.setPath(path)


class WorkflowGraphViewer(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse) # 缩放 center mouse
        self.setBackgroundBrush(Qt.white)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        
        # Panning State
        self._is_panning = False
        self._pan_start_pos = QPointF(0, 0)
        
        # Floating Fit Button
        self.fit_btn = QPushButton("Fit", self)
        self.fit_btn.setFixedSize(50, 30)
        self.fit_btn.setStyleSheet("""
            QPushButton {
                background-color: #333; 
                color: white; 
                border-radius: 4px;
                opacity: 0.8;
            }
            QPushButton:hover {
                background-color: #555;
            }
        """)
        self.fit_btn.clicked.connect(self.center_view)
        
        # Map node_id -> NodeItem
        self.node_items = {} 

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._is_panning = True
            self._pan_start_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_panning:
            delta = event.pos() - self._pan_start_pos
            self._pan_start_pos = event.pos()
            
            # Scrollbars
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._is_panning = False
            self.setCursor(Qt.ArrowCursor) # Or restore previous
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        # Keep button in bottom-right
        super().resizeEvent(event)
        self.fit_btn.move(self.width() - 60, self.height() - 40)

    def clear_graph(self):
        # Explicit cleanup
        scene = self.scene()
        for item in scene.items():
            scene.removeItem(item)
        self.node_items.clear()
        
    def leaveEvent(self, event):
        if self._is_panning:
            self._is_panning = False
            self.setCursor(Qt.ArrowCursor)
        super().leaveEvent(event)
        
    def focusOutEvent(self, event):
        if self._is_panning:
            self._is_panning = False
            self.setCursor(Qt.ArrowCursor)
        super().focusOutEvent(event)

    def load_workflow(self, json_data):
        self.clear_graph()
        
        try:
            # 1. Detect Format
            if "nodes" in json_data and isinstance(json_data["nodes"], list):
                # Standard Saved Format
                nodes_data = json_data.get("nodes", [])
                links_data = json_data.get("links", [])
                groups_data = json_data.get("groups", [])
                self._build_graph_standard(nodes_data, links_data, groups_data)
            else:
                # API Format (Dict: id -> node)
                # Or wrapped: {"workflow": ...}
                if "workflow" in json_data:
                    data = json_data["workflow"]
                    if "nodes" in data:
                        # Wrapped Standard
                        self._build_graph_standard(data.get("nodes", []), data.get("links", []), data.get("groups", []))
                        return
                    
                # Pure API Format
                if isinstance(json_data, dict):
                     self._build_graph_api(json_data)
                     
        except Exception as e:
            logging.error(f"错误 loading graph: {e}")

    def _build_graph_standard(self, nodes, links, groups):
        # 1. Create Groups (Background)
        for g in groups:
            item = WorkflowGroupItem(g)
            self.scene().addItem(item)
            
        # 2. Create Nodes
        for n in nodes:
            nid = str(n.get("id"))
            item = WorkflowNodeItem(nid, n)
            self.scene().addItem(item)
            self.node_items[nid] = item
            
            # Set Position
            pos = n.get("pos", [0, 0])
            if isinstance(pos, list) and len(pos) >= 2:
                item.setPos(pos[0], pos[1])
            else:
                item.setPos(0, 0) # Fallback

        # 3. Create Links
        # Link: [id, origin_id, origin_slot, target_id, target_slot, type]
        for l in links:
            if not isinstance(l, list) or len(l) < 5: continue
            
            origin_id = str(l[1])
            origin_slot = l[2]
            target_id = str(l[3])
            target_slot = l[4]
            
            origin_node = self.node_items.get(origin_id)
            target_node = self.node_items.get(target_id)
            
            if origin_node and target_node:
                link_item = WorkflowLinkItem(origin_node, origin_slot, target_node, target_slot)
                self.scene().addItem(link_item)
                
                # Register Link with Nodes for tracking
                origin_node.add_link(link_item)
                target_node.add_link(link_item)
                
        self.center_view()

    def _build_graph_api(self, api_data):
        # API format has no position info. Needs auto layout.
        
        # 1. Convert to internal list
        internal_nodes = []
        adj_list = {} # id -> list of child ids
        in_degree = {} # id -> count
        
        for nid, data in api_data.items():
            nid = str(nid)
            internal_nodes.append({"id": nid, **data})
            adj_list[nid] = []
            if nid not in in_degree: in_degree[nid] = 0

        # Create Items first
        for n in internal_nodes:
            nid = n["id"]
            item = WorkflowNodeItem(nid, n)
            self.scene().addItem(item)
            self.node_items[nid] = item
            
        # 2. Trace Links & Build Topology
        links_to_create = [] # (start_id, end_id, start_slot_name, end_slot_name)
        
        for target_nid, data in api_data.items():
            target_nid = str(target_nid)
            inputs = data.get("inputs", {})
            if not isinstance(inputs, dict): continue
            
            for input_name, value in inputs.items():
                # Link is ["node_id", slot_index]
                if isinstance(value, list) and len(value) == 2:
                    origin_nid = str(value[0])
                    outcome_slot_idx = value[1] 
                    
                    if origin_nid in self.node_items:
                        links_to_create.append((origin_nid, target_nid, outcome_slot_idx, input_name))
                        
                        adj_list[origin_nid].append(target_nid)
                        in_degree[target_nid] = in_degree.get(target_nid, 0) + 1

        # 3. Create Link Items
        for origin_nid, target_nid, out_slot, in_name in links_to_create:
            origin_node = self.node_items[origin_nid]
            target_node = self.node_items[target_nid]
            
            link_item = WorkflowLinkItem(origin_node, out_slot, target_node, in_name)
            self.scene().addItem(link_item)
            
            origin_node.add_link(link_item)
            target_node.add_link(link_item)

        # 4. Auto Layout (Simple Level-based)
        # Topological Sort with Levels
        queue = [nid for nid in in_degree if in_degree[nid] == 0]
        levels = {} # nid -> level
        for q in queue: levels[q] = 0
        
        sorted_nodes = []
        
        while queue:
            u = queue.pop(0)
            sorted_nodes.append(u)
            lvl = levels[u]
            
            for v in adj_list.get(u, []):
                in_degree[v] -= 1
                levels[v] = max(levels.get(v, 0), lvl + 1)
                if in_degree[v] == 0:
                    queue.append(v)
                    
        # Handle cycles (nodes not in sorted_nodes)
        for nid in self.node_items:
            if nid not in levels:
                levels[nid] = 0 
                
        # Assign Positions
        level_groups = {}
        for nid, lvl in levels.items():
            if lvl not in level_groups: level_groups[lvl] = []
            level_groups[lvl].append(nid)
            
        x_spacing = 250
        y_spacing = 150
        start_x = 50
        
        max_level = max(level_groups.keys()) if level_groups else 0
        
        for lvl in range(max_level + 1):
            nodes = level_groups.get(lvl, [])
            current_y = 50
            current_x = start_x + (lvl * x_spacing)
            
            for nid in nodes:
                item = self.node_items[nid]
                item.setPos(current_x, current_y)
                current_y += item.height + 20
        
        self.center_view()

    def center_view(self):
        # Fit logic
        rect = self.scene().itemsBoundingRect()
        self.setSceneRect(rect)
        self.fitInView(rect, Qt.KeepAspectRatio)

    def wheelEvent(self, event):
        # Smooth 缩放
        zoom_in = event.angleDelta().y() > 0
        factor = 1.15 if zoom_in else 1 / 1.15
        
        # Calculate new scale
        current_scale = self.transform().m11()
        new_scale = current_scale * factor
        
        # Dynamic Limits
        # Calculate min zoom to fit the entire scene in view
        scene_rect = self.sceneRect()
        view_rect = self.viewport().rect()
        
        if scene_rect.width() > 0 and scene_rect.height() > 0:
            scale_w = view_rect.width() / scene_rect.width()
            scale_h = view_rect.height() / scene_rect.height()
            fit_scale = min(scale_w, scale_h)
            
            # Allow zooming out to 80% of fit_scale or 0.05, whichever is smaller but reasonable
            min_zoom = max(fit_scale * 0.8, 0.05) 
        else:
            min_zoom = 0.1
            
        max_zoom = 2.0
        
        if min_zoom <= new_scale <= max_zoom:
            self.scale(factor, factor)
