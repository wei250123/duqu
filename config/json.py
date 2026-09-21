import json
import os
import sys
import datatime

class ConfigManager:
    def __init__(self, config_file: str):
       self._config_file = config_file
       self._config = self.load_config()
       self._logger = logging.getLogger(__name__)
       self._logger.info(f"Loaded config from {self._config_file}")
    def load_config(self) -> dict:
        with open(self._config_file, 'r') as f:
            return json.load(f)
    