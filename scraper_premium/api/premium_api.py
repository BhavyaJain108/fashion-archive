"""
Premium Scraper API
==================

Flask API endpoints for premium brand scraping functionality.
"""

from flask import jsonify, request
import os
import sys
import json
import time
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional
import traceback
from pathlib import Path

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ..tests.test_full_pipeline import test_full_brand_scrape
from ..brand import Brand
from ..page_extractor import extract_products_from_page


class ScrapingJob:
    """Represents an ongoing scraping job with status tracking"""
    
    def __init__(self, job_id: str, brand_url: str, brand_name: str):
        self.job_id = job_id
        self.brand_url = brand_url
        self.brand_name = brand_name
        self.status = "initializing"
        self.progress = 0
        self.total_products = 0
        self.categories_processed = 0
        self.total_categories = 0
        self.error = None
        self.result = None
        self.start_time = datetime.now()
        self.end_time = None
        self.current_action = "Starting scrape..."
        self.products = []
        self.results_dir = None
        
    def to_dict(self) -> Dict[str, Any]:
        """Convert job to dictionary for API response"""
        elapsed_time = None
        if self.end_time:
            elapsed_time = (self.end_time - self.start_time).total_seconds()
        elif self.status == "running":
            elapsed_time = (datetime.now() - self.start_time).total_seconds()
            
        return {
            "job_id": self.job_id,
            "brand_url": self.brand_url,
            "brand_name": self.brand_name,
            "status": self.status,
            "progress": self.progress,
            "total_products": self.total_products,
            "categories_processed": self.categories_processed,
            "total_categories": self.total_categories,
            "current_action": self.current_action,
            "error": self.error,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "elapsed_time": round(elapsed_time, 2) if elapsed_time else None,
            "products_preview": self.products[:10] if self.products else [],
            "results_dir": self.results_dir
        }


