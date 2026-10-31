# Mistral Document AI

Connect a project-scoped Mistral API key created at https://console.mistral.ai/ in Configuration. API access and billing may be required. Process document sends a PDF artifact to Mistral OCR, returning text, an optional schema-guided structured object, and a complete JSON result artifact. Requests may incur charges and send document contents to Mistral.

Select a PDF artifact (maximum 20 MiB). Choose inline Markdown, separate Markdown or HTML tables. Optionally supply an Draft 2020-12 object JSON Schema without references (maximum 64 KiB); schema extraction processes the whole document. Inline text is bounded to 128 KiB of JSON-escaped text; `text_truncated` indicates truncation. Structured output is returned inline when it fits within 128 KiB of JSON-escaped data, complexity limits, and the host credential-field policy; otherwise `structured` is null, `structured_omitted` is true, and `structured_omission_reason` identifies `size_or_complexity` or `credential_field`. The host also blocks results that reflect a protected connection secret; avoid documents containing the API key. The complete response and document annotation remain in the result artifact (up to 50 MiB). Review results before use. Requests are not automatically retried; on timeout check provider status before retrying.

Mistral API: https://docs.mistral.ai/api/endpoint/ocr .
