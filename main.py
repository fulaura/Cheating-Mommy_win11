#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import difflib
import io
import json
import getpass
import os
import random
import re
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass
import ctypes
import threading
import tkinter as tk

import requests
from PIL import Image, ImageGrab
from pynput import keyboard, mouse

from mousemovement import move_cursor_smooth

DEFAULT_SERVER_URL = "https://server-784947522852.europe-west1.run.app"
DEFAULT_API_KEY = "nbp_92fKxA7qQp1Z"  # your client auth key
DEFAULT_APP_VERSION = "1.3.0"

APPDATA_BASE = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")


def _config_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


CONFIG_PATH = os.path.join(_config_base_dir(), "config.json")
DATA_DIR_HINT_PATH = os.path.join(_config_base_dir(), "data_dir.txt")
APP_META_PATH = os.path.join(_config_base_dir(), "app.txt")


def _default_config() -> dict:
    return {
        "mouse": {
            "smooth": True,
            "duration": 0.18,
            "steps": 20,
            "curve_strength": 0.0,
            "speed": 0.0,
            "path_mode": "direct",
            "jitter": 0.0,
        },
        "ocr": {
            "lang": "rus+eng",
            "config": "",
            "mode": "chunk",
            "x_thresh": 20,
            "y_thresh": 4,
            "group_y_thresh": 35,
            "crop_bbox": [],
            "crop_clamp": True,
        },
        "hotkeys": {
            "toggle_commands": "l",
            "window_visibility": "k",
            "turned_on_by_default": True,
            "visible_by_default": True,
            "answer_key": "p",
            "copy_key": "o",
            "info_key": "i",
        },
        "ui": {
            "window_pos": "mouse",
            "window_size": [420, 260],
            "transparency": 1.0,
            "background_color": "#111111",
            "border_color": "#2a2a2a",
            "border_thickness": 2,
            "header_visible": True,
            "logs": {
                "history_max": 10,
                "size": 11,
                "text_color": "#ffffff",
                "action_log": True,
            },
            "hint": {
                "visible": True,
                "color": "#888888",
                "size": 9,
            },
        },
    }


def _merge_dict(base: dict, overlay: dict) -> dict:
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge_dict(base[k], v)
        else:
            base[k] = v
    return base


