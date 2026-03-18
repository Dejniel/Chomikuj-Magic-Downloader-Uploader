#!/usr/bin/env python3

import re

LOCAL_EXTENSION_RE = re.compile(r"\.[A-Za-z0-9]+$")
LOCAL_SAFE_CHARS = set(" .-_()[],")


def encode_local_component(name, allow_extension=False):
    text = str(name or "")
    extension = ""
    if allow_extension:
        match = LOCAL_EXTENSION_RE.search(text)
        if match and 0 < match.start() < len(text) - 1:
            text, extension = text[: match.start()], match.group(0)

    encoded = []
    last_index = len(text) - 1
    for index, char in enumerate(text):
        if ("a" <= char <= "z") or ("A" <= char <= "Z") or ("0" <= char <= "9"):
            encoded.append(char)
        elif char in LOCAL_SAFE_CHARS and 0 < index < last_index:
            encoded.append(char)
        else:
            encoded.extend(f"*{byte:02x}" for byte in char.encode("utf-8"))
    encoded_text = "".join(encoded) or "_"
    return encoded_text + extension
