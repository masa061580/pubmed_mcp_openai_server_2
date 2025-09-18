#!/usr/bin/env python3
"""
Test script for search count functionality
"""

import asyncio
import json
import logging
from pubmed_mcp_server import PubMedClient

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_count_search():
    """Test basic count search functionality"""
    print("Testing Count Search Functionality")
    print("=" * 80)
    
    async with PubMedClient() as client:
        # Test queries with expected different counts
        test_queries = [
            ("cancer", "Very broad query"),
            ("lung cancer", "More specific"),
            ("lung cancer[mh]", "MeSH term"),
            ("lung cancer[mh] AND 2024[dp]", "With date filter"),
            ("lung cancer[majr] AND clinical trial[pt] AND 2024[dp]", "Complex query"),
            ("COVID-19 vaccine", "Recent topic"),
            ("asdfghjklzxcvbnm", "Should return 0 results"),
        ]
        
        print("\nSingle Query Tests:")
        print("-" * 50)
        
        for query, description in test_queries:
            try:
                result = await client.count_search(query)
                print(f"\nQuery: {query}")
                print(f"Description: {description}")
                print(f"Count: {result['count']:,} papers")
                
                # Show query translation if different from original
                if result['query_translation'] and result['query_translation'] != query:
                    print(f"PubMed Translation: {result['query_translation'][:100]}...")
                
                if result.get('warnings'):
                    print(f"Warnings: {result['warnings']}")
                    
            except Exception as e:
                print(f"[ERROR] Failed for query '{query}': {e}")


async def test_count_batch():
    """Test batch count functionality"""
    print("\n" + "=" * 80)
    print("Testing Batch Count Functionality")
    print("-" * 50)
    
    async with PubMedClient() as client:
        # Compare different search strategies
        diabetes_queries = [
            "diabetes",
            "diabetes[mh]",
            "diabetes[majr]",
            "diabetes[tiab]",
            "diabetes AND clinical trial[pt]",
            "diabetes[mh] AND review[pt] AND 2023:2024[dp]"
        ]
        
        try:
            results = await client.count_batch(diabetes_queries)
            
            print("\nDiabetes Search Strategy Comparison:")
            print("-" * 30)
            for result in results:
                if 'error' not in result:
                    print(f"Query: {result['query']}")
                    print(f"  Count: {result['count']:,} papers")
                else:
                    print(f"Query: {result['query']}")
                    print(f"  Error: {result['error']}")
            
        except Exception as e:
            print(f"[ERROR] Batch count failed: {e}")


async def test_query_refinement():
    """Demonstrate query refinement workflow"""
    print("\n" + "=" * 80)
    print("Query Refinement Workflow Example")
    print("-" * 50)
    
    async with PubMedClient() as client:
        base_query = "breast cancer"
        refinements = [
            "",
            " AND treatment",
            " AND treatment AND 2024[dp]",
            " AND treatment AND clinical trial[pt] AND 2024[dp]",
            "[mh] AND immunotherapy[tiab] AND 2023:2024[dp]"
        ]
        
        print(f"\nRefining query: '{base_query}'")
        print("-" * 30)
        
        for refinement in refinements:
            if refinement:
                if refinement.startswith("["):
                    query = base_query + refinement
                else:
                    query = base_query + refinement
            else:
                query = base_query
                
            try:
                result = await client.count_search(query)
                count = result['count']
                
                # Show refinement progress
                if count > 10000:
                    status = "[TOO BROAD]"
                elif count > 1000:
                    status = "[BROAD]"
                elif count > 100:
                    status = "[GOOD]"
                elif count > 10:
                    status = "[FOCUSED]"
                elif count > 0:
                    status = "[VERY SPECIFIC]"
                else:
                    status = "[NO RESULTS]"
                
                print(f"{count:8,} results {status:15} - {query}")
                
            except Exception as e:
                print(f"[ERROR] Failed for query '{query}': {e}")


async def test_mesh_vs_text_search():
    """Compare MeSH term search vs text search"""
    print("\n" + "=" * 80)
    print("MeSH vs Text Search Comparison")
    print("-" * 50)
    
    async with PubMedClient() as client:
        comparisons = [
            ("hypertension", "hypertension[mh]", "hypertension[majr]"),
            ("myocardial infarction", "myocardial infarction[mh]", "heart attack"),
            ("neoplasms", "cancer", "cancer[mh]")
        ]
        
        for terms in comparisons:
            print(f"\nComparing: {terms[0]}")
            queries = list(terms)
            
            try:
                results = await client.count_batch(queries)
                for result in results:
                    if 'error' not in result:
                        print(f"  '{result['query']}': {result['count']:,} papers")
            except Exception as e:
                print(f"[ERROR] Comparison failed: {e}")


if __name__ == "__main__":
    print("Search Count Testing Suite")
    print("=" * 80)
    
    # Run all tests
    asyncio.run(test_count_search())
    asyncio.run(test_count_batch())
    asyncio.run(test_query_refinement())
    asyncio.run(test_mesh_vs_text_search())
    
    print("\n" + "=" * 80)
    print("All count tests completed!")