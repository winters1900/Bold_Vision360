"""Fetch official model releases once. Runtime never downloads models."""

import hashlib
import json
from pathlib import Path
import tarfile
import requests

ROOT = Path(__file__).resolve().parents[1]


def main():
    root = ROOT / "models"
    root.mkdir(exist_ok=True)
    url = "https://www.kaggle.com/api/v1/models/google/yamnet/tensorFlow2/yamnet/1/download"
    if not (root / "yamnet/saved_model.pb").exists():
        response = requests.get(url, timeout=180)
        response.raise_for_status()
        archive = root / "yamnet.tar.gz"
        archive.write_bytes(response.content)
        with tarfile.open(archive) as tar:
            tar.extractall(root / "yamnet", filter="data")
    if not (root / "yolov8n.onnx").exists():
        from ultralytics import YOLO

        YOLO(str(root / "yolov8n.pt")).export(format="onnx", opset=17, simplify=False, imgsz=640)
    manifest = {
        "yamnet_source": url,
        "yolo_source": "https://github.com/ultralytics/assets",
        "sha256": {},
    }
    for p in root.rglob("*"):
        if p.is_file() and p.name != "manifest.json":
            manifest["sha256"][str(p.relative_to(root))] = hashlib.sha256(
                p.read_bytes()
            ).hexdigest()
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Local models ready.")


if __name__ == "__main__":
    main()
