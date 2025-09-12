#!/usr/bin/env python3
"""
Test script for PubMed MCP Server

This script tests the core functionality of the PubMed MCP server
without requiring a full MCP client setup.
"""

import asyncio
import json
import logging
from typing import List

from pubmed_mcp_server import PubMedClient

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_search(client: PubMedClient, query: str = "COVID-19 AND vaccine", max_results: int = 5):
    """Test the search functionality"""
    print(f"\n{'='*60}")
    print(f"TESTING SEARCH: {query}")
    print(f"{'='*60}")
    
    try:
        results = await client.search_pubmed(query, retmax=max_results)
        
        print(f"Total count: {results['count']}")
        print(f"Retrieved: {len(results['items'])} results")
        print(f"Start index: {results['retstart']}")
        
        for i, item in enumerate(results['items'], 1):
            print(f"\n{i}. PMID: {item['pmid']}")
            print(f"   Title: {item['title'][:100]}...")
            print(f"   Journal: {item['journal']}")
            print(f"   Date: {item['pubdate']}")
            if item['authors']:
                authors_str = ', '.join(item['authors'][:3])
                if len(item['authors']) > 3:
                    authors_str += f" (and {len(item['authors']) - 3} more)"
                print(f"   Authors: {authors_str}")
        
        return [item['pmid'] for item in results['items']]
        
    except Exception as e:
        print(f"❌ Search failed: {e}")
        return []


async def test_fetch(client: PubMedClient, pmids: List[str]):
    """Test the fetch functionality (abstract retrieval)"""
    if not pmids:
        print("\n⚠️  No PMIDs available for abstract testing")
        return []
    
    # Test with first 3 PMIDs
    test_pmids = pmids[:3]
    
    print(f"\n{'='*60}")
    print(f"TESTING FETCH: {len(test_pmids)} PMIDs")
    print(f"{'='*60}")
    
    try:
        abstracts = await client.get_abstracts(test_pmids)
        
        print(f"Retrieved {len(abstracts)} abstracts")
        
        for i, item in enumerate(abstracts, 1):
            print(f"\n{i}. PMID: {item['pmid']}")
            print(f"   Title: {item['title'][:100]}...")
            print(f"   Journal: {item['journal']}")
            print(f"   Year: {item['year']}")
            
            if item['authors']:
                authors_str = ', '.join(item['authors'][:2])
                if len(item['authors']) > 2:
                    authors_str += f" et al."
                print(f"   Authors: {authors_str}")
            
            abstract = item['abstract']
            if len(abstract) > 200:
                abstract = abstract[:200] + "..."
            print(f"   Abstract: {abstract}")
        
        return abstracts
        
    except Exception as e:
        print(f"❌ Abstract retrieval failed: {e}")
        return []


async def test_full_text(client: PubMedClient, pmcids: List[str] = None):
    """Test the full text retrieval functionality"""
    # Use some known PMCIDs for testing if none provided
    if not pmcids:
        pmcids = ["PMC7920322", "PMC8187532", "PMC9999999"]  # Last one should fail
    
    print(f"\n{'='*60}")
    print(f"TESTING FULL TEXT: {len(pmcids)} PMCIDs")
    print(f"{'='*60}")
    
    try:
        full_texts = await client.get_full_text(pmcids)
        
        print(f"Processed {len(full_texts)} PMCIDs")
        
        for i, item in enumerate(full_texts, 1):
            print(f"\n{i}. PMCID: {item['pmcid']}")
            print(f"   Status: {item['status']}")
            
            if item['status'] == 'success':
                print(f"   ✅ JATS XML: {'Available' if item['jats_xml'] else 'Not available'}")
                print(f"   📄 PDF URL: {item['pdf_url'] or 'Not available'}")
                
                if item['jats_xml']:
                    xml_length = len(item['jats_xml'])
                    print(f"   📊 XML length: {xml_length:,} characters")
            else:
                print(f"   ❌ Error: {item.get('error', 'Unknown error')}")
        
        return full_texts
        
    except Exception as e:
        print(f"❌ Full text retrieval failed: {e}")
        return []


async def test_mesh_queries(client: PubMedClient):
    """Test various MeSH query formats"""
    mesh_queries = [
        "asthma[mh]",
        "COVID-19[mh] AND vaccine[mh]",
        "diabetes[mh] AND adult[mh]",
        "cancer[majr]",  # MeSH Major Topic
        "machine learning[tiab]"  # Title/Abstract
    ]
    
    print(f"\n{'='*60}")
    print("TESTING MESH QUERIES")
    print(f"{'='*60}")
    
    for i, query in enumerate(mesh_queries, 1):
        print(f"\n{i}. Testing: {query}")
        try:
            results = await client.search_pubmed(query, retmax=3)
            print(f"   Results: {results['count']} total, showing {len(results['items'])}")
            
            if results['items']:
                first_title = results['items'][0]['title']
                print(f"   First result: {first_title[:60]}...")
            
        except Exception as e:
            print(f"   ❌ Failed: {e}")


async def run_all_tests():
    """Run all tests"""
    print("🧪 Starting PubMed MCP Server Tests")
    print("=" * 80)
    
    async with PubMedClient() as client:
        # Test 1: Basic search
        pmids = await test_search(client)
        
        # Test 2: Fetch (Abstract retrieval)
        abstracts = await test_fetch(client, pmids)
        
        # Test 3: Full text retrieval
        await test_full_text(client)
        
        # Test 4: MeSH queries
        await test_mesh_queries(client)
    
    print(f"\n{'='*80}")
    print("🎉 All tests completed!")
    print("\nTo start the MCP server, run:")
    print("python pubmed_mcp_server.py")
    print("\nServer URL will be: http://localhost:8000/sse/")


async def quick_test():
    """Quick test with minimal output"""
    print("🚀 Quick functionality test...")
    
    async with PubMedClient() as client:
        try:
            # Quick search test
            results = await client.search_pubmed("COVID-19", retmax=2)
            print(f"✅ Search: Found {results['count']} results")
            
            if results['items']:
                pmid = results['items'][0]['pmid']
                
                # Quick fetch test
                abstracts = await client.get_abstracts([pmid])
                print(f"✅ Fetch: Retrieved abstract for PMID {pmid}")
                
                # Quick full text test (with known PMCID)
                full_texts = await client.get_full_text(["PMC7920322"])
                if full_texts and full_texts[0]['status'] == 'success':
                    print("✅ Full text: Retrieved successfully")
                else:
                    print("⚠️  Full text: May require valid PMCID")
            
            print("\n🎉 Quick test passed! Server should work correctly.")
            
        except Exception as e:
            print(f"❌ Quick test failed: {e}")
            print("Please check your environment variables and network connection.")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "quick":
        asyncio.run(quick_test())
    else:
        asyncio.run(run_all_tests())