# Toyxyz Manager

The toyxyz manager is a model, workflow, and prompt management tool designed to be used together with ComfyUI.

<img width="2254" height="1472" alt="image" src="https://github.com/user-attachments/assets/d10dbdcf-2a48-4f5b-87f7-d2849abd316f" />


---

## Installation

1. **Environment Setup**
Run `setup_env.bat`. Wait until the venv (virtual environment) is installed. Once complete, close the window.
2. **Execution**
Run `run.bat` or `launcher.vbs`. Both perform the same function; however, `run.bat` will display the command prompt (CMD) window. Use `run.bat` if you need to check for errors. If everything is working correctly, use `launcher.vbs`.

---

## Usage

### 1. Settings

First, enter the paths for your models, workflows, and prompts in the Settings menu located at the top-left. Each path must be designated as one of the following modes:

**model**: Checkpoint models.
* If the mode is set to 'model', you must specify the model type (e.g., LoRA, VAE, etc.). This setting is used for the Copy Node feature.
* ComfyUI Root : This refers to the root path specified when using the model loader within ComfyUI. This is also used for the Copy Node feature.

**workflow**: The path where ComfyUI workflow files (.json) are located.

**prompt**: The path where prompt presets will be saved.

**gallery**: The path where images and videos are located.

**Cache folder**: Designates the path where hashes, notes, and examples for specific models are stored. If left unspecified, a 'cache' folder will be automatically created in the directory where the current script is located.

---

### 2. Interface Overview

Select your desired mode from the tabs at the top. Each tab consists of a Tree View on the left, a Media View in the center, and a Detail View on the right.

* **Model**: Select models from the list and display the model's thumbnail and example detail notes.
* **Workflow**: Browse workflows and display notes and examples.
* **Prompt**: Create and modify prompt presets. Displays notes and examples.
* **Gallery**: Explore images and videos created with Comfyui. Displays the image's metadata.
* **Tasks**: Displays the real-time progress of ongoing operations, such as model and metadata downloads.

#### Tree View

* You can browse through directories in the Tree View. If multiple paths have been configured in the settings, you can select the desired path from the dropdown list at the top.

#### Media View

* The Media View allows you to browse thumbnails. You can open a workflow by dragging and dropping a thumbnail onto the ComfyUI canvas.
* When dragging thumbnails in the Model tab, the image file is used.
* In the Workflow tab, the .json file is used.
* By using the Copy button at the bottom of the Media View, the currently selected model is copied as its corresponding loader node. You can then paste it directly onto the ComfyUI canvas. In the Workflow tab, all nodes within that workflow are copied.
* *Note: The copy function may not work correctly if the workflow includes specific nodes such as "Everywhere" or "Set/Get" nodes.*



#### Detail View

* **Media Management**: You can upload, delete, and view example images and videos. You can also open workflows by dragging and dropping these example images onto the ComfyUI canvas.
* **Notes**: Allows you to save detailed information, including attached images and external links.
* **Auto Match**: Displayed in the Detail View of the Model tab. If the selected model is available on Civitai, it automatically downloads metadata, thumbnails, and example images. Please note that the first execution may take longer as it calculates the model's hash.
* **Manual URL**: Allows you to download metadata by manually entering a URL from Civitai or Hugging Face.
* **Download Model**: Downloads a model from a provided Civitai or Hugging Face URL. For Hugging Face, you must provide the direct link to a single model file. Example: (https://huggingface.co/lightx2v/Wan2.1-T2V-1.3B-longcat-step500/blob/main/adapter_model.safetensors)


---
