# ToyXYZ Manager (ComfyUI Asset Manager)

**ToyXYZ Manager** is a powerful desktop application designed to manage your ComfyUI assets, including **Models**, **Workflows**, and **Example Images**. It provides a convenient interface to browse, search, and manage metadata for your local AI generation resources.

![Application Screenshot](docs/screenshot.png) _(Placeholder)_

## ✨ Key Features

### 1. Model Management

- **Centralized View**: Browse checkpoints, LoRAs, and embeddings from multiple directories.
- **Civitai Integration**: Automatically fetch metadata and thumbnails for local models.
- **Notes**: Add personal notes to any model without modifying the file itself.
- **Lazy Loading**: Optimized for performance, handling thousands of files smoothly.

### 2. Workflow Management

- **JSON Viewer**: Preview workflow JSON files directly within the app.
- **Drag & Drop**: Drag a workflow JSON from the list directly into ComfyUI.
- **Metadata Association**: Link example images and notes to specific workflows.

### 3. Example & Prompt Gallery

- **Metadata Reader**:
  - Automatically parses generation parameters (Positive/Negative prompt, Steps, Sampler, etc.) from images.
  - Supports **PNG Info** (Standard) and **JPEG Exif UserComment** with robust encoding detection (fixes Mojibake issues).
- **Metadata Writer**: Edits tags and parameters, automatically converting non-standard formats (JPEG) to standard PNG text chunks for compatibility.
- **Gallery**: Manage example images for each model or workflow.

### 4. Global Search

- **On-Demand Search**: Quickly search for files across all registered directories.
- **Flat View**: View search results in a simple list with full path context.
- **Deep Scan**: Recursively searches through subdirectories.

## 🛠️ Installation & Setup

### Prerequisites

- Python 3.10+ (Recommended)
- Windows (Tested)

### Quick Start

1.  **Clone the repository**

    ```bash
    git clone https://github.com/yourusername/toyxyz-manager.git
    cd toyxyz-manager
    ```

2.  **Setup Environment**
    Run the setup script to create a virtual environment and install dependencies.

    ```cmd
    setup_env.bat
    ```

3.  **Run the Application**
    - **Method 1 (Console hidden)**: Double-click `launcher.vbs`
    - **Method 2 (Console visible)**: Double-click `run.bat`

## ⚙️ Configuration

On first launch, click the **Settings** button to configure your directory paths:

- **Root Directories**: Add the paths where your models and workflows are stored.
- **Cache Path**: (Optional) Set a custom location for thumbnails and metadata cache.

## 🏗️ Tech Stack

- **GUI**: [PySide6](https://pypi.org/project/PySide6/) (Qt for Python)
- **Image Processing**: [Pillow](https://python-pillow.org/)
- **Core Logic**: Python Standard Library (`json`, `os`, `re`, `threading`)

## 📝 Metadata Handling Policy

To ensure maximum compatibility with the AI art ecosystem (WebUI, ComfyUI, Civitai):

- **Reading**: Supports robust parsing of both PNG Text Chunks and JPEG Exif.
- **Saving**: All metadata edits are saved as **PNG Text Chunks**. If you edit a JPEG file, it will be converted to PNG to preserve the metadata standard.

## 📄 License

[MIT License](LICENSE)
