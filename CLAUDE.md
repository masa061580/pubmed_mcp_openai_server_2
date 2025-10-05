# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is a PubMed MCP server implementation that provides access to NCBI's PubMed/PMC research data through the Model Context Protocol (MCP). The server is built with Python using FastMCP framework and follows NCBI E-utilities API guidelines.

## Commands

### Running the Server
```bash
# Install dependencies
pip install -r requirements.txt

# Start the MCP server
python pubmed_mcp_server.py

# Run quick test suite
python test_server.py quick

# Run full test suite
python test_server.py
```

### Testing
```bash
# Test rate limiting compliance
python test_rate_limit.py

# Test individual tools with minimal output
python test_server.py quick
```

### Configuration
- Copy `.env.example` to `.env` for custom configuration
- All settings are optional - server works with defaults
- API key increases rate limit from 3 req/s to 10 req/s

## Architecture

### Core Server (`pubmed_mcp_server.py`)
The main server implements seven MCP tools:

1. **search**: PubMed queries with MeSH support, returns configurable number of paper titles (1-200, default: 50) with PMCID info. Supports Best Match (relevance) and Most Recent (pub_date) sorting
2. **fetch**: Single PMID abstract retrieval (OpenAI MCP compliant)
3. **fetch_batch**: Multiple PMID abstract retrieval (efficient batch processing)
4. **get_full_text**: PMC full-text retrieval (sections only)
5. **count**: Get result count for query optimization (fast, no data retrieval)
6. **find_similar_articles**: Find similar articles using PubMed's recommendation algorithm
7. **export_to_ris**: Export articles to RIS format for citation managers (EndNote/Zotero/Mendeley)

### Key Components

**Rate Limiting (`StrictRateLimiter`)**
- Enforces exact NCBI rate limits (3-10 req/s)
- Uses deque-based sliding window algorithm
- Blocks requests that would exceed limits

**PubMedClient Class**
- Handles all NCBI API interactions
- Manages HTTP sessions with httpx
- Implements automatic retry with exponential backoff
- Handles XML parsing for efetch responses

**API Flow**
1. Search: `esearch` → `esummary` (JSON responses)
2. Fetch: `efetch` with XML parsing (abstracts)
3. Full-text: `efetch` (PMC) + OA Web Service

### NCBI API Integration

**E-utilities Endpoints Used:**
- `/esearch.fcgi` - Query PubMed database
- `/esummary.fcgi` - Get paper metadata
- `/efetch.fcgi` - Retrieve abstracts and full-text
- `/elink.fcgi` - Find similar articles and citations
- PMC OA Service - PDF/supplementary file URLs

**Critical Compliance Points:**
- Always include `tool`, `email` parameters
- Never exceed rate limits (enforced by `StrictRateLimiter`)
- Use POST for large ID lists (>200 IDs)
- Handle 429 responses with retry logic

## Implementation Details

### MeSH Query Support
The server supports advanced PubMed syntax:
- `[mh]` - MeSH terms
- `[majr]` - MeSH Major Topic
- `[tiab]` - Title/Abstract
- `[dp]` - Date published
- Boolean operators: AND, OR, NOT

### XML Parsing Strategy
- Uses `xml.etree.ElementTree` for efetch responses
- Handles multi-section abstracts with labels
- Extracts structured metadata (authors, journal, year)

### Error Handling
- PubMedAPIError for API-specific issues
- Network retry with exponential backoff
- Graceful degradation for missing data fields
- Detailed logging at multiple levels

### OpenAI MCP Compliance
The `fetch` tool specifically follows OpenAI MCP requirements:
- Accepts single PMID only (no arrays)
- Returns specific JSON structure with `id`, `title`, `text`, `url`, `metadata`
- Separate `fetch_batch` tool for multiple PMIDs

### Similar Articles Algorithm
The `find_similar_articles` tool uses NCBI's elink API with `pubmed_pubmed` linkname:
- Computational similarity based on title/abstract words, MeSH terms, journal info
- Returns up to 100 similar articles with metadata
- Includes full-text availability detection
- Useful for literature review and related research discovery

### RIS Export Functionality (`ris_exporter.py`)
The `export_to_ris` tool generates compact RIS format for citation managers:
- **Minimal metadata approach**: Only exports PMID, title, first author, journal, year, DOI
- **Citation manager integration**: EndNote/Zotero/Mendeley auto-fetch complete metadata from PubMed using PMID
- **Workflow optimization**: Returns RIS text in chat → user copies → saves as .ris file → imports to citation manager
- **DOI extraction**: Automatically extracts DOI from PubMed XML (ArticleId with IdType="doi")
- **No file download**: MCP protocol limitation - users manually copy/paste RIS text to save locally