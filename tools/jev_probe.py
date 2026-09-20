"""Bounded, append-only runner for synthetic Jev TypeSafe probe cases."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import math
import os
import ssl
import sys
import time
import uuid
from pathlib import Path
from typing import Any


HOST = "api.typesafe.ai"
PATH = "/v1/systemone"
MODEL = "jev-1.13.0"
TIMEOUT_SECONDS = 30
MAX_REQUEST_BYTES = 25_000
MAX_INPUT_TOKENS = 65_536
INPUT_USD_PER_TOKEN = 0.042 / 1_000_000
RESERVED_USD = MAX_INPUT_TOKENS * INPUT_USD_PER_TOKEN


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and value >= 0 else None


def _append_record(output: Path, record: dict[str, Any]) -> None:
    """Append a durable JSONL record before any physical request is made."""
    line = _json_bytes(record) + b"\n"
    with output.open("ab") as ledger:
        ledger.write(line)
        ledger.flush()
        os.fsync(ledger.fileno())


def _question_option_count(question: dict[str, Any]) -> int | None:
    for key in ("criteria", "choices", "options"):
        value = question.get(key)
        if isinstance(value, (dict, list)):
            return len(value)
    return None


def _score_count(question: dict[str, Any]) -> int | None:
    options = _question_option_count(question)
    if options is not None:
        return options
    scale = question.get("scale")
    if isinstance(scale, int) and not isinstance(scale, bool):
        return scale
    minimum, maximum = question.get("min"), question.get("max")
    if (isinstance(minimum, int) and not isinstance(minimum, bool) and
            isinstance(maximum, int) and not isinstance(maximum, bool)):
        return maximum - minimum + 1
    value_range = question.get("range")
    if (isinstance(value_range, list) and len(value_range) == 2 and
            all(isinstance(value, int) and not isinstance(value, bool) for value in value_range)):
        return value_range[1] - value_range[0] + 1
    return None


def validate_case(case: Any) -> tuple[dict[str, Any], bytes, str]:
    """Validate one fixture and return its API-safe payload, bytes, and digest."""
    if not isinstance(case, dict):
        raise ValueError("case")
    case_id, category, state, questions = (case.get("id"), case.get("category"),
                                             case.get("state"), case.get("questions"))
    if not isinstance(case_id, str) or not case_id or not isinstance(category, str):
        raise ValueError("case identity")
    if not isinstance(questions, dict) or not questions:
        raise ValueError("case payload")
    for name, question in questions.items():
        if not isinstance(name, str) or not isinstance(question, dict):
            raise ValueError("question")
        instructions = question.get("instructions")
        if not isinstance(instructions, str) or not instructions or "\x00" in instructions:
            raise ValueError("instructions")
        kind = question.get("type")
        if not isinstance(kind, str):
            raise ValueError("question type")
        kind = kind.lower()
        if kind == "choice":
            count = _question_option_count(question)
            if count is None or not 1 <= count <= 255:
                raise ValueError("choice options")
        elif kind == "score":
            count = _score_count(question)
            if count is None or not 2 <= count <= 10:
                raise ValueError("score range")
        elif kind == "noul":
            pass
        else:
            raise ValueError("question type")
    payload = {"model": MODEL, "state": state, "questions": questions}
    try:
        payload_bytes = _json_bytes(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError("payload") from exc
    if len(payload_bytes) > MAX_REQUEST_BYTES:
        raise ValueError("request size")
    return payload, payload_bytes, hashlib.sha256(payload_bytes).hexdigest()


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as source:
            for line in source:
                if not line.strip():
                    continue
                value = json.loads(line)
                validate_case(value)
                cases.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("cases") from exc
    return cases


def ledger_state(path: Path) -> tuple[float, int, set[str]]:
    """Return charged cost, physical attempts, and IDs that must never be retried."""
    attempts: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return 0.0, 0, set()
    try:
        with path.open(encoding="utf-8") as ledger:
            for line in ledger:
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError("ledger record")
                if record.get("event") == "reserved":
                    attempt_id = record.get("attempt_id")
                    cost = _number(record.get("reserved_usd"))
                    case_id = record.get("id")
                    if not isinstance(attempt_id, str) or cost is None or not isinstance(case_id, str):
                        raise ValueError("reservation")
                    if attempt_id in attempts:
                        raise ValueError("duplicate reservation")
                    attempts[attempt_id] = {"cost": cost, "id": case_id}
                elif record.get("event") == "result":
                    attempt = attempts.get(record.get("attempt_id"))
                    charge = _number(record.get("charged_usd"))
                    if attempt is None or charge is None:
                        raise ValueError("result")
                    attempt["cost"] = charge
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise ValueError("ledger") from exc
    return sum(float(attempt["cost"]) for attempt in attempts.values()), len(attempts), {
        str(attempt["id"]) for attempt in attempts.values()
    }


def _result_record(
    case: dict[str, Any], attempt_id: str, digest: str, status: str, elapsed_ms: int,
    *, http_status: int | None = None, usage: dict[str, Any] | None = None,
    answers: Any = None, charged_usd: float = RESERVED_USD, model: str = MODEL,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "event": "result", "attempt_id": attempt_id, "utc": _utc_now(),
        "id": case["id"], "category": case["category"], "payload_sha256": digest,
        "model": model, "status": status, "roundtrip_ms": elapsed_ms,
        "charged_usd": charged_usd,
    }
    if http_status is not None:
        record["http_status"] = http_status
    if usage is not None:
        record["usage"] = usage
    if answers is not None:
        record["answers"] = answers
    if "expected" in case:
        record["expected"] = case["expected"]
    return record


def _response_parts(body: bytes) -> tuple[dict[str, Any], Any, str]:
    value = json.loads(body.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("response")
    raw_usage = value.get("usage")
    usage: dict[str, Any] = {}
    if isinstance(raw_usage, dict):
        for key, number in raw_usage.items():
            safe_number = _number(number)
            if isinstance(key, str) and safe_number is not None:
                usage[key] = safe_number
    response_model = value.get("model")
    return usage, value.get("answers"), response_model if isinstance(response_model, str) else MODEL


def run_live(cases: list[dict[str, Any]], output: Path, max_usd: float, max_calls: int) -> dict[str, Any]:
    if not math.isfinite(max_usd) or max_usd <= 0 or max_calls < 1:
        raise ValueError("limits")
    api_key = os.environ.get("JEV_API_KEY") or os.environ.get("TYPESAFE_API_KEY")
    if not api_key:
        raise ValueError("authorization")
    spent, physical_attempts, prior_ids = ledger_state(output)
    if spent > max_usd:
        raise ValueError("budget")
    output.parent.mkdir(parents=True, exist_ok=True)
    completed = skipped = successes = errors = 0
    consecutive_errors = 0
    stop_reason: str | None = None
    connection: http.client.HTTPSConnection | None = None
    try:
        for case in cases:
            if case["id"] in prior_ids:
                skipped += 1
                continue
            if physical_attempts >= max_calls:
                stop_reason = "max_calls"
                break
            if spent + RESERVED_USD > max_usd + 1e-12:
                stop_reason = "budget"
                break
            _, payload, digest = validate_case(case)
            attempt_id = uuid.uuid4().hex
            reservation = {
                "event": "reserved", "attempt_id": attempt_id, "utc": _utc_now(),
                "id": case["id"], "category": case["category"], "payload_sha256": digest,
                "model": MODEL, "status": "reserved", "reserved_usd": RESERVED_USD,
            }
            _append_record(output, reservation)
            prior_ids.add(case["id"])
            spent += RESERVED_USD
            physical_attempts += 1
            started = time.monotonic()
            try:
                if connection is None:
                    connection = http.client.HTTPSConnection(
                        HOST, timeout=TIMEOUT_SECONDS, context=ssl.create_default_context())
                connection.request("POST", PATH, body=payload, headers={
                    "Content-Type": "application/json", "Authorization": "Bearer " + api_key,
                    "Content-Length": str(len(payload)),
                })
                response = connection.getresponse()
                body = response.read()
                elapsed_ms = round((time.monotonic() - started) * 1000)
                if not 200 <= response.status < 300:
                    _append_record(output, _result_record(
                        case, attempt_id, digest, "http_error", elapsed_ms,
                        http_status=response.status))
                    errors += 1
                    consecutive_errors += 1
                    connection.close()
                    connection = None
                    if response.status in (401, 402, 403):
                        stop_reason = "authorization_or_payment"
                        break
                    if consecutive_errors >= 3:
                        stop_reason = "consecutive_errors"
                        break
                    continue
                usage, answers, response_model = _response_parts(body)
                input_tokens = usage.get("input_tokens")
                charged = RESERVED_USD if input_tokens is None else input_tokens * INPUT_USD_PER_TOKEN
                _append_record(output, _result_record(
                    case, attempt_id, digest, "success", elapsed_ms, http_status=response.status,
                    usage=usage or None, answers=answers, charged_usd=charged, model=response_model))
                spent += charged - RESERVED_USD
                successes += 1
                completed += 1
                consecutive_errors = 0
                if input_tokens is not None and input_tokens > MAX_INPUT_TOKENS:
                    stop_reason = "usage_exceeds_reservation"
                    break
            except Exception:
                elapsed_ms = round((time.monotonic() - started) * 1000)
                _append_record(output, _result_record(case, attempt_id, digest, "request_error", elapsed_ms))
                errors += 1
                consecutive_errors += 1
                if connection is not None:
                    connection.close()
                    connection = None
                if consecutive_errors >= 3:
                    stop_reason = "consecutive_errors"
                    break
            if physical_attempts % 20 == 0:
                print(json.dumps({"progress": physical_attempts, "successes": successes,
                                  "errors": errors, "charged_usd": round(spent, 9)}))
    finally:
        if connection is not None:
            connection.close()
    return {"mode": "live", "physical_attempts": physical_attempts, "completed": completed,
            "skipped": skipped, "successes": successes, "errors": errors,
            "charged_usd": spent, "stop_reason": stop_reason}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run synthetic Jev probes. Live use requires explicit API authorization.")
    parser.add_argument("--cases", type=Path, required=True, help="JSONL synthetic-case fixture")
    parser.add_argument("--output", type=Path, required=True, help="append-only JSONL ledger")
    parser.add_argument("--live", action="store_true", help="send authorized live requests (default: dry run)")
    parser.add_argument("--max-usd", type=float, default=0, help="hard local request-charge budget")
    parser.add_argument("--max-calls", type=int, default=100, help="maximum physical requests, including prior attempts")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        cases = load_cases(args.cases)
        if not args.live:
            bound = min(len(cases), max(args.max_calls, 0)) * RESERVED_USD
            print(json.dumps({"mode": "dry-run", "case_count": len(cases),
                              "max_cost_usd": bound}))
            return 0
        summary = run_live(cases, args.output, args.max_usd, args.max_calls)
        print(json.dumps(summary))
        return 0 if summary["stop_reason"] not in {"authorization_or_payment", "usage_exceeds_reservation"} else 1
    except (ValueError, OSError, UnicodeError, TypeError):
        print("jev probe refused: invalid input, ledger, limits, or authorization", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
