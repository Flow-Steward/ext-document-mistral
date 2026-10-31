# Mistral Document AI

Connect a project-scoped Mistral API key created at https://console.mistral.ai/ in Configuration. API access and billing may be required. Process document sends a PDF artifact to Mistral OCR, returning text, an optional schema-guided structured object, and a complete JSON result artifact. Requests may incur charges and send document contents to Mistral.

Select a PDF artifact (maximum 20 MiB). Choose inline Markdown, separate Markdown or HTML tables. Optionally supply an object JSON Schema (maximum 64 KiB); annotation processes only the first eight pages. OCR text is truncated inline at 512 KiB; the full response remains in the artifact (up to 50 MiB). Structured output is limited to 1 MiB inline. Review results before use. Requests are not automatically retried; on timeout check provider status before retrying.

Mistral API: https://docs.mistral.ai/api/endpoint/ocr .
