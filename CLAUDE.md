# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is a documentation repository focused on PubMed API integration with Model Context Protocol (MCP) servers. The repository contains comprehensive technical specifications and implementation guides for building MCP servers that interact with NCBI's PubMed/PMC APIs.

## Key Documentation Files

### OpenAI_MCP.md
Complete guide for building remote MCP servers compatible with ChatGPT connectors and deep research functionality. Contains:
- MCP server setup using FastMCP framework
- Required `search` and `fetch` tool implementations
- Vector store integration examples
- Authentication and security considerations
- Replit deployment instructions

### Pubmed_API_MCP.md (Japanese)
Detailed technical specification for implementing a PubMed/PMC API MCP server with three core functions:
- **Search**: MeSH-compatible queries returning up to 100 paper titles
- **Fetch**: Abstract retrieval for PMID arrays
- **GetFullText**: Full-text retrieval for PMCID arrays (JATS XML or OA service URLs)

## Technical Context

### API Integration Focus
- **NCBI E-utilities**: Primary API for PubMed data access
  - Base URL: `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/`
  - Key tools: esearch, esummary, efetch, epost, elink
- **PMC OA Web Service**: For open access full-text content
- **ID Converter API**: PMID/PMCID/DOI conversions

### Rate Limiting & Compliance
- Without API key: 3 requests/second maximum
- With API key: 10 requests/second maximum
- Required parameters: `tool` (application name) and `email` (developer contact)
- Large-scale operations should use History Server (`WebEnv`/`query_key`)
- PMC automatic downloading only allowed via authorized routes (OA service, FTP, BioC API, AWS RODA)

### MCP Server Requirements
Based on the documentation, any MCP server implementation should provide:
1. **search** tool returning JSON with `results` array containing `{id, title, url}`
2. **fetch** tool returning document content with `{id, title, text, url, metadata}`
3. Proper error handling and rate limiting
4. SSL/TLS transport (typically SSE - Server-Sent Events)

## Implementation Guidelines

When working with this repository:
- Follow NCBI's usage policies and rate limits strictly
- Implement proper error handling for API responses
- Use POST requests for large ID lists to avoid URL length limits
- Handle XML parsing for efetch responses (JSON not supported for efetch)
- Respect copyright and licensing for PMC content
- Implement exponential backoff for rate limit errors (429 status)

## Development Notes

This is primarily a documentation repository - actual server implementations would be created separately following these specifications. The guides provide complete implementation examples in Python using FastMCP framework, but the patterns can be adapted to other languages and MCP frameworks.