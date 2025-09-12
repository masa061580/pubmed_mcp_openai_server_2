"""
PubMed MCP Server

This server implements the Model Context Protocol (MCP) with PubMed API integration
providing search, abstract retrieval, and full-text capabilities.
"""

import asyncio
import logging
import os
import time
from typing import Dict, List, Any, Optional
from urllib.parse import quote_plus
import xml.etree.ElementTree as ET

import httpx
import xmltodict
from dotenv import load_dotenv
from fastmcp import FastMCP
from collections import deque

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")))
logger = logging.getLogger(__name__)

# NCBI Configuration
NCBI_API_KEY = os.getenv("NCBI_API_KEY")
NCBI_TOOL_NAME = os.getenv("NCBI_TOOL_NAME", "PubMedMCPServer")
NCBI_EMAIL = os.getenv("NCBI_EMAIL", "pubmed.mcp.server@example.com")  # Default email if not provided
NCBI_BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PMC_OA_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi"

# Rate limiting - 10 req/s with API key, 3 req/s without
MAX_REQUESTS_PER_SECOND = 10 if NCBI_API_KEY else 3

class StrictRateLimiter:
    """Strict rate limiter that ensures exact req/s limits"""
    
    def __init__(self, max_requests: int, window_seconds: int = 1):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests = deque()
        self.lock = asyncio.Lock()
    
    async def acquire(self):
        """Acquire permission to make a request, blocking if necessary"""
        async with self.lock:
            now = time.time()
            
            # Remove old requests outside the time window
            while self.requests and self.requests[0] <= now - self.window_seconds:
                self.requests.popleft()
            
            # If we're at the limit, wait until we can make another request
            if len(self.requests) >= self.max_requests:
                # Calculate how long to wait until the oldest request expires
                sleep_time = (self.requests[0] + self.window_seconds) - now + 0.001  # Small buffer
                if sleep_time > 0:
                    logger.debug(f"Rate limit reached, sleeping for {sleep_time:.3f} seconds")
                    await asyncio.sleep(sleep_time)
                    return await self.acquire()  # Recursive call after waiting
            
            # Record this request
            self.requests.append(now)

rate_limiter = StrictRateLimiter(MAX_REQUESTS_PER_SECOND)

# Server configuration
server_instructions = """
This MCP server provides PubMed/PMC research capabilities with three main tools:

1. search: Query PubMed database with MeSH support, returning up to 100 paper titles
2. get_abstract: Retrieve abstracts for specific PMIDs
3. get_full_text: Retrieve full-text content for PMCIDs (JATS XML or OA service URLs)

All queries respect NCBI rate limits and usage policies.
"""


class PubMedAPIError(Exception):
    """Custom exception for PubMed API errors"""
    pass


