"""Extrae la ultima imagen pegada del transcript de Claude Code (.jsonl) y la guarda como PNG."""
import json
import base64
import sys
from pathlib import Path
from PIL import Image
from io import BytesIO

def extract_last_image(jsonl_path: Path, output_path: Path) -> bool:
    last_image_bytes = None
    last_media_type = None
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = rec.get("message") or rec
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "image":
                    source = block.get("source", {})
                    if source.get("type") == "base64":
                        last_image_bytes = base64.b64decode(source.get("data", ""))
                        last_media_type = source.get("media_type", "image/png")
    if not last_image_bytes:
        print("NO_IMAGE_FOUND")
        return False
    img = Image.open(BytesIO(last_image_bytes))
    if img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        bg.paste(img, mask=img.split()[-1] if img.mode in ("RGBA", "LA") else None)
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG")
    print(f"OK  media_type={last_media_type}  size={img.size}  bytes={output_path.stat().st_size}  path={output_path}")
    return True

if __name__ == "__main__":
    jsonl = Path(sys.argv[1])
    out = Path(sys.argv[2])
    extract_last_image(jsonl, out)
