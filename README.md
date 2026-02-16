# ToyXYZ Manager (ComfyUI Asset Manager)

**ToyXYZ Manager** is a powerful local asset management tool designed for ComfyUI. It streamlines the management of models, workflows, prompts, and gallery images scattered across complex folder structures, providing advanced features like automatic metadata syncing with Civitai, workflow visualization, and efficient file previews.

## ✨ Key Features

### 1. 📦 Model Manager

- **Comprehensive Support**: Manage all ComfyUI model types including Checkpoints, LoRAs, VAEs, Embeddings, ControlNets, and Upscale Models.
- **Smart Previews**: Play video previews (`.mp4`, `.webm`) and animated GIFs alongside standard images (`.png`, `.jpg`, `.webp`).
- **Auto Metadata Matching**:
  - Calculates file hashes to retrieve accurate model details from Civitai.
  - Automatically fetches trigger words, version descriptions, and creator info.
- **ComfyUI Integration**:
  - **Copy Node**: Select a model and click `📋 Copy Node` to generate a node snippet ready to paste properly into ComfyUI.
- **Download Manager**:
  - Download models directly via Civitai or Hugging Face URLs.
  - Smart collision handling with options to rename or overwrite existing files.

### 2. 🖼️ Gallery Manager

- **Visual Browser**: A dedicated mode for browsing your generated images and videos.
- **Detailed Info Panel**: View essential file information such as filename, resolution, file size, and creation date at a glance.
- **Fullscreen Preview**: Click on any image in the preview pane to view it in full-screen mode for detailed inspection.

### 3. 🔄 Workflow Manager

- **Visualization**: Preview the structure of your ComfyUI workflow files (`.json`) without opening them.
- **Drag & Drop**: Drag workflow files from the manager directly into ComfyUI to load them instantly.

### 4. 📝 Prompt Manager

- **Library System**: Save and organize your frequently used positive and negative prompts.
- **Tagging**: Categorize prompts with tags for quick filtering.
- **One-Click Copy**: Easily copy prompt sets to your clipboard.

### 5. 📊 Task Monitor & Queue

- **Background Tasks**: Track the progress of file scanning, hash calculations, and downloads.
- **Smart Clear**: The "Clear Done" feature automatically removes completed, failed, or "not found" tasks from the list, keeping your view clean.

### 6. 🔍 Search & Filter

- **Real-time Filtering**: Instantly search for files within the current folder.
- **Deep Search**: Recursively search for files across all subdirectories.

---

## 🛠️ Installation & Usage

### Requirements

- **OS**: Windows 10/11 (Recommended)
- **Python**: 3.10 or higher
- **Dependencies**: `PySide6`, `requests`, `Pillow`, `markdown`, `markdownify`

### Installation Steps

1. **Clone or Download the Repository**

   ```bash
   git clone https://github.com/toyxyz/toyxyz_manager.git
   cd toyxyz_manager
   ```

2. **Set Up a Virtual Environment** (Recommended)

   ```bash
   python -m venv venv
   .\venv\Scripts\activate
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

### Running the App

- **Standard Mode**: Run the included `run.bat` file or execute:

  ```bash
  python main.py
  ```

- **Debug Mode**: To view detailed logs and troubleshoot issues:
  ```bash
  python main.py --debug
  ```

---

## ⚙️ Configuration Guide

After launching the app, click the **Settings** icon (top-right) to configure your asset folders.

1. **Category**: Give your folder a name (e.g., "My Checkpoints").
2. **Path**: Select the actual folder path on your disk.
3. **Mode**: Choose the folder type:
   - `model`: For ComfyUI models (Checkpoints, LoRAs, etc.).
   - `gallery`: For generated images and videos.
   - `workflow`: For `.json` workflow files.
   - `prompt`: For prompt libraries.
4. **Model Type**: (Only for `model` mode) Select the specific type (e.g., `checkpoints`, `loras`) to enable correct `Copy Node` functionality.
5. **Comfy Root**: (Optional) Set your ComfyUI installation root to enable relative path features.

---

## 💡 Tips

- **Custom Thumbnails**: Drag and drop an image onto the preview area of a model to set it as a custom thumbnail.
- **Notes**: Use the `Note` tab to write Markdown notes for any file.
- **Refresh**: Use the `🔄` button if you've added files externally and they aren't showing up.
- **Stability**: The application is optimized to handle large libraries without crashing, even during background scans.

---

## 📄 License

This project is licensed under the MIT License. Feel free to modify and distribute.
