import os
from typing import Optional
import json
from typing import Any

from google import genai
from google.genai import types

from variables import sys_instruction, resp_schema

_CLIENT: Optional[genai.Client] = None

def _get_client() -> genai.Client:
    global _CLIENT
    if _CLIENT is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("Missing GEMINI_API_KEY environment variable.")
        _CLIENT = genai.Client(api_key=api_key)
    return _CLIENT


def generate(
    prompt: str | None = None,
    image_bytes: bytes | None = None,
    image_mime_type: str | None = None,
    *,
    model: str = "gemini-2.5-flash",
    temperature: float = 0.75,
    enable_google_search: bool = False,
    force_json: bool = True,
) -> Any:
    parts: list[types.Part] = []

    if image_bytes:
        parts.append(
            types.Part.from_bytes(
                data=image_bytes,
                mime_type=image_mime_type or "application/octet-stream",
            )
        )

    if prompt is not None:
        parts.append(types.Part.from_text(text=prompt))

    if not parts:
        raise ValueError("Provide prompt and/or image.")

    client = _get_client()

    contents = [types.Content(role="user", parts=parts)]

    tools = [types.Tool(googleSearch=types.GoogleSearch())] if enable_google_search else []

    config = types.GenerateContentConfig(
        temperature=temperature,
        safety_settings=[
			types.SafetySetting(
				category="HARM_CATEGORY_HARASSMENT",
				threshold="BLOCK_NONE",
			),
			types.SafetySetting(
				category="HARM_CATEGORY_HATE_SPEECH",
				threshold="BLOCK_NONE",
			),
			types.SafetySetting(
				category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
				threshold="BLOCK_NONE",
			),
			types.SafetySetting(
				category="HARM_CATEGORY_DANGEROUS_CONTENT",
				threshold="BLOCK_NONE",
			),
		],
        tools=tools,
        system_instruction=[types.Part.from_text(text=sys_instruction)],
    )

    # If you want structured JSON, control it explicitly (not tied to google search)
    if force_json:
        config.response_mime_type = "application/json"
        config.response_schema = resp_schema["list_obj"]

    # Non-streaming is simpler for Cloud Run (less log spam)
    resp = client.models.generate_content(
        model=model,
        contents=contents,
        config=config,
    )

    raw = resp.text or ""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError(f"Model returned non-JSON: {raw[:200]}")







def generate_gem3(
    prompt: str | None = None,
    image_bytes: bytes | None = None,
    image_mime_type: str | None = None,
    *,
    model: str = "gemini-3-flash-preview",
    temperature: float = 0.75,
    enable_google_search: bool = True,
    force_json: bool = True,
) -> Any:
    parts: list[types.Part] = []

    if image_bytes:
        parts.append(
            types.Part.from_bytes(
                data=image_bytes,
                mime_type=image_mime_type or "application/octet-stream",
            )
        )

    if prompt is not None:
        parts.append(types.Part.from_text(text=prompt))

    if not parts:
        raise ValueError("Provide prompt and/or image.")

    client = _get_client()

    contents = [types.Content(role="user", parts=parts)]

    tools = [types.Tool(googleSearch=types.GoogleSearch())] if enable_google_search else []

    config = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(
            thinking_level="HIGH",
        ),
        temperature=temperature,
        safety_settings=[
			types.SafetySetting(
				category="HARM_CATEGORY_HARASSMENT",
				threshold="BLOCK_NONE",
			),
			types.SafetySetting(
				category="HARM_CATEGORY_HATE_SPEECH",
				threshold="BLOCK_NONE",
			),
			types.SafetySetting(
				category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
				threshold="BLOCK_NONE",
			),
			types.SafetySetting(
				category="HARM_CATEGORY_DANGEROUS_CONTENT",
				threshold="BLOCK_NONE",
			),
		],
        tools=tools,
        system_instruction=[types.Part.from_text(text=sys_instruction)],
    )

    # If you want structured JSON, control it explicitly (not tied to google search)
    if force_json:
        config.response_mime_type = "application/json"
        config.response_schema = resp_schema["list_obj"]

    # Non-streaming is simpler for Cloud Run (less log spam)
    resp = client.models.generate_content(
        model=model,
        contents=contents,
        config=config,
    )

    raw = resp.text or ""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError(f"Model returned non-JSON: {raw[:200]}")