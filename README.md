# PubMed MCP Server

A Model Context Protocol (MCP) server that provides access to PubMed/PMC research data through six core functions:

- **Search**: Query PubMed with MeSH support, returning up to 100 paper titles with PMCID info
- **Fetch**: Retrieve abstract for a single PMID (OpenAI MCP compliant)
- **Fetch Batch**: Retrieve abstracts for multiple PMIDs efficiently
- **Get Full Text**: Retrieve full-text content for PMCIDs (JATS XML or OA URLs)
- **Count**: Get result count for query optimization and refinement
- **Count Batch**: Get counts for multiple queries efficiently

## Features

- **MeSH Query Support**: Advanced medical subject heading searches
- **PMCID Detection**: Automatically identifies papers with PMC full-text availability
- **Rate Limited**: Respects NCBI guidelines (3-10 req/s depending on API key)
- **XML Parsing**: Handles PubMed XML responses with proper error handling
- **Open Access Integration**: Detects and provides PDF URLs for OA articles
- **Comprehensive Metadata**: Returns titles, abstracts, authors, journals, dates

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Environment Configuration (Optional)

All configuration is optional. The server works out-of-the-box without any setup.

For customization, copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Available settings:

```env
# All settings are optional
NCBI_API_KEY=your_ncbi_api_key_here  # For higher rate limits (10 req/s vs 3 req/s)  
NCBI_TOOL_NAME=PubMedMCPServer       # Custom tool identifier
NCBI_EMAIL=your.email@example.com    # Contact email (uses default if not provided)

# Server settings
HOST=0.0.0.0
PORT=8000
LOG_LEVEL=INFO
```

### 3. Start the Server

```bash
python pubmed_mcp_server.py
```

Server will be available at: `http://localhost:8000/sse/`

### 4. Get NCBI API Key (Optional, for Higher Rate Limits)

For higher throughput (10 req/s instead of 3 req/s):

