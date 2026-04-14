"""Container-side entrypoint for the strategy sandbox.

Reads strategy code from stdin, executes it, returns structured JSON via stdout.
The strategy code must assign a `result` variable.
"""
import json
import sys
import traceback


def main():
    code = sys.stdin.read()

    if not code.strip():
        print(json.dumps({"status": "error", "error_code": "EMPTY_CODE", "detail": "No code provided"}))
        return

    namespace = {}
    try:
        exec(code, namespace)  # noqa: S102
    except Exception:
        tb = traceback.format_exc()
        print(json.dumps({"status": "error", "error_code": "EXECUTION_ERROR", "detail": tb}))
        return

    if "result" not in namespace:
        print(json.dumps({"status": "error", "error_code": "NO_RESULT", "detail": "Strategy did not assign a 'result' variable"}))
        return

    try:
        payload = json.dumps({"status": "ok", "result": namespace["result"]})
    except (TypeError, ValueError) as exc:
        print(json.dumps({"status": "error", "error_code": "SERIALIZATION_ERROR", "detail": str(exc)}))
        return

    print(payload)


if __name__ == "__main__":
    main()
