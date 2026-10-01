from collections import defaultdict, deque
from pathlib import Path
import os
import sys
import pytesseract
from PIL import Image, ImageDraw


def _configure_tesseract() -> None:
    appdata = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
    app_name = "Cheating Mommy"
    data_dir_candidates: list[str] = []

    base_dir = os.path.dirname(os.path.abspath(__file__))
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base_dir = sys._MEIPASS
    install_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
    data_hint_path = os.path.join(install_dir, "data_dir.txt")
    if os.path.isfile(data_hint_path):
        try:
            with open(data_hint_path, "r", encoding="utf-8") as f:
                hinted_dir = f.read().strip()
            if hinted_dir:
                data_dir_candidates.append(hinted_dir)
        except OSError:
            pass

    if appdata:
        data_dir_candidates.append(os.path.join(appdata, app_name))

    for data_dir in data_dir_candidates:
        app_tess = os.path.join(data_dir, "tesseract")
        app_exe = os.path.join(app_tess, "tesseract.exe")
        if os.path.isfile(app_exe):
            pytesseract.pytesseract.tesseract_cmd = app_exe
            tessdata = os.path.join(app_tess, "tessdata")
            if os.path.isdir(tessdata):
                os.environ.setdefault("TESSDATA_PREFIX", tessdata)
            return

    tesseract_dir = os.path.join(base_dir, "tesseract")
    tesseract_exe = os.path.join(tesseract_dir, "tesseract.exe")
    if os.path.isfile(tesseract_exe):
        pytesseract.pytesseract.tesseract_cmd = tesseract_exe
        tessdata = os.path.join(tesseract_dir, "tessdata")
        if os.path.isdir(tessdata):
            os.environ.setdefault("TESSDATA_PREFIX", tessdata)


_configure_tesseract()


def warmup_tesseract() -> None:
    """Trigger a one-time Tesseract call to avoid first-use popup during OCR."""
    try:
        _ = pytesseract.get_tesseract_version()
    except Exception:
        pass