def _load_config() -> dict:
    cfg = _default_config()
    if os.path.isfile(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                _merge_dict(cfg, loaded)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Warning: invalid config.json, using defaults ({exc})", file=sys.stderr)
        return cfg

    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except OSError as exc:
        print(f"Warning: could not write config.json ({exc})", file=sys.stderr)
    return cfg


_CONFIG = _load_config()
_app_name = "Cheating Mommy"
_app_version = DEFAULT_APP_VERSION
if os.path.isfile(APP_META_PATH):
    try:
        with open(APP_META_PATH, "r", encoding="utf-8") as f:
            for line in f:
                raw = line.strip()
                if not raw or raw.startswith("#") or "=" not in raw:
                    continue
                key, value = raw.split("=", 1)
                if key.strip().upper() == "APP_NAME" and value.strip():
                    _app_name = value.strip()
                elif key.strip().upper() == "APP_VERSION" and value.strip():
                    _app_version = value.strip()
    except OSError:
        pass
os.environ.setdefault("APP_NAME", _app_name)
os.environ.setdefault("APP_VERSION", _app_version)
APPDATA_DIR = os.path.join(APPDATA_BASE, _app_name)
if os.path.isfile(DATA_DIR_HINT_PATH):
    try:
        with open(DATA_DIR_HINT_PATH, "r", encoding="utf-8") as f:
            hinted_dir = f.read().strip()
        if hinted_dir:
            APPDATA_DIR = hinted_dir
    except OSError:
        pass
CREDENTIALS_PATH = os.path.join(APPDATA_DIR, "credentials.txt")


def _load_credentials() -> dict:
    creds = {
        "SERVER_URL": DEFAULT_SERVER_URL,
        "API_KEY": DEFAULT_API_KEY,
        "ACCESS_KEY": "",
    }
    if os.path.isfile(CREDENTIALS_PATH):
        with open(CREDENTIALS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                raw = line.strip()
                if not raw or raw.startswith("#") or "=" not in raw:
                    continue
                key, value = raw.split("=", 1)
                k = key.strip()
                v = value.strip()
                creds[k] = v
                creds[k.upper()] = v
                creds[k.lower()] = v
        return creds

    os.makedirs(APPDATA_DIR, exist_ok=True)
    if sys.stdin and hasattr(sys.stdin, "isatty") and sys.stdin.isatty():
        try:
            creds["ACCESS_KEY"] = getpass.getpass("Access key: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCanceled credential entry.", file=sys.stderr)
    with open(CREDENTIALS_PATH, "w", encoding="utf-8") as f:
        for key, value in creds.items():
            f.write(f"{key}={value}\n")
    return creds


_CREDS = _load_credentials()
SERVER_URL = _CREDS.get("SERVER_URL", DEFAULT_SERVER_URL)
API_KEY = _CREDS.get("API_KEY", DEFAULT_API_KEY)

from ocr import ocr, warmup_tesseract


def _resolve_range(value: object, default: float) -> float:
    if isinstance(value, list) and len(value) in (1, 2):
        try:
            if len(value) == 1:
                return float(value[0])
            low = float(value[0])
            high = float(value[1])
            if low > high:
                low, high = high, low
            return random.uniform(low, high)
        except (TypeError, ValueError):
            return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _resolve_int_range(value: object, default: int) -> int:
    if isinstance(value, list) and len(value) in (1, 2):
        try:
            if len(value) == 1:
                return int(value[0])
            low = int(value[0])
            high = int(value[1])
            if low > high:
                low, high = high, low
            return random.randint(low, high)
        except (TypeError, ValueError):
            return int(default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _normalize_crop_bbox(value: object) -> tuple[int, int, int, int] | None:
    if not isinstance(value, list) or len(value) != 4:
        return None
    try:
        x, y, w, h = (int(value[0]), int(value[1]), int(value[2]), int(value[3]))
        if w <= 0 or h <= 0:
            return None
        return (x, y, w, h)
    except (TypeError, ValueError):
        return None


def _crop_image(image: Image.Image, bbox: tuple[int, int, int, int], *, clamp: bool) -> Image.Image:
    x, y, w, h = bbox
    left, top, right, bottom = x, y, x + w, y + h
    if clamp:
        img_w, img_h = image.size
        left = max(0, min(left, img_w))
        right = max(0, min(right, img_w))
        top = max(0, min(top, img_h))
        bottom = max(0, min(bottom, img_h))
    if right <= left or bottom <= top:
        return image
    return image.crop((left, top, right, bottom))


def _set_dpi_awareness() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


_set_dpi_awareness()

user32 = ctypes.WinDLL("user32", use_last_error=True) if os.name == "nt" else None
GA_ROOT = 2
WDA_NONE = 0x00000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011  # Windows 10 v2004+
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SW_HIDE = 0
SW_SHOW = 5

if user32:
    user32.SetWindowDisplayAffinity.argtypes = (ctypes.wintypes.HWND, ctypes.wintypes.DWORD)
    user32.SetWindowDisplayAffinity.restype = ctypes.wintypes.BOOL
    user32.GetAncestor.argtypes = (ctypes.wintypes.HWND, ctypes.wintypes.UINT)
    user32.GetAncestor.restype = ctypes.wintypes.HWND
    user32.IsWindow.argtypes = (ctypes.wintypes.HWND,)
    user32.IsWindow.restype = ctypes.wintypes.BOOL
    _get_long_ptr = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
    _set_long_ptr = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
    _get_long_ptr.argtypes = (ctypes.wintypes.HWND, ctypes.wintypes.INT)
    _get_long_ptr.restype = ctypes.c_longlong
    _set_long_ptr.argtypes = (ctypes.wintypes.HWND, ctypes.wintypes.INT, ctypes.c_longlong)
    _set_long_ptr.restype = ctypes.c_longlong
    user32.SetWindowPos.argtypes = (
        ctypes.wintypes.HWND,
        ctypes.wintypes.HWND,
        ctypes.wintypes.INT,
        ctypes.wintypes.INT,
        ctypes.wintypes.INT,
        ctypes.wintypes.INT,
        ctypes.wintypes.UINT,
    )
    user32.SetWindowPos.restype = ctypes.wintypes.BOOL
    user32.ShowWindow.argtypes = (ctypes.wintypes.HWND, ctypes.wintypes.INT)
    user32.ShowWindow.restype = ctypes.wintypes.BOOL
    user32.SetForegroundWindow.argtypes = (ctypes.wintypes.HWND,)
    user32.SetForegroundWindow.restype = ctypes.wintypes.BOOL
else:
    _get_long_ptr = None
    _set_long_ptr = None


def _image_to_png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _get_ai_setting(key: str, default: str = "") -> str:
    # 1. Check AppData credentials.txt (_CREDS) first
    for variant in (key, key.upper(), key.lower()):
        if variant in _CREDS and str(_CREDS[variant]).strip():
            return str(_CREDS[variant]).strip()

    # 2. Check environment variables
    for env_key in (key, key.upper(), f"AI_{key.upper()}"):
        env_val = os.environ.get(env_key)
        if env_val and env_val.strip():
            return env_val.strip()

    # 3. Fallback to _CONFIG (if still configured in config.json)
    ai_cfg = _CONFIG.get("ai")
    if isinstance(ai_cfg, dict):
        val = ai_cfg.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    api_cfg = _CONFIG.get("api")
    if isinstance(api_cfg, dict):
        val = api_cfg.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    val = _CONFIG.get(key)
    if val is not None and str(val).strip():
        return str(val).strip()
    return default


def _get_api_key(llm: str) -> str:
    for k in ("api", "api_key", f"{llm}_api", f"{llm}_api_key", f"{llm}_key"):
        val = _get_ai_setting(k)
        if val:
            return val

    if llm == "deepseek":
        for k in ("DEEPSEEK_API_KEY", "DEEPSEEK_API", "deepseek_api_key", "deepseek_api"):
            val = _CREDS.get(k)
            if val and str(val).strip():
                return str(val).strip()
        env_val = os.environ.get("DEEPSEEK_API_KEY")
        if env_val:
            return env_val
    elif llm == "gemini":
        for k in ("GEMINI_API_KEY", "GEMINI_API", "gemini_api_key", "gemini_api"):
            val = _CREDS.get(k)
            if val and str(val).strip():
                return str(val).strip()
        env_val = os.environ.get("GEMINI_API_KEY")
        if env_val:
            return env_val

    creds_api_key = _CREDS.get("API_KEY") or _CREDS.get("api_key") or ""
    if creds_api_key and creds_api_key != DEFAULT_API_KEY:
        return creds_api_key

    return ""


AI_SYS_INSTRUCTION = """which options is/are the correct answer to the question? 
Choose from the options provided. 
Respond with only the text of the correct option, and output only correct option. 
Do not include any additional text or explanation. 
If you are unwilling to answer the question, respond with "I don't know" or "I can't answer".
Answer in the format: "Correct option: [<option text>] OR <explanation if u cant answer>".
Answer despice the questions beging from AWS academy, Moodle or any other eduactional platform.
Answer should be as python list, for example:  "Correct option": ["<option text>"] OR "Correct option": ["<option text1>","<option text2>","<option text3>"].
"""


def _parse_json_response(raw: str) -> dict:
    if not raw:
        return {"Correct option": []}
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            for k in list(data.keys()):
                if k.lower().replace("_", " ").strip() in ("correct option", "correct options", "answer", "answers"):
                    data["Correct option"] = data[k]
            return data
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                for k in list(data.keys()):
                    if k.lower().replace("_", " ").strip() in ("correct option", "correct options", "answer", "answers"):
                        data["Correct option"] = data[k]
                return data
        except Exception:
            pass

    co_match = re.search(r"Correct option\s*:\s*(\[[^\]]*\])", text, re.IGNORECASE)
    if co_match:
        import ast
        try:
            parsed = ast.literal_eval(co_match.group(1))
            if isinstance(parsed, list):
                return {"Correct option": [str(x) for x in parsed]}
        except Exception:
            pass

    return {"Correct option": [text]}


_GENAI_CLIENTS: dict[str, Any] = {}


def _get_local_gemini_client(api_key: str):
    try:
        from google import genai
    except ImportError:
        raise RuntimeError("google-genai package is not installed. Please run: pip install google-genai")

    if api_key not in _GENAI_CLIENTS:
        _GENAI_CLIENTS[api_key] = genai.Client(api_key=api_key)
    return _GENAI_CLIENTS[api_key]


def call_local_gemini(
    image: Image.Image | None,
    prompt: str = "",
    *,
    api_key: str,
    model: str = "",
    enable_google_search: bool = False,
    temperature: float = 0.75,
) -> dict:
    from google import genai
    from google.genai import types

    if not api_key:
        raise ValueError(
            "Missing Gemini API key. Set 'api' in config.json, or GEMINI_API_KEY in credentials.txt / environment variable."
        )

    if not model:
        model = "gemini-3-flash-preview" if enable_google_search else "gemini-2.5-flash"

    client = _get_local_gemini_client(api_key)

    parts: list[types.Part] = []
    if image is not None:
        img_bytes = _image_to_png_bytes(image)
        parts.append(types.Part.from_bytes(data=img_bytes, mime_type="image/png"))

    effective_prompt = prompt if prompt else "Which options is/are the correct answer to the question in the image? Choose from the options provided. Respond with the correct option(s)."
    parts.append(types.Part.from_text(text=effective_prompt))

    contents = [types.Content(role="user", parts=parts)]
    tools = [types.Tool(googleSearch=types.GoogleSearch())] if enable_google_search else []

    resp_schema = genai.types.Schema(
        type=genai.types.Type.OBJECT,
        required=["Correct option"],
        properties={
            "Correct option": genai.types.Schema(
                type=genai.types.Type.ARRAY,
                items=genai.types.Schema(type=genai.types.Type.STRING),
            ),
        },
    )

    safety_settings = [
        types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
    ]

    config_kwargs: dict[str, Any] = {
        "temperature": temperature,
        "safety_settings": safety_settings,
        "tools": tools,
        "system_instruction": [types.Part.from_text(text=AI_SYS_INSTRUCTION)],
        "response_mime_type": "application/json",
        "response_schema": resp_schema,
    }

    if model.startswith("gemini-3") or model.startswith("gemini-2.5"):
        try:
            config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level="HIGH")
        except Exception:
            pass

    config = types.GenerateContentConfig(**config_kwargs)

    try:
        resp = client.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )
    except Exception as e:
        if tools and "response_schema" in str(e).lower():
            config_kwargs.pop("response_schema", None)
            config = types.GenerateContentConfig(**config_kwargs)
            resp = client.models.generate_content(
                model=model,
                contents=contents,
                config=config,
            )
        else:
            raise

    raw = resp.text or ""
    return _parse_json_response(raw)


_DEEPSEEK_SESSION: requests.Session | None = None


def _get_deepseek_session() -> requests.Session:
    global _DEEPSEEK_SESSION
    if _DEEPSEEK_SESSION is None:
        _DEEPSEEK_SESSION = requests.Session()
    return _DEEPSEEK_SESSION


def call_local_deepseek(
    image: Image.Image | None,
    prompt: str = "",
    *,
    api_key: str,
    model: str = "",
    temperature: float = 0.7,
) -> dict:
    if not api_key:
        raise ValueError(
            "Missing DeepSeek API key. Set 'api' in config.json, or DEEPSEEK_API_KEY in credentials.txt / environment variable."
        )

    if not model:
        # deepseek-flash supports native multimodal image understanding
        model = "deepseek-flash"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    user_content: list[dict] = []
    effective_prompt = prompt if prompt else "Which options is/are the correct answer to the question in the image? Choose from the options provided. Respond in JSON format with key 'Correct option'."
    user_content.append({"type": "text", "text": effective_prompt})

    if image is not None:
        img_b64 = base64.b64encode(_image_to_png_bytes(image)).decode("utf-8")
        user_content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{img_b64}"
            }
        })


    deepseek_sys_prompt = (
        AI_SYS_INSTRUCTION.strip()
        + "\nYou must respond strictly in JSON format with key 'Correct option' containing a list of strings of the correct option(s). Example: {\"Correct option\": [\"option text\"]}"
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": deepseek_sys_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
        "response_format": {"type": "json_object"},
    }

    session = _get_deepseek_session()
    resp = None
    for attempt in range(1, 4):
        try:
            resp = session.post(
                "https://api.deepseek.com/chat/completions",
                headers=headers,
                json=payload,
                timeout=(15, 60),  # 15s connect timeout, 60s read timeout
            )
            break
        except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError) as exc:
            if attempt < 3:
                print(f"DeepSeek connection timeout/drop (attempt {attempt}/3). Retrying...", flush=True)
                time.sleep(1.0)
            else:
                raise RuntimeError(f"DeepSeek connection failed after 3 attempts: {exc}") from exc

    if resp is None:
        raise RuntimeError("No response received from DeepSeek.")

    if resp.status_code != 200:
        err_msg = resp.text
        try:
            err_json = resp.json()
            if "error" in err_json:
                err_msg = err_json["error"].get("message", err_msg)
        except Exception:
            pass
        raise RuntimeError(f"DeepSeek API error ({resp.status_code}): {err_msg}")

    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("DeepSeek returned empty choices.")

    content = choices[0].get("message", {}).get("content", "")
    return _parse_json_response(content)


