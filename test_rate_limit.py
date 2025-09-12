#!/usr/bin/env python3
"""
Rate Limit Test Script for PubMed MCP Server

This script tests that the rate limiting is working correctly by making
multiple rapid requests and measuring the timing.
"""

import asyncio
import time
import logging
from pubmed_mcp_server import PubMedClient, MAX_REQUESTS_PER_SECOND

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_rate_limiting():
    """Test rate limiting by making rapid requests"""
    print(f"🧪 Testing Rate Limiting: {MAX_REQUESTS_PER_SECOND} requests/second")
    print("=" * 60)
    
    async with PubMedClient() as client:
        # Test making requests rapidly
        num_requests = 10
        request_times = []
        
        print(f"Making {num_requests} rapid requests...")
        start_time = time.time()
        
        for i in range(num_requests):
            request_start = time.time()
            
            try:
                # Make a simple search request
                results = await client.search_pubmed("test", retmax=1)
                request_end = time.time()
                
                elapsed = request_end - request_start
                total_elapsed = request_end - start_time
                
                request_times.append({
                    'request_num': i + 1,
                    'request_time': elapsed,
                    'total_elapsed': total_elapsed
                })
                
                print(f"Request {i+1}: {elapsed:.3f}s (total: {total_elapsed:.3f}s)")
                
            except Exception as e:
                print(f"Request {i+1} failed: {e}")
        
        total_time = time.time() - start_time
        actual_rate = num_requests / total_time
        
        print("\n" + "=" * 60)
        print("📊 Rate Limiting Analysis")
        print("=" * 60)
        print(f"Total requests: {num_requests}")
        print(f"Total time: {total_time:.3f} seconds")
        print(f"Actual rate: {actual_rate:.2f} requests/second")
        print(f"Target rate: {MAX_REQUESTS_PER_SECOND} requests/second")
        print(f"Rate compliance: {'✅ PASS' if actual_rate <= MAX_REQUESTS_PER_SECOND * 1.1 else '❌ FAIL'}")
        
        # Check inter-request intervals
        print(f"\n📈 Inter-request Intervals:")
        for i in range(1, len(request_times)):
            interval = request_times[i]['total_elapsed'] - request_times[i-1]['total_elapsed']
            expected_min_interval = 1.0 / MAX_REQUESTS_PER_SECOND
            status = "✅" if interval >= expected_min_interval * 0.9 else "⚠️"
            print(f"  {request_times[i-1]['request_num']} → {request_times[i]['request_num']}: {interval:.3f}s {status}")
        
        return actual_rate <= MAX_REQUESTS_PER_SECOND * 1.1


async def test_concurrent_requests():
    """Test that concurrent requests are also rate limited properly"""
    print(f"\n🔄 Testing Concurrent Rate Limiting")
    print("=" * 60)
    
    async def make_search_request(request_id: int):
        """Make a single search request with timing"""
        start_time = time.time()
        async with PubMedClient() as client:
            try:
                await client.search_pubmed("covid", retmax=1)
                elapsed = time.time() - start_time
                print(f"Concurrent request {request_id}: {elapsed:.3f}s")
                return elapsed
            except Exception as e:
                print(f"Concurrent request {request_id} failed: {e}")
                return None
    
    # Launch 6 concurrent requests (should take at least 2 seconds with 3 req/s)
    num_concurrent = 6
    start_time = time.time()
    
    tasks = [make_search_request(i+1) for i in range(num_concurrent)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    total_time = time.time() - start_time
    expected_min_time = (num_concurrent - 1) / MAX_REQUESTS_PER_SECOND
    
    print(f"\nConcurrent requests completed in {total_time:.3f}s")
    print(f"Expected minimum time: {expected_min_time:.3f}s")
    print(f"Concurrent rate limiting: {'✅ PASS' if total_time >= expected_min_time * 0.9 else '❌ FAIL'}")
    
    return total_time >= expected_min_time * 0.9


async def main():
    """Run all rate limiting tests"""
    print("🚦 PubMed MCP Server Rate Limiting Tests")
    print("=" * 80)
    print(f"Current rate limit: {MAX_REQUESTS_PER_SECOND} requests/second")
    print("=" * 80)
    
    try:
        # Test 1: Sequential requests
        sequential_pass = await test_rate_limiting()
        
        # Test 2: Concurrent requests  
        concurrent_pass = await test_concurrent_requests()
        
        # Summary
        print("\n" + "=" * 80)
        print("🎯 Test Summary")
        print("=" * 80)
        print(f"Sequential rate limiting: {'✅ PASS' if sequential_pass else '❌ FAIL'}")
        print(f"Concurrent rate limiting: {'✅ PASS' if concurrent_pass else '❌ FAIL'}")
        
        if sequential_pass and concurrent_pass:
            print("\n🎉 All rate limiting tests PASSED!")
            print("The server correctly enforces the rate limit.")
        else:
            print("\n⚠️  Some rate limiting tests FAILED!")
            print("The rate limiting may need adjustment.")
            
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())