1. Visit [NCBI API Key Settings](https://www.ncbi.nlm.nih.gov/account/settings/)
2. Sign in to your NCBI account  
3. Create a new API key
4. Add `NCBI_API_KEY=your_key_here` to your `.env` file

**Benefits of API Key:**
- 10 requests/second (vs 3 without key)
- Better reliability for high-volume usage

## MCP Tools

### 1. Search

Query PubMed database with advanced search capabilities.

**Parameters:**
- `query` (string): Search query with MeSH support

**Example Queries:**
```
"COVID-19 AND vaccine"
"asthma[mh] AND adult[mh]"  
"diabetes[tiab] AND 2023:2024[dp]"
"cancer treatment[majr]"
```

**Response:**
```json
{
  "results": [
    {
      "id": "12345678",
      "title": "Study Title",
      "url": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
      "pmcid": "PMC1234567",  // Present if full text available in PMC
      "full_text_available": true  // Indicates PMC full text availability
    }
  ]
}
```

### 2. Fetch

Retrieve abstract for a **single PMID only** (OpenAI MCP compliant).

**Important:** This tool accepts exactly one PMID per request. For multiple PMIDs, use `fetch_batch`.

**Parameters:**
- `id` (string): Single PubMed ID (PMID) - **NO ARRAYS OR COMMA-SEPARATED VALUES**

**Example:**
```json
{
  "id": "40930554"
}
```

**Response:**
```json
{
  "id": "40930554",
  "title": "Paper Title",
  "text": "Background: ... Methods: ... Results: ... Conclusions: ...",
  "url": "https://pubmed.ncbi.nlm.nih.gov/40930554/",
  "metadata": {
    "journal": "Journal Name",
    "year": "2024",
    "authors": ["Author 1", "Author 2"]
  }
}
```

### 3. Fetch Batch

Retrieve abstracts for multiple PMIDs efficiently in one request.

**Parameters:**
- `pmids` (array): List of PubMed IDs (PMIDs)

**Example:**
```json
{
  "pmids": ["40930554", "40929575", "40929571"]
}
```

**Response:**
```json
{
  "items": [
    {
      "pmid": "40930554",
      "title": "Paper Title 1",
      "abstract": "Background: ... Methods: ... Results: ... Conclusions: ...",
      "journal": "Journal Name",
      "year": "2024",
      "authors": ["Author 1", "Author 2"]
    },
    {
      "pmid": "40929575", 
      "title": "Paper Title 2",
      "abstract": "Background: ... Methods: ... Results: ... Conclusions: ...",
      "journal": "Another Journal",
      "year": "2024",
      "authors": ["Author 3", "Author 4"]
    }
  ]
}
```

### 4. Get Full Text

Retrieve full-text content for PMCIDs.

**Parameters:**
- `pmcids` (array): List of PMC IDs (with or without 'PMC' prefix)

**Example:**
```json
{
  "pmcids": ["PMC1234567", "7654321"]
}
```

**Response:**
```json
{
  "items": [
    {
      "pmcid": "PMC1234567",
      "jats_xml": "<article>...</article>",
      "pdf_url": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC1234567/pdf/",
      "status": "success"
    }
  ],
  "notes": [
    "Full text availability depends on PMC Open Access status",
    "JATS XML is provided when available",
    "PDF URLs are only available for Open Access articles"
  ]
}
```

### 5. Count

Get result count for a search query without retrieving papers (for query optimization).

**Parameters:**
- `query` (string): Search query with MeSH support

**Example:**
```json
{
  "query": "lung cancer[mh] AND 2024[dp]"
}
```

**Response:**
```json
{
  "query": "lung cancer[mh] AND 2024[dp]",
  "count": 12543,
  "query_translation": "\"lung neoplasms\"[MeSH Terms] AND 2024[dp]",
  "warnings": []
}
```

### 6. Count Batch

Get counts for multiple queries efficiently (for comparing search strategies).

**Parameters:**
- `queries` (array): List of search queries

**Example:**
```json
{
  "queries": [
    "diabetes",
    "diabetes[mh]",
    "diabetes[majr]",
    "diabetes[mh] AND clinical trial[pt]"
  ]
}
```

**Response:**
```json
[
  {"query": "diabetes", "count": 1072365, "query_translation": "..."},
  {"query": "diabetes[mh]", "count": 562256, "query_translation": "..."},
  {"query": "diabetes[majr]", "count": 287431, "query_translation": "..."},
  {"query": "diabetes[mh] AND clinical trial[pt]", "count": 45123, "query_translation": "..."}
]
```

## Query Refinement Workflow

The count tools enable efficient query refinement:

```python
# Start broad, then refine
"cancer"                                    # 5,000,000+ results (too broad)
"lung cancer"                               # 800,000 results
"lung cancer[mh]"                          # 400,000 results (MeSH term)
"lung cancer[mh] AND 2024[dp]"            # 12,000 results
"lung cancer[majr] AND clinical trial[pt] AND 2024[dp]"  # 450 results (optimal)
```

## MeSH Search Examples

The server supports advanced PubMed search syntax:

```bash
# MeSH terms
"diabetes mellitus[mh]"

# MeSH major topic  
"cancer[majr]"

# Title/Abstract
"machine learning[tiab]"

# Publication date
"2023:2024[dp]"

# Combined search
"COVID-19[mh] AND vaccine[tiab] AND 2023:2024[dp]"

# Author search
"Smith J[au]"

# Journal search  
"nature[ta]"
```

## Usage with ChatGPT/Claude

1. Start the server locally
2. Use the URL: `http://localhost:8000/sse/`
3. Configure as MCP connector in your AI interface
4. Enable tools: `search`, `fetch`, `fetch_batch`, `get_full_text`

## Rate Limiting & Compliance

- **Without API Key**: 3 requests/second maximum
- **With API Key**: 10 requests/second maximum  
- Automatic retry with exponential backoff
- Follows NCBI usage guidelines
- Tool and email identification in all requests

## Error Handling

The server handles various error conditions:

- Rate limit exceeded (429) → Automatic retry
- Invalid PMIDs/PMCIDs → Graceful error response
- Network timeouts → Retry with backoff
- XML parsing errors → Detailed error messages
- Missing abstracts → "No abstract available" message

## Development

### Testing Individual Functions

You can test the server functions directly:

```python
import asyncio
from pubmed_mcp_server import PubMedClient

async def test_search():
    async with PubMedClient() as client:
        results = await client.search_pubmed("COVID-19 AND vaccine", retmax=5)
        print(f"Found {results['count']} papers")
        for item in results['items']:
            print(f"- {item['title']}")

asyncio.run(test_search())
```

### Logging

Set `LOG_LEVEL=DEBUG` in `.env` for detailed request/response logging.

## License

This implementation follows NCBI usage policies and guidelines. Please ensure compliance with:

- NCBI E-utilities usage guidelines
- PMC Open Access licensing terms
- Rate limiting requirements
- Proper attribution in research use