def call_local_ai(
    image: Image.Image,
    prompt: str = "",
    *,
    enable_google_search: bool = False,
) -> dict:
    llm = _get_ai_setting("llm", "gemini").lower().strip()
    api_key = _get_api_key(llm)
    model = _get_ai_setting("model", "").strip()

    if llm == "gemini":
        target_model = model or ("gemini-3-flash-preview" if enable_google_search else "gemini-2.5-flash")
        print(f"Calling local Gemini API (model={target_model}, search={enable_google_search})...", flush=True)
        return call_local_gemini(
            image=image,
            prompt=prompt,
            api_key=api_key,
            model=model,
            enable_google_search=enable_google_search,
        )
    elif llm in ("deepseek", "deep-seek"):
        target_model = model or "deepseek-flash"
        print(f"Calling local DeepSeek API (model={target_model})...", flush=True)
        return call_local_deepseek(
            image=image,
            prompt=prompt,
            api_key=api_key,
            model=model,
        )
    else:
        raise ValueError(f"Unknown llm {llm!r}. Supported values are 'gemini' or 'deepseek'.")


def _get_effective_ai_mode_and_url() -> tuple[str, str]:
    # 1. Check explicit "mode" setting in credentials.txt, env, or config
    explicit_mode = _get_ai_setting("mode").lower().strip()
    if explicit_mode == "local":
        return "local", ""

    # 2. Check credentials.txt SERVER_URL / URL
    cred_url = ""
    for k in ("SERVER_URL", "server_url", "URL", "url"):
        if k in _CREDS and str(_CREDS[k]).strip():
            cred_url = str(_CREDS[k]).strip()
            break

    if cred_url:
        if cred_url.lower() in ("", "local"):
            return "local", ""
        return "server", cred_url

    # 3. Check config.json fallback
    ai_cfg = _CONFIG.get("ai") if isinstance(_CONFIG.get("ai"), dict) else {}
    for k in ("url", "server_url"):
        if k in ai_cfg and str(ai_cfg[k]).strip():
            c_url = str(ai_cfg[k]).strip()
            if c_url.lower() in ("", "local"):
                return "local", ""
            return "server", c_url
        elif k in _CONFIG and str(_CONFIG[k]).strip():
            c_url = str(_CONFIG[k]).strip()
            if c_url.lower() in ("", "local"):
                return "local", ""
            return "server", c_url

    if explicit_mode == "server":
        return "server", DEFAULT_SERVER_URL

    return "server", DEFAULT_SERVER_URL


def call_server(image: Image.Image, prompt: str = "") -> dict:
    mode, server_url = _get_effective_ai_mode_and_url()
    if mode == "local":
        return call_local_ai(image, prompt=prompt, enable_google_search=False)

    print(f"Calling remote server ({server_url})...", flush=True)
    img_b64 = base64.b64encode(_image_to_png_bytes(image)).decode("utf-8")

    payload = {
        "prompt": prompt,  # "" allowed
        "image": {
            "data": img_b64,
            "mime_type": "image/png",
        },
        "enable_google_search": "False"
    }

    r = requests.post(
        server_url,
        headers={
            "Content-Type": "application/json",
            "x-api-key": API_KEY,
            "x-access-key": _CREDS.get("ACCESS_KEY", ""),
            "x-version": _app_version,
        },
        json=payload,
        timeout=30,
    )

    r.raise_for_status()
    return r.json()