def ocr(
    image_path: str = "./img/screenshot.png",
    image: Image.Image | None = None,
    *,
    config: str | None = None,
    lang: str = "rus+eng",
    crop_bbox: tuple[int, int, int, int] | None = None,
    crop_clamp: bool = True,
    mode: str = "chunk",  # "line" or "chunk"
    visualize: bool = False,
    visualize_path: str = "./img/ocr_bboxes.png",
    x_thresh: float = 20,  # horizontal gap for merging in chunk mode
    y_thresh: float = 8,   # vertical gap for merging in chunk mode
    group_y_thresh: float = 35  # vertical gap to separate different question groups
):
    """
    Perform OCR on an image.

    Returns:
        A list of dictionaries for each chunk:
        {
            "text": "chunk text",
            "bbox": (x, y, w, h),
            "group_id": 1
        }
    """
    original_image = image or Image.open(image_path)

    offset_x = 0
    offset_y = 0
    image = original_image
    if crop_bbox is not None:
        x, y, w, h = crop_bbox
        left, top, right, bottom = x, y, x + w, y + h

        if crop_clamp:
            img_w, img_h = original_image.size
            left = max(0, min(left, img_w))
            right = max(0, min(right, img_w))
            top = max(0, min(top, img_h))
            bottom = max(0, min(bottom, img_h))

        if right <= left or bottom <= top:
            raise ValueError(f"Invalid crop_bbox after clamping: {crop_bbox!r}")

        offset_x = left
        offset_y = top
        image = original_image.crop((left, top, right, bottom))

    extra_kwargs: dict = {"output_type": pytesseract.Output.DICT}
    if lang:
        extra_kwargs["lang"] = lang
    if config:
        extra_kwargs["config"] = config

    try:
        data = pytesseract.image_to_data(image, **extra_kwargs)
    except Exception:
        # Fallback if configured language packs are missing
        if lang and lang != "eng":
            extra_kwargs["lang"] = "eng"
            try:
                data = pytesseract.image_to_data(image, **extra_kwargs)
            except Exception:
                extra_kwargs.pop("lang", None)
                data = pytesseract.image_to_data(image, **extra_kwargs)
        else:
            raise

    results = []

    # ---- LINE MODE ----
    if mode == "line":
        lines = defaultdict(list)
        for i, text in enumerate(data["text"]):
            if text.strip():
                line_num = data["line_num"][i]
                lines[line_num].append(
                    (
                        text,
                        data["left"][i],
                        data["top"][i],
                        data["width"][i],
                        data["height"][i],
                    )
                )
        for line_num, words in lines.items():
            full_text = " ".join([word[0] for word in words])
            x = min([word[1] for word in words])
            y = min([word[2] for word in words])
            w = max([word[1] + word[3] for word in words]) - x
            h = max([word[2] + word[4] for word in words]) - y
            results.append({"text": full_text, "bbox": (x + offset_x, y + offset_y, w, h)})

    # ---- CHUNK MODE ----
    elif mode == "chunk":
        boxes = []
        for i, text in enumerate(data["text"]):
            if text.strip():
                boxes.append({
                    "text": text,
                    "x": data["left"][i],
                    "y": data["top"][i],
                    "w": data["width"][i],
                    "h": data["height"][i],
                    "used": False
                })

        # compute gaps between boxes
        def box_distance(box1, box2):
            x_gap = max(box2["x"] - (box1["x"] + box1["w"]),
                        box1["x"] - (box2["x"] + box2["w"]),
                        0)
            y_gap = max(box2["y"] - (box1["y"] + box1["h"]),
                        box1["y"] - (box2["y"] + box2["h"]),
                        0)
            return x_gap, y_gap

        def is_close(box1, box2):
            x_gap, y_gap = box_distance(box1, box2)
            return x_gap <= x_thresh and y_gap <= y_thresh

        # merge boxes into chunks
        for i, box in enumerate(boxes):
            if box["used"]:
                continue
            chunk_text = box["text"]
            x1, y1 = box["x"], box["y"]
            x2, y2 = box["x"] + box["w"], box["y"] + box["h"]
            box["used"] = True

            queue = deque([box])
            while queue:
                current = queue.popleft()
                for other in boxes:
                    if not other["used"] and is_close(current, other):
                        x1 = min(x1, other["x"])
                        y1 = min(y1, other["y"])
                        x2 = max(x2, other["x"] + other["w"])
                        y2 = max(y2, other["y"] + other["h"])
                        chunk_text += " " + other["text"]
                        other["used"] = True
                        queue.append(other)

            results.append({"text": chunk_text, "bbox": (x1, y1, x2 - x1, y2 - y1)})
        if offset_x or offset_y:
            for r in results:
                x, y, w, h = r["bbox"]
                r["bbox"] = (x + offset_x, y + offset_y, w, h)

    else:
        raise ValueError("mode must be 'line' or 'chunk'")

    # ---- Assign group IDs ----
    results.sort(key=lambda r: r["bbox"][1])  # sort by y (top)
    group_id = 1
    last_y = None
    for r in results:
        y = r["bbox"][1]
        if last_y is None or (y - last_y) > group_y_thresh:
            group_id += 1
        r["group_id"] = group_id
        last_y = y

    # ---- Visualization ----
    if visualize:
        annotated = (original_image if (offset_x or offset_y) else image).convert("RGB").copy()
        draw = ImageDraw.Draw(annotated)
        if offset_x or offset_y:
            left, top = offset_x, offset_y
            right, bottom = offset_x + image.size[0], offset_y + image.size[1]
            draw.rectangle([left, top, right, bottom], outline="yellow", width=2)
        for r in results:
            x, y, w, h = r["bbox"]
            draw.rectangle([x, y, x + w, y + h], outline="lime", width=2)
            draw.text((x, max(0, y - 12)), f"[G{r['group_id']}] {r['text'][:30]}", fill="lime")
        out_path = Path(visualize_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        annotated.save(out_path)
        print(f"Saved OCR bbox visualization to: {out_path}")

    # ---- Print results ----
    # for r in results:
    #     print(f"G{r['group_id']}: {r['text']} //// \nBBOX: {r['bbox']} ////\n")

    return results


def main() -> None:
    ocr(image_path="./img/test_img.jpg", mode="chunk", visualize=True)


if __name__ == "__main__":
    main()
