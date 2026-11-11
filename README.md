# Mistral Document AI

Turn PDF artifacts into text and structured data for document review and processing workflows with Mistral Document AI. The action uses Mistral's OCR service. Supply a JSON Schema when you want document data organized into named fields, or use the text output directly in later workflow steps. A complete JSON result is also saved as an artifact.

Choose whether tables appear as inline Markdown, separate Markdown or HTML tables. The schema-guided extraction applies to the whole document, making the action useful for preparing invoice data, document summaries or review inputs before your own workflow applies business rules. The operation returns a provider request ID, a text-truncation flag and, when relevant, a reason why structured data was omitted from the inline result.

PDF input is limited to 20 MiB. Inline text and structured data each have 128 KiB JSON-encoded limits, while the complete result artifact can be up to 50 MiB. Some structured results therefore need to be read from the artifact. Document contents are sent to Mistral, and provider access and billing apply. Review extracted values before acting on them.

Select a PDF artifact (maximum 20 MiB). Choose inline Markdown, separate Markdown or HTML tables. Optionally supply an Draft 2020-12 object JSON Schema without references (maximum 64 KiB); schema extraction processes the whole document. Inline text is bounded to 128 KiB of JSON-escaped text; `text_truncated` indicates truncation. Structured output is returned inline when it fits within 128 KiB of JSON-escaped data, complexity limits, and the host credential-field policy; otherwise `structured` is null, `structured_omitted` is true, and `structured_omission_reason` identifies `size_or_complexity` or `credential_field`. The host also blocks results that reflect a protected connection secret; avoid documents containing the API key. The complete response and document annotation remain in the result artifact (up to 50 MiB). Review results before use. Requests are not automatically retried; on timeout check provider status before retrying.

Mistral API: https://docs.mistral.ai/api/endpoint/ocr .
