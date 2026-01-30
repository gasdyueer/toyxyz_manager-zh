import re
import logging
from ..utils.network import NetworkClient

class ApiService:
    """
    Handles interactions with external APIs (Civitai, HuggingFace).
    Now separated from MetadataWorker.
    """
    def __init__(self, civitai_key="", hf_key=""):
        self.client = NetworkClient(civitai_key, hf_key)

    def fetch_civitai_version(self, file_hash):
        try:
            resp = self.client.get(f"https://civitai.com/api/v1/model-versions/by-hash/{file_hash}")
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logging.error(f"[ApiService] fetch_civitai_version error: {e}")
        return {}

    def fetch_civitai_model(self, model_id):
        try:
            resp = self.client.get(f"https://civitai.com/api/v1/models/{model_id}")
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logging.error(f"[ApiService] fetch_civitai_model error: {e}")
        return {}

    def fetch_civitai_version_by_id(self, version_id):
        try:
            resp = self.client.get(f"https://civitai.com/api/v1/model-versions/{version_id}")
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
             logging.error(f"[ApiService] fetch_civitai_version_by_id error: {e}")
        return {}

    def fetch_hf_model(self, repo_id):
        try:
            resp = self.client.get(f"https://huggingface.co/api/models/{repo_id}")
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logging.error(f"[ApiService] fetch_hf_model error: {e}")
        return {}

    def fetch_hf_readme(self, repo_id):
        url = f"https://huggingface.co/{repo_id}/resolve/main/README.md"
        try:
            return self.client.get(url).text
        except Exception:
            return "*No README.md found.*"

    def download_file(self, url, dest_dir):
        """Proxy for NetworkClient download"""
        return self.client.download_file(url, dest_dir)