class PubMedClient:
    """Client for interacting with NCBI E-utilities and PMC APIs"""
    
    def __init__(self):
        self.session = httpx.AsyncClient(timeout=30.0)
        self.common_params = {
            "tool": NCBI_TOOL_NAME,
            "email": NCBI_EMAIL,
        }
        if NCBI_API_KEY:
            self.common_params["api_key"] = NCBI_API_KEY
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.session.aclose()
    
    async def _make_request(self, url: str, params: Dict[str, Any], method: str = "GET") -> httpx.Response:
        """Make rate-limited HTTP request"""
        # Acquire rate limit permission before making request
        await rate_limiter.acquire()
        
        params.update(self.common_params)
        
        try:
            if method == "GET":
                response = await self.session.get(url, params=params)
            else:  # POST
                response = await self.session.post(url, data=params)
            
            # Handle rate limit responses from NCBI
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 60))
                logger.warning(f"NCBI rate limit exceeded despite local limiting. Waiting {retry_after} seconds.")
                await asyncio.sleep(retry_after)
                return await self._make_request(url, params, method)
            
            # Log successful request for debugging
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(f"Request to {url} completed successfully")
            
            response.raise_for_status()
            return response
            
        except httpx.RequestError as e:
            logger.error(f"Request failed: {e}")
            raise PubMedAPIError(f"Network request failed: {e}")
    
    async def search_pubmed(self, query: str, retmax: int = 100, retstart: int = 0) -> Dict[str, Any]:
        """Search PubMed using esearch and esummary"""
        # Step 1: esearch to get PMIDs
        search_params = {
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retmax": retmax,
            "retstart": retstart,
            "usehistory": "y"
        }
        
        logger.info(f"Searching PubMed: {query}")
        search_response = await self._make_request(f"{NCBI_BASE_URL}/esearch.fcgi", search_params)
        search_data = search_response.json()
        
        if "esearchresult" not in search_data:
            raise PubMedAPIError("Invalid response from esearch")
        
        result = search_data["esearchresult"]
        pmids = result.get("idlist", [])
        count = int(result.get("count", 0))
        
        if not pmids:
            return {
                "count": count,
                "items": [],
                "retmax": retmax,
                "retstart": retstart
            }
        
        # Step 2: esummary to get titles and metadata
        summary_params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "json"
        }
        
        summary_response = await self._make_request(f"{NCBI_BASE_URL}/esummary.fcgi", summary_params)
        summary_data = summary_response.json()
        
        items = []
        if "result" in summary_data:
            for pmid in pmids:
                if pmid in summary_data["result"]:
                    paper = summary_data["result"][pmid]
                    items.append({
                        "pmid": pmid,
                        "title": paper.get("title", "No title available"),
                        "pubdate": paper.get("pubdate", "Unknown"),
                        "journal": paper.get("fulljournalname", paper.get("source", "Unknown journal")),
                        "authors": [author.get("name", "") for author in paper.get("authors", [])]
                    })
        
        return {
            "count": count,
            "items": items,
            "retmax": retmax,
            "retstart": retstart
        }
    
    async def get_abstracts(self, pmids: List[str]) -> List[Dict[str, Any]]:
        """Get abstracts for given PMIDs using efetch"""
        if not pmids:
            return []
        
        # Use POST for large ID lists
        fetch_params = {
            "db": "pubmed",
            "id": ",".join(pmids),
            "retmode": "xml",
            "rettype": "abstract"
        }
        
        logger.info(f"Fetching abstracts for {len(pmids)} PMIDs")
        response = await self._make_request(f"{NCBI_BASE_URL}/efetch.fcgi", fetch_params, method="POST")
        
        # Parse XML response
        try:
            root = ET.fromstring(response.text)
            items = []
            
            for article in root.findall(".//PubmedArticle"):
                pmid_elem = article.find(".//MedlineCitation/PMID")
                if pmid_elem is None:
                    continue
                
                pmid = pmid_elem.text
                
                # Extract title
                title_elem = article.find(".//Article/ArticleTitle")
                title = title_elem.text if title_elem is not None else "No title available"
                
                # Extract abstract
                abstract_texts = []
                for abstract_elem in article.findall(".//Abstract/AbstractText"):
                    label = abstract_elem.get("Label")
                    text = abstract_elem.text or ""
                    if label:
                        abstract_texts.append(f"{label}: {text}")
                    else:
                        abstract_texts.append(text)
                
                abstract = "\n".join(abstract_texts) if abstract_texts else "No abstract available"
                
                # Extract journal info
                journal_elem = article.find(".//Journal/Title")
                journal = journal_elem.text if journal_elem is not None else "Unknown journal"
                
                # Extract publication year
                year_elem = article.find(".//PubDate/Year")
                year = year_elem.text if year_elem is not None else "Unknown"
                
                # Extract authors
                authors = []
                for author_elem in article.findall(".//AuthorList/Author"):
                    forename = author_elem.find("ForeName")
                    lastname = author_elem.find("LastName")
                    if forename is not None and lastname is not None:
                        authors.append(f"{forename.text} {lastname.text}")
                
                items.append({
                    "pmid": pmid,
                    "title": title,
                    "abstract": abstract,
                    "journal": journal,
                    "year": year,
                    "authors": authors
                })
            
            return items
            
        except ET.ParseError as e:
            logger.error(f"XML parsing error: {e}")
            raise PubMedAPIError(f"Failed to parse XML response: {e}")
    
    async def get_full_text(self, pmcids: List[str]) -> List[Dict[str, Any]]:
        """Get full text for given PMCIDs using efetch and OA service"""
        if not pmcids:
            return []
        
        items = []
        
        for pmcid in pmcids:
            # Clean PMCID format
            clean_pmcid = pmcid.replace("PMC", "") if pmcid.startswith("PMC") else pmcid
            full_pmcid = f"PMC{clean_pmcid}"
            
            try:
                # Try to get JATS XML via efetch
                fetch_params = {
                    "db": "pmc",
                    "id": full_pmcid,
                    "retmode": "xml"
                }
                
                logger.info(f"Fetching full text for {full_pmcid}")
                xml_response = await self._make_request(f"{NCBI_BASE_URL}/efetch.fcgi", fetch_params, method="POST")
                
                jats_xml = xml_response.text
                
                # Try to get OA service info for PDF/supplementary files
                oa_url = None
                pdf_url = None
                
                try:
                    oa_params = {"id": full_pmcid}
                    oa_response = await self._make_request(PMC_OA_URL, oa_params)
                    oa_data = xmltodict.parse(oa_response.text)
                    
                    # Extract download links if available
                    if "OA" in oa_data and "records" in oa_data["OA"]:
                        record = oa_data["OA"]["records"].get("record")
                        if record:
                            links = record.get("link", [])
                            if not isinstance(links, list):
                                links = [links]
                            
                            for link in links:
                                if link.get("@format") == "pdf":
                                    pdf_url = link.get("@href")
                                    break
                
                except Exception as e:
                    logger.warning(f"Could not fetch OA info for {full_pmcid}: {e}")
                
                items.append({
                    "pmcid": full_pmcid,
                    "jats_xml": jats_xml,
                    "pdf_url": pdf_url,
                    "status": "success"
                })
                
            except Exception as e:
                logger.error(f"Failed to fetch full text for {full_pmcid}: {e}")
                items.append({
                    "pmcid": full_pmcid,
                    "jats_xml": None,
                    "pdf_url": None,
                    "status": "error",
                    "error": str(e)
                })
        
        return items


