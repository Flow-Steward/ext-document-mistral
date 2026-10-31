from __future__ import annotations

import base64
import json
from typing import Any
from urllib.error import HTTPError

from flowsteward_extension_sdk import report_progress, runtime_context_from_payload
from flowsteward_extension_sdk.artifacts import (
    ArtifactAccessError,
    find_artifact_descriptor,
    read_artifact_bytes,
    write_artifact_bytes,
)
from flowsteward_extension_sdk.http import Request, open_pinned_url, resolve_pinned_ips
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from referencing import Registry

INPUT_LIMIT = 20 * 1024 * 1024
OUTPUT_LIMIT = 50 * 1024 * 1024
INLINE_LIMIT = 1024 * 1024
TEXT_INLINE_LIMIT = 512 * 1024


class MistralError(RuntimeError):
    def __init__(self, code: str, message: str, request_id: str = ""):
        super().__init__(message)
        self.code, self.message, self.request_id = code, message, request_id


def build_request(data: bytes, mime: str, options: dict[str, Any]) -> dict[str, Any]:
    if mime != "application/pdf" or not data.startswith(b"%PDF-"):
        raise MistralError(
            "invalid_payload",
            "PDF document must be an application/pdf artifact with a valid PDF header.",
        )
    if len(data) > INPUT_LIMIT:
        raise MistralError("input_too_large", "PDF document exceeds the 20 MiB limit.")
    table = options.get("table_format", "inline")
    if table not in ("inline", "markdown", "html"):
        raise MistralError("invalid_payload", "Table output must be inline, markdown or html.")
    result: dict[str, Any] = {
        "model": "mistral-ocr-latest",
        "document": {
            "type": "document_url",
            "document_url": "data:application/pdf;base64," + base64.b64encode(data).decode("ascii"),
        },
        "include_blocks": True,
        "include_image_base64": False,
    }
    if table != "inline":
        result["table_format"] = table
    schema = options.get("schema")
    if schema is not None:
        if (
            not isinstance(schema, dict)
            or schema.get("type") != "object"
            or len(json.dumps(schema).encode()) > 65536
        ):
            raise MistralError(
                "invalid_payload",
                "Extraction JSON Schema must be an object schema of at most 64 KiB.",
            )

        def has_references(value: Any) -> bool:
            if not isinstance(value, dict):
                return False
            if "$ref" in value or "$dynamicRef" in value:
                return True
            maps = ("properties", "patternProperties", "$defs", "dependentSchemas")
            singles = (
                "additionalProperties",
                "unevaluatedProperties",
                "propertyNames",
                "items",
                "contains",
                "not",
                "if",
                "then",
                "else",
                "unevaluatedItems",
                "contentSchema",
            )
            arrays = ("allOf", "anyOf", "oneOf", "prefixItems")
            for keyword in maps:
                children = value.get(keyword)
                if isinstance(children, dict) and any(has_references(v) for v in children.values()):
                    return True
            if any(has_references(value.get(keyword)) for keyword in singles):
                return True
            for keyword in arrays:
                children = value.get(keyword)
                if isinstance(children, list) and any(has_references(v) for v in children):
                    return True
            return False

        if (
            has_references(schema)
            or schema.get("$schema", "https://json-schema.org/draft/2020-12/schema")
            != "https://json-schema.org/draft/2020-12/schema"
        ):
            raise MistralError(
                "invalid_payload",
                "Extraction JSON Schema must use Draft 2020-12 without references. Remove $ref or $dynamicRef.",
            )
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            path = ".".join(str(part) for part in exc.absolute_path) or "root"
            raise MistralError(
                "invalid_payload",
                f"Extraction JSON Schema is invalid at {path}; correct that field and retry.",
            ) from exc
        result["document_annotation_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "document_extraction", "schema": schema, "strict": True},
        }
    return result


def parse_response(
    response: dict[str, Any], schema: dict[str, Any] | None
) -> tuple[str, dict[str, Any]]:
    pages = response.get("pages")
    if not isinstance(pages, list) or any(
        not isinstance(p, dict) or not isinstance(p.get("markdown"), str) for p in pages
    ):
        raise MistralError("invalid_provider_response", "Mistral response lacks valid page text.")
    text = "\n\n".join(p["markdown"] for p in pages)
    structured: dict[str, Any] = {}
    if schema is not None:
        try:
            structured = json.loads(response["document_annotation"])
            if not isinstance(structured, dict):
                raise ValueError("annotation is not an object")
        except (KeyError, TypeError, ValueError) as exc:
            raise MistralError(
                "invalid_provider_response", "Mistral did not return a valid structured object."
            ) from exc
        error = next(
            Draft202012Validator(schema, registry=Registry()).iter_errors(structured), None
        )
        if error is not None:
            path = ".".join(str(part) for part in error.absolute_path) or "root"
            raise MistralError(
                "invalid_provider_response",
                f"Mistral structured output does not match Extraction JSON Schema at {path}; review the schema and document.",
            )
    return text, structured