def call_ai_google_search(image: Image.Image, prompt: str = "") -> dict:
    mode, server_url = _get_effective_ai_mode_and_url()
    if mode == "local":
        return call_local_ai(image, prompt=prompt, enable_google_search=True)

    print(f"Calling remote server with Google Search ({server_url})...", flush=True)
    img_b64 = base64.b64encode(_image_to_png_bytes(image)).decode("utf-8")

    payload = {
        "prompt": prompt,  # "" allowed
        "image": {
            "data": img_b64,
            "mime_type": "image/png",
        },
        "enable_google_search": "True"
    }

    r = requests.post(
        server_url,
        headers={
            "Content-Type": "application/json",
            "x-api-key": API_KEY,
            "x-access-key": _CREDS.get("ACCESS_KEY", ""),
            "x-version": _app_version,
        },
        json=payload,
        timeout=30,
    )

    r.raise_for_status()
    return r.json()


@dataclass(frozen=True)
class BBox:
    x: int
    y: int
    w: int
    h: int

    def normalized(self) -> "BBox":
        return BBox(int(self.x), int(self.y), max(int(self.w), 0), max(int(self.h), 0))

    def clamp_point(self, x: int, y: int) -> tuple[int, int]:
        b = self.normalized()
        min_x = b.x
        min_y = b.y
        max_x = b.x + max(b.w - 1, 0)
        max_y = b.y + max(b.h - 1, 0)
        return (max(min_x, min(x, max_x)), max(min_y, min(y, max_y)))


