"""Command-line check for the model runtime.

    python -m geoops.ai status
    python -m geoops.ai probe
    python -m geoops.ai chat "用一句中文说明你能做什么"

``status`` never prints the key. ``probe`` and ``chat`` make a real HTTP call;
they fail loudly when the endpoint or model is missing.
"""

from __future__ import annotations

import json
import sys

from geoops.ai.runtime import ModelRuntime, ModelRuntimeError


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "status"
    runtime = ModelRuntime.from_env()
    if command == "status":
        print(json.dumps(runtime.status(), ensure_ascii=False, indent=2))
        return 0 if runtime.status()["configured"] else 2
    if command == "probe":
        try:
            print(json.dumps(runtime.probe(), ensure_ascii=False, indent=2))
            return 0
        except ModelRuntimeError as exc:
            print(json.dumps({"ok": False, "code": exc.code, "error": str(exc)}, ensure_ascii=False, indent=2))
            return 1
    if command == "chat":
        prompt = " ".join(args[1:]).strip()
        if not prompt:
            print("chat needs a prompt", file=sys.stderr)
            return 2
        try:
            result = runtime.invoke(prompt, max_tokens=512)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        except ModelRuntimeError as exc:
            print(json.dumps({"ok": False, "code": exc.code, "error": str(exc)}, ensure_ascii=False, indent=2))
            return 1
    print("usage: python -m geoops.ai [status|probe|chat <prompt>]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