def handle_payload(payload: dict[str, Any]) -> dict[str, Any]:
    request_id = ""
    request_started = False
    try:
        runtime_context_from_payload(payload)
        runtime = payload.get("runtime_context") or {}
        if not isinstance(runtime.get("test_mode", False), bool):
            raise MistralError("invalid_payload", "Test mode must be a boolean.")
        if runtime.get("test_mode") is True:
            raise MistralError(
                "test_mode_suppressed", "Mistral requests are suppressed in test mode."
            )
        effect_id = runtime.get("external_effect_id")
        if not isinstance(effect_id, str) or not effect_id.strip() or len(effect_id) > 512:
            raise MistralError(
                "effect_claim_required",
                "A durable effect claim is required before calling Mistral.",
            )
        action = payload.get("action") or {}
        if action.get("action_id") != "process_document":
            raise MistralError("invalid_payload", "Unsupported action.")
        inputs = action.get("input") or {}
        raw_handle = inputs.get("artifact_handle")
        if isinstance(raw_handle, dict):
            raw_handle = raw_handle.get("artifact_handle") or raw_handle.get("artifact_id")
        if not isinstance(raw_handle, str) or not raw_handle.strip():
            raise MistralError("invalid_payload", "PDF document artifact is required.")
        handle = raw_handle.removeprefix("artifact:")
        connection = (action.get("target") or {}).get("connection") or {}
        if connection.get("connection_type") != "mistral_document":
            raise MistralError("invalid_connection", "Select a Mistral Document AI connection.")
        key = (connection.get("secrets") or {}).get("api_key")
        if not isinstance(key, str) or not key.strip():
            raise MistralError(
                "invalid_connection", "Mistral API key is required in the selected connection."
            )
        timeout = (connection.get("config") or {}).get("request_timeout_seconds", 120)
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 240:
            raise MistralError(
                "invalid_connection", "Request timeout must be an integer from 1 to 240 seconds."
            )
        descriptor = find_artifact_descriptor(
            payload, artifact_id=handle, binding_key="source_document", role="input"
        )
        if isinstance(descriptor.get("size_bytes"), int) and descriptor["size_bytes"] > INPUT_LIMIT:
            raise MistralError("input_too_large", "PDF document exceeds the 20 MiB limit.")
        report_progress("Reading the PDF document")
        body = read_artifact_bytes(
            payload, artifact_id=handle, binding_key="source_document", timeout_seconds=10
        )
        mime = descriptor.get("content_type") or descriptor.get("mime_type")
        if not mime and str(descriptor.get("filename", "")).lower().endswith(".pdf"):
            mime = "application/pdf"
        request_body = build_request(body, mime or "", inputs)
        report_progress("Processing the document with Mistral")
        request_started = True
        response, request_id = post_ocr(request_body, key, timeout)
        try:
            text, structured = parse_response(response, inputs.get("schema"))
        except MistralError as exc:
            exc.request_id = request_id
            raise
        output = json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode()
        if len(output) > OUTPUT_LIMIT:
            raise MistralError(
                "output_too_large", "Mistral response exceeds the 50 MiB output limit.", request_id
            )
        if len(json.dumps(structured, ensure_ascii=False).encode()) > INLINE_LIMIT:
            raise MistralError(
                "output_too_large", "Structured output exceeds the 1 MiB inline limit.", request_id
            )
        saved = write_artifact_bytes(
            payload,
            output,
            binding_key="result_artifact_handle",
            content_type="application/json",
            timeout_seconds=10,
        )
        inline = text.encode("utf-8")[:TEXT_INLINE_LIMIT].decode("utf-8", errors="ignore")
        return {
            "ok": True,
            "provider_message_id": request_id,
            "result": {
                "result_artifact_handle": saved.get("artifact_handle"),
                "text": inline,
                "text_truncated": len(inline) < len(text),
                "structured": structured,
                "request_id": request_id,
            },
        }
    except MistralError as exc:
        return {
            "ok": False,
            "error_code": exc.code,
            "error": exc.message,
            "errors": [{"code": exc.code, "message": exc.message}],
            "provider_message_id": exc.request_id,
            "result": {"request_id": exc.request_id},
            "definitely_no_external_effect": not request_started,
        }
    except ArtifactAccessError:
        return {
            "ok": False,
            "error_code": "artifact_access_failed",
            "error": "Could not access the document artifact.",
            "provider_message_id": request_id,
            "result": {"request_id": request_id},
            "definitely_no_external_effect": not request_started,
        }
    except (ValueError, TypeError, KeyError):
        return {
            "ok": False,
            "error_code": "invalid_payload",
            "error": "Invalid request or host envelope.",
            "definitely_no_external_effect": not request_started,
        }


def post_ocr(body: dict[str, Any], key: str, timeout: int) -> tuple[dict[str, Any], str]:
    request = Request(
        "https://api.mistral.ai/v1/ocr",
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    request_id = ""
    try:
        ips = resolve_pinned_ips("api.mistral.ai", port=443, purpose="Mistral OCR")
        with open_pinned_url(
            request, timeout_seconds=float(timeout), purpose="Mistral OCR", pinned_ips=tuple(ips)
        ) as response:
            request_id = str(response.headers.get("x-request-id", ""))[:256]
            raw = response.read(OUTPUT_LIMIT + 1)
    except HTTPError as exc:
        request_id = str(exc.headers.get("x-request-id", ""))[:256] if exc.headers else ""
        raise MistralError(
            "provider_http_error",
            f"Mistral returned HTTP {exc.code}. Check the API key, PDF, table format and extraction JSON Schema before retrying.",
            request_id,
        ) from exc
    except (OSError, ValueError) as exc:
        raise MistralError(
            "provider_request_failed",
            "Mistral request failed or timed out. Its outcome may be unknown; check Mistral before retrying.",
            request_id,
        ) from exc
    if len(raw) > OUTPUT_LIMIT:
        raise MistralError(
            "output_too_large", "Mistral response exceeds the 50 MiB output limit.", request_id
        )
    try:
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("not an object")
        return result, request_id
    except (ValueError, UnicodeDecodeError) as exc:
        raise MistralError(
            "invalid_provider_response", "Mistral response was not a JSON object.", request_id
        ) from exc
