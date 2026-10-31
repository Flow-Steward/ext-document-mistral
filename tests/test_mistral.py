import pytest
from mistral_extension import build_request, parse_response, MistralError


def test_pdf_ocr_contains_blocks_and_table_option():
    request = build_request(b"%PDF-1.4 text", "application/pdf", {"table_format": "html"})
    assert request["document"]["type"] == "document_url"
    assert request["include_blocks"] is True
    assert request["table_format"] == "html"


def test_scanned_pdf_annotation_uses_schema():
    schema = {"type": "object", "properties": {"total": {"type": "number"}}}
    request = build_request(b"%PDF-1.4 scan", "application/pdf", {"schema": schema})
    assert request["document_annotation_format"]["json_schema"]["schema"] == schema
    assert "pages" not in request


def test_table_and_annotation_outputs():
    text, structured = parse_response(
        {
            "pages": [{"markdown": "| a | b |", "tables": [{"content": "| 1 | 2 |"}]}],
            "document_annotation": '{"total":2}',
        },
        {"type": "object"},
    )
    assert text == "| a | b |"
    assert structured == {"total": 2}


@pytest.mark.parametrize("mime, data", [("text/plain", b"text"), ("application/pdf", b"bad")])
def test_rejects_unsupported_or_invalid_document(mime, data):
    with pytest.raises(MistralError):
        build_request(data, mime, {})


def test_invalid_schema_and_options_are_rejected():
    with pytest.raises(MistralError):
        build_request(b"%PDF-1.4", "application/pdf", {"schema": []})
    with pytest.raises(MistralError):
        build_request(b"%PDF-1.4", "application/pdf", {"table_format": "other"})


def test_missing_credentials_does_not_read_artifact(monkeypatch):
    import mistral_extension as ext

    monkeypatch.setattr(ext, "runtime_context_from_payload", lambda _: None)
    monkeypatch.setattr(ext, "read_artifact_bytes", lambda *a, **k: pytest.fail("must not read"))
    response = ext.handle_payload(
        {
            "runtime_context": {"external_effect_id": "effect-1"},
            "action": {
                "action_id": "process_document",
                "input": {"artifact_handle": "a"},
                "target": {"connection": {}},
            },
        }
    )
    assert response["error_code"] == "invalid_connection"


def test_timeout_reports_unknown_outcome_without_retry(monkeypatch):
    import mistral_extension as ext

    calls = []
    monkeypatch.setattr(ext, "resolve_pinned_ips", lambda *a, **k: ["1.1.1.1"])

    def fail(*args, **kwargs):
        calls.append(1)
        raise TimeoutError()

    monkeypatch.setattr(ext, "open_pinned_url", fail)
    with pytest.raises(MistralError, match="outcome may be unknown"):
        ext.post_ocr({}, "key", 1)
    assert len(calls) == 1


def test_end_to_end_mock_saves_complete_response(monkeypatch):
    import mistral_extension as ext

    saved = []
    response = {
        "pages": [
            {
                "markdown": "Scanned text",
                "blocks": [{"type": "text"}],
                "tables": [{"content": "| A |"}],
            }
        ],
        "document_annotation": '{"total": 3}',
    }
    monkeypatch.setattr(ext, "runtime_context_from_payload", lambda _: None)
    monkeypatch.setattr(ext, "report_progress", lambda *_: None)
    monkeypatch.setattr(ext, "find_artifact_descriptor", lambda *a, **k: {"filename": "scan.pdf"})
    monkeypatch.setattr(ext, "read_artifact_bytes", lambda *a, **k: b"%PDF-1.4 scanned")
    monkeypatch.setattr(ext, "post_ocr", lambda *a, **k: (response, "req-1"))

    def save(payload, body, **kwargs):
        saved.append((body, kwargs))
        return {"artifact_handle": "artifact:result"}

    monkeypatch.setattr(ext, "write_artifact_bytes", save)
    payload = {
        "runtime_context": {"external_effect_id": "effect-1"},
        "action": {
            "action_id": "process_document",
            "input": {"artifact_handle": "artifact:input", "schema": {"type": "object"}},
            "target": {
                "connection": {"connection_type": "mistral_document", "secrets": {"api_key": "key"}}
            },
        },
    }
    result = ext.handle_payload(payload)
    assert result["ok"] is True
    assert result["result"]["text"] == "Scanned text"
    assert result["result"]["structured"] == {"total": 3}
    assert result["result"]["request_id"] == "req-1"
    assert result["provider_message_id"] == "req-1"
    assert __import__("json").loads(saved[0][0]) == response
    assert saved[0][1]["binding_key"] == "result_artifact_handle"


