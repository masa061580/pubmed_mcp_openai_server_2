"""
PubMed MCP Server

This server implements the Model Context Protocol (MCP) with PubMed API integration
providing search, abstract retrieval, and full-text capabilities.
"""

import asyncio
import json
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

from ris_exporter import RISExporter

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
ICITE_API_URL = "https://icite.od.nih.gov/api/pubs"

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
This MCP server provides PubMed/PMC research capabilities with eight main tools:

1. search: PubMed queries with MeSH support, returning configurable number of paper titles (1-200, default: 50) with PMCID detection. Supports Best Match (relevance) and Most Recent (pub_date) sorting
2. fetch: Retrieve abstract for a single PMID (OpenAI MCP compliant)
3. fetch_batch: Retrieve abstracts for multiple PMIDs in one request
4. get_full_text: Retrieve full-text content for PMCIDs (sections only)
5. count: Get result count for a query (for search optimization)
6. find_similar_articles: Find similar articles using PubMed's recommendation algorithm
7. export_to_ris: Export articles to RIS format for citation managers (EndNote/Zotero/Mendeley)
8. get_citation_counts: Get citation counts for PMIDs using NIH iCite API (up to 1000 PMIDs per request)

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
    
    async def search_pubmed(self, query: str, retmax: int = 100, retstart: int = 0, sort: str = "relevance") -> Dict[str, Any]:
        """Search PubMed using esearch and esummary with PMCID detection

        Args:
            query: Search query string
            retmax: Maximum number of results to return
            retstart: Starting position for results
            sort: Sort order - "relevance" for Best Match (ML-based), "pub_date" for Most Recent
        """
        # Step 1: esearch to get PMIDs
        search_params = {
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retmax": retmax,
            "retstart": retstart,
            "usehistory": "y",
            "sort": sort  # Add sort parameter (relevance=Best Match, pub_date=Most Recent)
        }
        
        logger.info(f"Searching PubMed: {query} (sort: {sort})")
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
        
        # Step 2: esummary to get titles, metadata, and PMCIDs from articleids
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
                    
                    # Extract PMCID from articleids
                    pmcid = None
                    if "articleids" in paper:
                        for article_id in paper["articleids"]:
                            if article_id.get("idtype") == "pmc":
                                pmcid = article_id.get("value")
                                break
                    
                    item = {
                        "pmid": pmid,
                        "pmcid": pmcid,
                        "title": paper.get("title", "No title available"),
                        "pubdate": paper.get("pubdate", "Unknown"),
                        "journal": paper.get("fulljournalname", paper.get("source", "Unknown journal")),
                        "authors": [author.get("name", "") for author in paper.get("authors", [])],
                        "full_text_available": pmcid is not None
                    }
                    
                    items.append(item)
        
        return {
            "count": count,
            "items": items,
            "retmax": retmax,
            "retstart": retstart
        }
    
    async def count_search(self, query: str) -> Dict[str, Any]:
        """Get only the count of search results for query adjustment"""
        # Use esearch with retmax=0 for fast count-only response
        search_params = {
            "db": "pubmed",
            "term": query,
            "retmode": "json",
            "retmax": 0,  # Don't retrieve any IDs, just count
        }
        
        logger.info(f"Counting results for query: {query}")
        search_response = await self._make_request(f"{NCBI_BASE_URL}/esearch.fcgi", search_params)
        search_data = search_response.json()
        
        if "esearchresult" not in search_data:
            raise PubMedAPIError("Invalid response from esearch")
        
        result = search_data["esearchresult"]
        
        # Extract count and query translation info
        count = int(result.get("count", 0))
        
        # Get query translation to show how PubMed interpreted the query
        query_translation = result.get("querytranslation", "")
        
        # Get any warnings about the search
        warning_list = result.get("warninglist", {})
        warnings = []
        if warning_list:
            phrase_ignored = warning_list.get("phraseignored", [])
            quoted_phrase_not_found = warning_list.get("quotedphrasefound", [])
            if phrase_ignored:
                warnings.extend(phrase_ignored)
            if quoted_phrase_not_found:
                warnings.extend(quoted_phrase_not_found)
        
        return {
            "query": query,
            "count": count,
            "query_translation": query_translation,
            "warnings": warnings
        }

    async def find_similar_articles(self, pmid: str, retmax: int = 20) -> Dict[str, Any]:
        """Find similar articles using elink API

        Args:
            pmid: PubMed ID of the reference article
            retmax: Maximum number of similar articles to return (default: 20, max: 100)

        Returns:
            Dictionary containing similar articles with metadata
        """
        if not pmid or not pmid.strip():
            return {
                "reference_pmid": pmid,
                "similar_articles": [],
                "count": 0,
                "error": "No PMID provided"
            }

        # Validate and constrain retmax parameter
        if retmax < 1:
            retmax = 1
        elif retmax > 100:
            retmax = 100

        try:
            # Alternative approach: Use the article's metadata to find similar articles
            # Step 1: Get the article's abstract and metadata first
            fetch_params = {
                "db": "pubmed",
                "id": pmid.strip(),
                "retmode": "xml",
                "rettype": "abstract"
            }

            logger.info(f"Getting article metadata for PMID: {pmid}")
            fetch_response = await self._make_request(f"{NCBI_BASE_URL}/efetch.fcgi", fetch_params, method="POST")

            # Parse XML to extract MeSH terms and keywords
            import xml.etree.ElementTree as ET
            root = ET.fromstring(fetch_response.text)

            # Extract MeSH terms for similarity search
            mesh_terms = []
            for mesh_heading in root.findall(".//MeshHeading"):
                descriptor = mesh_heading.find("DescriptorName")
                if descriptor is not None:
                    mesh_terms.append(descriptor.text)

            # Extract title words for similarity
            title_elem = root.find(".//ArticleTitle")
            title = title_elem.text if title_elem is not None else ""

            if not mesh_terms and not title:
                return {
                    "reference_pmid": pmid,
                    "similar_articles": [],
                    "count": 0,
                    "error": "Could not extract metadata for similarity search"
                }

            # Step 2: Build a search query using the extracted MeSH terms and title words
            search_terms = []

            # Add top MeSH terms (limit to avoid too broad search)
            for mesh_term in mesh_terms[:3]:  # Use top 3 MeSH terms
                search_terms.append(f'"{mesh_term}"[MeSH Terms]')

            # Add key title words (excluding common words)
            if title:
                title_words = [word.strip('.,;:()[]{}').lower()
                             for word in title.split()
                             if len(word) > 3 and word.lower() not in
                             ['the', 'and', 'for', 'with', 'from', 'that', 'this', 'study', 'analysis']]
                for word in title_words[:2]:  # Use top 2 meaningful title words
                    search_terms.append(f'"{word}"[Title/Abstract]')

            if not search_terms:
                return {
                    "reference_pmid": pmid,
                    "similar_articles": [],
                    "count": 0,
                    "error": "Could not build similarity search query"
                }

            # Build search query
            search_query = " OR ".join(search_terms)
            # Exclude the original article
            search_query += f" NOT {pmid}[PMID]"

            logger.info(f"Similarity search query: {search_query}")

            # Step 3: Use esearch to find similar articles
            search_params = {
                "db": "pubmed",
                "term": search_query,
                "retmode": "json",
                "retmax": retmax,
                "sort": "relevance",  # Sort by relevance for better similarity
                "usehistory": "y"
            }

            search_response = await self._make_request(f"{NCBI_BASE_URL}/esearch.fcgi", search_params)
            search_data = search_response.json()

            if "esearchresult" not in search_data:
                return {
                    "reference_pmid": pmid,
                    "similar_articles": [],
                    "count": 0,
                    "error": "Invalid search response"
                }

            result = search_data["esearchresult"]
            similar_pmids = result.get("idlist", [])

            if not similar_pmids:
                return {
                    "reference_pmid": pmid,
                    "similar_articles": [],
                    "count": 0,
                    "error": "No similar articles found"
                }

            # similar_pmids are already limited by retmax in esearch
            # Step 4: Get metadata for similar articles using esummary
            summary_params = {
                "db": "pubmed",
                "id": ",".join(similar_pmids),
                "retmode": "json"
            }

            summary_response = await self._make_request(f"{NCBI_BASE_URL}/esummary.fcgi", summary_params)
            summary_data = summary_response.json()

            # Process results
            similar_articles = []
            if "result" in summary_data:
                for pmid_id in similar_pmids:
                    if pmid_id in summary_data["result"]:
                        paper = summary_data["result"][pmid_id]

                        # Extract PMCID from articleids if available
                        pmcid = None
                        if "articleids" in paper:
                            for article_id in paper["articleids"]:
                                if article_id.get("idtype") == "pmc":
                                    pmcid = article_id.get("value")
                                    break

                        similar_articles.append({
                            "pmid": pmid_id,
                            "pmcid": pmcid,
                            "title": paper.get("title", "No title available"),
                            "authors": [author.get("name", "") for author in paper.get("authors", [])],
                            "journal": paper.get("fulljournalname", paper.get("source", "Unknown journal")),
                            "pubdate": paper.get("pubdate", "Unknown"),
                            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid_id}/",
                            "full_text_available": pmcid is not None
                        })

            return {
                "reference_pmid": pmid,
                "similar_articles": similar_articles,
                "count": len(similar_articles),
                "error": None
            }

        except Exception as e:
            logger.error(f"Failed to find similar articles for PMID {pmid}: {e}")
            return {
                "reference_pmid": pmid,
                "similar_articles": [],
                "count": 0,
                "error": str(e)
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

                # Extract DOI
                doi = None
                for article_id in article.findall(".//ArticleId"):
                    if article_id.get("IdType") == "doi":
                        doi = article_id.text
                        break

                items.append({
                    "pmid": pmid,
                    "title": title,
                    "abstract": abstract,
                    "journal": journal,
                    "year": year,
                    "authors": authors,
                    "doi": doi
                })
            
            return items
            
        except ET.ParseError as e:
            logger.error(f"XML parsing error: {e}")
            raise PubMedAPIError(f"Failed to parse XML response: {e}")
    
    def _parse_jats_body(self, jats_xml: str) -> Dict[str, Any]:
        """Parse JATS XML to extract body text content only (excluding front metadata)"""
        try:
            if not jats_xml or "does not allow downloading" in jats_xml:
                return {
                    "body_text": None,
                    "sections": [],
                    "error": "Full text not available due to publisher restrictions"
                }

            root = ET.fromstring(jats_xml)

            # JATS XML structure: pmc-articleset > article > body
            # We only want the body element, not front (metadata)
            article = root.find('.//article')
            if article is None:
                # Try direct body search if article element is not found
                body = root.find('.//body')
            else:
                # Standard JATS path: article > body
                body = article.find('.//body')

            if body is None:
                return {
                    "body_text": None,
                    "sections": [],
                    "error": "No body element found in JATS XML"
                }

            def extract_text_from_element(element):
                """Recursively extract all text from an element and its children"""
                text_parts = []
                if element.text:
                    text_parts.append(element.text.strip())
                for child in element:
                    text_parts.extend(extract_text_from_element(child))
                    if child.tail:
                        text_parts.append(child.tail.strip())
                return [t for t in text_parts if t]

            # Extract sections from body only
            sections = []
            # Direct children sections of body
            for sec in body.findall('./sec'):
                # Get section title
                title_elem = sec.find('./title')
                title = title_elem.text.strip() if title_elem is not None and title_elem.text else "Untitled Section"

                # Get paragraphs directly in this section
                paragraphs = sec.findall('./p')
                section_text_parts = []
                for p in paragraphs:
                    p_text = extract_text_from_element(p)
                    if p_text:
                        section_text_parts.append(" ".join(p_text))

                # Also check for nested subsections
                for subsec in sec.findall('.//sec'):
                    subsec_title = subsec.find('./title')
                    if subsec_title is not None and subsec_title.text:
                        section_text_parts.append(f"\n{subsec_title.text.strip()}:")
                    for p in subsec.findall('./p'):
                        p_text = extract_text_from_element(p)
                        if p_text:
                            section_text_parts.append(" ".join(p_text))

                section_text = "\n\n".join(section_text_parts)

                if section_text:  # Only add sections with actual content
                    sections.append({
                        "title": title,
                        "text": section_text
                    })

            # Extract all body text (excluding front metadata)
            all_body_text = extract_text_from_element(body)
            full_body_text = " ".join(all_body_text)

            return {
                "body_text": full_body_text,
                "sections": sections,
                "error": None
            }
            
        except ET.ParseError as e:
            return {
                "body_text": None,
                "sections": [],
                "error": f"XML parsing error: {str(e)}"
            }
        except Exception as e:
            return {
                "body_text": None,
                "sections": [],
                "error": f"Error parsing JATS XML: {str(e)}"
            }

    async def get_full_text(self, pmcid: str) -> Dict[str, Any]:
        """Get full text for a single PMCID using efetch and OA service"""
        if not pmcid:
            return {
                "pmcid": None,
                "sections": [],
                "parsing_error": None,
                "pdf_url": None,
                "status": "error",
                "error": "No PMCID provided"
            }

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

            # Parse JATS XML to extract body text
            parsed_body = self._parse_jats_body(jats_xml)

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

            return {
                "pmcid": full_pmcid,
                "sections": parsed_body["sections"],
                "parsing_error": parsed_body["error"],
                "pdf_url": pdf_url,
                "status": "success"
            }

        except Exception as e:
            logger.error(f"Failed to fetch full text for {full_pmcid}: {e}")
            return {
                "pmcid": full_pmcid,
                "sections": [],
                "parsing_error": None,
                "pdf_url": None,
                "status": "error",
                "error": str(e)
            }

    async def get_citation_counts(self, pmids: List[str]) -> List[Dict[str, Any]]:
        """Get citation counts for PMIDs using NIH iCite API

        Args:
            pmids: List of PubMed IDs (PMIDs)

        Returns:
            List of dictionaries containing PMID and citation_count only
        """
        if not pmids:
            return []

        # iCite API accepts up to 1000 PMIDs at once
        pmids_str = ",".join(pmids[:1000])

        try:
            logger.info(f"Fetching citation counts for {len(pmids[:1000])} PMIDs from iCite")

            # iCite API doesn't use NCBI rate limiter, so we make direct request
            response = await self.session.get(
                ICITE_API_URL,
                params={"pmids": pmids_str, "format": "json"},
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()

            # Extract only PMID and citation_count from response
            results = []
            for item in data.get("data", []):
                pmid = str(item.get("pmid", ""))
                citation_count = item.get("citation_count")

                result = {"pmid": pmid}

                if citation_count is not None:
                    result["citation_count"] = citation_count
                else:
                    result["citation_count"] = None
                    result["note"] = "Citation data not available"

                results.append(result)

            return results

        except httpx.HTTPStatusError as e:
            logger.error(f"iCite API HTTP error: {e}")
            # Return error info for all PMIDs
            return [
                {"pmid": pmid, "citation_count": None, "error": f"HTTP error: {e.response.status_code}"}
                for pmid in pmids
            ]
        except Exception as e:
            logger.error(f"Failed to fetch citation counts: {e}")
            # Return error info for all PMIDs
            return [
                {"pmid": pmid, "citation_count": None, "error": str(e)}
                for pmid in pmids
            ]


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
    async def search(query: str, retmax: int = 50, sort: str = "relevance") -> str:
        """
        Search PubMed database with MeSH support and sorting options.

        Args:
            query: Search query string. Supports MeSH terms (e.g., "asthma[mh] AND adult[mh]")
            retmax: Maximum number of results to return (default: 50, max: 200)
            sort: Sort order - "relevance" for Best Match (ML-based), "pub_date" for Most Recent (default: "relevance")

        Returns:
            JSON string containing search results with paper metadata
        """
        if not query or not query.strip():
            empty_result = {"results": []}
            return json.dumps(empty_result)

        # Validate and constrain retmax parameter
        if retmax < 1:
            retmax = 1
        elif retmax > 200:
            retmax = 200

        # Validate sort parameter
        if sort not in ["relevance", "pub_date"]:
            raise ValueError(f"Invalid sort parameter: {sort}. Use 'relevance' for Best Match or 'pub_date' for Most Recent.")

        async with PubMedClient() as client:
            try:
                # Use search with PMCID detection from esummary articleids
                results = await client.search_pubmed(query, retmax=retmax, retstart=0, sort=sort)
                logger.info(f"Search returned {len(results['items'])} of {retmax} requested results for query: {query} (sort: {sort})")
                
                # Transform to OpenAI MCP format with PMCID info
                search_results = []
                for item in results['items']:
                    result_item = {
                        "id": item['pmid'],
                        "title": item['title'],
                        "url": f"https://pubmed.ncbi.nlm.nih.gov/{item['pmid']}/"
                    }
                    
                    # Add PMCID and full_text_available if present
                    if item.get('pmcid'):
                        result_item['pmcid'] = item['pmcid']
                        result_item['full_text_available'] = True
                    else:
                        result_item['full_text_available'] = False
                    
                    search_results.append(result_item)
                
                mcp_result = {"results": search_results}
                return json.dumps(mcp_result)
                
            except Exception as e:
                logger.error(f"Search failed: {e}")
                raise ValueError(f"Search failed: {str(e)}")
    
    @mcp.tool()
    async def fetch(id: str) -> str:
        """
        Retrieve abstract for a single PMID (OpenAI MCP compliant).
        
        This tool is designed to comply with OpenAI MCP specification and
        processes exactly one PMID per request. For multiple PMIDs, use fetch_batch.
        
        Args:
            id: Single PubMed ID (PMID) as string - NO ARRAYS OR COMMA-SEPARATED VALUES
        
        Returns:
            JSON string containing document with id, title, text, url, and metadata
        """
        if not id or not id.strip():
            raise ValueError("Single document ID is required")
        
        pmid = id.strip()
        
        # Validate that it's a single PMID (no commas, no array-like input)
        if ',' in pmid or '[' in pmid or ']' in pmid:
            raise ValueError("fetch tool accepts only a single PMID. Use fetch_batch for multiple PMIDs.")
        
        async with PubMedClient() as client:
            try:
                abstracts = await client.get_abstracts([pmid])
                logger.info(f"Retrieved abstract for single PMID: {pmid}")
                
                if not abstracts:
                    raise ValueError(f"No abstract found for PMID: {pmid}")
                
                # Get the first (and only) abstract
                abstract_data = abstracts[0]
                
                # Transform to OpenAI MCP format
                document = {
                    "id": pmid,
                    "title": abstract_data.get("title", "No title available"),
                    "text": abstract_data.get("abstract", "No abstract available"),
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    "metadata": {
                        "journal": abstract_data.get("journal", "Unknown journal"),
                        "year": abstract_data.get("year", "Unknown"),
                        "authors": abstract_data.get("authors", [])
                    }
                }
                
                return json.dumps(document)
                
            except Exception as e:
                logger.error(f"Abstract retrieval failed for PMID {pmid}: {e}")
                raise ValueError(f"Abstract retrieval failed: {str(e)}")
    
    @mcp.tool()
    async def fetch_batch(pmids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Retrieve abstracts for multiple PMIDs in a single batch request.
        
        This tool is optimized for processing multiple PMIDs efficiently
        and returns results in a structured format for batch operations.
        
        Args:
            pmids: List of PubMed IDs (PMIDs) as strings
        
        Returns:
            Dictionary with 'items' containing abstract data for each PMID
        """
        if not pmids:
            return {"items": []}
        
        # Remove duplicates and validate PMIDs
        unique_pmids = list(set(str(pmid).strip() for pmid in pmids if str(pmid).strip()))
        
        if not unique_pmids:
            return {"items": []}
        
        async with PubMedClient() as client:
            try:
                abstracts = await client.get_abstracts(unique_pmids)
                logger.info(f"Retrieved {len(abstracts)} abstracts for {len(unique_pmids)} PMIDs in batch")
                return {"items": abstracts}
            except Exception as e:
                logger.error(f"Batch abstract retrieval failed: {e}")
                raise ValueError(f"Batch abstract retrieval failed: {str(e)}")
    
    @mcp.tool()
    async def get_full_text(pmcid: str) -> Dict[str, Any]:
        """
        Retrieve full text content for a single PMCID.

        Args:
            pmcid: PMC ID (PMCID, with or without 'PMC' prefix)

        Returns:
            Dictionary with sections array containing title and text for each section
        """
        if not pmcid:
            return {
                "pmcid": None,
                "sections": [],
                "parsing_error": "No PMCID provided",
                "pdf_url": None,
                "status": "error",
                "error": "No PMCID provided"
            }
        
        # Clean PMCID format
        clean_pmcid = str(pmcid).strip()
        
        async with PubMedClient() as client:
            try:
                result = await client.get_full_text(clean_pmcid)
                logger.info(f"Retrieved full text for {result.get('pmcid', clean_pmcid)} - Status: {result.get('status')}")
                
                return result
                
            except Exception as e:
                logger.error(f"Full text retrieval failed for {clean_pmcid}: {e}")
                return {
                    "pmcid": clean_pmcid,
                    "sections": [],
                    "parsing_error": None,
                    "pdf_url": None,
                    "status": "error",
                    "error": str(e)
                }

    @mcp.tool()
    async def find_similar_articles(pmid: str, retmax: int = 20) -> Dict[str, Any]:
        """
        Find similar articles for a given PMID using PubMed's recommendation algorithm.

        This tool uses NCBI's elink API to find articles that are computationally similar
        to the reference article. The similarity is based on words from the title and
        abstract, MeSH terms, and journal information.

        Args:
            pmid: PubMed ID of the reference article
            retmax: Maximum number of similar articles to return (default: 20, max: 100)

        Returns:
            Dictionary containing similar articles with metadata including titles, authors,
            journals, publication dates, and full-text availability
        """
        if not pmid or not pmid.strip():
            return {
                "reference_pmid": None,
                "similar_articles": [],
                "count": 0,
                "error": "No PMID provided"
            }

        # Validate PMID format (basic check)
        clean_pmid = pmid.strip()
        if not clean_pmid.isdigit():
            return {
                "reference_pmid": clean_pmid,
                "similar_articles": [],
                "count": 0,
                "error": "Invalid PMID format. PMID should be a numeric string."
            }

        # Validate and constrain retmax parameter
        if retmax < 1:
            retmax = 1
        elif retmax > 100:
            retmax = 100

        async with PubMedClient() as client:
            try:
                result = await client.find_similar_articles(clean_pmid, retmax)
                logger.info(f"Found {result['count']} similar articles for PMID: {clean_pmid}")
                return result

            except Exception as e:
                logger.error(f"Similar articles search failed for PMID {clean_pmid}: {e}")
                return {
                    "reference_pmid": clean_pmid,
                    "similar_articles": [],
                    "count": 0,
                    "error": str(e)
                }

    @mcp.tool()
    async def count(query: str) -> str:
        """
        Get only the count of search results for query adjustment and optimization.

        This tool is designed for quickly checking how many papers match a query
        without retrieving the actual results. Useful for refining search strategies
        and testing different query combinations.

        Args:
            query: Search query string. Supports MeSH terms and all PubMed search syntax.

        Returns:
            JSON string containing:
            - query: The original query
            - count: Number of matching papers
            - query_translation: How PubMed interpreted the query (useful for debugging)
            - warnings: Any search warnings (e.g., ignored phrases)

        Example queries:
            - "cancer" - Very broad search
            - "lung cancer[mh]" - MeSH term search
            - "COVID-19[tiab] AND 2024[dp]" - Title/Abstract with date filter
            - "clinical trial[pt] AND diabetes[majr]" - Publication type with major topic
        """
        if not query or not query.strip():
            return json.dumps({
                "query": query,
                "count": 0,
                "query_translation": "",
                "warnings": []
            })

        async with PubMedClient() as client:
            try:
                result = await client.count_search(query)
                logger.info(f"Count for '{query}': {result['count']} results")
                return json.dumps(result)

            except Exception as e:
                logger.error(f"Count search failed: {e}")
                raise ValueError(f"Count search failed: {str(e)}")

    @mcp.tool()
    async def export_to_ris(pmids: List[str]) -> str:
        """
        Export PubMed articles to RIS format for citation managers (EndNote/Zotero/Mendeley).

        Returns compact RIS format with minimal metadata (PMID, title, first author, journal, year, DOI).
        Citation managers will auto-fetch complete metadata from PubMed using the PMID.

        Args:
            pmids: List of PubMed IDs (PMIDs) as strings

        Returns:
            RIS formatted text. Copy the output and save as .ris file for import.
        """
        if not pmids:
            return "Error: No PMIDs provided"

        # Remove duplicates and validate PMIDs
        unique_pmids = list(set(str(pmid).strip() for pmid in pmids if str(pmid).strip()))

        if not unique_pmids:
            return "Error: No valid PMIDs provided"

        async with PubMedClient() as client:
            try:
                # Fetch metadata for all PMIDs
                abstracts = await client.get_abstracts(unique_pmids)

                if not abstracts:
                    return f"Error: Could not retrieve data for PMIDs: {', '.join(unique_pmids)}"

                # Convert to RIS format
                ris_text = RISExporter.export_multiple_to_ris(abstracts)

                # Add user-friendly instructions with mandatory note
                header = (
                    f"📄 RIS Export Complete ({len(abstracts)} articles)\n\n"
                    "⚠️ IMPORTANT: This RIS file contains minimal metadata (PMID, title, first author only, journal, year, DOI).\n"
                    "Please use your citation manager (EndNote/Zotero/Mendeley) to retrieve complete information from PubMed.\n\n"
                    "Copy the text below and save as 'references.ris':\n\n"
                    "```ris\n"
                )
                footer = (
                    "```\n\n"
                    "✅ Ready for import into EndNote/Zotero/Mendeley\n"
                    "📝 After import, use your citation manager's \"Update from PubMed\" feature to fetch full author lists and abstracts"
                )

                logger.info(f"Exported {len(abstracts)} articles to RIS format")
                return f"{header}{ris_text}{footer}"

            except Exception as e:
                logger.error(f"RIS export failed: {e}")
                return f"Error: RIS export failed - {str(e)}"

    @mcp.tool()
    async def get_citation_counts(pmids: List[str]) -> Dict[str, Any]:
        """
        Get citation counts for PMIDs using NIH iCite API.

        This tool retrieves only the citation count for each PMID.
        The iCite database provides citation data based on PubMed Central references.

        Args:
            pmids: List of PubMed IDs (PMIDs) as strings (max 1000 per request)

        Returns:
            Dictionary with items array containing pmid and citation_count
            Example: {"items": [{"pmid": "12345678", "citation_count": 26}]}
        """
        if not pmids:
            return {"items": []}

        # Remove duplicates and validate PMIDs
        unique_pmids = list(set(str(pmid).strip() for pmid in pmids if str(pmid).strip()))

        if not unique_pmids:
            return {"items": []}

        async with PubMedClient() as client:
            try:
                results = await client.get_citation_counts(unique_pmids)
                logger.info(f"Retrieved citation counts for {len(results)} PMIDs")
                return {"items": results}

            except Exception as e:
                logger.error(f"Citation count retrieval failed: {e}")
                raise ValueError(f"Citation count retrieval failed: {str(e)}")


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