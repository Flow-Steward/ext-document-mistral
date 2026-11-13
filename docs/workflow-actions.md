# Workflow actions

Save a Mistral API key in a project Mistral connection and select it on the Extension tools step. Start with a PDF artifact from an earlier step. Document contents are sent to Mistral and provider billing applies.

Map your PDF into PDF document artifact. For invoice extraction, paste the example schema into Extraction JSON Schema. Use text or structured in later steps; if inline text/data is truncated or omitted, read the complete result artifact.

Select the named action in an Extension tools step. Map workflow values to its inputs and map the returned fields needed by later steps. Examples below contain sample data; replace artifact handles and embedding values with actual earlier-step outputs.

## Extract PDF text and schema-guided data

Send a PDF artifact to Mistral OCR to extract text, tables and optional data matching a supplied JSON Schema. Returns bounded inline text/data plus a complete result artifact; select a Mistral connection and review extracted values before use.

- **PDF document artifact**: Map a PDF artifact from an earlier workflow step, maximum 20 MiB. Other file formats are not accepted.
- **Table output format**: Choose inline Markdown (default), separate Markdown tables or separate HTML tables in the full result.
- **Extraction JSON Schema**: Optional Draft 2020-12 object schema up to 64 KiB, without references. Applies to the whole document. Inline structured data may be omitted for size, complexity or protected credential fields; the complete result remains in the artifact.

Example input values:

```json
{
  "artifact_handle": "artifact:input",
  "schema": {
    "type": "object",
    "properties": {
      "invoice_number": {
        "type": "string"
      },
      "total": {
        "type": "number"
      }
    },
    "required": [
      "invoice_number",
      "total"
    ]
  }
}
```

In the workflow editor, select the source artifact from the earlier step. `artifact:input` illustrates the mapped handle; replace it with the actual handle supplied by that step.
