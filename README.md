# PubMed MCP Server

A Model Context Protocol (MCP) server that provides access to PubMed/PMC research data through three core functions:

- **Search**: Query PubMed with MeSH support, returning up to 100 paper titles
- **Fetch**: Retrieve abstracts for specific PMIDs  
- **Get Full Text**: Retrieve full-text content for PMCIDs (JATS XML or OA URLs)

## Features

- **MeSH Query Support**: Advanced medical subject heading searches
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
- `max_results` (int, optional): Max results to return (default: 100, max: 100)
- `start_index` (int, optional): Starting index for pagination (default: 0)

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
  "count": 1234,
  "items": [
    {
      "pmid": "12345678",
      "title": "Study Title",
      "pubdate": "2023",
      "journal": "Journal Name",
      "authors": ["Author 1", "Author 2"]
    }
  ],
  "retmax": 100,
  "retstart": 0
}
```

### 2. Fetch

Retrieve abstracts for specific PMIDs.

**Parameters:**
- `pmids` (array): List of PubMed IDs

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
      "title": "Paper Title",
      "abstract": "Background: ... Methods: ... Results: ... Conclusions: ...",
      "journal": "Journal Name",
      "year": "2024",
      "authors": ["Author 1", "Author 2"]
    }
  ]
}
```

### 3. Get Full Text

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
4. Enable tools: `search`, `fetch`, `get_full_text`

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