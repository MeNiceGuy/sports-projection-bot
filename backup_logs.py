from pathlib import Path
from datetime import datetime
import shutil

ROOT = Path(__file__).resolve().parent
LOGS = ROOT / "logs"
BACKUP = ROOT / "backups" / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

BACKUP.mkdir(parents=True, exist_ok=True)

for file in LOGS.glob("*"):
    if file.is_file():
        shutil.copy2(file, BACKUP / file.name)

print(f"Backup created: {BACKUP}")
