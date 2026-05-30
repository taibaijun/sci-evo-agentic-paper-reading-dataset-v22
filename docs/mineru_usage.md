# MinerU Usage

MinerU is used as the document understanding and parsing layer.

## Parsing Outputs

For each paper, MinerU produces a directory like `docs/0001/` containing:

- `mineru.md`: Markdown text extracted by MinerU.
- `combined.md`: normalized full-paper text used as the canonical evidence source.
- `content_list.json`: structured content blocks.
- `middle.json`: intermediate parse representation.
- `images/`: extracted figures and page assets when available.
- `status.json`: parse status and metadata.

## Use in Dataset Construction

The V22 pipeline never treats the PDF filename or model memory as final evidence. Final evidence must come from `combined.md`.

MinerU is used for:

1. retrieving abstracts, section text, results, methods, discussions, and captions;
2. chunking long papers for event extraction;
3. checking every evidence quote against full-paper text;
4. preserving source document traceability via `docs/####/combined.md` paths.

## Included Raw Samples

`raw_data_samples/docs/` contains 10 complete MinerU sample directories with `combined.md`, `mineru.md`, `content_list.json`, and `status.json` when available. These demonstrate the original data format without packaging all source papers.