class PremiumScraperAPI:
    """API class for premium scraper endpoints"""
    
    def __init__(self):
        self.scraping_jobs = {}
        self.job_lock = threading.Lock()
    
    def _run_scraping_job(self, job: ScrapingJob):
        """Run the scraping job in a background thread"""
        try:
            job.status = "running"
            job.current_action = "Analyzing brand navigation..."
            
            # Call the premium scraper
            result = test_full_brand_scrape(
                brand_url=job.brand_url,
                brand_name=job.brand_name
            )
            
            if result.get("success"):
                job.status = "completed"
                job.result = result
                job.total_products = result.get("total_products", 0)
                job.products = result.get("products", [])
                job.categories_processed = result.get("successful_categories", 0)
                job.total_categories = result.get("total_categories", 0)
                job.results_dir = result.get("results_dir")
                job.progress = 100
                job.current_action = f"Completed! Scraped {job.total_products} products from {job.categories_processed} categories"
            else:
                job.status = "failed"
                job.error = result.get("error", "Unknown error occurred")
                job.current_action = f"Failed: {job.error}"
                
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            job.current_action = f"Error: {str(e)}"
            traceback.print_exc()
            
        finally:
            job.end_time = datetime.now()
    
    def start_scrape(self) -> tuple:
        """
        Start a premium scraping job for a brand
        
        Returns:
            Tuple of (response_dict, status_code)
        """
        try:
            data = request.get_json()
            brand_url = data.get('brand_url', '').strip()
            brand_name = data.get('brand_name', '').strip() or None
            
            if not brand_url:
                return {
                    'success': False,
                    'message': 'Brand URL is required'
                }, 400
            
            # Validate URL format
            if not brand_url.startswith(('http://', 'https://')):
                brand_url = f'https://{brand_url}'
            
            # Generate unique job ID
            job_id = f"scrape_{int(time.time() * 1000)}"
            
            # Create scraping job
            job = ScrapingJob(job_id, brand_url, brand_name or "Unknown Brand")
            
            with self.job_lock:
                self.scraping_jobs[job_id] = job
            
            # Start scraping in background thread
            thread = threading.Thread(target=self._run_scraping_job, args=(job,))
            thread.daemon = True
            thread.start()
            
            return {
                'success': True,
                'message': 'Scraping job started successfully',
                'job_id': job_id,
                'job': job.to_dict()
            }, 200
            
        except Exception as e:
            traceback.print_exc()
            return {
                'success': False,
                'message': f'Error starting scrape: {str(e)}'
            }, 500
    
    def get_job_status(self, job_id: str) -> tuple:
        """
        Get the status of a scraping job
        
        Returns:
            Tuple of (response_dict, status_code)
        """
        try:
            with self.job_lock:
                job = self.scraping_jobs.get(job_id)
            
            if not job:
                return {
                    'success': False,
                    'message': 'Job not found'
                }, 404
            
            return {
                'success': True,
                'job': job.to_dict()
            }, 200
            
        except Exception as e:
            return {
                'success': False,
                'message': f'Error getting job status: {str(e)}'
            }, 500
    
    def get_job_products(self, job_id: str) -> tuple:
        """
        Get the products from a completed scraping job with pagination
        
        Returns:
            Tuple of (response_dict, status_code)
        """
        try:
            with self.job_lock:
                job = self.scraping_jobs.get(job_id)
            
            if not job:
                return {
                    'success': False,
                    'message': 'Job not found'
                }, 404
            
            if job.status != "completed":
                return {
                    'success': False,
                    'message': f'Job is {job.status}, not completed'
                }, 400
            
            # Get pagination parameters
            page = int(request.args.get('page', 1))
            per_page = int(request.args.get('per_page', 50))
            
            # Calculate pagination
            total_products = len(job.products)
            start_idx = (page - 1) * per_page
            end_idx = start_idx + per_page
            
            products_page = job.products[start_idx:end_idx]
            
            return {
                'success': True,
                'products': products_page,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total': total_products,
                    'total_pages': (total_products + per_page - 1) // per_page
                },
                'job_info': {
                    'job_id': job_id,
                    'brand_name': job.brand_name,
                    'brand_url': job.brand_url,
                    'total_products': job.total_products,
                    'categories_processed': job.categories_processed
                }
            }, 200
            
        except Exception as e:
            return {
                'success': False,
                'message': f'Error getting products: {str(e)}'
            }, 500
    
    def download_results(self, job_id: str):
        """
        Download the CSV results of a completed scraping job
        
        Returns:
            File response or error tuple
        """
        try:
            with self.job_lock:
                job = self.scraping_jobs.get(job_id)
            
            if not job:
                return jsonify({
                    'success': False,
                    'message': 'Job not found'
                }), 404
            
            if job.status != "completed":
                return jsonify({
                    'success': False,
                    'message': f'Job is {job.status}, not completed'
                }), 400
            
            # Get the results directory from the job
            if job.results_dir:
                # Find the CSV file
                brand_slug = job.brand_name.lower().replace(' ', '_').replace('-', '_')
                csv_path = os.path.join(job.results_dir, f"{brand_slug}_products.csv")
                
                if os.path.exists(csv_path):
                    from flask import send_file
                    return send_file(
                        csv_path,
                        as_attachment=True,
                        download_name=f"{brand_slug}_products_{job.job_id}.csv",
                        mimetype='text/csv'
                    )
                else:
                    return jsonify({
                        'success': False,
                        'message': 'Results file not found'
                    }), 404
            else:
                return jsonify({
                    'success': False,
                    'message': 'No results directory found'
                }), 404
                
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'Error downloading results: {str(e)}'
            }), 500
    
    def list_jobs(self) -> tuple:
        """
        List all scraping jobs
        
        Returns:
            Tuple of (response_dict, status_code)
        """
        try:
            with self.job_lock:
                jobs = [job.to_dict() for job in self.scraping_jobs.values()]
            
            # Sort by start time, newest first
            jobs.sort(key=lambda x: x['start_time'], reverse=True)
            
            # Filter by status if requested
            status_filter = request.args.get('status')
            if status_filter:
                jobs = [j for j in jobs if j['status'] == status_filter]
            
            return {
                'success': True,
                'jobs': jobs,
                'total': len(jobs),
                'stats': {
                    'running': len([j for j in jobs if j['status'] == 'running']),
                    'completed': len([j for j in jobs if j['status'] == 'completed']),
                    'failed': len([j for j in jobs if j['status'] == 'failed'])
                }
            }, 200
            
        except Exception as e:
            return {
                'success': False,
                'message': f'Error listing jobs: {str(e)}'
            }, 500
    
    def analyze_brand(self) -> tuple:
        """
        Analyze a brand website to check if it can be scraped
        
        Returns:
            Tuple of (response_dict, status_code)
        """
        try:
            data = request.get_json()
            brand_url = data.get('brand_url', '').strip()
            
            if not brand_url:
                return {
                    'success': False,
                    'message': 'Brand URL is required'
                }, 400
            
            # Validate URL format
            if not brand_url.startswith(('http://', 'https://')):
                brand_url = f'https://{brand_url}'
            
            # Create a Brand instance to analyze
            brand = Brand(brand_url)

            # Extract links from homepage with menu expansion
            links = brand.extract_page_links_with_context(brand_url, expand_navigation_menus=True)
            
            if not links:
                return {
                    'success': False,
                    'message': 'Could not extract links from the website',
                    'is_scrapable': False
                }, 200
            
            # Get navigation prompt and model from centralized prompts
            from prompts import PromptManager
            prompt_data = PromptManager.get_navigation_analysis_prompt(brand.url, links)
            llm_response = brand.llm_handler.call(prompt_data['prompt'], expected_format="json", response_model=prompt_data['model'])
            
            if not llm_response.get("success", False):
                return {
                    'success': False,
                    'message': 'Could not analyze website navigation',
                    'is_scrapable': False
                }, 200
            
            analysis = llm_response.get("data", {})
            included_urls = analysis.get("included_urls", [])
            
            # Extract category names
            categories = []
            for url_obj in included_urls[:5]:  # First 5 categories
                if isinstance(url_obj, dict):
                    categories.append(url_obj.get("category", "Unknown"))
                else:
                    categories.append("Product Page")
            
            return {
                'success': True,
                'is_scrapable': len(included_urls) > 0,
                'analysis': {
                    'category_pages_found': len(included_urls),
                    'categories': categories,
                    'confidence': 'high' if len(included_urls) > 3 else 'medium' if len(included_urls) > 0 else 'low',
                    'estimated_time': len(included_urls) * 5  # Rough estimate: 5 seconds per category
                },
                'message': f'Found {len(included_urls)} product category pages'
            }, 200
            
        except Exception as e:
            traceback.print_exc()
            return {
                'success': False,
                'message': f'Error analyzing brand: {str(e)}',
                'is_scrapable': False
            }, 500