def create_server() -> FastMCP:
    """Create and configure the MCP server"""
    
    # Log configuration (email is now optional with default)
    logger.info(f"Initializing PubMed MCP Server with tool: {NCBI_TOOL_NAME}, email: {NCBI_EMAIL}")
    if NCBI_API_KEY:
        logger.info("✅ API key configured - using 10 requests/second rate limit")
    else:
        logger.warning("⚠️  No API key - using 3 requests/second rate limit")
        logger.info("To get an API key and increase rate limit, visit: https://www.ncbi.nlm.nih.gov/account/settings/")
    
    logger.info(f"🚦 Strict rate limiting enabled: {MAX_REQUESTS_PER_SECOND} requests/second")
    
    mcp = FastMCP(name="PubMed MCP Server", instructions=server_instructions)
    
    @mcp.tool()
    async def search(query: str, max_results: int = 100, start_index: int = 0) -> Dict[str, Any]:
        """
        Search PubMed database with MeSH support.
        
        Args:
            query: Search query string. Supports MeSH terms (e.g., "asthma[mh] AND adult[mh]")
            max_results: Maximum number of results to return (default: 100, max: 100)
            start_index: Starting index for pagination (default: 0)
        
        Returns:
            Dictionary containing search results with paper metadata
        """
        if not query or not query.strip():
            return {"count": 0, "items": [], "retmax": max_results, "retstart": start_index}
        
        # Limit max_results to 100 as per specification
        max_results = min(max_results, 100)
        
        async with PubMedClient() as client:
            try:
                results = await client.search_pubmed(query, max_results, start_index)
                logger.info(f"Search returned {len(results['items'])} results for query: {query}")
                return results
            except Exception as e:
                logger.error(f"Search failed: {e}")
                raise ValueError(f"Search failed: {str(e)}")
    
    @mcp.tool()
    async def get_abstract(pmids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Retrieve abstracts for specific PMIDs.
        
        Args:
            pmids: List of PubMed IDs (PMIDs)
        
        Returns:
            Dictionary with 'items' containing abstract data for each PMID
        """
        if not pmids:
            return {"items": []}
        
        # Remove duplicates and validate PMIDs
        unique_pmids = list(set(str(pmid).strip() for pmid in pmids if str(pmid).strip()))
        
        async with PubMedClient() as client:
            try:
                abstracts = await client.get_abstracts(unique_pmids)
                logger.info(f"Retrieved {len(abstracts)} abstracts for {len(unique_pmids)} PMIDs")
                return {"items": abstracts}
            except Exception as e:
                logger.error(f"Abstract retrieval failed: {e}")
                raise ValueError(f"Abstract retrieval failed: {str(e)}")
    
    @mcp.tool()
    async def get_full_text(pmcids: List[str]) -> Dict[str, Any]:
        """
        Retrieve full text content for PMCIDs.
        
        Args:
            pmcids: List of PMC IDs (PMCIDs, with or without 'PMC' prefix)
        
        Returns:
            Dictionary with 'items' containing full text data and 'notes' about availability
        """
        if not pmcids:
            return {"items": [], "notes": []}
        
        # Remove duplicates and clean PMCIDs
        unique_pmcids = list(set(str(pmcid).strip() for pmcid in pmcids if str(pmcid).strip()))
        
        async with PubMedClient() as client:
            try:
                full_texts = await client.get_full_text(unique_pmcids)
                
                success_count = sum(1 for item in full_texts if item["status"] == "success")
                logger.info(f"Retrieved {success_count} full texts for {len(unique_pmcids)} PMCIDs")
                
                notes = [
                    "Full text availability depends on PMC Open Access status",
                    "JATS XML is provided when available",
                    "PDF URLs are only available for Open Access articles"
                ]
                
                return {
                    "items": full_texts,
                    "notes": notes
                }
            except Exception as e:
                logger.error(f"Full text retrieval failed: {e}")
                raise ValueError(f"Full text retrieval failed: {str(e)}")
    
    return mcp


def main():
    """Main function to start the MCP server"""
    try:
        # Create server (email is now optional with default)
        server = create_server()
        
        # Start server
        host = os.getenv("HOST", "0.0.0.0")
        port = int(os.getenv("PORT", 8000))
        
        logger.info(f"Starting PubMed MCP server on {host}:{port}")
        logger.info("Server will be accessible via SSE transport")
        
        server.run(transport="sse", host=host, port=port)
        
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise


if __name__ == "__main__":
    main()