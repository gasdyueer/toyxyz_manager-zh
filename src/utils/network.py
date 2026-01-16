import os
import shutil
import time
import uuid
import logging
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

class NetworkClient:
    """
    Centralized network client with session management, retries, and safe file downloading.
    """
    def __init__(self, civitai_key=None, hf_key=None, retries=3, backoff_factor=0.3):
        self.civitai_key = civitai_key
        self.hf_key = hf_key
        self.session = requests.Session()
        
        # Configure Retries
        retry_strategy = Retry(
            total=retries,
            backoff_factor=backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        
        # Default Headers
        self.session.headers.update({
            'User-Agent': 'ComfyUI-Manager-QT',
        })

    def _get_headers(self, url):
        headers = {}
        if "civitai.com" in url and self.civitai_key:
            headers['Authorization'] = f'Bearer {self.civitai_key}'
        elif "huggingface.co" in url and self.hf_key:
            headers['Authorization'] = f'Bearer {self.hf_key}'
        return headers

    def get(self, url, stream=False, timeout=15, **kwargs):
        """Wrapper for session.get with automatic auth headers."""
        headers = self._get_headers(url)
        # Allow caller to override headers
        if 'headers' in kwargs:
            headers.update(kwargs.pop('headers'))
            
        try:
            response = self.session.get(url, headers=headers, stream=stream, timeout=timeout, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            # Caller handles exceptions (logging/UI update)
            raise e

    def download_file(self, url, dest_dir, filename=None, progress_callback=None, stop_callback=None):
        """
        Downloads a file safely using a temporary file and atomic rename.
        
        Args:
            url (str): Source URL
            dest_dir (str): Destination directory
            filename (str, optional): Target filename. If None, derived from URL or Content-Disposition.
            progress_callback (callable, optional): function(downloaded_bytes, total_bytes)
            stop_callback (callable, optional): function returning True if download should stop
            
        Returns:
            str: Absolute path to the downloaded file, or None on failure.
        """
        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir, exist_ok=True)
            
        try:
            # 1. Resolve Stream
            # Note: Allow redirects is True by default in requests
            # Handle Civitai specific model-download URLs that might redirect to S3
            with self.get(url, stream=True, timeout=30) as r:
                # Determine Filename
                if not filename:
                    # Try Content-Disposition
                    if "Content-Disposition" in r.headers:
                        from email.message import EmailMessage
                        msg = EmailMessage()
                        msg['content-disposition'] = r.headers["Content-Disposition"]
                        params = msg['content-disposition'].params
                        if 'filename' in params:
                            filename = params['filename']
                            import re
                            filename = re.sub(r'[<>:"/\\|?*]', '', filename).strip()
                    
                    if not filename:
                        path_part = url.split('?')[0]
                        filename = os.path.basename(path_part)
                        if not filename: filename = f"download_{uuid.uuid4().hex[:8]}"

                target_path = os.path.join(dest_dir, filename)
                temp_path = target_path + f".tmp.{uuid.uuid4().hex[:6]}"
                
                total_size = int(r.headers.get('content-length', 0))
                downloaded = 0
                
                with open(temp_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        # [Safety] Check for external stop signal
                        if stop_callback and stop_callback():
                             raise InterruptedError("Download interrupted by user")

                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress_callback and total_size > 0:
                                progress_callback(downloaded, total_size)
                                
                # Atomic Move
                if os.path.exists(target_path):
                    try:
                        os.remove(target_path) # Overwrite intention?
                    except OSError:
                        # [Fix] Create unique name if file is locked (e.g. video playing)
                        # OR just skip overwrite and use existing file?
                        # Skipping is better for cache efficiency.
                        logging.warning(f"[NetworkClient] File locked (in use), skipping overwrite: {filename}")
                        if os.path.exists(temp_path): os.remove(temp_path)
                        return target_path

                shutil.move(temp_path, target_path)
                return target_path

        except Exception as e:
            logging.error(f"[NetworkClient] Download failed: {e}")
            if 'temp_path' in locals() and os.path.exists(temp_path):
                os.remove(temp_path)
            raise e
