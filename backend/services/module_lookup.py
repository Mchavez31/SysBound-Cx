"""
Module codes lookup service for Willow commissioning data.
Loads from the extracted module_codes.csv or uses hardcoded mapping.
"""
import csv
from pathlib import Path
from typing import Dict, Optional

class ModuleLookup:
    def __init__(self):
        self._module_map: Dict[str, str] = {}
        self._load_modules()
    
    def _load_modules(self):
        """Load module codes from CSV if available, otherwise use hardcoded map."""
        csv_path = Path(__file__).parent / "module_codes.csv"
        
        if csv_path.exists():
            try:
                with open(csv_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        code = row.get('Value', '').strip()
                        desc = row.get('Description', '').strip()
                        if code:
                            self._module_map[code] = desc
                print(f"Loaded {len(self._module_map)} module codes from CSV")
            except Exception as e:
                print(f"Error loading module codes CSV: {e}")
                self._load_hardcoded()
        else:
            self._load_hardcoded()
    
    def _load_hardcoded(self):
        """Hardcoded common module codes based on PIMS data."""
        self._module_map = {
            # WOC Modules
            'WGL1': 'Gas Line 1',
            'WGL2': 'Gas Line 2', 
            'WGL3': 'Gas Line 3',
            'WGL4': 'Gas Line 4',
            'WGL5': 'Gas Line 5',
            'WGL7': 'Gas Line 7',
            'WGL8': 'Gas Line 8',
            'WGL9': 'Gas Line 9',
            'WGL0': 'Gas Line Common',
            'WGE1': 'Gas Equipment 1',
            'WGE9': 'Gas Equipment 9',
            'WGJ1': 'Gas J Module 1',
            'WGJ2': 'Gas J Module 2',
            'WGJ3': 'Gas J Module 3',
            'WGJ4': 'Gas J Module 4',
            'WGJ7': 'Gas J Module 7',
            'WGD1': 'Gas D Module 1',
            'WGD2': 'Gas D Module 2',
            'WGF2': 'Gas F Module 2',
            'WGG1': 'Gas G Module 1',
            'WGPT': 'Gas Production Train',
            'WGRT': 'Gas Recovery Train',
            # WF Modules
            'WFA1': 'Field Module A1',
            'WFA2': 'Field Module A2',
            'WFA3': 'Field Module A3',
            'WFB1': 'Field Module B1',
            'WFB2': 'Field Module B2',
            'WFB3': 'Field Module B3',
            'WFG1': 'Field Module G1',
            'WFG2': 'Field Module G2',
            'WFT1': 'Field Train 1',
            'WFT2': 'Field Train 2',
            'WFT3': 'Field Train 3',
            # BT Modules
            'BT1M': 'Battery 1 Main',
            'BT1S': 'Battery 1 Satellite',
            'BT2M': 'Battery 2 Main',
            'BT2S': 'Battery 2 Satellite',
            'BT3M': 'Battery 3 Main',
            'BT3S': 'Battery 3 Satellite',
        }
    
    def get_description(self, module_code: str) -> Optional[str]:
        """Get description for a module code."""
        return self._module_map.get(module_code)
    
    def is_valid_module(self, module_code: str) -> bool:
        """Check if a module code is valid."""
        return module_code in self._module_map

# Global instance
_lookup = None

def get_module_lookup() -> ModuleLookup:
    """Get singleton module lookup instance."""
    global _lookup
    if _lookup is None:
        _lookup = ModuleLookup()
    return _lookup
