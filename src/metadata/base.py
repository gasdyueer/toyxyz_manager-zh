from abc import ABC, abstractmethod
from typing import Dict, Any, Optional

class MetadataStrategy(ABC):
    @abstractmethod
    def extract(self, img) -> Optional[Dict[str, Any]]:
        pass
