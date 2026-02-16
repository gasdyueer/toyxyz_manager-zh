# Toyxyz Manager

The toyxyz manager is a model, workflow, and prompt management tool designed to be used together with ComfyUI.
---

## ✨ Key Features

### 1. 📦 Model Manager

- **Unified Management**: Organize Checkpoints, LoRAs, VAEs, Embeddings, ControlNets, and Upscale Models in one place.
- **Smart Previews**: Automatically plays video previews (`.mp4`, `.webm`) and animated GIFs alongside standard images.
- **Civitai Integration**:
  - **Auto-Match**: Calculates file hashes to automatically fetch metadata (Creator, Version Info, Trigger Words) from Civitai.
  - **One-Click Download**: Download new models directly via Civitai or Hugging Face URLs.
- **Seamless Copy**: Select a model and click `📋 Copy Node` to generate a node snippet that can be **pasted directly** into your ComfyUI canvas (Ctrl+V).

### 2. 🖼️ Gallery Manager

- **High-Performance Browser**: Browses thousands of generated images and videos with zero lag, thanks to optimized background scanning and caching.
- **Metadata Inspector**: View generation parameters (Prompt, Sampler, Seed, etc.) embedded in your images.
- **Fullscreen Preview**: Double-click or use the preview pane to inspect details in full resolution.
- **Duplicate Detection**: (Optional) Intelligent warning system for duplicate files (disabled in Gallery mode for a cleaner view).

### 3. 🔄 Workflow Manager

- **Visualizer**: Preview the structure of `.json` workflow files without opening ComfyUI.
- **Smart Copy**:
  - Copy workflows to clipboard in a format that ComfyUI recognizes as **"Paste Nodes"**.
  - Automatically handles subgraphs and converts link formats for maximum compatibility.

### 4. 📝 Prompt Manager

- **Library System**: Save, edit, and organize positive/negative prompts.
- **Tagging & Filtering**: meaningful tags for quick retrieval.
- **Example Images**: Associate example images with your prompts to remember their effects.

### 5. 🛠️ Power User Tools

- **Task Monitor**: Real-time tracking of background tasks (hashing, downloading, scanning).
- **Global Search**: Recursively search for files across your entire library.
- **Notes**: Add Markdown notes to any model or file for personal reference.

---

## 🚀 Installation

### Prerequisites

- **OS**: Windows 10/11
- **Python**: 3.10 or higher
- **ComfyUI**: (Optional, but recommended for full integration)

### Setup Guide

1. **Clone the Repository**

   ```bash
   git clone https://github.com/toyxyz/toyxyz_manager.git
   cd toyxyz_manager
   ```

2. **Create a Virtual Environment** (Recommended)

   ```bash
   python -m venv venv
   .\venv\Scripts\activate
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```
   _Core dependencies: `PySide6`, `requests`, `Pillow`, `markdown`, `markdownify`_

---

## 🎮 Usage

### Running the Application

Simply double-click the included **`run.bat`** file, or run via command line:

```bash
python main.py
```

### Initial Configuration

1. Click the **Settings (⚙️)** icon in the top-right corner.
2. Add your asset folders (where your models/images are stored).
3. Set the **Mode** for each folder:
   - `model`: For ComfyUI models (Checkpoints, LoRAs, etc.).
   - `gallery`: For generated outputs.
   - `workflow`: For JSON workflows.
   - `prompt`: For prompt text files.
4. (Optional) Set your **ComfyUI Root Path** to enable relative path features.

---

## 💡 Tips & Tricks

- **Custom Thumbnails**: Drag & Drop any image onto a model's preview area to set it as a custom thumbnail.
- **Fast Copy**: Right-click a prompt in the list to copy it instantly.
- **Notes**: Use the `Note` tab to document trigger words or recommended settings for your models.
- **Refresh**: Hit the `🔄` button to rescan folders if you've added files externally.