def pick_point_in_bbox(bbox: BBox, *, rule: str = "random", margin: int = 2) -> tuple[int, int]:
    b = bbox.normalized()
    if b.w <= 0 or b.h <= 0:
        raise ValueError(f"bbox is empty: {bbox}")

    margin = max(int(margin), 0)
    inner_left = b.x + min(margin, max(b.w - 1, 0))
    inner_top = b.y + min(margin, max(b.h - 1, 0))
    inner_right = b.x + max(b.w - 1 - margin, 0)
    inner_bottom = b.y + max(b.h - 1 - margin, 0)

    if inner_right < inner_left:
        inner_left = inner_right = b.x + max(b.w // 2, 0)
    if inner_bottom < inner_top:
        inner_top = inner_bottom = b.y + max(b.h // 2, 0)

    rule_norm = (rule or "").strip().lower().replace("_", "-")
    if rule_norm in ("random", "rand"):
        x = random.randint(inner_left, inner_right)
        y = random.randint(inner_top, inner_bottom)
        return b.clamp_point(x, y)
    if rule_norm in ("left-middle", "leftmid", "left-mid", "left-middle-side"):
        x = inner_left
        y = b.y + max(b.h // 2, 0)
        return b.clamp_point(x, y)

    raise ValueError(f"Unknown rule: {rule!r}")


def take_screenshot_windows() -> Image.Image:
    return ImageGrab.grab(all_screens=True)

def maybe_save_screenshot(image: Image.Image, *, enabled: bool) -> str | None:
    if not enabled:
        return None
    os.makedirs("img", exist_ok=True)
    filename = f"screenshot_{time.strftime('%Y%m%d_%H%M%S')}.png"
    path = os.path.abspath(os.path.join("img", filename))
    image.save(path, "PNG")
    return path


def maybe_ocr_visualize_path(*, enabled: bool) -> str | None:
    if not enabled:
        return None
    os.makedirs("img", exist_ok=True)
    filename = f"ocr_{time.strftime('%Y%m%d_%H%M%S')}.png"
    return os.path.abspath(os.path.join("img", filename))

_MOUSE = mouse.Controller()

_UI_STATE: dict | None = None


def _set_capture_exclusion(hwnd: int, hide: bool = True) -> None:
    if not user32:
        return
    hwnd = user32.GetAncestor(hwnd, GA_ROOT)
    if not user32.IsWindow(hwnd):
        return
    affinity = WDA_EXCLUDEFROMCAPTURE if hide else WDA_NONE
    user32.SetWindowDisplayAffinity(hwnd, affinity)


def _set_taskbar_visibility(hwnd: int, hide: bool = True) -> None:
    if not user32 or _get_long_ptr is None or _set_long_ptr is None:
        return
    hwnd = user32.GetAncestor(hwnd, GA_ROOT)
    if not user32.IsWindow(hwnd):
        return
    style = _get_long_ptr(hwnd, GWL_EXSTYLE)
    if hide:
        style |= WS_EX_TOOLWINDOW
        style &= ~WS_EX_APPWINDOW
    else:
        style |= WS_EX_APPWINDOW
        style &= ~WS_EX_TOOLWINDOW
    _set_long_ptr(hwnd, GWL_EXSTYLE, style)
    user32.SetWindowPos(
        hwnd,
        None,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
    )


def _show_window(root: tk.Tk) -> None:
    root.deiconify()
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass
    root.lift()
    root.focus_force()
    if user32:
        user32.ShowWindow(root.winfo_id(), SW_SHOW)
        user32.SetForegroundWindow(root.winfo_id())
    try:
        root.attributes("-topmost", False)
    except tk.TclError:
        pass


def _hide_window(root: tk.Tk) -> None:
    if user32:
        user32.ShowWindow(root.winfo_id(), SW_HIDE)
    root.withdraw()


def _init_ui(
    history_max: int,
    transparency: float,
    window_size: object,
    background_color: str,
    border_color: str,
    border_thickness: int,
    header_visible: bool,
    logs_size: int,
    logs_text_color: str,
    hint_visible: bool,
    hint_color: str,
    hint_size: int,
    *,
    start_hidden: bool,
) -> None:
    global _UI_STATE
    root = tk.Tk()
    root.title("AI window")
    if isinstance(window_size, (list, tuple)) and len(window_size) == 2:
        try:
            w = max(int(window_size[0]), 200)
            h = max(int(window_size[1]), 120)
            root.geometry(f"{w}x{h}")
        except (TypeError, ValueError):
            root.geometry("420x260")
    else:
        root.geometry("420x260")
    root.configure(bg=background_color)
    if not header_visible:
        try:
            root.overrideredirect(True)
        except tk.TclError:
            pass
    try:
        root.attributes("-alpha", max(0.1, min(float(transparency), 1.0)))
    except (tk.TclError, ValueError, TypeError):
        pass

    if start_hidden:
        root.withdraw()

    border_thickness = max(int(border_thickness), 0)
    list_frame = tk.Frame(
        root,
        bg=border_color,
        highlightthickness=0,
        bd=0,
    )
    list_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

    listbox = tk.Listbox(
        list_frame,
        font=("Segoe UI", max(int(logs_size), 8)),
        bg=background_color,
        fg=logs_text_color,
        highlightthickness=0,
        bd=0,
        selectbackground=border_color,
        activestyle="none",
    )
    listbox.pack(fill=tk.BOTH, expand=True, padx=border_thickness, pady=border_thickness)

    if hint_visible:
        hint_frame = tk.Frame(root, bg=background_color)
        hint_frame.pack(fill=tk.X, padx=10, pady=(0, 6))
        hint_label = tk.Label(
            hint_frame,
            text="k: hide/unhide | l: lock | p: ai clicks | o: ai copies | i: ai log",
            font=("Segoe UI", max(int(hint_size), 7)),
            bg=background_color,
            fg=hint_color,
            anchor="e",
            justify="right",
        )
        hint_label.pack(fill=tk.X)

    root.update()
    _set_capture_exclusion(root.winfo_id(), hide=True)
    _set_taskbar_visibility(root.winfo_id(), hide=True)

    _UI_STATE = {
        "root": root,
        "listbox": listbox,
        "history": [],
        "history_max": max(int(history_max), 1),
        "action_log": True,
    }


def _move_window_to_cursor(root: tk.Tk, *, offset_x: int = 0, offset_y: int = 0) -> None:
    try:
        x = root.winfo_pointerx()
        y = root.winfo_pointery()
        width = root.winfo_width()
        height = root.winfo_height()
        left = max(0, x - (width // 2) + int(offset_x))
        top = max(0, y - (height // 2) + int(offset_y))
        root.geometry(f"+{left}+{top}")
    except tk.TclError:
        pass


def _apply_window_pos(root: tk.Tk, value: object) -> None:
    if isinstance(value, str):
        mode = value.strip().lower()
        if mode == "mouse":
            _move_window_to_cursor(root)
            return
        match = re.match(r"^mouse\s*([+-])\s*\(\s*(-?\d+)\s*,\s*(-?\d+)\s*\)$", mode)
        if match:
            sign, raw_x, raw_y = match.groups()
            ox = int(raw_x)
            oy = int(raw_y)
            if sign == "-":
                ox = -ox
                oy = -oy
            _move_window_to_cursor(root, offset_x=ox, offset_y=oy)
        return
    if isinstance(value, (list, tuple)) and len(value) == 2:
        try:
            x = int(value[0])
            y = int(value[1])
            root.geometry(f"+{x}+{y}")
        except (TypeError, ValueError, tk.TclError):
            pass


def click_bbox_windows(
    bbox: tuple[int, int, int, int] | list[int] | BBox,
    *,
    rule: str = "random",
    margin: int = 2,
    smooth: bool = True,
    move_duration: float = 0.08,
    move_steps: int = 10,
    move_speed: float = 0.0,
    curve_strength: float = 0.0,
    path_mode: str = "direct",
    jitter: float = 0.0,
) -> tuple[int, int]:
    if not isinstance(bbox, BBox):
        bbox = BBox(int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3]))
    x, y = pick_point_in_bbox(bbox, rule=rule, margin=margin)
    if smooth:
        move_cursor_smooth(
            x=x,
            y=y,
            duration=move_duration,
            steps=move_steps,
            speed=move_speed,
            curve_strength=curve_strength,
            path_mode=path_mode,
            jitter=jitter,
        )
        if tuple(map(int, _MOUSE.position)) != (int(x), int(y)):
            _MOUSE.position = (x, y)
    else:
        _MOUSE.position = (x, y)
    _MOUSE.click(mouse.Button.left, 1)
    return (x, y)


def copy_to_clipboard_windows(text: str) -> None:
    subprocess.run(["clip"], input=text.encode("utf-8"), check=True)


def _clean_option_prefix(text: str) -> str:
    """Strip leading option markers like A., B), 1., 1), (a), etc."""
    return re.sub(r'^\s*(?:\([a-zA-Z0-9]+\)|[a-zA-Z0-9]+[\.\)\:\-])\s*', '', text)


def _normalize_text_for_match(text: str) -> str:
    if not text:
        return ""
    text = _clean_option_prefix(text.strip())
    reps = [
        (r'\\nu\b', 'v'), ('ν', 'v'), ('η', 'n'), ('—', '-'), ('–', '-'), ('−', '-'),
        ('“', '"'), ('”', '"'), ('«', '"'), ('»', '"'),
        ('‘', "'"), ('’', "'"), ('×', '*'), ('÷', '/'),
        ('≠', '!='), ('≤', '<='), ('≥', '>='), ('²', '^2'), ('³', '^3'),
        ('\n', ' ')
    ]
    for pat, rep in reps:
        if pat.startswith(r'\\'):
            text = re.sub(pat, rep, text, flags=re.IGNORECASE)
        else:
            text = text.replace(pat, rep)
    text = unicodedata.normalize('NFKD', text)
    text = "".join(c for c in text if not (0x0300 <= ord(c) <= 0x036F))
    text = text.lower()
    text = re.sub(r'\s*=\s*', '=', text)
    text = re.sub(r'[\s_]+', ' ', text).strip()
    return text


def _merge_bboxes(bboxes: list[tuple[int, int, int, int]]) -> tuple[int, int, int, int]:
    min_x = min(b[0] for b in bboxes)
    min_y = min(b[1] for b in bboxes)
    max_x = max(b[0] + b[2] for b in bboxes)
    max_y = max(b[1] + b[3] for b in bboxes)
    return (min_x, min_y, max_x - min_x, max_y - min_y)


def bbox_for_contains(ocr_results: list[dict], needle: str, strict: bool = False) -> tuple[int, int, int, int] | None:
    if not needle or not ocr_results:
        return None

    raw_needle = needle.strip()
    norm_needle = _normalize_text_for_match(raw_needle)
    if not norm_needle:
        return None

    # Handle very short needles (e.g. "5", "a", "no", "yes") safely
    if len(norm_needle) <= 3:
        for item in ocr_results:
            raw_t = item.get("text", "").strip()
            norm_t = _normalize_text_for_match(raw_t)
            if norm_needle == norm_t or norm_needle == raw_t.lower():
                return item["bbox"]
            pattern = r'(?<![0-9/])' + re.escape(norm_needle) + r'(?![0-9/])'
            if re.search(pattern, norm_t) or re.search(pattern, raw_t.lower()):
                return item["bbox"]
        return None

    # Pass 1: Check single chunks
    for item in ocr_results:
        raw_t = item.get("text", "").strip()
        norm_t = _normalize_text_for_match(raw_t)
        if not norm_t:
            continue
        if norm_needle == norm_t:
            return item["bbox"]
        if norm_needle in norm_t:
            return item["bbox"]
        if len(norm_t) >= 12 and norm_t in norm_needle and (len(norm_t) / len(norm_needle) >= 0.45):
            return item["bbox"]

    # Pass 2: Multi-chunk sliding window (1 to 10 chunks)
    n_items = len(ocr_results)
    best_score = 0.0
    best_bbox = None
    needle_words = set(re.findall(r'\w+', norm_needle))

    for i in range(n_items):
        combined_texts: list[str] = []
        combined_bboxes: list[tuple[int, int, int, int]] = []
        for k in range(1, min(11, n_items - i + 1)):
            chunk = ocr_results[i + k - 1]
            txt = chunk.get("text", "").strip()
            if not txt:
                continue
            combined_texts.append(txt)
            combined_bboxes.append(chunk["bbox"])

            combined_str = " ".join(combined_texts)
            norm_combined = _normalize_text_for_match(combined_str)

            # Check exact containment in combined window
            if norm_needle in norm_combined or (len(norm_combined) >= 15 and norm_combined in norm_needle and len(norm_combined) / len(norm_needle) >= 0.7):
                if len(combined_bboxes) > 1 and combined_bboxes[0][2] < 35:
                    return combined_bboxes[1]
                return combined_bboxes[0]

            # Sequence similarity
            sim = difflib.SequenceMatcher(None, norm_needle, norm_combined).ratio()

            if needle_words:
                comb_words = set(re.findall(r'\w+', norm_combined))
                overlap = len(needle_words & comb_words) / len(needle_words)
                score = 0.55 * sim + 0.45 * overlap
            else:
                score = sim

            if score > best_score:
                best_score = score
                if len(combined_bboxes) > 1 and combined_bboxes[0][2] < 35:
                    best_bbox = combined_bboxes[1]
                else:
                    best_bbox = combined_bboxes[0]

    # Acceptance threshold
    threshold = 0.65 if len(norm_needle) > 25 else 0.72
    if best_score >= threshold and best_bbox is not None:
        return best_bbox

    return None


def _normalize_correct_options(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        s = value.strip()
        if s.startswith("[") and s.endswith("]"):
            import ast
            try:
                parsed = ast.literal_eval(s)
                if isinstance(parsed, list):
                    return [str(v).strip() for v in parsed if str(v).strip()]
            except Exception:
                pass
        if s:
            return [s]
        return []
    return [str(value).strip()]


def find_answer(*, save_screenshot: bool) -> None:
    mouse_cfg = _CONFIG.get("mouse", {})
    ocr_cfg = _CONFIG.get("ocr", {})
    screenshot = take_screenshot_windows()
    crop_bbox = _normalize_crop_bbox(ocr_cfg.get("crop_bbox"))
    crop_clamp = bool(ocr_cfg.get("crop_clamp", True))
    cropped = _crop_image(screenshot, crop_bbox, clamp=crop_clamp) if crop_bbox else screenshot
    print("screenshot taken (in memory)", flush=True)
    saved_path = maybe_save_screenshot(cropped, enabled=save_screenshot)
    if saved_path:
        print(f"screenshot saved: {saved_path}", flush=True)
    ocr_visualize_path = maybe_ocr_visualize_path(enabled=save_screenshot)
    ocr_results = ocr(
        image=screenshot,
        crop_bbox=crop_bbox,
        crop_clamp=crop_clamp,
        mode=str(ocr_cfg.get("mode", "chunk")),
        visualize=bool(ocr_visualize_path),
        visualize_path=ocr_visualize_path or "./img/ocr_bboxes.png",
        x_thresh=float(ocr_cfg.get("x_thresh", 20)),
        y_thresh=float(ocr_cfg.get("y_thresh", 4)),
        group_y_thresh=float(ocr_cfg.get("group_y_thresh", 35)),
        config=ocr_cfg.get("config") or None,
        lang=str(ocr_cfg.get("lang", "rus+eng")),
    )
    if ocr_visualize_path:
        print(f"ocr image saved: {ocr_visualize_path}", flush=True)
    
    try:
        model_response = call_server(cropped, prompt="")
    except Exception as e:
        print(f"Error calling AI: {e}", file=sys.stderr)
        _log_result(f"AI error: {e}")
        return    

    options = _normalize_correct_options(model_response.get("Correct option"))
    for option in options:
        bbox = bbox_for_contains(ocr_results, option)
        found = bbox is not None
        if bbox is None:
            print(
                f"Could not find bbox for answer option: {option!r}",
                file=sys.stderr,
            )
            _log_result(f"Answer: {option} | OCR: not found")
            continue
        print(f"Clicking answer option: {option!r} at pos: {bbox}")
        _log_result(f"Answer: {option} | OCR: found")
        click_bbox_windows(
            bbox,
            rule="random",
            margin=2,
            smooth=bool(mouse_cfg.get("smooth", True)),
            move_duration=_resolve_range(mouse_cfg.get("duration"), 0.08),
            move_steps=_resolve_int_range(mouse_cfg.get("steps"), 10),
            move_speed=_resolve_range(mouse_cfg.get("speed"), 0.0),
            curve_strength=_resolve_range(mouse_cfg.get("curve_strength"), 0.0),
            path_mode=str(mouse_cfg.get("path_mode", "direct")),
            jitter=_resolve_range(mouse_cfg.get("jitter"), 0.0),
        )

    print("\nFull response:\n", options)
    print("\nPress 'p' anywhere (Ctrl+C to exit)...")


def ans_cp(*, save_screenshot: bool) -> None:
    ocr_cfg = _CONFIG.get("ocr", {})
    screenshot = take_screenshot_windows()
    crop_bbox = _normalize_crop_bbox(ocr_cfg.get("crop_bbox"))
    crop_clamp = bool(ocr_cfg.get("crop_clamp", True))
    cropped = _crop_image(screenshot, crop_bbox, clamp=crop_clamp) if crop_bbox else screenshot
    print("screenshot taken (in memory)", flush=True)
    saved_path = maybe_save_screenshot(cropped, enabled=save_screenshot)
    if saved_path:
        print(f"screenshot saved: {saved_path}", flush=True)
    ocr_visualize_path = maybe_ocr_visualize_path(enabled=save_screenshot)
    _ = ocr(
        image=screenshot,
        crop_bbox=crop_bbox,
        crop_clamp=crop_clamp,
        mode=str(ocr_cfg.get("mode", "chunk")),
        visualize=bool(ocr_visualize_path),
        visualize_path=ocr_visualize_path or "./img/ocr_bboxes.png",
        x_thresh=float(ocr_cfg.get("x_thresh", 20)),
        y_thresh=float(ocr_cfg.get("y_thresh", 4)),
        group_y_thresh=float(ocr_cfg.get("group_y_thresh", 35)),
        config=ocr_cfg.get("config") or None,
        lang=str(ocr_cfg.get("lang", "rus+eng")),
    )
    if ocr_visualize_path:
        print(f"ocr image saved: {ocr_visualize_path}", flush=True)
    try:
        model_response = call_server(
            cropped,
            prompt="Give answer to given question with details. Respond in JSON format like {\"Correct option\": \"<answer>\"}'",
        )
    except Exception as e:
        print(f"Error calling AI: {e}", file=sys.stderr)
        _log_result(f"AI error: {e}")
        return
    print("Model response:", model_response, flush=True)
    options = _normalize_correct_options(model_response.get("Correct option"))
    for option in options:
        copy_to_clipboard_windows(option)
        _log_result(f"Copied answer: {option}")
    print("\n\nFull response copied to clipboard:\n")


def ai_log_only(*, save_screenshot: bool) -> None:
    ocr_cfg = _CONFIG.get("ocr", {})
    screenshot = take_screenshot_windows()
    crop_bbox = _normalize_crop_bbox(ocr_cfg.get("crop_bbox"))
    crop_clamp = bool(ocr_cfg.get("crop_clamp", True))
    cropped = _crop_image(screenshot, crop_bbox, clamp=crop_clamp) if crop_bbox else screenshot
    try:
        model_response = call_ai_google_search(cropped, prompt="")
    except Exception as e:
        print(f"Error calling AI: {e}", file=sys.stderr)
        _log_result(f"AI log error: {e}")
        return
    _log_result(f"Correct option: {model_response.get('Correct option')}")


def _log_result(message: str) -> None:
    if not _UI_STATE:
        return
    root = _UI_STATE["root"]
    listbox = _UI_STATE["listbox"]
    history = _UI_STATE["history"]
    max_len = _UI_STATE["history_max"]

    history.append(message)
    if len(history) > max_len:
        del history[: len(history) - max_len]

    def _refresh() -> None:
        listbox.delete(0, tk.END)
        for item in history:
            listbox.insert(tk.END, item)

    root.after(0, _refresh)


def _get_active_modifiers() -> set[str]:
    mods = set()
    if os.name == "nt":
        user32 = ctypes.windll.user32
        if user32.GetAsyncKeyState(0x11) & 0x8000:  # VK_CONTROL
            mods.add("ctrl")
        if user32.GetAsyncKeyState(0x12) & 0x8000:  # VK_MENU (Alt)
            mods.add("alt")
        if user32.GetAsyncKeyState(0x10) & 0x8000:  # VK_SHIFT
            mods.add("shift")
        if (user32.GetAsyncKeyState(0x5B) & 0x8000) or (user32.GetAsyncKeyState(0x5C) & 0x8000):  # VK_LWIN / VK_RWIN
            mods.add("win")
    return mods


def _normalize_key(key: keyboard.Key | keyboard.KeyCode) -> str | None:
    if isinstance(key, keyboard.KeyCode):
        if key.vk is not None:
            if 0x41 <= key.vk <= 0x5A:
                return chr(key.vk).lower()
            if 0x30 <= key.vk <= 0x39:
                return chr(key.vk)
            if 0x70 <= key.vk <= 0x87:
                return f"f{key.vk - 0x70 + 1}"
            if 0x60 <= key.vk <= 0x69:
                return f"num{key.vk - 0x60}"
            vk_map = {
                0x20: "space",
                0x09: "tab",
                0x0D: "enter",
                0x08: "backspace",
                0x2E: "delete",
                0x2D: "insert",
                0x24: "home",
                0x23: "end",
                0x21: "pageup",
                0x22: "pagedown",
                0x26: "up",
                0x28: "down",
                0x25: "left",
                0x27: "right",
                0xBA: ";",
                0xBB: "=",
                0xBC: ",",
                0xBD: "-",
                0xBE: ".",
                0xBF: "/",
                0xC0: "`",
                0xDB: "[",
                0xDC: "\\",
                0xDD: "]",
                0xDE: "'",
            }
            if key.vk in vk_map:
                return vk_map[key.vk]

        if key.char and ord(key.char) >= 32:
            return key.char.lower()
        return None

    elif isinstance(key, keyboard.Key):
        name = key.name.lower()
        if name in (
            "ctrl", "ctrl_l", "ctrl_r",
            "alt", "alt_l", "alt_r", "alt_gr",
            "shift", "shift_l", "shift_r",
            "cmd", "cmd_l", "cmd_r"
        ):
            return None
        if name.startswith("page_"):
            return name.replace("page_", "page")
        return name

    return None


class HotkeyBinding:
    def __init__(self, raw: str | None, default: str):
        val = str(raw).strip().lower() if raw is not None and str(raw).strip() else default
        self.raw = val
        parts = [p.strip().lower() for p in self.raw.split("+") if p.strip()]
        self.modifiers = set()
        self.trigger = ""
        for p in parts:
            if p in ("ctrl", "control"):
                self.modifiers.add("ctrl")
            elif p in ("alt", "menu"):
                self.modifiers.add("alt")
            elif p in ("shift",):
                self.modifiers.add("shift")
            elif p in ("win", "cmd", "super"):
                self.modifiers.add("win")
            else:
                self.trigger = p

    def matches(self, trigger: str, active_mods: set[str]) -> bool:
        if not self.trigger or trigger.lower() != self.trigger:
            return False
        return self.modifiers == active_mods

    def __str__(self) -> str:
        mods = sorted(list(self.modifiers))
        if self.trigger:
            mods.append(self.trigger)
        return "+".join(mods)


class CompositeListener:
    def __init__(self, *listeners):
        self.listeners = listeners

    def stop(self) -> None:
        for l in self.listeners:
            try:
                l.stop()
            except Exception:
                pass


def listen_global(
    *,
    debug: bool = False,
    save_screenshot: bool = False,
    on_toggle=None,
    on_window_toggle=None,
    on_exit=None,
) -> CompositeListener:
    hotkeys_cfg = _CONFIG.get("hotkeys", {})
    b_answer = HotkeyBinding(hotkeys_cfg.get("answer_key"), "p")
    b_copy = HotkeyBinding(hotkeys_cfg.get("copy_key"), "o")
    b_info = HotkeyBinding(hotkeys_cfg.get("info_key"), "i")
    b_toggle = HotkeyBinding(hotkeys_cfg.get("toggle_commands"), "l")
    b_window = HotkeyBinding(hotkeys_cfg.get("window_visibility"), "k")

    commands_enabled = bool(hotkeys_cfg.get("turned_on_by_default", False))
    window_visible = bool(hotkeys_cfg.get("visible_by_default", True))
    busy_lock = threading.Lock()
    busy = {"value": False}

    class ClickTracker:
        def __init__(self, max_interval: float = 0.45):
            self.max_interval = max_interval
            self.history: dict[tuple[str, tuple[str, ...]], list[float]] = {}
            self.lock = threading.Lock()

        def register_click(self, btn: str, active_mods: set[str]) -> list[str]:
            now = time.time()
            mods_key = tuple(sorted(list(active_mods)))
            key = (btn, mods_key)

            with self.lock:
                prev = self.history.get(key, [])
                chain: list[float] = []
                for t in reversed(prev):
                    if not chain:
                        if (now - t) <= self.max_interval:
                            chain.append(t)
                    else:
                        if (chain[-1] - t) <= self.max_interval:
                            chain.append(t)
                        else:
                            break
                chain.reverse()
                chain.append(now)
                self.history[key] = chain

                count = len(chain)
                events: list[str] = []
                if count >= 3:
                    events.append(f"triple_{btn}")
                    # Clear chain so the next click starts a fresh cycle
                    self.history[key] = []
                elif count == 2:
                    events.append(f"double_{btn}")

                # Always include the single click trigger
                events.append(btn)
                return events

    click_tracker = ClickTracker(max_interval=0.45)

    def _try_run_task(func) -> bool:
        with busy_lock:
            if busy["value"]:
                return False
            busy["value"] = True

        def _worker() -> None:
            try:
                func()
            finally:
                with busy_lock:
                    busy["value"] = False

        threading.Thread(target=_worker, daemon=True).start()
        return True

    def _handle_trigger(trigger: str) -> bool | None:
        nonlocal commands_enabled, window_visible
        mods = _get_active_modifiers()
        if debug:
            print(f"[hotkey debug] trigger='{trigger}', mods={mods}", flush=True)

        # 1. Toggle commands (always available)
        if b_toggle.matches(trigger, mods):
            commands_enabled = not commands_enabled
            state = "enabled" if commands_enabled else "disabled"
            print(f"commands {state}", flush=True)
            if on_toggle:
                on_toggle(commands_enabled)
            return

        # 2. Toggle window visibility
        if b_window.matches(trigger, mods):
            if not commands_enabled:
                return
            window_visible = not window_visible
            if on_window_toggle:
                on_window_toggle(window_visible)
            return

        # 3. If commands disabled, don't run action hotkeys
        if not commands_enabled:
            return

        # 4. Action hotkeys
        if b_answer.matches(trigger, mods):
            print(f"{b_answer} is pressed", flush=True)
            if _try_run_task(lambda: find_answer(save_screenshot=save_screenshot)):
                if _UI_STATE and _UI_STATE.get("action_log", True):
                    _log_result(f"{b_answer} is pressed")
        elif b_copy.matches(trigger, mods):
            print(f"{b_copy} is pressed", flush=True)
            if _try_run_task(lambda: ans_cp(save_screenshot=save_screenshot)):
                if _UI_STATE and _UI_STATE.get("action_log", True):
                    _log_result(f"{b_copy} is pressed")
        elif b_info.matches(trigger, mods):
            print(f"{b_info} is pressed", flush=True)
            if _try_run_task(lambda: ai_log_only(save_screenshot=save_screenshot)):
                if _UI_STATE and _UI_STATE.get("action_log", True):
                    _log_result(f"{b_info} is pressed")

    def on_key_press(key: keyboard.Key | keyboard.KeyCode) -> bool | None:
        # Check Ctrl+Q for exit
        char = getattr(key, "char", None)
        vk = getattr(key, "vk", None)
        if char == "\x11" or ((vk == 0x51 or (char and char.lower() == "q")) and "ctrl" in _get_active_modifiers()):
            print("Ctrl+Q pressed, exiting...", flush=True)
            if on_exit:
                on_exit()
            return False

        norm = _normalize_key(key)
        if norm:
            _handle_trigger(norm)

    def on_mouse_click(x, y, button, pressed) -> None:
        if not pressed:
            return
        btn_name = getattr(button, "name", str(button)).lower()
        mods = _get_active_modifiers()
        triggers = click_tracker.register_click(btn_name, mods)
        # Check higher-order triggers (triple, then double, then single)
        for trig in triggers:
            _handle_trigger(trig)

    def on_mouse_scroll(x, y, dx, dy) -> None:
        if dy > 0:
            _handle_trigger("wheel_up")
        elif dy < 0:
            _handle_trigger("wheel_down")

    kb_listener = keyboard.Listener(on_press=on_key_press)
    kb_listener.start()

    mouse_listener = mouse.Listener(on_click=on_mouse_click, on_scroll=on_mouse_scroll)
    mouse_listener.start()

    print(
        f"Hotkeys loaded: answer={b_answer} | copy={b_copy} | info={b_info} | toggle={b_toggle} | window={b_window}",
        flush=True,
    )
    print(f"Listening globally for toggle '{b_toggle}' (Ctrl+C or Ctrl+Q to exit)...", flush=True)
    return CompositeListener(kb_listener, mouse_listener)


def main() -> int:
    warmup_tesseract()
    ai_mode, target_url = _get_effective_ai_mode_and_url()
    ai_llm = _get_ai_setting("llm", "gemini")
    ai_model = _get_ai_setting("model", "")
    if ai_mode == "local":
        print(f"Config loaded: mode=local | llm={ai_llm} | model={ai_model or '(default)'}", flush=True)
    else:
        print(f"Config loaded: mode=server | url={target_url}", flush=True)
    print(f"Config path: {CONFIG_PATH}", flush=True)
    print(f"Credentials path: {CREDENTIALS_PATH}", flush=True)
    ui_cfg = _CONFIG.get("ui", {})
    start_visible = bool(_CONFIG.get("hotkeys", {}).get("visible_by_default", True))
    _init_ui(
        int(ui_cfg.get("logs", {}).get("history_max", 10)),
        float(ui_cfg.get("transparency", 1.0)),
        ui_cfg.get("window_size", [420, 260]),
        str(ui_cfg.get("background_color", "#111111")),
        str(ui_cfg.get("border_color", "#2a2a2a")),
        int(ui_cfg.get("border_thickness", 2)),
        bool(ui_cfg.get("header_visible", True)),
        int(ui_cfg.get("logs", {}).get("size", 11)),
        str(ui_cfg.get("logs", {}).get("text_color", "#ffffff")),
        bool(ui_cfg.get("hint", {}).get("visible", True)),
        str(ui_cfg.get("hint", {}).get("color", "#888888")),
        int(ui_cfg.get("hint", {}).get("size", 9)),
        start_hidden=not start_visible,
    )
    _UI_STATE["action_log"] = bool(ui_cfg.get("logs", {}).get("action_log", True))
    root = _UI_STATE["root"]
    _apply_window_pos(root, ui_cfg.get("window_pos", "mouse"))
    if start_visible:
        _show_window(root)
    else:
        _hide_window(root)
    parser = argparse.ArgumentParser(
        description="Windows: listen for global key presses. Press 'p' for answers, 'o' to copy.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print every character received.",
    )
    parser.add_argument(
        "--save-screenshot",
        action="store_true",
        help="Save screenshots to ./img for debugging.",
    )
    args = parser.parse_args()
    def _do_exit() -> None:
        try:
            if listener:
                listener.stop()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass
        os._exit(0)

    listener = listen_global(
        debug=args.debug,
        save_screenshot=args.save_screenshot,
        on_toggle=None,
        on_window_toggle=lambda visible: (_apply_window_pos(root, ui_cfg.get("window_pos", "mouse")), _show_window(root)) if visible else _hide_window(root),
        on_exit=_do_exit,
    )
    try:
        root.mainloop()
    finally:
        if listener:
            listener.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