def test_http_error_includes_request_id_without_provider_body(monkeypatch):
    import io
    from urllib.error import HTTPError
    import mistral_extension as ext

    monkeypatch.setattr(ext, "resolve_pinned_ips", lambda *a, **k: ["1.1.1.1"])

    def fail(*args, **kwargs):
        raise HTTPError(
            "https://api.mistral.ai/v1/ocr",
            401,
            "unauthorized",
            {"x-request-id": "request-123"},
            io.BytesIO(b"secret body"),
        )

    monkeypatch.setattr(ext, "open_pinned_url", fail)
    with pytest.raises(MistralError) as caught:
        ext.post_ocr({}, "key", 1)
    assert caught.value.code == "provider_http_error"
    assert caught.value.request_id == "request-123"
    assert "secret body" not in str(caught.value)


def test_paid_call_requires_claim_and_suppresses_test_mode(monkeypatch):
    import mistral_extension as ext

    monkeypatch.setattr(ext, "runtime_context_from_payload", lambda _: None)
    monkeypatch.setattr(ext, "post_ocr", lambda *a, **k: pytest.fail("must not send"))
    no_claim = ext.handle_payload({"runtime_context": {}})
    suppressed = ext.handle_payload({"runtime_context": {"test_mode": True}})
    assert no_claim["error_code"] == "effect_claim_required"
    assert no_claim["definitely_no_external_effect"] is True
    assert suppressed["error_code"] == "test_mode_suppressed"
    assert suppressed["definitely_no_external_effect"] is True


def test_invalid_json_schema_and_falsey_table_are_rejected():
    for options in (
        {"schema": {"type": "object", "properties": []}},
        {"schema": {"type": "object", "$ref": "https://example.com/schema"}},
        {"table_format": ""},
        {"table_format": 0},
    ):
        with pytest.raises(MistralError):
            build_request(b"%PDF-1.4", "application/pdf", options)


def test_many_page_response_and_schema_conformance():
    schema = {"type": "object", "properties": {"total": {"type": "number"}}, "required": ["total"]}
    response = {
        "pages": [{"markdown": f"page {i}"} for i in range(10)],
        "document_annotation": '{"total": "bad"}',
    }
    with pytest.raises(MistralError, match="structured"):
        parse_response(response, schema)
    response["document_annotation"] = '{"total": 4}'
    text, structured = parse_response(response, schema)
    assert "page 9" in text
    assert structured == {"total": 4}


def test_provider_and_output_failures_preserve_reconciliation_id(monkeypatch):
    import mistral_extension as ext

    monkeypatch.setattr(ext, "runtime_context_from_payload", lambda _: None)
    monkeypatch.setattr(ext, "report_progress", lambda *_: None)
    monkeypatch.setattr(ext, "find_artifact_descriptor", lambda *a, **k: {"filename": "doc.pdf"})
    monkeypatch.setattr(ext, "read_artifact_bytes", lambda *a, **k: b"%PDF-1.4")
    payload = {
        "runtime_context": {"external_effect_id": "effect-1"},
        "action": {
            "action_id": "process_document",
            "input": {"artifact_handle": "doc"},
            "target": {
                "connection": {"connection_type": "mistral_document", "secrets": {"api_key": "key"}}
            },
        },
    }

    def provider_failure(*args, **kwargs):
        raise MistralError("provider_http_error", "failed", "request-http")

    monkeypatch.setattr(ext, "post_ocr", provider_failure)
    result = ext.handle_payload(payload)
    assert result["provider_message_id"] == "request-http"
    assert result["definitely_no_external_effect"] is False
    monkeypatch.setattr(
        ext, "post_ocr", lambda *a, **k: ({"pages": [{"markdown": "hello"}]}, "request-write")
    )

    def write_failure(*args, **kwargs):
        raise ext.ArtifactAccessError("unavailable")

    monkeypatch.setattr(ext, "write_artifact_bytes", write_failure)
    result = ext.handle_payload(payload)
    assert result["provider_message_id"] == "request-write"
    assert result["definitely_no_external_effect"] is False


@pytest.mark.parametrize("filename", ["text.pdf", "scanned.pdf", "table.pdf"])
def test_pdf_fixtures_are_transmitted_as_document_data(filename):
    import base64
    from pathlib import Path

    data = (Path(__file__).parent / "fixtures" / filename).read_bytes()
    request = build_request(data, "application/pdf", {})
    assert base64.b64decode(request["document"]["document_url"].split(",", 1)[1]) == data
